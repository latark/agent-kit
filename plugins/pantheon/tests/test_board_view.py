#!/usr/bin/env python3
"""metis-0123, metis-0069: доска начинается с «От меня нужно». Семь видов Доска.base, сводка со счётчиками,
предупреждения по options.

Запуск: python3 -I plugins/pantheon/tests/test_board_view.py  (код выхода 0 — все прошли)
"""
import json
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
RUN_PY = os.path.join(os.path.dirname(CLI), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
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


VIEWS5 = ["От меня нужно", "Доска", "Пачки", "Итоги пачек", "Все задачи", "Новое за неделю", "Хвосты"]  # + два вида metis-0506


def base_checks():
    vs = views()
    names = [n for n, _ in vs]
    check("Доска.base: ровно семь видов по порядку (metis-0069, metis-0506)", names == VIEWS5, names)
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
    check("Пульт.base: виды Пульт, Пачки, Пачки проекта, Задачи пачки, Учёт недели, Учёт с начала",
          [n for n, _ in pv] == ["Пульт", "Пачки", "Пачки проекта", "Задачи пачки", "Учёт недели", "Учёт с начала"],
          [n for n, _ in pv])
    pd = dict(pv)
    check("Пульт.base: «Пульт» — карточки проектов, картинка — цвет здоровья", pd["Пульт"].startswith("cards")
          and 'note["Тип"] == "проект"' in pd["Пульт"] and "image: note.Цвет" in pd["Пульт"]
          and all(f"note.{k}" in pd["Пульт"] for k in T.COUNTERS))
    check("Пульт.base: «Пачки проекта» и «Задачи пачки» — по ссылке на открытую заметку",
          "file.hasLink(this.file)" in pd["Пачки проекта"] and "file.hasLink(this.file)" in pd["Задачи пачки"]
          and "property: note.Порядок" in pd["Задачи пачки"])
    check("Пульт.base: «Учёт недели» и «Учёт с начала» — заметки учёта своего периода (metis-0294)",
          'note["Тип"] == "учёт"' in pd["Учёт недели"] and 'note["Период"] == "неделя"' in pd["Учёт недели"]
          and 'note["Период"] == "с начала"' in pd["Учёт с начала"] and "note.Долларов на задачу" in pd["Учёт недели"])
    check("Пульт.base: узлы ролей не попадают", "'!file.inFolder(\"Доска/Узлы\")'" in T.PULT_FILE)
    # metis-0306 (ревью, M10): компактная карточка «Пачки» и в Пульте — не длиннее 5 свойств, как в «Доске»
    ppacks = pd["Пачки"]
    porder = [x.strip() for x in re.search(r"^    order:\n((?:      - .+\n?)+)", ppacks, re.M).group(1).replace("      - ", "").split("\n") if x.strip()]
    check("metis-0306: Пульт.base, «Пачки» — карточка не больше 5 свойств: имя, Закрыто, Вопросов (metis-0801), сумма/бюджет, цепочка",
          porder == ["file.name", "note.Закрыто", "note.Вопросов", "formula.sum_budget", "note.Цепочка"], str(porder))
    # metis-0306 (ревью, M12): формула accept_view даёт «ждёт приёмки» только для «На проверке» с пустой Приёмкой
    acc = re.search(r"^  accept_view: (.+)$", T.BASE_FILE, re.M).group(1)
    check("metis-0306: accept_view — пустая Приёмка у «На проверке» даёт «ждёт приёмки», заполненная выводится как есть, прочее пусто",
          acc.startswith("'if(note[\"Приёмка\"].isEmpty()") and "ждёт приёмки" in acc and 'note["Статус"] == "На проверке"' in acc
          and acc.rstrip("'").endswith(', note["Приёмка"])') and acc.count('""') == 1, acc)


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
    # metis-0240: счётчик сравнивает «Кому» так же, как вид (contains «Владелец»), а не равенством
    t4 = dict(t2, **{"metis-1008": mk(8, owner="Владелец · гость")})
    cnt4 = next(ln for ln in T._summary(t4, T0)[0].split("\n") if "От меня нужно" in ln and "Просрочено" in ln)
    check("сводка: узел «Владелец · гость» в «От меня нужно», как в виде (contains)",
          T.Roles(()).name("Владелец · гость") == "Владелец · гость" and "От меня нужно 3 ·" in cnt4
          and 'note["Кому"].toString().contains("Владелец")' in T.BASE_FILE, cnt4)
    check("сводка: «Готово за сутки» свёрнуто", "> [!success]- 🟢 Готово за сутки (1)" in text)


def warn_checks():
    bad = ["А ()", "Б ( )", "В ≈ )", "Г $…", "Д ≈ ", "Е. всего  $ в месяц", "Ж. 20$ и ещё $"]
    check("option_warns: «()», «( )», «≈ )», «$…» — предупреждение",
          all(T.option_warns({"options": [o]}) for o in bad), [o for o in bad if not T.option_warns({"options": [o]})])
    good0 = ["А. Купить за 20$", "Б. Купить за 20 $", "В. 5 000 $ в месяц", "Г. $5", "Д. за 20  $", "Е. за 20\u00a0$",
             "Ж. за 20 \u202f $ и 30$"]  # metis-0240: два пробела и неразрывный пробел перед «$» — тоже валюта
    check("option_warns: «20$», «20 $», «20  $» — тихо", not any(T.option_warns({"options": [o]}) for o in good0),
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
            return subprocess.run([PY311, "-I", RUN_PY, *a], env=env, capture_output=True, text=True, timeout=60)

        r = run("task", "new", "--text", "тест", "--direction", "demo", "--title", "Выбор", "--option", "А ()", "--option", "Б ≈ )")
        check("task new с «()» и «≈ )»: создана, предупреждение в stderr",
              r.returncode == 0 and r.stderr.count("предупреждение") == 2, r.stderr)
        tid = r.stdout.split()[0]
        r = run("task", "set", tid, "--option", "В. Нормальный вариант с пояснением")
        check("task set с нормальным вариантом — без предупреждений", r.returncode == 0 and not r.stderr, r.stderr)
        r = run("task", "set", tid, "--option", "Г $…")
        check("task set с «$…» — предупреждение", r.returncode == 0 and "предупреждение" in r.stderr, r.stderr)
    finally:
        shutil.rmtree(tmp, True)


def snippet_checks():
    """metis-0306 (ревью): новый pantheon.css доходит до копии, у которой .obsidian уже есть (view-sync.sh кладёт образец
    только в пустую копию) — по образцу _sync_base: нетронутый прежний — молча, правка владельца — копия и одна тревога."""
    tmp = tempfile.mkdtemp(dir=os.environ.get("TMPDIR"))
    try:
        vault = os.path.join(tmp, "view")
        snip = os.path.join(vault, ".obsidian", "snippets", "pantheon.css")
        state = os.path.join(tmp, "state", "board.json")
        new = open(T.CSS_PATH, encoding="utf-8").read()
        alerts = []
        al = lambda *a, **k: alerts.append(a)
        keeps = lambda: sorted(f for f in os.listdir(os.path.dirname(state)) if f.startswith("board-css-")) \
            if os.path.isdir(os.path.dirname(state)) else []
        st = {}
        T._sync_snippet(vault, st, state, T0, al)
        check("сниппет: нет .obsidian — ничего не создаём (образец положит view-sync.sh)",
              not os.path.exists(os.path.join(vault, ".obsidian")) and not st and not alerts)
        os.makedirs(os.path.dirname(snip))
        # у владельца: .obsidian есть, сниппет прежний (нетронутый шаблон до 0.11.53)
        old = "/* прежний */\n"
        open(snip, "w", encoding="utf-8").write(old)
        T._sync_snippet(vault, st, state, T0, al, old_hashes={T._sha(old)})
        check("сниппет: у копии уже есть .obsidian, прежний нетронутый — обновлён без тревоги и копии",
              open(snip, encoding="utf-8").read() == new and not alerts and not keeps() and st["css_version"] == T._sha(new))
        # правка владельца при новой версии шаблона: копия + одна тревога
        st["css_version"] = "старая"
        open(snip, "w", encoding="utf-8").write("/* моё */\n")
        T._sync_snippet(vault, st, state, T0 + 5, al)
        k = keeps()
        check("сниппет: правка владельца — файл обновлён, его версия сохранена, одна тревога",
              open(snip, encoding="utf-8").read() == new and len(k) == 1 and len(alerts) == 1
              and open(os.path.join(os.path.dirname(state), k[0]), encoding="utf-8").read() == "/* моё */\n")
        # та же версия — правка владельца живёт
        open(snip, "w", encoding="utf-8").write("/* ещё моё */\n")
        T._sync_snippet(vault, st, state, T0 + 9, al)
        check("сниппет: версия та же — правка владельца не тронута",
              open(snip, encoding="utf-8").read() == "/* ещё моё */\n" and len(alerts) == 1)
        # настоящий прежний сниппет (main, sha b07338ca…) — в OLD_CSS_HASHES
        check("сниппет: хеш прежнего сниппета main в OLD_CSS_HASHES", "b07338ca44d6892d" in T.OLD_CSS_HASHES)
        # через тик: board_sync зовёт доставку
        os.remove(snip)
        pan = os.path.join(tmp, "pan")
        os.makedirs(pan)
        board = os.path.join(vault, "Доска")
        T.board_sync(pan, board, state, os.path.join(tmp, "log"), T0 + 20, alert=al)
        check("сниппет: тик доски (board_sync) возвращает удалённый сниппет",
              os.path.exists(snip) and open(snip, encoding="utf-8").read() == new)
    finally:
        shutil.rmtree(tmp, True)


def bookmark_checks():
    """metis-0324: закладки Obsidian — часть вида. Тик добавляет недостающие свои, закладки владельца не трогает,
    удалённую владельцем свою не возвращает, битый JSON не перезаписывает (одна тревога)."""
    tmp = tempfile.mkdtemp(dir=os.environ.get("TMPDIR"))
    try:
        want = json.load(open(T.BOOKMARKS_PATH, encoding="utf-8"))["items"]
        want_paths = [f["path"] for g in want for f in g["items"]]
        paths = lambda data: [f["path"] for f in T._bookmark_files(data["items"])]
        check("закладки: образец содержит Сводку, Доску, Пульт, Сроки, Кто есть кто, Проблемы и справку по видам",
              {"Доска/Сводка.md", "Доска/Доска.base", "Доска/Пульт.base", "board.md", "Кто есть кто.md",
               "Доска/Проблемы.md", f"Доска/{T.HELP_DIR}/{T.HELP_NOTE}.md"} <= set(want_paths), want_paths)

        def vault(name, raw=None):
            v = os.path.join(tmp, name)
            os.makedirs(os.path.join(v, ".obsidian"))
            p = os.path.join(v, ".obsidian", "bookmarks.json")
            if raw is not None:
                open(p, "w", encoding="utf-8").write(raw)
            return v, p
        alerts = []
        al = lambda *a, **k: alerts.append(a)

        v, p = vault("a")
        st = {}
        T._sync_bookmarks(v, st, al)
        got = json.load(open(p, encoding="utf-8"))
        check("закладки (а): пустой vault — все свои закладки, по группам образца",
              paths(got) == want_paths and [g["title"] for g in got["items"]] == [g["title"] for g in want]
              and sorted(st["bookmarks_seen"]) == sorted(want_paths) and not alerts, got)
        before = open(p, "rb").read()
        T._sync_bookmarks(v, st, al)
        sb = os.stat(p)
        T._sync_bookmarks(v, st, al)
        sa = os.stat(p)
        check("закладки: второй тик ничего не пишет (ни байтов, ни inode, ни mtime)",
              open(p, "rb").read() == before and (sb.st_ino, sb.st_mtime_ns) == (sa.st_ino, sa.st_mtime_ns))
        v0 = os.path.join(tmp, "none")
        os.makedirs(v0)
        T._sync_bookmarks(v0, {}, al)
        check("закладки: нет .obsidian — ничего не создаём", not os.path.exists(os.path.join(v0, ".obsidian")))

        own = {"items": [{"type": "file", "ctime": 1, "path": "Моя заметка.md", "title": "Моя"},
                         {"type": "group", "ctime": 2, "title": "Каждый день", "items": [
                             {"type": "file", "ctime": 3, "path": "Доска/Доска.base", "title": "Моя Доска"},
                             {"type": "file", "ctime": 4, "path": "Другое.md", "title": "Другое"}]},
                         {"type": "group", "ctime": 5, "title": "Своя группа", "items": [], "ключ": "x"}],
               "свойство": 1}
        v, p = vault("b", json.dumps(own, ensure_ascii=False))
        st = {"bookmarks_seen": []}  # состояние уже ведётся (не первый тик после выпуска): все недостающие свои — добавить
        T._sync_bookmarks(v, st, al)
        got = json.load(open(p, encoding="utf-8"))
        every = T._bookmark_files(got["items"])
        check("закладки (б): закладки владельца целы и в том же порядке, свои добавлены",
              got["items"][0] == own["items"][0] and got["items"][2] == own["items"][2] and got["свойство"] == 1
              and [i["path"] for i in got["items"][1]["items"][:2]] == ["Доска/Доска.base", "Другое.md"]
              and got["items"][1]["items"][0]["title"] == "Моя Доска"
              and [g.get("title") for g in got["items"]].count("Каждый день") == 1
              and "Доска/Пульт.base" in [i["path"] for i in got["items"][1]["items"]]
              and set(want_paths) <= {i["path"] for i in every}
              and [i["path"] for i in every].count("Доска/Доска.base") == 1, got)

        v, p = vault("c")
        st = {}
        T._sync_bookmarks(v, st, al)
        got = json.load(open(p, encoding="utf-8"))
        got["items"][0]["items"] = [i for i in got["items"][0]["items"] if i["path"] != "Доска/Пульт.base"]
        open(p, "w", encoding="utf-8").write(json.dumps(got, ensure_ascii=False))
        T._sync_bookmarks(v, st, al)
        T._sync_bookmarks(v, st, al)
        check("закладки (в): свою удалили — не вернулась", "Доска/Пульт.base" not in paths(json.load(open(p, encoding="utf-8"))))
        # новая свою закладка (образец дополнили) приходит, а удалённая по-прежнему нет
        src = os.path.join(tmp, "sample.json")
        ext = json.loads(json.dumps({"items": want}))
        ext["items"][1]["items"].append({"type": "file", "ctime": 9, "path": "Доска/Новый вид.md", "title": "Новый вид"})
        open(src, "w", encoding="utf-8").write(json.dumps(ext, ensure_ascii=False))
        T._sync_bookmarks(v, st, al, src=src)
        now = paths(json.load(open(p, encoding="utf-8")))
        check("закладки (в): новая своя закладка из образца приходит, удалённая — нет",
              "Доска/Новый вид.md" in now and "Доска/Пульт.base" not in now, now)

        # хранилище старого образца (до 0324), «Кто есть кто» владелец удалил, состояния ещё нет — первый тик не возвращает
        old = {"items": [{"type": "group", "ctime": 1, "title": "Каждый день", "items": [
                   {"type": "file", "ctime": 2, "path": "Доска/Сводка.md", "title": "Сводка"},
                   {"type": "file", "ctime": 3, "path": "Доска/Доска.base", "title": "Доска"}]},
               {"type": "group", "ctime": 4, "title": "Справка", "items": [
                   {"type": "file", "ctime": 5, "path": "Доска/Проблемы.md", "title": "Проблемы задач"}]}]}
        v, p = vault("old", json.dumps(old, ensure_ascii=False))
        st = {}
        T._sync_bookmarks(v, st, al)
        T._sync_bookmarks(v, st, al)
        now = paths(json.load(open(p, encoding="utf-8")))
        check("закладки (д): старый образец без ключа состояния — удалённая «Кто есть кто» не вернулась, новые пришли",
              "Кто есть кто.md" not in now and {"Доска/Пульт.base", "board.md", f"Доска/{T.HELP_DIR}/{T.HELP_NOTE}.md"} <= set(now)
              and "Доска/Сводка.md" in now, now)

        for name, raw in (("d1", '{"items": [ {'), ("d2", '["не", "словарь"]'), ("d3", '{"items": 5}')):
            v, p = vault(name, raw)
            alerts.clear()
            st = {}
            T._sync_bookmarks(v, st, al)
            T._sync_bookmarks(v, st, al)
            check(f"закладки (г): битый bookmarks.json ({name}) — файл не тронут, состояние пусто, тревога",
                  open(p, encoding="utf-8").read() == raw and not st and alerts and alerts[0][0] == "board-bookmarks"
                  and not [f for f in os.listdir(os.path.dirname(p)) if f.endswith(".tmp")], alerts)
        # через тик
        v, p = vault("e")
        pan = os.path.join(tmp, "pan")
        os.makedirs(pan, exist_ok=True)
        T.board_sync(pan, os.path.join(v, "Доска"), os.path.join(tmp, "state-e", "board.json"),
                     os.path.join(tmp, "log"), T0 + 30, alert=al)
        check("закладки: тик доски (board_sync) ставит набор", paths(json.load(open(p, encoding="utf-8"))) == want_paths)
        # path закладки владельца — не строка (список, объект): тик не падает, файл не тронут в чужой части, board.json пишется
        for name, bad in (("p1", ["x"]), ("p2", {"a": 1}), ("p3", 5), ("p4", None)):
            raw = json.dumps({"items": [{"type": "file", "ctime": 1, "path": bad, "title": "Чужая"}]}, ensure_ascii=False)
            v, p = vault(name, raw)
            st = {"bookmarks_seen": [["y"], {"b": 1}, "Доска/Сводка.md"]}
            try:
                T._sync_bookmarks(v, st, al)
                ok = True
            except Exception as e:
                ok = repr(e)
            got = json.load(open(p, encoding="utf-8"))
            check(f"закладки (ж): path не строка ({name}) — не падает, закладка владельца на месте, свои добавлены",
                  ok is True and got["items"][0]["path"] == bad and "Доска/Пульт.base" in paths(got)
                  and "Доска/Сводка.md" not in paths(got) and all(isinstance(x, str) for x in st["bookmarks_seen"]), ok)
            sp = os.path.join(tmp, "state-" + name, "board.json")
            pan = os.path.join(tmp, "pan-" + name)
            os.makedirs(pan)
            try:
                T.board_sync(pan, os.path.join(v, "Доска"), sp, os.path.join(tmp, "log"), T0 + 40, alert=al)
                ok = os.path.exists(sp)
            except Exception as e:
                ok = repr(e)
            check(f"закладки (ж): board_sync с path не строкой ({name}) доходит до записи board.json", ok is True, ok)
        # запись bookmarks.json падает: seen не обновился, тревога одна, следующий тик досыпает
        v, p = vault("w")
        st = {}
        alerts.clear()
        real = T._write_plain

        def boom(path, text):
            raise OSError("диск полон")
        T._write_plain = boom
        try:
            T._sync_bookmarks(v, st, al)
        finally:
            T._write_plain = real
        check("закладки (з): запись упала — bookmarks_seen не обновлён, файла нет, тревога одна",
              "bookmarks_seen" not in st and not os.path.exists(p) and len(alerts) == 1 and alerts[0][0] == "board-bookmarks", (st, alerts))
        T._sync_bookmarks(v, st, al)
        check("закладки (з): следующий тик после сбоя досыпает все закладки",
              paths(json.load(open(p, encoding="utf-8"))) == want_paths and sorted(st["bookmarks_seen"]) == sorted(want_paths))
        # одиночный суррогат в названии закладки (половина эмодзи из JSON.stringify): не кодируется в utf-8
        for kind in ("bookmarks", "types"):
            v, p = vault("sur-" + kind, json.dumps({"items": [{"type": "file", "ctime": 1, "path": "Чужая.md",
                                                           "title": "Обрезанный \ud83d"}]}) if kind == "bookmarks" else None)
            if kind == "types":
                with open(os.path.join(v, ".obsidian", "types.json"), "w", encoding="utf-8") as fh:
                    fh.write(json.dumps({"types": {"чужое": "text", "k\ud83d": "text"}}))
            alerts.clear()
            st = {}
            try:
                if kind == "bookmarks":
                    T._sync_bookmarks(v, st, al)
                else:
                    T._sync_types(v, al)
                ok = True
            except Exception as e:
                ok = repr(e)
            left = [x for x in os.listdir(os.path.join(v, ".obsidian")) if x.endswith(".tmp")]
            check(f"закладки (и): суррогат ({kind}) — не падает, tmp не остаётся, тревога есть",
                  ok is True and not left and len(alerts) == 1 and alerts[0][0] == "board-" + kind, (ok, left, alerts))
            if kind == "bookmarks":
                check("закладки (и): суррогат — bookmarks_seen не обновлён", "bookmarks_seen" not in st, st)
        # board_sync с суррогатом доходит до записи board.json
        v, p = vault("sur-bs", json.dumps({"items": [{"type": "file", "ctime": 1, "path": "Чужая.md", "title": "О \ud83d"}]}))
        sp = os.path.join(tmp, "state-sur", "board.json")
        pan = os.path.join(tmp, "pan-sur")
        os.makedirs(pan)
        try:
            T.board_sync(pan, os.path.join(v, "Доска"), sp, os.path.join(tmp, "log"), T0 + 50, alert=al)
            ok = os.path.exists(sp)
        except Exception as e:
            ok = repr(e)
        check("закладки (и): board_sync с суррогатом доходит до записи board.json", ok is True, ok)
    finally:
        shutil.rmtree(tmp, True)


def main():
    bookmark_checks()
    base_checks()
    card_checks()
    summary_checks()
    warn_checks()
    snippet_checks()
    print(f"{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
