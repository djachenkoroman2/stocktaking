"""Справочники и работы (ТЗ 5.1)."""
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from simple_history.models import HistoricalRecords

from .status import DEFAULT, WorkStatus
from .text import academic_year, full_name, norm, short_name

EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')  # как в extract_static.py


def validate_email(value):
    if value and not EMAIL_RE.match(value.strip()):
        raise ValidationError('Электронная почта: неверный формат адреса.')


class Department(models.Model):
    name = models.CharField('название', max_length=255)
    short_name = models.CharField('краткое название', max_length=50, blank=True)
    aliases = models.JSONField('другие написания', default=list, blank=True)
    is_active = models.BooleanField('активна', default=True)

    class Meta:
        verbose_name = 'кафедра'
        verbose_name_plural = 'кафедры'
        ordering = ['name']
        constraints = [models.UniqueConstraint(Lower('name'), name='department_name_ci_unique')]

    def __str__(self):
        return self.name

    def matches(self, text):
        key = norm(text)
        return bool(key) and (key == norm(self.name) or key in {norm(a) for a in self.aliases})


class Teacher(models.Model):
    last_name = models.CharField('фамилия', max_length=100)
    first_name = models.CharField('имя', max_length=100)
    middle_name = models.CharField('отчество', max_length=100, blank=True)
    position = models.CharField('должность', max_length=255, blank=True)
    academic_degree = models.CharField('учёная степень', max_length=100, blank=True)
    academic_title = models.CharField('учёное звание', max_length=100, blank=True)
    department = models.ForeignKey(Department, models.PROTECT, verbose_name='кафедра', related_name='teachers')
    email = models.CharField('email', max_length=254, blank=True, validators=[validate_email])
    phone = models.CharField('телефон', max_length=50, blank=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True,
                                verbose_name='учётная запись', related_name='teacher_profile')
    is_active = models.BooleanField('активен', default=True)
    merged_into = models.ForeignKey('self', models.SET_NULL, null=True, blank=True, editable=False,
                                    related_name='+', verbose_name='объединён с')
    history = HistoricalRecords()

    class Meta:
        verbose_name = 'преподаватель'
        verbose_name_plural = 'преподаватели'
        ordering = ['last_name', 'first_name', 'middle_name']
        indexes = [models.Index(fields=['last_name', 'first_name'])]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return full_name(self.last_name, self.first_name, self.middle_name)

    @property
    def short_name(self):
        return short_name(self.last_name, self.first_name, self.middle_name)

    @property
    def name_key(self):
        return norm(self.full_name)


class StudyGroup(models.Model):
    code = models.CharField('шифр', max_length=50)
    department = models.ForeignKey(Department, models.SET_NULL, null=True, blank=True,
                                   verbose_name='выпускающая кафедра', related_name='groups')
    is_active = models.BooleanField('активна', default=True)

    class Meta:
        verbose_name = 'группа'
        verbose_name_plural = 'группы'
        ordering = ['code']
        constraints = [models.UniqueConstraint(Lower('code'), name='group_code_ci_unique')]

    def __str__(self):
        return self.code


class Student(models.Model):
    class Category(models.TextChoices):
        STUDENT = 'student', 'Студент'
        CADET = 'cadet', 'Курсант'

    CONTACT_FIELDS = ('phone', 'email')

    last_name = models.CharField('фамилия', max_length=100)
    first_name = models.CharField('имя', max_length=100)
    middle_name = models.CharField('отчество', max_length=100, blank=True)
    category = models.CharField('категория', max_length=10, choices=Category.choices, blank=True)
    course = models.PositiveSmallIntegerField('курс', null=True, blank=True,
                                              validators=[MinValueValidator(1), MaxValueValidator(6)])
    group = models.ForeignKey(StudyGroup, models.PROTECT, verbose_name='группа', related_name='students')
    phone = models.CharField('телефон', max_length=50)
    email = models.CharField('email', max_length=254, validators=[validate_email])
    is_active = models.BooleanField('активен', default=True)
    merged_into = models.ForeignKey('self', models.SET_NULL, null=True, blank=True, editable=False,
                                    related_name='+', verbose_name='объединён с')
    history = HistoricalRecords()

    class Meta:
        verbose_name = 'студент (курсант)'
        verbose_name_plural = 'студенты (курсанты)'
        ordering = ['last_name', 'first_name', 'middle_name']
        indexes = [models.Index(fields=['last_name', 'first_name'])]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return full_name(self.last_name, self.first_name, self.middle_name)

    @property
    def short_name(self):
        return short_name(self.last_name, self.first_name, self.middle_name)

    def department_ids(self):
        """Кафедры, к которым относится студент: по преподавателям его работ и по группе."""
        ids = set(self.works.filter(is_deleted=False).values_list('teacher__department_id', flat=True))
        if self.group.department_id:
            ids.add(self.group.department_id)
        return ids


class WorkQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(is_deleted=False)


class ResearchWork(models.Model):
    class Source(models.TextChoices):
        MANUAL = 'manual', 'Вручную'
        PDF = 'pdf', 'PDF-анкета'

    # Поля, которые приходят из анкеты и сравниваются при повторной загрузке (ТЗ 7.6).
    IMPORTED_FIELDS = ('task', 'schedule', 'expected_results', 'status_comment', 'notes', 'course_at_filling')

    questionnaire_id = models.CharField('ID анкеты', max_length=100, null=True, blank=True, unique=True)
    teacher = models.ForeignKey(Teacher, models.PROTECT, verbose_name='преподаватель', related_name='works')
    student = models.ForeignKey(Student, models.PROTECT, verbose_name='студент', related_name='works')
    task = models.TextField('задача')
    schedule = models.TextField('расписание', blank=True)
    expected_results = models.TextField('ожидаемые результаты', blank=True)
    status = models.CharField('статус', max_length=20, choices=WorkStatus.choices, default=DEFAULT)
    status_comment = models.CharField('комментарий к статусу', max_length=500, blank=True)
    course_at_filling = models.CharField('курс по анкете', max_length=20, blank=True)
    date_filled = models.DateField('дата заполнения', null=True, blank=True)
    academic_year = models.CharField('учебный год', max_length=9, blank=True,
                                     help_text='Например, 2026/2027. Пусто — по дате заполнения.')
    notes = models.TextField('примечание', blank=True)
    source = models.CharField('источник', max_length=10, choices=Source.choices, default=Source.MANUAL)
    last_import_snapshot = models.JSONField('значения последнего импорта', default=dict, blank=True,
                                            editable=False)
    is_deleted = models.BooleanField('удалена', default=False)
    deleted_at = models.DateTimeField('удалена', null=True, blank=True, editable=False)
    created_at = models.DateTimeField('создана', auto_now_add=True)
    updated_at = models.DateTimeField('изменена', auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True,
                                   editable=False, related_name='+')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True,
                                   editable=False, related_name='+')
    history = HistoricalRecords()

    objects = WorkQuerySet.as_manager()

    class Meta:
        verbose_name = 'работа'
        verbose_name_plural = 'работы'
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['academic_year']), models.Index(fields=['status'])]

    def __str__(self):
        return f'{self.student.short_name} — {self.teacher.short_name}'

    @property
    def title(self):
        """Тема для списков: первая непустая строка задачи."""
        for line in self.task.splitlines():
            if line.strip():
                return line.strip()
        return ''

    def save(self, *args, **kwargs):
        if not self.academic_year:
            self.academic_year = academic_year(self.date_filled or timezone.localdate())
        super().save(*args, **kwargs)

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at', 'updated_at'])


class Achievement(models.Model):
    work = models.ForeignKey(ResearchWork, models.CASCADE, verbose_name='работа', related_name='achievements')
    text = models.TextField('достижение')
    source_row = models.PositiveSmallIntegerField('строка анкеты', null=True, blank=True)
    order = models.PositiveSmallIntegerField('порядок', default=0)
    history = HistoricalRecords()

    class Meta:
        verbose_name = 'достижение'
        verbose_name_plural = 'достижения'
        ordering = ['order', 'id']

    def __str__(self):
        return self.text[:80]
