#!/usr/bin/env python3
"""Журнал и отчёт отказов окон (metis-1135 Д; lib/denials.py, hooks/refusal.py, hooks.json).

Запуск: python3 -I plugins/pantheon/tests/test_denials.py  (код выхода 0 — все прошли)
Временные HOME и PANTHEON_STATE; транскрипты — только поддельные, во временном HOME. Проверяет:
  [хук]      PermissionDenied → строка STATE/denials/<дата>.jsonl: время, окно, инструмент, класс, причина ≤200 знаков;
             текста команды и секретов в строке нет; ошибка записи — код 0 без вывода;
  [песочница] refusal.py fail на «Operation not permitted» → строка source=sandbox; обычный сбой теста — строки нет;
  [hooks.json] PermissionDenied зовёт hooks/denials.py hook;
  [отчёт]    таблицы по классам и окнам по убыванию, --since/--days/--until, плохая дата → код 2, пустой журнал;
  [backfill] из поддельного транскрипта берутся только отказы, в журнале и выводе нет остального текста; границы дат;
             повтор не дублирует; плохие аргументы → код 2;
  [проход]   отчёт по понедельникам, раз за день, не в другие дни, не в PANTHEON_DRYRUN.
"""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _py311 import PY311, mkroot  # noqa: E402

ROOT = os.path.realpath(mkroot("denials-"))
atexit.register(shutil.rmtree, ROOT, True)
HOME = os.path.join(ROOT, "home")
STATE = os.path.join(ROOT, "state")
os.makedirs(HOME)
DENIALS = os.path.join(STATE, "denials")
DEN = os.path.join(PLUGIN, "lib", "denials.py")
REF = os.path.join(PLUGIN, "hooks", "refusal.py")
PANTHEON = os.path.join(PLUGIN, "lib", "pantheon.py")
ENV = {"HOME": HOME, "PANTHEON_STATE": STATE, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "CLAUDE_PID": "4242"}
FAILS = []
TOTAL = [0]
WRAP = os.path.join(PLUGIN, "hooks", "denials.py")


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f" — {extra}"))
    if not cond:
        FAILS.append(name)


def run(args, ev=None, **env):
    r = subprocess.run([PY311, "-I", *args], input=ev if isinstance(ev, str) else json.dumps(ev or {}),
                       env=dict(ENV, **env), capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr


def journal():
    out = []
    try:
        for n in sorted(os.listdir(DENIALS)):
            if n.endswith(".jsonl"):
                with open(os.path.join(DENIALS, n), encoding="utf-8") as fh:
                    out += [json.loads(ln) for ln in fh]
    except OSError:
        pass
    return out


def reset():
    shutil.rmtree(DENIALS, ignore_errors=True)


_spec = importlib.util.spec_from_file_location("denials_t", DEN)
DM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DM)
TODAY = datetime.now().strftime("%Y-%m-%d")

# --- хук ---------------------------------------------------------------------------------------------------------------
SECRET = "sk-ABCDEF1234567890XYZ"
LONG = "FULL-COMMAND-TEXT-MARKER " + "x" * 300
ev = {"hook_event_name": "PermissionDenied", "tool_name": "Bash",
      "tool_input": {"command": f"FOO=1 /usr/bin/curl -H 'Authorization: Bearer {SECRET}' http://h/ {LONG}"},
      "reason": f"curl to host not allowed, token={SECRET} in /Users/ivan/private Bearer hunter2 " + "слово " * 100}
rc, out, _ = run([DEN, "hook"], ev, PANTHEON_TMP=os.path.join(ROOT, "caches", "win-one", "tmp"), PANTHEON_ROLE="dev-sonnet")
rows = journal()
r0 = rows[0] if rows else {}
check("хук: событие → одна строка, код 0, без вывода", rc == 0 and out == "" and len(rows) == 1, (rc, out, rows))
check("хук: класс — первое слово команды без пути и env", r0.get("cls") == "curl" and r0.get("tool") == "Bash", r0)
check("хук: окно и роль из окружения, источник classifier, время", r0.get("window") == "win-one"
      and r0.get("role") == "dev-sonnet" and r0.get("source") == "classifier" and isinstance(r0.get("t"), float), r0)
check("хук: причина ≤200 знаков", 0 < len(r0.get("reason", "")) <= 200, len(r0.get("reason", "")))
blob = json.dumps(rows, ensure_ascii=False)
check("хук: в строке нет секрета, текста команды и имени из домашнего пути",
      SECRET not in blob and "FULL-COMMAND-TEXT-MARKER" not in blob and "ivan" not in blob and "hunter2" not in blob, blob)
check("хук: файл журнала — по дню, права 600",
      os.path.exists(os.path.join(DENIALS, TODAY + ".jsonl"))
      and os.stat(os.path.join(DENIALS, TODAY + ".jsonl")).st_mode & 0o777 == 0o600)
rc, out, _ = run([DEN, "hook"], {"tool_name": "mcp__x__do", "tool_input": {}, "reason": "no"})
check("хук: не Bash — класс = имя инструмента", journal()[-1].get("cls") == "mcp__x__do", journal()[-1])
n = len(journal())
rc, out, _ = run([DEN, "hook"], "не json")
rc2, out2, _ = run([DEN, "hook"], "[1, 2]")
check("хук: мусор на входе — код 0, строк не добавилось", rc == 0 and rc2 == 0 and out + out2 == "" and len(journal()) == n)

n = len(journal())
rc, out, er = run([WRAP, "hook"], {"tool_name": "Bash", "tool_input": {"command": "curl x"}, "reason": "no"})
check("обёртка hooks/denials.py hook (её зовёт hooks.json) → строка в журнале", rc == 0 and out == ""
      and len(journal()) == n + 1 and journal()[-1].get("cls") == "curl", (rc, out, er))

bad = os.path.join(ROOT, "state-is-file")
with open(bad, "w") as fh:
    fh.write("x")
rc, out, er = run([DEN, "hook"], ev, PANTHEON_STATE=bad)
check("хук: ошибка записи (STATE — файл) → код 0, без вывода", rc == 0 and out == "", (rc, out, er))

# --- песочница: refusal.py fail --------------------------------------------------------------------------------------
reset()
rc, out, _ = run([REF, "fail"], {"tool_name": "Bash", "tool_input": {"command": "curl -s 127.0.0.1:9333/health"},
                                 "error": "curl: (7) Failed to connect: Operation not permitted"})
rows = journal()
check("fail: отказ песочницы → строка source=sandbox, класс curl", rc == 0 and len(rows) == 1
      and rows[0].get("source") == "sandbox" and rows[0].get("cls") == "curl", (rc, rows))
rc, out, _ = run([REF, "fail"], {"tool_name": "Bash", "tool_input": {"command": "pytest"}, "error": "AssertionError: 1 != 2"})
check("fail: обычный сбой теста → строки нет", len(journal()) == 1, journal())
reset()
CMDX = "mytool --flag value-MARKER-CMD"
rc, out, _ = run([REF, "fail"], {"tool_name": "Bash", "tool_input": {"command": "grep sandbox notes/x.md"},
                                 "error": "Exit code 1\nnotes/x.md: sandbox password hunter2 for vpn\nx: Permission denied"})
check("fail (Б1а): вывод со словом sandbox / permission denied и «password» → строки в журнале нет, подсказка есть",
      journal() == [] and "Пантеон (metis-0832)" in out, (journal(), out))
rc, out, _ = run([REF, "fail"], {"tool_name": "Bash", "tool_input": {"command": CMDX},
                                 "error": f"{CMDX}: Operation not permitted (password=hunter2) deny(1)"})
blob = json.dumps(journal(), ensure_ascii=False)
check("fail (Б1б): строка отказа повторяет команду и секрет → в reason только имя признака",
      len(journal()) == 1 and journal()[0]["reason"] == "operation not permitted" and "MARKER-CMD" not in blob
      and "hunter2" not in blob, blob)
reset()
rc, out, _ = run([REF, "fail"], {"tool_name": "Bash", "tool_input": {"command": "x"}, "error": "Operation not permitted"},
                 PANTHEON_STATE=bad)
check("fail: журнал не пишется (STATE — файл) → код 0", rc == 0, (rc, out))

# --- hooks.json ------------------------------------------------------------------------------------------------------
with open(os.path.join(PLUGIN, "hooks", "hooks.json"), encoding="utf-8") as fh:
    HJ = json.load(fh)["hooks"]
cmds = [h["command"] for m in HJ.get("PermissionDenied", []) for h in m["hooks"]]
check("hooks.json: PermissionDenied зовёт hooks/denials.py hook и прежний refusal.py denied",
      any(c.endswith('hooks/denials.py" hook') for c in cmds) and any(c.endswith('refusal.py" denied') for c in cmds), cmds)

# --- отчёт -----------------------------------------------------------------------------------------------------------


def put(day, source, cls, window, n=1):
    os.makedirs(DENIALS, exist_ok=True)
    with open(os.path.join(DENIALS, day + ".jsonl"), "a", encoding="utf-8") as fh:
        for _ in range(n):
            fh.write(json.dumps({"t": 1.0, "window": window, "role": "", "tool": "Bash", "cls": cls, "reason": "r",
                                 "source": source}) + "\n")


reset()
d = lambda k: (datetime.now() - timedelta(days=k)).strftime("%Y-%m-%d")  # noqa: E731
put(d(0), "classifier", "git", "win-a", 3)
put(d(1), "classifier", "curl", "win-b", 1)
put(d(2), "sandbox", "curl", "win-a", 4)
put(d(20), "classifier", "old-class", "win-old", 9)
rc, out, _ = run([PANTHEON, "denials", "report"])
i_curl, i_git = out.find("| curl | 5 |"), out.find("| git | 3 |")
check("report: по умолчанию 7 дней, классы по убыванию, старое не берётся",
      rc == 0 and 0 <= i_curl < i_git and "old-class" not in out and "Всего: 8" in out, (rc, out))
check("report: окна по убыванию, источники", out.find("| win-a | 7 |") < out.find("| win-b | 1 |")
      and "| classifier | 4 |" in out and "| sandbox | 4 |" in out, out)
rc, out, _ = run([PANTHEON, "denials", "report", "--days", "1"])
check("report --days 1 — только сегодня", "Всего: 3" in out and "curl" not in out, out)
rc, out, _ = run([PANTHEON, "denials", "report", "--since", d(30)])
check("report --since — с этой даты", "Всего: 17" in out and "old-class" in out, out)
rc, out, _ = run([PANTHEON, "denials", "report", "--since", d(30), "--until", d(10)])
check("report --until — по эту дату", "Всего: 9" in out, out)
rc, out, er = run([PANTHEON, "denials", "report", "--since", "вчера"])
check("report: плохая дата → код 2, причина в stderr", rc == 2 and "не по образцу" in er and out == "", (rc, out, er))
rc, out, er = run([PANTHEON, "denials", "report", "--days", "0"])
check("report: --days 0 → код 2", rc == 2, (rc, er))
reset()
rc, out, _ = run([PANTHEON, "denials", "report"])
check("report: пустой журнал → «Отказов в журнале нет»", rc == 0 and "Отказов в журнале нет" in out, out)

# --- backfill --------------------------------------------------------------------------------------------------------
reset()
PRIV = "PRIVATE-CHAT-MARKER-77"
proj = os.path.join(HOME, ".claude", "projects", "-work-win-x")
os.makedirs(proj)


def tu(i, name, cmd, ts):
    return {"timestamp": ts, "type": "assistant", "message": {"content": [
        {"type": "text", "text": PRIV + " думаю"}, {"type": "tool_use", "id": i, "name": name, "input": {"command": cmd}}]}}


def tr(i, text, ts, err=True):
    return {"timestamp": ts, "type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": i, "is_error": err, "content": text}]}}


IN, BEFORE, AFTER = "2026-11-10T10:00:00+00:00", "2026-11-01T10:00:00+00:00", "2026-11-20T10:00:00+00:00"
recs = [
    {"timestamp": IN, "type": "user", "message": {"content": PRIV + " личное сообщение"}},
    tu("t1", "Bash", "git push origin main " + PRIV, IN),
    tr("t1", PRIV + "\nPermission for this action was denied by the auto mode classifier. Reason: push to main not "
       "authorized", IN),
    tu("t2", "Bash", "curl 127.0.0.1:9333", IN), tr("t2", PRIV + "\ncurl: (7) Operation not permitted\n" + PRIV, IN),
    tu("t3", "Bash", "pytest", IN), tr("t3", "AssertionError " + PRIV, IN),
    tu("t4", "Bash", "ls", IN), tr("t4", "Permission for this action was denied by the auto mode classifier", IN, err=False),
    tu("t5", "Read", "", BEFORE), tr("t5", "denied by the auto mode classifier. Reason: old", BEFORE),
    tu("t6", "Read", "", AFTER), tr("t6", "denied by the auto mode classifier. Reason: new", AFTER),
]
with open(os.path.join(proj, "s1.jsonl"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\nне json PRIVATE\n")
os.makedirs(os.path.join(proj, "s1", "subagents"))
with open(os.path.join(proj, "s1", "subagents", "agent-a.jsonl"), "w", encoding="utf-8") as fh:
    fh.write(json.dumps(tu("t7", "Bash", "docker run x", IN)) + "\n"
             + json.dumps(tr("t7", "denied by the auto mode classifier. Reason: docker not allowed", IN)) + "\n")
proj2 = os.path.join(HOME, ".claude", "projects", "-Users-ivan-projects-demo-app")
os.makedirs(os.path.join(proj2, "s2", "subagents"))
with open(os.path.join(proj2, "s2", "subagents", "agent-b.jsonl"), "w", encoding="utf-8") as fh:
    fh.write(json.dumps(tu("t8", "Bash", "curl q", IN)) + "\n" + json.dumps(tr("t8", "curl: Operation not permitted", IN)) + "\n"
             + json.dumps(tu("t9", "Bash", "ls", IN)) + "\n"
             + json.dumps(tr("t9", "Permission for this action was denied by the auto mode classifier. Reason: only-this-"
                             "part\nline 2 reason: tail-NOT-HERE", IN)) + "\n"
             + json.dumps(tu("t10", "Bash", "grep sandbox x", IN)) + "\n"
             + json.dumps(tr("t10", "x.md: sandbox password hunter2", IN)) + "\n")
with open(os.path.join(proj, "notes.txt"), "w") as fh:
    fh.write(PRIV)
rc, out, er = run([PANTHEON, "denials", "backfill", "--since", "2026-11-07", "--until", "2026-11-13"])
rows = journal()
check("backfill: код 0, в выводе только счётчики", rc == 0 and PRIV not in out + er and "новых строк отказов 5" in out
      and "файлов 3" in out, (rc, out, er))
by = {r["id"]: r for r in rows}
check("backfill: в журнале только отказы (t10 — только слово sandbox — не отказ)", set(by) == {"t1", "t2", "t7", "t8", "t9"},
      sorted(by))
check("backfill: классы и источники", by["t1"]["cls"] == "git" and by["t1"]["source"] == "classifier"
      and by["t2"]["cls"] == "curl" and by["t2"]["source"] == "sandbox" and by["t7"]["cls"] == "docker", rows)
check("backfill: в журнале нет ни строки переписки, ни текста команды, ни хвоста причины с метками",
      PRIV not in json.dumps(rows, ensure_ascii=False) and "origin" not in json.dumps(rows), rows)
check("backfill: набор полей — только поля отказа", all(set(r) <= {"t", "window", "role", "tool", "cls", "reason",
                                                                  "source", "id"} for r in rows), rows)
check("backfill (Б2): окно субагента t7 = окно главной сессии t1 (папка проекта), не «subagents»",
      by["t7"]["window"] == by["t1"]["window"] == "work-win-x" and all(r["window"] != "subagents" for r in rows),
      [(r["id"], r["window"]) for r in rows])
check("backfill (Д1): окно без users-<имя> и без «projects-»", by["t8"]["window"] == "demo-app"
      and "ivan" not in json.dumps([r["window"] for r in rows]), by["t8"]["window"])
check("backfill: причина песочницы — имя признака, причина классификатора — только после «Reason:» шаблона",
      by["t8"]["reason"] == "operation not permitted" and by["t9"]["reason"].startswith("only-this-")
      and "tail-NOT-HERE" in by["t9"]["reason"] and by["t2"]["reason"] == "operation not permitted", rows)
rc, out, _ = run([PANTHEON, "denials", "backfill", "--since", "2026-11-07", "--until", "2026-11-13"])
check("backfill: повтор не дублирует", "новых строк отказов 0" in out and len(journal()) == 5, (out, len(journal())))
for args in (["--since", "2026-11-07"], ["--since", "2026-11-13", "--until", "2026-11-07"], ["--since", "x", "--until", "y"]):
    rc, out, er = run([PANTHEON, "denials", "backfill", *args])
    check(f"backfill: плохие аргументы {args} → код 2", rc == 2 and out == "" and er.strip(), (rc, out, er))
rc, out, er = run([PANTHEON, "denials", "wat"])
check("denials: неизвестная подкоманда → код 2", rc == 2, (rc, er))

# --- маска секретов (argus2) ------------------------------------------------------------------------------------------
CANARY = ["hunter2", "s3cr3tpw", "qwerty", "abc123key", "dXNlcjpwYXNz", "tok-9f8e7d"]
for sample in ("curl -u admin:hunter2 http://h", "https://bob:s3cr3tpw@host/x", "PGPASSWORD=qwerty psql",
               "export OPENAI_API_KEY=abc123key", "Authorization: Basic dXNlcjpwYXNz", "curl --user=a:hunter2 u",
               "Authorization: Bearer tok-9f8e7d", "MY_SECRET_TOKEN: tok-9f8e7d"):
    out = DM.scrub(sample)
    check(f"scrub: «{sample}» → без значения", not any(c in out for c in CANARY), out)
check("scrub: обычный текст не портится", DM.scrub("curl to host not allowed") == "curl to host not allowed")

# --- плановый проход -------------------------------------------------------------------------------------------------
reset()
d0 = datetime.now().replace(hour=4, minute=0, second=0, microsecond=0)
mon = d0 - timedelta(days=d0.weekday())
tue = mon + timedelta(days=1)
put(mon.strftime("%Y-%m-%d"), "classifier", "git", "win-a", 2)
res = DM.tick(tue.timestamp(), STATE)
check("проход: не в понедельник — ничего", res is None and not os.path.exists(DENIALS + f"/report-{tue:%Y-%m-%d}.md"))
res = DM.tick(mon.timestamp(), STATE)
rp = os.path.join(DENIALS, f"report-{mon:%Y-%m-%d}.md")
check("проход: понедельник → report-<дата>.md с таблицей", res and os.path.exists(rp)
      and "| git | 2 |" in open(rp, encoding="utf-8").read(), res)
os.unlink(os.path.join(DENIALS, f"{mon:%Y-%m-%d}.jsonl"))
check("проход: второй раз в тот же день — не переписывает", DM.tick(mon.timestamp(), STATE) is None
      and "| git | 2 |" in open(rp, encoding="utf-8").read())
os.unlink(rp)
os.environ["PANTHEON_DRYRUN"] = "1"
check("проход: PANTHEON_DRYRUN — ничего", DM.tick(mon.timestamp(), STATE) is None and not os.path.exists(rp))
del os.environ["PANTHEON_DRYRUN"]

src = open(os.path.join(PLUGIN, "lib", "pantheon.py"), encoding="utf-8").read()
check("pantheon.py: release_ticks зовёт denials_mod, команда denials диспетчеризована",
      '"отчёт отказов", denials_mod)' in src and 'if cmd == "denials":' in src)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]}")
sys.exit(1 if FAILS else 0)
