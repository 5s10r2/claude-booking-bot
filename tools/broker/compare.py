"""
Structured property comparison: fetches details for 2-3 properties in parallel
and returns a structured comparison table with a recommendation.

Reduces comparison from 4+ LLM turns to 1 tool call + 1 response.
"""

import asyncio

import httpx

from config import settings
from core.log import get_logger
from db.redis_store import get_property_info_map, get_preferences, get_user_memory
from utils.scoring import match_score as calc_match_score

logger = get_logger("tools.compare")


def _find_property(user_id: str, property_name: str) -> dict | None:
    info_map = get_property_info_map(user_id)
    for p in info_map:
        if p.get("property_name", "").strip().lower() == property_name.strip().lower():
            return p
    for p in info_map:
        if property_name.strip().lower() in p.get("property_name", "").strip().lower():
            return p
    return None


async def _fetch_details(prop_id: str) -> dict:
    """Fetch property details from API. Returns raw dict or empty on failure."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/property/property-details-bots",
                json={"property_id": prop_id},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("property_data", data.get("data", {})) or {}
    except Exception as e:
        logger.warning("compare: details fetch failed for %s: %s", prop_id, e)
        return {}


async def _fetch_rooms(eazypg_id: str) -> list:
    """Fetch room details. Returns list or empty on failure."""
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
    except Exception as e:
        logger.warning("compare: rooms fetch failed for %s: %s", eazypg_id, e)
        return []


async def compare_properties(
    user_id: str,
    property_names: str,
    **kwargs,
) -> str:
    """Compare 2-3 properties side-by-side with structured data + recommendation."""
    names = [n.strip() for n in property_names.split(",") if n.strip()]
    if len(names) < 2:
        return "Please provide at least 2 property names separated by commas to compare."
    if len(names) > 3:
        names = names[:3]

    # Resolve properties from info_map
    props = []
    for name in names:
        prop = _find_property(user_id, name)
        if not prop:
            return f"Property '{name}' not found in search results. Please check the exact name."
        props.append(prop)

    # Fetch details + rooms in parallel for all properties
    tasks = []
    for prop in props:
        prop_id = prop.get("prop_id") or prop.get("pg_id", "")
        eazypg_id = prop.get("eazypg_id", "")
        tasks.append(_fetch_details(prop_id))
        tasks.append(_fetch_rooms(eazypg_id))

    results = await asyncio.gather(*tasks)

    # Build comparison data
    prefs = get_preferences(user_id)
    user_mem = get_user_memory(user_id)
    deal_breakers = user_mem.get("deal_breakers", [])

    comparison = []
    for i, prop in enumerate(props):
        details = results[i * 2] or {}
        rooms = results[i * 2 + 1] or []

        # Merge search data + API details
        name = details.get("property_name") or prop.get("property_name", "Property")
        location = details.get("location") or details.get("address") or prop.get("property_location", "N/A")
        rent = details.get("rent_starts_from") or prop.get("property_rent", "N/A")
        amenities = details.get("common_amenities") or details.get("amenities") or ""
        food = details.get("food_amenities", "")
        services = details.get("services_amenities", "")
        prop_type = details.get("property_type") or prop.get("property_type", "")
        available_for = details.get("tenants_preferred") or prop.get("pg_available_for", "")
        notice = details.get("notice_period", "")
        agreement = details.get("agreement_period", "")
        token = details.get("min_token_amount") or prop.get("min_token_amount", "")
        maps_link = prop.get("google_map", "")
        microsite = details.get("microsite_url") or prop.get("property_link", "")
        distance = prop.get("distance", "")

        # Room summary
        room_summary = []
        total_beds = 0
        for room in rooms[:5]:
            rname = room.get("room_name", room.get("name", "Room"))
            sharing = room.get("sharing_type", "")
            beds = room.get("beds_available", room.get("available", "?"))
            room_rent = room.get("rent", "N/A")
            room_summary.append(f"{rname}: {sharing} sharing, ₹{room_rent}, {beds} beds available")
            try:
                total_beds += int(beds)
            except (ValueError, TypeError):
                pass

        # Custom match score
        prop_data = {
            "rent": rent,
            "distance": distance,
            "amenities": amenities,
            "property_type": prop_type,
            "pg_available_for": available_for,
        }
        scoring_prefs = {
            "min_budget": prefs.get("min_budget", 0),
            "max_budget": prefs.get("max_budget", 100000),
            "amenities": prefs.get("amenities", ""),
            "must_have_amenities": prefs.get("must_have_amenities", ""),
            "nice_to_have_amenities": prefs.get("nice_to_have_amenities", ""),
            "property_type": prefs.get("property_type", ""),
            "pg_available_for": prefs.get("pg_available_for", ""),
        }
        score = calc_match_score(prop_data, scoring_prefs, deal_breakers=deal_breakers)

        comparison.append({
            "name": name,
            "location": location,
            "rent": rent,
            "score": score,
            "amenities": amenities,
            "food": food,
            "services": services,
            "type": prop_type,
            "available_for": available_for,
            "notice_period": notice,
            "agreement_period": agreement,
            "token_amount": token,
            "distance": distance,
            "rooms": room_summary,
            "total_beds": total_beds,
            "maps_link": maps_link,
            "microsite": microsite,
        })

    # Build structured comparison output
    output = "PROPERTY COMPARISON\n" + "=" * 50 + "\n\n"

    for c in comparison:
        output += f"📍 {c['name']}\n"
        output += f"   Location: {c['location']}\n"
        output += f"   Rent starts from: ₹{c['rent']}\n"
        output += f"   Match Score: {c['score']}/100\n"
        output += f"   Type: {c['type']} | For: {c['available_for']}\n"
        if c['distance']:
            output += f"   Distance: {c['distance']}m\n"
        if c['amenities']:
            output += f"   Amenities: {c['amenities']}\n"
        if c['food']:
            output += f"   Food: {c['food']}\n"
        if c['services']:
            output += f"   Services: {c['services']}\n"
        if c['notice_period']:
            output += f"   Notice Period: {c['notice_period']}\n"
        if c['token_amount']:
            output += f"   Token Amount: ₹{c['token_amount']}\n"
        if c['rooms']:
            output += f"   Rooms ({c['total_beds']} beds total):\n"
            for r in c['rooms']:
                output += f"     • {r}\n"
        if c['maps_link']:
            output += f"   Map: {c['maps_link']}\n"
        if c['microsite']:
            output += f"   Link: {c['microsite']}\n"
        output += "\n"

    # Recommendation
    best = max(comparison, key=lambda x: x["score"])
    output += "=" * 50 + "\n"
    output += f"RECOMMENDATION: {best['name']} (score: {best['score']}/100)\n"
    output += "Use this data to explain WHY this property is the best fit. Consider rent, amenities, distance, and the user's specific needs.\n"

    return output
