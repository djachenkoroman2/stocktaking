"""Выгрузка базы в JSON и восстановление (ТЗ 11.7, doc/json-format.md)."""
import hashlib
import json
from pathlib import Path
import zipfile

from django.apps import apps
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import Client
import pytest
from rest_framework.authtoken.models import Token

from accounts.models import AuditEvent, Role
from imports.copies import issue_copies, register_template
from imports.models import DocState, ImportedDocument, IssuedCopy
from imports.processing import mark_returned
from registry.models import Department, ResearchWork, Student, Teacher
from snapshots import schema, upgrades
from snapshots.exporter import checksum, export
from snapshots.models import SnapshotExport
from snapshots.restorer import Restore
from snapshots.service import process_queue
from tests.conftest import BLANK_FORM, make_user, upload
from tests.test_import_examples import confirm_all

PASSWORD = 'pass-12345-long'


def build_data(user):
    """Данные из 20 примеров анкет: работы, возвраты, история, копии, удаление, объединение, роли, токен."""
    batch = upload(user)
    confirm_all(batch, user)
    for document in batch.documents.filter(state=DocState.TO_RETURN)[:3]:
        mark_returned(document, user)
    department = Department.objects.get()
    Department.objects.create(name='Кафедра физики', aliases=['Физика'])
    teacher = Teacher.objects.order_by('pk').first()
    teacher.user = make_user('teacher')
    teacher.save()
    make_user('observer', Role.OBSERVER, department)
    Token.objects.create(user=user)
    register_template('blank.pdf', BLANK_FORM.read_bytes(), user)
    issue_copies(teacher, [teacher.works.first().student], 2, user)
    ResearchWork.objects.order_by('pk').last().soft_delete()
    main, duplicate = Student.objects.order_by('pk')[:2]
    duplicate.merged_into = main
    duplicate.is_active = False
    duplicate.save()
    work = ResearchWork.objects.order_by('pk').first()
    work.status_comment = 'Комментарий: «кавычки», переводы\nстрок и эмодзи 🙂'
    work.save()
    AuditEvent.objects.create(user=user, username=user.username, action='test', details={'n': 1})
    purged = ImportedDocument.objects.filter(state=DocState.SAVED).order_by('pk').last()  # как после purge_pdfs
    purged.file.delete(save=False)
    purged.file_purged_at = purged.uploaded_at
    purged.save(update_fields=['file', 'file_purged_at'])


def read_tables(path):
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist() if name.startswith('data/')}


def manifest_of(path):
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read('manifest.json'))


def rewrite(src, dst, changes=None, manifest=None, repack=True):
    """Копия архива с изменёнными файлами. repack — пересчитать SHA-256 и контрольную сумму, как будто
    архив собран корректно (для проверки содержимого, а не целостности)."""
    changes = changes or {}
    with zipfile.ZipFile(src) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    for name, change in changes.items():
        files[name] = change(files[name]) if callable(change) else change
    data = json.loads(files['manifest.json'])
    if repack:
        for table in data['tables']:
            table['sha256'] = hashlib.sha256(files[table['file']]).hexdigest()
        data['checksum'] = checksum(data['tables'])
    if manifest:
        manifest(data)
    files['manifest.json'] = json.dumps(data, ensure_ascii=False).encode()
    with zipfile.ZipFile(dst, 'w') as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return dst


def edit_records(table, change):
    def apply(content):
        records = json.loads(content)
        for record in records:
            change(record)
        return ('[\n' + ',\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n]\n').encode()
    return {schema.table_file(table): apply}


def wipe(settings, tmp_path, name='restored'):
    """Пустая база после migrate и пустой MEDIA_ROOT — как новый сервер."""
    call_command('flush', interactive=False, verbosity=0)
    settings.MEDIA_ROOT = tmp_path / name


def without_restore_events(content):
    records = json.loads(content)
    return [r for r in records if r['action'] != 'json_restore']


def test_schema_matches_saved_format():
    """Изменили модели — поднимите FORMAT_VERSION, сохраните formats/vN.json и добавьте преобразование."""
    saved = schema.saved_schema(schema.FORMAT_VERSION)
    assert saved is not None
    assert schema.structure(schema.describe()) == schema.structure(saved)
    labels = {m._meta.label_lower for m in apps.get_models()}
    assert labels == set(schema.TABLES) | set(schema.EXCLUDED), 'Новая модель: добавьте её в TABLES или EXCLUDED'
    assert not set(schema.TABLES) & set(schema.EXCLUDED)


@pytest.mark.django_db(transaction=True)
def test_roundtrip_with_media(responsible, settings, tmp_path):
    build_data(responsible)
    counts = {t: schema.model(t)._base_manager.count() for t in schema.TABLES}
    assert counts['registry.historicalresearchwork'] > 0 and counts['imports.issuedcopy'] >= 2
    first = export(tmp_path / 'first.zip', include_media=True, username='test')
    assert first.tables == counts and first.files_missing == 0 and first.media_files == first.files > 20

    wipe(settings, tmp_path)
    report = Restore(first.path).run()
    assert report.ok, report.lines()
    assert report.files_restored == first.files and not report.files_missing and not report.files_mismatch
    assert {row[0]: row[3] for row in report.tables} == counts

    second = export(tmp_path / 'second.zip', include_media=True)
    a, b = read_tables(first.path), read_tables(second.path)
    audit = schema.table_file('accounts.auditevent')
    assert without_restore_events(b.pop(audit)) == json.loads(a.pop(audit))
    assert a == b  # всё остальное — байт в байт
    restore_event = AuditEvent.objects.get(action='json_restore')
    assert restore_event.details['file'] == 'first.zip'
    assert AuditEvent.objects.count() == counts['accounts.auditevent'] + 1

    # История не дополнилась записями от восстановления; последовательности ключей сброшены.
    assert ResearchWork.history.count() == counts['registry.historicalresearchwork']
    department = Department.objects.create(name='Новая кафедра')
    assert department.pk == max(Department.objects.exclude(pk=department.pk).values_list('pk', flat=True)) + 1
    last_history = Teacher.history.order_by('-history_id').first().history_id
    teacher = Teacher.objects.first()
    teacher.position = 'Доцент'
    teacher.save()
    assert teacher.history.first().history_id == last_history + 1

    # Вход и файлы работают.
    client = Client()
    assert client.login(username=responsible.username, password=PASSWORD)
    document = ImportedDocument.objects.filter(state=DocState.SAVED).first()
    response = client.get(f'/imports/documents/{document.pk}/download/')
    assert response.status_code == 200 and b''.join(response.streaming_content)[:4] == b'%PDF'
    assert client.get('/reports/').status_code == 200


@pytest.mark.django_db(transaction=True)
def test_restore_without_media(responsible, settings, tmp_path):
    build_data(responsible)
    result = export(tmp_path / 'plain.zip')
    assert result.media_files == 0 and manifest_of(result.path)['media']['included'] is False
    wipe(settings, tmp_path)
    report = Restore(result.path).run()
    assert report.ok, report.lines()
    assert len(report.files_missing) == result.files and report.files_restored == 0
    assert any('нет ни в архиве' in w for w in report.warnings)
    client = Client()
    client.login(username=responsible.username, password=PASSWORD)
    document = ImportedDocument.objects.filter(state=DocState.SAVED).first()
    assert client.get(f'/imports/documents/{document.pk}/download/').status_code == 404
    copy = IssuedCopy.objects.first()
    assert client.get(f'/imports/copies/{copy.pk}/download/').status_code == 404


@pytest.mark.django_db(transaction=True)
def test_dry_run_and_existing_users(responsible, settings, tmp_path):
    build_data(responsible)
    path = export(tmp_path / 'a.zip').path
    wipe(settings, tmp_path)
    User.objects.create_superuser('admin', '', PASSWORD)  # как из DJANGO_SUPERUSER_*

    report = Restore(path).run()
    assert not report.ok and any('--drop-existing-users' in e for e in report.errors.items)
    report = Restore(path, dry_run=True, drop_existing_users=True).run()
    assert report.ok, report.lines()
    assert ResearchWork.objects.count() == 0 and User.objects.count() == 1  # проверка ничего не меняет
    report = Restore(path, drop_existing_users=True).run()
    assert report.ok and not User.objects.filter(username='admin').exists()
    assert ResearchWork.objects.count() > 0


@pytest.mark.django_db
def test_refuses_non_empty_database(responsible, tmp_path):
    build_data(responsible)
    path = export(tmp_path / 'a.zip').path
    rows = ResearchWork.objects.count()
    report = Restore(path, drop_existing_users=True).run()
    assert not report.ok and any('База не пустая' in e for e in report.errors.items)
    assert ResearchWork.objects.count() == rows


@pytest.mark.django_db(transaction=True)
def test_rejects_damaged_archives(responsible, settings, tmp_path):
    build_data(responsible)
    path = export(tmp_path / 'a.zip').path
    wipe(settings, tmp_path)
    work_file = schema.table_file('registry.researchwork')

    def error_of(archive):
        report = Restore(archive).run()
        assert not report.ok and ResearchWork.objects.count() == 0
        return ' '.join(report.errors.items)

    not_zip = tmp_path / 'not.zip'
    not_zip.write_bytes(b'not a zip')
    assert 'Не удалось открыть архив' in error_of(not_zip)
    damaged = rewrite(path, tmp_path / 'damaged.zip', {work_file: lambda c: c.replace(b'"task"', b'"task" ', 1)},
                      repack=False)
    assert 'SHA-256 не совпадает' in error_of(damaged)
    bad_checksum = rewrite(path, tmp_path / 'checksum.zip', manifest=lambda m: m.update(checksum='0' * 64))
    assert 'Контрольная сумма' in error_of(bad_checksum)
    newer = rewrite(path, tmp_path / 'newer.zip', manifest=lambda m: m.update(format_version=schema.FORMAT_VERSION + 1))
    assert 'более новой версией' in error_of(newer)
    broken_ref = rewrite(path, tmp_path / 'ref.zip', edit_records('registry.researchwork',
                                                                  lambda r: r.update(teacher=99999)))
    assert 'ссылка на несуществующую запись registry.teacher с ключом 99999' in error_of(broken_ref)
    duplicate = rewrite(path, tmp_path / 'dup.zip', edit_records('registry.studygroup',
                                                                 lambda r: r.update(code='А-1')))
    assert 'должно быть уникальным' in error_of(duplicate)
    missing_field = rewrite(path, tmp_path / 'field.zip', edit_records('registry.department',
                                                                       lambda r: r.pop('short_name')))
    assert 'поля не совпадают со схемой; нет: short_name' in error_of(missing_field)
    bad_date = rewrite(path, tmp_path / 'date.zip', edit_records('registry.researchwork',
                                                                 lambda r: r.update(created_at='вчера')))
    assert 'поле created_at' in error_of(bad_date)
    unsafe = rewrite(path, tmp_path / 'unsafe.zip', {'media/../../evil.pdf': b'%PDF'})
    assert 'Недопустимое имя' in error_of(unsafe)


@pytest.mark.django_db(transaction=True)
def test_upgrade_from_older_format(responsible, settings, tmp_path, monkeypatch):
    """Механизм версий: выгрузка «старого» формата, где поле называлось иначе, проходит через преобразование."""
    build_data(responsible)
    Department.objects.filter(name='Кафедра физики').update(short_name='Физ')
    before = sorted(Department.objects.values_list('name', 'short_name'))
    path = export(tmp_path / 'a.zip').path
    wipe(settings, tmp_path)
    old = rewrite(path, tmp_path / 'old.zip',
                  edit_records('registry.department', lambda r: r.update(abbr=r.pop('short_name'))))
    monkeypatch.setattr(schema, 'FORMAT_VERSION', 2)

    report = Restore(old).run()
    assert not report.ok and 'Нет преобразования формата 1 → 2' in ' '.join(report.errors.items)

    def v1_to_v2(table, records):
        if table == 'registry.department':
            return table, ({**{k: v for k, v in r.items() if k != 'abbr'}, 'short_name': r['abbr']} for r in records)
        return table, records

    monkeypatch.setattr(upgrades, 'UPGRADES', {1: v1_to_v2})
    report = Restore(old).run()
    assert report.ok, report.lines()
    assert sorted(Department.objects.values_list('name', 'short_name')) == before


@pytest.mark.django_db
def test_export_page(client, responsible, settings):
    settings.EXPORT_SYNC_ROWS = 100000
    admin_role = make_user('admin_role', Role.ADMIN)
    client.force_login(admin_role)
    assert client.get('/export/').status_code == 403  # администратор по роли — не суперпользователь
    superuser = User.objects.create_superuser('root', '', PASSWORD)
    client.force_login(superuser)
    assert 'Выгрузка в JSON' in client.get('/').content.decode()

    assert client.post('/export/').status_code == 302
    job = SnapshotExport.objects.get()
    assert job.state == SnapshotExport.State.DONE and job.path.exists() and job.rows > 0
    assert job.path.is_relative_to(settings.EXPORT_ROOT) and not job.path.is_relative_to(settings.MEDIA_ROOT)
    response = client.get(f'/export/{job.pk}/download/')
    assert response.status_code == 200 and response['Content-Type'] == 'application/zip'
    assert {'json_export', 'json_export_download'} <= set(AuditEvent.objects.values_list('action', flat=True))

    client.post('/export/', {'include_media': '1'})  # с файлами — в фоне
    queued = SnapshotExport.objects.latest('pk')
    assert queued.state == SnapshotExport.State.QUEUED
    assert process_queue() == 1
    queued.refresh_from_db()
    assert queued.state == SnapshotExport.State.DONE and queued.include_media

    client.post(f'/export/{job.pk}/delete/')
    assert not job.path.exists() and not SnapshotExport.objects.filter(pk=job.pk).exists()
    client.force_login(responsible)
    assert client.get(f'/export/{queued.pk}/download/').status_code == 403


@pytest.mark.django_db(transaction=True)
def test_commands(responsible, settings, tmp_path, capsys):
    build_data(responsible)
    path = tmp_path / 'cmd.zip'
    call_command('export_json', str(path), '--with-media')
    assert manifest_of(path)['media']['included'] and AuditEvent.objects.filter(action='json_export').exists()
    with pytest.raises(CommandError):
        call_command('restore_json', str(path), '--dry-run')
    assert 'База не пустая' in capsys.readouterr().out
    wipe(settings, tmp_path)
    call_command('restore_json', str(path))
    assert 'восстановление выполнено' in capsys.readouterr().out
    assert Path(settings.MEDIA_ROOT).exists() and ResearchWork.objects.exists()
