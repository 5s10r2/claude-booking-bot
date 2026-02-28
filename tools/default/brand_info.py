import hashlib
import httpx

from config import settings
from db.redis_store import get_whitelabel_pg_ids, _json_get, _json_set
from core.log import get_logger

logger = get_logger("tools.brand_info")

_BRAND_CACHE_TTL = 86400  # 24 hours


async def brand_info(user_id: str, **kwargs) -> str:
    pg_ids = get_whitelabel_pg_ids(user_id)
    if not pg_ids:
        return "Brand information not available."

    pg_ids_str = ",".join(str(p) for p in pg_ids) if isinstance(pg_ids, list) else str(pg_ids)

    # --- Check cache first ---
    cache_key = f"brand_info:{hashlib.md5(pg_ids_str.encode()).hexdigest()}"
    cached = _json_get(cache_key)
    if cached:
        logger.debug("brand_info cache hit for pg_ids=%s", pg_ids_str)
        return cached

    # --- Cache miss → fetch from API ---
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/property-info",
                params={"pg_ids": pg_ids_str},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
    except Exception as e:
        logger.warning("brand_info API failed: %s", e)
        return f"Error fetching brand info: {str(e)}"

    if not data:
        return "No brand information found."

    lines = ["Brand & Property Information:"]

    if data.get("rent"):
        lines.append(f"- Rent Range: {data['rent']}")
    if data.get("token_amount"):
        lines.append(f"- Token Amount: {data['token_amount']}")
    if data.get("property_type"):
        lines.append(f"- Property Types: {data['property_type']}")
    if data.get("tenants_preferred"):
        lines.append(f"- Tenants Preferred: {data['tenants_preferred']}")
    if data.get("unit_types_available"):
        lines.append(f"- Unit Types: {data['unit_types_available']}")
    if data.get("sharing_types_enabled"):
        lines.append(f"- Sharing Types: {data['sharing_types_enabled']}")
    if data.get("pg_availability"):
        lines.append(f"- Available For: {data['pg_availability']}")
    if data.get("common_amenities"):
        lines.append(f"- Common Amenities: {data['common_amenities']}")
    if data.get("uniqueAmenityNames"):
        lines.append(f"- Special Amenities: {data['uniqueAmenityNames']}")
    if data.get("services_amenities"):
        lines.append(f"- Services: {data['services_amenities']}")
    if data.get("emergency_stay_rate"):
        lines.append(f"- Emergency Stay Rate: {data['emergency_stay_rate']}")
    if data.get("address"):
        lines.append(f"- Address: {data['address']}")

    result = "\n".join(lines)

    # --- Cache the result ---
    try:
        _json_set(cache_key, result, ex=_BRAND_CACHE_TTL)
        logger.debug("brand_info cached for pg_ids=%s (24h TTL)", pg_ids_str)
    except Exception as e:
        logger.warning("brand_info cache write failed: %s", e)

    return result
