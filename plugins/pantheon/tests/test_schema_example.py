#!/usr/bin/env python3
"""Пример `pantheon task new` из schema.md рабочий (metis-0408): блок вытаскивается из файла и выполняется как есть.

Запуск: python3 -I plugins/pantheon/tests/test_schema_example.py  (код выхода 0 — все прошли)
Временные HOME, PANTHEON_HOME и PANTHEON_STATE; настоящая ~/ai/pantheon не трогается.
"""
import atexit
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="schema-example-"))
atexit.register(shutil.rmtree, ROOT, True)
PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_PY = os.path.join(PLUGIN, "lib", "run.py")
SCHEMA = os.path.join(PLUGIN, "template", "pantheon", "schema.md")
NOW = str(int(time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, -1))))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:500]}]"))


home, state, view = (os.path.join(ROOT, d) for d in ("pantheon", "state", "view"))
for d in ("directions/alpha/tasks", "inbox/tasks"):
    os.makedirs(os.path.join(home, d))
os.makedirs(view)
with open(os.path.join(home, "schedule.toml"), "w", encoding="utf-8") as fh:
    fh.write('primary_host = "mac-a"\n')
with open(os.path.join(home, "directions.toml"), "w", encoding="utf-8") as fh:
    fh.write('[[direction]]\nname = "alpha"\nproject = "Альфа"\n')
ENV = {"PATH": os.environ["PATH"], "HOME": ROOT, "PANTHEON_HOME": home, "PANTHEON_STATE": state, "PANTHEON_VIEW": view,
       "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "PANTHEON_FAKE_IDLE": "0",
       "PANTHEON_NOW": NOW, "TMPDIR": ROOT}


def pan(*a):
    return subprocess.run([PY311, "-I", RUN_PY, *a], env=ENV, capture_output=True, text=True, timeout=120)


def example():
    """Первый блок кода schema.md, где есть `pantheon task new` → список аргументов после слов `pantheon task new`."""
    with open(SCHEMA, encoding="utf-8") as fh:
        blocks = re.findall(r"```\n(.*?)```", fh.read(), re.S)
    for b in blocks:
        if b.lstrip().startswith("pantheon task new"):
            return shlex.split(b.replace("\\\n", " "))[3:]  # перенос строки оболочки — пробел
    return None


ex = example()
check("в schema.md есть блок с `pantheon task new`", ex is not None)
ex = ex or []
check("в примере есть --text, --mode и --mode-why", all(f in ex for f in ("--text", "--mode", "--mode-why")), ex)

# пачка, в которую заводим задачу из примера
r = pan("task", "new", "--direction", "alpha", "--type", "story", "--title", "Пачка: выгрузка отчётов без падений",
        "--text", "Пачка для проверки примера.", "--estimate", "5")
check("пачка заведена", r.returncode == 0 and "alpha-0001" in r.stdout, r.stdout + r.stderr)

args = [{"<направление>": "alpha", "<id пачки>": "alpha-0001"}.get(x, x) for x in ex]
r = pan("task", "new", *args)
check("пример из schema.md проходит task new: код 0, задача создана", r.returncode == 0 and "alpha-0002" in r.stdout,
      r.stdout + r.stderr)
body = ""
p = os.path.join(home, "directions", "alpha", "tasks", "alpha-0002.md")
if os.path.exists(p):
    with open(p, encoding="utf-8") as fh:
        body = fh.read()
check("в задаче текст, режим, причина режима и пачка из примера",
      "Выгрузка падает на пустом периоде" in body and "mode: single" in body and "mode_why:" in body
      and "parent: alpha-0001" in body, body)

# без --text тот же пример отказывает — иначе блок в schema.md ничего не доказывает
cut = []
skip = False
for x in args:
    if skip:
        skip = False
    elif x == "--text":
        skip = True
    else:
        cut.append(x)
r = pan("task", "new", *cut)
check("тот же пример без --text — отказ, код 2", r.returncode == 2, r.stdout + r.stderr)

print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
