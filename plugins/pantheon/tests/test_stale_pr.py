#!/usr/bin/env python3
"""metis-1170: плановый проход (tasks.board_sync) не теряет открытый PR.

1) авторазблокировка: ждала готовую задачу, а у неё открытый PR → review (не todo); без PR → todo;
2) тревога владельцу задачи о PR, который стоит дольше суток («принять» без заявки или CONFLICTING): одна на repo#N,
   до порога молчит, после — один раз с адресом владельца, конфликт снят — отсчёт сброшен.

Запуск: python3 -I plugins/pantheon/tests/test_stale_pr.py  (код выхода 0 — все прошли)
"""
import atexit
import os
import shutil
import sys
import tempfile

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="stale-pr-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

T0 = 1_794_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:900]}]"))


def mk(pan, tid, status, **extra):
    h = {"type": "task", "id": tid, "title": f"Задача {tid}", "status": status, "priority": 2,
         "direction": "metis-pantheon", "owner": "metis-pantheon", "project": "Пантеон", "mode": "single",
         "schema_version": 1, "created": "2026-11-01", "updated": "2026-11-02T10:00:00", **extra}
    if status == "done":
        h["closed"] = "2026-11-02"
    d = os.path.join(pan, "directions", "metis-pantheon", "tasks")
    os.makedirs(d, exist_ok=True)
    T.write_text(os.path.join(d, f"{tid}.md"), T.join(h, f"# {tid}\n\nТекст\n"))


def build(name):
    pan = os.path.join(ROOT, name)
    mk(pan, "metis-0001", "done")
    mk(pan, "metis-0002", "waiting", waiting_on="metis-0001")  # у неё открытый PR
    mk(pan, "metis-0003", "waiting", waiting_on="metis-0001")  # PR нет
    mk(pan, "metis-0004", "waiting", waiting_on="metis-0001")  # PR только слитый
    return pan


def sync(pan, label, t=T0, alert=None, **kw):
    view = os.path.join(ROOT, "v-" + label)
    return T.board_sync(pan, os.path.join(view, "Доска"), os.path.join(view, "st.json"), os.path.join(ROOT, "log-" + label),
                        t, primary=True, projects={}, registry={}, alert=alert, **kw)


def status(pan, tid):
    return T.load_tasks(pan, T.WORK_TYPES)[tid][1]["status"]


# --- 1. разблокировка ---------------------------------------------------------------------------------------------
pan = build("a")
sync(pan, "a", open_prs={"metis-0002"}, pr_index={"metis-0004": [{"repo": "r/x", "number": 4, "merged": True}]})
check("разблокировка: открытый PR (open_prs) → review", status(pan, "metis-0002") == "review", status(pan, "metis-0002"))
check("разблокировка: PR нет → todo", status(pan, "metis-0003") == "todo", status(pan, "metis-0003"))
check("разблокировка: только слитый PR → todo", status(pan, "metis-0004") == "todo", status(pan, "metis-0004"))
pan = build("b")
sync(pan, "b", pr_index={"metis-0002": [{"repo": "r/x", "number": 5, "merged": False}]})
check("разблокировка: открытый PR по pr_index → review, остальные todo",
      [status(pan, i) for i in ("metis-0002", "metis-0003")] == ["review", "todo"])

# --- 2. тревога о стоящем PR --------------------------------------------------------------------------------------
H = 3600
idx = {"metis-0002": [{"repo": "latark/x", "number": 7, "merged": False}]}
pan = build("c")
got = []
al = lambda k, v, text, who="board", note=None: got.append((k, text, who))
conf = [{"repo": "latark/x", "number": 7, "conflict": True, "accept_at": None}]
sync(pan, "c", T0, al, pr_index=idx, pr_watch=conf)
check("конфликт замечен впервые: тревоги нет", not [g for g in got if g[0].startswith("stalepr-")], got)
sync(pan, "c", T0 + 23 * H, al, pr_index=idx, pr_watch=conf)
check("конфликт 23 ч: тревоги нет (порог 24 ч)", not [g for g in got if g[0].startswith("stalepr-")], got)
sync(pan, "c", T0 + 25 * H, al, pr_index=idx, pr_watch=conf)
fired = [g for g in got if g[0].startswith("stalepr-")]
check("конфликт 25 ч: тревога с ключом на repo#N, владельцем задачи и текстом про CONFLICTING",
      len(fired) == 1 and fired[0][0] == "stalepr-latark/x#7" and fired[0][2] == "metis-pantheon"
      and "CONFLICTING" in fired[0][1] and "metis-0002" in fired[0][1], fired)
sync(pan, "c", T0 + 26 * H, al, pr_index=idx, pr_watch=conf)
check("ключ тревоги тот же на каждом проходе (alert_once шлёт одну на repo#N)",
      {g[0] for g in got if g[0].startswith("stalepr-")} == {"stalepr-latark/x#7"})
sync(pan, "c", T0 + 27 * H, al, pr_index=idx, pr_watch=[])
before = len(got)
sync(pan, "c", T0 + 60 * H, al, pr_index=idx, pr_watch=conf)
check("конфликт снят и вернулся: отсчёт заново, тревоги сразу нет", len(got) == before, got[before:])

pan = build("d")
got.clear()
acc = lambda age: [{"repo": "latark/x", "number": 7, "conflict": False, "accept_at": T0 - age}]
sync(pan, "d", T0, al, pr_index=idx, pr_watch=acc(23 * H))
check("«принять» без заявки 23 ч: тревоги нет", not got, got)
sync(pan, "d", T0, al, pr_index=idx, pr_watch=acc(25 * H))
check("«принять» без заявки 25 ч: тревога, в тексте про заявку tests",
      len(got) == 1 and got[0][0] == "stalepr-latark/x#7" and "без заявки" in got[0][1], got)
got.clear()
sync(pan, "d", T0, al, pr_index={}, pr_watch=acc(25 * H))
check("PR без задачи в индексе: тревога идёт на доску", len(got) == 1 and got[0][2] == "board", got)
got.clear()
sync(pan, "d", T0, al, pr_index=idx, pr_watch=None)
check("нет данных о PR (pr_watch пуст): тревог нет", not got, got)

print(f"{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
