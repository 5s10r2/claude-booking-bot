"""
routers/webhooks.py — Webhook and cron endpoints.

Routes:
  GET  /webhook/whatsapp  — Meta webhook verification challenge
  POST /webhook/whatsapp  — Incoming WhatsApp messages
  POST /webhook/payment   — Payment confirmation callback
  POST /cron/follow-ups   — Proactive follow-up processing
"""

import core.state as state
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from config import settings
from core.auth import verify_api_key
from core.log import get_logger
from core.pipeline import run_pipeline
from core.rate_limiter import check_rate_limit, RateLimitExceeded
from channels.whatsapp import send_text, send_carousel, send_images
from db import postgres as pg
from db.redis_store import (
    get_active_request,
    set_active_request,
    delete_active_request,
    get_account_values,
    set_whitelabel_pg_ids,
    set_user_name,
    get_no_message,
    clear_no_message,
    get_brand_wa_config,
    _json_set,
    get_property_template,
    get_property_images_id,
    get_due_followups,
    complete_followup,
    get_user_memory,
    get_conversation,
    save_conversation,
)

logger = get_logger("routers.webhooks")

router = APIRouter()


# ---------------------------------------------------------------------------
# WhatsApp webhook verification (GET — Meta webhook setup)
# ---------------------------------------------------------------------------

@router.get("/webhook/whatsapp")
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
# WhatsApp incoming messages (POST)
# ---------------------------------------------------------------------------

@router.post("/webhook/whatsapp", dependencies=[Depends(verify_api_key)])
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


# ---------------------------------------------------------------------------
# Payment confirmation webhook
# ---------------------------------------------------------------------------

@router.post("/webhook/payment", dependencies=[Depends(verify_api_key)])
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
        # Notify user that payment was confirmed
        notification = "Payment confirmed for your property reservation. Your booking is being processed."
        state.conversation.add_assistant_message(user_id, notification)

        # Send notification via WhatsApp if config exists
        account = get_account_values(user_id)
        if account.get("whatsapp_phone_number_id"):
            await send_text(user_id, notification)

    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Proactive follow-up cron
# ---------------------------------------------------------------------------

@router.post("/cron/follow-ups", dependencies=[Depends(verify_api_key)])
async def process_followups():
    """Process due follow-ups. Call this endpoint via an external cron (every 15 min)."""
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
