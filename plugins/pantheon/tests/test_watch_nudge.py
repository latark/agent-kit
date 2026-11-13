#!/usr/bin/env python3
"""Дежурный, часть 7: подталкивание простаивающего, пропуск не сбой, проигранная гонка (общая часть — _watch_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403


def test_autostart_nudges_idle_holder_0212():
    """metis-0212: Claude Code сам перезапустил фоновую сессию, задания у неё нет (claude agents: `state` working,
    `status` idle), а у направления задача с вашей отметкой — не «уже работает», а передача задания той же сессии
    тем же текстом самозапуска (claude respawn + текст для хука push) и тревога «…задания у неё нет — передал
    задание». Работает — `status` busy или живые субагенты: тогда не трогаем. Закончила ход (`state` done с живым
    процессом) — тоже передача задания, а не только тревога Зевсу. Передача не помогла (снова простаивает,
    STATUS.md не менялся) — сбой самозапуска, а не новая передача на каждом проходе."""
    e = Env()
    e.direction("fl-dir")
    e.task("fl-0001", "fl-dir")
    e.run("watch", t=T0)
    e.board("fl-0001", T0 + 10)
    a = bg("fl-dir", "working", "f1ee7001-1", pid=41)
    a["status"] = "busy"
    e.agents([a])
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check("fl-dir: уже работает" in out, f"0212: status busy — не «уже работает»: {out}")
    a["status"] = "idle"
    a["inFlight"] = {"tasks": 1, "queued": 0, "kinds": ["agent"]}
    e.agents([a])
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check("fl-dir: уже работает" in out, f"0212: idle с живыми субагентами — не «уже работает»: {out}")
    del a["inFlight"]
    e.agents([a])
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check(f"fl-dir: {RESTARTED} — передал бы задание" in out, f"0212: dry-run не передаёт задание: {out}")
    e.run("watch", t=T0 + 120)
    check(["respawn", "f1ee7001"] in e.calls(), f"0212: перезапущенной сессии задание не передано: {e.calls()}")
    check(not [c for c in e.calls() if c[:1] == ["--bg"]], f"0212: вместо передачи задания новая сессия: {e.calls()}")
    pushed = e.st("push", "f1ee7001-1.txt")
    text = open(pushed).read() if os.path.exists(pushed) else ""
    check(text.startswith("[Пантеон: поручение от tick] Самозапуск дежурным") and "fl-0001" in text,
          f"0212: текст задания не тот, что у самозапуска: {text!r}")
    check(f"fl-dir: {RESTARTED} — передал задание" in e.alerts(), f"0212: нет тревоги: {e.alerts()}")
    os.remove(pushed)  # хук push забрал текст при старте процесса
    # следующий проход: сессия всё ещё простаивает — второй передачи нет (пауза между попытками)
    e.run("watch", t=T0 + 420)
    check(len([c for c in e.calls() if c[:1] == ["respawn"]]) == 1, f"0212: передача на каждом проходе: {e.calls()}")
    check(json.load(open(e.st("autostart.json")))["fl-dir"].get("fails") == 1,
          "0212: передача не помогла (снова простаивает, STATUS.md не менялся) — не засчитана сбоем")
    # закончила ход с живым процессом — тоже передача задания
    e2 = Env()
    e2.direction("dn-dir")
    e2.task("dn-0001", "dn-dir")
    e2.run("watch", t=T0)
    e2.board("dn-0001", T0 + 10)
    e2.agents([bg("dn-dir", "done", "d0ee7001-1", pid=42)])
    e2.run("watch", t=T0 + 120)
    check(["respawn", "d0ee7001"] in e2.calls(), f"0212: done с процессом — задание не передано: {e2.calls()}")
    check("dn-dir: закончила ход, а задачи с вашим решением ждут — передал задание" in e2.alerts(),
          f"0212: нет тревоги о передаче задания done: {e2.alerts()}")
    # вкладка (реестр) и status idle без отметки владельца не трогаются
    e3 = Env()
    e3.direction("nt-dir")
    e3.task("nt-0001", "nt-dir")
    b = bg("nt-dir", "working", "a0ee7001-1", pid=43)
    b["status"] = "idle"
    e3.agents([b])
    e3.run("watch", t=T0)
    e3.run("watch", t=T0 + 120)
    check(not [c for c in e3.calls() if c[:1] == ["respawn"]], f"0212: передача без вашей отметки: {e3.calls()}")


def test_autostart_nudge_backoff_after_success_0212():
    """metis-0212, ревью argus: сбой → удачная передача задания → следующая не раньше чем через час после неё.
    Успех стирает `next` (паузу после сбоя): иначе прошедший `next` пускал передачу на каждом проходе."""
    e, _ = idle_env("bk-dir", "b0ee7001-1")
    e.run("watch", t=T0 + 120)                              # передача 1
    os.remove(e.st("push", "b0ee7001-1.txt"))
    e.run("watch", t=T0 + 420)                              # снова простаивает, STATUS.md тот же — сбой 1
    st = json.load(open(e.st("autostart.json")))["bk-dir"]
    check(st.get("fails") == 1 and st.get("next"), f"0212: сбой не записан: {st}")
    t2 = T0 + 420 + 4000                                    # после паузы сбоя (1 ч ±10 %)
    e.run("watch", t=t2)                                    # передача 2
    check(len(respawns(e)) == 2, f"0212: после паузы сбоя задание не передано: {e.calls()}")
    os.remove(e.st("push", "b0ee7001-1.txt"))
    status = os.path.join(e.pantheon, "directions", "bk-dir", "STATUS.md")
    open(status, "w").write("сделано\n")
    os.utime(status, (t2 + 100, t2 + 100))                  # сессия поработала и записала STATUS.md — успех
    e.run("watch", t=t2 + 300)
    e.run("watch", t=t2 + 600)
    st = json.load(open(e.st("autostart.json")))["bk-dir"]
    check(len(respawns(e)) == 2, f"0212: после успеха передача раньше часа (старый next): {respawns(e)}")
    check(st.get("fails") == 0 and "next" not in st, f"0212: успех не сбросил fails и next: {st}")
    e.run("watch", t=t2 + 3700)
    check(len(respawns(e)) == 3, f"0212: через час после успеха задание не передано: {respawns(e)}")


def test_autostart_nudge_guards_0212():
    """metis-0212, ревью argus: задание не передаётся сессии, которая работает или ждёт — по state.json (`inFlight`),
    по разрешению (`waitingFor`), по своему пробуждению (ScheduleWakeup: `inFlight.wake`, вид session_cron,
    `selfWake`), — и направлению, которое вы остановили или поставили на паузу."""
    e, a = idle_env("gd-dir", "c0ee7001-1")

    def dry():
        return e.run("watch", "--dry-run", t=T0 + 120).stdout

    out = dry()
    check(f"gd-dir: {RESTARTED} — передал бы задание" in out, f"0212: исходное состояние — не передача: {out}")
    # живые субагенты видны только в state.json, а в claude agents их нет
    job_state(e, "c0ee7001-1", {"state": "working", "inFlight": {"tasks": 2, "queued": 0, "kinds": ["local_agent"]}})
    out = dry()
    check("gd-dir: уже работает" in out, f"0212: inFlight из state.json не прочитан: {out}")
    # закончила ход с ScheduleWakeup: Claude Code 2.1.302 кладёт пробуждение в inFlight и ставит selfWake
    wake = {"at": T0 * 1000, "fires": 0}
    for js in ({"inFlight": {"tasks": 1, "queued": 0, "kinds": ["session_cron"], "wake": wake}, "selfWake": True},
               {"inFlight": {"tasks": 0, "queued": 0, "kinds": ["session_cron"]}},
               {"inFlight": {"tasks": 0, "queued": 0, "kinds": [], "wake": wake}},
               {"inFlight": {"tasks": 0, "queued": 0, "kinds": []}, "selfWake": True}):
        job_state(e, "c0ee7001-1", dict(js, state="working"))
        out = dry()
        check("gd-dir: уже работает" in out, f"0212: назначенное пробуждение {js} — не «уже работает»: {out}")
    job_state(e, "c0ee7001-1", {"state": "working", "inFlight": {"tasks": 0, "queued": 0, "kinds": []}})
    check(f"gd-dir: {RESTARTED} — передал бы задание" in dry(), "0212: пустой inFlight в state.json мешает передаче")
    # ждёт вашего разрешения
    a["waitingFor"] = "permission"
    e.agents([a])
    out = dry()
    check("gd-dir: уже работает" in out, f"0212: ждёт разрешения — не «уже работает»: {out}")
    del a["waitingFor"]
    e.agents([a])
    # остановлено вами
    os.makedirs(e.st("stopped"), exist_ok=True)
    open(e.st("stopped", "gd-dir"), "w").write("вы\n")
    out = dry()
    check(f"gd-dir: {RESTARTED} — передача задания ждёт: остановлено вами" in out, f"0212: обход остановки: {out}")
    e.run("watch", t=T0 + 120)
    check(not respawns(e), f"0212: задание передано остановленному направлению: {e.calls()}")
    os.remove(e.st("stopped", "gd-dir"))
    # пауза по нагрузке этого направления и общая пауза планировщика
    os.makedirs(e.st("pauses"), exist_ok=True)
    json.dump({"reason": "manual", "time": "2026-10-15T07:00:00"}, open(e.st("pauses", "gd-dir.json"), "w"))
    out = dry()
    check("передача задания ждёт: пауза по нагрузке (manual)" in out, f"0212: обход паузы по нагрузке: {out}")
    e.run("watch", t=T0 + 120)
    check(not respawns(e), f"0212: задание передано на паузе по нагрузке: {e.calls()}")
    os.remove(e.st("pauses", "gd-dir.json"))
    open(e.st("paused"), "w").write("вы\n")
    out = dry()
    check(f"gd-dir: {RESTARTED} — передача задания ждёт:" in out, f"0212: обход общей паузы: {out}")
    e.run("watch", t=T0 + 120)
    check(not respawns(e), f"0212: задание передано на общей паузе: {e.calls()}")
    os.remove(e.st("paused"))
    e.run("watch", t=T0 + 120)
    check(["respawn", "c0ee7001"] in e.calls(), f"0212: без помех задание не передано: {e.calls()}")


def test_autostart_skip_not_failure_0708():
    """metis-0708: 02.11 21:46 проход увидел окно metis-pantheon простаивающим (working + idle между ходами), а под
    блокировкой имени свежий claude agents показал его занятым (пришло сообщение, status busy): resume_session вернул
    SKIPPED (код 4, resume-skip «уже работает»). Самозапуск счёл это сбоем — тревога «передать задание не вышло,
    код 4», «сбой 2 из 3» и пауза 2 ч, третий такой пропуск остановил бы самозапуск направления. Пропуск — не сбой:
    ни тревоги, ни счётчика, ни pending; то же у продолжения остановленной сессии (resume_or_start)."""
    e, a = idle_env("sk-dir", "5ee70001-1")
    nxt = os.path.join(e.tmp, "agents-next.json")
    json.dump([dict(a, status="busy")], open(nxt, "w"))
    e.run("watch", t=T0 + 120, extra={"FAKE_AGENTS_NEXT": nxt})
    st = json.load(open(e.st("autostart.json"))).get("sk-dir", {})
    check(not respawns(e) and "\tresume-skip\tsk-dir\t5ee70001\ttick\tуже работает" in _start_log(e),
          f"0708: занятому окну передано задание: {e.calls()} {_start_log(e)!r}")
    check("передать задание не вышло" not in e.alerts() and "сбой" not in e.alerts(),
          f"0708: пропуск занятого окна — ложная тревога: {e.alerts()}")
    check(not st.get("fails") and not st.get("pending") and not st.get("gave_up"),
          f"0708: пропуск засчитан сбоем: {st}")
    # три таких прохода подряд (каждый после паузы) — самозапуск не встаёт
    for i in (1, 2, 3):
        os.remove(nxt + ".seen")
        e.run("watch", t=T0 + 120 + i * 4000, extra={"FAKE_AGENTS_NEXT": nxt})
    st = json.load(open(e.st("autostart.json"))).get("sk-dir", {})
    check(not st.get("fails") and not st.get("gave_up") and "остановлен после" not in e.alerts(),
          f"0708: повторные пропуски остановили самозапуск: {st} {e.alerts()}")
    # окно освободилось — задание передаётся, как раньше (metis-0212)
    e.run("watch", t=T0 + 120 + 5 * 4000)
    check(["respawn", "5ee70001"] in e.calls(), f"0708: свободному окну задание не передано: {e.calls()}")
    # продолжение остановленной сессии: к подъёму имя уже держит новая — тоже пропуск, не «не вышло, код 4»
    e2 = Env()
    e2.direction("sr-dir")
    e2.task("sr-0001", "sr-dir")
    e2.run("watch", t=T0)
    e2.board("sr-0001", T0 + 10)
    e2.agents([bg("sr-dir", "stopped", "5ee70002-1")])
    nxt2 = os.path.join(e2.tmp, "agents-next.json")
    json.dump([bg("sr-dir", "stopped", "5ee70002-1"), bg("sr-dir", "working", "5ee70003-1", pid=45)], open(nxt2, "w"))
    e2.run("watch", t=T0 + 120, extra={"FAKE_AGENTS_NEXT": nxt2})
    st = json.load(open(e2.st("autostart.json"))).get("sr-dir", {})
    check(not [c for c in e2.calls() if c[:1] in (["respawn"], ["--bg"])]
          and "\tresume-skip\tsr-dir\t5ee70002\ttick\tуже работает" in _start_log(e2),
          f"0708: остановленная поднята, хотя имя уже держат: {e2.calls()} {_start_log(e2)!r}")
    check("не вышло, код 4" not in e2.alerts() and not st.get("fails") and not st.get("pending"),
          f"0708: пропуск продолжения засчитан сбоем: {st} {e2.alerts()}")
    # пропущенное имя держат — место занято: третье направление сверх AUTOSTART_MAX (2) в тот же проход не поднимается
    e3 = Env()
    for n in ("aa-dir", "bb-dir", "cc-dir"):
        e3.direction(n)
    for n in ("aa-dir", "bb-dir"):
        e3.task(n[:2] + "-0001", n)
    e3.run("watch", t=T0)
    for n in ("aa-dir", "bb-dir"):
        e3.board(n[:2] + "-0001", T0 + 10)
    cc = dict(bg("cc-dir", "working", "5ee700cc-1", pid=46), status="busy")
    e3.agents([bg("aa-dir", "stopped", "5ee700aa-1"), cc])
    nxt3 = os.path.join(e3.tmp, "agents-next.json")
    json.dump([bg("aa-dir", "stopped", "5ee700aa-1"), bg("aa-dir", "working", "5ee700ab-1", pid=47), cc],
              open(nxt3, "w"))
    e3.run("watch", t=T0 + 120, extra={"FAKE_AGENTS_NEXT": nxt3})
    bb = json.load(open(e3.st("autostart.json"))).get("bb-dir", {})
    check("\tresume-skip\taa-dir\t5ee700aa\ttick\tуже работает" in _start_log(e3) and not bb.get("last"),
          f"0708: после пропуска поднято третье направление: {bb} {e3.calls()} {_start_log(e3)!r}")
    check("самозапуск bb-dir ждёт: нет места" in e3.alerts(), f"0708: нет тревоги «нет места»: {e3.alerts()}")


def test_start_lost_race_skip_0717():
    """metis-0717: плановый проход проверил снимок (имя свободно) и пошёл `pantheon start --from tick`, а под блокировкой
    имени его уже держат (другой процесс поднимает или сессия уже стоит в списке) — проигранная гонка. Раньше код 1 и
    ложная тревога «не вышло, код 1»; теперь код 4 (P.skipped), как у resume_session после metis-0708, и строка
    start-busy / start-skip в start.log. Владелец (--from owner) и подложенная запись замка — по-прежнему код 1."""
    e = Env()
    e.direction("rc-dir")
    lk = e.st("hq-rw", "locks")
    os.makedirs(lk, exist_ok=True)
    lp = os.path.join(lk, "start-rc-dir.lock")
    holder = subprocess.Popen([PY311, "-I", "-c",
                               "import fcntl,os,sys,time\nfd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT,0o600)\n"
                               "fcntl.flock(fd,fcntl.LOCK_EX)\nprint('ok',flush=True)\ntime.sleep(60)", lp],
                              stdout=subprocess.PIPE, text=True)
    try:
        check(holder.stdout.readline().strip() == "ok", "0717: держатель замка не взял замок")
        r = e.run("start", "rc-dir", "--from", "tick", "задание", t=T0)
        check(r.returncode == 4 and not _bgs(e, "rc-dir") and "\tstart-busy\trc-dir\ttick" in _start_log(e),
              f"0717: гонка за замок имени — не код 4: {r.returncode} {r.stderr[-300:]} {_start_log(e)!r}")
        r = e.run("start", "rc-dir", "--from", "owner", "задание", t=T0)
        check(r.returncode == 1 and not _bgs(e, "rc-dir"), f"0717: владельцу замок занят — не код 1: {r.returncode}")
    finally:
        holder.kill()
        holder.wait()
    # живая копия под блокировкой: снимок до неё пуст, а теперь имя в списке
    e.agents([bg("rc-dir", "working", "7170aaaa-1", pid=48)])
    r = e.run("start", "rc-dir", "--from", "tick", "задание", t=T0 + 5)
    check(r.returncode == 4 and not _bgs(e, "rc-dir") and "\tstart-skip\trc-dir\ttick\tуже работает" in _start_log(e),
          f"0717: живая копия под замком — не код 4: {r.returncode} {r.stderr[-300:]} {_start_log(e)!r}")
    r = e.run("start", "rc-dir", "--from", "owner", "задание", t=T0 + 6)
    check(r.returncode == 1 and "уже работает" in r.stderr, f"0717: владельцу живая копия — не код 1: {r.returncode}")
    # подложенная запись на месте замка — не гонка: код 1 даже у tick
    e2 = Env()
    e2.direction("rd-dir")
    hl = e2.st("hq-rw", "locks")
    os.makedirs(hl, exist_ok=True)
    os.mkfifo(os.path.join(hl, "start-rd-dir.lock"))
    r = e2.run("start", "rd-dir", "--from", "tick", t=T0)
    check(r.returncode == 1 and "блокировка start-rd-dir не взята" in r.stderr, f"0717: fifo на месте замка у tick: {r.returncode} {r.stderr[-200:]}")
    # вкладка терминала под замком (в реестре сессий, без id в claude agents): остановить её по id нельзя — не гонка, код 1
    e3 = Env()
    e3.direction("re-dir")
    os.makedirs(os.path.join(e3.home, ".claude", "sessions"), exist_ok=True)
    json.dump({"pid": os.getpid(), "sessionId": "tab-0717", "name": "re-dir", "kind": "interactive", "cwd": "/tmp"},
              open(os.path.join(e3.home, ".claude", "sessions", f"{os.getpid()}.json"), "w"))
    r = e3.run("start", "re-dir", "--from", "tick", "задание", t=T0)
    check(r.returncode == 1 and "вкладке терминала" in r.stderr and "\tstart-skip\t" not in _start_log(e3),
          f"0717: живая вкладка без id у tick — не код 1: {r.returncode} {r.stderr[-300:]} {_start_log(e3)!r}")
    # метка LOCK_CONTENDED от прошлого lock() не переживает следующий вызов: отказ из-за подложенной записи — не гонка
    e4 = Env()
    r = e4.run(LIB, os.path.join(e4.state, "hq-rw", "locks"), t=T0, argv=[PY311, "-I", "-c", _DIRECT_LOCK_STALE])
    check(r.stdout.strip() == "None", f"0717: LOCK_CONTENDED пережил следующий lock(): {r.stdout!r} {r.stderr[-300:]}")


def test_watch_lost_race_no_alert_0717():
    """metis-0717 п. 2: проигранная гонка за имя глазами дежурного. Самозапуск видит имя свободным (снимок пуст) и зовёт
    `pantheon start --from tick`, а под блокировкой имени уже стоит живая копия (start-skip) или замок держит другой
    процесс (start-busy). Код 4 — пропуск: в alerts нет «не вышло, код 1» (и никакого «не вышло»), счётчика сбоев нет."""
    def env(name):
        e = Env()
        e.direction(name)
        e.task(name[:2] + "-0001", name)
        e.run("watch", t=T0)
        e.board(name[:2] + "-0001", T0 + 10)
        e.agents([])
        return e
    # живая копия под блокировкой: снимок прохода пуст, свежий claude agents у pantheon start её видит
    e = env("lr-dir")
    e.run("watch", t=T0 + 120, extra=_next_agents(e, [bg("lr-dir", "working", "7170bbbb-1", pid=49)]))
    st = json.load(open(e.st("autostart.json"))).get("lr-dir", {})
    check("\tstart-skip\tlr-dir\ttick\tуже работает" in _start_log(e),
          f"0717 п.2: гонка не дошла до pantheon start под блокировкой: {_start_log(e)!r} {e.calls()}")
    check("не вышло, код 1" not in e.alerts() and "не вышло" not in e.alerts() and "сбой" not in e.alerts(),
          f"0717 п.2: проигранная гонка (живая копия) — тревога в alerts: {e.alerts()}")
    check(not st.get("fails") and not st.get("pending"), f"0717 п.2: проигранная гонка засчитана сбоем: {st}")
    # замок имени держит другой процесс
    e2 = env("lb-dir")
    lk = e2.st("hq-rw", "locks")
    os.makedirs(lk, exist_ok=True)
    holder = subprocess.Popen([PY311, "-I", "-c",
                               "import fcntl,os,sys,time\nfd=os.open(sys.argv[1],os.O_WRONLY|os.O_CREAT,0o600)\n"
                               "fcntl.flock(fd,fcntl.LOCK_EX)\nprint('ok',flush=True)\ntime.sleep(60)",
                               os.path.join(lk, "start-lb-dir.lock")], stdout=subprocess.PIPE, text=True)
    try:
        check(holder.stdout.readline().strip() == "ok", "0717 п.2: держатель замка не взял замок")
        e2.run("watch", t=T0 + 120)
    finally:
        holder.kill()
        holder.wait()
    st = json.load(open(e2.st("autostart.json"))).get("lb-dir", {})
    check("\tstart-busy\tlb-dir\ttick" in _start_log(e2),
          f"0717 п.2: гонка за замок не дошла до pantheon start: {_start_log(e2)!r} {e2.calls()}")
    check("не вышло, код 1" not in e2.alerts() and "не вышло" not in e2.alerts() and "сбой" not in e2.alerts(),
          f"0717 п.2: проигранная гонка (замок) — тревога в alerts: {e2.alerts()}")
    check(not st.get("fails") and not st.get("pending"), f"0717 п.2: гонка за замок засчитана сбоем: {st}")


def test_skip_not_failure_other_paths_0708():
    """metis-0708, находка: пропуск под блокировкой имени (SKIPPED, код 4) — не сбой и в трёх других путях подъёма.
    Разовый запуск: не «не вышло, код 4» и без уведомления «не вышел» — запись снова ждёт до срока и идёт, когда окно
    освободилось. Продолжение после паузы: не «не поднялась, код 4». Запуск по ответу владельца: не «не вышло, код 4»."""
    # разовый запуск: остановленную сессию к подъёму сменила новая (повторная проверка — resume-skip)
    e, oid = _oneshot_env()
    e.agents([bg("athena-a", "stopped", "5ee70010-1")])
    held = [bg("athena-a", "stopped", "5ee70010-1"), bg("athena-a", "working", "5ee70011-1", pid=48)]
    e.run("watch", t=T0 + 660, extra=_next_agents(e, held))
    rec = _oneshot_rec(e, oid)
    check(not respawns(e) and not _resumed(e, "5ee70010-1") and "не вышло, код 4" not in e.alerts() and f"разовый запуск {oid} ждёт: пропуск" in e.alerts(),
          f"0708: разовый запуск — пропуск засчитан сбоем: {e.calls()} {e.alerts()}")
    check(not rec.get("done_at") and "пропуск" in str(rec.get("wait")),
          f"0708: разовый запуск после пропуска погашен: {rec}")
    check("не вышел" not in e.sent() and f"oneshot-{oid}" not in e.queued(),
          f"0708: уведомление «не вышел» о пропуске: {e.sent()!r} {e.queued()}")
    # тот же пропуск ещё два прохода подряд — тревога «ждёт: пропуск» не повторяется (одна строка, а не строка на проход)
    for dt in (690, 705):
        e.run("watch", t=T0 + dt, extra=_next_agents(e, held))
    n_wait = e.alerts().count(f"разовый запуск {oid} ждёт: пропуск")
    check(n_wait == 1 and not _resumed(e, "5ee70010-1") and not _oneshot_rec(e, oid).get("done_at"),
          f"0708: тревога «разовый запуск … ждёт: пропуск» {n_wait} раз за 3 прохода: {e.alerts()} {_oneshot_rec(e, oid)}")
    e.run("watch", t=T0 + 720)                                 # окно свободно — запись исполняется
    check(_resumed(e, "5ee70010-1") and _oneshot_rec(e, oid).get("done_at"),
          f"0708: разовый запуск после пропуска не пошёл: {e.calls()} {_oneshot_rec(e, oid)}")
    # продолжение после паузы: остановленную паузой сессию к подъёму сменила новая
    e2 = Env()
    e2.direction("p1-dir")
    e2.agents([bg("p1-dir", "working", "5ee70020-1", pid=41)])
    e2.run("pause", "p1-dir", "--reason", "limit", "лимит 80", t=T0)
    e2.agents([bg("p1-dir", "stopped", "5ee70020-1")])
    nxt = _next_agents(e2, [bg("p1-dir", "stopped", "5ee70020-1"), bg("p1-dir", "working", "5ee70021-1", pid=42)])
    e2.run("watch", t=T0 + 120, extra={"PANTHEON_FAKE_LIMIT": "20", **nxt})
    check(not any("5ee70020-1" in c for c in e2.calls() if "--resume" in c)
          and not os.path.exists(e2.st("pauses", "p1-dir.json")),
          f"0708: после паузы поднята остановленная, хотя имя держат: {e2.calls()}")
    check("не поднялась, код 4" not in e2.alerts() and "p1-dir после паузы: пропуск" in e2.alerts(),
          f"0708: пропуск после паузы — ложная тревога: {e2.alerts()}")
    # запуск по ответу владельца: окно поднял другой процесс между снимком и блокировкой
    e3 = Env()
    e3.direction("wl-dir")
    e3.agents([bg("wl-dir", "stopped", "5ee70030-1")])
    e3.run("watch", t=T0)
    _zeus_answer(e3, T0 + 30, "[metis-0523] Запустить wl-dir?", "Да — запустить wl-dir")
    e3.run("watch", t=T0 + 60, extra=_next_agents(e3, [bg("wl-dir", "stopped", "5ee70030-1"),
                                                         bg("wl-dir", "working", "5ee70031-1", pid=43)]))
    wl = [r for r in _start_rows(e3) if r[1:2] == ["word-launch"]]
    check(not _bgs(e3, "wl-dir") and not _resumed(e3, "5ee70030-1") and wl and wl[-1][-1].startswith("пропуск"),
          f"0708: запуск по ответу — пропуск не записан: {e3.calls()} {wl}")
    check("не вышло, код 4" not in e3.alerts(), f"0708: запуск по ответу — ложная тревога: {e3.alerts()}")


def test_autostart_nudge_week_limit_0212():
    """metis-0212, ревью argus-43: передача задания простаивающей сессии — новое дело и ждёт недельный лимит, как
    новый запуск (gate «autostart»): жёлтая зона днём, красная, снимок старше 30 мин — ни respawn, ни новой сессии,
    в dry-run «передача задания ждёт: недельный лимит: …»; зелёная — задание передано. Жёлтую днём и старый снимок
    gate продолжения («respawn» в wake_block) пропускает — их ловит только проверка самозапуска."""
    e, _ = idle_env("wk-dir", "e0ee7001-1")
    cases = ((31.6, 0, "жёлтая зона днём"), (90.0, 0, "красная зона"), (10.0, 31 * 60, "лимит неизвестен (31 мин)"))
    for i, (pct, age, why) in enumerate(cases):
        e.week_pct, e.snap_age = pct, age
        out = e.run("watch", "--dry-run", t=T0 + 120 + i).stdout
        check(f"wk-dir: {RESTARTED} — передача задания ждёт: недельный лимит: {why}" in out,
              f"0212: неделя {pct} %, снимок {age} с — передача задания мимо недельного лимита: {out[-500:]}")
        e.run("watch", t=T0 + 130 + i)
        check(not respawns(e) and not [c for c in e.calls() if c[:1] == ["--bg"]],
              f"0212: неделя {pct} %, снимок {age} с — задание передано: {e.calls()}")
    e.week_pct, e.snap_age = 10.0, 0
    e.run("watch", t=T0 + 200)
    check(["respawn", "e0ee7001"] in e.calls(), f"0212: зелёная неделя — задание не передано: {e.calls()}")


def test_plugins_respawn_live_subagent_0181():
    """metis-0181: окно idle (закончило ход), а его субагент писал 5 мин назад — лид работает, окно не перезапускается,
    отметка стоит; субагент затих 15+ мин назад — перезапуск, отметка снята, строка в тревогах."""
    e, a, tp = respawn_env("rs-dir", "a5a5a5a5-1")
    sub = subagent(tp, T0 - 300)
    e.run("watch", t=T0)
    check(not respawned(e, "a5a5a5a5") and os.path.exists(e.st("plugins", "respawn.json")),
          f"0181: idle с субагентом, писавшим 5 мин назад, перезапущено: {e.calls()}")
    os.utime(sub, (T0 - 1200, T0 - 1200))
    r = e.run("watch", t=T0 + 60)
    check(respawned(e, "a5a5a5a5"), f"0181: субагент затих 20 мин назад — не перезапущено: {e.calls()} {r.stderr[-300:]}")
    pushed = e.st("push", "a5a5a5a5-1.txt")
    check(os.path.exists(pushed) and "[Пантеон: перезапуск после обновления плагинов]" in open(pushed).read(),
          "0181: перезапуску не передан текст «перезапуск после обновления плагинов»")
    check(not os.path.exists(e.st("plugins", "respawn.json")), "0181: все перезапущены — отметка не снята")
    check("перезапуск после обновления плагинов (pantheon): перезапущены rs-dir" in e.alerts(),
          f"0181: нет строки в тревогах: {e.alerts()}")


def test_plugins_respawn_quiet_subagent_0864():
    """metis-0864: субагент без «finished» в meta.json, затихший 20 мин назад (ждёт тесты), — живой: окно после выпуска
    не перезапускается, причина видна в строке «ждёт». Субагент закончил («finished») — перезапуск. Оборванный прошлым
    перезапуском (журнал старше старта процесса) и затихший дольше LIVE_SUBAGENT_MAX — мёртвые, окно не держат."""
    e, a, tp = respawn_env("rq-dir", "abab0864-1")
    a["startedAt"] = (T0 - 7200) * 1000
    e.agents([a])
    subagent(tp, T0 - 1200, n="q1")
    sub_meta(tp, "q1", T0 - 1200)
    e.run("watch", t=T0)
    check(not respawned(e, "abab0864") and "rq-dir (живые субагенты: dev-q1)" in e.alerts(),
          f"0864: тихий живой субагент — окно перезапущено или причины нет: {e.calls()} {e.alerts()[-400:]}")
    sub_meta(tp, "q1", T0 - 1200, finished=True)
    e.run("watch", t=T0 + 60)
    check(respawned(e, "abab0864"), f"0864: субагент закончил — окно не перезапущено: {e.calls()}")
    # оборванный прошлым перезапуском: журнал и meta — до старта нынешнего процесса
    e, a, tp = respawn_env("rd-dir", "cdcd0864-1")
    a["startedAt"] = (T0 - 7200) * 1000
    e.agents([a])
    subagent(tp, T0 - 7210, n="d1")
    sub_meta(tp, "d1", T0 - 7210)
    e.run("watch", t=T0)
    check(respawned(e, "cdcd0864"), f"0864: субагент, оборванный прошлым перезапуском, держит окно: {e.calls()}")
    e, a, tp = respawn_env("rs2-dir", "efef0864-1")
    a["startedAt"] = (T0 - 5 * 3600) * 1000
    e.agents([a])
    subagent(tp, T0 - 4 * 3600, n="s1")
    sub_meta(tp, "s1", T0 - 4 * 3600)
    e.run("watch", t=T0)
    check(respawned(e, "efef0864"), f"0864: субагент молчит 4 ч (больше LIVE_SUBAGENT_MAX) — держит окно: {e.calls()}")


def test_plugins_respawn_live_rule_0904():
    """metis-0904: watch берёт правило «живой» из lib/live_subagent.py, общее с хуком ctx. Субагент с «finished», чья
    фоновая команда ещё без итога (Bash ушёл в фон), — живой: окно не перезапускается; итог пришёл — перезапуск.
    Субагент, запущенный в первые LIVE_GRACE с после старта процесса (первая запись журнала позже старта), — живой,
    хотя журнал писался в пределах LIVE_GRACE."""
    bg = {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "content": "Command running in background with ID: bq1. Output x"}]}}
    note = {"type": "user", "message": {"role": "user", "content":
            "<task-notification>\n<task-id>bq1</task-id>\n<status>completed</status>\n</task-notification>"}}
    e, a, tp = respawn_env("rb-dir", "abcd0904-1")
    a["startedAt"] = (T0 - 7200) * 1000
    e.agents([a])
    sub_journal(tp, "b1", T0 - 1200, [{"type": "user", "message": {"role": "user", "content": "поручение"}}, bg])
    sub_meta(tp, "b1", T0 - 1200, finished=True)
    e.run("watch", t=T0)
    check(not respawned(e, "abcd0904") and "rb-dir (живые субагенты: dev-b1)" in e.alerts(),
          f"0904: finished с фоновой командой без итога — окно перезапущено: {e.calls()} {e.alerts()[-400:]}")
    sub_journal(tp, "b1", T0 - 1200, [{"type": "user", "message": {"role": "user", "content": "поручение"}}, bg, note])
    e.run("watch", t=T0 + 60)
    check(respawned(e, "abcd0904"), f"0904: итог фоновой пришёл — окно не перезапущено: {e.calls()}")
    # запущен через 10 с после старта, журнал последний раз писался через 60 с (в пределах LIVE_GRACE)
    e, a, tp = respawn_env("rg-dir", "dcba0904-1")
    a["startedAt"] = (T0 - 3600) * 1000
    e.agents([a])
    born = datetime.fromtimestamp(T0 - 3590, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sub_journal(tp, "g1", T0 - 3540, [{"type": "user", "timestamp": born, "message": {"role": "user", "content": "x"}}])
    sub_meta(tp, "g1", T0 - 3590)
    e.run("watch", t=T0)
    check(not respawned(e, "dcba0904") and "rg-dir (живые субагенты: dev-g1)" in e.alerts(),
          f"0904: запущенный в окне старта субагент не держит окно: {e.calls()} {e.alerts()[-400:]}")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
