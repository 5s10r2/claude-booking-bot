from db.redis_store import get_property_info_map
from utils.retry import http_get


async def fetch_nearby_places(
    user_id: str,
    property_name: str,
    radius: int = 5000,
    amenity: str = "",
    **kwargs,
) -> str:
    info_map = get_property_info_map(user_id)
    prop = None
    for p in info_map:
        if property_name.strip().lower() in p.get("property_name", "").strip().lower():
            prop = p
            break

    if not prop:
        return f"Property '{property_name}' not found."

    lat = prop.get("property_lat", "")
    lon = prop.get("property_long", "")
    if not lat or not lon:
        return "Property coordinates not available."

    amenity_filter = f'["amenity"="{amenity}"]' if amenity else '["amenity"]'
    query = f"""
    [out:json];
    (
      node{amenity_filter}(around:{radius},{lat},{lon});
    );
    out body 10;
    """

    try:
        data = await http_get(
            "https://overpass-api.de/api/interpreter",
            params={"data": query},
            timeout=20,
        )
    except Exception as e:
        return f"Error fetching nearby places: {str(e)}"

    elements = data.get("elements", [])
    if not elements:
        return f"No nearby {amenity or 'places'} found within {radius}m of '{property_name}'."

    results = []
    for el in elements[:10]:
        tags = el.get("tags", {})
        name = tags.get("name", "Unnamed")
        place_type = tags.get("amenity", "")
        results.append(f"- {name} ({place_type})")

    return f"Nearby places within {radius}m of '{prop.get('property_name', property_name)}':\n" + "\n".join(results)
