from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('works/', views.work_list, name='work_list'),
    path('works/new/', views.work_edit, name='work_create'),
    path('works/<int:pk>/', views.work_detail, name='work_detail'),
    path('works/<int:pk>/edit/', views.work_edit, name='work_edit'),
    path('works/<int:pk>/status/', views.work_status, name='work_status'),
    path('works/<int:pk>/delete/', views.work_delete, name='work_delete'),
    path('works/<int:pk>/restore/', views.work_restore, name='work_restore'),
    path('works/<int:pk>/purge/', views.work_purge, name='work_purge'),
    path('teachers/', views.teacher_list, name='teacher_list'),
    path('teachers/new/', views.teacher_edit, name='teacher_create'),
    path('teachers/<int:pk>/', views.teacher_detail, name='teacher_detail'),
    path('teachers/<int:pk>/edit/', views.teacher_edit, name='teacher_edit'),
    path('teachers/<int:pk>/merge/', views.teacher_merge, name='teacher_merge'),
    path('students/', views.student_list, name='student_list'),
    path('students/new/', views.student_edit, name='student_create'),
    path('students/<int:pk>/', views.student_detail, name='student_detail'),
    path('students/<int:pk>/edit/', views.student_edit, name='student_edit'),
    path('students/<int:pk>/merge/', views.student_merge, name='student_merge'),
    path('departments/', views.department_list, name='department_list'),
    path('departments/new/', views.department_edit, name='department_create'),
    path('departments/<int:pk>/edit/', views.department_edit, name='department_edit'),
    path('groups/', views.group_list, name='group_list'),
    path('groups/new/', views.group_edit, name='group_create'),
    path('groups/<int:pk>/edit/', views.group_edit, name='group_edit'),
    path('history/<str:kind>/<int:pk>/', views.history, name='history'),
]
