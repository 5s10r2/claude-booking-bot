import httpx

from config import settings
from db.redis_store import get_property_info_map


async def fetch_room_details(user_id: str, property_name: str, **kwargs) -> str:
    info_map = get_property_info_map(user_id)
    prop = None
    for p in info_map:
        if property_name.strip().lower() in p.get("property_name", "").strip().lower():
            prop = p
            break

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
        return f"No available rooms found for '{property_name}'."

    result = f"Available rooms at '{prop.get('property_name', property_name)}':\n"
    for room in rooms:
        name = room.get("room_name", room.get("name", "Room"))
        sharing = room.get("sharing_type", "")
        available = room.get("beds_available", room.get("available", ""))
        amenities = room.get("amenities", "")
        result += f"- {name}: {sharing} sharing, Available beds: {available}"
        if amenities:
            result += f", Amenities: {amenities}"
        result += "\n"

    return result
