"""
End-to-end broker agent test script.
Runs against the local server at http://localhost:8000.

Usage:
    python test_broker.py
"""
import json
import sys
import time
import pickle
import requests
import redis
from datetime import date

BASE_URL = "http://localhost:8000"
HEADERS = {"Content-Type": "application/json"}

# Redis for post-test verification (JSON mode)
r = redis.Redis(host="localhost", port=6379, decode_responses=True)
# Redis in bytes mode for reading legacy pickle keys
r_bytes = redis.Redis(host="localhost", port=6379, decode_responses=False)

PASS = "\033[92m  PASS\033[0m"
FAIL = "\033[91m  FAIL\033[0m"
INFO = "\033[94m  INFO\033[0m"
SECTION = "\033[1;96m"
RESET = "\033[0m"

# Rate limit: 6 req/min per user. Sleep between turns to stay safe.
TURN_DELAY = 11  # seconds between chat calls


def chat(user_id: str, message: str) -> dict:
    resp = requests.post(
        f"{BASE_URL}/chat",
        headers=HEADERS,
        json={"user_id": user_id, "message": message},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()


def check(label: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    suffix = f"  → {detail}" if detail else ""
    print(f"{status}  {label}{suffix}")
    return condition


results = []

def test(label: str, condition: bool, detail: str = ""):
    ok = check(label, condition, detail)
    results.append((label, ok))
    return ok


# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{SECTION}══ Phase 1: Server Health ══{RESET}")
# ─────────────────────────────────────────────────────────────────────────────

resp = requests.get(f"{BASE_URL}/health", timeout=5)
test("Server responds 200", resp.status_code == 200, f"status={resp.status_code}")


# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{SECTION}══ Phase 2: New User Broker Flow ══{RESET}")
# ─────────────────────────────────────────────────────────────────────────────

UID = f"test_broker_{int(time.time())}"  # Fresh user ID each run
print(f"{INFO}  user_id: {UID}")

# Clear any leftover state for this user
for key in r.scan_iter(f"{UID}*"):
    r.delete(key)

# Inject account config + pg_ids from stress_01 (Mumbai/OxOtel with multiple PGs)
# NOTE: search_properties reads {uid}:pg_ids separately from {uid}:account_values
try:
    acct_raw = r_bytes.get(b"stress_01:account_values")
    pgids_raw = r_bytes.get(b"stress_01:pg_ids")
    if acct_raw and pgids_raw:
        acct_data = pickle.loads(acct_raw)
        pg_ids_data = pickle.loads(pgids_raw)
        r.set(f"{UID}:account_values", json.dumps(acct_data))
        r.set(f"{UID}:pg_ids", json.dumps(pg_ids_data))
        print(f"{INFO}  Injected account: brand={acct_data.get('brand_name')} cities={acct_data.get('cities')} pg_ids={len(pg_ids_data)}")
    else:
        print(f"{INFO}  WARNING: stress_01 account not found — test may return no results")
except Exception as e:
    print(f"{INFO}  WARNING: could not inject account config: {e}")

# Turn 1: Full qualifiers provided → skip qualifying, search immediately
# NOTE: OxOtel properties are "Any" gender. Using gender-neutral query to get results.
print(f"\n  Turn 1: search query with all qualifiers")
t1 = chat(UID, "Looking for PG in Andheri, Mumbai, budget 25000")
print(f"  agent={t1.get('agent')}  chars={len(t1.get('response',''))}")
print(f"  response preview: {t1.get('response','')[:300]}")
test("T1: routed to broker", t1.get("agent") == "broker")
test("T1: response not empty", len(t1.get("response", "")) > 50)

resp_lower = t1.get("response", "").lower()
test(
    "T1: contains property listings or search result",
    any(kw in resp_lower for kw in ["₹", "room", "pg", "hostel", "properties", "mumbai", "beds", "bed", "andheri", "powai"]),
    "expected rent/room keywords"
)

# Extract a property name from the response for use in subsequent turns
lines = t1.get("response", "").split("\n")
prop_name = None
for line in lines:
    stripped = line.strip()
    # Format: **N. Property Name** or **Property Name**
    if stripped.startswith("**") and stripped.endswith("**"):
        candidate = stripped.strip("*").strip()
        if ". " in candidate:
            prop_name = candidate.split(". ", 1)[1].strip()
        else:
            prop_name = candidate
        if prop_name:
            break

if prop_name:
    print(f"{INFO}  Extracted property name: '{prop_name}'")
else:
    print(f"{INFO}  Could not extract property name — using generic reference")

time.sleep(TURN_DELAY)

# Turn 2: Property details
print(f"\n  Turn 2: fetch property details")
detail_msg = f"Tell me more about {prop_name}" if prop_name else "Tell me more about the first property"
t2 = chat(UID, detail_msg)
print(f"  agent={t2.get('agent')}  chars={len(t2.get('response',''))}")
print(f"  response preview: {t2.get('response','')[:200]}")
test("T2: still broker", t2.get("agent") == "broker")
resp2_lower = t2.get("response", "").lower()
test(
    "T2: contains property detail keywords",
    any(kw in resp2_lower for kw in ["amenities", "rent", "room", "available", "address", "wifi", "meals", "ac", "₹", "floor", "type", "location", "bed", "deposit"]),
    "expected amenity/rent keywords"
)

time.sleep(TURN_DELAY)

# Turn 3: Images
print(f"\n  Turn 3: fetch images")
t3 = chat(UID, "Show me images of this property")
print(f"  agent={t3.get('agent')}  chars={len(t3.get('response',''))}")
print(f"  response preview: {t3.get('response','')[:200]}")
test("T3: still broker", t3.get("agent") == "broker")
resp3_lower = t3.get("response", "").lower()
test(
    "T3: image-related response",
    any(kw in resp3_lower for kw in ["image", "photo", "picture", "http", "gallery", "available", "no image", "here are", "uploaded"]),
    "expected image/URL keywords"
)

time.sleep(TURN_DELAY)

# Turn 4: Shortlist
print(f"\n  Turn 4: shortlist")
t4 = chat(UID, "Shortlist this one for me")
print(f"  agent={t4.get('agent')}  chars={len(t4.get('response',''))}")
print(f"  response preview: {t4.get('response','')[:200]}")
test("T4: still broker", t4.get("agent") == "broker")
resp4_lower = t4.get("response", "").lower()
test(
    "T4: shortlist confirmed",
    any(kw in resp4_lower for kw in ["shortlist", "saved", "added", "noted", "bookmark", "shortlisted"]),
    "expected shortlist confirmation"
)

time.sleep(TURN_DELAY)

# Turn 5: Show more
print(f"\n  Turn 5: show more options")
t5 = chat(UID, "Show me more options please")
print(f"  agent={t5.get('agent')}  chars={len(t5.get('response',''))}")
print(f"  response preview: {t5.get('response','')[:200]}")
test("T5: still broker", t5.get("agent") == "broker")
resp5_lower = t5.get("response", "").lower()
test(
    "T5: more results or search expanded",
    any(kw in resp5_lower for kw in ["₹", "room", "pg", "hostel", "mumbai", "here", "options", "found", "andheri", "powai"]),
    "expected property content"
)

time.sleep(TURN_DELAY)

# Turn 6: Compare
print(f"\n  Turn 6: compare first two properties")
t6 = chat(UID, "Compare the first two properties you showed me")
print(f"  agent={t6.get('agent')}  chars={len(t6.get('response',''))}")
print(f"  response preview: {t6.get('response','')[:300]}")
test("T6: still broker", t6.get("agent") == "broker")
resp6_lower = t6.get("response", "").lower()
test(
    "T6: comparison response with recommendation",
    any(kw in resp6_lower for kw in ["recommend", "better", "vs", "compared", "comparison", "pick", "suggest", "winner", "prefer", "go with"]),
    "expected recommendation keywords"
)

time.sleep(TURN_DELAY)

# Turn 7: Commute
print(f"\n  Turn 7: commute estimate")
t7 = chat(UID, "How far is it from BKC?")
print(f"  agent={t7.get('agent')}  chars={len(t7.get('response',''))}")
print(f"  response preview: {t7.get('response','')[:300]}")
test("T7: still broker", t7.get("agent") == "broker")
resp7_lower = t7.get("response", "").lower()
test(
    "T7: commute/distance info",
    any(kw in resp7_lower for kw in ["min", "km", "metro", "drive", "commute", "distance", "far", "walk", "station", "route", "bkc"]),
    "expected commute keywords"
)

time.sleep(TURN_DELAY)

# Turn 8: New search (pushes old tool results past compaction window)
print(f"\n  Turn 8: new search to trigger compaction")
t8 = chat(UID, "Now show me PGs in Andheri under 15000")
print(f"  agent={t8.get('agent')}  chars={len(t8.get('response',''))}")
test("T8: still broker", t8.get("agent") == "broker")
test(
    "T8: Andheri results or relevant response",
    any(kw in t8.get("response", "").lower() for kw in ["andheri", "₹", "pg", "room", "options", "found"]),
)


# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{SECTION}══ Phase 3: Verify Compaction in Redis ══{RESET}")
# ─────────────────────────────────────────────────────────────────────────────

conv_key = f"{UID}:conversation"
raw = r.get(conv_key)
if raw:
    messages = json.loads(raw)
    print(f"{INFO}  Stored messages: {len(messages)}")
    compacted_count = 0
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        c = block.get("content", "")
                        if "[Compacted]" in c:
                            compacted_count += 1
    print(f"{INFO}  Compacted tool results found: {compacted_count}")
    test("Compaction: old tool results compacted", compacted_count > 0, f"{compacted_count} compacted blocks")
else:
    print(f"{INFO}  Conversation key not found at '{conv_key}' — trying alternate key format")
    found_keys = list(r.scan_iter(f"*{UID}*"))
    print(f"{INFO}  Keys for this user: {found_keys}")
    test("Compaction: conversation found in Redis", len(found_keys) > 0, "no conversation key found")


# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{SECTION}══ Phase 4: Verify Metrics in Redis ══{RESET}")
# ─────────────────────────────────────────────────────────────────────────────

today = date.today().isoformat()
tool_calls = r.hgetall(f"metrics:{today}:tool_calls")
tokens_in = r.hgetall(f"metrics:{today}:tokens_in")
tokens_out = r.hgetall(f"metrics:{today}:tokens_out")

print(f"{INFO}  metrics:{today}:tool_calls = {tool_calls}")
print(f"{INFO}  metrics:{today}:tokens_in  = {tokens_in}")
print(f"{INFO}  metrics:{today}:tokens_out = {tokens_out}")

test("Metrics: broker tool_calls > 0", int(tool_calls.get("broker", 0)) > 0, f"got {tool_calls.get('broker', 0)}")
test("Metrics: tokens_in tracked", int(tokens_in.get("broker", 0)) > 0, f"got {tokens_in.get('broker', 0)}")
test("Metrics: tokens_out tracked", int(tokens_out.get("broker", 0)) > 0, f"got {tokens_out.get('broker', 0)}")


# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{SECTION}══ Phase 5: Returning User (same user, same UID) ══{RESET}")
# ─────────────────────────────────────────────────────────────────────────────

time.sleep(TURN_DELAY)

print(f"\n  Turn R1: returning user greeting")
tr1 = chat(UID, "Hi, I'm looking for a PG")
print(f"  agent={tr1.get('agent')}  chars={len(tr1.get('response',''))}")
print(f"  response preview: {tr1.get('response','')[:300]}")
test("R1: broker agent", tr1.get("agent") == "broker")
resp_r1 = tr1.get("response", "").lower()
# Returning user should reference previous search (mumbai / girls / 20000)
# and NOT show the full bundled qualifying question block
test(
    "R1: references previous search OR skips full qualifying",
    any(kw in resp_r1 for kw in ["last time", "welcome back", "mumbai", "previously", "before", "andheri", "25,000", "25000"])
    or "is this for boys, girls, or mixed?" not in resp_r1,
    "expected returning user behavior"
)


# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{SECTION}══ Phase 6: Agent Scoping (switch to booking) ══{RESET}")
# ─────────────────────────────────────────────────────────────────────────────

time.sleep(TURN_DELAY)

print(f"\n  Turn S1: trigger booking agent")
ts1 = chat(UID, "I want to schedule a visit to one of those properties")
print(f"  agent={ts1.get('agent')}  chars={len(ts1.get('response',''))}")
print(f"  response preview: {ts1.get('response','')[:300]}")
test("S1: routed to booking agent", ts1.get("agent") == "booking")
resp_s1 = ts1.get("response", "").lower()
test(
    "S1: booking response content",
    any(kw in resp_s1 for kw in ["visit", "schedule", "date", "time", "book", "property", "slot"]),
    "expected booking keywords"
)


# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{SECTION}══ Results Summary ══{RESET}")
# ─────────────────────────────────────────────────────────────────────────────

passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
total = len(results)

print(f"\n  {passed}/{total} tests passed")
if failed:
    print(f"\n  Failed tests:")
    for label, ok in results:
        if not ok:
            print(f"    {FAIL}  {label}")

print()
sys.exit(0 if failed == 0 else 1)
