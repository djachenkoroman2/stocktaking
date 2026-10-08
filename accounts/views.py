import uuid

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.core.paginator import Paginator
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

from .access import access_for
from .forms import LoginForm
from .models import AuditEvent


class LoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = 'accounts/login.html'


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = 'accounts/password_change.html'
    success_url = '/'

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs['class'] = 'form-control'
        return form


def health(request):
    """Проверка работоспособности (ТЗ 11.5): БД и запись в хранилище."""
    status = {'database': False, 'storage': False}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        status['database'] = True
    except Exception:
        pass
    try:
        settings.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
        probe = settings.MEDIA_ROOT / f'.health-{uuid.uuid4().hex}'
        probe.write_text('ok')
        probe.unlink()
        status['storage'] = True
    except Exception:
        pass
    ok = all(status.values())
    return JsonResponse({'status': 'ok' if ok else 'error', **status}, status=200 if ok else 503)


def audit_list(request):
    access_for(request).require(access_for(request).is_admin)
    events = AuditEvent.objects.select_related('user')
    action = request.GET.get('action', '')
    username = request.GET.get('username', '')
    if action:
        events = events.filter(action=action)
    if username:
        events = events.filter(username__icontains=username)
    page = Paginator(events, 100).get_page(request.GET.get('page'))
    actions = AuditEvent.objects.order_by('action').values_list('action', flat=True).distinct()
    return render(request, 'accounts/audit.html', {'page': page, 'actions': actions,
                                                   'action': action, 'username': username})
