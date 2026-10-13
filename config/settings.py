"""Настройки «Учёт НИР». Все параметры среды — через переменные окружения (см. .env.example)."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def env_int(name, default):
    value = os.environ.get(name)
    return int(value) if value not in (None, '') else default


def env_list(name, default=''):
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


DEBUG = env_bool('DJANGO_DEBUG', False)
SECRET_KEY = env('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('Задайте DJANGO_SECRET_KEY или включите DJANGO_DEBUG=1 для разработки.')
    SECRET_KEY = 'dev-only-insecure-key'
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

INSTALLED_APPS = [
    'accounts.apps.SystemAdminConfig',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'simple_history',
    'accounts',
    'registry',
    'imports',
    'reports',
    'api',
    'snapshots',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
    'accounts.middleware.LoginRequiredMiddleware',
    'accounts.middleware.SwitchUserFallbackMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'accounts.context_processors.access',
    ]},
}]

WSGI_APPLICATION = 'config.wsgi.application'

if env('POSTGRES_HOST'):
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('POSTGRES_DB', 'stocktaking'),
        'USER': env('POSTGRES_USER', 'stocktaking'),
        'PASSWORD': env('POSTGRES_PASSWORD', ''),
        'HOST': env('POSTGRES_HOST'),
        'PORT': env('POSTGRES_PORT', '5432'),
        'CONN_MAX_AGE': 60,
    }}
else:
    # Только для разработки и тестов без Docker.
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.ModelBackend', 'accounts.backends.RoleAdminBackend']
LDAP = {
    'ENABLED': env_bool('LDAP_ENABLED', False),
    'SERVER_URI': env('LDAP_SERVER_URI', ''),
    'START_TLS': env_bool('LDAP_START_TLS', False),
    'USER_DN_TEMPLATE': env('LDAP_USER_DN_TEMPLATE', ''),
    'BIND_DN': env('LDAP_BIND_DN', ''),
    'BIND_PASSWORD': env('LDAP_BIND_PASSWORD', ''),
    'SEARCH_BASE': env('LDAP_SEARCH_BASE', ''),
    'SEARCH_FILTER': env('LDAP_SEARCH_FILTER', '(uid={username})'),
    'ATTR_FIRST_NAME': env('LDAP_ATTR_FIRST_NAME', 'givenName'),
    'ATTR_LAST_NAME': env('LDAP_ATTR_LAST_NAME', 'sn'),
    'ATTR_EMAIL': env('LDAP_ATTR_EMAIL', 'mail'),
}
if LDAP['ENABLED']:
    AUTHENTICATION_BACKENDS.insert(0, 'accounts.ldap_backend.LDAPBackend')

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'
LOGIN_MAX_FAILURES = env_int('LOGIN_MAX_FAILURES', 10)
LOGIN_LOCK_MINUTES = env_int('LOGIN_LOCK_MINUTES', 15)

LANGUAGE_CODE = 'ru'
TIME_ZONE = env('TIME_ZONE', 'Europe/Moscow')
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = Path(env('DJANGO_STATIC_ROOT', BASE_DIR / 'staticfiles'))
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_ROOT = Path(env('DJANGO_MEDIA_ROOT', BASE_DIR / 'media'))
# MEDIA_URL намеренно не публикуется: файлы отдаются только через представления с проверкой прав.

IMPORT_MAX_FILE_MB = env_int('IMPORT_MAX_FILE_MB', 10)
IMPORT_MAX_FILES = env_int('IMPORT_MAX_FILES', 200)
IMPORT_MAX_BATCH_MB = env_int('IMPORT_MAX_BATCH_MB', 200)
IMPORT_SYNC_LIMIT = env_int('IMPORT_SYNC_LIMIT', 20)
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = IMPORT_MAX_FILES + 10
STALE_WORK_DAYS = env_int('STALE_WORK_DAYS', 90)

# Выгрузка базы в JSON (snapshots): каталог готовых архивов — не публикуется и не входит в media.
EXPORT_ROOT = Path(env('DJANGO_EXPORT_ROOT', BASE_DIR / 'exports'))
# Выгрузка без файлов, в базе не больше стольких записей, — сразу в запросе; иначе — в фоне (worker).
EXPORT_SYNC_ROWS = env_int('EXPORT_SYNC_ROWS', 5000)

EMAIL_BACKEND = env('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend' if env('EMAIL_HOST')
                    else 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', '')
EMAIL_PORT = env_int('EMAIL_PORT', 25)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', False)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', 'stocktaking@localhost')
NOTIFY_PENDING_HOURS = env_int('NOTIFY_PENDING_HOURS', 0)  # 0 — уведомления выключены
SITE_URL = env('SITE_URL', '')

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool('DJANGO_SECURE_COOKIES', True)
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'}},
    'root': {'handlers': ['console'], 'level': env('LOG_LEVEL', 'INFO')},
}
