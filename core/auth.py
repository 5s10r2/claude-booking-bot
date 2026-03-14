"""
core/auth.py — FastAPI security dependencies + CHAT_BASE_URL constant.

Extracted from main.py so all routers can share auth logic without circular imports.
"""

import os

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from config import settings
from core.log import get_logger

logger = get_logger("auth")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

CHAT_BASE_URL = os.getenv("CHAT_BASE_URL", "https://eazypg-chat.vercel.app")


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


async def require_admin_brand_key(api_key: str = Security(_api_key_header)) -> str:
    """Admin auth: validates key has a brand_config entry, returns 16-char brand_hash.

    Every admin endpoint uses this instead of verify_api_key(). The admin frontend
    sends X-API-Key with every request; each brand's unique key (e.g. OxOtel1234)
    scopes that admin to their brand's data only.
    """
    if not api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    from db.redis.brand import _brand_hash, get_brand_config
    bh = _brand_hash(api_key)
    if not get_brand_config(api_key):
        raise HTTPException(status_code=403, detail="No brand configured for this API key")
    return bh
