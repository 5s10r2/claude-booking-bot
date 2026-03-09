import logging

from db.redis_store import save_preferences as redis_save_preferences, get_preferences, add_deal_breaker

logger = logging.getLogger("tools.broker.preferences")

TOOL_SCHEMA = {
    "name": "save_preferences",
    "description": "Save or update user's property search preferences. Call this before searching to store location, budget, property type, and other filters.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "location": {"type": "string", "description": "Area/locality AND city, e.g. 'Koramangala, Bangalore'"},
            "city": {"type": "string", "description": "City name, e.g. 'Bangalore'"},
            "min_budget": {"type": "number", "description": "Minimum monthly rent budget"},
            "max_budget": {"type": "number", "description": "Maximum monthly rent budget"},
            "move_in_date": {"type": "string", "description": "Preferred move-in date, pass as user stated it"},
            "property_type": {"type": "string", "description": "One of: PG Rooms, Co-Living, Hostel, or null for flats"},
            "unit_types_available": {"type": "string", "description": "Comma-separated: ROOM, 1RK, 1BHK, 2BHK, 3BHK, 4BHK, 5BHK"},
            "pg_available_for": {"type": "string", "description": "All Girls, All Boys, or Any"},
            "sharing_types_enabled": {"type": "string", "description": "Room sharing count: 1 for single, 2 for double, etc."},
            "amenities": {"type": "string", "description": "Comma-separated amenities: gym, wifi, parking, kitchen, etc. For backward compatibility, always pass the full combined list here."},
            "must_have_amenities": {"type": "string", "description": "Comma-separated amenities the user MUST have (said 'need', 'require', 'must have'). E.g. 'AC, WiFi'"},
            "nice_to_have_amenities": {"type": "string", "description": "Comma-separated amenities the user would PREFER but aren't essential (said 'prefer', 'nice to have', 'if possible'). E.g. 'gym, parking'"},
            "deal_breakers": {"type": "string", "description": "Comma-separated deal-breakers inferred from user rejecting 2+ properties for the same reason. E.g. 'no AC, far from metro'. Only set when a clear pattern emerges from rejections."},
            "description": {"type": "string", "description": "User's free-text description of what they want"},
            "commute_from": {"type": "string", "description": "User's commute reference point — office, college, or any landmark they want properties near. E.g. 'Reliance Corporate Park, Navi Mumbai'"},
        },
        "required": ["location"],
    },
}


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
    must_have_amenities: str = "",
    nice_to_have_amenities: str = "",
    deal_breakers: str = "",
    description: str = "",
    commute_from: str = "",
    **kwargs,
) -> str:
    try:
        existing = get_preferences(user_id)
    except Exception as e:
        logger.warning("Redis error loading preferences for user=%s: %s", user_id, e)
        existing = {}

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
    if must_have_amenities:
        existing["must_have_amenities"] = must_have_amenities
    if nice_to_have_amenities:
        existing["nice_to_have_amenities"] = nice_to_have_amenities
    if description:
        existing["description"] = description
    if commute_from:
        existing["commute_from"] = commute_from

    # Deal-breakers go to cross-session user memory, not search preferences
    if deal_breakers:
        for db in deal_breakers.split(","):
            db = db.strip()
            if db:
                add_deal_breaker(user_id, db)

    try:
        redis_save_preferences(user_id, existing)
    except Exception as e:
        logger.warning("Redis error saving preferences for user=%s: %s", user_id, e)
        return "Preferences noted but could not be saved due to a temporary error. Please try again."
    return f"Preferences saved: {existing}"
