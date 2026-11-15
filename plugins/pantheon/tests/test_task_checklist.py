#!/usr/bin/env python3
"""Пункты «Готово, когда» списком без чекбокса (metis-1266): `task new` и `task set --body` приводят их к «- [ ] …» и
говорят об этом строкой в stderr — иначе done_criteria их не видит, `pantheon review criteria` отвечает «пунктов нет»,
а argus не может отметить.

Запуск: python3 -I plugins/pantheon/tests/test_task_checklist.py  (код выхода 0 — все прошли)
Проверяет: task new с «1. … 2) …» и строкой продолжения — пункты «- [ ]», продолжение склеено, строка «без чекбокса —
2», `review criteria` их видит; task new с «- [ ] …» — без строки и без правки; простой список «- …» — тоже
приводится; task set --body с нумерованным списком — приводится. checklist_done_when: нумерованный список вне раздела
и после конца раздела не трогается, «- [x]» остаётся. Мутанты — внутри теста: подменённый taskcli.py (функция
checklist_done_when) и копия lib, где task_body_arg её не зовёт; мутант убит, только если покраснел названный случай.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import types
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402 — CLI pantheon только на Python 3.11+

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="checklist-root-"))
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
TASKCLI_PY = os.path.join(LIB, "taskcli.py")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

T0 = datetime(2026, 11, 15, 12, 0).timestamp()
results = []

NUMBERED = "Цель: проверить.\n\n## Готово, когда\n1. первый пункт\n2) второй пункт\n   и его продолжение\n"
CHECKED = "Цель: проверить.\n\n## Готово, когда\n- [ ] первый пункт\n- [x] второй пункт\n"
BULLETS = "Цель: проверить.\n\nГотово, когда:\n- первый пункт\n* второй пункт\n"


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="checklist-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("directions/metis-pantheon/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    os.makedirs(view)
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(
        '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0", "PANTHEON_SESSION": "metis-pantheon", "PANTHEON_NOW": str(T0)}
    return tmp, home, env


def scen_cli(run_py):
    """CLI на lib, где лежит run_py → {случай: bool}."""
    tmp, home, env = make()

    def pan(*a):
        return subprocess.run([PY311, "-I", run_py, *a], env=env, capture_output=True, text=True, timeout=120)

    def new(body):
        r = pan("task", "new", "--direction", "metis-pantheon", "--title", "Проверка", "--body", body)
        tid = r.stdout.split()[0] if r.returncode == 0 and r.stdout.split() else None
        path = os.path.join(home, "directions", "metis-pantheon", "tasks", f"{tid}.md")
        return r, tid, (open(path, encoding="utf-8").read() if tid and os.path.exists(path) else "")

    out = {}
    try:
        r, tid, card = new(NUMBERED)
        crit = pan("review", "criteria", tid).stdout if tid else ""
        out["new: «1. …» и «2) …» — пункты «- [ ]», продолжение склеено"] = (
            T.done_criteria(card) == [(False, "первый пункт"), (False, "второй пункт и его продолжение")])
        out["new: строка в stderr «без чекбокса — 2»"] = "без чекбокса — 2" in r.stderr
        out["new: review criteria видит оба пункта"] = f"{tid}#1 [ ] первый пункт" in crit and f"{tid}#2 [ ]" in crit
        r2, _, card2 = new(CHECKED)
        out["new: «- [ ] …» — без строки, текст как был"] = (
            "без чекбокса" not in r2.stderr and T.done_criteria(card2) == [(False, "первый пункт"), (True, "второй пункт")])
        _, _, card3 = new(BULLETS)
        out["new: простой список «- …», «* …» — тоже «- [ ]»"] = (
            T.done_criteria(card3) == [(False, "первый пункт"), (False, "второй пункт")])
        _, tid4, _ = new(CHECKED)
        r4 = pan("task", "set", tid4, "--body", NUMBERED) if tid4 else None
        card4 = open(os.path.join(home, "directions", "metis-pantheon", "tasks", f"{tid4}.md"),
                     encoding="utf-8").read() if tid4 else ""
        out["set --body: нумерованный список — «- [ ]» и строка в stderr"] = (
            r4 is not None and r4.returncode == 0 and "без чекбокса — 2" in r4.stderr
            and [x for _, x in T.done_criteria(card4)] == ["первый пункт", "второй пункт и его продолжение"])
    except Exception as e:  # noqa: BLE001 — упавший шаг: недошедшие случаи красные
        out["шаг упал"] = repr(e) and False
    finally:
        shutil.rmtree(tmp, True)
    return out


def scen_unit(fn):
    """checklist_done_when (fn) → {случай: bool}."""
    pairs = [
        ("unit: «1. шаг» до раздела не трогается",
         lambda: fn("Шаги:\n1. шаг\n\n## Готово, когда\n1. пункт\n") == ("Шаги:\n1. шаг\n\n## Готово, когда\n- [ ] пункт\n",
                                                                           1)),
        ("unit: после конца раздела (строка не из списка) — не трогается",
         lambda: fn("## Готово, когда\n1. пункт\nТекст.\n2. не пункт\n") == (
             "## Готово, когда\n- [ ] пункт\nТекст.\n2. не пункт\n", 1)),
        ("unit: «- [x]» остаётся, «3. …» после него приводится",
         lambda: fn("## Готово, когда\n- [x] было\n3. новое\n") == ("## Готово, когда\n- [x] было\n- [ ] новое\n", 1)),
        ("unit: строка с отступом — продолжение пункта",
         lambda: fn("## Готово, когда\n1. начало\n   конец\n") == ("## Готово, когда\n- [ ] начало конец\n", 1)),
        ("unit: номер с чекбоксом «1. [x]», «2. [ ]» → «- [x]», «- [ ]»",
         lambda: fn("## Готово, когда\n1. [x] было\n2. [ ] будет\n") == (
             "## Готово, когда\n- [x] было\n- [ ] будет\n", 2)),
        ("unit: без раздела — как было, 0", lambda: fn("1. шаг\n2. шаг") == ("1. шаг\n2. шаг", 0)),
    ]
    out = {}
    for name, f in pairs:
        try:
            out[name] = bool(f())
        except Exception:  # noqa: BLE001 — упавший случай красный
            out[name] = False
    return out


def load_taskcli(src):
    """taskcli.py (src — подменённый текст) отдельным модулем → его checklist_done_when с настоящим tasks (T). P ему
    не нужен: функция P не трогает."""
    m = types.ModuleType("taskcli_mut")
    m.__file__ = TASKCLI_PY
    exec(compile(src, TASKCLI_PY, "exec"), m.__dict__)
    return lambda text: m.checklist_done_when(T, text)


UNIT_MUTANTS = [
    ("        elif m:\n            ln, last, n =", "        elif False:\n            ln, last, n =",
     "unit: «- [x]» остаётся, «3. …» после него приводится"),
    ("            out[last] += \" \" + ln.strip()\n            continue", "            pass",
     "unit: строка с отступом — продолжение пункта"),
    ("        elif ln.strip():\n            on, last = False, None", "        elif False:\n            on, last = False, None",
     "unit: после конца раздела (строка не из списка) — не трогается"),
    ("        if not on:\n            on = bool(T._DW_LINE.match(ln))\n        elif m:",
     "        if False:\n            on = bool(T._DW_LINE.match(ln))\n        elif m:",
     "unit: «1. шаг» до раздела не трогается"),
]
UNIT_MUTANTS.append(("{m.group(2) or '[ ]'}", "[ ]", "unit: номер с чекбоксом «1. [x]», «2. [ ]» → «- [x]», «- [ ]»"))
CLI_OLD = 'text, n = checklist_done_when(T, "\\n\\n".join(x.strip() for x in parts))'
CLI_NEW = 'text, n = "\\n\\n".join(x.strip() for x in parts), 0'


def main():
    cli_src = open(TASKCLI_PY, encoding="utf-8").read()
    for name, ok in scen_unit(load_taskcli(cli_src)).items():
        check(name, ok)
    for name, ok in scen_cli(os.path.join(LIB, "run.py")).items():
        check(name, ok)
    for old, new, case in UNIT_MUTANTS:
        if cli_src.count(old) != 1:
            check(f"мутант taskcli.py «{old.strip()[:40]}»: строка одна", False, cli_src.count(old))
            continue
        got = scen_unit(load_taskcli(cli_src.replace(old, new)))
        check(f"мутант taskcli.py «{old.strip()[:40]}» убит случаем «{case}»", got.get(case) is False, got)
    if cli_src.count(CLI_OLD) != 1:
        check("мутант taskcli.py: строка вызова checklist_done_when одна", False, cli_src.count(CLI_OLD))
    else:
        d = os.path.join(_ROOT, "mutlib")
        shutil.copytree(LIB, d, ignore=shutil.ignore_patterns("__pycache__"))
        with open(os.path.join(d, "taskcli.py"), "w", encoding="utf-8") as fh:
            fh.write(cli_src.replace(CLI_OLD, CLI_NEW))
        got = scen_cli(os.path.join(d, "run.py"))
        case = "new: «1. …» и «2) …» — пункты «- [ ]», продолжение склеено"
        alive = "new: «- [ ] …» — без строки, текст как был"   # копия lib работает: красное — от мутанта, а не от сбоя
        check(f"мутант taskcli.py без checklist_done_when убит случаем «{case}»",
              got.get(case) is False and got.get(alive) is True, got)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(_ROOT, True)
    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.stdout.flush()
    os._exit(0 if results and all(results) else 1)
