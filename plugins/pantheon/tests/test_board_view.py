#!/usr/bin/env python3
"""metis-0123, metis-0069: доска начинается с «От меня нужно». Семь видов Доска.base, сводка со счётчиками,
предупреждения по options.

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


def base_filter(view_text):
    """Фильтр вида из текста .base (yaml без библиотеки): and/or-списки и три вида условий → функция карточки."""
    lines = [ln for ln in view_text.split("    filters:\n", 1)[1].split("\n    sort:", 1)[0].split("\n") if ln.strip()]

    def parse(i, indent):
        """Разбирает элементы списка с отступом indent, возвращает (список условий, следующая строка)."""
        items = []
        while i < len(lines) and len(lines[i]) - len(lines[i].lstrip()) == indent and lines[i].lstrip().startswith("-"):
            body = lines[i].lstrip()[1:].strip()
            if body in ("or:", "and:"):
                sub, i = parse(i + 1, indent + 4)
                items.append((body[:-1], sub))
            else:
                items.append(body.strip("'"))
                i += 1
        return items, i

    assert lines[0].strip() in ("and:", "or:"), lines[0]
    tree = (lines[0].strip()[:-1], parse(1, 8)[0])

    def ev(node, card):
        if isinstance(node, tuple):
            f = all if node[0] == "and" else any
            return f(ev(n, card) for n in node[1])
        m = re.fullmatch(r'note\["(.+?)"\](\.toString\(\)\.contains\(|\s*==\s*|\s*!=\s*)"(.*?)"\)?', node)
        assert m, node
        val, op, arg = str(card.get(m.group(1)) or ""), m.group(2), m.group(3)
        return arg in val if "contains" in op else (val == arg) == ("==" in op)

    return lambda card: ev(tree, card)


VIEWS5 = ["От меня нужно", "Доска", "Пачки", "Итоги пачек", "Все задачи"]


def base_checks():
    vs = views()
    names = [n for n, _ in vs]
    check("Доска.base: ровно пять видов по порядку (metis-0069)", names == VIEWS5, names)
    check("Доска.base: старых видов нет", not {"Мне ответить", "Система", "Очередь агентов", "Нужен ответ", "Горит",
                                               "Ночь", "Волны", "Утро", "Срочно"} & set(names), names)
    mine = dict(vs)["От меня нужно"]
    check("«От меня нужно»: Нужен ответ, Кому = Владелец или приёмка «к владельцу»",
          'note["Статус"] == "Нужен ответ"' in mine and 'note["Кому"].toString().contains("Владелец")' in mine
          and 'note["Приёмка"] == "к владельцу"' in mine and "- or:" in mine)
    cols = re.search(r"order: \[(.*)\]", mine).group(1).split(", ")
    check("«От меня нужно»: 5–6 колонок, первая — «Вопрос»", cols[0] == "note.Вопрос" and 5 <= len(cols) <= 6, cols)
    board = dict(vs)["Доска"]
    check("«Доска» — канбан, «Отменено» скрыто, «Очередь» видна, пачек нет", board.startswith("kanban")
          and 'note["Статус"] != "Отменено"' in board and 'note["Статус"] != "Очередь"' not in board
          and 'note["Тип"] != "пачка"' in board)
    go = re.search(r"groupOrder: \[(.*)\]", board).group(1)
    check("«Доска»: в порядке колонок есть «Очередь», нет «Отменено»", "Отменено" not in go and "Очередь" in go, go)
    check("«Доска»: «Готово» — за 7 дней по «Закрыта»",
          'note["Статус"] != "Готово"' in board and 'note["Закрыта"] >= today() - "7d"' in board)
    attn = re.search(r"^  attn: (.+)$", T.BASE_FILE, re.M).group(1)
    card = [x.strip() for x in re.search(r"^    order: \[(.*)\]", board, re.M).group(1).split(",")]
    check("«Доска»: «ждёт» и предупреждение режима — внутри одной строки formula.attn на карточке",
          "formula.waits" in attn and "formula.warn" in attn and 'note["Срок"]' in attn and "formula.attn" in card)
    check("metis-0306: карточка «Доски» — не больше 5 свойств", 0 < len(card) <= 5, str(card))
    check("metis-0306: заявки ролей (Тип «заявка», Кому без «Владелец») вне «Доски»",
          "- 'note[\"Тип\"] != \"заявка\"'" in board and "- 'note[\"Кому\"].toString().contains(\"Владелец\")'" in board)
    check("metis-0306: в «Все задачи» заявки остаются — фильтра заявок там нет", "заявка" not in dict(vs)["Все задачи"])
    check("metis-0306: справка «Доска» — не длиннее двух предложений, без «Пачки здесь не видны»",
          "Пачки здесь не видны" not in T.VIEW_HELP["Доска"] and len(re.findall(r"[.]\s", T.VIEW_HELP["Доска"] + " ")) <= 2)
    mine_sort = mine.split("sort:")[1].split("order:")[0]
    check("«От меня нужно»: срочные вверху — сортировка начинается с urgency", mine_sort.strip().startswith("- property: formula.urgency"))
    packs = dict(vs)["Пачки"]
    check("«Пачки» — канбан карточек пачек с суммой оценок и бюджетом", packs.startswith("kanban")
          and 'note["Тип"] == "пачка"' in packs and "note.Закрыто" in packs and "note.Цепочка" in packs
          and "formula.sum_budget" in packs and "Бюджет" in re.search(r"^  sum_budget: (.+)$", T.BASE_FILE, re.M).group(1)
          and len(re.search(r"^    order: \[(.*)\]", packs, re.M).group(1).split(",")) <= 5)
    css = open(os.path.join(os.path.dirname(LIB), "share", "pantheon-view-obsidian", "snippets", "pantheon.css"),
               encoding="utf-8").read()
    check("metis-0306: CSS — подписи карточки скрыты, встраивания и kanban ограничены по высоте окна (классы Obsidian)",
          ".bases-kanban-card-property .bases-kanban-card-label { display: none; }" in css
          and re.search(r"\.bases-embed \.bases-view[^{]*\{[^}]*max-height: calc\(100vh", css)
          and re.search(r"\.bases-embed \.bases-kanban-container[^{]*\{[^}]*max-height: calc\(100vh", css))
    check("metis-0306: «Итоги пачек» — Приёмка из formula.accept_view, «Все задачи» — колонка № шире",
          "formula.accept_view" in dict(vs)["Итоги пачек"] and re.search(r"columnSize:\n      note\.id: \d{3}", dict(vs)["Все задачи"]))
    res = dict(vs)["Итоги пачек"]
    check("«Итоги пачек»: задачи пачек, группы по пачке, по порядку", 'note["Тип"] != "пачка"' in res
          and "property: note.Пачка" in res and "property: note.Порядок" in res)
    allv = dict(vs)["Все задачи"]
    check("«Все задачи» — без фильтров статуса (полностью)", "filters:" not in allv)
    check("«От меня нужно»: исключает «Готово» и «Отменено»", hides_closed(mine))
    # сломать правило: проверка на вид без фильтра должна дать False
    for x in ("Готово", "Отменено"):
        broken = mine.replace(f'note["Статус"] != "{x}"', "true")
        check(f"проверка «{x} скрыто» краснеет на сломанном виде", hides_closed(mine) and not hides_closed(broken))
    # «На проверке» попадает в «От меня нужно» только адресованная Владельцу (по фильтру вида)
    passes = base_filter(mine)
    review = {"id": "t-2", "title": "Проверить", "status": "review", "project": "demo", "direction": "demo"}
    to_owner = T.render_card(dict(review, owner="Владелец"), "", "x.md", T0)[0]
    to_agent = T.render_card(dict(review, owner="argus"), "", "x.md", T0)[0]
    check("«На проверке» с Кому = Владелец — в «От меня нужно», с Кому = агент — нет",
          passes(to_owner) and not passes(to_agent), (to_owner.get("Кому"), to_agent.get("Кому")))
    broken_f = base_filter(mine.replace("        - 'note[\"Статус\"] != \"Отменено\"'",
                                        "        - 'note[\"Статус\"] != \"Отменено\"'\n        - 'note[\"Статус\"] == \"На проверке\"'"))
    check("фильтр из .base с дописанным Статус == «На проверке» краснеет: «Нужен ответ» не проходит",
          passes({"Статус": "Нужен ответ"}) and not broken_f({"Статус": "Нужен ответ"}))
    check("фильтр из .base: Готово не проходит даже при Кому = Владелец",
          not passes({"Статус": "Готово", "Кому": "Владелец"}))
    # Пульт.base: вариант В — карточки проектов с цветом здоровья, пачки канбаном, пачки проекта и задачи пачки
    pult = T.PULT_FILE.split("\nviews:\n", 1)[1]
    pv = [(re.search(r"^    name: (.+)$", x, re.M).group(1), x) for x in re.split(r"^  - type: ", pult, flags=re.M)[1:]]
    check("Пульт.base: виды Пульт, Пачки, Пачки проекта, Задачи пачки",
          [n for n, _ in pv] == ["Пульт", "Пачки", "Пачки проекта", "Задачи пачки"], [n for n, _ in pv])
    pd = dict(pv)
    check("Пульт.base: «Пульт» — карточки проектов, картинка — цвет здоровья", pd["Пульт"].startswith("cards")
          and 'note["Тип"] == "проект"' in pd["Пульт"] and "image: note.Цвет" in pd["Пульт"]
          and all(f"note.{k}" in pd["Пульт"] for k in T.COUNTERS))
    check("Пульт.base: «Пачки проекта» и «Задачи пачки» — по ссылке на открытую заметку",
          "file.hasLink(this.file)" in pd["Пачки проекта"] and "file.hasLink(this.file)" in pd["Задачи пачки"]
          and "property: note.Порядок" in pd["Задачи пачки"])
    check("Пульт.base: узлы ролей не попадают", "'!file.inFolder(\"Доска/Узлы\")'" in T.PULT_FILE)


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
    i_cnt = next((i for i, ln in enumerate(lines) if "От меня нужно 1" in ln), -1)
    i_mine = next((i for i, ln in enumerate(lines) if ln == "## От меня нужно"), -1)
    check("сводка: сверху строка счётчиков (сразу после заголовка)", lines[0] == "# Сводка" and i_cnt == 2
          and "Готово за сутки 1" in lines[i_cnt], lines[:4])
    check("сводка: под счётчиками «От меня нужно» со встроенным видом",
          i_cnt < i_mine and "![[Доска.base#От меня нужно]]" in lines[i_mine + 4])
    # Кому = Владелец: считается, без двойного счёта; Готово/Отменено — нет; чужой адресат — нет
    def mk(i, **kw):
        return (f"p{i}", {"type": "task", "id": f"metis-1{i:03d}", "title": f"З{i}", "status": "todo", "project": "demo",
                          "direction": "demo", "created": "2026-10-17", **kw}, "")
    cases = [mk(1, owner="Вы"), mk(2, owner="owner", status="done", updated=T.now_iso(T0 - 100)),
             mk(3, owner="human", status="dropped"), mk(4, owner="hephaestus-demo"),
             mk(5, owner="Владелец", status="waiting", waiting_on="human", question="Q?"), mk(6)]
    t2 = {c[1]["id"]: c for c in cases}
    text2, _ = T._summary(t2, T0)
    cnt = next(ln for ln in text2.split("\n") if "От меня нужно" in ln and "Просрочено" in ln)
    check("сводка: «От меня нужно» = Кому Владелец + ждут человека, без Готово/Отменено и двойного счёта",
          "От меня нужно 2 ·" in cnt and "Нужен ответ (1)" in text2, cnt)
    t3 = dict(t2, **{"metis-1007": mk(7, owner="argus", status="review", acceptance="к владельцу")})
    cnt3 = next(ln for ln in T._summary(t3, T0)[0].split("\n") if "От меня нужно" in ln and "Просрочено" in ln)
    check("сводка: приёмка «к владельцу» тоже в «От меня нужно», как в виде", "От меня нужно 3 ·" in cnt3, cnt3)
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
