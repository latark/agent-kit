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

if __name__ == "__main__":
    sys.exit(pantheon.main(sys.argv[1:]))
