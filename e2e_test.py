#!/usr/bin/env python3
"""E2E Test Runner — sends a single message and prints agent + response."""
import json
import sys
import urllib.request

BASE_URL = "http://localhost:8000/chat"
USER_ID = "e2e_test_01"

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


def send(message: str) -> dict:
    payload = json.dumps({
        "user_id": USER_ID,
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"agent": "ERROR", "response": str(e)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 e2e_test.py 'message'")
        sys.exit(1)

    msg = sys.argv[1]
    result = send(msg)
    agent = result.get("agent", "UNKNOWN")
    response = result.get("response", "")
    # Print first 400 chars of response
    print(f"AGENT: {agent}")
    print(f"RESPONSE: {response[:400]}")
