#!/bin/bash
# bootstrap.sh — one-time (idempotent): the gateway's own database + Secret `llm-gateway`.
#   * database `litellm` + role `litellm` on the existing TimescaleDB server (market-data namespace),
#     owning only that database (the pipeline's `postgres` DB is untouched);
#   * Secret llm/llm-gateway: master-key, salt-key, database-url. Provider keys are added later
#     with ops/set-provider-key.sh. Values are generated here and never printed.
# Re-running keeps existing values (the salt key must never change: it encrypts stored credentials).
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"
NS=llm
DBHOST=timescaledb.market-data.svc.cluster.local
gen() { python3 -c "import secrets,string;print('$1'+''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range($2)))"; }

kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create ns "$NS" >/dev/null
if kubectl -n "$NS" get secret llm-gateway >/dev/null 2>&1; then
  echo "Secret llm-gateway exists — keeping it"
  DBPW=$(kubectl -n "$NS" get secret llm-gateway -o jsonpath='{.data.database-url}' | base64 -d | sed -E 's#^postgresql://litellm:([^@]+)@.*#\1#')
else
  DBPW=$(gen "" 32)
  kubectl -n "$NS" create secret generic llm-gateway \
    --from-literal=master-key="$(gen sk- 48)" \
    --from-literal=salt-key="$(gen sk- 48)" \
    --from-literal=database-url="postgresql://litellm:${DBPW}@${DBHOST}:5432/litellm" >/dev/null
  echo "Secret llm-gateway created"
fi

PGPW=$(kubectl -n market-data get secret timescaledb-auth -o jsonpath='{.data.password}' | base64 -d)
# Role + database, idempotent; password via stdin only (never on a command line).
{
  printf "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='litellm') THEN CREATE ROLE litellm LOGIN; END IF; END \$\$;\n"
  printf "ALTER ROLE litellm LOGIN PASSWORD '%s';\n" "$DBPW"
  printf "SELECT 'CREATE DATABASE litellm OWNER litellm' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='litellm')\\\\gexec\n"
  printf "REVOKE CONNECT ON DATABASE litellm FROM PUBLIC;\n"
  printf "GRANT CONNECT ON DATABASE litellm TO litellm;\n"
} | kubectl -n market-data exec -i timescaledb-0 -- env PGPASSWORD="$PGPW" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1
unset DBPW PGPW
echo "database litellm ready (owner litellm)"
