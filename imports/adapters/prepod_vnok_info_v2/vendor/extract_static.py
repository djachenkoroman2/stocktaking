#!/usr/bin/env python3
"""Extract the one-student AcroForm as JSON (data schema 2.0), without OCR."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import uuid

from pypdf import PdfReader

from acroform import iter_terminal_fields

FORM_ID = 'prepod_vnok_info'
SCHEMA_VERSION = '2.0'
REQUIRED = {'last_name': 'Фамилия', 'first_name': 'Имя', 'group_code': 'Шифр группы', 'phone': 'Телефон',
            'email': 'Электронная почта', 'task': 'Задача'}
STUDENT_FIELDS = ('last_name', 'first_name', 'middle_name', 'course', 'group_code', 'phone', 'email', 'task',
                  'schedule', 'expected_results', 'status')
EMAIL = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
DATE = re.compile(r'^\d{2}\.\d{2}\.\d{4}$')
COURSE = re.compile(r'^[1-6]$')
ISO_DATE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')


def normalize_date(value):
    """Firefox (PDF.js) saves date fields as YYYY-MM-DD; bring a valid one to ДД.ММ.ГГГГ."""
    match = ISO_DATE.match(value.strip())
    if not match:
        return value
    year, month, day = match.groups()
    try:
        datetime(int(year), int(month), int(day))
    except ValueError:
        return value
    return f'{day}.{month}.{year}'


def read_fields(path):
    acroform = PdfReader(path).trailer['/Root'].get('/AcroForm')
    if acroform is None:
        raise ValueError('В PDF нет полей формы (возможно, он получен печатью в PDF).')
    acroform = acroform.get_object()
    if '/XFA' in acroform:
        raise ValueError('Это XFA-версия формы (v1.0); используйте src/extract_data.py.')
    return dict(iter_terminal_fields(acroform.get('/Fields', [])))


def extract_data(path, assign_id=False):
    fields = read_fields(path)

    def text(name):
        if name not in fields:
            raise ValueError(f'В форме нет поля {name}; это не форма {FORM_ID} на одного студента схемы {SCHEMA_VERSION}.')
        value = fields[name].get('/V')
        value = '' if value is None else str(value)
        return value.replace('\r\n', '\n').replace('\r', '\n')

    meta = {'form_id': text('meta.form_id'), 'schema_version': text('meta.schema_version')}
    if meta['form_id'] != FORM_ID:
        raise ValueError(f'Неподдерживаемая форма: {meta["form_id"]!r}.')
    if meta['schema_version'] == '1.0':
        raise ValueError('Файл заполнен в черновике v2.0-draft01 (схема данных 1.0: одно поле ФИО, расписание '
                         'по строкам). Этот обработчик читает схему 2.0; перенесите данные в форму v2.0-draft02 '
                         'или новее.')
    if meta['schema_version'] != SCHEMA_VERSION:
        raise ValueError(f'Неподдерживаемая версия схемы данных: {meta["schema_version"]!r}.')
    student_id = text('student.id').strip()
    if not student_id:
        if not assign_id:
            raise ValueError('ID анкеты не назначен. Готовьте копии командой prepare_copy.py '
                             'или укажите --assign-id для временного идентификатора.')
        student_id = f'student-unassigned-{uuid.uuid4()}'
        print(f'Предупреждение: назначен временный ID {student_id}; он не записан в PDF.', file=sys.stderr)

    achievements = []
    row = 1
    while f'achievements.{row}.text' in fields:
        value = text(f'achievements.{row}.text')
        if value.strip():
            achievements.append({'id': f'achievement-{row}', 'text': value})
        row += 1
    student = {'id': student_id}
    student.update({key: text('student.' + key) for key in STUDENT_FIELDS})
    student['achievements'] = achievements
    student['notes'] = text('student.notes')
    return {'schema_version': SCHEMA_VERSION, 'form_id': FORM_ID,
            'date_filled': normalize_date(text('meta.date_filled')),
            'teacher': {key: text('teacher.' + key) for key in ('full_name', 'position', 'department')},
            'students': [student]}


def valid_date(value):
    if not DATE.match(value):
        return False
    try:
        datetime.strptime(value, '%d.%m.%Y')
    except ValueError:
        return False
    return True


def check(data):
    """Checks the form itself cannot run without JavaScript. Returns (errors, warnings)."""
    errors, warnings = [], []
    date = data['date_filled'].strip()
    if date and not valid_date(date):
        errors.append(f'Дата заполнения: ожидается существующая дата в формате ДД.ММ.ГГГГ, указано {date!r}.')
    for student in data['students']:
        for key, label in REQUIRED.items():
            if not student[key].strip():
                errors.append(f'{label} — обязательное поле не заполнено.')
        if student['email'].strip() and not EMAIL.match(student['email'].strip()):
            errors.append('Электронная почта: неверный формат адреса.')
        course = student['course'].strip()
        if course and not COURSE.match(course):
            warnings.append(f'Курс: ожидается целое число от 1 до 6, указано {course!r}.')
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--output', type=Path, help='Новый JSON-файл; существующие файлы не перезаписываются.')
    parser.add_argument('--assign-id', action='store_true', help='Временный ID, если копия не была подготовлена.')
    parser.add_argument('--check', action='store_true',
                        help='Проверить обязательные поля и форматы; код 2 при ошибках (предупреждения не влияют).')
    args = parser.parse_args()
    try:
        data = extract_data(args.pdf, args.assign_id)
        result = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            with args.output.open('x', encoding='utf-8') as output:
                output.write(result)
        else:
            sys.stdout.write(result)
    except Exception as error:
        parser.exit(1, f'Ошибка извлечения: {error}\n')
    if args.check:
        errors, warnings = check(data)
        for message in errors:
            print('Ошибка: ' + message, file=sys.stderr)
        for message in warnings:
            print('Предупреждение: ' + message, file=sys.stderr)
        if errors:
            sys.exit(2)


if __name__ == '__main__':
    main()
