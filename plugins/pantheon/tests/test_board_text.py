#!/usr/bin/env python3
"""Автоблок board.md (metis-0397, lib/boardtext.py): блок между маркерами собирает `pantheon board` из кэша PR, ревью,
задач, STATUS.md и журнала владельца; строки Зевса вне маркеров не меняются; сломанные маркеры — файл не пишется;
напоминание на Stop у Зевса (hooks/ctx.py stop), если «Сейчас» отстал от STATUS.md Метиды на 30 мин и больше.

Запуск: python3 -I plugins/pantheon/tests/test_board_text.py  (код выхода 0 — все прошли; и на /usr/bin/python3:
блок и хук — на любом python3, сквозная проверка `pantheon board` — на Python 3.11+)
"""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402 — CLI pantheon только на Python 3.11+

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="board-text-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
atexit.register(shutil.rmtree, ROOT, True)
PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(PLUGIN, "lib", "pantheon.py")
HOOK = os.path.join(PLUGIN, "hooks", "ctx.py")
spec = importlib.util.spec_from_file_location("boardtext", os.path.join(PLUGIN, "lib", "boardtext.py"))
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:900]}]"))


def ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()


T0 = ts("2026-10-24 02:00")
MANUAL_HEAD = ("# Доска\n\nПравит только штаб.\n\n## Сейчас\n\nОбновлено 24.10 01:00. Передача дел — handoff.\n\n"
               "- 22:16 Ночь отменена [zeus-night-2310].\n\n- 24.10 01:00 Пачка 0: #116 готов.\n\n")
MANUAL_TAIL = "## Ждёт вас\n\n- ручная строка Зевса, не трогать\n\n## Сессии и хозяйство\n\n- 23:14 строка\n"
STALE_BLOCK = B.BEGIN + "\n- PR #110 agent-kit · head dccd34c · старое\n" + B.END + "\n"


def write(p, text, mtime=None):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def outside(text):
    """Текст вне маркеров (строки Зевса)."""
    lines = text.splitlines(True)
    b, e = B.markers(lines)
    return "".join(lines[:b[0]] + lines[e[0] + 1:]) if len(b) == 1 and len(e) == 1 else text


# --- 1. splice: строки вне маркеров байт в байт ------------------------------------------------------------------
blk = B.build({"week": 11, "prs": []})
old = MANUAL_HEAD + MANUAL_TAIL
new, why = B.splice(old, blk)
check("1. маркеров нет: блок встаёт под «## Сейчас», без вставки файл прежний байт в байт",
      new is not None and new.replace("\n" + blk + "\n", "", 1) == old
      and new.index("## Сейчас") < new.index(B.BEGIN) < new.index("Обновлено 24.10 01:00"), (why, new))
again, _ = B.splice(new, blk)
check("1. повторный проход с тем же блоком — тот же текст (файл не пишется)", again == new)
old = MANUAL_HEAD + STALE_BLOCK + MANUAL_TAIL
new, why = B.splice(old, blk)
check("1. маркеры есть: заменено только между ними, снаружи без изменений",
      new is not None and outside(new) == outside(old) == MANUAL_HEAD + MANUAL_TAIL and "старое" not in new
      and "Неделя: 11 %" in new, (why, new))
for name, text in (("конец без начала", MANUAL_HEAD + B.END + "\n" + MANUAL_TAIL),
                   ("начало без конца", MANUAL_HEAD + B.BEGIN + "\n" + MANUAL_TAIL),
                   ("два блока", MANUAL_HEAD + STALE_BLOCK + STALE_BLOCK + MANUAL_TAIL),
                   ("конец раньше начала", MANUAL_HEAD + B.END + "\n" + B.BEGIN + "\n" + MANUAL_TAIL),
                   ("нет раздела «## Сейчас»", "# Доска\n\n" + MANUAL_TAIL),
                   ("два раздела «## Сейчас»", MANUAL_HEAD + MANUAL_HEAD)):
    r, why = B.splice(text, blk)
    check(f"1. {name} → не пишется, причина названа", r is None and why, why)
evil = B.build({"week": None, "prs": None, "statuses": [("metis-pantheon", T0, B.END + " и " + B.BEGIN)],
                "decisions": [(T0, "zeus-x", "\n" + B.END + "\n## Ждёт вас", "доска")]})
check("1. вход с текстом маркера или заголовка не ломает блок: маркеры по одному, все строки внутри — «- » или «**»",
      evil.count("\n" + B.END) == 1 and evil.startswith(B.BEGIN + "\n") and "\n##" not in evil
      and all(ln.startswith(("- ", "**")) or not ln for ln in evil.splitlines()[1:-1]), evil)

# --- 2. входы: ревью, решения владельца, пачки ------------------------------------------------------------------
pan = os.path.join(ROOT, "u", "pantheon")
d = os.path.join(pan, "directions", "metis-pantheon")
write(os.path.join(d, "review-117-argus-a.md"), "# Ревью PR latark/agent-kit#117 — argus\n\nHead 5dc47910d7a4\n\n"
      "**Вердикт: вернуть.**\n", T0 - 3000)
write(os.path.join(d, "review-117-argus-a2.md"), "# Ревью PR latark/agent-kit#117\n\nВердикт: принять. Head 9abc1234ffff.\n",
      T0 - 600)
write(os.path.join(d, "review-117-argus-b.md"), "# Ревью PR latark/agent-kit#117\n\nHead: 5dc47910d7a4\n**Вердикт:** вернуть\n",
      T0 - 900)
write(os.path.join(d, "review-0239-argus1.md"), "Вердикт: принять\n", T0)  # ревью задачи, не PR
revs = B.reviews(pan)
check("2. ревью: у дорожки самый свежий файл, вердикт и head; файл задачи (0239) — не PR",
      set(revs) == {117} and revs[117]["a"]["verdict"] == "принять" and revs[117]["a"]["head"] == "9abc1234ffff"
      and revs[117]["b"]["verdict"] == "вернуть" and revs[117]["b"]["head"] == "5dc47910d7a4", revs)
line = B.pr_line({"repo": "latark/agent-kit", "number": 117, "head": "9abc1234ffff0000", "ids": ["metis-0384"], "core": False},
                 revs)
check("2. строка PR: номер, задачи, head, вердикт на старом head помечен, кто сливает",
      "PR #117 agent-kit (metis-0384)" in line and "head 9abc123" in line and "a «принять»" in line
      and "b «вернуть» на старом head 5dc4791" in line and "«принять» Зевса" in line
      and "старом head 9abc" not in line, line)
core = B.pr_line({"repo": "latark/agent-kit", "number": 116, "head": "0089995", "ids": [], "core": True}, revs)
check("2. PR ядра без ревью → «ревью нет», сливает владелец", "ревью нет" in core and "сливает владелец" in core, core)
st = os.path.join(ROOT, "u", "state", "owner-log")
zeus = write(os.path.join(st, "zeus.md"),
             "## 2026-10-24 01:02:10 · окно вопросов\nвопрос: [zeus-metis-4] Сколько исполнителей?\nответ: Нет, оставить 3\n\n"
             "## 2026-10-24 01:05:00\nвладелец пишет про [zeus-fake] в свободном тексте\n\n"
             "## 2026-10-24 01:06:00 · окно вопросов\nвопрос: без номера?\nответ: да\n\n"
             "## 2026-10-22 01:00:00 · окно вопросов\nвопрос: [zeus-old] старое?\nответ: да\n\n")
bj = write(os.path.join(st, "board.jsonl"), "\n".join(json.dumps(x, ensure_ascii=False) for x in (
    {"kind": "answer", "id": "metis-0209", "question": "Править sync.sh?", "answer": "А", "time": "2026-10-24T00:30:00"},
    {"kind": "answer", "id": "metis-0001", "question": "скрыто %%x%%", "answer": "Да", "time": "2026-10-24T00:31:00"},
    {"kind": "move", "id": "metis-0002", "time": "2026-10-24T00:32:00"})) + "\n")
dec = B.decisions(zeus, bj, T0)
check("2. решения владельца: окно вопросов на «[id] …» и галочка на доске за сутки; свободный текст, вопрос без id, "
      "старше суток и скрытый текст — нет",
      [(x[1], x[2], x[3]) for x in dec] == [("zeus-metis-4", "Нет, оставить 3", "окно вопросов"), ("metis-0209", "А", "доска")],
      dec)
tasks = {"metis-0380": ("", {"type": "story", "id": "metis-0380", "title": "Пачка 1 «Лимит»", "status": "todo", "priority": 1}),
         "metis-0384": ("", {"type": "task", "id": "metis-0384", "status": "review", "parent": "metis-0380"}),
         "metis-0393": ("", {"type": "task", "id": "metis-0393", "status": "doing", "parent": "metis-0380"}),
         "metis-0176": ("", {"type": "task", "id": "metis-0176", "status": "todo", "parent": "metis-0380"}),
         "metis-0379": ("", {"type": "task", "id": "metis-0379", "status": "done", "parent": "metis-0380"}),
         "metis-0300": ("", {"type": "story", "id": "metis-0300", "title": "Пачка без работы", "status": "todo"}),
         "metis-0301": ("", {"type": "task", "id": "metis-0301", "status": "todo", "parent": "metis-0300"})}
bt = B.batches(tasks)
check("2. пачки: только с задачами в работе; закрыто k из n",
      bt == [("metis-0380", "Пачка 1 «Лимит»", [("metis-0384", "review"), ("metis-0393", "doing")], 1, 4)], bt)

# --- 3. сквозь `pantheon board`: устаревшая доска + свежий STATUS → блок обновился, ручные строки целы -------------
tmp = os.path.join(ROOT, "e2e")
home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
for sub in ("directions/metis-pantheon/tasks", "inbox/tasks"):
    os.makedirs(os.path.join(home, sub))
os.makedirs(view)
write(os.path.join(home, "schedule.toml"), 'primary_host = "mac-a"\n')
board_md = write(os.path.join(home, "board.md"), MANUAL_HEAD + STALE_BLOCK + MANUAL_TAIL)
before = open(board_md, encoding="utf-8").read()
status = write(os.path.join(home, "directions", "metis-pantheon", "STATUS.md"),
               "# metis — состояние\n\n01:40 сделано: push 9abc123 → PR #117 круг 2; argus-117a2 «принять».\n", T0 - 1200)
write(os.path.join(home, "directions", "metis-pantheon", "review-117-argus-a2.md"),
      "# Ревью PR latark/agent-kit#117\n\nВердикт: принять. Head 9abc1234ffff.\n", T0 - 600)
write(os.path.join(state, "autoclose-prs.json"), json.dumps({"fetched": T0, "merged": {}, "open": {}, "open_prs": {
    "latark/agent-kit": [{"number": 117, "head": "9abc1234ffff", "ids": ["metis-0384"], "core": False},
                         {"number": 116, "head": "0089995abc", "ids": ["metis-0245"], "core": True}]}}))
env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state, "PANTHEON_VIEW": view,
       "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "PANTHEON_FAKE_IDLE": "0",
       "PANTHEON_METRICS": "0", "TMPDIR": tmp, "PANTHEON_NOW": str(T0)}


def board_run(t=T0):
    return subprocess.run([PY311, "-I", CLI, "board"], env=dict(env, PANTHEON_NOW=str(t)), capture_output=True, text=True,
                          timeout=300)


r = board_run()
after = open(board_md, encoding="utf-8").read()
check("3. устаревшая доска + свежий STATUS → блок обновился: PR #116 и #117, вердикт, кто сливает, строка STATUS",
      r.returncode == 0 and "старое" not in after and "PR #117 agent-kit (metis-0384) · head 9abc123 · argus: a «принять»" in after
      and "PR #116 agent-kit (metis-0245)" in after and "сливает владелец" in after
      and "STATUS metis-pantheon, правка 24.10 01:40" in after and "PR #117 круг 2" in after, r.stdout + r.stderr + after)
check("3. ручные строки Зевса целы: текст вне маркеров байт в байт", outside(after) == outside(before)
      and outside(after) == MANUAL_HEAD + MANUAL_TAIL, after)
mt = os.stat(board_md).st_mtime_ns
r2 = board_run(T0 + 60)
check("3. входы те же → файл не переписан (время правки прежнее)", r2.returncode == 0 and os.stat(board_md).st_mtime_ns == mt
      and "автоблок обновлён" not in r2.stdout, r2.stdout + r2.stderr)
write(board_md, MANUAL_HEAD + B.BEGIN + "\n- обрывок\n" + MANUAL_TAIL)
broken = open(board_md, encoding="utf-8").read()
r3 = board_run(T0 + 120)
alerts = r3.stdout  # PANTHEON_DRYRUN: тревога печатается «[alert] …», а не в alerts.md
check("3. маркер без пары → файл не тронут, тревога «маркеры сломаны»", r3.returncode == 0
      and open(board_md, encoding="utf-8").read() == broken and "маркеры автоблока сломаны" in alerts, r3.stderr + alerts)

# --- 4. напоминание на Stop у Зевса ------------------------------------------------------------------------------
hb = os.path.join(ROOT, "hook")
hpan, hstate = os.path.join(hb, "ai", "pantheon"), os.path.join(hb, ".local", "state", "pantheon")
hboard = write(os.path.join(hpan, "board.md"), MANUAL_HEAD + B.BEGIN + "\n- PR, правка 24.10 05:00\n" + B.END + "\n" + MANUAL_TAIL)
hstatus = os.path.join(hpan, "directions", "metis-pantheon", "STATUS.md")
tr = write(os.path.join(hb, "tr", "t.jsonl"), "")
henv = {"PATH": os.environ["PATH"], "HOME": hb, "PANTHEON_HOME": hpan, "PANTHEON_STATE": hstate,
        "CLAUDE_CODE_ENTRYPOINT": "cli", "TMPDIR": ROOT}
ev = {"session_id": "s-zeus", "transcript_path": tr, "hook_event_name": "Stop", "stop_hook_active": False, "agent_type": "hq"}


def stop(e=None, **extra):
    r = subprocess.run([sys.executable, "-I", HOOK, "stop"], env=dict(henv, **extra), input=json.dumps(e or ev),
                       capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout).get("hookSpecificOutput", {}).get("additionalContext", "") if r.stdout.strip() else ""
    return r, out


write(hstatus, "x\n", ts("2026-10-24 01:30"))
r, out = stop()
check("4. «Сейчас» 01:00, STATUS Метиды 01:30 (30 мин) → напоминание, код 0; время блока (05:00) не в счёт",
      r.returncode == 0 and "раздел «Сейчас» отстал" in out and "24.10 01:00" in out and "30 мин" in out, r.stdout + r.stderr)
r, out = stop()
check("4. тот же STATUS → повтора нет", r.returncode == 0 and out == "", r.stdout)
write(hstatus, "y\n", ts("2026-10-24 01:29"))
r, out = stop()
check("4. STATUS на 29 мин позже «Сейчас» → тишина", r.returncode == 0 and out == "", r.stdout)
write(hstatus, "z\n", ts("2026-10-24 02:10"))
for name, e, extra in (("координатор", dict(ev, agent_type="domain-coordinator"), {}), ("субагент", dict(ev, agent_id="a1"), {}),
                       ("stop_hook_active", dict(ev, stop_hook_active=True), {}),
                       ("claude -p", ev, {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}), ("PANTHEON_CTX_OFF", ev, {"PANTHEON_CTX_OFF": "1"})):
    r, out = stop(e, **extra)
    check(f"4. {name} → тишина", r.returncode == 0 and out == "", r.stdout)
r, out = stop()
check("4. новая правка STATUS (02:10) → снова напоминание, «на 70 мин»", "70 мин" in out, r.stdout + r.stderr)
write(hboard, MANUAL_HEAD.replace("24.10 01:00 Пачка", "24.10 02:05 Пачка") + MANUAL_TAIL)
write(hstatus, "w\n", ts("2026-10-24 02:20"))
r, out = stop()
check("4. Зевс дописал «Сейчас» 02:05, STATUS 02:20 → тишина", r.returncode == 0 and out == "", r.stdout)
os.remove(hboard)
write(hstatus, "v\n", ts("2026-10-24 03:20"))
r, out = stop()
check("4. board.md нет → тишина, код 0", r.returncode == 0 and out == "", r.stdout + r.stderr)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
