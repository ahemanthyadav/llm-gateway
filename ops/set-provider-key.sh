#!/bin/bash
# set-provider-key.sh <provider-field> <env-file> <VARIABLE>
#   Copies a provider API key from a local, gitignored env file into Secret llm/llm-gateway
#   without printing it, then restarts the gateway.
#   e.g.  ops/set-provider-key.sh nvidia-nim-api-key ../marketdata/.secrets.env LLM_API_KEY
#   Adding a provider = a field here + an env entry in manifests/gateway.yaml + models in config.
#   Supported providers: nvidia-nim-api-key, google-ai-key, groq-api-key, etc.
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"
FIELD=$1 FILE=$2 VAR=$3
# Validate field name format (should be a valid Kubernetes secret key)
if ! echo "$FIELD" | grep -qE '^[a-zA-Z][a-zA-Z0-9_-]*$'; then
  echo "ERROR: Invalid field name '$FIELD' — must be alphanumeric, hyphens, or underscores" >&2
  exit 2
fi
# Validate the env file exists
if [ ! -f "$FILE" ]; then
  echo "ERROR: Env file '$FILE' not found" >&2
  exit 2
fi
# Extract the variable value from the env file
VAL=$(python3 - "$FILE" "$VAR" <<'EOF'
import sys
path, var = sys.argv[1], sys.argv[2]
found = False
for line in open(path):
    line = line.strip()
    if line.startswith(var + "="):
        v = line.split("=", 1)[1].split(" #")[0].strip().strip('"').strip("'")
        print(v, end="")
        found = True
        break
if not found:
    print("", end="")
EOF
)
[ -n "$VAL" ] || { echo "$VAR is empty or missing in $FILE" >&2; exit 2; }
# Base64 encode the value for Kubernetes secret
B64=$(printf '%s' "$VAL" | base64 -w0); unset VAL
# Patch the secret - merge the new field value
kubectl -n llm patch secret llm-gateway --type merge -p "{\"data\":{\"$FIELD\":\"$B64\"}}" >/dev/null; unset B64
# Restart the gateway so it picks up the new provider key
kubectl -n llm rollout restart deployment/llm-gateway >/dev/null
kubectl -n llm rollout status deployment/llm-gateway --timeout=600s
# Map known provider fields for documentation
KNOWN_FIELDS="nvidia-nim-api-key google-ai-key groq-api-key cloudflare-api-key github-api-key cerebras-api-key openrouter-api-key ollama-api-key ollama-base-url"
if echo " $KNOWN_FIELDS " | grep -q " $FIELD "; then
  echo "$FIELD set (value not shown); gateway restarted"
else
  echo "$FIELD set in secret (value not shown); gateway restarted — see manifests/gateway.yaml for provider configuration"
fi