from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import AuditEvent, RoleAssignment


class RoleInline(admin.TabularInline):
    model = RoleAssignment
    extra = 1


admin.site.unregister(User)


@admin.register(User)
class UserWithRolesAdmin(UserAdmin):
    inlines = [RoleInline]
    list_display = ('username', 'last_name', 'first_name', 'email', 'is_active', 'is_superuser', 'roles_list')

    @admin.display(description='Роли')
    def roles_list(self, obj):
        return '; '.join(str(r) for r in obj.roles.select_related('department'))

    # Администратор по роли (не суперпользователь) управляет пользователями и ролями,
    # но не может выдать права суперпользователя и не меняет учётные записи суперпользователей.
    SUPERUSER_ONLY_FIELDS = ('is_superuser', 'is_staff', 'groups', 'user_permissions')

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            fields = (*fields, *self.SUPERUSER_ONLY_FIELDS)
        return fields

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ('at', 'username', 'action', 'object_type', 'object_id', 'ip')
    list_filter = ('action',)
    search_fields = ('username', 'object_id')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
