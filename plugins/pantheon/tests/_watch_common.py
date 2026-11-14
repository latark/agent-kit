# ruff: noqa: F401, F403, F405  (импорты общей части нужны частям через import *)
"""Общая часть test_watch*.py (образец metis-0750, план 1.0 Т2): заглушка claude, Env, помощники и константы дежурного. Сами случаи — в test_watch.py и test_watch_<часть>.py; здесь тестов нет."""
import hashlib
import re
import json
import shutil
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311, mkroot  # noqa: E402
import tempfile
# Все временные папки файла — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение);
# TMPDIR — для подпроцессов, которые тоже создают временные папки. Общий TMPDIR остаётся чистым.
import atexit as _atexit
import os as _os
import shutil as _shutil
_ROOT = mkroot("watch-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
T0 = 1_792_000_000
NIGHT_OFF = '[night]\nask_at = "00:00"\n[limits.night]\nstart = "00:00"\nend = "00:00"\n'
FAILS = []

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
log = os.environ["FAKE_CLAUDE_LOG"]
open(log, "a").write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
a = sys.argv[1:]
if a[:1] == ["agents"]:
    cnt = os.environ.get("FAKE_AGENTS_COUNT")  # metis-1192: первые FAKE_AGENTS_GOOD вызовов — список, дальше не JSON
    if cnt:
        n = len(open(cnt).read()) if os.path.exists(cnt) else 0
        open(cnt, "a").write(".")
        if n >= int(os.environ.get("FAKE_AGENTS_GOOD") or "1"):
            print("Error: daemon not ready")
            sys.exit(0)
    if os.environ.get("FAKE_AGENTS_SLEEP"):  # metis-1175: claude agents не отвечает
        import time
        time.sleep(float(os.environ["FAKE_AGENTS_SLEEP"]))
    slow = os.environ.get("FAKE_AGENTS_SLOW_NEXT")  # metis-1180: первый вызов отвечает, все следующие спят 5 с
    if slow and os.path.exists(slow):
        import time
        time.sleep(5)
    elif slow:
        open(slow, "w").close()
    nxt = os.environ.get("FAKE_AGENTS_NEXT")       # первый вызов — FAKE_AGENTS, все следующие — этот файл
    if nxt and os.path.exists(nxt + ".seen"):
        print(open(nxt).read())
    else:
        if nxt:
            open(nxt + ".seen", "w").close()
        print(open(os.environ["FAKE_AGENTS"]).read())
elif a[:1] == ["--version"]:
    print(os.environ.get("FAKE_CC", "2.1.292") + " (Claude Code)")
elif a[:1] == ["respawn"] and os.environ.get("FAKE_RESPAWN_RC"):
    print("respawn: no such session", file=sys.stderr)
    sys.exit(int(os.environ["FAKE_RESPAWN_RC"]))
elif a[:1] == ["stop"] and a[1:2] and a[1] in os.environ.get("FAKE_STOP_FAIL", "").split(","):
    print("stop: no such session", file=sys.stderr)
    sys.exit(1)
elif a[:1] == ["stop"] and os.environ.get("FAKE_STOP_MARK"):
    lst = json.load(open(os.environ["FAKE_AGENTS"]))
    for x in lst:
        if x.get("id") == a[1]:
            x.update(state="stopped", pid=None)
    json.dump(lst, open(os.environ["FAKE_AGENTS"], "w"))
elif a[:1] == ["rm"] and a[1:2] and a[1] in os.environ.get("FAKE_RM_REFUSE", "").split(","):
    print("refusing: worktree has unpushed commits (abc123@wt-1)", file=sys.stderr)
    sys.exit(1)
elif a[:1] == ["--bg"] and os.environ.get("FAKE_BG_SLEEP"):
    import time
    time.sleep(float(os.environ["FAKE_BG_SLEEP"]))
elif "--resume" in a and os.environ.get("FAKE_RESUME_RC"):
    print("resume: failed", file=sys.stderr)
    sys.exit(int(os.environ["FAKE_RESUME_RC"]))
elif "--resume" in a:
    print(os.environ.get("FAKE_RESUME_OUT", "backgrounded"))
else:
    print("ok")
'''


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("НЕ ПРОШЛО:", what)


class Env:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="watch-test-")
        self.home = os.path.join(self.tmp, "home")
        self.pantheon = os.path.join(self.home, "ai", "pantheon")
        self.state = os.path.join(self.tmp, "state")
        self.bin = os.path.join(self.tmp, "bin")
        for d in (self.pantheon, self.state, self.bin, os.path.join(self.state, "settings"),
                  os.path.join(self.state, "owner-log")):
            os.makedirs(d, exist_ok=True)
        open(os.path.join(self.bin, "claude"), "w").write(FAKE_CLAUDE)
        os.chmod(os.path.join(self.bin, "claude"), 0o755)
        # caffeinate — заглушка: «запрет сна Mac» (lib/awake.py) в тестах настоящий Mac не держит
        self.caff = os.path.join(self.tmp, "caffeinate.log")
        open(os.path.join(self.bin, "caffeinate"), "w").write(f'#!/bin/sh\necho "$@" >> "{self.caff}"\n')
        os.chmod(os.path.join(self.bin, "caffeinate"), 0o755)
        self.log = os.path.join(self.tmp, "claude.log")
        self.agents_file = os.path.join(self.tmp, "agents.json")
        self.notify = os.path.join(self.tmp, "notify.log")
        self.agents([])
        # ночной цикл (lib/night.py) здесь выключен: вопрос в 00:00 и конец ночи в 00:00 — ночи нет, днём только темп
        # недели; ночь и вопрос проверяет test_night.py
        self.schedule('primary_host = "mac-a"\n[defaults]\nlimit_max_pct = 70\n')
        self.doms = {}
        self.week_pct, self.snap_age = 10.0, 0  # снимок недельного лимита в run(): зелёная зона, свежий
        # уведомления идут через политику (metis-0023): простой — явно, по умолчанию «вы у Mac»
        # батарея и розетка подменены (metis-0210): иначе lib/awake.py читает настоящий pmset, и тест краснеет
        # на Mac с низким зарядом; тесты, которым нужна батарея, переопределяют через extra
        self.extra = {"PANTHEON_FAKE_IDLE": "0", "PANTHEON_FAKE_BATT": "100", "PANTHEON_FAKE_AC": "1"}
        # metis-0359: короткие ожидания имени и остановки — во всех проходах, а не только где передан QUICK. Без них
        # каждый самозапуск ждал появления сессии PANTHEON_NAME_WAIT по умолчанию (10 с, заглушка claude её не
        # показывает): ~37 таких проходов — 430 с файла из 435, а в фоне тика (ProcessType Background) — за 600 с.
        # Тест, которому нужно настоящее ожидание, передаёт своё значение в extra.
        self.extra.update(QUICK)

    def schedule(self, text):
        """schedule.toml теста: text плюс выключенная ночь (вопрос и конец ночи в 00:00). Без этого ночь 23:00–08:00 по
        умолчанию зависит от часового пояса машины, на которой идут тесты (metis-0459)."""
        open(os.path.join(self.pantheon, "schedule.toml"), "w").write(text + NIGHT_OFF)

    def notify_mode(self, idle, quiet=None):
        """Простой (с) и тихие часы для политики уведомлений: quiet=None — без тихих часов (как днём),
        quiet=(начало, конец) — свои, например ("12:00", "11:59") — тихо всегда, кроме минуты 11:59 (как ночью)."""
        self.extra["PANTHEON_FAKE_IDLE"] = str(idle)
        a, b = quiet or ("00:00", "00:00")
        p = os.path.join(self.pantheon, "schedule.toml")
        text = open(p).read().split("\n[notify]")[0]
        open(p, "w").write(text + f'\n[notify]\nquiet_start = "{a}"\nquiet_end = "{b}"\n')

    def sent(self):
        return open(self.notify, encoding="utf-8").read() if os.path.exists(self.notify) else ""

    def queued(self):
        p = os.path.join(self.state, "notify.json")
        return [x.get("id") for x in json.load(open(p)).get("queue", [])] if os.path.exists(p) else []

    def agents(self, lst):
        json.dump(lst, open(self.agents_file, "w"))

    def direction(self, name, trusted=True):
        folder = os.path.join(self.home, "projects", name)
        os.makedirs(os.path.join(folder, ".git"), exist_ok=True)
        os.makedirs(os.path.join(self.pantheon, "directions", name, "tasks"), exist_ok=True)
        self.doms[name] = [folder]
        json.dump({"domains": self.doms}, open(os.path.join(self.state, "domains.json"), "w"))
        json.dump({"env": {}}, open(os.path.join(self.state, "settings", name + ".json"), "w"))
        cj = os.path.join(self.home, ".claude.json")
        data = json.load(open(cj)) if os.path.exists(cj) else {"projects": {}}
        data["projects"][os.path.realpath(folder)] = {"hasTrustDialogAccepted": trusted}
        json.dump(data, open(cj, "w"))
        return folder

    def task(self, tid, direction, status="todo", extra="", updated="2026-10-15T07:00:00", priority=2):
        p = os.path.join(self.pantheon, "directions", direction, "tasks", tid + ".md")
        open(p, "w").write(f"---\ntype: task\nid: {tid}\ntitle: проба\nstatus: {status}\nproject: {direction}\n"
                           f"direction: {direction}\ncreated: 2026-10-15\nupdated: {updated}\n"
                           f"schema_version: 1\npriority: {priority}\n{extra}---\n\nтекст\n")

    def board(self, tid, t, kind="move", dst="Очередь"):
        rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)), "kind": kind, "id": tid, "dst": dst}
        with open(os.path.join(self.state, "owner-log", "board.jsonl"), "a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def run(self, *args, t=T0, extra=None, argv=None):
        # свежий снимок лимита строки статуса (lib/night.py): без него самозапуск закрыт — «лимит неизвестен»
        sl = os.path.join(self.home, ".local", "state", "claude-statusline")
        os.makedirs(sl, exist_ok=True)
        # неделя week_pct % при сбросе через 5 суток (линия ~28,6 %), снимок сделан snap_age с назад
        obs = t - self.snap_age
        open(os.path.join(sl, "five-hour"), "w").write(f"10 {t + 3600:.0f} {obs:.0f}\n")
        open(os.path.join(sl, "seven-day"), "w").write(f"{self.week_pct:g} {t + 5 * 86400:.0f} {obs:.0f}\n")
        env = {"PATH": self.bin + ":" + os.environ["PATH"], "HOME": self.home, "PANTHEON_HOME": self.pantheon,
               "PANTHEON_STATE": self.state, "PANTHEON_NOW": str(t), "PANTHEON_HOST": "mac-a",
               "PANTHEON_NOTIFY_LOG": self.notify, "FAKE_CLAUDE_LOG": self.log, "FAKE_AGENTS": self.agents_file,
               "PANTHEON_FAKE_SWAP": "1.0", "PANTHEON_FAKE_PRESSURE": "1", "PANTHEON_FAKE_PS": "", "PANTHEON_FAKE_CC": "2.1.292",
               "PANTHEON_FAKE_LIMIT": "10", "PANTHEON_CAFFEINATE": os.path.join(self.bin, "caffeinate")}
        if "TZ" in os.environ:  # дочерний процесс в том же поясе, что и тест, который считает местное время (metis-0222)
            env["TZ"] = os.environ["TZ"]
        env.update(self.extra)
        env.update(extra or {})
        # 180 с, а не 60 (metis-1022): проход watch при load ~40 шёл дольше минуты, и тест падал обрывом, а не проверкой
        return subprocess.run([*(argv or [PY311, "-I", RUN_PY]), *args], env=env, capture_output=True, text=True,
                              timeout=180)

    def calls(self):
        if not os.path.exists(self.log):
            return []
        return [json.loads(ln)["argv"] for ln in open(self.log)]

    def alerts(self):
        p = os.path.join(self.pantheon, "alerts.md")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    def st(self, *parts):
        return os.path.join(self.state, *parts)


def bg(name, state, sid, pid=None, started=T0 - 100):
    return {"id": sid[:8], "sessionId": sid, "name": name, "state": state, "pid": pid, "kind": "background",
            "cwd": "/tmp", "startedAt": started * 1000}


def goal_transcript(e, a, cond, met=False):
    """Транскрипт сессии a с целью /goal: запись goal_status, как её пишет Claude Code (attachment, met, condition)."""
    d = os.path.join(e.home, ".claude", "projects", "".join(ch if ch.isalnum() else "-" for ch in a["cwd"]))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, a["sessionId"] + ".jsonl")
    with open(p, "a") as fh:
        fh.write(json.dumps({"type": "attachment", "attachment": {"type": "goal_status", "met": met, "sentinel": True,
                                                                  "condition": cond}}, ensure_ascii=False) + "\n")
    return p


def _bg_text(e):
    starts = [c for c in e.calls() if c[:1] == ["--bg"]]
    return starts, " ".join(starts[0]) if starts else ""


def _give_up(e):
    """Три сбоя самозапуска hermes-x подряд — самозапуск встаёт. → время последнего прохода."""
    e.direction("hermes-x")
    e.task("hermes-0001", "hermes-x")
    e.run("watch", t=T0)
    e.board("hermes-0001", T0 + 10)
    t = T0 + 60
    for _ in range(3):
        e.run("watch", t=t)
        e.run("watch", t=t + 400)
        t = json.load(open(e.st("autostart.json")))["hermes-x"]["next"] + 10
    check(json.load(open(e.st("autostart.json")))["hermes-x"].get("gave_up"), "самозапуск не встал")
    return t


def transcript(e, a, tokens, mtime):
    """Транскрипт сессии a там, где его пишет Claude Code: ~/.claude/projects/<cwd с «-»>/<sessionId>.jsonl."""
    d = os.path.join(e.home, ".claude", "projects", "".join(ch if ch.isalnum() else "-" for ch in a["cwd"]))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, a["sessionId"] + ".jsonl")
    with open(p, "w") as fh:
        fh.write(json.dumps({"type": "user", "timestamp": "2026-10-16T10:00:00.000Z",
                             "message": {"role": "user", "content": "шаг"}}) + "\n")
        fh.write(json.dumps({"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "usage": {
            "input_tokens": 10, "cache_read_input_tokens": tokens - 10, "cache_creation_input_tokens": 0}}}) + "\n")
    os.utime(p, (mtime, mtime))
    return p


QUICK = {"PANTHEON_STOP_WAIT": "1", "PANTHEON_STOP_POLL": "0.02", "PANTHEON_STOP_SETTLE": "0.05",
         "PANTHEON_NAME_WAIT": "0.1"}


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


ZEUS_SID = "2e057e05-0001"


def zeus_env(tokens=160_000, state="blocked", extra_entries=(), saved=True):
    """Зевс в claude agents и его транскрипт: ход начался T0-3000, ответ T0-2990 (почти 50 мин назад); доска и handoff
    записаны T0-2900 (saved), T0-4000 (saved=False, до хода) или в момент saved (число)."""
    e = Env()
    json.dump({"env": {}}, open(e.st("settings", "hq.json"), "w"))
    z = {"id": "2e057e05", "sessionId": ZEUS_SID, "name": "zeus", "state": state, "status": "waiting",
         "waitingFor": "input needed", "pid": None, "kind": "background", "cwd": e.pantheon,
         "startedAt": (T0 - 9000) * 1000}
    e.agents([z])
    d = os.path.join(e.home, ".claude", "projects", "".join(ch if ch.isalnum() else "-" for ch in e.pantheon))
    os.makedirs(d, exist_ok=True)
    rows = [{"type": "user", "timestamp": _iso(T0 - 3000), "message": {"role": "user", "content": "что на доске?"}},
            _answer(T0 - 2990, tokens)]
    rows += list(extra_entries)
    e.zeus_transcript = os.path.join(d, ZEUS_SID + ".jsonl")
    with open(e.zeus_transcript, "w") as fh:
        fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    hand = os.path.join(e.pantheon, "handoff", "zeus-2026-10-16")
    os.makedirs(hand, exist_ok=True)
    for f in (os.path.join(e.pantheon, "board.md"), os.path.join(hand, "HANDOFF.md")):
        open(f, "w").write("состояние\n")
        m = saved if not isinstance(saved, bool) else T0 - 2900 if saved else T0 - 4000
        os.utime(f, (m, m))
    return e


def zeus_actions(e):
    return [c for c in e.calls() if c[:1] in (["stop"], ["--bg"], ["respawn"]) or "--resume" in c]


ZEUS_RUN = {**QUICK, "FAKE_STOP_MARK": "1"}


def _tool(name, tid, inp, t):
    return {"type": "assistant", "timestamp": _iso(t), "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tid, "name": name, "input": inp}], "usage": {
        "input_tokens": 10, "cache_read_input_tokens": 159_990, "cache_creation_input_tokens": 0}}}


def _result(tid, t, text="ok", tur=None):
    r = {"type": "user", "timestamp": _iso(t), "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tid, "content": text}]}}
    if tur is not None:
        r["toolUseResult"] = tur
    return r


def _answer(t, tokens=160_000):
    return {"type": "assistant", "timestamp": _iso(t), "message": {
        "role": "assistant", "stop_reason": "end_turn", "content": [{"type": "text", "text": "жду"}],
        "usage": {"input_tokens": 10, "cache_read_input_tokens": tokens - 10, "cache_creation_input_tokens": 0}}}


def _start_log(e):
    p = e.st("logs", "start.log")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def _zeus_last(e):
    p = e.st("zeus-clean.json")
    return (json.load(open(p)) if os.path.exists(p) else {}).get("last") or {}


_DIRECT_RESUME = r"""
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("pantheon_lib", sys.argv[1])
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
a = json.loads(sys.argv[2])
def recheck():
    os.makedirs(P.path("stopped"), exist_ok=True)       # метка stopped появилась, пока ждали блокировку
    open(P.path("stopped", a["name"]), "w").write("вы\n")
    return "остановлено вами"
print(P.resume_session(a["name"], a, "продолжай", "wake-waiting", recheck=recheck))
"""


def _zeus_answer(e, t, question, answer, mark="· окно вопросов", note=None):
    """Запись хука answer в owner-log/zeus.md: заголовок со временем t и пометкой, тело «вопрос: … / ответ: …»."""
    with open(e.st("owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
        fh.write(f"## {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))} {mark}\nвопрос: {question}\n"
                 f"ответ: {answer}\n" + (f"заметка: {note}\n" if note else "") + "\n")


def _start_rows(e):
    p = e.st("logs", "start.log")
    return [ln.split("\t") for ln in open(p, encoding="utf-8").read().splitlines()] if os.path.exists(p) else []


_HQ_RW_PROBE = r"""
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("pantheon_lib", sys.argv[1])
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
P.hq_mark("autostart-reset", "ln-dir", "метка\n")
P.HQ_LOCK_WAIT = 0.5
t0 = time.monotonic()
with P.lock("start-ln-dir") as got:
    print(got, round(time.monotonic() - t0, 2))
"""


def _night_now(e):
    """Ночь идёт в T0: вечер (ask_at) за 2 ч, ночь с T0 − 1 ч до T0 + 3 ч (по местному времени машины, на которой идут
    тесты); вопроса на ночь нет ([sb-simplify] п. 10), repeat и deadline не действуют."""
    f = lambda s: time.strftime("%H:%M", time.localtime(T0 + s))  # noqa: E731
    open(os.path.join(e.pantheon, "schedule.toml"), "w").write(
        f'primary_host = "mac-a"\n[defaults]\nlimit_max_pct = 70\n[night]\nask_at = "{f(-7200)}"\nrepeat = []\n'
        f'deadline = "{f(-1800)}"\n[limits.night]\nstart = "{f(-3600)}"\nend = "{f(3 * 3600)}"\n')


def _bgs(e, who=None):
    return [c for c in e.calls() if c[:1] == ["--bg"] and (who is None or any(who in x for x in c))]


def _pack_night(e, name="athena-p"):
    """Ночь как в _night_now (вечер с T0 − 2 ч, ночь с T0 − 1 ч) и ночная пачка направления name на утро после вечера."""
    _night_now(e)
    e.direction(name)
    evening = time.strftime("%Y-%m-%d", time.localtime(T0 - 7200))
    morning = time.strftime("%Y-%m-%d", time.localtime(T0 - 7200 + 86400))
    e.pack_rel = f"directions/{name}/night-{morning}-pack.md"
    e.pack = os.path.join(e.pantheon, e.pack_rel)
    open(e.pack, "w", encoding="utf-8").write(f"# Ночная пачка {name}\n\n| # | Задача |\n|---|---|\n| 1 | athena-0300 |\n")
    e.night_file = e.st("night", evening + ".json")
    e.evening = evening


def _night_yes(e, t, qid="metis-0700"):
    """Ваш выбор «Да — ночь <дата>» на вопрос pantheon night ask о пачке e.pack (её sha256 сейчас)."""
    sha = hashlib.sha256(open(e.pack, "rb").read()).hexdigest()
    _zeus_answer(e, t, f"[{qid}] Ночь {e.evening}: пачка {e.pack_rel} sha256 {sha}?", f"Да — ночь {e.evening}")


def _oneshot_env():
    """Env с направлением athena-a и разовой записью на T0 + 10 мин; → (e, id)."""
    e = Env()
    e.direction("athena-a")
    hhmm = time.strftime("%H:%M", time.localtime(T0 + 600))
    r = e.run("start", "athena-a", "--at", hhmm, "задание", t=T0)
    return e, r.stdout.split("разовый запуск ")[1].split(":")[0]


def _oneshot_rec(e, oid):
    return next(x for x in json.load(open(e.st("oneshot.json")))["items"] if x["id"] == oid)


_NIGHT_PROBE = r"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("pantheon_lib", sys.argv[1])
P = importlib.util.module_from_spec(spec)
sys.modules["pantheon_lib"] = P
spec.loader.exec_module(P)
N = P.night_mod()
cfg = N.config()
t = float(sys.argv[2])
print(N.night_of(t, cfg), N.evening(t, cfg), N.evening(t + 7 * 3600, cfg))
"""


def _now_env(name, head, turn_ago=600, mtime_ago=0, state="working", pid=None, e=None):
    """metis-0707: STATUS.md с разделом «Сейчас» (head — заголовок целиком, None — раздела нет); окно name с транскриптом,
    записанным turn_ago секунд назад (None — транскрипта нет), mtime файла — mtime_ago секунд назад."""
    e = e or Env()
    e.direction(name)
    p = os.path.join(e.pantheon, "directions", name, "STATUS.md")
    open(p, "w").write("# STATUS\n\n" + (head + "\n\n- шаг\n" if head else "- шаг\n"))
    os.utime(p, (T0 - mtime_ago, T0 - mtime_ago))
    a = bg(name, state, "%08x-1111" % (abs(hash(name)) % 16**8), pid=pid)
    e.now_agents = getattr(e, "now_agents", []) + [a]
    e.agents(e.now_agents)
    if turn_ago is not None:
        transcript(e, a, 20_000, T0 - turn_ago)
    return e


def _stamp(ago, minutes=None):
    s = time.strftime("%d.%m %H:%M", time.localtime(T0 - ago))
    return s[:-1] + minutes if minutes else s


def _fact_env(name, body, mtime_ago=7200):
    """metis-1005: окно name со STATUS.md, текст которого задаёт тест (body целиком), mtime — mtime_ago секунд назад."""
    e = _now_env(name, "## Сейчас", mtime_ago=mtime_ago, state="done", pid=4300 + len(name))
    p = os.path.join(e.pantheon, "directions", name, "STATUS.md")
    open(p, "w", encoding="utf-8").write(body)
    os.utime(p, (T0 - mtime_ago, T0 - mtime_ago))
    return e, p


def _age_tree(w, when):
    """Состарить копию целиком (файлы и папки без перехода по ссылкам, затем её саму): уборка копий смотрит не только
    mtime папки, но и свежие правки внутри (metis-0835, D1), а файлы теста созданы позже T0."""
    for d, dirs, files in os.walk(w, topdown=False):
        for n in files + dirs:
            os.utime(os.path.join(d, n), (when, when), follow_symlinks=False)
    os.utime(w, (when, when))


def _mk_wt_files(d, n):
    os.makedirs(d, exist_ok=True)
    for i in range(n):
        open(os.path.join(d, f"f{i}"), "w").close()


def _wt_repo(name):
    e = Env()
    folder = e.direction(name)
    shutil.rmtree(os.path.join(folder, ".git"))
    g = lambda *a, cwd=folder: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                              capture_output=True, text=True, env=dict(os.environ, HOME=e.home))
    g("init", "-q", "-b", "main")
    g("commit", "-q", "--allow-empty", "-m", "x")
    return e, folder, g


RESTARTED = "Claude Code сам перезапустил фоновую сессию, задания у неё нет"


def idle_env(name, sid):
    """Направление с задачей под вашей отметкой и простаивающей фоновой сессией (`state` working, `status` idle)."""
    e = Env()
    e.direction(name)
    e.task(name[:2] + "-0001", name)
    e.run("watch", t=T0)
    e.board(name[:2] + "-0001", T0 + 10)
    a = bg(name, "working", sid, pid=44)
    a["status"] = "idle"
    e.agents([a])
    return e, a


def job_state(e, sid, data):
    """state.json фоновой сессии, как его пишет Claude Code: ~/.claude/jobs/<короткий id>/state.json."""
    d = os.path.join(e.home, ".claude", "jobs", sid[:8])
    os.makedirs(d, exist_ok=True)
    json.dump(data, open(os.path.join(d, "state.json"), "w"))


def respawns(e):
    return [c for c in e.calls() if c[:1] == ["respawn"]]


_DIRECT_LOCK_STALE = r"""
import fcntl, importlib.util, os, sys
spec = importlib.util.spec_from_file_location("pantheon_lib", sys.argv[1])
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
lp = P.path(P.HQ_RW, "locks", "start-rf-dir.lock")
os.makedirs(os.path.dirname(lp), exist_ok=True)
fd = os.open(lp, os.O_WRONLY | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
with P.lock("start-rf-dir", block=False) as got:       # чужой владелец: метка выставлена
    assert not got and P.LOCK_CONTENDED == "start-rf-dir", (got, P.LOCK_CONTENDED)
os.close(fd)
os.unlink(lp)
os.mkfifo(lp)                                           # подложенная запись на месте замка
with P.lock("start-rf-dir", block=False) as got:
    assert not got
print(P.LOCK_CONTENDED)
"""


def _next_agents(e, lst):
    """FAKE_AGENTS_NEXT: свежий claude agents под блокировкой имени (повторная проверка) видит lst."""
    p = os.path.join(e.tmp, "agents-next.json")
    json.dump(lst, open(p, "w"))
    if os.path.exists(p + ".seen"):
        os.remove(p + ".seen")
    return {"FAKE_AGENTS_NEXT": p}


def _resumed(e, sid):
    """Сессию sid продолжили: claude respawn или --resume."""
    return any(c[:2] == ["respawn", sid[:8]] or ("--resume" in c and sid in c) for c in e.calls())


def respawn_env(name, sid, since=T0 - 50, state="done", status=None):
    """metis-0181: окно направления поднято до установки плагинов (startedAt T0-100 < since), отметка respawn.json стоит,
    транскрипт старый (час назад) и маленький — свежего старта нет, только respawn."""
    e = Env()
    e.direction(name)
    a = bg(name, state, sid, pid=51)
    if status:
        a["status"] = status
    e.agents([a])
    tp = transcript(e, a, 20_000, T0 - 3600)
    os.makedirs(e.st("plugins"), exist_ok=True)
    json.dump({"since": since, "plugins": ["pantheon"], "done": []}, open(e.st("plugins", "respawn.json"), "w"))
    return e, a, tp


def subagent(tp, mtime, n="a1"):
    """Журнал субагента там, где его пишет Claude Code: <папка транскрипта>/<sessionId>/subagents/agent-*.jsonl."""
    d = os.path.join(tp[:-len(".jsonl")], "subagents")
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, f"agent-{n}.jsonl")
    open(f, "w").write("{}\n")
    os.utime(f, (mtime, mtime))
    return f


def worktree(e, name, mtime):
    """Копия лида под .claude/worktrees/ в папке направления: всё в ней (и сами папки) — со временем mtime."""
    wt = os.path.join(e.doms[name][0], ".claude", "worktrees", "lead-a")
    os.makedirs(os.path.join(wt, "src"), exist_ok=True)
    open(os.path.join(wt, "src", "f.py"), "w").write("x = 1\n")
    for p in (os.path.join(wt, "src", "f.py"), os.path.join(wt, "src"), wt):
        os.utime(p, (mtime, mtime))
    return wt


def respawned(e, short):
    return ["respawn", short] in e.calls()


def sub_meta(tp, n, mtime, finished=False):
    """meta.json субагента рядом с его журналом (Claude Code ставит "finished": true по его концу)."""
    d = os.path.join(tp[:-len(".jsonl")], "subagents")
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, f"agent-{n}.meta.json")
    json.dump({"agentType": "dev-opus", "name": f"dev-{n}", **({"finished": True} if finished else {})}, open(f, "w"))
    os.utime(f, (mtime, mtime))
    return f


def sub_journal(tp, n, mtime, records):
    """Журнал субагента своими записями (dict) с временем mtime."""
    d = os.path.join(tp[:-len(".jsonl")], "subagents")
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, f"agent-{n}.jsonl")
    with open(f, "w") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.utime(f, (mtime, mtime))
    return f


# --- metis-0250: честные состояния сессий и уборка -------------------------------------------------------------

def _job(e, short, **st):
    """state.json задания Claude Code в подменённом HOME."""
    d = os.path.join(e.home, ".claude", "jobs", short)
    os.makedirs(d, exist_ok=True)
    json.dump(st, open(os.path.join(d, "state.json"), "w"))


def _roster(e, workers):
    """Реестр демона Claude Code: короткий id → pid процесса."""
    d = os.path.join(e.home, ".claude", "daemon")
    os.makedirs(d, exist_ok=True)
    json.dump({"proto": 1, "workers": {k: {"pid": v, "rvAuth": "секрет"} for k, v in workers.items()}},
              open(os.path.join(d, "roster.json"), "w"))


def _dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def _hestia_env(task_status, extra=""):
    """Гестия с задачей: run-файл окна (куда его пишет wake hestia) держит PANTHEON_TASK, реестр демона есть."""
    e = Env()
    e.direction("athena-x")
    e.task("athena-0071", "athena-x", status=task_status, extra=extra)
    os.makedirs(e.st("settings", "run"), exist_ok=True)
    json.dump({"env": {"PANTHEON_TASK": "athena-0071"}}, open(e.st("settings", "run", "hestia.json"), "w"))
    _roster(e, {"other": {"pid": 999999}})
    return e


def _hestia_calls(e):
    return [c for c in e.calls() if c[:1] in (["stop"], ["rm"]) and len(c) > 1 and c[1].startswith("h")]


def P_task_valid(e, status):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
    import tasks
    return (tasks.load_tasks(e.pantheon).get("athena-0071") or (0, {}, 0))[1].get("status") == status


BLK_SID = "b10c0001-aaaa"


def _blocked_env(tool=None, waiting="permission prompt"):
    """Фоновая сессия coord-x стоит на запросе разрешения; живой Зевс закончил ход (state done, процесс есть)."""
    e = Env()
    e.direction("coord-x")
    b = bg("coord-x", "blocked", BLK_SID, pid=31)
    if waiting:
        b["waitingFor"] = waiting
    z = bg("zeus", "done", "2e057e05-1", pid=32)
    e.agents([b, z])
    if tool:
        d = os.path.join(e.home, ".claude", "projects", "-tmp")
        os.makedirs(d, exist_ok=True)
        rows = [_tool(tool[0], "tu1", tool[1], T0 - 30)]
        with open(os.path.join(d, BLK_SID + ".jsonl"), "w") as fh:
            fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return e


def _relayed(e):
    return [c for c in e.calls() if c[:1] == ["respawn"] and c[1] == "2e057e05"]


def _pushed(e):
    p = e.st("push", "2e057e05-1.txt")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def _two_blocked_env():
    e = Env()
    e.direction("coord-x")
    e.direction("coord-y")
    a = bg("coord-x", "blocked", BLK_SID, pid=31)
    a["waitingFor"] = "Bash: one"
    b = bg("coord-y", "blocked", "b10c0002-bbbb", pid=33)
    b["waitingFor"] = "Bash: two"
    e.agents([a, b, bg("zeus", "done", "2e057e05-1", pid=32)])
    return e


def _relay_stops(setup, what, extra=None):
    e = _two_blocked_env()
    setup(e)
    e.run("watch", t=T0, extra=extra)
    check(not [c for c in e.calls() if c[:1] == ["respawn"]], f"0277: {what} — передача была: {e.calls()}")
    check("ждёт вас" in e.alerts(), f"0277: {what} — пропала тревога: {e.alerts()}")
    check(not os.path.exists(e.st("relay.json")), f"0277: {what} — запись в relay.json")



def _cap_rows(e):
    p = e.st("capacity.jsonl")
    return [json.loads(x) for x in open(p)] if os.path.exists(p) else []



def _ghost_env(name, updated=None):
    """Окружение для призраков: реестр демона с чужим живым воркером (непустой, нашей сессии нет), правлен updated."""
    e = Env()
    e.direction(name)
    daemon = os.path.join(e.home, ".claude", "daemon")
    os.makedirs(daemon, exist_ok=True)
    e.roster = os.path.join(daemon, "roster.json")
    e.set_roster = lambda upd: json.dump({"updatedAt": None if upd is None else upd * 1000,
                                          "workers": {"other": {"pid": 999999}}}, open(e.roster, "w"))
    e.set_roster(updated)
    return e


def _reg(e, rec):
    d = os.path.join(e.home, ".claude", "sessions")
    os.makedirs(d, exist_ok=True)
    json.dump({"pid": os.getpid(), "cwd": "/tmp", **rec}, open(os.path.join(d, f"{os.getpid()}.json"), "w"))


def _job(e, sid, **st):
    st.setdefault("detail", "Session ended")  # detail в state.json задания есть всегда (ревью argus-249a Б1)
    d = os.path.join(e.home, ".claude", "jobs", sid)
    os.makedirs(d, exist_ok=True)
    json.dump(st, open(os.path.join(d, "state.json"), "w"))


def _woke(e, sid="cccccccc"):
    return [c for c in e.calls() if c[:2] == ["respawn", sid] or ("--resume" in c and any(sid in x for x in c))]


def _maint(e, sessions, t=T0, reason="обновление"):
    json.dump({"id": P_STAMP(t), "since": t, "expires": t + 7200, "reason": reason, "by": "test", "sessions": sessions},
              open(e.st("maintenance.json"), "w"))


def P_STAMP(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


__all__ = [k for k in list(globals()) if not k.startswith("__")]   # всё, включая _помощники: части берут их через import *
