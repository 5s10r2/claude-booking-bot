"""
Booking agent: handles visits, calls, KYC, payments, reservations, cancellations.
Uses Sonnet (complex multi-step flows: KYC → Payment → Reserve).
"""

from config import settings
from core.claude import AnthropicEngine
from core.prompts import BOOKING_AGENT_PROMPT, format_prompt
from tools.registry import get_schemas_for_agent, get_handlers_for_agent
from core.tool_executor import ToolExecutor
from db.redis_store import get_account_values
from utils.date import today_date, current_day


async def run(
    engine: AnthropicEngine,
    messages: list[dict],
    user_id: str,
) -> str:
    account = get_account_values(user_id)

    system_prompt = format_prompt(
        BOOKING_AGENT_PROMPT,
        brand_name=account.get("brand_name", "our platform"),
        cities=account.get("cities", ""),
        areas=account.get("areas", ""),
        today_date=today_date(),
        current_day=current_day(),
    )

    tools = get_schemas_for_agent("booking")

    executor = ToolExecutor()
    executor.register_many(get_handlers_for_agent("booking"))

    original_executor = engine.tool_executor
    engine.tool_executor = executor

    try:
        response = await engine.run_agent(
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
            model=settings.SONNET_MODEL,
            user_id=user_id,
        )
    finally:
        engine.tool_executor = original_executor

    return response
