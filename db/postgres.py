from datetime import datetime
from typing import Optional

import asyncpg

from config import settings
from core.log import get_logger

logger = get_logger("db.postgres")

_pool: Optional[asyncpg.Pool] = None


async def init_pool() -> None:
    global _pool
    try:
        if settings.DATABASE_URL:
            # Render / managed Postgres provides a URL
            _pool = await asyncpg.create_pool(
                dsn=settings.DATABASE_URL,
                min_size=2,
                max_size=10,
            )
        else:
            _pool = await asyncpg.create_pool(
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                database=settings.DB_NAME,
                min_size=2,
                max_size=10,
            )
        logger.info("Connection pool created")
    except Exception as e:
        logger.warning("Could not connect (non-critical, continuing without DB): %s", e)
        _pool = None


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def insert_message(
    thread_id: str,
    user_phone: str,
    message_text: str,
    message_sent_by: int,
    platform_type: str,
    is_template: bool = False,
    pg_ids: Optional[list] = None,
) -> Optional[int]:
    if _pool is None:
        return None
    now = datetime.utcnow()
    try:
        row = await _pool.fetchrow(
            """
            INSERT INTO booking_messages
            (thread_id, user_phone, message_text, message_sent_by,
             created_at, updated_at, platform_type, is_template, pg_ids)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            thread_id,
            user_phone,
            message_text,
            message_sent_by,
            now,
            now,
            platform_type,
            is_template,
            pg_ids,
        )
        return row["id"] if row else None
    except Exception as e:
        logger.error("insert_message error: %s", e)
        return None


async def get_messages(thread_id: str, limit: int = 50) -> list[dict]:
    if _pool is None:
        return []
    try:
        rows = await _pool.fetch(
            """
            SELECT id, thread_id, user_phone, message_text, message_sent_by,
                   platform_type, is_template, created_at
            FROM booking_messages
            WHERE thread_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            thread_id,
            limit,
        )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("get_messages error: %s", e)
        return []
