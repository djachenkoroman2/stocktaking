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
