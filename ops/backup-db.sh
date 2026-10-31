#!/bin/bash
# backup-db.sh [--namespace <ns>] [--output-dir <dir>] [--retention-days <days>]
#   Backs up the llm-gateway TimescaleDB database (owner role `litellm`) on the
#   marketdata TimescaleDB server.
#   The backup is NOT part of marketdata's daily pg-backup (that dumps the `postgres`
#   DB), so this script ensures the `litellm` DB is backed up separately.
#   Backup files are named: litellm-<date>-<time>.sql.gz
#   Old backups beyond --retention-days are deleted.
#   e.g.  ops/backup-db.sh --output-dir /mnt/tx2-ssd/backups --retention-days 30
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/pi-cluster.yaml}"

NAMESPACE="market-data"
OUTPUT_DIR="/mnt/tx2-ssd/backups"
RETENTION_DAYS=30
DBHOST="timescaledb.${NAMESPACE}.svc.cluster.local"
DBUSER="litellm"
DBNAME="litellm"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NAMESPACE="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --retention-days) RETENTION_DAYS="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

DBHOST="timescaledb.${NAMESPACE}.svc.cluster.local"

mkdir -p "$OUTPUT_DIR"

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${OUTPUT_DIR}/litellm-${TIMESTAMP}.sql.gz"

echo "Backing up litellm DB from ${DBHOST}:5432 ..."

# Get the postgres password from the marketdata secret
PGPW=$(kubectl -n "$NAMESPACE" get secret timescaledb-auth -o jsonpath='{.data.password}' | base64 -d)

# Dump the litellm database (pipe through gzip, never write plaintext SQL to disk)
kubectl -n "$NAMESPACE" exec -i timescaledb-0 -- env PGPASSWORD="$PGPW" \
  pg_dump -U "$DBUSER" -d "$DBNAME" -h "$DBHOST" -p 5432 \
  | gzip > "$BACKUP_FILE"

unset PGPW

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "Backup complete: $BACKUP_FILE ($BACKUP_SIZE)"

# Delete old backups beyond retention
if [ "$RETENTION_DAYS" -gt 0 ]; then
  DELETED=$(find "$OUTPUT_DIR" -name "litellm-*.sql.gz" -mtime +$RETENTION_DAYS -delete -print 2>/dev/null || true)
  if [ -n "$DELETED" ]; then
    echo "Deleted old backups:"
    echo "$DELETED"
  fi
fi

echo "Backup retention: $RETENTION_DAYS days"
