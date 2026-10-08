# Копия модулей формы prepod_vnok_info (схема 2.0)

Файлы скопированы **без изменений** из проекта формы (вариант Б, ТЗ 7.3). Не редактируйте их здесь: изменения
вносятся в проекте формы, затем копия обновляется целиком.

| Файл | Источник | SHA-256 |
| --- | --- | --- |
| `extract_static.py` | `/home/roman/src/forms/forms/prepod_vnok_info/src/static/extract_static.py` | `42c59f3f3e559168c43f74a3b9c6e6a0f41cc0b86d75d634d53a75f795ba05f0` |
| `acroform.py` | `/home/roman/src/forms/forms/prepod_vnok_info/src/static/acroform.py` | `ac8b59386d9c9ba69ddc35781999f6223eda7a4b599163ac29a56e3736ccea2c` |
| `prepare_copy.py` | `/home/roman/src/forms/forms/prepod_vnok_info/src/static/prepare_copy.py` | `ebd15214b88da34c99f051349fbfc07660b9d5d2c7bdf4e049e38e1e6e8c782b` |

Дата копирования: 08.10.2026. Версии `pypdf` и `fonttools` в `requirements.txt` совпадают с
`src/requirements.txt` проекта формы.

## Как обновить

1. Скопировать три файла из проекта формы в этот каталог.
2. Записать новые SHA-256 в таблицу выше и в `VENDOR_SHA256` в `tests/test_parity.py`.
3. Если изменились примеры — скопировать `examples/*.pdf` в `tests/fixtures/examples/` и обновить `EXPECTED`
   в `tests/test_parity.py` по `examples/README.md`.
4. Запустить тесты: `.venv/bin/pytest`. Тест паритета покажет расхождения поведения.

Новая версия схемы данных (например, 3.0) — это **новый адаптер** `imports/adapters/prepod_vnok_info_v3/` и строка
в `ADAPTERS` (`imports/adapters/__init__.py`); этот каталог при этом не меняется. Загрузки в состоянии
«Версия не поддерживается» после этого можно обработать заново из журнала импорта.
