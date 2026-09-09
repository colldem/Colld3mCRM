#!/bin/sh
# Deploy the checked-out tree to the staging instance. Runs on the self-hosted
# runner. Staging holds a clone of production data, so this refuses to run unless
# the target really is an isolated tier.
#
# No database backup here, unlike scripts/deploy.sh: staging data is disposable
# and reloaded on demand by scripts/refresh-staging.sh.
#
#   CRM_STAGING_DIR  where staging lives (default /opt/crm-staging)
set -eu

APP="${CRM_STAGING_DIR:-/opt/crm-staging}"
VERSION="$(cat VERSION)"

echo ">>> staging deploy ${VERSION} to ${APP} (from $(git rev-parse --short HEAD 2>/dev/null || echo '?'))"

# --- sanity -------------------------------------------------------------
test -f manage.py && test -f compose.staging.yaml || { echo "FATAL: not a CRM checkout"; exit 1; }
test -d "$APP" || { echo "FATAL: $APP does not exist"; exit 1; }
test -f "$APP/.env" || { echo "FATAL: $APP/.env is missing"; exit 1; }
grep -q '^CRM_ENVIRONMENT=staging$' "$APP/.env" || {
  echo "FATAL: $APP/.env must set CRM_ENVIRONMENT=staging — refusing to deploy"; exit 1; }
grep -q '^COMPOSE_FILE=.*compose\.staging\.yaml' "$APP/.env" || {
  echo "FATAL: $APP/.env COMPOSE_FILE must include compose.staging.yaml"; exit 1; }
# The Tailscale overlay defaults to serve.json, which enables Funnel and would
# publish this clone of production data to the public internet.
if grep -q '^COMPOSE_FILE=.*compose\.tailscale\.yaml' "$APP/.env"; then
  grep -q '^TS_SERVE_CONFIG=/config/serve-staging\.json$' "$APP/.env" || {
    echo "FATAL: staging on Tailscale must set TS_SERVE_CONFIG=/config/serve-staging.json"
    echo "       (the default serve.json enables Funnel — public internet)"; exit 1; }
fi

# --- 1. publish the source ----------------------------------------------
rsync -a --delete \
  --exclude='.env' --exclude='.env.*' --exclude='runtime/' \
  --exclude='db.sqlite3' --exclude='*.dump' --exclude='.git/' \
  --exclude='staticfiles/' --exclude='__pycache__/' \
  ./ "$APP/"

# --- 2. build + roll -----------------------------------------------------
cd "$APP"
docker compose build --pull
docker compose up -d --remove-orphans

# --- 3. verify -----------------------------------------------------------
web="$(docker compose ps -q crm-web)"
ok=""
for _ in $(seq 1 30); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' "$web" 2>/dev/null)" = "healthy" ] && { ok=1; break; }
  sleep 3
done
[ -n "$ok" ] || { echo "FATAL: staging crm-web did not become healthy"; docker compose logs --tail 50 crm-web; exit 1; }

# The isolation switch is what lets this tier hold real data; prove it took.
tier="$(docker compose exec -T crm-web printenv CRM_ENVIRONMENT < /dev/null | tr -d '\r\n')"
[ "$tier" = "staging" ] || { echo "FATAL: CRM_ENVIRONMENT is '$tier', expected 'staging'"; exit 1; }
# And prove nothing is running on a timer against the cloned data.
running="$(docker compose ps --services --filter status=running | tr -d '\r')"
for svc in crm-worker crm-backup; do
  echo "$running" | grep -qx "$svc" && { echo "FATAL: $svc is running on staging"; exit 1; }
done

docker compose exec -T crm-web python manage.py migrate --check < /dev/null
docker compose ps
echo ">>> staging ${VERSION} OK (tier=${tier})"
