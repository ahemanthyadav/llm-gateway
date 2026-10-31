#!/bin/bash
# probe-models.sh --provider <nvidia|google|groq|...> --models <id1,id2,...> [--key-field <secret-field>]
#   Probes each model for availability (404 "not found for account" means unusable on this account).
#   Exits non-zero if any model is unreachable — do not add unreachable models to config/litellm.yaml.
#   Requires a provider API key already set in Secret llm/llm-gateway.
#   e.g.  ops/probe-models.sh --provider nvidia --models nemotron-3.5-lightning-30b-a3b,kimi-k2.6
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"

PROVIDER=""
MODELS=""
KEY_FIELD="nvidia-nim-api-key"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider) PROVIDER="$2"; shift 2 ;;
    --models)   MODELS="$2"; shift 2 ;;
    --key-field) KEY_FIELD="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

[ -n "$PROVIDER" ] || { echo "ERROR: --provider required" >&2; exit 2; }
[ -n "$MODELS" ] || { echo "ERROR: --models required" >&2; exit 2; }

API_KEY=$(kubectl -n llm get secret llm-gateway -o jsonpath="{.data.${KEY_FIELD}}" | base64 -d 2>/dev/null || true)
[ -n "$API_KEY" ] || { echo "ERROR: key field $KEY_FIELD not found in Secret llm-gateway" >&2; exit 2; }

FAIL=0
for model in $(echo "$MODELS" | tr ',' ' '); do
  CODE=$(kubectl -n llm exec -i deploy/llm-gateway -- python3 - "$PROVIDER" "$model" "$API_KEY" <<'PYEOF'
import json, sys, urllib.request, urllib.error
provider, model, api_key = sys.argv[1], sys.argv[2], sys.argv[3]
# Try a minimal completion to see if the model is reachable
body = json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}).encode()
req = urllib.request.Request("http://127.0.0.1:4000/v1/chat/completions",
                             data=body,
                             headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"{model}: reachable (HTTP {r.status})")
except urllib.error.HTTPError as e:
    body_text = (e.read() or b"").decode()[:200]
    if e.code == 404 and "not found" in body_text.lower():
        print(f"{model}: NOT FOUND for this account (404) — do not add to config")
    else:
        print(f"{model}: HTTP {e.code} — {body_text}")
    sys.exit(1)
except Exception as e:
    print(f"{model}: ERROR — {e}")
    sys.exit(1)
PYEOF
  ) || FAIL=1
  echo "$CODE"
done

if [ "$FAIL" -ne 0 ]; then
  echo "One or more models are unreachable — do not add them to config/litellm.yaml" >&2
  exit 1
fi
echo "All probed models are reachable"
