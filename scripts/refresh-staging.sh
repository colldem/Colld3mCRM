#!/bin/sh
# Refresh staging with a fresh copy of the production database.
#
# Run by hand on the NAS when you want staging to match production again:
#   sh /volume1/docker/crm-staging/scripts/refresh-staging.sh [--with-media]
#
# Reads production, writes only staging. The production stack is never modified:
# the only thing done there is a read-only pg_dump.
#
# Afterwards the clone still holds real personal data, so it stays protected by
# CRM_ENVIRONMENT=staging (SMTP/IMAP/Entra/webhooks forced off) plus the
# sanitize_staging pass below, which clears those settings from the data itself.
set -eu

PROD=/volume1/docker/crm
STAGING=/volume1/docker/crm-staging
WITH_MEDIA=""
[ "${1:-}" = "--with-media" ] && WITH_MEDIA=1

PROD_COMPOSE="docker compose -f $PROD/compose.yaml"
STAGING_COMPOSE="docker compose -f $STAGING/compose.staging.yaml"

# --- sanity: never let this run against production ----------------------
test -f "$STAGING/compose.staging.yaml" || { echo "FATAL: $STAGING is not a staging checkout"; exit 1; }
grep -q '^CRM_ENVIRONMENT=staging$' "$STAGING/.env" || {
  echo "FATAL: $STAGING/.env does not set CRM_ENVIRONMENT=staging — refusing"; exit 1; }
[ "$PROD" != "$STAGING" ] || { echo "FATAL: paths collide"; exit 1; }

DUMP="$STAGING/runtime/prod-$(date +%Y%m%d-%H%M%S).dump"
mkdir -p "$STAGING/runtime"

# --- 1. read production (read-only) -------------------------------------
echo ">>> dumping production"
$PROD_COMPOSE exec -T crm-db pg_dump -U crm -d crm -Fc < /dev/null > "$DUMP"
test -s "$DUMP" || { echo "FATAL: dump is empty"; rm -f "$DUMP"; exit 1; }
echo "    $(basename "$DUMP") ($(wc -c < "$DUMP") bytes)"

# --- 2. restore into staging -------------------------------------------
echo ">>> restoring into staging"
cd "$STAGING"
$STAGING_COMPOSE stop crm-web >/dev/null 2>&1 || true   # drop app connections first
$STAGING_COMPOSE up -d crm-db
for _ in $(seq 1 30); do
  $STAGING_COMPOSE exec -T crm-db pg_isready -U crm -d crm < /dev/null >/dev/null 2>&1 && break
  sleep 2
done
$STAGING_COMPOSE exec -T crm-db pg_restore --clean --if-exists --no-owner --no-privileges \
  -U crm -d crm < "$DUMP" || echo "    (pg_restore reported non-fatal notices)"

# --- 3. bring the app back and make the clone harmless ------------------
$STAGING_COMPOSE up -d
ok=""
for _ in $(seq 1 30); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' crm-staging-crm-web-1 2>/dev/null)" = "healthy" ] && { ok=1; break; }
  sleep 3
done
[ -n "$ok" ] || { echo "FATAL: staging crm-web did not become healthy"; exit 1; }

$STAGING_COMPOSE exec -T crm-web python manage.py migrate --noinput < /dev/null
$STAGING_COMPOSE exec -T crm-web python manage.py sanitize_staging < /dev/null

# --- 4. optional: real attachments --------------------------------------
if [ -n "$WITH_MEDIA" ]; then
  echo ">>> copying media"
  rsync -a --delete "$PROD/runtime/media/" "$STAGING/runtime/media/"
fi

ls -1t "$STAGING"/runtime/prod-*.dump 2>/dev/null | tail -n +4 | xargs -r rm -f   # keep 3
echo ">>> staging refreshed from production"
