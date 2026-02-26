"""
Sliding-window rate limiter backed by Redis sorted sets.

Three tiers (all configurable via env / config.py):
  1. Per-user per-minute  — stops rapid-fire abuse (default: 6 req/min)
  2. Per-user per-hour    — stops sustained abuse  (default: 30 req/hr)
  3. Global  per-minute   — protects total API budget (default: 100 req/min)

Algorithm:
  Each request adds a timestamped member to a Redis sorted set.
  Expired members are pruned atomically with ZREMRANGEBYSCORE.
  ZCARD gives the current count within the window.

Usage in FastAPI:
    from core.rate_limiter import check_rate_limit, RateLimitExceeded

    @app.post("/chat")
    async def chat(req: ChatRequest):
        check_rate_limit(req.user_id)   # raises RateLimitExceeded → 429
        ...
"""

import os
import time
from typing import Optional

import redis

from config import settings
from core.log import get_logger

logger = get_logger("rate_limiter")


# ── Redis connection (reuse the pool from redis_store) ──────────────────────

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


# ── Exception ───────────────────────────────────────────────────────────────

class RateLimitExceeded(Exception):
    """Raised when a user has exceeded one of the rate-limit tiers."""

    def __init__(self, retry_after: int, tier: str, limit: int):
        self.retry_after = retry_after
        self.tier = tier
        self.limit = limit
        super().__init__(
            f"Rate limit exceeded ({tier}: {limit}). "
            f"Retry after {retry_after}s."
        )


# ── Sliding-window helper ──────────────────────────────────────────────────

def _sliding_window_check(
    key: str,
    window_seconds: int,
    max_requests: int,
) -> Optional[int]:
    """Check a single sliding-window counter.

    Returns None if under limit, or seconds-until-retry if over.
    """
    now = time.time()
    window_start = now - window_seconds
    # Unique member name — random suffix prevents collisions when
    # concurrent requests arrive at the same timestamp.
    member = f"{now}:{os.urandom(4).hex()}"

    pipe = _r().pipeline(transaction=True)
    pipe.zremrangebyscore(key, "-inf", window_start)     # prune expired
    pipe.zadd(key, {member: now})                         # record this hit
    pipe.zcard(key)                                       # count in window
    pipe.expire(key, window_seconds + 10)                 # auto-cleanup
    results = pipe.execute()
    count = results[2]

    if count > max_requests:
        # Reject: remove the optimistic add we just did
        _r().zrem(key, member)
        # Calculate retry_after: oldest entry in window determines when
        # one slot frees up.
        oldest = _r().zrange(key, 0, 0, withscores=True)
        if oldest:
            oldest_ts = oldest[0][1]
            retry_after = max(1, int(oldest_ts + window_seconds - now) + 1)
        else:
            retry_after = 1
        return retry_after

    return None  # under limit


# ── Public API ──────────────────────────────────────────────────────────────

def check_rate_limit(user_id: str) -> None:
    """Check all rate-limit tiers for a user. Raises RateLimitExceeded on 429.

    Called at the top of /chat, /chat/stream, and /webhook/whatsapp
    *before* any expensive Claude API call is made.
    """
    # ── Tier 1: per-user per-minute ──
    retry = _sliding_window_check(
        key=f"rl:{user_id}:min",
        window_seconds=60,
        max_requests=settings.RATE_LIMIT_USER_PER_MINUTE,
    )
    if retry is not None:
        logger.warning(
            "Rate limit hit: user=%s tier=user/min limit=%d",
            user_id, settings.RATE_LIMIT_USER_PER_MINUTE,
        )
        raise RateLimitExceeded(
            retry_after=retry,
            tier="user/min",
            limit=settings.RATE_LIMIT_USER_PER_MINUTE,
        )

    # ── Tier 2: per-user per-hour ──
    retry = _sliding_window_check(
        key=f"rl:{user_id}:hr",
        window_seconds=3600,
        max_requests=settings.RATE_LIMIT_USER_PER_HOUR,
    )
    if retry is not None:
        logger.warning(
            "Rate limit hit: user=%s tier=user/hr limit=%d",
            user_id, settings.RATE_LIMIT_USER_PER_HOUR,
        )
        raise RateLimitExceeded(
            retry_after=retry,
            tier="user/hr",
            limit=settings.RATE_LIMIT_USER_PER_HOUR,
        )

    # ── Tier 3: global per-minute ──
    retry = _sliding_window_check(
        key="rl:__global__:min",
        window_seconds=60,
        max_requests=settings.RATE_LIMIT_GLOBAL_PER_MINUTE,
    )
    if retry is not None:
        logger.warning(
            "Rate limit hit: user=%s tier=global/min limit=%d",
            user_id, settings.RATE_LIMIT_GLOBAL_PER_MINUTE,
        )
        raise RateLimitExceeded(
            retry_after=retry,
            tier="global/min",
            limit=settings.RATE_LIMIT_GLOBAL_PER_MINUTE,
        )


def get_rate_limit_status(user_id: str) -> dict:
    """Return current usage counts for monitoring / admin dashboards."""
    now = time.time()
    r = _r()

    def _count(key: str, window: int) -> int:
        r.zremrangebyscore(key, "-inf", now - window)
        return r.zcard(key) or 0

    return {
        "user_per_minute": {
            "used": _count(f"rl:{user_id}:min", 60),
            "limit": settings.RATE_LIMIT_USER_PER_MINUTE,
        },
        "user_per_hour": {
            "used": _count(f"rl:{user_id}:hr", 3600),
            "limit": settings.RATE_LIMIT_USER_PER_HOUR,
        },
        "global_per_minute": {
            "used": _count("rl:__global__:min", 60),
            "limit": settings.RATE_LIMIT_GLOBAL_PER_MINUTE,
        },
    }
