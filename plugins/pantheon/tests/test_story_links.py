#!/usr/bin/env python3
"""Карточка пачки в Obsidian (metis-0322): «Цепочка», «Параллельно», «Пересечения» и «Зависит от» — щёлкаемые ссылки
[[имя карточки|id]], «Области не указаны» — «у N из M», «Режим» и «Ждёт» в «Составе» не пустые («ничего»), пачка пачек
считает и детей-пачки.

Запуск: python3 -I plugins/pantheon/tests/test_story_links.py  (код выхода 0 — все прошли)
"""
import os
import sys

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

T0 = 1_792_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def H(i, **kw):
    h = {"type": "task", "id": i, "title": f"Задача {i}", "status": "todo", "parent": "s-1", "priority": 2}
    h.update(kw)
    return h


def world():
    tasks = {"s-1": ("", {"type": "story", "id": "s-1", "title": "Пачка", "status": "todo", "estimate": "1 % недели"}, ""),
             "s-0": ("", {"type": "story", "id": "s-0", "title": "Пачка пачек", "status": "todo"}, "")}
    for h in (H("t-1", order=1, mode="single", touches=["a/x.py"]),
              H("t-2", order=2, mode="single", touches=["a/"]),
              H("t-3", order=3, mode="parallel", depends_on=["t-9"]),
              H("t-4", order=4, mode="parallel"),
              H("t-5", order=5, status="done", mode="self"),
              H("t-6", order=6)):
        tasks[h["id"]] = ("", h, "")
    names = {i: f"{i} Задача {i}" for i in tasks}
    return tasks, names


def card(sid, tasks, names):
    return T.render_story_card(tasks[sid][1], tasks[sid][2], "x.md", T0, tasks, names=names)


tasks, names = world()
c, body = card("s-1", tasks, names)
L = lambda i: f"[[{names[i]}|{i}]]"  # noqa: E731
check("Цепочка — список ссылок на карточки в порядке пачки", c["Цепочка"] == [L(i) for i in ("t-1", "t-2", "t-5", "t-6")],
      c.get("Цепочка"))
check("Параллельно — список ссылок", c["Параллельно"] == [L("t-3"), L("t-4")], c.get("Параллельно"))
check("Пересечения — ссылки на обе задачи и область",
      c["Пересечения"] == [f"{L('t-1')} и {L('t-2')}: a"], c.get("Пересечения"))
check("Области не указаны — «у N из M», а не дубль состава", c["Области не указаны"] == "у 4 из 6", c.get("Области не указаны"))
tasks2, names2 = world()
for i in ("t-3", "t-4", "t-5", "t-6"):
    tasks2[i][1]["touches"] = [f"z/{i}"]
check("все области указаны — поля нет", card("s-1", tasks2, names2)[0]["Области не указаны"] is None)
rows = [r for r in body.splitlines() if r.startswith("| ") and "t-" in r]
cell = lambda r, n: [x.strip() for x in r.strip("|").split(" | ")][n]  # noqa: E731
check("в «Составе» нет пустых «Режим» и «Ждёт» («—»)", rows and all(cell(r, 5) != "—" and cell(r, 6) != "—" for r in rows),
      rows)
check("«Ждёт»: у первого звена «ничего»", cell(rows[0], 6) == "ничего", rows[0])
check("«Ждёт»: у второго звена прошлое звено цепочки ссылкой", "t-1" in cell(rows[1], 6) and "[[" in cell(rows[1], 6), rows[1])
check("«Ждёт»: открытый depends_on", "t-9" in cell(rows[2], 6), rows[2])
check("«Ждёт»: звено после закрытого ждёт ближайшее НЕзакрытое (t-2)", "t-2" in cell(rows[5], 6) and "t-5" not in cell(rows[5], 6), rows[5])
tasks4, names4 = world()
for i in ("t-1", "t-2"):
    tasks4[i][1]["status"] = "done"
_, body4 = card("s-1", tasks4, names4)
rows4 = [r for r in body4.splitlines() if r.startswith("| ") and "t-" in r]
check("«Ждёт»: все прошлые звенья закрыты — «ничего»", cell(rows4[5], 6) == "ничего", rows4[5])
tasks5, names5 = world()
tasks5["t-6"][1]["status"] = "doing"
_, body5 = card("s-1", tasks5, names5)
rows5 = [r for r in body5.splitlines() if r.startswith("| ") and "t-" in r]
check("«Ждёт»: начатое звено (doing) не ждёт прошлых", cell(rows5[5], 6) == "ничего", rows5[5])
check("тип свойства «Цепочка» — multitext", T.PROP_TYPES.get("Цепочка") == "multitext", T.PROP_TYPES.get("Цепочка"))
check("«Режим» без mode — «не задан», а не «—»", cell(rows[5], 5) == "не задан", rows[5])
check("ссылки в таблице экранируют «|»", f"[[{names['t-1']}\\|t-1]]" in body, body[-600:])

# пачка пачек: дети — stories с parent или batch = её id
tasks3, names3 = world()
tasks3["s-1"][1]["parent"] = "s-0"
tasks3["s-2"] = ("", {"type": "story", "id": "s-2", "title": "Вторая", "status": "done", "batch": "s-0"}, "")
names3 = {i: f"{i} x" for i in tasks3}
c0, b0 = card("s-0", tasks3, names3)
check("пачка пачек: «Закрыто» считает детей-пачки (не 0 из 0)", c0["Закрыто"] == "1 из 2", c0.get("Закрыто"))
check("пачка пачек: дети-пачки в «Составе»", "s-1" in b0 and "s-2" in b0, b0[-400:])
check("пачка пачек: «Области не указаны» не считает пачки", c0["Области не указаны"] is None, c0.get("Области не указаны"))
tasks3["t-7"] = ("", H("t-7", parent="s-0", mode="self"), "")
names3["t-7"] = "t-7 x"
check("пачка с задачей и детьми-пачками: «у 1 из 1», пачки в M не входят",
      card("s-0", tasks3, names3)[0]["Области не указаны"] == "у 1 из 1")

# выжившие мутанты ревью 128 (п. 2): по проверке на каждый
tasks4, names4 = world()
tasks4["t-2"][1]["depends_on"] = ["t-1"]  # depends_on совпадает с прошлым звеном цепочки
rows4 = [r for r in card("s-1", tasks4, names4)[1].splitlines() if r.startswith("| ") and "t-" in r]
check("«Ждёт»: depends_on = прошлому звену — ссылка один раз", cell(rows4[1], 6).count("|t-1]]") == 1, rows4[1])
check("«Ждёт»: у закрытой задачи после открытого звена — «ничего»", cell(rows[4], 6) == "ничего", rows[4])
rows0 = [r for r in b0.splitlines() if r.startswith("| ") and "s-" in r]
check("«Режим» у пачки без mode — «—»", rows0 and all(cell(r, 5) == "—" for r in rows0), rows0)
tasks3["s-9"] = ("", {"type": "story", "id": "s-9", "title": "Сама себе", "status": "todo", "parent": "s-9"}, "")
names3["s-9"] = "s-9 x"
check("пачка с parent = своему id не входит в свой состав", "s-9" not in card("s-9", tasks3, names3)[1].split("## Состав")[-1])

# review 128b п.1: звено, которое уже идёт, не «ждёт» прошлое открытое звено
tasks5, names5 = world()
tasks5["t-3"][1].pop("depends_on")
for i, st in (("t-2", "review"), ("t-3", "doing"), ("t-4", "waiting")):
    tasks5[i][1]["status"] = st
    tasks5[i][1]["mode"] = "single"
tasks5["t-6"][1]["status"] = "todo"
tasks5["t-6"][1]["order"] = 5
tasks5["t-5"][1]["order"] = 9
tasks5["t-8"] = ("", H("t-8", order=6, status=""), "")
names5["t-8"] = "t-8 x"
rows5 = {cell(r, 1).split("|")[-1].rstrip("]"): r for r in card("s-1", tasks5, names5)[1].splitlines() if r.startswith("| ") and "t-" in r}
check("«Ждёт»: звено в review после открытого — «ничего»", cell(rows5["t-2"], 6) == "ничего", rows5["t-2"])
check("«Ждёт»: звено в doing после открытого — «ничего»", cell(rows5["t-3"], 6) == "ничего", rows5["t-3"])
check("«Ждёт»: звено в waiting после открытого — «ничего»", cell(rows5["t-4"], 6) == "ничего", rows5["t-4"])
check("«Ждёт»: не начатое звено со status todo ждёт прошлое", "[[" in cell(rows5["t-6"], 6), rows5["t-6"])
check("«Ждёт»: не начатое звено с пустым status ждёт прошлое", "[[" in cell(rows5["t-8"], 6), rows5["t-8"])
tasks5["t-3"][1]["depends_on"] = ["t-1"]
r3 = [r for r in card("s-1", tasks5, names5)[1].splitlines() if r.startswith("| ") and "[[t-3 " in r][0]
check("«Ждёт»: звено в doing с открытым depends_on — ссылка на него", "t-1" in cell(r3, 6), r3)

# review 128b п.2: мутанты
tasks6, names6 = world()
tasks6["t-7"] = ("", H("t-7", parent="s-1", batch="s-0"), "")  # задача (не пачка) со старым полем batch
check("story_children: задача с batch = id пачки не входит в её состав без parent",
      "t-7" not in T.story_children("s-0", tasks6), T.story_children("s-0", tasks6))
summary = [x for x in card("s-1", tasks, names)[1].splitlines() if "Цепочка одному исполнителю" in x]
check("сводка «Цепочка одному исполнителю» — ссылки, а не голые id",
      summary and summary[0].count("[[") == 4 and L("t-1") in summary[0], summary)

# карточки задач: «Зависит от», «Пересечения» — ссылки
cross = T.crossings(tasks)
ctx = T.card_ctx("t-3", tasks["t-3"][1], tasks, names, cross)
check("задача: «Зависит от» без карточки — голый id", ctx["waits"] == ["t-9"], ctx["waits"])
ctx = T.card_ctx("t-1", tasks["t-1"][1], tasks, names, cross)
check("задача: «Пересечения» — ссылка [[имя|id]]", ctx["cross"] == [L("t-2")], ctx["cross"])
tasks["t-2"][1]["depends_on"] = ["t-1"]
ctx = T.card_ctx("t-2", tasks["t-2"][1], tasks, names, cross)
check("задача: «Зависит от» с карточкой — ссылка", ctx["waits"] == [L("t-1")], ctx["waits"])

print(f"{sum(results)} из {len(results)}")
sys.exit(0 if all(results) else 1)
