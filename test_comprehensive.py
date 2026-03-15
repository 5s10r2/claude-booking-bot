#!/usr/bin/env python3
"""
test_comprehensive.py — 16-tool live API regression suite

Tests all broker, brand, profile, and booking tool functions against
the real OxOtel RentOK instance with real Redis and real HTTP calls.

Usage:
    cd /path/to/claude-booking-bot
    python test_comprehensive.py

Results: PASS / WARN (pre-declared expected partial) / FAIL (unexpected)
Target:  ≥14/16 PASS
"""

import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx

from config import settings

# ── Test identity ──────────────────────────────────────────────────────────────
UID   = "test_comp_2026"
PHONE = "9773510154"
NAME  = "sanchay bb test 1"

OXOTEL_PG_IDS = [
    "l5zf3ckOnRQV9OHdv5YTTXkvLHp1",
    "egu5HmrYFMP8MRJyMsefnpaL7ka2",
    "Z2wyLOXXp5QA596DQ6aZAQpakmQ2",
    "UaDCGP3dzzZRgVIzBDgXb5ry5ng2",
    "EqhTMiUNksgXh5QhGQRsY5DQiO42",
    "fzDBxYtHgVV21ertfkUdSHeomiv2",
    "CUxtdeaGxYS8IMXmGZ1yUnqyfOn2",
    "wtlUSKV9H8bkNqvlGmnogwoqwyk2",
    "1Dy0t6YeIHh3kQhqvQR8tssHWKt1",
    "U2uYCaeiCebrE95iUDsS4PwEd1J2",
]

# ── Result tracking ────────────────────────────────────────────────────────────
RESULTS: list[tuple[str, str, str]] = []  # (label, status, preview)


def record(label: str, result: str, warn: bool = False, expect_contains: str | None = None) -> None:
    """Evaluate result and record PASS / WARN / FAIL."""
    preview = (result or "<empty>")[:250].replace("\n", " | ")

    if expect_contains:
        if expect_contains.lower() in result.lower():
            status = "PASS"
        else:
            status = "FAIL"
            preview += f"  ← expected '{expect_contains}'"
    elif not result or result.lower().startswith("error") or result.lower().startswith("property id not"):
        status = "WARN" if warn else "FAIL"
    elif result.startswith("No ") or result.startswith("Unable"):
        status = "WARN" if warn else "FAIL"
    else:
        status = "PASS"

    RESULTS.append((label, status, preview))
    icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}[status]
    print(f"\n{icon} [{label}] {status}")
    print(f"   → {preview}")


# ── Phase 0: Discovery + Redis seed ──────────────────────────────────────────
async def phase0_discover_and_seed() -> list[dict]:
    """Fetch live OxOtel properties, build INFO_MAP, seed Redis."""
    print("\n" + "=" * 64)
    print("PHASE 0: Live property discovery + Redis seed")
    print("=" * 64)
    print(f"  Endpoint: {settings.RENTOK_API_BASE_URL}/bookingBot/fetch-all-properties")

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{settings.RENTOK_API_BASE_URL}/bookingBot/fetch-all-properties",
            json={"pg_ids": OXOTEL_PG_IDS},
        )
        resp.raise_for_status()
        raw = resp.json()

    properties = raw.get("data", raw.get("properties", []))
    if not properties:
        print("❌ fetch-all-properties returned no data — aborting")
        sys.exit(1)

    print(f"  Found {len(properties)} properties total")

    # Debug: show raw field names of first property
    first = properties[0]
    print(f"  Raw keys (first property): {list(first.keys())[:25]}")
    print(f"  pg_name  : {first.get('pg_name', first.get('property_name', '???'))}")
    print(f"  id (UUID): {first.get('id', '???')}")
    print(f"  pg_id    : {first.get('pg_id', '???')}")
    print(f"  eazypg_id: {first.get('eazypg_id', '???')}")
    print(f"  pg_number: {first.get('pg_number', '???')}")
    lat_val = first.get("latitude") or first.get("lat") or "???"
    lng_val = first.get("longitude") or first.get("lng") or "???"
    print(f"  lat/lng  : {lat_val} / {lng_val}")

    # Build info_map from first 2 properties that have a UUID
    info_map: list[dict] = []
    for p in properties:
        prop_id = p.get("id", "") or p.get("p_id", "")
        if not prop_id:
            continue
        name = (p.get("pg_name") or p.get("property_name") or p.get("name") or "Unknown").strip()
        lat = float(p.get("latitude") or p.get("lat") or 0.0)
        lng = float(p.get("longitude") or p.get("lng") or 0.0)
        info_map.append({
            "property_name":   name,
            "prop_id":         prop_id,                                       # UUID → property_details
            "property_id":     prop_id,                                       # alias
            "pg_id":           p.get("pg_id", ""),                           # Firebase UID → images
            "eazypg_id":       p.get("eazypg_id", ""),                      # → room_details
            "pg_number":       p.get("pg_number", ""),                       # → images
            "lat":             lat,
            "lng":             lng,
            "property_location": (
                p.get("address_line_1") or p.get("location") or p.get("area", "Mumbai")
            ),
            "property_link":   p.get("microsite_link", ""),
            "property_rent":   p.get("rent_starts_from") or p.get("rent", ""),
        })
        if len(info_map) == 2:
            break

    if not info_map:
        print("❌ No properties with UUID found — aborting")
        sys.exit(1)
    if len(info_map) < 2:
        print("⚠️  Only 1 property with UUID — compare test will use same property twice")
        info_map.append(dict(info_map[0]))  # duplicate for compare

    # Seed Redis with real data
    from db.redis_store import (
        set_property_info_map,
        save_preferences,
        set_user_phone,
        record_property_shortlisted,
    )
    set_property_info_map(UID, info_map)
    set_user_phone(UID, PHONE)
    save_preferences(
        UID,
        {"location": "Rabale", "city": "Mumbai", "max_budget": "15000"},
        profile_name=NAME,
    )
    record_property_shortlisted(UID, info_map[0]["prop_id"])

    print(f"\n  ✅ Redis seeded — user: {UID}")
    print(f"     PROP1: {info_map[0]['property_name']} (uuid={info_map[0]['prop_id'][:8]}…)")
    print(f"     PROP2: {info_map[1]['property_name']} (uuid={info_map[1]['prop_id'][:8]}…)")
    print(f"     Phone: {PHONE} | Name: {NAME}")

    return info_map


# ── Block A — Brand Tools ─────────────────────────────────────────────────────
async def block_a(info_map: list[dict]) -> None:
    from tools.default.brand_info import brand_info
    from tools.broker.query_properties import fetch_properties_by_query

    print("\n\n" + "=" * 64)
    print("BLOCK A — Brand Tools")
    print("=" * 64)

    # A1: brand_info — mock only get_whitelabel_pg_ids (brand config, not user Redis)
    with patch("tools.default.brand_info.get_whitelabel_pg_ids", return_value=OXOTEL_PG_IDS):
        result = await brand_info(UID)
    record("A1 brand_info", result)

    # A2: fetch_properties_by_query — same mock
    with patch("tools.broker.query_properties.get_whitelabel_pg_ids", return_value=OXOTEL_PG_IDS):
        result = await fetch_properties_by_query(UID, query="Rabale")
    record("A2 fetch_properties_by_query", result)


# ── Block B — Broker Tools ────────────────────────────────────────────────────
async def block_b(info_map: list[dict]) -> None:
    from tools.broker.property_details import fetch_property_details
    from tools.broker.room_details import fetch_room_details
    from tools.broker.images import fetch_property_images
    from tools.broker.compare import compare_properties
    from tools.broker.landmarks import fetch_landmarks
    from tools.broker.nearby_places import fetch_nearby_places
    from tools.broker.shortlist import shortlist_property

    PROP1 = info_map[0]["property_name"]
    PROP2 = info_map[1]["property_name"]

    print("\n\n" + "=" * 64)
    print("BLOCK B — Broker Tools")
    print("=" * 64)
    print(f"  PROP1: {PROP1}")
    print(f"  PROP2: {PROP2}")

    # B1: fetch_property_details — real API /property/property-details-bots
    result = await fetch_property_details(UID, PROP1)
    record("B1 fetch_property_details", result)

    # B2: fetch_room_details — /bookingBot/getAvailableRoomFromEazyPGID
    #     WARN expected: OxOtel instance returns 404 for this endpoint
    result = await fetch_room_details(UID, PROP1)
    record("B2 fetch_room_details", result, warn=True)

    # B3: fetch_property_images — /bookingBot/fetchPropertyImages
    result = await fetch_property_images(UID, PROP1)
    record("B3 fetch_property_images", result)

    # B4: compare_properties — 2x /property/property-details-bots in parallel
    #     property_names is a comma-separated string
    result = await compare_properties(UID, property_names=f"{PROP1}, {PROP2}")
    record("B4 compare_properties", result)

    # B5: fetch_landmarks — Overpass API + OSRM
    result = await fetch_landmarks(UID, landmark_name="Metro Station", property_name=PROP1)
    record("B5 fetch_landmarks", result)

    # B6: fetch_nearby_places — Overpass API
    result = await fetch_nearby_places(UID, property_name=PROP1)
    record("B6 fetch_nearby_places", result)

    # B7: shortlist_property — /bookingBot/shortlist-booking-bot-property
    #     Phone comes from real Redis (seeded in Phase 0 as 9773510154)
    #     Mock only analytics side-effects; record_property_shortlisted MUST run
    #     so that D3 (get_shortlisted_properties) finds the entry in user_memory.
    with patch("tools.broker.shortlist.track_funnel"), \
         patch("tools.broker.shortlist.schedule_followup"):
        result = await shortlist_property(UID, property_name=PROP1)
    record("B7 shortlist_property", result)


# ── Block C — Location Tool ───────────────────────────────────────────────────
async def block_c(info_map: list[dict]) -> None:
    from tools.broker.landmarks import estimate_commute

    PROP1 = info_map[0]["property_name"]

    print("\n\n" + "=" * 64)
    print("BLOCK C — Location Tool")
    print("=" * 64)

    # C1: estimate_commute — OSRM routing via maps.rentok.com
    result = await estimate_commute(UID, property_name=PROP1, destination="BKC, Mumbai")
    record("C1 estimate_commute", result)


# ── Block D — Profile Tools ───────────────────────────────────────────────────
async def block_d(info_map: list[dict]) -> None:
    from tools.profile.details import fetch_profile_details
    from tools.profile.events import get_scheduled_events
    from tools.profile.shortlisted import get_shortlisted_properties

    print("\n\n" + "=" * 64)
    print("BLOCK D — Profile Tools (real Redis — no mocks)")
    print("=" * 64)

    # D1: fetch_profile_details — Redis-only (reads prefs seeded in Phase 0)
    result = await fetch_profile_details(UID)
    record("D1 fetch_profile_details", result)

    # D2: get_scheduled_events — real /bookingBot/booking/{uid}/events
    #     WARN expected: synthetic test user has no real events
    result = await get_scheduled_events(UID)
    record("D2 get_scheduled_events", result, warn=True)

    # D3: get_shortlisted_properties — Redis-only (reads shortlist seeded in Phase 0)
    result = await get_shortlisted_properties(UID)
    record("D3 get_shortlisted_properties", result)


# ── Block E — Booking Phone Gate ──────────────────────────────────────────────
async def block_e(info_map: list[dict]) -> None:
    from tools.booking.schedule_visit import save_visit_time
    from tools.booking.schedule_call import save_call_time

    PROP1 = info_map[0]["property_name"]

    print("\n\n" + "=" * 64)
    print("BLOCK E — Booking Phone Gate")
    print("=" * 64)
    print(f"  Property: {PROP1}")

    # E1: save_visit_time with NO phone → gate must block before any API call
    with patch("tools.booking.schedule_visit.get_user_phone", return_value=None):
        result = await save_visit_time(
            UID, property_name=PROP1, visit_date="2026-03-20", visit_time="11:00 AM"
        )
    record("E1 visit_phone_gate (no phone)", result, expect_contains="phone number")

    # E2: save_call_time with NO phone → same gate
    with patch("tools.booking.schedule_call.get_user_phone", return_value=None):
        result = await save_call_time(
            UID, property_name=PROP1, visit_date="2026-03-20", visit_time="11:00 AM"
        )
    record("E2 call_phone_gate (no phone)", result, expect_contains="phone number")

    # E3: save_visit_time WITH real phone (already in Redis from Phase 0)
    #     Creates a real CRM lead: "sanchay bb test 1" / 9773510154
    #     WARN: may return 400 duplicate if run multiple times
    result = await save_visit_time(
        UID,
        property_name=PROP1,
        visit_date="2026-03-25",
        visit_time="02:00 PM",
        visit_type="Physical visit",
    )
    record("E3 visit_with_real_phone (9773510154 / sanchay bb test 1)", result, warn=True)


# ── Summary ───────────────────────────────────────────────────────────────────
def print_summary() -> None:
    print("\n\n" + "=" * 64)
    print("FINAL RESULTS — All 16 Tools")
    print("=" * 64)

    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for label, status, detail in RESULTS:
        icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}[status]
        print(f"  {icon}  {label}: {status}")
        counts[status] += 1

    total = len(RESULTS)
    pct = int(counts["PASS"] / total * 100) if total else 0
    print(f"\n  Score: {counts['PASS']}/{total} PASS ({pct}%)  |  "
          f"{counts['WARN']} WARN  |  {counts['FAIL']} FAIL")

    if counts["FAIL"] == 0:
        print("  🎉 All tools responded — zero unexpected failures")
    else:
        print(f"  ❗ {counts['FAIL']} unexpected failure(s) — review output above")


# ── Entry point ───────────────────────────────────────────────────────────────
async def main() -> None:
    print("=" * 64)
    print("EazyPG Booking Bot — Comprehensive Live API Test")
    print("=" * 64)
    print(f"  Backend : {settings.RENTOK_API_BASE_URL}")
    print(f"  User    : {UID}")
    print(f"  Phone   : {PHONE}")
    print(f"  Name    : {NAME}")

    info_map = await phase0_discover_and_seed()

    await block_a(info_map)
    await block_b(info_map)
    await block_c(info_map)
    await block_d(info_map)
    await block_e(info_map)

    print_summary()


if __name__ == "__main__":
    asyncio.run(main())
