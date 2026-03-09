"""
Claude Booking Bot — FastAPI Application (thin factory)

All routes live in routers/. This file only wires up startup/shutdown
and registers the four routers with the app.

Router modules:
  routers/public.py    — GET /health, GET /brand-config
  routers/chat.py      — POST /chat, POST /chat/stream, feedback, funnel, language
  routers/webhooks.py  — GET/POST /webhook/whatsapp, /webhook/payment, /cron/follow-ups
  routers/admin.py     — All /admin/* endpoints, /rate-limit/status
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import core.state as state
from core.claude import AnthropicEngine
from core.conversation import ConversationManager
from core.log import get_logger
from core.rate_limiter import RateLimitExceeded
from core.tool_executor import ToolExecutor
from db import postgres as pg
from routers import admin, chat, public, webhooks
from tools.registry import get_all_handlers, init_registry

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await pg.init_pool()
    await pg.create_property_documents_table()
    await pg.create_leads_table()
    init_registry()

    executor = ToolExecutor()
    executor.register_many(get_all_handlers())

    state.engine = AnthropicEngine(tool_executor=executor)
    state.conversation = ConversationManager()

    logger.info("Claude Booking Bot ready")
    yield

    # Shutdown
    await pg.close_pool()
    logger.info("Pools closed")


app = FastAPI(title="Claude Booking Bot", lifespan=lifespan)


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


app.include_router(public.router)
app.include_router(chat.router)
app.include_router(webhooks.router)
app.include_router(admin.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
