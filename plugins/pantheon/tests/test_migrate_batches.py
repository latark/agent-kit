#!/usr/bin/env python3
"""Пачки (story) и пульт проектов (metis-0069): attach/detach, сумма оценок в show, release вместо wave, пересечения
областей, заметки проектов со счётчиками и сверка их с задачами в `pantheon check`.

Запуск: python3 -I plugins/pantheon/tests/test_story.py  (код выхода 0 — все прошли)
"""
import os
import re
import subprocess
import sys
import tempfile
import atexit
import shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="migr-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CLI = os.path.join(LIB, "pantheon.py")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

T0 = 1_792_000_000  # 2026-10-15
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


DIRS = '''[[direction]]
name = "metis-pantheon"
project = "Пантеон"
mark = "🟪"

[[direction]]
name = "athena-shop"
project = "Магазин"
'''


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="migr-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("directions/metis-pantheon/tasks", "directions/athena-shop/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    os.makedirs(view)
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(DIRS)
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0"}
    return tmp, home, state, view, env


def run(env, *args, t=T0):
    e = dict(env, PANTHEON_NOW=str(t))
    return subprocess.run([PY311, "-I", CLI, *args], env=e, capture_output=True, text=True, timeout=60)


def new(env, direction, *args):
    r = run(env, "task", "new", "--direction", direction, *args)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()[0], r.stdout.split()[1]


def head(home, rel):
    return T.split(open(os.path.join(home, rel), encoding="utf-8").read())[0]


def snapshot(home):
    out = {}
    for root, _, files in os.walk(os.path.join(home, "directions")):
        for f in files:
            p = os.path.join(root, f)
            out[p] = open(p, encoding="utf-8").read()
    return out


def main():
    tmp, home, state, view, env = make()
    places = ["запас", "6", "2", "5", "3"]  # нарочно вперемешку
    ids = {}
    for pl in places:
        ids[pl] = new(env, "metis-pantheon", "--title", f"Задача {pl}", "--batch", f"ночь-18.10 · {pl}")
    other = new(env, "athena-shop", "--title", "Чужая", "--batch", "ночь-18.10 · 2")
    plain = new(env, "metis-pantheon", "--title", "Без места", "--batch", "просто так")
    pre = new(env, "metis-pantheon", "--title", "Уже в пачке", "--batch", "ночь-18.10 · 9")
    st, _ = new(env, "metis-pantheon", "--type", "story", "--title", "Своя")
    assert run(env, "task", "attach", pre[0], st).returncode == 0

    before = snapshot(home)
    r = run(env, "task", "migrate-batches", "--dry-run")
    check("dry-run: план печатает, код 0", r.returncode == 0 and "создать" in r.stdout and "ночь-18.10" in r.stdout, r.stdout + r.stderr)
    check("dry-run: ничего не записано", snapshot(home) == before)

    r = run(env, "task", "migrate-batches", t=T0 + 100)
    check("перенос: код 0", r.returncode == 0, r.stderr[-300:])
    tasks = T.load_tasks(home, T.WORK_TYPES)
    stories = [i for i, (_, h, _) in tasks.items() if h.get("type") == "story" and h.get("title") == "ночь-18.10"]
    by_dir = {tasks[i][1]["direction"] for i in stories}
    check("по одной story «ночь-18.10» в каждом направлении (2)", len(stories) == 2 and by_dir == {"metis-pantheon", "athena-shop"}, stories)
    mine = next(i for i in stories if tasks[i][1]["direction"] == "metis-pantheon")
    ordered = T.story_order(mine, tasks)
    want = [ids[p][0] for p in ("2", "3", "5", "6", "запас")]
    check("в story пять задач в порядке 2, 3, 5, 6, запас", ordered == want, (ordered, want))
    check("у всех пяти batch убран, parent = story", all("batch" not in tasks[i][1] and tasks[i][1].get("parent") == mine for i in want))
    o = tasks[other[0]][1]
    check("задача другого направления — в своей story", o.get("parent") in stories and o["parent"] != mine and "batch" not in o, o)
    check("batch без «·» не тронут", tasks[plain[0]][1].get("batch") == "просто так" and not tasks[plain[0]][1].get("parent"))
    check("задача уже в пачке не тронута", tasks[pre[0]][1].get("parent") == st and tasks[pre[0]][1].get("batch") == "ночь-18.10 · 9")

    after = snapshot(home)
    r = run(env, "task", "migrate-batches", t=T0 + 200)
    check("повтор: переносить нечего, 0 изменений", r.returncode == 0 and "переносить нечего" in r.stdout and snapshot(home) == after, r.stdout)
    r = run(env, "task", "show", mine, t=T0 + 300)
    check("show пачки: пять задач", r.returncode == 0 and all(i in r.stdout for i in want), r.stdout[-300:])
    r = run(env, "check")
    check("pantheon check: шапки с order проходят", "order" not in r.stdout and "order" not in r.stderr, r.stdout[-300:] + r.stderr[-300:])
    shutil.rmtree(tmp, True)


if PY311:
    main()
else:
    print("skip: нужен Python 3.11+ для CLI")
print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
