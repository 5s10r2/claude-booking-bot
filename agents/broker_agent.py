"""
Broker agent: handles property search, recommendations, details, images, shortlisting.
Uses Haiku (cost-optimized; switch back to SONNET_MODEL if quality drops).

Supports two modes (controlled by DYNAMIC_SKILLS_ENABLED):
- Dynamic skills: Loads only relevant prompt sections + filtered tools per turn
- Legacy: Full monolithic prompt + all broker tools (fallback)
"""

from config import settings
from core.claude import AnthropicEngine
from core.log import get_logger
from core.prompts import BROKER_AGENT_PROMPT, format_prompt
from core.tool_executor import ToolExecutor
from db.redis_store import get_account_values, build_returning_user_context
from tools.registry import get_schemas_for_agent, get_handlers_for_agent
from utils.date import today_date, current_day

log = get_logger(__name__)


def get_config(user_id: str, language: str = "en", skills: list[str] | None = None) -> dict:
    """Return agent setup for use by both run() and streaming endpoint.

    When DYNAMIC_SKILLS_ENABLED:
      - Loads only relevant skill .md files + few-shot examples
      - Filters tools to match loaded skills
      - Returns system_prompt as list[str] for split caching

    When disabled (fallback):
      - Uses monolithic BROKER_AGENT_PROMPT (identical to pre-feature behavior)
      - Loads all broker tools
    """
    account = get_account_values(user_id)
    returning_ctx = build_returning_user_context(user_id)

    template_vars = dict(
        language=language,
        brand_name=account.get("brand_name", "our platform"),
        cities=account.get("cities", ""),
        areas=account.get("areas", ""),
        today_date=today_date(),
        current_day=current_day(),
        returning_user_context=returning_ctx,
    )

    # ── Legacy path: monolithic prompt (feature flag OFF) ──────────────
    if not settings.DYNAMIC_SKILLS_ENABLED:
        system_prompt = format_prompt(BROKER_AGENT_PROMPT, **template_vars)
        tools = get_schemas_for_agent("broker")
        executor = ToolExecutor()
        executor.register_many(get_handlers_for_agent("broker"))
        return {
            "system_prompt": system_prompt,
            "tools": tools,
            "model": settings.HAIKU_MODEL,
            "executor": executor,
        }

    # ── Dynamic skill path ─────────────────────────────────────────────
    from skills.loader import build_skill_prompt
    from skills.skill_map import get_tools_for_skills, ALWAYS_SKILLS
    from tools.registry import get_schemas_by_names, get_handlers_by_names

    is_returning = bool(returning_ctx)

    # Determine skills (fallback if supervisor didn't provide any)
    if not skills:
        skills = ["search", "qualify_returning" if is_returning else "qualify_new"]

    # Auto-add qualifying when search is present but no qualify skill
    if "search" in skills and not any(s.startswith("qualify") for s in skills):
        skills.insert(0, "qualify_returning" if is_returning else "qualify_new")

    # Selectively add selling guidance for detail/compare/objection turns
    if any(s in skills for s in ("details", "compare")) and "selling" not in skills:
        skills.append("selling")

    # Add always-on skills (currently empty — kept for future use)
    for s in ALWAYS_SKILLS:
        if s not in skills:
            skills.append(s)

    log.info("user=%s skills=%s", user_id, skills)

    # Build two-block prompt: base (cached) + dynamic skills (NOT cached)
    base_prompt, skill_prompt = build_skill_prompt("broker", skills, **template_vars)

    # Filter tools to match loaded skills
    tool_names = get_tools_for_skills(skills)
    tools = get_schemas_by_names(tool_names)

    executor = ToolExecutor()
    executor.register_many(get_handlers_by_names(tool_names))
    # Set fallback to all broker tools for graceful expansion on skill misses
    executor.set_fallback(get_handlers_for_agent("broker"))

    return {
        "system_prompt": [base_prompt, skill_prompt],  # Two blocks for split caching
        "tools": tools,
        "model": settings.HAIKU_MODEL,
        "executor": executor,
        "skills": skills,
    }


async def run(
    engine: AnthropicEngine,
    messages: list[dict],
    user_id: str,
    language: str = "en",
    skills: list[str] | None = None,
) -> str:
    cfg = get_config(user_id, language=language, skills=skills)

    original_executor = engine.tool_executor
    engine.tool_executor = cfg["executor"]

    try:
        response = await engine.run_agent(
            system_prompt=cfg["system_prompt"],
            tools=cfg["tools"],
            messages=messages,
            model=cfg["model"],
            user_id=user_id,
        )
    finally:
        engine.tool_executor = original_executor

    return response
