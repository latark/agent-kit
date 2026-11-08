#!/usr/bin/env python3
"""metis-0947 (класс 3 модели угроз metis-0933): папка запуска направления — символьная ссылка (сама или звено пути):
start_target и direction_target отказывают строкой, окно не запускается; обычная папка — как раньше.

Запуск: python3 -I plugins/pantheon/tests/test_launch_symlink.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="lnksym-"))
tempfile.tempdir = _ROOT
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
os.environ.update({"HOME": os.path.join(_ROOT, "home"), "PANTHEON_HOME": os.path.join(_ROOT, "home", "ai", "pantheon"),
                   "PANTHEON_STATE": os.path.join(_ROOT, "state"), "PANTHEON_NO_NOTIFY": "1", "TMPDIR": _ROOT})
os.makedirs(os.environ["PANTHEON_HOME"])
os.makedirs(os.environ["PANTHEON_STATE"])
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


try:
    spec = importlib.util.spec_from_file_location("pantheon_lnksym_test", os.path.join(LIB, "pantheon.py"))
    P = importlib.util.module_from_spec(spec)
    sys.modules["pantheon_lnksym_test"] = P
    spec.loader.exec_module(P)
    home = os.environ["HOME"]
    real = os.path.join(home, "projects", "real")
    evil = os.path.join(home, "elsewhere", "evil")
    os.makedirs(real)
    os.makedirs(os.path.join(evil, "sub"))
    with open(os.path.join(evil, "CLAUDE.md"), "w") as fh:
        fh.write("чужие правила\n")
    os.symlink(evil, os.path.join(home, "projects", "linked"))  # сама папка — ссылка
    os.symlink(os.path.join(home, "elsewhere"), os.path.join(home, "projects", "mid"))  # ссылка в середине пути
    doms = {"plain": ["~/projects/real"], "leaf": ["~/projects/linked"], "mid": ["~/projects/mid/evil/sub"],
            "second": ["~/projects/nope", "~/projects/linked"], "abs": [real]}
    P.write_json(P.path("domains.json"), {"domains": doms})

    got = P.direction_target("plain", [], doms)
    check("обычная папка: окно как раньше", not isinstance(got, str) and got[2] == real and got[0] == "plain", got)
    got = P.direction_target("abs", [], doms)
    check("абсолютный путь обычной папки — как раньше", not isinstance(got, str) and got[2] == real, got)
    for name, where in (("leaf", "папка-ссылка"), ("mid", "ссылка в середине пути"),
                        ("second", "первая папка нет, вторая — ссылка")):
        got = P.direction_target(name, [], doms)
        check(f"{where}: отказ строкой про символьную ссылку, окна нет",
              isinstance(got, str) and "символьная ссылка" in got and "metis-0947" in got, got)
    got = P.direction_target("mid", [], doms)
    check("в строке отказа — путь самой ссылки", isinstance(got, str) and os.path.join(home, "projects", "mid") in got, got)
    got = P.start_target("leaf", [])
    check("start_target (sessions start): ссылка → строка отказа", isinstance(got, str) and "символьная ссылка" in got, got)
    got = P.start_target("plain", [])
    check("start_target: обычная папка — окно", not isinstance(got, str) and got[2] == real, got)
finally:
    shutil.rmtree(_ROOT, ignore_errors=True)

print(f"\n{sum(results)} из {len(results)} прошли")
sys.exit(0 if results and all(results) else 1)
