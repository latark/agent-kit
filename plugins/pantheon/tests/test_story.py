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

_ROOT = tempfile.mkdtemp(prefix="story-root-")
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
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="story-test-"))
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


def new(env, *args, t=T0):
    r = run(env, "task", "new", "--direction", "metis-pantheon", *args, t=t)
    assert r.returncode == 0, r.stderr
    return r.stdout.split()[0], r.stdout.split()[1]


def head(home, rel):
    return T.split(open(os.path.join(home, rel), encoding="utf-8").read())[0]


def story_checks(env, home):
    sid, srel = new(env, "--type", "story", "--title", "Пачка вечера", "--estimate", "1 % недели",
                    "--night", "2026-10-19")
    check("task new --type story: карточка type story", head(home, srel).get("type") == "story", head(home, srel))
    a, arel = new(env, "--title", "Первая", "--estimate", "0,2 % недели", "--touches", "plugins/pantheon/lib/", "--mode", "self")
    b, brel = new(env, "--title", "Вторая", "--estimate", "0,2 % недели", "--touches",
                  "plugins/pantheon/lib/tasks.py", "--mode", "parallel")
    c, crel = new(env, "--title", "Третья", "--estimate", "0,5 % недели", "--mode", "single")
    for x in (a, b, c):
        r = run(env, "task", "attach", x, sid, t=T0 + 10)
        check(f"attach {x} → пачка", r.returncode == 0 and head(home, arel if x == a else brel if x == b else crel)
              .get("parent") == sid, r.stderr[-200:])
    r = run(env, "task", "show", sid, t=T0 + 20)
    check("show пачки: «сумма 0,9 % из бюджета 1 %» и три задачи", r.returncode == 0 and "сумма 0,9 % из бюджета 1 %"
          in r.stdout and all(x in r.stdout for x in (a, b, c)), r.stdout[-400:])
    check("show пачки: пересечение по области первой и второй", f"{a} и {b}: plugins/pantheon/lib" in r.stdout,
          r.stdout[-300:])
    sjournal = open(os.path.join(home, srel), encoding="utf-8").read()
    check("attach: строка в журнал пачки", f"прикреплена задача {a}" in sjournal)
    r = run(env, "task", "attach", a, sid, t=T0 + 30)
    check("attach в ту же пачку — отказ", r.returncode != 0 and "уже в пачке" in r.stderr, r.stderr[-200:])
    s2, s2rel = new(env, "--type", "story", "--title", "Другая пачка")
    r = run(env, "task", "attach", c, s2, t=T0 + 40)
    check("attach в другую пачку: «была в», строка в журнал прежней",
          r.returncode == 0 and f"была в {sid}" in r.stdout and head(home, crel).get("parent") == s2
          and f"задача {c} перенесена в {s2}" in open(os.path.join(home, srel), encoding="utf-8").read(), r.stdout)
    r = run(env, "task", "show", sid, t=T0 + 50)
    check("после переноса сумма пачки 0,4 %", "сумма 0,4 % из бюджета 1 %" in r.stdout, r.stdout[-300:])
    r = run(env, "task", "attach", a, c, t=T0 + 55)
    check("attach к задаче, а не к пачке — отказ", r.returncode != 0 and "не пачка" in r.stderr, r.stderr[-200:])
    r = run(env, "task", "detach", c, t=T0 + 60)
    check("detach: parent снят, строка в журнал пачки", r.returncode == 0 and "parent" not in head(home, crel)
          and f"откреплена задача {c}" in open(os.path.join(home, s2rel), encoding="utf-8").read(), r.stderr[-200:])
    r = run(env, "task", "detach", c, t=T0 + 70)
    check("detach задачи вне пачки — понятная ошибка", r.returncode != 0 and "откреплять нечего" in r.stderr,
          r.stderr[-200:])
    return sid, a, b, c


def unit_checks():
    check("pct и pct_text: «0,5 % недели» → 0.5, 0.9 → «0,9 %»",
          T.pct("0,5 % недели") == 0.5 and T.pct("нет") is None and T.pct_text(0.9) == "0,9 %"
          and T.pct_text(1.0) == "1 %")
    check("paths_cross: вложенные и та же — да, соседние и префикс имени — нет",
          T.paths_cross("plugins/pantheon/", "plugins/pantheon/lib/watch.py") and T.paths_cross("./a/b", "a/b/")
          and not T.paths_cross("plugins/pan", "plugins/pantheon") and not T.paths_cross("a/x", "a/y")
          and not T.paths_cross("", "a"))
    tasks = {i: ("", {"type": "task", "status": st, "touches": tc}, "") for i, st, tc in (
        ("t-1", "todo", ["a/b"]), ("t-2", "doing", ["a/b/c.py"]), ("t-3", "done", ["a"]), ("t-4", "todo", ["z"]),
        ("t-5", "todo", []))}
    check("crossings: только живые задачи с пересекающимися областями",
          T.crossings(tasks) == {"t-1": ["t-2"], "t-2": ["t-1"]}, T.crossings(tasks))
    wt = {i: ("", {"type": "task", "status": "waiting", "waiting_on": w, "direction": "d"}, "") for i, w in (
        ("w-1", "human"), ("w-2", "agent"), ("w-3", "dependency"))}
    cnt = T.project_counts(wt, T0, {"d"})
    check("project_counts: «Ждёт вас» — только waiting_on = human, ждущие не человека не считаются",
          cnt["Ждёт вас"] == 1 and cnt["Открыто"] == 3, cnt)
    base = {"type": "task", "id": "metis-0001", "title": "x", "status": "todo", "project": "p", "direction": "p",
            "owner": "p", "created": "2026-10-17", "updated": "2026-10-17T10:00", "schema_version": T.SCHEMA_VERSION}
    text = T.join(dict(base, wave=3), "\n# x\n")
    h = T.split(text)[0]
    check("прежний ключ wave в файле читается как release", h.get("release") in (3, "3")
          and "wave" not in h, h)


def pult_checks(env, home, view, sid):
    board = os.path.join(view, "Доска")
    # просроченная задача и вопрос к владельцу в «Магазине»
    r = run(env, "task", "new", "--direction", "athena-shop", "--title", "Просрочка", "--due", "2026-10-01", t=T0)
    shop_tid = r.stdout.split()[0]
    r = run(env, "task", "new", "--direction", "athena-shop", "--title", "Вопрос", t=T0)
    q_tid = r.stdout.split()[0]
    r = run(env, "task", "set", q_tid, "status=waiting", "waiting_on=human", t=T0 + 5)
    check("задача ждёт владельца", r.returncode == 0, r.stderr[-300:])
    r = run(env, "board", t=T0 + 100)
    check("board: прошёл", r.returncode == 0, r.stderr[-400:])
    check("board: Пульт.base записан", os.path.isfile(os.path.join(board, "Пульт.base")))
    pn, sn = os.path.join(board, "Проекты", "Пантеон.md"), os.path.join(board, "Проекты", "Магазин.md")
    check("board: заметки проектов в Доска/Проекты/", os.path.isfile(pn) and os.path.isfile(sn),
          os.listdir(board))
    hp = T.split(open(pn, encoding="utf-8").read())[0] if os.path.isfile(pn) else {}
    hs = T.split(open(sn, encoding="utf-8").read())[0] if os.path.isfile(sn) else {}
    check("заметка «Пантеон»: Тип проект, 3 открытых, пачек 2, пересечений 2",
          hp.get("Тип") == "проект" and hp.get("Открыто") == 3 and hp.get("Пачек") == 2
          and hp.get("Пересечений") == 2, hp)
    check("заметка «Магазин»: просрочено 1, ждёт вас 1 — здоровье 🔴",
          hs.get("Просрочено") == 1 and hs.get("Ждёт вас") == 1 and str(hs.get("Здоровье", "")).startswith("🔴"), hs)
    story_card = next((f for f in os.listdir(board) if f.startswith(sid)), None)
    sc = T.split(open(os.path.join(board, story_card), encoding="utf-8").read()) if story_card else ({}, "")
    check("карточка пачки: Тип пачка, ссылка на пульт проекта, сумма оценок и «## Состав»",
          sc[0].get("Тип") == "пачка" and "Проекты/Пантеон" in str(sc[0].get("Пульт")) and sc[0].get("Сумма оценок")
          == "0,4 %" and "## Состав" in sc[1], sc[0])
    r = run(env, "check", t=T0 + 110)
    check("check: свежие счётчики пульта — ок (код 0)", r.returncode == 0 and "ОШИБКА" not in r.stdout,
          r.stdout[-400:] + r.stderr[-200:])
    # задача поменялась, счётчики те же — тик обновляет время заметки, сверка не выпадает
    run(env, "task", "set", shop_tid, "next=дальше", t=T0 + 120)
    run(env, "board", t=T0 + 130)
    newest = max(os.path.getmtime(os.path.join(dp, f)) for dp, _, fs in os.walk(os.path.join(home, "directions"))
                 for f in fs)
    check("тик: счётчики не изменились — время заметки не старше задач", os.path.getmtime(sn) >= newest)
    # подделка счётчика (вторая копия данных разошлась с задачами) — ошибка
    text = open(sn, encoding="utf-8").read()
    open(sn, "w", encoding="utf-8").write(re.sub(r"^Открыто: \d+$", "Открыто: 7", text, flags=re.M))
    r = run(env, "check", t=T0 + 140)
    check("check: счётчик заметки расходится с задачами — ОШИБКА и код 1",
          r.returncode == 1 and "ОШИБКА · Доска/Проекты/Магазин.md: счётчик «Открыто» 7, по задачам 2" in r.stdout,
          r.stdout[-400:])
    r = run(env, "check", "--quiet", t=T0 + 150)
    check("check --quiet (тик): расхождение — тревога, код 0", r.returncode == 0, r.stderr[-200:])
    run(env, "board", t=T0 + 200)
    r = run(env, "check", t=T0 + 210)
    check("тик перерисовал заметку — check снова 0", r.returncode == 0 and "ОШИБКА" not in r.stdout, r.stdout[-300:])
    # чужой файл в Проекты/ не сверяется и не перезаписывается
    alien = os.path.join(board, "Проекты", "Мои мысли.md")
    open(alien, "w", encoding="utf-8").write("---\nОткрыто: 99\n---\nсвоё\n")
    r = run(env, "check", t=T0 + 220)
    check("чужая заметка без «Тип: проект» в Проекты/ — не ошибка", r.returncode == 0, r.stdout[-300:])


def main():
    unit_checks()
    tmp, home, state, view, env = make()
    sid, a, b, c = story_checks(env, home)
    pult_checks(env, home, view, sid)
    print(f"\n{sum(results)} из {len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
