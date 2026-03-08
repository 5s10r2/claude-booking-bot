import json
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
            json.dumps(pg_ids) if pg_ids else None,
        )
        return row["id"] if row else None
    except Exception as e:
        logger.error("insert_message error: %s", e)
        return None


async def get_message_volume(start_date: str, end_date: str) -> dict:
    """Return daily message counts: {"2026-02-20": 42, ...}."""
    if _pool is None:
        return {}
    try:
        rows = await _pool.fetch(
            """
            SELECT DATE(created_at) AS day, COUNT(*) AS cnt
            FROM booking_messages
            WHERE created_at >= $1::date
              AND created_at < ($2::date + INTERVAL '1 day')
            GROUP BY DATE(created_at)
            ORDER BY day
            """,
            start_date,
            end_date,
        )
        return {str(r["day"]): r["cnt"] for r in rows}
    except Exception as e:
        logger.error("get_message_volume error: %s", e)
        return {}


async def create_property_documents_table() -> None:
    """Create property_documents table if it doesn't exist (called on startup)."""
    if _pool is None:
        return
    try:
        await _pool.execute("""
            CREATE TABLE IF NOT EXISTS property_documents (
                id          SERIAL PRIMARY KEY,
                property_id VARCHAR(100) NOT NULL,
                filename    VARCHAR(255) NOT NULL,
                file_type   VARCHAR(20)  NOT NULL,
                content_text TEXT        NOT NULL DEFAULT '',
                size_bytes  INT          NOT NULL,
                uploaded_at TIMESTAMP    DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_property_documents_property_id
                ON property_documents(property_id);
        """)
    except Exception as e:
        logger.warning("create_property_documents_table: %s", e)


async def insert_property_document(
    property_id: str,
    filename: str,
    file_type: str,
    content_text: str,
    size_bytes: int,
) -> dict:
    """Insert a document and return its metadata."""
    if _pool is None:
        raise RuntimeError("Database not available")
    row = await _pool.fetchrow(
        """
        INSERT INTO property_documents (property_id, filename, file_type, content_text, size_bytes)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, property_id, filename, file_type, size_bytes, uploaded_at
        """,
        property_id, filename, file_type, content_text, size_bytes,
    )
    return {
        "id":          row["id"],
        "property_id": row["property_id"],
        "filename":    row["filename"],
        "file_type":   row["file_type"],
        "size_bytes":  row["size_bytes"],
        "uploaded_at": row["uploaded_at"].isoformat(),
    }


async def get_property_documents(property_id: str) -> list[dict]:
    """Return document metadata (no content_text) for a property."""
    if _pool is None:
        return []
    rows = await _pool.fetch(
        """
        SELECT id, property_id, filename, file_type, size_bytes, uploaded_at
        FROM property_documents
        WHERE property_id = $1
        ORDER BY uploaded_at DESC
        """,
        property_id,
    )
    return [
        {
            "id":          r["id"],
            "property_id": r["property_id"],
            "filename":    r["filename"],
            "file_type":   r["file_type"],
            "size_bytes":  r["size_bytes"],
            "uploaded_at": r["uploaded_at"].isoformat(),
        }
        for r in rows
    ]


async def get_property_documents_text(property_ids: list[str], max_chars: int = 8000) -> list[dict]:
    """Return documents with content_text for KB injection (for broker agent)."""
    if _pool is None or not property_ids:
        return []
    rows = await _pool.fetch(
        """
        SELECT property_id, filename, content_text
        FROM property_documents
        WHERE property_id = ANY($1::varchar[])
        ORDER BY uploaded_at DESC
        LIMIT 10
        """,
        property_ids,
    )
    results = []
    total = 0
    for r in rows:
        text = (r["content_text"] or "")[:max_chars - total]
        if text:
            results.append({
                "property_id": r["property_id"],
                "filename":    r["filename"],
                "text":        text,
            })
            total += len(text)
            if total >= max_chars:
                break
    return results


async def delete_property_document(property_id: str, doc_id: int) -> bool:
    """Delete a document. Returns True if a row was deleted."""
    if _pool is None:
        return False
    result = await _pool.execute(
        "DELETE FROM property_documents WHERE id = $1 AND property_id = $2",
        doc_id, property_id,
    )
    return result == "DELETE 1"


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
