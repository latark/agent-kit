#!/usr/bin/env python3
"""Дежурный, часть 10: claude agents ответил не JSON или не ответил за срок — запуск и подъём отказывают, а не решают
«копий нет» и не поднимают дубль окна (metis-1192; общая часть — _watch_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403

SLOW = {"FAKE_AGENTS_SLEEP": "5", "PANTHEON_AGENTS_TIMEOUT": "0.3"}
SILENT = "claude agents --json не ответил"


def _not_json(e):
    """FAKE_AGENTS_NEXT с выводом не JSON: первый вызов claude agents отвечает списком, все следующие — нет (None)."""
    p = os.path.join(e.tmp, "agents-garbage.txt")
    open(p, "w").write("Error: daemon not ready\n")
    return {"FAKE_AGENTS_NEXT": p}


def _last(r):
    return (r.stderr.strip().splitlines() or [""])[-1]


def test_start_agents_not_json_refuses_1192():
    """metis-1192: pantheon start — claude agents ответил не JSON (None) — отказ «claude agents --json не ответил»
    последней строкой, окно не поднято (раньше None давал «копий нет» и дубль окна). Не ответил за срок — строка
    «… не ответил за N с», а не трасса Python; не запустился (OSError) — тоже строка отказа. Контроль — тот же
    запуск со списком сессий поднимает окно."""
    e = Env()
    e.direction("sa-dir")
    r = e.run("start", "sa-dir", "--from", "owner", "задание", t=T0)
    check(_bgs(e, "sa-dir"), f"1192: контроль start не поднял окно: {r.returncode} {e.calls()} {r.stderr[-300:]!r}")
    e = Env()
    e.direction("sa-dir")
    open(e.agents_file, "w").write("Error: daemon not ready\n")
    r = e.run("start", "sa-dir", "--from", "owner", "задание", t=T0)
    check(r.returncode != 0 and not _bgs(e) and _last(r) == f"pantheon start: отказ — {SILENT}",
          f"1192: start при выводе claude agents не JSON: код {r.returncode}, {_bgs(e)} {r.stderr[-300:]!r}")
    e = Env()
    e.direction("sa-dir")
    r = e.run("start", "sa-dir", "--from", "owner", "задание", t=T0, extra=SLOW)
    check(r.returncode != 0 and not _bgs(e) and "Traceback" not in r.stderr
          and _last(r) == f"pantheon start: отказ — {SILENT} за 0.3 с",
          f"1192: start при таймауте claude agents: код {r.returncode}, {_bgs(e)} {r.stderr[-400:]!r}")
    e = Env()
    e.direction("sa-dir")
    open(os.path.join(e.bin, "claude"), "w").write("#!/nonexistent/interpreter-1192\n")  # exec падает OSError
    r = e.run("start", "sa-dir", "--from", "owner", "задание", t=T0)
    check(r.returncode != 0 and "Traceback" not in r.stderr
          and _last(r).startswith(f"pantheon start: отказ — {SILENT} (не запустился:"),
          f"1192: start при незапуске claude agents: код {r.returncode} {r.stderr[-400:]!r}")


def test_autostart_agents_not_json_refuses_1192():
    """metis-1192: самозапуск плановым проходом — первый вызов claude agents ответил, вызов под блокировкой имени дал не
    JSON: новая сессия (дочерний pantheon start, _start_session) и продолжение остановленной (watch.recheck) окно не
    поднимают; у продолжения в start.log — пропуск с причиной «claude agents --json не ответил». Контроль — тот же
    проход без порчи вывода поднимает окно."""
    for bad in (False, True):
        for stopped in (False, True):
            e = Env()
            e.direction("sb-dir")
            e.task("sb-0001", "sb-dir")
            e.run("watch", t=T0)
            e.board("sb-0001", T0 + 10)
            if stopped:
                e.agents([bg("sb-dir", "stopped", "5ee71192-1")])
            n0 = len(e.calls())
            r = e.run("watch", t=T0 + 120, extra=_not_json(e) if bad else None)
            got = [c for c in e.calls()[n0:] if c[:1] in (["--bg"], ["respawn"]) or "--resume" in c]
            what = "продолжение" if stopped else "новая"
            if not bad:
                check(got, f"1192: контроль самозапуска ({what}) окна не поднял: {e.calls()[n0:]} {r.stderr[-300:]!r}")
                continue
            check(not got, f"1192: самозапуск ({what}) поднял окно при выводе claude agents не JSON: {got}")
            if stopped:
                skip = [ln for ln in _start_log(e).splitlines() if "-skip\tsb-dir" in ln]
                check(skip and skip[-1].endswith("\t" + SILENT),
                      f"1192: продолжение без причины «{SILENT}» в start.log: {_start_log(e)[-400:]!r}")


def test_wake_recheck_agents_not_json_1192():
    """metis-1192: общий pantheon wake — список сессий получен, а повторная проверка под блокировкой имени
    (wake_recheck) получила не JSON: остановленная сессия не продолжается, в start.log — resume-skip с причиной
    «claude agents --json не ответил» (раньше None давал «копий нет»). Контроль — без порчи вывода продолжается."""
    for bad in (False, True):
        e = Env()
        e.direction("wr-dir")
        e.task("wr-0001", "wr-dir", status="doing")
        e.agents([bg("wr-dir", "stopped", "3a111192-1")])
        r = e.run("wake", t=T0 + 60, extra=_not_json(e) if bad else None)
        if not bad:
            check(_resumed(e, "3a111192-1"), f"1192: контроль wake не продолжил сессию: {e.calls()} {r.stdout[-300:]!r}"
                  f" {r.stderr[-300:]!r}")
            continue
        skip = [ln for ln in _start_log(e).splitlines() if "-skip\twr-dir" in ln]
        check(not _resumed(e, "3a111192-1") and skip and skip[-1].endswith("\t" + SILENT),
              f"1192: wake при выводе claude agents не JSON под блокировкой: {e.calls()} {_start_log(e)[-400:]!r}"
              f" {r.stderr[-300:]!r}")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
