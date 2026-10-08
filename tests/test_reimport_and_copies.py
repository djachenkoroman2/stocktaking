"""Повторная загрузка (ТЗ 7.6) и выдача копий (ТЗ 8)."""
import pytest

from imports.apply import ApplyError, default_decision, save_document
from imports.copies import CopyError, issue_copies, register_template
from imports.matching import analyze
from imports.models import DocState
from imports.processing import Incoming, create_batch
from registry.models import Department, ResearchWork, Student, StudyGroup, Teacher
from registry.status import WorkStatus
from tests import pdfs
from tests.conftest import BLANK_FORM, EXAMPLES, upload

FULL = (EXAMPLES / '01-full.pdf').read_bytes()


def import_one(user, name, content, **decision_changes):
    document = create_batch(user, [Incoming(name, content)]).documents.get()
    assert document.state == DocState.PENDING, document.errors
    analysis = analyze(document)
    decision = default_decision(analysis)
    for key, value in decision_changes.items():
        setattr(decision, key, value)
    return document, analysis, save_document(document, decision, user)


@pytest.mark.django_db
def test_reimport_updates_same_work(responsible):
    _, _, work = import_one(responsible, '01.pdf', FULL)
    work.schedule = 'Изменено вручную'
    work.save()
    changed = pdfs.with_values(FULL, {
        'student.task': 'Новая задача.', 'student.schedule': 'Новое расписание.', 'student.status': 'Почти готово',
        'achievements.1.text': 'Изменённое достижение.', 'achievements.10.text': '', 'meta.date_filled': '01.10.2026'})
    document = create_batch(responsible, [Incoming('01-v2.pdf', changed)]).documents.get()
    analysis = analyze(document)
    assert analysis.work == work
    diffs = {d.field: d for d in analysis.work_diff}
    assert diffs['task'].new == 'Новая задача.' and not diffs['task'].manual
    assert diffs['schedule'].manual  # меняли вручную после прошлой загрузки
    assert [a.source_row for a in analysis.achievements_remove] == [10]
    assert len(analysis.achievements_update) == 1
    assert analysis.needs_decision

    decision = default_decision(analysis)
    decision.keep_fields = {'schedule'}
    decision.remove_achievements = {analysis.achievements_remove[0].pk}
    save_document(document, decision, responsible)
    work.refresh_from_db()
    assert ResearchWork.objects.count() == 1
    assert work.task == 'Новая задача.' and work.schedule == 'Изменено вручную'
    assert work.status_comment == 'Почти готово'
    assert sorted(work.achievements.values_list('source_row', flat=True)) == list(range(1, 10))
    assert work.achievements.get(source_row=1).text == 'Изменённое достижение.'
    assert work.history.first().history_change_reason == f'Загрузка PDF №{document.pk}'


@pytest.mark.django_db
def test_reimport_keeps_achievement_without_confirmation(responsible):
    _, _, work = import_one(responsible, '01.pdf', FULL)
    changed = pdfs.with_values(FULL, {'achievements.10.text': ''})
    import_one(responsible, '01-v2.pdf', changed)
    assert work.achievements.count() == 10


@pytest.mark.django_db
def test_reuse_for_other_student_requires_confirmation(responsible):
    import_one(responsible, '01.pdf', FULL)
    other = pdfs.with_values(FULL, {'student.last_name': 'Другой', 'student.first_name': 'Студент',
                                    'student.group_code': 'X-1'})
    document = create_batch(responsible, [Incoming('reuse.pdf', other)]).documents.get()
    analysis = analyze(document)
    assert any('переиспользована' in w for w in analysis.warnings)
    with pytest.raises(ApplyError):
        save_document(document, default_decision(analysis), responsible)


@pytest.mark.django_db
def test_older_version_warning(responsible):
    import_one(responsible, '01.pdf', FULL)
    older = pdfs.with_values(FULL, {'meta.date_filled': '01.09.2026', 'student.notes': 'старое'})
    document = create_batch(responsible, [Incoming('old.pdf', older)]).documents.get()
    assert any('более старая' in w for w in analyze(document).warnings)


@pytest.mark.django_db
def test_status_transition_on_reimport(responsible):
    _, _, work = import_one(responsible, '01.pdf', FULL)
    work.status = WorkStatus.COMPLETED
    work.save()
    changed = pdfs.with_values(FULL, {'student.notes': 'v2'})
    document = create_batch(responsible, [Incoming('v2.pdf', changed)]).documents.get()
    decision = default_decision(analyze(document))
    decision.status = WorkStatus.SUSPENDED
    with pytest.raises(ApplyError, match='можно перейти только'):
        save_document(document, decision, responsible)
    decision.status = WorkStatus.IN_PROGRESS
    with pytest.raises(ApplyError, match='комментария'):
        save_document(document, decision, responsible)
    decision.status_note = 'Продолжение темы'
    save_document(document, decision, responsible)
    work.refresh_from_db()
    assert work.status == WorkStatus.IN_PROGRESS and work.status_comment == 'Продолжение темы'


@pytest.mark.django_db
def test_issue_copy_and_import(responsible):
    with pytest.raises(CopyError):
        register_template('prepared.pdf', FULL, responsible)  # уже подготовленная копия
    register_template('blank.pdf', BLANK_FORM.read_bytes(), responsible)
    department = Department.objects.create(name='Кафедра физики')
    teacher = Teacher.objects.create(last_name='Иванова', first_name='Анна', middle_name='Петровна',
                                     position='Доцент', department=department)
    student = Student.objects.create(last_name='Петров', first_name='Олег', group=StudyGroup.objects.create(code='Ф-11'),
                                     phone='+7 (900) 000-00-99', email='petrov@example.org')
    [copy] = issue_copies(teacher, [student], 0, responsible)
    assert copy.questionnaire_id.startswith('student-') and copy.download_name.startswith('Иванова_А_П_')
    filled = pdfs.with_values(copy.file.read(), {
        'student.last_name': 'Петров', 'student.first_name': 'Олег', 'student.group_code': 'Ф-11',
        'student.phone': '+7 (900) 000-00-99', 'student.email': 'petrov@example.org', 'student.task': 'Задача.',
        'teacher.full_name': ''})
    document, analysis, work = import_one(responsible, 'copy.pdf', filled)
    assert analysis.teacher_source == 'copy' and analysis.student_source == 'copy'
    assert work.teacher == teacher and work.student == student and work.questionnaire_id == copy.questionnaire_id
    copy.refresh_from_db()
    assert copy.work == work


@pytest.mark.django_db
def test_copy_replaces_returned_document(responsible):
    register_template('blank.pdf', BLANK_FORM.read_bytes(), responsible)
    returned = upload(responsible, '20').documents.get()
    teacher = Teacher.objects.create(last_name='Мирошниченко', first_name='Алла',
                                     department=Department.objects.create(name='К'))
    [copy] = issue_copies(teacher, [], 1, responsible, replaces=returned)
    assert copy.replaces_document == returned and copy.student is None
