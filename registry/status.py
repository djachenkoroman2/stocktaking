"""Статусы работы (ТЗ 5.4)."""
from django.db import models


class WorkStatus(models.TextChoices):
    PLANNED = 'planned', 'Планируется'
    IN_PROGRESS = 'in_progress', 'В работе'
    SUSPENDED = 'suspended', 'Приостановлена'
    COMPLETED = 'completed', 'Завершена'
    TERMINATED = 'terminated', 'Прекращена'


TRANSITIONS = {
    WorkStatus.PLANNED: {WorkStatus.IN_PROGRESS, WorkStatus.TERMINATED},
    WorkStatus.IN_PROGRESS: {WorkStatus.SUSPENDED, WorkStatus.COMPLETED, WorkStatus.TERMINATED},
    WorkStatus.SUSPENDED: {WorkStatus.IN_PROGRESS, WorkStatus.TERMINATED},
    WorkStatus.COMPLETED: {WorkStatus.IN_PROGRESS},
    WorkStatus.TERMINATED: {WorkStatus.IN_PROGRESS},
}
ACTIVE = (WorkStatus.PLANNED, WorkStatus.IN_PROGRESS, WorkStatus.SUSPENDED)
DEFAULT = WorkStatus.IN_PROGRESS


def allowed_targets(current):
    """Статусы, доступные для выбора: текущий и допустимые переходы, в порядке списка."""
    targets = TRANSITIONS[WorkStatus(current)] | {WorkStatus(current)}
    return [status for status in WorkStatus if status in targets]


def is_reopening(current, new):
    return current in (WorkStatus.COMPLETED, WorkStatus.TERMINATED) and new == WorkStatus.IN_PROGRESS


def check_transition(current, new, comment=''):
    """Сообщение об ошибке или None. Возобновление требует комментария."""
    if current == new:
        return None
    if WorkStatus(new) not in TRANSITIONS[WorkStatus(current)]:
        allowed = ', '.join(f'«{s.label}»' for s in WorkStatus if s in TRANSITIONS[WorkStatus(current)])
        return f'Из статуса «{WorkStatus(current).label}» можно перейти только в: {allowed}.'
    if is_reopening(current, new) and not comment.strip():
        return 'Возобновление работы требует комментария.'
    return None
