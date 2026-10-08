from io import StringIO

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from ldap3 import MOCK_SYNC, OFFLINE_SLAPD_2_4, Connection, Server
import pytest

from accounts.ldap_backend import LDAPBackend
from imports.models import DocState, ImportedDocument
from tests.conftest import upload

USER_DN = 'uid=ivanova,ou=people,dc=example,dc=org'


class MockBackend(LDAPBackend):
    """Тот же backend поверх ldap3 MOCK_SYNC: общий словарь записей вместо сервера."""
    server = Server('mock', get_info=OFFLINE_SLAPD_2_4)
    entries = {}

    def connect(self, user, password):
        conn = Connection(self.server, user=user, password=password, client_strategy=MOCK_SYNC)
        for dn, attributes in self.entries.items():
            conn.strategy.add_entry(dn, attributes)
        return conn if conn.bind() else None


@pytest.fixture
def ldap_settings(settings):
    settings.LDAP = {**settings.LDAP, 'ENABLED': True, 'SERVER_URI': 'ldap://mock', 'USER_DN_TEMPLATE': '',
                     'BIND_DN': 'cn=reader,dc=example,dc=org', 'BIND_PASSWORD': 'reader-pass',
                     'SEARCH_BASE': 'ou=people,dc=example,dc=org', 'SEARCH_FILTER': '(uid={username})'}
    MockBackend.entries = {
        'cn=reader,dc=example,dc=org': {'objectClass': ['person'], 'userPassword': 'reader-pass', 'sn': 'reader'},
        USER_DN: {'objectClass': ['inetOrgPerson'], 'uid': 'ivanova', 'userPassword': 'secret', 'sn': 'Иванова',
                  'givenName': 'Анна', 'mail': 'ivanova@example.org'},
    }
    return settings


@pytest.mark.django_db
def test_ldap_search_mode(ldap_settings):
    backend = MockBackend()
    assert backend.authenticate(None, username='ivanova', password='wrong') is None
    user = backend.authenticate(None, username='ivanova', password='secret')
    assert user is not None and user.last_name == 'Иванова' and user.email == 'ivanova@example.org'
    assert not user.has_usable_password()
    assert backend.authenticate(None, username='nobody', password='secret') is None


@pytest.mark.django_db
def test_ldap_dn_template_mode(ldap_settings):
    ldap_settings.LDAP = {**ldap_settings.LDAP, 'USER_DN_TEMPLATE': 'uid={username},ou=people,dc=example,dc=org'}
    user = MockBackend().authenticate(None, username='ivanova', password='secret')
    assert user is not None and user.first_name == 'Анна'
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_notify_pending(responsible, settings):
    responsible.email = 'resp@example.org'
    responsible.save()
    upload(responsible, '01', '09')
    call_command('notify_pending', stdout=StringIO())
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert 'ожидают решения: 1' in body and 'вернуть преподавателям: 1' in body
    assert '+7' not in body


@pytest.mark.django_db
def test_purge_pdfs(responsible):
    upload(responsible, '09')
    document = ImportedDocument.objects.get()
    document.state = DocState.RETURNED
    document.save()
    call_command('purge_pdfs', '--older-than-days', '0', stdout=StringIO())
    document.refresh_from_db()
    assert not document.file and document.file_purged_at and document.extracted


@pytest.mark.django_db
def test_worker_once(responsible, settings):
    settings.IMPORT_SYNC_LIMIT = 0
    upload(responsible, '01')
    call_command('run_worker', '--once', stdout=StringIO())
    assert ImportedDocument.objects.get().state == DocState.PENDING


@pytest.mark.django_db
def test_ensure_superuser(monkeypatch):
    monkeypatch.setenv('DJANGO_SUPERUSER_USERNAME', 'root')
    monkeypatch.setenv('DJANGO_SUPERUSER_PASSWORD', 'root-pass-12345')
    call_command('ensure_superuser', stdout=StringIO())
    call_command('ensure_superuser', stdout=StringIO())
    assert User.objects.get(username='root').is_superuser
