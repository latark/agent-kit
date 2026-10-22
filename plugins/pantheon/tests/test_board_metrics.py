#!/usr/bin/env python3
"""Проход доски не ждёт учёт по задачам (metis-0320): учёт — отдельный процесс, не чаще раза в 30 минут, не при
занятой блокировке metrics, PANTHEON_METRICS=0 выключает.

Запуск: python3 -I plugins/pantheon/tests/test_board_metrics.py  (код выхода 0 — все прошли)
"""
import atexit
import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="bmetrics-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

CLI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


tmp = os.path.realpath(tempfile.mkdtemp(prefix="bmetrics-test-"))
home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
os.makedirs(os.path.join(home, "directions/metis-pantheon/tasks"))
os.makedirs(os.path.join(home, "inbox/tasks"))
os.makedirs(view)
with open(os.path.join(home, "schedule.toml"), "w") as fh:
    fh.write('primary_host = "mac-a"\n')
log = os.path.join(tmp, "runs.log")
stamp_p = os.path.join(state, "metrics-spawn")
lock_p = os.path.join(state, "locks", "metrics.lock")
ENV = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
       "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
       "PANTHEON_FAKE_IDLE": "0", "PANTHEON_METRICS_TEST_SLEEP": "3", "PANTHEON_METRICS_TEST_LOG": log}


def board(**extra):
    env = {k: v for k, v in dict(ENV, **extra).items() if v is not None}
    t0 = time.time()
    p = subprocess.run([PY311, "-I", CLI, "board"], env=env, capture_output=True, text=True, timeout=60)
    return p, time.time() - t0


def runs():
    try:
        with open(log) as fh:
            return len(fh.read().split())
    except OSError:
        return 0


def wait_runs(n, limit=15):
    end = time.time() + limit
    while time.time() < end and runs() < n:
        time.sleep(0.2)
    return runs()


# metis-0365: «не ждёт учёта» — по записи учёта сразу после выхода board, а не по секундомеру: «быстрее секунды»
# краснело под нагрузкой автоустановки (5,4 с на запуск CLI), хотя учёт ещё спал. Board, ждущий учёт (3 с), выходит
# уже с его записью — красное при любой нагрузке.
# Граница проверки (ревью #107, metis-0368): ловится board, который ждёт учёт до конца (3 с сна и запись). Board,
# который ждёт учёт с таймаутом короче сна (wait(timeout=2) и выход), вернётся без записи и пройдёт — его отличает
# только секундомер, а разница в 2 с тонет в шуме под нагрузкой (5,4 с на один запуск CLI при load avg 13,5).
# Сравнение с прогоном PANTHEON_METRICS=0 под той же нагрузкой не взято: красное от шума держало бы автоустановку.
# Ожидание с таймаутом — правка кода запуска учёта; её ловит ревью, а не этот тест.
p, dt = board()
r0 = runs()
check("board с учётом на 3 с возвращается, не дожидаясь учёта", p.returncode == 0 and r0 == 0,
      (p.returncode, r0, round(dt, 1), p.stderr[-300:]))
check("учёт запущен отдельным процессом: board вернулся, а учёт ещё спит", r0 == 0, r0)
check("отметка запуска записана", os.path.exists(stamp_p))
check("фоновый учёт дошёл до конца (одна запись)", wait_runs(1) == 1, runs())

p, dt = board()
time.sleep(4.5)
check("второй board в пределах 30 минут учёт не запускает", p.returncode == 0 and runs() == 1, runs())

os.remove(stamp_p)
fh = open(lock_p, "a")
fcntl.flock(fh, fcntl.LOCK_EX)
p, dt = board()
time.sleep(4.5)
check("блокировка metrics занята: учёт не запускается и отметка не ставится",
      p.returncode == 0 and runs() == 1 and not os.path.exists(stamp_p), (runs(), os.path.exists(stamp_p)))
fcntl.flock(fh, fcntl.LOCK_UN)
fh.close()

p, dt = board(PANTHEON_METRICS="0")
time.sleep(4.5)
check("PANTHEON_METRICS=0: учёт не запускается", runs() == 1 and not os.path.exists(stamp_p), runs())

p, dt = board()
r0 = runs()  # граница та же, что у первой проверки: ожидание учёта с таймаутом короче 3 с здесь не видно
check("блокировка свободна, отметки нет: board снова не ждёт учёта", p.returncode == 0 and r0 == 1, (r0, round(dt, 1)))
check("и учёт запущен второй раз", wait_runs(2) == 2, runs())

old = time.time() - 31 * 60
os.utime(stamp_p, (old, old))
p, dt = board()
check("отметка старше 30 минут: учёт запускается снова", wait_runs(3) == 3, runs())

# metrics run при занятой блокировке metrics прохода не делает (защита, когда учёт идёт у двух процессов сразу)
n0 = runs()
fh = open(lock_p, "a")
fcntl.flock(fh, fcntl.LOCK_EX)
q = subprocess.run([PY311, "-I", CLI, "metrics", "run"], env=dict(ENV, PANTHEON_METRICS_TEST_SLEEP="0"),
                   capture_output=True, text=True, timeout=60)
fcntl.flock(fh, fcntl.LOCK_UN)
fh.close()
check("metrics run при занятой блокировке: проходов 0, код 0", q.returncode == 0 and runs() == n0,
      (q.returncode, runs() - n0, q.stderr[-300:]))

# metrics-run.log обрезается как журналы задач: выше 400 КБ остаётся хвост 200 КБ
rlog = os.path.join(state, "metrics-run.log")
with open(rlog, "w") as fh:
    fh.write("x" * 450_000 + "ХВОСТ\n")
os.remove(stamp_p)
p, dt = board()
sz = os.path.getsize(rlog)
check("metrics-run.log выше 400 КБ обрезан до хвоста", p.returncode == 0 and sz <= 200_100, sz)
check("в обрезанном логе остался конец", open(rlog, encoding="utf-8").read().endswith("ХВОСТ\n"))
wait_runs(n0 + 1)

print(f"{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
