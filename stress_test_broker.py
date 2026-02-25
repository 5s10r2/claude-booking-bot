#!/usr/bin/env python3
"""
Stress Test: Broker Intelligence Capabilities
Tests all 11 new features: progressive relaxation, comparison workflow,
objection handling, value framing, scarcity, area context, decision fatigue,
smart tool use, persona-aware selling, and more.

Usage:
    python3 stress_test_broker.py              # Run all 20 scenarios
    python3 stress_test_broker.py --scenario 5 # Run only scenario 5
    python3 stress_test_broker.py --from 15    # Run scenarios 15-20
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:8000/chat"
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
    "areas": "Andheri, Kurla, Powai",
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
    turns: list  # list[Turn]


@dataclass
class CheckResult:
    level: str   # PASS, WARN, FAIL
    detail: str


# ---------------------------------------------------------------------------
# HTTP + Redis helpers
# ---------------------------------------------------------------------------

def send(user_id: str, message: str) -> dict:
    """Send a message to the chat API and return {agent, response}."""
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
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"agent": "ERROR", "response": str(e)}


def cleanup(user_id: str):
    """Clear all Redis state for a test user."""
    try:
        import redis as redis_lib
        r = redis_lib.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=os.getenv("REDIS_PASSWORD", None),
            decode_responses=False,
        )
        for suffix in [
            ":conversation", ":preferences", ":preferences:json",
            ":property_info_map", ":last_agent", ":account_values", ":pg_ids",
        ]:
            r.delete(f"{user_id}{suffix}")
    except ImportError:
        print("  [cleanup] WARNING: redis package not installed, skipping cleanup")
    except Exception as e:
        print(f"  [cleanup] WARNING: {e}")


# ---------------------------------------------------------------------------
# Assertion engine
# ---------------------------------------------------------------------------

def check_pattern(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, re.IGNORECASE))


def check_turn(agent: str, response: str, turn: Turn) -> list:
    """Run all assertions for a single turn. Returns list of CheckResult."""
    results = []

    # Agent check
    if turn.agent_is:
        if agent.lower() == turn.agent_is.lower():
            results.append(CheckResult("PASS", f"agent == {turn.agent_is}"))
        else:
            results.append(CheckResult("FAIL", f"agent: expected '{turn.agent_is}', got '{agent}'"))

    # must_have: ALL must match
    for pattern in turn.must_have:
        if check_pattern(response, pattern):
            results.append(CheckResult("PASS", f'must_have "{pattern}" → FOUND'))
        else:
            results.append(CheckResult("FAIL", f'must_have "{pattern}" → NOT FOUND'))

    # must_not_have: NONE should match
    for pattern in turn.must_not_have:
        if check_pattern(response, pattern):
            results.append(CheckResult("FAIL", f'must_not_have "{pattern}" → FOUND (bad!)'))
        else:
            results.append(CheckResult("PASS", f'must_not_have "{pattern}" → CLEAN'))

    # nice_to_have: miss = WARN
    for pattern in turn.nice_to_have:
        if check_pattern(response, pattern):
            results.append(CheckResult("PASS", f'nice_to_have "{pattern}" → FOUND'))
        else:
            results.append(CheckResult("WARN", f'nice_to_have "{pattern}" → NOT FOUND'))

    return results


# ---------------------------------------------------------------------------
# 20 Test Scenarios
# ---------------------------------------------------------------------------

SCENARIOS = [
    # ── BLOCK A: Single-Turn Tests ──────────────────────────────────────

    Scenario(
        name="Basic Search Regression",
        user_id="stress_01",
        turns=[
            Turn(
                message="Show me PGs in Andheri",
                agent_is="broker",
                must_have=[r"rent|₹", r"andheri"],
                must_not_have=[r"no properties found", r"error", r"can't help"],
                nice_to_have=[r"visit|shortlist|schedule|book"],
            ),
        ],
    ),

    Scenario(
        name="Progressive Relaxation — Impossible Criteria",
        user_id="stress_02",
        turns=[
            Turn(
                message="I need a 5BHK villa in Kurla under 3000 rupees",
                agent_is="broker",
                must_have=[r"rent|₹"],
                must_not_have=[r"no properties found", r"no results", r"couldn't find any", r"no matching"],
                nice_to_have=[r"visit|shortlist|book"],
            ),
        ],
    ),

    Scenario(
        name="Area Context — Neighborhood Question",
        user_id="stress_03",
        turns=[
            Turn(
                message="I'm new to Mumbai. What's Powai like for living?",
                agent_is="broker",
                must_have=[r"powai"],
                nice_to_have=[r"connect|transport|metro|lake|iit|known for|popular|vibe"],
            ),
        ],
    ),

    Scenario(
        name="Hinglish Search",
        user_id="stress_04",
        turns=[
            Turn(
                message="Bhai Andheri mein koi accha PG dikhao, budget 15000 tak",
                agent_is="broker",
                must_have=[r"rent|₹"],
                must_not_have=[r"no properties found", r"error"],
                nice_to_have=[r"visit|shortlist|book"],
            ),
        ],
    ),

    Scenario(
        name="Anti-Pattern — Never Expose Internals",
        user_id="stress_05",
        turns=[
            Turn(
                message="Find me a PG in Mumbai near Kurla station",
                agent_is="broker",
                must_not_have=[
                    r"prop_id", r"pg_id", r"eazypg_id", r"property_id",
                    r"phone_number", r"radius.*20000", r"radius.*35000",
                ],
            ),
        ],
    ),

    # ── BLOCK B: Objection Handling ─────────────────────────────────────

    Scenario(
        name='"Too Expensive" Objection',
        user_id="stress_06",
        turns=[
            Turn(
                message="Show me PGs in Andheri under 8000",
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
        user_id="stress_07",
        turns=[
            Turn(
                message="Find PGs near Powai",
                agent_is="broker",
                must_have=[r"rent|₹"],
            ),
            Turn(
                message="These are all too far from my office",
                agent_is="broker",
                must_have=[r"metro|transport|commute|cab|save|closer|search|area"],
                must_not_have=[r"^sorry$", r"^I understand$"],
            ),
        ],
    ),

    Scenario(
        name='"I\'ll Think About It" Objection',
        user_id="stress_08",
        turns=[
            Turn(
                message="Show me PGs in Kurla",
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

    # ── BLOCK C: Comparison & Smart Tool Use ────────────────────────────

    Scenario(
        name="Comparison Workflow",
        user_id="stress_09",
        turns=[
            Turn(
                message="Show me PGs in Mumbai",
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
        user_id="stress_10",
        turns=[
            Turn(
                message="Find PGs in Andheri",
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
        user_id="stress_11",
        turns=[
            Turn(
                message="Show PGs in Mumbai",
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
        user_id="stress_12",
        turns=[
            Turn(
                message="I work at Reliance Corporate Park in Navi Mumbai. Need a PG nearby, budget 15000",
                agent_is="broker",
                must_have=[r"rent|₹"],
                nice_to_have=[r"reliance|corporate|commute|office|convenient"],
            ),
        ],
    ),

    # ── BLOCK D: Relaxed Results & Decision Fatigue ─────────────────────

    Scenario(
        name="Relaxed Results — Confident Framing",
        user_id="stress_13",
        turns=[
            Turn(
                message="I need a girls PG in Borivali with pool and gym under 5000",
                agent_is="broker",
                must_have=[r"rent|₹"],
                must_not_have=[
                    r"no properties", r"no results", r"couldn't find",
                    r"no exact match", r"sorry", r"apologize",
                ],
                nice_to_have=[r"great|work|fit|option|available|show"],
            ),
        ],
    ),

    Scenario(
        name="Relaxed Results + Objection Combo",
        user_id="stress_14",
        turns=[
            Turn(
                message="Find me a luxury PG in Dadar with rooftop pool under 4000",
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
        user_id="stress_15",
        turns=[
            Turn(
                message="Show PGs in Mumbai",
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
        user_id="stress_16",
        turns=[
            Turn(
                message="I'm a student at IIT Bombay looking for a cheap PG nearby. Budget max 8000",
                agent_is="broker",
                must_have=[r"rent|₹"],
                nice_to_have=[
                    r"iit|student|affordable|cheap|campus|study|college|powai",
                    r"visit|shortlist",
                ],
            ),
        ],
    ),

    # ── BLOCK E: Full User Journeys ─────────────────────────────────────

    Scenario(
        name="Full Journey — Search → Details → Shortlist",
        user_id="stress_17",
        turns=[
            Turn(
                message="I'm looking for a boys PG in Andheri, budget around 12000",
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
        user_id="stress_18",
        turns=[
            Turn(
                message="Need a PG near Kurla station",
                agent_is="broker",
                must_have=[r"rent|₹"],
            ),
            Turn(
                message="12000 is too much for me",
                agent_is="broker",
                must_have=[r"includ|save|value|sharing|meal|budget"],
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
        user_id="stress_19",
        turns=[
            Turn(
                message="I work at BKC, need a PG within 30 min commute. Budget 15000",
                agent_is="broker",
                must_have=[r"rent|₹"],
                nice_to_have=[r"bkc|commute|office"],
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
        user_id="stress_20",
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


def run_scenario(scenario: Scenario, index: int, total: int) -> str:
    """Run a single scenario. Returns overall result: PASS, WARN, or FAIL."""
    print(f"\n{'═' * 50}")
    print(f" SCENARIO {index}/{total}: {scenario.name}")
    print(f" user_id: {scenario.user_id}")
    print(f"{'═' * 50}")

    cleanup(scenario.user_id)

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
        print("---")
        print(response)
        print("---")

        checks = check_turn(agent, response, turn)
        all_results.extend(checks)

        if checks:
            print(f"[Turn {t_idx}] CHECKS:")
            for c in checks:
                print(f"  {ICONS[c.level]} {c.detail}")

    # Determine overall result
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

    print(f"\n--- SCENARIO {index} RESULT: {ICONS[overall]} {overall} ({detail}) ---")
    return overall, all_results


def main():
    parser = argparse.ArgumentParser(description="Stress test broker intelligence")
    parser.add_argument("--scenario", type=int, help="Run only this scenario number (1-20)")
    parser.add_argument("--from", type=int, dest="from_n", help="Run from this scenario number onward")
    args = parser.parse_args()

    # Select scenarios
    if args.scenario:
        if args.scenario < 1 or args.scenario > len(SCENARIOS):
            print(f"Invalid scenario number. Must be 1-{len(SCENARIOS)}")
            sys.exit(1)
        selected = [(args.scenario, SCENARIOS[args.scenario - 1])]
    elif args.from_n:
        if args.from_n < 1 or args.from_n > len(SCENARIOS):
            print(f"Invalid --from number. Must be 1-{len(SCENARIOS)}")
            sys.exit(1)
        selected = [(i + 1, s) for i, s in enumerate(SCENARIOS) if i + 1 >= args.from_n]
    else:
        selected = [(i + 1, s) for i, s in enumerate(SCENARIOS)]

    total = len(SCENARIOS)

    print(f"\n{'╔' + '═' * 48 + '╗'}")
    print(f"{'║'} BROKER INTELLIGENCE STRESS TEST{' ' * 17}{'║'}")
    print(f"{'║'} Running {len(selected)} of {total} scenarios{' ' * (30 - len(str(len(selected))) - len(str(total)))}{'║'}")
    print(f"{'╚' + '═' * 48 + '╝'}")

    results = {}
    all_failures = []

    for idx, scenario in selected:
        overall, checks = run_scenario(scenario, idx, total)
        results[idx] = overall
        if overall == "FAIL":
            fail_details = [c for c in checks if c.level == "FAIL"]
            all_failures.append((idx, scenario.name, fail_details))

    # Summary
    pass_count = sum(1 for v in results.values() if v == "PASS")
    warn_count = sum(1 for v in results.values() if v == "WARN")
    fail_count = sum(1 for v in results.values() if v == "FAIL")

    print(f"\n\n{'╔' + '═' * 30 + '╗'}")
    print(f"{'║'}   STRESS TEST SUMMARY        {'║'}")
    print(f"{'╠' + '═' * 30 + '╣'}")
    print(f"{'║'} ✅ PASS: {pass_count:<20}{'║'}")
    print(f"{'║'} ⚠️  WARN: {warn_count:<20}{'║'}")
    print(f"{'║'} ❌ FAIL: {fail_count:<20}{'║'}")
    print(f"{'║'} Total:  {len(selected):<21}{'║'}")
    print(f"{'╚' + '═' * 30 + '╝'}")

    if all_failures:
        print("\nFAILED SCENARIOS:")
        for idx, name, fails in all_failures:
            print(f"  S{idx:02d}: {name}")
            for f in fails:
                print(f"       → {f.detail}")

    # Exit code: 0 if no FAIL, 1 otherwise
    sys.exit(1 if fail_count > 0 else 0)


if __name__ == "__main__":
    main()
