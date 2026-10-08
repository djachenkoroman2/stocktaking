#!/usr/bin/env python3
"""Make a personal copy of the blank form: assign a unique ID and optionally prefill the teacher."""
import argparse
from pathlib import Path
import uuid

from pypdf import PdfReader, PdfWriter

from acroform import set_values
from extract_static import read_fields


def prepare_copy(source, target, student_id=None, teacher_name=None, teacher_position=None,
                 teacher_department=None):
    fields = read_fields(source)
    if 'student.id' not in fields:
        raise ValueError('Это не форма prepod_vnok_info на одного студента.')
    if str(fields['student.id'].get('/V') or '').strip():
        raise ValueError('У копии уже есть ID анкеты; берите пустую форму, чтобы ID не повторялись.')
    values = {'student.id': student_id or f'student-{uuid.uuid4()}'}
    if teacher_name is not None:
        values['teacher.full_name'] = teacher_name
    if teacher_position is not None:
        values['teacher.position'] = teacher_position
    if teacher_department is not None:
        values['teacher.department'] = teacher_department
    writer = PdfWriter(clone_from=PdfReader(source))
    set_values(writer, values)
    target = Path(target)
    with target.open('xb') as output:
        writer.write(output)
    return target, values['student.id']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Пустая форма (PDF).')
    parser.add_argument('output', type=Path, help='Новый файл; существующие файлы не перезаписываются.')
    parser.add_argument('--student-id', help='Свой ID; по умолчанию student-<UUID>.')
    parser.add_argument('--teacher-name')
    parser.add_argument('--teacher-position')
    parser.add_argument('--teacher-department')
    args = parser.parse_args()
    try:
        path, identifier = prepare_copy(args.source, args.output, args.student_id, args.teacher_name,
                                        args.teacher_position, args.teacher_department)
    except Exception as error:
        parser.exit(1, f'Ошибка: {error}\n')
    print(f'{path}\tID {identifier}')
