"""Паритет копии extract_static.py с проектом формы (ТЗ 7.3, 12.1).

Ожидания — из /home/roman/src/forms/forms/prepod_vnok_info/examples/README.md (проверено 08.10.2026).
"""
import hashlib
from pathlib import Path

import pytest

from imports.adapters import prepod_vnok_info_v2 as adapter
from tests.conftest import EXAMPLES

extract_static = adapter.extract_static
VENDOR = Path(adapter.__file__).with_name('vendor')

EXPECTED = {
    '01': (0, []), '02': (0, []), '03': (0, []), '04': (0, []), '05': (0, []), '06': (0, []), '07': (0, []),
    '08': (0, ["Предупреждение: Курс: ожидается целое число от 1 до 6, указано 'II'."]),
    '09': (2, ["Ошибка: Дата заполнения: ожидается существующая дата в формате ДД.ММ.ГГГГ, указано '31.02.2026'.",
               'Ошибка: Электронная почта: неверный формат адреса.']),
    '10': (2, ['Ошибка: Телефон — обязательное поле не заполнено.', 'Ошибка: Задача — обязательное поле не заполнено.']),
    '11': (0, []), '12': (0, []), '13': (0, []), '14': (0, []), '15': (0, []),
    '16': (0, ["Предупреждение: Курс: ожидается целое число от 1 до 6, указано '1 курс'."]),
    '17': (2, ["Ошибка: Дата заполнения: ожидается существующая дата в формате ДД.ММ.ГГГГ, указано '7.10.2026'."]),
    '18': (2, ['Ошибка: Фамилия — обязательное поле не заполнено.', 'Ошибка: Имя — обязательное поле не заполнено.']),
    '19': (2, ['Ошибка: Электронная почта: неверный формат адреса.']),
    '20': (1, ['Ошибка извлечения: ID анкеты не назначен. Готовьте копии командой prepare_copy.py '
               'или укажите --assign-id для временного идентификатора.']),
}
VENDOR_SHA256 = {
    'acroform.py': 'ac8b59386d9c9ba69ddc35781999f6223eda7a4b599163ac29a56e3736ccea2c',
    'extract_static.py': '42c59f3f3e559168c43f74a3b9c6e6a0f41cc0b86d75d634d53a75f795ba05f0',
    'prepare_copy.py': 'ebd15214b88da34c99f051349fbfc07660b9d5d2c7bdf4e049e38e1e6e8c782b',
}


def run_check(path):
    """То же, что `extract_static.py --check`: (код выхода, строки stderr)."""
    try:
        data = extract_static.extract_data(path)
    except Exception as error:
        return 1, [f'Ошибка извлечения: {error}'], None
    errors, warnings = extract_static.check(data)
    lines = ['Ошибка: ' + e for e in errors] + ['Предупреждение: ' + w for w in warnings]
    return (2 if errors else 0), lines, data


def test_vendor_copies_are_unchanged():
    for name, digest in VENDOR_SHA256.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == digest, name


@pytest.mark.parametrize('path', sorted(EXAMPLES.glob('*.pdf')), ids=lambda p: p.stem)
def test_examples_match_form_project(path):
    code, lines, data = run_check(path)
    assert (code, lines) == EXPECTED[path.name[:2]]
    if data is not None:
        assert data['students'][0]['id'] == f'student-example-{path.name[:2]}'


def test_specific_values():
    _, _, data = run_check(EXAMPLES / '06-firefox-iso-date.pdf')
    assert data['date_filled'] == '30.09.2026'
    _, _, data = run_check(EXAMPLES / '13-acrobat-line-breaks.pdf')
    assert '\r' not in data['students'][0]['schedule'] + data['students'][0]['task']
    _, _, data = run_check(EXAMPLES / '07-portfolio-gaps.pdf')
    assert [a['id'] for a in data['students'][0]['achievements']] == ['achievement-1', 'achievement-4', 'achievement-7']
