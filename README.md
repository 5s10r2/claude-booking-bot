# EazyPG AI Booking Bot — Backend

> Multi-tenant, multi-channel conversational AI assistant for PG (Paying Guest) booking in India. Powered by Claude (Anthropic), deployed on Render, with Web + WhatsApp channels.

![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Claude](https://img.shields.io/badge/Claude_AI-191919?style=flat&logo=anthropic&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=flat&logo=redis&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white)
![Render](https://img.shields.io/badge/Render-46E3B7?style=flat&logo=render&logoColor=white)

**Last updated**: 2026-03-15

---

## What It Does

A full-stack conversational AI assistant that helps users find, compare, and book PG accommodations across Indian cities. Four specialized AI agents handle different aspects of the booking journey — from property search and comparison to visit scheduling and payment — powered by Claude Sonnet and Haiku models. The backend decides what UI to render (Generative UI pattern), and the frontend is a lightweight component registry that renders structured parts.

**Multi-tenant**: Each brand operator (OxOtel, Stanza, Zelter) gets their own API key, property scope, feature flags, analytics, and shareable chatbot URL. All data is isolated at the Redis key prefix level using `sha256(api_key)[:16]` as brand hash.

---

## Key Features

- **Multi-Agent AI** — Supervisor routes to 4 specialized agents: Broker, Booking, Profile, Default
- **Dynamic Skill System** — Broker agent loads only the skills/tools needed per turn (12 `.md` skill files, hot-reloadable, 30s cache)
- **Multi-Brand Isolation** — Per-brand data, analytics (dual-write), feature flags, human mode, and admin scoping
- **Property Search & Comparison** — Geocoded search, outcome-aware match scoring, side-by-side comparison tables
- **Visit Scheduling & Payments** — Schedule visits, reserve beds, create payment links (payment optional via `PAYMENT_REQUIRED` flag)
- **Post-Visit Follow-Ups** — 3-step automated follow-up state machine (2h/24h/48h) with reply classification
- **Observability Suite** — Tool reliability, response latency, routing accuracy, conversation quality (0-100), attention flags, structured error log
- **Outcome-Aware Recommendations** — Property conversion/no-show history adjusts match scores (+3/conversion, -5 for 2+ no-shows)
- **Lead Outcomes** — Admin marks converted/lost/no_show with side effects (funnel tracking, deal-breakers, property signals)
- **Generative UI** — Backend-controlled rich components (carousels, status cards, galleries, confirmation cards, expandable sections)
- **Dual Channel** — Web chat (SSE streaming with AbortController interrupt) + WhatsApp (Meta/Interakt APIs with multi-turn queue)
- **WhatsApp Multi-Turn** — Phase B+C: wamid dedup, Redis queue, 2s debounce, pipeline cancellation on new messages
- **Human Mode** — Admin can take over any conversation (brand-scoped); AI is fully bypassed while conversation history is preserved
- **Multilingual** — English, Hindi, Marathi with locale-aware UI
- **Voice Input** — Deepgram Nova-3 speech-to-text in all 3 languages
- **Smart Memory** — Cross-session user preferences, implicit feedback, conversation summarization (with brand context)
- **Web Intelligence** — Live web search for area insights and market data
- **Property Maps** — Leaflet maps with property pins, commute estimation via OSRM
- **Lead Scoring** — Automated lead qualification based on engagement signals
- **Property Documents KB** — Upload PDFs/XLSX/CSV/TXT per property; content injected into broker prompt
- **Per-Brand Feature Flags** — KYC_ENABLED, PAYMENT_REQUIRED, DYNAMIC_SKILLS_ENABLED — toggleable per brand at runtime

---

## Architecture

```
                          ┌─────────────┐
                          │   Frontend   │
                          │ (Vercel SPA) │
                          └──────┬───────┘
                                 │ SSE /chat/stream
                          ┌──────▼───────┐       ┌──────────────┐
  WhatsApp ──webhook──►   │   FastAPI    │◄─────►│    Redis     │
                          │  (routers/)  │       │  (state,     │
                          └──────┬───────┘       │   cache,     │
                                 │               │   analytics, │
                          ┌──────▼───────┐       │   brands)    │
                          │  Supervisor  │       └──────────────┘
                          │  (routing)   │
                          └──────┬───────┘       ┌──────────────┐
                     ┌───────────┼──────────┐    │  PostgreSQL  │
                     ▼           ▼          ▼    │  (msg logs,  │
               ┌──────────┐ ┌────────┐ ┌─────────┐ leads)     │
               │  Broker  │ │Booking │ │ Profile  │  + Default  └──────────────┘
               │ (Haiku)  │ │(Sonnet)│ │ (Sonnet) │
               └────┬─────┘ └───┬────┘ └────┬────┘
                    │            │            │
               ┌────▼────────────▼────────────▼────┐
               │           Tool Layer               │
               │  search, compare, schedule_visit,  │
               │  payment, shortlist, web_search,   │
               │  landmarks, images, preferences    │
               └───────────────┬───────────────────┘
                               │
                        ┌──────▼───────┐
                        │  Rentok API  │
                        │ (properties) │
                        └──────────────┘
```

**Dynamic Skill System (Broker Agent):**

The broker agent uses a skill-based architecture. The supervisor detects 1-3 skills per turn. Only the relevant skill files (`.md`) and their associated tools are loaded, reducing token usage and improving focus.

```
Supervisor → { "agent": "broker", "skills": ["search", "selling"] }
                                  │
                     skills/broker/_base.md      (always loaded, cached)
                   + skills/broker/search.md     (uncached, per-turn)
                   + skills/broker/selling.md    (uncached, per-turn)
                                  │
                     Tools filtered to match skills (3-5 vs 12 full set)
```

**Multi-Brand Isolation:**

```
API key (e.g. "oxotel-uat-2026")
  → sha256(key)[:16] = brand_hash (Redis prefix for all brand-scoped data)
  → Raw API key NEVER stored in Redis or logs
  → All admin endpoints use require_admin_brand_key → scoped to brand's data
  → Analytics dual-write: global + brand_hash-scoped keys
  → Feature flags: global defaults merged with brand overrides
```

**Generative UI Pattern:**

The backend returns structured `parts[]` in the SSE `done` event. The frontend maps each part type to a renderer:

```
parts: [
  { type: "text", markdown: "..." },
  { type: "property_carousel", properties: [...] },
  { type: "quick_replies", chips: [...] }
]
        │
        ▼
PART_RENDERERS = {
  text → renderTextPart()
  property_carousel → renderPropertyCarousel()
  comparison_table → renderComparisonTable()
  quick_replies → renderQuickReplies()
  action_buttons, status_card, image_gallery,
  confirmation_card, error_card, expandable_sections
}
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **AI** | Claude Sonnet 4.6, Claude Haiku 4.5 | Agent reasoning (Sonnet for most, Haiku for broker/supervisor) |
| **Backend** | FastAPI, Python 3.11+ | API server, SSE streaming, webhook handlers |
| **Cache/State** | Redis | Conversations, preferences, property cache, rate limits, analytics, brand config |
| **Database** | PostgreSQL | Message logging, leads, property documents |
| **Frontend** | Vanilla JS, Vite 6 | Chat UI, component registry, voice input |
| **Admin** | React 19, TypeScript, TanStack Query, shadcn/ui | Admin portal for brand operators |
| **Maps** | Leaflet, OSRM | Property maps, commute estimation |
| **Voice** | Deepgram Nova-3 | Speech-to-text (en/hi/mr) |
| **Hosting** | Render (backend), Vercel (frontends) | Auto-deploy from git |
| **WhatsApp** | Meta Cloud API / Interakt | WhatsApp channel |

---

## Project Structure

```
claude-booking-bot/
├── main.py                  # FastAPI app factory + lifespan (129 lines)
├── config.py                # Pydantic settings, feature flags, model IDs
├── requirements.txt         # Python dependencies
├── build.sh                 # Render build script
├── CLAUDE.md                # Complete file map with line numbers + task recipes
├── agents/                  # AI agent configs
│   ├── supervisor.py        # Intent routing → {agent, skills[]}
│   ├── broker_agent.py      # Property search/compare (dual-path: dynamic skills vs legacy)
│   ├── booking_agent.py     # Visits, payments, reservations
│   ├── profile_agent.py     # User preferences
│   └── default_agent.py     # Greetings, general help
├── routers/                 # FastAPI route modules
│   ├── public.py            # GET /health, GET /brand-config
│   ├── chat.py              # POST /chat, POST /chat/stream, POST /feedback, POST /language
│   ├── webhooks.py          # WhatsApp webhook, payment webhook, cron follow-ups
│   └── admin.py             # All /admin/* endpoints (brand-scoped via require_admin_brand_key)
├── core/                    # Engine
│   ├── claude.py            # Anthropic API wrapper (split prompt caching, cancellation checkpoint)
│   ├── prompts.py           # All system prompts (feature-flag-driven template vars)
│   ├── pipeline.py          # Shared pipeline: run_pipeline() for chat + WhatsApp
│   ├── auth.py              # Auth helpers: require_admin_brand_key, require_brand_api_key
│   ├── state.py             # Shared singletons (engine, conversation)
│   ├── followup.py          # Multi-step post-visit follow-up state machine (3-step, 2h/24h/48h)
│   ├── attention.py         # Needs-attention flag computation (5 conditions, 1h TTL)
│   ├── ui_parts.py          # Generative UI part generation
│   ├── message_parser.py    # Response → structured parts
│   ├── conversation.py      # History management + compaction (brand-aware)
│   ├── summarizer.py        # Hierarchical token-aware summarization (brand context)
│   ├── rate_limiter.py      # Sliding-window rate limits
│   ├── router.py            # Keyword safety net (3-phase: phrases→words→last_agent)
│   └── tool_executor.py     # Tool dispatch + graceful skill fallback
├── tools/                   # Tool implementations
│   ├── broker/              # search, compare, details, images, landmarks, shortlist, preferences, nearby, commute, query
│   ├── booking/             # payment, schedule_visit, schedule_call, reserve, cancel, reschedule, kyc, save_phone
│   ├── profile/             # user details, events, shortlisted
│   ├── default/             # brand_info
│   ├── common/              # web_search
│   └── registry.py          # Tool registration (28 tools, strict schemas, conditional payment/KYC tools)
├── skills/                  # Dynamic skill system (broker agent only)
│   ├── loader.py            # Skill file loading + YAML frontmatter + hot-reload (30s cache)
│   ├── skill_map.py         # Skill→tool mapping + keyword fallback
│   └── broker/              # 12 .md skill files (_base, search, details, compare, …)
├── db/                      # Data layer
│   ├── redis/               # Redis domain package (8 modules, ~1,279 lines)
│   │   ├── _base.py         # Connection pool, helpers
│   │   ├── conversation.py  # History, wamid dedup, WA queue, pipeline cancel
│   │   ├── user.py          # Memory, preferences, shortlist, followups, lead score
│   │   ├── property.py      # Property cache, images, templates
│   │   ├── payment.py       # Payment link + active request dedup
│   │   ├── analytics.py     # Funnel, feedback, usage, costs, property signals (dual-write)
│   │   ├── quality.py       # Conversation quality scoring (0-100, 7 signals)
│   │   ├── brand.py         # Brand config, WA reverse-lookup, per-brand flags
│   │   └── admin.py         # Active users, human mode (brand-scoped), session cost
│   ├── redis_store.py       # Backward-compat shim (re-exports from db/redis/)
│   └── postgres.py          # Message logging + leads + property docs + error events (brand_hash column)
├── channels/
│   └── whatsapp.py          # WhatsApp send (Meta/Interakt dual support)
├── utils/                   # Helpers
│   ├── scoring.py           # Property match scoring (weighted, fuzzy amenity, outcome-aware)
│   ├── geo.py               # Shared geocoding helper
│   ├── date.py              # Date/time parsing
│   ├── image.py             # Image processing (WEBP→JPEG for WhatsApp)
│   ├── retry.py             # Async retry decorator (2 retries, exponential backoff)
│   ├── properties.py        # Shared property lookup (exact + substring match)
│   ├── api.py               # Rentok API response validation
│   └── property_docs.py     # KB document formatting for prompt injection
├── data/
│   └── transit_lines.json   # Metro/transit lines (Mumbai/Bangalore/Delhi/Pune)
├── docs/                    # Documentation
│   ├── ARCHITECTURE.md      # Deep reference: Redis keys, Rentok API, agent-tool mapping
│   ├── DIRECTORY.md         # Canonical operating document (18 sections)
│   ├── CHANGES_FROM_MAIN.md # Change log
│   └── screenshots/         # 20 UI screenshots
└── tests                    # E2E tests (all require live backend)
    ├── stress_test_broker.py      # 20-scenario broker regression
    ├── stress_test_broker_prod.py # Same, against production URL
    ├── test_comprehensive.py      # 16-tool comprehensive test
    ├── test_dynamic_skills.py     # 8-scenario dynamic skill E2E
    ├── test_fixed_tools.py        # Fixed tools regression
    └── test_full_integration.py   # Full integration suite
```

> **For the complete file map with line numbers**, see `CLAUDE.md`. For deep dives into Redis keys, Rentok API params, or agent-tool mapping, see `docs/ARCHITECTURE.md`.

---

## Getting Started

### Prerequisites

- Python 3.11+
- Redis (local or managed)
- PostgreSQL (local or managed)
- Anthropic API key

### Backend Setup

```bash
cd claude-booking-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys and database URLs

# Run the server
uvicorn main:app --reload --port 8000
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `REDIS_URL` | Yes | — | Redis connection URL |
| `DATABASE_URL` | Yes | — | PostgreSQL connection URL |
| `RENTOK_API_BASE_URL` | No | `https://apiv2.rentok.com` | Rentok property API |
| `API_KEY` | No | — | Admin endpoint auth (disabled if empty) |
| `WHATSAPP_VERIFY_TOKEN` | No | `booking-bot-verify` | Meta webhook verification token |
| `TAVILY_API_KEY` | No | — | Tavily web search API key |
| `OSRM_API_KEY` | No | — | OSRM routing API key (commute estimation) |
| `CHAT_BASE_URL` | No | `https://eazypg-chat.vercel.app` | Chatbot URL for brand config response |
| `HAIKU_MODEL` | No | `claude-haiku-4-5-20251001` | Broker/supervisor model |
| `SONNET_MODEL` | No | `claude-sonnet-4-6` | Other agents model |
| `KYC_ENABLED` | No | `false` | Enable Aadhaar verification |
| `PAYMENT_REQUIRED` | No | `false` | Require payment before reservation (false = skip payment step) |
| `DYNAMIC_SKILLS_ENABLED` | No | `true` | Dynamic skill system (false = legacy monolithic prompt) |
| `WEB_SEARCH_MAX_PER_CONVERSATION` | No | `3` | Max web search calls per conversation |
| `WA_DEBOUNCE_SECONDS` | No | `2.0` | WhatsApp multi-turn queue debounce |
| `WAMID_DEDUP_TTL` | No | `86400` | WhatsApp message dedup TTL (seconds) |

---

## API Endpoints

### Public

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/brand-config?token={uuid}` | Public brand config (no auth — safe fields only) |

### Chat

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat` | Synchronous chat (JSON response) |
| `POST` | `/chat/stream` | SSE streaming chat (primary web endpoint) |
| `POST` | `/feedback` | Submit user feedback (thumbs up/down) |
| `GET` | `/feedback/stats` | Feedback statistics |
| `GET` | `/funnel` | Conversion funnel data |
| `GET` | `/rate-limit/status` | Rate limit status for a user |
| `POST` | `/language` | Set user language preference |

### WhatsApp

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook/whatsapp` | WhatsApp incoming (wamid dedup → queue → drain) |
| `GET` | `/webhook/whatsapp` | WhatsApp webhook verification |
| `POST` | `/webhook/payment` | Payment callback from Rentok |
| `POST` | `/cron/follow-ups` | Scheduled follow-up messages |

### Admin (all brand-scoped via `require_admin_brand_key`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/conversations` | Paginated conversation list |
| `GET` | `/admin/conversations/{uid}` | Full thread + memory + cost + human_mode |
| `POST` | `/admin/conversations/{uid}/takeover` | Activate human mode (brand-scoped) |
| `POST` | `/admin/conversations/{uid}/resume` | Deactivate human mode |
| `POST` | `/admin/conversations/{uid}/message` | Send admin message via WhatsApp |
| `GET` | `/admin/command-center` | Today's KPIs (messages, leads, visits, costs) |
| `GET` | `/admin/leads` | Filterable lead list (+ outcome filter) |
| `POST` | `/admin/leads/{uid}/outcome` | Mark lead outcome (converted/lost/no_show/in_progress) |
| `GET` | `/admin/analytics` | Full analytics (funnel, agents, skills, costs, feedback, property_performance, quality_distribution, error_summary) |
| `GET` | `/admin/errors` | Paginated structured error events (type/days filters) |
| `GET` | `/admin/flags` | Effective feature flags (global + brand overrides) |
| `POST` | `/admin/flags` | Toggle feature flags per-brand |
| `POST` | `/admin/broadcast` | WhatsApp blast to brand's active users (7 days) |
| `GET` | `/admin/properties` | List brand's properties |
| `POST` | `/admin/properties/{prop_id}/documents` | Upload document (ownership check) |
| `GET` | `/admin/properties/{prop_id}/documents` | List documents |
| `DELETE` | `/admin/properties/{prop_id}/documents/{doc_id}` | Delete document |
| `GET` | `/admin/brand-config` | Get brand config (token masked) |
| `POST` | `/admin/brand-config` | Create/update brand config |
| `POST` | `/admin/backfill-brands` | One-time migration: tag users with brand_hash |

---

## AI Agents

| Agent | Model | Responsibility |
|-------|-------|---------------|
| **Supervisor** | Haiku | Classifies user intent → `{agent, skills[]}` |
| **Broker** | Haiku | Property search, details, images, comparison, landmarks, shortlisting |
| **Booking** | Sonnet | Visit scheduling, call scheduling, reservations, payments, KYC |
| **Profile** | Sonnet | User preferences, scheduled events, shortlisted properties |
| **Default** | Sonnet | Greetings, brand information, general help |

The Broker and Supervisor agents use Haiku for cost efficiency (highest volume of requests). All other agents use Sonnet for higher reasoning quality.

---

## Dynamic Skill System

The broker agent uses a hot-reloadable skill file architecture. Skills are `.md` files with YAML frontmatter — editable without code changes.

| Skill File | Purpose |
|-----------|---------|
| `_base.md` | Identity, response format, tool policy — always loaded + cached |
| `qualify_new.md` | New user qualification (bundled intro questions) |
| `qualify_returning.md` | Returning user warm greeting |
| `search.md` | Preferences → search → results display |
| `details.md` | Property details, images, room types |
| `compare.md` | Side-by-side comparison + recommendation |
| `commute.md` | Commute estimation (driving + transit) |
| `shortlist.md` | Save to shortlist workflow |
| `show_more.md` | Load next batch / expand radius |
| `selling.md` | Objection handling, sentiment detection, value framing |
| `web_search.md` | Area/safety/market web intelligence |
| `learning.md` | Implicit feedback, deal-breaker detection |

**Rollback:** Set `DYNAMIC_SKILLS_ENABLED=false` to instantly revert to the monolithic broker prompt.

**Metrics:** Skill usage tracked in Redis (`skill_usage:{day}` + `skill_usage:{brand_hash}:{day}`, HINCRBY per skill). Exposed in `/admin/analytics`.

---

## Human Mode

Admin operators can take over any conversation from the admin portal. Human mode is **brand-scoped** — only the brand that activated takeover blocks AI; other brands are unaffected.

When human mode is active:
- `pipeline.py` checks `get_human_mode(uid, brand_hash)` before routing → early return
- AI never responds while human mode is active for that brand
- Conversation history continues to be saved
- Admin can send messages via `POST /admin/conversations/{uid}/message`
- "Resume AI" button clears human mode

Toggle via: `POST /admin/conversations/{uid}/takeover` and `POST /admin/conversations/{uid}/resume`

---

## Deployment

### Backend (Render)

- **Build command**: `bash build.sh` (installs Python dependencies)
- **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Services**: Managed Redis + PostgreSQL on Render
- **Live URL**: `https://claude-booking-bot.onrender.com`
- **Auto-deploy**: Push to `main` branch

### Frontends (Vercel)

| Project | URL | Purpose |
|---------|-----|---------|
| eazypg-chat | `https://eazypg-chat.vercel.app` | Chat widget (Vanilla JS) |
| eazypg-admin | `https://eazypg-admin.vercel.app` | Admin portal (React 19 + TypeScript) |

---

## Rate Limits

| Limit | Value |
|-------|-------|
| Per-user per-minute | 6 messages |
| Per-user per-hour | 30 messages |
| Global per-minute | 100 messages |
| Web search per-conversation | 3 calls |

---

## Documentation

| Document | Purpose | Read when |
|----------|---------|-----------|
| `CLAUDE.md` | Complete file map with line numbers, task recipes | Before reading any source file |
| `docs/ARCHITECTURE.md` | Redis key schema, Rentok API catalog, agent-tool mapping | Before changing data layer or APIs |
| `docs/DIRECTORY.md` | High-level operating guide, architecture, risk map | Starting any work |
| `RENTOK_API.md` | Detailed Rentok API documentation with gotchas | Before any Rentok integration |

---

## License

MIT
