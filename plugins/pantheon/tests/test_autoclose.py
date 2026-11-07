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
            pr(10, "metis-0003-v", "версия", merged_at, oid="1234567fffffff",
               files=[None, "plugins/pantheon/.claude-plugin/plugin.json"])])  # path null: fetch не падает (0674)
        write_gh(gh, "acme/site", "merged", [pr(3, "demo-0001-site", "", merged_at, oid="9999999aaaaaaa")])
        with open(os.path.join(gh, "diff.txt"), "w") as fh:
            fh.write('diff --git a/plugins/pantheon/.claude-plugin/plugin.json b/plugins/pantheon/.claude-plugin/plugin.json\n'
                     '-  "version": "0.11.49",\n+  "version": "0.11.50",\n')
        rf = pan(env, T0, "autoclose", "fetch")
        check("fetch: код 0, gh спрошен, кэш записан", rf.returncode == 0 and os.path.exists(os.path.join(gh, "calls.log"))
              and os.path.exists(os.path.join(state, "autoclose-prs.json")), rf.stdout + rf.stderr)
        ha = T.read(pa)[0]
        # metis-0868: закрытие — в том же проходе, сразу после fetch, а не на следующем тике
        check("fetch: слитый PR с metis-0001 в ветке закрывает задачу в том же проходе", ha.get("status") == "done",
              rf.stdout + rf.stderr + text(pa)[:400])
        fetched = {p: text(p) for p in (pa, pb, pc, pd)}
        os.remove(os.path.join(gh, "calls.log"))
        r = pan(env, T0, "tick")
        check("лёгкий тик не зовёт gh", not os.path.exists(os.path.join(gh, "calls.log")), text(os.path.join(gh, "calls.log"))
              if os.path.exists(os.path.join(gh, "calls.log")) else "")
        check("тик после fetch: закрывать уже нечего, задачи не изменились",
              r.returncode == 0 and {p: text(p) for p in (pa, pb, pc, pd)} == fetched, r.stdout + r.stderr)
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


def test_fetch_same_pass_primary_only():
    """metis-0868, п. 1: fetch закрывает в том же проходе только на главном Mac (как тик); карточки закрыты — view
    и доска сразу (задачи расписания), а не через минуту."""
    tmp, home, state, gh, env = make()
    try:
        open(os.path.join(home, "schedule.toml"), "w").write(
            'primary_host = "mac-a"\n\n[[job]]\nname = "view"\ncommand = "pantheon view --quiet"\nevery = "tick"\n')
        a, pa, _ = new(env, home, T0 - 7200, "metis-pantheon", "Ядро", "--status", "doing", "--next", "x")
        write_gh(gh, "latark/agent-kit", "merged", [pr(7, "feature", "Closes metis-0001", T0 - 3600)])
        rb = pan(dict(env, PANTHEON_HOST="mac-b", PANTHEON_REFRESH="1"), T0, "autoclose", "fetch")
        dry = os.path.join(state, "dryrun.log")
        check("fetch не на главном Mac: кэш записан, задача не закрыта (закрывает главный)",
              rb.returncode == 0 and T.read(pa)[0].get("status") == "doing" and not os.path.exists(dry), rb.stdout + rb.stderr)
        ra = pan(dict(env, PANTHEON_REFRESH="1"), T0 + 60, "autoclose", "fetch")
        check("fetch на главном Mac: закрыта в том же проходе, строка «автозакрытие ·» в выводе",
              ra.returncode == 0 and T.read(pa)[0].get("status") == "done" and f"автозакрытие · {a}" in ra.stdout,
              ra.stdout + ra.stderr)
        check("… и копия Obsidian сразу: задача view запущена", os.path.exists(dry) and text(dry).split()[1:] == ["view"],
              text(dry) if os.path.exists(dry) else "нет dryrun.log")
        open(os.path.join(home, "schedule.toml"), "w").write("primary_host = [не toml\n")
        rc = pan(env, T0 + 120, "autoclose", "fetch")
        check("schedule.toml не читается — fetch не падает, проход по кэшу пропущен с причиной",
              rc.returncode == 0 and "проход по кэшу пропущен: schedule.toml не читается" in rc.stderr, rc.stdout + rc.stderr)
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


def test_open_core_sandbox_build():
    """metis-0686: сводка доски берёт «ядро» у шлюза guard — и правка функции сборки окон в pantheon.py ядро."""
    import hashlib
    gate = A.load_gate()
    check("шлюз guard загружается из репозитория", gate is not None and hasattr(gate, "sandbox_build_changes"))
    src = open(CLI, encoding="utf-8").read()
    in_closure = src.replace("    try:\n        with open(policy_path, \"rb\") as fh:",
                             "    _x = 1\n    try:\n        with open(policy_path, \"rb\") as fh:", 1)
    outside = src.replace("def autoclose_cmd(rest):\n", "def autoclose_cmd(rest):\n    _y = 1\n", 1)
    check("пробы правок отличаются от исходника", in_closure != src and outside != src)

    def sha(n):
        return hashlib.sha1(str(n).encode()).hexdigest()
    base, head, mb, tip = sha("b"), sha("h"), sha("m"), sha("t")
    state = {"new": src}
    calls = []

    def fake_text(args, env=None, timeout=90):
        calls.append(args)
        if "compare" in args[1]:
            return mb + "\n"
        ref = args[1].rsplit("ref=", 1)[1]
        return state["new"] if ref == head else src

    def sb(r, p):
        return A.sandbox_core(r, p, gate=gate)

    def not_core(path):
        return False
    real_text, real_tip = A.gh_text, A.base_tip
    A.gh_text, A.base_tip = fake_text, lambda repo, branch, *a, **k: tip
    try:
        pp = "plugins/pantheon/lib/pantheon.py"
        row = {"number": 7, "headRefOid": head, "baseRefOid": base, "baseRefName": "main", "files": [{"path": pp}]}
        state["new"] = in_closure
        check("PR правит функцию из замыкания sandbox_build → ядро", A.open_core("a/b", row, not_core, sb) is True)
        state["new"] = outside
        check("PR правит в pantheon.py другую функцию → не ядро", A.open_core("a/b", row, not_core, sb) is False)
        n = len(calls)
        only = {"number": 8, "files": [{"path": "plugins/pantheon/lib/autoclose.py"}]}
        check("PR только с autoclose.py → не ядро, без запросов к gh",
              A.open_core("a/b", only, not_core, sb) is False and len(calls) == n)
        A.gh_text = lambda *a, **k: None
        state["new"] = in_closure
        check("файлы pantheon.py не получить → ядро (как у шлюза)", A.sandbox_core("a/b", row, gate=gate) is True)
        check("путь ядра по списку путей остаётся ядром", A.open_core("a/b", only, lambda x: True, None) is True)
    finally:
        A.gh_text, A.base_tip = real_text, real_tip


def test_open_core_sessions_launch():
    """metis-0551, 0552: доска берёт у шлюза и запуск окон в sessions.py — снятие --settings в _start_session ядро,
    новая функция в sessions.py — не ядро; PR с pantheon.py и sessions.py сверяет оба файла."""
    import hashlib
    gate = A.load_gate()
    pp, sp = "plugins/pantheon/lib/pantheon.py", "plugins/pantheon/lib/sessions.py"
    src = {pp: open(CLI, encoding="utf-8").read(), sp: open(os.path.join(LIB, "sessions.py"), encoding="utf-8").read()}
    a = '"--settings", run, prompt]'
    check("в sessions.py есть запуск с --settings", src[sp].count(a) == 1)

    def sha(n):
        return hashlib.sha1(str(n).encode()).hexdigest()
    base, head, mb, tip = sha("b"), sha("h"), sha("m"), sha("t")
    state = dict(src)
    asked = []

    def fake_text(args, env=None, timeout=90):
        if "compare" in args[1]:
            return mb + "\n"
        path, ref = args[1].split("/contents/", 1)[1].split("?ref=", 1)
        asked.append(path)
        return state[path] if ref == head else src[path]

    real_text, real_tip = A.gh_text, A.base_tip
    A.gh_text, A.base_tip = fake_text, lambda repo, branch, *a, **k: tip
    try:
        row = {"number": 7, "headRefOid": head, "baseRefOid": base, "baseRefName": "main", "files": [{"path": sp}]}
        state[sp] = src[sp].replace(a, "prompt]", 1)
        check("PR снимает --settings в _start_session → ядро", A.sandbox_core("a/b", row, gate=gate) is True)
        state[sp] = src[sp] + "\n\ndef _probe_0552():\n    return 1\n"
        check("PR добавляет функцию в sessions.py → не ядро", A.sandbox_core("a/b", row, gate=gate) is False)
        del asked[:]
        both = dict(row, files=[{"path": pp}, {"path": sp}])
        check("PR с pantheon.py и sessions.py без правки сборки → не ядро",
              A.sandbox_core("a/b", both, gate=gate) is False and {pp, sp} <= set(asked), asked)
        state[sp] = src[sp].replace(a, "prompt]", 1)
        check("PR с pantheon.py и sessions.py, снятие --settings → ядро", A.sandbox_core("a/b", both, gate=gate) is True)
    finally:
        A.gh_text, A.base_tip = real_text, real_tip


def test_board_line_core():
    """metis-0686 п. 3: PR с правкой функции из замыкания sandbox_build проходит весь путь доски — fetch (признак шлюза)
    → кэш autoclose-prs.json → boardtext.open_prs → pr_line: в строке «ядро → сливает владелец», слов «не ядро» нет.
    Соседний PR с правкой другой функции pantheon.py — «не ядро»."""
    import hashlib
    import boardtext as B
    gate = A.load_gate()
    src = open(CLI, encoding="utf-8").read()
    in_closure = src.replace("    try:\n        with open(policy_path, \"rb\") as fh:",
                             "    _x = 1\n    try:\n        with open(policy_path, \"rb\") as fh:", 1)
    outside = src.replace("def autoclose_cmd(rest):\n", "def autoclose_cmd(rest):\n    _y = 1\n", 1)
    check("0686 п.3: пробы правок отличаются от исходника", in_closure != src and outside != src)

    def sha(n):
        return hashlib.sha1(str(n).encode()).hexdigest()
    base, mb, tip, h_core, h_plain = sha("b"), sha("m"), sha("t"), sha("h1"), sha("h2")
    by_ref = {h_core: in_closure, h_plain: outside}

    def fake_text(args, env=None, timeout=90):
        if "compare" in args[1]:
            return mb + "\n"
        return by_ref.get(args[1].rsplit("ref=", 1)[1], src)
    pp = "plugins/pantheon/lib/pantheon.py"
    tmp, home, state, gh, env = make()
    real_text, real_tip = A.gh_text, A.base_tip
    A.gh_text, A.base_tip = fake_text, lambda repo, branch, *a, **k: tip
    try:
        write_gh(gh, "latark/agent-kit", "open", [
            {"number": 249, "headRefName": "metis-0686-x", "body": "", "headRefOid": h_core, "baseRefOid": base,
             "baseRefName": "main", "files": [{"path": pp}]},
            {"number": 250, "headRefName": "metis-0687-y", "body": "", "headRefOid": h_plain, "baseRefOid": base,
             "baseRefName": "main", "files": [{"path": pp}]}])
        cache = os.path.join(state, "autoclose-prs.json")
        os.makedirs(state, exist_ok=True)
        errs = A.fetch(cache, os.path.join(state, "s.json"), T0, ["latark/agent-kit"], env=dict(env),
                       core=lambda path: False,
                       sandbox=lambda r, p, left=None: A.sandbox_core(r, p, env, gate=gate, left=left))
        rows = {p["number"]: p for p in B.open_prs(cache) or []}
        line = B.pr_line(rows[249], {}) if 249 in rows else ""
        plain = B.pr_line(rows[250], {}) if 250 in rows else ""
        check("0686 п.3: строка доски PR с правкой замыкания sandbox_build — «ядро → сливает владелец», без «не ядро»",
              not errs and "ядро → сливает владелец" in line and "не ядро" not in line, f"{errs} {line!r}")
        check("0686 п.3: строка доски PR с правкой другой функции pantheon.py — «не ядро»",
              "не ядро → «принять» Зевса" in plain, plain)
    finally:
        A.gh_text, A.base_tip = real_text, real_tip
        shutil.rmtree(tmp, True)


def test_stub_four_consumers():
    """metis-0711, Д ревью #272: заглушку шаблона одинаково узнают все четыре, кто считает пункты «Готово, когда»:
    unchecked_criteria (закрытие и autoclose), criteria_count, no_criteria (direction_summary) и task_split (остаток). Та же
    заглушка с двойным пробелом, табуляцией и пробелами по краям — для всех «нет критериев»; рядом с настоящим пунктом —
    для всех один пункт."""
    tmp, home, state, gh, env = make()
    try:
        hint = T.DONE_WHEN_HINT
        stubs = {"дословно": hint, "двойной пробел": hint.replace(" ", "  ", 1),
                 "табуляция внутри": hint.replace(" ", "\t", 2), "пробелы по краям": "  " + hint + " "}
        for n, (name, stub) in enumerate(sorted(stubs.items())):
            tid = f"demo-02{n:02d}"
            p = put(home, "demo", tid, status="todo", created="2026-10-27", body="Готово, когда:\n- [ ] " + stub + "\n")
            head, body = T.read(p)
            tasks = {tid: (p, head, body)}
            got = {"unchecked_criteria": T.unchecked_criteria(head, body), "criteria_count": T.criteria_count(body),
                   "no_criteria": T.direction_summary(tasks)["demo"]["no_criteria"]}
            nid, np_ = T.task_split(home, T0, tid, "Остаток " + name)
            got["split"] = [x for _, x in T.done_criteria(T.read(np_)[1])]
            want = {"unchecked_criteria": 0, "criteria_count": "не заданы", "no_criteria": 1, "split": [hint]}
            check(f"0711: заглушка ({name}) — все четыре: нет критериев", got == want, f"{got}")
        p = put(home, "demo", "demo-0299", status="todo", created="2026-10-27",
                body="Готово, когда:\n- [ ] " + hint.replace(" ", "  ", 1) + "\n- [ ] настоящий\n")
        head, body = T.read(p)
        got = {"unchecked_criteria": T.unchecked_criteria(head, body), "criteria_count": T.criteria_count(body),
               "no_criteria": T.direction_summary({"demo-0299": (p, head, body)})["demo"]["no_criteria"]}
        nid, np_ = T.task_split(home, T0, "demo-0299", "Остаток с пунктом")
        got["split"] = [x for _, x in T.done_criteria(T.read(np_)[1])]
        check("0711: заглушка рядом с настоящим пунктом — все четыре видят один пункт",
              got == {"unchecked_criteria": 1, "criteria_count": "0 из 1", "no_criteria": 0, "split": ["настоящий"]}, f"{got}")
    finally:
        shutil.rmtree(tmp, True)


def test_core_budget_and_rename():
    """metis-0711: признак ядра в бюджете fetch (Д1), переименование pantheon.py (Д2), gh вершины ветки — из PANTHEON_GH (С1)."""
    import hashlib
    gate = A.load_gate()
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="autoclose-core-"))
    try:
        slow = os.path.join(tmp, "gh")
        open(slow, "w").write("#!/bin/sh\ntouch \"$0.ran\"\nsleep 5\nexit 1\n")
        os.chmod(slow, 0o755)
        env = {"PATH": "/usr/bin:/bin", "PANTHEON_GH": slow}
        pp = "plugins/pantheon/lib/pantheon.py"
        sh = lambda n: hashlib.sha1(str(n).encode()).hexdigest()
        row = {"number": 7, "headRefOid": sh("h"), "baseRefOid": sh("b"), "baseRefName": "main", "files": [{"path": pp}]}
        end = time.monotonic() + 2.5
        t0 = time.monotonic()
        got = A.sandbox_core("a/b", row, env, gate=gate, left=lambda: end - time.monotonic())
        el = time.monotonic() - t0
        check("Д1: медленный gh в пределах бюджета fetch, PR — ядро", got is True and el < 4.0, f"{el:.1f} c {got}")
        os.remove(slow + ".ran")
        end = time.monotonic() + 0.5
        t0 = time.monotonic()
        got = A.sandbox_core("a/b", row, env, gate=gate, left=lambda: end - time.monotonic())
        check("Д1: left() <= 1 — ядро без вызова gh", got is True and time.monotonic() - t0 < 1.0 and not os.path.exists(slow + ".ran"))

        seen = []

        def sb(r, p, left=None):
            seen.append(left)
            return False
        tmp2, home, state, gh, env2 = make()
        try:
            write_gh(gh, "a/b", "open", [{"number": 1, "headRefName": "x", "body": "", "files": [{"path": pp}]}])
            A.fetch(os.path.join(state, "p.json"), os.path.join(state, "s.json"), T0, ["a/b"], env=dict(env2), budget=60,
                    core=lambda x: False, sandbox=sb)
            check("Д1: fetch передаёт в sandbox остаток бюджета", len(seen) == 1 and callable(seen[0]) and 0 < seen[0]() <= 60, str(seen))
        finally:
            shutil.rmtree(tmp2, True)

        n = {"gh": 0}
        real_text = A.gh_text
        A.gh_text = lambda *a, **k: n.__setitem__("gh", n["gh"] + 1)
        try:
            for name, files in (
                    ("previous_filename = pantheon.py", [{"path": "plugins/pantheon/lib/old.py", "previous_filename": pp}]),
                    ("pantheon.py ушёл (путь с ./ и регистром)", [{"path": "x.py", "previous_filename": "./Plugins/Pantheon/lib/pantheon.py"}]),
                    ("changeType RENAMED, старый путь gh не отдаёт", [{"path": "plugins/pantheon/lib/other.py", "changeType": "RENAMED"}])):
                check("Д2: переименование — ядро: " + name, A.sandbox_core("a/b", dict(row, files=files), env, gate=gate) is True)
            check("Д2: обычная правка другого файла — не ядро",
                  A.sandbox_core("a/b", dict(row, files=[{"path": "README.md", "changeType": "MODIFIED"}]), env, gate=gate) is False)
        finally:
            A.gh_text = real_text

        # С1: gh вершины ветки — PANTHEON_GH, а не PATH
        fake = os.path.join(tmp, "gh2")
        tip = sh("t")
        open(fake, "w").write("#!/bin/sh\necho '{\"ref\":\"refs/heads/main\",\"object\":{\"type\":\"commit\",\"sha\":\"%s\"}}'\n" % tip)
        os.chmod(fake, 0o755)
        check("С1: base_tip берёт gh из PANTHEON_GH (в PATH его нет)",
              A.base_tip("a/b", "main", {"PATH": "/usr/bin:/bin", "PANTHEON_GH": fake}, gate) == tip)
        check("С1: нет gh — None", A.base_tip("a/b", "main", {"PATH": "/nonexistent"}, gate) is None)
        check("С1: плохое имя ветки — None", A.base_tip("a/b", "../x", {"PANTHEON_GH": fake}, gate) is None)
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


def test_fetch_keeps_rows_on_error():
    """metis-0808: ошибка gh по репозиторию (401, TLS, EOF, время) оставляет его прежние слитые и открытые PR, а в кэше —
    stale[repo] со временем последнего успеха; один завислый репозиторий не съедает проход; давний успех идёт первым."""
    tmp, home, state, gh, env = make()
    try:
        cf, sf = os.path.join(state, "p.json"), os.path.join(state, "s.json")
        repos = ["a/b", "c/d"]
        for r in repos:
            write_gh(gh, r, "merged", [pr(5, "metis-0808", "Closes metis-0808", T0)])
            write_gh(gh, r, "open", [{"number": 9, "headRefName": "x", "headRefOid": "1" * 40, "body": "Closes metis-0809", "files": []}])
        check("fetch: чистый проход — ошибок нет, stale пусто, repo_ok по обоим",
              A.fetch(cf, sf, T0, repos, env=dict(env)) == {} and A.load_state(cf).get("stale") == {}
              and A.load_state(cf).get("repo_ok") == {"a/b": T0, "c/d": T0})
        good = os.path.join(gh, "gh")
        ok_text = open(good).read()

        def gh_script(body):
            open(good, "w").write(ok_text.replace('if [ "$1 $2" = "pr list" ]; then', body + '\nif [ "$1 $2" = "pr list" ]; then', 1))
        # 401 по всем репозиториям
        gh_script('echo "HTTP 401: Bad credentials" >&2; exit 1')
        errs = A.fetch(cf, sf, T0 + 600, repos, env=dict(env))
        c = A.load_state(cf)
        check("401 по всем репозиториям: ошибки на обоих, прежние merged и open_prs на месте",
              sorted(errs) == repos and all("401" in v for v in errs.values())
              and [r["number"] for r in c["merged"]["a/b"]] == [5] and c["open_prs"]["c/d"][0]["number"] == 9
              and c["open"]["a/b"] == ["metis-0809"], (errs, c))
        check("401: stale[repo] — время последнего успеха, не нынешнего прохода", c["stale"] == {"a/b": T0, "c/d": T0}
              and c["fetched"] == T0 + 600 and c["repo_ok"] == {"a/b": T0, "c/d": T0}, c)
        idx = A.pr_index(c)
        check("401: pr_index (ссылки карточек, пачки) прежний", sorted((x["repo"], x["number"]) for x in idx.get("metis-0808", [])) == [("a/b", 5), ("c/d", 5)]
              and sorted((x["repo"], x["number"]) for x in idx.get("metis-0809", [])) == [("a/b", 9), ("c/d", 9)], idx)
        errs = A.fetch(cf, sf, T0 + 1200, repos, env=dict(env))
        check("второй сбой подряд: stale не сдвигается к нынешнему проходу", A.load_state(cf)["stale"] == {"a/b": T0, "c/d": T0})
        # сбой только открытых PR: слитые свежие, открытые прежние
        write_gh(gh, "a/b", "merged", [pr(5, "metis-0808", "Closes metis-0808", T0), pr(6, "x", "", T0)])
        gh_script('case "$*" in *"--state open"*) echo "TLS handshake timeout" >&2; exit 1;; esac')
        errs = A.fetch(cf, sf, T0 + 1800, repos, env=dict(env))
        c = A.load_state(cf)
        check("сбой только открытых PR: слитые новые, открытые прежние, ошибка и stale по репозиторию",
              [r["number"] for r in c["merged"]["a/b"]] == [5, 6] and c["open_prs"]["a/b"][0]["number"] == 9
              and "открытые PR" in errs.get("a/b", "") and c["stale"].get("a/b") == T0, (errs, c["stale"]))
        # починилось: stale и ошибки уходят, repo_ok обновлён
        open(good, "w").write(ok_text)
        write_gh(gh, "a/b", "open", [])
        errs = A.fetch(cf, sf, T0 + 2400, repos, env=dict(env))
        c = A.load_state(cf)
        check("gh снова отвечает: ошибок и stale нет, открытых PR у a/b нет (честный ноль), repo_ok обновлён",
              errs == {} and c["stale"] == {} and c["open_prs"]["a/b"] == [] and c["repo_ok"] == {"a/b": T0 + 2400, "c/d": T0 + 2400}, c)
        # репозиторий без прошлых строк и сбой: пусто, stale = 0 (данных нет)
        gh_script('echo "EOF" >&2; exit 1')
        errs = A.fetch(cf, sf, T0 + 3000, ["n/e"], env=dict(env))
        c = A.load_state(cf)
        check("новый репозиторий + сбой: строк нет, stale 0 (данных нет)", c["merged"] == {} and c["stale"] == {"n/e": 0}, c)
        open(good, "w").write(ok_text)
        # зависший gh: бюджет на репозиторий, второй не голодает
        A.save_state(cf, {"fetched": T0, "merged": {r: [{"number": 5}] for r in repos}, "open_prs": {}, "repo_ok": {r: T0 for r in repos}})
        open(os.path.join(gh, "sleep"), "w").write("5")
        open(os.path.join(gh, "calls.log"), "w").close()
        t0 = time.monotonic()
        errs = A.fetch(cf, sf, T0 + 3600, repos, env=dict(env), budget=60, repo_budget=1.5)
        el = time.monotonic() - t0
        calls = open(os.path.join(gh, "calls.log")).read()
        check("завислый gh: на репозиторий не больше repo_budget, оба репозитория опрошены, прежние строки целы",
              el < 8 and "--repo a/b" in calls and "--repo c/d" in calls and sorted(errs) == repos
              and A.load_state(cf)["merged"]["c/d"] == [{"number": 5}], f"{el:.1f} c {errs}")
        os.remove(os.path.join(gh, "sleep"))
        # порядок: давний успех идёт первым
        A.save_state(cf, {"fetched": T0, "merged": {}, "open_prs": {}, "repo_ok": {"a/b": T0 + 50, "c/d": T0 + 10}})
        open(os.path.join(gh, "calls.log"), "w").close()
        A.fetch(cf, sf, T0 + 4000, repos, env=dict(env))
        first = [ln for ln in open(os.path.join(gh, "calls.log")).read().splitlines() if ln.startswith("pr list")]
        check("порядок обхода: репозиторий с самым давним успехом первым", "--repo c/d" in first[0], first[:2])
        # Б1: кэш до metis-0808 (нет repo_ok): два сбоя подряд не сдвигают «данные от» к fetched
        A.save_state(cf, {"fetched": T0, "merged": {"a/b": [{"number": 5}]}, "open_prs": {}})
        e2 = dict(env, PANTHEON_GH="/nonexistent/gh")
        A.fetch(cf, sf, T0 + 600, ["a/b"], env=e2)
        c1 = A.load_state(cf)
        A.fetch(cf, sf, T0 + 1200, ["a/b"], env=e2)
        c2 = A.load_state(cf)
        check("старый кэш без repo_ok и два сбоя подряд: stale остаётся T0, repo_ok запомнен",
              c1["stale"] == {"a/b": T0} and c2["stale"] == {"a/b": T0} and c2["repo_ok"] == {"a/b": T0}
              and c2["merged"]["a/b"] == [{"number": 5}], (c1, c2))
        A.save_state(cf, {"fetched": T0, "merged": {}, "open_prs": {}})
        A.fetch(cf, sf, T0 + 600, ["a/b"], env=e2)
        check("старый кэш без строк репозитория и сбой: stale 0, repo_ok не выдуман",
              A.load_state(cf)["stale"] == {"a/b": 0} and "a/b" not in A.load_state(cf)["repo_ok"], A.load_state(cf))
        # бюджет прохода кончился: репозиторий не потерял строки
        A.save_state(cf, {"fetched": T0, "merged": {"a/b": [{"number": 5}]}, "open_prs": {}, "repo_ok": {"a/b": T0}})
        errs = A.fetch(cf, sf, T0 + 4500, ["a/b"], env=dict(env), budget=0)
        c = A.load_state(cf)
        check("не хватило времени прохода: прежние строки остаются", errs == {"a/b": "не хватило времени прохода"}
              and c["merged"]["a/b"] == [{"number": 5}] and c["stale"] == {"a/b": T0}, c)
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
        # metis-0799: признак форка (isCrossRepository) — в кэше как cross; gh его не дал — считается форком
        write_gh(gh, "a/b", "merged", [dict(pr(5, "batch/metis-0750", "", T0), isCrossRepository=False),
                                       dict(pr(6, "batch/metis-0750", "", T0), isCrossRepository=True), pr(7, "batch/metis-0750", "", T0)])
        write_gh(gh, "a/b", "open", [{"number": 8, "headRefName": "batch/metis-0751", "headRefOid": h("3"), "body": "",
                                      "files": [], "isCrossRepository": False},
                                     {"number": 9, "headRefName": "batch/metis-0751", "headRefOid": h("4"), "body": "",
                                      "files": [], "isCrossRepository": True}])
        A.fetch(cf, os.path.join(state, "s.json"), T0 + 1200, ["a/b"], env=dict(env))
        c = A.load_state(cf)
        check("fetch: cross в кэше — False только у PR из самого репозитория (слитые и открытые)",
              [r.get("cross") for r in c["merged"]["a/b"]] == [False, True, True]
              and [r.get("cross") for r in c["open_prs"]["a/b"]] == [False, True], (c["merged"], c["open_prs"]))
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
        dbl = T.DONE_WHEN_HINT.replace(" ", "  ", 1)
        p24 = put(home, "metis-pantheon", "metis-0024", body="Готово, когда:\n- [ ] " + dbl + "\n", created="2026-10-27")
        T.task_set(home, T0, "metis-0024", {"status": "done"})
        check("metis-0711: заглушка с двойным пробелом закрытие не держит", T.read(p24)[0].get("status") == "done")
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


def test_review_without_closes():
    """metis-0615 п. 3 (случай athena-0184, PR BA #38): открытый PR без Closes и без id в ветке ставит review задачам
    doing/waiting, названным в ветке или теле (ids); todo по упоминанию не трогает. PR с Closes ставит review и задаче в
    waiting; waiting владельца (waiting_on human) остаётся в «Нужен ответ»; «часть» — никому."""
    tmp, home, state, gh, env = make()
    try:
        R = "latark/agent-kit"
        ps = {i: put(home, "metis-pantheon", i, status=st, **kw) for i, st, kw in (
            ("metis-0101", "waiting", {"waiting_on": "talos"}), ("metis-0102", "doing", {}), ("metis-0103", "todo", {}),
            ("metis-0104", "waiting", {"waiting_on": "human"}), ("metis-0105", "waiting", {"waiting_on": "talos"}),
            ("metis-0106", "doing", {}), ("metis-0107", "todo", {}), ("metis-0108", "doing", {}),
            ("metis-0109", "waiting", {"waiting_on": "talos"}))}
        # ветка без префикса id (как BA #38 …-0184): номера 0101–0104 в ветке, 0108 и 0109 — только упоминание в теле
        # («после metis-0108», «зависит от metis-0109», argus #341 Б1)
        rows = [{"number": 38, "closes": [], "branch": "fix-0101-0102-0103-0104",
                 "ids": ["metis-0101", "metis-0102", "metis-0103", "metis-0104", "metis-0108", "metis-0109"], "part": False},
                {"number": 39, "closes": ["metis-0105", "metis-0107"], "ids": ["metis-0105", "metis-0106", "metis-0107"],
                 "part": False},
                {"number": 40, "closes": [], "ids": ["metis-0106"], "part": True}]
        log, errs = [], {}
        for row in rows:
            A.review_pr(home, T0, R, row, {"metis-pantheon"}, T, log, errs)
        st = {i: T.read(p)[0].get("status") for i, p in ps.items()}
        check("0615: PR без Closes — waiting и doing из ветки/тела → review, строка в журнале",
              st["metis-0101"] == "review" and st["metis-0102"] == "review"
              and "PR #38 (latark/agent-kit) " + A.REVIEW_MARK in text(ps["metis-0101"]), (st, errs))
        check("0615: PR без Closes — todo по упоминанию не трогает, waiting владельца (human) тоже",
              st["metis-0103"] == "todo" and st["metis-0104"] == "waiting", st)
        check("0615: PR с Closes — review и у waiting; упоминание рядом с Closes не в счёт; todo по Closes — review",
              st["metis-0105"] == "review" and st["metis-0106"] == "doing" and st["metis-0107"] == "review", st)
        check("0615: waiting → review снимает waiting_on, прежний — в строке журнала",
              T.read(ps["metis-0101"])[0].get("waiting_on") is None and "; был waiting_on talos" in text(ps["metis-0101"]),
              text(ps["metis-0101"])[-300:])
        check("0615 (argus #341 Б1): PR без Closes — задача только упомянута в теле («после Y»), номера нет в ветке: "
              "doing и waiting не трогаются, waiting_on цел",
              st["metis-0108"] == "doing" and st["metis-0109"] == "waiting"
              and T.read(ps["metis-0109"])[0].get("waiting_on") == "talos", st)
        check("0615: branch_named — номер числом в имени ветки; соседний номер (0274 при ветке …-0275), ветки нет — нет",
              A.branch_named("landing-claims-0275", ["athena-0274", "athena-0275", "athena-275", 7]) == ["athena-0275",
                                                                                                      "athena-275"]
              and A.branch_named(None, ["athena-0275"]) == [] and A.branch_named("x-02750", ["athena-0275"]) == [])
        check("0615: PR «часть» без Closes review не ставит", st["metis-0106"] == "doing" and not errs, (st, errs))
    finally:
        shutil.rmtree(tmp, True)


def main():
    test_lists_and_checked()
    test_unit()
    test_board_problems_unit()
    test_attention_on_card()
    test_close_criteria()
    test_tick()
    test_fetch_same_pass_primary_only()
    test_old_and_errors()
    test_rules()
    test_reopen_and_eviction()
    test_mutants()
    test_open_core_sandbox_build()
    test_board_line_core()
    test_stub_four_consumers()
    test_fetch_budget()
    test_fetch_keeps_rows_on_error()
    test_former_heads()
    test_core_budget_and_rename()
    test_batch_needs_mode()
    test_off_warning()
    test_check()
    test_review_without_closes()
    print(f"{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
