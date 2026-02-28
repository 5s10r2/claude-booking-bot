import json
import pickle
import hashlib
import os
import re
from typing import Optional

import redis

from config import settings

# Prefer REDIS_URL (Render / managed Redis), fallback to host/port/password
if settings.REDIS_URL:
    _pool = redis.ConnectionPool.from_url(
        settings.REDIS_URL, decode_responses=False
    )
else:
    _pool = redis.ConnectionPool(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD,
        decode_responses=False,
    )


def _r() -> redis.Redis:
    return redis.Redis(connection_pool=_pool)


# ---------------------------------------------------------------------------
# JSON helpers (replacing pickle for security — no RCE vector)
# ---------------------------------------------------------------------------

def _json_set(key: str, value, *, ex: int | None = None) -> None:
    """Serialize value as JSON and store in Redis."""
    data = json.dumps(value, default=str)
    if ex:
        _r().setex(key, ex, data)
    else:
        _r().set(key, data)


def _json_get(key: str, default=None):
    """Read from Redis with backward compat: JSON first, pickle fallback.

    Existing keys written with pickle will still be readable. New writes
    always use JSON, so pickle entries will age out naturally.
    """
    raw = _r().get(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass
    # Backward compat: try pickle for keys written before migration
    try:
        return pickle.loads(raw)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

def get_conversation(user_id: str) -> list[dict]:
    raw = _r().get(f"{user_id}:conversation")
    if raw is None:
        return []
    return json.loads(raw)


def save_conversation(user_id: str, messages: list[dict]) -> None:
    # Allow more messages when a summary is present (summary compresses older context)
    limit = settings.CONVERSATION_HISTORY_LIMIT * 2  # default: 40
    if messages and "[CONVERSATION_SUMMARY]" in str(messages[0].get("content", "")):
        limit = settings.CONVERSATION_HISTORY_LIMIT * 3  # with summary: 60
    trimmed = messages[-limit:]
    _r().setex(
        f"{user_id}:conversation",
        settings.CONVERSATION_TTL_SECONDS,
        json.dumps(trimmed),
    )


def clear_conversation(user_id: str) -> None:
    _r().delete(f"{user_id}:conversation")


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------

def save_preferences(user_id: str, data: dict, profile_name: str | None = None) -> None:
    if profile_name:
        data["profile_name"] = profile_name
    # Ensure bytes values are decoded for JSON compatibility
    clean = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in data.items()}
    _json_set(f"{user_id}:preferences", clean)


def get_preferences(user_id: str) -> dict:
    return _json_get(f"{user_id}:preferences", default={})


# ---------------------------------------------------------------------------
# Property info map (search results cache)
# ---------------------------------------------------------------------------

def set_property_info_map(user_id: str, info_map: list) -> None:
    _json_set(f"{user_id}:property_info_map", info_map, ex=15552000)


def get_property_info_map(user_id: str) -> list:
    return _json_get(f"{user_id}:property_info_map", default=[])


# ---------------------------------------------------------------------------
# Shortlisted properties
# ---------------------------------------------------------------------------

def get_shortlisted_properties(user_id: str) -> list:
    return _json_get(f"{user_id}:shortlisted", default=[])


# ---------------------------------------------------------------------------
# Property template (carousel cards)
# ---------------------------------------------------------------------------

def save_property_template(user_id: str, template: list) -> None:
    _json_set(f"{user_id}:property_template", template)


def get_property_template(user_id: str) -> list:
    return _json_get(f"{user_id}:property_template", default=[])


def clear_property_template(user_id: str) -> None:
    _r().delete(f"{user_id}:property_template")


# ---------------------------------------------------------------------------
# Property images
# ---------------------------------------------------------------------------

def set_property_images_id(user_id: str, images: list) -> None:
    _json_set(f"{user_id}:property_images_id", images)


def get_property_images_id(user_id: str) -> list:
    return _json_get(f"{user_id}:property_images_id", default=[])


def clear_property_images_id(user_id: str) -> None:
    _r().delete(f"{user_id}:property_images_id")


# ---------------------------------------------------------------------------
# Image URLs
# ---------------------------------------------------------------------------

def set_image_urls(user_id: str, urls: list) -> None:
    _json_set(f"{user_id}:image_urls", urls)


def get_image_urls(user_id: str) -> list:
    return _json_get(f"{user_id}:image_urls", default=[])


def clear_image_urls(user_id: str) -> None:
    _r().delete(f"{user_id}:image_urls")


# ---------------------------------------------------------------------------
# Active request dedup (30s TTL)
# ---------------------------------------------------------------------------

def set_active_request(user_id: str, message: str, ttl: int = 30) -> None:
    _r().set(f"{user_id}:active_request", message, ex=ttl)


def get_active_request(user_id: str) -> Optional[str]:
    raw = _r().get(f"{user_id}:active_request")
    return raw.decode() if raw else None


def delete_active_request(user_id: str) -> None:
    _r().delete(f"{user_id}:active_request")


# ---------------------------------------------------------------------------
# Last active agent tracking (10-min TTL for multi-turn continuations)
# ---------------------------------------------------------------------------

def set_last_agent(user_id: str, agent_name: str, ttl: int = 600) -> None:
    _r().set(f"{user_id}:last_agent", agent_name, ex=ttl)


def get_last_agent(user_id: str) -> Optional[str]:
    raw = _r().get(f"{user_id}:last_agent")
    return raw.decode() if raw else None


# ---------------------------------------------------------------------------
# Account values (whitelabel config)
# ---------------------------------------------------------------------------

def set_account_values(user_id: str, values: dict) -> None:
    _json_set(f"{user_id}:account_values", values)


def get_account_values(user_id: str) -> dict:
    return _json_get(f"{user_id}:account_values", default={})


def clear_account_values(user_id: str) -> None:
    _r().delete(f"{user_id}:account_values")


# ---------------------------------------------------------------------------
# Whitelabel PG IDs
# ---------------------------------------------------------------------------

def set_whitelabel_pg_ids(user_id: str, pg_ids: list) -> None:
    _json_set(f"{user_id}:pg_ids", pg_ids)


def get_whitelabel_pg_ids(user_id: str) -> list:
    return _json_get(f"{user_id}:pg_ids", default=[])


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
# KYC data (Aadhaar)
# ---------------------------------------------------------------------------

def set_aadhar_user_name(user_id: str, name: str) -> None:
    _r().set(f"{user_id}:aadhar_name", name)


def get_aadhar_user_name(user_id: str) -> Optional[str]:
    raw = _r().get(f"{user_id}:aadhar_name")
    return raw.decode() if raw else None


def delete_aadhar_user_name(user_id: str) -> None:
    _r().delete(f"{user_id}:aadhar_name")


def set_aadhar_gender(user_id: str, gender: str) -> None:
    _r().set(f"{user_id}:aadhar_gender", gender)


def get_aadhar_gender(user_id: str) -> Optional[str]:
    raw = _r().get(f"{user_id}:aadhar_gender")
    return raw.decode() if raw else None


def delete_aadhar_gender(user_id: str) -> None:
    _r().delete(f"{user_id}:aadhar_gender")


# ---------------------------------------------------------------------------
# User name
# ---------------------------------------------------------------------------

def set_user_name(user_id: str, name: str) -> None:
    _r().set(f"{user_id}:user_name", name)


def get_user_name(user_id: str) -> Optional[str]:
    raw = _r().get(f"{user_id}:user_name")
    return raw.decode() if raw else None


# ---------------------------------------------------------------------------
# User phone number (web-chat users don't have a phone in user_id)
# ---------------------------------------------------------------------------

def set_user_phone(user_id: str, phone: str) -> None:
    """Store the user's real 10-digit phone number (collected from web chat)."""
    _r().set(f"{user_id}:user_phone", phone)


def get_user_phone(user_id: str) -> Optional[str]:
    """
    Returns the user's 10-digit local phone number.

    Priority order:
      1. Explicitly stored phone (set_user_phone — used by web chat).
      2. Derived from user_id when user_id IS a phone number (WhatsApp channel:
         user_id = 12-digit international format like 919876543210).

    Returns None if no valid phone can be determined (e.g. web-chat user who
    hasn't provided their number yet).
    """
    stored = _r().get(f"{user_id}:user_phone")
    if stored:
        return stored.decode()
    # WhatsApp fallback: user_id IS a phone number (pure digits, 10-13 chars)
    # Web-chat IDs like "uat_k7x2m9qf" contain non-digits → skip fallback
    if user_id.isdigit() and 10 <= len(user_id) <= 13:
        return user_id[-10:]
    return None


# ---------------------------------------------------------------------------
# No-message flag
# ---------------------------------------------------------------------------

def set_no_message(user_id: str) -> None:
    _r().set(f"{user_id}:no_message", "1")


def get_no_message(user_id: str) -> str:
    raw = _r().get(f"{user_id}:no_message")
    return raw.decode() if raw else "0"


def clear_no_message(user_id: str) -> None:
    _r().delete(f"{user_id}:no_message")


# ---------------------------------------------------------------------------
# WhatsApp message response tracking
# ---------------------------------------------------------------------------

def set_response(wama_id: str, message: str) -> None:
    _r().setex(f"wama:{wama_id}", 3 * 24 * 60 * 60, message)


def get_response(wama_id: str) -> Optional[str]:
    raw = _r().get(f"wama:{wama_id}")
    return raw.decode() if raw else None


# ---------------------------------------------------------------------------
# Property search tool IDs (temporary, 10min TTL)
# ---------------------------------------------------------------------------

def set_property_id_for_search(user_id: str, property_ids: list) -> None:
    _json_set(f"{user_id}:search_property_ids", property_ids, ex=600)


def get_property_id_for_search(user_id: str) -> list:
    return _json_get(f"{user_id}:search_property_ids", default=[])


def clear_property_id_for_search(user_id: str) -> None:
    _r().delete(f"{user_id}:search_property_ids")


# ---------------------------------------------------------------------------
# FAISS vectorstore (knowledge base)
# ---------------------------------------------------------------------------

def get_file_hash(file_datas: list[bytes]) -> str:
    m = hashlib.sha256()
    for data in file_datas:
        m.update(data)
    return m.hexdigest()


def store_vectorstore_in_redis(file_hash: str, vectorstore) -> None:
    vectorstore.save_local(f"/tmp/faiss_{file_hash}")
    with open(f"/tmp/faiss_{file_hash}/index.faiss", "rb") as f:
        _r().set(f"faiss:{file_hash}:index", f.read())
    with open(f"/tmp/faiss_{file_hash}/index.pkl", "rb") as f:
        _r().set(f"faiss:{file_hash}:pkl", f.read())
    import shutil
    shutil.rmtree(f"/tmp/faiss_{file_hash}", ignore_errors=True)


def load_vectorstore_from_redis(file_hash: str):
    from langchain_openai import OpenAIEmbeddings
    from langchain_community.vectorstores import FAISS

    index_data = _r().get(f"faiss:{file_hash}:index")
    pkl_data = _r().get(f"faiss:{file_hash}:pkl")
    if not index_data or not pkl_data:
        return None
    os.makedirs(f"/tmp/faiss_{file_hash}", exist_ok=True)
    with open(f"/tmp/faiss_{file_hash}/index.faiss", "wb") as f:
        f.write(index_data)
    with open(f"/tmp/faiss_{file_hash}/index.pkl", "wb") as f:
        f.write(pkl_data)
    vectorstore = FAISS.load_local(
        f"/tmp/faiss_{file_hash}",
        OpenAIEmbeddings(),
        allow_dangerous_deserialization=True,
    )
    import shutil
    shutil.rmtree(f"/tmp/faiss_{file_hash}", ignore_errors=True)
    return vectorstore


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
        "ts": __import__("time").time(),
    })
    _r().rpush("feedback:log", entry)
    # Aggregate counters per agent
    _r().hincrby("feedback:counts", f"{agent}:{rating}", 1)
    _r().hincrby("feedback:counts", f"total:{rating}", 1)


def get_feedback_counts() -> dict:
    """Return all feedback counters as a dict."""
    raw = _r().hgetall("feedback:counts")
    return {k.decode(): int(v) for k, v in raw.items()} if raw else {}


# ---------------------------------------------------------------------------
# User language preference
# ---------------------------------------------------------------------------

def set_user_language(user_id: str, lang: str) -> None:
    """Store detected/selected language. TTL = 24h (same as conversation)."""
    _r().set(f"{user_id}:language", lang, ex=86400)


def get_user_language(user_id: str) -> str:
    """Return stored language or 'en' default."""
    raw = _r().get(f"{user_id}:language")
    return raw.decode() if raw else "en"


# ---------------------------------------------------------------------------
# Agent usage tracking (analytics)
# ---------------------------------------------------------------------------

def track_agent_usage(user_id: str, agent_name: str) -> None:
    """Increment agent usage counter for today. 90-day TTL."""
    from datetime import date
    day = date.today().isoformat()
    key = f"agent_usage:{day}"
    _r().hincrby(key, agent_name, 1)
    _r().expire(key, 90 * 86400)


def get_agent_usage(day: str = None) -> dict:
    """Return {agent: count} for a given day (default: today)."""
    if day is None:
        from datetime import date
        day = date.today().isoformat()
    raw = _r().hgetall(f"agent_usage:{day}")
    return {k.decode(): int(v) for k, v in raw.items()} if raw else {}


# ---------------------------------------------------------------------------
# Funnel tracking (search → detail → shortlist → visit → booking)
# ---------------------------------------------------------------------------

FUNNEL_STAGES = ("search", "detail", "shortlist", "visit", "booking")


def track_funnel(user_id: str, stage: str) -> None:
    """Increment a funnel stage counter. Idempotent per user+stage per day."""
    if stage not in FUNNEL_STAGES:
        return
    from datetime import date
    day = date.today().isoformat()
    key = f"funnel:{day}"
    _r().hincrby(key, stage, 1)
    _r().expire(key, 90 * 86400)  # keep 90 days


def get_funnel(day: str = None) -> dict:
    """Return funnel counts for a given day (default: today)."""
    if day is None:
        from datetime import date
        day = date.today().isoformat()
    raw = _r().hgetall(f"funnel:{day}")
    return {k.decode(): int(v) for k, v in raw.items()} if raw else {}


# ---------------------------------------------------------------------------
# Cross-session user memory (persistent — no TTL)
# ---------------------------------------------------------------------------

_MEMORY_DEFAULTS = {
    "first_seen": "",
    "last_seen": "",
    "session_count": 0,
    "properties_viewed": [],       # list of prop_ids
    "properties_shortlisted": [],  # list of prop_ids
    "properties_rejected": [],     # list of {"prop_id": ..., "traits": [...]}
    "visits_scheduled": [],        # list of prop_ids
    "deal_breakers": [],           # inferred: ["no AC", "far from metro"]
    "must_haves": [],              # inferred: ["AC", "WiFi"]
    "lead_score": 0,
    "last_search_location": "",
    "last_search_budget": "",
    "phone_collected": False,
    "funnel_max": "",              # highest funnel stage reached
    "persona": "",                 # "professional", "student", "family", or ""
}

# ---------------------------------------------------------------------------
# Persona detection keywords
# ---------------------------------------------------------------------------
_PERSONA_SIGNALS = {
    "professional": [
        "office", "work", "workplace", "company", "commute", "job",
        "corporate", "business park", "tech park", "it park", "bkc",
        "salary", "professional",
    ],
    "student": [
        "college", "university", "campus", "studies", "student",
        "hostel", "studying", "course", "engineering", "medical",
        "iit", "nit", "bits", "vit", "manipal", "amity",
    ],
    "family": [
        "family", "kids", "children", "school", "wife", "husband",
        "spouse", "parents", "daughter", "son", "married",
    ],
}


def detect_persona(text: str) -> str:
    """Detect user persona from conversation text. Returns persona string or empty."""
    lower = text.lower()
    scores = {"professional": 0, "student": 0, "family": 0}
    for persona, keywords in _PERSONA_SIGNALS.items():
        for kw in keywords:
            if kw in lower:
                scores[persona] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] >= 1 else ""


def update_persona(user_id: str, text: str) -> str:
    """Detect persona from text and persist if found (doesn't downgrade existing)."""
    detected = detect_persona(text)
    if not detected:
        return ""
    mem = get_user_memory(user_id)
    current = mem.get("persona", "")
    if not current:
        update_user_memory(user_id, persona=detected)
    return detected or current

FUNNEL_ORDER = ("search", "detail", "shortlist", "visit", "booking")


def get_user_memory(user_id: str) -> dict:
    """Return persistent cross-session memory for a user."""
    data = _json_get(f"{user_id}:user_memory")
    if data is None:
        return dict(_MEMORY_DEFAULTS)
    # Ensure all keys exist (forward compat if we add new fields)
    merged = dict(_MEMORY_DEFAULTS)
    merged.update(data)
    return merged


def save_user_memory(user_id: str, memory: dict) -> None:
    """Persist user memory (no TTL — survives across sessions)."""
    _json_set(f"{user_id}:user_memory", memory)


def update_user_memory(user_id: str, **updates) -> dict:
    """Merge updates into existing memory, recalculate lead score, and save.

    Convenience wrapper: ``update_user_memory(uid, session_count=mem["session_count"]+1)``
    """
    mem = get_user_memory(user_id)
    mem.update(updates)

    # Always refresh last_seen
    from datetime import date
    mem["last_seen"] = date.today().isoformat()
    if not mem["first_seen"]:
        mem["first_seen"] = mem["last_seen"]

    # Recalculate lead score
    mem["lead_score"] = _calculate_lead_score(mem)

    # Update funnel_max
    for stage in reversed(FUNNEL_ORDER):
        if stage == "visit" and mem.get("visits_scheduled"):
            mem["funnel_max"] = _max_funnel(mem.get("funnel_max", ""), "visit")
        elif stage == "shortlist" and mem.get("properties_shortlisted"):
            mem["funnel_max"] = _max_funnel(mem.get("funnel_max", ""), "shortlist")
        elif stage == "search" and mem.get("properties_viewed"):
            mem["funnel_max"] = _max_funnel(mem.get("funnel_max", ""), "search")

    save_user_memory(user_id, mem)
    return mem


def _max_funnel(current: str, new: str) -> str:
    """Return the deeper funnel stage."""
    cur_idx = FUNNEL_ORDER.index(current) if current in FUNNEL_ORDER else -1
    new_idx = FUNNEL_ORDER.index(new) if new in FUNNEL_ORDER else -1
    return FUNNEL_ORDER[max(cur_idx, new_idx)] if max(cur_idx, new_idx) >= 0 else current


def _calculate_lead_score(mem: dict) -> int:
    """Score 0-100 based on engagement signals. Higher = hotter lead."""
    score = 0

    # Session engagement (max 20)
    score += min(20, mem.get("session_count", 0) * 5)

    # Properties explored (max 15)
    score += min(15, len(mem.get("properties_viewed", [])) * 2)

    # Shortlisted (max 15)
    score += min(15, len(mem.get("properties_shortlisted", [])) * 5)

    # Visits scheduled (max 20)
    score += min(20, len(mem.get("visits_scheduled", [])) * 10)

    # Phone collected (10)
    if mem.get("phone_collected"):
        score += 10

    # Preferences completeness (max 10)
    loc = mem.get("last_search_location", "")
    budget = mem.get("last_search_budget", "")
    if loc:
        score += 5
    if budget:
        score += 5

    # Recency decay: -5 per week of inactivity (max -20)
    last_seen = mem.get("last_seen", "")
    if last_seen:
        from datetime import date
        try:
            days_inactive = (date.today() - date.fromisoformat(last_seen)).days
            weeks_inactive = days_inactive // 7
            score -= min(20, weeks_inactive * 5)
        except (ValueError, TypeError):
            pass

    return max(0, min(100, score))


def get_lead_temperature(score: int) -> str:
    """Classify lead score into temperature."""
    if score >= 70:
        return "hot"
    if score >= 40:
        return "warm"
    return "cold"


def record_property_viewed(user_id: str, prop_id: str) -> None:
    """Record that user viewed/was shown a property."""
    if not prop_id:
        return
    mem = get_user_memory(user_id)
    viewed = mem.get("properties_viewed", [])
    if prop_id not in viewed:
        viewed.append(prop_id)
        mem["properties_viewed"] = viewed[-50:]  # cap at 50
    update_user_memory(user_id, properties_viewed=mem["properties_viewed"])


def record_property_shortlisted(user_id: str, prop_id: str) -> None:
    """Record that user shortlisted a property."""
    if not prop_id:
        return
    mem = get_user_memory(user_id)
    shortlisted = mem.get("properties_shortlisted", [])
    if prop_id not in shortlisted:
        shortlisted.append(prop_id)
        mem["properties_shortlisted"] = shortlisted[-20:]
    update_user_memory(user_id, properties_shortlisted=mem["properties_shortlisted"])


def record_visit_scheduled(user_id: str, prop_id: str) -> None:
    """Record that user scheduled a visit."""
    if not prop_id:
        return
    mem = get_user_memory(user_id)
    visits = mem.get("visits_scheduled", [])
    if prop_id not in visits:
        visits.append(prop_id)
        mem["visits_scheduled"] = visits[-20:]
    update_user_memory(user_id, visits_scheduled=mem["visits_scheduled"])


def add_deal_breaker(user_id: str, deal_breaker: str) -> None:
    """Add an inferred deal-breaker (e.g., 'no AC')."""
    if not deal_breaker:
        return
    mem = get_user_memory(user_id)
    dbs = mem.get("deal_breakers", [])
    if deal_breaker.lower() not in [d.lower() for d in dbs]:
        dbs.append(deal_breaker)
        mem["deal_breakers"] = dbs[-10:]  # cap at 10
    save_user_memory(user_id, mem)


def build_returning_user_context(user_id: str) -> str:
    """Build a prompt-injectable summary of the returning user's history.

    Returns empty string for new users (no memory).
    """
    mem = get_user_memory(user_id)
    if not mem.get("first_seen") or mem.get("session_count", 0) < 1:
        return ""

    parts = []
    parts.append(f"RETURNING USER (session #{mem['session_count'] + 1}):")

    loc = mem.get("last_search_location", "")
    budget = mem.get("last_search_budget", "")
    if loc:
        search_info = f"Last searched: {loc}"
        if budget:
            search_info += f", budget {budget}"
        parts.append(search_info)

    n_viewed = len(mem.get("properties_viewed", []))
    n_short = len(mem.get("properties_shortlisted", []))
    n_visits = len(mem.get("visits_scheduled", []))
    if n_viewed or n_short or n_visits:
        engagement = []
        if n_viewed:
            engagement.append(f"{n_viewed} viewed")
        if n_short:
            engagement.append(f"{n_short} shortlisted")
        if n_visits:
            engagement.append(f"{n_visits} visits scheduled")
        parts.append("Properties: " + ", ".join(engagement))

    persona = mem.get("persona", "")
    if persona:
        parts.append(f"Persona: {persona}")

    dbs = mem.get("deal_breakers", [])
    if dbs:
        parts.append(f"Deal-breakers: {', '.join(dbs)}")

    must = mem.get("must_haves", [])
    if must:
        parts.append(f"Must-haves: {', '.join(must)}")

    score = mem.get("lead_score", 0)
    temp = get_lead_temperature(score)
    parts.append(f"Lead: {temp} ({score}/100)")

    if temp == "hot":
        parts.append("→ Use urgency and push for booking/visit NOW")
    elif temp == "warm":
        parts.append("→ Engage warmly, highlight new options, nudge toward action")
    else:
        parts.append("→ Be educational, build trust, don't push too hard")

    if loc and budget:
        parts.append("→ Skip qualifying questions — go straight to search or pick up where they left off")

    return "\n".join(parts)


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
    import time as _time
    trigger_at = _time.time() + delay_seconds
    member = json.dumps({
        "user_id": user_id,
        "type": followup_type,
        "data": data,
        "scheduled_at": _time.time(),
    }, default=str)
    _r().zadd(FOLLOWUP_KEY, {member: trigger_at})


def get_due_followups(limit: int = 50) -> list[dict]:
    """Return follow-ups whose trigger time has passed (ready to send)."""
    import time as _time
    now = _time.time()
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
            pass
    return removed
