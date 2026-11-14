#!/usr/bin/env python3
"""Слияние по Touch ID, часть 6 (metis-1153, вариант А владельца 14.11 11:49): `pantheon merge request N -R repo
--restart <окно>` — окно названо в заявке и в окне Touch ID, после слияния по этому Touch ID проход один раз
перезапускает именно его (watch.restart_merged). Без флага — как раньше. Общая часть — _merge_common.py.

Запуск: python3 -I plugins/pantheon/tests/test_merge_restart.py  (код выхода 0 — все прошли; Python 3.11+)
Проверяет: окно не из реестра domains.json, Зевс, пачка, нет реестра, флаг без имени — заявки нет, код 2, причина
последней строкой; заявка хранит окно, повтор с другим окном — новая заявка; окно Touch ID называет окно; после пальца —
перезапуск (claude agents → resume, сухой прогон), событие restart в merge.jsonl, метка один раз: повтор той же заявки
второго перезапуска не даёт; отказ в окне и слияние фразой — без перезапуска (фраза — с тревогой); нет фоновой
сессии — тревога с причиной; битое поле restart в файле заявки — заявка удалена.
"""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_common import *  # noqa: F403

WIN = "athena-shop"
SID = "a1a1a1a1-1111-4111-8111-111111111111"
# claude для перезапуска: agents — из FAKE_AGENTS, остальное — строка в журнале и «ok»
FAKE_CLAUDE = r'''
import json, os, sys
open(os.environ["FAKE_CLAUDE_LOG"], "a").write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1:2] == ["agents"]:
    print(open(os.environ["FAKE_AGENTS"]).read())
else:
    print("ok")
'''


def restart_box(agents=True, doms=(WIN,)):
    b = Box()
    if doms is not None:
        with open(os.path.join(b.state, "domains.json"), "w") as fh:
            json.dump({"domains": {d: [os.path.join(b.home, "projects", d)] for d in doms}}, fh)
    script(os.path.join(b.bin, "claude"), FAKE_CLAUDE)
    b.agents_file = os.path.join(b.rec, "agents.json")
    with open(b.agents_file, "w") as fh:
        json.dump([{"id": SID[:8], "sessionId": SID, "name": WIN, "state": "blocked", "pid": 51, "kind": "background",
                    "cwd": "/tmp", "startedAt": (T0 - 100) * 1000}] if agents else [], fh)
    return b


def run_env(b):
    return {"PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1", "FAKE_AGENTS": b.agents_file,
            "FAKE_CLAUDE_LOG": os.path.join(b.rec, "claude.log")}


def ask(b, *extra, pr=PR):
    return b.cli(["merge", "request", str(pr), "-R", REPO, *extra])


def restarts(b):
    return [r for r in merge_recs(b) if r["event"] == "restart"]


def mark(b):
    return os.path.join(b.state, "restart-owner", f"merge-latark__agent-kit__{PR}-{SHA[:12]}@{WIN}")


def last(r):
    lines = (r.stderr or "").strip().splitlines()
    return lines[-1] if lines else ""


def test_request_refused_names():
    for name, args, box, want in (
            ("окно не из реестра", ["--restart", "zz-out"], restart_box(), "нет в реестре окон"),
            ("Зевс", ["--restart", "zeus"], restart_box(doms=("zeus", WIN)), "Зевс"),
            ("не имя окна", ["--restart", "../x"], restart_box(), "не имя окна"),
            ("реестра нет", ["--restart", WIN], restart_box(doms=None), "domains.json не прочитан"),
            ("флаг без имени", ["--restart"], restart_box(), "pantheon merge request"),
            ("флаг дважды", ["--restart", WIN, "--restart", WIN], restart_box(), "pantheon merge request")):
        r = ask(box, *args)
        check(f"--restart, {name}: заявки нет, код 2, причина последней строкой",
              r.returncode == 2 and box.req() is None and want in last(r) and not box.calls("gh"),
              f"{r.returncode} {r.stdout!r} {r.stderr!r}")
    b = batch_box()
    with open(os.path.join(b.state, "domains.json"), "w") as fh:
        json.dump({"domains": {WIN: []}}, fh)
    r = b.cli(["merge", "request", "7", "8", "-R", REPO, "--restart", WIN])
    check("--restart у пачки: заявок нет, код 2", r.returncode == 2 and b.req(7) is None and b.req(8) is None
          and "не у пачки" in last(r), f"{r.returncode} {r.stderr!r}")


def test_request_keeps_window():
    b = restart_box()
    r = ask(b, "--restart", WIN)
    req = b.req()
    check("--restart: заявка с окном, вывод называет перезапуск", r.returncode == 0 and req and req.get("restart") == WIN
          and f"перезапустит окно {WIN}" in r.stdout, f"{r.returncode} {r.stdout!r} {r.stderr!r} {req}")
    r = ask(b, "--restart", WIN)
    check("--restart: повтор той же заявки — «уже стоит»", r.returncode == 0 and "уже стоит" in r.stdout, r.stdout)
    st = b.cli(["merge", "status"])
    check("merge status показывает окно для перезапуска", f"перезапуск окна {WIN}" in st.stdout, st.stdout)
    r = ask(b)
    check("без --restart после заявки с окном — новая заявка без окна (не «уже стоит»)",
          r.returncode == 0 and "уже стоит" not in r.stdout and "restart" not in (b.req() or {"restart": 1}), r.stdout)
    b2 = restart_box()
    r = ask(b2, "--restart", WIN, pr=PR)
    check("--restart перед -R и номером тоже разбирается", r.returncode == 0 and b2.req()["restart"] == WIN, r.stderr)
    b3 = restart_box()
    r = b3.cli(["merge", "request", "--restart", WIN, str(PR), "-R", REPO])
    check("--restart первым словом", r.returncode == 0 and (b3.req() or {}).get("restart") == WIN, r.stderr)


def test_touchid_restarts_once():
    b = restart_box()
    ask(b, "--restart", WIN)
    r = b.run(extra=run_env(b))
    w = b.windows()
    text = w[0][0] if w else ""
    check("окно Touch ID называет окно для перезапуска", f"затем перезапустить окно {WIN}" in text, text)
    check("после пальца — слияние этого SHA", merged_once(b), b.outs[-1])
    rs = restarts(b)
    check("после слияния по Touch ID — перезапуск окна из заявки (resume), событие restart rc 0",
          f"[resume] {WIN} {SID[:8]}" in r.stdout and len(rs) == 1 and rs[0]["window"] == WIN and rs[0]["rc"] == 0
          and os.path.exists(mark(b)), f"{r.stdout!r} {r.stderr!r} {rs}")
    check("тревога о перезапуске называет Touch ID слияния", f"окно {WIN} перезапущено одно" in b.alerts()
          and f"Touch ID слияния {REPO}#{PR}" in b.alerts(), b.alerts())
    # повтор той же заявки (тот же SHA) — второго перезапуска нет: метка restart-owner одна на слияние
    ask(b, "--restart", WIN)
    r = b.run(t=T0 + 30, extra=run_env(b))
    rs = restarts(b)
    check("повтор той же заявки: второй перезапуск не сделан, событие restart rc 2 с причиной",
          f"[resume] {WIN}" not in r.stdout and len(rs) == 2 and rs[1]["rc"] == 2
          and "уже перезапущено" in (rs[1].get("why") or ""), f"{r.stdout!r} {rs}")
    with open(os.path.join(b.rec, "claude.log")) as fh:
        agents = [ln for ln in fh if json.loads(ln)[:1] == ["agents"]]
    check("повтор: метка проверена до поиска сессии — claude agents второй раз не вызван", len(agents) == 1, agents)


def test_no_restart_without_flag_or_finger():
    b = restart_box()
    ask(b)
    r = b.run(extra=run_env(b))
    check("без --restart: слито, перезапуска нет", merged_once(b) and not restarts(b) and "[resume]" not in r.stdout,
          r.stdout)
    b = restart_box()
    ask(b, "--restart", WIN)
    b.set("touchid-rc", "1")
    r = b.run(extra=run_env(b))
    check("отказ в окне Touch ID: ни слияния, ни перезапуска", not b.merges() and not restarts(b)
          and "[resume]" not in r.stdout, r.stdout)
    b = restart_box()
    ask(b, "--restart", WIN)
    b.set("gh-merge-rc", "1")
    r = b.run(extra=run_env(b))
    check("gh pr merge упал: перезапуска нет", not restarts(b) and "[resume]" not in r.stdout, r.stdout)


def test_phrase_merge_does_not_restart():
    b = restart_box()
    ask(b, "--restart", WIN)
    say(b, f"слей #{PR} {SHA[:7]}", T0 + 60)
    r = b.run(t=T0 + 120, extra=dict(run_env(b), **AWAY))
    rs = restarts(b)
    check("слито фразой: окно не перезапущено, событие restart без кода, тревога с причиной",
          merged_once(b) and "[resume]" not in r.stdout and len(rs) == 1 and rs[0]["rc"] is None
          and "фразой" in rs[0]["why"] and f"окно {WIN} не перезапущено" in b.alerts(), f"{r.stdout!r} {rs}")


def test_restart_failure_alerts():
    b = restart_box(agents=False)
    ask(b, "--restart", WIN)
    b.run(extra=run_env(b))
    rs = restarts(b)
    check("нет фоновой сессии окна: слито, перезапуск rc 1, тревога с причиной",
          merged_once(b) and len(rs) == 1 and rs[0]["rc"] == 1 and "нет фоновой сессии" in rs[0]["why"]
          and "нет фоновой сессии" in b.alerts(), f"{rs} {b.alerts()}")
    # окно убрали из реестра после заявки — перезапуска нет, причина в тревоге
    b = restart_box()
    ask(b, "--restart", WIN)
    with open(os.path.join(b.state, "domains.json"), "w") as fh:
        json.dump({"domains": {"other-x": []}}, fh)
    r = b.run(extra=run_env(b))
    rs = restarts(b)
    check("окна нет в реестре к слиянию: перезапуска нет, rc 2, причина",
          merged_once(b) and "[resume]" not in r.stdout and len(rs) == 1 and rs[0]["rc"] == 2
          and "нет в реестре" in rs[0]["why"], f"{r.stdout!r} {rs}")


def test_bad_restart_field_dropped():
    for bad in ({"restart": "../x"}, {"restart": WIN, "batch": [7, 8]}, {"restart": 5}):
        b = restart_box()
        ask(b)
        req = b.req()
        req.update(bad)
        with open(b.req_path(), "w") as fh:
            json.dump(req, fh)
        r = b.run(extra=run_env(b))
        check(f"битое поле restart {bad}: заявка удалена, слияния нет", "битая заявка" in r.stdout and not b.merges()
              and b.req() is None, r.stdout)


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544); исключение — провал случая
    run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)], FAILS,
              lambda name, err: FAILS.append(name))
    print(f"\n{'ПРОВАЛ: ' + ', '.join(FAILS) if FAILS else 'все прошли'}")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
