from db.redis_store import get_property_info_map


def find_property(user_id: str, property_name: str) -> dict | None:
    """Find a property by name match in the user's cached info map.

    Tries exact match first, then substring match.
    """
    info_map = get_property_info_map(user_id)
    name_lower = property_name.strip().lower()
    # Exact match first
    for p in info_map:
        if p.get("property_name", "").strip().lower() == name_lower:
            return p
    # Substring match fallback — input may be verbose (e.g. "Name | Operator")
    # so check both directions: stored-in-input and input-in-stored
    for p in info_map:
        stored = p.get("property_name", "").strip().lower()
        if stored in name_lower or name_lower in stored:
            return p
    return None
