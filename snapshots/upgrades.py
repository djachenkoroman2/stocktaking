"""Преобразование выгрузок старых версий формата в текущую (doc/json-format.md, «Новая версия формата»).

UPGRADES[N] переводит данные из версии N в версию N + 1. Восстановление применяет цепочку от версии
выгрузки до FORMAT_VERSION. Преобразование работает потоком, по одной таблице:

    def v1_to_v2(table, records):
        # table — имя таблицы в версии 1, records — итератор записей (dict).
        # Вернуть (имя таблицы в версии 2 или None, если таблицы больше нет; итератор записей).
        if table == 'registry.researchwork':
            return table, ({**r, 'priority': 'normal'} for r in records)
        return table, records

    UPGRADES = {1: v1_to_v2}

Новые таблицы, которых не было в старой версии, после восстановления остаются пустыми; если их нужно
заполнить из старых данных — сделайте это миграцией данных Django после восстановления.
"""
UPGRADES = {}


def upgrade(version, current, table, records):
    """Таблица из выгрузки версии version → (имя таблицы, записи) в версии current."""
    for step in range(version, current):
        if table is None:
            break
        if step not in UPGRADES:
            raise LookupError(f'Нет преобразования формата {step} → {step + 1}.')
        table, records = UPGRADES[step](table, records)
    return table, records
