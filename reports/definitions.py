"""Определения 10 отчётов (ТЗ 9). Контакты студентов есть только в отчёте 7 (ТЗ 3.2)."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Max
from django.utils import timezone

from imports.models import DocState, IssuedCopy
from registry.models import Achievement
from registry.status import ACTIVE, WorkStatus
from registry.text import norm


@dataclass
class Section:
    title: str
    columns: list
    rows: list
    totals: list | None = None


@dataclass
class Result:
    sections: list = field(default_factory=list)
    params: list = field(default_factory=list)  # [(подпись, значение)]
    summary: list = field(default_factory=list)  # [(подпись, значение)]


HTML, XLSX, CSV, PDF = 'html', 'xlsx', 'csv', 'pdf'


@dataclass
class ReportDef:
    slug: str
    number: int
    title: str
    formats: tuple
    params: tuple = ()           # дополнительные параметры формы
    allowed: str = 'view'        # view | import | contacts
    common: bool = True          # общие параметры: учебный год, период, кафедра, неактивные

    def available(self, access):
        if self.allowed == 'contacts':
            return access.is_responsible
        if self.allowed == 'import':
            return access.can_import
        return access.has_any_role


def _base_works(access, p):
    works = access.works().select_related('teacher__department', 'student__group')
    if p.get('department'):
        works = works.filter(teacher__department=p['department'])
    if p.get('year'):
        works = works.filter(academic_year=p['year'])
    if p.get('date_from'):
        works = works.filter(date_filled__gte=p['date_from'])
    if p.get('date_to'):
        works = works.filter(date_filled__lte=p['date_to'])
    if not p.get('include_inactive'):
        works = works.filter(status__in=ACTIVE, student__is_active=True)
    return works


def _date(value):
    return value.strftime('%d.%m.%Y') if value else ''


def _achievement_texts(work):
    return '\n'.join(f'{i}. {a.text}' for i, a in enumerate(work.achievements.all(), 1))


def teacher_card(access, p):
    teacher = p['teacher']
    works = _base_works(access, p).filter(teacher=teacher).prefetch_related('achievements')
    rows = [[w.student.full_name, str(w.student.group), w.student.course or '', w.task, w.get_status_display(),
             w.expected_results, w.achievements.count(), _achievement_texts(w), _date(w.date_filled)]
            for w in works.order_by('student__last_name')]
    return Result(sections=[Section('Работы', ['Студент', 'Группа', 'Курс', 'Задача', 'Статус', 'Ожидаемые результаты',
                                               'Достижений', 'Достижения', 'Дата последней анкеты'], rows)],
                  summary=[('Преподаватель', teacher.full_name), ('Должность', teacher.position),
                           ('Кафедра', str(teacher.department)), ('Работ', len(rows))])


def department_summary(access, p):
    works = list(_base_works(access, p).annotate(n_ach=Count('achievements')))
    by_teacher = defaultdict(list)
    for work in works:
        by_teacher[work.teacher].append(work)
    statuses = list(WorkStatus)
    rows, totals = [], [0] * (len(statuses) + 2)
    for teacher in sorted(by_teacher, key=lambda t: (str(t.department), t.full_name)):
        items = by_teacher[teacher]
        active = len({w.student_id for w in items if w.status in ACTIVE})
        counts = Counter(w.status for w in items)
        values = [active] + [counts.get(s.value, 0) for s in statuses] + [sum(w.n_ach for w in items)]
        totals = [a + b for a, b in zip(totals, values)]
        rows.append([teacher.full_name, teacher.position, str(teacher.department)] + values)
    columns = ['Преподаватель', 'Должность', 'Кафедра', 'Активных студентов'] + [s.label for s in statuses] \
        + ['Достижений']
    return Result(sections=[Section('Сводка', columns, rows, ['Итого', '', ''] + totals)])


def students_by_course(access, p):
    works = _base_works(access, p)
    if p.get('course'):
        works = works.filter(student__course=p['course'])
    if p.get('group'):
        works = works.filter(student__group=p['group'])
    works = works.order_by('student__course', 'student__group__code', 'student__last_name')
    rows = [[w.student.course or '', str(w.student.group), w.student.full_name, w.teacher.short_name, w.title,
             w.get_status_display()] for w in works]
    return Result(sections=[Section('Студенты', ['Курс', 'Группа', 'Студент', 'Преподаватель', 'Тема', 'Статус'], rows)])


def works_by_status(access, p):
    works = _base_works(access, {**p, 'include_inactive': True})
    selected = p.get('statuses') or []
    if selected:
        works = works.filter(status__in=selected)
    if p.get('active_only'):
        works = works.filter(status__in=ACTIVE)
    order = {s.value: i for i, s in enumerate(WorkStatus)}
    works = sorted(works, key=lambda w: (order[w.status], w.student.last_name))
    rows = [[w.get_status_display(), w.student.full_name, str(w.student.group), w.teacher.short_name, w.status_comment,
             _date(timezone.localtime(w.updated_at))] for w in works]
    counts = Counter(w.get_status_display() for w in works)
    totals = Section('Итоги по статусам', ['Статус', 'Работ'],
                     [[s.label, counts.get(s.label, 0)] for s in WorkStatus if counts.get(s.label)])
    return Result(sections=[Section('Работы', ['Статус', 'Студент', 'Группа', 'Преподаватель', 'Комментарий к статусу',
                                               'Обновлено'], rows), totals])


def achievements(access, p):
    works = _base_works(access, {**p, 'include_inactive': True})
    if p.get('teacher'):
        works = works.filter(teacher=p['teacher'])
    items = (Achievement.objects.filter(work__in=works)
             .select_related('work__student__group', 'work__teacher__department')
             .order_by('work__teacher__last_name', 'work__student__last_name', 'order'))
    rows = [[a.text, a.work.student.full_name, str(a.work.student.group), a.work.teacher.short_name,
             str(a.work.teacher.department), a.work.academic_year] for a in items]
    per_teacher = Counter(row[3] for row in rows)
    return Result(sections=[
        Section('Достижения', ['Достижение', 'Студент', 'Группа', 'Преподаватель', 'Кафедра', 'Учебный год'], rows),
        Section('Итоги по преподавателям', ['Преподаватель', 'Достижений'],
                sorted(([k, v] for k, v in per_teacher.items()), key=lambda r: -r[1]),
                ['Итого', len(rows)])])


def teacher_load(access, p):
    works = list(_base_works(access, {**p, 'include_inactive': True}))
    data = defaultdict(lambda: {'students': set(), 'works': 0, 'completed': 0})
    for work in works:
        entry = data[work.teacher]
        entry['works'] += 1
        if work.status in ACTIVE and work.student.is_active:
            entry['students'].add(work.student_id)
        if work.status == WorkStatus.COMPLETED:
            entry['completed'] += 1
    minimum = p.get('min_students') or 0
    rows = [[t.full_name, str(t.department), len(v['students']), v['works'], v['completed']]
            for t, v in data.items() if len(v['students']) >= minimum]
    rows.sort(key=lambda r: (-r[2], r[0]))
    return Result(sections=[Section('Нагрузка', ['Преподаватель', 'Кафедра', 'Активных студентов', 'Работ',
                                                 'Из них завершённых'], rows)])


def contacts(access, p):
    teacher = p['teacher']
    works = _base_works(access, p).filter(teacher=teacher).order_by('student__last_name')
    seen, rows = set(), []
    for work in works:
        student = work.student
        if student.pk in seen or not access.can_see_contacts(student):
            continue
        seen.add(student.pk)
        rows.append([student.full_name, str(student.group), student.phone, student.email])
    return Result(sections=[Section('Контакты', ['Студент', 'Группа', 'Телефон', 'Email'], rows)],
                  summary=[('Преподаватель', teacher.full_name)])


def collection(access, p):
    documents = access.documents()
    teachers = access.teachers(edit=True)
    copies = IssuedCopy.objects.filter(teacher__in=teachers).select_related('teacher', 'student')
    if p.get('department'):
        copies = copies.filter(teacher__department=p['department'])
        documents = documents.filter(department=p['department'])
    last_upload = dict(documents.exclude(questionnaire_id='').values('questionnaire_id')
                       .annotate(last=Max('uploaded_at')).values_list('questionnaire_id', 'last'))
    last_state = {}
    for qid, state in documents.exclude(questionnaire_id='').order_by('uploaded_at').values_list(
            'questionnaire_id', 'state'):
        last_state[qid] = state
    labels = dict(DocState.choices)
    state_filter = p.get('state')
    copy_rows = []
    for copy in copies.order_by('teacher__last_name', 'issued_at'):
        state = last_state.get(copy.questionnaire_id, '')
        label = labels.get(state, 'Не получена')
        if state_filter and state_filter != (state or 'none'):
            continue
        copy_rows.append([copy.teacher.short_name, copy.student.full_name if copy.student else '',
                          _date(timezone.localtime(copy.issued_at)),
                          _date(timezone.localtime(last_upload[copy.questionnaire_id]))
                          if copy.questionnaire_id in last_upload else '', label])
    returned = documents.filter(state=DocState.RETURNED, resubmission__isnull=True).order_by('returned_at')
    today = timezone.now()
    returned_rows = [[d.teacher_name, d.student_name, d.original_name, _date(timezone.localtime(d.returned_at)),
                      (today - d.returned_at).days if d.returned_at else ''] for d in returned]
    counts = Counter(documents.values_list('state', flat=True))
    received = len([c for c in copies if c.questionnaire_id in last_upload])
    summary = [('Выдано копий', copies.count()), ('Получено по выданным копиям', received),
               ('Ожидает решения', counts.get(DocState.PENDING, 0)), ('К возврату', counts.get(DocState.TO_RETURN, 0)),
               ('Возвращено и не получено повторно', len(returned_rows)),
               ('Отклонено', counts.get(DocState.REJECTED_CHECK, 0) + counts.get(DocState.REJECTED_USER, 0))]
    return Result(summary=summary, sections=[
        Section('Выданные копии', ['Преподаватель', 'Студент', 'Выдана', 'Последняя загрузка', 'Состояние'], copy_rows),
        Section('Возвращённые анкеты без повторной загрузки', ['Преподаватель', 'Студент', 'Файл', 'Возвращена',
                                                               'Дней с возврата'], returned_rows)])


def quality(access, p):
    works = _base_works(access, p)
    stale_before = timezone.now() - timedelta(days=p.get('stale_days') or settings.STALE_WORK_DAYS)

    def work_rows(qs):
        return [[w.student.full_name, w.teacher.short_name, w.get_status_display(),
                 _date(timezone.localtime(w.updated_at))] for w in qs.order_by('student__last_name')]

    columns = ['Студент', 'Преподаватель', 'Статус', 'Обновлено']
    sections = [
        Section('Работы без достижений', columns, work_rows(works.annotate(n=Count('achievements')).filter(n=0))),
        Section('Работы без расписания', columns, work_rows(works.filter(schedule=''))),
        Section('Работы без даты заполнения', columns, work_rows(works.filter(date_filled__isnull=True))),
        Section(f'Не обновлялись больше {p.get("stale_days") or settings.STALE_WORK_DAYS} дней', columns,
                work_rows(works.filter(updated_at__lt=stale_before, status__in=ACTIVE))),
    ]
    if access.can_import:
        docs = access.documents().filter(state=DocState.SAVED).exclude(warnings=[]).select_related('work')
        sections.append(Section('Сохранённые анкеты с предупреждениями', ['Файл', 'Студент', 'Предупреждения'],
                                [[d.original_name, d.student_name, '\n'.join(d.warnings)] for d in docs]))
    groups = defaultdict(list)
    for student in access.students().filter(is_active=True).select_related('group'):
        groups[norm(student.full_name)].append(student)
    duplicates = [[s.full_name, str(s.group), len(items)] for items in groups.values() if len(items) > 1 for s in items]
    sections.append(Section('Возможные дубликаты студентов (одинаковые ФИО)', ['Студент', 'Группа', 'Записей'],
                            duplicates))
    return Result(sections=sections)


def import_journal(access, p):
    documents = access.documents().select_related('uploaded_by', 'work')
    if p.get('batch'):
        documents = documents.filter(batch_id=p['batch'])
    if p.get('author'):
        documents = documents.filter(uploaded_by__username__icontains=p['author'])
    if p.get('state'):
        documents = documents.filter(state=p['state'])
    if p.get('date_from'):
        documents = documents.filter(uploaded_at__date__gte=p['date_from'])
    if p.get('date_to'):
        documents = documents.filter(uploaded_at__date__lte=p['date_to'])
    rows = [[timezone.localtime(d.uploaded_at).strftime('%d.%m.%Y %H:%M'), d.uploaded_by.username if d.uploaded_by else '',
             d.original_name, d.questionnaire_id, d.get_state_display(),
             '\n'.join(d.errors + d.warnings), f'№{d.work_id}' if d.work_id else '']
            for d in documents.order_by('-uploaded_at')]
    return Result(sections=[Section('Загрузки', ['Дата', 'Автор', 'Файл', 'ID анкеты', 'Состояние',
                                                 'Ошибки и предупреждения', 'Работа'], rows)])


BUILDERS = {
    'teacher_card': teacher_card, 'department_summary': department_summary, 'students_by_course': students_by_course,
    'works_by_status': works_by_status, 'achievements': achievements, 'teacher_load': teacher_load,
    'contacts': contacts, 'collection': collection, 'quality': quality, 'import_journal': import_journal,
}

REPORTS = [
    ReportDef('teacher_card', 1, 'Карточка преподавателя', (HTML, PDF, XLSX), ('teacher',)),
    ReportDef('department_summary', 2, 'Сводка по кафедре', (HTML, XLSX, CSV, PDF)),
    ReportDef('students_by_course', 3, 'Студенты по курсам и группам', (HTML, XLSX, CSV), ('course', 'group')),
    ReportDef('works_by_status', 4, 'Работы по статусу', (HTML, XLSX, CSV), ('statuses', 'active_only')),
    ReportDef('achievements', 5, 'Достижения за учебный год', (HTML, XLSX, CSV, PDF), ('teacher_optional',)),
    ReportDef('teacher_load', 6, 'Нагрузка преподавателей', (HTML, XLSX, CSV), ('min_students',)),
    ReportDef('contacts', 7, 'Контакты студентов преподавателя', (HTML, XLSX), ('teacher',), allowed='contacts'),
    ReportDef('collection', 8, 'Сбор анкет', (HTML, XLSX), ('department', 'copy_state'), allowed='import',
              common=False),
    ReportDef('quality', 9, 'Качество данных', (HTML, XLSX), ('stale_days',)),
    ReportDef('import_journal', 10, 'Журнал импорта', (HTML, CSV), ('batch', 'author', 'doc_state', 'period'),
              allowed='import', common=False),
]
BY_SLUG = {r.slug: r for r in REPORTS}


def build(report, access, params):
    return BUILDERS[report.slug](access, params)
