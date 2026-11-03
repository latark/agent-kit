#!/usr/bin/env python3
"""Время прохода доски (metis-0709): строка «доска-время» с частями; занятая блокировка notify (как зависшее
уведомление или gh у соседнего процесса) не держит проход дольше бюджета — доска выходит с кодом 0 и без уведомлений;
SIGTERM (таймаут задания) не теряет строку времени.

Запуск: python3 -I plugins/pantheon/tests/test_board_time.py  (код выхода 0 — все прошли)
"""
import atexit
import fcntl
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="btime-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(CLI), "run.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


tmp = os.path.realpath(tempfile.mkdtemp(prefix="btime-test-"))
home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
os.makedirs(os.path.join(home, "directions/metis-pantheon/tasks"))
os.makedirs(os.path.join(home, "inbox/tasks"))
os.makedirs(view)
os.makedirs(os.path.join(state, "locks"))
with open(os.path.join(home, "schedule.toml"), "w") as fh:
    fh.write('primary_host = "mac-a"\n')
ENV = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
       "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
       "PANTHEON_FAKE_IDLE": "0", "PANTHEON_METRICS": "0"}
argv = [PY311, "-I", RUN_PY, "board"]


def line_of(out):
    ls = [x for x in out.splitlines() if x.startswith("доска-время:")]
    return ls[0] if len(ls) == 1 else None


# 1. обычный проход: одна строка с частями
p = subprocess.run(argv, env=ENV, capture_output=True, text=True, timeout=60)
ln = line_of(p.stdout)
check("проход: код 0 и одна строка «доска-время»", p.returncode == 0 and ln is not None,
      (p.returncode, p.stdout[-300:], p.stderr[-300:]))
check("в строке есть все части и итого",
      ln and all(w in ln for w in ("реестр ", "статусы ", "блокировка-notify ", "карточки ", "сводка ", "итого ")), ln)

# 2. блокировку notify держит чужой процесс: проход ждёт не дольше BOARD_NOTIFY_WAIT, кода 124 нет
src = open(CLI, encoding="utf-8").read()
wait = float(re.search(r"BOARD_NOTIFY_WAIT = ([0-9.]+)", src).group(1))
fh = open(os.path.join(state, "locks", "notify.lock"), "a")
fcntl.flock(fh, fcntl.LOCK_EX)
t0 = time.time()
p = subprocess.run(argv, env=dict(ENV, PANTHEON_BOARD_BUDGET="3"), capture_output=True, text=True, timeout=60)
dt = time.time() - t0
ln = line_of(p.stdout)
check("блокировка notify занята: код 0 за бюджет (3 с), а не за предел задания",
      p.returncode == 0 and dt < 3 + 15, (p.returncode, round(dt, 1), p.stderr[-300:]))
check("блокировка notify занята: строка времени называет пропуск уведомлений, карточки собраны",
      ln and "уведомления" in ln and "карточки " in ln and os.path.exists(os.path.join(state, "board.json")),
      (ln, os.listdir(state)))
check("бюджет вышел: сводка board-auto пропущена", ln and "сводка board-auto" in ln, ln)
check("ожидание замка ограничено бюджетом, а не BOARD_NOTIFY_WAIT", dt < wait, (dt, wait))
fcntl.flock(fh, fcntl.LOCK_UN)
fh.close()

# 3. SIGTERM в ожидании замка: строка времени всё равно есть, с пометкой «прервано в ...»
fh = open(os.path.join(state, "locks", "notify.lock"), "a")
fcntl.flock(fh, fcntl.LOCK_EX)
q = subprocess.Popen(argv, env=dict(ENV, PANTHEON_BOARD_BUDGET="60"), stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True)
time.sleep(4)
q.send_signal(signal.SIGTERM)
out, err = q.communicate(timeout=30)
ln = line_of(out)
check("SIGTERM: строка времени с «прервано в «блокировка-notify»»", ln and "прервано в «блокировка-notify»" in ln,
      (ln, out[-200:], err[-200:]))
fcntl.flock(fh, fcntl.LOCK_UN)
fh.close()

print(f"{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
