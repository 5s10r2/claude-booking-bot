# DIRECTORY.md — EazyPG AI Booking Bot: Canonical Operating Document

> **What this file is**: The single source of truth for engineers, PMs, designers, and AI agents working in this codebase. Not a README. Not marketing copy. A living, opinionated operating guide that tells you exactly what exists, how it works, what's risky, and how to change things safely.
>
> **How to use it**: Skim the Executive Summary (§1) for orientation. Jump directly to the section you need. Cross-reference CLAUDE.md for the complete file map and task recipes.
>
> **Last updated**: 2026-03-15 | **Maintained by**: whoever makes a structural change

---

## §0 — Document Map

| § | Section | When to read it |
|---|---|---|
| §1 | Executive Summary | Always first |
| §2 | Product Context | Before any feature work |
| §3 | Technology Stack | Before evaluating a new dependency |
| §4 | Repository Shape | When navigating the codebase |
| §5 | Architecture Overview | Before touching pipelines or SSE |
| §6 | Feature Domain Map | Before adding/modifying AI behavior |
| §7 | Key Workflows | Before changing any user-facing flow |
| §8 | Data & Integration Map | Before any Redis/DB/API change |
| §9 | Code Conventions | Before writing any code |
| §10 | Legacy & Technical Debt | Before touching any "obvious improvement" |
| §11 | High-Risk Files | Before editing any backend file |
| §12 | Safe Change Strategy | Before any PR |
| §13 | AI-Agent Guidance | Claude Code / LLM context |
| §14 | Practical Commands | Local dev, debugging, seeding |
| §15 | Deployment & Environment | Before deploying or adding env vars |
| §16 | Known Unknowns | Before making assumptions |
| §17 | Glossary | When a term is ambiguous |
| §18 | Document Maintenance | After structural changes |

---

## §1 — Executive Summary

EazyPG AI Booking Bot is a **multi-tenant, multi-channel conversational AI assistant** that helps tenants in Indian cities find, compare, and book PG (Paying Guest) accommodations. The product is white-labelled: brand operators (e.g. OxOtel) configure their property IDs and brand identity once via an admin panel, and get a shareable chatbot link that is scoped to their properties.

The system has three deployments that work together: a **FastAPI Python backend** (Render) that runs all AI logic, a **Vanilla JS chat widget** (Vercel) that serves end-users, and a **React 19 TypeScript admin portal** (Vercel) that operators use to manage conversations, leads, and brand config.

AI is powered by **Claude** (Anthropic): a Supervisor agent classifies intent and routes to one of four specialist agents — Broker (property search), Booking (visits + payments), Profile (user preferences), and Default (general help). The Broker agent uses Claude Haiku for cost efficiency; all others use Claude Sonnet.

**Redis is the primary state store** for everything: conversation history, user preferences, property cache, brand config, rate limits, and analytics. PostgreSQL is used only for message logging. There is no real-time database; all state is explicit and TTL-managed.

The chat widget is intentionally **zero-framework** (no React, no Vue, no Angular) — just Vite 6, DOMPurify, Leaflet, and Marked. The admin portal is **React 19 + TypeScript + TanStack Query + shadcn/ui + Tailwind v4**, built for operators not end-users.

---

## §2 — Product Context

### What It Does

- **Property discovery**: Natural-language search for PG accommodations by location, budget, amenities, gender preference, move-in date. Results are geocoded, scored, and cached.
- **Property detail**: Room-level details, images, amenities, nearby landmarks, commute estimates.
- **Visit scheduling**: Book physical or phone visits; creates CRM leads in Rentok.
- **Payments**: Generate payment links via Rentok; verify payment on webhook callback.
- **Shortlisting**: Users can save properties; cross-session preference learning.
- **WhatsApp + Web**: Both channels share the same pipeline. WhatsApp sends carousels, images, text. Web streams SSE with rich UI components (carousels, maps, comparison tables, celebration animations).
- **Admin oversight**: Operators see conversation threads, lead pipeline, analytics, and can take over conversations manually (Human Mode).
- **Multi-tenant**: Each brand gets its own API key, property scope, and chatbot URL. Isolation is enforced at the Redis key prefix level.

### What It Does NOT Do

- Real-time property availability (Rentok API is queried on demand, not subscribed to)
- Tenant management or lease generation
- Property content management (operators do not add/edit property details here)
- Payment processing (Rentok generates payment links; this system records the callback)
- Aadhaar KYC in production (KYC_ENABLED=false; the code exists but is disabled)

### Who Uses It

| Persona | Channel | What they do |
|---|---|---|
| Tenant / End-user | WhatsApp or eazypg-chat widget | Searches, compares, books PGs |
| Brand operator | eazypg-admin portal | Monitors conversations, manages leads, configures brand |
| Developer / AI agent | CLAUDE.md + this file | Understands system before making changes |

---

## §3 — Technology Stack

### Backend (`claude-booking-bot/`)

| Component | Technology | Version / Notes |
|---|---|---|
| Language | Python | 3.11+ required |
| Framework | FastAPI + Uvicorn | async, SSE streaming |
| AI SDK | anthropic | Latest; `claude-haiku-4-5-20251001` (broker/supervisor) + `claude-sonnet-4-6` (others) |
| Cache / State | Redis | aioredis; Render-managed; primary data store |
| Database | PostgreSQL | asyncpg; Render-managed; message logs only |
| HTTP client | httpx | Async, used in all Rentok + external API calls |
| Image handling | Pillow | WhatsApp WEBP → JPEG conversion |
| Config parsing | PyYAML | Skill .md frontmatter |
| Document parsing | pypdf + openpyxl | Property document ingestion |
| Retry logic | Custom `@with_retry` | 2 retries, exponential backoff (`utils/retry.py`) |
| **Removed** | faiss-cpu, langchain, sentence-transformers, streamlit | Deleted March 2026 — dead code |

### Chat Frontend (`eazypg-chat/`)

| Component | Technology | Notes |
|---|---|---|
| Build tool | Vite 6 | Multi-entry: index.html + dashboard.html |
| Language | Vanilla JavaScript | Zero framework — imperative DOM manipulation |
| Runtime deps (only 3) | DOMPurify, Leaflet, Marked | XSS sanitization, maps, markdown rendering |
| Voice input | Deepgram Nova-3 | en/hi/mr via Vercel Edge token proxy |
| Hosting | Vercel | Auto-deploy; Edge Functions for API proxies |

### Admin Portal (`eazypg-admin/`)

| Component | Technology | Notes |
|---|---|---|
| Framework | React 19 | concurrent features enabled |
| Language | TypeScript | Strict mode |
| Routing | React Router v7 | SPA with 6 routes |
| Server state | TanStack Query v5 | Polling, optimistic updates, select-transform |
| UI components | shadcn/ui | radix-ui primitives + Tailwind v4 |
| Styling | Tailwind CSS v4 | CSS-first config (no tailwind.config.js) |
| Icons | lucide-react | |
| Charts | Chart.js | Analytics page |
| Build | Vite 5 | Port 5174 in dev |
| Hosting | Vercel | Separate project from eazypg-chat |

### AI Models

| Agent | Model | Reason |
|---|---|---|
| Supervisor | claude-haiku-4-5-20251001 | High-volume classification; cost-sensitive |
| Broker | claude-haiku-4-5-20251001 | Highest request volume; cost-sensitive |
| Booking | claude-sonnet-4-6 | Complex multi-step reasoning |
| Profile | claude-sonnet-4-6 | Preference understanding |
| Default | claude-sonnet-4-6 | Brand voice quality |

---

## §4 — Repository Shape

```
CC Booking Bot FInal/              # polyrepo root — NOT a monorepo
│                                  # no shared package.json, no shared tooling
│                                  # three independent deployment units
│
├── claude-booking-bot/            # Python/FastAPI backend (git repo)
│   ├── main.py                    # FastAPI app factory + lifespan (129 lines — endpoints split into routers/)
│   ├── config.py                  # Pydantic settings, feature flags (KYC_ENABLED, PAYMENT_REQUIRED, DYNAMIC_SKILLS_ENABLED), model IDs
│   ├── requirements.txt           # 16 packages (lean after dead-code removal)
│   ├── build.sh                   # Render build script (pip install)
│   ├── .claude/launch.json        # Claude Code dev server config (uvicorn port 8000)
│   ├── CLAUDE.md                  # ✅ PRIMARY — complete file map, line numbers, task recipes
│   ├── PRD-VOICE-AGENT.md         # AI Voice Agent PRD v3.0 (2,609 lines — sales intelligence, skill reuse)
│   ├── QA_REPORT.md               # QA test results and regression reports
│   ├── RENTOK_API.md              # Rentok API documentation
│   ├── agents/                    # 5 agent configs (supervisor, broker, booking, profile, default)
│   ├── routers/                   # FastAPI routers: public.py, chat.py, webhooks.py, admin.py
│   ├── core/                      # Engine: claude.py, prompts.py, pipeline.py, summarizer.py, router.py, tool_executor.py, ui_parts.py, auth.py, state.py
│   ├── tools/                     # 28 tool implementations across broker/, booking/, profile/, default/, common/
│   ├── skills/                    # Dynamic skill system: loader.py, skill_map.py, broker/*.md (12 files)
│   ├── db/
│   │   ├── redis/                 # Redis domain package (8 modules, ~1,279 lines — split from former god-file)
│   │   │   ├── _base.py           # Connection pool, helpers
│   │   │   ├── conversation.py    # History, compaction, wamid dedup, WA queue, pipeline cancel
│   │   │   ├── user.py            # Memory, preferences, shortlist, followups, lead score
│   │   │   ├── property.py        # Property cache, images, templates
│   │   │   ├── payment.py         # Payment link + active request dedup
│   │   │   ├── analytics.py       # Funnel, feedback, agent/skill usage, costs (dual-write: global + brand)
│   │   │   ├── brand.py           # Brand config, WA reverse-lookup, per-brand flags
│   │   │   └── admin.py           # Active users, human mode (brand-scoped), session cost
│   │   ├── redis_store.py         # ⚠️ SHIM only — re-exports from db/redis/ (backward compat)
│   │   └── postgres.py            # Message logging + leads + property docs (brand_hash column)
│   ├── channels/                  # whatsapp.py (Meta + Interakt dual support)
│   ├── utils/                     # date.py, geo.py, image.py, scoring.py, retry.py, properties.py, api.py, property_docs.py
│   ├── data/                      # transit_lines.json (Mumbai/Bangalore/Delhi/Pune metro)
│   ├── docs/                      # Documentation directory
│   │   ├── ARCHITECTURE.md        # Deep reference — Redis keys, Rentok API catalog, agent-tool mapping
│   │   ├── CHANGES_FROM_MAIN.md   # Change log from main branch
│   │   ├── DIRECTORY.md           # This file
│   │   └── screenshots/           # 20 UI screenshots (carousel, cards, compare, welcome, etc.)
│   ├── stress_test_broker.py      # 20-scenario broker regression (local backend)
│   ├── stress_test_broker_prod.py # 20-scenario broker regression (production URL)
│   ├── test_comprehensive.py      # 16-tool comprehensive test suite
│   ├── test_dynamic_skills.py     # 8-scenario dynamic-skill E2E test
│   ├── test_fixed_tools.py        # Fixed tools regression test
│   └── test_full_integration.py   # Full integration test suite
│
├── eazypg-chat/                   # Vite 6 / Vanilla JS chat widget
│   ├── index.html                 # Chat interface (87 lines) + Stop button
│   ├── dashboard.html             # Analytics dashboard (562 lines)
│   ├── vite.config.js             # Multi-entry + dev proxy (/api/* → :8000)
│   ├── vercel.json                # Function timeouts: stream/chat=120s
│   ├── src/
│   │   ├── config.js              # Global state: userId, ACCOUNT_VALUES, FALLBACK_ACCOUNT_VALUES
│   │   ├── stream.js              # SSE handler + AbortController interrupt + stopStream()
│   │   ├── main.js                # Entry: fetchBrandConfig() + event listeners
│   │   ├── renderers/             # server-parts.js (10 component types), property-card.js, compare-card.js
│   │   └── components/            # PropertyMap.js (Leaflet)
│   ├── styles/                    # base.css, carousel.css, components.css, animations.css, gallery.css, status-card.css, input.css
│   └── api/                       # Vercel Edge proxies: stream.js, chat.js, feedback.js, brand-config.js, analytics.js, deepgram-token.js, language.js
│
├── eazypg-admin/                  # React 19 / TypeScript admin portal
│   ├── src/
│   │   ├── App.tsx                # React Router v7: 6 routes under AppShell
│   │   ├── lib/                   # types.ts (all interfaces), api.ts (apiFetch), auth.ts
│   │   ├── hooks/                 # 7 TanStack Query hooks (useConversations, useLeads, useBrandConfig, etc.)
│   │   ├── pages/                 # ConversationsPage, LeadsPage, AnalyticsPage, PropertiesPage, SettingsPage
│   │   └── components/            # AppShell, ThreadPanel, Sidebar (dynamic brand name)
│   └── api/                       # 16 Vercel Edge proxies → backend /admin/* endpoints
│
├── CLAUDE.md                      # Root-level project instructions (also in claude-booking-bot/)
├── ARCHITECTURE.md                # Root-level copy (canonical is docs/ARCHITECTURE.md)
├── README.md                      # ⚠️ STALE — references dead "Room" agent + KB endpoints
├── CHANGES_FROM_MAIN.md           # Root-level copy
└── PRD-VOICE-AGENT.md             # Root-level copy of voice agent PRD
```

**Key structural facts:**
- No Docker. Render uses native Python runtime (build.sh = pip install -r requirements.txt).
- No shared CI/CD. Each sub-project deploys independently to Vercel/Render on push to main.
- No shared environment config. Each sub-project has its own env vars on its host.
- `eazypg-admin` is a **separate Vercel project** from `eazypg-chat` — different project IDs, different deployment URLs.

---

## §5 — Architecture Overview

### Request Lifecycle — Web Chat

```
User types → eazypg-chat/src/stream.js (sendMessage + AbortController)
  → POST /api/stream (Vercel Edge proxy, 120s timeout)
  → POST https://claude-booking-bot.onrender.com/chat/stream
  → routers/chat.py:chat_stream (SSE endpoint)
    → core/pipeline.py:run_pipeline()
      → [Human Mode check] → if active: emit done{agent="human"}, return
      → rate_limiter.check_rate_limit (6/min, 30/hr, 100/min global)
      → load conversation history from Redis
      → _route_agent: keyword safety net → supervisor LLM → last_agent fallback
      → agent.run() with tool loop (max 15 rounds, parallel execution via asyncio.gather)
      → maybe_summarize() if >30 messages (brand context injected)
      → save conversation to Redis (24h TTL) + tag user brand
    → SSE stream: agent_start → tool_start → tool_done → content_delta×N → done{parts[]}
  → Frontend parses SSE, renders component registry (server-parts.js)
  → User can interrupt: AbortController cancels stream, Stop button visible during streaming
```

### Request Lifecycle — WhatsApp (Phase B+C: Multi-Turn Queue)

```
User sends message on WhatsApp
  → Meta/Interakt webhook → POST /webhook/whatsapp (routers/webhooks.py)
  → wamid dedup: is_wamid_seen(wamid) → skip if duplicate (24h TTL)
  → Extract phone_number_id → hydrate brand config from Redis (brand_wa:{phone_id})
  → Tag user: set_user_brand(uid, brand_hash)
  → wa_queue_push(uid, message) → Redis list {uid}:wa_queue
  → Return 200 immediately (no blocking)
  → _drain_and_process() async task:
    → wa_processing_acquire(uid) → SET NX lock (2 min TTL)
    → sleep(WA_DEBOUNCE_SECONDS=2.0) — wait for burst messages
    → wa_queue_drain(uid) → LPOP all pending messages
    → run_pipeline(combined_messages) → same pipeline as web
    → If new messages arrived during pipeline: set_cancel_requested(uid) → loop
    → message_parser.parse_message_parts: markdown → WhatsApp-compatible parts
    → whatsapp.py: send_text / send_carousel / send_image (Meta or Interakt per is_meta flag)
    → wa_processing_release(uid)
```

### SSE Event Protocol

```
event: agent_start    data: {"agent": "broker"}              → show agent badge in UI
event: tool_start     data: {"tool": "search_properties"}    → show tool indicator
event: tool_done      data: {"tool": "search_properties"}    → clear tool indicator
event: content_delta  data: {"delta": "Here are 3 PGs..."}  → append to streaming bubble
event: done           data: {"parts": [...], "agent": "broker", "quick_replies": [...]}
event: error          data: {"message": "..."}               → show error card
```

### Generative UI Pattern

The backend generates structured `parts[]` on every response. The frontend is a **component registry** that maps part types to renderers — the backend controls what UI appears:

```
Backend parts[] → server-parts.js PART_RENDERERS:
  "text"              → markdown bubble with price highlights
  "property_carousel" → horizontal scrolling cards with scores, images, amenity pills
  "comparison_table"  → side-by-side table with winner badge
  "quick_replies"     → contextual suggestion chips
  "action_buttons"    → primary/secondary CTA buttons
  "status_card"       → success/info/warning confirmation (+ celebration animation)
  "image_gallery"     → grid thumbnails with fullscreen lightbox
  "confirmation_card" → confirm/cancel dialog before irreversible actions
  "error_card"        → friendly error with retry button
```

### Multi-Tenant Isolation

```
API key (e.g. "oxotel-uat-2026")
  → sha256(key).hexdigest()[:16]  (redis_store.py:_brand_hash)
  → used as Redis prefix: brand_config:{hash16}
  → raw API key NEVER stored in Redis or logs
  → brand_token:{uuid} → hash (for public chatbot URL)
  → brand_wa:{phone_number_id} → full config (for WhatsApp webhook hydration)
```

### Human Mode (Admin Takeover — Brand-Scoped)

```
Admin clicks "Take Over" → POST /admin/conversations/{uid}/takeover
  → Redis: set {uid}:{brand_hash}:human_mode = {"active": "1", "taken_at": timestamp}
  → Brand-scoped: only the brand that took over blocks AI; other brands unaffected
  → Fallback: checks legacy {uid}:human_mode if brand-scoped key absent

Next user message (any channel):
  → pipeline.py: checks get_human_mode(uid, brand_hash) BEFORE routing → early return
  → AI never responds while human mode is active for that brand
```

### Dynamic Skill System (Broker Agent)

```
DYNAMIC_SKILLS_ENABLED=true (config.py):
  Supervisor LLM returns {"agent": "broker", "skills": ["search", "selling"]}
  broker_agent.py builds prompt: _base.md (cached) + search.md + selling.md (uncached)
  Tool filtering: ALWAYS_TOOLS + SKILL_TOOLS["search"] + SKILL_TOOLS["selling"] → ~5 tools
  Tool executor: if skill miss → fall back to full 12-tool set (logged to skill_misses:{day})

DYNAMIC_SKILLS_ENABLED=false:
  Legacy monolithic 340-line BROKER_AGENT_PROMPT from core/prompts.py
  All 12 broker tools available every turn
```

---

## §6 — Feature Domain Map

### Agent → Tool Mapping

| Agent | Model | Tools (count) | Skills |
|---|---|---|---|
| **Supervisor** | Haiku | 0 (classification only) | Detects 1-3 broker skills per turn |
| **Broker** | Haiku | 12 broker tools + web_search | search, details, compare, commute, shortlist, show_more, selling, web_search, learning, qualify_new, qualify_returning |
| **Booking** | Sonnet | save_phone, reserve_bed, check_reserve_bed, create_payment_link, verify_payment, save_visit_time, save_call_time, cancel_booking, reschedule_booking, initiate_kyc, verify_kyc, fetch_kyc_status (12) | — |
| **Profile** | Sonnet | fetch_profile_details, get_scheduled_events, get_shortlisted_properties (3) | — |
| **Default** | Sonnet | brand_info, query_knowledge_base (2) | — |

**Total registered tools: 28** — all schemas have `"strict": true`.

### Broker Tool Detail

| Tool | What it does | Key dependency |
|---|---|---|
| search_properties | Geocode → Rentok search → normalize → cache → images | Rentok getPropertyDetailsAroundLatLong |
| fetch_property_details | Full property info (amenities, rules, FAQs) | Rentok property-details-bots |
| fetch_room_details | Available rooms + sharing types | Rentok getAvailableRoomFromEazyPGID |
| fetch_property_images | Property photo URLs | Rentok fetchPropertyImages |
| fetch_landmarks | Driving distance to key landmarks | maps.rentok.com OSRM + Rentok geocode |
| fetch_nearby_places | Nearby amenities (food, transit, medical) | Overpass API (OSM) |
| shortlist_property | Save to user shortlist + update memory | Rentok shortlist-booking-bot-property |
| compare_properties | Side-by-side structured comparison | Cached property_info_map |
| save_preferences | Store location/budget/amenity prefs | Redis {uid}:preferences |
| estimate_commute | Drive/transit time estimation | OSRM + transit_lines.json |
| fetch_properties_by_query | All brand properties | Rentok fetch-all-properties |
| web_search | Area insights, market data | Tavily API (capped 3/conv) |

### Skill Files (`skills/broker/`)

| File | Always loaded? | Purpose |
|---|---|---|
| `_base.md` | ✅ YES — cached | Identity, format rules, never-rules, tools policy |
| `qualify_new.md` | When new user | Bundled qualifying questions for new users |
| `qualify_returning.md` | When returning | Warm greeting + preference confirmation |
| `search.md` | When searching | save_preferences → search → results workflow |
| `details.md` | When showing details | Property/room/images in parallel |
| `compare.md` | When comparing | Comparison + recommendation |
| `commute.md` | When commute asked | Driving + transit estimation |
| `shortlist.md` | When shortlisting | Shortlist workflow |
| `show_more.md` | When paginating | Show next batch / expand radius |
| `selling.md` | When objection handling | Sentiment detection, scarcity, value framing |
| `web_search.md` | When area questions | web_search + fetch_nearby_places pairing |
| `learning.md` | When feedback signals | Implicit feedback, deal-breaker updates |

---

## §7 — Key Workflows (Step-by-Step)

### Property Search

1. User: "Find me a PG near Andheri station under ₹8,000"
2. Supervisor detects broker agent + skills: ["search", "qualify_new"]
3. Broker: `save_preferences({location: "Andheri station", budget: 8000})`
4. Broker: `search_properties({query: "Andheri station", rent_ends_to: 8000})`
   - Geocodes address via Rentok `/property/getLatLongProperty`
   - Calls `/property/getPropertyDetailsAroundLatLong` with coords + filters
   - Normalizes: extracts pg_id, pg_number, eazypg_id, name, rent, amenities
   - Scores properties: `utils/scoring.py:match_score()` (weighted, fuzzy amenity matching)
   - Caches in `{uid}:property_info_map` (6-month TTL)
   - Fetches images: `Rentok/fetchPropertyImages`
5. Backend generates `parts[]`: property_carousel + quick_replies
6. Frontend renders: horizontal scrollable cards with score badges

### Visit Scheduling

1. User: "Schedule a visit to Purva Sugandha RABALE tomorrow at 10am"
2. Booking agent: `save_visit_time({property_name: "...", visit_date: "...", visit_time: "10:00"})`
   - Validates date via `utils/date.py:transcribe_date()`
   - Calls Rentok `/bookingBot/add-booking`
   - Creates CRM lead: Rentok `/tenant/addLeadFromEazyPGID`
3. Backend generates `parts[]`: status_card (success) + celebration animation trigger
4. Rentok sends WhatsApp/email confirmation to operator directly

### Payment Link Flow

1. User: "I want to pay the token amount"
2. Booking agent: `create_payment_link({property_name: "..."})`
   - Validates phone (must be collected first via `save_phone` for web users)
   - `GET /tenant/get-tenant_uuid?phone=...&eazypg_id=...`
   - `GET /tenant/{uuid}/lead-payment-link?pg_id=...&pg_number=...&amount=...`
   - Stores in Redis: `{uid}:payment_info` (pg_id, pg_number, amount, short_link)
3. Returns payment link to user; Rentok hosts the payment page
4. On payment: Rentok POSTs to `/webhook/payment`
   - Loads `payment_info` from Redis
   - Calls `POST /bookingBot/addPayment` to record in Rentok CRM

### Brand Configuration (Multi-Tenant Setup)

1. Admin opens Settings → Brand Configuration in eazypg-admin
2. Admin adds pg_ids → "Save PG IDs" → `POST /api/brand-config` (Vercel Edge proxy)
   - Proxy forwards to `POST /admin/brand-config` with X-API-Key header
   - Backend: SHA-256(api_key)[:16] → brand hash
   - Stores `brand_config:{hash}` + `brand_wa:{phone_id}` + `brand_token:{uuid}` atomically via Redis pipeline
   - Auto-generates `brand_link_token` (UUID v4) on first save
3. Admin sees: "Your Chatbot Link: `https://eazypg-chat.vercel.app?brand={uuid}`"
4. End-user visits link → `main.js:fetchBrandConfig()` reads `?brand=` param
   - 3s AbortController timeout; calls `GET /api/brand-config?brand={uuid}`
   - Gets back `{pg_ids, brand_name, cities, areas}` (no WhatsApp credentials)
   - Sets `ACCOUNT_VALUES` from response; stream.js uses `ACCOUNT_VALUES ?? FALLBACK_ACCOUNT_VALUES`

---

## §8 — Data & Integration Map

### Redis Key Schema (all keys, with TTLs)

> Full schema with implementation notes in ARCHITECTURE.md §Redis Key Schema

**Conversation & Routing**

| Key | TTL | Purpose |
|---|---|---|
| `{uid}:conversation` | 24h | Message history (JSON list) |
| `{uid}:language` | 24h | Detected locale: en/hi/mr |
| `{uid}:last_agent` | 10min | Agent stickiness for multi-turn |
| `{uid}:active_request` | 30s | Dedup lock — concurrent request prevention |

**User Profile**

| Key | TTL | Purpose |
|---|---|---|
| `{uid}:preferences` | None | Location, budget, amenities, move-in date |
| `{uid}:user_memory` | None | Cross-session intelligence (shortlists, feedback, deal-breakers) |
| `{uid}:account_values` | 1h (WA) | Brand config: pg_ids, WA creds (hydrated from brand_wa on webhook) |
| `{uid}:user_name` | None | Display name |
| `{uid}:user_phone` | None | 10-digit phone (web users only) |

**Property Cache**

| Key | TTL | Purpose |
|---|---|---|
| `{uid}:property_info_map` | 6 months | Normalized search results with scores |
| `{uid}:last_search` | 24h | Top-10 results from last search (for returning context) |
| `search_cache:{md5}` | 15min | Rentok search API response (keyed by payload hash) |

**Rate Limiting** (Redis Sorted Sets — sliding window)

| Key | TTL | Limit |
|---|---|---|
| `rl:{uid}:min` | 70s | 6 requests/minute per user |
| `rl:{uid}:hr` | 3610s | 30 requests/hour per user |
| `rl:__global__:min` | 70s | 100 requests/minute global |

**Brand Config** (Multi-Tenant)

| Key | TTL | Purpose |
|---|---|---|
| `brand_config:{sha256[:16]}` | None | Full brand config (pg_ids, identity, WhatsApp creds, brand_link_token) |
| `brand_wa:{phone_number_id}` | None | Reverse-lookup: Meta webhook → brand config |
| `brand_token:{uuid}` | None | Public chatbot link token → brand hash |

**Analytics (dual-write: global + brand-scoped)**

| Key | TTL | Purpose |
|---|---|---|
| `agent_usage:{YYYY-MM-DD}` | 90 days | Per-agent message counts (global) |
| `agent_usage:{brand_hash}:{day}` | 90 days | Per-agent message counts (brand-scoped) |
| `funnel:{YYYY-MM-DD}` | 90 days | Funnel events (global) |
| `funnel:{brand_hash}:{day}` | 90 days | Funnel events (brand-scoped) |
| `skill_usage:{day}` | 90 days | Per-skill call counts (global) |
| `skill_usage:{brand_hash}:{day}` | 90 days | Per-skill call counts (brand-scoped) |
| `skill_misses:{day}` | 90 days | Tool calls blocked by skill filtering (global) |
| `skill_misses:{brand_hash}:{day}` | 90 days | Tool calls blocked (brand-scoped) |
| `agent_cost:{day}` | 90 days | Agent cost tracking (global) |
| `agent_cost:{brand_hash}:{day}` | 90 days | Agent cost tracking (brand-scoped) |
| `daily_cost:{day}` | 90 days | Daily cost aggregate (global) |
| `daily_cost:{brand_hash}:{day}` | 90 days | Daily cost aggregate (brand-scoped) |
| `feedback:counts` | None | Aggregated thumbs up/down per agent (global) |
| `feedback:counts:{brand_hash}` | None | Feedback counts (brand-scoped) |
| `active_users` | None | Sorted Set: uid → last_seen timestamp (global) |
| `active_users:{brand_hash}` | None | Per-brand active user set |

**Human Mode (brand-scoped)**

| Key | TTL | Purpose |
|---|---|---|
| `{uid}:{brand_hash}:human_mode` | None | Per-brand human mode — `{active: "1", taken_at: timestamp}` |
| `{uid}:human_mode` | None | Legacy global fallback (read if brand-scoped absent) |

**Multi-Brand Isolation**

| Key | TTL | Purpose |
|---|---|---|
| `{uid}:brand_hash` | None | User → brand mapping (persistent, set on first message) |
| `brand_flags:{brand_hash}` | None | Per-brand feature flag overrides (JSON) |

**Multi-Turn Message Handling (Phase B+C)**

| Key | TTL | Purpose |
|---|---|---|
| `wamid:{wamid}` | 24h | WhatsApp message dedup by Meta unique ID |
| `{uid}:wa_queue` | 5 min | Pending WhatsApp messages (RPUSH on arrival, LPOP drain) |
| `{uid}:wa_processing` | 2 min | Per-user drain lock (SET NX) |
| `{uid}:cancel_requested` | 30s | Pipeline cancellation signal |

**Payment**

| Key | TTL | Purpose |
|---|---|---|
| `{uid}:payment_info` | None | pg_id, pg_number, amount, short_link for webhook verification |

**Session Cost**

| Key | TTL | Purpose |
|---|---|---|
| `{uid}:session_cost` | 7 days | tokens_in, tokens_out, cost_usd (Hash) |

### PostgreSQL Tables

```sql
booking_messages (id, user_id, role, content, agent, tokens_in, tokens_out, cost_usd, brand_hash, created_at)
leads (id, user_id, property_id, name, phone, stage, brand_hash, created_at, updated_at)
property_documents (id, property_id, filename, file_type, content_text, size_bytes, uploaded_at)
```
PostgreSQL is **non-critical** — the backend has graceful degradation if it's unavailable. Conversation state lives in Redis, not Postgres. `brand_hash` columns added via idempotent migration on startup (`add_brand_hash_columns`).

### External API Integrations

| Service | Base URL | Auth | Purpose |
|---|---|---|---|
| Rentok | `https://apiv2.rentok.com` | None observed | Property data, bookings, payments, leads, KYC |
| Deepgram | `https://api.deepgram.com` | API key (Edge proxy) | Voice speech-to-text (en/hi/mr) |
| Tavily | `https://api.tavily.com` | API key | Web search for area insights (max 3/conversation) |
| Meta Graph | `https://graph.facebook.com/v19.0` | Bearer token | WhatsApp send (Meta Cloud API) |
| Interakt | `https://amped-express.interakt.ai/api/v17.0` | Bearer token | WhatsApp send (Interakt API) |
| Overpass/OSM | `https://overpass-api.de/api/interpreter` | None | Nearby places (food, transit, medical) |
| OSRM | `https://maps.rentok.com/table/v1/driving` | Custom host | Driving distance/time estimation |

**Property ID Types** — these are NOT interchangeable:

| ID | Format | Example | Used for |
|---|---|---|---|
| `property_id` | `{pg_id}_{pg_number}` | `abc123_1` | Most booking APIs; stored in property_info_map |
| `pg_id` | Firebase UID | `abc123` | Images, shortlist, payment, brand lookup |
| `pg_number` | Integer string | `1` | Images, payment |
| `eazypg_id` | Alphanumeric + suffix | `4000033333B` | Lead creation, tenant UUID lookup, room details |

Using the wrong ID type causes **silent API failures** — Rentok returns success but does nothing.

---

## §9 — Code Conventions

### Backend (Python)

- **Redis helpers are synchronous** in `db/redis_store.py`. Where needed in async FastAPI handlers, they run in `asyncio.run_in_executor`. Don't add `async`/`await` to redis_store.py functions.
- **All tools return plain strings** — success message or error string beginning with `"Error:"`. Claude reads this string and decides how to respond. Never raise exceptions from tools (they're caught by tool_executor.py).
- **`find_property()`** in `utils/properties.py` is the canonical lookup for property names → property_info_map entry. Use it everywhere. Never write your own substring loop.
- **`check_rentok_response()`** in `utils/api.py` validates Rentok API responses before accessing data. All new Rentok calls must use it.
- **`@with_retry`** decorator from `utils/retry.py` — use on all external HTTP calls (2 retries, exponential backoff). Import: `from utils.retry import with_retry`.
- **Tool schemas**: all 28 registered tools have `"strict": true`. Any new tool must include this. Parameter schema changes require all callers to match.
- **Property ID discipline**: always split `property_id` on `_` to get `pg_id` + `pg_number`. Never construct IDs by string concatenation without documentation.
- **Error format**: tools return `f"Error: {description}"`. The tool_executor.py catches exceptions and formats them the same way.

### Chat Frontend (Vanilla JS)

- **No framework** — all DOM manipulation is explicit `createElement` / `appendChild` / `innerHTML` (always through `safeParse` from `src/sanitize.js` for user content).
- **State in config.js** — `ACCOUNT_VALUES`, `FALLBACK_ACCOUNT_VALUES`, `userId`, `chatHistory`, `isWaiting` are mutable module-level exports. No reactive system; no store.
- **ACCOUNT_VALUES nullable** — stream.js uses `ACCOUNT_VALUES ?? FALLBACK_ACCOUNT_VALUES`. Never assume ACCOUNT_VALUES is set.
- **SSE state machine** — stream.js is the central controller. All SSE events funnel through it. Don't add parallel SSE consumers.
- **DOMPurify** — all user-provided or bot-provided text that goes into innerHTML must pass through `safeParse()` or `safeParseInline()` (src/sanitize.js).

### Admin Portal (React 19 / TypeScript)

- **TanStack Query for all server state** — no useState + useEffect for data fetching. Use the hooks in `src/hooks/`. Add `staleTime` and `select` (for shape normalization) when appropriate.
- **All API calls via `apiFetch()`** in `src/lib/api.ts` — it injects `X-API-Key` from localStorage and throws on 401/non-200. Never call `fetch()` directly.
- **shadcn/ui components only** — don't add third-party UI libraries. The design system is Tailwind v4 + shadcn/ui + lucide-react.
- **Types in `src/lib/types.ts`** — all interfaces live here. Add new interfaces here, not inline.
- **Vercel Edge proxies** — every new backend endpoint needs a corresponding `api/*.js` proxy file and an entry in `vercel.json functions` block. Dynamic routes use `[uid].js` directory pattern, not flat files.

---

## §10 — Legacy & Technical Debt

Be honest about this. These exist. Work around them; don't pretend they don't exist.

| Debt | Location | Impact | Notes |
|---|---|---|---|
| **README.md stale** | README.md | Misleading to newcomers | References dead "Room" agent, `/knowledge-base`, `/query` endpoints — all removed March 2026 |
| ~~**main.py god-file**~~ | claude-booking-bot/main.py | ✅ RESOLVED | Split into `routers/` (public, chat, webhooks, admin); main.py now 129 lines — app factory + lifespan only |
| ~~**redis_store.py god-file**~~ | claude-booking-bot/db/redis_store.py | ✅ RESOLVED | Split into `db/redis/` (8 domain modules); redis_store.py is now a backward-compat shim |
| **Monolithic broker prompt** | core/prompts.py (BROKER_AGENT_PROMPT) | Maintained in parallel with skill files | ~340 lines; kept as DYNAMIC_SKILLS_ENABLED=false fallback |
| **No .env.example** | eazypg-chat/ | Undocumented env vars | New developers don't know which vars are needed |
| **No integration tests** | Test suite | Live backend required for all E2E tests | Only `stress_test_broker.py` and `test_dynamic_skills.py` (both require live Render URL) |
| **No Docker** | Deployment | No local containerization | Render uses native Python runtime; reproducing exact prod env locally is hard |
| **DocumentsPage unreachable** | eazypg-admin/src/pages/DocumentsPage.tsx | Dead UI code | Component exists but not in App.tsx routing; likely in-progress feature |
| **admin_api_key in localStorage** | eazypg-admin/src/lib/auth.ts | No expiry, no rotation, single global key | Any admin with the key has full access; no per-user auth |
| **No conversation schema versioning** | db/redis_store.py | TTL-based purge only | If conversation format changes, old keys aren't migrated — they expire naturally |
| **WhatsApp credentials in Redis** | brand_config:{hash} | Plaintext WA access tokens in Redis | Mitigated by Render managed Redis; no transport issue; but a concern if Redis is compromised |

---

## §11 — High-Risk Files

> **Read ARCHITECTURE.md before touching any of these.** A bad change here can silently break all users or all brands.

| File | Risk Level | Why It's Risky |
|---|---|---|
| `claude-booking-bot/db/redis/` | 🔴 CRITICAL | All state operations across 8 modules. Wrong TTL = data loss. Wrong key name = silent miss. Wrong serialization = corrupt state. |
| `claude-booking-bot/core/pipeline.py` | 🔴 CRITICAL | Shared pipeline for chat + WhatsApp. Human mode check, brand-scoped analytics, agent dispatch all flow through here. |
| `claude-booking-bot/routers/webhooks.py` | 🔴 CRITICAL | WhatsApp webhook + Phase B drain task. wamid dedup, queue management, cancellation. Breaking this = no WhatsApp responses. |
| `claude-booking-bot/tools/registry.py` | 🟠 HIGH | All 28 tool schemas with `strict=true`. Schema drift = Anthropic API rejects tool call. Missing `required` field = silent None. |
| `claude-booking-bot/core/prompts.py` | 🟠 HIGH | All system prompts. Small wording change = large behavior change across all users. Monolithic broker prompt lives here as fallback. |
| `claude-booking-bot/skills/broker/_base.md` | 🟠 HIGH | Always loaded for every broker turn. Prompt-cached. Error here affects every broker response. |
| `claude-booking-bot/core/claude.py` | 🟠 HIGH | Anthropic SDK wrapper. Parallel tool execution logic. Streaming protocol. Cost tracking. |
| `claude-booking-bot/core/summarizer.py` | 🟡 MEDIUM | Conversation compaction. Wrong summarization = loss of context or PII retention. Hierarchical merge logic is subtle. |
| `eazypg-chat/src/stream.js` | 🟡 MEDIUM | SSE event parsing, account_values injection, FALLBACK chain. Breaking this = no chat for all users. |
| `eazypg-chat/src/renderers/server-parts.js` | 🟡 MEDIUM | Component registry. Adding a new part type requires coordinating backend + frontend. Wrong type name = silent render failure. |
| `eazypg-admin/src/lib/api.ts` | 🟡 MEDIUM | All admin API calls. Auth header injection. Error handling. Breaking this = whole admin portal goes dark. |
| `claude-booking-bot/channels/whatsapp.py` | 🟡 MEDIUM | Dual Meta/Interakt support. Per-user `is_meta` flag controls routing. Wrong send path = no WhatsApp delivery. |

---

## §12 — Safe Change Strategy

### Changes That Are Safe to Make Independently

- Any `skills/broker/*.md` file **except `_base.md`** — hot-reloaded with 30s cache; no deploy needed; change, test in chat, rollback in seconds
- CSS files (all three sub-projects) — visual only, no behavior
- `src/i18n.js` — translation strings only
- Individual tool handler files (e.g. `tools/broker/shortlist.py`) — as long as you don't change the function signature that `registry.py` references
- Admin portal page/component files — React rendering only, no state/API shape changes

### Changes That Require Backend + Frontend Coordination

- SSE event types — adding a new event type requires both backend (emit) and stream.js (parse)
- `parts[]` schema additions — new part type requires: backend generate, frontend PART_RENDERERS entry, types.ts update
- `account_values` shape — changing fields requires: config.js, stream.js, main.py pipeline, and ARCHITECTURE.md

### Changes That Require Redis Migration Care

- TTL changes on `{uid}:conversation` or `{uid}:property_info_map` — existing keys keep old TTL until expiry; new keys get new TTL
- Key name renames — old keys stay in Redis until their TTL expires; both old and new names may coexist temporarily
- Conversation message format — no migration; old conversations parse with the old format; new ones with new format; plan for both

### Changes That Touch All 3 Deployments

- Brand config endpoint shape changes (`/admin/brand-config`, `/brand-config`) — backend must deploy first, then both Vercel frontends
- New required env var — must add to Render + both Vercel projects before deploying code that uses it

### Never Change Without Reading ARCHITECTURE.md First

- **Redis key schema** (§Redis Key Schema in ARCHITECTURE.md) — every TTL and key name is documented
- **Rentok API parameters** (§Rentok API Catalog) — exact param names, not guessable from code alone
- **Property ID types** (§Property ID Types) — pg_id vs property_id vs eazypg_id — wrong type = silent failure

---

## §13 — AI-Agent Guidance (Claude Code / LLM Context)

> This section is for AI agents (Claude Code sessions) working in this codebase.

**Before reading any source file**, consult `CLAUDE.md` — it has the complete file map with exact line numbers for every key function. You should almost never need to read more than 2-3 files to understand a problem.

**Use offset + limit reads**:
```
Read claude-booking-bot/routers/chat.py offset=1 limit=80     # chat endpoints
Read claude-booking-bot/routers/webhooks.py offset=1 limit=80 # WhatsApp webhook
Read claude-booking-bot/db/redis/user.py offset=12 limit=40   # get_user_memory
Read claude-booking-bot/agents/broker_agent.py offset=22 limit=40  # get_config dual-path
```

**Key function locations** (from CLAUDE.md):
- Pipeline: `core/pipeline.py` — `run_pipeline@32`, `_route_agent@113`
- Chat endpoints: `routers/chat.py` — `POST /chat`, `POST /chat/stream`
- WhatsApp: `routers/webhooks.py` — `POST /webhook/whatsapp`, `_drain_and_process`
- Admin: `routers/admin.py` — all `/admin/*` routes (brand-scoped)
- Redis ops: `db/redis/user.py` — `get_user_memory@12`, `update_user_memory@40`, `get_lead_score@200`
- Skill loading: `skills/loader.py` — `build_skill_prompt@38`
- Routing: `core/router.py` — `apply_keyword_safety_net@15`
- Tool executor: `core/tool_executor.py` — `ToolExecutor@55`, `set_fallback@66`
- Component registry: `eazypg-chat/src/renderers/server-parts.js` — `renderFromServerParts@359`

**When making changes, always update**:
- `CLAUDE.md` — add new files to the file map, add new endpoints to the endpoint list, add new Redis keys to the Redis key section
- `ARCHITECTURE.md` — for Redis key schema changes, Rentok API additions, agent-tool mapping changes

**Do not spawn multiple Explore agents** when CLAUDE.md already has the answer. It almost always does.

**When in doubt about an agent's behavior**, read its system prompt section in `core/prompts.py` and its tool registrations in `tools/registry.py`. The truth is in those two files.

**The dynamic skill system is the highest-leverage place** to change broker behavior: edit `.md` files in `skills/broker/`, no deploy needed, changes take effect within 30 seconds.

---

## §14 — Practical Commands

### Local Development

```bash
# Backend
cd "CC Booking Bot FInal/claude-booking-bot"
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your API keys
uvicorn main:app --reload --port 8000

# Chat frontend (proxies /api/* to :8000)
cd "CC Booking Bot FInal/eazypg-chat"
npm install
npm run dev  # Starts at http://localhost:5173

# Admin portal (proxies /api/* to :8000 with X-API-Key injection)
cd "CC Booking Bot FInal/eazypg-admin"
npm install
npm run dev  # Starts at http://localhost:5174
```

### Verification

```bash
# Backend health
curl https://claude-booking-bot.onrender.com/health

# Import check (zero warnings = clean)
cd claude-booking-bot && python -c "import main; print('OK')"

# Rate limit status
curl "https://claude-booking-bot.onrender.com/rate-limit/status?user_id=test_user"

# Feature flags
curl -H "X-API-Key: YOUR_KEY" https://claude-booking-bot.onrender.com/admin/flags
```

### Debugging

```bash
# Redis CLI (Render managed — connect via Render dashboard CLI)
redis-cli GET "uid:conversation"
redis-cli HGETALL "skill_usage:2026-03-09"
redis-cli HGETALL "agent_usage:2026-03-09"
redis-cli KEYS "brand_config:*"
redis-cli GET "brand_config:YOUR_HASH"

# Admin analytics
curl -H "X-API-Key: YOUR_KEY" https://claude-booking-bot.onrender.com/admin/analytics

# Funnel data
curl -H "X-API-Key: YOUR_KEY" https://claude-booking-bot.onrender.com/funnel
```

### E2E Tests (require live backend)

```bash
cd claude-booking-bot

# 16-tool comprehensive test (verifies all registered tools)
python test_comprehensive.py

# 20-scenario broker regression — local backend
python stress_test_broker.py
python stress_test_broker.py --scenario 3  # Run only scenario 3
python stress_test_broker.py --from 5      # Start from scenario 5

# 20-scenario broker regression — production URL
python stress_test_broker_prod.py

# Dynamic skill system E2E (8 scenarios, verifies skill analytics delta)
python test_dynamic_skills.py

# Fixed tools regression + full integration
python test_fixed_tools.py
python test_full_integration.py
```

### Brand Seeding (OxOtel initial setup)

```bash
# Run once after deploying to create OxOtel chatbot link
curl -X POST https://claude-booking-bot.onrender.com/admin/brand-config \
  -H "X-API-Key: oxotel-uat-2026" \
  -H "Content-Type: application/json" \
  -d '{
    "pg_ids": [
      "l5zf3ckOnRQV9OHdv5YTTXkvLHp1",
      "egu5HmrYFMP8MRJyMsefnpaL7ka2",
      "Z2wyLOXXp5QA596DQ6aZAQpakmQ2",
      "UaDCGP3dzzZRgVIzBDgXb5ry5ng2",
      "EqhTMiUNksgXh5QhGQRsY5DQiO42",
      "fzDBxYtHgVV21ertfkUdSHeomiv2",
      "CUxtdeaGxYS8IMXmGZ1yUnqyfOn2",
      "wtlUSKV9H8bkNqvlGmnogwoqwyk2",
      "1Dy0t6YeIHh3kQhqvQR8tssHWKt1",
      "U2uYCaeiCebrE95iUDsS4PwEd1J2"
    ],
    "brand_name": "OxOtel",
    "cities": "Mumbai",
    "areas": "Andheri, Kurla, Powai"
  }'
# Response: {"ok": true, "brand_link_token": "<uuid>"}
# Chatbot URL: https://eazypg-chat.vercel.app?brand=<uuid>
```

### Skill Hot-Reload (no deploy needed)

```bash
# Edit skill .md file
vim claude-booking-bot/skills/broker/search.md

# Changes take effect automatically within 30 seconds (loader.py memory cache TTL)
# To force immediate reload, restart the Uvicorn process (or kill/restart Render service)
```

---

## §15 — Deployment & Environment

### Deployments

| Service | URL | Host | Trigger |
|---|---|---|---|
| Backend | `https://claude-booking-bot.onrender.com` | Render (Oregon) | Push to main |
| Chat widget | `https://eazypg-chat.vercel.app` | Vercel | Push to main |
| Admin portal | `https://eazypg-admin.vercel.app` | Vercel (separate project) | Push to main |

### Backend Environment Variables (Render)

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ Yes | — | Claude API key |
| `REDIS_URL` | ✅ Yes | — | Render managed Redis connection URL |
| `DATABASE_URL` | ✅ Yes | — | Render managed PostgreSQL connection URL |
| `RENTOK_API_BASE_URL` | No | `https://apiv2.rentok.com` | Rentok API base |
| `API_KEY` | No | — | Admin endpoint auth key (blank = auth disabled) |
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `WHATSAPP_VERIFY_TOKEN` | No | `booking-bot-verify` | Meta webhook verification token |
| `TAVILY_API_KEY` | No | — | Web search (disabled if missing) |
| `OSRM_API_KEY` | No | — | OSRM routing (optional) |
| `CHAT_BASE_URL` | No | `https://eazypg-chat.vercel.app` | Used to build chatbot URL in brand config response |
| `HAIKU_MODEL` | No | `claude-haiku-4-5-20251001` | Broker/supervisor model |
| `SONNET_MODEL` | No | `claude-sonnet-4-6` | All other agents |
| `KYC_ENABLED` | No | `false` | Aadhaar verification (disabled in production) |
| `PAYMENT_REQUIRED` | No | `false` | Payment before reservation; set false to skip payment step |
| `DYNAMIC_SKILLS_ENABLED` | No | `true` | Dynamic skill system; set false for instant rollback to monolithic prompt |
| `WA_DEBOUNCE_SECONDS` | No | `2.0` | WhatsApp multi-turn queue debounce |
| `WAMID_DEDUP_TTL` | No | `86400` | WhatsApp message dedup TTL (seconds) |
| `WEB_SEARCH_ENABLED` | No | `true` | Web search feature flag |
| `WEB_SEARCH_MAX_PER_CONVERSATION` | No | `3` | Max Tavily calls per conversation |

### Admin Portal Environment Variables (Vercel)

| Variable | Required | Description |
|---|---|---|
| `BACKEND_URL` | No | Backend URL (defaults to Render URL if unset) |

### Chat Widget Environment Variables (Vercel)

None required in production. `FALLBACK_ACCOUNT_VALUES` is hardcoded in `src/config.js`. Deepgram key is injected via Vercel's `api/deepgram-token.js` Edge proxy using `DEEPGRAM_API_KEY` (set on Vercel project settings).

---

## §16 — Known Unknowns

These are things where the codebase evidence is ambiguous or incomplete. Don't assume — verify.

| Unknown | Evidence | How to resolve |
|---|---|---|
| **Rentok API authentication** | No `Authorization` header in any tool file. Requests use only JSON body params. | Confirm with Rentok team. Could be IP whitelisting on Render egress. |
| **OSRM endpoint SLA** | `maps.rentok.com/table/v1/driving` is a custom host (not the public OSRM). | Confirm with Rentok team. No SLA or rate limits documented. |
| **WhatsApp end-to-end in production** | WhatsApp SEND requires per-user `account_values` in Redis with `whatsapp_access_token`, `whatsapp_phone_number_id`, `waba_id`. Webhook hydration works via `brand_wa:{phone_id}`. | Test with real WhatsApp number + OxOtel Meta credentials after seeding brand config. |
| **KYC flow status** | `KYC_ENABLED=false` in production. Full Aadhaar OTP flow implemented in `tools/booking/kyc.py`. | Enable only after completing Meta/Rentok KYC integration agreement. |
| **Rentok CRM lead deduplication** | `addLeadFromEazyPGID` is called on every visit schedule. No dedup logic in our code. | Confirm if Rentok deduplicates on phone + eazypg_id. |
| **DocumentsPage routing** | `eazypg-admin/src/pages/DocumentsPage.tsx` exists but is not in `App.tsx` routes. | Confirm if this is in-progress or dead. Likely in-progress (uses property_documents table). |
| **Deepgram cost** | Deepgram API token is generated per-request via Edge proxy. No rate limiting on voice input. | Monitor Deepgram usage dashboard; consider adding per-user limits if costs spike. |

---

## §17 — Glossary

| Term | Definition |
|---|---|
| **pg_id** | Firebase UID of a property group (e.g. `l5zf3ckOnRQV9OHdv5YTTXkvLHp1`). Part of `property_id`. |
| **pg_number** | Integer string identifying a specific unit within a pg_id (e.g. `"1"`). Part of `property_id`. |
| **property_id** | Compound key `{pg_id}_{pg_number}` (e.g. `abc123_1`). Used in most booking API calls. |
| **eazypg_id** | Alphanumeric identifier with suffix (e.g. `4000033333B`). Used for leads, tenant lookup, room details. NOT interchangeable with property_id. |
| **account_values** | Brand config object `{pg_ids, brand_name, cities, areas, wa_token, ...}`. Sent in every SSE request body (web); stored in Redis per-user (WhatsApp). |
| **skill** | One of 12 named broker capabilities (search, details, compare, etc.). Maps to a `.md` prompt fragment + filtered tool set. Loaded dynamically per turn by the supervisor. |
| **parts[]** | Structured array of UI components returned in the SSE `done` event. Backend decides what components to show; frontend renders via component registry. |
| **human mode** | Admin takeover state. When active, AI is completely bypassed — all three pipeline paths return early without calling any agent. Cleared when admin clicks "Resume". |
| **brand hash** | `sha256(api_key).hexdigest()[:16]` — the Redis prefix for all brand-scoped data. Raw API key is never stored. |
| **brand_link_token** | UUID v4 auto-generated on first brand config save. Used as the `?brand=` URL param in the public chatbot link. Permanent — no expiry. |
| **ALWAYS_TOOLS** | `["save_preferences", "search_properties"]` — broker tools always included regardless of which skills are active. |
| **FALLBACK_ACCOUNT_VALUES** | OxOtel's 10 pg_ids hardcoded in `eazypg-chat/src/config.js`. Used when no `?brand=` URL param or when brand config fetch fails/times out. |
| **generative UI** | Pattern where the backend controls what UI components appear (not just text). Backend emits `parts[]`; frontend is a stateless renderer. |
| **polyrepo root** | The `CC Booking Bot FInal/` directory is NOT a monorepo — it's a shared parent directory for three independent projects with no shared tooling or package.json. |

---

## §18 — Document Maintenance

### When to Update This File

Update DIRECTORY.md any time you:
- Add, rename, or delete a sub-project directory
- Add a new deployment environment
- Add a new external API integration
- Add or remove a feature domain (agent, tool category, skill)
- Change the Redis key schema (also update ARCHITECTURE.md)
- Add a new major workflow
- Discover and document a new unknown or debt

### What to Keep in Sync

| Change | Files to update |
|---|---|
| New file in any sub-project | `CLAUDE.md` (file map) |
| New API endpoint | `CLAUDE.md` (endpoint list), `ARCHITECTURE.md` (if Rentok) |
| New Redis key | `ARCHITECTURE.md` (Redis Key Schema), `DIRECTORY.md §8` |
| New environment variable | `DIRECTORY.md §15`, README.md env table |
| New agent or tool | `CLAUDE.md` (file map), `ARCHITECTURE.md` (agent-tool mapping), `DIRECTORY.md §6` |
| Structural architecture change | `DIRECTORY.md §5`, `CLAUDE.md` (Architecture Overview) |

### Cross-Reference Map

| Document | What it's for | Read it when |
|---|---|---|
| **DIRECTORY.md** (this file) | High-level operating guide, architecture, risk map | Starting any work |
| **CLAUDE.md** | Complete file map with exact line numbers, task recipes | Before reading source files |
| **ARCHITECTURE.md** | Redis key schema, Rentok API catalog, agent-tool mapping, request lifecycle detail | Before changing data layer or APIs |
| **MEMORY.md** | Session history, known bugs, recent decisions | When you see something that "shouldn't be possible" |

> Do not let DIRECTORY.md become stale. A wrong map is worse than no map.
