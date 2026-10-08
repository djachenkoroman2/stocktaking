from django.conf import settings
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
