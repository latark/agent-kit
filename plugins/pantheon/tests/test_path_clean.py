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


CODE2 = ("import json,os,sys; sys.path.insert(0, sys.argv[1]); import pantheon as P; a=json.loads(sys.argv[2]); "
         "P.PLUGIN=a['plugin']; print(json.dumps(P.run_env()['PATH']))")


def run(code_args, env, code=CODE):
    r = subprocess.run([PY311, "-I", "-c", code, LIB, json.dumps(code_args)], env=env, capture_output=True, text=True, timeout=60)
    if r.returncode:
        print(r.stderr)
    return json.loads(r.stdout)


with tempfile.TemporaryDirectory(prefix="pathclean-") as home_raw:
    home = os.path.realpath(home_raw)  # /tmp → /private/tmp на macOS: realpath в коде иначе не совпадёт с путями теста
    cache = os.path.join(home, ".claude", "plugins", "cache", "agent-kit")
    for plug, vers in (("pantheon", ("0.11.57", "0.11.59", "0.11.61")),
                       ("guard", ("1.2.0", "1.3.0")), ("tools", ("0.5.9", "0.5.10")), ("rc", ("1.2.0", "1.2.0-rc1"))):
        for v in vers:
            os.makedirs(os.path.join(cache, plug, v, "bin"))
    b = lambda plug, v: os.path.join(cache, plug, v, "bin")
    # установленная версия: CURRENT -> 0.11.59; запущенная (PLUGIN) старее, 0.11.61 лежит в кэше, но не установлена
    os.makedirs(os.path.join(home, ".local", "share", "pantheon"))
    os.symlink(os.path.join(cache, "pantheon", "0.11.59"), os.path.join(home, ".local", "share", "pantheon", "current"))
    old, inst, newer = b("pantheon", "0.11.57"), b("pantheon", "0.11.59"), b("pantheon", "0.11.61")
    g_old, g_new = b("guard", "1.2.0"), b("guard", "1.3.0")
    t_old, t_new = b("tools", "0.5.9"), b("tools", "0.5.10")
    r_rel, r_rc = b("rc", "1.2.0"), b("rc", "1.2.0-rc1")
    others = ["/opt/homebrew/bin", os.path.join(home, ".local", "bin"), "/usr/bin", "/bin"]
    path = ":".join([old, others[0], inst, others[1], g_old, newer, g_new, t_old, t_new, r_rel, r_rc, others[2], others[3]])
    env = {"HOME": home, "PATH": "/usr/bin:/bin"}
    got = run({"path": path, "cur": ""}, env)[0].split(":")
    check("свой плагин: остался только bin установленной версии", inst in got and not {old, newer} & set(got), got)
    check("чужой плагин: старая версия убрана, новая осталась", g_old not in got and g_new in got, got)
    check("версии сравниваются числами: 0.5.9 убран, 0.5.10 остался", t_old not in got and t_new in got, got)
    check("пререлиз старше выпуска: rc1 убран, 1.2.0 остался", r_rc not in got and r_rel in got, got)
    check("прочие пути на месте и в прежнем порядке", [d for d in got if d in others] == others, got)
    check("порядок остальных не изменён", got == [others[0], inst, others[1], g_new, t_new, r_rel, others[2], others[3]], got)
    # run_env: запущена старая версия (PLUGIN = 0.11.57), установлена 0.11.59, в PATH окна bin старого кэша
    env["PATH"] = ":".join([old, "/usr/bin", newer])
    renv = run({"plugin": os.path.join(cache, "pantheon", "0.11.57")}, env, CODE2).split(":")
    check("run_env: первым bin установленной версии", renv[0] == inst, renv)
    check("run_env: bin запущенной старой версии нет", old not in renv, renv)
    check("run_env: bin неустановленной новой версии нет", newer not in renv, renv)
    check("run_env сохраняет /usr/bin", "/usr/bin" in renv)
    # без ссылки CURRENT эталон — запущенная версия
    os.unlink(os.path.join(home, ".local", "share", "pantheon", "current"))
    renv = run({"plugin": os.path.join(cache, "pantheon", "0.11.61")}, env, CODE2).split(":")
    check("без CURRENT эталон — PLUGIN", renv[0] == newer and old not in renv, renv)

sys.exit(1 if fails else 0)
