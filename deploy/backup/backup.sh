#!/usr/bin/env bash
# Nightly-safe Postgres backup for the docker-compose deployment.
#   ./backup.sh [backup_dir] [keep_count]
# Cron example (02:30 daily, keep 14):
#   30 2 * * * /opt/itam/deploy/backup/backup.sh /var/backups/itam 14
set -euo pipefail

BACKUP_DIR="${1:-./backups}"
KEEP="${2:-14}"
COMPOSE_FILE="$(cd "$(dirname "$0")/../docker" && pwd)/compose.prod.yml"
STAMP="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_DIR"

echo "[backup] dumping database…"
docker compose -f "$COMPOSE_FILE" exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' \
  | gzip > "$BACKUP_DIR/itam_db_${STAMP}.sql.gz"

echo "[backup] copying license file…"
docker compose -f "$COMPOSE_FILE" cp api:/data/license.lic \
  "$BACKUP_DIR/itam_license_${STAMP}.lic" 2>/dev/null \
  || echo "[backup] no license file found (skipped)"

echo "[backup] rotating (keeping last $KEEP)…"
ls -1t "$BACKUP_DIR"/itam_db_*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
ls -1t "$BACKUP_DIR"/itam_license_*.lic 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "[backup] done: $BACKUP_DIR/itam_db_${STAMP}.sql.gz"
