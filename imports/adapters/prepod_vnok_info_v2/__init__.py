"""Адаптер формы prepod_vnok_info, схема данных 2.0.

Модули в vendor/ — копии из проекта формы без изменений (см. vendor/README.md). Они импортируют
друг друга по короткому имени, поэтому каталог vendor добавляется в sys.path.
"""
from datetime import datetime
from pathlib import Path
import sys

from ..base import ExtractionResult, ImportData, Outcome, ReturnReason

_VENDOR = str(Path(__file__).with_name('vendor'))
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import extract_static  # noqa: E402
import prepare_copy as _prepare_copy  # noqa: E402

FORM_ID = extract_static.FORM_ID
SCHEMA_VERSION = extract_static.SCHEMA_VERSION
read_fields = extract_static.read_fields


def _field(fields, name):
    value = fields.get(name, {}).get('/V')
    return '' if value is None else str(value).strip()


def _parse_date(value):
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, '%d.%m.%Y').date()
    except ValueError:
        return None


def to_neutral(extracted):
    """JSON схемы 2.0 → нейтральная структура. Значения не меняются, кроме обрезки пробелов (ТЗ 5.3)."""
    student = extracted['students'][0]
    teacher = extracted['teacher']
    return ImportData(
        questionnaire_id=student['id'].strip(),
        date_filled=_parse_date(extracted['date_filled']),
        date_filled_raw=extracted['date_filled'],
        teacher_full_name=teacher['full_name'].strip(),
        teacher_position=teacher['position'].strip(),
        teacher_department=teacher['department'].strip(),
        last_name=student['last_name'].strip(),
        first_name=student['first_name'].strip(),
        middle_name=student['middle_name'].strip(),
        course_raw=student['course'].strip(),
        group_code=student['group_code'].strip(),
        phone=student['phone'].strip(),
        email=student['email'].strip(),
        task=student['task'].strip('\n').rstrip(),
        schedule=student['schedule'].strip('\n').rstrip(),
        expected_results=student['expected_results'].strip('\n').rstrip(),
        status_comment=student['status'].strip(),
        notes=student['notes'].strip('\n').rstrip(),
        achievements=[(int(item['id'].rsplit('-', 1)[1]), item['text'].strip()) for item in student['achievements']],
    )


def extract(path, fields):
    names = {'student_name': ' '.join(filter(None, (_field(fields, 'student.last_name'),
                                                    _field(fields, 'student.first_name'),
                                                    _field(fields, 'student.middle_name')))),
             'teacher_name': _field(fields, 'teacher.full_name')}
    try:
        extracted = extract_static.extract_data(path)
    except ValueError as error:
        message = str(error)
        if 'ID анкеты не назначен' in message:
            return ExtractionResult(Outcome.RETURN, FORM_ID, SCHEMA_VERSION,
                                    errors=['ID анкеты не назначен: копия формы не подготовлена через систему.'],
                                    return_reason=ReturnReason.NO_ID, **names)
        return ExtractionResult(Outcome.REJECT, FORM_ID, SCHEMA_VERSION, errors=[message], **names)
    errors, warnings = extract_static.check(extracted)
    data = to_neutral(extracted)
    return ExtractionResult(
        Outcome.RETURN if errors else Outcome.OK, FORM_ID, SCHEMA_VERSION,
        questionnaire_id=data.questionnaire_id, extracted=extracted, data=data,
        errors=errors, warnings=warnings, return_reason=ReturnReason.CHECK if errors else None, **names)


def prepare_copy(source, target, student_id, teacher_name, teacher_position, teacher_department):
    return _prepare_copy.prepare_copy(source, target, student_id=student_id, teacher_name=teacher_name,
                                      teacher_position=teacher_position, teacher_department=teacher_department)
