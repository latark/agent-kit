#!/usr/bin/env python3
"""`pantheon merge request` и пункты «Готово, когда» (metis-1260, тест — metis-1266): cmd_request зовёт
review_criteria_gap после шлюза, и PR с задачей из Closes, у которой пункт без отметки argus на head, заявки не
получает.

Запуск: python3 -I plugins/pantheon/tests/test_merge_criteria.py  (код выхода 0 — все прошли)
Поддельные gh и помощник окна — из _merge_common (Box). Проверяет: тело PR «Closes metis-0001», у задачи неотмеченный
пункт «- [ ]», в «принять» argus на head нет --criteria → код 1, причина называет пункт metis-0001#1 и «нет отметки
argus», файла заявки нет; те же «принять» с «да» на каждом пункте → заявка стоит (код 0). Мутант — внутри теста: копия
плагина, где cmd_request не зовёт review_criteria_gap, ставит заявку на неотмеченный пункт — значит случай его ловит.
"""
# ruff: noqa: F403, F405
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_common import *  # noqa: F403

sys.path.insert(0, LIBDIR)
import tasks as T  # noqa: E402 — хеш пункта, как его считает шлюз

TID = "metis-0001"
ITEM = "первый пункт: файл a.py"
CARD = ("---\ntype: task\nid: %s\ntitle: \"Задача\"\nstatus: doing\nproject: Пантеон\ndirection: metis-pantheon\n"
        "owner: metis-pantheon\ncreated: 2026-11-08\nupdated: 2026-11-08T10:00:00\nschema_version: 1\n---\n\n"
        "# Задача\n\n## Готово, когда\n\n- [ ] %s\n\n## Журнал\n\n- 2026-11-08 10:00 — агент: создана\n")
CALL = "(P.review_criteria_gap(repo, pr, sha, view, criteria_api()) or merge_conflict(view))"


def box(criteria=None):
    """PR ядра с «Closes metis-0001» в теле, задача с неотмеченным пунктом; запись тестов и два «принять» Opus на head,
    criteria — значения --criteria в обоих «принять» (None — без них)."""
    b = Box()
    d = os.path.join(b.pantheon, "directions", "metis-pantheon", "tasks")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, TID + ".md"), "w", encoding="utf-8") as fh:
        fh.write(CARD % (TID, ITEM))
    b.view(SHA, head={"body": f"Closes {TID}", "headRefName": "feature"})
    b.records = []
    b.add("tests", who="")
    extra = {} if criteria is None else {"criteria": criteria}
    b.add("accept", sid="s1", aid="a1", **extra)
    b.add("accept", sid="s2", aid="a2", **extra)
    return b


def mutant_plugin(tmp):
    """Копия плагина pantheon, где cmd_request не зовёт review_criteria_gap → путь к её run.py. Рядом — ссылка на
    настоящий guard: соседний плагин на том же месте, что в репозитории."""
    plugins = os.path.join(tmp, "mut", "plugins")
    plug = os.path.join(plugins, "pantheon")
    shutil.copytree(os.path.dirname(LIBDIR), plug,
                    ignore=shutil.ignore_patterns("__pycache__", "tests", ".git"))
    os.symlink(os.path.dirname(GUARD_HOOKS), os.path.join(plugins, "guard"))
    f = os.path.join(plug, "lib", "merge.py")
    src = open(f, encoding="utf-8").read()
    if src.count(CALL) != 1:
        return None
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(src.replace(CALL, "merge_conflict(view)"))
    return os.path.join(plug, "lib", "run.py")


def unmarked_refused(b, run_py=RUN_PY):
    """Случай: заявка на PR с неотмеченным пунктом — код 1, причина с пунктом, заявки нет."""
    r = subprocess.run([PY311, "-I", run_py, "merge", "request", str(PR), "-R", REPO], env=b.env(T0),
                       capture_output=True, text=True, timeout=120)
    return (r.returncode == 1 and f"{TID}#1" in r.stderr and "нет отметки argus" in r.stderr
            and b.req() is None), r.stdout + r.stderr


def test_unmarked_item_no_request():
    b = box()
    ok, out = unmarked_refused(b)
    check("merge request: пункт без отметки argus на head — код 1, «metis-0001#1 … нет отметки argus», заявки нет",
          ok, out)


def test_marked_items_request():
    b = box([f"{TID}#1 {T.criterion_hash(ITEM)} да tests/t.py:1"])
    r = b.request()
    check("merge request: «да» на каждом пункте в «принять» на head — заявка стоит", r.returncode == 0 and b.req()
          and b.req()["sha"] == SHA, b.outs[-1])


def test_batch_branch_story_not_required():
    """metis-1232: у PR пачки (ветка batch/<story>) пунктов story не требуют; Closes-задачи — как обычно."""
    b = box()
    b.view(SHA, head={"body": "Closes metis-0002", "headRefName": f"batch/{TID}"})
    r = b.request()
    check("merge request: ветка batch/metis-0001, пункт story не отмечен, «Closes metis-0002» — заявка стоит",
          r.returncode == 0 and b.req() and b.req()["sha"] == SHA, b.outs[-1])
    b2 = box()
    b2.view(SHA, head={"body": f"Closes {TID}", "headRefName": f"batch/{TID}"})
    ok, out = unmarked_refused(b2)
    check("merge request: ветка batch/…, но «Closes metis-0001» с неотмеченным пунктом — по-прежнему отказ", ok, out)


def test_mutant_no_gap_call():
    b = box()
    run_py = mutant_plugin(b.tmp)
    check("мутант: строка вызова review_criteria_gap в merge.py одна", run_py is not None, CALL)
    if run_py:
        ok, out = unmarked_refused(b, run_py)
        check("мутант merge.py без вызова review_criteria_gap убит случаем «пункт без отметки — заявки нет»",
              not ok and b.req() is not None, out)


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    cases = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    run_cases(cases, FAILS, lambda name, err: FAILS.append(name))
    print(f"\n{'ПРОВАЛ: ' + ', '.join(FAILS) if FAILS else f'{len(cases)} из {len(cases)} случаев прошли'}")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
