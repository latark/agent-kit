#!/usr/bin/env python3
"""Зависший terminal-notifier или osascript не обрывает вызывающего (metis-0709): notify() ловит TimeoutExpired.

Запуск: python3 -I plugins/pantheon/tests/test_notify_hang.py  (код выхода 0 — все прошли)
"""
import atexit
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: F401 — модуль pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="nhang-root-")
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)
tmp = os.path.realpath(tempfile.mkdtemp(prefix="nhang-test-"))
os.environ.update(HOME=tmp, PANTHEON_HOME=os.path.join(tmp, "p"), PANTHEON_STATE=os.path.join(tmp, "s"),
                  PANTHEON_VIEW=os.path.join(tmp, "v"))
for k in ("PANTHEON_NOTIFY_LOG", "PANTHEON_NO_NOTIFY", "PANTHEON_DRYRUN", "PANTHEON_TEST"):
    os.environ.pop(k, None)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
spec = importlib.util.spec_from_file_location("pantheon_nhang", LIB)
P = importlib.util.module_from_spec(spec)
sys.modules["pantheon_nhang"] = P
spec.loader.exec_module(P)

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


calls = []


def hang(args, **kw):
    calls.append(args[0])
    raise subprocess.TimeoutExpired(args, kw.get("timeout", 0))


P.notify_offscreen = lambda: False  # дойти до настоящей отправки
P._notifier = lambda: "/fake/terminal-notifier"
P.subprocess.run = hang
try:
    P.notify("текст", title="т", group="g")
    check("notifier и osascript зависли: notify() вернулся без исключения", True)
    check("после зависшего notifier пробуется osascript", calls == ["/fake/terminal-notifier", "osascript"], calls)
except subprocess.TimeoutExpired as e:
    check("notifier и osascript зависли: notify() вернулся без исключения", False, repr(e))

calls.clear()
P._notifier = lambda: None
try:
    P.notify("текст")
    check("osascript завис без notifier: без исключения", calls == ["osascript"], calls)
except subprocess.TimeoutExpired as e:
    check("osascript завис без notifier: без исключения", False, repr(e))

print(f"{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
