"""Вход через LDAP / Active Directory (ТЗ, этап 3). Включается переменной LDAP_ENABLED=1.

Два режима:
- шаблон DN (LDAP_USER_DN_TEMPLATE, например «uid={username},ou=people,dc=example,dc=org»
  или «{username}@example.org» для AD) — сразу bind от имени пользователя;
- поиск (LDAP_BIND_DN, LDAP_BIND_PASSWORD, LDAP_SEARCH_BASE, LDAP_SEARCH_FILTER) — служебная
  учётная запись находит DN пользователя, затем bind от его имени.

При первом входе создаётся локальная учётная запись без пароля. Роли назначает администратор.
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from ldap3 import ALL_ATTRIBUTES, Connection, Server
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

logger = logging.getLogger(__name__)


class LDAPBackend(BaseBackend):
    def get_server(self):
        return Server(settings.LDAP['SERVER_URI'])

    def connect(self, user, password):
        """Открытое соединение после успешного bind или None."""
        conn = Connection(self.get_server(), user=user, password=password, raise_exceptions=False)
        if settings.LDAP['START_TLS']:
            conn.open()
            conn.start_tls()
        return conn if conn.bind() else None

    def find_user(self, username):
        """(dn, атрибуты) пользователя или (None, {})."""
        config = settings.LDAP
        if config['USER_DN_TEMPLATE']:
            return config['USER_DN_TEMPLATE'].format(username=username), None
        conn = self.connect(config['BIND_DN'], config['BIND_PASSWORD'])
        if conn is None:
            logger.error('LDAP: не удалось войти служебной учётной записью')
            return None, {}
        search_filter = config['SEARCH_FILTER'].format(username=escape_filter_chars(username))
        conn.search(config['SEARCH_BASE'], search_filter, attributes=ALL_ATTRIBUTES)
        entries = conn.entries
        conn.unbind()
        if len(entries) != 1:
            return None, {}
        return entries[0].entry_dn, entries[0].entry_attributes_as_dict

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password or not settings.LDAP['SERVER_URI']:
            return None
        try:
            dn, attributes = self.find_user(username)
            if dn is None:
                return None
            conn = self.connect(dn, password)
            if conn is None:
                return None
            if attributes is None:
                conn.search(dn, '(objectClass=*)', search_scope='BASE', attributes=ALL_ATTRIBUTES)
                attributes = conn.entries[0].entry_attributes_as_dict if conn.entries else {}
            conn.unbind()
        except LDAPException:
            logger.exception('LDAP: ошибка при входе')
            return None
        return self.sync_user(username, attributes)

    def sync_user(self, username, attributes):
        def first(name):
            value = attributes.get(settings.LDAP[name]) or ['']
            return str(value[0]) if isinstance(value, (list, tuple)) else str(value)

        User = get_user_model()
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_unusable_password()
        user.first_name = first('ATTR_FIRST_NAME')[:150]
        user.last_name = first('ATTR_LAST_NAME')[:150]
        user.email = first('ATTR_EMAIL')[:254]
        user.save()
        return user if user.is_active else None

    def get_user(self, user_id):
        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
