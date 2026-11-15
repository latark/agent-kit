#!/usr/bin/env python3
"""Сверка плана с карточками пачек (metis-1235): lib/plancheck.py и строка доски.

- sections: разделы «## N. Пачка X «…»», ссылка [[id]] в заголовке, первой строке или строка «story: id»; номера
  задач только из строк таблиц, без зачёркнутого и кода; голые четыре цифры и id с префиксом.
- check: раздел без пачки, ссылка не на story, пачка найдена по имени в «ёлочках», задача не в своей пачке, пачка
  закрыта при открытых задачах; закрытые задачи и номера, которым нет задачи, — не расхождение.
- CLI `pantheon plan check <файл>`: код 1 и строки с `pantheon task attach`, код 0 без расхождений, код 2 без файла и
  с неверными аргументами; карточки не тронуты.
- plans/board_rows: поле plans в directions.toml и свежие plan-*.md направления; старый план не сверяется.
- boardtext.plan_lines: строка доски, чужая форма строки — пропуск.

Временные HOME, PANTHEON_HOME, PANTHEON_STATE; всё убирается в конце.
Запуск: python3.14 -I plugins/pantheon/tests/test_plancheck.py  (код выхода 0 — все прошли)
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402 — CLI pantheon только на Python 3.11+

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="plan-root-"))
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIB, "run.py")
sys.path.insert(0, LIB)
import boardtext as B  # noqa: E402
import plancheck as C  # noqa: E402

T0 = 1_792_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


PLAN = """# План

## 1. Главное

| Задача | Что |
|---|---|
| metis-0001 | не пачка — раздел не сверяется |

## 2. Пачка 0 «Ускорители» [[metis-0100]]

| Где | Задача |
|---|---|
| тесты | **metis-0001** — PR #416 (`batch/metis-0009`, head e268bd7c), набор 20261112-053839 |
| круги | **0002**, 0003 |
| ~~0004~~ | → пачка 1 |

Текст вне таблицы: 0005 остаётся в пачке 1.

## 3. Пачка 1 «Снять блокеры»

| Задача | Что |
|---|---|
| 0006 | открыта |
| 0007 | закрыта |

## 4. Пачка А «Без карточки»

| Задача | Что |
|---|---|
| 0008 | что-то |

## 5. Пачка Б «Ссылка мимо»

story: metis-0002

| Задача | Что |
|---|---|
| 9999 | номера нет — не задача |

## 6. Пачка В «Закрытая»
[[metis-0102]]

| Задача | Что |
|---|---|
| 0010 | открыта |
"""


def head(tid, typ="task", status="doing", parent=None, title=None, direction="metis-pantheon"):
    h = {"type": typ, "id": tid, "title": title or ("Задача " + tid), "status": status, "direction": direction}
    if parent:
        h["parent"] = parent
    return h


def fake_tasks():
    rows = [head("metis-0100", "story", "doing", title="Пачка 0 «Ускорители»"),
            head("metis-0101", "story", "doing", title="Пачка 1 «Снять блокеры» — 12.11"),
            head("metis-0102", "story", "done", title="Пачка В"),
            head("metis-0001", parent="metis-0100"),
            head("metis-0002", parent="metis-0100"),
            head("metis-0003", parent="metis-0050"),
            head("metis-0004"), head("metis-0005"), head("metis-0009"),
            head("metis-0006", parent="metis-0101"),
            head("metis-0007", status="done"),
            head("metis-0008"),
            head("metis-0010", parent="metis-0102"),
            head("athena-0003", direction="athena-demo")]
    return {h["id"]: (f"/x/{h['id']}.md", h, "") for h in rows}


def test_sections():
    secs = C.sections(PLAN)
    by = {s["num"]: s for s in secs}
    check("sections: только разделы «Пачка», по порядку", [s["num"] for s in secs] == ["2", "3", "4", "5", "6"],
          [s["num"] for s in secs])
    check("sections: ссылка в заголовке, строка story:, ссылка первой строкой",
          by["2"]["story"] == "metis-0100" and by["5"]["story"] == "metis-0002" and by["6"]["story"] == "metis-0102"
          and by["3"]["story"] is None, {k: v["story"] for k, v in by.items()})
    refs = [r for r, _ in by["2"]["refs"]]
    check("sections: id и голые номера из таблицы; код, SHA, длинные числа, зачёркнутое и текст вне таблицы — нет",
          refs == ["metis-0001", 2, 3], refs)


def test_check():
    found = C.check(PLAN, fake_tasks(), "metis-pantheon")
    kinds = sorted((k, n, s, tid, par) for k, n, s, tid, par, _ in found)
    want = sorted([("parent", "2", "metis-0100", "metis-0003", "metis-0050"),
                   ("no-story", "4", None, None, None),
                   ("not-story", "5", "metis-0002", None, None),
                   ("closed", "6", "metis-0102", "metis-0010", None)])
    check("check: задача в чужой пачке, раздел без пачки, ссылка не на story, закрытая пачка с открытой задачей",
          kinds == want, kinds)
    check("check: раздел 3 — пачка найдена по имени в «ёлочках», расхождений нет (0007 закрыта)",
          not any(n == "3" for _, n, *_ in found), found)
    t2 = fake_tasks()
    t2["metis-0006"][1].pop("parent")
    got = [x for x in C.check(PLAN, t2, "metis-pantheon") if x[1] == "3"]
    check("check: задача без parent в разделе пачки — расхождение «в пачке никакой»",
          len(got) == 1 and got[0][3] == "metis-0006" and "никакой" in C.describe(got[0]), got)
    got = C.check(PLAN, t2, None)
    check("check: без направления голый номер, который есть у двух направлений, не берётся",
          not any(x[3] == "metis-0003" for x in got), got)
    t3 = fake_tasks()
    t3["metis-0101"][1]["status"] = "done"
    t3["metis-0100"][1]["title"] = "П0"
    t3["metis-0101"][1]["title"] = "П1"
    got = sorted(x[1] for x in C.check(PLAN, t3, "metis-pantheon") if x[0] == "no-story")
    check("check: закрытая пачка по имени не находится — раздел без пачки", got == ["3", "4"], got)
    t4 = fake_tasks()
    t4["metis-0102"][1]["status"] = "doing"
    t4["metis-0010"][1]["status"] = "done"
    check("check: пачка открыта или задачи закрыты — «closed» нет",
          not any(x[0] == "closed" for x in C.check(PLAN, t4, "metis-pantheon")))


def write_task(home, h):
    d = os.path.join(home, "directions", h["direction"], "tasks")
    os.makedirs(d, exist_ok=True)
    full = dict(h, project="Пантеон", owner=h["direction"], created="2026-11-08", updated="2026-11-08T10:00:00",
                schema_version=1)
    lines = [f"{k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, str) else v}" for k, v in full.items()]
    p = os.path.join(d, h["id"] + ".md")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("---\n" + "\n".join(lines) + "\n---\n\n# " + h["title"] + "\n\n## Журнал\n\n- 2026-11-08 10:00 — агент: создана\n")
    return p


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="plan-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in (os.path.join(home, "inbox", "tasks"), state, view, os.path.join(tmp, ".claude", "pantheon")):
        os.makedirs(d)
    with open(os.path.join(home, "directions.toml"), "w", encoding="utf-8") as fh:
        fh.write('[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n\n'
                 '[[direction]]\nname = "athena-demo"\nproject = "DemoApp"\n')
    for _, h, _ in fake_tasks().values():
        write_task(home, h)
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0", "TMPDIR": tmp, "PANTHEON_NOW": str(T0)}
    return tmp, home, env


def pan(env, *a):
    return subprocess.run([PY311, "-I", RUN_PY, *a], env=env, capture_output=True, text=True, timeout=120)


def tree(home):
    out = {}
    for root, _, files in os.walk(os.path.join(home, "directions")):
        for f in files:
            p = os.path.join(root, f)
            out[p] = open(p, encoding="utf-8").read()
    return out


def test_cli():
    tmp, home, env = make()
    try:
        plan = os.path.join(home, "directions", "metis-pantheon", "plan-1.0.md")
        open(plan, "w", encoding="utf-8").write(PLAN)
        before = tree(home)
        r = pan(env, "plan", "check", plan)
        out = r.stdout
        check("CLI: расхождения — код 1, строка на каждое, команда attach у задачи не в своей пачке",
              r.returncode == 1 and "pantheon task attach metis-0003 metis-0100" in out and "раздел 4: нет карточки пачки" in out
              and "раздел 6: пачка metis-0102 закрыта, а открыты metis-0010" in out
              and "расхождений с карточками 4" in out, (r.returncode, out, r.stderr))
        check("CLI: карточки не тронуты", tree(home) == before)
        clean = os.path.join(home, "directions", "metis-pantheon", "plan-ok.md")
        open(clean, "w", encoding="utf-8").write("## 1. Пачка 0 «Ускорители»\n\n| З |\n|---|\n| 0001 |\n")
        r = pan(env, "plan", "check", clean)
        check("CLI: без расхождений — код 0", r.returncode == 0 and "расхождений с карточками нет" in r.stdout,
              (r.returncode, r.stdout, r.stderr))
        r = pan(env, "plan", "check", os.path.join(home, "нет.md"))
        check("CLI: файла нет — код 2, причина последней строкой",
              r.returncode == 2 and "не прочитан" in r.stderr.strip().splitlines()[-1], (r.returncode, r.stderr))
        r = pan(env, "plan", "check")
        check("CLI: без файла — код 2 и формат", r.returncode == 2 and "pantheon plan check" in r.stderr, r.stderr)
        r = pan(env, "plan", "check", plan, "--direction", "athena-demo")
        check("CLI: --direction — голые номера берутся у этого направления",
              r.returncode == 1 and "athena-0003" in r.stdout, r.stdout)
    finally:
        shutil.rmtree(tmp, True)


def test_board_rows():
    tmp, home, env = make()
    try:
        import tasks as T
        T.set_root(home)
        folder = os.path.join(home, "directions", "metis-pantheon")
        fresh, old = os.path.join(folder, "plan-new.md"), os.path.join(folder, "plan-old.md")
        for p in (fresh, old):
            open(p, "w", encoding="utf-8").write(PLAN)
        open(os.path.join(folder, "plan-text.md"), "w", encoding="utf-8").write("# без пачек\n")
        os.utime(fresh, (T0 - 3600, T0 - 3600))
        os.utime(old, (T0 - C.PLAN_FRESH - 3600, T0 - C.PLAN_FRESH - 3600))
        rows = C.board_rows(home, T.load_tasks(home, T.WORK_TYPES), T0)
        check("board_rows: свежий план с пачками сверен, старый и без пачек — нет",
              [r[0] for r in rows] == ["plan-new"] and rows[0][1] == 4 and len(rows[0][2]) == C.MAX_BOARD_ITEMS, rows)
        with open(os.path.join(home, "directions.toml"), "a", encoding="utf-8") as fh:
            fh.write('\n[[direction]]\nname = "zeus"\nproject = "Пританей"\nplans = ["directions/metis-pantheon/plan-old.md", '
                     '"directions/metis-pantheon/нет.md"]\n')
        rows = C.board_rows(home, T.load_tasks(home, T.WORK_TYPES), T0)
        check("board_rows: поле plans — план сверяется и старый, нечитаемый — число -1",
              ("plan-old", 4) in [(r[0], r[1]) for r in rows] and any(r[1] == -1 for r in rows), rows)
        got = B.plan_lines(rows)
        check("plan_lines: строка с числом, расхождениями и командой; нечитаемый — «не прочитан»",
              any("План plan-new: расхождений с карточками пачек 4: раздел" in x and "…" in x
                  and "pantheon plan check plan-new.md" in x for x in got)
              and any("не прочитан" in x for x in got), got)
        bad = B.plan_lines([("plan x/../y", 1, []), ("p", True, []), ("p", 2, ["<script>раздел 1: x"]), "мусор"])
        check("plan_lines: чужая форма — пропуск, строка не своего шаблона — не выводится",
              bad == ["- План p: расхождений с карточками пачек 2 … — pantheon plan check p.md"], bad)
        text = "\n".join(B.lines({"plan_drift": rows, "prs": []}))
        check("lines: строка плана в блоке board-auto", "План plan-new" in text, text)
    finally:
        shutil.rmtree(tmp, True)


def main():
    test_sections()
    test_check()
    test_cli()
    test_board_rows()
    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
