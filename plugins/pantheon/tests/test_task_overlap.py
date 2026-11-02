#!/usr/bin/env python3
"""Пересечение файлов внутри направления перед раздачей (metis-0665): `pantheon task overlap ID` и предупреждение при
`task set ID status=doing` / `task claim` — touches задачи против живых (doing, review) задач своего направления и
файлов открытых PR его репозиториев ([merge_repos] policy.toml). Вывод — с чем пересекается, какие файлы, и выбор с
готовыми командами: очередь (ждать слияния PR) или ветка от ветки PR (stacked PR, argus только на дельту). gh не
ответил — кэш планового прохода или строка «не проверено», не молчание. Предупреждение, не отказ: код 0, запись сделана.
gh подделан скриптом (PANTHEON_GH).

Запуск: python3 -I plugins/pantheon/tests/test_task_overlap.py  (код выхода 0 — все прошли)
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="overlap-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIB, "run.py")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402
import autoclose as A  # noqa: E402

T0 = 1_793_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


FAKE_GH = """#!/bin/sh
d="$FAKE_GH_DIR"; repo=""; prev=""
echo "$@" >> "$d/calls.log"
if [ -f "$d/fail" ]; then echo "error connecting to api.github.com" >&2; exit 1; fi
for a in "$@"; do
  case "$prev" in -R|--repo) repo="$a";; esac
  prev="$a"
done
if [ "$1 $2" = "pr list" ]; then
  f="$d/$(echo "$repo" | tr / _).json"
  [ -f "$f" ] && cat "$f" || echo "[]"
  exit 0
fi
exit 1
"""

DIRS = '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n\n[[direction]]\nname = "demo"\nproject = "Демо"\n'
POLICY = '[merge_repos]\nmetis-pantheon = ["latark/agent-kit"]\ndemo = ["acme/site"]\n'
GATE, MERGE = "plugins/guard/hooks/merge_gate.py", "plugins/pantheon/lib/merge.py"


def make(policy=POLICY):
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="overlap-test-"))
    home, state, view, gh = (os.path.join(tmp, x) for x in ("pantheon", "state", "view", "gh"))
    for d in ("directions/metis-pantheon/tasks", "directions/demo/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    for d in (view, gh, state, os.path.join(tmp, ".claude", "pantheon")):
        os.makedirs(d, exist_ok=True)
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(DIRS)
    if policy is not None:
        open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w", encoding="utf-8").write(policy)
    with open(os.path.join(gh, "gh"), "w") as fh:
        fh.write(FAKE_GH)
    os.chmod(os.path.join(gh, "gh"), 0o755)
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0", "FAKE_GH_DIR": gh, "PANTHEON_GH": os.path.join(gh, "gh"), "TMPDIR": tmp,
           "PANTHEON_METRICS": "0"}
    return tmp, home, state, gh, env


def pan(env, *a):
    return subprocess.run([PY311, "-I", RUN_PY, *a], env=dict(env, PANTHEON_NOW=str(T0)), capture_output=True, text=True,
                          timeout=120)


def put(home, direction, tid, status="todo", touches=None, **f):
    lines = ["---", "type: task", f"id: {tid}", f"title: Задача {tid}", f"status: {status}",
             f"project: {'Пантеон' if direction == 'metis-pantheon' else 'Демо'}", f"direction: {direction}",
             f"owner: {f.pop('owner', direction)}", "created: 2026-11-01", "updated: 2026-11-01T10:00:00",
             "schema_version: 1"]
    if touches:
        lines.append(f"touches: [{', '.join(touches)}]")
    for k, v in f.items():
        lines.append(f"{k}: {v}")
    lines += ["---", "", f"# Задача {tid}", "", "Текст.", "", "## Журнал", "", "- 2026-11-01 10:00 — агент: создана", ""]
    open(os.path.join(home, "directions", direction, "tasks", tid + ".md"), "w", encoding="utf-8").write("\n".join(lines))


def gh_prs(gh, repo, prs):
    open(os.path.join(gh, repo.replace("/", "_") + ".json"), "w").write(json.dumps(prs))


def calls(gh):
    p = os.path.join(gh, "calls.log")
    return open(p).read() if os.path.exists(p) else ""


PR248 = {"number": 248, "headRefName": "ci-billing-0655", "body": "Closes metis-0655",
         "files": [{"path": GATE}, {"path": MERGE}, {"path": "README.md"}]}
PR250 = {"number": 250, "headRefName": "other-0656", "body": "Closes metis-0656", "files": [{"path": "plugins/pantheon/lib/board.py"}]}


def pure():
    tasks = {
        "metis-0001": ("", {"type": "task", "direction": "metis-pantheon", "status": "todo",
                            "touches": ["plugins/guard/", MERGE], "depends_on": ["metis-0009"]}, ""),
        "metis-0002": ("", {"type": "task", "direction": "metis-pantheon", "status": "doing", "owner": "dev-a",
                            "touches": [GATE]}, ""),
        "metis-0003": ("", {"type": "task", "direction": "metis-pantheon", "status": "review", "touches": [MERGE]}, ""),
        "metis-0004": ("", {"type": "task", "direction": "metis-pantheon", "status": "todo", "touches": [GATE]}, ""),
        "metis-0005": ("", {"type": "task", "direction": "metis-pantheon", "status": "done", "touches": [GATE]}, ""),
        "demo-0001": ("", {"type": "task", "direction": "demo", "status": "doing", "touches": [GATE]}, ""),
        "metis-0006": ("", {"type": "story", "direction": "metis-pantheon", "status": "doing", "touches": [GATE]}, ""),
        "metis-0007": ("", {"type": "task", "direction": "metis-pantheon", "status": "doing", "touches": ["plugins/guardx"]}, ""),
    }
    got = T.overlap_tasks(tasks, "metis-0001")
    check("overlap_tasks: doing и review своего направления; todo, done, чужое направление, пачка, соседняя папка — нет",
          [g[0] for g in got] == ["metis-0002", "metis-0003"], got)
    check("overlap_tasks: общая область — более узкая (файл, а не папка задачи), owner и статус в строке",
          got[0] == ("metis-0002", "doing", "dev-a", [GATE]) and got[1][3] == [MERGE], got)
    tasks["metis-0001"][1]["touches"] = []
    check("overlap_tasks: без touches — пусто", T.overlap_tasks(tasks, "metis-0001") == [])
    tasks["metis-0001"][1]["touches"] = ["plugins/guard/", MERGE]
    head = tasks["metis-0001"][1]
    prs = [{"repo": "latark/agent-kit", "number": 248, "branch": "ci-billing-0655", "files": [GATE, MERGE, "README.md"],
            "ids": ["metis-0655"], "closes": ["metis-0655"]},
           {"repo": "latark/agent-kit", "number": 249, "branch": "mine-0001", "files": [GATE], "ids": ["metis-0001"], "closes": []},
           {"repo": "latark/agent-kit", "number": 251, "branch": "nofiles", "files": None, "ids": [], "closes": []},
           {"repo": "latark/agent-kit", "number": 252, "branch": "far", "files": ["docs/x.md"], "ids": [], "closes": []}]
    cp = T.overlap_prs("metis-0001", head, prs)
    check("overlap_prs: PR с общими файлами — с их списком; свой PR, PR без файлов и без пересечения — нет",
          [(p["number"], c) for p, c in cp] == [(248, sorted([GATE, MERGE]))], cp)
    text = "\n".join(T.overlap_text("metis-0001", head, got + [("metis-0655", "doing", "", [GATE])], cp))
    check("overlap_text: названы задачи и PR с файлами",
          "задача metis-0002 (doing, dev-a, открытого PR нет): " + GATE in text
          and "задача metis-0655 (doing, PR #248): " + GATE in text
          and f"PR #248 latark/agent-kit (ветка ci-billing-0655, metis-0655): {GATE}, {MERGE}" in text, text)
    for frag in ("gh pr view 248 -R latark/agent-kit --json state,mergedAt",
                 "git fetch origin && git switch -c metis-0001 origin/main",
                 "pantheon task set metis-0001 status=todo depends_on=metis-0009,metis-0655",
                 "git fetch origin && git switch -c metis-0001 origin/ci-billing-0655",
                 "gh pr create -R latark/agent-kit --base ci-billing-0655",
                 "argus — только дельта своего PR: git diff origin/ci-billing-0655...HEAD",
                 "после слияния #248 (--merge): gh pr edit <свой N> -R latark/agent-kit --base main — head тот же",
                 "конфликт с main — git merge origin/main, не rebase",
                 "#248 слит squash или rebase — «принять» на новый head не переносится",
                 "Без открытого PR: metis-0002, metis-0003 — очередь: pantheon task set metis-0001 status=todo "
                 "depends_on=metis-0009,metis-0002,metis-0003",
                 "это предупреждение, не запрет"):
        check(f"overlap_text: команда «{frag[:60]}»", frag in text, text)
    check("overlap_text: задача с открытым PR (metis-0655) — в блоке PR, не в «без открытого PR»",
          "metis-0655" not in [ln for ln in text.splitlines() if "Без открытого PR" in ln][0], text)
    check("overlap_text: пересечений нет и всё проверено — пусто", T.overlap_text("metis-0001", head, [], []) == [])
    notes = T.overlap_text("metis-0001", head, [], [], ["latark/agent-kit: gh не ответил (x)"])
    check("overlap_text: не проверенное не глушится и без пересечений", notes == ["не проверено: latark/agent-kit: gh не ответил (x)"], notes)
    nt = T.overlap_text("metis-0001", {"touches": []}, [], [])
    check("overlap_text: без touches — строка «нет touches» с командой", len(nt) == 1 and "нет touches" in nt[0]
          and "pantheon task set metis-0001 touches=" in nt[0], nt)


def cli():
    tmp, home, state, gh, env = make()
    put(home, "metis-pantheon", "metis-0001", touches=[GATE, "plugins/pantheon/lib/tasks.py"])
    put(home, "metis-pantheon", "metis-0655", status="doing", touches=[GATE, MERGE], owner="dev-b")
    put(home, "metis-pantheon", "metis-0010", status="todo", touches=["docs/"])
    put(home, "demo", "demo-0001", status="doing", touches=[GATE])
    gh_prs(gh, "latark/agent-kit", [PR248, PR250])
    gh_prs(gh, "acme/site", [dict(PR248, number=7)])
    r = pan(env, "task", "overlap", "metis-0001")
    check("task overlap: код 0, задача и PR #248 с файлом, ветка от ветки с готовой командой",
          r.returncode == 0 and "задача metis-0655 (doing, dev-b, PR #248)" in r.stdout
          and f"PR #248 latark/agent-kit (ветка ci-billing-0655, metis-0655): {GATE}" in r.stdout
          and "git switch -c metis-0001 origin/ci-billing-0655" in r.stdout and "#250" not in r.stdout, (r.stdout, r.stderr))
    check("task overlap: gh спрошен только про репозиторий своего направления, с файлами",
          "-R latark/agent-kit" in calls(gh) and "acme/site" not in calls(gh) and "files" in calls(gh), calls(gh))
    r = pan(env, "task", "overlap", "metis-0010")
    check("task overlap: пересечений нет — одна строка «пересечений … нет», код 0",
          r.returncode == 0 and "пересечений с живыми задачами направления и открытыми PR нет" in r.stdout, r.stdout)
    r = pan(env, "task", "overlap", "metis-9999")
    check("task overlap: нет задачи — код 1", r.returncode == 1 and "нет задачи" in r.stderr, r.stderr)
    r = pan(env, "task", "overlap")
    check("task overlap без id — код 2", r.returncode == 2, r.stderr)

    # gh упал: кэша нет — сказано и названа ручная команда; кэш есть — PR из кэша и строка про кэш
    open(os.path.join(gh, "fail"), "w").close()
    r = pan(env, "task", "overlap", "metis-0001")
    check("gh упал, кэша нет: «не проверено: … gh не ответил (…)» с командой для ручной проверки, задача всё равно сверена",
          r.returncode == 0 and "не проверено: latark/agent-kit: gh не ответил (error connecting" in r.stdout
          and "gh pr list -R latark/agent-kit --state open --json number,headRefName,files" in r.stdout
          and "задача metis-0655" in r.stdout and "PR #248" not in r.stdout.replace("PR #248)", ""), r.stdout)
    cache = {"fetched": T0 - 600, "open_prs": {"latark/agent-kit": [
        {"number": 248, "head": "a" * 40, "branch": "ci-billing-0655", "files": [GATE], "ids": ["metis-0655"],
         "closes": ["metis-0655"], "part": False, "core": True},
        {"number": 228, "head": "b" * 40, "ids": [], "closes": [], "part": False, "core": True}]}}
    open(os.path.join(state, "autoclose-prs.json"), "w").write(json.dumps(cache))
    r = pan(env, "task", "overlap", "metis-0001")
    check("gh упал, кэш есть: PR #248 из кэша, строка «из кэша планового прохода от …», PR без файлов назван",
          r.returncode == 0 and "из кэша планового прохода от" in r.stdout and "без списка файлов: #228" in r.stdout
          and f"PR #248 latark/agent-kit (ветка ci-billing-0655, metis-0655): {GATE}" in r.stdout, r.stdout)
    os.remove(os.path.join(gh, "fail"))

    # task set status=doing — предупреждение в stderr, запись сделана, код 0
    os.remove(os.path.join(gh, "calls.log"))
    r = pan(env, "task", "set", "metis-0001", "priority=1")
    check("task set без status=doing — gh не зовётся, предупреждения нет",
          r.returncode == 0 and calls(gh) == "" and "предупреждение" not in r.stderr, (r.stderr, calls(gh)))
    r = pan(env, "task", "set", "metis-0001", "status=doing")
    head = T.read(os.path.join(home, "directions", "metis-pantheon", "tasks", "metis-0001.md"))[0]
    check("task set status=doing: код 0, статус записан, в stderr — пересечение и выбор с командами",
          r.returncode == 0 and head.get("status") == "doing"
          and "предупреждение · metis-0001 пересекается по файлам" in r.stderr and "PR #248" in r.stderr
          and "git switch -c metis-0001 origin/ci-billing-0655" in r.stderr, (r.stdout, r.stderr))
    r = pan(env, "task", "set", "metis-0010", "status=doing")
    check("task set status=doing без пересечений — без предупреждения", r.returncode == 0 and "предупреждение" not in r.stderr,
          r.stderr)
    put(home, "metis-pantheon", "metis-0011")
    r = pan(env, "task", "set", "metis-0011", "status=doing")
    check("task set status=doing без touches — одна строка-подсказка", r.returncode == 0
          and r.stderr.count("предупреждение ·") == 1 and "нет touches" in r.stderr, r.stderr)
    put(home, "metis-pantheon", "metis-0012", touches=[MERGE])
    r = pan(env, "task", "claim", "metis-0012", "--by", "dev-c")
    check("task claim: тоже предупреждает о пересечении", r.returncode == 0 and "пересекается по файлам" in r.stderr
          and "metis-0655" in r.stderr, r.stderr)

    # policy.toml нет — сказано, что открытые PR не проверены
    tmp2, home2, _, gh2, env2 = make(policy=None)
    put(home2, "metis-pantheon", "metis-0001", touches=[GATE])
    r = pan(env2, "task", "overlap", "metis-0001")
    check("нет policy.toml: «не проверено: нет …policy.toml», gh не зовётся",
          r.returncode == 0 and "не проверено: нет" in r.stdout and "policy.toml" in r.stdout and calls(gh2) == "", r.stdout)
    tmp3, home3, _, gh3, env3 = make(policy='[merge_repos]\ndemo = ["acme/site"]\n')
    put(home3, "metis-pantheon", "metis-0001", touches=[GATE])
    r = pan(env3, "task", "overlap", "metis-0001")
    check("у направления нет [merge_repos]: сказано, gh не зовётся",
          r.returncode == 0 and "нет репозиториев в [merge_repos]" in r.stdout and calls(gh3) == "", r.stdout)


def fetch_cache():
    tmp, home, state, gh, env = make()
    # фальшивый gh отдаёт один и тот же список на merged и open: слитый без plugin.json fetch просто запомнит
    gh_prs(gh, "latark/agent-kit", [dict(PR248, headRefOid="c" * 40)])
    cache_file, state_file = os.path.join(state, "c.json"), os.path.join(state, "s.json")
    A.fetch(cache_file, state_file, T0, ["latark/agent-kit"], env=env)
    got = json.load(open(cache_file))["open_prs"]["latark/agent-kit"][0]
    check("autoclose fetch: open_prs несёт branch и files (кэш для сверки, когда gh в окне не отвечает)",
          got.get("branch") == "ci-billing-0655" and got.get("files") == [GATE, MERGE, "README.md"], got)


def main():
    pure()
    cli()
    fetch_cache()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
