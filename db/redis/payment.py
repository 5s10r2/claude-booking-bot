"""
db/redis/payment.py — Payment info and proactive follow-up scheduling.

Covers:
  - Payment info (pending link, amount, pg details)
  - Follow-up system (sorted set based, trigger-time scheduling)
"""

import json
import time
from typing import Optional

from db.redis._base import _r, _json_set, _json_get


# ---------------------------------------------------------------------------
# Payment info
# ---------------------------------------------------------------------------

def set_payment_info(
    user_id: str,
    pg_name: str,
    pg_id: str,
    pg_number: str,
    amount: str,
    short_link: str,
) -> None:
    _json_set(f"{user_id}:payment_info", {
        "pg_name": pg_name,
        "pg_id": pg_id,
        "pg_number": pg_number,
        "amount": amount,
        "short_link": short_link,
    })


def get_payment_info(user_id: str) -> Optional[dict]:
    return _json_get(f"{user_id}:payment_info", default=None)


def clear_payment_info(user_id: str) -> None:
    _r().delete(f"{user_id}:payment_info")


# ---------------------------------------------------------------------------
# Proactive follow-up system (sorted set based)
# ---------------------------------------------------------------------------

FOLLOWUP_KEY = "followups"


def schedule_followup(
    user_id: str,
    followup_type: str,
    data: dict,
    delay_seconds: int,
) -> None:
    """Schedule a follow-up message to be sent after a delay.

    Args:
        user_id: The user to follow up with.
        followup_type: One of "visit_complete", "payment_pending", "shortlist_idle".
        data: Context dict (property_name, property_id, etc.).
        delay_seconds: Seconds from now to trigger.
    """
    trigger_at = time.time() + delay_seconds
    member = json.dumps({
        "user_id": user_id,
        "type": followup_type,
        "data": data,
        "scheduled_at": time.time(),
    }, default=str)
    _r().zadd(FOLLOWUP_KEY, {member: trigger_at})


def get_due_followups(limit: int = 50) -> list[dict]:
    """Return follow-ups whose trigger time has passed (ready to send)."""
    now = time.time()
    raw_members = _r().zrangebyscore(FOLLOWUP_KEY, "-inf", now, start=0, num=limit)
    results = []
    for raw in raw_members:
        try:
            entry = json.loads(raw if isinstance(raw, str) else raw.decode())
            entry["_raw"] = raw  # keep original for removal
            results.append(entry)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Corrupt entry — remove it
            _r().zrem(FOLLOWUP_KEY, raw)
    return results


def complete_followup(raw_member) -> None:
    """Remove a processed follow-up from the sorted set."""
    _r().zrem(FOLLOWUP_KEY, raw_member)


def cancel_followups(user_id: str, followup_type: str = "") -> int:
    """Cancel pending follow-ups for a user (optionally filtered by type).

    Returns number of cancelled follow-ups.
    """
    # Scan all members and remove matching ones
    all_members = _r().zrange(FOLLOWUP_KEY, 0, -1)
    removed = 0
    for raw in all_members:
        try:
            entry = json.loads(raw if isinstance(raw, str) else raw.decode())
            if entry.get("user_id") == user_id:
                if not followup_type or entry.get("type") == followup_type:
                    _r().zrem(FOLLOWUP_KEY, raw)
                    removed += 1
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass  # Corrupt followup entry in sorted set — skip it, don't abort cleanup
    return removed
