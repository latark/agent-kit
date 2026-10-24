#!/usr/bin/env python3
"""Исполнители кода и обёртка `pantheon exec codex` (решение 175, metis-0166 А, 0173 Б) — контракт на заглушке codex.

Запуск: python3 -I plugins/pantheon/tests/test_executors.py  (код выхода 0 — все прошли)
Настоящий Codex не запускается: в PATH — tests/fixtures/codex-stub/codex, сценарий — файлом в CODEX_HOME роли
(обёртка срезает окружение). HOME, PANTHEON_STATE, PANTHEON_HOME, TMPDIR — временные папки. Сценарии — раздел 3
доклада prometheus 16.10 (успех, error, turn.failed, падение посреди хода, ошибка в stderr, лимит, высокий спрос,
«нужен вход», неизвестная сессия, тишина) и тесты 1–5 предложения 0166.
"""
import fcntl
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon и pconfig — только на Python 3.11+

if sys.version_info < (3, 11):  # на системном 3.9 — тем же тестом под найденным 3.11+ (нет — _py311 уже пропустил)
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)])

import tomllib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, "lib", "pantheon.py")
EXE = os.path.join(ROOT, "lib", "executors.py")
STUB = os.path.join(HERE, "fixtures", "codex-stub", "codex")
PROTECTED_PART = os.path.join(ROOT, "roles", "_parts", "protected.part")
HOOK = os.path.join(ROOT, "hooks", "dev-stop-verify.py")
T0 = 1_792_000_000  # «сейчас» для лимита
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{str(detail)[:1500]}]"))


TMP = os.path.realpath(tempfile.mkdtemp(prefix="executors-"))
HOME = os.path.join(TMP, "home")
STATE = os.path.join(TMP, "state")
PH = os.path.join(TMP, "pantheon")
TMPD = os.path.join(TMP, "t")
BIN = os.path.join(TMP, "bin")          # codex-заглушка
GITBIN = os.path.join(TMP, "gitbin")    # git, который пишет argv (тест «нет push»)
GITLOG = os.path.join(TMP, "git-argv.jsonl")
CH = os.path.join(STATE, "codex-dev")
for d in (HOME, STATE, TMPD, BIN, GITBIN, os.path.join(PH, "directions", "demo", "tasks")):
    os.makedirs(d, exist_ok=True)
os.symlink(STUB, os.path.join(BIN, "codex"))
REAL_GIT = shutil.which("git")
with open(os.path.join(GITBIN, "git"), "w") as fh:
    fh.write(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {GITLOG}\nexec {REAL_GIT} \"$@\"\n")
os.chmod(os.path.join(GITBIN, "git"), 0o755)
BASE_PATH = os.environ.get("PATH", "/usr/bin:/bin")
ENV = {"PATH": f"{GITBIN}:{BIN}:{BASE_PATH}", "HOME": HOME, "USER": "tester", "LANG": "C.UTF-8",
       "PANTHEON_HOME": PH, "PANTHEON_STATE": STATE, "PANTHEON_VIEW": os.path.join(TMP, "view"),
       "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "TMPDIR": TMPD,
       # чужие секреты вызывающего — не должны дойти до Codex
       "OPENAI_API_KEY": "sk-host-secret", "GH_TOKEN": "ghp_x", "MY_SECRET": "s", "AWS_ACCESS_KEY_ID": "a",
       "LC_ALL": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1"}


def run(*a, env=None, timeout=120, inp=None):
    e = dict(ENV, **(env or {}))
    e = {k: v for k, v in e.items() if v is not None}
    return subprocess.run([PY311, "-I", CLI, *a], env=e, capture_output=True, text=True, timeout=timeout, input=inp)


def py(code, env=None, timeout=120):
    """Вызов функции executors.py напрямую (add_codex с входом и пробой — у них нет команды pantheon)."""
    pre = ("import importlib.util, sys\n"
           f"spec = importlib.util.spec_from_file_location('ex', {EXE!r})\n"
           "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n")
    e = dict(ENV, **(env or {}))
    e = {k: v for k, v in e.items() if v is not None}
    return subprocess.run([PY311, "-I", "-c", pre + code], env=e, capture_output=True, text=True, timeout=timeout)


def scenario(data):
    os.makedirs(CH, exist_ok=True)
    with open(os.path.join(CH, "stub-scenario.json"), "w") as fh:
        json.dump(data, fh)
    for f in ("stub-exec-n", "stub-calls.jsonl", "stub-child.pid", "stub-self.pid"):
        try:
            os.remove(os.path.join(CH, f))
        except FileNotFoundError:
            pass


def calls(kind=None):
    try:
        got = [json.loads(x) for x in open(os.path.join(CH, "stub-calls.jsonl"))]
    except FileNotFoundError:
        return []
    if kind == "exec":
        return [c for c in got if c["argv"][:1] == ["exec"] and c["stdin"].strip() != "Respond with hello."]
    if kind == "hello":
        return [c for c in got if c["argv"][:1] == ["exec"] and c["stdin"].strip() == "Respond with hello."]
    return got


def cfg():
    try:
        return tomllib.load(open(os.path.join(STATE, "config.toml"), "rb"))
    except FileNotFoundError:
        return {}


def set_cfg(text):
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "config.toml"), "w") as fh:
        fh.write(text)


CODEX_ON = '[executors]\nset = ["claude", "codex"]\n\n[codex]\nenabled = true\n'


def git(cwd, *a, check=True):
    return subprocess.run([REAL_GIT, "-C", cwd, *a], capture_output=True, text=True, check=check)


# репозиторий проекта, удалённый bare и worktree на задачу
MAIN = os.path.join(TMP, "proj")
BARE = os.path.join(TMP, "remote.git")
git(TMP, "init", "-q", "--bare", BARE)
os.makedirs(MAIN)
git(MAIN, "init", "-q", "-b", "epic")
git(MAIN, "config", "user.name", "t")
git(MAIN, "config", "user.email", "t@t")
with open(os.path.join(MAIN, "README.md"), "w") as fh:
    fh.write("проект\n")
with open(os.path.join(MAIN, ".gitignore"), "w") as fh:
    fh.write("ignored/\n")
os.makedirs(os.path.join(MAIN, "plugins", "pantheon", "lib"))
with open(os.path.join(MAIN, "plugins", "pantheon", "lib", "pantheon.py"), "w") as fh:
    fh.write("RULES = {}\n")
os.makedirs(os.path.join(MAIN, "plugins", "guard"))
for rel in ("AGENTS.md", "plugins/guard/guard.py"):  # защищённые пути в базе — для проб переименования
    with open(os.path.join(MAIN, rel), "w") as fh:
        fh.write("x\n" * 50)
git(MAIN, "add", "-A")
git(MAIN, "commit", "-q", "-m", "base")
git(MAIN, "remote", "add", "origin", BARE)
git(MAIN, "push", "-q", "origin", "epic")
BRIEF = os.path.join(TMPD, "brief.md")
with open(BRIEF, "w") as fh:
    fh.write("# Поправить README\n\nДобавь строку.\n\nНе трогай: .claude/, AGENTS.md\n")
_wt_n = [0]


def new_wt():
    _wt_n[0] += 1
    wt = os.path.join(MAIN, ".claude", "worktrees", f"w{_wt_n[0]}")
    git(MAIN, "worktree", "add", "-q", "-b", f"task-{_wt_n[0]}", wt)
    return wt


def head(wt):
    return git(wt, "rev-parse", "HEAD").stdout.strip()


def ev(*items):
    return list(items)


STARTED = {"type": "thread.started", "thread_id": "codex-session-1"}
DONE = {"type": "turn.completed", "usage": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 1}}


def msg(text):
    return {"type": "item.completed", "item": {"type": "agent_message", "text": text}}


def ok_step(write=None, text="Готово: README поправлен.", **kw):
    return dict({"write": write if write is not None else {"README.md": "проект\nстрока\n"},
                 "stdout": [STARTED, msg("проверяю…"), msg(text), DONE]}, **kw)


def exec_codex(wt, env=None, timeout=120):
    return run("exec", "codex", wt, BRIEF, env=env, timeout=timeout)


def main():
    try:
        tests()
    finally:
        shutil.rmtree(TMP, True)
    print(f"{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


def tests():
    # задачи для pick: без поля (auto), закреплённая за codex, за claude
    def task(title, *extra):
        r = run("task", "new", "--direction", "demo", "--title", title, *extra)
        assert r.returncode == 0, r.stderr
        return r.stdout.split()[0]
    t_auto, t_codex, t_claude = task("Механика"), task("За Codex", "--executor", "codex"), \
        task("За Claude", "--executor", "claude")

    # --- 0166-1: установка только с Claude ------------------------------------------------------------------
    r = run("executors")
    check("0166-1: нет записи — набор только claude", r.returncode == 0 and "исполнители: claude" in r.stdout
          and "codex" not in r.stdout.split("\n")[0], r.stdout + r.stderr)
    picks = {k: run("executors", "pick", t_auto, "--kind", k).stdout.strip() for k in ("mechanics", "code", "hard")}
    check("0166-1: auto без Codex в наборе → dev по виду (codex на PATH есть, но не в наборе)",
          picks == {"mechanics": "dev-haiku", "code": "dev-sonnet", "hard": "dev-opus"}, picks)
    r = run("executors", "pick", t_auto)
    check("pick без --kind — вид code → dev-sonnet", r.stdout.strip() == "dev-sonnet", r.stdout + r.stderr)
    r = run("executors", "pick", t_auto, "--kind", "magic")
    check("pick с чужим видом — отказ", r.returncode == 2, r.stdout + r.stderr)
    r = run("executors", "pick", "nope-0001")
    check("pick неизвестной задачи — код 1", r.returncode == 1 and "нет задачи" in r.stderr, r.stderr)

    # --- 0166-4: Claude не удаляется --------------------------------------------------------------------------
    r = run("executors", "--remove", "claude")
    check("0166-4: --remove claude → отказ с понятным текстом, код ≠ 0",
          r.returncode != 0 and "не удаляется" in r.stderr, r.stdout + r.stderr)
    check("Claude не удаляется: набор после отказа — с claude",
          "claude" in (cfg().get("executors") or {}).get("set", ["claude"]))
    r = run("executors", "--remove", "gpt")
    check("--remove неизвестного — отказ", r.returncode == 2, r.stderr)

    # --- Codex нет на PATH ------------------------------------------------------------------------------------
    nopath = {"PATH": f"{GITBIN}:{BASE_PATH}"}
    r = run("executors", "check", env=nopath)
    check("Codex нет: check → код 3, «Codex недоступен», reason «нет на PATH»",
          r.returncode == 3 and "Codex недоступен" in r.stderr and cfg()["codex"]["reason"] == "нет на PATH"
          and cfg()["codex"]["enabled"] is False, r.stdout + r.stderr)
    r = py("sys.exit(m.add_codex(interactive=True, live_probe=True))", env=nopath)
    check("Codex нет: add_codex → инструкция, код 3, набор без codex",
          r.returncode == 3 and "npm install -g @openai/codex" in r.stdout and "Codex не добавлен" in r.stdout
          and (cfg().get("executors") or {}).get("set", ["claude"]) == ["claude"], r.stdout + r.stderr)
    set_cfg(CODEX_ON)
    scenario({})
    wt = new_wt()
    r = exec_codex(wt, env=nopath)
    check("Codex нет: exec → «Codex недоступен», код 3, Codex не запускался",
          r.returncode == 3 and "Codex недоступен" in r.stderr and not calls(), r.stdout + r.stderr)
    set_cfg("")

    # --- входа нет ----------------------------------------------------------------------------------------------
    scenario({"login": 1})
    r = run("executors", "--add", "codex")
    c = cfg()
    check("входа нет: --add codex → код 3, Codex выключен «нет входа», набор без codex, hello не шла",
          r.returncode == 3 and "нет входа" in r.stdout and c["codex"]["enabled"] is False
          and c["codex"]["reason"] == "нет входа" and c.get("executors", {}).get("set", ["claude"]) == ["claude"]
          and not calls("hello"), r.stdout + r.stderr)
    lc = [x for x in calls() if x["argv"][:2] == ["login", "status"]]
    check("вход проверяется `codex login status` с CODEX_HOME роли", lc and lc[0]["codex_home"] == CH, calls())
    r = run("executors", "pick", t_auto, "--kind", "mechanics")
    check("0166-3: Codex сломан (нет входа) → auto mechanics → dev-haiku", r.stdout.strip() == "dev-haiku", r.stdout)

    # --- 0166-2: добавление Codex с проходящей заглушкой ---------------------------------------------------------
    scenario({"version": "codex-cli 0.130.0"})
    r = run("executors", "--add", "codex")
    c = cfg()
    check("0166-2: --add codex с проходящей заглушкой → набор [claude, codex], Codex включён",
          r.returncode == 0 and c["executors"]["set"] == ["claude", "codex"] and c["codex"]["enabled"] is True
          and c["codex"]["reason"] == "", r.stdout + r.stderr)
    check("[codex] version, checked, home записаны", c["codex"].get("version") == "0.130.0" and c["codex"].get("checked")
          and c["codex"].get("home") == CH, c)
    check("CODEX_HOME роли 0700, config.toml в нём 0600",
          stat.S_IMODE(os.stat(CH).st_mode) == 0o700
          and stat.S_IMODE(os.stat(os.path.join(CH, "config.toml")).st_mode) == 0o600)
    check("общий ~/.codex не создан и не тронут", not os.path.exists(os.path.join(HOME, ".codex")))
    hc = calls("hello")
    a = hc[0]["argv"] if hc else []
    check("hello-проба: «Respond with hello.» через stdin, флаги доклада, пустая временная папка, не worktree",
          len(hc) == 1 and a[:2] == ["exec", "--json"] and "--ephemeral" in a and a[-1] == "-"
          and "features.plugins=false" in a and "features.remote_plugin=false" in a and "project_doc_max_bytes=0" in a
          and a.count("--skip-git-repo-check") == 1 and not os.listdir(TMPD + "/") == []
          and os.path.basename(hc[0]["cwd"]).startswith("tmp-codex-hello-"), hc)
    check("hello-папка убрана после пробы", not [x for x in os.listdir(TMPD) if x.startswith("tmp-codex-hello-")])
    check("0166-2: Codex выводится в «Подключённые приложения» — напоминание GHSA-gqqj", "GHSA-gqqj" in r.stdout,
          r.stdout)
    r = run("executors")
    check("pantheon executors: набор и «Codex: включён»", "исполнители: claude, codex" in r.stdout
          and "Codex: включён" in r.stdout, r.stdout)
    picks = {k: run("executors", "pick", t_auto, "--kind", k).stdout.strip() for k in ("mechanics", "code", "hard")}
    check("0166-2: auto mechanics и code → codex-dev, hard → dev-opus",
          picks == {"mechanics": "codex-dev", "code": "codex-dev", "hard": "dev-opus"}, picks)
    r = run("executors", "pick", t_claude, "--kind", "mechanics")
    check("executor claude → dev по виду даже при доступном Codex", r.stdout.strip() == "dev-haiku", r.stdout)
    r = run("executors", "pick", t_codex, "--kind", "hard")
    check("executor codex при доступном Codex → codex-dev", r.stdout.strip() == "codex-dev" and not r.stderr, r.stderr)

    # --- 0166-3: Codex сломан hello-пробой (turn.failed) -------------------------------------------------------
    scenario({"hello": {"stdout": [STARTED, {"type": "turn.failed", "error": {"message": "model access denied"}}],
                        "rc": 1}})
    r = run("executors", "check")
    c = cfg()
    check("0166-3: hello-проба turn.failed → код 3, Codex выключен (reason hello-проба)",
          r.returncode == 3 and c["codex"]["enabled"] is False and c["codex"]["reason"].startswith("hello-проба")
          and "Codex недоступен" in r.stderr, r.stdout + r.stderr)
    r = run("executors", "pick", t_auto, "--kind", "code")
    check("0166-3: та же задача (auto, code) → dev-sonnet", r.stdout.strip() == "dev-sonnet", r.stdout)
    # --- 0166-5: executor codex при выключенном Codex → Claude и предупреждение ---------------------------------
    r = run("executors", "pick", t_codex, "--kind", "code")
    check("0166-5: executor codex при выключенном → dev-sonnet и предупреждение, не ошибка",
          r.returncode == 0 and r.stdout.strip() == "dev-sonnet" and "предупреждение" in r.stderr, r.stdout + r.stderr)
    r = run("executors")
    check("pantheon executors показывает, почему Codex выключен", "Codex: Codex выключен: hello-проба" in r.stdout,
          r.stdout)
    scenario({"hello": {"stdout": [STARTED, msg("hi there"), DONE]}})
    r = run("executors", "check")
    check("hello-проба: ответ без hello → unexpected_output, выключен", r.returncode == 3
          and "unexpected_output" in cfg()["codex"]["reason"], r.stderr)
    scenario({"hello": {"stdout": [STARTED], "hang": 30}})
    t = time.time()
    r = run("executors", "check", env={"PANTHEON_CODEX_HELLO_S": "1"})
    check("hello-проба: молчит дольше предела → timed_out, выключен, быстро",
          r.returncode == 3 and "timed_out" in cfg()["codex"]["reason"] and time.time() - t < 20, r.stderr)
    scenario({"hello": {"stderr": ["OAuth failed: invalid_grant"], "rc": 1}})
    r = run("executors", "check")
    check("hello-проба: признак входа → reason «нужен вход»", cfg()["codex"]["reason"] == "нужен вход", cfg())

    # --- add_codex с входом и живой пробой ----------------------------------------------------------------------
    set_cfg("")
    probe_ok = os.path.join(TMP, "probe-ok.sh")
    probe_bad = os.path.join(TMP, "probe-bad.sh")
    open(probe_ok, "w").write('#!/bin/bash\necho "== N"\necho "CH=$CODEX_HOME"\n'
                              'echo "итог: N=0 W=0 D=1 (0 — работает и держит границу)"\n')
    open(probe_bad, "w").write('#!/bin/bash\necho "итог: N=0 W=1 D=0 (…)"\n')
    scenario({"login": 1, "device_auth": 0})
    r = py(f"m.PROBE = {probe_ok!r}\nsys.exit(m.add_codex(interactive=True, live_probe=True))")
    dev = [x for x in calls() if x["argv"][:2] == ["login", "--device-auth"]]
    check("add_codex(interactive): `codex login --device-auth` с CODEX_HOME роли, без ключей хоста",
          dev and dev[0]["codex_home"] == CH and dev[0]["openai_api_key"] == "", calls())
    check("add_codex(live_probe): итог пробы в выводе, CODEX_HOME роли передан, набор [claude, codex], код 0",
          r.returncode == 0 and "итог: N=0 W=0 D=1" in r.stdout and f"CH={CH}" in r.stdout
          and cfg()["executors"]["set"] == ["claude", "codex"], r.stdout + r.stderr)
    set_cfg("")
    scenario({})
    r = py(f"m.PROBE = {probe_bad!r}\nsys.exit(m.add_codex(interactive=False, live_probe=True))")
    check("add_codex: живая проба W≠0 → не добавлен, код 3, итог в выводе",
          r.returncode == 3 and "итог: N=0 W=1 D=0" in r.stdout
          and (cfg().get("executors") or {}).get("set", ["claude"]) == ["claude"], r.stdout + r.stderr)
    scenario({"device_auth": 1, "login": 1})
    r = py("sys.exit(m.add_codex(interactive=True, live_probe=False))")
    check("add_codex: вход не выполнен → код 3, не добавлен", r.returncode == 3 and "вход не выполнен" in r.stdout,
          r.stdout)

    # --- обёртка: успех ---------------------------------------------------------------------------------------------
    set_cfg(CODEX_ON)
    scenario({"exec": [ok_step()]})
    wt = new_wt()
    h0 = head(wt)
    remote0 = git(BARE, "show-ref").stdout
    open(GITLOG, "w").close()
    r = exec_codex(wt)
    lines = r.stdout.splitlines()
    m = re.match(r"^исполнитель: codex 0\.130\.0, лог: (\S+)$", lines[0]) if lines else None
    check("успех: код 0, первая строка «исполнитель: codex <версия>, лог: <путь>»", r.returncode == 0 and m,
          r.stdout + r.stderr)
    log = m.group(1) if m else ""
    check("лог JSONL — в $TMPDIR/tmp-codex-<ветка>/ и содержит события",
          log.startswith(os.path.join(TMPD, "tmp-codex-task-")) and '"turn.completed"' in open(log).read()
          if log else False, log)
    rep = next((x.split(": ", 1)[1] for x in lines if x.startswith("отчёт: ")), "")
    check("отчёт — последнее agent_message, не промежуточное",
          rep and open(rep).read() == "Готово: README поправлен.", rep)
    sha = next((x.split(": ", 1)[1] for x in lines if x.startswith("коммит: ")), "")
    check("коммит в worktree: HEAD = выведенный sha, родитель — снимок до запуска",
          sha and head(wt) == sha and git(wt, "rev-parse", "HEAD~1").stdout.strip() == h0, r.stdout)
    tr = git(wt, "log", "-1", "--format=%(trailers:key=Executor,valueonly)").stdout.strip()
    check("трейлер Executor: codex", tr == "codex", git(wt, "log", "-1", "--format=%B").stdout)
    ec = calls("exec")
    a = ec[0]["argv"] if ec else []
    check("запуск: codex exec --json --ephemeral --sandbox workspace-write … -",
          a[:5] == ["exec", "--json", "--ephemeral", "--sandbox", "workspace-write"] and a[-1] == "-", a)
    check("без -o, без network_access, без --dangerously…, --skip-git-repo-check не больше раза",
          "-o" not in a and not any("network_access" in x for x in a) and not any("dangerously" in x for x in a)
          and a.count("--skip-git-repo-check") <= 1 and "--output-last-message" not in a, a)
    check("поручение — через stdin, cwd — worktree", ec and ec[0]["stdin"] == open(BRIEF).read()
          and os.path.realpath(ec[0]["cwd"]) == os.path.realpath(wt), ec)
    names = ec[0]["env"] if ec else []
    bad = [n for n in names if re.search(r"key|secret|token", n, re.I) and n not in ("OPENAI_API_KEY", "CODEX_API_KEY")]
    check("в env Codex нет имён key/secret/token, OPENAI_API_KEY пуст, CODEX_API_KEY нет",
          ec and not bad and ec[0]["openai_api_key"] == "" and "CODEX_API_KEY" not in names and "MY_SECRET" not in names,
          (bad, names))
    allowed = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TMPDIR", "CODEX_HOME", "OPENAI_API_KEY",
               "CODEX_API_KEY", "__CF_USER_TEXT_ENCODING"}
    extra = [n for n in names if n not in allowed and not n.startswith("LC_")]
    check("env Codex — только белый список (+ CODEX_HOME роли)", ec and not extra and ec[0]["codex_home"] == CH, extra)
    gl = open(GITLOG).read().splitlines()
    check("обёртка не делает push (argv git) и удалённый bare не изменился",
          gl and not [x for x in gl if re.search(r"(^|\s)push(\s|$)", x)] and git(BARE, "show-ref").stdout == remote0,
          gl)
    check("дерево после коммита чистое", git(wt, "status", "--porcelain").stdout == "")

    scenario({"exec": [ok_step({"b.txt": "b"})]})
    wt = new_wt()
    r = exec_codex(wt, env={"CODEX_API_KEY": "ck-1"})
    ec = calls("exec")
    check("CODEX_API_KEY задан у вызова — проходит к Codex", ec and ec[0]["codex_api_key"] == "ck-1", ec)

    # --- Codex закоммитил сам → трейлер всё равно есть -----------------------------------------------------------
    scenario({"exec": [ok_step({"c.txt": "c"}, commit="codex: своё"), ]})
    wt = new_wt()
    h0 = head(wt)
    r = exec_codex(wt)
    body = git(wt, "log", "-1", "--format=%B").stdout
    check("Codex закоммитил сам → один коммит обёртки поверх снимка, трейлер Executor: codex, его заголовок в теле",
          r.returncode == 0 and git(wt, "rev-parse", "HEAD~1").stdout.strip() == h0 and "Executor: codex" in body
          and "codex: своё" in body and git(wt, "show", "HEAD:c.txt").stdout == "c", r.stdout + r.stderr + body)

    # --- грязный worktree до запуска — отказ (чужие правки не уходят под трейлер Codex) ------------------------------
    def lock_free():
        with open(os.path.join(STATE, "locks", "codex-dev.lock"), "a") as lk:
            try:
                fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                return False

    def dirty_case(name, prep, want):
        scenario({"exec": [ok_step({"src/codex.txt": "c"})]})
        wt = new_wt()
        prep(wt)
        h0 = head(wt)
        r = exec_codex(wt)
        check(name, r.returncode == 2 and want in r.stderr and "закоммить или убери до запуска Codex" in r.stderr
              and not calls() and head(wt) == h0 and lock_free()
              and not os.path.exists(os.path.join(wt, "src", "codex.txt")), (r.returncode, r.stdout, r.stderr, calls()))

    def write(wt, rel, text="x\n", mode="w"):
        os.makedirs(os.path.dirname(os.path.join(wt, rel)) or wt, exist_ok=True)
        with open(os.path.join(wt, rel), mode) as fh:
            fh.write(text)
    dirty_case("грязный отслеживаемый файл → код 2, Codex не запускался (ни одного вызова), коммита нет, замок снят",
               lambda wt: write(wt, "README.md", "правка человека\n", "a"), "worktree не чистый: README.md")
    dirty_case("отслеживаемый в индексе (git add) → код 2",
               lambda wt: (write(wt, "README.md", "в индексе\n", "a"), git(wt, "add", "README.md")),
               "worktree не чистый: README.md")
    dirty_case("неотслеживаемый файл → код 2", lambda wt: write(wt, "notes/new.txt"), "worktree не чистый: notes/new.txt")
    dirty_case("больше пяти путей → первые пять и «и ещё N»",
               lambda wt: [write(wt, f"n{i}.txt") for i in range(7)], "n0.txt, n1.txt, n2.txt, n3.txt, n4.txt и ещё 2")
    scenario({"exec": [ok_step()]})
    wt = new_wt()
    write(wt, "ignored/cache.bin", "кэш")
    r = exec_codex(wt)
    check("только игнорируемое (как node_modules) → запуск идёт, коммит без игнорируемого",
          r.returncode == 0 and len(calls("exec")) == 1 and "ignored/cache.bin" not in
          git(wt, "show", "--name-only", "--format=", "HEAD").stdout, r.stdout + r.stderr)

    # --- нет изменений --------------------------------------------------------------------------------------------
    scenario({"exec": [ok_step({})]})
    wt = new_wt()
    h0 = head(wt)
    r = exec_codex(wt)
    check("Codex ничего не изменил → код 1, коммита нет", r.returncode == 1 and "ничего не изменил" in r.stderr
          and head(wt) == h0, r.stdout + r.stderr)

    # --- защищённые пути --------------------------------------------------------------------------------------------
    scenario({"exec": [ok_step({".claude/settings.json": "{}", "src/ok.txt": "ok", "ignored/AGENTS.md": "x"})]})
    wt = new_wt()
    h0 = head(wt)
    r = exec_codex(wt)
    check("дифф в защищённом пути → отказ, пути в выводе, без коммита",
          r.returncode == 1 and ".claude/settings.json" in r.stderr and "ignored/AGENTS.md" in r.stderr
          and head(wt) == h0, r.stdout + r.stderr)
    check("защищённые пути: ничего не откатано", os.path.exists(os.path.join(wt, ".claude", "settings.json"))
          and os.path.exists(os.path.join(wt, "src", "ok.txt")))
    scenario({"exec": [ok_step({"AGENTS.md": "правила"}, commit="codex: agents")]})
    wt = new_wt()
    h0 = head(wt)
    r = exec_codex(wt)
    check("защищённый путь в собственном коммите Codex → отказ, его коммит не тронут",
          r.returncode == 1 and "AGENTS.md" in r.stderr and head(wt) != h0
          and git(wt, "log", "-1", "--format=%s").stdout.strip() == "codex: agents", r.stdout + r.stderr)
    scenario({"exec": [ok_step({"plugins/pantheon/lib/pantheon.py": 'RULES = {"autoMode": {}}\n'})]})
    wt = new_wt()
    r = exec_codex(wt)
    check("правила окон в pantheon.py (autoMode) → отказ", r.returncode == 1 and "правила окон" in r.stderr, r.stderr)
    scenario({"exec": [ok_step({"plugins/pantheon/lib/pantheon.py": 'X = 1\n'})]})
    wt = new_wt()
    r = exec_codex(wt)
    check("обычная правка pantheon.py без правил окон — коммит", r.returncode == 0, r.stderr)
    # переименование защищённого: у git mv старое имя тоже изменение (замечание argus к PR #37)
    for src, dst in (("AGENTS.md", "NOTES.md"), ("plugins/guard/guard.py", "plugins/other_guard.py")):
        for own in (False, True):
            scenario({"exec": [ok_step({}, mv=[[src, dst]], **({"commit": "codex: mv"} if own else {}))]})
            wt = new_wt()
            h0 = head(wt)
            r = exec_codex(wt)
            where = "собственным коммитом Codex" if own else "в индексе"
            check(f"git mv {src} → {dst} {where} → отказ, старое имя в выводе, коммита обёртки нет",
                  r.returncode == 1 and f"  {src}" in r.stderr and "Executor: codex" not in
                  git(wt, "log", "-1", "--format=%B").stdout and (head(wt) == h0) != own, r.stdout + r.stderr)
    scenario({"exec": [ok_step({}, mv=[["README.md", "docs/README.md"]])]})
    wt = new_wt()
    r = exec_codex(wt)
    check("git mv обычного файла — коммит с обоими именами", r.returncode == 0 and
          git(wt, "show", "--name-status", "--no-renames", "--format=", "HEAD").stdout.split() ==
          ["D", "README.md", "A", "docs/README.md"], r.stdout + r.stderr)

    # --- сценарии ошибок (раздел 3 доклада) ------------------------------------------------------------------------
    def fail_case(name, step, want_rc, want_text, n_calls=1, env=None, extra=None):
        scenario({"exec": step if isinstance(step, list) else [step]})
        wt = new_wt()
        h0 = head(wt)
        r = exec_codex(wt, env=env)
        ok = r.returncode == want_rc and want_text in r.stderr and len(calls("exec")) == n_calls and head(wt) == h0
        if extra:
            ok = ok and extra(r)
        check(name, ok, (r.returncode, r.stdout, r.stderr, len(calls("exec"))))
        return r

    fail_case("2 error без протокола (код 1) → отказ с текстом", {"stdout": [{"type": "error", "message": "boom"}],
                                                                   "rc": 1}, 1, "boom")
    fail_case("3 turn.failed → отказ с текстом",
              {"stdout": [STARTED, {"type": "turn.failed", "error": {"message": "the model rejected the request"}}],
               "rc": 1}, 1, "the model rejected the request")
    fail_case("turn.failed при коде 0 — всё равно отказ (строже Paperclip)",
              {"write": {"x.txt": "x"},
               "stdout": [STARTED, {"type": "turn.failed", "error": {"message": "model access denied"}}], "rc": 0},
              1, "model access denied", extra=lambda r: "не закоммичено: x.txt" in r.stderr)
    crash = {"stdout": [STARTED, msg("Starting the task.")], "rc": 1,
             "stderr": ["2026-07-23T22:58:56.007042Z ERROR rmcp::transport::worker: worker quit with fatal: Transport "
                        "channel closed, when UnexpectedContentType(Some(\"text/plain\"))"]}
    scenario({"exec": [crash, ok_step()]})
    wt = new_wt()
    r = exec_codex(wt)
    check("4 падение посреди хода → один повтор, второй успешен — коммит",
          r.returncode == 0 and len(calls("exec")) == 2 and "один повтор" in r.stderr and "первая попытка:" in r.stdout,
          (r.stdout, r.stderr))
    fail_case("4 падение посреди хода дважды → отказ после одного повтора", [crash, crash], 1, "rmcp", n_calls=2)
    fail_case("5 ошибка только в stderr → причина — первая значимая строка, шум пропущен",
              {"stderr": ["YOLO mode is enabled. All tool calls will be automatically approved.",
                          'Error: unexpected status 400 Bad Request: {"error":{"message":"The requested model '
                          "'gpt-5.3-codex-spark' does not exist.\",\"code\":\"model_not_found\"}}"], "rc": 1},
              1, "400 Bad Request", extra=lambda r: "YOLO" not in r.stderr)
    now_env = {"PANTHEON_NOW": str(T0)}
    base = datetime.fromtimestamp(T0)
    want = base.replace(hour=23, minute=31, second=0, microsecond=0)
    if want <= base:
        want += timedelta(days=1)
    fail_case("6 лимит «try again at 11:31 PM» → код 3, Codex выключен до этого времени",
              {"stdout": [STARTED, {"type": "turn.failed", "error": {"message":
                  "You've hit your usage limit for GPT-5.3-Codex-Spark. Switch to another model now, or try again at "
                  "11:31 PM."}}], "rc": 1}, 3, "Codex недоступен до", env=now_env,
              extra=lambda r: cfg()["codex"].get("disabled_until") == want.strftime("%Y-%m-%dT%H:%M")
              and cfg()["codex"]["reason"] == "лимит" and cfg()["codex"]["enabled"] is True)
    scenario({"exec": [ok_step()]})
    wt = new_wt()
    r = exec_codex(wt, env=now_env)
    check("лимит: до времени — exec «Codex недоступен», Codex не запускается",
          r.returncode == 3 and "Codex недоступен" in r.stderr and not calls("exec"), r.stderr)
    r = run("executors", "pick", t_auto, "--kind", "mechanics", env=now_env)
    check("лимит: до времени auto → dev-haiku", r.stdout.strip() == "dev-haiku", r.stdout)
    later = {"PANTHEON_NOW": str(want.timestamp() + 60)}
    r = run("executors", "pick", t_auto, "--kind", "mechanics", env=later)
    check("лимит: время наступило — Codex снова доступен (auto → codex-dev)", r.stdout.strip() == "codex-dev", r.stdout)
    set_cfg(CODEX_ON)
    fail_case("7 высокий спрос → код 3, Codex отдыхает 30 мин",
              {"stdout": [{"type": "error", "message": "Error running remote compact task: We're currently "
                           "experiencing high demand, which may cause temporary errors."}], "rc": 1},
              3, "Codex недоступен до", env=now_env,
              extra=lambda r: cfg()["codex"].get("disabled_until") ==
              datetime.fromtimestamp(T0 + 1800).strftime("%Y-%m-%dT%H:%M")
              and cfg()["codex"]["reason"] == "высокая нагрузка")
    for phrase in ("provider error: refresh_token_reused", "OAuth failed: refresh token has expired",
                   "OAuth failed: invalid_grant", "credential refresh returned 401 Unauthorized"):
        set_cfg(CODEX_ON)
        # структура «падение посреди хода», но признак входа — без повтора
        fail_case(f"8 «нужен вход» ({phrase.split(': ')[-1]}) → Codex выключен, без повторов, код 3",
                  {"stdout": [STARTED], "stderr": [phrase], "rc": 1}, 3, "нужен вход",
                  extra=lambda r: cfg()["codex"]["enabled"] is False and cfg()["codex"]["reason"] == "нужен вход")
    set_cfg(CODEX_ON)
    fail_case("9 неизвестная сессия (stderr) → отказ с текстом, без повтора",
              {"stderr": ["Error: thread/resume: thread/resume failed: no rollout found for thread id "
                          "d448e715-7607-4bcc-91fc-7a3c0c5a9632"], "rc": 1}, 1, "no rollout found")
    t = time.time()
    r = fail_case("10 тишина → SIGTERM группе, отказ «тишина», без повтора",
                  {"stdout": [STARTED], "hang": 120, "child": True}, 1, "тишина",
                  env={"PANTHEON_CODEX_IDLE_S": "1"})
    check("тишина: остановлено быстро (не ждали 120 с)", time.time() - t < 30)
    try:
        pid = int(open(os.path.join(CH, "stub-child.pid")).read())
        dead = False
        for _ in range(30):  # ps в песочнице запрещён — проверка сигналом 0; осиротевший sleep подбирает launchd
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                dead = True
                break
            time.sleep(0.1)
    except (OSError, ValueError):
        dead = False
    check("тишина: дочерний процесс Codex (вся группа) тоже остановлен", dead)
    fail_case("общий предел: вывод идёт, но время вышло → остановлен", {"stdout": [STARTED], "drip": 0.2}, 1,
              "общий предел", env={"PANTHEON_CODEX_IDLE_S": "10", "PANTHEON_CODEX_TIMEOUT_S": "1"})
    fail_case("код 0 без turn.completed → отказ", {"stdout": [STARTED, msg("половина")], "rc": 0}, 1,
              "без конечного события")

    # --- замок -------------------------------------------------------------------------------------------------------
    scenario({"exec": [ok_step()]})
    wt = new_wt()
    os.makedirs(os.path.join(STATE, "locks"), exist_ok=True)
    with open(os.path.join(STATE, "locks", "codex-dev.lock"), "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = exec_codex(wt)
    check("замок: другой запуск держит CODEX_HOME → «занят» без ожидания, Codex не запускался",
          r.returncode == 4 and "занят" in r.stderr and not calls("exec"), r.stderr)

    # --- обёртку остановили сигналом: Codex не работает дальше без неё (замечание argus к PR #37) -------------------
    def alive(pid):
        try:
            os.kill(pid, 0)  # ps в песочнице запрещён
            return True
        except ProcessLookupError:
            return False

    # ignore_term: заглушка и её дочерний не слушают SIGTERM — гасит только добивающий SIGKILL группе (ревью argus)
    for sig, ign in ((signal.SIGTERM, False), (signal.SIGHUP, False), (signal.SIGINT, False), (signal.SIGTERM, True)):
        set_cfg(CODEX_ON)
        scenario({"exec": [{"write": {"half.txt": "x"}, "stdout": [STARTED], "child": True, "hang": 120,
                            "ignore_term": ign}]})
        wt = new_wt()
        h0 = head(wt)
        e = {k: v for k, v in ENV.items() if v is not None}
        if ign:
            e["PANTHEON_CODEX_GRACE_S"] = "1"
        p = subprocess.Popen([PY311, "-I", CLI, "exec", "codex", wt, BRIEF], env=e, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        pidf, selff = os.path.join(CH, "stub-child.pid"), os.path.join(CH, "stub-self.pid")
        for _ in range(200):
            if os.path.exists(selff) and open(selff).read().strip():
                break
            time.sleep(0.05)
        child, stub = int(open(pidf).read()), int(open(selff).read())
        t = time.time()
        p.send_signal(sig)
        so, se = p.communicate(timeout=60)
        dead = False
        for _ in range(50):
            if not alive(child) and not alive(stub):
                dead = True
                break
            time.sleep(0.1)
        if not dead:
            for x in (child, stub):
                try:
                    os.kill(x, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        free = True
        with open(os.path.join(STATE, "locks", "codex-dev.lock"), "a") as lk:
            try:
                fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                free = False
        name = signal.Signals(sig).name + (" (Codex не слушает SIGTERM — нужен SIGKILL)" if ign else "")
        check(f"{name} обёртке → код 1, «прервано: Codex остановлен, изменения не закоммичены»",
              p.returncode == 1 and "прервано" in se and "Codex остановлен, изменения не закоммичены" in se
              and time.time() - t < 30, (p.returncode, so, se))
        check(f"{name} обёртке → группа Codex мертва (заглушка и её дочерний), коммита нет, замок снят",
              dead and head(wt) == h0 and free, (dead, head(wt) == h0, free))

    # --- вызов --------------------------------------------------------------------------------------------------------
    r = run("exec", "codex", TMP, BRIEF)
    check("exec не в папке git → код 2", r.returncode == 2, r.stderr)
    r = run("exec", "claude", TMP, BRIEF)
    check("exec не codex → справка, код 2", r.returncode == 2, r.stderr)
    r = run("help")
    check("справка pantheon: строки executors и exec codex", "pantheon executors" in r.stdout
          and "pantheon exec codex <worktree> <файл поручения>" in r.stdout)

    # --- список защищённых путей = roles/_parts/protected.part ----------------------------------------------------------
    import importlib.util
    spec = importlib.util.spec_from_file_location("ex_t", EXE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    part = open(PROTECTED_PART, encoding="utf-8").read()
    missing = [p for p in m.PROTECTED_ANY + m.PROTECTED_ROOT if f"`{p}`" not in part]
    in_part = set(re.findall(r"`([^` ]+)`", part)) - {"plugins/pantheon/lib/pantheon.py", ".claude/settings.local.json",
                                                        "sandbox_build"}
    lost = sorted(in_part - set(m.PROTECTED_ANY + m.PROTECTED_ROOT))
    check("защищённые пути обёртки совпадают с protected.part", not missing and not lost, (missing, lost))
    cases = {".claude/settings.json": True, "sub/.codex/config.toml": True, "AGENTS.md": True, "docs/CLAUDE.md": True,
             "settings.local.json": True, ".github/workflows/ci.yml": True, "plugins/guard/hooks/guard.py": True,
             "plugins/x/hooks/a.py": True, "plugins/pantheon/roles/a.tmpl": True, ".pantheon-verify": True,
             "README.md": False, "docs/plugins/guard/x.md": False, "src/app.py": False, ".github/ISSUE.md": False,
             "plugins/pantheon/lib/executors.py": False, "plugins/pantheon/lib/window_rules.py": True,
             "plugins/pantheon/lib/merge.py": True, "plugins/pantheon/lib/merge.pyc": False}
    wrong = {p: v for p, v in cases.items() if m.protected_hit(p) != v}
    check("защищённые пути: глубина и шаблоны", not wrong, wrong)
    fresh = os.path.join(TMP, "fresh")
    os.makedirs(os.path.join(fresh, "plugins", "pantheon", "lib"))
    git(fresh, "init", "-q")
    git(fresh, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "0")
    with open(os.path.join(fresh, "plugins", "pantheon", "lib", "pantheon.py"), "w") as fh:
        fh.write('D = {"permissions": 1}\n')
    check("правила окон: новый неотслеживаемый pantheon.py тоже смотрится", m.window_rules_hit(fresh, "HEAD"))
    # песочница окон (metis-0393): всё, что пишет sandbox_build, — и excludedCommands, и списки *_EXCLUDED
    check("песочница окон: строка с excludedCommands — защита",
          bool(m.WINDOW_WORDS.search('HQ_X = ["pantheon alert *"]  # excludedCommands'))
          and bool(m.WINDOW_WORDS.search('HQ_EXCLUDED = ["pantheon alert *"]'))
          and not m.WINDOW_WORDS.search('HQ_X = ["pantheon alert *"]'))

    # --- Stop-хук: запуск Codex — правка ----------------------------------------------------------------------------------
    spec = importlib.util.spec_from_file_location("dev_stop", HOOK)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    check("dev-stop-verify: `pantheon exec codex …` — правка (BASH_WRITES)",
          h.BASH_WRITES.search("pantheon exec codex /w \"$TMPDIR/tmp-codex-b/brief.md\"")
          and h.BASH_WRITES.search("cd /w && ~/.local/bin/pantheon exec codex /w b.md")
          and not h.BASH_WRITES.search("pantheon executors"))


if __name__ == "__main__":
    main()
