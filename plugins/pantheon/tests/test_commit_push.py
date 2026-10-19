#!/usr/bin/env python3
"""push автокоммита (metis-0133): буфер -c http.postBuffer на каждый push и тревога после 3 неудач подряд.

Запуск: python3 -I plugins/pantheon/tests/test_commit_push.py  (код выхода 0 — все прошли)
Всё во временных папках; git подменён функцией, которая записывает вызовы и отвечает по сценарию.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="commit-push-"))
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


home, pan, state = (os.path.join(ROOT, d) for d in ("home", "pantheon", "state"))
for d in (home, os.path.join(pan, ".git"), state):
    os.makedirs(d, exist_ok=True)

PROBE = f"""
import json, os, subprocess, sys
sys.path.insert(0, {LIB!r})
import pantheon as p
calls = []
script = iter(json.loads(os.environ["PUSH_SCRIPT"]))
def fake_git(*args, check=True):
    calls.append(list(args))
    out, rc, err = "", 0, ""
    if "push" in args:
        rc, err = next(script)
    elif "remote" in args:
        out = "origin\\n"
    elif "rev-list" in args:
        out = "1\\n"
    return subprocess.CompletedProcess(args, rc, out, err)
p.git = fake_git
codes = [p.commit() for _ in range(len(json.loads(os.environ["PUSH_SCRIPT"])))]
pushes = [c for c in calls if "push" in c]
alerts = open(os.path.join({pan!r}, "alerts.md")).read() if os.path.exists(os.path.join({pan!r}, "alerts.md")) else ""
print(json.dumps({{"codes": codes, "pushes": pushes, "alerts": alerts,
                  "fail": p.read_json(p.path("push-fail.json"))}}))
"""


def run(script):
    env = {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pan, "PANTHEON_STATE": state,
           "PUSH_SCRIPT": json.dumps(script), "PANTHEON_NOTIFY_LOG": os.path.join(ROOT, "notify.log")}
    r = subprocess.run([PY311, "-I", "-c", PROBE], env=env, capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print(r.stdout, r.stderr)
        return {}


HTTP = "error: RPC failed; HTTP 413 curl 22 The requested URL returned error: 413\nfatal: the remote end hung up"
NET = "fatal: unable to access 'https://x/': Could not resolve host: github.com"

got = run([[1, HTTP]])
pushes = got.get("pushes") or [[]]
check("push несёт -c http.postBuffer=157286400 перед подкомандой",
      pushes[0][:2] == ["-c", "http.postBuffer=157286400"] and pushes[0][2] == "push", pushes)
check("первая неудача по HTTP: счётчик 1, тревоги нет", (got.get("fail") or {}).get("n") == 1
      and "push не проходит" not in got.get("alerts", ""), got)

got = run([[1, HTTP], [1, NET], [1, HTTP]])  # 1 уже записана прошлым прогоном; сеть счётчик не трогает
check("третья неудача подряд (без сети между ними не считается) → тревога",
      (got.get("fail") or {}).get("n") == 3 and got.get("alerts", "").count("push не проходит 3 раза подряд") == 1, got)

got = run([[1, HTTP]])
check("четвёртая и дальше — без повторной тревоги", got.get("alerts", "").count("push не проходит") == 1, got)

got = run([[0, ""]])
check("удача сбрасывает счётчик", not got.get("fail") and not os.path.exists(os.path.join(state, "push-fail.json")), got)

for _ in range(3):
    got = run([[1, NET]])
check("обрыв сети не считается: три «нет сети» подряд — счётчика нет", not got.get("fail"), got)

got = run([[1, HTTP], [1, HTTP], [1, HTTP]])
check("после сброса новая серия из трёх даёт новую тревогу",
      got.get("alerts", "").count("push не проходит") == 2, got)

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
