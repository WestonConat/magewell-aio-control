import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import aiohttp

from .app import (
    enabled_effect_modes,
    get_allowed_network,
    get_device_credentials,
    get_device_report_with_login,
    login_device,
    md5_hash,
    settings_fingerprint,
)

logger = logging.getLogger(__name__)

EXPECTED_MODULE = "Ultra Encode AIO"
EXPECTED_HARDWARE = "B"
EXPECTED_PRODUCT_ID = 787
DEFAULT_RECOVERY_ROOT = Path("/var/lib/magewell-firmware-recovery")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

STATUS_FIRST_BOOT = 0x01
STATUS_RECORD = 0x02
STATUS_LIVING = 0x04
STATUS_STREAM = 0x08
STATUS_DISK_TEST = 0x1000
STATUS_UPGRADE = 0x4000
STATUS_NET_TEST = 0x8000
STATUS_OCCUPIED = 0x20000
STATUS_FORMAT_DISK = 0x100000
STATUS_FORMAT_SD = 0x200000
STATUS_SEARCH_WIFI = 0x400000
STATUS_CONNECT_WIFI = 0x800000
STATUS_LOADING = 0x1000000
STATUS_CHECK_UPGRADE = 0x2000000
STATUS_RESET = 0x4000000
STATUS_REBOOT = 0x20000000
STATUS_SEND_TEST = 0x40000000
BLOCKED_STATUS_MASK = (
    STATUS_FIRST_BOOT
    | STATUS_RECORD
    | STATUS_LIVING
    | STATUS_STREAM
    | STATUS_DISK_TEST
    | STATUS_UPGRADE
    | STATUS_NET_TEST
    | STATUS_OCCUPIED
    | STATUS_FORMAT_DISK
    | STATUS_FORMAT_SD
    | STATUS_SEARCH_WIFI
    | STATUS_CONNECT_WIFI
    | STATUS_LOADING
    | STATUS_CHECK_UPGRADE
    | STATUS_RESET
    | STATUS_REBOOT
    | STATUS_SEND_TEST
)


class FirmwareSafetyError(RuntimeError):
    pass


class FirmwareUploadResponseUnknown(FirmwareSafetyError):
    pass


class FirmwareInstallResponseUnknown(FirmwareSafetyError):
    pass


@dataclass(frozen=True)
class FirmwareManifestEntry:
    module: str
    hardware: str
    product_id: int
    version: str
    filename: str
    size: int
    sha256: str
    source_url: str


@dataclass
class ValidatedArtifact:
    file: BinaryIO
    manifest: FirmwareManifestEntry
    path: Path

    def public_metadata(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "filename": self.manifest.filename,
            "size": self.manifest.size,
            "sha256": self.manifest.sha256,
            "version": self.manifest.version,
            "module": self.manifest.module,
            "hardware": self.manifest.hardware,
            "product_id": self.manifest.product_id,
            "source_url": self.manifest.source_url,
        }


APPROVED_FIRMWARE = {
    (EXPECTED_MODULE, EXPECTED_HARDWARE, EXPECTED_PRODUCT_ID, "2.4.288"): FirmwareManifestEntry(
        module=EXPECTED_MODULE,
        hardware=EXPECTED_HARDWARE,
        product_id=EXPECTED_PRODUCT_ID,
        version="2.4.288",
        filename="ultra_encode_aio_gen2_rev_b_2_4_288.mwf",
        size=44_250_118,
        sha256="54a39e51e83c80cd567ac451f25a4faf7e84d5458797d069f18546cca0806361",
        source_url="https://www.magewell.com/files/firmware/ultra_encode_aio_2_4_288.zip",
    )
}


def parse_firmware_version(value: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError as exc:
        raise FirmwareSafetyError(f"Invalid firmware version: {value!r}.") from exc
    if len(parts) != 3:
        raise FirmwareSafetyError(f"Invalid firmware version: {value!r}.")
    return parts


def validate_target_ip(raw_ip: str) -> str:
    try:
        address = ipaddress.ip_address(raw_ip)
    except ValueError as exc:
        raise FirmwareSafetyError(f"Invalid device IP: {raw_ip}") from exc
    allowed_network = get_allowed_network()
    if address.version != 4 or address not in allowed_network:
        raise FirmwareSafetyError(
            f"Device IP {raw_ip} is outside ALLOWED_SUBNET ({allowed_network})."
        )
    return str(address)


def require_firmware_effects(confirm: bool) -> None:
    enabled = enabled_effect_modes()
    if enabled != {"firmware-update"}:
        if len(enabled) > 1:
            raise FirmwareSafetyError(
                "Invalid effect configuration: enable only firmware updates for this run."
            )
        raise FirmwareSafetyError(
            "Firmware updates are locked. Set ENABLE_FIRMWARE_UPDATES=true only for the "
            "single-device controlled update."
        )
    if not confirm:
        raise FirmwareSafetyError("Explicit firmware-update confirmation is required.")


def approved_manifest(target_version: str) -> FirmwareManifestEntry:
    parse_firmware_version(target_version)
    key = (EXPECTED_MODULE, EXPECTED_HARDWARE, EXPECTED_PRODUCT_ID, target_version)
    try:
        return APPROVED_FIRMWARE[key]
    except KeyError as exc:
        raise FirmwareSafetyError(
            "No approved firmware manifest entry matches Ultra Encode AIO hardware B "
            f"product 787 version {target_version}."
        ) from exc


@contextmanager
def open_validated_artifact(path: Path, target_version: str) -> Iterator[ValidatedArtifact]:
    manifest = approved_manifest(target_version)
    if path.name != manifest.filename or path.suffix.lower() != ".mwf":
        raise FirmwareSafetyError(
            f"Firmware artifact must use the approved filename {manifest.filename}."
        )
    try:
        firmware_file = path.open("rb")
    except OSError as exc:
        raise FirmwareSafetyError("Firmware artifact could not be opened.") from exc
    try:
        file_stat = os.fstat(firmware_file.fileno())
        if not stat.S_ISREG(file_stat.st_mode):
            raise FirmwareSafetyError("Firmware artifact must be a regular file.")
        digest = hashlib.sha256()
        for chunk in iter(lambda: firmware_file.read(1024 * 1024), b""):
            digest.update(chunk)
        actual_sha256 = digest.hexdigest()
        if file_stat.st_size != manifest.size:
            raise FirmwareSafetyError(
                f"Firmware size mismatch: expected {manifest.size}, got {file_stat.st_size}."
            )
        if actual_sha256 != manifest.sha256:
            raise FirmwareSafetyError(
                f"Firmware SHA-256 mismatch: expected {manifest.sha256}, got {actual_sha256}."
            )
        firmware_file.seek(0)
        yield ValidatedArtifact(firmware_file, manifest, path)
    finally:
        firmware_file.close()


def validate_artifact(path: Path, target_version: str) -> dict[str, Any]:
    with open_validated_artifact(path, target_version) as artifact:
        return artifact.public_metadata()


def _required_int(mapping: dict[str, Any], key: str, context: str) -> int:
    if key not in mapping:
        raise FirmwareSafetyError(f"Device {context} is missing {key!r}.")
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise FirmwareSafetyError(f"Device {context} has invalid {key!r}.")
    return value


def _assert_idle_activity_entry(entry: Any, context: str) -> None:
    if not isinstance(entry, dict):
        raise FirmwareSafetyError(f"Device {context} entry is invalid.")
    _required_int(entry, "id", context)
    _required_int(entry, "type", context)
    is_use = _required_int(entry, "is-use", context)
    if is_use not in (0, 1):
        raise FirmwareSafetyError(f"Device {context} has an unknown 'is-use' value.")
    schedule_key = "is-skd-running" if "is-skd-running" in entry else "is-skd-runnung"
    scheduled_running = _required_int(entry, schedule_key, context)
    if scheduled_running not in (0, 1):
        raise FirmwareSafetyError(f"Device {context} has an unknown schedule state.")
    result = _required_int(entry, "result", context)
    run_ms = _required_int(entry, "run-ms", context)
    if scheduled_running or result != 27 or run_ms != 0:
        raise FirmwareSafetyError(f"Device {context} is active or not in a known idle state.")


def assert_idle_status(status: dict[str, Any]) -> None:
    if not isinstance(status, dict):
        raise FirmwareSafetyError("Device status response is invalid.")
    current_status = _required_int(status, "cur-status", "status")
    blocked_bits = current_status & BLOCKED_STATUS_MASK
    if blocked_bits:
        raise FirmwareSafetyError(
            f"Device has blocked running-status bits set: 0x{blocked_bits:x}."
        )

    live_status = status.get("live-status")
    if not isinstance(live_status, dict):
        raise FirmwareSafetyError("Device status is missing a valid 'live-status' object.")
    if "result" in live_status and _required_int(live_status, "result", "live status") != 27:
        raise FirmwareSafetyError("Device live status is not in the initial/idle state.")
    if "run-ms" in live_status and _required_int(live_status, "run-ms", "live status") != 0:
        raise FirmwareSafetyError("Device live status reports elapsed streaming time.")
    streams = live_status.get("live")
    if not isinstance(streams, list):
        raise FirmwareSafetyError("Device live status is missing a valid stream list.")
    for stream in streams:
        _assert_idle_activity_entry(stream, "live stream")

    record_status = status.get("rec-status")
    if not isinstance(record_status, dict):
        raise FirmwareSafetyError("Device status is missing a valid 'rec-status' object.")
    recordings = record_status.get("rec")
    if not isinstance(recordings, list):
        raise FirmwareSafetyError("Device record status is missing a valid recording list.")
    for recording in recordings:
        _assert_idle_activity_entry(recording, "recording")

    upgrade_status = status.get("upgrade-status")
    if not isinstance(upgrade_status, dict):
        raise FirmwareSafetyError("Device status is missing a valid 'upgrade-status' object.")
    if _required_int(upgrade_status, "result", "upgrade status") != 27:
        raise FirmwareSafetyError("Device firmware state is not initial/idle.")
    if _required_int(upgrade_status, "step", "upgrade status") != 0:
        raise FirmwareSafetyError("Device firmware step is not idle.")
    if _required_int(upgrade_status, "percent", "upgrade status") != 0:
        raise FirmwareSafetyError("Device firmware progress is not idle.")
    if upgrade_status.get("mode") != "none":
        raise FirmwareSafetyError("Device firmware mode is not idle.")
    if not isinstance(upgrade_status.get("client-id"), str):
        raise FirmwareSafetyError("Device firmware client identity is invalid.")


def active_stream_count(status: dict[str, Any]) -> int:
    assert_idle_status(status)
    return 0


def validate_device_info(info: dict[str, Any], target_version: str) -> dict[str, Any]:
    product = info.get("product")
    mac_addresses = info.get("mac-addr")
    if not isinstance(product, dict) or not isinstance(mac_addresses, dict):
        raise FirmwareSafetyError("Device identity response is incomplete.")
    serial = product.get("sn")
    eth_mac = mac_addresses.get("eth")
    if not isinstance(serial, str) or not serial.strip():
        raise FirmwareSafetyError("Device identity is missing an immutable serial number.")
    if not isinstance(eth_mac, str) or not re.fullmatch(
        r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", eth_mac
    ):
        raise FirmwareSafetyError("Device identity is missing a valid Ethernet MAC address.")
    observed = {
        "module": product.get("module-name"),
        "hardware": product.get("hardware-ver"),
        "product_id": product.get("product-id"),
        "firmware": product.get("firmware-ver-s"),
        "serial": serial.strip(),
        "eth_mac": eth_mac.lower(),
    }
    expected = (EXPECTED_MODULE, EXPECTED_HARDWARE, EXPECTED_PRODUCT_ID)
    actual = (observed["module"], observed["hardware"], observed["product_id"])
    if actual != expected:
        raise FirmwareSafetyError(
            "Firmware target identity mismatch: expected Ultra Encode AIO hardware B "
            f"product 787, got {actual!r}."
        )
    current_version = str(observed["firmware"])
    current_parts = parse_firmware_version(current_version)
    target_parts = parse_firmware_version(target_version)
    if current_parts > target_parts:
        raise FirmwareSafetyError(
            f"Firmware downgrade is blocked: device has {current_version}, target is {target_version}."
        )
    observed["already_current"] = observed["firmware"] == target_version
    return observed


def assert_same_device(
    preflight: dict[str, Any],
    observed: dict[str, Any],
    report: dict[str, Any],
    expected_name: str,
) -> None:
    if report.get("name") != expected_name:
        raise FirmwareSafetyError("Firmware target display-name mismatch.")
    identity_fields = ("serial", "eth_mac", "module", "hardware", "product_id", "firmware")
    changed = [field for field in identity_fields if preflight.get(field) != observed.get(field)]
    if changed:
        raise FirmwareSafetyError(
            "Firmware target changed after preflight; mismatched identity fields: "
            + ", ".join(changed)
            + "."
        )


def assert_operator_approved_identity(
    preflight: dict[str, Any], expected_serial: str, expected_eth_mac: str
) -> None:
    serial = expected_serial.strip()
    mac = expected_eth_mac.strip().lower()
    if not serial:
        raise FirmwareSafetyError("An operator-approved device serial is required.")
    if not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac):
        raise FirmwareSafetyError("The operator-approved Ethernet MAC is invalid.")
    if preflight.get("serial") != serial or preflight.get("eth_mac") != mac:
        raise FirmwareSafetyError(
            "The live device does not match the serial and Ethernet MAC approved from preflight."
        )


async def get_authenticated_json(
    session: aiohttp.ClientSession,
    ip: str,
    cookie_header: str,
    method: str,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    async with session.get(
        f"http://{ip}/usapi",
        params={"method": method},
        headers={"Cookie": cookie_header},
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        data = await response.json()
    if data.get("result") not in (0, "0"):
        raise FirmwareSafetyError(f"Device rejected {method} with result {data.get('result')!r}.")
    return data


async def get_device_info(
    session: aiohttp.ClientSession,
    ip: str,
    cookie_header: str,
) -> dict[str, Any]:
    return await get_authenticated_json(session, ip, cookie_header, "get-info")


async def get_device_status(
    session: aiohttp.ClientSession,
    ip: str,
    cookie_header: str,
) -> dict[str, Any]:
    return await get_authenticated_json(session, ip, cookie_header, "get-status")


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    _fsync_directory(path)


def get_recovery_root() -> Path:
    return DEFAULT_RECOVERY_ROOT


def _safe_identity_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", value)
    if not safe:
        raise FirmwareSafetyError("Device identity cannot be used for recovery state.")
    return safe


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(payload, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    _fsync_directory(path.parent)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def acquire_effect_state(
    recovery_root: Path,
    preflight: dict[str, Any],
    artifact: dict[str, Any],
) -> Path:
    resolved = recovery_root.resolve()
    if (
        not resolved.is_absolute()
        or resolved == REPOSITORY_ROOT
        or REPOSITORY_ROOT in resolved.parents
    ):
        raise FirmwareSafetyError(
            "Firmware recovery state must use an absolute non-repository path."
        )
    _private_directory(resolved)
    device_dir = resolved / _safe_identity_component(str(preflight["serial"]))
    run_dir = device_dir / str(artifact["sha256"])
    _private_directory(device_dir)
    _private_directory(run_dir)
    lock_path = run_dir / "effect.lock"
    try:
        _write_json_exclusive(
            lock_path,
            {
                "state": "locked",
                "ip": preflight["ip"],
                "name": preflight["name"],
                "serial": preflight["serial"],
                "eth_mac": preflight["eth_mac"],
                "artifact_sha256": artifact["sha256"],
            },
        )
    except FileExistsError as exc:
        raise FirmwareSafetyError(
            "A durable firmware-effect receipt already exists for this device and artifact. "
            "Do not upload or install again; use read-only verification and inspect recovery state."
        ) from exc
    return run_dir


def record_effect_state(run_dir: Path, state: str, **details: Any) -> None:
    payload = {"state": state, **details}
    events_path = run_dir / "firmware-events.jsonl"
    fd = os.open(events_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as events:
        events.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        events.flush()
        os.fsync(events.fileno())
    _fsync_directory(run_dir)
    _write_json_atomic(run_dir / "firmware-state.json", payload)


def write_recovery_backup(
    run_dir: Path,
    ip: str,
    expected_name: str,
    settings: dict[str, Any],
    observed: dict[str, Any],
) -> Path:
    _private_directory(run_dir)
    backup_path = run_dir / "pre-firmware-settings.json"
    payload = {
        "ip": ip,
        "expected_name": expected_name,
        "observed": observed,
        "settings_sha256": settings_fingerprint(settings),
        "settings": settings,
    }
    _write_json_exclusive(backup_path, payload)
    return backup_path


async def upload_firmware_once(
    session: aiohttp.ClientSession,
    ip: str,
    cookie_header: str,
    artifact: ValidatedArtifact,
) -> dict[str, Any]:
    artifact.file.seek(0)
    form = aiohttp.FormData()
    form.add_field(
        "file",
        artifact.file,
        filename=artifact.manifest.filename,
        content_type="application/octet-stream",
    )
    try:
        async with session.post(
            f"http://{ip}/usapi",
            params={"method": "upload-update-file"},
            data=form,
            headers={"Cookie": cookie_header},
            timeout=aiohttp.ClientTimeout(total=180.0),
        ) as response:
            response.raise_for_status()
            result = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise FirmwareUploadResponseUnknown(
            "Firmware upload response is unknown; do not install or retry until the device "
            "state and durable receipt are inspected manually."
        ) from exc
    result_code = result.get("status", result.get("result"))
    if result_code not in (0, "0"):
        raise FirmwareSafetyError(f"Device rejected firmware upload with result {result_code!r}.")
    if str(result.get("version")) != artifact.manifest.version:
        raise FirmwareSafetyError(f"Uploaded firmware version mismatch: {result.get('version')!r}.")
    if result.get("size") != artifact.manifest.size:
        raise FirmwareSafetyError("Device-reported firmware upload size does not match artifact.")
    return result


async def start_firmware_update_once(
    session: aiohttp.ClientSession,
    ip: str,
    cookie_header: str,
) -> dict[str, Any]:
    try:
        async with session.get(
            f"http://{ip}/usapi",
            params={"method": "update", "mode": "upload"},
            headers={"Cookie": cookie_header},
            timeout=10.0,
        ) as response:
            response.raise_for_status()
            result = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise FirmwareInstallResponseUnknown(
            "Firmware install response is unknown; verification will continue without retry."
        ) from exc
    if result.get("result") not in (0, "0"):
        raise FirmwareSafetyError(
            f"Device rejected firmware install with result {result.get('result')!r}."
        )
    return result


async def wait_for_verified_firmware(
    ip: str,
    expected_name: str,
    username: str,
    password: str,
    target_version: str,
    expected_serial: str,
    expected_eth_mac: str,
    *,
    timeout_seconds: float = 600.0,
    poll_seconds: float = 5.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_error = "Device has not returned yet."
    while asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(poll_seconds)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20.0)) as session:
                cookie_header = await login_device(
                    session,
                    ip,
                    username,
                    md5_hash(password),
                    expected_name,
                )
                info = await get_device_info(session, ip, cookie_header)
                observed = validate_device_info(info, target_version)
                if observed["serial"] != expected_serial or observed["eth_mac"] != expected_eth_mac:
                    raise FirmwareSafetyError("Post-update immutable device identity mismatch.")
                if not observed["already_current"]:
                    last_error = f"Device returned on firmware {observed['firmware']!r}."
                    continue
                report = await get_device_report_with_login(
                    session, ip, username, password, timeout=20.0
                )
                if report.get("name") != expected_name:
                    raise FirmwareSafetyError("Post-update device display-name mismatch.")
                status = await get_device_status(session, ip, cookie_header)
                assert_idle_status(status)
                return (
                    {
                        **observed,
                        "name": report.get("name"),
                        "settings_sha256": settings_fingerprint(report),
                    },
                    report,
                )
        except FirmwareSafetyError:
            raise
        except Exception as exc:
            last_error = type(exc).__name__
    raise FirmwareSafetyError(
        "Firmware install may have started but exact post-reboot verification did not complete; "
        f"do not retry. Last observation: {last_error}"
    )


def settings_change_summary(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_keys = set(before)
    after_keys = set(after)
    common = before_keys & after_keys
    return {
        "added_top_level_keys": sorted(after_keys - before_keys),
        "removed_top_level_keys": sorted(before_keys - after_keys),
        "changed_top_level_keys": sorted(key for key in common if before[key] != after[key]),
    }


async def preflight_one(
    ip: str,
    expected_name: str,
    target_version: str,
) -> dict[str, Any]:
    approved_manifest(target_version)
    normalized_ip = validate_target_ip(ip)
    username, password = get_device_credentials()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30.0)) as session:
        cookie_header = await login_device(
            session,
            normalized_ip,
            username,
            md5_hash(password),
            expected_name,
        )
        report = await get_device_report_with_login(
            session, normalized_ip, username, password, timeout=20.0
        )
        if report.get("name") != expected_name:
            raise FirmwareSafetyError("Firmware target display-name mismatch.")
        info = await get_device_info(session, normalized_ip, cookie_header)
        status = await get_device_status(session, normalized_ip, cookie_header)
    observed = validate_device_info(info, target_version)
    assert_idle_status(status)
    return {
        "ip": normalized_ip,
        "name": expected_name,
        **observed,
        "active_streams": 0,
        "settings_sha256": settings_fingerprint(report),
    }


async def update_one(
    ip: str,
    expected_name: str,
    expected_serial: str,
    expected_eth_mac: str,
    target_version: str,
    artifact_path: Path,
    *,
    confirm: bool,
    recovery_root: Path | None = None,
) -> dict[str, Any]:
    require_firmware_effects(confirm)
    with open_validated_artifact(artifact_path, target_version) as artifact:
        artifact_metadata = artifact.public_metadata()
        preflight = await preflight_one(ip, expected_name, target_version)
        assert_operator_approved_identity(preflight, expected_serial, expected_eth_mac)
        if preflight["already_current"]:
            return {
                "status": "already-current",
                "preflight": preflight,
                "artifact": artifact_metadata,
            }

        username, password = get_device_credentials()
        normalized_ip = preflight["ip"]
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=210.0)) as session:
            cookie_header = await login_device(
                session,
                normalized_ip,
                username,
                md5_hash(password),
                expected_name,
            )
            settings = await get_device_report_with_login(
                session, normalized_ip, username, password, timeout=20.0
            )
            info = await get_device_info(session, normalized_ip, cookie_header)
            observed = validate_device_info(info, target_version)
            assert_same_device(preflight, observed, settings, expected_name)
            status = await get_device_status(session, normalized_ip, cookie_header)
            assert_idle_status(status)

            run_dir = acquire_effect_state(
                recovery_root or get_recovery_root(), preflight, artifact_metadata
            )
            backup_path = write_recovery_backup(
                run_dir,
                normalized_ip,
                expected_name,
                settings,
                preflight,
            )
            logger.warning("Firmware recovery backup is durable at %s", backup_path)
            record_effect_state(
                run_dir,
                "backup-ready",
                backup_path=str(backup_path),
                pre_settings_sha256=settings_fingerprint(settings),
            )

            final_report = await get_device_report_with_login(
                session, normalized_ip, username, password, timeout=20.0
            )
            final_info = await get_device_info(session, normalized_ip, cookie_header)
            final_observed = validate_device_info(final_info, target_version)
            assert_same_device(preflight, final_observed, final_report, expected_name)
            if settings_fingerprint(final_report) != settings_fingerprint(settings):
                record_effect_state(run_dir, "pre-upload-settings-changed")
                raise FirmwareSafetyError(
                    "Device settings changed after the recovery backup; stop before upload."
                )
            final_status = await get_device_status(session, normalized_ip, cookie_header)
            assert_idle_status(final_status)

            record_effect_state(run_dir, "upload-starting")
            try:
                upload = await upload_firmware_once(
                    session,
                    normalized_ip,
                    cookie_header,
                    artifact,
                )
            except FirmwareUploadResponseUnknown as exc:
                record_effect_state(run_dir, "upload-unknown", message=str(exc))
                raise
            except FirmwareSafetyError as exc:
                record_effect_state(run_dir, "upload-rejected", message=str(exc))
                raise
            record_effect_state(run_dir, "uploaded", device_response=upload)

            record_effect_state(run_dir, "install-starting")
            try:
                install = await start_firmware_update_once(session, normalized_ip, cookie_header)
            except FirmwareInstallResponseUnknown as exc:
                install = {"result": "unknown", "message": str(exc)}
                record_effect_state(run_dir, "install-unknown", message=str(exc))
            except FirmwareSafetyError as exc:
                record_effect_state(run_dir, "install-rejected", message=str(exc))
                raise
            else:
                record_effect_state(run_dir, "install-accepted", device_response=install)

        try:
            verified, post_settings = await wait_for_verified_firmware(
                normalized_ip,
                expected_name,
                username,
                password,
                target_version,
                preflight["serial"],
                preflight["eth_mac"],
            )
        except FirmwareSafetyError as exc:
            record_effect_state(run_dir, "verification-failed", message=str(exc))
            raise

        pre_settings_sha256 = settings_fingerprint(settings)
        post_settings_sha256 = settings_fingerprint(post_settings)
        settings_changes = settings_change_summary(settings, post_settings)
        if pre_settings_sha256 != post_settings_sha256:
            result_status = "firmware-verified-settings-changed"
            record_effect_state(
                run_dir,
                result_status,
                pre_settings_sha256=pre_settings_sha256,
                post_settings_sha256=post_settings_sha256,
                settings_changes=settings_changes,
            )
        else:
            result_status = "updated-and-verified"
            record_effect_state(
                run_dir,
                result_status,
                settings_sha256=post_settings_sha256,
            )
        return {
            "status": result_status,
            "preflight": preflight,
            "artifact": artifact_metadata,
            "recovery_state": str(run_dir),
            "backup_path": str(backup_path),
            "upload": upload,
            "install": install,
            "verified": verified,
            "settings_changes": settings_changes,
        }
