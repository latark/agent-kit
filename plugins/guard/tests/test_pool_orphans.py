#!/usr/bin/env python3
"""Воркеры пула test_shell_diff гаснут вместе с родителем (metis-0618, _orphan_pool.py).

Запуск: python3 -I plugins/guard/tests/test_pool_orphans.py   (код выхода 0 — все прошли)
Родитель — отдельный процесс: поднимает пул process_pool, ждёт, пока воркеры отработают задачи, пишет их pid и pid
resource_tracker и выходит os._exit(0) без shutdown — как убитый таймаутом прогон. Тест ждёт до DEADLINE с, что ни
одного из них не осталось. Не дождался — гасит их сам SIGKILL (свои процессы, а не чужие), чтобы не оставить сирот.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEADLINE = 10.0
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


PARENT = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
from multiprocessing import resource_tracker
from _orphan_pool import process_pool

def main():
    pool = process_pool(3)
    pids = {f.result() for f in [pool.submit(os.getpid) for _ in range(24)]}
    resource_tracker.ensure_running()
    out = {"workers": sorted(set(pool._processes) | pids), "tracker": resource_tracker._resource_tracker._pid}
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out))
    os._exit(0)  # без shutdown пула и atexit — как убитый родитель

if __name__ == "__main__":
    main()
"""


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sem_ok():
    """Песочница окна роли не даёт семафоры: ProcessPoolExecutor там падает на sysconf (metis-0666)."""
    try:
        os.sysconf("SC_SEM_NSEMS_MAX")
        return True
    except (PermissionError, ValueError, OSError):
        return False


def test_workers_die_with_parent():
    root = os.path.realpath(tempfile.mkdtemp(prefix="pool-orphans-"))
    try:
        script = os.path.join(root, "parent.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(PARENT)
        env = dict(os.environ, TMPDIR=root)
        out, err = os.path.join(root, "pids.json"), os.path.join(root, "parent.err")
        # вывод — в файлы, не в трубу: воркеры наследуют stdout/stderr родителя, и сирота держала бы трубу открытой —
        # run ждал бы её конца до таймаута и оставлял сирот (так и было на мутанте без сторожа)
        with open(err, "w", encoding="utf-8") as fe:
            r = subprocess.run([sys.executable, "-I", script, HERE, out], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=fe, timeout=120, env=env, cwd=root)
        try:
            with open(out, encoding="utf-8") as fh:
                got = json.load(fh)
        except (OSError, ValueError):
            check("родитель поднял пул и вышел os._exit", False, (r.returncode, open(err).read()[-600:]))
            return
        pids = list(got["workers"]) + ([got["tracker"]] if got.get("tracker") else [])
        check("родитель поднял воркеры и resource_tracker", r.returncode == 0 and len(got["workers"]) >= 1
              and got.get("tracker"), got)
        end = time.monotonic() + DEADLINE
        left = [p for p in pids if alive(p)]
        while left and time.monotonic() < end:
            time.sleep(0.2)
            left = [p for p in pids if alive(p)]
        for p in left:  # не оставлять сирот и при провале проверки
            try:
                os.kill(p, signal.SIGKILL)
            except OSError:
                pass
        check(f"родитель умер (os._exit) — за {DEADLINE:g} с не осталось ни воркеров, ни resource_tracker",
              not left, {"осталось": left, "все": pids})
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_worker_exits_on_parent_change():
    """Сторож сам по себе: родитель при старте сменился — os._exit(0); пока тот же — работает дальше."""
    code = ("import os, sys, time\nsys.path.insert(0, sys.argv[1])\nimport _orphan_pool as m\n"
            "m.WATCH_EVERY = 0.05\nreal = os.getppid\n"
            "os.getppid = lambda: real()\nm.die_with_parent()\ntime.sleep(0.3)\nprint('жив', flush=True)\n"
            "os.getppid = lambda: real() + 100000\ntime.sleep(2)\nprint('не вышел', flush=True)\n")
    r = subprocess.run([sys.executable, "-I", "-c", code, HERE], capture_output=True, text=True, timeout=30)
    check("сторож: при том же родителе живёт, при смене — выход 0", r.returncode == 0 and r.stdout.split() == ["жив"],
          (r.returncode, r.stdout, r.stderr[-300:]))


def test_owner_pid1():
    """metis-0805: владелец пула — сам PID 1 (контейнер без init). ppid воркера 1 с самого старта — это живой родитель:
    сторож не выходит сразу, а выходит только при смене ppid. Владелец не 1, а ppid 1 — родитель умер, выход сразу.
    Подмена os.getppid в отдельном процессе; process_pool передаёт воркеру pid владельца (initargs)."""
    code = ("import os, sys, time\nsys.path.insert(0, sys.argv[1])\nimport _orphan_pool as m\n"
            "m.WATCH_EVERY = 0.05\nos.getppid = lambda: 1\nm.die_with_parent(int(sys.argv[2]))\ntime.sleep(0.4)\n"
            "print('жив', flush=True)\nos.getppid = lambda: 4242\ntime.sleep(2)\nprint('не вышел', flush=True)\n")
    r = subprocess.run([sys.executable, "-I", "-c", code, HERE, "1"], capture_output=True, text=True, timeout=30)
    check("владелец пула PID 1: ppid 1 с начала — сторож живёт, смена ppid — выход 0",
          r.returncode == 0 and r.stdout.split() == ["жив"], (r.returncode, r.stdout, r.stderr[-300:]))
    r = subprocess.run([sys.executable, "-I", "-c", code, HERE, "777"], capture_output=True, text=True, timeout=30)
    check("владелец пула не PID 1, ppid воркера 1 — родитель умер, выход 0 сразу",
          r.returncode == 0 and r.stdout.split() == [], (r.returncode, r.stdout, r.stderr[-300:]))
    sys.path.insert(0, HERE)
    import _orphan_pool as m
    real = m.ProcessPoolExecutor
    m.ProcessPoolExecutor = lambda **kw: kw
    try:
        kw = m.process_pool(2)
    finally:
        m.ProcessPoolExecutor = real
    check("process_pool передаёт воркеру pid владельца пула (initargs)",
          kw.get("initializer") is m.die_with_parent and kw.get("initargs") == (os.getpid(),), kw)


if __name__ == "__main__":
    if not sem_ok():
        print("пропущено: песочница окна не даёт семафоры — пул multiprocessing")
        test_worker_exits_on_parent_change()
    else:
        test_workers_die_with_parent()
        test_worker_exits_on_parent_change()
    test_owner_pid1()
    print(f"{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)
