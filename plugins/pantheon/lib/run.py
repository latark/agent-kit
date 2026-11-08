"""Загрузчик: запускает pantheon модулем, а не скриптом.

Скрипт Python компилируется заново при каждом запуске, модуль — один раз, дальше .pyc из lib/__pycache__ (тик
запускает pantheon десятки тысяч раз в сутки, pantheon.py — 4400 строк). Если lib/__pycache__ не пишется (кэш
плагина только для чтения в песочнице окна) — Python молча компилирует в памяти, как раньше. Запуск — с -I, поэтому
каталог lib добавляется явно."""
import os
import sys

if sys.version_info < (3, 11):
    sys.exit("pantheon: нужен Python 3.11+ (здесь %d.%d)" % sys.version_info[:2])
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import pantheon  # noqa: E402


def main(argv):
    """metis-1009: в окне роли (PANTHEON_ROLE) запись, которую закрыла песочница окна, — одна строка и код 1, а не
    трассировка: роль по ней понимает, что команда не сделана и почему. В терминале владельца — трассировка, как была."""
    try:
        return pantheon.main(argv)
    except PermissionError as e:
        role = os.environ.get("PANTHEON_ROLE")
        if not role:
            raise
        where = e.filename or "файл"
        home = os.environ.get("HOME") or ""
        if home and isinstance(where, str) and where.startswith(home + os.sep):
            where = "~" + where[len(home):]
        cmd = " ".join(argv[:1]) or "pantheon"
        print(f"pantheon {cmd}: не сделано — окну {role} песочница не даёт записать {where} ({e.strerror or e}); эту "
              "запись делает плановый проход или запуск вне окна", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
