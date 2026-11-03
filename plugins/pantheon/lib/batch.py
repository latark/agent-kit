"""Пантеон: пачка — одна ветка и один PR (metis-0757, решение владельца 03.11 [zeus-fast-2d]).

`pantheon batch start <story>` — ветка batch/<story> от origin/main и worktree .claude/worktrees/batch-<story> в
репозитории текущей папки. `pantheon batch pr <story>` — один PR этой ветки в main (уже открыт — обновляет его тело).
Closes в теле — только задачам пачки, чей номер есть в коммитах ветки от origin/main (сообщение коммита или имя влитой
ветки): по Closes плановый проход (lib/autoclose.py) ставит задаче review при открытом PR и done при слиянии, и
недоделанная задача не должна закрыться вместе с пачкой. Остальные открытые — списком «не вошли», без Closes.
Задача с неотмеченным пунктом «Готово, когда» или заглушкой (metis-0767) тоже без Closes: слитый PR оставил бы её в
review, а не в done; в stderr — «<id>: неотмечено N», строка тела «Не целиком, остаются открытыми».
Шлюз guard не трогается: PR пачки он проверяет как любой другой.

P — модуль pantheon: его ставит загрузчик pantheon._attach до выполнения этого файла.
"""
import os
import re
import subprocess
import sys

__all__ = ["BATCH_ID", "batch_branch", "batch_body", "branch_ids", "batch_cmd"]

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
    if not [x for _, x in T.done_criteria(tasks[sid][2]) if not T._is_stub(x)]:
        return None, (f"у пачки {sid} нет критериев «Готово, когда» (только заглушка или раздела нет) — впиши проверяемые "
                      f"пункты в карточку story (pantheon task set {sid} --body-file …), заглушка пачку не закроет (metis-0766)")
    return tasks, None


ID_IN = re.compile(r"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")  # номер задачи, как ID_RE в autoclose.py


PART_ID = re.compile(r"(?<!\w)часть\s+(" + ID_IN.pattern + ")", re.I)
# слово «часть» в теле PR autoclose читает как «PR делает часть» и не закрывает НИ ОДНОЙ его задачи (PART_RE): в тело
# оно не должно попасть ни из заголовка задачи, ни из нашего текста
PART_WORD = re.compile(r"(?<!\w)часть(?!\w)", re.I)


def branch_ids(cwd):
    """(номера задач в коммитах ветки от origin/main — сообщения и «Merge branch '<id>-…'»; номера, которые хоть один
    коммит называет «часть <id>» — задача сделана не вся, Closes ей не ставим). None — git не ответил."""
    r = _git(["log", "--format=%B", "origin/" + BASE + "..HEAD"], cwd)
    if r.returncode != 0:
        return None
    return set(ID_IN.findall(r.stdout)), set(PART_ID.findall(r.stdout))


def _plain(text):
    return PART_WORD.sub("ч.", text)


def unchecked(tasks, tid):
    """Число неотмеченных пунктов «Готово, когда» карточки; заглушка DONE_WHEN_HINT — тоже неотмечено (разбор —
    T.done_criteria, тот же, по которому autoclose считает «неотмечено N»)."""
    T = P.tasks_mod()
    return sum(1 for done, _ in T.done_criteria(tasks[tid][2]) if not done)


def batch_body(sid, tasks, done_ids, part_ids=()):
    """(заголовок, тело PR пачки): задачи по порядку пачки; Closes — открытым задачам (не story) с номером в коммитах
    ветки (done_ids), кроме названных в коммите «часть <id>» (part_ids) — они «частично»; прочие открытые — «не
    вошли». Ни те, ни другие Closes не получают."""
    T = P.tasks_mod()
    head = tasks[sid][1]
    ids = [i for i in T.story_order(sid, tasks) if tasks[i][1].get("type") != "story"]
    opened = [i for i in ids if tasks[i][1].get("status") not in ("done", "dropped")]
    half = [i for i in opened if i in part_ids]
    left = {i: unchecked(tasks, i) for i in opened if i in done_ids and i not in half}
    left = {i: n for i, n in left.items() if n}
    half += [i for i in opened if i in left]
    shut = [i for i in opened if i in done_ids and i not in half]
    for i, n in left.items():
        print(f"{i}: неотмечено {n} — отметь пункты в карточке или оставь открытой", file=sys.stderr)
    out = [i for i in opened if i not in done_ids and i not in half]
    lines = [f"Пачка {sid}: {_plain(T.one_line(head.get('title')))}", "", "Задачи пачки:"]
    for i in ids:
        h = tasks[i][1]
        mark = "в ветке" if i in shut else "частично" if i in half else "не вошла" if i in out else h.get("status") or "?"
        lines.append(f"- {i} · {mark} · {_plain(T.one_line(h.get('title')))}")
    if not ids:
        lines.append("- (задач нет)")
    if out:
        lines += ["", "Не вошли в ветку (коммитов с их номером нет), после слияния остаются открытыми: " + "; ".join(out)]
    if half:
        lines += ["", "Не целиком, остаются открытыми: " + "; ".join(half)]
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
    found = branch_ids(cwd)
    if found is None:
        print(f"pantheon batch pr: git log origin/{BASE}..HEAD не прошёл — Closes не из чего собрать", file=sys.stderr)
        return 1
    title, body = batch_body(sid, tasks, *found)
    if dry:
        print(title + "\n\n" + body, end="")
        return 0
    env = {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}
    have = subprocess.run(["gh", "pr", "list", "--head", br, "--state", "open", "--json", "number", "--jq", ".[0].number"],
                          cwd=cwd, env=env, capture_output=True, text=True)
    if have.returncode != 0:
        print(f"pantheon batch pr: gh pr list не прошёл: {have.stderr.strip()[:300]}", file=sys.stderr)
        return 1
    num = have.stdout.strip()
    if num.isdigit():
        argv = ["gh", "pr", "edit", num, "--title", title, "--body", body]
    else:
        argv = ["gh", "pr", "create", "--base", BASE, "--head", br, "--title", title, "--body", body]
    return subprocess.run(argv, cwd=cwd, env=env).returncode


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
