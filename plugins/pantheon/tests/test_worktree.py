#!/usr/bin/env python3
"""pantheon worktree add|remove|list (metis-1225): worktree окна направления мимо песочницы — одна узкая команда.

- успех во временном репозитории: add (ветка = имя от HEAD, --branch/--base, уже есть ветка), list, remove; из worktree
  сессии (cwd в .claude/worktrees/<другая>) новая ложится в основную копию;
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
            ["remove", "h1", "--force"], ["remove", "../mine"], ["remove"], ["list", "x"], ["move", "a", "b"], []):
    r = cli(mine, *bad)
    check(f"отказ: worktree {' '.join(bad) or '(пусто)'} → код 2", r.returncode == 2 and r.stderr.strip(), r.stderr)
check("отказы ничего не создали", sorted(os.listdir(os.path.join(mine, ".claude", "worktrees"))) == ["b", "h1",
                                                                                                   "metis-1-a"])

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

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
