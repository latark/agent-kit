#!/usr/bin/env python3
"""Автозакрытие задач при слиянии PR и поля «Итогов пачек» (metis-0308): тик по `gh pr list --state merged` закрывает
задачу один раз (в том числе чужого направления), «часть» не закрывает, release и actual пишет сам; `--batch` без
`--mode` — отказ; check: задача пачки без mode, пустой release у закрытой по слиянию, done без closed (чинит),
review больше суток без PR, готово без приёмки после ночи. gh подделан скриптом в PATH.

Запуск: python3 -I plugins/pantheon/tests/test_autoclose.py  (код выхода 0 — все прошли)
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="autoclose-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CLI = os.path.join(LIB, "pantheon.py")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402
import autoclose as A  # noqa: E402

T0 = 1_792_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def day(t):
    return time.strftime("%Y-%m-%d", time.localtime(t))


def iso_utc(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


FAKE_GH = """#!/bin/sh
d="$FAKE_GH_DIR"; repo=""; state=""; prev=""
for a in "$@"; do
  case "$prev" in --repo) repo="$a";; --state) state="$a";; esac
  prev="$a"
done
if [ "$1 $2" = "pr list" ]; then
  f="$d/$(echo "$repo" | tr / _)-$state.json"
  [ -f "$f" ] && cat "$f" || echo "[]"
  exit 0
fi
if [ "$1 $2" = "pr diff" ]; then cat "$d/diff.txt"; exit 0; fi
exit 1
"""

DIRS = '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n\n[[direction]]\nname = "demo"\nproject = "Демо"\n'
POLICY = '[merge_repos]\nmetis-pantheon = ["latark/agent-kit"]\ndemo = ["acme/site"]\n'


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="autoclose-test-"))
    home, state, view, gh = (os.path.join(tmp, x) for x in ("pantheon", "state", "view", "gh"))
    for d in ("directions/metis-pantheon/tasks", "directions/demo/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    os.makedirs(view)
    os.makedirs(gh)
    os.makedirs(os.path.join(tmp, ".claude", "pantheon"))
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(DIRS)
    open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w", encoding="utf-8").write(POLICY)
    with open(os.path.join(gh, "gh"), "w") as fh:
        fh.write(FAKE_GH)
    os.chmod(os.path.join(gh, "gh"), 0o755)
    env = {"PATH": gh + ":" + os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0", "FAKE_GH_DIR": gh, "PANTHEON_GH": os.path.join(gh, "gh"), "TMPDIR": tmp}
    return tmp, home, state, gh, env


def pan(env, t, *a):
    return subprocess.run([PY311, "-I", CLI, *a], env=dict(env, PANTHEON_NOW=str(t)), capture_output=True, text=True,
                          timeout=120)


def new(env, home, t, direction, title, *extra):
    r = pan(env, t, "task", "new", "--direction", direction, "--title", title, *extra)
    tid, rel = (r.stdout.split() + ["", ""])[:2]
    return tid, os.path.join(home, rel), r


def text(p):
    return open(p, encoding="utf-8").read()


def put(home, direction, tid, status="doing", body="", **f):
    """Файл задачи руками: нужное время updated и поля, которых CLI не даёт."""
    head = {"type": "task", "id": tid, "title": "Задача " + tid, "status": status, "project": direction,
            "direction": direction, "owner": direction, "created": "2026-10-01", "updated": "2026-10-10T10:00:00",
            "schema_version": 1}
    head.update(f)
    p = os.path.join(home, "directions", direction, "tasks", tid + ".md")
    lines = [f"{k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, str) else v}" for k, v in head.items() if v is not None]
    open(p, "w", encoding="utf-8").write("---\n" + "\n".join(lines) + "\n---\n\n# " + head["title"] + "\n\n" + body
                                         + "\n## Журнал\n\n- 2026-10-10 10:00 — агент: создана\n")
    return p


def write_gh(gh, repo, state, prs):
    with open(os.path.join(gh, repo.replace("/", "_") + "-" + state + ".json"), "w", encoding="utf-8") as fh:
        json.dump(prs, fh)


def pr(n, branch, body, t, oid="abcdef0123456789", files=None):
    return {"number": n, "title": "t", "headRefName": branch, "body": body, "mergedAt": iso_utc(t),
            "mergeCommit": {"oid": oid}, "files": [{"path": f} for f in files or []]}


def test_unit():
    check("find_ids: ветка и тело, без повторов, порядок",
          A.find_ids("metis-0001-fix", "Закрывает metis-0001 и demo-0002") == ["metis-0001", "demo-0002"])
    check("is_part: слово «часть» — да, «участь» и «частью» — нет",
          A.is_part("Это часть 1 из 2") and not A.is_part("участь") and not A.is_part("целиком"))
    diff = ("diff --git a/plugins/pantheon/.claude-plugin/plugin.json b/plugins/pantheon/.claude-plugin/plugin.json\n"
            '-  "version": "0.11.49",\n+  "version": "0.11.50",\ndiff --git a/x.json b/x.json\n+  "version": "9"\n')
    check("plugin_versions: версия из plugin.json, чужой json не берётся", A.plugin_versions(diff) == {"pantheon": "0.11.50"})
    check("actual_text: нули и нет строки — «нет замера»",
          A.actual_text(None) == "нет замера" and A.actual_text({"usd": 0, "tokens_total": 0}) == "нет замера")
    check("actual_text: деньги, токены, часы",
          A.actual_text({"usd": 1.5, "tokens_total": 450000, "hours": 2.1}) == "$1.50 · 450k токенов · 2.1 ч")


def test_tick():
    tmp, home, state, gh, env = make()
    try:
        merged_at = T0 - 3600
        a, pa, _ = new(env, home, T0 - 7200, "metis-pantheon", "Ядро", "--status", "doing", "--next", "x")
        b, pb, _ = new(env, home, T0 - 7200, "metis-pantheon", "Часть", "--status", "doing", "--next", "x")
        c, pc, _ = new(env, home, T0 - 7200, "metis-pantheon", "Плагин", "--status", "doing", "--next", "x")
        d, pd, _ = new(env, home, T0 - 7200, "demo", "Чужое направление", "--status", "doing", "--next", "x")
        check("ids: metis-0001, metis-0002, metis-0003, demo-0001", [a, b, c, d] == ["metis-0001", "metis-0002", "metis-0003", "demo-0001"], str([a, b, c, d]))
        os.makedirs(os.path.join(home, "metrics"))
        with open(os.path.join(home, "metrics", "tasks.jsonl"), "w") as fh:
            fh.write(json.dumps({"v": 1, "id": a, "closed": day(merged_at), "usd": 1.5, "tokens_total": 450000, "hours": 2.1}) + "\n")
        write_gh(gh, "latark/agent-kit", "merged", [
            pr(7, "metis-0001-autoclose", "Закрывает задачу", merged_at),
            pr(8, "feature-x", "Только часть 1 из 2 для metis-0002", merged_at),
            pr(10, "metis-0003-v", "версия", merged_at, oid="1234567fffffff", files=["plugins/pantheon/.claude-plugin/plugin.json"])])
        write_gh(gh, "acme/site", "merged", [pr(3, "demo-0001-site", "", merged_at, oid="9999999aaaaaaa")])
        with open(os.path.join(gh, "diff.txt"), "w") as fh:
            fh.write('diff --git a/plugins/pantheon/.claude-plugin/plugin.json b/plugins/pantheon/.claude-plugin/plugin.json\n'
                     '-  "version": "0.11.49",\n+  "version": "0.11.50",\n')
        r = pan(env, T0, "tick")
        ha = T.read(pa)[0]
        check("тик: слитый PR с metis-0001 в ветке закрывает задачу", ha.get("status") == "done" and r.returncode == 0,
              r.stdout + r.stderr + text(pa)[:400])
        check("closed — день слияния", ha.get("closed") == day(merged_at), str(ha.get("closed")))
        check("release: PR → коммит", ha.get("release") == "PR #7 → abcdef0", str(ha.get("release")))
        check("actual: из metrics/tasks.jsonl", ha.get("actual") == "$1.50 · 450k токенов · 2.1 ч", str(ha.get("actual")))
        check("строка журнала с «закрыта по слиянию»", text(pa).count("закрыта по слиянию PR #7") == 1)
        hb = T.read(pb)[0]
        check("PR с «часть» в теле не закрывает", hb.get("status") == "doing" and "в теле «часть»" in text(pb), str(hb.get("status")))
        hc = T.read(pc)[0]
        check("PR с plugin.json: release — версия плагина и PR", hc.get("release") == "pantheon 0.11.50 (PR #10 → 1234567)",
              str(hc.get("release")))
        check("нет метрики — actual «нет замера»", hc.get("actual") == "нет замера", str(hc.get("actual")))
        hd = T.read(pd)[0]
        check("задача другого направления (demo) закрыта тоже", hd.get("status") == "done" and hd.get("release") == "PR #3 → 9999999"
              and hd.get("closed") == day(merged_at), str(hd))
        before = {p: text(p) for p in (pa, pb, pc, pd)}
        # владелец вернул задачу в работу; второй тик (после порога) её не трогает и ничего не дописывает
        pan(env, T0 + 100, "task", "set", a, "status=doing")
        before[pa] = text(pa)
        r = pan(env, T0 + 1500, "tick")
        after = {p: text(p) for p in (pa, pb, pc, pd)}
        check("второй тик: ни одна задача не изменилась (один раз на PR)", after == before and r.returncode == 0,
              "\n".join(p for p in after if after[p] != before[p]))
        st = json.load(open(os.path.join(state, "autoclose.json")))
        check("отметки обработанных PR в STATE", set(st["done"]) == {"latark/agent-kit#7", "latark/agent-kit#8", "latark/agent-kit#10", "acme/site#3"},
              str(st.get("done")))
    finally:
        shutil.rmtree(tmp, True)


def test_old_and_errors():
    tmp, home, state, gh, env = make()
    try:
        old = T0 - 10 * 86400
        a, pa, _ = new(env, home, T0 - 7200, "metis-pantheon", "Старое упоминание", "--status", "doing", "--next", "x")
        write_gh(gh, "latark/agent-kit", "merged", [pr(5, "x", "см. " + a, old)])
        pan(env, T0, "tick")
        check("PR старше 48 ч при первом проходе не трогает задачи (упоминание в тексте)", T.read(pa)[0].get("status") == "doing")
        # gh сломан: тик жив, задача цела
        os.remove(os.path.join(gh, "gh"))
        r = pan(env, T0 + 2000, "tick")
        check("нет gh в PATH: тик не падает", r.returncode == 0, r.stderr[-300:])
    finally:
        shutil.rmtree(tmp, True)


def test_batch_needs_mode():
    tmp, home, state, gh, env = make()
    try:
        r = pan(env, T0, "task", "new", "--direction", "demo", "--title", "Без режима", "--batch", "ночь · 1")
        check("task new --batch без --mode — отказ", r.returncode != 0 and "--mode" in r.stderr and not os.listdir(os.path.join(home, "directions", "demo", "tasks")),
              r.stdout + r.stderr)
        r = pan(env, T0, "task", "new", "--direction", "demo", "--title", "С режимом", "--batch", "ночь · 1", "--mode", "self")
        check("task new --batch --mode self — принят", r.returncode == 0, r.stderr)
        tid = r.stdout.split()[0]
        x, px, _ = new(env, home, T0, "demo", "Другая")
        r = pan(env, T0, "task", "set", x, "--batch", "ночь · 2")
        check("task set --batch без mode в шапке — отказ", r.returncode != 0 and "--mode" in r.stderr and "batch" not in text(px), r.stderr)
        r = pan(env, T0, "task", "set", x, "--batch", "ночь · 2", "--mode", "single", "--mode-why", "один файл")
        check("task set --batch --mode single --mode-why — принят", r.returncode == 0 and "mode: single" in text(px) and "mode_why:" in text(px), r.stderr)
        r = pan(env, T0, "task", "set", tid, "--batch", "ночь · 3")
        check("task set --batch, когда mode уже в шапке — принят", r.returncode == 0, r.stderr)
        y, py, _ = new(env, home, T0, "demo", "Ещё")
        s, ps, _ = new(env, home, T0, "demo", "Пачка", "--type", "story")
        r = pan(env, T0, "task", "attach", y, s)
        check("task attach задачи без mode — отказ", r.returncode != 0 and "mode" in r.stderr and "parent" not in text(py), r.stderr)
        pan(env, T0, "task", "set", y, "mode=parallel")
        r = pan(env, T0, "task", "attach", y, s)
        check("task attach задачи с mode — принят", r.returncode == 0, r.stderr)
    finally:
        shutil.rmtree(tmp, True)


def run_check(env, t):
    return pan(env, t, "check")


def test_check():
    tmp, home, state, gh, env = make()
    try:
        s, ps, _ = new(env, home, T0, "demo", "Пачка", "--type", "story", "--night", day(T0 - 3 * 86400))
        # 1. задача пачки без mode — ошибка с id
        put(home, "demo", "demo-0101", status="todo", parent=s)
        r = run_check(env, T0)
        check("check: задача пачки без mode — ОШИБКА с id", r.returncode != 0 and "ОШИБКА · demo-0101" in r.stdout and "mode" in r.stdout, r.stdout)
        put(home, "demo", "demo-0101", status="todo", parent=s, mode="self")
        r = run_check(env, T0)
        check("check: с mode — ошибки нет", "demo-0101" not in r.stdout and r.returncode == 0, r.stdout)
        # 2. закрытая по слиянию без release / actual
        put(home, "demo", "demo-0102", status="done", closed="2026-10-10", body="- закрыта по слиянию PR #4\n")
        r = run_check(env, T0)
        check("check: закрытая по слиянию без release — ОШИБКА с id",
              r.returncode != 0 and "ОШИБКА · demo-0102" in r.stdout and "release" in r.stdout and "actual" in r.stdout, r.stdout)
        put(home, "demo", "demo-0102", status="done", closed="2026-10-10", body="- закрыта по слиянию PR #4\n", release="PR #4 → abc1234", actual="нет замера")
        r = run_check(env, T0)
        check("check: с release и actual — ошибки нет", "demo-0102" not in r.stdout, r.stdout)
        # 3. done без closed — ошибка и починка из updated
        p3 = put(home, "demo", "demo-0103", status="done")
        r = run_check(env, T0)
        check("check: done без closed — ОШИБКА с id", r.returncode != 0 and "ОШИБКА · demo-0103" in r.stdout and "closed" in r.stdout, r.stdout)
        check("check: closed проставлен из updated", T.read(p3)[0].get("closed") == "2026-10-10", text(p3)[:300])
        r = run_check(env, T0)
        check("check: повтор после починки зелёный", "demo-0103" not in r.stdout and r.returncode == 0, r.stdout)
        # 4. review больше суток без PR — внимание
        put(home, "demo", "demo-0104", status="review", updated=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T0 - 30 * 3600)))
        put(home, "demo", "demo-0105", status="review", body="PR #12 открыт\n", updated=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T0 - 30 * 3600)))
        put(home, "demo", "demo-0106", status="review", updated=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T0 - 3 * 3600)))
        r = run_check(env, T0)
        check("check: review > 24 ч без PR — «внимание»", "внимание · demo-0104: review без PR" in r.stdout, r.stdout)
        check("check: review с PR в тексте и свежий review — без внимания", "demo-0105" not in r.stdout and "demo-0106" not in r.stdout, r.stdout)
        # 5. готово в пачке, ночь кончилась, приёмки нет
        put(home, "demo", "demo-0107", status="done", closed="2026-10-12", parent=s, mode="self")
        put(home, "demo", "demo-0108", status="done", closed="2026-10-12", parent=s, mode="self", acceptance="принято")
        r = run_check(env, T0)
        check("check: done в пачке после конца ночи без acceptance — «внимание»", "внимание · demo-0107: нет приёмки" in r.stdout, r.stdout)
        check("check: с acceptance — без внимания", "demo-0108" not in r.stdout, r.stdout)
        r = run_check(env, T0 - 3 * 86400 + 3600)  # ночь пачки ещё идёт
        check("check: ночь не кончилась — без «нет приёмки»", "нет приёмки" not in r.stdout, r.stdout)
    finally:
        shutil.rmtree(tmp, True)


def test_attention_on_card():
    heads = {"id": "x-0001", "type": "task", "status": "review", "updated": "2026-10-10T10:00:00"}
    ws = T.extra_attention(heads, "", {}, T0, "08:00", set())
    check("extra_attention: review без PR, а open_prs знает PR — молчит",
          T.NO_PR in ws and T.extra_attention(heads, "", {}, T0, "08:00", {"x-0001"}) == [])


def test_board_problems_unit():
    tasks = {"x-0001": ("p", {"id": "x-0001", "type": "task", "status": "done"}, ""),
             "x-0002": ("p", {"id": "x-0002", "type": "task", "status": "done", "closed": "2026-10-10"}, "")}
    errs, _ = T.board_problems(tasks, T0)
    check("board_problems: done без closed — ошибка с id, с closed — нет",
          [i for i, _ in errs] == ["x-0001"], str(errs))


def main():
    test_unit()
    test_board_problems_unit()
    test_attention_on_card()
    if PY311 is None:
        print("нет Python 3.11+ для CLI — проверки тика и check пропущены")
    else:
        test_tick()
        test_old_and_errors()
        test_batch_needs_mode()
        test_check()
    print(f"{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
