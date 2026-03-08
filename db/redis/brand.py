"""
db/redis/brand.py — Multi-tenant brand configuration.

Redis keys:
  brand_config:{sha256(api_key)[:16]}  — full brand config JSON (no TTL)
  brand_wa:{phone_number_id}           — reverse-lookup for WhatsApp webhook (no TTL)
  brand_token:{uuid}                   — public chatbot link token → brand hash (no TTL)

Isolation: raw API key NEVER stored — all reads/writes use _brand_hash(api_key)
as the Redis key prefix.
"""

import hashlib
import json

from db.redis._base import _r, _json_get


def _brand_hash(api_key: str) -> str:
    """16-char prefix of SHA-256(api_key) — never stores the raw key."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def get_brand_config(api_key: str):
    """Return brand config dict for the given API key, or None if not set."""
    return _json_get(f"brand_config:{_brand_hash(api_key)}")


def set_brand_config(api_key: str, config: dict) -> None:
    """Atomically write brand_config, brand_wa reverse-lookup, and brand_token."""
    brand_hash = _brand_hash(api_key)
    config_str = json.dumps(config, default=str)
    pipe = _r().pipeline()
    pipe.set(f"brand_config:{brand_hash}", config_str)
    if config.get("whatsapp_phone_number_id"):
        pipe.set(f"brand_wa:{config['whatsapp_phone_number_id']}", config_str)
    if config.get("brand_link_token"):
        pipe.set(f"brand_token:{config['brand_link_token']}", brand_hash)
    pipe.execute()


def get_brand_wa_config(phone_number_id: str):
    """Return brand config for a given WhatsApp phone_number_id, or None."""
    return _json_get(f"brand_wa:{phone_number_id}")


def get_brand_by_token(token: str):
    """Return brand config for a public link token, or None if not found."""
    brand_hash = _r().get(f"brand_token:{token}")
    if not brand_hash:
        return None
    return _json_get(f"brand_config:{brand_hash.decode()}")
