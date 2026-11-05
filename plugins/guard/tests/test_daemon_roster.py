#!/usr/bin/env python3
"""Правило daemon-roster (metis-0871): реестр демона Claude Code ~/.claude/daemon/roster.json агентам целиком не читать.

Запуск: python3 -I plugins/guard/tests/test_daemon_roster.py   (код выхода 0 — все прошли)
HOME подменён временной папкой, реестр — подставной файл с выдуманными ключами. Проверяет: Read, Grep и Bash по файлу
у субагента и окна роли — отказ правилом daemon-roster с подсказкой `pantheon roster`; безопасный путь `pantheon roster`
guard пропускает, и его вывод (настоящий CLI pantheon на том же HOME) ключей не содержит. Bash — по схеме metis-0823:
имя файла среди слов команды, во входном перенаправлении, код интерпретатору из stdin и неразборная команда — отказ;
текст коммита (-m, -F - из heredoc), задачи, echo и шаблон grep/rg, Glob имён и сессия владельца без роли — без
отказа. Имена собраны склейкой, чтобы команды прогона этого файла не задевали правило живого хука.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="guard-roster-"))
atexit.register(shutil.rmtree, ROOT, True)
HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(os.path.dirname(HERE), "hooks", "guard.py")
SHIM = os.path.join(HERE, "_guard_shim.py")
PANTHEON_RUN = os.path.join(os.path.dirname(os.path.dirname(HERE)), "pantheon", "lib", "run.py")
SUB_TIMEOUT = 60
RULE = "Правило daemon-roster"
HINT = "pantheon roster"
NAME = "roster" + ".json"
DAEMON = "dae" + "mon"
SECRETS = ("rv-SECRET-a1b2c3", "pty-SECRET-d4e5f6")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:500]}]"))


HOME = os.path.join(ROOT, "home")
APP = os.path.join(HOME, "projects", "app")
DDIR = os.path.join(HOME, ".claude", DAEMON)
ROSTER = os.path.join(DDIR, NAME)
for d in (APP, DDIR, os.path.join(HOME, ".local", "state", "pantheon"), os.path.join(ROOT, "tmp")):
    os.makedirs(d, exist_ok=True)
with open(ROSTER, "w") as fh:
    json.dump({"updatedAt": 1_792_000_000_000, "workers": {"abcd1234": {
        "pid": 4242, "startedAt": 1_791_999_000_000, "rvAuth": SECRETS[0], "ptyAuth": SECRETS[1]}}}, fh)
open(os.path.join(DDIR, "other.log"), "w").close()
LINK = os.path.join(ROOT, "tmp", "r.json")
os.symlink(ROSTER, LINK)


def run(tool, tool_input, role="dev-opus", sub=True, window=None):
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": APP,
             "session_id": "s-test", "tool_use_id": "toolu_" + uuid.uuid4().hex}
    if role:
        event["agent_type"] = role
    if sub:
        event["agent_id"] = "a1"
    env = {"HOME": HOME, "PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": APP, "TMPDIR": "/nonexistent-tmp"}
    if window:
        env["PANTHEON_ROLE"] = window
    r = subprocess.run([sys.executable, "-I", SHIM, GUARD], input=json.dumps(event), capture_output=True, text=True,
                       env=env, timeout=SUB_TIMEOUT)
    return r.stdout + (f"\n[код {r.returncode}] {r.stderr}" if r.returncode else "")


B = lambda cmd: ("Bash", {"command": cmd})  # noqa: E731
deny = [
    ("Read файла", ("Read", {"file_path": ROSTER}), {}),
    ("Read через ~", ("Read", {"file_path": f"~/.claude/{DAEMON}/{NAME}"}), {}),
    ("Read через симлинк", ("Read", {"file_path": LINK}), {}),
    ("Grep по файлу", ("Grep", {"pattern": "Auth", "path": ROSTER}), {}),
    ("Grep по папке daemon", ("Grep", {"pattern": "rvAuth", "path": DDIR}), {}),
    ("cat файла", B(f"cat ~/.claude/{DAEMON}/{NAME}"), {}),
    ("jq по файлу", B(f"jq '.workers' \"$HOME/.claude/{DAEMON}/{NAME}\""), {}),
    ("python3 -c open файла", B(f"python3 -c \"import json,os; print(json.load(open(os.path.expanduser("
                                f"'~/.claude/{DAEMON}/{NAME}'))))\""), {}),
    ("cd в папку && cat", B(f"cd ~/.claude/{DAEMON} && cat {NAME}"), {}),
    ("имя по частям в кавычках", B(f"cat ~/.claude/{DAEMON}/ros''ter.json"), {}),
    ("git commit -m && cat — не исключение", B(f'git commit -qm "x" && cat ~/.claude/{DAEMON}/{NAME}'), {}),
    ("git commit с путём вне сообщения", B(f'git commit -qm "ok" ~/.claude/{DAEMON}/{NAME}'), {}),
    ("git log с путём — не сообщение", B(f"git log -- ~/.claude/{DAEMON}/{NAME}"), {}),
    ("главная сессия окна роли (PANTHEON_ROLE)", ("Read", {"file_path": ROSTER}), {"role": None, "sub": False,
                                                                                  "window": "metis-pantheon"}),
    ("субагент сессии владельца", B(f"cat ~/.claude/{DAEMON}/{NAME}"), {"role": "general-purpose"}),
    # схема metis-0823: имя среди слов команды, вход перенаправления, код из stdin, команду не разобрать
    ("grep с файлом операндом (не шаблон)", B(f"grep -n Auth ~/.claude/{DAEMON}/{NAME}"), {}),
    ("файл входного перенаправления", B(f"head -c 400 < ~/.claude/{DAEMON}/{NAME}"), {}),
    ("python3 - <<EOF с кодом", B(f"python3 - <<'EOF'\nprint(open('/x/.claude/{DAEMON}/{NAME}').read())\nEOF"), {}),
    ("bash <<EOF с командой", B(f"bash <<'EOF'\ncat ~/.claude/{DAEMON}/{NAME}\nEOF"), {}),
    ("команду не разобрать", B(f"cat \"~/.claude/{DAEMON}/{NAME}"), {}),
]
for name, (tool, ti), kw in deny:
    out = run(tool, ti, **kw)
    ok = '"deny"' in out and RULE in out and HINT in out
    check(f"отказ: {name}", ok, out)

allow = [
    ("pantheon roster — безопасный путь", B("pantheon roster"), {}),
    ("Glob имён в папке daemon", ("Glob", {"pattern": "*", "path": DDIR}), {}),
    ("Read другого файла папки", ("Read", {"file_path": os.path.join(DDIR, "other.log")}), {}),
    ("Grep по папке выше (остаток, README)", ("Grep", {"pattern": "x", "path": os.path.join(HOME, ".claude")}), {}),
    ("поиск по исходникам без слова daemon", B(f"grep -n {NAME} plugins/pantheon/lib/pantheon.py"), {}),
    ("чужой roster.json без слова daemon", B(f"cat data/{NAME}"), {}),
    ("git commit -m с путём", B(f'git commit -qm "guard: ~/.claude/{DAEMON}/{NAME} — только через pantheon roster"'), {}),
    ("pantheon task set --note с путём", B(f'pantheon task set app-0001 --note "{DAEMON}/{NAME} закрыт"'), {}),
    ("сессия владельца без роли", ("Read", {"file_path": ROSTER}), {"role": None, "sub": False}),
    # схема metis-0823: текст сообщения и шаблон поиска путём не считаются (долги argus Д1, Д2 по #342)
    ("grep -rn шаблоном (Д1)", B(f"grep -rn {DAEMON}/{NAME} plugins/"), {}),
    ("rg -n шаблоном", B(f"rg -n '{DAEMON}/{NAME}' plugins/"), {}),
    ("git commit -F - из heredoc (Д2)", B(f"git commit -q -F - <<'EOF'\nguard: ~/.claude/{DAEMON}/{NAME}\nEOF"), {}),
    ("echo с путём в заметку", B(f"echo '~/.claude/{DAEMON}/{NAME} — через pantheon roster' >> notes.md"), {}),
    ("git commit -m && pantheon task --note", B(f'git commit -qm "{DAEMON}/{NAME}" && pantheon task set app-0001 '
                                                f'--note "{DAEMON}/{NAME}"'), {}),
]
for name, (tool, ti), kw in allow:
    out = run(tool, ti, **kw)
    check(f"можно: {name}", RULE not in out and '"deny"' not in out, out)

# безопасный путь целиком: то, что guard пропустил, печатает поля без ключей
env = {"PATH": os.environ["PATH"], "HOME": HOME, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
       "PANTHEON_STATE": os.path.join(HOME, ".local", "state", "pantheon"), "PANTHEON_NO_NOTIFY": "1",
       "PANTHEON_TEST": "1", "TMPDIR": os.path.join(ROOT, "tmp")}
r = subprocess.run([sys.executable, "-I", PANTHEON_RUN, "roster"], env=env, capture_output=True, text=True,
                   timeout=SUB_TIMEOUT)
out = r.stdout + r.stderr
check("pantheon roster: код 0, id/pid/startedAt есть, ключей нет",
      r.returncode == 0 and '"abcd1234"' in r.stdout and "4242" in r.stdout and "1791999000000" in r.stdout
      and not any(s in out for s in SECRETS + ("rvAuth", "ptyAuth")), out)

print(f"\n{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
