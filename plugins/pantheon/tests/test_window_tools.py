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

# metis-0569: окно без nvm в PATH — heavy находит pnpm сама и не падает FileNotFoundError
def heavy_run(home, args, state=None):
    env = {"HOME": home, "PATH": "/usr/bin:/bin", "PANTHEON_STATE": state or os.path.join(home, "state")}
    return subprocess.run([sys.executable, "-I", HEAVY, *args], env=env, capture_output=True, text=True, timeout=60)


with tempfile.TemporaryDirectory(prefix="wintools-") as raw:
    home = os.path.realpath(raw)
    bins = {v: os.path.join(home, ".nvm", "versions", "node", v, "bin") for v in ("v20.1.0", "v22.9.0")}
    for v, b in bins.items():
        os.makedirs(b)
    pnpm = os.path.join(bins["v22.9.0"], "pnpm")
    with open(pnpm, "w") as fh:
        fh.write('#!/bin/sh\necho "pnpm-ok $1"; echo "$PATH" | cut -d: -f1\n')
    os.chmod(pnpm, 0o755)
    r = heavy_run(home, ["pnpm", "run"])  # без мест блокировки
    check("pnpm только в nvm (alias нет): найден, код 0", r.returncode == 0 and "pnpm-ok run" in r.stdout, r.stderr + r.stdout)
    check("папка pnpm первой в PATH команды (shebang env node)", r.stdout.splitlines()[-1:] == [bins["v22.9.0"]], r.stdout)
    locks = os.path.join(home, "state", "locks")
    os.makedirs(locks)
    for n in ("heavy-cmd-1", "heavy-cmd-2"):
        open(os.path.join(locks, n + ".lock"), "w").close()
    r = heavy_run(home, ["pnpm", "run"])
    check("то же с местами блокировки", r.returncode == 0 and "pnpm-ok run" in r.stdout, r.stderr + r.stdout)
    os.makedirs(os.path.join(home, ".nvm", "alias"))
    with open(os.path.join(home, ".nvm", "alias", "default"), "w") as fh:
        fh.write("20\n")
    r = heavy_run(home, ["pnpm", "x"])
    check("pnpm есть не в версии по умолчанию — всё равно найден", r.returncode == 0 and "pnpm-ok x" in r.stdout, r.stderr)
    r = heavy_run(home, ["nosuchtool-xyz", "x"])
    check("команды нет нигде — код 127, строка без трейсбэка, места не заняты",
          r.returncode == 127 and "не найдена" in r.stderr and "Traceback" not in r.stderr and "жду" not in r.stderr, r.stderr)
    r = heavy_run(home, ["echo", "hi"])
    check("команда из PATH идёт как раньше", r.returncode == 0 and r.stdout.strip() == "hi", r.stderr)
    r = heavy_run(home, ["/bin/sh", "-c", "exit 3"])
    check("код выхода команды сохраняется", r.returncode == 3)

print(f"\n{len(done) - len(fails)} из {len(done)} прошли")  # итог с числом: его требует run-tests.py
sys.exit(1 if fails else 0)
