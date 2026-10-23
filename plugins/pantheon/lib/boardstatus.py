"""Статусы задач и пачек в шаг с работой (metis-0397, расширение 24.10: «вся доска», влита metis-0399).

Плановый проход доски (`pantheon board`, главный Mac) до сборки видов доски сверяет статусы по следам работы — без
модели и без ролей:
  - задача todo, а в репозитории её направления живая worktree на ветке с её id (`metis-0397-…` — тот же признак, по
    которому автозакрытие закрывает задачу при слиянии) → doing, строка в журнал задачи; вернули в todo после этого —
    второй раз не трогаем, а тревожим (worktree идёт, а задача в очереди);
  - задача todo с открытым PR, который её закрывает (номер в ветке или «Closes» в теле), — review ставит автозакрытие
    (lib/autoclose.py, run); не вышло (PR из репозитория чужого направления) — та же тревога;
  - пачка (story) — по составу: есть задача doing или review → doing («В работе»; из inbox, todo и done), все задачи
    done или dropped → done («Готово»; из inbox, todo, doing, review). Пачку в waiting (ждёт человека) и dropped,
    пачку без задач и смешанный состав без работы — не трогаем.
Выдача исполнителю командой `pantheon task claim` ставит doing сама (tasks.task_claim).

Только стандартная библиотека, Python 3.9+: тесты зовут модуль напрямую, проход — из pantheon.py.
"""
import glob
import os
import re

ID_RE = re.compile(r"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")  # как в autoclose.find_ids
STORY_DOING_FROM = ("inbox", "todo", "done")
STORY_DONE_FROM = ("inbox", "todo", "doing", "review")
WT_MARK = "worktree на ветке"   # строка журнала задачи: по ней проход второй раз задачу не двигает
REVIEW_MARK = "открыт → review"  # то же — у автозакрытия (autoclose.REVIEW_MARK)


def story_target(sid, tasks):
    """Статус, который пачке нужен по составу, или None — оставить как есть."""
    head = tasks[sid][1]
    kids = [h.get("status") for _, h, _ in tasks.values() if h.get("parent") == sid and h.get("type") == "task"]
    if not kids:
        return None
    st = head.get("status")
    if any(k in ("doing", "review") for k in kids):
        return "doing" if st in STORY_DOING_FROM else None
    if all(k in ("done", "dropped") for k in kids):
        return "done" if st in STORY_DONE_FROM else None
    return None


def roots(domains):
    """{направление: [корни репозиториев]} из domains.json (папки направлений с .git)."""
    out = {}
    for name, folders in (domains or {}).items():
        for f in folders if isinstance(folders, list) else []:
            if not isinstance(f, str):
                continue
            root = os.path.realpath(os.path.expanduser(f))
            if os.path.isdir(os.path.join(root, ".git")):
                out.setdefault(name, [])
                if root not in out[name]:
                    out[name].append(root)
    return out


def wt_heads(root):
    """Файлы HEAD записей worktree репозитория (<root>/.git/worktrees/*/HEAD) — для отпечатка входов прохода."""
    return sorted(glob.glob(os.path.join(root, ".git", "worktrees", "*", "HEAD")))


def _read(p, limit=4096):
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return None


def live_worktrees(root):
    """[(папка копии, ветка)] живых worktree репозитория: запись в .git/worktrees, папка копии на месте, HEAD — ветка.
    Без запуска git: проход идёт каждый тик."""
    out = []
    for head_file in wt_heads(root):
        d = os.path.dirname(head_file)
        m = re.match(r"ref: refs/heads/(\S+)", _read(head_file) or "")
        gitdir = (_read(os.path.join(d, "gitdir")) or "").strip()
        if not m or not gitdir:
            continue
        wt = os.path.dirname(gitdir)
        if os.path.isdir(wt):
            out.append((wt, m.group(1)))
    return out


def branch_ids(branch):
    return [m.group(0) for m in ID_RE.finditer(branch or "")]


def review_note(repo, number):
    """Строка журнала, которую пишет автозакрытие, ставя задаче review по открытому PR (тот же текст в autoclose.py)."""
    return f"PR #{number} ({repo}) {REVIEW_MARK}"


def plan(tasks, domains, open_closing=None):
    """Что сделать по следам работы → (moves, stale).
    moves — [(tid, changes, note)] для task_set; stale — {tid: причина} задач в todo, по которым идёт работа, но
    двигать проход не стал: их уже двигали этим же следом, а их вернули в todo (или worktree — в репозитории не их
    направления). open_closing — {id задачи: [(repo, номер)]} открытых PR, которые её закрывают (кэш autoclose)."""
    moves, stale = [], {}
    dirs_of = {}
    for d, rs in roots(domains).items():
        for root in rs:
            dirs_of.setdefault(root, set()).add(d)
    moved = set()
    for root in sorted(dirs_of):
        for wt, branch in live_worktrees(root):
            for tid in branch_ids(branch):
                path, h, body = tasks.get(tid, ("", {}, ""))
                if h.get("type") != "task" or h.get("status") != "todo" or tid in moved:
                    continue
                note = f"{WT_MARK} {branch} → doing"
                if h.get("direction") in dirs_of[root] and note not in (body or ""):
                    moves.append((tid, {"status": "doing"}, note))
                    moved.add(tid)
                    stale.pop(tid, None)
                else:
                    stale[tid] = f"worktree на ветке {branch}"
    for tid, prs in sorted((open_closing or {}).items()):
        _, h, body = tasks.get(tid, ("", {}, ""))
        if h.get("type") != "task" or h.get("status") != "todo" or tid in moved:
            continue
        back = [f"{r}#{n}" for r, n in prs if review_note(r, n) in (body or "")]
        if back:
            stale.setdefault(tid, "открытый PR " + ", ".join(back))
    # пачки — по составу с учётом задач, сдвинутых этим же проходом
    view = dict(tasks)
    for tid, ch, _ in moves:
        pth, h, body = view[tid]
        view[tid] = (pth, dict(h, **ch), body)
    for sid, (_, h, _) in sorted(tasks.items()):
        if h.get("type") == "story":
            want = story_target(sid, view)
            if want and want != h.get("status"):
                why = "есть задача в работе или на проверке" if want == "doing" else "все задачи закрыты"
                moves.append((sid, {"status": want}, f"пачка по составу: {why} → {want}"))
    return moves, stale
