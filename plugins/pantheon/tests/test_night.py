#!/usr/bin/env python3
"""Синтетические тесты темпа недельного лимита и ночного цикла (lib/night.py; metis-0127, 0128, 0129).

Запуск: python3 -I plugins/pantheon/tests/test_night.py  (код выхода 0 — все прошли)
pantheon.py загружается в этом же процессе; каждый тест — свои временные HOME, PANTHEON и STATE (константы модуля
подменяются), снимок строки статуса пишется в HOME/.local/state/claude-statusline. Время — местное: дата вечера
VEVENING, часы «ЧЧ:ММ» считаются от неё.
"""
import json
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # pantheon.py — только на Python 3.11+ (tomllib)
if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)])
import tempfile
import atexit as _atexit
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="night-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)
import importlib.util
import time
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
WEEK = 7 * 86400
EVENING = date(2026, 10, 15)  # четверг
FAILS = []

for k in ("PANTHEON_FAKE_LIMIT", "PANTHEON_DRYRUN", "PANTHEON_NO_NOTIFY"):
    os.environ.pop(k, None)
os.environ.update({"PANTHEON_HOST": "mac-a", "PANTHEON_FAKE_IDLE": "0", "HOME": os.path.join(_ROOT, "home0"),
                   "PANTHEON_HOME": os.path.join(_ROOT, "home0", "ai", "pantheon"),
                   "PANTHEON_STATE": os.path.join(_ROOT, "state0")})
_spec = importlib.util.spec_from_file_location("pantheon_night_test", os.path.join(LIB, "pantheon.py"))
P = importlib.util.module_from_spec(_spec)
sys.modules["pantheon_night_test"] = P
_spec.loader.exec_module(P)
N = P.night_mod()


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

    def board_answer(self, cid, answer, t, question=None):
        rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)), "kind": "answer", "id": cid,
               "answer": answer, "question": question or N.TITLE}
        with open(os.path.join(self.state, "owner-log", "board.jsonl"), "a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def zeus_answer(self, cid, answer, t):
        with open(os.path.join(self.state, "owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
            fh.write(f"\n## {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))} · окно вопросов\n\n"
                     f"вопрос: [{cid}] {N.TITLE}\nответ: {answer}\n")


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
    e3 = Env()
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


def test_evening_question():
    e = Env()
    t = hm("21:55")
    e.at_line(t, 0)
    e.watch(t)
    check(not e.cards() and not e.sent(), "до 22:00 вопрос задан")
    e.at_line(hm("22:00"), 0)
    e.watch(hm("22:00"))
    cards = e.cards()
    check(len(cards) == 1, f"22:00 — карточек {len(cards)}")
    cid, h = next(iter(cards.items()))
    T = P.tasks_mod()
    check(T.label_of(h) == T.HUMAN_WAIT, f"карточка не в «Нужен ответ»: {T.label_of(h)}")
    check(h["title"] == N.TITLE and h["owner"] == "zeus" and h["question"] == N.TITLE, f"шапка: {h}")
    check(h["options"] == ["Да — открыть ночь: бюджет 3 % недели, работа до 08:00", "Нет — ночь пропустить"],
          f"варианты: {h['options']}")
    check(h.get("why") and h.get("recommend") and h.get("if_no_answer"), "нет why/recommend/if_no_answer")
    check(len(e.sent()) == 1 and cid in e.sent()[0], f"22:00 — уведомлений {e.sent()}")
    st = e.state_of()
    check(st["card_id"] == cid and len(st["asked_at"]) == 1, f"состояние: {st}")
    e.watch(hm("22:30"))
    check(len(e.sent()) == 1, "22:30 — лишнее уведомление")
    for i, x in enumerate(("23:00", "23:30"), start=2):
        e.at_line(hm(x), 0)
        e.watch(hm(x))
        check(len(e.cards()) == 1, f"{x} — вторая карточка")
        check(len(e.sent()) == i, f"{x} — повтор не ушёл: {len(e.sent())}")
    e.watch(hm("23:45"))
    check(len(e.sent()) == 3, "23:45 — лишний повтор")
    check(not N.gate("autostart", hm("23:45"), heavy=0)[0], "ночь без ответа — gate пустил")
    e.at_line(hm("00:00"), 0)
    e.watch(hm("00:00"))
    st = e.state_of()
    check(st["skipped"] == "нет ответа к 00:00", f"00:00 без ответа — не пропущена: {st}")
    check("пропущена: нет ответа к 00:00" in e.alerts(), "нет строки о пропуске в тревогах")
    check(e.cards()[cid]["status"] == "dropped", f"карточка не закрыта: {e.cards()[cid]['status']}")
    check("Ночь: пропущена (нет ответа к 00:00)" in N.status_lines(hm("00:10")), N.status_lines(hm("00:10")))
    ok, why = N.gate("autostart", hm("00:10"), heavy=0)
    check(not ok and "пропущена" in why, f"пропущенная ночь — gate: {ok} {why}")
    # поздний ответ после 00:00 ночь не открывает
    e.board_answer(cid, h["options"][0], hm("00:05"))
    e.watch(hm("00:15"))
    check(not e.state_of().get("opened_at"), "ответ после 00:00 открыл ночь")


def test_missed_slots_no_burst():
    """Mac проснулся в 23:40: карточка и одно уведомление, без пачки повторов."""
    e = Env()
    e.at_line(hm("23:40"), 0)
    e.watch(hm("23:40"))
    check(len(e.cards()) == 1 and len(e.sent()) == 1, f"23:40 — {len(e.cards())} карточек, {len(e.sent())} уведомлений")
    e.watch(hm("23:50"))
    check(len(e.sent()) == 1, "23:50 — повтор за прошедший слот")


def open_night(e, answer_at, over=0.0, how="board"):
    e.resets = hm("22:00") + 3 * 86400
    e.at_line(hm("22:00"), over)
    e.watch(hm("22:00"))
    cid, h = next(iter(e.cards().items()))
    if how == "board":
        e.board_answer(cid, h["options"][0], answer_at)
    else:
        e.zeus_answer(cid, h["options"][0], answer_at)
    return cid, h


def test_answer_opens_night():
    e = Env()
    cid, h = open_night(e, hm("23:10"))
    e.at_line(hm("23:15"), 0)
    e.watch(hm("23:15"))
    st = e.state_of()
    check(st["answer"] == "да" and st["opened_at"] == hm("23:10"), f"ответ в 23:10 — opened_at {st.get('opened_at')}")
    check(st["budget_pct"] == 3 and abs(st["start_pct"] - N.measure(hm("23:15"))["used"]) < 1e-9, f"бюджет: {st}")
    check(e.cards()[cid]["status"] == "done", "карточка с ответом «Да» не закрыта")
    check(N.gate("autostart", hm("23:20"), heavy=0) == (True, ""), f"открытая ночь — gate: {N.gate('autostart', hm('23:20'), heavy=0)}")
    check(N.gate("respawn", hm("23:20")) == (True, ""), "открытая ночь — respawn не пустил")
    lines = N.status_lines(hm("23:20"))
    check(lines[1] == "Ночь: открыта с 23:10, потрачено 0 из 3 %", f"строка ночи: {lines[1]}")
    check("открыта с 23:10" in e.alerts(), "нет строки об открытии в тревогах")
    e.watch(hm("23:30"))
    check(len(e.sent()) == 1, f"после ответа — повтор вопроса: {e.sent()}")
    # ответ до 23:00 открывает ночь с 23:00
    e2 = Env()
    open_night(e2, hm("22:30"))
    e2.at_line(hm("22:40"), 0)
    e2.watch(hm("22:40"))
    check(not e2.state_of().get("opened_at"), "ночь открылась до 23:00")
    e2.at_line(hm("23:02"), 0)
    e2.watch(hm("23:02"))
    check(e2.state_of()["opened_at"] == hm("23:00"), f"ответ в 22:30 — opened_at {e2.state_of().get('opened_at')}")
    # ответ окном вопросов Зевса
    e3 = Env()
    open_night(e3, hm("23:20"), how="zeus")
    e3.at_line(hm("23:25"), 0)
    e3.watch(hm("23:25"))
    check(e3.state_of().get("opened_at") == hm("23:20"), f"ответ Зевсу — {e3.state_of()}")


def test_answer_no_and_file_only():
    e = Env()
    e.at_line(hm("22:00"), 0)
    e.watch(hm("22:00"))
    cid, h = next(iter(e.cards().items()))
    e.board_answer(cid, h["options"][1], hm("22:20"))
    e.watch(hm("22:25"))
    st = e.state_of()
    check(st["skipped"] == "ответ «Нет»" and st["answer"] == "нет", f"«Нет» — не пропущена: {st}")
    check(e.cards()[cid]["status"] == "dropped", "карточка с «Нет» не закрыта")
    e.watch(hm("23:00"))
    check(len(e.sent()) == 1, "после «Нет» — повтор вопроса")
    # ответ только в файле задачи — не ответ
    e2 = Env()
    e2.at_line(hm("22:00"), 0)
    e2.watch(hm("22:00"))
    cid, h = next(iter(e2.cards().items()))
    P.tasks_mod().task_set(e2.pantheon, hm("22:10"), cid, {"answer": h["options"][0]}, actor="агент")
    e2.at_line(hm("23:15"), 0)
    e2.watch(hm("23:15"))
    st = e2.state_of()
    check(st["answer"] is None and not st.get("opened_at"), f"ответ в файле задачи засчитан: {st}")
    # ответ в журнале на другой вопрос или чужой вариант — не ответ
    e2.board_answer(cid, h["options"][0], hm("23:16"), question="Другой вопрос?")
    e2.board_answer(cid, "Да, конечно", hm("23:17"))
    e2.watch(hm("23:20"))
    check(e2.state_of()["answer"] is None, "ответ на чужой вопрос или не из вариантов засчитан")
    # строка Зевсу без пометки «окно вопросов» — не ответ
    with open(os.path.join(e2.state, "owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
        fh.write(f"\n## {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(hm('23:21')))}\n\n"
                 f"вопрос: [{cid}] {N.TITLE}\nответ: Да\n")
    e2.watch(hm("23:25"))
    check(e2.state_of()["answer"] is None, "строка Зевсу без «окно вопросов» засчитана")
    e2.at_line(hm("00:00"), 0)
    e2.watch(hm("00:00"))
    check(e2.state_of()["skipped"], "без ответа из журнала ночь не пропущена")


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
    check(any(ln.startswith("Ночь 15.10: открыта с 23:05, потрачено 3 из 3 %") and "тревоги: 50 %, 80 %, 100 %" in ln
              for ln in rep), f"сводка: {rep}")


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
    check(lines[1].startswith("Ночь: не открыта — вопрос в 22:00") or lines[1].startswith("Ночь:"), lines[1])
    e.snap(t - 45 * 60, 41.0, resets)
    check(N.status_lines(t)[2] == "лимит неизвестен (45 мин)", N.status_lines(t)[2])
    check(N.num(1.25) in ("1,2", "1,3") and N.num(-2) == "−2" and N.signed(2.1) == "+2,1", "формат чисел")
    # CLI: pantheon night, pantheon night report, справка, pantheon status
    e.snap(t - 300, 41.0, resets)
    env = {"PATH": os.environ["PATH"], "HOME": e.home, "PANTHEON_HOME": e.pantheon, "PANTHEON_STATE": e.state,
           "PANTHEON_NOW": str(t), "PANTHEON_HOST": "mac-a", "PANTHEON_NO_NOTIFY": "1", "TMPDIR": _ROOT}
    run = lambda *a: subprocess.run([PY311, "-I", os.path.join(LIB, "pantheon.py"), *a], env=env,  # noqa: E731
                                    capture_output=True, text=True, timeout=60)
    r = run("night")
    check(r.returncode == 0 and "Неделя: 41 % · линия 43 %" in r.stdout, f"pantheon night: {r.stdout} {r.stderr[-300:]}")
    r = run("night", "report")
    check(r.returncode == 0 and r.stdout.startswith("Лимит\n") and "Сброс недели: пт 10:00" in r.stdout
          and "Ночь " in r.stdout, f"pantheon night report: {r.stdout} {r.stderr[-300:]}")
    check(run("night", "bogus").returncode == 2, "pantheon night bogus — не код 2")
    check("pantheon night [status|report]" in run("help").stdout, "в справке нет pantheon night")
    r = run("status")
    check("Лимит и ночь" in r.stdout and "Неделя: 41 %" in r.stdout, f"pantheon status без раздела: {r.stdout[-800:]}")


def test_py39_compile():
    py39 = "/usr/bin/python3"
    if not os.path.exists(py39):
        print("пропуск: нет /usr/bin/python3")
        return
    r = subprocess.run([py39, "-I", "-c", "import sys; compile(open(sys.argv[1], encoding='utf-8').read(), "
                        "sys.argv[1], 'exec'); print(sys.version_info[:2])", os.path.join(LIB, "night.py")],
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, f"night.py не компилируется на {py39}: {r.stderr[-400:]}")


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
