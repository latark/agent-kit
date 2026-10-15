"""Задачи Пантеона: схема свойств v1, проверка, команда `pantheon task` и доска владельца `pantheon board`.

Источник правды — файл задачи: markdown с плоской YAML-шапкой (ключи и коды статусов — английские).
Где лежат задачи: ~/ai/pantheon/directions/<направление>/tasks/*.md и ~/ai/pantheon/inbox/tasks/*.md
(входящие от владельца — разбирает Зевс). Агенты пишут их только через `pantheon task`.

Доска владельца — ~/ai/pantheon-view/Доска/: по карточке на живую задачу, поля по-русски, колонки — русские
статусы. Карточки рисует тик, двигает владелец (Obsidian Bases). Ход владельца тик находит трёхсторонним
сравнением: статус в карточке, статус, который тик записал в прошлый раз (его состояние — в
~/.local/state/pantheon/board.json, не в карточке), и статус в источнике. Ход применяется к источнику и
пишется в журнал владельца ~/.local/state/pantheon/owner-log/board.jsonl. Роли в папку доски писать не могут
(guard: вся ~/ai/pantheon-view; песочница: её нет в allowWrite), поэтому ход владельца им не подделать.
"""
import contextlib
import fcntl
import hashlib
import json
import os
import re
from datetime import datetime

SCHEMA_VERSION = 1
TYPES = ("task", "stage", "project")
STATUSES = ("inbox", "todo", "doing", "waiting", "review", "done", "dropped")
LABELS = {"inbox": "Входящие", "todo": "Очередь", "doing": "В работе", "waiting": "Ждёт", "review": "На проверке",
          "done": "Готово", "dropped": "Отменено"}
HUMAN_WAIT = "Нужен ответ"
OLD_HUMAN_WAIT = "Ждёт вас"  # прежнее имя колонки (до 0.9.28): в старых карточках и состоянии читается как HUMAN_WAIT
COLUMNS = ["Входящие", HUMAN_WAIT, "Очередь", "В работе", "Ждёт", "На проверке", "Готово", "Отменено"]
# куда владелец может перенести карточку сам; «Ждёт» и «На проверке» ставят агенты
OWNER_TARGETS = {"Входящие": ("inbox", None), "Очередь": ("todo", None), "В работе": ("doing", None),
                 HUMAN_WAIT: ("waiting", "human"), "Готово": ("done", None), "Отменено": ("dropped", None)}
ID_RE = re.compile(r"[a-z][a-z0-9]{1,11}-\d{3,}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?")
# поле → (тип, обязательно ли для task); типы: str, int, date, datetime, list
FIELDS = {
    "type": ("str", True), "id": ("str", True), "title": ("str", True), "status": ("str", True),
    "project": ("str", True), "direction": ("str", True), "owner": ("str", False), "created": ("date", True),
    "updated": ("datetime", True), "schema_version": ("int", True), "tags": ("list", False),
    "stage": ("str", False), "priority": ("int", False), "due": ("datetime", False), "next": ("str", False),
    "waiting_on": ("str", False), "depends_on": ("list", False), "claimed_by": ("str", False),
    "claimed_until": ("datetime", False), "parent": ("str", False), "result": ("str", False),
    "question": ("str", False), "options": ("list", False), "answer": ("str", False),
    # когда задан нынешний вопрос и когда задача закрыта — ставит CLI, на карточке «Вопрос задан» и «Закрыта»
    "question_at": ("datetime", False), "closed": ("date", False),
    # вопрос владельцу по шаблону (исследование 15.10): question — одна фраза «что решить», why — почему сейчас,
    # options — полные строки «А — название (совет). Что изменится. Цена: …», recommend — совет с причиной
    "why": ("str", False), "recommend": ("str", False), "if_no_answer": ("str", False),
    "risky": ("bool", False), "requested": ("str", False),
    # этап и проект
    "goal": ("str", False), "start": ("date", False), "exit_criteria": ("list", False), "repo_path": ("str", False),
    "health": ("str", False), "review_on": ("date", False),
}
# срок due — дата (срок — конец дня) или дата со временем «ГГГГ-ММ-ДДTЧЧ:ММ» (умные уведомления, metis-0023)
ORDER = list(FIELDS)
PRIORITY = {0: "срочно", 1: "высокий", 2: "обычный", 3: "низкий"}


# --- шапка ---------------------------------------------------------------------

class HeaderError(ValueError):
    pass


def _scalar(v):
    v = v.strip()
    if v in ("", "~", "null", "Null", "NULL"):
        return None
    if len(v) >= 2 and v[0] == v[-1] == '"':
        try:
            return json.loads(v)
        except ValueError as e:
            raise HeaderError(f"строка в кавычках: {v[:40]}") from e
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    if v[0] in "{&*!|>%@`":
        raise HeaderError(f"неподдерживаемое значение: {v[:40]}")
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if v in ("true", "false"):
        return v == "true"
    if v[0] == "[":
        if not v.endswith("]"):
            raise HeaderError(f"незакрытый список: {v[:40]}")
        body = v[1:-1].strip()
        if not body:
            return []
        out, cur, q = [], "", None
        for ch in body:
            if q:
                cur += ch
                if ch == q:
                    q = None
            elif ch in "\"'":
                q = ch
                cur += ch
            elif ch == ",":
                out.append(_scalar(cur))
                cur = ""
            else:
                cur += ch
        if q:
            raise HeaderError(f"незакрытая кавычка в списке: {v[:40]}")
        out.append(_scalar(cur))
        return out
    if " #" in v:
        v = v.split(" #", 1)[0].rstrip()
    return v


def split(text):
    """→ (шапка-словарь или None, тело). HeaderError — шапка битая."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 3)
    if end < 0 or (len(text) > end + 4 and text[end + 4] not in "\n"):
        raise HeaderError("шапка не закрыта строкой ---")
    raw, body = text[4:end], text[end + 5:] if len(text) > end + 4 else ""
    head, key = {}, None
    for n, line in enumerate(raw.split("\n"), 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^  ?- (.*)$|^-\s(.*)$", line)
        if m and key and isinstance(head.get(key), list):
            head[key].append(_scalar(m.group(1) if m.group(1) is not None else m.group(2)))
            continue
        if line[0] in " \t":
            raise HeaderError(f"строка {n}: вложенные значения не поддерживаются")
        m = re.match(r"^([A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё ]*?):(?:\s(.*))?$", line)
        if not m:
            raise HeaderError(f"строка {n}: не «ключ: значение»")
        key = m.group(1)
        if key in head:
            raise HeaderError(f"ключ {key} повторяется")
        val = m.group(2)
        head[key] = [] if val is None or val.strip() == "" else _scalar(val)
        if val is not None and val.strip() == "":
            head[key] = []  # дальше могут идти элементы списка; пустой — станет None ниже
    for k, v in list(head.items()):
        if v == [] and FIELDS.get(k, ("list",))[0] != "list":
            head[k] = None
    return head, body


def _fmt(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    s = str(v)
    if (DATE_RE.fullmatch(s) or DATETIME_RE.fullmatch(s)) or (re.fullmatch(r"[\wА-Яа-яЁё][\wА-Яа-яЁё .,()/-]*", s)
                                                            and s.strip() == s and s.lower() not in (
                                                                "yes", "no", "on", "off", "true", "false", "null")
                                                            and not re.fullmatch(r"-?\d+(\.\d+)?", s)):
        return s
    return json.dumps(s, ensure_ascii=False)


def join(head, body, order=None):
    keys = [k for k in (order or ORDER) if k in head] + [k for k in head if k not in (order or ORDER)]
    lines = [f"{k}: {_fmt(head[k])}" for k in keys if head[k] is not None]
    return "---\n" + "\n".join(lines) + "\n---\n" + body


# --- файлы внутри ~/ai/pantheon: без перехода по ссылкам ------------------------
# Тик работает с правами владельца, а папки направлений пишут роли. Проверка «это не ссылка» и сама запись
# раздельно оставляют окно для подмены, поэтому внутри корня папки открываются цепочкой от корня — каждая
# ступень с O_NOFOLLOW, — а файлы читаются, пишутся, переносятся и удаляются относительно уже открытой папки.

_ROOT = None


def set_root(pantheon):
    global _ROOT
    _ROOT = os.path.realpath(pantheon)


def _parts(path):
    if not _ROOT:
        return None
    a = os.path.abspath(path)
    if a == _ROOT or not a.startswith(_ROOT + os.sep):
        return None
    parts = a[len(_ROOT) + 1:].split(os.sep)
    if any(x in ("", ".", "..") for x in parts):  # noqa: путь собран кодом, это страховка
        raise ValueError(f"путь не по образцу: {path}")
    return parts


def _open_chain(parts, create=False):
    fd = os.open(_ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for x in parts:
            if create:
                try:
                    os.mkdir(x, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            nfd = os.open(x, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextlib.contextmanager
def _in_dir(path, create=False):
    """→ (fd папки или None, имя файла). None — путь вне корня: обычный ввод-вывод."""
    parts = _parts(path)
    if parts is None:
        yield None, path
        return
    fd = _open_chain(parts[:-1], create)
    try:
        yield fd, parts[-1]
    finally:
        os.close(fd)


def read_text(path):
    with _in_dir(path) as (fd, name):
        if fd is None:
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(f, encoding="utf-8") as fh:
            return fh.read()


def write_text(path, text):
    with _in_dir(path, create=True) as (fd, name):
        if fd is None:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
            return
        # временный файл — только новый и со случайным именем: заранее подложенный (в том числе жёсткой ссылкой
        # на чужой файл) не перезапишется
        import secrets
        tmp = f".{name}.{secrets.token_hex(8)}.tmp"
        f = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
        with os.fdopen(f, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)


def create_excl(path):
    with _in_dir(path, create=True) as (fd, name):
        if fd is None:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW))
        else:
            os.close(os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o644, dir_fd=fd))


def remove(path):
    with _in_dir(path) as (fd, name):
        os.unlink(name if fd is not None else path, dir_fd=fd)


def append_text(path, text):
    import stat as _st
    with _in_dir(path) as (fd, name):
        f = os.open(name if fd is not None else path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=fd)
        info = os.fstat(f)
        if not _st.S_ISREG(info.st_mode) or info.st_nlink != 1:  # жёсткая ссылка на чужой файл — не дописываем
            os.close(f)
            raise ValueError(f"{path}: не обычный файл или у него несколько ссылок — не дописываю")
        with os.fdopen(f, "a", encoding="utf-8") as fh:
            fh.write(text)


def move(src, dst):
    with _in_dir(src) as (sfd, sname), _in_dir(dst, create=True) as (dfd, dname):
        if sfd is None or dfd is None:
            raise ValueError("перенос — только внутри корня Пантеона")
        try:
            os.stat(dname, dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            os.rename(sname, dname, src_dir_fd=sfd, dst_dir_fd=dfd)
            return
        raise FileExistsError(dst)


def list_dir(d):
    """Имена в папке внутри корня (папка открыта цепочкой, без ссылок); [] — нет папки или по пути ссылка."""
    parts = _parts(d)
    try:
        if parts is None:
            return sorted(os.listdir(d))
        fd = _open_chain(parts)
        try:
            return sorted(os.listdir(fd))
        finally:
            os.close(fd)
    except OSError:
        return []


def is_file(d, name):
    """Обычный файл (не ссылка, не папка) — внутри корня проверяется относительно открытой папки."""
    try:
        with _in_dir(os.path.join(d, name)) as (fd, n):
            st = os.stat(n if fd is not None else os.path.join(d, name), dir_fd=fd, follow_symlinks=False)
        import stat as _st
        return _st.S_ISREG(st.st_mode)
    except OSError:
        return False


def read(path):
    return split(read_text(path))


def write(path, head, body, order=None):
    write_text(path, join(head, body, order))


def digest(path):
    try:
        return hashlib.sha256(read_text(path).encode("utf-8")).hexdigest()[:16]
    except (OSError, UnicodeDecodeError, ValueError):
        return ""


# --- проверка схемы -------------------------------------------------------------

def check_head(head):
    """→ (ошибки, предупреждения). Ошибка — файл выпадет из вида или собьёт агентов."""
    errs, warns = [], []
    t = head.get("type")
    if t not in TYPES:
        errs.append(f"type «{t}» — не из {', '.join(TYPES)}")
    for k, v in head.items():
        if k not in FIELDS:
            warns.append(f"неизвестное поле {k}")
            continue
        kind = FIELDS[k][0]
        if v is None:
            continue
        ok = {"str": isinstance(v, str), "int": isinstance(v, int) and not isinstance(v, bool), "bool": isinstance(v, bool),
              "list": isinstance(v, list), "date": isinstance(v, str) and bool(DATE_RE.fullmatch(v)),
              "datetime": isinstance(v, str) and bool(DATETIME_RE.fullmatch(v) or DATE_RE.fullmatch(v))}[kind]
        if not ok:
            errs.append(f"{k}: ожидается {kind}, а не «{v}»")
    for k, (kind, req) in FIELDS.items():
        if req and head.get(k) in (None, "") and not (k == "project" and t == "project"):
            errs.append(f"нет обязательного поля {k}")
    st = head.get("status")
    if st is not None and st not in STATUSES:
        errs.append(f"status «{st}» — не из {', '.join(STATUSES)}")
    if head.get("id") and not ID_RE.fullmatch(str(head["id"])):
        errs.append(f"id «{head['id']}» — нужен вид «pan-0001»")
    if t == "task":
        if not head.get("owner"):  # не ошибка: старые задачи без owner выпали бы с доски
            warns.append("нет owner (кому) — на доске будет координатор направления")
        if st in ("doing", "waiting") and not head.get("next"):
            warns.append(f"при {st} нужно поле next — следующий шаг")
        if st == "waiting" and not head.get("waiting_on"):
            errs.append("при waiting нужно поле waiting_on (human, id задачи или кто/что)")
        p = head.get("priority")
        if isinstance(p, int) and p not in PRIORITY:
            errs.append("priority — 0 (срочно) … 3 (низкий)")
        if head.get("options") and not head.get("question"):
            warns.append("options без question")
        q = head.get("question") or ""
        if len(q.split()) > 25:
            warns.append("question длиннее 25 слов — одна фраза «что решить», объяснение — в why")
        if q and head.get("status") == "waiting" and not head.get("why"):
            warns.append("вопрос без why — одна-две фразы «почему сейчас»")
        if len(head.get("options") or []) > 1 and not head.get("recommend"):
            warns.append("варианты без recommend — совет и причина")
        short = [o for o in head.get("options") or [] if len(str(o).split()) < 4]
        if short:
            warns.append(f"варианты без объяснения ({', '.join(map(str, short))}) — «название. Что изменится. Цена»")
    if head.get("schema_version") not in (None, SCHEMA_VERSION):
        warns.append(f"schema_version {head.get('schema_version')} — текущая {SCHEMA_VERSION}")
    return errs, warns


def check_file(path):
    try:
        head, _ = read(path)
    except HeaderError as e:
        return "broken", [str(e)], []
    except (OSError, UnicodeDecodeError) as e:
        return "broken", [f"не прочитать: {e}"], []
    if head is None:
        return "noheader", [], []
    errs, warns = check_head(head)
    return ("error" if errs else "ok"), errs, warns


# --- где лежат задачи -----------------------------------------------------------

def task_dirs(pantheon):
    d = os.path.join(pantheon, "directions")
    return [os.path.join(pantheon, "inbox", "tasks")] + [os.path.join(d, x, "tasks") for x in list_dir(d)
                                                          if DIRECTION_RE.fullmatch(x)]


def task_files(pantheon):
    for d in task_dirs(pantheon):
        for f in list_dir(d):  # папка, открытая без ссылок; файлы — только обычные
            if f.endswith(".md") and not f.startswith(".") and is_file(d, f):
                yield os.path.join(d, f)


def load_tasks(pantheon):
    """id → (путь, шапка, тело) — только исправные задачи."""
    out = {}
    for p in task_files(pantheon):
        try:
            head, body = read(p)
        except (HeaderError, OSError, UnicodeDecodeError):
            continue
        if head and head.get("type") == "task" and head.get("id") and not check_head(head)[0]:
            out[head["id"]] = (p, head, body)
    return out


# --- команда pantheon task ---------------------------------------------------------

def now_iso(t):
    return datetime.fromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%S")


def ts_of(v):
    """Дата или дата-время из шапки → метка времени (дата — её начало), иначе None."""
    if not isinstance(v, str):
        return None
    try:
        if DATETIME_RE.fullmatch(v):
            return datetime.strptime(v[:16], "%Y-%m-%dT%H:%M").timestamp() + (int(v[17:19]) if len(v) > 16 else 0)
        if DATE_RE.fullmatch(v):
            return datetime.strptime(v, "%Y-%m-%d").timestamp()
    except ValueError:
        return None
    return None


def due_ts(v):
    """Срок → метка времени: дата со временем — это время, дата без времени — конец дня."""
    t = ts_of(v)
    if t is None:
        return None
    return t if "T" in v else datetime.fromtimestamp(t + 86400 + 3600).replace(hour=0, minute=0, second=0).timestamp() - 1


def due_text(v):
    """Срок для человека: «15.10» или «15.10 07:00»."""
    if not isinstance(v, str) or len(v) < 10:
        return ""
    return f"{v[8:10]}.{v[5:7]}" + (f" {v[11:16]}" if "T" in v and len(v) >= 16 else "")


def overdue(h, t):
    d = due_ts(h.get("due"))
    return d is not None and t > d and h.get("status") not in ("done", "dropped")


def new_id(pantheon, direction, prefix=None):
    prefix = prefix or re.sub(r"[^a-z0-9]", "", direction.split("-")[0])[:8] or "task"
    nums = [int(i.split("-")[1]) for i in load_ids(pantheon) if i.startswith(prefix + "-")]
    return f"{prefix}-{max(nums, default=0) + 1:04d}"


def load_ids(pantheon):
    ids = []
    for p in task_files(pantheon):
        try:
            head, _ = read(p)
        except (HeaderError, OSError, UnicodeDecodeError):
            continue
        if head and head.get("id"):
            ids.append(str(head["id"]))
    return ids


DIRECTION_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")


def _file_for(pantheon, direction, tid):
    if not DIRECTION_RE.fullmatch(str(direction)) or not ID_RE.fullmatch(str(tid)):
        raise ValueError(f"направление или id не по образцу: {direction!r}, {tid!r}")
    base = os.path.join(pantheon, "inbox", "tasks") if direction == "inbox" else \
        os.path.join(pantheon, "directions", direction, "tasks")
    try:
        with _in_dir(os.path.join(base, ".probe"), create=True):
            pass  # папка открывается цепочкой без ссылок (и создаётся, если её нет)
    except OSError as e:
        raise ValueError(f"папка задач {base} — ссылка или не на своём месте ({e.strerror})") from e
    return os.path.join(base, tid + ".md")


def task_new(pantheon, t, direction, title, project=None, actor="агент", text=None, **fields):
    if not DIRECTION_RE.fullmatch(str(direction)):
        raise ValueError(f"направление не по образцу: {direction!r}")
    if direction != "inbox" and not os.path.isdir(os.path.join(pantheon, "directions", direction)):
        raise ValueError(f"нет направления {direction}")
    tid = new_id(pantheon, direction)
    path = _file_for(pantheon, direction, tid)
    while True:
        try:
            create_excl(path)
            break
        except FileExistsError:
            pre, num = tid.rsplit("-", 1)
            tid = f"{pre}-{int(num) + 1:04d}"
            path = _file_for(pantheon, direction, tid)
    head = {"type": "task", "id": tid, "title": title.strip(), "status": fields.pop("status", None) or "todo",
            "project": project or direction, "direction": direction, "created": now_iso(t)[:10],
            "updated": now_iso(t), "schema_version": SCHEMA_VERSION}
    head.update({k: v for k, v in fields.items() if v is not None})
    if not head.get("owner"):  # «Кому» обязательно: без --owner — координатор направления (входящие — Зевс)
        head["owner"] = "zeus" if direction == "inbox" else direction
    if head.get("question"):
        head["question_at"] = now_iso(t)
    errs, _ = check_head(head)
    if errs:
        remove(path)
        raise ValueError("; ".join(errs))
    desc = "\n".join(("\\" + ln) if ln.startswith("## ") else ln for ln in (text or "").strip().split("\n")).strip()
    write(path, head, f"\n# {title.strip()}\n\n" + (desc + "\n\n" if desc else "")
          + f"## Журнал\n\n- {now_iso(t)[:16].replace('T', ' ')} — {actor}: создана\n")
    return tid, path


def append_log(body, line):
    if "## Журнал" not in body:
        body = body.rstrip("\n") + "\n\n## Журнал\n"
    return body.rstrip("\n") + f"\n- {line}\n"


@contextlib.contextmanager
def dir_lock(d, wait=10.0):
    """Блокировка папки задач (файл .lock в ней же: роли в песочнице пишут только в папку своего направления).
    Без перехода по ссылке; ждём не дольше wait — роль, держащая блокировку, не подвесит тик."""
    import time as _time
    wait = float(os.environ.get("PANTHEON_LOCK_WAIT") or wait)
    with _in_dir(os.path.join(d, ".lock"), create=True) as (dfd, name):
        if dfd is None:
            os.makedirs(d, exist_ok=True)
        fd = os.open(name if dfd is not None else os.path.join(d, ".lock"),
                     os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o644, dir_fd=dfd)
    try:
        end = _time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if _time.monotonic() > end:
                    raise ValueError("папка задач занята другой правкой — повторите позже")
                _time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def task_set(pantheon, t, tid, changes, note=None, actor="агент", precheck=None):
    tasks = load_tasks(pantheon)
    if tid not in tasks:
        raise ValueError(f"нет задачи {tid} (или её шапка не проходит проверку)")
    with dir_lock(os.path.dirname(tasks[tid][0])):
        return _task_set_locked(tasks[tid][0], t, tid, changes, note, actor, precheck)


def task_note(pantheon, t, tid, note):
    """Заметка владельца с доски: текст — в «Заметки владельца» задачи, в журнал — строка, что она пришла."""
    tasks = load_tasks(pantheon)
    if tid not in tasks:
        raise ValueError(f"нет задачи {tid}")
    path = tasks[tid][0]
    with dir_lock(os.path.dirname(path)):
        head, body = read(path)
        if not head or head.get("id") != tid:
            raise ValueError(f"задача {tid} изменилась — повторите")
        stamp = now_iso(t)[:16].replace("T", " ")
        body = add_owner_note(body, stamp, note)
        body = append_log(body, f"{stamp} — владелец: новая заметка — в разделе «Заметки владельца»")
        head["updated"] = now_iso(t)
        write(path, head, body)
    return path


def task_claim(pantheon, t, tid, by, hours=1.0):
    """Аренда задачи: проверка «не взята ли» и запись — под одной блокировкой."""
    def precheck(head):
        cu = head.get("claimed_until") or ""
        if head.get("claimed_by") not in (None, by) and cu > now_iso(t):
            raise ValueError(f"{tid} уже взята: {head['claimed_by']} до {cu}")
    until = now_iso(t + 3600 * float(hours))
    return task_set(pantheon, t, tid, {"claimed_by": by, "claimed_until": until, "status": "doing"},
                    note=f"взял {by} до {until[11:16]}", precheck=precheck)


def _task_set_locked(path, t, tid, changes, note, actor, precheck):
    head, body = read(path)  # заново, уже под блокировкой: чужая правка между чтением и записью не потеряется
    if not head or head.get("id") != tid:
        raise ValueError(f"задача {tid} изменилась — повторите")
    if precheck:
        precheck(head)
    if changes.get("status") == "doing" and head.get("status") not in ("todo", "doing") and "claimed_by" in changes:
        changes = dict(changes, status=head.get("status"))
    if "owner" in changes and not changes["owner"]:
        raise ValueError("owner не очищается: у задачи всегда есть «Кому» — поставьте другого исполнителя")
    old_q, was_closed = head.get("question"), head.get("status") in ("done", "dropped")
    for k, v in changes.items():
        if k not in FIELDS or k in ("type", "id", "created", "schema_version"):
            raise ValueError(f"поле {k} так не меняется")
        head[k] = v
    if head.get("status") != "waiting":
        head["waiting_on"] = None
    if head.get("status") in ("done", "dropped"):
        head["question"], head["options"], head["requested"] = None, None, None
        if not was_closed:
            head["closed"] = now_iso(t)[:10]
    elif was_closed:
        head["closed"] = None
    if not head.get("question"):
        head["question_at"] = None
    elif head.get("question") != old_q:
        head["question_at"] = now_iso(t)
    head["updated"] = now_iso(t)
    errs, _ = check_head(head)
    if errs:
        raise ValueError("; ".join(errs))
    if note:
        body = append_log(body, f"{now_iso(t)[:16].replace('T', ' ')} — {actor}: {' '.join(str(note).split())}")
    write(path, head, body)
    return path, head


def ready(pantheon, t, direction=None, owner=None):
    """Что можно брать: todo без чужой живой аренды и без невыполненных зависимостей."""
    tasks = load_tasks(pantheon)
    done = {i for i, (_, h, _) in tasks.items() if h.get("status") in ("done", "dropped")}
    out = []
    for tid, (p, h, _) in tasks.items():
        if h.get("status") != "todo":
            continue
        if direction and h.get("direction") != direction or owner and h.get("owner") not in (owner, None):
            continue
        cu = h.get("claimed_until")
        if h.get("claimed_by") and cu and cu > now_iso(t):
            continue
        if any(d not in done for d in h.get("depends_on") or []):
            continue
        out.append((h.get("priority", 2), h.get("due") or "9999", tid, h))
    return [x[2:] for x in sorted(out, key=lambda x: (x[0], x[1], x[2]))]


# --- доска владельца ------------------------------------------------------------

CARD_ORDER = ["Статус", "Проект", "Внимание", "Приоритет", "Срок", "Кому", "Дальше", "Ждёт", "Создана", "Вопрос задан",
              "Закрыта", "Тип", "id", "tags"]
# типы свойств карточек для Obsidian (.obsidian/types.json хранилища): тик ставит свои ключи, чужие не трогает
PROP_TYPES = {"Внимание": "multitext", "Приоритет": "number", "Срок": "date", "Создана": "date",
              "Вопрос задан": "datetime", "Закрыта": "date", "Кому": "text", "tags": "tags"}
NODES_DIR = "Узлы"  # заметки-узлы ролей для графа — внутри Доска: копия view-sync.sh стирает всё вне Доска и .obsidian
NOTE_KEY = "Заметка агенту"  # прежнее поле заметки: в карточку больше не рисуется, но со старых карточек ещё читается
NOTES_HEAD = "## ✍️ Ваши заметки"
NOTES_HINT = ("<small>Пишите ниже своими словами: мысли, задачи, правки. Через минуту после того, как закончите, тик "
              "передаст их исполнителю — он прочитает до начала работы и ответит в журнале.</small>")
OWNER_NOTES = "## Заметки владельца"  # раздел файла задачи: сюда тик переносит текст из карточки
QUIET = 30  # с: новую карточку берём, когда у неё есть название и её столько не меняли (ответ и заметка — сразу)
UNTITLED = ("Без названия", "Untitled")
PROJECT_MARK = {"Пантеон": "⬛", "BrokerAssistant": "🟦", "alexbroker": "🟧", "MorphStream": "🟪", "expert-corpus": "🟫",
                "legal-watch": "🟫", "content-machine": "🟩", "second-brain": "🟨", "входящие": "📥"}
STATUS_MARK = {"Входящие": "📥", HUMAN_WAIT: "🔴", "Очередь": "⚪", "В работе": "🟡", "Ждёт": "⏸",
               "На проверке": "🔵", "Готово": "🟢", "Отменено": "⚫"}
PRIORITY_MARK = {0: "🔥🔥 срочно", 1: "🔥 высокий", 2: "обычный", 3: "▫️ низкий"}
CALLOUT = {HUMAN_WAIT: "danger", "В работе": "warning", "Готово": "success", "На проверке": "info", "Ждёт": "quote",
           "Отменено": "quote", "Входящие": "note", "Очередь": "note"}


def norm_label(x):
    """Колонка из карточки или состояния: прежнее «Ждёт вас» — это нынешнее «Нужен ответ» (переход без ложных ходов)."""
    return HUMAN_WAIT if x == OLD_HUMAN_WAIT else x


def label_of(head):
    st = head.get("status")
    if st == "waiting" and head.get("waiting_on") == "human":
        return HUMAN_WAIT
    return LABELS.get(st, st)


CONTROL_RE = re.compile(r"[\s\x00-\x1f\x7f\x85  ]+")  # переводы строк, NUL и прочие управляющие, пробелы


def one_line(s):
    """Одна строка без управляющих знаков: перевод строки в имени файла или ссылке рвал строку узла (там появлялся
    заголовок «===»), NUL в пути валил весь проход доски (ревью argus 15.10)."""
    return CONTROL_RE.sub(" ", str(s or "")).strip()


def card_name(head, with_id=None):
    """Имя файла карточки: у задачи «<id> <заголовок>», у заявки направлению и узла — без id."""
    with_id = bool(head.get("type") == "task" and head.get("id")) if with_id is None else with_id
    title = one_line(head.get("title") or head.get("id"))
    if with_id and title != one_line(head.get("id")):
        title = f"{one_line(head['id'])} {title}"
    name = title.replace(":", "꞉").replace("/", "⁄")  # похожие знаки, допустимые в имени
    name = re.sub(r'[\\*?"<>|#^\[\]]', "·", name)[:90].strip()
    # с точки или «_» — скрытый файл: доска его не видит, а «..» — не имя
    name = name.lstrip("._ ").strip()
    return name or one_line(head.get("id")).lstrip("._ ") or "—"


# --- заметки-узлы ролей: «Кому» на карточке ссылается на узел, узлы связаны в дерево до «Владелец» ---------------

GODS = {"zeus": "Зевс", "hq": "Зевс", "athena": "Афина", "hermes": "Гермес", "proteus": "Протей", "themis": "Фемида",
        "calliope": "Каллиопа", "mnemo": "Мнемозина", "metis": "Метида", "janus": "Янус", "daedalus": "Дедал",
        "apollo": "Аполлон", "hephaestus": "Гефест", "argus": "Аргус", "chiron": "Хирон", "prometheus": "Прометей",
        "talos": "Талос", "clio": "Клио", "iris": "Ирида"}
OWNER_SLUGS = ("вы", "владелец", "owner", "human")
OWNER_NODE, HQ_NODE = "Владелец", "Зевс"
LEAD_GODS = ("hephaestus", "apollo")  # лиды направлений: подчиняются координатору направления с тем же суффиксом


class Roles:
    """Имена узлов и дерево подчинения по слагу роли. directions — имена направлений (координатор = имя направления)."""

    def __init__(self, directions):
        self.directions = sorted({str(d) for d in directions if d and d != "inbox"})
        firsts = [d.split("-")[0] for d in self.directions]
        self.shared = {f for f in firsts if firsts.count(f) > 1}  # два направления одного бога — узлы с суффиксом

    @staticmethod
    def slug(s):
        return one_line(s).lower()

    def name(self, s):
        low = self.slug(s)
        if low in OWNER_SLUGS:
            return OWNER_NODE
        first, _, rest = low.partition("-")
        god = GODS.get(first)
        if not god:
            # незнакомый — слаг в нижнем регистре: файловая система Mac регистр не различает, «Bob» и «bob» — один
            # узел. Совпал с именем бога («зевс», «гефест · x») — это узел бога, а не второй файл с тем же именем
            n = card_name({"title": low or "—"}, with_id=False)
            for g in set(GODS.values()) | {OWNER_NODE}:
                if n == g.lower() or n.startswith(g.lower() + " · "):
                    return g + n[len(g):]
            return n
        if not rest or (low in self.directions and first not in self.shared):
            return god
        return card_name({"title": f"{god} · {rest}"}, with_id=False)

    def direction(self, s):
        """Направление узла: координатор — своё, лид — направление с тем же суффиксом, остальные — None."""
        low = self.slug(s)
        if low in self.directions:
            return low
        first, _, rest = low.partition("-")
        if first in LEAD_GODS and rest:
            for d in self.directions:
                if d.endswith("-" + rest):
                    return d
        return None

    def parent(self, s):
        """→ слаг руководителя; None — у Владельца."""
        low = self.slug(s)
        name = self.name(low)
        if name == OWNER_NODE:
            return None
        if name == HQ_NODE:
            return "owner"
        if low in self.directions:
            return "zeus"
        first, _, rest = low.partition("-")
        if first in LEAD_GODS and rest:
            return self.direction(low) or "zeus"
        return "zeus"


def assignee(head):
    """Слаг «Кому»: owner задачи, без него — координатор направления (входящие — Зевс)."""
    d = head.get("direction")
    return head.get("owner") or ("zeus" if d in (None, "", "inbox") else d)


def link(name):
    return f"[[{name}]]"


ATTENTION_WORDS = ("конфликт", "подтвердите словом", "вопрос к вам", "долго ждёт", "просрочено", "срок скоро")


def attention(head, t, conflict=None, long_wait=False):
    """«Внимание» — список слов без эмодзи (считает тик, формулам Bases не доверяем); пусто — None, ключа нет.
    Список: формула Bases сравнивает по элементу (contains), эмодзи этому мешали бы. long_wait — решение без ответа
    дольше порога (политика уведомлений): карточка поднимается наверх колонки."""
    out = []
    if conflict:
        out.append("конфликт")
    if head.get("risky") is True and head.get("requested"):
        out.append("подтвердите словом")
    elif head.get("question") and head.get("status") == "waiting" and head.get("waiting_on") == "human":
        out.append("вопрос к вам")
    if long_wait:
        out.append("долго ждёт")
    due = head.get("due")
    if isinstance(due, str) and due and head.get("status") not in ("done", "dropped"):
        if overdue(head, t):
            out.append("просрочено")
        elif due[:10] <= now_iso(t + 3 * 86400)[:10]:
            out.append("срок скоро")
    return out or None


def _one(v):
    """Поле шапки в карточку — одной строкой: в кавычках "…" JSON раскрывает \\n, а строка «- [x] вариант» с начала
    строки читается тиком как ваш ответ (находка проверки безопасности 15.10). Начало «- [» тоже гасим."""
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f\x85]", " ", str(v))  # NUL и прочие управляющие — тоже в пробел
    text = re.sub(r"\s*[\r\n\u2028\u2029]+\s*", " ", text).strip()
    return "\\" + text if re.match(r"[-*+]\s*\[", text) else text


def _date(v, n):
    """Дата из файла-источника (не из файловой системы) — первые n знаков; не дата — None."""
    return v[:n] if isinstance(v, str) and DATE_RE.match(v) else None


def render_card(head, body, src_rel, t, conflict=None, notes=None, logged=None, who=None, long_wait=False):
    """who — имя узла «Кому» (board_sync считает его по реестру направлений); без него — по слагу без реестра.
    long_wait — «долго ждёт» во «Внимание» (решает политика уведомлений)."""
    head = {k: (_one(v) if isinstance(v, str) else [_one(x) for x in v] if isinstance(v, list) else v)
            for k, v in head.items()}
    lab = label_of(head)
    proj = head.get("project") or ""
    prio = head.get("priority")
    node = who or Roles(()).name(assignee(head))
    direction = head.get("direction") or "inbox"
    closed = head.get("status") in ("done", "dropped")
    card = {"Статус": lab, "Проект": f"{PROJECT_MARK.get(proj, '▪️')} {proj}".strip(),
            "Внимание": attention(head, t, conflict, long_wait),
            # «Срок» — свойство-дата Bases: только дата; время срока — в выноске карточки
            "Приоритет": prio if isinstance(prio, int) and not isinstance(prio, bool) else None,
            "Срок": _date(head.get("due"), 10),
            "Кому": link(node), "Дальше": None if closed else head.get("next"),
            "Ждёт": head.get("waiting_on") if head.get("waiting_on") not in (None, "human") else None,
            "Создана": _date(head.get("created"), 10),
            "Вопрос задан": _date(head.get("question_at"), 19) if head.get("question") else None,
            "Закрыта": _date(head.get("closed"), 10) if closed else None,
            "Тип": "задача", "id": head.get("id"), "tags": [f"направление/{direction}"]}
    due = f" · 📅 {due_text(head['due'])}" if head.get("due") else ""
    who = f" · 👤 {head['owner']}" if head.get("owner") else ""
    parts = [f"> [!{CALLOUT.get(lab, 'note')}] {STATUS_MARK.get(lab, '')} {lab} · {card['Проект']}{who}{due}"
             + (f" · {PRIORITY_MARK[prio]}" if prio in (0, 1) else "")
             + f"\n> Кому: {link(node)} · Направление: {direction}"]  # страховка: граф может не брать ссылки из свойств
    closed = head.get("status") in ("done", "dropped")
    if closed:
        if head.get("result"):  # «Дальше» у закрытой задачи — устаревший шаг, итогом его не показываем
            parts[-1] += f"\n> **Итог:** {head['result']}"
    elif head.get("next"):
        parts[-1] += f"\n> **Дальше:** {head['next']}"
    if head.get("waiting_on") not in (None, "human"):
        parts[-1] += f"\n> **Ждёт:** {head['waiting_on']}"
    if conflict:
        parts.append(f"> [!warning] {conflict}")
    desc = description(body)
    if desc:
        parts.append(desc)
    if head.get("question"):
        risky = head.get("risky") is True
        parts.append("## ❓ Нужно решить" + (" · ⚠ рискованно" if risky else "") + "\n\n" + head["question"].strip())
        if head.get("why"):
            parts.append(f"**Почему сейчас:** {head['why'].strip()}")
        opts = head.get("options") or []
        if logged is None:  # без журнала (старые вызовы) — как раньше, из файла
            cur = head.get("requested") if risky else head.get("answer")
        else:
            cur = logged.get("request" if risky else "answer")
        if opts:
            hint = ("Отметьте вариант — это только ваш выбор: действие начнётся после подтверждения словом в окне Зевса."
                    if risky else "Отметьте один вариант — агент получит ответ в течение минуты. Передумали — снимите "
                                  "галочку и отметьте другой, пока задача не закрыта.")
            parts.append(hint + "\n\n" + "\n".join(f"- [{'x' if o == cur else ' '}] {o}" for o in opts))
        tail = []
        if head.get("recommend"):
            tail.append(f"**Совет:** {head['recommend'].strip()}")
        if head.get("if_no_answer"):
            tail.append(f"**Без ответа:** {head['if_no_answer'].strip()}")
        if tail:
            parts.append("\n".join(tail))
        if risky and head.get("requested"):
            parts.append(f"> [!warning] Вы выбрали «{head['requested']}». Подтвердите словом в окне Зевса: "
                         f"«да, {head['requested']}» — без этого агент не начнёт.")
    shown = head.get("answer") if logged is None else logged.get("answer")
    if shown and not head.get("question"):
        parts.append(f"**Ваш ответ:** {shown}")
    m = re.search(r"## Журнал\n(.*)$", body, re.S)
    if m:
        log = [x for x in m.group(1).strip().split("\n") if x.startswith("- ")][-3:][::-1]
        if log:  # «- [x] …» из журнала (его пишут агенты) не должна читаться как ваша галочка
            parts.append("## Последнее\n\n" + "\n".join("- " + ("\\" if x[2:].lstrip()[:1] == "[" else "") + x[2:]
                                                        for x in log))
    # без отметки времени: иначе тик переписывал бы каждую карточку каждую минуту, а Obsidian перечитывал бы доску
    parts.append(f"<small>Источник: `{src_rel}` · задача обновлена {str(head.get('updated') or '')[:16].replace('T', ' ')}</small>")
    parts.append(notes_block(notes or []))
    return card, "\n" + "\n\n".join(parts) + "\n"


def agent_text(text, title, limit=40):
    """Текст, который пишут агенты (текст задачи, заявка), — в карточку только внутри рамки с подписью: заголовок
    «## ✍️ Ваши заметки», «- [x] вариант» или «> [!warning]» в нём остаются частью рамки, а не разделом карточки,
    вашей галочкой или предупреждением тика (находка проверки безопасности 15.10)."""
    lines = text.strip().split("\n")
    out = [f"> [!abstract] {title}"]
    for ln in lines[:limit]:
        ln = ln.rstrip()
        if re.match(r"\s*(?:>\s*)*\[!", ln):
            ln = ln.replace("[", "\\[", 1)
        out.append("> " + ln if ln else ">")
    if len(lines) > limit:
        out.append("> …")
    return "\n".join(out)


def description(body, limit=40):
    """Текст задачи под заголовком до первого раздела «## …» — в рамке «Текст задачи»."""
    m = re.search(r"^# [^\n]*\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    if not m or not m.group(1).strip():
        return ""
    return agent_text(m.group(1), "Текст задачи (пишет агент)", limit)


def notes_block(notes):
    """Раздел карточки в самом низу: ваши переданные заметки, под ними — место для новых. Берутся из журнала доски
    (owner-log/board.jsonl — ролям не записать), а не из файла задачи: его направление может дописать от вашего имени.
    Цитатой: строка «- [x]» в заметке не станет галочкой."""
    text = NOTES_HEAD + "\n\n" + NOTES_HINT
    lines = []
    for rec in notes:
        lines.append(f"> **{str(rec.get('time') or '')[:16].replace('T', ' ')}**")
        lines += ["> " + ln.rstrip() for ln in str(rec.get("text") or "").strip().split("\n") if ln.strip()]
    if lines:
        text += "\n\n" + "\n".join(lines)
    return text + "\n"


def owner_notes_all(log_path):
    """Ваши заметки по задачам из журнала доски: {id: [запись, …]}."""
    out = {}
    try:
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("kind") == "note" and not rec.get("inbox") and rec.get("text"):
                    out.setdefault(rec.get("id"), []).append(rec)
    except OSError:
        pass
    return out


def owner_answers_all(log_path):
    """Ваши ответы с доски из журнала owner-log/board.jsonl: {id: {"answer": последний, "request": последний}}.
    Карточка показывает ответ отсюда, а не из поля answer файла задачи: файл может поправить и агент (metis-0024)."""
    out = {}
    try:
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(rec, dict) and rec.get("kind") in ("answer", "request")
                        and isinstance(rec.get("answer"), str) and rec.get("id")):
                    out.setdefault(rec["id"], []).append(rec)
    except OSError:
        pass
    return out


def _question_key(text):
    """Вопрос для сверки файла задачи с журналом — целиком, с точностью до пробелов и переносов (карточка их склеивает);
    «\\» снимается только там, где его ставит _one (перед «- [»). Обрезанная запись журнала (2000 знаков) не
    сверяется: хвост вопроса мог измениться (проверка безопасности 15.10). Пустой ключ — «вопроса нет»."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if re.match(r"\\[-*+]\s*\[", t):
        t = t[1:]
    return t


def logged_for(head, recs):
    """Ваш действующий ответ на ТЕКУЩИЙ вопрос задачи: последняя запись журнала, у которой вариант есть среди
    нынешних options, а вопрос (если записан) совпадает с нынешним. Ответ на прежний вопрос той же задачи
    новым не засчитывается (проверка безопасности 15.10)."""
    opts = [_one(o) for o in head.get("options") or []]
    q = _question_key(head.get("question"))
    out = {}
    for rec in recs or []:
        if opts and rec["answer"] not in opts:
            continue
        rq = rec.get("question") or ""
        # запись без вопроса (до 0.9.26) или обрезанная — на нынешний вопрос не засчитывается
        if q and (len(rq) >= 2000 or _question_key(rq) != q):
            continue
        out[rec["kind"]] = rec["answer"]
    return out


def answer_conflict(head, logged, recs=None):
    """Поле answer/requested файла задачи не равно ПОСЛЕДНЕМУ вашему ответу этого вида по задаче (на любой
    вопрос) → текст конфликта, иначе None. Тик пишет поле и журнал одним ходом, поэтому честный файл всегда равен
    последней записи; прежний ответ после нового вопроса — тоже она. Правкой текста вопроса это не обойти
    (проверка безопасности 15.10)."""
    risky = head.get("risky") is True
    field, kind = ("requested", "request") if risky else ("answer", "answer")
    in_file = head.get(field)
    last = next((r["answer"] for r in reversed(recs or []) if r.get("kind") == kind), None)
    if in_file and in_file != last:
        return (f"ответ в файле задачи («{str(in_file)[:120]}») не из вашего журнала"
                + (f" — там последним «{last[:120]}»" if last else " — там ответа нет")
                + ". Карточка показывает ответ из журнала; агент его не видит как ваш.")
    return None


def add_owner_note(body, stamp, note):
    """Заметку из карточки — в раздел «Заметки владельца» файла задачи (перед журналом). Строки — цитатой: текст
    владельца не начнёт новый раздел файла."""
    entry = f"- {stamp}\n" + "\n".join("  > " + ln.rstrip() for ln in note.strip().split("\n")) + "\n"
    if OWNER_NOTES not in body:
        i = body.find("## Журнал")
        block = OWNER_NOTES + "\n\n"
        body = (body[:i] + block + "\n" + body[i:]) if i >= 0 else body.rstrip("\n") + "\n\n" + block
    i = body.index(OWNER_NOTES) + len(OWNER_NOTES)
    j = body.find("\n## ", i)
    j = len(body) if j < 0 else j
    section = body[i:j].rstrip("\n") + "\n\n" + entry
    return body[:i] + section + body[j:]


def owner_added(rendered, body):
    """Строки, которые владелец дописал в тело карточки сверх нарисованного тиком (галочки ответов — не в счёт)."""
    if rendered is None:
        return None
    old = {ln.strip() for ln in rendered.split("\n")}
    added = [ln.strip() for ln in body.split("\n") if ln.strip() and ln.strip() not in old
             and not re.match(r"^- \[[ xXхХ]\] ", ln.strip())]
    return "\n".join(added) or None


def checked_option(body):
    m = re.findall(r"^- \[[xXхХ]\] (.+)$", body, re.M)
    return m[0].strip() if len(m) == 1 else (None if not m else "?")


BASE_FILE = """filters:
  and:
    - file.inFolder("Доска")
    - 'file.folder == "Доска"'
    - file.name != "Сводка"
    - file.name != "Проблемы"
formulas:
  urgency: 'if(note["Внимание"], if(note["Внимание"].contains("конфликт"), 0, if(note["Внимание"].contains("подтвердите словом"), 0, if(note["Внимание"].contains("просрочено"), 1, if(note["Внимание"].contains("долго ждёт"), 1, if(note["Внимание"].contains("срок скоро"), 2, 3))))), 3)'
  prio_rank: 'if(note["Приоритет"].isEmpty(), 2, number(note["Приоритет"]))'
  age_key: 'if(note["Статус"] == "Готово", if(note["Закрыта"], 0 - number(note["Закрыта"]), 0), if(note["Создана"], number(note["Создана"]), 0))'
  stage: 'if(note["Статус"] == "Нужен ответ", 0, if(note["Статус"] == "Входящие", 1, if(note["Статус"] == "На проверке", 2, if(note["Статус"] == "В работе", 3, if(note["Статус"] == "Ждёт", 4, if(note["Статус"] == "Очередь", 5, if(note["Статус"] == "Готово", 6, 7)))))))'
properties:
  file.name:
    displayName: Задача
views:
  - type: kanban
    name: Доска
    groupBy:
      property: note.Статус
      direction: ASC
    groupOrder: [Входящие, Нужен ответ, Очередь, В работе, Ждёт, На проверке, Готово, Отменено]
    sort:
      - property: formula.urgency
        direction: ASC
      - property: formula.prio_rank
        direction: ASC
      - property: note.Срок
        direction: ASC
      - property: formula.age_key
        direction: ASC
    order: [file.name, note.Проект, note.Внимание, note.Приоритет, note.Срок, note.Кому]
  - type: table
    name: Нужен ответ
    filters:
      and:
        - 'note["Статус"] == "Нужен ответ"'
    sort:
      - property: formula.urgency
        direction: ASC
      - property: formula.prio_rank
        direction: ASC
      - property: note.Срок
        direction: ASC
      - property: formula.age_key
        direction: ASC
    order: [file.name, note.Проект, note.Внимание, note.Дальше, note.Срок, note.Вопрос задан]
  - type: table
    name: Горит
    filters:
      and:
        - 'formula.urgency < 3'
        - 'note["Статус"] != "Готово"'
    sort:
      - property: formula.urgency
        direction: ASC
      - property: note.Срок
        direction: ASC
      - property: formula.prio_rank
        direction: ASC
      - property: formula.age_key
        direction: ASC
    order: [file.name, note.Проект, note.Статус, note.Внимание, note.Срок, note.Дальше]
  - type: table
    name: Все задачи
    groupBy:
      property: note.Проект
      direction: ASC
    sort:
      - property: formula.stage
        direction: ASC
      - property: formula.urgency
        direction: ASC
      - property: formula.prio_rank
        direction: ASC
      - property: note.Срок
        direction: ASC
      - property: formula.age_key
        direction: ASC
    order: [file.name, note.Статус, note.Внимание, note.Приоритет, note.Кому, note.Срок, note.Дальше, note.Создана, note.Закрыта]
"""
BASE_VERSION = hashlib.sha256(BASE_FILE.encode("utf-8")).hexdigest()[:12]  # сменился шаблон — тик перепишет Доска.base
# sha256[:16] шаблонов BASE_FILE до 0.9.28 (c616683 — 0.9.27, 7be0aa5 — раньше): тогда в состоянии не было base_hash,
# и нетронутый старый файл иначе считался бы правкой владельца. Дальше то, что записал тик, помнит base_hash
OLD_BASE_HASHES = {"917c6bef26511e65", "44467393293d25f4"}


OWNER_ONLY_FIELDS = ("answer", "requested")  # ставит только доска: ответ владельца и выбор по рискованному


def owner_words(log_path, tid):
    """Записи журнала владельца по задаче — единственное подтверждение его слов (строки «владелец:» в журнале
    задачи и поле answer — копия для удобства: направление может их переписать)."""
    out = []
    try:
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("id") == tid:
                    out.append(rec)
    except OSError:
        pass
    return out


def seen_question(card_body):
    """Текст вопроса так, как он стоит в карточке владельца: от «## ❓ Нужно решить» до «Почему сейчас» или вариантов."""
    m = re.search(r"^## ❓ Нужно решить[^\n]*\n(.*?)(?=^\*\*Почему сейчас:\*\*|^Отметьте |^- \[[ xX]\] |\Z)",
                  card_body, re.M | re.S)
    return m.group(1).strip()[:2000] if m else ""


def _owner_log(path, t, **rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rec = {"time": now_iso(t), **rec}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _live(head, t):
    st = head.get("status")
    if st in ("inbox", "todo", "doing", "waiting", "review"):
        return True
    return (head.get("updated") or "") >= now_iso(t - 7 * 86400)


def _plain(text):
    return re.sub(r"[\[\]|<>`#]", "·", one_line(text))  # одной строкой: перевод строки рвал бы список сводки; # — не тег


SUMMARY_WAIT_TOP = 5  # «Нужен ответ» в сводке: столько с советом, остальные — «ещё N»


def _summary(tasks, t, inbox=None, names=None, long_ids=None, queue=None):
    """names — id → имя файла карточки (как его записал проход доски); ссылки — с подписью-заголовком.
    long_ids — решения «долго ждёт»; queue — что политика уведомлений отложила без пинга за сутки."""
    names, long_ids = names or {}, long_ids or set()
    rows = {"wait": [], "overdue": [], "doing": [], "done": [],
            "inbox": [f"[[Доска/{names.get(cid) or card_name({'title': it['title']})}|{_plain(it['title'])}]] · "
                      f"{it['direction']}" for cid, it in (inbox or {}).items()]}
    wait = []
    for tid, (p, h, _) in sorted(tasks.items()):
        name = f"[[Доска/{names.get(tid) or card_name(h)}|{_plain(h.get('title'))}]] · {_plain(h.get('project'))}"
        if h.get("status") == "waiting" and h.get("waiting_on") == "human":
            rows["wait"].append(name)
            line = name + (f" · срок {due_text(h['due'])}" if h.get("due") else "")
            if h.get("recommend"):
                rec = _plain(h["recommend"])
                line += " · совет: " + (rec if len(rec) <= 120 else rec[:119] + "…")
            if tid in long_ids:
                line += " · ⏳ долго ждёт"
            since = ts_of(h.get("question_at")) or ts_of(h.get("created")) or t
            wait.append((due_ts(h.get("due")) or float("inf"), since, tid, line))
        if overdue(h, t):
            rows["overdue"].append(f"{name} · срок {h['due']}")
        if h.get("status") == "doing":
            rows["doing"].append(f"{name} · {_plain(h.get('owner')) or '—'}")
        if h.get("status") == "done" and (h.get("updated") or "") >= now_iso(t - 86400):
            rows["done"].append(name)
    sec = lambda title, xs, n=None: (f"## {title} ({len(xs) if n is None else n})\n\n"
                                     + ("\n".join(f"- {x}" for x in xs) if xs else "—") + "\n")
    # «Нужен ответ» — по сроку (ближний сверху), затем по возрасту (старый сверху); до 5 с советом, дальше «ещё N»
    wait.sort(key=lambda x: (x[0], x[1], x[2]))
    top = [x[3] for x in wait[:SUMMARY_WAIT_TOP]]
    if len(wait) > SUMMARY_WAIT_TOP:
        top.append(f"ещё {len(wait) - SUMMARY_WAIT_TOP} — колонка «{HUMAN_WAIT}» на доске")
    quiet = [f"{when} · {_plain(text)}" for when, _, _, text in (queue or [])]
    return ("# Сводка\n\n" + sec(f"🔴 {HUMAN_WAIT}", top, len(wait)) + "\n"
            + sec("⏰ Просрочено", rows["overdue"]) + "\n"
            + sec("📥 Входящие заявки направлениям", rows["inbox"]) + "\n"
            + sec("🟡 В работе", rows["doing"]) + "\n" + sec("🟢 Готово за сутки", rows["done"])
            + ("\n" + sec("🔕 Без уведомления за сутки", quiet) if quiet else "")
            + "\n✍️ Написать агенту — текстом в раздел «Ваши заметки» внизу карточки. Перенести — перетащите карточку на доске. "
              "Готовые карточки уходят с доски через 7 дней.\n"), rows




def card_url(vault, name):
    from urllib.parse import quote
    return f"obsidian://open?vault={quote(vault)}&file={quote('Доска/' + name + '.md')}"


def inbox_items(pantheon):
    """Входящие направлений: свободные заявки directions/<имя>/inbox/*.md (разбирает координатор)."""
    out, d = {}, os.path.join(pantheon, "directions")
    for name in list_dir(d):
        ib = os.path.join(d, name, "inbox")
        if not DIRECTION_RE.fullmatch(name):
            continue
        for f in list_dir(ib):
            path = os.path.join(ib, f)
            if not f.endswith(".md") or f.startswith(".") or not is_file(ib, f):
                continue
            try:
                text = read_text(path)[:20000]
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            m = re.search(r"^# (.+)$", text, re.M)
            frm = re.search(r"^От: (.+)$", text, re.M)
            cid = "in-" + hashlib.sha1(f"{name}/{f}".encode()).hexdigest()[:10]
            out[cid] = {"path": path, "direction": name, "file": f, "title": (m.group(1).strip() if m else f[:-3]),
                        "from": frm.group(1).strip() if frm else None, "text": text}
    return out


def render_inbox_card(item, project, conflict=None, who=None):
    proj = project or item["direction"]
    card = {"Статус": "Входящие", "Проект": f"{PROJECT_MARK.get(proj, '▪️')} {proj}".strip(),
            "Внимание": ["конфликт"] if conflict else None, "Кому": link(who or Roles(()).name(item["direction"])),
            "Дальше": "разобрать: в «Очередь» — станет задачей направления, в «Отменено» — в архив",
            "Тип": "заявка", "id": item["id"], "tags": [f"направление/{item['direction']}"]}
    body = re.sub(r"^# .+\n", "", item["text"], count=1, flags=re.M)
    body = re.sub(r"^От: .+\n", "", body, count=1, flags=re.M).strip()
    short = agent_text(body, f"Заявка от {item.get('from') or 'направления'}", 30) if body else ""
    parts = [f"> [!note] 📥 Входящие · {card['Проект']} · 👤 {item['direction']}"
             + (f"\n> **От:** {item['from']}" if item.get("from") else "")]
    if conflict:
        parts.append(f"> [!warning] {conflict}")
    if short:
        parts.append(short)
    rel = f"directions/{item['direction']}/inbox/{item['file']}"
    parts.append("Перенесите в «Очередь» — заявка станет задачей направления; в «Отменено» — уйдёт в архив входящих.\n\n"
                 f"<small>Источник: `{rel}`</small>")
    parts.append(notes_block(""))
    return card, "\n" + "\n\n".join(parts) + "\n"


def _inbox_done(item, t, prefix="", check_only=False):
    """Заявку — в inbox/done/ (папки открываются цепочкой без ссылок; check_only — только проверить путь)."""
    done = os.path.join(os.path.dirname(item["path"]), "done")
    try:
        with _in_dir(os.path.join(done, ".probe"), create=True) as (fd, _):
            if fd is None:
                raise ValueError("заявка вне корня Пантеона")
    except OSError as e:
        raise ValueError(f"inbox/done — ссылка или не папка ({e.strerror}); заявку не трогаю") from e
    if check_only:
        return
    dst = os.path.join(done, prefix + item["file"])
    try:
        move(item["path"], dst)
    except FileExistsError:
        move(item["path"], os.path.join(done, f"{prefix}{int(t)}-{item['file']}"))


def _accept_inbox(want, it, cid, p, pantheon, t, projects, log_path, rel, done_lines, cards, inbox, moved_by_owner, st):
    """Ход владельца по заявке направлению: в «Очередь»/«В работе» — задача, в «Отменено» — архив."""
    if want in ("Очередь", "В работе"):
        _inbox_done(it, t, check_only=True)  # сначала — можно ли убрать заявку, потом — задача
        body_text = re.sub(r"^# .+\n", "", it["text"], count=1, flags=re.M).strip()
        tid, tp = task_new(pantheon, t, it["direction"], it["title"], project=projects.get(it["direction"]),
                           owner=it["direction"], status="todo" if want == "Очередь" else "doing",
                           next="разобрать заявку" if want == "В работе" else None, actor="владелец")
        th, tb = read(tp)
        tb = tb.replace("\n## Журнал", f"\n{body_text}\n\n## Журнал", 1)
        write(tp, th, append_log(tb, f"{now_iso(t)[:16].replace('T', ' ')} — владелец: заявка из входящих → «{want}»"))
        _inbox_done(it, t)
        _owner_log(log_path, t, kind="inbox-accept", id=cid, task=tid, dst=want, inbox=rel(it["path"]))
        done_lines.append(f"{cid}: заявка стала задачей {tid} («{want}»)")
        os.remove(p)
        cards.pop(cid, None)
        inbox.pop(cid)
        moved_by_owner.add(tid)
    elif want == "Отменено":
        _inbox_done(it, t, "отклонено-")
        _owner_log(log_path, t, kind="inbox-drop", id=cid, inbox=rel(it["path"]))
        done_lines.append(f"{cid}: заявка в архив входящих")
        os.remove(p)
        cards.pop(cid, None)
        inbox.pop(cid)
    elif want != "Входящие":
        st["conflict_at"] = t
        st["conflict"] = "заявку можно перенести в «Очередь», «В работе» или «Отменено»"


def _sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()[:16]


def _write_plain(path, text):
    """Запись вне корня Пантеона (папка доски, хранилище, состояние): через временный файл."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def node_texts(roles, tasks, names, slugs):
    """Заметки-узлы ролей: {имя узла: текст}. Узлы — для тех, кто в «Кому» живых карточек, и их цепочки вверх
    (Зевс, Владелец, координатор направления лида): иначе дерево графа рвётся. Без отметки времени — пишется,
    только когда изменилось."""
    nodes = {}

    def add(slug):
        while slug is not None:
            n = roles.name(slug)
            if n in nodes:
                return
            parent = roles.parent(slug)
            nodes[n] = {"id": "zeus" if n == HQ_NODE else "owner" if n == OWNER_NODE else roles.slug(slug),
                        "parent": roles.name(parent) if parent is not None else None,
                        "direction": roles.direction(slug), "tasks": []}
            slug = parent

    for cid in sorted(slugs):
        add(slugs[cid])
    for tid, (_, h, _) in sorted(tasks.items()):
        if tid in slugs and tid in names and h.get("status") not in ("done", "dropped"):
            due = f" · срок {h['due']}" if h.get("due") else ""
            nodes[roles.name(slugs[tid])]["tasks"].append(
                f"- [[{names[tid]}|{tid}]] · {_plain(_one(h.get('title') or ''))} · {label_of(h)}{due}")
    out = {}
    for n, nd in nodes.items():
        head = {"type": "узел", "id": nd["id"], "parent": link(nd["parent"]) if nd["parent"] else None,
                "tags": [f"направление/{nd['direction']}"] if nd["direction"] else None}
        body = ("\n> Сгенерировано тиком. Не править.\n\n" + (f"Руководитель: {link(nd['parent'])}\n\n" if nd["parent"] else "")
                + f"## Открытые задачи ({len(nd['tasks'])})\n\n" + ("\n".join(nd["tasks"]) or "—") + "\n")
        out[n] = join(head, body, ["type", "id", "parent", "tags"])
    return out


def _sync_nodes(board, state, roles, tasks, names, slugs, alert):
    """Узлы в Доска/Узлы/: свои (хеш в состоянии) переписывает и удаляет; чужой файл с тем же именем и узел, который
    владелец правил, при удалении не трогает."""
    d = os.path.join(board, NODES_DIR)
    # имена сравниваются без регистра: файловая система Mac его не различает («Bob.md» и «bob.md» — один файл)
    old = {k.casefold(): v for k, v in (state.get("nodes") or {}).items()}
    mine = {}
    for n, text in node_texts(roles, tasks, names, slugs).items():
        p = os.path.join(d, n + ".md")
        if os.path.dirname(os.path.abspath(p)) != os.path.abspath(d):  # страховка: имя узла не выводит из Узлы/
            alert(f"board-node-path-{_sha(n)}", "1", f"доска: имя узла «{n[:60]}» не по образцу — пропущен", "board")
            continue
        try:
            try:
                with open(p, encoding="utf-8") as fh:
                    cur = fh.read()
            except FileNotFoundError:
                cur = None
            except (OSError, UnicodeDecodeError):
                cur = ""
            if cur == text:
                mine[n] = _sha(text)
                continue
            if cur is not None and n.casefold() not in old:
                alert(f"board-node-{n}", _sha(cur), f"доска: в Доска/{NODES_DIR}/ лежит чужой файл «{n}.md» — узел "
                                                    f"роли не записан; переименуйте или удалите файл", "board")
                continue
            _write_plain(p, text)
            mine[n] = _sha(text)
        except (OSError, ValueError, UnicodeError) as e:  # один битый узел не останавливает проход
            alert(f"board-node-{_sha(n)}", type(e).__name__, f"доска: узел «{n[:60]}» не записать ({e}) — пропущен",
                  "board")
    kept = {m.casefold() for m in mine}
    for f in (sorted(os.listdir(d)) if os.path.isdir(d) else []):
        n = f[:-3]
        if not f.endswith(".md") or n.casefold() in kept or n.casefold() not in old:
            continue
        p = os.path.join(d, f)
        try:
            with open(p, encoding="utf-8") as fh:
                cur = fh.read()
            head, _ = split(cur)
            if _sha(cur) == old[n.casefold()] and (head or {}).get("type") == "узел":
                os.remove(p)  # узел ушедшей роли; правленный владельцем — оставляем
        except (OSError, UnicodeDecodeError, HeaderError):
            continue
    if mine or "nodes" in state:
        state["nodes"] = mine


def _sync_base(board, state, state_path, t, alert):
    """Доска.base: нет файла или сменилась версия шаблона — записать; владелец правил файл — его версию сохранить
    в папку состояния и одна тревога. Та же версия — не трогать: настройки вида владельца живут."""
    bp = os.path.join(board, "Доска.base")
    try:
        with open(bp, "rb") as fh:
            cur = fh.read()
    except FileNotFoundError:
        cur = None
    if cur is not None and state.get("base_version") == BASE_VERSION:
        return
    new = BASE_FILE.encode("utf-8")
    # нетронутый прежний шаблон (у 0.9.27 и раньше в состоянии нет base_hash) — не правка владельца
    if cur is not None and cur != new and _sha(cur) != state.get("base_hash") and _sha(cur) not in OLD_BASE_HASHES:
        keep = os.path.join(os.path.dirname(os.path.abspath(state_path)),
                            f"board-base-{datetime.fromtimestamp(t).strftime('%Y%m%d-%H%M%S')}.base")
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        with open(keep, "wb") as fh:
            fh.write(cur)
        alert(f"board-base-{BASE_VERSION}", BASE_VERSION, f"Доска.base обновлён, ваша версия сохранена в {keep}", "board")
    if cur != new:
        _write_plain(bp, BASE_FILE)
    state["base_version"], state["base_hash"] = BASE_VERSION, _sha(new)


def _sync_types(vault, alert):
    """.obsidian/types.json хранилища: типы свойств карточек. Свои ключи ставит, чужие не трогает, пишет только при
    изменении; битый JSON — не трогает, одна тревога."""
    p = os.path.join(vault, ".obsidian", "types.json")
    try:
        with open(p, encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        raw = None
    except (OSError, UnicodeDecodeError) as e:
        alert("board-types", "unreadable", f"доска: {p} не читается ({e}) — типы свойств не обновлены", "board")
        return
    data = {"types": {}}
    if raw is not None:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.setdefault("types", {}), dict):
                raise ValueError("нет словаря types")
        except ValueError as e:
            alert("board-types", _sha(raw), f"доска: {p} — битый JSON ({e}); типы свойств не обновлены, файл не тронут",
                  "board")
            return
    if all(data["types"].get(k) == v for k, v in PROP_TYPES.items()):
        return
    data["types"].update(PROP_TYPES)
    _write_plain(p, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def board_sync(pantheon, board, state_path, log_path, t, alert=None, notify=None, primary=True, projects=None,
               policy=None):
    """Один проход доски. → список строк «что сделано» (для журнала тика). policy — политика уведомлений
    (lib/notify.py, её передаёт pantheon.py): решает, что показать, что отложить в сводку. Без неё — без
    уведомлений; notify — прежний параметр, не используется."""
    alert = alert or (lambda *a, **k: None)
    projects = projects or {}
    vault = os.path.basename(os.path.dirname(os.path.abspath(board)))
    done_lines, moved_by_owner = [], set()
    os.makedirs(board, exist_ok=True)
    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    cards = state.setdefault("cards", {})
    tasks = load_tasks(pantheon)
    inbox = inbox_items(pantheon)
    for cid, it in inbox.items():
        it["id"] = cid
    rel = lambda p: os.path.relpath(p, pantheon)

    # 1. что сейчас лежит в доске
    present, fresh, seen, mtime = {}, [], {}, {}
    for f in sorted(os.listdir(board)):
        if not f.endswith(".md") or f.startswith((".", "_")) or f in ("Сводка.md", "Проблемы.md"):
            continue
        p = os.path.join(board, f)
        try:
            head, body = read(p)
        except (HeaderError, OSError, UnicodeDecodeError) as e:
            alert(f"board-broken-{f}", "1", f"доска: карточка «{f}» не читается ({e}) — поправьте или удалите")
            continue
        head = head or {}
        cid = head.get("id")
        mtime[p] = os.path.getmtime(p)
        if cid and cid in present:
            continue
        if cid:
            present[cid] = (p, head, body)
            seen[cid] = digest(p)
        else:
            fresh.append((p, f[:-3], head, body))

    # 2. новые карточки владельца (без id) → задача во входящих, разбирает Зевс
    for p, name, head, body in fresh:
        if t - mtime[p] < QUIET or (name.startswith(UNTITLED) and t - mtime[p] < 600):
            continue  # владелец ещё пишет карточку; без названия ждём, пока назовёт (или 10 минут)
        text = (head.get(NOTE_KEY) or "").strip() if isinstance(head.get(NOTE_KEY), str) else ""
        title = name if not name.startswith(UNTITLED) else (text or body.strip().split("\n")[0] or name)
        try:
            tid, path = task_new(pantheon, t, "inbox", title, project="входящие", owner="zeus", status="inbox",
                                 actor="владелец")
        except ValueError as e:
            alert(f"board-new-{name}", "1", f"доска: не создать задачу из карточки «{name}»: {e}")
            continue
        if body.strip() or text:
            src_head, src_body = read(path)
            write(path, src_head, append_log(src_body, f"{now_iso(t)[:16].replace('T', ' ')} — владелец: "
                                                       f"{' '.join((text or body.strip()).split())[:500]}"))
        _owner_log(log_path, t, kind="new", id=tid, title=title)
        os.remove(p)
        done_lines.append(f"новая задача {tid} из карточки «{name}»")
        tasks = load_tasks(pantheon)

    # 3. ходы владельца на известных карточках (перенос — сразу: он делается одним движением;
    #    заметку Obsidian сохраняет по Enter или уходу из поля, галочку — щелчком: берём сразу)
    typing = set()
    answers_by_id = owner_answers_all(log_path)
    for cid, (p, head, body) in present.items():
        st = cards.get(cid)
        if st and digest(p) != st.get("card_hash") and t - mtime[p] < QUIET and owner_added(st.get("rendered"), body):
            typing.add(cid)  # вы ещё пишете заметку: не забираем недописанное и не перерисовываем карточку под курсором
            continue
        if not st or digest(p) == st.get("card_hash"):
            continue  # карточку никто не трогал
        want = norm_label(head.get("Статус"))
        synced = norm_label(st.get("synced"))
        note = head.get(NOTE_KEY) if isinstance(head.get(NOTE_KEY), str) and head.get(NOTE_KEY).strip() else None
        if cid in inbox:  # заявка направлению
            it = inbox[cid]
            extra = owner_added(st.get("rendered"), body)
            if extra:
                note = f"{note.strip()}\n{extra}" if note else extra
            if note:
                append_text(it["path"], f"\n\n- {now_iso(t)[:16].replace('T', ' ')} — владелец: {' '.join(note.split())[:1000]}\n")
                _owner_log(log_path, t, kind="note", id=cid, text=note.strip()[:1000], inbox=rel(it["path"]))
                done_lines.append(f"{cid}: заметка владельца к заявке")
            try:
                _accept_inbox(want, it, cid, p, pantheon, t, projects, log_path, rel, done_lines, cards, inbox, moved_by_owner, st)
            except (ValueError, OSError) as e:
                st["conflict_at"] = t
                st["conflict"] = f"заявку не перенести: {e}"
            continue
        if cid not in tasks:
            continue
        src_path, src_head, _ = tasks[cid]
        logged = logged_for(src_head, answers_by_id.get(cid))
        src_moved = digest(src_path) != st.get("src_hash")
        answer = checked_option(body) if src_head.get("options") else None
        if answer and answer != "?" and answer not in [_one(o) for o in src_head.get("options") or []]:
            # отмечена строка, которой нет среди вариантов задачи, — не ваш ответ, но и не молча: конфликт в карточке
            st["conflict_at"] = t
            st["conflict"] = (f"отмечен вариант, которого нет в задаче: «{_one(answer)[:120]}». "
                              f"Отметьте один из вариантов ниже")
            done_lines.append(f"{cid}: отмечен вариант не из задачи — конфликт в карточке")
            answer = None
        extra = owner_added(st.get("rendered"), body)  # текст, дописанный прямо в карточку, — тоже заметка
        if extra:
            note = f"{note.strip()}\n{extra}" if note else extra
        if want != synced:
            if src_moved:
                st["conflict_at"] = t
                st["conflict"] = f"пока вы переносили карточку в «{want}», агент изменил задачу — статус сейчас «{label_of(src_head)}». Перенесите ещё раз, если нужно."
                done_lines.append(f"{cid}: конфликт — ход «{want}» не применён")
                if policy is not None:  # конфликт карточки — без пинга, в сводку (таблица 6.3)
                    policy.later("conflict", cid, f"⚠ Перенос не применён: {one_line(src_head.get('title') or cid)}")
            elif want not in OWNER_TARGETS:
                st["conflict_at"] = t
                st["conflict"] = f"в «{want}» карточку переносит агент; вы можете: {', '.join(OWNER_TARGETS)}."
            else:
                status, wait_on = OWNER_TARGETS[want]
                ch = {"status": status}
                if wait_on:
                    ch["waiting_on"] = wait_on
                    ch["next"] = src_head.get("next") or "решение владельца"
                if status == "todo":
                    ch["claimed_by"], ch["claimed_until"] = None, None
                try:
                    task_set(pantheon, t, cid, ch, note=f"перенёс «{synced}» → «{want}»", actor="владелец")
                    _owner_log(log_path, t, kind="move", id=cid, src=synced, dst=want)
                    done_lines.append(f"{cid}: ход владельца «{synced}» → «{want}»")
                    moved_by_owner.add(cid)
                    if want == "В работе":  # будит исполнителя (с шага 1.4 — pantheon wake); вас не уведомляем
                        alert(f"wake-{cid}-{now_iso(t)[:16]}", "1",
                              f"«Сделать сейчас»: {src_head.get('title')} ({cid}) — разбудить {src_head.get('owner') or src_head.get('direction')}",
                              "board")
                    st.pop("conflict", None)
                    st.pop("conflict_at", None)
                except ValueError as e:
                    st["conflict_at"] = t
                    st["conflict"] = f"ход «{want}» не применён: {e}"
        if note:
            task_note(pantheon, t, cid, note.strip()[:4000])
            _owner_log(log_path, t, kind="note", id=cid, text=note.strip()[:4000])
            done_lines.append(f"{cid}: заметка владельца передана")
        risky = src_head.get("risky") is True
        # текущий ответ — из журнала, а не из файла: иначе поддельное answer в файле глушило бы вашу галочку
        current = logged.get("request" if risky else "answer")
        if answer and answer != "?" and answer != current:
            if risky:  # согласие на рискованное — только словом в окне Зевса; галочка — лишь выбор
                task_set(pantheon, t, cid, {"requested": answer},
                         note=f"выбрал «{answer}» — нужно подтверждение словом в окне Зевса", actor="владелец")
                _owner_log(log_path, t, kind="request", id=cid, answer=answer, question=seen_question(body))
                done_lines.append(f"{cid}: выбор владельца «{answer}» по рискованному — ждёт подтверждения словом")
            else:
                ch = {"answer": answer}
                if src_head.get("status") == "waiting" and src_head.get("waiting_on") == "human":
                    ch["status"] = "todo"
                task_set(pantheon, t, cid, ch, note=f"ответ: {answer}" + (f" (был «{current}»)" if current else ""),
                         actor="владелец")
                # вопрос — из карточки, которую вы отметили (её рисует тик, роли туда не пишут), а не из файла
                # задачи: его направление может поправить между вашей галочкой и тиком
                _owner_log(log_path, t, kind="answer", id=cid, answer=answer, question=seen_question(body))
                done_lines.append(f"{cid}: ответ владельца «{answer}»")
                # Зевсу — тревогой (её видит хук штаба): исполнитель ждёт его сигнала «pantheon consent» (metis-0022)
                alert(f"answer-{cid}", answer, f"ответ владельца на доске: {cid} — «{answer[:120]}». Если исполнитель "
                      f"ждёт — сообщи ему: pantheon consent {cid}", "board")
            moved_by_owner.add(cid)
            st.pop("conflict", None)  # верный вариант применён — прежний конфликт (неверная галочка, несколько) снят
            st.pop("conflict_at", None)
        elif answer == "?":
            st["conflict_at"] = t
            st["conflict"] = "отмечено несколько вариантов — оставьте один"
        tasks = load_tasks(pantheon)

    # 4. авторазблокировка: ждала задачу, та готова → в очередь (только главный Mac: правит источники)
    for tid, (_, h, _) in (list(tasks.items()) if primary else []):
        w = h.get("waiting_on")
        if h.get("status") == "waiting" and w in tasks and tasks[w][1].get("status") == "done":
            task_set(pantheon, t, tid, {"status": "todo"}, note=f"разблокирована: {w} готова", actor="тик")
            done_lines.append(f"{tid}: разблокирована ({w} готова)")
    tasks = load_tasks(pantheon)

    # 5. застрявшие и просроченные — одна тревога на задачу (вам — в утренней сводке)
    for tid, (_, h, _) in (tasks.items() if primary else []):
        if h.get("status") == "doing" and (h.get("updated") or "") < now_iso(t - 3 * 86400):
            alert(f"stale-{tid}", h.get("updated"), f"задача застряла: {h.get('title')} ({tid}) — в работе без движения с {h.get('updated', '')[:10]}", "board")
        if overdue(h, t):
            alert(f"overdue-{tid}", h["due"], f"просрочена: {h.get('title')} ({tid}), срок {h['due']}", "board")

    # 5а. решения «Нужен ответ» — циклы политики уведомлений: ответ, истекло, закрыто, «долго ждёт»
    long_ids = set()
    if policy is not None:
        decs = []
        for tid, (_, h, _) in tasks.items():
            if h.get("status") == "waiting" and h.get("waiting_on") == "human" and _live(h, t):
                q = hashlib.sha256(_question_key(h.get("question")).encode("utf-8")).hexdigest()[:12]
                decs.append({"id": tid, "sig": f"{h.get('question_at') or ''}|{q}", "since": ts_of(h.get("question_at")),
                             "due": due_ts(h.get("due")), "due_text": due_text(h.get("due")),
                             "title": one_line(h.get("title") or tid)[:120], "recommend": h.get("recommend")})
        long_ids = policy.decisions(decs)

    # 6. перерисовать карточки: задачи и заявки направлений
    names, items = {}, []
    notes_by_id = owner_notes_all(log_path)
    answers_by_id = owner_answers_all(log_path)
    roles = Roles(list(projects) + [d for d in list_dir(os.path.join(pantheon, "directions")) if DIRECTION_RE.fullmatch(d)])
    slugs = {}  # id карточки → слаг «Кому»
    for tid, (p, h, b) in sorted(tasks.items()):
        if _live(h, t):
            items.append((tid, card_name(h), p, h, b))
            slugs[tid] = assignee(h)
    for cid, it in inbox.items():
        items.append((cid, card_name({"title": it["title"], "id": cid}, with_id=False), it["path"], None, None))
        slugs[cid] = it["direction"]
    for cid, name, src, h, b in items:
        if name.casefold() in {x.casefold() for x in names.values()}:  # Mac: «Bob.md» и «bob.md» — один файл
            name = f"{name} ({cid})"
        names[cid] = name
        st = cards.setdefault(cid, {})
        if st.get("conflict") and t - st.get("conflict_at", t) > 86400:
            st.pop("conflict", None)
            st.pop("conflict_at", None)
        who = roles.name(slugs[cid])
        if h is None:
            card, cbody = render_inbox_card(inbox[cid], projects.get(inbox[cid]["direction"]), st.get("conflict"), who)
        else:
            logged = logged_for(h, answers_by_id.get(cid))
            forged = answer_conflict(h, logged, answers_by_id.get(cid))
            if forged:
                alert(f"answer-mismatch-{cid}", str(h.get("requested") if h.get("risky") is True else h.get("answer")),
                      f"конфликт ответа: {h.get('title')} ({cid}) — {forged}", "board")
            card, cbody = render_card(h, b, rel(src), t, " · ".join(x for x in (st.get("conflict"), forged) if x) or None,
                                      notes_by_id.get(cid), logged, who, long_wait=cid in long_ids)
        target = os.path.join(board, name + ".md")
        old = present.get(cid)
        if old and (digest(old[0]) != seen.get(cid) or cid in typing):
            continue  # владелец правит карточку прямо сейчас — следующий проход
        try:  # одна битая задача не останавливает проход: тревога, остальные карточки пишутся
            if old and old[0] != target:
                os.remove(old[0])  # задачу переименовали
            new_text = join(card, cbody, CARD_ORDER)
            cur = ""
            if os.path.exists(target):
                with open(target, encoding="utf-8") as fh:
                    cur = fh.read()
            if cur != new_text:
                write(target, card, cbody, CARD_ORDER)
        except (OSError, ValueError, UnicodeError) as e:
            alert(f"board-card-{cid}", type(e).__name__, f"доска: карточку {cid} не записать ({e}) — пропущена", "board")
            continue
        st.update({"file": name, "synced": card["Статус"], "src_hash": digest(src), "card_hash": digest(target),
                   "rendered": cbody})
    # карточки ушедших задач и разобранных заявок
    for cid, (p, _, _) in present.items():
        if cid not in names:
            st = cards.get(cid, {})
            if digest(p) == st.get("card_hash"):
                os.remove(p)
                cards.pop(cid, None)
    for cid in list(cards):
        if cid not in names and cid not in present:
            cards.pop(cid, None)

    _sync_nodes(board, state, roles, tasks, names, slugs, alert)

    # 7. уведомления (политика: утренний дайджест, пинги по решениям), сводка, вид
    _, rows = _summary(tasks, t, inbox, names, long_ids)
    if policy is not None:
        # digest_day прежнего board.json (до 0.9.30) — политике: в день обновления второго утреннего не будет
        policy.run((len(rows["wait"]), len(rows["overdue"]), len(rows["inbox"])),
                   lambda tid: card_url(vault, names.get(tid, "Сводка")), card_url(vault, "Сводка"),
                   legacy_digest_day=state.pop("digest_day", None))
    text, rows = _summary(tasks, t, inbox, names, long_ids, policy.queue_view() if policy is not None else None)
    sp = os.path.join(board, "Сводка.md")
    old = open(sp, encoding="utf-8").read() if os.path.exists(sp) else ""
    if old != text:
        with open(sp, "w", encoding="utf-8") as fh:
            fh.write(text)
    _sync_base(board, state, state_path, t, alert)
    _sync_types(os.path.dirname(os.path.abspath(board)), alert)
    new_state = json.dumps(state, ensure_ascii=False, indent=1)
    try:
        with open(state_path, encoding="utf-8") as fh:
            same = fh.read() == new_state
    except OSError:
        same = False
    if not same:  # без изменений не пишем: тик идёт каждую минуту
        tmp = f"{state_path}.{os.getpid()}"
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(new_state)
        os.replace(tmp, state_path)
    return done_lines
