#!/usr/bin/env python3
"""Откуда задача взялась, остаток и критерии готовности (metis-0502): поле from (допустимые значения) и source,
`task split` (остаток новой задачей со ссылкой в поле и в журнале обеих), `--done-when` и раздел «Готово, когда»,
строка в журнал при смене критериев, «Откуда» на карточке. Старые задачи без from читаются как раньше.

Запуск: python3 -I plugins/pantheon/tests/test_task_origin.py  (код выхода 0 — все прошли)
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="origin-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

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


DIRS = '''[[direction]]
name = "metis-pantheon"
project = "Пантеон"

[[direction]]
name = "athena-shop"
project = "Магазин"
'''


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="origin-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("directions/metis-pantheon/tasks", "directions/athena-shop/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    os.makedirs(view)
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(DIRS)
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0"}
    return tmp, home, env


def run(env, *args, t=T0):
    e = dict(env, PANTHEON_NOW=str(t))
    return subprocess.run([PY311, "-I", RUN_PY, *args], env=e, capture_output=True, text=True, timeout=60)


def read(home, rel):
    return open(os.path.join(home, rel), encoding="utf-8").read()


def lib_checks(home):
    errs, _ = T.check_head({"type": "task", "id": "demo-0001", "title": "x", "status": "todo", "project": "p",
                            "direction": "d", "created": "2026-10-26", "updated": "2026-10-26T10:00", "schema_version": 1,
                            "from": "сплетня"})
    check("check_head: чужое from — ошибка с перечнем", any("from" in e and "остаток" in e for e in errs), errs)
    for v in T.FROM_VALUES:
        errs, _ = T.check_head({"type": "task", "id": "demo-0001", "title": "x", "status": "todo", "project": "p",
                                "direction": "d", "created": "2026-10-26", "updated": "2026-10-26T10:00",
                                "schema_version": 1, "from": v})
        check(f"check_head: from «{v}» принят", not errs, errs)
    errs, _ = T.check_head({"type": "task", "id": "demo-0001", "title": "x", "status": "todo", "project": "p",
                            "direction": "d", "created": "2026-10-26", "updated": "2026-10-26T10:00", "schema_version": 1,
                            "from": "остаток", "source": "demo-0001"})
    check("check_head: source на саму задачу — ошибка", any("саму" in e for e in errs), errs)
    try:
        T.check_source(home, "demo-0001", "demo-0001")
        check("check_source: ссылка на себя — отказ", False)
    except ValueError as e:
        check("check_source: ссылка на себя — отказ", "саму" in str(e), e)
    check("FROM_VALUES — шесть значений решения",
          T.FROM_VALUES == ("слово владельца", "отчёт", "ревью", "остаток", "план", "по ходу"), T.FROM_VALUES)
    check("from и source — в FIELDS", "from" in T.FIELDS and "source" in T.FIELDS)

    # task_new: from, source, раздел критериев
    tid, p = T.task_new(home, T0, "metis-pantheon", "С происхождением", text="Цель.", done_when=["Первое", "Второе"],
                        **{"from": "ревью", "source": "review-147-argus-a.md#Д1"})
    h, b = T.split(read(home, os.path.relpath(p, home)))
    check("task_new: from и source в шапке", h.get("from") == "ревью" and h.get("source") == "review-147-argus-a.md#Д1", h)
    check("task_new: раздел «Готово, когда» с двумя пунктами",
          "## Готово, когда\n\n- [ ] Первое\n- [ ] Второе\n\n## Журнал" in b, b)
    check("done_criteria читает пункты", T.done_criteria(b) == [(False, "Первое"), (False, "Второе")], T.done_criteria(b))

    tid2, p2 = T.task_new(home, T0, "metis-pantheon", "Без флага", text="Цель.")
    b2 = T.split(read(home, os.path.relpath(p2, home)))[1]
    check("без --done-when раздел есть, пункт — подсказка", f"## Готово, когда\n\n- [ ] {T.DONE_WHEN_HINT}\n" in b2, b2)
    check("в шапке без from поля нет (старый вид)", "from" not in T.split(read(home, os.path.relpath(p2, home)))[0])

    for bad, why in (({"from": "сплетня"}, "чужое from"), ({"source": "metis-9999", "from": "остаток"}, "нет такой задачи"),
                     ({"source": "review.md#Д1"}, "source без from")):
        try:
            T.task_new(home, T0, "metis-pantheon", "Плохая", text="x", **bad)
            check(f"task_new: {why} — отказ", False)
        except ValueError as e:
            check(f"task_new: {why} — отказ", True, e)
    check("отказ не оставил файла", sorted(os.listdir(os.path.join(home, "directions/metis-pantheon/tasks")))
          == sorted([os.path.basename(p), os.path.basename(p2)]), os.listdir(os.path.join(home, "directions/metis-pantheon/tasks")))

    try:
        T.task_new(home, T0, "metis-pantheon", "Двойные", text="Готово, когда:\n- [ ] а", done_when=["б"])
        check("пункты и в тексте, и в --done-when — отказ", False)
    except ValueError as e:
        check("пункты и в тексте, и в --done-when — отказ", "не в обоих" in str(e), e)
    tid3, p3 = T.task_new(home, T0, "metis-pantheon", "Старый образец", text="Цель.\n\nГотово, когда:\n- [ ] а\n- [ ] б")
    b3 = T.split(read(home, os.path.relpath(p3, home)))[1]
    check("пункты уже в тексте — второго раздела нет", b3.count("Готово, когда") == 1, b3)

    # task set: source проверяется, смена критериев — в журнал
    try:
        T.task_set(home, T0 + 1, tid2, {"from": "остаток", "source": "metis-9999"})
        check("task_set: source на несуществующую — отказ", False)
    except ValueError as e:
        check("task_set: source на несуществующую — отказ", "нет такой задачи" in str(e), e)
    T.task_set(home, T0 + 2, tid2, {"from": "по ходу", "source": tid})
    check("task_set: from/source записаны", T.split(read(home, os.path.relpath(p2, home)))[0].get("source") == tid)
    T.task_set(home, T0 + 3, tid, {}, body="Цель.\n\n- [ ] Первое\n- [ ] Третье")
    b = T.split(read(home, os.path.relpath(p, home)))[1]
    check("замена текста с другими критериями — строка «критерии изменены»", "критерии «Готово, когда» изменены" in b, b)
    check("…с числами пунктов", "было пунктов 2, стало 0" in b, b)
    T.task_set(home, T0 + 4, tid3, {}, body="Цель новая.\n\nГотово, когда:\n- [x] а\n- [ ] б")
    b3 = T.split(read(home, os.path.relpath(p3, home)))[1]
    check("замена текста, где пункты те же (отметка не в счёт) — строки о критериях нет", "критерии" not in b3, b3)
    return tid, p


def split_checks(home):
    sid, _ = T.task_new(home, T0, "metis-pantheon", "Пачка", text="Пачка.", kind="story")
    src, sp = T.task_new(home, T0, "metis-pantheon", "Исходная", text="Цель.", done_when=["Сделано раз", "Сделано два"],
                         parent=sid, mode="single", owner="hephaestus-pantheon", priority=1)
    sp = os.path.relpath(sp, home)
    body = read(home, sp).replace("- [ ] Сделано раз", "- [x] Сделано раз")
    open(os.path.join(home, sp), "w", encoding="utf-8").write(body)
    nid, np_ = T.task_split(home, T0 + 10, src, "Довести два")
    nh, nb = T.split(read(home, os.path.relpath(np_, home)))
    check("split: from=остаток и source=исходная", nh.get("from") == "остаток" and nh.get("source") == src, nh)
    check("split: то же направление, проект, пачка, режим, владелец, приоритет",
          nh.get("direction") == "metis-pantheon" and nh.get("project") == T.split(read(home, sp))[0].get("project") and nh.get("parent") == sid
          and nh.get("mode") == "single" and nh.get("owner") == "hephaestus-pantheon" and nh.get("priority") == 1, nh)
    check("split: тег «остаток»", "остаток" in (nh.get("tags") or []), nh.get("tags"))
    check("split: пункты — только неотмеченные исходной", "- [ ] Сделано два" in nb and "Сделано раз" not in nb, nb)
    check("split: журнал новой со ссылкой на исходную", f"остаток задачи {src}" in nb, nb)
    oh, ob = T.split(read(home, sp))
    check("split: журнал исходной со ссылкой на новую", f"остаток вынесен в {nid}: Довести два" in ob, ob)
    check("split: исходная не закрыта и не изменена в полях", oh.get("status") == "todo" and "from" not in oh, oh)
    nid2, np2 = T.task_split(home, T0 + 20, src, "Свои пункты", done_when=["Особый"], text="Описание.")
    nb2 = T.split(read(home, os.path.relpath(np2, home)))[1]
    check("split --done-when: свои пункты вместо исходных", "- [ ] Особый" in nb2 and "Сделано два" not in nb2
          and "Описание." in nb2, nb2)
    for args, why in ((("metis-9999", "Т"), "нет такой задачи"), ((sid, "Т"), "пачка — не задача"), ((src, "  "), "пустое название")):
        try:
            T.task_split(home, T0 + 30, *args)
            check(f"split: {why} — отказ", False)
        except ValueError as e:
            check(f"split: {why} — отказ", True, e)
    # подмена direction в шапке исходной (файл остаётся в своей папке) → отказ, файла нет (Б1 argus)
    tdir = os.path.join(home, "directions/metis-pantheon/tasks")
    files0 = set(os.listdir(tdir))
    good = read(home, sp)
    open(os.path.join(home, sp), "w", encoding="utf-8").write(good.replace("direction: metis-pantheon", "direction: athena-shop", 1))
    swapped = read(home, sp)
    try:
        T.task_split(home, T0 + 35, src, "Чужое")
        check("split: direction в шапке не совпадает с папкой — отказ", False)
    except ValueError as e:
        check("split: direction в шапке не совпадает с папкой — отказ", "athena-shop" in str(e), e)
    check("split: при подмене direction файла не появилось и исходная не тронута",
          set(os.listdir(tdir)) == files0 and read(home, sp) == swapped)
    open(os.path.join(home, sp), "w", encoding="utf-8").write(good)
    # исходная в пачке с режимом «не решено»: split без --mode — отказ, с --mode — проходит (metis-0579)
    nomode, nmp = T.task_new(home, T0, "metis-pantheon", "Без режима", text="Цель.", done_when=["Пункт"])
    nmp = os.path.relpath(nmp, home)
    body = read(home, nmp).replace("\nowner:", f"\nparent: {sid}\nmode: undecided\nowner:", 1)
    open(os.path.join(home, nmp), "w", encoding="utf-8").write(body)
    try:
        T.task_split(home, T0 + 36, nomode, "Остаток без режима")
        check("split: пачка без режима и без --mode — отказ", False)
    except ValueError as e:
        check("split: пачка без режима и без --mode — отказ", "режима" in str(e), e)
    nid3, np3 = T.task_split(home, T0 + 37, nomode, "Остаток с режимом", mode="self", mode_why="мелочь")
    nh3 = T.split(read(home, os.path.relpath(np3, home)))[0]
    check("split --mode: режим и довод записаны", nh3.get("mode") == "self" and nh3.get("mode_why") == "мелочь"
          and nh3.get("parent") == sid, nh3)
    before = read(home, sp)
    # сбой записи в исходную → новая не остаётся
    real = T.task_set
    files = set(os.listdir(os.path.join(home, "directions/metis-pantheon/tasks")))

    def boom(*a, **k):
        raise ValueError("сбой записи")
    T.task_set = boom
    try:
        T.task_split(home, T0 + 40, src, "Не выйдет")
        check("split: сбой записи в исходную — отказ", False)
    except ValueError:
        check("split: сбой записи в исходную — отказ и новой задачи нет",
              set(os.listdir(os.path.join(home, "directions/metis-pantheon/tasks"))) == files)
    finally:
        T.task_set = real
    check("split: сбой не тронул исходную", read(home, sp) == before)


def card_checks():
    base = {"type": "task", "id": "metis-0001", "title": "x", "status": "todo", "project": "Пантеон",
            "direction": "metis-pantheon", "created": "2026-10-26", "updated": "2026-10-26T10:00", "owner": "a"}
    card = T.render_card(dict(base, **{"from": "остаток", "source": "metis-0000"}), "", "x.md", T0)[0]
    # metis-0506: «Откуда» — только вид (по нему группирует «Новое за неделю»), источник — отдельным «Из чего»
    check("карточка: «Откуда» — остаток, «Из чего» — исходная", card.get("Откуда") == "остаток"
          and card.get("Из чего") == "metis-0000", (card.get("Откуда"), card.get("Из чего")))
    card = T.render_card(base, "", "x.md", T0)[0]
    check("карточка старой задачи: «Откуда» пусто", card.get("Откуда") is None, card.get("Откуда"))
    check("«Откуда» есть в порядке свойств", "Откуда" in T.CARD_ORDER)


def cli_checks(home, env):
    r = run(env, "task", "new", "--direction", "metis-pantheon", "--title", "Через CLI", "--text", "Цель.",
            "--from", "отчёт", "--source", "research-x.md#3", "--done-when", "Раз", "--done-when", "Два")
    check("CLI task new --from --source --done-when ×2", r.returncode == 0, r.stderr)
    tid, rel = r.stdout.split()[:2]
    h, b = T.split(read(home, rel))
    check("CLI: шапка и два пункта", h.get("from") == "отчёт" and h.get("source") == "research-x.md#3"
          and "- [ ] Раз\n- [ ] Два\n" in b, (h, b))
    r = run(env, "task", "new", "--direction", "metis-pantheon", "--title", "Плохая", "--text", "Цель.", "--from", "сплетня")
    check("CLI: --from с чужим значением — код не 0, перечень в stderr, файла нет",
          r.returncode != 0 and "слово владельца" in r.stderr
          and len(os.listdir(os.path.join(home, "directions/metis-pantheon/tasks"))) == 1, r.stdout + r.stderr)
    r = run(env, "task", "new", "--direction", "metis-pantheon", "--title", "Двойное", "--text", "Цель.", "--from", "отчёт",
            "--from", "план")
    check("CLI: повтор одиночного --from — код 2", r.returncode == 2, r.stderr)
    r = run(env, "task", "split", tid, "--title", "Хвост", "--done-when", "Хвостовой пункт")
    check("CLI task split: код 0, строка «id путь (остаток X)»", r.returncode == 0 and f"(остаток {tid})" in r.stdout, r.stdout + r.stderr)
    nid, nrel = r.stdout.split()[:2]
    nh, nb = T.split(read(home, nrel))
    check("CLI split: from=остаток, source, пункт", nh.get("from") == "остаток" and nh.get("source") == tid
          and "- [ ] Хвостовой пункт" in nb, (nh, nb))
    check("CLI split: журнал исходной", f"остаток вынесен в {nid}" in read(home, rel))
    r = run(env, "task", "split", tid)
    check("CLI split без --title — код 2", r.returncode == 2 and "--title" in r.stderr, r.stderr)
    r = run(env, "task", "split", "metis-9999", "--title", "Х")
    check("CLI split несуществующей — код не 0", r.returncode != 0 and "нет задачи" in r.stderr, r.stderr)
    r = run(env, "task", "split", tid, "--title", "А", "--нет", "1")
    check("CLI split: неизвестный флаг — код 2", r.returncode == 2, r.stderr)
    r = run(env, "task", "set", tid, "from=сплетня")
    check("CLI task set from=чужое — отказ", r.returncode != 0, r.stderr)
    r = run(env, "task", "show", nid)
    check("CLI task show остатка работает", r.returncode == 0 and "остаток" in r.stdout, r.stderr)


def main():
    tmp, home, env = make()
    try:
        lib_checks(home)
        split_checks(home)
        card_checks()
        tmp2, home2, env2 = make()
        try:
            cli_checks(home2, env2)
        finally:
            shutil.rmtree(tmp2, True)
    finally:
        shutil.rmtree(tmp, True)
    print(f"{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
