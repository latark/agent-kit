#!/usr/bin/env python3
"""Тесты scripts/revert_check.py (metis-1176, metis-1182): выбор файлов из диффа PR и итог «тест ловит откат».

Временный git-репозиторий (корень — mkroot из _py311.py) с выдуманным плагином plugins/demo: main — база, ветка pr —
правка. Итог — последняя строка «итог: <статус> — …» и код выхода по статусу. Случаи: PR только с тестами или только с
документами — «пропуск», код 0; исходники без тестов — «не мерили», код 3; новые тесты зелёные на базе — «не ловит»,
код 1; один упал на базе — «ловит», код 0; ImportError нового модуля — упал; помощник tests/_*.py берётся из HEAD;
тест, который падает и на HEAD, — «не мерило»; списки раннера, SLOW и TIMEOUT, STUBS — из подменённого раннера
(--runner), а не настоящих списков; заглушка scutil настоящего раннера при RUN_TESTS_PLATFORM=linux; среда без
PANTHEON_*, HOME ≠ TMPDIR; свой таймаут — «упал»; предел прогона --budget — «не успел», «не мерили», код 3; -j 2 —
файлы идут сразу; внук с унаследованным stdout ожидание не держит, внуки гаснут (killpg); SIGTERM — «прервано», код 4,
внуки и копии убраны; в выводе упавшего — строка «НЕ ПРОШЁЛ» из начала лога; сводка шага и аннотация CI; нет base —
«сбой», код 2; копии дерева за собой убраны.

Запуск: python3 -I plugins/pantheon/tests/test_revert_check.py  (код выхода 0 — все прошли)
"""
import contextlib
import importlib.util
import io
import os
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311, mkroot  # noqa: E402 — путь к помощнику ставится строкой выше (тесты идут с -I)

ROOT = mkroot("revert-check-")
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "revert_check.py")
REAL_RUNNER = os.path.join(os.path.dirname(SCRIPT), "run-tests.py")
OK, FAIL = [], []

LIB = "def f():\n    return 1\n"
LIB2 = "def f():\n    return 2\n"
# тест демо-плагина: импорт lib из папки плагина, проверка значения, код выхода — итог
DEMO_TEST = ("import os, sys\nsys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n"
             "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n{body}\n")
CATCH = "import lib\nsys.exit(0 if lib.f() == 2 else 1)"  # зелёный на HEAD (LIB2), красный на базе (LIB)
# подменённый раннер: настоящий run-tests.py (make_stubs, PLATFORM), поверх — свои списки и пределы
FAKE_RUNNER = """import importlib.util
_spec = importlib.util.spec_from_file_location("rt_real_for_fake", {real!r})
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
_m.STUBS = {{**_m.STUBS, **{stubs!r}}}
STUBS, PLATFORM, make_stubs = _m.STUBS, _m.PLATFORM, _m.make_stubs
SKIP_NOT_MAC = {skip!r}
QUARANTINE = {quarantine!r}
SLOW = {slow!r}
TIMEOUT = {timeout!r}
"""


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


def fake_runner(name, skip=None, quarantine=None, slow=None, timeout=600, stubs=None):
    """Файл подменённого раннера → путь (для --runner)."""
    path = os.path.join(ROOT, f"runner-{name}.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(FAKE_RUNNER.format(real=REAL_RUNNER, stubs=stubs or {}, skip=skip or {}, quarantine=quarantine or {},
                                    slow=slow or {}, timeout=timeout))
    return path


def run(repo, *extra, env_add=None, timeout="60"):
    env = {"PATH": os.environ["PATH"], "HOME": ROOT, "TMPDIR": ROOT, **(env_add or {})}
    lim = ["--timeout", timeout] if timeout else []
    return subprocess.run([PY311, "-I", SCRIPT, "--base", "main", "--repo", repo, *lim, *extra],
                          capture_output=True, text=True, env=env, timeout=300)


def last(r):
    return (r.stdout.strip().splitlines() or [""])[-1]


def load():
    spec = importlib.util.spec_from_file_location("revert_check", SCRIPT)
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    return rc


def alive(pid):
    """Процесс жив (зомби — нет)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(r.stdout.strip()) and not r.stdout.strip().startswith("Z")


def all_dead(pids, wait=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait:
        if not any(alive(p) for p in pids):
            return True
        time.sleep(0.2)
    return False


def read_pids(path):
    try:
        with open(path) as fh:
            return [int(x) for x in fh.read().split()]
    except FileNotFoundError:
        return []


def t_classify():
    rc = load()
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
    check("(а) PR только с тестами и документами — «пропуск», код 0",
          r.returncode == 0 and last(r).startswith("итог: пропуск — PR не меняет исходников"), r.stdout + r.stderr)
    repo = make("only-docs", {"README.md": "демо 2\n"})
    r = run(repo)
    check("(а) PR только с документами — «пропуск», код 0",
          r.returncode == 0 and last(r).startswith("итог: пропуск — PR не меняет исходников"), r.stdout + r.stderr)
    repo = make("only-src", {"plugins/demo/lib.py": LIB2, "README.md": "демо 2\n"})
    r = run(repo)
    check("(б) Д1: исходники без тестов — не зелёный пропуск: «не мерили», код 3, файл исходника в выводе",
          r.returncode == 3 and last(r).startswith("итог: не мерили — PR меняет исходники (1), но не добавляет")
          and "исходники PR: plugins/demo/lib.py" in r.stdout, r.stdout + r.stderr)


def t_green():
    # правка исходника, новый тест зелёный и на базе; помощник _h.py есть только в HEAD — без него ImportError
    repo = make("green", {"plugins/demo/lib.py": LIB + "\n\ndef g():\n    return 3\n",
                          "plugins/demo/tests/_h.py": "WANT = 1\n",
                          "plugins/demo/tests/test_new.py": DEMO_TEST.format(
                              body="import lib, _h\nsys.exit(0 if lib.f() == _h.WANT else 1)")})
    r = run(repo)
    check("(в) новые тесты зелёные на базе — «не ловит», код 1, с именем файла",
          r.returncode == 1 and last(r).startswith("итог: не ловит — plugins/demo/tests/test_new.py зелёные")
          and "нужен случай, который краснеет без правки" in last(r), r.stdout + r.stderr)
    check("(в) копия базы убрана: в git worktree list одна запись", g(repo, "worktree", "list").count("\n") == 1,
          g(repo, "worktree", "list"))


def t_caught():
    repo = make("caught", {"plugins/demo/lib.py": LIB2,
                           "plugins/demo/tests/test_old.py": DEMO_TEST.format(body=CATCH),
                           "plugins/demo/tests/test_other.py": DEMO_TEST.format(body="sys.exit(0)")})
    r = run(repo)
    check("(г) один из тестов упал на базе — «ловит», код 0, строка «упал на merge-base» с этим файлом",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_old.py (код 1)" in r.stdout
          and "зелёный на merge-base: plugins/demo/tests/test_other.py" in r.stdout
          and last(r).startswith("итог: ловит — откат ловят 1 из 2"), r.stdout + r.stderr)
    repo = make("import", {"plugins/demo/newmod.py": "def h():\n    return 5\n",
                           "plugins/demo/tests/test_newmod.py": DEMO_TEST.format(
                               body="import newmod\nsys.exit(0 if newmod.h() == 5 else 1)")})
    r = run(repo)
    check("(д) новый тест нового модуля — ImportError на базе считается «упал», код 0",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_newmod.py" in r.stdout
          and "ModuleNotFoundError" in r.stdout, r.stdout + r.stderr)


def t_tail():
    # Д3: причина падения в начале длинного лога — в итоге, хотя она далеко от последних TAIL строк
    body = ("import lib\nif lib.f() == 1:\n    print('НЕ ПРОШЁЛ: важный случай')\n"
            "    for i in range(30):\n        print('шум', i)\n    sys.exit(1)\nsys.exit(0)")
    repo = make("tail", {"plugins/demo/lib.py": LIB2, "plugins/demo/tests/test_tail.py": DEMO_TEST.format(body=body)})
    r = run(repo)
    check("Д3: строка «НЕ ПРОШЁЛ» из начала лога и хвост с «…» между ними — в выводе упавшего",
          r.returncode == 0 and "    НЕ ПРОШЁЛ: важный случай" in r.stdout and "    …" in r.stdout
          and "    шум 29" in r.stdout and "    шум 10" not in r.stdout, r.stdout + r.stderr)
    rc = load()
    lines = ["a", "Traceback (most recent call last):", "b", "c", "d", "e", "f", "g", "h"]
    check("pick_lines: строка с меткой, «…», последние TAIL", rc.pick_lines(lines, n=2) ==
          ["Traceback (most recent call last):", "…", "g", "h"], rc.pick_lines(lines, n=2))


def t_notmeter():
    # тест падает и на HEAD (среда, а не откат) — не мерило; других нет — пропуск, а не «откат ловят»
    repo = make("notmeter", {"plugins/demo/lib.py": LIB2,
                             "plugins/demo/tests/test_env_bad.py": DEMO_TEST.format(body="sys.exit(1)")})
    r = run(repo)
    check("(е) тест падает и на HEAD — «не мерило», итог «пропуск — мерила нет», код 0, без «откат ловят»",
          r.returncode == 0 and "не мерило: падает и на HEAD — plugins/demo/tests/test_env_bad.py (код 1)" in r.stdout
          and "упал на merge-base" not in r.stdout and "откат ловят" not in r.stdout
          and last(r).startswith("итог: пропуск — мерила нет"), r.stdout + r.stderr)
    repo = make("notmeter-mix", {"plugins/demo/lib.py": LIB + "\n\ndef g():\n    return 3\n",
                                 "plugins/demo/tests/test_env_bad.py": DEMO_TEST.format(body="sys.exit(1)"),
                                 "plugins/demo/tests/test_green.py": DEMO_TEST.format(body="sys.exit(0)")})
    r = run(repo)
    check("(е) не мерило + зелёный на базе — «не ловит», код 1, только по мерилу",
          r.returncode == 1 and last(r).startswith("итог: не ловит — plugins/demo/tests/test_green.py зелёные"),
          r.stdout + r.stderr)


def t_runner_lists():
    # Д4: SKIP_NOT_MAC (вне macOS) и QUARANTINE — из подменённого раннера, а не настоящих списков run-tests.py
    runner = fake_runner("lists", skip={"demo/test_mac.py": ("подмена: только macOS", None),
                                        "demo/test_unless.py": ("подмена: есть sh", "/bin/sh")},
                         quarantine={"demo/test_q.py": "metis-9999"})
    repo = make("lists", {"plugins/demo/lib.py": LIB2,
                          "plugins/demo/tests/test_mac.py": "import sys\nsys.exit(1)\n",
                          "plugins/demo/tests/test_q.py": "import sys\nsys.exit(1)\n",
                          "plugins/demo/tests/test_unless.py": DEMO_TEST.format(body=CATCH)})
    r = run(repo, "--runner", runner, env_add={"RUN_TESTS_PLATFORM": "linux"})
    check("Д4: SKIP_NOT_MAC и QUARANTINE подменённого раннера — пропуск файла с причиной; программа unless есть — идёт",
          r.returncode == 0 and "пропуск файла: plugins/demo/tests/test_mac.py — нужен macOS — подмена: только macOS"
          in r.stdout and "пропуск файла: plugins/demo/tests/test_q.py — карантин раннера, задача metis-9999" in r.stdout
          and "упал на merge-base: plugins/demo/tests/test_unless.py" in r.stdout and "не мерило" not in r.stdout
          and last(r).startswith("итог: ловит — откат ловят 1 из 1"), r.stdout + r.stderr)
    r = run(repo, "--runner", runner, env_add={"RUN_TESTS_PLATFORM": "darwin"})
    check("Д4: на darwin SKIP_NOT_MAC не пропускает — test_mac.py идёт и падает на HEAD",
          "не мерило: падает и на HEAD — plugins/demo/tests/test_mac.py" in r.stdout
          and "пропуск файла: plugins/demo/tests/test_mac.py" not in r.stdout, r.stdout + r.stderr)


def t_limits():
    # предел файла — SLOW раннера, иначе его TIMEOUT, а не свой 300: оба файла идут 3 с
    runner = fake_runner("limits", slow={"demo/test_slow.py": 30}, timeout=2)
    sleepy = "import time\ntime.sleep(3)\n"
    repo = make("limits", {"plugins/demo/lib.py": LIB2,
                           "plugins/demo/tests/test_slow.py": DEMO_TEST.format(body=sleepy + CATCH),
                           "plugins/demo/tests/test_fast.py": DEMO_TEST.format(body=sleepy + "sys.exit(0)")})
    r = run(repo, "--runner", runner, "-j", "2", timeout=None)
    check("SLOW раннера — предел тяжёлого файла: мерит и падает на базе; без SLOW — TIMEOUT раннера (таймаут на HEAD)",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_slow.py (код 1)" in r.stdout
          and "не мерило: падает и на HEAD — plugins/demo/tests/test_fast.py (таймаут)" in r.stdout,
          r.stdout + r.stderr)


def t_stubs():
    # Д5: вне macOS заглушки STUBS раннера — в PATH файла теста
    runner = fake_runner("stubs", stubs={"zz-revert-stub": "echo stub-ok"})
    body = ("import shutil, subprocess\nw = shutil.which('zz-revert-stub')\n"
            "out = subprocess.run([w], capture_output=True, text=True).stdout.strip() if w else ''\n"
            "if out != 'stub-ok':\n    print('нет заглушки', w); sys.exit(1)\n" + CATCH)
    repo = make("stubs", {"plugins/demo/lib.py": LIB2, "plugins/demo/tests/test_stub.py": DEMO_TEST.format(body=body)})
    r = run(repo, "--runner", runner, env_add={"RUN_TESTS_PLATFORM": "linux"})
    check("Д5: заглушка STUBS в PATH файла при RUN_TESTS_PLATFORM=linux — мерит и падает на базе",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_stub.py (код 1)" in r.stdout
          and "не мерило" not in r.stdout, r.stdout + r.stderr)
    # заглушка scutil настоящего раннера: RUN_TESTS_PLATFORM=linux и scutil нет на PATH
    rc = load()
    empty = os.path.join(ROOT, "empty-path")
    scratch = os.path.join(ROOT, "stub-scratch")
    os.makedirs(empty)
    os.makedirs(scratch)
    saved = {k: os.environ.get(k) for k in ("RUN_TESTS_PLATFORM", "PATH")}
    try:
        os.environ.update(RUN_TESTS_PLATFORM="linux", PATH=empty)
        env = rc.base_env(rc.load_runner(), scratch)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    first = env["PATH"].split(os.pathsep)[0]
    out = subprocess.run(["/bin/sh", os.path.join(first, "scutil")], capture_output=True, text=True).stdout.strip()
    check("заглушка scutil настоящего раннера при RUN_TESTS_PLATFORM=linux — первой в PATH, печатает linux-host",
          first.startswith(scratch) and out == "linux-host", (env["PATH"], out))


def t_env():
    # среда как у раннера: PANTHEON_* сняты, HOME и TMPDIR разные, NO_COLOR=1; утечка — тест падает и на HEAD
    body = ("bad = [k for k in os.environ if k.startswith('PANTHEON_')]\n"
            "if bad or os.environ['HOME'] == os.environ['TMPDIR'] or os.environ.get('NO_COLOR') != '1':\n"
            "    print('среда:', bad); sys.exit(1)\n" + CATCH)
    repo = make("env", {"plugins/demo/lib.py": LIB2, "plugins/demo/tests/test_env.py": DEMO_TEST.format(body=body)})
    r = run(repo, env_add={"PANTHEON_HOST": "leak", "PANTHEON_LEAK": "1"})
    check("PANTHEON_* сняты, HOME ≠ TMPDIR, NO_COLOR=1 — тест мерит и падает на базе, код 0",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_env.py (код 1)" in r.stdout
          and "не мерило" not in r.stdout, r.stdout + r.stderr)


def t_timeout():
    # на базе файл висит — таймаут = «упал»; на HEAD f() == 2, проходит сразу
    hang = DEMO_TEST.format(body="import lib, time\nif lib.f() == 1:\n    time.sleep(60)\nsys.exit(0)")
    repo = make("hang", {"plugins/demo/lib.py": LIB2, "plugins/demo/tests/test_hang.py": hang})
    t0 = time.monotonic()
    r = run(repo, timeout="2")
    check("--timeout 2: зависший на базе тест — «упал на merge-base (таймаут)», код 0, без ожидания 60 с",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_hang.py (таймаут)" in r.stdout
          and time.monotonic() - t0 < 40, r.stdout + r.stderr)
    # внук с унаследованным stdout живёт 60 с, сам файл выходит с кодом 1: вывод в файл — ожидание не держится
    kid = DEMO_TEST.format(body="import lib, subprocess\nif lib.f() == 1:\n    subprocess.Popen(['sleep', '60'])\n"
                                "    sys.exit(1)\nsys.exit(0)")
    repo = make("grandkid", {"plugins/demo/lib.py": LIB2, "plugins/demo/tests/test_kid.py": kid})
    t0 = time.monotonic()
    r = run(repo, timeout="30")
    check("внук держит stdout — итог «код 1», а не таймаут; ждёт меньше предела",
          r.returncode == 0 and "упал на merge-base: plugins/demo/tests/test_kid.py (код 1)" in r.stdout
          and time.monotonic() - t0 < 25, r.stdout + r.stderr)


def t_killpg():
    # Д5: внук файла (sleep 60, вывод не держит) после выхода файла гаснет вместе с группой
    pidfile = os.path.join(ROOT, "killpg.pids")
    body = ("import subprocess\np = subprocess.Popen(['sleep', '60'], stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL)\nopen(os.environ['RC_PIDFILE'], 'a').write(f'{p.pid}\\n')\n" + CATCH)
    repo = make("killpg", {"plugins/demo/lib.py": LIB2, "plugins/demo/tests/test_kpg.py": DEMO_TEST.format(body=body)})
    r = run(repo, env_add={"RC_PIDFILE": pidfile})
    pids = read_pids(pidfile)
    check("Д5: внуки файла на HEAD и на базе погашены killpg после выхода файла",
          r.returncode == 0 and len(pids) == 2 and all_dead(pids), (pids, r.stdout + r.stderr))


def t_budget():
    # предел прогона: файл, оборванный --budget, и файл, не начатый до него, — «не успел», итог «не мерили», код 3
    repo = make("budget", {"plugins/demo/lib.py": LIB2,
                           "plugins/demo/tests/test_a.py": DEMO_TEST.format(body="import time\ntime.sleep(30)\n" + CATCH),
                           "plugins/demo/tests/test_b.py": DEMO_TEST.format(body=CATCH)})
    t0 = time.monotonic()
    r = run(repo, "--budget", "3", "-j", "1")
    check("--budget 3: «не успел» у обоих, не таймаут и не «не мерило»; «не мерили», код 3, быстро",
          r.returncode == 3 and "не успел: plugins/demo/tests/test_a.py" in r.stdout
          and "не успел: plugins/demo/tests/test_b.py" in r.stdout and "таймаут" not in r.stdout
          and "не мерило" not in r.stdout and last(r).startswith("итог: не мерили — не успели 2")
          and time.monotonic() - t0 < 25, r.stdout + r.stderr)
    rc = load()
    st, _, final = rc.verdict({"x": (1, []), "y": (rc.LATE, [])})
    check("verdict: упал один, другой не успел — «ловит»", st == "ловит" and "1 из 2" in final, (st, final))


def t_jobs():
    # -j 2: два файла ждут друг друга (метки в RC_SYNC); по одному первый не дождётся второго и упадёт на HEAD
    sync = os.path.join(ROOT, "sync")
    os.makedirs(sync)
    body = ("import time\nd = os.environ['RC_SYNC']\ncopy = os.path.basename(os.path.dirname(os.path.dirname(os.getcwd())))\n"
            "me = os.path.basename(__file__)\nother = 'test_p2.py' if me == 'test_p1.py' else 'test_p1.py'\n"
            "open(os.path.join(d, copy + '-' + me), 'w').close()\nt0 = time.monotonic()\n"
            "while not os.path.exists(os.path.join(d, copy + '-' + other)):\n"
            "    if time.monotonic() - t0 > 8:\n        print('не дождался', other); sys.exit(1)\n"
            "    time.sleep(0.1)\n" + CATCH)
    repo = make("jobs", {"plugins/demo/lib.py": LIB2, "plugins/demo/tests/test_p1.py": DEMO_TEST.format(body=body),
                         "plugins/demo/tests/test_p2.py": DEMO_TEST.format(body=body)})
    r = run(repo, "-j", "2", env_add={"RC_SYNC": sync})
    check("Д2: -j 2 — файлы идут сразу (ждут друг друга), оба мерят и падают на базе",
          r.returncode == 0 and last(r).startswith("итог: ловит — откат ловят 2 из 2") and "не мерило" not in r.stdout
          and "-j 2" in r.stdout, r.stdout + r.stderr)


def t_interrupt():
    # отменённый job: SIGTERM во время прогона — «прервано», код 4, внуки и копии дерева убраны
    pidfile = os.path.join(ROOT, "interrupt.pids")
    body = ("import subprocess, time\np = subprocess.Popen(['sleep', '60'], stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL)\nopen(os.environ['RC_PIDFILE'], 'a').write(f'{p.pid}\\n')\n"
            "time.sleep(60)\n" + CATCH)
    repo = make("interrupt", {"plugins/demo/lib.py": LIB2,
                              "plugins/demo/tests/test_int.py": DEMO_TEST.format(body=body)})
    env = {"PATH": os.environ["PATH"], "HOME": ROOT, "TMPDIR": ROOT, "RC_PIDFILE": pidfile}
    p = subprocess.Popen([PY311, "-I", SCRIPT, "--base", "main", "--repo", repo, "--timeout", "120"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    t0 = time.monotonic()
    while not read_pids(pidfile) and time.monotonic() - t0 < 30:
        time.sleep(0.2)
    p.send_signal(signal.SIGTERM)
    try:
        out, _ = p.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        p.kill()
        out, _ = p.communicate()
    lines = out.strip().splitlines() or [""]
    check("SIGTERM (отмена job) — «итог: прервано», код 4, это не «не ловит»; внук погашен; копий дерева нет",
          p.returncode == 4 and lines[-1].startswith("итог: прервано — job отменён (SIGTERM)")
          and "не ловит —" not in out and all_dead(read_pids(pidfile))
          and g(repo, "worktree", "list").count("\n") == 1, (p.returncode, out))


def t_ci_report():
    rc = load()
    summary = os.path.join(ROOT, "summary.md")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc.report_ci("x зелёные", "не ловит", {"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": summary})
        rc.report_ci("ok", "ловит", {"GITHUB_ACTIONS": "true"})
        rc.report_ci("тихо", "пропуск", {})
        rc.report_ci("y", "сбой", {"GITHUB_STEP_SUMMARY": ROOT})  # папка — не записать
    with open(summary, encoding="utf-8") as fh:
        text = fh.read()
    out = buf.getvalue()
    check("CI: аннотация ::warning у красного, ::notice у зелёного, итог в сводке шага; вне CI — молча",
          "::warning title=revert-check: не ловит::x зелёные" in out and "::notice title=revert-check: ловит::ok" in out
          and "тихо" not in out and text == "### revert-check: не ловит\n\nx зелёные\n", (out, text))
    check("CI: сводка шага не записана — строка о сбое, без исключения",
          "revert-check: сводка шага не записана" in out, out)


def t_error():
    repo = make("err", {"plugins/demo/lib.py": LIB2})
    r = run(repo, "--base", "нет-такой-ветки")
    check("нет base — «сбой», код 2 и причина последней строкой",
          r.returncode == 2 and last(r).startswith("итог: сбой — git merge-base"), r.stdout + r.stderr)


def main():
    try:
        for t in (t_classify, t_skip, t_green, t_caught, t_tail, t_notmeter, t_runner_lists, t_limits, t_stubs,
                  t_env, t_timeout, t_killpg, t_budget, t_jobs, t_interrupt, t_ci_report, t_error):
            t()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
    print(f"{len(OK)} из {len(OK) + len(FAIL)} прошли")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
