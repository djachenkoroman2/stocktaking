from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .audit import log


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    log(request, 'login', user=user)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        details = {'switch_user': True} if getattr(request, 'switch_user', False) else {}
        log(request, 'logout', user=user, **details)
