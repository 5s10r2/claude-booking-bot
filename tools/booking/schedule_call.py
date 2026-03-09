import httpx

from config import settings
from utils.date import transcribe_date
from utils.properties import find_property as _find_property


TOOL_SCHEMA = {
    "name": "save_call_time",
    "description": "Schedule a phone call or video tour with a property. Available 10 AM - 9 PM, next 7 days.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "property_name": {"type": "string", "description": "Exact property name"},
            "visit_date": {"type": "string", "description": "Date as stated by user"},
            "visit_time": {"type": "string", "description": "Time as stated by user"},
            "visit_type": {"type": "string", "description": "'Phone Call' or 'Video Tour'"},
        },
        "required": ["property_name", "visit_date", "visit_time"],
    },
}


async def save_call_time(
    user_id: str,
    property_name: str,
    visit_date: str,
    visit_time: str,
    visit_type: str = "Phone Call",
    **kwargs,
) -> str:
    prop = _find_property(user_id, property_name)
    if not prop:
        return f"Property '{property_name}' not found. Please provide the correct property name."

    property_id = prop.get("property_id", "")
    if not property_id:
        return "Property ID not available."

    visit_date = transcribe_date(visit_date)
    if not visit_date:
        return "I couldn't understand that date. Please say something like 'tomorrow', '15 March', or '25/03/2026'."

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/add-booking",
                json={
                    "user_id": user_id,
                    "property_id": property_id,
                    "visit_date": visit_date,
                    "visit_time": visit_time,
                    "visit_type": visit_type,
                    "property_name": prop.get("property_name", property_name),
                },
            )
            if resp.status_code == 400:
                return "There is already a scheduled booking for this property or on the same date. Would you like to see your scheduled events?"
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error scheduling {visit_type.lower()}: {str(e)}"

    if not data.get("success") and resp.status_code != 200:
        msg = data.get("message", "unknown error")
        return f"Booking failed: {msg}. Please try again."

    # Create external lead if needed
    eazypg_id = prop.get("eazypg_id", "")
    pg_id = prop.get("pg_id", "")
    pg_number = prop.get("pg_number", "")
    if eazypg_id:
        from tools.booking.schedule_visit import _create_external_lead

        await _create_external_lead(
            user_id, eazypg_id, pg_id, pg_number,
            visit_date, visit_time, visit_type,
        )

    return (
        f"{visit_type} scheduled successfully for '{prop.get('property_name', property_name)}' "
        f"on {visit_date} at {visit_time}."
    )
