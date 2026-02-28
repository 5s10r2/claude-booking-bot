import httpx

from config import settings
from core.log import get_logger
from db.redis_store import get_property_info_map, get_account_values, track_funnel, get_user_phone, get_aadhar_user_name, record_visit_scheduled, schedule_followup
from utils.date import transcribe_date
from utils.retry import http_post

logger = get_logger("tools.schedule_visit")


def _find_property(user_id: str, property_name: str):
    info_map = get_property_info_map(user_id)
    for p in info_map:
        if property_name.strip().lower() in p.get("property_name", "").strip().lower():
            return p
    return None


async def save_visit_time(
    user_id: str,
    property_name: str,
    visit_date: str,
    visit_time: str,
    visit_type: str = "Physical visit",
    **kwargs,
) -> str:
    prop = _find_property(user_id, property_name)
    if not prop:
        return f"Property '{property_name}' not found. Please provide the correct property name."

    property_id = prop.get("property_id", "")
    if not property_id:
        return "Property ID not available."

    # Normalise date (Claude should pass DD/MM/YYYY but handle natural language too)
    visit_date = transcribe_date(visit_date)

    try:
        resp = await http_post(
            f"{settings.RENTOK_API_BASE_URL}/bookingBot/add-booking",
            json={
                "user_id": user_id,
                "property_id": property_id,
                "visit_date": visit_date,
                "visit_time": visit_time,
                "visit_type": visit_type,
                "property_name": prop.get("property_name", property_name),
            },
            raw=True,
        )
        if resp.status_code == 400:
            return "There is already a scheduled visit for this property or a visit on the same date. Would you like to see your scheduled visits?"
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            return "There is already a scheduled visit for this property or a visit on the same date. Would you like to see your scheduled visits?"
        return f"Error scheduling visit: {str(e)}"
    except Exception as e:
        return f"Error scheduling visit: {str(e)}"

    # Create external lead if needed
    eazypg_id = prop.get("eazypg_id", "")
    pg_id = prop.get("pg_id", "")
    pg_number = prop.get("pg_number", "")
    if eazypg_id:
        await _create_external_lead(
            user_id, eazypg_id, pg_id, pg_number,
            visit_date, visit_time, visit_type,
        )

    prop_lat = prop.get("property_lat", "")
    prop_long = prop.get("property_long", "")
    maps_link = f"https://www.google.com/maps?q={prop_lat},{prop_long}" if prop_lat and prop_long else ""
    location_info = f"\nLocation: {maps_link}" if maps_link else ""

    track_funnel(user_id, "visit")
    record_visit_scheduled(user_id, property_id)

    # Schedule follow-up: 2 hours after the visit time
    try:
        from datetime import datetime as _dt
        visit_dt = _dt.strptime(f"{visit_date} {visit_time}", "%d/%m/%Y %I:%M %p")
        seconds_until_visit = max(0, (visit_dt - _dt.now()).total_seconds())
        followup_delay = int(seconds_until_visit) + 7200  # visit time + 2h
        schedule_followup(user_id, "visit_complete", {
            "property_name": prop.get("property_name", property_name),
            "property_id": property_id,
            "visit_date": visit_date,
            "visit_time": visit_time,
        }, followup_delay)
    except Exception as e:
        logger.warning("follow-up scheduling failed: %s", e)

    return (
        f"Visit scheduled successfully for '{prop.get('property_name', property_name)}' "
        f"on {visit_date} at {visit_time} ({visit_type}).{location_info}"
    )


async def _create_external_lead(
    user_id: str,
    eazypg_id: str,
    pg_id: str,
    pg_number: str,
    visit_date: str,
    visit_time: str,
    visit_type: str,
) -> None:
    """Create an external lead entry for tracking."""
    from db.redis_store import get_preferences, get_aadhar_gender

    gender = get_aadhar_gender(user_id) or "Any"
    prefs = get_preferences(user_id)
    budget = prefs.get("min_budget") or prefs.get("max_budget", "")

    from datetime import datetime

    phone = get_user_phone(user_id) or ""
    name = get_aadhar_user_name(user_id) or phone or "Guest"

    payload = {
        "eazypg_id": eazypg_id,
        "phone": phone,
        "name": name,
        "gender": gender,
        "rent_range": budget,
        "lead_source": "Booking Bot",
        "visit_date": visit_date,
        "visit_time": visit_time,
        "visit_type": visit_type,
        "lead_status": "Visit Scheduled",
        "firebase_id": f"cust_{datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}",
    }
    try:
        await http_post(
            f"{settings.RENTOK_API_BASE_URL}/tenant/addLeadFromEazyPGID",
            json=payload,
        )
    except Exception as e:
        logger.warning("lead creation failed for user=%s eazypg_id=%s: %s", user_id, eazypg_id, e)
