#!/usr/bin/env python3
"""Запуск правил guard для тестов так, чтобы результат не зависел от того, где их запускают (metis-0090).

    python3 -I _guard_shim.py <путь к guard.py> [--strict|--managed]   (stdin — событие хука)

Грузится модуль правил guard_rules.py рядом с guard.py (metis-0148: guard.py — короткий вход, его решения «молчать»
проверяет test_entry.py), запуск — его же вход run_hook. Правила не меняются; подменяется только обвязка — подмены
patch() из _guard_inproc.py (metis-1148: тот же текст подмен у вызова внутри процесса теста, а не копия):
1. Временный HOME тестов лежит в $TMPDIR, а в окне агента это /tmp/claude-<uid>: guard считает /tmp и /private/tmp
   временными корнями (TEMP_ROOTS) и разрешает запись во всё, что внутри, — в том числе в ~/ai/pantheon тестового HOME.
   Для путей внутри HOME теста корни, в которых лежит сам HOME, из TEMP_ROOTS не берутся. Пути вне HOME
   (/tmp/out.txt и т. п.) остаются временными, как в боевом guard. Если HOME не внутри временной папки — ничего не меняется.
2. Разрешение имён (check_cdp_role: «WebFetch в интернет») ходит в сеть; в песочнице DNS нет, и guard закрывает
   «не разрешилось». Имена разрешаются в публичный адрес (93.184.216.34, example.com: TEST-NET у ipaddress считается частным), IP-адреса — сами в себя.
3. Искусственный сбой (metis-0094): GUARD_SHIM_BOOM=<имя>[,<имя>] — функция модуля guard (или merge_gate.record)
   бросает исключение; GUARD_SHIM_HANG=<имя> — висит 15 с, а срок guard (DEADLINE) — GUARD_SHIM_DEADLINE секунд.
4. Без GUARD_SHIM_HANG сроки guard (DEADLINE 8 с) и его git/gh (3 и 6 с) не короче 45 и 40 с (metis-0763): тест
   проверяет правила, а не скорость машины; боевой код не меняется.
5. GUARD_SHIM_MANAGED — файл управляемых настроек вместо настоящего.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _guard_inproc import load_rules, patch  # noqa: E402

path, sys.argv = sys.argv[1], [sys.argv[1]] + sys.argv[2:]
g = load_rules(path)
patch(g, path)
g.run_hook()  # тот же вход, что в блоке __main__ guard.py: сбой — код 2 с причиной в stderr
