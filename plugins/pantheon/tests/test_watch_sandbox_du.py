#!/usr/bin/env python3
"""metis-1007: плановый проход не считает полный du по кэшу песочниц на каждом проходе.

Запуск: python3 -I plugins/pantheon/tests/test_watch_sandbox_du.py  (код выхода 0 — все прошли)
- первый проход зовёт du, второй в пределах SANDBOX_DU_TTL и без изменений верхнего уровня — нет, размер из кэша;
- TTL вышел — du заново; появилась или изменилась (mtime) папка окна — заново; кэш другого корня — заново;
  битый файл кэша — заново, без падения;
- уборка что-то убрала (force) — заново; du не ответил (None) — кэш не пишется;
- тревога по размеру: из кэша срабатывает так же (больше потолка — alert_once, нет — clear_once).
"""
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
import types

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PLUGIN, "lib"))
w = importlib.import_module("watch")

fails, total = [], []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f" {extra}" if not cond else ""))
    total.append(name)
    if not cond:
        fails.append(name)


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="tmp-sbxdu-"))
    try:
        state, home = os.path.join(tmp, "state"), os.path.join(tmp, "home")
        root = os.path.join(home, "Library", "Caches", "pantheon-sandbox")
        os.makedirs(state)
        os.makedirs(os.path.join(root, "argus"))
        log = []

        def write_atomic(p, text):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text)

        P = types.SimpleNamespace(HOME=home, path=lambda *a: os.path.join(state, *a), write_atomic=write_atomic,
                                  alert=lambda *a, **k: log.append(("alert", a)),
                                  alert_once=lambda *a, **k: log.append(("once", a)),
                                  clear_once=lambda *a, **k: log.append(("clear", a)))
        w.P = P
        calls = []
        size = [100]

        def fake_du(r):
            calls.append(r)
            return size[0]
        w._du_mb = fake_du

        check("первый проход: du зовётся", w.sandbox_mb(root) == 100 and len(calls) == 1, str(calls))
        size[0] = 7000
        check("второй проход в пределах TTL: du не зовётся, размер из кэша", w.sandbox_mb(root) == 100 and len(calls) == 1,
              str(calls))
        cp = os.path.join(state, "sandbox-size.json")
        c = json.load(open(cp))
        c["t"] = time.time() - w.SANDBOX_DU_TTL - 5
        json.dump(c, open(cp, "w"))
        check("TTL вышел: du заново", w.sandbox_mb(root) == 7000 and len(calls) == 2, str(calls))
        size[0] = 50
        check("снова в пределах TTL: из кэша", w.sandbox_mb(root) == 7000 and len(calls) == 2, str(calls))
        os.makedirs(os.path.join(root, "hermes"))
        check("появилась папка окна: du заново", w.sandbox_mb(root) == 50 and len(calls) == 3, str(calls))
        size[0] = 60
        old = time.time() - 3600
        os.utime(os.path.join(root, "argus"), (old, old))
        check("mtime папки окна изменился: du заново", w.sandbox_mb(root) == 60 and len(calls) == 4, str(calls))
        size[0] = 70
        check("force (уборка убрала): du заново", w.sandbox_mb(root, force=True) == 70 and len(calls) == 5, str(calls))
        c = json.load(open(cp))
        c["root"] = "/другой"
        json.dump(c, open(cp, "w"))
        size[0] = 80
        check("кэш другого корня: du заново", w.sandbox_mb(root) == 80 and len(calls) == 6, str(calls))
        open(cp, "w").write("{не json")
        check("битый кэш: du заново, без падения", w.sandbox_mb(root) == 80 and len(calls) == 7, str(calls))
        os.unlink(cp)
        w._du_mb = lambda r: None
        check("du не ответил: None и кэш не пишется", w.sandbox_mb(root) is None and not os.path.exists(cp))

        # тревога по размеру — из кэша, так же
        w._du_mb = fake_du
        w.sandbox_clean = lambda *a, **k: (0, 0)
        w._open_paths = lambda: set()
        os.environ["PANTHEON_SANDBOX_CAP_MB"] = "1000"
        size[0] = 5000
        n = len(calls)
        log.clear()
        w.sandbox_sweep(1_792_000_000)
        check("проход 1: больше потолка — тревога", any(k == "once" for k, _ in log) and len(calls) == n + 1, str(log))
        size[0] = 1
        log.clear()
        w.sandbox_sweep(1_792_000_000)
        check("проход 2 из кэша: du нет, тревога та же", len(calls) == n + 1 and any(k == "once" for k, _ in log), str(log))
        w.sandbox_clean = lambda *a, **k: (2, 0)
        log.clear()
        w.sandbox_sweep(1_792_000_000)
        check("уборка убрала записи: du заново, размер 1 МБ — тревога снята",
              len(calls) == n + 2 and any(k == "clear" for k, _ in log) and not any(k == "once" for k, _ in log), str(log))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(total) - len(fails)}/{len(total)} ok")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
