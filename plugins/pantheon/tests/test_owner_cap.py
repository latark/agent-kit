#!/usr/bin/env python3
"""Недельный потолок владельца ([limits.owner_cap], metis-0403; раньше дневной metis-0275).

Потолок только сужает: достигнут (неделя ≥ pct) — autostart, wake и respawn отказаны днём и ночью, новые субагенты из
окон координаторов и штаба — тоже (хук `pantheon night agent-gate`); задачи `claude -p` тика ждут, запуск по ответу в
окне вопросов отказан (metis-0444; ручные start и wake — test_start.py); ниже потолка — поведение как без него (жёлтая
и красная зона, hard_pct, ночь). При достижении — одна тревога и одна карточка Зевсу на неделю и pct.

Запуск: python3 -I plugins/pantheon/tests/test_owner_cap.py  (код выхода 0 — все прошли)
Помощники (Env, hm, check) — из test_night.py.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402
import json
import subprocess
from datetime import datetime, timedelta

import test_night as TN

check, hm, Env, N, P, EVENING, WEEK = TN.check, TN.hm, TN.Env, TN.N, TN.P, TN.EVENING, TN.WEEK
T = hm("12:00", EVENING - timedelta(days=1))  # среда 14.10, 12:00 — день
TN_NIGHT = hm("23:30", EVENING - timedelta(days=1))  # та же неделя, ночь
DAY = datetime.fromtimestamp(T).date()
CAP50 = '[limits.owner_cap]\npct = 50\ndecision = "zeus-limit-budget"\n'


def env(used, line, sec=CAP50, t=T, host="mac-a"):
    """Окружение: неделя used % при линии line % в момент t (сброс подобран под линию)."""
    e = Env(f'primary_host = "{host}"\n' + sec)
    e.resets = t + WEEK * (1 - line / 100.0)
    e.snap(t, used, e.resets)
    return e


def cap_alerts(e):
    return e.alerts().count("потолок владельца")


def with_role(role, fn):
    old = os.environ.get("PANTHEON_ROLE")
    if role is None:
        os.environ.pop("PANTHEON_ROLE", None)
    else:
        os.environ["PANTHEON_ROLE"] = role
    try:
        return fn()
    finally:
        if old is None:
            os.environ.pop("PANTHEON_ROLE", None)
        else:
            os.environ["PANTHEON_ROLE"] = old


def test_criterion_cap50_week50():
    """Критерий metis-0403: потолок 50, неделя 50 → autostart, wake, respawn и Agent из окна координатора отказаны с
    причиной; карточка одна, тревога одна."""
    e = env(50.0, 50.0, sec="")  # зелёная зона; без потолка всё открыто
    for kind in ("autostart", "wake", "respawn"):
        ok, why = N.gate(kind, T, heavy=0)
        check(ok, f"без потолка, неделя 50 в зелёной, {kind}: {ok} {why}")
    check(with_role("domain-coordinator", lambda: N.agent_gate(T)) is None, "без потолка agent_gate отказал")
    e = env(50.0, 50.0)
    check(N.measure(T)["zone"] == "green", "зона не зелёная")
    for _ in range(3):
        for kind in ("autostart", "wake", "respawn"):
            ok, why = N.gate(kind, T, heavy=0)
            check(not ok and "потолок владельца 50 %" in why and "неделя 50 %" in why and "zeus-limit-budget" in why,
                  f"потолок 50, неделя 50, {kind}: {ok} {why}")
        e.watch(T + 60)
    # ночью тоже: потолок не ждёт открытой ночи
    check(N.night_of(TN_NIGHT, N.config()) is not None, "23:30 не ночь")
    e.snap(TN_NIGHT, 50.0, e.resets)
    for kind in ("autostart", "wake", "respawn"):
        ok, why = N.gate(kind, TN_NIGHT, heavy=0)
        check(not ok and "потолок владельца" in why, f"ночь, потолок достигнут, {kind}: {ok} {why}")
    # окно координатора, мастерская и штаб (metis-0444) — отказ с причиной; окна задач и терминал — нет
    for role in ("domain-coordinator", "workshop", "hq"):
        why = with_role(role, lambda: N.agent_gate(TN_NIGHT))  # noqa: B023
        check(why and "потолок владельца 50 %" in why and "не запускай" in why, f"agent_gate {role}: {why!r}")
    hq_why = with_role("hq", lambda: N.agent_gate(TN_NIGHT)) or ""
    check(hq_why.startswith("Пантеон: недельный потолок") and "Субагентов не запускай" in hq_why
          and "отвечай владельцу сам" in hq_why and "остановилась" not in hq_why, f"agent_gate hq: {hq_why!r}")
    for role in ("job", "clio", "hestia", "", None):
        check(with_role(role, lambda: N.agent_gate(TN_NIGHT)) is None, f"agent_gate отказал роли {role!r}")
    cards = e.cards()
    check(len(cards) == 1, f"карточек должна быть одна: {sorted(cards)}")
    h = next(iter(cards.values()), {})
    body = json.dumps(h, ensure_ascii=False)
    check(h.get("owner") == "zeus" and h.get("status") == "waiting" and "поднять потолок до 60 %" in str(h.get("title"))
          and "[zeus-limit-budget]" in body, f"карточка: {h}")
    check(cap_alerts(e) == 1, f"тревога потолка должна быть одна: {e.alerts()!r}")
    st = json.load(open(os.path.join(e.state, "owner-cap.json")))
    check(st.get("card_id") in cards, f"owner-cap.json: {st}")
    # новая неделя (другой сброс) — новый вопрос; та же неделя, другой pct — тоже
    e.snap(T + WEEK, 50.0, e.resets + WEEK)
    N.gate("wake", T + WEEK, heavy=0)
    check(len(e.cards()) == 2 and cap_alerts(e) == 2, f"новая неделя без нового вопроса: {len(e.cards())}")


def test_watch_alone_notices():
    """Плановый проход сам заводит карточку и тревогу при достижении, без попытки запуска; повтор — молчит."""
    e = env(50.0, 50.0)
    for k in range(3):
        e.watch(T + 60 * k)
    check(len(e.cards()) == 1 and cap_alerts(e) == 1, f"watch: карточек {len(e.cards())}, тревог {cap_alerts(e)}")


def test_cap_reached_dryrun_and_not_primary():
    """Пробный запуск и не главный Mac: отказ есть, карточки и тревоги нет."""
    e = env(55.0, 54.0)
    os.environ["PANTHEON_DRYRUN"] = "1"
    try:
        ok, why = N.gate("wake", T, heavy=0)
    finally:
        os.environ.pop("PANTHEON_DRYRUN", None)
    check(not ok and "потолок" in why and not e.cards() and cap_alerts(e) == 0, f"пробный запуск: {ok} {e.cards()}")
    e = env(55.0, 54.0, host="mac-b")
    ok, why = N.gate("autostart", T, heavy=0)
    check(not ok and "потолок" in why and not e.cards(), f"не главный Mac: {ok} {why} {e.cards()}")


def test_below_cap_yellow_as_without():
    """Критерий metis-0403: неделя 49 при потолке 50 в жёлтой зоне — как без потолка (днём и ночью)."""
    for t in (T, TN_NIGHT):
        e = env(49.0, 46.0, sec="", t=t)
        check(N.measure(t)["zone"] == "yellow", f"зона не жёлтая: {N.measure(t)}")
        base = {k: N.gate(k, t, heavy=0) for k in ("autostart", "wake", "respawn")}
        e = env(49.0, 46.0, t=t)
        got = {k: N.gate(k, t, heavy=0) for k in ("autostart", "wake", "respawn")}
        check(got == base, f"49 в жёлтой с потолком 50 ≠ без потолка: {got} vs {base}")
        check(not e.cards() and cap_alerts(e) == 0, "ниже потолка — карточка или тревога")
        check(with_role("domain-coordinator", lambda: N.agent_gate(t)) is None, "ниже потолка agent_gate отказал")
    check(not base["wake"][0] or N.night_of(TN_NIGHT, N.config()) is not None, "проверка жёлтой без смысла")
    e = env(49.0, 46.0, sec="")
    check(not N.gate("wake", T, heavy=0)[0] and "жёлтая зона" in N.gate("wake", T, heavy=0)[1], "жёлтая днём открыта")


def test_cap_only_narrows():
    """Потолок выше расхода не снимает красную и жёлтую зону, heavy_max и hard_pct (дневной metis-0275 снимал)."""
    e = env(40.0, 30.0, sec='[limits.owner_cap]\npct = 90\n')  # красная: запас +10
    for kind in ("wake", "autostart", "respawn"):
        ok, why = N.gate(kind, T, heavy=0)
        check(not ok and "красная зона" in why, f"потолок 90 открыл красную, {kind}: {ok} {why}")
    e = env(40.0, 37.0, sec=f'[limits.owner_cap]\ndate = "{DAY}"\npct = 90\n')  # жёлтая, старый вид записи
    for kind in ("wake", "autostart"):
        ok, why = N.gate(kind, T, heavy=0)
        check(not ok and "жёлтая зона" in why, f"дневной потолок открыл жёлтую, {kind}: {ok} {why}")
    e = env(40.0, 40.0, sec='[limits.owner_cap]\npct = 90\n')
    check(N.gate("wake", T, heavy=0)[0], "зелёная ниже потолка закрыта")
    check(not N.gate("autostart", T, heavy=2)[0], "потолок отменил heavy_max")
    e = env(86.0, 85.0, sec='[limits.owner_cap]\npct = 99\n')
    ok, why = N.gate("wake", T, heavy=0)
    check(not ok and "красная зона" in why, f"hard_pct отменён потолком: {ok} {why}")


def test_cap_boundary_and_stale_snapshot():
    """Граница: 49,9 — не достигнут, 50 — достигнут. Старый снимок ≥ потолка — достигнут (расход не убывает); новая
    неделя (сброс в прошлом) — не достигнут."""
    e = env(49.9, 49.0)
    check(N.gate("wake", T, heavy=0)[0], "49,9 при потолке 50 закрыт")
    e = env(50.0, 49.0)
    check(not N.gate("wake", T, heavy=0)[0], "50 при потолке 50 открыт")
    e = env(52.0, 50.0)
    e.snap(T - 3 * 3600, 52.0, e.resets)  # снимок трёхчасовой: лимит неизвестен, но потолок уже был достигнут
    ok, why = N.gate("respawn", T, heavy=0)
    check(not ok and "потолок владельца" in why, f"старый снимок ≥ потолка: {ok} {why}")
    check(with_role("domain-coordinator", lambda: N.agent_gate(T)) is not None, "старый снимок: agent_gate пустил")
    e = env(52.0, 50.0)
    e.snap(T - 3 * 3600, 52.0, T - 60)  # сброс прошёл после снимка — неделя новая
    ok, why = N.gate("respawn", T, heavy=0)
    check("потолок" not in why, f"сброс прошёл, а потолок держит: {ok} {why}")


def test_cap_terms():
    """Срок потолка: без срока — каждую неделю; until дата; until = "reset" с since; since в будущем; старый date."""
    d = DAY.isoformat()
    yday = (DAY - timedelta(days=1)).isoformat()
    tomorrow = (DAY + timedelta(days=1)).isoformat()
    ten = (DAY - timedelta(days=10)).isoformat()
    cases = [
        ("", True, "каждую неделю"),
        (f'until = "{tomorrow}"\n', True, "по 15.10"),
        (f'until = "{d}"\n', True, "по 14.10"),
        (f'until = "{yday}"\n', False, "истёк 13.10"),
        (f'until = {yday}\n', False, "истёк 13.10"),
        (f'until = "reset"\nsince = "{d}"\n', True, "до сброса недели"),
        (f'until = "reset"\nsince = "{d} 09:30"\n', True, "до сброса недели"),
        (f'until = "reset"\nsince = {d}T09:30:00\n', True, "до сброса недели"),
        (f'until = "reset"\nsince = "{ten}"\n', False, "истёк"),
        ('until = "reset"\n', False, "без since"),
        (f'since = "{tomorrow}"\n', False, "действует с"),
        (f'since = "{d} 13:00"\n', False, "действует с"),
        (f'date = "{d}"\n', True, "на 14.10"),
        (f'date = {d}\n', True, "на 14.10"),
        (f'date = "{yday}"\n', False, "не сегодня"),
        ('until = "завтра"\n', False, "не разобрана"),
        ('since = "вчера"\n', False, "не разобрана"),
    ]
    for extra, on, word in cases:
        e = env(50.0, 49.0, sec=CAP50 + extra)
        cap, note = N.cap_read(T)
        check(bool(cap) == on and word in ((cap or {}).get("scope", "") + note), f"срок {extra!r}: {cap} {note!r}")
        ok, why = N.gate("wake", T, heavy=0)
        check(ok == (not on), f"срок {extra!r}: gate {ok} {why}")


def test_cap_since_reset_day():
    """since — дата дня сброса, сброс позже в тот же день: до сброса потолок держит, после сброса — истёк."""
    t2 = hm("19:00", DAY)  # новая неделя уже началась в 18:00
    # сброс 14.10 18:00; в 19:00 следующий — 21.10 18:00. Дата — по конец суток: запись после сброса держит до
    # следующего; время 00:00 — до сброса дня, после него истёк
    for t, used, line, since, on in ((T, 50.0, 96.43, f'"{DAY.isoformat()}"', True),
                                     (T, 50.0, 96.43, f'"{DAY.isoformat()} 00:00"', True),
                                     (t2, 0.2, 0.6, f'"{DAY.isoformat()}"', True),
                                     (t2, 0.2, 0.6, f'"{DAY.isoformat()} 00:00"', False)):
        e = env(used, line, sec=CAP50 + f'until = "reset"\nsince = {since}\n', t=t)
        cap, note = N.cap_read(t)
        check(bool(cap) == on and (on or "истёк" in note), f"since {since} в {t}: {cap} {note!r}")
        ok, why = N.gate("wake", t, heavy=0)
        check(ok == (not (on and used >= 50.0)), f"since {since} в {t}: gate {ok} {why}")  # новая неделя — потолок не достигнут


def test_cap_since_date_after_reset_hour():
    """Argus B: потолок 25, неделя 30, сброс был сегодня в 10:00, since — дата сброса, сейчас 12:00: потолок держит
    (раньше дата считалась с 00:00 и потолок сразу «истекал»); неделей позже — истёк."""
    d = DAY.isoformat()
    e = env(30.0, 100.0 * 2 / (7 * 24), sec=CAP50.replace("50", "25") + f'until = "reset"\nsince = "{d}"\n')
    cap, note = N.cap_read(T)
    check(cap and cap["pct"] == 25.0, f"потолок не действует: {cap} {note!r}")
    check(not N.gate("wake", T, heavy=0)[0], "gate wake пропустил")
    why = with_role("domain-coordinator", lambda: N.agent_gate(T))
    check(why and "потолок владельца 25 %" in why, f"agent_gate не отказал: {why!r}")
    t3 = T + WEEK  # следующая неделя: потолок записан на ту, что кончилась
    e.snap(t3, 5.0, e.resets + WEEK)
    cap, note = N.cap_read(t3)
    check(cap is None and "истёк" in note, f"через неделю: {cap} {note!r}")


def test_cap_bad_record_alert_once():
    """Кривая или истёкшая запись — одна тревога в watch с причиной; повтор молчит; исправили — тревога снимается."""
    for sec, word in ((CAP50 + 'until = "сброс"\n', "не разобрана"),
                      (CAP50 + 'until = "reset"\nsince = "2020-01-01"\n', "истёк")):
        e = env(10.0, 10.0, sec=sec)
        for k in range(3):
            e.watch(T + 60 * k)
        al = e.alerts()
        check(al.count("потолок владельца не действует") == 1 and word in al, f"{word}: {al!r}")


def test_cap_broken_records():
    """Кривая запись — как без потолка, а status говорит почему."""
    for bad in ('[limits.owner_cap]\npct = "много"\n', '[limits.owner_cap]\ndecision = "x"\n', 'limits.owner_cap = 5\n',
                '[limits.owner_cap]\npct = true\n', '[limits.owner_cap]\npct = 0\n', '[limits.owner_cap]\npct = -5\n',
                '[limits.owner_cap]\npct = 101\n', '[limits.owner_cap]\npct = nan\n', '[limits.owner_cap]\npct = inf\n',
                '[limits.owner_cap]\npct = -inf\n'):
        e = env(60.0, 59.0, sec=bad)
        check(N.owner_cap(T) is None, f"кривой потолок принят: {bad!r}")
        check(N.gate("wake", T, heavy=0)[0], f"кривой потолок закрыл: {bad!r}")
        ln = N.status_lines(T)[3]
        check(ln.startswith("Потолок владельца: не действует — запись [limits.owner_cap] не разобрана"), ln)
    e = env(60.0, 59.0, sec='[limits]\nwarn_pp = 2\n')
    check(N.owner_cap(T) is None and N.cap_read(T)[1] == "", "без раздела — пометка")


def test_status_line():
    """`pantheon night status` и сводка: потолок и запас до него."""
    e = env(45.0, 45.0)
    lines = N.status_lines(T)
    check(lines[3] == "Потолок владельца: 50 % каждую неделю · решение zeus-limit-budget · запас 5 п.п.", lines[3])
    check(lines[2].startswith("Снимок лимита"), lines[2])
    check(N.cap_line(T, N.measure(T)) in N.report_lines(T), "в сводке нет потолка")
    e = env(51.0, 50.0)
    check(N.status_lines(T)[3] == "Потолок владельца: 50 % каждую неделю · решение zeus-limit-budget · достигнут "
          "(неделя 51 %) — новые запуски и исполнители стоят", N.status_lines(T)[3])
    e = env(45.0, 45.0, sec="")
    check(N.status_lines(T)[3] == "Потолок владельца: нет", N.status_lines(T)[3])
    e = env(45.0, 45.0)
    e.snap(T, 45.0, T - 60)
    check(N.status_lines(T)[3].endswith("запас неизвестен (расхода недели нет)"), N.status_lines(T)[3])


def _cli_env(e, t, role="domain-coordinator", **kw):
    env_ = {"PATH": os.path.dirname(PY311) + ":/usr/bin:/bin", "HOME": e.home, "PANTHEON_HOME": e.pantheon,
            "PANTHEON_STATE": e.state, "PANTHEON_NOW": str(t), "PANTHEON_HOST": "mac-a", "PANTHEON_NO_NOTIFY": "1",
            "TMPDIR": e.tmp, "CLAUDE_PLUGIN_ROOT": TN.ROOT}
    if role is not None:
        env_["PANTHEON_ROLE"] = role
    if "TZ" in os.environ:
        env_["TZ"] = os.environ["TZ"]
    env_.update(kw)
    return env_


def _hook_cmd():
    h = json.load(open(os.path.join(TN.ROOT, "hooks", "hooks.json"), encoding="utf-8"))
    cmds = [x["command"] for g in h["hooks"]["PreToolUse"] if g.get("matcher") == "Agent|Task" for x in g["hooks"]]
    check(len(cmds) == 1 and "night agent-gate" in cmds[0], f"в hooks.json нет хука agent-gate на Agent|Task: {cmds}")
    return cmds[0] if cmds else "exit 0"


EVENT = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Agent",
                    "tool_input": {"subagent_type": "dev-opus", "prompt": "x"}})


def test_hook_agent_gate():
    """hooks.json: оболочка не запускает python без роли координатора и без owner_cap; с ними — `pantheon night
    agent-gate` отказывает (deny JSON) при достигнутом потолке и молчит ниже него."""
    sh = _hook_cmd()
    run = lambda env_: subprocess.run(["sh", "-c", sh], input=EVENT, env=env_, capture_output=True,  # noqa: E731
                                      text=True, timeout=60)
    # поддельный плагин: bin/pantheon только отмечает запуск
    e = env(50.0, 50.0)
    fake = os.path.join(e.tmp, "fakeplugin")
    os.makedirs(os.path.join(fake, "bin"))
    with open(os.path.join(fake, "bin", "pantheon"), "w") as fh:
        fh.write("#!/bin/sh\necho STARTED \"$@\"\n")
    os.chmod(os.path.join(fake, "bin", "pantheon"), 0o755)
    for role in ("job", "clio", "", None):
        r = run(_cli_env(e, T, role=role, CLAUDE_PLUGIN_ROOT=fake))
        check(r.returncode == 0 and r.stdout == "", f"роль {role!r}: хук запустил pantheon: {r.stdout!r}")
    for role in ("domain-coordinator", "workshop", "hq"):
        r = run(_cli_env(e, T, role=role, CLAUDE_PLUGIN_ROOT=fake))
        check(r.stdout.strip() == "STARTED night agent-gate", f"{role} с owner_cap: {r.stdout!r} {r.stderr!r}")
    e2 = env(50.0, 50.0, sec="")
    r = run(_cli_env(e2, T, CLAUDE_PLUGIN_ROOT=fake))
    check(r.returncode == 0 and r.stdout == "", f"без owner_cap хук запустил pantheon: {r.stdout!r}")
    r = run(_cli_env(e2, T, CLAUDE_PLUGIN_ROOT=fake, PANTHEON_HOME=os.path.join(e2.tmp, "нет")))
    check(r.returncode == 0 and r.stdout == "", f"без schedule.toml хук запустил pantheon: {r.stdout!r}")
    # настоящий плагин: достигнут — отказ с причиной, код 0
    for role in ("domain-coordinator", "workshop", "hq"):
        r = run(_cli_env(e, T, role=role))
        try:
            out = json.loads(r.stdout)["hookSpecificOutput"]
        except (ValueError, KeyError, TypeError):
            out = {}
        check(r.returncode == 0 and out.get("permissionDecision") == "deny" and out.get("hookEventName") == "PreToolUse"
              and "потолок владельца 50 %" in out.get("permissionDecisionReason", ""),
              f"хук {role}, потолок достигнут: {r.returncode} {r.stdout!r} {r.stderr[-300:]!r}")
    check(not e.cards(), "хук окна завёл карточку (её заводит плановый проход)")
    e3 = env(49.0, 49.0)
    r = run(_cli_env(e3, T))
    check(r.returncode == 0 and r.stdout == "", f"ниже потолка хук отказал: {r.stdout!r} {r.stderr[-300:]!r}")
    # сбой расчёта — не отказ: код 1 и причина последней строкой stderr
    r = run(_cli_env(e, T, PANTHEON_NOW="не-время"))
    last = (r.stderr.strip().splitlines() or [""])[-1]
    check(r.returncode == 1 and r.stdout == "" and last.startswith("pantheon night agent-gate: потолок не проверен"),
          f"сбой хука: {r.returncode} {r.stdout!r} {r.stderr[-300:]!r}")


def test_launch_cap():
    """metis-0444: launch_cap — причина отказа ручному запуску по origin; --over-cap снимает только у owner; ниже
    потолка и без него — None; достигнут — карточка одна; сбой расчёта — не отказ, строка в stderr и тревога."""
    e = env(50.0, 50.0)
    own = N.launch_cap("owner", t=T)
    check(own and own.startswith("недельный потолок владельца 50 % достигнут: неделя 50 %") and "zeus-limit-budget" in own
          and "до сброса недели" in own and "с --over-cap" in own and "может только владелец" not in own, f"owner: {own!r}")
    check(N.launch_cap("owner", True, t=T) is None, "--over-cap из терминала не снял отказ")
    for origin in ("zeus", "tick"):
        why = N.launch_cap(origin, t=T)
        check(why and "может только владелец" in why and "--over-cap" not in why, f"{origin}: {why!r}")
        why = N.launch_cap(origin, True, t=T)
        check(why and "может только владелец" in why and "только в его терминале" in why, f"{origin} + over: {why!r}")
    check(len(e.cards()) == 1 and cap_alerts(e) == 1, f"карточек {len(e.cards())}, тревог {cap_alerts(e)}")
    e = env(49.9, 49.0)
    check(all(N.launch_cap(o, t=T) is None for o in ("owner", "zeus", "tick")), "ниже потолка — отказ")
    e = env(90.0, 50.0, sec="")
    check(all(N.launch_cap(o, t=T) is None for o in ("owner", "zeus", "tick")), "без потолка — отказ")
    e = env(60.0, 50.0)
    import contextlib
    import io
    real, err = N.measure, io.StringIO()
    N.measure = lambda *a, **k: 1 / 0
    try:
        with contextlib.redirect_stderr(err):
            got = N.launch_cap("tick", t=T)
    finally:
        N.measure = real
    last = (err.getvalue().strip().splitlines() or [""])[-1]
    check(got is None and last.startswith("pantheon: потолок владельца не проверен (ZeroDivisionError")
          and "потолок владельца не проверен" in e.alerts(), f"сбой расчёта: {got!r} {last!r}")


JOBS = ('[[job]]\nname = "clio-weekly"\ncommand = "claude -p --agent clio \\"проход\\""\nevery = 5\n'
        '[[job]]\nname = "scout"\ncommand = "claude -p --agent iris \\"x\\""\nevery = 5\nclass = "heavy"\nclaude = true\n'
        '[[job]]\nname = "view"\ncommand = "pantheon view"\nevery = 5\n')


def _runs(e):
    p = os.path.join(e.state, "dryrun.log")
    return [ln.split()[1] for ln in open(p)] if os.path.exists(p) else []


def _jst(e, name):
    p = os.path.join(e.state, "jobs", name + ".json")
    return json.load(open(p)) if os.path.exists(p) else {}


def test_tick_claude_jobs_wait():
    """metis-0444: потолок достигнут — задачи `claude -p` тика (лёгкая и тяжёлая) не запускаются и ждут с причиной,
    срок не сдвигается; остальные задачи идут. Ниже потолка — запускаются."""
    e = env(60.0, 50.0, sec=CAP50 + JOBS)
    fake = {"PANTHEON_DRYRUN": "1", "PANTHEON_FAKE_WAKE": str(T - 7200), "PANTHEON_FAKE_AC": "1",
            "PANTHEON_FAKE_IDLE": "1200", "PANTHEON_FAKE_LIMIT": "10"}
    r = subprocess.run([PY311, "-I", os.path.join(TN.LIB, "run.py"), "tick"],
                       env=_cli_env(e, T, role=None, **fake), capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, f"тик: {r.returncode} {r.stderr[-300:]!r}")
    check(_runs(e) == ["view"], f"под потолком тик запустил: {_runs(e)}")
    for name in ("clio-weekly", "scout"):
        st = _jst(e, name)
        check("потолок владельца 50 %" in str(st.get("waiting")) and st.get("last_start") is None,
              f"{name} под потолком: {st}")
    e.snap(T + 120, 49.0, e.resets)
    r = subprocess.run([PY311, "-I", os.path.join(TN.LIB, "run.py"), "tick"],
                       env=_cli_env(e, T + 120, role=None, **fake), capture_output=True, text=True, timeout=60)
    check(sorted(_runs(e)) == ["clio-weekly", "scout", "view"], f"ниже потолка тик не запустил: {_runs(e)} {r.stderr[-300:]!r}")
    check(not _jst(e, "scout").get("waiting"), f"ждёт после снятия: {_jst(e, 'scout')}")


def test_run_job_claude_cap():
    """metis-0444: прямой `pantheon run-job` задачи `claude -p` при потолке — код 0, claude не зовётся, задача ждёт;
    ниже потолка — claude идёт."""
    e = env(60.0, 50.0, sec=CAP50 + JOBS)
    os.makedirs(os.path.join(e.state, "settings"), exist_ok=True)
    open(os.path.join(e.state, "settings", "job-clio.json"), "w").write("{}")
    bindir, mark = os.path.join(e.tmp, "bin"), os.path.join(e.tmp, "claude-ran")
    os.makedirs(bindir)
    with open(os.path.join(bindir, "claude"), "w") as fh:
        fh.write(f"#!/bin/sh\necho \"$@\" >> {mark}\n")
    os.chmod(os.path.join(bindir, "claude"), 0o755)

    def run_job(t):
        env_ = _cli_env(e, t, role=None, PANTHEON_FAKE_IDLE="1200", PANTHEON_FAKE_AC="1")
        env_["PATH"] = bindir + ":" + env_["PATH"]
        return subprocess.run([PY311, "-I", os.path.join(TN.LIB, "run.py"), "run-job", "clio-weekly"], env=env_,
                              capture_output=True, text=True, timeout=60)
    r = run_job(T)
    st = _jst(e, "clio-weekly")
    check(r.returncode == 0 and not os.path.exists(mark) and "потолок владельца 50 %" in str(st.get("waiting"))
          and st.get("last_start") is None, f"run-job под потолком: {r.returncode} {st} {r.stderr[-300:]!r}")
    e.snap(T + 60, 49.0, e.resets)
    r = run_job(T + 60)
    check(r.returncode == 0 and os.path.exists(mark) and "waiting" not in _jst(e, "clio-weekly"),
          f"run-job ниже потолка: {r.returncode} {_jst(e, 'clio-weekly')} {r.stderr[-300:]!r}")


def test_word_launch_cap():
    """metis-0444: ответ «Да — запустить|перезапустить|вернуть» при достигнутом потолке не исполняется — причина в
    результате; ниже потолка проверка потолка не мешает."""
    W = P.watch_mod()
    e = env(60.0, 50.0)
    for verb in ("запустить", "перезапустить", "вернуть"):
        res = W._word_do(verb, "athena-shop", "metis-0001", "2026-10-14 12:00:00", f"Да — {verb} athena-shop", [], [])
        check(res.startswith("не исполняю: недельный потолок владельца 50 %"), f"{verb}: {res!r}")
    # Гестию потолок не держит (решение владельца 29.10, PR #193): до запуска доходит — «уже поднято этим проходом»
    W.ONESHOT_STARTED.append("hestia")
    try:
        res = W._word_do("запустить", "hestia", "metis-0001", "2026-10-14 12:00:00", "Да — запустить hestia", [], [])
    finally:
        W.ONESHOT_STARTED.remove("hestia")
    check(res == "уже поднято этим проходом", f"hestia под потолком: {res!r}")
    e = env(49.0, 49.0)
    W.ONESHOT_STARTED.append("athena-shop")  # дальше — «уже поднято этим проходом», без запуска
    try:
        res = W._word_do("запустить", "athena-shop", "metis-0001", "2026-10-14 12:00:00", "Да — запустить athena-shop",
                         [], [])
    finally:
        W.ONESHOT_STARTED.remove("athena-shop")
    check(res == "уже поднято этим проходом", f"ниже потолка: {res!r}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            TN.FAILS.append(f"{fn.__name__}: {type(ex).__name__}: {ex}")
            print("ОШИБКА:", fn.__name__, type(ex).__name__, ex)
    print(f"тестов: {len(tests)}, не прошло: {len(TN.FAILS)}")
    sys.exit(1 if TN.FAILS else 0)
