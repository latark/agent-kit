#!/usr/bin/env python3
"""Поле задачи executor (auto|claude|codex, решение 175): схема принимает три значения, чужое — ошибка;
`pantheon task new --executor` и `task set executor=` пишут его в шапку.

Запуск: python3 -I plugins/pantheon/tests/test_executor_field.py  (код выхода 0 — все прошли)
"""
import os
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CLI = os.path.join(LIB, "pantheon.py")
T0 = 1_792_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="executor-field-"))
    try:
        home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
        os.makedirs(os.path.join(home, "directions", "demo", "tasks"))
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
               "PANTHEON_VIEW": os.path.join(tmp, "view"), "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
               "PANTHEON_NOW": str(T0), "TMPDIR": tmp}

        def run(*a):
            return subprocess.run([PY311, "-I", CLI, *a], env=env, capture_output=True, text=True, timeout=60)

        r = run("task", "new", "--direction", "demo", "--title", "Механика", "--executor", "codex")
        check("task new --executor codex — принят", r.returncode == 0, r.stderr)
        tid, rel = (r.stdout.split() + ["", ""])[:2]
        text = open(os.path.join(home, rel), encoding="utf-8").read() if rel else ""
        check("шапка: executor: codex", "\nexecutor: codex\n" in text, text[:300])
        r = run("task", "new", "--direction", "demo", "--title", "Плохое", "--executor", "gpt")
        check("task new --executor gpt — отказ с перечнем", r.returncode != 0 and "auto, claude, codex" in r.stderr,
              r.stdout + r.stderr)
        r = run("task", "set", tid, "executor=claude")
        text = open(os.path.join(home, rel), encoding="utf-8").read()
        check("task set executor=claude", r.returncode == 0 and "\nexecutor: claude\n" in text, r.stderr)
        r = run("task", "set", tid, "executor=human")
        check("task set executor=human — отказ", r.returncode != 0, r.stdout + r.stderr)
        r = run("task", "new", "--direction", "demo", "--title", "Без поля")
        rel2 = r.stdout.split()[1]
        check("без --executor поля нет (по умолчанию auto)",
              "executor:" not in open(os.path.join(home, rel2), encoding="utf-8").read())
    finally:
        shutil.rmtree(tmp, True)
    print(f"{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
