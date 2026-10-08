"""API только для чтения (ТЗ, этап 3). Права и области данных — как в интерфейсе; контакты — только
ответственным (ТЗ 3.2). Аутентификация: токен (заголовок «Authorization: Token …») или сессия."""
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied

from accounts.access import Access
from registry.models import Achievement, Department, ResearchWork, Student, StudyGroup, Teacher


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ['id', 'name', 'short_name', 'is_active']


class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudyGroup
        fields = ['id', 'code', 'department', 'is_active']


class TeacherSerializer(serializers.ModelSerializer):
    class Meta:
        model = Teacher
        fields = ['id', 'last_name', 'first_name', 'middle_name', 'position', 'academic_degree', 'academic_title',
                  'department', 'is_active']


class StudentSerializer(serializers.ModelSerializer):
    group = serializers.CharField(source='group.code')

    class Meta:
        model = Student
        fields = ['id', 'last_name', 'first_name', 'middle_name', 'category', 'course', 'group', 'is_active',
                  'phone', 'email']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self.context['access'].can_see_contacts(instance):
            data.pop('phone')
            data.pop('email')
        return data


class AchievementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = ['id', 'text', 'source_row', 'order']


class WorkSerializer(serializers.ModelSerializer):
    achievements = AchievementSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source='get_status_display')

    class Meta:
        model = ResearchWork
        fields = ['id', 'questionnaire_id', 'teacher', 'student', 'task', 'schedule', 'expected_results', 'status',
                  'status_label', 'status_comment', 'course_at_filling', 'date_filled', 'academic_year', 'notes',
                  'source', 'created_at', 'updated_at', 'achievements']


class ScopedViewSet(viewsets.ReadOnlyModelViewSet):
    scope_method = None

    @property
    def access(self):
        if not hasattr(self, '_access'):
            self._access = Access(self.request.user)
        return self._access

    def get_queryset(self):
        if not self.access.has_any_role:
            raise PermissionDenied('Нет ролей.')
        return getattr(self.access, self.scope_method)().order_by('pk')

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'access': self.access}


class DepartmentViewSet(ScopedViewSet):
    serializer_class = DepartmentSerializer
    scope_method = 'departments'


class GroupViewSet(ScopedViewSet):
    serializer_class = GroupSerializer
    scope_method = 'groups'


class TeacherViewSet(ScopedViewSet):
    serializer_class = TeacherSerializer
    scope_method = 'teachers'


class StudentViewSet(ScopedViewSet):
    serializer_class = StudentSerializer
    scope_method = 'students'

    def get_queryset(self):
        return super().get_queryset().select_related('group')


class WorkViewSet(ScopedViewSet):
    serializer_class = WorkSerializer
    scope_method = 'works'

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related('achievements')
        params = self.request.query_params
        for name in ('teacher', 'student', 'status', 'academic_year'):
            if params.get(name):
                qs = qs.filter(**{name: params[name]})
        if params.get('department'):
            qs = qs.filter(teacher__department=params['department'])
        return qs
