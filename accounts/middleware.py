from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

OPEN_PREFIXES = ('/health/', '/accounts/login/', '/static/', '/api/', '/admin/')


class LoginRequiredMiddleware:
    """Доступ только после входа (ТЗ 11.3). API и админ-панель проверяют вход сами."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(OPEN_PREFIXES):
            return redirect(f'{reverse(settings.LOGIN_URL)}?next={request.path}')
        return self.get_response(request)


class SwitchUserFallbackMiddleware:
    """После смены пользователя — возврат на прежнюю страницу; если она новому пользователю недоступна — главная.

    Страницу запоминает LoginView (сессия switch_next); проверяется только первый запрос после входа.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.switch_target = request.session.pop('switch_next', None) if request.user.is_authenticated else None
        return self.get_response(request)

    def process_exception(self, request, exception):
        if request.switch_target == request.path and isinstance(exception, (PermissionDenied, Http404)):
            messages.info(request, 'Страница, с которой вы сменили пользователя, этой учётной записи недоступна. '
                                   'Открыта главная страница.')
            return redirect('dashboard')
        return None
