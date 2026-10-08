"""Удаление исходных PDF старше заданного срока с сохранением извлечённых данных (ТЗ 11.3)."""
from datetime import timedelta

from django.core.management import BaseCommand
from django.utils import timezone

from imports.models import FINAL_STATES, ImportedDocument


class Command(BaseCommand):
    help = 'Удаляет файлы PDF завершённых загрузок старше N дней; записи и извлечённые данные остаются.'

    def add_arguments(self, parser):
        parser.add_argument('--older-than-days', type=int, required=True)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, older_than_days, dry_run=False, **options):
        before = timezone.now() - timedelta(days=older_than_days)
        documents = ImportedDocument.objects.filter(uploaded_at__lt=before, state__in=FINAL_STATES).exclude(file='')
        count = 0
        for document in documents:
            count += 1
            if not dry_run:
                document.file.delete(save=False)
                document.file_purged_at = timezone.now()
                document.save(update_fields=['file', 'file_purged_at'])
        self.stdout.write(f'{"Будет удалено" if dry_run else "Удалено"} файлов: {count}')
