#!/usr/bin/env python3
"""Тесты храповика scripts/lint_ratchet.py (metis-0854): временный git-репозиторий, ruff — заглушка.

Заглушка ruff берёт нарушения из пометок на строке def: `def f():  # cx C901=16 PLR0915=60`. Отдельный случай гоняет
настоящий ruff закреплённой версии (на PATH или через uvx); нет его — строка «пропущено».
Запуск: python3 -I plugins/pantheon/tests/test_lint_ratchet.py  (код выхода 0 — все прошли)
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

_ROOT = tempfile.mkdtemp(prefix="ratchet-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "lint_ratchet.py")
RUNNER = os.path.join(os.path.dirname(HERE), "scripts", "run-tests.py")
OK, FAIL = [], []

STUB = r'''
import json, os, re, sys
if os.environ.get("STUB_ARGS"):
    open(os.environ["STUB_ARGS"], "w").write(json.dumps(sys.argv[1:]))
if os.environ.get("STUB_BAD"):
    print("boom")
    sys.exit(2)
out = []
for f in [a for a in sys.argv[1:] if a.endswith(".py")]:
    for i, line in enumerate(open(f, encoding="utf-8"), 1):
        m = re.search(r"#\s*cx\s+(.*)$", line)
        if m and re.match(r"\s*(async\s+)?def\s", line):
            for code, v in re.findall(r"(\w+)=(\d+)", m.group(1)):
                out.append({"code": code, "filename": os.path.abspath(f), "location": {"row": i, "column": 5},
                            "message": "stub (%s > 1)" % v})
print(json.dumps(out))
'''
STUB_PATH = os.path.join(_ROOT, "stub_ruff.py")
with open(STUB_PATH, "w", encoding="utf-8") as _fh:
    _fh.write(STUB)


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    if not cond:
        print(f"НЕ ПРОШЁЛ: {name} {detail}")


def write(root, files):
    for rel, text in files.items():
        full = os.path.join(root, rel)
        if text is None:
            os.remove(full)
            continue
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)


def repo(files):
    root = tempfile.mkdtemp(prefix="repo-")
    subprocess.run(["git", "init", "-q", root], check=True, capture_output=True)
    write(root, files)
    return root


def run(root, *args, ruff=None, env=None):
    cmd = [sys.executable, "-I", SCRIPT, "--root", root, "--baseline", os.path.join(root, "base.json")]
    if ruff is not False:
        cmd += ["--ruff", ruff or f"{sys.executable} -I {STUB_PATH}"]
    r = subprocess.run(cmd + list(args), capture_output=True, text=True, env={**os.environ, **(env or {})})
    lines = (r.stdout + r.stderr).strip().splitlines()
    r.last = lines[-1] if lines else ""
    return r


def base(root):
    with open(os.path.join(root, "base.json"), encoding="utf-8") as fh:
        return json.load(fh)


def body(n):
    """Текст файла ровно в n строк."""
    return "".join(f"x{i} = {i}\n" for i in range(n))


def started(files):
    """Репозиторий с записанной базой."""
    root = repo(files)
    r = run(root, "--init")
    assert r.returncode == 0, r.stdout + r.stderr
    return root


def t_clean():
    root = started({"a.py": "def f():  # cx C901=20\n    pass\n", "b.py": "import a\n"})
    r = run(root)
    check("чистое дерево — код 0 и «чисто» последней строкой", r.returncode == 0 and "чисто" in r.last, r.stdout + r.stderr)
    check("база: строки, нарушение по функции, связь импорта",
          base(root)["files"]["a.py"] == {"lines": 2, "C901": {"f": 20}} and base(root)["imports"] == {"b.py": ["a.py"]},
          base(root))
    r = run(root, "--init")
    check("--init при готовой базе — код 2: поднять базу так нельзя", r.returncode == 2 and "уже есть" in r.last, r.last)


def t_sizes():
    root = started({"big.py": body(1600), "mid.py": body(1400)})
    write(root, {"big.py": body(1601)})
    r = run(root)
    check("файл длиннее 1500 строк вырос — код 1, «не растёт» и «что делать» последней строкой",
          r.returncode == 1 and "big.py" in r.last and "не растёт" in r.last and "Что делать" in r.last, r.stdout)
    write(root, {"big.py": body(1600), "mid.py": body(1500)})
    check("файл до 1500 строк растёт до 1500 — код 0", run(root).returncode == 0)
    write(root, {"mid.py": body(1501)})
    r = run(root)
    check("файл из базы перерос 1500 — код 1", r.returncode == 1 and "mid.py" in r.last, r.stdout)
    write(root, {"mid.py": body(1400), "new.py": body(801)})
    r = run(root)
    check("новый файл 801 строка — код 1 и «новый файл» последней строкой",
          r.returncode == 1 and "new.py" in r.last and "новый файл" in r.last, r.stdout)
    write(root, {"new.py": body(800)})
    r = run(root)
    check("новый файл 800 строк — код 0 и подсказка --update", r.returncode == 0 and "--update" in r.last, r.last)


def t_sizes_lower():
    root = started({"big.py": body(1600), "mid.py": body(1000)})
    write(root, {"big.py": body(1550), "mid.py": body(1200)})
    r = run(root)
    check("файл >1500 стал короче — код 0, подсказка --update", r.returncode == 0 and "--update" in r.last
          and "1600 → 1550" in r.last, r.last)
    r = run(root, "--update")
    b = base(root)["files"]
    check("--update опускает строки, а выросший файл до 1500 не поднимает",
          r.returncode == 0 and b["big.py"]["lines"] == 1550 and b["mid.py"]["lines"] == 1000, b)
    write(root, {"big.py": body(1551)})
    check("после --update рост на строку против новой базы — код 1", run(root).returncode == 1)


def t_complexity():
    root = started({"a.py": "def f():  # cx C901=20 PLR0915=60\n    pass\n\n\nclass K:\n"
                            "    def m(self):  # cx PLR0912=13\n        pass\n"})
    check("база: метод класса — Класс.метод", base(root)["files"]["a.py"].get("PLR0912") == {"K.m": 13}, base(root))
    write(root, {"a.py": "def f():  # cx C901=21 PLR0915=60\n    pass\n"})
    r = run(root)
    check("рост C901 у функции из базы — код 1, «в базе 20» и «что делать»",
          r.returncode == 1 and "C901 21" in r.last and "в базе 20" in r.last and "Что делать" in r.last, r.stdout)
    write(root, {"a.py": "def f():  # cx C901=20 PLR0915=60\n    pass\n\n\ndef g():  # cx C901=16\n    pass\n"})
    r = run(root)
    check("новая функция над порогом C901 — код 1, «в базе такой функции нет»",
          r.returncode == 1 and "g — C901 16" in r.last and "нет" in r.last, r.stdout)
    write(root, {"a.py": "def g():  # cx C901=16 PLR0915=60\n    pass\n"})
    r = run(root)
    check("обмен (f починили, g добавили) — код 1", r.returncode == 1 and "g — C901" in r.stdout, r.stdout)
    write(root, {"a.py": "def f():  # cx PLR0915=61\n    pass\n"})
    r = run(root)
    check("рост PLR0915 — код 1", r.returncode == 1 and "PLR0915 61" in r.last, r.stdout)


def t_complexity_lower():
    root = started({"a.py": "def f():  # cx C901=20\n    pass\n\n\ndef h():  # cx PLR0912=14\n    pass\n"})
    write(root, {"a.py": "def f():  # cx C901=17\n    pass\n\n\ndef h():\n    pass\n"})
    r = run(root)
    check("падение C901 и снятое нарушение — код 0, подсказка --update", r.returncode == 0 and "--update" in r.last, r.last)
    write(root, {"a.py": "def f():  # cx C901=17\n    pass\n\n\ndef h():  # cx PLR0912=15\n    pass\n"})
    r = run(root, "--update")
    check("--update при новом нарушении — код 1, база не тронута",
          r.returncode == 1 and base(root)["files"]["a.py"]["C901"] == {"f": 20}, base(root))
    write(root, {"a.py": "def f():  # cx C901=17\n    pass\n\n\ndef h():\n    pass\n"})
    r = run(root, "--update")
    b = base(root)["files"]["a.py"]
    check("--update опускает базу: C901 17, PLR0912 снято", r.returncode == 0 and b == {"lines": 6, "C901": {"f": 17}}, b)
    check("после --update — чисто без подсказки", "устарела" not in run(root).last)
    write(root, {"a.py": "def f():  # cx C901=18\n    pass\n"})
    r = run(root)
    check("после --update прежний запас не вернуть: 18 при базе 17 — код 1", r.returncode == 1 and "в базе 17" in r.last,
          r.last)


def t_move():
    root = started({"a.py": "def f():  # cx C901=20\n    pass\n", "b.py": "x = 1\n"})
    write(root, {"a.py": "x = 1\n", "c.py": "def f():  # cx C901=20\n    pass\n"})
    r = run(root)
    check("функция перенесена в новый файл с тем же числом — код 0", r.returncode == 0, r.stdout)
    write(root, {"c.py": "def f():  # cx C901=21\n    pass\n"})
    check("перенесённая функция выросла — код 1", run(root).returncode == 1)
    write(root, {"a.py": "def f():  # cx C901=20\n    pass\n", "c.py": "def f():  # cx C901=20\n    pass\n"})
    r = run(root)
    check("копия функции при оставшемся оригинале — код 1 (запись не свободна)", r.returncode == 1 and "c.py" in r.last,
          r.stdout)


def t_cycles():
    files = {"a.py": "import b\n", "b.py": "x = 1\n", "k1.py": "import k2\n", "k2.py": "import k1\n",
             "m1.py": "import m2\n", "m2.py": "import m1\n"}
    root = started(files)
    check("база: циклы записаны", base(root)["cycles"] == [["k1.py", "k2.py"], ["m1.py", "m2.py"]], base(root)["cycles"])
    check("старые циклы в базе — код 0", run(root).returncode == 0)
    write(root, {"b.py": "import a\n"})
    r = run(root)
    check("новый цикл a ↔ b — код 1, путь цикла и «модуль-лист» последней строкой",
          r.returncode == 1 and "новый цикл" in r.last and "a.py → b.py → a.py" in r.last and "модуль-лист" in r.last,
          r.stdout)
    write(root, {"b.py": "x = 1\n", "k3.py": "import k1\n", "k1.py": "import k2\nimport k3\n"})
    r = run(root)
    check("новый модуль вошёл в старый цикл (вынос из узла) — код 0", r.returncode == 0, r.stdout)
    write(root, {"k3.py": None, "k1.py": "import k2\nimport m1\n", "m1.py": "import m2\nimport k1\n"})
    r = run(root)
    check("два старых цикла слились — код 1", r.returncode == 1 and "новый цикл" in r.last, r.stdout)
    write(root, {"k1.py": "import k2\n", "m1.py": "import m2\n", "n1.py": "import n2\n", "n2.py": "import n1\n"})
    r = run(root)
    check("цикл из одних новых модулей — код 1", r.returncode == 1 and "n1.py" in r.last, r.stdout)
    write(root, {"n2.py": "x = 2\n", "a.py": "import n1\n", "n1.py": "import a\n"})
    r = run(root)
    check("старый модуль вне циклов в цикле с новым — код 1", r.returncode == 1 and "a.py" in r.last, r.stdout)


def t_edges():
    root = started({
        "plugins/pantheon/lib/pantheon.py": "x = 1\n",
        "plugins/pantheon/lib/sub.py": "def f():\n    return P.x\n",
        "plugins/pantheon/lib/loader.py": ("import importlib.util, os\n\n\ndef load():\n    return importlib.util."
                                           "spec_from_file_location('m', os.path.join('d', 'dyn.py'))\n"),
        "plugins/pantheon/lib/dyn.py": "x = 1\n",
        "plugins/pantheon/lib/att.py": "_attach('sub')\n",
        "plugins/pantheon/lib/tc.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import dyn\n",
        "plugins/pantheon/lib/say.py": "def f():\n    return 'dyn.py'\n",
        "plugins/pantheon/tests/test_x.py": "import dyn\n",
        "plugins/guard/hooks/g.py": "x = 1\n",
    })
    imp = base(root)["imports"]
    check("связи: P в lib → pantheon.py, загрузка «dyn.py» по имени, _attach",
          imp.get("plugins/pantheon/lib/sub.py") == ["plugins/pantheon/lib/pantheon.py"]
          and imp.get("plugins/pantheon/lib/loader.py") == ["plugins/pantheon/lib/dyn.py"]
          and imp.get("plugins/pantheon/lib/att.py") == ["plugins/pantheon/lib/sub.py"], imp)
    check("не связи: импорт под TYPE_CHECKING, строка «x.py» без загрузки, импорт из тестов",
          not {"plugins/pantheon/lib/tc.py", "plugins/pantheon/lib/say.py", "plugins/pantheon/tests/test_x.py"} & set(imp),
          imp)
    write(root, {"plugins/guard/hooks/g.py": "import dyn\n"})
    r = run(root)
    check("новая связь между плагинами — код 1, «между плагинами» последней строкой",
          r.returncode == 1 and "между плагинами" in r.last and "plugins/guard → plugins/pantheon" in r.last, r.stdout)
    write(root, {"plugins/guard/hooks/g.py": "x = 1\n", "plugins/guard/hooks/h.py": "import g\n"})
    check("новая связь внутри плагина без цикла — код 0", run(root).returncode == 0)


def t_backrefs():
    """Обратные ссылки как G в guard: sys.modules.get("X") и `mod.G = <себя>` в глобальное имя чужого модуля."""
    root = started({
        "plugins/guard/hooks/mg.py": "import sys\nG = sys.modules.get('gr')\n",
        "plugins/guard/hooks/pc.py": "G = None\nCACHE = None\n",
        "plugins/guard/hooks/gr.py": ("import pc\nimport sys\n_SELF = sys.modules[__name__]\npc.G = _SELF\n"
                                      "pc.CACHE = None\npc.OTHER = _SELF\n"),
        "plugins/guard/hooks/solo.py": "x = 1\n",
    })
    imp = base(root)["imports"]
    check("sys.modules.get('gr') — связь mg → gr; pc.G = _SELF из gr — связь pc → gr (G — глобальное имя pc)",
          imp.get("plugins/guard/hooks/mg.py") == ["plugins/guard/hooks/gr.py"]
          and imp.get("plugins/guard/hooks/pc.py") == ["plugins/guard/hooks/gr.py"], imp)
    check("цикл gr ↔ pc через обратную ссылку — в базе",
          base(root)["cycles"] == [["plugins/guard/hooks/gr.py", "plugins/guard/hooks/pc.py"]], base(root)["cycles"])
    write(root, {"plugins/guard/hooks/solo.py": "G = None\n", "plugins/guard/hooks/gr.py":
                 "import pc\nimport solo\nimport sys\n_SELF = sys.modules[__name__]\npc.G = _SELF\nsolo.G = _SELF\n"})
    r = run(root)
    check("новая обратная ссылка solo.G = <gr> — новый цикл, код 1", r.returncode == 1 and "solo.py" in r.last, r.stdout)


def t_backref_counts():
    """Число обращений P. (pantheon/lib) и G. (guard/hooks) по файлу и в сумме не растёт."""
    lib = "plugins/pantheon/lib/"
    root = started({lib + "pantheon.py": "x = 1\n", lib + "w.py": "def f():\n    return P.a + P.b + P.c\n",
                    "plugins/guard/hooks/m.py": "G = None\n\n\ndef f():\n    return G.x\n",
                    "plugins/pantheon/tests/test_w.py": "P = None\nP.a\n", "plugins/pantheon/scripts/s.py": "P = 1\nP.real\n"})
    files = base(root)["files"]
    check("база: P. в lib — 3, G. в guard/hooks — 1; тесты и другие папки не в счёт",
          files[lib + "w.py"].get("backrefs") == 3 and files["plugins/guard/hooks/m.py"].get("backrefs") == 1
          and "backrefs" not in files["plugins/pantheon/tests/test_w.py"]
          and "backrefs" not in files["plugins/pantheon/scripts/s.py"], files)
    write(root, {lib + "w.py": "def f():\n    return P.a + P.b + P.c + P.d\n"})
    r = run(root)
    check("P. в файле из базы выросло — код 1, «модуля-листа» последней строкой",
          r.returncode == 1 and "w.py" in r.last and "модуля-листа" in r.last, r.stdout)
    write(root, {lib + "w.py": "def f():\n    return P.a + P.b + P.c\n", lib + "new.py": "def g():\n    return P.z\n"})
    r = run(root)
    check("новый модуль с P. сверх ушедшего из старых — код 1 и имя модуля", r.returncode == 1 and "new.py" in r.last,
          r.stdout)
    write(root, {lib + "w.py": "def f():\n    return P.a + P.b\n"})
    check("P. перенесено из старого модуля в новый (сумма та же) — код 0", run(root).returncode == 0)
    write(root, {lib + "new.py": None, lib + "w.py": "def f():\n    return P.a + P.b + P.c\n",
                 "plugins/guard/hooks/m.py": "G = None\n\n\ndef f():\n    return G.x + G.y\n"})
    r = run(root)
    check("G. в guard/hooks выросло — код 1", r.returncode == 1 and "m.py" in r.last, r.stdout)
    write(root, {"plugins/guard/hooks/m.py": "G = None\n"})
    r = run(root, "--update")
    check("--update опускает счётчик G. (запись снята)",
          r.returncode == 0 and "backrefs" not in base(root)["files"]["plugins/guard/hooks/m.py"], base(root)["files"])


def mini_repo():
    """Репозиторий с храповиком, базой и плагином из одного зелёного файла тестов."""
    root = repo({"plugins/x/tests/test_a.py": "print('ok a')\nprint('1 из 1 прошли')\n"})
    os.makedirs(os.path.join(root, "plugins", "pantheon", "scripts"))
    shutil.copy(SCRIPT, os.path.join(root, "plugins", "pantheon", "scripts", "lint_ratchet.py"))
    stub = f"{sys.executable} -I {STUB_PATH}"
    subprocess.run([sys.executable, "-I", SCRIPT, "--root", root, "--init", "--ruff", stub], check=True, capture_output=True)
    return root, stub


def runner(root, *args, env=None):
    r = subprocess.run([sys.executable, "-I", RUNNER, *args, os.path.join(root, "plugins", "x")], capture_output=True,
                       text=True, env={**os.environ, **(env or {})}, timeout=300)
    lines = r.stdout.strip().splitlines()
    r.last = lines[-1] if lines else ""
    return r


def t_run_tests():
    """run-tests.py зовёт храповик до тестов: так его держит и запасной путь слияния (запись полного набора)."""
    root, stub = mini_repo()
    r = runner(root, env={"LINT_RATCHET_RUFF": stub})
    check("run-tests: храповик чистый — код 0, его строка в выводе", r.returncode == 0 and "храповик: чисто" in r.stdout,
          r.stdout[-800:])
    write(root, {"plugins/x/big.py": body(801)})
    r = runner(root, env={"LINT_RATCHET_RUFF": stub})
    check("run-tests: храповик красный при зелёных тестах — код 1, причина последней строкой",
          r.returncode == 1 and r.last.startswith("run-tests: храповик красный") and "big.py" in r.last, r.stdout[-800:])
    r = runner(root, env={"LINT_RATCHET_RUFF": stub, "STUB_BAD": "1"})
    check("run-tests: ruff недоступен — строка «skip lint_ratchet · пропущено» и код тестов",
          r.returncode == 0 and "skip lint_ratchet · пропущено" in r.stdout, r.stdout[-800:])
    r = runner(root, "--only", "x/test_a.py", env={"LINT_RATCHET_RUFF": stub})
    check("run-tests --only: храповик не идёт", r.returncode == 0 and "храповик" not in r.stdout, r.stdout[-800:])
    alone = repo({"plugins/x/tests/test_a.py": "print('ok a')\nprint('1 из 1 прошли')\n"})
    r = runner(alone, env={"LINT_RATCHET_RUFF": stub})
    check("run-tests: репозиторий без храповика — без строки храповика", r.returncode == 0 and "храповик" not in r.stdout
          and "lint_ratchet" not in r.stdout, r.stdout[-800:])


def t_real_baseline():
    """База репозитория читается и в ней нет записей сложности у самого храповика и этого теста."""
    with open(os.path.join(REPO, "plugins", "pantheon", "scripts", "lint-baseline.json"), encoding="utf-8") as fh:
        b = json.load(fh)
    own = [b["files"].get(p, {}) for p in ("plugins/pantheon/scripts/lint_ratchet.py",
                                          "plugins/pantheon/tests/test_lint_ratchet.py")]
    check("база репозитория: files и imports, у храповика и его теста нарушений нет",
          isinstance(b.get("imports"), dict) and all(set(e) == {"lines"} for e in own), own)


def t_fatal():
    root = repo({"a.py": "x = 1\n"})
    r = run(root)
    check("нет базы — код 2, подсказка --init последней строкой", r.returncode == 2 and "--init" in r.last, r.last)
    run(root, "--init")
    r = run(root, env={"STUB_BAD": "1"})
    check("ruff не дал JSON — код 2, причина последней строкой", r.returncode == 2 and "ruff не дал JSON" in r.last, r.last)
    with open(os.path.join(root, "base.json"), "w", encoding="utf-8") as fh:
        fh.write("[]")
    r = run(root)
    check("база не того вида — код 2", r.returncode == 2 and "не в том виде" in r.last, r.last)
    r = run(root, "--bogus")
    check("неизвестный аргумент — код 2", r.returncode == 2 and "--bogus" in r.last, r.last)
    r = run(root, ruff=False)
    check("нет версии ruff в .github/ruff-requirements.txt и нет --ruff — код 2", r.returncode == 2 and "--ruff" in r.last,
          r.last)
    args = os.path.join(root, "args.json")
    run(root, env={"STUB_ARGS": args})
    with open(args, encoding="utf-8") as fh:
        got = json.load(fh)
    want = ["--isolated", "--ignore-noqa", "C901,PLR0915,PLR0912", "lint.mccabe.max-complexity=15",
            "lint.pylint.max-statements=50", "lint.pylint.max-branches=12", "a.py"]
    check("ruff зовётся с --isolated, --ignore-noqa и порогами храповика", all(w in got for w in want), got)


def t_real_ruff():
    """Настоящий ruff закреплённой версии: пороги и ключи храповика дают нужные коды и числа."""
    try:
        with open(os.path.join(REPO, ".github", "ruff-requirements.txt"), encoding="utf-8") as fh:
            req = fh.read()
    except OSError:
        print("пропущено: настоящий ruff — нет .github/ruff-requirements.txt")
        return
    root = started({"x.py": "y = 1\n"})
    branches = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(16))
    write(root, {".github/ruff-requirements.txt": req,
                 "ruff.toml": '[lint]\nper-file-ignores = {"*" = ["C901", "PLR0912"]}\nmccabe.max-complexity = 50\n',
                 "x.py": "y = 1\n\n\ndef f(x):  # noqa: C901, PLR0912\n" + branches + "    return -1\n"})
    r = run(root, ruff=False)
    if r.returncode == 2:  # нет ruff закреплённой версии и uvx (или uvx без сети); в CI ruff стоит — там случай идёт
        print(f"пропущено: настоящий ruff — {r.last}")
        return
    check("настоящий ruff: C901 17 и PLR0912 16 у новой функции, ruff.toml и noqa не выключают",
          r.returncode == 1 and "f — C901 17" in r.stdout and "f — PLR0912 16" in r.stdout, r.stdout + r.stderr)


def main():
    for t in (t_clean, t_sizes, t_sizes_lower, t_complexity, t_complexity_lower, t_move, t_cycles, t_edges, t_backrefs,
              t_backref_counts, t_fatal, t_run_tests, t_real_baseline, t_real_ruff):
        t()
    print(f"{len(OK)} из {len(OK) + len(FAIL)} прошли")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
