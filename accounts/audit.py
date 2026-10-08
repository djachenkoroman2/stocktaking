"""Журнал аудита (ТЗ 11.3). В подробности не записываются телефоны, email и тексты анкет."""
from .models import AuditEvent


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[0].strip() or request.META.get('REMOTE_ADDR')) or None


def log(request_or_user, action, obj=None, user=None, **details):
    request = request_or_user if hasattr(request_or_user, 'META') else None
    if user is None:
        user = getattr(request, 'user', None) if request is not None else request_or_user
    if user is not None and not user.is_authenticated:
        user = None
    AuditEvent.objects.create(
        user=user,
        username=details.pop('username', None) or (user.get_username() if user else ''),
        action=action,
        object_type=obj._meta.model_name if obj is not None else '',
        object_id=str(obj.pk) if obj is not None else '',
        details=details,
        ip=client_ip(request),
    )
