"""Импорт PDF-анкет (ТЗ 5.1, 7, 8)."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def upload_path(instance, filename):
    now = timezone.now()
    return f'imports/{now:%Y/%m}/{uuid.uuid4().hex}.pdf'


def template_path(instance, filename):
    return f'templates/{uuid.uuid4().hex}.pdf'


def copy_path(instance, filename):
    return f'copies/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.pdf'


class FormTemplate(models.Model):
    """Пустая форма, из которой готовятся копии (ТЗ 8)."""
    file = models.FileField('файл', upload_to=template_path)
    original_name = models.CharField('имя файла', max_length=255)
    sha256 = models.CharField('SHA-256', max_length=64)
    form_id = models.CharField('форма', max_length=100)
    schema_version = models.CharField('версия схемы', max_length=20)
    is_current = models.BooleanField('текущий', default=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, related_name='+')
    uploaded_at = models.DateTimeField('загружен', auto_now_add=True)

    class Meta:
        verbose_name = 'шаблон формы'
        verbose_name_plural = 'шаблоны формы'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.original_name} ({self.form_id} {self.schema_version})'


class ImportBatch(models.Model):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, related_name='+',
                                   verbose_name='автор')
    created_at = models.DateTimeField('создан', auto_now_add=True)
    background = models.BooleanField('фоновая обработка', default=False)

    class Meta:
        verbose_name = 'пакет импорта'
        verbose_name_plural = 'пакеты импорта'
        ordering = ['-created_at']

    def __str__(self):
        return f'Пакет №{self.pk} от {timezone.localtime(self.created_at):%d.%m.%Y %H:%M}'


class DocState(models.TextChoices):
    QUEUED = 'queued', 'В очереди'
    PENDING = 'pending', 'Ожидает решения'
    SAVED = 'saved', 'Сохранено'
    TO_RETURN = 'to_return', 'К возврату'
    RETURNED = 'returned', 'Возвращено преподавателю'
    UNSUPPORTED = 'unsupported', 'Версия не поддерживается'
    REJECTED_CHECK = 'rejected_check', 'Отклонено проверкой'
    REJECTED_USER = 'rejected_user', 'Отклонено пользователем'
    DUPLICATE = 'duplicate', 'Дубликат файла'


FINAL_STATES = (DocState.SAVED, DocState.RETURNED, DocState.REJECTED_CHECK, DocState.REJECTED_USER,
                DocState.DUPLICATE)


class ImportedDocument(models.Model):
    batch = models.ForeignKey(ImportBatch, models.CASCADE, related_name='documents', verbose_name='пакет')
    file = models.FileField('файл', upload_to=upload_path, blank=True)
    file_purged_at = models.DateTimeField('файл удалён', null=True, blank=True)
    original_name = models.CharField('имя файла', max_length=255)
    size = models.PositiveIntegerField('размер', default=0)
    sha256 = models.CharField('SHA-256', max_length=64, db_index=True)
    form_id = models.CharField('форма', max_length=100, blank=True)
    schema_version = models.CharField('версия схемы', max_length=20, blank=True)
    questionnaire_id = models.CharField('ID анкеты', max_length=100, blank=True, db_index=True)
    student_name = models.CharField('студент по анкете', max_length=300, blank=True)
    teacher_name = models.CharField('преподаватель по анкете', max_length=300, blank=True)
    extracted = models.JSONField('извлечённые данные', null=True, blank=True)
    errors = models.JSONField('ошибки', default=list, blank=True)
    warnings = models.JSONField('предупреждения', default=list, blank=True)
    state = models.CharField('состояние', max_length=20, choices=DocState.choices, default=DocState.QUEUED,
                             db_index=True)
    department = models.ForeignKey('registry.Department', models.SET_NULL, null=True, blank=True,
                                   verbose_name='кафедра', related_name='+')
    work = models.ForeignKey('registry.ResearchWork', models.SET_NULL, null=True, blank=True,
                             verbose_name='работа', related_name='documents')
    duplicate_of = models.ForeignKey('self', models.SET_NULL, null=True, blank=True, related_name='+',
                                     verbose_name='дубликат загрузки')
    decision_note = models.TextField('комментарий решения', blank=True)
    return_message = models.TextField('текст возврата', blank=True)
    returned_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True,
                                    related_name='+', verbose_name='вернул')
    returned_at = models.DateTimeField('возвращено', null=True, blank=True)
    resubmission = models.ForeignKey('self', models.SET_NULL, null=True, blank=True, related_name='resubmits',
                                     verbose_name='повторно прислана')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, related_name='+',
                                    verbose_name='загрузил')
    uploaded_at = models.DateTimeField('загружено', auto_now_add=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True,
                                     related_name='+', verbose_name='решение принял')
    processed_at = models.DateTimeField('решение принято', null=True, blank=True)
    processing_error = models.TextField('ошибка обработки', blank=True)

    class Meta:
        verbose_name = 'загрузка PDF'
        verbose_name_plural = 'загрузки PDF'
        ordering = ['batch_id', 'original_name', 'id']

    def __str__(self):
        return self.original_name

    @property
    def is_open(self):
        return self.state == DocState.PENDING


class IssuedCopy(models.Model):
    """Копия формы с уникальным ID анкеты, подготовленная через систему (ТЗ 8)."""
    questionnaire_id = models.CharField('ID анкеты', max_length=100, unique=True)
    teacher = models.ForeignKey('registry.Teacher', models.PROTECT, related_name='issued_copies',
                                verbose_name='преподаватель')
    student = models.ForeignKey('registry.Student', models.SET_NULL, null=True, blank=True,
                                related_name='issued_copies', verbose_name='студент')
    work = models.ForeignKey('registry.ResearchWork', models.SET_NULL, null=True, blank=True,
                             related_name='issued_copies', verbose_name='работа')
    form_template = models.ForeignKey(FormTemplate, models.PROTECT, related_name='copies', verbose_name='шаблон')
    form_file_sha256 = models.CharField('SHA-256 шаблона', max_length=64)
    file = models.FileField('файл', upload_to=copy_path)
    replaces_document = models.ForeignKey(ImportedDocument, models.SET_NULL, null=True, blank=True,
                                          related_name='replacement_copies', verbose_name='взамен загрузки')
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, related_name='+',
                                  verbose_name='выдал')
    issued_at = models.DateTimeField('выдана', auto_now_add=True)

    class Meta:
        verbose_name = 'выданная копия'
        verbose_name_plural = 'выданные копии'
        ordering = ['-issued_at']

    def __str__(self):
        return self.questionnaire_id

    @property
    def download_name(self):
        from registry.text import short_name
        teacher = self.teacher
        base = short_name(teacher.last_name, teacher.first_name, teacher.middle_name)
        base = base.replace(' ', '_').replace('.', '_').strip('_')
        while '__' in base:
            base = base.replace('__', '_')
        return f'{base}_{self.questionnaire_id[-8:]}.pdf'
