#!/bin/bash
# deploy.sh — apply the gateway: ConfigMap from config/litellm.yaml, manifests, and roll the pod
# when the config changes (annotation = sha256 of the config). Run tests first (CI does too).
set -euo pipefail
cd "$(dirname "$0")/.."
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"
# 1. Run config validation (mirrors CI)
echo "=== Validating config ==="
python3 tests/test_config.py >/dev/null 2>&1 || { echo "config tests fail — fix before deploying" >&2; exit 1; }
echo "  ✓ test_config.py PASSED"
# 2. Validate capability routing with the architectural router
echo "=== Validating capability routing ==="
python3 -c "
import sys
sys.path.insert(0, '/home/ahy/Documents/piCluster/projects/llm-gateway')
from arch.capability_router import CapabilityRouter
from arch.fallback_diversification import validate_cross_family_diversification
router = CapabilityRouter()
router_all = router.all_capabilities()
print(f'  Capabilities: {len(router_all)}')
v = validate_cross_family_diversification(router)
bad = [c for c, f in v.items() if len(f) <= 1]
if bad:
    print(f'  ✗ Diversification VIOLATION: {bad}')
    exit(1)
else:
    print('  ✓ Cross-family diversification OK')
"
echo "  ✓ Capability routing validated"
# 3. Apply ConfigMap from config/litellm.yaml
echo "=== Applying ConfigMap ==="
kubectl apply -f manifests/gateway.yaml
kubectl -n llm create configmap llm-gateway-config --from-file=litellm.yaml=config/litellm.yaml \
  --dry-run=client -o yaml | kubectl apply -f -
# 4. Compute sha256 of config for roll annotation
SHA=$(sha256sum config/litellm.yaml | cut -c1-16)
kubectl -n llm patch deployment llm-gateway --type merge \
  -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"llm-gateway/config-sha\":\"$SHA\"}}}}}" >/dev/null
# 5. Roll the pod
echo "=== Rolling gateway pod ==="
kubectl -n llm rollout status deployment/llm-gateway --timeout=600s
echo "deployed config $SHA"
# 6. Run smoke test (without live key for routing proof)
echo "=== Running smoke test ==="
ops/smoke.sh
echo ""
echo "=== Deployment Complete ==="
echo "  - ConfigMap updated with litellm.yaml (sha256: $SHA)"
echo "  - Gateway pod rolled and ready"
echo "  - Config validated: test_config.py + diversification"
echo "  - Run: ops/smoke.sh --live for live provider calls"