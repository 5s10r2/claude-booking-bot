import httpx

from config import settings
from utils.properties import find_property as _find_property


TOOL_SCHEMA = {
    "name": "cancel_booking",
    "description": "Cancel an existing visit, call, or booking for a property.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "property_name": {"type": "string", "description": "Exact property name"},
        },
        "required": ["property_name"],
    },
}


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

    # cancel-booking always returns HTTP 200 with no `success` field in the body.
    # raise_for_status() above already handles any genuine HTTP errors (4xx/5xx).
    # We check the message as a final safety net.
    msg = data.get("message", "")
    if resp.status_code != 200:
        return f"Cancellation failed: {msg or 'unknown error'}. Please try again or contact support."
    return f"Booking cancelled successfully for '{prop.get('property_name', property_name)}'."
