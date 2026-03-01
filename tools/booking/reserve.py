import httpx

from config import settings
from utils.properties import find_property as _find_property


async def check_reserve_bed(user_id: str, property_name: str, **kwargs) -> str:
    prop = _find_property(user_id, property_name)
    if not prop:
        return f"Property '{property_name}' not found."

    property_id = prop.get("property_id", "")
    if not property_id:
        return "Property ID not available."

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/reserveProperty",
                json={"user_id": user_id, "property_id": property_id, "check_only": True},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error checking reservation status: {str(e)}"

    if data.get("success") or data.get("reserved"):
        return f"A bed is already reserved for you at '{prop.get('property_name', property_name)}'."
    return f"No bed reserved yet at '{prop.get('property_name', property_name)}'. You can proceed with reservation."


async def reserve_bed(user_id: str, property_name: str, **kwargs) -> str:
    prop = _find_property(user_id, property_name)
    if not prop:
        return f"Property '{property_name}' not found."

    property_id = prop.get("property_id", "")
    if not property_id:
        return "Property ID not available."

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/reserveProperty",
                json={"user_id": user_id, "property_id": property_id},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error reserving bed: {str(e)}"

    if data.get("success") or resp.status_code == 200:
        return f"Bed reserved successfully at '{prop.get('property_name', property_name)}'!"
    return f"Failed to reserve bed: {data.get('message', 'Unknown error')}"
