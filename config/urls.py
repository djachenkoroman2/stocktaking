from django.contrib import admin
from django.urls import include, path

from accounts import views as account_views

admin.site.site_header = 'Учёт НИР — администрирование'
admin.site.site_title = 'Учёт НИР'

urlpatterns = [
    path('health/', account_views.health, name='health'),
    path('accounts/', include('accounts.urls')),
    path('imports/', include('imports.urls')),
    path('reports/', include('reports.urls')),
    path('api/', include('api.urls')),
    path('export/', include('snapshots.urls')),
    path('admin/', admin.site.urls),
    path('', include('registry.urls')),
]
