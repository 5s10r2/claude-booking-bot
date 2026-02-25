import httpx

from config import settings
from db.redis_store import get_property_info_map, set_property_info_map


def _find_property(user_id: str, property_name: str) -> dict | None:
    info_map = get_property_info_map(user_id)
    for p in info_map:
        if p.get("property_name", "").strip().lower() == property_name.strip().lower():
            return p
    for p in info_map:
        if property_name.strip().lower() in p.get("property_name", "").strip().lower():
            return p
    return None


async def fetch_property_details(user_id: str, property_name: str, **kwargs) -> str:
    prop = _find_property(user_id, property_name)
    if not prop:
        return f"Property '{property_name}' not found. Please check the exact name from search results."

    prop_id = prop.get("prop_id") or prop.get("pg_id")
    if not prop_id:
        return "Property ID not available."

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/property/property-details-bots",
                json={"property_id": prop_id},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error fetching property details: {str(e)}"

    pd = data.get("property_data", data.get("data", {}))
    rooms = data.get("property_rooms", data.get("rooms", []))

    # Fallback if API returned no meaningful data
    if not pd or not any(pd.get(k) for k in ("property_name", "location", "address", "rent_starts_from", "amenities")):
        return (
            f"Detailed info for '{prop.get('property_name', property_name)}' is currently unavailable. "
            f"Here's what we know: Location: {prop.get('property_location', 'N/A')}, "
            f"Rent starts from: {prop.get('property_rent', 'N/A')}, "
            f"Type: {prop.get('property_type', 'N/A')}. "
            f"Link: {prop.get('property_link', 'N/A')}"
        )

    details = {
        "property_name": pd.get("property_name", prop.get("property_name", "")),
        "location": pd.get("location", pd.get("address", "")),
        "rent_starts_from": pd.get("rent_starts_from", pd.get("rent", "")),
        "amenities": pd.get("amenities", ""),
        "unit_types_available": pd.get("unit_types_available", ""),
        "property_type": pd.get("property_type", ""),
        "tenants_preferred": pd.get("tenants_preferred", ""),
        "notice_period": pd.get("notice_period", ""),
        "agreement_period": pd.get("agreement_period", ""),
        "checkin_time": pd.get("checkin_time", ""),
        "checkout_time": pd.get("checkout_time", ""),
        "locking_period": pd.get("locking_period", ""),
        "gst_on_rent": pd.get("gst_on_rent", ""),
        "property_rules": pd.get("property_rules", ""),
        "common_amenities": pd.get("common_amenities", ""),
        "food_amenities": pd.get("food_amenities", ""),
        "services_amenities": pd.get("services_amenities", ""),
        "about": pd.get("about", pd.get("owner_description", "")),
        "reviews": pd.get("reviews", ""),
        "faqs": pd.get("faqs", ""),
        "google_map": pd.get("google_map", prop.get("google_map", "")),
        "microsite_url": pd.get("microsite_url", prop.get("property_link", "")),
        "min_token_amount": pd.get("min_token_amount", ""),
    }

    info_map = get_property_info_map(user_id)
    for p in info_map:
        if p.get("property_name", "").strip().lower() == details["property_name"].strip().lower():
            p.update({k: v for k, v in details.items() if v})
            break
    set_property_info_map(user_id, info_map)

    result = f"PROPERTY DETAILS: {details['property_name']}\n"
    for key, val in details.items():
        if val and key not in ("property_name",):
            label = key.replace("_", " ").title()
            result += f"- {label}: {val}\n"

    if rooms:
        result += "\nAVAILABLE ROOMS:\n"
        for room in rooms[:10]:
            result += f"- {room.get('room_name', 'Room')}: {room.get('sharing_type', '')} sharing, Rent: {room.get('rent', 'N/A')}\n"

    return result
