#!/usr/bin/env python3
"""Автозакрытие задач при слиянии PR и поля «Итогов пачек» (metis-0308): проход `pantheon autoclose fetch` кладёт слитые PR
в кэш, лёгкий тик по кэшу (без gh) закрывает задачу один раз и только PR из репозитория её направления, по номеру в ветке или
после «Closes/Fixes»; «См. также» не закрывает; «часть» не закрывает, release и actual пишет сам; `--batch` без
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
RUN_PY = os.path.join(os.path.dirname(CLI), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
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
echo "$@" >> "$d/calls.log"
[ -f "$d/sleep" ] && sleep "$(cat "$d/sleep")"
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
    return subprocess.run([PY311, "-I", RUN_PY, *a], env=dict(env, PANTHEON_NOW=str(t)), capture_output=True, text=True,
                          timeout=120)


def new(env, home, t, direction, title, *extra):
    r = pan(env, t, "task", "new", "--text", "тест", "--direction", direction, "--title", title, *extra)
    tid, rel = (r.stdout.split() + ["", ""])[:2]
    return tid, os.path.join(home, rel), r


def text(p):
    return open(p, encoding="utf-8").read()


def put(home, direction, tid, status="doing", body="", **f):
    """Файл задачи руками: нужное время updated и поля, которых CLI не даёт."""
    head = {"type": "task", "id": tid, "title": "Задача " + tid, "status": status, "project": {"metis-pantheon": "Пантеон", "demo": "Демо"}.get(direction, direction),
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
    check("closing_ids: ветка и «Closes/Fixes»; «См. также», «Дальше», «часть» — нет",
          A.closing_ids("metis-0001-x", "См. также metis-0002. Closes metis-0003, часть metis-0004") == ["metis-0001", "metis-0003"])
    for neg in ("Не закрывает metis-0002: остаётся п. 2b", "пока не закрываю metis-0002", "doesn't fix metis-0002",
                "not closing metis-0002", "This PR does not close metis-0002", "Не исправляет metis-0002"):
        check(f"closing_ids: отрицание не закрывает — «{neg}»", A.closing_ids("x", neg) == [], str(A.closing_ids("x", neg)))
    check("closing_ids: отрицание у одной фразы не гасит другую", A.closing_ids("x", "Не закрывает metis-0002. Closes metis-0003") == ["metis-0003"])
    check("closing_ids: «Закрывает id» после «не» в другом предложении — закрывает",
          A.closing_ids("x", "Это не мелочь. Закрывает metis-0004") == ["metis-0004"])
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
            pr(8, "feature-x", "Closes metis-0002, но только часть 1 из 2", merged_at),
            pr(10, "metis-0003-v", "версия", merged_at, oid="1234567fffffff", files=["plugins/pantheon/.claude-plugin/plugin.json"])])
        write_gh(gh, "acme/site", "merged", [pr(3, "demo-0001-site", "", merged_at, oid="9999999aaaaaaa")])
        with open(os.path.join(gh, "diff.txt"), "w") as fh:
            fh.write('diff --git a/plugins/pantheon/.claude-plugin/plugin.json b/plugins/pantheon/.claude-plugin/plugin.json\n'
                     '-  "version": "0.11.49",\n+  "version": "0.11.50",\n')
        rf = pan(env, T0, "autoclose", "fetch")
        check("fetch: код 0, gh спрошен, кэш записан", rf.returncode == 0 and os.path.exists(os.path.join(gh, "calls.log"))
              and os.path.exists(os.path.join(state, "autoclose-prs.json")), rf.stdout + rf.stderr)
        check("fetch ничего не закрывает", T.read(pa)[0].get("status") == "doing")
        os.remove(os.path.join(gh, "calls.log"))
        r = pan(env, T0, "tick")
        check("лёгкий тик не зовёт gh", not os.path.exists(os.path.join(gh, "calls.log")), text(os.path.join(gh, "calls.log"))
              if os.path.exists(os.path.join(gh, "calls.log")) else "")
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
        check("задача направления demo закрыта PR из репозитория demo", hd.get("status") == "done" and hd.get("release") == "PR #3 → 9999999"
              and hd.get("closed") == day(merged_at), str(hd))
        before = {p: text(p) for p in (pa, pb, pc, pd)}
        # владелец вернул задачу в работу; второй тик (после порога) её не трогает и ничего не дописывает
        pan(env, T0 + 100, "task", "set", a, "status=doing")
        before[pa] = text(pa)
        pan(env, T0 + 1400, "autoclose", "fetch")
        r = pan(env, T0 + 1500, "tick")
        after = {p: text(p) for p in (pa, pb, pc, pd)}
        check("второй тик: ни одна задача не изменилась (один раз на PR)", after == before and r.returncode == 0,
              "\n".join(p for p in after if after[p] != before[p]))
        st = json.load(open(os.path.join(state, "autoclose.json")))
        check("отметки обработанных PR в STATE", set(st["done"]) == {"latark/agent-kit#7", "latark/agent-kit#8", "latark/agent-kit#10", "acme/site#3"},
              str(st.get("done")))
    finally:
        shutil.rmtree(tmp, True)


class FailOnce:
    """Прокси tasks.py: task_set падает ValueError на указанной задаче, пока fail не пуст."""
    def __init__(self, fail):
        self.fail = set(fail)

    def __getattr__(self, name):
        return getattr(T, name)

    def task_set(self, pantheon, t, tid, changes, **kw):
        if tid in self.fail:
            raise ValueError("шапка не прошла проверку (проба)")
        return T.task_set(pantheon, t, tid, changes, **kw)


def run_cache(home, state, t, prs_by_repo, T_mod=None, repo_dirs=None, opened=None):
    """Кэш fetch руками и один проход run. → (log, errors)."""
    cache = os.path.join(state, "autoclose-prs.json")
    os.makedirs(state, exist_ok=True)
    A.save_state(cache, {"fetched": t, "merged": prs_by_repo, "open": opened or {}, "errors": {}})
    return A.run(home, os.path.join(state, "autoclose.json"), cache, t, repo_dirs or {"latark/agent-kit": {"metis-pantheon"}},
                 T_mod or T)


def cpr(n, branch, body, t):
    return {"number": n, "headRefName": branch, "body": body, "mergedAt": iso_utc(t), "oid": "abcdef0123456789"}


def test_rules():
    tmp, home, state, gh, env = make()
    try:
        t_old = T0 - 3600
        put(home, "metis-pantheon", "metis-0001", status="doing")
        put(home, "metis-pantheon", "metis-0002", status="doing")
        put(home, "metis-pantheon", "metis-0003", status="doing")
        put(home, "demo", "demo-0001", status="doing")
        st = lambda i: T.read(os.path.join(home, "directions", i.split("-")[0].replace("metis", "metis-pantheon"), "tasks", i + ".md"))[0].get("status")
        # чужой репозиторий: PR acme/site (направление demo) с id задачи metis-pantheon в ветке
        log, errs = run_cache(home, state, T0, {"acme/site": [cpr(3, "metis-0001-x", "", t_old)]}, repo_dirs={"acme/site": {"demo"}})
        check("PR чужого репозитория не закрывает задачу другого направления", st("metis-0001") == "doing" and not log, str(log))
        # «См. также» и «Дальше» — упоминание, не закрытие
        log, errs = run_cache(home, state, T0 + 1, {"latark/agent-kit": [
            cpr(9, "metis-0999-x", "См. также metis-0002. Дальше — metis-0003 (не в этом PR)", t_old)]})
        check("«См. также» и «Дальше» в теле не закрывают", st("metis-0002") == "doing" and st("metis-0003") == "doing" and not log, str(log))
        # Closes — закрывает
        log, errs = run_cache(home, state, T0 + 2, {"latark/agent-kit": [cpr(10, "feature", "Closes metis-0002\nfixes: metis-0003", t_old)]})
        check("«Closes id» и «fixes: id» в теле закрывают", st("metis-0002") == "done" and st("metis-0003") == "done", str(log) + str(errs))
        # PR своего репозитория закрывает только задачи своего направления
        log, errs = run_cache(home, state, T0 + 3, {"latark/agent-kit": [cpr(11, "demo-0001-x", "", t_old)]})
        check("PR репозитория metis-pantheon не закрывает задачу demo", st("demo-0001") == "doing" and not log, str(log))
    finally:
        shutil.rmtree(tmp, True)


def test_reopen_and_eviction():
    tmp, home, state, gh, env = make()
    try:
        pa = put(home, "metis-pantheon", "metis-0001", status="doing")
        prs = [cpr(1, "metis-0001-x", "", T0 - 3600)]
        log, _ = run_cache(home, state, T0, {"latark/agent-kit": prs})
        check("закрыта по слиянию", T.read(pa)[0].get("status") == "done" and len(log) == 1)
        # владелец вернул, отметки обработанных PR вытеснены — второй раз не закрываем (смотрим журнал задачи)
        T.task_set(home, T0 + 10, "metis-0001", {"status": "doing"}, actor="владелец")
        st = A.load_state(os.path.join(state, "autoclose.json"))
        st["done"] = {}
        A.save_state(os.path.join(state, "autoclose.json"), st)
        log, _ = run_cache(home, state, T0 + 1200, {"latark/agent-kit": prs})
        check("переоткрытую задачу тем же PR второй раз не закрывает",
              T.read(pa)[0].get("status") == "doing" and text(pa).count("закрыта по слиянию PR #1") == 1 and not log, text(pa)[-400:])
        # «часть» не задваивается после вытеснения
        pb = put(home, "metis-pantheon", "metis-0002", status="doing")
        part = [cpr(2, "metis-0002-x", "часть 1", T0 - 3600)]
        run_cache(home, state, T0 + 1300, {"latark/agent-kit": part})
        st = A.load_state(os.path.join(state, "autoclose.json"))
        st["done"] = {}
        A.save_state(os.path.join(state, "autoclose.json"), st)
        run_cache(home, state, T0 + 1400, {"latark/agent-kit": part})
        check("строка «часть» в журнале не задваивается", text(pb).count("в теле «часть»") == 1, text(pb)[-400:])
    finally:
        shutil.rmtree(tmp, True)


def test_mutants():
    tmp, home, state, gh, env = make()
    try:
        # сбой посреди прохода: на одной задаче PR task_set падает — PR не отмечен, следующий проход дозакрывает
        pa = put(home, "metis-pantheon", "metis-0001", status="doing")
        pb = put(home, "metis-pantheon", "metis-0002", status="doing")
        prs = [cpr(5, "metis-0001-x", "Closes metis-0002", T0 - 3600)]
        log, errs = run_cache(home, state, T0, {"latark/agent-kit": prs}, T_mod=FailOnce(["metis-0002"]))
        d = A.load_state(os.path.join(state, "autoclose.json")).get("done") or {}
        check("сбой на одной задаче PR: PR не отмечен обработанным, ошибка названа",
              "latark/agent-kit#5" not in d and "metis-0002" in str(errs) and T.read(pa)[0].get("status") == "done"
              and T.read(pb)[0].get("status") == "doing", str(d) + str(errs))
        A.save_state(os.path.join(state, "autoclose-prs.json"), {})
        log, errs = run_cache(home, state, T0 + 60, {"latark/agent-kit": prs})
        d = A.load_state(os.path.join(state, "autoclose.json")).get("done") or {}
        check("следующий проход дозакрывает, первая задача не задвоена",
              T.read(pb)[0].get("status") == "done" and "latark/agent-kit#5" in d and text(pa).count("закрыта по слиянию PR #5") == 1, text(pa)[-300:])
        # сбой не ValueError (OSError) посреди прохода: тот же кэш прочитается заново, задача дозакроется
        pf = put(home, "metis-pantheon", "metis-0006", status="doing")

        class Boom(FailOnce):
            def task_set(self, *a, **kw):
                raise OSError("диск (проба)")
        prs2 = [cpr(8, "metis-0006-x", "", T0 - 3600)]
        try:
            run_cache(home, state, T0 + 90, {"latark/agent-kit": prs2}, T_mod=Boom([]))
        except OSError:
            pass
        run_cache(home, state, T0 + 90, {"latark/agent-kit": prs2})  # тот же кэш (то же время fetch)
        check("сбой OSError посреди прохода: следующий проход по тому же кэшу закрывает", T.read(pf)[0].get("status") == "done"
              and text(pf).count("закрыта по слиянию PR #8") == 1, text(pf)[-300:])
        # слияние за сутки до тика: closed — день слияния, а не день тика
        pc = put(home, "metis-pantheon", "metis-0003", status="doing")
        merged = T0 - 30 * 3600
        run_cache(home, state, T0 + 120, {"latark/agent-kit": [cpr(6, "metis-0003-x", "", merged)]})
        check("closed — день слияния, не день тика", day(merged) != day(T0) and T.read(pc)[0].get("closed") == day(merged),
              str(T.read(pc)[0].get("closed")))
        # dropped и done не воскрешаются
        pd = put(home, "metis-pantheon", "metis-0004", status="dropped", closed="2026-10-05")
        pe = put(home, "metis-pantheon", "metis-0005", status="done", closed="2026-10-05")
        before = (text(pd), text(pe))
        run_cache(home, state, T0 + 180, {"latark/agent-kit": [cpr(7, "metis-0004-x", "Closes metis-0005", T0 - 3600)]})
        check("задачи dropped и done слитым PR не меняются", (text(pd), text(pe)) == before and
              T.read(pd)[0].get("status") == "dropped", "")
    finally:
        shutil.rmtree(tmp, True)


def test_fetch_budget():
    tmp, home, state, gh, env = make()
    try:
        open(os.path.join(gh, "sleep"), "w").write("5")
        t0 = time.monotonic()
        errs = A.fetch(os.path.join(state, "p.json"), os.path.join(state, "s.json"), T0, ["a/b", "c/d", "e/f"],
                       env=dict(env), budget=2.5)
        el = time.monotonic() - t0
        check("fetch: предел времени на весь проход, остаток репозиториев — ошибка", el < 4.5 and len(errs) == 3, f"{el:.1f} c {errs}")
        check("fetch: кэш записан даже при сбое", A.load_state(os.path.join(state, "p.json")).get("errors") == errs)
    finally:
        shutil.rmtree(tmp, True)


def test_former_heads():
    """metis-0726: кэш помнит бывшие head ещё открытых PR — по ним outside снимает заявку test на устаревший head."""
    h = lambda c: c * 40  # noqa: E731
    prev = {"open_prs": {"a/b": [{"number": 1, "head": h("1")}, {"number": 2, "head": h("2")}], "c/d": []},
            "old_heads": {"a/b": {h("0"): 1, h("9"): 3}, "e/f": {h("5"): 4}}}
    now = {"a/b": [{"number": 1, "head": h("a")}, {"number": 2, "head": h("2")}], "c/d": []}
    got = A.former_heads(prev, now)
    check("former_heads: прошлый head PR #1 и его давний бывший — в old_heads; head PR #2 не менялся — нет; PR #3 закрыт — нет",
          got.get("a/b") == {h("0"): 1, h("1"): 1}, got)
    check("former_heads: репозиторий, про который gh не ответил (нет в open_prs), держит прошлые", got.get("e/f") == {h("5"): 4}, got)
    check("former_heads: нет бывших — репозитория нет", "c/d" not in got, got)
    check("former_heads: head вернулся (force-push назад) — уже не бывший",
          A.former_heads({"old_heads": {"a/b": {h("1"): 1}}}, {"a/b": [{"number": 1, "head": h("1")}]}) == {})
    check("former_heads: старый кэш без old_heads и мусор — не падает",
          A.former_heads({}, now) == {} and A.former_heads(None, now) == {} and A.former_heads({"old_heads": [1]}, now) == {})
    many = A.former_heads({"old_heads": {"a/b": {f"{i:040x}": 1 for i in range(A.OLD_HEADS_KEEP + 5)}}}, now)
    check("former_heads: не больше OLD_HEADS_KEEP на репозиторий, уходят старые",
          len(many["a/b"]) == A.OLD_HEADS_KEEP and f"{0:040x}" not in many["a/b"], len(many["a/b"]))
    tmp, home, state, gh, env = make()
    try:
        cf = os.path.join(state, "p.json")
        write_gh(gh, "a/b", "merged", [])
        write_gh(gh, "a/b", "open", [{"number": 1, "headRefName": "x", "headRefOid": h("1"), "body": "", "files": []}])
        A.fetch(cf, os.path.join(state, "s.json"), T0, ["a/b"], env=dict(env))
        write_gh(gh, "a/b", "open", [{"number": 1, "headRefName": "x", "headRefOid": h("2"), "body": "", "files": []}])
        A.fetch(cf, os.path.join(state, "s.json"), T0 + 600, ["a/b"], env=dict(env))
        c = A.load_state(cf)
        check("fetch: новый head PR — прошлый в old_heads кэша", c.get("old_heads") == {"a/b": {h("1"): 1}}
              and c["open_prs"]["a/b"][0]["head"] == h("2"), c.get("old_heads"))
    finally:
        shutil.rmtree(tmp, True)


def test_old_and_errors():
    tmp, home, state, gh, env = make()
    try:
        old = T0 - 10 * 86400
        a, pa, _ = new(env, home, T0 - 7200, "metis-pantheon", "Старое упоминание", "--status", "doing", "--next", "x")
        write_gh(gh, "latark/agent-kit", "merged", [pr(5, a + "-x", "", old)])
        pan(env, T0, "autoclose", "fetch")
        pan(env, T0, "tick")
        check("PR старше 48 ч при первом проходе не трогает задачи (номер в ветке, слияние 10 дней назад)", T.read(pa)[0].get("status") == "doing")
        # gh сломан: тик жив, задача цела
        os.remove(os.path.join(gh, "gh"))
        r = pan(env, T0 + 2000, "autoclose", "fetch")
        r2 = pan(env, T0 + 2000, "tick")
        check("нет gh в PATH: fetch и тик не падают", r.returncode == 0 and r2.returncode == 0, r.stderr[-300:] + r2.stderr[-300:])
    finally:
        shutil.rmtree(tmp, True)


def test_off_warning():
    tmp, home, state, gh, env = make()
    try:
        r = pan(env, T0, "tick")
        c = run_check(env, T0)
        check("нет кэша: тик жив, check предупреждает «нет строки autoclose-fetch»",
              r.returncode == 0 and c.returncode == 0 and "автозакрытие выключено: нет строки autoclose-fetch в schedule.toml" in c.stdout,
              r.stderr[-300:] + c.stdout)
        pan(env, T0, "autoclose", "fetch")
        c = run_check(env, T0 + 600)
        check("свежий кэш: предупреждения нет", "автозакрытие выключено" not in c.stdout, c.stdout)
        r = pan(env, T0 + 7200, "tick")
        c = run_check(env, T0 + 7200)
        check("кэш старше часа: тик жив, check предупреждает «кэш старше часа»",
              r.returncode == 0 and c.returncode == 0 and "автозакрытие выключено: кэш старше часа" in c.stdout, r.stderr[-300:] + c.stdout)
    finally:
        shutil.rmtree(tmp, True)


def test_batch_needs_mode():
    tmp, home, state, gh, env = make()
    try:
        r = pan(env, T0, "task", "new", "--text", "тест", "--direction", "demo", "--title", "Без режима", "--batch", "ночь · 1")
        check("task new --batch без --mode — отказ", r.returncode != 0 and "--mode" in r.stderr and not os.listdir(os.path.join(home, "directions", "demo", "tasks")),
              r.stdout + r.stderr)
        r = pan(env, T0, "task", "new", "--text", "тест", "--direction", "demo", "--title", "С режимом", "--batch", "ночь · 1", "--mode", "self")
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
        s, ps, _ = new(env, home, T0, "demo", "Пачка", "--type", "story", "--done-when", "пункт")
        r = pan(env, T0, "task", "attach", y, s)
        check("task attach задачи без mode — отказ", r.returncode != 0 and "mode" in r.stderr and "parent" not in text(py), r.stderr)
        pan(env, T0, "task", "set", y, "mode=parallel")
        r = pan(env, T0, "task", "attach", y, s)
        check("task attach задачи с mode — принят", r.returncode == 0, r.stderr)
        z, pz, _ = new(env, home, T0, "demo", "Без режима")
        r = pan(env, T0, "task", "set", z, f"parent={s}")
        check("task set parent=<пачка> без mode — отказ", r.returncode != 0 and "mode" in r.stderr and "parent" not in text(pz), r.stderr)
        r = pan(env, T0, "task", "set", z, f"parent={s}", "mode=self")
        check("task set parent=<пачка> вместе с mode — принят", r.returncode == 0 and "parent" in text(pz), r.stderr)
        n_before = len(os.listdir(os.path.join(home, "directions", "demo", "tasks")))
        r = pan(env, T0, "task", "new", "--text", "тест", "--direction", "demo", "--title", "Новая в пачку", "--parent", s)
        check("task new --parent <пачка> без mode — отказ", r.returncode != 0 and "mode" in r.stderr
              and len(os.listdir(os.path.join(home, "directions", "demo", "tasks"))) == n_before, r.stdout + r.stderr)
        r = pan(env, T0, "task", "new", "--text", "тест", "--direction", "demo", "--title", "Новая в пачку", "--parent", s, "--mode", "self")
        check("task new --parent <пачка> с mode — принят", r.returncode == 0, r.stderr)
    finally:
        shutil.rmtree(tmp, True)


def run_check(env, t):
    return pan(env, t, "check")


def test_check():
    tmp, home, state, gh, env = make()
    try:
        s, ps, _ = new(env, home, T0, "demo", "Пачка", "--type", "story", "--done-when", "пункт", "--night", day(T0 - 3 * 86400))
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
        own = "\n".join(x for x in r.stdout.splitlines() if not x.startswith("внимание · застой:"))  # сводка застоя (0583) — своя строка
        check("check: review с PR в тексте и свежий review — без внимания", "demo-0105" not in own and "demo-0106" not in own, r.stdout)
        check("check: застой doing/review > 2 сут — одна строка сводки с id (0583)",
              sum(x.startswith("внимание · застой: ") for x in r.stdout.splitlines()) == 1 and "demo-0104" in r.stdout.split("внимание · застой:")[1].split("\n")[0],
              r.stdout)
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


def test_close_criteria():
    """metis-0503: слитый PR и ручной done не закрывают задачу с неотмеченными «Готово, когда» (случай metis-0421)."""
    tmp, home, state, gh, env = make()
    try:
        two = "Готово, когда:\n- [x] сделано одно\n- [ ] сделано второе\n"
        pa = put(home, "metis-pantheon", "metis-0010", body=two, created="2026-10-27")
        pb = put(home, "metis-pantheon", "metis-0011", body=two, created="2026-10-26")
        pc = put(home, "metis-pantheon", "metis-0012", body="Готово, когда:\n- [x] а\n- [x] б\n", created="2026-10-27")
        pd = put(home, "metis-pantheon", "metis-0013", body=two, created="2026-10-27")
        prs = [cpr(1, "metis-0010-x", "", T0 - 3600), cpr(2, "metis-0011-x", "", T0 - 3600),
               cpr(3, "metis-0012-x", "", T0 - 3600), cpr(4, "metis-0013-x", "часть 1", T0 - 3600)]
        log, errs = run_cache(home, state, T0, {"latark/agent-kit": prs})
        ha = T.read(pa)[0]
        check("0421: PR без «часть», 1 из 2 пунктов → review, не done", ha.get("status") == "review" and not ha.get("closed"), str(ha))
        check("0421: в журнале «слит, неотмечено 1»", "слит, неотмечено 1" in text(pa), text(pa)[-300:])
        check("задача от 26.10 закрывается как раньше", T.read(pb)[0].get("status") == "done", str(log))
        check("все пункты отмечены → done", T.read(pc)[0].get("status") == "done")
        check("«часть» остаётся как есть", T.read(pd)[0].get("status") == "doing" and "в теле «часть»" in text(pd))
        run_cache(home, state, T0 + 10, {"latark/agent-kit": prs})
        check("повторный проход не задваивает строку", text(pa).count("слит, неотмечено 1") == 1)
        # ручной done
        pe = put(home, "metis-pantheon", "metis-0014", body=two, created="2026-10-27")
        try:
            T.task_set(home, T0, "metis-0014", {"status": "done"})
            err = ""
        except ValueError as e:
            err = str(e)
        check("ручной done с неотмеченными → отказ «неотмечено 1»", "неотмечено 1" in err and "pantheon task split" in err
              and T.read(pe)[0].get("status") == "doing", err)
        try:
            T.task_set(home, T0, "metis-0014", {"status": "done"}, force="  ")
            err = ""
        except ValueError as e:
            err = str(e)
        check("--force с пустой причиной → отказ", "причина" in err and T.read(pe)[0].get("status") == "doing", err)
        T.task_set(home, T0, "metis-0014", {"status": "done"}, force="второй пункт отменён владельцем")
        check("--force с причиной → done и строка в журнале", T.read(pe)[0].get("status") == "done"
              and "--force: второй пункт отменён владельцем" in text(pe), text(pe)[-300:])
        pf = put(home, "metis-pantheon", "metis-0015", body=two, created="2026-10-26")
        T.task_set(home, T0, "metis-0015", {"status": "done"})
        check("задача от 26.10 закрывается вручную без --force", T.read(pf)[0].get("status") == "done")
        p16 = put(home, "metis-pantheon", "metis-0016", body="Готово, когда:\n- [ ] " + T.DONE_WHEN_HINT + "\n", created="2026-10-27")
        try:
            T.task_set(home, T0, "metis-0016", {"status": "done"})
            err = ""
        except ValueError as e:
            err = str(e)
        check("заглушка-подсказка одна — не пункт, ручной done проходит (metis-0712)", err == "" and T.read(p16)[0].get("status") == "done", err)
        p16b = put(home, "metis-pantheon", "metis-0020", body="Готово, когда:\n- [ ] " + T.DONE_WHEN_HINT + "\n- [ ] настоящий\n", created="2026-10-27")
        try:
            T.task_set(home, T0, "metis-0020", {"status": "done"})
            err = ""
        except ValueError as e:
            err = str(e)
        check("заглушка рядом с настоящим пунктом: «неотмечено 1» без заглушки",
              "неотмечено 1 " in err and T.read(p16b)[0].get("status") != "done", err)
        p16c = put(home, "metis-pantheon", "metis-0021", body="Готово, когда:\n- [ ] " + T.DONE_WHEN_HINT + " ещё\n", created="2026-10-27")
        check("похожий, но не дословный текст — пункт", T.unchecked_criteria(*T.read(p16c)) == 1)
        pq = put(home, "metis-pantheon", "metis-0022", body="Готово, когда:\n- [ ] " + T.DONE_WHEN_HINT + "\n", created="2026-10-27")
        pr2 = put(home, "metis-pantheon", "metis-0023", body="Готово, когда:\n- [ ] " + T.DONE_WHEN_HINT + "\n- [ ] настоящий\n", created="2026-10-27")
        run_cache(home, state, T0, {"latark/agent-kit": [cpr(11, "metis-0022-x", "", T0 - 3600), cpr(12, "metis-0023-x", "", T0 - 3600)]})
        check("слитый PR, только заглушка → done (metis-0712)", T.read(pq)[0].get("status") == "done", text(pq)[-300:])
        check("слитый PR, заглушка + настоящий → review «неотмечено 1»", T.read(pr2)[0].get("status") == "review"
              and "слит, неотмечено 1" in text(pr2), text(pr2)[-300:])
        # остаток: task split пишет result, по нему done проходит без --force
        ph = put(home, "metis-pantheon", "metis-0017", body=two, created="2026-10-27")
        nid, _ = T.task_split(home, T0, "metis-0017", "Второе")
        check("task split пишет result со ссылкой на остаток", nid in str(T.read(ph)[0].get("result")), str(T.read(ph)[0].get("result")))
        T.task_set(home, T0, "metis-0017", {"status": "done"})
        check("после split ручной done проходит без --force", T.read(ph)[0].get("status") == "done")
        put(home, "metis-pantheon", "metis-0018", body=two, created="2026-10-27")
        try:
            T.task_set(home, T0, "metis-0018", {"status": "done", "result": "остаток в metis-9999"})
            err = ""
        except ValueError as e:
            err = str(e)
        check("result со ссылкой на чужой id не обходит правило", "неотмечено" in err, err)
        p19 = put(home, "metis-pantheon", "metis-0019", body=two, created="2026-10-27")
        r = pan(env, T0, "task", "set", "metis-0019", "status=done")
        check("CLI: task set status=done → код не 0 и «неотмечено 1»", r.returncode != 0 and "неотмечено 1" in r.stdout + r.stderr,
              f"{r.returncode} {r.stdout}{r.stderr}")
        r = pan(env, T0, "task", "set", "metis-0019", "status=done", "--force", "отменён")
        check("CLI: --force причина → код 0, done", r.returncode == 0 and T.read(p19)[0].get("status") == "done",
              f"{r.returncode} {r.stdout}{r.stderr}")
    finally:
        shutil.rmtree(tmp, True)


def test_lists_and_checked():
    """metis-0583: «Closes» со списком закрывает каждую задачу; без Closes задачу с отмеченными пунктами и слитым PR в
    журнале закрывает close_checked; неотмеченные, без пунктов, с открытым PR, PR чужого репозитория — нет."""
    ids = lambda b: A.closing_ids("simplify-1-windows", b)  # noqa: E731
    check("Closes списком: полные id, «и», «;», «and»", ids("Closes metis-0522, metis-0534 и metis-0535; metis-0536 and demo-0001")
          == ["metis-0522", "metis-0534", "metis-0535", "metis-0536", "demo-0001"], str(ids("Closes metis-0522, metis-0534 и metis-0535")))
    check("Closes списком: номер без префикса берёт префикс прошлого", ids("Closes metis-0522, 0534, 0535 и 0536.")
          == ["metis-0522", "metis-0534", "metis-0535", "metis-0536"], str(ids("Closes metis-0522, 0534, 0535 и 0536.")))
    check("Closes списком: префикс берётся у ближайшего полного id", ids("Closes demo-0001, 0002 и metis-0003, 0004")
          == ["demo-0001", "demo-0002", "metis-0003", "metis-0004"], str(ids("Closes demo-0001, 0002 и metis-0003, 0004")))
    check("Closes списком: «100 тестов», «1500 строк», «часть metis-…», «и это» — не номера",
          ids("Closes metis-0522, 100 тестов") == ["metis-0522"] and ids("Closes metis-0522, 100.") == ["metis-0522"] and ids("Closes metis-0522, 1500 строк") == ["metis-0522"]
          and ids("Closes metis-0522, часть metis-0004") == ["metis-0522"] and ids("Closes metis-0522 и это всё") == ["metis-0522"],
          str(ids("Closes metis-0522, 1500 строк")))
    check("Closes списком: «См. также a, b» — по-прежнему не закрывает; отрицание гасит весь список",
          ids("См. также metis-0522, metis-0534") == [] and ids("Не закрывает metis-0522, metis-0534") == [])
    check("Список PR #163 (без Closes) — ничего не закрывает", ids("PR 1 «окна»: metis-0522, 0534, 0535, 0536.") == [])
    tmp, home, state, gh, env = make()
    try:
        st = lambda i: T.read(os.path.join(home, "directions", "metis-pantheon", "tasks", i + ".md"))[0]  # noqa: E731
        for i in ("metis-0030", "metis-0031", "metis-0032"):
            put(home, "metis-pantheon", i, status="doing")
        log, errs = run_cache(home, state, T0, {"latark/agent-kit": [cpr(30, "simplify-2", "Closes metis-0030, 0031 и metis-0032", T0 - 3600)]})
        check("слитый PR «Closes a, b и c» под общей веткой закрывает все три",
              all(st(i).get("status") == "done" for i in ("metis-0030", "metis-0031", "metis-0032")), str(log) + str(errs))
        ok_body = "Готово, когда:\n- [x] сделано одно\n- [x] сделано второе\n"
        jr = "\n## Журнал\n\n- 2026-10-27 21:25 — агент: PR #40 слит владельцем (squash 1a1f77a)\n"
        mk = lambda i, body, **f: put(home, "metis-pantheon", i, body=body.replace("\n## Журнал", "") , created="2026-10-27", **f)  # noqa: E731

        def with_journal(i, body, extra=jr, **f):
            p = mk(i, body, **f)
            open(p, "a", encoding="utf-8").write(extra.split("## Журнал\n\n")[1])
            return p
        pa = with_journal("metis-0040", ok_body)
        pb = with_journal("metis-0041", "Готово, когда:\n- [x] одно\n- [ ] второе\n")
        pc = with_journal("metis-0042", "Без чек-листа.\n")
        pd = with_journal("metis-0043", ok_body)
        pe = with_journal("metis-0044", ok_body, extra="## Журнал\n\n- 2026-10-27 21:25 — агент: PR #41 слит\n")
        pf = with_journal("metis-0045", ok_body, status="review")
        pg = with_journal("metis-0046", ok_body, status="todo")
        ph = with_journal("metis-0047", ok_body, extra="## Журнал\n\n- 2026-10-27 10:00 — агент: PR #42 слит\n- 2026-10-27 11:00 — агент: доделка, PR #43 слит\n")
        prs = {"latark/agent-kit": [cpr(40, "simplify-1-windows", "PR 1: metis-0040, 0041", T0 - 7200),
                                    cpr(43, "b", "", T0 - 1800), cpr(42, "a", "", T0 - 9000)],
               "acme/site": [cpr(41, "x", "", T0 - 7200)]}
        cache = os.path.join(state, "autoclose-prs.json")
        A.save_state(cache, {"fetched": T0 + 100, "merged": prs, "open": {"latark/agent-kit": ["metis-0043"]}, "errors": {}})
        log, errs = A.run(home, os.path.join(state, "autoclose.json"), cache, T0 + 100,
                          {"latark/agent-kit": {"metis-pantheon"}, "acme/site": {"demo"}}, T)
        ha = T.read(pa)[0]
        check("все пункты отмечены, PR #40 из журнала слит → done, closed, release, строка в журнале",
              ha.get("status") == "done" and ha.get("closed") == day(T0 - 7200) and ha.get("release") == "PR #40 → abcdef0"
              and "закрыта по слиянию PR #40 (latark/agent-kit) → abcdef0" in text(pa) and A.CHECKED_WHY in text(pa)
              and ha.get("actual") == A.NO_METRIC, str(ha) + text(pa)[-300:])
        check("в журнале два слитых PR — закрывает последний по слиянию", "закрыта по слиянию PR #43" in text(ph)
              and T.read(ph)[0].get("closed") == day(T0 - 1800), text(ph)[-300:])
        check("review со всеми пунктами и слитым PR → done", T.read(pf)[0].get("status") == "done", text(pf)[-200:])
        check("неотмеченный пункт, нет чек-листа, открытый PR, PR чужого репозитория, todo — не трогаем",
              [T.read(p)[0].get("status") for p in (pb, pc, pd, pe, pg)] == ["doing", "doing", "doing", "doing", "todo"],
              str([T.read(p)[0].get("status") for p in (pb, pc, pd, pe, pg)]) + str(log))
        T.task_set(home, T0 + 200, "metis-0040", {"status": "doing"}, actor="владелец")
        A.save_state(cache, {"fetched": T0 + 300, "merged": prs, "open": {}, "errors": {}})
        A.run(home, os.path.join(state, "autoclose.json"), cache, T0 + 300, {"latark/agent-kit": {"metis-pantheon"}}, T)
        check("владелец вернул в работу — тем же PR второй раз не закрываем; открытый PR ушёл — закрываем",
              T.read(pa)[0].get("status") == "doing" and text(pa).count("закрыта по слиянию PR #40") == 1
              and T.read(pd)[0].get("status") == "done", text(pa)[-300:])
        # «часть» в теле PR из журнала: все пункты отмечены, но задача остаётся открытой, строка в журнал один раз
        pk = with_journal("metis-0050", ok_body, extra="## Журнал\n\n- 2026-10-27 21:25 — агент: PR #46 слит\n")
        prs3 = {"latark/agent-kit": [cpr(46, "e", "PR 1 из 2: часть задачи", T0 - 400)]}
        for k in (500, 600):
            A.save_state(cache, {"fetched": T0 + k, "merged": prs3, "open": {}, "errors": {}})
            A.run(home, os.path.join(state, "autoclose.json"), cache, T0 + k, {"latark/agent-kit": {"metis-pantheon"}}, T)
        check("close_checked: «часть» в теле PR — задача не закрыта, строка в журнале одна",
              T.read(pk)[0].get("status") == "doing"
              and text(pk).count("PR #46 (latark/agent-kit) слит, в теле «часть» — задача не закрыта") == 1, text(pk)[-300:])
        # сбой записи одной задачи (шапка не прошла проверку) — ошибка в errors, проход идёт дальше
        pi =with_journal("metis-0048", ok_body, extra="## Журнал\n\n- 2026-10-27 21:25 — агент: PR #44 слит\n")
        pj = with_journal("metis-0049", ok_body, extra="## Журнал\n\n- 2026-10-27 21:25 — агент: PR #45 слит\n")
        prs2 = {"latark/agent-kit": [cpr(44, "c", "", T0 - 600), cpr(45, "d", "", T0 - 500)]}
        A.save_state(cache, {"fetched": T0 + 400, "merged": prs2, "open": {}, "errors": {}})
        log, errs = A.run(home, os.path.join(state, "autoclose.json"), cache, T0 + 400,
                          {"latark/agent-kit": {"metis-pantheon"}}, FailOnce({"metis-0048"}))
        check("все пункты отмечены: сбой записи одной задачи — в errors, соседняя закрыта",
              "metis-0048" in errs.get("latark/agent-kit#44", "") and T.read(pi)[0].get("status") == "doing"
              and T.read(pj)[0].get("status") == "done", str(errs) + str(log))
    finally:
        shutil.rmtree(tmp, True)


def main():
    test_lists_and_checked()
    test_unit()
    test_board_problems_unit()
    test_attention_on_card()
    test_close_criteria()
    test_tick()
    test_old_and_errors()
    test_rules()
    test_reopen_and_eviction()
    test_mutants()
    test_fetch_budget()
    test_former_heads()
    test_batch_needs_mode()
    test_off_warning()
    test_check()
    print(f"{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
