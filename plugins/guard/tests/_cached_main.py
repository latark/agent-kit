#!/usr/bin/env python3
"""Запуск скрипта хука как __main__, но из .pyc — для тестов, которые зовут хук сотни раз (metis-0544).

    python3 -I _cached_main.py <путь к скрипту> [аргументы]   (stdin, stdout, код выхода — как у скрипта)

Скрипт Python компилируется заново на каждый запуск, а модуль — один раз в __pycache__ рядом с ним. С metis-0148
guard.py — короткий вход, правила он сам грузит модулем guard_rules.py из .pyc; загрузчик экономит только разбор
самого входа. Скрипт не меняется и выполняется тем же входом `if __name__ ==
"__main__"`: имя модуля __main__, __file__ и sys.argv[0] — путь скрипта, sys.path тот же, что у `python3 -I
скрипт` (-I не добавляет папку скрипта). Отличие одно — __spec__ не None. Кэш не пишется (папка только для
чтения) — Python молча компилирует в памяти, как при обычном запуске.

Сроки под нагрузкой (metis-0719): на занятом Mac (проход outside, -j 3, load 8-20) хук порой не укладывается в свой
срок DEADLINE (8 с) или git в нём — в timeout=3, и случай шлюза краснеет 1-3 раза из 1662 не по своей вине. Тест
поднимает эти сроки только своим вызовам — окружением загрузчика; код guard не меняется, без переменных всё как в бою:
  GUARD_TEST_DEADLINE=<с>     — срок signal.setitimer(ITIMER_REAL) не меньше <с> (DEADLINE guard.py, guard_rules, taint);
  GUARD_TEST_SUB_TIMEOUT=<с>  — timeout у subprocess.run не меньше <с> (git, gh, ps, lsof внутри хука).
Пусто, ноль или не число — не трогать."""
import importlib.machinery
import importlib.util
import os
import signal
import subprocess
import sys


def _floor(name):
    try:
        v = float(os.environ.get(name, ""))
    except ValueError:
        return None
    return v if v > 0 else None


_deadline, _sub = _floor("GUARD_TEST_DEADLINE"), _floor("GUARD_TEST_SUB_TIMEOUT")
if _deadline:
    _setitimer = signal.setitimer

    def _slow_setitimer(which, seconds, interval=0.0):
        if which == signal.ITIMER_REAL and seconds:
            seconds = max(seconds, _deadline)
        return _setitimer(which, seconds, interval)

    signal.setitimer = _slow_setitimer
if _sub:
    _run = subprocess.run

    def _slow_run(*args, **kw):
        if kw.get("timeout") is not None:
            kw["timeout"] = max(kw["timeout"], _sub)
        return _run(*args, **kw)

    subprocess.run = _slow_run

path = sys.argv[1]
sys.argv = sys.argv[1:]
loader = importlib.machinery.SourceFileLoader("__main__", path)
spec = importlib.util.spec_from_file_location("__main__", path, loader=loader)
mod = importlib.util.module_from_spec(spec)
sys.modules["__main__"] = mod
loader.exec_module(mod)
