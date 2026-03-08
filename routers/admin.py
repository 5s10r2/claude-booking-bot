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
  POST   /admin/backfill-users
"""

import json as _json_module
import time as _time
import traceback
import uuid as uuid_lib
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from channels.whatsapp import send_text
from config import settings
from core.auth import CHAT_BASE_URL, require_brand_api_key, verify_api_key
from core.log import get_logger
from db import postgres as pg
from db.redis_store import (
    _r,
    clear_human_mode,
    get_active_users,
    get_active_users_count,
    get_agent_usage,
    get_brand_config,
    get_conversation,
    get_feedback_counts,
    get_funnel,
    get_human_mode,
    get_last_agent,
    get_preferences,
    get_session_cost,
    get_skill_misses,
    get_skill_usage,
    get_user_memory,
    get_user_phone,
    save_conversation,
    set_brand_config,
    set_human_mode,
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

@router.get("/admin/analytics", dependencies=[Depends(verify_api_key)])
async def admin_analytics(days: int = 7):
    """Return aggregated analytics data for the dashboard.

    Query params:
      days: integer number of days to look back (default 7, max 90)
    """
    today = date.today()
    days = max(1, min(days, 90))

    # --- Funnel: aggregate across date range ---
    funnel_totals: dict[str, int] = {}
    for i in range(days):
        day = (today - timedelta(days=i)).isoformat()
        for stage, count in get_funnel(day).items():
            funnel_totals[stage] = funnel_totals.get(stage, 0) + count

    # --- Feedback ---
    feedback = get_feedback_counts()

    # --- Message volume (from Postgres) ---
    message_volume: dict[str, int] = {}
    try:
        start_date = today - timedelta(days=days - 1)
        message_volume = await pg.get_message_volume(
            start_date.isoformat(), today.isoformat()
        )
    except Exception as e:
        logger.warning("get_message_volume failed: %s", e)

    # --- Agent distribution: aggregate across date range ---
    agent_totals: dict[str, int] = {}
    for i in range(days):
        day = (today - timedelta(days=i)).isoformat()
        for agent, count in get_agent_usage(day).items():
            agent_totals[agent] = agent_totals.get(agent, 0) + count

    # --- Skill usage: aggregate across date range ---
    skill_totals: dict[str, int] = {}
    skill_miss_totals: dict[str, int] = {}
    for i in range(days):
        day = (today - timedelta(days=i)).isoformat()
        for skill, count in get_skill_usage(day).items():
            skill_totals[skill] = skill_totals.get(skill, 0) + count
        for tool, count in get_skill_misses(day).items():
            skill_miss_totals[tool] = skill_miss_totals.get(tool, 0) + count

    # --- Rate limit status (current snapshot) ---
    from core.rate_limiter import get_rate_limit_status
    rate_limits = {}
    try:
        rate_limits = get_rate_limit_status("__global__")
    except Exception as e:
        logger.warning("rate limit status fetch failed: %s", e)

    # --- Derived KPIs (fields analytics.js expects) ---
    total_messages = sum(message_volume.values())
    active_users_count = get_active_users_count()
    visits_booked = funnel_totals.get("visit", 0)
    new_leads = funnel_totals.get("search", 0)  # anyone who ran a search = engaged lead

    # Chronologically sorted daily message counts for the chart
    daily = [{"date": d, "count": c} for d, c in sorted(message_volume.items())]

    # Total cost: sum session_cost across all tracked users (best-effort)
    total_cost_usd = 0.0
    try:
        all_uids = get_active_users(offset=0, limit=500)
        for uid in all_uids:
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

@router.get("/admin/conversations", dependencies=[Depends(verify_api_key)])
async def admin_conversations(offset: int = 0, limit: int = 50):
    """Return paginated list of users sorted by most recent activity.

    Each entry contains enough metadata to render a conversation list row:
    uid, name, phone, last_message preview, last_agent, lead_score, human_mode.
    """
    total = get_active_users_count()
    uids = get_active_users(offset=offset, limit=limit)

    rows = []
    for uid in uids:
        mem = get_user_memory(uid)
        conv = get_conversation(uid)
        human_mode = get_human_mode(uid)

        # Last message preview (last non-empty text message)
        last_msg = ""
        last_role = ""
        for msg in reversed(conv):
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                last_msg = content[:120]
                last_role = msg.get("role", "")
                break

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
        })

    return {
        "conversations": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total,
    }


@router.get("/admin/conversations/{uid}", dependencies=[Depends(verify_api_key)])
async def admin_conversation_detail(uid: str):
    """Return full conversation thread + user context for a given uid."""
    conv = get_conversation(uid)
    mem = get_user_memory(uid)
    prefs = get_preferences(uid)
    cost = get_session_cost(uid)
    human_mode = get_human_mode(uid)
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


@router.post("/admin/conversations/{uid}/takeover", dependencies=[Depends(verify_api_key)])
async def admin_takeover(uid: str):
    """Activate human takeover — AI stops responding for this user."""
    set_human_mode(uid)
    return {"ok": True}


@router.post("/admin/conversations/{uid}/resume", dependencies=[Depends(verify_api_key)])
async def admin_resume(uid: str):
    """Deactivate human takeover — AI resumes handling this user."""
    clear_human_mode(uid)
    return {"ok": True}


@router.post("/admin/conversations/{uid}/message", dependencies=[Depends(verify_api_key)])
async def admin_send_message(uid: str, req: AdminMessageRequest):
    """Send a manual message as the admin (human operator).

    The message is delivered via WhatsApp and appended to the conversation
    history with source="human" so the thread view can style it distinctly.
    """
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
    save_conversation(uid, conv)

    return {"ok": True, "sent_at": sent_at}


# ---------------------------------------------------------------------------
# Command center
# ---------------------------------------------------------------------------

@router.get("/admin/command-center", dependencies=[Depends(verify_api_key)])
async def admin_command_center():
    """Today's at-a-glance stats for the command center home screen."""
    today = date.today().isoformat()
    day_funnel = get_funnel(today)
    day_agents = get_agent_usage(today)

    # Count conversations currently in human mode
    all_uids = get_active_users(offset=0, limit=200)
    human_count = sum(1 for uid in all_uids if get_human_mode(uid))

    # Message count for today from Postgres (best-effort)
    msg_count = 0
    try:
        vol = await pg.get_message_volume(today, today)
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
        "funnel": day_funnel,
        "agents": day_agents,
        "active_conversations": get_active_users_count(),
        "human_mode_count":     human_count,
        "generated_at":         datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

@router.get("/admin/leads", dependencies=[Depends(verify_api_key)])
async def admin_leads(
    stage: str = "",
    area: str = "",
    budget_max: int = 0,
    days_since_active: int = 0,
    q: str = "",
    offset: int = 0,
    limit: int = 25,
):
    """Return paginated, filterable lead list sorted by recency."""
    cutoff_ts = _time.time() - (days_since_active * 86400) if days_since_active else 0

    # Pull a larger batch from the sorted set so we can filter in Python
    batch_size = max(limit * 4, 200)
    uids = get_active_users(offset=0, limit=batch_size)

    rows = []
    for uid in uids:
        mem = get_user_memory(uid)

        # Age filter — compare timestamp in sorted set
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

        name = mem.get("profile_name") or mem.get("name") or ""
        phone = get_user_phone(uid) or ""

        # Full-text search across name + phone
        if q and q.lower() not in name.lower() and q.lower() not in phone:
            continue

        cost_data = get_session_cost(uid)
        rows.append({
            "uid":           uid,
            "name":          name,
            "phone":         phone,
            "location_pref": mem.get("location_preference") or mem.get("location_pref") or "",
            "budget":        budget_val,
            "stage":         mem.get("funnel_max") or "",
            "last_seen":     mem.get("last_seen") or "",
            "lead_score":    mem.get("lead_score", 0),
            "cost_usd":      cost_data.get("cost_usd", 0.0),
        })

    total = len(rows)
    page = rows[offset: offset + limit]
    return {"leads": page, "total": total, "offset": offset, "limit": limit}


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

@router.get("/admin/flags", dependencies=[Depends(verify_api_key)])
async def admin_get_flags():
    """Return current feature flag states."""
    return {
        "DYNAMIC_SKILLS_ENABLED": settings.DYNAMIC_SKILLS_ENABLED,
        "KYC_ENABLED":            settings.KYC_ENABLED,
        "WEB_SEARCH_ENABLED":     bool(settings.TAVILY_API_KEY),
    }


class FlagUpdateRequest(BaseModel):
    DYNAMIC_SKILLS_ENABLED: bool | None = None
    KYC_ENABLED:            bool | None = None
    WEB_SEARCH_ENABLED:     bool | None = None


@router.post("/admin/flags", dependencies=[Depends(verify_api_key)])
async def admin_set_flags(req: FlagUpdateRequest):
    """Update runtime feature flags (in-memory only; restart resets to env values)."""
    if req.DYNAMIC_SKILLS_ENABLED is not None:
        settings.DYNAMIC_SKILLS_ENABLED = req.DYNAMIC_SKILLS_ENABLED
    if req.KYC_ENABLED is not None:
        settings.KYC_ENABLED = req.KYC_ENABLED
    return {"ok": True}


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


@router.post("/admin/broadcast", dependencies=[Depends(verify_api_key)])
async def admin_broadcast(req: BroadcastRequest):
    """Send a text message to all users active in the last 7 days."""
    cutoff = _time.time() - 7 * 86400
    uids = get_active_users(offset=0, limit=500)

    sent = 0
    for uid in uids:
        try:
            score = _r().zscore("active_users", uid)
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

@router.get("/admin/properties", dependencies=[Depends(verify_api_key)])
async def admin_list_properties():
    """Return all known properties (from Redis property_info_map cache)."""
    try:
        raw = _r().get("property_info_map")
        if not raw:
            return {"properties": []}
        prop_map = _json_module.loads(raw)
        props = []
        for pid, info in prop_map.items():
            props.append({
                "id":   pid,
                "name": info.get("pg_name") or info.get("name") or pid,
                "area": info.get("area") or info.get("location") or "",
            })
        return {"properties": props}
    except Exception as e:
        logger.warning("admin_list_properties: %s", e)
        return {"properties": []}


@router.get("/admin/properties/{prop_id}/documents", dependencies=[Depends(verify_api_key)])
async def admin_get_documents(prop_id: str):
    """Return document metadata for a property."""
    docs = await pg.get_property_documents(prop_id)
    return {"documents": docs}


class UploadDocResponse(BaseModel):
    id: int
    filename: str
    size_bytes: int
    uploaded_at: str


@router.post("/admin/properties/{prop_id}/documents", dependencies=[Depends(verify_api_key)])
async def admin_upload_document(prop_id: str, file: UploadFile = File(...)):
    """Upload a knowledge document (PDF, XLSX, CSV, TXT) for a property."""
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


@router.delete("/admin/properties/{prop_id}/documents/{doc_id}", dependencies=[Depends(verify_api_key)])
async def admin_delete_document(prop_id: str, doc_id: int):
    """Delete a property document."""
    deleted = await pg.delete_property_document(prop_id, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Backfill utility
# ---------------------------------------------------------------------------

@router.post("/admin/backfill-users", dependencies=[Depends(verify_api_key)])
async def admin_backfill_users():
    """One-time backfill: populate active_users sorted set from existing conversation keys.

    Safe to call multiple times — ZADD NX only adds entries that don't exist yet.
    Returns count of users added.
    """
    try:
        r = _r()
        added = 0
        # Scan for all conversation keys
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match="*:conversation", count=200)
            for key in keys:
                key_str = key if isinstance(key, str) else key.decode()
                uid = key_str.replace(":conversation", "")
                if not uid:
                    continue
                # Use NX so we don't overwrite entries already added by save_conversation()
                result = r.zadd("active_users", {uid: _time.time()}, nx=True)
                added += int(result or 0)
            if cursor == 0:
                break
        total = r.zcard("active_users")
        return {"ok": True, "added": added, "total_in_set": total}
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "trace": traceback.format_exc()[-800:]},
        )
