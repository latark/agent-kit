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
import subprocess  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402 — pantheon.batch_outside только на Python 3.11+

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
                         "mergedAt": "2026-11-04T04:24:00Z", "oid": "a" * 40, "cross": False},
                        {"number": 250, "headRefName": "metis-0750-old", "body": "", "oid": "b" * 40, "cross": False},
                        {"number": 296, "headRefName": "batch/metis-0750", "body": "Closes metis-0689", "oid": "c" * 40,
                         "cross": True},
                        {"number": 297, "headRefName": "batch/metis-0750", "body": "Closes metis-0689", "oid": "d" * 40}]},
         "open_prs": {R: [{"number": 300, "branch": "batch/metis-0751", "closes": ["metis-0751"], "part": False,
                           "cross": False},
                          {"number": 305, "branch": "batch/metis-0750", "closes": ["metis-0750"], "part": False,
                           "cross": True}]}}
idx = A.pr_index(cache)
check("0799: pr_index хранит ветку PR (слитый — headRefName, открытый — branch)",
      idx["metis-0750"][0]["branch"] == "batch/metis-0750" and idx["metis-0751"][0]["branch"] == "batch/metis-0751", idx)
bprs = A.batch_prs(cache)
bp = T.batch_pr("metis-0750", bprs, [R])
check("0799: batch_pr — PR с ветки batch/<id>, слит, закрытые им задачи без самой пачки; ветка metis-0750-old — не PR пачки",
      bp == (R, 294, True, ["metis-0688", "metis-0773", "metis-0780"]), bp)
check("0799: PR из форка (cross) и строка кэша без cross — ветки в pr_index нет, ссылка на PR остаётся",
      [x["branch"] for x in idx["metis-0689"]] == ["", ""] and [x["number"] for x in idx["metis-0689"]] == [296, 297],
      idx.get("metis-0689"))
check("0799: batch_pr — репозиторий не направления пачки не берём", T.batch_pr("metis-0750", bprs, ["latark/other"]) is None)
check("0799: batch_pr — открытый PR пачки (ветка из open_prs)", T.batch_pr("metis-0751", bprs, None)[:3] == (R, 300, False))
bprs2 = A.batch_prs({"merged": cache["merged"], "open_prs": {R: [{"number": 310, "branch": "batch/metis-0750",
                                                                  "closes": ["metis-0750"], "part": False, "cross": False}]}})
check("0799: batch_pr — открытый PR пачки важнее слитого", T.batch_pr("metis-0750", bprs2, [R])[:3] == (R, 310, False))
check("0799: batch_pr — пустой и битый индекс без трассировки",
      T.batch_pr("metis-0750", None) is None and T.batch_pr("metis-0750", {"metis-0750": [5, ("x",), None]}) is None
      and T.batch_pr("metis-0750", {"metis-0750": 5}) is None and T.batch_pr("metis-0750", [1]) is None)
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
check("0799: board-auto — номер PR пачки по ветке batch/<id> из кэша (слитый и открытый); форк и строка без cross — нет",
      B.batch_branch_prs(cp) == {"metis-0750": 294, "metis-0751": 300}, B.batch_branch_prs(cp))
bt = B.batches(store(H("metis-0750", type="story", status="doing"), H("metis-0689", parent="metis-0750", status="doing")),
               B.batch_branch_prs(cp))
check("0799: board-auto — пачка без поля pr получает номер PR с ветки", bt and bt[0][4] == 294, bt)
check("0799: board-auto — кэша нет или битый: {}", B.batch_branch_prs(os.path.join(ROOT, "нет.json")) == {})

# --- metis-0800: «оценок нет» вместо «0 %»; подпись вида «Пачки» ------------------------------------------------
tk = store(H("s-1", type="story", title="П", status="doing"), H("t-1", parent="s-1", status="done", mode="single"),
           H("t-2", parent="s-1", mode="single"))
c, body = card("s-1", tk)
check("0800: у детей нет оценок — «Сумма оценок» «оценок нет», а не «0 %»; и в сводке карточки",
      c["Сумма оценок"] == "оценок нет" and "**Пачка:** оценок нет" in body and "0 %" not in body, (c["Сумма оценок"], body[:200]))
check("0800: task show пачки без оценок — «оценок нет»", "оценок нет" in T.story_text("s-1", tk) and "сумма 0 %"
      not in T.story_text("s-1", tk), T.story_text("s-1", tk))
tk["t-2"][1]["estimate"] = "0 % недели"
c, body = card("s-1", tk)
check("0800: оценка есть хоть у одного (даже 0 %) — число", c["Сумма оценок"] == "0 %" and "сумма оценок 0 %" in body,
      c["Сумма оценок"])
tk["t-1"][1]["estimate"] = "1,5 % недели"
check("0800: сумма оценок считается как прежде", card("s-1", tk)[0]["Сумма оценок"] == "1,5 %")
check("0800: пачка без детей — «оценок нет»", card("s-9", store(H("s-9", type="story")))[0]["Сумма оценок"] == "оценок нет")
for base, nm in ((T.PULT_FILE, "Пульт"), (T.BASE_FILE, "Доска")):
    check(f"0800: {nm}.base — колонка суммы подписана как оценки против бюджета, не прогресс",
          "formula.sum_budget:\n    displayName: Оценки / бюджет (не прогресс)" in base, base[:0])

# --- metis-0801: одно определение «Нужен ответ»; вопросы внутри пачки ------------------------------------------------
W = dict(status="waiting", waiting_on="human")
qa = store(H("athena-0075", type="story", status="doing", direction="athena-proja"),
           H("athena-0120", parent="athena-0075", mode="single", **W),
           H("athena-0121", parent="athena-0075", mode="single", **W),
           H("athena-0123", type="story", parent="athena-0075", status="todo"),
           H("athena-0122", parent="athena-0123", mode="single", **W),
           H("athena-0124", parent="athena-0075", mode="single", status="waiting", waiting_on="metis-0001"),
           H("athena-0125", parent="athena-0075", mode="single", status="todo", question="Какой вариант?"),
           H("athena-0126", parent="athena-0075", mode="single", status="done", waiting_on="human"))
check("0801: needs_answer — waiting и waiting_on human, и только они",
      [i for i in sorted(qa) if T.needs_answer(qa[i][1])] == ["athena-0120", "athena-0121", "athena-0122"])
check("0801: board-auto (boardtext.needs_answer) — то же определение, что у доски",
      all(B.needs_answer(qa[i][1]) == T.needs_answer(qa[i][1]) for i in qa))
check("0801: колонка «Нужен ответ» доски — по needs_answer",
      [i for i in sorted(qa) if T.label_of(qa[i][1]) == T.HUMAN_WAIT] == ["athena-0120", "athena-0121", "athena-0122"])
c, body = card("athena-0075", qa)
check("0801: «Вопросов» пачки — вопросы внутри неё, с вложенной пачкой (athena-0075 → 3); в сводке — список",
      c["Вопросов"] == 3 and "**Нужен ответ владельца внутри пачки:** 3 — [[athena-0120 x|athena-0120]], "
      "[[athena-0121 x|athena-0121]], [[athena-0122 x|athena-0122]]" in body, (c.get("Вопросов"), body[:900]))
check("0801: пачка без вопросов — «Вопросов» нет", card("athena-0123", store(H("athena-0123", type="story")))[0]["Вопросов"] is None)
check("0801: «Вопросов» — число в свойствах и в виде «Пачки» обеих баз",
      T.PROP_TYPES.get("Вопросов") == "number" and "Вопросов" in T.CARD_ORDER
      and "note.Вопросов" in T.PULT_FILE and "note.Вопросов" in T.BASE_FILE)
qa["athena-0075"][1].update(W)
pc = T.project_counts(qa, T0, ["athena-proja", "metis-pantheon"])
check("0801: «Ждёт вас» заметки проекта = колонка «Нужен ответ», пачки тоже (3 задачи + пачка = 4)", pc["Ждёт вас"] == 4, pc)
check("0801: на Пульте колонка «Ждёт вас» подписана «Нужен ответ»", "note.Ждёт вас:\n    displayName: Нужен ответ" in T.PULT_FILE)
oc = B.owner_cards(qa, lambda h: False)
check("0801: board-auto «Ждёт вас» — все карточки «Нужен ответ» при любом «Кому» (пачка тоже)",
      oc["ask"] == ["athena-0075", "athena-0120", "athena-0121", "athena-0122"] and oc["do"] == [], oc)

# --- metis-0802: parent — только пачка ----------------------------------------------------------------------------
PH = os.path.join(ROOT, "pantheon")
os.makedirs(os.path.join(PH, "directions", "metis-pantheon", "tasks"))
sid, _ = T.task_new(PH, T0, "metis-pantheon", "Пачка", kind="story")
plain, _ = T.task_new(PH, T0, "metis-pantheon", "Обычная задача")


def refused(fn):
    try:
        fn()
    except ValueError as e:
        return str(e)
    return None


err = refused(lambda: T.task_new(PH, T0, "metis-pantheon", "Ребёнок задачи", parent=plain, mode="single"))
check("0802: task new с parent на обычную задачу — отказ с понятным текстом, файла нет",
      err and f"parent {plain} — не пачка (type task)" in err
      and len(T.load_tasks(PH, T.WORK_TYPES)) == 2, err)
err = refused(lambda: T.task_new(PH, T0, "metis-pantheon", "Ребёнок пустоты", parent="metis-9999", mode="single"))
check("0802: task new с parent на несуществующий id — отказ", err and "нет такой пачки" in err, err)
kid, _ = T.task_new(PH, T0, "metis-pantheon", "Ребёнок пачки", parent=sid, mode="single")
check("0802: task new с parent на пачку — как прежде", T.load_tasks(PH, T.WORK_TYPES)[kid][1].get("parent") == sid)
err = refused(lambda: T.task_set(PH, T0, kid, {"parent": plain}))
check("0802: task set parent= на обычную задачу — отказ, parent прежний",
      err and "не пачка" in err and T.load_tasks(PH, T.WORK_TYPES)[kid][1].get("parent") == sid, err)
err = refused(lambda: T.task_set(PH, T0, kid, {"parent": kid}))
check("0802: task set parent= на саму себя — отказ", err and "сама карточка" in err, err)
T.task_set(PH, T0, kid, {"parent": None})
check("0802: task set parent= (пусто) — открепить можно", not T.load_tasks(PH, T.WORK_TYPES)[kid][1].get("parent"))
goal, _ = T.task_new(PH, T0, "metis-pantheon", "Пачка пачек", kind="story")
T.task_set(PH, T0, sid, {"parent": goal, "mode": "single"})
check("0802: parent пачки на пачку (пачка пачек) — можно", T.load_tasks(PH, T.WORK_TYPES)[sid][1].get("parent") == goal)
bad = store(H("metis-0194"), H("metis-0199", parent="metis-0194"), H("metis-0211", parent="metis-0006"),
            H("metis-0212", parent="metis-0194", status="done"), H("metis-0300", type="story"),
            H("metis-0301", parent="metis-0300", mode="single"))
for i, (pp, h, b0) in bad.items():
    bad[i] = (pp, dict(h, closed="2026-11-01") if h.get("status") == "done" else h, b0)
w = [x for x in T.board_problems(bad, T0)[1] if "не пачка" in x[1] or "нет такой пачки" in x[1]]
check("0802: check — открытые карточки с parent не на пачку и на несуществующий id; закрытые и в пачке — нет",
      [x[0] for x in w] == ["metis-0199", "metis-0211"] and "pantheon task attach metis-0199" in w[0][1], w)
T.task_set(PH, T0, plain, {"parent": None, "status": "doing"})
raw = T.load_tasks(PH, T.WORK_TYPES)[kid][0]
with open(raw, encoding="utf-8") as fh:
    txt = fh.read()
with open(raw, "w", encoding="utf-8") as fh:
    fh.write(txt.replace("type: task\n", f"type: task\nparent: {plain}\n", 1))
T.task_set(PH, T0, kid, {"status": "doing"})
check("0802: прежний неверный parent другим правкам не мешает (его показывает check)",
      T.load_tasks(PH, T.WORK_TYPES)[kid][1].get("status") == "doing")
rest, _ = T.task_split(PH, T0, kid, "Остаток", done_when=["пункт"])
check("0802: остаток задачи с неверным parent — без parent (не переносим ошибку)",
      not T.load_tasks(PH, T.WORK_TYPES)[rest][1].get("parent"))

# --- metis-0826: board_sync целиком - «PR #N слит ДД.ММ» во «Внимании» карточки и раздел «Слито, ждёт приёмки» в Сводке --------
P8 = os.path.join(ROOT, "pan8")
for d in ("directions/metis-pantheon/tasks", "inbox/tasks"):
    os.makedirs(os.path.join(P8, d))
tid8, _ = T.task_new(P8, T0, "metis-pantheon", "Слитая задача", done_when=["а", "б"], created_note=None)
T.task_set(P8, T0 + 1, tid8, {"status": "review"}, note="PR #77 слит")
cache8 = {"merged": {R: [{"number": 77, "headRefName": "x-" + tid8, "body": f"Closes {tid8}", "oid": "e" * 40, "cross": False,
                          "mergedAt": "2026-11-03T10:00:00Z"}]}}
idx8 = A.pr_index(cache8)
board8 = os.path.join(ROOT, "view8", "Доска")
T.board_sync(P8, board8, os.path.join(ROOT, "st8.json"), os.path.join(ROOT, "log8"), T0 + 5, pr_index=idx8,
             repos={"metis-pantheon": [R]})
cards8 = [f for f in os.listdir(board8) if f.startswith(tid8)]
ctext = open(os.path.join(board8, cards8[0]), encoding="utf-8").read() if cards8 else ""
day8 = A.merged_day("2026-11-03T10:00:00Z")
check("0826: board_sync - карточка в review: «PR #77 слит ДД.ММ, ждёт пунктов Готово, когда: 2 из 2» с датой слияния",
      f"PR #77 слит {day8[8:10]}.{day8[5:7]}, ждёт пунктов Готово, когда: 2 из 2" in ctext, ctext[:900])
summ = open(os.path.join(board8, "Сводка.md"), encoding="utf-8").read()
check("0826: board_sync - Сводка: раздел «Слито, ждёт приёмки (1)» со ссылкой на карточку и счётчик",
      "## 🔵 Слито, ждёт приёмки (1)" in summ and "🔵 Слито, ждёт приёмки: 1" in summ and "PR #77 слит" in summ, summ[summ.find("Слито, ждёт приёмки (") - 40:][:400])
T.board_sync(P8, board8, os.path.join(ROOT, "st8b.json"), os.path.join(ROOT, "log8"), T0 + 9, pr_index={}, repos={"metis-pantheon": [R]})
check("0826: board_sync - без слитого PR в индексе раздела нет",
      "Слито, ждёт приёмки" not in open(os.path.join(board8, "Сводка.md"), encoding="utf-8").read())

# --- metis-0810: одно правило «PR пачки» для карточки (tasks.batch_pr), board-auto (boardtext.batch_branch_prs) и check
# (pantheon.batch_outside): ветка batch/<id>, не форк, номер > 0, «часть» — PR пачки без закрытых задач, репозитории
# направления пачки (own); открытый важнее слитого --------------------------------------------------------------------
RO, RB = "latark/other", "latark/ba"
tk10 = store(H("metis-0760", type="story", status="doing"),
             H("metis-0761", type="story", status="doing", direction="athena-proja"),
             H("metis-0762", parent="metis-0760", status="doing", mode="single"),
             H("metis-0763", status="done"), H("metis-0764", status="done"), H("metis-0765", status="done"),
             H("metis-0766", status="done"))


def mpr(n, branch, body, **kw):
    return dict({"number": n, "headRefName": branch, "body": body, "mergedAt": "2026-11-04T04:24:00Z", "oid": "f" * 40,
                 "cross": False}, **kw)


cache10 = {"merged": {R: [mpr(900, "batch/metis-0760", "Closes metis-0762"),
                          mpr(400, "batch/metis-0760", "Closes metis-0762, metis-0763"),
                          mpr(402, "batch/metis-0760", "Closes metis-0764\nчасть: остальное позже"),
                          mpr(403, "batch/metis-0760", "Closes metis-0765", cross=True),
                          {k: v for k, v in mpr(406, "batch/metis-0760", "Closes metis-0765").items() if k != "cross"},
                          mpr(True, "batch/metis-0760", "Closes metis-0765"), mpr(0, "batch/metis-0760", "Closes metis-0765"),
                          mpr(410, "batch/metis-0761", "Closes metis-0766")]},
           "open_prs": {R: [{"number": 401, "branch": "batch/metis-0760", "closes": ["metis-0760", "metis-0763"],
                             "part": False, "cross": False}],
                        RO: [{"number": 500, "branch": "batch/metis-0760", "closes": ["metis-0765"], "part": False,
                              "cross": False}]}}
repos10 = {"metis-pantheon": [R], "athena-proja": ["Latark/BA"]}
own10 = {sid: [r.lower() for r in repos10.get(tk10[sid][1]["direction"]) or []] for sid in ("metis-0760", "metis-0761")}
cp10 = os.path.join(ROOT, "prs10.json")
with open(cp10, "w", encoding="utf-8") as fh:
    json.dump(cache10, fh)
card10 = {sid: T.batch_pr(sid, A.batch_prs(cache10), own10[sid]) for sid in own10}
board10 = B.batch_branch_prs(cp10, lambda sid: own10.get(sid))
CHK = ("import json, sys; sys.path.insert(0, sys.argv[1]); import pantheon as p, tasks as T\n"
       "d = json.load(open(sys.argv[2], encoding='utf-8'))\n"
       "tk = {i: ('', h, '') for i, h in d['tasks'].items()}\n"
       "print(json.dumps(p.batch_outside(T, tk, d['cache'], d.get('repos'))))\n")


def outside_check(tasks_, cache_, repos_):
    f = os.path.join(ROOT, "chk10.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump({"tasks": {i: h for i, (_, h, _b) in tasks_.items()}, "cache": cache_, "repos": repos_}, fh)
    env10 = {"PATH": os.environ["PATH"], "HOME": ROOT, "PANTHEON_HOME": os.path.join(ROOT, "pan10"),
             "PANTHEON_STATE": os.path.join(ROOT, "st10"), "PANTHEON_VIEW": os.path.join(ROOT, "view10"), "TMPDIR": ROOT}
    r = subprocess.run([PY311, "-I", "-c", CHK, LIB, f], env=env10, capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else ("сбой", r.stderr[-600:])


chk10 = outside_check(tk10, cache10, repos10)
c10, _ = card("metis-0760", tk10, batch_pr=card10["metis-0760"])
check("0810: у пачки слитый (#900, больший номер) и открытый (#401) PR — открытый важнее: карточка и board-auto (мутант M11)",
      card10["metis-0760"][:3] == (R, 401, False) and board10.get("metis-0760") == 401, (card10, board10))
check("0810: одно правило — номер PR пачки у карточки и board-auto совпадает; репозиторий не направления (#500 latark/other, "
      "#410 у пачки athena) — ни там, ни там",
      {s: (card10[s] or (0, None))[1] for s in own10} == {s: board10.get(s) for s in own10} == {"metis-0760": 401,
                                                                                              "metis-0761": None},
      (card10, board10))
check("0810: одно правило — «вне состава» карточки и строки check совпадают: только metis-0763; «часть» (#402), форк "
      "(#403), строка без cross (#406), номер True и 0, чужой репозиторий (#500) задач не закрывают",
      isinstance(chk10, list) and sorted({x[0] for x in chk10}) == ["metis-0763"]
      and c10["Вне состава"] == ["[[metis-0763 x|metis-0763]]"] and all("latark/agent-kit#" in x[1] for x in chk10), (chk10, c10))
chk_any = outside_check(tk10, cache10, None)
check("0810: без [merge_repos] check берёт любые репозитории (как board-auto без own): тогда и #500 и #410",
      isinstance(chk_any, list) and sorted({x[0] for x in chk_any}) == ["metis-0763", "metis-0765", "metis-0766"], chk_any)
chk_norow = outside_check(tk10, cache10, {"metis-pantheon": [R]})
check("0810 (argus #341 Д1): у направления пачки нет строки в [merge_repos] — её PR из любых репозиториев (#410 athena), "
      "у пачки со строкой — только свои (#500 нет)",
      isinstance(chk_norow, list) and sorted({x[0] for x in chk_norow}) == ["metis-0763", "metis-0766"], chk_norow)
tk10["metis-0760"][1]["keep_outside"] = ["metis-0763"]
check("0810: решение координатора — keep_outside у пачки снимает предупреждение check о задаче",
      outside_check(tk10, cache10, repos10) == [], outside_check(tk10, cache10, repos10))
del tk10["metis-0760"][1]["keep_outside"]
check("0810: pr_index и batch_prs — PR с «часть» в индексе остаётся (ссылка у задачи), а PR пачки по нему задач не закрывает",
      any(x["number"] == 402 for x in A.pr_index(cache10).get("metis-0764", []))
      and [r for r in A.batch_prs(cache10)["metis-0760"] if r[1] == 402][0][3] == [])

# --- metis-0810: board-auto (boardtext.batches) — поле pr важнее ветки (мутант M25 argus B) --------------------------
bt10 = B.batches(store(H("metis-0760", type="story", status="doing", pr=f"{R}#77"),
                       H("metis-0762", parent="metis-0760", status="doing")), {"metis-0760": 401})
bt11 = B.batches(store(H("metis-0760", type="story", status="doing", pr="мусор"),
                       H("metis-0762", parent="metis-0760", status="doing")), {"metis-0760": 401})
check("0810: board-auto — поле pr пачки важнее PR с ветки; поле не по шаблону — номер с ветки",
      bt10 and bt10[0][4] == 77 and bt11 and bt11[0][4] == 401, (bt10, bt11))

# --- metis-0810: keep_outside — поле пачки, только id задач; цикл пачек через parent ---------------------------------
s10a, _ = T.task_new(PH, T0, "metis-pantheon", "Пачка А", kind="story")
s10b, _ = T.task_new(PH, T0, "metis-pantheon", "Пачка Б", kind="story")
s10c, _ = T.task_new(PH, T0, "metis-pantheon", "Пачка В", kind="story")
t10, _ = T.task_new(PH, T0, "metis-pantheon", "Задача вне пачки")
T.task_set(PH, T0, s10a, {"keep_outside": [t10]})
check("0810: keep_outside у пачки — пишется списком", T.load_tasks(PH, T.WORK_TYPES)[s10a][1].get("keep_outside") == [t10])
err = refused(lambda: T.task_set(PH, T0, t10, {"keep_outside": [t10]}))
check("0810: keep_outside у обычной задачи — отказ", err and "поле пачки" in err, err)
err = refused(lambda: T.task_set(PH, T0, s10a, {"keep_outside": [s10b]}))
check("0810: keep_outside с id пачки — отказ «не задача»", err and "не задача" in err, err)
T.task_set(PH, T0, s10b, {"parent": s10a, "mode": "single"})
err = refused(lambda: T.task_set(PH, T0, s10a, {"parent": s10b, "mode": "single"}))
check("0810: цикл пачек A.parent=B при B.parent=A — отказ с кругом, parent прежний",
      err and "цикл" in err and f"{s10a} → {s10b} → {s10a}" in err
      and not T.load_tasks(PH, T.WORK_TYPES)[s10a][1].get("parent"), err)
T.task_set(PH, T0, s10c, {"parent": s10b, "mode": "single"})
err = refused(lambda: T.task_set(PH, T0, s10a, {"parent": s10c, "mode": "single"}))
check("0810: цикл через три пачки (A → В → Б → A) — отказ", err and f"{s10a} → {s10c} → {s10b} → {s10a}" in err, err)
cyc = store(H("metis-0770", type="story", status="doing", parent="metis-0771"),
            H("metis-0771", type="story", status="doing", parent="metis-0770"),
            H("metis-0772", type="story", status="doing", parent="metis-0770"))
w = [x for x in T.board_problems(cyc, T0)[1] if "цикл" in x[1]]
check("0810: check — пачки в цикле (правка руками мимо task set): предупреждение у обеих; ребёнок цикла — нет",
      sorted(x[0] for x in w) == ["metis-0770", "metis-0771"], w)

print(f"{sum(results)} из {len(results)}")
sys.exit(0 if all(results) else 1)
