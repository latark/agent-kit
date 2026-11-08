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
    без строки «доска-время» (metis-0709). Выход 0 по бюджету (следующий тик повторит), 143 по SIGTERM; os.write мимо
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
    signal.signal(signal.SIGALRM, stop(0))
    signal.setitimer(signal.ITIMER_REAL, max(budget, 1.0))


if __name__ == "__main__" and sys.argv[1:2] == ["board"]:
    _early_board_guard()
import pantheon  # noqa: E402

pantheon.PROC_T0 = T0
if __name__ == "__main__":
    sys.exit(pantheon.main(sys.argv[1:]))
