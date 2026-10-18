#!/usr/bin/env python3
"""Синтетические тесты дежурного и управления сессиями (lib/watch.py, шаг 1.4).

Запуск: python3 -I plugins/pantheon/tests/test_watch.py  (код выхода 0 — все прошли)
Проверяет строки карты решений SCHED-09, SCHED-10, SCHED-12, SCHED-15, COMM-04, COMM-10, COMM-14, STATE-14, QA-05,
COST-04, TOOL-04 на временных папках. Claude Code подменён скриптом `claude` в PATH: `agents --json --all` отдаёт
список из файла, остальные вызовы пишутся в журнал (запуски не настоящие).
"""
import json
import shutil
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
if sys.version_info < (3, 11):  # часть проверок импортирует pantheon.py в этом же процессе — ему нужен tomllib
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)])
import tempfile
# Все временные папки файла — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение);
# TMPDIR — для подпроцессов, которые тоже создают временные папки. Общий TMPDIR остаётся чистым.
import atexit as _atexit
import os as _os
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="watch-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "pantheon.py")
T0 = 1_792_000_000
FAILS = []

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
log = os.environ["FAKE_CLAUDE_LOG"]
open(log, "a").write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
a = sys.argv[1:]
if a[:1] == ["agents"]:
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
        open(os.path.join(self.pantheon, "schedule.toml"), "w").write(
            'primary_host = "mac-a"\n[defaults]\nlimit_max_pct = 70\n[night]\nask_at = "00:00"\n'
            '[limits.night]\nstart = "00:00"\nend = "00:00"\n')
        self.doms = {}
        self.week_pct, self.snap_age = 10.0, 0  # снимок недельного лимита в run(): зелёная зона, свежий
        # уведомления идут через политику (metis-0023): простой — явно, по умолчанию «вы у Mac»
        self.extra = {"PANTHEON_FAKE_IDLE": "0"}

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

    def task(self, tid, direction, status="todo"):
        p = os.path.join(self.pantheon, "directions", direction, "tasks", tid + ".md")
        open(p, "w").write(f"---\ntype: task\nid: {tid}\ntitle: проба\nstatus: {status}\nproject: {direction}\n"
                           f"direction: {direction}\ncreated: 2026-10-15\nupdated: 2026-10-15T07:00:00\n"
                           "schema_version: 1\npriority: 2\n---\n\nтекст\n")

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
               "PANTHEON_FAKE_SWAP": "1.0", "PANTHEON_FAKE_PS": "", "PANTHEON_FAKE_CC": "2.1.292",
               "PANTHEON_FAKE_LIMIT": "10", "PANTHEON_CAFFEINATE": os.path.join(self.bin, "caffeinate")}
        env.update(self.extra)
        env.update(extra or {})
        return subprocess.run([*(argv or [PY311, "-I", LIB]), *args], env=env, capture_output=True, text=True, timeout=60)

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


def test_autostart_only_new_sanctions():
    """Старые решения владельца (до включения дежурного) никого не будят; новое — будит, одна сессия, без доверия —
    тревога вместо запуска."""
    e = Env()
    e.direction("athena-x")
    e.task("athena-0001", "athena-x")
    e.board("athena-0001", T0 - 7 * 86400)                     # неделю назад, до включения
    e.run("watch", t=T0)
    check(not any(c[:1] == ["--bg"] or "start" in c for c in e.calls() if c[:1] != ["agents"] and c[:1] != ["--version"]),
          "самозапуск по старой карточке")
    check(os.path.exists(e.st("autostart-since")), "autostart-since записан")
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check("задачи с ними: нет" in out, f"dry-run видит старую карточку: {out}")
    e.board("athena-0001", T0 + 120)                            # новый ход владельца
    out = e.run("watch", "--dry-run", t=T0 + 180).stdout
    check("athena-x: поднял бы сейчас" in out, f"dry-run не видит новую карточку: {out}")
    check("athena-x" not in json.load(open(e.st("autostart.json"))), "dry-run ничего не пишет")
    r = e.run("watch", t=T0 + 240)
    starts = [c for c in e.calls() if c[:1] == ["--bg"]]
    check(len(starts) == 1 and "athena-x" in starts[0], f"самозапуск не пошёл: {e.calls()} {r.stderr}")
    check("самозапуск: athena-x" in e.alerts(), "строка самозапуска в тревогах")
    aw = json.load(open(e.st("awake.json")))
    check(aw.get("reason") == "поднята athena-x" and aw.get("pid"),
          f"после самозапуска сон Mac не запрещён в том же проходе: {aw}")
    # без доверия — тревога и уведомление, запуска нет
    e2 = Env()
    e2.direction("athena-y", trusted=False)
    e2.task("athena-0002", "athena-y")
    e2.run("watch", t=T0)
    e2.board("athena-0002", T0 + 60)
    e2.run("watch", t=T0 + 120)
    check(not [c for c in e2.calls() if c[:1] == ["--bg"]], "запуск без доверия")
    check("нет доверия" in e2.alerts(), "тревога о доверии")


def test_autostart_batch_in_owner_order_0242():
    """Пачка из 7 отметок владельца уходит в задание целиком и в порядке отметок, а не по алфавиту и не первыми пятью."""
    e = Env()
    e.direction("athena-x")
    order = [7, 3, 5, 1, 6, 2, 4]
    for n in range(1, 8):
        e.task(f"athena-000{n}", "athena-x")
    e.run("watch", t=T0)
    for i, n in enumerate(order):
        e.board(f"athena-000{n}", T0 + 100 + i * 10)
    e.board("athena-0003", T0 + 400)  # повторная отметка порядок не меняет
    e.run("watch", t=T0 + 500)
    starts = [c for c in e.calls() if c[:1] == ["--bg"]]
    check(len(starts) == 1, f"самозапуск не пошёл: {e.calls()}")
    text = " ".join(starts[0])
    want = ", ".join(f"athena-000{n}" for n in order)
    check(want in text, f"в задании нет всей пачки в порядке отметок ({want}): {text[-500:]}")


def test_autostart_order_board_vs_zeus_0242():
    """Отметки из board.jsonl и ответ окном вопросов (zeus.md) идут одним списком по времени, а не «сначала board»."""
    e = Env()
    e.direction("athena-x")
    for n in (1, 2, 3):
        e.task(f"athena-000{n}", "athena-x")
    e.run("watch", t=T0)
    e.board("athena-0002", T0 + 100)
    with open(e.st("owner-log", "zeus.md"), "w") as fh:
        fh.write(f"## {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(T0 + 50))} · окно вопросов\n"
                 "вопрос: [athena-0001] что-то\n\n")
    e.board("athena-0003", T0 + 150)
    e.run("watch", t=T0 + 500)
    starts = [c for c in e.calls() if c[:1] == ["--bg"]]
    check(len(starts) == 1, f"самозапуск не пошёл: {e.calls()}")
    want = "athena-0001, athena-0002, athena-0003"
    check(want in " ".join(starts[0]), f"порядок board/zeus.md нарушен ({want}): {' '.join(starts[0])[-400:]}")


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


def test_session_waits_reaches_you():
    """Ревью argus: сессия «ждёт вас», пока вы у Mac, — в очередь; ушли, а она всё ждёт — одна macOS и больше
    ни одной, пока ждёт; «упала» той же сессии — своё событие (свой ключ), а не «уже сообщали»."""
    e = Env()
    e.direction("coord-x")
    e.notify_mode(0)
    e.agents([bg("coord-x", "blocked", "sess0001-aaaa", pid=31)])
    e.run("watch", t=T0)                                         # «здесь»
    a = e.sent()
    e.notify_mode(1200)                                          # ушли
    e.run("watch", t=T0 + 300)
    b = e.sent()
    e.run("watch", t=T0 + 1800)
    c = e.sent()
    e.run("watch", t=T0 + 4200)
    d = e.sent()
    check("ждёт вас" not in a and "watch-blocked-sess0001" in e.queued(), f"«здесь»: без macOS и в очереди: {a!r}")
    check(b.count("coord-x ждёт вас") == 1, f"ушли — одна macOS: {b!r}")
    check(c.count("coord-x ждёт вас") == 1, f"через 25 мин — второй нет: {c!r}")
    check(d.count("coord-x ждёт вас") == 1 and "|session-coord-x" in d, f"через 65 мин — повтора нет: {d!r}")
    check(e.alerts().count("coord-x (sess0001) ждёт вас") == 1, "тревога в alerts.md — не разовая")
    # «готово» (сессия работает), затем снова «ждёт» — ещё одна macOS
    e.agents([bg("coord-x", "working", "sess0001-aaaa", pid=31)])
    e.run("watch", t=T0 + 4500)
    e.agents([bg("coord-x", "blocked", "sess0001-aaaa", pid=31)])
    e.run("watch", t=T0 + 4800)
    check(e.sent().count("coord-x ждёт вас") == 2, f"снова «ждёт» после снятия — без второй macOS: {e.sent()!r}")
    # весь день ждут две сессии, вас нет: по одной macOS на сессию, бюджет не съеден — решение «Нужен ответ» дойдёт
    e = Env()
    e.extra["TZ"] = "Europe/Moscow"
    e.direction("coord-x")
    e.direction("coord-y")
    e.notify_mode(1200)
    e.agents([bg("coord-x", "blocked", "sess0004-dddd", pid=34), bg("coord-y", "blocked", "sess0005-eeee", pid=35)])
    day = T0 - 8 * 3600 - 46 * 60                                  # 2026-10-14 12:00 по Москве
    for k in range(34):                                          # 12:00 … 23:00, каждые 20 мин
        e.run("watch", t=day + k * 1200)
    s = e.sent()
    used = json.load(open(e.st("notify.json"))).get("used")
    check(s.count("coord-x ждёт вас") == 1 and s.count("coord-y ждёт вас") == 1 and used == 2,
          f"день ожидания двух сессий — по одной macOS, бюджет 2: {s!r} used={used}")
    r = e.run("task", "new", "--direction", "coord-x", "--title", "Решить вечером", "--status", "waiting",
              "--waiting-on", "human", "--next", "ответ", "--question", "Что выбрать?", "--project", "coord-x",
              t=day + 11 * 3600 - 120)
    e.run("board", t=day + 11 * 3600 - 60)                       # 22:59 — ещё не тихие часы
    check(r.returncode == 0 and "Вопрос к вам: Решить вечером" in e.sent(),
          f"после дня ожидания решение «Нужен ответ» без macOS: {r.stderr} {e.sent()!r}")
    # «ждёт», через 10 мин «упала» той же сессии — при «нет» отдельная macOS
    e = Env()
    e.direction("coord-x")
    e.notify_mode(1200)
    e.agents([bg("coord-x", "blocked", "sess0002-bbbb", pid=32)])
    e.run("watch", t=T0)
    e.agents([bg("coord-x", "failed", "sess0002-bbbb", pid=32)])
    e.run("watch", t=T0 + 600)
    s = e.sent()
    check("coord-x ждёт вас" in s and "coord-x упала" in s, f"«упала» после «ждёт» при «нет» — своя macOS: {s!r}")
    # то же при «здесь» — обе строки в очереди сводки
    e = Env()
    e.direction("coord-x")
    e.notify_mode(0)
    e.agents([bg("coord-x", "blocked", "sess0003-cccc", pid=33)])
    e.run("watch", t=T0)
    e.agents([bg("coord-x", "failed", "sess0003-cccc", pid=33)])
    e.run("watch", t=T0 + 600)
    q = e.queued()
    check(not e.sent() and "watch-blocked-sess0003" in q and "watch-failed-sess0003" in q,
          f"«упала» после «ждёт» при «здесь» — строка в очереди: {q}")


def test_watch_notify_through_policy():
    """Уведомления дежурного — через политику (metis-0023): сбой «скоро» — macOS только при «нет» и не ночью,
    иначе в очередь сводки; подделка журнала ваших слов — критичное: сразу, и ночью, и когда вы у Mac."""
    e = Env()
    e.notify_mode(0)                                           # вы у Mac, день
    t = _give_up(e)
    check("Самозапуск" not in e.sent() and "autostart-gaveup-hermes-x" in e.queued(),
          f"самозапуск встал при «здесь»: уведомление или нет в очереди: {e.sent()!r} {e.queued()}")
    e.notify_mode(1200)                                        # ушли, а самозапуск так и стоит — macOS дойдёт
    e.run("watch", t=t + 60)
    check(e.sent().count("Самозапуск hermes-x встал") == 1, f"самозапуск стоит, вы ушли — без macOS: {e.sent()!r}")
    e = Env()
    e.notify_mode(1200, ("12:00", "11:59"))                    # нет у Mac, ночь (тихие часы весь день)
    _give_up(e)
    check("Самозапуск" not in e.sent() and "autostart-gaveup-hermes-x" in e.queued(),
          f"самозапуск встал ночью: уведомление или нет в очереди: {e.sent()!r}")
    e = Env()
    e.notify_mode(1200)                                        # нет у Mac, день
    _give_up(e)
    check("Самозапуск hermes-x встал" in e.sent(), "самозапуск встал при «нет» днём — без уведомления")
    # проверка опор после обновления Claude Code не прошла — сбой «скоро»: при «здесь» без уведомления
    e = Env()
    e.notify_mode(0)
    e.run("watch", t=T0)
    e.run("watch", t=T0 + 60, extra={"PANTHEON_FAKE_CC": "2.1.300"})
    check("НЕ в порядке" in e.alerts() and "проверка опор" not in e.sent() and "infra" in e.queued(),
          f"infra при «здесь»: {e.sent()!r} {e.queued()}")
    # техперезапуск истёк — сбой «скоро»: при «здесь» без уведомления
    e = Env()
    e.notify_mode(0)
    e.direction("mm-dir")
    e.run("restart", "--prepare", "обновление", t=T0)
    e.run("watch", t=T0 + 7300)
    check("истекла" in e.alerts() and "Техперезапуск" not in e.sent() and "restart" in e.queued(),
          f"restart при «здесь»: {e.sent()!r} {e.queued()}")
    # журнал ваших слов изменён задним числом — критичное: и при «здесь», и ночью
    for idle, quiet in ((0, None), (1200, ("12:00", "11:59"))):
        e = Env()
        e.notify_mode(idle, quiet)
        p = os.path.join(e.st("owner-log"), "athena.md")
        new = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 - 86400))
        open(p, "w").write(f"## {new}\nсвежее\n\n")
        e.run("watch", t=T0)
        open(p, "w").write(f"## {new}\nподменённое\n\n")
        e.run("watch", t=T0 + 86400)
        check("изменена уже записанная часть" in e.alerts() and "Журнал ваших слов изменён задним числом" in e.sent()
              and "критично" in e.sent(), f"подделка журнала (простой {idle}, тихие {quiet}): {e.sent()!r}")
        os.remove(p)
        e.run("watch", t=T0 + 2 * 86400)
        check("Журнал ваших слов удалён" in e.sent(), f"удаление журнала (простой {idle}, тихие {quiet}): {e.sent()!r}")
        nl = os.path.join(e.state, "notify-log.jsonl")
        check(os.path.exists(nl) and '"critical"' in open(nl).read(), "критичное дежурного не в журнале уведомлений")


def test_autostart_backoff_and_give_up():
    """Сбой — пауза растёт; три сбоя подряд — самозапуск направления встаёт, уведомление; resume сбрасывает."""
    e = Env()
    e.notify_mode(1200)  # «нет у Mac» и без тихих часов: сбой «скоро» уходит уведомлением (metis-0023)
    e.direction("hermes-x")
    e.task("hermes-0001", "hermes-x")
    e.run("watch", t=T0)
    e.board("hermes-0001", T0 + 10)
    t = T0 + 60
    for i in range(3):
        e.run("watch", t=t)                                    # запуск (сессии в claude agents так и нет)
        e.run("watch", t=t + 400)                              # итог: не появилась — сбой
        st = json.load(open(e.st("autostart.json")))["hermes-x"]
        check(st.get("fails") == i + 1, f"сбой {i + 1} не засчитан: {st}")
        if i < 2:
            gap = st["next"] - (t + 400)
            check(3600 * 2 ** i * 0.85 < gap < 3600 * 2 ** i * 1.15, f"пауза после сбоя {i + 1}: {gap}")
            t = st["next"] + 10
    check(st.get("gave_up"), "после трёх сбоев самозапуск не встал")
    check("остановлен после 3 сбоев" in e.alerts(), "тревога о трёх сбоях")
    check("Самозапуск hermes-x встал" in open(e.notify).read(), "уведомление о трёх сбоях")
    n = len([c for c in e.calls() if c[:1] == ["--bg"]])
    e.run("watch", t=t + 99999)
    check(len([c for c in e.calls() if c[:1] == ["--bg"]]) == n, "после отказа самозапуск продолжает")
    e.run("resume", "hermes-x", t=t + 99999)
    e.run("watch", t=t + 99999)
    check(not json.load(open(e.st("autostart.json")))["hermes-x"].get("gave_up"), "resume не сбросил счётчик сбоев")
    # снова встал (ревью argus): отметка once прежнего эпизода не снята (после resume живая сессия — сброса нет);
    # новый эпизод «встал» всё равно даёт macOS
    np = e.st("notify.json")

    def stale(at):  # отметка прежнего эпизода, которую autostart() не снял
        nst = json.load(open(np, encoding="utf-8"))
        nst.setdefault("faults", {})["autostart-gaveup-hermes-x"] = {"t": at, "text": "старое", "once": True}
        data = json.dumps(nst, ensure_ascii=False)
        with open(np, "w", encoding="utf-8") as fh:
            fh.write(data)
    before = open(e.notify).read().count("Самозапуск hermes-x встал")
    t = t + 99999 + 3 * 86400
    for i in range(3):
        e.run("watch", t=t)
        if i == 2:
            stale(t - 3 * 86400)  # прямо перед третьим сбоем: дальше — только fail()
        e.run("watch", t=t + 400)
        st = json.load(open(e.st("autostart.json")))["hermes-x"]
        if i < 2:
            t = st["next"] + 10
    check(st.get("gave_up") and open(e.notify).read().count("Самозапуск hermes-x встал") == before + 1,
          f"снова встал через 3 дня при неснятой отметке — нет второй macOS: {st}")


def test_autostart_start_timeout_0141():
    """metis-0141 п. 1: pantheon start из самозапуска не уложился в срок — строка в тревогах и код 124, без трассировки;
    срок по умолчанию покрывает шаги запуска (около 410 с) и меньше срока прохода дежурного (600 с)."""
    if sys.version_info < (3, 11):  # pantheon.py сам требует 3.11 (tomllib): на 3.9 он отвечал бы отказом на всё
        print("ok   пропуск: срок pantheon start требует Python 3.11+ (здесь %d.%d)" % sys.version_info[:2])
        return
    e = Env()
    e.direction("pluto-x")
    e.task("pluto-0001", "pluto-x")
    e.run("watch", t=T0)
    e.board("pluto-0001", T0 + 10)
    r = e.run("watch", t=T0 + 60, extra={"PANTHEON_START_TIMEOUT": "2", "FAKE_BG_SLEEP": "20"})
    check(r.returncode == 0 and "Traceback" not in r.stderr, f"проход упал на сроке запуска: {r.returncode} {r.stderr[-800:]}")
    check("pantheon start не уложился в 2 с" in e.alerts() and "не вышло, код 124" in e.alerts(),
          f"нет строки о сроке запуска: {e.alerts()[-600:]}")
    st = json.load(open(e.st("autostart.json")))["pluto-x"]
    check(st.get("fails") == 1, f"срок запуска не засчитан сбоем: {st}")
    src = open(os.path.join(ROOT, "lib", "watch.py"), encoding="utf-8").read()
    check("START_TIMEOUT = 420.0" in src and "timeout=300" not in src.split("def resume_or_start")[1].split("\ndef ")[0],
          "срок pantheon start в resume_or_start не 420 с")


def test_autostart_healthy_resets_and_limits():
    """Сессия проработала ≥ 30 мин — сбои забыты; два направления уже работают — третье ждёт места."""
    e = Env()
    for d in ("a-one", "b-two", "c-three"):
        e.direction(d)
    for d, tid in (("a-one", "aa-0001"), ("b-two", "bb-0001"), ("c-three", "cc-0001")):
        e.task(tid, d)
    e.run("watch", t=T0)
    for tid in ("aa-0001", "bb-0001", "cc-0001"):
        e.board(tid, T0 + 10)
    e.agents([bg("a-one", "working", "aaaaaaaa-1", pid=11), bg("b-two", "working", "bbbbbbbb-1", pid=12)])
    e.run("watch", t=T0 + 60)
    check(not [c for c in e.calls() if c[:1] == ["--bg"]], "третье направление запущено сверх двух")
    check("нет места" in e.alerts(), "тревога «нет места»")
    # здоровая сессия сбрасывает сбои
    json.dump({"a-one": {"last": T0, "pending": True, "fails": 2}}, open(e.st("autostart.json"), "w"))
    e.run("watch", t=T0 + 1900)
    check(json.load(open(e.st("autostart.json")))["a-one"].get("fails") == 0, "сбои не сброшены здоровой сессией")


def test_holders_registry_and_live_copies():
    """Имя держит и вкладка из ~/.claude/sessions (её нет в claude agents); stopped имени не держит."""
    e = Env()
    e.direction("zz-dir")
    e.task("zz-0001", "zz-dir")
    e.run("watch", t=T0)
    e.board("zz-0001", T0 + 10)
    os.makedirs(os.path.join(e.home, ".claude", "sessions"), exist_ok=True)
    json.dump({"pid": os.getpid(), "sessionId": "tab-1", "name": "zz-dir", "kind": "interactive", "cwd": "/tmp"},
              open(os.path.join(e.home, ".claude", "sessions", f"{os.getpid()}.json"), "w"))
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check("zz-dir: уже работает" in out, f"вкладка из реестра не держит имя: {out}")
    out = e.run("wake", "zz-dir", t=T0 + 60).stdout
    check("не спит" in out, f"wake будит при открытой вкладке: {out}")
    os.remove(os.path.join(e.home, ".claude", "sessions", f"{os.getpid()}.json"))
    e.agents([bg("zz-dir", "stopped", "dddddddd-1")])
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check("zz-dir: поднял бы сейчас" in out, f"stopped держит имя: {out}")
    # самозапуск продолжает остановленную той же сессией: claude respawn (id, имя, окно сохраняются), текст — push
    e.run("watch", t=T0 + 120)
    check(["respawn", "dddddddd"] in e.calls(), f"самозапуск не через respawn: {e.calls()}")
    pushed = e.st("push", "dddddddd-1.txt")
    check(os.path.exists(pushed) and open(pushed).read().startswith("[Пантеон:"), "текст для хука push")
    check(oct(os.stat(pushed).st_mode & 0o777) == "0o600", "права push-файла")
    # respawn не вышел (сессию удалили из списка) — --resume с именем и окном
    e.agents([bg("zz-dir", "stopped", "dddddddd-2", started=T0 + 1)])
    json.dump({}, open(e.st("autostart.json"), "w"))
    e.run("watch", t=T0 + 99999, extra={"FAKE_RESPAWN_RC": "1"})
    res = [c for c in e.calls() if "--resume" in c]
    check(res and res[-1][res[-1].index("--name") + 1] == "zz-dir" and "--settings" in res[-1],
          f"resume без --name/--settings: {res}")
    check(not os.path.exists(e.st("push", "dddddddd-2.txt")), "push-файл остался после неудачного respawn")


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


def test_resume_or_start_fresh():
    """metis-0147 п. 2 в дежурном (resume_or_start: pantheon wake <имя>, самозапуск, снятие паузы): контекст > 100 тыс.
    и простой > 60 мин — свежая сессия с файла состояния; иначе — respawn, как раньше."""
    e = Env()
    e.direction("fr-dir")
    a = bg("fr-dir", "stopped", "ffffffff-1")
    e.agents([a])
    transcript(e, a, 130_000, T0 - 7200)
    r = e.run("wake", "fr-dir", t=T0, extra=QUICK)
    c = e.calls()
    new = [x for x in c if "--bg" in x]
    check(not [x for x in c if x[:1] == ["respawn"] or "--resume" in x] and len(new) == 1
          and new[0][:5] == ["--bg", "--agent", "domain-coordinator", "--name", "fr-dir"]
          and os.path.realpath(new[0][6]) == os.path.realpath(e.st("settings", "run", "fr-dir.json"))
          and "[Пантеон: свежий старт]" in new[0][-1] and "~/ai/pantheon/directions/fr-dir/STATUS.md" in new[0][-1]
          and "Посмотри входящие" in new[0][-1], f"свежий старт в pantheon wake <имя>: {c} {r.stdout} {r.stderr}")
    open(e.log, "w").close()
    transcript(e, a, 130_000, T0 - 600)
    e.run("wake", "fr-dir", t=T0, extra=QUICK)
    check(["respawn", "ffffffff"] in e.calls() and not [x for x in e.calls() if "--bg" in x],
          f"простой 10 мин — не respawn: {e.calls()}")


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


def test_zeus_clean_0136():
    """metis-0136: дежурный очищает Зевса только при всех шести условиях — свежий старт (claude stop + claude --bg
    --agent hq --name zeus с окном штаба), одна строка «Зевс очищен в HH:MM, контекст N тыс.»; повторный проход —
    ничего. Любое условие не выполнено — очистки нет; не выполнено только (5) — напоминание не чаще раза в час;
    (6) — с конца хода меньше 20 мин: ни очистки, ни напоминания."""
    # все условия выполнены — ровно одно действие и одна строка
    e = zeus_env()
    r = e.run("watch", t=T0, extra=ZEUS_RUN)
    acts = zeus_actions(e)
    starts = [c for c in acts if c[:1] == ["--bg"]]
    check(acts[:1] == [["stop", "2e057e05"]] and len(starts) == 1 and len(acts) == 2,
          f"очистка Зевса — не stop + один --bg: {acts} {r.stderr[-600:]}")
    if starts:
        s = starts[0]
        check(s[s.index("--agent") + 1] == "hq" and s[s.index("--name") + 1] == "zeus"
              and os.path.realpath(s[s.index("--settings") + 1]) == os.path.realpath(e.st("settings", "hq.json")),
              f"свежий Зевс не с ролью, именем и окном штаба: {s}")
        check(s[-1].startswith("[Пантеон: очистка]") and "~/ai/pantheon/board.md" in s[-1]
              and "~/ai/pantheon/handoff/zeus-2026-10-16/HANDOFF.md" in s[-1] and "продолжай" in s[-1],
              f"текст свежего Зевса: {s[-1]}")
    hhmm = time.strftime("%H:%M", time.localtime(T0))
    check(e.alerts().count("Зевс очищен") == 1 and f"Зевс очищен в {hhmm}, контекст 160 тыс." in e.alerts(),
          f"нет одной строки об очистке: {e.alerts()[-500:]}")
    check(os.path.exists(e.zeus_transcript), "транскрипт прошлого Зевса пропал")
    n = len(e.calls())
    e.run("watch", t=T0 + 300, extra=ZEUS_RUN)                     # Зевс уже остановлен — ничего
    z = json.load(open(e.agents_file))
    z[0].update(state="blocked")                                     # старый список: та же сессия снова «ждёт»
    e.agents(z)
    e.run("watch", t=T0 + 600, extra=ZEUS_RUN)
    check(len(zeus_actions(e)) == 2 and e.alerts().count("Зевс очищен") == 1,
          f"повторный проход снова чистит: {e.calls()[n:]}")

    # каждое условие по отдельности не выполнено — очистки нет
    ask = [_tool("AskUserQuestion", "toolu_ask1", {"questions": []}, T0 - 2980)]
    bash_bg = [_tool("Bash", "toolu_bg1", {"command": "sleep 999", "run_in_background": True}, T0 - 2985),
               _result("toolu_bg1", T0 - 2984, "Command running in background with ID: b1", {"backgroundTaskId": "b1"}),
               _answer(T0 - 2983)]
    agent_bg = [_tool("Agent", "toolu_ag1", {"prompt": "x"}, T0 - 2985),
                _result("toolu_ag1", T0 - 2984, "Async agent launched successfully. agentId: a1",
                        {"isAsync": True, "status": "async_launched", "agentId": "a1"}), _answer(T0 - 2983)]
    cases = [("(1) контекст 140 тыс.", dict(tokens=140_000)),
             ("(2) Зевс работает", dict(state="working")),
             ("(2) ход идёт: ответа на ввод нет", dict(extra_entries=[
                 {"type": "user", "timestamp": _iso(T0 - 2950), "message": {"role": "user", "content": "ещё"}}])),
             ("(3) фоновая команда", dict(extra_entries=bash_bg)),
             ("(3) фоновый субагент", dict(extra_entries=agent_bg)),
             ("(4) открыт AskUserQuestion", dict(extra_entries=ask)),
             ("(5) доска и handoff старше хода", dict(saved=False))]
    for what, kw in cases:
        e = zeus_env(**kw)
        e.run("watch", t=T0, extra=ZEUS_RUN)
        check(not zeus_actions(e) and "Зевс очищен" not in e.alerts(), f"{what}: очистка всё равно была: {e.calls()}")
    # (6) только что ответил — владелец, скорее всего, читает: ни очистки, ни напоминания; через 20 мин — очистка
    fresh_turn = [{"type": "user", "timestamp": _iso(T0 - 700), "message": {"role": "user", "content": "и что?"}},
                  _answer(T0 - 600)]
    e = zeus_env(extra_entries=fresh_turn, saved=T0 - 500)
    e.run("watch", t=T0, extra=ZEUS_RUN)
    check(not zeus_actions(e) and "Зевс очищен" not in e.alerts() and "сверь доску" not in e.alerts(),
          f"(6) ответ 10 мин назад: Зевса тронули: {e.calls()} {e.alerts()[-300:]}")
    e.run("watch", t=T0 + 700, extra=ZEUS_RUN)
    check(e.alerts().count("Зевс очищен") == 1, f"(6) через 21 мин после ответа очистки нет: {e.alerts()[-300:]}")
    # (3) снят: уведомление о конце фоновой задачи пришло — очистка идёт
    done = {"type": "user", "timestamp": _iso(T0 - 2970), "origin": {"kind": "task-notification"}, "message": {
        "role": "user", "content": "<task-notification>\n<task-id>a1</task-id>\n<tool-use-id>toolu_ag1</tool-use-id>"
        "\n<status>completed</status>\n</task-notification>"}}
    e = zeus_env(extra_entries=agent_bg + [done, _answer(T0 - 2960)])
    e.run("watch", t=T0, extra=ZEUS_RUN)
    check(len([c for c in zeus_actions(e) if c[:1] == ["--bg"]]) == 1, f"субагент закончил — а очистки нет: {e.calls()}")

    # защиты дежурного держат: остановлен вами, технический перезапуск, карантин ~/.claude
    def stopped(e):
        os.makedirs(e.st("stopped"), exist_ok=True)
        open(e.st("stopped", "zeus"), "w").write("вы\n")

    def maint(e):
        json.dump({"reason": "обновление", "expires": T0 + 3600, "sessions": ["zeus"]}, open(e.st("maintenance.json"), "w"))

    def held(e):
        os.makedirs(os.path.join(e.home, ".claude"), exist_ok=True)
        open(os.path.join(e.home, ".claude", ".sync-held"), "w").write("task=x\n")
    for what, setup in [("остановлен вами", stopped), ("техперезапуск", maint), ("карантин", held)]:
        e = zeus_env()
        setup(e)
        e.run("watch", t=T0, extra=ZEUS_RUN)
        check(not zeus_actions(e), f"{what}: Зевса всё равно очистили: {e.calls()}")

    # только (5): напоминание — строка в тревогах и сброс метки Stop-хука; не чаще раза в час и только после нового хода
    e = zeus_env(saved=False)
    mark = e.st("ctx", "marks", ZEUS_SID)
    os.makedirs(os.path.dirname(mark), exist_ok=True)
    open(mark, "w").write("160000")
    e.run("watch", t=T0, extra=ZEUS_RUN)
    check(e.alerts().count("сверь доску и handoff") == 1 and not os.path.exists(mark) and not zeus_actions(e),
          f"нет напоминания при несохранённом: {e.alerts()[-400:]}")
    e.run("watch", t=T0 + 600, extra=ZEUS_RUN)
    e.run("watch", t=T0 + 3700, extra=ZEUS_RUN)                     # час прошёл, а нового хода не было
    check(e.alerts().count("сверь доску и handoff") == 1, "напоминание повторилось без нового хода")
    with open(e.zeus_transcript, "a") as fh:
        fh.write(json.dumps({"type": "user", "timestamp": _iso(T0 + 3800), "message": {"role": "user", "content": "?"}})
                 + "\n" + json.dumps(_answer(T0 + 3810)) + "\n")
    e.run("watch", t=T0 + 3900, extra=ZEUS_RUN)                     # ответ 90 с назад — (6): напоминания нет
    check(e.alerts().count("сверь доску и handoff") == 1, "напоминание, пока владелец читает ответ")
    e.run("watch", t=T0 + 5100, extra=ZEUS_RUN)
    check(e.alerts().count("сверь доску и handoff") == 2, "после нового хода и часа напоминания нет")
    with open(e.zeus_transcript, "a") as fh:                        # новый ход, но час с напоминания не прошёл
        fh.write(json.dumps({"type": "user", "timestamp": _iso(T0 + 5200), "message": {"role": "user", "content": "!"}})
                 + "\n" + json.dumps(_answer(T0 + 5210)) + "\n")
    e.run("watch", t=T0 + 6500, extra=ZEUS_RUN)
    check(e.alerts().count("сверь доску и handoff") == 2, "напоминание чаще раза в час")

    # повторная проверка под блокировкой: между проходом и claude stop Зевс взял работу — не трогать
    e = zeus_env()
    z = json.load(open(e.agents_file))
    z[0].update(state="working", status="busy")
    nxt = os.path.join(e.home, "agents-next.json")
    json.dump(z, open(nxt, "w"))
    e.run("watch", t=T0, extra={**ZEUS_RUN, "FAKE_AGENTS_NEXT": nxt})
    check(not zeus_actions(e) and "Зевс очищен" not in e.alerts() and "не вышла" not in e.alerts(),
          f"Зевс взял работу перед остановкой — а его остановили: {e.calls()} {e.alerts()[-300:]}")
    e.run("watch", t=T0 + 60, extra=ZEUS_RUN)                       # снова ждёт — следующий проход чистит
    check(e.alerts().count("Зевс очищен") == 1, f"после отказа проверки следующий проход не очистил: {e.calls()}")

    # свежий старт не вышел: тревога одна, сессия не помечена очищенной, повтор — не раньше чем через час
    e = zeus_env()
    e.run("watch", t=T0, extra={**QUICK, "PANTHEON_STOP_WAIT": "0.1"})  # claude stop не останавливает
    e.run("watch", t=T0 + 600, extra={**QUICK, "PANTHEON_STOP_WAIT": "0.1"})
    check(e.alerts().count("очистка Зевса не вышла") == 1 and "Зевс очищен" not in e.alerts(),
          f"неудачная очистка: нет одной тревоги или повтор раньше часа: {e.alerts()[-500:]}")
    e.run("watch", t=T0 + 3700, extra=ZEUS_RUN)
    check(e.alerts().count("Зевс очищен") == 1, f"через час после неудачи очистки нет: {e.alerts()[-400:]}")


def _start_log(e):
    p = e.st("logs", "start.log")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def _zeus_last(e):
    p = e.st("zeus-clean.json")
    return (json.load(open(p)) if os.path.exists(p) else {}).get("last") or {}


def test_zeus_clean_trace_0207():
    """metis-0207: каждый исход очистки Зевса виден. Все шесть условий — zeus-clean.json (cleared, last) и строка
    fresh-start в start.log; не выполнено (1), (3), (4), (5) или держит защита — fresh-skip с причиной, один раз, пока
    причина не сменилась; (2) и (6) — только в zeus-clean.json. Держание ~/.claude без вопроса (solo) очистку не держит."""
    e = zeus_env()
    e.run("watch", t=T0, extra=ZEUS_RUN)
    st = json.load(open(e.st("zeus-clean.json"))) if os.path.exists(e.st("zeus-clean.json")) else {}
    check(ZEUS_SID in (st.get("cleared") or []) and (st.get("last") or {}).get("result") == "очищен",
          f"очистка без следа в zeus-clean.json: {st}")
    check("fresh-start\tzeus\t2e057e05\ttick\t0\tочистка Зевса, контекст 160 тыс." in _start_log(e),
          f"нет строки fresh-start в start.log: {_start_log(e)!r}")

    ask = [_tool("AskUserQuestion", "toolu_ask1", {"questions": []}, T0 - 2980)]
    bash_bg = [_tool("Bash", "toolu_bg1", {"command": "sleep 999", "run_in_background": True}, T0 - 2985),
               _result("toolu_bg1", T0 - 2984, "Command running in background with ID: b1", {"backgroundTaskId": "b1"}),
               _answer(T0 - 2983)]

    def held(text):
        def setup(e):
            os.makedirs(os.path.join(e.home, ".claude"), exist_ok=True)
            open(os.path.join(e.home, ".claude", ".sync-held"), "w").write(text)
        return setup

    def stopped(e):
        os.makedirs(e.st("stopped"), exist_ok=True)
        open(e.st("stopped", "zeus"), "w").write("вы\n")
    cases = [("(1) контекст 140 тыс. < 150 тыс.", dict(tokens=140_000), None),
             ("(3) фоновые задачи: toolu_bg1", dict(extra_entries=bash_bg), None),
             ("(4) открыт вопрос AskUserQuestion", dict(extra_entries=ask), None),
             ("(5) не сохранено после последнего хода", dict(saved=False), None),
             ("(0) карантин правок ~/.claude ждёт ответа на metis-0187", {}, held("hash=a\ntask=metis-0187\nfiles=1\n")),
             ("(0) остановлен вами", {}, stopped)]
    for why, kw, setup in cases:
        e = zeus_env(**kw)
        if setup:
            setup(e)
        e.run("watch", t=T0, extra=ZEUS_RUN)
        e.run("watch", t=T0 + 300, extra=ZEUS_RUN)                   # причина та же — строка не повторяется
        log = _start_log(e)
        skips = [ln for ln in log.splitlines() if "\tfresh-skip\tzeus\t2e057e05\ttick\t" in ln]
        check(not zeus_actions(e) and len(skips) == 1 and why in skips[0] and why in " ".join(_zeus_last(e).get("miss") or []),
              f"{why}: нет одной строки fresh-skip с причиной или следа в zeus-clean.json: {log!r} {_zeus_last(e)}")
    # (2) и (6) — обычное дело: причина в zeus-clean.json, журнал не засоряется
    fresh_turn = [{"type": "user", "timestamp": _iso(T0 - 700), "message": {"role": "user", "content": "и что?"}},
                  _answer(T0 - 600)]
    for why, kw in [("(2) идёт ход", dict(state="working")), ("(6) с конца хода меньше 20 мин",
                                                              dict(extra_entries=fresh_turn, saved=T0 - 500))]:
        e = zeus_env(**kw)
        e.run("watch", t=T0, extra=ZEUS_RUN)
        last = _zeus_last(e)
        check(not zeus_actions(e) and "fresh-skip" not in _start_log(e) and last.get("result") == "пропуск"
              and any(m.startswith(why) for m in last.get("miss") or []), f"{why}: след не тот: {last} {_start_log(e)!r}")
    # sync.sh держит правку без вопроса (solo=1, task пустой) — ответа не будет, очистка идёт
    e = zeus_env()
    held("hash=a6202ffbaa71\ntask=\nfiles=4\nsolo=1\n")(e)
    e.run("watch", t=T0, extra=ZEUS_RUN)
    check(len([c for c in zeus_actions(e) if c[:1] == ["--bg"]]) == 1 and "\tfresh-start\tzeus\t" in _start_log(e),
          f"держание без вопроса блокирует очистку: {e.calls()} {_start_log(e)!r}")


def test_fresh_on_all_resume_paths_0207():
    """metis-0207: правило свежего старта (контекст > 100 тыс., простой > 60 мин) — на любом пути возобновления, а не
    только в resume_or_start и pantheon wake: ждущая сессия с задачей (wake-waiting) и техперезапуск (restart --go)."""
    e = Env()
    e.direction("fw-dir")
    e.task("fw-0001", "fw-dir")
    a = bg("fw-dir", "blocked", "fafafafa-1")
    e.agents([a])
    transcript(e, a, 130_000, T0 - 7200)
    r = e.run("watch", t=T0, extra=ZEUS_RUN)                      # claude stop в самом деле останавливает
    c = e.calls()
    new = [x for x in c if "--bg" in x]
    check(not [x for x in c if x[:1] == ["respawn"] or "--resume" in x] and len(new) == 1
          and new[0][:5] == ["--bg", "--agent", "domain-coordinator", "--name", "fw-dir"]
          and "[Пантеон: свежий старт]" in new[0][-1] and "fw-0001" in new[0][-1]
          and "\tfresh-start\tfw-dir\tfafafafa\twake-waiting\t0\t" in _start_log(e),
          f"ждущая сессия после долгого простоя — не свежий старт: {c} {_start_log(e)!r} {r.stderr[-400:]}")

    e = Env()
    e.direction("rg-dir")
    a = bg("rg-dir", "working", "dededede-1", pid=21)
    e.agents([a])
    transcript(e, a, 130_000, T0 - 7200)
    e.run("restart", "--prepare", "обновление", t=T0)
    e.run("saved", "--by", "rg-dir", "--state", "STATUS.md", t=T0 + 20)
    r = e.run("restart", "--go", t=T0 + 40, extra={"PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1"})
    check("[fresh] rg-dir" in r.stdout and "[resume] rg-dir" not in r.stdout,
          f"restart --go после долгого простоя — не свежий старт: {r.stdout[-500:]} {r.stderr[-300:]}")


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


def test_fresh_path_recheck_0207():
    """metis-0207 (argus PR #44): на пути свежего старта в resume_session recheck под блокировкой имени действует так
    же, как на обычном пути: сессия с контекстом 130 тыс. и простоем 2 ч не останавливается и не пересоздаётся."""
    # 1) recheck вернул причину (метка stopped появилась) — ни claude stop, ни --bg, строка resume-skip
    e = Env()
    e.direction("fr-dir")
    a = bg("fr-dir", "blocked", "fcfcfcfc-1")
    e.agents([a])
    transcript(e, a, 130_000, T0 - 7200)
    r = e.run(LIB, json.dumps(a), t=T0,
              extra=QUICK, argv=[PY311, "-I", "-c", _DIRECT_RESUME])
    c = e.calls()
    check(r.stdout.strip() == "(1, None)" and not [x for x in c if x[:1] == ["stop"] or "--bg" in x]
          and "\tresume-skip\tfr-dir\tfcfcfcfc\twake-waiting\tостановлено вами" in _start_log(e),
          f"recheck на пути свежего старта не остановил подъём: {r.stdout!r} {c} {_start_log(e)!r} {r.stderr[-400:]}")


def test_fresh_path_busy_0207():
    """metis-0207 (argus PR #44): занятая блокировка имени на пути свежего старта — отказ, а не остановка сессии."""
    import fcntl
    # имя занято (блокировка start-<имя> взята) — ни claude stop, ни --bg, строка resume-busy
    e = Env()
    e.direction("fb-dir")
    e.task("fb-0001", "fb-dir")
    a = bg("fb-dir", "blocked", "fdfdfdfd-1")
    e.agents([a])
    transcript(e, a, 130_000, T0 - 7200)
    os.makedirs(e.st("locks"), exist_ok=True)
    with open(e.st("locks", "start-fb-dir.lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        e.run("watch", t=T0, extra=ZEUS_RUN)
    c = e.calls()
    check(not [x for x in c if x[:1] == ["stop"] or "--bg" in x or x[:1] == ["respawn"]]
          and "\tresume-busy\tfb-dir\tfdfdfdfd\twake-waiting" in _start_log(e),
          f"занятая блокировка имени на пути свежего старта проигнорирована: {c} {_start_log(e)!r}")


def test_resume_copy_note():
    """--resume сделал копию — строка в тревогах."""
    e = Env()
    e.direction("cp-dir")
    e.agents([bg("cp-dir", "failed", "eeeeeeee-1")])
    e.run("wake", "cp-dir", t=T0, extra={"FAKE_RESPAWN_RC": "1", "FAKE_RESUME_OUT": "note: session is running; started a copy as 0123abcd"})
    check("сделал копию 0123abcd" in e.alerts(), "копия после --resume не замечена")


def test_maintenance():
    """Техперезапуск: метка с сроком, самозапуск и wake стоят; --go перезапускает сохранившихся один раз;
    истёкшая метка снимается с тревогой."""
    e = Env()
    e.direction("mm-dir")
    e.direction("nn-dir")
    e.agents([bg("mm-dir", "working", "mmmmmmmm-1", pid=21), bg("nn-dir", "working", "nnnnnnnn-1", pid=22)])
    r = e.run("restart", "--prepare", "обновление", t=T0)
    m = json.load(open(e.st("maintenance.json")))
    check(m["sessions"] == ["mm-dir", "nn-dir"] and m["expires"] == T0 + 7200, f"метка: {m} {r.stderr}")
    out = e.run("wake", "mm-dir", t=T0 + 10)
    check(out.returncode == 1 and "технический перезапуск" in out.stderr, "wake при метке")
    r = e.run("saved", "--by", "mm-dir", "--state", "STATUS.md", t=T0 + 20)
    check(r.returncode == 0 and os.path.exists(e.st("maintenance", "mm-dir.json")), f"saved: {r.stderr}")
    check(e.run("restart", "--status", t=T0 + 30).returncode == 1, "status при несохранившейся")
    r = e.run("restart", "--go", t=T0 + 40, extra={"PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1"})
    check("[resume] mm-dir" in r.stdout and "не тронуты: nn-dir" in r.stdout, f"--go: {r.stdout}")
    check(os.path.exists(e.st("maintenance", "mm-dir.done")) and not os.path.exists(e.st("maintenance", "mm-dir.json")),
          "отметка перезапуска")
    r = e.run("restart", "--go", t=T0 + 50, extra={"PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1"})
    check("[resume] mm-dir" not in r.stdout and "mm-dir (раньше)" in r.stdout, f"повтор --go трогает перезапущенную: {r.stdout}")
    e.run("watch", t=T0 + 7300)
    check(not os.path.exists(e.st("maintenance.json")) and "истекла" in e.alerts(), "истёкшая метка не снята")


def test_stop_resume_all_precise():
    """resume --all снимает только метки, поставленные stop --all."""
    e = Env()
    e.direction("s1-dir")
    e.direction("s2-dir")
    e.agents([bg("s1-dir", "working", "s1s1s1s1-1", pid=31)])
    e.run("stop", "s2-dir", t=T0)
    e.run("stop", "--all", t=T0 + 10)
    check(os.path.exists(e.st("paused")) and os.path.exists(e.st("stopped", "s1-dir")), "stop --all")
    check(["stop", "s1s1s1s1"] in e.calls(), "stop --all не остановил сессию")
    out = e.run("resume", "--all", t=T0 + 20).stdout
    check(not os.path.exists(e.st("stopped", "s1-dir")) and os.path.exists(e.st("stopped", "s2-dir")),
          f"resume --all снял чужую метку: {out}")
    check(not os.path.exists(e.st("paused")), "пауза планировщика осталась")


def test_stop_removes_from_fleet():
    """metis-0239: после claude stop идёт claude rm <id>, иначе флот Claude Code поднимает сессию снова;
    отказ rm (worktree с неотправленным) виден в выводе и в start.log, насильно не удаляем."""
    e = Env()
    e.direction("rm-dir")
    e.direction("rk-dir")
    e.agents([bg("rm-dir", "working", "r1r1r1r1-1", pid=61), bg("rk-dir", "working", "r2r2r2r2-1", pid=62)])
    r = e.run("stop", "rm-dir", t=T0)
    c = e.calls()
    check(["stop", "r1r1r1r1"] in c and ["rm", "r1r1r1r1"] in c and c.index(["stop", "r1r1r1r1"]) < c.index(["rm", "r1r1r1r1"]),
          f"stop не вызвал rm после stop: {c}")
    check("осталась во флоте" not in r.stdout, f"ложная «осталась во флоте»: {r.stdout}")
    r = e.run("stop", "rk-dir", t=T0 + 5, extra={"FAKE_RM_REFUSE": "r2r2r2r2"})
    check(["rm", "r2r2r2r2"] in e.calls() and not [x for x in e.calls() if "--discard-unpushed" in x or "--force-remove-worktree" in x],
          "rm вызван неверно или насильно")
    check("rk-dir: осталась во флоте: r2r2r2r2, причина:" in r.stdout and "unpushed" in r.stdout and r.returncode == 0,
          f"отказ rm не виден в выводе: {r.stdout!r}")
    log = open(e.st("logs", "start.log")).read()
    check("rm-refused\trk-dir\tr2r2r2r2" in log, f"отказ rm не в start.log: {log}")
    check("rk-dir: осталась во флоте Claude Code (rm отказал)" in e.alerts() and "r2r2r2r2" in e.alerts(),
          f"отказ rm без тревоги: {e.alerts()}")
    # stop --all: отказ rm — в выводе, в start.log и в тревоге
    e2 = Env()
    e2.direction("ra-dir")
    e2.agents([bg("ra-dir", "working", "r3r3r3r3-1", pid=63)])
    r = e2.run("stop", "--all", t=T0, extra={"FAKE_RM_REFUSE": "r3r3r3r3"})
    check(["rm", "r3r3r3r3"] in e2.calls() and "ra-dir: осталась во флоте: r3r3r3r3, причина:" in r.stdout,
          f"stop --all: отказ rm не виден в выводе: {r.stdout!r}")
    check("стоп всё: осталась во флоте Claude Code (rm отказал): ra-dir r3r3r3r3" in e2.alerts(),
          f"stop --all: отказ rm без тревоги: {e2.alerts()}")
    check("rm-refused\tra-dir\tr3r3r3r3" in open(e2.st("logs", "start.log")).read(), "stop --all: нет в start.log")
    # stop вернул не 0 — rm не зовём, сессия остаётся во флоте
    e3 = Env()
    e3.direction("rs-dir")
    e3.agents([bg("rs-dir", "working", "r4r4r4r4-1", pid=64)])
    r = e3.run("stop", "rs-dir", t=T0, extra={"FAKE_STOP_FAIL": "r4r4r4r4"})
    check(["stop", "r4r4r4r4"] in e3.calls() and ["rm", "r4r4r4r4"] not in e3.calls()
          and "rs-dir: осталась во флоте: r4r4r4r4" in r.stdout, f"stop с кодом 1: rm не должен вызываться: {e3.calls()} {r.stdout!r}")


def test_stop_without_locks_write():
    """metis-0078: окно Зевса не пишет в locks/ — pantheon stop работает без блокировки имени, с предупреждением."""
    e = Env()
    e.direction("nl-dir")
    e.agents([bg("nl-dir", "working", "nlnlnlnl-1", pid=51)])
    locks = e.st("locks")
    os.makedirs(locks, exist_ok=True)
    os.chmod(locks, 0o500)
    try:
        if os.access(locks, os.W_OK):  # root обходит права — проверять нечем
            return
        r = e.run("stop", "nl-dir", t=T0)
        check(r.returncode == 0 and os.path.exists(e.st("stopped", "nl-dir")),
              f"stop без записи в locks упал: {r.returncode} {r.stderr[-300:]}")
        check(["stop", "nlnlnlnl"] in e.calls(), "stop без записи в locks не остановил сессию")
        check("нет права записи" in r.stderr and "start-nl-dir" in r.stderr and "Traceback" not in r.stderr,
              f"нет понятного предупреждения: {r.stderr[-300:]}")
        # неблокирующий замок без файла по-прежнему отказ, а не молчаливое «взял»
        r2 = e.run("start", "nl-dir", t=T0)
        check("Traceback" in r2.stderr or r2.returncode != 0, f"start без locks прошёл молча: {r2.stdout} {r2.stderr[-200:]}")
    finally:
        os.chmod(locks, 0o700)


def test_pauses():
    """Пауза по направлению: останавливает сессию; дежурный снимает только свою причину и продолжает сессию."""
    e = Env()
    e.direction("p1-dir")
    e.direction("p2-dir")
    e.agents([bg("p1-dir", "working", "p1p1p1p1-1", pid=41)])
    e.run("pause", "p1-dir", "--reason", "limit", "лимит 80", t=T0)
    e.run("pause", "p2-dir", "--reason", "manual", t=T0)
    e.run("pause", "--all", "--reason", "swap", t=T0)
    check(["stop", "p1p1p1p1"] in e.calls(), "пауза не остановила сессию")
    e.agents([bg("p1-dir", "stopped", "p1p1p1p1-1")])
    e.run("watch", t=T0 + 60, extra={"PANTHEON_FAKE_LIMIT": "90", "PANTHEON_FAKE_SWAP": "9"})
    check(len(os.listdir(e.st("pauses"))) == 3, "паузы сняты раньше времени")
    e.run("watch", t=T0 + 120, extra={"PANTHEON_FAKE_LIMIT": "20", "PANTHEON_FAKE_SWAP": "9"})
    left = sorted(os.listdir(e.st("pauses")))
    check(left == ["_all.json", "p1-dir.json", "p2-dir.json"], f"пауза p1 снята при общей swap-паузе: {left}")
    check(["respawn", "p1p1p1p1"] not in e.calls(), "сессия поднята при общей паузе")
    e.run("watch", t=T0 + 180, extra={"PANTHEON_FAKE_LIMIT": "20", "PANTHEON_FAKE_SWAP": "1"})
    check(sorted(os.listdir(e.st("pauses"))) == ["p2-dir.json"], "swap-пауза не снята или снята ручная")
    check(any("p1p1p1p1-1" in c for c in e.calls() if "--resume" in c), "сессия после паузы не продолжена")
    # старая общая метка (до 0.10.0) переводится в паузу по лимиту
    open(e.st("load-pause"), "w").write("2026-10-15 старая")
    e.run("watch", t=T0 + 240, extra={"PANTHEON_FAKE_LIMIT": "90"})
    check(os.path.exists(e.st("pauses", "_all.json")) and not os.path.exists(e.st("load-pause")), "миграция load-pause")


def _night_now(e):
    """Ночь идёт в T0 и без ответа пропущена: вопрос за 2 ч, срок за 30 мин, ночь с T0 − 1 ч до T0 + 3 ч (по местному
    времени машины, на которой идут тесты)."""
    f = lambda s: time.strftime("%H:%M", time.localtime(T0 + s))  # noqa: E731
    open(os.path.join(e.pantheon, "schedule.toml"), "w").write(
        f'primary_host = "mac-a"\n[defaults]\nlimit_max_pct = 70\n[night]\nask_at = "{f(-7200)}"\nrepeat = []\n'
        f'deadline = "{f(-1800)}"\n[limits.night]\nstart = "{f(-3600)}"\nend = "{f(3 * 3600)}"\n')


def test_week_limit_blocks_autostart():
    """Самозапуск по задаче зовёт gate недели (metis-0127): жёлтая днём, красная, снимок старше 30 мин — не поднимает,
    причина «недельный лимит»; зелёная — поднимает."""
    e = Env()
    e.direction("athena-w")
    e.task("athena-0009", "athena-w")
    e.run("watch", t=T0)
    e.board("athena-0009", T0 + 60)
    cases = ((31.6, 0, "жёлтая зона днём"), (90.0, 0, "красная зона"), (10.0, 31 * 60, "лимит неизвестен (31 мин)"))
    for i, (pct, age, why) in enumerate(cases):
        e.week_pct, e.snap_age = pct, age
        out = e.run("watch", "--dry-run", t=T0 + 120 + i).stdout
        check(f"athena-w: ждёт — недельный лимит: {why}" in out, f"неделя {pct} %, снимок {age} с — dry-run: {out[-500:]}")
        r = e.run("watch", t=T0 + 130 + i)
        check(not [c for c in e.calls() if c[:1] == ["--bg"]], f"неделя {pct} %, снимок {age} с — самозапуск: "
              f"{e.calls()} {r.stderr[-300:]}")
    check("самозапуск athena-w ждёт" not in e.alerts(), "тревога autostart-wait по недельному лимиту")
    e.week_pct, e.snap_age = 10.0, 0
    e.run("watch", t=T0 + 200)
    check(len([c for c in e.calls() if c[:1] == ["--bg"]]) == 1, f"зелёная — самозапуск не пошёл: {e.calls()}")


def test_week_limit_blocks_wake_after_pause():
    """Сессия, уснувшая по пятичасовому лимиту: лимит ушёл, но неделя красная или ночь закрыта — не будится, пауза
    остаётся; неделя снова зелёная днём — продолжена."""
    for night in (False, True):
        e = Env()
        if night:
            _night_now(e)
        e.direction("p9-dir")
        e.agents([bg("p9-dir", "working", "p9p9p9p9-1", pid=43)])
        e.run("pause", "p9-dir", "--reason", "limit", "лимит 80", t=T0)
        e.agents([bg("p9-dir", "stopped", "p9p9p9p9-1")])
        if not night:
            e.week_pct = 90.0
        e.run("watch", t=T0 + 60, extra={"PANTHEON_FAKE_LIMIT": "20"})
        what = "ночь закрыта" if night else "неделя красная"
        check(os.path.exists(e.st("pauses", "p9-dir.json")), f"{what} — пауза снята")
        check(not any("p9p9p9p9-1" in c for c in e.calls() if "--resume" in c), f"{what} — сессия продолжена: {e.calls()}")
        if night:
            st = json.load(open(e.st("night", time.strftime("%Y-%m-%d", time.localtime(T0 - 7200)) + ".json")))
            check(st.get("skipped"), f"ночь без ответа не пропущена: {st}")
        else:
            e.week_pct = 10.0
            e.run("watch", t=T0 + 120, extra={"PANTHEON_FAKE_LIMIT": "20"})
            check(not os.path.exists(e.st("pauses", "p9-dir.json")), "зелёная — пауза не снята")
            check(any("p9p9p9p9-1" in c for c in e.calls() if "--resume" in c), "зелёная — сессия не продолжена")


def test_isolation_and_watch_last():
    """Сбой одной проверки — тревога о ней, остальные идут; watch-last пишет время и упавшие."""
    e = Env()
    e.direction("iso-dir")
    open(os.path.join(e.pantheon, "schedule.toml"), "w").write('primary_host = "mac-a"\n[defaults]\nswap_alert_gb = "x"\nlimit_max_pct = 70\n')
    os.makedirs(e.st("swap.jsonl"))                             # запись замеров swap упадёт
    r = e.run("watch", t=T0)
    wl = json.load(open(e.st("watch-last")))
    check(wl["time"] == T0 and wl["failed"] == ["swap"], f"watch-last: {wl} {r.stderr[-300:]}")
    check("проверка «swap» упала" in e.alerts(), "тревога о сбое проверки")
    check(os.path.exists(e.st("agents.json")) and os.path.exists(e.st("cc-version")), "остальные проверки не шли")
    out = e.run("status", t=T0 + 60).stdout
    check("упали проверки: swap" in out, f"status не видит сбой дежурного: {out[:400]}")


def test_status_long_and_swap_keep():
    e = Env()
    e.direction("long-dir")
    open(os.path.join(e.pantheon, "directions", "long-dir", "STATUS.md"), "w").write("x\n" * 201)
    with open(e.st("swap.jsonl"), "w") as fh:
        fh.write(json.dumps({"t": T0 - 14 * 86400, "gb": 1}) + "\n" + json.dumps({"t": T0 - 16 * 86400, "gb": 1}) + "\n")
    e.agents([bg("long-dir", "working", "llllllll-1", pid=51)])
    e.run("watch", t=T0, extra={"PANTHEON_FAKE_SWAP": "6", "PANTHEON_FAKE_PS": "123 claude attach abc"})
    check("STATUS.md long-dir — 201 строк" in e.alerts(), "тревога о длинном STATUS.md")
    rows = [json.loads(ln) for ln in open(e.st("swap.jsonl"))]
    check(len(rows) == 2 and rows[-1].get("working") == 1, f"замеры swap 15 дней: {rows}")
    check("работают сессий: 1" in e.alerts() and "claude attach" in e.alerts(), "тревога swap")


def test_owner_logs_daily():
    """Раз в сутки: записи старше 30 дней уходят, права сужаются, изменение задним числом — тревога."""
    e = Env()
    d = e.st("owner-log")
    old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 - 40 * 86400))
    new = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 - 86400))
    p = os.path.join(d, "athena.md")
    open(p, "w").write(f"## {old}\nстарое\n\n## {new}\nсвежее\n\n")
    os.chmod(p, 0o644)
    open(os.path.join(d, "gone.md"), "w").write(f"## {old}\nтолько старое\n\n")
    e.board("x-0001", T0 - 40 * 86400)
    e.board("x-0002", T0 - 86400)
    os.makedirs(e.st("logs"), exist_ok=True)
    hl = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 - 3600))
    open(e.st("logs", "ctx-hooks.log"), "w").write(f"{hl} owner-log пропуск: agent_type=''\n")
    e.run("watch", t=T0)
    check("хуки контекста" not in e.alerts(), "тревога на пояснения в ctx-hooks.log")
    with open(e.st("logs", "ctx-hooks.log"), "a") as fh:
        fh.write(f"{hl} start KeyError: 'x'\n")
    os.remove(e.st("watch-daily"))
    e.run("watch", t=T0)
    check("хуки контекста: сбоев за сутки 1" in e.alerts(), "сбой хука без тревоги")
    text = open(p).read()
    check("старое" not in text and "свежее" in text, f"уборка журнала: {text}")
    check(not os.path.exists(os.path.join(d, "gone.md")), "пустой журнал не удалён")
    check(oct(os.stat(p).st_mode & 0o777) == "0o600", "права журнала не сужены")
    check(len(open(os.path.join(d, "board.jsonl")).read().splitlines()) == 1, "board.jsonl не убран")
    # подмена уже записанной части — тревога на следующие сутки
    open(p, "w").write(text.replace("свежее", "подменённое"))
    e.run("watch", t=T0 + 86400)
    check("изменена уже записанная часть" in e.alerts(), "подмена журнала не замечена")
    hashes = json.load(open(e.st("owner-log-hashes.json")))
    check("athena.md" in hashes, "отпечатки журналов")


def test_revisits_repeat_and_edge():
    """Пересмотр: напоминание в срок, повтор через 3 дня, новое событие — сразу."""
    e = Env()
    day = time.strftime("%Y-%m-%d", time.localtime(T0 - 86400))
    open(os.path.join(e.pantheon, "revisits.toml"), "w").write(
        f'[[revisit]]\nid = "R-a"\ndue = "{day}"\nwhat = "проба"\n\n'
        '[[revisit]]\nid = "R-b"\nevent = "cc_updated"\nwhat = "версия"\n')
    e.run("revisits", t=T0)
    check(e.alerts().count("пора пересмотреть R-a") == 1, "R-a в срок")
    e.run("revisits", t=T0 + 86400)
    check(e.alerts().count("пора пересмотреть R-a") == 1, "R-a повторилось раньше 3 дней")
    e.run("revisits", t=T0 + 3 * 86400 + 10)
    check("снова: пора пересмотреть R-a" in e.alerts(), "R-a не повторилось через 3 дня")
    with open(e.st("events.jsonl"), "a") as fh:
        fh.write(json.dumps({"t": T0, "event": "cc_updated", "version": "2.1.300"}) + "\n")
    e.run("revisits", t=T0 + 3 * 86400 + 20)
    check(e.alerts().count("пересмотреть R-b") == 1, "R-b по событию")
    with open(e.st("events.jsonl"), "a") as fh:
        fh.write(json.dumps({"t": T0, "event": "cc_updated", "version": "2.1.301"}) + "\n")
    e.run("revisits", t=T0 + 3 * 86400 + 30)
    check(e.alerts().count("пересмотреть R-b") == 2, "новое событие не напомнило сразу")


def test_tool04_limit_after_max_delay():
    """Задача на Claude после max_delay всё равно ждёт лимита; обычная — идёт."""
    e = Env()
    open(os.path.join(e.pantheon, "schedule.toml"), "w").write(
        'primary_host = "mac-a"\n[[job]]\nname = "clio-weekly"\ncommand = "claude -p --agent clio \\"проход\\""\n'
        'every = 10080\nclass = "heavy"\nclaude = true\nmax_delay = 60\n'
        '[[job]]\nname = "heavy-plain"\ncommand = "pantheon view"\nevery = 10080\nclass = "heavy"\nmax_delay = 60\n'
        'priority = -1\n')
    env = {"PANTHEON_DRYRUN": "1", "PANTHEON_FAKE_WAKE": str(T0 - 7200), "PANTHEON_FAKE_AC": "1",
           "PANTHEON_FAKE_IDLE": "1200", "PANTHEON_FAKE_LIMIT": "95"}
    e.run("tick", t=T0, extra=env)
    e.run("tick", t=T0 + 3700, extra=env)
    st = json.load(open(e.st("jobs", "clio-weekly.json")))
    check("лимит" in (st.get("waiting") or "") and not st.get("last_start"), f"TOOL-04: {st}")


def test_argus_wake_rules():
    """Ревью argus 15.10: снятие паузы не будит при техперезапуске и общей паузе; wake не будит под паузой; не на
    главном Mac самозапуска нет; быстрый «закончила ход» без STATUS.md — сбой; Зевс без вашего слова метку не снимает;
    чужой текст задания — под своей пометкой; saved — только себя."""
    e = Env()
    e.direction("q-dir")
    e.agents([bg("q-dir", "working", "abcdef01-1", pid=61)])
    e.run("pause", "q-dir", "--reason", "limit", t=T0)
    e.agents([bg("q-dir", "stopped", "abcdef01-1")])
    e.run("pause", "--all", "--reason", "manual", t=T0)
    n0 = len([c for c in e.calls() if c[:1] == ["respawn"]])
    e.run("watch", t=T0 + 60, extra={"PANTHEON_FAKE_LIMIT": "10"})
    check(len([c for c in e.calls() if c[:1] == ["respawn"]]) == n0, "снятие паузы подняло сессию под общей паузой")
    check(os.path.exists(e.st("pauses", "q-dir.json")), "своя пауза снята, хотя будить нельзя")
    r = e.run("wake", "q-dir", t=T0 + 70)
    check(r.returncode == 1 and "пауза по нагрузке" in r.stderr, f"wake под паузой: {r.stdout} {r.stderr}")
    e.run("pause", "--off", "--all", t=T0 + 80)
    r = e.run("wake", "q-dir", "сделай", "X", t=T0 + 90)
    pushed = open(e.st("push", "abcdef01-1.txt")).read()
    check(pushed.startswith("[Пантеон: задание от владелец] сделай X"), f"текст задания без пометки: {pushed}")
    # не главный Mac
    e2 = Env()
    e2.direction("w-dir")
    e2.task("ww-0001", "w-dir")
    e2.run("watch", t=T0)
    e2.board("ww-0001", T0 + 10)
    out = e2.run("watch", "--dry-run", t=T0 + 60, extra={"PANTHEON_HOST": "mac-b"}).stdout
    check("не главный Mac" in out, f"самозапуск не на главном Mac: {out}")
    # быстрый done без STATUS.md — сбой
    e2.run("watch", t=T0 + 60)
    e2.agents([bg("w-dir", "done", "abcdef02-1", started=T0 + 61)])
    e2.run("watch", t=T0 + 400)
    check(json.load(open(e2.st("autostart.json")))["w-dir"].get("fails") == 1, "быстрый done засчитан успехом")
    # Зевс без вашего слова метку не снимает
    e2.run("stop", "w-dir", t=T0 + 500)
    r = e2.run("resume", "w-dir", t=T0 + 510, extra={"PANTHEON_ROLE": "hq", "PANTHEON_SESSION": "zeus"})
    check(r.returncode == 1 and os.path.exists(e2.st("stopped", "w-dir")), "Зевс снял метку без вашего слова")
    with open(e2.st("owner-log", "zeus.md"), "w") as fh:
        fh.write(f"## {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(T0 + 505))}\nверни w-dir\n\n")
    r = e2.run("resume", "w-dir", t=T0 + 510, extra={"PANTHEON_ROLE": "hq", "PANTHEON_SESSION": "zeus"})
    check(r.returncode == 0 and not os.path.exists(e2.st("stopped", "w-dir")), f"Зевс по вашему слову: {r.stderr}")
    # saved — только себя
    e2.agents([bg("w-dir", "working", "abcdef02-1", pid=62)])
    e2.run("restart", "--prepare", t=T0 + 600)
    r = e2.run("saved", "--by", "w-dir", t=T0 + 610, extra={"PANTHEON_SESSION": "other-dir"})
    check(r.returncode == 2, "сессия отметила чужую")


def test_owner_log_shrink_and_u2028():
    e = Env()
    d = e.st("owner-log")
    new = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 - 86400))
    p = os.path.join(d, "x.md")
    open(p, "w").write(f"## {new}\nне делай X\n\n## {new}\nдругое\n\n")
    rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T0 - 86400)), "kind": "note", "id": "x-0001",
           "text": "раз\u2028два"}
    open(os.path.join(d, "board.jsonl"), "w", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False) + "\n")
    e.board("x-0002", T0 - 40 * 86400)
    e.run("watch", t=T0)
    lines = open(os.path.join(d, "board.jsonl"), encoding="utf-8").read().split("\n")
    check(json.loads(lines[0]).get("text") == "раз\u2028два" and len([x for x in lines if x]) == 1,
          f"U+2028 порвал запись: {lines}")
    open(p, "w").write(f"## {new}\nдругое\n\n")
    os.chmod(p, 0o600)
    e.run("watch", t=T0 + 86400)
    check("укорочен" in e.alerts(), "удаление записи не замечено")
    os.remove(p)
    e.run("watch", t=T0 + 2 * 86400)
    check("x.md пропал" in e.alerts(), "пропажа журнала не замечена")


def test_security_0100():
    """Проверка безопасности 0.10.0: git в копии роли не исполняет конфигурацию; pause --off не выходит из pauses/;
    из сессии Claude метку и ручную паузу без вашей строки не снять; saved — только имя сессии."""
    e = Env()
    folder = e.direction("g-dir")
    shutil.rmtree(os.path.join(folder, ".git"))
    g = lambda *a, cwd=folder: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                              capture_output=True, text=True, env={"PATH": os.environ["PATH"], "HOME": e.home})  # без GIT_*/PANTHEON_* внешней среды
    g("init", "-q", "-b", "main")
    g("commit", "-q", "--allow-empty", "-m", "x")
    for n in ("w-ok", "w-bad"):
        g("worktree", "add", "-q", "-b", n, os.path.join(folder, ".claude", "worktrees", n))
    pwn = os.path.join(e.tmp, "pwned")
    bad = os.path.join(folder, ".claude", "worktrees", "w-bad")
    # роль подменяет указатель .git своей копии на собственный каталог git с исполняемым fsmonitor
    evil = os.path.join(bad, "evil.git")
    subprocess.run(["cp", "-R", os.path.join(folder, ".git", "worktrees", "w-bad"), evil])
    open(os.path.join(evil, "commondir"), "w").write(os.path.join(folder, ".git") + "\n")
    open(os.path.join(evil, "config.worktree"), "w").write(f"[core]\n\tfsmonitor = touch {pwn}\n")
    open(os.path.join(bad, ".git"), "w").write(f"gitdir: {evil}\n")
    g("config", "extensions.worktreeConfig", "true")
    old = T0 - 3 * 86400
    for n in ("w-ok", "w-bad"):
        os.utime(os.path.join(folder, ".claude", "worktrees", n), (old, old))
    e.run("watch", t=T0)
    check(not os.path.exists(pwn), "git исполнил fsmonitor из копии роли")
    check(not os.path.exists(os.path.join(folder, ".claude", "worktrees", "w-ok")), "чистая слитая копия не убрана")
    check(os.path.exists(bad), "копия с исполняемой конфигурацией убрана")
    # подраздел с U+2028 в имени не прячет фильтр от разбора
    w3 = os.path.join(folder, ".claude", "worktrees", "w-ok")
    g("worktree", "add", "-q", "-b", "w3", w3)
    g("config", "filter.x\u2028y.clean", f"touch {pwn}")
    open(os.path.join(w3, ".gitattributes"), "w").write("* filter=x\u2028y\n")
    os.utime(w3, (old, old))
    e.run("watch", t=T0 + 86400)
    check(not os.path.exists(pwn) and os.path.exists(w3), "фильтр с U+2028 в имени исполнился или копия убрана")
    # pause --off не выходит из pauses/
    open(e.st("maintenance.json"), "w").write("{}")
    r = e.run("pause", "--off", "../maintenance", t=T0)
    check(r.returncode == 2 and os.path.exists(e.st("maintenance.json")), "pause --off удалил файл вне pauses/")
    os.remove(e.st("maintenance.json"))
    # из сессии Claude без роли — нужна ваша строка
    e.run("pause", "g-dir", "--reason", "manual", t=T0)
    e.run("stop", "g-dir", t=T0)
    cl = {"CLAUDECODE": "1"}
    r = e.run("resume", "g-dir", t=T0 + 10, extra=cl)
    check(r.returncode == 1 and os.path.exists(e.st("stopped", "g-dir")), "сессия Claude сняла метку без вашего слова")
    r = e.run("pause", "--off", "g-dir", t=T0 + 10, extra=cl)
    check(r.returncode == 1 and os.path.exists(e.st("pauses", "g-dir.json")), "сессия Claude сняла ручную паузу")
    r = e.run("pause", "--off", "g-dir", t=T0 + 10)
    check(r.returncode == 0 and not os.path.exists(e.st("pauses", "g-dir.json")), "терминал не снял паузу")
    r = e.run("saved", "--by", "../x", t=T0 + 10)
    check(r.returncode != 0 and not os.path.exists(e.st("maintenance", "../x.json")), "saved с путём в имени")


def test_worktree_outward_links_0101():
    """Дежурный не удаляет слитую чистую копию со ссылкой наружу (старый Claude Code сносил цель ссылки); ссылка
    внутрь копии удалению не мешает."""
    e = Env()
    folder = e.direction("g-dir")
    shutil.rmtree(os.path.join(folder, ".git"))
    g = lambda *a, cwd=folder: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                              capture_output=True, text=True, env=dict(os.environ, HOME=e.home))
    g("init", "-q", "-b", "main")
    g("commit", "-q", "--allow-empty", "-m", "x")
    out_wt = os.path.join(folder, ".claude", "worktrees", "w-out")
    in_wt = os.path.join(folder, ".claude", "worktrees", "w-in")
    for n, w in (("w-out", out_wt), ("w-in", in_wt)):
        g("worktree", "add", "-q", "-b", n, w)
    target = os.path.join(e.tmp, "outside-data")
    os.makedirs(target)
    open(os.path.join(target, "keep.txt"), "w").write("x")
    os.symlink(target, os.path.join(out_wt, "link-out"))
    os.makedirs(os.path.join(in_wt, "sub"))
    os.symlink(os.path.join(in_wt, "sub"), os.path.join(in_wt, "link-in"))
    os.symlink("nowhere", os.path.join(in_wt, "link-broken"))
    for w in (out_wt, in_wt):  # копия чистая для git status: ссылки и папка игнорируются
        ex = subprocess.run(["git", "-C", w, "rev-parse", "--git-path", "info/exclude"], capture_output=True,
                            text=True).stdout.strip()
        ex = ex if os.path.isabs(ex) else os.path.join(w, ex)
        os.makedirs(os.path.dirname(ex), exist_ok=True)
        open(ex, "a").write("link-*\nsub\n")
        check(g("status", "--porcelain", cwd=w).stdout.strip() == "", "копия не чистая для git")
    old = T0 - 3 * 86400
    for w in (out_wt, in_wt):
        os.utime(w, (old, old))
    e.run("watch", t=T0)
    check(os.path.exists(out_wt) and os.path.exists(os.path.join(target, "keep.txt")),
          "копия со ссылкой наружу убрана или цель тронута")
    check("не убрана" in e.alerts() and "link-out" in e.alerts() and "w-out" in e.alerts(), "нет тревоги о ссылках")
    check(not os.path.exists(in_wt), "копия со ссылкой внутрь не убрана")


def test_outward_links_walk_limit_0101():
    """Обход длиннее WALK_LIMIT — None (копия небезопасна); в пределах лимита — число ссылок наружу."""
    import importlib
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    w = importlib.import_module("watch")
    d = tempfile.mkdtemp(prefix="walk-", dir=os.environ.get("TMPDIR"))
    saved = w.WALK_LIMIT
    try:
        for i in range(10):
            open(os.path.join(d, f"f{i}"), "w").close()
        w.WALK_LIMIT = 5
        check(w.outward_links(d) is None, "обход длиннее лимита не признан небезопасным")
        w.WALK_LIMIT = 50
        check(w.outward_links(d) == (0, None), "обход в пределах лимита без ссылок не (0, None)")
        os.symlink(tempfile.gettempdir(), os.path.join(d, "out"))
        res = w.outward_links(d)
        check(res and res[0] == 1 and res[1][0] == "out", "ссылка наружу не найдена")
    finally:
        w.WALK_LIMIT = saved
        shutil.rmtree(d, ignore_errors=True)


def test_worktree_outside_and_prune_0118():
    """Копии вне .claude/worktrees: тревога после WORKTREE_DAYS, никогда не удаляются; запись без папки чистится."""
    e = Env()
    folder = e.direction("g-dir")
    shutil.rmtree(os.path.join(folder, ".git"))
    g = lambda *a, cwd=folder: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                              capture_output=True, text=True, env=dict(os.environ, HOME=e.home))
    g("init", "-q", "-b", "main")
    g("commit", "-q", "--allow-empty", "-m", "x")
    outside = os.path.join(e.tmp, "ak-outside")
    young = os.path.join(e.tmp, "ak-young")
    gone = os.path.join(e.tmp, "ak-gone")
    for n, w in (("o-old", outside), ("o-young", young), ("o-gone", gone)):
        g("worktree", "add", "-q", "-b", n, w)
    shutil.rmtree(gone)
    old = T0 - 4 * 86400
    os.utime(outside, (old, old))
    os.utime(young, (T0, T0))
    e.run("watch", t=T0)
    check(os.path.isdir(outside), "копия вне штатной папки убрана")
    a = e.alerts()
    check("вне штатной папки" in a and "ak-outside" in a, "нет тревоги о копии вне штатной папки")
    check("ak-young" not in a, "тревога о молодой копии вне папки")
    lst = g("worktree", "list", "--porcelain").stdout
    check("ak-gone" not in lst and "ak-outside" in lst and "ak-young" in lst, "запись без папки не вычищена")
    check(g("rev-parse", "--verify", "-q", "o-old").returncode == 0, "ветка копии вне папки удалена")


def _wt_repo(name):
    e = Env()
    folder = e.direction(name)
    shutil.rmtree(os.path.join(folder, ".git"))
    g = lambda *a, cwd=folder: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,
                                              capture_output=True, text=True, env=dict(os.environ, HOME=e.home))
    g("init", "-q", "-b", "main")
    g("commit", "-q", "--allow-empty", "-m", "x")
    return e, folder, g


def test_worktree_prune_unreadable_0118():
    """Недоступная папка (EACCES) — не пропавшая: живая копия не теряет запись, prune откладывается и при другой
    пропавшей записи; когда доступ вернулся, prune чистит только пропавшую."""
    e, folder, g = _wt_repo("g-dir")
    wts = os.path.join(folder, ".claude", "worktrees")
    live_wt = os.path.join(wts, "w-live")
    g("worktree", "add", "-q", "-b", "w-live", live_wt)
    e.agents([{"id": "live0001", "sessionId": "live0001-x", "name": "w", "state": "working", "pid": os.getpid(),
               "kind": "background", "cwd": live_wt, "startedAt": (T0 - 100) * 1000}])
    ids = lambda: sorted(os.listdir(os.path.join(folder, ".git", "worktrees")))
    os.chmod(wts, 0o000)
    try:
        e.run("watch", t=T0)
        check("w-live" in ids(), "запись живой копии с недоступной папкой снята prune")
        check("недоступна" in e.alerts() and "prune отложен" in e.alerts(), "нет тревоги о недоступной записи")
    finally:
        os.chmod(wts, 0o755)
    check(os.path.exists(os.path.join(live_wt, ".git")), "копия повреждена")
    # недоступная копия без сессии + реально пропавшая запись: prune не делается
    e2, folder2, g2 = _wt_repo("g-dir")
    wts2 = os.path.join(folder2, ".claude", "worktrees")
    g2("worktree", "add", "-q", "-b", "w-noacc", os.path.join(wts2, "w-noacc"))
    gone = os.path.join(e2.tmp, "ak-gone2")
    g2("worktree", "add", "-q", "-b", "o-gone", gone)
    shutil.rmtree(gone)
    ids2 = lambda: sorted(os.listdir(os.path.join(folder2, ".git", "worktrees")))
    os.chmod(wts2, 0o000)
    try:
        e2.run("watch", t=T0)
        check(ids2() == ["ak-gone2", "w-noacc"], f"prune сработал при недоступной записи: {ids2()}")
    finally:
        os.chmod(wts2, 0o755)
    e2.run("watch", t=T0)
    check(ids2() == ["w-noacc"], f"после возврата доступа prune не убрал пропавшую: {ids2()}")
    # chmod 000 на саму копию (родитель читается): git видит <копия>/.git как «нет файла» — prune снёс бы обе записи
    e3, folder3, g3 = _wt_repo("g-dir")
    self_wt = os.path.join(folder3, ".claude", "worktrees", "w-self")
    g3("worktree", "add", "-q", "-b", "w-self", self_wt)
    gone3 = os.path.join(e3.tmp, "ak-gone3")
    g3("worktree", "add", "-q", "-b", "o-gone3", gone3)
    shutil.rmtree(gone3)
    ids3 = lambda: sorted(os.listdir(os.path.join(folder3, ".git", "worktrees")))
    os.chmod(self_wt, 0o000)
    try:
        e3.run("watch", t=T0)
        check(ids3() == ["ak-gone3", "w-self"], f"prune снял запись копии с chmod 000: {ids3()}")
        check("недоступна" in e3.alerts(), "нет тревоги о недоступной копии")
    finally:
        os.chmod(self_wt, 0o755)
    check(g3("status", "--porcelain", cwd=self_wt).returncode == 0, "копия сломана")
    e3.run("watch", t=T0)
    check(ids3() == ["w-self"], f"после возврата доступа prune не убрал пропавшую: {ids3()}")


def test_worktree_prune_alert_key_and_empty_gitdir_0118():
    """Тревога prune — со своим ключом (не склеивается с «забытой копией»); пустой gitdir — препятствие для prune."""
    # chmod 000 на копии старше WORKTREE_DAYS: второй проход не добавляет строк в alerts.md
    e, folder, g = _wt_repo("g-dir")
    wt = os.path.join(folder, ".claude", "worktrees", "w-old")
    g("worktree", "add", "-q", "-b", "w-old", wt)
    old = T0 - 10 * 86400
    os.utime(wt, (old, old))
    os.chmod(wt, 0o000)
    try:
        e.run("watch", t=T0)
        n1 = len(e.alerts().splitlines())
        check("prune отложен" in e.alerts(), "нет тревоги prune")
        e.run("watch", t=T0)
        n2 = len(e.alerts().splitlines())
        check(n2 == n1, f"второй проход добавил строки в alerts.md: {n1} -> {n2}")
    finally:
        os.chmod(wt, 0o755)
    # пустой gitdir + пропавшая запись: обе записи остаются, тревога есть
    e2, folder2, g2 = _wt_repo("g-dir")
    g2("worktree", "add", "-q", "-b", "w-empty", os.path.join(folder2, ".claude", "worktrees", "w-empty"))
    gone = os.path.join(e2.tmp, "ak-gone4")
    g2("worktree", "add", "-q", "-b", "o-gone4", gone)
    shutil.rmtree(gone)
    wd = os.path.join(folder2, ".git", "worktrees")
    open(os.path.join(wd, "w-empty", "gitdir"), "w").close()
    e2.run("watch", t=T0)
    check(sorted(os.listdir(wd)) == ["ak-gone4", "w-empty"], f"prune сработал при пустом gitdir: {sorted(os.listdir(wd))}")
    check("битая" in e2.alerts() and "prune отложен" in e2.alerts(), "нет тревоги о пустом gitdir")


def test_worktree_keeps_unmerged_and_untracked_0184():
    """metis-0184: уборка дежурным не удаляет копию с неслитым коммитом или неотслеживаемым файлом; контроль — слитая
    и чистая копия убирается (тест умеет удалять)."""
    e, folder, g = _wt_repo("g-dir")
    wts = os.path.join(folder, ".claude", "worktrees")
    path = {n: os.path.join(wts, n) for n in ("w-unpushed", "w-untracked", "w-clean")}
    for n, wt in path.items():
        g("worktree", "add", "-q", "-b", n, wt)
    open(os.path.join(path["w-unpushed"], "work.txt"), "w").write("работа\n")
    g("add", "work.txt", cwd=path["w-unpushed"])
    g("commit", "-q", "-m", "неотправленное", cwd=path["w-unpushed"])
    open(os.path.join(path["w-untracked"], "draft.txt"), "w").write("черновик\n")
    old = T0 - 3 * 86400
    for wt in path.values():
        os.utime(wt, (old, old))
    r = e.run("watch", t=T0)
    check(r.returncode == 0, f"watch упал: {r.stderr[-300:]}")
    check(not os.path.exists(path["w-clean"]), "контроль: слитая и чистая копия не убрана")
    check(g("rev-parse", "--verify", "-q", "w-clean").returncode != 0, "контроль: ветка убранной копии осталась")
    check(os.path.isfile(os.path.join(path["w-unpushed"], "work.txt")), "копия с неслитым коммитом удалена")
    check(g("rev-parse", "--verify", "-q", "w-unpushed").returncode == 0, "ветка с неслитым коммитом удалена")
    check(os.path.isfile(os.path.join(path["w-untracked"], "draft.txt")), "копия с неотслеживаемым файлом удалена")


def test_watch_and_wake_second_instance_exits_0184():
    """metis-0184: пока другой проход держит блокировку, второй watch и второй wake выходят без работы."""
    import fcntl
    e, folder, g = _wt_repo("g-dir")
    wt = os.path.join(folder, ".claude", "worktrees", "w-held")
    g("worktree", "add", "-q", "-b", "w-held", wt)
    old = T0 - 3 * 86400
    os.utime(wt, (old, old))
    e.task("g-0001", "g-dir", status="todo")
    e.agents([{"id": "dead0001", "sessionId": "dead0001-x", "name": "g-dir", "state": "failed", "kind": "background",
               "cwd": folder, "startedAt": (T0 - 7200) * 1000}])
    os.makedirs(e.st("locks"), exist_ok=True)
    with open(e.st("locks", "watch.lock"), "a") as fw, open(e.st("locks", "wake.lock"), "a") as fk:
        fcntl.flock(fw, fcntl.LOCK_EX)
        fcntl.flock(fk, fcntl.LOCK_EX)
        rw = e.run("watch", t=T0)
        rk = e.run("wake", t=T0)
    check(rw.returncode == 0 and "уже идёт другой проход" in rw.stdout, f"второй watch не вышел: {rw.stdout!r}")
    check(os.path.isdir(wt), "второй watch убрал копию")
    check(rk.returncode == 0 and "уже идёт в другом процессе" in rk.stdout, f"второй wake не вышел: {rk.stdout!r}")
    check(not e.calls(), f"второй watch/wake вызвал claude: {e.calls()}")
    check(not os.path.exists(e.st("start.log")) or "g-dir" not in open(e.st("start.log")).read(),
          "второй wake поднял сессию")
    # контроль: без чужой блокировки тот же watch работает и убирает копию
    e.run("watch", t=T0)
    check(not os.path.exists(wt), "контроль: свободный watch не убрал слитую копию")


def test_tick_subcommands():
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    for cmd in ("pantheon watch", "pantheon agents", "pantheon revisits", "pantheon usage 7"):
        check(p.parse_command(cmd) is not None, f"тик не пускает {cmd}")
    check(p.parse_command("pantheon restart --go") is None, "тик пускает restart")


def test_infra_check_managed_mode():
    """infra-check зовёт guard как живой хук: с --managed, когда управляемые настройки активны (metis-0114)."""
    import importlib.util
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    spec = importlib.util.spec_from_file_location("pantheon_watch_t", os.path.join(ROOT, "lib", "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(p)
    d = tempfile.mkdtemp(prefix="infra-")
    managed = os.path.join(d, "managed-settings.json")
    journal = os.path.join(d, "argv.log")
    fake = os.path.join(d, "guard.py")
    with open(fake, "w", encoding="utf-8") as fh:
        fh.write(
            "import json, sys\n"
            f"MANAGED = {managed!r}\n"
            f"JOURNAL = {journal!r}\n"
            "open(JOURNAL, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
            "mode = 'managed' if '--managed' in sys.argv else 'plugin'\n"
            "def active():\n"
            "    try:\n"
            "        data = json.load(open(MANAGED))\n"
            "    except (OSError, ValueError):\n"
            "        return False\n"
            "    for g in (data.get('hooks') or {}).get('PreToolUse') or []:\n"
            "        for h in g.get('hooks') or []:\n"
            "            c = h.get('command') or ''\n"
            "            if 'guard.py' in c and '--managed' in c:\n"
            "                return True\n"
            "    return False\n"
            "sys.stdin.read()\n"
            "if mode == 'plugin' and active():\n"
            "    sys.exit(0)\n"
            "print(json.dumps({'hookSpecificOutput': {'permissionDecision': 'deny'}}))\n")
    saved = {k: getattr(p, k) for k in ("MANAGED", "HOME", "guard_script", "agents_all", "alert_once", "clear_once")}
    want = "готово  guard отказывает на git push --force (роль dev-haiku)"
    try:
        p.MANAGED, p.HOME, p.guard_script, p.agents_all = managed, d, (lambda: fake), (lambda: [])
        p.alert_once = p.clear_once = lambda *a, **k: None  # тревоги — не в настоящий alerts.md
        with open(managed, "w", encoding="utf-8") as fh:
            json.dump({"hooks": {"PreToolUse": [{"hooks": [
                {"type": "command", "command": f'python3 "{fake}" --managed'}]}]}}, fh)
        _, lines = w.infra_check()
        check(want in lines, f"управляемые настройки активны: проба guard не отказала ({lines[:1]})")
        check("--managed" in open(journal).read(), "управляемые настройки активны: проба без --managed")
        os.remove(managed)
        os.remove(journal)
        _, lines = w.infra_check()
        check(want in lines, f"управляемых настроек нет: проба guard не отказала ({lines[:1]})")
        check("--managed" not in open(journal).read(), "управляемых настроек нет: проба с --managed")
        # строка «Python установки» (metis-alpha): не записан — ок с пометкой; записан и работает — ок; сломан — НЕТ
        st = os.path.join(d, "state")
        old_state = os.environ.get("PANTHEON_STATE")
        os.environ["PANTHEON_STATE"] = st
        try:
            ok, lines = w.infra_check()
            line = [x for x in lines if "Python установки" in x]
            check(line and "не записан (установка без pantheon-setup)" in line[0] and line[0].startswith("готово"),
                  f"Python не записан: ок с пометкой ({line})")
            os.makedirs(st)
            open(os.path.join(st, "config.toml"), "w").write(f'python = "{sys.executable}"\n')
            ok, lines = w.infra_check()
            line = [x for x in lines if "Python установки" in x]
            ver = "%d.%d.%d" % sys.version_info[:3]
            check(line and line[0].startswith("готово") and ver in line[0], f"Python записан и работает ({line})")
            open(os.path.join(st, "config.toml"), "w").write('python = "/nonexistent/python3.14"\n')
            ok, lines = w.infra_check()
            line = [x for x in lines if "Python установки" in x]
            check(not ok and line and line[0].startswith("НЕТ") and "не запускается" in line[0],
                  f"Python записан, но сломан: не ок ({line})")
        finally:
            if old_state is None:
                os.environ.pop("PANTHEON_STATE", None)
            else:
                os.environ["PANTHEON_STATE"] = old_state
    finally:
        for k, v in saved.items():
            setattr(p, k, v)


def test_infra_check_hq_section():
    """infra-check: нет раздела [hq] в policy.toml — строка НЕТ и тревога «штабу ничего не закрыто»; пустой [hq] —
    без тревоги, тревога снята; битый — строка НЕТ с причиной (metis-0182)."""
    import importlib.util
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    spec = importlib.util.spec_from_file_location("pantheon_watch_hq", os.path.join(ROOT, "lib", "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(p)
    d = tempfile.mkdtemp(prefix="infra-hq-")
    os.makedirs(os.path.join(d, ".claude", "pantheon"))
    pol = os.path.join(d, ".claude", "pantheon", "policy.toml")
    calls = []
    saved = {k: getattr(p, k) for k in ("MANAGED", "HOME", "guard_script", "agents_all", "alert_once", "clear_once")}
    try:
        p.MANAGED, p.HOME, p.guard_script, p.agents_all = os.path.join(d, "none.json"), d, (lambda: ""), (lambda: [])
        p.alert_once = lambda key, value, text, *a, **k: calls.append(("alert", key, text))
        p.clear_once = lambda key: calls.append(("clear", key))
        text = "в policy.toml нет раздела [hq]: штабу ничего не закрыто"
        for name, body in (("нет policy.toml", None), ("нет раздела", '[private]\nroles = ["hq"]\n')):
            calls.clear()
            if body is not None:
                open(pol, "w").write(body)
            ok, lines = w.infra_check()
            check(not ok and any(x.startswith("НЕТ") and "[hq]" in x for x in lines)
                  and any(c[0] == "alert" and c[1] == "hq-policy-missing" and c[2].startswith(text) for c in calls),
                  f"infra-check, {name}: нет строки НЕТ или тревоги про [hq] ({lines}, {calls})")
        calls.clear()
        open(pol, "w").write("[hq]\n")
        _, lines = w.infra_check()
        check(any(x.startswith("готово") and "[hq]" in x for x in lines)
              and not any(c[0] == "alert" and c[1] == "hq-policy-missing" for c in calls)
              and ("clear", "hq-policy-missing") in calls,
              f"infra-check, пустой [hq]: тревога или строка НЕТ ({lines}, {calls})")
        calls.clear()
        open(pol, "w").write('[hq]\nclosed_dirs = "~/x"\n')
        _, lines = w.infra_check()
        check(any(x.startswith("НЕТ") and "[hq].closed_dirs" in x for x in lines),
              f"infra-check, битый [hq]: нет строки НЕТ с причиной ({lines})")
    finally:
        for k, v in saved.items():
            setattr(p, k, v)


def test_infra_check_corpus_section():
    """infra-check: нет раздела [corpus] в policy.toml — строка НЕТ и тревога «corpus-role ничего не закрывает»;
    раздел есть (и пустой) — без тревоги, тревога снята; policy.toml не TOML — без второй строки (metis-0182)."""
    import importlib.util
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    spec = importlib.util.spec_from_file_location("pantheon_watch_corpus", os.path.join(ROOT, "lib", "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(p)
    d = tempfile.mkdtemp(prefix="infra-corpus-")
    os.makedirs(os.path.join(d, ".claude", "pantheon"))
    pol = os.path.join(d, ".claude", "pantheon", "policy.toml")
    calls = []
    saved = {k: getattr(p, k) for k in ("MANAGED", "HOME", "guard_script", "agents_all", "alert_once", "clear_once")}
    try:
        p.MANAGED, p.HOME, p.guard_script, p.agents_all = os.path.join(d, "none.json"), d, (lambda: ""), (lambda: [])
        p.alert_once = lambda key, value, text, *a, **k: calls.append(("alert", key, text))
        p.clear_once = lambda key: calls.append(("clear", key))
        text = "в policy.toml нет раздела [corpus]: правило corpus-role ничего не закрывает"
        for name, body in (("нет policy.toml", None), ("нет раздела", "[hq]\n")):
            calls.clear()
            if body is not None:
                open(pol, "w").write(body)
            ok, lines = w.infra_check()
            check(not ok and any(x.startswith("НЕТ") and "[corpus]" in x for x in lines)
                  and any(c[0] == "alert" and c[1] == "corpus-policy-missing" and c[2].startswith(text) for c in calls),
                  f"infra-check, {name}: нет строки НЕТ или тревоги про [corpus] ({lines}, {calls})")
        for name, body in (("пустой [corpus]", "[hq]\n[corpus]\n"),
                           ("[corpus] со списком", '[hq]\n[corpus]\ncommands = ["corpus-x"]\n')):
            calls.clear()
            open(pol, "w").write(body)
            _, lines = w.infra_check()
            check(any(x.startswith("готово") and "[corpus]" in x for x in lines)
                  and not any(c[0] == "alert" and c[1] == "corpus-policy-missing" for c in calls)
                  and ("clear", "corpus-policy-missing") in calls,
                  f"infra-check, {name}: тревога или строка НЕТ ({lines}, {calls})")
        calls.clear()
        open(pol, "w").write("[hq\n")
        _, lines = w.infra_check()
        check(not any("[corpus]" in x for x in lines)
              and not any(c[1] == "corpus-policy-missing" for c in calls),
              f"infra-check, policy.toml не TOML: лишняя строка или тревога про [corpus] ({lines}, {calls})")
    finally:
        for k, v in saved.items():
            setattr(p, k, v)


def test_infra_check_hooks_tomllib():
    """infra-check: python3 хуков без tomllib — строка НЕТ и тревога «guard не читает policy.toml»; с tomllib —
    строка «готово» и тревога снята (metis-0182: иначе пустой corpus-role на Python до 3.11 молчит)."""
    import importlib.util
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    spec = importlib.util.spec_from_file_location("pantheon_watch_tomllib", os.path.join(ROOT, "lib", "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(p)
    d = tempfile.mkdtemp(prefix="infra-toml-")
    calls = []
    saved = {k: getattr(p, k) for k in ("MANAGED", "HOME", "guard_script", "agents_all", "alert_once", "clear_once")}
    try:
        p.MANAGED, p.HOME, p.guard_script, p.agents_all = os.path.join(d, "none.json"), d, (lambda: ""), (lambda: [])
        p.alert_once = lambda key, value, text, *a, **k: calls.append(("alert", key, text))
        p.clear_once = lambda key: calls.append(("clear", key))
        line = "python3 хуков читает policy.toml"
        for rc, name in ((1, "без tomllib"), (0, "с tomllib")):
            fake = os.path.join(d, f"py{rc}")
            with open(fake, "w") as fh:
                fh.write(f"#!/bin/sh\nexit {rc}\n")
            os.chmod(fake, 0o755)
            w.HOOK_PYTHON = fake
            calls.clear()
            _, lines = w.infra_check()
            alerted = any(c[0] == "alert" and c[1] == "hooks-python-no-tomllib" and "policy.toml" in c[2]
                          for c in calls)
            if rc:
                check(any(x.startswith("НЕТ") and line in x for x in lines) and alerted,
                      f"infra-check, {name}: нет строки НЕТ или тревоги ({lines}, {calls})")
            else:
                check(any(x.startswith("готово") and line in x for x in lines) and not alerted
                      and ("clear", "hooks-python-no-tomllib") in calls,
                      f"infra-check, {name}: строка НЕТ, тревога или тревога не снята ({lines}, {calls})")
        w.HOOK_PYTHON = os.path.join(d, "нет-такого")
        calls.clear()
        _, lines = w.infra_check()
        check(any(x.startswith("НЕТ") and line in x for x in lines),
              f"infra-check, python3 не найден: нет строки НЕТ ({lines})")
    finally:
        for k, v in saved.items():
            setattr(p, k, v)


def test_who_is_who_memo():
    """Памятка «Кто есть кто.md» сверяется с ролями и реестром: +роль, −лишнее, совпало — тревога снята (metis-0120)."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    import importlib
    p = importlib.import_module("pantheon")
    d = tempfile.mkdtemp(prefix="who-")
    pan, st, ag = (os.path.join(d, x) for x in ("pantheon", "state", "agents"))
    for x in (pan, st, ag):
        os.makedirs(x)
    for r in ("argus", "momus", "hq", "workshop", "domain-coordinator", "hephaestus-pantheon", "apollo-site"):
        open(os.path.join(ag, r + ".md"), "w").write("---\nname: x\n---\n")
    os.makedirs(os.path.join(ag, "_parts"))
    open(os.path.join(ag, "argus.tmpl"), "w").write("шаблон")
    open(os.path.join(pan, "directions.toml"), "w").write(
        '[[direction]]\nname = "metis-pantheon"\n[[direction]]\nname = "hermes-site"\n')
    memo = os.path.join(pan, "Кто есть кто.md")
    full = ("`zeus` `daedalus-<задача>` `metis-pantheon` `hermes-site` `argus` `momus` `hephaestus-<проект>` "
            "`apollo-<проект>` `claude agents` `pantheon tick` `~/.claude/agents/<роль>.md`\n")
    saved = {k: getattr(p, k) for k in ("PANTHEON", "STATE", "AGENTS")}
    alerts = os.path.join(pan, "alerts.md")

    def read():
        return open(alerts, encoding="utf-8").read() if os.path.exists(alerts) else ""

    def put(text):
        open(memo, "w", encoding="utf-8").write(text)
    try:
        p.PANTHEON, p.STATE, p.AGENTS = pan, st, ag
        os.environ["PANTHEON_NO_NOTIFY"] = "1"
        # 1. всё совпадает (чужой код в кавычках не мешает): тихо
        put(full)
        check(p.who_is_who_check() == ([], []), f"совпало, а сверка нашла {p.who_is_who_check()}")
        check(p.who_is_who_alert() == "" and not read(), "совпало, а тревога есть")
        # 2. роли нет в памятке: +momus, на том же состоянии строка одна
        put(full.replace("`momus` ", ""))
        line = p.who_is_who_alert()
        check(line == "памятку обновить: +momus" and "+momus" in read(), f"нет тревоги +momus: {line!r}")
        p.who_is_who_alert()
        check(read().count("+momus") == 1, "тревога +momus повторилась на том же состоянии")
        # 3. направление пропало, лишнее есть: +hermes-site / −janus-probe
        put(full.replace("`hermes-site` ", "") + "`janus-probe` `hephaestus-old`\n")
        line = p.who_is_who_alert()
        check(line == "памятку обновить: +hermes-site / −hephaestus-old / −janus-probe", f"нет −janus-probe: {line!r}")
        # 4. снова совпало: тревога снята — новый сбой пишется заново
        put(full)
        check(p.who_is_who_alert() == "", "совпало, а тревога осталась")
        put(full.replace("`momus` ", ""))
        p.who_is_who_alert()
        check(read().count("+momus") == 2, "после снятия тревога +momus не вернулась")
        # 5. нет памятки: проверять нечего
        os.remove(memo)
        check(p.who_is_who_check() is None and p.who_is_who_alert() == "", "нет памятки, а сверка что-то нашла")
    finally:
        for k, v in saved.items():
            setattr(p, k, v)
        os.environ.pop("PANTHEON_NO_NOTIFY", None)
        shutil.rmtree(d, ignore_errors=True)


def test_autostart_nudges_idle_holder_0212():
    """metis-0212: Claude Code сам перезапустил фоновую сессию, задания у неё нет (claude agents: `state` working,
    `status` idle), а у направления задача с вашей отметкой — не «уже работает», а передача задания той же сессии
    тем же текстом самозапуска (claude respawn + текст для хука push) и тревога «…задания у неё нет — передал
    задание». Работает — `status` busy или живые субагенты: тогда не трогаем. Закончила ход (`state` done с живым
    процессом) — тоже передача задания, а не только тревога Зевсу. Передача не помогла (снова простаивает,
    STATUS.md не менялся) — сбой самозапуска, а не новая передача на каждом проходе."""
    e = Env()
    e.direction("fl-dir")
    e.task("fl-0001", "fl-dir")
    e.run("watch", t=T0)
    e.board("fl-0001", T0 + 10)
    a = bg("fl-dir", "working", "f1ee7001-1", pid=41)
    a["status"] = "busy"
    e.agents([a])
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check("fl-dir: уже работает" in out, f"0212: status busy — не «уже работает»: {out}")
    a["status"] = "idle"
    a["inFlight"] = {"tasks": 1, "queued": 0, "kinds": ["agent"]}
    e.agents([a])
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check("fl-dir: уже работает" in out, f"0212: idle с живыми субагентами — не «уже работает»: {out}")
    del a["inFlight"]
    e.agents([a])
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check(f"fl-dir: {RESTARTED} — передал бы задание" in out, f"0212: dry-run не передаёт задание: {out}")
    e.run("watch", t=T0 + 120)
    check(["respawn", "f1ee7001"] in e.calls(), f"0212: перезапущенной сессии задание не передано: {e.calls()}")
    check(not [c for c in e.calls() if c[:1] == ["--bg"]], f"0212: вместо передачи задания новая сессия: {e.calls()}")
    pushed = e.st("push", "f1ee7001-1.txt")
    text = open(pushed).read() if os.path.exists(pushed) else ""
    check(text.startswith("[Пантеон: поручение от tick] Самозапуск дежурным") and "fl-0001" in text,
          f"0212: текст задания не тот, что у самозапуска: {text!r}")
    check(f"fl-dir: {RESTARTED} — передал задание" in e.alerts(), f"0212: нет тревоги: {e.alerts()}")
    os.remove(pushed)  # хук push забрал текст при старте процесса
    # следующий проход: сессия всё ещё простаивает — второй передачи нет (пауза между попытками)
    e.run("watch", t=T0 + 420)
    check(len([c for c in e.calls() if c[:1] == ["respawn"]]) == 1, f"0212: передача на каждом проходе: {e.calls()}")
    check(json.load(open(e.st("autostart.json")))["fl-dir"].get("fails") == 1,
          "0212: передача не помогла (снова простаивает, STATUS.md не менялся) — не засчитана сбоем")
    # закончила ход с живым процессом — тоже передача задания
    e2 = Env()
    e2.direction("dn-dir")
    e2.task("dn-0001", "dn-dir")
    e2.run("watch", t=T0)
    e2.board("dn-0001", T0 + 10)
    e2.agents([bg("dn-dir", "done", "d0ee7001-1", pid=42)])
    e2.run("watch", t=T0 + 120)
    check(["respawn", "d0ee7001"] in e2.calls(), f"0212: done с процессом — задание не передано: {e2.calls()}")
    check("dn-dir: закончила ход, а задачи с вашим решением ждут — передал задание" in e2.alerts(),
          f"0212: нет тревоги о передаче задания done: {e2.alerts()}")
    # вкладка (реестр) и status idle без отметки владельца не трогаются
    e3 = Env()
    e3.direction("nt-dir")
    e3.task("nt-0001", "nt-dir")
    b = bg("nt-dir", "working", "a0ee7001-1", pid=43)
    b["status"] = "idle"
    e3.agents([b])
    e3.run("watch", t=T0)
    e3.run("watch", t=T0 + 120)
    check(not [c for c in e3.calls() if c[:1] == ["respawn"]], f"0212: передача без вашей отметки: {e3.calls()}")


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


def test_autostart_nudge_backoff_after_success_0212():
    """metis-0212, ревью argus: сбой → удачная передача задания → следующая не раньше чем через час после неё.
    Успех стирает `next` (паузу после сбоя): иначе прошедший `next` пускал передачу на каждом проходе."""
    e, _ = idle_env("bk-dir", "b0ee7001-1")
    e.run("watch", t=T0 + 120)                              # передача 1
    os.remove(e.st("push", "b0ee7001-1.txt"))
    e.run("watch", t=T0 + 420)                              # снова простаивает, STATUS.md тот же — сбой 1
    st = json.load(open(e.st("autostart.json")))["bk-dir"]
    check(st.get("fails") == 1 and st.get("next"), f"0212: сбой не записан: {st}")
    t2 = T0 + 420 + 4000                                    # после паузы сбоя (1 ч ±10 %)
    e.run("watch", t=t2)                                    # передача 2
    check(len(respawns(e)) == 2, f"0212: после паузы сбоя задание не передано: {e.calls()}")
    os.remove(e.st("push", "b0ee7001-1.txt"))
    status = os.path.join(e.pantheon, "directions", "bk-dir", "STATUS.md")
    open(status, "w").write("сделано\n")
    os.utime(status, (t2 + 100, t2 + 100))                  # сессия поработала и записала STATUS.md — успех
    e.run("watch", t=t2 + 300)
    e.run("watch", t=t2 + 600)
    st = json.load(open(e.st("autostart.json")))["bk-dir"]
    check(len(respawns(e)) == 2, f"0212: после успеха передача раньше часа (старый next): {respawns(e)}")
    check(st.get("fails") == 0 and "next" not in st, f"0212: успех не сбросил fails и next: {st}")
    e.run("watch", t=t2 + 3700)
    check(len(respawns(e)) == 3, f"0212: через час после успеха задание не передано: {respawns(e)}")


def test_autostart_nudge_guards_0212():
    """metis-0212, ревью argus: задание не передаётся сессии, которая работает или ждёт — по state.json (`inFlight`),
    по разрешению (`waitingFor`), по своему пробуждению (ScheduleWakeup: `inFlight.wake`, вид session_cron,
    `selfWake`), — и направлению, которое вы остановили или поставили на паузу."""
    e, a = idle_env("gd-dir", "c0ee7001-1")

    def dry():
        return e.run("watch", "--dry-run", t=T0 + 120).stdout

    out = dry()
    check(f"gd-dir: {RESTARTED} — передал бы задание" in out, f"0212: исходное состояние — не передача: {out}")
    # живые субагенты видны только в state.json, а в claude agents их нет
    job_state(e, "c0ee7001-1", {"state": "working", "inFlight": {"tasks": 2, "queued": 0, "kinds": ["local_agent"]}})
    out = dry()
    check("gd-dir: уже работает" in out, f"0212: inFlight из state.json не прочитан: {out}")
    # закончила ход с ScheduleWakeup: Claude Code 2.1.302 кладёт пробуждение в inFlight и ставит selfWake
    wake = {"at": T0 * 1000, "fires": 0}
    for js in ({"inFlight": {"tasks": 1, "queued": 0, "kinds": ["session_cron"], "wake": wake}, "selfWake": True},
               {"inFlight": {"tasks": 0, "queued": 0, "kinds": ["session_cron"]}},
               {"inFlight": {"tasks": 0, "queued": 0, "kinds": [], "wake": wake}},
               {"inFlight": {"tasks": 0, "queued": 0, "kinds": []}, "selfWake": True}):
        job_state(e, "c0ee7001-1", dict(js, state="working"))
        out = dry()
        check("gd-dir: уже работает" in out, f"0212: назначенное пробуждение {js} — не «уже работает»: {out}")
    job_state(e, "c0ee7001-1", {"state": "working", "inFlight": {"tasks": 0, "queued": 0, "kinds": []}})
    check(f"gd-dir: {RESTARTED} — передал бы задание" in dry(), "0212: пустой inFlight в state.json мешает передаче")
    # ждёт вашего разрешения
    a["waitingFor"] = "permission"
    e.agents([a])
    out = dry()
    check("gd-dir: уже работает" in out, f"0212: ждёт разрешения — не «уже работает»: {out}")
    del a["waitingFor"]
    e.agents([a])
    # остановлено вами
    os.makedirs(e.st("stopped"), exist_ok=True)
    open(e.st("stopped", "gd-dir"), "w").write("вы\n")
    out = dry()
    check(f"gd-dir: {RESTARTED} — передача задания ждёт: остановлено вами" in out, f"0212: обход остановки: {out}")
    e.run("watch", t=T0 + 120)
    check(not respawns(e), f"0212: задание передано остановленному направлению: {e.calls()}")
    os.remove(e.st("stopped", "gd-dir"))
    # пауза по нагрузке этого направления и общая пауза планировщика
    os.makedirs(e.st("pauses"), exist_ok=True)
    json.dump({"reason": "manual", "time": "2026-10-15T07:00:00"}, open(e.st("pauses", "gd-dir.json"), "w"))
    out = dry()
    check("передача задания ждёт: пауза по нагрузке (manual)" in out, f"0212: обход паузы по нагрузке: {out}")
    e.run("watch", t=T0 + 120)
    check(not respawns(e), f"0212: задание передано на паузе по нагрузке: {e.calls()}")
    os.remove(e.st("pauses", "gd-dir.json"))
    open(e.st("paused"), "w").write("вы\n")
    out = dry()
    check(f"gd-dir: {RESTARTED} — передача задания ждёт:" in out, f"0212: обход общей паузы: {out}")
    e.run("watch", t=T0 + 120)
    check(not respawns(e), f"0212: задание передано на общей паузе: {e.calls()}")
    os.remove(e.st("paused"))
    e.run("watch", t=T0 + 120)
    check(["respawn", "c0ee7001"] in e.calls(), f"0212: без помех задание не передано: {e.calls()}")


def test_autostart_nudge_week_limit_0212():
    """metis-0212, ревью argus-43: передача задания простаивающей сессии — новое дело и ждёт недельный лимит, как
    новый запуск (gate «autostart»): жёлтая зона днём, красная, снимок старше 30 мин — ни respawn, ни новой сессии,
    в dry-run «передача задания ждёт: недельный лимит: …»; зелёная — задание передано. Жёлтую днём и старый снимок
    gate продолжения («respawn» в wake_block) пропускает — их ловит только проверка самозапуска."""
    e, _ = idle_env("wk-dir", "e0ee7001-1")
    cases = ((31.6, 0, "жёлтая зона днём"), (90.0, 0, "красная зона"), (10.0, 31 * 60, "лимит неизвестен (31 мин)"))
    for i, (pct, age, why) in enumerate(cases):
        e.week_pct, e.snap_age = pct, age
        out = e.run("watch", "--dry-run", t=T0 + 120 + i).stdout
        check(f"wk-dir: {RESTARTED} — передача задания ждёт: недельный лимит: {why}" in out,
              f"0212: неделя {pct} %, снимок {age} с — передача задания мимо недельного лимита: {out[-500:]}")
        e.run("watch", t=T0 + 130 + i)
        check(not respawns(e) and not [c for c in e.calls() if c[:1] == ["--bg"]],
              f"0212: неделя {pct} %, снимок {age} с — задание передано: {e.calls()}")
    e.week_pct, e.snap_age = 10.0, 0
    e.run("watch", t=T0 + 200)
    check(["respawn", "e0ee7001"] in e.calls(), f"0212: зелёная неделя — задание не передано: {e.calls()}")


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


def test_plugins_respawn_live_subagent_0181():
    """metis-0181: окно idle (закончило ход), а его субагент писал 5 мин назад — лид работает, окно не перезапускается,
    отметка стоит; субагент затих 15+ мин назад — перезапуск, отметка снята, строка в тревогах."""
    e, a, tp = respawn_env("rs-dir", "a5a5a5a5-1")
    sub = subagent(tp, T0 - 300)
    e.run("watch", t=T0)
    check(not respawned(e, "a5a5a5a5") and os.path.exists(e.st("plugins", "respawn.json")),
          f"0181: idle с субагентом, писавшим 5 мин назад, перезапущено: {e.calls()}")
    os.utime(sub, (T0 - 1200, T0 - 1200))
    r = e.run("watch", t=T0 + 60)
    check(respawned(e, "a5a5a5a5"), f"0181: субагент затих 20 мин назад — не перезапущено: {e.calls()} {r.stderr[-300:]}")
    pushed = e.st("push", "a5a5a5a5-1.txt")
    check(os.path.exists(pushed) and "[Пантеон: перезапуск после обновления плагинов]" in open(pushed).read(),
          "0181: перезапуску не передан текст «перезапуск после обновления плагинов»")
    check(not os.path.exists(e.st("plugins", "respawn.json")), "0181: все перезапущены — отметка не снята")
    check("перезапуск после обновления плагинов (pantheon): перезапущены rs-dir" in e.alerts(),
          f"0181: нет строки в тревогах: {e.alerts()}")


def test_plugins_respawn_idle_free_0181():
    """metis-0181: idle, транскрипт и субагенты старше 15 мин, worktree нет — перезапуск. Свежая worktree лида в папке
    направления держит окно; поднятое после установки и Зевс — не кандидаты."""
    e, a, tp = respawn_env("rf-dir", "b6b6b6b6-1")
    subagent(tp, T0 - 1800)
    wt = worktree(e, "rf-dir", T0 - 300)
    e.run("watch", t=T0)
    check(not respawned(e, "b6b6b6b6"), f"0181: worktree лида менялась 5 мин назад — перезапущено: {e.calls()}")
    shutil.rmtree(wt)
    os.utime(os.path.dirname(wt), (T0 - 3600, T0 - 3600))
    e.run("watch", t=T0 + 60)
    check(respawned(e, "b6b6b6b6"), f"0181: idle 15+ мин без субагентов и worktree — не перезапущено: {e.calls()}")
    check(not os.path.exists(e.st("plugins", "respawn.json")), "0181: отметка не снята после перезапуска")
    # поднято после установки (startedAt > since) — не кандидат, отметка снимается: кандидатов нет
    e, a, tp = respawn_env("ra-dir", "c7c7c7c7-1", since=T0 - 200)
    e.run("watch", t=T0)
    check(not respawned(e, "c7c7c7c7") and not os.path.exists(e.st("plugins", "respawn.json")),
          f"0181: перезапущено окно, поднятое после установки: {e.calls()}")
    # Зевс поднят до установки, свободен и окно штаба есть — всё равно не трогаем (его перезапускаете вы)
    e, a, tp = respawn_env("rz-dir", "c8c8c8c8-1", since=T0 - 200)
    json.dump({"env": {}}, open(e.st("settings", "hq.json"), "w"))
    e.direction("zeus")  # окно есть: без исключения Зевса тик дошёл бы до respawn, а не споткнулся о «нет окна»
    z = bg("zeus", "done", "d8d8d8d8-1", pid=52, started=T0 - 1000)
    e.agents([a, z])
    transcript(e, z, 20_000, T0 - 3600)
    e.run("watch", t=T0)
    check(not respawned(e, "d8d8d8d8") and not [c for c in e.calls() if "--resume" in c or c[:1] == ["stop"]]
          and "\tzeus\td8d8d8d8\tplugins-respawn" not in _start_log(e),
          f"0181: Зевс перезапущен тиком: {e.calls()} {_start_log(e)!r}")


def test_plugins_respawn_empty_agents_0181():
    """metis-0181, ревью argus: пустой claude agents ([]) — не «все перезапущены»: отметка respawn.json остаётся."""
    e, a, tp = respawn_env("re-dir", "c9c9c9c9-1")
    e.agents([])
    e.run("watch", t=T0)
    check(os.path.exists(e.st("plugins", "respawn.json")), "0181: пустой claude agents снял отметку перезапуска")


def test_plugins_respawn_wait_alert_0181():
    """metis-0181, ревью argus: окна, которые ждут, видны строкой в тревогах и без перезапусков — одна строка на набор
    окон (не на каждом проходе); ожидание кончилось — следующий набор снова строкой."""
    e, a, tp = respawn_env("rw-dir", "cacacaca-1")
    subagent(tp, T0 - 300)
    e.run("watch", t=T0)
    e.run("watch", t=T0 + 60)
    line = "перезапуск после обновления плагинов (pantheon) ждёт: rw-dir (субагент писал меньше 15 мин назад)"
    check(e.alerts().count(line) == 1 and not respawned(e, "cacacaca"),
          f"0181: нет строки «ждёт» или она на каждом проходе: {e.alerts()}")


def test_plugins_respawn_ok_mark_0181():
    """metis-0181: метка «можно» (pantheon saved без техперезапуска) — перезапуск сразу, хоть транскрипт и свежий;
    busy — нет даже с меткой. Без отметки respawn.json pantheon saved отмечать нечего."""
    e, a, tp = respawn_env("rk-dir", "e9e9e9e9-1", state="working", status="busy")
    os.utime(tp, (T0 - 60, T0 - 60))
    r = e.run("saved", "--by", "rk-dir", "--state", "STATUS.md", t=T0)
    check(r.returncode == 0 and os.path.exists(e.st("plugins", "respawn-ok", "rk-dir.json")),
          f"0181: pantheon saved не поставил метку «можно»: {r.returncode} {r.stdout} {r.stderr}")
    check(not os.path.exists(e.st("maintenance", "rk-dir.json")), "0181: метка «можно» легла в maintenance/")
    e.run("watch", t=T0 + 10)
    check(not respawned(e, "e9e9e9e9") and os.path.exists(e.st("plugins", "respawn.json")),
          f"0181: busy с меткой «можно» перезапущено: {e.calls()}")
    a["status"] = "idle"
    e.agents([a])
    e.run("watch", t=T0 + 20)
    check(respawned(e, "e9e9e9e9"), f"0181: idle с меткой «можно» не перезапущено: {e.calls()}")
    check(not os.path.exists(e.st("plugins", "respawn.json"))
          and not os.path.exists(e.st("plugins", "respawn-ok", "rk-dir.json")), "0181: отметка и метка не сняты")
    # без метки тот же свежий транскрипт держит окно
    e, a, tp = respawn_env("rn-dir", "f0f0f0f0-1")
    os.utime(tp, (T0 - 60, T0 - 60))
    e.run("watch", t=T0)
    check(not respawned(e, "f0f0f0f0"), f"0181: транскрипт менялся минуту назад, метки нет — перезапущено: {e.calls()}")
    # метка старше since (прошлого обновления) не считается
    os.makedirs(e.st("plugins", "respawn-ok"), exist_ok=True)
    json.dump({"t": T0 - 100}, open(e.st("plugins", "respawn-ok", "rn-dir.json"), "w"))
    e.run("watch", t=T0 + 10)
    check(not respawned(e, "f0f0f0f0"), f"0181: метка старше since сочтена «можно»: {e.calls()}")
    e2 = Env()
    r = e2.run("saved", "--by", "rk-dir", "--state", "STATUS.md", t=T0)
    check(r.returncode == 1 and "отмечать нечего" in r.stdout, f"0181: saved без отметки: {r.returncode} {r.stdout}")



def test_plugins_respawn_recheck_0181():
    """metis-0181: под блокировкой имени перед перезапуском — свежий claude agents: окно, получившее ввод между проходом
    и перезапуском (status busy), не перезапускается, строка resume-skip в start.log, отметка стоит."""
    e, a, tp = respawn_env("rr-dir", "a1b2c3d4-1")
    b = dict(a, state="working", status="busy")
    nxt = os.path.join(e.tmp, "agents-next.json")
    json.dump([b], open(nxt, "w"))
    e.run("watch", t=T0, extra={"FAKE_AGENTS_NEXT": nxt})
    check(not respawned(e, "a1b2c3d4") and "\tresume-skip\trr-dir\ta1b2c3d4\tplugins-respawn\tзанято" in _start_log(e)
          and os.path.exists(e.st("plugins", "respawn.json")),
          f"0181: окно, занятое к моменту перезапуска, перезапущено: {e.calls()} {_start_log(e)!r}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            FAILS.append(f"{fn.__name__}: {type(ex).__name__}: {ex}")
            print("ОШИБКА:", fn.__name__, type(ex).__name__, ex)
    print(f"тестов: {len(tests)}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
