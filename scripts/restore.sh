#!/bin/sh
# Восстановление из резервной копии: scripts/restore.sh backups/db-ДАТА.dump backups/media-ДАТА.tar.gz
# ВНИМАНИЕ: текущие данные базы и загруженные файлы заменяются.
set -eu
DB_DUMP=$1
MEDIA_ARCHIVE=$2
[ -f "$DB_DUMP" ] && [ -f "$MEDIA_ARCHIVE" ] || { echo "Файлы не найдены"; exit 1; }
docker compose stop worker web nginx
docker compose up -d db
until docker compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; do sleep 1; done
docker compose exec -T db sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$DB_DUMP"
docker compose run --rm -T --no-deps --entrypoint sh web -c 'find /data/media -mindepth 1 -delete && tar -C /data/media -xzf -' < "$MEDIA_ARCHIVE"
docker compose up -d
echo "Восстановлено из $DB_DUMP и $MEDIA_ARCHIVE"
