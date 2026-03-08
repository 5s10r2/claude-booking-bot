"""
db/redis/conversation.py — Conversation history, session routing, and account context.

Covers:
  - Conversation history (get/save/clear)
  - Active request dedup
  - Last agent tracking
  - Account values + whitelabel PG IDs
"""

import time
from typing import Optional

import json

from config import settings
from db.redis._base import _r, _json_set, _json_get


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
    # Track user in active_users sorted set (score = unix timestamp for recency ordering)
    _r().zadd("active_users", {user_id: time.time()})


def clear_conversation(user_id: str) -> None:
    _r().delete(f"{user_id}:conversation")


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


def get_whitelabel_pg_ids(user_id: str) -> list[str]:
    return _json_get(f"{user_id}:pg_ids", default=[])
