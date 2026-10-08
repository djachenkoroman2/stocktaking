"""Письма ответственным о загрузках, ожидающих решения или возврата (ТЗ, этап 3).

Без контактов студентов и текстов анкет: только число загрузок и ссылка.
"""
from collections import Counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management import BaseCommand

from accounts.access import Access
from accounts.models import Role
from imports.models import DocState


class Command(BaseCommand):
    help = 'Отправляет ответственным письма о загрузках «Ожидает решения» и «К возврату».'

    def handle(self, *args, **options):
        users = get_user_model().objects.filter(is_active=True, roles__role=Role.RESPONSIBLE).exclude(email='').distinct()
        sent = 0
        for user in users:
            counts = Counter(Access(user).documents().filter(
                state__in=(DocState.PENDING, DocState.TO_RETURN)).values_list('state', flat=True))
            if not counts:
                continue
            lines = ['Здравствуйте!', '', 'В системе «Учёт НИР» есть загрузки анкет, требующие внимания:']
            if counts.get(DocState.PENDING):
                lines.append(f'— ожидают решения: {counts[DocState.PENDING]}')
            if counts.get(DocState.TO_RETURN):
                lines.append(f'— нужно вернуть преподавателям: {counts[DocState.TO_RETURN]}')
            if settings.SITE_URL:
                lines += ['', f'Журнал импорта: {settings.SITE_URL.rstrip("/")}/imports/documents/']
            send_mail('Учёт НИР: анкеты ждут решения', '\n'.join(lines), None, [user.email])
            sent += 1
        self.stdout.write(f'Отправлено писем: {sent}')
