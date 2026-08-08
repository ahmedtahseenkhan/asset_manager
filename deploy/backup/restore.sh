#!/usr/bin/env bash
# Restore a backup created by backup.sh.
#   ./restore.sh /var/backups/itam/itam_db_20260808_023000.sql.gz
# DESTRUCTIVE: replaces the current database content.
set -euo pipefail

DUMP="${1:?usage: restore.sh <itam_db_*.sql.gz>}"
COMPOSE_FILE="$(cd "$(dirname "$0")/../docker" && pwd)/compose.prod.yml"

[ -f "$DUMP" ] || { echo "No such file: $DUMP" >&2; exit 1; }

echo "This will REPLACE the current database with: $DUMP"
read -r -p "Type 'restore' to continue: " CONFIRM
[ "$CONFIRM" = "restore" ] || { echo "Aborted."; exit 1; }

echo "[restore] stopping API…"
docker compose -f "$COMPOSE_FILE" stop api web

echo "[restore] loading dump…"
gunzip -c "$DUMP" | docker compose -f "$COMPOSE_FILE" exec -T postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' > /dev/null

echo "[restore] starting services…"
docker compose -f "$COMPOSE_FILE" start api web

echo "[restore] done. Verify with: curl -s http://localhost:8080/api/health"
