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
    brand_hash: Optional[str] = None,
) -> Optional[int]:
    if _pool is None:
        return None
    now = datetime.utcnow()
    try:
        row = await _pool.fetchrow(
            """
            INSERT INTO booking_messages
            (thread_id, user_phone, message_text, message_sent_by,
             created_at, updated_at, platform_type, is_template, pg_ids, brand_hash)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
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
            brand_hash,
        )
        return row["id"] if row else None
    except Exception as e:
        logger.error("insert_message error: %s", e)
        return None


async def get_message_volume(start_date: str, end_date: str, brand_hash: Optional[str] = None) -> dict:
    """Return daily message counts: {"2026-02-20": 42, ...}.
    Brand-scoped if brand_hash provided.
    """
    if _pool is None:
        return {}
    try:
        if brand_hash:
            rows = await _pool.fetch(
                """
                SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                FROM booking_messages
                WHERE created_at >= $1::date
                  AND created_at < ($2::date + INTERVAL '1 day')
                  AND brand_hash = $3
                GROUP BY DATE(created_at)
                ORDER BY day
                """,
                start_date,
                end_date,
                brand_hash,
            )
        else:
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


async def add_brand_hash_columns() -> None:
    """Add brand_hash column to booking_messages and leads tables (idempotent migration)."""
    if _pool is None:
        return
    try:
        await _pool.execute("""
            ALTER TABLE booking_messages ADD COLUMN IF NOT EXISTS brand_hash VARCHAR(16);
            CREATE INDEX IF NOT EXISTS idx_booking_messages_brand_hash
                ON booking_messages(brand_hash);
        """)
    except Exception as e:
        logger.warning("add_brand_hash_columns (booking_messages): %s", e)
    try:
        await _pool.execute("""
            ALTER TABLE leads ADD COLUMN IF NOT EXISTS brand_hash VARCHAR(16);
            CREATE INDEX IF NOT EXISTS idx_leads_brand_hash ON leads(brand_hash);
        """)
    except Exception as e:
        logger.warning("add_brand_hash_columns (leads): %s", e)


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


async def create_leads_table() -> None:
    """Create the leads snapshot table (called on startup)."""
    if _pool is None:
        return
    try:
        await _pool.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                uid               TEXT PRIMARY KEY,
                name              TEXT,
                phone             TEXT,
                phone_collected   BOOLEAN   DEFAULT FALSE,
                persona           TEXT,
                stage             TEXT,
                first_seen        TEXT,
                last_seen         TEXT,
                session_count     INTEGER   DEFAULT 0,
                viewed_count      INTEGER   DEFAULT 0,
                shortlisted_count INTEGER   DEFAULT 0,
                visits_count      INTEGER   DEFAULT 0,
                deal_breakers     JSONB     DEFAULT '[]',
                must_haves        JSONB     DEFAULT '[]',
                lead_score        INTEGER   DEFAULT 0,
                location_pref     TEXT,
                budget_min        NUMERIC,
                budget_max        NUMERIC,
                budget            TEXT,
                property_type     TEXT,
                amenities         JSONB     DEFAULT '[]',
                sharing_types     JSONB     DEFAULT '[]',
                cost_usd          NUMERIC   DEFAULT 0,
                synced_at         TIMESTAMP DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_leads_stage     ON leads(stage);
            CREATE INDEX IF NOT EXISTS idx_leads_score     ON leads(lead_score DESC);
            CREATE INDEX IF NOT EXISTS idx_leads_last_seen ON leads(last_seen);
        """)
    except Exception as e:
        logger.warning("create_leads_table: %s", e)


async def upsert_leads(rows: list[dict], brand_hash: Optional[str] = None) -> None:
    """Batch upsert enriched lead snapshots. Called fire-and-forget from admin endpoints."""
    if _pool is None or not rows:
        return
    try:
        await _pool.executemany(
            """
            INSERT INTO leads (
                uid, name, phone, phone_collected, persona, stage,
                first_seen, last_seen, session_count, viewed_count, shortlisted_count,
                visits_count, deal_breakers, must_haves, lead_score, location_pref,
                budget_min, budget_max, budget, property_type, amenities,
                sharing_types, cost_usd, brand_hash, synced_at
            )
            VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,NOW()
            )
            ON CONFLICT (uid) DO UPDATE SET
                name=EXCLUDED.name, phone=EXCLUDED.phone,
                phone_collected=EXCLUDED.phone_collected, persona=EXCLUDED.persona,
                stage=EXCLUDED.stage, first_seen=EXCLUDED.first_seen,
                last_seen=EXCLUDED.last_seen, session_count=EXCLUDED.session_count,
                viewed_count=EXCLUDED.viewed_count, shortlisted_count=EXCLUDED.shortlisted_count,
                visits_count=EXCLUDED.visits_count, deal_breakers=EXCLUDED.deal_breakers,
                must_haves=EXCLUDED.must_haves, lead_score=EXCLUDED.lead_score,
                location_pref=EXCLUDED.location_pref, budget_min=EXCLUDED.budget_min,
                budget_max=EXCLUDED.budget_max, budget=EXCLUDED.budget,
                property_type=EXCLUDED.property_type, amenities=EXCLUDED.amenities,
                sharing_types=EXCLUDED.sharing_types, cost_usd=EXCLUDED.cost_usd,
                brand_hash=EXCLUDED.brand_hash,
                synced_at=NOW()
            """,
            [
                (
                    r["uid"], r["name"], r["phone"],
                    bool(r.get("phone_collected", False)),
                    r.get("persona") or "",
                    r.get("stage") or "",
                    r.get("first_seen") or "",
                    r.get("last_seen") or "",
                    int(r.get("session_count") or 0),
                    int(r.get("viewed_count") or 0),
                    int(r.get("shortlisted_count") or 0),
                    int(r.get("visits_count") or 0),
                    json.dumps(r.get("deal_breakers") or []),
                    json.dumps(r.get("must_haves") or []),
                    int(r.get("lead_score") or 0),
                    r.get("location_pref") or "",
                    r.get("budget_min"),
                    r.get("budget_max"),
                    r.get("budget") or "",
                    r.get("property_type") or "",
                    json.dumps(r.get("amenities") or []),
                    json.dumps(r.get("sharing_types") or []),
                    float(r.get("cost_usd") or 0.0),
                    brand_hash,
                )
                for r in rows
            ],
        )
    except Exception as e:
        logger.error("upsert_leads error: %s", e)


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
