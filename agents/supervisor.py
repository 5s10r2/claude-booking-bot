"""
Supervisor agent: routes user messages to the correct specialist agent.

Uses Haiku for fast, cheap classification. Returns a dict with
the agent name and (for broker) detected skills.
"""

from config import settings
from core.claude import AnthropicEngine
from core.log import get_logger
from core.prompts import SUPERVISOR_PROMPT

log = get_logger(__name__)

VALID_AGENTS = {"default", "broker", "booking", "profile"}


async def route(engine: AnthropicEngine, messages: list[dict]) -> dict:
    """Classify the user's latest message and return routing info.

    Returns {"agent": str, "skills": list[str]}.
    Skills are only populated for the "broker" agent.
    """
    # Supervisor only needs recent context for classification.
    # Rules 4-5 check "previous bot message was about X AND user replies Y"
    # which requires at most 1 prior assistant + 1 current user message.
    # 4 messages (2 full turns) covers all routing rules with padding.
    trimmed = messages[-4:] if len(messages) > 4 else messages
    result = await engine.classify(
        system_prompt=SUPERVISOR_PROMPT,
        messages=trimmed,
        model=settings.HAIKU_MODEL,
    )

    if result and isinstance(result, dict):
        agent = result.get("agent", "").lower().strip()
        if agent in VALID_AGENTS:
            skills = result.get("skills", [])
            # Validate: skills must be a list of strings
            if isinstance(skills, list):
                skills = [s for s in skills if isinstance(s, str)]
            else:
                skills = []
            return {"agent": agent, "skills": skills}

    # Fallback: default agent
    return {"agent": "default", "skills": []}
