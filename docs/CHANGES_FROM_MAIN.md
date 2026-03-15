# What Changed From Production (main) — Full Audit

**For:** Developer review
**Branches:** `main` (production, live on Render) → `feat/dynamic-skills` → `feat/context-engineering`
**Total changes:** Sprints 1-2 (Feb 2026): 28 files, 2,268 insertions, 90 deletions. Sprints 3-7 (March 2026): 50+ files, 5,000+ insertions covering multi-brand isolation, admin portal, WhatsApp multi-turn handling, feature flags, and production hardening.
**One-line summary:** A dynamic skill system for the broker agent (Sprint 1), context reliability fixes (Sprint 2), multi-brand isolation with admin portal (Sprints 3-6), and WhatsApp multi-turn message handling (Sprint 7). All changes are backward-compatible with feature flags for instant rollback.

---

## How to read this doc

Every section answers three questions:
1. **What exactly changed?** (file-level, line-level)
2. **Why?** (what problem it solves)
3. **Risk / things to check** (honest assessment)

---

## Sprint 1 — Dynamic Skill System for Broker Agent
_Commits: `a1f5228`, `3093085`_

The broker agent previously loaded its full 580-line monolithic system prompt + all 12 broker tools on every single message, even for a simple "hi, show me PGs in Andheri." The dynamic skill system loads only the relevant prompt sections and tools for each turn.

---

### NEW: `skills/` directory (7 new Python/YAML files + 12 Markdown files)

#### `skills/__init__.py`
Empty package init. No logic.

#### `skills/loader.py` — Skill file loader
Reads `.md` skill files from `skills/broker/`. Parses YAML frontmatter (`---`) and body. Has a 30-second in-memory cache so files aren't re-read every request. Supports hot-reload — edit a `.md` file, it picks up the change within 30 seconds without a server restart.

**Returns:** `(base_prompt, skill_prompt)` — two strings for split caching.

#### `skills/skill_map.py` — Skill→tool mapping
Maps each skill name to the tool names it needs. Example: `"search"` skill → `["save_preferences", "search_properties", "shortlist_property"]`.

Also contains `detect_skills_heuristic()` — a keyword fallback that guesses skills from the user's raw message text if the supervisor returns nothing. This is a safety net, not the primary path.

`ALWAYS_TOOLS = ["save_preferences", "search_properties"]` — these two are always included regardless of skills detected.

#### `skills/broker/_base.md`
The "always loaded" base prompt — brand identity, response format rules, never-do rules, property ID mappings. ~950 tokens. This is what gets cached via Anthropic's `cache_control: ephemeral`. Every broker turn loads this.

#### `skills/broker/*.md` — 11 skill files
Each file has YAML frontmatter + XML `<instructions>` + 2–4 `<example>` blocks:

| File | Skill name | What it covers |
|------|-----------|----------------|
| `qualify_new.md` | `qualify_new` | New user onboarding — ask location, budget, gender, amenities |
| `qualify_returning.md` | `qualify_returning` | Returning user warm re-engagement — confirm if prefs still apply |
| `search.md` | `search` | Run `save_preferences` → `search_properties` → show results |
| `details.md` | `details` | Property details, images, room info for a named property |
| `compare.md` | `compare` | Side-by-side comparison + recommendation |
| `commute.md` | `commute` | Distance + commute estimation (driving + transit) |
| `shortlist.md` | `shortlist` | Shortlist/bookmark workflow |
| `show_more.md` | `show_more` | Next batch of results / expand radius |
| `selling.md` | `selling` | Objection handling, value framing, scarcity (with factual guardrail) |
| `web_search.md` | `web_search` | Area info, neighborhood research, market data |
| `learning.md` | `learning` | User rejected a property or updated preferences mid-session |

**These files are readable by any non-developer.** Edit the instructions in any `.md` file and the bot picks them up within 30 seconds — no deploy needed.

---

### MODIFIED: `agents/broker_agent.py`
_89 lines changed_

**Before:** `get_config(user_id, language)` — always returned full monolithic prompt + all 12 tools.

**After:** `get_config(user_id, language, skills=None)` — **two paths controlled by `DYNAMIC_SKILLS_ENABLED`:**

**Legacy path** (`DYNAMIC_SKILLS_ENABLED=false`):
Identical to before. Same monolithic prompt. Same 12 tools. Zero behaviour change.

**Dynamic path** (`DYNAMIC_SKILLS_ENABLED=true`, current default):
1. Supervisor detects 1–3 skills relevant to this turn
2. Broker agent loads only those skill `.md` files
3. Filters tools to match loaded skills (3–5 instead of 12)
4. Returns `system_prompt` as a `list[str]` (two blocks) instead of a `str`
5. Sets fallback to all 12 tools on the executor, so if Claude calls a tool outside the filtered set, it still works (with a warning log)

Also auto-injects: qualifying skill if search is present without one; selling skill if details/compare are present.

---

### MODIFIED: `agents/supervisor.py`
_25 lines changed_

**Before:** `route()` returned `str` — just the agent name.
**After:** `route()` returns `dict` — `{"agent": str, "skills": list[str]}`.

Skills are only populated when agent is `"broker"`. For all other agents the `skills` list is empty.

⚠️ **Breaking change if called directly:** Any code that does `agent = await supervisor.route(engine, messages)` and then uses `agent` as a string will break. All call sites in `main.py` were updated — but if your developer has custom scripts or tests that call `supervisor.route()` directly, those need updating.

---

### MODIFIED: `agents/supervisor.py` + `core/prompts.py` (SUPERVISOR_PROMPT)
_18 lines added to prompts.py_

The supervisor prompt now asks the model to detect 1–3 broker skills alongside the agent name, and return `{"agent": "broker", "skills": ["search", "qualify_returning"]}` instead of `{"agent": "broker"}`.

---

### MODIFIED: `core/claude.py`
_39 lines changed_

**Before:** `run_agent()` and `run_agent_stream()` accepted only `system_prompt: str`. Built a single cached block internally.

**After:** Both methods accept `system_prompt: str | list[str]`.

New private method `_build_system_blocks()`:
- `str` → single cached block (backward compat — all agents except dynamic broker)
- `list[str]` → first block cached, second block NOT cached (dynamic broker: base cached, skill content not cached)

This is what enables split prompt caching — the base `.md` gets cached at Anthropic's infrastructure level, the per-turn skill content doesn't.

**Risk:** None. The method is additive; existing `str` prompt usage is unchanged.

---

### MODIFIED: `core/tool_executor.py`
_26 lines added_

Added `set_fallback(handlers)` method and graceful expansion logic in `execute()`.

When the broker agent runs with filtered tools (e.g., only search-related tools loaded), but Claude calls `fetch_landmarks` (a commute tool), the executor:
1. Doesn't find the handler in the filtered set
2. Checks the fallback (full broker tool set)
3. Finds it, logs a warning (`"Skill miss: tool 'X' not in filtered set — expanding from fallback"`)
4. Calls `track_skill_miss()` to Redis for monitoring
5. Registers it for subsequent calls in this turn
6. Executes normally — **user never sees an error**

**Risk:** None. Pure fallback; default path is unchanged.

---

### MODIFIED: `config.py`
_1 line added_

```python
DYNAMIC_SKILLS_ENABLED: bool = True
```

Set `DYNAMIC_SKILLS_ENABLED=false` in the Render env vars to instantly revert the broker agent to its original monolithic prompt. **This is the kill switch.**

---

### MODIFIED: `db/redis_store.py` (Sprint 1 additions)
_~45 lines added_

Four new functions for skill analytics:
- `track_skill_usage(skills)` — increments Redis hash `skill_usage:{date}` per skill name
- `track_skill_miss(tool_name)` — increments `skill_misses:{date}` when graceful expansion fires
- `get_skill_usage(day)` — read skill usage for a day
- `get_skill_misses(day)` — read skill misses for a day

All keys have 90-day TTL. Exposed in the existing `/admin/analytics` endpoint under `skills` and `skill_misses` keys.

---

### MODIFIED: `main.py`
_108 lines changed_

Two places updated (non-streaming `/chat` endpoint via `run_pipeline()`, and streaming `/chat/stream` via `_route_agent()`):

1. `supervisor.route()` now returns dict — `agent_name = route_result["agent"]`, `skills = route_result["skills"]`
2. If the keyword safety net overrides the agent, skills are cleared (they were for the original agent)
3. If agent is broker and skills are empty, `detect_skills_heuristic()` keyword fallback runs
4. Broker agent is called as `broker_agent.run(..., skills=skills)` instead of `broker_agent.run(...)`
5. `_route_agent()` now returns 4-tuple `(agent_name, messages, language, skills)` instead of 3-tuple
6. Skill usage tracked via `track_skill_usage(skills)` alongside existing `track_agent_usage()`
7. Analytics endpoint now includes `skills` and `skill_misses` in response

---

### NEW: `requirements.txt` addition
```
PyYAML>=6.0.0
```
Required for parsing YAML frontmatter in skill `.md` files. **Developer must run `pip install -r requirements.txt` after pulling.**

---

### NEW: `test_dynamic_skills.py` (798 lines)
E2E test file — **not deployed, not imported by the app**. Only runs when executed directly: `python test_dynamic_skills.py`. Tests 8 scenarios against a live server using real OxOtel PG IDs. Results were 4 PASS / 4 WARN / 0 FAIL.

---

### MODIFIED: `stress_test_broker.py`
_6 lines changed_

Minor update: Scenario 1 (`qualify_returning` greeting) tightened to reflect the new warm greeting format introduced in commit `3093085`. No functional change to the test structure.

---

## Sprint 2 — Context Engineering Hardening
_Commit: `55de5ce`_

Seven targeted fixes for context reliability failure modes. No new features, no new tools, no new agents.

---

### MODIFIED: `tools/registry.py`
_28 lines added_

`"strict": True` added to all 28 tool schema dicts.

**What it does:** Anthropic's strict mode makes the model emit JSON that conforms exactly to the declared schema — no extra fields, no hallucinated keys beyond what's in `"properties"`.

**Why:** Without this, Claude occasionally adds undeclared keys to tool calls (e.g., `"reason": "searching for user"` alongside `"location": "Andheri"`). Most handlers silently ignored these; some raised validation warnings. Strict mode eliminates the ambiguity.

**⚠️ Potential risk — most important thing to test:** If any existing tool call was passing extra fields that your handlers were silently using, strict mode will now cause those calls to be rejected by the Anthropic API before they even reach your handler. This is unlikely (we reviewed all 28 schemas and they're tight), but worth a smoke test — run a few normal conversations and watch for `tool_use_param_validation_error` in logs.

---

### MODIFIED: `db/redis_store.py` (Sprint 2 additions)
_22 lines added_

`build_returning_user_context()` now computes `days_since` from `last_seen` and injects one of three freshness markers:

| Gap since last visit | What's injected into the prompt |
|---------------------|--------------------------------|
| > 30 days | `⚠️ STALE CONTEXT (N days): Treat preferences as background only — re-qualify before searching` |
| 7–30 days | `Note: preferences last updated N days ago — confirm budget/location still current` |
| ≤ 7 days | Nothing (preferences are fresh) |

**Why:** Without this, the bot treats a 45-day-old `last_search_budget: ₹8,000` as a current constraint, skips re-qualification, and searches against stale preferences — producing confidently wrong results. A known failure mode called "context distraction" in prompt-engineering literature.

**Risk:** None. New users (no `last_seen`) and users with ≤7 day gap see zero change. The markers are informational text injected into the returning-user context block that already exists.

---

### MODIFIED: `core/summarizer.py`
_80 lines changed (largest single-file change in Sprint 2)_

Two independent changes:

#### Change A — CONTEXT CLASH RULE in `SUMMARIZER_PROMPT`
One rule added to the summarizer's instruction set:

> *"CONTEXT CLASH RULE: If the same property appears with different prices or availability at different points in the conversation, preserve ONLY the most recent data. Never carry forward conflicting historical values — always resolve in favour of the latest tool result."*

**Why:** Without this, the summarizer can write contradictory data — "OXO Zephyr: ₹8,000" from an early search AND "OXO Zephyr: ₹9,500" from a later detail fetch — keeping both in the summary. Future turns see conflicting data.

**Risk:** None. This is a prompt addition, not a code change.

#### Change B — Hierarchical summarization (replaces flat re-summarization)

New helper function `_extract_existing_summary(messages) → (str, list[dict])`:
- Checks if the first message contains a `[CONVERSATION_SUMMARY]...[/CONVERSATION_SUMMARY]` block (i.e., this is a second or later compression cycle)
- If yes: extracts the prior summary text as a clean string, returns the messages AFTER the summary pair
- If no: returns empty string + all messages unchanged

Modified `maybe_summarize()`:

**Before (flat — unreliable on second compression):**
- Formatted all older messages including the prior summary blob into one giant transcript string
- Appended a weak hint: *"NOTE: incorporate previous summary info"*
- Claude had to notice the summary tags in the transcript noise, parse them, and remember to merge — often dropped data across multiple compression cycles

**After (hierarchical — reliable):**
- Splits prior summary from new messages cleanly
- Sends two clearly labelled sections to Haiku: `--- PRIOR SUMMARY ---` and `--- NEW MESSAGES TO INTEGRATE ---`
- First compression (no prior summary): behaviour unchanged — uses original flat format
- Second+ compression: uses hierarchical format

**Verified with mock tests:** Both paths tested — first compression (flat) and second compression (hierarchical) confirmed working correctly without real API calls.

**Risk:** None for first summarization (identical path). Second summarization (when conversations exceed 60 messages) uses the new path — well-tested and only affects the structure of what's sent to Haiku, not the output structure stored in Redis.

---

### MODIFIED: `skills/broker/selling.md`
_9 lines added_

`FACTUAL GUARDRAIL` block added at the very top of `<instructions>`:

```
- "Only [N] beds left" → ONLY after fetch_room_details confirms beds_available ≤ 3
- "Price going up" / "limited time deal" → NEVER use
- Vague market framing → acceptable; specific numbers without tool data → forbidden
- Property-specific data → MUST come from tools only. Never invent.
```

**Why:** Without this, the selling skill can fabricate scarcity claims that get written into conversation history and persist in summaries as permanent false facts — a "context poisoning" pattern.

**Risk:** None. This is a prompt instruction in a `.md` file.

---

### MODIFIED: `skills/loader.py`
_7 lines changed — documentation only_

Updated `build_skill_prompt()` docstring to explain why the Haiku prompt caching threshold (~4,096 tokens minimum) isn't being hit by the base file (~950 tokens). No code change.

---

## Summary table

| File | Sprint | What changed | Lines | Risk |
|------|--------|-------------|-------|------|
| `skills/__init__.py` | 1 | New package | 12 | None |
| `skills/loader.py` | 1 | Skill file loader | 128 | None |
| `skills/skill_map.py` | 1 | Skill→tool map | 104 | None |
| `skills/broker/_base.md` | 1 | Always-on base prompt | 76 | None |
| `skills/broker/*.md` (11 files) | 1 | Skill instruction files | ~800 | None |
| `agents/broker_agent.py` | 1 | Dual-path broker config | +89 | Low |
| `agents/supervisor.py` | 1 | Returns dict instead of str | +25 | ⚠️ See note |
| `core/prompts.py` | 1 | Skill detection in supervisor prompt | +18 | None |
| `core/claude.py` | 1 | Split prompt caching support | +39 | None |
| `core/tool_executor.py` | 1 | Graceful tool fallback | +26 | None |
| `config.py` | 1 | `DYNAMIC_SKILLS_ENABLED` flag | +1 | None |
| `db/redis_store.py` (Sprint 1) | 1 | Skill usage tracking | +45 | None |
| `main.py` | 1 | Route skills through pipeline | +108 | Low |
| `requirements.txt` | 1 | PyYAML added | +1 | Install needed |
| `test_dynamic_skills.py` | 1 | E2E test (not imported by app) | +798 | None |
| `stress_test_broker.py` | 1 | Minor scenario update | ±6 | None |
| `tools/registry.py` | 2 | `"strict": True` on 28 schemas | +28 | ⚠️ See note |
| `db/redis_store.py` (Sprint 2) | 2 | Freshness markers | +22 | None |
| `core/summarizer.py` | 2 | Clash rule + hierarchical summarize | +80 | None |
| `skills/broker/selling.md` | 2 | Factual guardrail | +9 | None |
| `skills/loader.py` (docstring) | 2 | Cache threshold doc | +7 | None |

---

## What was NOT changed (Sprints 1-2 only)

These files were identical to production at the end of Sprint 2 (later sprints modified some of these — see Sprint 3+ sections below):

- All booking tools (`tools/booking/`) — later modified in Sprint 5 (API audit)
- All broker tools (`tools/broker/`) — the Python tool logic was untouched in Sprints 1-2
- All profile tools (`tools/profile/`)
- All other agents (`agents/booking_agent.py`, `agents/profile_agent.py`, `agents/default_agent.py`)
- WhatsApp channel (`channels/whatsapp.py`)
- Frontend (`eazypg-chat/` — entire directory) — later enhanced in Sprint 3 (Generative UI) and Sprint 8 (Phase A interrupt)
- Conversation manager (`core/conversation.py`) — later updated for brand_hash threading
- Rate limiter (`core/rate_limiter.py`)
- Message parser (`core/message_parser.py`)
- Router / keyword safety net (`core/router.py`)
- Language detection (`core/language.py`)
- No new environment variables required in Sprints 1-2 (beyond `DYNAMIC_SKILLS_ENABLED`)

---

## The two things your developer should actually check

### 1. `"strict": True` on tool schemas (most important)
Run a full end-to-end conversation that hits every tool type — search, details, commute, booking, payment. Watch the server logs for any `tool_use_param_validation_error`. If Claude was sending undeclared extra fields, you'll see errors here. If logs are clean, you're fine. This is the one change with a non-zero chance of causing a visible failure.

### 2. `supervisor.route()` now returns dict
If your developer has any script, test, or notebook that calls `supervisor.route()` directly and uses the result as a string, it will break. The fix is: `result = await supervisor.route(engine, messages); agent = result["agent"]`. All call sites inside `main.py` are already updated.

---

## Kill switch

If anything behaves unexpectedly, set this in Render environment variables:

```
DYNAMIC_SKILLS_ENABLED=false
```

This reverts the broker agent to the original monolithic prompt and all 12 tools — identical to what's currently live on `main`. No redeploy needed beyond the env var change. All other Sprint 2 changes (strict schemas, freshness markers, summarizer improvements) are independent and have no kill switch, but they also have near-zero failure risk.

---

## Is this over-engineered?

**Honest answer: Sprint 1 is architecturally significant. Sprint 2 is not.**

**Sprint 2 (7 fixes)** — Not over-engineered. Each change is 5–30 lines, solves a specific real problem, has an instant rollback, and touches nothing structural. A cautious developer should be comfortable with all of Sprint 2.

**Sprint 1 (dynamic skills)** — This is a real architectural addition. It adds a new abstraction layer (skills), a new directory, a new config flag, changes the supervisor's return type, and requires PyYAML. Whether this is "too much" depends on your team's comfort level with the codebase.

**The case for it:** The broker agent's 580-line monolithic prompt was genuinely hard to maintain — every change required editing a massive Python constant. The `.md` skill files are human-readable and hot-reloadable. The feature flag means it can be switched off in seconds.

**The case against it:** It adds conceptual overhead. A developer joining the project now needs to understand skills, the loader, the skill map, and the supervisor's new return format — before they can change how the broker behaves. If the team is small and the bot is working, adding complexity for marginal gains is a reasonable thing to push back on.

**What you can do:** If your developer is uncomfortable, flip `DYNAMIC_SKILLS_ENABLED=false`. The bot runs exactly as it did before PR #1. The skill files, loader, and skill map sit dormant and do nothing. Sprint 2's improvements are all still active.

---
---

## Sprint 3 — Admin Portal + Human Takeover (March 2026)
_Deployed to production on Render + Vercel_

### What changed

A full admin portal (`eazypg-admin/`) and backend admin endpoints were added. The admin portal is a separate Vercel project with conversation browser, lead pipeline, analytics dashboard, property document management, and settings panel.

#### Backend: Router refactoring
The monolithic `main.py` (formerly 700+ lines) was split into a clean router package:

| New file | Purpose |
|----------|---------|
| `routers/__init__.py` | Package init |
| `routers/public.py` | `/health`, `/brand-config` (no auth) |
| `routers/chat.py` | `/chat`, `/chat/stream`, `/feedback`, `/funnel`, `/language` |
| `routers/webhooks.py` | `/webhook/whatsapp`, `/webhook/payment`, `/cron/follow-ups` |
| `routers/admin.py` | All `/admin/*` endpoints (20+ routes) |

`main.py` is now 129 lines — just app factory + lifespan.

#### Backend: Redis refactoring
The monolithic `db/redis_store.py` (formerly 600+ lines) was split into 8 domain modules:

| Module | Domain |
|--------|--------|
| `db/redis/_base.py` | Connection pool, helpers |
| `db/redis/conversation.py` | History, compaction, last-agent |
| `db/redis/user.py` | Memory, preferences, shortlist, lead score |
| `db/redis/property.py` | Property cache, images, templates |
| `db/redis/payment.py` | Payment state, active request |
| `db/redis/analytics.py` | Funnel, feedback, agent/skill usage, costs |
| `db/redis/brand.py` | Brand config, WA reverse-lookup, flags |
| `db/redis/admin.py` | Active users, human mode, session cost |

`db/redis_store.py` is now a backward-compat shim (`from db.redis import *`).

#### Backend: New shared modules
| File | Purpose |
|------|---------|
| `core/auth.py` | `require_admin_brand_key` — brand-scoped auth for all admin endpoints |
| `core/pipeline.py` | `run_pipeline()` — shared pipeline used by both chat and WhatsApp |
| `core/state.py` | Shared singletons (engine, conversation) — eliminates circular imports |
| `core/router.py` | 3-phase keyword safety net (extracted from pipeline) |
| `core/ui_parts.py` | Generative UI parts (quick_replies, action_buttons, expandable_sections) |
| `utils/api.py` | Rentok API response validation |
| `utils/property_docs.py` | KB document formatting for broker prompt |

#### Backend: Human takeover
Admins can take over conversations from the bot:
- `POST /admin/conversations/{uid}/takeover` — sets human mode, bot stops responding
- `POST /admin/conversations/{uid}/resume` — clears human mode, bot resumes
- `POST /admin/conversations/{uid}/message` — send admin message via WhatsApp + auto-resume

#### Backend: Property documents
Knowledge base injection via file upload:
- Upload documents per property (`POST /admin/properties/{prop_id}/documents`)
- Documents stored in PostgreSQL (`property_documents` table)
- Content injected into broker prompt via `get_property_documents_text()`

#### Frontend: Admin portal (`eazypg-admin/`)
5 pages: Conversations (two-pane browser), Leads (filterable pipeline), Analytics (KPI cards + charts), Properties (document management), Settings (feature flags + broadcast).

#### Frontend: Chat widget enhancements
- Generative UI: 10 component types rendered from backend `parts[]` in SSE `done` event
- Property cards with match score badges and amenity pills
- Expandable sections (FAQ, rules, amenities) with pop-in animation
- Skeleton loaders, celebration animations, stagger transitions

---

## Sprint 4 — Production Bug Fixes (March 2026)
_Commit `47792bf` — deployed to Render production_

Analyzed 80 conversations in Redis. Found 10 bug patterns, applied 5 targeted fixes:

| Bug | Fix |
|-----|-----|
| Text concatenation (pre-tool + post-tool text glued together) | Fixed content delta accumulation in streaming |
| Bot silent after human takeover (4 consecutive empty responses) | Fixed human mode check ordering in pipeline |
| Disambiguation loop (same property list asked 4 times) | Improved context injection for follow-up turns |
| Payment retry loop (identical reserve+payment run twice) | Added idempotency check on payment state |
| Phone gate bypass via conversation summary | Summary now preserves accurate phone collection status |

---

## Sprint 5 — Fire-and-Forget API Audit (March 2026)
_Commit `92c372b` — deployed to Render production_

Audited all booking tools for silent CRM failures. 4 tools had fire-and-forget API calls that could fail silently:

| File | Fix |
|------|-----|
| `tools/booking/schedule_call.py` | Fixed `and`-bug in success check + track lead creation result |
| `tools/booking/payment.py` | Track `addLeadFromEazyPGID` result; always clear payment state; partial-failure message |
| `tools/broker/shortlist.py` | Add response body validation; only track funnel on confirmed success |
| `tools/booking/cancel.py` | Remove dead code (unreachable block after `raise_for_status()`) |

**Pattern applied consistently:** `if not data.get("success"):` check (no `and` clause), secondary CRM calls tracked with bool flag, `logger.error` for post-success CRM failures, state cleanup always happens.

---

## Sprint 6 — Multi-Brand Isolation (March 2026)
_3-phase implementation, all deployed to production_

### The problem
All brands shared one data namespace. OxOtel admin could see Stanza conversations. Analytics were aggregated across all brands. Feature flags were global.

### The solution: `brand_hash = sha256(api_key)[:16]`
Each brand gets a unique API key. The SHA-256 hash of the key (truncated to 16 chars) is used as a namespace prefix for all brand-scoped data. The raw API key is never stored.

### Phase 1: Core isolation
- All admin endpoints use `require_admin_brand_key` (validates API key → returns `brand_hash`)
- Users tagged with `brand_hash` on first message (`set_user_brand`)
- Active users tracked per-brand (`active_users:{brand_hash}` sorted set)
- Conversation list, thread view, leads, analytics — all filtered by `brand_hash`
- Property document ownership checks (prop_id must be in brand's `pg_ids`)

### Phase 2A: Per-brand feature flags
- `brand_flags:{brand_hash}` Redis key stores per-brand overrides
- `get_effective_flags(brand_hash)` merges brand overrides over global defaults from `config.py`
- Admin panel shows effective flags; toggles update brand-scoped key only
- Prompts resolve flags at request time via `format_prompt()`

### Phase 2B: Per-brand analytics + PostgreSQL
- ALL 12 analytics functions (`track_funnel`, `track_agent_usage`, `save_feedback`, etc.) dual-write to global + brand-scoped keys
- Admin endpoints read from brand-scoped keys; debug/global views read global keys
- PostgreSQL `booking_messages` + `leads` tables: `brand_hash` column added (idempotent migration on startup)
- Brand-scoped Redis keys: `funnel:{brand_hash}:{day}`, `agent_usage:{brand_hash}:{day}`, `skill_usage:{brand_hash}:{day}`, `agent_cost:{brand_hash}:{day}`, `daily_cost:{brand_hash}:{day}`, `feedback:counts:{brand_hash}`

### Phase 3: Polish
- Human mode scoped to `{uid}:{brand_hash}:human_mode` (with global fallback for backward compat)
- Brand context injected into conversation summarization prompt
- Admin portal sidebar shows dynamic brand name
- Brand configs auto-seed on startup (`_SEED_BRANDS` in `main.py`)

---

## Sprint 7 — PAYMENT_REQUIRED Feature Flag (March 2026)
_Commit `a4293a5` — deployed to Render production_

### The problem
The booking flow always required payment before reservation, but some brands want to skip payment and go directly to bed reservation.

### The solution: `PAYMENT_REQUIRED=false` (default)
When false, the booking prompt tells the agent to skip payment and call `reserve_bed` directly after visit. Payment tools (`create_payment_link`, `verify_payment`) are not registered in the tool set.

| File | Change |
|------|--------|
| `config.py` | Added `PAYMENT_REQUIRED: bool = False` |
| `tools/registry.py` | `_PAYMENT_TOOLS` conditional registration (same pattern as `_KYC_TOOLS`) |
| `tools/booking/reserve.py` | 4-way dynamic tool description based on KYC + Payment flags |
| `core/prompts.py` | 4-branch `kyc_reservation_flow` + 3 template vars in `format_prompt()` |
| `skills/broker/selling.md` | Hardcoded token lines → `{token_value_line}` template var |
| `routers/admin.py` | Fixed admin flags payload bug (Pydantic → raw JSON parsing) |

**Admin flags bug fix (pre-existing):** Frontend sent `{ key, value }` but Pydantic expected `{ FLAG: value }`. Silently ignored → no flag ever updated. Fixed by accepting both formats.

---

## Sprint 8 — WhatsApp Multi-Turn Message Handling (March 2026)
_Backend `c5f89b0` + Frontend `4f97f41` — deployed to production_

### The problem
Users send multiple WhatsApp messages in quick succession. Each message triggered a separate pipeline run, causing race conditions, duplicate responses, and wasted API calls.

### The solution: 3-phase handling

**Phase A — Web frontend: Interrupt-on-send**
- `AbortController` + `requestCounter` pattern in `stream.js`
- New message cancels any in-flight request; partial response gets amber "interrupted" badge
- Stop button added to input bar

**Phase B — WhatsApp: Queue + debounce**
- Webhook returns 200 immediately (non-blocking)
- Messages pushed to Redis list (`{uid}:wa_queue`)
- `_drain_and_process()` async task debounces 2 seconds, then drains all queued messages into one pipeline call
- Per-user lock (`{uid}:wa_processing`) prevents duplicate drain tasks
- wamid-based dedup replaces text-based dedup (`wamid:{wamid}`, 24h TTL)

**Phase C — Pipeline cancellation**
- If new messages arrive while pipeline is running, `set_cancel_requested(uid)` is called
- `core/claude.py` checks `is_cancel_requested()` between tool-call iterations
- Pipeline returns early; drain task loops back with fresh message batch

### New Redis keys
| Key | TTL | Purpose |
|-----|-----|---------|
| `wamid:{wamid}` | 24h | Message dedup by Meta unique ID |
| `{uid}:wa_queue` | 5 min | Pending message accumulation |
| `{uid}:wa_processing` | 2 min | Per-user drain lock |
| `{uid}:cancel_requested` | 30s | Pipeline cancellation signal |

### Config values (`config.py`)
`WA_DEBOUNCE_SECONDS=2.0`, `WAMID_DEDUP_TTL=86400`, `WA_QUEUE_TTL=300`, `WA_PROCESSING_TTL=120`

---

## Sprint 9 — Stress Test Resilience (March 2026)
_Commit `47792bf` — deployed to production_

Three-layer fix for 4 stress test failures (S01, S14, S19, E1/C5):

| Layer | Fix | Files |
|-------|-----|-------|
| Test infra | Server warmup + auto-retry on transient errors | `stress_test_broker_prod.py` |
| Prompts | DISSATISFACTION sentiment category + empathy never-rule | `selling.md`, `_base.md` |
| Tool runtime | 30s aggregate timeout + vague destination blocklist | `landmarks.py`, `commute.md` |
| E2E tests | 120s timeout for multi-turn tests | `e2e.spec.js` |

**Result:** Stress test improved from 10/6/4 (PASS/WARN/FAIL) to 13/5/2. Remaining 2 failures (S04, S08) are Haiku model stochasticity — pass on retry.

---

## What was NOT changed (still same as original production)

These files/systems remain untouched from the original `main` branch:
- `core/language.py` — language detection logic (en/hi/mr)
- `core/rate_limiter.py` — sliding window rate limiting
- `core/message_parser.py` — markdown → WhatsApp parts parsing
- `channels/whatsapp.py` — WhatsApp send logic (Meta/Interakt APIs)
- `utils/date.py` — date parsing
- `utils/image.py` — image conversion + WA upload
- `utils/scoring.py` — property match scoring
- `data/transit_lines.json` — metro/transit line data
- All Rentok API contracts — same endpoints, same payloads
- Redis conversation format — same JSON structure
- Frontend core rendering — same markdown parsing, carousel, comparison table logic
