#!/usr/bin/env python3
"""Справка по видам доски (metis-0288): у каждого вида Доска.base есть строка «что здесь и что вам делать» (VIEW_HELP),
Сводка.md встраивает каждый вид со своей строкой, Справка/Виды доски.md перечисляет те же строки, pantheon check
отказывает при виде без строки или строке без вида.

Запуск: python3 -I plugins/pantheon/tests/test_view_help.py  (код выхода 0 — все прошли)
"""
import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="vhelp-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CLI = os.path.join(LIB, "pantheon.py")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

T0 = 1_792_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def unit_checks():
    names = T.base_views(T.BASE_FILE)
    check("в шаблоне пять видов, имена не удлинены (до 14 знаков)", len(names) == 5 and all(len(n) <= 14 for n in names), names)
    check("у каждого вида шаблона есть непустая строка, лишних нет",
          list(T.VIEW_HELP) == names and all(v.strip() for v in T.VIEW_HELP.values()), (names, list(T.VIEW_HELP)))
    check("строки человеческие: «Что делать:» в каждой, без формул и полей",
          all("Что делать:" in v and "note[" not in v and "formula." not in v for v in T.VIEW_HELP.values()))
    check("check_views: шаблон и строки сходятся — расхождений нет", T.check_views() == [], T.check_views())
    # вид без строки
    lines = dict(T.VIEW_HELP)
    del lines["Пачки"]
    bad = T.check_views(help_lines=lines)
    check("вид без строки — расхождение с его именем", len(bad) == 1 and "«Пачки»" in bad[0], bad)
    lines = dict(T.VIEW_HELP, **{"Лишний": "строка без вида"})
    bad = T.check_views(help_lines=lines)
    check("строка без вида — расхождение", len(bad) == 1 and "«Лишний»" in bad[0], bad)
    lines = dict(T.VIEW_HELP, **{"Доска": "   "})
    check("пустая строка у вида — расхождение", len(T.check_views(help_lines=lines)) == 1)
    extra = T.BASE_FILE.rstrip("\n") + "\n  - type: table\n    name: Новый вид\n"
    bad = T.check_views(base_text=extra)
    check("новый вид в .base без строки — расхождение", len(bad) == 1 and "«Новый вид»" in bad[0], bad)
    text, _ = T._summary({}, T0)
    emb = re.findall(r"^## (.+)\n\n(.+)\n\n!\[\[Доска\.base#(.+)\]\]$", text, re.M)
    check("сводка: каждый вид — заголовок, его строка, встраивание (по порядку меню)",
          emb == [(n, T.VIEW_HELP[n], n) for n in T.base_views(T.BASE_FILE)], emb[:2])
    note = T.render_help_note()
    check("справка: строка каждого вида списком", all(f"- **{n}** — {line}" in note for n, line in T.VIEW_HELP.items()))


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="vhelp-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("directions/metis-pantheon/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    os.makedirs(view)
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(
        '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0"}
    return tmp, home, view, env


def run(env, *args, t=T0):
    e = dict(env, PANTHEON_NOW=str(t))
    return subprocess.run([PY311, "-I", CLI, *args], env=e, capture_output=True, text=True, timeout=60)


def live_checks():
    tmp, home, view, env = make()
    board = os.path.join(view, "Доска")
    r = run(env, "task", "new", "--text", "тест", "--direction", "metis-pantheon", "--title", "Первая")
    assert r.returncode == 0, r.stderr
    r = run(env, "board", t=T0 + 10)
    check("тик: код 0", r.returncode == 0, r.stderr[-300:])
    sv = open(os.path.join(board, "Сводка.md"), encoding="utf-8").read()
    check("Сводка.md: все пять встраиваний со строками",
          all(f"## {n}\n\n{line}\n\n![[Доска.base#{n}]]" in sv for n, line in T.VIEW_HELP.items()))
    hp = os.path.join(board, "Справка", "Виды доски.md")
    check("файл Справка/Виды доски.md записан", os.path.isfile(hp))
    if os.path.isfile(hp):
        check("в справке строка каждого вида", all(f"- **{n}** — {line}" in open(hp, encoding="utf-8").read()
                                                  for n, line in T.VIEW_HELP.items()))
    check("справка не попадает в задачи доски (фильтр Доска.base по папке Доска)", 'file.folder == "Доска"' in T.BASE_FILE)
    r = run(env, "check", t=T0 + 20)
    check("check: виды и строки сходятся — код 0", r.returncode == 0 and "ОШИБКА" not in r.stdout, r.stdout[-300:])
    # владелец добавил вид в свой Доска.base — у него нет строки
    bp = os.path.join(board, "Доска.base")
    open(bp, "a", encoding="utf-8").write("  - type: table\n    name: Мой вид\n")
    r = run(env, "check", t=T0 + 30)
    check("check: вид без строки — ОШИБКА и код 1", r.returncode == 1 and "«Мой вид»" in r.stdout, r.stdout[-300:])
    r = run(env, "check", "--quiet", t=T0 + 40)
    check("check --quiet (тик): тревога, код 0", r.returncode == 0, r.stderr[-200:])
    # чужой файл на месте справки не затирается
    os.remove(hp)
    open(hp, "w", encoding="utf-8").write("мои записи\n")
    run(env, "board", t=T0 + 50)
    check("чужой файл «Виды доски.md» не перезаписан", open(hp, encoding="utf-8").read() == "мои записи\n")
    shutil.rmtree(tmp, True)


unit_checks()
if PY311:
    live_checks()
else:
    print("skip: нужен Python 3.11+ для CLI")
print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
