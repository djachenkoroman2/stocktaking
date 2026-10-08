# Руководство администратора

Система «Учёт НИР», требования — [tz.md](tz.md). Команды выполняются из каталога проекта.

## 1. Установка

Требования к серверу: Linux с Docker Engine 24+ и Docker Compose v2, 2 ГБ памяти, место под базу данных и PDF (расчёт — ТЗ 11.4: около 25 ГБ на 50 000 загрузок). Доступ в интернет нужен только для сборки образов; работающая система внешних ресурсов не использует.

1. Скопировать проект на сервер.
2. `cp .env.example .env` и заполнить:
   - `DJANGO_SECRET_KEY` — длинная случайная строка, например `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`;
   - `POSTGRES_PASSWORD`;
   - `DJANGO_ALLOWED_HOSTS` и `DJANGO_CSRF_TRUSTED_ORIGINS` — имя сервера; в `DJANGO_CSRF_TRUSTED_ORIGINS` — полный адрес со схемой и портом, если он не 443: `https://nir.example.org:8443`;
   - `SERVER_NAME`, `HTTP_PORT`, `HTTPS_PORT`;
   - `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD` — первый администратор (можно не задавать и создать позже).
3. Сертификат: положить `server.crt` и `server.key` в каталог `TLS_CERT_DIR` (по умолчанию `docker/certs/`). Если файлов нет, при запуске создаётся самоподписанный сертификат на год — только для проверки.
4. `docker compose up -d --build`.
5. Проверить: `curl -k https://localhost:$HTTPS_PORT/health/` → `{"status": "ok", "database": true, "storage": true}`.

Администратора без переменных окружения: `docker compose exec web python manage.py createsuperuser`.

### Сервисы и тома

| Сервис | Назначение |
| --- | --- |
| `db` | PostgreSQL 17, том `pgdata` |
| `web` | Django + gunicorn. При запуске: ожидание БД, `migrate`, `collectstatic`, создание администратора из `DJANGO_SUPERUSER_*` |
| `worker` | Фоновая обработка пакетов больше `IMPORT_SYNC_LIMIT` файлов; уведомления (`NOTIFY_PENDING_HOURS`) |
| `nginx` | HTTPS, статика, перенаправление с HTTP |

Тома: `pgdata` (база), `media` (загруженные PDF, выданные копии, шаблон формы), `static` (пересобирается при запуске). Файлы из `media` отдаются только через приложение с проверкой прав — nginx их не публикует.

## 2. Пользователи и роли

«Администрирование → Пользователи, роли, настройки» (админ-панель Django, `/admin/`). В карточке пользователя — блок «Роли»:

| Роль | Кафедра | Что даёт |
| --- | --- | --- |
| Администратор | пусто | Вся система, кроме контактов студентов |
| Ответственный кафедры | кафедра или пусто (все) | Ввод данных, импорт, возврат, копии, контакты студентов своей области |
| Наблюдатель | кафедра или пусто (все) | Просмотр и отчёты без контактов |

Роль «Преподаватель» — это связь: в карточке преподавателя (в интерфейсе, «Преподаватели → Изменить», поле «Учётная запись») выбрать пользователя. Преподаватель видит только свои работы, без контактов студентов.

Суперпользователь Django — администратор системы. Чтобы администратор видел контакты, ему нужна ещё и роль ответственного (ТЗ 3.2, вопрос 20).

Новую кафедру создаёт администратор («Справочники → Кафедры»). Ответственный с областью «все кафедры» тоже может создать кафедру из предпросмотра импорта.

### Токены API

`/admin/authtoken/tokenproxy/` → «Добавить», выбрать пользователя. Запросы: `curl -H "Authorization: Token <ключ>" https://сервер/api/works/`. API отдаёт данные в правах этого пользователя. Ресурсы: `departments`, `groups`, `teachers`, `students`, `works` (фильтры `teacher`, `student`, `status`, `academic_year`, `department`).

### Вход через LDAP / Active Directory

В `.env`: `LDAP_ENABLED=1`, `LDAP_SERVER_URI`, затем один из режимов:

- шаблон DN: `LDAP_USER_DN_TEMPLATE=uid={username},ou=people,dc=example,dc=org` (для AD — `{username}@example.org`);
- поиск: `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD`, `LDAP_SEARCH_BASE`, `LDAP_SEARCH_FILTER` (для AD — `(sAMAccountName={username})`).

При первом входе создаётся локальная учётная запись без пароля; ФИО и почта берутся из атрибутов `LDAP_ATTR_*`. Роли назначает администратор. Локальные учётные записи продолжают работать.

## 3. Шаблон формы

«Импорт → Шаблон формы» — загрузить пустую форму `prepod_vnok_info` версии 2.0 (сейчас `prepod_vnok_info-v2.0-draft04.pdf` из проекта формы). Система проверяет, что это поддерживаемая форма без ID анкеты. Текущий шаблон используется для всех новых копий.

## 4. Резервное копирование и восстановление

```bash
scripts/backup.sh /путь/к/резервным/копиям      # db-ДАТА.dump (pg_dump -Fc) и media-ДАТА.tar.gz
scripts/restore.sh /путь/db-ДАТА.dump /путь/media-ДАТА.tar.gz
```

`restore.sh` останавливает приложение, **заменяет** данные базы и файлы, запускает всё снова. Расписание копирования — cron на сервере, например ежедневно в 02:00:

```cron
0 2 * * * cd /opt/stocktaking && scripts/backup.sh /backup/stocktaking >> /var/log/stocktaking-backup.log 2>&1
```

Храните копии вне сервера. Резервные копии содержат персональные данные студентов.

## 5. Обновление

```bash
scripts/backup.sh /backup/stocktaking
git pull                      # или скопировать новую версию
docker compose up -d --build  # миграции применяются при запуске web
```

Откат миграций — вручную: `docker compose exec web python manage.py migrate <приложение> <миграция>`, затем запустить предыдущую версию образа. Надёжнее — восстановить резервную копию.

## 6. Обслуживание

| Задача | Команда |
| --- | --- |
| Журналы | `docker compose logs -f web worker` |
| Удалить исходные PDF старше N дней (данные остаются) | `docker compose exec web python manage.py purge_pdfs --older-than-days 1095 [--dry-run]` |
| Разослать уведомления ответственным сейчас | `docker compose exec web python manage.py notify_pending` |
| Обработать очередь импорта вручную | `docker compose exec web python manage.py run_worker --once` |
| Журнал аудита | «Администрирование → Журнал аудита» |

Уведомления по почте: задать `EMAIL_HOST` и соседние переменные, `SITE_URL` и `NOTIFY_PENDING_HOURS` (например, 24). Письма содержат только число загрузок и ссылку, без данных студентов.

## 7. Обновление копии модулей формы

Если в проекте формы изменились `extract_static.py`, `acroform.py` или `prepare_copy.py`, — порядок в [imports/adapters/prepod_vnok_info_v2/vendor/README.md](../imports/adapters/prepod_vnok_info_v2/vendor/README.md). Новая версия схемы данных — новый адаптер; анкеты в состоянии «Версия не поддерживается» после этого обрабатываются заново кнопкой в карточке загрузки.
