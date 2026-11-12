#!/usr/bin/env python3
"""Лёгкий PR ядра (metis-1065, решение владельца 12.11, Р2): шлюз владельца (lib/merge.py, gate) засчитывает одно
«принять» argus вместо двух, если по записям REST pulls/N/files в PR только добавленные строки тестов и документы
README*.md, drafts/*.md, а «принять» — от argus на Opus с effort high по транскрипту (поле efforts записи хука guard).

Запуск: python3 -I plugins/pantheon/tests/test_merge_light.py  (код выхода 0 — все прошли)
Поддельные gh и помощник окна — из test_merge (Box). Проверяет: одни добавленные тесты — 1; удалённая строка в тесте,
run-tests.py, AGENTS.md, roles/*.tmpl, код с тестом, переименование теста — 2; README — 1; одно «принять» Opus medium
и без efforts — не хватает; список файлов не получен — заявка ждёт. И что light_pr, light_accept и LIGHT_* в merge.py
дословно те же, что в шлюзе guard (merge_gate.py), — сверка по AST.
"""
import ast
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_merge as tm  # noqa: E402  (Box, check, поддельные gh и окно)

OPUS_HIGH = {"models": ["claude-opus-5-5"], "efforts": ["high"]}
NAMES = ("light_pr", "light_accept", "light_same_head", "LIGHT_EFFORT", "LIGHT_TEST_RE", "LIGHT_DOC_RE", "LIGHT_NOT_RE")


def added(path, n=5):
    return {"filename": path, "status": "added", "additions": n, "deletions": 0}


def modified(path, plus=3, minus=0):
    return {"filename": path, "status": "modified", "additions": plus, "deletions": minus}


def box(files, accepts=(OPUS_HIGH,)):
    """PR из files с записью тестов и «принять» argus: по одному на словарь полей accepts (models, efforts)."""
    b = tm.Box()
    b.records = []
    b.add("tests", who="")
    for i, extra in enumerate(accepts, 1):
        b.add("accept", sid=f"s{i}", aid=f"a{i}", **extra)
    b.view(tm.SHA, files=files)
    return b


def one_enough(name, files, accepts=(OPUS_HIGH,)):
    """Заявка ставится и проход сливает по одному «принять» — лёгкий PR ядра, текст окна называет путь."""
    b = box(files, accepts)
    r = b.request()
    tm.check(f"{name}: заявка стоит", r.returncode == 0 and b.req() is not None, r.stderr)
    b.run()
    w = b.windows()
    tm.check(f"{name}: окно называет лёгкий PR ядра и 1 argus Opus high",
             len(w) == 1 and "лёгкий PR ядра" in w[0][0] and "1 argus Opus high" in w[0][0] and "argus ×1 ✓" in w[0][0],
             w)
    tm.check(f"{name}: слито", len(b.merges()) == 1, b.outs[-1])


def two_needed(name, files, accepts=(OPUS_HIGH,), why=""):
    """Одного «принять» мало: заявки нет, отказ «1 из 2» с причиной."""
    b = box(files, accepts)
    r = b.request()
    tm.check(f"{name}: отказ «1 из 2»" + (f" — «{why}»" if why else ""),
             r.returncode != 0 and b.req() is None and "1 из 2" in r.stderr and why in r.stderr, r.stderr)


def test_light_one():
    one_enough("одни добавленные тесты", [added("plugins/guard/tests/test_new.py"),
                                         modified("plugins/pantheon/tests/test_merge.py", 7, 0)])
    one_enough("README (и с удалёнными строками) и drafts", [modified("README.md", 4, 2),
                                                          modified("plugins/guard/readme.MD", 1, 1),
                                                          added("drafts/1065-plan.md")])
    one_enough("тест и README", [added("plugins/guard/tests/fixtures/case.json"), modified("README.md", 1, 0)])


def test_light_two():
    t = "plugins/guard/tests/test_merge_gate.py"
    two_needed("удалённая строка в тесте", [modified(t, 3, 1)], why="удалены строки")
    two_needed("run-tests.py (QUARANTINE)", [modified("plugins/pantheon/scripts/run-tests.py", 1, 0)],
               why="пропуски раннера")
    two_needed("AGENTS.md", [modified("AGENTS.md", 1, 0)], why="инструкция агентам")
    two_needed("roles/*.tmpl", [modified("plugins/pantheon/roles/argus.tmpl", 1, 0)], why="инструкция агентам")
    two_needed("код и тест", [modified("plugins/pantheon/lib/merge.py", 5, 0), added("plugins/pantheon/tests/t.py")],
               why="не тест и не документ")
    two_needed("переименование теста",
               [{"filename": "plugins/guard/tests/test_b.py", "previous_filename": "plugins/guard/tests/test_a.py",
                 "status": "renamed", "additions": 0, "deletions": 0}], why="renamed")
    two_needed("удалённый тест", [{"filename": t, "status": "removed", "additions": 0, "deletions": 9}],
               why="removed")
    two_needed("README в roles/", [modified("plugins/pantheon/roles/README.md", 1, 0)], why="инструкция агентам")
    two_needed("SKILL.md", [modified("plugins/pantheon/skills/x/SKILL.md", 1, 0)], why="инструкция агентам")
    two_needed("другой .md (не README, не drafts)", [modified("plugins/pantheon/template/pantheon/board.md", 1, 0)],
               why="инструкция агентам")
    two_needed("план вне drafts/", [added("plugins/pantheon/docs/plan.md")], why="не тест и не документ")


def test_light_accept_needed():
    tests_only = [added("plugins/guard/tests/test_new.py")]
    two_needed("одно «принять» Opus medium на лёгком PR", tests_only,
               ({"models": ["claude-opus-5-5"], "efforts": ["medium"]},), why="effort high")
    two_needed("одно «принять» без efforts (запись до metis-1065)", tests_only,
               ({"models": ["claude-opus-5-5"]},), why="effort high")
    two_needed("одно «принять» high и medium в одном транскрипте", tests_only,
               ({"models": ["claude-opus-5-5"], "efforts": ["high", "medium"]},), why="effort high")
    two_needed("одно «принять» без models (транскрипта нет)", tests_only, ({"efforts": ["high"]},), why="effort high")
    # два «принять» на Opus — как раньше, effort не нужен
    b = box(tests_only, ({"models": ["claude-opus-5-5"]}, {}))
    r = b.request()
    tm.check("два «принять» на Opus без efforts — заявка стоит, как раньше", r.returncode == 0 and b.req() is not None,
             r.stderr)


def test_light_files_missing():
    """Список файлов не получен — заявка ждёт, а не проходит по одному «принять» и не снимается."""
    b = box([added("plugins/guard/tests/test_new.py")])
    r = b.request()
    tm.check("файлы есть: заявка стоит", r.returncode == 0 and b.req() is not None, r.stderr)
    os.remove(os.path.join(b.rec, "gh-files.jsonl"))
    b.run()
    req = b.req()
    tm.check("файлы не получены: окна нет, слияния нет, заявка ждёт с причиной «лёгкий ли PR ядра»",
             not b.windows() and not b.merges() and req is not None and "лёгкий ли PR ядра" in str(req.get("waiting")),
             (b.outs[-1], req))
    b = box([added("plugins/guard/tests/test_new.py")])
    b.view(tm.SHA, files=[added("plugins/guard/tests/test_new.py")], count=2)
    r = b.request()
    tm.check("список неполон (changedFiles 2, записей 1): заявка ждёт «лёгкий ли PR ядра», а не проходит",
             r.returncode == 0 and b.req() is not None and "лёгкий ли pr ядра" in r.stdout.lower(),
             (r.returncode, r.stdout, r.stderr))
    b.run()
    tm.check("список неполон: проход не сливает и окна не показывает", not b.windows() and not b.merges(), b.outs[-1])


# обёртка поддельного gh: после первого запроса REST pulls/N/files подменяет ответ gh pr view файлом rec/gh-view-after.json
# — push в PR, пока шлюз читал список файлов (TOCTOU, metis-1065)
SWAP_GH = r'''
import os, subprocess, sys
rec = os.environ["FAKE_REC"]
r = subprocess.run([os.path.join(os.path.dirname(os.path.abspath(__file__)), "gh-real")] + sys.argv[1:])
after = os.path.join(rec, "gh-view-after.json")
if sys.argv[1:2] == ["api"] and "/files" in sys.argv[2] and os.path.exists(after):
    os.replace(after, os.path.join(rec, "gh-view.json"))
sys.exit(r.returncode)
'''


def swap_box(after):
    """Лёгкий PR и одно «принять» Opus high; after — новый ответ gh pr view после списка файлов (None — сбой gh)."""
    b = box([added("plugins/guard/tests/test_new.py")])
    os.replace(os.path.join(b.bin, "gh"), os.path.join(b.bin, "gh-real"))
    tm.script(os.path.join(b.bin, "gh"), SWAP_GH)
    with open(os.path.join(b.rec, "gh-view.json")) as fh:
        view = json.load(fh)
    with open(os.path.join(b.rec, "gh-view-after.json"), "w") as fh:
        fh.write("не json" if after is None else json.dumps(dict(view, **after)))
    return b


def test_light_head_swap():
    """После списка файлов gh pr view ещё раз: head или changedFiles сменились — не лёгкий, нужно 2; gh не ответил —
    заявка ждёт; всё то же — лёгкий (контроль обёртки)."""
    b = swap_box({})
    r = b.request()
    tm.check("head и число файлов те же после списка файлов: заявка стоит без ожидания (лёгкий, одно «принять»)",
             r.returncode == 0 and b.req() is not None and "закончатся" not in r.stdout, (r.stdout, r.stderr))
    for name, after, why in (("head сменился между запросами", {"headRefOid": "f" * 40}, "сменились"),
                             ("changedFiles сменилось между запросами", {"changedFiles": 2}, "сменились")):
        b = swap_box(after)
        r = b.request()
        tm.check(f"{name}: не лёгкий — отказ «1 из 2», «{why}»",
                 r.returncode != 0 and b.req() is None and "1 из 2" in r.stderr and why in r.stderr, r.stderr)
    b = swap_box(None)
    r = b.request()
    tm.check("второй gh pr view не ответил: заявка ждёт сверки head, а не проходит",
             r.returncode == 0 and "при сверке head" in r.stdout and not b.merges(), (r.stdout, r.stderr))


def test_light_same_as_guard():
    """light_pr, light_accept и LIGHT_* в merge.py дословно те же, что в merge_gate.py (AST)."""
    def parts(path):
        got = {}
        for n in ast.parse(open(path, encoding="utf-8").read()).body:
            if isinstance(n, ast.FunctionDef) and n.name in NAMES:
                got[n.name] = ast.dump(n)
            elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                    and n.targets[0].id in NAMES:
                got[n.targets[0].id] = ast.dump(n.value)
        return got
    mine = parts(os.path.join(tm.LIBDIR, "merge.py"))
    gate = parts(os.path.join(tm.GUARD_HOOKS, "merge_gate.py"))
    for k in NAMES:
        tm.check(f"merge.py {k} == merge_gate.py {k}", k in mine and mine.get(k) == gate.get(k), k)


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(tm.HERE)), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)], tm.FAILS,
              lambda name, err: tm.FAILS.append(name))
    print(f"\n{'ПРОВАЛ: ' + ', '.join(tm.FAILS) if tm.FAILS else 'все прошли'}")
    sys.stdout.flush()
    os._exit(1 if tm.FAILS else 0)
