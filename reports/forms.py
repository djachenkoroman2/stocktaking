from django import forms

from accounts.forms import BootstrapMixin
from imports.models import DocState
from registry.models import ResearchWork
from registry.status import WorkStatus

DATE = {'widget': forms.DateInput(attrs={'type': 'date'})}


class ReportForm(BootstrapMixin, forms.Form):
    """Параметры отчёта: общие (ТЗ 9) и дополнительные для конкретного отчёта."""

    def __init__(self, *args, report, access, **kwargs):
        self.report = report
        fields = {}
        departments = access.departments()
        if report.common:
            years = (ResearchWork.objects.alive().order_by('-academic_year')
                     .values_list('academic_year', flat=True).distinct())
            fields['year'] = forms.ChoiceField(label='Учебный год', required=False,
                                               choices=[('', 'все')] + [(y, y) for y in years])
            fields['date_from'] = forms.DateField(label='Дата анкеты с', required=False, **DATE)
            fields['date_to'] = forms.DateField(label='по', required=False, **DATE)
            fields['department'] = forms.ModelChoiceField(label='Кафедра', queryset=departments, required=False,
                                                          empty_label='все')
            fields['include_inactive'] = forms.BooleanField(
                label='Включать неактивных студентов и неактивные работы', required=False)
        teachers = access.teachers().select_related('department')
        for name in report.params:
            if name == 'teacher':
                fields['teacher'] = forms.ModelChoiceField(label='Преподаватель', queryset=teachers)
            elif name == 'teacher_optional':
                fields['teacher'] = forms.ModelChoiceField(label='Преподаватель', queryset=teachers, required=False,
                                                           empty_label='все')
            elif name == 'course':
                fields['course'] = forms.TypedChoiceField(label='Курс', required=False, coerce=int, empty_value=None,
                                                          choices=[('', 'все')] + [(i, i) for i in range(1, 7)])
            elif name == 'group':
                fields['group'] = forms.ModelChoiceField(label='Группа', queryset=access.groups(), required=False,
                                                         empty_label='все')
            elif name == 'statuses':
                fields['statuses'] = forms.MultipleChoiceField(label='Статусы', required=False,
                                                               choices=WorkStatus.choices,
                                                               widget=forms.CheckboxSelectMultiple)
            elif name == 'active_only':
                fields['active_only'] = forms.BooleanField(label='Только активные', required=False)
            elif name == 'min_students':
                fields['min_students'] = forms.IntegerField(label='Не меньше студентов', required=False, min_value=0)
            elif name == 'stale_days':
                fields['stale_days'] = forms.IntegerField(label='Не обновлялись дней', required=False, min_value=1)
            elif name == 'department':
                fields['department'] = forms.ModelChoiceField(label='Кафедра', queryset=departments, required=False,
                                                              empty_label='все')
            elif name == 'copy_state':
                fields['state'] = forms.ChoiceField(label='Состояние копии', required=False, choices=[
                    ('', 'все'), ('none', 'Не получена')] + list(DocState.choices))
            elif name == 'doc_state':
                fields['state'] = forms.ChoiceField(label='Состояние', required=False,
                                                    choices=[('', 'все')] + list(DocState.choices))
            elif name == 'batch':
                fields['batch'] = forms.IntegerField(label='Пакет №', required=False, min_value=1)
            elif name == 'author':
                fields['author'] = forms.CharField(label='Автор (имя входа)', required=False)
            elif name == 'period':
                fields['date_from'] = forms.DateField(label='Загружено с', required=False, **DATE)
                fields['date_to'] = forms.DateField(label='по', required=False, **DATE)
        self.base_fields = fields
        super().__init__(*args, **kwargs)

    def describe(self):
        """Параметры для шапки выгрузки."""
        result = []
        for name, field in self.fields.items():
            value = self.cleaned_data.get(name)
            if value in (None, '', [], False):
                continue
            if isinstance(field, forms.ChoiceField) and not isinstance(field, forms.ModelChoiceField):
                labels = dict(field.choices)
                value = ', '.join(str(labels.get(v, v)) for v in value) if isinstance(value, list) \
                    else labels.get(value, labels.get(str(value), value))
            elif value is True:
                value = 'да'
            elif hasattr(value, 'strftime'):
                value = value.strftime('%d.%m.%Y')
            result.append((str(field.label), str(value)))
        return result
