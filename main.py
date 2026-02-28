"""
Claude Booking Bot — FastAPI Application

Endpoints:
- POST /webhook/whatsapp   — WhatsApp incoming messages
- POST /webhook/payment    — Payment confirmation callback
- POST /chat               — Streamlit / API clients
- POST /chat/stream        — SSE streaming responses
- POST /knowledge-base     — Upload PDFs/QA pairs to FAISS vectorstore
- POST /query              — Query knowledge base
- GET  /health             — Health check
"""

import json
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, Depends, Security
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
from core.ui_parts import generate_ui_parts
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
    store_vectorstore_in_redis,
    get_file_hash,
    set_last_agent,
    save_feedback,
    get_feedback_counts,
    track_funnel,
    get_funnel,
    set_user_language,
    get_user_language,
    track_agent_usage,
    get_agent_usage,
    get_user_memory,
    update_user_memory,
    get_user_phone,
)
from agents import supervisor, default_agent, broker_agent, booking_agent, profile_agent, room_agent
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

    # Step 1: Supervisor routes to agent
    agent_name = await supervisor.route(engine, messages)

    # Safety net: keyword-based override if supervisor misclassifies
    agent_name = apply_keyword_safety_net(agent_name, message, user_id)

    logger.info("user=%s agent=%s lang=%s msg=%s", user_id, agent_name, language, message[:60])

    # Track agent usage for analytics
    track_agent_usage(user_id, agent_name)

    # Step 2: Run selected agent (with language)
    agent_map = {
        "default": default_agent.run,
        "broker": broker_agent.run,
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

async def _route_agent(user_id: str, message: str) -> tuple[str, list[dict], str]:
    """Shared routing logic: returns (agent_name, messages, language).

    Applies supervisor + keyword safety net + last-agent fallback —
    identical to run_pipeline but without running the agent itself.
    """
    # Detect language
    detected_lang = detect_language(message)
    stored_lang = get_user_language(user_id)
    language = detected_lang if detected_lang != "en" else stored_lang
    if detected_lang != "en":
        set_user_language(user_id, detected_lang)

    messages = await conversation.add_user_message_with_summary(user_id, message)

    agent_name = await supervisor.route(engine, messages)

    # Safety net: keyword-based override if supervisor misclassifies
    agent_name = apply_keyword_safety_net(agent_name, message, user_id)

    # Track agent usage for analytics
    track_agent_usage(user_id, agent_name)

    logger.info("user=%s agent=%s lang=%s msg=%s", user_id, agent_name, language, message[:60])
    return agent_name, messages, language


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

    # Route to the correct agent (fast — Haiku + keyword fallback)
    agent_name, messages, language = await _route_agent(req.user_id, req.message)

    # Get agent config (with language for prompt injection)
    config_map = {
        "default": default_agent.get_config,
        "broker": broker_agent.get_config,
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

    # Run pipeline
    try:
        response, agent_name, _lang = await run_pipeline(user_phone, text)
    except Exception as e:
        logger.error("Pipeline error for %s: %s", user_phone, e)
        response = "I'm sorry, I'm having trouble right now. Please try again."
        agent_name = "error"

    delete_active_request(user_phone)

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


@app.post("/knowledge-base", dependencies=[Depends(verify_api_key)])
async def upload_knowledge_base(request: Request):
    """Upload PDFs or QA pairs to create a FAISS vectorstore."""
    try:
        from PyPDF2 import PdfReader
        from langchain_community.vectorstores import FAISS
        from langchain_openai import OpenAIEmbeddings
        from langchain.text_splitter import RecursiveCharacterTextSplitter
    except ImportError:
        raise HTTPException(status_code=500, detail="Knowledge base dependencies not installed")

    form = await request.form()
    files = form.getlist("files")
    qa_data = form.get("qa_data", "")

    if not files and not qa_data:
        raise HTTPException(status_code=400, detail="No files or QA data provided")

    texts = []
    file_datas = []

    # Process PDF files
    for f in files:
        content = await f.read()
        file_datas.append(content)
        try:
            import io
            reader = PdfReader(io.BytesIO(content))
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    texts.append(page_text)
        except Exception as e:
            logger.error("Error reading PDF: %s", e)

    # Process QA data
    if qa_data:
        try:
            qa_pairs = json.loads(qa_data)
            for qa in qa_pairs:
                q = qa.get("question", "")
                a = qa.get("answer", "")
                if q and a:
                    texts.append(f"Q: {q}\nA: {a}")
                    file_datas.append(f"{q}{a}".encode())
        except json.JSONDecodeError:
            texts.append(qa_data)
            file_datas.append(qa_data.encode())

    if not texts:
        raise HTTPException(status_code=400, detail="No extractable text found")

    # Create vectorstore
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = splitter.split_text("\n\n".join(texts))

    embeddings = OpenAIEmbeddings()
    vectorstore = FAISS.from_texts(chunks, embeddings)

    file_hash = get_file_hash(file_datas)
    store_vectorstore_in_redis(file_hash, vectorstore)

    return JSONResponse({
        "status": "ok",
        "file_hash": file_hash,
        "chunks": len(chunks),
    })


@app.post("/query", dependencies=[Depends(verify_api_key)])
async def query_kb(request: Request):
    """Query the knowledge base."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    query = body.get("query", "")
    file_hash = body.get("file_hash", "")
    user_id = body.get("user_id", "anonymous")

    if not query or not file_hash:
        raise HTTPException(status_code=400, detail="query and file_hash are required")

    # Build messages for room agent
    messages = [{"role": "user", "content": query}]
    response = await room_agent.run(engine, messages, user_id, file_hash=file_hash)

    return JSONResponse({"response": response})


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
async def admin_analytics(time_range: str = "7d"):
    """Return aggregated analytics data for the dashboard.

    Query params:
      time_range: "today" | "7d" | "30d"  (default "7d")
    """
    from datetime import date, timedelta

    today = date.today()

    if time_range == "today":
        days = 1
    elif time_range == "30d":
        days = 30
    else:
        days = 7

    # --- Funnel: aggregate across date range ---
    funnel_totals: dict[str, int] = {}
    for i in range(days):
        day = (today - timedelta(days=i)).isoformat()
        day_funnel = get_funnel(day)
        for stage, count in day_funnel.items():
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
        day_agents = get_agent_usage(day)
        for agent, count in day_agents.items():
            agent_totals[agent] = agent_totals.get(agent, 0) + count

    # --- Rate limit status (current snapshot) ---
    from core.rate_limiter import get_rate_limit_status
    rate_limits = {}
    try:
        rate_limits = get_rate_limit_status("__global__")
    except Exception as e:
        logger.warning("rate limit status fetch failed: %s", e)

    return {
        "funnel": funnel_totals,
        "feedback": feedback,
        "messages": message_volume,
        "agents": agent_totals,
        "rate_limits": rate_limits,
        "meta": {
            "range": time_range,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
