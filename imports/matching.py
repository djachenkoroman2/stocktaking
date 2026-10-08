"""Сопоставление анкеты с существующими записями (ТЗ 7.5) и разница при повторной загрузке (ТЗ 7.6).

Анализ ничего не записывает в базу; он вычисляется заново при каждом открытии предпросмотра, поэтому
записи, созданные при подтверждении одного файла пакета, находятся для следующих (ТЗ 7.1, п. 7).
"""
from dataclasses import dataclass, field
import re

from registry.models import Department, ResearchWork, Student, StudyGroup, Teacher
from registry.text import norm, split_full_name, suggest_course

from .adapters import ImportData, to_neutral
from .models import IssuedCopy

COURSE_RE = re.compile(r'^[1-6]$')

WORK_FIELD_LABELS = {
    'task': 'Задача',
    'schedule': 'Расписание',
    'expected_results': 'Ожидаемые результаты',
    'status_comment': 'Комментарий к статусу',
    'notes': 'Примечание',
    'course_at_filling': 'Курс по анкете',
    'date_filled': 'Дата заполнения',
}
STUDENT_FIELD_LABELS = {
    'last_name': 'Фамилия', 'first_name': 'Имя', 'middle_name': 'Отчество', 'group': 'Группа',
    'course': 'Курс', 'phone': 'Телефон', 'email': 'Email',
}


@dataclass
class FieldDiff:
    field: str
    label: str
    old: object
    new: object
    manual: bool = False  # поле меняли вручную после прошлого импорта


@dataclass
class Analysis:
    data: ImportData
    copy: IssuedCopy | None = None
    work: ResearchWork | None = None
    teacher: Teacher | None = None
    teacher_source: str = ''
    teacher_candidates: list = field(default_factory=list)
    department: Department | None = None
    parsed_teacher: tuple = ('', '', '')
    group: StudyGroup | None = None
    student: Student | None = None
    student_source: str = ''
    student_candidates: list = field(default_factory=list)
    student_diff: list = field(default_factory=list)
    course: int | None = None
    course_warning: bool = False
    work_diff: list = field(default_factory=list)
    achievements_update: list = field(default_factory=list)
    achievements_add: list = field(default_factory=list)
    achievements_remove: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    reasons: list = field(default_factory=list)

    @property
    def needs_decision(self):
        return bool(self.reasons)

    @property
    def target_department(self):
        if self.teacher is not None:
            return self.teacher.department
        return self.department


def find_department(text):
    key = norm(text)
    if not key:
        return None
    for department in Department.objects.all():
        if department.matches(text):
            return department
    return None


def find_group(code):
    key = norm(code)
    for group in StudyGroup.objects.filter(code__iexact=code.strip()):
        return group
    for group in StudyGroup.objects.all():  # ё/е, неразрывные пробелы
        if norm(group.code) == key:
            return group
    return None


def _active_teachers():
    return Teacher.objects.filter(is_active=True, merged_into__isnull=True).select_related('department')


def _match_teacher(result, data):
    if data.teacher_full_name == '':
        result.teacher_source = 'empty'
        result.reasons.append('В анкете не указан преподаватель: выберите его.')
        result.teacher_candidates = []
        return
    key = norm(data.teacher_full_name)
    result.department = find_department(data.teacher_department)
    result.parsed_teacher = split_full_name(data.teacher_full_name)
    teachers = list(_active_teachers())
    by_name = [t for t in teachers if t.name_key == key]
    exact = [t for t in by_name if result.department and t.department_id == result.department.id]
    if len(exact) == 1:
        result.teacher, result.teacher_source = exact[0], 'exact'
        return
    last_key = norm(result.parsed_teacher[0])
    similar = by_name or [t for t in teachers if norm(t.last_name) == last_key
                          and (result.department is None or t.department_id == result.department.id)]
    if similar:
        result.teacher_source = 'candidates'
        result.teacher_candidates = similar
        result.reasons.append('Преподаватель найден неоднозначно: выберите из списка или создайте нового.')
    else:
        result.teacher_source = 'new'
        result.reasons.append('Преподаватель не найден: проверьте разбор ФИО и создайте запись.')
    if result.department is None and data.teacher_department:
        result.notes.append(f'Кафедра «{data.teacher_department}» не найдена.')


def _student_key(last, first, middle):
    return norm(' '.join((last, first, middle)))


def _match_student(result, data):
    key = _student_key(data.last_name, data.first_name, data.middle_name)
    if result.work is not None:
        student = result.work.student
        result.student, result.student_source = student, 'work'
        if _student_key(student.last_name, student.first_name, student.middle_name) != key \
                and norm(student.group.code) != norm(data.group_code):
            result.warnings.append('Анкета, вероятно, переиспользована для другого студента: '
                                   'ФИО и группа отличаются от сохранённых.')
            result.reasons.append('Подтвердите обновление работы другим студентом или отклоните анкету.')
        return
    if result.copy is not None and result.copy.student_id:
        result.student, result.student_source = result.copy.student, 'copy'
        return
    students = Student.objects.filter(is_active=True, merged_into__isnull=True).select_related('group')
    by_name = [s for s in students if _student_key(s.last_name, s.first_name, s.middle_name) == key]
    exact = [s for s in by_name if norm(s.group.code) == norm(data.group_code)]
    if len(exact) == 1:
        result.student, result.student_source = exact[0], 'exact'
        return
    email_key = norm(data.email)
    by_email = [s for s in students if email_key and norm(s.email) == email_key]
    if len(exact) == 0 and len(by_email) == 1 and by_email[0] in by_name:
        result.student, result.student_source = by_email[0], 'email'
        return
    candidates = exact or (by_name + [s for s in by_email if s not in by_name])
    if candidates:
        result.student_source = 'candidates'
        result.student_candidates = candidates
        result.reasons.append('Найдены похожие студенты: выберите существующего или создайте нового.')
    else:
        result.student_source = 'new'


def _course(result, data):
    raw = data.course_raw
    if not raw:
        result.course = None
    elif COURSE_RE.match(raw):
        result.course = int(raw)
    else:
        result.course = suggest_course(raw)
        result.course_warning = True
        result.reasons.append(f'Курс «{raw}» — не целое число от 1 до 6: подтвердите предложенное значение.')


def _student_diff(result, data):
    student = result.student
    if student is None:
        return
    new_values = {'last_name': data.last_name, 'first_name': data.first_name, 'middle_name': data.middle_name,
                  'group': data.group_code, 'phone': data.phone, 'email': data.email}
    old_values = {'last_name': student.last_name, 'first_name': student.first_name,
                  'middle_name': student.middle_name, 'group': student.group.code, 'phone': student.phone,
                  'email': student.email}
    for name, new in new_values.items():
        if norm(new) != norm(old_values[name]) or (new != old_values[name] and name in ('phone', 'email')):
            result.student_diff.append(FieldDiff(name, STUDENT_FIELD_LABELS[name], old_values[name], new))
    if result.course is not None and result.course != student.course:
        result.student_diff.append(FieldDiff('course', 'Курс', student.course, result.course))


def _work_diff(result, data):
    work = result.work
    new_values = {'task': data.task, 'schedule': data.schedule, 'expected_results': data.expected_results,
                  'status_comment': data.status_comment, 'notes': data.notes, 'course_at_filling': data.course_raw}
    snapshot = work.last_import_snapshot or {}
    for name, new in new_values.items():
        old = getattr(work, name)
        if old != new:
            manual = name in snapshot and snapshot[name] != old
            result.work_diff.append(FieldDiff(name, WORK_FIELD_LABELS[name], old, new, manual))
    if data.date_filled and data.date_filled != work.date_filled:
        result.work_diff.append(FieldDiff('date_filled', WORK_FIELD_LABELS['date_filled'], work.date_filled,
                                          data.date_filled))
        if work.date_filled and data.date_filled < work.date_filled:
            result.warnings.append('Загружается более старая версия анкеты: дата заполнения раньше сохранённой.')
            result.reasons.append('Подтвердите загрузку более старой версии анкеты.')
    if any(diff.manual for diff in result.work_diff):
        result.reasons.append('Поля, изменённые вручную после прошлой загрузки, отличаются от анкеты: '
                              'выберите, какое значение оставить.')
    existing = {a.source_row: a for a in work.achievements.all() if a.source_row is not None}
    rows = {row: text for row, text in data.achievements}
    for row, text in rows.items():
        if row in existing:
            if existing[row].text != text:
                result.achievements_update.append((existing[row], text))
        else:
            result.achievements_add.append((row, text))
    result.achievements_remove = [a for row, a in sorted(existing.items()) if row not in rows]
    if result.achievements_remove:
        result.reasons.append('В анкете очищены строки портфолио: подтвердите удаление достижений.')


def analyze(document):
    data = to_neutral(document)
    result = Analysis(data=data)
    if data.questionnaire_id:
        result.copy = IssuedCopy.objects.select_related('teacher__department', 'student').filter(
            questionnaire_id=data.questionnaire_id).first()
        result.work = ResearchWork.objects.alive().select_related('teacher__department', 'student__group').filter(
            questionnaire_id=data.questionnaire_id).first()
    if result.work is not None:
        result.teacher, result.teacher_source = result.work.teacher, 'work'
    elif result.copy is not None:
        result.teacher, result.teacher_source = result.copy.teacher, 'copy'
        if data.teacher_full_name and norm(data.teacher_full_name) != result.teacher.name_key:
            result.warnings.append(f'ФИО преподавателя в анкете («{data.teacher_full_name}») отличается от '
                                   f'выданной копии ({result.teacher.full_name}).')
    else:
        _match_teacher(result, data)

    result.group = find_group(data.group_code)
    if result.group is None:
        result.notes.append(f'Новая группа «{data.group_code}» будет создана.')
    _course(result, data)
    _match_student(result, data)
    _student_diff(result, data)
    if result.work is not None:
        _work_diff(result, data)
    if not data.date_filled:
        result.notes.append('Дата заполнения не указана: учебный год определяется по дате загрузки.')
    result.warnings = list(document.warnings) + result.warnings
    return result
