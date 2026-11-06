#!/usr/bin/env python3
"""Выпуск без Actions (metis-0880, lib/release_tick.py): плановый проход сам запускает release.py --push.

Запуск: python3 -I plugins/pantheon/tests/test_release_tick.py  (код выхода 0 — все прошли)
Настоящий git на временных папках: голый «origin» с main (коммит выпуска, затем слияние), веткой PR и рабочей копией
с незакоммиченной правкой release.py. release.py в репозитории — заглушка: пишет, откуда и с чем её позвали. gh
подменён (release_tick.gh_api), ядро pantheon — заглушка с временным STATE; сеть, настоящий gh и ~/.claude не трогаются.
Проверяет:
  [всё есть]  release.py --push зовётся из копии STATE/release/agent-kit на sha origin/main — не из рабочей папки и
              не с ветки PR; строка в logs/tick.log; на том же sha второй раз не зовётся;
  [условие 1] head main — коммит выпуска; слияние моложе 15 мин; коммита выпуска нет — не запускает;
  [условие 2] запуск release идёт, прошёл, отменён, упал не из-за лимита, ответ неполон, gh упал — не запускает;
              нет запуска, job без раннера, аннотация лимита — запускает;
  [условие 3] копия грязная или не на sha origin/main — не запускает, тревога;
  [частота]   повтор раньше 15 мин — без проверки; сбой release.py — тревога без critical; PANTHEON_DRYRUN — ничего.
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

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "lib")
sys.path.insert(0, HERE)
from _py311 import mkroot  # noqa: E402

_ROOT = os.path.realpath(mkroot("release-tick-"))
atexit.register(shutil.rmtree, _ROOT, True)
os.environ.pop("PANTHEON_DRYRUN", None)
REPO = "latark/agent-kit"
T = int(time.time())
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


M = load("pantheon_merge_t", "merge.py")
RT = load("pantheon_release_tick_t", "release_tick.py")


def git(d, *args, date=None):
    env = {"PATH": os.environ["PATH"], "HOME": os.path.join(_ROOT, "home"), "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    if date is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{date} +0000"
    r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


STUB = '''import json, os, subprocess, sys
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
with open({rec!r}, "a") as fh:
    fh.write(json.dumps({{"cwd": os.getcwd(), "argv": sys.argv[1:], "head": head, "from": {tag!r}}}) + "\\n")
print("готово: заглушка")
sys.exit({code})
'''


class World:
    """Временный мир: origin, рабочая копия, STATE, заглушка ядра."""

    def __init__(self, name, head="merge", merge_age=3600, release_code=0):
        self.root = os.path.join(_ROOT, name)
        os.makedirs(os.path.join(self.root, "home"))
        self.state = os.path.join(self.root, "state")
        self.rec = os.path.join(self.root, "release-calls.jsonl")
        self.origin = os.path.join(self.root, "origin.git")
        self.work = os.path.join(self.root, "work")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.work], check=True)
        script = os.path.join(self.work, ".github", "scripts", "release.py")
        os.makedirs(os.path.dirname(script))
        self._write(script, "main", release_code)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "начало", date=T - 7200)
        git(self.work, "commit", "-q", "--allow-empty", "-m", "выпуск: pantheon 0.1.1", date=T - 7000)
        if head == "merge":
            open(os.path.join(self.work, "f.txt"), "w").write("x")
            git(self.work, "add", "-A")
            git(self.work, "commit", "-q", "-m", "Merge pull request #1 from latark/x", date=T - merge_age)
        elif head == "no-release":
            git(self.work, "commit", "-q", "--amend", "--allow-empty", "-m", "не выпуск", date=T - 7000)
        git(self.work, "remote", "add", "origin", self.origin)
        git(self.work, "push", "-q", "origin", "main")
        self.sha = git(self.work, "rev-parse", "HEAD")
        # ветка PR со своим release.py — в копию не попадает
        git(self.work, "switch", "-q", "-c", "pr")
        self._write(script, "pr", 0)
        git(self.work, "commit", "-q", "-am", "PR: подмена release.py", date=T - 100)
        git(self.work, "push", "-q", "origin", "pr")
        git(self.work, "switch", "-q", "main")
        self._write(script, "worktree", 0)  # незакоммиченная правка рабочей копии
        self.alerts, self.cleared, self.calls = [], [], []
        self.api = {"runs": {"total_count": 0, "workflow_runs": []}}
        home = os.path.join(self.root, "home")
        core = types.SimpleNamespace(
            HOME=home, path=lambda *p: os.path.join(self.state, *p),
            read_json=self._read_json, write_json=self._write_json,
            stamp=lambda t=None: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)),
            alert_once=lambda key, value, text, who="pantheon", **kw: self.alerts.append((key, value, text, who, kw)),
            clear_once=lambda key: self.cleared.append(key),
            merge_mod=lambda: M)
        M.allowed_repos = lambda: {REPO, "latark/other"}
        RT.set_core(core)
        RT.URL = self.origin
        RT.gh_api = self.gh_api
        RT.prepare = ORIG_PREPARE

    def _write(self, script, tag, code):
        with open(script, "w") as fh:
            fh.write(STUB.format(rec=self.rec, tag=tag, code=code))

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

    def gh_api(self, endpoint):
        self.calls.append(endpoint)
        if "/annotations" in endpoint:
            key = "notes"
        elif "/jobs" in endpoint:
            key = "jobs"
        else:
            key = "runs"
            if f"head_sha={self.sha}" not in endpoint:
                return None, f"не тот sha в запросе: {endpoint}"
        got = self.api.get(key)
        return (None, got[1]) if isinstance(got, tuple) else (got, None)

    def run(self, **kw):
        status, concl = kw.get("status", "completed"), kw.get("conclusion", "failure")
        self.api["runs"] = {"total_count": kw.get("total", 1), "workflow_runs": [
            {"id": 11, "path": kw.get("path", ".github/workflows/release.yml@main"), "head_sha": self.sha,
             "status": status, "conclusion": concl}]}
        self.api["jobs"] = {"jobs": [kw.get("job", {"id": 21, "runner_id": 7, "runner_name": "GitHub Actions 7",
                                                     "steps": [{"name": "checkout"}]})]}
        self.api["notes"] = kw.get("notes", [])

    def releases(self):
        if not os.path.exists(self.rec):
            return []
        return [json.loads(ln) for ln in open(self.rec)]

    def tick_log(self):
        p = os.path.join(self.state, "logs", "tick.log")
        return open(p).read() if os.path.exists(p) else ""


ORIG_PREPARE = RT.prepare
BILLING = [{"annotation_level": "failure", "path": ".github",
            "message": M.CI_BILLING + ". For more information on how to increase your spending limit…"}]
UNSTARTED = {"id": 21, "runner_id": 0, "runner_name": "", "steps": []}

# --- [всё есть] ---------------------------------------------------------------------------------------------------
w = World("all")
out = RT.tick(T)
got = w.releases()
copy = os.path.realpath(os.path.join(w.state, "release", "agent-kit"))
check("всё есть, запуска release нет → release.py позван один раз", len(got) == 1, f"{got} {out}")
if got:
    g = got[0]
    check("release.py — с --push", g["argv"] == ["--push"], g)
    check("из копии STATE/release/agent-kit, не из рабочей папки", os.path.realpath(g["cwd"]) == copy
          and os.path.realpath(g["cwd"]) != os.path.realpath(w.work) and os.path.realpath(g["cwd"]) != os.getcwd(), g)
    check("код release.py — с main, не с ветки PR и не из правки рабочей копии", g["from"] == "main", g)
    check("копия на sha origin/main", g["head"] == w.sha, (g["head"], w.sha))
check("другой репозиторий из merge_repos не трогается", not os.path.exists(os.path.join(w.state, "release", "other")))
check("итог — строка release-tick в tick.log", "release-tick: latark/agent-kit: выпуск на " in w.tick_log(), w.tick_log())
check("удача снимает тревогу", w.cleared == [RT.ALERT_KEY] and not w.alerts, (w.cleared, w.alerts))
calls = len(w.calls)
check("повтор раньше 15 мин — без проверки", RT.tick(T + 60) is None and len(w.calls) == calls, w.calls)
RT.tick(T + RT.CHECK_EVERY + 1)
check("через 15 мин на том же sha release.py второй раз не зовётся", len(w.releases()) == 1, w.releases())
check("рабочая копия не тронута", "worktree" in open(os.path.join(w.work, ".github", "scripts", "release.py")).read()
      and git(w.work, "rev-parse", "--abbrev-ref", "HEAD") == "main")

# --- [условие 1] --------------------------------------------------------------------------------------------------
w = World("c1-release-head", head="release")
out = RT.tick(T)
check("условие 1: head main — коммит выпуска → не запускает", w.releases() == [] and "коммит выпуска" in out, out)
w = World("c1-young", merge_age=RT.MERGE_AGE - 60)
out = RT.tick(T)
check("условие 1: слияние моложе 15 мин → не запускает", w.releases() == [] and "моложе" in out, out)
w = World("c1-old-enough", merge_age=RT.MERGE_AGE + 1)
RT.tick(T)
check("условие 1: слияние старше 15 мин → запускает", len(w.releases()) == 1, w.releases())
w = World("c1-no-release", head="no-release")
out = RT.tick(T)
check("условие 1: коммита выпуска нет в истории → не запускает", w.releases() == [] and "нет в" in out, out)

# --- [условие 2] --------------------------------------------------------------------------------------------------
cases = [
    ("запуск release идёт", dict(status="in_progress", conclusion=None), False),
    ("запуск release в очереди, job без раннера", dict(status="queued", conclusion=None, job=UNSTARTED), False),
    ("запуск release прошёл", dict(conclusion="success"), False),
    ("запуск release отменён, job без раннера", dict(conclusion="cancelled", job=UNSTARTED), False),
    ("упал не из-за лимита (раннер был, аннотаций лимита нет)", dict(), False),
    ("аннотация лимита уровня warning", dict(notes=[dict(BILLING[0], annotation_level="warning")]), False),
    ("ответ gh неполон", dict(total=2, job=UNSTARTED), False),
    ("упал: job без раннера и шагов", dict(job=UNSTARTED), True),
    ("упал: аннотация лимита минут", dict(notes=BILLING), True),
    ("запуск другого workflow на sha не в счёт", dict(path=".github/workflows/tests.yml", conclusion="success"), True),
]
for i, (name, kw, want) in enumerate(cases):
    w = World(f"c2-{i}")
    w.run(**kw)
    out = RT.tick(T)
    check(f"условие 2: {name} → {'запускает' if want else 'не запускает'}", bool(w.releases()) == want, out)
w = World("c2-gh-down")
w.api["runs"] = (None, "gh api repos/x/actions/runs: HTTP 502")
out = RT.tick(T)
check("условие 2: gh не ответил → не запускает, тревога", w.releases() == [] and w.alerts
      and "HTTP 502" in w.alerts[0][2], (out, w.alerts))
w = World("c2-jobs-down")
w.run(job=UNSTARTED)
w.api["jobs"] = (None, "gh: таймаут")
RT.tick(T)
check("условие 2: список job не получен → не запускает", w.releases() == [] and w.alerts and "таймаут" in w.alerts[0][2], w.alerts)

# --- [условие 3] --------------------------------------------------------------------------------------------------
w2 = World("c3-dirty")
RT.tick(T)  # копия создана, release.py отработал
cp = os.path.join(w2.state, "release", "agent-kit")
n = len(w2.releases())
os.remove(os.path.join(w2.state, "release-tick.json"))  # без done_sha и метки частоты: проход дойдёт до условия 3
open(os.path.join(cp, "лишний.txt"), "w").write("грязь")
RT.prepare = lambda repo, copy: (w2.sha, None)  # сброс копии «не сработал»: остаётся то, что в ней
w2.calls.clear()
w2.alerts.clear()
RT.tick(T)
st = json.load(open(os.path.join(w2.state, "release-tick.json")))
check("условие 3: копия грязная → не запускает, тревога", len(w2.releases()) == n
      and any("не чистая" in a[2] for a in w2.alerts), (w2.releases(), w2.alerts, st))
check("условие 3 проверяется до gh", w2.calls == [], w2.calls)
os.remove(os.path.join(cp, "лишний.txt"))
os.remove(os.path.join(w2.state, "release-tick.json"))
git(cp, "checkout", "-q", "--detach", "HEAD~1")
w2.alerts.clear()
RT.tick(T)
check("условие 3: копия не на sha origin/main → не запускает", len(w2.releases()) == n
      and any("не на" in a[2] for a in w2.alerts), w2.alerts)
RT.prepare = ORIG_PREPARE

# --- [частота и сбой] ---------------------------------------------------------------------------------------------
w = World("fail", release_code=1)
RT.tick(T)
check("release.py с кодом 1 → тревога без critical", len(w.releases()) == 1 and w.alerts
      and "код 1" in w.alerts[0][2] and w.alerts[0][3] == "pantheon-tick" and not w.alerts[0][4].get("critical"),
      w.alerts)
RT.tick(T + RT.CHECK_EVERY + 1)
check("после сбоя через 15 мин — повтор (sha не запомнен)", len(w.releases()) == 2, w.releases())
check("сбой — строка в tick.log", "код 1" in w.tick_log(), w.tick_log())
w = World("dryrun")
os.environ["PANTHEON_DRYRUN"] = "1"
out = RT.tick(T)
os.environ.pop("PANTHEON_DRYRUN")
check("PANTHEON_DRYRUN=1 → ничего", out is None and w.releases() == [] and not os.path.exists(w.state))
w = World("no-repo")
M.allowed_repos = lambda: {"latark/other"}
check("agent-kit нет в merge_repos → ничего", RT.tick(T) is None and w.releases() == [])

print(f"\n{len(CHECKS) - len(FAILS)}/{len(CHECKS)}")
sys.exit(1 if FAILS else 0)
