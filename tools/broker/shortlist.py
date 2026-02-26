import httpx

from config import settings
from db.redis_store import get_property_info_map, get_whitelabel_pg_ids, track_funnel


async def shortlist_property(user_id: str, property_name: str, **kwargs) -> str:
    info_map = get_property_info_map(user_id)
    prop = None
    for p in info_map:
        if p.get("property_name", "").strip().lower() == property_name.strip().lower():
            prop = p
            break
    if not prop:
        for p in info_map:
            if property_name.strip().lower() in p.get("property_name", "").strip().lower():
                prop = p
                break

    if not prop:
        return f"Property '{property_name}' not found in search results."

    prop_id = prop.get("prop_id") or prop.get("pg_id")
    phone = prop.get("phone_number", user_id[:12])

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/shortlist-booking-bot-property",
                json={
                    "user_id": user_id[:12],
                    "property_id": prop_id,
                    "property_contact": phone,
                },
            )
            resp.raise_for_status()
    except Exception as e:
        return f"Error shortlisting property: {str(e)}"

    track_funnel(user_id, "shortlist")
    return f"Property '{prop.get('property_name', property_name)}' has been shortlisted successfully."
