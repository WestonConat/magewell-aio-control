import asyncio
import copy
from typing import Any

import pytest

from backend import video_color_experiment
from backend.video_color_experiment import (
    EXPECTED_COLOR_RANGE,
    EXPECTED_GET_INFO_SHA256,
    EXPECTED_IDENTITY_SHA256,
    EXPECTED_REPORT_SCHEMA_SHA256,
    Aio16VideoColorExperiment,
    Aio16VideoColorSnapshot,
    ExperimentPreflightError,
    build_aio16_video_color_preflight,
)


def settings() -> dict[str, Any]:
    # This fixture has only the approved color shape; its fingerprint values are
    # sanitized preconditions captured by the completed read-only evidence Task.
    return {
        "name": "AIO-16",
        "video-color": {
            "hdmi": {"contrast": 100, "brightness": 0, "saturation": 100, "hue": 0},
            "sdi": {"contrast": 100, "brightness": 0, "saturation": 100, "hue": 0},
        },
    }


@pytest.fixture(autouse=True)
def local_fixture_fingerprints(monkeypatch) -> None:
    """Bind tests to their sanitized fixture, never to a copied bench report."""
    local_settings = settings()
    monkeypatch.setattr(
        video_color_experiment,
        "EXPECTED_SETTINGS_SHA256",
        video_color_experiment.canonical_sha256(local_settings),
    )
    monkeypatch.setattr(
        video_color_experiment,
        "EXPECTED_VIDEO_COLOR_SHA256",
        video_color_experiment.canonical_sha256(local_settings["video-color"]),
    )


def snapshot(**overrides: Any) -> Aio16VideoColorSnapshot:
    values = {
        "identity_sha256": EXPECTED_IDENTITY_SHA256,
        "get_info_sha256": EXPECTED_GET_INFO_SHA256,
        "report_schema_sha256": EXPECTED_REPORT_SCHEMA_SHA256,
        "settings": settings(),
        "color_range": EXPECTED_COLOR_RANGE,
        "status_result": 0,
        "status_mask": 0x10010,
        "module": "Ultra Encode AIO",
        "hardware": "B",
        "product_id": 787,
        "firmware": "2.4.288",
        "api_version": "2.1",
    }
    values.update(overrides)
    return Aio16VideoColorSnapshot(**values)


def preflight():
    return build_aio16_video_color_preflight(snapshot())


def test_preflight_rejects_before_any_transport_is_selected() -> None:
    with pytest.raises(ExperimentPreflightError, match="status is not idle"):
        build_aio16_video_color_preflight(snapshot(status_mask=0x02))


def test_preflight_rejects_unsuccessful_status_before_any_transport_is_selected() -> None:
    with pytest.raises(ExperimentPreflightError, match="status is not idle"):
        build_aio16_video_color_preflight(snapshot(status_result=-9))


def test_preflight_rejects_unknown_status_bits_before_any_transport_is_selected() -> None:
    with pytest.raises(ExperimentPreflightError, match="status is not idle"):
        build_aio16_video_color_preflight(snapshot(status_mask=0x10010 | 0x8000000))


@pytest.mark.parametrize(
    "field,value", [("firmware", "2.4.289"), ("identity_sha256", "0" * 64), ("color_range", {})]
)
def test_preflight_rejects_fixture_drift(field: str, value: Any) -> None:
    with pytest.raises(ExperimentPreflightError):
        build_aio16_video_color_preflight(snapshot(**{field: value}))


def test_preflight_is_redacted_and_has_exact_forward_intent() -> None:
    result = preflight().redacted()
    assert result["forward_intent"]["color"] == {
        "contrast": 100,
        "brightness": 1,
        "saturation": 100,
        "hue": 0,
    }
    assert "settings" not in result
    assert "password" not in str(result).lower()
    assert "http" not in str(result).lower()


def test_preflight_rejects_raw_settings_that_do_not_match_its_fingerprint() -> None:
    stale = settings()
    stale["name"] = "STALE"
    with pytest.raises(ExperimentPreflightError, match="report fingerprint"):
        build_aio16_video_color_preflight(snapshot(settings=stale))


def test_forward_request_is_exactly_one_call_and_has_no_retry() -> None:
    calls: list[dict[str, Any]] = []

    async def send(params: dict[str, Any]) -> dict[str, int]:
        calls.append(dict(params))
        return {"result": 0}

    experiment = Aio16VideoColorExperiment(preflight())
    asyncio.run(experiment.submit_forward_once(send))
    assert calls == [
        {"method": "set-video-color", "contrast": 100, "brightness": 1, "saturation": 100, "hue": 0}
    ]
    assert experiment.state == "forward-submitted"


@pytest.mark.parametrize("response", [{"result": -9}, {}, {"result": 1}])
def test_non_success_marks_the_experiment_uncertain(response: dict[str, Any]) -> None:
    calls = 0

    async def send(_: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return response

    experiment = Aio16VideoColorExperiment(preflight())
    with pytest.raises(ExperimentPreflightError, match="definitive success"):
        asyncio.run(experiment.submit_forward_once(send))
    assert calls == 1
    assert experiment.state == "uncertain-high-risk"


def test_timeout_marks_the_experiment_uncertain_without_retry() -> None:
    calls = 0

    async def send(_: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise TimeoutError("secret transport detail")

    experiment = Aio16VideoColorExperiment(preflight())
    with pytest.raises(TimeoutError):
        asyncio.run(experiment.submit_forward_once(send))
    assert calls == 1
    assert experiment.state == "uncertain-high-risk"
    with pytest.raises(ExperimentPreflightError, match="not eligible"):
        asyncio.run(experiment.submit_forward_once(send))


def test_intents_are_immutable_and_reject_extra_or_missing_parameters() -> None:
    intent = preflight().forward_intent
    with pytest.raises(TypeError):
        intent.params["brightness"] = 2  # type: ignore[index]
    with pytest.raises(ExperimentPreflightError, match="intent"):
        video_color_experiment.VideoColorIntent(
            phase="forward",
            params={"method": "set-video-color", "brightness": 1},
        )
    with pytest.raises(ExperimentPreflightError, match="intent"):
        video_color_experiment.VideoColorIntent(
            phase="forward",
            params={
                "method": "set-video-color",
                "contrast": 100,
                "brightness": 1,
                "saturation": 100,
                "hue": 0,
                "unexpected": 1,
            },
        )


def test_dispatch_rejects_a_forced_mutated_intent_before_transport() -> None:
    intent = preflight().forward_intent
    object.__setattr__(intent, "params", {"method": "set-video-color", "brightness": 2})
    calls = 0

    async def send(_: dict[str, Any]) -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"result": 0}

    with pytest.raises(ExperimentPreflightError, match="intent"):
        asyncio.run(video_color_experiment.invoke_video_color_once(intent, send))
    assert calls == 0


def test_manually_constructed_preflight_cannot_bypass_fixture_binding() -> None:
    frozen = preflight()
    with pytest.raises(ExperimentPreflightError, match="preflight"):
        video_color_experiment.Aio16VideoColorPreflight(
            identity_sha256=frozen.identity_sha256,
            get_info_sha256=frozen.get_info_sha256,
            report_schema_sha256=frozen.report_schema_sha256,
            settings_sha256="0" * 64,
            video_color_sha256=frozen.video_color_sha256,
            forward_intent=frozen.forward_intent,
        )


@pytest.mark.parametrize(
    ("changed_inputs", "expected_mapping"),
    [(("hdmi", "sdi"), "hdmi-and-sdi"), (("hdmi",), "hdmi-only"), (("sdi",), "sdi-only")],
)
def test_definitive_readback_records_supported_mapping_and_allows_restore(
    changed_inputs: tuple[str, ...], expected_mapping: str
) -> None:
    before = settings()
    after = copy.deepcopy(before)
    for input_name in changed_inputs:
        after["video-color"][input_name]["brightness"] = 1
    experiment = Aio16VideoColorExperiment(preflight())
    asyncio.run(experiment.submit_forward_once(lambda _: _success()))
    assert (
        experiment.accept_forward_readback(EXPECTED_IDENTITY_SHA256, before, after)
        == expected_mapping
    )
    assert experiment.state == "restore-eligible"
    assert experiment.restore_intent().params["brightness"] == 0


def test_unrelated_drift_or_ambiguous_mapping_locks_restore() -> None:
    before = settings()
    after = copy.deepcopy(before)
    after["video-color"]["hdmi"]["brightness"] = 1
    after["name"] = "CHANGED"
    experiment = Aio16VideoColorExperiment(preflight())
    asyncio.run(experiment.submit_forward_once(lambda _: _success()))
    with pytest.raises(ExperimentPreflightError, match="unrelated settings drift"):
        experiment.accept_forward_readback(EXPECTED_IDENTITY_SHA256, before, after)
    assert experiment.state == "uncertain-high-risk"
    with pytest.raises(ExperimentPreflightError, match="eligible only"):
        experiment.restore_intent()


def test_restore_requires_definitive_forward_and_then_exact_baseline() -> None:
    experiment = Aio16VideoColorExperiment(preflight())
    with pytest.raises(ExperimentPreflightError, match="eligible only"):
        experiment.restore_intent()
    before = settings()
    after = copy.deepcopy(before)
    after["video-color"]["hdmi"]["brightness"] = 1
    after["video-color"]["sdi"]["brightness"] = 1
    asyncio.run(experiment.submit_forward_once(lambda _: _success()))
    experiment.accept_forward_readback(EXPECTED_IDENTITY_SHA256, before, after)
    calls: list[dict[str, Any]] = []

    async def restore(params: dict[str, Any]) -> dict[str, int]:
        calls.append(dict(params))
        return {"result": 0}

    asyncio.run(experiment.submit_restore_once(restore))
    assert calls[0]["brightness"] == 0
    experiment.accept_restore_readback(EXPECTED_IDENTITY_SHA256, before, before)
    assert experiment.state == "restored"


def test_identity_drift_in_readback_locks_the_experiment() -> None:
    before = settings()
    after = copy.deepcopy(before)
    after["video-color"]["hdmi"]["brightness"] = 1
    after["video-color"]["sdi"]["brightness"] = 1
    experiment = Aio16VideoColorExperiment(preflight())
    asyncio.run(experiment.submit_forward_once(lambda _: _success()))
    with pytest.raises(ExperimentPreflightError, match="identity"):
        experiment.accept_forward_readback("1" * 64, before, after)
    assert experiment.state == "uncertain-high-risk"


@pytest.mark.parametrize("failure", [TimeoutError(), ExperimentPreflightError("non-success")])
def test_restore_transport_failure_locks_the_experiment(failure: Exception) -> None:
    experiment, before = ready_for_restore()
    calls = 0

    async def fail(_: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise failure

    with pytest.raises(type(failure)):
        asyncio.run(experiment.submit_restore_once(fail))
    assert calls == 1
    assert experiment.state == "uncertain-high-risk"
    with pytest.raises(ExperimentPreflightError, match="eligible only"):
        experiment.restore_intent()


@pytest.mark.parametrize(
    "identity,changed_name", [("1" * 64, False), (EXPECTED_IDENTITY_SHA256, True)]
)
def test_restore_identity_or_unrelated_drift_locks_the_experiment(
    identity: str, changed_name: bool
) -> None:
    experiment, before = ready_for_restore()
    asyncio.run(experiment.submit_restore_once(lambda _: _success()))
    after = copy.deepcopy(before)
    if changed_name:
        after["name"] = "DRIFT"
    with pytest.raises(ExperimentPreflightError):
        experiment.accept_restore_readback(identity, before, after)
    assert experiment.state == "uncertain-high-risk"


def ready_for_restore() -> tuple[Aio16VideoColorExperiment, dict[str, Any]]:
    before = settings()
    after = copy.deepcopy(before)
    after["video-color"]["hdmi"]["brightness"] = 1
    after["video-color"]["sdi"]["brightness"] = 1
    experiment = Aio16VideoColorExperiment(preflight())
    asyncio.run(experiment.submit_forward_once(lambda _: _success()))
    experiment.accept_forward_readback(EXPECTED_IDENTITY_SHA256, before, after)
    return experiment, before


async def _success() -> dict[str, int]:
    return {"result": 0}
