#!/usr/bin/env python3
"""Тесты и пробы не показывают владельцу настоящие уведомления macOS (metis-0307).

Около 20:00 19.10 владельцу пришли «push не проходит несколько раз подряд» и «давно не синхронизируется с GitHub»
из test_commit_push: временные HOME и PANTHEON_STATE, но без PANTHEON_NOTIFY_LOG — notify звал terminal-notifier.
Теперь notify сам уводит уведомление в STATE/notify-test.log, если стоит PANTHEON_TEST или папка состояния не
настоящая. Здесь вместо terminal-notifier и osascript — ловушки: скрипты, которые только оставляют метку. Настоящий
terminal-notifier не запускается никогда, и при убранной защите тоже — тогда сработает ловушка и тест покраснеет.

Запуск: python3 -I plugins/pantheon/tests/test_notify_offscreen.py  (код выхода 0 — все прошли)
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

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="notify-offscreen-"))
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


TRAP = os.path.join(ROOT, "trap")
MARK = os.path.join(ROOT, "trap-fired.log")
os.makedirs(TRAP)
for name in ("terminal-notifier", "osascript"):
    f = os.path.join(TRAP, name)
    with open(f, "w") as fh:
        fh.write(f'#!/bin/sh\necho "{name} $*" >> "{MARK}"\nexit 0\n')
    os.chmod(f, 0o755)

# В подпроцессе: _notifier() указывает на ловушку (настоящий путь /opt/homebrew/bin в PATH не ищется),
# pwd — «учётная запись» с домашней папкой OWNER_HOME, чтобы проверить и случай настоящей папки состояния,
# не трогая настоящий ~/.local/state/pantheon.
PROBE = f"""
import json, os, pwd, sys
sys.path.insert(0, {LIB!r})
import pantheon as p
p._notifier = lambda: os.path.join({TRAP!r}, "terminal-notifier")
real_getpwuid = pwd.getpwuid
if os.environ.get("OWNER_HOME"):
    pwd.getpwuid = lambda uid: type("pw", (), {{"pw_dir": os.environ["OWNER_HOME"]}})()
off = p.notify_offscreen()
if os.environ.get("SEND"):
    p.notify("проверка metis-0307", group="probe")
print(json.dumps({{"offscreen": off, "state": p.STATE}}))
"""


def run(home, state=None, owner_home=None, test_flag=False, send=True):
    env = {"PATH": TRAP + ":" + os.environ["PATH"], "HOME": home}
    if state:
        env["PANTHEON_STATE"] = state
    if owner_home:
        env["OWNER_HOME"] = owner_home
    if test_flag:
        env["PANTHEON_TEST"] = "1"
    if send:
        env["SEND"] = "1"
    r = subprocess.run([PY311, "-I", "-c", PROBE], env=env, capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print(r.stdout, r.stderr)
        return {}


def fired():
    return open(MARK).read() if os.path.exists(MARK) else ""


def test_log(state):
    f = os.path.join(state, "notify-test.log")
    return open(f, encoding="utf-8").read() if os.path.exists(f) else ""


# 1. Как test_commit_push: временные HOME и PANTHEON_STATE, ни PANTHEON_NOTIFY_LOG, ни PANTHEON_TEST.
home1, state1 = os.path.join(ROOT, "h1"), os.path.join(ROOT, "s1")
os.makedirs(home1)
got = run(home1, state=state1)
check("временный STATE: notify не запускает внешний процесс (ловушки в PATH нетронуты)",
      got.get("offscreen") is True and fired() == "", (got, fired()))
check("временный STATE: уведомление строкой в STATE/notify-test.log",
      "Пантеон|проверка metis-0307||probe" in test_log(state1), test_log(state1))

# 2. Временный HOME без PANTHEON_STATE: папка состояния — по умолчанию из HOME, но HOME не владельца.
home2 = os.path.join(ROOT, "h2")
os.makedirs(home2)
got = run(home2)
st2 = os.path.join(home2, ".local", "state", "pantheon")
check("временный HOME без PANTHEON_STATE: тоже в файл, ловушки нетронуты",
      got.get("offscreen") is True and fired() == "" and "проверка metis-0307" in test_log(st2), (got, fired()))

# 3. Признак PANTHEON_TEST при «настоящей» папке (HOME совпадает с домашней папкой учётной записи).
home3 = os.path.join(ROOT, "h3")
os.makedirs(home3)
got = run(home3, owner_home=home3, test_flag=True)
st3 = os.path.join(home3, ".local", "state", "pantheon")
check("PANTHEON_TEST: в файл и при настоящей папке состояния",
      got.get("offscreen") is True and fired() == "" and "проверка metis-0307" in test_log(st3), (got, fired()))

# 4. Настоящая установка: HOME — домашняя папка учётной записи, STATE по умолчанию, признака теста нет.
#    Без отправки: здесь notify ушёл бы в ловушку, а не на экран, но проверяем только решение.
got = run(home3, owner_home=home3, send=False)
check("настоящая папка состояния без признака теста: уведомление идёт на экран (защита не глушит прод)",
      got.get("offscreen") is False, got)

# 5. Общая подмена: любой тест, подключивший _py311, несёт признак теста в окружении подпроцессов.
check("_py311 ставит PANTHEON_TEST=1", os.environ.get("PANTHEON_TEST") == "1")

check("ловушка за весь прогон не сработала ни разу", fired() == "", fired())

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
