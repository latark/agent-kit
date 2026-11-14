#!/usr/bin/env python3
"""Тесты scripts/revert_check.py (metis-1176): выбор файлов из диффа PR и вердикт «тест ловит откат».

Временный git-репозиторий (корень — mkroot из _py311.py) с выдуманным плагином plugins/demo: main — база, ветка pr —
правка. Случаи: PR только с тестами — пропуск; только с исходниками и документами — пропуск; новые тесты зелёные на
базе — код 1 и строка «тест не ловит откат»; один упал на базе — код 0; новый тест с ImportError нового модуля — упал,
код 0; помощник tests/_*.py берётся из HEAD; нет base — код 2; копия базы за собой убрана.

Запуск: python3 -I plugins/pantheon/tests/test_revert_check.py  (код выхода 0 — все прошли)
"""
import importlib.util
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311, mkroot  # noqa: E402 — путь к помощнику ставится строкой выше (тесты идут с -I)

ROOT = mkroot("revert-check-")
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "revert_check.py")
OK, FAIL = [], []

LIB = "def f():\n    return 1\n"
# тест демо-плагина: импорт lib из папки плагина, проверка значения, код выхода — итог
DEMO_TEST = ("import os, sys\nsys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
             "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n{body}\n")


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    if not cond:
        print(f"НЕ ПРОШЁЛ: {name} {str(detail)[-800:]}")


def g(repo, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                       cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {args}: {r.stderr}")
    return r.stdout


def put(repo, files):
    for rel, text in files.items():
        p = os.path.join(repo, rel)
        if text is None:
            os.remove(p)
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)


def make(name, pr_files):
    """Репозиторий: main с lib.py и старым тестом, ветка pr с pr_files (None — удалить) → путь."""
    repo = os.path.join(ROOT, name)
    os.makedirs(repo)
    g(repo, "init", "-q", "-b", "main")
    put(repo, {"plugins/demo/lib.py": LIB, "README.md": "демо\n",
               "plugins/demo/tests/test_old.py": DEMO_TEST.format(body="import lib\nsys.exit(0 if lib.f() == 1 else 1)")})
    g(repo, "add", "-A")
    g(repo, "commit", "-q", "-m", "база")
    g(repo, "checkout", "-q", "-b", "pr")
    put(repo, pr_files)
    g(repo, "add", "-A")
    g(repo, "commit", "-q", "-m", "pr")
    return repo


def run(repo, *extra):
    env = {"PATH": os.environ["PATH"], "HOME": ROOT, "TMPDIR": ROOT}
    return subprocess.run([PY311, "-I", SCRIPT, "--base", "main", "--repo", repo, "--timeout", "60", *extra],
                          capture_output=True, text=True, env=env, timeout=300)


def last(r):
    return (r.stdout.strip().splitlines() or [""])[-1]


def t_classify():
    spec = importlib.util.spec_from_file_location("revert_check", SCRIPT)
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    ns = ("A\tplugins/a/tests/test_x.py\nM\tplugins/b/tests/test_y.py\nD\tplugins/a/tests/test_gone.py\n"
          "A\tplugins/a/tests/_helper.py\nM\tplugins/a/tests/fixtures/f.json\nM\tplugins/a/README.md\n"
          "M\tdocs/x.md\nM\tplugins/a/lib/m.py\nD\tplugins/a/old.py\nA\tplugins/a/tests/sub/test_deep.py\n"
          "M\t.github/workflows/tests.yml\n")
    tests, sources = rc.classify(ns)
    check("classify: тесты — A/M plugins/*/tests/test_*.py прямо в tests/ (удалённый и вложенный — нет)",
          tests == ["plugins/a/tests/test_x.py", "plugins/b/tests/test_y.py"], tests)
    check("classify: исходники — вне tests/ и не *.md (удалённый исходник — тоже)",
          sources == [".github/workflows/tests.yml", "plugins/a/lib/m.py", "plugins/a/old.py"], sources)


def t_skip():
    repo = make("only-tests", {"plugins/demo/tests/test_new.py": DEMO_TEST.format(body="sys.exit(0)"),
                               "plugins/demo/tests/_h.py": "X = 1\n", "README.md": "демо 2\n"})
    r = run(repo)
    check("(а) PR только с тестами и документами — пропуск, код 0",
          r.returncode == 0 and last(r).startswith("пропуск: PR не меняет исходников"), r.stdout + r.stderr)
    repo = make("only-src", {"plugins/demo/lib.py": "def f():\n    return 2\n", "README.md": "демо 2\n"})
    r = run(repo)
    check("(б) PR только с исходниками и документами — пропуск, код 0",
          r.returncode == 0 and last(r).startswith("пропуск: PR не добавляет и не меняет тестов"), r.stdout + r.stderr)


def t_green():
    # правка исходника, новый тест зелёный и на базе; помощник _h.py есть только в HEAD — без него ImportError
    repo = make("green", {"plugins/demo/lib.py": LIB + "\n\ndef g():\n    return 3\n",
                          "plugins/demo/tests/_h.py": "WANT = 1\n",
                          "plugins/demo/tests/test_new.py": DEMO_TEST.format(
                              body="import lib, _h\nsys.exit(0 if lib.f() == _h.WANT else 1)")})
    r = run(repo)
    check("(в) новые тесты зелёные на базе — код 1, последней строкой «тест не ловит откат» с именем файла",
          r.returncode == 1 and last(r).startswith("тест не ловит откат: plugins/demo/tests/test_new.py зелёные")
          and "нужен случай, который краснеет без правки" in last(r), r.stdout + r.stderr)
    check("(в) копия базы убрана: в git worktree list одна запись", g(repo, "worktree", "list").count("\n") == 1,
          g(repo, "worktree", "list"))


def t_caught():
    repo = make("caught", {"plugins/demo/lib.py": "def f():\n    return 2\n",
                           "plugins/demo/tests/test_old.py": DEMO_TEST.format(
                               body="import lib\nsys.exit(0 if lib.f() == 2 else 1)"),
                           "plugins/demo/tests/test_other.py": DEMO_TEST.format(body="sys.exit(0)")})
    r = run(repo)
    check("(г) один из тестов упал на базе — код 0, строка «упал на merge-base» с этим файлом",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_old.py (код 1)" in r.stdout
          and "зелёный на merge-base: plugins/demo/tests/test_other.py" in r.stdout
          and last(r).startswith("ок: откат ловят 1 из 2"), r.stdout + r.stderr)
    repo = make("import", {"plugins/demo/newmod.py": "def h():\n    return 5\n",
                           "plugins/demo/tests/test_newmod.py": DEMO_TEST.format(
                               body="import newmod\nsys.exit(0 if newmod.h() == 5 else 1)")})
    r = run(repo)
    check("(д) новый тест нового модуля — ImportError на базе считается «упал», код 0",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_newmod.py" in r.stdout
          and "ModuleNotFoundError" in r.stdout, r.stdout + r.stderr)


def t_error():
    repo = make("err", {"plugins/demo/lib.py": "def f():\n    return 2\n"})
    r = run(repo, "--base", "нет-такой-ветки")
    check("нет base — код 2 и причина последней строкой", r.returncode == 2 and last(r).startswith("revert-check: сбой")
          and "merge-base" in last(r), r.stdout + r.stderr)


def main():
    try:
        for t in (t_classify, t_skip, t_green, t_caught, t_error):
            t()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    print(f"{len(OK)} из {len(OK) + len(FAIL)} прошли")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
