#!/bin/bash
# Periodic PostgreSQL + media backup: encrypted, checksummed, optionally copied
# off the host. Runs as the crm-backup service (deploy/backup/Dockerfile).
#
# Each run writes one set, named by UTC timestamp:
#   db-<ts>.dump[.age]        pg_dump custom format
#   media-<ts>.tar.gz[.age]   uploaded files
#   SHA256SUMS-<ts>           checksums of the two files above
#   manifest-<ts>.json        what the set is
# and touches `last-success`, which the container health check reads.
#
# Encryption: set BACKUP_AGE_RECIPIENTS (age public keys, space separated) or
# put them in /config/age-recipients.txt. The private key never goes on this
# host — restore with scripts/restore.sh --identity <key>. Without recipients
# the set is written in plain form and every run logs a warning, unless
# BACKUP_REQUIRE_ENCRYPTION=true, which refuses to start.
#
# Off-host copy: BACKUP_REMOTE=<rclone remote:path> with /config/rclone.conf;
# copies older than BACKUP_REMOTE_KEEP_DAYS are removed from the remote.
set -euo pipefail

DEST=/backups
KEEP="${BACKUP_KEEP:-14}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
ONCE="${BACKUP_ONCE:-false}"
RECIPIENTS="${BACKUP_AGE_RECIPIENTS:-}"
RECIPIENTS_FILE="${BACKUP_AGE_RECIPIENTS_FILE:-/config/age-recipients.txt}"
REQUIRE_ENCRYPTION="${BACKUP_REQUIRE_ENCRYPTION:-false}"
REMOTE="${BACKUP_REMOTE:-}"
REMOTE_KEEP_DAYS="${BACKUP_REMOTE_KEEP_DAYS:-30}"
export RCLONE_CONFIG="${RCLONE_CONFIG:-/config/rclone.conf}"

log() {  # level message — one JSON line, like the application logs
  printf '{"ts":"%s","level":"%s","logger":"crm.backup","message":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2"
}

encrypting() { [ -n "$RECIPIENTS" ] || [ -s "$RECIPIENTS_FILE" ]; }

encrypt() {  # stdin -> stdout
  if encrypting; then
    local args=()
    for recipient in $RECIPIENTS; do args+=(-r "$recipient"); done
    [ -s "$RECIPIENTS_FILE" ] && args+=(-R "$RECIPIENTS_FILE")
    age "${args[@]}"
  else
    cat
  fi
}

if ! encrypting; then
  if [ "$REQUIRE_ENCRYPTION" = "true" ]; then
    log ERROR "BACKUP_REQUIRE_ENCRYPTION=true but no age recipients are configured; refusing to write backups"
    exit 1
  fi
fi

run_once() {
  local ts ext db media sums manifest
  ts=$(date -u +%Y%m%d-%H%M%S)
  ext=""
  encrypting && ext=".age"
  db="db-$ts.dump$ext"
  media="media-$ts.tar.gz$ext"
  sums="SHA256SUMS-$ts"
  manifest="manifest-$ts.json"
  mkdir -p "$DEST"
  encrypting || log WARNING "backup set $ts is NOT encrypted: configure BACKUP_AGE_RECIPIENTS"

  # `set -e` does not apply inside a function called from `if`, so every step
  # checks its own status.
  PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -U "$DB_USER" -Fc "$DB_NAME" | encrypt > "$DEST/$db.part" \
    || { log ERROR "pg_dump for $ts failed"; return 1; }
  if [ -d /media ]; then
    tar czf - -C /media . | encrypt > "$DEST/$media.part" || { log ERROR "media archive for $ts failed"; return 1; }
  else
    tar czf - --files-from /dev/null | encrypt > "$DEST/$media.part" || { log ERROR "media archive for $ts failed"; return 1; }
  fi
  [ -s "$DEST/$db.part" ] || { log ERROR "database dump for $ts is empty"; return 1; }
  if ! encrypting; then
    pg_restore --list "$DEST/$db.part" > /dev/null || { log ERROR "database dump for $ts is unreadable"; return 1; }
  fi
  mv "$DEST/$db.part" "$DEST/$db" && mv "$DEST/$media.part" "$DEST/$media" \
    && (cd "$DEST" && sha256sum "$db" "$media" > "$sums") \
    || { log ERROR "finishing backup set $ts failed"; return 1; }
  printf '{"created_at":"%s","database":"%s","media":"%s","encrypted":%s,"pg_dump":"%s","checksums":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$db" "$media" "$(encrypting && echo true || echo false)" \
    "$(pg_dump --version | awk '{print $NF}')" "$sums" > "$DEST/$manifest"

  if [ -n "$REMOTE" ]; then
    rclone copy "$DEST" "$REMOTE" --include "*-$ts*" \
      || { log ERROR "off-host copy of $ts to $REMOTE failed"; return 1; }
    rclone delete "$REMOTE" --min-age "${REMOTE_KEEP_DAYS}d" --include "*-2*" \
      || log WARNING "could not prune old copies on $REMOTE"
  fi

  # Keep the newest $KEEP sets of each kind.
  for prefix in db media SHA256SUMS manifest; do
    ls -1t "$DEST"/"$prefix"-* 2>/dev/null | grep -v '\.part$' | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f "$old"; done
  done
  date -u +%Y-%m-%dT%H:%M:%SZ > "$DEST/last-success" || return 1
  log INFO "backup set $ts written ($(du -h "$DEST/$db" | cut -f1) database, $(du -h "$DEST/$media" | cut -f1) media)"
}

while true; do
  if ! run_once; then
    rm -f "$DEST"/*.part
    [ "$ONCE" = "true" ] && exit 1
  fi
  [ "$ONCE" = "true" ] && exit 0
  sleep "$INTERVAL"
done
