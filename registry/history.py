"""История изменений для интерфейса (ТЗ 6.3). Значения контактов скрываются (ТЗ 3.2)."""
from .models import Achievement, Student

HIDDEN = 'скрыто'
SKIP_FIELDS = {'updated_at', 'last_import_snapshot', 'updated_by', 'created_by'}
TYPES = {'+': 'Создание', '~': 'Изменение', '-': 'Удаление'}


def _label(model, name):
    try:
        return str(model._meta.get_field(name).verbose_name)
    except Exception:
        return name


def _display(record, name, value):
    field = record.instance_type._meta.get_field(name)
    if field.choices:
        return dict(field.flatchoices).get(value, value)
    if field.is_relation and value is not None:
        related = field.related_model.objects.filter(pk=value).first()
        return str(related) if related else value
    return value


def _entries(records, model, show_contacts, prefix=''):
    hidden = set(Student.CONTACT_FIELDS) if model is Student and not show_contacts else set()
    result = []
    for record in records:
        changes = []
        previous = record.prev_record
        if previous is not None and record.history_type == '~':
            for change in record.diff_against(previous).changes:
                if change.field in SKIP_FIELDS:
                    continue
                if change.field in hidden:
                    changes.append((_label(model, change.field), HIDDEN, 'изменено'))
                else:
                    changes.append((_label(model, change.field), _display(record, change.field, change.old),
                                    _display(record, change.field, change.new)))
            if not changes:
                continue
        elif record.history_type == '+' and model is Achievement:
            changes.append(('Текст', '', record.text))
        result.append({'date': record.history_date, 'user': record.history_user,
                       'reason': record.history_change_reason or '',
                       'type': f'{prefix}{TYPES.get(record.history_type, record.history_type)}',
                       'changes': changes})
    return result


def history_entries(obj, show_contacts):
    entries = _entries(obj.history.select_related('history_user'), type(obj), show_contacts)
    if hasattr(obj, 'achievements'):
        records = Achievement.history.filter(work_id=obj.pk).select_related('history_user')
        entries += _entries(records, Achievement, show_contacts, prefix='Достижение: ')
    return sorted(entries, key=lambda e: e['date'], reverse=True)
