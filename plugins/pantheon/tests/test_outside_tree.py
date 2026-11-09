#!/usr/bin/env python3
"""Проверки вне окна роли, часть «запись по дереву и test --sha» (metis-0732, 0779; разрез test_outside.py — metis-0750).

Запуск: python3 -I plugins/pantheon/tests/test_outside_tree.py  (код выхода 0 — все прошли)
Проход переносит запись tests на новый head с тем же деревом (by_tree) и не переносит при красном прогоне, чужом дереве,
другом python (env), сбое записи, команде не из FULL_TESTS и записи с другой cmd; `test --sha` проверяет коммит PR в
копии прохода, а не в worktree окна. Заглушка sandbox-exec, ps-shim и помощники — в _outside_common.py, репозиторий kit — в
_outside_kit.py; у файла свой временный корень, порты не нужны, кроме общих проверок прохода.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311  # pantheon.py — только на Python 3.11+

if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)] + sys.argv[1:])

# ruff: noqa: F405
from _outside_common import *  # noqa: E402,F403  (__all__ модуля — все его имена, в том числе с «_»)
from _outside_kit import *  # noqa: E402,F403

_saved = open(_cp).read() if os.path.exists(_cp) else None
os.makedirs(qa, exist_ok=True)   # папку заявок окна athena-x в основном файле создаёт первая заявка роли

# --- 5d. запись по дереву (metis-0732) ------------------------------------------------
if os.path.exists(_cp):
    os.remove(_cp)
n1 = len(calls())
res = kit_request()
rk1 = tests_for(K1)
check("0732: прогон полного набора — запись с деревом и env (python, macOS)",
      res.get("record") and len(calls()) == n1 + 1 and rk1 and rk1[-1].get("tree") == git(KIT, "rev-parse", f"{K1}^{{tree}}")
      and rk1[-1]["env"].get("python") and "os" in rk1[-1]["env"], (res, rk1))
git(KIT, "-c", "user.name=t", "commit", "-q", "--amend", "-m", "k1 другое сообщение")
K2 = git(KIT, "rev-parse", "HEAD")
n1 = len(calls())
res = kit_request()
rk2 = tests_for(K2)
check("0732: новый head с тем же деревом — запись без прогона, отметка by_tree, шлюз её читает",
      K2 != K1 and res.get("state") == "done" and res.get("code") == 0 and res.get("record")
      and res.get("by_tree") == K1 and len(calls()) == n1 and len(rk2) == 1 and rk2[0].get("by_tree") == K1
      and rk2[0]["by"]["agent_type"] == "pantheon-outside" and rk2[0]["pr"] is None
      and rk2[0]["cmd"] == rk1[-1]["cmd"] and rk2[0]["tree"] == rk1[-1]["tree"], (res, rk2, len(calls()) - n1))
n1 = len(calls())
res = kit_request()
check("0732: тот же head ещё раз — запись уже есть, без прогона и без новой строки",
      res.get("state") == "done" and "уже есть" in res.get("note", "") and len(calls()) == n1 and len(tests_for(K2)) == 1,
      res)
K3 = commit(KIT, {"t.py": GREEN + "# k3\n"}, "k3")
n1 = len(calls())
res = kit_request()
check("0732: другое дерево — прогон", res.get("record") and len(calls()) == n1 + 1 and not res.get("by_tree"), res)
K4 = commit(KIT, {"t.py": RED}, "k4 red")
res = kit_request()
git(KIT, "-c", "user.name=t", "commit", "-q", "--amend", "-m", "k4 другое сообщение")
K5 = git(KIT, "rev-parse", "HEAD")
n1 = len(calls())
res = kit_request()
check("0732: красный прогон не переносится — тот же tree после красного идёт заново",
      res.get("code") == 1 and not res.get("record") and len(calls()) == n1 + 1 and not tests_for(K5), res)
# поле tree записи сверяется с git: запись другого коммита с чужим tree (подложено, сбой) не переносится
with open(RECORDS, "a") as fh:
    fh.write(json.dumps({"v": 1, "kind": "tests", "repo": ["latark/kit"], "pr": None, "sha": K3,
                         "by": {"agent_type": "pantheon-outside", "agent_id": "", "session_id": "", "request": "x"},
                         "cmd": rk1[-1]["cmd"], "tree": git(KIT, "rev-parse", f"{K5}^{{tree}}"),
                         "env": O.run_env(rk1[-1]["cmd"])}) + "\n")
git(KIT, "-c", "user.name=t", "commit", "-q", "--amend", "-m", "k5 ещё сообщение")
n1 = len(calls())
res = kit_request()
check("0732: tree в записи не совпал с деревом её коммита по git — прогон, а не перенос",
      len(calls()) == n1 + 1 and not res.get("by_tree"), res)
K6 = commit(KIT, {"t.py": GREEN + "# k6\n"}, "k6")
kit_request()
git(KIT, "-c", "user.name=t", "commit", "-q", "--amend", "-m", "k6 другое сообщение")
_re = O.run_env
O.run_env = lambda line: {**_re(line), "python": "/other/python3.15"}
n1 = len(calls())
res = kit_request()
O.run_env = _re
check("0732: другой python (env) — прогон, а не перенос", len(calls()) == n1 + 1 and not res.get("by_tree"), res)
# сбой записи переноса (OSError) — не итог «записано», а обычный прогон
git(KIT, "-c", "user.name=t", "commit", "-q", "--amend", "-m", "k6 третье сообщение")
_at = O.append_tests


def _at_fail(*a, **kw):
    if kw.get("by_tree"):
        raise OSError("сбой диска")
    return _at(*a, **kw)


O.append_tests = _at_fail
n1 = len(calls())
res = kit_request()
O.append_tests = _at
check("0732: запись переноса не легла (OSError) — прогон, итог по нему, а не «без прогона»",
      len(calls()) == n1 + 1 and res.get("record") and not res.get("by_tree"), res)
# команда — не полный набор репозитория: не переносится (latark/app нет в FULL_TESTS)
git(APP, "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "app пусто")
git(APP, "-c", "user.name=t", "commit", "-q", "--amend", "--allow-empty", "-m", "app пусто 2")
r_x = one_request()
run_pass()
r_y = one_request()
n1 = len(calls())
run_pass()
check("0732: команда не из FULL_TESTS — повторный head того же дерева гоняется",
      len(calls()) == n1 + 1 and not (O.load_result(qa, r_y) or {}).get("by_tree"), O.load_result(qa, r_y))

# Д2: зелёная запись прохода с другой cmd на том же дереве не переносится — идёт прогон
K8 = commit(KIT, {"t.py": GREEN + "# k8\n"}, "k8")
_line = O.command(KIT, "test")[1]
with open(RECORDS, "a") as fh:
    fh.write(json.dumps({"v": 1, "kind": "tests", "repo": ["latark/kit"], "pr": None, "sha": K8,
                         "by": {"agent_type": "pantheon-outside", "agent_id": "", "session_id": "", "request": "x"},
                         "cmd": "heavy python3 other.py", "tree": git(KIT, "rev-parse", f"{K8}^{{tree}}"),
                         "env": O.run_env(_line)}) + "\n")
n1 = len(calls())
res = kit_request()
check("0732: запись прохода с другой cmd на том же дереве — прогон, а не перенос",
      len(calls()) == n1 + 1 and res.get("record") and not res.get("by_tree") and "уже есть" not in res.get("note", ""), res)

if _saved is not None:
    with open(_cp, "w") as fh:
        fh.write(_saved)
elif os.path.exists(_cp):
    os.remove(_cp)

# --- 5e. test --sha (metis-0779): проверка на коммите PR в своей копии прохода, а не в worktree окна ----------------
# окно не переключит свою worktree на ветку PR, если там другой .claude/ проекта (запись закрыта) — копия прохода
# на этом коммите, полное дерево вместе с .claude/; запись tests — на этот SHA, копия снимается
_saved_e = open(_cp).read() if os.path.exists(_cp) else None
if os.path.exists(_cp):
    os.remove(_cp)
HEADE = git(APP, "rev-parse", "HEAD")
git(APP, "switch", "-q", "-c", "pr-0779")
# тест проходит, только если в дереве есть .claude/skills проекта: копия — полное дерево коммита, а не HEAD папки
CPG = commit(APP, {".claude/skills/s/SKILL.md": "навык\n",
                   "t.py": "import os, sys; sys.exit(0 if os.path.isfile('.claude/skills/s/SKILL.md') else 4)\n"},
             "pr: .claude/skills")
CPR = commit(APP, {"t.py": RED}, "pr: red")
git(APP, "switch", "-q", "main")
check("0779: HEAD папки — не коммит PR, .claude/skills в папке нет",
      git(APP, "rev-parse", "HEAD") == HEADE and not os.path.exists(os.path.join(APP, ".claude", "skills")))




def sha_request(sha, label):
    """Заявка роли test --sha → (код CLI, папка, ID, итог прохода)."""
    q2, rid2 = new_request("athena-x", APP, "test", "--sha", sha)
    req2 = json.load(open(os.path.join(q2, rid2 + ".req.json")))
    check(f"0779: {label}: заявка несёт полный SHA и pin", req2.get("pin") is True and sha_full(req2.get("sha")), req2)
    run_pass()
    return q2, rid2, O.load_result(q2, rid2) or {}


def sha_full(s):
    return isinstance(s, str) and len(s) == 40


n0 = len(tests_for(CPG))
c0 = len(calls())
qs, rs, res = sha_request(CPG[:10], "зелёный")
ran = [c for c in calls()[c0:] if "t.py" in " ".join(c["cmd"])]
rec = tests_for(CPG)
check("0779: --sha: прогон в копии test-<ID> на этом коммите (.claude/skills на месте), код 0, запись на полный SHA",
      res.get("state") == "done" and res.get("code") == 0 and res.get("record") is True and res.get("sha") == CPG
      and res.get("src") == APP and res.get("dir") == test_work(rs) and ran and ran[-1]["cwd"] == test_work(rs)
      and len(rec) == n0 + 1 and rec[-1]["cwd"] == test_work(rs) and rec[-1]["repo"] == ["latark/app"],
      (res, ran[-1:] and ran[-1]["cwd"], rec[-1:]))
check("0779: --sha: копия снята (папка и worktree клона), HEAD и дерево папки не тронуты",
      not os.path.exists(test_work(rs)) and "test-" + rs not in worktrees()
      and git(APP, "rev-parse", "HEAD") == HEADE and O.head_state(APP) == (HEADE, True), worktrees())
check("0779: --sha: зависимости копии ставит проход (package.json без node_modules)",
      any(c["cwd"] == test_work(rs) and c["cmd"][1:2] in (["ci"], ["install"]) for c in calls()[c0:]))
qs, rs, res = sha_request(CPR, "красный")
check("0779: --sha красный: код 1, записи нет, копия снята", res.get("state") == "done" and res.get("code") == 1
      and res.get("record") is False and not tests_for(CPR) and not os.path.exists(test_work(rs)), res)

# установка зависимостей (lifecycle-скрипты пакета) сдвинула HEAD копии или правит дерево — ни прогона, ни записи
_prep = O.prepare
for label, spoil in (("сдвинула HEAD копии на другой зелёный коммит",
                      lambda w: git(w, "checkout", "-q", "--detach", HEADE)),
                     ("правит отслеживаемый файл копии", lambda w: _touch(w, "t.py", GREEN))):
    O.prepare = lambda d, rid, _spoil=spoil, **kw: (_prep(d, rid, **kw), _spoil(str(d)))[0]
    n_e, c0 = len(tests_for(HEADE)), len(calls())
    try:
        qs, rs, res = sha_request(CPG, label)
    finally:
        O.prepare = _prep
    check(f"0779: установка {label} — failed, прогона и записи нет, копия снята", res.get("state") == "failed"
          and "прогона и записи нет" in res.get("why", "") and res.get("sha") == CPG
          and not [c for c in calls()[c0:] if "t.py" in " ".join(c["cmd"])]
          and len(tests_for(HEADE)) == n_e and not os.path.exists(test_work(rs)), res)

# HEAD копии сдвинулся уже после первой проверки — перед прогоном (между tree_record и чтением HEAD) или во время
# прогона: запись только на коммит заявки, на сдвинутый HEAD — никогда
_tr, _wp, _rt = O.tree_record, O.wait_proc, O.run_test
_cwd_of = [None]  # папка прогона для подмены wait_proc; вне цикла, чтобы лямбды не держали переменную цикла (B023)


def _move_head(d):
    git(str(d), "checkout", "-q", "--detach", HEADE)


for label, attr, fake in (
        ("перед прогоном", "tree_record", lambda rid, d, *a, **kw: (_move_head(d), _tr(rid, d, *a, **kw))[1]),
        # wait_proc зовёт и установка (prepare) — HEAD двигаем только в прогоне теста (у него idle_log)
        ("во время прогона", "wait_proc",
         lambda proc, *a, **kw: (kw.get("idle_log") and _move_head(_cwd_of[0]), _wp(proc, *a, **kw))[1])):
    _cwd_of[0] = None
    O.run_test = lambda rid, d, *a, **kw: (_cwd_of.__setitem__(0, str(d)), _rt(rid, d, *a, **kw))[1]
    setattr(O, attr, fake)
    n_e, n_g = len(tests_for(HEADE)), len(tests_for(CPG))
    try:
        qs, rs, res = sha_request(CPG, f"HEAD сдвинут {label}")
    finally:
        O.tree_record, O.wait_proc, O.run_test = _tr, _wp, _rt
    check(f"0779: HEAD копии сдвинут {label} — записи нет ни на сдвинутый HEAD, ни на SHA заявки",
          res.get("record") is not True and len(tests_for(HEADE)) == n_e and len(tests_for(CPG)) == n_g
          and res.get("sha") == CPG and not os.path.exists(test_work(rs)), res)

# остатки установки (фоновый процесс с cwd в копии) гаснут до прогона, а не только при уборке копии
_bg = []


def _prep_bg(d, rid, **kw):
    code = _prep(d, rid, **kw)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=str(d), start_new_session=True)
    TEST_PROCS.append(p)
    _bg.append(p)
    return code


_seen = []
_rt = O.run_test
O.prepare = _prep_bg
O.run_test = lambda *a, **kw: (_seen.append(_bg[-1].poll() is not None or not still_alive(_bg[-1].pid, 0)),
                               _rt(*a, **kw))[1]
try:
    qs, rs, res = sha_request(CPG, "остатки установки")
finally:
    O.prepare, O.run_test = _prep, _rt
check_mac("0779: процесс установки с cwd в копии погашен до прогона теста (reap после prepare)",
          _seen == [True] and res.get("code") == 0, (_seen, res))

# tree_record копии — на коммите заявки, HEAD папки не читается: перенос по дереву на SHA, а не на HEAD
git(KIT, "switch", "-q", "-c", "pr-0779")
KA = commit(KIT, {"t.py": GREEN + "# ka\n"}, "ka")
kit_request()   # зелёный полный набор на KA — запись с деревом
git(KIT, "-c", "user.name=t", "commit", "-q", "--amend", "-m", "ka другое сообщение")
KB = git(KIT, "rev-parse", "HEAD")
git(KIT, "switch", "-q", "main")
c0 = len(calls())
res = O.tree_record("20261104-020202-c0c0c0", KIT, "metis-k", None, sha=KB)
rkb = tests_for(KB)
check("0779: tree_record(sha=) — запись на этот SHA по дереву, без прогона, HEAD папки другой",
      git(KIT, "rev-parse", "HEAD") != KB and (res or {}).get("by_tree") == KA and (res or {}).get("sha") == KB
      and len(rkb) == 1 and rkb[0].get("by_tree") == KA and len(calls()) == c0, (res, rkb))

# неверный и чужой SHA — отказ на месте, заявки нет
for bad, label in (("deadbeef1", "коммита нет в копии"), ("xyz;rm", "не по образцу"), (CPG[:5], "короче 7 знаков")):
    _q = os.path.join(CACHE, "athena-x", "outside")
    before = set(os.listdir(_q))
    _e = io.StringIO()
    with contextlib.redirect_stderr(_e):
        rc, _, _ = role_request("athena-x", APP, "test", "--sha", bad)
    check(f"0779: --sha {label}: код 2, заявки нет, причина — не коммит этой копии",
          rc == 2 and "не коммит этой копии" in _e.getvalue()
          and not [n for n in set(os.listdir(_q)) - before if n.endswith(".req.json")], (rc, _e.getvalue()))
# заявка в обход CLI с коммитом, которого нет в клоне: проход отказывает, копии нет, прогона нет
c0 = len(calls())
one_request.n += 1
rid_x = f"20261104-0{one_request.n:05d}-e0e0e0"
with open(os.path.join(qa, rid_x + ".req.json"), "w") as fh:
    json.dump({"v": 1, "id": rid_x, "kind": "test", "dir": APP, "sha": "deadbeef1", "pin": True,
               "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, fh)
run_pass()
res = O.load_result(qa, rid_x) or {}
check("0779: pin на коммит не из клона — failed «git fetch», копии и прогона нет", res.get("state") == "failed"
      and "git fetch" in res.get("why", "") and len(calls()) == c0 and not os.path.exists(test_work(rid_x)), res)
check("0779: pin — только true и только у test с коммитом",
      O.check_request({"v": 1, "id": "x", "kind": "serve", "dir": APP, "sha": CPG, "pin": True}, "x")
      and O.check_request({"v": 1, "id": "x", "kind": "test", "dir": APP, "sha": CPG, "pin": 1}, "x")
      and O.check_request({"v": 1, "id": "x", "kind": "test", "dir": APP, "pin": True}, "x")
      and not O.check_request({"v": 1, "id": "x", "kind": "test", "dir": APP, "sha": CPG, "pin": True}, "x"))

# бывший head открытого PR — отказ без копии, как у test без --sha (metis-0726)
put_cache(old_heads={"latark/app": {CPG: 5}}, prs={"latark/app": [{"number": 5, "head": NEWH}]})
c0 = len(calls())
qs, rs, res = sha_request(CPG, "устаревший head")
check("0779: --sha на бывший head PR — failed «head устарел», прогона нет", res.get("state") == "failed"
      and "head устарел" in res.get("why", "") and len(calls()) == c0 and not os.path.exists(test_work(rs)), res)
os.remove(_cp)

# тот же SHA ещё в очереди — второй заявки нет (live_test, metis-0706)
q1, r1 = new_request("athena-x", APP, "test", "--sha", CPR[:12])
_q = os.path.join(CACHE, "athena-x", "outside")
before = {n for n in os.listdir(_q) if n.endswith(".req.json")}
rc, _, _ = role_request("athena-x", APP, "test", "--sha", CPR)
check("0779: --sha тот же коммит в очереди — новой заявки нет, код 0",
      rc == 0 and {n for n in os.listdir(_q) if n.endswith(".req.json")} == before, rc)
# заявка без --sha на ту же папку не снимает ждущую --sha как дубль (тест не на HEAD папки)
r0 = one_request()   # ID 20261103-… — раньше r1 (время сейчас): идёт первой и зовёт drop_dupes при ждущей r1
check("0779: обычная заявка в очереди раньше --sha", r0 < r1, (r0, r1))
run_pass()
check("0779: обычная заявка и --sha на той же папке — обе прогнаны, --sha не снята как дубль",
      (O.load_result(q1, r1) or {}).get("sha") == CPR and (O.load_result(q1, r1) or {}).get("state") == "done"
      and not (O.load_result(q1, r1) or {}).get("dup") and (O.load_result(qa, r0) or {}).get("state") == "done",
      (O.load_result(q1, r1), O.load_result(qa, r0)))

# metis-0796 Д2: заявка --sha и обычная на одном SHA из одной папки не сцепляются в обе стороны (у --sha своя копия,
# у обычной — дерево папки): HEAD папки — на CPG, обе заявки получают свой ID
git(APP, "switch", "-q", "--detach", CPG)
_q = os.path.join(CACHE, "athena-x", "outside")


def reqs():
    return {n for n in os.listdir(_q) if n.endswith(".req.json")}


for first, second, label in ((("--sha", CPG), (), "--sha, затем обычная"), ((), ("--sha", CPG), "обычная, затем --sha")):
    before = reqs()
    new_request("athena-x", APP, "test", *first)
    mid = reqs()
    rc, _, _ = role_request("athena-x", APP, "test", *second)
    check(f"0796: {label} на одном SHA и папке — две заявки, не одна", rc == 0 and len(mid - before) == 1
          and len(reqs() - before) == 2, (rc, before, mid, reqs()))
    run_pass()
# две обычные на одном HEAD по-прежнему сцеплены (live_test не сломан)
new_request("athena-x", APP, "test")
before = reqs()
role_request("athena-x", APP, "test")
check("0796: две обычные на одном HEAD — вторая не плодит заявку", reqs() == before, (before, reqs()))
run_pass()

# metis-0798 Д1: итог running заявки --sha несёт pin, и обычная заявка при нём не сцепляется (мутант «pin убран из
# running» в run_test, outside.py: extra["pin"] = True)
_runs, _save0 = [], O.save_result


def _save_spy(qdir, rid, res):
    if res.get("state") == "running":
        _runs.append((qdir, rid, dict(res)))
    return _save0(qdir, rid, res)


O.save_result = _save_spy
try:
    q_pin, r_pin = new_request("athena-x", APP, "test", "--sha", CPG)
    run_pass()
finally:
    O.save_result = _save0
_run_pin = [r for r in _runs if r[1] == r_pin]
check("0798: итог running заявки --sha несёт pin: true", bool(_run_pin) and all(r[2].get("pin") is True for r in _run_pin),
      _runs)
_fake = "20261103-099999-feedfa"
_res_pin = {**_run_pin[-1][2], "id": _fake, "src": APP, "updated": P.stamp()}
with open(os.path.join(q_pin, _fake + ".result.json"), "w") as fh:
    json.dump(_res_pin, fh)
before = reqs()
rc, _, _ = role_request("athena-x", APP, "test")
check("0798: обычная заявка при running --sha на том же SHA — новая заявка, не сцепление",
      rc == 0 and len(reqs() - before) == 1, (rc, before, reqs()))
before = reqs()
role_request("athena-x", APP, "test", "--sha", CPG)
check("0798: --sha при running --sha на том же SHA — сцеплена, новой заявки нет", reqs() == before, (before, reqs()))
# и обратно: running обычной заявки не сцепляет --sha
with open(os.path.join(q_pin, _fake + ".result.json"), "w") as fh:
    json.dump({k: v for k, v in _res_pin.items() if k != "pin"}, fh)
before = reqs()
role_request("athena-x", APP, "test", "--sha", CPG)
check("0798: --sha при running обычной на том же SHA — новая заявка", len(reqs() - before) == 1, (before, reqs()))
os.remove(os.path.join(q_pin, _fake + ".result.json"))
for _n in reqs():   # ждущие заявки этого блока снимаем: дальше блоки считают очередь сами
    try:
        os.remove(os.path.join(_q, _n))
    except OSError:
        pass
git(APP, "switch", "-q", "main")

# metis-0796 Д1: refs/replace в клоне подменяет содержимое копии при том же HEAD и чистом status — копия идёт с
# --no-replace-objects: красный CPR остаётся красным, записи tests нет
def _blob(text):
    return subprocess.run(["git", "-C", APP, "hash-object", "-w", "--stdin"], input=text, text=True,
                          capture_output=True, check=True).stdout.strip()


git(APP, "replace", _blob(RED), _blob(GREEN))
try:
    n_r = len(tests_for(CPR))
    qs, rs, res = sha_request(CPR, "refs/replace в клоне")
finally:
    git(APP, "replace", "-d", _blob(RED))
check("0796: refs/replace в клоне — копия с настоящим деревом, красный код 1, записи tests нет",
      res.get("state") == "done" and res.get("code") == 1 and res.get("record") is False
      and len(tests_for(CPR)) == n_r, res)

# metis-0796 Д3: копия оказалась worktree другого клона (trusted_clone подменён) — отказ, прогона и записи нет
_tc = O.trusted_clone


def _other_clone(w, *a, **kw):
    r = _tc(w, *a, **kw)
    if os.path.basename(str(w)).startswith("test-"):
        return r[0], os.path.join(HOME, "elsewhere", ".git"), r[2]
    return r


O.trusted_clone = _other_clone
try:
    c0, n_g = len(calls()), len(tests_for(CPG))
    qs, rs, res = sha_request(CPG, "копия — worktree другого клона")
finally:
    O.trusted_clone = _tc
check("0796: копия — worktree другого клона — failed «не worktree клона», прогона и записи нет, копия снята",
      res.get("state") == "failed" and "не worktree клона" in res.get("why", "")
      and not [c for c in calls()[c0:] if "t.py" in " ".join(c["cmd"])] and len(tests_for(CPG)) == n_g
      and not os.path.exists(test_work(rs)), res)

# брошенная копия упавшего прохода — снимает следующий проход тестов; чужие имена в work не трогает
_orph = test_work("20261104-010101-abcdef")
_keep = os.path.join(os.path.dirname(_orph), "test-not-an-id")
os.makedirs(_orph)
os.makedirs(_keep)
run_pass()
check("0779: брошенная копия test-<ID> снята проходом тестов, test-<не ID> не тронута",
      not os.path.exists(_orph) and os.path.isdir(_keep))
shutil.rmtree(_keep, ignore_errors=True)

if _saved_e is not None:
    with open(_cp, "w") as fh:
        fh.write(_saved_e)


kill_all_servers()
_left = [p for p in fake_pids() if still_alive(p)]
if _left or not fake_pids():   # то же условие, что проверка «сирот» в test_outside.py; здесь — только провал
    check("тесты не оставляют процессов: заглушка sandbox-exec и задачи «turbo» погашены (tree)", False, (_left, len(fake_pids())))

print(f"{TOTAL[0] - len(FAILS) - len(SKIPPED_BIND)} из {TOTAL[0]} прошли"
      + (f", пропущено при закрытом bind: {len(SKIPPED_BIND)}" if SKIPPED_BIND else ""))
sys.exit(1 if FAILS else 0)
