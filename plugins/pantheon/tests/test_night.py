#!/usr/bin/env python3
"""Синтетические тесты темпа недельного лимита и ночного цикла (lib/night.py; metis-0127, 0128, 0129).

Запуск: python3 -I plugins/pantheon/tests/test_night.py  (код выхода 0 — все прошли)
pantheon.py загружается в этом же процессе; каждый тест — свои временные HOME, PANTHEON и STATE (константы модуля
подменяются), снимок строки статуса пишется в HOME/.local/state/claude-statusline. Время — местное: дата вечера
VEVENING, часы «ЧЧ:ММ» считаются от неё.
"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402
import tempfile
import atexit as _atexit
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="night-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)
import importlib.util
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
WEEK = 7 * 86400
EVENING = date(2026, 10, 15)  # четверг
FAILS = []

for k in ("PANTHEON_FAKE_LIMIT", "PANTHEON_DRYRUN", "PANTHEON_NO_NOTIFY"):
    os.environ.pop(k, None)
# питание подменено (metis-0284): проверка 21:30–22:00 не читает настоящий pmset; test_power_0284 подставляет свой
os.environ.update({"PANTHEON_FAKE_AC": "1", "PANTHEON_FAKE_BATT": "100"})
os.environ.update({"PANTHEON_HOST": "mac-a", "PANTHEON_FAKE_IDLE": "0", "HOME": os.path.join(_ROOT, "home0"),
                   "PANTHEON_HOME": os.path.join(_ROOT, "home0", "ai", "pantheon"),
                   "PANTHEON_STATE": os.path.join(_ROOT, "state0"), "PANTHEON_SCHEDULE_DEFAULTS": os.devnull})
_spec = importlib.util.spec_from_file_location("pantheon_night_test", os.path.join(LIB, "pantheon.py"))
P = importlib.util.module_from_spec(_spec)
sys.modules["pantheon_night_test"] = P
_spec.loader.exec_module(P)
N = P.night_mod()
PROBES = []  # вызовы пробного запроса (metis-0459): настоящий claude тесты не зовут никогда


_REAL_PROBE_RUN = N.probe_run


def _no_probe():
    PROBES.append(None)
    return 127, ""


# Настоящее событие `claude -p ok --model haiku --no-session-persistence --output-format stream-json --verbose`
# (живой запуск 02.11, metis-0459), строки потока как отдаёт claude, ничего не дописано от руки.
REAL_EVENT = (
    '{"type":"system","subtype":"hook_response","hook_name":"SessionStart:startup"}\n'
    '{"type":"rate_limit_event","rate_limit_info":{"status":"allowed","resetsAt":1793635800,"rateLimitType":"five_hour",'
    '"overageStatus":"rejected","overageDisabledReason":"org_level_disabled","isUsingOverage":false,"unifiedWindows":'
    '{"five_hour":{"utilization":0.1,"resetsAt":1793635800,"status":"allowed"},"seven_day":{"utilization":0.35,'
    '"resetsAt":1793941200,"status":"allowed"}}},"uuid":"b7817d97-7946-40f8-acdd-299e8b2e3a7d",'
    '"session_id":"8616cc57-76e0-4705-ae79-734af8a0cdd0"}\n'
    '{"type":"result","subtype":"success","is_error":false}\n')


N.probe_run = _no_probe


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("НЕ ПРОШЛО:", what)


def hm(s, d=EVENING):
    """Время «ЧЧ:ММ» вечера d: часы раньше 12:00 — уже следующие сутки."""
    h, m = map(int, s.split(":"))
    dt = datetime.combine(d, datetime.min.time()).replace(hour=h, minute=m)
    if h < 12:
        dt += timedelta(days=1)
    return dt.timestamp()


def day(s="14:00", d=EVENING):
    h, m = map(int, s.split(":"))
    return datetime.combine(d, datetime.min.time()).replace(hour=h, minute=m).timestamp()


class Env:
    def __init__(self, sched='primary_host = "mac-a"\n'):
        self.tmp = tempfile.mkdtemp(prefix="night-test-")
        self.home = os.path.join(self.tmp, "home")
        self.pantheon = os.path.join(self.home, "ai", "pantheon")
        self.state = os.path.join(self.tmp, "state")
        self.sl = os.path.join(self.home, ".local", "state", "claude-statusline")
        for d in (self.pantheon, os.path.join(self.pantheon, "inbox", "tasks"), os.path.join(self.state, "owner-log"),
                  self.sl):
            os.makedirs(d, exist_ok=True)
        P.HOME, P.PANTHEON, P.STATE = self.home, self.pantheon, self.state
        P.LIMIT_SNAPSHOT = os.path.join(self.sl, "five-hour")
        P._TASKS = None
        self.notify = os.path.join(self.tmp, "notify.log")
        os.environ["PANTHEON_NOTIFY_LOG"] = self.notify
        os.environ.pop("PANTHEON_FAKE_LIMIT", None)
        open(os.path.join(self.pantheon, "schedule.toml"), "w").write(sched)
        self.resets = None  # общий сброс недели для снимков одной ночи

    def snap(self, t_obs, used, resets, five=10.0, seven=True):
        open(os.path.join(self.sl, "five-hour"), "w").write(f"{five:g} {t_obs + 3600:.0f} {t_obs:.0f}\n")
        if seven:
            open(os.path.join(self.sl, "seven-day"), "w").write(f"{used!r} {resets:.0f} {t_obs:.0f}\n")

    def week_usage(self, rows):
        with open(os.path.join(self.sl, "week-usage"), "a") as fh:
            for now_, resets, pct in rows:
                fh.write(f"{now_:.0f} {resets:.0f} {pct:g}\n")

    def at_line(self, t, over, resets=None):
        """Снимок в момент t с запасом over от линии; сброс по умолчанию — через 3 суток."""
        resets = resets or self.resets or t + 3 * 86400
        line = 100.0 * (t - (resets - WEEK)) / WEEK
        self.snap(t, line + over, resets)
        return line

    def watch(self, t):
        os.environ["PANTHEON_NOW"] = str(t)
        N.watch([], [], {}, t)

    def state_of(self, d=EVENING):
        return json.load(open(os.path.join(self.state, "night", d.isoformat() + ".json")))

    def sent(self):
        return open(self.notify, encoding="utf-8").read().splitlines() if os.path.exists(self.notify) else []

    def alerts(self):
        p = os.path.join(self.pantheon, "alerts.md")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""

    def cards(self):
        T = P.tasks_mod()
        return {tid: h for tid, (_, h, _) in T.load_tasks(self.pantheon).items() if h.get("direction") == "inbox"}


def zone(e, over, used=None, t=None):
    t = t or day()
    if used is None:
        e.at_line(t, over)
    else:
        resets = t + 3 * 86400
        e.snap(t, used, resets)
    return N.measure(t)["zone"]


def test_zones():
    e = Env()
    for over, want in ((2, "green"), (2.1, "yellow"), (5, "yellow"), (5.1, "red"), (-3, "green")):
        check(zone(e, over) == want, f"запас {over:+} → {want}, а вышло {zone(e, over)}")
    # неделя 85 % — красная при любом запасе: линия ~88 %, запас −3
    t = day()
    resets = t + 0.12 * WEEK
    e.snap(t, 85.0, resets)
    m = N.measure(t)
    check(m["zone"] == "red" and m["over"] < 0, f"85 % при запасе {m['over']} — не красная: {m['zone']}")
    e.snap(t, 84.9, resets)
    check(N.measure(t)["zone"] == "green", "84,9 % при запасе −3 — не зелёная")


def test_snapshot_age():
    e = Env()
    t = day()
    for age, known in ((29, True), (31, False)):
        e.at_line(t - age * 60, 0, resets=t + 3 * 86400)
        m = N.measure(t)
        check(m["known"] is known, f"снимок {age} мин: known={m['known']}")
    m = N.measure(t)
    check(m["why"] == "лимит неизвестен (31 мин)" and not m["stale"], f"31 мин: {m['why']} stale={m['stale']}")
    ok, why = N.gate("autostart", t, heavy=0)
    check(not ok and why.startswith("лимит неизвестен"), f"31 мин — gate пустил: {why}")
    e.at_line(t - 181 * 60, 0, resets=t + 3 * 86400)
    m = N.measure(t)
    check(not m["known"] and m["stale"], "181 мин — не «старый»")
    e.watch(t)
    check("снимок недельного лимита не обновлялся 181 мин" in e.alerts(), f"181 мин — нет строки в тревогах: {e.alerts()}")
    e.watch(t + 300)
    check(e.alerts().count("снимок недельного лимита") == 1, "строка о старом снимке повторилась в тот же день")
    # 120 мин — неизвестен, но строки в тревогах нет
    e2 = Env()
    e2.at_line(t - 120 * 60, 0, resets=t + 3 * 86400)
    e2.watch(t)
    check("снимок недельного лимита" not in e2.alerts(), "120 мин — строка в тревогах, а порог 180")
    # нет снимка вовсе
    Env()
    m = N.measure(t)
    check(not m["known"] and m["stale"] and "снимка нет" in m["why"], f"без снимка: {m}")
    # seven-day нет — неделя из последней строки week-usage
    e4 = Env()
    resets = t + 3 * 86400
    e4.snap(t - 60, 0, resets, seven=False)
    e4.week_usage([(t - 7200, resets, 30), (t - 120, resets, 33)])
    m = N.measure(t)
    check(m["known"] and m["used"] == 33, f"week-usage не прочитан: {m}")
    # сброс недели в прошлом — новая неделя с неизвестным расходом, закрыто
    e5 = Env()
    e5.snap(t - 60, 40, t - 10)
    m = N.measure(t)
    check(not m["known"] and "новая неделя" in m["why"], f"сброс в прошлом: {m}")


def test_week_monotonic_0243():
    """Неделя не убывает в пределах окна сброса: простаивающее окно пишет старый pct — берём максимум."""
    t = day()
    e = Env()
    resets = t + 3 * 86400
    e.snap(t - 60, 38, resets)  # seven-day 38
    e.week_usage([(t - 300, resets, 40), (t - 200, resets, 38), (t - 100, resets + 600, 40)])
    s = N.snapshot()
    check(s["week"] == (40, resets, t - 60), f"максимум не взят или сброс/время не от свежей строки: {s}")
    check(N.measure(t)["used"] == 40, f"used не 40: {N.measure(t)}")
    # другое окно сброса (разница > 1 ч) в максимум не входит
    e2 = Env()
    e2.snap(t - 60, 5, resets + 7 * 86400)
    e2.week_usage([(t - 300, resets, 90)])
    check(N.snapshot()["week"][0] == 5, f"чужое окно сброса попало в максимум: {N.snapshot()}")
    # spent не уменьшается на скачке назад в том же окне; в новом окне считается по-старому
    m = {"known": True, "used": 38.0, "resets": resets}
    st = {"start_pct": 30.0, "last_used": 41.0, "resets_at": resets, "spent": 0.0}
    check(N.spent(st, m) == 11.0, f"spent упал на скачке: {N.spent(st, m)}")
    m2 = {"known": True, "used": 2.0, "resets": resets + 7 * 86400}
    check(N.spent(st, m2) == 13.0, f"спент при сбросе недели: {N.spent(st, m2)}")


def reset_mark(t, role=""):
    """pantheon limit reset-mark в момент t; role — PANTHEON_ROLE окна ("" — терминал владельца). (код, stdout, stderr)."""
    saved = {k: os.environ.get(k) for k in ("PANTHEON_NOW", "PANTHEON_ROLE")}
    os.environ["PANTHEON_NOW"] = str(t)
    os.environ.pop("PANTHEON_ROLE", None)
    if role:
        os.environ["PANTHEON_ROLE"] = role
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = N.limit_main(["reset-mark"])
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return rc, out.getvalue(), err.getvalue()


def early_reset_env(t, resets):
    """Файлы как у строки статуса 12.11: week-usage растёт до 99 % (пишется только рост), seven-day — один файл,
    последний замер до сброса 99 %."""
    e = Env()
    e.week_usage([(t - 86400 + 2000 * k, resets, 60 + k) for k in range(40)])  # 60..99 % за прошлые сутки
    e.snap(t - 3000, 99, resets)
    return e


def test_week_reset_mark_1067():
    """Досрочный сброс с тем же resets_at (владелец 12.11) — по отметке pantheon limit reset-mark: замеры до неё не
    учитываются. Без отметки неделя — максимум, как раньше; по падению pct сброс не угадывается."""
    t = day()
    resets = t + 22 * 3600
    # без отметки: seven-day 6 % после строк до 99 % — неделя 99 (падение — не сброс, metis-0243)
    e = early_reset_env(t, resets)
    e.snap(t - 60, 6, resets)
    check(N.snapshot()["week"] == (99, resets, t - 60), f"без отметки неделя не максимум: {N.snapshot()}")
    # отметка из терминала владельца: файл в STATE, окно — resets_at свежего замера
    e = early_reset_env(t, resets)
    rc, out, err = reset_mark(t - 1800)
    mark = json.load(open(os.path.join(e.state, "limit", "reset-mark.json")))
    check(rc == 0 and mark["at"] == t - 1800 and mark["resets_at"] == resets and "Отметка" in out,
          f"отметка не записана: код {rc}, {mark}, {out!r} {err!r}")
    # замеров после отметки ещё нет — неделя неизвестна, а не 99
    check(N.snapshot()["week"] is None, f"до замера после отметки неделя известна: {N.snapshot()}")
    check(not N.measure(t)["known"], f"до замера после отметки measure решает: {N.measure(t)}")
    # строка статуса перезаписала seven-day: 6 % — неделя 6, зона зелёная
    e.snap(t - 60, 6, resets)
    check(N.snapshot()["week"] == (6, resets, t - 60), f"отметка не обнулила базу: {N.snapshot()}")
    m = N.measure(t)
    check(m["known"] and m["used"] == 6 and m["zone"] == "green", f"measure после отметки: {m}")
    mark_p = os.path.join(e.state, "limit", "reset-mark.json")
    check(json.load(open(mark_p)).get("max") == 6, f"максимум после отметки не записан: {open(mark_p).read()}")
    # неделя после отметки не убывает (metis-0243): seven-day 70, затем простаивающее окно перезаписало его старым 6,
    # а week-usage строка статуса не пополняет (пишет только pct выше 99) — неделя 70 по max отметки
    e.snap(t - 30, 70, resets)
    check(N.snapshot()["week"][0] == 70, f"замер 70 после отметки не взят: {N.snapshot()}")
    e.snap(t - 20, 6, resets)
    check(N.snapshot()["week"] == (70, resets, t - 20), f"старый 6 опустил неделю после отметки: {N.snapshot()}")
    m = N.measure(t)
    check(m["used"] == 70, f"measure после 70 → 6: {m}")
    check(json.load(open(mark_p))["max"] == 70, f"max отметки не 70: {open(mark_p).read()}")
    # STATE не пишется (окно роли): snapshot не падает, неделя — по замеру и прежнему max
    os.chmod(os.path.dirname(mark_p), 0o500)
    try:
        e.snap(t - 10, 75, resets)
        check(N.snapshot()["week"][0] == 75, f"без записи в STATE: {N.snapshot()}")
    finally:
        os.chmod(os.path.dirname(mark_p), 0o700)
    check(json.load(open(mark_p))["max"] == 70, "max записан в каталог без права записи")
    # новая отметка того же окна — максимум заново
    rc, _, _ = reset_mark(t - 5)
    e.snap(t, 6, resets)
    check(rc == 0 and N.snapshot()["week"][0] == 6, f"новая отметка не сбросила максимум: {N.snapshot()}")
    # max отметки без замеров после неё — неделя по max, а не неизвестна и не 99
    e = early_reset_env(t, resets)
    P.write_json(os.path.join(e.state, "limit", "reset-mark.json"), {"at": t - 60, "resets_at": resets, "max": 40})
    check(N.snapshot()["week"][0] == 40, f"max отметки без замеров после неё: {N.snapshot()}")
    # отметка того же окна с допуском 1 ч действует, другого окна (новый resets_at) — нет
    for shift, want in ((1800, 6), (3 * 3600, 99)):
        e = early_reset_env(t, resets)
        P.write_json(os.path.join(e.state, "limit", "reset-mark.json"), {"at": t - 1800, "resets_at": resets + shift})
        e.snap(t - 60, 6, resets)
        check(N.snapshot()["week"][0] == want, f"отметка окна {resets + shift}: неделя {N.snapshot()}, ждали {want}")
    # битая отметка не действует: не JSON, время не число при верном окне
    for body in ("{", json.dumps({"at": "x", "resets_at": resets}), json.dumps({"resets_at": resets})):
        e = early_reset_env(t, resets)
        os.makedirs(os.path.join(e.state, "limit"))
        open(os.path.join(e.state, "limit", "reset-mark.json"), "w").write(body)
        e.snap(t - 60, 6, resets)
        check((N.snapshot()["week"] or (None,))[0] == 99, f"битая отметка {body!r} подействовала: {N.snapshot()}")
    # гонка процессов: другой проход успел записать больший max — меньший его не опускает; отметку сменили (новый
    # reset-mark) — max старой отметки в новую не пишется
    e = early_reset_env(t, resets)
    mp = os.path.join(e.state, "limit", "reset-mark.json")
    P.write_json(mp, {"at": t - 1800, "resets_at": resets, "max": 50})
    N.mark_max_save((t - 1800, resets, 20.0), 30.0)
    check(P.read_json(mp)["max"] == 50, f"меньший max опустил записанный: {P.read_json(mp)}")
    P.write_json(mp, {"at": t - 60, "resets_at": resets})
    N.mark_max_save((t - 1800, resets, 50.0), 80.0)
    check("max" not in P.read_json(mp), f"max старой отметки записан в новую: {P.read_json(mp)}")
    # кривой max — как нет: отметка действует, максимум заново
    e = early_reset_env(t, resets)
    P.write_json(os.path.join(e.state, "limit", "reset-mark.json"), {"at": t - 1800, "resets_at": resets, "max": "x"})
    e.snap(t - 60, 6, resets)
    check(N.snapshot()["week"][0] == 6 and P.read_json(N.reset_mark_path())["max"] == 6,
          f"кривой max: {N.snapshot()} {P.read_json(N.reset_mark_path())}")


def test_week_idle_window_after_mark_1075():
    """Окно, простаивавшее с запроса до сброса, пишет seven-day со старым 99 и после отметки: max до отметки (pre)
    хранит сама отметка, замер, равный pre, в неделю не входит. Неделя после отметки по-прежнему не убывает."""
    t = day()
    resets = t + 22 * 3600
    e = early_reset_env(t, resets)
    rc, _, err = reset_mark(t - 1800)
    mark_p = os.path.join(e.state, "limit", "reset-mark.json")
    check(rc == 0 and P.read_json(mark_p).get("pre") == 99, f"pre не записан: {rc} {err!r} {P.read_json(mark_p)}")
    # простаивающее окно первым после отметки — неделя неизвестна, а не 99
    e.snap(t - 70, 99, resets)
    check(N.snapshot()["week"] is None, f"старый 99 первым после отметки: {N.snapshot()}")
    # 6, затем старый 99 простаивающего окна, затем 7 — неделя 7, max отметки 7
    e.snap(t - 60, 6, resets)
    check(N.snapshot()["week"][0] == 6, f"6 после отметки: {N.snapshot()}")
    e.snap(t - 50, 99, resets)
    check(N.snapshot()["week"] == (6, resets, t - 50), f"старый 99 прибил неделю: {N.snapshot()}")
    e.snap(t - 40, 98.6, resets)  # допуск 0,5: 98,6 — тот же старый 99
    check(N.snapshot()["week"][0] == 6, f"98,6 в допуске pre взят: {N.snapshot()}")
    e.snap(t - 30, 7, resets)
    check(N.snapshot()["week"] == (7, resets, t - 30) and N.measure(t)["used"] == 7,
          f"неделя после 6 → 99 → 7: {N.snapshot()} {N.measure(t)}")
    check(P.read_json(mark_p)["max"] == 7, f"max отметки: {P.read_json(mark_p)}")
    # защита 0243 цела: 70, затем 6 — 70
    e.snap(t - 20, 70, resets)
    check(N.snapshot()["week"][0] == 70, f"70 после отметки не взят: {N.snapshot()}")
    e.snap(t - 10, 6, resets)
    check(N.snapshot()["week"][0] == 70, f"70 → 6 после отметки: {N.snapshot()}")
    # выше pre — настоящий расход (старое окно больше pre не видело): берётся
    e.snap(t - 5, 100, resets)
    check(N.snapshot()["week"][0] == 100, f"замер выше pre не взят: {N.snapshot()}")
    # отметка без pre (до metis-1075) — как раньше: старый 99 входит в неделю
    e = early_reset_env(t, resets)
    P.write_json(os.path.join(e.state, "limit", "reset-mark.json"), {"at": t - 1800, "resets_at": resets})
    e.snap(t - 60, 99, resets)
    check(N.snapshot()["week"][0] == 99, f"отметка без pre: {N.snapshot()}")


def test_reset_mark_refusals_1067():
    """reset-mark только из терминала владельца: окно роли — отказ, код 2, файла нет; окна недели нет или оно
    сброшено — код 1, файла нет; лишние слова — код 2."""
    t = day()
    resets = t + 22 * 3600
    for role in ("dev", "hq"):
        e = early_reset_env(t, resets)
        rc, out, err = reset_mark(t, role)
        check(rc == 2 and "окно роли" in err.splitlines()[-1] and not os.path.exists(N.reset_mark_path()),
              f"окно роли {role}: код {rc}, {err!r}")
    Env()
    rc, _, err = reset_mark(t)
    check(rc == 1 and "не записана" in err and not os.path.exists(N.reset_mark_path()), f"без снимка: {rc} {err!r}")
    e = Env()
    e.snap(t - 60, 40, t - 10)
    rc, _, err = reset_mark(t)
    check(rc == 1 and not os.path.exists(N.reset_mark_path()), f"окно уже сброшено: {rc} {err!r}")
    check(N.limit_main([]) == 2 and N.limit_main(["reset-mark", "x"]) == 2, "лишние слова приняты")


def test_heavy():
    e = Env()
    t = day()
    e.at_line(t, 0)
    check(N.gate("autostart", t, heavy=2)[0] is False, "2 тяжёлых — gate пустил")
    check(N.gate("autostart", t, heavy=1) == (True, ""), f"1 тяжёлый — gate не пустил: {N.gate('autostart', t, heavy=1)}")
    json.dump({"domains": {"athena-x": ["/x"], "hermes-y": ["/y"]}}, open(os.path.join(e.state, "domains.json"), "w"))
    agents = [{"name": "athena-x", "state": "working"}, {"name": "hermes-y (2)", "state": "working"},
              {"name": "zeus", "state": "working"}, {"name": "calliope-z", "state": "working"}]
    check(N.heavy_count(agents, []) == 2, f"heavy_count: {N.heavy_count(agents, [])}")
    ok, why = N.gate("autostart", t, agents, [])
    check(not ok and "тяжёлых уже 2" in why, f"gate по сессиям: {ok} {why}")
    agents[1]["state"] = "done"
    check(N.gate("autostart", t, agents, [])[0], "1 работающее направление — gate не пустил")
    # тяжёлая задача тика, которая идёт (держит job-<имя>)
    open(os.path.join(e.pantheon, "schedule.toml"), "a").write(
        '[[job]]\nname = "clio-weekly"\ncommand = "pantheon view"\nclass = "heavy"\n')
    with P.lock("job-clio-weekly"):
        check(N.heavy_count(agents, []) == 2, "идущая тяжёлая задача не посчитана")
    check(N.heavy_count(agents, []) == 1, "закончившаяся задача посчитана")
    # respawn тяжёлые не считает
    check(N.gate("respawn", t, heavy=5)[0], "respawn днём упёрся в тяжёлые")


def test_heavy_agents_unknown_1180():
    """metis-1180: claude agents ответил не JSON (None) — тяжёлых не сосчитать: heavy_count падает, а не считает 0, и
    gate нового запуска не пускает (awake.gate ловит исключение отказом); переданный список — как раньше."""
    e = Env()
    t = day()
    e.at_line(t, 0)
    real = P.agents_all
    P.agents_all = lambda: None
    try:
        err = None
        try:
            N.heavy_count()
        except RuntimeError as ex:
            err = ex
        check(err is not None and "claude agents" in str(err), f"heavy_count при None: {err!r}")
        ok, why = P.awake_mod().gate("wake", t)
        check(not ok and "claude agents" in why, f"gate при None claude agents пустил: {ok} {why}")
        check(N.heavy_count([], []) == 0, "heavy_count с пустым списком — не 0")
    finally:
        P.agents_all = real


def test_day_rules_and_respawn():
    e = Env()
    t = day()
    e.at_line(t, 3)  # жёлтая
    ok, why = N.gate("autostart", t, heavy=0)
    check(not ok and why.startswith("жёлтая зона днём"), f"жёлтая днём — autostart: {ok} {why}")
    check(not N.gate("wake", t, heavy=0)[0], "жёлтая днём — wake пустил")
    check(N.gate("respawn", t) == (True, ""), "respawn днём в жёлтой — не пустил")
    e.at_line(t, 6)  # красная
    ok, why = N.gate("respawn", t)
    check(not ok and why.startswith("красная зона"), f"respawn днём в красной: {ok} {why}")
    e.at_line(t - 3600, 0)  # неизвестен
    # днём продолжение прерванной снимка не ждёт (решение лида 17.10), новое — ждёт
    check(N.gate("respawn", t) == (True, ""), "respawn днём при неизвестном лимите не пустил")
    check(not N.gate("autostart", t, heavy=0)[0], "autostart при неизвестном лимите пустил")
    check(not N.gate("wake", t, heavy=0)[0], "wake при неизвестном лимите пустил")
    check(not N.gate("bogus", t)[0], "неизвестный вид пустил")
    # жёлтая в 22:30 — ещё день (ночь с 23:00)
    t2 = hm("22:30")
    e.at_line(t2, 3)
    check(not N.gate("autostart", t2, heavy=0)[0], "22:30 жёлтая — пустил")
    # ночью, даже в открытой ночи, продолжение прерванной без свежего снимка не пускается
    e2 = Env()
    open_night(e2, hm("23:05"))
    e2.at_line(hm("23:06"), 0)
    e2.watch(hm("23:06"))
    check(N.gate("respawn", hm("23:10")) == (True, ""), "respawn в открытой ночи со свежим снимком не пустил")
    e2.at_line(hm("01:00") - 3600, 0)
    ok, why = N.gate("respawn", hm("01:00"))
    check(not ok and why.startswith("лимит неизвестен"), f"respawn ночью при неизвестном лимите: {ok} {why}")


def night_yes(e, t, qid="metis-0700", d=EVENING, rel=None, sha=None, answer=None, note=None, question=None,
              mark="· окно вопросов"):
    """Запись хука answer в owner-log/zeus.md: ваш выбор на вопрос `pantheon night ask` (по умолчанию — «Да — ночь <дата>»
    на пачку e.pack с её текущим sha256)."""
    ds = d.isoformat()
    rel = rel or os.path.relpath(e.pack, e.pantheon)
    sha = sha or hashlib.sha256(open(e.pack, "rb").read()).hexdigest()
    q = question or f"[{qid}] Ночь {ds}: пачка {rel} sha256 {sha}?"
    with open(os.path.join(e.state, "owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
        fh.write(f"## {datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S')} {mark}\nвопрос: {q}\n"
                 f"ответ: {answer or 'Да — ночь ' + ds}\n" + (f"заметка: {note}\n" if note else "") + "\n")


def test_night_by_answer_only_b():
    """Решение владельца 28.10 (вариант Б): фиксированного вопроса в 22:00 нет, ночь открывается только вашим ответом
    «Да — ночь <дата>» на вопрос `pantheon night ask` о пачке (путь и sha256 в вопросе). Без ответа — ни карточки, ни
    уведомления, ночь не открыта, новое ночью не идёт; ответ после начала ночи открывает её в момент ответа."""
    e = Env()
    e.resets = hm("22:00") + 3 * 86400
    for x in ("21:55", "22:00", "22:30", "23:00", "23:30"):
        e.at_line(hm(x), 0)
        e.watch(hm(x))
    check(not e.cards() and not e.sent(), f"вопрос на ночь задан: карточки {e.cards()}, уведомления {e.sent()}")
    st = N.load(EVENING)
    check(st["answer"] is None and not st.get("opened_at") and not st.get("packs"), f"ночь без ответа: {st}")
    check(N.gate("autostart", hm("23:40"), heavy=0) == (False, "ночь не открыта"),
          f"ночь без ответа — gate: {N.gate('autostart', hm('23:40'), heavy=0)}")
    check(N.status_lines(hm("23:30"))[1] == "Ночь: " + N.NIGHT_CLOSED, N.status_lines(hm("23:30")))
    check("ночь" not in e.alerts().lower(), f"строка о ночи без ответа: {e.alerts()}")
    # пачка и точный ответ днём: одобрена в 22:00, ночь открыта в 23:00
    e1 = _pack_env(start_line="")
    rel = os.path.relpath(e1.pack, e1.pantheon)
    night_yes(e1, hm("21:00"))
    for x in ("22:00", "23:00"):
        e1.at_line(hm(x), 0)
        e1.watch(hm(x))
    st = e1.state_of()
    check(st["answer"] == "да" and st["answer_at"] == hm("21:00") and st["opened_at"] == hm("23:00")
          and st["budget_pct"] == 3 and [x["path"] for x in st["packs"]] == [rel] and not st.get("auto"),
          f"ночь по ответу: {st}")
    check(e1.alerts().count("одобрена вашим ответом") == 1 and "открыта с 23:00" in e1.alerts(),
          f"строки ночи в тревогах: {e1.alerts()}")
    check(N.gate("autostart", hm("23:20"), heavy=0) == (True, ""), f"открытая ночь — gate: {N.gate('autostart', hm('23:40'), heavy=0)}")
    check(N.status_lines(hm("23:10"))[1].startswith("Ночь: открыта с 23:00, потрачено "), N.status_lines(hm("23:10")))
    # ответ после начала ночи (00:30) — ночь открывается в момент ответа
    e2 = _pack_env(start_line="")
    e2.at_line(hm("22:00"), 0)
    e2.watch(hm("22:00"))
    check(e2.state_of()["answer"] is None, f"ночь до ответа: {e2.state_of()}")
    night_yes(e2, hm("00:30"))
    e2.at_line(hm("00:31"), 0)
    e2.watch(hm("00:31"))
    st = e2.state_of()
    check(st.get("opened_at") == hm("00:30") and st["answer_at"] == hm("00:30"), f"ответ в 00:30 — ночь: {st}")
    # лимит недели неизвестен — ночь разрешена, но не открыта и новое не идёт
    e3 = _pack_env(start_line="")
    night_yes(e3, hm("21:00"))
    e3.at_line(hm("22:00") - 7200, 0)
    e3.watch(hm("23:10"))
    st = e3.state_of()
    check(st["answer"] == "да" and not st.get("opened_at") and not N.gate("autostart", hm("23:10"), heavy=0)[0],
          f"неизвестный лимит — ночь: {st}")
    # потолок недели держит и ночь
    e4 = Env('primary_host = "mac-a"\n[limits.owner_cap]\npct = 20\ndecision = "zeus-x"\n')
    _add_pack(e4, "")
    night_yes(e4, hm("21:00"))
    e4.snap(hm("23:10"), 30.0, e4.resets)
    e4.watch(hm("22:00"))
    e4.watch(hm("23:10"))
    ok, why = N.gate("autostart", hm("23:15"), heavy=0)
    check(not ok and "20" in why, f"потолок недели ночью не держит: {ok} {why}")


def test_night_answer_refused_b():
    """Ответ, по которому ночь не открывается: пачка изменилась после вопроса (sha256 другой), ответ не дословный,
    заметка, вопрос не по шаблону, ответ «Нет», вопрос о другой ночи, без пометки «окно вопросов», пачки по пути нет.
    Отказ — строка в тревогах с причиной (кроме «Нет», чужой ночи и чужой пометки), ночь не открыта, запусков нет."""
    def changed(e):
        night_yes(e, hm("21:00"))
        open(e.pack, "a", encoding="utf-8").write("| 3 | metis-0399 | дописано после вопроса |\n")

    def no_sha(e):
        rel = os.path.relpath(e.pack, e.pantheon)
        night_yes(e, hm("21:00"), question=f"[metis-0700] Ночь {EVENING.isoformat()}: пачка {rel}?")

    cases = (
        ("пачка изменилась", changed, "изменилась после вашего ответа"),
        ("ответ «Да»", lambda e: night_yes(e, hm("21:00"), answer="Да"), "а не «Да — ночь 2026-10-15»"),
        ("ответ с хвостом", lambda e: night_yes(e, hm("21:00"), answer="Да — ночь 2026-10-15, но только 0210"),
         "а не «Да — ночь"),
        ("заметка", lambda e: night_yes(e, hm("21:00"), note="только metis-0210"), "заметка"),
        ("вопрос без sha256", no_sha, "не по шаблону pantheon night ask"),
        ("чужой sha256", lambda e: night_yes(e, hm("21:00"), sha="0" * 64), "изменилась после вашего ответа"),
        ("нет такой пачки", lambda e: night_yes(e, hm("21:00"), rel="directions/metis-x/night-2026-01-01-pack.md"),
         "ночь по ней не открываю"),
        ("ответ «Нет»", lambda e: night_yes(e, hm("21:00"), answer="Нет"), None),
        ("другая ночь", lambda e: night_yes(e, hm("21:00"), d=EVENING - timedelta(days=1)), None),
        ("свободный ввод", lambda e: night_yes(e, hm("21:00"), mark="· свободный ввод"), None),
    )
    for label, prep, why in cases:
        e = _pack_env(start_line="")
        prep(e)
        e.at_line(hm("23:05"), 0)
        e.watch(hm("23:05"))
        e.watch(hm("23:10"))
        st = N.load(EVENING)
        check(st["answer"] is None and not st.get("opened_at") and not st.get("packs") and not oneshots(e)
              and not N.gate("autostart", hm("23:20"), heavy=0)[0], f"{label}: ночь открылась: {st} {oneshots(e)}")
        al = e.alerts()
        if why:
            check(why in al and al.count("ночь 15.10:") == 1, f"{label}: нет причины отказа «{why}» (одна): {al}")
        else:
            check("ночь 15.10:" not in al, f"{label}: лишняя строка: {al}")


def test_night_ask_cmd_b():
    """`pantheon night ask <id> <направление>` печатает вопрос по шаблону с путём и sha256 пачки и варианты; ваш выбор
    «Да — ночь <дата>» на этот вопрос открывает ночь. Нет пачки, кривой id, лишний аргумент, кривая дата — код 2."""
    e = _pack_env(start_line="")

    def ask(*a):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = N.night_ask_cmd(list(a), t=hm("21:00"))
        return rc, out.getvalue(), err.getvalue()

    rc, out, err = ask("metis-0700", "metis-x")
    sha = hashlib.sha256(open(e.pack, "rb").read()).hexdigest()
    rel = os.path.relpath(e.pack, e.pantheon)
    q = f"[metis-0700] Ночь 2026-10-15: пачка {rel} sha256 {sha}?"
    check(rc == 0 and out.startswith(f"вопрос: {q}\nварианты: Да — ночь 2026-10-15 | Нет\n"), f"night ask: {rc} {out!r} {err!r}")
    bad = [ask(*a)[0] for a in (("metis-0700", "nosuch"), ("Metis-0700", "metis-x"), ("metis-0700", "metis-x", "x"),
                                ("metis-0700",), ("metis-0700", "metis-x", "2026-10-15", "лишнее"))]
    check(bad == [2, 2, 2, 2, 2], f"night ask без отказа: {bad}")
    check(ask("metis-0700", "metis-x", "2026-10-15")[0] == 0, "night ask с датой")
    lines = out.splitlines()
    night_yes(e, hm("21:01"), question=lines[0][len("вопрос: "):], answer=lines[1][len("варианты: "):].split(" | ")[0])
    e.at_line(hm("23:00"), 0)
    e.watch(hm("23:00"))
    check(e.state_of().get("opened_at") == hm("23:00"), f"ответ на напечатанный вопрос не открыл ночь: {e.state_of()}")


def test_night_old_card_closed_0523():
    """Карточка вопроса, заданного до выпуска (card_id в состоянии ночи, ответа нет), снимается проходом; без ответа
    о пачке ночь не открыта; уже пропущенная ночь («Нет» до выпуска) не открывается."""
    e = Env()
    e.resets = hm("22:00") + 3 * 86400
    T = P.tasks_mod()
    tid, _ = T.task_new(e.pantheon, hm("22:00"), "inbox", "Запустить сегодня на ночь выполнение задач?", owner="zeus",
                        status="waiting", waiting_on="human", actor="плановый проход")
    os.makedirs(os.path.join(e.state, "night"), exist_ok=True)
    json.dump({"card_id": tid, "card_at": hm("22:00"), "asked_at": ["x"]},
              open(os.path.join(e.state, "night", EVENING.isoformat() + ".json"), "w"))
    e.at_line(hm("23:05"), 0)
    e.watch(hm("23:05"))
    check(e.cards()[tid]["status"] == "dropped" and not e.state_of().get("opened_at"),
          f"старая карточка: {e.cards()[tid]['status']}, ночь {e.state_of()}")
    e2 = Env()
    os.makedirs(os.path.join(e2.state, "night"), exist_ok=True)
    json.dump({"answer": "нет", "skipped": "ответ «Нет»"},
              open(os.path.join(e2.state, "night", EVENING.isoformat() + ".json"), "w"))
    e2.at_line(hm("23:05"), 0)
    e2.watch(hm("23:05"))
    check(not e2.state_of().get("opened_at") and not N.gate("autostart", hm("23:10"), heavy=0)[0],
          f"пропущенная до выпуска ночь открылась: {e2.state_of()}")


def open_night(e, answer_at=None, over=0.0):
    """Ночь с пачкой и вашим ответом «Да — ночь» (вариант Б, 28.10), в 21:00; answer_at — от старого вопроса, не действует."""
    _add_pack(e, "")
    night_yes(e, hm("21:00"))
    e.resets = hm("22:00") + 3 * 86400
    e.at_line(hm("22:00"), over)
    e.watch(hm("22:00"))
    return None, None


def test_budget():
    e = Env()
    d = EVENING
    t = hm("23:00")
    for over, want in ((0, 3), (-10, 4.5), (-15, 5), (-30, 5), (4, 3)):
        e.at_line(t, over)
        b, last = N.budget(N.measure(t), d, N.config())
        check(b == want and not last, f"запас {over:+}: бюджет {b}, ждали {want}")
    # последняя ночь: сброс в пределах 24 ч от начала ночи
    for used, want in ((50, 10), (80, 5), (85, 0)):
        e.snap(t, used, t + 11 * 3600)
        b, last = N.budget(N.measure(t), d, N.config())
        check(last and b == want, f"последняя ночь, неделя {used} %: бюджет {b} ({last}), ждали {want}")
    e.snap(t, 50, t + 25 * 3600)
    check(not N.budget(N.measure(t), d, N.config())[1], "сброс через 25 ч — «последняя ночь»")
    # пороги из schedule.toml
    e2 = Env('primary_host = "mac-a"\n[limits.night]\nbudget_pct = 4\ncap_pct = 6\n')
    e2.at_line(t, -20)
    check(N.budget(N.measure(t), d, N.config())[0] == 6, "budget_pct/cap_pct из schedule.toml не взяты")
    e2.at_line(t, 0)
    check(N.budget(N.measure(t), d, N.config())[0] == 4, "budget_pct из schedule.toml не взят")
    # открытая ночь с переносом пишет бюджет в состояние
    e3 = Env()
    open_night(e3, hm("23:05"), over=-10)
    e3.at_line(hm("23:06"), -10)
    e3.watch(hm("23:06"))
    check(e3.state_of()["budget_pct"] == 4.5, f"перенос в состоянии ночи: {e3.state_of()}")


def test_night_alerts_and_close():
    e = Env()
    open_night(e, hm("23:05"))
    t0 = hm("23:06")
    resets = e.resets
    u0 = e.at_line(t0, 0)
    e.watch(t0)
    st = e.state_of()
    check(st["start_pct"] == u0 and st["budget_pct"] == 3, f"открытие: {st}")
    steps = (("00:30", 1.0, []), ("01:00", 1.5, [50]), ("01:30", 2.0, [50]), ("02:00", 2.4, [50, 80]))
    for x, d, want in steps:
        used = u0 + d
        e.snap(hm(x), used, resets)
        e.watch(hm(x))
        check(e.state_of()["alerts"] == want, f"{x} неделя {used}: тревоги {e.state_of()['alerts']}, ждали {want}")
    check(e.alerts().count("Ночь 15.10: потрачено") == 2, f"строки тревог ночи: {e.alerts()}")
    # 2,4 из 3: работа (3 − 1 = 2) исчерпана — новое не запускается, ночь ещё не закрыта
    ok, why = N.gate("autostart", hm("02:00"), heavy=0)
    check(not ok and "бюджет работы ночи исчерпан" in why, f"работа исчерпана — gate: {ok} {why}")
    e.snap(hm("02:30"), u0 + 3.0, resets)
    e.watch(hm("02:30"))
    st = e.state_of()
    check(st["alerts"] == [50, 80, 100] and st.get("closed"), f"100 % — {st}")
    check("ночь закрыта для нового" in e.alerts(), "нет строки о закрытии")
    check(N.gate("respawn", hm("02:40"))[0] is False, "закрытая ночь — respawn пустил")
    e.watch(hm("02:45"))
    check(e.alerts().count("Ночь 15.10: потрачено") == 3, "тревога ночи повторилась")
    e.snap(hm("08:55"), u0 + 3.1, resets)
    rep = N.report_lines(hm("09:00"))
    check(any(ln.startswith("Ночь 15.10: открыта с 23:00, потрачено 3 из 3 %") and "тревоги: 50 %, 80 %, 100 %" in ln
              for ln in rep), f"сводка: {rep}")


def test_reset_mid_night_two_passes_0243():
    """Сброс недели посреди ночи: расход ночи верен и на первом проходе после сброса, и на следующих."""
    e = Env()
    open_night(e, hm("23:05"))
    t0 = hm("23:06")
    u0 = e.at_line(t0, 0)
    e.watch(t0)
    e.snap(hm("23:30"), u0 + 1.0, e.resets)
    e.watch(hm("23:30"))
    check(e.state_of()["spent"] == 1.0, f"до сброса: {e.state_of()}")
    new = e.resets + 7 * 86400
    for x, used, want in (("00:30", 0.5, 1.5), ("01:00", 1.0, 2.0), ("01:30", 1.2, 2.2)):
        e.snap(hm(x), used, new)
        e.watch(hm(x))
        got = e.state_of()["spent"]
        check(abs(got - want) < 1e-6, f"{x} после сброса: spent {got}, ждали {want}: {e.state_of()}")


def test_early_reset_idle_window_0246():
    """metis-0246: неделю сбросили досрочно (новый resets_at), а простаивающее окно ещё пишет строку со старым
    resets_at позже новой. База недели переносится только вперёд: расход ночи 2, а не скачок (было 60)."""
    e = Env()
    open_night(e, hm("23:05"))
    t0 = hm("23:06")
    u0 = e.at_line(t0, 0)
    e.watch(t0)
    old, new = e.resets, e.resets + 2 * 86400
    e.snap(hm("23:30"), u0 + 1.0, old)
    e.watch(hm("23:30"))
    check(e.state_of()["spent"] == 1.0, f"до сброса: {e.state_of()}")
    e.week_usage([(hm("23:40"), new, 0.5)])
    e.snap(hm("23:40"), 0.5, new)
    e.watch(hm("23:40"))
    check(abs(e.state_of()["spent"] - 1.5) < 1e-6, f"после раннего сброса: {e.state_of()}")
    # простаивающее окно пишет старый сброс позже новой строки
    e.week_usage([(hm("23:45"), old, u0 + 1.0)])
    e.snap(hm("23:45"), u0 + 1.0, old)
    e.watch(hm("23:45"))
    check(abs(e.state_of()["spent"] - 1.5) < 1e-6, f"старая строка простаивающего окна сдвинула расход: {e.state_of()}")
    e.week_usage([(hm("23:50"), new, 1.0)])
    e.snap(hm("23:50"), 1.0, new)
    e.watch(hm("23:50"))
    check(abs(e.state_of()["spent"] - 2.0) < 1e-6, f"после старой строки: spent {e.state_of()['spent']}, ждали 2")
    # проба «вперёд»: строк новой недели в week-usage не осталось (файл усечён), в снимке только старая неделя
    # (resets_at раньше сохранённого больше чем на час) — замер игнорируется, spent не берёт used старой недели
    os.remove(os.path.join(e.sl, "week-usage"))
    e.snap(hm("23:55"), u0 + 60.8, old)
    e.watch(hm("23:55"))
    st = e.state_of()
    check(abs(st["spent"] - 2.0) < 1e-6 and st["resets_at"] == new,
          f"замер со старым resets_at (назад) сдвинул ночь: {st}")


def test_fractional_budget():
    """metis-0214: при budget_pct=1 тревоги 50/80 идут по дробному расходу (снимок недели с дробным процентом).
    Порог 50 % от 1 — 0,5 п. п., поэтому 0,4 тревоги не даёт, 0,5 даёт 50, 0,85 — 50 и 80."""
    e = Env('primary_host = "mac-a"\n[limits.night]\nbudget_pct = 1\ncheck_pct = 0.2\ncap_pct = 1\n')
    open_night(e, hm("23:05"))
    t0 = hm("23:06")
    resets = e.resets
    u0 = e.at_line(t0, 0)
    e.watch(t0)
    st = e.state_of()
    check(st["budget_pct"] == 1, f"бюджет 1: {st}")
    for x, d, want in (("00:30", 0.4, []), ("01:00", 0.5, [50]), ("01:30", 0.85, [50, 80])):
        e.snap(hm(x), u0 + d, resets)
        e.watch(hm(x))
        st = e.state_of()
        check(st["alerts"] == want and abs(st["spent"] - d) < 1e-6,
              f"{x} расход {d}: тревоги {st['alerts']}, потрачено {st['spent']}, ждали {want}")


def test_morning_five_hour():
    e = Env()
    open_night(e, hm("23:05"))
    e.at_line(hm("23:06"), 0)
    e.watch(hm("23:06"))
    u0 = e.state_of()["start_pct"]
    t = hm("04:10")
    e.snap(t, u0 + 0.5, e.resets)
    e.watch(t)
    e.snap(t, u0 + 0.5, e.resets, five=51)
    ok, why = N.gate("autostart", t, heavy=0)
    check(not ok and "пятичасовой лимит 51 % > 50 %" in why, f"после 04:00 пятичасовой 51 — gate: {ok} {why}")
    e.snap(t, u0 + 0.5, e.resets, five=50)
    check(N.gate("autostart", t, heavy=0)[0], "после 04:00 пятичасовой 50 — gate не пустил")
    # правило утра — и для продолжения прерванной (решение лида 17.10)
    e.snap(t, u0 + 0.5, e.resets, five=51)
    ok, why = N.gate("respawn", t)
    check(not ok and "пятичасовой лимит 51 % > 50 %" in why, f"после 04:00 пятичасовой 51 — respawn: {ok} {why}")
    e.snap(t, u0 + 0.5, e.resets, five=50)
    check(N.gate("respawn", t) == (True, ""), "после 04:00 пятичасовой 50 — respawn не пустил")
    t3 = hm("03:50")
    e.snap(t3, u0 + 0.5, e.resets, five=80)
    check(N.gate("autostart", t3, heavy=0)[0], "до 04:00 правило пятичасового лимита сработало")
    os.environ["PANTHEON_FAKE_LIMIT"] = "51"
    e.snap(t, u0 + 0.5, e.resets, five=10)
    check(not N.gate("wake", t, heavy=0)[0], "PANTHEON_FAKE_LIMIT не учтён")
    os.environ.pop("PANTHEON_FAKE_LIMIT", None)
    # ночь не открыта — ночью нельзя, даже в зелёной
    e2 = Env()
    e2.at_line(hm("01:00"), -20)
    ok, why = N.gate("autostart", hm("01:00"), heavy=0)
    check(not ok and why == "ночь не открыта", f"ночь без вопроса — gate: {ok} {why}")
    # жёлтая ночью с открытой ночью — можно (решает бюджет)
    e3 = Env()
    open_night(e3, hm("23:05"), over=3)
    e3.at_line(hm("23:06"), 3)
    e3.watch(hm("23:06"))
    e3.at_line(hm("23:30"), 3)
    check(N.gate("autostart", hm("23:30"), heavy=0)[0], "жёлтая ночью при открытой ночи — не пустил")
    # 08:00 — снова день
    e3.at_line(hm("08:00"), 0)
    check(N.night_of(hm("08:00"), N.config()) is None and N.gate("autostart", hm("08:00"), heavy=0)[0], "08:00 — не день")


def test_zone_notifications():
    e = Env()
    t = day("11:00")
    e.at_line(t, 3)
    e.watch(t)
    e.watch(t + 600)
    yellow = [x for x in e.alerts().splitlines() if "зона жёлтая" in x]
    check(len(yellow) == 1 and "п.п." in yellow[0] and "линии" in yellow[0], f"жёлтая — строк {yellow}")
    e.at_line(t + 1200, 6)
    e.watch(t + 1200)
    check(sum("зона красная" in x for x in e.alerts().splitlines()) == 1, "красная — нет строки")
    e.at_line(t + 86400, 3)
    e.watch(t + 86400)
    check(sum("зона жёлтая" in x for x in e.alerts().splitlines()) == 2, "жёлтая на другой день — не повторилась")


def test_not_primary():
    e = Env('primary_host = "mac-b"\n')
    e.at_line(hm("22:00"), 0)
    e.watch(hm("22:00"))
    check(not e.cards() and not e.sent(), "второй Mac задал вопрос")


def test_metrics():
    e = Env()
    t = day()
    r1 = t + 2 * 86400
    e.at_line(t, 0, resets=r1)
    e.week_usage([(t - 600, r1, 30), (t - 300, r1, 31)])
    e.watch(t)
    log = os.path.join(e.state, "metrics", "week-usage.log")
    check(open(log).read().count("\n") == 2, f"week-usage.log: {open(log).read()!r}")
    e.watch(t + 60)
    check(open(log).read().count("\n") == 2, "week-usage.log — повтор строк")
    e.week_usage([(t + 100, r1, 32)])
    e.watch(t + 200)
    check(open(log).read().splitlines()[-1].endswith(" 32") and open(log).read().count("\n") == 3, "новая строка не дописана")
    # ночь этой недели и смена недели
    json.dump({"opened_at": hm("23:05"), "budget_pct": 3, "spent": 1.2, "alerts": [50], "skipped": None,
               "asked_at": [], "card_id": None, "answer": "да", "start_pct": 20},
              open(os.path.join(e.state, "night", EVENING.isoformat() + ".json"), "w")) \
        if os.path.isdir(os.path.join(e.state, "night")) else None
    os.makedirs(os.path.join(e.state, "night"), exist_ok=True)
    json.dump({"opened_at": hm("23:05"), "budget_pct": 3, "spent": 1.2, "alerts": [50], "skipped": None,
               "asked_at": [], "card_id": None, "answer": "да", "start_pct": 20},
              open(os.path.join(e.state, "night", EVENING.isoformat() + ".json"), "w"))
    e.snap(t + 300, 64.0, r1)
    e.watch(t + 300)
    r2 = r1 + WEEK
    e.snap(r1 + 600, 1.0, r2)
    e.watch(r1 + 600)
    e.watch(r1 + 900)
    wj = os.path.join(e.state, "metrics", "weeks.jsonl")
    rows = [json.loads(x) for x in open(wj)] if os.path.exists(wj) else []
    check(len(rows) == 1 and rows[0]["final_pct"] == 64.0 and rows[0]["resets_at"] == round(r1)
          and rows[0]["nights"] and rows[0]["nights"][0]["date"] == EVENING.isoformat()
          and rows[0]["nights"][0]["spent"] == 1.2, f"weeks.jsonl: {rows}")


def test_status_format():
    e = Env()
    # пятница 16.10 10:00 — сброс; линия 43 %, неделя 41 %
    resets = datetime(2026, 10, 16, 10, 0).timestamp()
    t = resets - 0.57 * WEEK
    e.snap(t - 300, 41.0, resets)
    lines = N.status_lines(t)
    check(lines[0] == "Неделя: 41 % · линия 43 % · запас −2 п.п. · зона: зелёная · сброс пт 10:00", lines[0])
    check(lines[2] == "Снимок лимита: 5 мин назад", lines[2])
    check(lines[1] == "Ночь: не открыта — только по вашему ответу на вопрос о пачке (pantheon night ask)", lines[1])
    e.snap(t - 45 * 60, 41.0, resets)
    check(N.status_lines(t)[2] == "лимит неизвестен (45 мин)", N.status_lines(t)[2])
    check(N.num(1.25) in ("1,2", "1,3") and N.num(-2) == "−2" and N.signed(2.1) == "+2,1", "формат чисел")
    # CLI: pantheon night, pantheon night report, справка, pantheon status
    e.snap(t - 300, 41.0, resets)
    # поддельный claude первым в PATH: «pantheon status» считает тяжёлые сессии через `claude agents` — без подделки
    # тест звал бы настоящий claude владельца, а на раннере CI, где его нет, status падал (metis-0573)
    fbin = os.path.join(e.home, "fake-bin")
    os.makedirs(fbin, exist_ok=True)
    with open(os.path.join(fbin, "claude"), "w") as fh:
        fh.write("#!/bin/sh\necho '[]'\n")
    os.chmod(os.path.join(fbin, "claude"), 0o755)
    env = {"PATH": fbin + os.pathsep + os.environ["PATH"], "HOME": e.home, "PANTHEON_HOME": e.pantheon, "PANTHEON_SCHEDULE_DEFAULTS": os.devnull,
           "PANTHEON_STATE": e.state, "PANTHEON_NOW": str(t), "PANTHEON_HOST": "mac-a", "PANTHEON_NO_NOTIFY": "1", "TMPDIR": _ROOT}
    if "TZ" in os.environ:  # дочерний процесс в том же поясе, что и тест (metis-0222)
        env["TZ"] = os.environ["TZ"]
    run = lambda *a: subprocess.run([PY311, "-I", os.path.join(LIB, "pantheon.py"), *a], env=env,  # noqa: E731
                                    capture_output=True, text=True, timeout=60)
    r = run("night")
    check(r.returncode == 0 and "Неделя: 41 % · линия 43 %" in r.stdout, f"pantheon night: {r.stdout} {r.stderr[-300:]}")
    r = run("night", "report")
    check(r.returncode == 0 and r.stdout.startswith("Лимит\n") and "Сброс недели: пт 10:00" in r.stdout
          and "Ночь " in r.stdout, f"pantheon night report: {r.stdout} {r.stderr[-300:]}")
    check(run("night", "bogus").returncode == 2, "pantheon night bogus — не код 2")
    check("pantheon night [status|report]" in run("help").stdout and "pantheon night ask <id>" in run("help").stdout,
          "в справке нет pantheon night")
    r = run("status")
    check("Лимит и ночь" in r.stdout and "Неделя: 41 %" in r.stdout, f"pantheon status без раздела: код {r.returncode} {r.stdout[-800:]} {r.stderr[-600:]}")
    # pantheon limit reset-mark (metis-1067): из окна роли — отказ без файла, из терминала владельца — отметка
    mark = os.path.join(e.state, "limit", "reset-mark.json")
    env["PANTHEON_ROLE"] = "dev"
    r = run("limit", "reset-mark")
    check(r.returncode == 2 and "окно роли" in r.stderr and not os.path.exists(mark), f"limit из окна роли: {r}")
    del env["PANTHEON_ROLE"]
    r = run("limit", "reset-mark")
    check(r.returncode == 0 and json.load(open(mark))["resets_at"] == resets, f"pantheon limit reset-mark: {r}")
    check("pantheon limit reset-mark" in run("help").stdout, "в справке нет pantheon limit reset-mark")
    os.remove(mark)


def _pack_env(start_line="- Старт — 04:00, но не раньше выпуска"):
    """Направление metis-x с ночной пачкой на утро после вечера EVENING (как night-2026-10-19-pack.md у ночи 18→19)."""
    return _add_pack(Env(), start_line)


def _add_pack(e, start_line):
    folder = os.path.join(e.home, "projects", "metis-x")
    os.makedirs(folder, exist_ok=True)
    json.dump({"domains": {"metis-x": [folder]}}, open(os.path.join(e.state, "domains.json"), "w"))
    d = os.path.join(e.pantheon, "directions", "metis-x")
    os.makedirs(d, exist_ok=True)
    e.pack = os.path.join(d, f"night-{(EVENING + timedelta(days=1)).isoformat()}-pack.md")
    open(e.pack, "w", encoding="utf-8").write(
        "# Ночная пачка metis-x\n\n| Порядок | Задача | Что |\n|---|---|---|\n| 1 | metis-0210 | тест |\n"
        "| 2 | metis-0251 | ветка metis-night-1019 |\n\n## Стоп-условия\n\n" + start_line + "\n")
    e.resets = hm("22:00") + 3 * 86400
    return e


def oneshots(e):
    p = os.path.join(e.state, "oneshot.json")
    return json.load(open(p))["items"] if os.path.exists(p) else []


def test_pack_approved_0284():
    """Пачка с вашим ответом «Да — ночь» (вариант Б, 28.10) одобрена: путь и sha256 — в состоянии ночи, ровно один разовый
    запуск её координатора на старт пачки (04:00) со сроком до конца ночи, и повторный ответ его не удваивает."""
    e = _pack_env()
    rel = f"directions/metis-x/night-{(EVENING + timedelta(days=1)).isoformat()}-pack.md"
    night_yes(e, hm("21:00"))
    check(N.pack_night(hm("21:50")) == [], "пачка до вечера — уже ночь пачек")
    e.at_line(hm("22:00"), 0)
    e.watch(hm("22:00"))
    night_yes(e, hm("22:03"), qid="metis-0701")
    e.watch(hm("22:05"))
    check(not e.cards(), f"карточка вопроса: {e.cards()}")
    st = e.state_of()
    check([p["path"] for p in st.get("packs") or []] == [rel] and st["packs"][0]["start"] == "04:00"
          and len(st["packs"][0]["sha"]) == 64 and st["packs"][0]["tasks"] == ["metis-0210", "metis-0251"],
          f"пачка в состоянии: {st.get('packs')}")
    check("пачка metis-x/night-" in e.alerts() and e.alerts().count("одобрена вашим ответом") == 1,
          f"тревога не называет пачку: {e.alerts()}")
    items = oneshots(e)
    check(len(items) == 1, f"разовых запусков {len(items)}: {items}")
    if items:
        it = items[0]
        check(it["target"] == "metis-x" and it["at"] == hm("04:00") and it["expires"] == hm("08:00")
              and it["pack"] == rel and it["sha"] == st["packs"][0]["sha"] and not it["done_at"],
              f"запись разового запуска: {it}")
        check(rel in it["text"] and "не согласие" in it["text"] and "ответил «Да»" not in it["text"],
              f"задание: {it['text']}")
    check(e.state_of().get("pack_jobs") == [x["id"] for x in items], f"pack_jobs: {e.state_of().get('pack_jobs')}")
    check([p["path"] for p in N.pack_night(hm("23:30"))] == [rel], "ночь с пачкой — pack_night пуст")
    check(N.oneshot_due(hm("03:59")) == [] and len(N.oneshot_due(hm("04:00"))) == 1, "время разового запуска")
    check(any("Разовый запуск pack-" in x for x in N.status_lines(hm("23:00"))), "pantheon night не показывает запуск")
    # без строки «Старт» — в начале ночи; следующей ночью эта пачка уже взята — не берётся снова
    e2 = _pack_env(start_line="")
    night_yes(e2, hm("21:00"))
    e2.at_line(hm("22:00"), 0)
    e2.watch(hm("22:00"))
    check([x["at"] for x in oneshots(e2)] == [hm("23:00")], f"без «Старт» — не в начале ночи: {oneshots(e2)}")
    nxt = EVENING + timedelta(days=1)
    open(e2.pack.replace(nxt.isoformat(), (nxt - timedelta(days=1)).isoformat()), "w").write("старая\n")
    check(N.packs(nxt) == [] , f"взятая прошлой ночью пачка взята снова: {N.packs(nxt)}")
    check([p["path"] for p in N.packs(EVENING)] == [p["path"] for p in e2.state_of()["packs"]], "пачка вечера")


def test_pack_skip_cancels_0284():
    """Ночь пропущена (бюджета нет: последняя ночь перед сбросом, неделя у порога) — разовый запуск пачки погашен без
    запуска."""
    e = _pack_env()
    night_yes(e, hm("21:00"))
    e.resets = hm("22:00") + 12 * 3600
    e.snap(hm("22:00"), 85.0, e.resets)
    e.watch(hm("22:00"))
    e.snap(hm("23:05"), 85.0, e.resets)
    e.watch(hm("23:05"))
    items = oneshots(e)
    check(e.state_of()["skipped"] and len(items) == 1 and items[0]["done_at"] and "отменён" in (items[0]["result"] or ""),
          f"пропуск ночи не погасил запуск пачки: {e.state_of()} {items}")
    check(N.oneshot_due(hm("04:00")) == [] and N.pack_night(hm("23:30")) == [], "после пропуска пачка ещё в ночи")


def test_oneshot_id_by_source_0284():
    """Ручной --at и пачка ночи на ту же минуту и цель — две записи (ревью argus, #78): у пачки свой номер pack-…, текст,
    pack и sha; обратный порядок тоже. Своё повторное добавление по-прежнему не дублируется."""
    e = Env()
    t = day("14:00")
    for order in ((("zeus", {}), ("night", {"pack": "metis-x/p.md", "sha": "ab" * 32})),
                  (("night", {"pack": "metis-x/p.md", "sha": "ab" * 32}), ("zeus", {}))):
        open(os.path.join(e.state, "oneshot.json"), "w").write("{}")
        ids = [N.oneshot_add("metis-x", t + 600, f"текст {by}", by, t=t, **ex) for by, ex in order]
        items = {x["id"]: x for x in oneshots(e)}
        check(ids[0] != ids[1] and len(items) == 2, f"ручной и пачка слились: {ids} {items}")
        pk = next((x for x in items.values() if x["by"] == "night"), {})
        check(pk.get("id", "").startswith("pack-") and pk.get("text") == "текст night" and pk.get("sha") == "ab" * 32
              and pk.get("pack") == "metis-x/p.md", f"запись пачки потеряла свои поля: {pk}")
        hand = next((x for x in items.values() if x["by"] == "zeus"), {})
        check(hand.get("id", "").startswith("at-") and hand.get("pack") is None, f"ручная запись: {hand}")
    again = N.oneshot_add("metis-x", t + 600, "текст night", "night", t=t, pack="metis-x/p.md", sha="ab" * 32)
    check(again.startswith("pack-") and len(oneshots(e)) == 2, "повтор пачки продублирован")


def test_pack_text_home_prefix_0284():
    """Путь пачки в задании: «~» только вместо приставки HOME, а не первого вхождения (ревью argus, п. 4)."""
    Env()
    saved = (P.HOME, P.PANTHEON)
    try:
        P.HOME, P.PANTHEON = "/h", "/x/h/pan"
        txt = N.pack_text({"card_id": "c"}, EVENING, {"path": "d/n.md"})
        check("/x/h/pan/d/n.md" in txt and "~" not in txt, f"путь искажён: {txt[:200]}")
        P.HOME, P.PANTHEON = "/h", "/h/pan"
        txt = N.pack_text({"card_id": "c"}, EVENING, {"path": "d/n.md"})
        check("~/pan/d/n.md" in txt, f"приставка HOME не заменена: {txt[:200]}")
    finally:
        P.HOME, P.PANTHEON = saved


def test_oneshot_store_0284():
    """Запись разового запуска: тот же id второй раз не ставится, погашенная не гасится повторно, время «ЧЧ:ММ» —
    ближайшее впереди."""
    e = Env()
    t = day("14:00")
    a = N.oneshot_add("metis-x", t + 600, "задание", "zeus", t=t)
    b = N.oneshot_add("metis-x", t + 600, "задание", "zeus", t=t)
    check(a == b and len(oneshots(e)) == 1, f"дубль разового запуска: {oneshots(e)}")
    check(oneshots(e)[0]["expires"] == t + 600 + N.ONESHOT_TTL, "срок по умолчанию")
    check(N.oneshot_update(a, t, done_at=t, result="запущен") and not N.oneshot_update(a, t, done_at=t + 1),
          "погашенный гасится второй раз")
    check(N.parse_at("15:00", t) == day("15:00") and N.parse_at("13:00", t) == day("13:00") + 86400, "ЧЧ:ММ")
    for bad in ("25:00", "2020-01-01 10:00", "завтра"):
        try:
            N.parse_at(bad, t)
            check(False, f"parse_at принял {bad}")
        except ValueError:
            pass


FAKE_PMSET = {"battery": "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1234)\t23%; discharging; 2:10 "
                         "remaining present: true\n",
              "high": "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1234)\t91%; discharging; 9:10 "
                      "remaining present: true\n",
              "ac": "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1234)\t23%; charging; 1:10 remaining "
                    "present: true\n"}


def test_power_0284():
    """21:30–22:00 перед ночью: подставной `pmset -g batt` — на батарее 23 % тревога «подключите зарядку» и
    уведомление, одна за вечер; на зарядке, при 91 %, до 21:30 и у пропущенной ночи — тихо."""
    saved = {k: os.environ.pop(k, None) for k in ("PANTHEON_FAKE_AC", "PANTHEON_FAKE_BATT")}
    path0 = os.environ["PATH"]
    try:
        def run(kind, x, e, pre=None):
            b = os.path.join(e.tmp, "bin-" + kind)
            os.makedirs(b, exist_ok=True)
            open(os.path.join(b, "pmset"), "w").write("#!/bin/sh\ncat <<'X'\n" + FAKE_PMSET[kind] + "X\n")
            os.chmod(os.path.join(b, "pmset"), 0o755)
            os.environ["PATH"] = b + os.pathsep + path0
            t = day(x)
            e.at_line(t, 0)
            e.watch(t)

        def lines(e):
            return [x for x in e.alerts().splitlines() if "подключите зарядку" in x]
        e = Env()
        run("battery", "21:20", e)
        check(not lines(e), "до 21:30 — тревога о питании")
        run("battery", "21:35", e)
        got = lines(e)
        check(len(got) == 1 and "23 %" in got[0], f"батарея 23 % в 21:35 — тревога: {got}")
        notes = open(os.path.join(e.state, "notify.json"), encoding="utf-8").read() \
            if os.path.exists(os.path.join(e.state, "notify.json")) else ""
        check("подключите зарядку" in notes or any("подключите зарядку" in x for x in e.sent()),
              "нет уведомления о питании")
        run("battery", "21:50", e)
        check(len(lines(e)) == 1, f"вторая тревога о питании за вечер: {lines(e)}")
        e2 = Env()
        run("ac", "21:40", e2)
        run("high", "21:45", e2)
        check(not lines(e2), f"на зарядке или 91 % — тревога: {lines(e2)}")
        e3 = Env()
        os.makedirs(os.path.join(e3.state, "night"), exist_ok=True)
        json.dump({"skipped": "ответ «Нет»"}, open(os.path.join(e3.state, "night", EVENING.isoformat() + ".json"), "w"))
        run("battery", "21:40", e3)
        check(not lines(e3), "пропущенная ночь — тревога о питании")
        e4 = Env()
        run("battery", "21:40", e4)
        check(N.power() == (23.0, False), f"разбор pmset: {N.power()}")
    finally:
        os.environ["PATH"] = path0
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_probe_stale_snapshot_0459():
    """Снимок старше 3 ч, ночь одобрена: проход делает пробный запрос (заглушка), мерит заново и открывает ночь;
    не освежило — тревога и закрыто; не чаще раза в 30 мин; без одобрения, днём, при свежем снимке — запроса нет."""
    resets = hm("22:00") + 3 * 86400

    def run(e, t, fresh=False):
        PROBES.clear()

        def stub():
            PROBES.append(t)
            if fresh:  # настоящее событие, сроки подогнаны под время теста; снимок пишет сам probe_save
                return 0, REAL_EVENT.replace("1793941200", str(int(resets))).replace("1793635800", str(int(t + 3600)))
            return 0, ""
        N.probe_run = stub
        e.watch(t)
        N.probe_run = _no_probe
        return list(PROBES)

    e = Env()
    open_night(e)  # ответ «Да» есть, снимок 22:00
    e.resets = resets
    e.at_line(hm("22:00") - 4 * 3600, 0)  # снимок 4 ч назад
    check(len(run(e, hm("23:00"), fresh=True)) == 1, "старый снимок при одобренной ночи — пробного запроса нет")
    check(e.state_of().get("opened_at") == hm("23:00"), f"после зонда ночь не открылась: {e.state_of()}")
    check("зонд не освежил" not in e.alerts(), "зонд освежил, а тревога есть")
    sd = open(os.path.join(e.sl, "seven-day")).read().split()
    fh = open(os.path.join(e.sl, "five-hour")).read().split()
    check(sd == ["35", str(int(resets)), str(int(hm("23:00")))] and fh[0] == "10" and fh[2] == str(int(hm("23:00"))),
          f"снимок из события зонда: seven-day {sd}, five-hour {fh}")
    # зонд не помог: тревога, ночь закрыта, повтор не раньше чем через 30 мин
    e2 = Env()
    open_night(e2)
    e2.resets = resets
    e2.at_line(hm("22:00") - 5 * 3600, 0)
    check(len(run(e2, hm("23:00"))) == 1, "зонд не вызван")
    check("зонд не освежил снимок" in e2.alerts() and not e2.state_of().get("opened_at"),
          f"зонд не помог, а тревоги/закрытия нет: {e2.alerts()!r} {e2.state_of()}")
    check(os.path.exists(P.once_path("night-probe")), "тревога night-probe не отмечена")
    check(run(e2, hm("23:10")) == [], "повторный зонд раньше 30 мин")
    check(len(run(e2, hm("23:31"))) == 1, "зонд не повторён через 30 мин")
    # Д2: следующий зонд освежил — тревога снята (clear_once), при новом сбое будет снова
    check(len(run(e2, hm("00:02"), fresh=True)) == 1, "зонд после сбоя не вызван")
    check(not os.path.exists(P.once_path("night-probe")), "зонд освежил снимок, а отметка тревоги night-probe осталась")
    # нет одобрения / день / свежий снимок / пропущенная ночь — запроса нет
    e3 = Env()
    _add_pack(e3, "")
    e3.resets = resets
    e3.at_line(hm("22:00") - 5 * 3600, 0)
    check(run(e3, hm("23:00")) == [], "зонд без ответа «Да» о ночи")
    e4 = Env()
    open_night(e4)
    e4.resets = resets
    e4.at_line(day("14:00") - 5 * 3600, 0)
    check(run(e4, day("14:00")) == [], "зонд днём")
    e5 = Env()
    open_night(e5)
    e5.resets = resets
    e5.at_line(hm("23:00") - 600, 0)
    check(run(e5, hm("23:00")) == [], "зонд при свежем снимке")
    e8 = Env()
    open_night(e8)
    e8.resets = resets
    e8.at_line(hm("22:00") - 5 * 3600, 0)
    check(run(e8, hm("22:10")) == [] and len(run(e8, hm("22:31"))) == 1, "зонд раньше чем за 30 мин до начала ночи или не за 30 мин")
    e6 = Env()
    open_night(e6)
    st = e6.state_of()
    st["skipped"] = "x"
    json.dump(st, open(os.path.join(e6.state, "night", EVENING.isoformat() + ".json"), "w"))
    e6.resets = resets
    e6.at_line(hm("22:00") - 5 * 3600, 0)
    check(run(e6, hm("23:00")) == [], "зонд для пропущенной ночи")
    # Д1: ночь закрыта (бюджет вышел) — зонда нет
    e9 = Env()
    open_night(e9)
    st = e9.state_of()
    st["closed"] = True
    json.dump(st, open(os.path.join(e9.state, "night", EVENING.isoformat() + ".json"), "w"))
    e9.resets = resets
    e9.at_line(hm("22:00") - 5 * 3600, 0)
    check(run(e9, hm("23:00")) == [], "зонд для закрытой ночи")
    # снимка нет вовсе при одобренной ночи — тоже зонд
    e7 = Env()
    open_night(e7)
    for f in os.listdir(e7.sl):
        os.unlink(os.path.join(e7.sl, f))
    check(len(run(e7, hm("23:00"))) == 1, "снимка нет — зонда нет")


def test_probe_parse_save_0459():
    """Разбор настоящего события зонда и запись снимка в формате строки статуса; кривое и лишнее не пишется."""
    got = N.probe_parse(REAL_EVENT)
    check(got == {"five_hour": (10.0, 1793635800), "seven_day": (35.0, 1793941200)}, f"разбор настоящего события: {got}")
    one = REAL_EVENT.splitlines()[1]
    check(N.probe_parse("не json\n" + one + "\n{оборвано") == got, "мусор вокруг события мешает разбору")
    newer = one.replace('"utilization":0.35', '"utilization":0.3579')  # последнее событие побеждает; сотые, как pct2
    check(N.probe_parse(one + "\n" + newer)["seven_day"][0] == 35.79, f"последнее событие: {N.probe_parse(one + chr(10) + newer)}")
    for bad in ("", "{}", REAL_EVENT.splitlines()[0], one.replace('"unifiedWindows"', '"x"'),
                one.replace('"utilization":0.35', '"utilization":35'),
                one.replace('"utilization":0.35', '"utilization":"0.35"'),
                one.replace('"utilization":0.35', '"utilization":true'),
                one.replace('"resetsAt":1793941200', '"resetsAt":null')):
        g = N.probe_parse(bad)
        check("seven_day" not in g, f"кривое событие принято: {bad[:60]!r} → {g}")
    check(N.probe_parse(one.replace('"utilization":0.35', '"utilization":35')).get("five_hour") == (10.0, 1793635800),
          "неверное окно испортило соседнее")
    e = Env()
    t = hm("23:00")
    saved = N.probe_save({"five_hour": (10.0, int(t) + 3600), "seven_day": (35.5, int(t) + 86400)}, t)
    check(saved == ["five_hour", "seven_day"], f"записано: {saved}")
    check(open(os.path.join(e.sl, "seven-day")).read() == f"35.5 {int(t) + 86400} {int(t)}\n"
          and open(os.path.join(e.sl, "five-hour")).read() == f"10 {int(t) + 3600} {int(t)}\n", "формат файлов снимка")
    check(sorted(os.listdir(e.sl)) == ["five-hour", "seven-day"], f"остались временные файлы: {os.listdir(e.sl)}")
    check(N.probe_save({"seven_day": (35.0, int(t) - 1)}, t) == []
          and open(os.path.join(e.sl, "seven-day")).read().startswith("35.5"), "сброс в прошлом записан")
    check(N.snapshot()["week"][:2] == (35.5, float(int(t) + 86400)), f"snapshot() не читает записанное: {N.snapshot()}")
    # настоящий probe_run при PANTHEON_DRYRUN=1 claude не зовёт: код 127 и пусто
    os.environ["PANTHEON_DRYRUN"] = "1"
    try:
        check(_REAL_PROBE_RUN() == (127, ""), "probe_run в DRYRUN позвал claude")
    finally:
        os.environ.pop("PANTHEON_DRYRUN", None)


def test_old_card_leaves_board_0459():
    """Закрытая проходом карточка вопроса о ночи (до выпуска): статус dropped, вопрос и варианты сняты — на доске в
    «Ждёт вас» её нет (раньше: проверить при пробном прогоне, metis-0195)."""
    e = Env()
    e.resets = hm("22:00") + 3 * 86400
    T = P.tasks_mod()
    tid, _ = T.task_new(e.pantheon, hm("22:00"), "inbox", "Запустить сегодня на ночь выполнение задач?", owner="zeus",
                        status="waiting", waiting_on="human", actor="плановый проход",
                        question="Запустить ночь?", why="Ночь по расписанию", options=["Да — запустить", "Нет — пропустить"])
    before = e.cards()[tid]
    check(before.get("question") and before.get("options"), f"заготовка карточки без вопроса: {before}")
    os.makedirs(os.path.join(e.state, "night"), exist_ok=True)
    json.dump({"card_id": tid, "card_at": hm("22:00")},
              open(os.path.join(e.state, "night", EVENING.isoformat() + ".json"), "w"))
    e.at_line(hm("22:05"), 0)
    e.watch(hm("22:05"))
    after = e.cards()[tid]
    check(after["status"] == "dropped" and not after.get("question") and not after.get("options")
          and after.get("waiting_on") is None, f"карточка осталась с вопросом и вариантами: {after}")
    waiting = [i for i, h in e.cards().items() if h.get("status") == "waiting" and h.get("waiting_on") == "human"]
    check(tid not in waiting, f"карточка ночи в «Ждёт вас»: {waiting}")


def test_night_declined_no_repeat_0392():
    """metis-0392: владелец ответил «Нет» на вопрос о ночи в окне Зевса (22:16) — вечером он больше не спрашивается: проходы
    каждые 5 минут до 23:30 не заводят ни карточку «ночь?», ни уведомление, ни строки о ночи (с 28.10 фиксированного вопроса
    нет, ночь — только по ответу на вопрос о пачке; «Нет» разобран один раз, answers_seen). Слово «Да» позже — по-прежнему открывает ночь по пачке."""
    e = _pack_env(start_line="")
    night_yes(e, hm("22:16"), answer="Нет")
    t = hm("22:20")
    while t <= hm("23:30"):
        e.at_line(t, 0)
        e.watch(t)
        t += 300
    check(not e.cards(), f"0392: после «Нет» вопрос повторён карточкой: {e.cards()}")
    check(not e.sent() and "не исполняю" not in e.alerts() and "одобрена" not in e.alerts(),
          f"0392: после «Нет» уведомление/строка: {e.sent()} {e.alerts()}")
    st = N.load(EVENING)
    check(st["answer"] is None and not st.get("opened_at") and not st.get("packs") and len(st["answers_seen"]) == 1,
          f"0392: ночь после «Нет»: {st}")
    # «Да» после «Нет» (передумал) открывает ночь по пачке
    night_yes(e, hm("23:40"))
    e.at_line(hm("23:45"), 0)
    e.watch(hm("23:45"))
    st = N.load(EVENING)
    check(st["answer"] == "да" and st.get("opened_at") and len(st["answers_seen"]) == 2, f"0392: «Да» после «Нет»: {st}")


def test_limits_allow_1124():
    """metis-1124: [limits.allow] pct + until — внутри окна и ниже pct красная и жёлтая зоны запуск не держат; на pct — стоп,
    как потолок; после until — прежняя зона; кривая запись не действует и названа пометкой; строка в status."""
    base = 'primary_host = "mac-a"\n'
    allow = '[limits.allow]\npct = 30\nuntil = "2026-10-15 15:00"\ndecision = "owner-word-ref"\n'
    t, late = day("14:00"), day("16:00")
    resets = t + 6 * 86400  # линия ≈ 14 %

    def gate_at(e, now, over):
        e.at_line(now, over, resets=resets)
        return N.gate("autostart", now, heavy=0)

    # без записи: красная (над линией 10 п.п.) и жёлтая (3 п.п.) днём держат
    e0 = Env(base)
    ok, why = gate_at(e0, t, 10)
    check(not ok and "красная" in why, f"1124: красная без записи: {ok} {why}")
    ok, why = gate_at(e0, t, 3)
    check(not ok and "жёлтая" in why, f"1124: жёлтая без записи: {ok} {why}")
    # внутри окна и ниже pct — идёт при той же красной и жёлтой
    e = Env(base + allow)
    check(gate_at(e, t, 10) == (True, ""), f"1124: красная в окне, ниже pct: {gate_at(e, t, 10)}")
    check(gate_at(e, t, 3) == (True, ""), f"1124: жёлтая в окне, ниже pct: {gate_at(e, t, 3)}")
    check(N.measure(t)["zone"] == "green", f"1124: зона в окне: {N.measure(t)['zone']}")
    lines = N.status_lines(t)
    al = [x for x in lines if x.startswith("Разрешение до даты")]
    check(len(al) == 1 and "30 %" in al[0] and "owner-word-ref" in al[0] and "запас" in al[0], f"1124: status: {lines}")
    # на pct — стоп, как потолок (причина называет 30 %)
    ok, why = gate_at(e, t, 20)  # ≈ 34 %
    check(not ok and "30" in why and "потолок" in why, f"1124: на pct не стоп: {ok} {why}")
    check("достигнуто" in "".join(N.status_lines(t)), f"1124: status на pct: {N.status_lines(t)}")
    check(N.measure(t)["zone"] == "red", f"1124: зона на pct прежняя: {N.measure(t)['zone']}")
    line = 100.0 * (t - (resets - WEEK)) / WEEK
    ok, why = gate_at(e, t, 30.0 - line)  # ровно pct
    check(not ok and N.measure(t)["zone"] == "red", f"1124: ровно на pct: {ok} {why} {N.measure(t)['zone']}")
    # после until — прежняя зона, строка говорит почему
    ok, why = gate_at(e, late, 10)
    check(not ok and "красная" in why, f"1124: после until: {ok} {why}")
    check(N.measure(late)["zone"] == "red", f"1124: зона после until: {N.measure(late)['zone']}")
    check(any("не действует — истекло" in x for x in N.status_lines(late)), f"1124: status после until: {N.status_lines(late)}")
    # owner_cap не тронут: 95 держит своё и под разрешением, потолок ниже разрешения — первым
    e2 = Env(base + allow + '[limits.owner_cap]\npct = 25\ndecision = "zeus-x"\n')
    ok, why = gate_at(e2, t, 10)  # ≈ 24 % < 25 — идёт
    check(ok, f"1124: ниже потолка 25: {why}")
    ok, why = gate_at(e2, t, 12)  # ≈ 26 % ≥ 25 — стоп по потолку владельца
    check(not ok and "25" in why, f"1124: потолок ниже разрешения: {ok} {why}")
    # кривые записи: не действуют (зона прежняя), пометка в status
    bad = (("pct = 0\nuntil = \"2026-10-15 15:00\"\n", "pct"), ("pct = 130\nuntil = \"2026-10-15 15:00\"\n", "pct"),
           ("pct = \"30\"\nuntil = \"2026-10-15 15:00\"\n", "pct"), ("pct = true\nuntil = \"2026-10-15 15:00\"\n", "pct"),
           ("pct = 30\n", "нет until"), ("pct = 30\nuntil = \"когда-нибудь\"\n", "не дата"))
    for body, why_part in bad:
        eb = Env(base + "[limits.allow]\n" + body)
        ok, why = gate_at(eb, t, 10)
        st = "\n".join(N.status_lines(t))
        check(not ok and "красная" in why, f"1124: кривая запись {body!r} действует: {ok} {why}")
        check("не действует — запись [limits.allow] не разобрана" in st and why_part in st, f"1124: пометка {body!r}: {st}")
        eb.watch(t)
        check("разрешение до даты не действует" in eb.alerts(), f"1124: тревога {body!r}: {eb.alerts()}")
    # без записи строки нет
    e0 = Env(base)
    e0.at_line(t, 10, resets=resets)
    check(not [x for x in N.status_lines(t) if "Разрешение" in x], f"1124: строка без записи: {N.status_lines(t)}")


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
