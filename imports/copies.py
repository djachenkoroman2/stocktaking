"""Шаблон формы и подготовка копий с ID анкеты (ТЗ 8)."""
import hashlib
import io
from pathlib import Path
import tempfile
import uuid
import zipfile

from django.core.files.base import ContentFile
from django.db import transaction

from . import adapters
from .models import FormTemplate, IssuedCopy


class CopyError(Exception):
    pass


def _field(fields, name):
    value = fields.get(name, {}).get('/V')
    return '' if value is None else str(value).strip()


def register_template(name, content, user):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'form.pdf'
        path.write_bytes(content)
        try:
            fields = adapters.CURRENT.read_fields(path)
        except Exception as error:
            raise CopyError(f'Файл не является PDF-формой: {error}') from error
    form_id, version = _field(fields, 'meta.form_id'), _field(fields, 'meta.schema_version')
    if (form_id, version) not in adapters.ADAPTERS:
        raise CopyError(f'Форма {form_id!r} версии {version!r} не поддерживается.')
    if 'student.id' not in fields:
        raise CopyError('В форме нет поля ID анкеты.')
    if _field(fields, 'student.id'):
        raise CopyError('Это уже подготовленная копия с ID анкеты; загрузите пустую форму.')
    with transaction.atomic():
        FormTemplate.objects.update(is_current=False)
        template = FormTemplate(original_name=name[:255], sha256=hashlib.sha256(content).hexdigest(),
                                form_id=form_id, schema_version=version, is_current=True, uploaded_by=user)
        template.file.save(name, ContentFile(content), save=False)
        template.save()
    return template


def current_template():
    return FormTemplate.objects.filter(is_current=True).first()


def issue_copies(teacher, students, count, user, replaces=None):
    """Подготовить копии: по одной на каждого студента из списка, плюс count копий без студента."""
    template = current_template()
    if template is None:
        raise CopyError('Шаблон формы не загружен. Его загружает администратор.')
    adapter = adapters.ADAPTERS[(template.form_id, template.schema_version)]
    targets = list(students) + [None] * count
    if not targets:
        raise CopyError('Выберите студентов или укажите число копий.')
    copies = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, student in enumerate(targets):
            questionnaire_id = f'student-{uuid.uuid4()}'
            target = Path(tmp) / f'{index}.pdf'
            adapter.prepare_copy(template.file.path, target, questionnaire_id, teacher.full_name,
                                 teacher.position, teacher.department.name)
            copy = IssuedCopy(questionnaire_id=questionnaire_id, teacher=teacher, student=student,
                              form_template=template, form_file_sha256=template.sha256, issued_by=user,
                              replaces_document=replaces)
            copy.file.save('copy.pdf', ContentFile(target.read_bytes()), save=False)
            copy.save()
            copies.append(copy)
    return copies


def zip_copies(copies):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for copy in copies:
            with copy.file.open('rb') as handle:
                archive.writestr(copy.download_name, handle.read())
    return buffer.getvalue()
