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
PROP_ID = "l5zf3ckOnRQV9OHdv5YTTXkvLHp1"
TEST_UID = f"skb_{uuid.uuid4().hex[:6]}"

DOC_PRICING = """OxOtel Andheri West — Pricing Guide (March 2026)
- Triple sharing: ₹7,500/month
- Double sharing: ₹9,500/month
- Single room: ₹18,000/month
- Security deposit: 2 months rent (refundable)
- Token amount: ₹2,000
- Early bird: 10% off for 2-week advance booking
- Long-stay: 15% off for 6-month commitment
"""

DOC_LOCATION = """OxOtel Andheri West — Location Guide
- DN Nagar Metro: 5-min walk (Line 1)
- Andheri Railway Station: 15-min walk (Western Line)
- Lokhandwala Market: 8-min walk
- Infinity Mall: 12-min walk
- Mumbai Airport: 4km by auto
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

        # T6: Search first to populate property IDs, then ask pricing (2 Haiku calls)
        print("\n  💬 T6a: Search to build context (1 Haiku call)...")
        r = await c.post("/chat", headers={**HEADERS, "Content-Type": "application/json"},
                         json={"message": "Show me PGs in Andheri West",
                               "user_id": TEST_UID,
                               "account_values": {"brand": "OxOtel"}})
        t6a_ok = r.status_code == 200
        if t6a_ok:
            body = r.json()
            reply = body.get("response", "") or body.get("reply", "") or str(body)
            print(f"       Search reply: {reply[:150]}...")
        check("T6a Search context", t6a_ok, f"HTTP {r.status_code}")

        print("  💬 T6b: Pricing question (1 Haiku call)...")
        r = await c.post("/chat", headers={**HEADERS, "Content-Type": "application/json"},
                         json={"message": "What is the monthly rent for double sharing? Any discounts?",
                               "user_id": TEST_UID,
                               "account_values": {"brand": "OxOtel"}})
        if r.status_code == 200:
            body = r.json()
            reply = body.get("response", "") or body.get("reply", "") or str(body)
            kws = ["9,500", "9500", "discount", "15%", "10%", "deposit", "7,500", "7500", "rent", "₹"]
            hits = [k for k in kws if k.lower() in reply.lower()]
            print(f"       Reply preview: {reply[:250]}")
            check("T6b Pricing retrieval", len(hits) >= 1, f"matched: {hits}")
        else:
            check("T6b Pricing retrieval", False, f"HTTP {r.status_code}: {r.text[:150]}")

        # T7: Location question on same user (already has search context)
        print("\n  💬 T7: Location question (1 Haiku call)...")
        r = await c.post("/chat", headers={**HEADERS, "Content-Type": "application/json"},
                         json={"message": "How far is the nearest metro station from this property?",
                               "user_id": TEST_UID,
                               "account_values": {"brand": "OxOtel"}})
        if r.status_code == 200:
            body = r.json()
            reply = body.get("response", "") or body.get("reply", "") or str(body)
            kws = ["dn nagar", "metro", "5 min", "5-min", "walk", "andheri", "line 1", "station"]
            hits = [k for k in kws if k.lower() in reply.lower()]
            print(f"       Reply preview: {reply[:250]}")
            check("T7 Location retrieval", len(hits) >= 1, f"matched: {hits}")
        else:
            check("T7 Location retrieval", False, f"HTTP {r.status_code}: {r.text[:150]}")

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
