#!/usr/bin/env bash
# On-prem installer for IT Asset Manager (Docker Compose deployment).
# Run from anywhere inside the product directory on the target host:
#   ./deploy/install/install.sh
# Air-gapped hosts: docker-load the three images first (see ADMIN_GUIDE.md),
# then run this script — compose will use the local images.
set -euo pipefail

DOCKER_DIR="$(cd "$(dirname "$0")/../docker" && pwd)"
ENV_FILE="$DOCKER_DIR/.env"
COMPOSE="docker compose -f $DOCKER_DIR/compose.prod.yml"

echo "── IT Asset Manager installer ──────────────────────────"

command -v docker >/dev/null || { echo "ERROR: docker is required." >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose v2 is required." >&2; exit 1; }

if [ -f "$ENV_FILE" ]; then
  echo "[install] using existing $ENV_FILE"
else
  echo "[install] generating $ENV_FILE with strong secrets…"
  PG_PW="$(openssl rand -hex 24)"
  JWT="$(openssl rand -hex 32)"
  # Fernet key = urlsafe-base64 of 32 random bytes
  ENC="$(openssl rand 32 | base64 | tr '+/' '-_' )"
  cat > "$ENV_FILE" <<EOF
POSTGRES_DB=asset_manager
POSTGRES_USER=itam
POSTGRES_PASSWORD=$PG_PW
JWT_SECRET=$JWT
ENCRYPTION_KEY=$ENC
APP_NAME=IT Asset Manager
HTTP_PORT=8080
EOF
  chmod 600 "$ENV_FILE"
fi

echo "[install] building and starting services (first build takes a few minutes)…"
$COMPOSE up -d --build

echo "[install] waiting for API health…"
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:$(grep ^HTTP_PORT "$ENV_FILE" | cut -d= -f2)/api/health" >/dev/null 2>&1; then
    HEALTHY=1; break
  fi
  sleep 2
done
[ "${HEALTHY:-0}" = "1" ] || { echo "ERROR: API did not become healthy; check: $COMPOSE logs api" >&2; exit 1; }

echo "[install] creating initial admin user…"
$COMPOSE exec api python -m backend.scripts.create_admin || true

PORT="$(grep ^HTTP_PORT "$ENV_FILE" | cut -d= -f2)"
cat <<EOF

── Installation complete ───────────────────────────────
  Web UI:      http://<this-host>:$PORT
  Next steps:
    1. Sign in with the admin account you just created.
    2. Administration → License → upload your .lic file
       (until then the system runs read-only).
    3. Notifications → configure your SMTP relay.
    4. Schedule backups:  deploy/backup/backup.sh (cron)
    5. Put TLS in front — see docs/ADMIN_GUIDE.md.
EOF
