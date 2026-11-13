#!/usr/bin/env python3
"""Ночной полный набор на main — итог из GitHub Actions (metis-1115, lib/nightly_tick.py): плановый проход набор не
гоняет, а читает итог запуска tests.yml по расписанию через gh; красный — задача на каждый упавший файл и тревога,
карантин назван, но задачи не даёт.

Запуск: python3 -I plugins/pantheon/tests/test_nightly_tick.py  (код выхода 0 — все прошли)
gh подменён (nightly_tick.gh_api и gh_text отвечают из словаря), ядро pantheon — заглушка с временным STATE; сеть,
настоящий gh и ~/.claude не трогаются. Проверяет:
  [зелёный]   success → строка «зелёный», тревога снята, задач нет; запрос — tests.yml на main; тот же запуск второй
              раз не разбирается; локально ничего не запускается (subprocess кроме gh не зовётся);
  [события]   запуск на pull_request и не на main не в счёт; идущий запуск — ждать, разбирается прошлый завершённый;
  [красный]   FAIL файлов в логах частей (с меткой времени GitHub) → задача на каждый, тревога с именами; открытая
              задача с тем же заголовком — не дубль; перезапуск (run_attempt 2) — разбирается заново;
  [карантин]  success и строка «карантин» → зелёный, «карантин упал: …» в строке, задач и тревоги нет;
  [сбой]      failure без FAIL: части не стартовали (нет steps) → тревога «не стартовали»; лог не прочитан → тревога;
              cancelled → строка без смены тревоги;
  [свежесть]  нет завершённых запусков / gh не отвечает дольше STALE → тревога STALE_KEY, свежий итог её снимает;
  [частота]   не чаще CHECK_EVERY; PANTHEON_DRYRUN — ничего; старые ключи running/result локального набора убраны.
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
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "lib")
sys.path.insert(0, HERE)
from _py311 import mkroot  # noqa: E402

_ROOT = os.path.realpath(mkroot("nightly-tick-"))
atexit.register(shutil.rmtree, _ROOT, True)
os.environ.pop("PANTHEON_DRYRUN", None)
REPO = "latark/agent-kit"
T = int(datetime(2026, 11, 14, 3, 0, tzinfo=timezone.utc).timestamp())
C0 = T - 5 * 3600  # время запуска по умолчанию: ночь до T
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
NT = load("pantheon_nightly_tick_n", "nightly_tick.py")

STAMP = "2026-11-13T22:41:07.1234567Z "
GREEN = STAMP + "ok   guard/test_a.py · 1.0 с · проверок 3\n" + STAMP + "итого: файлов 1, ok 1, FAIL 0; проверок 3; 1 с\n"
RED1 = (STAMP + "FAIL guard/test_a.py · 2.0 с · проверок 3 · код 1\n" + STAMP
        + "итого: файлов 1, ok 0, FAIL 1; проверок 3; 2 с\n")
RED2 = (STAMP + "FAIL pantheon/test_b.py · 2.0 с · проверок 1 · код 1\n" + STAMP
        + "итого: файлов 1, ok 0, FAIL 1; проверок 1; 2 с\n")
QUAR = (STAMP + "карантин pantheon/test_outside_idle.py · 1.0 с · проверок 2 · код 1 · задача metis-0989\n" + STAMP
        + "итого: файлов 1, ok 0, FAIL 0, карантин 1; проверок 2; 1 с\n")
STEPS = [{"name": "Тесты", "conclusion": "success"}]


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def run(rid, concl="success", status="completed", event="schedule", branch="main", attempt=1, created=None, sha="a" * 40):
    created = created or iso(C0)
    return {"id": rid, "run_attempt": attempt, "status": status, "conclusion": concl if status == "completed" else None,
            "event": event, "head_branch": branch, "created_at": created, "head_sha": sha,
            "html_url": f"https://github.com/{REPO}/actions/runs/{rid}"}


def jobs(rid, logs, steps=STEPS):
    """logs — {номер части: текст лога}; job частей full-shard и собирающий full."""
    js = [{"id": rid * 10 + k, "name": f"full-shard ({k}/{len(logs)})", "steps": steps} for k in logs]
    return {"total_count": len(js) + 1, "jobs": js + [{"id": rid * 10 + 9, "name": "full", "steps": STEPS}]}


class World:
    def __init__(self, open_titles=()):
        self.root = os.path.join(_ROOT, f"w{len(os.listdir(_ROOT))}")
        os.makedirs(self.root)
        self.state = os.path.join(self.root, "state")
        self.alerts, self.cleared, self.tasks, self.calls = [], [], [], []
        self.runs, self.jobs, self.logs = [], {}, {}
        self.api_err = None
        self.open = {t: f"metis-90{i:02d}" for i, t in enumerate(open_titles)}
        tasks = types.SimpleNamespace(
            load_tasks=lambda pantheon: {tid: ("p", {"title": t, "status": "todo"}, "") for t, tid in self.open.items()},
            task_new=self._task_new)
        core = types.SimpleNamespace(
            HOME=os.path.join(self.root, "home"), PANTHEON=os.path.join(self.root, "pantheon"),
            path=lambda *p: os.path.join(self.state, *p), now=lambda: T,
            read_json=self._read_json, write_json=self._write_json,
            stamp=lambda t=None: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)),
            alert_once=lambda key, value, text, who="pantheon", **kw: self.alerts.append((key, text)),
            clear_once=lambda key: self.cleared.append(key),
            merge_mod=lambda: M, tasks_mod=lambda: tasks)
        M.allowed_repos = lambda: {REPO, "latark/other"}
        NT.set_core(core)
        NT.gh_api = self.gh_api
        NT.gh_text = self.gh_text

    def gh_api(self, endpoint):
        self.calls.append(endpoint)
        if self.api_err:
            return None, self.api_err
        if endpoint.startswith(f"repos/{REPO}/actions/workflows/tests.yml/runs?"):
            return {"total_count": len(self.runs), "workflow_runs": list(self.runs)}, None
        for rid, data in self.jobs.items():
            if endpoint.startswith(f"repos/{REPO}/actions/runs/{rid}/jobs"):
                return data, None
        return None, f"нет ответа на {endpoint}"

    def gh_text(self, endpoint):
        self.calls.append(endpoint)
        for jid, text in self.logs.items():
            if endpoint == f"repos/{REPO}/actions/jobs/{jid}/logs":
                return text, None
        return None, "HTTP 410: логи удалены"

    def add(self, r, logs=None, steps=STEPS):
        self.runs.insert(0, r)
        if logs is not None:
            self.jobs[r["id"]] = jobs(r["id"], logs, steps)
            for k, text in logs.items():
                self.logs[r["id"] * 10 + k] = text

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


# локально ничего не запускается: subprocess под запретом на время тиков (gh подменён выше)
_real_popen, _real_run = subprocess.Popen, subprocess.run
LOCAL = []


def _forbid(*a, **kw):
    LOCAL.append(a[0] if a else kw.get("args"))
    raise AssertionError("локальный запуск из тика")


subprocess.Popen = subprocess.run = _forbid
CE = NT.CHECK_EVERY

# --- [зелёный] ----------------------------------------------------------------------------------------------------
w = World()
w.add(run(101), {1: GREEN, 2: GREEN, 3: GREEN})
out = NT.tick(T)
check("success → строка «зелёный» в tick.log, тревога снята, задач нет",
      out and "зелёный" in out and "nightly-tick: latark/agent-kit" in w.tick_log() and NT.ALERT_KEY in w.cleared
      and not w.tasks and not w.alerts, (out, w.alerts))
check("запрос — запуски tests.yml на main (gh api), других репозиториев нет",
      w.calls[0] == f"repos/{REPO}/actions/workflows/tests.yml/runs?branch=main&per_page=30"
      and not any("latark/other" in c for c in w.calls), w.calls)
check("логи всех трёх частей прочитаны, собирающий full — нет",
      sorted(c for c in w.calls if c.endswith("/logs")) == [f"repos/{REPO}/actions/jobs/{1010 + k}/logs" for k in (1, 2, 3)],
      w.calls)
check("локально ничего не запущено", not LOCAL, LOCAL)
n = len(w.calls)
check("не чаще CHECK_EVERY: следующий тик сразу — ничего, gh не зовётся", NT.tick(T + 60) is None and len(w.calls) == n)
NT.tick(T + CE)
check("тот же запуск второй раз не разбирается (job и логи не читаются)",
      not any("/jobs" in c for c in w.calls[n:]), w.calls[n:])

# --- [события] ----------------------------------------------------------------------------------------------------
w = World()
w.add(run(201), {1: GREEN})
w.add(run(202, concl="failure", event="pull_request"), {1: RED1})
w.add(run(203, concl="failure", branch="feature"), {1: RED1})
w.add(run(204, status="in_progress"))
out = NT.tick(T)
check("pull_request и не main не в счёт, идущий — ждать: разобран прошлый завершённый (201)",
      out and "зелёный" in out and not w.alerts and f"repos/{REPO}/actions/runs/201/jobs?per_page=100" in w.calls
      and not any("/runs/20" + x in c for c in w.calls for x in "234"), (out, w.calls))
w.runs[0] = run(204, concl="success", created="2026-11-14T22:00:00Z")
w.jobs[204] = jobs(204, {1: GREEN})
w.logs[2041] = GREEN
out = NT.tick(T + CE)
check("идущий завершился — разобран новый", out and "зелёный" in out and "/runs/204/jobs" in " ".join(w.calls), out)
r = run(205, concl="success", event="workflow_dispatch", created="2026-11-15T10:00:00Z")
w.add(r, {1: GREEN})
out = NT.tick(T + 2 * CE)
check("ручной запуск (workflow_dispatch) на main в счёт", out and "/runs/205/jobs" in " ".join(w.calls), out)

# --- [красный] ----------------------------------------------------------------------------------------------------
w = World(open_titles=(NT.TITLE.format(label="pantheon/test_b.py"),))
w.add(run(301, concl="failure"), {1: RED1, 2: RED2, 3: GREEN})
out = NT.tick(T)
check("красный → задача только на файл без открытой (guard/test_a.py), открытая не дублируется",
      [x[2] for x in w.tasks] == [NT.TITLE.format(label="guard/test_a.py")] and w.tasks[0][1] == "metis-pantheon", w.tasks)
check("тревога называет оба файла и задачи", w.alerts and w.alerts[-1][0] == NT.ALERT_KEY
      and "guard/test_a.py" in w.alerts[-1][1] and "pantheon/test_b.py" in w.alerts[-1][1]
      and "metis-9100" in w.alerts[-1][1] and "metis-9000" in w.alerts[-1][1], w.alerts)
check("текст задачи — sha, итог частей и ссылка на запуск", "a" * 12 in w.tasks[0][3]["text"]
      and "итого: файлов 1, ok 0, FAIL 1" in w.tasks[0][3]["text"]
      and f"https://github.com/{REPO}/actions/runs/301" in w.tasks[0][3]["text"], w.tasks)
w.runs[0] = run(301, concl="success", attempt=2)
w.jobs[301] = jobs(301, {1: GREEN})
w.logs[3011] = GREEN
out = NT.tick(T + CE)
check("перезапуск (run_attempt 2) того же запуска разобран заново: зелёный снимает тревогу",
      out and "зелёный" in out and NT.ALERT_KEY in w.cleared, (out, w.cleared))

# --- [карантин] ---------------------------------------------------------------------------------------------------
w = World()
w.add(run(401), {1: GREEN, 2: QUAR})
out = NT.tick(T)
check("success и строка «карантин» → зелёный, «карантин упал: …» в строке, задач и тревоги нет",
      out and "зелёный; карантин упал: pantheon/test_outside_idle.py" in out and not w.tasks and not w.alerts,
      (out, w.alerts))

# --- [сбой] -------------------------------------------------------------------------------------------------------
w = World()
w.add(run(501, concl="failure"), {1: "", 2: "", 3: ""}, steps=[])
out = NT.tick(T)
check("части без steps (Actions не запустились) → тревога «не стартовали», логи не запрашиваются",
      w.alerts and "не стартовали" in w.alerts[-1][1] and not any(c.endswith("/logs") for c in w.calls)
      and not w.tasks, (w.alerts, w.calls))
w = World()
w.add(run(502, concl="failure"), {1: RED1})
w.logs.clear()
out = NT.tick(T)
check("лог части не прочитан → тревога «лог части не прочитать» с причиной gh", w.alerts
      and "лог части не прочитать" in w.alerts[-1][1] and "410" in w.alerts[-1][1], w.alerts)
w = World()
w.add(run(503, concl="failure"), {1: GREEN})
NT.tick(T)
check("красный без FAIL и без причины → тревога «красный без строк FAIL»", w.alerts
      and "без строк FAIL" in w.alerts[-1][1], w.alerts)
w = World()
w.add(run(504, concl="cancelled"), {1: GREEN})
out = NT.tick(T)
check("cancelled → строка «итога нет», тревога не ставится и не снимается",
      out and "итога нет" in out and not w.alerts and NT.ALERT_KEY not in w.cleared, (out, w.alerts, w.cleared))

# --- [свежесть] ---------------------------------------------------------------------------------------------------
w = World()
out = NT.tick(T)
check("запусков нет, срок не вышел → без тревоги", not w.alerts and NT.STALE_KEY in w.cleared, (out, w.alerts))
out = NT.tick(T + NT.STALE + 1)
check("запусков нет дольше STALE → тревога STALE_KEY", w.alerts and w.alerts[-1][0] == NT.STALE_KEY
      and "итога ночного набора в Actions нет" in w.alerts[-1][1], w.alerts)
w.add(run(601, created=iso(T + NT.STALE)), {1: GREEN})
w.cleared.clear()
NT.tick(T + NT.STALE + 1 + CE)
check("свежий итог снимает STALE_KEY", NT.STALE_KEY in w.cleared, w.cleared)
w.api_err = "gh api: HTTP 502"
w.alerts.clear()
NT.tick(T + NT.STALE + 1 + 2 * CE)
check("gh не отвечает, но итог свежий → без тревоги", not w.alerts, w.alerts)
NT.tick(T + 2 * NT.STALE + 10)
check("gh не отвечает дольше STALE от последнего итога → тревога STALE_KEY с причиной gh",
      w.alerts and w.alerts[-1][0] == NT.STALE_KEY and "502" in w.alerts[-1][1], w.alerts)
w = World()
w.add(run(701), {1: GREEN})
NT.tick(T)
w.add(run(702, status="queued"))
w.alerts.clear()
NT.tick(C0 + NT.STALE + 10)
check("новый запуск не завершён дольше STALE после прошлого итога → тревога STALE_KEY",
      w.alerts and w.alerts[-1][0] == NT.STALE_KEY and "идёт новый" in w.alerts[-1][1], w.alerts)

# --- [частота] ----------------------------------------------------------------------------------------------------
w = World()
w._write_json(os.path.join(w.state, "nightly-tick.json"), {"running": {"t": T, "pid": 1}, "result": {"code": 1}})
w.add(run(801), {1: GREEN})
NT.tick(T)
st = w._read_json(os.path.join(w.state, "nightly-tick.json"))
check("старые ключи running/result локального набора убраны", "running" not in st and "result" not in st, st)
w = World()
os.environ["PANTHEON_DRYRUN"] = "1"
out = NT.tick(T)
os.environ.pop("PANTHEON_DRYRUN")
check("PANTHEON_DRYRUN=1 → ничего", out is None and not w.calls and not os.path.exists(w.state))
check("parse: метка времени GitHub срезана; FAIL, карантин и итоги",
      NT.parse(RED1 + QUAR) == (["guard/test_a.py"], ["pantheon/test_outside_idle.py"],
                                ["итого: файлов 1, ok 0, FAIL 1; проверок 3; 2 с",
                                 "итого: файлов 1, ok 0, FAIL 0, карантин 1; проверок 2; 1 с"]), NT.parse(RED1 + QUAR))
check("локально ничего не запущено за весь тест", not LOCAL, LOCAL)

subprocess.Popen, subprocess.run = _real_popen, _real_run
print(f"\n{len(CHECKS) - len(FAILS)}/{len(CHECKS)}")
sys.exit(1 if FAILS else 0)
