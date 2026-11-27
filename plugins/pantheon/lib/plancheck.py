"""Сверка плана с карточками пачек (metis-1235): `pantheon plan check <файл> [--direction <имя>]`.

План (например directions/metis-pantheon/plan-1.0-*.md) раскладывает задачи по пачкам разделами «## N. Пачка X …».
Доска видит только карточки: parent задачи и карточка type story. План переписали, а карточки нет — доска молча
показывает старые пачки (15.11: задачи плана 1.0 висели в пачках П*, карточек новых пачек не было). Проверка ищет
расхождения и сообщает их, карточек не правит.

Раздел-пачка — заголовок второго уровня со словом «Пачка» после номера раздела («## 8. Пачка А «…»»). Его карточка:
- ссылка `[[<id>]]` в заголовке или первой непустой строке раздела, или строка `story: <id>` / `пачка: <id>` в разделе;
- иначе — единственная открытая карточка story, в названии которой есть имя пачки в «ёлочках» раздела.
Задачи раздела — номера в строках таблиц (строки с «|»): id с префиксом и голые четыре цифры («0968», «**0985,
0989**»). Зачёркнутое (`~~…~~`, «→ пачка 0») и код (`…`) не в счёт; текст вне таблиц — тоже (там упоминания:
«0544 остаётся в пачке А»). Голый номер берёт задачу направления плана (папка directions/<имя>/ или --direction) с тем
же числом; такой задачи нет — номер не задача (PR, год, число).

Виды расхождений (каждый — строка вывода):
- раздел без карточки пачки, или ссылка не на карточку type story;
- пачка закрыта (done/dropped), а в её разделе открытые задачи;
- открытая задача раздела, у которой parent — не эта пачка (другая или никакой).
Код выхода: 0 — расхождений нет, 1 — есть, 2 — файл не прочитан или аргументы не те.

`--apply` нет намеренно: план — текст, и номер в строке таблицы бывает упоминанием («из пачки 2», «принять в шаге 0»).
Перенос parent по такому тексту переложил бы задачу молча и неверно; вывод даёт готовую команду
`pantheon task attach <id> <пачка>` на каждую задачу — решает тот, кто ведёт план.

Плановый проход доски (board_auto_sync → board_rows) сверяет планы направлений: поле `plans = ["…"]` записи
directions.toml (пути от ~/ai/pantheon или с ~), а без него — файлы directions/<имя>/plan-*.md, правленные за
PLAN_FRESH дней, где есть разделы-пачки. Итог — строка «План …: расхождений N» в board-auto.md (только номера и id,
SEC-13). Модуль-лист: без P, зовётся через _plugin_map_mod.
"""
import os
import re
import sys
import time

try:
    import tomllib
except ImportError:  # pragma: no cover — хуки на 3.11+, tomllib есть
    tomllib = None

ID_RE = re.compile(r"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")   # как autoclose.ID_RE
SECTION_RE = re.compile(r"^##\s+(?:([0-9]+[а-яёa-z]?(?:-[^\s.]+)?)\.\s+)?Пачка\s+(\S+)(.*)$", re.I)
H2_RE = re.compile(r"^##\s")
LINK_RE = re.compile(r"\[\[(" + ID_RE.pattern + r")(?:[|#][^\]]*)?\]\]")
FIELD_RE = re.compile(r"^\s*[-*]?\s*(?:story|пачка)\s*:\s*\[?\[?(" + ID_RE.pattern + r")", re.I)
NAME_RE = re.compile(r"«([^»]{2,80})»")
STRIKE_RE = re.compile(r"~~.*?~~")
CODE_RE = re.compile(r"`[^`]*`")
BARE_RE = re.compile(r"(?<![\w#./-])(\d{4})(?![\w./%-])")
CLOSED = ("done", "dropped")
PLAN_FRESH = 14 * 86400   # авто-поиск планов: файл правлен не раньше стольких секунд назад
MAX_BOARD_ITEMS = 3       # расхождений одного плана в строке доски
SAFE_NAME = re.compile(r"[\w.-]{1,80}")


def sections(text):
    """План → [{"num", "name", "story", "line", "refs": [(id или число, строка)]}] разделов-пачек по порядку."""
    out, cur = [], None
    for i, ln in enumerate((text or "").splitlines(), 1):
        if H2_RE.match(ln):
            m = SECTION_RE.match(ln)
            cur = None
            if m:
                q = NAME_RE.search(m.group(3) or "")
                link = LINK_RE.search(ln)
                cur = {"num": m.group(1) or "", "name": m.group(2) + (f" «{q.group(1)}»" if q else ""),
                       "quoted": q.group(1) if q else "", "story": link.group(1) if link else None, "line": i,
                       "refs": [], "first": True}
                out.append(cur)
            continue
        if cur is None:
            continue
        if cur["first"] and ln.strip():
            cur["first"] = False
            link = LINK_RE.search(ln)
            if link and not cur["story"]:
                cur["story"] = link.group(1)
        f = FIELD_RE.match(ln)
        if f and not cur["story"]:
            cur["story"] = f.group(1)
        if ln.lstrip().startswith("|"):
            clean = CODE_RE.sub(" ", STRIKE_RE.sub(" ", ln))
            if re.fullmatch(r"[\s|:-]*", clean):
                continue
            cur["refs"] += [(m.group(0), i) for m in ID_RE.finditer(clean)]
            cur["refs"] += [(int(m.group(1)), i) for m in BARE_RE.finditer(ID_RE.sub(" ", clean))]
    for s in out:
        s.pop("first", None)
    return out


def _resolve(ref, tasks, direction):
    """Номер из плана → id задачи (type task) или None. Голое число — задача направления с тем же числом, одна."""
    if isinstance(ref, str):
        return ref if tasks.get(ref, ("", {}))[1].get("type") == "task" else None
    hit = [tid for tid, (_, h, _) in tasks.items() if h.get("type") == "task"
           and (direction is None or h.get("direction") == direction)
           and (m := re.search(r"-(\d+)$", tid)) and int(m.group(1)) == ref]
    return hit[0] if len(hit) == 1 else None


def _story_by_name(sec, tasks):
    if not sec["quoted"]:
        return None
    q = sec["quoted"].casefold()
    hit = [tid for tid, (_, h, _) in tasks.items() if h.get("type") == "story" and h.get("status") not in CLOSED
           and q in str(h.get("title") or "").casefold()]
    return hit[0] if len(hit) == 1 else None


def check(text, tasks, direction=None):
    """→ [(вид, номер раздела, пачка или None, задача или None, parent или None, строка плана)] расхождений.
    Виды: "no-story", "not-story", "closed", "parent"."""
    out = []
    for sec in sections(text):
        sid = sec["story"] or _story_by_name(sec, tasks)
        num = sec["num"] or sec["name"].split()[0]
        if not sid:
            out.append(("no-story", num, None, None, None, sec["line"]))
            continue
        sh = tasks.get(sid, ("", {}, ""))[1]
        if sh.get("type") != "story":
            out.append(("not-story", num, sid, None, None, sec["line"]))
            continue
        seen, open_ids = set(), []
        for ref, line in sec["refs"]:
            tid = _resolve(ref, tasks, direction)
            if not tid or tid in seen:
                continue
            seen.add(tid)
            h = tasks[tid][1]
            if h.get("status") in CLOSED:
                continue
            open_ids.append(tid)
            if h.get("parent") != sid:
                out.append(("parent", num, sid, tid, h.get("parent") or None, line))
        if sh.get("status") in CLOSED and open_ids:
            out.append(("closed", num, sid, ",".join(open_ids), None, sec["line"]))
    return out


def describe(p, board=False):
    """Строка расхождения: для CLI и (board) для доски — там только номера, id и постоянные слова (SEC-13)."""
    kind, num, sid, tid, par, _ = p
    if kind == "no-story":
        return f"раздел {num}: нет карточки пачки" + ("" if board else
                                                       " (story) — поставь [[<id>]] в заголовок или заведи пачку")
    if kind == "not-story":
        return f"раздел {num}: {sid} не карточка пачки" + ("" if board else " (type story)")
    if kind == "closed":
        return f"раздел {num}: пачка {sid} закрыта, а открыты {tid.replace(',', ', ')}"
    return f"раздел {num}: {tid} в пачке {par or 'никакой'}, а план кладёт её в {sid}"


def direction_of(path, pantheon):
    """directions/<имя>/… внутри pantheon → имя направления, иначе None."""
    try:
        rel = os.path.relpath(os.path.realpath(path), os.path.realpath(pantheon))
    except ValueError:
        return None
    parts = rel.split(os.sep)
    return parts[1] if len(parts) >= 3 and parts[0] == "directions" else None


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main(rest, pantheon, T, t=None):
    """`pantheon plan check <файл> [--direction <имя>]` → код 0/1/2 (см. шапку)."""
    use = "pantheon plan check <файл плана> [--direction <имя>]"
    args = list(rest)
    if args[:1] != ["check"] or len(args) not in (2, 4) or (len(args) == 4 and args[2] != "--direction"):
        print(f"pantheon plan: {use}", file=sys.stderr)
        return 2
    path = os.path.expanduser(args[1])
    direction = args[3] if len(args) == 4 else direction_of(path, pantheon)
    try:
        text = _read(path)
    except (OSError, UnicodeDecodeError) as e:
        print(f"pantheon plan check: {path} не прочитан ({type(e).__name__}: {e}) — ничего не сверено", file=sys.stderr)
        return 2
    secs = sections(text)
    if not secs:
        print(f"pantheon plan check: в {path} нет разделов «## N. Пачка …» — сверять нечего")
        return 0
    tasks = T.load_tasks(pantheon, T.WORK_TYPES)
    found = check(text, tasks, direction)
    for p in found:
        line = f"{os.path.basename(path)}:{p[5]}: {describe(p)}"
        if p[0] == "parent":
            line += f" — pantheon task attach {p[3]} {p[2]}"
        print(line)
    if found:
        print(f"план {os.path.basename(path)}: разделов-пачек {len(secs)}, расхождений с карточками {len(found)} — "
              "карточки не тронуты, поправь parent (pantheon task attach) или план")
        return 1
    print(f"план {os.path.basename(path)}: разделов-пачек {len(secs)}, расхождений с карточками нет")
    return 0


def plans(pantheon, t, unread=None):
    """Планы для прохода доски → [(путь, направление)]: поле plans направления в directions.toml, без него — свежие
    directions/<имя>/plan-*.md с разделами-пачками. unread — множество: сюда попадает направление, у которого план
    не прочитался (metis-1394), чтобы вызывающий не счёл пачки из него «вне плана»."""
    try:
        with open(os.path.join(pantheon, "directions.toml"), "rb") as fh:
            reg = tomllib.load(fh) if tomllib else {}
    except (OSError, ValueError):
        reg = {}
    out = []
    for d in reg.get("direction") or []:
        name = d.get("name") if isinstance(d, dict) else None
        if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
            continue
        listed = d.get("plans")
        if isinstance(listed, list):
            for x in listed:  # направление плана — папка directions/<имя>/ файла, иначе запись реестра
                if isinstance(x, str):
                    p = os.path.expanduser(x)
                    p = p if os.path.isabs(p) else os.path.join(pantheon, p)
                    out.append((p, direction_of(p, pantheon) or name))
            continue
        folder = os.path.join(pantheon, "directions", name)
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for fn in names:
            p = os.path.join(folder, fn)
            if not (fn.startswith("plan-") and fn.endswith(".md")):
                continue
            try:
                if t - os.stat(p).st_mtime > PLAN_FRESH or not sections(_read(p)):
                    continue
            except (OSError, UnicodeDecodeError):
                if unread is not None:
                    unread.add(name)
                continue
            out.append((p, name))
    return out


def board_rows(pantheon, tasks, t=None):
    """Строки для board-auto.md (data["plan_drift"]) → [(имя файла без .md, число расхождений, [коротко])].
    Сбой чтения плана — строка с числом -1: доска скажет «не прочитан», сводка не падает."""
    t = time.time() if t is None else t
    out = []
    for path, name in plans(pantheon, t):
        base = os.path.basename(path)[:-3] if path.endswith(".md") else os.path.basename(path)
        if not SAFE_NAME.fullmatch(base):
            continue
        try:
            found = check(_read(path), tasks, name)
        except (OSError, UnicodeDecodeError):
            out.append((base, -1, []))
            continue
        if found:
            out.append((base, len(found), [describe(p, board=True) for p in found[:MAX_BOARD_ITEMS]]))
    return out


def uncovered_packs(pantheon, tasks, t, T):
    """Открытые пачки (story, не цели) направлений, у которых есть план, а раздела-пачки с ними нет → [id] (metis-1378).
    Раздел покрывает пачку, если его карточка найдена (ссылка, поле story/пачка или имя в «ёлочках»). Направление без
    плана не в счёт: сверять не с чем. План не прочитан — направление пропущено, а не «всё вне плана»."""
    covered, planned, unread = set(), set(), set()
    for path, name in plans(pantheon, t, unread):
        try:
            secs = sections(_read(path))
        except (OSError, UnicodeDecodeError):
            unread.add(name)
            continue
        planned.add(name)
        for sec in secs:
            sid = sec["story"] or _story_by_name(sec, tasks)
            if sid:
                covered.add(sid)
    planned -= unread  # хоть один план направления не прочитан — его пачки могли быть там (metis-1394)
    return sorted(sid for sid, (_, h, _) in tasks.items()
                  if h.get("type") == "story" and h.get("status") not in CLOSED and h.get("direction") in planned
                  and sid not in covered and not T.is_goal(sid, tasks))
