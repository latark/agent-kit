#!/usr/bin/env python3
"""Проверки вне окна роли ([sb-simplify] п. 7, lib/outside.py): sandbox-exec подменён записывающей заглушкой.

Запуск: python3 -I plugins/pantheon/tests/test_outside.py  (код выхода 0 — все прошли)
Проверяет на временных папках: после «принять» argus проход сам гоняет тесты и пишет запись tests, которую
принимает настоящий merge_gate.read_records guard; красные тесты, чужой agent_type, старое «принять», уже есть
tests, грязное дерево, команда меняет дерево, пустая команда — записи нет; коммит не на HEAD — временный worktree с
установкой зависимостей и его уборка; заявка роли из кэша окна → итог рядом с ней; окно не своего направления,
мастерская, подложенная ссылка, скрипта нет — отказ; dev-сервер → адрес, «стоп» и срок гасят; окружение команды с
нуля; профиль; тик зовёт проход только по делу; `outside run` из окна Claude Code — отказ; guard не спрашивает.
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
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1", "TMPDIR": _ROOT, "GH_TOKEN": "secret-gh"})
sys.path.insert(0, LIBDIR)
import pantheon as P  # noqa: E402
O = P.outside_mod()


def _kill_servers():
    """Серверы теста гаснут и при падении проверки (мутант без гашения не оставляет http.server висеть)."""
    for s in O.servers().values():
        if s.get("pid"):
            O.kill_group(int(s["pid"]))


_atexit.register(_kill_servers)  # раньше rmtree: atexit идёт с конца

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
with open(FAKE, "w") as fh:
    fh.write(f"#!{sys.executable}\n" + r'''
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
    task = ("import os, signal, socket\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "s = socket.socket(); s.bind(('127.0.0.1', int(os.environ['PORT']))); s.listen(64)\n"
            "while True:\n    s.accept()[0].close()\n")
    kid = subprocess.Popen([sys.executable, "-c", task], start_new_session=True)
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
''' % (REC, DEVTREE_PIDS, HOLD_RELEASE))
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
    code = ("import sys, json; sys.path.insert(0, %r); import guard, merge_gate as m; "
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
    for n in (".env", ".env.local", ".env.production.local", ".env.example.bak", ".env.example", ".env.sample",
              ".env.template"):
        with open(os.path.join(d, n), "w") as fh:
            fh.write("x")
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

# --- 4. dev-сервер ------------------------------------------------------------------------------------------------
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

before = len(calls())
rc, q, rid = role_request("athena-x", APP, "serve", "--minutes", "5")
run_pass()
res = O.load_result(q, rid) or {}
port = res.get("port") or 0
check("ряд портов сервера по умолчанию — 3200–3299", DEFAULT_PORTS == range(3200, 3300), DEFAULT_PORTS)
check("сервер: адрес http://127.0.0.1:<порт из ряда>", res.get("state") == "serving" and port in O.SERVER_PORTS
      and res.get("url") == f"http://127.0.0.1:{port}", res)
check("сервер отвечает по адресу", port_open(port))
c = calls()[before:]
check("сервер: PORT в окружении, без CI и GH_TOKEN", c and c[-1]["env"].get("PORT") == str(port)
      and "CI" not in c[-1]["env"] and "GH_TOKEN" not in c[-1]["env"], c[-1]["env"] if c else c)
check("сервер в servers.json", rid in O.servers())
check("тик: живой сервер в срок — прохода нет", not O.pending())
rc, q2, rid2 = role_request("athena-x", APP, "serve")
run_pass()
res2 = O.load_result(q2, rid2) or {}
check("второй сервер — другой порт", res2.get("state") == "serving" and res2.get("port") != port, res2)
os.environ["PANTHEON_TMP"] = os.path.join(CACHE, "athena-x", "tmp")
check("стоп: код 0", O.main(["stop", rid]) == 0)
os.environ.pop("PANTHEON_TMP")
check("тик: «стоп» — проход нужен", O.pending())
run_pass()
res = O.load_result(q, rid) or {}
check("стоп: сервер погашен, итог stopped", res.get("state") == "stopped" and not port_open(port) and rid not in O.servers(), res)
check("второй сервер жив", port_open(res2.get("port") or 0) and rid2 in O.servers())
os.environ["PANTHEON_NOW"] = str(time.time() + 31 * 60)
check("тик: срок вышел — проход нужен", O.pending())
run_pass()
os.environ.pop("PANTHEON_NOW")
res2 = O.load_result(q2, rid2) or {}
check("срок вышел: сервер погашен сам", res2.get("state") == "stopped" and "срок" in res2.get("why", "")
      and not port_open(res2.get("port") or 0), res2)

rc, q, rid = role_request("athena-x", APP, "serve", "--script", "bad")
run_pass()
res = O.load_result(q, rid) or {}
check("сервер упал: failed, код и хвост журнала", res.get("state") == "failed" and "кодом 3" in res.get("why", "")
      and "boom" in res.get("tail", ""), res)
O.READY_SEC = 2
rc, q, rid = role_request("athena-x", APP, "serve", "--script", "slow")
t0 = time.monotonic()
run_pass()
res = O.load_result(q, rid) or {}
check("порт не открылся: failed, процесс погашен", res.get("state") == "failed" and "не открылся" in res.get("why", "")
      and not O.servers(), res)
rc, _, _ = role_request("athena-x", APP, "serve", "--minutes", "500")
check("срок больше 120 минут: код 2", rc == 2)

# --- serve и очередь heavy (metis-0593): оба места заняты — ждать в пределах --wait роли, не падать за 6 с ----------
import fcntl, threading
LOCKS = os.path.join(STATE, "locks")
os.makedirs(LOCKS, exist_ok=True)
for _n in ("heavy-cmd-1", "heavy-cmd-2", "heavy-server"):
    open(os.path.join(LOCKS, _n + ".lock"), "a").close()


def hold(*names):
    fds = []
    for n in names:
        fd = os.open(os.path.join(LOCKS, n + ".lock"), os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fds.append(fd)
    return fds


def release(fds):
    for fd in fds:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def serve_with_wait(wait, *args):
    """Заявка serve с полем wait (как у `--wait N`, но без блокировки теста на N секунд)."""
    rc, q, rid = role_request("athena-x", APP, "serve", *args)
    fp = os.path.join(q, rid + ".req.json")
    req = json.load(open(fp))
    req["wait"] = wait
    json.dump(req, open(fp, "w"))
    return q, rid


O.HEAVY = "default"
held = hold("heavy-cmd-1", "heavy-cmd-2")
q, rid = serve_with_wait(40)
threading.Timer(9, release, [held]).start()   # дольше старых 6 с: мутант «ждать 6 с» этот тест краснит
t0 = time.monotonic()
run_pass()
res = O.load_result(q, rid) or {}
check("serve при занятых местах heavy: ждёт освобождения и поднимается (не failed за 6 с)",
      res.get("state") == "serving" and time.monotonic() - t0 >= 8, (res, time.monotonic() - t0))
check("serve из очереди: сервер отвечает", port_open(res.get("port") or 0))
_srv = O.servers()
O.kill_group(_srv[rid]["pid"])
_srv.pop(rid)
O.save_servers(_srv)

held = hold("heavy-cmd-1", "heavy-cmd-2")
q, rid = serve_with_wait(4)
t0 = time.monotonic()
run_pass()
res = O.load_result(q, rid) or {}
check("serve: места не освободились за --wait — failed, настоящая причина, не «сервер уже запущен»",
      res.get("state") == "failed" and "оба места heavy заняты тяжёлыми командами" in res.get("why", "")
      and "не дождалась за 4 с" in res.get("why", "") and "уже запущен" not in res.get("why", ""), res)
check("serve: не дождалась — код 75", O.result_code(res) == 75 and 3 <= time.monotonic() - t0 < 14, O.result_code(res))
release(held)

held = hold("heavy-server")
q, rid = serve_with_wait(4)
run_pass()
res = O.load_result(q, rid) or {}
check("serve: место сервера занято другим сервером — своя причина и код 75",
      res.get("state") == "failed" and "heavy --server держит" in res.get("why", "") and O.result_code(res) == 75, res)
release(held)

q, rid = serve_with_wait(0)
held = hold("heavy-cmd-1", "heavy-cmd-2")
t0 = time.monotonic()
run_pass()
res = O.load_result(q, rid) or {}
check("serve без --wait: старое короткое ожидание, failed с верной причиной",
      res.get("state") == "failed" and "оба места" in res.get("why", "") and time.monotonic() - t0 < 14, res)
release(held)

# --- «стоп» при занятом проходе и задача в своей группе процессов (metis-0606): настоящий heavy --server ----------
# 30.10: проход держал замок, пока гонял тесты после «принять» (часами), «стоп» ждал конца всех прогонов; а turbo
# ставит задаче свою группу — next dev переживал killpg группы сервера.


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


def devtree_pids():
    try:
        with open(DEVTREE_PIDS) as fh:
            return [int(x) for x in fh.read().split()]
    except (OSError, ValueError):
        return []


def _kill_devtree():
    import signal as _sig
    for p in devtree_pids():
        try:
            os.kill(p, _sig.SIGKILL)
        except OSError:
            pass


_atexit.register(_kill_devtree)   # мутант без гашения ушедших групп не оставляет задачу висеть на порту


def new_request(window, *args):
    q = os.path.join(CACHE, window, "outside")
    before = set(os.listdir(q)) if os.path.isdir(q) else set()
    rc, q, _ = role_request(window, APP, *args)
    rid = next(n[:-9] for n in os.listdir(q) if n.endswith(".req.json") and n not in before)
    return q, rid


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


O.READY_SEC = 15
q, rid_s = new_request("athena-x", "serve", "--script", "devtree")
_, rid_t = new_request("athena-x", "test", "--script", "hold")
th = threading.Thread(target=run_pass)
th.start()
up = wait_for(lambda: state(q, rid_s) == "serving" and state(q, rid_t) == "running", 40)
res = O.load_result(q, rid_s) or {}
port, pids = res.get("port") or 0, devtree_pids()
hv = int((O.servers().get(rid_s) or {}).get("pid") or 0)
check("стоп при занятом проходе: сервер (heavy --server → «turbo» → задача в своей группе) поднят, тест идёт",
      up and port_open(port) and len(pids) == 2 and hv and th.is_alive(), (res, pids, hv))
os.environ["PANTHEON_TMP"] = os.path.join(CACHE, "athena-x", "tmp")
O.main(["stop", rid_s])
os.environ.pop("PANTHEON_TMP")
t0 = time.monotonic()
stopped = wait_for(lambda: state(q, rid_s) == "stopped", 20)
dt = time.monotonic() - t0
check("стоп во время прогона тестов прохода: stopped за ≤10 с, тест ещё идёт",
      stopped and dt <= 10 and th.is_alive() and state(q, rid_t) == "running", (state(q, rid_s), round(dt, 1)))
check("стоп: порт свободен, погашены heavy --server, «turbo» и задача в своей группе процессов",
      # слушателя нет — не port_free: bind без SO_REUSEADDR (metis-0592) ловит TIME_WAIT после accept().close()
      not port_open(port) and not any(pid_alive(p) for p in pids + [hv]) and rid_s not in O.servers()
      and not (O.load_result(q, rid_s) or {}).get("note"), [(p, pid_alive(p, 0)) for p in pids + [hv]])
open(HOLD_RELEASE, "w").close()
th.join(90)
res = O.load_result(q, rid_t) or {}
check("тест после стопа сервера дошёл до конца, код 0", res.get("state") == "done" and res.get("code") == 0, res)
_kill_devtree()

# «погаси прежний и подними новый»: новый ждёт место heavy --server, «стоп» прежнего приходит в это время
q, rid_a = new_request("athena-x", "serve")
run_pass()
check("прежний сервер поднят, в servers.json — время старта его процесса",
      state(q, rid_a) == "serving" and O.servers()[rid_a].get("started") == O.started(O.servers()[rid_a]["pid"])
      and O.servers()[rid_a].get("started"), O.servers().get(rid_a))
q, rid_b = serve_with_wait(15)


def _stop_a():
    os.environ["PANTHEON_TMP"] = os.path.join(CACHE, "athena-x", "tmp")
    O.main(["stop", rid_a])
    os.environ.pop("PANTHEON_TMP")


threading.Timer(3, _stop_a).start()
t0 = time.monotonic()
run_pass()
dt = time.monotonic() - t0
res = O.load_result(q, rid_b) or {}
check("новый сервер ждёт место, «стоп» прежнего в это время — прежний гаснет, новый поднят до конца --wait",
      state(q, rid_a) == "stopped" and res.get("state") == "serving" and dt < 14, (state(q, rid_a), res, round(dt, 1)))
_stops = [json.loads(x) for x in open(os.path.join(STATE, "logs", "outside.jsonl"))]
_stops = [x.get("why") for x in _stops if x.get("id") == rid_a and x.get("kind") == "stop"]
check("servers.json — только новый: прежний не вернулся из старого снимка (один «стоп», причина — заявка)",
      set(O.servers()) == {rid_b} and _stops == ["заявка «стоп»"]
      and (O.load_result(q, rid_a) or {}).get("why") == "заявка «стоп»", (O.servers(), _stops))
_srv = O.servers()
for _r in list(_srv):
    O.kill_group(_srv[_r]["pid"])
O.save_servers({})
O.HEAVY = None

# --- номер процесса сервера занял чужой (metis-0606, Д-2 argus): не гасить ни его, ни его детей в своих группах ----
_spawn = [sys.executable, "-c", "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', "
          "'import time; time.sleep(60)'], start_new_session=True); time.sleep(60)"]
alien = subprocess.Popen(_spawn)                                  # не глава группы: группа — наша, теста
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
    with __import__("contextlib").suppress(OSError):
        os.kill(_p, 9)
alien.kill()
alien.wait()

leader = subprocess.Popen(["/bin/sleep", "60"], start_new_session=True)   # глава своей группы, как heavy сервера
time.sleep(0.3)
O.save_servers({"20261030-000000-b2b2b2": {"pid": leader.pid, "started": "Thu Jan  1 00:00:00 1970", "port": 0,
                                           "until": time.time() + 3600, "qdir": None}})
check("номер сервера занял чужой процесс — серверу пора к гашению (sweep_due)", O.sweep_due())
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

# --- время заявки в будущем (metis-0604): ожидание не больше --wait, заявка со временем позже now+60 с отклонена -----
_fmt = "%Y-%m-%dT%H:%M:%S%z"
check("serve_wait: заявка недавняя — остаток меньше --wait",
      0 < O.serve_wait({"wait": 100, "time": time.strftime(_fmt, time.localtime(time.time() - 30))}) <= 71)
check("serve_wait: время заявки в будущем не растит ожидание сверх --wait",
      O.serve_wait({"wait": 100, "time": time.strftime(_fmt, time.localtime(time.time() + 3600))}) == 100)
_ok = {"v": 1, "id": "r1", "kind": "serve", "dir": "/x", "wait": 5}
check("check_request: время сейчас — принята",
      O.check_request({**_ok, "time": time.strftime("%Y-%m-%d %H:%M")}, "r1") is None)
check("check_request: время на час вперёд — отклонена (формат P.stamp)",
      O.check_request({**_ok, "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + 3600))}, "r1"))
check("check_request: время на час вперёд — отклонена (формат с секундами и поясом)",
      O.check_request({**_ok, "time": time.strftime(_fmt, time.localtime(time.time() + 3600))}, "r1"))

check("serve_wait: заявка от CLI (время P.stamp) — вычитает прошедшее время",
      O.serve_wait({"wait": 300, "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 120))}) <= 240)
_rc, _q, _rid = role_request("athena-x", APP, "serve")
_t = json.load(open(os.path.join(_q, _rid + ".req.json")))["time"]
os.remove(os.path.join(_q, _rid + ".req.json"))
check("заявка от CLI несёт время с секундами и поясом (ожидание не теряет до минуты)",
      "T" in _t and abs(O._epoch({"time": _t}) - time.time()) < 5, _t)
check("_epoch: минутное время — конец минуты (+59 с), ожидание старых заявок не занижается",
      O._epoch({"time": "2026-10-30 10:00"}) - O._epoch({"time": "2026-10-30 09:59"}) == 60
      and O._epoch({"time": "2026-10-30 10:00"}) - __import__("datetime").datetime(2026, 10, 30, 10, 0).timestamp() == 59)
check("_epoch: оба формата разбираются, мусор и пусто — None",
      O._epoch({"time": "2026-10-30 10:00"}) is not None and O._epoch({"time": "2026-10-30T10:00:00+0300"}) is not None
      and O._epoch({"time": "вчера"}) is None and O._epoch({}) is None)

# --- sweep_quiet (metis-0606, Д-1 argus): сбой sweep посреди прогона не роняет тесты, в журнал — один раз ------------
O.SWEEP_EVERY = 0.2
O._SWEEP_ERR.clear()
_log = os.path.join(STATE, "logs", "outside.jsonl")
_n0 = sum(1 for _ in open(_log))
_real_sweep = O.sweep


def _boom(t=None):
    raise ValueError("битый servers.json")


O.sweep = _boom
try:
    res = O.run_test("20261030-000000-d4d4d4", APP, "nap", "athena-x", None, O.registry(None))
except Exception as e:  # noqa: BLE001 — мутант без try: исключение вышло из run_test
    res = {"state": f"исключение {type(e).__name__}: {e}"}
finally:
    O.sweep = _real_sweep
    O.SWEEP_EVERY = 2
_errs = [json.loads(x) for x in list(open(_log))[_n0:]]
_errs = [x for x in _errs if x.get("kind") == "sweep-error"]
check("sweep падает посреди прогона: тест дошёл, done с кодом 0, в журнале один sweep-error",
      res.get("state") == "done" and res.get("code") == 0 and len(_errs) == 1
      and "битый servers.json" in _errs[0].get("why", ""), (res.get("state"), res.get("code"), _errs))

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
code = ("import sys, json; sys.path.insert(0, %r); import guard as g; "
        "print(json.dumps([g.check_dev_server('pantheon outside serve --wait 120', {}), "
        "g.check_dev_server('pnpm dev', {}) is not None, g.pantheon_cli('pantheon outside test --wait 300', %r)]))"
        % (GUARD_HOOKS, _ROOT))
r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                   env={"HOME": HOME, "PATH": os.environ["PATH"]})
got = json.loads(r.stdout) if r.returncode == 0 else None
check("guard: `pantheon outside serve` — не dev-сервер (pnpm dev — да)", got and got[0] is None and got[1], r.stdout + r.stderr)
check("guard: `pantheon outside test` — не привилегированная команда", got and got[2] == [], got)

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
