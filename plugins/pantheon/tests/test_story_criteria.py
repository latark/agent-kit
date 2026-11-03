#!/usr/bin/env python3
"""Новая story без проверяемого пункта «Готово, когда» — отказ (metis-0766): заглушка пачку не закроет.

Запуск: python3 -I plugins/pantheon/tests/test_story_criteria.py  (код выхода 0 — все прошли)
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="storycrit-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

RUN_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "run.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


tmp = os.path.realpath(tempfile.mkdtemp(prefix="storycrit-test-"))
home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
os.makedirs(os.path.join(home, "directions", "metis-pantheon", "tasks"))
os.makedirs(view)
open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(
    '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n')
env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state, "PANTHEON_VIEW": view,
       "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "PANTHEON_FAKE_IDLE": "0"}


def new(*a):
    return subprocess.run([PY311, "-I", RUN_PY, "task", "new", "--direction", "metis-pantheon", *a], env=env,
                          capture_output=True, text=True, timeout=60)


def cards():
    return sorted(os.listdir(os.path.join(home, "directions", "metis-pantheon", "tasks")))


HINT = "(впишите проверяемые пункты: что должно работать и как это проверить)"
r = new("--type", "story", "--title", "Пачка без пунктов", "--text", "цель абзацем")
check("story без пунктов → отказ, код не 0, подсказка про --done-when, файла нет",
      r.returncode != 0 and "--done-when" in r.stderr and not cards(), r.stdout + r.stderr)
r = new("--type", "story", "--title", "Пачка с заглушкой в теле", "--text", f"## Готово, когда\n\n- [ ] {HINT}")
check("story с заглушкой в теле → отказ", r.returncode != 0 and not cards(), r.stdout + r.stderr)
r = new("--type", "story", "--title", "Пачка с пунктом", "--text", "цель", "--done-when", "тест зелёный")
check("story с --done-when → создана", r.returncode == 0 and len(cards()) == 1, r.stdout + r.stderr)
r = new("--type", "story", "--title", "Пачка с разделом в теле", "--text", "цель\n\n## Готово, когда\n\n- [ ] тест зелёный")
check("story с разделом «Готово, когда» в --body → создана", r.returncode == 0 and len(cards()) == 2, r.stdout + r.stderr)
r = new("--title", "Обычная задача без пунктов", "--text", "цель")
check("задача без пунктов → создаётся как раньше", r.returncode == 0 and len(cards()) == 3, r.stdout + r.stderr)

print(f"\n{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
