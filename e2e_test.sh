#!/bin/bash
# E2E Test Helper - sends messages to the chat API
# Usage: ./e2e_test.sh "message text"

MESSAGE="$1"
USER_ID="${2:-e2e_test_01}"

# Write JSON payload to a temp file to avoid shell escaping issues
cat > /tmp/e2e_payload.json << 'ENDJSON'
{
  "user_id": "USER_ID_PLACEHOLDER",
  "message": "MSG_PLACEHOLDER",
  "account_values": {
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
      "Ei1CXqVU2gQPGo2GKRKfLYk53Yl2"
    ],
    "brand_name": "OxOtel",
    "cities": "Mumbai",
    "areas": "Andheri, Kurla, Powai"
  }
}
ENDJSON

# Replace placeholders with actual values using python for safe JSON manipulation
/opt/anaconda3/bin/python3 -c "
import json, sys
with open('/tmp/e2e_payload.json') as f:
    data = json.load(f)
data['user_id'] = '$USER_ID'
data['message'] = '''$MESSAGE'''
with open('/tmp/e2e_payload.json', 'w') as f:
    json.dump(data, f)
"

# Send request
RESPONSE=$(curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d @/tmp/e2e_payload.json)

# Extract agent and response
AGENT=$(/opt/anaconda3/bin/python3 -c "import json,sys; d=json.loads('''$RESPONSE'''); print(d.get('agent','UNKNOWN'))" 2>/dev/null || echo "PARSE_ERROR")
RESP=$(/opt/anaconda3/bin/python3 -c "import json,sys; d=json.loads('''$RESPONSE'''); print(d.get('response','')[:300])" 2>/dev/null || echo "$RESPONSE")

echo "AGENT: $AGENT"
echo "RESPONSE: $RESP"
