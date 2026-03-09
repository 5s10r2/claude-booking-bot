import httpx

from config import settings
from utils.api import parse_amenities, parse_sharing_types
from utils.properties import find_property


TOOL_SCHEMA = {
    "name": "fetch_room_details",
    "description": "Get REAL-TIME bed availability per room (beds_available count, sharing type, per-room amenities). Uses a different API endpoint from fetch_property_details. Call alongside fetch_property_details for a complete room picture. Falls back to search cache data (sharing types, amenities, rent) if live availability is empty.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "property_name": {"type": "string", "description": "Exact property name"},
        },
        "required": ["property_name"],
    },
}


async def _fetch_rooms_raw(eazypg_id: str) -> list:
    """Fetch raw room list from API. Used by compare_properties.

    Returns a list of room dicts on success, [] on any failure or missing ID.
    Unlike fetch_room_details(), this returns structured data, not a
    formatted string — callers are responsible for rendering.
    """
    if not eazypg_id:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/getAvailableRoomFromEazyPGID",
                params={"eazypg_id": eazypg_id},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("rooms", data.get("data", []))
    except Exception:
        return []


async def fetch_room_details(user_id: str, property_name: str, **kwargs) -> str:
    prop = find_property(user_id, property_name)
    if not prop:
        return f"Property '{property_name}' not found."

    eazypg_id = prop.get("eazypg_id", "")
    if not eazypg_id:
        return "Property EazyPG ID not available."

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/getAvailableRoomFromEazyPGID",
                params={"eazypg_id": eazypg_id},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error fetching room details: {str(e)}"

    rooms = data.get("rooms", data.get("data", []))
    if not rooms:
        sharing_types = prop.get("sharing_types", [])
        amenities_raw = prop.get("amenities", "")
        rent = prop.get("property_rent", "")
        sharing_str = parse_sharing_types(sharing_types)
        amenities_str = parse_amenities(amenities_raw)
        if sharing_str or amenities_str:
            name = prop.get("property_name", property_name)
            result = f"Live bed availability for '{name}' isn't showing right now. From our listings:\n"
            if sharing_str:
                result += f"- Sharing options: {sharing_str}\n"
            if amenities_str:
                result += f"- Amenities: {amenities_str}\n"
            if rent:
                result += f"- Rent starts from: ₹{rent}/mo\n"
            result += "For confirmed availability, schedule a visit or call the property directly."
            return result
        return f"No room data available for '{property_name}'. Schedule a visit to check in person."

    result = f"Available rooms at '{prop.get('property_name', property_name)}':\n"
    for room in rooms:
        # API may use room_name, room_type, name, or room_no — try all
        name = (room.get("room_name") or room.get("room_type") or room.get("name")
                or (f"Room {room.get('room_no', room.get('number', ''))}" if room.get("room_no") or room.get("number") else "Room"))
        sharing = room.get("sharing_type", "")
        available = room.get("beds_available", room.get("available", ""))
        amenities = parse_amenities(room.get("amenities", ""))
        result += f"- {name}: {sharing} sharing, Available beds: {available}"
        if amenities:
            result += f", Amenities: {amenities}"
        result += "\n"

    return result
