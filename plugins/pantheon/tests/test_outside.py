#!/usr/bin/env python3
"""Проверки вне окна роли ([sb-simplify] п. 7, lib/outside.py): sandbox-exec подменён записывающей заглушкой.

Запуск: python3 -I plugins/pantheon/tests/test_outside.py  (код выхода 0 — все прошли)
Проверяет на временных папках: после «принять» argus проход сам гоняет тесты и пишет запись tests, которую
принимает настоящий merge_gate.read_records guard; красные тесты, чужой agent_type, старое «принять», уже есть
tests, грязное дерево, команда меняет дерево, пустая команда — записи нет; коммит не на HEAD — временный worktree с
установкой зависимостей и его уборка; заявка роли из кэша окна → итог рядом с ней; окно не своего направления,
мастерская, подложенная ссылка, скрипта нет — отказ; dev-сервер (metis-0614) — свой проход и сторож, своя копия на
коммите (--sha), порт 4300–4399 мимо портов владельца, не больше двух и отказ при давлении памяти, монорепо и --app,
dev-ключи из STATE окружением, «стоп» из любого окна и «нет такой заявки», отмена до запуска, срок, сирота по папке
копии, лимит памяти сервера; безопасность копии: .git-файл роли, конфиг клона с командами, подмодули, worktree
для тестов после «принять» — через trusted_clone; окружение команды с нуля; профиль; тик зовёт каждый проход только по
делу; `outside run` из окна Claude Code — отказ; guard не спрашивает; сирот нет: заглушка и задачи «turbo» гаснут сами
без процесса теста (и при SIGKILL раннера), в конце — проверка, что ни одна не жива.
Порты в окне роли закрыты, поэтому в Пантеоне файл идёт через `pantheon outside test` — под песочницей прохода. Там
живые пробы sandbox-exec пропускаются (вложенная песочница), а setuid /bin/ps не запускается — вместо него ps-shim на
libproc с тем же выводом, вместе с rss (O.PS); что он совпадает с ps, проверяется и в обычном прогоне.
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
from _py311 import PY311  # pantheon.py — только на Python 3.11+

if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)] + sys.argv[1:])

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


def check(name, cond, extra=""):
    TOTAL[0] += 1
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
_me = os.getpid()
_sh = subprocess.run([PS_SHIM, "-axo", "pid=,ppid=,pgid=,rss="], capture_output=True,
                     text=True).stdout.split("\n") if MAC else []
_row = next((ln.split() for ln in _sh if ln.split()[:1] == [str(_me)]), [])
check_mac("ps-shim (libproc): pid, ppid, pgid теста — как у ОС, rss больше нуля",
          _row[:3] == [str(_me), str(os.getppid()), str(os.getpgrp())] and int(_row[3]) > 0, _row)
if not MAC:
    print("пропущено: нужен macOS — ps-shim (libproc): время старта — как у ps (UTC)")
elif _ps_ok:
    _real = subprocess.run(["/bin/ps", "-o", "lstart=", "-p", str(_me)], capture_output=True, text=True,
                           env={"LC_ALL": "C", "TZ": "UTC", "PATH": "/usr/bin:/bin"}).stdout.split()
    _fake = subprocess.run([PS_SHIM, "-o", "lstart=", "-p", str(_me)], capture_output=True, text=True).stdout.split()
    check("ps-shim (libproc): время старта — как у ps (UTC)", _real and _real == _fake, (_real, _fake))


def calls():
    try:
        with open(REC) as fh:
            return [json.loads(x) for x in fh]
    except OSError:
        return []


def git(d, *args):
    r = subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        *args], capture_output=True, text=True)
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


# --- 1. профиль и команда -----------------------------------------------------------------------------------------
prof = O.profile_text([os.path.realpath(APP)])
check("профиль: ~/.ssh закрыт на чтение", f'(subpath "{os.path.realpath(HOME)}/.ssh")' in prof.split("(deny file-write*\n")[0])
check("профиль: пароль демона CDP закрыт", "/.config/cdp-daemon" in prof)
check("профиль: .env* и secrets/", '/\\.env[^/]*$' in prof and "/secrets(/|$)" in prof)
# metis-0578: шаблоны .env.example/.sample/.template читаются, остальное .env* закрыто; запись в шаблоны закрыта
ALLOW = '(allow file-read* (regex #"/\\.env\\.(example|sample|template)$"))'
DENY_SEC = '(deny file-read* (regex #"/secrets(/|$)"))'
check("профиль: deny чтения < allow шаблонов .env < deny secrets < deny записи",
      ALLOW in prof and DENY_SEC in prof and prof.index("(deny file-read* file-write*") < prof.index(ALLOW)
      < prof.index(DENY_SEC) < prof.index("(deny file-write*\n"))


def env_probe(profile):
    """Живая проба: (None, причина), если sandbox-exec не запускается; иначе список расхождений с ожиданием."""
    d = os.path.realpath(tempfile.mkdtemp(prefix="env-probe-", dir=_ROOT))
    sb = os.path.join(d, "p.sb")
    with open(sb, "w") as fh:
        fh.write(profile)

    def run(*cmd):
        return subprocess.run(["/usr/bin/sandbox-exec", "-f", sb, *cmd], capture_output=True, text=True, cwd=d)
    # metis-0634: сначала — запускается ли sandbox-exec, и только потом файлы .env*. Внутри песочницы (окно роли, сам
    # проход outside) вложенный sandbox_apply запрещён, а профиль outside ещё и не даёт создать .env*: файлы первыми —
    # PermissionError и весь файл тестов красный вместо «ПРОПУЩЕНО».
    try:
        r = run("/usr/bin/true")
    except OSError as e:
        return None, str(e)
    if r.returncode != 0 and "sandbox_apply" in r.stderr:
        return None, r.stderr.strip()
    try:
        for n in (".env", ".env.local", ".env.production.local", ".env.example.bak", ".env.example", ".env.sample",
                  ".env.template"):
            with open(os.path.join(d, n), "w") as fh:
                fh.write("x")
    except PermissionError as e:   # тест под профилем прохода (`pantheon outside test`): .env* там закрыт
        return None, f"файлы .env* не создать — тест уже под песочницей ({e.strerror})"
    os.makedirs(os.path.join(d, "secrets"))
    with open(os.path.join(d, "secrets", ".env.example"), "w") as fh:
        fh.write("x")
    bad = []
    for n in (".env.example", ".env.sample", ".env.template"):
        if run("/bin/cat", n).returncode != 0:
            bad.append("читать " + n)
    for n in (".env", ".env.local", ".env.production.local", ".env.example.bak"):
        if run("/bin/cat", n).returncode == 0:
            bad.append("прочитан " + n)
    if run("/bin/cat", "secrets/.env.example").returncode == 0:
        bad.append("прочитан secrets/.env.example")
    # запись в шаблон: deny file-write* на .env* не снимается allow-ом чтения
    if run("/bin/sh", "-c", "echo y > .env.example").returncode == 0:
        bad.append("записан .env.example")
    return bad, ""


bad, why = env_probe(prof)
if bad is None:
    print("ПРОПУЩЕНО (живая проба .env*): sandbox-exec не запускается:", why)
else:
    check("профиль вживую: .env.example читается, .env/.env.local/.env.*.local/.env.example.bak и запись закрыты",
          bad == [], bad)
    check("мутант «нет allow» ловится пробой", env_probe(prof.replace(ALLOW, ""))[0] != [])
    check("мутант «без повторного deny secrets» ловится пробой", env_probe(prof.replace(DENY_SEC, ""))[0] != [])
    check("мутант «allow без $» ловится пробой", env_probe(prof.replace("(example|sample|template)$", "(example|sample|template)"))[0] != [])
check("профиль: Связка ключей", "com.apple.SecurityServer" in prof and "/Library/Keychains" in prof)
check("профиль: порты браузеров и прокси",
      all(f'(remote ip "*:{p}")' in prof for p in (9222, 9333, 9334, 9339, 6152, 6153)) and '"*:9340"' not in prof)
check("профиль: запись в STATE закрыта", f'(subpath "{STATE}")' in prof.split("(deny file-write*\n")[1])
check("профиль: .git/config папок реестра", "\\.git/(config|hooks)" in prof)
wsec = prof.split("(deny file-write*\n")[1]
check("профиль: запись в ~/.nvm, ~/.claude и кэши окон закрыта",
      all(x in wsec for x in ('/.nvm")', '/.claude")', '/Library/Caches/pantheon-sandbox")')), wsec)
# metis-0573: ключ реестра в ~/.npmrc — закрыт и на чтение (npm и pnpm без него работают, проба 28.10)
rsec = prof.split("(deny file-write*\n")[0]
check("профиль: ~/.npmrc, ~/.netrc закрыты на чтение",
      all(f'(literal "{os.path.realpath(HOME)}/{x}")' in rsec for x in (".npmrc", ".netrc", ".git-credentials")), rsec)
HEAD_NOTE = "python3 t.py  # .pantheon-verify ветки (HEAD)"
check("команда: строка .pantheon-verify без heavy, из ветки — с пометкой",
      O.command(os.path.realpath(APP), "test") == (["/bin/sh", "-c", "python3 t.py"], HEAD_NOTE))
# metis-0653: строка `dev:` — только для исполнителя; outside берёт первую некомментарную строку
commit(OTHER, {".pantheon-verify": "# полный\npython3 t.py\ndev: python3 narrow.py\n"}, "o2 dev-строка")
check("команда: строка `dev:` .pantheon-verify outside не берёт — первая некомментарная",
      O.command(os.path.realpath(OTHER), "test")[0] == ["/bin/sh", "-c", "python3 t.py"])
commit(OTHER, {".pantheon-verify": "# только узкая\ndev: python3 narrow.py\npython3 t.py\n"}, "o3 dev-строка первой")
check("команда: `dev:` первой строкой пропускается, берётся следующая некомментарная",
      O.command(os.path.realpath(OTHER), "test")[0] == ["/bin/sh", "-c", "python3 t.py"])
commit(OTHER, {".pantheon-verify": "dev: python3 narrow.py\n"}, "o4 только dev")
check("команда: только строка `dev:` — не команда, дальше package.json/pytest (здесь нечем — отказ)",
      O.command(os.path.realpath(OTHER), "test")[0] is None)
commit(OTHER, {".pantheon-verify": "python3 t.py\n"}, "o5 вернул")
check("команда: --script из package.json", O.command(os.path.realpath(APP), "test", "lint")[1] == "npm run lint")
check("команда: скрипта нет — отказ", O.command(os.path.realpath(APP), "test", "nope")[0] is None)
check("команда: сервер без скрипта dev — отказ", O.command(os.path.realpath(OTHER), "serve")[0] is None)
check("пустые команды", all(O.empty_command(x) for x in ("true", "CI=1 true", "echo ok", "/bin/echo", ":",
                                                       "npm run test  # package.json: echo no tests"))
      and not O.empty_command("npm run test  # package.json: vitest run")
      and not O.empty_command("python3 t.py") and not O.empty_command("pnpm run test"))

# .pantheon-verify — из ветки по умолчанию (origin/main), а не из PR
B = os.path.join(_ROOT, "base-probe")
shutil.copytree(APP, B)
base = git(B, "rev-parse", "HEAD")
commit(B, {".pantheon-verify": "true\n"}, "ослабил проверку")
git(B, "update-ref", "refs/remotes/origin/main", base)
check("команда: .pantheon-verify из origin/main, правка ветки не действует", O.command(B, "test")[1] == "python3 t.py")

# --- 2. прямой путь: заявка test -> run_test в папке клона (автопрогонов нет, решение владельца 03.11) ----------------
APPR = os.path.realpath(APP)


def direct(rid):
    return O.run_test(rid, APPR, None, "athena-x", None, [APPR])


before = len(calls())
res = direct("direct-c3")
check("прямой прогон C3 (HEAD): код 0, запись есть", res.get("code") == 0 and res.get("record") is True, res)
recs = tests_for(C3)
check("запись tests принята настоящим шлюзом guard", len(recs) == 1, gate_records())
r0 = recs[0] if recs else {}
check("запись: команда и папка", r0.get("cmd") == HEAD_NOTE and r0.get("cwd") == APPR, r0)
check("запись: repo по remote, pr null, by = проход, window",
      r0.get("repo") == [REPO] and r0.get("pr") is None and r0.get("by", {}).get("agent_type") == "pantheon-outside"
      and r0.get("by", {}).get("window") == "athena-x", r0)
c = calls()[before:]
check("прогон — под sandbox-exec с профилем STATE/outside/profile.sb",
      len(c) == 1 and c[0]["profile"] == os.path.join(STATE, "outside", "profile.sb") and os.path.isfile(c[0]["profile"]), c)
env = c[0]["env"] if c else {}
check("окружение с нуля: нет GH_TOKEN, есть CI=1 и свой TMPDIR",
      "GH_TOKEN" not in env and env.get("CI") == "1" and env.get("TMPDIR", "").startswith(_ROOT)
      and env.get("HOME") == os.path.realpath(HOME), sorted(env))

# красные тесты: записи нет, хвост журнала в итоге
C4 = commit(APP, {"t.py": RED}, "c4 red")
res = direct("direct-c4")
check("красный: код 1, записи нет", res.get("code") == 1 and not tests_for(C4) and res.get("record") is False, res)
check("красный: хвост журнала в итоге", "тест упал" in (res.get("tail") or ""), res)

# команда портит дерево — записи нет
C5 = commit(APP, {"t.py": "open('junk.txt', 'w').write('x')\n"}, "c5 пачкает")
res = direct("direct-c5")
check("команда изменила дерево: записи нет, причина названа",
      not tests_for(C5) and res.get("code") == 0 and "изменила HEAD или дерево" in (res.get("why") or ""), res)
os.remove(os.path.join(APP, "junk.txt"))

# пустая команда в .pantheon-verify — записи нет
C6 = commit(APP, {".pantheon-verify": "true\n"}, "c6 пустая проверка")
res = direct("direct-c6")
check("пустая команда (true): записи нет", not tests_for(C6) and "ничего не проверяет" in (res.get("why") or ""), res)
C7 = commit(APP, {".pantheon-verify": "heavy python3 t.py\n", "t.py": GREEN}, "c7")

# --- 3. заявка роли из окна -------------------------------------------------------------------------------------
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


rc, q, rid = role_request("athena-x", APP, "test")
check("заявка роли: в кэше окна, код 0", rc == 0 and rid and os.path.isfile(os.path.join(q, rid + ".req.json")), (rc, rid))
check("тик: заявка есть — проход нужен", O.pending())
os.environ["PANTHEON_DRYRUN"] = "1"
P.outside_kick()
os.environ.pop("PANTHEON_DRYRUN")
with open(os.path.join(STATE, "dryrun.log")) as fh:
    check("тик зовёт `outside run`", "outside-run" in fh.read())
check("проход: код 0", run_pass() == 0)
res = O.load_result(q, rid)
check("итог рядом с заявкой: done, код 0, запись tests", res and res["state"] == "done" and res["code"] == 0 and res["record"], res)
check("заявка снята", not os.path.exists(os.path.join(q, rid + ".req.json")))
check("запись tests по заявке — window в by", any(r["by"].get("window") == "athena-x" for r in tests_for(C7)))
os.environ["PANTHEON_TMP"] = os.path.join(CACHE, "athena-x", "tmp")
check("--wait: итог готов — код команды", O.wait_result(q, rid, 3) == 0)
os.environ.pop("PANTHEON_TMP")
os.environ["PANTHEON_DRYRUN"] = "1"
open(os.path.join(STATE, "dryrun.log"), "w").close()
P.outside_kick()
os.environ.pop("PANTHEON_DRYRUN")
import inspect  # noqa: E402
check("tick() зовёт outside_kick после merge_kick", "merge_kick()\n        outside_kick()" in inspect.getsource(P.tick))
check("тик без дела — прохода нет", open(os.path.join(STATE, "dryrun.log")).read() == "")

# отказы
rc, q, rid = role_request("metis-y", APP, "test")
run_pass()
res = O.load_result(q, rid) or {}
check("окно другого направления: отказ", res.get("state") == "failed" and "не из папок направления metis-y" in res.get("why", ""), res)
rc, q, rid = role_request("workshop", APP, "test")
run_pass()
res = O.load_result(q, rid) or {}
check("мастерская (не направление): отказ", res.get("state") == "failed" and "не направление" in res.get("why", ""), res)
rc, q, rid = role_request("athena-x", APP, "test", "--script", "nope")
run_pass()
res = O.load_result(q, rid) or {}
check("скрипта нет: отказ", res.get("state") == "failed" and "нет скрипта" in res.get("why", ""), res)
rc, q, rid = role_request("athena-x", APP, "test", "--script", "lint")
before_recs = len(gate_records())
run_pass()
res = O.load_result(q, rid) or {}
check("--script: прогон есть, код 0, записи tests нет", res.get("state") == "done" and res.get("code") == 0
      and res.get("record") is False and "только у проверки проекта" in res.get("note", "")
      and len(gate_records()) == before_recs, res)
os.environ["PANTHEON_TMP"] = os.path.join(CACHE, "athena-x", "tmp")
check("--script: --wait даёт код команды 0", O.wait_result(q, rid, 3) == 0)
os.environ.pop("PANTHEON_TMP")
rc, _, _ = role_request("athena-x", APP, "test", "--script", "a;rm")
check("имя скрипта не по образцу: код 2", rc == 2)
rc, _, _ = role_request("athena-x", os.path.join(APP, "node_modules") if os.path.isdir(os.path.join(APP, "node_modules")) else _ROOT, "test")
check("не репозиторий: код 2", rc == 2)

with open(os.path.join(APP, "t.py"), "a") as fh:
    fh.write("# грязно\n")
rc, q, rid = role_request("athena-x", APP, "test")
run_pass()
res = O.load_result(q, rid) or {}
check("грязное дерево: отказ, записи нет", res.get("state") == "failed" and "не чистое" in res.get("why", ""), res)
git(APP, "checkout", "--", "t.py")


# .claude/worktrees/ (живые worktree субагентов) — не грязь; прочее неотслеживаемое и правки — грязь
def _dirty_case(name, mk, want):
    d = tempfile.mkdtemp(prefix="hs-", dir=os.environ.get("TMPDIR"))
    git(d, "init", "-q")
    commit(d, {"a.txt": "1\n", ".claude/settings.json": "{}"}, "i")
    mk(d)
    check(f"head_state: {name}", O.head_state(d)[1] is want, git(d, "status", "--porcelain"))
    shutil.rmtree(d, ignore_errors=True)


def _touch(d, rel, text="x"):
    os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
    with open(os.path.join(d, rel), "w") as fh:
        fh.write(text)


_dirty_case("только ?? .claude/worktrees/ — чисто", lambda d: _touch(d, ".claude/worktrees/x/f"), True)
_dirty_case("?? other.txt — грязно", lambda d: _touch(d, "other.txt"), False)
_dirty_case("worktrees и ?? other.txt — грязно", lambda d: (_touch(d, ".claude/worktrees/x/f"), _touch(d, "other.txt")), False)
_dirty_case("worktrees и правка отслеживаемого — грязно",
            lambda d: (_touch(d, ".claude/worktrees/x/f"), _touch(d, "a.txt", "2\n")), False)
_dirty_case(".claude/worktrees-evil/ — грязно", lambda d: _touch(d, ".claude/worktrees-evil/f"), False)
_dirty_case("a/.claude/worktrees/ — грязно", lambda d: _touch(d, "a/.claude/worktrees/f"), False)
_dirty_case("отслеживаемый файл под worktrees с правкой — грязно",
            lambda d: (_touch(d, ".claude/worktrees/t"), git(d, "add", "-f", ".claude/worktrees/t"),
                       git(d, "commit", "-q", "-m", "t"), _touch(d, ".claude/worktrees/t", "y")), False)

# ссылка node_modules (metis-0721): только неотслеживаемая симлинка в корне, apps/*, packages/* — не грязь
def _nm_link(rel):
    return lambda d: (os.makedirs(os.path.dirname(os.path.join(d, rel)) or d, exist_ok=True),
                      os.symlink("/nonexistent-target", os.path.join(d, rel)))


_dirty_case("симлинк node_modules в корне — чисто", _nm_link("node_modules"), True)
_dirty_case("симлинк apps/x/node_modules — чисто", lambda d: (_touch(d, "apps/x/p.json"), git(d, "add", "-A"),
            git(d, "commit", "-q", "-m", "a"), _nm_link("apps/x/node_modules")(d)), True)
_dirty_case("симлинк packages/y/node_modules — чисто", lambda d: (_touch(d, "packages/y/p.json"), git(d, "add", "-A"),
            git(d, "commit", "-q", "-m", "a"), _nm_link("packages/y/node_modules")(d)), True)
_dirty_case("симлинк в корне и ?? other.txt — грязно", lambda d: (_nm_link("node_modules")(d), _touch(d, "other.txt")), False)
_dirty_case("папка node_modules с файлом — грязно", lambda d: _touch(d, "node_modules/f"), False)
_dirty_case("файл node_modules — грязно", lambda d: _touch(d, "node_modules"), False)
_dirty_case("симлинк с другим именем — грязно", _nm_link("modules"), False)
_dirty_case("симлинк apps/x/y/node_modules глубже — грязно", _nm_link("apps/x/y/node_modules"), False)
_dirty_case("симлинк nested/node_modules — грязно", _nm_link("nested/node_modules"), False)

# та же функция без git init: разбор вывода status + проверка «это симлинк»
_td = tempfile.mkdtemp(prefix="tc-", dir=os.environ.get("TMPDIR"))
os.symlink("/nonexistent-target", os.path.join(_td, "node_modules"))
os.makedirs(os.path.join(_td, "apps", "x", "node_modules"))
os.symlink("/nonexistent-target", os.path.join(_td, "apps", "x", "y"))
check("tree_clean: симлинк node_modules в корне", P.tree_clean("?? node_modules\n", _td) is True)
check("tree_clean: папка apps/x/node_modules (не симлинк) — грязно", P.tree_clean("?? apps/x/node_modules\n", _td) is False)
check("tree_clean: ссылка глубже — грязно", P.tree_clean("?? apps/x/y/node_modules\n", _td) is False)
check("tree_clean: изменённый отслеживаемый — грязно", P.tree_clean(" M node_modules\n", _td) is False)
check("tree_clean: None — грязно", P.tree_clean(None, _td) is False)
shutil.rmtree(_td, ignore_errors=True)

# подложенная ссылка вместо заявки — не читается и не исполняется
q = os.path.join(CACHE, "athena-x", "outside")
secret = os.path.join(_ROOT, "secret.json")
with open(secret, "w") as fh:
    json.dump({"v": 1, "id": "20261028-010101-abcdef", "kind": "test", "dir": APP}, fh)
os.symlink(secret, os.path.join(q, "20261028-010101-abcdef.req.json"))
before = len(calls())
run_pass()
res = O.load_result(q, "20261028-010101-abcdef") or {}
check("ссылка вместо заявки: не исполнена", len(calls()) == before and res.get("state") == "failed", res)
check("ссылка убрана, файл-цель цел", not os.path.lexists(os.path.join(q, "20261028-010101-abcdef.req.json")) and os.path.exists(secret))

# очередь STATE (ваши сессии): любые папки реестра
old = os.getcwd()
os.chdir(OTHER)
rc = O.main(["test"])
os.chdir(old)
check("вне окна: заявка в STATE/outside/queue", rc == 0 and any(n.endswith(".req.json") for n in os.listdir(os.path.join(STATE, "outside", "queue"))))
run_pass()
check("очередь STATE: проверка другой папки реестра прошла, запись tests",
      len(tests_for(git(OTHER, "rev-parse", "HEAD"))) == 1)

# скрипт test из package.json ветки: тело видно в записи; пустое тело — записи нет
PKGD = os.path.join(HOME, "projects", "pkg")
os.makedirs(PKGD)
git(PKGD, "init", "-q", "-b", "main")
git(PKGD, "remote", "add", "origin", "https://github.com/latark/pkg.git")
commit(PKGD, {"package.json": json.dumps({"scripts": {"test": "python3 -c 'import sys; sys.exit(0)'"}}),
              "pnpm-lock.yaml": ""}, "p1")
P.write_json(os.path.join(STATE, "domains.json"),
             {"domains": {"athena-x": ["~/projects/app"], "metis-y": ["~/projects/other", "~/projects/pkg"]}})
os.chdir(PKGD)
O.main(["test"])
os.chdir(old)
run_pass()
pr = tests_for(git(PKGD, "rev-parse", "HEAD"))
check("package.json: запись tests с телом скрипта", len(pr) == 1
      and pr[0]["cmd"] == "pnpm run test  # package.json: python3 -c 'import sys; sys.exit(0)'", pr)
P2 = commit(PKGD, {"package.json": json.dumps({"scripts": {"test": "echo no tests"}})}, "p2 пустой test")
os.chdir(PKGD)
O.main(["test"])
os.chdir(old)
run_pass()
check("package.json: пустое тело (echo) — записи нет", not tests_for(P2))

# проход только плановый
os.environ["CLAUDECODE"] = "1"
check("outside run из окна Claude Code: код 2", O.main(["run"]) == 2)
os.environ.pop("CLAUDECODE")
os.environ["CLAUDE_CODE_ENTRYPOINT"] = "cli"
check("outside run с CLAUDE_CODE_ENTRYPOINT: код 2", O.main(["run"]) == 2)
os.environ.pop("CLAUDE_CODE_ENTRYPOINT")

# --- 4. dev-сервер (metis-0614): свой проход, своя копия на коммите, порт из ряда, не больше двух, стоп откуда угодно -
import contextlib  # noqa: E402
import io  # noqa: E402
import signal  # noqa: E402
import threading  # noqa: E402


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


# порт, занятый слушателем на 0.0.0.0 (чужой http.server, dev-сервер), не свободен: на macOS bind с SO_REUSEADDR
# на 127.0.0.1 при этом удавался, сервер «поднимался» на чужом порту (metis-0592)
try:
    _wild = socket.socket()
    _wild.bind(("0.0.0.0", 0))
    _wild.listen()
    _wp = _wild.getsockname()[1]
    check("порт под слушателем на 0.0.0.0 не свободен", not O.port_free(_wp))
    _wild.close()
    _lo = socket.socket()
    _lo.bind(("127.0.0.1", 0))
    _lo.listen()
    check("порт под слушателем на 127.0.0.1 не свободен", not O.port_free(_lo.getsockname()[1]))
    _lo.close()
except PermissionError as e:  # окно роли: bind на локальный порт закрыт песочницей (metis-0773)
    print(f"пропущено: окно не даёт занять локальный порт ({e}) — случаи «порт под слушателем не свободен»")

# ряд портов: не 3000, не 3100–3199 (разработчики), не 3200 (показ владельцу) — 30.10 landing взял PORT=3200
check("ряд портов сервера по умолчанию — 4300–4399, без портов владельца",
      DEFAULT_PORTS == range(4300, 4400) and not set(DEFAULT_PORTS) & O.OWNER_PORTS
      and {3000, 3100, 3199, 3200} <= O.OWNER_PORTS, DEFAULT_PORTS)
_real_free, _real_ports = O.port_free, O.SERVER_PORTS
O.port_free, O.SERVER_PORTS = (lambda p: True), [3000, 3200, 3150, _pbase + 99]
try:
    check("pick_port: порты владельца пропускаются, даже если свободны", O.pick_port(set()) == _pbase + 99)
finally:
    O.port_free, O.SERVER_PORTS = _real_free, _real_ports

# заявка serve: queued до прохода, проход тестов её не берёт, тик зовёт проход серверов
before = len(calls())
rc, q, rid = role_request("athena-x", APP, "serve", "--minutes", "5")
HEAD = git(APP, "rev-parse", "HEAD")
res = O.load_result(q, rid) or {}
check("заявка serve: состояние queued сразу, коммит — HEAD папки", rc == 0 and res.get("state") == "queued"
      and res.get("sha") == HEAD, res)
check("тик: заявка serve — дело проходу серверов, не тестов", O.pending_serve() and not O.pending_test())
run_pass()
check("проход тестов заявку serve не съел", os.path.isfile(os.path.join(q, rid + ".req.json")) and len(calls()) == before)
os.environ["PANTHEON_DRYRUN"] = "1"
open(os.path.join(STATE, "dryrun.log"), "w").close()
P.outside_kick()
_dry = open(os.path.join(STATE, "dryrun.log")).read()
check("тик зовёт `outside run --serve`, а не проход тестов", "outside-serve" in _dry and "outside-run" not in _dry, _dry)
with P.lock("outside-serve", block=False) as _got:
    open(os.path.join(STATE, "dryrun.log"), "w").close()
    P.outside_kick()
    check("проход серверов уже идёт (замок outside-serve) — второго не зовёт",
          _got and "outside-serve" not in open(os.path.join(STATE, "dryrun.log")).read())
    check("пока идёт проход серверов, проход тестов не ждёт его замка", O.cmd_run() == 0)
os.environ.pop("PANTHEON_DRYRUN")

serve_pass()
res = O.load_result(q, rid) or {}
port, W = res.get("port") or 0, work_of(rid)
check("сервер: адрес http://127.0.0.1:<порт из ряда>", res.get("state") == "serving" and port in O.SERVER_PORTS
      and res.get("url") == f"http://127.0.0.1:{port}", res)
check("сервер отвечает по адресу", port_open(port))
c = calls()[before:]
check("сервер: своя копия на коммите заявки — сначала зависимости, сервер в папке копии",
      len(c) == 2 and c[0]["cmd"] == ["npm", "ci"] and c[0]["cwd"] == W and c[1]["cwd"] == W
      and git(W, "rev-parse", "HEAD") == HEAD and W in worktrees() and res.get("dir") == W, [(x["cmd"], x["cwd"]) for x in c])
check("сервер: PORT в окружении, без CI и GH_TOKEN", c and c[-1]["env"].get("PORT") == str(port)
      and "CI" not in c[-1]["env"] and "GH_TOKEN" not in c[-1]["env"], c[-1]["env"] if c else c)
check("сервер: без heavy (лимит держит проход)", c and "heavy" not in " ".join(c[-1]["cmd"]))
_s = O.servers().get(rid) or {}
check("сервер в servers.json: копия, клон, коммит, папка заявки", _s.get("work") == W and _s.get("sha") == HEAD
      and _s.get("src") == os.path.realpath(APP) and _s.get("common") == os.path.realpath(os.path.join(APP, ".git")), _s)
check("ключей нет — пометка, куда их класть", "latark__app.env" in res.get("note", ""), res)
check("тик: живой сервер — сторожу есть дело, тестам нет", O.pending_serve() and not O.pending_test())

rc, q2, rid2 = role_request("athena-x", APP, "serve")
serve_pass()
res2 = O.load_result(q2, rid2) or {}
check("второй сервер — другой порт и своя копия", res2.get("state") == "serving" and res2.get("port") != port
      and res2.get("dir") == work_of(rid2) and work_of(rid2) != W, res2)

# третий — отказ сразу, с причиной и кодом 75 (решение владельца 01.11: не больше двух, без очереди)
before = len(calls())
rc, q3, rid3 = role_request("athena-x", APP, "serve")
serve_pass()
res3 = O.load_result(q3, rid3) or {}
check("третий сервер: отказ «уже идут 2 сервера», код 75, ничего не запущено, копии нет",
      res3.get("state") == "failed" and "уже идут 2 сервера из 2" in res3.get("why", "") and rid in res3.get("why", "")
      and O.result_code(res3) == 75 and len(calls()) == before and not os.path.exists(work_of(rid3)), res3)

# «стоп» из окна координатора (другая папка заявок) — 30.10 стоп лежал в чужой папке, проход его не видел
rc, out = say("metis-y", "stop", rid, "--wait", "0")
check("стоп из другого окна: заявка известна (итог прохода в STATE), «стоп» записан в своей папке, код 0",
      rc == 0 and os.path.isfile(os.path.join(CACHE, "metis-y", "outside", rid + ".stop")), (rc, out))
check("тик: «стоп» — дело проходу серверов", O.pending_serve())
serve_pass()
res = O.load_result(q, rid) or {}
check("стоп из другого окна: погашен, итог stopped в папке заявки, порт свободен",
      res.get("state") == "stopped" and res.get("why") == "заявка «стоп»" and not port_open(port)
      and rid not in O.servers(), res)
check("стоп: копия снята (папки нет, git worktree list её не знает), «стоп» убран",
      not os.path.exists(W) and W not in worktrees()
      and not os.path.exists(os.path.join(CACHE, "metis-y", "outside", rid + ".stop")))
check("стоп: в журнале — кто просил", [e.get("by") for e in events(rid, "stop")] == [["metis-y"]], events(rid, "stop"))
check("второй сервер жив", port_open(res2.get("port") or 0) and rid2 in O.servers())
rc, out = say("metis-y", "stop", rid)
check("стоп погашенного: «уже stopped», код 0, без нового «стопа»", rc == 0 and "уже stopped" in out
      and not os.path.exists(os.path.join(CACHE, "metis-y", "outside", rid + ".stop")), (rc, out))

# «нет такой заявки» — честно, код 1, файла нет
rc, out = say("athena-x", "stop", "20261101-000000-abcdef", "--wait", "0")
check("стоп неизвестного ID: «нет такой заявки», код 1, «стоп» не записан", rc == 1 and "нет такой заявки" in out
      and not os.path.exists(os.path.join(CACHE, "athena-x", "outside", "20261101-000000-abcdef.stop")), (rc, out))
rc, _ = say("athena-x", "stop", "x;rm")
check("стоп: ID не по образцу — код 2", rc == 2)
rc, _ = say("athena-x", "stop", rid2, "--wait", "abc")
check("стоп: --wait не число — код 2", rc == 2)

# стоп из очереди STATE (сессия вне окна)
rc, out = say(None, "stop", rid2, "--wait", "0")
serve_pass()
res2 = O.load_result(q2, rid2) or {}
check("стоп из очереди STATE: погашен", rc == 0 and res2.get("state") == "stopped" and not O.servers()
      and not os.path.exists(work_of(rid2)), (rc, out, res2))

# «стоп» заявки, которая ещё в очереди — отмена до запуска
rc, q, rid = role_request("athena-x", APP, "serve")
rc, out = say("athena-x", "stop", rid, "--wait", "0")
before = len(calls())
serve_pass()
res = O.load_result(q, rid) or {}
check("стоп заявки в очереди: stopped «отменена», не запущено, копии нет", rc == 0 and res.get("state") == "stopped"
      and "отменена" in res.get("why", "") and len(calls()) == before and not os.path.exists(work_of(rid)), (rc, out, res))
check("стоп тестов: «это тесты», код 1", say("athena-x", "stop", rid_test_done, "--wait", "0")[0] == 1
      if (rid_test_done := next((n[:-12] for n in sorted(os.listdir(q)) if n.endswith(".result.json")
                                  and (O.load_result(q, n[:-12]) or {}).get("kind") == "test"), None)) else False)

# заявка пролежала дольше REQ_TTL — не запускается
rc, q, rid = role_request("athena-x", APP, "serve")
_fp = os.path.join(q, rid + ".req.json")
_req = json.load(open(_fp))
_req["time"] = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - 20 * 60))
json.dump(_req, open(_fp, "w"))
before = len(calls())
serve_pass()
res = O.load_result(q, rid) or {}
check("заявка старше 15 мин: failed «пролежала», не запущено", res.get("state") == "failed"
      and "пролежала 20 мин" in res.get("why", "") and len(calls()) == before, res)

# срок вышел — гаснет сам
rc, q, rid = role_request("athena-x", APP, "serve")
serve_pass()
port = (O.load_result(q, rid) or {}).get("port") or 0
os.environ["PANTHEON_NOW"] = str(time.time() + 31 * 60)
try:
    serve_pass()
finally:
    os.environ.pop("PANTHEON_NOW")
res = O.load_result(q, rid) or {}
check("срок вышел: сервер погашен сам, копия снята", res.get("state") == "stopped" and "срок" in res.get("why", "")
      and not port_open(port) and not os.path.exists(work_of(rid)), res)

rc, q, rid = role_request("athena-x", APP, "serve", "--script", "bad")
serve_pass()
res = O.load_result(q, rid) or {}
check("сервер упал: failed, код и хвост журнала, копия снята", res.get("state") == "failed"
      and "кодом 3" in res.get("why", "") and "boom" in res.get("tail", "") and not os.path.exists(work_of(rid)), res)
O.READY_SEC = 2
rc, q, rid = role_request("athena-x", APP, "serve", "--script", "slow")
serve_pass()
res = O.load_result(q, rid) or {}
check("порт не открылся: failed, процесс погашен", res.get("state") == "failed" and "не открылся" in res.get("why", "")
      and not O.servers() and not os.path.exists(work_of(rid)), res)
O.READY_SEC = 15
rc, _, _ = role_request("athena-x", APP, "serve", "--minutes", "500")
check("срок больше 120 минут: код 2", rc == 2)

# давление памяти: критичное — отказ любому, предупреждение — второму (решение владельца 01.11)
os.environ["PANTHEON_FAKE_PRESSURE"] = "4"
rc, q, rid = role_request("athena-x", APP, "serve")
serve_pass()
res = O.load_result(q, rid) or {}
check("давление памяти критичное: отказ сразу, код 75", res.get("state") == "failed"
      and "критичное" in res.get("why", "") and O.result_code(res) == 75 and not O.servers(), res)
os.environ["PANTHEON_FAKE_PRESSURE"] = "2"
rc, q, rid = role_request("athena-x", APP, "serve")
serve_pass()
check("давление «предупреждение», серверов нет — первый поднимается", state(q, rid) == "serving")
rc, q2, rid2 = role_request("athena-x", APP, "serve")
serve_pass()
res2 = O.load_result(q2, rid2) or {}
check("давление «предупреждение» и один сервер идёт — второму отказ, код 75", res2.get("state") == "failed"
      and "предупреждение" in res2.get("why", "") and O.result_code(res2) == 75 and set(O.servers()) == {rid}, res2)
os.environ["PANTHEON_FAKE_PRESSURE"] = "1"
kill_all_servers()

# лимит памяти у каждого сервера (решение владельца 01.11): дерево сервера больше лимита — сторож гасит с причиной
check("лимит памяти сервера по умолчанию — 4 ГБ (решение владельца 01.11)", O.SERVER_MEM_MB == 4096)
rc, q, rid = role_request("athena-x", APP, "serve")
serve_pass()
_srv = O.servers().get(rid) or {}
port = (O.load_result(q, rid) or {}).get("port") or 0
_mb = O.tree_mb(int(_srv.get("pid") or 0), O.ps_table())
O.sweep()
check("в пределах лимита сервер живёт, память дерева считается", rid in O.servers() and _mb > 0, (_mb, O.servers()))
_real_mem = O.SERVER_MEM_MB
O.SERVER_MEM_MB = 0
try:
    O.sweep()
finally:
    O.SERVER_MEM_MB = _real_mem
res = O.load_result(q, rid) or {}
check("дерево сервера больше лимита: погашен сам, причина «память», порт свободен, копия снята",
      res.get("state") == "stopped" and "память" in res.get("why", "") and rid not in O.servers()
      and not port_open(port) and not os.path.exists(work_of(rid)), res)
kill_all_servers()

# --sha: сервер на коммите PR, а не на HEAD папки (talos не входит в чужую worktree)
rc, q, rid = role_request("athena-x", APP, "serve", "--sha", C1[:10])
serve_pass()
res = O.load_result(q, rid) or {}
check("--sha: копия на этом коммите, HEAD папки не тронут", res.get("state") == "serving" and res.get("sha") == C1
      and git(work_of(rid), "rev-parse", "HEAD") == C1 and git(APP, "rev-parse", "HEAD") == HEAD, res)
kill_all_servers()
rc, q, rid = role_request("athena-x", APP, "serve", "--sha", "deadbeef1")
serve_pass()
res = O.load_result(q, rid) or {}
check("--sha нет в клоне: failed «git fetch»", res.get("state") == "failed" and "git fetch" in res.get("why", "")
      and not os.path.exists(work_of(rid)), res)
rc, _, _ = role_request("athena-x", APP, "serve", "--sha", "xyz;rm")
check("--sha не по образцу: код 2", rc == 2)
with open(os.path.join(APP, "t.py"), "a") as fh:
    fh.write("# правка без коммита\n")
rc, q, rid = role_request("athena-x", APP, "serve")
serve_pass()
res = O.load_result(q, rid) or {}
check("незакоммиченные правки: сервер на коммите, пометка", res.get("state") == "serving" and res.get("sha") == HEAD
      and "незакоммиченные" in res.get("note", ""), res)
git(APP, "checkout", "--", "t.py")
kill_all_servers()

# монорепо: PORT — одному приложению (--app), turbo.json не правится
MONO = os.path.join(HOME, "projects", "mono")
os.makedirs(MONO)
git(MONO, "init", "-q", "-b", "main")
git(MONO, "remote", "add", "origin", "https://github.com/latark/mono.git")
commit(MONO, {"package.json": json.dumps({"name": "root", "workspaces": ["apps/*"], "scripts": {"dev": "turbo run dev"}}),
              "pnpm-lock.yaml": "", ".gitignore": "node_modules/\n",
              "apps/web/package.json": json.dumps({"name": "@m/web", "scripts": {"dev": "next dev"}}),
              "apps/landing/package.json": json.dumps({"name": "landing", "scripts": {"dev": "next dev --port ${PORT:-3100}"}}),
              "apps/lib/package.json": json.dumps({"name": "lib", "scripts": {"build": "tsc"}})}, "m1")
P.write_json(os.path.join(STATE, "domains.json"),
             {"domains": {"athena-x": ["~/projects/app", "~/projects/mono"],
                          "metis-y": ["~/projects/other", "~/projects/pkg"]}})
rc, q, rid = role_request("athena-x", MONO, "serve")
serve_pass()
res = O.load_result(q, rid) or {}
check("монорепо без --app: отказ со списком приложений со скриптом", res.get("state") == "failed"
      and "--app" in res.get("why", "") and "@m/web" in res.get("why", "") and "landing" in res.get("why", "")
      and "lib" not in res.get("why", "").split("(")[1], res)
os.makedirs(os.path.join(STATE, "outside", "env"), mode=0o700)
with open(os.path.join(STATE, "outside", "env", "latark__mono.env"), "w") as fh:
    fh.write("# dev-ключи\nexport DATABASE_URL='postgres://dev-secret'\nPORT=1\nDYLD_INSERT_LIBRARIES=x\n"
             "API_KEY=root # проект\nPANTHEON_ROLE=x\n")
with open(os.path.join(STATE, "outside", "env", "latark__mono__web.env"), "w") as fh:
    fh.write('API_KEY="web-key"\n')
before = len(calls())
rc, q, rid = role_request("athena-x", MONO, "serve", "--app", "web")
serve_pass()
res = O.load_result(q, rid) or {}
c = calls()[before:]
env = c[-1]["env"] if c else {}
check("--app web: сервер в папке приложения копии, PORT — ему", res.get("state") == "serving"
      and c and c[-1]["cwd"] == os.path.join(work_of(rid), "apps", "web") and c[-1]["cmd"][-3:] == ["pnpm", "run", "dev"]
      and env.get("PORT") == str(res.get("port")), (res, [(x["cmd"], x["cwd"]) for x in c]))
check("--app: зависимости ставятся в корне копии (pnpm install --frozen-lockfile)",
      c and c[0]["cmd"] == ["pnpm", "install", "--frozen-lockfile"] and c[0]["cwd"] == work_of(rid), c[:1])
check("dev-ключи: из файла проекта и приложения, через окружение; служебные имена не перекрыты",
      env.get("DATABASE_URL") == "postgres://dev-secret" and env.get("API_KEY") == "web-key"
      and "DYLD_INSERT_LIBRARIES" not in env and env.get("PANTHEON_ROLE") is None and env.get("PORT") != "1", env)
_txt = json.dumps(res) + open(os.path.join(STATE, "logs", "outside.jsonl")).read()
check("dev-ключи: в итоге и журнале — только имена, значений нет",
      res.get("keys") == ["API_KEY", "DATABASE_URL"] and "dev-secret" not in _txt and "web-key" not in _txt, res.get("keys"))
check("dev-ключи: пропущенные служебные имена названы", "DYLD_INSERT_LIBRARIES" in res.get("note", "")
      and "PORT" in res.get("note", ""), res.get("note"))
kill_all_servers()
rc, q, rid = role_request("athena-x", MONO, "serve", "--app", "nope")
serve_pass()
check("--app нет такого: отказ со списком", state(q, rid) == "failed"
      and "нет приложения «nope»" in (O.load_result(q, rid) or {}).get("why", ""))
before = len(calls())
rc, q, rid = role_request("athena-x", MONO, "serve", "--app", ".")
serve_pass()
c = calls()[before:]
check("--app .: корневой скрипт в корне копии", state(q, rid) == "serving" and c and c[-1]["cwd"] == work_of(rid), c[-1:])
kill_all_servers()
rc, q, rid = role_request("athena-x", APP, "serve", "--app", "web")
serve_pass()
check("--app у не-монорепо: отказ", state(q, rid) == "failed"
      and "не монорепо" in (O.load_result(q, rid) or {}).get("why", ""))
rc, _, _ = role_request("athena-x", MONO, "serve", "--app", "../x")
check("--app не по образцу: код 2", rc == 2)

# metis-0790: не монорепо, без корневого package.json — приложение в подпапке (alexbroker: site/)
SUB = os.path.join(HOME, "projects", "subapp")
os.makedirs(SUB)
git(SUB, "init", "-q", "-b", "main")
git(SUB, "remote", "add", "origin", "https://github.com/latark/subapp.git")
commit(SUB, {"site/package.json": json.dumps({"name": "site", "scripts": {"dev": "next dev"}}),
             "site/pnpm-lock.yaml": "", "empty/readme.txt": "x", ".gitignore": "node_modules/\n"}, "s1")
os.symlink(os.path.join(HOME, "projects"), os.path.join(SUB, "out"))   # ссылка наружу корня
git(SUB, "add", "out")
git(SUB, "commit", "-q", "-m", "s2")
P.write_json(os.path.join(STATE, "domains.json"),
             {"domains": {"athena-x": ["~/projects/app", "~/projects/mono", "~/projects/subapp"],
                          "metis-y": ["~/projects/other", "~/projects/pkg"]}})
kill_all_servers()
before = len(calls())
rc, q, rid = role_request("athena-x", SUB, "serve", "--app", "site")
serve_pass()
res = O.load_result(q, rid) or {}
c = calls()[before:]
_site = os.path.join(work_of(rid), "site")
check("0790: --app site без корневого package.json — сервер в site/ (скрипт и cwd)",
      res.get("state") == "serving" and c and c[-1]["cwd"] == _site and c[-1]["cmd"][-3:] == ["pnpm", "run", "dev"]
      and c[-1]["env"].get("PORT") == str(res.get("port")), (res, [(x["cmd"], x["cwd"]) for x in c]))
check("0790: зависимости ставятся в site/, а не в корне копии",
      c and c[0]["cmd"] == ["pnpm", "install", "--frozen-lockfile"] and c[0]["cwd"] == _site, c[:1])
kill_all_servers()
rc, q, rid = role_request("athena-x", SUB, "serve")
serve_pass()
check("0790: без --app и без корневого package.json — прежний отказ",
      state(q, rid) == "failed" and "нет package.json" in (O.load_result(q, rid) or {}).get("why", ""))
for _bad, _why in (("out", "вне корня"), ("empty", "нет package.json"), ("nope", "не монорепо")):
    rc, q, rid = role_request("athena-x", SUB, "serve", "--app", _bad)
    serve_pass()
    check(f"0790: --app {_bad}: отказ ({_why})", state(q, rid) == "failed"
          and _why in (O.load_result(q, rid) or {}).get("why", ""), O.load_result(q, rid))
rc, _, _ = role_request("athena-x", SUB, "serve", "--app", "../x")
check("0790: --app ../x: код 2", rc == 2)
rc, _, _ = role_request("athena-x", SUB, "serve", "--app", "/etc")
check("0790: --app абсолютный путь: код 2", rc == 2)
_sw = os.path.realpath(tempfile.mkdtemp(prefix="sw-"))
_sx = os.path.realpath(tempfile.mkdtemp(prefix="sx-"))
os.makedirs(os.path.join(_sw, "site"))
json.dump({"scripts": {"dev": "x"}}, open(os.path.join(_sw, "site", "package.json"), "w"))
json.dump({"scripts": {"dev": "x"}}, open(os.path.join(_sx, "package.json"), "w"))
os.symlink(_sx, os.path.join(_sw, "ext"))            # папка-ссылка наружу, с package.json
os.makedirs(os.path.join(_sw, "pk"))
os.symlink(os.path.join(_sx, "package.json"), os.path.join(_sw, "pk", "package.json"))   # package.json-ссылка наружу
check("0790: serve_command(site) — папка site", O.serve_command(_sw, None, "site")[2] == os.path.join(_sw, "site"))
check("0790: serve_command(абсолютный) — отказ", O.serve_command(_sw, None, "/etc")[0] is None)
check("0790: serve_command(..) — отказ", O.serve_command(_sw, None, "../x")[0] is None
      and O.serve_command(_sw, None, "site/../../x")[0] is None)
check("0790: serve_command(ссылка-папка наружу) — отказ", O.serve_command(_sw, None, "ext")[0] is None)
check("0790: serve_command(package.json-ссылка наружу) — отказ", O.serve_command(_sw, None, "pk")[0] is None)

# разбор workspaces и выбор приложения — без запуска
_ws = os.path.realpath(tempfile.mkdtemp(prefix="ws-"))
for rel, pj in {"package.json": {"name": "r"}, "apps/a/package.json": {"name": "a", "scripts": {"dev": "x"}},
                "packages/b/package.json": {"name": "b"}, "other/c/package.json": {"name": "c", "scripts": {"dev": "x"}}}.items():
    os.makedirs(os.path.dirname(os.path.join(_ws, rel)), exist_ok=True)
    json.dump(pj, open(os.path.join(_ws, rel), "w"))
with open(os.path.join(_ws, "pnpm-workspace.yaml"), "w") as fh:
    fh.write("packages:\n  - 'apps/*'\n  - \"packages/*\"   # библиотеки\n  - '!apps/skip'\ncatalog:\n  x: 1\n")
check("workspaces: pnpm-workspace.yaml — шаблоны в кавычках, комментарий, исключение пропущено",
      sorted(O.workspaces(_ws, {"name": "r"})) == ["apps/a", "packages/b"], O.workspaces(_ws, {"name": "r"}))
_sc = O.serve_command(_ws)
check("одно приложение со скриптом — берётся само", _sc[2] == os.path.join(_ws, "apps", "a"), _sc)
json.dump({"name": "r", "workspaces": {"packages": ["other/*", "../up"]}}, open(os.path.join(_ws, "package.json"), "w"))
check("workspaces: {packages} в package.json, «..» не выходит из папки",
      sorted(O.workspaces(_ws, O._pkg(_ws))) == ["apps/a", "other/c", "packages/b"])
check("два приложения со скриптом без --app — отказ", O.serve_command(_ws)[0] is None)

# файл ключей: разбор, ссылка не читается, профиль закрывает папку ключей
check("parse_env: export, кавычки, комментарии, служебные имена",
      O.parse_env("export A='1 # x'\nB=2 # c\n#C=3\nbad line\nD=\"q\"\nHOME=/x\nLD_PRELOAD=y\n1X=2\n")
      == ({"A": "1 # x", "B": "2", "D": "q"}, ["HOME", "LD_PRELOAD"]))
_envd = os.path.join(STATE, "outside", "env")
os.symlink(os.path.join(_ROOT, "secret.json"), os.path.join(_envd, "latark__app.env"))
check("файл ключей — ссылка: не читается", O.dev_keys("latark/app")[1] == [])
os.remove(os.path.join(_envd, "latark__app.env"))
prof = O.profile_text([os.path.realpath(APP)])
check("профиль: папка dev-ключей закрыта на чтение",
      f'(subpath "{os.path.realpath(_envd)}")' in prof.split("(deny file-write*\n")[0])
_sb = os.path.join(_ROOT, "envprobe.sb")
with open(_sb, "w") as fh:
    fh.write(prof)
try:
    _r = subprocess.run(["/usr/bin/sandbox-exec", "-f", _sb, "/bin/cat", os.path.join(_envd, "latark__mono.env")],
                        capture_output=True, text=True)
    _ok = subprocess.run(["/usr/bin/sandbox-exec", "-f", _sb, "/bin/cat", os.path.join(MONO, "package.json")],
                         capture_output=True, text=True)
    if _ok.returncode != 0 and "sandbox_apply" in _ok.stderr:
        print("ПРОПУЩЕНО (живая проба ключей): sandbox-exec не запускается:", _ok.stderr.strip())
    else:
        check("профиль вживую: файл dev-ключей не читается, файл проекта читается",
              _r.returncode != 0 and "dev-secret" not in _r.stdout and _ok.returncode == 0, (_r.returncode, _ok.stderr))
except OSError as e:
    print("ПРОПУЩЕНО (живая проба ключей):", e)

# заявки делятся по проходам: каждый берёт только свои
q, rid_sv = new_request("athena-x", APP, "serve")
q, rid_ts = new_request("athena-x", APP, "test")
got = O.requests(("serve",))
check("requests: проход серверов берёт serve, test остаётся лежать", [x[4] for x in got] == [rid_sv]
      and os.path.isfile(os.path.join(q, rid_ts + ".req.json")) and not os.path.exists(os.path.join(q, rid_sv + ".req.json")))
got = O.requests(("test",))
check("requests: проход тестов берёт test", [x[4] for x in got] == [rid_ts])

# metis-0706: не плодить дубли заявок test; тест в очереди снимается stop; --wait ждёт уже поданную заявку
def dup_say(window, cwd, *args):
    os.environ["PANTHEON_TMP"] = os.path.join(CACHE, window, "tmp")
    old, buf = os.getcwd(), io.StringIO()
    os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(buf):
            rc = O.main(list(args))
    finally:
        os.chdir(old)
        os.environ.pop("PANTHEON_TMP")
    return rc, buf.getvalue()


def req_ids(q):
    return sorted(n[:-9] for n in os.listdir(q) if n.endswith(".req.json")) if os.path.isdir(q) else []


q, rid_a = new_request("athena-x", APP, "test")
head_now = O.head_state(APP)[0]
check("дубль: в заявке test записан head", (O.load_result(q, rid_a) or {}).get("sha") == head_now, O.load_result(q, rid_a))
rc, out = dup_say("athena-x", APP, "test")
check("дубль (а): тот же head и папка, прежняя в очереди — новой заявки нет, ID прежней в выводе, код 0",
      rc == 0 and req_ids(q) == [rid_a] and rid_a in out, (rc, out, req_ids(q)))
rc, out = dup_say("athena-x", APP, "test")
check("дубль (а): и третья заявка не плодит", rc == 0 and req_ids(q) == [rid_a], (rc, req_ids(q)))
rc, out = dup_say("athena-x", APP, "test", "--script", "lint")
ids = req_ids(q)
check("дубль (а): другой --script — отдельная заявка", rc == 0 and len(ids) == 2 and rid_a in ids, (rc, out, ids))
for i in ids:
    if i != rid_a:
        os.unlink(os.path.join(q, i + ".req.json"))
        O.save_result(q, i, {"state": "failed", "kind": "test", "why": "проба"})
# заявка взята проходом и идёт (running, итог свежий) — тоже живая
os.unlink(os.path.join(q, rid_a + ".req.json"))
O.save_result(q, rid_a, {"state": "running", "kind": "test", "sha": head_now, "cmd": "x", "dir": APP})
rc, out = dup_say("athena-x", APP, "test")
check("дубль (а): прежний тест идёт (running) — новой заявки нет", rc == 0 and req_ids(q) == [] and rid_a in out,
      (rc, out, req_ids(q)))
rc, out = say("athena-x", "stop", rid_a, "--wait", "0")
check("stop идущего теста — по-прежнему отказ «это тесты», код 1", rc == 1 and "это тесты" in out, (rc, out))
# running старше срока теста — висяк, не блокирует
O.save_result(q, rid_a, {"state": "running", "kind": "test", "sha": head_now, "cmd": "x", "dir": APP,
                         "updated": "2020-01-01 00:00"})
rc, out = dup_say("athena-x", APP, "test")
ids = req_ids(q)
check("дубль (а): висящий running старше срока не мешает — заявка новая", rc == 0 and len(ids) == 1 and ids[0] != rid_a,
      (rc, out, ids))
rid_b = ids[0]
# другой head — отдельная заявка (регрессия)
git(APP, "commit", "--allow-empty", "-q", "-m", "m0706")
rc, out = dup_say("athena-x", APP, "test")
ids = req_ids(q)
check("регрессия: другой head — вторая заявка, обе в очереди", rc == 0 and len(ids) == 2 and rid_b in ids, (rc, out, ids))
rid_c = next(i for i in ids if i != rid_b)
check("регрессия: у второй свой head", (O.load_result(q, rid_c) or {}).get("sha") != head_now, O.load_result(q, rid_c))
# (б) stop снимает тест, пока он в очереди
rc, out = say("athena-x", "stop", rid_c, "--wait", "0")
res = O.load_result(q, rid_c) or {}
check("stop (б): тест в очереди снят — код 0, заявки нет, итог stopped «отменена»",
      rc == 0 and rid_c not in req_ids(q) and res.get("state") == "stopped" and "отменена" in res.get("why", ""),
      (rc, out, res))
run_pass()
check("stop (б): снятый тест проход не запускает, остальная очередь идёт",
      (O.load_result(q, rid_c) or {}).get("state") == "stopped"
      and (O.load_result(q, rid_b) or {}).get("state") in ("done", "failed"), (O.load_result(q, rid_c), O.load_result(q, rid_b)))
rc, out = say("athena-x", "stop", rid_c, "--wait", "0")
check("stop (б): повтор — «уже stopped», код 0", rc == 0 and "stopped" in out, (rc, out))
git(APP, "reset", "-q", "--hard", head_now)
# (в) --wait с уже поданной заявкой ждёт её итог
q, rid_w = new_request("athena-x", APP, "test")
threading.Timer(1.0, run_pass).start()
rc, out = dup_say("athena-x", APP, "test", "--wait", "30")
res = O.load_result(q, rid_w) or {}
check("--wait (в): ждёт итог прежней заявки, новой нет, код — её кода",
      res.get("state") in O.FINAL and req_ids(q) == [] and rc == O.result_code(res) and rid_w in out, (rc, out, res))

# «стоп» без сервера и заявки: старый убирается, молодой ждёт
_qa = os.path.join(CACHE, "athena-x", "outside")
_orph, _young = os.path.join(_qa, "20261101-000000-0a0a0a.stop"), os.path.join(_qa, "20261101-000000-0b0b0b.stop")
open(_orph, "w").close()
open(_young, "w").close()
os.utime(_orph, (time.time() - 120,) * 2)
serve_pass()
check("брошенный «стоп» старше минуты убран, молодой остался", not os.path.exists(_orph) and os.path.exists(_young))
os.remove(_young)

check("check_request: коммит и приложение по образцу",
      O.check_request({"v": 1, "id": "r", "kind": "serve", "dir": "/x", "sha": "abc1234", "app": "@m/web"}, "r") is None
      and O.check_request({"v": 1, "id": "r", "kind": "serve", "dir": "/x", "sha": "abc"}, "r")
      and O.check_request({"v": 1, "id": "r", "kind": "serve", "dir": "/x", "app": "a b"}, "r"))

# --- безопасность копии (metis-0614, находки фоновой проверки): .git-файл роли, конфиг клона, ключи только по origin --
# Роль пишет свою папку целиком, в том числе .git-файл worktree, но не .git/config клона (окну закрыт ~/**/.git/config).
kill_all_servers()
_envd = os.path.join(STATE, "outside", "env")
with open(os.path.join(_envd, "latark__other.env"), "w") as fh:
    fh.write("OTHER_SECRET=other-secret\n")
with open(os.path.join(_envd, "latark__app.env"), "w") as fh:
    fh.write("APP_KEY=app-key\n")
EVIL = os.path.join(_ROOT, "evil-repo")   # вне реестра; origin — чужой репозиторий с ключами
os.makedirs(EVIL)
git(EVIL, "init", "-q", "-b", "main")
git(EVIL, "remote", "add", "origin", "https://github.com/latark/other.git")
commit(EVIL, {"package.json": json.dumps(PKG), ".gitignore": "node_modules/\n"}, "e1")
_wtd = os.path.join(APP, ".claude", "worktrees")
os.makedirs(_wtd, exist_ok=True)


def refused(window, folder, needle, label):
    """Заявка serve из folder: failed с needle в причине, ничего не запущено, чужих ключей нигде нет."""
    pre = len(calls())
    q, rid = new_request(window, folder, "serve", "--minutes", "5")
    serve_pass()
    res = O.load_result(q, rid) or {}
    check(label, res.get("state") == "failed" and needle in (res.get("why") or "") and len(calls()) == pre
          and not os.path.isdir(work_of(rid)) and rid not in O.servers(), res)
    return res


# 1. .git-файл в папке направления ведёт в чужой gitdir (remote — другой репозиторий): отказ, ключей нет
FAKE1 = os.path.join(_wtd, "fake1")
os.makedirs(FAKE1)
with open(os.path.join(FAKE1, ".git"), "w") as fh:
    fh.write(f"gitdir: {os.path.join(EVIL, '.git')}\n")
refused("athena-x", FAKE1, "не worktree клона", ".git-файл ведёт в чужой gitdir: отказ, ключей и копии нет")
# 2. настоящий worktree чужого клона, положенный в папку направления: клон вне реестра — отказ
FAKE2 = os.path.join(_wtd, "fake2")
git(EVIL, "worktree", "add", "-q", "--detach", FAKE2)
refused("athena-x", FAKE2, "не из папок направления", "worktree клона вне реестра в папке направления: отказ")
# 3. gitdir, который роль завела в своей папке (bare-клон не по имени .git, конфиг пишет роль): отказ по устройству
EVILB = os.path.join(APP, ".claude", "evilbare")
subprocess.run(["git", "clone", "-q", "--bare", EVIL, EVILB], check=True, capture_output=True)
FAKE3 = os.path.join(_wtd, "fake3")
subprocess.run(["git", f"--git-dir={EVILB}", "worktree", "add", "-q", "--detach", FAKE3, "main"], check=True,
               capture_output=True)
refused("athena-x", FAKE3, "не worktree клона", "gitdir роли в папке направления (не <клон>/.git): отказ")
check("trusted_clone: worktree клона принят, подделки — нет",
      O.trusted_clone(os.path.realpath(FAKE2))[0] == os.path.realpath(EVIL)
      and O.trusted_clone(os.path.realpath(FAKE1))[0] is None and O.trusted_clone(os.path.realpath(FAKE3))[0] is None
      and O.trusted_clone(os.path.realpath(APP))[0] == os.path.realpath(APP))

# 4. настоящий worktree клона реестра: сервер поднят, ключи — только по origin клона, лишний remote ничего не даёт
git(APP, "remote", "add", "upstream", "https://github.com/latark/other.git")
WT = os.path.join(_wtd, "wt-ok")
git(APP, "worktree", "add", "-q", "--detach", WT)
FAKE4 = os.path.join(_wtd, "fake4")   # .git-файл на gitdir чужого worktree: обратная ссылка не сходится
os.makedirs(FAKE4)
shutil.copy(os.path.join(WT, ".git"), os.path.join(FAKE4, ".git"))
check("trusted_clone: .git-файл на gitdir другого worktree — отказ (обратная ссылка)",
      O.trusted_clone(os.path.realpath(FAKE4))[0] is None and O.trusted_clone(os.path.realpath(WT))[0] == os.path.realpath(APP))
shutil.rmtree(FAKE4)
_pre = len(calls())
q, rid = new_request("athena-x", WT, "serve", "--minutes", "5")
serve_pass()
res = O.load_result(q, rid) or {}
_c = calls()[_pre:]
_env = _c[-1]["env"] if _c else {}
check("worktree клона реестра: сервер поднят из своей копии", res.get("state") == "serving"
      and res.get("dir") == work_of(rid), res)
check("ключи — только по origin клона: лишний remote чужого репозитория ключей не даёт",
      res.get("keys") == ["APP_KEY"] and _env.get("APP_KEY") == "app-key" and "OTHER_SECRET" not in _env, res.get("keys"))
check("origin_id: только origin", O.origin_id(os.path.realpath(os.path.join(APP, ".git"))) == "latark/app")
kill_all_servers()
git(APP, "remote", "remove", "upstream")
# проверка и использование — одно: после resolve_dir git по папке идёт через проверенный gitdir, а не через .git-файл
_r, _ = O.resolve_dir(WT, "athena-x")
_saved = open(os.path.join(WT, ".git")).read()
with open(os.path.join(WT, ".git"), "w") as fh:
    fh.write(f"gitdir: {os.path.join(EVIL, '.git')}\n")
check("подмена .git-файла после проверки: git заявки видит клон реестра, а не подложенный",
      isinstance(_r, O.Repo) and O.remotes(_r) == ["latark/app"] and O.head_state(_r)[0] == git(APP, "rev-parse", "HEAD")
      and O.remotes(os.path.realpath(WT)) == ["latark/other"], (O.remotes(_r), O.remotes(os.path.realpath(WT))))
with open(os.path.join(WT, ".git"), "w") as fh:
    fh.write(_saved)
git(APP, "worktree", "remove", "--force", WT)
# common со своим commondir, config — ссылка: отказ (git взял бы конфиг не из проверенного файла)
_cd = os.path.join(APP, ".git", "commondir")
with open(_cd, "w") as fh:
    fh.write(os.path.join(EVIL, ".git") + "\n")
check("у .git клона свой commondir — отказ", O.trusted_clone(os.path.realpath(APP))[0] is None
      and "commondir" in (O.trusted_clone(os.path.realpath(APP))[1] or ""))
os.remove(_cd)
_cfg = os.path.join(APP, ".git", "config")
shutil.copy(_cfg, _cfg + ".real")
os.remove(_cfg)
os.symlink(_cfg + ".real", _cfg)
check("config клона — ссылка: отказ", O.trusted_clone(os.path.realpath(APP))[0] is None
      and "обычный файл" in (O.trusted_clone(os.path.realpath(APP))[1] or ""))
os.remove(_cfg)
os.rename(_cfg + ".real", _cfg)
check("после уборки клон снова принят", O.trusted_clone(os.path.realpath(APP))[0] == os.path.realpath(APP))

# 5. конфиг клона, исполняющий команду вне песочницы: core.fsmonitor с командой — отказ; head_state его не зовёт
_mark = os.path.join(_ROOT, "fsmonitor-ran")
_hook = os.path.join(_ROOT, "fsmonitor-hook")
with open(_hook, "w") as fh:
    fh.write(f"#!/bin/sh\ntouch {_mark}\nexit 1\n")
os.chmod(_hook, 0o755)
git(APP, "config", "core.fsmonitor", _hook)
refused("athena-x", APP, "core.fsmonitor", "core.fsmonitor с командой в конфиге клона: отказ, копии нет")
O.head_state(os.path.realpath(APP))
O.toplevel(os.path.realpath(APP))
check("git прохода не зовёт core.fsmonitor (GIT_SAFE)", not os.path.exists(_mark))
subprocess.run(["git", "-C", APP, "status", "--porcelain"], capture_output=True)
check("проба честная: голый git status монитор зовёт", os.path.exists(_mark))
git(APP, "config", "core.fsmonitor", "true")
check("core.fsmonitor=true (встроенный монитор git) — не отказ", O.unsafe_config(os.path.realpath(os.path.join(APP, ".git"))) is None)
git(APP, "config", "--unset", "core.fsmonitor")
_gd = os.path.realpath(os.path.join(APP, ".git"))
for _k, _v in (("filter.x.smudge", "touch /tmp/x"), ("include.path", "/tmp/x.cfg"),
               ("includeIf.gitdir:/.path", "/tmp/x.cfg"), ("extensions.worktreeConfig", "true")):
    git(APP, "config", _k, _v)
    check(f"конфиг клона с {_k}: отказ", _k.lower().split(".")[0] in (O.unsafe_config(_gd) or "").lower())
    git(APP, "config", "--unset", _k)
check("чистый конфиг клона — не отказ", O.unsafe_config(_gd) is None)
# ключи-команды (*.command и родня): вне песочницы любая из них — чужой код у прохода
for _k in ("core.sshCommand", "diff.x.command", "diff.x.textconv", "merge.x.driver", "credential.helper",
           "gpg.program", "core.pager", "pager.status", "alias.st", "core.alternateRefsCommand"):
    git(APP, "config", _k, "touch /tmp/x")
    check(f"конфиг клона с {_k}: отказ", _k.lower() in (O.unsafe_config(_gd) or "").lower(), O.unsafe_config(_gd))
    git(APP, "config", "--unset", _k)
git(APP, "config", "core.hooksPath", ".husky")   # -c core.hooksPath=/dev/null его перекрывает — не повод отказывать
check("core.hooksPath и обычные ключи — не отказ", O.unsafe_config(_gd) is None, O.unsafe_config(_gd))
git(APP, "config", "--unset", "core.hooksPath")

# 6. подмодуль: его конфиг (<клон>/.git/modules/<имя>/config) окну роли открыт, git status прохода в него не заходит
SUPER, SUBR = os.path.join(_ROOT, "super"), os.path.join(_ROOT, "subrepo")
os.makedirs(SUPER)
os.makedirs(SUBR)
git(SUBR, "init", "-q", "-b", "main")
commit(SUBR, {"f.txt": "data\n", ".gitattributes": "f.txt filter=evil\n"}, "s1")
git(SUPER, "init", "-q", "-b", "main")
commit(SUPER, {"a.txt": "a\n"}, "p1")
subprocess.run(["git", "-C", SUPER, "-c", "protocol.file.allow=always", "submodule", "add", "-q", SUBR, "sub"],
               check=True, capture_output=True)
git(SUPER, "commit", "-q", "-m", "sub")
_smark = os.path.join(_ROOT, "submodule-filter-ran")
subprocess.run(["git", "config", "--file", os.path.join(SUPER, ".git", "modules", "sub", "config"),
                "filter.evil.clean", f"touch {_smark}; cat"], check=True)
_f = os.path.join(SUPER, "sub", "f.txt")
os.utime(_f, (time.time() + 100,) * 2)   # индекс подмодуля устарел: status сверит содержимое через clean-фильтр
_hs = O.head_state(os.path.realpath(SUPER))
check("head_state не заходит в подмодуль: clean-фильтр из его конфига не исполнен", not os.path.exists(_smark)
      and _hs[1] is True, _hs)
subprocess.run(["git", "-C", SUPER, "status", "--porcelain"], capture_output=True)
check("проба честная: голый git status фильтр подмодуля исполняет", os.path.exists(_smark))

for _p in (FAKE1, EVILB):
    shutil.rmtree(_p, ignore_errors=True)
for _p in (FAKE2, FAKE3):
    shutil.rmtree(_p, ignore_errors=True)
git(APP, "worktree", "prune")
shutil.rmtree(os.path.join(APP, ".claude"), ignore_errors=True)
for _n in ("latark__other.env", "latark__app.env"):
    os.remove(os.path.join(_envd, _n))

# --- сторож живёт своим проходом: «стоп» ≤10 с, пока проход тестов занят (metis-0606, 0614) -------------------------
DEVTREE = DEVTREE_PIDS


def devtree_pids():
    try:
        with open(DEVTREE) as fh:
            return [int(x) for x in fh.read().split()]
    except (OSError, ValueError):
        return []


def _kill_devtree():
    for p in devtree_pids():
        with contextlib.suppress(OSError):
            os.kill(p, signal.SIGKILL)


_atexit.register(_kill_devtree)   # мутант без гашения ушедших групп не оставляет задачу висеть на порту
_atexit.register(kill_all_servers)

q, rid_s = new_request("athena-x", APP, "serve", "--script", "devtree")
_, rid_t = new_request("athena-x", APP, "test", "--script", "hold")
O.RESIDENT_MAX = 90   # мутант, при котором сервер не гаснет, не держит тест час
th_t = threading.Thread(target=run_pass, daemon=True)
th_s = threading.Thread(target=O.cmd_run_serve, daemon=True)
th_t.start()
th_s.start()
up = wait_for(lambda: state(q, rid_s) == "serving" and state(q, rid_t) == "running", 40)
res = O.load_result(q, rid_s) or {}
port, pids = res.get("port") or 0, devtree_pids()
srvpid = int((O.servers().get(rid_s) or {}).get("pid") or 0)
check("сторож: сервер («turbo» → задача в своей группе) поднят, тест идёт, проход серверов живёт",
      up and port_open(port) and len(pids) == 2 and srvpid and th_t.is_alive() and th_s.is_alive(), (res, pids, srvpid))
check("второй проход серверов при живом сторож — сразу выходит (замок)", serve_pass() == 0 and th_s.is_alive())
# сирота: процесс с текущей папкой в копии, не потомок сервера и не в его группе (next dev, ушедший к launchd)
def _gone(proc, timeout=5):
    try:
        return proc.wait(timeout=timeout) is not None
    except subprocess.TimeoutExpired:
        return False


_orphan = subprocess.Popen([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                            "time.sleep(120)"], cwd=work_of(rid_s) if os.path.isdir(work_of(rid_s)) else _ROOT,
                           start_new_session=True)   # копии нет, если сервер не поднялся: FAIL выше, а не обрыв файла (metis-0731)
TEST_PROCS.append(_orphan)
t0 = time.monotonic()
rc, out = say("metis-y", "stop", rid_s)
dt = time.monotonic() - t0
check("стоп из другого окна при занятом проходе тестов: stopped за ≤10 с, `stop` дождался, код 0, тест идёт",
      rc == 0 and "stopped" in out and dt <= 10 and th_t.is_alive() and state(q, rid_t) == "running",
      (rc, out, round(dt, 1)))
check("стоп: порт свободен, погашены сервер, «turbo» и задача в своей группе, копия снята",
      not port_open(port) and not any(pid_alive(p) for p in pids + [srvpid])
      and rid_s not in O.servers() and not os.path.exists(work_of(rid_s)),
      [(p, pid_alive(p, 0)) for p in pids + [srvpid]])
# сирота по папке копии ищется через /usr/sbin/lsof — путь macOS
check_mac("стоп: сирота по папке копии (lsof) погашена", MAC and _gone(_orphan), _orphan.poll())
th_s.join(15)
check("сторож без серверов и заявок выходит сам", not th_s.is_alive())
open(HOLD_RELEASE, "w").close()
th_t.join(90)
res = O.load_result(q, rid_t) or {}
check("тест после стопа сервера дошёл до конца, код 0", res.get("state") == "done" and res.get("code") == 0, res)
_kill_devtree()
with contextlib.suppress(OSError):
    _orphan.kill()

# «погаси прежний и подними новый»: стоп прежнего во время установки нового — оба по порядку
q, rid_a = role_request("athena-x", APP, "serve")[1:]
serve_pass()
check("прежний сервер поднят, в servers.json — время старта его процесса",
      state(q, rid_a) == "serving" and O.servers()[rid_a].get("started") == O.started(O.servers()[rid_a]["pid"])
      and O.servers()[rid_a].get("started"), O.servers().get(rid_a))
q, rid_b = role_request("athena-x", APP, "serve")[1:]
say("athena-x", "stop", rid_a, "--wait", "0")
serve_pass()
_stops = [x.get("why") for x in events(rid_a, "stop")]
check("стоп прежнего и новый в одном круге: прежний погашен один раз, новый поднят, в servers.json — только новый",
      state(q, rid_a) == "stopped" and state(q, rid_b) == "serving" and set(O.servers()) == {rid_b}
      and _stops == ["заявка «стоп»"], (state(q, rid_a), state(q, rid_b), O.servers(), _stops))
kill_all_servers()

# «стоп» своей заявки во время установки зависимостей — прерывает её
O.SWEEP_EVERY = 0.2
_real_prepare = O.prepare


def _slow_prepare(d, rid, heavy=True, tick=None, timeout=O.TEST_TIMEOUT):
    p = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
    TEST_PROCS.append(p)
    say("athena-x", "stop", rid, "--wait", "0")
    try:
        return O.wait_proc(p, 30, tick)
    finally:
        _slow_prepare.pid = p.pid


O.prepare = _slow_prepare
try:
    q, rid = role_request("athena-x", APP, "serve")[1:]
    t0 = time.monotonic()
    serve_pass()
    dt = time.monotonic() - t0
finally:
    O.prepare = _real_prepare
    O.SWEEP_EVERY = 2
res = O.load_result(q, rid) or {}
check("стоп во время установки: установка прервана, stopped без запуска сервера, копия снята",
      res.get("state") == "stopped" and dt < 15 and not pid_alive(_slow_prepare.pid, 0) and not O.servers()
      and not os.path.exists(work_of(rid)), (res, round(dt, 1)))

# metis-0731: fork/exec под нагрузкой даёт временный отказ — установка зависимостей повторяется, а не падает «кодом -1»
import errno as _errno
_pd = tempfile.mkdtemp(prefix="prep-", dir=_ROOT)
with open(os.path.join(_pd, "package.json"), "w") as fh:
    fh.write('{"name": "p"}')
_real_popen, _real_wrap, _real_sleep = subprocess.Popen, O.wrap, time.sleep


def _prep_with(errnos):
    """prepare() с Popen, отказывающим по очереди errnos; → (код, число запусков, журнал)."""
    calls = []

    def popen(argv, *a, **kw):
        calls.append(argv)
        if len(calls) <= len(errnos):
            raise OSError(errnos[len(calls) - 1], os.strerror(errnos[len(calls) - 1]))
        return _real_popen([sys.executable, "-c", "pass"], **{k: v for k, v in kw.items() if k != "env"})

    rid_p = "20261103-000000-" + os.urandom(3).hex()
    subprocess.Popen, O.wrap, time.sleep = popen, (lambda argv, *a, **kw: argv), (lambda t: None)
    try:
        code = O.prepare(_pd, rid_p)
    finally:
        subprocess.Popen, O.wrap, time.sleep = _real_popen, _real_wrap, _real_sleep
    with open(O.root("runs", rid_p + ".log")) as fh:
        return code, len(calls), fh.read()


_code, _n, _log = _prep_with([_errno.EAGAIN, _errno.ETXTBSY])
check("установка: временный отказ запуска (EAGAIN, ETXTBSY) — повтор, код 0", _code == 0 and _n == 3, (_code, _n, _log))
_code, _n, _log = _prep_with([_errno.EAGAIN] * 3)
check("установка: отказ на каждой попытке — код -1 после 3 запусков, причина в журнале",
      _code == -1 and _n == 3 and "установка не запустилась: BlockingIOError" in _log, (_code, _n, _log))
_code, _n, _log = _prep_with([_errno.ENOENT])
check("установка: постоянный отказ (ENOENT) — без повтора, код -1, причина в журнале",
      _code == -1 and _n == 1 and "установка не запустилась: FileNotFoundError" in _log, (_code, _n, _log))

# --- номер процесса сервера занял чужой (metis-0606, Д-2 argus): не гасить ни его, ни его детей в своих группах ----
_spawn = [sys.executable, "-c", "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', "
          "'import time; time.sleep(60)'], start_new_session=True); time.sleep(60)"]
alien = subprocess.Popen(_spawn)                                  # не глава группы: группа — наша, теста
TEST_PROCS.append(alien)
time.sleep(0.8)
_ps = subprocess.run([O.PS, "-axo", "pid=,ppid="], capture_output=True, text=True).stdout.split()
_kid = [int(a) for a, b in zip(_ps[::2], _ps[1::2]) if int(b) == alien.pid]   # ребёнок в своей группе
O.kill_group(alien.pid)
check("kill_group по pid, который не глава группы: ни он, ни его ребёнок в своей группе не гаснут",
      alien.poll() is None and _kid and all(pid_alive(p, 0) for p in _kid), (alien.poll(), _kid))
O.save_servers({"20261030-000000-a1a1a1": {"pid": alien.pid, "port": 0, "until": 0, "qdir": None}})
O.sweep()
check("sweep: запись с чужим не-главой снята, процессы живы", not O.servers() and alien.poll() is None
      and all(pid_alive(p, 0) for p in _kid), O.servers())
for _p in _kid:
    with contextlib.suppress(OSError):
        os.kill(_p, 9)
alien.kill()
alien.wait()

# --- ps не запустить (sandbox-exec): strays и kill_group идут по libproc (metis-0786) ---
if not MAC:
    print("пропущено: нужен macOS — strays и kill_group без ps (libproc)")
else:
    _ps_keep = O.PS
    O.PS = os.path.join(_ROOT, "нет-ps-0786")
    _par = subprocess.Popen([sys.executable, "-c", "import subprocess, sys, time; subprocess.Popen([sys.executable, "
                            "'-c', 'import time; time.sleep(60)'], start_new_session=True); time.sleep(60)"],
                            start_new_session=True)
    TEST_PROCS.append(_par)
    _kid2 = []
    for _ in range(40):
        time.sleep(0.1)
        _kid2 = [p for p, (pp, g, _r) in O.ps_table().items() if pp == _par.pid]
        if _kid2:
            break
    _st = O.strays(_par.pid)
    _me_row = O.ps_table().get(os.getpid(), (0, 0, 0))
    check("без ps: ps_table видит процессы с pid, ppid, pgid, rss", _me_row[:2] == (os.getppid(), os.getpgrp())
          and _me_row[2] > 0, _me_row)
    check("без ps: strays находит потомка в своей группе", bool(_kid2) and [p for p, _g in _st] == _kid2, (_st, _kid2))
    O.kill_group(_par.pid)
    time.sleep(0.3)
    check("без ps: kill_group гасит и главу, и потомка в своей группе",
          _par.poll() is not None and _kid2 and not any(pid_alive(p, 0) for p in _kid2), (_par.poll(), _kid2))
    O.PS = _ps_keep

leader = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)   # глава своей группы, как сервер
TEST_PROCS.append(leader)
time.sleep(0.3)
O.save_servers({"20261030-000000-b2b2b2": {"pid": leader.pid, "started": "Thu Jan  1 00:00:00 1970", "port": 0,
                                           "until": time.time() + 3600, "qdir": None}})
O.sweep()
res = P.read_json(os.path.join(STATE, "outside", "runs", "20261030-000000-b2b2b2.json"), {})
check("sweep: время старта не то — процесс не гасится, запись снята, причина «процесс завершился»",
      leader.poll() is None and not O.servers() and res.get("why") == "процесс завершился", (leader.poll(), res))
_tz = os.environ.get("TZ")
_seen = set()
for _z in ("Asia/Novosibirsk", "America/New_York", "UTC"):
    os.environ["TZ"] = _z
    time.tzset()
    _seen.add(O.started(leader.pid))
if _tz is None:
    os.environ.pop("TZ")
else:
    os.environ["TZ"] = _tz
time.tzset()
_env_seen = []
_real_run = O.subprocess.run


def _spy_run(*a, **kw):
    _env_seen.append(kw.get("env"))
    return _real_run(*a, **kw)


O.subprocess.run = _spy_run
try:
    O.started(leader.pid)
finally:
    O.subprocess.run = _real_run
check("время старта — в UTC и не зависит от пояса прохода: ps зовётся с чистым env и TZ=UTC (metis-0609)",
      len(_env_seen) == 1 and _env_seen[0] and _env_seen[0].get("TZ") == "UTC" and _env_seen[0].get("LC_ALL") == "C"
      and len(_seen) == 1, (_env_seen, _seen))
O.save_servers({"20261030-000000-c3c3c3": {"pid": leader.pid, "started": O.started(leader.pid), "port": 0,
                                           "until": 0, "qdir": None}})
O.sweep()
check("sweep: время старта совпало — срок вышел, процесс погашен", leader.wait(timeout=10) is not None
      and not O.servers())

# reap — только внутри папки копий: чужая папка не трогается
_keep = subprocess.Popen(["/bin/sleep", "30"], cwd=os.path.realpath(APP), start_new_session=True)
TEST_PROCS.append(_keep)
check("reap вне папки копий ничего не гасит", O.reap(os.path.realpath(APP)) == 0 and pid_alive(_keep.pid, 0))
_keep.kill()
_keep.wait()

# --- время заявки в будущем (metis-0604): заявка со временем позже now+60 с отклонена ------------------------------
_fmt = "%Y-%m-%dT%H:%M:%S%z"
_ok = {"v": 1, "id": "r1", "kind": "serve", "dir": "/x", "wait": 5}
check("check_request: время сейчас — принята",
      O.check_request({**_ok, "time": time.strftime("%Y-%m-%d %H:%M")}, "r1") is None)
check("check_request: время на час вперёд — отклонена (формат P.stamp)",
      O.check_request({**_ok, "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + 3600))}, "r1"))
check("check_request: время на час вперёд — отклонена (формат с секундами и поясом)",
      O.check_request({**_ok, "time": time.strftime(_fmt, time.localtime(time.time() + 3600))}, "r1"))
_rc, _q, _rid = role_request("athena-x", APP, "serve")
_t = json.load(open(os.path.join(_q, _rid + ".req.json")))["time"]
os.remove(os.path.join(_q, _rid + ".req.json"))
check("заявка от CLI несёт время с секундами и поясом",
      "T" in _t and abs(O._epoch({"time": _t}) - time.time()) < 5, _t)
check("_epoch: минутное время — конец минуты (+59 с)",
      O._epoch({"time": "2026-10-30 10:00"}) - O._epoch({"time": "2026-10-30 09:59"}) == 60
      and O._epoch({"time": "2026-10-30 10:00"}) - __import__("datetime").datetime(2026, 10, 30, 10, 0).timestamp() == 59)
check("_epoch: оба формата разбираются, мусор и пусто — None",
      O._epoch({"time": "2026-10-30 10:00"}) is not None and O._epoch({"time": "2026-10-30T10:00:00+0300"}) is not None
      and O._epoch({"time": "вчера"}) is None and O._epoch({}) is None)

# --- sweep_quiet (metis-0606, Д-1 argus): сбой сторожа посреди запуска сервера не роняет проход, в журнал — один раз --
O._SWEEP_ERR.clear()
_log = os.path.join(STATE, "logs", "outside.jsonl")
_n0 = sum(1 for _ in open(_log))
_real_sweep = O.sweep


def _boom(t=None, stops=None):
    raise ValueError("битый servers.json")


O.sweep = _boom
try:
    O.sweep_quiet()
    O.sweep_quiet()
    _raised = None
except Exception as e:  # noqa: BLE001 — мутант без try: исключение вышло
    _raised = e
finally:
    O.sweep = _real_sweep
_errs = [json.loads(x) for x in list(open(_log))[_n0:]]
_errs = [x for x in _errs if x.get("kind") == "sweep-error"]
check("sweep падает в сторожке: исключение не выходит, в журнале один sweep-error",
      _raised is None and len(_errs) == 1 and "битый servers.json" in _errs[0].get("why", ""), (_raised, _errs))

# --- сбой посреди заявки serve (Д2 argus #232): итог failed, а не preparing до суток; копия снята; круг идёт дальше --
kill_all_servers()
_real_keys, _real_resolve = O.dev_keys, O.resolve_dir


def _keys_boom(*a, **k):
    raise ValueError("битый файл ключей")


O.dev_keys = _keys_boom
try:
    q, rid = new_request("athena-x", APP, "serve")
    _raised = None
    try:
        serve_pass()
    except Exception as e:  # noqa: BLE001 — мутант без except Exception в run_serve
        _raised = e
finally:
    O.dev_keys = _real_keys
res = O.load_result(q, rid) or {}
check("сбой в run_serve (ValueError): итог failed «сбой прохода», копия снята, сервера нет, проход не упал",
      _raised is None and res.get("state") == "failed" and "сбой прохода: ValueError" in res.get("why", "")
      and not os.path.exists(work_of(rid)) and rid not in O.servers(), (_raised, res))


def _resolve_boom(*a, **k):
    raise OSError("папка заявки пропала")


O.resolve_dir = _resolve_boom
try:
    q, rid_a = new_request("athena-x", APP, "serve")
    q, rid_b = new_request("athena-x", APP, "serve")
    _raised = None
    try:
        serve_pass()
    except Exception as e:  # noqa: BLE001 — мутант без try вокруг handle в serve_round
        _raised = e
finally:
    O.resolve_dir = _real_resolve
_ra, _rb = O.load_result(q, rid_a) or {}, O.load_result(q, rid_b) or {}
check("сбой до копии (handle): обе заявки круга — failed «сбой прохода», в журнале serve-error, проход не упал",
      _raised is None and _ra.get("state") == _rb.get("state") == "failed"
      and "сбой прохода: OSError" in _ra.get("why", "") and "сбой прохода" in _rb.get("why", "")
      and any(json.loads(x).get("kind") == "serve-error" for x in open(_log)), (_raised, _ra, _rb))

# --- брошенные копии (Д1 argus #232): копия без сервера старше WORK_ORPHAN_AGE снимается в конце круга -------------
kill_all_servers()
_wr = os.path.join(os.path.realpath(HOME), "Library", "Caches", "pantheon-outside", "work")
_OLD_T = time.time() - O.WORK_ORPHAN_AGE - 60
_dirs = {k: os.path.join(_wr, n) for k, n in (("old", "20261101-000000-0a0a0a"), ("young", "20261101-000001-0b0b0b"),
                                               ("live", "20261101-000002-0c0c0c"), ("odd", "notes"))}
for _k, _d in _dirs.items():
    os.makedirs(os.path.join(_d, "node_modules"), exist_ok=True)
    if _k != "young":
        os.utime(_d, (_OLD_T, _OLD_T))
_sleeper = subprocess.Popen(["/bin/sleep", "60"], cwd=_dirs["old"], start_new_session=True)
TEST_PROCS.append(_sleeper)
_live_leader = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)
TEST_PROCS.append(_live_leader)
O.save_servers({os.path.basename(_dirs["live"]): {"pid": _live_leader.pid, "started": O.started(_live_leader.pid),
                                                  "port": 0, "until": time.time() + 3600, "qdir": None,
                                                  "work": _dirs["live"]}})
serve_pass()
check("брошенная копия старше 10 мин без сервера — снята, в журнале work-orphan",
      not os.path.exists(_dirs["old"])
      and any(json.loads(x).get("kind") == "work-orphan" for x in open(_log)), os.listdir(_wr))
check_mac("брошенная копия: процесс с папкой в ней (lsof) погашен", MAC and _gone(_sleeper), _sleeper.poll())
check("молодая копия, копия живого сервера и папка не по образцу ID — не тронуты",
      all(os.path.isdir(_dirs[k]) for k in ("young", "live", "odd")), os.listdir(_wr))
kill_all_servers()
for _d in _dirs.values():
    shutil.rmtree(_d, ignore_errors=True)

# проход серверов только плановый
os.environ["CLAUDECODE"] = "1"
check("outside run --serve из окна Claude Code: код 2", O.main(["run", "--serve"]) == 2)
os.environ.pop("CLAUDECODE")
check("outside run с лишним аргументом — код 2", O.main(["run", "--bogus"]) == 2)

# --- 4а. уборка итогов в папках заявок (metis-0573): старше суток — удалить ---------------------------------------
q = os.path.join(CACHE, "athena-x", "outside")
fresh = sorted(n for n in os.listdir(q) if n.endswith(".result.json"))
OLD = time.time() - 25 * 3600


def _old_file(d, name, text="{}"):
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w") as fh:
        fh.write(text)
    os.utime(p, (OLD, OLD))
    return p


old_res = _old_file(q, "20261001-010101-aaaaaa.result.json")
old_stop = _old_file(q, "20261001-010101-bbbbbb.stop", "")
day_res = os.path.join(q, "20261001-010101-dddddd.result.json")
_old_file(q, "20261001-010101-dddddd.result.json")
os.utime(day_res, (time.time() - 23 * 3600,) * 2)
notes = _old_file(q, "notes.result.json")
target = _old_file(os.path.join(_ROOT, "elsewhere"), "keep.json", "чужое")
link = os.path.join(q, "20261001-010101-cccccc.result.json")
os.symlink(target, link)
os.utime(link, (OLD, OLD), follow_symlinks=False)
state_res = _old_file(os.path.join(STATE, "outside", "queue"), "20261001-010101-eeeeee.result.json")
live = _old_file(q, "20261001-010101-ffffff.result.json")
O.save_servers({"20261001-010101-ffffff": {"pid": 0, "until": time.time() + 3600, "qdir": q}})
stale = {n for _, n in O._stale()}
check("уборка: файлы живого сервера — не к удалению", "20261001-010101-ffffff.result.json" not in stale
      and "20261001-010101-aaaaaa.result.json" in stale, stale)
O.save_servers({})
check("тик: старые итоги — проход нужен", O.pending())
run_pass()
check("уборка: итог старше суток удалён", not os.path.lexists(old_res))
check("уборка: брошенный «стоп» старше суток удалён", not os.path.lexists(old_stop))
check("уборка: итог в STATE/outside/queue старше суток удалён", not os.path.lexists(state_res))
check("уборка: итог младше суток остался", os.path.isfile(day_res))
check("уборка: свежие итоги остались", fresh and all(os.path.isfile(os.path.join(q, n)) for n in fresh), fresh)
check("уборка: имя не по образцу ID — не трогает", os.path.isfile(notes))
check("уборка: ссылка не трогается, её цель цела", os.path.islink(link) and open(target).read() == "чужое")
check("тик: убрано — прохода нет", not O.pending())
for p in (notes, link, day_res):
    os.remove(p)

# --- 5. guard: команда роли не спрашивает и не считается dev-сервером -------------------------------------------
code = ("import sys, json; sys.path.insert(0, %r); import guard_rules as g; "
        "print(json.dumps([g.check_dev_server('pantheon outside serve --wait 120', {}), "
        "g.check_dev_server('pnpm dev', {}) is not None, g.pantheon_cli('pantheon outside test --wait 300', %r)]))"
        % (GUARD_HOOKS, _ROOT))
r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                   env={"HOME": HOME, "PATH": os.environ["PATH"]})
got = json.loads(r.stdout) if r.returncode == 0 else None
check("guard: `pantheon outside serve` — не dev-сервер (pnpm dev — да)", got and got[0] is None and got[1], r.stdout + r.stderr)
check("guard: `pantheon outside test` — не привилегированная команда", got and got[2] == [], got)

# --- 5b. заявки по одной (metis-0716); автопрогонов нет (03.11) ---------------------------------------------------
# заявки по одной: убитый заход не теряет остальные (2а), неснимаемая заявка не крутит заход
_h = O.handle
got = []
rc, q, r1 = role_request("athena-x", APP, "test")
time.sleep(1.1)   # время заявки — с точностью до секунды: вторая позже первой
# metis-0706: такой же test (тот же head и папка) отдал бы второй заявке id первой — вторая нужна отдельная, с другим --script
rc, q, r2 = role_request("athena-x", APP, "test", "--script", "lint")


def kill_after_first(qdir, window, rid, req):
    got.append(rid)
    raise SystemExit(9)   # заход убит посреди первой заявки


O.handle = kill_after_first
try:
    O.run_test_queue()
except SystemExit:
    pass
O.handle = _h
check("заход прерван на первой заявке: её .req.json снят, вторая лежит в очереди",
      got == [r1] and not os.path.exists(os.path.join(q, r1 + ".req.json"))
      and os.path.exists(os.path.join(q, r2 + ".req.json")), (got, r1, r2))
os.remove(os.path.join(q, r2 + ".req.json"))
rc, q, r3 = role_request("athena-x", APP, "test")
_u = O._unlink_in
O._unlink_in = lambda dfd, name: None   # снять заявку не удаётся
got = []
O.handle = lambda qdir, window, rid, req: got.append(rid)
t0 = time.time()
O.run_test_queue()
O.handle, O._unlink_in = _h, _u
check("заявку не снять: заход заканчивается, заявка не запускается и не крутит цикл", got == [] and time.time() - t0 < 30, got)
os.remove(os.path.join(q, r3 + ".req.json"))

# порядок заявок: по времени из id и по кругу между окнами, req["time"] (пишет клиент) не в счёт
qa = os.path.join(CACHE, "athena-x", "outside")
qb = os.path.join(CACHE, "metis-y", "outside")


def mkreq(qd, rid, when):
    with open(os.path.join(qd, rid + ".req.json"), "w") as fh:
        json.dump({"v": 1, "id": rid, "kind": "test", "dir": APP, "time": when}, fh)


EARLY = "2000-01-01T00:00:00+0000"
mkreq(qa, "20261102-120001-aaaaaa", EARLY)       # окно ставит себе давнее время
mkreq(qa, "20261102-120002-aaaaab", EARLY)
mkreq(qb, "20261102-120000-bbbbbb", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
order = [x[4] for x in O.requests(("test",))]
check("порядок заявок: по id, а не по времени клиента, по кругу между окнами (по одной от окна за круг)",
      order == ["20261102-120000-bbbbbb", "20261102-120001-aaaaaa", "20261102-120002-aaaaab"], order)
mkreq(qa, "20261102-120001-aaaaaa", EARLY)
mkreq(qa, "20261102-120002-aaaaab", EARLY)
mkreq(qb, "20261102-120003-bbbbbc", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
order = [x[4] for x in O.requests(("test",))]
check("круг между окнами: у окна две заявки раньше, но вторая идёт после заявки другого окна",
      order == ["20261102-120001-aaaaaa", "20261102-120003-bbbbbc", "20261102-120002-aaaaab"], order)

# круг между окнами в основном пути (run_test_queue берёт по одной заявке): a1, b, a2, a3, а не a1, a2, a3, b
mkreq(qa, "20261102-130001-aaaaaa", EARLY)
mkreq(qa, "20261102-130002-aaaaab", EARLY)
mkreq(qa, "20261102-130003-aaaaac", EARLY)
mkreq(qb, "20261102-130004-bbbbbb", EARLY)
_h, _got = O.handle, []
O.handle = lambda qdir, window, rid, req: _got.append(rid[-6:])
O.run_test_queue()
O.handle = _h
check("run_test_queue: круг между окнами сквозь заходы limit=1 — a1, b, a2, a3",
      _got == ["aaaaaa", "bbbbbb", "aaaaab", "aaaaac"], _got)

# потерянная заявка и зомби running: чинит только заход под замком outside-run
qa = os.path.join(CACHE, "athena-x", "outside")


def put_result(rid, res, age=0):
    fp = os.path.join(qa, rid + ".result.json")
    with open(fp, "w") as fh:
        json.dump({"id": rid, **res}, fh)
    os.utime(fp, (time.time() - age, time.time() - age))


put_result("20261102-101010-aaaaaa", {"state": "queued", "kind": "test", "url": "http://evil", "note": "подложено окном"}, age=900)
put_result("20261102-101010-bbbbbb", {"state": "queued", "kind": "test"}, age=30)
put_result("20261102-101010-cccccc", {"state": "queued", "kind": "test"}, age=900)
with open(os.path.join(qa, "20261102-101010-cccccc.req.json"), "w") as fh:
    fh.write("{}")
O.save_result(qa, "20261102-101010-dddddd", {"state": "running", "kind": "test", "sha": "a" * 40})   # как пишет заход
put_result("20261102-101010-gggggg", {"state": "running", "kind": "test"}, age=900)   # подложено окном
put_result("20261102-101010-a1a1a1", {"state": "running", "kind": "test"})   # старая запись runs/ без qdir
P.write_json(O.root("runs", "20261102-101010-a1a1a1.json"), {"id": "20261102-101010-a1a1a1", "state": "running", "kind": "test"})
put_result("20261102-101010-eeeeee", {"state": "queued", "kind": "serve"}, age=900)
put_result("20261102-101010-ffffff", {"state": "running", "kind": "serve"}, age=900)
P.write_json(O.root("runs", "20261102-101010-a0a0a0.json"), {"id": "20261102-101010-a0a0a0", "state": "running", "kind": "test"})
_sv = (O._queued_ids, O.overdue_accepts, O._stale)
O._queued_ids, O.overdue_accepts, O._stale = (lambda kinds=(): []), (lambda *a, **k: []), (lambda t=None: [])
check("тик: одни итоги-зомби (queued без заявки, running в runs/) — дело проходу тестов", O.pending_test() is True)
with P.lock("outside-run", block=False):
    check("тик: заход жив (замок взят) — зомби не повод для pending_test", O.pending_test() is False)
O._queued_ids, O.overdue_accepts, O._stale = _sv
with P.lock("outside-run", block=False):
    check("тик: заход жив (замок взят) — зомби не повод", not O._zombies())
O.recover_results()
st = {x: (O.load_result(qa, "20261102-101010-" + x) or {}) for x in ("aaaaaa", "bbbbbb", "cccccc", "dddddd", "eeeeee", "ffffff", "gggggg", "a1a1a1")}
check("после починки зомби в pending_test нет", not O._zombies())
check("потеряна: queued без .req.json старше 5 мин → failed «заявка потеряна»",
      st["aaaaaa"].get("state") == "failed" and "потеряна" in st["aaaaaa"].get("why", ""), st["aaaaaa"])
check("queued свежее 5 мин и queued с лежащей заявкой — не тронуты",
      st["bbbbbb"].get("state") == "queued" and st["cccccc"].get("state") == "queued", (st["bbbbbb"], st["cccccc"]))
check("зомби: running из runs/ (записал заход) → failed «заход прерван», итог — минимальный объект",
      st["dddddd"].get("state") == "failed" and "прерван" in st["dddddd"].get("why", "")
      and set(st["dddddd"]) == {"id", "kind", "state", "why", "updated"}, st["dddddd"])
check("running, подложенный окном (в runs/ нет) — не тронут",
      st["gggggg"].get("state") == "running", st["gggggg"])
check("потерянная: чужие поля из result.json окна (url, note) в итог не копируются",
      set(st["aaaaaa"]) == {"id", "kind", "state", "why", "updated"}, st["aaaaaa"])
check("serve (queued и running) проход тестов не трогает", st["eeeeee"].get("state") == "queued"
      and st["ffffff"].get("state") == "running", (st["eeeeee"], st["ffffff"]))
check("старая запись runs/ без qdir: итог в очереди окна тоже стал failed (status не врёт running)",
      st["a1a1a1"].get("state") == "failed" and "прерван" in st["a1a1a1"].get("why", ""), st["a1a1a1"])
check("running только в runs/ (без итога в очереди) → failed",
      P.read_json(O.root("runs", "20261102-101010-a0a0a0.json"), {}).get("state") == "failed")
O.save_result(qa, "20261102-101010-dddddd", {"state": "running", "kind": "test"})
check("cmd_run (замок свободен) чинит зомби сам",
      run_pass() == 0 and O.load_result(qa, "20261102-101010-dddddd").get("state") == "failed")
for x in ("aaaaaa", "bbbbbb", "cccccc", "dddddd", "eeeeee", "ffffff", "gggggg", "a1a1a1"):
    for ext in ("result.json", "req.json"):
        if os.path.exists(os.path.join(qa, f"20261102-101010-{x}.{ext}")):
            os.remove(os.path.join(qa, f"20261102-101010-{x}.{ext}"))
os.remove(O.root("runs", "20261102-101010-a0a0a0.json"))
os.remove(O.root("runs", "20261102-101010-dddddd.json"))
os.remove(O.root("runs", "20261102-101010-a1a1a1.json"))

# сторож (metis-0723): running дольше срока при живом заходе — снять; queued с заявкой дольше срока — одна тревога
_alerts = []
_pa = P.alert
P.alert = lambda text, who="pantheon": _alerts.append(text)
HOLD = ("import fcntl,os,subprocess,sys,time;"
        "fd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT|os.O_APPEND);fcntl.flock(fd,fcntl.LOCK_EX);"
        "k=subprocess.Popen(['sleep','300'],start_new_session=True,stdin=-3,stdout=-3,stderr=-3);print(k.pid,flush=True);time.sleep(300)")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    time.sleep(0.05)
    try:
        return os.waitpid(pid, os.WNOHANG) == (0, 0)
    except ChildProcessError:
        return True


def holder_start():
    os.makedirs(P.path("locks"), exist_ok=True)
    h = subprocess.Popen([sys.executable, "-I", "-c", HOLD, P.path("locks", "outside-run.lock")],
                         stdout=subprocess.PIPE, text=True)
    return h, int(h.stdout.readline())


def age_runs(rid, age):
    fp = O.root("runs", rid + ".json")
    os.utime(fp, (time.time() - age, time.time() - age))


WQ, WR, WF, WL = ("20261102-111111-" + x for x in ("aaaaaa", "bbbbbb", "cccccc", "dddddd"))
put_result(WQ, {"state": "queued", "kind": "test"}, age=O.WATCH_QUEUED + 600)
with open(os.path.join(qa, WQ + ".req.json"), "w") as fh:
    fh.write("{}")
put_result(WF, {"state": "queued", "kind": "test"}, age=O.WATCH_QUEUED - 600)    # срок не прошёл
with open(os.path.join(qa, WF + ".req.json"), "w") as fh:
    fh.write("{}")
put_result(WL, {"state": "queued", "kind": "test"}, age=O.WATCH_QUEUED + 600)    # без заявки — не дело сторожа
check("сторож: queued с заявкой дольше срока — due, моложе срока и без заявки — нет",
      O._watch_due() == [("queued", qa, WQ)], O._watch_due())
check("сторож: queued — одна тревога, итог не тронут",
      O.watchdog() == 1 and len(_alerts) == 1 and WQ in _alerts[0] and O.load_result(qa, WQ).get("state") == "queued", _alerts)
check("сторож: после тревоги queued не повод тику", not O._watch_due())
check("сторож: повторные проходы (в том числе cmd_run) тревоги не повторяют",
      O.watchdog() == 0 and run_pass() == 0 and len(_alerts) == 1, _alerts)
O.save_result(qa, WR, {"state": "running", "kind": "test", "sha": "a" * 40})
_h0 = O._run_holder
h, kid = holder_start()
O._run_holder = lambda: h.pid
O.watchdog()
check("сторож: running в пределах срока при живом заходе — не тронут",
      O.load_result(qa, WR).get("state") == "running" and alive(h.pid) and alive(kid) and len(_alerts) == 1)
age_runs(WR, O.WATCH_RUNNING + 60)
check("сторож: running дольше срока — due", O._watch_due() == [("running", qa, WR)], O._watch_due())
n = O.watchdog()
h.wait(timeout=10)
rs = O.load_result(qa, WR)
check("сторож: running дольше срока при живом заходе → failed «проверка заявок: дольше», заход и его группа убиты",
      n == 1 and rs.get("state") == "failed" and "проверка заявок: дольше" in rs.get("why", "") and not alive(h.pid) and not alive(kid)
      and set(rs) == {"id", "kind", "state", "why", "updated"}, (n, rs))
check("сторож: на снятие одна тревога, status видит итог", len(_alerts) == 2 and WR in _alerts[1]
      and P.read_json(O.root("runs", WR + ".json"), {}).get("state") == "failed", _alerts)
O.save_result(qa, WR, {"state": "running", "kind": "test"})
age_runs(WR, O.WATCH_RUNNING + 60)
O.watchdog()
check("сторож: захода нет (замок свободен) — running не снимает, его чинит recover_results",
      O.load_result(qa, WR).get("state") == "running" and len(_alerts) == 2)
h, kid = holder_start()
O._run_holder = lambda: None
O.watchdog()
O.watchdog()
check("сторож: замок держит не определить — тревога раз, процесс не тронут, итог тот же",
      len(_alerts) == 3 and alive(h.pid) and O.load_result(qa, WR).get("state") == "running", _alerts)
O._run_holder = _h0
if MAC:
    check("_run_holder: lsof находит держателя замка", O._run_holder() == h.pid, O._run_holder())
h.kill()
h.wait()
os.kill(kid, 9)
P.alert = _pa
for x in (WQ, WR, WF, WL):
    for ext in ("result.json", "req.json"):
        if os.path.exists(os.path.join(qa, f"{x}.{ext}")):
            os.remove(os.path.join(qa, f"{x}.{ext}"))
    for ext in ("json", "alerted"):
        if os.path.exists(O.root("runs", f"{x}.{ext}")):
            os.remove(O.root("runs", f"{x}.{ext}"))


# --- тревога дежурному: «принять» argus без tests дольше часа; автопрогонов нет (решение владельца 03.11) ---------
_cp = os.path.join(STATE, "autoclose-prs.json")
_saved = open(_cp).read() if os.path.exists(_cp) else None
if os.path.exists(_cp):
    os.remove(_cp)
HEADA = commit(APP, {"t.py": GREEN + "# al-run\n"}, "al-run")   # коммит без записи tests
accept(HEADA, repo="latark/al-run", age=7200)
n0, pend0 = len(calls()), O.pending_test()
run_pass()
O.run_test_queue()
check("проход без заявки тесты не запускает, даже при «принять» старше часа на открытом head: прогонов нет, записи нет",
      len(calls()) == n0 and not tests_for(HEADA), (len(calls()) - n0, tests_for(HEADA)))
for _n in ("auto_pass", "auto_todo", "run_auto", "auto_due", "early_todo", "heads_due", "find_checkout", "waiting_keys"):
    check(f"автопрогонов нет: O.{_n} удалена", not hasattr(O, _n))
a_ = P.read_json(O.root("auto.json"), {})
check("«принять» старше часа + открытый head → дело для тика и одна тревога с repo@sha12 и номером PR",
      pend0 and O.pending_test() is False and a_.get("alerted", {}).get(f"latark/al-run@{HEADA}")
      and alerts().count(f"latark/al-run@{HEADA[:12]}") == 1 and "(PR #100)" in alerts(), (pend0, alerts()[-300:]))
run_pass()
run_pass()
check("повторные проходы: тревога на (repo, sha) одна", alerts().count(f"latark/al-run@{HEADA[:12]}") == 1, alerts()[-400:])
check("после тревоги тик не будится", not O.pending_test())

AL = {c: c * 40 for c in "abcdefg"}
accept(AL["a"], repo="latark/al-new", age=1800)
check("«принять» 30 мин назад (<1 ч): ни дела, ни тревоги",
      O.overdue_accepts() == [] and O.alert_overdue() == 0 and AL["a"][:12] not in alerts() and not O.pending_test())
accept(AL["b"], repo="latark/al-tests", age=7200)
with open(RECORDS, "a") as fh:
    fh.write(json.dumps({"v": 1, "kind": "tests", "repo": ["latark/al-tests"], "pr": None, "sha": AL["b"],
                         "by": {"agent_type": "pantheon-outside", "agent_id": "", "session_id": "", "request": "x"},
                         "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}) + "\n")
accept(AL["c"], repo="latark/al-dev", who="dev-opus", age=7200)
accept(AL["d"], repo="latark/al-old", age=2 * 86400)
check("есть запись tests, «принять» не от argus, старше суток: тревоги нет",
      O.overdue_accepts() == [] and O.alert_overdue() == 0 and not any(AL[c][:12] in alerts() for c in "bcd"))
accept(AL["e"], repo="latark/al-moved", age=7200)
os.remove(_cp)
open_pr("latark/al-moved", AL["f"])      # PR ушёл вперёд: «принять» было на другой head
check("head уже не открыт у PR: тревоги нет", O.overdue_accepts() == [] and O.alert_overdue() == 0)
os.remove(_cp)
accept(AL["g"], repo="latark/al-nocache", age=7200)
os.remove(_cp)
check("кэша открытых PR нет: журнал не читается, тревоги нет", O.overdue_accepts() == [] and not O.pending_test())
accept(AL["g"], repo="latark/al-stale", age=7200)
c_ = json.load(open(_cp))
c_["fetched"] = time.time() - 2 * 3600
json.dump(c_, open(_cp, "w"))
check("кэш старше часа (gh не ответил): тревоги нет", O.overdue_accepts() == [])
c_["fetched"] = time.time()
c_["errors"] = {"latark/al-stale": "gh не ответил"}
json.dump(c_, open(_cp, "w"))
check("gh не ответил по репозиторию: тревоги нет", O.overdue_accepts() == [])
if _saved is not None:
    with open(_cp, "w") as fh:
        fh.write(_saved)
elif os.path.exists(_cp):
    os.remove(_cp)

# --- 5c. перед стартом заявки test: устаревший head и дубли (metis-0726) -------------------------------------------
_cp = os.path.join(STATE, "autoclose-prs.json")
_saved = open(_cp).read() if os.path.exists(_cp) else None
qa = os.path.join(CACHE, "athena-x", "outside")
HEADA = git(APP, "rev-parse", "HEAD")


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
put_cache(old_heads={"Latark/App": {HEADA: 5}}, prs={"Latark/App": [{"number": 5, "head": NEWH}]})
n0 = len(calls())
r_st = one_request()
run_pass()
res = O.load_result(qa, r_st) or {}
check("0726: HEAD папки — бывший head открытого PR, у PR другой head → failed «head устарел», прогона нет",
      res.get("state") == "failed" and "head устарел, подай на текущий" in res.get("why", "")
      and NEWH[:12] in res.get("why", "") and len(calls()) == n0, (res, len(calls()) - n0))
r_lint = one_request(script="lint")
run_pass()
check("0726: --script на бывшем head идёт (проверка для себя, не для шлюза)",
      (O.load_result(qa, r_lint) or {}).get("state") == "done" and len(calls()) == n0 + 1)
for label, kw in (("кэша нет", None), ("кэш старше часа", {"fetched": time.time() - 2 * 3600}),
                  ("gh не ответил по репозиторию", {"errors": {"latark/app": "x"}}),
                  ("SHA не бывший head (коммит не пушили)", {"old": {"latark/app": {"8" * 40: 5}}}),
                  ("PR закрыт (в open_prs его нет)", {"prs": {"latark/app": [{"number": 6, "head": NEWH}]}})):
    if kw is None:
        os.remove(_cp)
    else:
        put_cache(old_heads=kw.get("old", {"latark/app": {HEADA: 5}}),
                  prs=kw.get("prs", {"latark/app": [{"number": 5, "head": NEWH}]}),
                  fetched=kw.get("fetched"), errors=kw.get("errors"))
    n1 = len(calls())
    r_ok = one_request()
    run_pass()
    res = O.load_result(qa, r_ok) or {}
    check(f"0726: {label} — прогон как раньше", res.get("state") == "done" and len(calls()) == n1 + 1, res)

# Д3: SHA — бывший head PR #5 и при этом head другого открытого PR (#7) в том же кэше — не устарел, прогон
put_cache(old_heads={"Latark/App": {HEADA: 5}},
          prs={"Latark/App": [{"number": 5, "head": NEWH}, {"number": 7, "head": HEADA.upper()}]})
n1 = len(calls())
r_ok = one_request()
run_pass()
res = O.load_result(qa, r_ok) or {}
check("0726: бывший head #5 стал head #7 — не устарел, прогон", res.get("state") == "done" and len(calls()) == n1 + 1, res)
# force-push назад: PR #5 снова на старом head, old_heads его ещё помнит
put_cache(old_heads={"Latark/App": {HEADA: 5}}, prs={"Latark/App": [{"number": 5, "head": HEADA}]})
n1 = len(calls())
r_ok = one_request()
run_pass()
res = O.load_result(qa, r_ok) or {}
check("0726: force-push назад — старый head снова текущий, прогон", res.get("state") == "done" and len(calls()) == n1 + 1, res)
put_cache(old_heads={"Latark/App": {HEADA: 5}},
          prs={"Latark/App": [{"number": 5, "head": NEWH}, {"number": 7, "head": HEADA}]})
check("0726: stale_head напрямую: head другого открытого PR — None", O.stale_head(APP, HEADA) is None)

# дубли: три заявки на одну папку и одна с --script — идёт первая и lint, две другие failed «дубль <первая>»
os.remove(_cp)
n1 = len(calls())
r_d = [one_request() for _ in range(3)]
r_dl = one_request(script="lint")
qk = os.path.join(CACHE, "metis-y", "outside")
r_other = one_request(qd=qk)   # чужое окно: папка не его — отказ своим путём, не дубль
run_pass()
st = {r: O.load_result(qa, r) or {} for r in r_d + [r_dl]}
check("0726: дубли на ту же папку — в работу одна (первая), прогон один",
      st[r_d[0]].get("state") == "done" and st[r_d[0]].get("code") == 0 and len(calls()) == n1 + 2,
      (st[r_d[0]], len(calls()) - n1))
check("0726: остальные — failed «дубль <id первой>», с командой итога",
      all(st[r].get("state") == "failed" and st[r].get("why", "").startswith(f"дубль {r_d[0]}")
          and f"итог у заявки {r_d[0]} в окне athena-x" in st[r]["why"] and "outside status" not in st[r]["why"]
          for r in r_d[1:]), [st[r] for r in r_d[1:]])
check("0726: снятый дубль и --wait: код 75 («итога ещё нет»), а не 1",
      all(O.result_code(st[r]) == 75 for r in r_d[1:]) and O.result_code({"state": "failed", "why": "x"}) == 1,
      [O.result_code(st[r]) for r in r_d[1:]])
check("0726: заявка с другим --script — не дубль, идёт", st[r_dl].get("state") == "done", st[r_dl])
check("0726: заявка чужого окна на ту же папку — не дубль (отказ «не из папок направления»)",
      "не из папок направления" in (O.load_result(qk, r_other) or {}).get("why", ""))
# другая папка того же репозитория на том же HEAD (worktree) — тоже дубль
WT2 = os.path.join(APP, "..", "app-wt2")
git(APP, "worktree", "add", "-q", "--detach", os.path.realpath(WT2), HEADA)
P.write_json(os.path.join(STATE, "domains.json"),
             {"domains": {"athena-x": ["~/projects/app", "~/projects/app-wt2"], "metis-y": ["~/projects/other"]}})
r_a = one_request()
one_request.n += 1
r_b = f"20261103-0{one_request.n:05d}-c0c0c0"
with open(os.path.join(qa, r_b + ".req.json"), "w") as fh:
    json.dump({"v": 1, "id": r_b, "kind": "test", "dir": os.path.realpath(WT2),
               "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, fh)
n1 = len(calls())
run_pass()
check("0726: worktree того же репозитория на том же HEAD — дубль",
      (O.load_result(qa, r_b) or {}).get("why", "").startswith(f"дубль {r_a}") and len(calls()) == n1 + 1,
      (O.load_result(qa, r_b), len(calls()) - n1))
# Д1: worktree того же репозитория на другом HEAD — не дубль
WT2R = os.path.realpath(WT2)


def req_dir(d):
    one_request.n += 1
    rid = f"20261103-0{one_request.n:05d}-c0c0c0"
    with open(os.path.join(qa, rid + ".req.json"), "w") as fh:
        json.dump({"v": 1, "id": rid, "kind": "test", "dir": d, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, fh)
    return rid


git(WT2R, "commit", "-q", "--allow-empty", "-m", "wt2 свой коммит")
r_a = req_dir(APP)
r_b = req_dir(WT2R)
n1 = len(calls())
run_pass()
rb = O.load_result(qa, r_b) or {}
check("0726: worktree того же репозитория на другом HEAD — не дубль, идёт своим прогоном",
      rb.get("state") == "done" and not rb.get("dup") and len(calls()) == n1 + 2, (rb, len(calls()) - n1))
# тот же HEAD, но дерево грязное — не дубль (итог — «дерево не чистое», а не «дубль»)
git(WT2R, "reset", "-q", "--hard", HEADA)
with open(os.path.join(WT2R, "dirty.txt"), "w") as fh:
    fh.write("x")
r_a = req_dir(APP)
r_b = req_dir(WT2R)
run_pass()
rb = O.load_result(qa, r_b) or {}
check("0726: тот же HEAD, дерево грязное — не дубль",
      not rb.get("dup") and not rb.get("why", "").startswith("дубль") and "не чистое" in rb.get("why", ""), rb)
os.remove(os.path.join(WT2R, "dirty.txt"))
git(APP, "worktree", "remove", "--force", os.path.realpath(WT2))
P.write_json(os.path.join(STATE, "domains.json"),
             {"domains": {"athena-x": ["~/projects/app"], "metis-y": ["~/projects/other"]}})

# --- 5d. запись по дереву (metis-0732) ------------------------------------------------
KIT = os.path.join(HOME, "projects", "kit")
os.makedirs(KIT)
git(KIT, "init", "-q", "-b", "main")
git(KIT, "remote", "add", "origin", "git@github.com:latark/kit.git")
os.makedirs(os.path.join(CACHE, "metis-k", "tmp"))
P.write_json(os.path.join(STATE, "domains.json"),
             {"domains": {"athena-x": ["~/projects/app"], "metis-y": ["~/projects/other"], "metis-k": ["~/projects/kit"]}})
M = P.merge_mod()
M.FULL_TESTS["kit"] = "heavy python3 t.py"   # полный набор этого репозитория для теста (у agent-kit — run-tests.py)
K1 = commit(KIT, {"t.py": GREEN, ".pantheon-verify": "heavy python3 t.py\n"}, "k1")
qkit = os.path.join(CACHE, "metis-k", "outside")


def kit_request():
    one_request.n += 1
    rid = f"20261103-1{one_request.n:05d}-c0c0c0"
    os.makedirs(qkit, exist_ok=True)
    with open(os.path.join(qkit, rid + ".req.json"), "w") as fh:
        json.dump({"v": 1, "id": rid, "kind": "test", "dir": KIT, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, fh)
    run_pass()
    return O.load_result(qkit, rid) or {}


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


def test_work(rid):
    return os.path.join(os.path.realpath(HOME), "Library", "Caches", "pantheon-outside", "work", "test-" + rid)


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
_tr, _wp = O.tree_record, O.wait_proc


def _move_head(d):
    git(str(d), "checkout", "-q", "--detach", HEADE)


for label, attr, fake in (
        ("перед прогоном", "tree_record", lambda rid, d, *a, **kw: (_move_head(d), _tr(rid, d, *a, **kw))[1]),
        # wait_proc зовёт и установка (prepare) — HEAD двигаем только в прогоне теста (у него idle_log)
        ("во время прогона", "wait_proc",
         lambda proc, *a, **kw: (kw.get("idle_log") and _move_head(_cwd_of[0]), _wp(proc, *a, **kw))[1])):
    _cwd_of = [None]
    _rt = O.run_test
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

# --- 6. сироты (metis-0614): после всех серверов и стопов ни заглушки, ни задач «turbo» в живых --------------------
kill_all_servers()
_left = [p for p in fake_pids() if still_alive(p)]
check("тесты не оставляют процессов: заглушка sandbox-exec и задачи «turbo» погашены", fake_pids() and not _left,
      (_left, len(fake_pids())))

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
