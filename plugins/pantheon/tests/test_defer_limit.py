#!/usr/bin/env python3
"""metis-0834: после трёх «отложить» по одной задаче плановый проход больше не задаёт владельцу тот же вопрос:
пинги по ней молчат, координатору направления (Зевсу — у направления без координатора) уходит задача «найти исполнителя
или решение» один раз, а владельцу — строка суточной сводки. Счётчик переносов — tasks.deferral_counts.

Запуск: python3 -I plugins/pantheon/tests/test_defer_limit.py  (код выхода 0 — все прошли)
"""
import atexit
import importlib.util
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="defer-limit-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

D = T._deferral

spec = importlib.util.spec_from_file_location("notify_t", os.path.join(LIB, "notify.py"))
N = importlib.util.module_from_spec(spec)
spec.loader.exec_module(N)

T0 = 1_792_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:900]}]"))


def ans(tid, text):
    return {"kind": "answer", "id": tid, "answer": text}


# --- счётчик переносов ------------------------------------------------------------------------------------------------
recs = {"a-1": [ans("a-1", "В — отложить"), ans("a-1", "Б — нет"), ans("a-1", "отложи до завтра"),
                {"kind": "request", "id": "a-1", "answer": "отложить"}]}
check("счётчик: два «отложить» из четырёх записей, «нет» и kind request не считаются",
      D.deferral_counts(recs) == {"a-1": 2}, D.deferral_counts(recs))
check("счётчик: пусто и без слов про откладывание — нуль", D.deferral_counts({}) == {}
      and D.deferral_counts({"x": [ans("x", "А — да")]}) == {})
ZLOG = ("## 2026-11-01 17:33:00 · окно вопросов\nвопрос: [athena-0205] Росреестр?\nответ: спроси ещё через 2 часа\n\n"
        "## 2026-11-01 19:34:00 · ответ в чате\nвопрос: [athena-0205] Росреестр?\nответ: В — отложить\n\n"
        "## 2026-11-02 11:00:00 · окно вопросов\nвопрос: [athena-0205] Росреестр?\nответ: А — да\n\n"
        "## 2026-11-02 12:00:00 · ответ в чате не распознан\nвопрос: [athena-0205] Росреестр?\nответ: отложить\n")
check("счётчик: окно вопросов и чат считаются, «да» и «не распознан» — нет",
      D.deferral_counts({}, ZLOG) == {"athena-0205": 2}, D.deferral_counts({}, ZLOG))
check("счётчик: доска и окно складываются",
      D.deferral_counts({"athena-0205": [ans("athena-0205", "отложить")]}, ZLOG) == {"athena-0205": 3})


# --- проход доски --------------------------------------------------------------------------------------------------------
def world(name, n_board=0, zeus_log="", status="waiting", direction="metis-pantheon", dirs_cfg=None):
    pan = os.path.join(ROOT, name, "pan")
    state = os.path.join(ROOT, name, "state")
    os.makedirs(os.path.join(state, "owner-log"))
    for d in ("directions/metis-pantheon/tasks", "directions/hq-dir/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(pan, d))
    tid, _ = T.task_new(pan, T0 - 7200, direction, "Наборы Росреестра", status=status, waiting_on="human",
                        question="Что делаем?", options=["А — да", "Б — нет", "В — отложить"], done_when=["пункт"])
    with open(os.path.join(state, "owner-log", "board.jsonl"), "w", encoding="utf-8") as fh:
        for _ in range(n_board):
            fh.write(json.dumps(ans(tid, "В — отложить"), ensure_ascii=False) + "\n")
    if zeus_log:
        with open(os.path.join(state, "owner-log", "zeus.md"), "w", encoding="utf-8") as fh:
            fh.write(zeus_log.replace("athena-0205", tid))
    return pan, state, tid, dirs_cfg


def tick(w, t, primary=True):
    pan, state, tid, dirs_cfg = w
    pol = N.Policy(os.path.join(state, "notify.json"), os.path.join(state, "notify-log.jsonl"), t=t, idle=3600)
    reg = T.project_registry(dirs_cfg or [{"name": "metis-pantheon"}, {"name": "hq-dir", "coordinator": False}])
    lines = T.board_sync(pan, os.path.join(state, "view", "Доска"), os.path.join(state, "board.json"),
                         os.path.join(state, "owner-log", "board.jsonl"), t, policy=pol, registry=reg, primary=primary)
    pol.save() if hasattr(pol, "save") else None
    return pol, lines


def made(pan, direction="metis-pantheon"):
    ts = T.load_tasks(pan, T.WORK_TYPES)
    return {i: h for i, (_, h, _) in ts.items() if i != "" and "Найти исполнителя" in str(h.get("title"))}


# 1. два переноса — вопрос ещё идёт
w = world("two", n_board=2)
pol, _ = tick(w, T0)
check("2 переноса: цикл вопроса живой (пинги идут), поручения нет",
      w[2] in pol.st["cycles"] and not made(w[0]), (list(pol.st["cycles"]), made(w[0])))

# 2. три переноса — вопрос не пингуется, поручение координатору, сводка владельцу
w = world("three", n_board=3)
pol, lines = tick(w, T0)
mk = made(w[0])
check("3 переноса: цикл вопроса не заводится — пингов нет", w[2] not in pol.st["cycles"], list(pol.st["cycles"]))
check("3 переноса: ровно одно поручение координатору направления (owner = направление)",
      len(mk) == 1 and list(mk.values())[0].get("owner") == "metis-pantheon"
      and list(mk.values())[0].get("direction") == "metis-pantheon", mk)
check("3 переноса: в поручении Харон и outside, ссылка на задачу",
      all(x in open(T.load_tasks(w[0], T.WORK_TYPES)[next(iter(mk))][0], encoding="utf-8").read()
          for x in ("Харон", "outside", f"[[{w[2]}]]")))
check("3 переноса: владельцу — строка суточной сводки (очередь), не пинг",
      any(q[1] == "defer" and q[2] == w[2] for q in pol.queue_view()) and not pol.sent, (pol.queue_view(), pol.sent))
check("3 переноса: строка «что сделано» называет задачу и поручение", any(w[2] in x and "поручение" in x for x in lines), lines)
cid = w[2]
st = json.load(open(os.path.join(w[1], "board.json"), encoding="utf-8"))
check("3 переноса: id поручения записан в состояние доски", st["cards"][cid].get("defer_task") in mk, st["cards"][cid])
pol2, _ = tick(w, T0 + 3600)
check("следующий проход: второго поручения нет", len(made(w[0])) == 1, made(w[0]))
check("следующий проход: сводка не плодит дубль внутри суток", sum(1 for q in pol2.queue_view() if q[1] == "defer") == 1,
      pol2.queue_view())

# 3. счётчик из окна вопросов (owner-log/zeus.md)
w = world("zlog", zeus_log=ZLOG.replace("ответ: А — да", "ответ: отложить"))
pol, _ = tick(w, T0)
check("перенос через окно вопросов: 3 слова «отложить» в zeus.md — то же поручение, пингов нет",
      len(made(w[0])) == 1 and w[2] not in pol.st["cycles"], (made(w[0]), list(pol.st["cycles"])))

# 4. направление без координатора — поручение Зевсу
w = world("hq", n_board=3, direction="hq-dir")
tick(w, T0)
mk = made(w[0])
check("направление без координатора: поручение с owner = zeus", [h.get("owner") for h in mk.values()] == ["zeus"], mk)

# 5. задача не ждёт владельца — не трогаем
w = world("notwait", n_board=5, status="todo")
pol, _ = tick(w, T0)
check("перенесено 5 раз, но задача не ждёт владельца: поручения и строки сводки нет",
      not made(w[0]) and not pol.queue_view(), (made(w[0]), pol.queue_view()))

# 6. не главный Mac — задач не создаём
w = world("secondary", n_board=3)
tick(w, T0, primary=False)
check("не главный Mac (primary=False): поручение не создаётся", not made(w[0]))

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
