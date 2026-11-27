"""Карантин тестов run-tests.py со сроком и лимитом (metis-1359; родитель — пачка metis-1210).

QUARANTINE в run-tests.py — {метка файла: (задача на починку «metis-NNNN», срок «ГГГГ-ММ-ДД»)}. Срок ставят при
записи: сегодня + TTL_DAYS (7) дней. Упавший файл с живой записью — строка «карантин», код прогона не портится
(metis-1050). Срок прошёл (на день срока запись ещё жива) — запись не действует: упавший файл — обычный FAIL, а в
строке и в итоге — «карантин просрочен»; красный CI — тревога «чини или продли осознанно». Записей больше MAX (5) —
раннер не запускает ничего: код 2 и причина последней строкой. Запись неверного вида — тот же отказ.
Только stdlib; в run-tests.py модуль подключается через sys.path (раннер идёт с -I).
"""
import datetime
import re

TTL_DAYS = 7
MAX = 5
TASK = re.compile(r"metis-\d{4}")


def _until(entry):
    """Срок записи как дата или None — запись неверного вида."""
    try:
        task, until = entry
        if not (isinstance(task, str) and TASK.fullmatch(task)):
            return None
        return datetime.date.fromisoformat(until)
    except (TypeError, ValueError):
        return None


def refuse(entries):
    """Причина отказа раннера (одной строкой) или None: записей больше MAX, либо запись не (задача, срок)."""
    if len(entries) > MAX:
        return (f"run-tests: карантин: записей {len(entries)}, больше {MAX} — почини тесты или убери записи из "
                "QUARANTINE, лимит не поднимать")
    for label, entry in entries.items():
        if _until(entry) is None:
            return f"run-tests: карантин: запись {label} — нужно (\"metis-NNNN\", \"ГГГГ-ММ-ДД\"), а не {entry!r}"
    return None


def expired(entries, label, today=None):
    """Запись label есть, и её срок прошёл."""
    if label not in entries:
        return False
    return _until(entries[label]) < (today or datetime.date.today())


def active(entries, label, today=None):
    """Запись label есть и жива: упавший файл не портит код прогона."""
    return label in entries and not expired(entries, label, today)


def note(entries, label, today=None):
    """Пометка упавшего файла для строки и итога: «карантин, задача X», «карантин просрочен: задача X, срок D» или ""."""
    if label not in entries:
        return ""
    task, until = entries[label]
    if expired(entries, label, today):
        return f"карантин просрочен: задача {task}, срок {until}"
    return f"карантин, задача {task}"
