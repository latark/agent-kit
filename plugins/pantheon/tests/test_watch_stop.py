#!/usr/bin/env python3
"""Дежурный, часть 3: стоп и возобновление, запуск по слову, паузы, лимит недели, ночной пакет (общая часть — _watch_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403


def test_stop_resume_all_precise():
    """resume --all снимает только метки, поставленные stop --all."""
    e = Env()
    e.direction("s1-dir")
    e.direction("s2-dir")
    e.agents([bg("s1-dir", "working", "s1s1s1s1-1", pid=31)])
    e.run("stop", "s2-dir", t=T0)
    e.run("stop", "--all", t=T0 + 10)
    check(os.path.exists(e.st("paused")) and os.path.exists(e.st("stopped", "s1-dir")), "stop --all")
    check(["stop", "s1s1s1s1"] in e.calls(), "stop --all не остановил сессию")
    out = e.run("resume", "--all", t=T0 + 20).stdout
    check(not os.path.exists(e.st("stopped", "s1-dir")) and os.path.exists(e.st("stopped", "s2-dir")),
          f"resume --all снял чужую метку: {out}")
    check(not os.path.exists(e.st("paused")), "пауза планировщика осталась")


def test_stop_removes_from_fleet():
    """metis-0239: после claude stop идёт claude rm <id>, иначе Claude Code сам перезапускает фоновую сессию;
    отказ rm (worktree с неотправленным) виден в выводе и в start.log, насильно не удаляем."""
    e = Env()
    e.direction("rm-dir")
    e.direction("rk-dir")
    e.agents([bg("rm-dir", "working", "r1r1r1r1-1", pid=61), bg("rk-dir", "working", "r2r2r2r2-1", pid=62)])
    r = e.run("stop", "rm-dir", t=T0)
    c = e.calls()
    check(["stop", "r1r1r1r1"] in c and ["rm", "r1r1r1r1"] in c and c.index(["stop", "r1r1r1r1"]) < c.index(["rm", "r1r1r1r1"]),
          f"stop не вызвал rm после stop: {c}")
    check("осталась среди фоновых сессий Claude Code" not in r.stdout, f"ложная «осталась среди фоновых сессий Claude Code»: {r.stdout}")
    r = e.run("stop", "rk-dir", t=T0 + 5, extra={"FAKE_RM_REFUSE": "r2r2r2r2"})
    check(["rm", "r2r2r2r2"] in e.calls() and not [x for x in e.calls() if "--discard-unpushed" in x or "--force-remove-worktree" in x],
          "rm вызван неверно или насильно")
    check("rk-dir: осталась среди фоновых сессий Claude Code: r2r2r2r2, причина:" in r.stdout and "unpushed" in r.stdout and r.returncode == 0,
          f"отказ rm не виден в выводе: {r.stdout!r}")
    log = open(e.st("logs", "start.log")).read()
    check("rm-refused\trk-dir\tr2r2r2r2" in log, f"отказ rm не в start.log: {log}")
    check("rk-dir: осталась среди фоновых сессий Claude Code (rm отказал)" in e.alerts() and "r2r2r2r2" in e.alerts(),
          f"отказ rm без тревоги: {e.alerts()}")
    # stop --all: отказ rm — в выводе, в start.log и в тревоге
    e2 = Env()
    e2.direction("ra-dir")
    e2.agents([bg("ra-dir", "working", "r3r3r3r3-1", pid=63)])
    r = e2.run("stop", "--all", t=T0, extra={"FAKE_RM_REFUSE": "r3r3r3r3"})
    check(["rm", "r3r3r3r3"] in e2.calls() and "ra-dir: осталась среди фоновых сессий Claude Code: r3r3r3r3, причина:" in r.stdout,
          f"stop --all: отказ rm не виден в выводе: {r.stdout!r}")
    check("стоп всё: осталась среди фоновых сессий Claude Code (rm отказал): ra-dir r3r3r3r3" in e2.alerts(),
          f"stop --all: отказ rm без тревоги: {e2.alerts()}")
    check("rm-refused\tra-dir\tr3r3r3r3" in open(e2.st("logs", "start.log")).read(), "stop --all: нет в start.log")
    # stop вернул не 0 — rm не зовём, сессия остаётся среди фоновых сессий Claude Code
    e3 = Env()
    e3.direction("rs-dir")
    e3.agents([bg("rs-dir", "working", "r4r4r4r4-1", pid=64)])
    r = e3.run("stop", "rs-dir", t=T0, extra={"FAKE_STOP_FAIL": "r4r4r4r4"})
    check(["stop", "r4r4r4r4"] in e3.calls() and ["rm", "r4r4r4r4"] not in e3.calls()
          and "rs-dir: осталась среди фоновых сессий Claude Code: r4r4r4r4" in r.stdout, f"stop с кодом 1: rm не должен вызываться: {e3.calls()} {r.stdout!r}")
    # ревью argus к #53 (metis-0250 п. 5): тревога называет того, кто отказал, — stop, а не rm
    check("rs-dir: осталась среди фоновых сессий Claude Code (stop отказал): r4r4r4r4 — claude stop: " in e3.alerts()
          and "rm отказал" not in e3.alerts(), f"stop с кодом 1 — тревога «rm отказал»: {e3.alerts()}")


def test_stop_without_locks_write():
    """metis-0078: окно без записи в папку замков имён (STATE/hq-rw/locks, metis-0523) — pantheon stop работает без
    блокировки имени, с предупреждением."""
    e = Env()
    e.direction("nl-dir")
    e.agents([bg("nl-dir", "working", "nlnlnlnl-1", pid=51)])
    locks = e.st("hq-rw", "locks")
    os.makedirs(locks, exist_ok=True)
    os.chmod(locks, 0o500)
    try:
        if os.access(locks, os.W_OK):  # root обходит права — проверять нечем
            return
        r = e.run("stop", "nl-dir", t=T0)
        check(r.returncode == 0 and os.path.exists(e.st("stopped", "nl-dir")),
              f"stop без записи в locks упал: {r.returncode} {r.stderr[-300:]}")
        check(["stop", "nlnlnlnl"] in e.calls(), "stop без записи в locks не остановил сессию")
        check("нет права записи" in r.stderr and "start-nl-dir" in r.stderr and "Traceback" not in r.stderr,
              f"нет понятного предупреждения: {r.stderr[-300:]}")
        # неблокирующий замок без файла — отказ с кодом 1 и предупреждением, а не молчаливое «взял» и не падение
        os.remove(e.st("stopped", "nl-dir"))
        r2 = e.run("start", "nl-dir", t=T0)
        check(r2.returncode == 1 and "Traceback" not in r2.stderr and "блокировка start-nl-dir не взята" in r2.stderr,
              f"start без записи в замки: {r2.returncode} {r2.stdout} {r2.stderr[-200:]}")
    finally:
        os.chmod(locks, 0o700)


def test_word_launch_0523():
    """metis-0523 (решение владельца 27.10 «(а)», ревью безопасности): ваш выбор «Да — запустить <имя>» на вопрос по шаблону
    pantheon launch-question — плановый проход сам поднимает окно, без СБ; строка word-launch в start.log и тревога на
    каждое поручение; один раз на запись. Вопрос не по шаблону (текст после имени), ответ не точный вариант,
    заметка, без пометки «окно вопросов», без [id], неизвестное имя, запись до включения прохода — без запуска."""
    e = Env()
    e.direction("wl-dir")
    e.direction("wl-two")
    os.makedirs(os.path.join(e.pantheon, "directions", "metis-pantheon", "tasks"), exist_ok=True)
    e.task("metis-0523", "metis-pantheon")  # id вопроса — задача: в тексте запуска ссылка на её карточку (metis-0820)
    _zeus_answer(e, T0 - 600, "[metis-0523] Запустить wl-dir?", "Да — запустить wl-dir")  # до включения прохода
    e.run("watch", t=T0)
    check(not _bgs(e), f"0523: запись до включения прохода подняла окно: {e.calls()}")
    _zeus_answer(e, T0 + 30, "[metis-0523] Запустить wl-dir?", "Да — запустить wl-dir")
    _zeus_answer(e, T0 + 31, "[metis-0524] Запустить wl-two?", "Нет")
    _zeus_answer(e, T0 + 32, "[metis-0525] Запустить wl-two?", "Да — запустить wl-two", mark="· свободный ввод")
    _zeus_answer(e, T0 + 33, "Запустить wl-two?", "Да — запустить wl-two")
    _zeus_answer(e, T0 + 34, "[metis-0526] Запустить nosuch-dir?", "Да — запустить nosuch-dir")
    _zeus_answer(e, T0 + 35, "[metis-0527] Давай без спешки: запустить wl-two?", "Да — запустить wl-two")
    _zeus_answer(e, T0 + 36, "[metis-0529] Запустить wl-two? Только не сейчас", "Да — запустить wl-two")
    _zeus_answer(e, T0 + 37, "[metis-0530] Запустить wl-two?", "Да")
    _zeus_answer(e, T0 + 38, "[metis-0531] Запустить wl-two?", "Да — запустить wl-two", note="но не сегодня")
    _zeus_answer(e, T0 + 39, "[metis-0532] Вернуть wl-two?", "Да — вернуть")
    _zeus_answer(e, T0 + 40, "[metis-0534] Запустить wl-two?", "Да — запустить wl-two, но не сейчас")
    e.run("watch", t=T0 + 60)
    check(len(_bgs(e, "wl-dir")) == 1, f"0523: «Да — запустить» не подняло wl-dir: {e.calls()}")
    check(not _bgs(e, "wl-two"), f"0523: wl-two поднят без точного выбора на вопрос по шаблону: {e.calls()}")
    wl = [r for r in _start_rows(e) if r[1:2] == ["word-launch"]]
    check([r[4] for r in wl] == ["metis-0523", "metis-0524", "metis-0526", "metis-0529", "metis-0530", "metis-0531",
                                 "metis-0532", "metis-0534"]
          and wl[0][2] == "wl-dir" and wl[0][-1] == "поднято" and "а не «Да — запустить wl-two»" in wl[1][-1]
          and "нет такого направления" in wl[2][-1] and "не по шаблону" in wl[3][-1] and "а не «Да" in wl[4][-1]
          and "заметка" in wl[5][-1] and "а не «Да — вернуть wl-two»" in wl[6][-1] and "а не «Да" in wl[7][-1],
          f"0523: строки журнала поручений: {wl}")
    al = e.alerts()
    check("по вашему ответу в окне вопросов" in al and "[metis-0523]): запустить wl-dir — поднято" in al,
          f"0523: нет тревоги о поручении: {al[-400:]}")
    task_text = [c for c in _bgs(e, "wl-dir")][0][-1]
    check("pantheon task show metis-0523" in task_text and "[Пантеон: поручение от tick]" in task_text,
          f"0523: поручение без id и origin: {task_text}")
    e.run("watch", t=T0 + 360)
    check(len(_bgs(e, "wl-dir")) == 1 and len([r for r in _start_rows(e) if r[1:2] == ["word-launch"]]) == 8,
          f"0523: запись исполнена повторно: {e.calls()}")
    # старше окна (12 ч) — не исполняется; испорченный word-launch.json проверку не роняет
    _zeus_answer(e, T0 + 400, "[metis-0528] Запустить wl-two?", "Да — запустить wl-two")
    with open(e.st("word-launch.json"), "w") as fh:
        fh.write("[]")
    e.run("watch", t=T0 + 400 + 13 * 3600)
    check(not _bgs(e, "wl-two"), f"0523: запись старше 12 ч исполнена: {e.calls()}")
    check("«окна по вашему ответу» упала" not in e.alerts(), "0523: испорченный word-launch.json уронил проверку")
    # шаблон печатает pantheon launch-question; чужой глагол, лишнее и неизвестное имя — код 2
    r = e.run("launch-question", "metis-0533", "запустить", "wl-two", t=T0)
    check(r.returncode == 0 and "вопрос: [metis-0533] Запустить wl-two?" in r.stdout
          and "Да — запустить wl-two | Нет" in r.stdout, f"0523: launch-question: {r.returncode} {r.stdout!r} {r.stderr!r}")
    r = e.run("launch-question", "metis-0533", "вернуть", "wl-two", t=T0)
    check(r.returncode == 0 and "вопрос: [metis-0533] Вернуть wl-two?" in r.stdout
          and "Да — вернуть wl-two | Нет" in r.stdout, f"28.10: launch-question вернуть: {r.returncode} {r.stdout!r}")
    bad = [e.run("launch-question", *a, t=T0).returncode for a in (("metis-0533", "поднять", "wl-two"),
                                                                   ("metis-0533", "запустить", "nosuch-dir"),
                                                                   ("metis-0533", "запустить", "wl-two", "сейчас"))]
    check(bad == [2, 2, 2], f"0523: launch-question без отказа: {bad}")


def test_word_launch_question_id_not_task_0820():
    """metis-0820: id вопроса без карточки задачи (05.11: [hermes-review-1], [zeus-wake-0511]). Текст запуска не ссылается
    на «pantheon task show <id>» и прямо говорит, что задачи с этим id нет: иначе он входил в цель окна (/goal) и проверка
    цели держала окно по кругу. Так и у «запустить», и у «перезапустить» (pantheon start --restart)."""
    e = Env()
    e.direction("nq-dir")
    e.direction("nq-two")
    e.run("watch", t=T0)
    _zeus_answer(e, T0 + 10, "[nq-review-1] Запустить nq-dir?", "Да — запустить nq-dir")
    e.agents([bg("nq-two", "working", "nqnqnqnq-1", pid=None)])
    _zeus_answer(e, T0 + 11, "[nq-wake-0511] Перезапустить nq-two?", "Да — перезапустить nq-two")
    e.run("watch", t=T0 + 60, extra={"FAKE_STOP_MARK": "1"})
    texts = {who: [c[-1] for c in _bgs(e, who)] for who in ("nq-dir", "nq-two")}
    check(len(texts["nq-dir"]) == 1 and len(texts["nq-two"]) == 1, f"0820: окна не подняты: {e.calls()}")
    for who, qid in (("nq-dir", "nq-review-1"), ("nq-two", "nq-wake-0511")):
        text = texts[who][0] if texts[who] else ""
        check("task show" not in text and f"[{qid}] — номер вопроса, а не задачи" in text
              and f"в цель окна задача {qid} не входит" in text, f"0820: {who}: текст запуска {text!r}")


def test_word_launch_return_restart_0523():
    """metis-0523 и решение владельца 28.10: «запустить» метку «остановлено вами» не снимает; «Да — вернуть <имя>» на
    «[<id>] Вернуть <имя>?» — снимает (метка, имя в stopped-all.json) и поднимает окно, не дословный ответ — отказ, метка
    остаётся; «перезапустить» — pantheon start --restart: живая копия останавливается, поднимается новая; живую
    «запустить» не трогает."""
    e = Env()
    e.direction("wr-dir")
    e.run("watch", t=T0)
    os.makedirs(e.st("stopped"), exist_ok=True)
    open(e.st("stopped", "wr-dir"), "w").write("x\n")
    open(e.st("stopped", "zz-other"), "w").write("x\n")
    json.dump({"names": ["wr-dir", "zz-other"]}, open(e.st("stopped-all.json"), "w"))
    _zeus_answer(e, T0 + 10, "[metis-0600] Запустить wr-dir?", "Да — запустить wr-dir")
    _zeus_answer(e, T0 + 11, "[metis-0603] Вернуть wr-dir?", "Да — вернуть wr-dir сейчас")
    _zeus_answer(e, T0 + 12, "[metis-0604] Вернуть wr-dir?", "Да — вернуть wr-dir", note="после обеда")
    e.run("watch", t=T0 + 60)
    check(not _bgs(e, "wr-dir") and os.path.exists(e.st("stopped", "wr-dir")),
          f"0523: «запустить» или не дословное «вернуть» подняло остановленное вами: {e.calls()}")
    check("снимает ответ «Да — вернуть wr-dir» или ваша команда pantheon resume" in e.alerts(),
          f"0523: нет причины отказа: {e.alerts()[-300:]}")
    _zeus_answer(e, T0 + 100, "[metis-0605] Вернуть wr-dir?", "Да — вернуть wr-dir")
    json.dump({"wr-dir": {"fails": 3, "gave_up": T0, "last": T0}}, open(e.st("autostart.json"), "w"))
    e.run("watch", t=T0 + 160)
    asj = json.load(open(e.st("autostart.json")))
    check(not (asj.get("wr-dir") or {}).get("gave_up") and not (asj.get("wr-dir") or {}).get("fails"),
          f"28.10: «вернуть» не сбросило счётчик самозапуска: {asj}")
    info = json.load(open(e.st("stopped-all.json")))
    check(not os.path.exists(e.st("stopped", "wr-dir")) and os.path.exists(e.st("stopped", "zz-other"))
          and info.get("names") == ["zz-other"] and len(_bgs(e, "wr-dir")) == 1,
          f"28.10: «Да — вернуть» не сняло метку или не подняло: {info} {e.calls()}")
    check("wr-dir: метка «остановлено вами» снята (ваш ответ «Да — вернуть wr-dir»" in e.alerts()
          and "[metis-0605]): вернуть wr-dir — поднято" in e.alerts(), f"28.10: тревоги возврата: {e.alerts()[-500:]}")
    e.agents([bg("wr-dir", "working", "wrwrwrwr-1", pid=None)])
    _zeus_answer(e, T0 + 200, "[metis-0601] Запустить wr-dir?", "Да — запустить wr-dir")
    e.run("watch", t=T0 + 260)
    check(len(_bgs(e, "wr-dir")) == 1 and "уже работает" in e.alerts(), f"0523: живую подняли второй раз: {e.calls()}")
    _zeus_answer(e, T0 + 300, "[metis-0602] Перезапустить wr-dir?", "Да — перезапустить wr-dir")
    e.run("watch", t=T0 + 360, extra={"FAKE_STOP_MARK": "1"})
    check(["stop", "wrwrwrwr"] in e.calls() and len(_bgs(e, "wr-dir")) == 2,
          f"0523: «перезапустить» не остановило и не подняло: {e.calls()}")
    wl = [r[-1] for r in _start_rows(e) if r[1:2] == ["word-launch"]]
    check(wl[-1] == "перезапущено", f"0523: итог перезапуска: {wl}")


def test_lock_symlink_refused_0523():
    """metis-0523, ревью безопасности: окно Зевса пишет только в STATE/hq-rw; замок имени там, подменённый ссылкой или
    жёсткой ссылкой, не берётся (O_NOFOLLOW, fstat: st_nlink == 1) — запись не уходит, start не поднимает; метка сброса
    самозапуска по ссылке не пишется; ждущий замок в hq-rw окно не держит дольше HQ_LOCK_WAIT."""
    import fcntl
    e = Env()
    e.direction("ln-dir")
    hl = e.st("hq-rw", "locks")
    os.makedirs(hl, exist_ok=True)
    victim = e.st("victim.txt")
    with open(victim, "w") as fh:
        fh.write("целый\n")
    os.symlink(victim, os.path.join(hl, "start-ln-dir.lock"))
    r = e.run("start", "ln-dir", t=T0)
    check(not _bgs(e, "ln-dir") and open(victim).read() == "целый\n",
          f"0523: замок по ссылке взят: {r.returncode} {e.calls()} {r.stderr[-200:]}")
    os.remove(os.path.join(hl, "start-ln-dir.lock"))
    os.link(victim, os.path.join(hl, "start-ln-dir.lock"))
    r = e.run("start", "ln-dir", t=T0)
    check(not _bgs(e, "ln-dir") and "блокировка start-ln-dir не взята" in r.stderr and open(victim).read() == "целый\n",
          f"0523: замок по жёсткой ссылке взят: {r.returncode} {e.calls()} {r.stderr[-200:]}")
    # замки прохода — не в hq-rw
    e.run("watch", t=T0)
    check(os.path.exists(e.st("locks", "watch.lock")) and not os.path.exists(os.path.join(hl, "watch.lock")),
          "0523: замок прохода не в STATE/locks")
    # метка сброса самозапуска: ссылка на её месте снимается, чужой файл цел; ждущий замок имени, занятый «окном», —
    # не дольше HQ_LOCK_WAIT
    ar = e.st("hq-rw", "autostart-reset")
    os.makedirs(ar, exist_ok=True)
    os.symlink(victim, os.path.join(ar, "ln-dir"))
    os.remove(os.path.join(hl, "start-ln-dir.lock"))
    with open(os.path.join(hl, "start-ln-dir.lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        r = e.run(LIB, t=T0, argv=[PY311, "-I", "-c", _HQ_RW_PROBE])
    check(open(victim).read() == "целый\n" and not os.path.islink(os.path.join(ar, "ln-dir"))
          and open(os.path.join(ar, "ln-dir")).read() == "метка\n", f"0523: метка сброса ушла по ссылке: {r.stderr[-300:]}")
    out = (r.stdout.strip().splitlines() or [""])[-1].split()
    check(out[:1] == ["False"] and len(out) == 2 and float(out[1]) < 5,
          f"0523: ждущий замок в hq-rw: {r.stdout!r} {r.stderr[-300:]}")


def test_hq_rw_bad_entries_0523():
    """Ревью безопасности (metis-0523): подложенная в STATE/hq-rw запись — FIFO, папка, ссылка на месте замка, файл на
    месте папки autostart-reset — замок не берётся с предупреждением, start выходит с кодом 1, плановый проход и
    resume не падают (ELOOP/ENXIO/EISDIR/ENOTDIR → UnsafeFile)."""
    e = Env()
    e.direction("bd-dir")
    hl = e.st("hq-rw", "locks")
    os.makedirs(hl, exist_ok=True)
    p = os.path.join(hl, "start-bd-dir.lock")
    for kind in ("fifo", "dir", "link"):
        if os.path.islink(p) or os.path.isfile(p) or (os.path.exists(p) and not os.path.isdir(p)):
            os.remove(p)
        elif os.path.isdir(p):
            os.rmdir(p)
        if kind == "fifo":
            os.mkfifo(p)
        elif kind == "dir":
            os.mkdir(p)
        else:
            os.symlink(e.st("nowhere"), p)
        r = e.run("start", "bd-dir", t=T0)
        check(r.returncode == 1 and "Traceback" not in r.stderr and "блокировка start-bd-dir не взята" in r.stderr
              and "блокировка имени не взята" in r.stderr.strip().splitlines()[-1] and not _bgs(e, "bd-dir"),
              f"0523: {kind} на месте замка: {r.returncode} {r.stderr[-300:]}")
    os.mkdir(os.path.join(hl, "wake.lock"))
    r = e.run("watch", t=T0)
    check(r.returncode == 0 and "Traceback" not in r.stderr + r.stdout and "упала" not in e.alerts(),
          f"0523: папка на месте wake.lock уронила проход: {r.returncode} {r.stderr[-300:]} {e.alerts()[-300:]}")
    open(e.st("hq-rw", "autostart-reset"), "w").write("x")
    r = e.run("resume", "bd-dir", t=T0)
    check("Traceback" not in r.stderr and "метка autostart-reset/bd-dir не записана" in r.stderr,
          f"0523: файл на месте autostart-reset уронил resume: {r.returncode} {r.stderr[-300:]}")


def test_stop_lock_busy_fail_closed_0523():
    """Ревью безопасности (metis-0523): замок имени в hq-rw занят дольше PANTHEON_HQ_LOCK_WAIT — pantheon stop не
    останавливает вслепую: код 1, причина последней строкой, сессии не тронуты, метка «остановлено вами» стоит (новые
    запуски не пойдут), тревога. Замок свободен — stop останавливает."""
    import fcntl
    e = Env()
    e.direction("sb-dir")
    e.agents([bg("sb-dir", "working", "sbsbsbsb-1", pid=52)])
    hl = e.st("hq-rw", "locks")
    os.makedirs(hl, exist_ok=True)
    with open(os.path.join(hl, "start-sb-dir.lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        r = e.run("stop", "sb-dir", t=T0, extra={"PANTHEON_HQ_LOCK_WAIT": "0.3"})
    check(r.returncode == 1 and ["stop", "sbsbsbsb"] not in e.calls() and os.path.exists(e.st("stopped", "sb-dir"))
          and "не остановлена" in r.stderr.strip().splitlines()[-1] and "sb-dir не остановлена" in e.alerts(),
          f"0523: stop при занятом замке: {r.returncode} {e.calls()} {r.stderr[-300:]}")
    r = e.run("stop", "sb-dir", t=T0 + 10)
    check(r.returncode == 0 and ["stop", "sbsbsbsb"] in e.calls(), f"0523: stop при свободном замке: {r.stderr[-300:]}")


def test_pauses():
    """Пауза по направлению: останавливает сессию; дежурный снимает только свою причину и продолжает сессию."""
    e = Env()
    e.direction("p1-dir")
    e.direction("p2-dir")
    e.agents([bg("p1-dir", "working", "p1p1p1p1-1", pid=41)])
    e.run("pause", "p1-dir", "--reason", "limit", "лимит 80", t=T0)
    e.run("pause", "p2-dir", "--reason", "manual", t=T0)
    e.run("pause", "--all", "--reason", "swap", t=T0)
    check(["stop", "p1p1p1p1"] in e.calls(), "пауза не остановила сессию")
    e.agents([bg("p1-dir", "stopped", "p1p1p1p1-1")])
    e.run("watch", t=T0 + 60, extra={"PANTHEON_FAKE_LIMIT": "90", "PANTHEON_FAKE_SWAP": "9"})
    check(len(os.listdir(e.st("pauses"))) == 3, "паузы сняты раньше времени")
    e.run("watch", t=T0 + 120, extra={"PANTHEON_FAKE_LIMIT": "20", "PANTHEON_FAKE_SWAP": "9"})
    left = sorted(os.listdir(e.st("pauses")))
    check(left == ["_all.json", "p1-dir.json", "p2-dir.json"], f"пауза p1 снята при общей swap-паузе: {left}")
    check(["respawn", "p1p1p1p1"] not in e.calls(), "сессия поднята при общей паузе")
    e.run("watch", t=T0 + 180, extra={"PANTHEON_FAKE_LIMIT": "20", "PANTHEON_FAKE_SWAP": "1"})
    check(sorted(os.listdir(e.st("pauses"))) == ["p2-dir.json"], "swap-пауза не снята или снята ручная")
    check(any("p1p1p1p1-1" in c for c in e.calls() if "--resume" in c), "сессия после паузы не продолжена")
    # старая общая метка (до 0.10.0) переводится в паузу по лимиту
    open(e.st("load-pause"), "w").write("2026-10-15 старая")
    e.run("watch", t=T0 + 240, extra={"PANTHEON_FAKE_LIMIT": "90"})
    check(os.path.exists(e.st("pauses", "_all.json")) and not os.path.exists(e.st("load-pause")), "миграция load-pause")


def test_week_limit_blocks_autostart():
    """Самозапуск по задаче зовёт gate недели (metis-0127): жёлтая днём, красная, снимок старше 30 мин — не поднимает,
    причина «недельный лимит»; зелёная — поднимает."""
    e = Env()
    e.direction("athena-w")
    e.task("athena-0009", "athena-w")
    e.run("watch", t=T0)
    e.board("athena-0009", T0 + 60)
    cases = ((31.6, 0, "жёлтая зона днём"), (90.0, 0, "красная зона"), (10.0, 31 * 60, "лимит неизвестен (31 мин)"))
    for i, (pct, age, why) in enumerate(cases):
        e.week_pct, e.snap_age = pct, age
        out = e.run("watch", "--dry-run", t=T0 + 120 + i).stdout
        check(f"athena-w: ждёт — недельный лимит: {why}" in out, f"неделя {pct} %, снимок {age} с — dry-run: {out[-500:]}")
        r = e.run("watch", t=T0 + 130 + i)
        check(not [c for c in e.calls() if c[:1] == ["--bg"]], f"неделя {pct} %, снимок {age} с — самозапуск: "
              f"{e.calls()} {r.stderr[-300:]}")
    check("самозапуск athena-w ждёт" not in e.alerts(), "тревога autostart-wait по недельному лимиту")
    e.week_pct, e.snap_age = 10.0, 0
    e.run("watch", t=T0 + 200)
    check(len([c for c in e.calls() if c[:1] == ["--bg"]]) == 1, f"зелёная — самозапуск не пошёл: {e.calls()}")


def test_week_limit_blocks_wake_after_pause():
    """Сессия, уснувшая по пятичасовому лимиту: лимит ушёл, но неделя красная или ночь закрыта — не будится, пауза
    остаётся; неделя снова зелёная днём — продолжена."""
    for night in (False, True):
        e = Env()
        if night:  # ночь идёт и закрыта (пропущена): вопроса больше нет, состояние ночи — готовое
            _night_now(e)
            os.makedirs(e.st("night"), exist_ok=True)
            json.dump({"answer": "да", "skipped": "проба: ночь закрыта"},
                      open(e.st("night", time.strftime("%Y-%m-%d", time.localtime(T0 - 7200)) + ".json"), "w"))
        e.direction("p9-dir")
        e.agents([bg("p9-dir", "working", "p9p9p9p9-1", pid=43)])
        e.run("pause", "p9-dir", "--reason", "limit", "лимит 80", t=T0)
        e.agents([bg("p9-dir", "stopped", "p9p9p9p9-1")])
        if not night:
            e.week_pct = 90.0
        e.run("watch", t=T0 + 60, extra={"PANTHEON_FAKE_LIMIT": "20"})
        what = "ночь закрыта" if night else "неделя красная"
        check(os.path.exists(e.st("pauses", "p9-dir.json")), f"{what} — пауза снята")
        check(not any("p9p9p9p9-1" in c for c in e.calls() if "--resume" in c), f"{what} — сессия продолжена: {e.calls()}")
        if night:
            st = json.load(open(e.st("night", time.strftime("%Y-%m-%d", time.localtime(T0 - 7200)) + ".json")))
            check(st.get("skipped") and not st.get("opened_at"), f"пропущенная ночь открылась: {st}")
        else:
            e.week_pct = 10.0
            e.run("watch", t=T0 + 120, extra={"PANTHEON_FAKE_LIMIT": "20"})
            check(not os.path.exists(e.st("pauses", "p9-dir.json")), "зелёная — пауза не снята")
            check(any("p9p9p9p9-1" in c for c in e.calls() if "--resume" in c), "зелёная — сессия не продолжена")


def test_night_only_by_answer_0523():
    """Решение владельца 28.10 (вариант Б): вечером плановый проход вопроса не задаёт — ни карточки во входящих, ни
    уведомления; без вашего ответа о пачке ночь не открыта: ночью ни пачку, ни задачу с отметкой не поднимают. Ответ
    на напечатанный `pantheon night ask` вопрос, но с пачкой, изменённой после него, — отказ и тревога."""
    e = Env()
    _pack_night(e)
    e.direction("athena-q")
    e.task("athena-0301", "athena-q")
    e.agents([])
    r = e.run("watch", t=T0 - 7200)
    st = json.load(open(e.night_file)) if os.path.exists(e.night_file) else {}
    box = os.path.join(e.pantheon, "inbox", "tasks")
    cards = os.listdir(box) if os.path.isdir(box) else []
    check(st.get("answer") is None and not st.get("packs") and not st.get("card_id") and not cards,
          f"вечер: {st} {cards} {r.stderr[-300:]}")
    check("на ночь" not in e.sent(), f"уведомление о ночи: {e.sent()[-300:]}")
    e.board("athena-0301", T0 - 3650)
    e.run("watch", t=T0 - 3500)
    e.run("watch", t=T0 - 3400)
    st = json.load(open(e.night_file)) if os.path.exists(e.night_file) else {}
    check(not _bgs(e) and not st.get("opened_at"), f"ночь без ответа — кого-то подняли: {e.calls()} {st}")
    # pantheon night ask печатает вопрос; ответ на него, а пачку потом изменили — не одобрена
    r = e.run("night", "ask", "metis-0710", "athena-p", e.evening, t=T0 - 3300)
    q = r.stdout.splitlines()[0][len("вопрос: "):] if r.stdout else ""
    check(r.returncode == 0 and q.startswith(f"[metis-0710] Ночь {e.evening}: пачка {e.pack_rel} sha256 "),
          f"night ask: {r.returncode} {r.stdout!r} {r.stderr[-300:]}")
    _zeus_answer(e, T0 - 3290, q, f"Да — ночь {e.evening}")
    open(e.pack, "a", encoding="utf-8").write("| 2 | athena-0399 | дописано после вопроса |\n")
    e.run("watch", t=T0 - 3200)
    st = json.load(open(e.night_file))
    check(not _bgs(e) and not st.get("packs") and "изменилась после вашего ответа" in e.alerts(),
          f"изменённую после вопроса пачку одобрили: {st} {e.calls()} {e.alerts()[-300:]}")
    check(e.run("night", "ask", "metis-0710", "nosuch-dir", t=T0).returncode == 2, "night ask без пачки — не код 2")


def test_night_pack_starts_once_0284():
    """Пачка с вашим ответом «Да — ночь» одобрена: в начале ночи плановый проход поднимает её координатора с путём
    пачки в задании — один раз; отметки владельца у других направлений ночью с пачкой никого не поднимают."""
    e = Env()
    _pack_night(e)
    e.direction("athena-q")
    e.task("athena-0301", "athena-q")
    _night_yes(e, T0 - 7300)
    e.run("watch", t=T0 - 7200)                       # вечер: пачка одобрена вашим ответом, разовый запуск записан
    st = json.load(open(e.night_file))
    check([x["path"] for x in st.get("packs") or []] == [e.pack_rel], f"пачка не зафиксирована: {st}")
    e.run("watch", t=T0 - 7000)
    e.run("watch", t=T0 - 3700)                       # до начала ночи
    check(not _bgs(e), f"пачку подняли до ночи: {e.calls()}")
    e.board("athena-0301", T0 - 3650)                 # владелец отметил задачу другого направления
    r = e.run("watch", t=T0 - 3500)
    got = _bgs(e, "athena-p")
    check(len(got) == 1 and any(e.pack_rel in x or os.path.basename(e.pack) in x for x in got[0]),
          f"пачку не подняли с её путём: {e.calls()} {r.stderr[-300:]}")
    e.run("watch", t=T0 - 3400)
    e.run("watch", t=T0 - 3000)
    check(len(_bgs(e, "athena-p")) == 1, f"пачку подняли повторно: {_bgs(e)}")
    check(not _bgs(e, "athena-q"), f"ночью с пачкой подняли по отметке: {_bgs(e)}")
    out = e.run("watch", "--dry-run", t=T0 - 2900).stdout
    check("ночью идут только одобренные пачки" in out, f"dry-run не объясняет ожидание: {out[-400:]}")
    check("разовый запуск pack-" in e.alerts() and "athena-p — запущен" in e.alerts(), f"тревоги: {e.alerts()[-400:]}")


def test_night_pack_changed_not_started_0284():
    """Пачка, изменённая после одобрения вечером, не запускается: запись гаснет, тревога и уведомление."""
    e = Env()
    _pack_night(e)
    _night_yes(e, T0 - 7300)
    e.run("watch", t=T0 - 7200)
    e.run("watch", t=T0 - 7000)
    open(e.pack, "a", encoding="utf-8").write("| 2 | athena-0399 | дописано после фиксации |\n")
    e.run("watch", t=T0 - 3500)
    e.run("watch", t=T0 - 3400)
    check(not _bgs(e), f"изменённую пачку подняли: {e.calls()}")
    check("изменилась после фиксации" in e.alerts(), f"нет тревоги об изменённой пачке: {e.alerts()[-400:]}")
    check("не состоялся" in e.sent() or os.path.exists(e.st("notify.json")), "нет уведомления об изменённой пачке")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
