from django.apps import AppConfig
from django.contrib.admin import apps as admin_apps


class AccountsConfig(AppConfig):
    name = 'accounts'
    verbose_name = 'Пользователи и аудит'

    def ready(self):
        from . import signals  # noqa: F401


class SystemAdminConfig(admin_apps.AdminConfig):
    """Админка Django с доступом по роли «Администратор» (admin_site.SystemAdminSite)."""
    default = False
    default_site = 'accounts.admin_site.SystemAdminSite'
