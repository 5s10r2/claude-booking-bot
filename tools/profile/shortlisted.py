from db.redis_store import get_shortlisted_properties as get_shortlisted, get_property_info_map


async def get_shortlisted_properties(user_id: str, **kwargs) -> str:
    shortlisted_ids = get_shortlisted(user_id)
    if not shortlisted_ids:
        return "No shortlisted properties yet. Search for properties and shortlist the ones you like!"

    info_map = get_property_info_map(user_id)
    names = []
    for prop_id in shortlisted_ids:
        for info in info_map:
            if info.get("property_id") == prop_id:
                names.append(info.get("property_name", "Unknown"))
                break
        else:
            names.append(f"Property ID: {prop_id}")

    lines = ["Your shortlisted properties:"]
    for i, name in enumerate(names, 1):
        lines.append(f"{i}. {name}")

    lines.append("\nWould you like to see details or schedule a visit for any of these?")
    return "\n".join(lines)
