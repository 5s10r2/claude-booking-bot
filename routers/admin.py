"""
routers/admin.py — Admin and internal endpoints.

Routes:
  GET    /rate-limit/status
  GET    /admin/analytics
  GET    /admin/conversations
  GET    /admin/conversations/{uid}
  POST   /admin/conversations/{uid}/takeover
  POST   /admin/conversations/{uid}/resume
  POST   /admin/conversations/{uid}/message
  GET    /admin/command-center
  GET    /admin/leads
  GET    /admin/flags
  POST   /admin/flags
  GET    /admin/brand-config
  POST   /admin/brand-config
  POST   /admin/broadcast
  GET    /admin/properties
  GET    /admin/properties/{prop_id}/documents
  POST   /admin/properties/{prop_id}/documents
  DELETE /admin/properties/{prop_id}/documents/{doc_id}
  POST   /admin/backfill-brands
"""

import asyncio
import json as _json_module
import time as _time
import traceback
import uuid as uuid_lib
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from channels.whatsapp import send_text
from config import settings
from core.auth import CHAT_BASE_URL, require_admin_brand_key, require_brand_api_key, verify_api_key
from core.log import get_logger
from db import postgres as pg
from db.redis_store import (
    _r,
    clear_human_mode,
    get_active_users,
    get_agent_usage,
    get_brand_active_users,
    get_brand_active_users_count,
    get_brand_config,
    get_brand_config_by_hash,
    get_conversation,
    get_feedback_counts,
    get_funnel,
    get_human_mode,
    get_last_agent,
    get_preferences,
    get_session_cost,
    get_skill_misses,
    get_skill_usage,
    get_user_brand,
    get_user_memory,
    get_user_phone,
    save_conversation,
    set_brand_config,
    set_human_mode,
    get_agent_costs,
    get_daily_cost,
)

logger = get_logger("routers.admin")

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _r_score(uid: str):
    """Get uid score from active_users sorted set."""
    try:
        score = _r().zscore("active_users", uid)
        return float(score) if score is not None else None
    except Exception:
        return None


def _require_ownership(uid: str, brand_hash: str) -> None:
    """Raise 404 if `uid` does not belong to the given brand.

    Uses a lenient check: if the user has no brand tag yet (legacy user),
    the request is allowed. This avoids breaking admin operations for
    users who haven't been backfilled yet.
    """
    user_brand = get_user_brand(uid)
    if user_brand and user_brand != brand_hash:
        raise HTTPException(status_code=404, detail="Conversation not found")


# ---------------------------------------------------------------------------
# Rate-limit status
# ---------------------------------------------------------------------------

@router.get("/rate-limit/status", dependencies=[Depends(verify_api_key)])
async def rate_limit_status(user_id: str):
    """Show current rate-limit usage for a given user."""
    from core.rate_limiter import get_rate_limit_status
    return get_rate_limit_status(user_id)


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/admin/analytics")
async def admin_analytics(days: int = 7, brand_hash: str = Depends(require_admin_brand_key)):
    """Return aggregated analytics data for the dashboard.

    Query params:
      days: integer number of days to look back (default 7, max 90)
    """
    today = date.today()
    days = max(1, min(days, 90))

    # --- Funnel: aggregate across date range (brand-scoped) ---
    funnel_totals: dict[str, int] = {}
    for i in range(days):
        day = (today - timedelta(days=i)).isoformat()
        for stage, count in get_funnel(day, brand_hash=brand_hash).items():
            funnel_totals[stage] = funnel_totals.get(stage, 0) + count

    # --- Feedback (brand-scoped) ---
    feedback = get_feedback_counts(brand_hash=brand_hash)

    # --- Message volume (from Postgres, brand-scoped) ---
    message_volume: dict[str, int] = {}
    try:
        start_date = today - timedelta(days=days - 1)
        message_volume = await pg.get_message_volume(
            start_date.isoformat(), today.isoformat(), brand_hash=brand_hash
        )
    except Exception as e:
        logger.warning("get_message_volume failed: %s", e)

    # --- Agent distribution: aggregate across date range (brand-scoped) ---
    agent_totals: dict[str, int] = {}
    for i in range(days):
        day = (today - timedelta(days=i)).isoformat()
        for agent, count in get_agent_usage(day, brand_hash=brand_hash).items():
            agent_totals[agent] = agent_totals.get(agent, 0) + count

    # --- Skill usage: aggregate across date range (brand-scoped) ---
    skill_totals: dict[str, int] = {}
    skill_miss_totals: dict[str, int] = {}
    for i in range(days):
        day = (today - timedelta(days=i)).isoformat()
        for skill, count in get_skill_usage(day, brand_hash=brand_hash).items():
            skill_totals[skill] = skill_totals.get(skill, 0) + count
        for tool, count in get_skill_misses(day, brand_hash=brand_hash).items():
            skill_miss_totals[tool] = skill_miss_totals.get(tool, 0) + count

    # --- Rate limit status (current snapshot) ---
    from core.rate_limiter import get_rate_limit_status
    rate_limits = {}
    try:
        rate_limits = get_rate_limit_status("__global__")
    except Exception as e:
        logger.warning("rate limit status fetch failed: %s", e)

    # --- Derived KPIs — brand-scoped user count & cost ---
    total_messages = sum(message_volume.values())
    active_users_count = get_brand_active_users_count(brand_hash)
    visits_booked = funnel_totals.get("visit", 0)
    new_leads = funnel_totals.get("search", 0)  # anyone who ran a search = engaged lead

    # Chronologically sorted daily message counts for the chart
    daily = [{"date": d, "count": c} for d, c in sorted(message_volume.items())]

    # Total cost: sum session_cost across brand's tracked users (best-effort)
    total_cost_usd = 0.0
    try:
        brand_uids = get_brand_active_users(brand_hash, offset=0, limit=500)
        for uid in brand_uids:
            total_cost_usd += get_session_cost(uid).get("cost_usd", 0.0)
    except Exception as e:
        logger.warning("cost aggregation failed: %s", e)

    return {
        # KPI cards
        "total_messages": total_messages,
        "active_users": active_users_count,
        "visits_booked": visits_booked,
        "new_leads": new_leads,
        "total_cost_usd": round(total_cost_usd, 4),
        # Chart data
        "daily": daily,
        "agents": agent_totals,
        "skills": {"usage": skill_totals, "misses": skill_miss_totals},
        # Extended data (kept for backward compat)
        "funnel": funnel_totals,
        "feedback": feedback,
        "messages": message_volume,
        "rate_limits": rate_limits,
        "meta": {
            "days": days,
            "generated_at": datetime.utcnow().isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Conversation browser
# ---------------------------------------------------------------------------

@router.get("/admin/conversations")
async def admin_conversations(offset: int = 0, limit: int = 50, brand_hash: str = Depends(require_admin_brand_key)):
    """Return paginated list of users sorted by most recent activity.

    Each entry contains enough metadata to render a conversation list row:
    uid, name, phone, last_message preview, last_agent, lead_score, human_mode.
    """
    total = get_brand_active_users_count(brand_hash)
    uids = get_brand_active_users(brand_hash, offset=offset, limit=limit)

    rows = []
    for uid in uids:
        mem = get_user_memory(uid)
        conv = get_conversation(uid)
        human_mode = get_human_mode(uid, brand_hash=brand_hash)

        # Last message preview (last non-empty text message)
        last_msg = ""
        last_role = ""
        for msg in reversed(conv):
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                last_msg = content[:120]
                last_role = msg.get("role", "")
                break

        cost_data = get_session_cost(uid)
        rows.append({
            "uid": uid,
            "name": mem.get("profile_name") or mem.get("name") or "",
            "phone": get_user_phone(uid) or "",
            "last_message": last_msg,
            "last_role": last_role,
            "last_agent": get_last_agent(uid) or "default",
            "lead_score": mem.get("lead_score", 0),
            "funnel_stage": mem.get("funnel_max", ""),
            "last_seen": mem.get("last_seen", ""),
            "human_mode": human_mode,
            "message_count": len(conv),
            "cost_usd": cost_data.get("cost_usd", 0.0),
        })

    return {
        "conversations": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total,
    }


@router.get("/admin/conversations/{uid}")
async def admin_conversation_detail(uid: str, brand_hash: str = Depends(require_admin_brand_key)):
    """Return full conversation thread + user context for a given uid."""
    _require_ownership(uid, brand_hash)
    conv = get_conversation(uid)
    mem = get_user_memory(uid)
    prefs = get_preferences(uid)
    cost = get_session_cost(uid)
    human_mode = get_human_mode(uid, brand_hash=brand_hash)
    last_agent = get_last_agent(uid) or "default"

    return {
        "uid": uid,
        "messages": conv,
        "memory": mem,
        "preferences": prefs,
        "cost": cost,
        "human_mode": human_mode,
        "last_agent": last_agent,
    }


class AdminMessageRequest(BaseModel):
    message: str
    platform: str = "whatsapp"  # "whatsapp" | "web"


@router.post("/admin/conversations/{uid}/takeover")
async def admin_takeover(uid: str, brand_hash: str = Depends(require_admin_brand_key)):
    """Activate human takeover — AI stops responding for this user."""
    _require_ownership(uid, brand_hash)
    set_human_mode(uid, brand_hash=brand_hash)
    return {"ok": True}


@router.post("/admin/conversations/{uid}/resume")
async def admin_resume(uid: str, brand_hash: str = Depends(require_admin_brand_key)):
    """Deactivate human takeover — AI resumes handling this user."""
    _require_ownership(uid, brand_hash)
    clear_human_mode(uid, brand_hash=brand_hash)
    return {"ok": True}


@router.post("/admin/conversations/{uid}/message")
async def admin_send_message(uid: str, req: AdminMessageRequest, brand_hash: str = Depends(require_admin_brand_key)):
    """Send a manual message as the admin (human operator).

    The message is delivered via WhatsApp and appended to the conversation
    history with source="human" so the thread view can style it distinctly.

    After sending, human_mode is automatically cleared so the AI resumes
    on the user's next reply. This prevents the silent-bot bug where the
    admin sends one message and forgets to click "Resume AI", leaving every
    subsequent user message unanswered.
    """
    _require_ownership(uid, brand_hash)
    sent_at = datetime.utcnow().isoformat()

    # Deliver via WhatsApp if platform is whatsapp
    if req.platform == "whatsapp":
        await send_text(uid, req.message)

    # Append to conversation history for thread view
    conv = get_conversation(uid)
    conv.append({
        "role": "assistant",
        "content": req.message,
        "source": "human",
        "sent_at": sent_at,
    })
    save_conversation(uid, conv, brand_hash=brand_hash)

    # Auto-resume AI after admin message — prevents silent-bot if admin forgets
    # to click "Resume AI". Admin can re-take-over by calling /takeover again.
    clear_human_mode(uid, brand_hash=brand_hash)

    return {"ok": True, "sent_at": sent_at}


# ---------------------------------------------------------------------------
# Command center
# ---------------------------------------------------------------------------

@router.get("/admin/command-center")
async def admin_command_center(brand_hash: str = Depends(require_admin_brand_key)):
    """Today's at-a-glance stats for the command center home screen."""
    today = date.today().isoformat()
    day_funnel = get_funnel(today, brand_hash=brand_hash)
    day_agents = get_agent_usage(today, brand_hash=brand_hash)

    # Count conversations currently in human mode (brand-scoped)
    brand_uids = get_brand_active_users(brand_hash, offset=0, limit=200)
    human_count = sum(1 for uid in brand_uids if get_human_mode(uid, brand_hash=brand_hash))

    # Message count for today from Postgres (best-effort)
    msg_count = 0
    try:
        vol = await pg.get_message_volume(today, today, brand_hash=brand_hash)
        msg_count = vol.get(today, 0)
    except Exception:
        pass

    return {
        "today": {
            "messages":         msg_count,
            "new_leads":        day_funnel.get("searching", 0),
            "visits_scheduled": day_funnel.get("visit_scheduled", 0),
            "booked":           day_funnel.get("booked", 0),
        },
        "funnel":               day_funnel,
        "agents":               day_agents,
        "active_conversations": get_brand_active_users_count(brand_hash),
        "human_mode_count":     human_count,
        # Cost fields — consumed by admin portal AnalyticsPage AgentCostTable + KPI card
        "cost_usd_today":       get_daily_cost(today, brand_hash=brand_hash),
        "agents_cost":          get_agent_costs(today, brand_hash=brand_hash),
        "generated_at":         datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

def _lead_row(uid: str) -> dict:
    """Build the full 25-field lead dict for a single uid. DRY helper used by both endpoints."""
    mem   = get_user_memory(uid)
    prefs = get_preferences(uid)
    phone = get_user_phone(uid) or ""
    name  = mem.get("profile_name") or mem.get("name") or ""
    cost  = get_session_cost(uid)

    # Budget: prefer structured prefs, fall back to memory strings
    budget_min = prefs.get("min_budget")
    budget_max = prefs.get("max_budget") or mem.get("budget_max") or mem.get("budget")

    return {
        # Identity
        "uid":              uid,
        "name":             name,
        "phone":            phone,
        "phone_collected":  bool(mem.get("phone_collected", False)),
        "persona":          mem.get("persona") or "",
        # Funnel
        "stage":            mem.get("funnel_max") or "",
        "first_seen":       mem.get("first_seen") or "",
        "last_seen":        mem.get("last_seen") or "",
        "session_count":    int(mem.get("session_count") or 0),
        # Engagement
        "viewed_count":      len(mem.get("properties_viewed") or []),
        "shortlisted_count": len(mem.get("properties_shortlisted") or []),
        "visits_count":      len(mem.get("visits_scheduled") or []),
        # Intent signals
        "deal_breakers":    mem.get("deal_breakers") or [],
        "must_haves":       mem.get("must_haves") or [],
        "lead_score":       int(mem.get("lead_score") or 0),
        # Location & Budget
        "location_pref":    mem.get("location_preference") or mem.get("location_pref") or "",
        "budget_min":       budget_min,
        "budget_max":       budget_max,
        "budget":           mem.get("budget") or "",
        # Preferences
        "property_type":    prefs.get("property_type") or "",
        "amenities":        prefs.get("amenities") or prefs.get("must_have_amenities") or [],
        "sharing_types":    prefs.get("sharing_types_enabled") or [],
        # Cost
        "cost_usd":         float(cost.get("cost_usd") or 0.0),
    }


@router.get("/admin/leads")
async def admin_leads(
    stage: str = "",
    area: str = "",
    budget_max: int = 0,
    days_since_active: int = 0,
    q: str = "",
    offset: int = 0,
    limit: int = 25,
    brand_hash: str = Depends(require_admin_brand_key),
):
    """Return paginated, filterable lead list sorted by recency."""
    cutoff_ts = _time.time() - (days_since_active * 86400) if days_since_active else 0

    # Pull a larger batch from the brand's sorted set so we can filter in Python
    batch_size = max(limit * 4, 200)
    uids = get_brand_active_users(brand_hash, offset=0, limit=batch_size)

    rows = []
    for uid in uids:
        mem = get_user_memory(uid)

        # Age filter
        if cutoff_ts:
            score = _r_score(uid)
            if score and score < cutoff_ts:
                continue

        # Stage filter
        if stage and mem.get("funnel_max") != stage:
            continue

        # Area filter
        loc = (mem.get("location_preference") or mem.get("location_pref") or "").lower()
        if area and area.lower() not in loc:
            continue

        # Budget filter
        budget_val = mem.get("budget_max") or mem.get("budget")
        if budget_max and budget_val:
            try:
                if int(budget_val) > budget_max:
                    continue
            except (ValueError, TypeError):
                pass

        name  = mem.get("profile_name") or mem.get("name") or ""
        phone = get_user_phone(uid) or ""

        # Full-text search across name + phone
        if q and q.lower() not in name.lower() and q.lower() not in phone:
            continue

        rows.append(_lead_row(uid))

    total = len(rows)
    page  = rows[offset: offset + limit]

    # Persist enriched snapshot to PostgreSQL (fire-and-forget, brand-scoped)
    if rows:
        asyncio.create_task(pg.upsert_leads(rows, brand_hash=brand_hash))

    return {"leads": page, "total": total, "offset": offset, "limit": limit}


@router.get("/admin/leads/{uid}")
async def admin_lead_detail(uid: str, brand_hash: str = Depends(require_admin_brand_key)):
    """Return the full 25-field profile for a single lead."""
    _require_ownership(uid, brand_hash)
    row = _lead_row(uid)
    asyncio.create_task(pg.upsert_leads([row], brand_hash=brand_hash))
    return row


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

@router.get("/admin/flags")
async def admin_get_flags(brand_hash: str = Depends(require_admin_brand_key)):
    """Return effective feature flag states (per-brand overrides merged over global defaults)."""
    from db.redis_store import get_effective_flags
    flags = get_effective_flags(brand_hash)
    flags["WEB_SEARCH_ENABLED"] = bool(settings.TAVILY_API_KEY)  # always global, read-only
    return flags


# Mutable flags that can be toggled per-brand (persisted in Redis).
_MUTABLE_FLAGS = {"DYNAMIC_SKILLS_ENABLED", "KYC_ENABLED", "PAYMENT_REQUIRED"}


@router.post("/admin/flags")
async def admin_set_flags(request: Request, brand_hash: str = Depends(require_admin_brand_key)):
    """Update per-brand feature flags (persisted in Redis per brand).

    Accepts both payload formats:
      - { "key": "FLAG_NAME", "value": bool }  (frontend sends this)
      - { "FLAG_NAME": bool }                  (direct API usage)
    """
    from db.redis_store import set_brand_flag, get_effective_flags
    body = await request.json()

    # Support both: { KEY: value } and { key: "KEY", value: bool }
    if "key" in body and "value" in body:
        updates = {body["key"]: body["value"]}
    else:
        updates = body

    changed = {}
    for flag in _MUTABLE_FLAGS:
        if flag in updates and updates[flag] is not None:
            set_brand_flag(brand_hash, flag, bool(updates[flag]))
            changed[flag] = bool(updates[flag])

    # Return all effective flags so frontend reflects the merged state
    return {"ok": True, "changed": changed, "effective": get_effective_flags(brand_hash)}


# ---------------------------------------------------------------------------
# Brand configuration (multi-tenant white-label)
# ---------------------------------------------------------------------------

class BrandConfigRequest(BaseModel):
    pg_ids: list[str] | None = None
    brand_name: str | None = None
    cities: str | None = None
    areas: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_access_token: str | None = None  # "••••xxxx" → preserve existing token
    waba_id: str | None = None
    is_meta: bool | None = None
    # brand_link_token is auto-generated server-side, never in request body


@router.get("/admin/brand-config")
async def admin_get_brand_config(api_key: str = Depends(require_brand_api_key)):
    """Return brand config for the given API key. Access token is masked."""
    config = dict(get_brand_config(api_key) or {})
    token = config.get("whatsapp_access_token", "")
    if token:
        config["whatsapp_access_token"] = "••••" + token[-4:]
    link_token = config.get("brand_link_token", "")
    chatbot_url = f"{CHAT_BASE_URL}?brand={link_token}" if link_token else None
    return {"is_configured": bool(config.get("pg_ids")), "chatbot_url": chatbot_url, **config}


@router.post("/admin/brand-config")
async def admin_set_brand_config(body: BrandConfigRequest, api_key: str = Depends(require_brand_api_key)):
    """Upsert brand config. Partial updates are merged with existing config."""
    existing = dict(get_brand_config(api_key) or {})
    merged = {**existing, **{k: v for k, v in body.dict().items() if v is not None}}
    wa_token = merged.get("whatsapp_access_token", "")
    if wa_token.startswith("••••"):
        # Masked value submitted — preserve the real token already in Redis
        merged["whatsapp_access_token"] = existing.get("whatsapp_access_token", "")
    if not merged.get("brand_link_token"):
        # Auto-generate a permanent UUID on first save
        merged["brand_link_token"] = str(uuid_lib.uuid4())
    merged["updated_at"] = datetime.utcnow().isoformat() + "Z"
    if "created_at" not in merged:
        merged["created_at"] = merged["updated_at"]
    set_brand_config(api_key, merged)
    return {"ok": True, "brand_link_token": merged["brand_link_token"]}


# ---------------------------------------------------------------------------
# Broadcast
# ---------------------------------------------------------------------------

class BroadcastRequest(BaseModel):
    message: str


@router.post("/admin/broadcast")
async def admin_broadcast(req: BroadcastRequest, brand_hash: str = Depends(require_admin_brand_key)):
    """Send a text message to all brand users active in the last 7 days."""
    cutoff = _time.time() - 7 * 86400
    uids = get_brand_active_users(brand_hash, offset=0, limit=500)

    sent = 0
    for uid in uids:
        try:
            score = _r().zscore(f"active_users:{brand_hash}", uid)
            if score and float(score) < cutoff:
                continue
            await send_text(uid, req.message)
            sent += 1
        except Exception as e:
            logger.warning("broadcast to %s failed: %s", uid, e)

    return {"ok": True, "sent": sent}


# ---------------------------------------------------------------------------
# Property documents
# ---------------------------------------------------------------------------

@router.get("/admin/properties")
async def admin_list_properties(brand_hash: str = Depends(require_admin_brand_key)):
    """Return properties belonging to this brand (from Redis property_info_map cache)."""
    # Determine which pg_ids belong to this brand
    brand_cfg = get_brand_config_by_hash(brand_hash) or {}
    brand_pg_ids = set(brand_cfg.get("pg_ids", []))

    try:
        raw = _r().get("property_info_map")
        if not raw:
            return {"properties": []}
        prop_map = _json_module.loads(raw)
        props = []
        for pid, info in prop_map.items():
            # Only show properties belonging to this brand
            if brand_pg_ids and pid not in brand_pg_ids:
                continue
            props.append({
                "id":   pid,
                "name": info.get("pg_name") or info.get("name") or pid,
                "area": info.get("area") or info.get("location") or "",
            })
        return {"properties": props}
    except Exception as e:
        logger.warning("admin_list_properties: %s", e)
        return {"properties": []}


def _require_property_ownership(prop_id: str, brand_hash: str) -> None:
    """Raise 403 if prop_id is not in the brand's pg_ids list."""
    brand_cfg = get_brand_config_by_hash(brand_hash) or {}
    brand_pg_ids = brand_cfg.get("pg_ids", [])
    if brand_pg_ids and prop_id not in brand_pg_ids:
        raise HTTPException(status_code=403, detail="Property not in your brand")


@router.get("/admin/properties/{prop_id}/documents")
async def admin_get_documents(prop_id: str, brand_hash: str = Depends(require_admin_brand_key)):
    """Return document metadata for a property."""
    _require_property_ownership(prop_id, brand_hash)
    docs = await pg.get_property_documents(prop_id)
    return {"documents": docs}


class UploadDocResponse(BaseModel):
    id: int
    filename: str
    size_bytes: int
    uploaded_at: str


@router.post("/admin/properties/{prop_id}/documents")
async def admin_upload_document(prop_id: str, file: UploadFile = File(...), brand_hash: str = Depends(require_admin_brand_key)):
    """Upload a knowledge document (PDF, XLSX, CSV, TXT) for a property."""
    _require_property_ownership(prop_id, brand_hash)
    ALLOWED = {"pdf", "xlsx", "csv", "txt"}
    MAX_SIZE = 10 * 1024 * 1024  # 10 MB

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: .{ext}")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 10 MB limit")

    # Extract text
    text = ""
    try:
        if ext == "pdf":
            from io import BytesIO
            import pypdf
            reader = pypdf.PdfReader(BytesIO(content))
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
        elif ext == "xlsx":
            from io import BytesIO
            import openpyxl
            wb = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
            rows = []
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    rows.append("\t".join(str(c) if c is not None else "" for c in row))
            text = "\n".join(rows)
        elif ext == "csv":
            text = content.decode("utf-8", errors="replace")
        else:
            text = content.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("text extraction failed for %s: %s", file.filename, e)
        text = ""

    doc = await pg.insert_property_document(
        property_id=prop_id,
        filename=file.filename,
        file_type=ext,
        content_text=text,
        size_bytes=len(content),
    )
    return doc


@router.delete("/admin/properties/{prop_id}/documents/{doc_id}")
async def admin_delete_document(prop_id: str, doc_id: int, brand_hash: str = Depends(require_admin_brand_key)):
    """Delete a property document."""
    _require_property_ownership(prop_id, brand_hash)
    deleted = await pg.delete_property_document(prop_id, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Backfill utility
# ---------------------------------------------------------------------------

@router.post("/admin/backfill-brands")
async def admin_backfill_brands(brand_hash: str = Depends(require_admin_brand_key)):
    """One-time backfill: tag all existing users with this brand and populate
    the brand-scoped active_users sorted set.

    Safe to call multiple times — idempotent writes.

    How it works:
      1. Scans the global active_users sorted set (all existing users).
      2. For each user, checks if they already have a brand tag.
      3. If untagged (legacy user), assigns them to the calling admin's brand.
      4. Users already tagged with a different brand are skipped.
    """
    from db.redis_store import set_user_brand, add_to_brand_active_users

    try:
        r = _r()
        tagged = 0
        skipped = 0
        already_tagged = 0

        # Iterate all users in the global sorted set
        all_uids = get_active_users(offset=0, limit=5000)
        for uid in all_uids:
            existing_brand = get_user_brand(uid)
            if existing_brand == brand_hash:
                # Already tagged with this brand
                already_tagged += 1
                continue
            if existing_brand:
                # Tagged with a different brand — skip
                skipped += 1
                continue
            # Untagged legacy user — assign to calling brand
            set_user_brand(uid, brand_hash)
            add_to_brand_active_users(uid, brand_hash)
            tagged += 1

        total = get_brand_active_users_count(brand_hash)
        return {
            "ok": True,
            "tagged": tagged,
            "already_tagged": already_tagged,
            "skipped_other_brand": skipped,
            "total_in_brand": total,
        }
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "trace": traceback.format_exc()[-800:]},
        )
