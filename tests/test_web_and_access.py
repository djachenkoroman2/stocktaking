"""Права, области данных и скрытие контактов во всех представлениях (ТЗ 3.1, 3.2, 12.3)."""
from django.urls import reverse
import pytest
from rest_framework.authtoken.models import Token

from accounts.models import AuditEvent, Role
from imports.models import DocState, ImportedDocument
from registry.models import Department, ResearchWork, Student, Teacher
from tests.conftest import BLANK_FORM, make_user, upload
from tests.test_import_examples import confirm_all

PHONE = '+7 (900) 000-00-'  # тестовые номера всех примеров


@pytest.fixture
def data(responsible):
    batch = upload(responsible)
    confirm_all(batch, responsible)
    department = Department.objects.get()
    other = Department.objects.create(name='Кафедра физики')
    teacher = Teacher.objects.get(last_name='Белозёрова')
    users = {
        'resp': responsible,
        'resp_a': make_user('resp_a', Role.RESPONSIBLE, department),
        'resp_b': make_user('resp_b', Role.RESPONSIBLE, other),
        'admin': make_user('admin', is_superuser=True, is_staff=True),
        'observer': make_user('observer', Role.OBSERVER, department),
        'observer_b': make_user('observer_b', Role.OBSERVER, other),
        'teacher': make_user('teacher'),
        'nobody': make_user('nobody'),
    }
    teacher.user = users['teacher']
    teacher.save()
    work = teacher.works.first()
    other_work = ResearchWork.objects.exclude(teacher=teacher).first()
    return {'users': users, 'batch': batch, 'work': work, 'other_work': other_work, 'teacher': teacher,
            'department': department}


def client_for(client, user):
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_login_required_and_health(client):
    assert client.get('/works/').status_code == 302
    assert client.get('/health/').json()['status'] == 'ok'
    assert client.get('/api/works/').status_code in (401, 403)


@pytest.mark.django_db
def test_login_lockout(client, responsible, settings):
    settings.LOGIN_MAX_FAILURES = 3
    for _ in range(3):
        client.post(reverse('login'), {'username': 'resp', 'password': 'wrong'})
    response = client.post(reverse('login'), {'username': 'resp', 'password': 'pass-12345-long'})
    assert 'Слишком много неудачных попыток' in response.content.decode()
    assert AuditEvent.objects.filter(action='login_failed').count() == 3


@pytest.mark.django_db
def test_pages_render_for_responsible(client, data):
    c = client_for(client, data['users']['resp'])
    work, batch = data['work'], data['batch']
    pending = ImportedDocument.objects.filter(state=DocState.TO_RETURN).first()
    student = work.student
    urls = ['/', '/works/', f'/works/{work.pk}/', f'/works/{work.pk}/edit/', '/works/new/', '/teachers/',
            f'/teachers/{work.teacher.pk}/', f'/teachers/{work.teacher.pk}/edit/', f'/teachers/{work.teacher.pk}/merge/',
            '/students/', f'/students/{student.pk}/', f'/students/{student.pk}/edit/', '/students/new/',
            f'/students/{student.pk}/merge/', '/departments/', '/groups/', '/groups/new/',
            f'/history/work/{work.pk}/', f'/history/student/{student.pk}/', f'/history/teacher/{work.teacher.pk}/',
            '/imports/upload/', '/imports/batches/', f'/imports/batches/{batch.pk}/', '/imports/documents/',
            f'/imports/documents/{pending.pk}/', f'/imports/batches/{batch.pk}/return-texts/',
            f'/imports/documents/{pending.pk}/return-text/', '/imports/copies/', '/imports/copies/new/',
            '/reports/']
    for url in urls:
        assert c.get(url).status_code == 200, url
    c = client_for(client, data['users']['admin'])
    for url in ['/imports/templates/', '/accounts/audit/', '/admin/', '/admin/registry/student/',
                f'/admin/registry/student/{student.pk}/change/', '/admin/imports/importeddocument/',
                f'/admin/imports/importeddocument/{pending.pk}/change/']:
        response = c.get(url)
        assert response.status_code == 200, url
        assert PHONE not in response.content.decode(), url


@pytest.mark.django_db
def test_contacts_only_for_responsible(client, data):
    users, work = data['users'], data['work']
    phone = work.student.phone
    for name, visible in [('resp', True), ('resp_a', True), ('admin', False), ('observer', False), ('teacher', False)]:
        c = client_for(client, users[name])
        for url in (f'/works/{work.pk}/', f'/students/{work.student.pk}/'):
            body = c.get(url).content.decode()
            assert (phone in body) == visible, (name, url)
    # Поиск по телефону — только ответственным.
    assert work.student.full_name in client_for(client, users['resp_a']).get(f'/students/?q={phone}').content.decode()
    assert work.student.full_name not in client_for(client, users['admin']).get(f'/students/?q={phone}').content.decode()
    assert work.student.full_name not in client_for(client, users['observer']).get(f'/works/?q={phone}').content.decode()


@pytest.mark.django_db
def test_contacts_in_history_hidden(client, data):
    student = data['work'].student
    student.phone = '+7 (900) 111-11-11'
    student.save()
    assert '111-11-11' in client_for(client, data['users']['resp']).get(f'/history/student/{student.pk}/').content.decode()
    body = client_for(client, data['users']['admin']).get(f'/history/student/{student.pk}/').content.decode()
    assert '111-11-11' not in body and 'скрыто' in body


@pytest.mark.django_db
def test_contacts_in_preview_hidden_for_admin(client, data):
    document = ImportedDocument.objects.filter(state=DocState.TO_RETURN, original_name__startswith='09').get()
    body = client_for(client, data['users']['admin']).get(f'/imports/documents/{document.pk}/').content.decode()
    assert PHONE not in body and 'скрыто' in body
    assert PHONE in client_for(client, data['users']['resp']).get(f'/imports/documents/{document.pk}/').content.decode()


@pytest.mark.django_db
def test_pdf_download_only_for_responsible(client, data):
    document = ImportedDocument.objects.filter(state=DocState.SAVED).first()
    assert client_for(client, data['users']['resp_a']).get(f'/imports/documents/{document.pk}/download/').status_code == 200
    assert client_for(client, data['users']['admin']).get(f'/imports/documents/{document.pk}/download/').status_code == 403
    assert client_for(client, data['users']['resp_b']).get(f'/imports/documents/{document.pk}/download/').status_code == 404
    assert AuditEvent.objects.filter(action='pdf_download').count() == 1


@pytest.mark.django_db
def test_contacts_report(client, data):
    url = f'/reports/contacts/?teacher={data["teacher"].pk}&run=1'
    assert PHONE in client_for(client, data['users']['resp']).get(url).content.decode()
    for name in ('admin', 'observer', 'teacher'):
        assert client_for(client, data['users'][name]).get(url).status_code == 403, name
    assert AuditEvent.objects.filter(action='contacts_report').exists()


@pytest.mark.django_db
def test_no_contacts_in_other_reports(client, data):
    c = client_for(client, data['users']['resp'])
    for slug, extra in [('teacher_card', f'&teacher={data["teacher"].pk}'), ('department_summary', ''),
                        ('students_by_course', ''), ('works_by_status', ''), ('achievements', ''),
                        ('teacher_load', ''), ('collection', ''), ('quality', ''), ('import_journal', '')]:
        for fmt in ('html', 'csv', 'xlsx'):
            response = c.get(f'/reports/{slug}/?run=1&include_inactive=on{extra}&format={fmt}')
            if response.status_code == 404:  # формат не предусмотрен для отчёта
                continue
            assert response.status_code == 200, (slug, fmt)
            if fmt != 'xlsx':
                assert PHONE not in response.content.decode('utf-8-sig'), (slug, fmt)


@pytest.mark.django_db
def test_scope_by_department(client, data):
    work = data['work']
    for name in ('resp_b', 'observer_b', 'nobody'):
        c = client_for(client, data['users'][name])
        assert c.get(f'/works/{work.pk}/').status_code == 404, name
        assert work.student.full_name not in c.get('/works/').content.decode(), name
    assert client_for(client, data['users']['observer']).get(f'/works/{work.pk}/').status_code == 200
    assert client_for(client, data['users']['observer']).get(f'/works/{work.pk}/edit/').status_code == 403
    assert client_for(client, data['users']['resp_b']).get(f'/works/{work.pk}/edit/').status_code == 404
    assert client_for(client, data['users']['resp_b']).get('/imports/documents/').content.decode().count('01-full') == 0


@pytest.mark.django_db
def test_teacher_read_only(client, data):
    c = client_for(client, data['users']['teacher'])
    assert c.get(f'/works/{data["work"].pk}/').status_code == 200
    assert c.get(f'/works/{data["other_work"].pk}/').status_code == 404
    for url in (f'/works/{data["work"].pk}/edit/', '/works/new/', '/imports/upload/', '/imports/copies/new/',
                '/students/new/', '/imports/documents/'):
        assert c.get(url).status_code == 403, url
    assert c.post(f'/works/{data["work"].pk}/status/', {'status': 'completed'}).status_code == 404
    body = c.get('/reports/teacher_load/?run=1&include_inactive=on').content.decode()
    assert 'Белозёрова' in body and 'Кочетов' not in body


@pytest.mark.django_db
def test_admin_cannot_create_students(client, data):
    c = client_for(client, data['users']['admin'])
    assert c.get('/students/new/').status_code == 403
    response = c.get(f'/students/{data["work"].student.pk}/edit/')
    assert response.status_code == 200 and 'name="phone"' not in response.content.decode()


@pytest.mark.django_db
def test_status_change_and_audit(client, data):
    work = data['work']
    c = client_for(client, data['users']['resp_a'])
    c.post(f'/works/{work.pk}/status/', {'status': 'completed'})
    work.refresh_from_db()
    assert work.status == 'completed'
    c.post(f'/works/{work.pk}/status/', {'status': 'in_progress'})
    work.refresh_from_db()
    assert work.status == 'completed'  # без комментария не возобновляется
    assert AuditEvent.objects.filter(action='work_status').count() == 1


@pytest.mark.django_db
def test_preview_flow_via_web(client, responsible):
    batch = upload(responsible, '01', '08')
    c = client_for(client, responsible)
    first = batch.documents.get(original_name__startswith='01')
    form = {'teacher_mode': 'new', 'new_last_name': 'Белозёрова', 'new_first_name': 'Марина',
            'new_middle_name': 'Викторовна', 'new_position': 'Профессор',
            'new_department': 'Кафедра прикладной математики и информатики', 'student': 'new', 'status': 'planned'}
    response = c.post(f'/imports/documents/{first.pk}/', form)
    assert response.status_code == 302
    work = ResearchWork.objects.get()
    assert work.status == 'planned' and work.teacher.position == 'Профессор'
    second = batch.documents.get(original_name__startswith='08')
    page = c.get(f'/imports/documents/{second.pk}/').content.decode()
    assert 'Курс (в анкете: «II»)' in page
    response = c.post(f'/imports/documents/{second.pk}/', {
        'teacher_mode': 'existing', 'teacher': work.teacher.pk, 'student': 'new', 'course': '2',
        'status': 'in_progress'})
    assert response.status_code == 302
    assert Student.objects.get(last_name='Тарасова').course == 2
    reject = upload(responsible, '03').documents.get()
    assert c.post(f'/imports/documents/{reject.pk}/reject/', {'note': 'Не наша анкета'}).status_code == 302
    reject.refresh_from_db()
    assert reject.state == DocState.REJECTED_USER


@pytest.mark.django_db
def test_upload_zip_and_mark_returned(client, responsible):
    import io
    import zipfile
    from tests.conftest import EXAMPLES
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name in ('09-bad-email-and-date.pdf', '12-cadet-6th-course.pdf'):
            archive.write(EXAMPLES / name, f'folder/{name}')
        archive.writestr('readme.txt', 'skip')
    buffer.seek(0)
    buffer.name = 'pack.zip'
    c = client_for(client, responsible)
    response = c.post('/imports/upload/', {'files': [buffer]})
    batch_id = int(response['Location'].rstrip('/').split('/')[-1])
    assert ImportedDocument.objects.filter(batch_id=batch_id).count() == 2
    c.post(f'/imports/batches/{batch_id}/mark-returned/')
    assert ImportedDocument.objects.get(batch_id=batch_id, original_name__startswith='09').state == DocState.RETURNED
    report = c.get('/reports/collection/?run=1').content.decode()
    assert '09-bad-email-and-date.pdf' in report


@pytest.mark.django_db
def test_template_and_copies_via_web(client, data):
    c = client_for(client, data['users']['admin'])
    with open(BLANK_FORM, 'rb') as handle:
        assert c.post('/imports/templates/', {'file': handle}).status_code == 302
    response = c.post('/imports/copies/new/', {'teacher': data['teacher'].pk, 'count': 2})
    assert response.status_code == 200 and 'Копии подготовлены' in response.content.decode()
    ids = response.context['ids']
    zipped = c.get(f'/imports/copies/zip/?ids={ids}')
    assert zipped.status_code == 200 and zipped['Content-Type'] == 'application/zip'


@pytest.mark.django_db
def test_pdf_reports(client, data):
    c = client_for(client, data['users']['resp'])
    for url in (f'/reports/teacher_card/?run=1&teacher={data["teacher"].pk}&format=pdf',
                '/reports/department_summary/?run=1&format=pdf', '/reports/achievements/?run=1&format=pdf'):
        response = c.get(url)
        assert response.status_code == 200 and response.content.startswith(b'%PDF'), url


@pytest.mark.django_db
def test_report_numbers(client, data):
    from reports.definitions import BY_SLUG, build
    from accounts.access import Access
    access = Access(data['users']['resp'])
    load = build(BY_SLUG['teacher_load'], access, {'include_inactive': True}).sections[0].rows
    assert {row[0].split()[0]: row[2] for row in load} == {
        'Белозёрова': 3, 'Сорокопудов': 2, 'Кочетов': 1, 'Ладыгина': 2, 'Мирошниченко': 6}
    summary = build(BY_SLUG['department_summary'], access, {}).sections[0]
    assert summary.totals[3] == 14  # активных студентов
    achievements = build(BY_SLUG['achievements'], access, {}).sections[0].rows
    expected = sum(ResearchWork.objects.get(pk=w).achievements.count() for w in ResearchWork.objects.values_list('pk', flat=True))
    assert len(achievements) == expected


@pytest.mark.django_db
def test_api(client, data):
    users = data['users']
    token = Token.objects.create(user=users['resp_a'])
    response = client.get('/api/students/', HTTP_AUTHORIZATION=f'Token {token.key}')
    assert response.status_code == 200 and 'phone' in response.json()['results'][0]
    token_admin = Token.objects.create(user=users['admin'])
    results = client.get('/api/students/', HTTP_AUTHORIZATION=f'Token {token_admin.key}').json()['results']
    assert results and 'phone' not in results[0]
    works = client.get('/api/works/', HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=users["teacher"]).key}')
    assert {w['teacher'] for w in works.json()['results']} == {data['teacher'].pk}
    nobody = client.get('/api/works/', HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=users["nobody"]).key}')
    assert nobody.status_code == 403
    observer_b = Token.objects.create(user=users['observer_b'])
    assert client.get('/api/works/', HTTP_AUTHORIZATION=f'Token {observer_b.key}').json()['count'] == 0
