"""Общая часть test_outside*.py: подмена sandbox-exec, ps-shim, временный HOME, помощники (metis-0750).

Не тест. Модуль выполняется при импорте: временный корень, STATE, заглушка, репозитории APP и OTHER с коммитами C1–C3.
Каждый файл test_outside*.py импортирует его и получает свою копию корня: файлы не делят ни папок, ни STATE, ни портов
(порт серверу даёт pick_port по свободным).
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import atexit as _atexit
_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="outside-root-"))
tempfile.tempdir = _ROOT
_atexit.register(shutil.rmtree, _ROOT, True)

LIBDIR = os.path.join(os.path.dirname(HERE), "lib")
GUARD_HOOKS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "hooks")
HOME = os.path.join(_ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE"))]:
    os.environ.pop(k)
os.environ.update({"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1", "TMPDIR": _ROOT, "GH_TOKEN": "secret-gh",
                   "PANTHEON_FAKE_PRESSURE": "1"})   # давление памяти Mac не решает за тест, сколько серверов поднять
sys.path.insert(0, LIBDIR)
import pantheon as P  # noqa: E402
O = P.outside_mod()


def _kill_servers():
    """Серверы теста гаснут и при падении проверки (мутант без гашения не оставляет http.server висеть)."""
    for s in O.servers().values():
        if s.get("pid"):
            O.kill_group(int(s["pid"]))


_atexit.register(_kill_servers)  # раньше rmtree: atexit идёт с конца
TEST_PROCS = []   # процессы, которые тест порождает сам в своих сессиях (сирота, «чужой», sleep)


class _Gk:
    """Процесс-внук, известный только по pid: в TEST_PROCS ради последнего рубежа (SIGKILL), как Popen."""

    def __init__(self, pid):
        self.pid = pid

    def kill(self):
        os.kill(self.pid, 9)

    def wait(self, timeout=None):
        pass


def fake_pids():
    """Номера всех процессов заглушки sandbox-exec и задач «turbo» за прогон (пишут сами при старте)."""
    try:
        with open(os.path.join(_ROOT, "fake-pids")) as fh:
            return [int(x) for x in fh.read().split()]
    except (OSError, ValueError):
        return []


def still_alive(pid, grace=3):
    """Жив ли процесс через grace с; своего зомби сперва прибрать — он уже не процесс."""
    end = time.monotonic() + grace
    while True:
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        if time.monotonic() >= end:
            return True
        time.sleep(0.1)


def _kill_leftovers():
    """Последний рубеж перед rmtree: всё, что тест породил, — SIGKILL (упавшая проверка не оставляет сирот)."""
    for proc in TEST_PROCS:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
    for pid in fake_pids():
        try:
            os.kill(pid, 9)
        except OSError:
            pass


_atexit.register(_kill_leftovers)

FAILS = []
TOTAL = [0]


def _bind_open():
    """Даёт ли окружение занять локальный TCP-порт (окно роли: нет, песочница — metis-0773, 0777)."""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return True
    except OSError:
        return False
    finally:
        s.close()


BIND_OPEN = _bind_open()
PORT_MISS = [0]    # сколько раз pick_port не нашёл порт — только при закрытом bind это значит «bind закрыт»
SKIPPED_BIND = []


def _pick_port_counted(taken, _real=O.pick_port):
    port = _real(taken)
    if not port and not BIND_OPEN:
        PORT_MISS[0] += 1
    return port


O.pick_port = _pick_port_counted


def check(name, cond, extra=""):
    """Случай, которому нужен bind на порт: при закрытом bind (окно роли) и после того, как сервер не нашёл свободный
    порт — строка «пропущено: …», остальные идут (metis-0777). При открытом bind пропуска нет: упавшая проверка — FAIL."""
    TOTAL[0] += 1
    if not cond and not BIND_OPEN and PORT_MISS[0]:
        SKIPPED_BIND.append(name)
        print(f"пропущено: {name} — bind на локальный порт закрыт (сервер не нашёл свободный порт)")
        return
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{extra}]"))
    if not cond:
        FAILS.append(name)


MAC = sys.platform == "darwin"


def check_mac(name, cond, extra=""):
    """Случай про libproc или /usr/sbin/lsof macOS: вне macOS (CI на Linux) — строка «пропущено», а не проверка."""
    if MAC:
        check(name, cond, extra)
    else:
        print(f"пропущено: нужен macOS — {name}")


# --- заглушка sandbox-exec: пишет argv и окружение, затем исполняет команду (или изображает npm) ------------------
REC = os.path.join(_ROOT, "sandbox-calls.jsonl")
FAKE = os.path.join(_ROOT, "fake-sandbox-exec")
DEVTREE_PIDS = os.path.join(_ROOT, "devtree-pids")      # «turbo» и его задача (metis-0606)
HOLD_RELEASE = os.path.join(_ROOT, "hold-release")      # тест «hold» идёт, пока нет этого файла
FAKE_PIDS = os.path.join(_ROOT, "fake-pids")            # все процессы заглушки и задачи «turbo» — для проверки сирот
# сторож сирот (metis-0614): заглушка и задача «turbo» живут в своих сессиях, и killpg раннера их не достаёт. Тест упал,
# убит по таймауту или мутант не гасит сервер — они гаснут сами, когда нет процесса теста или его папки _ROOT
WATCH = (f"import os as _o, threading as _th, time as _t\n"
         f"def _watch():\n"
         f"    while True:\n"
         f"        _t.sleep(0.5)\n"
         f"        try:\n"
         f"            _o.kill({os.getpid()}, 0)\n"
         f"        except ProcessLookupError:\n"
         f"            _o._exit(0)\n"
         f"        except OSError:\n"
         f"            pass\n"
         f"        if not _o.path.isdir({_ROOT!r}):\n"
         f"            _o._exit(0)\n"
         f"_th.Thread(target=_watch, daemon=True).start()\n"
         f"with open({FAKE_PIDS!r}, 'a') as _fh:\n"
         f"    _fh.write(str(_o.getpid()) + '\\n')\n")
with open(FAKE, "w") as fh:
    fh.write(f"#!{sys.executable}\n" + WATCH + (r'''
import json, os, sys, time
args = sys.argv[1:]
assert args[0] == "-f", args
profile, cmd = args[1], args[2:]
with open(%r, "a") as fh:
    fh.write(json.dumps({"profile": profile, "cmd": cmd, "cwd": os.getcwd(), "env": dict(os.environ)}) + "\n")
tail = cmd[-2:]
if tail == ["run", "dev"]:
    print("сервер слушает", os.environ["PORT"], flush=True)
    # не «-m http.server»: его server_bind зовёт socket.getfqdn, а обратный DNS на раннере CI висит дольше
    # READY_SEC — порт не открывается вовремя (metis-0573)
    import http.server, socketserver
    class S(http.server.HTTPServer):
        def server_bind(self):
            socketserver.TCPServer.server_bind(self)
            self.server_name, self.server_port = "127.0.0.1", self.server_address[1]
    S(("127.0.0.1", int(os.environ["PORT"])), http.server.SimpleHTTPRequestHandler).serve_forever()
    os._exit(0)
if tail == ["run", "bad"]:
    print("boom: не собралось", flush=True)
    os._exit(3)
if tail == ["run", "slow"]:
    time.sleep(60)
    os._exit(0)
if tail == ["run", "devtree"]:
    # как turbo (metis-0606): задача — в своей сессии и группе процессов, на SIGTERM не гаснет и держит PORT; сам
    # «turbo» на SIGTERM выходит, задачу не гасит — killpg группы сервера её не достаёт
    import subprocess, signal
    task = (WATCH + "import os, signal, socket\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "s = socket.socket(); s.bind(('127.0.0.1', int(os.environ['PORT']))); s.listen(64)\n"
            "while True:\n    s.accept()[0].close()\n")
    # cwd="/": сирота по папке копии её не достаёт — гасит только обход потомков (strays), мутант без него убит
    kid = subprocess.Popen([sys.executable, "-c", task], start_new_session=True, cwd="/")
    with open(%r, "a") as fh:
        fh.write(f"{os.getpid()} {kid.pid}\n")
    time.sleep(600)
    os._exit(0)
if tail == ["run", "nap"]:
    time.sleep(1.5)
    os._exit(0)
if tail == ["run", "hold"]:
    end = time.time() + 120
    while time.time() < end and not os.path.exists(%r):
        time.sleep(0.2)
    os._exit(0)
if tail in (["run", "test"], ["run", "check"]):
    body = json.load(open("package.json"))["scripts"][tail[1]]
    os.execv("/bin/sh", ["/bin/sh", "-c", body])
if tail == ["run", "lint"] or cmd[1:2] in (["ci"], ["install"]):
    print("ok", cmd)
    os._exit(0)
os.execvp(cmd[0], cmd)
''' % (REC, DEVTREE_PIDS, HOLD_RELEASE)).replace("(WATCH + ", f"({WATCH!r} + "))
os.chmod(FAKE, 0o755)
O.SANDBOX_EXEC = FAKE
O.HEAVY = None
O.READY_SEC = 15
O.KILL_WAIT = 2
# свой случайный ряд портов вместо 3200–3299: два test_outside сразу (argus и разработчик) иначе берут один порт, и
# «сервер поднят» видит чужой слушатель (metis-0606)
import random as _random  # noqa: E402
DEFAULT_PORTS = O.SERVER_PORTS
_pbase = _random.randrange(20000, 48000, 100)
O.SERVER_PORTS = range(_pbase, _pbase + 100)


# setuid /bin/ps под sandbox-exec не запускается: test_outside, идущий через `pantheon outside test` (порты в окне
# закрыты), иначе не видит групп, памяти и времени старта. Тогда — заменитель на libproc с тем же выводом
# (pid, ppid, pgid, rss, lstart)
PS_SHIM = os.path.join(_ROOT, "ps-shim")
with open(PS_SHIM, "w") as fh:
    fh.write(f"#!{sys.executable}\n" + r'''
import ctypes, sys, time
lib = ctypes.CDLL("/usr/lib/libproc.dylib")
U = ctypes.c_uint32


class BSD(ctypes.Structure):   # struct proc_bsdinfo (sys/proc_info.h), PROC_PIDTBSDINFO = 3
    _fields_ = [(n, U) for n in ("flags", "status", "xstatus", "pid", "ppid", "uid", "gid", "ruid", "rgid", "svuid",
                                 "svgid", "rfu")] + [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)] + \
               [(n, U) for n in ("nfiles", "pgid", "pjobc", "tdev", "tpgid")] + \
               [("nice", ctypes.c_int32), ("start", ctypes.c_uint64), ("ustart", ctypes.c_uint64)]


def info(pid):
    b = BSD()
    ok = lib.proc_pidinfo(pid, 3, ctypes.c_uint64(0), ctypes.byref(b), ctypes.sizeof(b)) == ctypes.sizeof(b)
    return b if ok else None


def rss_kb(pid):   # struct proc_taskinfo: pti_virtual_size, pti_resident_size, …; PROC_PIDTASKINFO = 4
    t = (ctypes.c_uint64 * 12)()
    ok = lib.proc_pidinfo(pid, 4, ctypes.c_uint64(0), ctypes.byref(t), ctypes.sizeof(t)) == ctypes.sizeof(t)
    return t[1] // 1024 if ok else 0


args, fields, only = sys.argv[1:], [], None
for i, a in enumerate(args):
    if a in ("-o", "-axo"):
        fields = [f.rstrip("=") for f in args[i + 1].split(",")]
    if a == "-p":
        only = [int(args[i + 1])]
if only is None:
    n = lib.proc_listallpids(None, 0)
    buf = (ctypes.c_int * (n + 256))()
    got = lib.proc_listallpids(buf, ctypes.sizeof(buf))
    only = list(buf)[:got]
rows = []
for pid in only:
    b = info(pid)
    if b is None:
        continue
    val = {"pid": str(b.pid), "ppid": str(b.ppid), "pgid": str(b.pgid),
           "lstart": time.strftime("%a %b %e %H:%M:%S %Y", time.gmtime(b.start))}
    if "rss" in fields:
        val["rss"] = str(rss_kb(pid))
    rows.append(" ".join(val[f] for f in fields))
print("\n".join(rows))
sys.exit(0 if rows else 1)
''')
os.chmod(PS_SHIM, 0o755)
try:
    _ps_ok = subprocess.run(["/bin/ps", "-o", "pid=", "-p", str(os.getpid())], capture_output=True).returncode == 0
except OSError:
    _ps_ok = False
if not _ps_ok:
    print("ЗАМЕНЕНО: /bin/ps под песочницей не запускается — группы и время старта по libproc (ps-shim)")
    O.PS = PS_SHIM
# заменитель отдаёт то же, что ps: иначе его поломку увидит только прогон под песочницей

def calls():
    try:
        with open(REC) as fh:
            return [json.loads(x) for x in fh]
    except OSError:
        return []


def git(d, *args):
    """git в папке теста. Фоновый git самого прохода (сверка head, «грязное дерево») на миг держит index.lock: наша
    команда падала с «File exists» — как любой git при гонке за замок (metis-0672). Повтор только по этой причине;
    замок убитого git держится дольше срока повторов, и тест тогда упадёт."""
    for left in range(40, -1, -1):
        r = subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "-c",
                            "commit.gpgsign=false", *args], capture_output=True, text=True)
        if r.returncode == 0 or left == 0 or "index.lock" not in r.stderr or "File exists" not in r.stderr:
            break
        time.sleep(0.25)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


APP = os.path.join(HOME, "projects", "app")
OTHER = os.path.join(HOME, "projects", "other")
REPO = "latark/app"
PKG = {"name": "app", "scripts": {"dev": "next dev", "bad": "x", "slow": "x", "lint": "x", "devtree": "x", "hold": "x", "nap": "x"}}


def commit(d, files, msg):
    for name, text in files.items():
        p = os.path.join(d, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", msg)
    return git(d, "rev-parse", "HEAD")


for d in (APP, OTHER):
    os.makedirs(d)
    git(d, "init", "-q", "-b", "main")
git(APP, "remote", "add", "origin", "git@github.com:Latark/App.git")
git(OTHER, "remote", "add", "origin", "https://github.com/latark/other.git")
GREEN = "import sys; sys.exit(0)\n"
RED = "import sys; print('тест упал'); sys.exit(1)\n"
C1 = commit(APP, {"package.json": json.dumps(PKG), ".pantheon-verify": "# проверка\nheavy python3 t.py\n",
                  "t.py": GREEN, ".gitignore": "node_modules/\n"}, "c1")
C2 = commit(APP, {"t.py": RED}, "c2 red")
C3 = commit(APP, {"t.py": GREEN + "# c3\n"}, "c3")
commit(OTHER, {"t.py": GREEN, ".pantheon-verify": "python3 t.py\n"}, "o1")
P.write_json(os.path.join(STATE, "domains.json"),
             {"domains": {"athena-x": ["~/projects/app"], "metis-y": ["~/projects/other"]}})
RECORDS = os.path.join(STATE, "merge-gate", "records.jsonl")
NOW = time.time()


def accept(sha, repo=REPO, who="argus", age=0, pr=5):
    os.makedirs(os.path.dirname(RECORDS), exist_ok=True)
    t = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(NOW - age))
    rec = {"v": 1, "kind": "accept", "repo": [repo], "pr": pr, "sha": sha,
           "by": {"agent_type": who, "agent_id": "a", "session_id": "s"}, "cwd": APP, "time": t}
    with open(RECORDS, "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    open_pr(repo, sha)


def open_pr(repo, sha):
    """Кэш `autoclose fetch`: sha — head открытого PR (автопрогон берёт только такие, metis-0716)."""
    cp = os.path.join(STATE, "autoclose-prs.json")
    try:
        with open(cp) as fh:
            c = json.load(fh)
    except (OSError, ValueError):
        c = {}
    prs = c.setdefault("open_prs", {}).setdefault(repo, [])
    prs.append({"number": 100 + len(prs), "head": sha})
    c["fetched"] = time.time()
    c.setdefault("errors", {})
    with open(cp, "w") as fh:
        json.dump(c, fh)


def gate_records():
    """Записи журнала глазами настоящего шлюза guard (merge_gate.read_records + _valid)."""
    code = ("import sys, json; sys.path.insert(0, %r); import guard_rules, merge_gate as m; "
            "print(json.dumps(m.read_records()))" % GUARD_HOOKS)
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                       env={"HOME": HOME, "PATH": os.environ["PATH"]})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def tests_for(sha):
    return [r for r in gate_records() if r["kind"] == "tests" and r["sha"] == sha]


def alerts():
    try:
        with open(os.path.join(HOME, "ai", "pantheon", "alerts.md")) as fh:
            return fh.read()
    except OSError:
        return ""




CACHE = os.path.join(HOME, "Library", "Caches", "pantheon-sandbox")
os.makedirs(os.path.join(CACHE, "athena-x", "tmp"))
os.makedirs(os.path.join(CACHE, "workshop", "tmp"))
os.makedirs(os.path.join(CACHE, "metis-y", "tmp"))


def role_request(window, cwd, *args):
    os.environ["PANTHEON_TMP"] = os.path.join(CACHE, window, "tmp")
    old = os.getcwd()
    os.chdir(cwd)
    try:
        rc = O.main(list(args))
    finally:
        os.chdir(old)
        os.environ.pop("PANTHEON_TMP")
    q = os.path.join(CACHE, window, "outside")
    ids = sorted(n[:-9] for n in os.listdir(q) if n.endswith(".req.json"))
    return rc, q, ids[-1] if ids else None


def run_pass():
    return O.cmd_run()


def _touch(d, rel, text="x"):
    os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
    with open(os.path.join(d, rel), "w") as fh:
        fh.write(text)



import contextlib  # noqa: E402
import io  # noqa: E402
import signal  # noqa: E402,F401  (для файлов, что берут имена звёздочкой)
import threading  # noqa: E402,F401


def port_open(port):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def serve_pass():
    """Один круг прохода серверов (без житья сторожем)."""
    return O.cmd_run_serve(once=True)


def say(window, *args):
    """Команда роли из окна window (None — вне окна, очередь STATE) → (код, вывод)."""
    if window:
        os.environ["PANTHEON_TMP"] = os.path.join(CACHE, window, "tmp")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = O.main(list(args))
    finally:
        os.environ.pop("PANTHEON_TMP", None)
    return rc, buf.getvalue()


def wait_for(fn, sec):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    return fn()


def state(q, rid):
    return (O.load_result(q, rid) or {}).get("state")


def pid_alive(pid, grace=3):
    end = time.monotonic() + grace
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        if time.monotonic() >= end:
            return True
        time.sleep(0.1)


def new_request(window, cwd, *args):
    """Заявка роли → (папка, ID) — новый файл, а не последний по имени (две заявки в одну секунду)."""
    q = os.path.join(CACHE, window, "outside")
    before = set(os.listdir(q)) if os.path.isdir(q) else set()
    rc, q, _ = role_request(window, cwd, *args)
    return q, next(n[:-9] for n in os.listdir(q) if n.endswith(".req.json") and n not in before)


def worktrees(d=APP):
    return git(d, "worktree", "list", "--porcelain")


def work_of(rid):
    return os.path.join(os.path.realpath(HOME), "Library", "Caches", "pantheon-outside", "work", rid)


def events(rid=None, kind=None):
    try:
        rows = [json.loads(x) for x in open(os.path.join(STATE, "logs", "outside.jsonl"))]
    except OSError:
        return []
    return [x for x in rows if (rid is None or x.get("id") == rid) and (kind is None or x.get("kind") == kind)]


def kill_all_servers():
    srv = O.servers()
    for r, s in srv.items():
        if s.get("pid"):
            O.kill_group(int(s["pid"]))
        O.reap(s.get("work"))
        O.remove_work(s.get("common"), s.get("work"))
    O.save_servers({})

_atexit.register(kill_all_servers)

_cp = os.path.join(STATE, "autoclose-prs.json")
qa = os.path.join(CACHE, "athena-x", "outside")


def put_cache(old_heads=None, prs=None, fetched=None, errors=None):
    with open(_cp, "w") as fh:
        json.dump({"fetched": time.time() if fetched is None else fetched, "open_prs": prs or {},
                   "old_heads": old_heads or {}, "errors": errors or {}}, fh)


def one_request(window=None, qd=None, rid=None, script=None):
    """Заявка test на APP с id по счётчику (role_request берёт последнюю по имени, а время — секундами)."""
    one_request.n += 1
    rid = rid or f"20261103-0{one_request.n:05d}-c0c0c0"
    req = {"v": 1, "id": rid, "kind": "test", "dir": APP, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if script:
        req["script"] = script
    with open(os.path.join(qd or qa, rid + ".req.json"), "w") as fh:
        json.dump(req, fh)
    return rid


one_request.n = 0
NEWH = "9" * 40


def test_work(rid):
    return os.path.join(os.path.realpath(HOME), "Library", "Caches", "pantheon-outside", "work", "test-" + rid)


__all__ = [k for k in dir() if not k.startswith("__")]
