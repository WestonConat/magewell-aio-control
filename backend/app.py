import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import socket
from typing import Any

import aiohttp
from bs4 import BeautifulSoup
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from .settings_merge import get_bulk_update_settings

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_SUBNET = "127.0.0.1/32"
DEFAULT_ALLOWED_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
OPERATOR_INTENT_HEADER = "X-Magewell-Operator-Intent"
OPERATOR_INTENT_VALUE = "confirmed"


class DeviceSelection(BaseModel):
    ip: str
    magewell_id: str = Field(min_length=1, max_length=128)


class PushUpdateRequest(BaseModel):
    devices: list[DeviceSelection] = Field(min_length=1)
    confirm: bool = False


class VerifyTargetRequest(BaseModel):
    device: DeviceSelection


class CredentialRotationRequest(BaseModel):
    device: DeviceSelection
    confirm: bool = False


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_allowed_network() -> ipaddress.IPv4Network:
    raw_value = os.getenv("ALLOWED_SUBNET", DEFAULT_ALLOWED_SUBNET)
    try:
        network = ipaddress.ip_network(raw_value, strict=False)
    except ValueError as exc:
        raise RuntimeError(f"ALLOWED_SUBNET is invalid: {raw_value}") from exc
    if network.version != 4:
        raise RuntimeError("ALLOWED_SUBNET must be an IPv4 network")
    return network


def get_allowed_origins() -> list[str]:
    raw_value = os.getenv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    return [origin.strip().rstrip("/") for origin in raw_value.split(",") if origin.strip()]


def require_operator_intent(intent: str | None, origin: str | None) -> None:
    """Require an explicit browser intent signal before any device network access."""
    if intent != OPERATOR_INTENT_VALUE:
        raise HTTPException(status_code=403, detail="Explicit operator intent is required.")
    if origin and origin.rstrip("/") not in get_allowed_origins():
        raise HTTPException(status_code=403, detail="Browser origin is not allowed.")


def safe_device_error(exc: BaseException) -> str:
    """Return an actionable error without serializing credential-bearing request URLs."""
    if isinstance(exc, aiohttp.ClientError | TimeoutError):
        return "Device request failed; verify reachability, credentials, and device response."
    return str(exc)


def settings_fingerprint(settings: dict[str, Any]) -> str:
    canonical = json.dumps(settings, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_max_scan_hosts() -> int:
    try:
        value = int(os.getenv("MAX_SCAN_HOSTS", "1024"))
    except ValueError as exc:
        raise RuntimeError("MAX_SCAN_HOSTS must be an integer") from exc
    if value < 1 or value > 4096:
        raise RuntimeError("MAX_SCAN_HOSTS must be between 1 and 4096")
    return value


def get_max_update_devices() -> int:
    try:
        value = int(os.getenv("MAX_UPDATE_DEVICES", "100"))
    except ValueError as exc:
        raise RuntimeError("MAX_UPDATE_DEVICES must be an integer") from exc
    if value < 1 or value > 500:
        raise RuntimeError("MAX_UPDATE_DEVICES must be between 1 and 500")
    return value


def get_device_credentials() -> tuple[str, str]:
    username = os.getenv("MAGEWELL_USERNAME", "").strip()
    password = os.getenv("MAGEWELL_PASSWORD", "")
    if not username or not password:
        raise HTTPException(
            status_code=503,
            detail="Set MAGEWELL_USERNAME and MAGEWELL_PASSWORD before device reads or writes.",
        )
    return username, password


def get_credential_rotation_credentials() -> tuple[str, str, str]:
    username, new_password = get_device_credentials()
    old_password = os.getenv("MAGEWELL_OLD_PASSWORD", "")
    if not old_password:
        raise HTTPException(
            status_code=503,
            detail="Set MAGEWELL_OLD_PASSWORD only in the disposable rotation runtime.",
        )
    if old_password == new_password:
        raise HTTPException(status_code=400, detail="Old and new passwords must differ.")
    if not 8 <= len(new_password) <= 32:
        raise HTTPException(
            status_code=400,
            detail="The new Magewell password must contain between 8 and 32 characters.",
        )
    return username, old_password, new_password


def validate_scan_network(subnet: str) -> ipaddress.IPv4Network:
    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid subnet: {subnet}") from exc
    allowed_network = get_allowed_network()
    if network.version != 4 or not network.subnet_of(allowed_network):
        raise HTTPException(
            status_code=400,
            detail=f"Subnet must be within ALLOWED_SUBNET ({allowed_network}).",
        )
    host_count = max(network.num_addresses - (0 if network.prefixlen >= 31 else 2), 0)
    if host_count > get_max_scan_hosts():
        raise HTTPException(
            status_code=400,
            detail=f"Subnet contains {host_count} hosts; MAX_SCAN_HOSTS is {get_max_scan_hosts()}.",
        )
    return network


def validate_device_ip(raw_ip: str) -> str:
    try:
        address = ipaddress.ip_address(raw_ip)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid device IP: {raw_ip}") from exc
    allowed_network = get_allowed_network()
    if address.version != 4 or address not in allowed_network:
        raise HTTPException(
            status_code=400,
            detail=f"Device IP {raw_ip} is outside ALLOWED_SUBNET ({allowed_network}).",
        )
    return str(address)


def ensure_unique_devices(devices: list[DeviceSelection]) -> None:
    seen: set[str] = set()
    for device in devices:
        normalized_ip = validate_device_ip(device.ip)
        if normalized_ip in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate device IP: {normalized_ip}")
        seen.add(normalized_ip)
    if len(devices) > get_max_update_devices():
        raise HTTPException(
            status_code=400,
            detail=f"At most {get_max_update_devices()} devices may be updated at once.",
        )


def require_device_writes(confirm: bool) -> None:
    if not env_flag("ENABLE_DEVICE_WRITES"):
        raise HTTPException(
            status_code=403,
            detail="Device writes are locked. Set ENABLE_DEVICE_WRITES=true only for the controlled live run.",
        )
    if not confirm:
        raise HTTPException(status_code=400, detail="Explicit write confirmation is required.")


def require_credential_rotation(confirm: bool) -> None:
    if not env_flag("ENABLE_CREDENTIAL_ROTATION"):
        raise HTTPException(
            status_code=403,
            detail=(
                "Credential rotation is locked. Set ENABLE_CREDENTIAL_ROTATION=true only "
                "in the disposable rotation runtime."
            ),
        )
    if env_flag("ENABLE_DEVICE_WRITES"):
        raise HTTPException(
            status_code=409,
            detail="Credential rotation and Camera-profile writes cannot be enabled together.",
        )
    if not confirm:
        raise HTTPException(
            status_code=400, detail="Explicit credential-rotation confirmation is required."
        )


def md5_hash(password: str) -> str:
    return hashlib.md5(password.encode("utf-8"), usedforsecurity=False).hexdigest()


app = FastAPI(title="Magewell AIO Control", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", OPERATOR_INTENT_HEADER],
)


def get_mutation_lock() -> asyncio.Lock:
    lock = getattr(app.state, "mutation_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        app.state.mutation_lock = lock
    return lock


def public_device_list(devices: list[dict[str, Any]]) -> list[dict[str, str]]:
    public_devices = []
    for device in devices:
        public_device = {"ip": device["ip"], "name": device.get("name", "")}
        if device.get("read_error"):
            public_device["read_error"] = device["read_error"]
        public_devices.append(public_device)
    return public_devices


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(1),
    retry=retry_if_exception_type(aiohttp.ClientError),
    reraise=True,
)
async def login_device(
    session: aiohttp.ClientSession,
    magewell_ip: str,
    username: str,
    hashed_password: str,
    magewell_id: str,
) -> str:
    login_url = f"http://{magewell_ip}/usapi?method=login&id={username}&pass={hashed_password}"
    async with session.get(login_url) as response:
        response.raise_for_status()
        data = await response.json()
        if data.get("result") not in (0, "0"):
            raise RuntimeError(f"Device login was rejected with result {data.get('result')!r}")
        cookie_header = "; ".join(
            f"{name}={cookie.value}" for name, cookie in response.cookies.items()
        )
        if not cookie_header:
            raise RuntimeError("Device login returned no session cookie")
        logger.info("Login succeeded for device %s", magewell_id)
        return cookie_header


async def get_users_call(
    session: aiohttp.ClientSession,
    magewell_ip: str,
    cookie_header: str,
) -> list[dict[str, Any]]:
    url = f"http://{magewell_ip}/usapi"
    async with session.get(
        url,
        params={"method": "get-users"},
        headers={"Cookie": cookie_header},
    ) as response:
        response.raise_for_status()
        result = await response.json()
    if result.get("result") not in (0, "0"):
        raise RuntimeError(f"Device rejected user listing with result {result.get('result')!r}")
    users = result.get("users")
    if not isinstance(users, list):
        raise RuntimeError("Device user listing returned an invalid response")
    return users


async def set_password_call(
    session: aiohttp.ClientSession,
    magewell_ip: str,
    username: str,
    new_password: str,
    cookie_header: str,
) -> None:
    """Submit exactly one credential mutation; this call is intentionally not retried."""
    url = f"http://{magewell_ip}/usapi"
    async with session.get(
        url,
        params={
            "method": "set-passwd",
            "id": username,
            "pass": md5_hash(new_password),
        },
        headers={"Cookie": cookie_header},
    ) as response:
        response.raise_for_status()
        result = await response.json()
    if result.get("result") not in (0, "0"):
        raise RuntimeError(f"Device rejected password change with result {result.get('result')!r}")


async def import_settings_call(
    session: aiohttp.ClientSession,
    magewell_ip: str,
    modified_settings: dict[str, Any],
    cookie_header: str,
    magewell_id: str,
) -> dict[str, Any]:
    """Submit exactly one device mutation; this call is intentionally not retried."""
    import_url = f"http://{magewell_ip}/usapi?method=import-settings"
    async with session.post(
        import_url,
        json=modified_settings,
        headers={"Cookie": cookie_header},
    ) as response:
        response.raise_for_status()
        result = await response.json()
        if result.get("result") not in (0, "0"):
            raise RuntimeError(f"Device rejected settings with result {result.get('result')!r}")
        logger.info("Settings updated for device %s", magewell_id)
        return result


async def get_device_report_with_login(
    session: aiohttp.ClientSession,
    magewell_ip: str,
    username: str,
    password: str,
    timeout: float = 2.0,
) -> dict[str, Any]:
    cookie_header = await login_device(
        session,
        magewell_ip,
        username,
        md5_hash(password),
        magewell_ip,
    )
    url = f"http://{magewell_ip}/usapi?method=get-report"
    headers = {
        "Accept": "text/html",
        "User-Agent": "magewell-aio-control/1.0",
        "Cookie": cookie_header,
    }
    async with session.get(
        url,
        timeout=timeout,
        headers=headers,
        allow_redirects=False,
    ) as response:
        response.raise_for_status()
        soup = BeautifulSoup(await response.text(), "html.parser")
    report_content = soup.find("div", class_="report-content")
    if not report_content:
        raise RuntimeError("Report contains no report-content section")
    for div in report_content.find_all("div", class_="content-level1"):
        heading = div.find("h2")
        if heading and heading.get_text(strip=True).upper() == "SETTINGS":
            pre = div.find("pre", class_="json")
            if not pre:
                break
            settings_data = json.loads(pre.get_text(strip=True))
            if not isinstance(settings_data, dict):
                raise RuntimeError("SETTINGS report is not a JSON object")
            return settings_data
    raise RuntimeError("Report contains no SETTINGS section")


async def identify_rotation_device(
    session: aiohttp.ClientSession,
    magewell_ip: str,
    username: str,
    old_password: str,
    new_password: str,
    timeout: float,
) -> dict[str, str]:
    for credential_state, password in (("new", new_password), ("old", old_password)):
        try:
            report = await get_device_report_with_login(
                session,
                magewell_ip,
                username,
                password,
                timeout,
            )
        except Exception:
            continue
        name = report.get("name", "")
        if not name:
            return {
                "ip": magewell_ip,
                "name": "",
                "credential_state": "error",
                "read_error": "Authenticated report returned no device identity.",
            }
        return {"ip": magewell_ip, "name": name, "credential_state": credential_state}
    return {
        "ip": magewell_ip,
        "name": "",
        "credential_state": "error",
        "read_error": "Neither configured credential authenticated.",
    }


async def ping_magewell(
    session: aiohttp.ClientSession,
    ip: str,
    per_ip_timeout: float = 1.0,
) -> bool:
    url = f"http://{ip}/usapi?method=ping"
    try:
        async with session.get(
            url,
            timeout=per_ip_timeout,
            headers={"Accept": "application/json", "User-Agent": "magewell-aio-control/1.0"},
            allow_redirects=False,
        ) as response:
            data = await response.json()
        return response.status == 200 and data.get("result") in (0, "0")
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return False


async def sem_ping(
    semaphore: asyncio.Semaphore,
    session: aiohttp.ClientSession,
    ip: str,
    timeout: float,
) -> bool:
    async with semaphore:
        return await ping_magewell(session, ip, timeout)


async def push_update_for_device(
    session: aiohttp.ClientSession,
    magewell_ip: str,
    magewell_id: str,
    settings: dict[str, Any],
    username: str,
    password: str,
) -> dict[str, str]:
    try:
        cookie_header = await login_device(
            session,
            magewell_ip,
            username,
            md5_hash(password),
            magewell_id,
        )
        await import_settings_call(session, magewell_ip, settings, cookie_header, magewell_id)
        return {"ip": magewell_ip, "magewell_id": magewell_id, "status": "updated"}
    except Exception as exc:
        error = safe_device_error(exc)
        logger.error("Update failed for %s (%s): %s", magewell_id, magewell_ip, error)
        return {
            "ip": magewell_ip,
            "magewell_id": magewell_id,
            "status": "failed",
            "error": error,
        }


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "allowed_subnet": str(get_allowed_network()),
        "device_reads_configured": bool(
            os.getenv("MAGEWELL_USERNAME", "").strip() and os.getenv("MAGEWELL_PASSWORD", "")
        ),
        "device_writes_enabled": env_flag("ENABLE_DEVICE_WRITES"),
        "credential_rotation_configured": bool(os.getenv("MAGEWELL_OLD_PASSWORD", "")),
        "credential_rotation_enabled": env_flag("ENABLE_CREDENTIAL_ROTATION"),
    }


@app.get("/local-subnet")
async def local_subnet() -> dict[str, str]:
    return {"local_subnet": str(get_allowed_network())}


@app.get("/discover-magewell")
async def discover_magewell(
    subnet: str = Query(..., description="IPv4 subnet within ALLOWED_SUBNET"),
    rescan: bool = Query(False, description="Force a new scan"),
    per_ip_timeout: float = Query(1.0, gt=0, le=5),
    max_concurrent: int = Query(50, ge=1, le=200),
    settings_timeout: float = Query(2.0, gt=0, le=10),
    x_magewell_operator_intent: str | None = Header(None),
    origin: str | None = Header(None),
) -> dict[str, Any]:
    require_operator_intent(x_magewell_operator_intent, origin)
    network = validate_scan_network(subnet)
    username, password = get_device_credentials()
    if not rescan and getattr(app.state, "devices", None):
        return {"devices": public_device_list(app.state.devices), "cached": True}

    app.state.control_settings = None
    app.state.control_device_ip = None
    app.state.control_settings_sha256 = None
    ips = [str(ip) for ip in network.hosts()]
    connector = aiohttp.TCPConnector(ssl=False, family=socket.AF_INET)
    semaphore = asyncio.Semaphore(max_concurrent)
    async with aiohttp.ClientSession(connector=connector) as session:
        ping_results = await asyncio.gather(
            *(sem_ping(semaphore, session, ip, per_ip_timeout) for ip in ips)
        )
        magewell_ips = [ip for ip, matched in zip(ips, ping_results) if matched]
        report_results = await asyncio.gather(
            *(
                get_device_report_with_login(
                    session,
                    ip,
                    username,
                    password,
                    settings_timeout,
                )
                for ip in magewell_ips
            ),
            return_exceptions=True,
        )

    devices = []
    for ip, report in zip(magewell_ips, report_results):
        if isinstance(report, Exception):
            error = safe_device_error(report)
            logger.error("Could not read settings from %s: %s", ip, error)
            devices.append({"ip": ip, "name": "", "settings": {}, "read_error": error})
        else:
            devices.append({"ip": ip, "name": report.get("name", ""), "settings": report})
    app.state.devices = devices
    return {"devices": public_device_list(devices), "cached": False}


@app.get("/credential-rotation-inventory")
async def credential_rotation_inventory(
    subnet: str = Query(..., description="IPv4 subnet within ALLOWED_SUBNET"),
    per_ip_timeout: float = Query(1.0, gt=0, le=5),
    max_concurrent: int = Query(50, ge=1, le=200),
    settings_timeout: float = Query(2.0, gt=0, le=10),
    x_magewell_operator_intent: str | None = Header(None),
    origin: str | None = Header(None),
) -> dict[str, Any]:
    """Classify devices by old/new credential without changing either credential."""
    require_operator_intent(x_magewell_operator_intent, origin)
    network = validate_scan_network(subnet)
    username, old_password, new_password = get_credential_rotation_credentials()
    ips = [str(ip) for ip in network.hosts()]
    connector = aiohttp.TCPConnector(ssl=False, family=socket.AF_INET)
    semaphore = asyncio.Semaphore(max_concurrent)
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=max(30.0, settings_timeout * 10)),
    ) as session:
        ping_results = await asyncio.gather(
            *(sem_ping(semaphore, session, ip, per_ip_timeout) for ip in ips)
        )
        magewell_ips = [ip for ip, matched in zip(ips, ping_results) if matched]
        devices = await asyncio.gather(
            *(
                identify_rotation_device(
                    session,
                    ip,
                    username,
                    old_password,
                    new_password,
                    settings_timeout,
                )
                for ip in magewell_ips
            )
        )
    app.state.rotation_devices = devices
    app.state.rotation_unknown_ips = set()
    return {"devices": devices}


@app.post("/rotate-credential")
async def rotate_credential(
    request: CredentialRotationRequest,
    x_magewell_operator_intent: str | None = Header(None),
    origin: str | None = Header(None),
) -> dict[str, str]:
    """Rotate exactly one device and verify its identity with the new credential."""
    require_operator_intent(x_magewell_operator_intent, origin)
    require_credential_rotation(request.confirm)
    username, old_password, new_password = get_credential_rotation_credentials()
    ip = validate_device_ip(request.device.ip)
    devices = getattr(app.state, "rotation_devices", [])
    cached_device = next((device for device in devices if device["ip"] == ip), None)
    if not cached_device:
        raise HTTPException(
            status_code=400,
            detail="Rotation target is not in the latest credential inventory.",
        )
    if request.device.magewell_id != cached_device.get("name"):
        raise HTTPException(status_code=400, detail="Rotation target identity mismatch.")
    if cached_device.get("credential_state") == "error":
        raise HTTPException(
            status_code=400,
            detail="Rotation target did not authenticate with either configured credential.",
        )
    unknown_ips = getattr(app.state, "rotation_unknown_ips", None)
    if unknown_ips is None:
        unknown_ips = set()
        app.state.rotation_unknown_ips = unknown_ips
    if ip in unknown_ips:
        raise HTTPException(
            status_code=409,
            detail="Credential state is unknown; run a fresh credential inventory before retrying.",
        )

    lock = get_mutation_lock()
    if lock.locked():
        raise HTTPException(status_code=409, detail="Another device mutation is already running.")
    async with lock:
        connector = aiohttp.TCPConnector(ssl=False, family=socket.AF_INET)
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=10.0),
        ) as session:
            if cached_device["credential_state"] == "new":
                report = await get_device_report_with_login(
                    session, ip, username, new_password, timeout=10.0
                )
                if report.get("name") != request.device.magewell_id:
                    raise HTTPException(status_code=400, detail="New-credential identity mismatch.")
                return {
                    "ip": ip,
                    "magewell_id": request.device.magewell_id,
                    "status": "already-rotated",
                }

            old_report = await get_device_report_with_login(
                session, ip, username, old_password, timeout=10.0
            )
            if old_report.get("name") != request.device.magewell_id:
                raise HTTPException(status_code=400, detail="Old-credential identity mismatch.")
            cookie_header = await login_device(
                session,
                ip,
                username,
                md5_hash(old_password),
                request.device.magewell_id,
            )
            users = await get_users_call(session, ip, cookie_header)
            current_user = next((user for user in users if user.get("id") == username), None)
            if not current_user or current_user.get("type") not in (1, "1"):
                raise HTTPException(
                    status_code=403,
                    detail="Configured Magewell user is not confirmed as an administrator.",
                )
            try:
                await set_password_call(
                    session,
                    ip,
                    username,
                    new_password,
                    cookie_header,
                )
            except Exception as exc:
                app.state.rotation_unknown_ips.add(ip)
                logger.error(
                    "Credential mutation response was not verified for %s (%s): %s",
                    request.device.magewell_id,
                    ip,
                    safe_device_error(exc),
                )
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Credential mutation was not verified; stop and run a fresh credential "
                        "inventory before any retry."
                    ),
                ) from None
            try:
                new_report = await get_device_report_with_login(
                    session, ip, username, new_password, timeout=10.0
                )
            except Exception:
                app.state.rotation_unknown_ips.add(ip)
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Password change was accepted but new-credential verification failed; "
                        "stop and recover this device before continuing."
                    ),
                ) from None
            if new_report.get("name") != request.device.magewell_id:
                app.state.rotation_unknown_ips.add(ip)
                raise HTTPException(
                    status_code=502,
                    detail="Password changed but new-credential identity verification failed.",
                )
            cached_device["credential_state"] = "new"
            return {
                "ip": ip,
                "magewell_id": request.device.magewell_id,
                "status": "rotated-and-verified",
            }


@app.post("/set-control")
async def set_control(device: DeviceSelection) -> dict[str, Any]:
    ip = validate_device_ip(device.ip)
    cached_devices = getattr(app.state, "devices", [])
    control_device = next((item for item in cached_devices if item["ip"] == ip), None)
    if not control_device:
        raise HTTPException(status_code=400, detail="Control device is not in the latest scan.")
    control_settings = control_device.get("settings", {})
    if not control_settings:
        raise HTTPException(
            status_code=400, detail="Control device settings were not read successfully."
        )
    scanned_name = control_device.get("name", "")
    if not scanned_name or device.magewell_id != scanned_name:
        raise HTTPException(status_code=400, detail="Control device identity mismatch.")
    frozen_settings = get_bulk_update_settings(
        device.magewell_id,
        control_settings,
        control_settings,
    )
    fingerprint = settings_fingerprint(frozen_settings)
    app.state.control_settings = frozen_settings
    app.state.control_device_ip = ip
    app.state.control_settings_sha256 = fingerprint
    return {
        "message": "Live control settings frozen.",
        "ip": ip,
        "magewell_id": device.magewell_id,
        "settings_sha256": fingerprint,
    }


@app.post("/push-updates")
async def push_updates(
    request: PushUpdateRequest,
    x_magewell_operator_intent: str | None = Header(None),
    origin: str | None = Header(None),
) -> dict[str, Any]:
    require_operator_intent(x_magewell_operator_intent, origin)
    require_device_writes(request.confirm)
    username, password = get_device_credentials()
    ensure_unique_devices(request.devices)
    control_settings = getattr(app.state, "control_settings", None)
    if not control_settings:
        raise HTTPException(
            status_code=400, detail="Select a control device before pushing settings."
        )
    cached_devices = {item["ip"]: item for item in getattr(app.state, "devices", [])}
    invalid_targets = [
        device.ip
        for device in request.devices
        if device.ip not in cached_devices
        or cached_devices[device.ip].get("read_error")
        or not cached_devices[device.ip].get("settings")
    ]
    if invalid_targets:
        raise HTTPException(
            status_code=400,
            detail=(
                "Every write target must have a successful latest-scan report; invalid: "
                f"{', '.join(invalid_targets)}"
            ),
        )
    identity_mismatches = [
        device.ip
        for device in request.devices
        if device.magewell_id != cached_devices[device.ip].get("name")
    ]
    if identity_mismatches:
        raise HTTPException(
            status_code=400,
            detail=f"Write target identity mismatch: {', '.join(identity_mismatches)}",
        )
    source_ip = getattr(app.state, "control_device_ip", None)
    if source_ip and any(device.ip == source_ip for device in request.devices):
        raise HTTPException(status_code=400, detail="The control source cannot be a write target.")
    target_payloads: list[tuple[DeviceSelection, dict[str, Any], str]] = []
    for device in request.devices:
        try:
            payload = get_bulk_update_settings(
                device.magewell_id,
                control_settings,
                cached_devices[device.ip]["settings"],
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Write target {device.ip} is not profile-compatible: {exc}",
            ) from None
        target_payloads.append((device, payload, settings_fingerprint(payload)))
    lock = get_mutation_lock()
    if lock.locked():
        raise HTTPException(status_code=409, detail="Another device update is already running.")
    async with lock:
        connector = aiohttp.TCPConnector(ssl=False, family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector) as session:
            mutation_results = await asyncio.gather(
                *(
                    push_update_for_device(
                        session,
                        device.ip,
                        device.magewell_id,
                        payload,
                        username,
                        password,
                    )
                    for device, payload, _ in target_payloads
                )
            )
    results = []
    for mutation_result, (_, _, expected_fingerprint) in zip(mutation_results, target_payloads):
        results.append(
            {
                **mutation_result,
                "expected_settings_sha256": expected_fingerprint,
            }
        )
    return {
        "source_ip": source_ip,
        "source_settings_sha256": getattr(app.state, "control_settings_sha256", None),
        "results": results,
    }


@app.post("/verify-target")
async def verify_target(
    request: VerifyTargetRequest,
    x_magewell_operator_intent: str | None = Header(None),
    origin: str | None = Header(None),
) -> dict[str, Any]:
    require_operator_intent(x_magewell_operator_intent, origin)
    username, password = get_device_credentials()
    ip = validate_device_ip(request.device.ip)
    cached_device = next(
        (item for item in getattr(app.state, "devices", []) if item["ip"] == ip),
        None,
    )
    if not cached_device or request.device.magewell_id != cached_device.get("name"):
        raise HTTPException(status_code=400, detail="Verification target identity mismatch.")
    if ip == getattr(app.state, "control_device_ip", None):
        raise HTTPException(
            status_code=400, detail="The control source is not a verification target."
        )
    control_settings = getattr(app.state, "control_settings", None)
    if not control_settings:
        raise HTTPException(status_code=400, detail="Select and freeze a control source first.")
    try:
        expected_settings = get_bulk_update_settings(
            request.device.magewell_id,
            control_settings,
            cached_device["settings"],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Verification target is not profile-compatible: {exc}",
        ) from None
    expected = settings_fingerprint(expected_settings)
    connector = aiohttp.TCPConnector(ssl=False, family=socket.AF_INET)
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            report = await get_device_report_with_login(
                session, ip, username, password, timeout=10.0
            )
    except Exception as exc:
        error = safe_device_error(exc)
        logger.error(
            "Verification read failed for %s (%s): %s", request.device.magewell_id, ip, error
        )
        raise HTTPException(status_code=502, detail=error) from None
    actual = settings_fingerprint(report)
    return {
        "ip": ip,
        "magewell_id": request.device.magewell_id,
        "expected_settings_sha256": expected,
        "actual_settings_sha256": actual,
        "matches_expected_profile": actual == expected,
    }


@app.post("/bulk-update")
async def bulk_update(
    confirm: bool = Query(False),
    x_magewell_operator_intent: str | None = Header(None),
    origin: str | None = Header(None),
) -> dict[str, Any]:
    require_operator_intent(x_magewell_operator_intent, origin)
    require_device_writes(confirm)
    raise HTTPException(
        status_code=409,
        detail=(
            "Embedded baseline writes are disabled. Discover devices and select a live "
            "control source instead."
        ),
    )
