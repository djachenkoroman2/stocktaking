from .access import access_for


def access(request):
    if not hasattr(request, 'user'):
        return {}
    return {'access': access_for(request)}
