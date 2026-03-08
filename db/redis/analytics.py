"""
db/redis/analytics.py — Analytics, feedback, skill tracking, funnel, and WhatsApp dedup.

Covers:
  - Feedback (thumbs up/down)
  - Agent usage tracking
  - Skill usage + miss tracking
  - Funnel stage tracking
  - WhatsApp message response tracking (dedup)
"""

import json
import time
from datetime import date
from typing import Optional

from db.redis._base import _r, ANALYTICS_TTL


# ---------------------------------------------------------------------------
# Feedback (thumbs up / down)
# ---------------------------------------------------------------------------

def save_feedback(user_id: str, message_snippet: str, rating: str, agent: str = "") -> None:
    """Store a feedback entry. rating is 'up' or 'down'."""
    entry = json.dumps({
        "user_id": user_id,
        "snippet": message_snippet[:200],
        "rating": rating,
        "agent": agent,
        "ts": time.time(),
    })
    _r().rpush("feedback:log", entry)
    # Aggregate counters per agent
    _r().hincrby("feedback:counts", f"{agent}:{rating}", 1)
    _r().hincrby("feedback:counts", f"total:{rating}", 1)


def get_feedback_counts() -> dict[str, int]:
    """Return all feedback counters as a dict."""
    raw = _r().hgetall("feedback:counts")
    return {k.decode(): int(v) for k, v in raw.items()} if raw else {}


# ---------------------------------------------------------------------------
# Agent usage tracking (analytics)
# ---------------------------------------------------------------------------

def track_agent_usage(user_id: str, agent_name: str) -> None:
    """Increment agent usage counter for today. 90-day TTL."""
    day = date.today().isoformat()
    key = f"agent_usage:{day}"
    _r().hincrby(key, agent_name, 1)
    _r().expire(key, ANALYTICS_TTL)


def get_agent_usage(day: str = None) -> dict[str, int]:
    """Return {agent: count} for a given day (default: today)."""
    if day is None:
        day = date.today().isoformat()
    raw = _r().hgetall(f"agent_usage:{day}")
    return {k.decode(): int(v) for k, v in raw.items()} if raw else {}


# ---------------------------------------------------------------------------
# Skill usage tracking (dynamic skills system)
# ---------------------------------------------------------------------------

def track_skill_usage(skills: list[str]) -> None:
    """Increment skill usage counters for today. 90-day TTL."""
    if not skills:
        return
    day = date.today().isoformat()
    key = f"skill_usage:{day}"
    pipe = _r().pipeline(transaction=False)
    for skill in skills:
        pipe.hincrby(key, skill, 1)
    pipe.expire(key, ANALYTICS_TTL)
    pipe.execute()


def track_skill_miss(tool_name: str) -> None:
    """Increment counter when a tool is not in filtered set (skill detection miss). 90-day TTL."""
    day = date.today().isoformat()
    key = f"skill_misses:{day}"
    _r().hincrby(key, tool_name, 1)
    _r().expire(key, ANALYTICS_TTL)


def get_skill_usage(day: str = None) -> dict[str, int]:
    """Return {skill: count} for a given day (default: today)."""
    if day is None:
        day = date.today().isoformat()
    raw = _r().hgetall(f"skill_usage:{day}")
    return {k.decode(): int(v) for k, v in raw.items()} if raw else {}


def get_skill_misses(day: str = None) -> dict[str, int]:
    """Return {tool_name: miss_count} for a given day (default: today)."""
    if day is None:
        day = date.today().isoformat()
    raw = _r().hgetall(f"skill_misses:{day}")
    return {k.decode(): int(v) for k, v in raw.items()} if raw else {}


# ---------------------------------------------------------------------------
# Funnel tracking (search → detail → shortlist → visit → booking)
# ---------------------------------------------------------------------------

FUNNEL_STAGES = ("search", "detail", "shortlist", "visit", "booking")


def track_funnel(user_id: str, stage: str) -> None:
    """Increment a funnel stage counter. Idempotent per user+stage per day."""
    if stage not in FUNNEL_STAGES:
        return
    day = date.today().isoformat()
    key = f"funnel:{day}"
    _r().hincrby(key, stage, 1)
    _r().expire(key, ANALYTICS_TTL)  # keep 90 days


def get_funnel(day: str = None) -> dict[str, int]:
    """Return funnel counts for a given day (default: today)."""
    if day is None:
        day = date.today().isoformat()
    raw = _r().hgetall(f"funnel:{day}")
    return {k.decode(): int(v) for k, v in raw.items()} if raw else {}


# ---------------------------------------------------------------------------
# WhatsApp message response tracking (dedup)
# ---------------------------------------------------------------------------

def set_response(wama_id: str, message: str) -> None:
    _r().setex(f"wama:{wama_id}", 3 * 24 * 60 * 60, message)


def get_response(wama_id: str) -> Optional[str]:
    raw = _r().get(f"wama:{wama_id}")
    return raw.decode() if raw else None
