"""Восстановление базы из выгрузки JSON (doc/json-format.md, doc/admin-guide.md).

Порядок: проверка архива и данных без изменения базы → загрузка всех таблиц в одной транзакции →
сброс последовательностей ключей → файлы → одно событие аудита. Записи вставляются «как есть» (raw):
без save(), сигналов и auto_now, поэтому история изменений и даты переносятся без искажений.
"""
from collections import defaultdict
from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management.color import no_style
from django.db import DEFAULT_DB_ALIAS, connection, connections, models, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.functions import Lower

from accounts.models import AuditEvent

from . import schema
from .exporter import applied_migrations, checksum, hash_file, media_path
from . import upgrades
from .upgrades import upgrade

ERROR_LIMIT = 100


class RestoreError(Exception):
    """Архив нельзя прочитать как выгрузку: дальнейшая проверка бессмысленна."""


class Problems:
    def __init__(self):
        self.items = []
        self.total = 0

    def add(self, message):
        self.total += 1
        if len(self.items) < ERROR_LIMIT:
            self.items.append(message)

    def __bool__(self):
        return self.total > 0


@dataclass
class Report:
    archive: str
    dry_run: bool
    manifest: dict = field(default_factory=dict)
    errors: Problems = field(default_factory=Problems)
    warnings: list = field(default_factory=list)
    tables: list = field(default_factory=list)  # [таблица, в заголовке, проверено, загружено]
    files_restored: int = 0
    files_present: int = 0  # уже были в MEDIA_ROOT с той же SHA-256
    files_missing: list = field(default_factory=list)
    files_mismatch: list = field(default_factory=list)
    loaded: bool = False

    @property
    def ok(self):
        return not self.errors

    def lines(self):
        manifest = self.manifest
        out = [f'Архив: {self.archive}']
        if manifest:
            out.append(f'Выгрузка: формат {manifest.get("format_version")}, система {manifest.get("app_version")}, '
                       f'{manifest.get("created_at")}, выгрузил {manifest.get("created_by") or "—"}, '
                       f'файлы {"включены" if manifest.get("media", {}).get("included") else "не включены"}')
        if self.tables:
            out.append('Таблицы (в заголовке / проверено / загружено):')
            for table, expected, checked, loaded in self.tables:
                out.append(f'  {table}: {"—" if expected is None else expected} / {checked} / '
                           f'{"—" if loaded is None else loaded}')
        referenced = self.files_restored + self.files_present + len(self.files_missing)
        if referenced:
            verb = 'будет восстановлено' if self.dry_run or not self.loaded else 'восстановлено'
            out.append(f'Файлы: {verb} {self.files_restored}, уже на месте {self.files_present}, '
                       f'отсутствуют {len(self.files_missing)}, SHA-256 не совпала {len(self.files_mismatch)}')
            out += [f'  нет файла: {name}' for name in self.files_missing[:ERROR_LIMIT]]
            out += [f'  SHA-256 не совпала: {name}' for name in self.files_mismatch[:ERROR_LIMIT]]
        out += [f'Предупреждение: {w}' for w in self.warnings]
        out += [f'Ошибка: {e}' for e in self.errors.items]
        if self.errors.total > len(self.errors.items):
            out.append(f'… и ещё ошибок: {self.errors.total - len(self.errors.items)}')
        if self.errors:
            out.append(f'Итог: ошибок {self.errors.total}, база не изменена.')
        elif self.dry_run:
            out.append('Итог: проверка пройдена, база не изменена (режим проверки).')
        else:
            out.append('Итог: восстановление выполнено.')
        return out


class Snapshot:
    """Архив выгрузки: заголовок, записи таблиц, файлы."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.zip = zipfile.ZipFile(self.path)
        except (OSError, zipfile.BadZipFile) as error:
            raise RestoreError(f'Не удалось открыть архив: {error}') from error
        self.names = set(self.zip.namelist())
        if 'manifest.json' not in self.names:
            raise RestoreError('В архиве нет manifest.json: это не выгрузка «Учёт НИР».')
        try:
            self.manifest = json.loads(self.zip.read('manifest.json').decode('utf-8'))
        except (ValueError, zipfile.BadZipFile) as error:
            raise RestoreError(f'manifest.json повреждён: {error}') from error
        if not isinstance(self.manifest, dict) or self.manifest.get('format') != schema.FORMAT:
            raise RestoreError('manifest.json: неизвестный формат, это не выгрузка «Учёт НИР».')

    def close(self):
        self.zip.close()

    def file_sha256(self, name):
        digest = hashlib.sha256()
        with self.zip.open(name) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def records(self, name):
        """Записи таблицы потоком. Формат файла — по одной записи в строке (так пишет выгрузка);
        файл в другой разметке JSON читается целиком."""
        with self.zip.open(name) as raw:
            text = io.TextIOWrapper(raw, encoding='utf-8')
            if text.readline().strip() != '[':
                yield from self._whole(name)
                return
            for number, line in enumerate(text, start=2):
                line = line.strip()
                if line in ('', ']'):
                    continue
                try:
                    yield json.loads(line[:-1] if line.endswith(',') else line)
                except ValueError as error:
                    raise RestoreError(f'{name}, строка {number}: неверный JSON ({error.args[0]}).') from error

    def _whole(self, name):
        try:
            data = json.loads(self.zip.read(name).decode('utf-8'))
        except ValueError as error:
            raise RestoreError(f'{name}: неверный JSON ({error}).') from error
        if not isinstance(data, list):
            raise RestoreError(f'{name}: ожидается массив записей.')
        yield from data


def _unique_sets(model):
    """Наборы полей, значения которых уникальны: unique=True и UniqueConstraint (в т. ч. по Lower)."""
    result = []
    for model_field in model._meta.concrete_fields:
        if model_field.unique and not model_field.primary_key:
            result.append(((model_field.name,), False))
    for constraint in model._meta.constraints:
        if not isinstance(constraint, models.UniqueConstraint) or constraint.condition is not None:
            continue
        if constraint.fields:
            result.append((tuple(constraint.fields), False))
        elif all(isinstance(e, Lower) and isinstance(e.source_expressions[0], models.F)
                 for e in constraint.expressions):
            result.append((tuple(e.source_expressions[0].name for e in constraint.expressions), True))
    return result


class Restore:
    def __init__(self, path, dry_run=False, drop_existing_users=False, username=''):
        self.path = Path(path)
        self.dry_run = dry_run
        self.drop_existing_users = drop_existing_users
        self.username = username
        self.report = Report(archive=self.path.name, dry_run=dry_run)
        self.plan = []  # [(файл, таблица выгрузки, таблица назначения)]
        self.files = {}  # путь → сведения о файле из записи
        self.version = None

    def run(self):
        report = self.report
        try:
            snapshot = Snapshot(self.path)
        except RestoreError as error:
            report.errors.add(str(error))
            return report
        try:
            report.manifest = snapshot.manifest
            self._check_manifest(snapshot)
            if not report.errors:
                self._check_database()
                self._check_records(snapshot)
                self._check_files(snapshot)
            if not report.errors and not self.dry_run:
                self._load(snapshot)
        except RestoreError as error:
            report.errors.add(str(error))
        finally:
            snapshot.close()
        return report

    # Проверка

    def _check_manifest(self, snapshot):
        manifest, errors = snapshot.manifest, self.report.errors
        version = manifest.get('format_version')
        if not isinstance(version, int) or version < 1:
            errors.add('manifest.json: нет версии формата.')
            return
        if version > schema.FORMAT_VERSION:
            errors.add(f'Выгрузка сделана более новой версией системы (формат {version}, эта версия читает '
                       f'формат до {schema.FORMAT_VERSION}). Обновите систему.')
            return
        missing_steps = [step for step in range(version, schema.FORMAT_VERSION) if step not in upgrades.UPGRADES]
        if missing_steps:
            errors.add(f'Нет преобразования формата {missing_steps[0]} → {missing_steps[0] + 1}: выгрузку версии '
                       f'{version} эта версия системы прочитать не может.')
            return
        self.version = version
        tables = manifest.get('tables')
        if not isinstance(tables, list) or not all(isinstance(t, dict) for t in tables):
            errors.add('manifest.json: нет списка таблиц.')
            return
        for name in sorted(snapshot.names):
            parts = PurePosixPath(name).parts
            if name.startswith('/') or '..' in parts or '\\' in name:
                errors.add(f'Недопустимое имя в архиве: {name}.')
        if errors:
            return
        if checksum(tables) != manifest.get('checksum'):
            errors.add('Контрольная сумма данных в manifest.json не совпадает со списком таблиц.')
        for item in tables:
            name = item.get('file')
            if name not in snapshot.names:
                errors.add(f'В архиве нет файла таблицы {name}.')
            elif snapshot.file_sha256(name) != item.get('sha256'):
                errors.add(f'{name}: SHA-256 не совпадает с manifest.json — файл повреждён или изменён.')
        if errors:
            return
        for item in tables:
            target, _ = upgrade(version, schema.FORMAT_VERSION, item['name'], iter(()))
            if target is None:
                continue
            if target not in schema.TABLES:
                errors.add(f'Таблица {target} неизвестна этой версии системы.')
                continue
            self.plan.append((item['file'], item['name'], target, item.get('count')))
        present = {target for _, _, target, _ in self.plan}
        for table in schema.TABLES:
            if table not in present:
                self.report.warnings.append(f'Таблицы {table} нет в выгрузке: она останется пустой.')
        if version == schema.FORMAT_VERSION and manifest.get('migrations') != applied_migrations():
            self.report.warnings.append(
                f'Миграции выгрузки {manifest.get("migrations")} отличаются от миграций этой базы '
                f'{applied_migrations()}. Формат совпадает, поля проверены по текущей схеме.')
        for warning in manifest.get('warnings') or []:
            self.report.warnings.append(f'При выгрузке: {warning}')

    def _check_database(self):
        errors = self.report.errors
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            errors.add('В базе применены не все миграции: выполните python manage.py migrate.')
            return
        busy = [t for t in schema.TABLES if t != 'auth.user' and schema.model(t)._base_manager.exists()]
        if busy:
            errors.add('База не пустая, восстановление возможно только в пустую базу. Есть данные в таблицах: '
                       + ', '.join(busy) + '. См. doc/admin-guide.md, «Восстановление из JSON».')
        users = User.objects.count()
        if users and not self.drop_existing_users:
            errors.add(f'В базе уже есть пользователи ({users}), например созданный из DJANGO_SUPERUSER_*. '
                       'Запустите восстановление с --drop-existing-users: они будут удалены и заменены '
                       'пользователями из выгрузки.')
        elif users:
            self.report.warnings.append(f'Существующие пользователи ({users}) будут удалены.')

    def _check_records(self, snapshot):
        errors = self.report.errors
        pks = defaultdict(set)
        refs = []  # (таблица назначения ссылки, значение, откуда)
        blanks = defaultdict(int)
        bad_choices = defaultdict(int)
        unique_seen = {}
        checked = defaultdict(int)
        for name, source, table, _ in self.plan:
            model = schema.model(table)
            table_fields = {f.name: f for f in schema.fields(table)}
            pk_name = model._meta.pk.name
            unique_sets = _unique_sets(model)
            for columns, _ in unique_sets:
                unique_seen.setdefault((table, columns), set())
            _, records = upgrade(self.version, schema.FORMAT_VERSION, source, snapshot.records(name))
            for number, record in enumerate(records, start=1):
                checked[table] += 1
                where = f'{table}, запись {number}'
                if not isinstance(record, dict):
                    errors.add(f'{where}: ожидается объект.')
                    continue
                keys = {k for k in record if not k.startswith('_')}
                if keys != set(table_fields):
                    missing, extra = set(table_fields) - keys, keys - set(table_fields)
                    errors.add(f'{where}: поля не совпадают со схемой'
                               + (f'; нет: {", ".join(sorted(missing))}' if missing else '')
                               + (f'; лишние: {", ".join(sorted(extra))}' if extra else '') + '.')
                    continue
                values = {}
                for field_name, model_field in table_fields.items():
                    try:
                        values[field_name] = schema.from_json(model_field, record[field_name])
                    except ValidationError as error:
                        errors.add(f'{where}, поле {field_name}: {"; ".join(error.messages)}.')
                        values[field_name] = None
                        continue
                    value = values[field_name]
                    if value is None:
                        if not model_field.null:
                            errors.add(f'{where}, поле {field_name}: обязательное поле пустое.')
                        continue
                    if isinstance(model_field, models.CharField) and model_field.max_length \
                            and len(value) > model_field.max_length:
                        errors.add(f'{where}, поле {field_name}: длиннее {model_field.max_length} символов.')
                    if value == '' and not model_field.blank:
                        blanks[(table, field_name)] += 1
                    if model_field.choices and value != '' and str(value) not in \
                            {str(v) for v, _ in model_field.flatchoices}:
                        bad_choices[(table, field_name, str(value))] += 1
                    kind = schema.kind(model_field)
                    if kind == 'ref' and model_field.db_constraint:
                        refs.append((model_field.related_model._meta.label_lower, value, f'{where}, поле {field_name}'))
                    elif kind == 'file' and record[field_name] is not None:
                        self._collect_file(record[field_name], where, field_name)
                pk = values.get(pk_name)
                if pk in pks[table]:
                    errors.add(f'{where}: повторяется ключ {pk_name}={pk}.')
                pks[table].add(pk)
                for columns, ci in unique_sets:
                    key = tuple(values.get(c) for c in columns)
                    if any(v is None for v in key):
                        continue
                    if ci:
                        key = tuple(str(v).lower() for v in key)
                    seen = unique_seen[(table, columns)]
                    if key in seen:
                        errors.add(f'{where}: значение {", ".join(columns)} = {", ".join(map(str, key))} '
                                   'повторяется, а должно быть уникальным.')
                    seen.add(key)
        for target, value, where in refs:
            if value not in pks.get(target, ()):
                errors.add(f'{where}: ссылка на несуществующую запись {target} с ключом {value}.')
        for (table, field_name), count in sorted(blanks.items()):
            self.report.warnings.append(f'{table}.{field_name}: пустое значение у {count} записей '
                                        '(поле обязательно в формах, база это допускает).')
        for (table, field_name, value), count in sorted(bad_choices.items()):
            self.report.warnings.append(f'{table}.{field_name}: значение «{value}» не из перечня ({count} записей).')
        expected = defaultdict(int)
        for _, _, table, count in self.plan:
            expected[table] += count if isinstance(count, int) else 0
        if self.version == schema.FORMAT_VERSION:
            for table in expected:
                if expected[table] != checked[table]:
                    errors.add(f'{table}: в manifest.json {expected[table]} записей, в файле {checked[table]}.')
        self.report.tables = [[t, expected[t] if self.version == schema.FORMAT_VERSION else None, checked[t], None]
                              for t in schema.TABLES if t in checked or t in expected]

    def _collect_file(self, info, where, field_name):
        name = info['path']
        if media_path(name) is None:
            self.report.errors.add(f'{where}, поле {field_name}: недопустимый путь файла {name}.')
            return
        self.files.setdefault(name, info)

    def _check_files(self, snapshot):
        report = self.report
        self.to_extract = []
        for name, info in sorted(self.files.items()):
            member = f'media/{name}'
            target = media_path(name)
            on_disk = None
            if target.exists():
                on_disk, _ = hash_file(target)
            if member in snapshot.names:
                actual = snapshot.file_sha256(member)
                if on_disk is not None:
                    if on_disk == actual:
                        report.files_present += 1
                    else:
                        report.errors.add(f'Файл {name} уже есть в MEDIA_ROOT с другим содержимым; '
                                          'перезаписывать его восстановление не будет.')
                    continue
                if info.get('sha256') and actual != info['sha256']:
                    report.files_mismatch.append(name)
                self.to_extract.append((member, target))
                report.files_restored += 1
            elif on_disk is not None:
                report.files_present += 1
                if info.get('sha256') and on_disk != info['sha256']:
                    report.files_mismatch.append(name)
            else:
                report.files_missing.append(name)
        if report.files_missing:
            report.warnings.append(f'Файлов нет ни в архиве, ни в MEDIA_ROOT: {len(report.files_missing)}. '
                                   'Записи восстанавливаются, скачать эти файлы будет нельзя.')

    # Загрузка

    def _load(self, snapshot):
        report = self.report
        written = []
        try:
            with transaction.atomic():
                if self.drop_existing_users:
                    User.objects.all().delete()
                for name, source, table, _ in self.plan:
                    _, records = upgrade(self.version, schema.FORMAT_VERSION, source, snapshot.records(name))
                    self._insert(table, records)
                loaded_models = [schema.model(t) for t in schema.TABLES]
                with connection.cursor() as cursor:
                    for sql in connection.ops.sequence_reset_sql(no_style(), loaded_models):
                        cursor.execute(sql)
                for row in report.tables:
                    row[3] = schema.model(row[0])._base_manager.count()
                    if row[3] != row[2]:
                        raise RestoreError(f'{row[0]}: загружено {row[3]} записей вместо {row[2]}.')
                for member, target in self.to_extract:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    partial = target.with_name(target.name + '.part')
                    with snapshot.zip.open(member) as source_file, open(partial, 'wb') as out:
                        shutil.copyfileobj(source_file, out, 1024 * 1024)
                    partial.replace(target)
                    written.append(target)
                manifest = report.manifest
                AuditEvent.objects.create(
                    username=self.username or 'manage.py', action='json_restore',
                    details={'file': self.path.name, 'format_version': self.version,
                             'source_created_at': manifest.get('created_at'),
                             'source_app_version': manifest.get('app_version'),
                             'rows': sum(row[3] for row in report.tables), 'files': len(written),
                             'files_missing': len(report.files_missing)})
        except BaseException:
            for target in written:
                target.unlink(missing_ok=True)
            raise
        report.loaded = True

    def _insert(self, table, records):
        model = schema.model(table)
        table_fields = schema.fields(table)
        manager = model._base_manager
        ops = connections[DEFAULT_DB_ALIAS].ops
        batch = []

        def flush():
            size = max(1, ops.bulk_batch_size(table_fields, batch) or len(batch))
            for start in range(0, len(batch), size):
                manager._insert(batch[start:start + size], fields=table_fields, raw=True, using=DEFAULT_DB_ALIAS)
            batch.clear()

        for record in records:
            values = {f.attname: schema.from_json(f, record[f.name]) for f in table_fields}
            batch.append(model(**values))
            if len(batch) >= 1000:
                flush()
        if batch:
            flush()
