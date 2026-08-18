import asyncio
import copy
import hashlib
import json
import stat
from pathlib import Path

import pytest

from backend import firmware
from backend.firmware import (
    APPROVED_FIRMWARE,
    EXPECTED_HARDWARE,
    EXPECTED_MODULE,
    EXPECTED_PRODUCT_ID,
    FirmwareInstallResponseUnknown,
    FirmwareManifestEntry,
    FirmwareSafetyError,
    FirmwareUploadResponseUnknown,
    acquire_effect_state,
    assert_idle_status,
    open_validated_artifact,
    require_firmware_effects,
    settings_preservation_report,
    update_one,
    validate_artifact,
    validate_device_info,
    verify_one,
    write_recovery_backup,
)

TARGET_VERSION = "2.4.288"
ARTIFACT_FILENAME = "ultra_encode_aio_gen2_rev_b_2_4_288.mwf"


def valid_status() -> dict:
    return {
        "cur-status": 0,
        "live-status": {"result": 27, "run-ms": 0, "live": []},
        "rec-status": {"rec": []},
        "upgrade-status": {
            "result": 27,
            "step": 0,
            "percent": 0,
            "mode": "none",
            "client-id": "",
        },
    }


def valid_info(version: str = "2.3.206") -> dict:
    return {
        "mac-addr": {"eth": "d0:c8:57:80:3a:70"},
        "product": {
            "sn": "A305200908002",
            "module-name": EXPECTED_MODULE,
            "hardware-ver": EXPECTED_HARDWARE,
            "product-id": EXPECTED_PRODUCT_ID,
            "firmware-ver-s": version,
        },
    }


def valid_preflight() -> dict:
    return {
        "ip": "192.0.2.10",
        "name": "ENCODER-01",
        "module": EXPECTED_MODULE,
        "hardware": EXPECTED_HARDWARE,
        "product_id": EXPECTED_PRODUCT_ID,
        "firmware": "2.3.206",
        "serial": "A305200908002",
        "eth_mac": "d0:c8:57:80:3a:70",
        "already_current": False,
        "active_streams": 0,
        "settings_sha256": "preflight-hash",
    }


def install_test_manifest(monkeypatch, artifact_path: Path, payload: bytes) -> str:
    artifact_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    monkeypatch.setitem(
        APPROVED_FIRMWARE,
        (EXPECTED_MODULE, EXPECTED_HARDWARE, EXPECTED_PRODUCT_ID, TARGET_VERSION),
        FirmwareManifestEntry(
            module=EXPECTED_MODULE,
            hardware=EXPECTED_HARDWARE,
            product_id=EXPECTED_PRODUCT_ID,
            version=TARGET_VERSION,
            filename=ARTIFACT_FILENAME,
            size=len(payload),
            sha256=digest,
            source_url="https://www.magewell.com/official-test-package.zip",
        ),
    )
    return digest


def arm_only_firmware(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_FIRMWARE_UPDATES", "true")
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "false")
    monkeypatch.setenv("ENABLE_CREDENTIAL_ROTATION", "false")


def test_firmware_effect_boundary_requires_single_enabled_mode(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_FIRMWARE_UPDATES", "false")
    with pytest.raises(FirmwareSafetyError, match="locked"):
        require_firmware_effects(confirm=True)

    arm_only_firmware(monkeypatch)
    with pytest.raises(FirmwareSafetyError, match="confirmation"):
        require_firmware_effects(confirm=False)

    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "true")
    with pytest.raises(FirmwareSafetyError, match="Invalid effect configuration"):
        require_firmware_effects(confirm=True)


@pytest.mark.parametrize(
    ("profile", "rotation", "firmware_enabled"),
    [
        (True, True, False),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ],
)
def test_firmware_rejects_every_multi_effect_configuration(
    monkeypatch, profile: bool, rotation: bool, firmware_enabled: bool
) -> None:
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", str(profile).lower())
    monkeypatch.setenv("ENABLE_CREDENTIAL_ROTATION", str(rotation).lower())
    monkeypatch.setenv("ENABLE_FIRMWARE_UPDATES", str(firmware_enabled).lower())
    with pytest.raises(FirmwareSafetyError):
        require_firmware_effects(confirm=True)


def test_artifact_requires_approved_manifest_hash_size_and_name(monkeypatch, tmp_path) -> None:
    artifact = tmp_path / ARTIFACT_FILENAME
    payload = b"official-test-artifact"
    digest = install_test_manifest(monkeypatch, artifact, payload)
    metadata = validate_artifact(artifact, TARGET_VERSION)
    assert metadata["sha256"] == digest
    assert metadata["size"] == len(payload)
    assert metadata["hardware"] == "B"

    artifact.write_bytes(b"wrong-artifact")
    with pytest.raises(FirmwareSafetyError, match="size mismatch|SHA-256 mismatch"):
        validate_artifact(artifact, TARGET_VERSION)


def test_upload_uses_the_same_descriptor_that_was_hashed(monkeypatch, tmp_path) -> None:
    artifact_path = tmp_path / ARTIFACT_FILENAME
    original = b"validated-bytes"
    install_test_manifest(monkeypatch, artifact_path, original)
    with open_validated_artifact(artifact_path, TARGET_VERSION) as artifact:
        artifact_path.unlink()
        artifact_path.write_bytes(b"replacement-bytes")
        assert artifact.file.read() == original


@pytest.mark.parametrize(
    "bad_status",
    [
        {},
        {"cur-status": 0},
        {
            "cur-status": "0",
            "live-status": {"result": 27, "run-ms": 0, "live": []},
            "upgrade-status": {
                "result": 27,
                "step": 0,
                "percent": 0,
                "mode": "none",
                "client-id": "",
            },
        },
        {
            "cur-status": 0,
            "live-status": {"result": 27, "run-ms": 0},
            "upgrade-status": {
                "result": 27,
                "step": 0,
                "percent": 0,
                "mode": "none",
                "client-id": "",
            },
        },
        {
            "cur-status": 0,
            "live-status": {"result": 27, "run-ms": 0, "live": []},
            "upgrade-status": {"result": 99},
        },
    ],
)
def test_idle_status_rejects_empty_partial_malformed_and_unknown(bad_status) -> None:
    with pytest.raises(FirmwareSafetyError):
        assert_idle_status(bad_status)


def test_preflight_blocks_busy_or_streaming_device() -> None:
    busy = valid_status()
    busy["cur-status"] = 0x4000
    with pytest.raises(FirmwareSafetyError, match="running-status"):
        assert_idle_status(busy)

    streaming = valid_status()
    streaming["live-status"]["live"] = [
        {
            "id": 0,
            "type": 130,
            "is-use": 1,
            "is-skd-runnung": 0,
            "result": 22,
            "run-ms": 10,
        }
    ]
    with pytest.raises(FirmwareSafetyError, match="live stream"):
        assert_idle_status(streaming)


@pytest.mark.parametrize(
    "active_mask",
    [
        0x01,
        0x02,
        0x04,
        0x08,
        0x1000,
        0x4000,
        0x8000,
        0x20000,
        0x100000,
        0x200000,
        0x400000,
        0x800000,
        0x1000000,
        0x2000000,
        0x4000000,
        0x20000000,
        0x40000000,
    ],
)
def test_every_known_active_status_mask_is_blocked(active_mask) -> None:
    status = valid_status()
    status["cur-status"] = active_mask
    with pytest.raises(FirmwareSafetyError, match="running-status"):
        assert_idle_status(status)


def test_documented_empty_and_configured_idle_activity_are_accepted() -> None:
    documented_idle = valid_status()
    documented_idle["live-status"] = {"live": []}
    assert_idle_status(documented_idle)

    configured_idle = valid_status()
    configured_idle["live-status"]["live"] = [
        {
            "id": 0,
            "type": 130,
            "is-use": 1,
            "is-skd-runnung": 0,
            "result": 27,
            "run-ms": 0,
        }
    ]
    configured_idle["rec-status"]["rec"] = [
        {
            "id": 1,
            "type": 1,
            "is-use": 1,
            "is-skd-running": 0,
            "result": 27,
            "run-ms": 0,
        }
    ]
    assert_idle_status(configured_idle)

    current_firmware_idle = valid_status()
    current_firmware_idle["live-status"]["result"] = 0
    current_firmware_idle["rec-status"].update({"result": 0, "run-ms": 0})
    with pytest.raises(FirmwareSafetyError, match="live status"):
        assert_idle_status(current_firmware_idle)
    assert_idle_status(current_firmware_idle, post_update=True)


def test_background_wifi_is_allowed_only_for_post_update_verification() -> None:
    status = valid_status()
    status["cur-status"] = 0x400010
    with pytest.raises(FirmwareSafetyError, match="running-status"):
        assert_idle_status(status)
    assert assert_idle_status(status, post_update=True) == 0x400000


def test_post_update_wrapper_result_zero_requires_empty_activity_lists() -> None:
    live = valid_status()
    live["live-status"].update(
        {
            "result": 0,
            "live": [
                {
                    "id": 0,
                    "type": 130,
                    "is-use": 1,
                    "is-skd-runnung": 0,
                    "result": 27,
                    "run-ms": 0,
                }
            ],
        }
    )
    with pytest.raises(FirmwareSafetyError, match="empty stream list"):
        assert_idle_status(live, post_update=True)

    recording = valid_status()
    recording["rec-status"].update(
        {
            "result": 0,
            "run-ms": 0,
            "rec": [
                {
                    "id": 1,
                    "type": 1,
                    "is-use": 1,
                    "is-skd-runnung": 0,
                    "result": 27,
                    "run-ms": 0,
                }
            ],
        }
    )
    with pytest.raises(FirmwareSafetyError, match="empty recording list"):
        assert_idle_status(recording, post_update=True)


def test_scheduled_live_and_recording_activity_are_blocked() -> None:
    scheduled_live = valid_status()
    scheduled_live["live-status"]["live"] = [
        {
            "id": 0,
            "type": 130,
            "is-use": 1,
            "is-skd-runnung": 1,
            "result": 27,
            "run-ms": 0,
        }
    ]
    with pytest.raises(FirmwareSafetyError, match="live stream"):
        assert_idle_status(scheduled_live)

    recording = valid_status()
    recording["rec-status"]["rec"] = [
        {
            "id": 1,
            "type": 1,
            "is-use": 1,
            "is-skd-runnung": 0,
            "result": 2,
            "run-ms": 1700,
        }
    ]
    with pytest.raises(FirmwareSafetyError, match="recording"):
        assert_idle_status(recording)

    recording_mask = valid_status()
    recording_mask["cur-status"] = 0x02
    with pytest.raises(FirmwareSafetyError, match="running-status"):
        assert_idle_status(recording_mask)


def test_device_info_requires_exact_immutable_identity() -> None:
    observed = validate_device_info(valid_info(), TARGET_VERSION)
    assert observed["serial"] == "A305200908002"
    assert observed["eth_mac"] == "d0:c8:57:80:3a:70"
    assert observed["already_current"] is False

    wrong_hardware = valid_info()
    wrong_hardware["product"]["hardware-ver"] = "C"
    with pytest.raises(FirmwareSafetyError, match="identity mismatch"):
        validate_device_info(wrong_hardware, TARGET_VERSION)

    missing_serial = valid_info()
    del missing_serial["product"]["sn"]
    with pytest.raises(FirmwareSafetyError, match="serial"):
        validate_device_info(missing_serial, TARGET_VERSION)


def test_device_info_blocks_downgrade() -> None:
    with pytest.raises(FirmwareSafetyError, match="downgrade"):
        validate_device_info(valid_info("2.4.288"), "2.4.210")


def test_settings_preservation_accepts_only_observed_firmware_defaults_and_transients() -> None:
    before = {
        "name": "ENCODER-01",
        "profile": "camera",
        "living": {"ttl": 0},
        "stream-server": [{"id": 0, "name": "SRT"}],
        "wifi": [{"ssid": "", "level": -74}],
    }
    after = copy.deepcopy(before)
    after["wifi"][0]["level"] = -76
    after.update(
        {
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
    )
    after["living"]["live-keep-last"] = 1
    after["stream-server"][0].update(
        {
            "audio-pids": [0] * 8,
            "is-custom-pid": 0,
            "pcr-pid": 0,
            "pmt-pid": 0,
            "video-pid": 0,
        }
    )
    report = settings_preservation_report(before, after)
    assert report["preserved"] is True
    assert report["unexpected_change_paths"] == []
    assert "enable-zen-master" in report["accepted_firmware_additions"]
    assert report["ignored_transient_paths"] == ["after.wifi.0.level", "before.wifi.0.level"]

    after["profile"] = "unexpected-change"
    changed = settings_preservation_report(before, after)
    assert changed["preserved"] is False
    assert changed["unexpected_change_paths"] == ["profile"]


def test_recovery_backup_is_private_durable_and_never_overwritten(tmp_path) -> None:
    run_dir = tmp_path / "recovery" / "serial" / "hash"
    backup = write_recovery_backup(
        run_dir,
        "192.0.2.10",
        "ENCODER-01",
        {"name": "ENCODER-01", "secret-setting": "kept-private"},
        {"firmware": "2.3.206"},
    )
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert json.loads(backup.read_text())["settings"]["secret-setting"] == "kept-private"
    with pytest.raises(FileExistsError):
        write_recovery_backup(
            run_dir,
            "192.0.2.10",
            "ENCODER-01",
            {"name": "ENCODER-01"},
            {"firmware": "2.3.206"},
        )


def test_effect_state_is_fixed_per_serial_and_artifact(monkeypatch, tmp_path) -> None:
    artifact_path = tmp_path / ARTIFACT_FILENAME
    digest = install_test_manifest(monkeypatch, artifact_path, b"artifact")
    metadata = {"sha256": digest}
    root = tmp_path / "recovery"
    run_dir = acquire_effect_state(root, valid_preflight(), metadata)
    assert run_dir == root / "A305200908002" / digest
    with pytest.raises(FirmwareSafetyError, match="durable firmware-effect receipt"):
        acquire_effect_state(root, valid_preflight(), metadata)


class FakeClientSession:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def install_orchestration_fakes(monkeypatch, post_settings: dict | None = None) -> dict[str, int]:
    calls = {"report": 0, "info": 0, "status": 0, "upload": 0, "install": 0, "verify": 0}
    settings = {"name": "ENCODER-01", "profile": "camera"}

    async def fake_preflight(*args, **kwargs):
        return valid_preflight()

    async def fake_login(*args, **kwargs):
        return "sid=test"

    async def fake_report(*args, **kwargs):
        calls["report"] += 1
        return copy.deepcopy(settings)

    async def fake_info(*args, **kwargs):
        calls["info"] += 1
        return valid_info()

    async def fake_status(*args, **kwargs):
        calls["status"] += 1
        return valid_status()

    async def fake_upload(*args, **kwargs):
        calls["upload"] += 1
        return {"status": 0, "version": TARGET_VERSION, "size": 1}

    async def fake_install(*args, **kwargs):
        calls["install"] += 1
        return {"result": 0}

    async def fake_verify(*args, **kwargs):
        calls["verify"] += 1
        final_settings = copy.deepcopy(post_settings if post_settings is not None else settings)
        return (
            {
                **validate_device_info(valid_info(TARGET_VERSION), TARGET_VERSION),
                "name": "ENCODER-01",
                "settings_sha256": firmware.settings_fingerprint(final_settings),
            },
            final_settings,
        )

    monkeypatch.setattr(firmware.aiohttp, "ClientSession", FakeClientSession)
    monkeypatch.setattr(firmware, "preflight_one", fake_preflight)
    monkeypatch.setattr(firmware, "login_device", fake_login)
    monkeypatch.setattr(firmware, "get_device_credentials", lambda: ("Admin", "password"))
    monkeypatch.setattr(firmware, "get_device_report_with_login", fake_report)
    monkeypatch.setattr(firmware, "get_device_info", fake_info)
    monkeypatch.setattr(firmware, "get_device_status", fake_status)
    monkeypatch.setattr(firmware, "upload_firmware_once", fake_upload)
    monkeypatch.setattr(firmware, "start_firmware_update_once", fake_install)
    monkeypatch.setattr(firmware, "wait_for_verified_firmware", fake_verify)
    return calls


def test_update_revalidates_identity_and_idle_then_submits_exactly_once(
    monkeypatch, tmp_path
) -> None:
    arm_only_firmware(monkeypatch)
    artifact_path = tmp_path / ARTIFACT_FILENAME
    install_test_manifest(monkeypatch, artifact_path, b"artifact")
    calls = install_orchestration_fakes(monkeypatch)

    result = asyncio.run(
        update_one(
            "192.0.2.10",
            "ENCODER-01",
            "A305200908002",
            "d0:c8:57:80:3a:70",
            TARGET_VERSION,
            artifact_path,
            confirm=True,
            recovery_root=tmp_path / "recovery",
        )
    )

    assert result["status"] == "updated-and-verified"
    assert calls == {"report": 2, "info": 2, "status": 2, "upload": 1, "install": 1, "verify": 1}
    events = (Path(result["recovery_state"]) / "firmware-events.jsonl").read_text()
    assert '"state":"uploaded"' in events
    assert '"state":"install-accepted"' in events


def test_unknown_upload_is_durable_and_never_starts_install(monkeypatch, tmp_path) -> None:
    arm_only_firmware(monkeypatch)
    artifact_path = tmp_path / ARTIFACT_FILENAME
    digest = install_test_manifest(monkeypatch, artifact_path, b"artifact")
    calls = install_orchestration_fakes(monkeypatch)

    async def unknown_upload(*args, **kwargs):
        calls["upload"] += 1
        raise FirmwareUploadResponseUnknown("upload unknown")

    monkeypatch.setattr(firmware, "upload_firmware_once", unknown_upload)
    with pytest.raises(FirmwareUploadResponseUnknown):
        asyncio.run(
            update_one(
                "192.0.2.10",
                "ENCODER-01",
                "A305200908002",
                "d0:c8:57:80:3a:70",
                TARGET_VERSION,
                artifact_path,
                confirm=True,
                recovery_root=tmp_path / "recovery",
            )
        )
    assert calls["upload"] == 1
    assert calls["install"] == 0
    state_path = tmp_path / "recovery" / "A305200908002" / digest / "firmware-state.json"
    assert json.loads(state_path.read_text())["state"] == "upload-unknown"


def test_unknown_install_is_recorded_and_only_verification_continues(monkeypatch, tmp_path) -> None:
    arm_only_firmware(monkeypatch)
    artifact_path = tmp_path / ARTIFACT_FILENAME
    install_test_manifest(monkeypatch, artifact_path, b"artifact")
    calls = install_orchestration_fakes(monkeypatch)

    async def unknown_install(*args, **kwargs):
        calls["install"] += 1
        raise FirmwareInstallResponseUnknown("install unknown")

    monkeypatch.setattr(firmware, "start_firmware_update_once", unknown_install)
    result = asyncio.run(
        update_one(
            "192.0.2.10",
            "ENCODER-01",
            "A305200908002",
            "d0:c8:57:80:3a:70",
            TARGET_VERSION,
            artifact_path,
            confirm=True,
            recovery_root=tmp_path / "recovery",
        )
    )
    assert result["status"] == "updated-and-verified"
    assert calls["install"] == 1
    assert calls["verify"] == 1
    events = (Path(result["recovery_state"]) / "firmware-events.jsonl").read_text()
    assert '"state":"install-unknown"' in events


def test_post_update_settings_change_stops_fleet_progress(monkeypatch, tmp_path) -> None:
    arm_only_firmware(monkeypatch)
    artifact_path = tmp_path / ARTIFACT_FILENAME
    install_test_manifest(monkeypatch, artifact_path, b"artifact")
    install_orchestration_fakes(
        monkeypatch,
        post_settings={"name": "ENCODER-01", "profile": "camera", "new-firmware-key": 1},
    )
    result = asyncio.run(
        update_one(
            "192.0.2.10",
            "ENCODER-01",
            "A305200908002",
            "d0:c8:57:80:3a:70",
            TARGET_VERSION,
            artifact_path,
            confirm=True,
            recovery_root=tmp_path / "recovery",
        )
    )
    assert result["status"] == "firmware-verified-settings-changed"
    assert result["settings_changes"] == {
        "added_top_level_keys": ["new-firmware-key"],
        "removed_top_level_keys": [],
        "changed_top_level_keys": [],
    }


def test_update_requires_serial_and_mac_from_reviewed_preflight(monkeypatch, tmp_path) -> None:
    arm_only_firmware(monkeypatch)
    artifact_path = tmp_path / ARTIFACT_FILENAME
    install_test_manifest(monkeypatch, artifact_path, b"artifact")
    calls = install_orchestration_fakes(monkeypatch)
    with pytest.raises(FirmwareSafetyError, match="does not match"):
        asyncio.run(
            update_one(
                "192.0.2.10",
                "ENCODER-01",
                "WRONG-SERIAL",
                "d0:c8:57:80:3a:70",
                TARGET_VERSION,
                artifact_path,
                confirm=True,
                recovery_root=tmp_path / "recovery",
            )
        )
    assert calls["upload"] == 0
    assert calls["install"] == 0
    assert not (tmp_path / "recovery").exists()


def test_changed_settings_after_backup_stop_before_upload(monkeypatch, tmp_path) -> None:
    arm_only_firmware(monkeypatch)
    artifact_path = tmp_path / ARTIFACT_FILENAME
    digest = install_test_manifest(monkeypatch, artifact_path, b"artifact")
    calls = install_orchestration_fakes(monkeypatch)

    async def changing_report(*args, **kwargs):
        calls["report"] += 1
        if calls["report"] == 1:
            return {"name": "ENCODER-01", "profile": "camera"}
        return {"name": "ENCODER-01", "profile": "changed-after-backup"}

    monkeypatch.setattr(firmware, "get_device_report_with_login", changing_report)
    with pytest.raises(FirmwareSafetyError, match="changed after the recovery backup"):
        asyncio.run(
            update_one(
                "192.0.2.10",
                "ENCODER-01",
                "A305200908002",
                "d0:c8:57:80:3a:70",
                TARGET_VERSION,
                artifact_path,
                confirm=True,
                recovery_root=tmp_path / "recovery",
            )
        )
    assert calls["upload"] == 0
    assert calls["install"] == 0
    run_dir = tmp_path / "recovery" / "A305200908002" / digest
    assert json.loads((run_dir / "firmware-state.json").read_text())["state"] == (
        "pre-upload-settings-changed"
    )


def test_recovery_verification_is_read_only_and_accepts_known_post_update_shape(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("ALLOWED_SUBNET", "192.0.2.0/24")
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "false")
    monkeypatch.setenv("ENABLE_CREDENTIAL_ROTATION", "false")
    monkeypatch.setenv("ENABLE_FIRMWARE_UPDATES", "false")
    artifact_path = tmp_path / ARTIFACT_FILENAME
    digest = install_test_manifest(monkeypatch, artifact_path, b"artifact")
    before = {
        "name": "ENCODER-01",
        "profile": "camera",
        "wifi": [{"ssid": "", "level": -74}],
    }
    after = copy.deepcopy(before)
    after["wifi"][0]["level"] = -76
    after.update(
        {
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
    )
    run_dir = acquire_effect_state(tmp_path / "recovery", valid_preflight(), {"sha256": digest})
    write_recovery_backup(
        run_dir,
        "192.0.2.10",
        "ENCODER-01",
        before,
        valid_preflight(),
    )

    async def fake_login(*args, **kwargs):
        return "sid=test"

    async def fake_info(*args, **kwargs):
        return valid_info(TARGET_VERSION)

    async def fake_report(*args, **kwargs):
        return copy.deepcopy(after)

    async def fake_status(*args, **kwargs):
        status = valid_status()
        status["cur-status"] = 0x400010
        status["live-status"]["result"] = 0
        status["rec-status"].update({"result": 0, "run-ms": 0})
        return status

    monkeypatch.setattr(firmware.aiohttp, "ClientSession", FakeClientSession)
    monkeypatch.setattr(firmware, "login_device", fake_login)
    monkeypatch.setattr(firmware, "get_device_credentials", lambda: ("Admin", "password"))
    monkeypatch.setattr(firmware, "get_device_info", fake_info)
    monkeypatch.setattr(firmware, "get_device_report_with_login", fake_report)
    monkeypatch.setattr(firmware, "get_device_status", fake_status)

    result = asyncio.run(
        verify_one(
            "192.0.2.10",
            "ENCODER-01",
            "A305200908002",
            "d0:c8:57:80:3a:70",
            TARGET_VERSION,
            recovery_root=tmp_path / "recovery",
        )
    )
    assert result["status"] == "recovery-verified"
    assert result["background_status_bits"] == 0x400000
    assert result["preservation"]["preserved"] is True
    assert json.loads((run_dir / "firmware-state.json").read_text())["state"] == (
        "recovery-verified"
    )
