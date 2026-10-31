#!/bin/bash
# delete-project.sh <project> <k8s-namespace> [--rotate]
#   Revoke/delete a project key created by ops/new-project.sh.
#   Removes Secret <namespace>/llm-gateway-key (or SECRET_NAME override).
#   Does NOT print the key. After deletion, clients using that key get 401/403.
#   e.g.  ops/delete-project.sh marketdata market-data
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"
PROJECT=$1
TARGET_NS=$2
SECRET=${SECRET_NAME:-llm-gateway-key}

if ! kubectl -n "$TARGET_NS" get secret "$SECRET" >/dev/null 2>&1; then
  echo "Secret $TARGET_NS/$SECRET does not exist — nothing to delete"; exit 0
fi

kubectl -n "$TARGET_NS" delete secret "$SECRET" >/dev/null
echo "project $PROJECT: key deleted from $TARGET_NS/$SECRET"
