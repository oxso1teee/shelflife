#!/usr/bin/env bash
# ShelfLife backup: a consistent copy of the SQLite database (taken with the
# site running) and an archive of the uploaded logos, into ./backups by default.
# Keeps the newest KEEP backups (default 14).
#
#   ./scripts/backup.sh                 # from cron: 0 3 * * * cd /opt/shelflife && ./scripts/backup.sh
#   BACKUP_DIR=/mnt/backups KEEP=30 ./scripts/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

DEST=${BACKUP_DIR:-./backups}
KEEP=${KEEP:-14}
STAMP=$(date +%Y%m%d-%H%M%S)
TMP=/tmp/shelflife-backup-$STAMP.db
mkdir -p "$DEST"

# SQLite's online backup copies a consistent state even while the site writes.
docker compose exec -T web sqlite3 /var/www/html/db/wallos.db ".backup '$TMP'"
if [ "$(docker compose exec -T web sqlite3 "$TMP" 'PRAGMA integrity_check;' | tr -d '\r')" != "ok" ]; then
  echo "backup failed the integrity check" >&2
  docker compose exec -T web rm -f "$TMP"
  exit 1
fi
docker compose cp "web:$TMP" "$DEST/shelflife-$STAMP.db" >/dev/null
docker compose exec -T web rm -f "$TMP"
tar -czf "$DEST/shelflife-logos-$STAMP.tar.gz" -C .data logos

# Rotation
ls -1t "$DEST"/shelflife-[0-9]*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
ls -1t "$DEST"/shelflife-logos-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "$(date '+%F %T') backup written: $DEST/shelflife-$STAMP.db"
