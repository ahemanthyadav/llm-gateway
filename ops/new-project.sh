#!/bin/bash
# new-project.sh <project> <namespace> <capabilities,comma> <rpm> [max-budget-usd] [--rotate]
#   Creates a gateway key for one project (allowed capabilities, request limit, optional budget)
#   and stores it — never printed — as Secret <namespace>/llm-gateway-key with fields
#   `api-key` and `base-url`. Projects outside the cluster: see README "Clients outside the cluster".
#   e.g.  ops/new-project.sh marketdata market-data fast-json,general,embed 10 0
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"
PROJECT=$1 TARGET_NS=$2 MODELS=$3 RPM=$4 BUDGET=${5:-0} ROTATE=${6:-}
if kubectl -n "$TARGET_NS" get secret llm-gateway-key >/dev/null 2>&1 && [ "$ROTATE" != "--rotate" ]; then
  echo "Secret $TARGET_NS/llm-gateway-key exists — keeping it (pass --rotate to replace)"; exit 0
fi
KEY=$(kubectl -n llm exec -i deploy/llm-gateway -- python - "$PROJECT" "$MODELS" "$RPM" "$BUDGET" <<'EOF'
import json, os, sys, urllib.request
project, models, rpm, budget = sys.argv[1], sys.argv[2].split(","), int(sys.argv[3]), float(sys.argv[4])
body = {"key_alias": f"{project}", "models": models, "rpm_limit": rpm,
        "metadata": {"project": project}}
if budget > 0:
    body.update(max_budget=budget, budget_duration="30d")
req = urllib.request.Request("http://127.0.0.1:4000/key/generate", data=json.dumps(body).encode(),
                             headers={"Authorization": "Bearer " + os.environ["LITELLM_MASTER_KEY"],
                                      "Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req, timeout=30))["key"], end="")
EOF
)
[ -n "$KEY" ] || { echo "key generation failed" >&2; exit 1; }
kubectl -n "$TARGET_NS" create secret generic llm-gateway-key \
  --from-literal=api-key="$KEY" \
  --from-literal=base-url="http://llm-gateway.llm.svc.cluster.local:4000/v1" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null
unset KEY
echo "project $PROJECT: key stored in $TARGET_NS/llm-gateway-key (capabilities: $MODELS, rpm: $RPM, budget: \$$BUDGET)"
