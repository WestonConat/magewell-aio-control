import asyncio
import os

import aiohttp
import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.app import (
    OPERATOR_INTENT_VALUE,
    PushUpdateRequest,
    app,
    public_device_list,
    push_update_for_device,
    push_updates,
    safe_device_error,
    settings_fingerprint,
    validate_scan_network,
)
from backend.settings_merge import get_bulk_update_settings

os.environ.setdefault("ALLOWED_SUBNET", "192.0.2.0/24")
os.environ.setdefault("ENABLE_DEVICE_WRITES", "false")


client = TestClient(app)
OPERATOR_HEADERS = {"X-Magewell-Operator-Intent": OPERATOR_INTENT_VALUE}


def test_health_reports_safe_write_boundary() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "allowed_subnet": "192.0.2.0/24",
        "device_reads_configured": False,
        "device_writes_enabled": False,
        "credential_rotation_configured": False,
        "credential_rotation_enabled": False,
    }


def test_scan_must_stay_inside_allowed_subnet() -> None:
    response = client.get(
        "/discover-magewell",
        params={"subnet": "198.51.100.0/24"},
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 400
    assert "within ALLOWED_SUBNET" in response.json()["detail"]


def test_scan_requires_operator_intent_before_network_access() -> None:
    response = client.get("/discover-magewell", params={"subnet": "192.0.2.0/24"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Explicit operator intent is required."


def test_write_endpoint_is_locked_before_network_access() -> None:
    response = client.post(
        "/push-updates",
        json={
            "confirm": True,
            "devices": [{"ip": "192.0.2.10", "magewell_id": "ENCODER-01"}],
        },
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 403
    assert "Device writes are locked" in response.json()["detail"]


def test_write_endpoint_requires_request_confirmation(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "true")
    response = client.post(
        "/push-updates",
        json={
            "confirm": False,
            "devices": [{"ip": "192.0.2.10", "magewell_id": "ENCODER-01"}],
        },
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Explicit write confirmation is required."


def test_embedded_baseline_endpoint_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "true")
    response = client.post(
        "/bulk-update",
        params={"confirm": "true"},
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 409
    assert "Embedded baseline writes are disabled" in response.json()["detail"]


def test_credential_rotation_is_locked_before_network_access(monkeypatch) -> None:
    monkeypatch.setenv("MAGEWELL_USERNAME", "Admin")
    monkeypatch.setenv("MAGEWELL_PASSWORD", "new-password")
    monkeypatch.setenv("MAGEWELL_OLD_PASSWORD", "old-password")
    response = client.post(
        "/rotate-credential",
        json={
            "confirm": True,
            "device": {"ip": "192.0.2.10", "magewell_id": "ENCODER-01"},
        },
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 403
    assert "Credential rotation is locked" in response.json()["detail"]


def test_credential_rotation_requires_profile_writes_to_be_locked(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_CREDENTIAL_ROTATION", "true")
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "true")
    monkeypatch.setenv("MAGEWELL_USERNAME", "Admin")
    monkeypatch.setenv("MAGEWELL_PASSWORD", "new-password")
    monkeypatch.setenv("MAGEWELL_OLD_PASSWORD", "old-password")
    response = client.post(
        "/rotate-credential",
        json={
            "confirm": True,
            "device": {"ip": "192.0.2.10", "magewell_id": "ENCODER-01"},
        },
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 409
    assert "cannot be enabled together" in response.json()["detail"]


def test_scan_host_cap_is_enforced(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_SUBNET", "10.0.0.0/8")
    monkeypatch.setenv("MAX_SCAN_HOSTS", "100")
    response = client.get(
        "/discover-magewell",
        params={"subnet": "10.0.0.0/24"},
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 400
    assert "MAX_SCAN_HOSTS" in response.json()["detail"]


def test_live_profile_preserves_target_local_settings() -> None:
    source = {
        "name": "CONTROL",
        "wifi": [{"ssid": "control"}],
        "rec-channels": [{"dir-name": "CONTROL"}],
        "enable-deinterlace": 1,
    }
    target = {
        "name": "TARGET-01",
        "wifi": [{"ssid": "target"}],
        "rec-channels": [{"dir-name": "TARGET-01"}],
        "enable-deinterlace": 0,
    }
    frozen = get_bulk_update_settings(
        "TARGET-01",
        source,
        target,
    )
    assert frozen == {
        "name": "TARGET-01",
        "wifi": [{"ssid": "target"}],
        "rec-channels": [{"dir-name": "TARGET-01"}],
        "enable-deinterlace": 1,
    }
    assert frozen is not source
    assert frozen["rec-channels"] is not source["rec-channels"]
    assert frozen["rec-channels"] is not target["rec-channels"]
    frozen["rec-channels"][0]["dir-name"] = "CHANGED"
    assert source["rec-channels"][0]["dir-name"] == "CONTROL"
    assert target["rec-channels"][0]["dir-name"] == "TARGET-01"


def test_live_profile_rejects_schema_or_identity_mismatch() -> None:
    with pytest.raises(ValueError, match="identity"):
        get_bulk_update_settings("TARGET-01", {"name": "CONTROL"}, {"name": "OTHER"})
    with pytest.raises(ValueError, match="schemas differ"):
        get_bulk_update_settings(
            "TARGET-01",
            {"name": "CONTROL", "profile": "camera"},
            {"name": "TARGET-01"},
        )


def test_device_settings_are_not_returned_to_the_browser() -> None:
    assert public_device_list(
        [
            {
                "ip": "192.0.2.10",
                "name": "ENCODER-01",
                "settings": {"wifi": [{"passwd": "secret"}]},
            }
        ]
    ) == [{"ip": "192.0.2.10", "name": "ENCODER-01"}]


def test_loopback_default_is_a_valid_single_host(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_SUBNET", "127.0.0.1/32")
    assert str(validate_scan_network("127.0.0.1/32")) == "127.0.0.1/32"


def test_cross_origin_baseline_request_is_rejected_before_route_logic(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "true")
    response = client.post(
        "/bulk-update",
        params={"confirm": "true"},
        headers={
            "Origin": "https://untrusted.example",
            "X-Magewell-Operator-Intent": OPERATOR_INTENT_VALUE,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Browser origin is not allowed."


def test_device_network_errors_do_not_expose_credential_urls(monkeypatch, caplog) -> None:
    secret_error = aiohttp.ClientConnectionError(
        "http://192.0.2.10/usapi?method=login&id=Admin&pass=credential-hash"
    )

    async def failed_login(*args, **kwargs):
        raise secret_error

    monkeypatch.setattr(app_module, "login_device", failed_login)

    async def run_failure() -> dict[str, str]:
        return await push_update_for_device(
            object(),
            "192.0.2.10",
            "ENCODER-01",
            {},
            "Admin",
            "plaintext-password",
        )

    result = asyncio.run(run_failure())
    assert result["status"] == "failed"
    assert result["error"] == safe_device_error(secret_error)
    assert "Admin" not in result["error"]
    assert "credential-hash" not in result["error"]
    assert "credential-hash" not in caplog.text


def test_ambiguous_device_error_does_not_retry_import(monkeypatch) -> None:
    mutation_calls = 0

    async def successful_login(*args, **kwargs):
        return "session-cookie"

    async def ambiguous_import(*args, **kwargs):
        nonlocal mutation_calls
        mutation_calls += 1
        raise aiohttp.ServerDisconnectedError("ambiguous response")

    monkeypatch.setattr(app_module, "login_device", successful_login)
    monkeypatch.setattr(app_module, "import_settings_call", ambiguous_import)

    async def run_failure() -> dict[str, str]:
        return await push_update_for_device(
            object(), "192.0.2.10", "ENCODER-01", {}, "test-user", "test-password"
        )

    result = asyncio.run(run_failure())
    assert result["status"] == "failed"
    assert mutation_calls == 1


def test_credential_rotation_is_single_device_and_verified(monkeypatch) -> None:
    mutation_calls = 0

    async def report(*args, **kwargs):
        return {"name": "ENCODER-01"}

    async def login(*args, **kwargs):
        return "session-cookie"

    async def users(*args, **kwargs):
        return [{"id": "Admin", "type": 1}]

    async def rotate(*args, **kwargs):
        nonlocal mutation_calls
        mutation_calls += 1

    monkeypatch.setenv("ENABLE_CREDENTIAL_ROTATION", "true")
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "false")
    monkeypatch.setenv("MAGEWELL_USERNAME", "Admin")
    monkeypatch.setenv("MAGEWELL_PASSWORD", "new-password")
    monkeypatch.setenv("MAGEWELL_OLD_PASSWORD", "old-password")
    monkeypatch.setattr(app_module, "get_device_report_with_login", report)
    monkeypatch.setattr(app_module, "login_device", login)
    monkeypatch.setattr(app_module, "get_users_call", users)
    monkeypatch.setattr(app_module, "set_password_call", rotate)
    app.state.rotation_devices = [
        {
            "ip": "192.0.2.10",
            "name": "ENCODER-01",
            "credential_state": "old",
        }
    ]
    app.state.rotation_unknown_ips = set()
    response = client.post(
        "/rotate-credential",
        json={
            "confirm": True,
            "device": {"ip": "192.0.2.10", "magewell_id": "ENCODER-01"},
        },
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rotated-and-verified"
    assert mutation_calls == 1
    assert app.state.rotation_devices[0]["credential_state"] == "new"


def test_ambiguous_credential_rotation_requires_fresh_inventory(monkeypatch) -> None:
    mutation_calls = 0

    async def report(*args, **kwargs):
        return {"name": "ENCODER-01"}

    async def login(*args, **kwargs):
        return "session-cookie"

    async def users(*args, **kwargs):
        return [{"id": "Admin", "type": 1}]

    async def ambiguous_rotation(*args, **kwargs):
        nonlocal mutation_calls
        mutation_calls += 1
        raise aiohttp.ServerDisconnectedError("ambiguous response")

    monkeypatch.setenv("ENABLE_CREDENTIAL_ROTATION", "true")
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "false")
    monkeypatch.setenv("MAGEWELL_USERNAME", "Admin")
    monkeypatch.setenv("MAGEWELL_PASSWORD", "new-password")
    monkeypatch.setenv("MAGEWELL_OLD_PASSWORD", "old-password")
    monkeypatch.setattr(app_module, "get_device_report_with_login", report)
    monkeypatch.setattr(app_module, "login_device", login)
    monkeypatch.setattr(app_module, "get_users_call", users)
    monkeypatch.setattr(app_module, "set_password_call", ambiguous_rotation)
    app.state.rotation_devices = [
        {
            "ip": "192.0.2.10",
            "name": "ENCODER-01",
            "credential_state": "old",
        }
    ]
    app.state.rotation_unknown_ips = set()
    request = {
        "confirm": True,
        "device": {"ip": "192.0.2.10", "magewell_id": "ENCODER-01"},
    }
    first_response = client.post("/rotate-credential", json=request, headers=OPERATOR_HEADERS)
    second_response = client.post("/rotate-credential", json=request, headers=OPERATOR_HEADERS)
    assert first_response.status_code == 502
    assert second_response.status_code == 409
    assert "fresh credential inventory" in second_response.json()["detail"]
    assert mutation_calls == 1


def test_already_rotated_device_is_verified_without_mutation(monkeypatch) -> None:
    async def report(*args, **kwargs):
        return {"name": "ENCODER-01"}

    async def forbidden_mutation(*args, **kwargs):
        raise AssertionError("already-rotated device must not be mutated")

    monkeypatch.setenv("ENABLE_CREDENTIAL_ROTATION", "true")
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "false")
    monkeypatch.setenv("MAGEWELL_USERNAME", "Admin")
    monkeypatch.setenv("MAGEWELL_PASSWORD", "new-password")
    monkeypatch.setenv("MAGEWELL_OLD_PASSWORD", "old-password")
    monkeypatch.setattr(app_module, "get_device_report_with_login", report)
    monkeypatch.setattr(app_module, "set_password_call", forbidden_mutation)
    app.state.rotation_devices = [
        {
            "ip": "192.0.2.10",
            "name": "ENCODER-01",
            "credential_state": "new",
        }
    ]
    app.state.rotation_unknown_ips = set()
    response = client.post(
        "/rotate-credential",
        json={
            "confirm": True,
            "device": {"ip": "192.0.2.10", "magewell_id": "ENCODER-01"},
        },
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "already-rotated"


def test_concurrent_write_batch_is_rejected_before_second_mutation(monkeypatch) -> None:
    mutation_started = asyncio.Event()
    allow_completion = asyncio.Event()
    mutation_calls = 0

    async def slow_update(*args, **kwargs):
        nonlocal mutation_calls
        mutation_calls += 1
        mutation_started.set()
        await allow_completion.wait()
        return {"ip": "192.0.2.10", "magewell_id": "ENCODER-01", "status": "updated"}

    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "true")
    monkeypatch.setenv("MAGEWELL_USERNAME", "test-user")
    monkeypatch.setenv("MAGEWELL_PASSWORD", "test-password")
    monkeypatch.setattr(app_module, "push_update_for_device", slow_update)
    app.state.devices = [
        {
            "ip": "192.0.2.10",
            "name": "ENCODER-01",
            "settings": {"name": "ENCODER-01", "profile": "old"},
        }
    ]
    app.state.control_settings = {"name": "SOURCE-01", "profile": "camera"}
    app.state.control_device_ip = "192.0.2.20"
    app.state.control_settings_sha256 = settings_fingerprint(app.state.control_settings)
    request = PushUpdateRequest(
        confirm=True,
        devices=[{"ip": "192.0.2.10", "magewell_id": "ENCODER-01"}],
    )

    async def run_concurrent_batches() -> None:
        app.state.mutation_lock = asyncio.Lock()
        first = asyncio.create_task(push_updates(request, OPERATOR_INTENT_VALUE, None))
        await mutation_started.wait()
        try:
            await push_updates(request, OPERATOR_INTENT_VALUE, None)
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 409
        else:
            raise AssertionError("Concurrent write batch was not rejected")
        allow_completion.set()
        await first

    asyncio.run(run_concurrent_batches())
    assert mutation_calls == 1


def test_control_source_cannot_be_a_write_target(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "true")
    monkeypatch.setenv("MAGEWELL_USERNAME", "test-user")
    monkeypatch.setenv("MAGEWELL_PASSWORD", "test-password")
    app.state.devices = [
        {"ip": "192.0.2.10", "name": "SOURCE-01", "settings": {"profile": "camera"}}
    ]
    app.state.control_settings = {"profile": "camera"}
    app.state.control_device_ip = "192.0.2.10"
    app.state.control_settings_sha256 = settings_fingerprint(app.state.control_settings)
    response = client.post(
        "/push-updates",
        json={
            "confirm": True,
            "devices": [{"ip": "192.0.2.10", "magewell_id": "SOURCE-01"}],
        },
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "The control source cannot be a write target."


def test_verify_target_returns_only_fingerprints(monkeypatch) -> None:
    source = {"name": "SOURCE-01", "profile": {"mode": "camera"}}
    target_before = {"name": "TARGET-01", "profile": {"mode": "old"}}
    expected = {"name": "TARGET-01", "profile": {"mode": "camera"}}

    async def matching_report(*args, **kwargs):
        return expected

    monkeypatch.setenv("MAGEWELL_USERNAME", "test-user")
    monkeypatch.setenv("MAGEWELL_PASSWORD", "test-password")
    monkeypatch.setattr(app_module, "get_device_report_with_login", matching_report)
    app.state.devices = [{"ip": "192.0.2.10", "name": "TARGET-01", "settings": target_before}]
    app.state.control_device_ip = "192.0.2.20"
    app.state.control_settings = source
    app.state.control_settings_sha256 = settings_fingerprint(source)
    response = client.post(
        "/verify-target",
        json={"device": {"ip": "192.0.2.10", "magewell_id": "TARGET-01"}},
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 200
    assert response.json() == {
        "ip": "192.0.2.10",
        "magewell_id": "TARGET-01",
        "expected_settings_sha256": settings_fingerprint(expected),
        "actual_settings_sha256": settings_fingerprint(expected),
        "matches_expected_profile": True,
        "verification_attempts": 1,
    }


def test_verify_target_allows_bounded_read_only_settle(monkeypatch) -> None:
    source = {"name": "SOURCE-01", "profile": {"mode": "camera"}}
    target_before = {"name": "TARGET-01", "profile": {"mode": "old"}}
    expected = {"name": "TARGET-01", "profile": {"mode": "camera"}}
    reports = iter([target_before, expected])

    async def settling_report(*args, **kwargs):
        return next(reports)

    async def no_wait(*args, **kwargs):
        return None

    monkeypatch.setenv("MAGEWELL_USERNAME", "test-user")
    monkeypatch.setenv("MAGEWELL_PASSWORD", "test-password")
    monkeypatch.setattr(app_module, "get_device_report_with_login", settling_report)
    monkeypatch.setattr(app_module.asyncio, "sleep", no_wait)
    app.state.devices = [{"ip": "192.0.2.10", "name": "TARGET-01", "settings": target_before}]
    app.state.control_device_ip = "192.0.2.20"
    app.state.control_settings = source
    app.state.control_settings_sha256 = settings_fingerprint(source)
    response = client.post(
        "/verify-target",
        json={"device": {"ip": "192.0.2.10", "magewell_id": "TARGET-01"}},
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["matches_expected_profile"] is True
    assert response.json()["verification_attempts"] == 2
