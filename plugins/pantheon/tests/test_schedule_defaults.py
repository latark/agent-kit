#!/usr/bin/env python3
"""Задания расписания из плагина (metis-0833): reap --auto виден в `pantheon jobs` без правки schedule.toml;
schedule.toml владельца только переопределяет (выключить, реже), свои задания остаются.

Запуск: python3 -I plugins/pantheon/tests/test_schedule_defaults.py  (код выхода 0 — все прошли)
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

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="sched-def-"))
atexit.register(shutil.rmtree, ROOT, True)
PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


home, pan, state = (os.path.join(ROOT, d) for d in ("home", "pantheon", "state"))
for d in (home, pan, state):
    os.makedirs(d)


def env(**extra):
    return {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pan, "PANTHEON_STATE": state,
            "PANTHEON_NOTIFY_LOG": os.path.join(ROOT, "notify.log"), **extra}


def schedule(owner_text, **extra):
    open(os.path.join(pan, "schedule.toml"), "w").write(owner_text)
    code = ("import json, sys; sys.path.insert(0, %r); import pantheon as p; s = p.load_schedule(); "
            "print(json.dumps(s['job']))" % LIB)
    r = subprocess.run([PY311, "-I", "-c", code], env=env(**extra), capture_output=True, text=True, timeout=60)
    try:
        return {j["name"]: j for j in json.loads(r.stdout.strip().splitlines()[-1])}
    except (ValueError, IndexError):
        print(r.stdout, r.stderr)
        return {}


BASE = 'primary_host = "mac-a"\n'

jobs = schedule(BASE)
reap = jobs.get("reap", {})
check("пустой schedule.toml: reap --auto от плагина есть",
      reap.get("command") == "pantheon reap --auto" and reap.get("every") == 30 and reap.get("enabled") is not False, jobs)

shown = subprocess.run([os.path.join(PLUGIN, "bin", "pantheon"), "jobs"], env=env(),
                       capture_output=True, text=True, timeout=60)
check("`pantheon jobs` показывает reap без правки файла", shown.returncode == 0 and "reap" in shown.stdout,
      (shown.returncode, shown.stdout[-300:], shown.stderr[-300:]))

jobs = schedule(BASE + '[[job]]\nname = "reap"\nenabled = false\n')
check("владелец выключает: enabled = false, остальные поля остались от плагина",
      jobs["reap"].get("enabled") is False and jobs["reap"].get("command") == "pantheon reap --auto", jobs)

jobs = schedule(BASE + '[[job]]\nname = "reap"\nevery = 60\n')
check("владелец меняет every: 60, команда от плагина", jobs["reap"]["every"] == 60
      and jobs["reap"]["command"] == "pantheon reap --auto", jobs)

jobs = schedule(BASE + '[[job]]\nname = "board"\ncommand = "pantheon board"\nevery = "tick"\n')
check("своё задание владельца остаётся рядом с умолчаниями", "board" in jobs and "reap" in jobs, list(jobs))

jobs = schedule(BASE, PANTHEON_SCHEDULE_DEFAULTS=os.path.join(ROOT, "нет-такого.toml"))
check("нет файла умолчаний — расписание читается, без reap", jobs == {} , jobs)

bad = os.path.join(ROOT, "bad.toml")
open(bad, "w").write("[[job\nэто не toml")
jobs = schedule(BASE + '[[job]]\nname = "board"\ncommand = "pantheon board"\n', PANTHEON_SCHEDULE_DEFAULTS=bad)
check("битый файл умолчаний не роняет расписание владельца", list(jobs) == ["board"], jobs)

# файл умолчаний в самом плагине: разрешённая команда
code = ("import sys; sys.path.insert(0, %r); import pantheon as p; "
        "print([p.parse_command(j.get('command')) is not None for j in p.default_jobs()])" % LIB)
r = subprocess.run([PY311, "-I", "-c", code], env=env(), capture_output=True, text=True, timeout=60)
check("все задания schedule-defaults.toml проходят parse_command", r.stdout.strip() == "[True]", (r.stdout, r.stderr))

# порядок (metis-0993): нетронутые умолчания первыми, потом задания владельца в его порядке; одноимённое стоит у владельца
two = os.path.join(ROOT, "два.toml")
open(two, "w").write('[[job]]\nname = "d1"\ncommand = "pantheon reap --auto"\nevery = 30\n\n'
                     '[[job]]\nname = "d2"\ncommand = "pantheon reap --auto"\nevery = 30\n')
jobs = schedule(BASE + '[[job]]\nname = "x"\ncommand = "pantheon board"\n[[job]]\nname = "d1"\nevery = 5\n'
                '[[job]]\nname = "y"\ncommand = "pantheon board"\n', PANTHEON_SCHEDULE_DEFAULTS=two)
check("порядок: d2 (умолчание), затем x, d1, y как у владельца; d1 с полями умолчания и every = 5",
      list(jobs) == ["d2", "x", "d1", "y"] and jobs["d1"]["every"] == 5 and jobs["d1"]["command"] == "pantheon reap --auto", list(jobs))
jobs = schedule(BASE + '[[job]]\nname = "z"\ncommand = "pantheon board"\n[[job]]\nname = "a"\ncommand = "pantheon board"\n',
                PANTHEON_SCHEDULE_DEFAULTS=two)
check("порядок: чужие задания владельца идут как записаны (z, a), после умолчаний", list(jobs) == ["d1", "d2", "z", "a"], list(jobs))

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
