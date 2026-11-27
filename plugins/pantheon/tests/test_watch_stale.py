#!/usr/bin/env python3
"""Дежурный, часть 12: окно со старой сборкой — тревога Зевсу «перезапустить» (metis-1337); метка asks-answered: отказ
по ответу, снятие у ожившей записи, чистка старых (долги metis-1329). Общая часть — _watch_common.py."""
# ruff: noqa: F403, F405
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403

_FP_PROBE = r"""
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("pantheon_lib", sys.argv[1])
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
print(P.window_build_fp(json.load(open(sys.argv[2]))))
"""


def _fp(e, name):
    """Отпечаток текущего settings/<name>.json — тем же window_build_fp, что у run_settings и watch."""
    r = e.run(LIB, e.st("settings", name + ".json"), t=T0, argv=[PY311, "-I", "-c", _FP_PROBE])
    return (r.stdout.strip().splitlines() or [""])[-1]


def _run_file(e, name, build):
    """Файл запуска живой сессии, как его пишет run_settings: окно, имя и (если build) отпечаток сборки при запуске."""
    os.makedirs(e.st("settings", "run"), exist_ok=True)
    env = {"PANTHEON_WINDOW": name, "PANTHEON_SESSION": name, "PANTHEON_ROLE": "coordinator"}
    if build:
        env["PANTHEON_BUILD"] = build
    json.dump({"env": env}, open(e.st("settings", "run", name + ".json"), "w"))


def test_stale_window_alert_1337():
    """metis-1337: окно поднято со сборкой (PANTHEON_BUILD файла запуска), которая не совпала с отпечатком текущего
    settings/<окно>.json, — тревога «Зевсу: перезапустить <окно>»; повтор по тому же окну и отпечатку — не раньше
    суток. С текущим отпечатком и без PANTHEON_BUILD (поднято до metis-1337) — тревоги нет; Зевс и остановленное
    вами — не кандидаты."""
    e = Env()
    e.direction("st-dir")
    a = bg("st-dir", "done", "abab0001-1", pid=51)
    e.agents([a])
    _run_file(e, "st-dir", None)
    e.run("watch", t=T0)  # без отпечатка — не сверяется; заодно сборка окон этого прохода, если она есть
    line = "Зевсу: перезапустить st-dir"
    check(line not in e.alerts(), f"1337: тревога у окна без PANTHEON_BUILD: {e.alerts()}")
    cur = _fp(e, "st-dir")
    check(len(cur) == 16, f"1337: отпечаток не посчитан: {cur!r}")
    _run_file(e, "st-dir", cur)
    e.run("watch", t=T0 + 60)
    check(line not in e.alerts(), f"1337: тревога при текущем отпечатке: {e.alerts()}")
    _run_file(e, "st-dir", "0" * 16)
    e.run("watch", t=T0 + 120)
    check(e.alerts().count(line) == 1 and f"сборкой {'0' * 16}, текущая {cur}" in e.alerts(),
          f"1337: нет тревоги у окна со старой сборкой: {e.alerts()}")
    e.run("watch", t=T0 + 3600)
    check(e.alerts().count(line) == 1, f"1337: повтор тревоги раньше суток: {e.alerts()}")
    e.run("watch", t=T0 + 120 + 86460)
    check(e.alerts().count(line) == 2, f"1337: нет повтора через сутки: {e.alerts()}")
    # остановлено вами — не кандидат
    e2 = Env()
    e2.direction("ss-dir")
    e2.agents([bg("ss-dir", "done", "abab0002-1", pid=51)])
    _run_file(e2, "ss-dir", "0" * 16)
    os.makedirs(e2.st("stopped"), exist_ok=True)
    open(e2.st("stopped", "ss-dir"), "w").close()
    e2.run("watch", t=T0)
    check("перезапустить ss-dir" not in e2.alerts(), f"1337: тревога у остановленного вами: {e2.alerts()}")


def test_word_refused_keeps_ghost_asking_1329():
    """metis-1329 Д1, решение «нет»: ответ «Да — запустить <имя>», отклонённый меткой «остановлено вами» или недельным
    потолком, метку asks-answered не ставит — призрак остаётся «ждёт вас», а не поднимается позже самозапуском без
    строки «ответа на твой вопрос нет». Контроль — тот же ответ без отказа метку ставит."""
    for label in ("stopped", "cap", "control"):
        t = T0 + 60
        e = _ghost_env("zz-ra", updated=T0 - 1000)
        e.task("zz-0011", "zz-ra", status="doing")
        rec = dict(bg("zz-ra", "blocked", "cccccccc-1"), waitingFor="какую базу брать?")
        e.agents([rec])
        e.run("watch", t=t)
        if label == "stopped":
            os.makedirs(e.st("stopped"), exist_ok=True)
            open(e.st("stopped", "zz-ra"), "w").close()
        elif label == "cap":
            day = time.strftime("%Y-%m-%d", time.localtime(T0))  # потолок владельца 5 % при неделе 10 % — достигнут
            with open(os.path.join(e.pantheon, "schedule.toml"), "a") as fh:
                fh.write(f'\n[limits.owner_cap]\ndate = "{day}"\npct = 5\ndecision = "t"\n')
        _zeus_answer(e, t + 30, "[zz-0011] Запустить zz-ra?", "Да — запустить zz-ra")
        e.agents([rec])
        e.run("watch", t=t + 60)
        mark = os.path.exists(e.st("asks-answered", "cccccccc")) or [
            r for r in _start_rows(e) if r[1:2] == ["asks-answered"]]
        wl = [r for r in _start_rows(e) if r[1:2] == ["word-launch"]]
        if label == "control":
            check(mark, f"1329 Д1: контроль — ответ без отказа не поставил метку: {_start_rows(e)}")
            continue
        check(wl and "не исполняю" in wl[-1][-1], f"1329 Д1 ({label}): ответ не отклонён: {wl}")
        check(not mark, f"1329 Д1 ({label}): отклонённый ответ поставил метку asks-answered: {_start_rows(e)}")


def test_alive_record_clears_mark_1329():
    """metis-1329 Д2: запись claude agents с меткой asks-answered, процесс которой жив (воркер демона), — после прохода
    watch метки нет (reconcile_agents, ветка «ожила»): ответ использован, следующий вопрос снова «ждёт вас». Контроль —
    мёртвая запись (призрак) метку сохраняет."""
    for alive in (True, False):
        e = _ghost_env("zz-la", updated=T0 - 1000)
        daemon = os.path.dirname(e.roster)
        workers = {"cccccccc": {"pid": os.getpid()}} if alive else {"other": {"pid": 999999}}
        json.dump({"updatedAt": (T0 - 1000) * 1000, "workers": workers}, open(os.path.join(daemon, "roster.json"), "w"))
        e.agents([bg("zz-la", "working", "cccccccc-1")])
        os.makedirs(e.st("asks-answered"), exist_ok=True)
        open(e.st("asks-answered", "cccccccc"), "w").write("zz-la\tq\tts\n")
        e.run("watch", t=T0)
        left = os.path.exists(e.st("asks-answered", "cccccccc"))
        if alive:
            check(not left, "1329 Д2: живая запись — метка asks-answered осталась после watch")
        else:
            check(left or _woke(e), f"1329 Д2: контроль — у мёртвой записи метка снята без подъёма: {e.calls()}")


def test_asks_answered_old_marks_swept_1329():
    """Долг metis-1329: метки asks-answered старше ASKS_ANSWERED_DAYS (14 дн) убирает проход с ответом «Да —
    запустить»; моложе — остаются."""
    t = T0 + 60
    e = _ghost_env("zz-sw", updated=T0 - 1000)
    e.task("zz-0021", "zz-sw", status="doing")
    os.makedirs(e.st("asks-answered"), exist_ok=True)
    for aid, age in (("aaaa0001", 15), ("aaaa0002", 13)):
        p = e.st("asks-answered", aid)
        open(p, "w").write("x\tq\tts\n")
        os.utime(p, (T0 - age * 86400, T0 - age * 86400))
    e.agents([dict(bg("zz-sw", "blocked", "cccccccc-1"), waitingFor="вопрос?")])
    e.run("watch", t=t)
    _zeus_answer(e, t + 30, "[zz-0021] Запустить zz-sw?", "Да — запустить zz-sw")
    e.run("watch", t=t + 60)
    check(not os.path.exists(e.st("asks-answered", "aaaa0001")), "1329: метка старше 14 дн не убрана")
    check(os.path.exists(e.st("asks-answered", "aaaa0002")), "1329: метка моложе 14 дн убрана")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
