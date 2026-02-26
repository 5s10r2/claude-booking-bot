"""
Claude Booking Bot — FastAPI Application

Endpoints:
- POST /webhook/whatsapp   — WhatsApp incoming messages
- POST /webhook/payment    — Payment confirmation callback
- POST /chat               — Streamlit / API clients
- POST /knowledge-base     — Upload PDFs/QA pairs to FAISS vectorstore
- POST /query              — Query knowledge base
- GET  /health             — Health check
"""

import json
import hashlib
import re
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, Depends, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from core.log import get_logger

logger = get_logger("main")
from pydantic import BaseModel

from config import settings
from core.claude import AnthropicEngine
from core.conversation import ConversationManager
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
    get_last_agent,
    set_last_agent,
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
# Request / Response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    user_id: str
    message: str
    account_values: dict = {}


class ChatResponse(BaseModel):
    response: str
    agent: str = ""


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(user_id: str, message: str) -> tuple[str, str]:
    """Run the full supervisor → agent pipeline. Returns (response, agent_name)."""
    # Load conversation history
    history = conversation.get_history(user_id)
    conversation.add_user_message(user_id, message)

    # Build messages for Claude
    messages = history + [{"role": "user", "content": message}]

    # Step 1: Supervisor routes to agent
    agent_name = await supervisor.route(engine, messages)

    # Safety net: keyword-based override if supervisor misclassifies
    #
    # Design: 3 layers, each more permissive:
    #   Phase 1 — Multi-word phrases (resolve ambiguous words by context)
    #   Phase 2 — Single words (word-boundary matching, not substring)
    #   Phase 3 — Last-agent fallback for continuations
    #
    # Key insight: the same root word can mean different things:
    #   "shortlist this property" (ACTION → broker) vs "show shortlisted" (QUERY → profile)
    #   "schedule a visit" (ACTION → booking) vs "my visits" (QUERY → profile)
    # Phrases in Phase 1 disambiguate; Phase 2 handles the unambiguous remainder.

    msg_lower = message.lower()
    if agent_name == "default":
        # Normalize: strip punctuation so word matching works on "PG!" → "pg"
        msg_clean = re.sub(r"[^\w\s-]", " ", msg_lower)
        words = set(msg_clean.split())

        # --- Phase 1: Multi-word phrases (highest confidence) ---
        # These resolve words that are ambiguous at the single-word level.
        profile_phrases = [
            "my visit", "my visits", "my booking", "my bookings",
            "my schedule", "my event", "my events",
            "my preference", "my preferences", "my profile",
            "shortlisted propert", "saved propert",
            "booking status", "visit status", "scheduled event",
        ]
        broker_phrases = [
            "more about", "tell me about",
            "details of", "details about", "details for",
            "images of", "photos of", "pictures of",
            "far from", "distance from", "distance to",
            "shortlist this", "shortlist the",
        ]
        # (No booking phrases needed — booking actions are unambiguous
        #  at the single-word level: "cancel", "reschedule", "kyc", etc.)

        if any(p in msg_lower for p in profile_phrases):
            agent_name = "profile"
        elif any(p in msg_lower for p in broker_phrases):
            agent_name = "broker"
        else:
            # --- Phase 2: Single-word matching (word boundary, not substring) ---
            # Profile: informational/query words — "show me my X"
            # Note: plurals ("visits", "bookings") imply listing = profile
            profile_words = {
                "profile", "preference", "preferences", "upcoming",
                "events", "visits", "bookings", "shortlisted",
            }
            # Booking: action words — "do X"
            booking_words = {
                "visit", "schedule", "book", "appointment", "call", "video",
                "tour", "payment", "pay", "token", "kyc", "aadhaar", "otp",
                "reserve", "cancel", "reschedule",
            }
            # Broker: property exploration (broadest — checked last)
            broker_words = {
                "find", "search", "looking", "property", "properties",
                "pg", "flat", "apartment", "hostel", "coliving", "co-living",
                "room", "rent", "budget", "area", "location", "available",
                "recommend", "suggest", "bhk", "1bhk", "2bhk", "rk",
                "single", "double", "girls", "boys", "sharing",
                "place", "stay", "accommodation", "housing", "near", "nearby",
                "shortlist", "details", "images", "photos",
                "landmark", "landmarks", "distance", "far",
                # Hindi/Hinglish
                "kamra", "kiraya", "ghar", "chahiye", "dikhao", "jagah", "rehne",
            }

            if words & profile_words:
                agent_name = "profile"
            elif words & booking_words:
                agent_name = "booking"
            elif words & broker_words:
                agent_name = "broker"

    # --- Phase 3: Last-agent fallback for continuations ---
    # Catches affirmatives ("yes", "ok", "haan") and very short follow-ups
    # (≤5 words) that don't contain question/greeting words.
    # Longer follow-ups should be caught by the improved phrase/keyword
    # matching in Phases 1-2 instead.
    if agent_name == "default":
        last = get_last_agent(user_id)
        if last and last != "default":
            affirmatives = {
                "yes", "ok", "okay", "sure", "go ahead", "please",
                "yeah", "yep", "yup", "haan", "ha", "theek hai",
                "kar do", "ho jayega", "confirm", "done", "proceed",
            }
            # Words that signal a NEW intent (not a continuation)
            new_intent_words = {
                "hello", "hi", "hey", "howdy", "namaste",
                "thanks", "thank", "bye", "goodbye",
                "what", "who", "where", "when", "how", "why", "which",
            }
            msg_stripped = msg_lower.strip().rstrip(".!,?")
            is_new_intent = bool(words & new_intent_words)
            if msg_stripped in affirmatives or (len(message.split()) <= 5 and not is_new_intent):
                agent_name = last
                logger.debug("last_agent fallback → %s", last)

    logger.info("user=%s agent=%s msg=%s", user_id, agent_name, message[:60])

    # Step 2: Run selected agent
    agent_map = {
        "default": default_agent.run,
        "broker": broker_agent.run,
        "booking": booking_agent.run,
        "profile": profile_agent.run,
    }

    agent_fn = agent_map.get(agent_name, default_agent.run)
    response = await agent_fn(engine, messages, user_id)

    # Track last active agent for multi-turn continuations
    set_last_agent(user_id, agent_name)

    # Save assistant response to history
    conversation.add_assistant_message(user_id, response)

    return response, agent_name


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

    # Set account values if provided
    if req.account_values:
        set_account_values(req.user_id, req.account_values)
        # Store pg_ids separately (tools read from {user_id}:pg_ids)
        pg_ids = req.account_values.get("pg_ids", [])
        if pg_ids:
            set_whitelabel_pg_ids(req.user_id, pg_ids)

    response, agent_name = await run_pipeline(req.user_id, req.message)

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

    return ChatResponse(response=response, agent=agent_name)


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
        response, agent_name = await run_pipeline(user_phone, text)
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
