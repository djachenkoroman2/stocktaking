from django.urls import path

from . import views

urlpatterns = [
    path('', views.report_list, name='report_list'),
    path('<slug:slug>/', views.report_view, name='report'),
]
