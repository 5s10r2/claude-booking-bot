from typing import Any, Callable

from core.log import get_logger

logger = get_logger("core.tool_executor")

# Tools that can fall back to cached property data on failure
_PROPERTY_FALLBACK_TOOLS = {
    "fetch_property_details",
    "fetch_room_details",
    "fetch_property_images",
    "fetch_landmarks",
    "fetch_nearby_places",
    "compare_properties",
}


def _build_fallback(tool_name: str, tool_input: dict, user_id: str, error: str) -> str:
    """Try to return useful cached data instead of a raw error message."""
    if tool_name not in _PROPERTY_FALLBACK_TOOLS:
        return f"Error executing {tool_name}: {error}"

    property_name = tool_input.get("property_name", tool_input.get("property_names", ""))
    if not property_name:
        return f"Error executing {tool_name}: {error}"

    try:
        from db.redis_store import get_property_info_map
        info_map = get_property_info_map(user_id)
        prop = None
        for p in info_map:
            if property_name.strip().lower() in p.get("property_name", "").strip().lower():
                prop = p
                break

        if not prop:
            return f"Error executing {tool_name}: {error}"

        # Build a helpful fallback from cached search data
        name = prop.get("property_name", property_name)
        parts = [f"[Tool error — showing cached data for '{name}']"]
        if prop.get("property_location"):
            parts.append(f"Location: {prop['property_location']}")
        if prop.get("property_rent"):
            parts.append(f"Rent starts from: ₹{prop['property_rent']}")
        if prop.get("pg_available_for"):
            parts.append(f"For: {prop['pg_available_for']}")
        if prop.get("property_type"):
            parts.append(f"Type: {prop['property_type']}")
        if prop.get("google_map"):
            parts.append(f"Map: {prop['google_map']}")
        if prop.get("property_link"):
            parts.append(f"Link: {prop['property_link']}")
        parts.append("Suggest: schedule a call to get more details directly from the property.")
        return "\n".join(parts)
    except Exception:
        return f"Error executing {tool_name}: {error}"


class ToolExecutor:
    def __init__(self):
        self._handlers: dict[str, Callable] = {}

    def register(self, name: str, handler: Callable) -> None:
        self._handlers[name] = handler

    def register_many(self, handlers: dict[str, Callable]) -> None:
        self._handlers.update(handlers)

    async def execute(self, tool_name: str, tool_input: dict, user_id: str) -> str:
        handler = self._handlers.get(tool_name)
        if handler is None:
            return f"Error: Unknown tool '{tool_name}'"
        try:
            result = handler(user_id=user_id, **tool_input)
            if hasattr(result, "__await__"):
                result = await result
            return str(result)
        except Exception as e:
            logger.error("Error executing %s: %s", tool_name, e, exc_info=True)
            return _build_fallback(tool_name, tool_input, user_id, str(e))
