#!/bin/sh
# Порядок запуска web (ТЗ 11.2): ожидание БД → migrate → collectstatic → первый администратор → команда.
set -e
python - <<'PY'
import os, time, psycopg
for attempt in range(60):
    try:
        psycopg.connect(host=os.environ['POSTGRES_HOST'], port=os.environ.get('POSTGRES_PORT', '5432'),
                        dbname=os.environ['POSTGRES_DB'], user=os.environ['POSTGRES_USER'],
                        password=os.environ['POSTGRES_PASSWORD'], connect_timeout=3).close()
        break
    except psycopg.OperationalError:
        time.sleep(2)
else:
    raise SystemExit('База данных недоступна')
PY
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput --verbosity 0
  python manage.py ensure_superuser
fi
exec "$@"
