#!/bin/bash
# Restore the CRM from a backup set written by the crm-backup service.
#
#   bash scripts/restore.sh --db runtime/backups/db-20260913-020000.dump.age \
#       [--media runtime/backups/media-20260913-020000.tar.gz.age] \
#       [--identity /secure/crm-backup-key.txt] [--yes]
#
# Run from the Compose project directory (or set CRM_APP_DIR). It
#   1. verifies the files against the set's SHA256SUMS file,
#   2. stops crm-web and crm-worker,
#   3. decrypts inside the crm-backup container (plaintext never touches the host
#      disk) and restores the database in a single transaction (a failed restore
#      leaves the database as it was),
#   4. replaces runtime/media with the archived files, if --media is given,
#   5. starts everything, waits for /health/ready and prints record counts.
# Encrypted files (.age) need --identity: the age private key, kept off this host.
set -euo pipefail

APP="${CRM_APP_DIR:-$(pwd)}"
DB=""; MEDIA=""; IDENTITY=""; YES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB="$2"; shift 2 ;;
    --media) MEDIA="$2"; shift 2 ;;
    --identity) IDENTITY="$2"; shift 2 ;;
    --yes) YES=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$DB" ] || { echo "usage: restore.sh --db FILE [--media FILE] [--identity KEY] [--yes]" >&2; exit 2; }
test -f "$APP/compose.yaml" || { echo "FATAL: $APP is not the CRM project directory" >&2; exit 1; }
COMPOSE="docker compose --project-directory $APP"

absolute() { (cd "$(dirname "$1")" && printf '%s/%s' "$(pwd)" "$(basename "$1")"); }
DB="$(absolute "$DB")"
[ -z "$MEDIA" ] || MEDIA="$(absolute "$MEDIA")"
[ -z "$IDENTITY" ] || IDENTITY="$(absolute "$IDENTITY")"
for file in "$DB" $MEDIA; do
  test -s "$file" || { echo "FATAL: $file is missing or empty" >&2; exit 1; }
  case "$file" in *.age) test -s "$IDENTITY" || { echo "FATAL: $file is encrypted; pass --identity" >&2; exit 1; } ;; esac
done

# --- 1. checksums ---------------------------------------------------------
stamp="$(basename "$DB" | sed -E 's/^db-([0-9]{8}-[0-9]{6}).*/\1/')"
sums="$(dirname "$DB")/SHA256SUMS-$stamp"
if [ -f "$sums" ]; then
  for file in "$DB" $MEDIA; do
    (cd "$(dirname "$sums")" && grep " $(basename "$file")\$" "$sums" | sha256sum -c --quiet -) \
      || { echo "FATAL: checksum mismatch for $file" >&2; exit 1; }
  done
  echo ">>> checksums verified ($sums)"
else
  echo "!!! no SHA256SUMS-$stamp next to the dump; restoring without checksum verification"
fi

if [ -z "$YES" ]; then
  printf 'This REPLACES the CRM database%s in %s.\nType RESTORE to continue: ' "${MEDIA:+ and uploaded files}" "$APP"
  read -r answer
  [ "$answer" = "RESTORE" ] || { echo "aborted"; exit 1; }
fi

# Stream a backup file through the crm-backup container, decrypting when needed.
decrypted() {
  if [[ "$1" == *.age ]]; then
    $COMPOSE run --rm -T --no-deps -v "$IDENTITY:/identity:ro" --entrypoint age crm-backup -d -i /identity < "$1"
  else
    cat "$1"
  fi
}

# --- 2. stop the application ---------------------------------------------
echo ">>> stopping crm-web and crm-worker"
$COMPOSE stop crm-web crm-worker >/dev/null 2>&1 || true
$COMPOSE up -d crm-db
for _ in $(seq 1 30); do
  $COMPOSE exec -T crm-db pg_isready -U crm -d crm < /dev/null >/dev/null 2>&1 && break
  sleep 2
done

# --- 3. database -----------------------------------------------------------
echo ">>> restoring the database from $(basename "$DB")"
decrypted "$DB" | $COMPOSE exec -T crm-db pg_restore --clean --if-exists --no-owner --no-privileges \
  --single-transaction --exit-on-error -U crm -d crm

# --- 4. media --------------------------------------------------------------
if [ -n "$MEDIA" ]; then
  echo ">>> restoring uploaded files from $(basename "$MEDIA")"
  mkdir -p "$APP/runtime/media"
  decrypted "$MEDIA" | $COMPOSE run --rm -T --no-deps -v "$APP/runtime/media:/restore" --entrypoint sh crm-backup \
    -c 'find /restore -mindepth 1 -delete && tar xzf - -C /restore'
fi

# --- 5. start and prove it --------------------------------------------------
echo ">>> starting the CRM"
$COMPOSE up -d
for _ in $(seq 1 60); do
  if $COMPOSE exec -T crm-web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health/ready', timeout=3)" < /dev/null >/dev/null 2>&1; then
    $COMPOSE exec -T crm-web python manage.py shell -v 0 -c \
      "from contacts.models import Person, Company, Activity, Attachment; print('restored: %d people, %d companies, %d activities, %d attachments' % (Person.objects.count(), Company.objects.count(), Activity.objects.count(), Attachment.objects.count()))" < /dev/null
    echo ">>> restore complete"
    exit 0
  fi
  sleep 3
done
echo "FATAL: crm-web did not become ready after the restore" >&2
exit 1
