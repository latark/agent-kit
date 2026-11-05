#!/usr/bin/env python3
"""Пропуск прогонов тика без изменений входов (metis-0149): четыре случая и отпечатки всех четырёх задач.

Запуск: python3 -I plugins/pantheon/tests/test_tick_skip.py  (код выхода 0 — все прошли)
Всё во временных папках: HOME, PANTHEON_HOME, PANTHEON_STATE подменены; sync.sh — заглушка, пишущая отметку.
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

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="tick-skip-"))
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
T0 = 1_792_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


SCHED = '''primary_host = "mac-a"
[[job]]
name = "sw"
command = "pantheon sync-answers"
every = "tick"
[[job]]
name = "view"
command = "pantheon view --quiet"
every = "tick"
[[job]]
name = "board"
command = "pantheon board"
every = "tick"
[[job]]
name = "agents"
command = "pantheon agents"
every = "tick"
[[job]]
name = "plain"
command = "pantheon view"
every = "tick"
'''


class Env:
    def __init__(self, tag):
        self.home = os.path.join(ROOT, tag, "home")
        self.pan = os.path.join(ROOT, tag, "pantheon")
        self.state = os.path.join(ROOT, tag, "state")
        self.claude = os.path.join(self.home, ".claude")
        self.mark = os.path.join(ROOT, tag, "sync-runs")
        for d in (self.claude, self.pan, os.path.join(self.state, "owner-log")):
            os.makedirs(d, exist_ok=True)
        with open(os.path.join(self.pan, "schedule.toml"), "w") as fh:
            fh.write(SCHED)
        sh = os.path.join(self.claude, "sync.sh")
        with open(sh, "w") as fh:
            fh.write(f'#!/bin/sh\necho x >> "{self.mark}"\n')
        os.chmod(sh, 0o755)
        with open(os.path.join(self.claude, ".sync-held"), "w") as fh:
            fh.write("task=T1\n")
        self.answer("Отправить на другие Mac")

    def answer(self, text):
        with open(os.path.join(self.state, "owner-log", "board.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": "answer", "id": "T1", "answer": text}, ensure_ascii=False) + "\n")

    def run(self, args, t, dry=False, **extra):
        env = {"PATH": os.environ["PATH"], "HOME": self.home, "PANTHEON_HOME": self.pan, "PANTHEON_STATE": self.state,
               "PANTHEON_NOW": str(t), "PANTHEON_HOST": "mac-a", "PANTHEON_NO_NOTIFY": "1",
               "PANTHEON_VIEW": os.path.join(ROOT, "view"), "TMPDIR": ROOT}
        if dry:
            env["PANTHEON_DRYRUN"] = "1"
        env.update(extra)
        return subprocess.run([PY311, "-I", RUN_PY] + args, env=env, capture_output=True, text=True, timeout=60)

    def syncs(self):
        return len(open(self.mark).read().split()) if os.path.exists(self.mark) else 0

    def launched(self):
        p = os.path.join(self.state, "dryrun.log")
        return [ln.split()[1] for ln in open(p)] if os.path.exists(p) else []

    def skipped(self):
        try:
            return json.load(open(os.path.join(self.state, "tick-skipped.json")))["skipped"]
        except (OSError, ValueError, KeyError):
            return None

    def reset_log(self):
        with open(os.path.join(self.state, "dryrun.log"), "w"):
            pass


def primed(tag):
    e = Env(tag)
    r = e.run(["run-job", "sw"], T0)
    st = json.load(open(os.path.join(e.state, "jobs", "sw.json")))
    assert r.returncode == 0 and e.syncs() == 1 and st.get("skip_fp"), (r.stderr, st)
    return e


# 1. входы не менялись — задача пропущена, остальное идёт (view/board/agents без прогона не пропускаются)
e = primed("same")
e.run(["tick"], T0 + 60, dry=True)
check("1. входы не менялись: sync-answers не запущен тиком", "sw" not in e.launched(), e.launched())
check("1. пропуск записан в tick-skipped.json", e.skipped() == ["sw"], e.skipped())
check("1. задача вне таблицы (pantheon view) идёт как раньше", "plain" in e.launched(), e.launched())
check("1. задачи таблицы, не бежавшие ни разу, идут", {"view", "board", "agents"} <= set(e.launched()), e.launched())

# 2. вход изменился — идёт
e = primed("changed")
e.answer("Пока держать")
e.run(["tick"], T0 + 60, dry=True)
check("2. вход изменился: задача запущена", "sw" in e.launched() and "sw" not in (e.skipped() or []),
      (e.launched(), e.skipped()))

# 3. прошло 15 минут — идёт, хотя входы те же
e = primed("quarter")
e.run(["tick"], T0 + 899, dry=True)
a = "sw" not in e.launched()
e.reset_log()
e.run(["tick"], T0 + 901, dry=True)
check("3. через 15 минут: на 899-й секунде пропуск, на 901-й запуск", a and "sw" in e.launched(), (a, e.launched()))

# 4. ручной вызов идёт, пока тик пропускает
e = primed("manual")
e.run(["tick"], T0 + 60, dry=True)
skipped = "sw" not in e.launched()
r = e.run(["sync-answers"], T0 + 61)
check("4. ручной `pantheon sync-answers` выполняется при тех же входах, когда тик его пропускает",
      skipped and r.returncode == 0 and e.syncs() == 2, (skipped, r.returncode, e.syncs()))
r = e.run(["run-job", "sw"], T0 + 62)
check("4. `pantheon run-job` тоже идёт", r.returncode == 0 and e.syncs() == 3, (r.returncode, e.syncs()))

# 5. неудачный прогон отпечаток не оставляет
e = primed("fail")
os.chmod(os.path.join(e.claude, "sync.sh"), 0o644)  # sync.sh не запускается — sync-answers вернёт 1
e.answer("Откатить правку")
r = e.run(["run-job", "sw"], T0 + 10)
st = json.load(open(os.path.join(e.state, "jobs", "sw.json")))
e.run(["tick"], T0 + 70, dry=True)
check("5. прогон с кодом не 0: отпечатка нет, тик задачу запускает",
      r.returncode != 0 and "skip_fp" not in st and "sw" in e.launched(), (r.returncode, st, e.launched()))

# 6. отпечатки всех четырёх задач: есть и меняются при смене входа
probe = f"""
import json, os, sys
sys.path.insert(0, {os.path.dirname(LIB)!r})
import pantheon as p
jobs = {{n: {{"command": c}} for n, c in [("view", "pantheon view --quiet"), ("board", "pantheon board"),
        ("sw", "pantheon sync-answers"), ("agents", "pantheon agents"), ("other", "pantheon view")]}}
fp = lambda: {{n: p.tick_fingerprint(j) for n, j in jobs.items()}}
a = fp()
mut = json.loads(sys.argv[1])
for kind, target, *body in mut:
    d = os.path.dirname(target)
    os.makedirs(d, exist_ok=True)
    open(target, "w" if body else "a").write(body[0] if body else "x")
    b = fp()
    print(json.dumps([kind, [n for n in a if a[n] != b[n]]]))
    a = b
print(json.dumps(["none", [n for n in a if a[n] is None]]))
"""
e = Env("fps")
for d in (os.path.join(ROOT, "view"), os.path.join(e.pan, "inbox", "tasks")):
    os.makedirs(d, exist_ok=True)
muts = [["view", os.path.join(e.pan, "notes", "a.md")],
        ["board", os.path.join(e.pan, "inbox", "tasks", "t1.md")],
        ["sw", os.path.join(e.claude, ".sync-incoming")],
        ["agents", os.path.join(e.claude, "daemon", "roster.json")],
        # входы сводки board-auto.md (metis-0397): ревью, STATUS.md, decisions.md, журнал владельца, кэш открытых PR
        ["b-review", os.path.join(e.pan, "directions", "metis-pantheon", "review-120-argus.md")],
        ["b-status", os.path.join(e.pan, "directions", "metis-pantheon", "STATUS.md")],
        ["b-decisions", os.path.join(e.pan, "decisions.md")],
        ["b-ownerlog", os.path.join(e.state, "owner-log", "zeus.md")],
        ["b-prs", os.path.join(e.state, "autoclose-prs.json"),
         json.dumps({"open_prs": {"latark/agent-kit": [{"number": 120, "head": "abcdef1", "ids": [], "core": False}]}})],
        ["b-prs-same", os.path.join(e.state, "autoclose-prs.json"),
         json.dumps({"open_prs": {"latark/agent-kit": [{"number": 120, "head": "abcdef1", "ids": [], "core": False}]},
                     "checked": 1})],
        # следы работы для статусов (metis-0397, п. 7): worktree в репозитории направления, PR, закрывающий задачу
        ["b-repo", os.path.join(ROOT, "fps-repo", ".git", "config")],
        ["b-domains", os.path.join(e.state, "domains.json"),
         json.dumps({"domains": {"metis-pantheon": [os.path.join(ROOT, "fps-repo")]}})],
        ["b-wt-head", os.path.join(ROOT, "fps-repo", ".git", "worktrees", "w1", "HEAD"), "ref: refs/heads/metis-0600-x\n"],
        ["b-wt-gitdir", os.path.join(ROOT, "fps-repo", ".git", "worktrees", "w1", "gitdir"),
         os.path.join(ROOT, "fps-copy", ".git") + "\n"],
        ["b-wt-live", os.path.join(ROOT, "fps-copy", ".git")],
        ["b-closes", os.path.join(e.state, "autoclose-prs.json"),
         json.dumps({"open_prs": {"latark/agent-kit": [{"number": 120, "head": "abcdef1", "ids": [], "core": False,
                                                        "closes": ["metis-0600"]}]}, "checked": 1})],
        # metis-0808: сбой gh по репозиторию и время последнего успеха меняют отпечаток (строка «данные от HH:MM» в board-auto)
        ["b-errors", os.path.join(e.state, "autoclose-prs.json"),
         json.dumps({"open_prs": {"latark/agent-kit": [{"number": 120, "head": "abcdef1", "ids": [], "core": False,
                                                        "closes": ["metis-0600"]}]}, "checked": 1,
                     "errors": {"latark/agent-kit": "HTTP 401"}, "stale": {"latark/agent-kit": 100}})],
        ["b-stale", os.path.join(e.state, "autoclose-prs.json"),
         json.dumps({"open_prs": {"latark/agent-kit": [{"number": 120, "head": "abcdef1", "ids": [], "core": False,
                                                        "closes": ["metis-0600"]}]}, "checked": 1,
                     "errors": {"latark/agent-kit": "HTTP 401"}, "stale": {"latark/agent-kit": 200}})],
        ["b-pr-error", os.path.join(e.state, "autoclose-prs.json"),
         json.dumps({"open_prs": {"latark/agent-kit": [{"number": 120, "head": "abcdef1", "ids": [], "core": False,
                                                        "closes": ["metis-0600"]}]}, "checked": 1,
                     "errors": {"latark/agent-kit": "HTTP 401", "latark/agent-kit#5": "diff"}, "stale": {"latark/agent-kit": 200}})]]
r = subprocess.run([PY311, "-I", "-c", probe, json.dumps(muts)],
                   env={"PATH": os.environ["PATH"], "HOME": e.home, "PANTHEON_HOME": e.pan, "PANTHEON_STATE": e.state,
                        "PANTHEON_VIEW": os.path.join(ROOT, "view"), "TMPDIR": ROOT},
                   capture_output=True, text=True, timeout=60)
rows = {}
for ln in r.stdout.splitlines():
    k, v = json.loads(ln)
    rows[k] = v
check("6. новый файл в ~/ai/pantheon меняет отпечаток view", "view" in rows.get("view", []), (rows, r.stderr[-300:]))
check("6. новая задача меняет отпечаток board", "board" in rows.get("board", []), rows)
check("6. .sync-incoming меняет отпечаток sync-answers", "sw" in rows.get("sw", []), rows)
check("6. roster.json демона меняет отпечаток agents", "agents" in rows.get("agents", []), rows)
for k, what in [("b-review", "review-*-argus.md"), ("b-status", "STATUS.md"), ("b-decisions", "decisions.md"),
                ("b-ownerlog", "журнал владельца"), ("b-prs", "открытые PR в кэше autoclose")]:
    check(f"6. {what} меняет отпечаток board", "board" in rows.get(k, []), rows)
check("6. прочие поля кэша autoclose (не открытые PR) отпечаток board не меняют", "board" not in rows.get("b-prs-same", ["board"]),
      rows)
for k, what in [("b-domains", "новый репозиторий направления в domains.json"),
                ("b-wt-head", "новая запись worktree (HEAD)"), ("b-wt-live", "появившаяся папка копии worktree"),
                ("b-closes", "PR в кэше стал закрывать задачу")]:
    check(f"6. {what} меняет отпечаток board", "board" in rows.get(k, []), rows)
check("6. 0808: появилась ошибка gh по репозиторию (errors) - отпечаток board другой", "board" in rows.get("b-errors", []), rows)
check("6. 0808: сменилось только время последнего успеха (stale) - отпечаток board другой", "board" in rows.get("b-stale", []), rows)
check("6. 0808: ошибка по PR (ключ с «#») блок не меняет - отпечаток тот же", "board" not in rows.get("b-pr-error", ["board"]), rows)
check("6. отпечаток только у задач таблицы (pantheon view без --quiet — нет)", rows.get("none") == ["other"], rows)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
