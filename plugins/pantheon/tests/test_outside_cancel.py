#!/usr/bin/env python3
"""Проверки вне окна роли, часть «окно снимает свой прогон» (metis-0873; разрез test_outside.py — metis-0750).

Запуск: python3 -I plugins/pantheon/tests/test_outside_cancel.py  (код выхода 0 — все прошли)
Окно снимает свой идущий прогон и прогон в очереди командой stop, чужой qdir и чужие метки не в счёт, проход снимает
прогон ушедшего head, снятый полный набор не попадает в full.jsonl. Общая часть — _outside_common.py, kit — _outside_kit.py.
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

os.makedirs(qkit, exist_ok=True)   # папку заявок окна metis-k в основном файле создаёт kit_request раздела «запись по дереву»

# --- metis-0873: окно снимает свой прогон (идущий и в очереди), проход снимает прогон ушедшего head -------------------
import fcntl as _fcntl
import threading as _thr

S_PIDS, S_MODE, S_GO = (os.path.join(_ROOT, n) for n in ("stop0873-pids", "stop0873-mode", "stop0873-go"))
S_TPY = (f"import os, signal, sys, time\nR = {_ROOT!r}  # 0873\n"
         "mode = open(os.path.join(R, 'stop0873-mode')).read().strip()\n"
         "with open(os.path.join(R, 'stop0873-pids'), 'a') as fh:\n    fh.write(f'{os.getpid()}\\n')\n"
         "if mode.startswith('mark:'):\n    open(mode[5:], 'w').close()\n    sys.exit(0)\n"
         "if mode == 'red':\n    sys.exit(1)\n"
         "if mode == 'trap':\n    signal.signal(signal.SIGTERM, lambda *a: os._exit(0))\n"
         "end = time.time() + 120\n"
         "while time.time() < end and not os.path.exists(os.path.join(R, 'stop0873-go')):\n    time.sleep(0.2)\n"
         "sys.exit(0)\n")
O.SUPERSEDE_EVERY, O.PROCS_EVERY = 1, 1
# Нагрузка Mac тесту не нужна: порог outside (3.0 × ядра) на загруженном Mac держит заявку queued, и s_start не видит
# running (T11, metis-1035). Подмена только у теста; run_pass идёт потоком в этом процессе, O — тот же модуль.
O.load_state = lambda: (0.0, 24.0)


def s_pids():
    try:
        with open(S_PIDS) as fh:
            return [int(x) for x in fh.read().split()]
    except (OSError, ValueError):
        return []


def s_mode(m):
    with open(S_MODE, "w") as fh:
        fh.write(m)
    with contextlib.suppress(FileNotFoundError):
        os.remove(S_PIDS)
    with contextlib.suppress(FileNotFoundError):
        os.remove(S_GO)


def s_dead(pids, sec=10):
    return wait_for(lambda: all(not pid_alive(p, 0) for p in pids), sec)


def s_start(q, rid, sec=120):   # ждём события «running»; под нагрузкой 30 с не хватало (T11)
    th = _thr.Thread(target=run_pass, daemon=True)
    th.start()
    return th, wait_for(lambda: state(q, rid) == "running" and s_pids(), sec)


def s_stopped(q, rid, sec=10):
    return wait_for(lambda: state(q, rid) == "stopped", sec)


git(APP, "switch", "-q", "main")
D0 = git(APP, "rev-parse", "HEAD")
SD = commit(APP, {"t.py": S_TPY}, "0873 диспетчер")
n_full0 = len(open(O.full_file()).read().splitlines()) if os.path.exists(O.full_file()) else 0

# R1: T1 срез процессов, T3b чужая метка, T9 метка-ссылка, T6b грязное дерево, затем T3a свой «стоп»
s_mode("sleep")
q, rid = new_request("athena-x", APP, "test")
th, up = s_start(q, rid)
pids = s_pids()
# Срез procs пишет TestWatch.__call__ на тике wait_proc: тик раз в SWEEP_EVERY с, запись не раньше PROCS_EVERY с после
# старта сторожа (lib/outside.py). procs_of берёт данные у ps (setuid /bin/ps), а сбой ps даёт procs == [] — ключ есть,
# но пустой. В песочнице ps не запускается (Operation not permitted, metis-0786), и итог несёт [], а не срез: на
# «пусто» тест ждал зря (metis-0873, прогон 20261106-050513-080e2d: ([257], [257], {})). Ждём по коду ключ procs
# (PROCS_EVERY + SWEEP_EVERY + 10 с ps + запас; wait_for выходит сразу), pid в срезе требуем, когда ps доступен.
try:
    PS_OK = subprocess.run(["ps", "-o", "pid=", "-p", str(os.getpid())], capture_output=True, text=True,
                           timeout=10).stdout.split() == [str(os.getpid())]
except (OSError, subprocess.SubprocessError):
    PS_OK = False
res = wait_for(lambda: "procs" in (O.load_result(q, rid) or {}) and O.load_result(q, rid),
               O.PROCS_EVERY + O.SWEEP_EVERY + 10 + 20) or {}
if not PS_OK:
    print("пропущено: ps недоступен (песочница) — pid прогона в срезе procs T1 не проверяется")
check("T1 status_shows_procs_own_only: итог running своего qdir несёт срез процессов с pid прогона, в соседнем qdir — "
      "ничего", up and "procs" in res and (not PS_OK or any(p.get("pid") in pids for p in res["procs"]))
      and not os.path.exists(os.path.join(CACHE, "metis-y", "outside", rid + ".result.json")), (up, pids, res))
_fy = os.path.join(CACHE, "metis-y", "outside", rid + ".stop")
os.makedirs(os.path.dirname(_fy), exist_ok=True)
open(_fy, "w").close()
_lnk = os.path.join(q, rid + ".stop")
open(os.path.join(_ROOT, "stop0873-target"), "w").close()
os.symlink(os.path.join(_ROOT, "stop0873-target"), _lnk)
with open(os.path.join(APP, "t.py"), "a") as fh:
    fh.write("# грязная правка\n")
time.sleep(4)
check("T3b stop_foreign_qdir_ignored: метка в соседнем qdir — прогон идёт, метка убрана, в журнале stop-foreign",
      state(q, rid) == "running" and all(pid_alive(p, 0) for p in pids) and not os.path.exists(_fy)
      and [e.get("by") for e in events(rid, "stop-foreign")] == [["metis-y"]], (state(q, rid), events(rid)))
check("T9 stop_symlink_marker_ignored: ссылка на месте метки — прогон идёт", state(q, rid) == "running", state(q, rid))
check("T6b dirty_tree_not_superseded: грязная правка без коммита — прогон идёт", state(q, rid) == "running")
os.remove(_lnk)
git(APP, "checkout", "--", "t.py")
n_rec = len(tests_for(SD))
t0 = time.monotonic()
rc, out = say("athena-x", "stop", rid, "--wait", "15")
dt = time.monotonic() - t0
res = O.load_result(q, rid) or {}
th.join(30)
check("T3a stop_running_own: stop своего идущего теста — код 0, stopped за ≤10 с, группа мертва, метки нет",
      rc == 0 and res.get("state") == "stopped" and dt <= 10 and s_dead(pids)
      and "заявка «стоп»" in res.get("why", "") and not os.path.exists(os.path.join(q, rid + ".stop")),
      (rc, out, round(dt, 1), res))
check("T3a: снятый — без записи tests и без строки full.jsonl; в журнале stop с окном",
      res.get("record") is False and len(tests_for(SD)) == n_rec
      and (len(open(O.full_file()).read().splitlines()) if os.path.exists(O.full_file()) else 0) == n_full0
      and [e.get("by") for e in events(rid, "stop")] == [["athena-x"]], (res, events(rid, "stop")))

# T3c: команда ловит TERM и выходит с 0 — записи нет
s_mode("trap")
q, rid = new_request("athena-x", APP, "test")
th, up = s_start(q, rid)
pids = s_pids()
rc, out = say("athena-x", "stop", rid, "--wait", "15")
th.join(30)
res = O.load_result(q, rid) or {}
check("T3c stop_trap_term_exit0_no_record: код 0 после TERM — stopped, record false, записи tests нет",
      up and rc == 0 and res.get("state") == "stopped" and res.get("code") == 0 and res.get("record") is False
      and len(tests_for(SD)) == n_rec and s_dead(pids), (up, rc, out, res))

# T10c: метка ставится самой командой перед выходом с 0 — записи нет
q, rid = new_request("athena-x", APP, "test")
s_mode("mark:" + os.path.join(q, rid + ".stop"))
run_pass()
res = O.load_result(q, rid) or {}
check("T10c stop_before_append: «стоп» пришёл перед выходом с 0 — stopped, записи tests нет, метка убрана",
      res.get("state") == "stopped" and res.get("code") == 0 and len(tests_for(SD)) == n_rec and s_pids()
      and not os.path.exists(os.path.join(q, rid + ".stop")), res)

# T10a: «стоп» между взятием заявки и запуском — команда не запускается
s_mode("sleep")
q, rid = new_request("athena-x", APP, "test")
_cmd0 = O.command


def _cmd_mark(d, kind, script=None):
    open(os.path.join(q, rid + ".stop"), "w").close()
    return _cmd0(d, kind, script)


O.command = _cmd_mark
try:
    run_pass()
finally:
    O.command = _cmd0
res = O.load_result(q, rid) or {}
check("T10a stop_between_take_and_popen: метка до Popen — stopped, команда не запускалась, метка убрана",
      res.get("state") == "stopped" and not s_pids() and not os.path.exists(os.path.join(q, rid + ".stop")), res)

# T10b: прогон уже done с записью — stop так и говорит, код 0
rid_b = "20261106-000001-0873bb"
O.save_result(q, rid_b, {"state": "done", "kind": "test", "sha": SD, "code": 0, "record": True})
rc, out = say("athena-x", "stop", rid_b, "--wait", "0")
check("T10b stop_after_record_keeps_record: «уже done», запись есть, код 0, метки нет",
      rc == 0 and "уже done" in out and "запись tests" in out and not os.path.exists(os.path.join(q, rid_b + ".stop")),
      (rc, out))

# T2: заявка в очереди, STATE окну закрыт (runs/ только для чтения) — снятие без записи в STATE
q, rid = new_request("athena-x", APP, "test")
_runs = O.root("runs")
os.chmod(_runs, 0o500)
try:
    rc, out = say("athena-x", "stop", rid, "--wait", "0")
except PermissionError as e:
    rc, out = None, f"PermissionError: {e}"
finally:
    os.chmod(_runs, 0o700)
O.recover_results(t=time.time() + 3600)
check("T2 stop_queued_from_window_no_state_write: код 0, stopped в своей папке, заявки нет, STATE не писался, "
      "recover_results не делает «потеряна»", rc == 0 and state(q, rid) == "stopped"
      and not os.path.exists(os.path.join(q, rid + ".req.json")) and not os.path.exists(os.path.join(_runs, rid + ".json")),
      (rc, out, O.load_result(q, rid)))

# T4: метка идущего теста старше STOP_ORPHAN_AGE — drop_orphan_stops её не убирает
rid_4 = "20261106-000002-0873cc"
O.save_result(q, rid_4, {"state": "running", "kind": "test", "sha": SD})
_m4 = os.path.join(q, rid_4 + ".stop")
open(_m4, "w").close()
os.utime(_m4, (time.time() - 3600, time.time() - 3600))
O.drop_orphan_stops()
check("T4 orphan_stops_keeps_running_test: метка running-теста лежит после drop_orphan_stops", os.path.exists(_m4))
O.save_result(q, rid_4, {"state": "stopped", "kind": "test", "sha": SD})
O.drop_orphan_stops()
check("T4: тест закончен — метка-сирота убрана", not os.path.exists(_m4))

# T3b из CLI: заявка другого окна, итог которой виден в STATE (идёт) — «не из этого окна», код 1, метки нет;
# снятая из окна (итог только в его папке, T2) другому окну не видна вовсе — «нет такой заявки», код 1
rid_3 = "20261106-000003-0873cc"
O.save_result(q, rid_3, {"state": "running", "kind": "test", "sha": SD})
rc, out = say("metis-y", "stop", rid_3, "--wait", "0")
check("T3b CLI: stop идущей заявки другого окна — «не из этого окна», код 1, метки нет",
      rc == 1 and "не из этого окна" in out
      and not os.path.exists(os.path.join(CACHE, "metis-y", "outside", rid_3 + ".stop")), (rc, out))
O.save_result(q, rid_3, {"state": "stopped", "kind": "test", "sha": SD})
rc, out = say("metis-y", "stop", rid, "--wait", "0")
check("T3b CLI: stop снятой в другом окне — «нет такой заявки», код 1, метки нет",
      rc == 1 and "нет такой заявки" in out
      and not os.path.exists(os.path.join(CACHE, "metis-y", "outside", rid + ".stop")), (rc, out))

# T6a: коммит в папке во время прогона — проход снимает сам (superseded), записи нет
s_mode("sleep")
q, rid = new_request("athena-x", APP, "test")
th, up = s_start(q, rid)
pids = s_pids()
SE = commit(APP, {"t.py": S_TPY + "# e\n"}, "0873 новый head")
ok = s_stopped(q, rid, 15)
th.join(30)
res = O.load_result(q, rid) or {}
check("T6a superseded_head_moved_running: HEAD ушёл — stopped «superseded», группа мертва, записи нет",
      up and ok and "superseded: HEAD ушёл" in res.get("why", "") and res.get("record") is False and s_dead(pids)
      and len(tests_for(SD)) == n_rec, (up, res))

# T8a: заявка в очереди на ушедший head при более новой заявке той же папки — failed superseded, без прогона
s_mode("red")
qa, ra = new_request("athena-x", APP, "test")
SF = commit(APP, {"t.py": S_TPY + "# f\n"}, "0873 f")
# ID заявки — секунда и случайный хвост: в одну секунду новая могла встать раньше старой и снять её «дублем»
# (pr353-red-1) — новая заявка в следующей секунде
wait_for(lambda: time.strftime("%Y%m%d-%H%M%S") > ra[:15], 3)
# новая заявка — файлом, мимо cmd_request: подача сама сняла бы старую на предке (metis-0852), а здесь проверка
# прохода — заявки, поданные до выпуска 0852 или с другого пути
qb, rb = qa, one_request(qd=qa, rid=time.strftime("%Y%m%d-%H%M%S") + "-b8b8b8")
run_pass()
resa, resb = O.load_result(qa, ra) or {}, O.load_result(qb, rb) or {}
check("T8a queued_superseded_by_newer: старая — failed «superseded <новый>», новая прогнана, прогон один",
      resa.get("state") == "failed" and resa.get("superseded") == rb and f"superseded {rb}" in resa.get("why", "")
      and resb.get("state") == "done" and len(s_pids()) == 1, (resa, resb, s_pids()))
# T8b: новой заявки нет — старая идёт на текущем HEAD
s_mode("red")
qc, rc_ = new_request("athena-x", APP, "test")
SG = commit(APP, {"t.py": S_TPY + "# g\n"}, "0873 g")
run_pass()
resc = O.load_result(qc, rc_) or {}
check("T8b queued_no_newer_runs: новой заявки нет — прогон текущего HEAD", resc.get("state") == "done"
      and resc.get("sha") == SG and len(s_pids()) == 1, resc)

# T7a/T7b: test --sha — снимает только более новая заявка --sha из того же qdir на потомка
s_mode("sleep")
PX = commit(APP, {"t.py": S_TPY + "# x\n"}, "0873 x")
PY = commit(APP, {"t.py": S_TPY + "# y\n"}, "0873 y")
qx, rx = new_request("athena-x", APP, "test", "--sha", PX)
th, up = s_start(qx, rx, 60)
pids = s_pids()
_cwd = os.getcwd()
os.chdir(APP)
try:
    rcs, _o = say(None, "test", "--sha", PY)   # из очереди терминала (другой qdir) — не снимает
finally:
    os.chdir(_cwd)
time.sleep(3)
check("T7b pin_not_superseded_by_other_qdir: новая заявка --sha из другого qdir — старая идёт",
      up and rcs == 0 and state(qx, rx) == "running" and all(pid_alive(p, 0) for p in pids), (up, rcs, state(qx, rx)))
# заявка терминала на PY убрана: иначе новая заявка окна на тот же коммит сцепляется с ней (pr353-red-1)
for _n in os.listdir(O.root("queue")):
    if _n.endswith(".req.json"):
        os.remove(os.path.join(O.root("queue"), _n))
qy, ry = new_request("athena-x", APP, "test", "--sha", PY)
ok = s_stopped(qx, rx, 15)
res = O.load_result(qx, rx) or {}
open(S_GO, "w").close()
th.join(90)
check("T7a pin_superseded_by_newer_same_qdir: новая --sha того же qdir на потомка — старая stopped «superseded», "
      "копия снята, записи нет", ok and "superseded: заявка " + ry in res.get("why", "") and s_dead(pids)
      and not os.path.exists(test_work(rx)) and not tests_for(PX), res)
for _n in os.listdir(O.root("queue")):
    if _n.endswith(".req.json"):
        os.remove(os.path.join(O.root("queue"), _n))
git(APP, "reset", "-q", "--hard", D0)

# T5a/T5b: настоящий heavy — после стопа места свободны; стоп, пока heavy ждёт место, — команда не стартовала
_locks = os.path.join(STATE, "locks")
os.makedirs(_locks, exist_ok=True)
_slots = [os.path.join(_locks, f"heavy-cmd-{i}.lock") for i in (1, 2)]
for _s in _slots:
    open(_s, "a").close()
O.HEAVY = "default"
SH = commit(APP, {"t.py": S_TPY + "# h\n"}, "0873 heavy")
try:
    s_mode("sleep")
    q, rid = new_request("athena-x", APP, "test")
    th, up = s_start(q, rid, 60)
    pids = s_pids()
    rc, out = say("athena-x", "stop", rid, "--wait", "15")
    th.join(30)
    free = []
    for _s in _slots:
        with open(_s, "a") as fh:
            try:
                _fcntl.flock(fh, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                free.append(True)
            except OSError:
                free.append(False)
    check("T5a stop_releases_heavy_slot: стоп под heavy — stopped, оба места свободны",
          up and rc == 0 and state(q, rid) == "stopped" and s_dead(pids) and free == [True, True], (up, rc, out, free))
    _held = [open(_s, "a") for _s in _slots]
    for fh in _held:
        _fcntl.flock(fh, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
    s_mode("sleep")
    q, rid = new_request("athena-x", APP, "test")
    th = _thr.Thread(target=run_pass, daemon=True)
    th.start()
    up = wait_for(lambda: state(q, rid) == "running", 30)
    time.sleep(2)
    rc, out = say("athena-x", "stop", rid, "--wait", "15")
    th.join(30)
    for fh in _held:
        fh.close()
    check("T5b stop_while_heavy_waits: стоп, пока heavy ждёт место, — stopped, команда не стартовала",
          up and rc == 0 and state(q, rid) == "stopped" and not s_pids(), (up, rc, out, s_pids()))
finally:
    O.HEAVY = None
    git(APP, "reset", "-q", "--hard", D0)

# T11: снятый полный набор не попадает в full.jsonl
s_mode("sleep")
KS = commit(KIT, {"t.py": S_TPY + "# kit\n"}, "0873 kit")
one_request.n += 1
rk = f"20261106-1{one_request.n:05d}-c0c0c0"
with open(os.path.join(qkit, rk + ".req.json"), "w") as fh:
    json.dump({"v": 1, "id": rk, "kind": "test", "dir": KIT, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, fh)
n_full = len(open(O.full_file()).read().splitlines()) if os.path.exists(O.full_file()) else 0
th, up = s_start(qkit, rk)
rc, out = say("metis-k", "stop", rk, "--wait", "15")
th.join(30)
check("T11 stopped_not_in_full_jsonl: снятый полный набор — stopped, строки full.jsonl нет, записи tests нет",
      up and rc == 0 and state(qkit, rk) == "stopped" and not tests_for(KS)
      and (len(open(O.full_file()).read().splitlines()) if os.path.exists(O.full_file()) else 0) == n_full,
      (up, rc, out))
open(S_GO, "w").close()
for _p in s_pids():
    with contextlib.suppress(OSError):
        os.kill(_p, signal.SIGKILL)
O.SUPERSEDE_EVERY, O.PROCS_EVERY = 30, 30


kill_all_servers()
_left = [p for p in fake_pids() if still_alive(p)]
if _left or not fake_pids():   # то же условие, что проверка «сирот» в test_outside.py; здесь — только провал
    check("тесты не оставляют процессов: заглушка sandbox-exec и задачи «turbo» погашены (cancel)", False, (_left, len(fake_pids())))

print(f"{TOTAL[0] - len(FAILS) - len(SKIPPED_BIND)} из {TOTAL[0]} прошли"
      + (f", пропущено при закрытом bind: {len(SKIPPED_BIND)}" if SKIPPED_BIND else ""))
sys.exit(1 if FAILS else 0)
