"""
Dynamic Skills E2E Test
=======================
Verifies correct skill loading AND real search results using real pg_ids.

Usage:
  python3 test_dynamic_skills.py              # All 8 scenarios
  python3 test_dynamic_skills.py --scenario 3 # Single scenario
  python3 test_dynamic_skills.py --from 4     # Scenarios 4 through 8

Requires:
  - Server running: nohup python3 -m uvicorn main:app --port 8000 > /tmp/booking_bot_server.log 2>&1 &
  - redis-py: pip install redis
"""

import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field

import redis as redis_lib

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL       = "http://localhost:8000/chat"
ANALYTICS_URL  = "http://localhost:8000/admin/analytics?days=1"
TIMEOUT        = 120  # seconds per request

ACCOUNT_VALUES = {
    "pg_ids": [
        "l5zf3ckOnRQV9OHdv5YTTXkvLHp1", "DRJR8tMKWGPUzKn0RH46FgEBpHG3",
        "8dBkLn1JymhCN8sQYU3l2e9EHBm1", "YqcLVKwR0wdaDqz7K9rV16RgzR73",
        "6k1c9f49wQUKEXBhGrH16gBqhyG3", "KyMOYLEFOlVN7gEjXXNlBuZ8OsH3",
        "WVHglVelRvSqn2IQn2sj5yZL3Xr2", "TZN29JI4lgONzqV8E0cpLmDNivg2",
        "xRQptcIjxjR4b6VoQn4zcJwbq583", "Ei1CXqVU2gQPGo2GKRKfLYk53Yl2",
    ],
    "brand_name": "OxOtel",
    "cities":     "Mumbai",
    "areas":      "Andheri, Kurla, Powai",
}

# Redis connection (matches the server's env — adjust if different)
_redis_host     = "localhost"
_redis_port     = 6379
_redis_password = None   # set to your REDIS_PASSWORD if needed

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def send(user_id: str, message: str) -> dict:
    """POST to /chat with real account_values. Returns parsed JSON dict."""
    payload = json.dumps({
        "user_id":        user_id,
        "message":        message,
        "account_values": ACCOUNT_VALUES,
    }).encode()
    req = urllib.request.Request(
        BASE_URL, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def clear_user(user_id: str):
    """Wipe all Redis state for a test user."""
    try:
        r = redis_lib.Redis(
            host=_redis_host, port=_redis_port, password=_redis_password,
            decode_responses=True,
        )
        for suffix in [
            ":conversation", ":preferences", ":preferences:json",
            ":property_info_map", ":last_agent", ":account_values", ":pg_ids",
            ":shortlisted", ":user_memory",
        ]:
            r.delete(f"{user_id}{suffix}")
    except Exception as exc:
        print(f"  {YELLOW}[WARN] Redis clear failed: {exc}{RESET}")


def get_analytics_skills() -> dict[str, int]:
    """Fetch current skill usage counts from /admin/analytics."""
    try:
        with urllib.request.urlopen(ANALYTICS_URL, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get("skills", {})
    except Exception:
        return {}


def get_skill_misses_count() -> int:
    """Fetch skill miss count from analytics."""
    try:
        with urllib.request.urlopen(ANALYTICS_URL, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        misses = data.get("skill_misses", {})
        return sum(misses.values()) if misses else 0
    except Exception:
        return 0


def extract_property_names(response_text: str, max_n: int = 3) -> list[str]:
    """
    Extract property names from markdown-formatted search results.
    Matches patterns like: **1. Property Name** or **Property Name**
    Filters out sentence-like text to ensure we get only real property names.
    """
    # Sentence-start words that indicate it's NOT a property name
    _BAD_STARTS = {
        "let", "here", "quick", "great", "sure", "yes", "no", "i", "the",
        "a", "an", "based", "note", "now", "ok", "please", "would", "want",
        "can", "will", "should", "just", "what", "how", "why", "tell",
        "are", "is", "these", "those", "both", "all", "some", "few",
    }

    names = []

    # Priority 1: numbered list format — **1. Name**
    for m in re.finditer(r"\*\*\d+\.\s+([^*\n]+?)\*\*", response_text):
        name = m.group(1).strip()
        first_word = name.split()[0].lower().rstrip(",.:") if name else ""
        if (4 < len(name) <= 60
                and first_word not in _BAD_STARTS
                and not name.startswith("₹")
                and "%" not in name
                and name[0].isupper()
                and name not in names):
            names.append(name)
        if len(names) >= max_n:
            break

    # Priority 2: inline bold names — **Name of Place** (no leading number)
    if not names:
        for m in re.finditer(r"\*\*([A-Z][A-Za-z0-9\s\-']{4,40}?)\*\*", response_text):
            name = m.group(1).strip()
            first_word = name.split()[0].lower().rstrip(",.:") if name else ""
            # Must look like a proper noun (multiple words, title-case)
            words = name.split()
            if (len(words) >= 2
                    and first_word not in _BAD_STARTS
                    and not name.startswith("₹")
                    and "%" not in name
                    and all(w[0].isupper() for w in words if len(w) > 3)
                    and name not in names):
                names.append(name)
            if len(names) >= max_n:
                break

    return names[:max_n]


# ---------------------------------------------------------------------------
# Assertion engine
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    label:   str
    passed:  bool
    warn:    bool = False
    detail:  str  = ""


def check(
    label:            str,
    result:           dict,
    skills_before:    dict[str, int],   # analytics skills snapshot BEFORE request
    misses_before:    int,              # skill_misses count BEFORE request
    expected_skills:  list[str],
    must_have:        tuple[str, ...] = (),
    must_not_have:    tuple[str, ...] = (),
    nice_to_have:     tuple[str, ...] = (),
) -> list[CheckResult]:
    """
    Run assertions on a /chat response + analytics endpoint.
    Returns list[CheckResult]. Print per-check outcome.
    """
    results: list[CheckResult] = []
    response = result.get("response", "")
    agent    = result.get("agent", "")

    # Snapshot AFTER the request
    skills_after  = get_analytics_skills()
    misses_after  = get_skill_misses_count()

    # Skills that incremented during this request
    fired_skills = [
        s for s in skills_after
        if skills_after.get(s, 0) > skills_before.get(s, 0)
    ]

    def _add(lbl, ok, warn=False, detail=""):
        results.append(CheckResult(lbl, ok, warn, detail))
        if ok:
            sym = f"{GREEN}✓{RESET}"
        elif warn:
            sym = f"{YELLOW}⚠{RESET}"
        else:
            sym = f"{RED}✗{RESET}"
        print(f"    {sym} {lbl}" + (f" — {detail}" if detail else ""))

    # 1. Agent routing
    _add(
        f"agent=broker (got '{agent}')",
        agent == "broker",
        detail="" if agent == "broker" else f"Expected 'broker', got '{agent}'",
    )

    # 2. Response non-empty
    _add(
        "response non-empty",
        bool(response.strip()),
        detail="Empty response!" if not response.strip() else "",
    )

    # 3. Skill detection (via analytics delta)
    missing = [s for s in expected_skills if s not in fired_skills]
    extra   = [s for s in fired_skills if s not in expected_skills]
    ok = len(missing) == 0
    detail_parts = []
    if missing:
        detail_parts.append(f"missing: {missing}")
    if extra:
        detail_parts.append(f"extra (ok): {extra}")
    _add(
        f"skills fired={fired_skills} (expected ⊇ {expected_skills})",
        ok,
        detail=", ".join(detail_parts) if detail_parts else "",
    )

    # 4. No new skill-miss warnings
    new_misses = misses_after - misses_before
    _add(
        "no skill-miss warnings",
        new_misses == 0,
        detail=f"{new_misses} new miss(es)" if new_misses > 0 else "",
    )

    # 5. must_have patterns
    for pat in must_have:
        found = bool(re.search(pat, response, re.IGNORECASE))
        _add(
            f"must_have: r'{pat}'",
            found,
            detail="Pattern NOT found in response" if not found else "",
        )

    # 6. must_not_have patterns
    for pat in must_not_have:
        found = bool(re.search(pat, response, re.IGNORECASE))
        _add(
            f"must_not_have: r'{pat}'",
            not found,
            detail="Unwanted pattern FOUND in response" if found else "",
        )

    # 7. nice_to_have patterns (WARN on miss, not FAIL)
    for pat in nice_to_have:
        found = bool(re.search(pat, response, re.IGNORECASE))
        _add(
            f"nice_to_have: r'{pat}'",
            found,
            warn=not found,
            detail="Pattern not found (WARN only)" if not found else "",
        )

    return results


def verdict(results: list[CheckResult]) -> str:
    if any(not r.passed and not r.warn for r in results):
        return "FAIL"
    if any(r.warn and not r.passed for r in results):
        return "WARN"
    return "PASS"


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def run_all(run_only: int | None = None, from_n: int | None = None):
    """Run 8 dynamic-skill scenarios sequentially."""

    # Shared state across scenarios (build on each other)
    prop_names: list[str] = []   # populated after scenario 1

    USER_A = "dyn_skills_A"   # main user (scenarios 1-7)
    USER_B = "dyn_skills_B"   # returning-user test (scenario 8)
    USER_B_SEED = "dyn_skills_B_seed"  # seeded first so B is "returning"

    # Clean both users at the start of a full run
    if run_only is None and from_n is None:
        print(f"\n{CYAN}Clearing Redis state for test users...{RESET}")
        clear_user(USER_A)
        clear_user(USER_B)
        clear_user(USER_B_SEED)
        print("  Done.\n")

    # Pre-seed USER_B_SEED as a returning user (give them a completed search first)
    # Use a two-turn seed: qualifying message + location answer, so memory is built.
    if run_only is None and (from_n is None or from_n <= 8):
        print(f"{CYAN}Pre-seeding returning user {USER_B_SEED}...{RESET}")
        try:
            _seed_resp = send(
                USER_B_SEED,
                "Hi, I'm looking for a boys PG in Andheri, budget ₹12,000, need WiFi and meals.",
            )
            _seed_agent = _seed_resp.get("agent", "?")
            _seed_text  = _seed_resp.get("response", "")
            if _seed_text:
                print(f"  Seed turn 1 done. Agent={_seed_agent}. Response snippet: {_seed_text[:80]}...")
            else:
                print(f"  {YELLOW}[WARN] Seed turn 1 response empty{RESET}")
        except Exception as exc:
            print(f"  {YELLOW}[WARN] Seed failed: {exc}{RESET}")
        time.sleep(3)  # Short pause between seed turns
        print()

    all_results: dict[int, str] = {}

    def should_run(n: int) -> bool:
        if run_only is not None:
            return n == run_only
        if from_n is not None:
            return n >= from_n
        return True

    # ── Scenario 1: New user search ────────────────────────────────────────
    n = 1
    if should_run(n):
        if run_only == n or from_n == n:
            clear_user(USER_A)
        print(f"{BOLD}{'─'*60}{RESET}")
        print(f"{BOLD}S{n:02d}: New user search (qualify_new + search){RESET}")
        # Give complete info upfront so bot can search immediately.
        # NOTE: OxOtel properties are in Rabale/Navi Mumbai — use that location.
        msg = (
            "Hi! I'm a male student looking for a boys PG in Rabale, Navi Mumbai. "
            "Budget is ₹10,000/month. Must have WiFi. Please show me options."
        )
        print(f"  User: \"{msg}\"")

        skills_snap = get_analytics_skills()
        misses_snap = get_skill_misses_count()
        try:
            result = send(USER_A, msg)
        except Exception as exc:
            print(f"  {RED}[ERROR] Request failed: {exc}{RESET}")
            all_results[n] = "FAIL"
        else:
            resp_text = result.get("response", "")
            print(f"\n  Bot:\n  {resp_text[:600]}{'...' if len(resp_text) > 600 else ''}\n")

            # Try to extract property names; S02 will override with real names
            _s01_names = extract_property_names(resp_text, max_n=3)
            if _s01_names:
                prop_names.extend(_s01_names)
                print(f"  {CYAN}S01 property names: {prop_names}{RESET}\n")
            else:
                print(f"  {CYAN}No property names from S01 (bot may have asked qualifying question) — will use S02 names{RESET}\n")

            results = check(
                label="S01 new-user search",
                result=result,
                skills_before=skills_snap,
                misses_before=misses_snap,
                expected_skills=["qualify_new", "search"],
                # Lenient: accept qualifying questions OR search results
                # (bot may ask one follow-up even with full info)
                must_have=(
                    r"boys|male|gender|pg|property|properties|rabale|navi mumbai|budget|₹|10[,.]?000|wifi|wi-fi",
                ),
                must_not_have=(
                    r"i don.t have any properties",
                    r"no properties found",
                    r"0 properties",
                ),
                nice_to_have=(
                    r"\*\*\d+\.",                    # numbered list (full search result)
                    r"₹|rent|month",                # price shown
                ),
            )
            v = verdict(results)
            all_results[n] = v
            print(f"  {BOLD}S{n:02d} → {GREEN if v=='PASS' else YELLOW if v=='WARN' else RED}{v}{RESET}\n")
        time.sleep(5)  # Rate limit buffer

    # ── Scenario 2: Show more results ──────────────────────────────────────
    n = 2
    if should_run(n):
        if run_only == n:
            clear_user(USER_A)
            send(USER_A, "Looking for boys PG in Andheri under 15k, need WiFi")
            time.sleep(2)

        print(f"{BOLD}{'─'*60}{RESET}")
        print(f"{BOLD}S{n:02d}: Show more options{RESET}")
        msg = "Show me more options"
        print(f"  User: \"{msg}\"")

        skills_snap = get_analytics_skills()
        misses_snap = get_skill_misses_count()
        try:
            result = send(USER_A, msg)
        except Exception as exc:
            print(f"  {RED}[ERROR] Request failed: {exc}{RESET}")
            all_results[n] = "FAIL"
        else:
            resp_text = result.get("response", "")
            print(f"\n  Bot:\n  {resp_text[:600]}{'...' if len(resp_text) > 600 else ''}\n")

            # ── Key: update prop_names from S02 (most reliable source of real names)
            _s02_names = extract_property_names(resp_text, max_n=3)
            if _s02_names:
                prop_names.clear()
                prop_names.extend(_s02_names)
                print(f"  {CYAN}Updated property names from S02: {prop_names}{RESET}")
            elif not prop_names:
                # Last-resort fallback — known OxOtel Rabale properties
                prop_names.extend(["Purva Sugandha RABALE", "OXO ZEPHYR RABALE"])
                print(f"  {CYAN}Using fallback property names: {prop_names}{RESET}")
            else:
                print(f"  {CYAN}Keeping S01 property names: {prop_names}{RESET}")
            print()

            results = check(
                label="S02 show-more",
                result=result,
                skills_before=skills_snap,
                misses_before=misses_snap,
                expected_skills=["show_more"],
                must_have=(
                    r"₹|rs\.?|rent|month|property|properties|pg|hostel|options|expanded|radius",
                ),
                nice_to_have=(
                    r"\*\*\d+\.",       # numbered results
                    r"andheri|mumbai|kurla|powai|rabale|navi mumbai",
                ),
            )
            v = verdict(results)
            all_results[n] = v
            print(f"  {BOLD}S{n:02d} → {GREEN if v=='PASS' else YELLOW if v=='WARN' else RED}{v}{RESET}\n")
        time.sleep(5)

    # ── Scenario 3: Property details ───────────────────────────────────────
    n = 3
    if should_run(n):
        if run_only == n:
            clear_user(USER_A)
            r1 = send(USER_A, "Looking for boys PG in Andheri under 15k, need WiFi")
            prop_names = extract_property_names(r1.get("response", ""), max_n=3)
            time.sleep(2)

        target = prop_names[0] if prop_names else "the first property"
        print(f"{BOLD}{'─'*60}{RESET}")
        print(f"{BOLD}S{n:02d}: Property details — \"{target}\"{RESET}")
        msg = f"Tell me more about {target}"
        print(f"  User: \"{msg}\"")

        skills_snap = get_analytics_skills()
        misses_snap = get_skill_misses_count()
        try:
            result = send(USER_A, msg)
        except Exception as exc:
            print(f"  {RED}[ERROR] Request failed: {exc}{RESET}")
            all_results[n] = "FAIL"
        else:
            resp_text = result.get("response", "")
            print(f"\n  Bot:\n  {resp_text[:600]}{'...' if len(resp_text) > 600 else ''}\n")
            results = check(
                label="S03 property-details",
                result=result,
                skills_before=skills_snap,
                misses_before=misses_snap,
                expected_skills=["details"],
                must_have=(
                    r"₹|rent|month|amenity|amenities|room|bed|wifi|ac|meal|food|bathroom|floor",
                ),
                must_not_have=(
                    r"i don.t have information about",
                    r"couldn.t find",
                ),
                nice_to_have=(
                    r"image|photo|picture|gallery",   # images loaded
                    r"visit|schedule|book",            # CTA
                ),
            )
            v = verdict(results)
            all_results[n] = v
            print(f"  {BOLD}S{n:02d} → {GREEN if v=='PASS' else YELLOW if v=='WARN' else RED}{v}{RESET}\n")
        time.sleep(5)

    # ── Scenario 4: Shortlist ──────────────────────────────────────────────
    n = 4
    if should_run(n):
        if run_only == n:
            clear_user(USER_A)
            r1 = send(USER_A, "Looking for boys PG in Andheri under 15k, need WiFi")
            prop_names = extract_property_names(r1.get("response", ""), max_n=3)
            time.sleep(2)

        target = prop_names[0] if prop_names else "the first property"
        print(f"{BOLD}{'─'*60}{RESET}")
        print(f"{BOLD}S{n:02d}: Shortlist — \"{target}\"{RESET}")
        msg = f"Shortlist {target} for me"
        print(f"  User: \"{msg}\"")

        skills_snap = get_analytics_skills()
        misses_snap = get_skill_misses_count()
        try:
            result = send(USER_A, msg)
        except Exception as exc:
            print(f"  {RED}[ERROR] Request failed: {exc}{RESET}")
            all_results[n] = "FAIL"
        else:
            resp_text = result.get("response", "")
            print(f"\n  Bot:\n  {resp_text[:600]}{'...' if len(resp_text) > 600 else ''}\n")
            results = check(
                label="S04 shortlist",
                result=result,
                skills_before=skills_snap,
                misses_before=misses_snap,
                expected_skills=["shortlist"],
                must_have=(
                    r"shortlist|saved|added|bookmark|favourite|noted",
                ),
                nice_to_have=(
                    r"visit|schedule|call|book|details",   # follow-up CTA
                ),
            )
            v = verdict(results)
            all_results[n] = v
            print(f"  {BOLD}S{n:02d} → {GREEN if v=='PASS' else YELLOW if v=='WARN' else RED}{v}{RESET}\n")
        time.sleep(5)

    # ── Scenario 5: Compare two properties ────────────────────────────────
    n = 5
    if should_run(n):
        if run_only == n:
            clear_user(USER_A)
            r1 = send(USER_A, "Looking for boys PG in Andheri under 15k, need WiFi")
            prop_names = extract_property_names(r1.get("response", ""), max_n=3)
            time.sleep(2)

        p1 = prop_names[0] if len(prop_names) > 0 else "property 1"
        p2 = prop_names[1] if len(prop_names) > 1 else "property 2"
        print(f"{BOLD}{'─'*60}{RESET}")
        print(f"{BOLD}S{n:02d}: Compare two properties — \"{p1}\" vs \"{p2}\"{RESET}")
        msg = f"Compare {p1} and {p2}"
        print(f"  User: \"{msg}\"")

        skills_snap = get_analytics_skills()
        misses_snap = get_skill_misses_count()
        try:
            result = send(USER_A, msg)
        except Exception as exc:
            print(f"  {RED}[ERROR] Request failed: {exc}{RESET}")
            all_results[n] = "FAIL"
        else:
            resp_text = result.get("response", "")
            print(f"\n  Bot:\n  {resp_text[:600]}{'...' if len(resp_text) > 600 else ''}\n")
            results = check(
                label="S05 compare",
                result=result,
                skills_before=skills_snap,
                misses_before=misses_snap,
                expected_skills=["compare"],
                must_have=(
                    r"vs\.?|versus|compare|comparison|side.by.side|₹|rent",
                ),
                must_not_have=(
                    r"i can.t compare|unable to compare",
                ),
                nice_to_have=(
                    r"recommend|suggest|winner|better",  # recommendation
                    r"visit|schedule|book",               # CTA
                ),
            )
            v = verdict(results)
            all_results[n] = v
            print(f"  {BOLD}S{n:02d} → {GREEN if v=='PASS' else YELLOW if v=='WARN' else RED}{v}{RESET}\n")
        time.sleep(5)

    # ── Scenario 6: Commute estimation ─────────────────────────────────────
    n = 6
    if should_run(n):
        if run_only == n:
            clear_user(USER_A)
            r1 = send(USER_A, "Looking for boys PG in Andheri under 15k, need WiFi")
            prop_names = extract_property_names(r1.get("response", ""), max_n=3)
            time.sleep(2)

        target = prop_names[0] if prop_names else "the first property"
        print(f"{BOLD}{'─'*60}{RESET}")
        print(f"{BOLD}S{n:02d}: Commute — \"{target}\" to Mindspace office{RESET}")
        msg = f"How far is {target} from Mindspace Malad?"
        print(f"  User: \"{msg}\"")

        skills_snap = get_analytics_skills()
        misses_snap = get_skill_misses_count()
        try:
            result = send(USER_A, msg)
        except Exception as exc:
            print(f"  {RED}[ERROR] Request failed: {exc}{RESET}")
            all_results[n] = "FAIL"
        else:
            resp_text = result.get("response", "")
            print(f"\n  Bot:\n  {resp_text[:600]}{'...' if len(resp_text) > 600 else ''}\n")
            results = check(
                label="S06 commute",
                result=result,
                skills_before=skills_snap,
                misses_before=misses_snap,
                expected_skills=["commute"],
                must_have=(
                    r"km|kilomet|minute|min\b|distance|travel|commute|drive|transit|walk",
                ),
                nice_to_have=(
                    r"\d+\s*(min|km|hour)",   # actual numbers
                    r"auto|taxi|metro|bus|train",  # transport modes
                ),
            )
            v = verdict(results)
            all_results[n] = v
            print(f"  {BOLD}S{n:02d} → {GREEN if v=='PASS' else YELLOW if v=='WARN' else RED}{v}{RESET}\n")
        time.sleep(5)

    # ── Scenario 7: Web search (area safety) ──────────────────────────────
    n = 7
    if should_run(n):
        print(f"{BOLD}{'─'*60}{RESET}")
        print(f"{BOLD}S{n:02d}: Web search — area safety{RESET}")
        msg = "Tell me about the area — is Andheri safe to live in?"
        print(f"  User: \"{msg}\"")

        skills_snap = get_analytics_skills()
        misses_snap = get_skill_misses_count()
        result = None
        for attempt in range(3):
            try:
                result = send(USER_A, msg)
                break
            except Exception as exc:
                if "429" in str(exc) and attempt < 2:
                    print(f"  {YELLOW}[WARN] 429 rate limit, waiting 15s... (attempt {attempt+1}){RESET}")
                    time.sleep(15)
                else:
                    print(f"  {RED}[ERROR] Request failed: {exc}{RESET}")
                    all_results[n] = "FAIL"
                    break
        if result is not None:
            resp_text = result.get("response", "")
            print(f"\n  Bot:\n  {resp_text[:600]}{'...' if len(resp_text) > 600 else ''}\n")
            results = check(
                label="S07 web-search",
                result=result,
                skills_before=skills_snap,
                misses_before=misses_snap,
                expected_skills=["web_search"],
                must_have=(
                    r"andheri|mumbai|area|neighborhood|locality|safe|safety|neighbourhood",
                ),
                nice_to_have=(
                    r"crime|police|infrastructure|transport|connectivity",
                    r"residential|commercial|cosmopolitan",
                ),
            )
            v = verdict(results)
            all_results[n] = v
            print(f"  {BOLD}S{n:02d} → {GREEN if v=='PASS' else YELLOW if v=='WARN' else RED}{v}{RESET}\n")
        time.sleep(12)  # Extra buffer before S8 (returning user + new search)

    # ── Scenario 8: Returning user search ──────────────────────────────────
    n = 8
    if should_run(n):
        # USER_B_SEED was seeded at top with a PG search in Andheri.
        # Now we send as the SAME user — they have history so qualify_returning fires.
        # Location: Navi Mumbai/Rabale where OxOtel properties actually exist.
        print(f"{BOLD}{'─'*60}{RESET}")
        print(f"{BOLD}S{n:02d}: Returning user search (qualify_returning + search){RESET}")
        msg = "I'm back! Last time I searched in Andheri. Can you now show me options in Navi Mumbai under 12k?"
        print(f"  User: \"{msg}\" (as returning user {USER_B_SEED})")

        skills_snap = get_analytics_skills()
        misses_snap = get_skill_misses_count()
        try:
            result = send(USER_B_SEED, msg)  # same user who was seeded earlier
        except Exception as exc:
            print(f"  {RED}[ERROR] Request failed: {exc}{RESET}")
            all_results[n] = "FAIL"
        else:
            resp_text = result.get("response", "")
            # Debug: print full result if response is empty
            if not resp_text.strip():
                print(f"  {RED}[DEBUG] Full result dict: {result}{RESET}\n")
            print(f"\n  Bot:\n  {resp_text[:800]}{'...' if len(resp_text) > 800 else ''}\n")
            results = check(
                label="S08 returning-user search",
                result=result,
                skills_before=skills_snap,
                misses_before=misses_snap,
                expected_skills=["qualify_returning", "search"],
                # Accepting qualifying question OR search results — either is valid
                must_have=(
                    r"navi mumbai|rabale|mumbai|pg|property|properties|₹|rent|budget|12[,.]?000",
                ),
                must_not_have=(
                    r"no properties found",
                    r"0 properties",
                ),
                nice_to_have=(
                    r"welcome back|back again|good to|great to|hi again|nice to|last time|previously|remember",
                    r"\*\*\d+\.",   # numbered results
                ),
            )
            v = verdict(results)
            all_results[n] = v
            print(f"  {BOLD}S{n:02d} → {GREEN if v=='PASS' else YELLOW if v=='WARN' else RED}{v}{RESET}\n")

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}DYNAMIC SKILLS TEST SUMMARY{RESET}")
    print(f"{'='*60}")

    total = len(all_results)
    passed = sum(1 for v in all_results.values() if v == "PASS")
    warned = sum(1 for v in all_results.values() if v == "WARN")
    failed = sum(1 for v in all_results.values() if v == "FAIL")

    for sc_n, v in sorted(all_results.items()):
        colour = GREEN if v == "PASS" else (YELLOW if v == "WARN" else RED)
        print(f"  S{sc_n:02d}: {colour}{v}{RESET}")

    print(f"\n  Total: {total}  |  "
          f"{GREEN}PASS: {passed}{RESET}  |  "
          f"{YELLOW}WARN: {warned}{RESET}  |  "
          f"{RED}FAIL: {failed}{RESET}")
    print(f"{'='*60}\n")

    return failed == 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    run_only = None
    from_n   = None

    i = 0
    while i < len(args):
        if args[i] == "--scenario" and i + 1 < len(args):
            run_only = int(args[i + 1])
            i += 2
        elif args[i] == "--from" and i + 1 < len(args):
            from_n = int(args[i + 1])
            i += 2
        else:
            i += 1

    # Quick health check
    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}Dynamic Skills E2E Test — {ACCOUNT_VALUES['brand_name']}{RESET}")
    print(f"{CYAN}Server:    {BASE_URL}{RESET}")
    print(f"{CYAN}Analytics: {ANALYTICS_URL}{RESET}")
    print(f"{CYAN}PG IDs:    {len(ACCOUNT_VALUES['pg_ids'])} configured{RESET}")
    print(f"{CYAN}{'='*60}{RESET}\n")

    try:
        hc = urllib.request.urlopen("http://localhost:8000/health", timeout=5)
        print(f"{GREEN}✓ Server healthy{RESET}\n")
    except Exception as e:
        print(f"{RED}✗ Server not reachable: {e}{RESET}")
        print(f"{RED}  Start with: python3 -m uvicorn main:app --port 8000{RESET}\n")
        sys.exit(1)

    ok = run_all(run_only=run_only, from_n=from_n)
    sys.exit(0 if ok else 1)
