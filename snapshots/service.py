"""Выгрузки из интерфейса: синхронно для небольшой базы, иначе — фоновым обработчиком (run_worker)."""
import logging

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from accounts.audit import log

from .exporter import count_rows, export
from .models import SnapshotExport

logger = logging.getLogger(__name__)


def archive_name(include_media=False, number=None):
    stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
    return f'stocktaking-{stamp}{f"-{number}" if number else ""}{"-media" if include_media else ""}.zip'


def audit_details(result):
    return {'file': result.path.name, 'rows': result.rows, 'media_files': result.media_files}


def request_export(user, include_media):
    """Создать выгрузку. Небольшая база без файлов выгружается сразу, остальное ставится в очередь."""
    job = SnapshotExport.objects.create(created_by=user, include_media=include_media)
    if not include_media and count_rows() <= settings.EXPORT_SYNC_ROWS:
        run(job)
    return job


def run(job):
    job.state = SnapshotExport.State.RUNNING
    job.file_name = archive_name(job.include_media, job.pk)
    job.save(update_fields=['state', 'file_name'])
    username = job.created_by.get_username() if job.created_by else ''
    try:
        result = export(job.path, include_media=job.include_media, username=username)
    except Exception as error:  # ошибка видна на странице выгрузок, подробности — в журнале
        logger.exception('Выгрузка в JSON №%s не выполнена', job.pk)
        job.state = SnapshotExport.State.FAILED
        job.error = str(error) or error.__class__.__name__
    else:
        job.state = SnapshotExport.State.DONE
        job.size = job.path.stat().st_size
        job.rows = result.rows
        job.summary = {'tables': result.tables, 'files': result.files, 'files_missing': result.files_missing,
                       'media_files': result.media_files, 'warnings': result.warnings}
        log(job.created_by, 'json_export', job, **audit_details(result))
    job.finished_at = timezone.now()
    job.save()
    return job


def process_queue():
    """Выполнить выгрузки «В очереди». Возвращает число выполненных. Для фонового обработчика."""
    done = 0
    while True:
        with transaction.atomic():
            qs = SnapshotExport.objects.filter(state=SnapshotExport.State.QUEUED).order_by('id')
            if connection.features.has_select_for_update_skip_locked:
                qs = qs.select_for_update(skip_locked=True)
            job = qs.first()
            if job is None:
                return done
            job.state = SnapshotExport.State.RUNNING
            job.save(update_fields=['state'])
        run(job)
        done += 1
