# OxOtel AI Booking Bot

> AI-powered PG (Paying Guest) booking assistant with multi-agent architecture, Generative UI, and dual-channel support (Web + WhatsApp).

![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Claude](https://img.shields.io/badge/Claude_AI-191919?style=flat&logo=anthropic&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=flat&logo=redis&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-646CFF?style=flat&logo=vite&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-000?style=flat&logo=vercel&logoColor=white)
![Render](https://img.shields.io/badge/Render-46E3B7?style=flat&logo=render&logoColor=white)

---

## What It Does

A full-stack conversational AI assistant that helps users find, compare, and book PG accommodations across Indian cities. Five specialized AI agents handle different aspects of the booking journey — from property search and comparison to visit scheduling and payment — powered by Claude Sonnet and Haiku models. The backend decides what UI to render (Generative UI pattern), and the frontend is a lightweight component registry that renders structured parts.

## Key Features

- **Multi-Agent AI** — Supervisor routes to 5 specialized agents: Broker, Booking, Profile, Default, Room
- **Property Search & Comparison** — Geocoded search, match scoring, side-by-side comparison tables
- **Visit Scheduling & Payments** — Schedule visits, reserve beds, create payment links
- **Generative UI** — Backend-controlled rich components (carousels, status cards, galleries, confirmation cards)
- **Dual Channel** — Web chat (SSE streaming) + WhatsApp (Meta/Interakt APIs)
- **Multilingual** — English, Hindi, Marathi with locale-aware UI
- **Voice Input** — Deepgram Nova-3 speech-to-text in all 3 languages
- **Smart Memory** — Cross-session user preferences, implicit feedback, conversation summarization
- **Web Intelligence** — Live web search for area insights and market data
- **Property Maps** — Leaflet maps with property pins, commute estimation via OSRM
- **Lead Scoring** — Automated lead qualification based on engagement signals
- **Celebration Animations** — Confetti, heart pulse, checkmark draw on key actions

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
                     ┌───────────┼───────────┐   │  (msg logs)  │
                     ▼           ▼           ▼   └──────────────┘
               ┌──────────┐ ┌────────┐ ┌─────────┐
               │  Broker  │ │Booking │ │ Profile  │  + Default, Room
               │ (Haiku)  │ │(Sonnet)│ │ (Sonnet) │
               └────┬─────┘ └───┬────┘ └────┬────┘
                    │            │            │
               ┌────▼────────────▼────────────▼────┐
               │           Tool Layer              │
               │  search, compare, schedule_visit, │
               │  payment, shortlist, web_search,  │
               │  landmarks, images, preferences   │
               └───────────────┬───────────────────┘
                               │
                        ┌──────▼───────┐
                        │  Rentok API  │
                        │ (properties) │
                        └──────────────┘
```

**Frontend: Component Registry Pattern**

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
| **Cache/State** | Redis | Conversations, preferences, property cache, rate limits |
| **Database** | PostgreSQL | Message logging, analytics |
| **Frontend** | Vanilla JS, Vite | Chat UI, component registry, voice input |
| **Maps** | Leaflet, OSRM | Property maps, commute estimation |
| **Markdown** | Marked.js | Bot message rendering |
| **Voice** | Deepgram Nova-3 | Speech-to-text (en/hi/mr) |
| **Hosting** | Render (backend), Vercel (frontend) | Auto-deploy from git |
| **WhatsApp** | Meta Cloud API / Interakt | WhatsApp channel |

---

## Project Structure

```
.
├── claude-booking-bot/          # Backend (FastAPI)
│   ├── main.py                  # App entry + all endpoints
│   ├── config.py                # Pydantic settings
│   ├── requirements.txt         # Python dependencies
│   ├── build.sh                 # Render build script
│   ├── agents/                  # AI agent configs
│   │   ├── supervisor.py        # Intent routing
│   │   ├── broker_agent.py      # Property search/compare
│   │   ├── booking_agent.py     # Visits, payments, reservations
│   │   ├── profile_agent.py     # User preferences
│   │   ├── default_agent.py     # Greetings, general help
│   │   └── room_agent.py        # Room-level details
│   ├── core/                    # Engine
│   │   ├── claude.py            # Anthropic API wrapper
│   │   ├── prompts.py           # All system prompts
│   │   ├── ui_parts.py          # Generative UI part generation
│   │   ├── message_parser.py    # Response → structured parts
│   │   ├── conversation.py      # History management
│   │   ├── summarizer.py        # Token-aware summarization
│   │   ├── rate_limiter.py      # Sliding-window rate limits
│   │   ├── router.py            # Keyword safety net
│   │   └── tool_executor.py     # Tool dispatch + error recovery
│   ├── tools/                   # Tool implementations
│   │   ├── broker/              # search, compare, details, images, landmarks, shortlist
│   │   ├── booking/             # payment, schedule_visit, reserve, cancel, kyc
│   │   ├── profile/             # user details, events, shortlisted
│   │   ├── common/              # web_search
│   │   └── registry.py          # Tool registration for all agents
│   ├── db/                      # Data layer
│   │   ├── redis_store.py       # All Redis operations
│   │   └── postgres.py          # PostgreSQL logging
│   ├── channels/
│   │   └── whatsapp.py          # WhatsApp send (Meta/Interakt)
│   └── utils/                   # Helpers
│       ├── scoring.py           # Property match scoring
│       ├── date.py              # Date/time parsing
│       ├── image.py             # Image processing
│       └── retry.py             # Async retry decorator
│
├── eazypg-chat/                 # Frontend (Vite SPA)
│   ├── index.html               # Chat interface
│   ├── dashboard.html           # Analytics dashboard
│   ├── package.json             # Dependencies
│   ├── vite.config.js           # Build config
│   ├── vercel.json              # Vercel deployment config
│   ├── src/
│   │   ├── main.js              # Entry point
│   │   ├── stream.js            # SSE streaming handler
│   │   ├── message-builder.js   # DOM message construction
│   │   ├── streaming-ui.js      # Skeleton loaders + typing animation
│   │   ├── i18n.js              # Multilingual (en/hi/mr)
│   │   ├── voice-input.js       # Deepgram voice input
│   │   ├── lightbox.js          # Fullscreen image viewer
│   │   ├── renderers/
│   │   │   ├── server-parts.js  # Component registry (9 types)
│   │   │   ├── property-card.js # Property card with scores
│   │   │   ├── compare-card.js  # Comparison tables
│   │   │   └── rich-message.js  # Fallback markdown renderer
│   │   └── components/
│   │       └── PropertyMap.js   # Leaflet map component
│   ├── styles/                  # CSS
│   │   ├── base.css             # Design tokens, layout
│   │   ├── carousel.css         # Property carousel
│   │   ├── components.css       # Chips, buttons, typing
│   │   ├── status-card.css      # Status card variants
│   │   ├── gallery.css          # Image gallery
│   │   └── animations.css       # Skeletons, celebrations, transitions
│   └── api/                     # Vercel serverless proxies
│       ├── stream.js            # SSE proxy → /chat/stream
│       ├── chat.js              # POST proxy → /chat
│       └── feedback.js          # POST proxy → /feedback
│
└── README.md                    # This file
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
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

### Frontend Setup

```bash
cd eazypg-chat

# Install dependencies
npm install

# Run dev server (proxies API to backend)
npm run dev
```

The frontend dev server starts at `http://localhost:5173` and proxies API requests to the backend.

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
| `API_KEY` | No | — | API authentication (disabled if empty) |
| `HAIKU_MODEL` | No | `claude-haiku-4-5-20251001` | Broker agent model |
| `SONNET_MODEL` | No | `claude-sonnet-4-6` | Other agents model |
| `KYC_ENABLED` | No | `false` | Enable Aadhaar verification |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/chat` | Synchronous chat (JSON response) |
| `POST` | `/chat/stream` | SSE streaming chat (primary web endpoint) |
| `POST` | `/webhook/whatsapp` | WhatsApp incoming messages |
| `GET` | `/webhook/whatsapp` | WhatsApp webhook verification |
| `POST` | `/webhook/payment` | Payment callback from Rentok |
| `POST` | `/knowledge-base` | Upload PDFs to FAISS vector store |
| `POST` | `/query` | Query knowledge base |
| `POST` | `/feedback` | Submit user feedback (thumbs up/down) |
| `GET` | `/feedback/stats` | Feedback statistics |
| `GET` | `/funnel` | Conversion funnel data |
| `GET` | `/rate-limit/status` | Rate limit status for a user |
| `POST` | `/language` | Set user language preference |
| `GET` | `/admin/analytics` | Analytics dashboard data |
| `POST` | `/cron/follow-ups` | Trigger scheduled follow-up messages |

---

## AI Agents

| Agent | Model | Responsibility |
|-------|-------|---------------|
| **Supervisor** | Sonnet | Classifies user intent and routes to the correct agent |
| **Broker** | Haiku | Property search, details, images, comparison, landmarks, shortlisting |
| **Booking** | Sonnet | Visit scheduling, call scheduling, reservations, payments, KYC |
| **Profile** | Sonnet | User preferences, scheduled events, shortlisted properties |
| **Default** | Sonnet | Greetings, brand information, general help |
| **Room** | Sonnet | Room-level and bed-level details |

The Broker agent uses Haiku for cost efficiency (it handles the highest volume of requests). All other agents use Sonnet for higher reasoning quality.

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

## Deployment

### Backend (Render)

The backend auto-deploys to Render on push to `main`:

- **Build command**: `bash build.sh` (installs Python dependencies)
- **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Services**: Managed Redis + PostgreSQL on Render

### Frontend (Vercel)

The frontend auto-deploys to Vercel:

- **Build command**: `npm run build`
- **Output directory**: `dist/`
- **Serverless functions**: `api/` directory proxies requests to the backend with custom timeouts (120s for streaming, 10-30s for others)

---

## License

MIT
