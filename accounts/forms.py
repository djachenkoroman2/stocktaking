from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone

from .audit import client_ip, log
from .models import LoginFailure


class BootstrapMixin:
    """Классы Bootstrap для всех виджетов формы."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
                css = 'form-check-input'
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = 'form-select'
            else:
                css = 'form-control'
            existing = widget.attrs.get('class', '')
            widget.attrs['class'] = f'{existing} {css}'.strip()


class LoginForm(BootstrapMixin, AuthenticationForm):
    """Вход с блокировкой после LOGIN_MAX_FAILURES неудачных попыток на LOGIN_LOCK_MINUTES минут."""

    def clean(self):
        username = (self.cleaned_data.get('username') or '').strip()
        since = timezone.now() - timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
        if username and LoginFailure.objects.filter(username__iexact=username, at__gte=since).count() \
                >= settings.LOGIN_MAX_FAILURES:
            raise forms.ValidationError(
                f'Слишком много неудачных попыток входа. Повторите через {settings.LOGIN_LOCK_MINUTES} минут.',
                code='locked')
        try:
            return super().clean()
        except forms.ValidationError:
            if username:
                LoginFailure.objects.create(username=username, ip=client_ip(self.request))
                log(None, 'login_failed', username=username)
            raise

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        LoginFailure.objects.filter(username__iexact=user.get_username()).delete()
