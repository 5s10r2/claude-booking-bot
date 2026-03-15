# EazyPG Booking Bot — Deep Architecture Reference

Read this file only when you need detailed information about Redis keys, Rentok APIs, agent-tool mapping, or conversation lifecycle. For quick orientation, use CLAUDE.md instead.

---

## Request Lifecycle

### WhatsApp Flow
```
User sends message on WhatsApp
  → Meta/Interakt webhook → POST /whatsapp (main.py:552)
  → Extract user_id (phone: 919876543210), message text, account_values
  → Store account_values in Redis (whitelabel config: pg_ids, brand_name, tokens)
  → run_pipeline(user_id, message) (main.py:155)
    → rate_limiter.check_rate_limit (sliding window: 6/min, 30/hr, 100/min global)
    → load conversation history from Redis
    → _route_agent: keyword safety net → supervisor LLM → fallback to last_agent
    → agent.run() with tools (Anthropic tool_use loop, max 15 iterations)
    → save conversation to Redis
    → message_parser.parse_message_parts (markdown → WhatsApp-compatible parts)
    → whatsapp.send_text / send_carousel / send_image
```

### Web Chat Flow
```
User types in eazypg-chat widget
  → src/stream.js:sendMessage → POST /api/stream (Vercel serverless proxy)
  → Proxy forwards to https://claude-booking-bot.onrender.com/chat/stream
  → main.py:chat_stream@464 (SSE endpoint)
    → Same pipeline as WhatsApp but streams events:
      - agent_start: {agent_name}
      - tool_start: {tool_name}
      - content_delta: {text chunk}
      - done: {}
  → Frontend parses SSE, renders markdown in real-time
  → Rich content: property carousels, comparison tables, maps
```

### Key Differences by Channel
| Aspect | WhatsApp | Web Chat |
|--------|----------|----------|
| user_id format | Pure digits: `919876543210` | Alphanumeric: `uat_k7x2m9qf` |
| Phone number | Extracted from user_id[-10:] | Must be collected via save_phone tool |
| Response format | Parsed into text/carousel/image parts | Raw markdown streamed via SSE |
| Account values | Sent in webhook payload | Not available (no whitelabel) |
| Images | Uploaded to WhatsApp media API | Displayed as `<img>` tags |

---

## Redis Key Schema

All keys use `{user_id}` prefix unless noted. Redis instance is Render-managed.

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

### Analytics & Feedback
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `feedback:log` | list | none | Append-only feedback entries |
| `feedback:counts` | hash | none | Aggregated counts: `{agent}:up`, `{agent}:down`, `total:up`, `total:down` |
| `agent_usage:{YYYY-MM-DD}` | hash | 90 days | Per-agent usage counts by day |
| `funnel:{YYYY-MM-DD}` | hash | 90 days | Funnel stage counts: search, detail, shortlist, visit, booking |

### WhatsApp Message Tracking
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `wama:{wama_id}` | string | 3 days | Map WA message ID → user message for response tracking |

### Knowledge Base (FAISS)
| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `faiss:{file_hash}:index` | binary | none | FAISS vector index |
| `faiss:{file_hash}:pkl` | binary | none | FAISS pickle data |

---

## Rentok API Catalog

Base URL: `https://apiv2.rentok.com` (configurable via `RENTOK_API_BASE_URL`)

### Search & Discovery
| Method | Endpoint | Key Params | File | Purpose |
|--------|----------|------------|------|---------|
| POST | `/property/getLatLongProperty` | `{"address": str}` | search.py, landmarks.py | Geocode location to lat/lng |
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

### KYC
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
| GET | `http://maps.rentok.com/table/v1/driving/...` | landmarks.py | Driving distance/time |
| POST | `graph.facebook.com/v19.0/{id}/messages` | whatsapp.py | Send WA message (Meta) |
| POST | `amped-express.interakt.ai/api/v17.0/{id}/messages` | whatsapp.py | Send WA message (Interakt) |

---

## Agent-Tool Mapping

| Agent | Model | Tools |
|-------|-------|-------|
| **supervisor** | Haiku | None (classification only) |
| **booking** | Sonnet | save_phone, reserve_bed, check_reserve_bed, create_payment_link, verify_payment, save_visit_time, save_call_time, cancel_booking, reschedule_booking, initiate_kyc, verify_kyc, fetch_kyc_status |
| **broker** | Haiku | search_properties, fetch_property_details, fetch_room_details, fetch_property_images, fetch_landmarks, fetch_nearby_places, shortlist_property, save_preferences, fetch_properties_by_query |
| **profile** | Sonnet | fetch_profile_details, get_scheduled_events, get_shortlisted_properties |
| **default** | Sonnet | brand_info, query_knowledge_base |
| **room** | Sonnet | fetch_room_details |

---

## Conversation Lifecycle

1. **Load**: `get_conversation(user_id)` from Redis (JSON list of messages)
2. **Append**: User message added to history
3. **Route**: Supervisor classifies intent → agent name (keyword safety net → LLM → last_agent fallback)
4. **Execute**: Agent runs with conversation history + tools (max 15 iterations)
5. **Summarize**: If message count > 30, `maybe_summarize()` compresses older messages into a summary, keeping 10 most recent verbatim
6. **Save**: `save_conversation(user_id, messages)` to Redis (TTL: 24h)
7. **Respond**: WhatsApp: parse markdown → send parts. Web: stream SSE events.

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
event: agent_start    → data: {"agent": "broker"}     → Show agent badge
event: tool_start     → data: {"tool": "search_properties"} → Show tool indicator
event: content_delta  → data: {"delta": "Here are..."}  → Append to message
event: done           → data: {}                        → Finalize, show quick replies
```

### Rich Content Rendering Pipeline
```
Raw markdown from backend
  → rich-message.js: detect property listings (H3 headers with bold fields)
  → If listing detected: build property carousel (property-card.js)
  → If comparison detected: build comparison table (compare-card.js)
  → If server-parts format: render structured parts (server-parts.js)
  → If map data present: render Leaflet map (PropertyMap.js)
  → Otherwise: render as markdown (marked.js)
```

### State Management
- `config.js`: Global mutable state (userId, chatHistory, isWaiting, carouselSeq)
- `chat-history.js`: localStorage persistence for message replay on page load
- `i18n.js`: Locale state with translations for en/hi/mr

---

## Keyword Safety Net (main.py:_route_agent)

Before the supervisor LLM classifies intent, a keyword-based override catches common patterns:

| Keywords | Agent | Reason |
|----------|-------|--------|
| payment, pay, token amount, razorpay | booking | Payment never routes to broker |
| visit, schedule, cancel, reschedule | booking | Booking actions |
| search, find, looking for, PG near | broker | Property discovery |
| profile, my bookings, my events | profile | User-specific data |

The safety net runs first; supervisor LLM runs only if no keyword match. Last-agent stickiness (10min TTL) handles follow-up messages in the same flow.
