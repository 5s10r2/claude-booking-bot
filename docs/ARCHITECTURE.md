# EazyPG Booking Bot — Deep Architecture Reference

Read this file only when you need detailed information about Redis keys, Rentok APIs, agent-tool mapping, or conversation lifecycle. For quick orientation, use CLAUDE.md instead.

---

## Request Lifecycle

### WhatsApp Flow (Phase B: Queue + Debounce)
```
User sends message on WhatsApp
  → Meta/Interakt webhook → POST /webhook/whatsapp (routers/webhooks.py)
  → Extract user_id (phone: 919876543210), message text, account_values
  → Dedup by wamid (is_wamid_seen) — skip if already processed
  → Store account_values in Redis (whitelabel config: pg_ids, brand_name, tokens)
  → Tag user with brand_hash (set_user_brand)
  → wa_queue_push(user_id, message) → Redis list
  → If no drain task running (wa_processing_acquire):
    → asyncio.create_task(_drain_and_process)
      → Sleep WA_DEBOUNCE_SECONDS (2s) — collect rapid-fire messages
      → wa_queue_drain → join all queued messages
      → run_pipeline(user_id, combined_message, brand_hash)
        → rate_limiter.check_rate_limit (sliding window: 6/min, 30/hr, 100/min global)
        → Check human_mode (brand-scoped: {uid}:{brand_hash}:human_mode)
        → load conversation history from Redis
        → _route_agent: keyword safety net → supervisor LLM → fallback to last_agent
        → agent.run() with tools (Anthropic tool_use loop, max 15 iterations)
          → Phase C: check cancel_requested between tool iterations
        → save conversation to Redis (brand_hash tagged)
        → message_parser.parse_message_parts (markdown → WhatsApp-compatible parts)
        → whatsapp.send_text / send_carousel / send_image
      → If new messages arrived during processing:
        → set_cancel_requested → loop back to drain
      → wa_processing_release
  → Webhook returns 200 immediately (non-blocking)
```

### Web Chat Flow
```
User types in eazypg-chat widget
  → src/stream.js:sendMessage → POST /api/stream (Vercel serverless proxy)
  → AbortController cancels any in-flight request (Phase A: interrupt-on-send)
  → Proxy forwards to https://claude-booking-bot.onrender.com/chat/stream
  → routers/chat.py:chat_stream (SSE endpoint)
    → Same pipeline as WhatsApp but streams events:
      - agent_start: {agent_name}
      - tool_start: {tool_name}
      - content_delta: {text chunk}
      - done: {parts: [...]}  ← Generative UI parts (quick_replies, action_buttons, etc.)
  → Frontend parses SSE, renders markdown in real-time
  → Rich content: property carousels, comparison tables, maps, expandable sections
```

### Key Differences by Channel
| Aspect | WhatsApp | Web Chat |
|--------|----------|----------|
| user_id format | Pure digits: `919876543210` | Alphanumeric: `uat_k7x2m9qf` |
| Phone number | Extracted from user_id[-10:] | Must be collected via save_phone tool |
| Response format | Parsed into text/carousel/image parts | Raw markdown streamed via SSE |
| Account values | Sent in webhook payload | Via brand-config token URL param |
| Images | Uploaded to WhatsApp media API | Displayed as `<img>` tags |
| Multi-message | Queue + debounce (Phase B) | AbortController interrupt (Phase A) |
| Human mode | Brand-scoped, checked in pipeline | Brand-scoped, checked in pipeline |

---

## Redis Key Schema

All keys use `{uid}` (user_id) prefix unless noted. Redis instance is Render-managed.

### Conversation & Chat
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `{uid}:conversation` | string (JSON) | 24h | Message history (list of role/content dicts) |
| `{uid}:language` | string | 24h | Detected language: en, hi, mr |
| `{uid}:last_agent` | string | 10min | Last routed agent name for multi-turn stickiness |
| `{uid}:active_request` | string | 30s | Dedup lock — prevents concurrent requests |
| `{uid}:no_message` | string | none | Flag to suppress bot response |

### User Profile
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `{uid}:preferences` | string (JSON) | none | Location, budget, amenities, property type, move-in date |
| `{uid}:account_values` | string (JSON) | none | Whitelabel config: pg_ids, brand_name, kyc_enabled, wa_token |
| `{uid}:pg_ids` | string (JSON) | none | Whitelabel property group IDs for search filtering |
| `{uid}:user_name` | string | none | User's display name |
| `{uid}:user_phone` | string | none | 10-digit phone (web users only; WA users derive from user_id) |
| `{uid}:user_memory` | string (JSON) | none | Persistent user memory (preferences, deal-breakers, past interactions) |
| `{uid}:aadhar_name` | string | none | Full name from Aadhaar KYC |
| `{uid}:aadhar_gender` | string | none | Gender from Aadhaar KYC |

### Property Cache
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `{uid}:property_info_map` | string (JSON array) | 6 months | Cached search results with normalized metadata |
| `{uid}:property_template` | string (JSON array) | none | Top 5 properties for WA carousel |
| `{uid}:property_images_id` | string (JSON array) | none | WA media IDs for property images |
| `{uid}:image_urls` | string (JSON array) | none | Image URLs before WA upload |
| `{uid}:search_property_ids` | string (JSON array) | 10min | Recent search result IDs for deduplication |
| `search_cache:{md5}` | string (JSON) | 15min | Rentok search API response cache (keyed by payload hash) |

### Payment & Booking
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `{uid}:payment_info` | string (JSON) | none | pg_id, pg_number, amount, short_link for payment verification |

### Rate Limiting (Sorted Sets — sliding window)
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `rl:{uid}:min` | sorted set | 70s | Per-user per-minute (default: 6) |
| `rl:{uid}:hr` | sorted set | 3610s | Per-user per-hour (default: 30) |
| `rl:__global__:min` | sorted set | 70s | Global per-minute (default: 100) |

### Analytics & Feedback (Global)
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `feedback:log` | list | none | Append-only feedback entries |
| `feedback:counts` | hash | none | Aggregated counts: `{agent}:up`, `{agent}:down`, `total:up`, `total:down` |
| `agent_usage:{YYYY-MM-DD}` | hash | 90 days | Per-agent usage counts by day |
| `funnel:{YYYY-MM-DD}` | hash | 90 days | Funnel stage counts: search, detail, shortlist, visit, booking |
| `skill_usage:{YYYY-MM-DD}` | hash | 90 days | Per-skill usage counts by day |
| `skill_misses:{YYYY-MM-DD}` | hash | 90 days | Tool calls that fell back to full toolset |
| `agent_cost:{YYYY-MM-DD}` | hash | 90 days | Per-agent API cost by day |
| `daily_cost:{YYYY-MM-DD}` | hash | 90 days | Total daily API cost |

### Analytics & Feedback (Brand-Scoped — dual-write)
All analytics functions write to BOTH global keys (above) and brand-scoped keys (below). Admin endpoints read from brand-scoped keys.

| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `feedback:counts:{brand_hash}` | hash | none | Brand-scoped feedback counts |
| `funnel:{brand_hash}:{YYYY-MM-DD}` | hash | 90 days | Brand-scoped funnel events |
| `agent_usage:{brand_hash}:{YYYY-MM-DD}` | hash | 90 days | Brand-scoped agent usage |
| `skill_usage:{brand_hash}:{YYYY-MM-DD}` | hash | 90 days | Brand-scoped skill usage |
| `skill_misses:{brand_hash}:{YYYY-MM-DD}` | hash | 90 days | Brand-scoped skill misses |
| `agent_cost:{brand_hash}:{YYYY-MM-DD}` | hash | 90 days | Brand-scoped agent cost |
| `daily_cost:{brand_hash}:{YYYY-MM-DD}` | hash | 90 days | Brand-scoped daily cost |

### Brand Config & Isolation
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `brand_config:{brand_hash}` | string (JSON) | none | Full brand config (pg_ids, identity, WA creds, brand_link_token, brand_hash) |
| `brand_wa:{phone_number_id}` | string (JSON) | none | Reverse-lookup: Meta webhook phone_number_id → brand config |
| `brand_token:{uuid}` | string | none | Public chatbot link token → brand_hash |
| `brand_flags:{brand_hash}` | string (JSON) | none | Per-brand feature flag overrides |
| `{uid}:brand_hash` | string | none | User → brand mapping (persistent, set on first message) |

### Admin & Human Mode
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `active_users` | sorted set | none | Global active users (member=uid, score=unix_timestamp) |
| `active_users:{brand_hash}` | sorted set | none | Per-brand active user list |
| `{uid}:{brand_hash}:human_mode` | hash | none | Brand-scoped human takeover: `{active: "1", taken_at: timestamp}` |
| `{uid}:human_mode` | hash | none | Legacy global human mode (fallback only) |
| `{uid}:session_cost` | hash | 7 days | Session token/cost tracking: `{tokens_in, tokens_out, cost_usd}` |

### WhatsApp Multi-Turn (Phase B+C)
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `wamid:{wamid}` | string "1" | 24h | Message dedup by Meta unique wamid |
| `{uid}:wa_queue` | list | 5 min | Pending WhatsApp messages (RPUSH on arrival, LPOP on drain) |
| `{uid}:wa_processing` | string "1" (NX lock) | 2 min | Per-user drain task lock |
| `{uid}:cancel_requested` | string "1" | 30s | Pipeline cancellation signal (Phase C) |

### Observability (Sprints 1-5)
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `tool_reliability:{day}` | hash | 90d | Per-tool success/failure/latency_sum/latency_count |
| `routing_accuracy:{day}` | hash | 90d | Supervisor override counts |
| `response_latency:{day}` | hash | 90d | Per-agent latency_sum/latency_count |
| `property_events:{day}` | hash | 90d | Property lifecycle events ({property_id}:{event} count) |
| `property_events:{brand_hash}:{day}` | hash | 90d | Brand-scoped property events |
| `property_signals:{property_id}` | hash | none | Outcome counts {converted, lost, no_show} for scoring adjustments |
| `{uid}:attention_flags` | JSON list | 1h | Cached attention flags (no_response, negative_feedback, hot_lead_stalled, human_active, tool_errors) |
| `{uid}:conversation_quality` | JSON | 90d | Quality score {score: 0-100, signals: {...}, computed_at} |

### Follow-Up State Machine (Sprint 2)
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `{uid}:followup_state` | JSON list | 7d | Multi-step follow-up [{property_id, property_name, step, status, visit_time, ...}] |

### Web Search Cache
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `web_intel:{category}:{hash}` | string (JSON) | 24h | Cached web search results (area/brand/general) |

---

## Rentok API Catalog

Base URL: `https://apiv2.rentok.com` (configurable via `RENTOK_API_BASE_URL`)

### Search & Discovery
| Method | Endpoint | Key Params | File | Purpose |
|--------|----------|------------|------|---------|
| POST | `/property/getLatLongProperty` | `{"address": str}` | search.py, landmarks.py (via utils/geo.py) | Geocode location to lat/lng |
| POST | `/property/getPropertyDetailsAroundLatLong` | `coords, radius, rent_ends_to, pg_ids, unit_types_available?, pg_available_for?, sharing_type_enabled?` | search.py:_call_search_api | Search properties by geo + filters |
| POST | `/property/property-details-bots` | `{"property_id": str}` | property_details.py | Full property details (amenities, rules, FAQs) |
| POST | `/bookingBot/fetchPropertyImages` | `{"pg_id": str, "pg_number": str}` | images.py, search.py | Fetch property images |
| POST | `/bookingBot/fetch-all-properties` | `{"pg_ids": list}` | query_properties.py | All properties for a brand |
| GET | `/bookingBot/getAvailableRoomFromEazyPGID` | `?eazypg_id=str` | room_details.py | Available rooms at property |

### Booking & Visits
| Method | Endpoint | Key Params | File | Purpose |
|--------|----------|------------|------|---------|
| POST | `/bookingBot/reserveProperty` | `user_id, property_id, check_only?` | reserve.py | Check/reserve bed |
| POST | `/bookingBot/add-booking` | `user_id, property_id, visit_date, visit_time, visit_type, property_name` | schedule_visit.py, schedule_call.py | Schedule visit or call |
| POST | `/bookingBot/cancel-booking` | `user_id, property_id` | cancel.py | Cancel booking |
| POST | `/bookingBot/update-booking` | `user_id, property_id, visit_date?, visit_time?, visit_type?` | reschedule.py | Reschedule booking |
| GET | `/bookingBot/booking/{user_id}/events` | URL param | events.py | Get user's scheduled events |
| POST | `/bookingBot/shortlist-booking-bot-property` | `user_id, property_id, property_contact` | shortlist.py | Shortlist property |

### Leads & Tenants
| Method | Endpoint | Key Params | File | Purpose |
|--------|----------|------------|------|---------|
| POST | `/tenant/addLeadFromEazyPGID` | `eazypg_id, phone, name, gender, rent_range, lead_source, visit_date, visit_time, visit_type, lead_status, firebase_id` | schedule_visit.py, payment.py | Create CRM lead (NOT a tenant) |
| GET | `/tenant/get-tenant_uuid` | `?phone=str&eazypg_id=str` | payment.py | Get tenant UUID for payment |
| GET | `/tenant/{tenant_uuid}/lead-payment-link` | `?pg_id=str&pg_number=str&amount=int` | payment.py | Generate payment link |
| POST | `/bookingBot/addPayment` | `user_id, pg_id, pg_number, amount, short_link` | payment.py | Record completed payment |

### KYC (conditional — KYC_ENABLED feature flag)
| Method | Endpoint | Key Params | File | Purpose |
|--------|----------|------------|------|---------|
| GET | `/bookingBotKyc/user-kyc/{user_id}` | URL param | kyc.py | Init KYC entry |
| GET | `/bookingBotKyc/booking/{user_id}/kyc-status` | URL param | kyc.py | Check KYC completion |
| POST | `/checkIn/generateAadharOTP` | `aadhar_number, user_phone_number` | kyc.py | Generate Aadhaar OTP |
| POST | `/checkIn/verifyAadharOTP` | `otp, user_phone_number` | kyc.py | Verify OTP, get user data |
| POST | `/bookingBotKyc/update-kyc` | `user_id, kyc_data` | kyc.py | Update KYC status |

### Brand Info
| Method | Endpoint | Key Params | File | Purpose |
|--------|----------|------------|------|---------|
| GET | `/bookingBot/property-info` | `?pg_ids=str` (comma-separated) | brand_info.py | Brand details (rent range, amenities, token amounts) |

### External APIs (non-Rentok)
| Method | Endpoint | File | Purpose |
|--------|----------|------|---------|
| GET | `https://overpass-api.de/api/interpreter` | nearby_places.py | OSM nearby amenities |
| GET | `http://maps.rentok.com/table/v1/driving/...` | landmarks.py | Driving distance/time (OSRM) |
| POST | `graph.facebook.com/v19.0/{id}/messages` | whatsapp.py | Send WA message (Meta) |
| POST | `amped-express.interakt.ai/api/v17.0/{id}/messages` | whatsapp.py | Send WA message (Interakt) |
| POST | `api.tavily.com/search` | web_search.py | Web intelligence (optional, via TAVILY_API_KEY) |

---

## Agent-Tool Mapping

4 active agents + 1 supervisor. Tool availability for booking agent varies based on feature flags (KYC_ENABLED, PAYMENT_REQUIRED).

| Agent | Model | Tools |
|-------|-------|-------|
| **supervisor** | Haiku | None (classification only → `{"agent": str, "skills": list[str]}`) |
| **booking** | Sonnet | save_phone, reserve_bed, check_reserve_bed, save_visit_time, save_call_time, cancel_booking, reschedule_booking + conditionally: create_payment_link, verify_payment (PAYMENT_REQUIRED), initiate_kyc, verify_kyc, fetch_kyc_status (KYC_ENABLED) |
| **broker** | Haiku | search_properties, fetch_property_details, fetch_room_details, fetch_property_images, fetch_landmarks, estimate_commute, fetch_nearby_places, shortlist_property, save_preferences, fetch_properties_by_query, compare_properties, web_search |
| **profile** | Sonnet | fetch_profile_details, get_scheduled_events, get_shortlisted_properties |
| **default** | Sonnet | brand_info, web_search |

### Dynamic Skill System (broker agent only)

When `DYNAMIC_SKILLS_ENABLED=true` (default), the supervisor returns 1-3 skill names alongside the agent. The broker agent loads only the relevant skill prompt files and filters tools to match. This reduces prompt size and cost.

```
Supervisor classifies: {"agent": "broker", "skills": ["search", "qualify_new"]}
  → skills/loader.py: load _base.md (always) + search.md + qualify_new.md
  → skills/skill_map.py: get_tools_for_skills → filtered tool set
  → Prompt: [cached _base.md] + [uncached skill .md files]
  → If tool call misses skill set → ToolExecutor graceful fallback to full broker tools
```

Available skills: `qualify_new`, `qualify_returning`, `search`, `details`, `compare`, `commute`, `shortlist`, `show_more`, `selling`, `web_search`, `learning`

Fallback: `DYNAMIC_SKILLS_ENABLED=false` → monolithic broker prompt (all skills + all tools).

---

## Conversation Lifecycle

1. **Load**: `get_conversation(user_id)` from Redis (JSON list of messages)
2. **Append**: User message added to history
3. **Follow-up Check**: `has_active_followup(uid)` — if true, `handle_followup_reply()` routes to follow-up state machine before normal routing
4. **Human Mode Check**: `get_human_mode(uid, brand_hash)` — if active, skip AI pipeline
5. **Route**: Supervisor classifies intent → agent name + skills (keyword safety net → LLM → last_agent fallback)
6. **Execute**: Agent runs with conversation history + tools (max 15 iterations)
   - Phase C: `is_cancel_requested(uid)` checked between tool iterations — returns early if set
7. **Summarize**: If message count > 30, `maybe_summarize()` compresses older messages into a summary, keeping 10 most recent verbatim. Brand context injected when `brand_hash` available.
8. **Save**: `save_conversation(user_id, messages, brand_hash)` to Redis (TTL: 24h). Tags user with brand, adds to brand active users.
9. **Post-Save (fire-and-forget)**: Compute attention flags (`update_attention_flags`) + quality score (`update_conversation_quality`)
10. **Analytics**: Track agent usage, skill usage, funnel events, API costs — all dual-written (global + brand-scoped)
11. **Respond**: WhatsApp: parse markdown → send parts. Web: stream SSE events with Generative UI parts.

### Conversation Format
```python
[
  {"role": "user", "content": "search PGs in Andheri"},
  {"role": "assistant", "content": "...", "tool_use": [...]},
  {"role": "tool", "content": "...", "tool_use_id": "..."},
  {"role": "assistant", "content": "Here are 5 properties..."}
]
```

---

## Multi-Brand Isolation

Each brand gets a unique API key. The SHA-256 hash of the key (`brand_hash = sha256(key)[:16]`) is used as a namespace prefix for all brand-scoped data. The raw API key is NEVER stored.

```
Brand "OxOtel" → API key "OxOtel1234" → brand_hash = sha256("OxOtel1234")[:16] = "a1b2c3d4e5f6g7h8"
```

### Isolation boundaries
- **Admin endpoints**: `require_admin_brand_key` validates API key, returns `brand_hash` — all queries scoped automatically
- **User tagging**: `set_user_brand(uid, brand_hash)` on first message — persistent, never changes
- **Analytics**: Dual-write to global + `{brand_hash}:` scoped keys
- **Human mode**: `{uid}:{brand_hash}:human_mode` (with global `{uid}:human_mode` as fallback)
- **Feature flags**: `brand_flags:{brand_hash}` merged over global defaults via `get_effective_flags()`
- **PostgreSQL**: `brand_hash` column on `booking_messages` + `leads` tables

### Brand config auto-seed
On startup, `main.py` lifespan seeds configs for known brands (`_SEED_BRANDS` dict). Each config includes: `pg_ids`, `brand_name`, `cities`, `areas`, `wa_phone_number_id`, `wa_token`, `brand_hash`, `brand_link_token`.

---

## Feature Flags

Three global flags, overridable per-brand via admin panel:

| Flag | Default | Effect |
|------|---------|--------|
| `KYC_ENABLED` | `false` | Enables Aadhaar KYC tools (initiate_kyc, verify_kyc, fetch_kyc_status) and KYC flow in booking prompt |
| `PAYMENT_REQUIRED` | `false` | Enables payment tools (create_payment_link, verify_payment) and payment-before-reservation flow. When false, reservation skips payment. |
| `DYNAMIC_SKILLS_ENABLED` | `true` | Enables dynamic skill loading for broker agent. When false, uses monolithic prompt. |

**Runtime limitation**: Tool sets are built at import time (`tools/registry.py:init_registry()`). Toggling KYC_ENABLED or PAYMENT_REQUIRED at runtime changes prompts immediately but tool availability only changes on server restart.

**Flag resolution**: `get_effective_flags(brand_hash)` merges global defaults from `config.py` with per-brand overrides from `brand_flags:{brand_hash}` Redis key.

---

## Property ID Types

These are NOT interchangeable — using the wrong one causes silent API failures:

| ID | Format | Example | Source | Used For |
|----|--------|---------|--------|----------|
| `property_id` | `{pg_id}_{pg_number}` | `abc123_1` | Search results, stored in property_info_map | Most booking APIs |
| `pg_id` | Firebase UID | `abc123` | Part of property_id, split on `_` | Payment, images, shortlist |
| `pg_number` | Integer string | `1` | Part of property_id, split on `_` | Payment, images |
| `eazypg_id` | Alphanumeric with suffix | `4000033333B` | Search results `p_eazypg_id` field | Lead creation, tenant lookup, room details |

---

## Frontend Architecture

### SSE Event Protocol (stream.js)
```
event: agent_start    → data: {"agent": "broker"}                → Show agent badge
event: tool_start     → data: {"tool": "search_properties"}      → Show tool indicator
event: content_delta  → data: {"delta": "Here are..."}           → Append to message
event: done           → data: {"parts": [{type, ...}, ...]}      → Finalize, render Generative UI parts
```

### Generative UI Parts (server-parts.js)
Backend `core/ui_parts.py:generate_ui_parts()` produces structured parts in the `done` event. Frontend `server-parts.js` has a component registry:

| Part Type | Description |
|-----------|-------------|
| `text` | Markdown text block |
| `property_carousel` | Swipeable property cards with score badges |
| `comparison_table` | Side-by-side property comparison |
| `quick_replies` | Context-aware suggestion chips |
| `action_buttons` | CTA buttons (schedule visit, reserve, etc.) |
| `status_card` | Success/info/warning status message |
| `image_gallery` | Grid of property images with lightbox |
| `confirmation_card` | Booking/visit confirmation details |
| `error_card` | Error display with retry action |
| `expandable_sections` | Collapsible detail sections (FAQ, rules, amenities) |

### Rich Content Rendering Pipeline
```
Raw markdown from backend
  → rich-message.js: detect property listings (H3 headers with bold fields)
  → If listing detected: build property carousel (property-card.js)
  → If comparison detected: build comparison table (compare-card.js)
  → If server-parts format: render structured parts (server-parts.js)
  → If map data present: render Leaflet map (PropertyMap.js)
  → Otherwise: render as markdown (marked.js + DOMPurify)
```

### State Management
- `config.js`: Global mutable state (userId, chatHistory, isWaiting, carouselSeq)
- `chat-history.js`: localStorage persistence for message replay on page load
- `i18n.js`: Locale state with translations for en/hi/mr
- `stream.js`: AbortController + requestCounter for interrupt-on-send (Phase A)

---

## Keyword Safety Net (core/router.py:apply_keyword_safety_net)

3-phase routing before the supervisor LLM classifies intent:

**Phase 1 — Phrase match** (exact multi-word phrases):
| Phrases | Agent | Reason |
|---------|-------|--------|
| token amount, payment link, razorpay | booking | Payment never routes to broker |
| schedule visit, cancel booking, reschedule | booking | Booking actions |

**Phase 2 — Word match** (single keywords):
| Keywords | Agent | Reason |
|----------|-------|--------|
| payment, pay, reserve, kyc, aadhaar | booking | Booking/payment domain |
| search, find, looking, compare, commute | broker | Property discovery |
| profile, bookings, events, shortlisted | profile | User-specific data |

**Phase 3 — Last-agent stickiness** (10min TTL):
If no keyword match and no supervisor override, route to `last_agent` for multi-turn continuity.

The safety net runs first; supervisor LLM runs only if no keyword match.

---

## Backend Endpoint Catalog

### Public (no auth)
| Method | Path | Router | Purpose |
|--------|------|--------|---------|
| GET | `/health` | public.py | Health check |
| GET | `/brand-config?token={uuid}` | public.py | Public brand info (pg_ids, brand_name, cities, areas, brand_hash) |

### Chat (no auth — user_id in payload)
| Method | Path | Router | Purpose |
|--------|------|--------|---------|
| POST | `/chat` | chat.py | Synchronous chat (returns full response) |
| POST | `/chat/stream` | chat.py | SSE streaming chat |
| POST | `/feedback` | chat.py | Submit feedback (thumbs up/down) |
| GET | `/feedback/stats` | chat.py | Feedback statistics |
| GET | `/funnel` | chat.py | Funnel stage counts |
| POST | `/language` | chat.py | Set user language preference |

### Webhooks
| Method | Path | Router | Purpose |
|--------|------|--------|---------|
| GET | `/webhook/whatsapp` | webhooks.py | Meta webhook verification (challenge response) |
| POST | `/webhook/whatsapp` | webhooks.py | WhatsApp message ingestion (Phase B queue) |
| POST | `/webhook/payment` | webhooks.py | Razorpay payment confirmation webhook |
| POST | `/cron/follow-ups` | webhooks.py | Scheduled follow-up message trigger |

### Admin (all require `X-API-Key` header → `require_admin_brand_key` → brand-scoped)
| Method | Path | Router | Purpose |
|--------|------|--------|---------|
| GET | `/rate-limit/status` | admin.py | Rate limit status for a user |
| GET | `/admin/conversations` | admin.py | Paginated user list (brand-scoped) |
| GET | `/admin/conversations/{uid}` | admin.py | Full thread + memory + cost + human_mode |
| POST | `/admin/conversations/{uid}/takeover` | admin.py | Activate human mode (brand-scoped) |
| POST | `/admin/conversations/{uid}/resume` | admin.py | Deactivate human mode (brand-scoped) |
| POST | `/admin/conversations/{uid}/message` | admin.py | Send admin message via WhatsApp + auto-resume AI |
| GET | `/admin/command-center` | admin.py | Today's KPIs (messages, leads, visits, funnel, costs) |
| GET | `/admin/leads` | admin.py | Filterable lead list (brand-scoped) |
| GET | `/admin/analytics` | admin.py | Dashboard data (funnel, agents, skills, costs, feedback) |
| GET | `/admin/flags` | admin.py | Effective feature flags (global defaults + brand overrides) |
| POST | `/admin/flags` | admin.py | Toggle feature flags per-brand |
| POST | `/admin/broadcast` | admin.py | Send WhatsApp message to brand's active users (last 7 days) |
| GET | `/admin/properties` | admin.py | List brand's properties |
| POST | `/admin/properties/{prop_id}/documents` | admin.py | Upload document (ownership check) |
| GET | `/admin/properties/{prop_id}/documents` | admin.py | List documents (ownership check) |
| DELETE | `/admin/properties/{prop_id}/documents/{doc_id}` | admin.py | Delete document (ownership check) |
| GET | `/admin/brand-config` | admin.py | Get brand config (token masked) |
| POST | `/admin/brand-config` | admin.py | Create/update brand config |
| POST | `/admin/leads/{uid}/outcome` | admin.py | Mark lead outcome (converted/lost/no_show/in_progress) with side effects |
| GET | `/admin/errors` | admin.py | Paginated structured error events (type/days filters + summary) |
| POST | `/admin/backfill-brands` | admin.py | One-time migration: tag existing users with brand_hash |
