#!/bin/sh
# Deploy the checked-out tree to a Docker host. Runs on the self-hosted runner,
# which mounts /var/run/docker.sock and the app directory. Idempotent.
#
# The target directory and the compose overlays are configuration, not hardcoded:
#   CRM_APP_DIR   where the deployment lives (default /opt/crm)
#   COMPOSE_FILE  set in that directory's .env, e.g.
#                 compose.yaml:compose.tailscale.yaml
set -eu

APP="${CRM_APP_DIR:-/opt/crm}"
VERSION="$(cat VERSION)"
TS="$(date +%Y%m%d-%H%M%S)"
DUMP="$APP/pre-${VERSION}-${TS}.dump"

echo ">>> deploy ${VERSION} to ${APP} (from $(git rev-parse --short HEAD 2>/dev/null || echo '?'))"

# --- sanity -------------------------------------------------------------
test -f manage.py && test -f compose.yaml || { echo "FATAL: not a CRM checkout"; exit 1; }
test -d "$APP" || { echo "FATAL: $APP does not exist"; exit 1; }
test -f "$APP/.env" || { echo "FATAL: $APP/.env is missing"; exit 1; }
grep -q '^CRM_SECRETS_KEY=' "$APP/.env" || { echo "FATAL: CRM_SECRETS_KEY not set in $APP/.env"; exit 1; }
# Without this the base file alone would apply, quietly dropping whichever
# overlay puts this instance on the network.
grep -q '^COMPOSE_FILE=' "$APP/.env" || {
  echo "FATAL: $APP/.env must set COMPOSE_FILE — see docs/DEPLOYMENT.md"; exit 1; }

# --- 1. back up the live database ---------------------------------------
# Explicit -f compose.yaml, not the .env COMPOSE_FILE: an overlay named there
# (compose.tailscale.yaml) may not be on the host yet on the deploy that first
# introduces it, and the backup only needs the already-running db container,
# which compose.yaml alone defines.
docker compose -f "$APP/compose.yaml" --project-directory "$APP" \
  exec -T crm-db pg_dump -U crm -d crm -Fc < /dev/null > "$DUMP"
test -s "$DUMP" || { echo "FATAL: backup is empty"; rm -f "$DUMP"; exit 1; }
echo "    backup: $(basename "$DUMP") ($(wc -c < "$DUMP") bytes)"
ls -1t "$APP"/pre-*.dump 2>/dev/null | tail -n +21 | xargs -r rm -f   # keep 20

# --- 2. publish the source (the image is rebuilt from it) ----------------
# .env, runtime/ and the .dump backups are host-only and must survive.
rsync -a --delete \
  --exclude='.env' --exclude='.env.*' --exclude='runtime/' \
  --exclude='db.sqlite3' --exclude='*.dump' --exclude='.git/' \
  --exclude='staticfiles/' --exclude='__pycache__/' \
  ./ "$APP/"

# --- 3. build + roll -----------------------------------------------------
cd "$APP"
docker compose build --pull
docker compose up -d --remove-orphans

# --- 4. verify -----------------------------------------------------------
web="$(docker compose ps -q crm-web)"
ok=""
for _ in $(seq 1 30); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$web" 2>/dev/null)" = "healthy" ] && { ok=1; break; }
  sleep 3
done
[ -n "$ok" ] || { echo "FATAL: crm-web did not become healthy"; docker compose logs --tail 50 crm-web; exit 1; }
docker compose exec -T crm-web python manage.py migrate --check < /dev/null
docker compose ps
echo ">>> deployed ${VERSION} OK"
