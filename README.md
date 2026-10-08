# Учёт НИР

Веб-приложение для учёта научной работы преподавателей со студентами (курсантами): справочники, работы и их статусы, достижения, импорт PDF-анкет `prepod_vnok_info` с проверкой и возвратом преподавателю, выдача копий формы, 10 отчётов с выгрузкой, API только для чтения.

Требования: [doc/tz.md](doc/tz.md) (версия 0.2). Документация: [руководство администратора](doc/admin-guide.md), [руководство пользователя](doc/user-guide.md).

Стек: Python 3.12, Django 5.2 LTS, PostgreSQL 17, gunicorn, nginx, Docker Compose.

## Быстрый старт

Нужны Docker и Docker Compose v2.

```bash
cp .env.example .env        # заполнить DJANGO_SECRET_KEY, POSTGRES_PASSWORD, DJANGO_SUPERUSER_*
docker compose up -d --build
```

Откройте `https://localhost` (или `https://localhost:$HTTPS_PORT`) и войдите под `DJANGO_SUPERUSER_USERNAME`. Если сертификат не подключён, nginx создаёт самоподписанный — браузер предупредит об этом.

Дальше администратор:

1. «Администрирование → Пользователи, роли» — создать кафедры и пользователей, назначить роли (ответственный кафедры, наблюдатель) и связать учётные записи преподавателей с карточками преподавателей.
2. «Импорт → Шаблон формы» — загрузить пустую форму (`prepod_vnok_info-v2.0-draft04.pdf`), чтобы ответственные могли готовить копии.

## Состав

| Каталог | Назначение |
| --- | --- |
| `config/` | Настройки Django (все параметры — переменные окружения, см. `.env.example`) |
| `accounts/` | Роли и области данных (`access.py`), аудит, блокировка входа, вход через LDAP |
| `registry/` | Кафедры, преподаватели, группы, студенты, работы, достижения, статусы, история |
| `imports/` | Импорт PDF: адаптеры форм, сопоставление, предпросмотр, возврат, выдача копий, фоновый обработчик |
| `imports/adapters/prepod_vnok_info_v2/vendor/` | Копия `extract_static.py`, `acroform.py`, `prepare_copy.py` из проекта формы, без изменений |
| `reports/` | 10 отчётов, выгрузки HTML/XLSX/CSV/PDF |
| `api/` | REST API только для чтения (`/api/`) |
| `templates/`, `static/` | Интерфейс; Bootstrap 5.3.3 лежит локально, без CDN |
| `docker/`, `compose.yaml`, `Dockerfile` | Развёртывание |
| `scripts/` | Резервное копирование и восстановление |
| `tests/` | Тесты, включая 20 примеров анкет |

## Разработка

```bash
uv venv .venv --python 3.12 && uv pip install -p .venv/bin/python -r requirements-dev.txt
DJANGO_DEBUG=1 .venv/bin/python manage.py migrate
DJANGO_DEBUG=1 .venv/bin/python manage.py createsuperuser
DJANGO_DEBUG=1 .venv/bin/python manage.py runserver
.venv/bin/pytest                      # 66 тестов; без POSTGRES_HOST — на SQLite
```

Без `POSTGRES_HOST` приложение использует SQLite (только для разработки и тестов). Разработка в Docker: `docker compose -f compose.yaml -f compose.dev.yaml up` — runserver на `http://localhost:8000`, без nginx.

Тесты на PostgreSQL в контейнере:

```bash
docker compose run --rm --no-deps -e RUN_MIGRATIONS=0 web sh -c \
  "pip install -q --target /tmp/t pytest==9.1.1 pytest-django==4.14.0 && PYTHONPATH=/tmp/t python -m pytest -p no:cacheprovider"
```
