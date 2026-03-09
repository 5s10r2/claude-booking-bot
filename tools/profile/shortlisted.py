from db.redis_store import get_shortlisted_properties as get_shortlisted, get_property_info_map


TOOL_SCHEMA = {
    "name": "get_shortlisted_properties",
    "description": "Get the list of properties the user has shortlisted.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "required": [],
    },
}


async def get_shortlisted_properties(user_id: str, **kwargs) -> str:
    shortlisted_ids = get_shortlisted(user_id)
    if not shortlisted_ids:
        return "No shortlisted properties yet. Search for properties and shortlist the ones you like!"

    info_map = get_property_info_map(user_id)
    # Build a lookup dict covering all possible ID keys — O(n) instead of O(n²)
    id_to_name: dict[str, str] = {}
    for info in info_map:
        name = info.get("property_name", "Unknown")
        for key in ("property_id", "prop_id", "pg_id"):
            pid = info.get(key, "")
            if pid:
                id_to_name[pid] = name
    names = [id_to_name.get(pid, f"Property ID: {pid}") for pid in shortlisted_ids]

    lines = ["Your shortlisted properties:"]
    for i, name in enumerate(names, 1):
        lines.append(f"{i}. {name}")

    lines.append("\nWould you like to see details or schedule a visit for any of these?")
    return "\n".join(lines)
