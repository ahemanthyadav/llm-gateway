#!/bin/bash
# deploy.sh — apply the gateway: ConfigMap from config/litellm.yaml, manifests, and roll the pod
# when the config changed (annotation = sha256 of the config). Run tests first (CI does too).
set -euo pipefail
cd "$(dirname "$0")/.."
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"
python3 tests/test_config.py >/dev/null 2>&1 || { echo "config tests fail — fix before deploying" >&2; exit 1; }
kubectl apply -f manifests/gateway.yaml
kubectl -n llm create configmap llm-gateway-config --from-file=litellm.yaml=config/litellm.yaml \
  --dry-run=client -o yaml | kubectl apply -f -
SHA=$(sha256sum config/litellm.yaml | cut -c1-16)
kubectl -n llm patch deployment llm-gateway --type merge \
  -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"llm-gateway/config-sha\":\"$SHA\"}}}}}" >/dev/null
kubectl -n llm rollout status deployment/llm-gateway --timeout=600s
echo "deployed config $SHA"
