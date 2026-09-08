#!/bin/sh
# Periodic PostgreSQL + media backup with simple daily retention.
# Runs as its own Compose service; see compose.yaml (crm-backup).
set -eu

DEST=/backups
KEEP="${BACKUP_KEEP:-14}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
mkdir -p "$DEST"

while true; do
  ts=$(date +%Y%m%d-%H%M%S)
  echo "[backup] $ts start"
  if PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -U "$DB_USER" -Fc "$DB_NAME" > "$DEST/db-$ts.dump.part"; then
    mv "$DEST/db-$ts.dump.part" "$DEST/db-$ts.dump"
  else
    rm -f "$DEST/db-$ts.dump.part"
    echo "[backup] $ts pg_dump FAILED"
  fi
  if [ -d /media ]; then
    tar czf "$DEST/media-$ts.tar.gz.part" -C /media . && mv "$DEST/media-$ts.tar.gz.part" "$DEST/media-$ts.tar.gz" || rm -f "$DEST/media-$ts.tar.gz.part"
  fi
  # Keep only the newest $KEEP of each kind.
  for prefix in db media; do
    ls -1t "$DEST"/$prefix-* 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f "$old"; done
  done
  echo "[backup] $ts done ($(ls -1 "$DEST" | wc -l) files kept)"
  sleep "$INTERVAL"
done
