from utils.properties import find_property
from utils.retry import http_get


TOOL_SCHEMA = {
    "name": "fetch_nearby_places",
    "description": "Find nearby points of interest (restaurants, metro stations, hospitals, etc.) around a property.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "property_name": {"type": "string", "description": "Exact property name"},
            "radius": {"type": "integer", "description": "Search radius in meters (default 5000)"},
            "amenity": {"type": "string", "description": "Type of place to search for, e.g. restaurant, hospital, school"},
        },
        "required": ["property_name"],
    },
}


async def fetch_nearby_places(
    user_id: str,
    property_name: str,
    radius: int = 5000,
    amenity: str = "",
    **kwargs,
) -> str:
    prop = find_property(user_id, property_name)
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
