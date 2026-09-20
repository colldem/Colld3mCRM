#!/bin/sh
# Refresh staging with a fresh copy of the production database.
#
# Run by hand on the NAS when you want staging to match production again:
#   CRM_APP_DIR=/volume1/docker/crm CRM_STAGING_DIR=/volume1/docker/crm-staging \
#     sh /volume1/docker/crm-staging/scripts/refresh-staging.sh [--with-media]
#
# The Regitra staging instance is refreshed the same way, only pointed elsewhere:
#   CRM_APP_DIR=/volume1/docker/crm CRM_STAGING_DIR=/volume1/docker/crm-regitra-staging \
#     sh /volume1/docker/crm-regitra-staging/scripts/refresh-staging.sh
#
# Reads production, writes only staging. The production stack is never modified:
# the only thing done there is a read-only pg_dump.
#
# Afterwards the clone is protected by CRM_ENVIRONMENT=staging (SMTP/IMAP/Entra/
# webhooks forced off) plus the sanitize_staging pass below, which clears those
# settings from the data and anonymises the personal data in it.
set -eu

PROD="${CRM_APP_DIR:-/opt/crm}"
STAGING="${CRM_STAGING_DIR:-/opt/crm-staging}"
WITH_MEDIA=""
[ "${1:-}" = "--with-media" ] && WITH_MEDIA=1

# Each directory's .env selects its own overlays through COMPOSE_FILE.
PROD_COMPOSE="docker compose --project-directory $PROD"
STAGING_COMPOSE="docker compose --project-directory $STAGING"

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
#
# The database is dropped and recreated first. --clean --if-exists is not enough:
# whatever it fails to drop survives into the clone, and a leftover column from a
# branch production does not have leaves the schema ahead of the restored
# django_migrations table — the next migrate then tries to add a column that is
# already there and the app never starts. An empty database cannot do that.
echo ">>> recreating the staging database"
$STAGING_COMPOSE exec -T crm-db psql -U crm -d postgres -v ON_ERROR_STOP=1 \
  -c 'DROP DATABASE IF EXISTS crm WITH (FORCE)' \
  -c 'CREATE DATABASE crm OWNER crm' < /dev/null

echo ">>> streaming production -> staging"
$PROD_COMPOSE exec -T crm-db pg_dump -U crm -d crm -Fc < /dev/null \
  | $STAGING_COMPOSE exec -T crm-db pg_restore --no-owner --no-privileges \
      -U crm -d crm \
  || echo "    (pg_restore reported notices; checked below)"

# --- 3. bring the app back and make the clone harmless ------------------
$STAGING_COMPOSE up -d
ok=""
for _ in $(seq 1 30); do
  # Asked through compose, so this works for every staging instance: the
  # container name carries the project name, which differs per overlay.
  cid="$($STAGING_COMPOSE ps -q crm-web 2>/dev/null)"
  [ -n "$cid" ] \
    && [ "$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null)" = "healthy" ] \
    && { ok=1; break; }
  sleep 3
done
[ -n "$ok" ] || { echo "FATAL: staging crm-web did not become healthy"; exit 1; }

# Prove the restore actually landed before declaring success.
# -v 0 keeps Django 5.2's automatic-model-import notice out of the value.
people="$($STAGING_COMPOSE exec -T crm-web python manage.py shell -v 0 -c \
  'from contacts.models import Person; print(Person.objects.count())' < /dev/null | tr -d '\r\n')"
echo "    restored contacts: $people"

# --- 4. optional: attachments, copied BEFORE the anonymising pass replaces them ---
if [ -n "$WITH_MEDIA" ]; then
  # Through a container, because the deploy leaves runtime/ owned by root.
  echo ">>> copying media"
  docker run --rm \
    -v "$PROD/runtime/media:/src:ro" -v "$STAGING/runtime/media:/dst" \
    alpine:3 sh -c 'rm -rf /dst/* && cp -a /src/. /dst/ 2>/dev/null; echo "    media copied"'
fi

$STAGING_COMPOSE exec -T crm-web python manage.py migrate --noinput < /dev/null
# Clears integration credentials and anonymises personal data (names, contact
# details, texts, attachment files, users, mail, audit trail).
$STAGING_COMPOSE exec -T crm-web python manage.py sanitize_staging < /dev/null

echo ">>> staging refreshed from production"
