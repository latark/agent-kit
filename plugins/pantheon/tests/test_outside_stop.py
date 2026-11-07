#!/usr/bin/env python3
"""`pantheon outside` из окон роли без права писать в STATE (lib/outside.py; metis-0867, 0939, 0849, 0848, 0862, 0646).

Запуск: python3 -I plugins/pantheon/tests/test_outside_stop.py  (код выхода 0 — все прошли)
Проверяет: own_qdir берёт кэш окна через browser.window_cache (PANTHEON_TMP или только XDG_CACHE_HOME — hq, hestia,
job-*), а проход видит такую папку и называет окно по ней; под seatbelt-профилем окна (запись только в кэш окна,
STATE закрыт; образец — test_read:test_window_queue_seatbelt): заявка окна hq и окна направления — в кэше окна, STATE
не тронут; окно не опознано — код 1, причина последней строкой, без Traceback; `stop` заявки в очереди окна без права
писать в runs/ ставит отмену в свою папку, ждущий `test --wait` получает итог stopped, а не висит; итог отмены в STATE
не записать — заявка возвращается в очередь, код 1; установка зависимостей не считает ожидание места heavy в свой срок
(metis-0862); в итоге running есть started (metis-0646).
"""
import atexit
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311  # noqa: E402  pantheon.py — только на Python 3.11+

if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)] + sys.argv[1:])

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="outside-stop-"))
tempfile.tempdir = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIBDIR = os.path.join(os.path.dirname(HERE), "lib")
RUN_PY = os.path.join(LIBDIR, "run.py")
HOME = os.path.join(_ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
CACHES = os.path.join(HOME, "Library", "Caches", "pantheon-sandbox")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE", "XDG_"))]:
    os.environ.pop(k)
os.environ.update({"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1", "TMPDIR": _ROOT})
sys.path.insert(0, LIBDIR)
import pantheon as P  # noqa: E402
O = P.outside_mod()

FAILS, TOTAL = [], [0]


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{str(extra)[-800:]}]"))
    if not cond:
        FAILS.append(name)


def git(d, *args):
    r = subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        *args], capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


RP = os.path.join(HOME, "projects", "rp")
os.makedirs(RP)
git(RP, "init", "-q", "-b", "main")
git(RP, "remote", "add", "origin", "git@github.com:latark/rp.git")
with open(os.path.join(RP, "f.txt"), "w") as fh:
    fh.write("a\n")
git(RP, "add", "-A")
git(RP, "commit", "-q", "-m", "a")
with open(os.path.join(RP, ".pantheon-verify"), "w") as fh:
    fh.write("sh -c true\n")
git(RP, "add", "-A")
git(RP, "commit", "-q", "-m", "verify")
FAKE_SB = os.path.join(_ROOT, "fake-sb")
with open(FAKE_SB, "w") as fh:
    fh.write("#!/bin/sh\nshift 2\nexec \"$@\"\n")
os.chmod(FAKE_SB, 0o755)
O.SANDBOX_EXEC, O.HEAVY = FAKE_SB, None   # без настоящего sandbox-exec (в окне он вложенный) и без очереди heavy
P.write_json(os.path.join(STATE, "domains.json"), {"domains": {"win-a": ["~/projects/rp"]}})


def window(name, xdg_only=False):
    """Кэш окна name и окружение, как его ставит сборка: PANTHEON_TMP, у hq/hestia/job-* — только XDG_CACHE_HOME."""
    cache = os.path.join(CACHES, name)
    os.makedirs(os.path.join(cache, "tmp"), exist_ok=True)
    os.makedirs(os.path.join(cache, "xdg"), exist_ok=True)
    if xdg_only:
        return cache, {"XDG_CACHE_HOME": os.path.join(cache, "xdg")}
    return cache, {"PANTHEON_TMP": os.path.join(cache, "tmp")}


@contextlib.contextmanager
def env(extra):
    old = {k: os.environ.get(k) for k in ("PANTHEON_TMP", "XDG_CACHE_HOME")}
    for k in old:
        os.environ.pop(k, None)
    os.environ.update(extra)
    try:
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


# --- 1. own_qdir: кэш окна через browser.window_cache (metis-0848) ---------------------------------------------------
cache_a, env_a = window("win-a")
cache_hq, env_hq = window("hq", xdg_only=True)
with env(env_a):
    check("own_qdir: окно с PANTHEON_TMP — outside/ его кэша", O.own_qdir() == os.path.join(cache_a, "outside"),
          O.own_qdir())
with env(env_hq):
    check("own_qdir: окно hq только с XDG_CACHE_HOME — outside/ его кэша, а не STATE", O.own_qdir() == os.path.join(
        cache_hq, "outside"), O.own_qdir())
with env({"XDG_CACHE_HOME": os.path.join(HOME, ".cache")}):
    check("own_qdir: XDG_CACHE_HOME вне кэшей окон — не окно, очередь STATE", O.own_qdir() == O.root("queue"),
          O.own_qdir())
with env({}):
    check("own_qdir: вне окна — очередь STATE", O.own_qdir() == O.root("queue"), O.own_qdir())


def say(extra, *args, cwd=RP):
    """Команда из окна (env.update) в этом же процессе → (код, stdout, stderr)."""
    out, errb = io.StringIO(), io.StringIO()
    old = os.getcwd()
    os.chdir(cwd)
    try:
        with env(extra), contextlib.redirect_stdout(out), contextlib.redirect_stderr(errb):
            rc = O.main(list(args))
    finally:
        os.chdir(old)
    return rc, out.getvalue(), errb.getvalue()


rc, out, _e = say(env_hq, "test")
rid_hq = (out.split("заявка ", 1) + [""])[1].split(":", 1)[0]
req_hq = os.path.join(cache_hq, "outside", rid_hq + ".req.json")
check("hq: заявка test — в outside/ кэша окна, в STATE/outside/queue её нет", rc == 0 and rid_hq and os.path.isfile(
    req_hq) and not os.path.exists(os.path.join(STATE, "outside", "queue", rid_hq + ".req.json")), (rc, out))
seen = [(w, r) for _t, _k, _q, w, r, _req in O.requests(("test",))]
check("hq: проход видит заявку и называет окно по папке кэша", ("hq", rid_hq) in seen, seen)
for _n in os.listdir(os.path.join(cache_hq, "outside")):   # requests() заявку взяла (сняла с диска)
    os.remove(os.path.join(cache_hq, "outside", _n))

# --- 2. итог running несёт started (metis-0646) ----------------------------------------------------------------------
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    O.show({"id": "x", "state": "running", "started": "2026-11-07T10:00:00"})
check("show: у running — «начат <время>»", "начат 2026-11-07T10:00:00" in buf.getvalue(), buf.getvalue())
RUNNING = []
_save = O.save_result


def _spy(qdir, rid, r):
    RUNNING.append(dict(r))
    return _save(qdir, rid, r)


O.save_result = _spy
try:
    O.run_test("20261107-100001-bbbbbb", RP, None, "win-a", os.path.join(cache_a, "outside"), O.registry(None),
               record=False)
finally:
    O.save_result = _save
runs = [r for r in RUNNING if r.get("state") == "running"]
check("run_test: save_result(running) несёт started", runs and all(r.get("started") for r in runs), RUNNING)

# --- 3. seatbelt: окна без права писать в STATE ---------------------------------------------------------------------


def _seatbelt():
    sb = "/usr/bin/sandbox-exec"
    if sys.platform != "darwin" or not os.path.exists(sb):
        return None
    r = subprocess.run([sb, "-p", "(version 1)(allow default)", "/usr/bin/true"], capture_output=True, text=True,
                       timeout=30)
    return sb if r.returncode == 0 else None


SB = _seatbelt()
SBTMP = os.path.join(_ROOT, "sbtmp")
os.makedirs(SBTMP)


def sb_cmd(extra, *args):
    """Команда в профиле окна: запись — только в кэши окон и свою tmp; STATE (и runs/) закрыты. → Popen-аргументы."""
    allow = [os.path.realpath(CACHES), os.path.realpath(SBTMP), "/dev"]
    profile = ("(version 1)(allow default)(deny file-write* (require-not (require-any "
               + " ".join(f"(subpath {json.dumps(p)})" for p in allow) + ")))")
    e = {"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.environ["PANTHEON_HOME"],
         "PANTHEON_NO_NOTIFY": "1", "PATH": os.environ["PATH"], "TMPDIR": SBTMP, **extra}
    return [SB, "-p", profile, PY311, "-I", RUN_PY, "outside", *args], e


def sb_run(extra, *args, timeout=60):
    argv, e = sb_cmd(extra, *args)
    return subprocess.run(argv, env=e, cwd=RP, capture_output=True, text=True, timeout=timeout)


def rid_of(text):
    return (text.split("заявка ", 1) + [""])[1].split(":", 1)[0].strip()


shutil.rmtree(O.root(), ignore_errors=True)   # следы прогонов этого же процесса: дальше только то, что пишут окна
if SB is None:
    print("пропущено: нужен macOS — sandbox-exec недоступен или проба идёт внутри песочницы")
else:
    # 3a. hq (только XDG) и окно направления ставят заявку в кэш окна, STATE не тронут
    r_hq = sb_run(env_hq, "test")
    git(RP, "commit", "-q", "--allow-empty", "-m", "a2")   # другой head: заявка hq не склеивается с этой
    r_a = sb_run(env_a, "test")
    h, a = rid_of(r_hq.stdout), rid_of(r_a.stdout)
    check("seatbelt, окно hq без PANTHEON_TMP: заявка в outside/ его кэша", r_hq.returncode == 0 and h and os.path.isfile(
        os.path.join(cache_hq, "outside", h + ".req.json")), (r_hq.returncode, r_hq.stdout, r_hq.stderr[-500:]))
    check("seatbelt, окно направления: заявка в outside/ его кэша", r_a.returncode == 0 and a and os.path.isfile(
        os.path.join(cache_a, "outside", a + ".req.json")), (r_a.returncode, r_a.stdout, r_a.stderr[-500:]))
    check("seatbelt: в STATE/outside окна ничего не записали", not os.path.exists(os.path.join(STATE, "outside")))
    seen = {(w, r) for _t, _k, _q, w, r, _req in O.requests(("test",))}
    check("seatbelt: проход забирает обе заявки, окно — по папке кэша", {("hq", h), ("win-a", a)} <= seen, seen)

    # 3b. окно не опознано: код 1, причина последней строкой, без трассировки
    r_u = sb_run({}, "test")
    last = (r_u.stderr.strip().splitlines() or [""])[-1]
    check("seatbelt, окно не опознано: test — код 1, причина последней строкой без Traceback",
          r_u.returncode == 1 and "заявку не записать" in last and "перезапустить" in last
          and "Traceback" not in r_u.stderr and "PermissionError" in last, (r_u.returncode, r_u.stderr[-500:]))

    # 3c. stop заявки в очереди окна без права писать в runs/: отмена в свою папку, ждущий --wait получает итог
    for n in os.listdir(os.path.join(cache_a, "outside")):
        os.remove(os.path.join(cache_a, "outside", n))
    git(RP, "commit", "-q", "--allow-empty", "-m", "b")   # новый head: прежних заявок на нём нет
    argv, e = sb_cmd(env_a, "test", "--wait", "40")
    waiter = subprocess.Popen(argv, env=e, cwd=RP, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    qa = os.path.join(cache_a, "outside")
    end = time.monotonic() + 20
    rid_w = None
    while time.monotonic() < end and not rid_w:
        rid_w = next((n[:-len(".req.json")] for n in os.listdir(qa) if n.endswith(".req.json")), None)
        time.sleep(0.2)
    r_s = sb_run(env_a, "stop", rid_w or "20261107-000000-000000", "--wait", "0")
    t0 = time.monotonic()
    try:
        w_out, w_err = waiter.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        waiter.kill()
        w_out, w_err = waiter.communicate()
    check("seatbelt: stop заявки в очереди окна — код 0, без Traceback, заявки в очереди нет", rid_w and r_s.returncode == 0
          and "снят" in r_s.stdout and "Traceback" not in r_s.stderr and not os.path.exists(
              os.path.join(qa, rid_w + ".req.json")), (r_s.returncode, r_s.stdout, r_s.stderr[-500:]))
    check("seatbelt: итог отмены — stopped в папке окна, в STATE/outside/runs ничего нет", rid_w and (
        O.load_result(qa, rid_w) or {}).get("state") == "stopped" and not os.path.exists(
            os.path.join(STATE, "outside", "runs")), O.load_result(qa, rid_w or "x"))
    check("seatbelt: ждущий `test --wait` получил итог stopped, а не завис (до срока)",
          waiter.returncode == 1 and "stopped" in w_out and "отменена до запуска" in w_out
          and time.monotonic() - t0 < 25, (waiter.returncode, w_out, w_err[-300:]))

    # 3d. заявка в очереди STATE, окно не опознано: stop — код 1, строка причины, заявка осталась
    q_state = O.root("queue")
    os.makedirs(q_state)
    rid_st = "20261107-110000-cccccc"
    req_st = {"v": 1, "id": rid_st, "kind": "test", "dir": RP, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "sha": git(RP, "rev-parse", "HEAD")}
    with open(os.path.join(q_state, rid_st + ".req.json"), "w") as fh:
        json.dump(req_st, fh)
    r_x = sb_run({}, "stop", rid_st, "--wait", "0")
    last = (r_x.stderr.strip().splitlines() or [""])[-1]
    check("seatbelt, окно не опознано: stop заявки очереди STATE — код 1, причина без Traceback, заявка на месте",
          r_x.returncode == 1 and "Traceback" not in r_x.stderr and "перезапустить" in last and os.path.isfile(
              os.path.join(q_state, rid_st + ".req.json")), (r_x.returncode, r_x.stdout, r_x.stderr[-500:]))

# --- 4. итог отмены в STATE не записать: заявка возвращается, код 1 (metis-0867) -------------------------------------
q_state = O.root("queue")
os.makedirs(q_state, exist_ok=True)
rid_b = "20261107-120000-dddddd"
req_b = {"v": 1, "id": rid_b, "kind": "test", "dir": RP, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
with open(os.path.join(q_state, rid_b + ".req.json"), "w") as fh:
    json.dump(req_b, fh)


def _deny(qdir, rid, r):
    raise PermissionError(13, "Operation not permitted", "runs")


O.save_result = _deny
try:
    rc, out, errtext = say({}, "stop", rid_b, "--wait", "0")
finally:
    O.save_result = _save
back = O._parse(open(os.path.join(q_state, rid_b + ".req.json")).read()) if os.path.isfile(
    os.path.join(q_state, rid_b + ".req.json")) else None
check("итог отмены не записать: код 1, строка причины, заявка возвращена в очередь, а не потеряна",
      rc == 1 and "итог отмены не записать" in errtext and "Traceback" not in errtext and back == req_b, (rc, errtext, back))
rc, out, errtext = say({}, "stop", rid_b, "--wait", "0")
check("итог пишется — та же заявка снимается: код 0, stopped в STATE/outside/runs", rc == 0 and (P.read_json(
    O.root("runs", rid_b + ".json"), {}) or {}).get("state") == "stopped", (rc, out, errtext))

# --- 5. установка зависимостей не считает ожидание места heavy в свой срок (metis-0862) ---------------------------------
FAKE_HEAVY = os.path.join(_ROOT, "fake-heavy")
with open(FAKE_HEAVY, "w") as fh:   # «места заняты»: 3 с ни одного потомка, потом команда — потомком
    fh.write(f"#!{sys.executable}\nimport subprocess, sys, time\ntime.sleep(3)\n"
             "sys.exit(subprocess.run(sys.argv[1:]).returncode)\n")
os.chmod(FAKE_HEAVY, 0o755)
FAKE_PM = os.path.join(HOME, ".local", "bin")   # sandbox_env ставит его в PATH раньше системных
os.makedirs(FAKE_PM)
with open(os.path.join(FAKE_PM, "fakepm"), "w") as fh:
    fh.write("#!/bin/sh\necho installed\nexit 0\n")
os.chmod(os.path.join(FAKE_PM, "fakepm"), 0o755)
PD = os.path.join(_ROOT, "prep")
os.makedirs(PD)
with open(os.path.join(PD, "package.json"), "w") as fh:
    json.dump({"name": "p"}, fh)
old = (O.SANDBOX_EXEC, O.HEAVY, O.package_manager)
O.HEAVY, O.package_manager = FAKE_HEAVY, lambda d, pkg: "fakepm"   # настоящий npm не нужен
try:
    t0 = time.monotonic()
    sweep, O.SWEEP_EVERY = O.SWEEP_EVERY, 0.3   # шаг сторожа меньше срока: иначе срок кончается до первой проверки hold
    code = O.prepare(PD, "20261107-130000-eeeeee", timeout=2)
    dt = time.monotonic() - t0
    O.SWEEP_EVERY = sweep
    log_text = open(O.root("runs", "20261107-130000-eeeeee.log")).read() if os.path.exists(
        O.root("runs", "20261107-130000-eeeeee.log")) else ""
finally:
    O.SANDBOX_EXEC, O.HEAVY, O.package_manager = old
check("prepare: срок 2 с, heavy ждёт место 3 с — установка дождалась и вышла кодом 0, а не -1", code == 0 and dt >= 2.5,
      (code, dt, log_text))

print(f"\n{TOTAL[0] - len(FAILS)} ok, {len(FAILS)} FAIL")
sys.exit(1 if FAILS else 0)
