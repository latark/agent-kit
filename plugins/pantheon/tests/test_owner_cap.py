#!/usr/bin/env python3
"""Потолок дня владельца ([limits.owner_cap], metis-0275): wake и autostart днём до потолка, нан/inf, ночь, зоны.

Запуск: python3 -I plugins/pantheon/tests/test_owner_cap.py  (код выхода 0 — все прошли)
Помощники (Env, hm, check) — из test_night.py.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # pantheon.py — только на Python 3.11+ (tomllib)
if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)])
from datetime import datetime, timedelta

import test_night as TN

check, hm, Env, N, EVENING = TN.check, TN.hm, TN.Env, TN.N, TN.EVENING


def test_owner_cap():
    """metis-0275: потолок дня владельца пускает wake/autostart в красной зоне днём; ночь, respawn, heavy_max, hard_pct не меняет."""
    t = hm("12:00", EVENING - timedelta(days=1))  # день 15.10, 12:00
    day = datetime.fromtimestamp(t).date().isoformat()
    yday = (datetime.fromtimestamp(t).date() - timedelta(days=1)).isoformat()

    def env(sec):
        e = Env('primary_host = "mac-a"\n' + sec)
        e.at_line(t, 10)  # красная зона: запас +10 п.п.
        return e

    def cnt(e):
        return e.alerts().count("потолок владельца")

    def sec(date_, pct):
        return f'[limits.owner_cap]\ndate = "{date_}"\npct = {pct}\ndecision = "18.10 13:47"\n'
    e = env("")
    used = N.measure(t)["used"]
    for kind in ("wake", "autostart"):
        ok, why = N.gate(kind, t, heavy=0)
        check(not ok and "красная зона" in why, f"без потолка {kind}: {ok} {why}")
    e = env(sec(day, used + 5))
    for kind in ("wake", "autostart"):
        ok, why = N.gate(kind, t, heavy=0)
        check(ok, f"потолок выше расхода, {kind}: {ok} {why}")
    check(not N.gate("autostart", t, heavy=2)[0], "потолок отменил heavy_max")
    check(not N.gate("respawn", t)[0], "потолок открыл respawn в красной зоне")
    check(cnt(e) == 0, "тревога потолка без достижения")
    # расход ≥ потолка: закрыто, тревога одна (повторные проходы молчат: ключ — дата и потолок)
    e = env(sec(day, used - 1))
    for _ in range(3):
        ok, why = N.gate("wake", t + 60, heavy=0)
        check(not ok and "потолок владельца" in why and "достигнут" in why, f"расход ≥ потолка: {ok} {why}")
    check(cnt(e) == 1, f"тревог потолка должно быть 1: {e.alerts()}")
    # потолок на вчера не действует
    e = env(sec(yday, used + 5))
    ok, why = N.gate("wake", t, heavy=0)
    check(not ok and "красная зона" in why, f"вчерашний потолок: {ok} {why}")
    # битые секции — как без потолка
    for bad in ('[limits.owner_cap]\ndate = "завтра"\npct = 90\n', f'[limits.owner_cap]\ndate = "{day}"\npct = "много"\n',
                f'[limits.owner_cap]\ndate = "{day}"\n', 'limits.owner_cap = 5\n',
                f'[limits.owner_cap]\ndate = "{day}"\npct = true\n'):
        e = env(bad)
        ok, why = N.gate("autostart", t, heavy=0)
        check(not ok and "красная зона" in why, f"битый потолок {bad!r}: {ok} {why}")
    # потолок выше hard_pct не отменяет hard_pct
    e = Env('primary_host = "mac-a"\n' + sec(day, 99))
    e.snap(t, 86.0, t + 3 * 86400)
    ok, why = N.gate("wake", t, heavy=0)
    check(not ok and "красная зона" in why, f"hard_pct отменён потолком: {ok} {why}")
    # nan и inf отбрасываются: не потолок, красная зона закрыта (TOML понимает nan и inf)
    for bad in ("nan", "inf", "-inf"):
        e = env(f'[limits.owner_cap]\ndate = "{day}"\npct = {bad}\n')
        check(N.owner_cap(t) is None, f"pct = {bad} принят как потолок")
        ok, why = N.gate("wake", t, heavy=0)
        check(not ok and "красная зона" in why, f"pct = {bad}: {ok} {why}")
    # дата TOML без кавычек
    e = env(f'[limits.owner_cap]\ndate = {day}\npct = {used + 5}\n')
    check(N.gate("wake", t, heavy=0)[0], "дата TOML без кавычек не принята")


def test_owner_cap_night_yellow_green():
    """metis-0275, замечания argus: ночь с потолком, жёлтая зона днём, зелёная при расходе ≥ потолка, ключ тревоги."""
    t = hm("12:00", EVENING - timedelta(days=1))
    day = datetime.fromtimestamp(t).date().isoformat()

    def env(over, sec):
        e = Env('primary_host = "mac-a"\n' + sec)
        e.at_line(t, over)
        return e

    def sec(pct):
        return f'[limits.owner_cap]\ndate = "{day}"\npct = {pct}\ndecision = "18.10 13:47"\n'
    # жёлтая зона (запас +3 п.п.): без потолка закрыто, с потолком выше расхода — открыто (мутант m2)
    e = env(3, "")
    used = N.measure(t)["used"]
    ok, why = N.gate("wake", t, heavy=0)
    check(not ok and "жёлтая зона" in why, f"жёлтая без потолка: {ok} {why}")
    e = env(3, sec(used + 5))
    check(N.measure(t)["zone"] == "yellow", "зона не жёлтая")
    for kind in ("wake", "autostart"):
        ok, why = N.gate(kind, t, heavy=0)
        check(ok, f"жёлтая с потолком, {kind}: {ok} {why}")
    # жёлтая зона, расход ≥ потолка: wake и autostart закрыты именно потолком, тревога одна (мутант m3: жёлтая пропускает потолок)
    e = env(3, sec(used - 1))
    check(N.measure(t)["zone"] == "yellow", "зона не жёлтая (расход ≥ потолка)")
    for kind in ("wake", "autostart"):
        ok, why = N.gate(kind, t, heavy=0)
        check(not ok and "потолок владельца" in why and "достигнут" in why, f"жёлтая, расход ≥ потолка, {kind}: {ok} {why}")
    check(e.alerts().count("потолок владельца") == 1, f"тревога в жёлтой зоне должна быть одна: {e.alerts()!r}")
    # ночь: потолок красную зону не открывает (мутант m1). Дата потолка — день ночи, ночь начинается в 23:00
    tn = hm("23:30", EVENING - timedelta(days=1))
    dn = datetime.fromtimestamp(tn).date().isoformat()
    e = Env('primary_host = "mac-a"\n' + f'[limits.owner_cap]\ndate = "{dn}"\npct = 99\n')
    e.at_line(tn, 10)
    check(N.night_of(tn, N.config()) is not None, "23:30 не ночь")
    ok, why = N.gate("wake", tn, heavy=0)
    check(not ok and "красная зона" in why, f"ночью красная зона открыта потолком: {ok} {why}")
    # зелёная зона при расходе ≥ потолка: закрыто и тревога (решение А)
    e = env(-3, "")
    used = N.measure(t)["used"]
    e = env(-3, sec(used - 1))
    check(N.measure(t)["zone"] == "green", "зона не зелёная")
    ok, why = N.gate("wake", t, heavy=0)
    check(not ok and "потолок владельца" in why, f"зелёная при расходе ≥ потолка: {ok} {why}")
    check(e.alerts().count("потолок владельца") == 1, f"тревога в зелёной зоне: {e.alerts()!r}")
    ok, why = N.gate("autostart", t, heavy=0)
    check(not ok, "зелёная, autostart открыт")
    check(N.gate("respawn", t)[0], "respawn закрыт потолком в зелёной зоне")
    # зелёная ниже потолка — открыто
    e = env(-3, sec(used + 5))
    check(N.gate("wake", t, heavy=0)[0], "зелёная ниже потолка закрыта")
    # ключ тревоги — дата и потолок: граница часа не даёт второй
    e = env(10, "")
    used = N.measure(t)["used"]
    e = env(10, sec(used - 1))
    N.gate("wake", t, heavy=0)
    t2 = t + 3600
    e.snap(t2, used + 0.5, e.resets or t + 3 * 86400)
    N.gate("wake", t2, heavy=0)
    check(e.alerts().count("потолок владельца") == 1, f"тревога повторилась через час: {e.alerts()!r}")


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
