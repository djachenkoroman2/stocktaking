from .access import Access


class RoleAdminBackend:
    """Права модели в админке Django для пользователей с ролью «Администратор».

    Не аутентифицирует. Ограничения для учётных записей суперпользователей — в admin.UserWithRolesAdmin.
    """

    def authenticate(self, request, **credentials):
        return None

    def _is_role_admin(self, user):
        if not user.is_active or user.is_anonymous:
            return False
        if not hasattr(user, '_role_admin'):
            user._role_admin = Access(user).is_admin
        return user._role_admin

    def has_perm(self, user, perm, obj=None):
        return self._is_role_admin(user)

    def has_module_perms(self, user, app_label):
        return self._is_role_admin(user)
