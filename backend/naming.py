"""Pure helpers for the guarded device naming workflow."""

import re
from copy import deepcopy
from typing import Any

DEVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 ._\-+'\[\]\(\),]+$")


def validate_new_name(value: str) -> str:
    """Validate the exact Magewell ``set-name`` API contract before any write."""
    if not 1 <= len(value) <= 32:
        raise ValueError("New device name must contain 1 to 32 characters.")
    if value != value.strip():
        raise ValueError("New device name cannot start or end with a space.")
    if not DEVICE_NAME_PATTERN.fullmatch(value):
        raise ValueError("New device name may use only letters, numbers, spaces, and ._-+'[](),.")
    return value


RECORDING_NAME_SUFFIXES = {
    "dir-name": "_REC",
    "prefix-name": "_",
}


def reset_recording_name_values(
    value: Any, new_name: str, path: str = "rec-channels"
) -> tuple[Any, list[dict[str, str]]]:
    """Reset every supported recording naming field from the new device name."""
    changes: list[dict[str, str]] = []
    if isinstance(value, dict):
        updated: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in RECORDING_NAME_SUFFIXES and isinstance(child, str):
                updated_value = f"{new_name}{RECORDING_NAME_SUFFIXES[key]}"
                updated[key] = updated_value
                if child != updated_value:
                    changes.append({"path": child_path, "before": child, "after": updated_value})
                continue
            updated[key], child_changes = reset_recording_name_values(child, new_name, child_path)
            changes.extend(child_changes)
        return updated, changes
    if isinstance(value, list):
        updated_list = []
        for index, child in enumerate(value):
            updated_child, child_changes = reset_recording_name_values(
                child, new_name, f"{path}.{index}"
            )
            updated_list.append(updated_child)
            changes.extend(child_changes)
        return updated_list, changes
    return value, changes


def build_rename_settings(
    settings: dict[str, Any], current_name: str, new_name: str
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Return the final settings payload used only for recorder-name changes.

    ``import-settings`` is not the device display-name mutation.  The caller must
    use ``set-name`` first and read it back before submitting this full settings
    snapshot to reset supported recording names.
    """
    if settings.get("name") != current_name:
        raise ValueError("target settings identity does not match the scanned device")
    updated = deepcopy(settings)
    updated["name"] = validate_new_name(new_name)
    channels = updated.get("rec-channels")
    if channels is None:
        return updated, []
    updated_channels, changes = reset_recording_name_values(channels, new_name)
    updated["rec-channels"] = updated_channels
    return updated, changes
