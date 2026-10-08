"""Приём файлов и обработка загрузок (ТЗ 7.1, 7.2, 7.4)."""
from dataclasses import dataclass, field
import hashlib
import io
import logging
from pathlib import PurePosixPath
import zipfile

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from . import adapters
from .adapters import Outcome
from .models import DocState, ImportBatch, ImportedDocument
from .returns import build_return_message

logger = logging.getLogger(__name__)
MB = 1024 * 1024
ZIP_MAX_RATIO = 100  # защита от «zip-бомб»


@dataclass
class Incoming:
    name: str
    content: bytes


@dataclass
class Intake:
    files: list = field(default_factory=list)
    skipped: list = field(default_factory=list)  # сообщения о файлах, которые не приняты


def _safe_name(name):
    return PurePosixPath(name.replace('\\', '/')).name[:255] or 'file.pdf'


def collect(uploaded_files):
    """Файлы из формы загрузки (PDF и ZIP) → список PDF с проверкой ограничений."""
    intake = Intake()
    max_file = settings.IMPORT_MAX_FILE_MB * MB
    max_total = settings.IMPORT_MAX_BATCH_MB * MB
    total = 0

    def add(name, content):
        nonlocal total
        if len(intake.files) >= settings.IMPORT_MAX_FILES:
            intake.skipped.append(f'{name}: превышено число файлов в пакете ({settings.IMPORT_MAX_FILES}).')
            return
        if len(content) > max_file:
            intake.skipped.append(f'{name}: файл больше {settings.IMPORT_MAX_FILE_MB} МБ.')
            return
        if total + len(content) > max_total:
            intake.skipped.append(f'{name}: превышен общий размер пакета ({settings.IMPORT_MAX_BATCH_MB} МБ).')
            return
        total += len(content)
        intake.files.append(Incoming(name, content))

    for uploaded in uploaded_files:
        name = _safe_name(uploaded.name)
        if uploaded.size > max(max_file, max_total):
            intake.skipped.append(f'{name}: файл слишком большой.')
            continue
        content = uploaded.read()
        if name.lower().endswith('.zip') or content[:4] == b'PK\x03\x04':
            _collect_zip(name, content, add, intake)
        else:
            add(name, content)
    return intake


def _collect_zip(name, content, add, intake):
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        intake.skipped.append(f'{name}: повреждённый ZIP-архив.')
        return
    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            member = _safe_name(info.filename)
            if not member.lower().endswith('.pdf') or member.startswith('.') or '__MACOSX' in info.filename:
                continue
            if info.file_size > settings.IMPORT_MAX_FILE_MB * MB:
                intake.skipped.append(f'{name}/{member}: файл больше {settings.IMPORT_MAX_FILE_MB} МБ.')
                continue
            if info.compress_size and info.file_size / info.compress_size > ZIP_MAX_RATIO:
                intake.skipped.append(f'{name}/{member}: подозрительная степень сжатия, файл пропущен.')
                continue
            with archive.open(info) as handle:
                data = handle.read(settings.IMPORT_MAX_FILE_MB * MB + 1)
            add(member, data)


def create_batch(user, incoming):
    """Сохранить файлы пакета. Маленький пакет обрабатывается сразу, большой — фоновым обработчиком."""
    background = len(incoming) > settings.IMPORT_SYNC_LIMIT
    with transaction.atomic():
        batch = ImportBatch.objects.create(created_by=user, background=background)
        documents = []
        for item in incoming:
            document = ImportedDocument(batch=batch, original_name=item.name, size=len(item.content),
                                        sha256=hashlib.sha256(item.content).hexdigest(), uploaded_by=user,
                                        state=DocState.QUEUED)
            document.file.save(item.name, ContentFile(item.content), save=False)
            document.save()
            documents.append(document)
    if not background:
        for document in documents:
            process_document(document)
    return batch


def _find_duplicate(document):
    return (ImportedDocument.objects.filter(sha256=document.sha256, id__lt=document.id)
            .exclude(state__in=(DocState.REJECTED_USER, DocState.DUPLICATE, DocState.QUEUED))
            .order_by('id').first())


def guess_department(document):
    """Кафедра загрузки для области видимости журнала: по выданной копии, работе или тексту анкеты."""
    from registry.models import ResearchWork

    from .matching import find_department
    from .models import IssuedCopy
    if document.questionnaire_id:
        work = ResearchWork.objects.filter(questionnaire_id=document.questionnaire_id).select_related('teacher').first()
        if work:
            return work.teacher.department
        copy = IssuedCopy.objects.filter(questionnaire_id=document.questionnaire_id).select_related('teacher').first()
        if copy:
            return copy.teacher.department
    data = adapters.to_neutral(document)
    if data is not None:
        return find_department(data.teacher_department)
    return None


def process_document(document):
    """Извлечение, проверка и состояние загрузки. Рабочие таблицы не меняются."""
    try:
        result = adapters.extract(document.file.path)
    except Exception:  # extract() не должна бросать, но фоновая обработка не должна останавливаться
        logger.exception('Ошибка обработки загрузки %s', document.pk)
        document.state = DocState.REJECTED_CHECK
        document.processing_error = 'Внутренняя ошибка обработки файла.'
        document.save()
        return document
    document.form_id = result.form_id
    document.schema_version = result.schema_version
    document.questionnaire_id = result.questionnaire_id
    document.extracted = result.extracted
    document.errors = result.errors
    document.warnings = result.warnings
    document.student_name = result.student_name[:300]
    document.teacher_name = result.teacher_name[:300]
    document.return_message = ''

    duplicate = _find_duplicate(document)
    if duplicate is not None:
        document.state = DocState.DUPLICATE
        document.duplicate_of = duplicate
    elif result.outcome == Outcome.OK:
        document.state = DocState.PENDING
    elif result.outcome == Outcome.RETURN:
        document.state = DocState.TO_RETURN
        document.return_message = build_return_message(document, result.return_reason)
    elif result.outcome == Outcome.UNSUPPORTED:
        document.state = DocState.UNSUPPORTED
    else:
        document.state = DocState.REJECTED_CHECK
    document.department = guess_department(document)
    document.save()

    if document.state != DocState.DUPLICATE and document.questionnaire_id:
        (ImportedDocument.objects
         .filter(questionnaire_id=document.questionnaire_id, id__lt=document.id, resubmission__isnull=True,
                 state__in=(DocState.TO_RETURN, DocState.RETURNED))
         .update(resubmission=document))
    return document


def reprocess(document):
    """Повторная обработка из журнала (например, после добавления адаптера новой версии)."""
    document.state = DocState.QUEUED
    document.save(update_fields=['state'])
    return process_document(document)


def process_queue(limit=50):
    """Обработать документы «В очереди». Возвращает число обработанных. Для фонового обработчика."""
    from django.db import connection
    done = 0
    while done < limit:
        with transaction.atomic():
            qs = ImportedDocument.objects.filter(state=DocState.QUEUED).order_by('id')
            if connection.features.has_select_for_update_skip_locked:
                qs = qs.select_for_update(skip_locked=True)
            document = qs.first()
            if document is None:
                break
            process_document(document)
        done += 1
    return done


def mark_returned(document, user):
    document.state = DocState.RETURNED
    document.returned_by = user
    document.returned_at = timezone.now()
    document.save(update_fields=['state', 'returned_by', 'returned_at'])
