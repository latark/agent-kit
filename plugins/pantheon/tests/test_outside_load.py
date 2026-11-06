#!/usr/bin/env python3
"""Очередь outside под нагрузкой (metis-0901, lib/outside.py: wait_load, overload_files, wait_proc hold, result_code).

Запуск: python3 -I plugins/pantheon/tests/test_outside_load.py  (код выхода 0 — все прошли)
Проверяет: полный набор при load выше порога не стартует — итог queued с причиной «жду спада нагрузки (load N)», команда
не запущена, после спада идёт; красный только из-за таймаутов файлов под нагрузкой — один повтор сам, второй такой же —
итог «таймаут под нагрузкой» (overload, код 75), не красный, не в журнал full.jsonl; другой провал или малый load —
обычный красный без повтора; ожидание места heavy не входит в TEST_TIMEOUT (wait_proc hold и прогон с heavy-заглушкой).
sandbox-exec и heavy подменены заглушками.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311  # noqa: E402,F401  pantheon.py — только на Python 3.11+

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="outside-load-"))
tempfile.tempdir = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIBDIR = os.path.join(os.path.dirname(HERE), "lib")
HOME = os.path.join(_ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE"))]:
    os.environ.pop(k)
os.environ.update({"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1", "TMPDIR": _ROOT})
sys.path.insert(0, LIBDIR)
import pantheon as P  # noqa: E402
O = P.outside_mod()

FAILS, TOTAL = [], [0]


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{str(extra)[-800:]}]"))
    if not cond:
        FAILS.append(name)


REC = os.path.join(_ROOT, "calls.jsonl")
FAKE = os.path.join(_ROOT, "fake-sandbox-exec")
with open(FAKE, "w") as fh:
    fh.write(f"#!{sys.executable}\nimport json, os, sys\ncmd = sys.argv[3:]\n"
             f"with open({REC!r}, 'a') as fh:\n    fh.write(json.dumps(cmd) + '\\n')\nos.execvp(cmd[0], cmd)\n")
os.chmod(FAKE, 0o755)
O.SANDBOX_EXEC = FAKE
O.HEAVY = None


def ncalls():
    try:
        with open(REC) as fh:
            return len(fh.read().splitlines())
    except OSError:
        return 0


def git(*args):
    r = subprocess.run(["git", "-C", RK, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        *args], capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


RK = os.path.join(HOME, "projects", "lk")
os.makedirs(RK)
git("init", "-q", "-b", "feat")
git("remote", "add", "origin", "git@github.com:latark/lk.git")
MODE = os.path.join(_ROOT, "mode.json")   # t.py читает отсюда, что напечатать в этом запуске
TIMEOUTS = ("run-tests: 2 файлов\nFAIL lk/test_a.py · 720.0 с · проверок 3 · таймаут\n"
            "FAIL lk/test_b.py · 1200.0 с · проверок 1 · таймаут\n"
            "итого: файлов 2, ok 0, FAIL 2; проверок 4; 1200 с, воркеров 2\n")
MIXED = ("run-tests: 2 файлов\nFAIL lk/test_a.py · 720.0 с · проверок 3 · таймаут\n"
         "FAIL lk/test_b.py · 1.0 с · проверок 1 · код 1\n"
         "итого: файлов 2, ok 0, FAIL 2; проверок 4; 720 с, воркеров 2\n")
GREENOUT = "run-tests: 2 файлов\nok   lk/test_a.py · 1 с · проверок 3\nok   lk/test_b.py · 1 с · проверок 1\n" \
           "итого: файлов 2, ok 2, FAIL 0; проверок 4; 1 с, воркеров 2\n"
T_PY = ("import json, sys\nm = json.load(open(%r))\nk = m['runs'].pop(0) if len(m['runs']) > 1 else m['runs'][0]\n"
        "json.dump(m, open(%r, 'w'))\nout = m['out'][k]\nsys.stdout.write(out)\nsys.exit(0 if k == 'green' else 1)\n"
        % (MODE, MODE))


def set_mode(runs):
    with open(MODE, "w") as fh:
        json.dump({"runs": runs, "out": {"green": GREENOUT, "timeouts": TIMEOUTS, "mixed": MIXED}}, fh)


def commit(text, msg):
    with open(os.path.join(RK, "t.py"), "w") as fh:
        fh.write(text)
    with open(os.path.join(RK, ".pantheon-verify"), "w") as fh:
        fh.write("heavy python3 t.py\n")
    git("add", "-A")
    git("commit", "-q", "-m", msg)
    return git("rev-parse", "HEAD")


P.merge_mod().FULL_TESTS["lk"] = "heavy python3 t.py"
N = [0]
LOAD = [1.0]
O.load_state = lambda: (LOAD[0], 10.0)
O.LOAD_POLL = 0.2
O.SWEEP_EVERY = 0.1
QD = os.path.join(_ROOT, "q")
os.makedirs(QD)


def run(**kw):
    N[0] += 1
    rid = f"20261106-{N[0]:06d}-abcdef"
    return rid, O.run_test(rid, RK, None, "metis-l", QD, [RK], **kw)


def reds():
    return [e for e in O.read_full() if e.get("code") != 0]


# --- 1. полный набор под нагрузкой не стартует ---------------------------------------------------------------------
commit(T_PY, "c1")
set_mode(["green"])
LOAD[0] = 50.0
out = {}
n0 = ncalls()
N[0] += 1
RID1 = f"20261106-{N[0]:06d}-abcdef"
th = threading.Thread(target=lambda: out.update(O.run_test(RID1, RK, None, "metis-l", QD, [RK])))
th.start()
seen = None
for _ in range(60):
    seen = O.load_result(QD, RID1) or {}
    if seen.get("state") == "queued" and "жду спада нагрузки" in seen.get("why", ""):
        break
    time.sleep(0.1)
check("нагрузка: load выше порога — итог queued, причина «жду спада нагрузки (load N)», порог в тексте",
      seen.get("state") == "queued" and "жду спада нагрузки (load 50, порог 10)" in seen.get("why", ""), seen)
time.sleep(0.5)
check("нагрузка: пока load высокий, команда тестов не запущена", ncalls() == n0 and th.is_alive(), (ncalls(), n0))
LOAD[0] = 1.0
th.join(20)
check("нагрузка: после спада прогон идёт и кончается зелёным с записью",
      not th.is_alive() and ncalls() == n0 + 1 and out.get("state") == "done" and out.get("code") == 0
      and out.get("record"), out)
check("нагрузка: после ожидания итог снова running→done без «жду»", "жду" not in out.get("why", ""), out)

set_mode(["green"])
O.LOAD_WAIT_MAX = 0.5
LOAD[0] = 50.0
n0 = ncalls()
t0 = time.monotonic()
commit(T_PY + "# c2\n", "c2")
rid, res = run()
check("нагрузка: ждать спада не дольше LOAD_WAIT_MAX — потом идёт как есть",
      res.get("state") == "done" and ncalls() == n0 + 1 and time.monotonic() - t0 < 10, (res, ncalls() - n0))
O.LOAD_WAIT_MAX = 3600

# «стоп» в ожидании спада снимает заявку без прогона
set_mode(["green"])
commit(T_PY + "# c3\n", "c3")
n0 = ncalls()
N[0] += 1
RID3 = f"20261106-{N[0]:06d}-abcdef"
out3 = {}
th = threading.Thread(target=lambda: out3.update(O.run_test(RID3, RK, None, "metis-l", QD, [RK])))
th.start()
for _ in range(60):
    s3 = O.load_result(QD, RID3) or {}
    if s3.get("state") == "queued":
        break
    time.sleep(0.1)
STOP3 = os.path.join(O.root("queue"), RID3 + ".stop")   # очередь терминала владельца — своя для любой заявки
os.makedirs(os.path.dirname(STOP3), exist_ok=True)
with open(STOP3, "w") as fh:
    fh.write("")
th.join(20)
if th.is_alive():   # не снялась — отпустить, чтобы поток не жил в следующих случаях
    LOAD[0] = 1.0
    th.join(20)
    LOAD[0] = 50.0
check("нагрузка: «стоп» в ожидании — stopped, команда не запускалась",
      not th.is_alive() and out3.get("state") == "stopped" and ncalls() == n0, (out3, ncalls() - n0))
if os.path.exists(STOP3):
    os.remove(STOP3)

# --- 2. таймаут под нагрузкой: один повтор сам, не красный --------------------------------------------------------
O.wait_load = lambda *a, **k: None   # ожидание спада проверено выше; здесь нагрузка высока только при разборе итога
LOAD[0] = 50.0
commit(T_PY + "# c4\n", "c4")
set_mode(["timeouts", "green"])
n0 = ncalls()
rid, res = run()
check("повтор: таймауты под нагрузкой, второй прогон зелёный — повтор один, сам, итог зелёный с записью",
      ncalls() == n0 + 2 and res.get("state") == "done" and res.get("code") == 0 and res.get("record")
      and not res.get("overload") and "повтор после «таймаут под нагрузкой»" in res.get("note", ""), (res, ncalls() - n0))

commit(T_PY + "# c5\n", "c5")
set_mode(["timeouts"])
n0 = ncalls()
nfull = len(O.read_full())
rid, res = run()
check("повтор: оба прогона упали по таймаутам — ровно два запуска, итог «таймаут под нагрузкой», overload",
      ncalls() == n0 + 2 and res.get("state") == "done" and res.get("overload") is True
      and "таймаут под нагрузкой" in res.get("why", "") and not res.get("record"), (res, ncalls() - n0))
check("повтор: итог overload — код 75 («повторить»), а не 1", O.result_code(res) == 75, O.result_code(res))
check("повтор: итог overload не пишется красной строкой в full.jsonl", len(O.read_full()) == nfull, O.read_full()[nfull:])
check("повтор: красный прогон без overload по-прежнему код 1",
      O.result_code({"state": "done", "code": 1, "why": ""}) == 1 and O.result_code({"state": "done", "code": 0}) == 0)

commit(T_PY + "# c6\n", "c6")
set_mode(["mixed", "green"])
n0 = ncalls()
rid, res = run()
check("повтор: упал не только таймаут (код 1 у второго файла) — обычный красный, без повтора",
      ncalls() == n0 + 1 and res.get("code") == 1 and not res.get("overload") and O.result_code(res) == 1,
      (res, ncalls() - n0))

LOAD[0] = 1.0
commit(T_PY + "# c7\n", "c7")
set_mode(["timeouts", "green"])
n0 = ncalls()
rid, res = run()
check("повтор: таймауты при малой нагрузке — это красный, без повтора",
      ncalls() == n0 + 1 and res.get("code") == 1 and not res.get("overload") and O.result_code(res) == 1,
      (res, ncalls() - n0))

# --- 3. ожидание места heavy не входит в TEST_TIMEOUT --------------------------------------------------------------
t0 = time.monotonic()
p = subprocess.Popen(["sleep", "2.5"])
code = O.wait_proc(p, 1, hold=lambda: time.monotonic() < t0 + 2)
check("heavy: wait_proc — пока hold True, срок не идёт (sleep 2.5 при сроке 1 с и ожидании 2 с)", code == 0, code)
p = subprocess.Popen(["sleep", "2.5"])
try:
    O.wait_proc(p, 1)
    expired = False
except subprocess.TimeoutExpired:
    expired = True
p.kill()
p.wait()
check("heavy: тот же прогон без hold — срок вышел", expired)
O.HEAVY_WAIT_MAX = 1
p = subprocess.Popen(["sleep", "4"])
try:
    O.wait_proc(p, 1, hold=lambda: True)
    expired = False
except subprocess.TimeoutExpired:
    expired = True
p.kill()
p.wait()
O.HEAVY_WAIT_MAX = 3600
check("heavy: ожидание места, не входящее в срок, ограничено HEAVY_WAIT_MAX", expired)

if O.ps_table():
    HV = os.path.join(_ROOT, "fake-heavy")
    with open(HV, "w") as fh:   # ждёт «место» без потомков 3.5 с, затем запускает команду потомком, как настоящий heavy
        fh.write(f"#!{sys.executable}\nimport subprocess, sys, time\ntime.sleep(3.5)\n"
                 "sys.exit(subprocess.call(sys.argv[1:]))\n")
    os.chmod(HV, 0o755)
    O.HEAVY = HV
    O.TEST_TIMEOUT = 2
    O.SWEEP_EVERY = 0.2
    commit(T_PY + "# c8\n", "c8")
    set_mode(["green"])
    LOAD[0] = 1.0
    rid, res = run()
    check("heavy: прогон ждёт место 3,5 с при TEST_TIMEOUT 2 с — не остановлен, зелёный",
          res.get("state") == "done" and res.get("code") == 0 and "дольше" not in res.get("why", ""), res)
    O.HEAVY = None
    O.TEST_TIMEOUT = 7200
else:
    print("пропущено: ps_table пуст — нет libproc и ps")

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
