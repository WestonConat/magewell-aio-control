from copy import deepcopy


def get_bulk_update_settings(target_magewell_id: str, control_settings: dict) -> dict:
    """Freeze an independent, exact copy of settings read from the live control device."""
    del target_magewell_id
    return deepcopy(control_settings)
