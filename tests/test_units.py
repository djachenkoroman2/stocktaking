from datetime import date

from registry import status
from registry.status import WorkStatus
from registry.text import academic_year, norm, split_full_name, suggest_course


def test_norm():
    assert norm('  Белозёрова  Марина ') == norm('белозерова марина')


def test_split_full_name():
    assert split_full_name('Белозёрова Марина Викторовна') == ('Белозёрова', 'Марина', 'Викторовна')
    assert split_full_name('Иванов И. И.') == ('Иванов', 'И.', 'И.')
    assert split_full_name('Иванов И.И.') == ('Иванов', 'И.', 'И.')
    assert split_full_name('') == ('', '', '')


def test_suggest_course():
    assert suggest_course('II') == 2
    assert suggest_course('1 курс') == 1
    assert suggest_course('VI') == 6
    assert suggest_course('0') is None
    assert suggest_course('третий') is None


def test_academic_year():
    assert academic_year(date(2026, 9, 30)) == '2026/2027'
    assert academic_year(date(2027, 3, 15)) == '2026/2027'
    assert academic_year(date(2026, 8, 31)) == '2025/2026'


def test_transitions():
    assert status.check_transition(WorkStatus.PLANNED, WorkStatus.IN_PROGRESS) is None
    assert status.check_transition(WorkStatus.PLANNED, WorkStatus.COMPLETED)
    assert status.check_transition(WorkStatus.TERMINATED, WorkStatus.IN_PROGRESS) == 'Возобновление работы требует комментария.'
    assert status.check_transition(WorkStatus.TERMINATED, WorkStatus.IN_PROGRESS, 'причина') is None
    assert [s.value for s in status.allowed_targets(WorkStatus.COMPLETED)] == ['in_progress', 'completed']
