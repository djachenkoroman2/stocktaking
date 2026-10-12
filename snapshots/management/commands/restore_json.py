"""Восстановление базы из выгрузки JSON. Только в пустую базу после migrate."""
from django.core.management import BaseCommand, CommandError

from snapshots.restorer import Restore


class Command(BaseCommand):
    help = ('Восстанавливает базу из архива export_json. База должна быть пустой (после migrate); '
            'сначала стоит выполнить проверку с --dry-run.')

    def add_arguments(self, parser):
        parser.add_argument('path', help='Архив выгрузки (ZIP).')
        parser.add_argument('--dry-run', action='store_true', help='Только проверить архив и базу, ничего не менять.')
        parser.add_argument('--drop-existing-users', action='store_true',
                            help='Удалить пользователей, которые уже есть в пустой базе (например, созданного '
                                 'из DJANGO_SUPERUSER_*), и загрузить пользователей из выгрузки.')

    def handle(self, *args, path, dry_run=False, drop_existing_users=False, **options):
        report = Restore(path, dry_run=dry_run, drop_existing_users=drop_existing_users, username='manage.py').run()
        for line in report.lines():
            style = self.style.ERROR if line.startswith('Ошибка') else (
                self.style.WARNING if line.startswith('Предупреждение') else str)
            self.stdout.write(style(line))
        if not report.ok:
            raise CommandError('Восстановление не выполнено.' if not dry_run else 'Проверка не пройдена.')
