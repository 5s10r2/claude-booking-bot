import httpx

from config import settings
from db.redis_store import get_property_info_map


async def fetch_landmarks(user_id: str, landmark_name: str, property_name: str, **kwargs) -> str:
    info_map = get_property_info_map(user_id)
    prop = None
    for p in info_map:
        if property_name.strip().lower() in p.get("property_name", "").strip().lower():
            prop = p
            break

    if not prop:
        return f"Property '{property_name}' not found."

    prop_lat = prop.get("property_lat", "")
    prop_long = prop.get("property_long", "")
    if not prop_lat or not prop_long:
        return "Property coordinates not available."

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            geo_resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/property/getLatLongProperty",
                json={"address": landmark_name},
            )
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()
    except Exception as e:
        return f"Error finding landmark: {str(e)}"

    landmark_lat = geo_data.get("lat", geo_data.get("latitude", ""))
    landmark_long = geo_data.get("long", geo_data.get("longitude", ""))
    if not landmark_lat or not landmark_long:
        return f"Could not find coordinates for '{landmark_name}'."

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            dist_resp = await client.get(
                f"http://maps.rentok.com/table/v1/driving/{prop_long},{prop_lat};{landmark_long},{landmark_lat}",
                params={"sources": "0", "api_key": "f34519d734a599611aece8b96810d122"},
            )
            dist_resp.raise_for_status()
            dist_data = dist_resp.json()
    except Exception as e:
        return f"Error calculating distance: {str(e)}"

    durations = dist_data.get("durations", [[]])
    distances = dist_data.get("distances", [[]])

    if durations and durations[0] and len(durations[0]) > 1:
        time_min = round(durations[0][1] / 60, 1)
        dist_km = round(distances[0][1] / 1000, 1) if distances and distances[0] and len(distances[0]) > 1 else "N/A"
        return f"Distance from '{prop.get('property_name', property_name)}' to '{landmark_name}': {dist_km} km ({time_min} min by car)"

    return "Could not calculate distance."
