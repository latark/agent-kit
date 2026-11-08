#!/usr/bin/env python3
"""Замок доски BOARD_LOCK (metis-0882): `pantheon board archive` из окна Зевса и коммит ~/ai/pantheon не идут вместе.

Окно Зевса пишет в STATE только в hq-rw/ (metis-0523), замок pantheon-git в STATE/locks ему закрыт — board archive
падал PermissionError. Теперь переписывание board.md и коммит прохода делят замок BOARD_LOCK в STATE/hq-rw/locks.
Проверяет: в подменённой песочнице окна (запись в STATE вне hq-rw — PermissionError) lock("pantheon-git") падает, а
board archive переносит старое в archive/ с кодом 0; пока коммит держит замок, board archive отказывает кодом 1 и
board.md не трогает; пока board archive переписывает доску, коммит не идёт (TEMPFAIL, нового коммита нет);
`pantheon archive` тоже ждёт замок; застрявший замок больше 6 ч после последней синхронизации — тревога.

Запуск: python3 -I plugins/pantheon/tests/test_board_lock.py  (код выхода 0 — все прошли)
Настоящий git во временной папке, без remote; настоящие ~/ai/pantheon и ~/.local/state/pantheon не трогаются.
"""
import atexit
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311, mkroot  # noqa: E402

ROOT = os.path.realpath(mkroot("board-lock-"))
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:900]}]"))


NOW = datetime.strptime("2026-11-03 12:00", "%Y-%m-%d %H:%M").timestamp()
SRC = ("# Доска\n\n## Сейчас\n\nОбновлено 03.11 10:00.\n\n- 03.11 свежее\n- 20.10 старое A\n  хвост A\n\n"
       "## Сессии и хозяйство\n\n- 25.10 старое C\n- 02.11 свежее D\n")
GENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
home = os.path.join(ROOT, "home")
pan = os.path.join(ROOT, "pantheon")
state = os.path.join(ROOT, "state")
for d in (home, pan, os.path.join(state, "locks")):
    os.makedirs(d, exist_ok=True)
env = {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pan, "PANTHEON_STATE": state,
       "PANTHEON_VIEW": os.path.join(ROOT, "view"), "PANTHEON_HOST": "mac-a", "PANTHEON_NO_NOTIFY": "1",
       "PANTHEON_NOTIFY_LOG": os.path.join(ROOT, "notify.log"), "PANTHEON_METRICS": "0", "PANTHEON_NOW": str(NOW),
       "PANTHEON_HQ_LOCK_WAIT": "1", "TMPDIR": ROOT, **GENV}
BM = os.path.join(pan, "board.md")
ARCH = os.path.join(pan, "archive")
LOCKF = os.path.join(state, "hq-rw", "locks", "board-git.lock")


def git(*a):
    return subprocess.run(["git", "-C", pan, *a], env=env, capture_output=True, text=True, check=True).stdout


git("init", "-q", "-b", "main")
with open(os.path.join(pan, "a.md"), "w", encoding="utf-8") as fh:
    fh.write("a\n")
git("add", "-A")
git("commit", "-q", "-m", "init")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def write(p, text):
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


# Подмена песочницы окна Зевса: любая запись в STATE вне STATE/hq-rw — PermissionError, как у Seatbelt (EPERM).
# hq_open открывает файл относительно дескриптора папки hq-rw/<sub> — такой путь пропускаем.
HQ = ("import builtins, errno, os, sys, time; sys.path.insert(0, %r); import pantheon as p\n"
      "ST, HQ = p.STATE + os.sep, os.path.join(p.STATE, 'hq-rw') + os.sep\n"
      "W = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC\n"
      "def closed(f):\n"
      "    f = os.path.abspath(os.fsdecode(f)) + os.sep\n"
      "    return f.startswith(ST) and not f.startswith(HQ)\n"
      "def deny(f): raise PermissionError(errno.EPERM, 'Operation not permitted', f)\n"
      "if 'hq' in sys.argv[2:]:\n"
      "    ropen, rmkdir, bopen = os.open, os.mkdir, builtins.open\n"
      "    def o(f, flags, mode=0o777, *, dir_fd=None):\n"
      "        if dir_fd is None and flags & W and closed(f): deny(f)\n"
      "        return ropen(f, flags, mode, dir_fd=dir_fd)\n"
      "    def md(f, mode=0o777, *, dir_fd=None):\n"
      "        if dir_fd is None and closed(f): deny(f)\n"
      "        return rmkdir(f, mode, dir_fd=dir_fd)\n"
      "    def bo(f, mode='r', *a, **k):\n"
      "        if isinstance(f, (str, bytes, os.PathLike)) and set(mode) & set('wax+') and closed(f): deny(f)\n"
      "        return bopen(f, mode, *a, **k)\n"
      "    os.open, os.mkdir, builtins.open = o, md, bo\n"
      "what = sys.argv[1]\n"
      "if what == 'probe':\n"
      "    try:\n"
      "        with p.lock('pantheon-git'):\n"
      "            print('git-lock: взят')\n"
      "    except PermissionError as e:\n"
      "        print('git-lock: PermissionError', e.filename)\n"
      "    sys.exit(0)\n"
      "if what == 'board-slow':  # board archive, который держит замок доски 3 с посреди разбора\n"
      "    M = p.boardmd_mod(); real = M.split\n"
      "    def split(*a):\n"
      "        open(os.path.join(p.STATE, 'hq-rw', 'started'), 'w').close(); time.sleep(3); return real(*a)\n"
      "    M.split = split; p.boardmd_mod = lambda: M\n"
      "    sys.exit(p.board_archive([]))\n"
      "if what == 'commit-slow':  # коммит, который держит замки 3 с перед git add\n"
      "    g = p.commit.__globals__; real = g['data_guard']  # имя модуля lib/archive.py, а не копия в pantheon\n"
      "    def dg():\n"
      "        open(os.path.join(p.STATE, 'commit-started'), 'w').close(); time.sleep(3); return real()\n"
      "    g['data_guard'] = dg\n"
      "    sys.exit(p.commit())\n"
      "sys.exit(p.main(sys.argv[1].split()))\n" % LIB)


def run(what, *flags, extra=None):
    return subprocess.run([PY311, "-I", "-c", HQ, what, *flags], env=dict(env, **(extra or {})), capture_output=True,
                          text=True, timeout=120)


def start(what, marker):
    if os.path.exists(marker):
        os.remove(marker)
    pr = subprocess.Popen([PY311, "-I", "-c", HQ, what], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True)
    deadline = time.monotonic() + 30
    while not os.path.exists(marker) and time.monotonic() < deadline and pr.poll() is None:
        time.sleep(0.05)
    check(f"{what}: процесс дошёл до места под замком (метка {os.path.basename(marker)})", os.path.exists(marker)
          and pr.poll() is None, pr.poll())
    return pr


def commits():
    return int(git("rev-list", "--count", "HEAD").strip())


# --- 1. окно Зевса: pantheon-git недоступен, board archive работает ----------------------------------------------------
r = run("probe", "hq")
check("1. подменённая песочница окна: lock('pantheon-git') в STATE/locks → PermissionError (так падала команда)",
      "git-lock: PermissionError" in r.stdout and os.path.join(state, "locks", "pantheon-git.lock") in r.stdout,
      r.stdout + r.stderr)
write(BM, SRC)
r = run("board archive", "hq")
a10 = os.path.join(ARCH, "2026-10.md")
check("1. board archive в окне Зевса → код 0, старое в archive/2026-10.md, board.md без него, трассировки нет",
      r.returncode == 0 and "- 20.10 старое A" not in read(BM) and "- 03.11 свежее" in read(BM)
      and os.path.exists(a10) and "- 20.10 старое A" in read(a10) and "  хвост A" in read(a10)
      and "- 25.10 старое C" in read(a10) and "Traceback" not in r.stderr, (r.returncode, r.stdout, r.stderr[-600:]))
check("1. замок доски — в STATE/hq-rw/locks, в STATE/locks окно ничего не создало",
      os.path.isfile(LOCKF) and not os.path.exists(os.path.join(state, "locks", "pantheon-git.lock")),
      sorted(os.listdir(os.path.join(state, "locks"))))
git("add", "-A")
git("commit", "-q", "-m", "после архива")

# --- 2. замок держит другой процесс: board archive отказывает, commit и archive ждут -----------------------------------
write(BM, SRC)
before_arch = read(a10)
with open(LOCKF, "a") as held:
    fcntl.flock(held, fcntl.LOCK_EX)
    r = run("board archive", "hq")
    check("2. замок доски занят → board archive: код 1, «повтори», board.md и архив не тронуты",
          r.returncode == 1 and "повтори" in r.stderr and read(BM) == SRC and read(a10) == before_arch
          and "Traceback" not in r.stderr, (r.returncode, r.stderr[-400:]))
    n0 = commits()
    r = run("commit")
    check("2. замок доски занят → commit: код 75 (TEMPFAIL), нового коммита нет, причина в stderr",
          r.returncode == 75 and commits() == n0 and "board-git" in r.stderr.strip().splitlines()[-1],
          (r.returncode, commits(), n0, r.stderr[-400:]))
    r = run("archive")
    check("2. замок доски занят → pantheon archive: код 75, board.md не тронут",
          r.returncode == 75 and read(BM) == SRC and "board-git" in r.stderr, (r.returncode, r.stderr[-400:]))
    # застрявший замок: последняя синхронизация больше 6 ч назад — тревога, а не вечная тишина TEMPFAIL
    with open(os.path.join(state, "commit-ok.json"), "w") as fh:
        json.dump({"t": NOW - 7 * 3600}, fh)
    r = run("commit")
    alerts = read(os.path.join(pan, "alerts.md")) if os.path.exists(os.path.join(pan, "alerts.md")) else ""
    check("2. замок занят, синхронизации нет 7 ч → тревога «не коммитится больше 6 часов»",
          r.returncode == 75 and "не коммитится больше 6 часов" in alerts, (r.returncode, alerts[-300:], r.stderr[-300:]))
    with open(os.path.join(state, "commit-ok.json"), "w") as fh:
        json.dump({"t": NOW - 3600}, fh)
    os.remove(os.path.join(pan, "alerts.md"))
    for f in os.listdir(state):
        if "commit-board-lock" in f:
            os.remove(os.path.join(state, f))
    r = run("commit")
    check("2. замок занят, синхронизация час назад → тревоги нет (обычная заминка)",
          r.returncode == 75 and not os.path.exists(os.path.join(pan, "alerts.md")), (r.returncode, r.stderr[-300:]))
r = run("commit")
check("2. замок свободен → commit: код 0, правка board.md закоммичена", r.returncode == 0 and commits() == n0 + 1
      and not git("status", "--porcelain").strip(), (r.returncode, r.stderr[-400:]))

# --- 3. настоящая пара: архивация и коммит тика не идут одновременно ---------------------------------------------------
check("3. исходная доска закоммичена", git("show", "HEAD:board.md") == SRC and read(BM) == SRC)
pr = start("board-slow", os.path.join(state, "hq-rw", "started"))
n0 = commits()
r = run("commit")
out, err = pr.communicate(timeout=60)
check("3. board archive переписывает доску → коммит тика в это время: код 75, нового коммита нет",
      r.returncode == 75 and commits() == n0, (r.returncode, commits(), n0, r.stderr[-400:]))
check("3. board archive после этого закончил: код 0, старое в архиве", pr.returncode == 0 and "- 20.10 старое A" not in read(BM),
      (pr.returncode, out, err[-400:]))
r = run("commit")
check("3. следующий проход коммитит перенос", r.returncode == 0 and commits() == n0 + 1, (r.returncode, r.stderr[-300:]))

write(BM, SRC)
write(os.path.join(pan, "b.md"), "b\n")
pr = start("commit-slow", os.path.join(state, "commit-started"))
r = run("board archive", "hq")
out, err = pr.communicate(timeout=60)
check("3. коммит тика идёт → board archive из окна Зевса в это время: код 1, board.md не тронут",
      r.returncode == 1 and "повтори" in r.stderr and read(BM) == SRC, (r.returncode, r.stdout, r.stderr[-400:]))
check("3. коммит закончил сам: код 0, закоммичена доска как была (не вполовину переписанная)",
      pr.returncode == 0 and git("show", "HEAD:board.md") == SRC, (pr.returncode, err[-400:]))

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
