"""Набор анкет без ошибок (samples/valid-forms, scripts/generate_valid_forms.py)."""
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
import pytest

from imports.apply import default_decision, save_document, save_ready
from imports.matching import analyze
from imports.models import DocState
from imports.processing import Incoming, collect, create_batch, process_queue
from registry.models import Achievement, Department, ResearchWork, Student, StudyGroup, Teacher
from registry.text import norm
from tests.conftest import upload
from tests.test_import_examples import confirm_all

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / 'samples' / 'valid-forms'
NEW_TEACHER = 'Преподаватель не найден: проверьте разбор ФИО и создайте запись.'

spec = importlib.util.spec_from_file_location('generate_valid_forms', ROOT / 'scripts' / 'generate_valid_forms.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
from extract_static import check, extract_data  # noqa: E402  (vendor в sys.path — из генератора)


@pytest.fixture(scope='module')
def valid_set(tmp_path_factory):
    """Набор, собранный заново во временном каталоге."""
    out = tmp_path_factory.mktemp('valid-forms')
    generator.generate(out)
    expected = json.loads((out / 'expected.json').read_text(encoding='utf-8'))
    return out, expected


def forms_of(expected):
    return [(form, form['data']['students'][0]) for form in expected['forms']]


def test_reproducible_and_committed_description_current(valid_set):
    """Генерация воспроизводима байт в байт, а expected.json и README.md в репозитории — от текущего генератора."""
    out, expected = valid_set
    assert (out / 'expected.json').read_bytes() == (SAMPLES / 'expected.json').read_bytes()
    assert (out / 'README.md').read_bytes() == (SAMPLES / 'README.md').read_bytes()
    with zipfile.ZipFile(out / generator.ZIP_NAME) as archive:
        assert sorted(archive.namelist()) == sorted(f['file'] for f in expected['forms'])


def test_every_form_is_valid(valid_set):
    out, expected = valid_set
    layout = generator.Layout(generator.FORM)
    for form, _ in forms_of(expected):
        path = out / form['file']
        assert generator.hashlib.sha256(path.read_bytes()).hexdigest() == form['sha256']
        data = extract_data(path)
        assert data == form['data'], form['file']
        assert check(data) == ([], []), form['file']
        for name, value in generator.field_values(data).items():
            assert layout.fits(name, value), (form['file'], name)


def test_set_structure(valid_set):
    _, expected = valid_set
    forms = forms_of(expected)
    per_teacher = Counter(form['teacher'] for form, _ in forms)
    assert len(per_teacher) == 20 and set(per_teacher.values()) <= {3, 4, 5}
    assert {form['data']['teacher']['department'] for form, _ in forms} == {generator.DEPARTMENT}
    for teacher in per_teacher:  # ФИО и должность преподавателя одинаковы во всех его анкетах
        assert len({(f['data']['teacher']['full_name'], f['data']['teacher']['position'])
                    for f, _ in forms if f['teacher'] == teacher}) == 1
    assert len({form['questionnaire_id'] for form, _ in forms}) == len(forms)
    assert all(re.fullmatch(r'student-set-\d{2}-\d', form['questionnaire_id']) for form, _ in forms)
    names = [norm(f'{s["last_name"]} {s["first_name"]} {s["middle_name"]}') for _, s in forms]
    assert len(set(names)) == len(names)
    assert len({s['email'] for _, s in forms}) == len(forms) and len({s['phone'] for _, s in forms}) == len(forms)
    assert all(s['email'].split('@')[1] in generator.DOMAINS for _, s in forms)
    assert {s['course'] for _, s in forms} == {'1', '2', '3', '4', '5', '6'}
    counts = Counter(len(s['achievements']) for _, s in forms)
    assert 0 in counts and 10 in counts
    assert set(expected['totals']['statuses']) == {'planned', 'in_progress', 'suspended', 'completed', 'terminated'}
    for form, _ in forms:
        day, month, year = map(int, form['data']['date_filled'].split('.'))
        assert generator.FIRST_DAY <= generator.date(year, month, day) <= generator.TODAY


def test_no_overlap_with_examples(valid_set):
    _, expected = valid_set
    example_students, example_teachers, example_emails = set(), set(), set()
    for path in (ROOT / 'tests' / 'fixtures' / 'examples').glob('*.pdf'):
        try:
            data = extract_data(path)
        except ValueError:  # пример 20 — без ID анкеты
            continue
        student = data['students'][0]
        example_students.add(norm(student['last_name']))
        example_emails.add(norm(student['email']))
        if data['teacher']['full_name']:
            example_teachers.add(norm(data['teacher']['full_name'].split()[0]))
    for form, student in forms_of(expected):
        assert norm(student['last_name']) not in example_students
        assert norm(student['email']) not in example_emails
        assert norm(form['teacher'].split()[0]) not in example_teachers


@pytest.mark.django_db
def test_zip_fits_import_limits(valid_set):
    out, expected = valid_set
    archive = SimpleUploadedFile(generator.ZIP_NAME, (out / generator.ZIP_NAME).read_bytes())
    intake = collect([archive])
    assert intake.skipped == [] and len(intake.files) == len(expected['forms'])


def load_set(out, expected, user):
    """Сценарий из README набора: пакет в фоне → по анкете каждого преподавателя → «Сохранить все готовые»."""
    files = [Incoming(form['file'], (out / form['file']).read_bytes()) for form in expected['forms']]
    batch = create_batch(user, files)
    assert batch.background
    while process_queue():
        pass
    documents = list(batch.documents.order_by('original_name'))
    assert {d.state for d in documents} == {DocState.PENDING}
    assert all(d.errors == [] and d.warnings == [] for d in documents)
    for document in documents:
        assert analyze(document).reasons == [NEW_TEACHER], document.original_name
    first = {}
    for document in documents:
        first.setdefault(document.original_name.split('-')[0], document)
    for document in first.values():
        save_document(document, default_decision(analyze(document)), user)
    saved, skipped = save_ready(batch.documents.all(), user)
    assert (saved, skipped) == (len(documents) - 20, 0)
    assert set(batch.documents.values_list('state', flat=True)) == {DocState.SAVED}
    return batch


@pytest.mark.django_db
def test_import_into_empty_database(valid_set, responsible):
    out, expected = valid_set
    totals = expected['totals']
    load_set(out, expected, responsible)
    assert Department.objects.count() == 1
    assert Teacher.objects.count() == 20
    assert Student.objects.count() == ResearchWork.objects.count() == totals['works']
    assert StudyGroup.objects.count() == totals['groups']
    assert Achievement.objects.count() == totals['achievements']
    for form, student in forms_of(expected):
        work = ResearchWork.objects.get(questionnaire_id=form['questionnaire_id'])
        assert work.teacher.full_name == form['teacher'] and work.student.email == student['email']
        assert work.status_comment == student['status'] and work.achievements.count() == len(student['achievements'])


@pytest.mark.django_db
def test_import_on_top_of_examples(valid_set, responsible):
    """Набор и 20 примеров в одной базе: новые записи не сливаются со старыми."""
    confirm_all(upload(responsible), responsible)
    before = {model: model.objects.count() for model in (Teacher, Student, StudyGroup, ResearchWork)}
    out, expected = valid_set
    load_set(out, expected, responsible)
    totals = expected['totals']
    assert Department.objects.count() == 1
    assert Teacher.objects.count() == before[Teacher] + 20
    assert Student.objects.count() == before[Student] + totals['works']
    assert ResearchWork.objects.count() == before[ResearchWork] + totals['works']
    assert StudyGroup.objects.count() == before[StudyGroup] + totals['groups']
