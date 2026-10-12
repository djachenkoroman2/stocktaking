"""Состав и формат выгрузки базы в JSON (описание — doc/json-format.md).

Схема выгрузки строится по моделям Django. Сохранённое описание схемы каждой версии формата лежит в
formats/v<N>.json; тест сравнивает его с текущими моделями. Изменили модель — поднимите FORMAT_VERSION,
сохраните новое описание и добавьте преобразование в upgrades.py.
"""
import datetime
import decimal
import json
from pathlib import Path
import uuid

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.dateparse import parse_datetime

FORMAT = 'stocktaking-snapshot'
FORMAT_VERSION = 1
FORMATS_DIR = Path(__file__).parent / 'formats'

# Таблицы в порядке загрузки: сначала те, на которые ссылаются.
TABLES = [
    'auth.user',
    'authtoken.token',
    'registry.department',
    'registry.studygroup',
    'registry.teacher',
    'registry.student',
    'registry.researchwork',
    'registry.achievement',
    'accounts.roleassignment',
    'accounts.auditevent',
    'imports.formtemplate',
    'imports.importbatch',
    'imports.importeddocument',
    'imports.issuedcopy',
    'registry.historicalteacher',
    'registry.historicalstudent',
    'registry.historicalresearchwork',
    'registry.historicalachievement',
]

# Модели, которые не выгружаются, и почему. Тест проверяет, что каждая модель есть в одном из списков.
EXCLUDED = {
    'auth.group': 'не используются: права задаются ролями (accounts.roleassignment)',
    'auth.permission': 'служебная таблица, создаётся командой migrate',
    'contenttypes.contenttype': 'служебная таблица, создаётся командой migrate',
    'admin.logentry': 'журнал админ-панели Django; значимые действия записываются в журнал аудита',
    'sessions.session': 'сеансы входа',
    'accounts.loginfailure': 'временные данные блокировки входа',
    'authtoken.tokenproxy': 'прокси-модель, данные — в authtoken.token',
    'snapshots.snapshotexport': 'журнал самих выгрузок; архивы на сервере не переносятся',
}

# Человекочитаемый ключ записи (поле «_key»): чтобы выгрузку можно было понять без базы.
LABELS = {
    'auth.user': lambda o: o.username,
    'registry.department': lambda o: o.name,
    'registry.studygroup': lambda o: o.code,
    'registry.teacher': lambda o: f'{o.full_name} / {o.department.name}',
    'registry.student': lambda o: f'{o.full_name} / {o.group.code}',
    'registry.researchwork': lambda o: o.questionnaire_id or f'{o.student.full_name} — {o.teacher.full_name}',
    'imports.formtemplate': lambda o: o.original_name,
    'imports.issuedcopy': lambda o: o.questionnaire_id,
}
SELECT_RELATED = {
    'registry.teacher': ['department'],
    'registry.student': ['group'],
    'registry.researchwork': ['student', 'teacher'],
}


def model(table):
    return apps.get_model(table)


def table_file(table):
    return f'data/{table}.json'


def fields(table):
    """Поля таблицы в выгрузке: все хранимые поля модели, в порядке объявления."""
    return list(model(table)._meta.concrete_fields)


def kind(field):
    if isinstance(field, models.ForeignKey):
        return 'ref'
    if isinstance(field, models.FileField):
        return 'file'
    if isinstance(field, models.JSONField):
        return 'json'
    if isinstance(field, models.DateTimeField):
        return 'datetime'
    if isinstance(field, models.DateField):
        return 'date'
    if isinstance(field, models.BooleanField):
        return 'boolean'
    if isinstance(field, (models.IntegerField, models.AutoField)):
        return 'integer'
    if isinstance(field, models.DecimalField):
        return 'decimal'
    if isinstance(field, models.FloatField):
        return 'number'
    if isinstance(field, (models.CharField, models.TextField, models.GenericIPAddressField, models.UUIDField)):
        return 'string'
    raise TypeError(f'Тип поля {field.model._meta.label}.{field.name} не поддерживается выгрузкой JSON.')


def describe_field(field):
    item = {'name': field.name, 'type': kind(field), 'null': field.null, 'title': str(field.verbose_name)}
    if field.primary_key:
        item['primary_key'] = True
    if field.unique and not field.primary_key:
        item['unique'] = True
    if isinstance(field, models.CharField) and field.max_length:
        item['max_length'] = field.max_length
    if field.choices:
        item['choices'] = {str(value): str(label) for value, label in field.flatchoices}
    if item['type'] == 'ref':
        item['ref'] = field.related_model._meta.label_lower
        if not field.db_constraint:
            item['weak'] = True  # ссылка без ограничения в базе: может указывать на удалённую запись
    return item


def describe():
    """Описание схемы текущей версии: таблицы, поля, типы, ссылки, перечни значений."""
    return {table: {'title': str(model(table)._meta.verbose_name_plural),
                    'fields': [describe_field(f) for f in fields(table)]} for table in TABLES}


def structure(schema):
    """Схема без названий: то, что влияет на совместимость данных."""
    return {table: [{k: v for k, v in f.items() if k != 'title'} for f in spec['fields']]
            for table, spec in schema.items()}


def saved_schema(version):
    path = FORMATS_DIR / f'v{version}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


# Значения полей

def to_json(field, value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.astimezone(datetime.timezone.utc).isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, (decimal.Decimal, uuid.UUID)):
        return str(value)
    return value


def from_json(field, value):
    """Значение из выгрузки → значение для записи в базу. Ошибка формата — ValidationError."""
    field_kind = kind(field)
    if value is None:
        # Файла нет (не загружался или удалён purge_pdfs): в базе это пустая строка, а не NULL.
        return '' if field_kind == 'file' and not field.null else None
    if field_kind == 'ref':
        return field.target_field.to_python(value)
    if field_kind == 'file':
        if not isinstance(value, dict) or not isinstance(value.get('path'), str):
            raise ValidationError('ожидается объект файла с полем path')
        return value['path']
    if field_kind == 'json':
        return value
    if field_kind == 'datetime':
        parsed = parse_datetime(value) if isinstance(value, str) else None
        if parsed is None or parsed.tzinfo is None:
            raise ValidationError('ожидается дата и время ISO 8601 с часовым поясом')
        return parsed
    if field_kind == 'boolean' and not isinstance(value, bool):
        raise ValidationError('ожидается true или false')
    if field_kind == 'integer' and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValidationError('ожидается целое число')
    if field_kind == 'string' and not isinstance(value, str):
        raise ValidationError('ожидается строка')
    return field.to_python(value)
