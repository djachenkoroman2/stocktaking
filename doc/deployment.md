# Развёртывание

Пошаговая установка системы «Учёт НИР» на сервер, настройка, проверка, обновление и перенос. Краткая версия и работа с пользователями — в [руководстве администратора](admin-guide.md), требования к развёртыванию — [ТЗ, раздел 11](tz.md#11-нефункциональные-требования).

Все команды выполняются из каталога проекта на сервере (в примерах — `/opt/stocktaking`), если не сказано иное.

## 1. Схема

```
            HTTP_PORT (80) ──┐
браузер / API ──────────────►│ nginx ──► web (Django + gunicorn, :8000) ──► db (PostgreSQL 17)
           HTTPS_PORT (443) ─┘   │              │                             ▲
                                 │ /static/     │ /data/media                  │
                                 ▼              ▼                              │
                              том static     том media ◄── worker (импорт, уведомления)
```

| Сервис | Образ | Что делает | Порты наружу |
| --- | --- | --- | --- |
| `db` | `postgres:17` | База данных, том `pgdata` | нет |
| `web` | `stocktaking-app:latest` (собирается из `Dockerfile`) | Django + gunicorn (3 процесса, тайм-аут 180 с). При старте применяет миграции, собирает статику, создаёт первого администратора | нет |
| `worker` | тот же образ | Обрабатывает пакеты импорта больше `IMPORT_SYNC_LIMIT` файлов, рассылает уведомления | нет |
| `nginx` | собирается из `docker/nginx/` на основе `nginx:1.28-alpine` | HTTPS, отдача статики, перенаправление HTTP → HTTPS, проксирование на `web` | `HTTP_PORT`, `HTTPS_PORT` |

Порядок запуска задают проверки готовности: `db` (`pg_isready`) → `web` (`/health/`) → `worker` и `nginx`. Наружу открыт только nginx; база и приложение доступны лишь внутри сети Compose.

Тома:

| Том | Содержимое | Резервное копирование |
| --- | --- | --- |
| `pgdata` | Данные PostgreSQL | Через `pg_dump` (`scripts/backup.sh`), не копированием тома |
| `media` | Загруженные PDF, выданные копии, шаблон формы | Да, архивом (`scripts/backup.sh`) |
| `static` | Собранная статика | Нет, пересобирается при каждом запуске `web` |
| `exports` | Архивы выгрузки в JSON ([руководство администратора, раздел 8](admin-guide.md#8-выгрузка-в-json-и-восстановление)) | Нет: забирайте нужные архивы с сервера, ненужные удаляйте — в них персональные данные |

Каталог `media` nginx не публикует: файлы отдаёт приложение после проверки прав.

## 2. Требования к серверу

| Ресурс | Минимум | Примечание |
| --- | --- | --- |
| ОС | Linux x86-64 | Проверено на Ubuntu; подойдёт любой дистрибутив с Docker |
| Docker | Docker Engine 24+, Docker Compose v2 (`docker compose`, не `docker-compose`) | |
| Процессор | 2 ядра | |
| Память | 2 ГБ | PostgreSQL + 3 процесса gunicorn + обработчик |
| Диск | 10 ГБ для начала | Расчёт на полный объём ТЗ (50 000 загрузок) — около 25 ГБ под PDF плюс база и резервные копии |
| Сеть | Входящие `HTTP_PORT` и `HTTPS_PORT` | Интернет нужен только при сборке образов (Docker Hub, PyPI, репозиторий Debian). Работающая система внешних ресурсов не использует |

Также понадобятся DNS-имя сервера (например, `nir.example.org`) и, для рабочей эксплуатации, TLS-сертификат на это имя.

## 3. Подготовка сервера

### 3.1. Docker

Ubuntu/Debian — по [официальной инструкции Docker](https://docs.docker.com/engine/install/). Кратко для Ubuntu:

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
```

Проверка:

```bash
docker --version          # 24 и новее
docker compose version    # v2.x
```

Чтобы не писать `sudo` перед каждой командой, добавьте пользователя-администратора в группу `docker` (`sudo usermod -aG docker $USER`, затем перелогиниться). Учтите: членство в этой группе равнозначно правам root.

Docker сам запускается при загрузке системы, а сервисы проекта перезапускаются автоматически (`restart: unless-stopped`), поэтому отдельный systemd-юнит не нужен.

### 3.2. Сетевой экран

Откройте только порты nginx. Пример для `ufw`:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

Порты, опубликованные Docker, обходят правила `ufw` в цепочке INPUT. Если сервер не должен быть доступен из какой-то сети, ограничьте доступ на внешнем сетевом экране или в цепочке `DOCKER-USER`.

### 3.3. Код проекта

```bash
sudo mkdir -p /opt/stocktaking && sudo chown $USER /opt/stocktaking
git clone <адрес репозитория> /opt/stocktaking
cd /opt/stocktaking
```

Без доступа к репозиторию — скопировать каталог проекта архивом (`scp`, `rsync`). Каталоги `.venv`, `db.sqlite3`, `media`, `backups` и `.env` с машины разработчика переносить не нужно.

## 4. Настройка `.env`

```bash
cp .env.example .env
chmod 600 .env          # в файле пароли
```

Файл читают все сервисы. Ниже — что заполнить обязательно и что можно оставить по умолчанию.

### 4.1. Обязательные параметры

| Переменная | Что указать |
| --- | --- |
| `DJANGO_SECRET_KEY` | Длинная случайная строка. Сгенерировать: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Без неё приложение не запустится. Смена ключа завершает все сеансы пользователей |
| `DJANGO_DEBUG` | `0`. Режим `1` только для разработки: он показывает трассировки и отключает защищённые cookie |
| `DJANGO_ALLOWED_HOSTS` | Имена, по которым открывают сайт, через запятую: `nir.example.org`. Оставьте `localhost` — по нему идёт внутренняя проверка `/health/` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Полный адрес со схемой: `https://nir.example.org`. Если порт не 443 — с портом: `https://nir.example.org:8443`. Иначе формы (в том числе вход) будут отклоняться с ошибкой CSRF |
| `POSTGRES_PASSWORD` | Пароль базы. Используется при **первом** создании тома `pgdata`; позже его смена в `.env` пароль в базе не меняет (см. [раздел 11](#11-смена-паролей-и-ключей)) |
| `SERVER_NAME` | Имя сервера для nginx и самоподписанного сертификата: `nir.example.org` |
| `SITE_URL` | Адрес сайта для ссылок в письмах: `https://nir.example.org` |

### 4.2. Первый администратор

| Переменная | Назначение |
| --- | --- |
| `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` | При каждом запуске `web` создаётся суперпользователь, если заданы имя и пароль и такого пользователя ещё нет. Существующего пользователя команда не меняет |

После первого входа пароль лучше сменить в интерфейсе и удалить `DJANGO_SUPERUSER_PASSWORD` из `.env`. Можно вообще не задавать эти переменные и создать администратора вручную ([раздел 6.3](#63-первый-администратор)).

### 4.3. Порты и сертификат

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `HTTP_PORT` | `80` | Порт HTTP на сервере; с него всё перенаправляется на HTTPS |
| `HTTPS_PORT` | `443` | Порт HTTPS на сервере |
| `TLS_CERT_DIR` | `./docker/certs` | Каталог на сервере с `server.crt` и `server.key` |

Если 80/443 заняты другим веб-сервером, задайте другие порты (например, 8081/8443) и не забудьте указать порт в `DJANGO_CSRF_TRUSTED_ORIGINS` и `SITE_URL`.

### 4.4. Необязательные параметры

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `TIME_ZONE` | `Europe/Moscow` | Часовой пояс приложения |
| `LOG_LEVEL` | `INFO` | Уровень журнала: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `IMPORT_MAX_FILE_MB` | `10` | Наибольший размер одного PDF |
| `IMPORT_MAX_FILES` | `200` | Наибольшее число файлов в пакете |
| `IMPORT_MAX_BATCH_MB` | `200` | Наибольший размер пакета. Больше 200 — поменять и `client_max_body_size` в `docker/nginx/default.conf.template` |
| `IMPORT_SYNC_LIMIT` | `20` | Пакеты больше этого числа файлов обрабатывает `worker` в фоне |
| `STALE_WORK_DAYS` | `90` | Порог «давно не обновлялась» в отчёте «Качество данных» |
| `EXPORT_SYNC_ROWS` | `5000` | Выгрузка в JSON без файлов и не больше этого числа записей выполняется сразу, иначе — в фоне через `worker` |
| `LOGIN_MAX_FAILURES`, `LOGIN_LOCK_MINUTES` | `10`, `15` | Блокировка входа после неудачных попыток |
| `DJANGO_SECURE_COOKIES` | `1` | Cookie только по HTTPS. Выключать (`0`) только для проверки без HTTPS |
| `NOTIFY_PENDING_HOURS` | `0` | Раз в сколько часов напоминать ответственным о загрузках, ожидающих проверки; `0` — не напоминать |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | пусто, `25`, …, `stocktaking@localhost` | SMTP-сервер для уведомлений. Без `EMAIL_HOST` письма только пишутся в журнал |
| `LDAP_*` | выключено | Вход через LDAP / Active Directory, см. [руководство администратора](admin-guide.md#вход-через-ldap--active-directory) |

`POSTGRES_HOST` и `POSTGRES_PORT` задаются в `compose.yaml`, в `.env` их указывать не нужно.

### 4.5. Пример для рабочего сервера

```dotenv
DJANGO_SECRET_KEY=Zq3...сгенерированная-строка...
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=nir.example.org,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://nir.example.org
TIME_ZONE=Europe/Moscow
LOG_LEVEL=INFO

POSTGRES_DB=stocktaking
POSTGRES_USER=stocktaking
POSTGRES_PASSWORD=...

DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@example.org
DJANGO_SUPERUSER_PASSWORD=...

SERVER_NAME=nir.example.org
HTTP_PORT=80
HTTPS_PORT=443
TLS_CERT_DIR=/etc/stocktaking/certs

SITE_URL=https://nir.example.org
NOTIFY_PENDING_HOURS=24
EMAIL_HOST=smtp.example.org
EMAIL_PORT=587
EMAIL_USE_TLS=1
EMAIL_HOST_USER=stocktaking
EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=nir@example.org
```

## 5. TLS-сертификат

nginx берёт `server.crt` и `server.key` из `TLS_CERT_DIR`.

**Сертификат организации.** Положите в каталог файл сертификата (вместе с цепочкой промежуточных сертификатов, сертификат сервера первым) под именем `server.crt` и закрытый ключ под именем `server.key`:

```bash
sudo mkdir -p /etc/stocktaking/certs
sudo cp nir.example.org-fullchain.pem /etc/stocktaking/certs/server.crt
sudo cp nir.example.org.key           /etc/stocktaking/certs/server.key
sudo chmod 600 /etc/stocktaking/certs/server.key
```

**Самоподписанный сертификат.** Если файлов нет, nginx при запуске создаёт самоподписанный сертификат на год на имя `SERVER_NAME` и сохраняет его в `TLS_CERT_DIR`. Браузеры предупредят о нём — годится только для проверки и пробной эксплуатации.

**Замена сертификата.** Заменить файлы и перезапустить nginx: `docker compose restart nginx`.

**Let's Encrypt.** Если сервер доступен из интернета, сертификат можно получить `certbot` в режиме `standalone` (порт 80 на время выпуска должен быть свободен: `docker compose stop nginx`) и копировать `fullchain.pem`/`privkey.pem` в `TLS_CERT_DIR` хуком `--deploy-hook` с последующим `docker compose restart nginx`.

nginx отдаёт заголовок HSTS на год: после первого захода браузер будет открывать сайт только по HTTPS.

## 6. Первый запуск

### 6.1. Сборка и запуск

```bash
docker compose up -d --build
```

Первая сборка занимает несколько минут: скачиваются базовые образы, системные библиотеки WeasyPrint и шрифты, Python-зависимости из `requirements.txt`.

Следить за запуском:

```bash
docker compose ps                    # все сервисы Up, у db и web — (healthy)
docker compose logs -f web           # миграции, «Создан администратор …», запуск gunicorn
```

`web` становится `healthy` примерно через минуту, после этого стартуют `worker` и `nginx`.

### 6.2. Проверка

```bash
curl -k https://localhost:${HTTPS_PORT:-443}/health/
# {"status": "ok", "database": true, "storage": true}

curl -sI http://localhost:${HTTP_PORT:-80}/ | head -3
# HTTP/1.1 301 … Location: https://…
```

`database: false` — приложение не видит базу; `storage: false` — нельзя записать в том `media`. В обоих случаях код ответа 503, подробности — в `docker compose logs web`.

Затем откройте `https://nir.example.org` в браузере и войдите под первым администратором. Проверьте `/admin/` и раздел «Отчёты».

### 6.3. Первый администратор

Если `DJANGO_SUPERUSER_*` не заданы:

```bash
docker compose exec web python manage.py createsuperuser
```

### 6.4. Начальная настройка в интерфейсе

1. «Администрирование → Пользователи, роли» — кафедры, пользователи, роли ([руководство администратора, раздел 2](admin-guide.md#2-пользователи-и-роли)).
2. «Импорт → Шаблон формы» — загрузить пустую форму `prepod_vnok_info-v2.0-draft04.pdf`.
3. Если нужен API — выдать токены.
4. Включить [резервное копирование](#8-резервное-копирование).

## 7. Проверка после развёртывания

| Что | Как | Ожидается |
| --- | --- | --- |
| Состояние сервисов | `docker compose ps` | 4 сервиса `Up`, `db` и `web` — `healthy` |
| Здоровье | `curl -k https://<сервер>/health/` | `"status": "ok"` |
| HTTP → HTTPS | `curl -sI http://<сервер>/` | `301` на `https://` |
| Вход | браузер | Вход проходит, нет ошибки CSRF |
| Статика | страница входа | Оформление Bootstrap на месте |
| Импорт | загрузить пример анкеты из `tests/fixtures/examples/` | Предпросмотр открывается |
| Фоновый импорт | пакет больше `IMPORT_SYNC_LIMIT` файлов | Пакет в состоянии «В очереди», затем обработан; в `docker compose logs worker` — «Обработано загрузок: N» |
| PDF-отчёт | выгрузка любого отчёта в PDF | Кириллица отображается |
| Резервная копия | `scripts/backup.sh /backup/stocktaking` | Два файла: `db-…dump`, `media-…tar.gz` |
| Восстановление | на тестовом сервере — `scripts/restore.sh` | Данные совпадают (требование приёмки, ТЗ 11.2) |
| Почта | `docker compose exec web python manage.py notify_pending` | Письмо ответственному, если есть ожидающие загрузки |

## 8. Резервное копирование

```bash
scripts/backup.sh /backup/stocktaking
```

Скрипт делает дамп базы (`pg_dump -Fc`) и архив тома `media`, с меткой времени в имени. Приложение при этом не останавливается.

Ежедневно в 02:00 (cron пользователя, состоящего в группе `docker`, или root):

```cron
0 2 * * * cd /opt/stocktaking && scripts/backup.sh /backup/stocktaking >> /var/log/stocktaking-backup.log 2>&1
```

Старые копии скрипт не удаляет. Пример очистки копий старше 30 дней — ещё одна строка cron:

```cron
30 3 * * * find /backup/stocktaking -name '*-20*' -mtime +30 -delete
```

Копии содержат персональные данные студентов: храните их вне сервера, с ограниченным доступом. Восстановление и проверка — [руководство администратора, раздел 4](admin-guide.md#4-резервное-копирование-и-восстановление).

Для переноса данных в другую установку или перед переработкой системы есть ещё выгрузка всей базы в JSON (`export_json`, «Администрирование → Выгрузка в JSON»). Она не заменяет `backup.sh`, подробности — [руководство администратора, раздел 8](admin-guide.md#8-выгрузка-в-json-и-восстановление).

## 9. Обновление

```bash
cd /opt/stocktaking
scripts/backup.sh /backup/stocktaking     # обязательно перед обновлением
git pull                                  # или распаковать новую версию поверх, сохранив .env
docker compose up -d --build              # пересборка и перезапуск; миграции применяет web
docker compose ps && curl -k https://localhost:${HTTPS_PORT:-443}/health/
```

Во время перезапуска сайт недоступен 1–2 минуты. Сравните `.env.example` с вашим `.env`: в новой версии могут появиться переменные.

Откат: вернуть предыдущую версию кода (`git checkout <тег или коммит>`), `docker compose up -d --build` и, если новая версия меняла схему базы, восстановить резервную копию, сделанную перед обновлением. Ручной откат миграций — `docker compose exec web python manage.py migrate <приложение> <миграция>` до остановки новой версии.

Неиспользуемые старые образы занимают место: `docker image prune`.

## 10. Установка без интернета

На машине с интернетом и той же архитектурой:

```bash
cd stocktaking
docker compose build
docker compose pull db
docker save -o stocktaking-images.tar stocktaking-app:latest stocktaking-nginx postgres:17
```

Перенести на сервер `stocktaking-images.tar` и каталог проекта, затем:

```bash
docker load -i stocktaking-images.tar
docker compose up -d --no-build
```

Имя образа nginx посмотрите в `docker images` после сборки (обычно `stocktaking-nginx`).

## 11. Смена паролей и ключей

| Что | Как |
| --- | --- |
| Пароль пользователя | Интерфейс или `docker compose exec web python manage.py changepassword <имя>` |
| Пароль базы | `docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`, в консоли `\password stocktaking` (имя из `POSTGRES_USER`), затем тот же пароль в `POSTGRES_PASSWORD` в `.env` и `docker compose up -d` |
| `DJANGO_SECRET_KEY` | Новое значение в `.env`, `docker compose up -d`. Все пользователи выйдут из системы |
| Сертификат | [Раздел 5](#5-tls-сертификат) |

После правки `.env` нужен `docker compose up -d` — Compose пересоздаст контейнеры с новыми переменными. `docker compose restart` переменные не перечитывает.

## 12. За внешним прокси

Если перед сервером уже есть балансировщик или общий nginx, который завершает HTTPS:

- задайте свободные порты (`HTTP_PORT=8081`, `HTTPS_PORT=8443`) и проксируйте на `https://127.0.0.1:8443`;
- чтобы эти порты не были видны снаружи, привяжите их к локальному адресу в `compose.yaml`: `"127.0.0.1:${HTTPS_PORT:-443}:443"` (и так же для 80). Переменную `HTTPS_PORT` IP-адресом не дополняйте — nginx подставляет её в адрес перенаправления.

Внешний прокси должен передавать заголовок `Host` и пропускать тело запроса до `IMPORT_MAX_BATCH_MB` (у nginx — `client_max_body_size 210m`), с тайм-аутом не меньше 300 с. `DJANGO_ALLOWED_HOSTS` и `DJANGO_CSRF_TRUSTED_ORIGINS` указывают внешнее имя.

## 13. Эксплуатация

| Задача | Команда |
| --- | --- |
| Состояние | `docker compose ps` |
| Журналы | `docker compose logs -f --tail=200 web worker nginx` |
| Перезапуск | `docker compose restart web worker` |
| Остановка / запуск | `docker compose stop` / `docker compose up -d` |
| Консоль Django | `docker compose exec web python manage.py shell` |
| Консоль базы | `docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'` |
| Место на дисках | `docker system df -v` |
| Удалить исходные PDF старше N дней | `docker compose exec web python manage.py purge_pdfs --older-than-days 1095 --dry-run` (без `--dry-run` — удалить) |

Журналы контейнеров хранит Docker. Чтобы они не заняли весь диск, ограничьте их размер в `/etc/docker/daemon.json` и перезапустите Docker:

```json
{ "log-driver": "json-file", "log-opts": { "max-size": "50m", "max-file": "5" } }
```

Для внешнего мониторинга опрашивайте `https://<сервер>/health/` или `http://<сервер>/health/` (на HTTP-порту он отвечает без перенаправления; имя сервера должно быть в `DJANGO_ALLOWED_HOSTS`): `200` — всё в порядке, `503` — нет базы или хранилища.

**Не выполняйте** `docker compose down -v`: ключ `-v` удаляет тома, то есть базу и все загруженные файлы. Обычный `docker compose down` данные сохраняет.

## 14. Типичные проблемы

| Признак | Причина и решение |
| --- | --- |
| `web` перезапускается, в журнале `ImproperlyConfigured: Задайте DJANGO_SECRET_KEY` | Не задан `DJANGO_SECRET_KEY` в `.env` |
| В журнале `web` — «База данных недоступна» | `db` не поднялась за 2 минуты: `docker compose logs db`. Частая причина — нет места на диске |
| `password authentication failed for user` | `POSTGRES_PASSWORD` в `.env` изменили после создания тома. Вернуть старый пароль или сменить его в базе ([раздел 11](#11-смена-паролей-и-ключей)) |
| `Bad Request (400)` | Имени, по которому открыт сайт, нет в `DJANGO_ALLOWED_HOSTS` |
| `Forbidden (403) CSRF verification failed` при входе | `DJANGO_CSRF_TRUSTED_ORIGINS` не совпадает с адресом в браузере (схема, имя, порт) |
| `Bind for 0.0.0.0:80 failed: port is already allocated` | Порт занят другим сервисом: `sudo ss -ltnp 'sport = :80'`. Освободить или сменить `HTTP_PORT`/`HTTPS_PORT` |
| `413 Request Entity Too Large` при импорте | Пакет больше `client_max_body_size` nginx (210 МБ) или внешнего прокси |
| `504 Gateway Time-out` при большом пакете | Уменьшить `IMPORT_SYNC_LIMIT`, чтобы большие пакеты уходили в фон |
| Пакет надолго «В очереди» | Не работает `worker`: `docker compose ps worker`, `docker compose logs worker` |
| `/health/` — `storage: false` | Нет места или прав на том `media`: `docker system df`, `docker compose exec web ls -ld /data/media` (владелец — пользователь `app`, uid 1000) |
| Нет оформления страниц | Статика не собралась: `docker compose logs web`, затем `docker compose up -d --force-recreate web` |
| Письма не приходят | `EMAIL_HOST` пуст или SMTP отклоняет — ошибки в `docker compose logs worker` |

## 15. Среда разработки

Не для рабочего сервера.

Без Docker (SQLite):

```bash
uv venv .venv --python 3.12 && uv pip install -p .venv/bin/python -r requirements-dev.txt
DJANGO_DEBUG=1 .venv/bin/python manage.py migrate
DJANGO_DEBUG=1 .venv/bin/python manage.py createsuperuser
DJANGO_DEBUG=1 .venv/bin/python manage.py runserver      # http://127.0.0.1:8000
```

В Docker с PostgreSQL, исходники монтируются с хоста, без nginx:

```bash
docker compose -f compose.yaml -f compose.dev.yaml up    # http://localhost:${DEV_PORT:-8000}
```
