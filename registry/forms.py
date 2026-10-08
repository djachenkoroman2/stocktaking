from django import forms
from django.forms import inlineformset_factory

from accounts.forms import BootstrapMixin

from . import status as statuses
from .models import Achievement, Department, ResearchWork, Student, StudyGroup, Teacher
from .text import clean


class StripMixin:
    """Обрезка пробелов по краям всех строковых полей (ТЗ 5.3)."""

    def clean(self):
        data = super().clean()
        for name, value in list(data.items()):
            if isinstance(value, str):
                data[name] = clean(value)
        return data


class DepartmentForm(BootstrapMixin, StripMixin, forms.ModelForm):
    aliases_text = forms.CharField(label='Другие написания', required=False, widget=forms.Textarea(attrs={'rows': 3}),
                                   help_text='По одному в строке. Используются при сопоставлении анкет.')

    class Meta:
        model = Department
        fields = ['name', 'short_name', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['aliases_text'].initial = '\n'.join(self.instance.aliases or [])

    def save(self, commit=True):
        self.instance.aliases = [line.strip() for line in self.cleaned_data['aliases_text'].splitlines() if line.strip()]
        return super().save(commit)


class GroupForm(BootstrapMixin, StripMixin, forms.ModelForm):
    class Meta:
        model = StudyGroup
        fields = ['code', 'department', 'is_active']

    def __init__(self, *args, departments=None, **kwargs):
        super().__init__(*args, **kwargs)
        if departments is not None:
            self.fields['department'].queryset = departments


class TeacherForm(BootstrapMixin, StripMixin, forms.ModelForm):
    class Meta:
        model = Teacher
        fields = ['last_name', 'first_name', 'middle_name', 'position', 'academic_degree', 'academic_title',
                  'department', 'email', 'phone', 'user', 'is_active']

    def __init__(self, *args, departments=None, can_link_user=False, **kwargs):
        super().__init__(*args, **kwargs)
        if departments is not None:
            self.fields['department'].queryset = departments
        if not can_link_user:
            del self.fields['user']


class StudentForm(BootstrapMixin, StripMixin, forms.ModelForm):
    class Meta:
        model = Student
        fields = ['last_name', 'first_name', 'middle_name', 'category', 'course', 'group', 'phone', 'email',
                  'is_active']

    def __init__(self, *args, groups=None, show_contacts=True, **kwargs):
        super().__init__(*args, **kwargs)
        if groups is not None:
            self.fields['group'].queryset = groups
        if not show_contacts:  # контакты видят только ответственные (ТЗ 3.2)
            del self.fields['phone']
            del self.fields['email']


class WorkForm(BootstrapMixin, StripMixin, forms.ModelForm):
    class Meta:
        model = ResearchWork
        fields = ['teacher', 'student', 'task', 'schedule', 'expected_results', 'status', 'status_comment',
                  'date_filled', 'academic_year', 'notes']
        widgets = {
            'task': forms.Textarea(attrs={'rows': 8}),
            'schedule': forms.Textarea(attrs={'rows': 4}),
            'expected_results': forms.Textarea(attrs={'rows': 4}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'date_filled': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    status_note = forms.CharField(label='Комментарий к смене статуса', required=False,
                                  help_text='Обязателен при возобновлении завершённой или прекращённой работы.')

    def __init__(self, *args, teachers=None, students=None, **kwargs):
        super().__init__(*args, **kwargs)
        if teachers is not None:
            self.fields['teacher'].queryset = teachers
        if students is not None:
            self.fields['student'].queryset = students
        if self.instance.pk:
            allowed = statuses.allowed_targets(self.instance.status)
            self.fields['status'].choices = [(s.value, s.label) for s in allowed]

    def clean(self):
        data = super().clean()
        if self.instance.pk and 'status' in data:
            error = statuses.check_transition(self.instance.status, data['status'], data.get('status_note', ''))
            if error:
                self.add_error('status', error)
        return data


class StatusForm(BootstrapMixin, forms.Form):
    status = forms.ChoiceField(label='Новый статус')
    comment = forms.CharField(label='Комментарий', required=False, max_length=500)

    def __init__(self, *args, work, **kwargs):
        super().__init__(*args, **kwargs)
        self.work = work
        self.fields['status'].choices = [(s.value, s.label) for s in statuses.allowed_targets(work.status)]
        self.fields['status'].initial = work.status

    def clean(self):
        data = super().clean()
        error = statuses.check_transition(self.work.status, data.get('status', self.work.status),
                                          data.get('comment', ''))
        if error:
            raise forms.ValidationError(error)
        return data


class AchievementForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Achievement
        fields = ['text', 'order']
        widgets = {'text': forms.Textarea(attrs={'rows': 2})}


AchievementFormSet = inlineformset_factory(ResearchWork, Achievement, form=AchievementForm, extra=2,
                                           can_delete=True)


class MergeForm(BootstrapMixin, forms.Form):
    duplicate = forms.ModelChoiceField(label='Дубликат (будет деактивирован)', queryset=None)

    def __init__(self, *args, queryset, main, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['duplicate'].queryset = queryset.exclude(pk=main.pk)
