"""Смена пользователя и доступ к админке Django из интерфейса (prompts/0005_improved.txt)."""
from django.contrib.auth.models import User
from django.urls import reverse
import pytest

from accounts.models import AuditEvent, Role
from registry.models import Teacher
from tests.conftest import make_user

PASSWORD = 'pass-12345-long'
SWITCH_ITEM = 'Сменить пользователя'
ADMIN_ITEM = 'Админка Django: пользователи, роли, настройки'


@pytest.fixture
def users(department):
    teacher_user = make_user('teacher', first_name='Анна', last_name='Белова')
    Teacher.objects.create(last_name='Белова', first_name='Анна', department=department, user=teacher_user)
    return {
        'superuser': User.objects.create_superuser('root', 'root@example.org', PASSWORD),
        'role_admin': make_user('role_admin', Role.ADMIN, first_name='Иван', last_name='Петров'),
        'resp': make_user('resp', Role.RESPONSIBLE, department),
        'observer': make_user('observer', Role.OBSERVER, department),
        'teacher': teacher_user,
        'nobody': make_user('nobody'),
        'staff_only': make_user('staff_only', is_staff=True),
    }


def switch(client, next_url):
    return client.post(reverse('switch_user'), {'next': next_url})


def login(client, username, next_url=''):
    url = reverse('login') + (f'?next={next_url}' if next_url else '')
    return client.post(url, {'username': username, 'password': PASSWORD, 'next': next_url})


@pytest.mark.django_db
@pytest.mark.parametrize('name', ['superuser', 'role_admin', 'resp', 'observer', 'teacher', 'nobody'])
def test_switch_item_in_menu_for_every_role(client, users, name):
    client.force_login(users[name])
    html = client.get('/').content.decode()
    assert SWITCH_ITEM in html
    assert f'action="{reverse("switch_user")}"' in html


@pytest.mark.django_db
def test_switch_logs_out_and_shows_login_hint(client, users):
    client.force_login(users['role_admin'])
    response = switch(client, '/works/?status=active')
    assert response.status_code == 302
    assert response.url == reverse('login') + '?next=%2Fworks%2F%3Fstatus%3Dactive'
    assert '_auth_user_id' not in client.session
    html = client.get(response.url).content.decode()
    assert 'Вы вышли из учётной записи «Иван Петров»' in html
    assert 'value="role_admin"' not in html  # поле логина пустое


@pytest.mark.django_db
def test_switch_requires_post(client, users):
    client.force_login(users['resp'])
    assert client.get(reverse('switch_user')).status_code == 405
    assert client.session['_auth_user_id'] == str(users['resp'].pk)


@pytest.mark.django_db
def test_switch_ignores_external_next(client, users):
    client.force_login(users['resp'])
    assert switch(client, 'https://evil.example.org/').url == reverse('login')


@pytest.mark.django_db
def test_switch_returns_to_accessible_page(client, users):
    client.force_login(users['superuser'])
    switch(client, '/works/')
    response = login(client, 'observer', '/works/')
    assert response.url == '/works/'
    assert client.get('/works/').status_code == 200
    assert 'switch_from' not in client.session
    assert 'switch_next' not in client.session


@pytest.mark.django_db
def test_switch_to_user_without_access_opens_dashboard(client, users):
    client.force_login(users['superuser'])
    switch(client, '/accounts/audit/')
    response = login(client, 'resp', '/accounts/audit/')
    response = client.get(response.url, follow=True)
    assert response.redirect_chain == [(reverse('dashboard'), 302)]
    assert 'этой учётной записи недоступна' in response.content.decode()
    # Проверка только для первого запроса после входа: дальше — обычный отказ.
    assert client.get('/accounts/audit/').status_code == 403


@pytest.mark.django_db
def test_ordinary_login_keeps_forbidden_response(client, users):
    response = login(client, 'resp', '/accounts/audit/')
    assert client.get(response.url).status_code == 403


@pytest.mark.django_db
def test_switch_audit_events(client, users):
    client.force_login(users['resp'])
    switch(client, '/')
    login(client, 'observer')
    events = list(AuditEvent.objects.order_by('id').values_list('username', 'action', 'details'))
    assert events[-2:] == [('resp', 'logout', {'switch_user': True}), ('observer', 'login', {})]


@pytest.mark.django_db
def test_switch_login_keeps_lockout(client, users, settings):
    settings.LOGIN_MAX_FAILURES = 2
    client.force_login(users['resp'])
    switch(client, '/')
    for _ in range(2):
        client.post(reverse('login'), {'username': 'observer', 'password': 'wrong'})
    response = login(client, 'observer')
    assert 'Слишком много неудачных попыток' in response.content.decode()
    assert '_auth_user_id' not in client.session


@pytest.mark.django_db
@pytest.mark.parametrize('name', ['superuser', 'role_admin'])
def test_admins_see_and_open_django_admin(client, users, name):
    client.force_login(users[name])
    assert ADMIN_ITEM in client.get('/').content.decode()
    response = client.get(reverse('admin:index'))
    assert response.status_code == 200
    assert 'href="/"' in response.content.decode()  # «Открыть сайт» — обратно в интерфейс
    assert client.get(reverse('admin:auth_user_changelist')).status_code == 200
    assert client.get(reverse('admin:registry_teacher_changelist')).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize('name', ['resp', 'observer', 'teacher', 'nobody', 'staff_only'])
def test_others_have_no_django_admin(client, users, name):
    client.force_login(users[name])
    assert ADMIN_ITEM not in client.get('/').content.decode()
    # Админка перенаправляет на свою страницу входа, а та отказывает вошедшему без роли администратора.
    for url in (reverse('admin:index'), reverse('admin:auth_user_changelist')):
        assert client.get(url, follow=True).status_code == 403, url
    assert client.get(reverse('admin:login')).status_code == 403


@pytest.mark.django_db
def test_admin_login_goes_through_system_login(client, users):
    response = client.get(reverse('admin:index'))
    assert response.url == reverse('admin:login') + '?next=/admin/'
    response = client.get(response.url)
    assert response.url == reverse('login') + '?next=%2Fadmin%2F'
    response = login(client, 'role_admin', '/admin/')
    assert response.url == '/admin/'
    assert client.get('/admin/').status_code == 200


@pytest.mark.django_db
def test_role_admin_manages_users_but_not_superusers(client, users):
    client.force_login(users['role_admin'])
    resp, root = users['resp'], users['superuser']
    html = client.get(reverse('admin:auth_user_change', args=[resp.pk])).content.decode()
    assert 'name="is_superuser"' not in html  # только для чтения
    assert 'name="is_active"' in html
    response = client.post(reverse('admin:auth_user_change', args=[resp.pk]), {
        'username': 'resp', 'is_active': 'on', 'is_superuser': 'on', 'is_staff': 'on',
        'date_joined_0': '2026-10-13', 'date_joined_1': '10:00:00', 'first_name': 'Новое имя',
        'roles-TOTAL_FORMS': '0', 'roles-INITIAL_FORMS': '0',
    })
    assert response.status_code == 302, response.content.decode()[:2000]
    resp.refresh_from_db()
    assert resp.first_name == 'Новое имя' and not resp.is_superuser and not resp.is_staff
    # Суперпользователя — только просмотр: ни изменения, ни смены пароля, ни удаления.
    assert client.post(reverse('admin:auth_user_change', args=[root.pk]), {'username': 'root2'}).status_code == 403
    assert client.get(reverse('admin:auth_user_password_change', args=[root.pk])).status_code == 403
    assert client.get(reverse('admin:auth_user_delete', args=[root.pk])).status_code == 403
    root.refresh_from_db()
    assert root.username == 'root'
