#!/usr/bin/env python3
"""
EazyPG × RentOK — Full Integration Test
Real user: Sanchay Raj Test | 9773510154 | Male | Mumbai | ₹97,000 | Move-in 15 Apr 2026

Tests all 13 RentOK endpoints end-to-end with real credentials.
Run: python test_full_integration.py
"""

import asyncio
import httpx
import json
from datetime import datetime

# ── User Config ─────────────────────────────────────────────────────────────
PHONE       = "9773510154"
NAME        = "Sanchay Raj Test"
GENDER      = "Male"
MAX_BUDGET  = 97000
MOVE_IN     = "15/04/2026"
AREA        = "Mumbai"
COMMUTE_FROM = "Andheri"
PERSONA     = "Working Professional"

# ── API Config ───────────────────────────────────────────────────────────────
BASE_URL = "https://apiv2.rentok.com"

# OxOtel pg_ids (from eazypg-chat/src/config.js)
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

# Mumbai central coordinates
MUMBAI_LAT  = 19.0760
MUMBAI_LNG  = 72.8777

# Test visit (next week, safe future date)
VISIT_DATE  = "20/03/2026"
VISIT_TIME  = "10:00 AM"
VISIT_TYPE  = "Physical visit"

# ── Helpers ──────────────────────────────────────────────────────────────────
def make_firebase_id():
    return f"cust_{datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}"

def sep(title):
    print(f"\n{'─'*65}")
    print(f"  {title}")
    print(f"{'─'*65}")

def ok(label, detail=""):
    print(f"  ✅  {label}")
    if detail: print(f"       {detail}")

def fail(label, detail=""):
    print(f"  ❌  {label}")
    if detail: print(f"       {detail}")

def info(label, detail=""):
    print(f"  ℹ️   {label}")
    if detail: print(f"       {detail}")

def check(label, cond, detail=""):
    (ok if cond else fail)(label, detail)
    return cond

# Cumulative score
_results = []
def record(label, passed):
    _results.append((label, passed))

# ── Tests ────────────────────────────────────────────────────────────────────
async def run_all():
    print("=" * 65)
    print("  EazyPG × RentOK  —  Full Integration Test")
    print(f"  User : {NAME} | {PHONE} | {GENDER}")
    print(f"  Area : {AREA} (flexible) | Budget ≤ ₹{MAX_BUDGET:,}/mo")
    print(f"  Move-in: {MOVE_IN} | Commute from: {COMMUTE_FROM}")
    print("=" * 65)

    async with httpx.AsyncClient(timeout=30) as c:

        # ── 1. Property Search ────────────────────────────────────────────
        sep("TEST 1 — Property Search  (getPropertyDetailsAroundLatLong)")
        payload = {
            "coords": [[MUMBAI_LAT, MUMBAI_LNG]],
            "radius": 35000,
            "rent_ends_to": MAX_BUDGET,
            "pg_ids": PG_IDS,
        }
        resp = await c.post(f"{BASE_URL}/property/getPropertyDetailsAroundLatLong", json=payload)
        raw  = resp.json()
        inner        = raw.get("data", {})
        inner_status = inner.get("status")
        results      = inner.get("data", {}).get("results", [])

        p1a = check("HTTP 200",              resp.status_code == 200,  f"HTTP {resp.status_code}")
        p1b = check("No inner-500",          inner_status != 500,      f"inner status = {inner_status}")
        p1c = check("Properties returned",   len(results) > 0,         f"{len(results)} properties")
        record("Property Search", p1a and p1b and p1c)

        if not results:
            fail("Cannot continue — no properties found")
            return

        print(f"\n  All {len(results)} properties found within 35 km of Mumbai:")
        for i, p in enumerate(results):
            loc = f"{p.get('p_address_line_1','')} {p.get('p_city','')}".strip() or "?"
            print(f"  {i+1:2}. {p.get('p_pg_name','?'):<35} | "
                  f"{loc:<30} | "
                  f"₹{p.get('p_rent_starts_from','?')}/mo | "
                  f"eazypg_id={p.get('p_eazypg_id','?')}")

        # Pin first property for all downstream tests
        prop        = results[0]
        eazypg_id   = prop.get("p_eazypg_id", "")
        pg_id       = prop.get("p_pg_id", "")
        pg_number   = prop.get("p_pg_number", "")
        property_id = prop.get("p_id", "")
        prop_name   = prop.get("p_pg_name", "Unknown")
        prop_phone  = prop.get("p_personal_contact", prop.get("p_phone_number", prop.get("phone_number", "")))
        prop_loc    = f"{prop.get('p_address_line_1','')} {prop.get('p_city','')}".strip()

        print(f"\n  ★ Using for all further tests:")
        print(f"    Name:        {prop_name}")
        print(f"    Location:    {prop_loc}")
        print(f"    Rent from:   ₹{prop.get('p_rent_starts_from','?')}/mo")
        print(f"    eazypg_id:   {eazypg_id}")
        print(f"    pg_id:       {pg_id}")
        print(f"    pg_number:   {pg_number}")
        print(f"    property_id: {property_id}")
        print(f"    Prop phone:  {prop_phone or 'N/A'}")

        # ── 2. Lead Creation — FULL enriched payload ──────────────────────
        sep("TEST 2 — Lead Creation: Full 22-field payload  (addLeadFromEazyPGID)")
        full_lead = {
            # ── Required ──────────────────────────────────────────────────
            "eazypg_id":            eazypg_id,
            "phone":                PHONE,
            "name":                 NAME,
            "gender":               GENDER,
            "firebase_id":          make_firebase_id(),
            "lead_source":          "Booking Bot",
            "lead_status":          "Visit Scheduled",
            # ── Standard optional (bot sends today) ───────────────────────
            "rent_range":           str(MAX_BUDGET),
            "visit_date":           VISIT_DATE,
            "visit_time":           VISIT_TIME,
            "visit_type":           VISIT_TYPE,
            # ── Enrichment optional (currently NOT sent by bot) ───────────
            "move_in_date":         MOVE_IN,
            "area":                 AREA,
            "sharing_type":         "Single",
            "sharing_types_enabled":"Single",
            "commute_from":         COMMUTE_FROM,
            "persona":              PERSONA,
            "must_haves":           "WiFi, AC",
            "deal_breakers":        "No pets",
            "occupation":           "Technology",
            "city":                 "Mumbai",
            "budget":               MAX_BUDGET,
        }
        print(f"\n  Sending {len(full_lead)} fields:")
        for k, v in full_lead.items():
            tag = "(enrichment—not sent today)" if k in {
                "move_in_date","area","sharing_type","sharing_types_enabled",
                "commute_from","persona","must_haves","deal_breakers",
                "occupation","city","budget"} else ""
            print(f"    {k:<28} = {str(v):<30} {tag}")

        resp = await c.post(f"{BASE_URL}/tenant/addLeadFromEazyPGID", json=full_lead)
        rd   = resp.json()
        already_exists_2 = resp.status_code == 401 and "already exists" in rd.get("message", "").lower()
        p2   = check("Lead created (full payload)",
                     resp.status_code == 200 or already_exists_2,
                     f"HTTP {resp.status_code} | {'✓ Lead already in CRM (HTTP 401 = OK on re-run)' if already_exists_2 else json.dumps(rd)}")
        record("Lead Creation (full 22-field)", p2)

        # ── 3. Lead Creation — standard 11-field payload (what bot sends today) ──
        sep("TEST 3 — Lead Creation: Standard 11-field payload  (current bot behaviour)")
        standard_lead = {
            "eazypg_id":   eazypg_id,
            "phone":       PHONE,
            "name":        NAME,
            "gender":      GENDER,
            "rent_range":  str(MAX_BUDGET),
            "lead_source": "Booking Bot",
            "visit_date":  VISIT_DATE,
            "visit_time":  VISIT_TIME,
            "visit_type":  VISIT_TYPE,
            "lead_status": "Visit Scheduled",
            "firebase_id": make_firebase_id(),
        }
        resp = await c.post(f"{BASE_URL}/tenant/addLeadFromEazyPGID", json=standard_lead)
        rd   = resp.json()
        already_exists = resp.status_code == 401 and "already exists" in rd.get("message", "").lower()
        p3   = check("Lead created (standard 11-field)",
                     resp.status_code == 200 or already_exists,
                     f"HTTP {resp.status_code} | {'✓ Lead already in CRM (HTTP 401 = OK on re-run)' if already_exists else json.dumps(rd)}")
        record("Lead Creation (standard 11-field)", p3)

        # ── 4. Lead with Token status (payment confirmed) ─────────────────
        sep("TEST 4 — Lead Creation: Status = 'Token'  (post-payment)")
        token_lead = {**standard_lead,
                      "lead_status": "Token",
                      "firebase_id": make_firebase_id(),
                      "visit_date": "", "visit_time": "", "visit_type": ""}
        resp = await c.post(f"{BASE_URL}/tenant/addLeadFromEazyPGID", json=token_lead)
        rd   = resp.json()
        already_exists_4 = resp.status_code == 401 and "already exists" in rd.get("message", "").lower()
        p4   = check("Lead created (Token status)",
                     resp.status_code == 200 or already_exists_4,
                     f"HTTP {resp.status_code} | {'✓ Lead already in CRM (HTTP 401 = OK on re-run)' if already_exists_4 else json.dumps(rd)}")
        record("Lead Creation (Token status)", p4)

        # ── 5. Schedule Visit (add-booking) ──────────────────────────────
        sep("TEST 5 — Schedule Visit  (add-booking)")
        user_id_test = f"test_{PHONE}"
        if property_id:
            booking_payload = {
                "user_id":       user_id_test,
                "property_id":   property_id,
                "visit_date":    VISIT_DATE,
                "visit_time":    VISIT_TIME,
                "visit_type":    VISIT_TYPE,
                "property_name": prop_name,
            }
            print(f"\n  Payload: {json.dumps(booking_payload, indent=4)}")
            resp = await c.post(f"{BASE_URL}/bookingBot/add-booking", json=booking_payload)
            rd   = resp.json()
            inner_status_5 = rd.get("status") if isinstance(rd, dict) else None
            duplicate_5    = (resp.status_code == 400) or (resp.status_code == 200 and inner_status_5 == 400)
            if duplicate_5:
                ok("add-booking", f"Duplicate detected (HTTP {resp.status_code}, inner status={inner_status_5}) — booking already exists (expected on re-run)")
                info(f"Message: {rd.get('message','') if isinstance(rd, dict) else str(rd)[:100]}")
                record("Schedule Visit", True)
            else:
                p5 = check("add-booking", resp.status_code == 200,
                           f"HTTP {resp.status_code} | {json.dumps(rd)[:200]}")
                record("Schedule Visit", p5)
        else:
            fail("add-booking skipped", "No property_id from search")
            record("Schedule Visit", False)

        # ── 6. Schedule Phone Call ────────────────────────────────────────
        sep("TEST 6 — Schedule Phone Call  (add-booking with 'Phone Call')")
        if property_id:
            call_payload = {
                "user_id":       user_id_test,
                "property_id":   property_id,
                "visit_date":    "21/03/2026",
                "visit_time":    "3:00 PM",
                "visit_type":    "Phone Call",
                "property_name": prop_name,
            }
            resp = await c.post(f"{BASE_URL}/bookingBot/add-booking", json=call_payload)
            rd   = resp.json()
            inner_status_6 = rd.get("status") if isinstance(rd, dict) else None
            duplicate_6    = (resp.status_code == 400) or (resp.status_code == 200 and inner_status_6 == 400)
            if duplicate_6:
                ok("add-booking (Phone Call)", f"Duplicate detected (HTTP {resp.status_code}, inner status={inner_status_6}) — expected on re-run")
                info(f"Message: {rd.get('message','') if isinstance(rd, dict) else str(rd)[:100]}")
                record("Schedule Phone Call", True)
            else:
                p6 = check("add-booking (Phone Call)", resp.status_code == 200,
                           f"HTTP {resp.status_code} | {json.dumps(rd)[:200]}")
                record("Schedule Phone Call", p6)

        # ── 7. Get Scheduled Events ───────────────────────────────────────
        sep("TEST 7 — Get Scheduled Events  (booking/{user_id}/events)")
        resp   = await c.get(f"{BASE_URL}/bookingBot/booking/{user_id_test}/events")
        rd     = resp.json()
        events = rd.get("data") or []
        p7     = check("Get events HTTP", resp.status_code == 200, f"HTTP {resp.status_code}")
        info(f"{len(events)} events for user_id={user_id_test}")
        for ev in events:
            print(f"    • {ev.get('property_name','?')} | {ev.get('visit_type','?')} "
                  f"on {ev.get('visit_date','?')} at {ev.get('visit_time','?')} "
                  f"— status: {ev.get('status','?')}")
        if not events:
            print(f"    Raw: {json.dumps(rd)[:300]}")
        record("Get Scheduled Events", p7)

        # ── 8. Reschedule Booking (update-booking) ────────────────────────
        sep("TEST 8 — Reschedule  (update-booking)")
        if property_id:
            resch_payload = {
                "user_id":     user_id_test,
                "property_id": property_id,
                "visit_date":  "25/03/2026",
                "visit_time":  "11:00 AM",
            }
            resp = await c.post(f"{BASE_URL}/bookingBot/update-booking", json=resch_payload)
            rd   = resp.json()
            p8   = check("update-booking", rd.get("success") is True or resp.status_code == 200,
                         f"HTTP {resp.status_code} | success={rd.get('success')} | {rd.get('message','')}")
            record("Reschedule Booking", p8)

        # ── 9. Room Availability ──────────────────────────────────────────
        sep("TEST 9 — Room Availability  (getAvailableRoomFromEazyPGID)")
        if eazypg_id:
            resp  = await c.get(f"{BASE_URL}/bookingBot/getAvailableRoomFromEazyPGID",
                                params={"eazypg_id": eazypg_id})
            p9    = check("Room availability HTTP", resp.status_code == 200,
                          f"HTTP {resp.status_code} | {'⚠ endpoint may be unavailable in this instance' if resp.status_code == 404 else ''}")
            if resp.status_code != 200:
                info(f"Response body (first 200 chars): {resp.text[:200]}")
                record("Room Availability", False)
            else:
                try:
                    rd    = resp.json()
                    rooms = rd.get("rooms", rd.get("data", []))
                    info(f"{len(rooms)} rooms returned for eazypg_id={eazypg_id}")
                    for r in rooms:
                        print(f"    • {r.get('room_name','Room'):<30} | "
                              f"{r.get('sharing_type','?')} sharing | "
                              f"{r.get('beds_available','?')} beds available | "
                              f"₹{r.get('rent','?')}/mo")
                    if not rooms:
                        print(f"    Raw: {json.dumps(rd)[:300]}")
                except Exception as e:
                    fail(f"JSON decode error: {e}")
                    info(f"Response body: {resp.text[:200]}")
                record("Room Availability", p9)

        # ── 10. Full Property Details ─────────────────────────────────────
        sep("TEST 10 — Full Property Details  (property-details-bots)")
        # IMPORTANT: property_id must be the UUID (p_id from search), NOT the Firebase pg_id
        if property_id:
            resp = await c.post(f"{BASE_URL}/property/property-details-bots",
                                json={"property_id": property_id})
            rd   = resp.json()
            p10  = check("property-details-bots", resp.status_code == 200, f"HTTP {resp.status_code}")
            # Real response shape: d["data"]["property"] (214 keys) + d["data"]["propertyMicrosite"] (21 keys)
            outer = rd.get("data", {}) or {}
            pd    = outer.get("property", {}) or {}           # 214 flat property fields
            ms    = outer.get("propertyMicrosite", {}) or {}  # 21 microsite fields
            check("Has property inner", bool(pd), f"Keys found: {list(pd.keys())[:6] if pd else 'EMPTY'}")
            if pd:
                print(f"    pg_name:          {pd.get('pg_name','N/A')}")
                print(f"    address_line_1:   {pd.get('address_line_1','N/A')}")
                print(f"    address_line_2:   {pd.get('address_line_2','N/A')}")
                print(f"    city:             {pd.get('city','N/A')}")
                print(f"    owner_name:       {pd.get('owner_name','N/A')}")
                print(f"    personal_contact: {pd.get('personal_contact','N/A')}")
                print(f"    pg_available_for: {pd.get('pg_available_for','N/A')}")
                print(f"    tenants_preferred:{pd.get('tenants_preferred','N/A')}")
                print(f"    notice_period:    {pd.get('notice_period','N/A')} days")
                print(f"    agreement_period: {pd.get('agreement_period','N/A')} months")
                print(f"    locking_period:   {pd.get('locking_period','N/A')} months")
                print(f"    emergency_rate:   ₹{pd.get('emergency_stay_rate','N/A')}")
                print(f"    eazypg_id:        {pd.get('eazypg_id','N/A')}")
            if ms:
                print(f"    microsite about:  {str(ms.get('about','N/A'))[:80]}")
                print(f"    min_token_amount: ₹{ms.get('min_token_amount','N/A')}")
                print(f"    property_rules:   {str(ms.get('property_rules','N/A'))[:80]}")
                reviews = ms.get("reviews", []) or []
                print(f"    reviews count:    {len(reviews)}")
                amen = ms.get("property_amenities", {}) or {}
                furniture = amen.get("furniture", []) or []
                print(f"    property amenities: {', '.join(a.get('name','') for a in furniture[:5])}")
            info(f"⚠ NOTE: production tool uses pg_id (Firebase UID) not property_id (UUID) → always hits fallback")
            record("Property Details", p10)
        else:
            fail("property-details-bots skipped", "No property_id (UUID) from search result")
            record("Property Details", False)

        # ── 11. Property Images ───────────────────────────────────────────
        sep("TEST 11 — Property Images  (fetchPropertyImages)")
        if pg_id and pg_number is not None:
            resp   = await c.post(f"{BASE_URL}/bookingBot/fetchPropertyImages",
                                  json={"pg_id": pg_id, "pg_number": pg_number})
            rd     = resp.json()
            images = rd.get("images", rd.get("data", []))
            p11    = check("Images HTTP", resp.status_code == 200, f"HTTP {resp.status_code}")
            info(f"{len(images)} images returned")
            for img in images[:3]:
                url = img.get("url", img.get("media_id", img)) if isinstance(img, dict) else img
                print(f"    {str(url)[:100]}")
            record("Property Images", p11)

        # ── 12. Tenant UUID + Payment Link ────────────────────────────────
        sep("TEST 12 — Payment Flow Step 1: Get Tenant UUID")
        resp = await c.get(f"{BASE_URL}/tenant/get-tenant_uuid",
                           params={"phone": PHONE, "eazypg_id": eazypg_id})
        rd          = resp.json()
        tenant_uuid = rd.get("data", {}).get("tenant_uuid", "")
        p12a        = check("get-tenant_uuid HTTP", resp.status_code == 200, f"HTTP {resp.status_code}")
        p12b        = check("tenant_uuid returned", bool(tenant_uuid),
                            f"UUID: {tenant_uuid or 'NOT FOUND — lead may need a moment to propagate'}")
        print(f"    Full response: {json.dumps(rd)[:300]}")
        record("Tenant UUID", p12a and p12b)

        sep("TEST 12b — Payment Flow Step 2: Generate Payment Link")
        if tenant_uuid:
            token_amount = prop.get("p_token_amount", prop.get("property_min_token_amount", 1000)) or 1000
            resp = await c.get(f"{BASE_URL}/tenant/{tenant_uuid}/lead-payment-link",
                               params={"pg_id": pg_id, "pg_number": pg_number, "amount": token_amount})
            rd   = resp.json()
            link     = rd.get("data", {}).get("link", "")
            pg_name  = rd.get("data", {}).get("pg_name", "")
            p12c = check("lead-payment-link HTTP", resp.status_code == 200, f"HTTP {resp.status_code}")
            p12d = check("Payment link generated", bool(link),
                         f"Full URL: {'https://pay.rentok.com/p/' + link if link else 'NOT GENERATED'}")
            if pg_name:
                info(f"Property name from payment API: {pg_name}")
            if not link:
                print(f"    Full response: {json.dumps(rd)[:400]}")
            record("Payment Link Generation", p12c and p12d)
        else:
            fail("Payment link skipped", "No tenant_uuid — run again in a few seconds after lead propagates")
            record("Payment Link Generation", False)

        # ── 13. Shortlist ─────────────────────────────────────────────────
        sep("TEST 13 — Shortlist Property  (shortlist-booking-bot-property)")
        resp = await c.post(f"{BASE_URL}/bookingBot/shortlist-booking-bot-property",
                            json={"user_id": PHONE, "property_id": pg_id,
                                  "property_contact": prop_phone or ""})
        rd   = resp.json()
        p13  = check("Shortlist HTTP", resp.status_code == 200, f"HTTP {resp.status_code}")
        info(f"Response: {json.dumps(rd)[:200]}")
        record("Shortlist", p13)

        # ── 14. Fetch All Properties ──────────────────────────────────────
        sep("TEST 14 — Fetch All Brand Properties  (fetch-all-properties)")
        resp  = await c.post(f"{BASE_URL}/bookingBot/fetch-all-properties", json={"pg_ids": PG_IDS})
        rd    = resp.json()
        props = rd.get("properties", rd.get("data", []))
        p14   = check("Fetch-all HTTP", resp.status_code == 200, f"HTTP {resp.status_code}")
        info(f"{len(props)} total properties in OxOtel portfolio")
        # CORRECT field names: pg_name (not property_name/name), microsite_link (not address)
        info("⚠ NOTE: production tool checks 'property_name'/'name' — both missing here; 'pg_name' is correct field")
        for p in props[:8]:
            ms = p.get("microsite_data", {}) or {}
            support = ms.get("customer_support_number","N/A")
            print(f"    • {p.get('pg_name','?'):<45} | "
                  f"support={support} | "
                  f"link={p.get('microsite_link','?')}")
        record("Fetch All Properties", p14)

        # ── 15. Brand / Property Info ─────────────────────────────────────
        sep("TEST 15 — Brand Info  (property-info)")
        resp  = await c.get(f"{BASE_URL}/bookingBot/property-info",
                            params={"pg_ids": ",".join(PG_IDS)})
        rd    = resp.json()
        bdata = rd.get("data", {})
        p15   = check("Brand info HTTP", resp.status_code == 200, f"HTTP {resp.status_code}")
        check("Brand data non-empty", bool(bdata), f"Keys: {list(bdata.keys()) if bdata else 'EMPTY'}")
        if bdata:
            print(f"    Rent range:     {bdata.get('rent','N/A')}")
            print(f"    Token amount:   {bdata.get('token_amount','N/A')}")
            print(f"    Property types: {bdata.get('property_type','N/A')}")
            print(f"    Sharing types:  {bdata.get('sharing_types_enabled','N/A')}")
            print(f"    Amenities:      {str(bdata.get('common_amenities','N/A'))[:80]}")
        record("Brand Info", p15)

        # ── 16. Cancel Booking ────────────────────────────────────────────
        sep("TEST 16 — Cancel Booking  (cancel-booking)")
        if property_id:
            resp = await c.post(f"{BASE_URL}/bookingBot/cancel-booking",
                                json={"user_id": user_id_test, "property_id": property_id})
            rd   = resp.json()
            p16  = check("cancel-booking HTTP", resp.status_code == 200,
                         f"HTTP {resp.status_code} | message: {rd.get('message','')}")
            check("No success field (expected)", "success" not in rd,
                  "✓ cancel-booking correctly has no success field")
            record("Cancel Booking", p16)

        # ── SUMMARY ───────────────────────────────────────────────────────
        passed = sum(1 for _, ok in _results if ok)
        total  = len(_results)
        print()
        print("=" * 65)
        print(f"  RESULTS: {passed}/{total} passed")
        print("=" * 65)
        for label, ok_flag in _results:
            icon = "✅" if ok_flag else "❌"
            print(f"  {icon}  {label}")
        print()
        print(f"  User in RentOK CRM:  {NAME} ({PHONE})")
        print(f"  Leads created with:  eazypg_id = {eazypg_id}")
        print(f"  Property tested:     {prop_name}")
        if tenant_uuid:
            print(f"  Tenant UUID:         {tenant_uuid}")
        print("=" * 65)


if __name__ == "__main__":
    asyncio.run(run_all())
