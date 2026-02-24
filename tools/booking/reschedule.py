import httpx

from config import settings
from db.redis_store import get_property_info_map
from utils.date import transcribe_date


def _find_property(user_id: str, property_name: str):
    info_map = get_property_info_map(user_id)
    for p in info_map:
        if property_name.strip().lower() in p.get("property_name", "").strip().lower():
            return p
    return None


async def reschedule_booking(
    user_id: str,
    property_name: str,
    visit_date: str = None,
    visit_time: str = None,
    visit_type: str = None,
    **kwargs,
) -> str:
    prop = _find_property(user_id, property_name)
    if not prop:
        return f"Property '{property_name}' not found."

    property_id = prop.get("property_id", "")
    if not property_id:
        return "Property ID not available."

    update_data = {"user_id": user_id, "property_id": property_id}

    if visit_date:
        update_data["visit_date"] = transcribe_date(visit_date)
    if visit_time:
        update_data["visit_time"] = visit_time
    if visit_type:
        update_data["visit_type"] = visit_type

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/update-booking",
                json=update_data,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error rescheduling booking: {str(e)}"

    parts = []
    if visit_date:
        parts.append(f"date: {update_data['visit_date']}")
    if visit_time:
        parts.append(f"time: {visit_time}")
    if visit_type:
        parts.append(f"type: {visit_type}")

    changes = ", ".join(parts) if parts else "details updated"
    return f"Booking rescheduled for '{prop.get('property_name', property_name)}' — {changes}."
