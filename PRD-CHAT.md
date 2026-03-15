# EazyPG AI Chat — Product Requirements Document

**Version:** 1.0
**Date:** March 2026
**Author:** Product & Engineering
**Status:** Production — Documenting Existing System

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [The Chat Experience — Design Principles](#2-the-chat-experience--design-principles)
3. [Users & Personas](#3-users--personas)
4. [Problem & Opportunity](#4-problem--opportunity)
5. [System Architecture](#5-system-architecture)
6. [Multi-Agent System](#6-multi-agent-system)
7. [The Broker Intelligence — How It Sells](#7-the-broker-intelligence--how-it-sells)
8. [Conversation Flows — Complete Journeys](#8-conversation-flows--complete-journeys)
9. [WhatsApp Channel](#9-whatsapp-channel)
10. [Web Chat Channel](#10-web-chat-channel)
11. [Generative UI System](#11-generative-ui-system)
12. [Multi-Brand White-Label System](#12-multi-brand-white-label-system)
13. [Feature Flags](#13-feature-flags)
14. [Human Takeover System](#14-human-takeover-system)
15. [Dynamic Skill System](#15-dynamic-skill-system)
16. [Conversation Memory & Summarization](#16-conversation-memory--summarization)
17. [Technology Stack](#17-technology-stack)
18. [Data Model](#18-data-model)
19. [Analytics & Funnel Tracking](#19-analytics--funnel-tracking)
20. [Rate Limiting & Safety](#20-rate-limiting--safety)
21. [Success Metrics](#21-success-metrics)
22. [Known Limitations & Future Work](#22-known-limitations--future-work)

---

## 1. Executive Summary

EazyPG Chat is a two-channel AI chatbot — WhatsApp and Web — that acts as a conversational real estate broker for PG (Paying Guest) and co-living properties in India. It is not a search engine with a chat interface. It is a sales agent that qualifies leads, recommends properties, handles objections, and drives users toward scheduling a visit — the single highest-conversion event in Indian PG rentals.

**What makes this product different:**

1. **It sells, it doesn't search.** The bot never presents a list of 20 options and says "here you go." It qualifies users, scores properties against their preferences, and presents the top 5 with match percentages and narrative explanations. It handles objections ("that's too expensive") with value reframing, not just cheaper alternatives. It always gravitates toward a visit booking.

2. **Two channels, one brain.** WhatsApp (India's dominant messaging platform) and the web widget share the exact same AI pipeline. A user can start on the website and continue on WhatsApp with full context. The same agents, same tools, same memory.

3. **White-labeled for multiple brands.** OxOtel, Stanza, Zelter — each brand gets its own identity, property inventory, analytics, and feature flags. The bot introduces itself by the brand's name, shows only that brand's properties, and tracks analytics separately. Brand isolation is cryptographic (SHA-256 hash), not just a database filter.

4. **Multi-agent architecture.** Not one massive prompt trying to do everything. A supervisor routes each message to one of four specialist agents (broker, booking, profile, default), each with its own model, prompt, and toolset. The broker runs on Haiku for cost efficiency; booking runs on Sonnet for reliability on transactional operations.

5. **Dynamic skill system.** The broker agent doesn't load a 580-line monolithic prompt every turn. The supervisor detects which 1-3 skills are needed (search, details, compare, commute, selling, etc.), and only those skill files are loaded. This reduces token costs, improves response quality, and allows hot-reloading of individual skills without restarting the server.

**Production stats:**

| Metric | Value |
|--------|-------|
| Registered tools | 28 |
| Broker skills | 12 |
| Agents | 4 + supervisor |
| Supported languages | English, Hindi, Marathi (+ Hinglish code-switching) |
| Channels | WhatsApp + Web |
| Brands in production | 3 (OxOtel, Stanza, Zelter) |
| Test coverage | 35/35 e2e, 16/16 tool tests, 13/5/2 stress tests |

---

## 2. The Chat Experience — Design Principles

This section defines what the product *feels* like. Every architectural decision, every prompt tweak, every UI component exists to serve this experience. If a technical decision degrades any principle below, the technical decision is wrong.

### Principle 1: Conversational Broker, Not Search Engine

The difference between EazyPG Chat and a property portal is the difference between walking into a real estate office and opening Zillow. A portal gives you 200 listings and says "filter to your heart's content." A broker listens to what you need, knows the market, and says "I've got three places that would work for you — here's why."

**What this means in practice:**

The user says: "I need a PG near Andheri, under 10k"

Bad bot: "Here are 47 PGs near Andheri under 10,000. [link to listing page]"
*(That's a search engine. The user already tried that. It didn't help.)*

Good bot: "Got it — Andheri under 10k. Quick question: is this for work or college? I want to make sure I'm looking near the right part of Andheri."
*(That's a broker. She's qualifying before searching, because the right 5 results are worth more than 47 random ones.)*

The bot calls `save_preferences` before `search_properties` — every time. Because showing results without understanding needs is just noise.

### Principle 2: ONE Question at a Time

This is non-negotiable. Every response ends with exactly ONE question or call-to-action. Not two. Not "or would you prefer...?" Not a list of options.

**Why:** Multiple questions create decision paralysis. The user reads the first question, starts thinking about it, reads the second, gets confused about which to answer, and either picks one randomly or doesn't respond at all. One question per turn keeps the conversation moving forward with purpose.

**Wrong:**
> "Want to see details? Or images? Or should I shortlist it? Or we could schedule a visit?"

**Right:**
> "Want to see details on the first one, or go straight to booking a visit?"

Even this example has a binary choice, which is acceptable. But the ideal is a single, directional question that moves toward conversion:
> "They have slots this Saturday — want me to book a morning visit?"

### Principle 3: Never Say "Go to a Website"

This IS the service. The moment the bot says "you can check our website for more details" or "visit rentok.com to complete your booking," it has failed. Every action — searching, viewing images, comparing properties, scheduling visits, making payments — happens inside the conversation.

The bot has 28 tools. If it can't do something, it should say "let me check that for you" and call the appropriate tool. If no tool exists for the request, it should acknowledge the gap honestly, not redirect to a website.

### Principle 4: Multilingual with Natural Code-Switching

The bot supports English, Hindi, and Marathi — but more importantly, it supports Hinglish, the way young Indians actually communicate. Language detection happens on the first message, and the bot mirrors the user's register:

| User Register | Bot Response Style |
|--------------|-------------------|
| Formal English | Professional, data-led, zero filler |
| Casual English | Friendly, uses contractions, light emoji |
| Hindi | Natural Hindi, Devanagari when appropriate |
| Hinglish ("yaar koi accha PG dikhao near Andheri") | Code-switches naturally, peer energy |
| Marathi | Responds in Marathi with warmth |

The bot never forces a language. It follows the user's lead. If the user switches from English to Hindi mid-conversation, the bot switches too — without commenting on it.

### Principle 5: Warm but Not Salesy on First Message, Persistent on Conversion

The first message sets the tone. If the bot opens with "Hi! I can help you find your PERFECT PG today!!!" the user's trust drops immediately. If it opens with "Hey, I'm Tarini from OxOtel. Looking for a PG? I know the area well — tell me what you need," trust goes up.

But warmth on the first message doesn't mean passivity throughout the conversation. The bot is a sales agent. After building trust and showing properties, it should persistently (but respectfully) guide toward a visit booking:

| Conversation Phase | Bot Behavior |
|-------------------|-------------|
| First 2-3 turns | Warm, qualifying, building rapport |
| Property presentation | Excited about good matches, honest about trade-offs |
| Post-presentation | Persistent — "They have a slot Saturday morning, want me to lock it in?" |
| Objection handling | Empathetic first ("I hear you"), then reframe, then alternative |
| User going cold | Plant a seed — "I'll save your preferences. When you're ready, just ping me." |

### Principle 6: Narrative First, Data Second

Properties are not spreadsheet rows. They're places where people will live. The bot presents properties as narratives with supporting data, not data dumps with no context.

**Wrong:**
> Property: Sharma PG. Area: Andheri West. Rent: 9000. Sharing: Double. Amenities: AC, WiFi, Meals, Laundry. Distance: 1.2km from metro.

**Right:**
> **Sharma PG** is your best match at 91% — it's in Andheri West, just a 15-minute walk from the metro. Double sharing at 9,000/mo with AC, WiFi, meals, and laundry included. Most people spending this much in Andheri don't get meals included — that alone saves you 4-5k/month.

The data is the same. The framing is completely different. The second version tells a story: why this property matters for THIS user.

### Principle 7: Rich UI as Supporting Evidence, Not Primary Response

On the web channel, the bot can render carousels, comparison tables, maps, image galleries, and expandable sections. These are powerful — but they support the narrative, they don't replace it.

The bot should never respond with ONLY a carousel and no text. The text explains WHY these properties were chosen. The carousel shows WHAT they look like. Together, they're persuasive. Apart, the carousel is just a list and the text is just a wall of words.

### Principle 8: Always Gravitate Toward a Visit

Every response, at every stage of the conversation, should create a natural path toward scheduling a site visit. Not by being pushy — by making the visit sound easy, low-commitment, and valuable.

The visit is not just a feature of the product. The visit IS the product. Industry data shows 8%+ conversion from site visit to booking — 8-10x higher than inquiry-to-booking without a visit. Once someone physically visits, sunk cost psychology kicks in. They invested time and effort. They convert.

**CTA variations based on conversation temperature:**

| Temperature | CTA Style |
|-------------|-----------|
| Hot ("I need to move by Monday") | "I can hold a slot for you this Saturday. Want me to lock it in?" |
| Warm (interested, comparing options) | "You could swing by and see it — no commitment, just a look. Saturday work?" |
| Cold ("just browsing") | "I'll send you the details. If you like what you see, we can set up a visit whenever you're ready." |

---

## 3. Users & Personas

### Persona 1: The Urgent Mover

> *"I need a room by Monday. My job starts next week in Whitefield."*

| Attribute | Detail |
|-----------|--------|
| **Profile** | Priya, 23, software engineer relocating for a new job |
| **Temperature** | Hot |
| **Signals** | Specific timeline, asks about availability, mentions job start date |
| **Decision-maker** | Self (working professional, paying own rent) |
| **What the bot should do** | Skip deep qualifying. She already knows what she needs. Go straight to best-match property. Push for immediate visit. "They have a bed available right now — want to see it this Saturday morning?" |
| **Biggest risk** | Speed. If the bot takes 3 turns to qualify her, she'll book the first decent PG she finds on NoBroker. Every second of unnecessary qualifying is a lost lead. |

**Example conversation:**
```
Priya: I need a PG near Whitefield, under 12k, with AC. Moving next week.

Bot:   Got it — Whitefield, under 12k, AC. Let me search right now.
       [calls save_preferences → search_properties]

       Great news! Your best match is OxOtel Tech Park — 91% match.
       📍 Whitefield, Bangalore · ₹11,000/mo · Female · 8 min from ITPL

       AC, WiFi, meals, and laundry all included. They have a bed available
       right now. Want me to book a visit for this Saturday morning?
```

### Persona 2: The Careful Planner

> *"I'm moving to Mumbai in about a month. Just starting to look around."*

| Attribute | Detail |
|-----------|--------|
| **Profile** | Rahul, 24, marketing executive being transferred |
| **Temperature** | Warm |
| **Signals** | Has a timeline but it's not urgent, asks comparative questions, wants to understand options |
| **Decision-maker** | Self, but will consult parents on final choice |
| **What the bot should do** | Qualify thoroughly. Rahul has time and wants to make a good decision. Show him his top 5 options. Offer comparison. Build shortlist. Don't rush the visit — earn it by demonstrating value. |
| **Biggest risk** | Information overload. Rahul will research 15 options across 4 platforms. The bot needs to make its recommendations feel definitive: "I've looked at everything in your criteria — these are the best 5." |

**Example conversation:**
```
Rahul: Moving to Mumbai next month for work. Need a PG near BKC, budget
       around 15k. What options do you have?

Bot:   BKC, nice! Is your office right in BKC or nearby? I want to make
       sure I search the right commute radius.

Rahul: It's in the Bandra Kurla Complex area, near Diamond Garden.

Bot:   Perfect — let me find you the best matches near BKC.
       [calls save_preferences → search_properties]

       Found 5 strong options. Your top match:

       **1. OxOtel BKC Residency** — 94% match
       📍 BKC, Mumbai · ₹14,500/mo · Male · 10 min walk from Diamond Garden

       **2. Zelter Bandra East** — 87% match
       📍 Bandra East · ₹13,000/mo · Male · 15 min by auto

       [3 more properties...]

       Want me to pull up details on the top one, or compare a couple side by side?
```

### Persona 3: The Budget Hunter

> *"Kya sabse sasta PG hai Andheri mein? 6000 se kam chahiye."*

| Attribute | Detail |
|-----------|--------|
| **Profile** | Anjali, 19, first-year college student from Lucknow. Parents are paying. |
| **Temperature** | Warm (has intent, constrained by budget) |
| **Signals** | Leads with budget, asks about discounts, Hinglish, mentions parents |
| **Decision-maker** | Parents (paying and approving every rupee) |
| **What the bot should do** | Never start with the cheapest option — it anchors low. Frame total value: "7,000 includes meals, WiFi, and laundry — eating out alone costs 4-5k/month." Address parents' concerns proactively: safety, proximity to college, total cost transparency. Code-switch to match Anjali's register. |
| **Biggest risk** | Sticker shock leading to immediate disengagement. Must frame value before stating price. If everything is genuinely above her budget, be honest — don't show options that will disappoint. |

**Example conversation:**
```
Anjali: Kya sabse sasta PG hai Andheri mein? 6000 se kam chahiye.

Bot:   Andheri mein 6k ke under tough hai, but let me check — college ke
       liye aa rahi ho ya job?

Anjali: College — NMIMS hai Vile Parle mein.

Bot:   NMIMS, nice! Vile Parle is better than Andheri for you — closer to
       campus and slightly cheaper. Let me search.
       [calls save_preferences → search_properties]

       Best option: OxOtel Vile Parle at ₹7,500/mo — I know it's a bit
       over 6k, but this includes meals, WiFi, and laundry. Bahar khana
       khane mein hi 4-5k lag jaate hain, so net-net you're saving money.

       Parents ko bhi safe lagega — it's gated with CCTV and right next to
       the station. Want to see photos?
```

### Persona 4: The Parents

> *"My daughter is joining engineering college in Pune. We want something very safe."*

| Attribute | Detail |
|-----------|--------|
| **Profile** | Mr. and Mrs. Sharma, 50s, checking PGs for their 18-year-old daughter |
| **Temperature** | Warm (active intent, high anxiety) |
| **Signals** | "My daughter/son," asks about safety, CCTV, curfew, food quality, visitor policies |
| **Decision-maker** | Themselves (they are the decision-makers, the student is the user) |
| **What the bot should do** | Address safety FIRST — before price, before amenities, before location. Mention security features proactively: CCTV, gated entry, warden on premises, visitor logs. Offer to send photos of the entrance, common areas, and security setup. Formal register — no emoji, no "yaar." |
| **Biggest risk** | Trust. Parents are handing their child's safety to a stranger. The bot must feel reliable and thorough, not casual and breezy. One flippant response about safety and they're gone. |

**Example conversation:**
```
Parent: My daughter is joining engineering college in Pune. We want
        something very safe, preferably with meals and close to campus.

Bot:    Absolutely — safety is the top priority. Which college is she
        joining? I'll look for options with 24/7 security, CCTV, and
        warden-supervised access.

Parent: MIT Pune, the one in Kothrud.

Bot:    MIT Kothrud — let me find the safest options nearby.
        [calls save_preferences → search_properties]

        Your best match is OxOtel Kothrud — it has 24/7 security with a
        warden, CCTV in all common areas, biometric entry, and a strict
        visitor policy. It's a 10-minute walk from MIT.

        ₹9,500/mo including three meals a day. Vegetarian and non-veg
        options available.

        Would you like me to send you photos of the property — especially
        the entrance, security setup, and rooms?
```

---

## 4. Problem & Opportunity

### The Problem

The Indian PG market is a trust desert. Here's what a typical tenant's search looks like:

1. **Search on 3-4 portals** (NoBroker, Housing.com, MagicBricks, 99acres). Get 200+ listings. Most are outdated, many are fake.

2. **Call 10-15 PGs**. Half don't pick up. Three have no beds available. Two are nothing like the photos. One number is disconnected.

3. **Visit 4-5 properties** over 2 weekends. Two are in the wrong area (the listing said "near metro" — it's 3km away). One has no AC despite claiming it. One is genuinely good but costs 20% more than listed.

4. **Book the least-bad option** out of exhaustion, not conviction.

This process takes 1-3 weeks. It is frustrating, time-consuming, and builds zero trust in the market. Every step involves information asymmetry: the tenant doesn't know the area, doesn't know fair pricing, doesn't know which PGs are legitimate.

**For property operators, the problem is equally brutal:**

- **Lead waste.** A portfolio operator with 5 PGs gets 30-100 inquiries per day. No human team can respond to all of them fast enough. A lead contacted within 5 minutes is 21x more likely to convert than one contacted after 30 minutes. Most operators respond the next day, if at all.

- **Qualification cost.** Human sales reps spend 60-70% of their time talking to people who will never book — wrong budget, wrong area, just browsing. Without systematic qualification, every lead looks the same.

- **Consistency.** Human reps have good days and bad days. They forget to mention amenities. They get defensive about pricing. They don't follow up. An AI agent is consistent on every single conversation.

### The Opportunity

**For tenants:** An AI broker that qualifies their needs, knows every property in the inventory, scores matches objectively, handles the entire booking flow, and never asks them to "check the website."

**For operators:** An AI sales team that responds instantly to every lead, qualifies systematically, books visits automatically, and costs a fraction of a human team.

**The market dynamics that make this work:**

1. **WhatsApp dominance.** India has 500M+ WhatsApp users. It's the default communication channel for 18-35 year olds. A PG chatbot on WhatsApp doesn't need to convince users to download anything — it meets them where they already are.

2. **Fragmented supply.** The PG market is hyper-local, fragmented across thousands of small operators. This creates information asymmetry that an AI broker can exploit: by knowing ALL properties in an area, it can genuinely recommend the best one for each user.

3. **High conversion from visits.** 8%+ of site visits convert to bookings (industry data). The bottleneck is getting people from "interested" to "visiting." Reducing inquiry-to-visit from days to minutes is the core value proposition.

4. **AI cost curve.** Claude Haiku costs ~$0.25 per million input tokens. A typical broker conversation is 15-20 turns. Total cost per conversation: $0.02-0.05. Compare that to a human sales rep handling 30-40 leads per day at ₹25,000/month salary.

---

## 5. System Architecture

### Architecture Diagram

```
USER
  │
  ├── WhatsApp ──→ [Meta Webhook] ──→ POST /webhook/whatsapp
  │                                         │
  │                                    [Phase B: Queue + Debounce]
  │                                    wamid dedup → wa_queue → 2s debounce
  │                                         │
  └── Web Chat ──→ [SSE Stream] ──→ POST /chat/stream
                                         │
                                    [Phase A: AbortController]
                                    interrupt-on-send
                                         │
                                         ▼
                              ┌─────────────────────┐
                              │   SHARED PIPELINE    │
                              │   run_pipeline()     │
                              │                      │
                              │  1. Rate limit check │
                              │  2. Human mode check │
                              │  3. Load conversation│
                              │  4. Load user memory │
                              │  5. Detect language  │
                              │                      │
                              │         │            │
                              │         ▼            │
                              │   ┌───────────┐      │
                              │   │SUPERVISOR │      │
                              │   │  (Haiku)  │      │
                              │   └─────┬─────┘      │
                              │         │            │
                              │    classifies to:    │
                              │    {agent, skills[]} │
                              │         │            │
                              │    ┌────┼────┐       │
                              │    ▼    ▼    ▼       │
                              │  ┌──┐ ┌──┐ ┌──┐     │
                              │  │Bk│ │Bo│ │Pr│ ... │
                              │  └──┘ └──┘ └──┘     │
                              │    │                 │
                              │    ▼                 │
                              │  [Tool Executor]     │
                              │    │                 │
                              │    ▼                 │
                              │  [Rentok API]        │
                              │  apiv2.rentok.com    │
                              │                      │
                              └──────────┬───────────┘
                                         │
                              ┌──────────┼──────────┐
                              │          │          │
                              ▼          ▼          ▼
                         [WhatsApp]  [SSE Stream] [Redis]
                         send_text   content_delta save_conversation
                         send_carousel            track_analytics

Bk = Broker Agent (Haiku)
Bo = Booking Agent (Sonnet)
Pr = Profile Agent (Sonnet)
... = Default Agent (Sonnet)
```

### Key Architectural Decisions

**1. Shared pipeline for both channels.** WhatsApp and web both call `run_pipeline(user_id, message_text)`. This is the most important architectural decision in the system. It means every feature — memory, analytics, brand isolation, human takeover — works identically on both channels without any channel-specific code.

**2. Multi-brand isolation via `brand_hash`.** Each brand's API key is hashed: `brand_hash = sha256(api_key)[:16]`. This 16-character hash becomes the namespace for ALL brand-scoped data: conversation tags, analytics, feature flags, human mode. The raw API key is never stored. A brand can only see its own data, enforced cryptographically at the Redis key level.

**3. Supervisor + specialist agents, not one monolithic agent.** The supervisor (Haiku, fast) classifies each message and routes to the right specialist. This means the broker agent never sees booking tool schemas (reducing confusion), and the booking agent never sees property search tools (reducing cost). Each agent has its own system prompt optimized for its task.

**4. Dynamic skill loading for the broker agent.** Instead of loading all 12 skill prompts every turn, the supervisor detects which 1-3 skills are needed and only those are loaded. This reduces input tokens by 60-70% per broker turn.

**5. Redis for state, PostgreSQL for logs.** Redis holds everything the AI needs in real-time: conversation history, user memory, property cache, rate limits, analytics counters. PostgreSQL holds everything humans need to audit: message logs and lead records. Both are brand-scoped.

---

## 6. Multi-Agent System

### The Supervisor

The supervisor is the first agent to see every message. Its job: classify intent and route to the right specialist.

| Attribute | Detail |
|-----------|--------|
| **Model** | Claude Haiku (`claude-haiku-4-5-20251001`) |
| **Latency** | 200-400ms typical |
| **Output** | `{"agent": "broker"|"booking"|"profile"|"default", "skills": ["search", "details", ...]}` |
| **Skills detection** | Only for broker agent. 1-3 skills per turn. |
| **Fallback** | Keyword safety net (3-phase: phrases -> words -> last_agent) if classifier fails |

The supervisor prompt includes skill detection heuristics — when it classifies to the broker agent, it also identifies which broker skills are needed. This drives the dynamic skill system (Section 15).

The keyword safety net is a fallback for when the Haiku classifier makes a mistake. It runs a 3-phase keyword match:
1. **Phrase match:** "schedule a visit" -> booking agent
2. **Word match:** "visit" -> booking agent, "compare" -> broker agent
3. **Last-agent stickiness:** if no keywords match, route to the last-used agent (stored in Redis)

### Broker Agent

The workhorse. Handles property search, details, images, comparisons, commute estimation, shortlisting, and the qualifying conversation.

| Attribute | Detail |
|-----------|--------|
| **Model** | Claude Haiku (`claude-haiku-4-5-20251001`) — chosen for cost, adequate for property conversations |
| **Persona** | Tarini — 28-year-old real estate broker, 5 years experience, warm and direct |
| **Prompt** | Dynamic: `_base.md` (always loaded) + 1-3 skill files |
| **Max tool iterations** | 15 per run |

**Tools:**

| Tool | Function | Purpose |
|------|----------|---------|
| `save_preferences` | `tools/broker/preferences.py` | Save user's must-haves and nice-to-haves before searching |
| `search_properties` | `tools/broker/search.py` | Geocode address -> Rentok API search -> cache -> score -> return top results |
| `fetch_property_details` | `tools/broker/property_details.py` | Detailed info on a specific property |
| `fetch_room_details` | `tools/broker/room_details.py` | Room/bed-level details and availability |
| `fetch_property_images` | `tools/broker/images.py` | Property image URLs |
| `fetch_landmarks` | `tools/broker/landmarks.py` | Landmark distances from property |
| `estimate_commute` | `tools/broker/landmarks.py` | Driving + transit commute estimation via OSRM |
| `fetch_nearby_places` | `tools/broker/nearby_places.py` | Nearby amenities via OSM Overpass API |
| `shortlist_property` | `tools/broker/shortlist.py` | Add to user's shortlist + update memory |
| `compare_properties` | `tools/broker/compare.py` | Structured side-by-side comparison of 2-3 properties |
| `fetch_properties_by_query` | `tools/broker/query_properties.py` | Query all brand properties by criteria |
| `web_search` | `tools/common/web_search.py` | Web intelligence for area info, brand info, general questions |

### Booking Agent

Handles all transactional operations: scheduling visits, calls, reservations, payments, KYC, cancellations, and rescheduling.

| Attribute | Detail |
|-----------|--------|
| **Model** | Claude Sonnet (`claude-sonnet-4-6`) — higher reliability for transactional operations |
| **Purpose** | Every action that changes state in the CRM or costs the user money |

**Tools:**

| Tool | Function | Purpose |
|------|----------|---------|
| `save_visit_time` | `tools/booking/schedule_visit.py` | Schedule a property visit + create CRM lead |
| `save_call_time` | `tools/booking/schedule_call.py` | Schedule a callback |
| `check_reserve_bed` | `tools/booking/reserve.py` | Check bed reservation eligibility |
| `reserve_bed` | `tools/booking/reserve.py` | Reserve a specific bed |
| `create_payment_link` | `tools/booking/payment.py` | Generate payment link (conditional on PAYMENT_REQUIRED flag) |
| `verify_payment` | `tools/booking/payment.py` | Verify payment status (conditional on PAYMENT_REQUIRED flag) |
| `initiate_kyc` | `tools/booking/kyc.py` | Start Aadhaar OTP verification (conditional on KYC_ENABLED flag) |
| `verify_kyc` | `tools/booking/kyc.py` | Complete KYC with OTP (conditional on KYC_ENABLED flag) |
| `cancel_booking` | `tools/booking/cancel.py` | Cancel an existing booking |
| `reschedule_booking` | `tools/booking/reschedule.py` | Reschedule a visit or booking |
| `save_phone_number` | `tools/booking/save_phone.py` | Capture phone number (web users only) |

### Profile Agent

Lightweight agent for user-specific queries that don't involve property search or booking.

| Attribute | Detail |
|-----------|--------|
| **Model** | Claude Sonnet (`claude-sonnet-4-6`) |
| **Purpose** | "What are my upcoming visits?" "Show me my shortlist" "What's my profile?" |

**Tools:**

| Tool | Function | Purpose |
|------|----------|---------|
| `fetch_profile_details` | `tools/profile/details.py` | User profile information |
| `get_scheduled_events` | `tools/profile/events.py` | Upcoming visits and calls |
| `get_shortlisted_properties` | `tools/profile/shortlisted.py` | User's shortlisted properties |

### Default Agent

Handles greetings, brand information queries, off-topic messages, and general help.

| Attribute | Detail |
|-----------|--------|
| **Model** | Claude Sonnet (`claude-sonnet-4-6`) |
| **Purpose** | First contact, brand questions, graceful handling of off-topic requests |

**Tools:**

| Tool | Function | Purpose |
|------|----------|---------|
| `brand_info` | `tools/default/brand_info.py` | Brand information with Redis cache (24h TTL) |
| `web_search` | `tools/common/web_search.py` | General web search for non-property queries |

---

## 7. The Broker Intelligence — How It Sells

This is the section that separates EazyPG Chat from every other property chatbot. The broker agent doesn't just search and display — it qualifies, scores, frames, and sells. Here's how.

### 7.1 Qualify Before Search

The bot NEVER searches before understanding what the user needs. Even when the user says "show me PGs in Andheri," the bot first calls `save_preferences` to record location, then asks one qualifying question (budget, sharing preference, or must-haves) before calling `search_properties`.

**Why this matters:** A search without preferences returns generic results. A search with preferences returns scored, ranked results where the top match is genuinely the best option for this specific user. The difference in conversion is dramatic — a 91% match score communicates "I found this specifically for you," while a list of 10 random properties communicates "here, figure it out yourself."

The `save_preferences` tool captures two categories:
- **Must-haves:** Deal-breakers. If a property doesn't have these, it gets a hard penalty in scoring. Examples: AC, female-only, meals included.
- **Nice-to-haves:** Bonuses. Properties with these rank higher but aren't excluded without them. Examples: gym, balcony, single room.

### 7.2 Match Scoring

Every search result is scored against the user's preferences using a weighted scoring system in `utils/scoring.py`:

| Factor | Weight | Logic |
|--------|--------|-------|
| Budget fit | High | Within budget = full score, 10-20% over = partial, >20% over = penalty |
| Distance | Medium | Closer to target location = higher score |
| Amenity match | Variable | Must-haves: hard penalty if missing. Nice-to-haves: bonus if present. |
| Property type match | Medium | Single/double/triple sharing alignment |
| Gender match | Binary | Wrong gender = excluded entirely |

**Fuzzy amenity matching** handles the real-world mess of naming conventions. "AC" matches "Air Conditioning." "WiFi" matches "Internet." "Meals" matches "Food" matches "Mess" matches "Tiffin." The alias map covers ~95% of real-world mismatches.

**Deal-breaker penalty** comes from cross-session user memory. If the user rejected a property because "no AC" in a previous conversation, AC becomes a hard filter in all future searches — even if the user doesn't mention it again.

### 7.3 Property Presentation Format

After scoring, the bot presents the top 5 results in a strict compact format:

```
**1. Sharma PG** — 91% match
📍 Andheri West, Mumbai · ₹9,000/mo · Female · 15 min walk from metro

**2. Zelter Heights** — 87% match
📍 Andheri West, Mumbai · ₹11,500/mo · Female · 8 min walk from metro

[... up to 5 properties]
```

Each property gets exactly 2 lines: name + match score, then location + rent + gender + proximity. No paragraphs. No amenity lists. No descriptions. The compact format is the listing.

After listing all 5 properties, the bot adds max 2 sentences of context and ONE next-step question. This is enforced in the `_base.md` skill prompt as a non-negotiable response format rule.

### 7.4 Objection Handling

The `selling.md` skill (8.8k characters, the largest skill file) encodes objection handling strategies:

| Objection | Bad Response | Bot Response |
|-----------|-------------|--------------|
| "That's too expensive" | "It's actually quite affordable for the area" | "I hear you. What would you be comfortable with? Let me check if there's something in that range — or I can break down what's included in the ₹11k so you can see the real cost." |
| "I've seen cheaper on NoBroker" | "Our properties are better" | "What did you like about those? I want to make sure I'm showing you the right kind of place." |
| "The area seems far" | "It's actually well-connected" | "Where's your office? Let me check the actual commute time — sometimes it's shorter than you'd think." |
| "I need to think about it" | "Sure, take your time" (dead lead) | "Totally fair. What's the main thing you're weighing? Sometimes talking it through helps." |

**Key pattern:** The bot always validates the objection FIRST ("I hear you"), then either reframes the value, redirects to a tool call (commute estimation, comparison), or asks a diagnostic question to understand the real obstacle.

### 7.5 Scarcity and Value Framing

The bot uses legitimate scarcity signals (not manufactured ones):

- **Availability:** "They only have 2 beds left in double sharing" — if the API confirms limited availability.
- **Value anchoring:** "Most people in Whitefield spend 4-5k on food alone — this includes meals, so you're actually saving money."
- **Social proof:** "This one fills up fast — three people booked visits last week" — if search volume data supports it.
- **Compensating weaknesses:** "No gym, but Gold's Gym is a 2-minute walk — saves you 3k/month on a home gym."

The bot never fabricates scarcity. The scarcity framing only applies when tool results provide genuine data points.

### 7.6 User Memory and Returning Users

When a returning user messages, the bot has full context from previous conversations:

```
{returning_user_context}:
- Previously searched: Andheri West, budget 10-12k
- Shortlisted: Sharma PG (but didn't schedule a visit)
- Deal-breakers: No AC, no meals
- Preferences: Near metro, female-only
```

This context is injected into the broker prompt via the `{returning_user_context}` template variable. The bot should reference this naturally — not dump it as a list, but weave it into the conversation:

> "Hey, welcome back! Last time you were looking at Sharma PG in Andheri — still interested, or has anything changed?"

### 7.7 Lead Scoring

The bot tracks implicit and explicit signals to score leads:

| Signal Type | Examples | Impact |
|-------------|----------|--------|
| **Explicit high-intent** | "I want to book a visit," asks about availability | High score increase |
| **Implicit high-intent** | Asks for details, requests comparison, asks about commute | Medium score increase |
| **Engagement** | Multi-turn conversation, returns after break | Score maintained or increased |
| **Low-intent** | "Just browsing," monosyllabic answers, no timeline | Low score |
| **Negative** | Stops responding, says "not interested" | Score decrease |

Lead scores are stored in Redis (`{uid}:user_memory`) and used for prioritizing follow-ups and reporting in the admin portal.

---

## 8. Conversation Flows — Complete Journeys

### Flow 1: New User — Greeting to Visit Booking

This is the golden path. A new user arrives, gets qualified, sees results, likes one, and schedules a visit.

```
                            ┌──────────────────────┐
                            │  User sends first    │
                            │  message             │
                            └──────────┬───────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │  Supervisor → default_agent  │
                        │  (greeting + brand info)     │
                        └──────────────┬──────────────┘
                                       │
                              User states need
                                       │
                        ┌──────────────▼──────────────┐
                        │  Supervisor → broker_agent   │
                        │  Skills: qualify_new, search  │
                        └──────────────┬──────────────┘
                                       │
                       ┌───────────────▼──────────────┐
                       │ save_preferences → search     │
                       │ → present top 5 with scores   │
                       └───────────────┬──────────────┘
                                       │
                              User asks for details
                                       │
                        ┌──────────────▼──────────────┐
                        │  broker_agent                │
                        │  Skills: details             │
                        │  → fetch_property_details    │
                        │  → fetch_property_images     │
                        └──────────────┬──────────────┘
                                       │
                           User: "Can I visit?"
                                       │
                        ┌──────────────▼──────────────┐
                        │  Supervisor → booking_agent  │
                        │  → save_visit_time           │
                        │  → _create_external_lead     │
                        └──────────────┬──────────────┘
                                       │
                              Visit confirmed!
```

**Example conversation (12 turns):**

```
User:   Hi, I'm looking for a PG in Mumbai

Bot:    Hey! I'm Tarini from OxOtel. Welcome!
        Which area in Mumbai are you looking at, and is this for work or college?

User:   Work — my office is in BKC

Bot:    BKC, nice! What's your monthly budget? And any must-haves — like AC,
        meals, or single room?

User:   Around 12-15k. AC is a must. Meals would be nice.

Bot:    Perfect — BKC, 12-15k, AC must-have, meals preferred. Let me search.
        [save_preferences → search_properties]

        Found 5 great options! Your top matches:

        **1. OxOtel BKC** — 94% match
        📍 BKC, Mumbai · ₹14,500/mo · Male · 5 min walk from BKC metro

        **2. OxOtel Bandra East** — 89% match
        📍 Bandra East · ₹12,000/mo · Male · 15 min by auto to BKC

        **3. Zelter Kurla West** — 85% match
        📍 Kurla West · ₹11,500/mo · Male · 20 min by metro to BKC

        **4. OxOtel Santacruz** — 82% match
        📍 Santacruz East · ₹13,000/mo · Male · 12 min by auto

        **5. Zelter Sion** — 78% match
        📍 Sion · ₹10,500/mo · Male · 25 min by metro

        OxOtel BKC is your best match — 5-minute walk to the metro.
        Want to see details and photos?

User:   Yeah, show me the first one

Bot:    [fetch_property_details → fetch_property_images]

        OxOtel BKC is a 50-bed co-living space with:
        - AC in every room, high-speed WiFi, 3 meals/day
        - Fully furnished: bed, wardrobe, study desk, chair
        - Housekeeping 3x/week, laundry service included
        - 24/7 security with CCTV

        Double sharing at ₹14,500/mo — with meals and laundry included,
        you're looking at saving 6-7k compared to a flat + eating out.

        They have 3 beds available right now. Want to schedule a visit
        this weekend?

User:   Saturday morning works

Bot:    [save_visit_time → creates CRM lead]

        Done! Your visit to OxOtel BKC is booked for Saturday at 10:00 AM.

        📍 Address: [full address]

        I'll send you the location pin closer to the date. See you there!
```

### Flow 2: Returning User — Memory-Driven Conversation

```
User:   Hey, I'm back. Still looking.

Bot:    Welcome back! Last time you were checking out OxOtel BKC and Zelter
        Kurla — you liked the BKC one but wanted to compare commute times.
        Still interested in those, or anything changed?

User:   Actually my budget went up a bit — I can do up to 16k now. Anything
        better come up?

Bot:    Nice, 16k opens up some great options! Let me search with the updated
        budget.
        [save_preferences (updated budget) → search_properties]

        With the higher budget, a new one popped up:

        **1. OxOtel BKC Premium** — 96% match
        📍 BKC · ₹15,500/mo · Male · Single occupancy with AC

        This wasn't in your range last time — single room, attached bathroom,
        and meals. That's basically a studio apartment experience at PG prices.

        Want me to compare this with the OxOtel BKC you saw before?

User:   Yeah, compare them

Bot:    [compare_properties → structured comparison table]

        Here's the side-by-side:

        |                 | OxOtel BKC        | OxOtel BKC Premium |
        |-----------------|-------------------|--------------------|
        | Rent            | ₹14,500/mo        | ₹15,500/mo         |
        | Sharing         | Double             | Single             |
        | Bathroom        | Shared             | Attached           |
        | AC              | ✅                 | ✅                  |
        | Meals           | ✅ 3/day           | ✅ 3/day            |
        | Match Score     | 94%                | 96%                |

        For ₹1,000 more you get your own room and bathroom — that's a solid
        upgrade. Want to visit both on Saturday?
```

### Flow 3: Booking Flow — Visit to Reservation

```
User:   I visited OxOtel BKC Premium yesterday. I want to reserve a bed.

Bot:    Great to hear! Let me check availability.
        [check_reserve_bed]

        Good news — they have beds available. I can reserve one for you right
        now. Which room type: the single with attached bathroom at ₹15,500?

User:   Yes, that one.

Bot:    [reserve_bed]

        Your bed at OxOtel BKC Premium is reserved! Here's your confirmation:

        ✅ Property: OxOtel BKC Premium
        🛏️ Room: Single, attached bathroom
        💰 Rent: ₹15,500/month

        The property team will reach out within 24 hours to finalize
        move-in details. Anything else you need?
```

### Flow 4: Objection Handling — Price to Visit

```
User:   14,500 for a PG?? That's way too much. I can get a flat for that.

Bot:    I hear you — that does sound like a lot upfront. But let me break
        it down, because the real comparison isn't rent vs rent.

        A flat at 14k in BKC means:
        - Deposit: 2-3 months (₹28-42k upfront)
        - Brokerage: 1 month (₹14k)
        - Food: ₹5-6k/month eating out
        - WiFi: ₹800/month
        - Electricity: ₹1,500-2,000/month (AC)
        - Cleaning: ₹2,000/month

        Real flat cost: ₹23-25k/month + ₹42-56k upfront.

        OxOtel at ₹14,500 includes everything — meals, WiFi, laundry,
        cleaning, furnished room. Zero deposit hassle.

        But if 14.5k is genuinely over budget, I have options at 10-12k
        that are still great. Want me to show you those?

User:   Okay, show me the cheaper ones

Bot:    [search_properties with adjusted budget]

        Here are your best matches under 12k:

        **1. Zelter Kurla West** — 88% match
        📍 Kurla West · ₹11,500/mo · Male · 20 min metro to BKC

        **2. Zelter Sion** — 83% match
        📍 Sion · ₹10,500/mo · Male · 25 min metro to BKC

        Zelter Kurla is solid — same amenities, just a slightly longer
        commute. Want me to check the exact travel time to your office?

User:   Yeah, how far is Kurla from BKC by metro?

Bot:    [estimate_commute]

        Kurla to BKC: 18 minutes by metro (direct line, no transfers).
        Station is a 5-minute walk from the PG.

        Total door-to-door: about 25 minutes. That's shorter than most
        people's commute in Mumbai.

        They have a slot this Saturday at 11 AM — want to check it out?

User:   Sure, book it.

Bot:    [save_visit_time]

        Done! Visit booked at Zelter Kurla West, Saturday at 11:00 AM.
        I'll send you the address and location pin. See you there!
```

---

## 9. WhatsApp Channel

### How Messages Flow

WhatsApp messages arrive via Meta's webhook infrastructure. The flow has evolved through three phases to handle multi-turn messaging correctly:

```
Meta sends POST /webhook/whatsapp
        │
        ▼
  [1. wamid dedup]
  Check: is wamid:{wamid} set in Redis?
  Yes → skip (duplicate delivery from Meta)
  No  → set wamid:{wamid} with 24h TTL, continue
        │
        ▼
  [2. Brand resolution]
  Look up brand config by phone_number_id
  (brand_wa:{phone_number_id} → brand config)
        │
        ▼
  [3. Queue message]
  RPUSH to {uid}:wa_queue
  Return 200 immediately (don't make Meta wait)
        │
        ▼
  [4. Drain task]
  If no drain task running for this user:
    Acquire lock: {uid}:wa_processing (SET NX, 2 min TTL)
    Wait 2 seconds (debounce — user may be typing more)
    Drain all messages from queue
    Concatenate into single pipeline run
        │
        ▼
  [5. Pipeline]
  run_pipeline(uid, concatenated_messages)
        │
        ▼
  [6. Check for new arrivals]
  If queue has new messages (arrived during processing):
    Set cancel_requested for current pipeline run
    Loop back to step 4
  Else:
    Release lock, done
```

**Why the debounce matters:** WhatsApp users typically send messages in bursts — "I need a PG" [enter] "near Andheri" [enter] "under 10k" [enter]. Without debouncing, the bot would process "I need a PG" alone, produce a confused response, then get "near Andheri" and try again. The 2-second debounce collects all burst messages and processes them as one.

**Why wamid dedup matters:** Meta sometimes delivers the same message multiple times (webhook retries on slow 200 responses). Without dedup, the bot would process the same message twice and send duplicate responses. The wamid (WhatsApp Message ID) is Meta's unique identifier — checking it prevents all duplicate processing.

### Message Format

Claude's markdown responses are parsed into WhatsApp-compatible parts by `core/message_parser.py`:

| Claude Output | WhatsApp Format |
|--------------|----------------|
| Plain text with **bold** | WhatsApp text with *bold* formatting |
| Property listings with image URLs | Interactive carousel cards (up to 5) |
| Comparison tables | Formatted text table |
| Status cards | Rich text with emoji indicators |
| Long responses | Split into multiple messages (WhatsApp has a 4096 character limit) |

### Carousel Cards

When the broker agent returns search results with image URLs, `channels/whatsapp.py:send_carousel()` formats them as interactive cards:

Each card shows:
- Property image (uploaded via Meta's media API)
- Property name
- Area, rent, sharing type
- "View Details" and "Schedule Visit" quick reply buttons

The carousel is limited to 5 cards — matching the bot's "show top 5 results" behavior.

### Account Values and Brand Config

WhatsApp channels carry brand configuration through Meta's `account_values` system. When a user messages a brand's WhatsApp number:
1. Meta delivers the message with `phone_number_id`
2. The webhook looks up `brand_wa:{phone_number_id}` in Redis
3. Returns the full brand config (pg_ids, brand name, WA credentials, etc.)
4. All subsequent operations are brand-scoped

---

## 10. Web Chat Channel

### SSE Streaming

The web chat uses Server-Sent Events (SSE) for real-time streaming. When the user sends a message:

```
POST /chat/stream
  Body: { user_id, message, brand_hash }
  Response: text/event-stream

Events:
  event: content_delta
  data: {"text": "partial response token..."}

  event: ui_parts
  data: {"parts": [...]}  (Generative UI components)

  event: done
  data: {}
```

The frontend (`src/stream.js`) processes `content_delta` events character-by-character, rendering them into the chat with a typing animation. The `ui_parts` event arrives after the text is complete and triggers rich component rendering.

### Interrupt-on-Send (Phase A)

When the user sends a new message while the bot is still responding, the frontend:
1. Aborts the current SSE connection via `AbortController`
2. Marks the partial response with an amber "interrupted" badge
3. Sends the new message immediately
4. The `requestCounter` pattern ensures only the latest request is active

This prevents the "ghost response" problem where old responses arrive after the user has moved on.

### Stop Button

A stop button appears while the bot is streaming. It calls `stopStream()` which aborts the SSE connection and marks the partial response as interrupted. The button uses a square icon (standard "stop" symbol) and appears between the microphone and send buttons.

### Deepgram Voice Input

The web widget supports voice input in English, Hindi, and Marathi via Deepgram Nova-3:

1. User clicks the microphone button
2. Frontend requests a temporary Deepgram token from `api/deepgram-token.js`
3. Opens a WebSocket to Deepgram's streaming API
4. Transcribes speech in real-time, displaying interim results
5. On silence detection (or user clicks stop), sends the final transcript as a message

Voice input is particularly important for Hindi/Marathi users who may be more comfortable speaking than typing in a non-native script.

### Chat History Persistence

Conversations are persisted in `localStorage` and restored on page reload. The `src/chat-history.js` module handles:
- `saveChatHistory()` — serializes the current conversation to localStorage on each message
- `loadChatHistory()` — restores the conversation from localStorage on page load

This means a user can close the tab and return later to see their full conversation history. The chat history key is scoped to the user ID, so multiple users on the same device don't see each other's conversations.

### Frontend Tech Stack

| Decision | Choice | Why |
|----------|--------|-----|
| Framework | None (vanilla JS) | Minimal bundle size, no framework overhead for a single-page chat widget |
| Bundler | Vite | Fast dev server, optimized production builds |
| Markdown | DOMPurify + marked | XSS-safe markdown parsing |
| Maps | Leaflet | Lightweight, open-source map rendering |
| Animations | CSS only | Skeleton loaders, slide-in carousels, stagger transitions — all CSS |
| Hosting | Vercel | Edge deployment, serverless API proxies, auto-deploy on push |

---

## 11. Generative UI System

The web chat doesn't just render text — it renders rich, interactive components driven entirely by the backend. The `core/ui_parts.py` module analyzes tool results and conversation context to generate UI components, which the frontend renders using a component registry.

### How It Works

```
Agent calls tools → Tool results returned
        │
        ▼
  generate_ui_parts(tool_results, context)
        │
  Analyzes: which tools were called?
  What data did they return?
  What's the conversation context?
        │
        ▼
  Returns: list of UI part objects
  [
    {type: "property_carousel", properties: [...]},
    {type: "quick_replies", options: [...]},
    {type: "expandable_sections", sections: [...]}
  ]
        │
        ▼
  Sent to frontend as SSE event: "ui_parts"
        │
        ▼
  Frontend: PART_RENDERERS[type](data) → DOM
```

### The 10 Component Types

| Type | Purpose | When Generated | Example |
|------|---------|----------------|---------|
| `text` | Formatted text block | Always (fallback) | Markdown-rendered response text |
| `property_carousel` | Horizontal scrolling property cards | After `search_properties` returns results | 5 cards with images, prices, match scores, amenity pills |
| `comparison_table` | Side-by-side property comparison | After `compare_properties` | 2-3 column table with rent, amenities, distance |
| `quick_replies` | Contextual action chips | After most responses | "Show details," "Compare these," "Book a visit" |
| `action_buttons` | Primary action buttons | After property details or booking confirmation | "Schedule Visit," "Shortlist," "See on Map" |
| `status_card` | Status indicator card (success/info/warning) | After booking/payment actions | Green card: "Visit booked for Saturday 10 AM" |
| `image_gallery` | Grid of property images | After `fetch_property_images` | 6-8 images with lightbox on click |
| `confirmation_card` | Booking/reservation confirmation | After `save_visit_time` or `reserve_bed` | Card with date, time, address, celebration animation |
| `error_card` | Error state with retry action | On tool failures | "Couldn't load property details. Tap to retry." |
| `expandable_sections` | Accordion-style detail sections | After `fetch_property_details` | House Rules, FAQs, About sections that expand on tap |

### Quick Replies Intelligence

Quick replies are not static — they're contextually generated based on the conversation state and the properties currently being discussed:

```
After search results:
  → "Show details on #1"
  → "Compare top 2"
  → "Show more options"

After property details:
  → "Book a visit"
  → "See images"
  → "How far from metro?"

After visit booking:
  → "Show other properties"
  → "Cancel visit"
  → "That's all, thanks!"

After objection:
  → "Show cheaper options"
  → "Compare with others"
```

The `src/quick-replies.js` module extracts property names from the bot's response and generates contextually relevant chips. It even detects when specific properties are mentioned and offers property-specific actions.

### Property Cards

Each property card in the carousel includes:
- Property image (with fallback placeholder)
- Property name and area
- Rent in bold
- Match score badge (color-coded: green >85%, yellow 70-85%, gray <70%)
- Amenity pills (top 4 amenities as small tags)
- Slide-in animation on render

---

## 12. Multi-Brand White-Label System

### The Problem

EazyPG Chat serves multiple property brands. OxOtel has different properties, different branding, different WhatsApp numbers, and different admin teams than Stanza or Zelter. Each brand must see ONLY its own data — its own properties, its own conversations, its own analytics.

### How Brand Isolation Works

```
Brand API Key: "OxOtel1234"
        │
        ▼
  brand_hash = sha256("OxOtel1234")[:16]
  → "a3f8b2c1d4e5f607"
        │
        ▼
  ALL data namespaced under this hash:

  Redis:
    brand_config:{hash}        → brand configuration
    active_users:{hash}        → brand's active users
    funnel:{hash}:{day}        → brand's funnel events
    agent_usage:{hash}:{day}   → brand's agent usage
    brand_flags:{hash}         → brand's feature flags
    {uid}:{hash}:human_mode    → brand-scoped takeover

  PostgreSQL:
    booking_messages.brand_hash = {hash}
    leads.brand_hash = {hash}
```

**The raw API key is never stored.** All lookups use the hash. This means even if Redis is compromised, API keys cannot be recovered.

### Brand Configuration

Each brand config stored in Redis contains:

| Field | Purpose | Example |
|-------|---------|---------|
| `brand_name` | Bot introduces itself as this brand | "OxOtel" |
| `pg_ids` | Property IDs this brand owns | ["PG001", "PG002", "PG003"] |
| `cities` | Cities this brand operates in | ["Mumbai", "Bangalore"] |
| `areas` | Specific areas | ["Andheri", "BKC", "Whitefield"] |
| `wa_phone_number_id` | Meta WhatsApp phone number ID | "1234567890" |
| `wa_access_token` | Meta API access token | "EAA..." |
| `brand_link_token` | UUID for public chatbot URL | "f47ac10b-58cc-..." |
| `brand_hash` | The SHA-256 hash itself | "a3f8b2c1d4e5f607" |

### Public Chatbot URL

Each brand gets a public chatbot URL: `https://eazypg-chat.vercel.app?brand={brand_link_token}`

The frontend calls `GET /brand-config?token={uuid}` (public, no auth) to fetch the brand's safe fields (pg_ids, brand_name, cities, areas, brand_hash). This initializes the widget with the correct brand identity.

### Auto-Seeding on Startup

Known brands (OxOtel, Stanza, Zelter) are auto-seeded in `main.py`'s lifespan handler. This means a fresh deployment immediately has all brand configs available — no manual setup needed.

---

## 13. Feature Flags

Three feature flags control major system behaviors. Each has a global default and can be overridden per-brand.

### KYC_ENABLED (default: false)

When enabled, the booking flow requires Aadhaar verification before reservation:
1. `initiate_kyc` sends an OTP to the user's Aadhaar-linked phone
2. User provides the OTP
3. `verify_kyc` validates the OTP
4. Only then can `reserve_bed` proceed

When disabled (current default), the reservation flow skips KYC entirely. The KYC tools are not even registered in the tool registry, preventing the agent from calling them.

### PAYMENT_REQUIRED (default: false)

When enabled, reservation requires payment:
1. `create_payment_link` generates a payment URL
2. User completes payment
3. `verify_payment` confirms payment status
4. Only then can `reserve_bed` proceed

When disabled (current default), reservation goes directly to `reserve_bed` without payment. The booking prompt dynamically adjusts its instructions via the `{kyc_reservation_flow}` template variable.

### DYNAMIC_SKILLS_ENABLED (default: true)

When enabled (current default), the broker agent uses the dynamic skill system:
- Supervisor detects skills per turn
- Only relevant skill files loaded
- Tools filtered to match loaded skills

When disabled, the broker agent falls back to the legacy monolithic prompt (580+ lines, all skills in one blob). This is the instant rollback mechanism — if the dynamic skill system misbehaves, flip this flag and the entire system reverts.

### How Flags Affect the System

```
Feature Flag
    │
    ├── Prompt level (immediate effect)
    │   format_prompt() reads flags and injects different template values:
    │   - {kyc_reservation_flow}: 4 different instruction variants
    │   - {reserve_option}: dynamic tool description
    │   - {token_value_line}: scarcity text or empty
    │   - {post_visit_reserve_cta}: different CTA text
    │
    └── Tool level (requires restart)
        init_registry() conditionally registers tools:
        - KYC_ENABLED=false → KYC tools not registered
        - PAYMENT_REQUIRED=false → payment tools not registered
        The agent literally cannot call tools that aren't registered.
```

**Important limitation:** Tool registration happens at import time. Toggling a flag at runtime changes the prompt immediately (the agent gets different instructions) but tool availability only changes on server restart. This is a known limitation, shared with the KYC flag since launch.

### Per-Brand Overrides

Each brand can override global defaults via `POST /admin/flags`:
```json
{"key": "PAYMENT_REQUIRED", "value": true}
```

This sets `brand_flags:{brand_hash}` in Redis. When the pipeline runs, it calls `get_effective_flags(brand_hash)` which merges brand overrides over global defaults. A brand can require payment while others don't, or enable KYC independently.

---

## 14. Human Takeover System

### Why It Exists

AI handles 95% of conversations well. For the other 5% — complex negotiations, complaints, users who explicitly ask for a human, high-value leads that need personal attention — a human operator needs to take over seamlessly.

### How It Works

```
Admin Portal                    Backend                     User
    │                              │                          │
    │  POST /admin/{uid}/takeover  │                          │
    │ ───────────────────────────► │                          │
    │                              │  Set human_mode:         │
    │                              │  {uid}:{brand_hash}:     │
    │                              │  human_mode = active     │
    │                              │                          │
    │                              │  Pipeline checks         │
    │                              │  human_mode on every     │
    │                              │  message → skips AI      │
    │                              │                          │
    │  POST /admin/{uid}/message   │                          │
    │  "Hi, this is Priya from     │  Send via WhatsApp ───► │
    │   OxOtel. How can I help?"   │  (channels/whatsapp.py)  │
    │                              │                          │
    │  POST /admin/{uid}/resume    │                          │
    │ ───────────────────────────► │                          │
    │                              │  Clear human_mode        │
    │                              │  Bot resumes responding  │
```

### Brand-Scoped Takeover

Human mode is scoped to `{uid}:{brand_hash}:human_mode` — a brand can only take over conversations that belong to its users. The backend verifies ownership before allowing takeover.

There's also a legacy global key `{uid}:human_mode` that serves as a fallback. When `get_human_mode(uid, brand_hash)` is called, it checks the brand-scoped key first, then falls back to the global key. This ensures backward compatibility with conversations that were taken over before the brand-scoping migration.

### Auto-Resume on Admin Message

When an admin sends a message via `POST /admin/{uid}/message`, the system automatically clears human mode after the message is sent. This means the human only needs to explicitly resume if they want to return control without sending a message.

---

## 15. Dynamic Skill System

### The Problem

The original broker agent had a single system prompt — 580+ lines, covering every scenario from new user greeting to objection handling to commute estimation. This caused three problems:

1. **Token cost.** Every broker turn sent 580 lines of instructions, even if the user just said "show me images." At Haiku pricing, this added up.

2. **Attention dilution.** With 580 lines of instructions, the model sometimes followed the wrong section. A user asking for details would trigger the search formatting rules because both sections were in the prompt.

3. **Update risk.** Editing one section could break another. The prompt was a monolith — you couldn't touch the comparison section without risking the search section.

### The Solution: 12 Skill Files

The monolithic prompt was decomposed into 12 separate Markdown files with YAML frontmatter:

| Skill File | Size | Purpose |
|-----------|------|---------|
| `_base.md` | 3.6k | Always loaded. Identity, response format, never-rules. |
| `qualify_new.md` | 2.0k | New user qualifying flow (2 examples) |
| `qualify_returning.md` | 1.4k | Returning user warm greeting (2 examples) |
| `search.md` | 5.4k | save_preferences -> search -> present results (4 examples) |
| `details.md` | 2.2k | Property details, images, rooms (3 examples) |
| `compare.md` | 2.5k | Side-by-side comparison + recommendation (2 examples) |
| `commute.md` | 2.9k | Commute estimation via driving + transit (2 examples) |
| `shortlist.md` | 0.9k | Shortlist workflow (2 examples) |
| `show_more.md` | 1.7k | Show next batch / expand radius (2 examples) |
| `selling.md` | 8.8k | Objection handling, scarcity, value framing (3 examples) |
| `web_search.md` | 2.6k | Web search rules (2 examples) |
| `learning.md` | 2.4k | Implicit feedback, deal-breakers (2 examples) |

### How Skills Are Selected

```
User: "How far is OxOtel BKC from Andheri station?"
        │
        ▼
  Supervisor classifies:
  {agent: "broker", skills: ["commute"]}
        │
        ▼
  build_skill_prompt(["commute"]):
    → Load _base.md (always)
    → Load commute.md (selected skill)
    → Skip other 10 skill files
        │
        ▼
  get_tools_for_skills(["commute"]):
    → ALWAYS_TOOLS (save_preferences, web_search)
    → commute tools (estimate_commute, fetch_landmarks)
    → Skip search, details, compare, shortlist tools
```

**Result:** Instead of sending 580 lines + 12 tool schemas, the system sends ~150 lines + 4 tool schemas. The model is more focused, responses are better, and token costs drop 60-70%.

### Skill-to-Tool Mapping

The `skills/skill_map.py` module maps each skill to its required tools:

| Skill | Required Tools |
|-------|---------------|
| `qualify_new` | save_preferences |
| `qualify_returning` | save_preferences |
| `search` | save_preferences, search_properties |
| `details` | fetch_property_details, fetch_property_images, fetch_room_details |
| `compare` | compare_properties, fetch_property_details, fetch_room_details |
| `commute` | estimate_commute, fetch_landmarks |
| `shortlist` | shortlist_property |
| `show_more` | search_properties |
| `selling` | search_properties, save_preferences |
| `web_search` | web_search |
| `learning` | save_preferences |

**ALWAYS_TOOLS** (registered regardless of skills): `save_preferences`, `web_search`

### Graceful Fallback

If the agent calls a tool that wasn't in its filtered set (skill miss), the `ToolExecutor` expands to the full broker tool set and retries. This is logged to Redis (`skill_misses:{day}` and `skill_misses:{brand_hash}:{day}`) for monitoring, but the user never sees an error.

### Hot-Reload

Skill files are loaded from disk with a 30-second memory cache. Editing a skill file on disk takes effect within 30 seconds — no server restart required. This enables rapid iteration on prompts without downtime.

---

## 16. Conversation Memory & Summarization

### Three Layers of Memory

The system maintains three layers of conversation memory, each with a different scope and persistence:

| Layer | Storage | TTL | Purpose |
|-------|---------|-----|---------|
| **Conversation history** | Redis: `{uid}:conversation` | 24 hours | Current session messages (user + assistant + tool calls) |
| **User memory** | Redis: `{uid}:user_memory` | No TTL (persistent) | Cross-session preferences, deal-breakers, past interactions, lead score |
| **Message log** | PostgreSQL: `booking_messages` | Permanent | Audit trail, analytics, admin conversation viewer |

### Conversation History

Every message in a conversation is stored as a JSON array in Redis. Each entry includes the role (user/assistant/tool), content, and timestamp. The history is loaded at the start of every pipeline run and appended to the agent's message array, giving the model full context of the current conversation.

**24-hour TTL** means conversations reset after a day of inactivity. This is intentional — PG searches are time-bounded activities. A user who returns after 3 days is essentially starting a new search, and stale context would confuse the model.

### User Memory

User memory is the bot's long-term brain. It persists indefinitely and stores:

| Field | Example | Used For |
|-------|---------|----------|
| `location_preference` | "Andheri West" | Pre-populating search queries |
| `budget` | "10000-12000" | Filtering results |
| `sharing_preference` | "double" | Filtering results |
| `must_haves` | ["AC", "meals"] | Match scoring (hard penalty if missing) |
| `deal_breakers` | ["no AC", "far from metro"] | Cross-session filtering |
| `shortlisted_properties` | ["PG001", "PG003"] | Returning user context |
| `past_visits` | [{"pg_id": "PG001", "date": "2026-03-10"}] | Returning user context |
| `lead_score` | 72 | Follow-up prioritization |

This memory is injected into the agent's prompt via the `{returning_user_context}` template variable. When a returning user messages, the bot knows their preferences, deal-breakers, and history before they say a word.

### Summarization

When a conversation exceeds 30 messages, `core/summarizer.py` kicks in:

1. Takes the full conversation history
2. Keeps the 10 most recent messages as-is
3. Summarizes everything before that into a concise summary
4. Replaces the old messages with: `[summary] + [10 recent messages]`

This keeps the context window manageable while preserving the most important information. The summarization prompt includes brand context when a `brand_hash` is available, ensuring the summary references the correct brand.

The summary is not a lossy compression — it explicitly preserves:
- User preferences and deal-breakers mentioned
- Properties discussed and user reactions to them
- Booking actions taken
- Outstanding questions or objections

### How Memory Flows Through the System

```
User sends message
        │
        ▼
  Load conversation history (Redis, 24h TTL)
  Load user memory (Redis, persistent)
        │
        ▼
  Build system prompt:
    format_prompt(
      returning_user_context = user_memory.summary(),
      language_directive = detected_language,
      ...
    )
        │
        ▼
  Agent sees full context:
    [system prompt with user memory]
    [conversation history or summary + recent]
    [new user message]
        │
        ▼
  Agent responds + calls tools
  Tools may update user memory:
    - save_preferences → updates preferences
    - shortlist_property → adds to shortlist
    - Learning skill → detects deal-breakers
        │
        ▼
  Save conversation (append new messages)
  Maybe summarize (if >30 messages)
  Brand-tag user (if brand_hash available)
```

---

## 17. Technology Stack

### Backend

| Component | Technology | Version/Detail |
|-----------|-----------|----------------|
| **Language** | Python | 3.11 |
| **Framework** | FastAPI | Async, ASGI, Pydantic validation |
| **AI SDK** | Anthropic Python SDK | Official SDK, streaming support |
| **Redis client** | redis-py | Async connection pool |
| **PostgreSQL client** | asyncpg | Async, connection pool |
| **HTTP client** | httpx | Async, used for Rentok API + external calls |
| **Settings** | Pydantic Settings | Environment-based configuration |

### Frontend

| Component | Technology | Detail |
|-----------|-----------|--------|
| **Language** | Vanilla JavaScript | No framework — intentional choice for bundle size |
| **Bundler** | Vite | Dev server + production build |
| **Markdown** | marked + DOMPurify | XSS-safe markdown rendering |
| **Maps** | Leaflet | Property location maps |
| **Voice** | Deepgram Nova-3 | Streaming voice-to-text (en/hi/mr) |
| **Hosting** | Vercel | Edge deployment, serverless proxies |

### AI Models

| Agent | Model | ID | Why |
|-------|-------|----|-----|
| Supervisor | Haiku | `claude-haiku-4-5-20251001` | Fast classification (200-400ms), low cost |
| Broker | Haiku | `claude-haiku-4-5-20251001` | Cost efficiency for high-volume property conversations |
| Booking | Sonnet | `claude-sonnet-4-6` | Higher reliability for transactional operations |
| Profile | Sonnet | `claude-sonnet-4-6` | Consistency on user data queries |
| Default | Sonnet | `claude-sonnet-4-6` | Quality on brand representation |

**Why Haiku for the broker:** The broker agent handles the highest message volume — property search, qualifying, details, comparisons. Haiku at ~$0.25/M input tokens vs Sonnet at ~$3/M makes a 12x cost difference. For property conversations (where the facts come from tool calls, not the model's knowledge), Haiku's quality is sufficient.

**Why Sonnet for booking:** Booking operations change state in the CRM. A missed tool call or incorrect parameter means a lost reservation. Sonnet's higher reliability on tool use justifies the cost premium for these lower-volume, higher-stakes operations.

### Infrastructure

| Component | Service | Detail |
|-----------|---------|--------|
| **Backend** | Render | Auto-deploy from `main` branch, `https://claude-booking-bot.onrender.com` |
| **Redis** | Render | Managed Redis instance |
| **PostgreSQL** | Render | Managed PostgreSQL |
| **Frontend (chat)** | Vercel | `https://eazypg-chat.vercel.app` |
| **Admin portal** | Vercel | Separate project, `eazypg-admin/` |

### External APIs

| API | Purpose | Used By |
|-----|---------|---------|
| **Rentok API** (`apiv2.rentok.com`) | Property data, bookings, leads, KYC | All broker and booking tools |
| **Meta WhatsApp API** | Send/receive WhatsApp messages | `channels/whatsapp.py` |
| **Interakt API** | Alternative WhatsApp delivery | `channels/whatsapp.py` (dual-support) |
| **OSRM** | Driving/transit route calculation | `tools/broker/landmarks.py` |
| **OSM Overpass** | Nearby places/amenities | `tools/broker/nearby_places.py` |
| **Deepgram** | Voice-to-text (web widget) | `src/voice-input.js`, `api/deepgram-token.js` |
| **Tavily** | Web search (optional) | `tools/common/web_search.py` |

---

## 18. Data Model

### Redis Key Schema

**Conversation & User State:**

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `{uid}:conversation` | List | 24h | Conversation message history |
| `{uid}:user_memory` | JSON | None | Persistent user preferences, deal-breakers, lead score |
| `{uid}:last_agent` | String | 24h | Last-used agent (for routing stickiness) |
| `{uid}:brand_hash` | String | None | User-to-brand mapping |
| `{uid}:session_cost` | Hash | 7 days | Current session token usage and cost |

**Multi-Turn Message Handling:**

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `wamid:{wamid}` | String | 24h | WhatsApp message dedup |
| `{uid}:wa_queue` | List | 5 min | Pending WhatsApp messages |
| `{uid}:wa_processing` | String | 2 min | Per-user drain task lock |
| `{uid}:cancel_requested` | String | 30s | Pipeline cancellation signal |

**Brand Configuration:**

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `brand_config:{hash}` | JSON | None | Full brand configuration |
| `brand_wa:{phone_number_id}` | JSON | None | WhatsApp phone -> brand reverse lookup |
| `brand_token:{uuid}` | String | None | Public link token -> brand hash |
| `brand_flags:{hash}` | JSON | None | Per-brand feature flag overrides |

**Property Cache:**

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `property_info:{pg_id}` | JSON | 1h | Cached property details |
| `property_images:{pg_id}` | JSON | 1h | Cached property images |
| `{uid}:last_search` | JSON | 24h | Last search results for "show more" |

**Admin & Takeover:**

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `active_users` | Sorted Set | None | Global active user list (member=uid, score=timestamp) |
| `active_users:{hash}` | Sorted Set | None | Per-brand active user list |
| `{uid}:{hash}:human_mode` | Hash | None | Brand-scoped human takeover state |
| `{uid}:human_mode` | Hash | None | Legacy global takeover (fallback) |

**Analytics (all dual-written: global + brand-scoped):**

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `funnel:{day}` / `funnel:{hash}:{day}` | Hash | 90 days | Funnel stage counts |
| `agent_usage:{day}` / `agent_usage:{hash}:{day}` | Hash | 90 days | Agent invocation counts |
| `skill_usage:{day}` / `skill_usage:{hash}:{day}` | Hash | 90 days | Skill usage counts |
| `skill_misses:{day}` / `skill_misses:{hash}:{day}` | Hash | 90 days | Skill miss counts (fallback events) |
| `agent_cost:{day}` / `agent_cost:{hash}:{day}` | Hash | 90 days | Per-agent token cost |
| `daily_cost:{day}` / `daily_cost:{hash}:{day}` | Hash | 90 days | Total daily cost |
| `feedback:counts` / `feedback:counts:{hash}` | Hash | None | Thumbs up/down per agent |

**Other:**

| Key Pattern | Type | TTL | Purpose |
|-------------|------|-----|---------|
| `web_intel:{category}:{hash}` | JSON | 24h | Cached web search results |
| `{uid}:rate_limit:{window}` | Sorted Set | Varies | Sliding window rate limit entries |
| `payment:{uid}:{pg_id}` | JSON | 1h | Active payment request dedup |

### PostgreSQL Tables

**booking_messages:**

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL | Primary key |
| user_id | VARCHAR | User identifier |
| role | VARCHAR | "user", "assistant", or "tool" |
| content | TEXT | Message content |
| brand_hash | VARCHAR(16) | Brand isolation |
| created_at | TIMESTAMP | Message timestamp |

**leads:**

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL | Primary key |
| user_id | VARCHAR | User identifier |
| property_id | VARCHAR | Property the lead is for |
| stage | VARCHAR | Funnel stage (inquiry, visit_scheduled, visited, booked) |
| score | INTEGER | Lead score |
| brand_hash | VARCHAR(16) | Brand isolation |
| created_at | TIMESTAMP | Lead creation time |
| updated_at | TIMESTAMP | Last update |

**property_documents:**

| Column | Type | Purpose |
|--------|------|---------|
| id | SERIAL | Primary key |
| property_id | VARCHAR | Associated property |
| filename | VARCHAR | Original filename |
| file_type | VARCHAR | File MIME type |
| content_text | TEXT | Extracted text content (for KB injection) |
| size_bytes | INTEGER | File size |
| uploaded_at | TIMESTAMP | Upload time |

### Rentok API Endpoints

| Endpoint | Method | Used By | Purpose |
|----------|--------|---------|---------|
| `/search` | GET | `search_properties` | Property search with geocoding |
| `/property/{id}` | GET | `fetch_property_details` | Property details |
| `/property/{id}/rooms` | GET | `fetch_room_details` | Room and bed details |
| `/property/{id}/images` | GET | `fetch_property_images` | Property images |
| `/booking/visit` | POST | `save_visit_time` | Schedule a visit |
| `/booking/call` | POST | `save_call_time` | Schedule a callback |
| `/booking/reserve` | POST | `reserve_bed` | Reserve a bed |
| `/booking/cancel` | POST | `cancel_booking` | Cancel a booking |
| `/booking/reschedule` | POST | `reschedule_booking` | Reschedule a booking |
| `/payment/create` | POST | `create_payment_link` | Generate payment link |
| `/payment/verify` | GET | `verify_payment` | Check payment status |
| `/kyc/initiate` | POST | `initiate_kyc` | Start Aadhaar verification |
| `/kyc/verify` | POST | `verify_kyc` | Verify Aadhaar OTP |
| `/leads/add` | POST | `_create_external_lead` | Create CRM lead |
| `/brand/info` | GET | `brand_info` | Brand information |

---

## 19. Analytics & Funnel Tracking

### Funnel Stages

The system tracks users through a conversion funnel:

```
search → detail → shortlist → visit_scheduled → visited → booked
  │         │         │              │              │         │
  │         │         │              │              │         └── Tenant acquired
  │         │         │              │              └── Visit happened (CRM confirmed)
  │         │         │              └── Visit booked via bot
  │         │         └── User shortlisted a property
  │         └── User viewed property details
  └── User performed a property search
```

Each stage transition is tracked via `track_funnel(event, brand_hash)` which increments both the global counter (`funnel:{day}`) and the brand-scoped counter (`funnel:{brand_hash}:{day}`).

### Agent Usage

Every agent invocation is tracked: which agent was called, how many turns it ran, and how many tool calls it made. This data answers questions like:
- What percentage of messages go to the broker vs booking agent?
- Is the supervisor routing correctly?
- Are there agents being invoked unnecessarily?

### Skill Usage

For the broker agent specifically, each skill activation is tracked. This reveals:
- Which skills are most frequently needed (search dominates, followed by details)
- Which skills are rarely used (candidates for consolidation)
- Skill miss rate (how often the tool executor falls back to the full tool set)

### Cost Tracking

Token usage is tracked per-agent per-day:
- Input tokens (prompt + conversation history)
- Output tokens (model response)
- Estimated cost in USD

This enables cost optimization: if the broker agent's input tokens are unexpectedly high, it suggests the dynamic skill system isn't filtering effectively.

### Feedback

Users can give thumbs up/down on any bot response. Feedback is stored per-agent, enabling targeted prompt improvements:
- "Booking agent gets 90% thumbs up — it's working well"
- "Broker agent gets 72% thumbs up on search but 55% on objection handling — selling.md needs work"

### Dual-Write Pattern

ALL analytics are dual-written to both global and brand-scoped keys. This enables:
- **Admin portal** reads brand-scoped keys (each brand sees only its own data)
- **Debug/engineering** reads global keys (cross-brand overview)
- **No fan-out queries needed** — both views are pre-computed at write time

---

## 20. Rate Limiting & Safety

### Rate Limits

| Limit | Window | Purpose |
|-------|--------|---------|
| 6 messages per minute per user | Sliding window | Prevent spam/abuse from individual users |
| 30 messages per hour per user | Sliding window | Prevent sustained abuse |
| 100 messages per minute global | Sliding window | Protect backend from traffic spikes |

Rate limits use a sliding window implementation in `core/rate_limiter.py`. Each message is recorded in a Redis sorted set with the timestamp as the score. When a new message arrives, the window is trimmed and the count is checked. If exceeded, the bot returns a polite "you're sending messages too fast" response.

### Tool Call Limits

Each agent run is limited to 15 tool call iterations. This prevents infinite loops where the model keeps calling tools without converging on a response. In practice, most conversations use 1-3 tool calls per turn. The limit is a safety net, not a constraint.

### Web Search Limit

Web search (via Tavily) is limited to 3 calls per conversation. This prevents cost overruns — web search is the most expensive tool call (external API cost + latency). The limit is tracked in the conversation context and enforced by the tool executor.

### Commute Estimation Timeout

The `estimate_commute` tool has a 30-second aggregate timeout across all OSRM API calls. If geocoding + routing takes longer than 30 seconds, the tool returns a partial result with whatever data it has. This prevents the "infinite thinking" problem where the bot appears unresponsive because an external API is slow.

### XSS Protection

The web frontend uses DOMPurify + marked for all markdown rendering. Raw HTML from the bot response is sanitized before insertion into the DOM. This prevents XSS attacks if the model somehow generates malicious HTML (which it shouldn't, but defense in depth).

### No Secrets in Frontend

The Vercel frontend never touches backend API keys directly. All API calls go through Vercel serverless proxies (`api/*.js`) which add authentication headers server-side. The only secret in the frontend is the Deepgram temporary token, which is generated on-demand with short TTL.

### Vague Destination Blocklist

The commute estimation tool rejects vague destinations like "my office" or "work" — it requires a specific address or landmark. This prevents the tool from making up distances based on incomplete information.

---

## 21. Success Metrics

### Response Quality

| Metric | Current | Target | How Measured |
|--------|---------|--------|-------------|
| Routing accuracy | ~95% | >97% | Supervisor routes to correct agent (manual audit of samples) |
| Tool call success rate | ~92% | >95% | Tools return valid results / total tool calls |
| E2E test pass rate | 35/35 (100%) | 100% | Playwright e2e test suite |
| Tool unit test pass rate | 16/16 (100%) | 100% | Comprehensive tool test suite |
| Stress test pass rate | 13 PASS / 5 WARN / 2 FAIL | <2 FAIL | 20-scenario broker intelligence regression suite |

### User Engagement

| Metric | What It Measures | Tracked In |
|--------|-----------------|------------|
| Messages per session | Conversation depth — are users engaging or bouncing? | Redis conversation length |
| Return rate | Users who come back after first conversation | User memory existence check |
| Session duration | How long users spend in conversation | Timestamp delta (first to last message) |
| Language distribution | Which languages are being used | Language detection on each message |

### Conversion Funnel

| Stage Transition | What It Means | Target |
|-----------------|---------------|--------|
| Search -> Detail | User found something interesting | >40% |
| Detail -> Shortlist | User is seriously considering | >25% |
| Shortlist -> Visit | User committed to action | >15% |
| Visit -> Booking | Site visit converted to deal | >8% (industry benchmark) |

### Cost Efficiency

| Metric | Current | Notes |
|--------|---------|-------|
| Cost per message (broker) | ~$0.002-0.004 | Haiku pricing, dynamic skills reduce this |
| Cost per message (booking) | ~$0.008-0.015 | Sonnet pricing, lower volume |
| Cost per conversation (average) | ~$0.02-0.05 | 15-20 turns typical |
| Daily cost tracking | Per-brand, per-agent | Redis `daily_cost:{day}` keys |

### Feedback Sentiment

| Agent | Thumbs Up Rate | Notes |
|-------|---------------|-------|
| Broker | ~72-80% | Lower on objection handling, higher on search |
| Booking | ~85-90% | High satisfaction on successful bookings |
| Default | ~90% | Greeting quality is high |
| Profile | ~88% | Simple queries, reliable answers |

---

## 22. Known Limitations & Future Work

### Known Limitations

**1. Haiku stochasticity on phrasing (S04/S08 stress tests)**

The broker agent (Haiku) occasionally produces different phrasing patterns across runs. Stress test scenarios S04 (Hinglish handling) and S08 (CTA phrasing) intermittently fail because Haiku's exact wording varies. These pass on retry — the issue is consistency, not capability. This is inherent to LLM inference and not fixable without deterministic decoding (which degrades quality).

**2. Tool set rebuilt only on restart**

Feature flags (KYC_ENABLED, PAYMENT_REQUIRED) control which tools are registered. But tool registration happens at import time via `init_registry()`. Toggling a flag at runtime changes the prompt immediately (the agent gets different instructions), but the tool set only changes on server restart. This means a brand that enables payments at runtime will have the agent tell users about payment but be unable to actually create payment links until the server restarts.

**3. Conversation history 24-hour TTL**

Conversations in Redis expire after 24 hours of inactivity. User memory persists (preferences, deal-breakers), but the actual conversation thread is lost. A user returning after 2 days sees a fresh conversation — they can't say "that property you showed me yesterday." The bot remembers their preferences but not the specific properties discussed.

This is intentional (PG search is time-bounded) but occasionally frustrating for users in longer decision cycles.

**4. Single-region deployment**

The backend runs on Render US. Redis and PostgreSQL are co-located. For Indian users (the primary audience), this adds ~200-300ms latency on every request. The frontend is on Vercel Edge (global), but SSE streams still connect to the US backend. Moving to an India-region deployment would reduce P95 latency by 40-60%.

**5. No offline/push notification support**

The web widget requires an active browser tab. There are no push notifications for follow-ups, no email summaries, no out-of-band communication on the web channel. WhatsApp handles this naturally (users get notifications), but web-only users can go dark without any re-engagement mechanism.

**6. Phone gate bypass via summarization**

A known bug (P7): When the summarizer compresses conversation history, it sometimes includes "phone confirmed" in the summary even when the user's memory has `phone_collected=false`. This allows the booking flow to proceed without a phone number on web, which breaks visit scheduling (no phone to send SMS confirmation to).

**7. Text concatenation on streaming responses**

When the model produces text before and after a tool call, the pre-tool preamble can be concatenated with the post-tool text without a space ("right away!Great news"). This is a streaming assembly issue in the SSE handler.

### Future Work

**1. Voice Agent Integration (PRD exists)**

The voice agent (documented in `PRD-VOICE-AGENT.md`) will add telephony as a third channel. The existing pipeline is transport-agnostic — voice becomes another caller of `run_pipeline()` with voice-optimized prompts. This is the next major product expansion.

**2. India-Region Deployment**

Move backend to Mumbai/India cloud region. Estimated 40-60% latency reduction. Requires Render or alternative provider with India presence.

**3. Persistent Conversation History**

Move conversation history from Redis (24h TTL) to PostgreSQL (permanent). Enable "show me what we discussed last week" queries. This requires conversation search/retrieval infrastructure.

**4. Proactive Follow-Up System**

Automated follow-ups for users who searched but didn't book a visit. The `POST /cron/follow-ups` endpoint exists but the logic is minimal. A full follow-up system would:
- Score users by lead temperature
- Send WhatsApp messages at optimal times
- Reference specific properties they viewed
- Track follow-up response rates

**5. Multi-Language Prompt Optimization**

Currently, all prompts are in English and the model code-switches based on user input. Hindi-specific prompts could improve quality for Hindi-primary users — especially on objection handling where cultural nuances matter.

**6. A/B Testing Framework**

No infrastructure for testing different prompts, response formats, or CTA strategies against each other. Adding this would enable data-driven prompt optimization instead of intuition-based edits.

**7. Image Understanding**

Users sometimes send photos (screenshots of other PGs, photos of their current room, maps). The bot currently ignores images. Adding vision capabilities would enable "find me something like this" and "is this the property you mentioned?" interactions.

---

*This document describes EazyPG Chat as it exists in production as of March 2026. It is a living document — update it when the system changes.*
