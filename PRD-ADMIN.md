# EazyPG Admin Control Panel — Product Requirements Document

**Version:** 1.0
**Date:** March 2026
**Author:** Product & Engineering
**Status:** Production — Documenting Existing System

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [The Admin Experience — Design Principles](#2-the-admin-experience--design-principles)
3. [Users & Roles](#3-users--roles)
4. [Authentication & Brand Isolation](#4-authentication--brand-isolation)
5. [Page 1 — Conversations](#5-page-1--conversations)
6. [Page 2 — Leads](#6-page-2--leads)
7. [Page 3 — Analytics](#7-page-3--analytics)
8. [Page 4 — Properties](#8-page-4--properties)
9. [Page 5 — Documents](#9-page-5--documents)
10. [Page 6 — Settings](#10-page-6--settings)
11. [System Architecture](#11-system-architecture)
12. [Human Takeover System — Deep Dive](#12-human-takeover-system--deep-dive)
13. [API Proxy Architecture](#13-api-proxy-architecture)
14. [Frontend Architecture](#14-frontend-architecture)
15. [Thread Renderer](#15-thread-renderer)
16. [Technology Stack](#16-technology-stack)
17. [Data Flow & Backend Endpoints](#17-data-flow--backend-endpoints)
18. [Success Metrics](#18-success-metrics)
19. [Known Limitations & Future Work](#19-known-limitations--future-work)

---

## 1. Executive Summary

The EazyPG Admin Control Panel is the brand operator dashboard for managing AI chatbot conversations, leads, analytics, properties, and configuration. It is the operational nerve center for PG operators who use EazyPG's AI booking bot across WhatsApp and web channels.

**What it does:** Gives brand operators — PG owners, co-living managers, support staff — a single interface to monitor every conversation their AI chatbot is having, intervene when needed (human takeover), track lead quality and funnel progression, manage property knowledge bases, and control runtime behavior through feature flags.

**What makes it different from a generic admin panel:**

1. **Human takeover is a first-class feature, not an afterthought.** The amber "Take Over" button sits in the conversation header, not buried three menus deep. Because in Indian PG rentals, the moment a tenant is ready to book, a human needs to step in. The admin panel is designed around that moment.

2. **Multi-brand isolation is invisible but absolute.** Three brands — OxOtel, Stanza, Zelter — share the same backend infrastructure. But when an OxOtel operator logs in, they see only OxOtel conversations, OxOtel leads, OxOtel analytics. They never know other brands exist. This is achieved through a single mechanism: every API call includes `X-API-Key`, which the backend hashes to a `brand_hash` that scopes all queries.

3. **The lead profile is AI-native.** Unlike CRM tools that show fields a human filled in, the Leads page shows what the AI learned: deal-breakers extracted from conversation, must-have amenities inferred from questions, persona classification (professional/student/family), and a composite lead score computed from engagement signals. The admin sees the AI's understanding of each lead, not a form.

4. **Document upload creates AI knowledge, not file storage.** When an operator uploads a vacancy sheet or marketing PDF to a property, the content is extracted, stored in PostgreSQL, and injected into the broker agent's system prompt. The AI can then answer questions about current availability, pricing specials, or amenity details that aren't in the Rentok API. This is knowledge base management, not Dropbox.

**Technology:** React + TypeScript + Vite on Vercel, with Tailwind CSS and shadcn/ui components. Vercel Edge API proxies forward all requests to the shared FastAPI backend on Render. The frontend has zero direct backend access — every request passes through a proxy that forwards the `X-API-Key` header.

**Pages:** Conversations (default), Leads, Lead Profile, Analytics, Properties, Documents, Settings.

---

## 2. The Admin Experience — Design Principles

### Principle 1: Conversations First, Everything Else Second

The root URL (`/`) is the Conversations page. Not a dashboard. Not an overview. The first thing an operator sees is the list of people talking to their bot right now.

This is an opinionated choice. Most admin panels default to a dashboard with charts and KPIs. But PG operators don't open the admin panel to admire graphs — they open it because something needs attention. Either a high-value lead is asking about availability, or a frustrated tenant sent a complaint, or the AI gave a wrong answer. The Conversations page puts them one click from every conversation.

### Principle 2: Real-Time Enough, Not Real-Time

The panel uses polling, not WebSocket. Conversations refresh every 30 seconds. The command center (analytics) refreshes on page load.

This sounds like a limitation, but it is a deliberate trade-off. WebSocket infrastructure adds deployment complexity (sticky sessions, connection management, reconnection logic) for a product where 30-second staleness is acceptable. The operator is not a stock trader — they are a PG manager who checks the panel a few times a day. If they need faster updates, they hit the browser refresh button.

The `staleTime: 15_000` and `refetchInterval: 30_000` in React Query give a good balance: data feels fresh, but the backend is not hammered with requests.

### Principle 3: Human Takeover as a Workflow, Not a Toggle

Taking over a conversation is not just flipping a boolean. It is a workflow with clear states:

```
AI Active  ──[Take Over]──>  Human Mode  ──[Send Message]──>  Message Sent via WhatsApp
                                          ──[Resume AI]────>  AI Active
```

The UI reflects this: the amber "Take Over" button transforms into a green "Resume AI" button. A banner appears ("You're handling this conversation -- AI is paused"). An input bar materializes at the bottom. The operator types a message, hits Enter, and it is sent to the user via WhatsApp. When done, they click "Resume AI" and the bot picks up where it left off.

This is not a settings toggle. It is the most important feature in the product.

### Principle 4: Brand Isolation is Invisible

An OxOtel operator never sees a "brand" dropdown. They never select a workspace. They never filter by brand. They log in with their API key, and everything they see is already scoped to their brand.

This is the correct UX for multi-tenant systems where each tenant should feel like they own the entire product. The complexity of brand isolation lives entirely in the backend (`require_admin_brand_key` -> `brand_hash` -> scoped queries). The frontend simply sends `X-API-Key` on every request and trusts that the backend returns the right data.

### Principle 5: Density Over Decoration

The UI is dense. The conversation list shows name, last message, timestamp, lead score, session cost, and human mode status — all in a 72px row. The leads table has 8 columns. The analytics page has 6 KPI cards, a funnel, a skill usage table, and an agent cost table, all above the fold.

This is for operators who manage 50+ conversations a day. They need to scan, not scroll. Every pixel carries information.

### Principle 6: Mobile-Ready, Desktop-First

The layout adapts to mobile with a bottom tab bar (replacing the sidebar) and slide-in panels (conversations, document panels). But the primary use case is a desktop browser. The two-pane conversation layout, the 8-column leads table, the side-by-side property documents panel — these are designed for 1440px+ screens.

Mobile is the "check something on the go" mode. Desktop is the "manage the operation" mode.

---

## 3. Users & Roles

### Brand Operator (Primary User)

The PG owner or co-living manager who contracted EazyPG. They use the admin panel to:

- Monitor what the AI is telling their customers
- Take over conversations when a lead is ready to book
- Track how many leads the bot is generating
- Upload property documents (vacancy sheets, marketing materials)
- Toggle feature flags (enable/disable KYC, payment)
- Send broadcast messages to recent users

**Frequency:** Daily. Usually checks 2-5 times per day, spending 5-15 minutes per session.

### Support Agent

A staff member who monitors conversations and intervenes on behalf of the operator. Same capabilities as the operator — there is no role distinction.

**Frequency:** Continuous during business hours (9 AM - 9 PM IST).

### No Role System

Currently, there is a single API key per brand. Anyone with the key has full admin access. There is no distinction between "viewer" and "editor," no audit log of who did what, and no way to revoke access for a specific person without rotating the entire key.

This is a known limitation (Section 19), but it is acceptable for the current scale: each brand has 1-3 people who use the admin panel, and they all need full access.

---

## 4. Authentication & Brand Isolation

### Login Flow

```
┌──────────────────────────────────────────────────────────┐
│                    Login Screen                          │
│                                                          │
│   ┌──────────────────────────────────────────────────┐  │
│   │  EazyPG Admin                                    │  │
│   │                                                  │  │
│   │  Sign in                                         │  │
│   │  Enter your API key to access the admin portal.  │  │
│   │                                                  │  │
│   │  API Key                                         │  │
│   │  ┌────────────────────────── [eye icon]─────┐   │  │
│   │  │  ●●●●●●●●●●●●●●●                        │   │  │
│   │  └──────────────────────────────────────────┘   │  │
│   │                                                  │  │
│   │  ┌──────────────────────────────────────────┐   │  │
│   │  │            Continue                      │   │  │
│   │  └──────────────────────────────────────────┘   │  │
│   └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

1. Operator enters API key (e.g., `OxOtel1234`)
2. Key is stored in `localStorage` as `admin_api_key`
3. Frontend makes a validation request: `GET /api/conversations?limit=1`
4. If the backend returns 401, the key is invalid — cleared from localStorage, error shown
5. If 200, the operator is authenticated — the AppShell renders

### API Key Flow (Every Request)

```
Browser                    Vercel Edge Proxy              Render Backend
  │                            │                              │
  │  GET /api/conversations    │                              │
  │  X-API-Key: OxOtel1234    │                              │
  │ ─────────────────────────> │                              │
  │                            │  GET /admin/conversations    │
  │                            │  X-API-Key: OxOtel1234      │
  │                            │ ───────────────────────────> │
  │                            │                              │
  │                            │    require_admin_brand_key() │
  │                            │    brand_hash = sha256(key)  │
  │                            │             [:16]            │
  │                            │    Query scoped by           │
  │                            │       brand_hash             │
  │                            │                              │
  │                            │  <─────── {conversations}    │
  │  <─────────────────────────│                              │
```

### Brand Isolation Guarantee

The `require_admin_brand_key` function in `core/auth.py` does three things:

1. Computes `brand_hash = sha256(api_key)[:16]`
2. Verifies that a brand config exists in Redis for this hash
3. Returns the `brand_hash` to the route handler

Every admin endpoint receives this `brand_hash` and uses it to scope all queries:

- **Conversations:** Only users tagged with `{uid}:brand_hash == brand_hash` are returned
- **Leads:** PostgreSQL `WHERE brand_hash = :brand_hash`
- **Analytics:** Read from brand-scoped Redis keys (`funnel:{brand_hash}:{day}`)
- **Properties:** Only property IDs from the brand's `pg_ids` config
- **Feature flags:** Merged from global defaults + `brand_flags:{brand_hash}`
- **Human mode:** Scoped to `{uid}:{brand_hash}:human_mode`

The raw API key is **never stored** anywhere. Only the hash exists in Redis and PostgreSQL.

---

## 5. Page 1 — Conversations

**Route:** `/` (default)
**Component:** `ConversationsPage.tsx`

The Conversations page is a two-pane layout: conversation list on the left (360px), conversation thread on the right (fills remaining width).

### Left Pane: Conversation List

```
┌─────────────────────────────────────────────────┐
│  42 conversations          [●  3 taken over]    │
│  ┌─────────────────────────────────────────┐    │
│  │ 🔍 Search by name or phone...           │    │
│  └─────────────────────────────────────────┘    │
│                                                  │
│  ┌──┐  Arjun Sharma                    2m       │
│  │AS│  Looking for PGs in Andheri...             │
│  └──┘  ● AI Active   72   $0.0312               │
│  ─────────────────────────────────────────────   │
│  ┌──┐  Priya Patel                     15m      │
│  │PP│  Can I schedule a visit?                   │
│  └──┘  ● Human                                  │
│  ─────────────────────────────────────────────   │
│  ┌──┐  Rahul M                         1h       │
│  │RM│  Thanks, I'll think about it               │
│  └──┘  ● AI Active   45                         │
│  ─────────────────────────────────────────────   │
│                                                  │
│              [Load more]                         │
└─────────────────────────────────────────────────┘
```

Each conversation row shows:

| Element | Source | Visual |
|---------|--------|--------|
| Avatar circle | First+last initials from name, or last 2 digits of phone | Color-coded by lead score: emerald (70+), blue (35-69), slate (<35) |
| Display name | `name` or `phone` or first 12 chars of `uid` | Bold, truncated |
| Timestamp | `last_seen` (unix) | Relative: "2m", "1h", "3d" |
| Last message | `last_message` | Single line, truncated, slate-500 |
| Status dot | `human_mode` + `message_count` | Amber "Human" / Green "AI Active" / Gray "Idle" |
| Lead score | `lead_score` | Pill badge, only shown if > 0 |
| Session cost | `cost_usd` | Green pill, format `$0.0312`, only if > 0.0001 |

**Filtering:**
- Search by name, phone, or uid (client-side filter on loaded data)
- "Taken over" amber chip: toggles human-mode-only filter. Shows count of conversations currently in human mode.

**Pagination:** Initial load is 50 conversations. "Load more" button loads 50 more. Server-side `limit`/`offset` via query params.

**Polling:** `refetchInterval: 30_000` (30 seconds). `staleTime: 15_000` (15 seconds). React Query handles deduplication and background refetch.

### Right Pane: Thread Panel

When a conversation is selected, the right pane shows the full thread. See [Section 15: Thread Renderer](#15-thread-renderer) for message rendering details.

The thread header contains:

- **Avatar** with lead-score-colored background
- **Name** (bold) + **agent badge** (e.g., "Broker") + **session cost** ($0.0312 in green pill)
- **Phone number** (if available)
- **Lead score bar** (visual progress bar, 0-100)
- **Context button** — expands a panel showing user memory: budget, area preference, shortlisted properties, move-in date
- **Take Over / Resume AI button** — the human takeover workflow (Section 12)

Below the header: an amber banner when human mode is active ("You're handling this conversation -- AI is paused"), then the scrollable message thread, then the input bar (only visible in human mode).

### Mobile Layout

On screens < 768px:
- The list takes full width
- Selecting a conversation slides the thread in from the right (CSS `animate-slide-in-right`)
- A back arrow in the thread header returns to the list
- The two-pane layout is replaced by a single-pane with navigation

---

## 6. Page 2 — Leads

**Route:** `/leads`
**Component:** `LeadsPage.tsx`

The Leads page is a filterable, paginated table of all users who have interacted with the chatbot. Unlike a traditional CRM, every field in this table was computed by the AI, not entered by a human.

### Table Columns

| Column | Source | Display |
|--------|--------|---------|
| Name | `name` from user memory | Bold text + persona pill (Pro/Student/Family) |
| Phone | `phone` from user memory or WhatsApp user_id | Tabular numbers |
| Stage | `funnel_max` from Redis | Color-coded pill: New (slate), Searching (sky), Researching (blue), Shortlisted (violet), Visit Sched. (amber), Booked (green) |
| Area | `location_pref` or `area` from user memory | Plain text |
| Budget | `budget_min`/`budget_max` from preferences | Formatted: "INR 8k-12k" or "up to INR 10k" |
| Activity | `viewed_count`, `shortlisted_count`, `visits_count` | Three icon chips: eye (viewed), star (shortlisted), calendar (visits) |
| Score | `lead_score` (0-100) | Visual bar + numeric value + temperature chip (Hot/Warm/Cold) |
| Last seen | `last_seen` timestamp | Relative: "2m", "1h", "3d" |

**Hot lead highlighting:** Rows with `lead_score >= 70` get an orange left border, making them visually pop.

### Filters

- **Search:** Free-text, matches name or phone
- **Stage:** Dropdown with all stage values
- **Area:** Free-text filter

Filters reset pagination offset to 0 when changed.

### Pagination

25 rows per page. Previous/next chevron buttons. "Showing 1-25 of 142" counter.

### Lead Profile (Sub-route)

Clicking any lead row navigates to `/leads/{uid}`, which renders `LeadProfilePage.tsx` — a dedicated profile view with two tabs:

**Chat Tab:** The full conversation thread (reuses `ThreadPanel` component), with take-over/resume functionality.

**Profile Tab:** A card grid showing:
- **Identity Card:** Phone, area preference, persona badge, first/last seen dates
- **Engagement Card:** Sessions count, properties viewed, shortlisted count, visits booked, AI cost (in INR, 1 USD = 95 INR)
- **Preferences Card:** Property type, budget, amenities (blue pills), sharing types (slate pills)
- **Intent Signals Card:** Must-haves (green pills) and deal-breakers (red pills) — extracted by the AI from conversation context

This is the AI-native CRM view. Every data point was inferred by the broker agent during conversation, stored in user memory (`{uid}:user_memory`), and surfaced here without any manual data entry.

---

## 7. Page 3 — Analytics

**Route:** `/analytics`
**Component:** `AnalyticsPage.tsx`

The Analytics page is powered by the `/admin/command-center` endpoint, which returns today's KPIs and breakdowns, all scoped to the requesting brand.

### KPI Cards (6-card grid)

| Card | Value Source | Icon | Color |
|------|-------------|------|-------|
| Messages Today | `messages_today` | MessageSquare | Blue |
| New Leads | `new_leads_today` | Users | Emerald |
| Active Users | `active_users` | Activity | Purple |
| Human Mode | `human_mode_count` | UserCheck | Amber |
| Site Visits | `visits_today` | TrendingUp | Rose |
| Total Cost Today | `cost_usd_today` | DollarSign | Slate |

Each card shows: icon (colored background), label (small caps), value (large number), and optional subtitle (e.g., "Unique users last 5 min" for Active Users).

### Conversion Funnel

A horizontal bar showing funnel stage counts for today: search, detail, shortlist, visit, booking. Each stage shows its count with a capitalized label.

### Skill Usage Table

Shows which dynamic broker skills were invoked today, sorted by count descending. Each row has a proportional bar (relative to the most-used skill). Skills include: search, qualify_new, details, selling, compare, commute, shortlist, etc.

This is valuable for understanding what users are asking about. If "selling" (objection handling) is high, users are pushing back on price. If "compare" is trending, users are evaluating options.

### Agent Cost Table

Breaks down today's API cost by agent (broker, booking, profile, default). Each row shows tokens in, tokens out, and USD cost. The broker agent (on Haiku) typically dominates volume but not cost; booking agent (on Sonnet) costs more per call.

---

## 8. Page 4 — Properties

**Route:** `/properties`
**Component:** `PropertiesPage.tsx`

The Properties page shows the brand's property portfolio — the properties their chatbot can search and recommend. The list comes from the brand's `pg_ids` configuration.

### Property Table

| Column | Source | Notes |
|--------|--------|-------|
| Property | `name` from Rentok API | Bold |
| Area | `area` or `location` | Plain text |
| Enquiries (7d) | `enquiries_7d` | Rolling 7-day count |
| Documents | `doc_count` | Number of uploaded KB docs |
| Chevron | — | Indicates expandability |

Clicking a property row opens a side panel (desktop) or bottom sheet (mobile) showing that property's documents with upload/delete capabilities. This is the same document management as the dedicated Documents page, but contextual to a single property.

### Document Side Panel

The panel shows:
- Property name in the header
- List of uploaded documents (filename, size, upload date)
- Delete button per document (with confirmation spinner)
- Upload button with file picker (accepts PDF, XLSX, CSV, TXT)

On mobile, the panel slides up as a bottom sheet with a drag handle, covering 80% of viewport height. A backdrop overlay dismisses it.

---

## 9. Page 5 — Documents

**Route:** `/documents`
**Component:** `DocumentsPage.tsx`

The Documents page provides a property-centric view of all knowledge base documents. Unlike the Properties page where documents are a side panel, here documents are the primary focus.

### How Documents Become AI Knowledge

```
Operator uploads PDF    PostgreSQL stores content    Broker agent prompt
  to property X     ─>   property_documents table ─>  includes text from
                          (id, property_id,            format_property_docs()
                           filename, content_text,     up to 8000 chars
                           size_bytes, uploaded_at)
```

When a user asks the chatbot about property X, the broker agent's system prompt includes the extracted text content of all documents uploaded for that property. This means the AI can answer questions like "What's the current vacancy?" or "Do you have any move-in offers?" based on the uploaded documents, not just the Rentok API data.

### Page Layout

Each property is an expandable accordion. Collapsed, it shows the property name, area, and document count. Expanded, it shows:

1. **Document list:** Each document as a row with filename, size, date, and a delete button (appears on hover)
2. **Upload zone:** Drag-and-drop area or click-to-upload. Accepts PDF, XLSX, CSV, TXT. Max 10 MB each. Shows upload progress spinner.

### Manual Entry

Below the property list, a "Upload to a specific property" section allows entering a property ID manually. This is useful when the property hasn't been searched by any user yet (and therefore isn't in the cached property list).

### Accepted File Types

| Type | Extension | Use Case |
|------|-----------|----------|
| PDF | .pdf | Brochures, vacancy sheets, pricing documents |
| Excel | .xlsx | Room availability matrices, pricing tables |
| CSV | .csv | Bulk amenity data, contact lists |
| Text | .txt | General notes, FAQ answers, special instructions |

---

## 10. Page 6 — Settings

**Route:** `/settings`
**Component:** `SettingsPage.tsx`

The Settings page has four sections: Brand Configuration, Feature Flags, Model Info, and Broadcast.

### Brand Configuration

Four sub-panels for configuring the brand's chatbot:

**Chatbot Link:** A read-only URL that operators share with users. Format: `https://eazypg-chat.vercel.app?brand={uuid}`. Copy button and "Open in new tab" button. This link is permanent and auto-generated when brand config is saved.

**PG Property IDs:** A chip list of Rentok property IDs that the chatbot searches. Add by typing + Enter, remove by clicking the X on each chip. "Save PG IDs" button persists to backend.

**Brand Identity:** Brand name, operating cities, and areas. These are injected into the AI's system prompt so it knows what brand it represents and what geography it covers.

**WhatsApp Credentials:** Phone Number ID, Access Token (password field, write-only — displays `••••xxxx` on load), WABA ID, and an "Is Meta" toggle (Meta Graph API vs. Interakt). Amber-bordered panel to signal sensitivity. "Save WhatsApp Config" button. The access token is write-only: updating with the masked value preserves the existing stored token.

### Feature Flags

Three toggleable flags, plus one read-only flag:

| Flag | Label | Description | Default |
|------|-------|-------------|---------|
| `DYNAMIC_SKILLS_ENABLED` | Dynamic Skills | Modular broker prompt assembly per turn. Disable for monolithic fallback. | `true` |
| `KYC_ENABLED` | KYC (Aadhaar) | Aadhaar OTP verification flow for booking. | `false` |
| `PAYMENT_REQUIRED` | Payment Required | Require token payment before bed reservation. Disable for direct booking. | `false` |
| `WEB_SEARCH_ENABLED` | Web Search | Controlled by server environment (TAVILY_API_KEY). | Read-only badge |

Each flag shows a toggle switch. Changes are scoped to the brand only (stored in `brand_flags:{brand_hash}` in Redis). The effective value is the merge of global defaults from `config.py` and per-brand overrides.

**Runtime limitation (documented in UI description):** Toggling KYC_ENABLED or PAYMENT_REQUIRED changes prompts immediately, but tool availability changes only on server restart. This is because the tool registry is built at import time.

### Model Info

A read-only table showing which Claude model each agent uses:

| Agent | Model | Note |
|-------|-------|------|
| Broker | `claude-haiku-4-5-20251001` | Cost-optimised |
| Booking | `claude-sonnet-4-6` | Full capability |
| Profile | `claude-sonnet-4-6` | Full capability |
| Default | `claude-sonnet-4-6` | Full capability |

### Broadcast

A textarea for composing a WhatsApp message, sent to all users active in the last 7 days for this brand. "Send Broadcast" button with spinner. Result displays as "Sent to N users" or error message.

This is a blunt instrument — no targeting, no scheduling, no templates. It sends the raw text via WhatsApp to every recent user. Useful for announcements like "We have new properties in Andheri!" or "Diwali special: first month free!"

---

## 11. System Architecture

```
┌─────────────────┐    ┌──────────────────────────┐    ┌───────────────────────────┐
│   Browser        │    │   Vercel Edge Proxies     │    │   Render (FastAPI)        │
│   (React SPA)    │    │   (12 proxy files)        │    │                           │
│                  │    │                            │    │   routers/admin.py        │
│  ┌────────────┐  │    │  api/conversations.js ──────>  │   GET /admin/conversations│
│  │  AppShell  │  │    │  api/conversation.js  ──────>  │   GET /admin/conv/{uid}   │
│  │  Sidebar   │  │    │  api/takeover.js      ──────>  │   POST ../takeover        │
│  │  <Outlet>  │──┼──> │  api/resume.js        ──────>  │   POST ../resume          │
│  └────────────┘  │    │  api/send-message.js  ──────>  │   POST ../message         │
│                  │    │  api/command-center.js ──────>  │   GET /admin/cmd-center   │
│  X-API-Key       │    │  api/leads.js         ──────>  │   GET /admin/leads        │
│  in every req    │    │  api/analytics.js     ──────>  │   GET /admin/analytics    │
│                  │    │  api/documents.js     ──────>  │   /admin/properties/...   │
│                  │    │  api/flags.js         ──────>  │   /admin/flags            │
│                  │    │  api/broadcast.js     ──────>  │   POST /admin/broadcast   │
│                  │    │  api/brand-config.js  ──────>  │   /admin/brand-config     │
└─────────────────┘    └──────────────────────────┘    └───────────────────────────┘
                                                              │
                                                              │  require_admin_brand_key()
                                                              │  brand_hash = sha256(key)[:16]
                                                              │
                                                    ┌────────────────────┐
                                                    │  Redis             │
                                                    │  (brand-scoped     │
                                                    │   keys)            │
                                                    │                    │
                                                    │  PostgreSQL        │
                                                    │  (brand_hash col)  │
                                                    └────────────────────┘
```

### Why Vercel Edge Proxies?

Every admin API request goes through a Vercel Edge Function that forwards it to the Render backend. This seems like unnecessary indirection, but it serves three purposes:

1. **Hide the backend URL.** The browser never sees `claude-booking-bot.onrender.com`. It only sees `/api/conversations`. If the backend moves to a different host, only the `BACKEND_URL` environment variable on Vercel needs to change.

2. **CORS elimination.** Since the frontend and API proxies are on the same Vercel domain, there are no cross-origin issues. No CORS headers needed. No preflight requests.

3. **Edge caching potential.** Although not currently used, the Edge runtime allows adding `Cache-Control` headers for read-heavy endpoints like analytics or command center data.

Each proxy file is ~25 lines of boilerplate: check method, construct target URL, forward `X-API-Key` header, return response. The `BACKEND_URL` is read from Vercel environment variables.

---

## 12. Human Takeover System — Deep Dive

Human takeover is the most important feature in the admin panel. It is the mechanism that turns an AI chatbot into an AI-assisted sales tool. Here is how it works, end to end.

### The Takeover Flow

```
State: AI Active
  │
  │  Admin clicks [Take Over]
  │  POST /api/takeover/{uid}
  │  Backend: set_human_mode(uid, brand_hash)
  │    → Redis SET {uid}:{brand_hash}:human_mode = {active: "1", taken_at: <timestamp>}
  │
  ▼
State: Human Mode
  │  ● Amber banner: "You're handling this conversation — AI is paused"
  │  ● Input bar appears at bottom of thread
  │  ● Bot stops responding (pipeline checks get_human_mode before processing)
  │
  │  Admin types message + hits Enter
  │  POST /api/send-message/{uid}  {message: "Hi Arjun, I'm the property manager..."}
  │  Backend:
  │    1. Send message via WhatsApp (Meta/Interakt API)
  │    2. Save to conversation history (role: "assistant", source: "human")
  │    3. Auto-resume: clear_human_mode(uid, brand_hash)
  │
  ▼
State: AI Active (auto-resumed after message sent)
```

### Why Brand-Scoped Human Mode?

Before multi-brand isolation, human mode was stored in a global key: `{uid}:human_mode`. This meant that if Brand A took over a conversation, Brand B's admin could theoretically see that the user was in human mode (if they happened to share a user). Worse, Brand B could resume AI and override Brand A's takeover.

The fix: `{uid}:{brand_hash}:human_mode`. The human mode key now includes the brand hash, ensuring complete isolation. The pipeline checks `get_human_mode(uid, brand_hash)`, which reads the brand-scoped key first and falls back to the global key (for backward compatibility with legacy data).

### Auto-Resume After Message

When an admin sends a message via the admin panel, the backend automatically clears human mode after delivery. This is a deliberate UX choice: the most common workflow is "take over, send one message, let the bot handle the rest." Making the admin explicitly resume would add friction to the 80% case.

If the admin wants to send multiple messages, they need to take over again after each auto-resume. This is a known UX gap, but in practice, multi-message admin interventions are rare — they usually happen over WhatsApp directly, not through the admin panel.

### Edge Case: Forgotten Takeover

If an admin takes over and forgets to resume or send a message, the user is stuck in human mode indefinitely. The `{uid}:{brand_hash}:human_mode` key has no TTL.

Current mitigation: the Conversations list shows human mode status prominently (amber dot + "Human" label). The Analytics page shows a "Human Mode" KPI card counting active takeovers. But there is no automatic timeout or notification.

### What the Pipeline Does

In `core/pipeline.py:run_pipeline()`, before any agent processing:

```python
if await get_human_mode(uid, brand_hash):
    return ""  # Skip AI processing entirely
```

The bot literally does nothing. No response, no tool calls, no analytics tracking. The user's message is saved to conversation history, but the AI is silent. This continues until `clear_human_mode` is called.

---

## 13. API Proxy Architecture

Complete mapping of Vercel Edge proxy files to backend endpoints:

| Proxy File | Method | Frontend Path | Backend Path |
|------------|--------|---------------|--------------|
| `api/conversations.js` | GET | `/api/conversations` | `/admin/conversations` |
| `api/conversation.js` | GET | `/api/conversation/{uid}` | `/admin/conversations/{uid}` |
| `api/takeover.js` | POST | `/api/takeover/{uid}` | `/admin/conversations/{uid}/takeover` |
| `api/resume.js` | POST | `/api/resume/{uid}` | `/admin/conversations/{uid}/resume` |
| `api/send-message.js` | POST | `/api/send-message/{uid}` | `/admin/conversations/{uid}/message` |
| `api/command-center.js` | GET | `/api/command-center` | `/admin/command-center` |
| `api/leads.js` | GET | `/api/leads` | `/admin/leads` |
| `api/analytics.js` | GET | `/api/analytics` | `/admin/analytics` |
| `api/documents.js` | GET/POST/DELETE | `/api/documents?propId=X` | `/admin/properties/{propId}/documents` |
| `api/flags.js` | GET/POST | `/api/flags` | `/admin/flags` |
| `api/broadcast.js` | POST | `/api/broadcast` | `/admin/broadcast` |
| `api/brand-config.js` | GET/POST | `/api/brand-config` | `/admin/brand-config` |

All proxy files share the same pattern:

1. Extract `X-API-Key` from request headers
2. Construct target URL from `BACKEND_URL` env var
3. Forward the request with the API key header
4. Return the upstream response with `Content-Type: application/json`

All proxies run on Vercel Edge Runtime (`export const config = { runtime: 'edge' }`), which means they execute in the nearest Vercel edge location — typically <50ms overhead.

---

## 14. Frontend Architecture

### Technology Choices

| Choice | What | Why |
|--------|------|-----|
| React 18 | UI framework | Component model, hooks, React Query integration |
| TypeScript | Type safety | Catch API contract mismatches at compile time |
| Vite | Build tool | Fast HMR, ESBuild for production builds |
| Tailwind CSS | Styling | Utility-first, no custom CSS files needed |
| React Router v6 | Routing | `createBrowserRouter` with nested layouts |
| TanStack React Query | Data fetching | Caching, polling, mutations, query invalidation |
| Lucide React | Icons | Consistent icon set, tree-shakeable |
| shadcn/ui primitives | UI components | Radix-based accessible components (dialog, switch, tooltip) |
| clsx + tailwind-merge | Class merging | `cn()` utility for conditional Tailwind classes |

### Application Structure

```
src/
  App.tsx                          Router configuration
  main.tsx                         React root mount
  index.css                        Tailwind imports + global styles

  lib/
    api.ts                         apiFetch wrapper (X-API-Key header injection)
    auth.ts                        localStorage API key management
    types.ts                       TypeScript interfaces for all API responses
    utils.ts                       Shared utilities (relTs, avatarInitials, scoreFill, cn)

  hooks/
    useBrandConfig.ts              GET/POST /api/brand-config
    useCommandCenter.ts            GET /api/command-center (analytics data)
    useConversation.ts             GET /api/conversation/{uid}
    useConversations.ts            GET /api/conversations (polling: 30s)
    useFlags.ts                    GET/POST /api/flags
    useLeadProfile.ts              GET /api/leads?uid={uid}
    useLeads.ts                    GET /api/leads (with filters)
    useProperties.ts               GET /api/properties, documents CRUD

  pages/
    ConversationsPage.tsx          Two-pane conversation browser
    LeadsPage.tsx                  Filterable lead table
    LeadProfilePage.tsx            Individual lead profile (chat + profile tabs)
    AnalyticsPage.tsx              KPI cards + tables
    PropertiesPage.tsx             Property list with document side panel
    DocumentsPage.tsx              Document-centric view with upload zones
    SettingsPage.tsx               Flags + brand config + broadcast

  components/
    layout/
      AppShell.tsx                 Login gate + sidebar + mobile tab bar + <Outlet>
      Sidebar.tsx                  Dark nav rail (220px, collapsible to 56px)
    conversations/
      ConversationList.tsx         Scrollable list with search + human-mode filter
      ConversationRow.tsx          Single row: avatar, name, status dot, score
      ThreadPanel.tsx              Thread header + messages + input bar
      ThreadMessage.tsx            Individual message bubble (user/assistant/human/tool)
    ui/
      badge.tsx, button.tsx, card.tsx, dialog.tsx, input.tsx,
      scroll-area.tsx, separator.tsx, skeleton.tsx, switch.tsx,
      table.tsx, textarea.tsx, tooltip.tsx
      (shadcn/ui primitives — Radix-based accessible components)
```

### Design System

The admin panel uses CSS custom properties via Tailwind, with the Geist font family loaded from Google Fonts. The color palette is slate-based with blue as the primary accent.

Key design tokens:
- **Sidebar:** `bg-slate-900`, 220px width (collapsible to 56px), dark text
- **Content area:** `bg-slate-50` (light gray background), white cards with `border-slate-200`
- **Accent:** Blue-600 for primary actions, amber-500 for human mode, emerald-500 for success
- **Typography:** Geist (400/500/600/700 weights), system font fallback
- **Radius:** `rounded-xl` for cards, `rounded-md` for buttons/inputs, `rounded-full` for pills/avatars
- **Shadows:** `shadow-sm` on cards only — minimal shadow usage

### Sidebar Navigation

The sidebar has 6 navigation items, each with a Lucide icon:

| Icon | Label | Route |
|------|-------|-------|
| MessageSquare | Conversations | `/` |
| Users | Leads | `/leads` |
| BarChart2 | Analytics | `/analytics` |
| Building2 | Properties | `/properties` |
| FolderOpen | Documents | `/documents` |
| Settings | Settings | `/settings` |

The sidebar header shows the brand name dynamically (fetched via `useBrandConfig()`). When collapsed, only the brand initial and icons are visible.

Footer: collapse/expand toggle + sign-out button.

On mobile (< 768px), the sidebar is hidden and replaced by a fixed bottom tab bar with 5 items (Documents is omitted from mobile nav).

---

## 15. Thread Renderer

The thread renderer (`ThreadMessage.tsx`) handles four message types, each with distinct visual treatment:

### User Messages

```
┌───────────────────────────────────┐
│  Looking for PGs in Andheri       │  ← slate-100 bg, rounded-tl-sm
│  with WiFi and AC                 │    (sharp top-left corner)
└───────────────────────────────────┘
                              10:34 AM
```

Left-aligned. Gray background (`bg-slate-100`). Standard text rendering.

### Assistant (AI) Messages

```
                ┌───────────────────────────────────┐
  blue border → │  BROKER                           │  ← white bg, colored left border
                │  Here are 3 properties in          │    based on agent:
                │  Andheri matching your budget:      │    blue=broker, emerald=booking,
                │                                     │    purple=profile, slate=default
                │  🔍 Tool: search_properties    [>] │  ← collapsible tool call card
                └───────────────────────────────────┘
                                              10:34 AM
```

Right-aligned. White background with a 4px left border color-coded by agent. Agent name shown in uppercase 10px text at the top. Tool calls rendered as collapsible cards: click to expand and see the JSON input parameters.

Agent-to-border-color mapping:
- **broker:** blue-400
- **booking:** emerald-400
- **profile:** purple-400
- **default:** slate-300

### Admin (Human) Messages

```
                ┌───────────────────────────────────┐
 amber border → │  ADMIN                            │  ← white bg, amber left border
                │  Hi Arjun, this is the property   │
                │  manager. Let me help you with     │
                │  the booking directly.             │
                └───────────────────────────────────┘
                                              10:35 AM
```

Right-aligned. White background with amber left border. "ADMIN" label in amber. These are messages sent by the operator through the admin panel's input bar, delivered to the user via WhatsApp.

### Tool Call Cards

When an assistant message contains `tool_use` content blocks, they render as collapsible sections:

- Collapsed: magnifying glass icon + "Tool: search_properties" + chevron
- Expanded: JSON-formatted input parameters in a monospace `<pre>` block, with `break-all` word wrap

### Time Dividers

If two consecutive messages are more than 30 minutes apart, a horizontal divider with the timestamp appears between them:

```
────────────── 2:15 PM ──────────────
```

---

## 16. Technology Stack

### Frontend

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Framework | React | 18 | UI rendering, component model |
| Language | TypeScript | 5.x | Type safety for API contracts |
| Build | Vite | 5.x | Dev server (port 5174), production builds |
| Styling | Tailwind CSS | 3.x | Utility-first CSS, responsive design |
| Data fetching | TanStack React Query | 5.x | Caching, polling, optimistic updates |
| Routing | React Router | 6.x | SPA routing with nested layouts |
| Icons | Lucide React | — | Consistent icon set |
| UI primitives | shadcn/ui (Radix) | — | Accessible dialog, switch, tooltip |
| Class merging | clsx + tailwind-merge | — | `cn()` utility |

### Hosting

| Component | Platform | Config |
|-----------|----------|--------|
| Frontend | Vercel | Auto-deploy from `eazypg-admin/` directory |
| API proxies | Vercel Edge Functions | Same project, `api/` directory |
| Backend | Render | Shared with chat widget (FastAPI) |
| Database | Render PostgreSQL | Shared with chat widget |
| Cache | Render Redis | Shared with chat widget |

### Environment Variables (Vercel)

| Variable | Purpose | Example |
|----------|---------|---------|
| `BACKEND_URL` | FastAPI backend URL | `https://claude-booking-bot.onrender.com` |

The frontend has exactly one environment variable. Everything else is either hardcoded (Tailwind config, route paths) or fetched from the backend at runtime (brand config, feature flags).

---

## 17. Data Flow & Backend Endpoints

### Endpoint Catalog

All admin endpoints require the `X-API-Key` header. The backend validates the key via `require_admin_brand_key()`, which returns the `brand_hash` used to scope all queries.

#### Conversations

**GET /admin/conversations**

Request: `?limit=50&offset=0`

Response:
```json
{
  "conversations": [
    {
      "uid": "919876543210",
      "name": "Arjun Sharma",
      "phone": "9876543210",
      "lead_score": 72,
      "human_mode": false,
      "last_seen": 1710500000,
      "last_message": "Looking for PGs in Andheri",
      "message_count": 14,
      "last_agent": "broker",
      "cost_usd": 0.0312
    }
  ],
  "total": 42
}
```

**GET /admin/conversations/{uid}**

Response:
```json
{
  "uid": "919876543210",
  "name": "Arjun Sharma",
  "phone": "9876543210",
  "lead_score": 72,
  "human_mode": false,
  "last_agent": "broker",
  "messages": [
    {
      "role": "user",
      "content": "Hi, looking for PGs",
      "timestamp": 1710499000
    },
    {
      "role": "assistant",
      "content": [
        {"type": "text", "text": "Let me search..."},
        {"type": "tool_use", "name": "search_properties", "input": {"location": "Andheri"}}
      ],
      "metadata": {"agent": "broker"},
      "timestamp": 1710499005
    }
  ],
  "memory": {
    "budget_min": 8000,
    "budget_max": 12000,
    "area_preference": "Andheri West",
    "shortlisted_properties": ["Sunshine PG", "Green View"],
    "move_in_date": "2026-04-01"
  },
  "cost": {
    "tokens_in": 15420,
    "tokens_out": 2310,
    "cost_usd": 0.0312
  }
}
```

#### Human Takeover

**POST /admin/conversations/{uid}/takeover** — Sets `{uid}:{brand_hash}:human_mode`. Returns `{"ok": true}`.

**POST /admin/conversations/{uid}/resume** — Clears human mode. Returns `{"ok": true}`.

**POST /admin/conversations/{uid}/message** — Sends message via WhatsApp, saves to history, auto-resumes AI. Body: `{"message": "text"}`. Returns `{"ok": true, "sent": true}`.

#### Analytics

**GET /admin/command-center**

Response:
```json
{
  "messages_today": 142,
  "new_leads_today": 8,
  "active_users": 12,
  "human_mode_count": 2,
  "visits_today": 3,
  "cost_usd_today": 0.2140,
  "funnel": {
    "search": 45, "detail": 28, "shortlist": 12, "visit": 3, "booking": 1
  },
  "skill_usage": {
    "search": 34, "qualify_new": 18, "details": 15, "selling": 8
  },
  "agents": {
    "broker": {"tokens_in": 245000, "tokens_out": 32000, "cost_usd": 0.0890},
    "booking": {"tokens_in": 12000, "tokens_out": 3500, "cost_usd": 0.0620}
  }
}
```

#### Leads

**GET /admin/leads**

Request: `?limit=25&offset=0&stage=shortlist&area=Andheri&search=arjun`

Response:
```json
{
  "leads": [
    {
      "uid": "919876543210",
      "name": "Arjun Sharma",
      "phone": "9876543210",
      "persona": "professional",
      "stage": "shortlist",
      "lead_score": 72,
      "location_pref": "Andheri West",
      "budget_min": 8000,
      "budget_max": 12000,
      "viewed_count": 5,
      "shortlisted_count": 2,
      "visits_count": 0,
      "must_haves": ["AC", "WiFi"],
      "deal_breakers": ["no non-veg"],
      "first_seen": "2026-03-10T10:00:00Z",
      "last_seen": "2026-03-15T14:30:00Z",
      "cost_usd": 0.0312
    }
  ],
  "total": 42
}
```

#### Feature Flags

**GET /admin/flags** — Returns effective flags (global defaults merged with brand overrides).

Response: `{"DYNAMIC_SKILLS_ENABLED": true, "KYC_ENABLED": false, "PAYMENT_REQUIRED": false}`

**POST /admin/flags** — Two accepted formats:

Format 1: `{"key": "KYC_ENABLED", "value": true}`
Format 2: `{"KYC_ENABLED": true}`

Both update the brand-scoped override in `brand_flags:{brand_hash}`.

#### Properties & Documents

**GET /admin/properties** — Returns properties from brand's pg_ids config.

**POST /admin/properties/{prop_id}/documents** — Upload file (multipart/form-data). Ownership check: prop_id must be in brand's pg_ids.

**GET /admin/properties/{prop_id}/documents** — List documents for a property.

**DELETE /admin/properties/{prop_id}/documents/{doc_id}** — Delete a document.

#### Brand Config

**GET /admin/brand-config** — Returns brand config with masked WhatsApp token.

**POST /admin/brand-config** — Create or update brand config. Auto-generates `brand_link_token` (UUID) for the chatbot URL.

#### Broadcast

**POST /admin/broadcast** — Body: `{"message": "text"}`. Sends to all brand users active in last 7 days. Returns `{"sent": 42}`.

---

## 18. Success Metrics

### Adoption Metrics

| Metric | Definition | Target |
|--------|-----------|--------|
| Weekly active brands | % of configured brands that access the admin panel at least once per week | > 80% |
| Daily active operators | Number of unique API keys used per day | Track trend |
| Page distribution | Which pages operators visit most (via page view counts) | Conversations > 50% |

### Takeover Metrics

| Metric | Definition | Why It Matters |
|--------|-----------|----------------|
| Time to takeover | Time between user's message and admin's takeover click | Measures admin responsiveness |
| Takeover rate | % of conversations that involve at least one human takeover | Measures AI sufficiency (lower = better AI) |
| Messages per takeover | How many admin messages are sent per takeover session | 1 = AI handles the rest; 5+ = AI is failing |
| Forgotten takeovers | Human mode sessions active for > 4 hours without a message sent | Measures the "forgotten takeover" edge case |

### Content Metrics

| Metric | Definition |
|--------|-----------|
| Broadcast send rate | Number of broadcasts sent per week per brand |
| Document upload rate | Number of documents uploaded per property per month |
| Flag toggle rate | How often feature flags are changed per brand |

### Operational Metrics

| Metric | Definition |
|--------|-----------|
| API proxy latency (p50/p99) | Vercel Edge proxy overhead |
| Polling failure rate | % of background refetches that return errors |
| Login failure rate | % of API key validation attempts that fail |

---

## 19. Known Limitations & Future Work

### Limitations

| Category | Limitation | Impact | Workaround |
|----------|-----------|--------|------------|
| **Real-time** | Polling-based, not WebSocket | Conversations can be up to 30s stale | Manual browser refresh |
| **Auth** | No role-based access control — single API key per brand | Cannot give read-only access to investors or limited access to junior staff | Share key selectively (not ideal) |
| **Audit** | No audit log for admin actions | Cannot track who took over, who sent broadcasts, who changed flags | Review conversation history for takeover evidence |
| **UI** | No dark mode | Aesthetic preference only | Browser extensions |
| **Mobile** | Documents page omitted from mobile nav | Cannot manage documents on mobile | Use desktop |
| **Export** | No CSV/PDF export for leads or analytics | Operators cannot pull data into spreadsheets | Screenshot or manual copy |
| **Notifications** | No real-time notification for new conversations | Operator must check the panel proactively | Set browser tab to auto-refresh |
| **Thread rendering** | Does not render Generative UI parts (property carousels, comparison tables) | Admin sees raw markdown instead of rich cards | Content is still readable as text |
| **Takeover** | No auto-timeout for forgotten takeovers | Users stuck in human mode indefinitely | Monitor human_mode_count in analytics |
| **Takeover** | Auto-resume after each message sent | Cannot send multiple messages in one takeover session without re-taking over | Use WhatsApp directly for multi-message interventions |
| **Flags** | Tool availability changes require server restart | Toggling KYC/Payment flags has delayed effect on tool set | Restart backend after flag change |
| **Search** | Client-side search on loaded data, not server-side full-text search | Cannot search across all conversations if only 50 are loaded | Load more data first |

### Future Work (Prioritized)

**P0 — High Impact, Low Effort:**
- Add auto-timeout for human mode (4-hour TTL on `{uid}:{brand_hash}:human_mode`)
- Add CSV export for leads table
- Render Generative UI parts in thread (reuse chat widget's renderer components)

**P1 — High Impact, Medium Effort:**
- WebSocket for conversation list (eliminate polling, enable real-time notifications)
- Role-based access: viewer (read-only), agent (conversations + takeover), admin (full access)
- Audit log for admin actions (takeover, resume, message, flag toggle, broadcast)
- Server-side full-text search across all conversations

**P2 — Nice to Have:**
- Dark mode (Tailwind `dark:` variants)
- Mobile-optimized document management
- Scheduled broadcasts (not just immediate)
- Targeted broadcasts (filter by stage, area, score)
- Analytics date range selector (currently today-only)
- Chart.js visualizations for funnel and cost trends over time
- Notification badge on sidebar when new conversations arrive
- Keyboard shortcuts (j/k to navigate list, Enter to open, Esc to close)
