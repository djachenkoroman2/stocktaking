#!/bin/sh
# Резервная копия (ТЗ 11.2): дамп PostgreSQL (pg_dump, формат custom) и архив тома media.
# Использование: scripts/backup.sh [каталог]   (по умолчанию ./backups). Запускать из каталога проекта.
set -eu
DIR=${1:-./backups}
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$DIR"
docker compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$DIR/db-$STAMP.dump"
docker compose exec -T web tar -C /data/media -czf - . > "$DIR/media-$STAMP.tar.gz"
echo "Готово: $DIR/db-$STAMP.dump, $DIR/media-$STAMP.tar.gz"
