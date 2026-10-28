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
if tail in (["run", "test"], ["run", "check"]):
    body = json.load(open("package.json"))["scripts"][tail[1]]
    os.execv("/bin/sh", ["/bin/sh", "-c", body])
if tail == ["run", "lint"] or cmd[1:2] in (["ci"], ["install"]):
    print("ok", cmd)
    os._exit(0)
os.execvp(cmd[0], cmd)
''' % REC)
os.chmod(FAKE, 0o755)
O.SANDBOX_EXEC = FAKE
O.HEAVY = None
O.READY_SEC = 15
O.KILL_WAIT = 2


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
PKG = {"name": "app", "scripts": {"dev": "next dev", "bad": "x", "slow": "x", "lint": "x"}}


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
check("профиль: Связка ключей", "com.apple.SecurityServer" in prof and "/Library/Keychains" in prof)
check("профиль: порты браузеров и прокси",
      all(f'(remote ip "*:{p}")' in prof for p in (9222, 9333, 9334, 9339, 6152, 6153)) and '"*:9340"' not in prof)
check("профиль: запись в STATE закрыта", f'(subpath "{STATE}")' in prof.split("(deny file-write*\n")[1])
check("профиль: .git/config папок реестра", "\\.git/(config|hooks)" in prof)
wsec = prof.split("(deny file-write*\n")[1]
check("профиль: запись в ~/.nvm, ~/.npmrc, ~/.claude и кэши окон закрыта",
      all(x in wsec for x in ('/.nvm")', '/.npmrc")', '/.claude")', '/Library/Caches/pantheon-sandbox")')), wsec)
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


before = len(calls())
rc, q, rid = role_request("athena-x", APP, "serve", "--minutes", "5")
run_pass()
res = O.load_result(q, rid) or {}
port = res.get("port") or 0
check("сервер: адрес http://127.0.0.1:<3200–3299>", res.get("state") == "serving" and 3200 <= port < 3300
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
