from typing import Any, Callable


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
            print(f"[tool_executor] Error executing {tool_name}: {e}")
            return f"Error executing {tool_name}: {str(e)}"
