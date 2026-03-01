import httpx

from config import settings
from utils.properties import find_property as _find_property


async def cancel_booking(user_id: str, property_name: str, **kwargs) -> str:
    prop = _find_property(user_id, property_name)
    if not prop:
        return f"Property '{property_name}' not found."

    property_id = prop.get("property_id", "")
    if not property_id:
        return "Property ID not available."

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/cancel-booking",
                json={"user_id": user_id, "property_id": property_id},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error cancelling booking: {str(e)}"

    return f"Booking cancelled for '{prop.get('property_name', property_name)}'."
