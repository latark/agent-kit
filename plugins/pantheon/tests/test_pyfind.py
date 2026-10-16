#!/usr/bin/env python3
"""Поиск Python 3.11+ в bin/pantheon и bin/pantheon-tick, одна строка вместо трассы на старом python, запуск задач
тем же интерпретатором.

Запуск: python3 -I plugins/pantheon/tests/test_pyfind.py  (код выхода 0 — все прошли)
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN, LIB = os.path.join(ROOT, "bin"), os.path.join(ROOT, "lib")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok else f"  [{detail}]"))


tmp = os.path.realpath(tempfile.mkdtemp(prefix="pyfind-test-"))
atexit.register(shutil.rmtree, tmp, True)
fake = os.path.join(tmp, "fake")
os.makedirs(fake)


def script(name, body):
    p = os.path.join(fake, name)
    with open(p, "w") as fh:
        fh.write("#!/bin/sh\n" + body)
    os.chmod(p, 0o755)


def env_for(**extra):
    home = os.path.join(tmp, "home")
    os.makedirs(home, exist_ok=True)
    e = {"PATH": fake + ":/usr/bin:/bin", "HOME": home, "PANTHEON_HOME": os.path.join(tmp, "pantheon"),
         "PANTHEON_STATE": os.path.join(tmp, "state"), "TMPDIR": tmp, "PANTHEON_PY_DIRS": os.path.join(tmp, "nowhere")}
    e.update(extra)
    return e


def run(cmd, env):
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)


# «python3» из PATH — старый (на -c отвечает как 3.9: код 1); python3.12 — настоящий 3.11+
script("python3", "exit 1\n")
script("python3.12", f'exec "{PY311}" "$@"\n')

r = run([os.path.join(BIN, "pantheon"), "help"], env_for())
check("python3 старый, python3.12 в PATH — команда идёт через найденный", r.returncode == 0 and "Пантеон" in r.stdout,
      (r.returncode, r.stderr[-200:]))
script("python3.12", "exit 1\n")
r = run([os.path.join(BIN, "pantheon"), "help"], env_for(PANTHEON_PYTHON=PY311))
check("PANTHEON_PYTHON важнее PATH", r.returncode == 0 and "Пантеон" in r.stdout, (r.returncode, r.stderr[-200:]))
d = os.path.join(tmp, "brew")
os.makedirs(d)
os.symlink(PY311, os.path.join(d, "python3.13"))
r = run([os.path.join(BIN, "pantheon"), "help"], env_for(PANTHEON_PY_DIRS=os.path.join(tmp, "nope") + ":" + d))
check("нет в PATH — ищет в каталогах PANTHEON_PY_DIRS", r.returncode == 0 and "Пантеон" in r.stdout,
      (r.returncode, r.stderr[-200:]))

# ничего подходящего
r = run([os.path.join(BIN, "pantheon"), "status"], env_for())
check("нет Python 3.11+: понятная строка, код не 0, без трассы",
      r.returncode != 0 and "нужен Python 3.11+" in r.stderr and "Traceback" not in r.stderr + r.stdout
      and "brew install" in r.stderr, (r.returncode, r.stderr[-200:]))

alerts = os.path.join(tmp, "pantheon", "alerts.md")
mark = os.path.join(tmp, "state", "no-python-alert")
r = run([os.path.join(BIN, "pantheon-tick")], env_for())
lines = [x for x in open(alerts, encoding="utf-8").read().splitlines() if "нужен Python 3.11+" in x] \
    if os.path.exists(alerts) else []
check("тик без Python 3.11+: код не 0, строка в alerts.md", r.returncode != 0 and len(lines) == 1, (r.returncode, lines))
run([os.path.join(BIN, "pantheon-tick")], env_for())
lines = [x for x in open(alerts, encoding="utf-8").read().splitlines() if "нужен Python 3.11+" in x]
check("второй тик в те же сутки строку не добавляет", len(lines) == 1, lines)
with open(mark, "w") as fh:
    fh.write("2000-01-01")
run([os.path.join(BIN, "pantheon-tick")], env_for())
lines = [x for x in open(alerts, encoding="utf-8").read().splitlines() if "нужен Python 3.11+" in x]
check("на следующие сутки — снова строка", len(lines) == 2, lines)
check("в alerts.md нет абсолютного пути пользователя", "/Users/" not in open(alerts, encoding="utf-8").read())

# lib/pantheon.py на системном python < 3.11 — одна строка, без трассы
old = "/usr/bin/python3"
if os.path.exists(old) and subprocess.run([old, "-c", "import sys; sys.exit(sys.version_info < (3, 11))"]).returncode:
    r = run([old, "-I", os.path.join(LIB, "pantheon.py"), "status"], env_for())
    check("pantheon.py на 3.9: одна строка «нужен Python 3.11+», код 1, без трассы",
          r.returncode == 1 and len([x for x in r.stderr.splitlines() if "xcrun" not in x]) == 1
          and "нужен Python 3.11+" in r.stderr
          and "Traceback" not in r.stderr, (r.returncode, r.stderr))
    r = run([old, "-I", os.path.join(LIB, "run.py"), "status"], env_for())
    check("загрузчик run.py на 3.9: то же", r.returncode == 1 and "нужен Python 3.11+" in r.stderr
          and "Traceback" not in r.stderr, (r.returncode, r.stderr))
    for s in ("baseline.py", "decision-map-check.py"):
        r = run([old, "-I", os.path.join(ROOT, "scripts", s)], env_for())
        check(f"scripts/{s} на 3.9: одна строка, без трассы",
              r.returncode == 1 and "нужен Python 3.11+" in r.stderr and "Traceback" not in r.stderr, r.stderr[-200:])

# launch(): дочерний run-job — тем же интерпретатором и через загрузчик; run_env передаёт его bin/pantheon
probe = f"""
import json, sys
sys.path.insert(0, {LIB!r})
import pantheon as p
got = []
p.subprocess.Popen = lambda argv, **kw: got.append(list(argv))
p.launch("x", 0)
print(json.dumps({{"argv": got[0], "exe": sys.executable, "env": p.run_env().get("PANTHEON_PYTHON")}}))
"""
r = run([PY311, "-I", "-c", probe], dict(env_for(), PANTHEON_HOME=os.path.join(tmp, "p2")))
try:
    got = json.loads(r.stdout)
except ValueError:
    got = {}
    print(r.stderr[-500:])
check("launch: тот же интерпретатор, run.py из lib, run-job",
      got.get("argv", [""])[0] == got.get("exe") and got["argv"][1] == "-I" and got["argv"][2] == os.path.join(LIB, "run.py")
      and got["argv"][3:] == ["run-job", "x"], got)
check("run_env: PANTHEON_PYTHON = sys.executable", got.get("env") == got.get("exe"), got)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
