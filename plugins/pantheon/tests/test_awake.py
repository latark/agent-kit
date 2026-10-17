#!/usr/bin/env python3
"""Тесты ночного цикла (lib/awake.py): бодрость Mac (metis-0126), напоминание о перезагрузке, подъём после недельного
лимита (metis-0132), будильник ждущих (metis-0127 п. 2).

Запуск: python3 -I plugins/pantheon/tests/test_awake.py  (код выхода 0 — все прошли)
Модули pantheon и awake грузятся в процесс теста, их папки (HOME, PANTHEON, STATE) подменены временными. Настоящий
caffeinate не запускается: вместо него скрипт из временной папки, пишущий журнал запусков и спящий. `ps` подменён
(в песочнице окна он закрыт, а проверять нужно «наш ли это процесс»). Подъём сессий — запись вызова
resume_session, запор ночного модуля — подставленная функция.
"""
import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # pantheon.py идёт только на Python 3.11+
if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)])
import atexit
import contextlib
import io
import shutil
import signal
import tempfile
import time
import types
from datetime import datetime, timezone

_ROOT = tempfile.mkdtemp(prefix="awake-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import importlib
P = importlib.import_module("pantheon")
AW = P.awake_mod()
FAILS = []
SPAWNED = []

FAKE_CAFFEINATE = '''#!/usr/bin/env python3
import os, sys, time
open(os.environ["FAKE_CAFFEINATE_LOG"], "a").write(" ".join(sys.argv[1:]) + "\\n")
time.sleep(120)
'''


def _reap():
    for pid in SPAWNED:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)
        with contextlib.suppress(OSError):
            os.waitpid(pid, 0)


atexit.register(_reap)


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("НЕ ПРОШЛО:", what)


def at(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm).timestamp()


MON = at(2026, 10, 19, 12, 0)   # понедельник
FRI = at(2026, 10, 23, 10, 0)   # пятница
DOMS = {"hermes-site": ["x"], "athena-shop": ["y"]}


class Env:
    """Временные HOME, ~/ai/pantheon и STATE; подмены модуля и окружения."""

    def __init__(self, ac=True, batt=None):
        self.tmp = tempfile.mkdtemp(prefix="awake-test-")
        self.home = os.path.join(self.tmp, "home")
        self.pantheon = os.path.join(self.home, "ai", "pantheon")
        self.state = os.path.join(self.tmp, "state")
        self.bin = os.path.join(self.tmp, "bin")
        for d in (self.pantheon, self.state, self.bin):
            os.makedirs(d)
        self.caff = os.path.join(self.bin, "caffeinate")
        open(self.caff, "w").write(FAKE_CAFFEINATE)
        os.chmod(self.caff, 0o755)
        self.caff_log = os.path.join(self.tmp, "caff.log")
        self.notify_log = os.path.join(self.tmp, "notify.log")
        self.calls = []
        self.gate_calls = []
        self.gate_ok = (True, None)
        self.foreign = set()
        self.seen = set()
        P.HOME, P.PANTHEON, P.STATE = self.home, self.pantheon, self.state
        P._TASKS = None
        os.environ.update({"HOME": self.home, "PANTHEON_HOST": "mac-a", "PANTHEON_NOTIFY_LOG": self.notify_log,
                           "FAKE_CAFFEINATE_LOG": self.caff_log, "PANTHEON_FAKE_IDLE": "9999",
                           "PANTHEON_FAKE_AC": "1" if ac else "0"})
        os.environ.pop("PANTHEON_FAKE_SWAP", None)
        if batt is None:
            os.environ.pop("PANTHEON_FAKE_BATT", None)
        else:
            os.environ["PANTHEON_FAKE_BATT"] = str(batt)
        self.schedule()
        json.dump({"domains": DOMS}, open(os.path.join(self.state, "domains.json"), "w"))
        AW.CAFFEINATE = self.caff
        AW.proc_comm = self.comm
        AW.RESUMED.clear()
        AW._NIGHT = types.SimpleNamespace(gate=self.gate)
        P.resume_session = self.resume
        P.agents_all = lambda: self.agents_list
        self.agents_list = []
        self.now(MON)

    def schedule(self, jobs=""):
        open(os.path.join(self.pantheon, "schedule.toml"), "w").write(
            'primary_host = "mac-a"\n[defaults]\nlimit_max_pct = 70\n[notify]\nquiet_start = "00:00"\n'
            'quiet_end = "00:00"\n[[job]]\nname = "watch"\ncommand = "pantheon watch"\nevery = 5\n' + jobs)

    def now(self, t):
        os.environ["PANTHEON_NOW"] = str(t)
        return t

    # подмены
    def comm(self, pid):
        if pid in self.foreign:
            with contextlib.suppress(OSError):
                os.kill(pid, 0)
                return "python3"
            return ""
        try:
            done, _ = os.waitpid(pid, os.WNOHANG)
            if done:
                return ""
        except ChildProcessError:
            try:
                os.kill(pid, 0)
            except OSError:
                return ""
        return "caffeinate"

    def gate(self, kind, t, agents=None, registry=None, heavy=None):
        self.gate_calls.append(kind)
        return self.gate_ok

    def resume(self, name, a, text, origin, recheck=None):
        why = recheck() if recheck else None
        if why:
            return 1, None
        self.calls.append((name, text, origin))
        return 0, None

    # сессии
    def agent(self, name, state="working", sid=None, **state_json):
        sid = sid or f"{abs(hash(name)) % 10**8:08x}"
        a = {"id": sid, "sessionId": sid + "-0000", "name": name, "state": state, "pid": 1, "kind": "background",
             "cwd": self.home, "startedAt": (MON - 100000) * 1000}
        d = os.path.join(self.home, ".claude", "jobs", sid)
        os.makedirs(d, exist_ok=True)
        json.dump({"state": state, **state_json}, open(os.path.join(d, "state.json"), "w"))
        self.agents_list.append(a)
        return a

    def limited(self, name, resets="resets 8am", updated=None):
        """Сессия, вставшая на лимите: updatedAt — вечер до сброса."""
        upd = updated or at(2026, 10, 18, 22, 0)
        iso = datetime.fromtimestamp(upd, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return self.agent(name, "blocked", needs=f"rate limited · {resets}", updatedAt=iso)

    def keep(self, t, agents=None):
        self.now(t)
        AW.keep_awake(self.agents_list if agents is None else agents, [], DOMS, t)
        st = P.read_json(P.path("awake.json"), {})
        pid = st.get("pid")
        if pid and pid not in self.seen:
            self.seen.add(pid)
            for _ in range(100):   # поддельный caffeinate пишет журнал при старте
                if len(self.starts()) >= len(self.seen):
                    break
                time.sleep(0.05)
        return st

    def starts(self):
        return open(self.caff_log).read().splitlines() if os.path.exists(self.caff_log) else []

    def alive(self, pid):
        return bool(pid) and self.comm(pid) == "caffeinate"

    def sent(self):
        return open(self.notify_log, encoding="utf-8").read() if os.path.exists(self.notify_log) else ""

    def track(self, st):
        if st.get("pid"):
            SPAWNED.append(st["pid"])
        return st

    def task(self, direction, title="задача", **fields):
        os.makedirs(os.path.join(self.pantheon, "directions", direction, "tasks"), exist_ok=True)
        tid, _ = P.tasks_mod().task_new(self.pantheon, MON, direction, title, **fields)
        return tid

    def status_md(self, direction, text):
        os.makedirs(os.path.join(self.pantheon, "directions", direction), exist_ok=True)
        open(os.path.join(self.pantheon, "directions", direction, "STATUS.md"), "w").write(text)


def started(e, st):
    e.track(st)
    return st


# --- бодрость ------------------------------------------------------------------------

def test_hold_working_once_and_release():
    e = Env()
    e.agent("hermes-site", "working")
    st = started(e, e.keep(MON))
    check(st.get("pid") and e.alive(st["pid"]), f"работает, а caffeinate нет: {st}")
    check(e.starts() == ["-i -t 420"], f"запуск не -i -t 420: {e.starts()}")
    check("hermes-site работает" in st.get("reason", ""), f"причина: {st.get('reason')}")
    st2 = e.keep(MON + 250)
    check(e.starts() == ["-i -t 420"] and st2["pid"] == st["pid"], "повторный проход плодит второй caffeinate")
    check(AW.status_line(MON + 250).startswith("Mac бодр: hermes-site работает"), AW.status_line(MON + 250))
    # до конца старого меньше 120 с — новый, старый убит
    time.sleep(0.1)
    st3 = started(e, e.keep(MON + 311))
    check(st3["pid"] != st["pid"] and len(e.starts()) == 2, f"не продлил: {st3} {e.starts()}")
    time.sleep(0.2)
    check(not e.alive(st["pid"]) and e.alive(st3["pid"]), "старый не убит или новый не жив")
    # работы нет — отпущен
    e.agents_list[0]["state"] = "done"
    json.dump({"state": "done"}, open(os.path.join(e.home, ".claude", "jobs", e.agents_list[0]["id"], "state.json"), "w"))
    st4 = e.keep(MON + 400)
    time.sleep(0.2)
    check(not e.alive(st3["pid"]) and not st4.get("pid"), f"не отпустил: {st4}")
    check(AW.status_line(MON + 400).startswith("Mac может спать"), AW.status_line(MON + 400))


def test_interval_from_schedule():
    e = Env()
    open(os.path.join(e.pantheon, "schedule.toml"), "w").write(
        'primary_host = "mac-a"\n[[job]]\nname = "watch"\ncommand = "pantheon watch"\nevery = 10\n')
    e.agent("hermes-site", "working")
    started(e, e.keep(MON))
    check(e.starts() == ["-i -t 720"], f"интервал 10 мин → 720 с: {e.starts()}")


def test_hold_reasons_and_idle():
    # фоновые субагенты у сессии, закончившей ход
    e = Env()
    e.agent("hermes-site", "done", inFlight={"tasks": 2, "queued": 0, "kinds": ["agent"]})
    st = started(e, e.keep(MON))
    check(st.get("pid") and "фоновые" in st["reason"], f"inFlight.tasks не держит: {st}")
    # все простаивают, ждут вас (не лимит), упали, остановлены; чужая сессия работает — не причина
    e = Env()
    e.agent("hermes-site", "done", inFlight={"tasks": 0, "queued": 0, "kinds": []})
    e.agent("athena-shop", "blocked", needs="waiting for your answer")
    e.agent("random-other", "working")
    e.agent("zeus", "stopped")
    st = e.keep(MON)
    check(not st.get("pid") and not e.starts(), f"простой держит Mac: {st}")
    # планировщик на паузе: работает, а не держим; уже держащий отпускается
    e = Env()
    e.agent("hermes-site", "working")
    st = started(e, e.keep(MON))
    open(os.path.join(e.state, "paused"), "w").close()
    st2 = e.keep(MON + 60)
    time.sleep(0.2)
    check(not st2.get("pid") and not e.alive(st["pid"]), f"пауза не отпустила: {st2}")
    check("пауз" in AW.status_line(MON + 60) or "спать" in AW.status_line(MON + 60), AW.status_line(MON + 60))
    # пауза по нагрузке всего (_all)
    e = Env()
    e.agent("hermes-site", "working")
    P.write_json(P.path("pauses", "_all.json"), {"reason": "limit"})
    check(not e.keep(MON).get("pid"), "пауза _all не отпустила")


def test_limit_wait_until_reset_plus_10():
    e = Env()
    e.limited("hermes-site")  # сброс 19.10 08:00, держим до 08:10
    st = started(e, e.keep(at(2026, 10, 19, 7, 0)))
    check(st.get("pid") and "лимита" in st["reason"], f"до сброса не держит: {st}")
    st = e.keep(at(2026, 10, 19, 8, 9))
    check(st.get("pid") and "08:10" in st["reason"], f"08:09 не держит: {st}")
    e2 = Env()
    e2.limited("hermes-site")
    st = e2.keep(at(2026, 10, 19, 8, 11))
    check(not st.get("pid"), f"после сброса + 10 мин держит: {st}")
    # дата в тексте: «resets Oct 20, 8am»
    li = AW.limit_info(e2.limited("athena-shop", "resets Oct 20, 8am"))
    check(li and li[0] == at(2026, 10, 20, 8, 0), f"resets Oct 20, 8am: {li}")
    li = AW.limit_info(e2.limited("a-b", "resets 10:30pm"))
    check(li and li[0] == at(2026, 10, 18, 22, 30), f"resets 10:30pm после 22:00: {li}")
    li = AW.limit_info(e2.limited("c-d", "resets 12am"))
    check(li and li[0] == at(2026, 10, 19, 0, 0), f"resets 12am: {li}")


def test_job_and_autostart_window():
    job = '[[job]]\nname = "clio-weekly"\ncommand = "claude -p --agent clio x"\nevery = 60\nclass = "light"\n'
    e = Env()
    e.schedule(job)
    P.save_job_state("clio-weekly", {"last_start": MON - 31 * 60})   # следующий через 29 мин
    st = started(e, e.keep(MON))
    check(st.get("pid") and "clio-weekly" in st["reason"], f"задача через 29 мин не держит: {st}")
    e = Env()
    e.schedule(job)
    P.save_job_state("clio-weekly", {"last_start": MON - 29 * 60})   # через 31 мин
    check(not e.keep(MON).get("pid"), "задача через 31 мин держит")
    # лёгкая pantheon-задача каждые 5 мин — не причина
    e = Env()
    e.schedule('[[job]]\nname = "commit"\ncommand = "pantheon commit"\nevery = 5\nclass = "light"\n')
    P.save_job_state("commit", {"last_start": MON - 290})
    check(not e.keep(MON).get("pid"), "лёгкая задача держит Mac")
    # тяжёлая задача на паузе — нет
    e = Env()
    e.schedule('[[job]]\nname = "hv"\ncommand = "pantheon usage 7"\nevery = 60\nclass = "heavy"\n')
    P.save_job_state("hv", {"last_start": MON - 3500, "paused": True})
    check(not e.keep(MON).get("pid"), "задача на паузе держит")
    # самозапуск
    e = Env()
    P.write_json(P.path("autostart.json"), {"hermes-site": {"next": MON + 29 * 60}})
    st = started(e, e.keep(MON))
    check(st.get("pid") and "самозапуск" in st["reason"], f"самозапуск через 29 мин не держит: {st}")
    e = Env()
    P.write_json(P.path("autostart.json"), {"hermes-site": {"next": MON + 31 * 60}})
    check(not e.keep(MON).get("pid"), "самозапуск через 31 мин держит")


def test_battery():
    e = Env(ac=False, batt=31)
    e.agent("hermes-site", "working")
    st = started(e, e.keep(MON))
    check(st.get("pid"), f"батарея 31 % не держит: {st}")
    check("Пантеон" not in e.sent() and not e.sent(), f"уведомление при 31 %: {e.sent()}")
    os.environ["PANTHEON_FAKE_BATT"] = "30"
    st2 = e.keep(MON + 60)
    time.sleep(0.2)
    check(not st2.get("pid") and not e.alive(st["pid"]), f"батарея 30 % не отпустила: {st2}")
    check(e.sent().count("подключите зарядку") == 1, f"уведомление не одно: {e.sent()!r}")
    e.keep(MON + 360)
    e.keep(MON + 660)
    check(e.sent().count("подключите зарядку") == 1, f"уведомление повторилось: {e.sent()!r}")
    check("подключите зарядку" in AW.status_line(MON + 660), AW.status_line(MON + 660))
    # зарядили — держит, а на следующем разряде уведомление снова
    os.environ["PANTHEON_FAKE_AC"] = "1"
    started(e, e.keep(MON + 700))
    os.environ["PANTHEON_FAKE_AC"] = "0"
    os.environ["PANTHEON_FAKE_BATT"] = "25"
    e.keep(MON + 800)
    check(e.sent().count("подключите зарядку") == 2, f"новый разряд без уведомления: {e.sent()!r}")
    # на батарее без работы уведомления нет
    e = Env(ac=False, batt=10)
    e.agent("hermes-site", "done")
    e.keep(MON)
    check(not e.sent(), "уведомление без причины держать")


def test_foreign_pid_not_killed():
    e = Env()
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    SPAWNED.append(other.pid)
    e.foreign.add(other.pid)
    P.write_json(P.path("awake.json"), {"pid": other.pid, "until": MON + 10000, "reason": "чужое"})
    e.keep(MON)   # работы нет: отпускаем «свой» pid, а это не caffeinate
    check(other.poll() is None, "убит чужой процесс при отпускании")
    e.agent("hermes-site", "working")
    st = started(e, e.keep(MON + 10))
    check(other.poll() is None, "убит чужой процесс при продлении")
    check(st.get("pid") and st["pid"] != other.pid and len(e.starts()) == 1, f"чужой pid принят за свой: {st}")
    check(P.read_json(P.path("awake.json"), {}).get("pid") == st["pid"], "pid не записан")


# --- напоминание о перезагрузке -----------------------------------------------------

def test_reboot_reminder():
    e = Env()
    os.environ["PANTHEON_FAKE_SWAP"] = "2.4"
    # загрузка после прошлой пятницы (16.10 00:00) — молчит
    os.environ["PANTHEON_FAKE_BOOT"] = str(at(2026, 10, 17, 8, 0))
    e.now(FRI)
    check(AW.reboot_reminder([], FRI) == 0 and not e.sent(), "перезагрузка была на неделе, а напомнил")
    check(not os.path.exists(P.path("reboot-reminder.json")), "метка без напоминания")
    # загрузка до — карточка и уведомление
    boot = at(2026, 10, 8, 8, 0)
    os.environ["PANTHEON_FAKE_BOOT"] = str(boot)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        AW.reboot_reminder([], FRI)
    heads = [h for _, h, _ in P.tasks_mod().load_tasks(e.pantheon).values()]
    cards = [h for h in heads if h.get("title") == "Перезагрузить Mac"]
    check(len(cards) == 1, f"карточек не одна: {len(cards)}; {buf.getvalue()}")
    if cards:
        c = cards[0]
        check(c.get("owner") == "zeus" and c.get("status") == "waiting" and c.get("waiting_on") == "human"
              and c.get("direction") == "inbox", f"поля карточки: {c}")
    msg = e.sent()
    check("Перезагрузите Mac: аптайм 15 суток, своп 2.4 ГБ" in msg and "claude respawn --all" in msg, f"текст: {msg!r}")
    # второй вызов в ту же неделю и в воскресенье — без второй карточки
    AW.reboot_reminder([], FRI + 3600)
    AW.reboot_reminder(["--now"], FRI + 2 * 86400)
    n = sum(1 for _, h, _ in P.tasks_mod().load_tasks(e.pantheon).values() if h.get("title") == "Перезагрузить Mac")
    check(n == 1 and e.sent().count("Перезагрузите Mac") == 1, f"вторая карточка или уведомление: {n}")
    # не пятница и пятница до 09:30 — тишина (без --now)
    e2 = Env()
    os.environ["PANTHEON_FAKE_BOOT"] = str(boot)
    AW.reboot_reminder([], MON)
    AW.reboot_reminder([], at(2026, 10, 23, 9, 29))
    check(not e2.sent() and not P.tasks_mod().load_tasks(e2.pantheon), "напомнил не в пятницу или раньше 09:30")
    # следующая неделя — новая карточка
    e3 = Env()
    os.environ["PANTHEON_FAKE_BOOT"] = str(boot)
    AW.reboot_reminder([], FRI)
    AW.reboot_reminder([], FRI + 7 * 86400)
    n = sum(1 for _, h, _ in P.tasks_mod().load_tasks(e3.pantheon).values() if h.get("title") == "Перезагрузить Mac")
    check(n == 2, f"через неделю карточка не заведена: {n}")
    os.environ.pop("PANTHEON_FAKE_BOOT", None)
    os.environ.pop("PANTHEON_FAKE_SWAP", None)


def test_reboot_cli_registered():
    check("reboot-reminder" in P.TICK_SUBCOMMANDS, "reboot-reminder не разрешён задачам тика")
    check(P.parse_command("pantheon reboot-reminder") is not None, "команда задачи не разбирается")
    check("reboot-reminder" in (P.__doc__ or ""), "нет в справке")


# --- подъём после лимита -----------------------------------------------------------------

def test_limit_resume():
    e = Env()
    a = e.limited("hermes-site")   # сброс 19.10 08:00
    LIM = at(2026, 10, 19, 8, 0)
    AW.limit_resume(e.agents_list, [], DOMS, LIM + 9 * 60)
    check(not e.calls and not e.gate_calls, f"до 08:10 тронул: {e.calls}")
    e.now(LIM + 11 * 60)
    AW.limit_resume(e.agents_list, [], DOMS, LIM + 11 * 60)
    check(e.calls == [("hermes-site", "[Пантеон: лимит сброшен] продолжай с файла состояния", "limit")],
          f"подъём: {e.calls}")
    check(e.gate_calls == ["respawn"], f"запор respawn: {e.gate_calls}")
    check(AW.RESUMED == ["hermes-site"], "проход не запомнил подъём")
    AW.limit_resume(e.agents_list, [], DOMS, LIM + 16 * 60)
    AW.limit_resume(e.agents_list, [], DOMS, LIM + 3600)
    check(len(e.calls) == 1, f"второй подъём на тот же сброс: {len(e.calls)}")
    # новый сброс (та же сессия снова встала) — новый подъём
    a["id"] = a["id"]
    e.limited("hermes-site", "resets 8am", updated=at(2026, 10, 19, 21, 0))
    e.agents_list[:] = [x for x in e.agents_list if x is not a]
    e.agents_list[0]["id"], e.agents_list[0]["sessionId"] = a["id"], a["sessionId"]
    json.dump({"state": "blocked", "needs": "rate limited · resets 8am",
               "updatedAt": datetime.fromtimestamp(at(2026, 10, 19, 21, 0), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")},
              open(os.path.join(e.home, ".claude", "jobs", a["id"], "state.json"), "w"))
    AW.limit_resume(e.agents_list, [], DOMS, at(2026, 10, 20, 8, 15))
    check(len(e.calls) == 2, f"новый сброс не поднят: {len(e.calls)}")


def test_limit_resume_gate_refused_then_retry():
    e = Env()
    e.limited("hermes-site")
    LIM = at(2026, 10, 19, 8, 0)
    e.gate_ok = (False, "темп недели выше нормы")
    AW.limit_resume(e.agents_list, [], DOMS, LIM + 11 * 60)
    AW.limit_resume(e.agents_list, [], DOMS, LIM + 16 * 60)
    check(not e.calls and e.gate_calls == ["respawn", "respawn"], f"запор отказал, а поднял: {e.calls} {e.gate_calls}")
    log = open(os.path.join(e.state, "logs", "start.log")).read()
    check("limit-gate" in log and "темп недели" in log, f"отказ не в журнале: {log!r}")
    e.gate_ok = (True, None)
    AW.limit_resume(e.agents_list, [], DOMS, LIM + 21 * 60)
    check(len(e.calls) == 1, f"после снятия запора не поднял: {e.calls}")


def alerts_text(e):
    f = os.path.join(e.pantheon, "alerts.md")
    return open(f, encoding="utf-8").read() if os.path.exists(f) else ""


def test_limit_resume_no_window_no_alert_no_try():
    # код «нет окна» — одна тревога от window_missing, а не вторая «не поднялась»; попытка не засчитана (metis-0132)
    e = Env()
    e.limited("hermes-site")
    LIM = at(2026, 10, 19, 8, 0)
    calls = []

    def nw(name, a, text, origin, recheck=None):
        calls.append(name)
        return P.NO_WINDOW, None
    P.resume_session = nw
    for i in range(AW.LIMIT_TRIES + 3):
        AW.limit_resume(e.agents_list, [], DOMS, LIM + (11 + 6 * i) * 60)
    check("не поднялась" not in alerts_text(e), f"вторая тревога при «нет окна»: {alerts_text(e)!r}")
    check(len(calls) == AW.LIMIT_TRIES + 3, f"попытки засчитаны и оборвались: {len(calls)}")
    mk = AW.read_marks().get("limit", {})
    check(all(m.get("tries") == 0 and m.get("done") is False for m in mk.values()), f"метки: {mk}")
    # окно появилось — подъём проходит
    P.resume_session = e.resume
    AW.limit_resume(e.agents_list, [], DOMS, LIM + 3 * 3600)
    check(len(e.calls) == 1, f"после появления окна не поднял: {e.calls}")
    # другой код по-прежнему тревожит и засчитывается
    e2 = Env()
    e2.limited("hermes-site")
    P.resume_session = lambda name, a, text, origin, recheck=None: (1, None)
    AW.limit_resume(e2.agents_list, [], DOMS, LIM + 11 * 60)
    check("не поднялась (код 1, попытка 1 из" in alerts_text(e2), f"код 1 без тревоги: {alerts_text(e2)!r}")


def test_limit_resume_no_night_module():
    e = Env()
    e.limited("hermes-site")
    AW._NIGHT = AW._UNSET
    real = AW.P.LIB
    AW.P.LIB = os.path.join(e.tmp, "nolib")   # night.py там нет
    try:
        ok, why = AW.gate("respawn", MON)
        check(not ok and "не найден" in why, f"без night.py запор не отказал: {ok} {why}")
        AW.limit_resume(e.agents_list, [], DOMS, at(2026, 10, 19, 9, 0))
        check(not e.calls, "поднял без ночного модуля")
    finally:
        AW.P.LIB = real
    AW._NIGHT = types.SimpleNamespace(gate=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("сбой")))
    ok, why = AW.gate("wake", MON)
    check(not ok and "запор упал" in why, f"исключение запора: {ok} {why}")


def test_limit_skips_stopped_and_paused():
    e = Env()
    e.limited("hermes-site")
    os.makedirs(os.path.join(e.state, "stopped"))
    open(os.path.join(e.state, "stopped", "hermes-site"), "w").close()
    AW.limit_resume(e.agents_list, [], DOMS, at(2026, 10, 19, 9, 0))
    check(not e.calls, "поднял остановленную вами")


def test_pantheon_wake_sees_limited():
    e = Env()
    e.direction_tasks = e.task("hermes-site")  # открытая задача направления
    a = e.limited("hermes-site")
    LIM = at(2026, 10, 19, 8, 0)
    run = lambda t: (e.now(t), io.StringIO())

    def wake(t):
        e.now(t)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            P._wake(False)
        return buf.getvalue()
    out = wake(LIM - 600)
    check("поднимаю" not in out and not e.calls, f"до сброса wake поднял: {out!r}")
    out = wake(LIM + 60)
    check("поднимаю: hermes-site" in out and len(e.calls) == 1, f"wake не видит сессию на лимите: {out!r} {e.calls}")
    # работающую сессию wake по-прежнему не трогает
    e2 = Env()
    e2.task("hermes-site")
    e2.agent("hermes-site", "blocked", needs="waiting for your answer")
    e2.now(LIM + 60)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        P._wake(False)
    check(not e2.calls, f"wake поднял обычную ждущую: {e2.calls}")


# --- будильник ждущих --------------------------------------------------------------------

def test_wake_waiting():
    e = Env()
    e.agent("hermes-site", "blocked", needs="waiting for your answer")
    tid = e.task("hermes-site")
    AW.wake_waiting(e.agents_list, [], DOMS, MON)
    check(e.calls == [("hermes-site", f"[Пантеон: есть задача без блокера] возьми {tid} из очереди", "wake-waiting")],
          f"будильник: {e.calls}")
    check(e.gate_calls == ["wake"], f"запор wake: {e.gate_calls}")
    AW.wake_waiting(e.agents_list, [], DOMS, MON + 3599)
    check(len(e.calls) == 1, "будит чаще раза в час")
    AW.wake_waiting(e.agents_list, [], DOMS, MON + 3601)
    check(len(e.calls) == 2, "через час не разбудил снова")
    # работающую и закончившую не будим; чужое направление без задач — тоже
    e = Env()
    e.agent("hermes-site", "working")
    e.agent("athena-shop", "done")
    e.task("hermes-site")
    e.task("athena-shop")
    AW.wake_waiting(e.agents_list, [], DOMS, MON)
    check(not e.calls, f"разбудил не ждущую: {e.calls}")


def test_wake_waiting_no_window_no_alert():
    e = Env()
    e.agent("hermes-site", "blocked", needs="waiting for your answer")
    e.task("hermes-site")
    calls = []

    def nw(name, a, text, origin, recheck=None):
        calls.append(name)
        return P.NO_WINDOW, None
    P.resume_session = nw
    AW.wake_waiting(e.agents_list, [], DOMS, MON)
    check(len(calls) == 1 and "не поднялась" not in alerts_text(e), f"вторая тревога: {alerts_text(e)!r}")
    AW.wake_waiting(e.agents_list, [], DOMS, MON + 600)
    check(len(calls) == 1, "отметка раз в час не осталась")
    P.resume_session = lambda name, a, text, origin, recheck=None: (1, None)
    AW.wake_waiting(e.agents_list, [], DOMS, MON + 3601)
    check("будильник ждущих: hermes-site не поднялась (код 1)" in alerts_text(e), f"код 1 без тревоги: {alerts_text(e)!r}")


def test_pantheon_wake_fresh_sees_limited():
    # ветвь fresh_start в _wake: recheck обязан знать state, иначе сессия на лимите «уже работает» (metis-0132)
    e = Env()
    e.task("hermes-site")
    e.limited("hermes-site")
    LIM = at(2026, 10, 19, 8, 0)
    e.now(LIM + 60)
    got = []

    def fs(name, a, text, origin, recheck=None):
        w = recheck() if recheck else None
        got.append(w)
        return 0 if not w else 1
    saved = (P.fresh_reason, P.state_files, P.fresh_start)
    P.fresh_reason = lambda a, t=None: "контекст большой"
    P.state_files = lambda n: []
    P.fresh_start = fs
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            P._wake(False)
    finally:
        P.fresh_reason, P.state_files, P.fresh_start = saved
    check(got == [None], f"recheck свежего старта на лимите: {got} {buf.getvalue()!r}")
    check("свежей сессией" in buf.getvalue(), f"нет свежего старта в выводе: {buf.getvalue()!r}")


def test_wake_waiting_blockers():
    # все задачи с «владелец: id» в STATUS.md — молчит
    e = Env()
    e.agent("hermes-site", "blocked", needs="x")
    t1, t2 = e.task("hermes-site", "один"), e.task("hermes-site", "два")
    e.status_md("hermes-site", f"# Статус\n\n- владелец: {t1}, {t2} — ждут ответа\n")
    AW.wake_waiting(e.agents_list, [], DOMS, MON)
    check(not e.calls and not e.gate_calls, f"разбудил при блокере владельца: {e.calls}")
    # одна из двух свободна — берётся она
    e.status_md("hermes-site", f"# Статус\n\n- владелец: {t1}\n")
    AW.wake_waiting(e.agents_list, [], DOMS, MON)
    check(len(e.calls) == 1 and t2 in e.calls[0][1] and t1 not in e.calls[0][1], f"не та задача: {e.calls}")
    # depends_on на незакрытую — не берётся; на закрытую — берётся
    e = Env()
    e.agent("hermes-site", "blocked", needs="x")
    base = e.task("hermes-site", "основа")
    dep = e.task("hermes-site", "зависимая", depends_on=[base])
    free = AW.free_task("hermes-site", MON)
    check(free == base, f"первой должна быть основа: {free}")
    e2 = Env()
    e2.agent("hermes-site", "blocked", needs="x")
    open_dep = e2.task("hermes-site", "первая", status="doing")
    e2.task("hermes-site", "вторая", depends_on=[open_dep])
    AW.wake_waiting(e2.agents_list, [], DOMS, MON)
    check(not e2.calls, f"взяла задачу с depends_on на незакрытую: {e2.calls}")
    e3 = Env()
    e3.agent("hermes-site", "blocked", needs="x")
    done = e3.task("hermes-site", "готовая", status="done")
    nxt = e3.task("hermes-site", "следом", depends_on=[done])
    AW.wake_waiting(e3.agents_list, [], DOMS, MON)
    check(len(e3.calls) == 1 and nxt in e3.calls[0][1], f"зависимость закрыта, а не взяла: {e3.calls}")
    # waiting_on на человека — не берётся
    e4 = Env()
    e4.agent("hermes-site", "blocked", needs="x")
    e4.task("hermes-site", "ждёт", status="todo", waiting_on="athena-0001")
    AW.wake_waiting(e4.agents_list, [], DOMS, MON)
    check(not e4.calls, f"взяла задачу с waiting_on: {e4.calls}")


def test_wake_waiting_gate_refused():
    for why in ("старый снимок недели", "неделя выше порога", "темп днём выше нормы"):
        e = Env()
        e.agent("hermes-site", "blocked", needs="x")
        e.task("hermes-site")
        e.gate_ok = (False, why)
        AW.wake_waiting(e.agents_list, [], DOMS, MON)
        check(not e.calls and e.gate_calls == ["wake"], f"запор «{why}» отказал, а разбудил: {e.calls}")
    # отказ не сжигает «раз в час»: после снятия запора будит сразу
    e.gate_ok = (True, None)
    AW.wake_waiting(e.agents_list, [], DOMS, MON + 60)
    check(len(e.calls) == 1, "после снятия запора не разбудил")


def test_wake_waiting_skips_limited_and_stopped():
    e = Env()
    e.limited("hermes-site")
    e.task("hermes-site")
    AW.wake_waiting(e.agents_list, [], DOMS, at(2026, 10, 19, 9, 0))
    check(not e.calls, "ждущую на лимите разбудил как ждущую")
    e = Env()
    e.agent("hermes-site", "blocked", needs="x")
    e.task("hermes-site")
    os.makedirs(os.path.join(e.state, "stopped"))
    open(os.path.join(e.state, "stopped", "hermes-site"), "w").close()
    AW.wake_waiting(e.agents_list, [], DOMS, MON)
    check(not e.calls, "разбудил остановленную вами")


# --- крючки в дежурном -------------------------------------------------------------------

def test_watch_hooks_wired():
    src = open(os.path.join(ROOT, "lib", "watch.py"), encoding="utf-8").read()
    for name in ("бодрость", "подъём после лимита", "будильник ждущих"):
        check(f'("{name}"' in src, f"в _watch() нет проверки «{name}»")
    check("awake_mod().status_line()" in open(os.path.join(ROOT, "lib", "pantheon.py"), encoding="utf-8").read(),
          "в status() нет строки Mac бодр")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            FAILS.append(f"{fn.__name__}: {type(ex).__name__}: {ex}")
            print("ОШИБКА:", fn.__name__, type(ex).__name__, ex)
    print(f"тестов: {len(tests)}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
