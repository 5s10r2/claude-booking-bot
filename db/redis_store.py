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
    serializable = {
        k: (v.decode() if isinstance(v, bytes) else v) for k, v in data.items()
    }
    _r().set(f"{user_id}:preferences", pickle.dumps(data))
    _r().setex(f"{user_id}:preferences:json", 7776000, json.dumps(serializable))


def get_preferences(user_id: str) -> dict:
    raw = _r().get(f"{user_id}:preferences")
    if raw is None:
        return {}
    try:
        return pickle.loads(raw)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Property info map (search results cache)
# ---------------------------------------------------------------------------

def set_property_info_map(user_id: str, info_map: list) -> None:
    _r().setex(f"{user_id}:property_info_map", 15552000, pickle.dumps(info_map))


def get_property_info_map(user_id: str) -> list:
    raw = _r().get(f"{user_id}:property_info_map")
    if raw is None:
        return []
    try:
        return pickle.loads(raw)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Shortlisted properties
# ---------------------------------------------------------------------------

def get_shortlisted_properties(user_id: str) -> list:
    raw = _r().get(f"{user_id}:shortlisted")
    if raw is None:
        return []
    try:
        return pickle.loads(raw)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Property template (carousel cards)
# ---------------------------------------------------------------------------

def save_property_template(user_id: str, template: list) -> None:
    _r().set(f"{user_id}:property_template", pickle.dumps(template))


def get_property_template(user_id: str) -> list:
    raw = _r().get(f"{user_id}:property_template")
    return pickle.loads(raw) if raw else []


def clear_property_template(user_id: str) -> None:
    _r().delete(f"{user_id}:property_template")


# ---------------------------------------------------------------------------
# Property images
# ---------------------------------------------------------------------------

def set_property_images_id(user_id: str, images: list) -> None:
    _r().set(f"{user_id}:property_images_id", pickle.dumps(images))


def get_property_images_id(user_id: str) -> list:
    raw = _r().get(f"{user_id}:property_images_id")
    return pickle.loads(raw) if raw else []


def clear_property_images_id(user_id: str) -> None:
    _r().delete(f"{user_id}:property_images_id")


# ---------------------------------------------------------------------------
# Image URLs
# ---------------------------------------------------------------------------

def set_image_urls(user_id: str, urls: list) -> None:
    _r().set(f"{user_id}:image_urls", pickle.dumps(urls))


def get_image_urls(user_id: str) -> list:
    raw = _r().get(f"{user_id}:image_urls")
    return pickle.loads(raw) if raw else []


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
    _r().set(f"{user_id}:account_values", pickle.dumps(values))


def get_account_values(user_id: str) -> dict:
    raw = _r().get(f"{user_id}:account_values")
    return pickle.loads(raw) if raw else {}


def clear_account_values(user_id: str) -> None:
    _r().delete(f"{user_id}:account_values")


# ---------------------------------------------------------------------------
# Whitelabel PG IDs
# ---------------------------------------------------------------------------

def set_whitelabel_pg_ids(user_id: str, pg_ids: list) -> None:
    _r().set(f"{user_id}:pg_ids", pickle.dumps(pg_ids))


def get_whitelabel_pg_ids(user_id: str) -> list:
    raw = _r().get(f"{user_id}:pg_ids")
    return pickle.loads(raw) if raw else []


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
    _r().set(
        f"{user_id}:payment_info",
        pickle.dumps({
            "pg_name": pg_name,
            "pg_id": pg_id,
            "pg_number": pg_number,
            "amount": amount,
            "short_link": short_link,
        }),
    )


def get_payment_info(user_id: str) -> Optional[dict]:
    raw = _r().get(f"{user_id}:payment_info")
    return pickle.loads(raw) if raw else None


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
    _r().setex(f"{user_id}:search_property_ids", 600, pickle.dumps(property_ids))


def get_property_id_for_search(user_id: str) -> list:
    raw = _r().get(f"{user_id}:search_property_ids")
    return pickle.loads(raw) if raw else []


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
