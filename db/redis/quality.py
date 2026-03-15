"""
db/redis/quality.py — Conversation quality scoring (0-100).

Computed after each pipeline response (alongside attention flags).
Lightweight — reads only from data already loaded by the caller.

Scoring signals:
| Signal                                     | Points |
|--------------------------------------------|--------|
| Reached CTA (visit/booking/shortlist)      | +30    |
| All tool calls succeeded (no failures)     | +20    |
| User engaged (3+ messages)                 | +15    |
| No routing overrides in session            | +10    |
| Average latency < 5s                       | +10    |
| Positive feedback given                    | +15    |
| Negative feedback penalty                  | -20    |

Storage: {uid}:conversation_quality — JSON, 90-day TTL.
"""

import json
import time

from db.redis._base import _r, ANALYTICS_TTL

# Funnel stages that count as "reached CTA"
_CTA_STAGES = {"shortlist", "visit", "booking", "visit_attended", "booking_initiated", "payment_completed"}


def compute_conversation_quality(
    uid: str,
    messages: list[dict],
    user_memory: dict,
) -> dict:
    """Compute a 0-100 quality score with signal breakdown.

    Returns: {score: int, signals: {signal_name: bool, ...}, computed_at: float}
    """
    score = 0
    signals: dict[str, bool] = {}

    # 1. Reached CTA (+30)
    funnel_max = user_memory.get("funnel_max", "")
    cta_reached = funnel_max in _CTA_STAGES
    signals["cta_reached"] = cta_reached
    if cta_reached:
        score += 30

    # 2. No tool failures in last 10 messages (+20)
    error_markers = ("error", "failed", "exception", "timeout", "could not")
    tool_errors_found = False
    recent = messages[-10:] if len(messages) >= 10 else messages
    for msg in recent:
        content = msg.get("content", "")
        role = msg.get("role", "")
        if role in ("assistant", "tool") and isinstance(content, str):
            if any(marker in content.lower() for marker in error_markers):
                tool_errors_found = True
                break
    signals["no_tool_errors"] = not tool_errors_found
    if not tool_errors_found:
        score += 20

    # 3. User engaged — 3+ user messages (+15)
    user_msg_count = sum(1 for m in messages if m.get("role") == "user")
    engaged = user_msg_count >= 3
    signals["user_engaged"] = engaged
    if engaged:
        score += 15

    # 4. No routing overrides (+10)
    # Check today's routing overrides for this user (lightweight — just check count)
    no_overrides = True
    try:
        from datetime import date
        from db.redis.analytics import get_routing_overrides
        overrides = get_routing_overrides(date.today().isoformat())
        # If there are overrides at all today, we can't attribute to specific user,
        # so just check if override count is low relative to total traffic
        override_total = overrides.get("_total", 0)
        no_overrides = override_total == 0
    except Exception:
        pass
    signals["no_routing_overrides"] = no_overrides
    if no_overrides:
        score += 10

    # 5. Average latency < 5s (+10)
    fast_latency = True
    try:
        from datetime import date
        from db.redis.analytics import get_response_latency
        latency = get_response_latency(date.today().isoformat())
        if latency:
            total_ms = sum(a.get("avg_ms", 0) * a.get("count", 1) for a in latency.values())
            total_n = sum(a.get("count", 0) for a in latency.values())
            if total_n > 0:
                avg_ms = total_ms / total_n
                fast_latency = avg_ms < 5000
    except Exception:
        pass
    signals["fast_latency"] = fast_latency
    if fast_latency:
        score += 10

    # 6. Feedback (+15 positive / -20 negative)
    feedback_positive = False
    feedback_negative = False
    try:
        raw_list = _r().lrange("feedback:log", -50, -1)
        for entry in reversed(raw_list or []):
            try:
                fb = json.loads(entry)
                if fb.get("user_id") == uid:
                    if fb.get("rating") == "up":
                        feedback_positive = True
                    elif fb.get("rating") == "down":
                        feedback_negative = True
                    break  # Only check most recent for this user
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception:
        pass

    signals["positive_feedback"] = feedback_positive
    signals["negative_feedback"] = feedback_negative
    if feedback_positive:
        score += 15
    if feedback_negative:
        score -= 20

    # Clamp to 0-100
    score = max(0, min(100, score))

    return {
        "score": score,
        "signals": signals,
        "computed_at": time.time(),
    }


def save_conversation_quality(uid: str, data: dict) -> None:
    """Cache quality score with 90-day TTL."""
    _r().setex(f"{uid}:conversation_quality", ANALYTICS_TTL, json.dumps(data))


def get_conversation_quality(uid: str) -> dict:
    """Return cached quality data, or empty dict if expired/missing."""
    raw = _r().get(f"{uid}:conversation_quality")
    if raw is None:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def update_conversation_quality(
    uid: str,
    messages: list[dict],
    user_memory: dict,
) -> dict:
    """Compute + save quality in one call. Returns the quality data."""
    data = compute_conversation_quality(uid, messages, user_memory)
    save_conversation_quality(uid, data)
    return data
