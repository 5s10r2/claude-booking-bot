from db.redis_store import get_preferences


async def fetch_profile_details(user_id: str, **kwargs) -> str:
    prefs = get_preferences(user_id)

    if not prefs:
        return (
            f"Phone: {user_id}\n"
            "No saved preferences yet. Start a property search to set up your preferences!"
        )

    lines = [f"Phone: {user_id}", "Saved preferences:"]

    field_labels = {
        "location": "Location",
        "city": "City",
        "min_budget": "Min Budget",
        "max_budget": "Max Budget",
        "move_in_date": "Move-in Date",
        "property_type": "Property Type",
        "unit_types_available": "Unit Types",
        "pg_available_for": "Available For",
        "sharing_types_enabled": "Sharing Type",
        "amenities": "Amenities",
        "description": "Description",
    }

    for key, label in field_labels.items():
        value = prefs.get(key)
        if value:
            lines.append(f"- {label}: {value}")

    return "\n".join(lines)
