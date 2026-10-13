"""Админка Django для администраторов системы (роль «Администратор» или суперпользователь).

Стандартная админка пускает только is_staff и проверяет права модели; роль «Администратор»
задаётся в RoleAssignment, поэтому доступ и права определяются ролью (см. backends.RoleAdminBackend).
Вход — только через страницу входа системы: блокировка, LDAP и аудит работают одинаково.
"""
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from .access import access_for


class SystemAdminSite(admin.AdminSite):
    site_header = 'Учёт НИР — админка Django'
    site_title = 'Учёт НИР'
    index_title = 'Пользователи, роли, настройки'
    site_url = '/'

    def has_permission(self, request):
        return request.user.is_active and access_for(request).is_admin

    def login(self, request, extra_context=None):
        if request.user.is_authenticated:
            if self.has_permission(request):
                return redirect(request.GET.get('next') or reverse('admin:index', current_app=self.name))
            raise PermissionDenied
        next_url = request.GET.get('next') or reverse('admin:index', current_app=self.name)
        return redirect(f'{reverse(settings.LOGIN_URL)}?{urlencode({"next": next_url})}')
