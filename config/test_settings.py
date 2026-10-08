"""Настройки для тестов: без внешних зависимостей, если POSTGRES_HOST не задан."""
import os

os.environ.setdefault('DJANGO_DEBUG', '1')
os.environ.setdefault('DJANGO_SECRET_KEY', 'test-secret-key')

from .settings import *  # noqa: E402,F401,F403

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
