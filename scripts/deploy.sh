#!/bin/sh
# Deploy the checked-out tree to the NAS. Runs on the self-hosted runner, whose
# container mounts /var/run/docker.sock and /volume1/docker/crm. Idempotent.
set -eu

APP=/volume1/docker/crm
VERSION="$(cat VERSION)"
TS="$(date +%Y%m%d-%H%M%S)"
DUMP="$APP/pre-${VERSION}-${TS}.dump"

echo ">>> deploy ${VERSION} (from $(git rev-parse --short HEAD 2>/dev/null || echo '?'))"

# --- sanity -------------------------------------------------------------
test -f manage.py && test -f compose.yaml || { echo "FATAL: not a CRM checkout"; exit 1; }
test -f "$APP/.env" || { echo "FATAL: $APP/.env is missing"; exit 1; }
grep -q '^CRM_SECRETS_KEY=' "$APP/.env" || { echo "FATAL: CRM_SECRETS_KEY not set in $APP/.env"; exit 1; }

APP_COMPOSE="docker compose -f $APP/compose.yaml"

# --- 1. back up the live database -------------------------------------
$APP_COMPOSE exec -T crm-db pg_dump -U crm -d crm -Fc < /dev/null > "$DUMP"
test -s "$DUMP" || { echo "FATAL: backup is empty"; rm -f "$DUMP"; exit 1; }
echo "    backup: $(basename "$DUMP") ($(wc -c < "$DUMP") bytes)"
ls -1t "$APP"/pre-*.dump 2>/dev/null | tail -n +21 | xargs -r rm -f   # keep 20

# --- 2. publish the source (image is rebuilt from it) ----------------
# .env, runtime/ and the .dump backups are NAS-only and must survive.
rsync -a --delete \
  --exclude='.env' --exclude='.env.*' --exclude='runtime/' \
  --exclude='db.sqlite3' --exclude='*.dump' --exclude='.git/' \
  --exclude='staticfiles/' --exclude='__pycache__/' \
  ./ "$APP/"

# --- 3. build + roll -------------------------------------------------
cd "$APP"
docker compose -f compose.yaml build --pull
docker compose -f compose.yaml up -d --remove-orphans

# --- 4. verify -----------------------------------------------------
ok=""
for _ in $(seq 1 30); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' crm-crm-web-1 2>/dev/null)" = "healthy" ] && { ok=1; break; }
  sleep 3
done
[ -n "$ok" ] || { echo "FATAL: crm-web did not become healthy"; docker compose -f compose.yaml logs --tail 50 crm-web; exit 1; }
docker compose -f compose.yaml exec -T crm-web python manage.py migrate --check < /dev/null
docker compose -f compose.yaml ps
echo ">>> deployed ${VERSION} OK"
