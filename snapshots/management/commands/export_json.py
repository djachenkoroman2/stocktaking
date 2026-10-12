"""Выгрузка всей базы в ZIP-архив с JSON (doc/json-format.md)."""
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand

from accounts.audit import log
from snapshots.exporter import export
from snapshots.service import archive_name, audit_details


class Command(BaseCommand):
    help = 'Выгружает базу в ZIP-архив с JSON. Архив содержит персональные данные и хеши паролей.'

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', help='Файл архива. По умолчанию — EXPORT_ROOT/stocktaking-ДАТА.zip.')
        parser.add_argument('--with-media', action='store_true',
                            help='Положить в архив загруженные PDF, выданные копии и шаблоны формы.')

    def handle(self, *args, path=None, with_media=False, **options):
        path = Path(path) if path else Path(settings.EXPORT_ROOT) / archive_name(with_media)
        result = export(path, include_media=with_media, username='manage.py')
        log(None, 'json_export', username='manage.py', **audit_details(result))
        for table, count in result.tables.items():
            self.stdout.write(f'  {table}: {count}')
        self.stdout.write(f'Файлов в записях: {result.files}, нет на диске: {result.files_missing}, '
                          f'в архиве: {result.media_files} ({result.media_bytes} байт).')
        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(f'Предупреждение: {warning}'))
        self.stdout.write(self.style.SUCCESS(f'Готово: {path} — записей {result.rows}, '
                                             f'{path.stat().st_size} байт.'))
