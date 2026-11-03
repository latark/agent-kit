#!/usr/bin/env python3
"""Пачка — одна ветка и один PR (metis-0757): pantheon batch start|pr.

Запуск: python3 -I plugins/pantheon/tests/test_batch.py  (код выхода 0 — все прошли)
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="batch-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIB, "run.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def card(path, head, body=""):
    lines = ["---"] + [f"{k}: {v}" for k, v in head.items()] + ["---", "", f"# {head['title']}", "", body]
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


tmp = os.path.realpath(tempfile.mkdtemp(prefix="batch-test-"))
home, state, view, bindir = (os.path.join(tmp, x) for x in ("pantheon", "state", "view", "bin"))
tdir = os.path.join(home, "directions", "metis-pantheon", "tasks")
os.makedirs(tdir)
os.makedirs(view)
os.makedirs(bindir)
open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
open(os.path.join(home, "directions.toml"), "w", encoding="utf-8").write(
    '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n')
base = {"project": "Пантеон", "direction": "metis-pantheon", "owner": "metis-pantheon", "created": "2026-11-03",
        "updated": "2026-11-03T12:00:00", "schema_version": 1}
card(os.path.join(tdir, "metis-0900.md"), {"type": "story", "id": "metis-0900", "title": '"П9 Пачка"',
                                           "status": "doing", **base})
card(os.path.join(tdir, "metis-0901.md"), {"type": "task", "id": "metis-0901", "title": '"Первая"', "status": "doing",
                                           "parent": "metis-0900", **base})
card(os.path.join(tdir, "metis-0902.md"), {"type": "task", "id": "metis-0902", "title": '"Вторая"', "status": "todo",
                                           "parent": "metis-0900", "depends_on": "[metis-0901]", **base})
card(os.path.join(tdir, "metis-0903.md"), {"type": "task", "id": "metis-0903", "title": '"Готовая"', "status": "done",
                                           "parent": "metis-0900", **base})
card(os.path.join(tdir, "metis-0904.md"), {"type": "task", "id": "metis-0904", "title": '"Чужая"', "status": "todo",
                                           **base})

# репозиторий с origin: голый origin, копия с main
origin = os.path.join(tmp, "origin.git")
repo = os.path.join(tmp, "repo")
subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
genv = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
os.environ.update(genv)
open(os.path.join(repo, "a.txt"), "w").write("a\n")
git(repo, "add", "a.txt")
git(repo, "commit", "-q", "-m", "init")
git(repo, "remote", "add", "origin", origin)
git(repo, "push", "-q", "origin", "main")
main_sha = git(repo, "rev-parse", "HEAD")

# поддельный gh: пишет argv построчно (NUL-разделитель) в файл
ghlog = os.path.join(tmp, "gh.log")
open(os.path.join(bindir, "gh"), "w").write(
    f"#!/bin/sh\nfor a in \"$@\"; do printf '%s\\0' \"$a\"; done > '{ghlog}'\necho https://github.com/x/y/pull/9\n")
os.chmod(os.path.join(bindir, "gh"), 0o755)

env = {"PATH": bindir + os.pathsep + os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
       "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
       "PANTHEON_FAKE_IDLE": "0", "TMPDIR": _ROOT, "GH_REPO": "evil/repo", **genv}


def cli(cwd, *a):
    return subprocess.run([PY311, "-I", RUN_PY, *a], cwd=cwd, env=env, capture_output=True, text=True)


# разбор
for bad in ([], ["start"], ["go", "metis-0900"], ["start", "../x"], ["start", "metis-0900", "x"],
            ["start", "metis-0900", "--dry-run"]):
    r = cli(repo, "batch", *bad)
    check(f"разбор: batch {' '.join(bad) or '(пусто)'} → код 2", r.returncode == 2, r.stderr[-200:])
r = cli(repo, "batch", "start", "metis-0901")
check("start на задаче, не пачке → код 1, «нет»", r.returncode == 1 and "нет" in r.stderr, r.stderr)

# start
r = cli(repo, "batch", "start", "metis-0900")
wt = os.path.join(repo, ".claude", "worktrees", "batch-metis-0900")
check("start: код 0, копия создана", r.returncode == 0 and os.path.isdir(wt), r.stdout + r.stderr)
check("start: ветка batch/metis-0900 от origin/main",
      os.path.isdir(wt) and git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "batch/metis-0900"
      and git(wt, "rev-parse", "HEAD") == main_sha)
r = cli(repo, "batch", "start", "metis-0900")
check("start повторно → код 1, «уже есть»", r.returncode == 1 and "уже есть" in r.stderr, r.stderr)
r = cli(wt, "batch", "start", "metis-0900")
check("start из копии пачки — тот же репозиторий, «уже есть»", r.returncode == 1 and "уже есть" in r.stderr, r.stderr)

# pr
r = cli(repo, "batch", "pr", "metis-0900")
check("pr не из ветки пачки → код 2, gh не зван", r.returncode == 2 and not os.path.exists(ghlog), r.stderr)
r = cli(wt, "batch", "pr", "metis-0900", "--dry-run")
check("pr --dry-run: тело напечатано, gh не зван", r.returncode == 0 and "Closes" in r.stdout
      and not os.path.exists(ghlog), r.stdout + r.stderr)
out = r.stdout
check("тело: задачи пачки по порядку, чужой нет",
      out.find("metis-0901") < out.find("metis-0902") < out.find("Closes") and "metis-0903" in out
      and "metis-0904" not in out, out)
check("тело: Closes — на открытые, без закрытой и без самой пачки",
      "Closes metis-0901, metis-0902\n" in out and "Closes metis-0900" not in out, out)
r = cli(wt, "batch", "pr", "metis-0900")
argv = open(ghlog).read().split("\0")[:-1] if os.path.exists(ghlog) else []
check("pr: gh pr create --base main --head batch/metis-0900", r.returncode == 0 and argv[:7] == [
    "pr", "create", "--base", "main", "--head", "batch/metis-0900", "--title"], str(argv))
check("pr: заголовок и тело с Closes", len(argv) == 10 and argv[7].startswith("Пачка metis-0900")
      and argv[8] == "--body" and "Closes metis-0901, metis-0902" in argv[9], str(argv))
check("pr: ссылка gh в выводе", "pull/9" in r.stdout, r.stdout)

# GH_REPO не доходит до gh
open(os.path.join(bindir, "gh"), "w").write(f"#!/bin/sh\necho \"$GH_REPO\" > '{ghlog}'\n")
cli(wt, "batch", "pr", "metis-0900")
check("pr: GH_REPO из окружения до gh не доходит", open(ghlog).read().strip() == "")

r = subprocess.run([PY311, "-I", RUN_PY, "help"], env=env, capture_output=True, text=True)
check("справка называет batch start|pr", "batch start|pr" in r.stdout)

print(f"\n{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
