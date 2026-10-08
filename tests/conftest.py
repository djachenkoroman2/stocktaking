from pathlib import Path

from django.contrib.auth.models import User
import pytest

from accounts.models import Role, RoleAssignment
from imports.processing import Incoming, create_batch
from registry.models import Department

FIXTURES = Path(__file__).parent / 'fixtures'
EXAMPLES = FIXTURES / 'examples'
BLANK_FORM = FIXTURES / 'forms' / 'prepod_vnok_info-v2.0-draft04.pdf'
DEPARTMENT = 'Кафедра прикладной математики и информатики'


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / 'media'
    return settings.MEDIA_ROOT


def make_user(username, role=None, department=None, **extra):
    user = User.objects.create_user(username, password='pass-12345-long', **extra)
    if role:
        RoleAssignment.objects.create(user=user, role=role, department=department)
    return user


@pytest.fixture
def responsible(db):
    """Ответственный с областью «все кафедры»: может создавать кафедры из предпросмотра."""
    return make_user('resp', Role.RESPONSIBLE, first_name='Ответственный')


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser('admin', 'admin@example.org', 'pass-12345-long')


def example_files(*names):
    paths = sorted(EXAMPLES.glob('*.pdf'))
    if names:
        paths = [p for p in paths if p.name.split('-')[0] in names]
    return [Incoming(p.name, p.read_bytes()) for p in paths]


@pytest.fixture
def department(db):
    return Department.objects.create(name=DEPARTMENT, short_name='ПМИ')


def upload(user, *names):
    return create_batch(user, example_files(*names))
