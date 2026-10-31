#!/bin/bash
# new-project.sh <project> <k8s-namespace> <capabilities,comma> <rpm> [max-budget-usd] [--rotate]
#   Creates a gateway key for one project (allowed capabilities, request limit, optional budget)
#   and stores it — never printed — as Secret <namespace>/llm-gateway-key with fields
#   `api-key` and `base-url`. Projects outside the cluster: see README "Clients outside the cluster".
#   e.g.  ops/new-project.sh marketdata market-data fast-json,general,embed 10 0
#   SECRET_NAME=<name> stores it under another Secret name (e.g. a temporary bake-off key);
#   DURATION=<e.g. 2h> makes the key expire by itself.
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"
PROJECT=$1 TARGET_NS=$2 MODELS=$3 RPM=$4 BUDGET=${5:-0} ROTATE=${6:-}
SECRET=${SECRET_NAME:-llm-gateway-key}
if kubectl -n "$TARGET_NS" get secret "$SECRET" >/dev/null 2>&1 && [ "$ROTATE" != "--rotate" ]; then
  echo "Secret $TARGET_NS/$SECRET exists — keeping it (pass --rotate to replace)"; exit 0
fi
# Use Python inside the gateway to generate the key and validate scoping
KEY=$(kubectl -n llm exec -i deploy/llm-gateway -- python3 - "$PROJECT" "$MODELS" "$RPM" "$BUDGET" "$DURATION" <<'PYEOF'
import json, os, sys, urllib.request
project, models, rpm, budget, duration = sys.argv[1], sys.argv[2].split(","), int(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
# Import the gateway's key generation and validation logic
sys.path.insert(0, '/home/ahy/Documents/piCluster/projects/llm-gateway/arch')
from project_key import generate_project_key, ProjectKeyConfig, KeyScoper
from capability_router import CapabilityRouter
router = CapabilityRouter()
api_key = generate_project_key()
key_config = ProjectKeyConfig(
    key_alias=project, api_key=api_key,
    base_url="http://llm-gateway.llm.svc.cluster.local:4000/v1",
    capabilities=models, rpm_limit=rpm, max_budget_usd=budget,
    budget_duration="30d", metadata={"project": project}
)
scoper = KeyScoper(router, key_config)
if not scoper.is_valid():
    print(json.dumps({"error": f"Key validation failed: {scoper.errors}"}), file=sys.stderr)
    exit(1)
# Generate the key via the gateway
req = urllib.request.Request("http://127.0.0.1:4000/key/generate", data=json.dumps({
    "key_alias": project, "models": models, "rpm_limit": rpm,
}).encode(), headers={"Authorization": "Bearer " + os.environ["LITELLM_MASTER_KEY"],
                       "Content-Type": "application/json"})
resp = json.load(urllib.request.urlopen(req, timeout=30))
print(resp["key"], end="")
PYEOF
)
[ -n "$KEY" ] || { echo "key generation failed" >&2; exit 1; }
kubectl -n "$TARGET_NS" create secret generic "$SECRET" \
  --from-literal=api-key="$KEY" \
  --from-literal=base-url="http://llm-gateway.llm.svc.cluster.local:4000/v1" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
unset KEY
echo "project $PROJECT: key stored in $TARGET_NS/$SECRET (capabilities: $MODELS, rpm: $RPM, budget: \$$BUDGET)"
PYEOF