"""
db/redis/admin.py — Admin portal state: user enumeration, human mode, session cost.

Covers:
  - Active users sorted set (get/count)
  - Human mode takeover (get/set/clear)
  - Session cost tracking (per-user, 7-day TTL)
"""

import time

from db.redis._base import _r


# ---------------------------------------------------------------------------
# Admin portal — user enumeration
# ---------------------------------------------------------------------------

def get_active_users(offset: int = 0, limit: int = 50) -> list[str]:
    """Return user IDs sorted by most recent activity (newest first).

    Uses the active_users sorted set populated by save_conversation().
    """
    raw = _r().zrevrange("active_users", offset, offset + limit - 1)
    return [uid.decode() if isinstance(uid, bytes) else uid for uid in raw]


def get_active_users_count() -> int:
    """Return total number of tracked users."""
    return _r().zcard("active_users") or 0


# ---------------------------------------------------------------------------
# Human mode (admin takeover)
# ---------------------------------------------------------------------------

def get_human_mode(uid: str) -> bool:
    """Return True if admin has taken over this conversation."""
    val = _r().hget(f"{uid}:human_mode", "active")
    return val == b"1" or val == "1"


def set_human_mode(uid: str) -> None:
    """Activate human takeover for uid. Admin messages are sent manually."""
    _r().hset(f"{uid}:human_mode", mapping={"active": "1", "taken_at": str(time.time())})


def clear_human_mode(uid: str) -> None:
    """Deactivate human takeover — AI resumes handling the conversation."""
    _r().delete(f"{uid}:human_mode")


# ---------------------------------------------------------------------------
# Session cost tracking (per-user, 7-day TTL)
# ---------------------------------------------------------------------------

def increment_session_cost(uid: str, tokens_in: int, tokens_out: int, model: str) -> None:
    """Accumulate token usage and USD cost for a user's session (7-day TTL)."""
    from config import settings
    rates = getattr(settings, "COST_PER_MTK", {}).get(model, {"in": 0.0, "out": 0.0})
    cost_usd = (tokens_in * rates["in"] + tokens_out * rates["out"]) / 1_000_000

    key = f"{uid}:session_cost"
    pipe = _r().pipeline()
    pipe.hincrbyfloat(key, "tokens_in", tokens_in)
    pipe.hincrbyfloat(key, "tokens_out", tokens_out)
    pipe.hincrbyfloat(key, "cost_usd", cost_usd)
    pipe.expire(key, 7 * 86400)
    pipe.execute()


def get_session_cost(uid: str) -> dict:
    """Return accumulated cost stats for a user. Returns zeros if no data."""
    raw = _r().hgetall(f"{uid}:session_cost")
    if not raw:
        return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
    return {
        "tokens_in": int(float(raw.get(b"tokens_in", 0))),
        "tokens_out": int(float(raw.get(b"tokens_out", 0))),
        "cost_usd": round(float(raw.get(b"cost_usd", 0.0)), 6),
    }
