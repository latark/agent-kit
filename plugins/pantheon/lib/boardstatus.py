"""Статусы задач и пачек в шаг с работой (metis-0397, расширение 24.10: «вся доска», влита metis-0399).

Плановый проход доски (`pantheon board`, главный Mac) до сборки видов доски сверяет статусы по следам работы — без
модели и без ролей:
  - задача todo, а в репозитории её направления живая worktree на ветке с её id (`metis-0397-…` — тот же признак, по
    которому автозакрытие закрывает задачу при слиянии) → doing, строка в журнал задачи; вернули в todo после этого —
    второй раз не трогаем, а тревожим (worktree идёт, а задача в очереди);
  - задача todo с открытым PR, который её закрывает (номер в ветке или «Closes» в теле), — review ставит автозакрытие
    (lib/autoclose.py, run); не вышло (PR из репозитория чужого направления) — та же тревога;
  - пачка (story) — по составу: есть задача doing или review → doing («В работе»; из inbox, todo и done), все задачи
    done или dropped → done («Готово»; из inbox, todo, doing). Пачку в waiting (ждёт человека), review (приёмка — её
    закрывает человек, а не состав) и dropped, пачку без задач и смешанный состав без работы — не трогаем. Пачку с
    открытым вопросом владельцу (question, options, requested) не двигаем вовсе — done стёр бы вопрос (tasks.task_set),
    — а тревожим. Сдвиг пачки — строка в её журнал; проход уже ставил этот статус, а пачку вернули руками (закрыли,
    открыли) — второй раз не двигаем, а тревожим, как у задач. Пачку, которая уже в doing не проходом (создана так,
    выдана, поставлена руками) и состав держит её там, проход один раз отмечает в журнале той же строкой без сдвига:
    закрыли её потом руками — второй раз не открываем, а тревожим (metis-0412). Вопрос владельцу, появившийся между
    планом и записью, сверяет проверка под блокировкой (pantheon.board_status_sync): сдвиг не стирает его.
Выдача исполнителю командой `pantheon task claim` ставит doing сама (tasks.task_claim).

Только стандартная библиотека, Python 3.9+: тесты зовут модуль напрямую, проход — из pantheon.py.
"""
import glob
import os
import re

ID_RE = re.compile(r"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")  # как в autoclose.find_ids
STORY_DOING_FROM = ("inbox", "todo", "done")
STORY_DONE_FROM = ("inbox", "todo", "doing")  # review — приёмка человеком, не состав
WT_MARK = "worktree на ветке"   # строка журнала задачи: по ней проход второй раз задачу не двигает
REVIEW_MARK = "открыт → review"  # то же — у автозакрытия (autoclose.REVIEW_MARK)
STORY_MARK = "пачка по составу:"  # строка журнала пачки при сдвиге проходом: «… → <статус>»
STORY_HOLD = ("question", "options", "requested")  # открытое решение владельца: пачку с ним проход не двигает
STORY_MOVE_RE = re.compile(r"— плановый проход: " + re.escape(STORY_MARK) + r"[^\n]*→ (\w+)")


def last_story_move(body):
    """Статус, который проход ставил пачке последним (по строкам её журнала), или None."""
    found = STORY_MOVE_RE.findall(body or "")
    return found[-1] if found else None


def story_want(sid, tasks):
    """Статус, которого требует состав пачки, без оглядки на её текущий статус: doing, done или None."""
    kids = [h.get("status") for _, h, _ in tasks.values() if h.get("parent") == sid and h.get("type") == "task"]
    if not kids:
        return None
    if any(k in ("doing", "review") for k in kids):
        return "doing"
    if all(k in ("done", "dropped") for k in kids):
        return "done"
    return None


def story_target(sid, tasks):
    """Статус, который пачке нужен по составу, или None — оставить как есть."""
    want, st = story_want(sid, tasks), tasks[sid][1].get("status")
    if want == "doing":
        return "doing" if st in STORY_DOING_FROM else None
    if want == "done":
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
    moves — [(tid, changes, note)] для task_set (changes пустой — только отметка в журнале пачки); stale — {tid:
    причина} задач в todo, по которым идёт работа, но двигать проход не стал: их уже двигали этим же следом, а их вернули в todo (или worktree — в репозитории не их
    направления); и пачек, которым состав требует другой статус, а проход не двигает: открыт вопрос владельцу или
    этот статус проход уже ставил, а пачку вернули руками. open_closing — {id задачи: [(repo, номер)]} открытых PR, которые её закрывают (кэш autoclose)."""
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
    for sid, (_, h, body) in sorted(tasks.items()):
        if h.get("type") != "story":
            continue
        want = story_target(sid, view)
        held = [f for f in STORY_HOLD if h.get(f)]
        if h.get("status") == "doing" and story_want(sid, view) == "doing" and not held \
                and last_story_move(body) != "doing":  # в doing не проходом: отметка — ручное закрытие не откроем
            moves.append((sid, {}, f"{STORY_MARK} уже в работе, есть задача в работе или на проверке → doing"))
            continue
        if not want or want == h.get("status"):
            continue
        if held:  # done стёр бы вопрос и выбор владельца (tasks.task_set), doing — увёл бы пачку из «Нужен ответ»
            stale[sid] = f"пачка ждёт ответа владельца ({', '.join(held)}), по составу — {want}"
        elif last_story_move(body) == want:  # проход уже ставил этот статус, а пачку вернули руками
            stale[sid] = f"пачку вернули руками в {h.get('status')} после сдвига проходом в {want}"
        else:
            why = "есть задача в работе или на проверке" if want == "doing" else "все задачи закрыты"
            moves.append((sid, {"status": want}, f"{STORY_MARK} {why} → {want}"))
    return moves, stale
