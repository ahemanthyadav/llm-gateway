#!/bin/bash
# set-provider-key.sh <secret-field> <env-file> <VARIABLE>
#   Copies a provider API key from a local, gitignored env file into Secret llm/llm-gateway
#   without printing it, then restarts the gateway.
#   e.g.  ops/set-provider-key.sh nvidia-nim-api-key ../marketdata/.secrets.env LLM_API_KEY
# Adding a provider = a field here + an env entry in manifests/gateway.yaml + models in config.
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"
FIELD=$1 FILE=$2 VAR=$3
VAL=$(python3 - "$FILE" "$VAR" <<'EOF'
import sys
path, var = sys.argv[1], sys.argv[2]
for line in open(path):
    line = line.strip()
    if line.startswith(var + "="):
        v = line.split("=", 1)[1].split(" #")[0].strip().strip('"').strip("'")
        print(v, end="")
        break
EOF
)
[ -n "$VAL" ] || { echo "$VAR is empty or missing in $FILE" >&2; exit 2; }
B64=$(printf '%s' "$VAL" | base64 -w0); unset VAL
kubectl -n llm patch secret llm-gateway --type merge -p "{\"data\":{\"$FIELD\":\"$B64\"}}" >/dev/null; unset B64
kubectl -n llm rollout restart deployment/llm-gateway >/dev/null
kubectl -n llm rollout status deployment/llm-gateway --timeout=600s
echo "$FIELD set (value not shown); gateway restarted"
