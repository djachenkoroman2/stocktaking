"""Запись подтверждённой анкеты в рабочие таблицы (ТЗ 7.1, 7.5, 7.6)."""
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from registry import status as statuses
from registry.models import Achievement, Department, ResearchWork, Student, StudyGroup, Teacher

from .matching import analyze
from .models import DocState


class ApplyError(Exception):
    pass


@dataclass
class Decision:
    teacher_id: int | None = None
    new_teacher: dict | None = None        # last_name, first_name, middle_name, position
    department_id: int | None = None       # кафедра нового преподавателя
    new_department_name: str = ''
    add_alias: bool = False                # запомнить написание кафедры из анкеты
    student_id: int | None = None          # None — создать нового
    update_student: bool = True
    course: int | None = None
    status: str = statuses.DEFAULT
    status_note: str = ''
    keep_fields: set = field(default_factory=set)
    remove_achievements: set = field(default_factory=set)
    confirm_reuse: bool = False
    note: str = ''


def default_decision(analysis):
    decision = Decision(course=analysis.course)
    if analysis.teacher is not None:
        decision.teacher_id = analysis.teacher.id
    elif analysis.teacher_source == 'new':
        last, first, middle = analysis.parsed_teacher
        decision.new_teacher = {'last_name': last, 'first_name': first, 'middle_name': middle,
                                'position': analysis.data.teacher_position}
        if analysis.department is not None:
            decision.department_id = analysis.department.id
        else:
            decision.new_department_name = analysis.data.teacher_department
    if analysis.student is not None:
        decision.student_id = analysis.student.id
    if analysis.work is not None:
        decision.status = analysis.work.status
    return decision


def _tag(obj, document):
    obj._change_reason = f'Загрузка PDF №{document.pk}'
    return obj


def _resolve_teacher(decision, analysis, document):
    if decision.teacher_id:
        teacher = Teacher.objects.select_related('department').get(pk=decision.teacher_id)
    elif decision.new_teacher:
        values = {k: (v or '').strip() for k, v in decision.new_teacher.items()}
        if not values.get('last_name') or not values.get('first_name'):
            raise ApplyError('Для нового преподавателя укажите фамилию и имя.')
        if decision.department_id:
            department = Department.objects.get(pk=decision.department_id)
        elif decision.new_department_name.strip():
            name = decision.new_department_name.strip()
            department = next((d for d in Department.objects.all() if d.matches(name)), None) \
                or Department.objects.create(name=name)
        else:
            raise ApplyError('Для нового преподавателя выберите кафедру или укажите название новой.')
        teacher = _tag(Teacher(department=department, **values), document)
        teacher.save()
    else:
        raise ApplyError('Выберите преподавателя или создайте нового.')
    text = analysis.data.teacher_department
    if decision.add_alias and text and not teacher.department.matches(text):
        teacher.department.aliases = [*teacher.department.aliases, text]
        teacher.department.save(update_fields=['aliases'])
    return teacher


def _resolve_group(analysis):
    if analysis.group is not None:
        return analysis.group
    code = analysis.data.group_code
    return next((g for g in StudyGroup.objects.filter(code__iexact=code)), None) \
        or StudyGroup.objects.create(code=code)


def _resolve_student(decision, analysis, group, document):
    data = analysis.data
    values = {'last_name': data.last_name, 'first_name': data.first_name, 'middle_name': data.middle_name,
              'group': group, 'phone': data.phone, 'email': data.email}
    if decision.student_id:
        student = Student.objects.get(pk=decision.student_id)
        if decision.update_student:
            for name, value in values.items():
                setattr(student, name, value)
            if decision.course is not None:
                student.course = decision.course
            _tag(student, document).save()
        return student
    student = _tag(Student(course=decision.course, **values), document)
    student.save()
    return student


def _apply_work(decision, analysis, teacher, student, document, user):
    data = analysis.data
    work = analysis.work
    new_values = {'task': data.task, 'schedule': data.schedule, 'expected_results': data.expected_results,
                  'status_comment': data.status_comment, 'notes': data.notes, 'course_at_filling': data.course_raw}
    if work is None:
        if ResearchWork.objects.filter(questionnaire_id=data.questionnaire_id).exists():
            raise ApplyError('Работа с этим ID анкеты уже есть (возможно, удалена). Восстановите её.')
        work = ResearchWork(questionnaire_id=data.questionnaire_id, source=ResearchWork.Source.PDF,
                            created_by=user, status=decision.status, date_filled=data.date_filled, **new_values)
    else:
        error = statuses.check_transition(work.status, decision.status, decision.status_note)
        if error:
            raise ApplyError(error)
        work.status = decision.status
        for name, value in new_values.items():
            if name not in decision.keep_fields:
                setattr(work, name, value)
        if data.date_filled and 'date_filled' not in decision.keep_fields:
            work.date_filled = data.date_filled
    if decision.status_note.strip():
        work.status_comment = decision.status_note.strip()[:500]
    work.teacher = teacher
    work.student = student
    work.updated_by = user
    work.last_import_snapshot = {name: getattr(work, name) for name in new_values}
    _tag(work, document).save()

    existing = {a.source_row: a for a in work.achievements.all() if a.source_row is not None}
    rows = dict(data.achievements)
    for row, text in rows.items():
        if row in existing:
            if existing[row].text != text:
                existing[row].text = text
                _tag(existing[row], document).save()
        else:
            _tag(Achievement(work=work, text=text, source_row=row, order=row), document).save()
    for row, achievement in existing.items():
        if row not in rows and achievement.id in decision.remove_achievements:
            _tag(achievement, document).delete()
    return work


@transaction.atomic
def save_document(document, decision, user):
    """Записать анкету. Анализ выполняется заново внутри транзакции."""
    document.refresh_from_db()
    if document.state != DocState.PENDING:
        raise ApplyError('Эта загрузка уже обработана.')
    analysis = analyze(document)
    reuse_warning = any('переиспользована' in w for w in analysis.warnings)
    if reuse_warning and not decision.confirm_reuse:
        raise ApplyError('Подтвердите обновление работы другим студентом или отклоните анкету.')
    if decision.status not in statuses.WorkStatus.values:
        raise ApplyError('Неизвестный статус.')
    teacher = _resolve_teacher(decision, analysis, document)
    group = _resolve_group(analysis)
    student = _resolve_student(decision, analysis, group, document)
    work = _apply_work(decision, analysis, teacher, student, document, user)
    if analysis.copy is not None:
        analysis.copy.work = work
        if analysis.copy.student_id is None:
            analysis.copy.student = student
        analysis.copy.save(update_fields=['work', 'student'])
    document.state = DocState.SAVED
    document.work = work
    document.department = teacher.department
    document.processed_by = user
    document.processed_at = timezone.now()
    document.decision_note = decision.note
    document.save()
    return work


def is_ready(analysis):
    """«Готово»: сохраняется без открытия предпросмотра (ТЗ 7.2)."""
    return not analysis.needs_decision and analysis.teacher is not None


def save_ready(documents, user):
    """«Сохранить все готовые»: по умолчанию новая работа — «В работе», обновляемая сохраняет статус."""
    saved, skipped = 0, 0
    for document in documents:
        if document.state != DocState.PENDING:
            continue
        analysis = analyze(document)
        if not is_ready(analysis):
            skipped += 1
            continue
        save_document(document, default_decision(analysis), user)
        saved += 1
    return saved, skipped


def reject_document(document, user, note):
    if not note.strip():
        raise ApplyError('Укажите причину отклонения.')
    document.state = DocState.REJECTED_USER
    document.decision_note = note.strip()
    document.processed_by = user
    document.processed_at = timezone.now()
    document.save()
