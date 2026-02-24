"""
Default agent: handles greetings, general questions, and brand info.
Uses Haiku (fast, cheap) since tasks are simple.
"""

from config import settings
from core.claude import AnthropicEngine
from core.prompts import DEFAULT_AGENT_PROMPT, format_prompt
from tools.registry import get_schemas_for_agent, get_handlers_for_agent
from core.tool_executor import ToolExecutor
from db.redis_store import get_account_values, get_user_name
from utils.date import today_date, current_day


async def run(
    engine: AnthropicEngine,
    messages: list[dict],
    user_id: str,
) -> str:
    account = get_account_values(user_id)
    user_name = get_user_name(user_id) or "there"

    system_prompt = format_prompt(
        DEFAULT_AGENT_PROMPT,
        brand_name=account.get("brand_name", "our platform"),
        cities=account.get("cities", ""),
        areas=account.get("areas", ""),
        user_name=user_name,
        today_date=today_date(),
        current_day=current_day(),
    )

    tools = get_schemas_for_agent("default")

    # Build a scoped tool executor for this agent
    executor = ToolExecutor()
    executor.register_many(get_handlers_for_agent("default"))

    # Temporarily swap the engine's executor
    original_executor = engine.tool_executor
    engine.tool_executor = executor

    try:
        response = await engine.run_agent(
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
            model=settings.HAIKU_MODEL,
            user_id=user_id,
        )
    finally:
        engine.tool_executor = original_executor

    return response
