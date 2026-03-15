"""
core/attention.py — Needs-attention flag computation.

Pre-computed attention flags cached per user. Conditions that trigger "needs attention":

| Condition                                        | Flag              |
|--------------------------------------------------|-------------------|
| Last user message has no bot response             | no_response       |
| User sent negative feedback in this conversation  | negative_feedback |
| High-value lead (score >= 70) stalled at early stage | hot_lead_stalled |
| Human mode active                                 | human_active      |
| 2+ tool failures in last 5 messages               | tool_errors       |

Storage: {uid}:attention_flags — JSON list of flag strings, 1-hour TTL.
Triggered: on conversation save (inside save_conversation).
"""

import json
from typing import Optional

from core.log import get_logger
from db.redis._base import _r, _json_get, _json_set

logger = get_logger("core.attention")

# 1-hour TTL for attention flags — recomputed on next conversation save
ATTENTION_FLAGS_TTL = 3600

# Early funnel stages where a hot lead is considered "stalled"
_EARLY_STAGES = {"", "search", "detail", "shortlist"}


def compute_attention_flags(
    uid: str,
    conversation: list[dict],
    user_memory: dict,
    brand_hash: str | None = None,
) -> list[str]:
    """Compute attention flags for a user based on their current state.

    All checks are cheap — reads only from data already loaded by the caller
    (conversation, user_memory) or quick Redis GETs.

    Returns a list of flag strings (empty = no attention needed).
    """
    flags: list[str] = []

    # 1. no_response — last user message has no bot response
    if conversation and len(conversation) >= 1:
        last = conversation[-1]
        if last.get("role") == "user":
            # User message is the last thing — no bot reply yet
            flags.append("no_response")

    # 2. negative_feedback — check Redis feedback log for this user
    try:
        raw = _r().lrange("feedback:log", -50, -1)
        for entry in reversed(raw or []):
            try:
                fb = json.loads(entry)
                if fb.get("user_id") == uid:
                    if fb.get("rating") == "down":
                        flags.append("negative_feedback")
                    break  # Only check most recent for this user
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception:
        pass

    # 3. hot_lead_stalled — high lead score but stuck in early funnel
    lead_score = user_memory.get("lead_score", 0)
    funnel_max = user_memory.get("funnel_max", "")
    if lead_score >= 70 and funnel_max in _EARLY_STAGES:
        flags.append("hot_lead_stalled")

    # 4. human_active — human mode is on
    try:
        from db.redis.admin import get_human_mode
        if get_human_mode(uid, brand_hash=brand_hash):
            flags.append("human_active")
    except Exception:
        pass

    # 5. tool_errors — 2+ tool failures in last 5 messages
    error_count = 0
    recent_msgs = conversation[-5:] if len(conversation) >= 5 else conversation
    for msg in recent_msgs:
        content = msg.get("content", "")
        if isinstance(content, str) and any(
            marker in content.lower()
            for marker in ["error", "failed", "exception", "timeout", "could not"]
        ):
            # Only count assistant messages with error markers (tool results)
            if msg.get("role") in ("assistant", "tool"):
                error_count += 1
    if error_count >= 2:
        flags.append("tool_errors")

    return flags


def save_attention_flags(uid: str, flags: list[str]) -> None:
    """Cache attention flags with 1-hour TTL."""
    _r().setex(f"{uid}:attention_flags", ATTENTION_FLAGS_TTL, json.dumps(flags))


def get_attention_flags(uid: str) -> list[str]:
    """Return cached attention flags, or empty list if expired/missing."""
    raw = _r().get(f"{uid}:attention_flags")
    if raw is None:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def update_attention_flags(
    uid: str,
    conversation: list[dict],
    user_memory: dict,
    brand_hash: str | None = None,
) -> list[str]:
    """Compute + save attention flags in one call. Returns the flags."""
    flags = compute_attention_flags(uid, conversation, user_memory, brand_hash=brand_hash)
    save_attention_flags(uid, flags)
    return flags
