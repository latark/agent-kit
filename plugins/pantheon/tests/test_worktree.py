#!/usr/bin/env python3
"""pantheon worktree add|remove|list (metis-1225): worktree окна направления мимо песочницы — одна узкая команда.

- успех во временном репозитории: add (ветка = имя от HEAD, --branch/--base, уже есть ветка), list, remove; из worktree
  сессии (cwd в .claude/worktrees/<другая>) новая ложится в основную копию;
- add --detach: копия без ветки, ветки с именем копии нет, повтор с тем же именем после remove проходит; remove копии
  без ветки с неотслеживаемым выводом — отказ с подсказкой --force, remove --force её убирает; --force у копии на
  ветке — отказ 2, грязная копия цела;
- --force — только у своей копии (метка pantheon-detach в gitdir, её пишет add --detach): чужая detached-копия
  (git worktree add --detach мимо команды) и копия посреди merge/rebase/bisect — отказ 2, файлы целы;
- вложенные папки направлений: владелец репозитория — самая глубокая (Д3);
- git зовётся с GIT_CONFIG_NOSYSTEM=1 и без GIT_* окна (F2);
- отказ: `..`, ведущий `-`, абсолютный путь, лишние флаги и --force; ссылка на месте .claude, .claude/worktrees и звена
  имени; remove папки, которая не worktree; cwd вне основной копии; репозиторий чужого направления и вне папок
  направлений (PANTHEON_WINDOW из domains.json);
- git без хуков окна: post-checkout из core.hooksPath (.husky в папке окна) не исполняется; GIT_DIR окна не уводит в
  другой репозиторий;
- мутанты встроены: копия lib с откатом проверки (.., ссылка, своё направление, hooksPath) — тот же случай проходит,
  то есть тест краснеет на откате.

Запуск: python3 -I plugins/pantheon/tests/test_worktree.py  (код выхода 0 — все прошли)
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311, mkroot  # CLI pantheon — только на Python 3.11+

ROOT = os.path.realpath(mkroot("tmp-wtcmd-"))
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{str(detail)[-400:]}]"))


genv = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True,
                          env={**os.environ, **genv}).stdout.strip()


def mkrepo(p):
    os.makedirs(p)
    git(p, "init", "-q", "-b", "main")
    open(os.path.join(p, "a.txt"), "w").write("a\n")
    git(p, "add", "a.txt")
    git(p, "commit", "-q", "-m", "init")
    return p


home = os.path.join(ROOT, "home")
state = os.path.join(home, ".local", "state", "pantheon")
os.makedirs(state)
mine = mkrepo(os.path.join(home, "projects", "mine"))
other = mkrepo(os.path.join(home, "projects", "other"))
stray = mkrepo(os.path.join(home, "projects", "stray"))
json.dump({"domains": {"themis-x": ["~/projects/mine"], "athena-y": ["~/projects/other"]}},
          open(os.path.join(state, "domains.json"), "w"))
env = {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": os.path.join(home, "ai", "pantheon"),
       "PANTHEON_STATE": state, "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "TMPDIR": ROOT, **genv}


def cli(cwd, *a, lib=LIB, extra=None):
    return subprocess.run([PY311, "-I", os.path.join(lib, "run.py"), "worktree", *a], cwd=cwd,
                          env={**env, **(extra or {})}, capture_output=True, text=True, timeout=120)


def wt(repo, name):
    return os.path.join(repo, ".claude", "worktrees", *name.split("/"))


def listed(repo):
    return [ln.split(" ", 1)[1] for ln in git(repo, "worktree", "list", "--porcelain").splitlines()
            if ln.startswith("worktree ")]


# успех
r = cli(mine, "add", "metis-1-a")
check("add: код 0, папка и ветка metis-1-a от HEAD", r.returncode == 0 and os.path.isdir(wt(mine, "metis-1-a"))
      and git(wt(mine, "metis-1-a"), "rev-parse", "--abbrev-ref", "HEAD") == "metis-1-a", r.stdout + r.stderr)
r = cli(mine, "add", "b/c", "--branch", "metis-2-x", "--base", "main")
check("add: вложенное имя, --branch и --base", r.returncode == 0
      and git(wt(mine, "b/c"), "rev-parse", "--abbrev-ref", "HEAD") == "metis-2-x", r.stdout + r.stderr)
git(mine, "branch", "have-1")
r = cli(mine, "add", "h1", "--branch", "have-1")
check("add: ветка уже есть — worktree на ней", r.returncode == 0
      and git(wt(mine, "h1"), "rev-parse", "--abbrev-ref", "HEAD") == "have-1", r.stdout + r.stderr)
r = cli(mine, "add", "h2", "--branch", "have-1", "--base", "main")
check("add: ветка есть и --base — отказ 2", r.returncode == 2 and "уже есть" in r.stderr, r.stderr)
r = cli(wt(mine, "metis-1-a"), "add", "from-wt")
check("add из worktree сессии — новая в основной копии", r.returncode == 0 and os.path.isdir(wt(mine, "from-wt"))
      and not os.path.exists(os.path.join(wt(mine, "metis-1-a"), ".claude", "worktrees", "from-wt")), r.stderr)
r = cli(mine, "list")
check("list: свои worktree по имени", r.returncode == 0 and "metis-1-a\t" in r.stdout and "b/c\t" in r.stdout, r.stdout)
r = cli(mine, "add", "metis-1-a")
check("add: папка уже есть — отказ 2", r.returncode == 2 and "уже есть" in r.stderr, r.stderr)
r = cli(mine, "remove", "from-wt")
check("remove: код 0, папки нет, в git worktree list нет", r.returncode == 0 and not os.path.exists(wt(mine, "from-wt"))
      and wt(mine, "from-wt") not in listed(mine), r.stdout + r.stderr)
open(os.path.join(wt(mine, "h1"), "dirty.txt"), "w").write("x\n")
r = cli(mine, "remove", "h1")
check("remove: незакоммиченное — git отказал, код 1, папка цела", r.returncode == 1 and os.path.isdir(wt(mine, "h1")),
      r.stderr)

# отказ: имена и форма
for bad in (["add", "../x"], ["add", "a/../b"], ["add", "a..b"], ["add", "-x"], ["add", "/tmp/x"], ["add", "a/"],
            ["add", "x", "--branch", "../main"], ["add", "x", "--base", "-c"], ["add", "x", "--force"],
            ["add", "x", "--branch"], ["add", "x", "--branch", "a", "--branch", "b"], ["add"], ["add", "x.lock"],
            ["remove", "h1", "--force"], ["remove", "../mine"], ["remove"], ["list", "x"], ["move", "a", "b"], [],
            ["add", "x", "--detach", "--branch", "b"], ["add", "x", "--detach", "--detach"], ["remove", "--force", "h1"],
            ["add", "x", "--detach", "--base", "no-such-ref"]):
    r = cli(mine, *bad)
    check(f"отказ: worktree {' '.join(bad) or '(пусто)'} → код 2", r.returncode == 2 and r.stderr.strip(), r.stderr)
check("отказы ничего не создали", sorted(os.listdir(os.path.join(mine, ".claude", "worktrees"))) == ["b", "h1",
                                                                                                   "metis-1-a"])

# --detach (Б2) и remove --force только у копии без ветки (Д3)
r = cli(mine, "add", "tmp-9", "--detach", "--base", "main")
check("add --detach: код 0, HEAD без ветки, ветки tmp-9 нет", r.returncode == 0
      and git(wt(mine, "tmp-9"), "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
      and subprocess.run(["git", "rev-parse", "--verify", "--quiet", "refs/heads/tmp-9"], cwd=mine).returncode != 0,
      r.stdout + r.stderr)
open(os.path.join(wt(mine, "tmp-9"), "run.log"), "w").write("вывод прогона\n")
r = cli(mine, "remove", "tmp-9")
check("remove копии без ветки с неотслеживаемым — код 1, подсказка --force, папка цела", r.returncode == 1
      and "pantheon worktree remove tmp-9 --force" in r.stderr and os.path.isdir(wt(mine, "tmp-9")), r.stderr)
r = cli(mine, "remove", "tmp-9", "--force")
check("remove --force копии без ветки — код 0, папки нет", r.returncode == 0 and not os.path.exists(wt(mine, "tmp-9"))
      and wt(mine, "tmp-9") not in listed(mine), r.stdout + r.stderr)
r = cli(mine, "add", "tmp-9", "--base", "main", "--detach")
check("повтор add tmp-9 --detach после remove (флаги в другом порядке) — код 0", r.returncode == 0
      and os.path.isdir(wt(mine, "tmp-9")), r.stderr)
r = cli(mine, "remove", "tmp-9")
check("remove чистой копии без ветки — код 0 без --force", r.returncode == 0, r.stderr)
def gitdir(p):
    return git(p, "rev-parse", "--absolute-git-dir")


r = cli(mine, "add", "tmp-8", "--detach")
check("add --detach пишет метку pantheon-detach в gitdir копии", r.returncode == 0
      and os.path.isfile(os.path.join(gitdir(wt(mine, "tmp-8")), "pantheon-detach")), r.stderr)
git(mine, "worktree", "add", "-q", "--detach", wt(mine, "ext-1"), "main")  # чужая копия без ветки: outside, сессия
open(os.path.join(wt(mine, "ext-1"), "unsaved.txt"), "w").write("x\n")
r = cli(mine, "remove", "ext-1", "--force")
check("remove --force чужой detached-копии (метки нет) — отказ 2, файл цел", r.returncode == 2 and "метки нет" in r.stderr
      and os.path.exists(os.path.join(wt(mine, "ext-1"), "unsaved.txt")), r.stderr)
r = cli(mine, "remove", "ext-1")
check("remove чужой грязной detached без --force — код 1, подсказки --force нет", r.returncode == 1
      and "--force`" not in r.stderr, r.stderr)
open(os.path.join(wt(mine, "tmp-8"), "run.log"), "w").write("x\n")
for busy in ("MERGE_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply"):
    bp = os.path.join(gitdir(wt(mine, "tmp-8")), busy)
    os.makedirs(bp) if busy.startswith("rebase") else open(bp, "w").write(git(mine, "rev-parse", "HEAD") + "\n")
    r = cli(mine, "remove", "tmp-8", "--force")
    check(f"remove --force своей копии во время {busy} — отказ 2, копия цела", r.returncode == 2 and busy in r.stderr
          and os.path.isdir(wt(mine, "tmp-8")), r.stderr)
    shutil.rmtree(bp) if busy.startswith("rebase") else os.remove(bp)
r = cli(mine, "remove", "h1", "--force")
check("remove --force копии на ветке — отказ 2, грязный файл цел", r.returncode == 2 and "на ветке" in r.stderr
      and os.path.exists(os.path.join(wt(mine, "h1"), "dirty.txt")), r.stderr)

# отказ: ссылки
lnk = mkrepo(os.path.join(home, "projects", "mine", "sub-l"))  # вложенный репозиторий внутри своей папки
outside = os.path.join(ROOT, "outside")
os.makedirs(outside)
os.symlink(outside, os.path.join(lnk, ".claude"))
r = cli(lnk, "add", "y")
check("ссылка на месте .claude — отказ, снаружи пусто", r.returncode == 2 and "ссылка" in r.stderr
      and os.listdir(outside) == [], r.stderr)
os.remove(os.path.join(lnk, ".claude"))
os.makedirs(os.path.join(lnk, ".claude"))
os.symlink(outside, os.path.join(lnk, ".claude", "worktrees"))
r = cli(lnk, "add", "y")
check("ссылка на месте .claude/worktrees — отказ", r.returncode == 2 and "ссылка" in r.stderr
      and os.listdir(outside) == [], r.stderr)
os.remove(os.path.join(lnk, ".claude", "worktrees"))
os.makedirs(os.path.join(lnk, ".claude", "worktrees"))
os.symlink(outside, os.path.join(lnk, ".claude", "worktrees", "seg"))
r = cli(lnk, "add", "seg/y")
check("ссылка на месте звена имени — отказ", r.returncode == 2 and "ссылка" in r.stderr
      and os.listdir(outside) == [], r.stderr)
os.makedirs(os.path.join(mine, ".claude", "worktrees", "plain"))
r = cli(mine, "remove", "plain")
check("remove папки, которая не worktree — отказ, папка цела", r.returncode == 2 and "не worktree" in r.stderr
      and os.path.isdir(os.path.join(mine, ".claude", "worktrees", "plain")), r.stderr)

# отказ: где стоит команда
far = os.path.join(ROOT, "far-wt")
git(mine, "worktree", "add", "-q", far, "-b", "far-1")
r = cli(far, "add", "z")
check("cwd — worktree вне основной копии — отказ", r.returncode == 2 and "вне основной копии" in r.stderr, r.stderr)
r = cli(ROOT, "add", "z")
check("cwd не в git — отказ", r.returncode == 2 and "не в git" in r.stderr, r.stderr)
r = cli(other, "add", "z", extra={"PANTHEON_WINDOW": "themis-x"})
check("окно themis-x: репозиторий athena-y — отказ, worktree нет", r.returncode == 2 and "athena-y" in r.stderr
      and not os.path.exists(wt(other, "z")), r.stderr)
r = cli(stray, "add", "z", extra={"PANTHEON_WINDOW": "themis-x"})
check("окно themis-x: репозиторий вне папок направлений — отказ", r.returncode == 2
      and "вне папок направлений" in r.stderr and not os.path.exists(wt(stray, "z")), r.stderr)
r = cli(mine, "add", "own-1", extra={"PANTHEON_WINDOW": "themis-x"})
check("окно themis-x: свой репозиторий — код 0", r.returncode == 0 and os.path.isdir(wt(mine, "own-1")), r.stderr)
# вложенные папки направлений (Д3): mine/deep — направление hermes-z, глубже themis-x — владелец оно
deep = mkrepo(os.path.join(mine, "deep"))
json.dump({"domains": {"themis-x": ["~/projects/mine"], "athena-y": ["~/projects/other"],
                       "hermes-z": ["~/projects/mine/deep"]}}, open(os.path.join(state, "domains.json"), "w"))
r = cli(deep, "add", "d1", extra={"PANTHEON_WINDOW": "themis-x"})
check("вложенное направление: окно внешнего (themis-x) — отказ, владелец hermes-z", r.returncode == 2
      and "hermes-z" in r.stderr and not os.path.exists(wt(deep, "d1")), r.stderr)
r = cli(deep, "add", "d2", extra={"PANTHEON_WINDOW": "hermes-z"})
check("вложенное направление: окно самой глубокой папки — код 0", r.returncode == 0 and os.path.isdir(wt(deep, "d2")),
      r.stderr)
r = cli(mine, "add", "own-2", extra={"PANTHEON_WINDOW": "hermes-z"})
check("вложенное направление: внешний репозиторий окну hermes-z — отказ", r.returncode == 2 and "themis-x" in r.stderr,
      r.stderr)
r = cli(mine, "add", "env-1", extra={"GIT_DIR": os.path.join(other, ".git"), "GIT_WORK_TREE": other})
check("GIT_DIR окна не уводит: worktree в репозитории cwd", r.returncode == 0 and os.path.isdir(wt(mine, "env-1"))
      and not os.path.exists(wt(other, "env-1")), r.stderr)

# хук из папки окна не исполняется
hooks = os.path.join(other, ".husky")
os.makedirs(hooks)
marker = os.path.join(ROOT, "hook-ran")
open(os.path.join(hooks, "post-checkout"), "w").write(f"#!/bin/sh\ntouch '{marker}'\n")
os.chmod(os.path.join(hooks, "post-checkout"), 0o755)
git(other, "config", "core.hooksPath", ".husky")
git(other, "worktree", "add", "-q", os.path.join(ROOT, "probe-hook"), "-b", "probe-hook")
check("самопроверка: обычный git worktree add хук исполняет", os.path.exists(marker))
os.remove(marker)
r = cli(other, "add", "hk")
check("post-checkout из core.hooksPath не исполнен", r.returncode == 0 and not os.path.exists(marker), r.stderr)


# мутанты: копия lib с откатом одной проверки — тот же случай проходит
def mutant(old, new, *more):
    d = os.path.join(ROOT, "mut-" + str(len(os.listdir(ROOT))))
    shutil.copytree(LIB, d, ignore=shutil.ignore_patterns("__pycache__"))
    f = os.path.join(d, "worktree.py")
    src = open(f, encoding="utf-8").read()
    pairs = [(old, new)] + list(zip(more[::2], more[1::2]))
    for a, b in pairs:
        assert src.count(a) == 1, a
        src = src.replace(a, b)
    open(f, "w", encoding="utf-8").write(src)
    return d


m = mutant('or ".." in x or', "or")
r = cli(mine, "add", "a..b", "--branch", "mut-ab", lib=m)
check("мутант: без проверки .. — a..b проходит (тест выше краснеет)", r.returncode == 0, r.stderr)
m = mutant("        if os.path.islink(p):\n", "        if False:\n")
r = cli(lnk, "add", "seg/y2", lib=m)
check("мутант: без проверки ссылок — отказ уже не «ссылка» (тест звена краснеет)", "ссылка" not in r.stderr, r.stderr)
m = mutant("        if os.path.islink(p):\n", "        if False:\n",
           "    if not _under(parent, base) or os.path.realpath(base) != base:\n", "    if False:\n")
r = cli(lnk, "add", "seg/y3", lib=m)
check("мутант: без проверки ссылок и настоящего пути — запись уходит наружу",
      os.path.exists(os.path.join(outside, "y3")), r.stderr)
m = mutant("    if owner != win:\n", "    if False:\n")
r = cli(other, "add", "mz", lib=m, extra={"PANTHEON_WINDOW": "themis-x"})
check("мутант: без проверки направления — чужой репозиторий проходит", r.returncode == 0, r.stderr)
m = mutant('"-c", "core.hooksPath=/dev/null", ', "")
r = cli(other, "add", "hk2", lib=m)
check("мутант: без core.hooksPath=/dev/null — хук окна исполнен", os.path.exists(marker), r.stderr)

m = mutant("    owner = max(hits, key=lambda x: len(x[0]))[1] if hits else None\n",
           "    owner = min(hits, key=lambda x: len(x[0]))[1] if hits else None\n")
r = cli(deep, "add", "d3", extra={"PANTHEON_WINDOW": "hermes-z"})
r2 = cli(deep, "add", "d4", lib=m, extra={"PANTHEON_WINDOW": "hermes-z"})
check("мутант: владелец — самая мелкая папка — окно глубокой получает отказ", r.returncode == 0 and r2.returncode == 2,
      r2.stderr)
m = mutant("    if force and not detached:\n", "    if False:\n",
           "    if force and not (gd and os.path.isfile(os.path.join(gd, DETACH_MARK))):\n", "    if False:\n")
git(mine, "worktree", "add", "-q", wt(mine, "fb"), "-b", "fb-1")
open(os.path.join(wt(mine, "fb"), "dirty.txt"), "w").write("x\n")
r = cli(mine, "remove", "fb", "--force", lib=m)
check("мутант: --force без проверок ветки и метки — грязная копия на ветке убрана", r.returncode == 0
      and not os.path.exists(wt(mine, "fb")), r.stderr)
m = mutant("    if force and not (gd and os.path.isfile(os.path.join(gd, DETACH_MARK))):\n", "    if False:\n")
r = cli(mine, "remove", "ext-1", "--force", lib=m)
check("мутант: --force без метки — чужая detached-копия с несохранённым убрана", r.returncode == 0
      and not os.path.exists(wt(mine, "ext-1")), r.stderr)
open(os.path.join(gitdir(wt(mine, "tmp-8")), "MERGE_HEAD"), "w").write(git(mine, "rev-parse", "HEAD") + "\n")
m = mutant("    if force and busy:\n", "    if False:\n")
r = cli(mine, "remove", "tmp-8", "--force", lib=m)
check("мутант: --force без проверки merge — копия посреди merge убрана", r.returncode == 0
      and not os.path.exists(wt(mine, "tmp-8")), r.stderr)
m = mutant("    if branch is None:\n", "    if False:\n")
r = cli(mine, "add", "tmp-m", "--detach", lib=m)
check("мутант: --detach без своей ветви кода — копии без ветки нет", r.returncode != 0
      or git(wt(mine, "tmp-m"), "rev-parse", "--abbrev-ref", "HEAD") != "HEAD", r.stdout + r.stderr)


# F2: GIT_CONFIG_NOSYSTEM=1 и без GIT_* окна — по самому вызову git (системный gitconfig в тесте не подменить)
def git_env(src):
    seen = {}

    class Run:
        @staticmethod
        def run(args, **kw):
            seen.update(kw.get("env") or {})
            return subprocess.CompletedProcess(args, 0, "", "")
    ns = {"__name__": "wt_under_test"}
    exec(compile(src, "worktree.py", "exec"), ns)
    ns["subprocess"] = Run
    os.environ["GIT_DIR"] = "/nowhere"
    try:
        ns["_git"](["status"], ROOT)
    finally:
        del os.environ["GIT_DIR"]
    return seen


wsrc = open(os.path.join(LIB, "worktree.py"), encoding="utf-8").read()
e = git_env(wsrc)
check("git: GIT_CONFIG_NOSYSTEM=1, GIT_DIR окна снят", e.get("GIT_CONFIG_NOSYSTEM") == "1" and "GIT_DIR" not in e, e)
nosys = '    env["GIT_CONFIG_NOSYSTEM"] = "1"\n'
check("самопроверка мутанта: строка NOSYSTEM одна", wsrc.count(nosys) == 1)
check("мутант: без NOSYSTEM — проверка выше краснеет", git_env(wsrc.replace(nosys, "")).get("GIT_CONFIG_NOSYSTEM") != "1")

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
