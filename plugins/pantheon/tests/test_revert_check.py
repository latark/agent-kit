#!/usr/bin/env python3
"""Тесты scripts/revert_check.py (metis-1176): выбор файлов из диффа PR и вердикт «тест ловит откат».

Временный git-репозиторий (корень — mkroot из _py311.py) с выдуманным плагином plugins/demo: main — база, ветка pr —
правка. Случаи: PR только с тестами — пропуск; только с исходниками и документами — пропуск; новые тесты зелёные на
базе — код 1 и строка «тест не ловит откат»; один упал на базе — код 0; новый тест с ImportError нового модуля — упал,
код 0; помощник tests/_*.py берётся из HEAD; тест, который падает и на HEAD, — «не мерило», а не «ловит»;
SKIP_NOT_MAC и QUARANTINE раннера — пропуск файла; среда без PANTHEON_*, HOME ≠ TMPDIR; таймаут (--timeout 2) — «упал»;
внук с унаследованным stdout ожидание не держит; нет base — код 2; копии дерева за собой убраны.

Запуск: python3 -I plugins/pantheon/tests/test_revert_check.py  (код выхода 0 — все прошли)
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import time

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


def run(repo, *extra, env_add=None):
    env = {"PATH": os.environ["PATH"], "HOME": ROOT, "TMPDIR": ROOT, **(env_add or {})}
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


def t_notmeter():
    # тест падает и на HEAD (среда, а не откат) — не мерило; других нет — пропуск, а не «откат ловят»
    repo = make("notmeter", {"plugins/demo/lib.py": "def f():\n    return 2\n",
                             "plugins/demo/tests/test_env_bad.py": DEMO_TEST.format(body="sys.exit(1)")})
    r = run(repo)
    check("(е) тест падает и на HEAD — «не мерило», итог «пропуск: мерила нет», код 0, без «откат ловят»",
          r.returncode == 0 and "не мерило: падает и на HEAD — plugins/demo/tests/test_env_bad.py (код 1)" in r.stdout
          and "упал на merge-base" not in r.stdout and "откат ловят" not in r.stdout
          and last(r).startswith("пропуск: мерила нет"), r.stdout + r.stderr)
    repo = make("notmeter-mix", {"plugins/demo/lib.py": LIB + "\n\ndef g():\n    return 3\n",
                                 "plugins/demo/tests/test_env_bad.py": DEMO_TEST.format(body="sys.exit(1)"),
                                 "plugins/demo/tests/test_green.py": DEMO_TEST.format(body="sys.exit(0)")})
    r = run(repo)
    check("(е) не мерило + зелёный на базе — код 1 «тест не ловит откат» только по мерилу",
          r.returncode == 1 and last(r).startswith("тест не ловит откат: plugins/demo/tests/test_green.py зелёные"),
          r.stdout + r.stderr)


def t_runner_lists():
    # SKIP_NOT_MAC (вне macOS) и QUARANTINE берутся из run-tests.py: их файлы — пропуск с причиной
    repo = make("lists", {"plugins/pantheon/lib.py": "X = 1\n",
                          "plugins/pantheon/tests/test_setup.py": "import sys\nsys.exit(1)\n",
                          "plugins/pantheon/tests/test_outside_idle.py": "import sys\nsys.exit(1)\n"})
    r = run(repo, env_add={"RUN_TESTS_PLATFORM": "linux"})
    check("SKIP_NOT_MAC и QUARANTINE раннера — пропуск файла с причиной, итог «пропуск», код 0",
          r.returncode == 0 and "пропуск файла: plugins/pantheon/tests/test_setup.py — нужен macOS" in r.stdout
          and "пропуск файла: plugins/pantheon/tests/test_outside_idle.py — карантин раннера, задача metis-" in r.stdout
          and "не мерило" not in r.stdout and last(r).startswith("пропуск: мерила нет"), r.stdout + r.stderr)


def t_env():
    # среда как у раннера: PANTHEON_* сняты, HOME и TMPDIR разные, NO_COLOR=1; утечка — тест падает и на HEAD
    body = ("bad = [k for k in os.environ if k.startswith('PANTHEON_')]\n"
            "if bad or os.environ['HOME'] == os.environ['TMPDIR'] or os.environ.get('NO_COLOR') != '1':\n"
            "    print('среда:', bad); sys.exit(1)\nimport lib\nsys.exit(0 if lib.f() == 2 else 1)")
    repo = make("env", {"plugins/demo/lib.py": "def f():\n    return 2\n",
                        "plugins/demo/tests/test_env.py": DEMO_TEST.format(body=body)})
    r = run(repo, env_add={"PANTHEON_HOST": "leak", "PANTHEON_LEAK": "1"})
    check("PANTHEON_* сняты, HOME ≠ TMPDIR, NO_COLOR=1 — тест мерит и падает на базе, код 0",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_env.py (код 1)" in r.stdout
          and "не мерило" not in r.stdout, r.stdout + r.stderr)


def t_timeout():
    # на базе файл висит — таймаут = «упал»; на HEAD f() == 2, проходит сразу
    hang = DEMO_TEST.format(body="import lib, time\nif lib.f() == 1:\n    time.sleep(60)\nsys.exit(0)")
    repo = make("hang", {"plugins/demo/lib.py": "def f():\n    return 2\n", "plugins/demo/tests/test_hang.py": hang})
    t0 = time.monotonic()
    r = run(repo, "--timeout", "2")
    check("--timeout 2: зависший на базе тест — «упал на merge-base (таймаут)», код 0, без ожидания 60 с",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_hang.py (таймаут)" in r.stdout
          and time.monotonic() - t0 < 40, r.stdout + r.stderr)
    # внук с унаследованным stdout живёт 60 с, сам файл выходит с кодом 1: вывод в файл — ожидание не держится
    kid = DEMO_TEST.format(body="import lib, subprocess\nif lib.f() == 1:\n    subprocess.Popen(['sleep', '60'])\n"
                                "    sys.exit(1)\nsys.exit(0)")
    repo = make("grandkid", {"plugins/demo/lib.py": "def f():\n    return 2\n", "plugins/demo/tests/test_kid.py": kid})
    t0 = time.monotonic()
    r = run(repo, "--timeout", "30")
    check("внук держит stdout — итог «код 1», а не таймаут; ждёт меньше предела",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_kid.py (код 1)" in r.stdout
          and time.monotonic() - t0 < 25, r.stdout + r.stderr)


def t_error():
    repo = make("err", {"plugins/demo/lib.py": "def f():\n    return 2\n"})
    r = run(repo, "--base", "нет-такой-ветки")
    check("нет base — код 2 и причина последней строкой", r.returncode == 2 and last(r).startswith("revert-check: сбой")
          and "merge-base" in last(r), r.stdout + r.stderr)


def main():
    try:
        for t in (t_classify, t_skip, t_green, t_caught, t_notmeter, t_runner_lists, t_env, t_timeout, t_error):
            t()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    print(f"{len(OK)} из {len(OK) + len(FAIL)} прошли")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
