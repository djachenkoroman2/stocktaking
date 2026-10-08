"""Первый администратор из DJANGO_SUPERUSER_* (ТЗ 11.2): создаётся, только если такого пользователя нет."""
import os

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand


class Command(BaseCommand):
    help = 'Создаёт суперпользователя из переменных DJANGO_SUPERUSER_USERNAME/EMAIL/PASSWORD, если его нет.'

    def handle(self, *args, **options):
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
        if not username or not password:
            self.stdout.write('DJANGO_SUPERUSER_* не заданы — пропуск.')
            return
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(f'Пользователь {username} уже есть.')
            return
        User.objects.create_superuser(username, os.environ.get('DJANGO_SUPERUSER_EMAIL', ''), password)
        self.stdout.write(f'Создан администратор {username}.')
