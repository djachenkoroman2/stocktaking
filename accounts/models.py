from django.conf import settings
from django.db import models


class Role(models.TextChoices):
    ADMIN = 'admin', 'Администратор'
    RESPONSIBLE = 'responsible', 'Ответственный кафедры'
    OBSERVER = 'observer', 'Наблюдатель'


class RoleAssignment(models.Model):
    """Роль пользователя в области данных. Кафедра не указана — вся система.

    Роль «Преподаватель» задаётся связью преподавателя с учётной записью (Teacher.user).
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.CASCADE, related_name='roles',
                             verbose_name='пользователь')
    role = models.CharField('роль', max_length=20, choices=Role.choices)
    department = models.ForeignKey('registry.Department', models.CASCADE, null=True, blank=True,
                                   verbose_name='кафедра', help_text='Пусто — все кафедры.')

    class Meta:
        verbose_name = 'роль'
        verbose_name_plural = 'роли'
        constraints = [models.UniqueConstraint(fields=['user', 'role', 'department'], name='role_unique')]

    def __str__(self):
        return f'{self.get_role_display()}: {self.department or "все кафедры"}'


class AuditEvent(models.Model):
    at = models.DateTimeField('время', auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True,
                             verbose_name='пользователь')
    username = models.CharField('имя входа', max_length=150, blank=True)
    action = models.CharField('действие', max_length=50, db_index=True)
    object_type = models.CharField('объект', max_length=50, blank=True)
    object_id = models.CharField('ID объекта', max_length=100, blank=True)
    details = models.JSONField('подробности', default=dict, blank=True)
    ip = models.GenericIPAddressField('IP', null=True, blank=True)

    class Meta:
        verbose_name = 'событие аудита'
        verbose_name_plural = 'журнал аудита'
        ordering = ['-at']

    def __str__(self):
        return f'{self.at:%d.%m.%Y %H:%M} {self.username} {self.action}'


class LoginFailure(models.Model):
    username = models.CharField(max_length=150, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)
