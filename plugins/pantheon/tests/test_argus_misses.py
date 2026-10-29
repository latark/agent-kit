#!/usr/bin/env python3
"""Учёт пропусков argus (metis-0401): `pantheon review miss` пишет пометку только на PR с «принять» в журнале шлюза,
свод недели считает долю по классам × 1 или 2 argus, `pantheon review sample` берёт PR ядра с одним argus.
Временные HOME, PANTHEON_HOME, PANTHEON_STATE; всё убирается в конце."""
import atexit as _atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

_ROOT = tempfile.mkdtemp(prefix="misses-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIB, "run.py")
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or not detail else f"  [{detail}]"))


def rec(kind, repo, pr, who, time, sha="a" * 40):
    return {"v": 1, "kind": kind, "repo": [repo], "pr": pr, "sha": sha, "time": time,
            "by": {"agent_type": "argus", "agent_id": who, "session_id": "s"},
            "checklist": {"opened": "a", "ran": "модель: claude-opus-5-5", "unchecked": "b"}}


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="misses-test-"))
    try:
        run_all(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if all(results) else 1


def run_all(tmp):
    home, state = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    os.makedirs(os.path.join(state, "merge-gate"))
    os.makedirs(os.path.join(tmp, ".claude", "pantheon"))
    with open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w") as fh:
        fh.write('[merge_repos]\nmetis-pantheon = ["latark/agent-kit"]\nathena-x = ["acme/app"]\n')
    A, B = "latark/agent-kit", "acme/app"
    W = "2026-10-28T10:00:00"      # неделя 2026-W44
    P = "2026-10-21T10:00:00"      # неделя 2026-W43
    recs = [rec("accept", A, 50, "a1", W), rec("accept", A, 50, "a2", W),                 # два argus
            rec("reject", A, 51, "a1", W), rec("accept", A, 51, "a1", W),                 # один argus (вернул и принял)
            rec("accept", A, 52, "a1", W), rec("accept", A, 53, "a2", W),                 # ещё два PR ядра с одним
            rec("accept", B, 60, "a1", W),                                                # вне ядра, один
            rec("accept", B, 61, "a1", W), rec("reject", B, 61, "a2", "2026-11-03T10:00:00"),  # неделя — по «принять»
            rec("accept", A, 80, "a1", "2026-11-04T10:00:00"), rec("accept", A, 81, "a2", "2026-11-04T11:00:00"),
            rec("accept", A, 40, "a1", P)]                                                # прошлая неделя
    with open(os.path.join(state, "merge-gate", "records.jsonl"), "w") as fh:
        fh.write("битая\n" + "".join(json.dumps(r) + "\n" for r in recs))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": tmp, "PANTHEON_HOME": home,
           "PANTHEON_STATE": state, "PANTHEON_NO_NOTIFY": "1"}

    def pantheon(*args):
        return subprocess.run([sys.executable, "-I", RUN_PY, *args], capture_output=True, text=True, env=env, cwd=tmp)

    mpath = os.path.join(state, "argus-misses.jsonl")
    rows = lambda: [json.loads(x) for x in open(mpath)] if os.path.exists(mpath) else []

    r = pantheon("review", "miss", f"{A}#999", "--by", "argus-1", "--text", "x")
    check("miss на PR без «принять» — код 2, ничего не записано", r.returncode == 2 and "не пропуск" in r.stderr
          and not rows(), r.stderr)
    for bad in ([f"{A}#50", "--by", "x"], [f"{A}#50", "--text", "x"], [f"{A}", "--by", "x", "--text", "y"],
                [f"{A}#0", "--by", "x", "--text", "y"], [f"{A}#50", "--by", "x", "--text", "y", "--class", "что-то"],
                [f"{A}#50", "--by", "x", "--text", "--by"], [f"{A}#50", "--by", "x", "--by", "z", "--text", "y"],
                [f"{A}#50", "--by", "x", "--text", "y", "--foo", "1"], [f"{A}#50", "--by", " ", "--text", "y"]):
        r = pantheon("review", "miss", *bad)
        check(f"miss {' '.join(bad)[:45]} — код 2 и ничего не записано", r.returncode == 2 and not rows(), r.stderr)
    r = pantheon("review", "miss", f"{A}#50", "--by", "argus-7", "--text", "#192: сломал YAML tests.yml")
    row = rows()[0] if rows() else {}
    check("miss — код 0, два argus, класс ядро по репозиторию Пантеона", r.returncode == 0 and row.get("argus") == 2
          and row.get("class") == "ядро" and row.get("pr") == 50 and row.get("by") == "argus-7", r.stdout + r.stderr)
    r = pantheon("review", "miss", f"{A}#51", "--by", "argus-7", "--text", "t", "--class", "защиты")
    check("miss — один argus, класс задан флагом", r.returncode == 0 and rows()[1]["argus"] == 1
          and rows()[1]["class"] == "защиты", r.stderr)
    r = pantheon("review", "miss", f"{B}#60", "--by", "argus-7", "--text", "t")
    check("miss — вне ядра по репозиторию", r.returncode == 0 and rows()[2]["class"] == "вне ядра", r.stderr)

    spec = importlib.util.spec_from_file_location("pm", os.path.join(LIB, "metrics.py"))
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    t = M.epoch("2026-10-29T12:00:00")
    ctx = M.Ctx(home, state, tmp, t, None, {"metis-pantheon": [A], "athena-x": [B]})
    st = M.miss_stats(ctx)["2026-W44"]
    check("доля: ядро и защиты, 2 argus — 1 PR, 1 пропуск", st[("ядро и защиты", 2)] == {"prs": 1, "misses": 1, "protect": 0}, st)
    check("доля: ядро и защиты, 1 argus — 3 PR, 1 пропуск (из них защиты)",
          st[("ядро и защиты", 1)] == {"prs": 3, "misses": 1, "protect": 1}, st)
    check("доля: вне ядра, 1 argus — 2 PR (поздний «вернуть» неделю не сдвигает), 1 пропуск",
          st[("вне ядра", 1)] == {"prs": 2, "misses": 1, "protect": 0}, st)
    tbl = M.misses_table({"2026-W44": st})
    check("таблица: доли 50% и 33%", "| 2026-W44 | ядро и защиты | 1 | 3 | 1 | 33% | 1 |" in tbl
          and "| 2026-W44 | вне ядра | 1 | 2 | 1 | 50% | 0 |" in tbl, tbl)
    s = M.summary([], t, misses=M.miss_stats(ctx))
    check("свод недели содержит раздел пропусков", "## Пропуски argus" in M.week_md(s, t))
    check("свод без пометок и PR — раздела нет", "## Пропуски argus" not in M.week_md(M.summary([], t), t))

    # выборка: PR 51, 52, 53 ядра с одним argus (3 = порог) — одна группа; пропуска на прошлой неделе нет — потолок 1
    pick = M.sample_pick(ctx)
    check("sample: группа из 3 PR ядра одним запуском, потолок 1, вне ядра не берёт",
          pick["budget"] == 1 and pick["targets"] == [[(A, 51), (A, 52), (A, 53)]], pick)
    # пропуск на прошлой неделе — потолок 2
    with open(mpath, "a") as fh:
        fh.write(json.dumps({"repo": A, "pr": 40, "class": "ядро", "argus": 1, "time": P}) + "\n")
    check("sample: после недели с пропуском потолок 2", M.sample_pick(ctx)["budget"] == 2)
    # меньше порога — один последний PR; нет ядра с одним argus — пропуск недели
    ctx2 = M.Ctx(home, state, tmp, M.epoch("2026-10-22T12:00:00"), None, {"metis-pantheon": [A]})
    p2 = M.sample_pick(ctx2)
    check("sample: меньше порога — один PR", p2["targets"] == [[(A, 40)]], p2)
    ctx4 = M.Ctx(home, state, tmp, M.epoch("2026-11-05T12:00:00"), None, {"metis-pantheon": [A]})
    check("sample: два PR (меньше порога 3) — берётся один, последний", M.sample_pick(ctx4)["targets"] == [[(A, 81)]])
    ctx3 = M.Ctx(home, state, tmp, M.epoch("2026-10-29T12:00:00"), None, {"metis-pantheon": ["other/x"]})
    p3 = M.sample_pick(ctx3)
    check("sample: нет PR ядра с одним argus — неделя пропущена", p3["targets"] == [] and "пропущена" in p3["why"], p3)
    r = pantheon("review", "sample")
    check("sample из командной строки — код 0, строка недели", r.returncode == 0 and "выборка недели" in r.stdout, r.stdout)


if __name__ == "__main__":
    sys.exit(main())
