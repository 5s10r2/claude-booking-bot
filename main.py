"""
Claude Booking Bot — FastAPI Application

Endpoints:
- POST /webhook/whatsapp   — WhatsApp incoming messages
- POST /webhook/payment    — Payment confirmation callback
- POST /chat               — Streamlit / API clients
- POST /chat/stream        — SSE streaming responses
- GET  /health             — Health check
"""

import json
import os
import uuid as uuid_lib
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, Depends, Security, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader

from core.log import get_logger
from core.rate_limiter import check_rate_limit, RateLimitExceeded
from core.language import detect_language
from core.router import apply_keyword_safety_net

logger = get_logger("main")
from pydantic import BaseModel

from config import settings
from core.claude import AnthropicEngine
from core.conversation import ConversationManager
from core.message_parser import parse_message_parts
from core.ui_parts import generate_ui_parts, make_error_part
from core.tool_executor import ToolExecutor
from tools.registry import init_registry, get_all_handlers
from db import postgres as pg
from db.redis_store import (
    get_active_request,
    set_active_request,
    delete_active_request,
    set_account_values,
    get_account_values,
    set_whitelabel_pg_ids,
    set_user_name,
    get_no_message,
    set_no_message,
    clear_no_message,
    set_last_agent,
    save_feedback,
    get_feedback_counts,
    track_funnel,
    get_funnel,
    set_user_language,
    get_user_language,
    track_agent_usage,
    get_agent_usage,
    track_skill_usage,
    get_skill_usage,
    get_skill_misses,
    get_user_memory,
    update_user_memory,
    get_user_phone,
    get_active_users,
    get_active_users_count,
    get_human_mode,
    set_human_mode,
    clear_human_mode,
    get_session_cost,
    get_conversation,
    save_conversation,
    get_preferences,
    get_last_agent,
    get_brand_config,
    set_brand_config,
    get_brand_wa_config,
    get_brand_by_token,
    _json_set,
)
from agents import supervisor, default_agent, broker_agent, booking_agent, profile_agent
from channels.whatsapp import send_text, send_carousel, send_images
from db.redis_store import get_property_template, get_property_images_id

# ---------------------------------------------------------------------------
# API key auth (optional — disabled when API_KEY is unset)
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(_api_key_header)):
    """Dependency that enforces X-API-Key when settings.API_KEY is set."""
    expected = settings.API_KEY
    if not expected:
        return  # auth disabled
    if api_key != expected:
        logger.warning("Rejected request — invalid or missing API key")
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def require_brand_api_key(api_key: str = Security(_api_key_header)) -> str:
    """Brand endpoint auth — any non-empty key is accepted; isolation by hash."""
    if not api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    return api_key


CHAT_BASE_URL = os.getenv("CHAT_BASE_URL", "https://eazypg-chat.vercel.app")


# ---------------------------------------------------------------------------
# Globals (initialised at startup)
# ---------------------------------------------------------------------------
engine: AnthropicEngine = None
conversation: ConversationManager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, conversation

    # Startup
    await pg.init_pool()
    await pg.create_property_documents_table()
    init_registry()

    executor = ToolExecutor()
    executor.register_many(get_all_handlers())

    engine = AnthropicEngine(tool_executor=executor)
    conversation = ConversationManager()

    logger.info("Claude Booking Bot ready")
    yield

    # Shutdown
    await pg.close_pool()
    logger.info("Pools closed")


app = FastAPI(title="Claude Booking Bot", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Rate-limit 429 handler
# ---------------------------------------------------------------------------

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded ({exc.tier}). "
                      f"Try again in {exc.retry_after}s.",
            "retry_after": exc.retry_after,
            "tier": exc.tier,
            "limit": exc.limit,
        },
        headers={"Retry-After": str(exc.retry_after)},
    )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    user_id: str
    message: str
    account_values: dict = {}


class ChatResponse(BaseModel):
    response: str
    agent: str = ""
    parts: list[dict] = []
    locale: str = "en"


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(user_id: str, message: str) -> tuple[str, str, str]:
    """Run the full supervisor → agent pipeline. Returns (response, agent_name, language)."""
    # Human takeover bypass — admin is handling this user manually
    if get_human_mode(user_id):
        from db.redis_store import get_conversation
        conv = get_conversation(user_id)
        conv.append({"role": "user", "content": message})
        save_conversation(user_id, conv)
        return "", "human", get_user_language(user_id) or "en"

    # Update cross-session memory (only bump session_count on first message of a session)
    mem = get_user_memory(user_id)
    updates = {"phone_collected": bool(get_user_phone(user_id))}
    # Conversation history is empty on first message → new session
    from db.redis_store import get_conversation
    if not get_conversation(user_id):
        updates["session_count"] = mem.get("session_count", 0) + 1
    update_user_memory(user_id, **updates)

    # Detect and persist persona from user message (non-blocking)
    from db.redis_store import update_persona
    update_persona(user_id, message)

    # Detect language from message
    detected_lang = detect_language(message)
    stored_lang = get_user_language(user_id)
    language = detected_lang if detected_lang != "en" else stored_lang
    if detected_lang != "en":
        set_user_language(user_id, detected_lang)

    # Load conversation history + summarize if needed
    messages = await conversation.add_user_message_with_summary(user_id, message)

    # SKILL RESOLUTION ORDER (broker agent only):
    # 1. Supervisor LLM classifies → {"agent": str, "skills": list[str]}
    # 2. Keyword safety net overrides agent if LLM misclassifies (e.g. booking
    #    intent mis-routed to broker). If it fires, skills are cleared — they
    #    were computed for the wrong agent.
    # 3. If broker has no skills after step 2, keyword heuristic fills them in
    #    (detect_skills_heuristic). This is the last-resort fallback.
    route_result = await supervisor.route(engine, messages)
    agent_name = route_result["agent"]
    skills = route_result.get("skills", [])

    original_agent = agent_name
    agent_name = apply_keyword_safety_net(agent_name, message, user_id)
    if agent_name != original_agent:
        skills = []  # Safety net fired — skills from wrong agent are invalid

    if agent_name == "broker" and not skills:
        from skills.skill_map import detect_skills_heuristic
        skills = detect_skills_heuristic(message)

    logger.info("user=%s agent=%s lang=%s msg=%s", user_id, agent_name, language, message[:60])

    # Track agent usage + skill usage for analytics
    track_agent_usage(user_id, agent_name)
    if skills:
        track_skill_usage(skills)

    # Step 2: Run selected agent (with language + skills for broker)
    if agent_name == "broker":
        response = await broker_agent.run(engine, messages, user_id, language=language, skills=skills)
    else:
        agent_map = {
            "default": default_agent.run,
            "booking": booking_agent.run,
            "profile": profile_agent.run,
        }
        agent_fn = agent_map.get(agent_name, default_agent.run)
        response = await agent_fn(engine, messages, user_id, language=language)

    # Track last active agent for multi-turn continuations
    set_last_agent(user_id, agent_name)

    # Save assistant response to history
    conversation.add_assistant_message(user_id, response)

    return response, agent_name, language


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(verify_api_key)])
async def chat(req: ChatRequest):
    """JSON API for Streamlit and other clients."""
    if not req.user_id or not req.message:
        raise HTTPException(status_code=400, detail="user_id and message are required")

    check_rate_limit(req.user_id)

    # Set account values if provided
    if req.account_values:
        set_account_values(req.user_id, req.account_values)
        # Store pg_ids separately (tools read from {user_id}:pg_ids)
        pg_ids = req.account_values.get("pg_ids", [])
        if pg_ids:
            set_whitelabel_pg_ids(req.user_id, pg_ids)

    response, agent_name, language = await run_pipeline(req.user_id, req.message)

    # Human mode — AI bypassed; admin is responding manually
    if agent_name == "human":
        return ChatResponse(response="", agent="human", parts=[], locale=language)

    # Persist to Postgres
    pg_ids_list = req.account_values.get("pg_ids", []) if req.account_values else []
    await pg.insert_message(
        thread_id=req.user_id,
        user_phone=req.user_id,
        message_text=req.message,
        message_sent_by=1,
        platform_type="api",
        is_template=False,
        pg_ids=pg_ids_list,
    )
    await pg.insert_message(
        thread_id=req.user_id,
        user_phone=req.user_id,
        message_text=response,
        message_sent_by=2,
        platform_type="api",
        is_template=False,
        pg_ids=pg_ids_list,
    )

    # Parse structured parts for frontend rendering
    try:
        parts = parse_message_parts(response, req.user_id)
    except Exception as e:
        logger.warning("parse_message_parts failed: %s", e)
        parts = [{"type": "text", "markdown": response}]

    # Generate backend-controlled UI parts (chips, buttons)
    try:
        ui_parts = generate_ui_parts(response, agent_name, req.user_id, language)
        parts.extend(ui_parts)
    except Exception as e:
        logger.warning("generate_ui_parts failed: %s", e)

    return ChatResponse(response=response, agent=agent_name, parts=parts, locale=language)


# ---------------------------------------------------------------------------
# SSE streaming endpoint
# ---------------------------------------------------------------------------

async def _route_agent(user_id: str, message: str) -> tuple[str, list[dict], str, list[str]]:
    """Shared routing logic: returns (agent_name, messages, language, skills).

    Applies supervisor + keyword safety net + last-agent fallback + skill detection —
    identical to run_pipeline but without running the agent itself.
    """
    # Detect language
    detected_lang = detect_language(message)
    stored_lang = get_user_language(user_id)
    language = detected_lang if detected_lang != "en" else stored_lang
    if detected_lang != "en":
        set_user_language(user_id, detected_lang)

    messages = await conversation.add_user_message_with_summary(user_id, message)

    route_result = await supervisor.route(engine, messages)
    agent_name = route_result["agent"]
    skills = route_result.get("skills", [])

    # Safety net: keyword-based override if supervisor misclassifies
    original_agent = agent_name
    agent_name = apply_keyword_safety_net(agent_name, message, user_id)
    # If safety net changed the agent, skills are no longer valid
    if agent_name != original_agent:
        skills = []
    # Keyword fallback for broker skill detection
    if agent_name == "broker" and not skills:
        from skills.skill_map import detect_skills_heuristic
        skills = detect_skills_heuristic(message)

    # Track agent usage + skill usage for analytics
    track_agent_usage(user_id, agent_name)
    if skills:
        track_skill_usage(skills)

    logger.info("user=%s agent=%s lang=%s skills=%s msg=%s", user_id, agent_name, language, skills, message[:60])
    return agent_name, messages, language, skills


@app.post("/chat/stream", dependencies=[Depends(verify_api_key)])
async def chat_stream(req: ChatRequest):
    """SSE streaming endpoint — streams agent events as they happen."""
    if not req.user_id or not req.message:
        raise HTTPException(status_code=400, detail="user_id and message are required")

    check_rate_limit(req.user_id)

    if req.account_values:
        set_account_values(req.user_id, req.account_values)
        pg_ids = req.account_values.get("pg_ids", [])
        if pg_ids:
            set_whitelabel_pg_ids(req.user_id, pg_ids)

    # Human takeover bypass — save user message and emit empty stream so admin handles it
    if get_human_mode(req.user_id):
        conv = get_conversation(req.user_id)
        conv.append({"role": "user", "content": req.message})
        save_conversation(req.user_id, conv)
        language = get_user_language(req.user_id) or "en"

        async def _human_stream():
            yield f"event: done\ndata: {json.dumps({'agent': 'human', 'full_response': '', 'parts': [], 'locale': language})}\n\n"

        return StreamingResponse(
            _human_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    # Route to the correct agent (fast — Haiku + keyword fallback + skill detection)
    agent_name, messages, language, skills = await _route_agent(req.user_id, req.message)

    # Get agent config (with language + skills for broker)
    if agent_name == "broker":
        cfg = broker_agent.get_config(req.user_id, language=language, skills=skills)
        await broker_agent._inject_doc_context(cfg)
    else:
        config_map = {
            "default": default_agent.get_config,
            "booking": booking_agent.get_config,
            "profile": profile_agent.get_config,
        }
        get_cfg = config_map.get(agent_name, default_agent.get_config)
        cfg = get_cfg(req.user_id, language=language)

    async def event_generator():
        # Emit agent_start so frontend knows which agent is handling + locale
        yield f"event: agent_start\ndata: {json.dumps({'agent': agent_name, 'locale': language})}\n\n"

        full_text = ""
        try:
            async for ev in engine.run_agent_stream(
                system_prompt=cfg["system_prompt"],
                tools=cfg["tools"],
                messages=messages,
                model=cfg["model"],
                user_id=req.user_id,
                tool_executor=cfg["executor"],
            ):
                yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'])}\n\n"
                if ev["event"] == "content_delta":
                    full_text += ev["data"]["text"]

        except Exception as e:
            logger.error("stream error: %s", e)
            error_msg = "I'm experiencing a temporary issue. Please try again."
            yield f"event: error\ndata: {json.dumps({'text': error_msg})}\n\n"
            full_text = full_text or error_msg
            # Emit error card instead of plain text
            error_part = make_error_part(
                title="Couldn't process your request",
                message="We hit a temporary issue. This usually resolves in a moment.",
                retry_label="Try Again",
                retry_message=req.message,
            )
            error_parts = [error_part]
            yield f"event: done\ndata: {json.dumps({'agent': agent_name or 'system', 'full_response': full_text, 'parts': error_parts, 'locale': language})}\n\n"
            # Persist and return
            set_last_agent(req.user_id, agent_name or "system")
            conversation.add_assistant_message(req.user_id, full_text)
            pg_ids_list = req.account_values.get("pg_ids", []) if req.account_values else []
            await pg.insert_message(thread_id=req.user_id, user_phone=req.user_id, message_text=req.message, message_sent_by=1, platform_type="api", is_template=False, pg_ids=pg_ids_list)
            await pg.insert_message(thread_id=req.user_id, user_phone=req.user_id, message_text=full_text, message_sent_by=2, platform_type="api", is_template=False, pg_ids=pg_ids_list)
            return

        # Parse structured parts for frontend rendering
        try:
            parts = parse_message_parts(full_text, req.user_id)
        except Exception as e:
            logger.warning("parse_message_parts failed: %s", e)
            parts = [{"type": "text", "markdown": full_text}]

        # Generate backend-controlled UI parts (chips, buttons)
        try:
            ui_parts = generate_ui_parts(full_text, agent_name, req.user_id, language)
            parts.extend(ui_parts)
        except Exception as e:
            logger.warning("generate_ui_parts failed: %s", e)

        # Emit final done event with the full assembled response + parts + locale
        yield f"event: done\ndata: {json.dumps({'agent': agent_name, 'full_response': full_text, 'parts': parts, 'locale': language})}\n\n"

        # Persist state (same as non-streaming path)
        set_last_agent(req.user_id, agent_name)
        conversation.add_assistant_message(req.user_id, full_text)

        pg_ids_list = req.account_values.get("pg_ids", []) if req.account_values else []
        await pg.insert_message(
            thread_id=req.user_id, user_phone=req.user_id,
            message_text=req.message, message_sent_by=1,
            platform_type="api", is_template=False, pg_ids=pg_ids_list,
        )
        await pg.insert_message(
            thread_id=req.user_id, user_phone=req.user_id,
            message_text=full_text, message_sent_by=2,
            platform_type="api", is_template=False, pg_ids=pg_ids_list,
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable Nginx buffering on Render
        },
    )


@app.post("/webhook/whatsapp", dependencies=[Depends(verify_api_key)])
async def whatsapp_webhook(request: Request):
    """Handle incoming WhatsApp messages (Meta + Interakt webhook)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "invalid json"}, status_code=400)

    # Extract message data from webhook payload
    entry = body.get("entry", [{}])
    if not entry:
        return JSONResponse({"status": "no entry"})

    changes = entry[0].get("changes", [{}])
    if not changes:
        return JSONResponse({"status": "no changes"})

    value = changes[0].get("value", {})
    messages = value.get("messages", [])
    contacts = value.get("contacts", [])

    if not messages:
        return JSONResponse({"status": "no messages"})

    msg = messages[0]
    msg_type = msg.get("type", "")

    # Only handle text messages
    if msg_type != "text":
        return JSONResponse({"status": "ignored", "type": msg_type})

    user_phone = msg.get("from", "")
    text = msg.get("text", {}).get("body", "").strip()
    wamid = msg.get("id", "")

    if not user_phone or not text:
        return JSONResponse({"status": "empty message"})

    # Rate limiting — protect against WhatsApp message floods
    try:
        check_rate_limit(user_phone)
    except RateLimitExceeded as e:
        logger.warning("WhatsApp rate limited: user=%s tier=%s", user_phone, e.tier)
        return JSONResponse({"status": "rate_limited", "retry_after": e.retry_after})

    # Dedup: skip if same message within 30s
    active = get_active_request(user_phone)
    if active == text:
        return JSONResponse({"status": "duplicate"})
    set_active_request(user_phone, text)

    # Store contact name
    if contacts:
        name = contacts[0].get("profile", {}).get("name", "")
        if name:
            set_user_name(user_phone, name)

    # Extract account context from query params or headers
    account_id = request.query_params.get("account_id", "")
    pg_ids = request.query_params.get("pg_ids", "")
    if pg_ids:
        set_whitelabel_pg_ids(user_phone, pg_ids.split(","))

    # Persist incoming message
    pg_ids_val = request.query_params.get("pg_ids", "")
    await pg.insert_message(
        thread_id=user_phone,
        user_phone=user_phone,
        message_text=text,
        message_sent_by=1,
        platform_type="whatsapp",
        is_template=False,
        pg_ids=pg_ids_val,
    )

    # Hydrate brand config from WhatsApp phone_number_id
    # value is already extracted above; metadata.phone_number_id identifies the brand
    phone_number_id = value.get("metadata", {}).get("phone_number_id")
    if phone_number_id:
        brand_cfg = get_brand_wa_config(phone_number_id)
        if brand_cfg:
            hydrated = {
                "pg_ids": brand_cfg.get("pg_ids", []),
                "whatsapp_phone_number_id": brand_cfg.get("whatsapp_phone_number_id", ""),
                "whatsapp_access_token": brand_cfg.get("whatsapp_access_token", ""),
                "waba_id": brand_cfg.get("waba_id", ""),
                "is_meta": brand_cfg.get("is_meta", True),
                "brand_name": brand_cfg.get("brand_name", ""),
            }
            # Write with 1-hour TTL so stale creds don't linger
            _json_set(f"{user_phone}:account_values", hydrated, ex=3600)

    # Run pipeline
    try:
        response, agent_name, _lang = await run_pipeline(user_phone, text)
    except Exception as e:
        logger.error("Pipeline error for %s: %s", user_phone, e)
        response = "I'm sorry, I'm having trouble right now. Please try again."
        agent_name = "error"

    delete_active_request(user_phone)

    # Human mode — pipeline saved the user message; admin is responding manually, skip all outbound sends
    if agent_name == "human":
        return JSONResponse({"status": "ok", "agent": "human", "human_mode": True})

    # Check if we should skip sending (no_message flag)
    if get_no_message(user_phone) == "1":
        clear_no_message(user_phone)
        return JSONResponse({"status": "ok", "agent": agent_name, "no_message": True})

    # Send response via WhatsApp
    await send_text(user_phone, response)

    # Send property carousel if available
    template = get_property_template(user_phone)
    if template:
        await send_carousel(user_phone, template)

    # Send property images if available
    images = get_property_images_id(user_phone)
    if images:
        await send_images(user_phone, images)

    return JSONResponse({"status": "ok", "agent": agent_name})


@app.post("/webhook/payment", dependencies=[Depends(verify_api_key)])
async def payment_webhook(request: Request):
    """Handle payment confirmation callback from Rentok."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "invalid json"}, status_code=400)

    user_id = body.get("user_id", "")
    pg_id = body.get("pg_id", "")
    pg_number = body.get("pg_number", "")
    status = body.get("status", "")

    if not user_id:
        return JSONResponse({"status": "missing user_id"}, status_code=400)

    if status == "success":
        # Run verify_payment for the user
        notification = f"Payment confirmed for your property reservation. Your booking is being processed."
        conversation.add_assistant_message(user_id, notification)

        # Send notification via WhatsApp if config exists
        account = get_account_values(user_id)
        if account.get("whatsapp_phone_number_id"):
            await send_text(user_id, notification)

    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    user_id: str
    message_snippet: str = ""
    rating: str  # "up" or "down"
    agent: str = ""


@app.post("/feedback", dependencies=[Depends(verify_api_key)])
async def submit_feedback(req: FeedbackRequest):
    """Record thumbs-up / thumbs-down feedback on a bot response."""
    if req.rating not in ("up", "down"):
        raise HTTPException(status_code=400, detail="rating must be 'up' or 'down'")
    save_feedback(req.user_id, req.message_snippet, req.rating, req.agent)
    return {"status": "ok"}


@app.get("/feedback/stats", dependencies=[Depends(verify_api_key)])
async def feedback_stats():
    """Return aggregate feedback counters."""
    return get_feedback_counts()


# ---------------------------------------------------------------------------
# Funnel tracking
# ---------------------------------------------------------------------------

@app.get("/funnel", dependencies=[Depends(verify_api_key)])
async def funnel_stats(day: str = None):
    """Return funnel stage counts for a given day (default: today)."""
    return get_funnel(day)


# ---------------------------------------------------------------------------
# Rate-limit status (admin / monitoring)
# ---------------------------------------------------------------------------

@app.get("/rate-limit/status", dependencies=[Depends(verify_api_key)])
async def rate_limit_status(user_id: str):
    """Show current rate-limit usage for a given user."""
    from core.rate_limiter import get_rate_limit_status
    return get_rate_limit_status(user_id)


# ---------------------------------------------------------------------------
# WhatsApp webhook verification (GET for Meta webhook setup)
# ---------------------------------------------------------------------------

@app.get("/webhook/whatsapp")
async def verify_whatsapp_webhook(request: Request):
    """Meta webhook verification challenge."""
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")

    verify_token = settings.WHATSAPP_VERIFY_TOKEN if hasattr(settings, "WHATSAPP_VERIFY_TOKEN") else "booking-bot-verify"

    if mode == "subscribe" and token == verify_token:
        return int(challenge) if challenge else ""

    raise HTTPException(status_code=403, detail="Verification failed")


# ---------------------------------------------------------------------------
# Language preference (explicit override from frontend)
# ---------------------------------------------------------------------------

class LanguageRequest(BaseModel):
    user_id: str
    language: str  # "en", "hi", or "mr"


@app.post("/language", dependencies=[Depends(verify_api_key)])
async def set_language(req: LanguageRequest):
    """Allow the frontend to explicitly set the user's preferred language."""
    if req.language not in ("en", "hi", "mr"):
        raise HTTPException(status_code=400, detail="language must be 'en', 'hi', or 'mr'")
    set_user_language(req.user_id, req.language)
    return {"status": "ok", "language": req.language}


# ---------------------------------------------------------------------------
# Admin analytics
# ---------------------------------------------------------------------------

@app.get("/admin/analytics", dependencies=[Depends(verify_api_key)])
async def admin_analytics(days: int = 7):
    """Return aggregated analytics data for the dashboard.

    Query params:
      days: integer number of days to look back (default 7, max 90)
    """
    from datetime import date, timedelta

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
# Proactive follow-up cron
# ---------------------------------------------------------------------------

@app.post("/cron/follow-ups", dependencies=[Depends(verify_api_key)])
async def process_followups():
    """Process due follow-ups. Call this endpoint via an external cron (every 15 min)."""
    from db.redis_store import get_due_followups, complete_followup, get_user_memory

    followups = get_due_followups(limit=50)
    processed = 0
    errors = 0

    for entry in followups:
        user_id = entry.get("user_id", "")
        ftype = entry.get("type", "")
        data = entry.get("data", {})
        raw = entry.get("_raw")

        if not user_id:
            complete_followup(raw)
            continue

        prop_name = data.get("property_name", "your shortlisted property")

        try:
            if ftype == "visit_complete":
                message = (
                    f"Hey! How was your visit to {prop_name}? 🏠\n\n"
                    "Quick feedback:\n"
                    "1️⃣ Loved it — I want to book!\n"
                    "2️⃣ It was okay\n"
                    "3️⃣ Not for me\n\n"
                    "Just reply with 1, 2, or 3 and I'll take it from there!"
                )
            elif ftype == "payment_pending":
                link = data.get("link", "")
                amount = data.get("amount", "")
                message = (
                    f"Just a friendly reminder — your payment link for {prop_name} "
                    f"is still active (₹{amount}).\n\n"
                    f"{link}\n\n"
                    "Complete it to lock in your reservation. "
                    "Let me know if you have any questions!"
                )
            elif ftype == "shortlist_idle":
                mem = get_user_memory(user_id)
                n_shortlisted = len(mem.get("properties_shortlisted", []))
                message = (
                    f"Hey! You shortlisted {prop_name} a couple of days ago. "
                    f"Still interested? 🤔\n\n"
                )
                if n_shortlisted > 1:
                    message += (
                        f"You have {n_shortlisted} properties shortlisted. "
                        "Want me to compare them or schedule a visit to your top pick?"
                    )
                else:
                    message += (
                        "Want me to show you more details, schedule a visit, "
                        "or look for other options nearby?"
                    )
            else:
                complete_followup(raw)
                continue

            # Send via appropriate channel
            # Check if user is a WhatsApp user (phone-based ID)
            if user_id.isdigit() and 10 <= len(user_id) <= 13:
                account = get_account_values(user_id)
                if account.get("whatsapp_phone_number_id"):
                    await send_text(user_id, message)
                    processed += 1
                else:
                    logger.info("follow-up skipped (no WA config): user=%s type=%s", user_id, ftype)
            else:
                # Web chat user — store message for next session retrieval
                from db.redis_store import save_conversation, get_conversation
                conv = get_conversation(user_id)
                conv.append({"role": "assistant", "content": f"[FOLLOW_UP] {message}"})
                save_conversation(user_id, conv)
                processed += 1

            complete_followup(raw)

        except Exception as e:
            logger.error("follow-up processing failed: user=%s type=%s error=%s", user_id, ftype, e)
            errors += 1
            # Don't remove — will be retried on next cron run

    return {
        "status": "ok",
        "processed": processed,
        "errors": errors,
        "pending": len(followups) - processed - errors,
    }


# ---------------------------------------------------------------------------
# Admin — conversation browser
# ---------------------------------------------------------------------------

@app.get("/admin/conversations", dependencies=[Depends(verify_api_key)])
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


@app.get("/admin/conversations/{uid}", dependencies=[Depends(verify_api_key)])
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


@app.post("/admin/conversations/{uid}/takeover", dependencies=[Depends(verify_api_key)])
async def admin_takeover(uid: str):
    """Activate human takeover — AI stops responding for this user."""
    set_human_mode(uid)
    return {"ok": True}


@app.post("/admin/conversations/{uid}/resume", dependencies=[Depends(verify_api_key)])
async def admin_resume(uid: str):
    """Deactivate human takeover — AI resumes handling this user."""
    clear_human_mode(uid)
    return {"ok": True}


@app.post("/admin/conversations/{uid}/message", dependencies=[Depends(verify_api_key)])
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
# Admin — command center (Sprint 3)
# ---------------------------------------------------------------------------

@app.get("/admin/command-center", dependencies=[Depends(verify_api_key)])
async def admin_command_center():
    """Today's at-a-glance stats for the command center home screen."""
    from datetime import date
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
            "messages":          msg_count,
            "new_leads":         day_funnel.get("searching", 0),
            "visits_scheduled":  day_funnel.get("visit_scheduled", 0),
            "booked":            day_funnel.get("booked", 0),
        },
        "funnel": day_funnel,
        "agents": day_agents,
        "active_conversations": get_active_users_count(),
        "human_mode_count":     human_count,
        "generated_at":         datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Admin — leads (Sprint 4)
# ---------------------------------------------------------------------------

@app.get("/admin/leads", dependencies=[Depends(verify_api_key)])
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
    import time as _time
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


def _r_score(uid: str):
    """Helper — get uid score from active_users sorted set."""
    try:
        from db.redis_store import _r
        score = _r().zscore("active_users", uid)
        return float(score) if score is not None else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Admin — feature flags (Sprint 3)
# ---------------------------------------------------------------------------

@app.get("/admin/flags", dependencies=[Depends(verify_api_key)])
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


@app.post("/admin/flags", dependencies=[Depends(verify_api_key)])
async def admin_set_flags(req: FlagUpdateRequest):
    """Update runtime feature flags (in-memory only; restart resets to env values)."""
    if req.DYNAMIC_SKILLS_ENABLED is not None:
        settings.DYNAMIC_SKILLS_ENABLED = req.DYNAMIC_SKILLS_ENABLED
    if req.KYC_ENABLED is not None:
        settings.KYC_ENABLED = req.KYC_ENABLED
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin — brand configuration (multi-tenant white-label)
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


@app.get("/admin/brand-config")
async def admin_get_brand_config(api_key: str = Depends(require_brand_api_key)):
    """Return brand config for the given API key. Access token is masked."""
    config = dict(get_brand_config(api_key) or {})
    token = config.get("whatsapp_access_token", "")
    if token:
        config["whatsapp_access_token"] = "••••" + token[-4:]
    link_token = config.get("brand_link_token", "")
    chatbot_url = f"{CHAT_BASE_URL}?brand={link_token}" if link_token else None
    return {"is_configured": bool(config.get("pg_ids")), "chatbot_url": chatbot_url, **config}


@app.post("/admin/brand-config")
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


# PUBLIC endpoint — no auth — used by eazypg-chat to load brand config at startup
@app.get("/brand-config")
async def get_public_brand_config(token: str):
    """Return public brand fields for a chatbot link token. No credentials exposed."""
    config = get_brand_by_token(token)
    if not config:
        raise HTTPException(status_code=404, detail="Brand not found")
    return {
        "pg_ids": config.get("pg_ids", []),
        "brand_name": config.get("brand_name", ""),
        "cities": config.get("cities", ""),
        "areas": config.get("areas", ""),
        "is_configured": bool(config.get("pg_ids")),
    }


# ---------------------------------------------------------------------------
# Admin — broadcast (Sprint 3)
# ---------------------------------------------------------------------------

class BroadcastRequest(BaseModel):
    message: str


@app.post("/admin/broadcast", dependencies=[Depends(verify_api_key)])
async def admin_broadcast(req: BroadcastRequest):
    """Send a text message to all users active in the last 7 days."""
    import time as _time
    cutoff = _time.time() - 7 * 86400
    uids = get_active_users(offset=0, limit=500)

    sent = 0
    for uid in uids:
        try:
            from db.redis_store import _r
            score = _r().zscore("active_users", uid)
            if score and float(score) < cutoff:
                continue
            await send_text(uid, req.message)
            sent += 1
        except Exception as e:
            logger.warning("broadcast to %s failed: %s", uid, e)

    return {"ok": True, "sent": sent}


# ---------------------------------------------------------------------------
# Admin — property documents (Sprint 5)
# ---------------------------------------------------------------------------

@app.get("/admin/properties", dependencies=[Depends(verify_api_key)])
async def admin_list_properties():
    """Return all known properties (from Redis property_info_map cache)."""
    try:
        from db.redis_store import _r
        raw = _r().get("property_info_map")
        if not raw:
            return {"properties": []}
        import json as _json_local
        prop_map = _json_local.loads(raw)
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


@app.get("/admin/properties/{prop_id}/documents", dependencies=[Depends(verify_api_key)])
async def admin_get_documents(prop_id: str):
    """Return document metadata for a property."""
    docs = await pg.get_property_documents(prop_id)
    return {"documents": docs}


class UploadDocResponse(BaseModel):
    id: int
    filename: str
    size_bytes: int
    uploaded_at: str


@app.post("/admin/properties/{prop_id}/documents", dependencies=[Depends(verify_api_key)])
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


@app.delete("/admin/properties/{prop_id}/documents/{doc_id}", dependencies=[Depends(verify_api_key)])
async def admin_delete_document(prop_id: str, doc_id: int):
    """Delete a property document."""
    deleted = await pg.delete_property_document(prop_id, doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


@app.post("/admin/backfill-users", dependencies=[Depends(verify_api_key)])
async def admin_backfill_users():
    """One-time backfill: populate active_users sorted set from existing conversation keys.

    Safe to call multiple times — ZADD NX only adds entries that don't exist yet.
    Returns count of users added.
    """
    import time as _time
    import traceback
    try:
        from db.redis_store import _r
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
        return JSONResponse(status_code=500, content={"error": str(exc), "trace": traceback.format_exc()[-800:]})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
