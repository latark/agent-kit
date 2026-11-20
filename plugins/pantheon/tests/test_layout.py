#!/usr/bin/env python3
"""Карта «что где» и проверка «папка вне раскладки» (lib/layout.py, metis-0899).

1. problems() на временном HOME: каждая ветка правила даёт свою строку, а по карте — ни одной лишней.
2. Мутанты внутри теста: каждая ветка problems()/folder_ok() по очереди отключается в исходнике — набор строк обязан
   поменяться (откат ветки краснит этот файл, а не только CI revert-check).
3. CLI на временном HOME: `pantheon layout` (код 1 и строки), `pantheon check` (предупреждение), `check --quiet`
   (тревога в alerts.md), `pantheon direction check` (строки про папки ~/ai/life/<x>)."""
import os
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import atexit
import shutil

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="layout-root-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
atexit.register(shutil.rmtree, ROOT, True)

LIBDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIBDIR, "run.py")
SRC = open(os.path.join(LIBDIR, "layout.py"), encoding="utf-8").read()
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or not detail else f"\n     {detail}"))


def write(p, text=""):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def load(src):
    m = types.ModuleType("layout_under_test")
    exec(compile(src, "layout.py", "exec"), m.__dict__)
    return m


def fixture():
    """HOME с папками по карте и вне неё. → (home, реестр, старые папки несделанных переносов)."""
    home = os.path.realpath(tempfile.mkdtemp(prefix="layout-home-"))
    for d in ("ai/pantheon", "ai/knowledge", "ai/junk", "ai/.hidden", "ai/life/.git", "ai/life/career/.git",
              "ai/life/nogit", "projects/demo", "projects/broker/app", "projects/other/sessync", "projects/archive/old",
              "projects/stray", "projects/workshop", ".claude", "elsewhere"):
        os.makedirs(os.path.join(home, d))
    write(os.path.join(home, "ai", "note.txt"), "файл, не папка — не смотрим\n")
    os.symlink(os.path.join(home, "elsewhere"), os.path.join(home, "ai", "life", "linked"))
    reg = {"iris-demo": ["~/projects/demo", "~/projects/broker/app", "~/projects/other/sessync"],
           "nike-career": ["~/ai/life/career"],
           "mnemo-brain": ["~/ai/knowledge", "~/.claude"],
           "bad-one": ["~/projects/archive/old", "~/elsewhere", "~/ai/life", "~/ai/junk"]}
    pending = {os.path.join(home, "projects", "workshop")}
    return home, reg, pending


EXPECTED = {"~/ai/junk", "~/ai/life/.git", "~/ai/life/nogit", "~/ai/life/linked", "~/projects/stray",
            "bad-one:~/projects/archive/old", "bad-one:~/elsewhere", "bad-one:~/ai/life", "bad-one:~/ai/junk"}

# (что отключено, было, стало) — каждая ветка правила
MUTANTS = [
    ("~/ai/<x> вне карты", "        if n not in AI_KNOWN:\n", "        if False:\n"),
    (".git у ~/ai/life", '    if os.path.lexists(os.path.join(life, ".git")):\n', "    if False:\n"),
    ("область-ссылка", "        if os.path.islink(p):\n", "        if False:\n"),
    ("область без git", '        elif not os.path.lexists(os.path.join(p, ".git")):\n', "        elif False:\n"),
    ("other/ и archive/ — свои", "n in PROJECTS_OWN or ", ""),
    ("старая папка переноса — по карте", "p in pending or ", ""),
    ("папка из реестра — по карте", " or any(_under(u, rp) for u in used)", ""),
    ("папка направления вне карты", "if isinstance(f, str) and f and not folder_ok(f, home):",
     "if isinstance(f, str) and f and False:"),
    ("archive в реестре — вне карты", '    if _under(p, j("projects", "archive")):\n        return False\n', ""),
    ("~/projects/… — по карте", '    if p != j("projects") and _under(p, j("projects")):\n        return True\n', ""),
    ("папка системы в ~/ai — по карте", '    if any(_under(p, j("ai", x)) for x in AI_KNOWN - {"life"}):\n        return True\n',
     ""),
    ("~/ai/life/<x> — по карте", '    if p != j("ai", "life") and _under(p, j("ai", "life")):\n        return True\n', ""),
    ("сама ~/ai/life — не папка направления", 'if p != j("ai", "life") and _under(', 'if _under('),
    ("~/.claude — по карте", '    return _under(p, j(".claude"))\n', "    return False\n"),
]


def test_problems():
    home, reg, pending = fixture()
    m = load(SRC)
    got = {k for k, _ in m.problems(home, reg, pending)}
    check("по карте лишних строк нет, вне карты — каждая папка", got == EXPECTED,
          f"лишние {sorted(got - EXPECTED)}, нет {sorted(EXPECTED - got)}")
    texts = dict(m.problems(home, reg, pending))
    check("строки называют путь через ~ и что делать", "pantheon direction init" in texts["~/ai/life/nogit"]
          and "~/projects/other" in texts["~/projects/stray"])
    os.rmdir(os.path.join(home, "projects", "workshop"))
    check("перенос сделан (старой папки нет) — строк не прибавилось",
          {k for k, _ in m.problems(home, reg, set())} == EXPECTED)
    os.makedirs(os.path.join(home, "projects", "workshop"))
    check("старая папка вернулась после переноса — вне карты",
          "~/projects/workshop" in {k for k, _ in m.problems(home, reg, set())})
    check("нет ~/ai и ~/projects — пусто, без исключения",
          load(SRC).problems(os.path.join(home, "nothing"), {}, set()) == [])
    # второй реестр — без папок в other/ и archive/: иначе их «покрывал» бы реестр, и мутант PROJECTS_OWN выжил бы
    small = {"nike-career": reg["nike-career"]}
    cases = [(r, pd) for r in (reg, small) for pd in (pending, set())]
    for what, old, new in MUTANTS:
        check(f"мутант «{what}» в исходнике есть один раз", SRC.count(old) == 1, old)
        mut = load(SRC.replace(old, new, 1))
        check(f"мутант «{what}» убит: строки другие",
              any(mut.problems(home, r, pd) != m.problems(home, r, pd) for r, pd in cases))


def env_for(tmp):
    return {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": os.path.join(tmp, "ai", "pantheon"),
            "PANTHEON_STATE": os.path.join(tmp, "state"), "PANTHEON_NO_NOTIFY": "1"}


def test_cli():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="layout-cli-"))
    for d in ("ai/pantheon", "ai/life/career/.git", "ai/life/nogit", "projects/demo", "state"):
        os.makedirs(os.path.join(tmp, d))
    write(os.path.join(tmp, "ai", "pantheon", "directions.toml"),
          '[[direction]]\nname = "nike-career"\nproject = "career"\nfolders = ["~/ai/life/career"]\n'
          'does = "Карьера"\ndoes_not = "Чужое"\nexamples = ["раз", "два", "три"]\n'
          '[[direction]]\nname = "iris-demo"\nproject = "demo"\nfolders = ["~/projects/demo", "~/projects/archive/x"]\n')
    env = env_for(tmp)
    run = lambda *a: subprocess.run([PY311, "-I", RUN_PY, *a], env=env, capture_output=True, text=True, timeout=120)
    r = run("layout")
    check("pantheon layout: карта и папки вне неё, код 1",
          r.returncode == 1 and "| ~/ai/life |" in r.stdout and "вне раскладки · ~/ai/life/nogit" in r.stdout
          and "~/projects/archive/x направления iris-demo" in r.stdout, r.stdout[-400:] + r.stderr[-400:])
    check("pantheon layout с аргументом — код 2", run("layout", "x").returncode == 2)
    r = run("direction", "check", "nike-career")
    check("direction check nike-career: путь ~/ai/life/career и строка карты «готово»",
          "готово  папки направления есть на этом Mac: ~/ai/life/career" in r.stdout
          and "готово  папки по карте «что где»" in r.stdout, r.stdout)
    r = run("direction", "check", "iris-demo")
    check("direction check: папка в ~/projects/archive — «НЕТ» с путём",
          "НЕТ     папки по карте «что где» (pantheon layout): вне карты ~/projects/archive/x" in r.stdout, r.stdout)
    r = run("check")
    check("pantheon check: предупреждение о папке вне раскладки",
          "предупреждение · раскладка · ~/ai/life/nogit" in r.stdout, r.stdout[-600:] + r.stderr[-400:])
    run("check", "--quiet")
    al = os.path.join(tmp, "ai", "pantheon", "alerts.md")
    text = open(al, encoding="utf-8").read() if os.path.isfile(al) else ""
    check("check --quiet: тревога «папки вне раскладки» в alerts.md", "папки вне раскладки: 2" in text, text[-400:])
    os.rmdir(os.path.join(tmp, "ai", "life", "nogit"))
    write(os.path.join(tmp, "ai", "pantheon", "directions.toml"),
          '[[direction]]\nname = "nike-career"\nproject = "career"\nfolders = ["~/ai/life/career"]\n'
          '[[direction]]\nname = "iris-demo"\nproject = "demo"\nfolders = ["~/projects/demo"]\n')
    r = run("layout")
    check("всё по карте: pantheon layout — код 0", r.returncode == 0 and "все папки по карте" in r.stdout, r.stdout[-300:])
    check("всё по карте: check без предупреждения о раскладке", "раскладка" not in run("check").stdout)


if __name__ == "__main__":
    test_problems()
    test_cli()
    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)
