from django import forms

from accounts.forms import BootstrapMixin
from registry import status as statuses
from registry.models import Student

from .apply import Decision


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput(attrs={'accept': '.pdf,.zip,application/pdf,application/zip'}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(item, initial) for item in data]
        return [single(data, initial)]


class UploadForm(BootstrapMixin, forms.Form):
    files = MultipleFileField(label='PDF-анкеты или ZIP-архив',
                              help_text='Можно выбрать несколько файлов. Анкеты загружают только ответственные.')


class TemplateForm(BootstrapMixin, forms.Form):
    file = forms.FileField(label='Пустая форма (PDF)', widget=forms.ClearableFileInput(attrs={'accept': '.pdf'}))


class CopyForm(BootstrapMixin, forms.Form):
    teacher = forms.ModelChoiceField(label='Преподаватель', queryset=None)
    students = forms.ModelMultipleChoiceField(label='Студенты (по копии на каждого)', queryset=None, required=False,
                                              widget=forms.SelectMultiple(attrs={'size': 8}))
    count = forms.IntegerField(label='Копий без студента', min_value=0, max_value=100, initial=0)

    def __init__(self, *args, teachers, students, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['teacher'].queryset = teachers
        self.fields['students'].queryset = students

    def clean(self):
        data = super().clean()
        if not data.get('students') and not data.get('count'):
            raise forms.ValidationError('Выберите студентов или укажите число копий.')
        return data


class RejectForm(BootstrapMixin, forms.Form):
    note = forms.CharField(label='Причина отклонения', widget=forms.Textarea(attrs={'rows': 2}))


class DecisionForm(BootstrapMixin, forms.Form):
    """Решения ответственного в предпросмотре (ТЗ 7.1, п. 5). Значения анкеты не редактируются."""

    note = forms.CharField(label='Комментарий', required=False)

    def __init__(self, *args, analysis, teachers, departments, can_create_department=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.analysis = analysis
        self.can_create_department = can_create_department
        a = analysis
        self.teacher_fixed = a.teacher_source in ('work', 'copy')
        if not self.teacher_fixed:
            mode = 'existing' if a.teacher is not None or a.teacher_source in ('candidates', 'empty') else 'new'
            self.fields['teacher_mode'] = forms.ChoiceField(
                label='Преподаватель', initial=mode, widget=forms.RadioSelect,
                choices=[('existing', 'Выбрать существующего'), ('new', 'Создать нового')])
            candidates = [t.pk for t in a.teacher_candidates]
            qs = teachers.filter(is_active=True)
            self.fields['teacher'] = forms.ModelChoiceField(
                label='Существующий преподаватель', queryset=qs, required=False,
                initial=a.teacher.pk if a.teacher else (candidates[0] if len(candidates) == 1 else None),
                help_text='Похожие: ' + ', '.join(str(t) for t in a.teacher_candidates) if candidates else '')
            last, first, middle = a.parsed_teacher
            self.fields['new_last_name'] = forms.CharField(label='Фамилия', required=False, initial=last)
            self.fields['new_first_name'] = forms.CharField(label='Имя', required=False, initial=first)
            self.fields['new_middle_name'] = forms.CharField(label='Отчество', required=False, initial=middle)
            self.fields['new_position'] = forms.CharField(label='Должность', required=False,
                                                          initial=a.data.teacher_position)
            self.fields['department'] = forms.ModelChoiceField(
                label='Кафедра нового преподавателя', queryset=departments, required=False,
                initial=a.department.pk if a.department else None)
            self.fields['new_department'] = forms.CharField(
                label='…или новая кафедра', required=False,
                initial='' if a.department else a.data.teacher_department,
                help_text='Создавать новую кафедру может только администратор.')
            if a.data.teacher_department and a.department is None:
                self.fields['add_alias'] = forms.BooleanField(
                    label=f'Запомнить написание «{a.data.teacher_department}» для выбранной кафедры', required=False)

        if a.student_source not in ('work', 'copy'):
            choices = [(str(s.pk), f'{s.full_name}, группа {s.group}') for s in
                       ([a.student] if a.student else []) + a.student_candidates]
            choices.append(('new', 'Создать нового студента'))
            self.fields['student'] = forms.ChoiceField(
                label='Студент', choices=choices, widget=forms.RadioSelect,
                initial=str(a.student.pk) if a.student else 'new')
        if a.student_diff:
            self.fields['update_student'] = forms.BooleanField(
                label='Обновить данные студента значениями из анкеты', required=False, initial=True)
        if a.course_warning:
            self.fields['course'] = forms.TypedChoiceField(
                label=f'Курс (в анкете: «{a.data.course_raw}»)', coerce=int, empty_value=None, required=False,
                choices=[('', 'не указывать')] + [(i, str(i)) for i in range(1, 7)], initial=a.course)

        if a.work is None:
            status_choices = statuses.WorkStatus.choices
            initial = statuses.DEFAULT
        else:
            status_choices = [(s.value, s.label) for s in statuses.allowed_targets(a.work.status)]
            initial = a.work.status
        self.fields['status'] = forms.ChoiceField(
            label='Статус работы', choices=status_choices, initial=initial,
            help_text=f'Текущий статус в анкете (свободный текст): «{a.data.status_comment or "—"}». '
                      'Он сохранится как комментарий к статусу.')
        self.fields['status_note'] = forms.CharField(
            label='Комментарий к смене статуса', required=False,
            help_text='Обязателен при возобновлении. Если заполнен, заменяет комментарий из анкеты.')

        for diff in a.work_diff:
            self.fields[f'keep_{diff.field}'] = forms.ChoiceField(
                label=diff.label + (' — изменено вручную после прошлой загрузки' if diff.manual else ''),
                choices=[('new', 'Значение из анкеты'), ('keep', 'Оставить текущее')], widget=forms.RadioSelect,
                initial='keep' if diff.manual else 'new')
        for achievement in a.achievements_remove:
            self.fields[f'remove_{achievement.pk}'] = forms.BooleanField(
                label=f'Удалить достижение (строка {achievement.source_row}): «{achievement.text[:120]}»',
                required=False, initial=False)
        if any('переиспользована' in w for w in a.warnings):
            self.fields['confirm_reuse'] = forms.BooleanField(
                label='Подтверждаю: обновить работу данными другого студента', required=False)
        # Поля выбора и создания преподавателя показываются в зависимости от режима (скрипт в base.html).
        for name in ('teacher',):
            if name in self.fields:
                self.fields[name].widget.attrs['data_show_when'] = 'teacher_mode=existing'
        for name in ('new_last_name', 'new_first_name', 'new_middle_name', 'new_position', 'department',
                     'new_department', 'add_alias'):
            if name in self.fields:
                self.fields[name].widget.attrs['data_show_when'] = 'teacher_mode=new'
        self.order_fields(['teacher_mode', 'teacher', 'new_last_name', 'new_first_name', 'new_middle_name',
                           'new_position', 'department', 'new_department', 'add_alias', 'student',
                           'update_student', 'course', 'status', 'status_note'])
        # BootstrapMixin проставил классы только полям, объявленным в классе; добавленным — здесь.
        for field in self.fields.values():
            widget = field.widget
            if 'class' not in widget.attrs:
                if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
                    widget.attrs['class'] = 'form-check-input'
                elif isinstance(widget, forms.Select):
                    widget.attrs['class'] = 'form-select'
                else:
                    widget.attrs['class'] = 'form-control'

    def clean(self):
        data = super().clean()
        if not self.teacher_fixed:
            if data.get('teacher_mode') == 'existing' and not data.get('teacher'):
                self.add_error('teacher', 'Выберите преподавателя.')
            if data.get('teacher_mode') == 'new':
                if not data.get('new_last_name') or not data.get('new_first_name'):
                    self.add_error('new_last_name', 'Укажите фамилию и имя.')
                if not data.get('department') and not data.get('new_department'):
                    self.add_error('department', 'Выберите кафедру или укажите новую.')
                elif not data.get('department') and not self.can_create_department:
                    self.add_error('new_department', 'Новую кафедру создаёт администратор; выберите существующую.')
        return data

    def to_decision(self):
        data = self.cleaned_data
        a = self.analysis
        decision = Decision(status=data['status'], status_note=data.get('status_note', ''),
                            note=data.get('note', ''), confirm_reuse=data.get('confirm_reuse', False),
                            course=data['course'] if 'course' in data else a.course,
                            update_student=data.get('update_student', True))
        if self.teacher_fixed:
            decision.teacher_id = a.teacher.pk
        elif data['teacher_mode'] == 'existing':
            decision.teacher_id = data['teacher'].pk
        else:
            decision.new_teacher = {'last_name': data['new_last_name'], 'first_name': data['new_first_name'],
                                    'middle_name': data.get('new_middle_name', ''),
                                    'position': data.get('new_position', '')}
            decision.department_id = data['department'].pk if data.get('department') else None
            decision.new_department_name = '' if data.get('department') else data.get('new_department', '')
        decision.add_alias = data.get('add_alias', False)
        if 'student' in data:
            decision.student_id = None if data['student'] == 'new' else int(data['student'])
            if decision.student_id and not Student.objects.filter(pk=decision.student_id).exists():
                decision.student_id = None
        elif a.student is not None:
            decision.student_id = a.student.pk
        decision.keep_fields = {d.field for d in a.work_diff if data.get(f'keep_{d.field}') == 'keep'}
        decision.remove_achievements = {x.pk for x in a.achievements_remove if data.get(f'remove_{x.pk}')}
        return decision
