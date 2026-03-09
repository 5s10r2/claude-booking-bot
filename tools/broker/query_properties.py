import httpx

from config import settings
from db.redis_store import get_whitelabel_pg_ids
from utils.api import RentokAPIError, check_rentok_response


TOOL_SCHEMA = {
    "name": "fetch_properties_by_query",
    "description": "Fetch properties matching a text query/name.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {"type": "string", "description": "Property name or search query"},
        },
        "required": ["query"],
    },
}


async def fetch_properties_by_query(user_id: str, query: str, **kwargs) -> str:
    pg_ids = get_whitelabel_pg_ids(user_id)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/fetch-all-properties",
                json={"pg_ids": pg_ids},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error fetching properties: {str(e)}"

    try:
        check_rentok_response(data, "fetch-all-properties")
    except RentokAPIError as e:
        return f"Error fetching properties: {e}"

    # fetch-all-properties returns data at top-level "data" key (array of property objects).
    # Each object uses "pg_name" (not "property_name" or "name") for the property name,
    # and "id" (UUID) / "pg_id" (Firebase UID) for identifiers.
    properties = data.get("data", data.get("properties", []))
    if not properties:
        return "No properties found."

    matches = []
    query_lower = query.strip().lower()
    for p in properties:
        # Name field is "pg_name" in the real API response
        name = p.get("pg_name", p.get("property_name", p.get("name", ""))).strip().lower()
        if query_lower in name or name in query_lower:
            matches.append(p)

    if not matches:
        return f"No properties matching '{query}' found."

    results = []
    for p in matches[:5]:
        display_name = p.get("pg_name") or p.get("property_name") or p.get("name", "")
        ms_data = p.get("microsite_data") or {}
        about = (ms_data.get("about") or "")[:80]
        link = p.get("microsite_link", "N/A")
        results.append(f"- {display_name} | {about} | Link: {link}")

    return f"Properties matching '{query}':\n" + "\n".join(results)
