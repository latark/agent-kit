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
копии, лимит памяти сервера; безопасность копии: .git-файл роли, конфиг клона с командами, подмодули, worktree для тестов
после «принять» — через trusted_clone; окружение команды с нуля; профиль; тик зовёт каждый проход только по делу; `outside run` из окна Claude Code —
отказ; guard не спрашивает.
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
    # cwd="/": сирота по папке копии её не достаёт — гасит только обход потомков (strays), мутант без него красный
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
    try:
        for n in (".env", ".env.local", ".env.production.local", ".env.example.bak", ".env.example", ".env.sample",
                  ".env.template"):
            with open(os.path.join(d, n), "w") as fh:
                fh.write("x")
    except PermissionError as e:   # сам тест идёт под профилем прохода (`pantheon outside test`): .env* там закрыт
        return None, f"файлы .env* не создать — тест уже под песочницей ({e.strerror})"
    os.makedirs(os.path.join(d, "secrets"))
    with open(os.path.join(d, "secrets", ".env.example"), "w") as fh:
        fh.write("x")
    sb = os.path.join(d, "p.sb")
    with open(sb, "w") as fh:
        fh.write(profile)

    def run(*cmd):
        return subprocess.run(["/usr/bin/sandbox-exec", "-f", sb, *cmd], capture_output=True, text=True, cwd=d)
    try:
        r = run("/bin/cat", ".env.example")
    except OSError as e:
        return None, str(e)
    if r.returncode != 0 and "sandbox_apply" in r.stderr:
        return None, r.stderr.strip()
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

# --- 2. тесты после «принять» -------------------------------------------------------------------------------------
before = len(calls())
accept(C3)
check("тик: есть новое «принять» — проход нужен", O.pending())
res = O.auto_pass()
check("принять C3 (HEAD клона): один прогон", len(res) == 1 and res[0].get("code") == 0, res)
recs = tests_for(C3)
check("запись tests принята настоящим шлюзом guard", len(recs) == 1, gate_records())
r0 = recs[0] if recs else {}
check("запись: repo по remote, pr null, by = проход",
      r0.get("repo") == [REPO] and r0.get("pr") is None and r0.get("by", {}).get("agent_type") == "pantheon-outside", r0)
check("запись: команда и папка", r0.get("cmd") == HEAD_NOTE and r0.get("cwd") == os.path.realpath(APP), r0)
c = calls()[before:]
check("прогон — под sandbox-exec с профилем STATE/outside/profile.sb",
      len(c) == 1 and c[0]["profile"] == os.path.join(STATE, "outside", "profile.sb") and os.path.isfile(c[0]["profile"]), c)
env = c[0]["env"] if c else {}
check("окружение с нуля: нет GH_TOKEN, есть CI=1 и свой TMPDIR",
      "GH_TOKEN" not in env and env.get("CI") == "1" and env.get("TMPDIR", "").startswith(_ROOT) and env.get("HOME") == os.path.realpath(HOME), sorted(env))
check("тик: «принять» разобрано — прохода нет", not O.pending())
check("повтор прохода — без второго прогона", O.auto_pass() == [] and len(tests_for(C3)) == 1)

# коммит не на HEAD: временный worktree, зависимости, уборка
before = len(calls())
accept(C1)
res = O.auto_pass()
check("принять C1 (не HEAD): тесты прошли, запись есть", len(res) == 1 and len(tests_for(C1)) == 1, res)
c = calls()[before:]
wt = os.path.join(HOME, "Library", "Caches", "pantheon-outside", "wt")
check("временный worktree вне STATE, сначала npm ci, потом тест",
      len(c) == 2 and c[0]["cmd"] == ["npm", "ci"] and c[1]["cwd"].startswith(os.path.realpath(wt)), [x["cmd"] for x in c])
check("временный worktree снят", not os.listdir(wt) and "pantheon-outside" not in git(APP, "worktree", "list"))
check("клон не тронут: HEAD = C3", git(APP, "rev-parse", "HEAD") == C3)

# красные тесты
accept(C2)
res = O.auto_pass()
check("принять C2 (красный): записи нет", len(tests_for(C2)) == 0 and res and res[0].get("code") == 1, res)
check("красный: тревога со ссылкой на журнал", f"{REPO}@{C2[:12]}" in alerts() and "pantheon outside status" in alerts())
check("красный: хвост журнала в итоге", "тест упал" in (res[0].get("tail") or "") if res else False, res)

# не берутся: чужой agent_type, старое, нет копии, уже есть tests
accept(C1[:-1] + ("0" if C1[-1] != "0" else "1"), who="dev-opus")
accept("e" * 40, age=2 * 86400)
accept("f" * 40, repo="latark/nowhere")
todo = O.auto_todo()
check("не argus и старше суток — не берутся; нет копии — берётся", todo == [("latark/nowhere", "f" * 40)], todo)
res = O.auto_pass()
check("нет копии: тревога, записи нет", "нет копии latark/nowhere" in alerts() and not tests_for("f" * 40), res)

# грязное дерево клона на HEAD: копия не годится, worktree на коммите — чистый
C4 = commit(APP, {"t.py": GREEN + "# c4\n"}, "c4")
with open(os.path.join(APP, "t.py"), "a") as fh:
    fh.write("raise SystemExit(0)  # правка без коммита\n")
accept(C4)
before = len(calls())
O.auto_pass()
c = calls()[before:]
check("грязный клон: тест идёт во временном worktree", c and c[-1]["cwd"] != os.path.realpath(APP) and len(tests_for(C4)) == 1,
      [x["cwd"] for x in c])
git(APP, "checkout", "--", "t.py")

# команда портит дерево — записи нет
C5 = commit(APP, {"t.py": "open('junk.txt', 'w').write('x')\n"}, "c5 пачкает")
accept(C5)
res = O.auto_pass()
check("команда изменила дерево: записи нет, причина названа",
      not tests_for(C5) and "изменила HEAD или дерево" in (res[0].get("why") or ""), res)
os.remove(os.path.join(APP, "junk.txt"))

# пустая команда в .pantheon-verify — записи нет
C6 = commit(APP, {".pantheon-verify": "true\n"}, "c6 пустая проверка")
accept(C6)
res = O.auto_pass()
check("пустая команда (true): записи нет", not tests_for(C6) and "ничего не проверяет" in (res[0].get("why") or ""), res)
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
import fcntl  # noqa: E402
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
check("лимит памяти сервера по умолчанию — 6 ГБ", O.SERVER_MEM_MB == 6144)
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

# 7. тесты после «принять»: worktree роли, чей .git-файл ведёт не в <клон>/.git/worktrees/<имя>, не берётся — его git
# исполнил бы конфиг, который пишет роль; берётся временный worktree прохода
_S = C1   # не HEAD клона: иначе find_checkout возьмёт сам клон
WT7 = os.path.join(_wtd, "wt7")
git(APP, "worktree", "add", "-q", "--detach", WT7, _S)
_fc = O.find_checkout(REPO, _S)
check("find_checkout: настоящий worktree клона реестра — Repo с gitdir клона",
      isinstance(_fc[0], O.Repo) and _fc[0].clone == os.path.realpath(APP)
      and _fc[0].gitdir.startswith(os.path.join(os.path.realpath(APP), ".git", "worktrees") + "/")
      and isinstance(_fc[1], O.Repo), _fc)
_EG = os.path.join(_ROOT, "evil-gitdir", "wt7")
_real_gd = open(os.path.join(WT7, ".git")).read().split(":", 1)[1].strip()
shutil.copytree(_real_gd, _EG)
with open(os.path.join(_EG, "commondir"), "w") as fh:
    fh.write(os.path.join(os.path.realpath(APP), ".git") + "\n")
_saved7 = open(os.path.join(WT7, ".git")).read()
with open(os.path.join(WT7, ".git"), "w") as fh:
    fh.write(f"gitdir: {_EG}\n")
check("проба честная: git по подложенному gitdir видит тот же HEAD и чистое дерево",
      O.head_state(os.path.realpath(WT7)) == (_S, True), O.head_state(os.path.realpath(WT7)))
_fc = O.find_checkout(REPO, _S)
check("find_checkout: .git-файл worktree ведёт в gitdir роли — копия не берётся, только клон для временного worktree",
      _fc[0] is None and _fc[1] == os.path.realpath(APP), _fc)
with open(os.path.join(WT7, ".git"), "w") as fh:
    fh.write(_saved7)
git(APP, "worktree", "remove", "--force", WT7)
shutil.rmtree(WT7, ignore_errors=True)
shutil.rmtree(os.path.dirname(_EG), ignore_errors=True)
git(APP, "worktree", "prune")

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
                            "time.sleep(120)"], cwd=work_of(rid_s), start_new_session=True)
TEST_PROCS.append(_orphan)
t0 = time.monotonic()
rc, out = say("metis-y", "stop", rid_s)
dt = time.monotonic() - t0
check("стоп из другого окна при занятом проходе тестов: stopped за ≤10 с, `stop` дождался, код 0, тест идёт",
      rc == 0 and "stopped" in out and dt <= 10 and th_t.is_alive() and state(q, rid_t) == "running",
      (rc, out, round(dt, 1)))
check("стоп: порт свободен, погашены сервер, «turbo», задача в своей группе и сирота по папке копии",
      not port_open(port) and not any(pid_alive(p) for p in pids + [srvpid]) and _gone(_orphan)
      and rid_s not in O.servers() and not os.path.exists(work_of(rid_s)),
      [(p, pid_alive(p, 0)) for p in pids + [srvpid]] + [_orphan.poll()])
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

# --- номер процесса сервера занял чужой (metis-0606, Д-2 argus): не гасить ни его, ни его детей в своих группах ----
_spawn = [sys.executable, "-c", "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', "
          "'import time; time.sleep(60)'], start_new_session=True); time.sleep(60)"]
alien = subprocess.Popen(_spawn)                                  # не глава группы: группа — наша, теста
TEST_PROCS.append(alien)
time.sleep(0.8)
_ps = subprocess.run(["/bin/ps", "-axo", "pid=,ppid="], capture_output=True, text=True).stdout.split()
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

# --- 6. сироты (metis-0614): после всех серверов и стопов ни заглушки, ни задач «turbo» в живых --------------------
kill_all_servers()
_left = [p for p in fake_pids() if still_alive(p)]
check("тесты не оставляют процессов: заглушка sandbox-exec и задачи «turbo» погашены", fake_pids() and not _left,
      (_left, len(fake_pids())))

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
