#!/usr/bin/env python3
"""metis-0342: окно, запущенное из сессии на старой версии, не берёт pantheon из старого кэша.

Запуск: python3 -I plugins/pantheon/tests/test_path_clean.py  (код выхода 0 — все прошли)
pantheon.py идёт на Python 3.11+, поэтому проверка выполняется подпроцессом (на 3.9 берётся найденный 3.11+).
"""
import json
import os
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CODE = ("import json,os,sys; sys.path.insert(0, sys.argv[1]); import pantheon as P; a=json.loads(sys.argv[2]); "
        "print(json.dumps([P.clean_path(a['path'], a['cur']), P.run_env()['PATH']]))")

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f" {extra}" if not cond else ""))
    if not cond:
        fails.append(name)


with tempfile.TemporaryDirectory(prefix="pathclean-") as home:
    cache = os.path.join(home, ".claude", "plugins", "cache", "agent-kit")
    for plug, vers in (("pantheon", ("0.11.57", "0.11.59", "0.11.61")), ("guard", ("1.2.0", "1.3.0"))):
        for v in vers:
            os.makedirs(os.path.join(cache, plug, v, "bin"))
    old, cur = (os.path.join(cache, "pantheon", "0.11.57", "bin"), os.path.join(cache, "pantheon", "0.11.61", "bin"))
    mid = os.path.join(cache, "pantheon", "0.11.59", "bin")
    g_old, g_new = os.path.join(cache, "guard", "1.2.0", "bin"), os.path.join(cache, "guard", "1.3.0", "bin")
    others = ["/opt/homebrew/bin", os.path.join(home, ".local", "bin"), "/usr/bin", "/bin"]
    path = ":".join([old, others[0], mid, others[1], g_old, cur, g_new, others[2], others[3]])
    env = {"HOME": home, "PATH": "/usr/bin:/bin"}
    r = subprocess.run([PY311, "-I", "-c", CODE, LIB, json.dumps({"path": path, "cur": os.path.join(cache, "pantheon", "0.11.61")})],
                       env=env, capture_output=True, text=True, timeout=60)
    if r.returncode:
        print(r.stderr)
    got = json.loads(r.stdout)[0].split(":")
    check("bin старой версии убран", old not in got and mid not in got, got)
    check("bin текущей версии есть", cur in got, got)
    check("чужой плагин: старая версия убрана, новая осталась", g_old not in got and g_new in got, got)
    check("прочие пути на месте и в прежнем порядке", [d for d in got if d in others] == others, got)
    check("порядок остальных не изменён", got == [others[0], others[1], cur, g_new, others[2], others[3]], got)
    # run_env: окружение процесса с PATH старого кэша
    env["PATH"] = path
    r = subprocess.run([PY311, "-I", "-c", CODE, LIB, json.dumps({"path": "", "cur": cur[:-4]})],
                       env=env, capture_output=True, text=True, timeout=60)
    renv = json.loads(r.stdout)[1].split(":")
    check("run_env не отдаёт окну bin старой версии", old not in renv and mid not in renv, renv)
    check("run_env сохраняет /usr/bin", "/usr/bin" in renv)

sys.exit(1 if fails else 0)
