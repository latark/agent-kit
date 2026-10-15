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
    print(open(os.environ["FAKE_AGENTS"]).read())
elif a[:1] == ["--version"]:
    print(os.environ.get("FAKE_CC", "2.1.292") + " (Claude Code)")
elif a[:1] == ["respawn"] and os.environ.get("FAKE_RESPAWN_RC"):
    print("respawn: no such session", file=sys.stderr)
    sys.exit(int(os.environ["FAKE_RESPAWN_RC"]))
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
        self.log = os.path.join(self.tmp, "claude.log")
        self.agents_file = os.path.join(self.tmp, "agents.json")
        self.notify = os.path.join(self.tmp, "notify.log")
        self.agents([])
        open(os.path.join(self.pantheon, "schedule.toml"), "w").write('primary_host = "mac-a"\n[defaults]\nlimit_max_pct = 70\n')
        self.doms = {}
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

    def run(self, *args, t=T0, extra=None):
        env = {"PATH": self.bin + ":" + os.environ["PATH"], "HOME": self.home, "PANTHEON_HOME": self.pantheon,
               "PANTHEON_STATE": self.state, "PANTHEON_NOW": str(t), "PANTHEON_HOST": "mac-a",
               "PANTHEON_NOTIFY_LOG": self.notify, "FAKE_CLAUDE_LOG": self.log, "FAKE_AGENTS": self.agents_file,
               "PANTHEON_FAKE_SWAP": "1.0", "PANTHEON_FAKE_PS": "", "PANTHEON_FAKE_CC": "2.1.292",
               "PANTHEON_FAKE_LIMIT": "10"}
        env.update(self.extra)
        env.update(extra or {})
        return subprocess.run([sys.executable, "-I", LIB, *args], env=env, capture_output=True, text=True, timeout=60)

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
    # без доверия — тревога и уведомление, запуска нет
    e2 = Env()
    e2.direction("athena-y", trusted=False)
    e2.task("athena-0002", "athena-y")
    e2.run("watch", t=T0)
    e2.board("athena-0002", T0 + 60)
    e2.run("watch", t=T0 + 120)
    check(not [c for c in e2.calls() if c[:1] == ["--bg"]], "запуск без доверия")
    check("нет доверия" in e2.alerts(), "тревога о доверии")


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
    чужой текст толчка — под своей пометкой; saved — только себя."""
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
    check(pushed.startswith("[Пантеон: толчок от владелец] сделай X"), f"текст толчка без пометки: {pushed}")
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
                                              capture_output=True, text=True, env=dict(os.environ, HOME=e.home))
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
    saved = {k: getattr(p, k) for k in ("MANAGED", "HOME", "guard_script", "agents_all")}
    want = "готово  guard отказывает на git push --force (роль dev-haiku)"
    try:
        p.MANAGED, p.HOME, p.guard_script, p.agents_all = managed, d, (lambda: fake), (lambda: [])
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
    finally:
        for k, v in saved.items():
            setattr(p, k, v)


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
