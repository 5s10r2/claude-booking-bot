from db.redis_store import save_preferences as redis_save_preferences, get_preferences


def save_preferences(
    user_id: str,
    location: str = "",
    city: str = "",
    min_budget: float = None,
    max_budget: float = None,
    move_in_date: str = "",
    property_type: str = None,
    unit_types_available: str = None,
    pg_available_for: str = None,
    sharing_types_enabled: str = None,
    amenities: str = "",
    description: str = "",
    commute_from: str = "",
    **kwargs,
) -> str:
    existing = get_preferences(user_id)

    if location:
        existing["location"] = location
    if city:
        existing["city"] = city
    if min_budget is not None:
        existing["min_budget"] = min_budget
    if max_budget is not None:
        existing["max_budget"] = max_budget
    if move_in_date:
        existing["move_in_date"] = move_in_date
    if property_type is not None:
        existing["property_type"] = property_type
    if unit_types_available is not None:
        existing["unit_types_available"] = unit_types_available
    if pg_available_for is not None:
        existing["pg_available_for"] = pg_available_for
    if sharing_types_enabled is not None:
        existing["sharing_types_enabled"] = sharing_types_enabled
    if amenities:
        existing["amenities"] = amenities
    if description:
        existing["description"] = description
    if commute_from:
        existing["commute_from"] = commute_from

    redis_save_preferences(user_id, existing)
    return f"Preferences saved: {existing}"
