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
        "use-nosignal-file",
        "nas",
        "send-file-cloud",
        "enable-zen-master",
        "zen-master",
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
    missing_profile_keys = (set(control_settings) - TARGET_LOCAL_KEYS) - set(target_settings)
    if missing_profile_keys:
        missing = ", ".join(sorted(missing_profile_keys))
        raise ValueError(f"target schema is missing source profile settings: {missing}")

    # Start from the target so firmware-specific extensions remain untouched,
    # then overlay only the source's portable Camera-profile settings.
    merged = deepcopy(target_settings)
    for key, value in control_settings.items():
        if key not in TARGET_LOCAL_KEYS:
            merged[key] = deepcopy(value)
    return merged
