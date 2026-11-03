#!/usr/bin/env python3
"""Сторож тишины прогона тестов (metis-0770, lib/outside.py: wait_proc(idle_log), Silent, tree_cpu).

Запуск: python3 -I plugins/pantheon/tests/test_outside_idle.py  (код выхода 0 — все прошли)
Временный репозиторий, sandbox-exec подменён заглушкой, IDLE_TIMEOUT — 2 с. Проверяет: молчащий `sleep` гасится
SIGKILL по тишине (state=failed, why «тишина … последний вывод: …», причина и в логе прогона, и в outside.jsonl,
процесса нет); процесс, пишущий строку раз в 0,5 с, не гасится (его останавливает только общий TEST_TIMEOUT);
молчащий, но тратящий CPU — не гасится; CPU не узнать (ps пуст) — судим по тишине; разбор времени ps.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311  # noqa: E402,F401

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="outside-idle-"))
tempfile.tempdir = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)
HOME = os.path.join(_ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE"))]:
    os.environ.pop(k)
os.environ.update({"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1", "TMPDIR": _ROOT})
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import pantheon as P  # noqa: E402
O = P.outside_mod()

FAILS, TOTAL = [], [0]


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{str(extra)[-800:]}]"))
    if not cond:
        FAILS.append(name)


FAKE = os.path.join(_ROOT, "fake-sandbox-exec")
with open(FAKE, "w") as fh:
    fh.write(f"#!{sys.executable}\nimport os, sys\ncmd = sys.argv[3:]\nos.execvp(cmd[0], cmd)\n")
os.chmod(FAKE, 0o755)
O.SANDBOX_EXEC = FAKE
O.HEAVY = None
O.IDLE_TIMEOUT = 2
O.SWEEP_EVERY = 0.2

N = [0]


def repo(line):
    d = os.path.join(HOME, "projects", f"r{N[0]}")
    os.makedirs(d)

    def g(*a):
        return subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                               "commit.gpgsign=false", *a], capture_output=True, text=True, check=True)
    g("init", "-q", "-b", "feat")
    g("remote", "add", "origin", "git@github.com:latark/rk.git")
    with open(os.path.join(d, ".pantheon-verify"), "w") as fh:
        fh.write(line + "\n")
    g("add", "-A")
    g("commit", "-q", "-m", "c")
    return d


def run(line, timeout=6):
    N[0] += 1
    O.TEST_TIMEOUT = timeout
    d = repo(line)
    rid = f"20261103-{N[0]:06d}-abcdef"
    t0 = time.monotonic()
    res = O.run_test(rid, d, None, "metis-r", None, [d])
    return res, time.monotonic() - t0


def events():
    try:
        with open(os.path.join(STATE, "logs", "outside.jsonl")) as fh:
            return [json.loads(x) for x in fh if x.strip()]
    except OSError:
        return []


def alive(pat):
    return subprocess.run(["pgrep", "-f", pat], capture_output=True).returncode == 0


SPIN = "python3 -c 'import time; t=time.time()\nwhile time.time()-t<30: pass'"

res, dt = run("echo started-ok; sleep 31337")
log = open(res["log"]).read() if res.get("log") else ""
check("молчащий sleep гасится по тишине: failed, why «тишина» и последняя строка",
      res.get("state") == "failed" and "тишина" in res.get("why", "") and "started-ok" in res["why"] and dt < 5,
      (res, dt))
check("причина — в логе прогона и в outside.jsonl", "тишина" in log and any(
    e.get("kind") == "test-silent" and "тишина" in e.get("why", "") for e in events()), (log, events()))
time.sleep(0.3)
check("дерево убито: sleep не жив", not alive("sleep 31337"))

res, dt = run("while :; do echo tick; sleep 0.5; done", timeout=5)
check("строка раз в 0,5 с — не гасится по тишине (стоп только по общему сроку)",
      res.get("state") == "done" and "дольше" in res.get("why", "") and "тишина" not in res.get("why", ""), res)

res, dt = run("echo busy; " + SPIN, timeout=5)
check("молчит, но жжёт CPU — не гасится по тишине",
      res.get("state") == "done" and "тишина" not in res.get("why", ""), res)

_ps = O.ps_table
O.ps_table = lambda: {}
res, dt = run("echo nops; " + SPIN, timeout=8)
O.ps_table = _ps
check("ps недоступен, CPU не узнать — суд по тишине лога",
      res.get("state") == "failed" and "тишина" in res.get("why", "") and "nops" in res["why"], res)

check("разбор времени ps", O._cpu_secs("1:02.50") == 62.5 and O._cpu_secs("1:00:00") == 3600
      and O._cpu_secs("1-00:00:01") == 86401 and O._cpu_secs("x") is None)

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
