#!/usr/bin/env python3
"""Хвосты ревью #128 к карточке пачки (metis-0457): звено в inbox «ждёт» прошлое, как todo; выноски «Параллельно» и
«Пересечения по файлам» — ссылки на карточки, а не голые id; «Области не указаны» — текстовое свойство Obsidian.
Плюс литералы режима в формулах видов (metis-0510): каждое значение `note["Режим"] == "…"` в Доска.base и Пульт.base —
одно из значений MODES, иначе вид молча не находит задачи после переименования режима.

Запуск: python3 -I plugins/pantheon/tests/test_story_callouts.py  (код выхода 0 — все прошли)
"""
import os
import re
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
    tasks = {"s-1": ("", {"type": "story", "id": "s-1", "title": "Пачка", "status": "todo"}, "")}
    for h in (H("t-1", order=1, mode="single", touches=["a/x.py"]),
              H("t-2", order=2, mode="single", touches=["a/"], status="inbox"),
              H("t-3", order=3, mode="parallel", touches=["b/"]),
              H("t-4", order=4, mode="parallel")):
        tasks[h["id"]] = ("", h, "")
    return tasks, {i: f"{i} Задача {i}" for i in tasks}


tasks, names = world()
c, body = T.render_story_card(tasks["s-1"][1], "", "x.md", T0, tasks, names=names)
L = lambda i: f"[[{names[i]}|{i}]]"  # noqa: E731
row = next(r for r in body.splitlines() if r.startswith("| ") and "|t-2]]" in r)
last = [x.strip() for x in row.strip("|").split(" | ")][-1]
check("«Состав»: звено в inbox после открытого ждёт прошлое (как todo)", "t-1" in last and "[[" in last, row)
tasks["t-2"][1]["status"] = "doing"
row2 = next(r for r in T.render_story_card(tasks["s-1"][1], "", "x.md", T0, tasks, names=names)[1].splitlines()
            if r.startswith("| ") and "|t-2]]" in r)
check("«Состав»: контроль — звено в doing не ждёт", "t-1" not in [x.strip() for x in row2.strip("|").split(" | ")][-1], row2)
par = next((x for x in body.splitlines() if x.startswith("> **Параллельно:**")), "")
check("выноска «Параллельно» — ссылки на карточки, не голые id",
      par == f"> **Параллельно:** {L('t-3')}, {L('t-4')}", par)
crs = next((x for x in body.splitlines() if x.startswith("> **Пересечения по файлам:**")), "")
check("выноска «Пересечения по файлам» — ссылки на обе задачи", crs.startswith(f"> **Пересечения по файлам:** {L('t-1')} и {L('t-2')}:")
      and not re.search(r"(?<![|\w-])t-\d(?![\w\]-])", crs.split(":", 1)[1].replace(L("t-1"), "").replace(L("t-2"), "")), crs)
na = next((x for x in body.splitlines() if x.startswith("> **Области не указаны:**")), "")
check("«Области не указаны» — выноска «у N из M» и свойство того же текста", na == "> **Области не указаны:** у 1 из 4"
      and c["Области не указаны"] == "у 1 из 4", (na, c.get("Области не указаны")))
check("«Области не указаны» — текстовое свойство в types.json (не список)", T.PROP_TYPES.get("Области не указаны") == "text")
check("свойства-ссылки пачки — списки", all(T.PROP_TYPES.get(k) == "multitext" for k in ("Цепочка", "Параллельно", "Пересечения")))

# metis-0510: литералы режима в формулах видов — из MODES
lits = {name: set(re.findall(r'note\["Режим"\]\s*==\s*"([^"]*)"', text)) for name, text in
        (("Доска.base", T.BASE_FILE), ("Пульт.base", T.PULT_FILE))}
modes = set(T.MODES.values())
check("литералы `note[\"Режим\"] == …` в Доска.base и Пульт.base есть (проверка не пустая)",
      all(lits.values()), lits)
check("каждый литерал режима в формулах видов — значение MODES", all(v <= modes for v in lits.values()),
      {k: sorted(v - modes) for k, v in lits.items()})

print(f"{sum(results)} из {len(results)}")
sys.exit(0 if all(results) else 1)
