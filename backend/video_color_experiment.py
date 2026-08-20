"""Fixture-gated adapter for one reviewed AIO-16 video-color experiment.

This module deliberately has no FastAPI route, device lookup, login, or HTTP client.
It turns a fresh, caller-supplied read-only snapshot into a single redacted intent,
then evaluates a caller-supplied single response and read-back.  A later, separately
authorized live-run owner must supply the authenticated transport and hold the app's
mutation lock around it; tests exercise the transport seam with fixtures only.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

EXPERIMENT_NAME = "aio16-video-color-brightness-0-to-1"
TARGET_LABEL = "AIO-16"
EXPECTED_IDENTITY_SHA256 = "90dcd504cd5d67dccbcfbc0c1ecbe9b315e8d21d2905b56c71b902cd9bc0095d"
EXPECTED_GET_INFO_SHA256 = "e2484d356b3ba81658a543ef1391f2919fd4010e5d60cc52c06cf810ef69dd93"
EXPECTED_REPORT_SCHEMA_SHA256 = "2eaca2840eff145ab47885840cdfdae85a764f7408bf2a4d6de15b9107db6eea"
EXPECTED_SETTINGS_SHA256 = "7dacb930d51286cfdab35c459cfde48cdbfdb1fab02f558e88cd366d313009ca"
EXPECTED_VIDEO_COLOR_SHA256 = "618f0a5e8995cac64067d2c337e40dcab816e6b50daa36b82efb4661f9628ec4"

EXPECTED_COHORT = {
    "module": "Ultra Encode AIO",
    "hardware": "B",
    "product_id": 787,
    "firmware": "2.4.288",
    "api_version": "2.1",
}
EXPECTED_COLOR_RANGE = {
    "brightness": (-100, 100),
    "contrast": (50, 200),
    "saturation": (0, 200),
    "hue": (-90, 90),
}
BASELINE_COLOR = {"contrast": 100, "brightness": 0, "saturation": 100, "hue": 0}
FORWARD_COLOR = {"contrast": 100, "brightness": 1, "saturation": 100, "hue": 0}

# The vendor's ready example is 0x10010 (disk-ready plus password-set).  This
# fixture is conservative: every other current or future status bit is a stop.
PERMITTED_IDLE_STATUS_MASK = 0x10 | 0x10000

ExperimentState = Literal[
    "ready",
    "forward-submitted",
    "restore-eligible",
    "restore-submitted",
    "restored",
    "uncertain-high-risk",
]
MappingResult = Literal["hdmi-and-sdi", "hdmi-only", "sdi-only"]


class ExperimentPreflightError(ValueError):
    """A safe, non-sensitive reason that no device request may be made."""


def canonical_sha256(value: Any) -> str:
    """Hash ephemeral report data without retaining or displaying it."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _video_color(settings: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    color = settings.get("video-color")
    if not isinstance(color, Mapping):
        raise ExperimentPreflightError("video-color report path is unavailable")
    normalized: dict[str, dict[str, int]] = {}
    for input_name in ("hdmi", "sdi"):
        values = color.get(input_name)
        if not isinstance(values, Mapping):
            raise ExperimentPreflightError("video-color report path is incomplete")
        if set(values) != set(BASELINE_COLOR):
            raise ExperimentPreflightError("video-color report fields are not the approved shape")
        if any(type(values[key]) is not int for key in BASELINE_COLOR):
            raise ExperimentPreflightError("video-color report values must be integers")
        normalized[input_name] = {key: values[key] for key in BASELINE_COLOR}
    return normalized


def _without_video_color(settings: Mapping[str, Any]) -> dict[str, Any]:
    copy_without_color = copy.deepcopy(dict(settings))
    copy_without_color.pop("video-color", None)
    return copy_without_color


@dataclass(frozen=True)
class Aio16VideoColorSnapshot:
    """Ephemeral read-only inputs supplied by a future live-run preflight."""

    identity_sha256: str
    get_info_sha256: str
    report_schema_sha256: str
    settings: dict[str, Any]
    color_range: Mapping[str, tuple[int, int]]
    status_result: int | str
    status_mask: int
    module: str
    hardware: str
    product_id: int
    firmware: str
    api_version: str


@dataclass(frozen=True)
class VideoColorIntent:
    phase: Literal["forward", "restore"]
    params: Mapping[str, int | str]
    target_label: str = TARGET_LABEL

    def __post_init__(self) -> None:
        expected = _params_for_phase(self.phase)
        if self.target_label != TARGET_LABEL or dict(self.params) != expected:
            raise ExperimentPreflightError("video-color intent does not match the reviewed request")
        object.__setattr__(self, "params", MappingProxyType(expected))

    def redacted(self) -> dict[str, Any]:
        """The only displayable form: no address, credential, cookie, or report."""
        return {
            "experiment": EXPERIMENT_NAME,
            "target_label": self.target_label,
            "phase": self.phase,
            "method": "set-video-color",
            "color": {
                key: self.params[key] for key in ("contrast", "brightness", "saturation", "hue")
            },
        }


@dataclass(frozen=True)
class Aio16VideoColorPreflight:
    """Redacted successful preflight. It is valid only for this fixture cohort."""

    identity_sha256: str
    get_info_sha256: str
    report_schema_sha256: str
    settings_sha256: str
    video_color_sha256: str
    forward_intent: VideoColorIntent

    def __post_init__(self) -> None:
        if (
            self.identity_sha256 != EXPECTED_IDENTITY_SHA256
            or self.get_info_sha256 != EXPECTED_GET_INFO_SHA256
            or self.report_schema_sha256 != EXPECTED_REPORT_SCHEMA_SHA256
            or self.settings_sha256 != EXPECTED_SETTINGS_SHA256
            or self.video_color_sha256 != EXPECTED_VIDEO_COLOR_SHA256
            or self.forward_intent.phase != "forward"
        ):
            raise ExperimentPreflightError("preflight does not match the reviewed AIO-16 fixture")

    def redacted(self) -> dict[str, Any]:
        return {
            "experiment": EXPERIMENT_NAME,
            "target_label": TARGET_LABEL,
            "identity_sha256": self.identity_sha256,
            "get_info_sha256": self.get_info_sha256,
            "report_schema_sha256": self.report_schema_sha256,
            "settings_sha256": self.settings_sha256,
            "video_color_sha256": self.video_color_sha256,
            "forward_intent": self.forward_intent.redacted(),
        }


def build_aio16_video_color_preflight(
    snapshot: Aio16VideoColorSnapshot,
) -> Aio16VideoColorPreflight:
    """Validate every fixture fact before exposing a one-shot forward intent.

    This pure function opens no socket and retains no raw report. A caller must reject
    before selecting an authenticated transport when this raises.
    """
    if {
        "module": snapshot.module,
        "hardware": snapshot.hardware,
        "product_id": snapshot.product_id,
        "firmware": snapshot.firmware,
        "api_version": snapshot.api_version,
    } != EXPECTED_COHORT:
        raise ExperimentPreflightError("target cohort does not match the reviewed AIO-16 fixture")
    expected_fingerprints = {
        "identity": EXPECTED_IDENTITY_SHA256,
        "get-info": EXPECTED_GET_INFO_SHA256,
        "report-schema": EXPECTED_REPORT_SCHEMA_SHA256,
    }
    actual_fingerprints = {
        "identity": snapshot.identity_sha256,
        "get-info": snapshot.get_info_sha256,
        "report-schema": snapshot.report_schema_sha256,
    }
    if actual_fingerprints != expected_fingerprints:
        raise ExperimentPreflightError("fresh target binding does not match the reviewed fixture")
    if (
        snapshot.status_result not in (0, "0")
        or type(snapshot.status_mask) is not int
        or snapshot.status_mask & ~PERMITTED_IDLE_STATUS_MASK
    ):
        raise ExperimentPreflightError("device status is not idle and safe for the experiment")
    if dict(snapshot.color_range) != EXPECTED_COLOR_RANGE:
        raise ExperimentPreflightError("video-color range does not match the reviewed fixture")
    colors = _video_color(snapshot.settings)
    if any(values != BASELINE_COLOR for values in colors.values()):
        raise ExperimentPreflightError(
            "video-color baseline no longer matches the reviewed fixture"
        )
    settings_sha256 = canonical_sha256(snapshot.settings)
    video_color_sha256 = canonical_sha256(colors)
    if (
        settings_sha256 != EXPECTED_SETTINGS_SHA256
        or video_color_sha256 != EXPECTED_VIDEO_COLOR_SHA256
    ):
        raise ExperimentPreflightError(
            "fresh report fingerprint does not match the reviewed fixture"
        )
    return Aio16VideoColorPreflight(
        identity_sha256=snapshot.identity_sha256,
        get_info_sha256=snapshot.get_info_sha256,
        report_schema_sha256=snapshot.report_schema_sha256,
        settings_sha256=settings_sha256,
        video_color_sha256=video_color_sha256,
        forward_intent=VideoColorIntent(phase="forward", params=_params_for_phase("forward")),
    )


def evaluate_forward_readback(
    preflight: Aio16VideoColorPreflight,
    observed_identity_sha256: str,
    before_settings: Mapping[str, Any],
    after_settings: Mapping[str, Any],
) -> MappingResult:
    """Accept only an unchanged non-color report plus a clear brightness mapping."""
    if observed_identity_sha256 != preflight.identity_sha256:
        raise ExperimentPreflightError("post-effect identity does not match the frozen preflight")
    if canonical_sha256(before_settings) != preflight.settings_sha256:
        raise ExperimentPreflightError("pre-effect report no longer matches the frozen preflight")
    before_colors = _video_color(before_settings)
    after_colors = _video_color(after_settings)
    if any(values != BASELINE_COLOR for values in before_colors.values()):
        raise ExperimentPreflightError("pre-effect video-color baseline changed before submission")
    if _without_video_color(before_settings) != _without_video_color(after_settings):
        raise ExperimentPreflightError("unrelated settings drift detected after submission")
    changed = {name for name, values in after_colors.items() if values == FORWARD_COLOR}
    unchanged = {name for name, values in after_colors.items() if values == BASELINE_COLOR}
    if changed == {"hdmi", "sdi"}:
        return "hdmi-and-sdi"
    if changed == {"hdmi"} and unchanged == {"sdi"}:
        return "hdmi-only"
    if changed == {"sdi"} and unchanged == {"hdmi"}:
        return "sdi-only"
    raise ExperimentPreflightError("video-color read-back mapping is ambiguous")


async def invoke_video_color_once(
    intent: VideoColorIntent,
    send: Callable[[Mapping[str, int | str]], Awaitable[Mapping[str, Any]]],
) -> None:
    """Invoke one injected transport request; this adapter intentionally never retries."""
    params = _params_for_phase(intent.phase)
    if dict(intent.params) != params:
        raise ExperimentPreflightError("video-color intent does not match the reviewed request")
    response = await send(params)
    if not isinstance(response, Mapping) or response.get("result") not in (0, "0"):
        raise ExperimentPreflightError("video-color setter did not return a definitive success")


class Aio16VideoColorExperiment:
    """Small in-memory state machine used by a future separately authorized runner."""

    def __init__(self, preflight: Aio16VideoColorPreflight) -> None:
        # Reconstructing validates the preflight even if a caller bypassed its public builder.
        self.preflight = Aio16VideoColorPreflight(**preflight.__dict__)
        self.state: ExperimentState = "ready"
        self.mapping: MappingResult | None = None

    async def submit_forward_once(
        self, send: Callable[[Mapping[str, int | str]], Awaitable[Mapping[str, Any]]]
    ) -> None:
        if self.state != "ready":
            raise ExperimentPreflightError("forward intent is not eligible")
        self.state = "forward-submitted"
        try:
            await invoke_video_color_once(self.preflight.forward_intent, send)
        except Exception:
            self.state = "uncertain-high-risk"
            raise

    def accept_forward_readback(
        self,
        observed_identity_sha256: str,
        before_settings: Mapping[str, Any],
        after_settings: Mapping[str, Any],
    ) -> MappingResult:
        if self.state != "forward-submitted":
            raise ExperimentPreflightError("forward read-back is not eligible")
        try:
            self.mapping = evaluate_forward_readback(
                self.preflight, observed_identity_sha256, before_settings, after_settings
            )
        except Exception:
            self.state = "uncertain-high-risk"
            raise
        self.state = "restore-eligible"
        return self.mapping

    def restore_intent(self) -> VideoColorIntent:
        if self.state != "restore-eligible":
            raise ExperimentPreflightError(
                "restore is eligible only after definitive forward read-back"
            )
        return VideoColorIntent(phase="restore", params=_params_for_phase("restore"))

    async def submit_restore_once(
        self, send: Callable[[Mapping[str, int | str]], Awaitable[Mapping[str, Any]]]
    ) -> None:
        intent = self.restore_intent()
        self.state = "restore-submitted"
        try:
            await invoke_video_color_once(intent, send)
        except Exception:
            self.state = "uncertain-high-risk"
            raise

    def accept_restore_readback(
        self,
        observed_identity_sha256: str,
        before_settings: Mapping[str, Any],
        after_settings: Mapping[str, Any],
    ) -> None:
        if self.state != "restore-submitted":
            raise ExperimentPreflightError("restore read-back is not eligible")
        try:
            if observed_identity_sha256 != self.preflight.identity_sha256:
                raise ExperimentPreflightError(
                    "post-restore identity does not match the frozen preflight"
                )
            colors = _video_color(after_settings)
            if any(values != BASELINE_COLOR for values in colors.values()):
                raise ExperimentPreflightError("restore read-back did not return to baseline")
            if _without_video_color(before_settings) != _without_video_color(after_settings):
                raise ExperimentPreflightError("unrelated settings drift detected after restore")
        except Exception:
            self.state = "uncertain-high-risk"
            raise
        self.state = "restored"


def _params_for_phase(phase: Literal["forward", "restore"]) -> dict[str, int | str]:
    if phase == "forward":
        color = FORWARD_COLOR
    elif phase == "restore":
        color = BASELINE_COLOR
    else:
        raise ExperimentPreflightError("video-color intent phase is invalid")
    return {"method": "set-video-color", **color}
