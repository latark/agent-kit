#!/usr/bin/env python3
"""Отложенная вставка после сжатия (hooks/ctx.py, metis-0788 → долги metis-0793) и двойной захват в чистке записей:

- вставку выдаёт ровно один из одновременных хуков (clock, deferred, maint-post): отметка забирается rename в своё
  имя, а не os.remove — на APFS один файл успешно удаляют несколько процессов разом (Д-A);
- оболочка из hooks.json запускает python только при отметке своего процесса (<CLAUDE_PID>.<sid>.json, Д1);
- снятие старой отметки не уносит только что записанную новую (Д4: deferred_compact, sweep_deferred);
- после claude -r, respawn и /resume отметка переходит в продолженную сессию по sid и выдаётся один раз; отметки
  других сессий не трогаются; отметки умершего процесса и прошлой сессии процесса ждут на стоянке parked.<sid> (metis-0816);
- prune_records (ctx.py, бывшая строка 791) не ломает замок: удаление файла и его замка — под самим замком, а locked
  после захвата сверяет, что запер файл под этим именем.

Запуск: python3 -I plugins/pantheon/tests/test_ctx_deferred.py  (код выхода 0 — все прошли)
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "ctx.py")
HOOKS_JSON = os.path.join(os.path.dirname(HOOK), "hooks.json")
PY = os.environ.get("CTX_TEST_PYTHON") or sys.executable
tmp = os.path.realpath(tempfile.mkdtemp(prefix="ctx-deferred-test-"))
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


home = tmp
pantheon, state = os.path.join(home, "ai", "pantheon"), os.path.join(home, ".local", "state", "pantheon")
for d in (pantheon, state, os.path.join(home, "tr")):
    os.makedirs(d, exist_ok=True)
PID = str(os.getpid())
BASE = {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pantheon, "PANTHEON_VIEW": os.path.join(home, "v"),
        "PANTHEON_STATE": state, "CLAUDE_PID": PID, "CLAUDE_CODE_ENTRYPOINT": "cli", "TZ": "Europe/Moscow",
        "TMPDIR": tmp}
os.environ.update(BASE)  # модуль ctx в этом процессе берёт папки из окружения при загрузке
spec = importlib.util.spec_from_file_location("ctx_under_test", HOOK)
ctx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctx)
DEFD = os.path.join(state, "ctx", "deferred")
HLOG = os.path.join(state, "logs", "ctx-hooks.log")


def run(cmd, ev, **env):
    e = dict(BASE)
    for k, v in env.items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = v
    return subprocess.run([PY, "-I", HOOK, cmd], input=json.dumps(ev), env=e, capture_output=True, text=True, timeout=60)


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def boundary(t):
    return {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted", "timestamp": iso(t)}


def append(p, d):
    with open(p, "a") as fh:
        fh.write(json.dumps(d, ensure_ascii=False) + "\n")


def mark_of(sid, pid=PID):
    return os.path.join(DEFD, "%s.%s.json" % (pid, sid))


def live_sub(tp, sid):
    p = os.path.join(os.path.dirname(tp), sid, "subagents", "agent-a1.jsonl")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "a").close()
    os.utime(p)


def ctx_text(out):
    try:
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError):
        return ""


hand = os.path.join(pantheon, "handoff", "race", "HANDOFF.md")
os.makedirs(os.path.dirname(hand))
open(hand, "w").write("# Передача дел\n\nКодовое слово: СЛИВА\n")


def session(sid):
    """Сессия без роли с файлом передачи дел в транскрипте — его и выдаёт вставка после сжатия."""
    tp = os.path.join(home, "tr", sid + ".jsonl")
    now = time.time()
    with open(tp, "w") as fh:
        for d in ({"type": "user", "isSidechain": False, "promptId": sid + "-1", "timestamp": iso(now - 300),
                   "message": {"role": "user", "content": "сохрани дела"}, "origin": {"kind": "human"}},
                  {"type": "assistant", "isSidechain": False, "timestamp": iso(now - 280),
                   "message": {"role": "assistant", "content": [
                       {"type": "tool_use", "name": "Write", "input": {"file_path": hand, "content": "x"}}]}}):
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    return {"session_id": sid, "transcript_path": tp, "source": "compact"}


# --- Д1: отметка с PID процесса, оболочка из hooks.json смотрит только свою -------------------------------------
ms = session("s-race")
live_sub(ms["transcript_path"], "s-race")
r = run("start", ms)
check("сжатие при живом субагенте → отметка <CLAUDE_PID>.<sid>.json", os.path.exists(mark_of("s-race")),
      sorted(os.listdir(DEFD)) if os.path.isdir(DEFD) else r.stderr)
append(ms["transcript_path"], boundary(time.time() + 1))
mark_saved = open(mark_of("s-race"), "rb").read() if os.path.exists(mark_of("s-race")) else b"{}"

with open(HOOKS_JSON) as fh:
    sh = [h["command"] for m in json.load(fh)["hooks"]["PostToolUse"] for h in m["hooks"]
          if h["command"].endswith("ctx.py\" deferred; done")]
sh = sh[0] if len(sh) == 1 else "echo PYTHON-STARTED"
FAKE_ROOT = os.path.join(home, "fake-plugin")  # корень плагина, где hooks/python.sh — заглушка вместо python
os.makedirs(os.path.join(FAKE_ROOT, "hooks"))
with open(os.path.join(FAKE_ROOT, "hooks", "python.sh"), "w") as fh:
    fh.write('#!/bin/sh\necho "PYTHON-STARTED $*"\n')


def shell(pid):
    e = dict(BASE, CLAUDE_PLUGIN_ROOT=FAKE_ROOT, PATH="/usr/bin:/bin")
    if pid is None:
        e.pop("CLAUDE_PID")
    else:
        e["CLAUDE_PID"] = pid
    r = subprocess.run(["sh", "-c", sh], input="{}", env=e, capture_output=True, text=True, timeout=30)
    return r.stdout.strip(), r.returncode


started = "PYTHON-STARTED %s/hooks/ctx.py deferred" % FAKE_ROOT
check("оболочка: отметка этого процесса (её записал start) → python запускается один раз",
      shell(PID) == (started, 0), shell(PID))
check("оболочка: отметка только другого процесса → python не запускается (Д1)", shell("1") == ("", 0), shell("1"))
check("оболочка: CLAUDE_PID не число → ищет nopid.*, чужую отметку не видит", shell("12a") == ("", 0), shell("12a"))
open(mark_of("x", "nopid"), "w").close()
check("оболочка: без CLAUDE_PID → своя отметка nopid.* запускает python", shell(None) == (started, 0), shell(None))
check("оболочка: CLAUDE_PID не число → тоже nopid.*", shell("12a") == (started, 0), shell("12a"))
os.remove(mark_of("x", "nopid"))
open(mark_of("x", PID + "0"), "w").close()
check("оболочка: PID-префикс другого процесса (<pid>0) не совпадает со своим", shell("1") == ("", 0)
      and sorted(os.listdir(DEFD)) == sorted([os.path.basename(mark_of("s-race")), os.path.basename(mark_of("x", PID + "0"))]),
      os.listdir(DEFD))
os.remove(mark_of("x", PID + "0"))
check("python: defer_path берёт PID так же, как оболочка (не число → nopid)",
      os.path.basename(ctx.defer_path("s/x")) == "%s.sx.json" % PID, ctx.defer_path("s/x"))

# --- Д-A: ровно одна выдача при одновременных хуках --------------------------------------------------------------
# модель APFS: os.remove не исключителен — удаление файла, который уже удалил другой, тоже «успешно»
real_remove = os.remove


def apfs_remove(p, *a, **kw):
    try:
        real_remove(p, *a, **kw)
    except FileNotFoundError:
        pass


os.makedirs(DEFD, exist_ok=True)
pm = os.path.join(DEFD, "model.json")
open(pm, "w").write("{}")
os.remove = apfs_remove
try:
    got = [ctx.claim_mark(pm), ctx.claim_mark(pm)]
finally:
    os.remove = real_remove
check("claim_mark: при неисключительном remove (как на APFS) забирает ровно один из двух вызовов",
      got == [True, False] and not os.path.exists(pm), got)

# гонка процессов: каждый грузит ctx.py и читает событие заранее, потом все разом стартуют по файлу-флагу
RUNNER = os.path.join(tmp, "race_runner.py")
with open(RUNNER, "w") as fh:
    fh.write("""import importlib.util, os, sys, time
hook, cmd, go = sys.argv[1:4]
spec = importlib.util.spec_from_file_location("ctx_race", hook)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
ev = m.read_event()
fn = {"deferred": m.cmd_deferred, "clock": m.cmd_clock, "maint-post": m.cmd_maint_post}[cmd]
open(go + "." + str(os.getpid()), "w").close()
while not os.path.exists(go):
    time.sleep(0.0002)
sys.exit(fn(ev))
""")
race_bad, rounds = [], 25
cmds = ("deferred", "deferred", "clock", "maint-post", "deferred", "clock")
for i in range(rounds):
    with open(mark_of("s-race"), "wb") as fh:
        fh.write(mark_saved)
    go = os.path.join(tmp, "go-%d" % i)
    ps = [subprocess.Popen([PY, "-I", RUNNER, HOOK, c, go], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=BASE, text=True) for c in cmds]
    for pr in ps:
        pr.stdin.write(json.dumps(dict(ms, hook_event_name="PostToolUse", tool_name="Read", prompt="x")))
        pr.stdin.close()
        pr.stdin = None  # communicate иначе пишет в закрытый поток
    deadline = time.time() + 30
    while time.time() < deadline and sum(n.startswith("go-%d." % i) for n in os.listdir(tmp)) < len(ps):
        time.sleep(0.005)
    open(go, "w").close()
    outs = [pr.communicate(timeout=60)[0] for pr in ps]
    n = sum("СЛИВА" in o for o in outs)
    if n != 1 or os.path.exists(mark_of("s-race")):
        race_bad.append(n)
check("гонка: 6 одновременных deferred/clock/maint-post × %d → выдача ровно одна, отметка снята, хвостов .claim нет"
      % rounds, not race_bad and not [x for x in os.listdir(DEFD) if ".claim" in x], race_bad)

# --- Д4: снятие старой отметки не уносит только что записанную новую ----------------------------------------------
fresh = json.dumps({"session_id": "s-d4", "t": time.time(), "role": "", "tp": "", "off": None}).encode()
p4 = mark_of("s-d4")
with open(p4, "wb") as fh:
    fh.write(fresh)
check("claim_mark(seen=байты старой): под именем уже другая отметка → False, новая на месте",
      ctx.claim_mark(p4, b'{"t": 1}') is False and open(p4, "rb").read() == fresh
      and not [x for x in os.listdir(DEFD) if ".claim" in x], os.listdir(DEFD))
check("claim_mark(seen=те же байты) → True, отметка снята", ctx.claim_mark(p4, fresh) and not os.path.exists(p4))


def stale(p, age=1000):
    with open(p, "w") as fh:
        json.dump({"session_id": "s-d4", "t": time.time() - age, "role": "", "tp": "", "off": None}, fh)
    os.utime(p, (time.time() - age, time.time() - age))


def rewrite_then(real, p):
    """Обёртка шага проверки: перед ответом новое сжатие записывает свежую отметку (как defer_compact)."""
    def f(*a, **kw):
        ctx.save_json(p, json.loads(fresh))
        return real(*a, **kw)
    return f


stale(p4)
real_dead = ctx.pid_dead
ctx.pid_dead = rewrite_then(real_dead, p4)
try:
    ctx.sweep_deferred()
finally:
    ctx.pid_dead = real_dead
check("sweep_deferred: просроченную отметку подменила свежая между чтением и снятием → свежая цела (Д4)",
      os.path.exists(p4) and json.load(open(p4))["t"] > time.time() - 60, os.listdir(DEFD))
real_cb = ctx.compact_boundary_since
for why, ev4 in (("границы нет, срок вышел", session("s-d4")), ("граница есть, выдача", dict(ms, session_id="s-d4"))):
    stale(p4)
    ctx.compact_boundary_since = rewrite_then(real_cb, p4)
    try:
        out = ctx.deferred_compact(ev4, "deferred", 9000)
    finally:
        ctx.compact_boundary_since = real_cb
    check("deferred_compact (%s): старую отметку подменила свежая до снятия → без вставки, свежая цела (Д4)" % why,
          out == [] and os.path.exists(p4) and json.load(open(p4))["t"] > time.time() - 60, os.listdir(DEFD))
stale(p4)
ctx.sweep_deferred()
check("sweep_deferred без подмены: просроченная без границы снята", not os.path.exists(p4), os.listdir(DEFD))

# --- отметка умершего процесса и прошлой сессии этого процесса --------------------------------------------------
dead = subprocess.Popen([PY, "-I", "-c", "pass"])
dead.wait()
for p in (mark_of("s-gone", str(dead.pid)), mark_of("s-old"), mark_of("s-other", "1")):
    with open(p, "w") as fh:
        json.dump({"session_id": "x", "t": time.time(), "role": ""}, fh)
r = run("start", {"session_id": "s-new", "transcript_path": os.path.join(home, "tr", "s-new.jsonl"), "source": "clear"})
left = sorted(os.listdir(DEFD))
check("start: свежая отметка умершего процесса ушла из его PID на стоянку parked.<sid> (metis-0816)",
      os.path.basename(mark_of("s-gone", str(dead.pid))) not in left and "parked.s-gone.json" in left, left)
check("start: отметка прошлой сессии этого процесса (/clear) — на стоянке, живого чужого процесса — цела",
      os.path.basename(mark_of("s-old")) not in left and "parked.s-old.json" in left
      and os.path.basename(mark_of("s-other", "1")) in left, left)
check("оболочка: отметок своего PID не осталось → python не запускается", shell(PID) == ("", 0), shell(PID))
for x in (mark_of("s-other", "1"), mark_of("s-gone", "parked"), mark_of("s-old", "parked")):
    os.remove(x)
with open(mark_of("s-new"), "w") as fh:
    json.dump({"session_id": "s-new", "t": time.time(), "role": ""}, fh)
run("start", {"session_id": "s-new", "transcript_path": os.path.join(home, "tr", "s-new.jsonl"), "source": "resume"})
check("start той же сессии свою свежую отметку не снимает", os.path.exists(mark_of("s-new")), os.listdir(DEFD))
r = run("start", {"session_id": "s-new2", "transcript_path": os.path.join(home, "tr", "s-new.jsonl"), "source": "clear"},
        CLAUDE_CODE_ENTRYPOINT="sdk-cli")
check("start в claude -p (sdk) отметки процесса не трогает", os.path.exists(mark_of("s-new")), os.listdir(DEFD))
shutil.rmtree(DEFD)

# --- metis-0816: claude -r, respawn и /resume — отметка переходит в продолженную сессию по sid ---------------------


def tool_ev(ev):
    return dict(ev, hook_event_name="PostToolUse", tool_name="Read", prompt="x", source=None)


def deliveries(ev, cmds=("deferred", "clock", "deferred", "maint-post"), **env):
    """Какие хуки подряд выдали вставку (кодовое слово из файла передачи дел)."""
    return [("СЛИВА" in ctx_text(run(c, tool_ev(ev), **env).stdout)) for c in cmds]


def defer_at(sid, pid):
    """Сжатие при живом субагенте в процессе pid → отметка pid.sid; граница сжатия — следом в транскрипт."""
    ev = session(sid)
    live_sub(ev["transcript_path"], sid)
    run("start", ev, CLAUDE_PID=pid)
    ok = os.path.exists(mark_of(sid, pid))
    append(ev["transcript_path"], boundary(time.time() + 1))
    return ev, ok


def ls():
    return sorted(os.listdir(DEFD)) if os.path.isdir(DEFD) else []


# claude -r / respawn: старый процесс умер, между его смертью и продолжением стартует другая сессия Mac (чистка)
old_proc = subprocess.Popen(["sleep", "60"])
ev_r, ok = defer_at("s-cr", str(old_proc.pid))
old_proc.kill()
old_proc.wait()
run("start", {"session_id": "s-bystander", "transcript_path": os.path.join(home, "tr", "s-by.jsonl"), "source": "startup"},
    CLAUDE_PID="1")
check("claude -r: отметка умершего процесса чисткой другой сессии не снята, а ушла на стоянку",
      ok and "parked.s-cr.json" in ls() and os.path.basename(mark_of("s-cr", str(old_proc.pid))) not in ls(), ls())
run("start", dict(ev_r, source="resume"))  # новый процесс (CLAUDE_PID = PID), тот же sid
check("claude -r: start продолженной сессии перенёс отметку в своё имя <новый PID>.<sid>, стоянка пуста",
      ls() == [os.path.basename(mark_of("s-cr"))], ls())
check("claude -r: оболочка hooks.json нового процесса видит перенесённую отметку", shell(PID) == (started, 0), shell(PID))
got = deliveries(ev_r)
check("claude -r: вставка старой сессии выдана в продолженную ровно один раз (deferred, clock, deferred, maint-post)",
      got.count(True) == 1 and ls() == [], (got, ls()))

# respawn, пока старый процесс ещё жив: отметку забирает продолженная сессия, старый процесс её больше не выдаёт
old_proc = subprocess.Popen(["sleep", "60"])
try:
    ev_r, ok = defer_at("s-rs", str(old_proc.pid))
    run("start", dict(ev_r, source="resume"))
    moved = ls() == [os.path.basename(mark_of("s-rs"))]
    got = deliveries(ev_r, ("deferred",), CLAUDE_PID=str(old_proc.pid)) + deliveries(ev_r)
finally:
    old_proc.kill()
    old_proc.wait()
check("respawn при живом старом процессе: отметка перенесена, выдача одна — в новом процессе, не в старом",
      ok and moved and got == [False, True, False, False, False] and ls() == [], (ok, moved, got, ls()))

# /resume в том же процессе после /clear: отметка ждёт на стоянке, /resume обратно её забирает
ev_c, ok = defer_at("s-back", PID)
run("start", {"session_id": "s-other2", "transcript_path": os.path.join(home, "tr", "s-o2.jsonl"), "source": "clear"})
parked = ls() == ["parked.s-back.json"] and shell(PID) == ("", 0)
run("start", dict(ev_c, source="resume"))
got = deliveries(ev_c)
check("/resume обратно после /clear: отметка со стоянки вернулась, вставка выдана один раз",
      ok and parked and got.count(True) == 1 and ls() == [], (ok, parked, got, ls()))

# отметки других сессий продолжение не трогает: ни живого чужого процесса, ни стоянки, ни sid с тем же началом
ev_m = session("s-mine")
alien = {mark_of("s-alien", "1"): b'{"session_id": "s-alien", "t": %f}' % time.time(),
         mark_of("s-alien2", "parked"): b'{"session_id": "s-alien2", "t": %f}' % time.time(),
         mark_of("s-mine2", "1"): b'{"session_id": "s-mine2", "t": %f}' % time.time()}
os.makedirs(DEFD, exist_ok=True)
for x, b in alien.items():
    with open(x, "wb") as fh:
        fh.write(b)
before = {x: os.stat(x).st_ino for x in alien}
run("start", dict(ev_m, source="resume"))
got = deliveries(ev_m, ("deferred", "clock"))
check("чужие отметки (другой sid, в том числе s-mine2) не перенесены и не выданы: имена, байты и inode те же",
      got == [False, False] and ls() == sorted(os.path.basename(x) for x in alien)
      and all(open(x, "rb").read() == b and os.stat(x).st_ino == before[x] for x, b in alien.items()), (got, ls()))
for x in alien:
    os.remove(x)

# у продолженной сессии уже есть своя отметка: остаётся она, перенесённая снимается, выдача одна
ev_d, ok = defer_at("s-dup", PID)
own_b = open(mark_of("s-dup"), "rb").read() if ok else b""
with open(mark_of("s-dup", "1"), "w") as fh:
    json.dump({"session_id": "s-dup", "t": time.time(), "role": "", "tp": "", "off": None}, fh)
run("start", dict(ev_d, source="resume"))
kept = ls() == [os.path.basename(mark_of("s-dup"))] and open(mark_of("s-dup"), "rb").read() == own_b
got = deliveries(ev_d)
check("своя отметка и чужая того же sid: своя цела, чужая снята, вставка одна",
      ok and kept and got.count(True) == 1 and ls() == [], (ok, kept, got, ls()))

# claude -p (sdk) с тем же sid отметку не забирает — её ждёт продолжение в окне
with open(mark_of("s-sdk", "1"), "w") as fh:
    json.dump({"session_id": "s-sdk", "t": time.time()}, fh)
run("start", {"session_id": "s-sdk", "transcript_path": os.path.join(home, "tr", "s-sdk.jsonl"), "source": "resume"},
    CLAUDE_CODE_ENTRYPOINT="sdk-cli")
check("claude -p -r (sdk): отметку той же сессии не переносит", ls() == [os.path.basename(mark_of("s-sdk", "1"))], ls())
os.remove(mark_of("s-sdk", "1"))

# стоянка подчиняется срокам чистки: без границы старше 15 мин — снята, свежая — цела
for sid, age in (("s-p-old", 1000), ("s-p-new", 100)):
    with open(mark_of(sid, "parked"), "w") as fh:
        json.dump({"session_id": sid, "t": time.time() - age, "tp": "", "off": None}, fh)
    os.utime(mark_of(sid, "parked"), (time.time() - age, time.time() - age))
ctx.sweep_deferred()
check("стоянка: просроченная без границы снята, свежая цела", ls() == ["parked.s-p-new.json"], ls())
shutil.rmtree(DEFD)

# перенос (park и adopt) идёт link, а не копией: inode и время записи те же — срок отметки не продлевается
dead = subprocess.Popen([PY, "-I", "-c", "pass"])
dead.wait()
os.makedirs(DEFD, exist_ok=True)
p = mark_of("s-mt", str(dead.pid))
with open(p, "w") as fh:
    json.dump({"session_id": "s-mt", "t": time.time() - 300, "tp": "", "off": None}, fh)
os.utime(p, (time.time() - 300, time.time() - 300))
st0 = os.stat(p)
ctx.sweep_deferred()
pk = mark_of("s-mt", "parked")
st1 = os.stat(pk) if os.path.exists(pk) else None
check("стоянка (park): inode и mtime отметки те же, что до переноса",
      st1 is not None and (st1.st_ino, st1.st_mtime_ns) == (st0.st_ino, st0.st_mtime_ns),
      (ls(), st0, st1))
ctx.adopt_marks("s-mt")
st2 = os.stat(mark_of("s-mt")) if os.path.exists(mark_of("s-mt")) else None
check("продолжение (adopt): inode и mtime отметки те же, что до переноса, стоянка пуста",
      st2 is not None and (st2.st_ino, st2.st_mtime_ns) == (st0.st_ino, st0.st_mtime_ns) and ls() == ["%s.s-mt.json" % PID],
      (ls(), st0, st2))
shutil.rmtree(DEFD)


# сбой ФС при переносе (не ENOENT) не роняет SessionStart: вставка после сжатия, часы и чистка выдаются (Б1 круга 1)
def hlog_has(s):
    try:
        with open(HLOG, encoding="utf-8") as fh:
            return s in fh.read()
    except OSError:
        return False


os.makedirs(DEFD, exist_ok=True)
ev_ro = session("s-ro")
pk = mark_of("s-ro", "parked")
body = b'{"session_id": "s-ro", "t": %f}' % time.time()
with open(pk, "wb") as fh:
    fh.write(body)
os.chmod(DEFD, 0o555)
try:
    r = run("start", ev_ro)
finally:
    os.chmod(DEFD, 0o755)
check("deferred только для чтения + отметка этого sid на стоянке: SessionStart:compact выдаёт вставку, код 0",
      r.returncode == 0 and "СЛИВА" in ctx_text(r.stdout), (r.returncode, r.stdout[:200], r.stderr[-300:]))
check("deferred только для чтения: отметка не потеряна (байты те же), сбой переноса — в журнале хуков",
      ls() == ["parked.s-ro.json"] and open(pk, "rb").read() == body and hlog_has("parked.s-ro.json не перенесена"),
      ls())
os.remove(pk)

ev_ln = session("s-long")
n = "9" * (255 - len(".s-long.json") - 2) + ".s-long.json"  # своё имя влезает в NAME_MAX, имя .claim — нет
pl = os.path.join(DEFD, n)
with open(pl, "wb") as fh:
    fh.write(b'{"session_id": "s-long", "t": %f}' % time.time())
r = run("start", ev_ln)
check("имя .claim длиннее NAME_MAX: SessionStart:compact выдаёт вставку, код 0",
      r.returncode == 0 and "СЛИВА" in ctx_text(r.stdout), (r.returncode, r.stdout[:200], r.stderr[-300:]))
check("имя .claim длиннее NAME_MAX: отметка на месте, сбой переноса — в журнале хуков",
      ls() == [n] and hlog_has("%s не перенесена" % n), ls())
shutil.rmtree(DEFD)

# --- ctx.py:791 prune_records: двойной захват замка -------------------------------------------------------------
CTXD = os.path.join(state, "ctx")
old_t = time.time() - 40 * 86400


def prep(name, with_lock=True):
    p = os.path.join(CTXD, name)
    open(p, "w").write("{}")
    os.utime(p, (old_t, old_t))
    if with_lock:
        open(p + ".lock", "w").close()
        os.utime(p + ".lock", (old_t, old_t))
    try:
        os.remove(os.path.join(CTXD, ".pruned"))
    except FileNotFoundError:
        pass
    return p


p = prep("proc-race.json")
inside, peak, bad_ino, lk = [0], [0], [], threading.Lock()


def holder(entered):
    with ctx.locked(p) as L:
        with lk:
            inside[0] += 1
            peak[0] = max(peak[0], inside[0])
        entered.set()
        try:
            if os.fstat(L.fd).st_ino != os.stat(L.path).st_ino:
                bad_ino.append("замок под именем — не тот, что заперт")
        except FileNotFoundError:
            bad_ino.append("замка под именем нет")
        time.sleep(0.4)
        with lk:
            inside[0] -= 1


threads = []


def remove_racing(path, *a, **kw):
    """Чистка удаляет замок: в этот момент хук A пытается войти, а сразу после удаления — хук B."""
    if path == p + ".lock":
        ea, eb = threading.Event(), threading.Event()
        ta = threading.Thread(target=holder, args=(ea,))
        ta.start()
        ea.wait(0.3)  # старая чистка замок не держит — A входит; новая держит — A ждёт на нём
        real_remove(path, *a, **kw)
        tb = threading.Thread(target=holder, args=(eb,))
        tb.start()
        eb.wait(0.2)
        threads.extend([ta, tb])
        return None
    return real_remove(path, *a, **kw)


os.remove = remove_racing
try:
    ctx.prune_records()
finally:
    os.remove = real_remove
for t in threads:
    t.join(10)
check("prune_records: замок удаляется под самим замком — два хука в нём разом не оказываются (ctx.py:791)",
      len(threads) == 2 and peak[0] == 1 and not bad_ino, (len(threads), peak[0], bad_ino))
check("prune_records: старый файл с замком снят", not os.path.exists(p), os.listdir(CTXD))

p = prep("proc-fresh.json")
ctx.save_json(p, {"x": 1})
ctx.prune_records()
check("prune_records: свежий файл не трогается, его замок тоже", os.path.exists(p) and os.path.exists(p + ".lock"))
pm = prep("mark-old", with_lock=False)
pf = os.path.join(CTXD, "mark-fresh")
open(pf, "w").write("1")
q = os.path.join(CTXD, ".mark-fresh.claim")
ctx.prune_unlocked(pf, q, old_t + 86400)  # файл переписан после проверки срока — он свежий
check("prune_unlocked: файл переписали после проверки срока → возвращён на место, не удалён",
      os.path.exists(pf) and open(pf).read() == "1" and not os.path.exists(q), os.listdir(CTXD))
ctx.prune_records()
check("prune_records: старый файл без замка снят, хвостов .prune нет",
      not os.path.exists(pm) and not [x for x in os.listdir(CTXD) if x.endswith(".prune")], os.listdir(CTXD))

shutil.rmtree(tmp, ignore_errors=True)
print("%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
