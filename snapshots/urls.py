from django.urls import path

from . import views

urlpatterns = [
    path('', views.export_list, name='export_list'),
    path('<int:pk>/download/', views.export_download, name='export_download'),
    path('<int:pk>/delete/', views.export_delete, name='export_delete'),
]
