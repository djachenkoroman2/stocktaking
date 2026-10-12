"""Журнал выгрузок в JSON, сделанных через интерфейс (сами архивы — в EXPORT_ROOT)."""
from pathlib import Path

from django.conf import settings
from django.db import models


class SnapshotExport(models.Model):
    class State(models.TextChoices):
        QUEUED = 'queued', 'В очереди'
        RUNNING = 'running', 'Выполняется'
        DONE = 'done', 'Готово'
        FAILED = 'failed', 'Ошибка'

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, related_name='+',
                                   verbose_name='запросил')
    created_at = models.DateTimeField('запрошена', auto_now_add=True)
    include_media = models.BooleanField('с файлами', default=False)
    state = models.CharField('состояние', max_length=10, choices=State.choices, default=State.QUEUED,
                             db_index=True)
    file_name = models.CharField('архив', max_length=255, blank=True)
    size = models.BigIntegerField('размер', null=True, blank=True)
    rows = models.PositiveIntegerField('записей', null=True, blank=True)
    summary = models.JSONField('итоги', default=dict, blank=True)
    error = models.TextField('ошибка', blank=True)
    finished_at = models.DateTimeField('завершена', null=True, blank=True)

    class Meta:
        verbose_name = 'выгрузка в JSON'
        verbose_name_plural = 'выгрузки в JSON'
        ordering = ['-created_at']

    def __str__(self):
        return self.file_name or f'Выгрузка №{self.pk}'

    @property
    def path(self):
        return Path(settings.EXPORT_ROOT) / self.file_name if self.file_name else None

    @property
    def is_active(self):
        return self.state in (self.State.QUEUED, self.State.RUNNING)
