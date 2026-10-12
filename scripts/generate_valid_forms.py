#!/usr/bin/env python3
"""Набор заполненных анкет prepod_vnok_info 2.0 без ошибок (samples/valid-forms/README.md).

Одна кафедра, 20 преподавателей, у каждого случайно 3–5 студентов (курсантов); один файл — один студент.
Все данные вымышлены. Распределение и тексты задаются зерном SEED: повторный запуск даёт те же данные,
те же ID анкет и те же байты PDF. Каждое значение проверяется до записи: анкета проходит
extract_static.py --check без ошибок и предупреждений, а текст умещается в видимую область поля.

Пишет в каталог набора: PDF, valid-forms.zip (всё одним файлом для загрузки), expected.json (ожидаемые
данные и SHA-256 файлов), README.md. Существующие PDF перезаписываются только с --force.

    .venv/bin/python scripts/generate_valid_forms.py [--force] [--out samples/valid-forms]
"""
import argparse
from datetime import date, timedelta
import hashlib
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'imports' / 'adapters' / 'prepod_vnok_info_v2' / 'vendor'))

from pypdf import PdfReader, PdfWriter  # noqa: E402

from acroform import FF_MULTILINE, FONT_KEY, EmbeddedFont, font_size, iter_terminal_fields, set_values  # noqa: E402
from extract_static import check, extract_data  # noqa: E402
from prepare_copy import prepare_copy  # noqa: E402

SEED = 20261012
FORM = ROOT / 'tests' / 'fixtures' / 'forms' / 'prepod_vnok_info-v2.0-draft04.pdf'
OUT = ROOT / 'samples' / 'valid-forms'
ZIP_NAME = 'valid-forms.zip'
DEPARTMENT = 'Кафедра прикладной математики и информатики'
TODAY = date(2026, 10, 12)  # дата подготовки набора: даты заполнения не позже неё
FIRST_DAY = date(2026, 9, 1)
STUDENTS_PER_TEACHER = (3, 5)
STUDENT_KEYS = ('last_name', 'first_name', 'middle_name', 'course', 'group_code', 'phone', 'email', 'task',
                'schedule', 'expected_results', 'status', 'notes')

# Направления: темы работ, этапы реализации, ожидаемые результаты, профильные достижения.
AREAS = {
    'numeric': {
        'title': 'вычислительная математика',
        'topics': ['Метод конечных элементов для задачи теплопроводности в неоднородной среде',
                   'Итерационные методы решения разреженных систем линейных уравнений',
                   'Численное решение жёстких систем обыкновенных дифференциальных уравнений',
                   'Сплайн-аппроксимация экспериментальных данных с шумом',
                   'Параллельные алгоритмы умножения больших матриц на видеокартах',
                   'Разностные схемы для уравнения переноса с разрывными решениями',
                   'Адаптивные сетки для задач с пограничным слоем'],
        'impl': 'Реализация метода на C++ с проверкой на модельных задачах',
        'experiment': 'Вычислительные эксперименты: точность, сходимость, время счёта',
        'results': ['программная реализация метода с набором тестовых задач',
                    'сравнение с методами из библиотек SciPy и PETSc',
                    'оценки погрешности и порядка сходимости',
                    'доклад на студенческой конференции'],
        'achievements': ['Диплом II степени конкурса студенческих работ «Вычислительная математика — 2026».',
                         'Программа расчёта зарегистрирована в фонде алгоритмов университета.']},
    'ml': {
        'title': 'машинное обучение',
        'topics': ['Классификация медицинских изображений свёрточными нейронными сетями',
                   'Распознавание именованных сущностей в научных текстах на русском языке',
                   'Прогнозирование нагрузки на городскую транспортную сеть',
                   'Обнаружение аномалий в журналах информационных систем',
                   'Рекомендательная система учебных курсов для студентов',
                   'Сжатие нейронных сетей для работы на мобильных устройствах',
                   'Автоматическая проверка решений задач по программированию'],
        'impl': 'Подготовка набора данных и обучение моделей на PyTorch',
        'experiment': 'Сравнение моделей по точности, полноте и скорости работы',
        'results': ['обученная модель и воспроизводимый код эксперимента',
                    'размеченный набор данных с описанием',
                    'сравнение с базовыми моделями на открытых наборах',
                    'статья в сборнике студенческих работ'],
        'achievements': ['Призёр хакатона по анализу данных «Цифровой прорыв» (региональный этап, 2026).',
                         'Решение вошло в 10 % лучших в соревновании по классификации текстов.']},
    'optimization': {
        'title': 'методы оптимизации',
        'topics': ['Метаэвристики для задачи составления расписания занятий',
                   'Задача маршрутизации транспорта с временными окнами',
                   'Градиентные методы для негладких задач выпуклой оптимизации',
                   'Оптимальное размещение базовых станций сотовой связи',
                   'Многокритериальная оптимизация портфеля проектов',
                   'Целочисленное программирование в планировании производства'],
        'impl': 'Реализация алгоритмов и решателя на Python',
        'experiment': 'Сравнение с точными методами на тестовых наборах задач',
        'results': ['библиотека алгоритмов с документацией',
                    'таблица сравнения качества решений и времени счёта',
                    'рекомендации по выбору параметров алгоритмов',
                    'доклад на семинаре кафедры'],
        'achievements': ['Победитель внутривузовского конкурса проектов по исследованию операций (2026).',
                         'Алгоритм составления расписания внедрён на кафедре в тестовом режиме.']},
    'statistics': {
        'title': 'теория вероятностей и математическая статистика',
        'topics': ['Байесовские модели для анализа результатов экзаменов',
                   'Непараметрические критерии однородности для малых выборок',
                   'Моделирование временных рядов потребления электроэнергии',
                   'Статистический анализ успеваемости студентов первого курса',
                   'Методы бутстрепа для оценки доверительных интервалов',
                   'Модели выживаемости в задаче оттока клиентов'],
        'impl': 'Реализация методов на R и Python, подготовка данных',
        'experiment': 'Моделирование методом Монте-Карло и анализ реальных данных',
        'results': ['отчёт со статистическим анализом и выводами',
                    'воспроизводимый код анализа',
                    'сравнение мощности критериев на моделированных данных',
                    'тезисы доклада'],
        'achievements': ['Лучший доклад секции «Статистика» студенческой конференции университета (2026).',
                         'Участник школы-семинара «Статистические методы анализа данных».']},
    'se': {
        'title': 'программная инженерия',
        'topics': ['Мобильное приложение для учёта посещаемости занятий',
                   'Автоматизация тестирования веб-приложений кафедры',
                   'Система электронной очереди для приёмной комиссии',
                   'Сервис проверки оформления студенческих работ',
                   'Статический анализ кода студенческих проектов на Python',
                   'Микросервисная архитектура системы бронирования аудиторий'],
        'impl': 'Проектирование и разработка приложения, модульные тесты',
        'experiment': 'Опытная эксплуатация на кафедре и сбор отзывов',
        'results': ['работающее приложение с исходным кодом и инструкцией',
                    'техническое задание и проектная документация',
                    'отчёт об опытной эксплуатации',
                    'доклад на конференции'],
        'achievements': ['Проект отобран в акселератор студенческих стартапов университета (2026).',
                         'Приложение используется на кафедре для учёта посещаемости.']},
    'networks': {
        'title': 'компьютерные сети и защита информации',
        'topics': ['Обнаружение сетевых атак по статистике трафика',
                   'Моделирование протоколов маршрутизации в беспроводных сетях',
                   'Анализ защищённости веб-приложений университета',
                   'Криптографические протоколы для электронного голосования',
                   'Мониторинг локальной сети кафедры на базе открытого ПО',
                   'Защита умного дома от атак через беспроводные интерфейсы'],
        'impl': 'Развёртывание стенда и реализация программных модулей',
        'experiment': 'Эксперименты на стенде и анализ результатов',
        'results': ['стенд и программные модули с описанием',
                    'отчёт об эксперименте с рекомендациями',
                    'методические указания к лабораторной работе',
                    'тезисы доклада'],
        'achievements': ['Команда — призёр соревнований по информационной безопасности CTF (2026).',
                         'Сертификат курса «Основы сетевых технологий».']},
    'databases': {
        'title': 'базы данных',
        'topics': ['Оптимизация запросов к базе данных электронного деканата',
                   'Хранилище данных для анализа приёмной кампании',
                   'Полнотекстовый поиск по архиву выпускных работ',
                   'Миграция учебной базы данных в облачную СУБД',
                   'Графовая база данных связей научных публикаций кафедры',
                   'Версионирование данных в учебных информационных системах'],
        'impl': 'Проектирование схемы данных и реализация на PostgreSQL',
        'experiment': 'Нагрузочное тестирование и сравнение вариантов',
        'results': ['схема базы данных и скрипты развёртывания',
                    'отчёт о производительности запросов',
                    'прототип интерфейса для пользователей',
                    'доклад на семинаре кафедры'],
        'achievements': ['Сертификат курса «Администрирование PostgreSQL».',
                         'Прототип хранилища данных передан в отдел приёмной комиссии.']},
    'education': {
        'title': 'методика преподавания информатики',
        'topics': ['Онлайн-тренажёр по алгоритмам для школьников',
                   'Геймификация курса «Основы программирования»',
                   'Автоматическая генерация вариантов контрольных работ',
                   'Цифровые лаборатории по физике на базе микроконтроллеров',
                   'Адаптивное тестирование по дискретной математике',
                   'Визуализация алгоритмов на графах для первокурсников'],
        'impl': 'Разработка учебных материалов и программной платформы',
        'experiment': 'Апробация в группе школьников и анализ результатов',
        'results': ['учебные материалы и программная платформа',
                    'результаты апробации с выводами',
                    'методические рекомендации для преподавателей',
                    'статья в сборнике'],
        'achievements': ['Вожатый проектной смены для школьников «IT-лето» (2026).',
                         'Материалы курса опубликованы на образовательном портале университета.']},
}

TEACHERS = [
    ('Вершинина Лариса Аркадьевна', 'Заведующий кафедрой, доктор физико-математических наук, профессор', 'numeric'),
    ('Головин Станислав Эдуардович', 'Профессор, доктор технических наук', 'ml'),
    ('Рябинина Ирина Всеволодовна', 'Профессор, доктор физико-математических наук', 'optimization'),
    ('Тихомиров Аркадий Львович', 'Профессор, доктор технических наук, профессор', 'networks'),
    ('Даниленко Вадим Петрович', 'Доцент, кандидат технических наук', 'se'),
    ('Ефремова Наталья Георгиевна', 'Доцент, кандидат физико-математических наук, доцент', 'statistics'),
    ('Журавлёв Олег Борисович', 'Доцент, кандидат технических наук, доцент', 'networks'),
    ('Исаева Камила Рустамовна', 'Доцент, кандидат педагогических наук', 'education'),
    ('Королёв Павел Андреевич', 'Доцент, кандидат физико-математических наук', 'numeric'),
    ('Лебедева Светлана Олеговна', 'Доцент, кандидат технических наук', 'databases'),
    ('Макаров Егор Валентинович', 'Старший преподаватель, кандидат технических наук', 'ml'),
    ('Нестерова Алина Викторовна', 'Старший преподаватель', 'se'),
    ('Орлов Денис Сергеевич', 'Старший преподаватель', 'networks'),
    ('Пахомова Юлия Игоревна', 'Старший преподаватель, кандидат физико-математических наук', 'statistics'),
    ('Румянцев Артур Маратович', 'Старший преподаватель', 'databases'),
    ('Савельева Ксения Дмитриевна', 'Ассистент', 'optimization'),
    ('Титов Роман Алексеевич', 'Ассистент', 'ml'),
    ('Уварова Елена Николаевна', 'Ассистент', 'numeric'),
    ('Фомин Григорий Ильич', 'Ассистент', 'se'),
    ('Шестакова Вера Павловна', 'Ассистент, кандидат технических наук', 'education'),
]

SURNAMES = ['Агеев', 'Белов', 'Борисов', 'Валиев', 'Васильев', 'Воробьёв', 'Гаврилов', 'Голубев', 'Громов',
            'Давыдов', 'Дементьев', 'Дорофеев', 'Жуков', 'Зайцев', 'Зуев', 'Игнатьев', 'Калинин', 'Карпов',
            'Климов', 'Комаров', 'Кудрявцев', 'Куликов', 'Лапин', 'Логинов', 'Лукин', 'Майоров', 'Мартынов',
            'Медведев', 'Миронов', 'Назаров', 'Никитин', 'Носков', 'Овчинников', 'Осипов', 'Павлов', 'Панов',
            'Пестов', 'Поляков', 'Пономарёв', 'Прохоров', 'Родионов', 'Рожков', 'Рыбаков', 'Сафонов',
            'Селезнёв', 'Симонов', 'Субботин', 'Суханов', 'Тимофеев', 'Третьяков', 'Устинов', 'Федосеев',
            'Филатов', 'Фролов', 'Харитонов', 'Цветков', 'Чернов', 'Шубин', 'Щербаков', 'Юдин', 'Яковлев',
            'Ястребов', 'Белоусов', 'Вишневский', 'Корецкий', 'Савицкий']
MALE_NAMES = ['Александр', 'Алексей', 'Андрей', 'Антон', 'Арсений', 'Богдан', 'Вадим', 'Виктор', 'Владимир',
              'Всеволод', 'Георгий', 'Даниил', 'Денис', 'Дмитрий', 'Евгений', 'Егор', 'Захар', 'Иван', 'Игорь',
              'Константин', 'Максим', 'Матвей', 'Михаил', 'Никита', 'Олег', 'Павел', 'Платон', 'Роман',
              'Сергей', 'Степан', 'Тимур', 'Фёдор', 'Юрий', 'Ярослав']
FEMALE_NAMES = ['Александра', 'Алина', 'Алиса', 'Анастасия', 'Анна', 'Валерия', 'Варвара', 'Вера', 'Виктория',
                'Дарья', 'Диана', 'Екатерина', 'Елизавета', 'Ксения', 'Любовь', 'Маргарита', 'Марина', 'Милана',
                'Надежда', 'Ольга', 'Полина', 'Софья', 'Таисия', 'Ульяна', 'Яна']
PATRONYMICS = [('Александрович', 'Александровна'), ('Алексеевич', 'Алексеевна'), ('Андреевич', 'Андреевна'),
               ('Борисович', 'Борисовна'), ('Васильевич', 'Васильевна'), ('Викторович', 'Викторовна'),
               ('Владимирович', 'Владимировна'), ('Геннадьевич', 'Геннадьевна'), ('Дмитриевич', 'Дмитриевна'),
               ('Евгеньевич', 'Евгеньевна'), ('Иванович', 'Ивановна'), ('Игоревич', 'Игоревна'),
               ('Константинович', 'Константиновна'), ('Михайлович', 'Михайловна'), ('Николаевич', 'Николаевна'),
               ('Олегович', 'Олеговна'), ('Павлович', 'Павловна'), ('Петрович', 'Петровна'),
               ('Сергеевич', 'Сергеевна'), ('Юрьевич', 'Юрьевна'), ('Ильдарович', 'Ильдаровна'),
               ('Русланович', 'Руслановна')]
FOREIGN = [('Чжан', 'Вэй'), ('Тран', 'Тхи Лан'), ('Сингх', 'Арджун'), ('Мендес', 'Лусия'), ('Окафор', 'Чиди'),
           ('Ли', 'Мин Чжу'), ('Пак', 'Джи Хун'), ('Абебе', 'Мекдес')]
FOREIGN_NOTE = 'Иностранный студент; консультации на русском языке, термины дублируются на английском.'

# Чтобы набор можно было загрузить в одну базу с 20 примерами (tests/fixtures/examples), их ФИО не
# повторяются: совпадение фамилии преподавателя дало бы «неоднозначного» преподавателя.
EXAMPLE_TEACHER_SURNAMES = {'Белозёрова', 'Сорокопудов', 'Кочетов', 'Ладыгина', 'Мирошниченко'}
EXAMPLE_STUDENT_SURNAMES = {'Ветрова', 'Гусев', 'Нгуен', 'Колесников', 'Д’Артаньян-Ёлкина', 'Бондаренко',
                            'Захарченко', 'Тарасова', 'Филиппова', 'Абрамов', 'Островский', 'Ермаков',
                            'Соловьёва', 'Лазарев', 'Кузьмина', 'Галиев', 'Панкратова', 'Иванов'}

COURSE_WEIGHTS = {1: 10, 2: 20, 3: 25, 4: 25, 5: 12, 6: 8}
GROUPS = {1: ['ПМ-11', 'ПМ-12'], 2: ['ПМ-21', 'ПМ-22'], 3: ['ПМ-31', 'ПМ-32'], 4: ['ПМ-41', 'ПМ-42'], 5: ['ПМ-51'],
          6: []}  # группы студентов; у курсантов — ПМ-<курс>1к, на 6-м курсе только курсанты
CADET_SHARE = 0.25
DOMAINS = ['example.org', 'example.com', 'example.ru']

# Текст статуса в анкете → статус системы, который ответственный выберет в предпросмотре (ТЗ 5.4).
STATUSES = [
    ('in_progress', 50, ['В работе', 'В работе: выполнен обзор литературы', 'В работе, этап 2 из 4',
                         'В работе: идёт реализация', 'В работе по плану']),
    ('planned', 15, ['Планируется: тема согласована', 'Планируется, начало — после сессии',
                     'Планируется: подбирается литература']),
    ('completed', 15, ['Завершена: доклад сделан, статья подана', 'Завершена, результаты внедрены на кафедре',
                       'Завершена']),
    ('suspended', 10, ['Приостановлена: академический отпуск до 01.02.2027', 'Приостановлена до окончания сессии']),
    ('terminated', 10, ['Прекращена: студент перешёл на другое направление',
                        'Прекращена по решению студента']),
]
STATUS_TITLES = {'planned': 'Планируется', 'in_progress': 'В работе', 'suspended': 'Приостановлена',
                 'completed': 'Завершена', 'terminated': 'Прекращена'}

GENERIC_ACHIEVEMENTS = [
    'Доклад на {n} Всероссийской студенческой конференции «Математика и информатика» ({city}, {month} {year}).',
    'Диплом {degree} степени конкурса студенческих научных работ университета ({year}).',
    'Тезисы в сборнике конференции «Молодёжь и наука», {year}, с. {p}–{p2}.',
    'Статья в журнале «Вестник студенческой науки», № {k}, {year}.',
    'Свидетельство о регистрации программы для ЭВМ № {year}6{reg} (вымышленный номер).',
    'Участник летней школы «{school}» ({city}, июль {year}).',
    'Финалист олимпиады по {subject} ({year}).',
    'Именная стипендия Учёного совета университета ({year}/{year1} учебный год).',
    'Выступление на научном семинаре кафедры ({month} {year}).',
    'Грамота за лучшую курсовую работу по направлению ({year}).',
]
CITIES = ['Москва', 'Казань', 'Новосибирск', 'Томск', 'Екатеринбург', 'Самара', 'Нижний Новгород']
MONTHS = ['апрель', 'май', 'октябрь', 'ноябрь', 'декабрь']
SCHOOLS = ['Современная математика', 'Анализ данных', 'Алгоритмы и программирование']
SUBJECTS = ['программированию', 'математике', 'информатике', 'анализу данных']

NOTES = ['Планируется продолжение темы в выпускной квалификационной работе.',
         'Участвует в проекте кафедры по гранту (вымышленный номер 26-11-00{k}).',
         'Рекомендован к участию в конкурсе «Студент года».',
         'Материалы работы хранятся в репозитории кафедры.',
         'Совмещает работу с подготовкой к олимпиаде.']
CADET_NOTE = 'Курсант: занятия — в часы самоподготовки, по согласованию с командиром подразделения.'

TRANSLIT = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                    ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's',
                     't', 'u', 'f', 'kh', 'ts', 'ch', 'sh', 'shch', '', 'y', '', 'e', 'yu', 'ya']))


def translit(text):
    return ''.join(TRANSLIT.get(c, c) for c in text.lower() if c.isalnum() or c == '-').replace(' ', '')


def feminine(surname):
    if surname.endswith('ский'):
        return surname[:-2] + 'ая'
    return surname + 'а'


def ru_date(day):
    return day.strftime('%d.%m.%Y')


def norm(value):
    return ' '.join(value.replace('ё', 'е').replace('Ё', 'Е').split()).casefold()


class Layout:
    """Видимая область полей формы: те же метрики шрифта и перенос строк, что при отрисовке (acroform)."""

    def __init__(self, form):
        acroform = PdfReader(form).trailer['/Root']['/AcroForm']
        font_ref = acroform['/DR']['/Font'].raw_get('/' + FONT_KEY)
        data = font_ref.get_object()['/DescendantFonts'][0].get_object()['/FontDescriptor']['/FontFile2'].get_data()
        self.font = EmbeddedFont(data)
        self.fields = {}
        for name, field in iter_terminal_fields(acroform['/Fields']):
            rect = [float(v) for v in field['/Rect']]
            self.fields[name] = (rect[2] - rect[0], rect[3] - rect[1], font_size(field),
                                 bool(int(field.get('/Ff', 0)) & FF_MULTILINE))

    def capacity(self, name):
        """Число строк, которые видны целиком (для многострочного поля)."""
        _, height, size, _ = self.fields[name]
        leading = size * 1.15
        top = height - 2.5 - self.font.ascent * size / 1000
        bottom = 1 - self.font.descent * size / 1000  # нижняя граница области отсечения + выносные элементы
        return int((top - bottom) / leading) + 1

    def fits(self, name, text):
        width, _, size, multiline = self.fields[name]
        if not multiline:
            return '\n' not in text and self.font.width(text, size) <= width - 5
        return len(self.font.wrap(text, width - 5, size)) <= self.capacity(name)


class Builder:
    def __init__(self, seed, layout):
        self.rng = random.Random(seed)
        self.layout = layout
        self.used_names = set()
        self.used_emails = set()

    def pick_fitting(self, field, options):
        options = list(options)
        self.rng.shuffle(options)
        for text in options:
            if self.layout.fits(field, text):
                return text
        raise ValueError(f'Ни один вариант не умещается в поле {field}.')

    def person(self):
        rng = self.rng
        while True:
            if rng.random() < 0.07:
                last, first = rng.choice(FOREIGN)
                middle, female = '', None
            else:
                female = rng.random() < 0.45
                base = rng.choice(SURNAMES)
                last = feminine(base) if female else base
                first = rng.choice(FEMALE_NAMES if female else MALE_NAMES)
                middle = rng.choice(PATRONYMICS)[1 if female else 0]
            key = norm(f'{last} {first} {middle}')
            if key not in self.used_names and last not in EXAMPLE_STUDENT_SURNAMES:
                self.used_names.add(key)
                return last, first, middle

    def email(self, last, first, middle):
        local = f'{translit(last)}.{translit(first)[0]}{translit(middle)[:1]}'
        domain = self.rng.choice(DOMAINS)
        candidate, n = f'{local}@{domain}', 2
        while candidate in self.used_emails:
            candidate, n = f'{local}{n}@{domain}', n + 1
        self.used_emails.add(candidate)
        return candidate

    def task(self, topic, area, filled, status):
        rng = self.rng
        steps = [f'Обзор литературы: не менее {rng.choice([10, 12, 15, 20])} источников, аннотированный список',
                 'Постановка задачи и выбор методов', area['impl'], area['experiment'],
                 'Доклад на студенческой научной конференции',
                 'Оформление результатов: отчёт по ГОСТ 7.32-2017 или статья']
        count = rng.randint(3, 5)
        chosen = [steps[0]] + [steps[i] for i in sorted(rng.sample(range(1, len(steps)), count - 1))]
        if status in ('completed', 'terminated'):  # работа шла в прошлом учебном году
            start = filled - timedelta(days=rng.randint(330, 380))
        else:
            start = filled + timedelta(days=rng.randint(20, 40))
        lines = [f'Тема: «{topic}».', '']
        if status == 'planned':
            lines.append(f'Начало работы — с {ru_date(start)}.')
            lines.append('')
        for number, step in enumerate(chosen, 1):
            deadline = start + timedelta(days=45 * number + rng.randint(0, 20))
            lines.append(f'{number}. {step} (до {ru_date(deadline)}).')
        return '\n'.join(lines)

    def schedule(self, cadet):
        rng = self.rng
        day = rng.choice(['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница'])
        time = rng.choice(['13:00–14:30', '15:40–17:10', '17:20–18:50'])
        lines = [f'{day}, {time} — консультация, ауд. {rng.randint(1, 5)}{rng.randint(0, 2)}{rng.randint(1, 9)}.']
        extra = ['Онлайн-встреча раз в две недели по средам, 19:00.',
                 'Отчёт о ходе работы — в последнюю пятницу месяца.',
                 'Вопросы по почте, ответ в течение двух рабочих дней.']
        lines += rng.sample(extra, rng.randint(0, 2))
        if cadet:
            lines.append('Время занятий согласуется с командиром подразделения.')
        return '\n'.join(lines)

    def achievements(self, area, course, status):
        rng = self.rng
        if status == 'planned':
            return []
        if course >= 4 and rng.random() < 0.15:
            count = 10  # всё портфолио заполнено
        else:
            count = min(10, max(0, round(rng.triangular(0, 10, min(course, 4)))))
        if count == 0:
            return []
        rows = sorted(rng.sample(range(1, 11), count)) if rng.random() < 0.25 else list(range(1, count + 1))
        templates = area['achievements'] + GENERIC_ACHIEVEMENTS  # 12 видов: в анкете не повторяются
        rng.shuffle(templates)
        texts, result = [], []
        for template in templates[:len(rows)]:
            year = rng.choice([2025, 2026]) if course > 1 else 2026
            for _ in range(20):
                text = template.format(n=rng.choice(['VII', 'VIII', 'IX', 'X']), city=rng.choice(CITIES),
                                       month=rng.choice(MONTHS), year=year, year1=year + 1,
                                       degree=rng.choice(['I', 'II', 'III']), p=(p := rng.randint(10, 200)),
                                       p2=p + rng.randint(2, 6), k=rng.randint(1, 12),
                                       reg=f'{rng.randint(10000, 99999)}', school=rng.choice(SCHOOLS),
                                       subject=rng.choice(SUBJECTS))
                if self.layout.fits('achievements.1.text', text):
                    break
            texts.append(text)
        for row, text in zip(rows, texts):
            result.append({'id': f'achievement-{row}', 'text': text})
        return result

    def form(self, teacher_index, student_index, teacher):
        rng = self.rng
        full_name, position, area_key = teacher
        area = AREAS[area_key]
        last, first, middle = self.person()
        course = rng.choices(list(COURSE_WEIGHTS), weights=COURSE_WEIGHTS.values())[0]
        cadet = course == 6 or rng.random() < CADET_SHARE
        group = f'ПМ-{course}1к' if cadet else rng.choice(GROUPS[course])
        status_code, _, texts = rng.choices(STATUSES, weights=[s[1] for s in STATUSES])[0]
        status_text = rng.choice(texts)
        filled = FIRST_DAY + timedelta(days=rng.randint(0, (TODAY - FIRST_DAY).days))
        topic = self.topics[teacher_index].pop()
        results = rng.sample(area['results'], rng.randint(2, 3))
        notes = []
        if not middle:
            notes.append(FOREIGN_NOTE)
        if cadet:
            notes.append(CADET_NOTE)
        if rng.random() < 0.35:
            notes.append(rng.choice(NOTES).format(k=rng.randint(100, 999)))
        if status_code == 'terminated':
            notes.append('Работа прекращена; материалы переданы на кафедру.')
        student = {
            'id': f'student-set-{teacher_index:02d}-{student_index}',
            'last_name': last, 'first_name': first, 'middle_name': middle, 'course': str(course),
            'group_code': group,
            'phone': f'+7 (900) 0{teacher_index:02d}-{student_index:02d}-{rng.randint(10, 99)}',
            'email': self.email(last, first, middle),
            'task': self.task(topic, area, filled, status_code),
            'schedule': self.schedule(cadet),
            'expected_results': '\n'.join(f'— {line};' for line in results[:-1]) + f'\n— {results[-1]}.',
            'status': status_text,
            'achievements': self.achievements(area, course, status_code),
            'notes': '\n'.join(notes),
        }
        data = {'schema_version': '2.0', 'form_id': 'prepod_vnok_info', 'date_filled': ru_date(filled),
                'teacher': {'full_name': full_name, 'position': position, 'department': DEPARTMENT},
                'students': [student]}
        slug = translit(last).replace('-', '')
        return {'file': f'{teacher_index:02d}-{student_index}-{slug}.pdf', 'questionnaire_id': student['id'],
                'teacher': full_name, 'suggested_status': status_code, 'data': data}

    def build(self):
        for name, _, area in TEACHERS:
            assert name.split()[0] not in EXAMPLE_TEACHER_SURNAMES
        self.topics = {}
        forms = []
        for index, teacher in enumerate(TEACHERS, 1):
            count = self.rng.randint(*STUDENTS_PER_TEACHER)
            topics = AREAS[teacher[2]]['topics'][:]
            self.rng.shuffle(topics)
            self.topics[index] = topics
            forms += [self.form(index, number, teacher) for number in range(1, count + 1)]
        return forms


def field_values(data):
    values = {'meta.date_filled': data['date_filled']}
    values.update({'teacher.' + key: value for key, value in data['teacher'].items()})
    student = data['students'][0]
    values.update({'student.' + key: student[key] for key in STUDENT_KEYS})
    for item in student['achievements']:
        values[f"achievements.{item['id'].split('-')[-1]}.text"] = item['text']
    return values


def validate(form, layout):
    """Анкета без ошибок и предупреждений проверки, все значения умещаются в поля."""
    data = form['data']
    errors, warnings = check(data)
    if errors or warnings:
        raise ValueError(f"{form['file']}: {errors + warnings}")
    for name, value in field_values(data).items():
        if not layout.fits(name, value):
            raise ValueError(f"{form['file']}: значение не умещается в поле {name}: {value!r}")


def render(form, temp):
    student_id = form['data']['students'][0]['id']
    source, _ = prepare_copy(FORM, Path(temp) / form['file'], student_id=student_id)
    writer = PdfWriter(clone_from=PdfReader(source))
    set_values(writer, field_values(form['data']))
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def totals(forms):
    students = [f['data']['students'][0] for f in forms]
    statuses = {}
    for form in forms:
        statuses[form['suggested_status']] = statuses.get(form['suggested_status'], 0) + 1
    return {'department': 1, 'teachers': len({f['teacher'] for f in forms}), 'students': len(students),
            'works': len(forms), 'groups': len({s['group_code'] for s in students}),
            'achievements': sum(len(s['achievements']) for s in students),
            'cadets': sum(s['group_code'].endswith('к') for s in students),
            'without_middle_name': sum(not s['middle_name'] for s in students),
            'statuses': dict(sorted(statuses.items()))}


def readme(forms, summary):
    by_teacher = {}
    for form in forms:
        by_teacher.setdefault(form['teacher'], []).append(form)
    rows = []
    for index, (name, position, area) in enumerate(TEACHERS, 1):
        rows.append(f'| {index:02d} | {name} | {position} | {AREAS[area]["title"]} | {len(by_teacher[name])} |')
    status_rows = '\n'.join(f'| {title} | {summary["statuses"].get(code, 0)} |' for code, title in STATUS_TITLES.items())
    return f"""# Набор анкет без ошибок

{summary['works']} заполненных анкет `prepod_vnok_info` версии 2.0 (форма `prepod_vnok_info-v2.0-draft04.pdf`), которые проходят проверку `extract_static.py --check` без ошибок и предупреждений и загружаются в «Учёт НИР» без возврата. Набор нужен для демонстрации системы, ручной проверки интерфейса и отчётов и как тестовые данные. Требования — [prompts/0004_improved.txt](../../prompts/0004_improved.txt), отчёт — [doc/report-0004.md](../../doc/report-0004.md).

**Все данные вымышлены.** Почта только в доменах `example.org`, `example.com`, `example.ru`; телефоны вида `+7 (900) 0ПП-СС-NN`, где ПП — номер преподавателя, СС — номер студента. ФИО не совпадают с [20 примерами](../../tests/fixtures/examples): оба набора можно загрузить в одну базу.

Этот файл и `expected.json` создаёт генератор, править их вручную не нужно.

## Получение файлов

PDF ({str(summary['pdf_mb']).replace('.', ',')} МБ) и ZIP ({str(summary['zip_mb']).replace('.', ',')} МБ) в репозитории не хранятся: генератор воспроизводит их байт в байт.

```bash
.venv/bin/python scripts/generate_valid_forms.py            # из корня проекта; --force — пересоздать
```

| Файл | Что это |
| --- | --- |
| `ПП-С-фамилия.pdf` | Анкета: ПП — номер преподавателя (таблица ниже), С — номер студента у него |
| `{ZIP_NAME}` | Все анкеты одним архивом для загрузки |
| `expected.json` | Ожидаемые данные каждой анкеты (ровно то, что извлекает `extract_static.py`), SHA-256 файлов, предлагаемый статус, итоги |

Зерно генератора — `{SEED}`. Другое зерно (`SEED` в генераторе) даст другой набор с тем же устройством.

## Состав

Одна кафедра — «{DEPARTMENT}», та же, что в примерах. 20 преподавателей, у каждого случайно от 3 до 5 студентов (курсантов); один файл — один студент. ID анкеты — `student-set-ПП-С`.

| ПП | Преподаватель | Должность | Направление | Студентов |
| --- | --- | --- | --- | --- |
{chr(10).join(rows)}

Итого: преподавателей — {summary['teachers']}, студентов и работ — {summary['works']}, групп — {summary['groups']}, строк портфолио (достижений) — {summary['achievements']}. Курсантов (группы с «к») — {summary['cadets']}, иностранных студентов без отчества — {summary['without_middle_name']}.

Тексты статуса в анкетах и статус системы, который им соответствует (`suggested_status` в `expected.json`):

| Статус | Анкет |
| --- | --- |
{status_rows}

Что разнообразно, оставаясь допустимым: курсы 1–6 цифрой, шифры групп по курсу, студенты и курсанты, ФИО с отчеством и без, `ё` и кавычки «», темы и этапы работ по направлению преподавателя, расписание и примечания, от 0 до 10 строк портфолио, иногда с пропусками строк. Даты заполнения — с {ru_date(FIRST_DAY)} по {ru_date(TODAY)}. Все тексты умещаются в видимую область полей: генератор проверяет это по метрикам встроенного шрифта.

## Загрузка в систему

1. «Импорт → Загрузить анкеты», выбрать `{ZIP_NAME}`. В пакете больше {20} файлов, поэтому он обрабатывается в фоне (`worker`); страница пакета обновится сама.
2. Все анкеты получат состояние «Ожидает решения»; к возврату и с предупреждениями проверки — ни одной.
3. В пустой базе преподавателей ещё нет, поэтому каждая анкета требует решения «Преподаватель не найден: создайте запись». Это поведение системы, а не ошибка в анкетах. Достаточно открыть **по одной анкете каждого преподавателя** (файлы `ПП-1-…`) и сохранить с предложенными значениями: создаются кафедра (при первой анкете), преподаватель, группа, студент и работа. Если преподаватели уже заведены в справочнике с теми же ФИО и кафедрой, этот шаг не нужен.
4. «Сохранить все готовые» на странице пакета — остальные анкеты сохраняются без предпросмотра.
5. Итог: 1 кафедра, {summary['teachers']} преподавателей, {summary['works']} студентов и работ, {summary['groups']} групп, {summary['achievements']} достижений.

При сохранении кнопкой «Сохранить все готовые» новая работа получает статус «В работе», а текст статуса из анкеты сохраняется как комментарий (ТЗ 7.2). Чтобы статусы соответствовали `suggested_status`, выбирайте их в предпросмотре каждой анкеты.

Проверка набора — `tests/test_valid_forms.py`: каждая анкета, сборка байт в байт, загрузка в пустую базу и поверх 20 примеров.
"""


def generate(out=OUT, force=False):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    existing = sorted(out.glob('*.pdf'))
    if existing and not force:
        raise FileExistsError(f'В {out} уже есть PDF ({len(existing)}); для пересоздания укажите --force.')
    layout = Layout(FORM)
    forms = Builder(SEED, layout).build()
    for path in existing:
        path.unlink()
    zip_info = []
    with tempfile.TemporaryDirectory() as temp:
        for form in forms:
            validate(form, layout)
            content = render(form, temp)
            (out / form['file']).write_bytes(content)
            form['sha256'] = hashlib.sha256(content).hexdigest()
            zip_info.append((form['file'], content))
    with zipfile.ZipFile(out / ZIP_NAME, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in zip_info:
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 12, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    summary = totals(forms)
    summary['pdf_mb'] = round(sum(len(content) for _, content in zip_info) / 1e6, 1)
    summary['zip_mb'] = round((out / ZIP_NAME).stat().st_size / 1e6, 1)
    expected = {'seed': SEED, 'form': FORM.name, 'department': DEPARTMENT, 'totals': summary,
                'forms': [{key: form[key] for key in ('file', 'sha256', 'questionnaire_id', 'teacher',
                                                      'suggested_status', 'data')} for form in forms]}
    (out / 'expected.json').write_text(json.dumps(expected, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    (out / 'README.md').write_text(readme(forms, summary), encoding='utf-8')
    # Повторная проверка готовых файлов тем же извлечением, что в системе.
    for form in forms:
        if extract_data(out / form['file']) != form['data']:
            raise ValueError(f"{form['file']}: извлечённые данные не совпадают с ожидаемыми.")
    return forms, summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--force', action='store_true', help='Пересоздать PDF, если они уже есть.')
    parser.add_argument('--out', type=Path, default=OUT, help=f'Каталог набора (по умолчанию {OUT.relative_to(ROOT)}).')
    args = parser.parse_args()
    try:
        forms, summary = generate(args.out, args.force)
    except Exception as error:
        parser.exit(1, f'Ошибка: {error}\n')
    print(f"Готово: {args.out} — анкет {summary['works']}, преподавателей {summary['teachers']}, "
          f"групп {summary['groups']}, достижений {summary['achievements']}.")
