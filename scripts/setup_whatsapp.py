#!/usr/bin/env python3
"""
Configure WhatsApp brand credentials and run sanity checks.

Interakt (default for this deployment):
  python scripts/setup_whatsapp.py --interakt --backend https://claude-booking-bot.onrender.com --api-key OxOtel1234

Meta Graph API:
  export WHATSAPP_ACCESS_TOKEN="EAA..."
  python scripts/setup_whatsapp.py --meta --backend https://claude-booking-bot.onrender.com --api-key OxOtel1234

Reads INTERAKT_ACCESS_TOKEN / WHATSAPP_ACCESS_TOKEN from .env when not set in the shell.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_PHONE_NUMBER_ID = "643690922154797"
DEFAULT_WABA_ID = "1750554065865807"
DEFAULT_PG_ID = "dxgQszaNRgfnslUGJR4AWKFU8Hl1"


def _load_env_file(env_path: Path) -> dict[str, str]:
    """Parse .env lines; tolerates spaces around '='."""
    out: dict[str, str] = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def _get(url: str, api_key: str) -> dict:
    req = urllib.request.Request(url, headers={"X-API-Key": api_key})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _post(url: str, api_key: str, body: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def main() -> int:
    parser = argparse.ArgumentParser(description="WhatsApp brand setup + webhook smoke test")
    parser.add_argument("--backend", default=os.getenv("BACKEND_URL", "https://claude-booking-bot.onrender.com"))
    parser.add_argument("--api-key", default=os.getenv("BRAND_API_KEY", "OxOtel1234"))
    parser.add_argument("--phone-number-id", default=DEFAULT_PHONE_NUMBER_ID)
    parser.add_argument("--waba-id", default=DEFAULT_WABA_ID)
    parser.add_argument("--pg-id", default=DEFAULT_PG_ID)
    parser.add_argument("--verify-token", default=os.getenv("WHATSAPP_VERIFY_TOKEN", "booking-bot-verify"))
    parser.add_argument("--app-secret", default=os.getenv("WHATSAPP_APP_SECRET", ""))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--interakt", action="store_true", help="Use Interakt API (is_meta=false)")
    mode.add_argument("--meta", action="store_true", help="Use Meta Graph API (is_meta=true)")
    parser.add_argument("--skip-webhook-test", action="store_true")
    args = parser.parse_args()

    env_vars = _load_env_file(Path(__file__).resolve().parents[1] / ".env")
    use_interakt = args.interakt or (not args.meta and bool(env_vars.get("INTERAKT_ACCESS_TOKEN")))

    if use_interakt:
        access_token = (
            os.getenv("INTERAKT_ACCESS_TOKEN", "").strip()
            or env_vars.get("INTERAKT_ACCESS_TOKEN", "").strip()
        )
        provider = "Interakt"
    else:
        access_token = (
            os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
            or env_vars.get("WHATSAPP_ACCESS_TOKEN", "").strip()
        )
        provider = "Meta"

    backend = args.backend.rstrip("/")
    brand_url = f"{backend}/admin/brand-config"
    webhook_url = f"{backend}/webhook/whatsapp"

    print(f"Backend:  {backend}")
    print(f"Provider: {provider} (is_meta={not use_interakt})")
    print(f"API key:  {args.api_key[:4]}…")

    try:
        existing = _get(brand_url, args.api_key)
    except urllib.error.HTTPError as e:
        print(f"ERROR: GET brand-config failed ({e.code}): {e.read().decode()}", file=sys.stderr)
        return 1

    pg_ids = list(existing.get("pg_ids") or [])
    if args.pg_id not in pg_ids:
        pg_ids.insert(0, args.pg_id)

    payload: dict = {
        "whatsapp_phone_number_id": args.phone_number_id,
        "waba_id": args.waba_id,
        "is_meta": not use_interakt,
        "pg_ids": pg_ids,
    }
    if access_token:
        payload["whatsapp_access_token"] = access_token

    try:
        result = _post(brand_url, args.api_key, payload)
        print("Brand config updated:", json.dumps(result, indent=2))
    except urllib.error.HTTPError as e:
        print(f"ERROR: POST brand-config failed ({e.code}): {e.read().decode()}", file=sys.stderr)
        return 1

    cfg = _get(brand_url, args.api_key)
    print("\n--- Brand config ---")
    print(f"  is_meta:         {cfg.get('is_meta', True)}")
    print(f"  phone_number_id: {cfg.get('whatsapp_phone_number_id')}")
    print(f"  waba_id:         {cfg.get('waba_id')}")
    print(f"  access_token:    {'set' if cfg.get('whatsapp_access_token') else 'MISSING — bot cannot reply on WhatsApp'}")
    print(f"  pg_ids (first):  {(cfg.get('pg_ids') or [''])[0]}")

    if not access_token:
        key_name = "INTERAKT_ACCESS_TOKEN" if use_interakt else "WHATSAPP_ACCESS_TOKEN"
        print(f"\n⚠️  Set {key_name} in .env or env, then re-run.")

    challenge = "setup-whatsapp-test"
    verify_url = (
        f"{webhook_url}?hub.mode=subscribe"
        f"&hub.verify_token={urllib.parse.quote(args.verify_token)}"
        f"&hub.challenge={challenge}"
    )
    try:
        req = urllib.request.Request(verify_url)
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode()
        ok = body.strip() == challenge
        print(f"\nWebhook verify (GET): {'OK' if ok else 'FAIL'} → {body[:80]!r}")
    except Exception as e:
        print(f"\nWebhook verify (GET): FAIL — {e}")

    if args.skip_webhook_test or not args.app_secret:
        if not args.app_secret:
            print("\nSkipping signed POST test (WHATSAPP_APP_SECRET not set).")
        return 0

    test_phone = "919892462013"
    body_obj = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": args.phone_number_id},
                    "contacts": [{"profile": {"name": "Test User"}, "wa_id": test_phone}],
                    "messages": [{
                        "from": test_phone,
                        "id": f"wamid.setup.{hashlib.sha256(test_phone.encode()).hexdigest()[:16]}",
                        "timestamp": "1710000000",
                        "type": "text",
                        "text": {"body": "Hi, show me PG options"},
                    }],
                },
            }],
        }],
    }
    raw = json.dumps(body_obj, separators=(",", ":")).encode()
    sig = _sign(args.app_secret, raw)
    req = urllib.request.Request(
        webhook_url,
        data=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            out = resp.read().decode()
        print(f"\nWebhook simulate (POST): {resp.status} → {out}")
    except urllib.error.HTTPError as e:
        print(f"\nWebhook simulate (POST): FAIL {e.code} → {e.read().decode()}", file=sys.stderr)
        return 1

    print("\nDone. Send a WhatsApp message to +91 9892462013 to test end-to-end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
