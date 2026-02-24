import httpx

from config import settings


async def get_scheduled_events(user_id: str, **kwargs) -> str:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{settings.RENTOK_API_BASE_URL}/bookingBot/booking/{user_id}/events"
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return f"Error fetching scheduled events: {str(e)}"

    events = data.get("data", [])
    if not events:
        return "No scheduled events found. Would you like to schedule a property visit or call?"

    lines = ["Your scheduled events:"]
    for event in events:
        name = event.get("property_name", "Unknown Property")
        date = event.get("visit_date", "")
        time = event.get("visit_time", "")
        visit_type = event.get("visit_type", "")
        status = event.get("status", "")

        line = f"- {name}: {visit_type} on {date} at {time}"
        if status:
            line += f" (Status: {status})"
        lines.append(line)

    return "\n".join(lines)
