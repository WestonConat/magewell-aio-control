"""Pure helpers for the guarded device naming workflow."""

from copy import deepcopy
from typing import Any


def validate_new_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ValueError("New device name cannot be empty.")
    if len(name) > 128:
        raise ValueError("New device name exceeds the 128-character operator limit.")
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise ValueError("New device name cannot contain control characters.")
    return name


def replace_recording_name_values(
    value: Any, old_name: str, new_name: str, path: str = "rec-channels"
) -> tuple[Any, list[dict[str, str]]]:
    """Replace only literal old-name occurrences inside recording-channel values."""
    changes: list[dict[str, str]] = []
    if isinstance(value, dict):
        updated: dict[str, Any] = {}
        for key, child in value.items():
            updated[key], child_changes = replace_recording_name_values(
                child, old_name, new_name, f"{path}.{key}"
            )
            changes.extend(child_changes)
        return updated, changes
    if isinstance(value, list):
        updated_list = []
        for index, child in enumerate(value):
            updated_child, child_changes = replace_recording_name_values(
                child, old_name, new_name, f"{path}.{index}"
            )
            updated_list.append(updated_child)
            changes.extend(child_changes)
        return updated_list, changes
    if isinstance(value, str) and old_name in value:
        updated_value = value.replace(old_name, new_name)
        return updated_value, [{"path": path, "before": value, "after": updated_value}]
    return value, changes


def build_rename_settings(
    settings: dict[str, Any], current_name: str, new_name: str
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Return a target-local rename payload and the recording values it changes."""
    if settings.get("name") != current_name:
        raise ValueError("target settings identity does not match the scanned device")
    updated = deepcopy(settings)
    updated["name"] = validate_new_name(new_name)
    channels = updated.get("rec-channels")
    if channels is None:
        return updated, []
    updated_channels, changes = replace_recording_name_values(channels, current_name, new_name)
    updated["rec-channels"] = updated_channels
    return updated, changes
