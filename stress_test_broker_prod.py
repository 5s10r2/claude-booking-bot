#!/usr/bin/env python3
"""
Production Stress Test: Broker Intelligence — All 20 Scenarios  [v2 — calibrated]
Targets https://claude-booking-bot.onrender.com with OxOtel pg_ids.

Areas updated to use Navi Mumbai / Rabale where OxOtel properties actually live.
Broad "Mumbai" searches used where the exact area doesn't matter for the scenario.

v2 calibration (2026-03-09):
  Turn 1 messages now include explicit gender ("boys PG") where needed.
  The qualify_new dynamic skill correctly asks gender BEFORE searching for vague
  queries — so assertions that expect rent|₹ in Turn 1 would always fail without it.
  Adding gender/budget info to Turn 1 gives the broker enough context to search
  immediately, matching real-world usage patterns.

Usage:
    python3 stress_test_broker_prod.py              # Run all 20
    python3 stress_test_broker_prod.py --scenario 5 # Run only scenario 5
    python3 stress_test_broker_prod.py --from 10    # Run from scenario 10
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Config — production target, broader areas
# ---------------------------------------------------------------------------

BASE_URL = "https://claude-booking-bot.onrender.com/chat"
TIMEOUT = 120

ACCOUNT_VALUES = {
    "pg_ids": [
        "l5zf3ckOnRQV9OHdv5YTTXkvLHp1",
        "DRJR8tMKWGPUzKn0RH46FgEBpHG3",
        "8dBkLn1JymhCN8sQYU3l2e9EHBm1",
        "YqcLVKwR0wdaDqz7K9rV16RgzR73",
        "6k1c9f49wQUKEXBhGrH16gBqhyG3",
        "KyMOYLEFOlVN7gEjXXNlBuZ8OsH3",
        "WVHglVelRvSqn2IQn2sj5yZL3Xr2",
        "TZN29JI4lgONzqV8E0cpLmDNivg2",
        "xRQptcIjxjR4b6VoQn4zcJwbq583",
        "Ei1CXqVU2gQPGo2GKRKfLYk53Yl2",
    ],
    "brand_name": "OxOtel",
    "cities": "Mumbai",
    "areas": "Rabale, Navi Mumbai, Ghansoli, Airoli, Kopar Khairane, Thane, Andheri, Kurla, Powai, BKC, Mulund, Vikhroli, Dadar, Borivali",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Turn:
    message: str
    agent_is: str = ""
    must_have: list = field(default_factory=list)
    must_not_have: list = field(default_factory=list)
    nice_to_have: list = field(default_factory=list)


@dataclass
class Scenario:
    name: str
    user_id: str
    turns: list


@dataclass
class CheckResult:
    level: str  # PASS, WARN, FAIL
    detail: str


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def send(user_id: str, message: str) -> dict:
    payload = json.dumps({
        "user_id": user_id,
        "message": message,
        "account_values": ACCOUNT_VALUES,
    }).encode()
    req = urllib.request.Request(
        BASE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode()
            # Strip stray control chars that break JSON
            safe = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
            return json.loads(safe)
    except Exception as e:
        return {"agent": "ERROR", "response": str(e)}


def cleanup(user_id: str):
    """Best-effort Redis cleanup — skipped for production remote Redis."""
    pass   # Production Redis is remote; tests use unique user_ids per run


def _warmup_server():
    """Hit /health up to 3 times with 10s waits to wake Render from cold start."""
    health_url = BASE_URL.replace("/chat", "/health")
    print(f"\n  Warming up server: {health_url}")
    for attempt in range(3):
        try:
            req = urllib.request.Request(health_url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    print(f"  ✅ Server warm ({attempt + 1} attempt(s))")
                    return True
        except Exception as e:
            print(f"  ⏳ Warmup attempt {attempt + 1}/3: {e}")
            time.sleep(10)
    print("  ⚠️  Server may still be cold — proceeding anyway")
    return False


# ---------------------------------------------------------------------------
# Assertion engine
# ---------------------------------------------------------------------------

def check_pattern(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, re.IGNORECASE))


def check_turn(agent: str, response: str, turn: Turn) -> list:
    results = []
    if turn.agent_is:
        if agent.lower() == turn.agent_is.lower():
            results.append(CheckResult("PASS", f"agent == {turn.agent_is}"))
        else:
            results.append(CheckResult("FAIL", f"agent: expected '{turn.agent_is}', got '{agent}'"))
    for pattern in turn.must_have:
        if check_pattern(response, pattern):
            results.append(CheckResult("PASS", f'must_have "{pattern}" → FOUND'))
        else:
            results.append(CheckResult("FAIL", f'must_have "{pattern}" → NOT FOUND'))
    for pattern in turn.must_not_have:
        if check_pattern(response, pattern):
            results.append(CheckResult("FAIL", f'must_not_have "{pattern}" → FOUND (bad!)'))
        else:
            results.append(CheckResult("PASS", f'must_not_have "{pattern}" → CLEAN'))
    for pattern in turn.nice_to_have:
        if check_pattern(response, pattern):
            results.append(CheckResult("PASS", f'nice_to_have "{pattern}" → FOUND'))
        else:
            results.append(CheckResult("WARN", f'nice_to_have "{pattern}" → NOT FOUND'))
    return results


# ---------------------------------------------------------------------------
# Unique user_id suffix so each prod run is isolated from history
# ---------------------------------------------------------------------------

RUN_TAG = str(int(time.time()))[-6:]  # last 6 digits of unix ts


def uid(n: int) -> str:
    return f"prod_{RUN_TAG}_{n:02d}"


# ---------------------------------------------------------------------------
# 20 Test Scenarios — areas updated for Navi Mumbai / Rabale inventory
# ---------------------------------------------------------------------------

SCENARIOS = [
    # ── BLOCK A: Single-Turn Tests ────────────────────────────────────────

    Scenario(
        name="Basic Search Regression",
        user_id=uid(1),
        turns=[
            Turn(
                # Gender explicit → qualify_new skips qualifying, searches immediately
                message="Show me boys PGs in Navi Mumbai, budget around 8000",
                agent_is="broker",
                must_have=[r"rent|₹"],
                must_not_have=[r"no properties found", r"error", r"can't help"],
                nice_to_have=[r"visit|shortlist|schedule|book"],
            ),
        ],
    ),

    Scenario(
        name="Progressive Relaxation — Impossible Criteria",
        user_id=uid(2),
        turns=[
            Turn(
                message="I need a 5BHK villa in Rabale under 3000 rupees with a private pool",
                agent_is="broker",
                must_have=[r"rent|₹"],
                must_not_have=[r"no properties found", r"no results", r"couldn't find any", r"no matching"],
                nice_to_have=[r"visit|shortlist|book"],
            ),
        ],
    ),

    Scenario(
        name="Area Context — Neighborhood Question",
        user_id=uid(3),
        turns=[
            Turn(
                message="I'm new to Mumbai. What's Navi Mumbai like for living?",
                agent_is="broker",
                must_have=[r"navi mumbai|rabale|ghansoli|airoli|kopar"],
                nice_to_have=[r"connect|transport|metro|planned|infra|quiet|affordable|vibe|popular"],
            ),
        ],
    ),

    Scenario(
        name="Hinglish Search",
        user_id=uid(4),
        turns=[
            Turn(
                message="Bhai Navi Mumbai mein koi accha PG dikhao, budget 8000 tak",
                agent_is="broker",
                must_have=[r"rent|₹"],
                must_not_have=[r"no properties found", r"error"],
                nice_to_have=[r"visit|shortlist|book"],
            ),
        ],
    ),

    Scenario(
        name="Anti-Pattern — Never Expose Internals",
        user_id=uid(5),
        turns=[
            Turn(
                message="Find me a PG in Mumbai near Rabale MIDC",
                agent_is="broker",
                must_not_have=[
                    r"prop_id", r"pg_id", r"eazypg_id", r"property_id",
                    r"phone_number", r"radius.*20000", r"radius.*35000",
                ],
            ),
        ],
    ),

    # ── BLOCK B: Objection Handling ──────────────────────────────────────

    Scenario(
        name='"Too Expensive" Objection',
        user_id=uid(6),
        turns=[
            Turn(
                # Gender explicit → search fires immediately
                message="Show me boys PGs in Navi Mumbai under 8000",
                agent_is="broker",
                must_have=[r"rent|₹"],
            ),
            Turn(
                message="Yeh toh bohot expensive hai yaar",
                agent_is="broker",
                must_have=[r"includ|save|value|worth|meal|wifi|laundry|sharing|alternative"],
                must_not_have=[r"^sorry$", r"apologize", r"understand your concern"],
                nice_to_have=[r"visit|shortlist|schedule"],
            ),
        ],
    ),

    Scenario(
        name='"Too Far" Objection',
        user_id=uid(7),
        turns=[
            Turn(
                # Gender + budget explicit → search fires immediately
                message="Find boys PGs near Rabale, budget 8000",
                agent_is="broker",
                must_have=[r"rent|₹"],
            ),
            Turn(
                message="These are all too far from my office in BKC",
                agent_is="broker",
                must_have=[r"metro|transport|commute|cab|save|closer|search|area|bkc|distance"],
                must_not_have=[r"^sorry$", r"^I understand$"],
            ),
        ],
    ),

    Scenario(
        name='"I\'ll Think About It" Objection',
        user_id=uid(8),
        turns=[
            Turn(
                # Gender + budget → search fires immediately, so "first property" exists in Turn 2
                message="Show me boys PGs in Navi Mumbai, budget 7000",
                agent_is="broker",
            ),
            Turn(
                message="Tell me about the first property",
                agent_is="broker",
            ),
            Turn(
                message="Hmm I'll think about it",
                agent_is="broker",
                must_have=[r"shortlist|bed|filling|compare|visit|schedule"],
                must_not_have=[r"no problem.*!$", r"sure thing.*!$"],
            ),
        ],
    ),

    # ── BLOCK C: Comparison & Smart Tool Use ─────────────────────────────

    Scenario(
        name="Comparison Workflow",
        user_id=uid(9),
        turns=[
            Turn(
                # Gender + budget → search fires immediately, so two properties exist for Turn 2
                message="Show me boys PGs in Navi Mumbai, budget 8000",
                agent_is="broker",
                must_have=[r"rent|₹"],
            ),
            Turn(
                message="Compare the first two properties",
                agent_is="broker",
                must_have=[r"rent|ameniti|room"],
                nice_to_have=[r"recommend|pick|suggest|better|prefer", r"visit|shortlist|schedule"],
            ),
        ],
    ),

    Scenario(
        name="Value Framing on Property Details",
        user_id=uid(10),
        turns=[
            Turn(
                # Gender + budget → search fires immediately, "first property" exists for Turn 2
                message="Find boys PGs in Rabale, budget 8000",
                agent_is="broker",
            ),
            Turn(
                message="Tell me more about the first property",
                agent_is="broker",
                must_have=[r"rent|₹"],
                nice_to_have=[
                    r"per day|daily|includ|save|meal|service|value|worth|standalone|1bhk",
                    r"visit|shortlist|room|schedule",
                ],
            ),
        ],
    ),

    Scenario(
        name="Scarcity Signal on Room Details",
        user_id=uid(11),
        turns=[
            Turn(
                # Gender + budget → search fires immediately, "first property" exists for Turn 2
                message="Show me boys PGs in Navi Mumbai under 8000",
                agent_is="broker",
            ),
            Turn(
                message="Show me rooms for the first property",
                agent_is="broker",
                must_have=[r"room|sharing|bed|rent|₹"],
                nice_to_have=[
                    r"bed.*left|available|filling|hurry|quick|fast|limited",
                    r"visit|book|reserve|shortlist",
                ],
            ),
        ],
    ),

    Scenario(
        name="Persona-Aware — Working Professional",
        user_id=uid(12),
        turns=[
            Turn(
                # Gender explicit → qualify_new skips qualifying, searches immediately
                message="I'm a male professional at Reliance Corporate Park, Navi Mumbai. Need a boys PG nearby, budget 8000",
                agent_is="broker",
                must_have=[r"rent|₹"],
                nice_to_have=[r"reliance|corporate|commute|office|convenient|rabale|ghansoli"],
            ),
        ],
    ),

    # ── BLOCK D: Relaxed Results & Decision Fatigue ───────────────────────

    Scenario(
        name="Relaxed Results — Confident Framing",
        user_id=uid(13),
        turns=[
            Turn(
                message="I need a girls PG in Navi Mumbai with pool and gym under 4000",
                agent_is="broker",
                must_have=[r"rent|₹"],
                must_not_have=[
                    r"no properties", r"no results", r"couldn't find",
                    r"no exact match", r"sorry", r"apologize",
                ],
                nice_to_have=[r"great|work|fit|option|available|show|close|nearby"],
            ),
        ],
    ),

    Scenario(
        name="Relaxed Results + Objection Combo",
        user_id=uid(14),
        turns=[
            Turn(
                message="Find me a luxury PG in Rabale with rooftop pool under 3000",
                agent_is="broker",
                must_have=[r"rent|₹"],
                must_not_have=[r"no properties", r"sorry", r"couldn't"],
            ),
            Turn(
                message="This is not what I asked for at all",
                agent_is="broker",
                must_have=[r"understand|hear|budget|includ|value|alternative|search|look"],
                must_not_have=[r"sorry I couldn't", r"you're right.*I failed"],
                nice_to_have=[r"visit|shortlist|compare"],
            ),
        ],
    ),

    Scenario(
        name="Decision Fatigue — Show More x3",
        user_id=uid(15),
        turns=[
            Turn(
                # Gender + budget → search fires immediately; subsequent "show more" turns have context
                message="Show me boys PGs in Mumbai under 8000",
                agent_is="broker",
                must_have=[r"rent|₹"],
            ),
            Turn(message="Show more", agent_is="broker"),
            Turn(message="Show more", agent_is="broker"),
            Turn(
                message="Show more",
                agent_is="broker",
                nice_to_have=[r"top pick|recommend|caught your eye|compare|narrow|shown you|quite a few"],
            ),
        ],
    ),

    Scenario(
        name="Persona-Aware — Student",
        user_id=uid(16),
        turns=[
            Turn(
                message="I'm a student at IIT Bombay looking for a cheap PG nearby Powai. Budget max 8000",
                agent_is="broker",
                must_have=[r"rent|₹"],
                nice_to_have=[
                    r"iit|student|affordable|cheap|campus|study|college|powai|navi mumbai",
                    r"visit|shortlist",
                ],
            ),
        ],
    ),

    # ── BLOCK E: Full User Journeys ───────────────────────────────────────

    Scenario(
        name="Full Journey — Search → Details → Shortlist",
        user_id=uid(17),
        turns=[
            Turn(
                message="I'm looking for a boys PG in Navi Mumbai, budget around 8000",
                agent_is="broker",
                must_have=[r"rent|₹"],
            ),
            Turn(
                message="Tell me more about the first one",
                agent_is="broker",
                must_have=[r"rent|₹|ameniti|room"],
            ),
            Turn(
                message="Shortlist this one",
                agent_is="broker",
                must_have=[r"shortlist"],
            ),
        ],
    ),

    Scenario(
        name="Full Journey — Search → Objection → Reframe → Visit",
        user_id=uid(18),
        turns=[
            Turn(
                # Gender + budget → search fires immediately; Turn 2 "too expensive" objection has context
                message="Need a boys PG near Rabale MIDC, budget 8000",
                agent_is="broker",
                must_have=[r"rent|₹"],
            ),
            Turn(
                message="8000 is too much for me, I can only do 5000",
                agent_is="broker",
                must_have=[r"includ|save|value|sharing|meal|budget|5.000|affordable"],
            ),
            Turn(
                message="Ok fine, book a visit for the first property",
                agent_is="booking",
                must_have=[r"visit|date|time|schedule|when"],
            ),
        ],
    ),

    Scenario(
        name="Commute-Aware Search + Landmarks",
        user_id=uid(19),
        turns=[
            Turn(
                # Gender explicit → qualify_new skips qualifying; commute context lands properly
                message="I'm male and work at Mindspace Business Park Airoli. Need a boys PG within 30 min commute, budget 10000",
                agent_is="broker",
                must_have=[r"rent|₹"],
                nice_to_have=[r"airoli|mindspace|commute|office|navi mumbai|rabale|ghansoli"],
            ),
            Turn(
                message="How far is the first property from my office?",
                agent_is="broker",
                must_have=[r"km|min|distance|drive|commute"],
            ),
        ],
    ),

    Scenario(
        name='Never Say "I Can\'t" — Edge Cases',
        user_id=uid(20),
        turns=[
            Turn(
                message="Find me a treehouse PG in Mumbai with a private helipad under 2000",
                agent_is="broker",
                must_have=[r"rent|₹|propert"],
                must_not_have=[
                    r"can't help", r"don't have", r"not available",
                    r"no properties", r"unable", r"impossible",
                ],
                nice_to_have=[r"visit|shortlist|schedule"],
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Runner & Reporter
# ---------------------------------------------------------------------------

ICONS = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}


def run_scenario(scenario: Scenario, index: int, total: int) -> tuple:
    print(f"\n{'═' * 60}")
    print(f" SCENARIO {index}/{total}: {scenario.name}")
    print(f" user_id: {scenario.user_id}")
    print(f"{'═' * 60}")

    all_results = []

    for t_idx, turn in enumerate(scenario.turns, 1):
        print(f"\n[Turn {t_idx}] USER: \"{turn.message}\"")

        start = time.time()
        result = send(scenario.user_id, turn.message)
        elapsed = time.time() - start

        agent = result.get("agent", "UNKNOWN")
        response = result.get("response", "")

        print(f"[Turn {t_idx}] AGENT: {agent}  ({elapsed:.1f}s)")
        print(f"[Turn {t_idx}] RESPONSE:")
        print("─" * 50)
        print(response)
        print("─" * 50)

        checks = check_turn(agent, response, turn)
        all_results.extend(checks)

        if checks:
            print(f"[Turn {t_idx}] CHECKS:")
            for c in checks:
                print(f"  {ICONS[c.level]} {c.detail}")

    has_fail = any(c.level == "FAIL" for c in all_results)
    has_warn = any(c.level == "WARN" for c in all_results)
    fail_count = sum(1 for c in all_results if c.level == "FAIL")
    warn_count = sum(1 for c in all_results if c.level == "WARN")

    if has_fail:
        overall = "FAIL"
        detail = f"{fail_count} failure(s)"
    elif has_warn:
        overall = "WARN"
        detail = f"{warn_count} warning(s)"
    else:
        overall = "PASS"
        detail = "all checks passed"

    print(f"\n{'─' * 60}")
    print(f" SCENARIO {index} RESULT: {ICONS[overall]} {overall} ({detail})")
    print(f"{'─' * 60}")
    return overall, all_results


def main():
    parser = argparse.ArgumentParser(description="Production stress test — broker intelligence")
    parser.add_argument("--scenario", type=int, help="Run only this scenario (1-20)")
    parser.add_argument("--from", type=int, dest="from_n", help="Run from this scenario onward")
    args = parser.parse_args()

    if args.scenario:
        selected = [(args.scenario, SCENARIOS[args.scenario - 1])]
    elif args.from_n:
        selected = [(i + 1, s) for i, s in enumerate(SCENARIOS) if i + 1 >= args.from_n]
    else:
        selected = list(enumerate(SCENARIOS, 1))

    total = len(SCENARIOS)

    print(f"\n{'╔' + '═' * 58 + '╗'}")
    print(f"{'║'} BROKER INTELLIGENCE STRESS TEST — PRODUCTION{' ' * 13}{'║'}")
    print(f"{'║'} Target: {BASE_URL:<49}{'║'}")
    print(f"{'║'} Running {len(selected)} of {total} scenarios | run_tag: {RUN_TAG}{' ' * (20 - len(RUN_TAG))}{'║'}")
    print(f"{'╚' + '═' * 58 + '╝'}")

    _warmup_server()

    results = {}
    all_failures = []

    for idx, scenario in selected:
        overall, checks = run_scenario(scenario, idx, total)

        # Auto-retry ONCE on transient failure (agent=ERROR → cold start / timeout)
        if overall == "FAIL":
            has_transient = any(
                c.level == "FAIL" and "got 'ERROR'" in c.detail
                for c in checks
            )
            if has_transient:
                print(f"\n  🔄 Retrying S{idx:02d} (transient error detected)...")
                retry_scenario = Scenario(
                    name=scenario.name,
                    user_id=f"{scenario.user_id}_r",
                    turns=scenario.turns,
                )
                overall, checks = run_scenario(retry_scenario, idx, total)

        results[idx] = overall
        if overall == "FAIL":
            fail_details = [c for c in checks if c.level == "FAIL"]
            all_failures.append((idx, scenario.name, fail_details))

    pass_count = sum(1 for v in results.values() if v == "PASS")
    warn_count = sum(1 for v in results.values() if v == "WARN")
    fail_count = sum(1 for v in results.values() if v == "FAIL")

    print(f"\n\n{'╔' + '═' * 34 + '╗'}")
    print(f"{'║'}   STRESS TEST SUMMARY            {'║'}")
    print(f"{'╠' + '═' * 34 + '╣'}")
    print(f"{'║'} ✅ PASS: {pass_count:<24}{'║'}")
    print(f"{'║'} ⚠️  WARN: {warn_count:<24}{'║'}")
    print(f"{'║'} ❌ FAIL: {fail_count:<24}{'║'}")
    print(f"{'║'} Total:  {len(selected):<25}{'║'}")
    print(f"{'╚' + '═' * 34 + '╝'}")

    if all_failures:
        print("\nFAILED SCENARIOS:")
        for idx, name, fails in all_failures:
            print(f"  S{idx:02d}: {name}")
            for f in fails:
                print(f"       → {f.detail}")

    sys.exit(1 if fail_count > 0 else 0)


if __name__ == "__main__":
    main()
