"""Выбор адаптера по (form_id, schema_version) — ТЗ 4.1, 7.3.

Новая версия формы — новый модуль-адаптер и строка в ADAPTERS; существующие адаптеры не меняются.
"""
import logging

from . import prepod_vnok_info_v2
from .base import ExtractionResult, ImportData, Outcome, ReturnReason

logger = logging.getLogger(__name__)

FORM_ID = 'prepod_vnok_info'
ADAPTERS = {
    (FORM_ID, '2.0'): prepod_vnok_info_v2,
}
# Версии, которые система не поддерживает и не будет: анкету возвращают для заполнения формы 2.0.
OLD_VERSIONS = {'1.0'}
CURRENT = ADAPTERS[(FORM_ID, '2.0')]

OLD_VERSION_MESSAGE = ('Анкета заполнена в устаревшей версии формы ({version}). Данные нужно перенести '
                       'в форму версии 2.0.')

__all__ = ['ExtractionResult', 'ImportData', 'Outcome', 'ReturnReason', 'extract', 'to_neutral']


def _value(fields, name):
    value = fields.get(name, {}).get('/V')
    return '' if value is None else str(value).strip()


def extract(path):
    """Извлечь и проверить анкету. Никогда не бросает исключений: всё — в ExtractionResult."""
    try:
        with open(path, 'rb') as handle:
            head = handle.read(1024)
    except OSError:
        return ExtractionResult(Outcome.REJECT, errors=['Файл не удалось прочитать.'])
    if b'%PDF' not in head:
        return ExtractionResult(Outcome.REJECT, errors=['Это не PDF-файл.'])
    try:
        fields = CURRENT.read_fields(path)
    except ValueError as error:
        if 'XFA' in str(error):
            return ExtractionResult(Outcome.RETURN, FORM_ID, '1.0', return_reason=ReturnReason.OLD_VERSION,
                                    errors=[OLD_VERSION_MESSAGE.format(version='1.0, XFA')])
        return ExtractionResult(Outcome.REJECT, errors=[str(error)])
    except Exception:
        logger.info('PDF не разобран', exc_info=True)
        return ExtractionResult(Outcome.REJECT, errors=['Файл повреждён или не является PDF-формой.'])

    form_id = _value(fields, 'meta.form_id')
    version = _value(fields, 'meta.schema_version')
    if not form_id:
        return ExtractionResult(Outcome.REJECT, errors=[f'Это не форма {FORM_ID}: нет служебного поля формы.'])
    if form_id != FORM_ID:
        return ExtractionResult(Outcome.REJECT, form_id, version, errors=[f'Неподдерживаемая форма: {form_id!r}.'])
    adapter = ADAPTERS.get((form_id, version))
    if adapter is None:
        if version in OLD_VERSIONS:
            return ExtractionResult(Outcome.RETURN, form_id, version, return_reason=ReturnReason.OLD_VERSION,
                                    errors=[OLD_VERSION_MESSAGE.format(version=f'черновик v2.0-draft01, схема {version}')],
                                    student_name=_value(fields, 'student.full_name'),
                                    teacher_name=_value(fields, 'teacher.full_name'))
        return ExtractionResult(Outcome.UNSUPPORTED, form_id, version,
                                errors=[f'Версия схемы данных {version!r} не поддерживается.'])
    try:
        return adapter.extract(path, fields)
    except Exception:
        logger.exception('Ошибка адаптера %s %s', form_id, version)
        return ExtractionResult(Outcome.REJECT, form_id, version, errors=['Не удалось извлечь данные из формы.'])


def to_neutral(document):
    """Нейтральная структура из сохранённого JSON загрузки (для повторной обработки)."""
    adapter = ADAPTERS.get((document.form_id, document.schema_version))
    if adapter is None or not document.extracted:
        return None
    return adapter.to_neutral(document.extracted)
