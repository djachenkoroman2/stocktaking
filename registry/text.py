"""Нормализация строк для сравнения (ТЗ 5.3) и разбор ФИО (ТЗ 7.5)."""
from datetime import date
import re

_SPACES = re.compile(r'\s+')
_ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6}


def norm(value):
    """Ключ сравнения: без учёта регистра, ё = е, неразрывный пробел = пробел, пробелы сжаты."""
    value = (value or '').replace(' ', ' ').replace('ё', 'е').replace('Ё', 'Е')
    return _SPACES.sub(' ', value).strip().casefold()


def clean(value):
    """Значение для хранения: обрезка пробелов по краям; одни пробелы — пустая строка."""
    return (value or '').strip()


def split_full_name(full_name):
    """«Фамилия Имя Отчество» → (фамилия, имя, отчество); инициалы разбираются так же."""
    parts = clean(full_name).replace(' ', ' ').split()
    if not parts:
        return '', '', ''
    if len(parts) == 1:
        return parts[0], '', ''
    # «Иванов И.И.» → имя «И.», отчество «И.»
    if len(parts) == 2 and re.fullmatch(r'(\w\.){2}', parts[1]):
        return parts[0], parts[1][:2], parts[1][2:]
    return parts[0], parts[1], ' '.join(parts[2:])


def suggest_course(raw):
    """Предложение курса для предупреждения check(): «II» → 2, «1 курс» → 1, иначе None."""
    value = clean(raw)
    if not value:
        return None
    match = re.match(r'^(\d+)', value)
    if match:
        number = int(match.group(1))
        return number if 1 <= number <= 6 else None
    word = value.split()[0].upper()
    return _ROMAN.get(word)


def academic_year(day: date):
    """Учебный год с 1 сентября: 30.09.2026 → «2026/2027», 15.03.2027 → «2026/2027»."""
    start = day.year if day.month >= 9 else day.year - 1
    return f'{start}/{start + 1}'


def full_name(last, first, middle=''):
    return ' '.join(part for part in (last, first, middle) if part)


def short_name(last, first, middle=''):
    initials = ''.join(f'{part[0]}.' for part in (first, middle) if part)
    return f'{last} {initials}'.strip()
