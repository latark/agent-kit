#!/usr/bin/env python3
"""Дежурный, часть 2: держатели, продолжение сессии, уборка Зевса, пересоздание (общая часть — _watch_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403


def test_autostart_start_timeout_0141():
    """metis-0141 п. 1: pantheon start из самозапуска не уложился в срок — строка в тревогах и код 124, без трассировки;
    срок по умолчанию покрывает шаги запуска (около 410 с) и меньше срока прохода дежурного (600 с)."""
    e = Env()
    e.direction("pluto-x")
    e.task("pluto-0001", "pluto-x")
    e.run("watch", t=T0)
    e.board("pluto-0001", T0 + 10)
    r = e.run("watch", t=T0 + 60, extra={"PANTHEON_START_TIMEOUT": "2", "FAKE_BG_SLEEP": "20"})
    check(r.returncode == 0 and "Traceback" not in r.stderr, f"проход упал на сроке запуска: {r.returncode} {r.stderr[-800:]}")
    check("pantheon start не уложился в 2 с" in e.alerts() and "не вышло, код 124" in e.alerts(),
          f"нет строки о сроке запуска: {e.alerts()[-600:]}")
    st = json.load(open(e.st("autostart.json")))["pluto-x"]
    check(st.get("fails") == 1, f"срок запуска не засчитан сбоем: {st}")
    src = open(os.path.join(ROOT, "lib", "watch.py"), encoding="utf-8").read()
    check("START_TIMEOUT = 420.0" in src and "timeout=300" not in src.split("def resume_or_start")[1].split("\ndef ")[0],
          "срок pantheon start в resume_or_start не 420 с")


def test_autostart_healthy_resets_and_limits():
    """Сессия проработала ≥ 30 мин — сбои забыты; два направления уже работают — третье ждёт места."""
    e = Env()
    for d in ("a-one", "b-two", "c-three"):
        e.direction(d)
    for d, tid in (("a-one", "aa-0001"), ("b-two", "bb-0001"), ("c-three", "cc-0001")):
        e.task(tid, d)
    e.run("watch", t=T0)
    for tid in ("aa-0001", "bb-0001", "cc-0001"):
        e.board(tid, T0 + 10)
    e.agents([bg("a-one", "working", "aaaaaaaa-1", pid=11), bg("b-two", "working", "bbbbbbbb-1", pid=12)])
    e.run("watch", t=T0 + 60)
    check(not [c for c in e.calls() if c[:1] == ["--bg"]], "третье направление запущено сверх двух")
    check("нет места" in e.alerts(), "тревога «нет места»")
    # здоровая сессия сбрасывает сбои
    json.dump({"a-one": {"last": T0, "pending": True, "fails": 2}}, open(e.st("autostart.json"), "w"))
    e.run("watch", t=T0 + 1900)
    check(json.load(open(e.st("autostart.json")))["a-one"].get("fails") == 0, "сбои не сброшены здоровой сессией")


def test_holders_registry_and_live_copies():
    """Имя держит и вкладка из ~/.claude/sessions (её нет в claude agents); stopped имени не держит."""
    e = Env()
    e.direction("zz-dir")
    e.task("zz-0001", "zz-dir")
    e.run("watch", t=T0)
    e.board("zz-0001", T0 + 10)
    os.makedirs(os.path.join(e.home, ".claude", "sessions"), exist_ok=True)
    json.dump({"pid": os.getpid(), "sessionId": "tab-1", "name": "zz-dir", "kind": "interactive", "cwd": "/tmp"},
              open(os.path.join(e.home, ".claude", "sessions", f"{os.getpid()}.json"), "w"))
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check("zz-dir: уже работает" in out, f"вкладка из реестра не держит имя: {out}")
    out = e.run("wake", "zz-dir", t=T0 + 60).stdout
    check("не спит" in out, f"wake будит при открытой вкладке: {out}")
    os.remove(os.path.join(e.home, ".claude", "sessions", f"{os.getpid()}.json"))
    e.agents([bg("zz-dir", "stopped", "dddddddd-1")])
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check("zz-dir: поднял бы сейчас" in out, f"stopped держит имя: {out}")
    # самозапуск продолжает остановленную той же сессией: claude respawn (id, имя, окно сохраняются), текст — push
    e.run("watch", t=T0 + 120)
    check(["respawn", "dddddddd"] in e.calls(), f"самозапуск не через respawn: {e.calls()}")
    pushed = e.st("push", "dddddddd-1.txt")
    check(os.path.exists(pushed) and open(pushed).read().startswith("[Пантеон:"), "текст для хука push")
    check(oct(os.stat(pushed).st_mode & 0o777) == "0o600", "права push-файла")
    # respawn не вышел (сессию удалили из списка) — --resume с именем и окном
    e.agents([bg("zz-dir", "stopped", "dddddddd-2", started=T0 + 1)])
    json.dump({}, open(e.st("autostart.json"), "w"))
    e.run("watch", t=T0 + 99999, extra={"FAKE_RESPAWN_RC": "1"})
    res = [c for c in e.calls() if "--resume" in c]
    check(res and res[-1][res[-1].index("--name") + 1] == "zz-dir" and "--settings" in res[-1],
          f"resume без --name/--settings: {res}")
    check(not os.path.exists(e.st("push", "dddddddd-2.txt")), "push-файл остался после неудачного respawn")


def test_resume_or_start_fresh():
    """metis-0147 п. 2 в дежурном (resume_or_start: pantheon wake <имя>, самозапуск, снятие паузы): контекст > 100 тыс.
    и простой > 60 мин — свежая сессия с файла состояния; иначе — respawn, как раньше."""
    e = Env()
    e.direction("fr-dir")
    a = bg("fr-dir", "stopped", "ffffffff-1")
    e.agents([a])
    transcript(e, a, 130_000, T0 - 7200)
    r = e.run("wake", "fr-dir", t=T0, extra=QUICK)
    c = e.calls()
    new = [x for x in c if "--bg" in x]
    check(not [x for x in c if x[:1] == ["respawn"] or "--resume" in x] and len(new) == 1
          and new[0][:5] == ["--bg", "--agent", "domain-coordinator", "--name", "fr-dir"]
          and os.path.realpath(new[0][6]) == os.path.realpath(e.st("settings", "run", "fr-dir.json"))
          and "[Пантеон: свежий старт]" in new[0][-1] and "~/ai/pantheon/directions/fr-dir/STATUS.md" in new[0][-1]
          and "Посмотри входящие" in new[0][-1], f"свежий старт в pantheon wake <имя>: {c} {r.stdout} {r.stderr}")
    open(e.log, "w").close()
    transcript(e, a, 130_000, T0 - 600)
    e.run("wake", "fr-dir", t=T0, extra=QUICK)
    check(["respawn", "ffffffff"] in e.calls() and not [x for x in e.calls() if "--bg" in x],
          f"простой 10 мин — не respawn: {e.calls()}")


def test_zeus_clean_0136():
    """metis-0136: дежурный очищает Зевса только при всех шести условиях — свежий старт (claude stop + claude --bg
    --agent hq --name zeus с окном штаба), одна строка «Зевс очищен в HH:MM, контекст N тыс.»; повторный проход —
    ничего. Любое условие не выполнено — очистки нет; не выполнено только (5) — напоминание не чаще раза в час;
    (6) — с конца хода меньше 20 мин: ни очистки, ни напоминания."""
    # все условия выполнены — ровно одно действие и одна строка
    e = zeus_env()
    r = e.run("watch", t=T0, extra=ZEUS_RUN)
    acts = zeus_actions(e)
    starts = [c for c in acts if c[:1] == ["--bg"]]
    check(acts[:1] == [["stop", "2e057e05"]] and len(starts) == 1 and len(acts) == 2,
          f"очистка Зевса — не stop + один --bg: {acts} {r.stderr[-600:]}")
    if starts:
        s = starts[0]
        check(s[s.index("--agent") + 1] == "hq" and s[s.index("--name") + 1] == "zeus"
              and os.path.realpath(s[s.index("--settings") + 1]) == os.path.realpath(e.st("settings", "hq.json")),
              f"свежий Зевс не с ролью, именем и окном штаба: {s}")
        check(s[-1].startswith("[Пантеон: очистка]") and "~/ai/pantheon/board.md" in s[-1]
              and "~/ai/pantheon/handoff/zeus-2026-10-16/HANDOFF.md" in s[-1] and "продолжай" in s[-1],
              f"текст свежего Зевса: {s[-1]}")
    hhmm = time.strftime("%H:%M", time.localtime(T0))
    check(e.alerts().count("Зевс очищен") == 1 and f"Зевс очищен в {hhmm}, контекст 160 тыс." in e.alerts(),
          f"нет одной строки об очистке: {e.alerts()[-500:]}")
    check(os.path.exists(e.zeus_transcript), "транскрипт прошлого Зевса пропал")
    n = len(e.calls())
    e.run("watch", t=T0 + 300, extra=ZEUS_RUN)                     # Зевс уже остановлен — ничего
    z = json.load(open(e.agents_file))
    z[0].update(state="blocked")                                     # старый список: та же сессия снова «ждёт»
    e.agents(z)
    e.run("watch", t=T0 + 600, extra=ZEUS_RUN)
    check(len(zeus_actions(e)) == 2 and e.alerts().count("Зевс очищен") == 1,
          f"повторный проход снова чистит: {e.calls()[n:]}")

    # каждое условие по отдельности не выполнено — очистки нет
    ask = [_tool("AskUserQuestion", "toolu_ask1", {"questions": []}, T0 - 2980)]
    bash_bg = [_tool("Bash", "toolu_bg1", {"command": "sleep 999", "run_in_background": True}, T0 - 2985),
               _result("toolu_bg1", T0 - 2984, "Command running in background with ID: b1", {"backgroundTaskId": "b1"}),
               _answer(T0 - 2983)]
    agent_bg = [_tool("Agent", "toolu_ag1", {"prompt": "x"}, T0 - 2985),
                _result("toolu_ag1", T0 - 2984, "Async agent launched successfully. agentId: a1",
                        {"isAsync": True, "status": "async_launched", "agentId": "a1"}), _answer(T0 - 2983)]
    cases = [("(1) контекст 140 тыс.", dict(tokens=140_000)),
             ("(2) Зевс работает", dict(state="working")),
             ("(2) ход идёт: ответа на ввод нет", dict(extra_entries=[
                 {"type": "user", "timestamp": _iso(T0 - 2950), "message": {"role": "user", "content": "ещё"}}])),
             ("(3) фоновая команда", dict(extra_entries=bash_bg)),
             ("(3) фоновый субагент", dict(extra_entries=agent_bg)),
             ("(4) открыт AskUserQuestion", dict(extra_entries=ask)),
             ("(5) доска и handoff старше хода", dict(saved=False))]
    for what, kw in cases:
        e = zeus_env(**kw)
        e.run("watch", t=T0, extra=ZEUS_RUN)
        check(not zeus_actions(e) and "Зевс очищен" not in e.alerts(), f"{what}: очистка всё равно была: {e.calls()}")
    # (6) только что ответил — владелец, скорее всего, читает: ни очистки, ни напоминания; через 20 мин — очистка
    fresh_turn = [{"type": "user", "timestamp": _iso(T0 - 700), "message": {"role": "user", "content": "и что?"}},
                  _answer(T0 - 600)]
    e = zeus_env(extra_entries=fresh_turn, saved=T0 - 500)
    e.run("watch", t=T0, extra=ZEUS_RUN)
    check(not zeus_actions(e) and "Зевс очищен" not in e.alerts() and "сверь доску" not in e.alerts(),
          f"(6) ответ 10 мин назад: Зевса тронули: {e.calls()} {e.alerts()[-300:]}")
    e.run("watch", t=T0 + 700, extra=ZEUS_RUN)
    check(e.alerts().count("Зевс очищен") == 1, f"(6) через 21 мин после ответа очистки нет: {e.alerts()[-300:]}")
    # (3) снят: уведомление о конце фоновой задачи пришло — очистка идёт
    done = {"type": "user", "timestamp": _iso(T0 - 2970), "origin": {"kind": "task-notification"}, "message": {
        "role": "user", "content": "<task-notification>\n<task-id>a1</task-id>\n<tool-use-id>toolu_ag1</tool-use-id>"
        "\n<status>completed</status>\n</task-notification>"}}
    e = zeus_env(extra_entries=agent_bg + [done, _answer(T0 - 2960)])
    e.run("watch", t=T0, extra=ZEUS_RUN)
    check(len([c for c in zeus_actions(e) if c[:1] == ["--bg"]]) == 1, f"субагент закончил — а очистки нет: {e.calls()}")

    # защиты дежурного держат: остановлен вами, технический перезапуск, карантин ~/.claude
    def stopped(e):
        os.makedirs(e.st("stopped"), exist_ok=True)
        open(e.st("stopped", "zeus"), "w").write("вы\n")

    def maint(e):
        json.dump({"reason": "обновление", "expires": T0 + 3600, "sessions": ["zeus"]}, open(e.st("maintenance.json"), "w"))

    def held(e):
        os.makedirs(os.path.join(e.home, ".claude"), exist_ok=True)
        open(os.path.join(e.home, ".claude", ".sync-held"), "w").write("task=x\n")
    for what, setup in [("остановлен вами", stopped), ("техперезапуск", maint), ("карантин", held)]:
        e = zeus_env()
        setup(e)
        e.run("watch", t=T0, extra=ZEUS_RUN)
        check(not zeus_actions(e), f"{what}: Зевса всё равно очистили: {e.calls()}")

    # только (5): напоминание — строка в тревогах и сброс метки Stop-хука; не чаще раза в час и только после нового хода
    e = zeus_env(saved=False)
    mark = e.st("ctx", "marks", ZEUS_SID)
    os.makedirs(os.path.dirname(mark), exist_ok=True)
    open(mark, "w").write("160000")
    e.run("watch", t=T0, extra=ZEUS_RUN)
    check(e.alerts().count("сверь доску и handoff") == 1 and not os.path.exists(mark) and not zeus_actions(e),
          f"нет напоминания при несохранённом: {e.alerts()[-400:]}")
    e.run("watch", t=T0 + 600, extra=ZEUS_RUN)
    e.run("watch", t=T0 + 3700, extra=ZEUS_RUN)                     # час прошёл, а нового хода не было
    check(e.alerts().count("сверь доску и handoff") == 1, "напоминание повторилось без нового хода")
    with open(e.zeus_transcript, "a") as fh:
        fh.write(json.dumps({"type": "user", "timestamp": _iso(T0 + 3800), "message": {"role": "user", "content": "?"}})
                 + "\n" + json.dumps(_answer(T0 + 3810)) + "\n")
    e.run("watch", t=T0 + 3900, extra=ZEUS_RUN)                     # ответ 90 с назад — (6): напоминания нет
    check(e.alerts().count("сверь доску и handoff") == 1, "напоминание, пока владелец читает ответ")
    e.run("watch", t=T0 + 5100, extra=ZEUS_RUN)
    check(e.alerts().count("сверь доску и handoff") == 2, "после нового хода и часа напоминания нет")
    with open(e.zeus_transcript, "a") as fh:                        # новый ход, но час с напоминания не прошёл
        fh.write(json.dumps({"type": "user", "timestamp": _iso(T0 + 5200), "message": {"role": "user", "content": "!"}})
                 + "\n" + json.dumps(_answer(T0 + 5210)) + "\n")
    e.run("watch", t=T0 + 6500, extra=ZEUS_RUN)
    check(e.alerts().count("сверь доску и handoff") == 2, "напоминание чаще раза в час")

    # повторная проверка под блокировкой: между проходом и claude stop Зевс взял работу — не трогать
    e = zeus_env()
    z = json.load(open(e.agents_file))
    z[0].update(state="working", status="busy")
    nxt = os.path.join(e.home, "agents-next.json")
    json.dump(z, open(nxt, "w"))
    e.run("watch", t=T0, extra={**ZEUS_RUN, "FAKE_AGENTS_NEXT": nxt})
    check(not zeus_actions(e) and "Зевс очищен" not in e.alerts() and "не вышла" not in e.alerts(),
          f"Зевс взял работу перед остановкой — а его остановили: {e.calls()} {e.alerts()[-300:]}")
    e.run("watch", t=T0 + 60, extra=ZEUS_RUN)                       # снова ждёт — следующий проход чистит
    check(e.alerts().count("Зевс очищен") == 1, f"после отказа проверки следующий проход не очистил: {e.calls()}")

    # свежий старт не вышел: тревога одна, сессия не помечена очищенной, повтор — не раньше чем через час
    e = zeus_env()
    e.run("watch", t=T0, extra={**QUICK, "PANTHEON_STOP_WAIT": "0.1"})  # claude stop не останавливает
    e.run("watch", t=T0 + 600, extra={**QUICK, "PANTHEON_STOP_WAIT": "0.1"})
    check(e.alerts().count("очистка Зевса не вышла") == 1 and "Зевс очищен" not in e.alerts(),
          f"неудачная очистка: нет одной тревоги или повтор раньше часа: {e.alerts()[-500:]}")
    e.run("watch", t=T0 + 3700, extra=ZEUS_RUN)
    check(e.alerts().count("Зевс очищен") == 1, f"через час после неудачи очистки нет: {e.alerts()[-400:]}")


def test_zeus_clean_trace_0207():
    """metis-0207: каждый исход очистки Зевса виден. Все шесть условий — zeus-clean.json (cleared, last) и строка
    fresh-start в start.log; не выполнено (1), (3), (4), (5) или держит защита — fresh-skip с причиной, один раз, пока
    причина не сменилась; (2) и (6) — только в zeus-clean.json. Держание ~/.claude без вопроса (solo) очистку не держит."""
    e = zeus_env()
    e.run("watch", t=T0, extra=ZEUS_RUN)
    st = json.load(open(e.st("zeus-clean.json"))) if os.path.exists(e.st("zeus-clean.json")) else {}
    check(ZEUS_SID in (st.get("cleared") or []) and (st.get("last") or {}).get("result") == "очищен",
          f"очистка без следа в zeus-clean.json: {st}")
    check("fresh-start\tzeus\t2e057e05\ttick\t0\tочистка Зевса, контекст 160 тыс." in _start_log(e),
          f"нет строки fresh-start в start.log: {_start_log(e)!r}")

    ask = [_tool("AskUserQuestion", "toolu_ask1", {"questions": []}, T0 - 2980)]
    bash_bg = [_tool("Bash", "toolu_bg1", {"command": "sleep 999", "run_in_background": True}, T0 - 2985),
               _result("toolu_bg1", T0 - 2984, "Command running in background with ID: b1", {"backgroundTaskId": "b1"}),
               _answer(T0 - 2983)]

    def held(text):
        def setup(e):
            os.makedirs(os.path.join(e.home, ".claude"), exist_ok=True)
            open(os.path.join(e.home, ".claude", ".sync-held"), "w").write(text)
        return setup

    def stopped(e):
        os.makedirs(e.st("stopped"), exist_ok=True)
        open(e.st("stopped", "zeus"), "w").write("вы\n")
    cases = [("(1) контекст 140 тыс. < 150 тыс.", dict(tokens=140_000), None),
             ("(3) фоновые задачи: toolu_bg1", dict(extra_entries=bash_bg), None),
             ("(4) открыт вопрос AskUserQuestion", dict(extra_entries=ask), None),
             ("(5) не сохранено после последнего хода", dict(saved=False), None),
             ("(0) карантин правок ~/.claude ждёт ответа на metis-0187", {}, held("hash=a\ntask=metis-0187\nfiles=1\n")),
             ("(0) остановлен вами", {}, stopped)]
    for why, kw, setup in cases:
        e = zeus_env(**kw)
        if setup:
            setup(e)
        e.run("watch", t=T0, extra=ZEUS_RUN)
        e.run("watch", t=T0 + 300, extra=ZEUS_RUN)                   # причина та же — строка не повторяется
        log = _start_log(e)
        skips = [ln for ln in log.splitlines() if "\tfresh-skip\tzeus\t2e057e05\ttick\t" in ln]
        check(not zeus_actions(e) and len(skips) == 1 and why in skips[0] and why in " ".join(_zeus_last(e).get("miss") or []),
              f"{why}: нет одной строки fresh-skip с причиной или следа в zeus-clean.json: {log!r} {_zeus_last(e)}")
    # (2) и (6) — обычное дело: причина в zeus-clean.json, журнал не засоряется
    fresh_turn = [{"type": "user", "timestamp": _iso(T0 - 700), "message": {"role": "user", "content": "и что?"}},
                  _answer(T0 - 600)]
    for why, kw in [("(2) идёт ход", dict(state="working")), ("(6) с конца хода меньше 20 мин",
                                                              dict(extra_entries=fresh_turn, saved=T0 - 500))]:
        e = zeus_env(**kw)
        e.run("watch", t=T0, extra=ZEUS_RUN)
        last = _zeus_last(e)
        check(not zeus_actions(e) and "fresh-skip" not in _start_log(e) and last.get("result") == "пропуск"
              and any(m.startswith(why) for m in last.get("miss") or []), f"{why}: след не тот: {last} {_start_log(e)!r}")
    # sync.sh держит правку без вопроса (solo=1, task пустой) — ответа не будет, очистка идёт
    e = zeus_env()
    held("hash=a6202ffbaa71\ntask=\nfiles=4\nsolo=1\n")(e)
    e.run("watch", t=T0, extra=ZEUS_RUN)
    check(len([c for c in zeus_actions(e) if c[:1] == ["--bg"]]) == 1 and "\tfresh-start\tzeus\t" in _start_log(e),
          f"держание без вопроса блокирует очистку: {e.calls()} {_start_log(e)!r}")


def test_fresh_on_all_resume_paths_0207():
    """metis-0207: правило свежего старта (контекст > 100 тыс., простой > 60 мин) — на любом пути возобновления, а не
    только в resume_or_start и pantheon wake: ждущая сессия с задачей (wake-waiting) и техперезапуск (restart --go)."""
    e = Env()
    e.direction("fw-dir")
    e.task("fw-0001", "fw-dir")
    a = bg("fw-dir", "blocked", "fafafafa-1")
    e.agents([a])
    transcript(e, a, 130_000, T0 - 7200)
    r = e.run("watch", t=T0, extra=ZEUS_RUN)                      # claude stop в самом деле останавливает
    c = e.calls()
    new = [x for x in c if "--bg" in x]
    check(not [x for x in c if x[:1] == ["respawn"] or "--resume" in x] and len(new) == 1
          and new[0][:5] == ["--bg", "--agent", "domain-coordinator", "--name", "fw-dir"]
          and "[Пантеон: свежий старт]" in new[0][-1] and "fw-0001" in new[0][-1]
          and "\tfresh-start\tfw-dir\tfafafafa\twake-waiting\t0\t" in _start_log(e),
          f"ждущая сессия после долгого простоя — не свежий старт: {c} {_start_log(e)!r} {r.stderr[-400:]}")

    e = Env()
    e.direction("rg-dir")
    a = bg("rg-dir", "working", "dededede-1", pid=21)
    e.agents([a])
    transcript(e, a, 130_000, T0 - 7200)
    e.run("restart", "--prepare", "обновление", t=T0)
    e.run("saved", "--by", "rg-dir", "--state", "STATUS.md", t=T0 + 20)
    r = e.run("restart", "--go", t=T0 + 40, extra={"PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1"})
    check("[fresh] rg-dir" in r.stdout and "[resume] rg-dir" not in r.stdout,
          f"restart --go после долгого простоя — не свежий старт: {r.stdout[-500:]} {r.stderr[-300:]}")


def test_fresh_path_recheck_0207():
    """metis-0207 (argus PR #44): на пути свежего старта в resume_session recheck под блокировкой имени действует так
    же, как на обычном пути: сессия с контекстом 130 тыс. и простоем 2 ч не останавливается и не пересоздаётся."""
    # 1) recheck вернул причину (метка stopped появилась) — ни claude stop, ни --bg, строка resume-skip
    e = Env()
    e.direction("fr-dir")
    a = bg("fr-dir", "blocked", "fcfcfcfc-1")
    e.agents([a])
    transcript(e, a, 130_000, T0 - 7200)
    r = e.run(LIB, json.dumps(a), t=T0,
              extra=QUICK, argv=[PY311, "-I", "-c", _DIRECT_RESUME])
    c = e.calls()
    check(r.stdout.strip() == "(4, None)" and not [x for x in c if x[:1] == ["stop"] or "--bg" in x]
          and "\tresume-skip\tfr-dir\tfcfcfcfc\twake-waiting\tостановлено вами" in _start_log(e),
          f"recheck на пути свежего старта не остановил подъём: {r.stdout!r} {c} {_start_log(e)!r} {r.stderr[-400:]}")


def test_fresh_path_busy_0207():
    """metis-0207 (argus PR #44): занятая блокировка имени на пути свежего старта — отказ, а не остановка сессии."""
    import fcntl
    # имя занято (блокировка start-<имя> взята) — ни claude stop, ни --bg, строка resume-busy
    e = Env()
    e.direction("fb-dir")
    e.task("fb-0001", "fb-dir")
    a = bg("fb-dir", "blocked", "fdfdfdfd-1")
    e.agents([a])
    transcript(e, a, 130_000, T0 - 7200)
    os.makedirs(e.st("hq-rw", "locks"), exist_ok=True)  # замки имён сессий — в STATE/hq-rw/locks (metis-0523)
    with open(e.st("hq-rw", "locks", "start-fb-dir.lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        e.run("watch", t=T0, extra=ZEUS_RUN)
    c = e.calls()
    check(not [x for x in c if x[:1] == ["stop"] or "--bg" in x or x[:1] == ["respawn"]]
          and "\tresume-busy\tfb-dir\tfdfdfdfd\twake-waiting" in _start_log(e),
          f"занятая блокировка имени на пути свежего старта проигнорирована: {c} {_start_log(e)!r}")


def test_resume_copy_note():
    """--resume сделал копию — строка в тревогах."""
    e = Env()
    e.direction("cp-dir")
    e.agents([bg("cp-dir", "failed", "eeeeeeee-1")])
    e.run("wake", "cp-dir", t=T0, extra={"FAKE_RESPAWN_RC": "1", "FAKE_RESUME_OUT": "note: session is running; started a copy as 0123abcd"})
    check("сделал копию 0123abcd" in e.alerts(), "копия после --resume не замечена")
    # metis-0081 п. 4: копию сразу убираем — stop, затем rm без насильных флагов; исходная не тронута
    c = e.calls()
    check(["stop", "0123abcd"] in c and ["rm", "0123abcd"] in c and c.index(["stop", "0123abcd"]) < c.index(["rm", "0123abcd"])
          and not [x for x in c if x[:2] in (["stop", "eeeeeeee"], ["rm", "eeeeeeee"]) or "--discard-unpushed" in x],
          f"копия по COPY_NOTE не убрана или тронута исходная: {c}")
    check("копия убрана" in e.alerts() and "copy-removed\tcp-dir\t0123abcd\n" in _start_log(e),
          f"нет следа уборки копии: {e.alerts()!r}")
    # отказ rm (незапушенная работа) — копия остаётся, тревога говорит об этом
    e2 = Env()
    e2.direction("cq-dir")
    e2.agents([bg("cq-dir", "failed", "eeeeeeee-1")])
    e2.run("wake", "cq-dir", t=T0, extra={"FAKE_RESPAWN_RC": "1", "FAKE_RM_REFUSE": "0123abcd",
                                          "FAKE_RESUME_OUT": "note: session is running; started a copy as 0123abcd"})
    check("копию убрать не вышло" in e2.alerts() and "refused" in _start_log(e2),
          f"отказ rm копии без тревоги: {e2.alerts()!r}")


def test_reap_log():
    """metis-0081 п. 3: каждый claude rm — строка в logs/reap.log (время, имя, id, причина, транскрипт, хост); отказ rm строки
    не даёт; транскрипт не тронут."""
    e = Env()
    e.direction("rl-dir")
    e.direction("rn-dir")
    tr = os.path.join(e.home, ".claude", "projects", "-x", "c1c1c1c1-aaaa.jsonl")
    os.makedirs(os.path.dirname(tr))
    open(tr, "w").write("{}\n")
    e.agents([bg("rl-dir", "working", "c1c1c1c1-1", pid=61), bg("rn-dir", "working", "c2c2c2c2-1", pid=62)])
    e.run("stop", "rl-dir", t=T0)
    e.run("stop", "rn-dir", t=T0, extra={"FAKE_RM_REFUSE": "c2c2c2c2"})
    rows = [ln.split("\t") for ln in open(e.st("logs", "reap.log")).read().splitlines()]
    check(len(rows) == 1 and rows[0][1:5] == ["rl-dir", "c1c1c1c1", "stop", tr] and len(rows[0]) == 6,
          f"reap.log неверен: {rows}")
    check(os.path.exists(tr), "транскрипт тронут")


def test_maintenance():
    """Техперезапуск: метка с сроком, самозапуск и wake стоят; --go перезапускает сохранившихся один раз;
    истёкшая метка снимается с тревогой."""
    e = Env()
    e.direction("mm-dir")
    e.direction("nn-dir")
    e.agents([bg("mm-dir", "working", "mmmmmmmm-1", pid=21), bg("nn-dir", "working", "nnnnnnnn-1", pid=22)])
    r = e.run("restart", "--prepare", "обновление", t=T0)
    m = json.load(open(e.st("maintenance.json")))
    check(m["sessions"] == ["mm-dir", "nn-dir"] and m["expires"] == T0 + 7200, f"метка: {m} {r.stderr}")
    out = e.run("wake", "mm-dir", t=T0 + 10)
    check(out.returncode == 0 and "пропуск: mm-dir — " in out.stdout and "технический перезапуск" in out.stdout
          and "поднимаю" not in out.stdout, f"wake при метке: {out.stdout!r} {out.stderr!r}")
    r = e.run("saved", "--by", "mm-dir", "--state", "STATUS.md", t=T0 + 20)
    check(r.returncode == 0 and os.path.exists(e.st("maintenance", "mm-dir.json")), f"saved: {r.stderr}")
    check(e.run("restart", "--status", t=T0 + 30).returncode == 1, "status при несохранившейся")
    r = e.run("restart", "--go", t=T0 + 40, extra={"PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1"})
    check("[resume] mm-dir" in r.stdout and "не тронуты: nn-dir" in r.stdout, f"--go: {r.stdout}")
    check(os.path.exists(e.st("maintenance", "mm-dir.done")) and not os.path.exists(e.st("maintenance", "mm-dir.json")),
          "отметка перезапуска")
    r = e.run("restart", "--go", t=T0 + 50, extra={"PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1"})
    check("[resume] mm-dir" not in r.stdout and "mm-dir (раньше)" in r.stdout, f"повтор --go трогает перезапущенную: {r.stdout}")
    e.run("watch", t=T0 + 7300)
    check(not os.path.exists(e.st("maintenance.json")) and "истекла" in e.alerts(), "истёкшая метка не снята")


def test_restart_go_picks_saved_session_0421():
    """metis-0421: ожившая остановленная копия с тем же именем и более свежим startedAt не перехватывает restart --go:
    берётся сессия, записавшая pantheon saved (по id); нет записи id — прежний выбор и предупреждение в stderr."""
    go = {"PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1"}
    saved_id = "5a5a5a5a-1111-4111-8111-111111111111"
    for with_id in (True, False):
        e = Env()
        e.direction("sv-dir")
        e.agents([bg("sv-dir", "working", saved_id, pid=41, started=T0 - 500),
                  bg("sv-dir", "stopped", "bbbbbbbb-2222-4222-8222-222222222222", started=T0 - 10)])
        e.run("restart", "--prepare", "обновление", t=T0)
        sid_env = {"PANTHEON_SESSION": "sv-dir"}
        if with_id:
            sid_env["CLAUDE_CODE_SESSION_ID"] = saved_id
        r = e.run("saved", "--by", "sv-dir", "--state", "STATUS.md", t=T0 + 20, extra=sid_env)
        rec = json.load(open(e.st("maintenance", "sv-dir.json")))
        check(r.returncode == 0 and (rec.get("sessionId") == saved_id) == with_id, f"saved пишет id: {rec} {r.stderr}")
        r = e.run("restart", "--go", t=T0 + 40, extra=go)
        if with_id:
            check("[resume] sv-dir 5a5a5a5a" in r.stdout and "bbbbbbbb" not in r.stdout and "нет среди" not in r.stderr,
                  f"--go взял не сохранённую сессию: {r.stdout!r} {r.stderr!r}")
        else:
            check("[resume] sv-dir bbbbbbbb" in r.stdout and "нет id сессии" in r.stderr,
                  f"без id — прежний выбор с предупреждением: {r.stdout!r} {r.stderr!r}")
    # id записан, но такой сессии среди сессий с этим именем уже нет — прежний выбор и предупреждение
    e = Env()
    e.direction("sv-dir")
    e.agents([bg("sv-dir", "working", "bbbbbbbb-2222-4222-8222-222222222222", pid=42, started=T0 - 10)])
    e.run("restart", "--prepare", "обновление", t=T0)
    e.run("saved", "--by", "sv-dir", t=T0 + 20, extra={"PANTHEON_SESSION": "sv-dir", "CLAUDE_CODE_SESSION_ID": saved_id})
    r = e.run("restart", "--go", t=T0 + 40, extra=go)
    check("[resume] sv-dir bbbbbbbb" in r.stdout and "5a5a5a5a" in r.stderr, f"id не найден: {r.stdout!r} {r.stderr!r}")



def _owner_said(e, qid, question, answer, t):
    """Ответ владельца в owner-log/zeus.md, как его пишет хук окна вопросов: «вопрос: [qid] …» и «ответ: …»."""
    at = datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    with open(e.st("owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
        fh.write(f"\n## {at} · окно вопросов\nвопрос: [{qid}] {question}\nответ: {answer}\n")


def test_restart_only_one_window_1122():
    """metis-1122: pantheon restart --only <сессия> --owner <id> перезапускает одно окно без общего перезапуска и без
    метки saved (окно стоит на запросе разрешения), но только по «да» владельца на вопрос [id] с именем окна."""
    go = {"PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1"}
    e = Env()
    e.direction("mt-dir")
    e.direction("ot-dir")
    e.agents([bg("mt-dir", "blocked", "a1a1a1a1-1111-4111-8111-111111111111", pid=51),
              bg("ot-dir", "working", "b2b2b2b2-2222-4222-8222-222222222222", pid=52)])
    r = e.run("restart", "--only", "mt-dir", "--owner", "restart-1311", t=T0, extra=go)
    check(r.returncode == 1 and "[resume]" not in r.stdout and "нет «да» владельца" in r.stderr,
          f"без ответа владельца окно перезапущено: {r.returncode} {r.stdout!r} {r.stderr!r}")
    _owner_said(e, "restart-1311", "Перезапустить окно: ot-dir?", "Да", T0 - 60)
    r = e.run("restart", "--only", "mt-dir", "--owner", "restart-1311", t=T0, extra=go)
    check(r.returncode == 1 and "[resume]" not in r.stdout, f"«да» о другом окне перезапустило mt-dir: {r.stdout!r}")
    # Б1 argus PR #435: «да» на вопрос о другом действии, где окно лишь упомянуто, — не согласие на перезапуск;
    # и вопрос о перезапуске не строгой формы (имена не списком после двоеточия) — тоже
    for i, q in enumerate(("Пушить ветку mt-dir в origin?", "Перезапустить окно mt-dir?",
                           "Перезапустить окна: mt-dir и ot-dir?", "Перезапустить окна: ot-dir, mt-dir? Метиду не ждать",
                           "Перезапустить окна: mt-dir, ot-dir — кроме mt-dir?")):
        e1 = Env()
        e1.direction("mt-dir")
        e1.agents([bg("mt-dir", "blocked", "a1a1a1a1-1111-4111-8111-111111111111", pid=51)])
        _owner_said(e1, f"push-1311-{i}", q, "Да", T0 - 60)
        r = e1.run("restart", "--only", "mt-dir", "--owner", f"push-1311-{i}", t=T0, extra=go)
        check(r.returncode == 1 and "[resume]" not in r.stdout,
              f"«да» на «{q}» перезапустило mt-dir: {r.returncode} {r.stdout!r} {r.stderr!r}")
    _owner_said(e, "restart-1311", "Перезапустить окна: mt-dir, ot-dir?", "А — Да", T0 - 30)
    r = e.run("restart", "--only", "mt-dir", "--owner", "restart-1311", t=T0, extra=go)
    check(r.returncode == 0 and "[resume] mt-dir a1a1a1a1" in r.stdout and "ot-dir" not in r.stdout
          and "сохранения не ждал" in r.stdout, f"--only не перезапустил одно окно: {r.returncode} {r.stdout!r} {r.stderr!r}")
    check(not os.path.exists(e.st("maintenance.json")), "--only поставил метку общего перезапуска")
    # Б3 argus PR #435: одно «да» — один перезапуск окна; повтор с тем же id — отказ, код 2, причина последней строкой
    r = e.run("restart", "--only", "mt-dir", "--owner", "restart-1311", t=T0 + 5, extra=go)
    check(r.returncode == 2 and "[resume]" not in r.stdout and "уже использовано" in r.stderr.strip().splitlines()[-1],
          f"повтор того же «да» перезапустил окно: {r.returncode} {r.stdout!r} {r.stderr!r}")
    r = e.run("restart", "--only", "ot-dir", "--owner", "restart-1311", t=T0 + 6, extra=go)
    check(r.returncode == 0 and "[resume] ot-dir b2b2b2b2" in r.stdout,
          f"второе окно из того же списка не перезапущено: {r.returncode} {r.stdout!r} {r.stderr!r}")
    check(e.run("restart", "--only", "zeus", "--owner", "restart-1311", t=T0, extra=go).returncode == 2,
          "--only перезапускает Зевса")
    check(e.run("restart", "--only", "mt-dir", t=T0, extra=go).returncode == 2, "--only без --owner не код 2")
    # позднее «нет» на тот же вопрос отменяет «да»
    e3 = Env()
    e3.direction("mt-dir")
    e3.agents([bg("mt-dir", "blocked", "a1a1a1a1-1111-4111-8111-111111111111", pid=51)])
    _owner_said(e3, "restart-1311", "Перезапустить окна: mt-dir, ot-dir?", "Да", T0 - 30)
    _owner_said(e3, "restart-1311", "Перезапустить окна: mt-dir, ot-dir?", "Нет", T0 - 10)
    r = e3.run("restart", "--only", "mt-dir", "--owner", "restart-1311", t=T0, extra=go)
    check(r.returncode == 1 and "[resume]" not in r.stdout, f"«нет» после «да» не отменило: {r.stdout!r}")
    # имя-префикс: «да» на «Перезапустить окно: mt-dir2?» — не про mt-dir
    e4 = Env()
    e4.direction("mt-dir")
    e4.direction("mt-dir2")
    e4.agents([bg("mt-dir", "blocked", "a1a1a1a1-1111-4111-8111-111111111111", pid=51)])
    _owner_said(e4, "pre-1311", "Перезапустить окно: mt-dir2?", "Да", T0 - 30)
    r = e4.run("restart", "--only", "mt-dir", "--owner", "pre-1311", t=T0, extra=go)
    check(r.returncode == 1 and "[resume]" not in r.stdout, f"«да» про mt-dir2 перезапустило mt-dir: {r.stdout!r}")
    # окно вне Пантеона (нет в domains.json) — код 2, даже при «да» и живой сессии
    e4.agents([bg("mt-dir", "blocked", "a1a1a1a1-1111-4111-8111-111111111111", pid=51),
               bg("zz-out", "blocked", "c3c3c3c3-3333-4333-8333-333333333333", pid=53)])
    _owner_said(e4, "out-1311", "Перезапустить окно: zz-out?", "Да", T0 - 30)
    r = e4.run("restart", "--only", "zz-out", "--owner", "out-1311", t=T0, extra=go)
    check(r.returncode == 2 and "[resume]" not in r.stdout and "не окно Пантеона" in r.stderr,
          f"--only перезапустил окно вне Пантеона: {r.returncode} {r.stdout!r} {r.stderr!r}")
    # окно остановлено владельцем (метка stopped) — не трогаем, «да» не расходуется
    _owner_said(e4, "stop-1311", "Перезапустить окно: mt-dir?", "Да", T0 - 30)
    os.makedirs(e4.st("stopped"), exist_ok=True)
    open(e4.st("stopped", "mt-dir"), "w").close()
    r = e4.run("restart", "--only", "mt-dir", "--owner", "stop-1311", t=T0, extra=go)
    check(r.returncode == 1 and "[resume]" not in r.stdout and "остановлено вами" in r.stderr,
          f"--only перезапустил остановленное окно: {r.returncode} {r.stdout!r} {r.stderr!r}")
    os.remove(e4.st("stopped", "mt-dir"))
    r = e4.run("restart", "--only", "mt-dir", "--owner", "stop-1311", t=T0 + 1, extra=go)
    check(r.returncode == 0 and "[resume] mt-dir" in r.stdout, f"после снятия stopped: {r.returncode} {r.stderr!r}")
    # ответ старше суток — не согласие
    e2 = Env()
    e2.direction("mt-dir")
    e2.agents([bg("mt-dir", "blocked", "a1a1a1a1-1111-4111-8111-111111111111", pid=51)])
    _owner_said(e2, "restart-1311", "Перезапустить окно: mt-dir?", "Да", T0 - 2 * 86400)
    r = e2.run("restart", "--only", "mt-dir", "--owner", "restart-1311", t=T0, extra=go)
    check(r.returncode == 1 and "[resume]" not in r.stdout, f"ответ двухдневной давности сработал: {r.stdout!r}")


def test_restart_go_owner_forces_named_1122():
    """metis-1122: restart --go --owner <id> берёт без метки saved только окна, названные в вопросе [id] с «да»
    владельца; остальные несохранившиеся не трогает. Нет такого ответа — никто не перезапущен, код 1."""
    go = {"PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1"}
    e = Env()
    e.direction("mm-dir")
    e.direction("nn-dir")
    e.agents([bg("mm-dir", "blocked", "mmmmmmmm-1", pid=21), bg("nn-dir", "working", "nnnnnnnn-1", pid=22)])
    e.run("restart", "--prepare", "обновление", t=T0)
    # к --go mm-dir живёт копией с номером («mm-dir (2)»): сессии сверяются по имени без номера, как в --only
    e.agents([bg("mm-dir (2)", "blocked", "mmmmmmmm-1", pid=21), bg("nn-dir", "working", "nnnnnnnn-1", pid=22)])
    r = e.run("restart", "--go", "--owner", "restart-all-1311", t=T0 + 40, extra=go)
    check(r.returncode == 1 and "[resume]" not in r.stdout and "никто не перезапущен" in r.stderr
          and os.path.exists(e.st("maintenance.json")),
          f"--owner без ответа перезапустил: {r.stdout!r} {r.stderr!r}")
    # Б2 argus PR #435: имя в отрицании («кроме nn-dir») — не согласие; имена — только строгий список после двоеточия
    _owner_said(e, "all-1311", "Перезапустить всех, кроме nn-dir — его не трогать?", "Да", T0 + 30)
    r = e.run("restart", "--go", "--owner", "all-1311", t=T0 + 40, extra=go)
    check(r.returncode == 1 and "[resume]" not in r.stdout and os.path.exists(e.st("maintenance.json")),
          f"«кроме nn-dir» перезапустило окно: {r.returncode} {r.stdout!r} {r.stderr!r}")
    _owner_said(e, "restart-all-1311", "Перезапустить окна: mm-dir?", "Да", T0 + 30)
    r = e.run("restart", "--go", "--owner", "restart-all-1311", t=T0 + 40, extra=go)
    check("[resume] mm-dir" in r.stdout and "[resume] nn-dir" not in r.stdout and "не тронуты: nn-dir" in r.stdout,
          f"--go --owner: {r.stdout!r} {r.stderr!r}")
    # Б3: в новом перезапуске то же «да» окно без saved больше не берёт — код 2, причина последней строкой
    e.run("restart", "--cancel", t=T0 + 50)
    e.agents([bg("mm-dir", "blocked", "mmmmmmmm-1", pid=21), bg("nn-dir", "working", "nnnnnnnn-1", pid=22)])
    e.run("restart", "--prepare", "ещё раз", t=T0 + 60)
    r = e.run("restart", "--go", "--owner", "restart-all-1311", t=T0 + 70, extra=go)
    check(r.returncode == 2 and "[resume]" not in r.stdout and "уже использовано" in r.stderr.strip().splitlines()[-1],
          f"повтор --go --owner с тем же id: {r.returncode} {r.stdout!r} {r.stderr!r}")


def test_saved_by_copy_name_1122():
    """metis-1122 (13.11 20:58): копия «zeus (2)» — `pantheon saved --by 'zeus (2)'` и `--by zeus` оба принимаются;
    в списке перезапуска — имя без номера."""
    for by in ("zeus (2)", "zeus"):
        e = Env()
        e.direction("mm-dir")
        e.agents([bg("mm-dir", "working", "mmmmmmmm-1", pid=21), bg("zeus (2)", "working", "zzzzzzzz-1", pid=23)])
        e.run("restart", "--prepare", "обновление", t=T0)
        m = json.load(open(e.st("maintenance.json")))
        check("zeus" in m["sessions"] and "zeus (2)" not in m["sessions"], f"список с номером копии: {m['sessions']}")
        r = e.run("saved", "--by", by, "--state", "STATUS.md", t=T0 + 20)
        check(r.returncode == 0 and os.path.exists(e.st("maintenance", "zeus.json")),
              f"saved --by {by!r}: {r.returncode} {r.stdout!r} {r.stderr!r}")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
