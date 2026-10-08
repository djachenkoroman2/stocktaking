"""Справочники, работы, история (ТЗ 6, 10)."""
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.access import access_for
from accounts.audit import log
from imports.models import DocState, ImportedDocument

from . import status as statuses
from .forms import (AchievementFormSet, DepartmentForm, GroupForm, MergeForm, StatusForm, StudentForm, TeacherForm,
                    WorkForm)
from .history import history_entries
from .models import Department, ResearchWork, Student
from .status import WorkStatus


def paginate(request, qs, size=50):
    return Paginator(qs, size).get_page(request.GET.get('page'))


def _scoped(qs, pk):
    obj = qs.filter(pk=pk).first()
    if obj is None:
        raise Http404
    return obj


def dashboard(request):
    access = access_for(request)
    works = access.works()
    by_status = dict(works.values_list('status').annotate(n=Count('id')))
    context = {
        'status_counts': [(s, by_status.get(s.value, 0)) for s in WorkStatus],
        'total_works': works.count(),
        'recent': ResearchWork.history.filter(id__in=works.values('id')).select_related('history_user')[:10],
        'no_role': not access.has_any_role,
    }
    if access.can_import:
        docs = access.documents()
        context.update(pending=docs.filter(state=DocState.PENDING).count(),
                       to_return=docs.filter(state=DocState.TO_RETURN).count(),
                       returned=docs.filter(state=DocState.RETURNED, resubmission__isnull=True).count(),
                       queued=docs.filter(state=DocState.QUEUED).count())
    return render(request, 'registry/dashboard.html', context)


# Работы

def work_list(request):
    access = access_for(request)
    show_deleted = request.GET.get('deleted') == '1' and access.is_admin
    qs = access.works(ResearchWork.objects.filter(is_deleted=show_deleted))
    qs = qs.select_related('teacher__department', 'student__group')
    f = request.GET
    if f.get('department'):
        qs = qs.filter(teacher__department_id=f['department'])
    if f.get('teacher'):
        qs = qs.filter(teacher_id=f['teacher'])
    if f.get('course'):
        qs = qs.filter(student__course=f['course'])
    if f.get('group'):
        qs = qs.filter(student__group_id=f['group'])
    if f.get('status'):
        qs = qs.filter(status=f['status'])
    if f.get('year'):
        qs = qs.filter(academic_year=f['year'])
    if f.get('q'):
        q = f['q'].strip()
        condition = (Q(student__last_name__icontains=q) | Q(student__first_name__icontains=q)
                     | Q(teacher__last_name__icontains=q) | Q(student__group__code__icontains=q)
                     | Q(task__icontains=q) | Q(questionnaire_id__icontains=q))
        if access.can_see_any_contacts:  # поиск по контактам — только ответственным (ТЗ 3.2)
            condition |= Q(student__phone__icontains=q, teacher__department_id__in=_contact_ids(access)) \
                | Q(student__email__icontains=q, teacher__department_id__in=_contact_ids(access))
        qs = qs.filter(condition)
    context = {
        'page': paginate(request, qs.order_by('student__last_name', 'student__first_name')),
        'departments': access.departments(), 'teachers': access.teachers().filter(is_active=True),
        'groups': access.groups(), 'statuses': WorkStatus.choices,
        'years': ResearchWork.objects.alive().order_by('-academic_year').values_list('academic_year', flat=True).distinct(),
        'filters': f, 'show_deleted': show_deleted,
    }
    return render(request, 'registry/work_list.html', context)


def _contact_ids(access):
    scope = access.contact_scope
    return Department.objects.values('id') if scope is None else list(scope)


def work_detail(request, pk):
    access = access_for(request)
    qs = ResearchWork.objects.all() if access.is_admin else access.works()
    work = _scoped(qs.select_related('teacher__department', 'student__group'), pk)
    documents = access.documents(ImportedDocument.objects.filter(
        Q(work=work) | Q(questionnaire_id=work.questionnaire_id) if work.questionnaire_id else Q(work=work)))
    context = {
        'work': work, 'achievements': work.achievements.all(),
        'can_edit': access.can_edit_work(work),
        'show_contacts': access.can_see_contacts(work.student),
        'documents': documents.order_by('-uploaded_at') if access.can_import else [],
        'copies': work.issued_copies.all() if access.can_import else [],
        'transitions': [s for s in statuses.allowed_targets(work.status) if s != work.status],
        'status_form': StatusForm(work=work) if access.can_edit_work(work) else None,
    }
    return render(request, 'registry/work_detail.html', context)


def _work_form_kwargs(access):
    return {'teachers': access.teachers(edit=True).filter(is_active=True),
            'students': access.students(edit=True).filter(is_active=True) if not access.is_admin
            else Student.objects.filter(is_active=True)}


def work_edit(request, pk=None):
    access = access_for(request)
    access.require(access.can_edit)
    work = None
    if pk is not None:
        work = _scoped(access.works(edit=True), pk)
    form = WorkForm(request.POST or None, instance=work, **_work_form_kwargs(access))
    formset = AchievementFormSet(request.POST or None, instance=work or ResearchWork())
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        teacher = form.cleaned_data['teacher']
        access.require(access.can_edit_department(teacher.department_id))
        with transaction.atomic():
            obj = form.save(commit=False)
            if work is None:
                obj.created_by = request.user
            obj.updated_by = request.user
            if form.cleaned_data.get('status_note'):
                obj.status_comment = form.cleaned_data['status_note'][:500]
            obj.save()
            formset.instance = obj
            formset.save()
        duplicates = (ResearchWork.objects.alive().filter(teacher=obj.teacher, student=obj.student,
                                                          academic_year=obj.academic_year,
                                                          status__in=statuses.ACTIVE).exclude(pk=obj.pk))
        if duplicates.exists():
            messages.warning(request, 'У этой пары «преподаватель — студент» уже есть активная работа '
                                      'в этом учебном году.')
        log(request, 'work_create' if work is None else 'work_update', obj)
        messages.success(request, 'Работа сохранена.')
        return redirect('work_detail', obj.pk)
    return render(request, 'registry/work_form.html', {'form': form, 'formset': formset, 'work': work})


@require_POST
def work_status(request, pk):
    access = access_for(request)
    work = _scoped(access.works(edit=True), pk)
    form = StatusForm(request.POST, work=work)
    if form.is_valid():
        old = work.get_status_display()
        work.status = form.cleaned_data['status']
        if form.cleaned_data['comment']:
            work.status_comment = form.cleaned_data['comment']
        work.updated_by = request.user
        work._change_reason = 'Смена статуса'
        work.save()
        log(request, 'work_status', work, old=old, new=work.get_status_display())
        messages.success(request, f'Статус изменён: «{old}» → «{work.get_status_display()}».')
    else:
        messages.error(request, ' '.join(form.non_field_errors()) or 'Статус не изменён.')
    return redirect('work_detail', pk)


@require_POST
def work_delete(request, pk):
    access = access_for(request)
    work = _scoped(access.works(edit=True), pk)
    work.soft_delete()
    log(request, 'work_delete', work)
    messages.success(request, 'Работа удалена. Администратор может её восстановить.')
    return redirect('work_list')


@require_POST
def work_restore(request, pk):
    access = access_for(request)
    access.require(access.is_admin)
    work = get_object_or_404(ResearchWork, pk=pk, is_deleted=True)
    work.is_deleted = False
    work.deleted_at = None
    work.save(update_fields=['is_deleted', 'deleted_at', 'updated_at'])
    log(request, 'work_restore', work)
    messages.success(request, 'Работа восстановлена.')
    return redirect('work_detail', pk)


@require_POST
def work_purge(request, pk):
    """Физическое удаление — только администратор, вместе с загрузками PDF (ТЗ 6.1)."""
    access = access_for(request)
    access.require(access.is_admin)
    work = get_object_or_404(ResearchWork, pk=pk, is_deleted=True)
    with transaction.atomic():
        for document in ImportedDocument.objects.filter(work=work):
            document.file.delete(save=False)
            document.delete()
        log(request, 'work_purge', work)
        work.delete()
    messages.success(request, 'Работа и её загрузки удалены безвозвратно.')
    return redirect(reverse('work_list') + '?deleted=1')


# Преподаватели

def teacher_list(request):
    access = access_for(request)
    qs = access.teachers().select_related('department').annotate(
        works_count=Count('works', filter=Q(works__is_deleted=False))).order_by('last_name', 'first_name')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(last_name__icontains=q) | Q(first_name__icontains=q) | Q(position__icontains=q))
    if request.GET.get('department'):
        qs = qs.filter(department_id=request.GET['department'])
    if request.GET.get('inactive') != '1':
        qs = qs.filter(is_active=True)
    return render(request, 'registry/teacher_list.html', {
        'page': paginate(request, qs), 'q': q, 'departments': access.departments(), 'filters': request.GET})


def teacher_detail(request, pk):
    access = access_for(request)
    teacher = _scoped(access.teachers().select_related('department'), pk)
    works = access.works().filter(teacher=teacher).select_related('student__group')
    return render(request, 'registry/teacher_detail.html', {
        'teacher': teacher, 'works': works, 'can_edit': access.can_edit_department(teacher.department_id)})


def teacher_edit(request, pk=None):
    access = access_for(request)
    access.require(access.can_edit)
    teacher = _scoped(access.teachers(edit=True), pk) if pk else None
    form = TeacherForm(request.POST or None, instance=teacher, departments=access.departments(edit=True),
                       can_link_user=access.is_admin)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        log(request, 'teacher_create' if teacher is None else 'teacher_update', obj)
        messages.success(request, 'Преподаватель сохранён.')
        return redirect('teacher_detail', obj.pk)
    return render(request, 'registry/simple_form.html', {
        'form': form, 'title': 'Преподаватель' if teacher is None else f'Преподаватель: {teacher}',
        'back': reverse('teacher_detail', args=[teacher.pk]) if teacher else reverse('teacher_list')})


def teacher_merge(request, pk):
    access = access_for(request)
    access.require(access.can_edit)
    main = _scoped(access.teachers(edit=True), pk)
    form = MergeForm(request.POST or None, queryset=access.teachers(edit=True).filter(is_active=True), main=main)
    if request.method == 'POST' and form.is_valid():
        duplicate = form.cleaned_data['duplicate']
        with transaction.atomic():
            moved = ResearchWork.objects.filter(teacher=duplicate).update(teacher=main)
            duplicate.issued_copies.update(teacher=main)
            duplicate.is_active = False
            duplicate.merged_into = main
            duplicate._change_reason = f'Объединён с №{main.pk}'
            duplicate.save()
        log(request, 'teacher_merge', main, duplicate=duplicate.pk, works=moved)
        messages.success(request, f'Объединено: перенесено работ — {moved}.')
        return redirect('teacher_detail', main.pk)
    return render(request, 'registry/merge.html', {'form': form, 'main': main, 'kind': 'преподавателя'})


# Студенты

def student_list(request):
    access = access_for(request)
    qs = access.students().select_related('group').order_by('last_name', 'first_name', 'id')
    q = request.GET.get('q', '').strip()
    if q:
        condition = Q(last_name__icontains=q) | Q(first_name__icontains=q) | Q(group__code__icontains=q)
        if access.can_see_any_contacts:
            contact_students = access.students(Student.objects.filter(Q(phone__icontains=q) | Q(email__icontains=q)))
            if access.contact_scope is not None:
                contact_students = contact_students.filter(
                    Q(works__teacher__department_id__in=access.contact_scope)
                    | Q(group__department_id__in=access.contact_scope))
            condition |= Q(id__in=contact_students.values('id'))
        qs = qs.filter(condition)
    if request.GET.get('course'):
        qs = qs.filter(course=request.GET['course'])
    if request.GET.get('inactive') != '1':
        qs = qs.filter(is_active=True)
    return render(request, 'registry/student_list.html', {'page': paginate(request, qs), 'q': q,
                                                          'filters': request.GET})


def student_detail(request, pk):
    access = access_for(request)
    student = _scoped(access.students().select_related('group'), pk)
    works = access.works().filter(student=student).select_related('teacher__department')
    return render(request, 'registry/student_detail.html', {
        'student': student, 'works': works, 'show_contacts': access.can_see_contacts(student),
        'can_edit': access.can_edit and (access.is_admin or access.students(edit=True).filter(pk=pk).exists())})


def student_edit(request, pk=None):
    access = access_for(request)
    access.require(access.can_edit)
    if pk is None:
        access.require(access.can_create_students())  # телефон и email обязательны (ТЗ 3.1)
        student = None
        show_contacts = True
    else:
        qs = Student.objects.all() if access.is_admin else access.students(edit=True)
        student = _scoped(qs, pk)
        show_contacts = access.can_see_contacts(student)
    form = StudentForm(request.POST or None, instance=student, groups=access.groups(edit=True),
                       show_contacts=show_contacts)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        log(request, 'student_create' if student is None else 'student_update', obj)
        messages.success(request, 'Студент сохранён.')
        if request.GET.get('next', '').startswith('/'):
            return redirect(request.GET['next'])
        return redirect('student_detail', obj.pk)
    return render(request, 'registry/simple_form.html', {
        'form': form, 'title': 'Студент (курсант)' if student is None else f'Студент: {student}',
        'back': reverse('student_detail', args=[student.pk]) if student else reverse('student_list')})


def student_merge(request, pk):
    access = access_for(request)
    access.require(access.is_responsible)
    main = _scoped(access.students(edit=True), pk)
    form = MergeForm(request.POST or None, queryset=access.students(edit=True).filter(is_active=True), main=main)
    if request.method == 'POST' and form.is_valid():
        duplicate = form.cleaned_data['duplicate']
        with transaction.atomic():
            moved = ResearchWork.objects.filter(student=duplicate).update(student=main)
            duplicate.issued_copies.update(student=main)
            duplicate.is_active = False
            duplicate.merged_into = main
            duplicate._change_reason = f'Объединён с №{main.pk}'
            duplicate.save()
        log(request, 'student_merge', main, duplicate=duplicate.pk, works=moved)
        messages.success(request, f'Объединено: перенесено работ — {moved}.')
        return redirect('student_detail', main.pk)
    return render(request, 'registry/merge.html', {'form': form, 'main': main, 'kind': 'студента'})


# Кафедры и группы

def department_list(request):
    access = access_for(request)
    qs = access.departments().annotate(teachers_count=Count('teachers', distinct=True))
    return render(request, 'registry/department_list.html', {'departments': qs})


def department_edit(request, pk=None):
    access = access_for(request)
    access.require(access.is_admin if pk is None else access.can_edit)
    department = _scoped(access.departments(edit=True), pk) if pk else None
    form = DepartmentForm(request.POST or None, instance=department)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        log(request, 'department_save', obj)
        messages.success(request, 'Кафедра сохранена.')
        return redirect('department_list')
    return render(request, 'registry/simple_form.html', {'form': form, 'title': 'Кафедра',
                                                         'back': reverse('department_list')})


def group_list(request):
    access = access_for(request)
    qs = access.groups().select_related('department').annotate(students_count=Count('students')).order_by('code')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(code__icontains=q)
    return render(request, 'registry/group_list.html', {'page': paginate(request, qs, 100), 'q': q})


def group_edit(request, pk=None):
    access = access_for(request)
    access.require(access.can_edit)
    group = _scoped(access.groups(edit=True), pk) if pk else None
    form = GroupForm(request.POST or None, instance=group, departments=access.departments(edit=True))
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        log(request, 'group_save', obj)
        messages.success(request, 'Группа сохранена.')
        return redirect('group_list')
    return render(request, 'registry/simple_form.html', {'form': form, 'title': 'Группа',
                                                         'back': reverse('group_list')})


# История

def history(request, kind, pk):
    access = access_for(request)
    if kind == 'work':
        obj = _scoped(ResearchWork.objects.all() if access.is_admin else access.works(), pk)
        show_contacts = access.can_see_contacts(obj.student)
    elif kind == 'student':
        obj = _scoped(access.students(), pk)
        show_contacts = access.can_see_contacts(obj)
    elif kind == 'teacher':
        obj = _scoped(access.teachers(), pk)
        show_contacts = True
    else:
        raise Http404
    return render(request, 'registry/history.html', {
        'obj': obj, 'kind': kind, 'entries': history_entries(obj, show_contacts)})
