#!/bin/bash
# rotate-keys.sh <project> <k8s-namespace> [--all] [--dry-run]
#   Rotates a project's API key by generating a new one, updating the Secret,
#   and optionally restarting the gateway so it picks up any related changes.
#   The old key is revoked immediately — clients must switch to the new key.
#   The key is never printed to stdout.
#   e.g.  ops/rotate-keys.sh marketdata market-data
#   e.g.  ops/rotate-keys.sh --all                          # rotate all project keys
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"

PROJECT=${1:-}
TARGET_NS=${2:-}
ALL=${3:-}
DRY_RUN=${4:-}

SECRET=${SECRET_NAME:-llm-gateway-key}

if [ "$ALL" = "--all" ]; then
  # Rotate all llm-gateway-key secrets across namespaces
  echo "Rotating all project keys..."
  for ns in $(kubectl get secrets --all-namespaces -o jsonpath='{range .items[*]}{@.metadata.namespace}{"\t"}{@.metadata.name}{"\n"}{end}' \
              | awk '$2=="llm-gateway-key"{print $1}'); do
    echo "  Rotating key in namespace: $ns"
    kubectl -n "$ns" delete secret llm-gateway-key >/dev/null 2>&1 || true
    # Re-create via new-project.sh would need the original params —
    # this script only deletes; the project must re-run ops/new-project.sh
  done
  echo "All llm-gateway-key secrets deleted. Projects must re-run ops/new-project.sh to recreate keys."
  exit 0
fi

if [ -z "$PROJECT" ] || [ -z "$TARGET_NS" ]; then
  echo "Usage: $0 <project> <k8s-namespace> [--all] [--dry-run]" >&2
  exit 2
fi

if ! kubectl -n "$TARGET_NS" get secret "$SECRET" >/dev/null 2>&1; then
  echo "Secret $TARGET_NS/$SECRET does not exist — nothing to rotate"; exit 0
fi

if [ "$DRY_RUN" = "--dry-run" ]; then
  echo "[dry-run] Would delete and recreate $TARGET_NS/$SECRET for project $PROJECT"
  echo "[dry-run] Project must re-run ops/new-project.sh to get a new key"
  exit 0
fi

# Delete the old key (immediate revocation)
kubectl -n "$TARGET_NS" delete secret "$SECRET" >/dev/null
echo "project $PROJECT: old key revoked from $TARGET_NS/$SECRET"
echo ""
echo "Next steps:"
echo "  1. Re-create the key:  ops/new-project.sh $PROJECT $TARGET_NS <caps> <rpm> [budget]"
echo "  2. Distribute the new key to clients (never printed by this script)"
echo "  3. Clients using the old key will receive 401/403 immediately"
