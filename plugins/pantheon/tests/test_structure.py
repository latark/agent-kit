#!/usr/bin/env python3
"""Единая структура задач по направлениям (metis-0505) на трёх синтетических направлениях: alpha — с пачками, beta — без
пачек, gamma — пустое. Разовая миграция mode (pantheon task migrate-mode: --dry-run ничего не пишет, запись, повтор,
сбой записи → код 1), сводка и пропуски «Кто делает» в pantheon check, «не решено» (undecided) не годится пачке,
правила названий пачек и целей, dropped → done по правилу критериев (metis-0543 Д1).

Запуск: python3 -I plugins/pantheon/tests/test_structure.py  (код выхода 0 — все прошли; CLI — только с Python 3.11+)
"""
import atexit
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402  (CLI pantheon — только на Python 3.11+)

_ROOT = tempfile.mkdtemp(prefix="structure-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CLI = os.path.join(LIB, "pantheon.py")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

T_NEW = int(time.mktime((2026, 10, 28, 12, 0, 0, 0, 0, -1)))  # после CRITERIA_FROM (27.10)
results = []
DIRS = ('[[direction]]\nname = "alpha"\nproject = "Альфа"\n\n[[direction]]\nname = "beta"\nproject = "Бета"\n\n'
        '[[direction]]\nname = "gamma"\nproject = "Гамма"\n')
PROJ = {"alpha": "Альфа", "beta": "Бета", "gamma": "Гамма", "inbox": "Входящие"}


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{str(detail)[:600]}]"))


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="structure-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("directions/alpha/tasks", "directions/beta/tasks", "directions/gamma/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    os.makedirs(view)
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(DIRS)
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0", "TMPDIR": tmp}
    return tmp, home, env


def run(env, *args, t=T_NEW):
    return subprocess.run([PY311, "-I", CLI, *args], env=dict(env, PANTHEON_NOW=str(t)), capture_output=True, text=True,
                          timeout=120)


def put(home, direction, tid, status="todo", body="", kind="task", **f):
    """Файл задачи руками: поля, которых CLI не даёт (задача пачки без mode, старая дата created)."""
    head = {"type": kind, "id": tid, "title": "Задача " + tid, "status": status, "project": PROJ[direction],
            "direction": direction, "owner": "zeus" if direction == "inbox" else direction, "created": "2026-10-20",
            "updated": "2026-10-20T10:00:00", "schema_version": 1}
    head.update(f)
    base = os.path.join(home, "inbox", "tasks") if direction == "inbox" else os.path.join(home, "directions", direction, "tasks")
    p = os.path.join(base, tid + ".md")
    lines = []
    for k, v in head.items():
        if v is None:
            continue
        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, (str, list)) else v}")
    open(p, "w", encoding="utf-8").write("---\n" + "\n".join(lines) + "\n---\n\n# " + head["title"] + "\n\n" + body
                                         + "\n## Журнал\n\n- 2026-10-20 10:00 — агент: создана\n")
    return p


def snapshot(home):
    out = {}
    for root, _, files in os.walk(home):
        for f in files:
            if f != ".lock":
                out[os.path.join(root, f)] = open(os.path.join(root, f), "rb").read()
    return out


def head_of(p):
    return T.read(p)[0]


def fixture(home):
    """alpha — пачка с задачами (одна без mode), beta — свободная очередь, gamma — пусто, inbox — заявка без mode."""
    put(home, "alpha", "alpha-0001", kind="story", title="Пачка: быстрый вход", created="2026-10-28")
    p = {"a_ok": put(home, "alpha", "alpha-0002", parent="alpha-0001", mode="single"),
         "a_nomode": put(home, "alpha", "alpha-0003", parent="alpha-0001"),
         "a_free": put(home, "alpha", "alpha-0004", status="doing", next="дописать", body="Готово, когда:\n- [ ] а\n"),
         "b_todo": put(home, "beta", "beta-0001"),
         "b_inbox": put(home, "beta", "beta-0002", status="inbox"),
         "b_wait": put(home, "beta", "beta-0003", status="waiting", waiting_on="human", next="ответ"),
         "b_done": put(home, "beta", "beta-0004", status="done", closed="2026-10-21"),
         "b_drop": put(home, "beta", "beta-0005", status="dropped", closed="2026-10-21"),
         "b_self": put(home, "beta", "beta-0006", mode="self"),
         "b_und": put(home, "beta", "beta-0007", mode="undecided"),
         "b_rest": put(home, "beta", "beta-0008", tags=["остаток"], body="Готово, когда:\n- [ ] " + T.DONE_WHEN_HINT + "\n"),
         "inbox": put(home, "inbox", "inbox-0001")}
    return p


MIGRATED = ("a_free", "b_todo", "b_inbox", "b_wait", "b_rest")
UNTOUCHED = ("a_ok", "a_nomode", "b_done", "b_drop", "b_self", "b_und", "inbox")


def test_unit():
    tmp, home, env = make()
    try:
        p = fixture(home)
        tasks = T.load_tasks(home, T.WORK_TYPES)
        s = T.direction_summary(tasks, T.direction_names(home, T.load_directions(home)))
        check("сводка: три направления, пустое gamma — с нулями", sorted(s) == ["alpha", "beta", "gamma"]
              and all(v == 0 for k, v in s["gamma"].items() if k != "no_mode_ids"), s)
        a, b = s["alpha"], s["beta"]
        check("сводка alpha: открытых 3, без пачки 1, без mode 2", (a["open"], a["no_pack"], a["no_mode"]) == (3, 1, 2), a)
        check("сводка beta: открытых 6 (done и dropped не считаются), без пачки 6, без mode 4, «не решено» 1, остатков 1",
              (b["open"], b["no_pack"], b["no_mode"], b["undecided"], b["rest_open"]) == (6, 6, 4, 1, 1), b)
        check("сводка: заглушка-подсказка — «без Готово, когда»; пункт — с критериями",
              a["no_criteria"] == 2 and b["no_criteria"] == 6, (a, b))
        check("сводка: заявка из inbox/ в направления не попала", "inbox" not in s, sorted(s))
        check("mode_decided: self/single/parallel — да; undecided, пусто, чужое — нет",
              [T.mode_decided({"mode": m}) for m in ("self", "single", "parallel", "undecided", None, "", "x")]
              == [True, True, True, False, False, False, False])
        check("check_head: mode undecided — законное значение", not T.check_head(head_of(p["b_und"]))[0])
        # сбой записи: строка «не записано» и счёт сбоев
        real = T.task_set

        def boom(*a, **kw):
            raise ValueError("занято")
        T.task_set = boom
        try:
            lines, failed = T.migrate_modes(home, T_NEW)
        finally:
            T.task_set = real
        check("migrate_modes: сбой task_set → сбоев 5, строки «не записано»", failed == len(MIGRATED)
              and sum("не записано: занято" in x for x in lines) == len(MIGRATED), (failed, lines))
        # attach отказывает сам, до записи: шлюз task_set за ним — второй слой, а не единственный
        calls = []
        T.task_set = lambda *a, **kw: calls.append(a)
        try:
            T.task_attach(home, T_NEW, "beta-0007", "alpha-0001")
            err = ""
        except ValueError as e:
            err = str(e)
        finally:
            T.task_set = real
        check("task_attach: undecided — отказ до любой записи", "не годится" in err and not calls, (err, calls))
        # карточка: «не решено» — пустое свойство «Режим», иначе вид показал бы «один исполнитель»
        card, _ = T.render_card(head_of(p["b_und"]), "", "x.md", T_NEW)
        card2, _ = T.render_card(head_of(p["b_self"]), "", "x.md", T_NEW)
        check("карточка: undecided → «Режим» пуст, self → «сам»", card.get("Режим") is None and card2.get("Режим") == "сам",
              (card.get("Режим"), card2.get("Режим")))
    finally:
        shutil.rmtree(tmp, True)


def test_pack_titles():
    tasks = {}

    def st(i, title, created="2026-10-28", status="todo", parent=None, direction="alpha"):
        tasks[i] = ("p", {"id": i, "type": "story", "title": title, "status": status, "created": created,
                          "direction": direction, "parent": parent}, "")
    st("alpha-0010", "Пачка: быстрый вход")
    st("alpha-0011", "П3 вход")
    st("alpha-0012", "Пачка 2. Оплата")
    st("alpha-0013", "Пачка: 3")
    st("alpha-0014", "Оплата картой")
    st("alpha-0015", "П0 старое", created="2026-10-20")
    st("alpha-0016", "Цель: бета", )
    st("alpha-0017", "Пачка: шаг цели", parent="alpha-0016")
    st("alpha-0018", "Пачка 1", created="2026-10-28")
    st("alpha-0019", "Пачка: шаг", parent="alpha-0018")
    st("alpha-0020", "Пачка 3", created="2026-10-10")
    st("alpha-0021", "Пачка  3", created="2026-10-11")
    st("beta-0010", "Пачка 3", created="2026-10-10", direction="beta")
    st("alpha-0022", "Пачка: быстрый вход", status="done")
    w = dict(T.pack_title_warns(tasks))
    check("название «Пачка: результат» — без предупреждения", "alpha-0010" not in w and "alpha-0017" not in w, w)
    check("новая «П3», «Пачка 2.», «Пачка: 3», без «Пачка: » — предупреждения",
          all(i in w and "Пачка: " in w[i] for i in ("alpha-0011", "alpha-0012", "alpha-0013", "alpha-0014")), w)
    check("старая «П0» (created до 27.10) — без предупреждения", "alpha-0015" not in w, w)
    check("цель «Цель: …» с пачкой внутри — без предупреждения", "alpha-0016" not in w, w)
    check("новая цель с названием «Пачка 1» — предупреждение цели", "цель" in w.get("alpha-0018", ""), w)
    check("две открытые «Пачка 3» одного направления (любой давности) — предупреждение на вторую",
          "alpha-0020" in w.get("alpha-0021", "") and "alpha-0020" not in w, w)
    check("то же название в другом направлении и у закрытой пачки — не дубль",
          "beta-0010" not in w and "alpha-0022" not in w, w)
    errs, warns = T.board_problems(tasks, T_NEW)
    check("board_problems несёт предупреждения названий", ("alpha-0011", w["alpha-0011"]) in warns, warns)


def test_cli():
    tmp, home, env = make()
    try:
        p = fixture(home)
        r = run(env, "check")
        out = r.stdout
        check("check: сводка по всем трём направлениям", all(f"сводка · {d}:" in out for d in ("alpha", "beta", "gamma")), out)
        check("check: gamma — открытых 0", "сводка · gamma: открытых 0 ·" in out, out)
        check("check: пропуски mode найдены по направлениям (alpha 2, beta 4)",
              "внимание · alpha: без «Кто делает» (mode) открытых задач 2" in out
              and "внимание · beta: без «Кто делает» (mode) открытых задач 4" in out, out)
        check("check: задача пачки без mode — ОШИБКА", "ОШИБКА · alpha-0003" in out and r.returncode != 0, out)
        r = run(env, "check", "--quiet")
        check("check --quiet: сводки нет", "сводка ·" not in r.stdout, r.stdout)

        before = snapshot(home)
        for bad in (["--dryrun"], ["--dry-run", "--x"], ["--write"]):
            r = run(env, "task", "migrate-mode", *bad)
            check(f"migrate-mode {' '.join(bad)}: код 2, ничего не записано", r.returncode == 2 and snapshot(home) == before,
                  (r.returncode, r.stderr))
        r = run(env, "task", "migrate-mode", "--dry-run")
        planned = {ln.split(":")[0] for ln in r.stdout.splitlines() if "→ undecided" in ln}
        want = {os.path.basename(p[k])[:-3] for k in MIGRATED}
        check("dry-run: код 0, в плане ровно открытые задачи без mode вне пачек", r.returncode == 0 and planned == want,
              (planned, want, r.stdout, r.stderr))
        check("dry-run: задача пачки — «пропущена»", "alpha-0003: в пачке alpha-0001 без mode — пропущена" in r.stdout, r.stdout)
        check("dry-run: ничего не записано на всех трёх направлениях", snapshot(home) == before)
        check("dry-run: строка «ничего не записано»", "(--dry-run: ничего не записано)" in r.stdout, r.stdout)

        # сбой записи: папка beta только для чтения → код 1, alpha записана
        bdir = os.path.join(home, "directions", "beta", "tasks")
        os.chmod(bdir, stat.S_IRUSR | stat.S_IXUSR)
        try:
            r = run(env, "task", "migrate-mode", t=T_NEW + 50)
        finally:
            os.chmod(bdir, stat.S_IRWXU)
        check("сбой записи: код 1, последняя строка stderr называет число", r.returncode == 1
              and "не записано 4" in (r.stderr.strip().splitlines() or [""])[-1], (r.returncode, r.stdout, r.stderr))
        check("сбой записи: beta не тронута", all(head_of(p[k]).get("mode") is None for k in ("b_todo", "b_inbox", "b_wait", "b_rest")))

        untouched = {k: open(p[k], "rb").read() for k in UNTOUCHED}
        r = run(env, "task", "migrate-mode", t=T_NEW + 100)
        check("запись: код 0", r.returncode == 0, r.stdout + r.stderr)
        hs = {k: head_of(p[k]) for k in MIGRATED}
        check("запись: открытые без mode → undecided", all(h.get("mode") == "undecided" for h in hs.values()), hs)
        check("запись: updated прежний (служебная правка)",
              all(h.get("updated") == "2026-10-20T10:00:00" for k, h in hs.items() if k != "a_free"), hs)
        check("запись: строка в журнале", all("разовая миграция mode, metis-0505" in open(p[k], encoding="utf-8").read()
                                              for k in MIGRATED))
        check("запись: done, dropped, с mode, «не решено», задача пачки и inbox не тронуты",
              all(open(p[k], "rb").read() == untouched[k] for k in UNTOUCHED))
        after = snapshot(home)
        r = run(env, "task", "migrate-mode", t=T_NEW + 200)
        check("повтор: только пропуск задачи пачки, 0 изменений", r.returncode == 0 and "→ undecided" not in r.stdout
              and snapshot(home) == after, r.stdout)
        r = run(env, "check", t=T_NEW + 300)
        check("check после миграции: пропуск mode остался только у задачи пачки (alpha 1), у beta нет",
              "внимание · alpha: без «Кто делает» (mode) открытых задач 1" in r.stdout
              and "внимание · beta: без «Кто делает»" not in r.stdout and "«не решено» 5" in r.stdout, r.stdout)

        # «не решено» пачке не годится
        r = run(env, "task", "attach", "beta-0001", "alpha-0001", t=T_NEW + 400)
        check("attach задачи с undecided — отказ", r.returncode != 0 and "не годится" in r.stderr
              and "parent" not in open(p["b_todo"], encoding="utf-8").read(), r.stderr)
        r = run(env, "task", "set", "alpha-0002", "mode=undecided", t=T_NEW + 400)
        check("task set mode=undecided у задачи пачки — отказ", r.returncode != 0 and head_of(p["a_ok"]).get("mode") == "single",
              r.stderr)
        r = run(env, "task", "set", "alpha-0002", "mode=", t=T_NEW + 400)
        check("снять mode у задачи пачки — отказ", r.returncode != 0 and head_of(p["a_ok"]).get("mode") == "single", r.stderr)
        r = run(env, "task", "set", "alpha-0002", "mode=self", t=T_NEW + 400)
        check("задаче пачки другой решённый режим — можно", r.returncode == 0 and head_of(p["a_ok"]).get("mode") == "self",
              r.stderr)
        r = run(env, "task", "new", "--text", "т", "--direction", "alpha", "--title", "Новая", "--parent", "alpha-0001",
                "--mode", "undecided", t=T_NEW + 400)
        check("task new --parent пачка --mode undecided — отказ", r.returncode != 0 and "не годится" in r.stderr, r.stderr)
        r = run(env, "task", "set", "beta-0006", "mode=undecided", t=T_NEW + 400)
        check("задаче вне пачки «не решено» — можно", r.returncode == 0 and head_of(p["b_self"]).get("mode") == "undecided", r.stderr)
        put(home, "alpha", "alpha-0003", parent="alpha-0001", mode="undecided")
        r = run(env, "check", t=T_NEW + 500)
        check("check: задача пачки с undecided — ОШИБКА", "ОШИБКА · alpha-0003" in r.stdout and r.returncode != 0, r.stdout)
    finally:
        shutil.rmtree(tmp, True)


def test_dropped_to_done():
    """metis-0543 Д1: dropped → done — закрытие, правило неотмеченных «Готово, когда» действует."""
    tmp, home, env = make()
    try:
        two = "Готово, когда:\n- [x] одно\n- [ ] второе\n"
        pd = put(home, "beta", "beta-0101", status="dropped", closed="2026-10-28", created="2026-10-28", body=two)
        try:
            T.task_set(home, T_NEW, "beta-0101", {"status": "done"})
            err = ""
        except ValueError as e:
            err = str(e)
        check("dropped → done с неотмеченным — отказ «неотмечено 1»", "неотмечено 1" in err
              and head_of(pd).get("status") == "dropped", err)
        T.task_set(home, T_NEW, "beta-0101", {"status": "done"}, force="отменили второй пункт")
        check("dropped → done с --force причина — done", head_of(pd).get("status") == "done")
        T.task_set(home, T_NEW, "beta-0101", {"status": "done", "result": "готово"})
        check("done → done (повтор) — без отказа", head_of(pd).get("result") == "готово")
        po = put(home, "beta", "beta-0102", status="dropped", closed="2026-10-21", created="2026-10-20", body=two)
        T.task_set(home, T_NEW, "beta-0102", {"status": "done"})
        check("старая (до 27.10) dropped → done — как раньше", head_of(po).get("status") == "done")
    finally:
        shutil.rmtree(tmp, True)


def main():
    test_unit()
    test_pack_titles()
    test_dropped_to_done()
    if PY311:
        test_cli()
    else:
        print("skip: CLI — нужен Python 3.11+")


main()
print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if results and all(results) else 1)
