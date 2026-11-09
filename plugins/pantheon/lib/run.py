"""Загрузчик: запускает pantheon модулем, а не скриптом.

Скрипт Python компилируется заново при каждом запуске, модуль — один раз, дальше .pyc из lib/__pycache__ (тик
запускает pantheon десятки тысяч раз в сутки, pantheon.py — 4400 строк). Если lib/__pycache__ не пишется (кэш
плагина только для чтения в песочнице окна) — Python молча компилирует в памяти, как раньше. Запуск — с -I, поэтому
каталог lib добавляется явно."""
import os
import signal
import sys
import time

T0 = time.monotonic()  # начало процесса: импорт pantheon.py под нагрузкой Mac бывает десятки секунд (metis-0709)

if sys.version_info < (3, 11):
    sys.exit("pantheon: нужен Python 3.11+ (здесь %d.%d)" % sys.version_info[:2])
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))


def _early_board_guard():
    """Проход board: до конца импорта pantheon.py SIGTERM (таймаут задания) и бюджет не должны убить процесс молча —
    без строки «доска-время» (metis-0709). Выход 77 (BUDGET_CUT) по бюджету (следующий тик повторит, отпечатка входов нет), 143 по SIGTERM; os.write мимо
    буфера stdout. Когда pantheon.board() запущена, она ставит свои обработчики."""
    try:
        budget = float(os.environ.get("PANTHEON_BOARD_BUDGET") or 45)
    except ValueError:
        budget = 45.0

    def stop(code):
        def handler(*_):
            msg = f"доска-время: прервано в «импорт pantheon.py» · итого {time.monotonic() - T0:.1f} с\n"
            with __import__("contextlib").suppress(OSError):
                os.write(1, msg.encode())
            os._exit(code)
        return handler

    signal.signal(signal.SIGTERM, stop(143))
    signal.signal(signal.SIGALRM, stop(77))  # 77 = BUDGET_CUT в pantheon.py
    signal.setitimer(signal.ITIMER_REAL, max(budget, 1.0) + 5.0)  # = BOARD_HARD_GRACE в pantheon.py


if __name__ == "__main__" and sys.argv[1:] == ["board"]:  # только сам проход; board archive и прочие подкоманды — как на base (ждут замок до HQ_LOCK_WAIT, откат metis-0810)
    _early_board_guard()
import pantheon  # noqa: E402

pantheon.PROC_T0 = T0


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
