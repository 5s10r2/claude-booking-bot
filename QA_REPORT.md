# End-to-End QA Report — Claude Booking Bot
**Date:** 2026-02-24
**Test Method:** curl → FastAPI /chat endpoint
**Server:** uvicorn main:app on localhost:8000
**PG IDs:** OxOtel Mumbai (10 IDs)
**Brand:** OxOtel | Cities: Mumbai | Areas: Andheri, Kurla, Powai

---

## Test Results Summary

| # | Test | Agent Expected | Agent Actual | Result | Issue |
|---|------|---------------|-------------|--------|-------|
| 1 | Broker: Mumbai flat search | broker | broker | ✅ PASS | 11 properties found |
| 2 | Broker: PG boys Andheri ₹10k | broker | broker | ⚠️ WARN | No results (may be legitimate - low budget for area) |
| 3 | Broker: show more / next batch | broker | broker | ✅ PASS | Properties 6-10 shown correctly |
| 4 | Broker: property details | broker | broker | ⚠️ WARN | Tool called, returned data, but Claude said "info didn't load properly" |
| 5 | Broker: shortlist property | broker → default | default | ⚠️ WARN | Shortlisted OK, but "yes shortlist it" continuation routed to default |
| 6 | Broker: change preferences | broker | broker | ✅ PASS | 39 results in Kurla after pref change |
| 7 | Booking: schedule visit | booking | booking | ✅ PASS | Asked for confirmation correctly |
| 8 | Booking: confirm "yes, tomorrow 2pm" | booking | default | ⚠️ WARN | Visit scheduled BUT routed to default agent |
| 9 | Booking: video tour (fresh user) | booking | booking | ⚠️ WARN | Property not found - no search context for this user |
| 10 | Booking: reserve bed | booking | booking | ✅ PASS | Asked for Aadhaar correctly |
| 11 | Profile: fetch details | profile | broker | ❌ FAIL | Routed to broker, said "don't have access" |
| 12 | Profile: scheduled events | profile | broker | ❌ FAIL | Routed to broker, told user to "go to website" |
| 13 | Profile: shortlisted properties | profile | broker | ❌ FAIL | Routed to broker, told user to "go to website" |
| 14 | Default: greeting "Hello" | default | default | ✅ PASS | Warm greeting, correct routing |
| 15 | Default: off-topic (weather) | default | default | ✅ PASS | Redirected to rental help gracefully |
| 16 | Supervisor: Hindi "kamra chahiye Mumbai" | broker | default | ⚠️ WARN | Hindi word "kamra" (room) not in keyword list |
| 17 | Supervisor: "place to stay near Powai" | broker | default | ⚠️ WARN | "place" and "stay" not in broker keyword list |
| 18 | Supervisor: "pay token amount" | booking | booking | ✅ PASS | Correct routing |
| 19 | Supervisor: "cancel my booking" | booking | booking | ✅ PASS | Correct routing |
| 20 | Supervisor: "show me upcoming visits" | profile | broker | ❌ FAIL | "show" matched broker keyword, not profile |
| 21 | Broker: 2BHK Andheri ₹25k | broker | broker | ✅ PASS | No results but helpful suggestions |
| 22 | Broker: Hinglish girls PG | broker | broker | ✅ PASS | No results but helpful Hinglish response |
| 23 | Supervisor: "saved preferences" | profile | default | ❌ FAIL | No profile keywords in fallback |
| 24 | Broker: ambiguous follow-up (no context) | broker | broker | ✅ PASS | Correctly asked for search context |
| 25 | Booking: Hinglish "book karo visit" | booking | booking | ✅ PASS | Correct routing + response |

**Score: 13 PASS / 7 WARN / 5 FAIL out of 25 tests**

---

## CRITICAL ISSUES (Must Fix)

### ISSUE #1: Supervisor classify() fails 100% of the time
**Severity:** 🔴 CRITICAL
**Where:** `core/claude.py` → `classify()` method (lines 79-109)
**What:** Every single test shows ALL 3 classify attempts failing with:
```
[claude] classify attempt 1 failed: Expecting value: line 1 column 1 (char 0)
[claude] classify attempt 2 failed: Expecting value: line 1 column 1 (char 0)
[claude] classify attempt 3 failed: Expecting value: line 1 column 1 (char 0)
```
**Root Cause:** Haiku returns the JSON wrapped in markdown code fences (e.g., `` ```json\n{"agent":"broker"}\n``` ``) or with extra text. `json.loads()` fails because the raw response starts with `` ` `` not `{`. The `_extract_text()` method strips text blocks but doesn't strip markdown formatting.
**Impact:** The supervisor NEVER routes correctly. 100% of routing falls to the keyword safety net in `main.py`. The supervisor is essentially dead code — we're paying for 3 Haiku API calls per message for nothing.
**Evidence:** Every test in server logs shows 3 failed classify attempts before keyword fallback.

---

### ISSUE #2: Profile agent is COMPLETELY UNREACHABLE
**Severity:** 🔴 CRITICAL
**Where:** `main.py` → `run_pipeline()` (lines 110-127)
**What:** The keyword safety net has broker_keywords and booking_keywords but **ZERO profile keywords**. Since the supervisor always fails (Issue #1), and there's no `profile_keywords` set in the fallback, the profile agent can NEVER be reached.
**Root Cause:** Missing `profile_keywords` set in `main.py` keyword fallback.
**Impact:** Tests 11, 12, 13, 20, 23 all fail — every profile query either goes to broker (if it contains "show") or stays at default.
**Evidence:**
```
Test 11: "show me my profile details" → agent=broker (keyword "show" matches broker)
Test 12: "show my scheduled events" → agent=broker
Test 13: "show my shortlisted properties" → agent=broker
Test 20: "show me my upcoming visits" → agent=broker
Test 23: "what are my saved preferences" → agent=default (no keyword match at all)
```
**Fix needed:** Add `profile_keywords` set with: `{"profile", "preference", "preferences", "saved", "shortlist", "shortlisted", "history", "events", "upcoming", "past", "my bookings", "my visits"}`
**Priority order:** Profile keywords should be checked BEFORE broker keywords since "show" appears in both contexts.

---

### ISSUE #3: Broker agent violates "NEVER tell user to go to website" rule
**Severity:** 🔴 CRITICAL (UX / Product)
**Where:** `core/prompts.py` → BROKER_AGENT_PROMPT behavior
**What:** When the broker agent receives profile-type queries (due to mis-routing from Issue #2), it responds with:
- "I don't have the ability to view or manage your scheduled visits"
- "You can check your profile on the website/app"
**Evidence:** Tests 11, 12, 20 all show the broker saying it can't help and directing users elsewhere.
**Why it matters:** The prompt explicitly says "NEVER tell the user to go to an app/website themselves — this IS the service" and "NEVER say you can't access something". But when broker gets profile queries, it has no choice — it genuinely can't help.
**Real fix:** Fix Issue #2 (route to profile agent). The broker behavior is technically correct for its capabilities — it just should never receive these queries.

---

### ISSUE #4: "yes/ok/sure" continuations lose agent context
**Severity:** 🟡 HIGH
**Where:** `main.py` → `run_pipeline()` keyword fallback (lines 110-127)
**What:** When user says "yes", "ok", "sure", "go ahead" in response to an agent's question, the keyword fallback doesn't match any keywords → routes to "default".
**Evidence:**
- Test 5: Broker asks "Want me to shortlist it?" → User: "yes shortlist it" → agent=default (keyword "shortlist" isn't in broker keywords... wait actually it is not. But "shortlist" IS a valid broker action)
- Test 8: Booking asks "Should I schedule?" → User: "yes, tomorrow at 2pm" → agent=default ("yes" + "tomorrow" + "2pm" don't match any keywords)
**Root Cause:** The keyword fallback has no concept of conversation context. The SUPERVISOR_PROMPT has rules 4 and 5 for handling "yes/ok" based on previous bot message, but since the supervisor always fails (Issue #1), this logic is never applied.
**Impact:** Multi-turn conversations break after the first message. Every confirmation/follow-up potentially routes to wrong agent.
**Possible fixes:**
  a. Fix supervisor classify so it works (Issue #1) — the prompt already handles "yes" context
  b. Add a "last_agent" tracker in Redis that persists the previous agent for a user, and default to it for generic affirmatives
  c. Add affirmative words ("yes", "ok", "sure", "haan", "theek hai") as a special case in keyword fallback that uses last agent

---

## MEDIUM ISSUES

### ISSUE #5: Hindi/Hinglish messages without English keywords miss routing
**Severity:** 🟡 MEDIUM
**Where:** `main.py` → keyword fallback (lines 112-127)
**What:** Pure Hindi messages that don't contain any English keywords get routed to "default" even when intent is clear.
**Evidence:**
- Test 16: "mujhe ek kamra chahiye Mumbai mein" (I need a room in Mumbai) → agent=default ("kamra" = room in Hindi, not in keywords)
- Test 22: "kya aapke paas koi girls PG hai Andheri mein?" → agent=broker (because "PG" and "girls" are in English)
**Fix needed:** Add common Hindi/Hinglish property terms to keyword sets:
- Broker: "kamra", "kiraya", "ghar", "chahiye", "dikhao", "jagah", "rehne"
- Booking: "milna", "dekhna", "visit karo"
- Or: Fix the supervisor (Issue #1) since the LLM can handle any language

---

### ISSUE #6: "place to stay" doesn't trigger broker routing
**Severity:** 🟡 MEDIUM
**Where:** `main.py` → broker_keywords set
**What:** Natural language variations like "place to stay", "accommodation", "housing", "need a place" don't match any broker keywords.
**Evidence:** Test 17: "I need a place to stay near Powai" → agent=default
**Fix needed:** Add more natural language keywords: "place", "stay", "accommodation", "housing", "nearby", "near"

---

### ISSUE #7: fetch_property_details returns data but Claude says "didn't load properly"
**Severity:** 🟡 MEDIUM
**Where:** `tools/broker/details.py` → `fetch_property_details()` and/or BROKER_AGENT_PROMPT
**What:** The tool was called and returned "PROPERTY DETAILS: DREAM HOUSE 802" but Claude told the user "the detailed info didn't load properly for that specific property."
**Evidence:** Test 4 — tool called with correct property name, returned a result string, but agent interpreted it as failure.
**Possible causes:**
  a. The returned string is mostly empty/minimal (property may not have detailed data in Rentok API)
  b. The response format doesn't match what Claude expects to see
  c. The result string starts with a header but has no actual data fields
**Investigation needed:** Check what `fetch_property_details` actually returns — may need to add error handling for API returning empty detail objects.

---

### ISSUE #8: Booking agent can't find properties for users who haven't searched
**Severity:** 🟡 MEDIUM
**Where:** Cross-agent property context in Redis
**What:** When a fresh user (no prior search) goes directly to booking with a property name, the booking tools can't find the property because `property_info_map` in Redis is empty for that user.
**Evidence:** Test 9 — qa03 (fresh user) asked for video tour of "DREAM HOUSE 702" → tool returned "Property not found" because qa03 never searched.
**Root Cause:** Property info is stored per-user in Redis (key `{user_id}:property_info_map`). Booking tools look up property by name in this map. If user hasn't searched, map is empty.
**Possible fixes:**
  a. When booking can't find property, automatically search for it using the Rentok API
  b. Store a global property cache (not per-user)
  c. Have booking agent tell user to search first (current behavior, but poor UX)

---

### ISSUE #9: Default agent asks 3+ questions at once
**Severity:** 🟢 LOW (UX improvement)
**Where:** `core/prompts.py` → DEFAULT_AGENT_PROMPT behavior
**What:** When default agent handles property-adjacent queries (due to mis-routing), it asks 3 questions in bullets instead of 1 at a time.
**Evidence:** Test 16 response:
```
- Budget kya hai? (monthly rent range)
- Kaunse area mein prefer karte ho?
- Kya chahiye? (single room, studio, shared, AC, kitchen access, etc.)
```
Test 17 response also showed 3 bullet-point questions.
**Why it matters:** The BROKER_AGENT_PROMPT says "Ask ONE question at a time, keep questions under 15 words". The default agent doesn't have this rule, and when it handles mis-routed broker queries, it over-asks.
**Fix:** Either fix routing so default never gets these queries, or add "ask ONE question at a time" to DEFAULT_AGENT_PROMPT.

---

### ISSUE #10: No images or microsite URLs in many property results
**Severity:** 🟢 LOW (Data quality)
**Where:** `tools/broker/search.py` → property field extraction
**What:** Many properties in search results have empty `p_image` and `p_microsite_url` fields.
**Evidence:** Test 1 results — several properties showed "Image: | Link:" with empty values.
**Root Cause:** The Rentok API doesn't return these fields for all properties. This is a data issue, not a code issue.
**Possible improvement:** If no image URL, omit the image line. If no microsite URL, omit the link line. Don't show empty fields.

---

## IMPROVEMENTS (Nice-to-have)

### IMPROVEMENT #1: Add debug logging to supervisor classify
**What:** Log what Haiku actually returns before json.loads. Currently we only see the exception. We need to see the raw text to understand the format.
**Where:** `core/claude.py` → `classify()` method
**Add:** `print(f"[classify] raw text: {repr(text)}")` before the `json.loads(text)` call.

### IMPROVEMENT #2: Strip markdown code fences in classify
**What:** Haiku likely returns `` ```json\n{"agent":"broker"}\n``` ``. Add a simple regex to strip code fences before `json.loads`.
**Where:** `core/claude.py` → `classify()` method

### IMPROVEMENT #3: Track last active agent per user
**What:** Store `{user_id}:last_agent` in Redis. When keyword fallback can't determine agent and user sends a short affirmative ("yes", "ok", "haan"), fall back to last_agent instead of "default".
**Where:** `main.py` → `run_pipeline()` and `db/redis_store.py`

### IMPROVEMENT #4: Add "shortlist" to broker_keywords
**What:** The word "shortlist" is a broker action but isn't in broker_keywords. Add it.
**Where:** `main.py` → broker_keywords set

### IMPROVEMENT #5: Smarter property display — hide empty fields
**What:** Don't show "Image: | Link:" when values are empty. Only display fields that have data.
**Where:** `tools/broker/search.py` → result formatting (lines 155-160)

### IMPROVEMENT #6: Add response time logging
**What:** Log total pipeline time (supervisor + agent) per request for performance monitoring.
**Where:** `main.py` → `run_pipeline()`

### IMPROVEMENT #7: Conversation history pruning
**What:** Long conversations accumulate messages and increase token usage. Add a max history length (e.g., last 20 messages).
**Where:** `core/conversation.py`

### IMPROVEMENT #8: Brand info tool for default agent
**What:** The default agent prompt mentions "TOOL: brand_info — Call this ONLY when the user explicitly asks about the brand" but Test 23 showed the default agent calling brand_info for a "saved preferences" query, which isn't brand-related. The tool seems to be called too eagerly.
**Where:** `core/prompts.py` → DEFAULT_AGENT_PROMPT tool calling rules

---

## Architecture Summary

```
User Message
    ↓
Supervisor classify() [BROKEN - always fails]
    ↓
Keyword Safety Net [WORKS but incomplete]
    ↓
Agent Selection
    ├── default → ✅ Works for greetings, off-topic
    ├── broker → ✅ Works for property search (tools called correctly)
    ├── booking → ✅ Works for scheduling, payments, KYC
    └── profile → ❌ UNREACHABLE (no keywords route here)
```

**What works well:**
- Broker agent tool-calling flow (save_preferences → search_properties → display)
- Booking agent multi-step flows (visit, call, reserve bed, KYC)
- Search API integration (geocoding + property search)
- Hinglish/multilingual responses
- Property type mapping (flat → BHK, PG → ROOM)
- Budget and gender filtering

**What's broken:**
- Supervisor LLM classification (0% success rate)
- Profile agent routing (100% unreachable)
- Multi-turn conversation continuity (affirmatives lose context)
- Hindi-only keyword coverage

---

## Priority Fix Order (Recommended)

1. **ISSUE #1** — Fix supervisor classify (strip markdown fences from Haiku response)
2. **ISSUE #2** — Add profile_keywords to keyword fallback in main.py
3. **ISSUE #4** — Add last_agent tracking for "yes/ok" continuations
4. **ISSUE #5** — Add Hindi keywords to fallback
5. **ISSUE #6** — Add natural language keywords ("place", "stay", "near")
6. **ISSUE #7** — Investigate fetch_property_details return format
7. **ISSUE #8** — Handle booking for users without search context
8. **ISSUE #3** — Will auto-resolve when Issues #1 and #2 are fixed
9. **ISSUE #9** — Minor UX improvement
10. **ISSUE #10** — Minor display improvement
