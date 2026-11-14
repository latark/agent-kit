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
    # первый вызов отвечает, второй (снимок перед claude --bg, launch_snapshot) — не JSON или таймаут: окна нет, трассы нет
    for how in ("не JSON", "таймаут"):
        e = Env()
        e.direction("sa-dir")
        extra = (_not_json(e) if how == "не JSON"
                 else {"FAKE_AGENTS_SLOW_NEXT": os.path.join(e.tmp, "agents-slow"), "PANTHEON_AGENTS_TIMEOUT": "0.3"})
        r = e.run("start", "sa-dir", "--from", "owner", "задание", t=T0, extra=extra)
        want = f"pantheon start: отказ — {SILENT}" + (" за 0.3 с" if how == "таймаут" else "")
        check(r.returncode != 0 and not _bgs(e) and "Traceback" not in r.stderr and _last(r) == want,
              f"1192: start, второй вызов claude agents ({how}): код {r.returncode}, {_bgs(e)} {r.stderr[-400:]!r}")


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


def _good_then_bad(e, good, **more):
    """Первые good вызовов claude agents отвечают списком, следующие — не JSON (FAKE_AGENTS_COUNT)."""
    return dict({"FAKE_AGENTS_COUNT": os.path.join(e.tmp, "agents-count"), "FAKE_AGENTS_GOOD": str(good)}, **more)


def test_resume_snapshot_not_json_1192():
    """metis-1192: общий pantheon wake, respawn не прошёл — путь --resume. Снимок claude agents перед ним (третий вызов:
    _wake, wake_recheck, снимок) дал не JSON — --resume не идёт, в start.log resume-skip с причиной (раньше пустой
    снимок, и rm_previous с check копий шли вслепую). Контроль — без порчи вывода --resume идёт."""
    for bad in (False, True):
        e = Env()
        e.direction("rs-dir")
        e.task("rs-0001", "rs-dir", status="doing")
        e.agents([bg("rs-dir", "stopped", "3b221192-1")])
        extra = _good_then_bad(e, 2, FAKE_RESPAWN_RC="1") if bad else {"FAKE_RESPAWN_RC": "1"}
        r = e.run("wake", t=T0 + 60, extra=extra)
        resumed = [c for c in e.calls() if "--resume" in c]
        if not bad:
            check(resumed, f"1192: контроль — --resume не пошёл: {e.calls()} {r.stderr[-300:]!r}")
            continue
        skip = [ln for ln in _start_log(e).splitlines() if "resume-skip\trs-dir" in ln]
        check(not resumed and skip and skip[-1].endswith("\t" + SILENT) and "Traceback" not in r.stderr,
              f"1192: --resume при снимке claude agents не JSON: {resumed} {_start_log(e)[-400:]!r} {r.stderr[-300:]!r}")


def test_fresh_start_not_json_1192():
    """metis-1192: свежий старт (pantheon wake, контекст 130 тыс., простой 2 ч) — список сессий в _fresh_start (третий
    вызов) или снимок перед claude --bg (четвёртый) дал не JSON: окно не поднято, в start.log fresh-skip с причиной
    (раньше «копий нет» и запуск с пустым снимком). Контроль — без порчи вывода свежий старт идёт."""
    for good in (None, 2, 3):
        e = Env()
        e.direction("fs-dir")
        e.task("fs-0001", "fs-dir", status="doing")
        a = bg("fs-dir", "stopped", "3c331192-1")
        e.agents([a])
        transcript(e, a, 130_000, T0 - 7200)
        r = e.run("wake", t=T0, extra=_good_then_bad(e, good) if good else None)
        if good is None:
            check(_bgs(e, "fs-dir"), f"1192: контроль — свежий старт не пошёл: {e.calls()} {_start_log(e)[-300:]!r}")
            continue
        skip = [ln for ln in _start_log(e).splitlines() if "fresh-skip\tfs-dir" in ln]
        check(not _bgs(e) and skip and skip[-1].endswith("\t" + SILENT) and "Traceback" not in r.stderr,
              f"1192: свежий старт, вызов claude agents №{good + 1} не JSON: {_bgs(e)} {_start_log(e)[-400:]!r} "
              f"{r.stderr[-300:]!r}")


def _tty_start_zeus():
    """argv: pantheon start zeus с stdin-«терминалом» (как test_start.py: псевдотерминалов в песочнице нет)."""
    boot = ("import runpy, sys\nclass T:\n    def isatty(self):\n        return True\n"
            f"sys.stdin = T()\nsys.argv = [{RUN_PY!r}, 'start', 'zeus']\nrunpy.run_path({RUN_PY!r}, run_name='__main__')\n")
    return [PY311, "-I", "-c", boot]


def test_start_zeus_agents_not_json_1192():
    """metis-1192: pantheon start zeus — claude agents ответил не JSON: отказ «claude agents --json не ответил» последней
    строкой, код 1, claude не запущен (раньше «копий нет» и второй Зевс). Контроль — со списком сессий запуск идёт."""
    for bad in (False, True):
        e = Env()
        open(e.st("settings", "hq.json"), "w").write("{}")
        if bad:
            open(e.agents_file, "w").write("Error: daemon not ready\n")
        r = e.run(t=T0, argv=_tty_start_zeus())
        hq = [c for c in e.calls() if c[:2] == ["--agent", "hq"]]
        if not bad:
            check(hq, f"1192: контроль start zeus не запустил claude: {r.returncode} {e.calls()} {r.stderr[-300:]!r}")
            continue
        check(r.returncode == 1 and not hq and _last(r) == f"pantheon start: отказ — {SILENT}",
              f"1192: start zeus при выводе claude agents не JSON: код {r.returncode}, {hq} {r.stderr[-300:]!r}")


def test_goal_recheck_agents_not_json_1192():
    """metis-1192: смена цели окна (goal_recheck) под блокировкой имени — claude agents не JSON: отказ с причиной, а не
    «держателей нет» (раньше `or []`, и свежий старт со сменой цели шёл вслепую). Контроль — со списком без держателей
    причина не эта."""
    import importlib
    import importlib.util
    d = tempfile.mkdtemp(prefix="goal-1192-")
    for k, sub in (("HOME", "home"), ("PANTHEON_HOME", "pantheon"), ("PANTHEON_STATE", "state")):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
        os.environ[k] = os.path.join(d, sub)
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    p = importlib.import_module("pantheon")
    spec = importlib.util.spec_from_file_location("pantheon_watch_g1192", os.path.join(ROOT, "lib", "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(p)
    saved = p.agents_all, p.sessions_registry
    p.sessions_registry = lambda: []
    try:
        p.agents_all = lambda: None
        got = w.goal_recheck("gr-dir", {"id": "a1"})()
        p.agents_all = lambda: []
        ctl = w.goal_recheck("gr-dir", {"id": "a1"})()
    finally:
        p.agents_all, p.sessions_registry = saved
    check(got == SILENT and w.AGENTS_SILENT == p.AGENTS_SILENT == SILENT,
          f"1192: goal_recheck при claude agents не JSON: {got!r}")
    check(ctl != SILENT, f"1192: контроль goal_recheck со списком — та же причина: {ctl!r}")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
