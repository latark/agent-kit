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
HUMAN_WAIT = "Ждёт вас"
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
    "stage": ("str", False), "priority": ("int", False), "due": ("date", False), "next": ("str", False),
    "waiting_on": ("str", False), "depends_on": ("list", False), "claimed_by": ("str", False),
    "claimed_until": ("datetime", False), "parent": ("str", False), "result": ("str", False),
    "question": ("str", False), "options": ("list", False), "answer": ("str", False),
    "risky": ("bool", False), "requested": ("str", False),
    # этап и проект
    "goal": ("str", False), "start": ("date", False), "exit_criteria": ("list", False), "repo_path": ("str", False),
    "health": ("str", False), "review_on": ("date", False),
}
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
        tmp = f".{name}.{os.getpid()}.tmp"
        f = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644, dir_fd=fd)
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
    with _in_dir(path) as (fd, name):
        f = os.open(name if fd is not None else path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=fd)
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
        if st in ("doing", "waiting") and not head.get("next"):
            warns.append(f"при {st} нужно поле next — следующий шаг")
        if st == "waiting" and not head.get("waiting_on"):
            errs.append("при waiting нужно поле waiting_on (human, id задачи или кто/что)")
        p = head.get("priority")
        if isinstance(p, int) and p not in PRIORITY:
            errs.append("priority — 0 (срочно) … 3 (низкий)")
        if head.get("options") and not head.get("question"):
            warns.append("options без question")
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


def task_new(pantheon, t, direction, title, project=None, actor="агент", **fields):
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
    errs, _ = check_head(head)
    if errs:
        remove(path)
        raise ValueError("; ".join(errs))
    write(path, head, f"\n# {title.strip()}\n\n## Журнал\n\n- {now_iso(t)[:16].replace('T', ' ')} — {actor}: создана\n")
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
    for k, v in changes.items():
        if k not in FIELDS or k in ("type", "id", "created", "schema_version"):
            raise ValueError(f"поле {k} так не меняется")
        head[k] = v
    if head.get("status") != "waiting":
        head["waiting_on"] = None
    if head.get("status") in ("done", "dropped"):
        head["question"], head["options"], head["requested"] = None, None, None
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

CARD_ORDER = ["Статус", "Проект", "Внимание", "Приоритет", "Срок", "Кто", "Дальше", "Ждёт", "Заметка агенту", "id"]
NOTE_KEY = "Заметка агенту"
QUIET = 30  # с: новую карточку берём, когда у неё есть название и её столько не меняли (ответ и заметка — сразу)
UNTITLED = ("Без названия", "Untitled")
PROJECT_MARK = {"Пантеон": "⬛", "BrokerAssistant": "🟦", "alexbroker": "🟧", "MorphStream": "🟪", "expert-corpus": "🟫",
                "legal-watch": "🟫", "content-machine": "🟩", "second-brain": "🟨", "входящие": "📥"}
STATUS_MARK = {"Входящие": "📥", HUMAN_WAIT: "🔴", "Очередь": "⚪", "В работе": "🟡", "Ждёт": "⏸",
               "На проверке": "🔵", "Готово": "🟢", "Отменено": "⚫"}
PRIORITY_MARK = {0: "🔥🔥 срочно", 1: "🔥 высокий", 2: "обычный", 3: "▫️ низкий"}
CALLOUT = {HUMAN_WAIT: "danger", "В работе": "warning", "Готово": "success", "На проверке": "info", "Ждёт": "quote",
           "Отменено": "quote", "Входящие": "note", "Очередь": "note"}


def label_of(head):
    st = head.get("status")
    if st == "waiting" and head.get("waiting_on") == "human":
        return HUMAN_WAIT
    return LABELS.get(st, st)


def card_name(head):
    name = str(head.get("title") or head.get("id")).replace(":", "꞉").replace("/", "⁄")  # похожие знаки, допустимые в имени
    name = re.sub(r'[\\*?"<>|#^\[\]]', "·", name)[:90].strip()
    return name or str(head.get("id"))


def attention(head, t, conflict=None):
    """Значки «Внимание» — их считает тик, формулам Bases не доверяем."""
    out, today = [], now_iso(t)[:10]
    if conflict:
        out.append("⚠ конфликт")
    if head.get("risky") is True and head.get("requested"):
        out.append("⚠ подтвердите словом")
    elif head.get("question") and head.get("status") == "waiting" and head.get("waiting_on") == "human":
        out.append("❓ вопрос к вам")
    due = head.get("due")
    if due and head.get("status") not in ("done", "dropped"):
        if due < today:
            out.append("🔴 просрочено")
        elif due <= now_iso(t + 3 * 86400)[:10]:
            out.append("🟠 скоро")
    return " ".join(out) or None


def render_card(head, body, src_rel, t, conflict=None):
    lab = label_of(head)
    proj = head.get("project") or ""
    prio = head.get("priority")
    card = {"Статус": lab, "Проект": f"{PROJECT_MARK.get(proj, '▪️')} {proj}".strip(), "Внимание": attention(head, t, conflict),
            "Приоритет": PRIORITY_MARK.get(prio) if prio is not None else None, "Срок": head.get("due"),
            "Кто": head.get("owner"), "Дальше": head.get("next"),
            "Ждёт": head.get("waiting_on") if head.get("waiting_on") not in (None, "human") else None,
            NOTE_KEY: "", "id": head.get("id")}
    due = f" · 📅 {head['due'][8:10]}.{head['due'][5:7]}" if head.get("due") else ""
    who = f" · 👤 {head['owner']}" if head.get("owner") else ""
    parts = [f"> [!{CALLOUT.get(lab, 'note')}] {STATUS_MARK.get(lab, '')} {lab} · {card['Проект']}{who}{due}"
             + (f" · {card['Приоритет']}" if prio in (0, 1) else "")]
    if head.get("next"):
        parts[-1] += f"\n> **Дальше:** {head['next']}"
    if head.get("waiting_on") not in (None, "human"):
        parts[-1] += f"\n> **Ждёт:** {head['waiting_on']}"
    if conflict:
        parts.append(f"> [!warning] {conflict}")
    if head.get("question"):
        risky = head.get("risky") is True
        parts.append("## ❓ Вопрос к вам" + (" · ⚠ рискованно" if risky else "") + "\n\n" + head["question"].strip())
        opts = head.get("options") or []
        cur = head.get("requested") if risky else head.get("answer")
        if opts:
            hint = ("Отметьте вариант — это только ваш выбор: действие начнётся после подтверждения словом в окне Зевса."
                    if risky else "Отметьте один вариант — агент получит ответ в течение минуты. Передумали — снимите "
                                  "галочку и отметьте другой, пока задача не закрыта.")
            parts.append(hint + "\n\n" + "\n".join(f"- [{'x' if o == cur else ' '}] {o}" for o in opts))
        if risky and head.get("requested"):
            parts.append(f"> [!warning] Вы выбрали «{head['requested']}». Подтвердите словом в окне Зевса: "
                         f"«да, {head['requested']}» — без этого агент не начнёт.")
    if head.get("answer") and not head.get("question"):
        parts.append(f"**Ваш ответ:** {head['answer']}")
    m = re.search(r"## Журнал\n(.*)$", body, re.S)
    if m:
        log = [x for x in m.group(1).strip().split("\n") if x.startswith("- ")][-5:]
        if log:
            parts.append("## Последнее\n\n" + "\n".join(log))
    # без отметки времени: иначе тик переписывал бы каждую карточку каждую минуту, а Obsidian перечитывал бы доску
    parts.append("✍️ Написать агенту — поле «Заметка агенту» вверху. Перенести — перетащите карточку на доске.\n\n"
                 f"<small>Источник: `{src_rel}` · задача обновлена {str(head.get('updated') or '')[:16].replace('T', ' ')}</small>")
    return card, "\n" + "\n\n".join(parts) + "\n"


def checked_option(body):
    m = re.findall(r"^- \[[xXхХ]\] (.+)$", body, re.M)
    return m[0].strip() if len(m) == 1 else (None if not m else "?")


BASE_FILE = """filters:
  and:
    - file.inFolder("Доска")
    - file.name != "Сводка"
    - file.name != "Проблемы"
properties:
  file.name:
    displayName: Задача
views:
  - type: kanban
    name: Доска
    groupBy:
      property: note.Статус
      direction: ASC
    groupOrder: [Входящие, Ждёт вас, Очередь, В работе, Ждёт, На проверке, Готово]
    order: [file.name, note.Проект, note.Внимание, note.Приоритет, note.Срок, note.Кто]
  - type: table
    name: Ждёт вас
    filters:
      and:
        - 'note["Статус"] == "Ждёт вас"'
    order: [file.name, note.Проект, note.Внимание, note.Дальше, note.Срок]
  - type: table
    name: Все задачи
    groupBy:
      property: note.Проект
      direction: ASC
    order: [file.name, note.Статус, note.Внимание, note.Приоритет, note.Кто, note.Срок, note.Дальше]
"""


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
    return re.sub(r"[\[\]|<>`]", "·", str(text or ""))


def _summary(tasks, t, inbox=None):
    today = now_iso(t)[:10]
    rows = {"wait": [], "overdue": [], "doing": [], "done": [],
            "inbox": [f"[[Доска/{card_name({'title': it['title']})}|{_plain(it['title'])}]] · {it['direction']}"
                      for it in (inbox or {}).values()]}
    for tid, (p, h, _) in sorted(tasks.items()):
        name = f"[[Доска/{card_name(h)}|{_plain(h.get('title'))}]] · {_plain(h.get('project'))}"
        if h.get("status") == "waiting" and h.get("waiting_on") == "human":
            rows["wait"].append(name)
        if h.get("due") and h["due"] < today and h.get("status") not in ("done", "dropped"):
            rows["overdue"].append(f"{name} · срок {h['due']}")
        if h.get("status") == "doing":
            rows["doing"].append(f"{name} · {h.get('owner') or '—'}")
        if h.get("status") == "done" and (h.get("updated") or "") >= now_iso(t - 86400):
            rows["done"].append(name)
    sec = lambda title, xs: f"## {title} ({len(xs)})\n\n" + ("\n".join(f"- {x}" for x in xs) if xs else "—") + "\n"
    return ("# Сводка\n\n" + sec("🔴 Ждёт вас", rows["wait"]) + "\n" + sec("⏰ Просрочено", rows["overdue"]) + "\n"
            + sec("📥 Входящие заявки направлениям", rows["inbox"]) + "\n"
            + sec("🟡 В работе", rows["doing"]) + "\n" + sec("🟢 Готово за сутки", rows["done"])), rows


QUIET_HOURS = (23, 8)  # ночью сразу не уведомляем: всё попадёт в утреннюю сводку


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


def render_inbox_card(item, project, conflict=None):
    proj = project or item["direction"]
    card = {"Статус": "Входящие", "Проект": f"{PROJECT_MARK.get(proj, '▪️')} {proj}".strip(),
            "Внимание": "⚠ конфликт" if conflict else "📥 заявка направлению", "Кто": item["direction"],
            "Дальше": "разобрать: в «Очередь» — станет задачей направления, в «Отменено» — в архив",
            NOTE_KEY: "", "id": item["id"]}
    body = re.sub(r"^# .+\n", "", item["text"], count=1, flags=re.M)
    body = re.sub(r"^От: .+\n", "", body, count=1, flags=re.M).strip()
    lines = body.split("\n")
    short = "\n".join(lines[:30]) + ("\n\n…" if len(lines) > 30 else "")
    parts = [f"> [!note] 📥 Входящие · {card['Проект']} · 👤 {item['direction']}"
             + (f"\n> **От:** {item['from']}" if item.get("from") else "")]
    if conflict:
        parts.append(f"> [!warning] {conflict}")
    parts.append(short)
    rel = f"directions/{item['direction']}/inbox/{item['file']}"
    parts.append("✍️ Перенесите в «Очередь» — заявка станет задачей направления; в «Отменено» — уйдёт в архив входящих.\n\n"
                 f"<small>Источник: `{rel}`</small>")
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


def board_sync(pantheon, board, state_path, log_path, t, alert=None, notify=None, primary=True, projects=None):
    """Один проход доски. → список строк «что сделано» (для журнала тика)."""
    alert = alert or (lambda *a, **k: None)
    notify = notify or (lambda *a, **k: None)
    projects = projects or {}
    vault = os.path.basename(os.path.dirname(os.path.abspath(board)))
    done_lines, events, moved_by_owner = [], [], set()
    os.makedirs(board, exist_ok=True)
    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    first_run = "cards" not in state
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
    for cid, (p, head, body) in present.items():
        st = cards.get(cid)
        if not st or digest(p) == st.get("card_hash"):
            continue  # карточку никто не трогал
        want = head.get("Статус")
        note = head.get(NOTE_KEY) if isinstance(head.get(NOTE_KEY), str) and head.get(NOTE_KEY).strip() else None
        if cid in inbox:  # заявка направлению
            it = inbox[cid]
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
        src_moved = digest(src_path) != st.get("src_hash")
        answer = checked_option(body) if src_head.get("options") else None
        if want != st.get("synced"):
            if src_moved:
                st["conflict_at"] = t
                st["conflict"] = f"пока вы переносили карточку в «{want}», агент изменил задачу — статус сейчас «{label_of(src_head)}». Перенесите ещё раз, если нужно."
                done_lines.append(f"{cid}: конфликт — ход «{want}» не применён")
                events.append((f"⚠ Перенос не применён: {src_head.get('title')}", cid))
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
                    task_set(pantheon, t, cid, ch, note=f"перенёс «{st.get('synced')}» → «{want}»", actor="владелец")
                    _owner_log(log_path, t, kind="move", id=cid, src=st.get("synced"), dst=want)
                    done_lines.append(f"{cid}: ход владельца «{st.get('synced')}» → «{want}»")
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
            task_set(pantheon, t, cid, {}, note=note.strip()[:1000], actor="владелец")
            _owner_log(log_path, t, kind="note", id=cid, text=note.strip()[:1000])
            done_lines.append(f"{cid}: заметка владельца передана")
        risky = src_head.get("risky") is True
        current = src_head.get("requested") if risky else src_head.get("answer")
        if answer and answer != "?" and answer != current:
            if risky:  # согласие на рискованное — только словом в окне Зевса; галочка — лишь выбор
                task_set(pantheon, t, cid, {"requested": answer},
                         note=f"выбрал «{answer}» — нужно подтверждение словом в окне Зевса", actor="владелец")
                _owner_log(log_path, t, kind="request", id=cid, answer=answer)
                done_lines.append(f"{cid}: выбор владельца «{answer}» по рискованному — ждёт подтверждения словом")
            else:
                ch = {"answer": answer}
                if src_head.get("status") == "waiting" and src_head.get("waiting_on") == "human":
                    ch["status"] = "todo"
                task_set(pantheon, t, cid, ch, note=f"ответ: {answer}" + (f" (был «{current}»)" if current else ""),
                         actor="владелец")
                _owner_log(log_path, t, kind="answer", id=cid, answer=answer)
                done_lines.append(f"{cid}: ответ владельца «{answer}»")
            moved_by_owner.add(cid)
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
    today = now_iso(t)[:10]
    for tid, (_, h, _) in (tasks.items() if primary else []):
        if h.get("status") == "doing" and (h.get("updated") or "") < now_iso(t - 3 * 86400):
            alert(f"stale-{tid}", h.get("updated"), f"задача застряла: {h.get('title')} ({tid}) — в работе без движения с {h.get('updated', '')[:10]}", "board")
        if h.get("due") and h["due"] < today and h.get("status") not in ("done", "dropped"):
            alert(f"overdue-{tid}", h["due"], f"просрочена: {h.get('title')} ({tid}), срок {h['due']}", "board")

    # 6. перерисовать карточки: задачи и заявки направлений
    names, items = {}, []
    for tid, (p, h, b) in sorted(tasks.items()):
        if _live(h, t):
            items.append((tid, card_name(h), p, h, b))
    for cid, it in inbox.items():
        items.append((cid, card_name({"title": it["title"], "id": cid}), it["path"], None, None))
    for cid, name, src, h, b in items:
        if name in names.values():
            name = f"{name} ({cid})"
        names[cid] = name
        st = cards.setdefault(cid, {})
        if st.get("conflict") and t - st.get("conflict_at", t) > 86400:
            st.pop("conflict", None)
            st.pop("conflict_at", None)
        if h is None:
            card, cbody = render_inbox_card(inbox[cid], projects.get(inbox[cid]["direction"]), st.get("conflict"))
        else:
            card, cbody = render_card(h, b, rel(src), t, st.get("conflict"))
        target = os.path.join(board, name + ".md")
        old = present.get(cid)
        if old and digest(old[0]) != seen.get(cid):
            continue  # владелец правит карточку прямо сейчас — следующий проход
        if old and old[0] != target:
            os.remove(old[0])  # задачу переименовали
        new_text = join(card, cbody, CARD_ORDER)
        cur = ""
        if os.path.exists(target):
            with open(target, encoding="utf-8") as fh:
                cur = fh.read()
        if cur != new_text:
            write(target, card, cbody, CARD_ORDER)
        prev = st.get("synced")
        if (card["Статус"] == HUMAN_WAIT and prev != HUMAN_WAIT and not first_run and cid not in moved_by_owner):
            events.append((f"❓ Вопрос к вам: {h.get('title') if h else name}", cid))
        st.update({"file": name, "synced": card["Статус"], "src_hash": digest(src), "card_hash": digest(target)})
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

    # 7. сводка, уведомления, вид
    text, rows = _summary(tasks, t, inbox)
    sp = os.path.join(board, "Сводка.md")
    old = open(sp, encoding="utf-8").read() if os.path.exists(sp) else ""
    if old != text:
        with open(sp, "w", encoding="utf-8") as fh:
            fh.write(text)
    hour = datetime.fromtimestamp(t).hour
    night = hour >= QUIET_HOURS[0] or hour < QUIET_HOURS[1]
    if hour >= QUIET_HOURS[1] and state.get("digest_day") != today:
        state["digest_day"] = today
        if rows["wait"] or rows["overdue"] or rows["inbox"]:
            notify(f"Доброе утро. Ждёт вас: {len(rows['wait'])}, просрочено: {len(rows['overdue'])}, "
                   f"входящих заявок: {len(rows['inbox'])}.", card_url(vault, "Сводка"))
    elif events and not night:
        if len(events) == 1:
            notify(events[0][0], card_url(vault, names.get(events[0][1], "Сводка")))
        else:
            notify(f"На доске {len(events)} новых события: " + "; ".join(e[0] for e in events[:3]),
                   card_url(vault, "Сводка"))
    bp = os.path.join(board, "Доска.base")
    if not os.path.exists(bp):
        with open(bp, "w", encoding="utf-8") as fh:
            fh.write(BASE_FILE)
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
