"""
db/redis/_base.py — Shared infrastructure for all Redis domain modules.

Contains the connection pool, JSON helpers, and TTL constants.
Imported by every domain module in this package.
"""

import json
import pickle
import time
from typing import Optional

import redis

from config import settings
from core.log import get_logger

logger = get_logger("db.redis")

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
PROPERTY_INFO_TTL = 15552000    # 6 months
SEARCH_IDS_TTL = 600            # 10 minutes
LANGUAGE_TTL = 86400            # 24 hours
ANALYTICS_TTL = 90 * 86400     # 90 days
LAST_SEARCH_TTL = 86400         # 24 hours

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
        pass  # Not JSON — fall through to pickle backward-compat path below
    # Backward compat: try pickle for keys written before migration
    try:
        return pickle.loads(raw)
    except Exception as e:
        logger.debug("_json_get pickle fallback failed: %s", e)
        return default
