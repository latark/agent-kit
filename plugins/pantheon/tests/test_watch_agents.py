#!/usr/bin/env python3
"""Дежурный, часть 10: claude agents ответил не JSON или не ответил за срок — запуск и подъём отказывают, а не решают
«копий нет» и не поднимают дубль окна (metis-1192; общая часть — _watch_common.py)."""
# ruff: noqa: F403, F405
import contextlib
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
    # не JSON только список в _fresh_start (вызов №3), снимок №4 отвечает (FAKE_AGENTS_BAD): пропуск, а не запуск —
    # ловит мутант `P.agents_all() or []` на списке, который выше маскировал отказ снимка
    e = Env()
    e.direction("fs-dir")
    e.task("fs-0001", "fs-dir", status="doing")
    a = bg("fs-dir", "stopped", "3c331192-1")
    e.agents([a])
    transcript(e, a, 130_000, T0 - 7200)
    r = e.run("wake", t=T0, extra={"FAKE_AGENTS_COUNT": os.path.join(e.tmp, "agents-count"), "FAKE_AGENTS_BAD": "3"})
    skip = [ln for ln in _start_log(e).splitlines() if "fresh-skip\tfs-dir" in ln]
    check(not _bgs(e) and not [c for c in e.calls() if c[:1] == ["stop"]] and skip and skip[-1].endswith("\t" + SILENT),
          f"1192: свежий старт, не JSON только вызов №3: {e.calls()} {_start_log(e)[-400:]!r} {r.stderr[-300:]!r}")


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


def _core():
    """pantheon и watch в этом процессе (каждый случай — в своём fork, run_cases) с временными HOME, PANTHEON_HOME,
    PANTHEON_STATE и быстрыми PANTHEON_STOP_*. → (pantheon, watch)."""
    import importlib
    import importlib.util
    d = tempfile.mkdtemp(prefix="agents-1192-")
    for k, sub in (("HOME", "home"), ("PANTHEON_HOME", "pantheon"), ("PANTHEON_STATE", "state")):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
        os.environ[k] = os.path.join(d, sub)
    os.environ.update({"PANTHEON_STOP_WAIT": "1", "PANTHEON_STOP_POLL": "0.01", "PANTHEON_DRYRUN": ""})
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    p = importlib.import_module("pantheon")
    spec = importlib.util.spec_from_file_location("pantheon_watch_g1192", os.path.join(ROOT, "lib", "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(p)
    return p, w


def _answers(*seq):
    """Подмена agents_all: ответы по порядку, последний повторяется; n[0] — число вызовов."""
    left, n = list(seq), [0]

    def f():
        n[0] += 1
        return left.pop(0) if len(left) > 1 else left[0]
    return f, n


class _Launched(Exception):
    pass


def _fresh_box(p, answers, alerts, stops, launched):
    """_fresh_start("zeus") с подменами: окно есть, имя освобождается сразу, claude stop и запуск окна — записью
    (запуск обрывается _Launched: дальше снимок не нужен). → код или "launched"."""
    g = p._fresh_start.__globals__  # sessions.py: свои имена модуль ищет у себя
    g["fresh_target"] = lambda name, origin: ("hq", p.HOME, os.path.join(p.HOME, "hq.json"), "hq")
    g["wait_name_free"] = lambda name, stopped: None
    p.agents_all, n = _answers(*answers)
    p.sessions_registry = lambda: []
    p.stop_copies = lambda name, live, tag: stops.extend(x["id"] for x in live)
    p.alert = lambda text, src=None: alerts.append(text)

    def launch(*a):
        launched.append(a)
        raise _Launched()
    p.window_launch = launch
    try:
        return p._fresh_start("zeus", {"id": "2e057e05"}, "очистка", "tick"), n[0]
    except _Launched:
        return "launched", n[0]


ZLIVE = {"id": "2e057e05", "sessionId": "2e057e05-0001", "name": "zeus", "state": "blocked", "kind": "background"}
ZDOWN = dict(ZLIVE, state="stopped")


def test_fresh_start_live_copy_list_not_json_1192():
    """metis-1192 (argus A, #472): свежий старт при живой копии — не JSON только список в _fresh_start, следующий вызов
    отвечает: пропуск с причиной, без claude stop и без запуска окна. Ловит откат отказа на списке (мутант
    `agents = P.agents_all() or []`: копий «нет», stop не идёт, снимок отвечает — окно поднялось бы рядом с живой
    копией). Контроль — список отвечает: stop живой копии и запуск."""
    p, _ = _core()
    alerts, stops, launched = [], [], []
    rc, _ = _fresh_box(p, [None, [ZLIVE]], alerts, stops, launched)
    check(rc == p.SKIPPED and p.SKIP_WHY == SILENT and not stops and not launched and not alerts,
          f"1192: _fresh_start, список не JSON при живой копии: {rc} {p.SKIP_WHY!r} stop={stops} {launched} {alerts}")
    rc, _ = _fresh_box(p, [[ZLIVE], [ZDOWN]], alerts, stops, launched)
    check(rc == "launched" and stops == ["2e057e05"], f"1192: контроль _fresh_start: {rc} stop={stops}")


def test_fresh_start_snapshot_after_stop_waits_1192():
    """metis-1192 (argus B, Д): копии уже погашены, снимок перед запуском не ответил — повтор до срока ожидания имени
    (PANTHEON_STOP_WAIT), а не пропуск после первого сбоя: два сбоя и ответ — окно поднято (ловит снимок без повтора).
    Так и не ответил — пропуск и тревога «Зевс остановлен — pantheon start zeus» с причиной (ловит пропуск без
    тревоги), вызовов больше двух. Без остановленных копий (снимок launch_snapshot) повтора нет: один вызов."""
    p, _ = _core()
    alerts, stops, launched = [], [], []
    rc, n = _fresh_box(p, [[ZLIVE], None, None, [ZDOWN]], alerts, stops, launched)
    check(rc == "launched" and stops == ["2e057e05"] and n == 4 and not alerts,
          f"1192: снимок после stop не повторён до ответа: {rc} вызовов {n} {alerts}")
    alerts, stops, launched = [], [], []
    os.environ["PANTHEON_STOP_WAIT"] = "0.2"
    rc, n = _fresh_box(p, [[ZLIVE], None], alerts, stops, launched)
    check(rc == p.SKIPPED and not launched and n > 2 and p.SKIP_WHY == SILENT
          and [x for x in alerts if x.startswith("Зевс остановлен — pantheon start zeus") and SILENT in x],
          f"1192: снимок после stop так и не ответил: {rc} вызовов {n} {alerts}")
    p.agents_all, n = _answers(None)
    check(p.agents_snapshot() == (None, SILENT) and n[0] == 1, f"1192: снимок без остановки повторялся: {n[0]}")


def test_zeus_clean_skipped_not_code4_1192():
    """metis-1192 (argus B, Д): очистка Зевса, свежий старт дал пропуск (SKIPPED: claude agents не ответил) — проход
    «отложено» с причиной, повтор не раньше часа (failed), без «очистка Зевса не вышла, код 4» (тревогу «Зевс
    остановлен» даёт fresh_skip). Ловит откат ветки `rc == P.SKIPPED` в zeus_clean. Контроль — код 1 по-прежнему «не
    вышла, код 1»."""
    p, w = _core()
    w.zeus_clean_check = lambda a, tp: ([], 160_000, {"turn": 1})
    w.zeus_hold = lambda: None
    p.transcript_path = lambda a: "/nonexistent/zeus.jsonl"
    p.agents_all = lambda: [ZLIVE]
    for rc in (p.SKIPPED, 1):
        alerts = []
        p.alert = lambda text, src=None, alerts=alerts: alerts.append(text)

        def fresh(name, a, text, origin, recheck=None, reason=None, rc=rc):
            recheck()
            return p.skipped(SILENT) if rc == p.SKIPPED else rc
        p.fresh_start = fresh
        with contextlib.suppress(OSError):
            os.remove(p.path("zeus-clean.json"))
        w.zeus_clean([ZLIVE], T0)
        st = p.read_json(p.path("zeus-clean.json"), {}) or {}
        last = st.get("last") or {}
        if rc == 1:
            check(any("не вышла, код 1" in x for x in alerts), f"1192: контроль — код 1 без тревоги: {alerts} {last}")
            continue
        check(not [x for x in alerts if "не вышла" in x] and last.get("result") == "отложено"
              and last.get("miss") == [f"(0) {SILENT}"] and (st.get("failed") or {}).get("sid") == ZLIVE["sessionId"],
              f"1192: очистка Зевса при пропуске: {alerts} {st}")


def test_zeus_clean_agents_silent_after_stop_1192():
    """metis-1192 (находка раунда 4): очистка Зевса, claude agents молчит (не JSON) после claude stop до конца срока
    ожидания имени — без трассы и без запуска; тревога «Зевс остановлен — pantheon start zeus» с причиной «claude
    agents не ответил», проход «отложено», а не «не вышла, код 1». Ловит откат fresh_skip в ветке отказа
    wait_name_free (там был return 1 и тревога «свежий старт не сделан»)."""
    e = zeus_env()
    mark = os.path.join(e.tmp, "agents-silent")
    r = e.run("watch", t=T0, extra={**ZEUS_RUN, "PANTHEON_STOP_WAIT": "0.3", "FAKE_AGENTS_SILENT_AFTER_STOP": mark})
    stops = [c for c in e.calls() if c[:1] == ["stop"]]
    al = e.alerts()
    check(stops and not _bgs(e) and "Traceback" not in r.stderr and "не вышла" not in al
          and [ln for ln in al.splitlines() if "Зевс остановлен — pantheon start zeus" in ln and "claude agents не ответил" in ln]
          and _zeus_last(e).get("result") == "отложено",
          f"1192: Зевс, claude agents молчит после stop: {e.calls()} {al[-500:]!r} {_zeus_last(e)} {r.stderr[-300:]!r}")


def test_wait_name_free_agents_raises_1192():
    """metis-1192: wait_name_free — claude agents не ответил за срок (TimeoutExpired) или не запустился (OSError):
    «не ответил», имя не свободно, отказ текстом после срока, а не трасса Python с уже погашенными копиями. Ловит
    откат except в _agents_or_none."""
    import subprocess as sp
    p, _ = _core()
    os.environ["PANTHEON_STOP_WAIT"] = "0.05"
    p.sessions_registry = lambda: []
    for err in (sp.TimeoutExpired(["claude", "agents"], 15), OSError("exec format error")):
        def boom(err=err):
            raise err
        p.agents_all = boom
        try:
            why = p.wait_name_free("zeus", [ZLIVE])
        except (sp.TimeoutExpired, OSError) as ex:
            why = f"трасса: {ex!r}"
        check(isinstance(why, str) and "claude agents не ответил" in why,
              f"1192: wait_name_free при {type(err).__name__}: {why!r}")


def test_start_restart_first_call_not_json_1192():
    """metis-1192 (argus A, #472): pantheon start <имя> --restart при живой копии — не JSON только первый вызов claude
    agents (start_agents в _start_session), остальные отвечают: отказ «claude agents --json не ответил» последней
    строкой, без claude stop и без --bg. Ловит откат первого отказа (мутант `agents = P.agents_all() or []`: копий
    «нет», снимок launch_snapshot отвечает — дубль окна). Контроль — все вызовы отвечают: stop и --bg."""
    for bad in (False, True):
        e = Env()
        e.direction("sr-dir")
        e.agents([bg("sr-dir", "blocked", "5af01192-1")])
        extra = dict(ZEUS_RUN, **({"FAKE_AGENTS_COUNT": os.path.join(e.tmp, "agents-count"), "FAKE_AGENTS_BAD": "1"}
                                  if bad else {}))
        r = e.run("start", "sr-dir", "--from", "owner", "задание", "--restart", t=T0, extra=extra)
        stops = [c for c in e.calls() if c[:1] == ["stop"]]
        if not bad:
            check(stops and _bgs(e, "sr-dir"), f"1192: контроль start --restart: {r.returncode} {e.calls()} "
                  f"{r.stderr[-300:]!r}")
            continue
        check(r.returncode != 0 and not stops and not _bgs(e) and _last(r) == f"pantheon start: отказ — {SILENT}",
              f"1192: start --restart, первый вызов не JSON: код {r.returncode} {e.calls()} {r.stderr[-300:]!r}")


def test_goal_recheck_agents_not_json_1192():
    """metis-1192: смена цели окна (goal_recheck) под блокировкой имени — claude agents не JSON: отказ с причиной, а не
    «держателей нет» (раньше `or []`, и свежий старт со сменой цели шёл вслепую). Контроль — со списком без держателей
    причина не эта."""
    p, w = _core()
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
