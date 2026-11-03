"""Пантеон: пачка — одна ветка и один PR (metis-0757, решение владельца 03.11 [zeus-fast-2d]).

`pantheon batch start <story>` — ветка batch/<story> от origin/main и worktree .claude/worktrees/batch-<story> в
репозитории текущей папки. `pantheon batch pr <story>` — один PR этой ветки в main: в теле задачи пачки и строка
Closes на открытые. Шлюз guard не трогается: PR пачки он проверяет как любой другой.

P — модуль pantheon: его ставит загрузчик pantheon._attach до выполнения этого файла.
"""
import os
import re
import subprocess
import sys

__all__ = ["BATCH_ID", "batch_branch", "batch_body", "batch_cmd"]

BATCH_ID = re.compile(r"[a-z][a-z0-9-]{0,40}-\d{4}")
BASE = "main"


def batch_branch(sid):
    return "batch/" + sid


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _story(sid):
    """(карточка пачки, все задачи) или (None, причина)."""
    T = P.tasks_mod()
    tasks = T.load_tasks(P.PANTHEON, T.WORK_TYPES)
    if sid not in tasks or tasks[sid][1].get("type") != "story":
        return None, f"пачки {sid} нет (нужна карточка type: story)"
    return tasks, None


def batch_body(sid, tasks):
    """(заголовок, тело PR пачки): задачи по порядку пачки, Closes — на незакрытые задачи (не story)."""
    T = P.tasks_mod()
    head = tasks[sid][1]
    ids = [i for i in T.story_order(sid, tasks) if tasks[i][1].get("type") != "story"]
    lines = [f"Пачка {sid}: {T.one_line(head.get('title'))}", "", "Задачи пачки:"]
    for i in ids:
        h = tasks[i][1]
        lines.append(f"- {i} · {h.get('status') or '?'} · {T.one_line(h.get('title'))}")
    if not ids:
        lines.append("- (задач нет)")
    shut = [i for i in ids if tasks[i][1].get("status") not in ("done", "dropped")]
    if shut:
        lines += ["", "Closes " + ", ".join(shut)]
    return f"Пачка {sid}: {T.one_line(head.get('title'))}"[:200], "\n".join(lines) + "\n"


def _root(cwd):
    """Корень основной копии репозитория текущей папки (из worktree — тоже основная) или None."""
    r = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return os.path.dirname(r.stdout.strip().rstrip("/"))


def _start(sid, cwd):
    root = _root(cwd)
    if not root:
        print("pantheon batch start: текущая папка не в git-репозитории", file=sys.stderr)
        return 2
    br = batch_branch(sid)
    if _git(["rev-parse", "--verify", "--quiet", "refs/heads/" + br], root).returncode == 0:
        print(f"pantheon batch start: ветка {br} уже есть — работай в ней", file=sys.stderr)
        return 1
    f = _git(["fetch", "-q", "origin", BASE], root)
    if f.returncode != 0:
        print(f"pantheon batch start: git fetch origin {BASE} не прошёл: {f.stderr.strip()[:300]}", file=sys.stderr)
        return 1
    wt = os.path.join(root, ".claude", "worktrees", "batch-" + sid)
    a = _git(["worktree", "add", "-q", "-b", br, wt, "origin/" + BASE], root)
    if a.returncode != 0:
        print(f"pantheon batch start: git worktree add не прошёл: {a.stderr.strip()[:300]}", file=sys.stderr)
        return 1
    print(f"ветка {br} от origin/{BASE}, копия {wt}\nзадачи пачки — коммитами или слияниями в неё, узкие тесты; "
          f"PR — pantheon batch pr {sid}")
    return 0


def _pr(sid, tasks, cwd, dry):
    br = batch_branch(sid)
    cur = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if cur.returncode != 0 or cur.stdout.strip() != br:
        print(f"pantheon batch pr: запускай из копии ветки {br} (сейчас: {cur.stdout.strip() or '?'})", file=sys.stderr)
        return 2
    title, body = batch_body(sid, tasks)
    argv = ["gh", "pr", "create", "--base", BASE, "--head", br, "--title", title, "--body", body]
    if dry:
        print(title + "\n\n" + body, end="")
        return 0
    env = {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}
    r = subprocess.run(argv, cwd=cwd, env=env)
    return r.returncode


def batch_cmd(args, cwd=None):
    """pantheon batch start <story> | pr <story> [--dry-run]"""
    cwd = cwd or os.getcwd()
    dry = "--dry-run" in args
    rest = [a for a in args if a != "--dry-run"]
    if len(rest) != 2 or rest[0] not in ("start", "pr") or not BATCH_ID.fullmatch(rest[1]) or (dry and rest[0] != "pr"):
        print("pantheon batch: start <story-id> | pr <story-id> [--dry-run]", file=sys.stderr)
        return 2
    sub, sid = rest
    tasks, why = _story(sid)
    if tasks is None:
        print(f"pantheon batch {sub}: {why}", file=sys.stderr)
        return 1
    return _start(sid, cwd) if sub == "start" else _pr(sid, tasks, cwd, dry)
