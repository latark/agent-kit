#!/usr/bin/env python3
"""Ночной полный набор на main (metis-1050, lib/nightly_tick.py): плановый проход ночью гоняет run-tests.py на свежем
origin/main, красный — задача на каждый упавший файл и тревога, карантин назван, но задачи не даёт.

Запуск: python3 -I plugins/pantheon/tests/test_nightly_tick.py  (код выхода 0 — все прошли)
Настоящий git на временных папках: голый «origin» с main; run-tests.py в репозитории — заглушка (вывод берёт из файла
рядом). heavy, load, задачи и запуск работника подменены (работник зовётся прямо). Проверяет:
  [зелёный]   ночью → прогон в копии на sha origin/main, строка nightly-tick, тревога снята, задач нет;
  [красный]   FAIL файлов → задача на каждый, тревога с именами; открытая задача с тем же заголовком — не дубль;
  [карантин]  упал только файл карантина → зелёный, но в строке «карантин упал: …», задач нет;
  [сбой]      без строки итога → тревога;
  [частота]   днём — ничего; раз за ночь; тот же sha в следующую ночь — не гоняет; load выше порога — пропуск;
              живой работник — тик ждёт; PANTHEON_DRYRUN — ничего.
"""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import types
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "lib")
sys.path.insert(0, HERE)
from _py311 import mkroot  # noqa: E402

_ROOT = os.path.realpath(mkroot("nightly-tick-"))
atexit.register(shutil.rmtree, _ROOT, True)
os.environ.pop("PANTHEON_DRYRUN", None)
REPO = "latark/agent-kit"
NIGHT = datetime.now().replace(hour=3, minute=0, second=0, microsecond=0)
T = int(NIGHT.timestamp())
DAY = int(NIGHT.replace(hour=14).timestamp())
FAILS = []
CHECKS = []


def check(name, cond, extra=""):
    CHECKS.append(name)
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f" — {extra}"))
    if not cond:
        FAILS.append(name)


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(LIB, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = load("pantheon_merge_n", "merge.py")
RT = load("pantheon_release_tick_n", "release_tick.py")
NT = load("pantheon_nightly_tick_n", "nightly_tick.py")


def git(d, *args):
    env = {"PATH": os.environ["PATH"], "HOME": os.path.join(_ROOT, "home"), "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


# заглушка раннера: печатает stub-out, код — stub-code; argv — в stub-argv
STUB = '''import os, sys
here = os.path.dirname(os.path.abspath(__file__))
open(os.path.join(here, "stub-argv"), "w").write(" ".join(sys.argv[1:]))
print(open(os.path.join(here, "stub-out")).read())
sys.exit(int(open(os.path.join(here, "stub-code")).read()))
'''
GREEN = "ok   guard/test_a.py · 1.0 с · проверок 3\nитого: файлов 1, ok 1, FAIL 0; проверок 3; 1 с, воркеров 3\n"
RED = ("FAIL guard/test_a.py · 2.0 с · проверок 3 · код 1\nFAIL pantheon/test_b.py · 2.0 с · проверок 1 · код 1\n"
       "итого: файлов 2, ok 0, FAIL 2; проверок 4; 2 с, воркеров 3\n")
QUAR = ("карантин pantheon/test_outside_idle.py · 1.0 с · проверок 2 · код 1 · задача metis-0989\n"
        "итого: файлов 1, ok 0, FAIL 0, карантин 1; проверок 2; 1 с, воркеров 3\n")


class World:
    def __init__(self, name, out=GREEN, code=0, loadavg=0.0, open_titles=()):
        self.root = os.path.join(_ROOT, name)
        os.makedirs(os.path.join(self.root, "home"))
        self.state = os.path.join(self.root, "state")
        self.origin = os.path.join(self.root, "origin.git")
        self.work = os.path.join(self.root, "work")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.work], check=True)
        sdir = os.path.join(self.work, "plugins", "pantheon", "scripts")
        os.makedirs(sdir)
        open(os.path.join(sdir, "run-tests.py"), "w").write(STUB)
        open(os.path.join(sdir, "stub-out"), "w").write(out)
        open(os.path.join(sdir, "stub-code"), "w").write(str(code))
        open(os.path.join(self.work, ".gitignore"), "w").write("stub-argv\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "начало")
        git(self.work, "remote", "add", "origin", self.origin)
        git(self.work, "push", "-q", "origin", "main")
        self.sha = git(self.work, "rev-parse", "HEAD")
        self.alerts, self.cleared, self.spawned, self.tasks = [], [], [], []
        self.open = {t: f"metis-90{i:02d}" for i, t in enumerate(open_titles)}
        tasks = types.SimpleNamespace(
            load_tasks=lambda pantheon: {tid: ("p", {"title": t, "status": "todo"}, "") for t, tid in self.open.items()},
            task_new=self._task_new)
        outside = types.SimpleNamespace(heavy_bin=lambda: "heavy-заглушка", load_state=lambda: (loadavg, 24.0))
        core = types.SimpleNamespace(
            HOME=os.path.join(self.root, "home"), PANTHEON=os.path.join(self.root, "pantheon"),
            path=lambda *p: os.path.join(self.state, *p), now=lambda: T,
            read_json=self._read_json, write_json=self._write_json,
            stamp=lambda t=None: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)),
            alert_once=lambda key, value, text, who="pantheon", **kw: self.alerts.append((key, text)),
            clear_once=lambda key: self.cleared.append(key),
            pid_alive=lambda pid: pid == os.getpid(),
            merge_mod=lambda: M, release_tick_mod=lambda: RT, outside_mod=lambda: outside, tasks_mod=lambda: tasks)
        M.allowed_repos = lambda: {REPO, "latark/other"}
        RT.set_core(core)
        RT.URL = self.origin
        NT.set_core(core)
        NT.spawn = self._spawn

    def _spawn(self, job):
        self.spawned.append(job)
        job = dict(job, heavy=[])   # heavy — заглушка: раннер зовётся прямо
        NT.work(job)

    def _task_new(self, pantheon, t, direction, title, **kw):
        tid = f"metis-91{len(self.tasks):02d}"
        self.tasks.append((tid, direction, title, kw))
        return tid, None

    @staticmethod
    def _read_json(p, default=None):
        try:
            with open(p) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {} if default is None else default

    @staticmethod
    def _write_json(p, data):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            json.dump(data, fh)

    def tick_log(self):
        p = os.path.join(self.state, "logs", "tick.log")
        return open(p).read() if os.path.exists(p) else ""

    def argv(self):
        p = os.path.join(self.state, "nightly", "agent-kit", "plugins", "pantheon", "scripts", "stub-argv")
        return open(p).read() if os.path.exists(p) else ""


# --- [зелёный] ----------------------------------------------------------------------------------------------------
w = World("green")
out = NT.tick(T)
check("ночью → прогон запущен на sha origin/main", w.spawned and w.spawned[0]["sha"] == w.sha and "запущен" in out,
      (out, w.spawned))
check("раннер — -j 3, --log-dir и все три папки плагинов",
      w.argv().startswith("-j 3 --log-dir ") and w.argv().endswith("plugins/guard plugins/pantheon plugins/project-tools"),
      w.argv())
check("другой репозиторий не трогается", not os.path.exists(os.path.join(w.state, "nightly", "other")))
out = NT.tick(T + 60)
check("итог — строка «зелёный» в tick.log, тревога снята, задач нет",
      "nightly-tick: latark/agent-kit" in w.tick_log() and "зелёный" in out and w.cleared and not w.tasks
      and not w.alerts, (out, w.tick_log()))
check("раз за ночь: следующий тик той же ночи — ничего", NT.tick(T + NT.CHECK_EVERY + 61) is None
      and len(w.spawned) == 1)
nxt = T + 24 * 3600
check("следующая ночь, main тот же — не гоняет", "уже прогнан ночью" in (NT.tick(nxt) or "") and len(w.spawned) == 1)
open(os.path.join(w.work, "x.txt"), "w").write("x")
git(w.work, "add", "-A")
git(w.work, "commit", "-q", "-m", "новое")
git(w.work, "push", "-q", "origin", "main")
out = NT.tick(nxt + 2 * 24 * 3600)
check("ночь с новым main — гоняет снова", len(w.spawned) == 2 and "запущен" in (out or ""), out)

# --- [красный] ----------------------------------------------------------------------------------------------------
w = World("red", out=RED, code=1, open_titles=(NT.TITLE.format(label="pantheon/test_b.py"),))
NT.tick(T)
out = NT.tick(T + 60)
check("красный → задача только на файл без открытой (guard/test_a.py), открытая не дублируется",
      [x[2] for x in w.tasks] == [NT.TITLE.format(label="guard/test_a.py")] and w.tasks[0][1] == "metis-pantheon", w.tasks)
check("тревога называет оба файла и задачи", w.alerts and "guard/test_a.py" in w.alerts[-1][1]
      and "pantheon/test_b.py" in w.alerts[-1][1] and "metis-9100" in w.alerts[-1][1] and "metis-9000" in w.alerts[-1][1],
      w.alerts)
check("текст задачи — sha, итог раннера и путь к логу", w.sha[:12] in w.tasks[0][3]["text"]
      and "итого: файлов 2" in w.tasks[0][3]["text"] and ".log" in w.tasks[0][3]["text"], w.tasks)

# --- [карантин] ---------------------------------------------------------------------------------------------------
w = World("quar", out=QUAR, code=0)
NT.tick(T)
out = NT.tick(T + 60)
check("упал только карантин → зелёный, «карантин упал: …» в строке, задач и тревоги нет",
      "зелёный; карантин упал: pantheon/test_outside_idle.py" in out and not w.tasks and not w.alerts, (out, w.alerts))

# --- [сбой] -------------------------------------------------------------------------------------------------------
w = World("broken", out="Traceback: всё сломалось\n", code=2)
NT.tick(T)
NT.tick(T + 60)
check("без строки итога → тревога «без строки итога»", w.alerts and "без строки итога" in w.alerts[-1][1], w.alerts)

# --- [частота] ----------------------------------------------------------------------------------------------------
w = World("day")
check("днём — ничего", NT.tick(DAY) is None and not w.spawned)
w = World("load", loadavg=99.0)
check("load выше порога → пропуск", NT.tick(T) is None and not w.spawned)
w = World("busy")
w._write_json(os.path.join(w.state, "nightly-tick.json"), {"running": {"t": T, "pid": os.getpid(), "sha": w.sha}})
check("живой работник → тик ждёт", NT.tick(T + 60) is None and not w.spawned)
w._write_json(os.path.join(w.state, "nightly-tick.json"), {"running": {"t": T, "pid": 1, "sha": w.sha, "repo": REPO}})
NT.tick(T + 120)
check("работник погиб без итога → тревога", w.alerts and "погиб" in w.alerts[-1][1], w.alerts)
w = World("dryrun")
os.environ["PANTHEON_DRYRUN"] = "1"
out = NT.tick(T)
os.environ.pop("PANTHEON_DRYRUN")
check("PANTHEON_DRYRUN=1 → ничего", out is None and not w.spawned and not os.path.exists(w.state))
check("parse: FAIL, карантин и итог", NT.parse(RED + QUAR) == (["guard/test_a.py", "pantheon/test_b.py"],
                                                             ["pantheon/test_outside_idle.py"],
                                                             "итого: файлов 1, ok 0, FAIL 0, карантин 1; проверок 2; 1 с, "
                                                             "воркеров 3"), NT.parse(RED + QUAR))

print(f"\n{len(CHECKS) - len(FAILS)}/{len(CHECKS)}")
sys.exit(1 if FAILS else 0)
