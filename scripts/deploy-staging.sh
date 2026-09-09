#!/bin/sh
# Deploy the checked-out tree to the staging stack on the NAS. Runs on the
# self-hosted runner, which mounts /var/run/docker.sock and /volume1/docker.
#
# No database backup here, unlike scripts/deploy.sh: staging data is a disposable
# copy of production, refreshed on demand by scripts/refresh-staging.sh.
set -eu

APP=/volume1/docker/crm-staging
VERSION="$(cat VERSION)"

echo ">>> staging deploy ${VERSION} (from $(git rev-parse --short HEAD 2>/dev/null || echo '?'))"

# --- sanity -------------------------------------------------------------
test -f manage.py && test -f compose.staging.yaml || { echo "FATAL: not a CRM checkout"; exit 1; }
test -f "$APP/.env" || { echo "FATAL: $APP/.env is missing"; exit 1; }
grep -q '^CRM_ENVIRONMENT=staging$' "$APP/.env" || {
  echo "FATAL: $APP/.env must set CRM_ENVIRONMENT=staging — refusing to deploy"; exit 1; }

# --- 1. publish the source ---------------------------------------------
# .env and runtime/ are NAS-only and must survive.
rsync -a --delete \
  --exclude='.env' --exclude='.env.*' --exclude='runtime/' \
  --exclude='db.sqlite3' --exclude='*.dump' --exclude='.git/' \
  --exclude='staticfiles/' --exclude='__pycache__/' \
  ./ "$APP/"

# --- 2. build + roll ----------------------------------------------------
cd "$APP"
docker compose -f compose.staging.yaml build --pull
docker compose -f compose.staging.yaml up -d --remove-orphans

# --- 3. verify ----------------------------------------------------------
ok=""
for _ in $(seq 1 30); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' crm-staging-crm-web-1 2>/dev/null)" = "healthy" ] && { ok=1; break; }
  sleep 3
done
[ -n "$ok" ] || {
  echo "FATAL: staging crm-web did not become healthy"
  docker compose -f compose.staging.yaml logs --tail 50 crm-web
  exit 1; }

# The isolation switch is what lets this tier hold real data; prove it took.
tier="$(docker compose -f compose.staging.yaml exec -T crm-web printenv CRM_ENVIRONMENT < /dev/null | tr -d '\r\n')"
[ "$tier" = "staging" ] || { echo "FATAL: CRM_ENVIRONMENT is '$tier', expected 'staging'"; exit 1; }

docker compose -f compose.staging.yaml exec -T crm-web python manage.py migrate --check < /dev/null
docker compose -f compose.staging.yaml ps
echo ">>> staging ${VERSION} OK (tier=${tier})"
