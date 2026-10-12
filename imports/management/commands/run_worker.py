"""Фоновый обработчик пакетного импорта (ТЗ 7.1, 11.1) и уведомлений ответственным (ТЗ, этап 3)."""
import time

from django.conf import settings
from django.core.management import BaseCommand, call_command
from django.db import close_old_connections, connection
from django.utils import timezone

from imports.processing import process_queue
from snapshots.service import process_queue as process_exports


class Command(BaseCommand):
    help = 'Обрабатывает загрузки и выгрузки в JSON «В очереди»; раз в NOTIFY_PENDING_HOURS часов рассылает уведомления.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Обработать очередь один раз и выйти.')
        parser.add_argument('--interval', type=float, default=3.0, help='Пауза между проверками, секунд.')

    def handle(self, *args, once=False, interval=3.0, **options):
        last_notify = None
        self.stdout.write('Обработчик импорта запущен.')
        while True:
            if not connection.in_atomic_block:  # в тестах команда выполняется внутри транзакции
                close_old_connections()
            done = process_queue()
            if done:
                self.stdout.write(f'Обработано загрузок: {done}')
            exports = process_exports()
            if exports:
                self.stdout.write(f'Выполнено выгрузок в JSON: {exports}')
            hours = settings.NOTIFY_PENDING_HOURS
            if hours and (last_notify is None or (timezone.now() - last_notify).total_seconds() >= hours * 3600):
                call_command('notify_pending')
                last_notify = timezone.now()
            if once:
                return
            if not done:
                time.sleep(interval)
