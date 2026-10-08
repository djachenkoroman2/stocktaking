from django.contrib import admin

from .models import FormTemplate, ImportBatch, ImportedDocument, IssuedCopy


@admin.register(FormTemplate)
class FormTemplateAdmin(admin.ModelAdmin):
    list_display = ('original_name', 'form_id', 'schema_version', 'is_current', 'uploaded_at')
    exclude = ('file',)
    readonly_fields = ('original_name', 'sha256', 'form_id', 'schema_version', 'uploaded_by')


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'created_by', 'background')


@admin.register(ImportedDocument)
class ImportedDocumentAdmin(admin.ModelAdmin):
    """Без файла и извлечённого JSON: в них есть контакты студентов."""
    list_display = ('original_name', 'state', 'questionnaire_id', 'uploaded_at', 'uploaded_by')
    list_filter = ('state',)
    search_fields = ('original_name', 'questionnaire_id')
    exclude = ('file', 'extracted')
    readonly_fields = ('batch', 'sha256', 'size', 'form_id', 'schema_version', 'questionnaire_id', 'errors',
                       'warnings', 'work', 'duplicate_of', 'resubmission', 'uploaded_by', 'processed_by')


@admin.register(IssuedCopy)
class IssuedCopyAdmin(admin.ModelAdmin):
    list_display = ('questionnaire_id', 'teacher', 'student', 'issued_at', 'work')
    raw_id_fields = ('teacher', 'student', 'work', 'replaces_document')
    exclude = ('file',)
