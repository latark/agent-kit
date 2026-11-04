#!/usr/bin/env python3
"""Доска в шаг с данными (metis-0799…0803): PR пачки с ветки batch/<id> без поля pr, задачи вне состава, закрытые PR
пачки; «оценок нет» вместо «0 %»; одно определение «Нужен ответ» для Пульта, доски и board-auto и вопросы внутри
пачки; parent не на пачку; пачка пачек по составу.

Запуск: python3 -I plugins/pantheon/tests/test_board_sync.py  (код выхода 0 — все прошли)
"""
import atexit
import importlib.util
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="board-sync-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402
import autoclose as A  # noqa: E402

spec = importlib.util.spec_from_file_location("boardtext", os.path.join(LIB, "boardtext.py"))
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)

T0 = 1_792_000_000
R = "latark/agent-kit"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:900]}]"))


def H(i, **kw):
    h = {"type": "task", "id": i, "title": f"Задача {i}", "status": "todo", "priority": 2, "direction": "metis-pantheon"}
    h.update(kw)
    return h


def store(*heads):
    return {h["id"]: ("", h, "") for h in heads}


def card(sid, tasks, **kw):
    names = {i: f"{i} x" for i in tasks}
    return T.render_story_card(tasks[sid][1], tasks[sid][2], "x.md", T0, tasks, names=names, **kw)


# --- metis-0799: PR пачки по ветке batch/<id>; задачи вне состава ------------------------------------------------
tasks = store(H("metis-0750", type="story", title="Пачка П5", status="doing"),
              H("metis-0688", parent="metis-0750", status="done", mode="single"),
              H("metis-0689", parent="metis-0750", mode="single"),
              H("metis-0773", parent="metis-0749", status="done", mode="single"),
              H("metis-0780", status="done"))
cache = {"merged": {R: [{"number": 294, "headRefName": "batch/metis-0750", "body": "Closes metis-0688, metis-0773 и 0780",
                         "mergedAt": "2026-11-04T04:24:00Z", "oid": "a" * 40},
                        {"number": 250, "headRefName": "metis-0750-old", "body": "", "oid": "b" * 40}]},
         "open_prs": {R: [{"number": 300, "branch": "batch/metis-0751", "closes": ["metis-0751"], "part": False}]}}
idx = A.pr_index(cache)
check("0799: pr_index хранит ветку PR (слитый — headRefName, открытый — branch)",
      idx["metis-0750"][0]["branch"] == "batch/metis-0750" and idx["metis-0751"][0]["branch"] == "batch/metis-0751", idx)
bp = T.batch_pr("metis-0750", idx, [R])
check("0799: batch_pr — PR с ветки batch/<id>, слит, закрытые им задачи без самой пачки; ветка metis-0750-old — не PR пачки",
      bp == (R, 294, True, ["metis-0688", "metis-0773", "metis-0780"]), bp)
check("0799: batch_pr — репозиторий не направления пачки не берём", T.batch_pr("metis-0750", idx, ["latark/other"]) is None)
check("0799: batch_pr — открытый PR пачки (ветка из open_prs)", T.batch_pr("metis-0751", idx, None)[:3] == (R, 300, False))
idx2 = A.pr_index({"merged": cache["merged"], "open_prs": {R: [{"number": 310, "branch": "batch/metis-0750",
                                                                "closes": ["metis-0750"], "part": False}]}})
check("0799: batch_pr — открытый PR пачки важнее слитого", T.batch_pr("metis-0750", idx2, [R])[:3] == (R, 310, False))
check("0799: batch_pr — пустой и битый индекс без трассировки",
      T.batch_pr("metis-0750", None) is None and T.batch_pr("metis-0750", {"x": [5, {"branch": "batch/metis-0750"}]}) is None)
c, body = card("metis-0750", tasks, batch_pr=bp)
check("0799: карточка пачки без поля pr — «PR пачки» по ветке batch/<id>, ветка и «слит»",
      c["PR пачки"] == f"https://github.com/{R}/pull/294" and c["Ветка"] == "batch/metis-0750"
      and f"**PR пачки:** [PR #294](https://github.com/{R}/pull/294) · {R} · слит" in body, (c.get("PR пачки"), body[:600]))
check("0799: «Вне состава» — задачи, закрытые PR пачки, с другим parent или без него; свои — нет",
      c["Вне состава"] == ["[[metis-0773 x|metis-0773]]", "[[metis-0780 x|metis-0780]]"]
      and "PR пачки закрыл и задачи вне её состава" in body and "metis-0688 x|metis-0688]], [[" not in body, c.get("Вне состава"))
check("0799: «Закрыто» — по составу (parent): 1 из 2", c["Закрыто"] == "1 из 2", c["Закрыто"])
c0, b0 = card("metis-0750", tasks)
check("0799: без PR по ветке — ни «PR пачки», ни «Вне состава»", c0["PR пачки"] is None and c0["Вне состава"] is None
      and "вне её состава" not in b0, c0)
tasks["metis-0750"][1]["pr"] = f"{R}#999"
c1, _ = card("metis-0750", tasks, batch_pr=bp)
check("0799: поле pr важнее ветки; PR по ветке с другим номером не смешивается (нет «Вне состава»)",
      c1["PR пачки"] == f"https://github.com/{R}/pull/999" and c1["Вне состава"] is None, c1)
del tasks["metis-0750"][1]["pr"]
check("0799: «Вне состава» — свойство карточки (порядок и тип Obsidian)",
      "Вне состава" in T.CARD_ORDER and T.PROP_TYPES.get("Вне состава") == "multitext")
cp = os.path.join(ROOT, "prs.json")
with open(cp, "w", encoding="utf-8") as fh:
    json.dump(cache, fh)
check("0799: board-auto — номер PR пачки по ветке batch/<id> из кэша (слитый и открытый)",
      B.batch_branch_prs(cp) == {"metis-0750": 294, "metis-0751": 300}, B.batch_branch_prs(cp))
bt = B.batches(store(H("metis-0750", type="story", status="doing"), H("metis-0689", parent="metis-0750", status="doing")),
               B.batch_branch_prs(cp))
check("0799: board-auto — пачка без поля pr получает номер PR с ветки", bt and bt[0][4] == 294, bt)
check("0799: board-auto — кэша нет или битый: {}", B.batch_branch_prs(os.path.join(ROOT, "нет.json")) == {})

print(f"{sum(results)} из {len(results)}")
sys.exit(0 if all(results) else 1)
