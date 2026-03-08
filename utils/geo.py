"""Shared geocoding helper for Rentok's /property/getLatLongProperty API.

Single source of truth for address→coordinates conversion. Handles both
response formats the API has returned historically:
  - Nested:    {"data": {"data": {"lat": ..., "lng": ...}}}
  - Top-level: {"lat": ..., "long": ...}
"""

from config import settings
from core.log import get_logger

logger = get_logger("utils.geo")


async def geocode_address(location: str) -> tuple[float | None, float | None]:
    """Convert an address string to (lat, lng) via Rentok's geocoding API.

    Returns (float, float) on success, (None, None) on any failure.
    Tries nested response format first, then top-level as fallback.
    """
    from utils.retry import http_post

    try:
        resp = await http_post(
            f"{settings.RENTOK_API_BASE_URL}/property/getLatLongProperty",
            json={"address": location},
            timeout=10,
        )
        # Primary format: {"data": {"data": {"lat": ..., "lng": ...}}}
        nested = resp.get("data", {}).get("data", {})
        lat = nested.get("lat") or nested.get("latitude")
        lng = nested.get("lng") or nested.get("longitude") or nested.get("long")

        # Fallback format: {"lat": ..., "long": ...} (top-level)
        if not lat or not lng:
            lat = resp.get("lat") or resp.get("latitude")
            lng = resp.get("lng") or resp.get("longitude") or resp.get("long")

        if lat and lng:
            return float(lat), float(lng)
    except Exception as e:
        logger.warning("geocode_address failed for '%s': %s", location, e)

    return None, None
