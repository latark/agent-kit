#!/usr/bin/env python3
"""Автоотметка «Готово, когда» по вердикту argus (metis-1004).

- `pantheon review accept|reject … --criteria "<id>#<N> <хеш> да|нет <опора>"`: формат, хеш от нынешнего текста пункта,
  у accept — без «нет», вердикт можно не по всем пунктам; `pantheon review criteria <id>` печатает готовые флаги; status
  показывает пункты записи.
- criteria_accepted: только «принять» на head слияния, по правилу шлюза (последний вердикт рецензента, перечень, Opus у
  ядра, base, позже «вернуть»); «нет» или разный хеш у двух argus — пункт не принят; строка кэша без core — как ядро.
- merged_core: оба пути переименования, переименование без старого пути и список файлов, обрезанный gh, — ядро.
- autoclose (fetch с поддельным gh → проход по кэшу): слитый PR с Closes отмечает пункты с «да» из записи argus на head
  слияния; все отмечены — done, иначе review с номерами неотмеченных; запись другого head, пункт, которого нет в
  карточке, и пункт, изменённый после приёмки, не отмечают ничего; ядро — только «принять» на Opus.
- metis-1193: пункт задачи вне Closes отмечается, если тело PR его называет («пункт N <id>») и argus принял его на head
  слияния; названный без приёмки, принятый без названия, чужого направления, done, со сменой текста — не отмечается.

Временные HOME, PANTHEON_HOME, PANTHEON_STATE; всё убирается в конце.
Запуск: python3.14 -I plugins/pantheon/tests/test_criteria_tick.py  (код выхода 0 — все прошли)
"""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402 — CLI pantheon только на Python 3.11+

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="crit-root-"))
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIB, "run.py")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

T0 = 1_792_000_000
H1, H2 = "1" * 40, "2" * 40
CL = {"opened": "review.py", "ran": "heavy pytest", "unchecked": "живой gh"}
OPUS = dict(CL, ran="модель: claude-opus-5-5, heavy pytest")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


FAKE_GH = """#!/bin/sh
d="$FAKE_GH_DIR"; repo=""; state=""; prev=""
echo "$@" >> "$d/calls.log"
for a in "$@"; do
  case "$prev" in --repo) repo="$a";; --state) state="$a";; esac
  prev="$a"
done
if [ "$1 $2" = "pr list" ]; then
  f="$d/$(echo "$repo" | tr / _)-$state.json"
  [ -f "$f" ] && cat "$f" || echo "[]"
  exit 0
fi
exit 1
"""

DIRS = '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n'
POLICY = '[merge_repos]\nmetis-pantheon = ["latark/agent-kit"]\n'
TWO = "## Готово, когда\n\n- [ ] первый пункт: файл a.py\n- [ ] второй пункт (тест)\n"


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="crit-test-"))
    home, state, view, gh = (os.path.join(tmp, x) for x in ("pantheon", "state", "view", "gh"))
    os.makedirs(os.path.join(home, "directions", "metis-pantheon", "tasks"))
    os.makedirs(os.path.join(home, "inbox", "tasks"))
    os.makedirs(os.path.join(state, "merge-gate"))
    for d in (view, gh, os.path.join(tmp, ".claude", "pantheon")):
        os.makedirs(d)
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


def pan(env, *a, t=T0):
    return subprocess.run([PY311, "-I", RUN_PY, *a], env=dict(env, PANTHEON_NOW=str(t)), capture_output=True, text=True,
                          timeout=120)


def put(home, tid, body=TWO, status="doing"):
    head = {"type": "task", "id": tid, "title": "Задача " + tid, "status": status, "project": "Пантеон",
            "direction": "metis-pantheon", "owner": "metis-pantheon", "created": "2026-11-08",
            "updated": "2026-11-08T10:00:00", "schema_version": 1}
    p = os.path.join(home, "directions", "metis-pantheon", "tasks", tid + ".md")
    lines = [f"{k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, str) else v}" for k, v in head.items()]
    open(p, "w", encoding="utf-8").write("---\n" + "\n".join(lines) + "\n---\n\n# " + head["title"] + "\n\n" + body
                                         + "\n## Журнал\n\n- 2026-11-08 10:00 — агент: создана\n")
    return p


def text(p):
    return open(p, encoding="utf-8").read()


def h(body_line):
    return T.criterion_hash(body_line)


A1, A2 = h("первый пункт: файл a.py"), h("второй пункт (тест)")


def crit(tid, n, hh, verdict="да", basis="tests/t.py:1"):
    return f"{tid}#{n} {hh} {verdict} {basis}"


def verdict(kind, sha, agent="ag1", sid="s1", criteria=None, cl=CL, pr=7, base="main", **kw):
    r = {"v": 1, "kind": kind, "repo": ["latark/agent-kit"], "pr": pr, "sha": sha,
         "by": {"agent_type": "argus", "agent_id": agent, "session_id": sid}, "time": "2026-11-08T12:00:00+0700"}
    if cl:
        r["checklist"] = cl
    if base:
        r["base"] = base
    if criteria is not None:
        r["criteria"] = criteria
    r.update(kw)
    return r


def write_records(state, recs):
    with open(os.path.join(state, "merge-gate", "records.jsonl"), "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


# --- tasks: формат и отметка ----------------------------------------------------------------------------------------

def test_tasks_unit():
    check("parse_criterion: id#N, хеш, да, опора с пробелами и «:»",
          T.parse_criterion(f"metis-1004#2 {A1} да plugins/x.py:12 и тест t_a") ==
          ("metis-1004", 2, A1, "да", "plugins/x.py:12 и тест t_a"))
    for bad in (f"metis-1004#2 {A1} да", f"metis-1004 {A1} да x", f"metis-1004#0 {A1} да x", f"metis-1004#2 {A1[:11]} да x",
                f"metis-1004#2 {A1.upper()} да x", f"metis-1004#2 {A1} может x", f"METIS-1004#2 {A1} да x", "", None):
        check(f"parse_criterion: «{bad}» — не в формате", T.parse_criterion(bad) is None)
    check("criterion_hash: 12 знаков, зависит от текста дословно",
          len(A1) == 12 and h("первый пункт: файл a.py ") != A1 and h("первый пункт: файл a.py") == A1)
    tmp, home, state, gh, env = make()
    try:
        p = put(home, "metis-0001", body=TWO + "- [x] третий\n")
        got = T.criteria_tick(home, T0, "metis-0001", {1: A1, 2: h("не тот текст"), 3: h("третий"), 9: A1},
                              "плановый проход", "PR #7 слит")
        body = text(p)
        check("criteria_tick: отмечен только пункт с тем же хешем; другой хеш, отмеченный и несуществующий — нет",
              got == [1] and "- [x] первый пункт" in body and "- [ ] второй пункт" in body, (got, body))
        check("criteria_tick: строка журнала с номерами", "PR #7 слит — отмечены пункты 1" in body, body[-300:])
        check("unchecked_numbers: номера неотмеченных", T.unchecked_numbers(*T.read(p)) == [2])
        before = text(p)
        check("criteria_tick: нечего отмечать — файл не тронут",
              T.criteria_tick(home, T0, "metis-0001", {1: A1}, "x", "y") == [] and text(p) == before)
        stub = put(home, "metis-0002", body="## Готово, когда\n\n- [ ] " + T.DONE_WHEN_HINT + "\n")
        check("criteria_tick: заглушку не отмечает",
              T.criteria_tick(home, T0, "metis-0002", {1: h(T.DONE_WHEN_HINT)}, "x", "y") == [] and "[x]" not in text(stub))
    finally:
        shutil.rmtree(tmp, True)


# --- pantheon review --criteria и criteria ----------------------------------------------------------------------------

def test_review_cli():
    tmp, home, state, gh, env = make()
    try:
        put(home, "metis-0001")
        # metis-0669: «принять» — только на head с записью тестов шлюза или зелёным CI; запись tests на H1 есть
        write_records(state, [dict(verdict("tests", H1, cl=None, base=None), by={"agent_type": "pantheon-outside"},
                                   cmd="x")])
        base = ["review", "accept", "latark/agent-kit", "7", H1, "--opened", "a", "--ran", "b", "--unchecked", "c"]
        ok1, ok2 = crit("metis-0001", 1, A1), crit("metis-0001", 2, A2, basis="t_two")
        r = pan(env, *base, "--criteria", ok1, f"--criteria={ok2}")
        check("accept с вердиктом по каждому пункту — код 0, пункты напечатаны",
              r.returncode == 0 and f"пункт: {ok1}" in r.stdout and f"пункт: {ok2}" in r.stdout, r.stdout + r.stderr)
        r = pan(env, *base, "--criteria", ok1)
        check("accept с вердиктом не по всем пунктам (часть, после слияния) — код 0", r.returncode == 0
              and f"пункт: {ok1}" in r.stdout, r.stdout + r.stderr)
        cases = [
            ([ok1, crit("metis-0001", 2, A2, "нет")], "это «вернуть»"),
            ([ok1, crit("metis-0001", 2, A1)], "хеш"),
            ([ok1, crit("metis-0001", 3, A2)], "нет пункта 3"),
            ([ok1, ok2, crit("metis-0999", 1, A1)], "задачи metis-0999 нет"),
            ([ok1, ok1, ok2], "указан дважды"),
            ([ok1, crit("metis-0001", 2, A2, basis="ОПОРА")], "вместо «ОПОРА»"),
            (["metis-0001#1 да"], "не в формате"),
        ]
        for items, why in cases:
            args = [x for v in items for x in ("--criteria", v)]
            r = pan(env, *base, *args)
            check(f"accept --criteria → код 2, «{why}»", r.returncode == 2 and why in r.stderr, r.stdout + r.stderr)
        r = pan(env, *base, "--criteria")
        check("accept --criteria без значения — код 2", r.returncode == 2, r.stderr)
        r = pan(env, "review", "reject", "latark/agent-kit", "7", H1, "--criteria", crit("metis-0001", 2, A2, "нет", "нет теста"))
        check("reject с «нет» по одному пункту — код 0 (вердикт по каждому не обязателен)", r.returncode == 0, r.stderr)
        r = pan(env, "review", "talos", "latark/agent-kit", "7", H1, "--criteria", ok1)
        check("talos — --criteria нет, код 2", r.returncode == 2, r.stderr)
        r = pan(env, "review", "criteria", "metis-0001")
        check("review criteria — пункты с номером и готовым флагом с хешем и «ОПОРА»",
              r.returncode == 0 and "metis-0001#1 [ ] первый пункт: файл a.py" in r.stdout
              and f'--criteria "metis-0001#2 {A2} да ОПОРА"' in r.stdout, r.stdout + r.stderr)
        check("review criteria: нет задачи — код 1, без id — код 2",
              pan(env, "review", "criteria", "metis-0999").returncode == 1 and pan(env, "review", "criteria").returncode == 2)
        write_records(state, [verdict("accept", H1, criteria=[ok1, ok2])])
        r = pan(env, "review", "status", "latark/agent-kit", "7")
        check("status показывает пункты записи", r.returncode == 0 and f"пункт: {ok1}" in r.stdout, r.stdout + r.stderr)
    finally:
        shutil.rmtree(tmp, True)


# --- criteria_accepted: правило засчитывания ---------------------------------------------------------------------------

def load_pantheon(tmp):
    os.environ.update(HOME=tmp, PANTHEON_HOME=os.path.join(tmp, "pantheon"), PANTHEON_STATE=os.path.join(tmp, "state"),
                      PANTHEON_VIEW=os.path.join(tmp, "view"))
    spec = importlib.util.spec_from_file_location("pantheon_crit_test", os.path.join(LIB, "pantheon.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # merge_mod берёт ядро из sys.modules[__name__]
    spec.loader.exec_module(mod)
    return mod


def test_accepted_unit():
    tmp, home, state, gh, env = make()
    try:
        P = load_pantheon(tmp)
        both = [crit("metis-0001", 1, A1), crit("metis-0001", 2, A2)]
        want = {"metis-0001": {1: A1, 2: A2}}

        def acc(recs, head=H1, base="main", core=False):
            return P.criteria_accepted(recs, 7, head, base, core)
        check("«принять» на head с «да» — оба пункта", acc([verdict("accept", H1, criteria=both)]) == want)
        check("запись другого head — ничего", acc([verdict("accept", H2, criteria=both)]) == {})
        check("другой PR — ничего", acc([verdict("accept", H1, criteria=both, pr=8)]) == {})
        check("не argus — ничего", acc([dict(verdict("accept", H1, criteria=both), by={"agent_type": "dev-opus",
                                                                                      "agent_id": "x", "session_id": "s"})]) == {})
        check("без полного перечня — ничего", acc([verdict("accept", H1, criteria=both, cl=dict(CL, ran=" "))]) == {})
        check("base записи не base PR — ничего", acc([verdict("accept", H1, criteria=both, base="dev")]) == {})
        check("base PR неизвестна — ничего", acc([verdict("accept", H1, criteria=both)], base=None) == {})
        check("ядро: «принять» не на Opus — ничего", acc([verdict("accept", H1, criteria=both)], core=True) == {})
        check("ядро: «принять» на Opus — оба", acc([verdict("accept", H1, criteria=both, cl=OPUS)], core=True) == want)
        check("последний вердикт рецензента — «вернуть» на head — ничего",
              acc([verdict("accept", H1, criteria=both), verdict("reject", H1)]) == {})
        check("«вернуть» другого argus на head последним — ничего",
              acc([verdict("accept", H1, criteria=both), verdict("reject", H1, agent="ag2")]) == {})
        check("«вернуть» на прошлом head раньше «принять» — в счёт",
              acc([verdict("reject", H2), verdict("accept", H1, criteria=both, agent="ag2")]) == want)
        check("«вернуть» другого argus на head раньше «принять» — ничего",
              acc([verdict("reject", H1, agent="ag2"), verdict("accept", H1, criteria=both)]) == {})
        check("«вернуть» снято «принять» того же рецензента на третьем head — не снято, ничего",
              acc([verdict("accept", H1, criteria=both, agent="ag2"), verdict("reject", H2),
                   verdict("accept", "3" * 40)]) == {})
        check("«принять» раньше неснятого «вернуть» на прошлом head — не в счёт",
              acc([verdict("accept", H1, criteria=both, agent="ag2"), verdict("reject", H2)]) == {})
        check("тот же рецензент снял своё «вернуть» на том же head — в счёт",
              acc([verdict("reject", H1), verdict("accept", H1, criteria=both)]) == want)
        check("один пункт «нет» — принят только другой",
              acc([verdict("accept", H1, criteria=[both[0], crit("metis-0001", 2, A2, "нет")])]) == {"metis-0001": {1: A1}})
        check("два argus: у второго «нет» по пункту 2 — пункт 2 не принят",
              acc([verdict("accept", H1, criteria=both), verdict("accept", H1, agent="ag2",
                                                                  criteria=[both[0], crit("metis-0001", 2, A2, "нет")])])
              == {"metis-0001": {1: A1}})
        check("два argus с разным хешем пункта — не принят",
              acc([verdict("accept", H1, criteria=both), verdict("accept", H1, agent="ag2",
                                                                  criteria=[crit("metis-0001", 1, A2)])])
              == {"metis-0001": {2: A2}})
        check("битые строки criteria пропускаются",
              acc([verdict("accept", H1, criteria=["мусор", 5, both[0]])]) == {"metis-0001": {1: A1}})
        check("criteria не список — ничего", acc([verdict("accept", H1, criteria=both[0])]) == {})
        check("«вернули» без «вернуть» на PR (returned_lie) — не в счёт",
              acc([verdict("accept", H1, criteria=both, returned=["zzzzzzzz/s9"])]) == {})
        check("review_criteria_ticks: строка кэша без head — пусто",
              P.review_criteria_ticks("latark/agent-kit", {"number": 7}) == {})
        # строка кэша до metis-1004 без поля core — как ядро: «принять» не на Opus не в счёт, на Opus — в счёт
        write_records(state, [verdict("accept", H1, criteria=both)])
        row = {"number": 7, "head": H1, "base": "main"}
        check("review_criteria_ticks: core False — «принять» не на Opus в счёт",
              P.review_criteria_ticks("latark/agent-kit", dict(row, core=False)) == want)
        check("review_criteria_ticks: строка кэша без core — как ядро, «принять» не на Opus не в счёт",
              P.review_criteria_ticks("latark/agent-kit", row) == {})
        check("review_criteria_ticks: core null — как ядро", P.review_criteria_ticks("latark/agent-kit", dict(row, core=None)) == {})
        write_records(state, [verdict("accept", H1, criteria=both, cl=OPUS)])
        check("review_criteria_ticks: строка кэша без core, «принять» на Opus — в счёт",
              P.review_criteria_ticks("latark/agent-kit", row) == want)
    finally:
        shutil.rmtree(tmp, True)


# --- merged_core: переименования и обрезанный список файлов (долг argus #401, Д1) --------------------------------------

def test_merged_core():
    import autoclose as A
    gate = A.load_gate()
    files_core = {c.casefold() for c in gate.CORE_FILES}
    core = lambda p: gate._is_core(p, files_core)  # noqa: E731 — как merge.is_core
    CORE, PAN = "plugins/guard/hooks/merge_gate.py", "plugins/pantheon/lib/pantheon.py"
    f = lambda path, ct="MODIFIED", **kw: dict({"path": path, "changeType": ct}, **kw)  # noqa: E731
    mc = A.merged_core
    check("merged_core: обычный файл — не ядро", mc([f("README.md")], core, 1) is False)
    check("merged_core: файл ядра — ядро", mc([f(CORE)], core, 1) is True)
    check("merged_core: pantheon.py — ядро", mc([f(PAN)], core, 1) is True)
    check("merged_core: sessions.py (BUILD_ROOTS шлюза) — ядро",
          mc([f("plugins/pantheon/lib/sessions.py")], core, 1) is True)
    check("merged_core: пустой PR — не ядро", mc([], core, 0) is False)
    check("merged_core: переименование без старого пути (gh pr list) — ядро", mc([f("docs/x.py", "RENAMED")], core, 1) is True)
    check("merged_core: копия без старого пути — ядро", mc([f("docs/x.py", "copied")], core, 1) is True)
    check("merged_core: переименование из ядра (previous_filename) — ядро",
          mc([f("docs/x.py", "RENAMED", previous_filename=CORE)], core, 1) is True)
    check("merged_core: previous_filename без changeType — старый путь тоже",
          mc([{"path": "docs/x.py", "previous_filename": PAN}], core, 1) is True)
    check("merged_core: переименование вне ядра с известным старым путём — не ядро",
          mc([f("docs/y.md", "RENAMED", previous_filename="docs/x.md")], core, 1) is False)
    many = [f(f"docs/f{i}.md") for i in range(A.FILES_CAP)]
    check("merged_core: changedFiles больше полученных (обрезка gh) — ядро", mc(many, core, 250) is True)
    check("merged_core: changedFiles меньше полученных — ядро", mc([f("a.md"), f("b.md")], core, 1) is True)
    check("merged_core: ровно 100 из 100 — не ядро", mc(many, core, A.FILES_CAP) is False)
    check("merged_core: 100 файлов без changedFiles — ядро (обрезку не исключить)", mc(many, core) is True)
    check("merged_core: 99 файлов без changedFiles — не ядро", mc(many[1:], core) is False)
    check("merged_core: changedFiles не число (True) — по числу полученных", mc(many[1:], core, True) is False
          and mc(many, core, True) is True)
    check("merged_core: файл без пути — ядро", mc([f("a.md"), {"path": None}], core, 2) is True)
    check("merged_core: строка файлов не словарь — ядро", mc([f("a.md"), "x"], core) is True)
    check("merged_core: files не список — ядро", mc(None, core, 0) is True)
    check("merged_core: core нет — ядро", mc([f("README.md")], None, 1) is True)


# --- autoclose: отметка при слиянии -------------------------------------------------------------------------------------

def mpr(n, body, head, files=("README.md",), base="main", branch="feature"):
    return {"number": n, "headRefName": branch, "headRefOid": head, "baseRefName": base, "body": body,
            "mergedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T0 - 600)), "mergeCommit": {"oid": "abcdef0123456"},
            "files": [{"path": f} for f in files], "isCrossRepository": False}


def test_autoclose():
    tmp, home, state, gh, env = make()
    try:
        H3, H4, H5, H6, H7 = ("3" * 40, "4" * 40, "5" * 40, "6" * 40, "7" * 40)
        pa = put(home, "metis-0001")   # оба «да» на head слияния → done
        pb = put(home, "metis-0002")   # «да» только по пункту 1 → review, неотмечен 2
        pc = put(home, "metis-0003")   # «принять» на другом head → ничего
        pd = put(home, "metis-0004")   # пункт 3, которого нет, и чужая задача → ничего
        pe = put(home, "metis-0005")   # пункт 1 изменён после приёмки → не отмечен
        pf = put(home, "metis-0006")   # ядро, «принять» не на Opus → ничего
        pg = put(home, "metis-0007")   # ядро, «принять» на Opus → done
        ph = put(home, "metis-0008")   # чужая задача: её пункты в записи PR 4, а в Closes её нет нигде → не тронута
        pi = put(home, "metis-0009")   # metis-1193: вне Closes, «пункты 1 и 2 metis-0009» в теле PR 1, приняты → done
        both = lambda tid: [crit(tid, 1, A1), crit(tid, 2, A2)]  # noqa: E731
        write_records(state, [
            verdict("accept", H1, pr=1, criteria=both("metis-0001") + both("metis-0009")),
            verdict("accept", H2, pr=2, criteria=[crit("metis-0002", 1, A1)]),
            verdict("accept", "9" * 40, pr=3, criteria=both("metis-0003")),
            verdict("accept", H4, pr=4, criteria=[crit("metis-0004", 3, A1), crit("metis-0008", 1, A1),
                                                     crit("metis-0008", 2, A2)]),
            verdict("accept", H5, pr=5, criteria=both("metis-0005")),
            verdict("accept", H6, pr=6, criteria=both("metis-0006")),
            verdict("accept", H7, pr=8, criteria=both("metis-0007"), cl=OPUS),
        ])
        b = text(pe).replace("- [ ] первый пункт: файл a.py", "- [ ] первый пункт: файл b.py")
        open(pe, "w", encoding="utf-8").write(b)
        core = ("plugins/guard/hooks/merge_gate.py",)
        with open(os.path.join(gh, "latark_agent-kit-merged.json"), "w", encoding="utf-8") as fh:
            json.dump([mpr(1, "Closes metis-0001\n\nпункты 1 и 2 metis-0009", H1), mpr(2, "Closes metis-0002", H2), mpr(3, "Closes metis-0003", H3),
                       mpr(4, "Closes metis-0004", H4), mpr(5, "Closes metis-0005", H5),
                       mpr(6, "Closes metis-0006", H6, files=core), mpr(8, "Closes metis-0007", H7, files=core),
                       dict(mpr(9, "", H1), files=[{"path": "docs/gate.py", "changeType": "RENAMED"}], changedFiles=1),
                       dict(mpr(10, "", H1), changedFiles=300)], fh)
        r = pan(env, "autoclose", "fetch")
        cache = json.load(open(os.path.join(state, "autoclose-prs.json"), encoding="utf-8"))
        row = next(x for x in cache["merged"]["latark/agent-kit"] if x["number"] == 6)
        check("fetch: в строке слитого PR head, base и core", row.get("head") == H6 and row.get("base") == "main"
              and row.get("core") is True and next(x for x in cache["merged"]["latark/agent-kit"]
                                                   if x["number"] == 1).get("core") is False, row)
        rows = {x["number"]: x for x in cache["merged"]["latark/agent-kit"]}
        check("fetch: переименование без старого пути и PR с обрезанным списком файлов — core",
              rows[9].get("core") is True and rows[10].get("core") is True, (rows[9], rows[10]))
        calls = [c for c in open(os.path.join(gh, "calls.log"), encoding="utf-8").read().splitlines()
                 if "--state merged" in c]
        check("fetch: слитые PR запрошены с headRefOid, baseRefName и changedFiles",
              calls and all("headRefOid" in c and "baseRefName" in c and "changedFiles" in c for c in calls), calls)
        st = lambda p: T.read(p)[0].get("status")  # noqa: E731
        check("все пункты «да» на head слияния → отмечены, задача done",
              st(pa) == "done" and text(pa).count("- [x]") == 2 and "отмечены пункты 1, 2" in text(pa),
              r.stdout + r.stderr + text(pa)[-500:])
        check("«да» по одному пункту → он отмечен, задача review с номером неотмеченного",
              st(pb) == "review" and "- [x] первый пункт" in text(pb) and "- [ ] второй пункт" in text(pb)
              and "слит, неотмечено 1 (пункты 2)" in text(pb), text(pb)[-500:])
        check("запись другого head не отмечает ничего",
              st(pc) == "review" and "[x]" not in text(pc) and "неотмечено 2 (пункты 1, 2)" in text(pc), text(pc)[-400:])
        check("пункт, которого нет в карточке, и пункт чужой задачи не отмечают ничего",
              st(pd) == "review" and "[x]" not in text(pd) and st(ph) == "doing" and "[x]" not in text(ph)
              and "отмечены" not in text(ph), text(pd)[-400:] + text(ph)[-400:])
        check("пункт изменён после приёмки — отметка снята (не отмечен), второй отмечен",
              st(pe) == "review" and "- [ ] первый пункт: файл b.py" in text(pe) and "- [x] второй пункт" in text(pe)
              and "неотмечено 1 (пункты 1)" in text(pe), text(pe)[-500:])
        check("ядро: «принять» не на Opus не отмечает", st(pf) == "review" and "[x]" not in text(pf), text(pf)[-400:])
        check("ядро: «принять» на Opus отмечает, задача done", st(pg) == "done" and text(pg).count("- [x]") == 2,
              text(pg)[-400:])
        check("1193: пункты задачи вне Closes, названные в теле PR и принятые argus на head, — отмечены, задача done "
              "(все пункты отмечены, PR в журнале)",
              st(pi) == "done" and text(pi).count("- [x]") == 2 and "названы в теле PR другой задачи" in text(pi)
              and "по приёмке argus (не Closes)" in r.stdout, r.stdout + r.stderr + text(pi)[-600:])
        check("строка прохода об отметке в выводе", "отмечены пункты 1, 2 по приёмке argus" in r.stdout, r.stdout)
    finally:
        shutil.rmtree(tmp, True)


def test_tick_failure():
    """Сбой отметки (не ValueError) не роняет проход: задача не тронута, PR повторим, ошибка в errors для тревоги."""
    import autoclose as A
    tmp, home, state, gh, env = make()
    try:
        os.environ.update(HOME=tmp, PANTHEON_HOME=home, PANTHEON_STATE=state, PANTHEON_VIEW=os.path.join(tmp, "view"))
        pa, pb = put(home, "metis-0011"), put(home, "metis-0012")
        calls = []

        def accepted(repo, pr):
            calls.append(repo)
            if len(calls) == 1:
                raise RuntimeError("сломалось")
            return {}

        log, errors = [], {}
        pr = dict(mpr(11, "Closes metis-0011, metis-0012", H1), head=H1)
        ok = A.close_pr(home, T0, "latark/agent-kit", pr, {"metis-pantheon"}, T, None, log, errors, accepted)
        err = errors.get("latark/agent-kit#11", "")
        check("сбой отметки: PR не отмечен обработанным, ошибка с задачей и типом в errors",
              ok is False and "metis-0011" in err and "RuntimeError: сломалось" in err, (ok, errors))
        check("сбой отметки: задача со сбоем не тронута", T.read(pa)[0].get("status") == "doing", text(pa)[-300:])
        check("сбой отметки: вторая задача того же PR обработана",
              T.read(pb)[0].get("status") == "review" and "неотмечено 2" in text(pb), text(pb)[-300:])
    finally:
        shutil.rmtree(tmp, True)


def test_named():
    """metis-1193: tick_named через close_pr с подставным accepted (без журнала шлюза): каждая ветка отбора."""
    import autoclose as A
    tmp, home, state, gh, env = make()
    try:
        os.environ.update(HOME=tmp, PANTHEON_HOME=home, PANTHEON_STATE=state, PANTHEON_VIEW=os.path.join(tmp, "view"))
        p = {i: put(home, f"metis-00{i}", status="done" if i == 26 else "review") for i in range(21, 28)}
        b = text(p[25]).replace("- [ ] первый пункт: файл a.py", "- [ ] первый пункт: файл c.py")
        open(p[25], "w", encoding="utf-8").write(b)
        both = {1: A1, 2: A2}
        acc = {f"metis-00{i}": dict(both) for i in (21, 22, 24, 25, 26, 27)}  # 23 — не принята

        def run(body, dirs=("metis-pantheon",), accepted=lambda repo, pr: acc, n=21):
            log, errors = [], {}
            pr = dict(mpr(n, body, H1), head=H1)
            ok = A.close_pr(home, T0, "latark/agent-kit", pr, set(dirs), T, None, log, errors, accepted)
            return ok, log, errors

        ok, log, errors = run("Closes metis-0021\nпункт 1 metis-0022\nпункты 1 и 2 metis-0023\nпункты 1, 2 metis-0024\n"
                              "пункт 1 metis-0025\nпункты 1 и 2 metis-0026\nсм. metis-0027")
        x = lambda i: text(p[i]).count("- [x]")  # noqa: E731
        check("1193: названный «пункт 1» при принятых 1 и 2 — отмечен только 1", ok and x(22) == 1
              and "- [x] первый пункт" in text(p[22]), (ok, errors, text(p[22])[-400:]))
        check("1193: названные без приёмки argus — не отмечены", x(23) == 0, text(p[23])[-300:])
        check("1193: «пункты 1, 2» — оба отмечены, строка прохода", x(24) == 2
              and any("metis-0024" in s and "(не Closes)" in s for s in log), (log, text(p[24])[-300:]))
        check("1193: текст пункта изменён после приёмки — не отмечен", x(25) == 0, text(p[25])[-300:])
        check("1193: задача done — не тронута", x(26) == 0 and "названы" not in text(p[26]), text(p[26])[-300:])
        check("1193: упомянута без «пункт N», хоть и принята — не отмечена", x(27) == 0, text(p[27])[-300:])
        put(home, "metis-0022", status="review")
        ok, log, errors = run("пункт 1 metis-0022", dirs=("other",), n=22)
        check("1193: задача не из направления репозитория — не отмечена", ok and x(22) == 0, text(p[22])[-300:])
        put(home, "metis-0027", status="review")
        ok, log, errors = run("Closes metis-0027, часть metis-0027\nпункт 1 metis-0027", n=23)
        check("1193: задача из Closes PR с «часть» по названию не отмечается (как Closes-путь)", ok and x(27) == 0,
              text(p[27])[-300:])

        def boom(repo, pr):
            raise RuntimeError("журнал не прочитан")
        ok, log, errors = run("пункт 1 metis-0022", accepted=boom, n=24)
        check("1193: сбой приёмки — PR не обработан, ошибка с типом в errors",
              ok is False and "RuntimeError: журнал не прочитан" in errors.get("latark/agent-kit#24", "")
              and x(22) == 0, (ok, errors))
        check("1193: named_items — «пункты 1, 2 и 4 X», регистр, повтор задачи сливает номера",
              A.named_items("Пункты 1, 2 и 4 metis-0001; пункт 7 metis-0001; пункт metis-0002") == {"metis-0001": {1, 2, 4, 7}},
              A.named_items("Пункты 1, 2 и 4 metis-0001; пункт 7 metis-0001; пункт metis-0002"))
    finally:
        shutil.rmtree(tmp, True)


def main():
    test_tasks_unit()
    test_review_cli()
    test_accepted_unit()
    test_merged_core()
    test_autoclose()
    test_tick_failure()
    test_named()
    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
