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
import unicodedata
from datetime import datetime

SCHEMA_VERSION = 1
TYPES = ("task", "stage", "project", "story")
# что идёт на доску и меняется командой pantheon task: задачи и пачки (story, metis-0069)
WORK_TYPES = ("task", "story")
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
    # кто пишет код задачи (решение 175, metis-0166 вариант А): auto — правило лида по набору `pantheon executors`
    "executor": ("str", False),
    # ночной цикл (metis-0129): пачка, на какую ночь запланирована, оценка и факт расхода, итог приёмки.
    # release — выпуск, с которым изменение поставлено («pantheon 0.11.37»), пишет служебная роль при установке
    # (metis-0069: вместо прежнего числа wave; старое wave читается как release — LEGACY_KEYS)
    "release": ("str", False), "batch": ("str", False), "night": ("date", False), "estimate": ("str", False),
    "actual": ("str", False), "acceptance": ("str", False),
    # режим работы и области (план metis-0248, шаг 1): mode — заявка координатора, touches — файлы или папки задачи
    "mode": ("str", False), "mode_why": ("str", False), "touches": ("list", False),
    # место задачи в пачке (metis-0069, перенос batch): меньше — раньше; без него — по зависимостям и приоритету
    "order": ("int", False),
}
# прежние ключи шапки → нынешние: читаются при разборе, при записи уходят под новым именем
LEGACY_KEYS = {"wave": "release"}
# режим: сам координатор, один исполнитель на цепочку, параллельно; пусто — как single
MODES = {"self": "сам", "single": "один исполнитель", "parallel": "параллельно"}
EXECUTORS = ("auto", "claude", "codex")
# итог приёмки утром: как у приоритета — значение из перечня, иное — ошибка шапки
ACCEPTANCE = ("принято", "вернуть", "к владельцу")
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
        out, cur, q, esc = [], "", None, False
        for ch in body:
            if q:
                cur += ch
                if esc:  # \" внутри "…" — экранированная кавычка, так её пишет join (json.dumps) — metis-0037
                    esc = False
                elif ch == "\\" and q == '"':
                    esc = True
                elif ch == q:
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
    for k, to in LEGACY_KEYS.items():
        if k in head:
            v = head.pop(k)
            if head.get(to) is None and v is not None:
                head[to] = str(v)
    return head, body


def _fmt(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        # элемент с запятой — в кавычках: без них список «[А, б, в]» читается как три элемента (metis-0037)
        return "[" + ", ".join(json.dumps(x, ensure_ascii=False) if isinstance(x, str) and "," in x else _fmt(x)
                               for x in v) + "]"
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


def write_task(path, head, body):
    """Файл задачи — только если шапка прочитается обратно такой же: иначе отказ, а не битый файл (metis-0037)."""
    text = join(head, body)
    try:
        back, _ = split(text)
    except HeaderError as e:
        raise ValueError(f"шапка не прочитается после записи ({e}) — файл не тронут") from e
    for k, v in head.items():
        if v not in (None, []) and back.get(k) != v:
            raise ValueError(f"поле {k} не прочитается обратно таким же — файл не тронут")
    write_text(path, text)


def digest(path):
    try:
        return hashlib.sha256(read_text(path).encode("utf-8")).hexdigest()[:16]
    except (OSError, UnicodeDecodeError, ValueError):
        return ""


# --- проверка схемы -------------------------------------------------------------

# Битый текст варианта (metis-0123): пустые скобки, обрезанная сумма («≈ )»; «$…» в athena-0005 съела оболочка).
_OPT_EMPTY = re.compile(r"\(\s*\)")
_OPT_CUT = re.compile(r"≈\s*[)\s]*(\)|$)|(?<!\d)(?<!\d\s)\$(?!\d)")  # «20$», «20 $» — валюта, не съеденная оболочкой
_OPT_RISKY = re.compile(r"[₽$€]|\bруб|деньг|оплат|платеж|платёж|списан|необратим|удал|безвозврат", re.I)


def option_warns(head):
    """Предупреждения по тексту options: пустые скобки, обрезанная сумма, «(совет)» в варианте про деньги или необратимое
    (совет — отдельным полем recommend, после вариантов). Не ошибка: задача пишется, автор видит строку."""
    out = []
    for o in head.get("options") or []:
        o = str(o)
        if _OPT_EMPTY.search(o) or _OPT_CUT.search(o):
            out.append(f"вариант «{o[:60]}» с пустыми скобками или обрезанной суммой («()», «≈ )», «$…») — "
                       "проверьте кавычки: оболочка съедает «$…», пишите сумму в одинарных кавычках")
        if "(совет)" in o.lower() and _OPT_RISKY.search(o):
            out.append(f"вариант «{o[:60]}» про деньги или необратимое помечен «(совет)» — совет пишите отдельно, "
                       "в recommend, после вариантов")
    return out

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
    if head.get("acceptance") not in (None, *ACCEPTANCE):
        errs.append(f"acceptance «{head.get('acceptance')}» — не из {', '.join(ACCEPTANCE)}")
    if head.get("id") and not ID_RE.fullmatch(str(head["id"])):
        errs.append(f"id «{head['id']}» — нужен вид «pan-0001»")
    if head.get("mode") is not None and head.get("mode") not in MODES:
        errs.append(f"mode «{head.get('mode')}» — не из {', '.join(MODES)}")
    if head.get("mode") == "parallel" and not head.get("touches"):
        warns.append("mode parallel без touches — области неизвестны, параллельно самозапуск её не отдаст")
    if t == "task":
        if not head.get("owner"):  # не ошибка: старые задачи без owner выпали бы с доски
            warns.append("нет owner (кому) — на доске будет координатор направления")
        if st in ("doing", "waiting") and not head.get("next"):
            warns.append(f"при {st} нужно поле next — следующий шаг")
        if st == "waiting" and not head.get("waiting_on"):
            errs.append("при waiting нужно поле waiting_on (human, id задачи или кто/что)")
        ex = head.get("executor")
        if ex is not None and ex not in EXECUTORS:
            errs.append(f"executor «{ex}» — не из {', '.join(EXECUTORS)}")
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
        warns.extend(option_warns(head))
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


def load_tasks(pantheon, types=("task",)):
    """id → (путь, шапка, тело) — только исправные задачи; types — какие типы брать (пачки — WORK_TYPES)."""
    out = {}
    for p in task_files(pantheon):
        try:
            head, body = read(p)
        except (HeaderError, OSError, UnicodeDecodeError):
            continue
        if head and head.get("type") in types and head.get("id") and not check_head(head)[0]:
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


def task_new(pantheon, t, direction, title, project=None, actor="агент", text=None, kind="task", **fields):
    """kind — task или story (пачка, metis-0069)."""
    if kind not in WORK_TYPES:
        raise ValueError(f"тип {kind!r} — только {', '.join(WORK_TYPES)}")
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
    head = {"type": kind, "id": tid, "title": title.strip(), "status": fields.pop("status", None) or "todo",
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
    try:
        write_task(path, head, f"\n# {title.strip()}\n\n" + (desc + "\n\n" if desc else "")
                   + f"## Журнал\n\n- {now_iso(t)[:16].replace('T', ' ')} — {actor}: создана\n")
    except ValueError:
        remove(path)  # заготовку create_excl не оставляем
        raise
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
    tasks = load_tasks(pantheon, WORK_TYPES)
    if tid not in tasks:
        raise ValueError(f"нет задачи {tid} (или её шапка не проходит проверку)")
    with dir_lock(os.path.dirname(tasks[tid][0])):
        return _task_set_locked(tasks[tid][0], t, tid, changes, note, actor, precheck)


def task_note(pantheon, t, tid, note):
    """Заметка владельца с доски: текст — в «Заметки владельца» задачи, в журнал — строка, что она пришла."""
    tasks = load_tasks(pantheon, WORK_TYPES)
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
        write_task(path, head, body)
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
    write_task(path, head, body)
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
        d = due_ts(h.get("due"))  # по времени: дата без времени (конец дня) — после даты-времени того же дня
        out.append((h.get("priority", 2), float("inf") if d is None else d, tid, h))
    return [x[2:] for x in sorted(out, key=lambda x: (x[0], x[1], x[2]))]


# --- режим, зависимости и пересечения (план metis-0248) ------------------------------

def _area(p):
    p = str(p).strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def paths_cross(a, b):
    """Две области пересекаются, если одна — та же или вложена в другую: `plugins/pantheon/` и
    `plugins/pantheon/lib/watch.py` — да, соседние папки и `plugins/pan` с `plugins/pantheon` — нет."""
    a, b = _area(a), _area(b)
    if not a or not b:
        return False
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def crossings(tasks, live=None):
    """id → отсортированный список других живых задач, у которых область пересекается с её областями.
    live(h) — что считать живой (по умолчанию — не done и не dropped); задачи без touches ни с кем не пересекаются."""
    live = live or (lambda h: h.get("status") not in ("done", "dropped"))
    items = [(tid, h.get("touches") or []) for tid, (_, h, _) in sorted(tasks.items())
             if h.get("type", "task") == "task" and live(h) and h.get("touches")]
    out = {}
    for i, (a, ta) in enumerate(items):
        for b, tb in items[i + 1:]:
            if any(paths_cross(x, y) for x in ta for y in tb):
                out.setdefault(a, []).append(b)
                out.setdefault(b, []).append(a)
    return {k: sorted(v) for k, v in out.items()}


def open_deps(head, tasks):
    """Незакрытые зависимости задачи: id из depends_on, которые не done и не dropped (нет такой задачи — тоже ждёт)."""
    return [d for d in head.get("depends_on") or []
            if d not in tasks or tasks[d][1].get("status") not in ("done", "dropped")]


def card_ctx(tid, head, tasks, names, cross):
    """Что карточке задачи нужно знать о других: незакрытые зависимости, пересечения, пачка и место в ней."""
    ctx = {"waits": open_deps(head, tasks), "cross": cross.get(tid) or []}
    sid = head.get("parent")
    if sid in tasks and tasks[sid][1].get("type") == "story":
        ctx["story"] = names.get(sid) or card_name(tasks[sid][1])
        ids = story_order(sid, tasks)
        ctx["order"] = ids.index(tid) + 1 if tid in ids else None
    return ctx


# --- пачка (story, metis-0069) ------------------------------------------------------
# Story — карточка type story: название, ночь или день (night, due), бюджет (estimate). Задачи прикрепляются полем
# parent (pantheon task attach/detach); сумма их оценок считается, а не вводится руками.

PCT_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def pct(v):
    """Оценка «0,5 % недели» → 0.5; без числа — None."""
    m = PCT_RE.search(str(v or ""))
    return float(m.group(0).replace(",", ".")) if m else None


def pct_text(x):
    """0.9 → «0,9 %»."""
    return ("%.2f" % x).rstrip("0").rstrip(".").replace(".", ",") + " %"


def story_children(sid, tasks):
    return [tid for tid, (_, h, _) in tasks.items() if h.get("parent") == sid and h.get("type") == "task"]


def _prio(h):
    p = h.get("priority")
    return p if isinstance(p, int) and not isinstance(p, bool) else 2


def _ord(h):
    o = h.get("order")
    return o if isinstance(o, int) and not isinstance(o, bool) else 10 ** 9


def story_order(sid, tasks):
    """Задачи пачки по порядку: сначала зависимости внутри пачки, при равенстве — приоритет, затем id.
    Цикл зависимостей порядок не роняет: оставшиеся идут по приоритету и id."""
    left, out = set(story_children(sid, tasks)), []
    while left:
        free = [i for i in left if not any(d in left for d in tasks[i][1].get("depends_on") or [])]
        nxt = min(free or left, key=lambda i: (_ord(tasks[i][1]), _prio(tasks[i][1]), i))
        out.append(nxt)
        left.discard(nxt)
    return out


def story_info(sid, tasks):
    """Состав пачки: порядок, сумма оценок против бюджета, закрыто, цепочка (одному исполнителю по порядку),
    параллельно, пересечения внутри пачки, задачи без областей."""
    ids = story_order(sid, tasks)
    heads = {i: tasks[i][1] for i in ids}
    ests = [pct(heads[i].get("estimate")) for i in ids]
    par = [i for i in ids if heads[i].get("mode") == "parallel"]
    cross = []
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            common = sorted({_area(x) if len(_area(x)) <= len(_area(y)) else _area(y)
                             for x in heads[a].get("touches") or [] for y in heads[b].get("touches") or []
                             if paths_cross(x, y)})
            if common:
                cross.append(f"{a} и {b}: {', '.join(common)}")
    return {"ids": ids, "sum": sum(e for e in ests if e is not None),
            "no_estimate": [i for i, e in zip(ids, ests) if e is None],
            "budget": pct(tasks[sid][1].get("estimate")) if sid in tasks else None,
            "closed": [i for i in ids if heads[i].get("status") in ("done", "dropped")],
            "chain": [i for i in ids if i not in par], "parallel": par, "cross": cross,
            "unknown": [i for i in ids if not heads[i].get("touches")]}


def over_budget(inf):
    return inf["budget"] is not None and inf["sum"] > inf["budget"] + 1e-9


def story_text(sid, tasks):
    """Состав пачки строками — для pantheon task show."""
    inf = story_info(sid, tasks)
    lines = [f"Пачка {sid}: задач {len(inf['ids'])}, закрыто {len(inf['closed'])}"]
    for n, i in enumerate(inf["ids"], 1):
        h = tasks[i][1]
        lines.append(f"{n}. {i} · {label_of(h)} · {h.get('estimate') or 'без оценки'} · "
                     f"{MODES.get(h.get('mode')) or 'режим не задан'} · {one_line(h.get('title'))}")
    lines.append(f"сумма {pct_text(inf['sum'])}"
                 + (f" из бюджета {pct_text(inf['budget'])}" if inf["budget"] is not None else " (бюджет не задан)")
                 + (" — больше бюджета" if over_budget(inf) else "")
                 + (f"; без оценки: {', '.join(inf['no_estimate'])}" if inf["no_estimate"] else ""))
    if inf["cross"]:
        lines.append("пересечения: " + "; ".join(inf["cross"]))
    return "\n".join(lines)


def task_attach(pantheon, t, tid, sid, actor="агент"):
    """Прикрепить задачу к пачке: parent у задачи и строка в журнал обеих. Была в другой пачке — переносится,
    строка и в журнал прежней. → прежняя пачка или None."""
    tasks = load_tasks(pantheon, WORK_TYPES)
    if tid not in tasks or tasks[tid][1].get("type") != "task":
        raise ValueError(f"нет задачи {tid}")
    if sid not in tasks or tasks[sid][1].get("type") != "story":
        raise ValueError(f"{sid} — не пачка: прикреплять можно только к карточке type story")
    old = tasks[tid][1].get("parent")
    if old == sid:
        raise ValueError(f"{tid} уже в пачке {sid}")
    was = f" (была в {old})" if old else ""
    task_set(pantheon, t, tid, {"parent": sid}, note=f"прикреплена к пачке {sid}{was}", actor=actor)
    task_set(pantheon, t, sid, {}, note=f"прикреплена задача {tid}{was}", actor=actor)
    if old in tasks and tasks[old][1].get("type") == "story":
        task_set(pantheon, t, old, {}, note=f"задача {tid} перенесена в {sid}", actor=actor)
    return old


def task_detach(pantheon, t, tid, actor="агент"):
    """Открепить задачу от пачки: parent снят, строка в журнал обеих. Не в пачке — понятная ошибка. → пачка."""
    tasks = load_tasks(pantheon, WORK_TYPES)
    if tid not in tasks or tasks[tid][1].get("type") != "task":
        raise ValueError(f"нет задачи {tid}")
    sid = tasks[tid][1].get("parent")
    if not sid or sid not in tasks or tasks[sid][1].get("type") != "story":
        raise ValueError(f"{tid} не прикреплена ни к одной пачке — откреплять нечего")
    task_set(pantheon, t, tid, {"parent": None, "order": None}, note=f"откреплена от пачки {sid}", actor=actor)
    task_set(pantheon, t, sid, {}, note=f"откреплена задача {tid}", actor=actor)
    return sid


BATCH_RE = re.compile(r"^\s*(.+?)\s*·\s*(.+?)\s*$")


def _place_key(place):
    """Место в ночи: числа по возрастанию, потом прочее («запас») по тексту."""
    return (0, int(place), "") if place.isdigit() else (1, 0, place)


def migrate_batches(pantheon, t, dry_run=False, actor="агент"):
    """Старое поле batch «<имя> · <место>» → story «<имя>» в том же направлении, задача прикреплена (parent), место —
    в order (число места как есть, «запас» — после всех чисел), batch убран. Повтор ничего не меняет. → строки плана."""
    tasks = load_tasks(pantheon, WORK_TYPES)
    groups = {}
    for tid, (_, h, _) in tasks.items():
        m = BATCH_RE.match(h.get("batch") or "") if h.get("type") == "task" and not h.get("parent") else None
        if m:
            groups.setdefault((h.get("direction"), m.group(1)), []).append((m.group(2), tid))
    plan = []
    for (direction, name), items in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        sid = next((i for i, (_, h, _) in sorted(tasks.items()) if h.get("type") == "story"
                    and h.get("direction") == direction and h.get("title") == name), None)
        plan.append(f"{direction}: пачка «{name}» — " + (f"есть {sid}" if sid else "создать"))
        if sid is None and not dry_run:
            sid = task_new(pantheon, t, direction, name, kind="story", actor=actor)[0]
        spare = 0
        for place, tid in sorted(items, key=lambda x: (_place_key(x[0]), x[1])):
            # порядок берётся из самого места: повтор и догон дают тот же порядок; нечисловое («запас») — после всех чисел
            if place.isdigit():
                n = int(place)
            else:
                spare += 1
                n = 10**6 + spare
            plan.append(f"  {tid}: место {place} → порядок {n}")
            if not dry_run:
                task_attach(pantheon, t, tid, sid, actor=actor)
                task_set(pantheon, t, tid, {"order": n, "batch": None}, note=f"batch «{name} · {place}» перенесён: порядок {n}",
                         actor=actor)
    return plan


def render_story_card(head, body, src_rel, t, tasks, project=None, **kw):
    """Карточка пачки: та же, что у задачи (вопрос, ответ, заметки работают так же), плюс состав, сумма оценок против
    бюджета, цепочка, параллельно, пересечения. project — имя заметки проекта на пульте: ссылка на неё нужна виду
    «Пачки проекта»."""
    names = kw.get("names") or {}
    card, text = render_card(head, body, src_rel, t, **kw)
    inf = story_info(head.get("id"), tasks)
    over = over_budget(inf)
    for k in ("Пачка", "Порядок", "Режим", "Режим почему", "Зависит от", "Области", "Пересечения"):
        card.pop(k, None)
    card.update({"Пульт": link(f"{PROJECTS_DIR}/{project}|{project}") if project else None,
                 "Когда": _date(head.get("night"), 10) or _date(head.get("due"), 10),
                 "Бюджет": head.get("estimate"),
                 "Сумма оценок": pct_text(inf["sum"]) + (" ⚠ больше бюджета" if over else ""),
                 "Закрыто": f"{len(inf['closed'])} из {len(inf['ids'])}",
                 "Цепочка": " → ".join(inf["chain"]) or None, "Параллельно": inf["parallel"] or None,
                 "Пересечения": inf["cross"] or None, "Области не указаны": inf["unknown"] or None, "Тип": "пачка"})
    summary = (f"> **Пачка:** сумма оценок {pct_text(inf['sum'])}"
               + (f" из бюджета {pct_text(inf['budget'])}" if inf["budget"] is not None else " · бюджет не задан")
               + (" · ⚠ больше бюджета" if over else "") + f" · закрыто {card['Закрыто']}"
               + (f"\n> **Цепочка одному исполнителю:** {' → '.join(inf['chain'])}" if inf["chain"] else "")
               + (f"\n> **Параллельно:** {', '.join(inf['parallel'])}" if inf["parallel"] else "")
               + (f"\n> **Пересечения по файлам:** {'; '.join(inf['cross'])}" if inf["cross"] else "")
               + (f"\n> **Области не указаны:** {', '.join(inf['unknown'])}" if inf["unknown"] else ""))
    rows = []
    for n, i in enumerate(inf["ids"], 1):
        h = tasks[i][1]
        ref = f"[[{names[i]}\\|{i}]]" if names.get(i) else i
        rows.append(f"| {n} | {ref} | {_plain(one_line(h.get('title'))).replace('|', '/')} | {label_of(h)} | "
                    f"{_plain(h.get('estimate') or '—').replace('|', '/')} | {MODES.get(h.get('mode')) or '—'} | "
                    f"{', '.join(open_deps(h, tasks)) or '—'} |")
    table = ("## Состав\n\n| № | Задача | Название | Статус | Оценка | Режим | Ждёт |\n|---|---|---|---|---|---|---|\n"
             + ("\n".join(rows) if rows else "| — | задач пока нет | | | | | |"))
    first, sep, rest = text[1:].partition("\n\n")
    return card, "\n" + first + "\n" + summary + "\n\n" + table + (sep + rest if sep else "\n")


# --- пульт проектов (вариант В, metis-0234) ---------------------------------------------
# Заметка проекта — Доска/Проекты/<проект>.md: справочник из directions.toml и счётчики по задачам. Bases не суммирует
# по связям, поэтому счётчики пишет тик — это вторая копия данных; pantheon check сверяет её с задачами (check_projects).

PROJECTS_DIR = "Проекты"
COUNTERS = ("Открыто", "В работе", "Ждёт вас", "Просрочено", "Пересечений", "Пачек")
HEALTH = {"red": ("🔴 плохо", "#d64545"), "yellow": ("🟡 риск", "#e0a800"), "green": ("🟢 норма", "#2f9e44"),
          "quiet": ("⚪ тихо", "#9e9e9e")}
PROJECT_ORDER = ["Тип", "Направление", "Значок", "Статус проекта", "Ранг", "Координатор", "Цель", "Здоровье", "Цвет",
                 "Обновлено", "Бюджет недели", *COUNTERS]


def project_counts(tasks, t, directions):
    """Счётчики проекта по задачам его направлений. Один расчёт и для тика, и для pantheon check."""
    cross = crossings(tasks)
    c = dict.fromkeys(COUNTERS, 0)
    for tid, (_, h, _) in tasks.items():
        if h.get("direction") not in directions or h.get("status") in ("done", "dropped"):
            continue
        if h.get("type") == "story":
            c["Пачек"] += 1
            continue
        if h.get("type") != "task":
            continue
        c["Открыто"] += 1
        c["В работе"] += h.get("status") == "doing"
        c["Ждёт вас"] += h.get("status") == "waiting" and h.get("waiting_on") == "human"
        c["Просрочено"] += overdue(h, t)
        c["Пересечений"] += tid in cross
    return {k: int(v) for k, v in c.items()}


def project_health(c):
    """Здоровье по счётчикам: просрочено или три и больше вопросов к вам — 🔴; вопрос или пересечение — 🟡."""
    if not c["Открыто"] and not c["Пачек"]:
        return "quiet"
    if c["Просрочено"] or c["Ждёт вас"] >= 3:
        return "red"
    if c["Ждёт вас"] or c["Пересечений"]:
        return "yellow"
    return "green"


def project_registry(dirs):
    """Записи [[direction]] реестра → {проект: {directions, mark, rank, goal, budget, status, coordinator}}.
    Проект — поле project, иначе имя направления; ранг — поле rank, иначе порядок в реестре."""
    out = {}
    for n, d in enumerate(dirs or [], 1):
        if not isinstance(d, dict) or not isinstance(d.get("name"), str) or not d["name"] or d["name"] == "inbox":
            continue
        p = one_line(d.get("project") or d["name"])
        rank = d.get("rank") if isinstance(d.get("rank"), int) and not isinstance(d.get("rank"), bool) else n
        e = out.setdefault(p, {"directions": [], "mark": d.get("mark"), "rank": rank, "goal": d.get("goal"),
                               "budget": d.get("budget"), "status": d.get("status") or "активный",
                               "coordinator": d["name"]})
        e["directions"].append(d["name"])
    return out


def project_note_name(p):
    return card_name({"title": p}, with_id=False)


def render_project_note(p, reg, tasks, t, roles=None):
    """Заметка проекта для пульта. Обновлено — последняя правка задач проекта, а не время прохода: иначе тик
    переписывал бы заметку каждую минуту."""
    c = project_counts(tasks, t, reg["directions"])
    hl, color = HEALTH[project_health(c)]
    upd = max((str(h.get("updated") or "")[:10] for _, h, _ in tasks.values() if h.get("direction") in reg["directions"]),
              default=None)
    node = (roles or Roles(reg["directions"])).name(reg["coordinator"])
    mark = project_mark(p, {p: reg.get("mark")} if reg.get("mark") else None)
    budget = reg.get("budget")
    head = {"Тип": "проект", "Направление": ", ".join(reg["directions"]), "Значок": mark,
            "Статус проекта": one_line(reg.get("status")), "Ранг": reg["rank"], "Координатор": link(node),
            "Цель": one_line(reg.get("goal")) or None, "Здоровье": hl, "Цвет": color, "Обновлено": upd or None,
            "Бюджет недели": one_line(budget) if budget not in (None, "") else None, **c}
    body = (f"\n> Заметку пишет плановый проход по `directions.toml` и задачам. Не правьте её: счётчики сверяет "
            f"`pantheon check`.\n\n# {mark} {p}\n\n**Здоровье:** {hl} · **Координатор:** {link(node)}"
            + (f" · **Цель:** {head['Цель']}" if head["Цель"] else "")
            + f"\n\nОткрыто {c['Открыто']} · в работе {c['В работе']} · ждёт вас {c['Ждёт вас']} · просрочено "
              f"{c['Просрочено']} · с пересечениями {c['Пересечений']} · пачек {c['Пачек']}\n\n"
              f"## Пачки проекта\n\n![[Пульт.base#Пачки проекта]]\n")
    return join(head, body, PROJECT_ORDER)


def check_projects(board, tasks, t, registry):
    """Сверка счётчиков заметок проектов с задачами → список расхождений. Заметка старше последней правки задач —
    тик её ещё не перерисовал, не ошибка. Просрочка зависит от времени, поэтому счётчик сверяется и на «сейчас»,
    и на время записи заметки."""
    d = os.path.join(board, PROJECTS_DIR)
    if not os.path.isdir(d):
        return []
    out = []
    newest = max((os.path.getmtime(p) for p, _, _ in tasks.values() if os.path.exists(p)), default=0)
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if not f.endswith(".md") or not os.path.isfile(p) or os.path.islink(p):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                head, _ = split(fh.read())
        except (HeaderError, OSError, UnicodeDecodeError) as e:
            out.append(f"{PROJECTS_DIR}/{f}: не читается ({e})")
            continue
        if (head or {}).get("Тип") != "проект":
            continue
        reg = next((r for pn, r in registry.items() if project_note_name(pn) == f[:-3]), None)
        if reg is None:
            continue  # проект убран из реестра — заметку уберёт тик
        mt = os.path.getmtime(p)
        if mt < newest:
            continue  # задачи менялись после записи — сверит следующий проход
        want = [project_counts(tasks, x, reg["directions"]) for x in (t, mt)]
        bad = [f"счётчик «{k}» {head.get(k)}, по задачам {want[0][k]}" for k in COUNTERS
               if all(head.get(k) != w[k] for w in want)]
        if bad:
            out.append(f"{PROJECTS_DIR}/{f}: " + "; ".join(bad))
    return out


def _sync_projects(board, state, tasks, t, registry, roles, alert):
    """Заметки проектов в Доска/Проекты/: свои (хеш в состоянии) переписывает и удаляет, чужой файл не трогает."""
    d = os.path.join(board, PROJECTS_DIR)
    old = state.get("projects") or {}
    mine = {}
    newest = max((os.path.getmtime(p) for p, _, _ in tasks.values() if os.path.exists(p)), default=0)
    for p, reg in sorted(registry.items()):
        n = project_note_name(p)
        path = os.path.join(d, n + ".md")
        text = render_project_note(p, reg, tasks, t, roles)
        try:
            cur = None
            if os.path.lexists(path):
                if os.path.islink(path) or not os.path.isfile(path):
                    raise ValueError("на месте заметки не обычный файл")
                with open(path, encoding="utf-8") as fh:
                    cur = fh.read()
            if cur is not None and cur != text and _sha(cur) != old.get(n):
                head, _ = split(cur)
                if (head or {}).get("Тип") != "проект":
                    alert(f"board-project-{_sha(n)}", _sha(cur),
                          f"доска: в Доска/{PROJECTS_DIR}/ лежит чужой файл «{n}.md» — заметка проекта не записана",
                          "board")
                    continue
            if cur != text:
                os.makedirs(d, exist_ok=True)
                _write_plain(path, text)
            elif os.path.getmtime(path) < newest:
                os.utime(path)  # счётчики те же, но сверены после правки задач — иначе check считал бы заметку старой
            mine[n] = _sha(text)
        except (OSError, ValueError, UnicodeError) as e:
            alert(f"board-project-{_sha(n)}", type(e).__name__, f"доска: заметку проекта «{n[:60]}» не записать ({e})",
                  "board")
    for n, h in old.items():
        if n in mine:
            continue
        path = os.path.join(d, n + ".md")
        try:
            with open(path, encoding="utf-8") as fh:
                if _sha(fh.read()) == h:
                    os.remove(path)
        except (OSError, UnicodeDecodeError):
            continue
    if mine or "projects" in state:
        state["projects"] = mine


PULT_FILE = """filters:
  and:
    - file.inFolder("Доска")
    - '!file.inFolder("Доска/Узлы")'
formulas:
  prio_rank: 'if(note["Приоритет"].isEmpty(), 2, number(note["Приоритет"]))'
  mode_view: 'if(note["Режим"].isEmpty(), "", if(note["Режим"] == "параллельно", "⇉ параллельно", if(note["Режим"] == "сам", "● сам", "→ один исполнитель")))'
  waits: 'if(note["Зависит от"].isEmpty(), "", "⏳ ждёт " + note["Зависит от"].join(", "))'
  cross: 'if(note["Пересечения"].isEmpty(), "", "✂ " + note["Пересечения"].join(", "))'
  areas: 'if(note["Области"].isEmpty(), "❔ не указаны", note["Области"].join(", "))'
  sum_budget: '[note["Сумма оценок"], note["Бюджет"]].filter(value.isTruthy()).join(" / ")'
properties:
  file.name:
    displayName: Карточка
  formula.sum_budget:
    displayName: Сумма / бюджет
  note.id:
    displayName: №
  formula.mode_view:
    displayName: Режим
  formula.waits:
    displayName: Ждёт задачу
  formula.cross:
    displayName: Пересечения
  formula.areas:
    displayName: Области
views:
  - type: cards
    name: Пульт
    filters:
      and:
        - 'note["Тип"] == "проект"'
    sort:
      - property: note.Ранг
        direction: ASC
    image: note.Цвет
    order:
      - file.name
      - note.Здоровье
      - note.Цель
      - note.Открыто
      - note.В работе
      - note.Ждёт вас
      - note.Просрочено
      - note.Пересечений
      - note.Пачек
      - note.Бюджет недели
      - note.Обновлено
  - type: kanban
    name: Пачки
    filters:
      and:
        - 'note["Тип"] == "пачка"'
        - 'note["Статус"] != "Отменено"'
    groupBy:
      property: note.Статус
      direction: ASC
    groupOrder:
      - Входящие
      - Нужен ответ
      - Очередь
      - В работе
      - Ждёт
      - На проверке
      - Готово
    sort:
      - property: note.Когда
        direction: ASC
      - property: formula.prio_rank
        direction: ASC
    order:
      - file.name
      - note.Закрыто
      - formula.sum_budget
      - note.Цепочка
  - type: table
    name: Пачки проекта
    filters:
      and:
        - 'note["Тип"] == "пачка"'
        - file.hasLink(this.file)
    sort:
      - property: note.Когда
        direction: DESC
    order:
      - file.name
      - note.Статус
      - note.Когда
      - note.Сумма оценок
      - note.Бюджет
      - note.Закрыто
      - note.Цепочка
      - note.Параллельно
      - note.Пересечения
  - type: table
    name: Задачи пачки
    filters:
      and:
        - 'note["Тип"] == "задача"'
        - file.hasLink(this.file)
    sort:
      - property: note.Порядок
        direction: ASC
    order:
      - note.Порядок
      - note.id
      - file.name
      - note.Статус
      - formula.mode_view
      - formula.waits
      - formula.areas
      - formula.cross
      - note.Оценка
      - note.Факт
"""
PULT_VERSION = hashlib.sha256(PULT_FILE.encode("utf-8")).hexdigest()[:12]  # сменился шаблон — тик перепишет Пульт.base


# --- доска владельца ------------------------------------------------------------

CARD_ORDER = ["Статус", "Проект", "Внимание", "Вопрос", "Приоритет", "Срок", "Кому", "Дальше", "Ждёт", "Создана", "Вопрос задан",
              "Закрыта", "Выпуск", "Пачка", "Пульт", "Ночь", "Оценка", "Факт", "Приёмка", "Порядок", "Режим", "Режим почему",
              "Зависит от", "Области", "Пересечения",
              # карточка пачки (story) и заметка проекта (пульт)
              "Когда", "Бюджет", "Сумма оценок", "Закрыто", "Цепочка", "Параллельно", "Области не указаны",
              "Тип", "id", "tags"]
# типы свойств карточек для Obsidian (.obsidian/types.json хранилища): тик ставит свои ключи, чужие не трогает
PROP_TYPES = {"Внимание": "multitext", "Приоритет": "number", "Срок": "date", "Создана": "date",
              "Вопрос задан": "datetime", "Вопрос": "text", "Закрыта": "date", "Кому": "text", "tags": "tags",
              "Выпуск": "text", "Пачка": "text", "Ночь": "date", "Оценка": "text", "Факт": "text", "Приёмка": "text",
              "Порядок": "number", "Режим": "text", "Зависит от": "multitext", "Области": "multitext",
              "Пересечения": "multitext", "Параллельно": "multitext", "Области не указаны": "multitext",
              # заметка проекта на пульте
              "Ранг": "number", "Обновлено": "date", "Открыто": "number", "В работе": "number", "Ждёт вас": "number",
              "Просрочено": "number", "Пересечений": "number", "Пачек": "number"}
NODES_DIR = "Узлы"  # заметки-узлы ролей для графа — внутри Доска: копия view-sync.sh стирает всё вне Доска и .obsidian
NOTE_KEY = "Заметка агенту"  # прежнее поле заметки: в карточку больше не рисуется, но со старых карточек ещё читается
NOTES_HEAD = "## ✍️ Ваши заметки"
NOTES_HINT = ("<small>Пишите ниже своими словами: мысли, задачи, правки. Через минуту после того, как закончите, плановый проход "
              "передаст их исполнителю — он прочитает до начала работы и ответит в журнале.</small>")
OWNER_NOTES = "## Заметки владельца"  # раздел файла задачи: сюда тик переносит текст из карточки
QUIET = 30  # с: новую карточку берём, когда у неё есть название и её столько не меняли (ответ и заметка — сразу)
UNTITLED = ("Без названия", "Untitled")
PROJECT_MARK = {"входящие": "📥"}  # встроенный; остальные значки — поле `mark` направления в directions.toml
DEFAULT_MARK = "⬜"
MARK_OK = re.compile(r"[^\s:#\"'`\[\]{}|>&*!%@,]{1,4}")  # значок попадает в YAML-шапку карточки: коротко, без разметки


def _mark_char_ok(c):
    """Управляющие (Cc), суррогаты, форматирующие (Cf — кроме ZWJ: он склеивает составные эмодзи) и несимволы
    Юникода ломают YAML-шапку или меняют порядок показа — не значок."""
    o = ord(c)
    if 0xFDD0 <= o <= 0xFDEF or (o & 0xFFFE) == 0xFFFE:
        return False
    cat = unicodedata.category(c)
    return cat not in ("Cc", "Cs") and (cat != "Cf" or c == "\u200d")


def project_mark(proj, marks=None):
    """Значок проекта: встроенный, затем из реестра (marks: проект → значок), иначе ⬜. Чужое значение — ⬜."""
    m = PROJECT_MARK.get(proj) or (marks or {}).get(proj)
    ok = isinstance(m, str) and MARK_OK.fullmatch(m) and all(_mark_char_ok(c) for c in m)
    return m if ok else DEFAULT_MARK
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
    with_id = bool(head.get("type") in WORK_TYPES and head.get("id")) if with_id is None else with_id
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
        "talos": "Талос", "clio": "Клио", "iris": "Ирида", "hestia": "Гестия"}
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


TASK_ID_RE = re.compile(r"(?<![\w\[|/.-])([a-z][a-z0-9]*-\d{4})(?![\w-])")


def link_ids(text, names, own=None):
    """Номера задач в тексте карточки (metis-0042) — ссылкой на их карточку: [[<имя карточки>|metis-0042]]. Только
    известные доске номера; внутри `кода` и уже готовых ссылок [[…]] не трогаем."""
    if not names:
        return text
    def one(m):
        tid = m.group(1)
        return f"[[{names[tid]}|{tid}]]" if tid in names and tid != own else tid
    def line(ln):
        # строки вариантов «- [ ] …» не трогаем: отмеченный вариант тик сверяет с options дословно (ревью argus 15.10)
        if re.match(r"\s*[-*+]\s*\[[ xXхХ]\]", ln):
            return ln
        parts = re.split(r"(`[^`\n]*`|\[\[[^\]\n]*\]\])", ln)
        return "".join(x if i % 2 else TASK_ID_RE.sub(one, x) for i, x in enumerate(parts))
    return "\n".join(line(ln) for ln in text.split("\n"))


def render_card(head, body, src_rel, t, conflict=None, notes=None, logged=None, who=None, long_wait=False, names=None, marks=None,
                ctx=None):
    """who — имя узла «Кому» (board_sync считает его по реестру направлений); без него — по слагу без реестра.
    long_wait — «долго ждёт» во «Внимание» (решает политика уведомлений).
    names — id → имя карточки: номера задач в тексте станут ссылками (link_ids).
    ctx — что считает тик по всем задачам: waits (незакрытые depends_on), cross (пересечения областей),
    story (имя карточки пачки) и order (место в ней)."""
    ctx = ctx or {}
    head = {k: (_one(v) if isinstance(v, str) else [_one(x) for x in v] if isinstance(v, list) else v)
            for k, v in head.items()}
    lab = label_of(head)
    proj = head.get("project") or ""
    prio = head.get("priority")
    node = who or Roles(()).name(assignee(head))
    direction = head.get("direction") or "inbox"
    closed = head.get("status") in ("done", "dropped")
    card = {"Статус": lab, "Проект": f"{project_mark(proj, marks)} {proj}".strip(),
            "Внимание": attention(head, t, conflict, long_wait),
            # «Срок» — свойство-дата Bases: только дата; время срока — в выноске карточки
            "Приоритет": prio if isinstance(prio, int) and not isinstance(prio, bool) else None,
            "Срок": _date(head.get("due"), 10),
            "Кому": link(node), "Дальше": None if closed else head.get("next"),
            "Ждёт": head.get("waiting_on") if head.get("waiting_on") not in (None, "human") else None,
            "Создана": _date(head.get("created"), 10),
            "Вопрос задан": _date(head.get("question_at"), 19) if head.get("question") else None,
            "Вопрос": _plain(head["question"]) if head.get("question") and not closed else None,
            # закрытые до 0.9.28 даты закрытия не имеют — тогда последнее изменение задачи (из её шапки)
            "Закрыта": (_date(head.get("closed"), 10) or _date(head.get("updated"), 10)) if closed else None,
            # ночной цикл (metis-0129) и выпуск (metis-0069): строки; пусто — None
            "Выпуск": head.get("release"),
            # пачка: ссылка на карточку story, к которой задача прикреплена (parent), иначе прежнее поле batch
            "Пачка": link(ctx["story"]) if ctx.get("story") else head.get("batch"), "Порядок": ctx.get("order"),
            "Ночь": _date(head.get("night"), 10), "Оценка": head.get("estimate"),
            "Факт": head.get("actual"), "Приёмка": head.get("acceptance"),
            # режим и зависимости (план metis-0248): «Зависит от» — только незакрытые depends_on, «Пересечения» —
            # живые задачи с общей областью (считает тик, overlaps)
            "Режим": MODES.get(head.get("mode")), "Режим почему": head.get("mode_why"),
            "Зависит от": ctx.get("waits") or None, "Области": head.get("touches") or None,
            "Пересечения": ctx.get("cross") or None,
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
    if not closed and card["Режим"]:
        parts[-1] += f"\n> **Режим:** {card['Режим']}" + (f" — {head['mode_why']}" if head.get("mode_why") else "")
    if not closed and card["Зависит от"]:
        parts[-1] += f"\n> **Ждёт задачу:** {', '.join(card['Зависит от'])}"
    if not closed and card["Пересечения"]:
        parts[-1] += f"\n> **Пересечения по файлам:** {', '.join(card['Пересечения'])}"
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
    parts = [link_ids(x, names, head.get("id")) for x in parts]  # до «Источника» и ваших заметок — их не трогаем
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


# Сортировка колонок вида «Доска» (metis-0172). В Bases сортировка одна на вид, а колонки — значения «Статус», поэтому
# ключи сортировки — формулы col_k1..col_k3, зависящие от статуса; все по возрастанию, убывание — минусом. Пустой «Срок»
# и пустой «Вопрос задан» — в конец (due_n, qa_n — очень большое число). Закрыта/Создана — метка времени (cr_n, cl_n).
# Ключи: u — urgency, p — prio_rank, due — Срок↑, cr — Создана↑, -cr — Создана↓, -cl — Закрыта↓, qa — Вопрос задан↑.
COLUMN_KEYS = {
    "Входящие": ("-cr", "p", "u"),
    "Нужен ответ": ("u", "p", "qa"),
    "Очередь": ("p", "due", "cr"),
    "В работе": ("u", "p", "due"),
    "Ждёт": ("u", "due", "cr"),
    "На проверке": ("u", "p", "cr"),
    "Готово": ("-cl", "p", "-cr"),
    "Отменено": ("-cl", "-cr", "0"),
}
_KEY_EXPR = {"u": "formula.urgency", "p": "formula.prio_rank", "due": "formula.due_n", "cr": "formula.cr_n",
             "-cr": "0 - formula.cr_n", "-cl": "0 - formula.cl_n", "qa": "formula.qa_n", "0": "0"}


def _col_formula(i):
    expr = "0"
    for status in reversed(list(COLUMN_KEYS)):
        expr = f'if(note["Статус"] == "{status}", {_KEY_EXPR[COLUMN_KEYS[status][i]]}, {expr})'
    return expr


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
  cr_n: 'if(note["Создана"], number(note["Создана"]), 0)'
  cl_n: 'if(note["Закрыта"], number(note["Закрыта"]), 0)'
  due_n: 'if(note["Срок"], number(note["Срок"]), 99999999999999)'
  qa_n: 'if(note["Вопрос задан"], number(note["Вопрос задан"]), 99999999999999)'
  col_k1: '{COLK1}'
  col_k2: '{COLK2}'
  col_k3: '{COLK3}'
  stage: 'if(note["Статус"] == "Нужен ответ", 0, if(note["Статус"] == "Входящие", 1, if(note["Статус"] == "На проверке", 2, if(note["Статус"] == "В работе", 3, if(note["Статус"] == "Ждёт", 4, if(note["Статус"] == "Очередь", 5, if(note["Статус"] == "Готово", 6, 7)))))))'
  status_view: 'if(note["Статус"] == "Нужен ответ", "🔴 Нужен ответ", if(note["Статус"] == "Входящие", "📥 Входящие", if(note["Статус"] == "В работе", "🟡 В работе", if(note["Статус"] == "На проверке", "🔵 На проверке", if(note["Статус"] == "Ждёт", "⏸ Ждёт", if(note["Статус"] == "Очередь", "⚪ Очередь", if(note["Статус"] == "Готово", "🟢 Готово", if(note["Статус"] == "Отменено", "⚫ Отменено", note["Статус"]))))))))'
  prio_view: 'if(note["Приоритет"].isEmpty(), "", if(number(note["Приоритет"]) == 0, "🔥🔥 0 срочно", if(number(note["Приоритет"]) == 1, "🔥 1 высокий", if(number(note["Приоритет"]) == 2, "2 обычный", "▫️ 3 низкий"))))'
  mode_view: 'if(note["Режим"].isEmpty(), "", if(note["Режим"] == "параллельно", "⇉ параллельно", if(note["Режим"] == "сам", "● сам", "→ один исполнитель")))'
  waits: 'if(note["Зависит от"].isEmpty(), "", "⏳ ждёт " + note["Зависит от"].join(", "))'
  cross: 'if(note["Пересечения"].isEmpty(), "", "✂ " + note["Пересечения"].join(", "))'
  warn: 'if(note["Режим"] == "параллельно" && note["Области"].isEmpty(), "⚠ области не указаны", if(note["Режим"] == "параллельно" && !note["Пересечения"].isEmpty(), "⚠ параллельно при общей области", if(note["Режим"] == "параллельно" && !note["Зависит от"].isEmpty(), "⚠ параллельно, но ждёт", "")))'
  attn: '[note["Внимание"], note["Срок"], formula.waits, formula.warn].filter(value.isTruthy()).join(" · ")'
  accept_view: 'if(note["Приёмка"].isEmpty(), if(note["Статус"] == "На проверке", "⏳ ждёт приёмки", ""), note["Приёмка"])'
  sum_budget: '[note["Сумма оценок"], note["Бюджет"]].filter(value.isTruthy()).join(" / ")'
properties:
  file.name:
    displayName: Задача
  formula.attn:
    displayName: Внимание
  formula.accept_view:
    displayName: Приёмка
  formula.sum_budget:
    displayName: Сумма / бюджет
  note.id:
    displayName: №
  formula.status_view:
    displayName: Статус
  formula.prio_view:
    displayName: Приоритет
  formula.mode_view:
    displayName: Режим
  formula.waits:
    displayName: Ждёт задачу
  formula.cross:
    displayName: Пересечения
  formula.warn:
    displayName: Внимание к режиму
views:
  - type: table
    name: От меня нужно
    filters:
      and:
        - or:
            - 'note["Статус"] == "Нужен ответ"'
            - 'note["Кому"].toString().contains("Владелец")'
            - 'note["Приёмка"] == "к владельцу"'
        - 'note["Статус"] != "Готово"'
        - 'note["Статус"] != "Отменено"'
    sort:
      - property: formula.urgency
        direction: ASC
      - property: formula.prio_rank
        direction: ASC
      - property: formula.qa_n
        direction: ASC
    order: [note.Вопрос, file.name, note.Проект, note.Внимание, formula.prio_view, note.Срок]
  - type: kanban
    name: Доска
    filters:
      and:
        - 'note["Тип"] != "пачка"'
        - 'note["Статус"] != "Отменено"'
        - or:
            - 'note["Тип"] != "заявка"'
            - 'note["Кому"].toString().contains("Владелец")'
        - or:
            - 'note["Статус"] != "Готово"'
            - 'note["Закрыта"] >= today() - "7d"'
    groupBy:
      property: note.Статус
      direction: ASC
    groupOrder: [Входящие, Нужен ответ, Очередь, В работе, Ждёт, На проверке, Готово]
    sort:
      - property: formula.col_k1
        direction: ASC
      - property: formula.col_k2
        direction: ASC
      - property: formula.col_k3
        direction: ASC
    order: [file.name, note.Проект, note.Кому, formula.prio_view, formula.attn]
  - type: kanban
    name: Пачки
    filters:
      and:
        - 'note["Тип"] == "пачка"'
        - or:
            - 'note["Статус"] != "Готово"'
            - 'note["Закрыта"] >= today() - "7d"'
        - 'note["Статус"] != "Отменено"'
    groupBy:
      property: note.Статус
      direction: ASC
    groupOrder: [Нужен ответ, Очередь, В работе, Ждёт, На проверке, Готово]
    sort:
      - property: note.Когда
        direction: ASC
      - property: formula.prio_rank
        direction: ASC
    order: [file.name, note.Закрыто, formula.sum_budget, note.Цепочка]
  - type: table
    name: Итоги пачек
    filters:
      and:
        - 'note["Тип"] != "пачка"'
        - '!note["Пачка"].isEmpty()'
        - or:
            - 'note["Статус"] == "На проверке"'
            - 'note["Статус"] == "Готово"'
            - '!note["Приёмка"].isEmpty()'
    groupBy:
      property: note.Пачка
      direction: ASC
    sort:
      - property: note.Порядок
        direction: ASC
      - property: formula.cl_n
        direction: DESC
    order: [note.id, file.name, formula.status_view, formula.accept_view, note.Оценка, note.Факт, formula.mode_view, note.Выпуск, note.Кому]
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
    order: [note.id, file.name, formula.status_view, formula.prio_view, note.Внимание, note.Кому, note.Срок, note.Дальше, note.Создана, note.Закрыта]
    columnSize:
      note.id: 150
"""
for _i in (1, 2, 3):
    BASE_FILE = BASE_FILE.replace("{COLK%d}" % _i, _col_formula(_i - 1))
BASE_VERSION = hashlib.sha256(BASE_FILE.encode("utf-8")).hexdigest()[:12]  # сменился шаблон — тик перепишет Доска.base
# sha256[:16] шаблонов BASE_FILE до 0.9.28 (c616683 — 0.9.27, 7be0aa5 — раньше): тогда в состоянии не было base_hash,
# и нетронутый старый файл иначе считался бы правкой владельца. Дальше то, что записал тик, помнит base_hash
OLD_BASE_HASHES = {"917c6bef26511e65", "44467393293d25f4"}

# У вида в .base своего поля описания нет (документация Obsidian Bases: у вида type, name, filters, sort, groupBy, order,
# limit, summaries), поэтому «что здесь и что вам делать» живёт тут: из этого словаря тик пишет и Сводка.md (заголовок,
# строка, встраивание вида), и Справка/Виды доски.md. pantheon check сверяет: у каждого вида BASE_FILE есть строка,
# лишних строк нет (metis-0288). Имена видов — в BASE_FILE выше; строку правят вместе с фильтром вида.
VIEW_HELP = {
    "От меня нужно": "Ждут вашего ответа или приёмки, либо адресованы вам; срочные — вверху. Что делать: ответить или "
                     "принять; готовые и отменённые не показываются.",
    "Доска": "Задачи по статусам, готовые — за 7 дней; заявки ролей друг другу здесь не показаны (они в «Все задачи»). "
             "Что делать: смотреть, что движется; сменить статус — перетащить карточку.",
    "Пачки": "Пачки (наборы задач на ночь) по статусам, с суммой оценок против бюджета; готовые — 7 дней. Что делать: "
             "следить за бюджетом и пересечениями по файлам.",
    "Итоги пачек": "Задачи из пачек, которые дошли до проверки, готовы или ждут приёмки, по пачкам. Что делать: принять "
                   "результат ночи.",
    "Все задачи": "Вообще все задачи и пачки, включая готовые, по проектам. Что делать: искать то, чего нет в других видах.",
}
HELP_DIR = "Справка"
HELP_NOTE = "Виды доски"


def base_views(text):
    """Имена видов .base в порядке меню."""
    return re.findall(r"^  - type: \w+\n    name: (.+?)\s*$", text, re.M)


def check_views(board=None, base_text=None, help_lines=None):
    """Сверка строк справки с видами Доска.base → список расхождений: у вида нет строки; строка без вида. Шаблон тика
    (BASE_FILE) и, если лежит в board, файл владельца: вид, добавленный вручную, тоже должен иметь строку."""
    help_lines = VIEW_HELP if help_lines is None else help_lines
    out = []
    sources = [("шаблон Доска.base", BASE_FILE if base_text is None else base_text)]
    if board and base_text is None:
        try:
            with open(os.path.join(board, "Доска.base"), encoding="utf-8") as fh:
                sources.append(("Доска/Доска.base", fh.read()))
        except (OSError, UnicodeDecodeError):
            pass
    for label, text in sources:
        views = base_views(text)
        out += [f"{label}: у вида «{v}» нет строки «что здесь» (VIEW_HELP)" for v in views
                if not str(help_lines.get(v) or "").strip()]
        if label.startswith("шаблон"):
            out += [f"VIEW_HELP: строка «{k}» без вида в Доска.base" for k in help_lines if k not in views]
    return out


def render_views_section(level="##"):
    return "".join(f"{level} {n}\n\n{line}\n\n![[Доска.base#{n}]]\n\n" for n, line in VIEW_HELP.items())


def render_help_note():
    body = ("\n> Заметку пишет плановый проход из `VIEW_HELP`. Не правьте её: строки сверяет `pantheon check`.\n\n"
            "# Виды доски\n\nВиды меню в Доска.base — что в каждом и что вам делать. Те же виды со встроенной таблицей "
            "лежат в сводке.\n\n" + "\n".join(f"- **{n}** — {line}" for n, line in VIEW_HELP.items()) + "\n")
    return join({"Тип": "справка"}, body, ["Тип"])


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
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)  # журнал ваших слов — только вам (COMM-10)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
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
    mine = set()  # вид «От меня нужно»: ждут ответа, адресованы Владельцу или приёмка «к владельцу»; без двойного счёта
    for tid, (p, h, _) in sorted(tasks.items()):
        if (h.get("status") == "waiting" and h.get("waiting_on") == "human") or (
                h.get("status") not in ("done", "dropped")
                and (Roles(()).name(assignee(h)) == OWNER_NODE or h.get("acceptance") == "к владельцу")):
            mine.add(tid)
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
    counters = (f"🔴 От меня нужно {len(mine)} · ⏰ Просрочено {len(rows['overdue'])} · 📥 Входящие {len(rows['inbox'])}"
                f" · 🟡 В работе {len(rows['doing'])} · 🟢 Готово за сутки {len(rows['done'])}")
    done_fold = (f"> [!success]- 🟢 Готово за сутки ({len(rows['done'])})\n"
                 + ("\n".join(f"> - {x}" for x in rows["done"]) if rows["done"] else "> —") + "\n")
    return ("# Сводка\n\n" + counters + "\n\n" + render_views_section() + "\n"
            + "Проекты и пачки — [[Пульт.base|пульт]].\n\n"
            + sec(f"🔴 {HUMAN_WAIT}", top, len(wait)) + "\n"
            + sec("⏰ Просрочено", rows["overdue"]) + "\n"
            + sec("📥 Входящие заявки направлениям", rows["inbox"]) + "\n"
            + sec("🟡 В работе", rows["doing"]) + "\n" + done_fold
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


def render_inbox_card(item, project, conflict=None, who=None, marks=None):
    proj = project or item["direction"]
    card = {"Статус": "Входящие", "Проект": f"{project_mark(proj, marks)} {proj}".strip(),
            "Внимание": ["конфликт"] if conflict else None, "Кому": link(who or Roles(()).name(item["direction"])),
            "Дальше": "разобрать: в «Очередь» — станет задачей направления, в «Отменено» — в архив",
            "Создана": _date(item["file"][:10], 10),
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
        body = ("\n> Сгенерировано плановым проходом. Не править.\n\n" + (f"Руководитель: {link(nd['parent'])}\n\n" if nd["parent"] else "")
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


def _sync_base(board, state, state_path, t, alert, fname="Доска.base", text=None, version=None, key="base",
               old_hashes=None):
    """Доска.base (и Пульт.base — fname, text, version, key): нет файла или сменилась версия шаблона — записать;
    владелец правил файл — его версию сохранить в папку состояния и одна тревога. Та же версия — не трогать:
    настройки вида владельца живут."""
    text = BASE_FILE if text is None else text
    version = BASE_VERSION if version is None else version
    old_hashes = OLD_BASE_HASHES if old_hashes is None else old_hashes
    bp = os.path.join(board, fname)
    try:
        with open(bp, "rb") as fh:
            cur = fh.read()
    except FileNotFoundError:
        cur = None
    if cur is not None and state.get(f"{key}_version") == version:
        return
    new = text.encode("utf-8")
    # нетронутый прежний шаблон (у 0.9.27 и раньше в состоянии нет base_hash) — не правка владельца
    if cur is not None and cur != new and _sha(cur) != state.get(f"{key}_hash") and _sha(cur) not in old_hashes:
        keep = os.path.join(os.path.dirname(os.path.abspath(state_path)),
                            f"board-{key}-{datetime.fromtimestamp(t).strftime('%Y%m%d-%H%M%S')}.base")
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        with open(keep, "wb") as fh:
            fh.write(cur)
        alert(f"board-{key}-{version}", version, f"{fname} обновлён, ваша версия сохранена в {keep}", "board")
    if cur != new:
        _write_plain(bp, text)
    state[f"{key}_version"], state[f"{key}_hash"] = version, _sha(new)


def _sync_help(board, state, alert):
    """Доска/Справка/Виды доски.md: свою (хеш в состоянии, Тип «справка») переписывает, чужой файл не трогает."""
    path = os.path.join(board, HELP_DIR, HELP_NOTE + ".md")
    text = render_help_note()
    try:
        cur = None
        if os.path.lexists(path):
            if os.path.islink(path) or not os.path.isfile(path):
                raise ValueError("на месте заметки не обычный файл")
            with open(path, encoding="utf-8") as fh:
                cur = fh.read()
        if cur is not None and cur != text and _sha(cur) != state.get("help"):
            head, _ = split(cur)
            if (head or {}).get("Тип") != "справка":
                alert("board-help", _sha(cur), f"доска: в Доска/{HELP_DIR}/ лежит чужой файл «{HELP_NOTE}.md» — справка "
                      "по видам не записана", "board")
                return
        if cur != text:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _write_plain(path, text)
        state["help"] = _sha(text)
    except (OSError, ValueError, UnicodeError) as e:
        alert("board-help", type(e).__name__, f"доска: справку по видам не записать ({e})", "board")


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
               policy=None, marks=None, registry=None):
    """Один проход доски. → список строк «что сделано» (для журнала тика). policy — политика уведомлений
    (lib/notify.py, её передаёт pantheon.py): решает, что показать, что отложить в сводку. Без неё — без
    уведомлений; notify — прежний параметр, не используется. registry — проекты для пульта (project_registry);
    без него — из projects и marks."""
    alert = alert or (lambda *a, **k: None)
    projects = projects or {}
    if registry is None:
        registry = project_registry([{"name": d, "project": p, "mark": (marks or {}).get(p)} for d, p in projects.items()])
    vault = os.path.basename(os.path.dirname(os.path.abspath(board)))
    done_lines, moved_by_owner = [], set()
    os.makedirs(board, exist_ok=True)
    try:
        with open(state_path, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    cards = state.setdefault("cards", {})
    tasks = load_tasks(pantheon, WORK_TYPES)
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
        tasks = load_tasks(pantheon, WORK_TYPES)

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
        tasks = load_tasks(pantheon, WORK_TYPES)

    # 4. авторазблокировка: ждала задачу, та готова → в очередь (только главный Mac: правит источники)
    for tid, (_, h, _) in (list(tasks.items()) if primary else []):
        w = h.get("waiting_on")
        if h.get("status") == "waiting" and w in tasks and tasks[w][1].get("status") == "done":
            task_set(pantheon, t, tid, {"status": "todo"}, note=f"разблокирована: {w} готова", actor="плановый проход")
            done_lines.append(f"{tid}: разблокирована ({w} готова)")
    tasks = load_tasks(pantheon, WORK_TYPES)

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
                             # срок-дата: пинги по сроку — к началу тихих часов дня срока, не ночью
                             "due_day": bool(DATE_RE.fullmatch(str(h.get("due") or ""))),
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
    cross = crossings(tasks)
    for cid, _, src, h, b in items:
        name = names[cid]
        st = cards.setdefault(cid, {})
        if st.get("conflict") and t - st.get("conflict_at", t) > 86400:
            st.pop("conflict", None)
            st.pop("conflict_at", None)
        who = roles.name(slugs[cid])
        if h is None:
            card, cbody = render_inbox_card(inbox[cid], projects.get(inbox[cid]["direction"]), st.get("conflict"), who, marks)
        else:
            logged = logged_for(h, answers_by_id.get(cid))
            forged = answer_conflict(h, logged, answers_by_id.get(cid))
            if forged:
                alert(f"answer-mismatch-{cid}", str(h.get("requested") if h.get("risky") is True else h.get("answer")),
                      f"конфликт ответа: {h.get('title')} ({cid}) — {forged}", "board")
            kw = dict(conflict=" · ".join(x for x in (st.get("conflict"), forged) if x) or None,
                      notes=notes_by_id.get(cid), logged=logged, who=who, long_wait=cid in long_ids, names=names,
                      marks=marks)
            if h.get("type") == "story":
                pn = next((project_note_name(pr) for pr, r in registry.items() if h.get("direction") in r["directions"]),
                          None)
                card, cbody = render_story_card(h, b, rel(src), t, tasks, project=pn, **kw)
            else:
                card, cbody = render_card(h, b, rel(src), t, ctx=card_ctx(cid, h, tasks, names, cross), **kw)
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
        # digest_day прежнего board.json (до 0.11.15) — политике: в день обновления второго утреннего не будет
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
    _sync_help(board, state, alert)
    _sync_base(board, state, state_path, t, alert, "Пульт.base", PULT_FILE, PULT_VERSION, "pult", ())
    _sync_projects(board, state, tasks, t, registry, roles, alert)
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
