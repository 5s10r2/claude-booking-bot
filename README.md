# OxOtel AI Booking Bot — Backend

> AI-powered PG (Paying Guest) booking assistant with multi-agent architecture, Generative UI, and dual-channel support (Web + WhatsApp).

![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Claude](https://img.shields.io/badge/Claude_AI-191919?style=flat&logo=anthropic&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=flat&logo=redis&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white)
![Render](https://img.shields.io/badge/Render-46E3B7?style=flat&logo=render&logoColor=white)

---

## What It Does

A full-stack conversational AI assistant that helps users find, compare, and book PG accommodations across Indian cities. Four specialized AI agents handle different aspects of the booking journey — from property search and comparison to visit scheduling and payment — powered by Claude Sonnet and Haiku models. The backend decides what UI to render (Generative UI pattern), and the frontend is a lightweight component registry that renders structured parts.

---

## Key Features

- **Multi-Agent AI** — Supervisor routes to 4 specialized agents: Broker, Booking, Profile, Default
- **Dynamic Skill System** — Broker agent loads only the skills/tools needed per turn (12 `.md` skill files, hot-reloadable, 30s cache)
- **Property Search & Comparison** — Geocoded search, match scoring, side-by-side comparison tables
- **Visit Scheduling & Payments** — Schedule visits, reserve beds, create payment links
- **Generative UI** — Backend-controlled rich components (carousels, status cards, galleries, confirmation cards)
- **Dual Channel** — Web chat (SSE streaming) + WhatsApp (Meta/Interakt APIs)
- **Human Mode** — Admin can take over any conversation; AI is fully bypassed across all three pipeline paths (SSE, JSON, WhatsApp webhook) while conversation history is preserved
- **Multilingual** — English, Hindi, Marathi with locale-aware UI
- **Voice Input** — Deepgram Nova-3 speech-to-text in all 3 languages
- **Smart Memory** — Cross-session user preferences, implicit feedback, conversation summarization
- **Web Intelligence** — Live web search for area insights and market data
- **Property Maps** — Leaflet maps with property pins, commute estimation via OSRM
- **Lead Scoring** — Automated lead qualification based on engagement signals
- **Property Documents KB** — Upload PDFs/XLSX/CSV/TXT per property; content injected into broker prompt

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
                          │   main.py    │       │  (state,     │
                          └──────┬───────┘       │   cache,     │
                                 │               │   memory)    │
                          ┌──────▼───────┐       └──────────────┘
                          │  Supervisor  │
                          │  (routing)   │       ┌──────────────┐
                          └──────┬───────┘       │  PostgreSQL  │
                     ┌───────────┼──────────┐    │  (msg logs)  │
                     ▼           ▼          ▼    └──────────────┘
               ┌──────────┐ ┌────────┐ ┌─────────┐
               │  Broker  │ │Booking │ │ Profile  │  + Default
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
  quick_replies → renderQuickReplies()
  ...7 more types
}
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **AI** | Claude Sonnet 4.6, Claude Haiku 4.5 | Agent reasoning (Sonnet for most, Haiku for broker) |
| **Backend** | FastAPI, Python 3.11+ | API server, SSE streaming, webhook handlers |
| **Cache/State** | Redis | Conversations, preferences, property cache, rate limits, analytics |
| **Database** | PostgreSQL | Message logging, property documents |
| **Frontend** | Vanilla JS, Vite | Chat UI, component registry, voice input |
| **Maps** | Leaflet, OSRM | Property maps, commute estimation |
| **Markdown** | Marked.js | Bot message rendering |
| **Voice** | Deepgram Nova-3 | Speech-to-text (en/hi/mr) |
| **Hosting** | Render (backend), Vercel (frontend) | Auto-deploy from git |
| **WhatsApp** | Meta Cloud API / Interakt | WhatsApp channel |

---

## Project Structure

```
claude-booking-bot/
├── main.py                  # App entry + all endpoints (~900 lines)
├── config.py                # Pydantic settings
├── requirements.txt         # Python dependencies
├── build.sh                 # Render build script
├── agents/                  # AI agent configs
│   ├── supervisor.py        # Intent routing → {agent, skills[]}
│   ├── broker_agent.py      # Property search/compare (dual-path: dynamic skills vs legacy)
│   ├── booking_agent.py     # Visits, payments, reservations
│   ├── profile_agent.py     # User preferences
│   └── default_agent.py     # Greetings, general help
├── core/                    # Engine
│   ├── claude.py            # Anthropic API wrapper (split prompt caching)
│   ├── prompts.py           # All system prompts (13 modular broker sections)
│   ├── ui_parts.py          # Generative UI part generation
│   ├── message_parser.py    # Response → structured parts
│   ├── conversation.py      # History management + compaction
│   ├── summarizer.py        # Hierarchical token-aware summarization
│   ├── rate_limiter.py      # Sliding-window rate limits
│   ├── router.py            # Keyword safety net (3-phase)
│   └── tool_executor.py     # Tool dispatch + graceful skill fallback
├── tools/                   # Tool implementations
│   ├── broker/              # search, compare, details, images, landmarks, shortlist
│   ├── booking/             # payment, schedule_visit, reserve, cancel, kyc
│   ├── profile/             # user details, events, shortlisted
│   ├── common/              # web_search
│   └── registry.py          # Tool registration for all agents (28 tools, strict schemas)
├── skills/                  # Dynamic skill system (broker agent only)
│   ├── loader.py            # Skill file loading + YAML frontmatter + hot-reload
│   ├── skill_map.py         # Skill→tool mapping + keyword fallback
│   └── broker/              # 12 .md skill files (_base, search, details, compare, …)
├── db/                      # Data layer
│   ├── redis_store.py       # All Redis operations
│   └── postgres.py          # PostgreSQL logging + property_documents table
├── channels/
│   └── whatsapp.py          # WhatsApp send (Meta/Interakt)
└── utils/                   # Helpers
    ├── scoring.py           # Property match scoring (weighted, fuzzy amenity)
    ├── geo.py               # Shared geocoding helper
    ├── date.py              # Date/time parsing
    ├── image.py             # Image processing (WEBP→JPEG for WhatsApp)
    └── retry.py             # Async retry decorator
```

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
| `REDIS_URL` | No | — | Redis connection URL (or use REDIS_HOST/PORT) |
| `REDIS_HOST` | No | `localhost` | Redis host (fallback) |
| `REDIS_PORT` | No | `6379` | Redis port (fallback) |
| `DATABASE_URL` | No | — | PostgreSQL URL (or use DB_HOST/NAME/USER/PASSWORD/PORT) |
| `RENTOK_API_BASE_URL` | No | `https://apiv2.rentok.com` | Rentok property API |
| `WHATSAPP_ACCESS_TOKEN` | No | — | Meta WhatsApp API token |
| `TAVILY_API_KEY` | No | — | Tavily web search API key |
| `OSRM_API_KEY` | No | — | OSRM routing API key (commute estimation) |
| `API_KEY` | No | — | API authentication (disabled if empty) |
| `HAIKU_MODEL` | No | `claude-haiku-4-5-20251001` | Broker agent model |
| `SONNET_MODEL` | No | `claude-sonnet-4-6` | Other agents model |
| `KYC_ENABLED` | No | `false` | Enable Aadhaar verification |
| `DYNAMIC_SKILLS_ENABLED` | No | `true` | Use dynamic skill system for broker (false = legacy monolithic prompt) |
| `WEB_SEARCH_MAX_PER_CONVERSATION` | No | `3` | Max web search calls per conversation |

---

## API Endpoints

### Chat

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
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
| `POST` | `/webhook/whatsapp` | WhatsApp incoming messages |
| `GET` | `/webhook/whatsapp` | WhatsApp webhook verification |
| `POST` | `/webhook/payment` | Payment callback from Rentok |

### Admin Portal

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/conversations` | Paginated conversation list with metadata |
| `GET` | `/admin/conversations/{uid}` | Full thread + memory + cost + human_mode |
| `POST` | `/admin/conversations/{uid}/takeover` | Activate human mode (AI bypassed) |
| `POST` | `/admin/conversations/{uid}/resume` | Deactivate human mode (AI resumes) |
| `POST` | `/admin/conversations/{uid}/message` | Send admin message via WhatsApp + save to history |
| `GET` | `/admin/command-center` | Today's KPIs (messages, leads, visits, active users) |
| `GET` | `/admin/leads` | Filterable lead list (stage, area, budget, days) |
| `GET` | `/admin/analytics` | Full analytics (metrics, skill usage, cost breakdown) |
| `GET` | `/admin/flags` | Current feature flag values |
| `POST` | `/admin/flags` | Toggle feature flags at runtime |
| `POST` | `/admin/broadcast` | WhatsApp blast to users active in last 7 days |
| `GET` | `/admin/properties` | List all properties from cache |
| `POST` | `/admin/properties/{prop_id}/documents` | Upload document (PDF/XLSX/CSV/TXT) |
| `GET` | `/admin/properties/{prop_id}/documents` | List documents for a property |
| `DELETE` | `/admin/properties/{prop_id}/documents/{doc_id}` | Delete a document |

---

## AI Agents

| Agent | Model | Responsibility |
|-------|-------|---------------|
| **Supervisor** | Sonnet | Classifies user intent → `{agent, skills[]}` |
| **Broker** | Haiku | Property search, details, images, comparison, landmarks, shortlisting |
| **Booking** | Sonnet | Visit scheduling, call scheduling, reservations, payments, KYC |
| **Profile** | Sonnet | User preferences, scheduled events, shortlisted properties |
| **Default** | Sonnet | Greetings, brand information, general help |

The Broker agent uses Haiku for cost efficiency (highest volume of requests). All other agents use Sonnet for higher reasoning quality.

---

## Dynamic Skill System

The broker agent uses a hot-reloadable skill file architecture. Skills are `.md` files with YAML frontmatter — editable by non-developers without code changes.

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

**Metrics:** Skill usage tracked in Redis (`skill_usage:{day}` HINCRBY per skill). Exposed in `/admin/analytics`.

---

## Generative UI Components

The backend generates structured `parts[]` that the frontend renders via a component registry. Nine part types are supported:

| Part Type | Description |
|-----------|-------------|
| `text` | Markdown-formatted text with inline price highlighting |
| `property_carousel` | Horizontal scrolling property cards with images, scores, amenity pills |
| `comparison_table` | Side-by-side property comparison with winner badge |
| `quick_replies` | Contextual suggestion chips (backend-controlled) |
| `action_buttons` | Primary/secondary CTA buttons |
| `status_card` | Success/info/warning cards for confirmations (with celebration animations) |
| `image_gallery` | Grid thumbnails with fullscreen lightbox |
| `confirmation_card` | Pre-action confirmation with confirm/cancel |
| `error_card` | Friendly error display with retry button |

---

## Human Mode

Admin operators can take over any conversation from the admin portal. When human mode is active:

- **SSE endpoint (`/chat/stream`)**: Returns an empty `done` event with `agent="human"`. User message is saved to Redis history. No AI response generated.
- **JSON endpoint (`/chat`)**: Returns `ChatResponse(response="", agent="human")`. Same history-saving behavior.
- **WhatsApp webhook**: Saves inbound message to history, returns early without calling any send functions (no empty message sent to user).
- **Admin portal**: Amber banner displayed in thread panel. Input bar appears for admin to type and send messages. "Resume AI" button re-enables AI responses.

Toggle via: `POST /admin/conversations/{uid}/takeover` and `POST /admin/conversations/{uid}/resume`

---

## Redis Key Schema

| Key Pattern | Type | Description |
|------------|------|-------------|
| `{uid}:conversation` | List | Message history (JSON per entry) |
| `{uid}:preferences` | Hash | User budget, area, amenity preferences |
| `{uid}:user_memory` | Hash | Cross-session memory (shortlisted, events, notes) |
| `{uid}:human_mode` | Hash | `{active, taken_at}` — human takeover state |
| `{uid}:last_agent` | String | Last agent used (routing stickiness, 1h TTL) |
| `{uid}:last_search` | JSON | Top-10 results from last search (24h TTL) |
| `{uid}:session_cost` | Hash | `{tokens_in, tokens_out, cost_usd}` (7-day TTL) |
| `{uid}:user_language` | String | Detected language (en/hi/mr) |
| `{uid}:lead_score` | String | Lead qualification score 0-100 |
| `active_users` | Sorted Set | member=uid, score=unix_ts (for command-center) |
| `prop_cache:{pg_id}` | JSON | Property data cache (1h TTL) |
| `web_intel:{category}:{hash}` | JSON | Web search results cache |
| `metrics:{day}:*` | Hash | Per-agent daily metrics (tool_calls, tokens, errors) |
| `skill_usage:{day}` | Hash | Per-skill invocation counts (90-day TTL) |
| `skill_misses:{day}` | Hash | Per-tool skill-miss counts (90-day TTL) |
| `rate:{uid}:minute` | Sorted Set | Sliding-window rate limit (per-user, per-minute) |
| `rate:{uid}:hour` | Sorted Set | Sliding-window rate limit (per-user, per-hour) |

---

## Deployment

### Backend (Render)

The backend auto-deploys to Render on push to `main`:

- **Build command**: `bash build.sh` (installs Python dependencies)
- **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Services**: Managed Redis + PostgreSQL on Render
- **Live URL**: `https://claude-booking-bot.onrender.com`

---

## Rate Limits

| Limit | Value |
|-------|-------|
| Per-user per-minute | 6 messages |
| Per-user per-hour | 30 messages |
| Global per-minute | 100 messages |
| Web search per-conversation | 3 calls |

---

## License

MIT
