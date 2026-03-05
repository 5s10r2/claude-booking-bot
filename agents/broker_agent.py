"""
Broker agent: handles property search, recommendations, details, images, shortlisting.
Uses Haiku (cost-optimized; switch back to SONNET_MODEL if quality drops).
"""

from config import settings
from core.claude import AnthropicEngine
from core.prompts import build_broker_prompt, format_prompt
from tools.registry import get_schemas_for_agent, get_handlers_for_agent
from core.tool_executor import ToolExecutor
from db.redis_store import get_account_values, build_returning_user_context
from utils.date import today_date, current_day


def get_config(user_id: str, language: str = "en") -> dict:
    """Return agent setup for use by both run() and streaming endpoint."""
    account = get_account_values(user_id)
    returning_ctx = build_returning_user_context(user_id)
    broker_template = build_broker_prompt(has_returning_context=bool(returning_ctx))
    system_prompt = format_prompt(
        broker_template,
        language=language,
        brand_name=account.get("brand_name", "our platform"),
        cities=account.get("cities", ""),
        areas=account.get("areas", ""),
        today_date=today_date(),
        current_day=current_day(),
        returning_user_context=returning_ctx,
    )
    tools = get_schemas_for_agent("broker")
    executor = ToolExecutor()
    executor.register_many(get_handlers_for_agent("broker"))
    return {
        "system_prompt": system_prompt,
        "tools": tools,
        "model": settings.HAIKU_MODEL,
        "executor": executor,
    }


async def run(
    engine: AnthropicEngine,
    messages: list[dict],
    user_id: str,
    language: str = "en",
) -> str:
    cfg = get_config(user_id, language=language)

    response = await engine.run_agent(
        system_prompt=cfg["system_prompt"],
        tools=cfg["tools"],
        messages=messages,
        model=cfg["model"],
        user_id=user_id,
        tool_executor=cfg["executor"],
        agent_name="broker",
    )
    return response
