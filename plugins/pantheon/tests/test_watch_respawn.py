#!/usr/bin/env python3
"""Дежурный, часть 8: перезапуск после плагинов, честные состояния, Гестия, передача заблокированных (общая часть — _watch_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403


def test_plugins_respawn_idle_free_0181():
    """metis-0181: idle, транскрипт и субагенты старше 15 мин, worktree нет — перезапуск. Свежая worktree лида в папке
    направления держит окно; поднятое после установки и Зевс — не кандидаты."""
    e, a, tp = respawn_env("rf-dir", "b6b6b6b6-1")
    subagent(tp, T0 - 1800)
    wt = worktree(e, "rf-dir", T0 - 300)
    e.run("watch", t=T0)
    check(not respawned(e, "b6b6b6b6"), f"0181: worktree лида менялась 5 мин назад — перезапущено: {e.calls()}")
    shutil.rmtree(wt)
    os.utime(os.path.dirname(wt), (T0 - 3600, T0 - 3600))
    e.run("watch", t=T0 + 60)
    check(respawned(e, "b6b6b6b6"), f"0181: idle 15+ мин без субагентов и worktree — не перезапущено: {e.calls()}")
    check(not os.path.exists(e.st("plugins", "respawn.json")), "0181: отметка не снята после перезапуска")
    # поднято после установки (startedAt > since) — не кандидат, отметка снимается: кандидатов нет
    e, a, tp = respawn_env("ra-dir", "c7c7c7c7-1", since=T0 - 200)
    e.run("watch", t=T0)
    check(not respawned(e, "c7c7c7c7") and not os.path.exists(e.st("plugins", "respawn.json")),
          f"0181: перезапущено окно, поднятое после установки: {e.calls()}")
    # Зевс поднят до установки, свободен и окно штаба есть — всё равно не трогаем (его перезапускаете вы)
    e, a, tp = respawn_env("rz-dir", "c8c8c8c8-1", since=T0 - 200)
    json.dump({"env": {}}, open(e.st("settings", "hq.json"), "w"))
    e.direction("zeus")  # окно есть: без исключения Зевса тик дошёл бы до respawn, а не споткнулся о «нет окна»
    z = bg("zeus", "done", "d8d8d8d8-1", pid=52, started=T0 - 1000)
    e.agents([a, z])
    transcript(e, z, 20_000, T0 - 3600)
    e.run("watch", t=T0)
    check(not respawned(e, "d8d8d8d8") and not [c for c in e.calls() if "--resume" in c or c[:1] == ["stop"]]
          and "\tzeus\td8d8d8d8\tplugins-respawn" not in _start_log(e),
          f"0181: Зевс перезапущен тиком: {e.calls()} {_start_log(e)!r}")


def test_plugins_respawn_empty_agents_0181():
    """metis-0181, ревью argus: пустой claude agents ([]) — не «все перезапущены»: отметка respawn.json остаётся."""
    e, a, tp = respawn_env("re-dir", "c9c9c9c9-1")
    e.agents([])
    e.run("watch", t=T0)
    check(os.path.exists(e.st("plugins", "respawn.json")), "0181: пустой claude agents снял отметку перезапуска")


def test_plugins_respawn_wait_alert_0181():
    """metis-0181, ревью argus: окна, которые ждут, видны строкой в тревогах и без перезапусков — одна строка на набор
    окон (не на каждом проходе); ожидание кончилось — следующий набор снова строкой."""
    e, a, tp = respawn_env("rw-dir", "cacacaca-1")
    subagent(tp, T0 - 300)
    e.run("watch", t=T0)
    e.run("watch", t=T0 + 60)
    line = "перезапуск после обновления плагинов (pantheon) ждёт: rw-dir (субагент писал меньше 15 мин назад)"
    check(e.alerts().count(line) == 1 and not respawned(e, "cacacaca"),
          f"0181: нет строки «ждёт» или она на каждом проходе: {e.alerts()}")


def test_plugins_respawn_ok_mark_0181():
    """metis-0181: метка «можно» (pantheon saved без техперезапуска) — перезапуск сразу, хоть транскрипт и свежий;
    busy — нет даже с меткой. Без отметки respawn.json pantheon saved отмечать нечего."""
    e, a, tp = respawn_env("rk-dir", "e9e9e9e9-1", state="working", status="busy")
    os.utime(tp, (T0 - 60, T0 - 60))
    r = e.run("saved", "--by", "rk-dir", "--state", "STATUS.md", t=T0)
    check(r.returncode == 0 and os.path.exists(e.st("plugins", "respawn-ok", "rk-dir.json")),
          f"0181: pantheon saved не поставил метку «можно»: {r.returncode} {r.stdout} {r.stderr}")
    check(not os.path.exists(e.st("maintenance", "rk-dir.json")), "0181: метка «можно» легла в maintenance/")
    e.run("watch", t=T0 + 10)
    check(not respawned(e, "e9e9e9e9") and os.path.exists(e.st("plugins", "respawn.json")),
          f"0181: busy с меткой «можно» перезапущено: {e.calls()}")
    a["status"] = "idle"
    e.agents([a])
    e.run("watch", t=T0 + 20)
    check(respawned(e, "e9e9e9e9"), f"0181: idle с меткой «можно» не перезапущено: {e.calls()}")
    check(not os.path.exists(e.st("plugins", "respawn.json"))
          and not os.path.exists(e.st("plugins", "respawn-ok", "rk-dir.json")), "0181: отметка и метка не сняты")
    # без метки тот же свежий транскрипт держит окно
    e, a, tp = respawn_env("rn-dir", "f0f0f0f0-1")
    os.utime(tp, (T0 - 60, T0 - 60))
    e.run("watch", t=T0)
    check(not respawned(e, "f0f0f0f0"), f"0181: транскрипт менялся минуту назад, метки нет — перезапущено: {e.calls()}")
    # метка старше since (прошлого обновления) не считается
    os.makedirs(e.st("plugins", "respawn-ok"), exist_ok=True)
    json.dump({"t": T0 - 100}, open(e.st("plugins", "respawn-ok", "rn-dir.json"), "w"))
    e.run("watch", t=T0 + 10)
    check(not respawned(e, "f0f0f0f0"), f"0181: метка старше since сочтена «можно»: {e.calls()}")
    e2 = Env()
    r = e2.run("saved", "--by", "rk-dir", "--state", "STATUS.md", t=T0)
    check(r.returncode == 1 and "отмечать нечего" in r.stdout, f"0181: saved без отметки: {r.returncode} {r.stdout}")



def test_plugins_respawn_recheck_0181():
    """metis-0181: под блокировкой имени перед перезапуском — свежий claude agents: окно, получившее ввод между проходом
    и перезапуском (status busy), не перезапускается, строка resume-skip в start.log, отметка стоит."""
    e, a, tp = respawn_env("rr-dir", "a1b2c3d4-1")
    b = dict(a, state="working", status="busy")
    nxt = os.path.join(e.tmp, "agents-next.json")
    json.dump([b], open(nxt, "w"))
    e.run("watch", t=T0, extra={"FAKE_AGENTS_NEXT": nxt})
    check(not respawned(e, "a1b2c3d4") and "\tresume-skip\trr-dir\ta1b2c3d4\tplugins-respawn\tзанято" in _start_log(e)
          and os.path.exists(e.st("plugins", "respawn.json")),
          f"0181: окно, занятое к моменту перезапуска, перезапущено: {e.calls()} {_start_log(e)!r}")


def test_status_live_not_failed_0250():
    """п. 1: из окна с песочницей claude agents пишет живую сессию failed без pid (19.10 zeus, metis-pantheon), а
    задание working и процесс в реестре демона жив — сводка и дежурный не зовут её «упала»; настоящая упавшая
    (процесса нет) — «упали» с причиной из state.json."""
    e = Env()
    e.direction("lv-dir")
    alive = os.getpid()
    e.agents([bg("zeus", "failed", "zzzzzzzz-1"), bg("lv-dir", "failed", "lvlvlvlv-1"),
              bg("lv-dir", "failed", "dddddddd-1")])
    _job(e, "zzzzzzzz", state="working", detail="пишет итог")
    _job(e, "lvlvlvlv", state="blocked", needs="выбрать: А или Б")
    _job(e, "dddddddd", state="working", detail="API Error: overloaded")    # процесса нет — правда упала
    _roster(e, {"zzzzzzzz": alive, "lvlvlvlv": alive, "dddddddd": _dead_pid()})
    out = e.run("status", t=T0).stdout
    check("упали: zeus" not in out and "фоновые работают: 1" in out, f"живой zeus «упал»: {out}")
    check("ждут вас: lv-dir — выбрать: А или Б" in out, f"живая ждущая — не «ждут вас» с вопросом: {out}")
    check("упали: lv-dir — API Error: overloaded" in out and "упали: 1" in out, f"настоящая упавшая не видна: {out}")
    e.run("watch", t=T0)
    al = e.alerts()
    check("zeus (zzzzzzzz) упала" not in al and "lv-dir (dddddddd) упала: API Error" in al,
          f"дежурный: живая «упала» или упавшая без тревоги: {al}")
    snap = json.load(open(e.st("agents.json")))["agents"]
    check({a["id"]: a.get("pid") for a in snap}.get("zzzzzzzz") == alive, f"pid из реестра демона не в снимке: {snap}")
    check("секрет" not in json.dumps(snap), "жетон реестра демона попал в снимок")


def test_status_blocked_without_process_0250():
    """п. 2: «ждёт вас» без процесса и без вопроса (18.10, координатор без процесса) — не «ждут вас» и без тревоги
    дежурного; с вопросом владельцу — ждёт вас; реестра демона нет — ничего не утверждаем, как раньше."""
    e = Env()
    e.direction("th-dir")
    e.direction("hm-dir")
    e.agents([bg("th-dir", "blocked", "thththth-1"), bg("hm-dir", "blocked", "hmhmhmhm-1"),
              bg("zeus", "done", "2e057e05-1", pid=32)])    # живой Зевс закончил ход: ему уходит «ждёт вас»
    e.notify_mode(1200)
    _job(e, "thththth", state="blocked", detail="ждёт разрешения")
    _job(e, "hmhmhmhm", state="blocked", needs="выбрать: А — разрешить")
    _roster(e, {})
    out = e.run("status", t=T0).stdout
    check("ждут вас: th-dir" not in out and "без процесса: th-dir — ждать нечего" in out and "claude rm thththth" in out,
          f"снятая сессия висит «ждёт вас»: {out}")
    # metis-0651: без процесса вообще (ни pid, ни реестра) сессия с вопросом — тоже призрак: имя не держит, вопрос виден
    check("упали: hm-dir — выбрать: А — разрешить" in out, f"призрак с вопросом: вопрос не виден в «упали»: {out}")
    e.run("watch", t=T0)
    check("th-dir (thththth) ждёт вас" not in e.alerts() and "hm-dir (hmhmhmhm): процесс умер" in e.alerts()
          and "ждала: выбрать: А — разрешить" in e.alerts(), f"дежурный: тревога по призраку с вопросом: {e.alerts()}")
    # metis-0651 (ревью argus Б1): призрак с вопросом по-прежнему «ждёт вас» — уведомление и передача Зевсу (metis-0250)
    check("hm-dir ждёт вас: выбрать: А — разрешить" in e.sent(), f"призрак с вопросом: нет уведомления: {e.sent()!r}")
    check("th-dir" not in e.sent(), f"снятая без вопроса сессия уведомила: {e.sent()!r}")
    check([c for c in e.calls() if c[:1] == ["respawn"] and c[1] == "2e057e05"]
          and "hmhmhmhm" in open(e.st("push", "2e057e05-1.txt"), encoding="utf-8").read(),
          f"призрак с вопросом: Зевсу не передано: {e.calls()}")
    # ревью argus Б2: следующие проходы (и через 20 мин) не повторяют ни уведомление, ни передачу Зевсу
    for dt in (60, 120, 180, 1200):
        e.run("watch", t=T0 + dt)
    check(e.sent().count("hm-dir ждёт вас") == 1, f"призрак с вопросом: уведомление повторяется: {e.sent()!r}")
    check(len([c for c in e.calls() if c[:1] == ["respawn"] and c[1] == "2e057e05"]) == 1,
          f"призрак с вопросом: повторная передача Зевсу: {e.calls()}")
    os.remove(os.path.join(e.home, ".claude", "daemon", "roster.json"))
    out = e.run("status", t=T0 + 60).stdout
    check("ждут вас: th-dir" in out, f"без реестра демона сессия объявлена снятой: {out}")


def test_status_no_dash_without_reason_0250():
    """п. 4: причины нет ни в claude agents, ни в state.json — строка без висячего тире."""
    e = Env()
    e.direction("nd-dir")
    e.agents([bg("nd-dir", "failed", "ndndndnd-1"), bg("zeus", "blocked", "nznznznz-1")])
    out = e.run("status", t=T0).stdout
    lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith(("упали:", "ждут вас:"))]
    check("упали: nd-dir" in lines and "ждут вас: zeus" in lines and not [ln for ln in lines if ln.endswith("—")],
          f"висячее тире: {lines}")


def test_auto_rm_done_stopped_0250():
    """п. 3: дежурный убирает (claude rm) сессии Пантеона в done/stopped без процесса дольше 2 ч; не трогает: свежие,
    с процессом, чужие, на паузе по нагрузке, при паузе планировщика; отказ rm (неотправленное в worktree) — тревога
    один раз и повтор через сутки, без --discard-unpushed. Есть живая сессия того же имени — прежние (done/stopped без
    процесса) убираются сразу, без 2 ч и без state.json: в claude agents у имени одна строка."""
    e = Env()
    for d in ("ar-dir", "ap-dir", "aq-dir", "ad-dir"):
        e.direction(d)
    old, fresh = T0 - 3 * 3600, T0 - 600
    e.agents([bg("ar-dir", "done", "a1a1a1a1-1"), bg("ar-dir", "stopped", "a2a2a2a2-1"),
              bg("aq-dir", "done", "a3a3a3a3-1"),                     # свежая — 10 мин
              bg("ar-dir", "done", "a4a4a4a4-1", pid=os.getpid()),    # процесс жив — держит имя (CTX-10)
              bg("чужая", "done", "a5a5a5a5-1"),                     # не Пантеон
              bg("ap-dir", "stopped", "a6a6a6a6-1"),                 # пауза по нагрузке — её снятие продолжит
              bg("ad-dir", "working", "a7a7a7a7-1", pid=os.getpid()),  # живая новая того же имени —
              bg("ar-dir", "done", "a8a8a8a8-1"),                     # worktree с неотправленным — rm откажет
              bg("ad-dir", "done", "b1b1b1b1-1"), bg("ad-dir", "stopped", "b2b2b2b2-1")])  # прежние убрать сразу
    for sid in ("a1a1a1a1", "a2a2a2a2", "a4a4a4a4", "a5a5a5a5", "a6a6a6a6", "a7a7a7a7", "a8a8a8a8"):
        _job(e, sid, state="done", updatedAt=_iso(old), lastTerminalAt=_iso(old))
    for sid in ("a3a3a3a3", "b1b1b1b1"):
        _job(e, sid, state="done", updatedAt=_iso(fresh), lastTerminalAt=_iso(fresh))
    e.extra["PANTHEON_FAKE_SWAP"] = "50"    # swap высокий — пауза по нагрузке держится весь тест
    e.run("pause", "ap-dir", "--reason", "swap", "проба", t=T0 - 100)
    # пауза планировщика — уборки нет совсем
    open(e.st("paused"), "w").write("x")
    e.run("watch", t=T0)
    check(not [c for c in e.calls() if c[:1] == ["rm"]], f"уборка при паузе планировщика: {e.calls()}")
    os.remove(e.st("paused"))
    e.run("watch", t=T0 + 10, extra={"FAKE_RM_REFUSE": "a8a8a8a8"})
    rms = [c[1] for c in e.calls() if c[:1] == ["rm"]]
    check(sorted(rms) == ["a1a1a1a1", "a2a2a2a2", "a8a8a8a8", "b1b1b1b1", "b2b2b2b2"], f"уборка не те сессии: {rms}")
    check(not [c for c in e.calls() if c[1:2] == ["a7a7a7a7"]], "уборка тронула живую новую сессию имени")
    check(not [c for c in e.calls() if "--discard-unpushed" in c or "--force-remove-worktree" in c], "rm насильно")
    check(not [c for c in e.calls() if c[:1] == ["stop"] and c[1] in ("a1a1a1a1", "a2a2a2a2")], "уборка зовёт stop")
    log = open(e.st("logs", "start.log")).read()
    check("auto-rm\tar-dir\ta1a1a1a1\tdone" in log and "rm-refused\tar-dir\ta8a8a8a8" in log, f"start.log: {log}")
    al = e.alerts()
    check("уборка: убраны из фоновых сессий Claude Code" in al and "ar-dir a1a1a1a1" in al and "ar-dir a2a2a2a2" in al,
          f"нет строки уборки: {al}")
    check("ar-dir: прежняя сессия a8a8a8a8 осталась среди фоновых сессий Claude Code (уборка, rm отказал): " in al
          and "unpushed" in al, f"отказ rm без тревоги: {al}")
    # следующий проход: отказавшую не дёргаем до суток, тревога не повторяется
    n = len(rms)
    e.run("watch", t=T0 + 400, extra={"FAKE_RM_REFUSE": "a8a8a8a8"})
    again = [c[1] for c in e.calls() if c[:1] == ["rm"]][n:]
    check("a8a8a8a8" not in again, f"отказавшую дёрнули снова через 5 мин: {again}")
    check(e.alerts().count("a8a8a8a8 осталась") == 1, "тревога об отказе повторилась")
    e.run("watch", t=T0 + 10 + 86400 + 60, extra={"FAKE_RM_REFUSE": "a8a8a8a8"})
    check("a8a8a8a8" in [c[1] for c in e.calls() if c[:1] == ["rm"]][n + len(again):], "через сутки повтора нет")
    check(e.alerts().count("a8a8a8a8 осталась") == 1, "тот же отказ — вторая тревога")


def test_auto_rm_suffixed_live_name_0885():
    """metis-0885: перезапуск окна (plugins-update: старая stopped; start --restart: старая done) при живой старой
    сессии даёт новой имя «zeus (2)» — прежнюю «zeus» убираем в том же проходе, без 2 ч (свежая отметка state.json)."""
    for old_name, state, sid in (("zeus", "stopped", "c1c1c1c1"), ("zeus", "done", "c2c2c2c2"),
                                 ("ar-dir", "stopped", "c3c3c3c3")):
        e = Env()
        e.direction("ar-dir")
        live = old_name + " (2)"
        e.agents([bg(old_name, state, sid + "-1"), bg(live, "working", "d9d9d9d9-1", pid=os.getpid())])
        _job(e, sid, state="done", updatedAt=_iso(T0 - 60), lastTerminalAt=_iso(T0 - 60))
        e.run("watch", t=T0)
        rms = [c[1] for c in e.calls() if c[:1] == ["rm"]]
        check(rms == [sid], f"0885: {old_name}/{state} при живой «{live}»: rm {rms}")
    # мёртвая «zeus (2)» при живой «zeus» — убирается; живая «zeus (2)» без живой «zeus» — не трогается
    e = Env()
    e.agents([bg("zeus (2)", "stopped", "f1f1f1f1-1"), bg("zeus", "working", "f2f2f2f2-1", pid=os.getpid())])
    _job(e, "f1f1f1f1", state="done", updatedAt=_iso(T0 - 60), lastTerminalAt=_iso(T0 - 60))
    e.run("watch", t=T0)
    rms = [c[1] for c in e.calls() if c[:1] == ["rm"]]
    check(rms == ["f1f1f1f1"], f"0885: мёртвая «zeus (2)» при живой «zeus»: rm {rms}")
    e = Env()
    e.agents([bg("zeus (2)", "working", "g1g1g1g1-1", pid=os.getpid())])
    e.run("watch", t=T0)
    check(not [c for c in e.calls() if c[:1] == ["rm"]], f"0885: живую «zeus (2)» тронули: {e.calls()}")
    e = Env()
    e.agents([bg("zeus", "stopped", "e1e1e1e1-1"), bg("zeus (2)", "stopped", "e2e2e2e2-1")])
    _job(e, "e1e1e1e1", state="done", updatedAt=_iso(T0 - 60), lastTerminalAt=_iso(T0 - 60))
    e.run("watch", t=T0)
    check(not [c for c in e.calls() if c[:1] == ["rm"]], f"0885: нет живой — свежая убрана: {e.calls()}")


def test_hestia_reap_waiting_open_0677():
    """metis-0677: задача окна Гестии waiting/inbox — открыта (ждёт consent владельца): живую сессию не гасим; done|dropped
    — гасим. Неизвестная задача — по-прежнему гасим."""
    for status in ("waiting", "inbox"):
        e = _hestia_env(status, extra="next: ждём consent\nwaiting_on: human\n" if status == "waiting" else "")
        e.agents([bg("hestia", "done", "h8h8h8h8-1", pid=os.getpid())])
        check(P_task_valid(e, status), f"0677: тестовая задача {status} не загружается")
        e.run("watch", t=T0)
        check(not _hestia_calls(e), f"0677: {status} — Гестия убрана: {e.calls()}")
    for status in ("done", "dropped"):
        e = _hestia_env(status)
        e.agents([bg("hestia", "done", "h9h9h9h9-1", pid=os.getpid())])
        e.run("watch", t=T0)
        check(_hestia_calls(e) == [["stop", "h9h9h9h9"], ["rm", "h9h9h9h9"]], f"0677: {status} не убрана: {e.calls()}")


def test_stop_removes_ghost_0685():
    """metis-0685: pantheon stop убирает и призрака (запись без процесса, reconcile_agents ставит ghost) — stop+rm, и число
    остановленных его считает; живая копия и призрак одного имени — каждая по разу."""
    e = Env()
    e.direction("gh-dir")
    _roster(e, {"other": 999999})
    e.agents([bg("gh-dir", "blocked", "g1g1g1g1-1")])
    r = e.run("stop", "gh-dir", t=T0)
    c = e.calls()
    check(["stop", "g1g1g1g1"] in c and ["rm", "g1g1g1g1"] in c, f"0685: призрак не убран: {c}")
    check("остановлено сессий 1" in r.stdout, f"0685: призрак не посчитан: {r.stdout!r}")
    e = Env()
    e.direction("gh-dir")
    _roster(e, {"other": 999999})
    e.agents([bg("gh-dir", "blocked", "g2g2g2g2-1"), bg("gh-dir", "working", "g3g3g3g3-1", pid=os.getpid())])
    r = e.run("stop", "gh-dir", t=T0)
    c = e.calls()
    check(c.count(["stop", "g2g2g2g2"]) == 1 and c.count(["stop", "g3g3g3g3"]) == 1 and "остановлено сессий 2" in r.stdout,
          f"0685: призрак с живой копией: {c} {r.stdout!r}")


def test_hestia_reap_0671():
    """metis-0671: плановый проход убирает Гестию (claude stop, затем rm) без метки stopped/hestia: (а) призрак без
    процесса; (б) закончила ход (не working), а её задача закрыта. Не трогает: working, живую с открытой задачей,
    запись моложе минуты, паузу планировщика."""
    # (а) призрак: blocked без pid, процесса нет ни у записи, ни в реестре — при открытой задаче
    e = _hestia_env("doing")
    e.agents([bg("hestia", "blocked", "h1h1h1h1-1")])
    e.run("watch", t=T0)
    check(_hestia_calls(e) == [["stop", "h1h1h1h1"], ["rm", "h1h1h1h1"]], f"0671 а: призрак не убран: {e.calls()}")
    check(not os.path.exists(e.st("stopped", "hestia")), "0671 а: поставлена метка stopped/hestia")
    check("Гестия h1h1h1h1 убрана" in e.alerts(), f"0671 а: нет тревоги уборки: {e.alerts()}")
    # (а1) призрак с мёртвым pid в записи: тот же результат
    e = _hestia_env("doing")
    e.agents([bg("hestia", "working", "h7h7h7h7-1", pid=999999)])
    e.run("watch", t=T0)
    check(_hestia_calls(e) == [["stop", "h7h7h7h7"], ["rm", "h7h7h7h7"]], f"0671 а1: призрак с pid не убран: {e.calls()}")
    # (а2) мёртвая запись done без pid при открытой задаче: rm без stop
    e = _hestia_env("doing")
    e.agents([bg("hestia", "done", "h2h2h2h2-1")])
    e.run("watch", t=T0)
    check(_hestia_calls(e) == [["rm", "h2h2h2h2"]], f"0671 а2: done без pid не убрана: {e.calls()}")
    # (б) процесс жив, ход закончен, задача закрыта — убрана; метки нет
    e = _hestia_env("done")
    e.agents([bg("hestia", "done", "h3h3h3h3-1", pid=os.getpid())])
    e.run("watch", t=T0)
    check(_hestia_calls(e) == [["stop", "h3h3h3h3"], ["rm", "h3h3h3h3"]], f"0671 б: закрытая задача: {e.calls()}")
    check(not os.path.exists(e.st("stopped", "hestia")), "0671 б: поставлена метка stopped/hestia")
    # задача неизвестна (run-файла нет), сессия не working — тоже убрана
    e = _hestia_env("doing")
    os.remove(e.st("settings", "run", "hestia.json"))
    e.agents([bg("hestia", "done", "h4h4h4h4-1", pid=os.getpid())])
    e.run("watch", t=T0)
    check(len(_hestia_calls(e)) == 2, f"0671 б2: без задачи не убрана: {e.calls()}")
    # не трогаем: working при любой задаче, done/blocked с процессом при открытой, свежая запись
    for status, st, pid, started in (("doing", "working", os.getpid(), T0 - 100), ("done", "working", os.getpid(), T0 - 100),
                                     ("review", "done", os.getpid(), T0 - 100), ("todo", "blocked", os.getpid(), T0 - 100),
                                     ("done", "done", None, T0 - 10)):
        e = _hestia_env(status)
        e.agents([bg("hestia", st, "h5h5h5h5-1", pid=pid, started=started)])
        e.run("watch", t=T0)
        check(not _hestia_calls(e), f"0671 нет: тронута {status}/{st}/{pid}/{started}: {e.calls()}")
        check(not os.path.exists(e.st("stopped", "hestia")), "0671: метка stopped/hestia")
    # пауза планировщика — уборки нет
    e = _hestia_env("doing")
    e.agents([bg("hestia", "blocked", "h6h6h6h6-1")])
    open(e.st("paused"), "w").write("x")
    e.run("watch", t=T0)
    check(not _hestia_calls(e), f"0671: уборка при паузе: {e.calls()}")


def test_blocked_relay_to_zeus_0277():
    """metis-0277: blocked уходит живому Зевсу (push + respawn) с инструментом и целью; повтор не чаще раза в 15 мин
    на сессию; текст сессии — данные: обрезан до 120 знаков, без переводов строк."""
    e = _blocked_env(("EnterWorktree", {"path": "/Users/x/tgdaemon/wt"}))
    e.run("watch", t=T0)
    text = _pushed(e)
    check(len(_relayed(e)) == 1, f"0277: Зевсу не передано: {e.calls()}")
    check("EnterWorktree → /Users/x/tgdaemon/wt" in text and "permission prompt" not in text
          and "b10c0001" in text and text.startswith("[Пантеон:"), f"0277: нет инструмента и цели: {text!r}")
    check("EnterWorktree → /Users/x/tgdaemon/wt" in e.alerts(), f"0277: в тревоге нет цели: {e.alerts()}")
    os.remove(e.st("push", "2e057e05-1.txt"))                     # хук push забрал текст
    e.run("watch", t=T0 + 300)
    check(len(_relayed(e)) == 1, f"0277: через 5 мин второе сообщение: {e.calls()}")
    e.run("watch", t=T0 + 960)
    check(len(_relayed(e)) == 1, f"0277: тот же пункт через 16 мин разбудил Зевса снова: {e.calls()}")
    # текст сессии — данные: длинная цель с переводами строк
    e = _blocked_env(("Bash", {"command": "echo a\n" + "x" * 300}))
    e.run("watch", t=T0)
    text = _pushed(e)
    check("\n" not in text and "x" * 121 not in text and "echo a x" in text, f"0277: текст не обрезан: {text!r}")


def test_blocked_no_zeus_only_alert_0277():
    """metis-0277: Зевса нет, остановлен или он занят ходом — сообщения нет, остаются тревога и уведомление."""
    e = _blocked_env(("EnterWorktree", {"path": "/w/wt"}))
    e.agents([bg("coord-x", "blocked", BLK_SID, pid=31)])
    e.run("watch", t=T0)
    check(not _relayed(e) and not [c for c in e.calls() if c[:1] == ["respawn"]], f"0277: без Зевса — передача: {e.calls()}")
    check("coord-x (b10c0001) ждёт вас" in e.alerts(), f"0277: без Зевса нет тревоги: {e.alerts()}")
    e = _blocked_env(("EnterWorktree", {"path": "/w/wt"}))
    os.makedirs(e.st("stopped"), exist_ok=True)
    open(e.st("stopped", "zeus"), "w").write("x")
    e.run("watch", t=T0)
    check(not _relayed(e) and "ждёт вас" in e.alerts(), f"0277: остановленному Зевсу передано: {e.calls()}")
    e = _blocked_env(("EnterWorktree", {"path": "/w/wt"}))
    busy = bg("zeus", "working", "2e057e05-1", pid=32)
    busy["status"] = "busy"
    e.agents([bg("coord-x", "blocked", BLK_SID, pid=31), busy])
    e.run("watch", t=T0)
    check(not _relayed(e), f"0277: занятому ходом Зевсу передано (respawn оборвал бы ход): {e.calls()}")


def test_blocked_reason_fallbacks_0277():
    """metis-0277 п. 2: нет журнала — waitingFor, если он не общий «permission prompt»; нет и его — «причина
    неизвестна — claude attach <id>» без пустого места после тире."""
    e = _blocked_env(None, waiting="Bash: rm -rf build")
    e.run("watch", t=T0)
    check("Bash: rm -rf build" in _pushed(e), f"0277: waitingFor не взят: {_pushed(e)!r}")
    e = _blocked_env(None, waiting="permission prompt")
    e.run("watch", t=T0)
    text = _pushed(e)
    check("ждёт вас: причина неизвестна — claude attach b10c0001" in text and "permission prompt" not in text,
          f"0277: нет «причина неизвестна»: {text!r}")


def test_relay_one_per_pass_0277():
    """metis-0277 (ревью argus 1): две blocked за проход — один respawn Зевса, в тексте обе, в relay.json обе."""
    e = _two_blocked_env()
    e.run("watch", t=T0)
    text = _pushed(e)
    check(len(_relayed(e)) == 1, f"0277: две передачи за проход: {e.calls()}")
    check("b10c0001" in text and "b10c0002" in text and "Bash: one" in text and "Bash: two" in text,
          f"0277: в тексте не обе сессии: {text!r}")
    st = json.load(open(e.st("relay.json")))
    check(set(st) == {"b10c0001", "b10c0002"}, f"0277: в relay.json не обе: {st}")


def test_relay_zeus_busy_on_fresh_agents_0277():
    """metis-0277 (ревью argus 1): снимок прохода говорит «Зевс простаивает», а свежий claude agents под блокировкой
    start-zeus — он взял ход: передачи нет."""
    e = _two_blocked_env()
    lst = json.load(open(e.agents_file))
    for x in lst:
        if x["name"] == "zeus":
            x.update(state="working", status="busy")
    nxt = os.path.join(e.home, "agents-next.json")
    json.dump(lst, open(nxt, "w"))
    e.run("watch", t=T0, extra={"FAKE_AGENTS_NEXT": nxt})
    check(not _relayed(e) and not os.path.exists(e.st("push", "2e057e05-1.txt")),
          f"0277: Зевс занят по свежему списку, а передача была: {e.calls()}")
    check("ждёт вас" in e.alerts(), f"0277: пропала тревога: {e.alerts()}")


def test_relay_maintenance_paused_0277():
    """metis-0277 (ревью argus 2): метка техперезапуска и пауза планировщика — передачи нет, тревога остаётся."""
    def maint(e):
        os.makedirs(e.st(), exist_ok=True)
        json.dump({"reason": "probe", "expires": T0 + 3600, "started": T0 - 60}, open(e.st("maintenance.json"), "w"))

    def paused(e):
        os.makedirs(e.st(), exist_ok=True)
        open(e.st("paused"), "w").write("x")
    _relay_stops(maint, "метка техперезапуска")
    _relay_stops(paused, "пауза планировщика")


def test_relay_limits_0277():
    """metis-0277: пятичасовой, недельный лимит и потолок владельца — передачи нет; потолок выше расхода пускает."""
    _relay_stops(lambda e: None, "пятичасовой лимит", extra={"PANTHEON_FAKE_LIMIT": "90"})

    def week(e):
        e.week_pct = 90.0
    _relay_stops(week, "недельный лимит (красная зона)")

    day = time.strftime("%Y-%m-%d", time.localtime(T0))

    def cap(pct):
        def f(e):
            with open(os.path.join(e.pantheon, "schedule.toml"), "a") as fh:
                fh.write(f'\n[limits.owner_cap]\ndate = "{day}"\npct = {pct}\ndecision = "t"\n')
        return f
    _relay_stops(cap(5), "потолок владельца")
    e = _two_blocked_env()
    cap(50)(e)
    e.run("watch", t=T0)
    check(len(_relayed(e)) == 1, f"0277: потолок выше расхода закрыл передачу: {e.calls()}")


def test_relay_once_per_item_0277():
    """metis-0277: один пункт — одна передача: тот же вопрос через 20 мин не будит; новый вопрос — будит; вышла из
    blocked и вернулась — будит."""
    e = _blocked_env(None, waiting="Bash: one")
    e.run("watch", t=T0)
    check(len(_relayed(e)) == 1, f"0277: нет первой передачи: {e.calls()}")
    os.remove(e.st("push", "2e057e05-1.txt"))
    e.run("watch", t=T0 + 1200)
    check(len(_relayed(e)) == 1, f"0277: тот же пункт через 20 мин разбудил снова: {e.calls()}")
    b = bg("coord-x", "blocked", BLK_SID, pid=31)
    b["waitingFor"] = "Bash: other"
    e.agents([b, bg("zeus", "done", "2e057e05-1", pid=32)])
    e.run("watch", t=T0 + 1300)
    check(len(_relayed(e)) == 2 and "Bash: other" in _pushed(e), f"0277: новый пункт не передан: {e.calls()}")
    os.remove(e.st("push", "2e057e05-1.txt"))
    e.agents([bg("coord-x", "working", BLK_SID, pid=31), bg("zeus", "done", "2e057e05-1", pid=32)])
    e.run("watch", t=T0 + 1400)  # вышла из blocked
    b["waitingFor"] = "Bash: other"
    e.agents([b, bg("zeus", "done", "2e057e05-1", pid=32)])
    e.run("watch", t=T0 + 1400 + 1000)
    check(len(_relayed(e)) == 3, f"0277: вернулась в blocked — передачи нет: {e.calls()}")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
