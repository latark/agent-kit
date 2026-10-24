#!/usr/bin/env python3
"""Недельный потолок владельца ([limits.owner_cap], metis-0403; раньше дневной metis-0275).

Потолок только сужает: достигнут (неделя ≥ pct) — autostart, wake и respawn отказаны днём и ночью, новые субагенты из
окон координаторов — тоже (хук `pantheon night agent-gate`); ниже потолка — поведение как без него (жёлтая и красная
зона, hard_pct, ночь). При достижении — одна тревога и одна карточка Зевсу на неделю и pct.

Запуск: python3 -I plugins/pantheon/tests/test_owner_cap.py  (код выхода 0 — все прошли)
Помощники (Env, hm, check) — из test_night.py.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # pantheon.py — только на Python 3.11+ (tomllib)
if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)])
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
    # окно координатора и мастерская — отказ с причиной; штаб, окна задач и терминал — нет
    for role in ("domain-coordinator", "workshop"):
        why = with_role(role, lambda: N.agent_gate(TN_NIGHT))  # noqa: B023
        check(why and "потолок владельца 50 %" in why and "не запускай" in why, f"agent_gate {role}: {why!r}")
    for role in ("hq", "job", "", None):
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
    for role in ("hq", "job", "", None):
        r = run(_cli_env(e, T, role=role, CLAUDE_PLUGIN_ROOT=fake))
        check(r.returncode == 0 and r.stdout == "", f"роль {role!r}: хук запустил pantheon: {r.stdout!r}")
    r = run(_cli_env(e, T, CLAUDE_PLUGIN_ROOT=fake))
    check(r.stdout.strip() == "STARTED night agent-gate", f"координатор с owner_cap: {r.stdout!r} {r.stderr!r}")
    e2 = env(50.0, 50.0, sec="")
    r = run(_cli_env(e2, T, CLAUDE_PLUGIN_ROOT=fake))
    check(r.returncode == 0 and r.stdout == "", f"без owner_cap хук запустил pantheon: {r.stdout!r}")
    r = run(_cli_env(e2, T, CLAUDE_PLUGIN_ROOT=fake, PANTHEON_HOME=os.path.join(e2.tmp, "нет")))
    check(r.returncode == 0 and r.stdout == "", f"без schedule.toml хук запустил pantheon: {r.stdout!r}")
    # настоящий плагин: достигнут — отказ с причиной, код 0
    for role in ("domain-coordinator", "workshop"):
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
