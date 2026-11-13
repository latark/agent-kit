#!/usr/bin/env python3
"""Дежурный, часть 4: разовый запуск, память, «сейчас» сессии устарело (общая часть — _watch_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403


def test_start_at_oneshot_0284():
    """`pantheon start <направление> --at ЧЧ:ММ` — запись для планового прохода, не sleep: до времени не запускает,
    после — ровно один запуск с заданием, повторный проход не повторяет; --at-cancel гасит, --at-list показывает."""
    e = Env()
    e.direction("athena-a")
    hhmm = time.strftime("%H:%M", time.localtime(T0 + 600))
    r = e.run("start", "athena-a", "--at", hhmm, "сделай", "проверку", "0284", t=T0)
    check(r.returncode == 0 and "разовый запуск at-" in r.stdout, f"--at: {r.returncode} {r.stdout} {r.stderr}")
    check(not _bgs(e), f"--at запустил сразу: {e.calls()}")
    e.run("watch", t=T0 + 300)
    check(not _bgs(e), f"запуск раньше времени: {e.calls()}")
    e.run("watch", t=T0 + 660)
    got = _bgs(e, "athena-a")
    check(len(got) == 1 and any("сделай проверку 0284" in x for x in got[0]), f"разовый запуск не пошёл: {e.calls()}")
    e.run("watch", t=T0 + 720)
    e.run("watch", t=T0 + 1200)
    check(len(_bgs(e, "athena-a")) == 1, f"разовый запуск повторён: {_bgs(e)}")
    # отмена: второй запуск на +40 мин отменён — не идёт
    hh2 = time.strftime("%H:%M", time.localtime(T0 + 2400))
    r = e.run("start", "athena-a", "--at", hh2, "второй", t=T0 + 1300)
    oid = r.stdout.split("разовый запуск ")[1].split(":")[0] if "разовый запуск " in r.stdout else "?"
    lst = e.run("start", "--at-list", t=T0 + 1310).stdout
    check(oid in lst, f"--at-list без записи {oid}: {lst}")
    r = e.run("start", "--at-cancel", oid, t=T0 + 1320)
    check(r.returncode == 0, f"--at-cancel: {r.stdout} {r.stderr}")
    e.run("watch", t=T0 + 2500)
    check(len(_bgs(e, "athena-a")) == 1, f"отменённый разовый запуск пошёл: {_bgs(e)}")
    check(e.run("start", "--at-cancel", oid, t=T0 + 2600).returncode == 1, "повторная отмена не отказ")
    check(e.run("start", "nope-dir", "--at", hh2, t=T0 + 2600).returncode == 2, "--at не направления принят")
    check(e.run("start", "athena-a", "--at", "2020-01-01 10:00", t=T0 + 2600).returncode == 2, "--at в прошлом принят")


def test_oneshot_expires_0284():
    """Разовая запись после срока (expires) не запускается: гасится с результатом «срок вышел» и тревогой (ревью
    argus M9, #78)."""
    e, oid = _oneshot_env()
    e.run("watch", t=_oneshot_rec(e, oid)["expires"] + 60)
    check(not _bgs(e), f"запись с вышедшим сроком запущена: {e.calls()}")
    rec = _oneshot_rec(e, oid)
    check(rec["done_at"] and "срок вышел" in (rec["result"] or "") and rec["result"].startswith("не запущен"),
          f"запись не погашена по сроку: {rec}")
    check(f"разовый запуск {oid} погашен без запуска" in e.alerts(), f"нет тревоги: {e.alerts()[-300:]}")


def test_oneshot_week_gate_0284():
    """Закрытый недельный запор (жёлтая зона днём) не пускает разовый запуск: запуска нет, запись не погашена и ждёт
    с причиной «недельный лимит»; запор открылся до срока — запуск идёт (ревью argus M11, #78)."""
    e, oid = _oneshot_env()
    e.week_pct = 31.6
    e.run("watch", t=T0 + 660)
    e.run("watch", t=T0 + 720)
    check(not _bgs(e), f"запуск при закрытом запоре: {e.calls()}")
    rec = _oneshot_rec(e, oid)
    check(not rec["done_at"] and "недельный лимит" in (rec["wait"] or ""), f"запись не ждёт запора: {rec}")
    e.week_pct = 10.0
    e.run("watch", t=T0 + 780)
    check(len(_bgs(e, "athena-a")) == 1, f"запор открылся, запуска нет: {e.calls()}")
    check(_oneshot_rec(e, oid)["done_at"], "запущенная запись не погашена")


def test_red_memory_warns_oneshot_0523():
    """[sb-simplify] п. 5 (metis-0523; было metis-0261 А — «отложено»): красный замер памяти разовый запуск не держит —
    запуск в том же проходе, запись погашена, в тревогах — предупреждение о памяти, а не «ждёт»."""
    e, oid = _oneshot_env()
    e.run("watch", t=T0 + 660, extra={"PANTHEON_FAKE_SWAP": "9"})
    check(len(_bgs(e, "athena-a")) == 1, f"0523: красная память отложила разовый запуск: {e.calls()}")
    rec = _oneshot_rec(e, oid)
    check(rec["done_at"] and rec["result"] == "запущен" and not rec.get("wait"), f"0523: запись не погашена: {rec}")
    check("красной памяти" in e.alerts() and "предупреждение" in e.alerts(),
          f"0523: нет предупреждения о памяти: {e.alerts()[-300:]}")


def test_red_memory_warns_zeus_oneshot_0523():
    """metis-0523: запись `--at --from zeus` со словом владельца при постановке исполняется плановым проходом и при
    красной памяти (слово проверено при постановке, память — только предупреждение)."""
    e = Env()
    e.direction("athena-a")
    with open(e.st("owner-log", "zeus.md"), "w") as fh:
        fh.write(f"## {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(T0 - 30))} · окно вопросов\nда\n\n")
    hhmm = time.strftime("%H:%M", time.localtime(T0 + 600))
    r = e.run("start", "athena-a", "--at", hhmm, "--from", "zeus", "задание", t=T0)
    check(r.returncode == 0, f"постановка со словом отказана: {r.stdout} {r.stderr}")
    oid = r.stdout.split("разовый запуск ")[1].split(":")[0]
    check(_oneshot_rec(e, oid)["by"] == "zeus", f"origin не сохранён: {_oneshot_rec(e, oid)}")
    e.run("watch", t=T0 + 660, extra={"PANTHEON_FAKE_SWAP": "9"})
    check(len(_bgs(e, "athena-a")) == 1 and _oneshot_rec(e, oid)["done_at"],
          f"0523: красная память отложила запись со словом: {e.calls()}")


def test_red_memory_warns_autostart_0523():
    """metis-0523: красный замер (своп 9 ГБ, давление «предупреждение») самозапуск не держит — запуск в первом же
    проходе, сбоя и паузы нет."""
    for label, ex in (("своп", {"PANTHEON_FAKE_SWAP": "9"}), ("давление", {"PANTHEON_FAKE_PRESSURE": "2"})):
        e = Env()
        e.direction("hermes-x")
        e.task("hermes-0001", "hermes-x")
        e.run("watch", t=T0)
        e.board("hermes-0001", T0 + 10)
        e.run("watch", t=T0 + 60, extra=ex)
        st = json.load(open(e.st("autostart.json"))).get("hermes-x") or {}
        check(len(_bgs(e, "hermes-x")) == 1, f"0523 {label}: самозапуск отложен по памяти: {e.calls()}")
        check(not st.get("fails") and st.get("pending"), f"0523 {label}: состояние самозапуска: {st}")
        check("самозапуск: hermes-x по задачам hermes-0001 — запущен" in e.alerts(),
              f"0523 {label}: нет строки самозапуска: {e.alerts()[-300:]}")


def test_oneshot_pack_and_hand_same_minute_0284():
    """Ручной --at и пачка ночи на ту же минуту и цель — обе записи живут; пачка идёт со своим текстом и сверкой sha:
    изменённая пачка не стартует, а ручная запись при этом запускается (ревью argus п. 1, #78)."""
    e = Env()
    e.direction("athena-a")
    pk = os.path.join(e.pantheon, "directions", "athena-a", "night-pack.md")
    open(pk, "w").write("пачка\n")
    when = T0 + 600
    hm_ = time.strftime("%H:%M", time.localtime(when))
    e.run("start", "athena-a", "--at", hm_, "ручное", t=T0)
    pid = "pack-" + time.strftime("%Y%m%d-%H%M", time.localtime(when)) + "-athena-a"
    store = json.load(open(e.st("oneshot.json")))
    store["items"].append({"id": pid, "target": "athena-a", "at": float(when), "expires": float(when + 3600),
                           "text": "текст пачки", "by": "night", "created": "", "done_at": None, "result": None,
                           "wait": None, "pack": "directions/athena-a/night-pack.md",
                           "sha": hashlib.sha256(open(pk, "rb").read()).hexdigest()})
    json.dump(store, open(e.st("oneshot.json"), "w"))
    items = json.load(open(e.st("oneshot.json")))["items"]
    check(len(items) == 2 and pid.startswith("pack-"), f"записей {len(items)}: {items}")
    open(pk, "a").write("дописано\n")
    e.run("watch", t=T0 + 660)
    rec = _oneshot_rec(e, pid)
    check(rec["done_at"] and "изменилась после фиксации" in rec["result"], f"sha пачки не сверена: {rec}")
    got = _bgs(e, "athena-a")
    check(len(got) == 1 and any("ручное" in x for x in got[0]) and not any("текст пачки" in x for x in got[0]),
          f"ручная запись не ушла или ушла пачка: {e.calls()}")


def test_schedule_night_off_0459():
    """Тестовый schedule.toml выключает ночь: ни в каком часовом поясе T0 не ночь и не вечер (Env.schedule)."""
    for off in (True, False):
        e = Env()
        if not off:  # контроль пробы: с ночью по умолчанию в поясе UTC+6 (T0 = 23:46) ночь видна
            open(os.path.join(e.pantheon, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
        else:
            e.schedule('primary_host = "mac-a"\n')
        for tz in ("UTC", "Etc/GMT-6", "Etc/GMT+8", "Europe/Moscow"):
            env = dict(os.environ, HOME=e.home, PANTHEON_HOME=e.pantheon, PANTHEON_STATE=e.state, TZ=tz,
                       PANTHEON_HOST="mac-a")
            r = subprocess.run([sys.executable, "-I", "-c", _NIGHT_PROBE, LIB, str(T0)],
                               capture_output=True, text=True, env=env)
            got = r.stdout.strip()
            if off:
                check(got == "None None None", f"в поясе {tz} T0 попал в ночь/вечер: {got!r} {r.stderr[-200:]}")
            elif tz == "Etc/GMT-6":
                check(got != "None None None", f"контроль: ночь по умолчанию в UTC+6 не видна: {got!r} {r.stderr[-200:]}")


def test_isolation_and_watch_last():
    """Сбой одной проверки — тревога о ней, остальные идут; watch-last пишет время и упавшие."""
    e = Env()
    e.direction("iso-dir")
    e.schedule('primary_host = "mac-a"\n[defaults]\nswap_alert_gb = "x"\nlimit_max_pct = 70\n')
    os.makedirs(e.st("swap.jsonl"))                             # запись замеров swap упадёт
    r = e.run("watch", t=T0)
    wl = json.load(open(e.st("watch-last")))
    check(wl["time"] == T0 and wl["failed"] == ["swap"], f"watch-last: {wl} {r.stderr[-300:]}")
    check("проверка «swap» упала" in e.alerts(), "тревога о сбое проверки")
    check(os.path.exists(e.st("agents.json")) and os.path.exists(e.st("cc-version")), "остальные проверки не шли")
    out = e.run("status", t=T0 + 60).stdout
    check("упали проверки: swap" in out, f"status не видит сбой дежурного: {out[:400]}")


def test_status_long_and_swap_keep():
    e = Env()
    e.direction("long-dir")
    open(os.path.join(e.pantheon, "directions", "long-dir", "STATUS.md"), "w").write("x\n" * 201)
    with open(e.st("swap.jsonl"), "w") as fh:
        fh.write(json.dumps({"t": T0 - 14 * 86400, "gb": 1}) + "\n" + json.dumps({"t": T0 - 16 * 86400, "gb": 1}) + "\n")
    e.agents([bg("long-dir", "working", "llllllll-1", pid=51)])
    e.run("watch", t=T0, extra={"PANTHEON_FAKE_SWAP": "6", "PANTHEON_FAKE_PS": "123 claude attach abc"})
    check("STATUS.md long-dir — 201 строк" in e.alerts(), "тревога о длинном STATUS.md")
    rows = [json.loads(ln) for ln in open(e.st("swap.jsonl"))]
    check(len(rows) == 2 and rows[-1].get("working") == 1, f"замеры swap 15 дней: {rows}")
    check("работают сессий: 1" in e.alerts() and "claude attach" in e.alerts(), "тревога swap")


def test_stale_now_0707():
    """metis-0707: «Сейчас» в STATUS.md окна, у которого были ходы за последние 6 ч, старше 6 ч — тревога; свежий,
    без хода, без раздела — нет; без даты в заголовке — по mtime файла; «Мx» читается; напоминание роли."""
    H = 3600
    def alerted(e):
        return "раздел «Сейчас» не обновлялся" in e.alerts()
    e = _now_env("sn-fresh", f"## Сейчас ({_stamp(5 * H + 3000)})")
    e.run("watch", t=T0)
    check(not alerted(e), "0707: «Сейчас» 5 ч 50 мин — тревога на свежий")
    e = _now_env("sn-old", f"## Сейчас ({_stamp(6 * H + 600)})")
    e.run("watch", t=T0)
    check(alerted(e) and "sn-old" in e.alerts(), f"0707: «Сейчас» 6 ч 10 мин — нет тревоги: {e.alerts()}")
    e.run("watch", t=T0 + 300)
    check(e.alerts().count("раздел «Сейчас» не обновлялся") == 1, "0707: тревога повторилась в следующем проходе")
    e = _now_env("sn-notr", f"## Сейчас ({_stamp(8 * H + 600)})", turn_ago=None)
    e.run("watch", t=T0)
    check(not alerted(e), "0707: нет транскрипта (ходов нет) — тревога")
    e = _now_env("sn-idle", f"## Сейчас ({_stamp(9 * H)})", turn_ago=7 * H)
    e.run("watch", t=T0)
    check(not alerted(e), "0707: старый «Сейчас», а ходов за 6 ч нет — тревога")
    e = _now_env("sn-nodate", "## Сейчас", mtime_ago=7 * H)
    e.run("watch", t=T0)
    check(alerted(e), "0707: заголовок без даты, mtime 7 ч — нет тревоги")
    e = _now_env("sn-nodate", "## Сейчас", mtime_ago=2 * H)
    e.run("watch", t=T0)
    check(not alerted(e), "0707: заголовок без даты, mtime 2 ч — тревога")
    e = _now_env("sn-none", None, mtime_ago=9 * H)
    e.run("watch", t=T0)
    check(not alerted(e), "0707: раздела «Сейчас» нет — тревога")
    e = _now_env("sn-x", f"## Сейчас ({_stamp(7 * H, 'x')})")
    e.run("watch", t=T0)
    check(alerted(e), "0707: заголовок «ЧЧ:Мx» старше 6 ч — нет тревоги")
    # напоминание роли: простаивающая живая сессия получает строку один раз; работающая — только тревога
    e = _now_env("sn-push", f"## Сейчас ({_stamp(7 * H)})", state="done", pid=4242)
    e.run("watch", t=T0)
    first = [c for c in e.calls() if c[:1] == ["respawn"]]
    e.run("watch", t=T0 + 300)
    again = [c for c in e.calls() if c[:1] == ["respawn"]]
    check(alerted(e) and len(first) == 1 and len(again) == 1, f"0707: напоминание простаивающей: {first} {again}")
    e = _now_env("sn-busy", f"## Сейчас ({_stamp(7 * H)})", state="working", pid=4243)
    e.run("watch", t=T0)
    check(alerted(e) and not [c for c in e.calls() if c[:1] == ["respawn"]], "0707: работающей — только тревога")


def test_now_from_fact_1005():
    """metis-1005: шапка «Сейчас» STATUS.md — по времени последней строки журнала; остальной текст цел; недавно правленный
    файл и файл без журнала не трогаем; ручной раздел с датой старше журнала больше 6 ч — тревога владельцу файла."""
    H = 3600
    j = _stamp(3600)  # журнал: час назад
    body = (f"# STATUS\n\n## Сейчас ({_stamp(30 * H)})\n- руками написанный шаг\n\n## Ход\n{_stamp(5 * H)} старая запись\n"
            f"{j} свежая запись\n13:5x запись без даты\n")
    e, p = _fact_env("nf-head", body)
    e.run("watch", t=T0)
    out = open(p, encoding="utf-8").read()
    want = f"## Сейчас ({j[:-1]}x)"
    check(want in out and out.replace(want, f"## Сейчас ({_stamp(30 * H)})") == body,
          f"1005: шапка не по журналу или тронут остальной текст: {out!r}")
    check(os.stat(p).st_mtime == T0 - 7200 + 1,
          "1005: mtime после замены шапки не «прежний + 1 с»: сдвиг — возраст файла и дата журнала без даты поедут, "
          "без сдвига — rsync копии Obsidian (размер и mtime) не увидит шапку той же длины")
    ino = os.stat(p).st_ino
    e.run("watch", t=T0 + 300)
    check(os.stat(p).st_ino == ino, "1005: шапка уже верна — файл переписан второй раз")
    e, p = _fact_env("nf-fresh", body, mtime_ago=5)
    e.run("watch", t=T0)
    check(open(p, encoding="utf-8").read() == body, "1005: файл правили 5 с назад — шапку переписали (гонка с ролью)")
    nojournal = "# STATUS\n\n## Сейчас (01.01 00:0x)\n- шаг\n"
    e, p = _fact_env("nf-nojr", nojournal)
    e.run("watch", t=T0)
    check(open(p, encoding="utf-8").read() == nojournal, "1005: журнала нет — шапку переписали")
    # ручной раздел с датой
    def alerted(e):
        return "ручной раздел с датой старше журнала" in e.alerts()
    sec = lambda ago: (f"# STATUS\n\n## Сейчас\n- шаг\n\n## Ждёт владельца ({_stamp(ago)})\n- вопрос\n\n"
                       f"## Ход\n{_stamp(0)} запись\n")
    e, p = _fact_env("nf-late", sec(7 * H))
    e.run("watch", t=T0)
    check(alerted(e) and "nf-late" in e.alerts() and "Ждёт владельца" in e.alerts() and "координатор nf-late" in e.alerts(),
          f"1005: раздел старше журнала на 7 ч — нет тревоги владельцу: {e.alerts()}")
    e.run("watch", t=T0 + 300)
    check(e.alerts().count("ручной раздел с датой старше журнала") == 1, "1005: тревога повторилась в следующем проходе")
    e, p = _fact_env("nf-ok", sec(5 * H))
    e.run("watch", t=T0)
    check(not alerted(e), f"1005: раздел старше журнала на 5 ч — тревога: {e.alerts()}")
    e, p = _fact_env("nf-arch", "# STATUS\n\n## Ранее (01.01 10:00) — в archive/STATUS-x.md\n\n## Ход\n" + _stamp(0) + " запись\n")
    e.run("watch", t=T0)
    check(not alerted(e), "1005: указатель на archive/ принят за ручной раздел")
    e, p = _fact_env("nf-upd", f"# STATUS\n\n## Открытые задачи\nОбновлено {_stamp(9 * H)}\n\n## Ход\n{_stamp(0)} запись\n")
    e.run("watch", t=T0)
    check(alerted(e), "1005: строка «Обновлено …» старше журнала на 9 ч — нет тревоги")
    e, p = _fact_env("nf-nojr2", f"# STATUS\n\n## Ждёт владельца ({_stamp(40 * H)})\n- вопрос\n")
    e.run("watch", t=T0)
    check(not alerted(e), "1005: журнала нет — сравнивать не с чем, тревоги быть не должно")



def test_retime_race_1005():
    """metis-1005 (Д1 argus #399): роль дописала STATUS.md между чтением и заменой — файл не тронут, ручная строка цела."""
    import importlib
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    w, nf = importlib.import_module("watch"), importlib.import_module("nowfact")
    saved = w.P
    w.P = type("Core", (), {"boardtext_mod": staticmethod(lambda: type("B", (), {"nowfact": staticmethod(lambda: nf)}))})
    try:
        d = tempfile.mkdtemp(prefix="race-", dir=os.environ.get("TMPDIR"))
        p = os.path.join(d, "STATUS.md")
        body = "## Сейчас (01.11 10:0x)\n\n## Ход\n08.11 10:00 а\n"
        open(p, "w", encoding="utf-8").write(body)
        os.utime(p, (T0 - 3600, T0 - 3600))
        st = os.stat(p)
        real_chmod = os.chmod

        def chmod_and_append(path, mode):  # роль дописывает файл, пока пишется временный (Д5 argus #399)
            real_chmod(path, mode)
            with open(p, "a", encoding="utf-8") as fh:
                fh.write("РУЧНАЯ\n")
        os.chmod = chmod_and_append
        try:
            out, _ = w.retime_status("race", p, body, st, T0)
        finally:
            os.chmod = real_chmod
        check(out == body and "РУЧНАЯ" in open(p, encoding="utf-8").read(),
              "1005: файл менялся, пока писали временный, — шапку заменили и ручная строка потеряна")
        check(not [f for f in os.listdir(d) if f.endswith(".tmp")], "1005: временный файл остался")
    finally:
        w.P = saved

def test_stale_now_push_fail_0707():
    """metis-0707 (argus-277, Б и Д): напоминание не доставлено (respawn, код 1) — отметка пишется всё равно: за 3 прохода
    один respawn и одна тревога; сбой проверки одного направления не обрывает следующие."""
    H = 3600
    e = _now_env("sn-fail", f"## Сейчас ({_stamp(7 * H)})", state="done", pid=4244)
    for i in range(3):
        e.run("watch", t=T0 + 300 * i, extra={"FAKE_RESPAWN_RC": "1", "FAKE_RESUME_RC": "1"})
    n = len([c for c in e.calls() if c[:1] == ["respawn"]])
    a = e.alerts().count("напоминание про «Сейчас» не доставлено (код 1)")
    check(n == 1 and a == 1, f"0707: отказ напоминания, 3 прохода: respawn {n}, тревог {a}")
    # Д: исключение в stale_now первого направления (непрочитанная отметка) не мешает второму
    e = _now_env("sn-boom", f"## Сейчас ({_stamp(7 * H)})", state="done", pid=4245)
    _now_env("sn-next", f"## Сейчас ({_stamp(7 * H)})", state="working", pid=4246, e=e)
    safe = re.sub(r"[^\w.-]", "_", "watch-now-push-sn-boom")[:60]
    mark = os.path.join(e.st("once"), f"{safe}-{hashlib.sha1(b'watch-now-push-sn-boom').hexdigest()[:8]}")
    os.makedirs(e.st("once"), exist_ok=True)
    open(mark, "wb").write(b"\xff\xfe\xfa")
    r = e.run("watch", t=T0)
    al = e.alerts()
    check("sn-boom: проверка «Сейчас» упала" in al and "STATUS.md sn-next: раздел «Сейчас» не обновлялся" in al,
          f"0707: сбой одного направления обрывает следующее: rc={r.returncode} {al[-500:]}")


def test_culprits_wired_0568():
    """metis-0568: дежурный в красной зоне зовёт проверку «виновники памяти» — строка с таблицей в alerts.md, одна на
    эпизод; в зелёной зоне и без подмены процессов (тесты не читают настоящий ps) строки нет. Подробно — test_culprits.py."""
    e = Env()
    folder = e.direction("athena-c")
    gone = os.path.join(folder, ".claude", "worktrees", "agent-gone")
    procs = json.dumps([{"pid": 4242, "ppid": 1, "age": 5 * 3600, "rss": 900 * 1024, "args": "node zprobe1.ts",
                         "cwd": gone}])
    e.run("watch", t=T0, extra={"PANTHEON_FAKE_SWAP": "9"})
    check("виновники памяти" not in e.alerts(), "0568: без подмены процессов настоящий ps в тестах не читается")
    e.run("watch", t=T0 + 60, extra={"PANTHEON_FAKE_PROCS": procs})
    check("виновники памяти" not in e.alerts(), "0568: зелёная зона — без строки")
    e.run("watch", t=T0 + 120, extra={"PANTHEON_FAKE_SWAP": "9", "PANTHEON_FAKE_PROCS": procs})
    e.run("watch", t=T0 + 420, extra={"PANTHEON_FAKE_SWAP": "9", "PANTHEON_FAKE_PROCS": procs})
    a = e.alerts()
    check(a.count("виновники памяти") == 1 and "node zprobe1.ts (pid 4242) → athena-c, worktree agent-gone" in a
          and "проверка «виновники памяти» упала" not in a, f"0568: строка виновников в тревогах: {a[-600:]}")


def test_owner_logs_daily():
    """Раз в сутки: записи старше 30 дней уходят, права сужаются, изменение задним числом — тревога."""
    e = Env()
    d = e.st("owner-log")
    old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 - 40 * 86400))
    new = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 - 86400))
    p = os.path.join(d, "athena.md")
    open(p, "w").write(f"## {old}\nстарое\n\n## {new}\nсвежее\n\n")
    os.chmod(p, 0o644)
    open(os.path.join(d, "gone.md"), "w").write(f"## {old}\nтолько старое\n\n")
    e.board("x-0001", T0 - 40 * 86400)
    e.board("x-0002", T0 - 86400)
    os.makedirs(e.st("logs"), exist_ok=True)
    hl = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 - 3600))
    open(e.st("logs", "ctx-hooks.log"), "w").write(f"{hl} owner-log пропуск: agent_type=''\n")
    e.run("watch", t=T0)
    check("хуки контекста" not in e.alerts(), "тревога на пояснения в ctx-hooks.log")
    with open(e.st("logs", "ctx-hooks.log"), "a") as fh:
        fh.write(f"{hl} start KeyError: 'x'\n")
    os.remove(e.st("watch-daily"))
    e.run("watch", t=T0)
    check("хуки контекста: сбоев за сутки 1" in e.alerts(), "сбой хука без тревоги")
    text = open(p).read()
    check("старое" not in text and "свежее" in text, f"уборка журнала: {text}")
    check(not os.path.exists(os.path.join(d, "gone.md")), "пустой журнал не удалён")
    check(oct(os.stat(p).st_mode & 0o777) == "0o600", "права журнала не сужены")
    check(len(open(os.path.join(d, "board.jsonl")).read().splitlines()) == 1, "board.jsonl не убран")
    # подмена уже записанной части — тревога на следующие сутки
    open(p, "w").write(text.replace("свежее", "подменённое"))
    e.run("watch", t=T0 + 86400)
    check("изменена уже записанная часть" in e.alerts(), "подмена журнала не замечена")
    hashes = json.load(open(e.st("owner-log-hashes.json")))
    check("athena.md" in hashes, "отпечатки журналов")


def test_revisits_repeat_and_edge():
    """Пересмотр: напоминание в срок, повтор через 3 дня, новое событие — сразу."""
    e = Env()
    day = time.strftime("%Y-%m-%d", time.localtime(T0 - 86400))
    open(os.path.join(e.pantheon, "revisits.toml"), "w").write(
        f'[[revisit]]\nid = "R-a"\ndue = "{day}"\nwhat = "проба"\n\n'
        '[[revisit]]\nid = "R-b"\nevent = "cc_updated"\nwhat = "версия"\n')
    e.run("revisits", t=T0)
    check(e.alerts().count("пора пересмотреть R-a") == 1, "R-a в срок")
    e.run("revisits", t=T0 + 86400)
    check(e.alerts().count("пора пересмотреть R-a") == 1, "R-a повторилось раньше 3 дней")
    e.run("revisits", t=T0 + 3 * 86400 + 10)
    check("снова: пора пересмотреть R-a" in e.alerts(), "R-a не повторилось через 3 дня")
    with open(e.st("events.jsonl"), "a") as fh:
        fh.write(json.dumps({"t": T0, "event": "cc_updated", "version": "2.1.300"}) + "\n")
    e.run("revisits", t=T0 + 3 * 86400 + 20)
    check(e.alerts().count("пересмотреть R-b") == 1, "R-b по событию")
    with open(e.st("events.jsonl"), "a") as fh:
        fh.write(json.dumps({"t": T0, "event": "cc_updated", "version": "2.1.301"}) + "\n")
    e.run("revisits", t=T0 + 3 * 86400 + 30)
    check(e.alerts().count("пересмотреть R-b") == 2, "новое событие не напомнило сразу")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
