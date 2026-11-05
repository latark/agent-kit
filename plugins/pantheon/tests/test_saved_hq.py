#!/usr/bin/env python3
"""metis-0577: `pantheon saved --by zeus` из окна штаба. Песочница hq не пускает писать в STATE/maintenance и STATE/plugins,
а пишет только в STATE/hq-rw/<папки>: метка ложится в STATE/hq-rw/saved, команда — код 0; её читают restart --status и
saved_sid (id сессии для restart --go). Другое окно (не zeus*) в hq-rw/saved не пишет: ему метка нужна в maintenance.

Запуск: python3.14 -I plugins/pantheon/tests/test_saved_hq.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIB, "run.py")
T0 = 1_792_000_000
SID = "5a5a5a5a-1111-4111-8111-111111111111"
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="savedhq-"))
    env = {"PATH": os.environ["PATH"], "HOME": os.path.join(tmp, "home"), "PANTHEON_HOME": os.path.join(tmp, "home", "ai", "pantheon"),
           "PANTHEON_STATE": os.path.join(tmp, "state"), "PANTHEON_NOW": str(T0), "PANTHEON_NO_NOTIFY": "1", "TMPDIR": tmp}
    os.makedirs(env["PANTHEON_HOME"])
    os.makedirs(os.path.join(env["PANTHEON_STATE"], "hq-rw", "saved"))
    return tmp, env


def run(env, *a, **extra):
    return subprocess.run([sys.executable, "-I", RUN_PY, *a], env={**env, **extra}, capture_output=True, text=True, timeout=60)


def maint(env, sessions):
    json.dump({"id": "2026-11-06T00:00:00", "since": T0, "expires": T0 + 7200, "reason": "t", "by": "test", "sessions": sessions},
              open(os.path.join(env["PANTHEON_STATE"], "maintenance.json"), "w"))


tmp, env = make()
st = env["PANTHEON_STATE"]
own = {"PANTHEON_SESSION": "zeus", "CLAUDE_CODE_SESSION_ID": SID}
mark = os.path.join(st, "hq-rw", "saved", "zeus.json")
try:
    if os.geteuid() == 0:
        print("пропущено: root обходит права")
        sys.exit(0)
    # техперезапуск: STATE/maintenance закрыта (как в песочнице), hq-rw/saved открыта
    maint(env, ["zeus", "dev-x"])
    os.makedirs(os.path.join(st, "maintenance"))
    os.chmod(os.path.join(st, "maintenance"), 0o500)
    r = run(env, "saved", "--by", "zeus", "--state", "STATUS.md", **own)
    rec = json.load(open(mark)) if os.path.exists(mark) else {}
    check("saved zeus: код 0, метка в hq-rw/saved с id сессии, без трассировки",
          r.returncode == 0 and rec.get("sessionId") == SID and "Traceback" not in r.stderr
          and "hq-rw/saved/zeus.json" in r.stderr, (r, rec))
    check("saved zeus: в maintenance ничего не появилось", not os.path.exists(os.path.join(st, "maintenance", "zeus.json")))
    r = run(env, "restart", "--status", **own)
    check("restart --status видит метку из hq-rw/saved", "zeus: сохранилась" in r.stdout, r)
    r = run(env, "saved", "--by", "zeus", "--state", "NEW", **own)
    check("повторный saved перезаписывает метку", r.returncode == 0 and json.load(open(mark)).get("state") == "NEW", r)
    code = f"import sys;sys.path.insert(0,{LIB!r});import pantheon as P;print(P.watch_mod().saved_sid('zeus'))"
    r = subprocess.run([sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True)
    check("saved_sid берёт id из hq-rw/saved", r.stdout.strip() == SID, r)
    r = run(env, "saved", "--by", "dev-x", "--state", "S", PANTHEON_SESSION="dev-x", CLAUDE_CODE_SESSION_ID=SID)
    check("saved dev-x: код 1, в hq-rw/saved не пишет",
          r.returncode == 1 and not os.path.exists(os.path.join(st, "hq-rw", "saved", "dev-x.json")), r)
    # ссылка на месте метки: пишем не через неё
    os.remove(mark)
    victim = os.path.join(tmp, "victim")
    open(victim, "w").write("keep\n")
    os.symlink(victim, mark)
    r = run(env, "saved", "--by", "zeus", "--state", "S", **own)
    check("ссылка на месте метки: цель не тронута, код 0", r.returncode == 0 and open(victim).read() == "keep\n", r)
    os.remove(mark)
    # restart --done снимает метку
    r = run(env, "saved", "--by", "zeus", "--state", "S", **own)
    check("метка есть до restart --done", os.path.exists(mark), r)
    os.chmod(os.path.join(st, "maintenance"), 0o700)
    run(env, "restart", "--done")
    check("после restart --done метки в hq-rw/saved нет", not os.listdir(os.path.join(st, "hq-rw", "saved")))
finally:
    for d, _, _ in os.walk(tmp):
        os.chmod(d, 0o700)
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
