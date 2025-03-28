from .magewell_settings import get_modified_settings

def get_bulk_update_settings(target_magewell_id: str, control_settings: dict) -> dict:
    """
    Generate the bulk update settings for a target device with magewell_id.
    Use the default settings (which embed target magewell_id in rec-channels)
    and merge in the control device's settings for keys other than rec-channels.
    """
    baseline = get_modified_settings(target_magewell_id)
    merged = baseline.copy()
    for key, control_value in control_settings.items():
        # Skip keys that you don't want to override.
        if key == "rec-channels":
            continue
        merged[key] = control_value
    return merged

