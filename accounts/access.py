"""Права и области данных (ТЗ 3.1, 3.2). Все проверки выполняются на сервере через этот класс."""
from functools import cached_property

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .models import Role

ALL = None  # область «все кафедры»


def _union(a, b):
    if a is ALL or b is ALL:
        return ALL
    return a | b


class Access:
    def __init__(self, user):
        self.user = user

    @cached_property
    def _roles(self):
        scopes = {role: frozenset() for role in Role.values}
        if not self.user.is_authenticated or not self.user.is_active:
            return scopes
        for role, department_id in self.user.roles.values_list('role', 'department_id'):
            if department_id is None or scopes[role] is ALL:
                scopes[role] = ALL
            else:
                scopes[role] = scopes[role] | {department_id}
        return scopes

    @cached_property
    def is_admin(self):
        return self.user.is_authenticated and (self.user.is_superuser or self._roles[Role.ADMIN] is ALL
                                               or bool(self._roles[Role.ADMIN]))

    @property
    def responsible_scope(self):
        return self._roles[Role.RESPONSIBLE]

    @cached_property
    def is_responsible(self):
        return self.responsible_scope is ALL or bool(self.responsible_scope)

    @cached_property
    def is_observer(self):
        scope = self._roles[Role.OBSERVER]
        return scope is ALL or bool(scope)

    @cached_property
    def teacher(self):
        if not self.user.is_authenticated:
            return None
        from registry.models import Teacher
        return Teacher.objects.filter(user=self.user).first()

    # Области данных: ALL или множество ID кафедр.
    @cached_property
    def edit_scope(self):
        return ALL if self.is_admin else self.responsible_scope

    @cached_property
    def view_scope(self):
        return _union(self.edit_scope, self._roles[Role.OBSERVER])

    @property
    def contact_scope(self):
        """Контакты студентов — только ответственным (решение 6, ТЗ 14.1). Администратору — только при роли."""
        return self.responsible_scope

    @property
    def has_any_role(self):
        return self.is_admin or self.is_responsible or self.is_observer or self.teacher is not None

    @property
    def can_import(self):
        return self.is_admin or self.is_responsible

    @property
    def can_edit(self):
        return self.is_admin or self.is_responsible

    @property
    def can_see_any_contacts(self):
        return self.is_responsible

    @staticmethod
    def _in(scope, department_id):
        return scope is ALL or department_id in scope

    def can_view_department(self, department_id):
        return self._in(self.view_scope, department_id)

    def can_edit_department(self, department_id):
        return self._in(self.edit_scope, department_id)

    # Фильтры querysets.
    def _filter(self, qs, scope, field):
        if scope is ALL:
            return qs
        return qs.filter(**{f'{field}__in': scope})

    def departments(self, qs=None, edit=False):
        from registry.models import Department
        qs = Department.objects.all() if qs is None else qs
        if not edit and self.teacher is not None and self.view_scope is not ALL:
            return qs.filter(Q(id__in=self.view_scope) | Q(id=self.teacher.department_id))
        return self._filter(qs, self.edit_scope if edit else self.view_scope, 'id')

    def works(self, qs=None, edit=False):
        from registry.models import ResearchWork
        qs = ResearchWork.objects.alive() if qs is None else qs
        scope = self.edit_scope if edit else self.view_scope
        if scope is ALL:
            return qs
        condition = Q(teacher__department_id__in=scope)
        if not edit and self.teacher is not None:
            condition |= Q(teacher=self.teacher)
        return qs.filter(condition)

    def teachers(self, qs=None, edit=False):
        from registry.models import Teacher
        qs = Teacher.objects.all() if qs is None else qs
        scope = self.edit_scope if edit else self.view_scope
        if scope is ALL:
            return qs
        condition = Q(department_id__in=scope)
        if not edit and self.teacher is not None:
            condition |= Q(id=self.teacher.id)
        return qs.filter(condition)

    def students(self, qs=None, edit=False):
        from registry.models import Student
        qs = Student.objects.all() if qs is None else qs
        scope = self.edit_scope if edit else self.view_scope
        if scope is ALL:
            return qs
        condition = (Q(works__teacher__department_id__in=scope, works__is_deleted=False)
                     | Q(group__department_id__in=scope))
        if not edit and self.teacher is not None:
            condition |= Q(works__teacher=self.teacher, works__is_deleted=False)
        return qs.filter(condition).distinct()

    def groups(self, qs=None, edit=False):
        from registry.models import StudyGroup
        qs = StudyGroup.objects.all() if qs is None else qs
        scope = self.edit_scope if edit else self.view_scope
        if scope is ALL:
            return qs
        return qs.filter(Q(department__isnull=True) | Q(department_id__in=scope))

    def documents(self, qs=None):
        """Журнал импорта: администратор — всё; ответственный — свои загрузки и загрузки своих кафедр."""
        from imports.models import ImportedDocument
        qs = ImportedDocument.objects.all() if qs is None else qs
        if self.is_admin:
            return qs
        if not self.is_responsible:
            return qs.none()
        if self.responsible_scope is ALL:
            return qs
        return qs.filter(Q(uploaded_by=self.user) | Q(department_id__in=self.responsible_scope))

    # Проверки одного объекта.
    def can_view_work(self, work):
        return self.works().filter(pk=work.pk).exists()

    def can_edit_work(self, work):
        return self.can_edit_department(work.teacher.department_id)

    def can_see_contacts(self, student):
        scope = self.contact_scope
        if scope is ALL:
            return True
        return bool(scope) and bool(student.department_ids() & scope)

    def can_create_students(self):
        return self.is_responsible

    def can_download_document(self, document):
        """Заполненный PDF содержит контакты — только ответственным в их области (ТЗ 3.1)."""
        if not self.is_responsible or not self.documents().filter(pk=document.pk).exists():
            return False
        if self.responsible_scope is ALL or document.uploaded_by_id == self.user.id:
            return True
        return document.department_id in self.responsible_scope

    def require(self, condition):
        if not condition:
            raise PermissionDenied


def access_for(request):
    if not hasattr(request, '_access'):
        request._access = Access(request.user)
    return request._access
