import httpx

from config import settings
from db.redis_store import (
    get_preferences,
    get_property_info_map,
    set_property_info_map,
    save_property_template,
    get_whitelabel_pg_ids,
    save_preferences as redis_save_preferences,
)


async def _geocode_location(location: str) -> tuple:
    """Convert a location string to lat/long using Rentok's geocoding API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/property/getLatLongProperty",
                json={"address": location},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {}).get("data", {})
            lat = data.get("lat")
            lng = data.get("lng")
            if lat and lng:
                return float(lat), float(lng)
    except Exception as e:
        print(f"[geocode] error for '{location}': {e}")
    return None, None


async def _call_search_api(payload: dict) -> list:
    """Call Rentok search API and return raw properties list."""
    # Rentok API requires pg_ids to be a non-empty array.
    # Empty [] causes SQL syntax error; missing key causes null reference.
    if not payload.get("pg_ids"):
        print("[search] WARNING: pg_ids is empty — API will return no results. "
              "Ensure account_values.pg_ids is configured.")
        return []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/property/getPropertyDetailsAroundLatLong",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            # Check for inner error (API returns 200 but data.status may be 500)
            inner = data.get("data", {})
            if inner.get("status") == 500:
                print(f"[search] API inner error: {inner.get('message', '')} — {inner.get('data', {}).get('error', '')}")
                return []
            return inner.get("data", {}).get("results", [])
    except Exception as e:
        print(f"[search] API error: {e}")
        return []


async def search_properties(user_id: str, radius_flag: bool = False, **kwargs) -> str:
    prefs = get_preferences(user_id)
    if not prefs.get("location"):
        return "No location set. Please save preferences with a location first."

    location = prefs.get("location", "")
    min_budget = prefs.get("min_budget", 0)
    max_budget = prefs.get("max_budget", 100000)
    amenities = prefs.get("amenities", "")
    property_type = prefs.get("property_type")
    unit_types = prefs.get("unit_types_available")
    pg_available_for = prefs.get("pg_available_for")
    sharing_types = prefs.get("sharing_types_enabled")
    radius = prefs.get("radius", 20000)

    if radius_flag:
        radius = min(radius + 5000, 35000)
        prefs["radius"] = radius
        redis_save_preferences(user_id, prefs)

    # Step 1: Geocode location to lat/long
    lat, lng = await _geocode_location(location)
    if lat is None or lng is None:
        return f"Could not find coordinates for '{location}'. Please try a more specific area or city name."

    print(f"[search] geocoded '{location}' → lat={lat}, lng={lng}")

    # Step 2: Get PG IDs
    pg_ids = get_whitelabel_pg_ids(user_id)

    # Step 3: Build payload matching the original API format
    payload = {
        "coords": [[lat, lng]],
        "radius": radius,
        "rent_ends_to": max_budget if max_budget else 10000000,
        "pg_ids": pg_ids,
    }
    if min_budget:
        payload["rent_starts_from"] = min_budget
    if unit_types:
        payload["unit_types_available"] = unit_types
    if pg_available_for and pg_available_for in ["All Boys", "All Girls"]:
        payload["pg_available_for"] = pg_available_for
    if sharing_types:
        payload["sharing_type_enabled"] = sharing_types

    print(f"[search] payload → {payload}")

    # Step 4: Search with progressive relaxation — ALWAYS return results
    properties = await _call_search_api(payload)
    relaxed_note = ""

    if not properties:
        # Round 1: expand radius, double budget, drop min_budget
        payload["radius"] = 35000
        payload["rent_ends_to"] = max(max_budget * 2, 200000) if max_budget else 10000000
        payload.pop("rent_starts_from", None)
        print(f"[search] relaxation round 1 → {payload}")
        properties = await _call_search_api(payload)
        relaxed_note = "[RELAXED: expanded area, flexible budget] "

    if not properties:
        # Round 2: drop ALL filters, just coords + pg_ids + wide radius
        payload = {"coords": [[lat, lng]], "radius": 50000, "rent_ends_to": 10000000, "pg_ids": pg_ids}
        print(f"[search] relaxation round 2 → {payload}")
        properties = await _call_search_api(payload)
        relaxed_note = "[RELAXED: showing all nearby properties] "

    if not properties:
        return "No properties are currently available in this region."

    print(f"[search] found {len(properties)} properties")

    existing_map = get_property_info_map(user_id)
    property_template = []

    results = []
    for p in properties[:20]:
        property_name = p.get("p_pg_name", p.get("property_name", "Property"))
        address = ", ".join(filter(None, [
            p.get("p_address_line_1", ""),
            p.get("p_address_line_2", ""),
            p.get("p_city", ""),
        ]))
        rent = p.get("p_rent_starts_from", p.get("rent", ""))
        available_for = p.get("p_pg_available_for", "Any")
        prop_type = p.get("p_property_type", "")
        prop_id = p.get("p_id", p.get("prop_id", ""))
        pg_id = p.get("p_pg_id", "")
        pg_number = p.get("p_pg_number", "")
        eazypg_id = p.get("p_eazypg_id", "")
        image = p.get("p_image", p.get("image", ""))
        distance = p.get("p_distance", p.get("distance", ""))
        lat_val = p.get("p_latitude", p.get("latitude", ""))
        long_val = p.get("p_longitude", p.get("longitude", ""))
        phone = p.get("p_phone_number", "")
        min_token = p.get("p_min_token_amount", 1000)
        microsite_url = p.get("p_microsite_url", p.get("microsite_url", ""))
        match_score = p.get("p_match_score", p.get("match_score", ""))
        sharing_types_data = p.get("p_sharing_types_enabled", [])

        info = {
            "property_name": property_name,
            "property_location": address,
            "property_rent": str(rent),
            "pg_available_for": available_for,
            "property_type": prop_type,
            "property_image": image,
            "prop_id": prop_id,
            "property_id": prop_id,                    # alias for booking tools
            "pg_id": pg_id,
            "pg_number": pg_number,
            "eazypg_id": eazypg_id,
            "property_link": microsite_url,
            "google_map": f"https://www.google.com/maps?q={lat_val},{long_val}" if lat_val and long_val else "",
            "match_score": match_score,
            "distance": distance,
            "property_lat": lat_val,
            "property_long": long_val,
            "phone_number": phone,
            "min_token_amount": min_token,
            "property_min_token_amount": min_token,    # alias for payment tool
            "sharing_types": sharing_types_data,
        }
        existing_map.append(info)
        property_template.append(info)

        results.append(
            f"- {property_name} | {address} | "
            f"Rent starts from: {rent} | For: {available_for} | "
            f"Match: {match_score} | Distance: {distance} | "
            f"Image: {image} | Link: {microsite_url}"
        )

    set_property_info_map(user_id, existing_map)
    save_property_template(user_id, property_template[:5])

    return f"{relaxed_note}Found {len(properties)} properties. Here are the results:\n" + "\n".join(results)
