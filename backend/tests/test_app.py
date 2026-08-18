import os

from fastapi.testclient import TestClient

from backend.app import app, public_device_list, validate_scan_network
from backend.settings_merge import get_bulk_update_settings

os.environ.setdefault("ALLOWED_SUBNET", "192.0.2.0/24")
os.environ.setdefault("ENABLE_DEVICE_WRITES", "false")


client = TestClient(app)


def test_health_reports_safe_write_boundary() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "allowed_subnet": "192.0.2.0/24",
        "device_reads_configured": False,
        "device_writes_enabled": False,
    }


def test_scan_must_stay_inside_allowed_subnet() -> None:
    response = client.get("/discover-magewell", params={"subnet": "198.51.100.0/24"})
    assert response.status_code == 400
    assert "within ALLOWED_SUBNET" in response.json()["detail"]


def test_write_endpoint_is_locked_before_network_access() -> None:
    response = client.post(
        "/push-updates",
        json={
            "confirm": True,
            "devices": [{"ip": "192.0.2.10", "magewell_id": "ENCODER-01"}],
        },
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
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Explicit write confirmation is required."


def test_csv_rejects_blank_identity_before_network_access(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_DEVICE_WRITES", "true")
    monkeypatch.setenv("MAGEWELL_USERNAME", "test-user")
    monkeypatch.setenv("MAGEWELL_PASSWORD", "test-password")
    response = client.post(
        "/bulk-update",
        params={"confirm": "true"},
        files={"file": ("devices.csv", "Magewell ID,Magewell IP\n,192.0.2.10\n", "text/csv")},
    )
    assert response.status_code == 400
    assert "CSV row 2" in response.json()["detail"]


def test_scan_host_cap_is_enforced(monkeypatch) -> None:
    monkeypatch.setenv("ALLOWED_SUBNET", "10.0.0.0/8")
    monkeypatch.setenv("MAX_SCAN_HOSTS", "100")
    response = client.get("/discover-magewell", params={"subnet": "10.0.0.0/24"})
    assert response.status_code == 400
    assert "MAX_SCAN_HOSTS" in response.json()["detail"]


def test_control_merge_preserves_target_recording_names() -> None:
    merged = get_bulk_update_settings(
        "TARGET-01",
        {"rec-channels": [{"dir-name": "CONTROL"}], "enable-deinterlace": 1},
    )
    assert merged["enable-deinterlace"] == 1
    assert merged["rec-channels"][0]["dir-name"] == "TARGET-01_REC_Folder"


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
