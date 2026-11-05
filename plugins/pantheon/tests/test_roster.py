#!/usr/bin/env python3
"""Реестр демона Claude Code без ключей (metis-0871): P.roster_safe и команда `pantheon roster`.

Запуск: python3 -I plugins/pantheon/tests/test_roster.py  (код выхода 0 — все прошли)
Всё во временной папке: HOME подменён, реестр — подставной файл с выдуманными ключами. Проверяет, что команда и
функции, читающие реестр (daemon_workers, roster_changed_at, session_started), отдают только id, pid, startedAt и
updatedAt, а значения ключей в вывод не попадают.
"""
import atexit
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="roster-"))
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIB, "run.py")
results = []
SECRET_RV, SECRET_PTY, SECRET_TOP = "rv-SECRET-1f2e3d", "pty-SECRET-4c5b6a", "top-SECRET-778899"


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:600]}]"))


def home(tag, roster):
    h = os.path.join(ROOT, tag)
    os.makedirs(os.path.join(h, ".claude", "daemon"), exist_ok=True)
    if roster is not None:
        with open(os.path.join(h, ".claude", "daemon", "roster.json"), "w") as fh:
            fh.write(roster if isinstance(roster, str) else json.dumps(roster))
    return h


def cli(h, *args):
    env = {"PATH": os.environ["PATH"], "HOME": h, "PANTHEON_HOME": os.path.join(h, "ai", "pantheon"),
           "PANTHEON_STATE": os.path.join(h, "state"), "PANTHEON_NO_NOTIFY": "1", "TMPDIR": ROOT, "PANTHEON_TEST": "1"}
    return subprocess.run([PY311, "-I", RUN_PY, "roster", *args], env=env, capture_output=True, text=True, timeout=60)


ROSTER = {
    "updatedAt": 1_792_000_000_000, "controlKey": SECRET_TOP,
    "workers": {
        "abcd1234": {"pid": 4242, "startedAt": 1_791_999_000_000, "rvAuth": SECRET_RV, "ptyAuth": SECRET_PTY,
                     "sock": "/tmp/x.sock"},
        "efgh5678": {"pid": 77, "startedAt": 1_791_998_000_000, "rvAuth": {"token": SECRET_RV}},
        "bad": "not-a-dict",
        "odd": {"pid": {"nested": SECRET_PTY}, "startedAt": True},
    },
}

# 1. Команда печатает только безопасные поля, ключей в выводе нет
h = home("full", ROSTER)
r = cli(h)
out = r.stdout + r.stderr
try:
    got = json.loads(r.stdout)
except ValueError:
    got = None
check("1. pantheon roster: код 0 и JSON", r.returncode == 0 and isinstance(got, dict), out)
check("1. ключей (rvAuth, ptyAuth, прочих полей) в выводе нет",
      not any(s in out for s in (SECRET_RV, SECRET_PTY, SECRET_TOP, "rvAuth", "ptyAuth", "controlKey", "sock")), out)
check("1. поля — ровно updatedAt и у воркеров id, pid, startedAt", got == {
    "updatedAt": 1_792_000_000_000,
    "workers": {"abcd1234": {"pid": 4242, "startedAt": 1_791_999_000_000},
                "efgh5678": {"pid": 77, "startedAt": 1_791_998_000_000},
                "odd": {"pid": None, "startedAt": None}}}, got)

# 2. Реестра нет / он битый — код 1, причина последней строкой в stderr; аргумент — код 2
for tag, roster in (("missing", None), ("broken", "{not json"), ("list", "[1, 2]")):
    r = cli(home(tag, roster))
    check(f"2. реестр {tag}: код 1, причина последней строкой stderr",
          r.returncode == 1 and r.stdout == "" and "реестра демона нет" in r.stderr.strip().splitlines()[-1],
          (r.returncode, r.stdout, r.stderr))
r = cli(h, "--all")
check("2. аргумент — код 2 и подсказка", r.returncode == 2 and "аргументов нет" in r.stderr and r.stdout == "",
      (r.returncode, r.stderr))

# 3. Функции Пантеона в процессе: те же поля через roster_safe
os.environ["HOME"] = h
sys.path.insert(0, LIB)
P = importlib.import_module("pantheon")
P.HOME = h
safe = P.roster_safe()
check("3. roster_safe без ключей", SECRET_RV not in json.dumps(safe) and SECRET_PTY not in json.dumps(safe)
      and SECRET_TOP not in json.dumps(safe), safe)
check("3. daemon_workers: id → pid", P.daemon_workers() == {"abcd1234": 4242, "efgh5678": 77, "odd": None},
      P.daemon_workers())
check("3. roster_changed_at: updatedAt в с", P.roster_changed_at() == 1_792_000_000, P.roster_changed_at())
check("3. session_started берёт startedAt воркера",
      P.session_started({"id": "abcd1234", "startedAt": 1_000}) == 1_791_999_000, P.session_started({"id": "abcd1234"}))
check("3. session_started: воркера нет — startedAt записи",
      P.session_started({"id": "zzzz9999", "startedAt": 5_000}) == 5, P.session_started({"id": "zzzz9999"}))
# workers не объект: о процессах ничего не утверждаем, updatedAt остаётся
P.HOME = home("noworkers", {"updatedAt": 2_000, "workers": [SECRET_RV]})
check("3. workers не объект — daemon_workers None, updatedAt есть",
      P.daemon_workers() is None and P.roster_changed_at() == 2.0 and SECRET_RV not in json.dumps(P.roster_safe()),
      P.roster_safe())
P.HOME = home("nofile", None)
check("3. реестра нет — None везде", P.roster_safe() is None and P.daemon_workers() is None
      and P.roster_changed_at() is None and P.session_started({"id": "abcd1234", "startedAt": 3_000}) == 3)

print(f"\n{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
