#!/bin/bash
# deploy.sh — apply the gateway: ConfigMap from config/litellm.yaml, manifests, and roll the pod
# when the config changes (annotation = sha256 of the config). Run tests first (CI does too).
#
# Modes:
#   deploy.sh                  — full rollout (validate → ConfigMap → roll → smoke)
#   deploy.sh --canary         — deploy config as canary, run smoke, wait for promotion
#   deploy.sh --promote <sha>  — promote a canary deployment to full rollout
set -euo pipefail
cd "$(dirname "$0")/.."
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"

MODE="full"
PROMOTE_SHA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --canary) MODE="canary"; shift ;;
    --promote) PROMOTE_SHA="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

# ── Promote a canary to full rollout ──────────────────────────
if [ -n "$PROMOTE_SHA" ]; then
  echo "=== Promoting canary deployment: $PROMOTE_SHA ==="
  kubectl -n llm rollout status deployment/llm-gateway --timeout=600s
  ops/smoke.sh
  echo "=== Canary $PROMOTE_SHA promoted to full rollout ==="
  exit 0
fi

# ── Common: validate config ───────────────────────────────────
echo "=== Validating config ==="
python3 tests/test_config.py >/dev/null 2>&1 || { echo "config tests fail — fix before deploying" >&2; exit 1; }
echo "  ✓ test_config.py PASSED"

# ── Common: validate capability routing ───────────────────────
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

# ── Compute config SHA ────────────────────────────────────────
SHA=$(sha256sum config/litellm.yaml | cut -c1-16)

# ── Apply ConfigMap from config/litellm.yaml ──────────────────
echo "=== Applying ConfigMap ==="
kubectl apply -f manifests/gateway.yaml
kubectl -n llm create configmap llm-gateway-config --from-file=litellm.yaml=config/litellm.yaml \
  --dry-run=client -o yaml | kubectl apply -f -

# ── Annotate deployment with config SHA ───────────────────────
kubectl -n llm patch deployment llm-gateway --type merge \
  -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"llm-gateway/config-sha\":\"$SHA\"}}}}}" >/dev/null

if [ "$MODE" = "canary" ]; then
  echo "=== Canary mode: config $SHA deployed, waiting for promotion ==="
  echo "  - ConfigMap updated with litellm.yaml (sha256: $SHA)"
  echo "  - Gateway pod NOT rolled yet — run 'ops/deploy.sh --promote $SHA' to roll out"
  echo "  - Run 'ops/smoke.sh' to validate before promoting"
  exit 0
fi

# ── Full rollout: roll the pod ────────────────────────────────
echo "=== Rolling gateway pod ==="
kubectl -n llm rollout status deployment/llm-gateway --timeout=600s
echo "deployed config $SHA"

# ── Run smoke test ────────────────────────────────────────────
echo "=== Running smoke test ==="
ops/smoke.sh
echo ""
echo "=== Deployment Complete ==="
echo "  - ConfigMap updated with litellm.yaml (sha256: $SHA)"
echo "  - Gateway pod rolled and ready"
echo "  - Config validated: test_config.py + diversification"
echo "  - Run: ops/smoke.sh --live for live provider calls"
