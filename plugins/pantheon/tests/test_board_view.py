#!/usr/bin/env python3
"""metis-0123: доска начинается с «Мне ответить». Виды Доска.base, сводка со счётчиками, предупреждения по options.

Запуск: python3 -I plugins/pantheon/tests/test_board_view.py  (код выхода 0 — все прошли)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CLI = os.path.join(LIB, "pantheon.py")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

T0 = 1_792_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def views():
    """Виды Доска.base по порядку: имя → текст вида."""
    body = T.BASE_FILE.split("\nviews:\n", 1)[1]
    parts = re.split(r"^  - type: ", body, flags=re.M)[1:]
    return [(re.search(r"^    name: (.+)$", p, re.M).group(1), p) for p in parts]


def hides_closed(view_text):
    """Вид исключает Готово и Отменено фильтрами статуса."""
    return all(f'note["Статус"] != "{x}"' in view_text for x in ("Готово", "Отменено"))


def base_checks():
    vs = views()
    names = [n for n, _ in vs]
    check("Доска.base: первый вид «Мне ответить», второй «Система»", names[:2] == ["Мне ответить", "Система"], names)
    check("Доска.base: есть «Очередь агентов» и «Все задачи»", {"Очередь агентов", "Все задачи"} <= set(names))
    mine = dict(vs)["Мне ответить"]
    check("«Мне ответить»: Статус «Нужен ответ» или Кому = Владелец",
          'note["Статус"] == "Нужен ответ"' in mine and 'note["Кому"].toString().contains("Владелец")' in mine
          and "- or:" in mine)
    cols = re.search(r"order: \[(.*)\]", mine).group(1).split(", ")
    check("«Мне ответить»: 5–6 колонок, первая — «Вопрос»", cols[0] == "note.Вопрос" and 5 <= len(cols) <= 6, cols)
    sysv = dict(vs)["Система"]
    check("«Система» — канбан, «Отменено» и «Очередь» скрыты", sysv.startswith("kanban")
          and 'note["Статус"] != "Отменено"' in sysv and 'note["Статус"] != "Очередь"' in sysv)
    go = re.search(r"groupOrder: \[(.*)\]", sysv).group(1)
    check("«Система»: в порядке колонок нет «Отменено» и «Очередь»", "Отменено" not in go and "Очередь" not in go, go)
    check("«Система»: «Готово» — за 7 дней по «Закрыта»",
          'note["Статус"] != "Готово"' in sysv and 'note["Закрыта"] >= today() - "7d"' in sysv)
    queue = dict(vs)["Очередь агентов"]
    check("«Очередь агентов»: только «Очередь»", 'note["Статус"] == "Очередь"' in queue)
    allv = dict(vs)["Все задачи"]
    check("«Все задачи» — без фильтров статуса (полностью)", "filters:" not in allv)
    check("«Мне ответить»: исключает «Готово» и «Отменено»", hides_closed(mine))
    # сломать правило: проверка на вид без фильтра должна дать False
    for x in ("Готово", "Отменено"):
        broken = mine.replace(f'note["Статус"] != "{x}"', "true")
        check(f"проверка «{x} скрыто» краснеет на сломанном виде", hides_closed(mine) and not hides_closed(broken))


def card_checks():
    head = {"id": "t-1", "title": "Выбрать", "status": "waiting", "waiting_on": "human", "question": "Брать А или Б?",
            "project": "demo", "direction": "demo", "owner": "demo"}
    card = T.render_card(head, "", "x.md", T0)[0]
    check("карточка: свойство «Вопрос» — фраза из question", card is not None and card.get("Вопрос") == "Брать А или Б?",
          card)


def summary_checks():
    h = {"type": "task", "id": "metis-0001", "title": "Нужно решить", "status": "waiting", "waiting_on": "human",
         "project": "demo", "direction": "demo", "question": "Q?", "created": "2026-10-17"}
    h2 = {"type": "task", "id": "metis-0002", "title": "Сделано", "status": "done", "project": "demo",
          "direction": "demo", "created": "2026-10-17", "updated": T.now_iso(T0 - 100)}
    tasks = {"metis-0001": ("p1", h, ""), "metis-0002": ("p2", h2, "")}
    text, _ = T._summary(tasks, T0)
    lines = text.split("\n")
    i_cnt = next((i for i, ln in enumerate(lines) if "Мне ответить 1" in ln), -1)
    i_mine = next((i for i, ln in enumerate(lines) if ln == "## Мне ответить"), -1)
    check("сводка: сверху строка счётчиков (сразу после заголовка)", lines[0] == "# Сводка" and i_cnt == 2
          and "Готово за сутки 1" in lines[i_cnt], lines[:4])
    check("сводка: под счётчиками «Мне ответить» со встроенным видом",
          i_cnt < i_mine and "![[Доска.base#Мне ответить]]" in lines[i_mine + 2])
    # Кому = Владелец: считается, без двойного счёта; Готово/Отменено — нет; чужой адресат — нет
    def mk(i, **kw):
        return (f"p{i}", {"type": "task", "id": f"metis-1{i:03d}", "title": f"З{i}", "status": "todo", "project": "demo",
                          "direction": "demo", "created": "2026-10-17", **kw}, "")
    cases = [mk(1, owner="Вы"), mk(2, owner="owner", status="done", updated=T.now_iso(T0 - 100)),
             mk(3, owner="human", status="dropped"), mk(4, owner="hephaestus-demo"),
             mk(5, owner="Владелец", status="waiting", waiting_on="human", question="Q?"), mk(6)]
    t2 = {c[1]["id"]: c for c in cases}
    text2, _ = T._summary(t2, T0)
    cnt = next(ln for ln in text2.split("\n") if "Мне ответить" in ln and "Просрочено" in ln)
    check("сводка: «Мне ответить» = Кому Владелец + ждут человека, без Готово/Отменено и двойного счёта",
          "Мне ответить 2 ·" in cnt and "Нужен ответ (1)" in text2, cnt)
    check("сводка: «Готово за сутки» свёрнуто", "> [!success]- 🟢 Готово за сутки (1)" in text)


def warn_checks():
    bad = ["А ()", "Б ( )", "В ≈ )", "Г $…", "Д ≈ "]
    check("option_warns: «()», «( )», «≈ )», «$…» — предупреждение",
          all(T.option_warns({"options": [o]}) for o in bad), [o for o in bad if not T.option_warns({"options": [o]})])
    good0 = ["А. Купить за 20$", "Б. Купить за 20 $", "В. 5 000 $ в месяц", "Г. $5"]
    check("option_warns: «20$», «20 $» — тихо", not any(T.option_warns({"options": [o]}) for o in good0),
          [o for o in good0 if T.option_warns({"options": [o]})])
    good = ["А. Купить за 5 000 ₽ (дороже). Цена: деньги", "Б. Подождать до пятницы. Цена: срок", "В. ≈ 5 дней"]
    check("option_warns: нормальные варианты — тихо", not any(T.option_warns({"options": [o]}) for o in good))
    check("option_warns: «(совет)» в варианте про деньги — предупреждение, без денег — нет",
          T.option_warns({"options": ["А (совет). Оплатить 5000 ₽"]}) and not T.option_warns({"options": ["А (совет). Подождать"]}))
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="board-view-"))
    try:
        home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
        os.makedirs(os.path.join(home, "directions", "demo", "tasks"))
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
               "PANTHEON_VIEW": os.path.join(tmp, "view"), "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
               "PANTHEON_NOW": str(T0), "TMPDIR": tmp}

        def run(*a):
            return subprocess.run([PY311, "-I", CLI, *a], env=env, capture_output=True, text=True, timeout=60)

        r = run("task", "new", "--direction", "demo", "--title", "Выбор", "--option", "А ()", "--option", "Б ≈ )")
        check("task new с «()» и «≈ )»: создана, предупреждение в stderr",
              r.returncode == 0 and r.stderr.count("предупреждение") == 2, r.stderr)
        tid = r.stdout.split()[0]
        r = run("task", "set", tid, "--option", "В. Нормальный вариант с пояснением")
        check("task set с нормальным вариантом — без предупреждений", r.returncode == 0 and not r.stderr, r.stderr)
        r = run("task", "set", tid, "--option", "Г $…")
        check("task set с «$…» — предупреждение", r.returncode == 0 and "предупреждение" in r.stderr, r.stderr)
    finally:
        shutil.rmtree(tmp, True)


def main():
    base_checks()
    card_checks()
    summary_checks()
    warn_checks()
    print(f"{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
