#!/usr/bin/env python3
"""Сводка тела PR в заявке слияния (metis-1347, приём PurpleFlow п. 4, разбор metis-1339): `pantheon merge request`
кладёт в заявку поле summary — строку «Closes …» и первые строки тела PR — и печатает её; `merge status` её
показывает. Окно Touch ID не меняется.

Запуск: python3 -I plugins/pantheon/tests/test_merge_summary.py  (код выхода 0 — все прошли)
Проверяет: тело с разметкой, управляющими знаками (ESC, U+202E, перевод строки внутри) и длинной строкой → сводка в
файле заявки и выводе, Closes первой, без управляющих, bidi, кавычек и разметки, не длиннее BODY_MAX с «…»; пустое
тело → пустая сводка и «(пусто)». Мутант — внутри теста: копия плагина, где сводка — сырое тело, убита случаем.
"""
# ruff: noqa: F403, F405
import os
import subprocess
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_common import *  # noqa: F403
from _py311 import copy_plugin  # noqa: E402 — общий помощник (metis-1432)

BODY_MAX = 240
BODY = ("## Что сделано\n\n- правка \x1b[31mmerge.py\u202e: сводка\n* «вторая» строка " + "длинная " * 60
        + "\n\nCloses metis-1347\nтретья строка\nчетвёртая строка не входит\n")
CALL = "said[pr] = body_summary(view)"





def mutant_run(tmp):
    """Копия плагина pantheon, где сводка — сырое тело PR → путь к её run.py (None — строка вызова не одна)."""
    plugins = os.path.join(tmp, "mut", "plugins")
    plug = os.path.join(plugins, "pantheon")
    copy_plugin(os.path.dirname(LIBDIR), plug)
    os.symlink(os.path.dirname(GUARD_HOOKS), os.path.join(plugins, "guard"))
    f = os.path.join(plug, "lib", "merge.py")
    src = open(f, encoding="utf-8").read()
    if src.count(CALL) != 1:
        return None
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(src.replace(CALL, 'said[pr] = str(view.get("body") or "")'))
    return os.path.join(plug, "lib", "run.py")


def clean(s):
    return not any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp", "Pi", "Pf") for c in s)


def summary_ok(b, run_py=RUN_PY):
    """Случай: заявка на PR с грязным телом — сводка чистая, короткая, Closes первой, и в выводе тоже."""
    r = subprocess.run([PY311, "-I", run_py, "merge", "request", str(PR), "-R", REPO], env=b.env(T0),
                       capture_output=True, text=True, timeout=120)
    req = b.req() or {}
    s = req.get("summary")
    ok = (r.returncode == 0 and isinstance(s, str) and clean(s) and len(s) <= BODY_MAX and s.endswith("…")
          and s.startswith("Closes metis-1347 / Что сделано / правка") and "[31mmerge.py: сводка" in s
          and "##" not in s and " / - " not in s and "вторая строка длинная" in s and "четвёртая" not in s
          and f"тело PR со слов автора: {s}" in r.stdout)
    return ok, f"rc={r.returncode} summary={s!r}\n{r.stdout}{r.stderr}"


def test_summary_in_request():
    b = Box()
    b.view(SHA, head={"body": BODY, "headRefName": "metis-1347-x"})
    ok, out = summary_ok(b)
    check("merge request: сводка тела в заявке и выводе — Closes первой, без управляющих и разметки, ≤ 240 с «…»",
          ok, out)
    r = b.cli(["merge", "status"])
    check("merge status: у заявки «тело: Closes metis-1347 …»", r.returncode == 0
          and "тело: Closes metis-1347 / Что сделано" in r.stdout and "\x1b" not in r.stdout and "\u202e" not in r.stdout,
          r.stdout + r.stderr)


def test_empty_body():
    b = Box()
    b.view(SHA, head={"body": "", "headRefName": "feature"})
    r = b.request()
    check("merge request: пустое тело — пустая сводка и «(пусто)» в выводе", r.returncode == 0 and b.req()
          and b.req().get("summary") == "" and "тело PR со слов автора: (пусто)" in r.stdout, b.outs[-1])


def test_mutant_raw_body():
    b = Box()
    b.view(SHA, head={"body": BODY, "headRefName": "metis-1347-x"})
    run_py = mutant_run(b.tmp)
    check("мутант: строка сводки в cmd_request одна", run_py is not None, CALL)
    if run_py:
        ok, out = summary_ok(b, run_py)
        check("мутант «сводка — сырое тело» убит случаем «сводка чистая и короткая»", not ok, out)


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    cases = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    run_cases(cases, FAILS, lambda name, err: FAILS.append(name))
    print(f"\n{'ПРОВАЛ: ' + ', '.join(FAILS) if FAILS else f'{len(cases)} из {len(cases)} случаев прошли'}")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
