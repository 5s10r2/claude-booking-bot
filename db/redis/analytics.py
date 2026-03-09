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
# Per-agent cost tracking (streaming path — fire-and-forget)
# ---------------------------------------------------------------------------

def increment_agent_cost(agent_name: str, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
    """Accumulate per-agent token usage + cost for today. 90-day TTL.

    Writes to hash  agent_cost:{YYYY-MM-DD}
    Fields:         {agent}:tokens_in, {agent}:tokens_out, {agent}:cost_usd
    Read by:        get_agent_costs()  ← used in /admin/command-center
    """
    day = date.today().isoformat()
    key = f"agent_cost:{day}"
    pipe = _r().pipeline(transaction=False)
    pipe.hincrbyfloat(key, f"{agent_name}:tokens_in", tokens_in)
    pipe.hincrbyfloat(key, f"{agent_name}:tokens_out", tokens_out)
    pipe.hincrbyfloat(key, f"{agent_name}:cost_usd", cost_usd)
    pipe.expire(key, ANALYTICS_TTL)
    pipe.execute()


def get_agent_costs(day: str = None) -> dict[str, dict]:
    """Return {agent: {tokens_in, tokens_out, cost_usd}} for a given day (default: today).

    Returns empty dict if no cost data has been tracked yet for that day.
    """
    if day is None:
        day = date.today().isoformat()
    raw = _r().hgetall(f"agent_cost:{day}")
    if not raw:
        return {}
    result: dict[str, dict] = {}
    for k, v in raw.items():
        parts = k.decode().rsplit(":", 1)
        if len(parts) != 2:
            continue
        agent, field = parts
        if agent not in result:
            result[agent] = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        val = float(v)
        if field == "tokens_in":
            result[agent]["tokens_in"] = int(val)
        elif field == "tokens_out":
            result[agent]["tokens_out"] = int(val)
        elif field == "cost_usd":
            result[agent]["cost_usd"] = round(val, 6)
    return result


def increment_daily_cost(cost_usd: float) -> None:
    """Accumulate today's total cost across all agents. 90-day TTL.

    Writes to hash  daily_cost:{YYYY-MM-DD}
    Fields:         cost_usd
    Read by:        get_daily_cost()  ← used in /admin/command-center
    """
    day = date.today().isoformat()
    key = f"daily_cost:{day}"
    _r().hincrbyfloat(key, "cost_usd", cost_usd)
    _r().expire(key, ANALYTICS_TTL)


def get_daily_cost(day: str = None) -> float:
    """Return total cost_usd for a given day (default: today). Returns 0.0 if no data."""
    if day is None:
        day = date.today().isoformat()
    raw = _r().hget(f"daily_cost:{day}", "cost_usd")
    return round(float(raw), 4) if raw else 0.0


# ---------------------------------------------------------------------------
# WhatsApp message response tracking (dedup)
# ---------------------------------------------------------------------------

def set_response(wama_id: str, message: str) -> None:
    _r().setex(f"wama:{wama_id}", 3 * 24 * 60 * 60, message)


def get_response(wama_id: str) -> Optional[str]:
    raw = _r().get(f"wama:{wama_id}")
    return raw.decode() if raw else None
