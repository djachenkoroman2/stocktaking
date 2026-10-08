from django.urls import path

from . import views

urlpatterns = [
    path('upload/', views.upload, name='import_upload'),
    path('batches/', views.batch_list, name='batch_list'),
    path('batches/<int:pk>/', views.batch_detail, name='batch_detail'),
    path('batches/<int:pk>/save-ready/', views.batch_save_ready, name='batch_save_ready'),
    path('batches/<int:pk>/return-texts/', views.batch_return_texts, name='batch_return_texts'),
    path('batches/<int:pk>/mark-returned/', views.batch_mark_returned, name='batch_mark_returned'),
    path('documents/', views.document_list, name='document_list'),
    path('documents/<int:pk>/', views.document_detail, name='document_detail'),
    path('documents/<int:pk>/reject/', views.document_reject, name='document_reject'),
    path('documents/<int:pk>/returned/', views.document_mark_returned, name='document_mark_returned'),
    path('documents/<int:pk>/return-text/', views.document_return_text, name='document_return_text'),
    path('documents/<int:pk>/reprocess/', views.document_reprocess, name='document_reprocess'),
    path('documents/<int:pk>/delete/', views.document_delete, name='document_delete'),
    path('documents/<int:pk>/download/', views.document_download, name='document_download'),
    path('templates/', views.template_list, name='template_list'),
    path('templates/<int:pk>/current/', views.template_make_current, name='template_make_current'),
    path('copies/', views.copy_list, name='copy_list'),
    path('copies/new/', views.copy_create, name='copy_create'),
    path('copies/<int:pk>/download/', views.copy_download, name='copy_download'),
    path('copies/zip/', views.copy_download_zip, name='copy_download_zip'),
]
