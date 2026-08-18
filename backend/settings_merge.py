from copy import deepcopy

# These settings identify a device, keep it reachable, or refer to files and
# destinations that exist only on that target. They are never cloned from the
# control source. The remaining settings form the live Camera profile.
TARGET_LOCAL_KEYS = frozenset(
    {
        "name",
        "eth",
        "enable-station",
        "wifi",
        "softap",
        "rndis",
        "web",
        "rec-channels",
        "image",
        "nosignal-files",
        "nas",
        "send-file-cloud",
    }
)


def get_bulk_update_settings(
    target_magewell_id: str,
    control_settings: dict,
    target_settings: dict,
) -> dict:
    """Build a live-source profile while preserving target-local settings."""
    if target_settings.get("name") != target_magewell_id:
        raise ValueError("target settings identity does not match the scanned device")
    if set(control_settings) != set(target_settings):
        raise ValueError("source and target settings schemas differ")

    merged = deepcopy(control_settings)
    for key in TARGET_LOCAL_KEYS:
        if key in target_settings:
            merged[key] = deepcopy(target_settings[key])
    return merged
