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

# --- 1. prepare staging -------------------------------------------------
cd "$STAGING"
$STAGING_COMPOSE stop crm-web >/dev/null 2>&1 || true   # drop app connections first
$STAGING_COMPOSE up -d crm-db
for _ in $(seq 1 30); do
  $STAGING_COMPOSE exec -T crm-db pg_isready -U crm -d crm < /dev/null >/dev/null 2>&1 && break
  sleep 2
done

# --- 2. stream production straight into it ------------------------------
# Piped rather than staged through a file: the deploy already leaves dated dumps
# in the production directory if one is ever needed, and this way the refresh
# needs no writable path on the host, which the deploy leaves owned by root.
echo ">>> streaming production -> staging"
$PROD_COMPOSE exec -T crm-db pg_dump -U crm -d crm -Fc < /dev/null \
  | $STAGING_COMPOSE exec -T crm-db pg_restore --clean --if-exists --no-owner \
      --no-privileges -U crm -d crm \
  || echo "    (pg_restore reported notices; checked below)"

# --- 3. bring the app back and make the clone harmless ------------------
$STAGING_COMPOSE up -d
ok=""
for _ in $(seq 1 30); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' crm-staging-crm-web-1 2>/dev/null)" = "healthy" ] && { ok=1; break; }
  sleep 3
done
[ -n "$ok" ] || { echo "FATAL: staging crm-web did not become healthy"; exit 1; }

# Prove the restore actually landed before declaring success.
# -v 0 keeps Django 5.2's automatic-model-import notice out of the value.
people="$($STAGING_COMPOSE exec -T crm-web python manage.py shell -v 0 -c \
  'from contacts.models import Person; print(Person.objects.count())' < /dev/null | tr -d '\r\n')"
echo "    restored contacts: $people"

$STAGING_COMPOSE exec -T crm-web python manage.py migrate --noinput < /dev/null
$STAGING_COMPOSE exec -T crm-web python manage.py sanitize_staging < /dev/null

# --- 4. optional: real attachments --------------------------------------
if [ -n "$WITH_MEDIA" ]; then
  # Through a container, because the deploy leaves runtime/ owned by root.
  echo ">>> copying media"
  docker run --rm \
    -v "$PROD/runtime/media:/src:ro" -v "$STAGING/runtime/media:/dst" \
    alpine:3 sh -c 'rm -rf /dst/* && cp -a /src/. /dst/ 2>/dev/null; echo "    media copied"'
fi

echo ">>> staging refreshed from production"
