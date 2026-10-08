from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'
    verbose_name = 'Пользователи и аудит'

    def ready(self):
        from . import signals  # noqa: F401
