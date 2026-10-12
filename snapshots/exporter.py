"""Выгрузка базы в ZIP-архив с JSON (doc/json-format.md).

Архив: manifest.json (заголовок), data/<таблица>.json (по одной записи в строке), media/ (файлы, если
выгрузка с файлами). Таблицы читаются частями и пишутся в архив потоком: база целиком в память не
загружается.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from config.version import VERSION

from . import schema

CHUNK = 2000


@dataclass
class ExportResult:
    path: Path
    tables: dict = field(default_factory=dict)  # таблица → число записей
    files: int = 0  # файлов, на которые ссылаются записи
    files_missing: int = 0  # из них нет на диске
    media_files: int = 0  # файлов в архиве
    media_bytes: int = 0
    warnings: list = field(default_factory=list)

    @property
    def rows(self):
        return sum(self.tables.values())


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(', ', ': '))


def hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def media_path(name):
    """Путь файла внутри MEDIA_ROOT или None, если имя выходит за его пределы."""
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / name).resolve()
    return path if path.is_relative_to(root) and path != root else None


def checksum(tables):
    """Контрольная сумма данных: SHA-256 от строк «файл:sha256» всех таблиц по порядку."""
    lines = ''.join(f'{t["file"]}:{t["sha256"]}\n' for t in tables)
    return hashlib.sha256(lines.encode()).hexdigest()


def git_commit():
    commit = os.environ.get('APP_COMMIT')
    if commit:
        return commit
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=settings.BASE_DIR, capture_output=True,
                                text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def applied_migrations():
    """Последняя применённая миграция каждого приложения, чьи таблицы выгружаются."""
    app_labels = {table.split('.')[0] for table in schema.TABLES}
    last = {}
    for app_label, name in MigrationRecorder(connection).applied_migrations():
        if app_label in app_labels and name > last.get(app_label, ''):
            last[app_label] = name
    return dict(sorted(last.items()))


def count_rows():
    return sum(schema.model(table)._base_manager.count() for table in schema.TABLES)


class _Files:
    """Файлы, на которые ссылаются записи: путь, размер, SHA-256 (один раз на файл)."""

    def __init__(self):
        self.info = {}

    def describe(self, name):
        if name not in self.info:
            path = media_path(name)
            try:
                sha256, size = hash_file(path) if path else (None, None)
            except OSError:
                sha256, size = None, None
            self.info[name] = {'path': name, 'size': size, 'sha256': sha256}
        return self.info[name]


def _record(table, obj, table_fields, label, files):
    record = {}
    for index, model_field in enumerate(table_fields):
        if schema.kind(model_field) == 'file':
            name = getattr(obj, model_field.attname)
            value = files.describe(str(name)) if name else None
        else:
            value = schema.to_json(model_field, getattr(obj, model_field.attname))
        record[model_field.name] = value
        if index == 0 and label:
            record['_key'] = label(obj)
    return record


def _write_table(archive, table, files):
    model = schema.model(table)
    table_fields = schema.fields(table)
    label = schema.LABELS.get(table)
    queryset = model._base_manager.order_by('pk').select_related(*schema.SELECT_RELATED.get(table, []))
    digest = hashlib.sha256()
    count = 0
    with archive.open(schema.table_file(table), 'w', force_zip64=True) as out:
        def write(text):
            data = text.encode('utf-8')
            out.write(data)
            digest.update(data)

        write('[\n')
        for obj in queryset.iterator(chunk_size=CHUNK):
            write((',\n' if count else '') + dumps(_record(table, obj, table_fields, label, files)))
            count += 1
        write('\n]\n' if count else ']\n')
    return {'name': table, 'file': schema.table_file(table), 'count': count, 'sha256': digest.hexdigest()}


def _warnings():
    from django.contrib.auth.models import User
    warnings = []
    with_groups = User.objects.filter(groups__isnull=False).distinct().count()
    with_perms = User.objects.filter(user_permissions__isnull=False).distinct().count()
    if with_groups or with_perms:
        warnings.append(f'Группы и отдельные права Django не выгружаются (есть у пользователей: '
                        f'{max(with_groups, with_perms)}). Права системы задаются ролями и выгружаются.')
    return warnings


def export(path, include_media=False, username=''):
    """Выгрузить базу в архив path. Возвращает ExportResult."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + '.part')
    result = ExportResult(path=path)
    files = _Files()
    try:
        with zipfile.ZipFile(partial, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            outermost = not connection.in_atomic_block
            with transaction.atomic():
                if connection.vendor == 'postgresql' and outermost:
                    # Один согласованный снимок базы на всю выгрузку. Внутри чужой транзакции уровень
                    # изоляции задать нельзя: согласованность тогда обеспечивает она.
                    with connection.cursor() as cursor:
                        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                tables = [_write_table(archive, table, files) for table in schema.TABLES]
                migrations = applied_migrations()
                result.warnings = _warnings()
            for item in files.info.values():
                result.files += 1
                if item['sha256'] is None:
                    result.files_missing += 1
                elif include_media:
                    archive.write(media_path(item['path']), f'media/{item["path"]}', compress_type=zipfile.ZIP_STORED)
                    result.media_files += 1
                    result.media_bytes += item['size']
            if result.files_missing:
                result.warnings.append(f'Файлов нет на диске: {result.files_missing}. В записях у них size и '
                                       'sha256 равны null.')
            result.tables = {t['name']: t['count'] for t in tables}
            manifest = {
                'format': schema.FORMAT,
                'format_version': schema.FORMAT_VERSION,
                'app_version': VERSION,
                'git_commit': git_commit(),
                'created_at': timezone.now().astimezone(timezone.get_fixed_timezone(0)).isoformat(),
                'created_by': username,
                'database': connection.vendor,
                'migrations': migrations,
                'tables': tables,
                'checksum': checksum(tables),
                'media': {'included': include_media, 'files': result.media_files, 'bytes': result.media_bytes,
                          'referenced': result.files, 'missing': result.files_missing},
                'warnings': result.warnings,
                'schema': schema.describe(),
            }
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        partial.replace(path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return result
