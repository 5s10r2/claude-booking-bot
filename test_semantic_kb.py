"""
Semantic KB End-to-End Test Suite
Tests the full pipeline: flag toggle → document upload with category → embedding → semantic retrieval via chat

Requires: production backend running with NOMIC_API_KEY set
Usage: python test_semantic_kb.py
"""

import asyncio
import httpx
import json
import time
import sys
import uuid

# ── Config ──────────────────────────────────────────────────────────
BASE_URL = "https://claude-booking-bot.onrender.com"
API_KEY = "OxOtel1234"
HEADERS = {"X-API-Key": API_KEY}
# Use first OxOtel property
TEST_PROP_ID = "l5zf3ckOnRQV9OHdv5YTTXkvLHp1"
TEST_USER_ID = f"test_semantic_kb_{uuid.uuid4().hex[:8]}"
TIMEOUT = 60.0


# ── Helpers ─────────────────────────────────────────────────────────
async def api(method: str, path: str, **kwargs):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as c:
        resp = await getattr(c, method)(path, headers=HEADERS, **kwargs)
        return resp


def result(name: str, passed: bool, detail: str = ""):
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))
    return passed


# ── Tests ───────────────────────────────────────────────────────────
async def test_1_health():
    """Verify backend is up"""
    print("\n[T1] Health check")
    try:
        resp = await api("get", "/health")
        return result("Backend healthy", resp.status_code == 200, f"status={resp.status_code}")
    except Exception as e:
        return result("Backend healthy", False, str(e))


async def test_2_enable_flag():
    """Enable SEMANTIC_KB_ENABLED for OxOtel brand"""
    print("\n[T2] Enable SEMANTIC_KB_ENABLED flag")

    # First check current flags
    resp = await api("get", "/admin/flags")
    if resp.status_code != 200:
        return result("Get flags", False, f"status={resp.status_code}")

    flags = resp.json()
    current = flags.get("SEMANTIC_KB_ENABLED", False)
    print(f"       Current SEMANTIC_KB_ENABLED = {current}")

    # Enable it
    resp = await api("post", "/admin/flags", json={"key": "SEMANTIC_KB_ENABLED", "value": True})
    if resp.status_code != 200:
        return result("Enable flag", False, f"status={resp.status_code} body={resp.text}")

    # Verify
    resp = await api("get", "/admin/flags")
    flags = resp.json()
    enabled = flags.get("SEMANTIC_KB_ENABLED", False)
    return result("SEMANTIC_KB_ENABLED = true", enabled is True, f"flags={flags}")


async def test_3_upload_document():
    """Upload a test document with category"""
    print("\n[T3] Upload document with category")

    # Create a realistic test document
    doc_text = """OxOtel Andheri West - Pricing & Availability Guide

Monthly Rent Structure:
- Single occupancy bed in shared room: ₹12,000/month
- Double occupancy bed in shared room: ₹9,500/month
- Triple occupancy bed in shared room: ₹7,500/month
- Private room (single): ₹18,000/month

Security Deposit: 2 months rent (refundable)
Lock-in Period: 3 months minimum stay
Token Amount: ₹2,000 (adjustable against first month rent)

Current Availability (March 2026):
- 3 beds available in triple sharing
- 1 bed available in double sharing
- Private rooms: Waitlisted (expected April 2026)

Special Offers:
- Early bird discount: 10% off first 3 months for bookings made 2 weeks in advance
- Referral bonus: ₹2,000 credit for each successful referral
- Long-stay discount: 15% off for 6-month commitment
"""

    files = {"file": ("test_pricing_doc.txt", doc_text.encode(), "text/plain")}
    data = {"category": "pricing_availability"}

    resp = await api("post", f"/admin/properties/{TEST_PROP_ID}/documents", files=files, data=data)
    if resp.status_code != 200:
        return result("Upload document", False, f"status={resp.status_code} body={resp.text[:200]}")

    body = resp.json()
    doc_id = body.get("id") or body.get("doc_id")
    print(f"       Document ID: {doc_id}")
    print(f"       Category: {body.get('category', 'N/A')}")

    # Wait for background embedding to complete
    print("       Waiting 5s for background embedding...")
    await asyncio.sleep(5)

    return result("Document uploaded", doc_id is not None, f"id={doc_id}"), doc_id


async def test_4_upload_location_doc():
    """Upload a second document with different category for contrast"""
    print("\n[T4] Upload location document")

    doc_text = """OxOtel Andheri West - Location & Connectivity

Address: Plot 42, DN Nagar, Andheri West, Mumbai 400053

Metro Connectivity:
- DN Nagar Metro Station: 5 minute walk (Line 1)
- Andheri Metro Station: 10 minute auto ride
- Direct metro to BKC (25 mins), Ghatkopar (20 mins)

Railway:
- Andheri Railway Station: 15 minute walk (Western Line)
- Direct trains to Churchgate (40 mins), Borivali (25 mins)

Nearby Landmarks:
- Lokhandwala Market: 8 min walk
- Infinity Mall: 12 min walk
- Kokilaben Hospital: 10 min drive
- JVPD Scheme: 5 min walk

Area Highlights:
- Well-connected IT hub area
- Multiple food options within 500m radius
- 24/7 pharmacy and medical stores nearby
"""

    files = {"file": ("test_location_doc.txt", doc_text.encode(), "text/plain")}
    data = {"category": "location_area"}

    resp = await api("post", f"/admin/properties/{TEST_PROP_ID}/documents", files=files, data=data)
    if resp.status_code != 200:
        return result("Upload location doc", False, f"status={resp.status_code}")

    body = resp.json()
    doc_id = body.get("id") or body.get("doc_id")

    # Wait for embedding
    print("       Waiting 5s for background embedding...")
    await asyncio.sleep(5)

    return result("Location doc uploaded", doc_id is not None, f"id={doc_id}"), doc_id


async def test_5_verify_documents():
    """Verify documents exist with categories"""
    print("\n[T5] Verify documents in DB")

    resp = await api("get", f"/admin/properties/{TEST_PROP_ID}/documents")
    if resp.status_code != 200:
        return result("List documents", False, f"status={resp.status_code}")

    docs = resp.json()
    if not isinstance(docs, list):
        docs = docs.get("documents", [])

    print(f"       Found {len(docs)} documents")
    for d in docs:
        cat = d.get("category", "none")
        fname = d.get("filename", "?")
        print(f"       - {fname} [{cat}]")

    has_pricing = any(d.get("category") == "pricing_availability" for d in docs)
    has_location = any(d.get("category") == "location_area" for d in docs)

    return result("Both categories present", has_pricing and has_location,
                   f"pricing={has_pricing}, location={has_location}")


async def test_6_semantic_retrieval_pricing():
    """Ask a pricing question — should retrieve pricing doc via semantic search"""
    print("\n[T6] Semantic retrieval: pricing question")

    question = "What is the monthly rent for a single bed in Andheri? Any discounts available?"

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=90.0) as c:
        resp = await c.post("/chat/stream", json={
            "message": question,
            "user_id": TEST_USER_ID,
            "account_values": {"brand": "OxOtel"},
        }, headers={"Accept": "text/event-stream"})

        if resp.status_code != 200:
            return result("Chat stream", False, f"status={resp.status_code} body={resp.text[:200]}")

        # Collect SSE response
        full_text = ""
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    if "text" in chunk:
                        full_text += chunk["text"]
                    elif "content" in chunk:
                        full_text += chunk["content"]
                except json.JSONDecodeError:
                    full_text += data

    print(f"       Response length: {len(full_text)} chars")
    preview = full_text[:300].replace("\n", " ")
    print(f"       Preview: {preview}...")

    # Check if response contains pricing info from our uploaded doc
    pricing_keywords = ["12,000", "12000", "9,500", "9500", "7,500", "7500", "18,000", "18000",
                        "discount", "token", "deposit", "rent"]
    matches = [kw for kw in pricing_keywords if kw.lower() in full_text.lower()]

    return result("Response contains pricing data", len(matches) >= 2,
                   f"matched: {matches}")


async def test_7_semantic_retrieval_location():
    """Ask a location question — should retrieve location doc"""
    print("\n[T7] Semantic retrieval: location question")

    question = "How far is the nearest metro station from OxOtel Andheri? What about the railway station?"

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=90.0) as c:
        resp = await c.post("/chat/stream", json={
            "message": question,
            "user_id": TEST_USER_ID + "_loc",
            "account_values": {"brand": "OxOtel"},
        }, headers={"Accept": "text/event-stream"})

        if resp.status_code != 200:
            return result("Chat stream", False, f"status={resp.status_code}")

        full_text = ""
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    if "text" in chunk:
                        full_text += chunk["text"]
                    elif "content" in chunk:
                        full_text += chunk["content"]
                except json.JSONDecodeError:
                    full_text += data

    print(f"       Response length: {len(full_text)} chars")
    preview = full_text[:300].replace("\n", " ")
    print(f"       Preview: {preview}...")

    # Check location info from our doc
    location_keywords = ["DN Nagar", "metro", "andheri", "railway", "walk", "minute",
                         "Lokhandwala", "Western Line"]
    matches = [kw for kw in location_keywords if kw.lower() in full_text.lower()]

    return result("Response contains location data", len(matches) >= 2,
                   f"matched: {matches}")


async def test_8_cleanup(doc_ids: list):
    """Clean up: delete test documents, disable flag"""
    print("\n[T8] Cleanup")

    deleted = 0
    for doc_id in doc_ids:
        if doc_id:
            resp = await api("delete", f"/admin/properties/{TEST_PROP_ID}/documents/{doc_id}")
            if resp.status_code == 200:
                deleted += 1

    result("Deleted test documents", deleted == len([d for d in doc_ids if d]),
           f"{deleted}/{len(doc_ids)}")

    # Disable flag
    resp = await api("post", "/admin/flags", json={"key": "SEMANTIC_KB_ENABLED", "value": False})
    result("SEMANTIC_KB_ENABLED reset to false", resp.status_code == 200)

    return True


# ── Runner ──────────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("  Semantic KB End-to-End Test Suite")
    print("=" * 60)
    print(f"  Backend:  {BASE_URL}")
    print(f"  Brand:    OxOtel (key: {API_KEY})")
    print(f"  Property: {TEST_PROP_ID}")
    print(f"  User:     {TEST_USER_ID}")

    results = []
    doc_ids = []

    # T1: Health
    r = await test_1_health()
    results.append(r)
    if not r:
        print("\n⚠️  Backend not reachable. Waiting 30s for cold start...")
        await asyncio.sleep(30)
        r = await test_1_health()
        results[-1] = r
        if not r:
            print("\n❌ Backend still down. Aborting.")
            sys.exit(1)

    # T2: Enable flag
    r = await test_2_enable_flag()
    results.append(r)
    if not r:
        print("\n❌ Cannot enable flag. Aborting.")
        sys.exit(1)

    # T3: Upload pricing doc
    r, doc_id = await test_3_upload_document()
    results.append(r)
    doc_ids.append(doc_id)

    # T4: Upload location doc
    r, doc_id = await test_4_upload_location_doc()
    results.append(r)
    doc_ids.append(doc_id)

    # T5: Verify docs
    r = await test_5_verify_documents()
    results.append(r)

    # T6: Semantic retrieval - pricing
    r = await test_6_semantic_retrieval_pricing()
    results.append(r)

    # T7: Semantic retrieval - location
    r = await test_7_semantic_retrieval_location()
    results.append(r)

    # T8: Cleanup
    await test_8_cleanup(doc_ids)

    # Summary
    passed = sum(1 for r in results if r)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"  Results: {passed}/{total} PASS")
    print("=" * 60)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
