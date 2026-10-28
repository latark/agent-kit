#!/usr/bin/env python3
"""Запуск скрипта хука как __main__, но из .pyc — для тестов, которые зовут хук сотни раз (metis-0544).

    python3 -I _cached_main.py <путь к скрипту> [аргументы]   (stdin, stdout, код выхода — как у скрипта)

Скрипт Python компилируется заново на каждый запуск, а модуль — один раз в __pycache__ рядом с ним: у guard.py
(4000 строк) это 0,025 с из 0,06 с вызова. Скрипт не меняется и выполняется тем же входом `if __name__ ==
"__main__"`: имя модуля __main__, __file__ и sys.argv[0] — путь скрипта, sys.path тот же, что у `python3 -I
скрипт` (-I не добавляет папку скрипта). Отличие одно — __spec__ не None. Кэш не пишется (папка только для
чтения) — Python молча компилирует в памяти, как при обычном запуске."""
import importlib.machinery
import importlib.util
import sys

path = sys.argv[1]
sys.argv = sys.argv[1:]
loader = importlib.machinery.SourceFileLoader("__main__", path)
spec = importlib.util.spec_from_file_location("__main__", path, loader=loader)
mod = importlib.util.module_from_spec(spec)
sys.modules["__main__"] = mod
loader.exec_module(mod)
