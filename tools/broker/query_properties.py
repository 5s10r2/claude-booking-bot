import httpx

from config import settings
from db.redis_store import get_whitelabel_pg_ids


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

    properties = data.get("properties", data.get("data", []))
    if not properties:
        return "No properties found."

    matches = []
    query_lower = query.strip().lower()
    for p in properties:
        name = p.get("property_name", p.get("name", "")).strip().lower()
        if query_lower in name or name in query_lower:
            matches.append(p)

    if not matches:
        return f"No properties matching '{query}' found."

    results = []
    for p in matches[:5]:
        results.append(
            f"- {p.get('property_name', p.get('name', ''))} | "
            f"{p.get('location', p.get('address', ''))} | "
            f"Rent: {p.get('rent', p.get('rent_starts_from', ''))}"
        )

    return f"Properties matching '{query}':\n" + "\n".join(results)
