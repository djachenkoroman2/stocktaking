"""Текст возврата анкеты преподавателю (ТЗ 7.7)."""
from django.utils import timezone

from .adapters import ReturnReason

REQUIRED_SUFFIX = ' — обязательное поле не заполнено.'


def advice(error):
    """Ошибка check() → что исправить, понятными словами."""
    if error.endswith(REQUIRED_SUFFIX):
        label = error[:-len(REQUIRED_SUFFIX)]
        return f'Заполните поле «{label}» (оно обязательное, отмечено звёздочкой).'
    if error.startswith('Дата заполнения:'):
        return 'Укажите дату заполнения в формате ДД.ММ.ГГГГ, например 07.10.2026, или оставьте поле пустым.'
    if error.startswith('Электронная почта:'):
        return 'Укажите адрес электронной почты полностью и без пробелов, например student@example.org.'
    return ''


def build_return_message(document, reason):
    lines = ['Анкета «Информация о студенте (курсанте)» возвращена на исправление.', '']
    if document.student_name:
        lines.append(f'Студент (курсант): {document.student_name}')
    if document.teacher_name:
        lines.append(f'Преподаватель: {document.teacher_name}')
    if document.questionnaire_id:
        lines.append(f'ID анкеты: {document.questionnaire_id}')
    lines.append(f'Файл: {document.original_name}')
    lines.append(f'Загружен: {timezone.localtime(document.uploaded_at):%d.%m.%Y}')
    lines.append('')
    if reason == ReturnReason.CHECK:
        lines.append('Что нужно исправить:')
        for number, error in enumerate(document.errors, 1):
            hint = advice(error)
            lines.append(f'{number}. {error}' + (f' {hint}' if hint else ''))
        lines += ['', 'Исправьте эти поля в том же файле и пришлите его снова.']
    elif reason == ReturnReason.NO_ID:
        lines += ['Анкета заполнена в копии формы без идентификатора, поэтому её нельзя принять.',
                  'Вам пришлют новую копию формы. Перенесите в неё данные и пришлите заполненную новую копию.']
    else:
        lines += [*document.errors,
                  'Вам пришлют новую копию формы. Перенесите в неё данные и пришлите заполненную новую копию.']
    lines += ['', 'Сохраняйте файл командой «Сохранить» (в Chrome и Edge — «Скачать» → «С изменениями»). '
                  'Не используйте «Печать → Сохранить как PDF»: получится файл без полей, который нельзя обработать.']
    return '\n'.join(lines)


def batch_return_text(documents):
    """Общий текст по всем анкетам к возврату, сгруппированный по преподавателям."""
    groups = {}
    for document in documents:
        groups.setdefault(document.teacher_name or 'Преподаватель не указан', []).append(document)
    parts = []
    for teacher in sorted(groups):
        parts.append(f'===== {teacher} =====')
        for document in groups[teacher]:
            parts += [document.return_message, '-----']
        parts.append('')
    return '\n'.join(parts)
