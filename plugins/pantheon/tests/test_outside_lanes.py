#!/usr/bin/env python3
"""Две дорожки очереди outside (metis-1081, lib/outside.py: LANES, lane_of, cmd_run(lane), requests(lane=…)).

Запуск: python3 -I plugins/pantheon/tests/test_outside_lanes.py  (код выхода 0 — все прошли)
Проверяет: дорожка заявки — full у проверки проекта с полным набором в FULL_TESTS, quick у --affected, --script,
других проектов и неразборчивой папки, битая — full; заявка другого проекта стартует и кончается зелёной с записью
tests, пока идёт полный набор, а полный набор после этого не снят; две заявки quick не идут сразу (второй проход
дорожки выходит с 0, заявка лежит), проход full чужую дорожку не берёт; «стоп» снимает идущий прогон в обеих
дорожках; замена заявки на предке и сцепка с идущей заявкой работают в обеих дорожках; ждущий спада полный набор
уступает только своей дорожке (Defer); «заход прерван», уборка копий test --sha, сторож и тик берут свою дорожку;
взятая заявка не считается потерянной проходом другой дорожки. Общая часть — _outside_common.py, kit — _outside_kit.py.
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

O.load_state = lambda: (0.0, 10.0)   # нагрузка Mac тесту не нужна: полный набор под нагрузкой ждал бы спада
O.SUPERSEDE_EVERY, O.PROCS_EVERY = 1, 1
qother = os.path.join(CACHE, "metis-y", "outside")
for _d in (qkit, qa, qother):
    os.makedirs(_d, exist_ok=True)
N = [0]


def put_req(qd, d, **extra):
    """Заявка test в папке qd на папку d с id по счётчику (позже — больше)."""
    N[0] += 1
    rid = f"20261113-{N[0]:06d}-1a2b3c"
    req = {"v": 1, "id": rid, "kind": "test", "dir": d, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **extra}
    with open(os.path.join(qd, rid + ".req.json"), "w") as fh:
        json.dump(req, fh)
    return rid


def block(tag):
    """t.py: отмечает старт и ждёт файла lane-<tag>-go (не дольше 60 с), затем код 0."""
    return (f"import os, sys, time\nR = {_ROOT!r}\nopen(os.path.join(R, 'lane-{tag}-started'), 'a').write('x\\n')\n"
            f"end = time.time() + 60\nwhile time.time() < end and not os.path.exists(os.path.join(R, 'lane-{tag}-go')):\n"
            "    time.sleep(0.1)\nsys.exit(0)\n")


def started(tag):
    return os.path.exists(os.path.join(_ROOT, f"lane-{tag}-started"))


def release(tag):
    open(os.path.join(_ROOT, f"lane-{tag}-go"), "w").close()


def bg(fn, *a):
    out = {}
    th = threading.Thread(target=lambda: out.update(rc=fn(*a)), daemon=True)
    th.start()
    return th, out


def runs(rid):
    return P.read_json(O.root("runs", rid + ".json"), {}) or {}


def has_req(qd, rid):
    return os.path.isfile(os.path.join(qd, rid + ".req.json"))


def req_of(qd, rid):
    with open(os.path.join(qd, rid + ".req.json")) as fh:
        return json.load(fh)


def cli_test(window, cwd):
    """`pantheon outside test` из окна → (код, вывод, новые .req.json в папке окна)."""
    q = os.path.join(CACHE, window, "outside")
    before = {n for n in os.listdir(q) if n.endswith(".req.json")}
    os.environ["PANTHEON_TMP"] = os.path.join(CACHE, window, "tmp")
    old, buf = os.getcwd(), io.StringIO()
    os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(buf):
            rc = O.main(["test"])
    finally:
        os.chdir(old)
        os.environ.pop("PANTHEON_TMP")
    return rc, buf.getvalue(), sorted(n[:-9] for n in os.listdir(q) if n.endswith(".req.json") and n not in before)


# --- 1. дорожка заявки ----------------------------------------------------------------------------------------------
_rk, _ra = put_req(qkit, KIT), put_req(qa, APP)
check("lane_of: проверка проекта с полным набором в FULL_TESTS — full",
      O.lane_of(req_of(qkit, _rk), "metis-k", _rk) == "full", req_of(qkit, _rk))
check("lane_of: другой проект (без FULL_TESTS) — quick", O.lane_of(req_of(qa, _ra), "athena-x", _ra) == "quick")
_base = {"v": 1, "id": _rk, "kind": "test", "dir": KIT}
check("lane_of: --affected (base) и --script того же репозитория — quick",
      O.lane_of({**_base, "base": "a" * 40}, "metis-k", _rk) == "quick"
      and O.lane_of({**_base, "script": "lint"}, "metis-k", _rk) == "quick")
check("lane_of: папка не из реестра окна — quick (отказ придёт сразу), битая заявка — full",
      O.lane_of({**_base, "dir": "/nonexistent/x"}, "metis-k", _rk) == "quick"
      and O.lane_of({"v": 2}, "metis-k", _rk) == "full" and O.lane_of(None, "metis-k", _rk) == "full")
check("_queued_ids по дорожке: заявка kit — только full, заявка app — только quick",
      (_rk, "test") in O._queued_ids(("test",), lane="full") and (_ra, "test") not in O._queued_ids(("test",), lane="full")
      and (_ra, "test") in O._queued_ids(("test",), lane="quick")
      and (_rk, "test") not in O._queued_ids(("test",), lane="quick"))
check("тик: заявка другого проекта — дело дорожке quick", O.pending_quick() is True)

# Defer уступает только своей дорожке: ждущий полный набор не отдаёт очередь заявке quick (она идёт своим проходом)
os.remove(os.path.join(qkit, _rk + ".req.json"))
check("Defer full: в очереди только заявка quick — уступать некому (иначе набор крутился бы на ней)",
      O.Defer(qkit, "20261113-999999-1a2b3c", {}, {}, lane="full").others() is False)
check("Defer quick и Defer без дорожки видят заявку quick",
      O.Defer(qkit, "20261113-999999-1a2b3c", {}, {}, lane="quick").others() is True
      and O.Defer(qkit, "20261113-999999-1a2b3c", {}, {}).others() is True)
_rk2 = put_req(qkit, KIT)
check("Defer full: в очереди другая заявка full — уступает", O.Defer(qkit, "20261113-999999-1a2b3c", {}, {},
                                                                    lane="full").others() is True)
for _q, _r in ((qkit, _rk2), (qa, _ra)):
    os.remove(os.path.join(_q, _r + ".req.json"))

# --- 2. заявка другого проекта идёт, пока идёт полный набор ----------------------------------------------------------
KF1 = commit(KIT, {"t.py": block("f1")}, "lanes f1")
APP_G1 = commit(APP, {"t.py": GREEN + "# lanes g1\n"}, "lanes g1")
r_full = put_req(qkit, KIT)
th, out = bg(O.cmd_run)
up = wait_for(lambda: state(qkit, r_full) == "running" and started("f1"), 30)
check("полный набор kit взят дорожкой full и идёт", up, O.load_result(qkit, r_full))
rc, outp, new = cli_test("metis-k", KIT)
check("сцепка в дорожке full: тот же head идёт — новой заявки нет, в выводе ID идущей",
      rc == 0 and new == [] and r_full in outp, (rc, outp, new))
r_quick = put_req(qa, APP)
check("тик: пока проход full держит замок, дорожка quick не занята — её проход зовётся",
      P.locked("outside-run") and not P.locked("outside-quick") and O.pending_quick())
rc = O.cmd_run("quick")
rq = O.load_result(qa, r_quick) or {}
check("1081: заявка другого проекта стартует и кончается, пока идёт полный набор — done, код 0, запись tests",
      rc == 0 and rq.get("state") == "done" and rq.get("code") == 0 and rq.get("record") is True
      and bool(tests_for(APP_G1)) and th.is_alive(), (rc, rq, th.is_alive()))
check("1081: проход quick не тронул идущий полный набор (recover_results своей дорожки) — running",
      state(qkit, r_full) == "running" and runs(r_full).get("state") == "running", O.load_result(qkit, r_full))
check("1081: запись в runs/ несёт дорожку — full у набора, quick у другой",
      runs(r_full).get("lane") == "full" and runs(r_quick).get("lane") == "quick", (runs(r_full), runs(r_quick)))
release("f1")
th.join(30)
rf = O.load_result(qkit, r_full) or {}
check("полный набор после прохода quick кончается сам: done, код 0, запись tests",
      not th.is_alive() and out.get("rc") == 0 and rf.get("state") == "done" and rf.get("code") == 0
      and rf.get("record") is True and bool(tests_for(KF1)), (rf, out))

# --- 3. две заявки quick не идут одновременно; full чужую дорожку не берёт ---------------------------------------------
commit(APP, {"t.py": block("q2")}, "lanes q2")
r_a = put_req(qa, APP)
r_b = put_req(qother, OTHER)
th, out = bg(O.cmd_run, "quick")
up = wait_for(lambda: state(qa, r_a) == "running" and started("q2"), 30)
check("первая заявка quick идёт", up, O.load_result(qa, r_a))
rc, outp, new = cli_test("athena-x", APP)
check("сцепка в дорожке quick: тот же head идёт — новой заявки нет, в выводе ID идущей",
      rc == 0 and new == [] and r_a in outp, (rc, outp, new))
rc2 = O.cmd_run("quick")
check("1081: второй проход quick, пока идёт первый, — код 0, вторая заявка лежит и не начата",
      rc2 == 0 and has_req(qother, r_b) and state(qother, r_b) is None and state(qa, r_a) == "running",
      (rc2, O.load_result(qother, r_b)))
rc3 = O.cmd_run()
check("1081: проход full заявку quick не берёт и идущий прогон quick не трогает",
      rc3 == 0 and has_req(qother, r_b) and state(qa, r_a) == "running" and runs(r_a).get("state") == "running",
      (rc3, O.load_result(qa, r_a)))
os.environ["PANTHEON_DRYRUN"] = "1"
open(P.path("dryrun.log"), "w").close()
P.outside_kick()
_dry = open(P.path("dryrun.log")).read()
check("тик: проход quick идёт (замок outside-quick) — второй экземпляр дорожки не зовётся", "outside-quick" not in _dry,
      _dry)
os.environ.pop("PANTHEON_DRYRUN")
release("q2")
th.join(30)
rb = O.load_result(qother, r_b) or {}
check("тот же проход quick после первой берёт вторую: обе done", not th.is_alive() and state(qa, r_a) == "done"
      and rb.get("state") == "done" and rb.get("code") == 0 and not has_req(qother, r_b), (O.load_result(qa, r_a), rb))

# тик: только заявка quick — зовётся проход quick, а не full; проход full идёт — quick всё равно зовётся
r_t = put_req(qother, OTHER)
os.environ["PANTHEON_DRYRUN"] = "1"
open(P.path("dryrun.log"), "w").close()
_sv = (O.overdue_accepts, O._stale, O._watch_due)
O.overdue_accepts, O._stale, O._watch_due = (lambda *a, **k: []), (lambda *a, **k: []), (lambda *a, **k: [])
try:
    P.outside_kick()
    _dry = open(P.path("dryrun.log")).read()
    check("тик: в очереди только заявка quick — зовётся `outside run --quick`, проход full — нет",
          "outside-quick" in _dry and "outside-run" not in _dry, _dry)
    with P.lock("outside-run", block=False) as _got:
        open(P.path("dryrun.log"), "w").close()
        P.outside_kick()
        check("тик: проход full держит замок — проход quick зовётся всё равно",
              _got and "outside-quick" in open(P.path("dryrun.log")).read())
finally:
    O.overdue_accepts, O._stale, O._watch_due = _sv
    os.environ.pop("PANTHEON_DRYRUN")
check("outside run --quick вне окна Claude Code — проход дорожки, код 0", O.main(["run", "--quick"]) == 0
      and state(qother, r_t) == "done")
os.environ["CLAUDECODE"] = "1"
check("outside run --quick из окна Claude Code: код 2", O.main(["run", "--quick"]) == 2)
os.environ.pop("CLAUDECODE")

# --- 4. «стоп» в обеих дорожках ---------------------------------------------------------------------------------------
for lane, window, qd, d, tag in (("full", "metis-k", qkit, KIT, "s-full"), ("quick", "athena-x", qa, APP, "s-quick")):
    sha = commit(d, {"t.py": block(tag)}, "lanes " + tag)
    r = put_req(qd, d)
    th, out = bg(O.cmd_run, lane)
    up = wait_for(lambda qd=qd, r=r, tag=tag: state(qd, r) == "running" and started(tag), 30)
    rc, outp = say(window, "stop", r, "--wait", "30")
    th.join(30)
    res = O.load_result(qd, r) or {}
    check(f"«стоп» в дорожке {lane}: идущий прогон снят — stopped, записи tests нет",
          up and rc == 0 and not th.is_alive() and res.get("state") == "stopped" and res.get("record") is False
          and not tests_for(sha), (rc, outp, res))
    release(tag)

# --- 5. замена заявки на предке в обеих дорожках (replace_older), затем каждая идёт своей дорожкой ---------------------
got = {}
for lane, window, d in (("full", "metis-k", KIT), ("quick", "athena-x", APP)):
    commit(d, {"t.py": GREEN + f"# {lane} r1\n"}, f"lanes {lane} r1")
    _rc, _o, n1 = cli_test(window, d)
    h2 = commit(d, {"t.py": GREEN + f"# {lane} r2\n"}, f"lanes {lane} r2")
    _rc, _o, n2 = cli_test(window, d)
    q = os.path.join(CACHE, window, "outside")
    ra = O.load_result(q, n1[0]) if len(n1) == 1 else {}
    check(f"замена в дорожке {lane}: заявка на предке снята «заменена», новая лежит в своей дорожке",
          len(n1) == 1 and len(n2) == 1 and (ra or {}).get("state") == "stopped"
          and (ra or {}).get("replaced_by") == n2[0] and not has_req(q, n1[0])
          and O.lane_of(req_of(q, n2[0]), window, n2[0]) == lane, (n1, n2, ra))
    got[lane] = (q, n2[0] if n2 else None, h2)
O.cmd_run("quick")
qf, rf_, hf = got["full"]
qq, rq_, hq = got["quick"]
check("замена: проход quick прогнал свою новую заявку, заявка full лежит",
      state(qq, rq_) == "done" and has_req(qf, rf_), (O.load_result(qq, rq_), O.load_result(qf, rf_)))
O.cmd_run()
check("замена: проход full прогнал свою, у обеих запись tests на новый head",
      state(qf, rf_) == "done" and bool(tests_for(hf)) and bool(tests_for(hq)), O.load_result(qf, rf_))

# --- 6. взятая заявка — не «потерянная» для прохода другой дорожки -----------------------------------------------------
r_l = put_req(qa, APP)
O.save_result(qa, r_l, {"state": "queued", "kind": "test", "sha": "a" * 40})
_old = time.time() - O.LOST_AFTER - 120
os.utime(os.path.join(qa, r_l + ".result.json"), (_old, _old))
taken = O.requests(("test",), limit=1, lane="quick")
O.recover_results(lane="full")
check("1081: заявку взял проход quick (итог queued давний) — recover_results прохода full её не сочтёт потерянной",
      [x[4] for x in taken] == [r_l] and state(qa, r_l) == "queued", (taken, O.load_result(qa, r_l)))
O.save_result(qa, r_l, {"state": "failed", "kind": "test", "why": "проба"})

# --- 7. «заход прерван», копии test --sha, сторож и тик — только своя дорожка -----------------------------------------
_lane = O._LANE
RZ = "20261113-777777-1a2b3c"
O._LANE.name = "quick"
O.save_result(qa, RZ, {"state": "running", "kind": "test"})
O._LANE.name = None
check("runs/: запись прохода quick несёт lane quick, итог в папке окна — без него",
      runs(RZ).get("lane") == "quick" and "lane" not in (O.load_result(qa, RZ) or {}), runs(RZ))
check("зомби quick: running дорожки quick при свободном замке — дело проходу quick, не full",
      O._zombies(lane="quick") == 1 and O._zombies() == 0 and O.pending_quick() is True)
with P.lock("outside-quick", block=False):
    check("зомби quick: заход quick жив (замок взят) — не зомби", O._zombies(lane="quick") == 0)
O.recover_results(lane="full")
check("recover_results(full) не трогает running дорожки quick", state(qa, RZ) == "running")
W = test_work(RZ)
os.makedirs(W)
O.drop_test_work("full")
check("drop_test_work(full): копия test --sha идущего прогона quick остаётся", os.path.isdir(W))
O.drop_test_work("quick")
check("drop_test_work(quick): копия своей дорожки снята", not os.path.exists(W))
O.recover_results(lane="quick")
check("recover_results(quick) чинит running своей дорожки — failed «заход прерван»",
      state(qa, RZ) == "failed" and "прерван" in (O.load_result(qa, RZ) or {}).get("why", ""))

# сторож: running дорожки quick дольше срока при живом заходе quick — гаснет держатель замка outside-quick
_alerts = []
_pa = P.alert
P.alert = lambda text, who="pantheon": _alerts.append(text)
HOLD = ("import fcntl,os,sys,time;"
        "fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_APPEND);fcntl.flock(fd,fcntl.LOCK_EX);"
        "print(os.getpid(),flush=True);time.sleep(300)")
os.makedirs(P.path("locks"), exist_ok=True)
h = subprocess.Popen([sys.executable, "-I", "-c", HOLD, P.path("locks", "outside-quick.lock")], stdout=subprocess.PIPE,
                     text=True)
TEST_PROCS.append(h)
int(h.stdout.readline())
RW = "20261113-888888-1a2b3c"
O._LANE.name = "quick"
O.save_result(qa, RW, {"state": "running", "kind": "test"})
O._LANE.name = None
_t = time.time() - O.WATCH_RUNNING - 60
os.utime(O.root("runs", RW + ".json"), (_t, _t))
_h0 = O._run_holder
asked = []
O._run_holder = lambda name="outside-run": asked.append(name) or h.pid
try:
    n = O.watchdog()
    h.wait(timeout=10)
finally:
    O._run_holder = _h0
    P.alert = _pa
check("сторож: running дорожки quick дольше срока — держатель замка outside-quick снят, итог failed",
      n == 1 and asked == ["outside-quick"] and h.poll() is not None and state(qa, RW) == "failed", (n, asked, _alerts))

# --- 8. ждущий спада полный набор уступает только своей дорожке: заход full передаёт Defer свою дорожку -----------------
LOADV = [50.0]
O.load_state = lambda: (LOADV[0], 10.0)
O.LOAD_POLL, O.SWEEP_EVERY = 0.2, 0.1
KD = commit(KIT, {"t.py": GREEN + "# lanes defer\n"}, "lanes defer")
r_d = put_req(qkit, KIT)
r_o = put_req(qother, OTHER)
th, out = bg(O.cmd_run)
wait_for(lambda: "жду спада" in ((O.load_result(qkit, r_d) or {}).get("why") or ""), 30)
time.sleep(1.0)
rd = O.load_result(qkit, r_d) or {}
check("1081: полный набор ждёт спада в проходе full и не уступает заявке quick (её ведёт свой проход) — заход жив, "
      "без «пропущены», заявка quick лежит", th.is_alive() and "жду спада" in rd.get("why", "")
      and "пропущены" not in rd.get("why", "") and has_req(qother, r_o), (rd, th.is_alive()))
LOADV[0] = 1.0
th.join(30)
rd = O.load_result(qkit, r_d) or {}
check("1081: после спада полный набор идёт: done, запись tests", not th.is_alive() and rd.get("state") == "done"
      and bool(tests_for(KD)), rd)
O.cmd_run("quick")
check("заявка quick после этого идёт своим проходом", state(qother, r_o) == "done", O.load_result(qother, r_o))
O.load_state = lambda: (0.0, 10.0)

if FAILS:
    for _r in [x for x in os.listdir(_ROOT) if x.startswith("lane-") and x.endswith("-started")]:
        release(_r[len("lane-"):-len("-started")])
print(f"{TOTAL[0] - len(FAILS) - len(SKIPPED_BIND)} из {TOTAL[0]} прошли"
      + (f", пропущено при закрытом bind: {len(SKIPPED_BIND)}" if SKIPPED_BIND else ""))
sys.exit(1 if FAILS else 0)
