"""
Supervisor agent: routes user messages to the correct specialist agent.

Uses Haiku for fast, cheap classification. Returns a JSON object with
the agent name ("default", "broker", "booking", "profile").
"""

from config import settings
from core.claude import AnthropicEngine
from core.prompts import SUPERVISOR_PROMPT

VALID_AGENTS = {"default", "broker", "booking", "profile"}


async def route(engine: AnthropicEngine, messages: list[dict]) -> str:
    """Classify the user's latest message and return the target agent name."""
    result = engine.classify(
        system_prompt=SUPERVISOR_PROMPT,
        messages=messages,
        model=settings.HAIKU_MODEL,
    )

    if result and isinstance(result, dict):
        agent = result.get("agent", "").lower().strip()
        if agent in VALID_AGENTS:
            return agent

    # Fallback: default agent
    return "default"
