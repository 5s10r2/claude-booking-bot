import httpx

from config import settings
from db.redis_store import (
    get_preferences,
    get_property_info_map,
    set_property_info_map,
    save_property_template,
    get_whitelabel_pg_ids,
)


async def search_properties(user_id: str, radius_flag: bool = False, **kwargs) -> str:
    prefs = get_preferences(user_id)
    if not prefs.get("location"):
        return "No location set. Please save preferences with a location first."

    location = prefs.get("location", "")
    min_budget = prefs.get("min_budget", 0)
    max_budget = prefs.get("max_budget", 100000)
    amenities = prefs.get("amenities", "")
    property_type = prefs.get("property_type")
    unit_types = prefs.get("unit_types_available")
    pg_available_for = prefs.get("pg_available_for")
    sharing_types = prefs.get("sharing_types_enabled")
    radius = prefs.get("radius", 20000)

    if radius_flag:
        radius = min(radius + 5000, 35000)
        prefs["radius"] = radius
        from db.redis_store import save_preferences
        save_preferences(user_id, prefs)

    pg_ids = get_whitelabel_pg_ids(user_id)

    payload = {
        "location": location,
        "min_budget": min_budget,
        "max_budget": max_budget,
        "radius": radius,
        "amenities": amenities,
        "pg_ids": pg_ids,
    }
    if property_type:
        payload["property_type"] = property_type
    if unit_types:
        payload["unit_types_available"] = unit_types
    if pg_available_for:
        payload["pg_available_for"] = pg_available_for
    if sharing_types:
        payload["sharing_types_enabled"] = sharing_types

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/save-property-recommendations",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error searching properties: {str(e)}"

    properties = data.get("properties", data.get("data", []))
    if not properties:
        return "No properties found matching your criteria. Would you like to expand the search radius or update your preferences?"

    existing_map = get_property_info_map(user_id)
    property_template = []

    results = []
    for p in properties[:20]:
        info = {
            "property_name": p.get("property_name", p.get("name", "")),
            "property_location": p.get("location", p.get("address", "")),
            "property_rent": str(p.get("rent", p.get("rent_starts_from", ""))),
            "pg_available_for": p.get("pg_available_for", "Any"),
            "property_type": p.get("property_type", ""),
            "property_image": p.get("image", p.get("property_image", "")),
            "prop_id": p.get("prop_id", p.get("property_id", "")),
            "pg_id": p.get("pg_id", ""),
            "pg_number": p.get("pg_number", ""),
            "eazypg_id": p.get("eazypg_id", ""),
            "property_link": p.get("property_link", p.get("microsite_url", "")),
            "google_map": p.get("google_map", ""),
            "match_score": p.get("match_score", p.get("score", "")),
            "distance": p.get("distance", ""),
            "property_lat": p.get("latitude", p.get("lat", "")),
            "property_long": p.get("longitude", p.get("long", "")),
            "phone_number": p.get("phone_number", ""),
            "min_token_amount": p.get("min_token_amount", 1000),
        }
        existing_map.append(info)
        property_template.append(info)

        results.append(
            f"- {info['property_name']} | {info['property_location']} | "
            f"Rent: {info['property_rent']} | For: {info['pg_available_for']} | "
            f"Match: {info['match_score']} | Distance: {info['distance']} | "
            f"Link: {info['property_link']}"
        )

    set_property_info_map(user_id, existing_map)
    save_property_template(user_id, property_template[:5])

    return f"Found {len(properties)} properties. Here are the results:\n" + "\n".join(results)
