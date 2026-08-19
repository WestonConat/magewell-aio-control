import asyncio
import copy
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
    import_settings_call,
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


def assert_idle_status(status: dict[str, Any], *, post_update: bool = False) -> int:
    if not isinstance(status, dict):
        raise FirmwareSafetyError("Device status response is invalid.")
    current_status = _required_int(status, "cur-status", "status")
    allowed_background_bits = STATUS_SEARCH_WIFI | STATUS_CONNECT_WIFI if post_update else 0
    blocked_bits = current_status & (BLOCKED_STATUS_MASK & ~allowed_background_bits)
    if blocked_bits:
        raise FirmwareSafetyError(
            f"Device has blocked running-status bits set: 0x{blocked_bits:x}."
        )

    live_status = status.get("live-status")
    if not isinstance(live_status, dict):
        raise FirmwareSafetyError("Device status is missing a valid 'live-status' object.")
    live_result = None
    if "result" in live_status:
        live_result = _required_int(live_status, "result", "live status")
        if live_result not in (0, 27):
            raise FirmwareSafetyError("Device live status is not in a known idle state.")
    if "run-ms" in live_status and _required_int(live_status, "run-ms", "live status") != 0:
        raise FirmwareSafetyError("Device live status reports elapsed streaming time.")
    streams = live_status.get("live")
    if not isinstance(streams, list):
        raise FirmwareSafetyError("Device live status is missing a valid stream list.")
    if live_result == 0 and streams:
        raise FirmwareSafetyError(
            "Post-update live wrapper result 0 is valid only with an empty stream list."
        )
    for stream in streams:
        _assert_idle_activity_entry(stream, "live stream")

    record_status = status.get("rec-status")
    if not isinstance(record_status, dict):
        raise FirmwareSafetyError("Device status is missing a valid 'rec-status' object.")
    record_result = None
    if "result" in record_status:
        record_result = _required_int(record_status, "result", "record status")
        if record_result not in (0, 27):
            raise FirmwareSafetyError("Device record status is not in a known idle state.")
    if "run-ms" in record_status and _required_int(record_status, "run-ms", "record status") != 0:
        raise FirmwareSafetyError("Device record status reports elapsed recording time.")
    recordings = record_status.get("rec")
    if not isinstance(recordings, list):
        raise FirmwareSafetyError("Device record status is missing a valid recording list.")
    if record_result == 0 and recordings:
        raise FirmwareSafetyError(
            "Post-update record wrapper result 0 is valid only with an empty recording list."
        )
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
    return current_status & allowed_background_bits


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
                try:
                    background_status_bits = assert_idle_status(status, post_update=True)
                except FirmwareSafetyError as exc:
                    last_error = str(exc)
                    continue
                return (
                    {
                        **observed,
                        "name": report.get("name"),
                        "settings_sha256": settings_fingerprint(report),
                        "background_status_bits": background_status_bits,
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


def _remove_expected_addition(
    before: dict[str, Any],
    after: dict[str, Any],
    key: str,
    expected_value: Any,
    path: str,
    accepted: list[str],
) -> None:
    if key not in before and after.get(key) == expected_value:
        after.pop(key)
        accepted.append(path)


def _difference_paths(before: Any, after: Any, path: tuple[str, ...] = ()) -> list[str]:
    if type(before) is not type(after):
        return [".".join(path) or "<root>"]
    if isinstance(before, dict):
        differences: list[str] = []
        for key in sorted(set(before) | set(after)):
            child_path = (*path, str(key))
            if key not in before or key not in after:
                differences.append(".".join(child_path))
            else:
                differences.extend(_difference_paths(before[key], after[key], child_path))
        return differences
    if isinstance(before, list):
        differences = []
        if len(before) != len(after):
            differences.append(".".join((*path, "length")))
        for index, (before_item, after_item) in enumerate(zip(before, after)):
            differences.extend(_difference_paths(before_item, after_item, (*path, str(index))))
        return differences
    return [] if before == after else [".".join(path) or "<root>"]


def settings_preservation_report(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    normalized_before = copy.deepcopy(before)
    normalized_after = copy.deepcopy(after)
    ignored_transient_paths: list[str] = []
    for label, settings in (("before", normalized_before), ("after", normalized_after)):
        wifi_entries = settings.get("wifi")
        if isinstance(wifi_entries, list):
            for index, entry in enumerate(wifi_entries):
                if isinstance(entry, dict) and "level" in entry:
                    entry.pop("level")
                    ignored_transient_paths.append(f"{label}.wifi.{index}.level")

    accepted_additions: list[str] = []
    expected_top_level_additions = {
        "enable-ndi-bridge": 0,
        "ndi-bridge": {
            "bridge-name": "",
            "encryp-key": "",
            "groups": "Public",
            "ip-addr": "",
            "port": 5990,
        },
        "enable-zen-master": 0,
        "zen-master": {
            "host": "",
            "is-key-valid": 0,
            "tunnel-port": 0,
            "user-name": "",
        },
    }
    for key, expected_value in expected_top_level_additions.items():
        _remove_expected_addition(
            normalized_before,
            normalized_after,
            key,
            expected_value,
            key,
            accepted_additions,
        )

    before_living = normalized_before.get("living")
    after_living = normalized_after.get("living")
    if isinstance(before_living, dict) and isinstance(after_living, dict):
        _remove_expected_addition(
            before_living,
            after_living,
            "live-keep-last",
            1,
            "living.live-keep-last",
            accepted_additions,
        )

    before_servers = normalized_before.get("stream-server")
    after_servers = normalized_after.get("stream-server")
    server_defaults = {
        "audio-pids": [0] * 8,
        "is-custom-pid": 0,
        "pcr-pid": 0,
        "pmt-pid": 0,
        "video-pid": 0,
    }
    if isinstance(before_servers, list) and isinstance(after_servers, list):
        for index, (before_server, after_server) in enumerate(zip(before_servers, after_servers)):
            if not isinstance(before_server, dict) or not isinstance(after_server, dict):
                continue
            for key, expected_value in server_defaults.items():
                _remove_expected_addition(
                    before_server,
                    after_server,
                    key,
                    expected_value,
                    f"stream-server.{index}.{key}",
                    accepted_additions,
                )

    before_schedulers = normalized_before.get("schedulers")
    after_schedulers = normalized_after.get("schedulers")
    scheduler_defaults = {
        "panopto-folder-id": "",
        "source": 0,
        "uid": "",
        "utc-dateline": 0,
        "utc-time-begin": 0,
        "utc-time-end": 0,
    }
    if isinstance(before_schedulers, list) and isinstance(after_schedulers, list):
        for scheduler_index, (before_scheduler, after_scheduler) in enumerate(
            zip(before_schedulers, after_schedulers)
        ):
            if not isinstance(before_scheduler, dict) or not isinstance(after_scheduler, dict):
                continue
            _remove_expected_addition(
                before_scheduler,
                after_scheduler,
                "import-type",
                0,
                f"schedulers.{scheduler_index}.import-type",
                accepted_additions,
            )
            before_channels = before_scheduler.get("channels")
            after_channels = after_scheduler.get("channels")
            if not isinstance(before_channels, list) or not isinstance(after_channels, list):
                continue
            for channel_index, (before_channel, after_channel) in enumerate(
                zip(before_channels, after_channels)
            ):
                if not isinstance(before_channel, dict) or not isinstance(after_channel, dict):
                    continue
                for key, expected_value in scheduler_defaults.items():
                    _remove_expected_addition(
                        before_channel,
                        after_channel,
                        key,
                        expected_value,
                        f"schedulers.{scheduler_index}.channels.{channel_index}.{key}",
                        accepted_additions,
                    )

    unexpected_change_paths = _difference_paths(normalized_before, normalized_after)
    return {
        "preserved": not unexpected_change_paths,
        "accepted_firmware_additions": sorted(accepted_additions),
        "ignored_transient_paths": sorted(ignored_transient_paths),
        "unexpected_change_paths": unexpected_change_paths,
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


async def verify_one(
    ip: str,
    expected_name: str,
    expected_serial: str,
    expected_eth_mac: str,
    target_version: str,
    *,
    recovery_root: Path | None = None,
) -> dict[str, Any]:
    if enabled_effect_modes():
        raise FirmwareSafetyError("Lock all effect modes before recovery verification.")
    normalized_ip = validate_target_ip(ip)
    manifest = approved_manifest(target_version)
    run_dir = (
        (recovery_root or get_recovery_root())
        / _safe_identity_component(expected_serial.strip())
        / manifest.sha256
    )
    backup_path = run_dir / "pre-firmware-settings.json"
    lock_path = run_dir / "effect.lock"
    if not backup_path.is_file() or not lock_path.is_file():
        raise FirmwareSafetyError("The durable firmware recovery receipt is incomplete.")
    try:
        backup_payload = json.loads(backup_path.read_text(encoding="utf-8"))
        lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FirmwareSafetyError("The durable firmware recovery receipt is unreadable.") from exc
    expected_receipt = {
        "ip": normalized_ip,
        "name": expected_name,
        "serial": expected_serial.strip(),
        "eth_mac": expected_eth_mac.strip().lower(),
        "artifact_sha256": manifest.sha256,
    }
    if any(lock_payload.get(key) != value for key, value in expected_receipt.items()):
        raise FirmwareSafetyError("The recovery receipt does not match the approved target.")
    before_settings = backup_payload.get("settings")
    if not isinstance(before_settings, dict):
        raise FirmwareSafetyError("The recovery backup contains no valid settings snapshot.")

    username, password = get_device_credentials()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30.0)) as session:
        cookie_header = await login_device(
            session,
            normalized_ip,
            username,
            md5_hash(password),
            expected_name,
        )
        info = await get_device_info(session, normalized_ip, cookie_header)
        observed = validate_device_info(info, target_version)
        assert_operator_approved_identity(observed, expected_serial, expected_eth_mac)
        if not observed["already_current"]:
            raise FirmwareSafetyError(
                f"Recovery verification found firmware {observed['firmware']!r}, not {target_version}."
            )
        report = await get_device_report_with_login(
            session, normalized_ip, username, password, timeout=20.0
        )
        if report.get("name") != expected_name:
            raise FirmwareSafetyError("Recovery verification found a display-name mismatch.")
        status = await get_device_status(session, normalized_ip, cookie_header)
        background_status_bits = assert_idle_status(status, post_update=True)

    preservation = settings_preservation_report(before_settings, report)
    settings_changes = settings_change_summary(before_settings, report)
    result_status = (
        "recovery-verified" if preservation["preserved"] else "recovery-verified-settings-changed"
    )
    record_effect_state(
        run_dir,
        result_status,
        firmware=observed["firmware"],
        background_status_bits=background_status_bits,
        pre_settings_sha256=settings_fingerprint(before_settings),
        post_settings_sha256=settings_fingerprint(report),
        preservation=preservation,
    )
    return {
        "status": result_status,
        "ip": normalized_ip,
        "name": expected_name,
        **observed,
        "background_status_bits": background_status_bits,
        "settings_changes": settings_changes,
        "preservation": preservation,
        "recovery_state": str(run_dir),
    }


async def restore_recording_channel_one(
    ip: str,
    expected_name: str,
    expected_serial: str,
    expected_eth_mac: str,
    target_version: str,
    *,
    confirm: bool,
    recovery_root: Path | None = None,
) -> dict[str, Any]:
    """Restore one firmware-reset recording enable flag from the durable backup."""
    require_firmware_effects(confirm)
    normalized_ip = validate_target_ip(ip)
    manifest = approved_manifest(target_version)
    run_dir = (
        (recovery_root or get_recovery_root())
        / _safe_identity_component(expected_serial.strip())
        / manifest.sha256
    )
    backup_path = run_dir / "pre-firmware-settings.json"
    effect_lock_path = run_dir / "effect.lock"
    state_path = run_dir / "firmware-state.json"
    if not backup_path.is_file() or not effect_lock_path.is_file() or not state_path.is_file():
        raise FirmwareSafetyError("The durable firmware recovery receipt is incomplete.")
    try:
        backup_payload = json.loads(backup_path.read_text(encoding="utf-8"))
        effect_lock = json.loads(effect_lock_path.read_text(encoding="utf-8"))
        effect_state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FirmwareSafetyError("The durable firmware recovery receipt is unreadable.") from exc
    expected_receipt = {
        "ip": normalized_ip,
        "name": expected_name,
        "serial": expected_serial.strip(),
        "eth_mac": expected_eth_mac.strip().lower(),
        "artifact_sha256": manifest.sha256,
    }
    if any(effect_lock.get(key) != value for key, value in expected_receipt.items()):
        raise FirmwareSafetyError("The recovery receipt does not match the approved target.")
    if effect_state.get("state") not in {
        "firmware-verified-settings-changed",
        "recovery-verified-settings-changed",
    }:
        raise FirmwareSafetyError("The receipt does not record a settings-verification stop.")
    before_settings = backup_payload.get("settings")
    if not isinstance(before_settings, dict):
        raise FirmwareSafetyError("The recovery backup contains no valid settings snapshot.")
    try:
        backed_up_value = before_settings["rec-channels"][0]["is-use"]
    except (KeyError, IndexError, TypeError) as exc:
        raise FirmwareSafetyError(
            "The recovery backup has no recording-channel enable flag."
        ) from exc
    if backed_up_value != 1:
        raise FirmwareSafetyError(
            "The backed-up recording-channel value is not the approved value 1."
        )

    username, password = get_device_credentials()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30.0)) as session:
        cookie_header = await login_device(
            session,
            normalized_ip,
            username,
            md5_hash(password),
            expected_name,
        )
        info = await get_device_info(session, normalized_ip, cookie_header)
        observed = validate_device_info(info, target_version)
        assert_operator_approved_identity(observed, expected_serial, expected_eth_mac)
        if not observed["already_current"]:
            raise FirmwareSafetyError("Recording recovery requires the verified target firmware.")
        current_settings = await get_device_report_with_login(
            session, normalized_ip, username, password, timeout=20.0
        )
        if current_settings.get("name") != expected_name:
            raise FirmwareSafetyError("Recording recovery found a display-name mismatch.")
        status = await get_device_status(session, normalized_ip, cookie_header)
        background_status_bits = assert_idle_status(status, post_update=True)
        preservation = settings_preservation_report(before_settings, current_settings)
        if preservation["unexpected_change_paths"] != ["rec-channels.0.is-use"]:
            raise FirmwareSafetyError(
                "Recording recovery found drift beyond the single approved enable flag."
            )
        try:
            current_value = current_settings["rec-channels"][0]["is-use"]
        except (KeyError, IndexError, TypeError) as exc:
            raise FirmwareSafetyError(
                "The current recording-channel enable flag is missing."
            ) from exc
        if current_value != 0:
            raise FirmwareSafetyError(
                "The current recording-channel value is not the stopped value 0."
            )

        repair_lock = run_dir / "recording-recovery.lock"
        try:
            _write_json_exclusive(
                repair_lock,
                {
                    "state": "locked",
                    **expected_receipt,
                    "path": "rec-channels.0.is-use",
                    "before": current_value,
                    "restore": backed_up_value,
                    "current_settings_sha256": settings_fingerprint(current_settings),
                },
            )
        except FileExistsError as exc:
            raise FirmwareSafetyError(
                "A durable recording-recovery receipt already exists; do not submit again."
            ) from exc

        final_settings = await get_device_report_with_login(
            session, normalized_ip, username, password, timeout=20.0
        )
        if settings_fingerprint(final_settings) != settings_fingerprint(current_settings):
            record_effect_state(run_dir, "recording-recovery-prewrite-settings-changed")
            raise FirmwareSafetyError("Device settings changed before recording recovery.")
        repaired_settings = copy.deepcopy(final_settings)
        repaired_settings["rec-channels"][0]["is-use"] = backed_up_value
        record_effect_state(run_dir, "recording-recovery-starting")
        try:
            device_response = await import_settings_call(
                session,
                normalized_ip,
                repaired_settings,
                cookie_header,
                expected_name,
            )
        except Exception as exc:
            record_effect_state(
                run_dir,
                "recording-recovery-response-unknown",
                message=type(exc).__name__,
            )
            raise FirmwareSafetyError(
                "Recording recovery response is unknown; do not retry before read-only verification."
            ) from exc

        verified_settings: dict[str, Any] = {}
        for verification_attempt in range(1, 4):
            verified_settings = await get_device_report_with_login(
                session, normalized_ip, username, password, timeout=20.0
            )
            if settings_preservation_report(before_settings, verified_settings)["preserved"]:
                break
            if verification_attempt < 3:
                await asyncio.sleep(1)
        verified_info = await get_device_info(session, normalized_ip, cookie_header)
        verified_observed = validate_device_info(verified_info, target_version)
        assert_operator_approved_identity(verified_observed, expected_serial, expected_eth_mac)
        if verified_settings.get("name") != expected_name:
            raise FirmwareSafetyError("Recording recovery found a post-write name mismatch.")
        verified_status = await get_device_status(session, normalized_ip, cookie_header)
        verified_background_bits = assert_idle_status(verified_status, post_update=True)

    verified_preservation = settings_preservation_report(before_settings, verified_settings)
    if not verified_preservation["preserved"]:
        record_effect_state(
            run_dir,
            "recording-recovery-verification-failed",
            preservation=verified_preservation,
        )
        raise FirmwareSafetyError("Recording recovery did not restore settings preservation.")
    record_effect_state(
        run_dir,
        "recording-recovery-verified",
        settings_sha256=settings_fingerprint(verified_settings),
        preservation=verified_preservation,
    )
    return {
        "status": "recording-recovery-verified",
        "ip": normalized_ip,
        "name": expected_name,
        **verified_observed,
        "restored_path": "rec-channels.0.is-use",
        "restored_value": backed_up_value,
        "device_response": device_response,
        "background_status_bits": max(background_status_bits, verified_background_bits),
        "preservation": verified_preservation,
        "recovery_state": str(run_dir),
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
        preservation = settings_preservation_report(settings, post_settings)
        if not preservation["preserved"]:
            result_status = "firmware-verified-settings-changed"
            record_effect_state(
                run_dir,
                result_status,
                pre_settings_sha256=pre_settings_sha256,
                post_settings_sha256=post_settings_sha256,
                settings_changes=settings_changes,
                preservation=preservation,
            )
        else:
            result_status = "updated-and-verified"
            record_effect_state(
                run_dir,
                result_status,
                settings_sha256=post_settings_sha256,
                pre_settings_sha256=pre_settings_sha256,
                preservation=preservation,
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
            "preservation": preservation,
        }
