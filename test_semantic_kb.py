"""
Semantic KB End-to-End Test Suite
Tests: flag toggle → doc upload with category → embedding → semantic retrieval via chat

Cost: ~2 Haiku calls ($0.002 total)
Usage: python test_semantic_kb.py
"""

import asyncio, httpx, json, time, sys, uuid

BASE_URL = "https://claude-booking-bot.onrender.com"
API_KEY = "OxOtel1234"
HEADERS = {"X-API-Key": API_KEY}
PROP_ID = "UaDCGP3dzzZRgVIzBDgXb5ry5ng2"   # Kurla property — appears consistently in searches
TEST_UID = f"skb_{uuid.uuid4().hex[:6]}"

# OxOtel brand account_values — includes pg_ids so search_properties can filter by brand properties.
# The browser widget fetches these from /brand-config?token=... and passes them here; in tests we
# must include them explicitly, otherwise get_whitelabel_pg_ids returns [] and search returns nothing.
OXOTEL_ACCOUNT_VALUES = {
    "brand": "cdeaa3d2-3d82-4a36-9e94-e4985e4bdcbc",
    "brand_hash": "5cbc221962dfae5a",
    "pg_ids": [
        "l5zf3ckOnRQV9OHdv5YTTXkvLHp1", "egu5HmrYFMP8MRJyMsefnpaL7ka2",
        "Z2wyLOXXp5QA596DQ6aZAQpakmQ2", "UaDCGP3dzzZRgVIzBDgXb5ry5ng2",
        "EqhTMiUNksgXh5QhGQRsY5DQiO42", "fzDBxYtHgVV21ertfkUdSHeomiv2",
        "CUxtdeaGxYS8IMXmGZ1yUnqyfOn2", "wtlUSKV9H8bkNqvlGmnogwoqwyk2",
        "1Dy0t6YeIHh3kQhqvQR8tssHWKt1", "U2uYCaeiCebrE95iUDsS4PwEd1J2",
    ],
}

DOC_PRICING = """OxOtel Kurla — Pricing Guide (March 2026)
- Triple sharing: ₹7,500/month
- Double sharing: ₹9,500/month
- Single room: ₹18,000/month
- Security deposit: 2 months rent (refundable)
- Token amount: ₹2,000
- Early bird: 10% off for 2-week advance booking
- Long-stay: 15% off for 6-month commitment
"""

DOC_LOCATION = """OxOtel Kurla — Location Guide
- Kurla Railway Station: 5-min walk (Central Line + Harbour Line)
- LBS Road: 2-min walk
- Phoenix Marketcity: 10-min walk
- BKC: 15-min by auto
- Mumbai Airport: 8km
"""

scores = []

def check(name, ok, detail=""):
    scores.append(ok)
    print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))
    return ok


async def main():
    print(f"\n{'='*55}\n  Semantic KB E2E Tests — {BASE_URL}\n{'='*55}")
    doc_ids = []

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=90) as c:
        # T1: Health
        r = await c.get("/health")
        if not check("T1 Health", r.status_code == 200):
            print("  ⏳ Cold start — waiting 30s...")
            await asyncio.sleep(30)
            r = await c.get("/health")
            if not check("T1 Retry", r.status_code == 200):
                sys.exit(1)

        # T2: Enable SEMANTIC_KB_ENABLED
        r = await c.post("/admin/flags", headers=HEADERS,
                         json={"key": "SEMANTIC_KB_ENABLED", "value": True})
        check("T2 Enable flag", r.status_code == 200, r.text[:80] if r.status_code != 200 else "")

        r = await c.get("/admin/flags", headers=HEADERS)
        flags = r.json() if r.status_code == 200 else {}
        check("T2b Verify flag", flags.get("SEMANTIC_KB_ENABLED") is True)

        # T3: Upload pricing doc
        r = await c.post(
            f"/admin/properties/{PROP_ID}/documents",
            headers={"X-API-Key": API_KEY},
            files={"file": ("pricing.txt", DOC_PRICING.encode(), "text/plain")},
            data={"category": "pricing_availability"},
        )
        d3 = r.json() if r.status_code == 200 else {}
        did3 = d3.get("id") or d3.get("doc_id")
        doc_ids.append(did3)
        check("T3 Upload pricing doc", did3 is not None, f"id={did3}")

        # T4: Upload location doc
        r = await c.post(
            f"/admin/properties/{PROP_ID}/documents",
            headers={"X-API-Key": API_KEY},
            files={"file": ("location.txt", DOC_LOCATION.encode(), "text/plain")},
            data={"category": "location_area"},
        )
        d4 = r.json() if r.status_code == 200 else {}
        did4 = d4.get("id") or d4.get("doc_id")
        doc_ids.append(did4)
        check("T4 Upload location doc", did4 is not None, f"id={did4}")

        # Wait for background embedding
        print("  ⏳ Waiting 6s for Nomic embedding...")
        await asyncio.sleep(6)

        # T5: Verify docs have categories
        r = await c.get(f"/admin/properties/{PROP_ID}/documents", headers=HEADERS)
        docs = r.json() if r.status_code == 200 else []
        if isinstance(docs, dict):
            docs = docs.get("documents", [])
        our = [d for d in docs if d.get("id") in (did3, did4)]
        cats = [d.get("category") for d in our]
        check("T5 Docs have categories", len(our) == 2 and all(cats), f"cats={cats}")

        # T6: Full search with qualifiers to bypass bot qualifying questions, then ask pricing
        # Include gender + budget + location in one shot so the broker agent searches immediately.
        print("\n  💬 T6a: Full search (gender + budget + location — 1 Haiku call)...")
        r = await c.post("/chat", headers={**HEADERS, "Content-Type": "application/json"},
                         json={"message": "Show me PGs in Kurla Mumbai, any type, budget ₹12,000",
                               "user_id": TEST_UID,
                               "account_values": OXOTEL_ACCOUNT_VALUES})
        t6a_ok = r.status_code == 200
        if t6a_ok:
            body = r.json()
            reply = body.get("response", "") or body.get("reply", "") or str(body)
            print(f"       Search reply (first 200): {reply[:200]}")
            # Confirm a real search ran (not just qualifier questions)
            search_ran = any(k in reply.lower() for k in ["result", "found", "option", "property", "pg", "₹", "kurla", "here", "available"])
        check("T6a Search triggered", t6a_ok and search_ran if t6a_ok else False,
              f"search_ran={search_ran}" if t6a_ok else f"HTTP {r.status_code}")

        print("  💬 T6b: Pricing question (1 Haiku call)...")
        r = await c.post("/chat", headers={**HEADERS, "Content-Type": "application/json"},
                         json={"message": "What are the pricing details and any discounts available?",
                               "user_id": TEST_UID,
                               "account_values": OXOTEL_ACCOUNT_VALUES})
        if r.status_code == 200:
            body = r.json()
            reply = body.get("response", "") or body.get("reply", "") or str(body)
            # Strict KB content check — ₹9,500 or ₹7,500 from the uploaded doc specifically
            strict_kws = ["9,500", "9500", "7,500", "7500", "10%", "15%", "18,000"]
            loose_kws  = ["deposit", "token", "discount", "₹", "rent"]
            strict_hits = [k for k in strict_kws if k in reply]
            loose_hits  = [k for k in loose_kws  if k.lower() in reply.lower()]
            print(f"       Reply preview: {reply[:350]}")
            print(f"       Strict KB hits: {strict_hits}  |  Loose hits: {loose_hits}")
            kb_ok = len(strict_hits) >= 1
            check("T6b Pricing KB injection", kb_ok,
                  f"strict_hits={strict_hits}" if kb_ok else
                  f"No specific pricing from doc. loose_hits={loose_hits}")
        else:
            check("T6b Pricing KB injection", False, f"HTTP {r.status_code}: {r.text[:150]}")

        # T7: Location question on same user (KB docs already injected via search context)
        print("\n  💬 T7: Location question (1 Haiku call)...")
        r = await c.post("/chat", headers={**HEADERS, "Content-Type": "application/json"},
                         json={"message": "How far is the nearest railway station from this PG?",
                               "user_id": TEST_UID,
                               "account_values": OXOTEL_ACCOUNT_VALUES})
        if r.status_code == 200:
            body = r.json()
            reply = body.get("response", "") or body.get("reply", "") or str(body)
            # Doc says "Kurla Railway Station: 5-min walk"
            kws = ["kurla", "railway", "station", "5-min", "5 min", "walk", "central", "harbour", "lbs"]
            hits = [k for k in kws if k.lower() in reply.lower()]
            print(f"       Reply preview: {reply[:250]}")
            check("T7 Location KB injection", len(hits) >= 1, f"matched: {hits}")
        else:
            check("T7 Location KB injection", False, f"HTTP {r.status_code}: {r.text[:150]}")

        # Cleanup
        print("\n  🧹 Cleanup...")
        for did in doc_ids:
            if did:
                await c.delete(f"/admin/properties/{PROP_ID}/documents/{did}", headers=HEADERS)
        await c.post("/admin/flags", headers=HEADERS,
                     json={"key": "SEMANTIC_KB_ENABLED", "value": False})

    # Summary
    p = sum(scores)
    t = len(scores)
    print(f"\n{'='*55}\n  {p}/{t} PASS" + (" — 🎉 All passed!" if p == t else "") + f"\n{'='*55}")
    sys.exit(0 if p == t else 1)

if __name__ == "__main__":
    asyncio.run(main())
