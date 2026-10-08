"""Нейтральная структура импорта (ТЗ 7.3): не зависит от версии формы."""
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum


class Outcome(str, Enum):
    OK = 'ok'                    # данные извлечены, ошибок проверки нет
    RETURN = 'return'            # анкету нужно вернуть преподавателю
    UNSUPPORTED = 'unsupported'  # форма известна, версия схемы — нет
    REJECT = 'reject'            # не PDF, не форма, другая форма


class ReturnReason(str, Enum):
    CHECK = 'check'              # ошибки check()
    NO_ID = 'no_id'              # копия не подготовлена через prepare_copy
    OLD_VERSION = 'old_version'  # XFA 1.0 или draft01


@dataclass
class ImportData:
    questionnaire_id: str = ''
    date_filled: date | None = None
    date_filled_raw: str = ''
    teacher_full_name: str = ''
    teacher_position: str = ''
    teacher_department: str = ''
    last_name: str = ''
    first_name: str = ''
    middle_name: str = ''
    course_raw: str = ''
    group_code: str = ''
    phone: str = ''
    email: str = ''
    task: str = ''
    schedule: str = ''
    expected_results: str = ''
    status_comment: str = ''
    notes: str = ''
    achievements: list[tuple[int, str]] = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


@dataclass
class ExtractionResult:
    outcome: Outcome
    form_id: str = ''
    schema_version: str = ''
    questionnaire_id: str = ''
    extracted: dict | None = None
    data: ImportData | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    return_reason: ReturnReason | None = None
    student_name: str = ''
    teacher_name: str = ''
