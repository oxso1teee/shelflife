#!/usr/bin/env bash
# ShelfLife restore: replaces the database (and optionally the logos) with a
# backup made by scripts/backup.sh. The site and the bot are stopped meanwhile;
# on start the web container applies any newer migrations to the restored data.
#
#   ./scripts/restore.sh backups/shelflife-20261014-030000.db [backups/shelflife-logos-20261014-030000.tar.gz]
set -euo pipefail
cd "$(dirname "$0")/.."

DB=${1:?usage: restore.sh <backup.db> [logos.tar.gz]}
LOGOS=${2:-}
DB_ABS=$(realpath "$DB")

# Check the backup before touching anything (with the sqlite3 of the web image).
CHECK=$(docker compose run --rm --no-deps -T -v "$DB_ABS:/restore/backup.db:ro" --entrypoint sqlite3 web \
  /restore/backup.db 'PRAGMA integrity_check;' | tr -d '\r')
if [ "$CHECK" != "ok" ]; then
  echo "$DB does not pass the integrity check: $CHECK" >&2
  exit 1
fi

docker compose stop bot web
docker compose run --rm --no-deps -T -v "$DB_ABS:/restore/backup.db:ro" --entrypoint sh web -c '
  cp /restore/backup.db /var/www/html/db/wallos.db &&
  rm -f /var/www/html/db/wallos.db-wal /var/www/html/db/wallos.db-shm &&
  chown www-data:www-data /var/www/html/db/wallos.db'

if [ -n "$LOGOS" ]; then
  LOGOS_ABS=$(realpath "$LOGOS")
  docker compose run --rm --no-deps -T -v "$LOGOS_ABS:/restore/logos.tar.gz:ro" --entrypoint sh web -c '
    rm -rf /var/www/html/images/uploads/logos/* &&
    tar -xzf /restore/logos.tar.gz -C /var/www/html/images/uploads &&
    chown -R www-data:www-data /var/www/html/images/uploads/logos'
fi

docker compose up -d web bot
echo "restored $DB"
