import json
import pickle
import hashlib
import os
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
    trimmed = messages[-settings.CONVERSATION_HISTORY_LIMIT * 2 :]
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
