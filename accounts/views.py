import uuid
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth import views as auth_views
from django.core.paginator import Paginator
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .access import access_for
from .forms import LoginForm
from .models import AuditEvent


SWITCH_FROM = 'switch_from'  # сессия: кто вышел через «Сменить пользователя»
SWITCH_NEXT = 'switch_next'  # сессия: страница, на которую вернуться после смены (см. SwitchUserFallbackMiddleware)


class LoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = 'accounts/login.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['switch_from'] = self.request.session.get(SWITCH_FROM)
        return context

    def form_valid(self, form):
        switching = self.request.session.get(SWITCH_FROM) is not None
        response = super().form_valid(form)
        self.request.session.pop(SWITCH_FROM, None)
        next_url = self.get_redirect_url()
        if switching and next_url:
            self.request.session[SWITCH_NEXT] = urlsplit(next_url).path
        return response


@require_POST
def switch_user(request):
    """«Сменить пользователя»: обычный выход и страница входа с подсказкой; next — страница, где нажата кнопка."""
    previous = request.user.get_full_name() or request.user.get_username()
    next_url = request.POST.get('next', '')
    request.switch_user = True  # для записи в журнал аудита (signals.on_logout)
    logout(request)
    request.session[SWITCH_FROM] = previous
    url = reverse(settings.LOGIN_URL)
    safe = url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure())
    if next_url and safe and not next_url.startswith(reverse('switch_user')):
        url += '?' + urlencode({'next': next_url})
    return redirect(url)


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
