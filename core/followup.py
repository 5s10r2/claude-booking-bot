"""
core/followup.py — Multi-step post-visit follow-up state machine.

State machine per user+property:

  VISIT_SCHEDULED
    ──[2h after visit time]──> STEP_1: "How was your visit to {property}?"
        ──[positive reply]──> track visit_attended, suggest booking → END
        ──[negative reply]──> save deal-breaker, suggest alternatives → END
        ──[no reply 24h]──> STEP_2: "Did you get to visit {property}?"
            ──[reply]──> handle same as STEP_1
            ──[no reply 48h]──> STEP_3: "Still looking? Here are similar options"
                ──> END

Storage: {uid}:followup_state — JSON list of active follow-ups, 7-day TTL.
Delivery: WhatsApp (WA users + web users with phone) or in-chat (web-only).
"""

import time
from datetime import datetime

from core.log import get_logger

logger = get_logger("core.followup")

# Step intervals (seconds from when the step message is sent)
STEP_1_DELAY = 0        # Fires at visit_time + 2h (set by schedule_visit)
STEP_2_DELAY = 86400    # 24h after Step 1 was sent
STEP_3_DELAY = 172800   # 48h after Step 1 was sent (24h after Step 2)

# Keyword classification
_POSITIVE_KEYWORDS = {
    "1", "loved", "love", "great", "good", "nice", "amazing", "awesome",
    "book", "reserve", "liked", "perfect", "excellent", "superb", "yes",
    "want to book", "proceed", "lock it", "go ahead",
}
_NEGATIVE_KEYWORDS = {
    "3", "no", "not", "bad", "expensive", "dirty", "far", "didn't",
    "didn't go", "not for me", "too far", "too expensive", "didn't like",
    "skip", "pass", "nah", "nope", "cancel",
}
_NEUTRAL_KEYWORDS = {
    "2", "okay", "ok", "fine", "it was okay", "so-so", "average", "decent",
}


def create_followup_state(
    user_id: str,
    property_id: str,
    property_name: str,
    visit_time_str: str,
    brand_hash: str = "",
) -> None:
    """Create a follow-up state entry when a visit is scheduled.

    Called from tools/booking/schedule_visit.py after successful booking.
    The first step message fires 2h after visit_time (handled by the
    existing sorted-set follow-up system in db/redis/payment.py).
    This function stores the state for multi-step progression.
    """
    from db.redis_store import _json_get, _json_set

    key = f"{user_id}:followup_state"
    states = _json_get(key, default=[])

    # Don't duplicate — check if we already have a followup for this property
    for s in states:
        if s.get("property_id") == property_id and s.get("status") != "completed":
            return  # Already tracking this property

    states.append({
        "property_id": property_id,
        "property_name": property_name,
        "step": 0,  # 0 = scheduled, 1/2/3 = step sent
        "status": "pending",  # pending, awaiting_reply, completed
        "visit_time": visit_time_str,
        "created_at": time.time(),
        "step_1_sent_at": None,
        "step_2_sent_at": None,
        "step_3_sent_at": None,
        "brand_hash": brand_hash,
    })

    _json_set(key, states, ex=604800)  # 7-day TTL


def get_followup_state(user_id: str) -> list[dict]:
    """Get all active follow-up states for a user."""
    from db.redis_store import _json_get
    return _json_get(f"{user_id}:followup_state", default=[])


def _save_followup_state(user_id: str, states: list[dict]) -> None:
    """Persist follow-up states."""
    from db.redis_store import _json_set
    # Remove completed entries older than 24h to keep list clean
    now = time.time()
    active = [
        s for s in states
        if s.get("status") != "completed"
        or (now - s.get("completed_at", now)) < 86400
    ]
    _json_set(f"{user_id}:followup_state", active, ex=604800)


def classify_reply(message: str) -> str:
    """Classify a user reply as positive, negative, neutral, or unclear.

    Returns one of: "positive", "negative", "neutral", "unclear"
    """
    msg_lower = message.strip().lower()

    # Check exact matches first (numbered replies)
    if msg_lower in ("1", "1️⃣"):
        return "positive"
    if msg_lower in ("2", "2️⃣"):
        return "neutral"
    if msg_lower in ("3", "3️⃣"):
        return "negative"

    # Check keyword presence
    for kw in _POSITIVE_KEYWORDS:
        if kw in msg_lower:
            return "positive"
    for kw in _NEGATIVE_KEYWORDS:
        if kw in msg_lower:
            return "negative"
    for kw in _NEUTRAL_KEYWORDS:
        if kw in msg_lower:
            return "neutral"

    return "unclear"


def has_active_followup(user_id: str) -> bool:
    """Check if user has any follow-up awaiting reply."""
    states = get_followup_state(user_id)
    return any(s.get("status") == "awaiting_reply" for s in states)


def handle_followup_reply(user_id: str, message: str) -> str | None:
    """Process a user's reply to a follow-up message.

    Returns a response message if the reply was handled, or None if no
    active follow-up was awaiting a reply.
    """
    from db.redis_store import (
        track_funnel, get_user_brand, update_user_memory,
        add_deal_breaker, get_user_memory,
    )

    states = get_followup_state(user_id)
    awaiting = [s for s in states if s.get("status") == "awaiting_reply"]

    if not awaiting:
        return None

    # Handle the most recent awaiting followup
    followup = awaiting[-1]
    prop_name = followup.get("property_name", "the property")
    prop_id = followup.get("property_id", "")
    brand_hash = followup.get("brand_hash") or get_user_brand(user_id)

    sentiment = classify_reply(message)
    logger.info(
        "followup reply: user=%s prop=%s step=%d sentiment=%s",
        user_id, prop_name, followup.get("step", 0), sentiment,
    )

    # Mark as completed
    followup["status"] = "completed"
    followup["completed_at"] = time.time()
    followup["reply_sentiment"] = sentiment
    _save_followup_state(user_id, states)

    if sentiment == "positive":
        # Track visit_attended funnel event
        track_funnel(user_id, "visit_attended", brand_hash=brand_hash)

        # Update user memory
        mem = get_user_memory(user_id)
        attended = mem.get("visits_attended", [])
        if prop_id and prop_id not in attended:
            attended.append(prop_id)
        update_user_memory(user_id, visits_attended=attended)

        return (
            f"That's wonderful to hear! Glad you liked {prop_name}. 🎉\n\n"
            "Would you like to reserve a bed and lock in your spot? "
            "I can help you with the booking right away!"
        )

    elif sentiment == "negative":
        # Save deal-breaker for future recommendations
        add_deal_breaker(user_id, f"Didn't like {prop_name} after visit")

        return (
            f"Sorry to hear {prop_name} wasn't quite right. "
            "Your feedback helps me find better matches!\n\n"
            "Want me to look for similar properties in the same area? "
            "I'll make sure to factor in what didn't work this time."
        )

    elif sentiment == "neutral":
        return (
            f"Thanks for the feedback on {prop_name}! "
            "If you're on the fence, I can:\n\n"
            "• Show you similar options nearby for comparison\n"
            "• Share more details about this property\n"
            "• Help you schedule another visit\n\n"
            "What would you prefer?"
        )

    else:  # unclear
        return (
            f"Thanks for getting back about {prop_name}! "
            "Just to make sure I understand — how was the visit?\n\n"
            "1️⃣ Loved it — I want to book!\n"
            "2️⃣ It was okay\n"
            "3️⃣ Not for me\n\n"
            "Just reply with 1, 2, or 3!"
        )


def advance_followup(user_id: str, followup: dict) -> str | None:
    """Generate the next follow-up message based on current step.

    Called by the cron handler when a step's wait time has elapsed
    without a reply. Returns the message to send, or None if done.
    """
    step = followup.get("step", 0)
    prop_name = followup.get("property_name", "your shortlisted property")
    now = time.time()

    if step == 0:
        # Step 1: Initial post-visit check-in (2h after visit)
        followup["step"] = 1
        followup["step_1_sent_at"] = now
        followup["status"] = "awaiting_reply"
        return (
            f"Hey! How was your visit to {prop_name}? 🏠\n\n"
            "Quick feedback:\n"
            "1️⃣ Loved it — I want to book!\n"
            "2️⃣ It was okay\n"
            "3️⃣ Not for me\n\n"
            "Just reply with 1, 2, or 3 and I'll take it from there!"
        )

    elif step == 1:
        # Step 2: 24h nudge (no reply to step 1)
        followup["step"] = 2
        followup["step_2_sent_at"] = now
        followup["status"] = "awaiting_reply"
        return (
            f"Hey! Just checking in — did you get to visit {prop_name}? "
            "Would love to know how it went! 🤔\n\n"
            "If you visited, just reply:\n"
            "1️⃣ Loved it\n"
            "2️⃣ It was okay\n"
            "3️⃣ Not for me"
        )

    elif step == 2:
        # Step 3: 48h final nudge — suggest alternatives
        followup["step"] = 3
        followup["step_3_sent_at"] = now
        followup["status"] = "completed"
        followup["completed_at"] = now
        followup["reply_sentiment"] = "no_reply"
        return (
            f"Still looking for the perfect PG? "
            "I have some great options that might interest you!\n\n"
            "Just say 'show me options' and I'll find matches "
            "based on your preferences. 🔍"
        )

    # Beyond step 3 — should not happen
    followup["status"] = "completed"
    followup["completed_at"] = now
    return None


def get_due_state_followups(limit: int = 50) -> list[tuple[str, dict]]:
    """Scan all users with active followup states and return due entries.

    Returns list of (user_id, followup_dict) where the followup is ready
    for the next step based on elapsed time since last step.

    This is called by the cron handler alongside get_due_followups().
    """
    from db.redis_store import _r

    # Scan for users with followup_state keys
    results = []
    cursor = 0
    now = time.time()

    while True:
        cursor, keys = _r().scan(cursor, match="*:followup_state", count=100)
        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else key
            uid = key_str.rsplit(":followup_state", 1)[0]

            states = get_followup_state(uid)
            for s in states:
                if s.get("status") == "completed":
                    continue

                step = s.get("step", 0)

                # Check if enough time has elapsed for next step
                if step == 0 and s.get("status") == "pending":
                    # Step 1 fires via the existing sorted-set system
                    # (schedule_followup in payment.py). When the cron
                    # processes it, it calls advance_followup.
                    continue

                if step == 1 and s.get("status") == "awaiting_reply":
                    sent_at = s.get("step_1_sent_at", 0)
                    if now - sent_at >= STEP_2_DELAY:
                        results.append((uid, s))

                elif step == 2 and s.get("status") == "awaiting_reply":
                    sent_at = s.get("step_2_sent_at", 0)
                    if now - sent_at >= (STEP_3_DELAY - STEP_2_DELAY):
                        results.append((uid, s))

                if len(results) >= limit:
                    return results

        if cursor == 0:
            break

    return results
