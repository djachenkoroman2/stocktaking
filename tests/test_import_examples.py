"""Импорт 20 примеров с ожиданиями из ТЗ 12.2."""
from datetime import date

import pytest

from imports.apply import default_decision, is_ready, save_document, save_ready
from imports.matching import analyze
from imports.models import DocState, ImportedDocument
from imports.processing import Incoming, create_batch, mark_returned
from registry.models import Department, ResearchWork, StudyGroup, Teacher
from registry.status import WorkStatus
from registry.text import academic_year
from tests import pdfs
from tests.conftest import DEPARTMENT, EXAMPLES, upload

RETURNED = {'09', '10', '17', '18', '19', '20'}


def doc(batch, number):
    return batch.documents.get(original_name__startswith=number)


def confirm_all(batch, user, teacher_for_02='Мирошниченко'):
    """Действия ответственного: подтвердить каждую анкету с решением по умолчанию."""
    pending = list(batch.documents.filter(state=DocState.PENDING).order_by('original_name'))
    pending.sort(key=lambda d: d.original_name.startswith('02'))  # 02 — последним: преподавателя выбирают вручную
    for document in pending:
        analysis = analyze(document)
        decision = default_decision(analysis)
        if analysis.teacher_source == 'empty':
            decision.teacher_id = Teacher.objects.get(last_name=teacher_for_02).pk
        save_document(document, decision, user)


@pytest.mark.django_db
def test_states_after_upload(responsible):
    batch = upload(responsible)
    states = {d.original_name[:2]: d.state for d in batch.documents.all()}
    assert {n for n, s in states.items() if s == DocState.TO_RETURN} == RETURNED
    assert {n for n, s in states.items() if s == DocState.PENDING} == {f'{i:02}' for i in range(1, 21)} - RETURNED
    assert ResearchWork.objects.count() == 0  # без подтверждения ничего не записывается


@pytest.mark.django_db
def test_full_batch_acceptance(responsible):
    batch = upload(responsible)
    first = analyze(doc(batch, '01'))
    assert first.teacher_source == 'new' and first.department is None
    assert first.parsed_teacher == ('Белозёрова', 'Марина', 'Викторовна')

    save_document(doc(batch, '01'), default_decision(first), responsible)
    # Повторное сопоставление: преподаватель и кафедра из 01 находятся для 08 и 11 (ТЗ 7.1, п. 7).
    eleven = analyze(doc(batch, '11'))
    assert eleven.teacher_source == 'exact' and is_ready(eleven)
    assert not is_ready(analyze(doc(batch, '08')))  # предупреждение о курсе

    confirm_all(batch, responsible)
    assert Department.objects.count() == 1 and Department.objects.get().name == DEPARTMENT
    assert Teacher.objects.count() == 5
    assert ResearchWork.objects.count() == 14
    per_teacher = {t.last_name: t.works.count() for t in Teacher.objects.all()}
    assert per_teacher == {'Белозёрова': 3, 'Сорокопудов': 2, 'Кочетов': 1, 'Ладыгина': 2, 'Мирошниченко': 6}
    assert batch.documents.filter(state=DocState.TO_RETURN).count() == 6
    assert all(w.status == WorkStatus.IN_PROGRESS for w in ResearchWork.objects.all())

    def work(number):
        return ResearchWork.objects.get(questionnaire_id=f'student-example-{number}')

    assert work('01').achievements.count() == 10
    assert sorted(work('07').achievements.values_list('source_row', flat=True)) == [1, 4, 7]
    assert work('08').student.course == 2 and work('08').course_at_filling == 'II'
    assert work('16').student.course == 1 and work('16').course_at_filling == '1 курс'
    assert work('12').student.course == 6
    assert work('06').date_filled == date(2026, 9, 30)
    assert '\r' not in work('13').task + work('13').schedule
    assert work('14').task.rstrip().endswith(work('14').task.rstrip().splitlines()[-1])
    assert len(work('14').task.splitlines()) >= 32
    assert work('15').date_filled is None and work('15').academic_year == academic_year(date.today())
    assert work('05').student.group.code == '007-ПМИ/01'
    assert work('05').student.email.count('+') == 1
    assert work('03').student.middle_name == '' and work('03').student.first_name == 'Ван Тхань'
    assert work('02').schedule == '' and work('02').achievements.count() == 0
    assert work('04').status_comment == 'Выполняется п. 1 (обзор литературы)'
    assert StudyGroup.objects.filter(code='ПМИ-51').count() == 1  # 06 и 11 — одна группа


@pytest.mark.django_db
def test_save_ready_rematches(responsible):
    batch = upload(responsible, '01', '11')
    assert save_ready(batch.documents.order_by('id'), responsible) == (0, 2)
    save_document(doc(batch, '01'), default_decision(analyze(doc(batch, '01'))), responsible)
    assert save_ready(batch.documents.order_by('id'), responsible) == (1, 0)
    assert Teacher.objects.get().works.count() == 2


@pytest.mark.django_db
def test_return_texts(responsible):
    batch = upload(responsible, '09', '20')
    nine, twenty = doc(batch, '09'), doc(batch, '20')
    assert '1. Дата заполнения' in nine.return_message and '2. Электронная почта' in nine.return_message
    assert 'например student@example.org' in nine.return_message
    assert 'Печать → Сохранить как PDF' in nine.return_message
    assert 'новую копию' in twenty.return_message and twenty.student_name in twenty.return_message
    assert twenty.student_name
    mark_returned(nine, responsible)
    nine.refresh_from_db()
    assert nine.state == DocState.RETURNED and nine.returned_by == responsible and nine.returned_at


@pytest.mark.django_db
def test_duplicate_and_resubmission(responsible):
    batch = upload(responsible, '10')
    returned = doc(batch, '10')
    again = upload(responsible, '10').documents.get()
    assert again.state == DocState.DUPLICATE and again.duplicate_of == returned

    fixed = pdfs.with_values((EXAMPLES / '10-missing-required.pdf').read_bytes(),
                             {'student.phone': '+7 (900) 000-00-10', 'student.task': 'Исправленная задача.'})
    new = create_batch(responsible, [Incoming('10-fixed.pdf', fixed)]).documents.get()
    assert new.state == DocState.PENDING
    returned.refresh_from_db()
    assert returned.resubmission == new


@pytest.mark.django_db
def test_rejected_and_old_versions(responsible):
    blank = (EXAMPLES / '01-full.pdf').read_bytes()
    files = [
        Incoming('plain.pdf', pdfs.plain_pdf()),
        Incoming('text.pdf', b'not a pdf'),
        Incoming('xfa.pdf', pdfs.with_xfa(blank)),
        Incoming('draft01.pdf', pdfs.with_values(blank, {'meta.schema_version': '1.0'})),
        Incoming('other.pdf', pdfs.with_values(blank, {'meta.form_id': 'another_form'})),
        Incoming('future.pdf', pdfs.with_values(blank, {'meta.schema_version': '3.0'})),
    ]
    states = {d.original_name: d.state for d in create_batch(responsible, files).documents.all()}
    assert states == {'plain.pdf': DocState.REJECTED_CHECK, 'text.pdf': DocState.REJECTED_CHECK,
                      'xfa.pdf': DocState.TO_RETURN, 'draft01.pdf': DocState.TO_RETURN,
                      'other.pdf': DocState.REJECTED_CHECK, 'future.pdf': DocState.UNSUPPORTED}
    xfa = ImportedDocument.objects.get(original_name='xfa.pdf')
    assert 'устаревшей версии' in xfa.return_message


@pytest.mark.django_db
def test_background_batch(responsible, settings):
    settings.IMPORT_SYNC_LIMIT = 2
    batch = upload(responsible, '01', '02', '03')
    assert batch.background and batch.documents.filter(state=DocState.QUEUED).count() == 3
    from imports.processing import process_queue
    assert process_queue() == 3
    assert batch.documents.filter(state=DocState.PENDING).count() == 3
