#!/usr/bin/env python3
"""Синтетические тесты дежурного и управления сессиями (lib/watch.py, шаг 1.4).

Запуск: python3 -I plugins/pantheon/tests/test_watch.py  (код выхода 0 — все прошли)
Проверяет строки карты решений SCHED-09, SCHED-10, SCHED-12, SCHED-15, COMM-04, COMM-10, COMM-14, STATE-14, QA-05,
COST-04, TOOL-04 на временных папках. Claude Code подменён скриптом `claude` в PATH: `agents --json --all` отдаёт
список из файла, остальные вызовы пишутся в журнал (запуски не настоящие).
Файл разрезан на части для параллельного прогона (общее — tests/_watch_common.py): здесь самозапуск; остальное — test_watch_zeus.py, _stop, _oneshot, _sandbox, _infra, _nudge, _respawn, _ghost.
"""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403


def test_harness_quick_waits_0359():
    """metis-0359: Env по умолчанию — с короткими ожиданиями (QUICK); иначе файл не укладывается в 600 с тика."""
    e = Env()
    check(all(e.extra.get(k) == v for k, v in QUICK.items()), f"0359: Env без QUICK по умолчанию: {e.extra}")
    # самозапуск: до правки проход ждал имени новой сессии 10 с (заглушка её не показывает) — не меньше 10 с
    e.direction("athena-q")
    e.task("athena-0009", "athena-q")
    e.run("watch", t=T0)
    e.board("athena-0009", T0 + 120)
    t = time.monotonic()
    e.run("watch", t=T0 + 240)
    took = time.monotonic() - t
    starts = [c for c in e.calls() if c[:1] == ["--bg"]]
    check(len(starts) == 1 and took < 8, f"0359: самозапуск {took:.1f} с (ждёт имени по умолчанию?): {starts}")


def test_autostart_only_new_sanctions():
    """Старые решения владельца (до включения дежурного) никого не будят; новое — будит, одна сессия, без доверия —
    тревога вместо запуска."""
    e = Env()
    e.direction("athena-x")
    e.task("athena-0001", "athena-x")
    e.board("athena-0001", T0 - 7 * 86400)                     # неделю назад, до включения
    e.run("watch", t=T0)
    check(not any(c[:1] == ["--bg"] or "start" in c for c in e.calls() if c[:1] != ["agents"] and c[:1] != ["--version"]),
          "самозапуск по старой карточке")
    check(os.path.exists(e.st("autostart-since")), "autostart-since записан")
    out = e.run("watch", "--dry-run", t=T0 + 60).stdout
    check("задачи с ними: нет" in out, f"dry-run видит старую карточку: {out}")
    e.board("athena-0001", T0 + 120)                            # новый ход владельца
    out = e.run("watch", "--dry-run", t=T0 + 180).stdout
    check("athena-x: поднял бы сейчас" in out, f"dry-run не видит новую карточку: {out}")
    check("athena-x" not in json.load(open(e.st("autostart.json"))), "dry-run ничего не пишет")
    r = e.run("watch", t=T0 + 240)
    starts = [c for c in e.calls() if c[:1] == ["--bg"]]
    check(len(starts) == 1 and "athena-x" in starts[0], f"самозапуск не пошёл: {e.calls()} {r.stderr}")
    check("самозапуск: athena-x" in e.alerts(), "строка самозапуска в тревогах")
    aw = json.load(open(e.st("awake.json")))
    check(aw.get("reason") == "поднята athena-x" and aw.get("pid"),
          f"после самозапуска сон Mac не запрещён в том же проходе: {aw}")
    # без доверия — тревога и уведомление, запуска нет
    e2 = Env()
    e2.direction("athena-y", trusted=False)
    e2.task("athena-0002", "athena-y")
    e2.run("watch", t=T0)
    e2.board("athena-0002", T0 + 60)
    e2.run("watch", t=T0 + 120)
    check(not [c for c in e2.calls() if c[:1] == ["--bg"]], "запуск без доверия")
    check("нет доверия" in e2.alerts(), "тревога о доверии")


def test_autostart_batch_in_owner_order_0242():
    """Пачка из 7 отметок владельца уходит в задание целиком и в порядке отметок, а не по алфавиту и не первыми пятью."""
    e = Env()
    e.direction("athena-x")
    order = [7, 3, 5, 1, 6, 2, 4]
    for n in range(1, 8):
        e.task(f"athena-000{n}", "athena-x")
    e.run("watch", t=T0)
    for i, n in enumerate(order):
        e.board(f"athena-000{n}", T0 + 100 + i * 10)
    e.board("athena-0003", T0 + 400)  # повторная отметка порядок не меняет
    e.run("watch", t=T0 + 500)
    starts = [c for c in e.calls() if c[:1] == ["--bg"]]
    check(len(starts) == 1, f"самозапуск не пошёл: {e.calls()}")
    text = " ".join(starts[0])
    want = ", ".join(f"athena-000{n}" for n in order)
    check(want in text, f"в задании нет всей пачки в порядке отметок ({want}): {text[-500:]}")


def test_autostart_order_board_vs_zeus_0242():
    """Отметки из board.jsonl и ответ окном вопросов (zeus.md) идут одним списком по времени, а не «сначала board»."""
    e = Env()
    e.direction("athena-x")
    for n in (1, 2, 3):
        e.task(f"athena-000{n}", "athena-x")
    e.run("watch", t=T0)
    e.board("athena-0002", T0 + 100)
    with open(e.st("owner-log", "zeus.md"), "w") as fh:
        fh.write(f"## {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(T0 + 50))} · окно вопросов\n"
                 "вопрос: [athena-0001] что-то\n\n")
    e.board("athena-0003", T0 + 150)
    e.run("watch", t=T0 + 500)
    starts = [c for c in e.calls() if c[:1] == ["--bg"]]
    check(len(starts) == 1, f"самозапуск не пошёл: {e.calls()}")
    want = "athena-0001, athena-0002, athena-0003"
    check(want in " ".join(starts[0]), f"порядок board/zeus.md нарушен ({want}): {' '.join(starts[0])[-400:]}")


def test_autostart_owner_elsewhere_0564():
    """metis-0564: задачу с owner не координатора направления (другая сессия, Зевс, вы, другое направление) самозапуск
    его сессии не отдаёт и места в очереди ею не занимает; owner — само направление или его лид/исполнитель — отдаёт."""
    e = Env()
    e.direction("metis-x")
    e.task("metis-0001", "metis-x", extra="owner: agent-kit-62\n")
    e.task("metis-0002", "metis-x", extra="owner: zeus\n")
    e.task("metis-0003", "metis-x", extra="owner: вы\n")
    e.run("watch", t=T0)
    for i, n in enumerate((1, 2, 3)):
        e.board(f"metis-000{n}", T0 + 100 + i * 10)
    out = e.run("watch", "--dry-run", t=T0 + 200).stdout
    check("не отдаю координатору" in out and "metis-0001 (agent-kit-62)" in out and "задачи с ними: нет" in out,
          f"0564: dry-run не говорит, что задачи чужие: {out}")
    e.run("watch", t=T0 + 240)
    check(not [c for c in e.calls() if c[:1] == ["--bg"]], f"0564: координатор поднят по чужой задаче: {e.calls()}")
    e.task("metis-0004", "metis-x", extra="owner: metis-x\n")
    e.task("metis-0005", "metis-x", extra="owner: hephaestus-board\n")
    e.task("metis-0006", "metis-x")  # без owner — координатор направления
    for i, n in enumerate((4, 5, 6)):
        e.board(f"metis-000{n}", T0 + 300 + i * 10)
    e.run("watch", t=T0 + 400)
    starts, text = _bg_text(e)
    check(len(starts) == 1 and "metis-0004, metis-0005, metis-0006" in text
          and not any(f"metis-000{n}" in text for n in (1, 2, 3)),
          f"0564: в задании координатору не те задачи: {text[-400:]}")


def test_autostart_goal_released_on_handover_0631():
    """metis-0631: окно поднято самозапуском с /goal по задачам mg-0001, mg-0002; mg-0001 передали другой сессии (owner
    сменился) — за один проход цель снимается: прежняя сессия остановлена, новая того же имени с /goal по оставшейся
    mg-0002 и следующей из очереди mg-0003, без mg-0001; тревога. Пока задачи окна на нём — «уже работает», ничего не
    трогаем. Сделанная (done) и «ждёт» (waiting) цель не снимают. Ушли все и очереди нет — сессия остановлена и убрана
    из списка (claude stop + rm). Сессию, которая ждёт вас (blocked), не трогаем — тревога."""
    e = Env()
    e.direction("mg-dir")
    e.task("mg-0001", "mg-dir")
    e.task("mg-0002", "mg-dir")
    e.run("watch", t=T0)
    e.board("mg-0001", T0 + 10)
    e.board("mg-0002", T0 + 20)
    e.run("watch", t=T0 + 60)
    starts, text = _bg_text(e)
    check(len(starts) == 1 and "Все: mg-0001, mg-0002." in text, f"0631: самозапуск не тот: {starts}")
    goal = starts[0][-1]
    check(goal.startswith("/goal "), f"0631: самозапуск без /goal: {goal[:80]}")
    a = bg("mg-dir", "working", "a6a10631-1", pid=51, started=T0 + 61)
    a["status"] = "busy"
    a["cwd"] = os.path.join(e.home, "projects", "mg-dir")
    e.agents([a])
    goal_transcript(e, a, goal[len("/goal "):])
    # задачи окна на нём, одна сделана, другая ждёт — цель не трогаем
    e.task("mg-0001", "mg-dir", status="done")
    e.task("mg-0002", "mg-dir", status="waiting", extra="waiting_on: human\nnext: ответ\n")
    out = e.run("watch", "--dry-run", t=T0 + 400).stdout
    check("цель окна" not in out, f"0631: цель снята без передачи: {out}")
    e.run("watch", t=T0 + 400)
    check(len(_bgs(e)) == 1 and not [c for c in e.calls() if c[:1] == ["stop"]],
          f"0631: сессию тронули без передачи задачи: {e.calls()}")
    # передача: owner mg-0001 — другая сессия; mg-0002 снова в работе у окна; в очереди появилась mg-0003
    e.task("mg-0001", "mg-dir", status="doing", extra="owner: agent-kit-47\n")
    e.task("mg-0002", "mg-dir", status="doing")
    e.task("mg-0003", "mg-dir")
    e.board("mg-0003", T0 + 500)
    out = e.run("watch", "--dry-run", t=T0 + 600).stdout
    check("mg-dir: цель окна на задачах, которые ушли: mg-0001 (ведёт agent-kit-47) — перезапустил бы с новой целью"
          in out, f"0631: dry-run не говорит о снятии цели: {out}")
    e.run("watch", t=T0 + 700, extra={"FAKE_STOP_MARK": "1"})
    check(["stop", "a6a10631"] in e.calls(), f"0631: сессия на чужой задаче не остановлена: {e.calls()}")
    starts = _bgs(e)
    new = starts[-1][-1] if len(starts) == 2 else ""
    check(new.startswith("/goal [Пантеон: смена цели]") and "Все: mg-0002, mg-0003." in new
          and "Другие задачи и пункты эпика в эту цель не входят" in new and "a6a10631" in new,
          f"0631: новая цель не та: {starts[-1:]}")
    check("Все: mg-0001" not in new and "mg-0001, mg-0002" not in new, f"0631: переданная задача осталась в цели: {new}")
    check("самозапуск mg-dir: цель окна снята — mg-0001 (ведёт agent-kit-47); окно перезапущено с новой целью"
          in e.alerts(), f"0631: нет тревоги о смене цели: {e.alerts()[-400:]}")
    rows = [r for r in _start_rows(e) if r[1:2] == ["fresh-start"]]
    check(rows and rows[-1][2] == "mg-dir" and "ушли mg-0001" in rows[-1][-1], f"0631: нет строки fresh-start: {rows}")
    # новая сессия с новой целью — следующий проход её не трогает
    b = bg("mg-dir", "working", "b6b10631-2", pid=52, started=T0 + 701)
    b["status"] = "busy"
    b["cwd"] = a["cwd"]
    e.agents([b])
    goal_transcript(e, b, new[len("/goal "):])
    e.run("watch", t=T0 + 1000)
    check(len(_bgs(e)) == 2 and ["stop", "b6b10631"] not in e.calls(), f"0631: новую цель сняли снова: {e.calls()}")
    # ушли все задачи цели, очереди нет — остановить и убрать из списка
    for n in (2, 3):
        e.task(f"mg-000{n}", "mg-dir", status="dropped" if n == 2 else "doing", extra="" if n == 2 else "owner: zeus\n")
    e.run("watch", t=T0 + 1300, extra={"FAKE_STOP_MARK": "1"})
    check(["stop", "b6b10631"] in e.calls() and ["rm", "b6b10631"] in e.calls() and len(_bgs(e)) == 2,
          f"0631: без очереди сессия не остановлена или поднята новая: {e.calls()[-4:]}")
    check("цель окна снята — mg-0002 (отменена), mg-0003 (ведёт zeus); новой задачи сейчас нет (очереди нет)"
          in e.alerts(), f"0631: нет тревоги об остановке: {e.alerts()[-400:]}")
    # ждёт вас (blocked) — не трогаем, тревога
    e2 = Env()
    e2.direction("mh-dir")
    e2.task("mh-0001", "mh-dir", extra="owner: agent-kit-9\n")
    c = bg("mh-dir", "blocked", "c6c10631-3", pid=53)
    c["cwd"] = os.path.join(e2.home, "projects", "mh-dir")
    e2.agents([c])
    goal_transcript(e2, c, "[Пантеон: поручение от tick] Самозапуск дежурным по задачам: следующая: mh-0001. "
                    "Все: mh-0001. Прочитай STATUS.md")
    e2.run("watch", t=T0)
    check(not [x for x in e2.calls() if x[:1] in (["stop"], ["--bg"])], f"0631: blocked тронули: {e2.calls()}")
    check("сессия ждёт вас, сниму после ответа" in e2.alerts(), f"0631: нет тревоги blocked: {e2.alerts()[-300:]}")
    # цель достигнута (met) — снимать нечего
    goal_transcript(e2, c, "[Пантеон: поручение от tick] Самозапуск дежурным: Все: mh-0001.", met=True)
    c["state"] = "working"
    e2.agents([c])
    e2.run("watch", t=T0 + 300)
    check(not [x for x in e2.calls() if x[:1] in (["stop"], ["--bg"])], f"0631: снята достигнутая цель: {e2.calls()}")
    # задачу перенесли в другое направление, а подъём закрыт (планировщик на паузе) — остановить без новой сессии
    e2.direction("ot-dir")
    e2.task("mh-0002", "ot-dir")
    e2.task("mh-0003", "mh-dir")
    e2.board("mh-0003", T0 + 310)
    goal_transcript(e2, c, "[Пантеон: поручение от tick] Самозапуск дежурным: следующая: mh-0002. Все: mh-0002.")
    open(e2.st("paused"), "w").write("x\n")
    e2.run("watch", t=T0 + 400, extra={"FAKE_STOP_MARK": "1"})
    check(["stop", "c6c10631"] in e2.calls() and ["rm", "c6c10631"] in e2.calls()
          and not [x for x in e2.calls() if x[:1] == ["--bg"]], f"0631: на паузе не остановлена: {e2.calls()}")
    check("mh-0002 (перенесена в ot-dir); новой задачи сейчас нет (весь планировщик на паузе)" in e2.alerts(),
          f"0631: нет тревоги о переносе: {e2.alerts()[-400:]}")
    # ревью argus Б2: ушедшая задача, а своя ещё в doing, подъём закрыт (пауза) — сессию не гасить, тревога «снимем»
    e3 = Env()
    e3.direction("mk-dir")
    e3.task("mk-0001", "mk-dir", status="doing", extra="owner: agent-kit-5\n")
    e3.task("mk-0002", "mk-dir", status="doing")
    e3.board("mk-0001", T0 + 10)
    e3.board("mk-0002", T0 + 20)
    k = bg("mk-dir", "working", "d6d10631-4", pid=54, started=T0 + 30)
    k["status"] = "busy"
    k["cwd"] = os.path.join(e3.home, "projects", "mk-dir")
    e3.agents([k])
    goal_transcript(e3, k, "[Пантеон: поручение от tick] Самозапуск дежурным по задачам: следующая: mk-0001. "
                    "Все: mk-0001, mk-0002. Прочитай STATUS.md")
    open(e3.st("paused"), "w").write("x\n")
    out = e3.run("watch", "--dry-run", t=T0 + 100).stdout
    check("сессия ведёт свои mk-0002, сниму, когда подъём откроется: весь планировщик на паузе" in out,
          f"0631 Б2: dry-run не тот: {out}")
    e3.run("watch", t=T0 + 100, extra={"FAKE_STOP_MARK": "1"})
    check(not [x for x in e3.calls() if x[:1] in (["stop"], ["rm"], ["--bg"])],
          f"0631 Б2: сессию со своей задачей в doing остановили на паузе: {e3.calls()}")
    check("цель окна на задачах, которые ушли: mk-0001 (ведёт agent-kit-5); сессия ведёт свои mk-0002 — снимем, когда "
          "подъём откроется (весь планировщик на паузе)" in e3.alerts(), f"0631 Б2: нет тревоги: {e3.alerts()[-400:]}")
    # ревью argus Б1: между снимком и блокировкой владелец поднял окно вручную — под блокировкой отказ, stop не зовётся
    os.remove(e3.st("paused"))
    manual = bg("mk-dir", "working", "e6e10631-5", pid=55, started=T0 + 150)
    manual["status"] = "busy"
    nxt = os.path.join(e3.tmp, "agents-next.json")
    open(nxt, "w").write(json.dumps([k, manual]))
    e3.run("watch", t=T0 + 200, extra={"FAKE_STOP_MARK": "1", "FAKE_AGENTS_NEXT": nxt})
    check(not [x for x in e3.calls() if x[:1] in (["stop"], ["rm"], ["--bg"])],
          f"0631 Б1: ручную сессию или старую тронули после повторной проверки: {e3.calls()}")
    check("цель окна на задачах, которые ушли: mk-0001 (ведёт agent-kit-5) — смена отложена: уже работает" in e3.alerts(),
          f"0631 Б1: нет тревоги об отложенной смене: {e3.alerts()[-400:]}")


def test_autostart_push_order_priority_pack_reserve_0292():
    """metis-0292: в толчке сначала высший priority, затем порядок пачки (order), запас — последним, хоть он и важнее;
    первая названа «следующая: <id>»; тревога и текст — в том же порядке."""
    e = Env()
    e.direction("athena-x")
    e.task("athena-0001", "athena-x", priority=3, extra="order: 2\n")
    e.task("athena-0002", "athena-x", priority=3, extra="order: 1\n")
    e.task("athena-0003", "athena-x", priority=0, extra="order: 1000001\n")  # запас, важный, но последний
    e.task("athena-0004", "athena-x", priority=1)
    e.task("athena-0005", "athena-x", priority=2)
    e.task("athena-0006", "athena-x", priority=0)
    e.task("athena-0007", "athena-x", priority=3, extra="order: 3\n")
    e.run("watch", t=T0)
    for i, n in enumerate((1, 2, 3, 4, 5, 6, 7)):  # отметки идут по id: прежний порядок
        e.board(f"athena-000{n}", T0 + 100 + i * 10)
    e.run("watch", t=T0 + 500)
    starts, text = _bg_text(e)
    check(len(starts) == 1, f"0292: самозапуск не пошёл: {e.calls()}")
    want = "athena-0006, athena-0004, athena-0005, athena-0002, athena-0001, athena-0007, athena-0003"
    check("следующая: athena-0006." in text, f"0292: нет «следующая: athena-0006»: {text[-500:]}")
    check(want in text, f"0292: порядок толчка ({want}): {text[-500:]}")
    check("athena-0006, athena-0004, athena-0005, athena-0002, athena-0001" in e.alerts(),
          f"0292: тревога в другом порядке: {e.alerts()[-400:]}")


def test_autostart_deps_order_0248():
    """metis-0248: A зависит от B, отметки A, B → в задании B, A (зависимости раньше отметок); цепочка — одна сессия."""
    e = Env()
    e.direction("athena-x")
    e.task("athena-0001", "athena-x", extra="depends_on: [athena-0002]\n")
    e.task("athena-0002", "athena-x")
    e.run("watch", t=T0)
    e.board("athena-0001", T0 + 100)
    e.board("athena-0002", T0 + 110)
    e.run("watch", t=T0 + 500)
    starts, text = _bg_text(e)
    check(len(starts) == 1 and "athena-0002, athena-0001" in text, f"0248: порядок B, A: {text[-400:]}")


def test_autostart_stuck_pred_alert_0248():
    """Предшественник waiting → «ждёт зависший», тревога, запуска нет; без изменений > 24 ч (вне пачки) — то же."""
    for kw, name in (({"status": "waiting", "extra": "waiting_on: human\n"}, "waiting"), ({"status": "doing", "updated": time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(T0 - 30 * 3600))}, "старше 24 ч")):
        e = Env()
        e.direction("athena-x")
        e.task("athena-0001", "athena-x", extra="depends_on: [athena-0002]\n")
        e.task("athena-0002", "athena-x", **kw)
        check(os.path.exists(os.path.join(e.pantheon, "directions", "athena-x", "tasks", "athena-0002.md")), "задача записана")
        e.run("watch", t=T0)
        e.board("athena-0001", T0 + 100)
        e.run("watch", t=T0 + 500)
        check(not _bg_text(e)[0], f"0248: запуск при зависшем ({name})")
        check("ждёт зависший athena-0002" in e.alerts(), f"0248: нет тревоги ({name}): {e.alerts()[-300:]}")
    # свежий doing — просто ждёт, тревоги нет
    e = Env()
    e.direction("athena-x")
    e.task("athena-0001", "athena-x", extra="depends_on: [athena-0002]\n")
    e.task("athena-0002", "athena-x", status="doing", updated=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T0 - 3600)))
    e.run("watch", t=T0)
    e.board("athena-0001", T0 + 100)
    e.run("watch", t=T0 + 500)
    check(not _bg_text(e)[0] and "зависший" not in e.alerts() and "athena-0001 — ждёт athena-0002" in e.alerts(),
          f"0248: свежий предшественник — ожидание с тревогой «ждёт id», не зависший: {e.alerts()[-300:]}")


def test_autostart_cycle_alert_0248():
    """Цикл depends_on → тревога, без запуска."""
    e = Env()
    e.direction("athena-x")
    e.task("athena-0001", "athena-x", extra="depends_on: [athena-0002]\n")
    e.task("athena-0002", "athena-x", extra="depends_on: [athena-0001]\n")
    e.run("watch", t=T0)
    e.board("athena-0001", T0 + 100)
    e.board("athena-0002", T0 + 110)
    e.run("watch", t=T0 + 500)
    check(not _bg_text(e)[0], "0248: запуск при цикле")
    check("в цикле зависимостей" in e.alerts(), f"0248: нет тревоги о цикле: {e.alerts()[-300:]}")


def test_autostart_shared_touches_other_direction_0248():
    """Общие файлы с идущей у другого направления задачей → вторая не стартует (пустой touches не блокирует); соседние
    папки — стартует."""
    for mine, theirs, goes in ((["plugins/pantheon/lib/watch.py"], ["plugins/pantheon/"], False),
                               ([], [], True), (["plugins/pantheon/"], ["plugins/guard/"], True)):
        e = Env()
        e.direction("athena-x")
        e.direction("hermes-y")
        fm = lambda v: ("touches: [" + ", ".join(v) + "]\n") if v else ""  # noqa: E731
        e.task("athena-0001", "athena-x", extra=fm(mine))
        e.task("hermes-0001", "hermes-y", status="doing", extra=fm(theirs),
               updated=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T0 - 600)))
        e.agents([bg("hermes-y", "working", "11111111-aaaa", pid=os.getpid())])
        e.run("watch", t=T0)
        e.board("athena-0001", T0 + 100)
        e.run("watch", t=T0 + 500)
        starts = [c for c in e.calls() if c[:1] == ["--bg"] and "athena-x" in " ".join(c)]
        check(bool(starts) == goes, f"0248: touches {mine} vs {theirs}: ждали запуск={goes}, {e.calls()}")
        if not goes:
            check("athena-0001 — ждёт hermes-0001: общие файлы" in e.alerts(), f"0248: ожидание без тревоги: {e.alerts()[-300:]}")


def test_session_waits_reaches_you():
    """Ревью argus: сессия «ждёт вас», пока вы у Mac, — в очередь; ушли, а она всё ждёт — одна macOS и больше
    ни одной, пока ждёт; «упала» той же сессии — своё событие (свой ключ), а не «уже сообщали»."""
    e = Env()
    e.direction("coord-x")
    e.notify_mode(0)
    e.agents([bg("coord-x", "blocked", "sess0001-aaaa", pid=31)])
    e.run("watch", t=T0)                                         # «здесь»
    a = e.sent()
    e.notify_mode(1200)                                          # ушли
    e.run("watch", t=T0 + 300)
    b = e.sent()
    e.run("watch", t=T0 + 1800)
    c = e.sent()
    e.run("watch", t=T0 + 4200)
    d = e.sent()
    check("ждёт вас" not in a and "watch-blocked-sess0001" in e.queued(), f"«здесь»: без macOS и в очереди: {a!r}")
    check(b.count("coord-x ждёт вас") == 1, f"ушли — одна macOS: {b!r}")
    check(c.count("coord-x ждёт вас") == 1, f"через 25 мин — второй нет: {c!r}")
    check(d.count("coord-x ждёт вас") == 1 and "|session-coord-x" in d, f"через 65 мин — повтора нет: {d!r}")
    check(e.alerts().count("coord-x (sess0001) ждёт вас") == 1, "тревога в alerts.md — не разовая")
    # «готово» (сессия работает), затем снова «ждёт» — ещё одна macOS
    e.agents([bg("coord-x", "working", "sess0001-aaaa", pid=31)])
    e.run("watch", t=T0 + 4500)
    e.agents([bg("coord-x", "blocked", "sess0001-aaaa", pid=31)])
    e.run("watch", t=T0 + 4800)
    check(e.sent().count("coord-x ждёт вас") == 2, f"снова «ждёт» после снятия — без второй macOS: {e.sent()!r}")
    # весь день ждут две сессии, вас нет: по одной macOS на сессию, бюджет не съеден — решение «Нужен ответ» дойдёт
    e = Env()
    e.extra["TZ"] = "Europe/Moscow"
    e.direction("coord-x")
    e.direction("coord-y")
    e.notify_mode(1200)
    e.agents([bg("coord-x", "blocked", "sess0004-dddd", pid=34), bg("coord-y", "blocked", "sess0005-eeee", pid=35)])
    day = T0 - 8 * 3600 - 46 * 60                                  # 2026-10-14 12:00 по Москве
    for k in range(34):                                          # 12:00 … 23:00, каждые 20 мин
        e.run("watch", t=day + k * 1200)
    s = e.sent()
    used = json.load(open(e.st("notify.json"))).get("used")
    check(s.count("coord-x ждёт вас") == 1 and s.count("coord-y ждёт вас") == 1 and used == 2,
          f"день ожидания двух сессий — по одной macOS, бюджет 2: {s!r} used={used}")
    r = e.run("task", "new", "--text", "тест", "--direction", "coord-x", "--title", "Решить вечером", "--status", "waiting",
              "--waiting-on", "human", "--next", "ответ", "--question", "Что выбрать?", "--project", "coord-x",
              t=day + 11 * 3600 - 120)
    e.run("board", t=day + 11 * 3600 - 60)                       # 22:59 — ещё не тихие часы
    check(r.returncode == 0 and "Вопрос к вам: Решить вечером" in e.sent(),
          f"после дня ожидания решение «Нужен ответ» без macOS: {r.stderr} {e.sent()!r}")
    # «ждёт», через 10 мин «упала» той же сессии — при «нет» отдельная macOS
    e = Env()
    e.direction("coord-x")
    e.notify_mode(1200)
    e.agents([bg("coord-x", "blocked", "sess0002-bbbb", pid=32)])
    e.run("watch", t=T0)
    e.agents([bg("coord-x", "failed", "sess0002-bbbb", pid=32)])
    e.run("watch", t=T0 + 600)
    s = e.sent()
    check("coord-x ждёт вас" in s and "coord-x упала" in s, f"«упала» после «ждёт» при «нет» — своя macOS: {s!r}")
    # то же при «здесь» — обе строки в очереди сводки
    e = Env()
    e.direction("coord-x")
    e.notify_mode(0)
    e.agents([bg("coord-x", "blocked", "sess0003-cccc", pid=33)])
    e.run("watch", t=T0)
    e.agents([bg("coord-x", "failed", "sess0003-cccc", pid=33)])
    e.run("watch", t=T0 + 600)
    q = e.queued()
    check(not e.sent() and "watch-blocked-sess0003" in q and "watch-failed-sess0003" in q,
          f"«упала» после «ждёт» при «здесь» — строка в очереди: {q}")


def test_watch_notify_through_policy():
    """Уведомления дежурного — через политику (metis-0023): сбой «скоро» — macOS только при «нет» и не ночью,
    иначе в очередь сводки; подделка журнала ваших слов — критичное: сразу, и ночью, и когда вы у Mac."""
    e = Env()
    e.notify_mode(0)                                           # вы у Mac, день
    t = _give_up(e)
    check("Самозапуск" not in e.sent() and "autostart-gaveup-hermes-x" in e.queued(),
          f"самозапуск встал при «здесь»: уведомление или нет в очереди: {e.sent()!r} {e.queued()}")
    e.notify_mode(1200)                                        # ушли, а самозапуск так и стоит — macOS дойдёт
    e.run("watch", t=t + 60)
    check(e.sent().count("Самозапуск hermes-x встал") == 1, f"самозапуск стоит, вы ушли — без macOS: {e.sent()!r}")
    e = Env()
    e.notify_mode(1200, ("12:00", "11:59"))                    # нет у Mac, ночь (тихие часы весь день)
    _give_up(e)
    check("Самозапуск" not in e.sent() and "autostart-gaveup-hermes-x" in e.queued(),
          f"самозапуск встал ночью: уведомление или нет в очереди: {e.sent()!r}")
    e = Env()
    e.notify_mode(1200)                                        # нет у Mac, день
    _give_up(e)
    check("Самозапуск hermes-x встал" in e.sent(), "самозапуск встал при «нет» днём — без уведомления")
    # проверка опор после обновления Claude Code не прошла — сбой «скоро»: при «здесь» без уведомления
    e = Env()
    e.notify_mode(0)
    e.run("watch", t=T0)
    e.run("watch", t=T0 + 60, extra={"PANTHEON_FAKE_CC": "2.1.300"})
    check("НЕ в порядке" in e.alerts() and "проверка опор" not in e.sent() and "infra" in e.queued(),
          f"infra при «здесь»: {e.sent()!r} {e.queued()}")
    # техперезапуск истёк — сбой «скоро»: при «здесь» без уведомления
    e = Env()
    e.notify_mode(0)
    e.direction("mm-dir")
    e.run("restart", "--prepare", "обновление", t=T0)
    e.run("watch", t=T0 + 7300)
    check("истекла" in e.alerts() and "Техперезапуск" not in e.sent() and "restart" in e.queued(),
          f"restart при «здесь»: {e.sent()!r} {e.queued()}")
    # журнал ваших слов изменён задним числом — критичное: и при «здесь», и ночью
    for idle, quiet in ((0, None), (1200, ("12:00", "11:59"))):
        e = Env()
        e.notify_mode(idle, quiet)
        p = os.path.join(e.st("owner-log"), "athena.md")
        new = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 - 86400))
        open(p, "w").write(f"## {new}\nсвежее\n\n")
        e.run("watch", t=T0)
        open(p, "w").write(f"## {new}\nподменённое\n\n")
        e.run("watch", t=T0 + 86400)
        check("изменена уже записанная часть" in e.alerts() and "Журнал ваших слов изменён задним числом" in e.sent()
              and "критично" in e.sent(), f"подделка журнала (простой {idle}, тихие {quiet}): {e.sent()!r}")
        os.remove(p)
        e.run("watch", t=T0 + 2 * 86400)
        check("Журнал ваших слов удалён" in e.sent(), f"удаление журнала (простой {idle}, тихие {quiet}): {e.sent()!r}")
        nl = os.path.join(e.state, "notify-log.jsonl")
        check(os.path.exists(nl) and '"critical"' in open(nl).read(), "критичное дежурного не в журнале уведомлений")


def test_autostart_backoff_and_give_up():
    """Сбой — пауза растёт; три сбоя подряд — самозапуск направления встаёт, уведомление; resume сбрасывает."""
    e = Env()
    e.notify_mode(1200)  # «нет у Mac» и без тихих часов: сбой «скоро» уходит уведомлением (metis-0023)
    e.direction("hermes-x")
    e.task("hermes-0001", "hermes-x")
    e.run("watch", t=T0)
    e.board("hermes-0001", T0 + 10)
    t = T0 + 60
    for i in range(3):
        e.run("watch", t=t)                                    # запуск (сессии в claude agents так и нет)
        e.run("watch", t=t + 400)                              # итог: не появилась — сбой
        st = json.load(open(e.st("autostart.json")))["hermes-x"]
        check(st.get("fails") == i + 1, f"сбой {i + 1} не засчитан: {st}")
        if i < 2:
            gap = st["next"] - (t + 400)
            check(3600 * 2 ** i * 0.85 < gap < 3600 * 2 ** i * 1.15, f"пауза после сбоя {i + 1}: {gap}")
            t = st["next"] + 10
    check(st.get("gave_up"), "после трёх сбоев самозапуск не встал")
    check("остановлен после 3 сбоев" in e.alerts(), "тревога о трёх сбоях")
    check("Самозапуск hermes-x встал" in open(e.notify).read(), "уведомление о трёх сбоях")
    n = len([c for c in e.calls() if c[:1] == ["--bg"]])
    e.run("watch", t=t + 99999)
    check(len([c for c in e.calls() if c[:1] == ["--bg"]]) == n, "после отказа самозапуск продолжает")
    e.run("resume", "hermes-x", t=t + 99999)
    e.run("watch", t=t + 99999)
    check(not json.load(open(e.st("autostart.json")))["hermes-x"].get("gave_up"), "resume не сбросил счётчик сбоев")
    # снова встал (ревью argus): отметка once прежнего эпизода не снята (после resume живая сессия — сброса нет);
    # новый эпизод «встал» всё равно даёт macOS
    np = e.st("notify.json")

    def stale(at):  # отметка прежнего эпизода, которую autostart() не снял
        nst = json.load(open(np, encoding="utf-8"))
        nst.setdefault("faults", {})["autostart-gaveup-hermes-x"] = {"t": at, "text": "старое", "once": True}
        data = json.dumps(nst, ensure_ascii=False)
        with open(np, "w", encoding="utf-8") as fh:
            fh.write(data)
    before = open(e.notify).read().count("Самозапуск hermes-x встал")
    t = t + 99999 + 3 * 86400
    for i in range(3):
        e.run("watch", t=t)
        if i == 2:
            stale(t - 3 * 86400)  # прямо перед третьим сбоем: дальше — только fail()
        e.run("watch", t=t + 400)
        st = json.load(open(e.st("autostart.json")))["hermes-x"]
        if i < 2:
            t = st["next"] + 10
    check(st.get("gave_up") and open(e.notify).read().count("Самозапуск hermes-x встал") == before + 1,
          f"снова встал через 3 дня при неснятой отметке — нет второй macOS: {st}")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
