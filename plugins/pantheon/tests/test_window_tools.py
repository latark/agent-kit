#!/usr/bin/env python3
"""metis-0563: в окне разработчика `heavy pnpm check` находит pnpm и запускает tsx.

Запуск: python3 -I plugins/pantheon/tests/test_window_tools.py  (код выхода 0 — все прошли)
- run_env: в PATH окна — bin версии node по умолчанию из nvm (alias/default, иначе новейшая), версии сравниваются
  числами; nvm нет — PATH без него;
- heavy: в окне роли (PANTHEON_TMP) команда получает TMPDIR=$PANTHEON_TMP — песочница ставит TMPDIR туда, где сокеты
  запрещены, и tsx падал на listen EPERM (живая проба 27.10: с этой папкой tsx работает); без PANTHEON_TMP TMPDIR
  не трогается.
pantheon.py идёт на Python 3.11+, поэтому run_env проверяется подпроцессом.
"""
import json
import os
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib")
HEAVY = os.path.join(PLUGIN, "bin", "heavy")
CODE = "import json,sys; sys.path.insert(0, sys.argv[1]); import pantheon as P; print(json.dumps(P.run_env()['PATH']))"

fails, done = [], []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f" {extra}" if not cond else ""))
    done.append(name)
    if not cond:
        fails.append(name)


def path_of(home):
    env = {"HOME": home, "PATH": "/usr/bin:/bin", "PANTHEON_STATE": os.path.join(home, "state")}
    r = subprocess.run([PY311, "-I", "-c", CODE, LIB], env=env, capture_output=True, text=True, timeout=60)
    if r.returncode:
        print(r.stderr)
    return json.loads(r.stdout).split(":")


def heavy_tmpdir(home, tmp):
    env = {"HOME": home, "PATH": "/usr/bin:/bin", "TMPDIR": "/sandbox-tmp", "PANTHEON_STATE": os.path.join(home, "state")}
    if tmp:
        env["PANTHEON_TMP"] = tmp
    r = subprocess.run([sys.executable, "-I", HEAVY, "/bin/sh", "-c", "echo $TMPDIR"], env=env, capture_output=True,
                       text=True, timeout=60)
    return r.stdout.strip()


with tempfile.TemporaryDirectory(prefix="wintools-") as raw:
    home = os.path.realpath(raw)
    check("без nvm в PATH его нет", not any("/.nvm/" in d for d in path_of(home)))
    node = os.path.join(home, ".nvm", "versions", "node")
    for v in ("v18.20.1", "v22.9.0", "v22.10.2", "v20.1.0"):
        os.makedirs(os.path.join(node, v, "bin"))
    want = lambda v: os.path.join(node, v, "bin")  # noqa: E731
    p = path_of(home)
    check("без alias — новейшая версия, числами (22.10 > 22.9)", want("v22.10.2") in p and want("v22.9.0") not in p, p)
    os.makedirs(os.path.join(home, ".nvm", "alias"))
    with open(os.path.join(home, ".nvm", "alias", "default"), "w") as fh:
        fh.write("20\n")
    p = path_of(home)
    check("alias default «20» — v20.1.0", want("v20.1.0") in p and want("v22.10.2") not in p, p)
    check("bin nvm — вторым, после bin плагина", p.index(want("v20.1.0")) == 1, p)

    tmp = os.path.join(home, "cache", "tmp")
    os.makedirs(tmp)
    check("heavy в окне: TMPDIR = PANTHEON_TMP", heavy_tmpdir(home, tmp) == tmp)
    check("heavy вне окна: TMPDIR не тронут", heavy_tmpdir(home, None) == "/sandbox-tmp")
    check("heavy: папки PANTHEON_TMP нет — TMPDIR не тронут", heavy_tmpdir(home, os.path.join(home, "nope")) == "/sandbox-tmp")

print(f"\n{len(done) - len(fails)} из {len(done)} прошли")  # итог с числом: его требует run-tests.py
sys.exit(1 if fails else 0)
