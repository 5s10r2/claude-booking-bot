"""
test_fixed_tools.py — Smoke-test the three broker tools fixed for B1/B2/B3.

Tests (all async, run against live RentOK API):

  T1  _fetch_details_raw()      — B1+B3 fix: correct UUID, correct response parsing
  T2  fetch_property_details()  — full tool flow with mocked user_id + known property name
  T3  fetch_properties_by_query() — B2 fix: pg_name field, correct response key
  T4  compare_properties()       — B1 fix in compare.py (property_id not pg_id)

Run:
  python test_fixed_tools.py

Requirements:
  .env with RENTOK_API_BASE_URL, REDIS_HOST/PORT/PASSWORD (or REDIS_URL)
  The OxOtel properties must be searchable (same pg_ids as config.js)
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# ── helpers ──────────────────────────────────────────────────────────────────

PASS = "\033[32m✅ PASS\033[0m"
FAIL = "\033[31m❌ FAIL\033[0m"
WARN = "\033[33m⚠  WARN\033[0m"
INFO = "\033[36mℹ  INFO\033[0m"

results: list[tuple[str, bool, str]] = []

def check(label: str, ok: bool, detail: str = "") -> bool:
    tag = PASS if ok else FAIL
    line = f"  {tag}  {label}"
    if detail:
        line += f"  →  {detail}"
    print(line)
    results.append((label, ok, detail))
    return ok


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ── Step 0: discover a live UUID via fetch-all-properties ─────────────────────

PG_IDS = [
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


async def discover_properties() -> list[dict]:
    """Hit fetch-all-properties and return raw list of property dicts."""
    import httpx
    from config import settings

    async with httpx.AsyncClient(timeout=20) as c:
        resp = await c.post(
            f"{settings.RENTOK_API_BASE_URL}/bookingBot/fetch-all-properties",
            json={"pg_ids": PG_IDS},
        )
        resp.raise_for_status()
        data = resp.json()
        props = data.get("data", data.get("properties", []))
        return props if isinstance(props, list) else []


# ── T1: _fetch_details_raw() ──────────────────────────────────────────────────

async def test_fetch_details_raw(uuid: str, pg_name: str):
    section(f"T1 — _fetch_details_raw(uuid) — B1+B3 fix")
    print(f"  Property: {pg_name}")
    print(f"  UUID    : {uuid}")

    from tools.broker.property_details import _fetch_details_raw

    raw = await _fetch_details_raw(uuid)

    check("Returns non-empty dict", bool(raw), f"{len(raw)} keys" if raw else "empty dict")
    check("property_name populated",
          bool(raw.get("property_name")),
          raw.get("property_name", "MISSING"))
    check("location populated",
          bool(raw.get("location")),
          raw.get("location", "MISSING"))
    amenities_val = raw.get("amenities") or raw.get("common_amenities")
    check("amenities populated",
          bool(amenities_val),
          str(amenities_val)[:60] if amenities_val else "MISSING")
    check("No 'pg_id fallback' smell — property_name is pg_name style",
          "Firebase" not in str(raw.get("property_name", "")),
          "")

    if raw:
        print(f"\n  Raw keys returned: {sorted(raw.keys())}")


# ── T2: fetch_property_details() ─────────────────────────────────────────────

async def test_fetch_property_details(pg_name: str, uuid: str):
    section(f"T2 — fetch_property_details() — full tool flow")
    print(f"  Searching for: '{pg_name}'  (UUID: {uuid[:8]}...)")

    import unittest.mock as mock

    # find_property() (in utils/properties.py) calls get_property_info_map from
    # its own import namespace — patch it there, not in property_details.
    # Return a list (matching Redis schema) with the known property entry.
    fake_info_list = [{
        "property_name":    pg_name,
        "prop_id":          uuid,      # B1 fix: UUID, not Firebase UID
        "property_id":      uuid,
        "pg_id":            PG_IDS[0],
        "property_location": "Mumbai",
    }]

    with mock.patch("utils.properties.get_property_info_map",
                    return_value=fake_info_list), \
         mock.patch("tools.broker.property_details.set_property_info_map",
                    new_callable=mock.AsyncMock), \
         mock.patch("tools.broker.property_details.track_funnel",
                    new_callable=mock.AsyncMock):

        from tools.broker.property_details import fetch_property_details
        result = await fetch_property_details(
            user_id="test_user_fixed",
            property_name=pg_name,
        )

    check("Returns a string result", isinstance(result, str), "")
    check("Not empty / not 'could not find'",
          bool(result) and "could not find" not in result.lower(),
          result[:80] if result else "EMPTY")
    check("Contains property name",
          pg_name.split()[0].lower() in result.lower(),
          "")
    # Live data = no 'cached snapshot' phrase; warn if cache path hit
    is_live = "snapshot" not in result.lower() and "cached" not in result.lower()
    tag = PASS if is_live else WARN
    print(f"  {tag}  Live API data (not cache fallback)  →  {'yes' if is_live else 'cache path hit'}")
    if result:
        print(f"\n  Result preview:\n    {result[:200]}")


# ── T3: fetch_properties_by_query() — B2 fix ─────────────────────────────────

async def test_fetch_properties_by_query():
    section("T3 — fetch_properties_by_query() — B2 fix (pg_name)")

    import unittest.mock as mock

    # Patch get_whitelabel_pg_ids at the import reference inside query_properties
    with mock.patch("tools.broker.query_properties.get_whitelabel_pg_ids",
                    return_value=PG_IDS):

        from tools.broker.query_properties import fetch_properties_by_query
        # Use "thane" — substring of "Tejdeep 902 Boy's THANE" and others
        result = await fetch_properties_by_query(
            user_id="test_user_fixed",
            query="thane",
        )

    check("Returns a string", isinstance(result, str), "")
    check("Not empty", bool(result) and len(result) > 10, result[:80] if result else "EMPTY")
    check("Contains at least one property name",
          any(word in result.lower() for word in ["tejdeep", "thane", "metropolis", "coral"]),
          result[:120] if result else "EMPTY")
    check("No 'no properties found' error",
          "no properties" not in result.lower() and "0 properties" not in result.lower(),
          "")

    print(f"\n  Result preview:\n    {result[:200]}")


# ── T4: compare_properties() — B1 fix in compare.py ─────────────────────────

async def test_compare_properties(props: list[dict]):
    section("T4 — compare_properties() — B1 fix in compare.py line 59")

    # Pick 2 properties that have UUIDs
    candidates = [p for p in props if p.get("id") or p.get("p_id")][:2]
    if len(candidates) < 2:
        print(f"  {WARN}  Need 2 properties with UUIDs — only found {len(candidates)}")
        return

    names = [p.get("pg_name", p.get("property_name", "")) for p in candidates]
    print(f"  Comparing: {names[0]}  vs  {names[1]}")

    import unittest.mock as mock

    # Build info_map list entries with correct UUIDs (the B1 fix)
    entry0 = {
        "property_name": names[0],
        "prop_id":       candidates[0].get("id") or candidates[0].get("p_id"),
        "property_id":   candidates[0].get("id") or candidates[0].get("p_id"),
        "pg_id":         candidates[0].get("pg_id", ""),
        "eazypg_id":     candidates[0].get("eazypg_id", ""),
        "property_location": candidates[0].get("city", ""),
    }
    entry1 = {
        "property_name": names[1],
        "prop_id":       candidates[1].get("id") or candidates[1].get("p_id"),
        "property_id":   candidates[1].get("id") or candidates[1].get("p_id"),
        "pg_id":         candidates[1].get("pg_id", ""),
        "eazypg_id":     candidates[1].get("eazypg_id", ""),
        "property_location": candidates[1].get("city", ""),
    }
    fake_info_list = [entry0, entry1]
    fake_memory = {"shortlisted": [entry0, entry1]}

    with mock.patch("tools.broker.compare.get_user_memory",
                    return_value=fake_memory), \
         mock.patch("tools.broker.compare.get_preferences",
                    return_value={}), \
         mock.patch("utils.properties.get_property_info_map",
                    return_value=fake_info_list):

        from tools.broker.compare import compare_properties
        result = await compare_properties(
            user_id="test_user_fixed",
            property_names=", ".join(names),   # tool expects comma-separated string
        )

    check("Returns a string", isinstance(result, str), "")
    check("Not empty", bool(result) and len(result) > 20, result[:80] if result else "EMPTY")
    check("Contains both property names or comparison data",
          any(n.split()[0].lower() in result.lower() for n in names),
          result[:120] if result else "EMPTY")
    check("No UUID error (HTTP 500 / invalid input syntax)",
          "invalid input" not in result.lower() and "http 500" not in result.lower(),
          "")

    print(f"\n  Result preview:\n    {result[:200]}")


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    print("\n" + "═"*60)
    print("  EazyPG — Fixed Tool Smoke Tests (B1 / B2 / B3)")
    print("═"*60)

    # Discover a live property to use across tests
    section("STEP 0 — Discover live OxOtel properties (fetch-all-properties)")
    try:
        props = await discover_properties()
        check("fetch-all-properties OK", bool(props), f"{len(props)} properties")
    except Exception as e:
        check("fetch-all-properties OK", False, str(e))
        print("\n  Cannot continue without live property data.")
        sys.exit(1)

    # Print discovered property names + UUIDs
    print(f"\n  Discovered properties:")
    for p in props[:5]:
        uuid = p.get("id") or p.get("p_id", "—")
        name = p.get("pg_name") or p.get("property_name") or "?"
        print(f"    [{uuid[:8]}...]  {name}")
    if len(props) > 5:
        print(f"    ... and {len(props)-5} more")

    # Pick the first property with a UUID for detail tests
    test_prop = next((p for p in props if p.get("id") or p.get("p_id")), None)
    if not test_prop:
        print(f"\n  {WARN}  No properties with UUIDs found — T1/T2/T4 will be skipped")
        await test_fetch_properties_by_query()
    else:
        uuid = test_prop.get("id") or test_prop.get("p_id")
        pg_name = test_prop.get("pg_name") or test_prop.get("property_name") or "Unknown"

        await test_fetch_details_raw(uuid, pg_name)
        await test_fetch_property_details(pg_name, uuid)
        await test_fetch_properties_by_query()
        await test_compare_properties(props)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "═"*60)
    total  = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed
    print(f"  RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} failed)")
        print("\n  Failed checks:")
        for label, ok, detail in results:
            if not ok:
                print(f"    ❌  {label}  {detail}")
    else:
        print("  🎉")
    print("═"*60 + "\n")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
