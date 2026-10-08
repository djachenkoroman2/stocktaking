"""Админ-панель для служебных операций. Контактов студентов здесь нет (ТЗ 3.2)."""
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Achievement, Department, ResearchWork, Student, StudyGroup, Teacher


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_name', 'is_active')
    search_fields = ('name',)


@admin.register(StudyGroup)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('code', 'department', 'is_active')
    search_fields = ('code',)


@admin.register(Teacher)
class TeacherAdmin(SimpleHistoryAdmin):
    list_display = ('last_name', 'first_name', 'middle_name', 'position', 'department', 'user', 'is_active')
    list_filter = ('department', 'is_active')
    search_fields = ('last_name', 'first_name')
    autocomplete_fields = ('user',)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    exclude = ('phone', 'email')
    list_display = ('last_name', 'first_name', 'middle_name', 'group', 'course', 'is_active')
    search_fields = ('last_name', 'first_name')

    def has_add_permission(self, request):
        return False  # телефон и email обязательны — студентов создаёт ответственный в интерфейсе


class AchievementInline(admin.TabularInline):
    model = Achievement
    extra = 0


@admin.register(ResearchWork)
class WorkAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'status', 'academic_year', 'questionnaire_id', 'is_deleted')
    list_filter = ('status', 'is_deleted', 'academic_year')
    search_fields = ('questionnaire_id', 'student__last_name', 'teacher__last_name')
    raw_id_fields = ('teacher', 'student')
    inlines = [AchievementInline]
