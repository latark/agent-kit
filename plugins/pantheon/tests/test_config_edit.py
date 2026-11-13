#!/usr/bin/env python3
"""Настройки, хуки и .mcp.json worktree роли — по «да» или Touch ID, привязанным к sha256 (metis-0844,
lib/config_edit.py).

Запуск: python3 -I plugins/pantheon/tests/test_config_edit.py  (код выхода 0 — все прошли)
Временный HOME и STATE, проект — git init и linked worktree во временной папке; окно Touch ID (config_edit.ask), простой
владельца и тревоги подменены, окружение прохода — merge.TEST (clean_env). По пунктам «Готово, когда» карточки:
  [свой]    своя роль пишет хук и .mcp.json после «да» с совпавшим sha256 → записано, права, журнал, итог роли;
  [Touch ID] палец → записано и строка config-edit-approve; отказ, владелец не у Mac, заявку сменили — не записано;
  [отказ]   другое содержимое (вопрос не дословно), «нет», файл изменён после заявки, чужой проект (и заявка, подложенная
            в чужую очередь), основная копия вместо worktree, taint (в заявке и после неё), сессия не опознана, путь вне
            списка, ссылка, не JSON, вне окна, повтор той же заявки — не записано;
  [проход]  из окна Claude Code — отказ; тик зовёт проход только при заявке.
"""
import atexit
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _py311 import mkroot  # noqa: E402

_ROOT = os.path.realpath(mkroot("config-edit-"))
atexit.register(shutil.rmtree, _ROOT, True)
HOME = os.path.join(_ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE", "XDG_"))]:
    os.environ.pop(k)
BASE_ENV = {"PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"), "PANTHEON_NO_NOTIFY": "1",
            "PANTHEON_TEST": "1"}
os.environ.update(dict(BASE_ENV, HOME=HOME))
sys.path.insert(0, os.path.join(PLUGIN, "lib"))
import pantheon as P  # noqa: E402

CE = P.config_edit_mod()
OE = P.owner_edit_mod()
M = P.merge_mod()
M.TEST = {"env": BASE_ENV}
CACHES = os.path.join(HOME, "Library", "Caches", "pantheon-sandbox")
APP = os.path.join(HOME, "projects", "app")
OTHER = os.path.join(HOME, "projects", "other")
WT = os.path.join(APP, ".claude", "worktrees", "w1")
WORK = os.path.join(_ROOT, "work")
TAINT = os.path.join(HOME, ".local", "state", "tg-taint")
SID = "0b6f2c1e-1111-4222-8333-444455556666"
os.makedirs(WORK)

FAILS, TOTAL = [], [0]


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{str(extra)[-800:]}]"))
    if not cond:
        FAILS.append(name)


ASKED, ALERTS = [], []
ANSWER = {"code": 0, "during": None}
IDLE = [0.0]


def fake_ask(text):
    ASKED.append(text)
    if ANSWER["during"]:
        ANSWER["during"]()
    return ANSWER["code"]


CE.ask = fake_ask
P.idle_sec = lambda: IDLE[0]
P.alert_once = lambda key, value, text, *a, **kw: ALERTS.append((key, value, text))


PATH = os.environ.get("PATH") or "/usr/bin:/bin"


def git(*args, cwd=None, check=True):
    env = {"HOME": HOME, "PATH": PATH, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                           *args], cwd=cwd, env=env, capture_output=True, text=True, check=check)


def write(p, text, mode=0o644):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(p, mode)


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


for repo in (APP, OTHER):
    os.makedirs(repo)
    git("init", "-q", cwd=repo)
    write(os.path.join(repo, "README.md"), "x\n")
    git("add", "README.md", cwd=repo)
    git("commit", "-qm", "init", cwd=repo)
git("worktree", "add", "-q", "-b", "w1", WT, cwd=APP)
OTHER_WT = os.path.join(OTHER, ".claude", "worktrees", "o1")
git("worktree", "add", "-q", "-b", "o1", OTHER_WT, cwd=OTHER)
write(os.path.join(STATE, "domains.json"), json.dumps({"domains": {"app": [APP], "other": [OTHER]}}))

MCP_OLD = '{"mcpServers": {}}\n'
MCP_NEW = '{"mcpServers": {"next-devtools": {"command": "npx", "args": ["-y", "next-devtools-mcp@0.3.1"]}}}\n'
HOOK = "#!/bin/sh\nexit 0\n"
SETTINGS = '{"enabledMcpjsonServers": ["next-devtools"]}\n'


def quiet(fn, *a):
    out, errb = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(errb):
        rc = fn(*a)
    return rc, out.getvalue(), errb.getvalue()


def fresh(code=0, during=None):
    os.environ.clear()
    os.environ.update(dict(BASE_ENV, HOME=HOME))
    P.HOME, P.STATE = HOME, STATE
    for d in (os.path.join(STATE, "config-edit"), os.path.join(STATE, "owner-log"), os.path.join(STATE, "logs"), CACHES,
              TAINT, os.path.join(WT, ".claude", "hooks")):
        shutil.rmtree(d, ignore_errors=True)
    for p in (os.path.join(WT, ".claude", "settings.json"), os.path.join(WT, ".mcp.json"), os.path.join(APP, ".mcp.json")):
        with contextlib.suppress(FileNotFoundError):
            os.remove(p)
    write(os.path.join(WT, ".mcp.json"), MCP_OLD, 0o640)
    ASKED.clear()
    ALERTS.clear()
    ANSWER.update(code=code, during=during)
    IDLE[0] = 0.0


def request(pairs, window="app", sid=SID, task="metis-0844", why="сервер next-devtools"):
    args = []
    for i, (dst, text) in enumerate(pairs):
        src = os.path.join(WORK, f"new{i}.txt")
        write(src, text)
        args.append(f"{dst}={src}")
    if window:
        os.makedirs(os.path.join(CACHES, window, "tmp"), exist_ok=True)
        os.environ["PANTHEON_TMP"] = os.path.join(CACHES, window, "tmp")
        os.environ["PANTHEON_ROLE"] = "dev-opus"
    if sid:
        os.environ["CLAUDE_CODE_SESSION_ID"] = sid
    try:
        return quiet(CE.main, ["request", *args, "--task", task, "--why", why])
    finally:
        for k in ("PANTHEON_TMP", "PANTHEON_ROLE", "CLAUDE_CODE_SESSION_ID"):
            os.environ.pop(k, None)


def reqs():
    out = []
    for d, win in CE.queue_dirs():
        for n in sorted(os.listdir(d)):
            if n.endswith(".req.json"):
                out.append((os.path.join(d, n), json.loads(read(os.path.join(d, n))), win))
    return out


def answer(q, a, t=None):
    os.makedirs(os.path.join(STATE, "owner-log"), exist_ok=True)
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t if t is not None else time.time()))
    with open(os.path.join(STATE, "owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
        fh.write(f"\n## {when} · окно вопросов\nвопрос: {q}\nответ: {a}\n")


def run():
    rc = quiet(CE.main, ["run"])
    os.environ.clear()
    os.environ.update(dict(BASE_ENV, HOME=HOME))
    return rc


def journal():
    p = os.path.join(STATE, "logs", CE.JOURNAL)
    return [json.loads(ln) for ln in read(p).splitlines()] if os.path.exists(p) else []


def result(req, win="app"):
    p = os.path.join(CACHES, win, "config-edit", f"{req['id']}.result.json")
    return json.loads(read(p)) if os.path.exists(p) else {}


def approve_log():
    p = os.path.join(STATE, "owner-log", CE.APPROVE_LOG)
    return read(p) if os.path.exists(p) else ""


def q_of(req, win="app"):
    return CE.question(dict(req, window=win))


HOOK_P = os.path.join(WT, ".claude", "hooks", "check.sh")
MCP_P = os.path.join(WT, ".mcp.json")
SET_P = os.path.join(WT, ".claude", "settings.json")

# --- [свой] своя роль, «да» с совпавшим sha256 → записано --------------------------------------------------------------
fresh()
rc, out, errs = request([(MCP_P, MCP_NEW), (HOOK_P, HOOK), (SET_P, SETTINGS)])
q = reqs()
check("request: заявка в кэше окна роли", rc == 0 and len(q) == 1 and q[0][2] == "app", (rc, out, errs))
_, req, _ = q[0]
check("request: вопрос Зевсу с [id] и sha заявки в выводе", f"[{req['id']}]" in out and req["sha"][:16] in out, out)
check("request: файлы роль не трогала", read(MCP_P) == MCP_OLD and not os.path.exists(HOOK_P), req)
check("request: новый файл — sha до «absent»", [f["before"] for f in req["files"]][1:] == ["absent", "absent"], req)
check("request: в вопросе ключ JSON и строка хука", "mcpServers\\.next\\-devtools\\.command" in q_of(req)
      and "\\+exit 0" in q_of(req), q_of(req))
answer(q_of(req), "А — Да, записать")
rc, out, errs = run()
check("«да» с sha заявки → .mcp.json записан, права прежние (640)", read(MCP_P) == MCP_NEW
      and stat.S_IMODE(os.stat(MCP_P).st_mode) == 0o640, (rc, out, errs, journal()))
check("«да» → хук записан в новую папку .claude/hooks, права 644", os.path.exists(HOOK_P) and read(HOOK_P) == HOOK
      and stat.S_IMODE(os.stat(HOOK_P).st_mode) == 0o644, journal())
check("«да» → общий .claude/settings.json записан", os.path.exists(SET_P) and read(SET_P) == SETTINGS)
j = journal()
check("журнал: done, how=consent, sha заявки", len(j) == 1 and j[0]["state"] == "done" and j[0]["how"] == "consent"
      and j[0]["sha"] == req["sha"], j)
check("итог роли done, заявки нет, Touch ID не спрашивали", result(req).get("state") == "done" and not reqs()
      and not ASKED, (result(req), ASKED))
check("основной репозиторий не тронут", not os.path.exists(os.path.join(APP, ".mcp.json")))
git_st = git("status", "--porcelain", cwd=WT).stdout
check("файлы в worktree — для коммита ролью", ".mcp.json" in git_st and ".claude/" in git_st, git_st)
# повтор той же заявки (один файл, вернули как было, «да» в журнале то же) — второй раз не применяется
fresh()
request([(MCP_P, MCP_NEW)])
_, req, _ = reqs()[0]
answer(q_of(req), "А — Да, записать")
run()
d = os.path.join(CACHES, "app", "config-edit")
write(MCP_P, MCP_OLD, 0o640)
with open(os.path.join(d, f"{req['id']}.req.json"), "w", encoding="utf-8") as fh:
    json.dump(req, fh)
rc, _, _ = run()
check("повтор той же заявки — refused «уже в журнале», файл не тронут", read(MCP_P) == MCP_OLD
      and journal()[-1]["state"] == "refused" and "уже в журнале" in journal()[-1]["note"], journal())

# --- [отказ] «да» на другой текст, «нет», файл изменён --------------------------------------------------------------
fresh()
request([(MCP_P, MCP_NEW)])
_, req, _ = reqs()[0]
answer(q_of(req).replace(req["sha"][:16], "0" * 16), "А — Да, записать")
run()
check("«да» на вопрос с другим sha — refused, не записано", read(MCP_P) == MCP_OLD
      and journal()[-1]["state"] == "refused" and not ASKED, journal())

fresh()
request([(MCP_P, MCP_NEW)])
_, req, _ = reqs()[0]
answer(q_of(req), "Б — Нет")
run()
check("ответ «нет» — declined, не записано", read(MCP_P) == MCP_OLD and journal()[-1]["state"] == "declined", journal())

fresh()
request([(MCP_P, MCP_NEW)])
_, req, _ = reqs()[0]
write(MCP_P, '{"mcpServers": {"x": {}}}\n', 0o640)
answer(q_of(req), "А — Да, записать")
run()
check("файл изменён после заявки — refused, «да» не применено", read(MCP_P) == '{"mcpServers": {"x": {}}}\n'
      and journal()[-1]["state"] == "refused" and "изменился" in journal()[-1]["note"], journal())

fresh()
request([(MCP_P, MCP_NEW)])
_, req, _ = reqs()[0]
answer(q_of(req), "А — Да, записать", t=time.time() - 3600)
IDLE[0] = 10_000
rc, _, _ = run()
check("ответ до заявки и владельца нет — заявка ждёт", read(MCP_P) == MCP_OLD and reqs() and not journal()
      and not ASKED, journal())

# --- [отказ] taint, сессия, чужой проект, основная копия, пути -------------------------------------------------------
fresh()
os.makedirs(TAINT)
write(os.path.join(TAINT, SID), "1")
rc, _, errs = request([(MCP_P, MCP_NEW)])
check("taint в сессии — отказ заявки, код 2, причина последней строкой", rc == 2 and not reqs()
      and "Telegram" in errs.strip().splitlines()[-1], errs)

fresh()
request([(MCP_P, MCP_NEW)])
_, req, _ = reqs()[0]
os.makedirs(TAINT)
write(os.path.join(TAINT, SID), "1")
answer(q_of(req), "А — Да, записать")
run()
check("taint после заявки — refused и с «да»", read(MCP_P) == MCP_OLD and journal()[-1]["state"] == "refused"
      and "Telegram" in journal()[-1]["note"], journal())

fresh()
rc, _, errs = request([(MCP_P, MCP_NEW)], sid=None)
check("сессия не опознана — отказ заявки", rc == 2 and not reqs() and "taint не проверить" in errs, errs)

fresh()
rc, _, errs = request([(MCP_P, MCP_NEW)], window="other")
check("чужой проект (окно other, worktree app) — отказ заявки", rc == 2 and not reqs() and "чужой проект" in errs, errs)

fresh()
request([(MCP_P, MCP_NEW)])
path0, req, _ = reqs()[0]
od = os.path.join(CACHES, "other", "config-edit")
os.makedirs(od)
shutil.move(path0, os.path.join(od, os.path.basename(path0)))
answer(q_of(req, "other"), "А — Да, записать")
run()
check("заявка в очереди чужого окна — refused по папке очереди, не из текста", read(MCP_P) == MCP_OLD
      and journal()[-1]["state"] == "refused" and "чужой проект" in journal()[-1]["note"], journal())

fresh()
rc, _, errs = request([(os.path.join(APP, ".mcp.json"), MCP_NEW)])
check("основная копия проекта — отказ заявки", rc == 2 and not reqs() and "основная копия" in errs, errs)

fresh()
rc, _, errs = request([(os.path.join(WT, "src", "a.py"), "x\n")])
check("путь вне списка — отказ", rc == 2 and not reqs() and "не из списка" in errs, errs)
rc, _, errs = request([(os.path.join(WT, ".claude", "hooks", "..", "settings.json"), SETTINGS)])
check("«..» в пути сведён к .claude/settings.json — заявка на него, не мимо списка",
      rc == 0 and reqs()[0][1]["files"][0]["rel"] == ".claude/settings.json", (rc, errs))
fresh()
rc, _, errs = request([(MCP_P, "[1, 2]\n")])
check(".mcp.json не объект JSON — отказ", rc == 2 and not reqs() and "не объект JSON" in errs, errs)
rc, _, errs = request([(HOOK_P, "echo\u202ex\n")])
check("невидимый знак в хуке — отказ", rc == 2 and not reqs() and "U+202E" in errs, errs)
rc, _, errs = request([(MCP_P, MCP_NEW)], window=None)
check("вне окна направления — отказ", rc == 2 and not reqs() and "окна направления" in errs, errs)
rc, _, errs = request([(MCP_P, MCP_OLD)])
check("текст как в файле — отказ «править нечего»", rc == 2 and not reqs(), errs)
os.makedirs(os.path.join(WT, ".claude"), exist_ok=True)
os.symlink(os.path.join(HOME, "elsewhere.json"), SET_P)
rc, _, errs = request([(SET_P, SETTINGS)])
check("файл — ссылка — отказ заявки", rc == 2 and not reqs() and not os.path.exists(os.path.join(HOME, "elsewhere.json")),
      errs)
os.remove(SET_P)

fresh()
request([(SET_P, SETTINGS)])
_, req, _ = reqs()[0]
os.makedirs(os.path.join(HOME, "elsewhere"), exist_ok=True)
shutil.rmtree(os.path.join(WT, ".claude"), ignore_errors=True)
os.symlink(os.path.join(HOME, "elsewhere"), os.path.join(WT, ".claude"))
answer(q_of(req), "А — Да, записать")
run()
check("папка .claude подменена ссылкой после заявки — не записано", not os.listdir(os.path.join(HOME, "elsewhere"))
      and journal()[-1]["state"] in ("refused", "failed"), journal())
os.remove(os.path.join(WT, ".claude"))

# --- [Touch ID] ----------------------------------------------------------------------------------------------------
fresh()
request([(MCP_P, MCP_NEW)])
_, req, _ = reqs()[0]
run()
check("палец → записано, how=touchid", read(MCP_P) == MCP_NEW and journal()[-1]["how"] == "touchid", journal())
check("Touch ID: в окне проект, worktree, файл, sha и путь к диффу", ASKED and "worktrees/w1" in ASKED[0]
      and ".mcp.json" in ASKED[0] and req["sha"][:16] in ASKED[0] and "diffs" in ASKED[0], ASKED)
check("Touch ID: строка config-edit-approve с id и sha", f"config-edit-approve {req['id']} {req['sha']}" in approve_log(),
      approve_log())
check("Touch ID: полный дифф лежит по пути из окна", "next-devtools" in read(CE.diff_path(req)))

fresh(code=1)
request([(MCP_P, MCP_NEW)])
run()
check("отказ в окне Touch ID — declined, не записано", read(MCP_P) == MCP_OLD and journal()[-1]["state"] == "declined")

fresh()
request([(MCP_P, MCP_NEW)])
IDLE[0] = 10_000
run()
check("владелец не у Mac — окна нет, заявка ждёт", not ASKED and reqs() and read(MCP_P) == MCP_OLD)

fresh(code=3)
request([(MCP_P, MCP_NEW)])
run()
run()
check("время вышло — повтор не раньше RETRY_SEC", len(ASKED) == 1 and reqs() and read(MCP_P) == MCP_OLD, ASKED)


def swap():
    p, r, _ = reqs()[0]
    r["why"] = "другое"
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(r, fh)


fresh(during=swap)
request([(MCP_P, MCP_NEW)])
run()
check("заявку сменили, пока окно открыто — палец не засчитан", read(MCP_P) == MCP_OLD
      and journal()[-1]["state"] == "dropped" and not approve_log(), journal())

# --- [проход] -------------------------------------------------------------------------------------------------------
fresh()
request([(MCP_P, MCP_NEW)])
os.environ["CLAUDECODE"] = "1"
rc, _, errs = quiet(CE.main, ["run"])
os.environ.pop("CLAUDECODE", None)
os.environ.update(dict(BASE_ENV, HOME=HOME))
check("run из окна Claude Code — отказ, код 2", rc == 2 and read(MCP_P) == MCP_OLD and not ASKED, errs)
rc, out, _ = quiet(P.main, ["config", "status"])
check("pantheon config status: заявка видна", "ждёт" in out and ".mcp.json" in out, out)
dry = os.path.join(STATE, "dryrun.log")
with contextlib.suppress(FileNotFoundError):
    os.remove(dry)
os.environ["PANTHEON_DRYRUN"] = "1"
P.owner_edit_kick()
check("тик: есть заявка — проход config-edit запускается", os.path.exists(dry) and "config-edit-run" in read(dry))
os.remove(dry)
with P.lock("config-edit-run") as held:
    P.owner_edit_kick()
check("тик: замок прохода занят — проход не запускается", held and not os.path.exists(dry))
_, r0, _ = reqs()[0]
os.environ["PANTHEON_TMP"] = os.path.join(CACHES, "app", "tmp")
rc, _, _ = quiet(CE.main, ["cancel", r0["id"]])
os.environ.pop("PANTHEON_TMP")
P.owner_edit_kick()
os.environ.pop("PANTHEON_DRYRUN")
check("тик: заявок нет — прохода нет", rc == 0 and not reqs() and not os.path.exists(dry))

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
