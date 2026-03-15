import time
from typing import Any, Callable

from core.log import get_logger
from utils.properties import find_property

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
        prop = find_property(user_id, property_name)
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
    except Exception as e:
        logger.warning("Fallback lookup failed for %s: %s", tool_name, e)
        return f"Error executing {tool_name}: {error}"


class ToolExecutor:
    def __init__(self):
        self._handlers: dict[str, Callable] = {}
        self._fallback_handlers: dict[str, Callable] | None = None

    def register(self, name: str, handler: Callable) -> None:
        self._handlers[name] = handler

    def register_many(self, handlers: dict[str, Callable]) -> None:
        self._handlers.update(handlers)

    def set_fallback(self, handlers: dict[str, Callable]) -> None:
        """Set fallback handlers for graceful tool expansion on skill misses.

        When a tool is not found in the primary handler set, the executor
        checks the fallback set before returning an error. This ensures
        Claude can still call any broker tool even if skill detection was wrong.
        """
        self._fallback_handlers = handlers

    async def execute(self, tool_name: str, tool_input: dict, user_id: str) -> str:
        handler = self._handlers.get(tool_name)
        # Graceful expansion: if tool not in filtered set, try fallback
        if handler is None and self._fallback_handlers:
            handler = self._fallback_handlers.get(tool_name)
            if handler:
                logger.warning(
                    "Skill miss: tool '%s' not in filtered set — expanding from fallback",
                    tool_name,
                )
                # Track the miss for monitoring (brand-scoped)
                try:
                    from db.redis_store import track_skill_miss, get_user_brand
                    track_skill_miss(tool_name, brand_hash=get_user_brand(user_id))
                except Exception:
                    pass  # Non-blocking — don't break tool execution
                # Register for subsequent calls in this turn
                self._handlers[tool_name] = handler
        if handler is None:
            return f"Error: Unknown tool '{tool_name}'"
        t0 = time.monotonic()
        try:
            result = handler(user_id=user_id, **tool_input)
            if hasattr(result, "__await__"):
                result = await result
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._track(tool_name, True, latency_ms, user_id)
            return str(result)
        except Exception as e:
            latency_ms = int((time.monotonic() - t0) * 1000)
            self._track(tool_name, False, latency_ms, user_id)
            logger.error("Error executing %s: %s", tool_name, e, exc_info=True)
            return _build_fallback(tool_name, tool_input, user_id, str(e))

    @staticmethod
    def _track(tool_name: str, success: bool, latency_ms: int, user_id: str) -> None:
        """Fire-and-forget tool reliability tracking."""
        try:
            from db.redis_store import track_tool_result, get_user_brand
            track_tool_result(tool_name, success, latency_ms, brand_hash=get_user_brand(user_id))
        except Exception:
            pass  # Non-blocking — never break tool execution
