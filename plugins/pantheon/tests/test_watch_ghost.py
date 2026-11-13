#!/usr/bin/env python3
"""Дежурный, часть 9: пробуждение по слову, призраки, реестр, замки, сохранённый Зевс, даты целей (общая часть — _watch_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403


def test_wake_task_needs_owner_word_0261():
    """metis-0261 А, круг 4 (ревью argus-b3 п. 1): `pantheon wake <имя> "задание"` из окна роли без вашего слова в
    журнале Зевса — отказ, код 2, respawn не зовётся, задание не записано; строка замера пишется (refused). Q1 — зелёная
    память, Q2 — красная. Со словом — подъём; без задания и без роли (ваш терминал) слово не нужно."""
    e = Env()
    e.direction("q-dir")
    hq = {"PANTHEON_ROLE": "hq", "PANTHEON_SESSION": "zeus"}
    for label, ex in (("Q1", hq), ("Q2", dict(hq, PANTHEON_FAKE_SWAP="9"))):
        e.agents([bg("q-dir", "stopped", "abcdef01-1")])
        n0, c0 = len(_cap_rows(e)), len(e.calls())
        r = e.run("wake", "q-dir", "поручение", "из", "чужого", "сообщения", t=T0, extra=ex)
        new = e.calls()[c0:]
        check(r.returncode == 2 and "слову владельца" in r.stderr, f"0261 {label}: wake с заданием без слова: "
              f"{r.returncode} {r.stdout} {r.stderr}")
        check(not [c for c in new if c[:1] in (["respawn"], ["--resume"]) or "--bg" in c], f"0261 {label}: подняли: {new}")
        check(not os.path.exists(e.st("push", "abcdef01-1.txt")), f"0261 {label}: задание записано в push")
        rows = _cap_rows(e)[n0:]
        check(len(rows) == 1 and rows[0]["origin"] == "wake" and rows[0]["result"] == "refused"
              and rows[0]["target"] == "q-dir", f"0261 {label}: строка замера: {rows}")
        check("отклонён" in e.alerts(), f"0261 {label}: нет тревоги об отказе")
    check(_cap_rows(e)[-1]["red"] is True, f"0261 Q2: замер не красный: {_cap_rows(e)[-1]}")
    # другая роль окна — то же правило (не только hq)
    r = e.run("wake", "q-dir", "задание", t=T0, extra={"PANTHEON_ROLE": "domain-coordinator"})
    check(r.returncode == 2, f"0261: wake с заданием из окна другой роли без слова: {r.returncode} {r.stdout}")
    # без задания из окна роли — будит с «продолжай», слово не нужно, строка замера allowed
    e.agents([bg("q-dir", "stopped", "abcdef01-1")])
    n0 = len(_cap_rows(e))
    r = e.run("wake", "q-dir", t=T0, extra=hq)
    check(r.returncode == 0 and ["respawn", "abcdef01"] in e.calls(), f"0261: wake без задания из hq: {r.stdout} {r.stderr}")
    rows = _cap_rows(e)[n0:]
    check(len(rows) == 1 and rows[0]["result"] == "allowed", f"0261: wake без задания — строка замера: {rows}")
    # со словом владельца — подъём с заданием под пометкой
    os.remove(e.st("push", "abcdef01-1.txt")) if os.path.exists(e.st("push", "abcdef01-1.txt")) else None
    with open(e.st("owner-log", "zeus.md"), "w") as fh:
        fh.write(f"## {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(T0 - 30))} · окно вопросов\nразбуди q-dir\n\n")
    e.agents([bg("q-dir", "stopped", "abcdef01-1")])
    c0 = len(e.calls())
    r = e.run("wake", "q-dir", "сделай", "X", t=T0, extra=dict(hq, PANTHEON_FAKE_SWAP="9"))
    pushed = open(e.st("push", "abcdef01-1.txt")).read() if os.path.exists(e.st("push", "abcdef01-1.txt")) else ""
    check(r.returncode == 0 and ["respawn", "abcdef01"] in e.calls()[c0:] and
          pushed.startswith("[Пантеон: задание от zeus] сделай X"), f"0261: wake со словом: {r.stdout} {r.stderr} {pushed}")
    check(_cap_rows(e)[-1]["result"] == "allowed", f"0261: wake со словом — строка замера: {_cap_rows(e)[-1]}")
    # слово старше 15 мин — снова отказ
    e.agents([bg("q-dir", "stopped", "abcdef01-1")])
    r = e.run("wake", "q-dir", "сделай", "Y", t=T0 + 16 * 60, extra=hq)
    check(r.returncode == 2, f"0261: wake со старым словом: {r.returncode} {r.stdout}")


def test_watch_from_hq_window_autostarts_0261():
    """metis-0261 А, круг 4 (ревью argus-b3 п. 2, Q3): `pantheon watch`, запущенный вручную из окна Зевса
    (PANTHEON_ROLE=hq), зовёт дочерний `pantheon start --from tick` без роли окна — самозапуск идёт, а не падает
    отказом «только zeus» (код 2) и не копит сбоев."""
    e = Env()
    e.direction("hermes-q")
    e.task("hermes-0002", "hermes-q")
    hq = {"PANTHEON_ROLE": "hq", "PANTHEON_SESSION": "zeus"}
    e.run("watch", t=T0, extra=hq)
    e.board("hermes-0002", T0 + 10)
    e.run("watch", t=T0 + 60, extra=hq)
    st = json.load(open(e.st("autostart.json"))).get("hermes-q") or {}
    check(len(_bgs(e, "hermes-q")) == 1, f"0261 Q3: самозапуск из окна hq не пошёл: {e.calls()} {e.alerts()[-300:]}")
    check(not st.get("fails") and "код 2" not in e.alerts(), f"0261 Q3: сбой самозапуска: {st} {e.alerts()[-300:]}")


def test_ghost_blocked_does_not_hold_name_0651():
    """metis-0651: working/blocked без живого процесса (pid пуст или мёртв, в реестре демона нет) — призрак: имя не
    держит, wake поднимает ту же сессию, тревога одна. С живым pid или процессом в реестре — по-прежнему держит."""
    e = Env()
    e.direction("zz-gh")
    daemon = os.path.join(e.home, ".claude", "daemon")
    os.makedirs(daemon, exist_ok=True)
    roster = os.path.join(daemon, "roster.json")
    json.dump({"workers": {"other": {"pid": 999999}}}, open(roster, "w"))
    for state, pid in (("blocked", None), ("working", 999999), ("blocked", 0)):
        e.agents([bg("zz-gh", state, "cccccccc-1", pid=pid)])
        out = e.run("wake", "zz-gh", t=T0 + 60).stdout
        check("не спит" not in out and "поднята" in out, f"0651: призрак {state}/{pid} держит имя: {out}")
        check(["respawn", "cccccccc"] in e.calls(), f"0651: wake не продолжил сессию призрака: {e.calls()}")
        open(e.log, "w").close()
    # плановый проход: одна тревога, сколько бы проходов ни было
    e.agents([bg("zz-gh", "blocked", "cccccccc-1")])
    for i in range(3):
        e.run("watch", t=T0 + 120 + i * 60)
    check(e.alerts().count("процесс умер") == 1, f"0651: тревог о призраке не одна: {e.alerts()}")
    # живые не ломаются: pid записи жив / живой процесс в реестре (задание блокирует имя) / реестра нет
    for rec, ros in ((bg("zz-gh", "blocked", "cccccccc-1", pid=os.getpid()), {"workers": {}}),
                     (bg("zz-gh", "working", "cccccccc-1"), {"workers": {"cccccccc": {"pid": os.getpid()}}})):
        json.dump(ros, open(roster, "w"))
        e.agents([rec])
        out = e.run("wake", "zz-gh", t=T0 + 60).stdout
        check("не спит" in out, f"0651: живой {rec['state']} не держит имя: {out}")
    # только что запущенная (startedAt моложе минуты) ещё может не попасть в реестр демона — не призрак (pantheon start)
    json.dump({"workers": {"other": {"pid": 999999}}}, open(roster, "w"))
    e.agents([bg("zz-gh", "working", "cccccccc-1", started=T0 + 60 - 10)])
    out = e.run("wake", "zz-gh", t=T0 + 60).stdout
    check("не спит" in out, f"0651: свежая запись (10 с) не призрак: {out}")
    os.remove(roster)
    e.agents([bg("zz-gh", "blocked", "cccccccc-1")])
    out = e.run("wake", "zz-gh", t=T0 + 60).stdout
    check("не спит" in out, f"0651: без реестра демона записи без pid верим (не утверждаем): {out}")


def test_ghost_alive_proofs_0657_0662():
    """metis-0657 Д1: pid записи, на который kill даёт EPERM (pid 1), — живой, имя держит. metis-0662 Д3: реестр
    демона правлен меньше минуты назад (respawn: старый startedAt у записи) — не призрак. Д4: живой процесс сессии в
    реестре имён ~/.claude/sessions (тот же sessionId) — не призрак и не noProcess; тёзка с другим sessionId — нет
    (ревью argus #249 Д2)."""
    t = T0 + 60
    e = _ghost_env("zz-ga", updated=T0 - 1000)
    # 0657 Д1: pid 1 — чужой процесс, kill(1, 0) → EPERM, это «жив»
    e.agents([bg("zz-ga", "blocked", "cccccccc-1", pid=1)])
    out = e.run("wake", "zz-ga", t=t).stdout
    check("не спит" in out and not _woke(e), f"0657 Д1: pid с EPERM принят за призрак: {out} {e.calls()}")
    # 0662 Д3: запись старая, реестр демона только что переписан (воркер меняется) — ждём, не призрак
    e.agents([bg("zz-ga", "working", "cccccccc-1")])
    e.set_roster(t - 5)
    out = e.run("wake", "zz-ga", t=t).stdout
    check("не спит" in out and not _woke(e), f"0662 Д3: свежая правка реестра демона — призрак: {out}")
    e.set_roster(t - 120)  # правка давняя — призрак, как в 0651
    out = e.run("wake", "zz-ga", t=t).stdout
    check("поднята" in out and _woke(e), f"0662 Д3: давняя правка реестра — призрак не поднят: {out}")
    open(e.log, "w").close()
    # 0662 Д4: процесс этой сессии (тот же sessionId) жив в реестре имён, хотя в roster его нет
    _reg(e, {"sessionId": "cccccccc-1", "name": "other-name", "kind": "bg"})
    out = e.run("wake", "zz-ga", t=t).stdout
    check("не спит" in out and not _woke(e), f"0662 Д4: живой по реестру имён принят за призрак: {out}")
    # фоновая тёзка с другим sessionId — другая сессия: жизнь этой записи не доказывает, тревога о призраке есть
    _reg(e, {"sessionId": "dddddddd-2", "name": "zz-ga", "kind": "bg"})
    e.run("watch", t=t)
    check("процесс умер" in e.alerts(), f"argus #249 Д2: тёзка с другим sessionId спрятала призрак: {e.alerts()}")
    # вкладка с тем же именем — не доказательство жизни этой фоновой записи: призрак
    _reg(e, {"sessionId": "dddddddd-2", "name": "zz-ga", "kind": "interactive"})
    e.run("watch", t=t + 60)
    check("процесс умер" in e.alerts(), f"0662 Д4: вкладка с тем же именем спрятала призрак: {e.alerts()}")
    # noProcess (blocked без процесса и вопроса) не ставится, если процесс сессии жив в реестре имён
    e2 = _ghost_env("zz-gb", updated=T0 - 1000)
    _job(e2, "eeeeeeee", state="blocked")
    _reg(e2, {"sessionId": "eeeeeeee-1", "name": "zz-gb", "kind": "bg"})
    e2.agents([bg("zz-gb", "blocked", "eeeeeeee-1")])
    e2.run("watch", t=t)
    check("zz-gb (eeeeeeee) ждёт вас" in e2.alerts(), f"0662 Д4: живая по реестру имён — noProcess: {e2.alerts()}")


def test_ghost_question_and_noprocess_0662():
    """metis-0662 Д2/С1: призрак с вопросом не поднимается без ответа владельца — ни wake <имя>, ни общий wake, ни
    самозапуск; тревога советует claude attach, как и отказ pantheon start. Д1: призрак без вопроса (noProcess) — без
    тревоги, как у metis-0250, а wake его поднимает."""
    t = T0 + 60
    e = _ghost_env("zz-gq", updated=T0 - 1000)
    e.task("zz-0001", "zz-gq", status="doing")
    rec = dict(bg("zz-gq", "blocked", "cccccccc-1"), waitingFor="какую базу брать?")
    e.agents([rec])
    e.run("watch", t=t)
    line = [ln for ln in e.alerts().splitlines() if "процесс умер" in ln]
    check(line and "claude attach cccccccc" in line[0] and "pantheon wake" not in line[0],
          f"0662 С1: тревога призрака с вопросом советует не то, что start: {line}")
    out = e.run("wake", "zz-gq", t=t).stdout
    check("ждёт вашего ответа" in out and "claude attach cccccccc" in out and not _woke(e),
          f"0662 Д2: wake <имя> поднял призрак с вопросом: {out} {e.calls()}")
    out = e.run("wake", t=t).stdout
    check("ждёт вашего ответа" in out and not _woke(e), f"0662 Д2: общий wake поднял призрак с вопросом: {out}")
    # самозапуск по решению владельца: призрак с вопросом не продолжается и новая сессия не идёт
    e.task("zz-0002", "zz-gq")
    e.board("zz-0002", t + 10)
    e.run("watch", t=t + 60)
    check(not _woke(e) and not _bgs(e, "zz-gq"), f"0662 Д2: самозапуск поднял призрак с вопросом: {e.calls()}")
    # без вопроса тот же призрак самозапуск поднимает (контроль: проверка выше не пустая)
    e.agents([bg("zz-gq", "blocked", "cccccccc-1")])
    e.board("zz-0002", t + 70)
    e.run("watch", t=t + 120)
    check(_woke(e) or _bgs(e, "zz-gq"), f"0662 Д2: контроль — призрак без вопроса самозапуск не поднял: {e.calls()}")
    # Д1: noProcess-призрак (задание есть, вопроса нет) — ни «ждёт вас», ни тревоги о призраке; wake поднимает
    e2 = _ghost_env("zz-gn", updated=T0 - 1000)
    _job(e2, "ffffffff", state="blocked")
    e2.agents([bg("zz-gn", "blocked", "ffffffff-1")])
    e2.run("watch", t=t)
    check("zz-gn" not in e2.alerts(), f"0662 Д1: noProcess-призрак дал тревогу: {e2.alerts()}")
    out = e2.run("wake", "zz-gn", t=t).stdout
    check("поднята" in out and _woke(e2, "ffffffff"), f"0662 Д1: wake не поднял noProcess-призрак: {out}")


def test_registry_stale_record_249():
    """Ревью argus #249. Д1: запись реестра имён с тем же sessionId, но не того процесса — файл назван другим pid
    (pid 1 жив всегда) или время старта процесса не совпало с procStart — призрака не прячет; ps не дал ответа (metis-0679/0690) — «не знаю»: призрака не утверждаем, живого не гасим; совпало —
    прячет; то же для записи по jobId. Д2: мёртвая blocked-запись без вопроса при живой тёзке с другим sessionId — noProcess, без
    тревоги «ждёт вас». С2: pid 0 в реестре — не живой."""
    import json as _j
    t = T0 + 60

    def reg_file(e, fname, rec):
        d = os.path.join(e.home, ".claude", "sessions")
        os.makedirs(d, exist_ok=True)
        _j.dump(rec, open(os.path.join(d, f"{fname}.json"), "w"))

    def fake_ps(e, out):
        p = os.path.join(e.bin, "ps")
        open(p, "w").write("#!/bin/sh\n" + (f"echo '{out}'\n" if out else "exit 1\n"))
        os.chmod(p, 0o755)

    me = os.getpid()
    cases = (  # (имя файла, pid записи, procStart, вывод ps, призрак?)
        (4242, 1, None, None, True),                                          # файл не того pid
        (0, 0, None, None, True),                                             # pid 0 — группа, не процесс
        (me, me, "Mon Jan  1 00:00:00 2024", "Sun Nov  1 14:23:55 2026", True),  # pid занят другим процессом
        (me, me, "Sun Nov  1 14:23:55 2026", "Sun Nov  1 14:23:55 2026", False),  # тот самый процесс
        (me, me, "Sun Nov  1 14:23:55 2026", "", False),                      # ps не ответил — «не знаю», не призрак (metis-0690)
        (me, me, None, "", False),                                            # procStart в записи нет — сверять нечего
    )
    for fname, pid, proc, ps_out, ghost in cases:
        e = _ghost_env("zz-rs", updated=T0 - 1000)
        e.agents([bg("zz-rs", "working", "cccccccc-1")])
        reg_file(e, fname, dict(pid=pid, sessionId="cccccccc-1", name="zz-rs", kind="bg",
                                **({"procStart": proc} if proc else {})))
        if ps_out is not None:
            fake_ps(e, ps_out)
        out = e.run("wake", "zz-rs", t=t).stdout
        got = "поднята" in out and bool(_woke(e))
        check(got == ghost, f"Д1: файл {fname}, pid {pid}, procStart {proc!r}, ps {ps_out!r}: призрак {got}, "
                            f"а надо {ghost}: {out.strip()[:160]}")
    # argus-249a Б1: у живой фоновой sessionId в реестре бывает другим, совпадает jobId (= id записи claude agents)
    for job, ghost in (("cccccccc", False), ("dddddddd", True)):
        e = _ghost_env("zz-rj", updated=T0 - 1000)
        e.agents([bg("zz-rj", "working", "cccccccc-1")])
        _reg(e, dict(sessionId="ffffffff-9", jobId=job, name="zz-rj", kind="bg"))
        e.run("watch", t=t)  # wake тут не мерило: живая фоновая тёзка держит имя в любом случае (holders)
        got = "процесс умер" in e.alerts()
        check(got == ghost, f"Б1 jobId {job}: призрак {got}, а надо {ghost}: {e.alerts()[-300:]}")
    # metis-0679 (argus-249a Д1): тот же отбор для записи по jobId при чужом sessionId — файл не назван pid, procStart
    # не тот, ps не ответил (в песочнице окна) — не призрак (metis-0690); тот самый процесс — не призрак
    same = "Sun Nov  1 14:23:55 2026"
    for fname, proc, ps_out, ghost in ((4242, None, None, True),
                                       (me, "Mon Jan  1 00:00:00 2024", same, True),
                                       (me, same, "", False),  # ps недоступен — не призрак (metis-0690)
                                       (me, same, same, False)):
        e = _ghost_env("zz-rj", updated=T0 - 1000)
        e.agents([bg("zz-rj", "working", "cccccccc-1")])
        reg_file(e, fname, dict(pid=me, sessionId="ffffffff-9", jobId="cccccccc", name="zz-rj", kind="bg",
                                **({"procStart": proc} if proc else {})))
        if ps_out is not None:
            fake_ps(e, ps_out)
        e.run("watch", t=t)
        got = "процесс умер" in e.alerts()
        check(got == ghost, f"Д1 jobId: файл {fname}, procStart {proc!r}, ps {ps_out!r}: призрак {got}, а надо "
                            f"{ghost}: {e.alerts()[-300:]}")
    # Д2: живая тёзка с другим sessionId не снимает noProcess с мёртвой blocked-записи без вопроса
    e = _ghost_env("zz-nm", updated=T0 - 1000)
    _job(e, "aaaaaaaa", state="blocked")
    _reg(e, dict(sessionId="bbbbbbbb-2", name="zz-nm", kind="bg"))
    e.agents([bg("zz-nm", "blocked", "aaaaaaaa-1"), bg("zz-nm", "working", "bbbbbbbb-2", pid=me, started=T0)])
    e.run("watch", t=t)
    bad = [ln for ln in e.alerts().splitlines() if "aaaaaaaa" in ln and "ждёт вас" in ln]
    check(not bad, f"Д2: тёзка с другим sessionId — мёртвая запись «ждёт вас»: {bad}")


def test_ghost_detail_is_not_question_0662():
    """argus-249a Б1/Д1/Д2: detail задания (есть всегда) — не вопрос. Призрак blocked с мёртвым pid без needs, working-
    призрак с detail — wake поднимает, тревога советует wake. Вопрос из needs задания — по-прежнему ждёт ответа.
    Правка реестра демона из будущего не прячет призрак."""
    t = T0 + 60
    for state, pid in (("blocked", 999999), ("working", None)):
        e = _ghost_env("zz-gd", updated=T0 - 1000)
        _job(e, "cccccccc", state=state)
        e.agents([bg("zz-gd", state, "cccccccc-1", pid=pid)])
        e.run("watch", t=t)
        line = [ln for ln in e.alerts().splitlines() if "процесс умер" in ln]
        check(line and "pantheon wake zz-gd" in line[0] and "claude attach" not in line[0],
              f"Б1: призрак {state}/{pid} с detail — тревога как у вопроса: {line}")
        out = e.run("wake", "zz-gd", t=t).stdout
        check("поднята" in out and _woke(e), f"Б1: призрак {state}/{pid} с detail не поднят wake: {out}")
    # вопрос бывает только у blocked: working-призрак со старым needs в задании — wake поднимает (мутант m10);
    # noProcess (blocked без процесса и needs) с причиной в waitingFor записи — не вопрос, wake поднимает
    for state, rec_extra, job in (("working", {}, {"needs": "старый вопрос"}),
                                  ("blocked", {"waitingFor": "причина из claude agents"}, {})):
        e = _ghost_env("zz-gd", updated=T0 - 1000)
        _job(e, "cccccccc", state=state, **job)
        e.agents([dict(bg("zz-gd", state, "cccccccc-1"), **rec_extra)])
        out = e.run("wake", "zz-gd", t=t).stdout
        check("поднята" in out and _woke(e), f"Б1: {state} {rec_extra} {job} — принят за вопрос: {out}")
    # контроль: вопрос в needs задания (waitingFor записи пуст) — ждёт ответа, wake не поднимает
    e = _ghost_env("zz-gd", updated=T0 - 1000)
    _job(e, "cccccccc", state="blocked", needs="какую ветку слить?")
    e.agents([bg("zz-gd", "blocked", "cccccccc-1", pid=999999)])
    out = e.run("wake", "zz-gd", t=t).stdout
    check("ждёт вашего ответа" in out and not _woke(e), f"Б1: вопрос из needs не держит призрак: {out}")
    # Д2: updatedAt реестра демона на час вперёд — не «только что», призрак находится
    e = _ghost_env("zz-gd", updated=t + 3600)
    e.agents([bg("zz-gd", "working", "cccccccc-1")])
    out = e.run("wake", "zz-gd", t=t).stdout
    check("поднята" in out and _woke(e), f"Д2: правка реестра из будущего спрятала призрак: {out}")


def test_jobs_show_read_only_locks_0266():
    """metis-0266: `pantheon jobs` в окне, куда в STATE/locks не пишут (песочница), не падает с PermissionError: замок
    задачи показ открывает только на чтение. Замок держит другой процесс — «идёт»; файл замка не читается — «не знаю»,
    а остальные строки таблицы целы."""
    import fcntl
    e = Env()
    e.schedule('primary_host = "mac-a"\n[[job]]\nname = "jb-a"\ncommand = "pantheon sync-answers"\nevery = "tick"\n'
               '[[job]]\nname = "jb-b"\ncommand = "pantheon sync-answers"\nevery = "tick"\n')
    locks = e.st("locks")
    os.makedirs(locks, exist_ok=True)
    la, lb = os.path.join(locks, "job-jb-a.lock"), os.path.join(locks, "job-jb-b.lock")
    open(la, "w").close()
    open(lb, "w").close()
    os.chmod(la, 0o400)  # писать в замок нельзя (как в песочнице окна): O_WRONLY → PermissionError
    os.chmod(lb, 0o000)  # а этот и читать нельзя — «не знаю»
    os.chmod(locks, 0o500)
    try:
        if os.access(la, os.W_OK):  # root обходит права — проверять нечем
            return
        r = e.run("jobs", t=T0)
        check(r.returncode == 0 and "Traceback" not in r.stderr and "jb-a" in r.stdout and "jb-b" in r.stdout,
              f"0266: jobs при замках без записи: {r.returncode} {r.stderr[-300:]} {r.stdout[-300:]}")
        row_b = [ln for ln in r.stdout.splitlines() if ln.startswith("jb-b")]
        check(row_b and "идёт ли сейчас — не знаю" in row_b[0] and "не знаю (блокировка" in row_b[0],
              f"0266: нечитаемый замок — не «не знаю» в состоянии и в «дальше»: {row_b}")
        row_a = [ln for ln in r.stdout.splitlines() if ln.startswith("jb-a")]
        check(row_a and "идёт" not in row_a[0] and "не знаю" not in row_a[0],
              f"0266: свободный замок показан занятым: {row_a}")
    finally:
        os.chmod(locks, 0o700)
        os.chmod(lb, 0o600)
        os.chmod(la, 0o600)
    # замок держит другой процесс — «идёт» (и тоже без записи в замок)
    with open(la, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        os.chmod(locks, 0o500)
        try:
            r = e.run("jobs", t=T0)
            row_a = [ln for ln in r.stdout.splitlines() if ln.startswith("jb-a")]
            check(r.returncode == 0 and row_a and row_a[0].count("идёт") == 2,
                  f"0266: замок занят, а показ не «идёт»: {r.returncode} {row_a} {r.stderr[-200:]}")
        finally:
            os.chmod(locks, 0o700)
    # замка нет и создать его нельзя — задача свободна, показ не падает
    os.remove(lb)
    os.chmod(locks, 0o500)
    try:
        r = e.run("jobs", t=T0)
        row_b = [ln for ln in r.stdout.splitlines() if ln.startswith("jb-b")]
        check(r.returncode == 0 and row_b and "идёт" not in row_b[0] and not os.path.exists(lb),
              f"0266: нет файла замка: {r.returncode} {row_b} {r.stderr[-200:]}")
    finally:
        os.chmod(locks, 0o700)


def test_saved_zeus_in_read_only_state_0577():
    """metis-0577: `pantheon saved --by zeus` из окна штаба (песочница не пускает писать в STATE/maintenance и STATE/plugins)
    не падает с PermissionError: код 0, понятная строка в stderr без трассировки; для остальных окон — код 1 с той же
    строкой (метка им нужна). Метка там, куда писать можно, по-прежнему пишется (с id сессии)."""
    sid = "5a5a5a5a-1111-4111-8111-111111111111"
    own = {"PANTHEON_SESSION": "zeus", "CLAUDE_CODE_SESSION_ID": sid}
    e = Env()
    _maint(e, ["zeus", "dev-x"])
    md = e.st("maintenance")
    os.makedirs(md, exist_ok=True)
    os.chmod(md, 0o500)
    try:
        if os.access(md, os.W_OK):  # root обходит права — проверять нечем
            return
        r = e.run("saved", "--by", "zeus", "--state", "STATUS.md", extra=own)
        check(r.returncode == 0 and "Traceback" not in r.stderr and "не записана" in r.stderr and "ведёт владелец" in r.stderr,
              f"0577: saved zeus без записи в STATE: {r.returncode} {r.stderr[-300:]}")
        r = e.run("saved", "--by", "dev-x", "--state", "STATUS.md", extra={**own, "PANTHEON_SESSION": "dev-x"})
        check(r.returncode == 1 and "Traceback" not in r.stderr and "не записана" in r.stderr
              and "ведёт владелец" not in r.stderr, f"0577: saved другого окна без записи — не отказ: {r.returncode} {r.stderr[-300:]}")
        # перезапуск после плагинов: метка respawn-ok — тоже без трассировки
        e2 = Env()
        os.makedirs(e2.st("plugins"), exist_ok=True)
        json.dump({"since": T0 - 100, "plugins": ["pantheon"], "done": []}, open(e2.st("plugins", "respawn.json"), "w"))
        os.chmod(e2.st("plugins"), 0o500)
        try:
            r = e2.run("saved", "--by", "zeus", "--state", "STATUS.md", extra=own)
            check(r.returncode == 0 and "Traceback" not in r.stderr and "не записана" in r.stderr,
                  f"0577: saved zeus (после плагинов) без записи: {r.returncode} {r.stderr[-300:]}")
        finally:
            os.chmod(e2.st("plugins"), 0o700)
    finally:
        os.chmod(md, 0o700)
    r = e.run("saved", "--by", "zeus", "--state", "STATUS.md", extra=own)
    rec = json.load(open(e.st("maintenance", "zeus.json"))) if os.path.exists(e.st("maintenance", "zeus.json")) else {}
    check(r.returncode == 0 and rec.get("sessionId") == sid and not r.stderr.strip(), f"0577: запись при праве: {r} {rec}")


def test_restart_done_and_auto_close_0338():
    """metis-0338: завершённый техперезапуск закрывается — `restart --done` снимает метку и пишет в тревоги «завершён»; --status
    закрывает сам, когда все перезапущены, а Зевс (если был) поднят заново (id сессии не тот, что в его saved); пока Зевс
    не поднят или id неизвестен — метка стоит; --go без пропущенных пишет «завершён», а не «перезапущены»."""
    zold, znew = "20202020-0000-4000-8000-000000000001", "30303030-0000-4000-8000-000000000002"
    # --done: метка и отметки сняты, тревога «завершён», код 0
    e = Env()
    _maint(e, ["mm-dir", "zeus"])
    os.makedirs(e.st("maintenance"), exist_ok=True)
    open(e.st("maintenance", "mm-dir.done"), "w").write("x\n")
    r = e.run("restart", "--done", t=T0 + 60)
    check(r.returncode == 0 and not os.path.exists(e.st("maintenance.json"))
          and not os.listdir(e.st("maintenance")) and "технический перезапуск завершён" in e.alerts()
          and "mm-dir" in e.alerts() and "--done" in e.alerts(), f"0338: --done: {r.returncode} {r.stderr[-200:]} {e.alerts()}")
    check(e.run("restart", "--done", t=T0 + 70).returncode == 1, "0338: --done без метки — не «готово»")
    # --done при неперезапущенной сессии — закрывает, но называет её
    e = Env()
    _maint(e, ["mm-dir"])
    r = e.run("restart", "--done", t=T0 + 60)
    check(r.returncode == 0 and "без перезапуска: mm-dir" in r.stdout and "остались: mm-dir" in e.alerts(),
          f"0338: --done с остатком: {r.stdout!r} {e.alerts()}")

    def zeus_case(saved_sid, live_sid, done=True):
        e = Env()
        e.direction("mm-dir")
        _maint(e, ["mm-dir", "zeus"])
        os.makedirs(e.st("maintenance"), exist_ok=True)
        if done:
            open(e.st("maintenance", "mm-dir.done"), "w").write("x\n")
        json.dump({"time": "2026-10-15 10:00:00", "state": "S", "by": "zeus", **({"sessionId": saved_sid} if saved_sid else {})},
                  open(e.st("maintenance", "zeus.json"), "w"))
        e.agents([bg("zeus", "working", live_sid, pid=77)] if live_sid else [])
        return e, e.run("restart", "--status", t=T0 + 60)
    e, r = zeus_case(zold, znew)
    check(r.returncode == 0 and not os.path.exists(e.st("maintenance.json")) and "перезапуск завершён" in r.stdout
          and "технический перезапуск завершён" in e.alerts(), f"0338: --status, Зевс поднят заново: {r.stdout!r} {r.stderr[-200:]}")
    for what, args in (("Зевс всё ещё старый", (zold, zold)), ("id Зевса в saved неизвестен", (None, znew)),
                       ("Зевса нет среди живых", (zold, None))):
        e, r = zeus_case(*args)
        check(os.path.exists(e.st("maintenance.json")) and "Зевс" in r.stdout and "технический перезапуск завершён" not in e.alerts(),
              f"0338: {what} — метка должна стоять: {r.stdout!r}")
    e, r = zeus_case(zold, znew, done=False)
    check(os.path.exists(e.st("maintenance.json")), f"0338: сессия не перезапущена — --status не закрывает: {r.stdout!r}")
    # --go без пропущенных: тревога «завершён»
    e = Env()
    e.direction("mm-dir")
    e.agents([bg("mm-dir", "working", "mmmmmmmm-1", pid=21)])
    e.run("restart", "--prepare", "обновление", t=T0)
    e.run("saved", "--by", "mm-dir", "--state", "STATUS.md", t=T0 + 20)
    r = e.run("restart", "--go", t=T0 + 40, extra={"PANTHEON_DRYRUN": "1", "PANTHEON_ALERTS_IN_DRYRUN": "1"})
    check(r.returncode == 0 and "технический перезапуск завершён" in e.alerts() and not os.path.exists(e.st("maintenance.json")),
          f"0338: --go без пропущенных: {r.stdout!r} {e.alerts()!r}")


def test_resume_picks_saved_session_0499():
    """metis-0499: продолжение остановленной сессии (resume_or_start: wake, самозапуск) берёт ту, что записала `pantheon saved`
    (id в метке), а не самую свежую по startedAt; метки нет или id среди остановленных нет — прежний выбор. Перезапуск
    после плагинов: метка «можно» с id сессии относится только к ней, другая живая копия ждёт простоя."""
    saved_id = "5a5a5a5a-1111-4111-8111-111111111111"
    other = "bbbbbbbb-2222-4222-8222-222222222222"
    for with_mark, want in (("maintenance", "5a5a5a5a"), ("respawn-ok", "5a5a5a5a"), (None, "bbbbbbbb"), ("gone", "bbbbbbbb")):
        e = Env()
        e.direction("sv-dir")
        e.agents([bg("sv-dir", "stopped", saved_id, started=T0 - 500), bg("sv-dir", "stopped", other, started=T0 - 10)])
        if with_mark:
            rec = {"time": "2026-10-15 10:00:00", "state": "S", "by": "x", "t": T0 - 50,
                   "sessionId": saved_id if with_mark != "gone" else "cccccccc-3333-4333-8333-333333333333"}
            d = e.st("maintenance") if with_mark in ("maintenance", "gone") else e.st("plugins", "respawn-ok")
            os.makedirs(d, exist_ok=True)
            json.dump(rec, open(os.path.join(d, "sv-dir.json"), "w"))
        r = e.run("wake", "sv-dir", t=T0, extra={"PANTHEON_DRYRUN": "1"})
        check(f"[resume] sv-dir {want}" in r.stdout, f"0499: метка {with_mark}: ждали {want}: {r.stdout!r} {r.stderr[-200:]}")
    # перезапуск после плагинов: метка «можно» с id другой копии не освобождает эту (транскрипт свежий — без метки ждёт)
    for sid_in_mark, want in ((None, True), ("5a5a5a5a-1111-4111-8111-111111111111", True),
                              ("bbbbbbbb-2222-4222-8222-222222222222", False)):
        e, a, tp = respawn_env("rk-dir", "5a5a5a5a-1111-4111-8111-111111111111", state="done")
        os.utime(tp, (T0 - 60, T0 - 60))
        rec = {"t": T0 - 10, "time": "x", "state": "S", "by": "x"}
        if sid_in_mark:
            rec["sessionId"] = sid_in_mark
        os.makedirs(e.st("plugins", "respawn-ok"), exist_ok=True)
        json.dump(rec, open(e.st("plugins", "respawn-ok", "rk-dir.json"), "w"))
        e.run("watch", t=T0)
        check(respawned(e, "5a5a5a5a") == want, f"0499: метка «можно» с id {sid_in_mark}: перезапущено={not want}: {e.calls()}")
    # saved записывает id сессии и в метку «можно»
    e, a, tp = respawn_env("rk-dir", "5a5a5a5a-1111-4111-8111-111111111111", state="working", status="busy")
    e.run("saved", "--by", "rk-dir", "--state", "S", t=T0,
          extra={"PANTHEON_SESSION": "rk-dir", "CLAUDE_CODE_SESSION_ID": "5a5a5a5a-1111-4111-8111-111111111111"})
    check(json.load(open(e.st("plugins", "respawn-ok", "rk-dir.json"))).get("sessionId") == "5a5a5a5a-1111-4111-8111-111111111111",
          "0499: saved не записал id в метку «можно»")

def test_goal_dates_0829():
    """metis-0829 п. 4: цель или бюджет в directions.toml с прошедшей датой → одна тревога координатору направления на
    (направление, поле, дата); повтор прохода молчит; дата не прошла или дат нет — тревоги нет; новая прошедшая дата —
    новая тревога; поле обновили — отметка снята и следующая прошедшая дата снова тревожит."""
    e = Env()
    toml = os.path.join(e.pantheon, "directions.toml")

    def put(goal, budget=None):
        body = f'[[direction]]\nname = "gl-dir"\ngoal = "{goal}"\n' + (f'budget = "{budget}"\n' if budget else "")
        open(toml, "w", encoding="utf-8").write(body)

    def n(what="устарела"):
        return e.alerts().count(what)

    put("выпуск сайта до 10.10")
    e.run("watch", t=T0)
    check(n() == 1 and "gl-dir" in e.alerts() and "цель устарела" in e.alerts() and "Координатору gl-dir" in e.alerts(),
          f"0829: прошла дата цели — нет одной тревоги координатору: {e.alerts()!r}")
    e.run("watch", t=T0 + 300)
    e.run("watch", t=T0 + 600)
    check(n() == 1, f"0829: повтор прохода дал вторую тревогу: {e.alerts()!r}")
    put("выпуск сайта до 20.10")
    e.run("watch", t=T0 + 900)
    check(n() == 1, "0829: новая дата ещё не прошла — тревога на ровном месте")
    put("выпуск сайта до 10.10")
    e.run("watch", t=T0 + 1200)
    check(n() == 2, f"0829: дата снова прошла (после обновления) — тревоги нет: {e.alerts()!r}")
    put("выпуск сайта до 11.10")
    e.run("watch", t=T0 + 1500)
    check(n() == 3, "0829: другая прошедшая дата — новой тревоги нет")
    put("без дат, версия 1.0")
    e.run("watch", t=T0 + 1800)
    check(n() == 3 and "упала" not in e.alerts(), f"0829: в цели дат нет — тревога или проверка упала: {e.alerts()!r}")
    put("этап 1 до 10.10, этап 2 до 25.10")
    e.run("watch", t=T0 + 1950)
    check(n() == 3, "0829: прошла только ранняя дата, поздняя впереди — тревога (нужны все даты прошедшими)")
    put("цель на сегодня " + time.strftime("%d.%m", time.localtime(T0)))
    e.run("watch", t=T0 + 2100)
    check(n() == 3, "0829: срок сегодня ещё не прошёл — тревога")
    put("цель живая до 25.10", "бюджет до 09.10")
    e.run("watch", t=T0 + 2400)
    check(n() == 4 and "бюджет недели устарела" in e.alerts(), f"0829: бюджет с прошедшей датой — нет тревоги: {e.alerts()!r}")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
