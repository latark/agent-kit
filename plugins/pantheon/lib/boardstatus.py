"""Статусы задач и пачек в шаг с работой (metis-0397, расширение 24.10: «вся доска», влита metis-0399).

Плановый проход доски (`pantheon board`, главный Mac) до сборки видов доски сверяет статусы по следам работы — без
модели и без ролей:
  - задача todo, а в репозитории её направления живая worktree на ветке с её id (`metis-0397-…` — тот же признак, по
    которому автозакрытие закрывает задачу при слиянии) → doing, строка в журнал задачи; вернули в todo после этого —
    второй раз не трогаем, а тревожим (worktree идёт, а задача в очереди);
  - задача todo с открытым PR, который её закрывает (номер в ветке или «Closes» в теле), — review ставит автозакрытие
    (lib/autoclose.py, run); не вышло (PR из репозитория чужого направления) — та же тревога;
  - пачка (story) — по составу: есть задача doing или review → doing («В работе»; из inbox, todo и done), все задачи
    done или dropped → done («Готово»; из inbox, todo, doing). Пачка пачек (metis-0803) — так же: вложенная пачка
    (parent или batch = id) в составе наравне с задачами, по своему статусу. Пачку в waiting (ждёт человека), review (приёмка — её
    закрывает человек, а не состав) и dropped, пачку без задач и смешанный состав без работы — не трогаем. Пачку с
    открытым вопросом владельцу (question, options, requested) не двигаем вовсе — done стёр бы вопрос (tasks.task_set),
    — а тревожим. Сдвиг пачки — строка в её журнал; проход уже ставил этот статус, а пачку вернули руками (закрыли,
    открыли) — второй раз не двигаем, а тревожим, как у задач. Пачку, которая уже в doing не проходом (создана так,
    выдана, поставлена руками) и состав держит её там, проход один раз отмечает в журнале той же строкой без сдвига:
    закрыли её потом руками — второй раз не открываем, а тревожим (metis-0412). Вопрос владельцу, появившийся между
    планом и записью, сверяет проверка под блокировкой (pantheon.board_status_sync): сдвиг не стирает его.
Выдача исполнителю командой `pantheon task claim` ставит doing сама (tasks.task_claim).

Только стандартная библиотека: тесты зовут модуль напрямую, проход — из pantheon.py.
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
    """Статус, которого требует состав пачки, без оглядки на её текущий статус: doing, done или None. Состав — как у
    tasks.story_children: задачи и пачки с parent = sid и пачки с batch = sid (пачка пачек, metis-0803); вложенная
    пачка считается по своему статусу, как задача."""
    kids = [h.get("status") for tid, (_, h, _) in tasks.items() if tid != sid and (
        h.get("parent") == sid and h.get("type") in ("task", "story") or h.get("type") == "story" and h.get("batch") == sid)]
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


# --- хозяин задачи и следы работы (metis-0868) -------------------------------------------------------------------
# Проход доски сверяет «Кому» открытых задач с окнами сессий (снимок `pantheon agents`, STATE/agents.json, и реестр
# имён ~/.claude/sessions): сессию переименовали — owner карточек следует за ней по sessionId, а не по имени; хозяина
# нет среди окон или его остановил владелец — тревога «задача без хозяина» с готовой командой передачи. Задача doing
# без ветки, worktree и PR с её номером и без правки дольше STALE_DOING_HOURS — тревога.
OPEN = ("todo", "doing", "review", "waiting")
OWNER_FREE = ("вы", "владелец", "owner", "human")  # как tasks.OWNER_SLUGS: задача у владельца, окно не нужно
ROLE_OWNERS = ("zeus", "hq", "hestia", "argus", "chiron", "talos", "apollo", "prometheus", "clio", "iris", "momus")
DEAD_STATES = ("stopped",)  # claude agents после claude stop; done (закончила ход) и failed (её поднимет дежурный) — окно есть
STALE_DOING_HOURS = 6
SESSION_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")


def name_alias(name):
    """Имя и копии, которым Claude Code дал другое имя (как pantheon.name_alias): «имя (2)», «имя-два-слова»."""
    return re.compile(re.escape(name) + r"(?: \(\d+\)|-[a-z]+-[a-z]+)?")


def kept_owner(owner, directions):
    """owner — не сессия: владелец, роль или координатор направления (его будит дежурный по открытым задачам)."""
    return owner in OWNER_FREE or owner in ROLE_OWNERS or owner in directions or not SESSION_RE.fullmatch(owner)


def session_rows(agents):
    """[(sessionId, имя, состояние)] из снимка сессий; запись без sessionId или имени не годится."""
    out = []
    for a in agents or []:
        if isinstance(a, dict) and isinstance(a.get("sessionId"), str) and isinstance(a.get("name"), str) \
                and a["sessionId"] and a["name"].strip():
            out.append((a["sessionId"], a["name"].strip(), a.get("state")))
    return out


def owner_renames(tasks, agents, known, directions):
    """Переименование сессии → owner карточек за ней (по sessionId). known — {sessionId: прежнее имя} прошлого
    прохода. → (renames [(tid, старое, новое, sessionId)], новый known). Старое имя — направление, роль или владелец
    — не переносим (owner там — не сессия); старое имя носит другое живое окно — тоже: карточки могут быть его."""
    rows = session_rows(agents)
    now_names = {}
    for sid, name, state in rows:
        now_names.setdefault(sid, name)
    live_names = {name for _, name, state in rows if state not in DEAD_STATES}
    renames = []
    for sid, new in sorted(now_names.items()):
        old = known.get(sid)
        if not old or old == new or kept_owner(old, directions):
            continue
        if any(name_alias(old).fullmatch(n) for s, n in now_names.items() if s != sid and n in live_names):
            continue
        for tid, (_, h, _) in sorted(tasks.items()):
            if h.get("owner") == old and h.get("status") in OPEN:
                renames.append((tid, old, new, sid))
    out = dict(known)
    out.update(now_names)
    return renames, out


def orphan_owners(tasks, agents, directions, stopped=()):
    """Открытые задачи, чей хозяин-сессия не работает: его остановил владелец (stopped — имена с меткой
    STATE/stopped/<имя>, и координатор тоже: его уже никто не будит), он остановлен (claude stop) или его нет среди окон.
    → {tid: (owner, почему)}."""
    rows = session_rows(agents)
    out = {}
    for tid, (_, h, _) in sorted(tasks.items()):
        owner = h.get("owner")
        if h.get("status") not in OPEN or h.get("type") not in ("task", "story") or not isinstance(owner, str):
            continue
        if owner in stopped:
            out[tid] = (owner, "сессию остановили (pantheon stop)")
            continue
        if kept_owner(owner, directions):
            continue
        mine = [state for _, name, state in rows if name_alias(owner).fullmatch(name)]
        if not mine:
            out[tid] = (owner, "сессии нет среди окон")
        elif all(s in DEAD_STATES for s in mine):
            out[tid] = (owner, "сессия остановлена")
    return out


def handover(owner, direction, directions):
    """Кому передать задачу без хозяина: координатору её направления; остановили самого координатора — Зевсу."""
    return "zeus" if owner == direction or direction not in directions else direction


def branch_refs(root):
    """Имена веток репозитория — локальные и удалённые (refs/heads, refs/remotes, packed-refs) — без запуска git."""
    out = set()
    g = os.path.join(root, ".git")
    for top in ("heads", "remotes"):
        base = os.path.join(g, "refs", top)
        for d, _, files in os.walk(base):
            for f in files:
                out.add(os.path.relpath(os.path.join(d, f), base))
    for ln in (_read(os.path.join(g, "packed-refs"), 1 << 20) or "").splitlines():
        m = re.match(r"[0-9a-f]{7,64} refs/(?:heads|remotes)/(\S+)", ln)
        if m:
            out.add(m.group(1))
    return out


def stale_doing(tasks, domains, open_ids, t, ts_of, hours=STALE_DOING_HOURS):
    """Задачи doing направления с репозиторием, у которых нет ни ветки, ни worktree, ни открытого PR с их номером, а
    карточку не правили дольше hours часов. open_ids — номера из открытых PR (кэш autoclose); ts_of — tasks.ts_of.
    Аренда (claimed_until) ещё идёт — не трогаем. → {tid: часов без правки}."""
    rts = roots(domains)
    marks = {}
    for d, rs in rts.items():
        for root in rs:
            names = branch_refs(root) | {b for _, b in live_worktrees(root)}
            marks.setdefault(d, set()).update(i for b in names for i in branch_ids(b))
    out = {}
    for tid, (_, h, _) in sorted(tasks.items()):
        if h.get("type") != "task" or h.get("status") != "doing" or not rts.get(h.get("direction")):
            continue
        if tid in marks.get(h.get("direction"), ()) or tid in open_ids:
            continue
        upd = ts_of(h.get("updated"))
        claimed = ts_of(h.get("claimed_until"))
        if upd is None or t - upd < hours * 3600 or (claimed is not None and claimed > t):
            continue
        out[tid] = int((t - upd) // 3600)
    return out
