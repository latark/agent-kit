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
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("pantheon_deferral", os.path.join(os.path.dirname(os.path.abspath(__file__)), "deferral.py"))
_deferral = _ilu.module_from_spec(_spec)  # metis-0834: отложенные вопросы; файл рядом, путь импорта под -I не нужен
_spec.loader.exec_module(_deferral)

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
# metis-0714, вариант А координатора (argus-280b): «ждёт» снимает задачу с цели окна (/goal), только если она ждёт владельца
# с вопросом или другую задачу, которая её правда держит (goal_released); блокер, названный сессией самой («agent», «ревью»), задачу в цели оставляет, как doing.
# `task set` печатает одну из двух строк, а WAITING_GOAL в lib/sessions.py велит проверяющей модели верить только ей.
GOAL_OUT = "снята с цели окна"
GOAL_IN = "остаётся в цели окна"
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
    # откуда задача взялась (metis-0502): from — одно из FROM_VALUES, source — на что ссылается («metis-0400» или путь
    # отчёта/ревью с #якорем); у остатка source — исходная задача. Старые задачи без from читаются как раньше
    "from": ("str", False), "source": ("str", False),
    # ветка и PR пачки (story, metis-0757): ставят `pantheon batch start` (branch — batch/<id>) и `pantheon batch pr`
    # (pr — «владелец/репозиторий#N», STORY_PR_RE); карточка пачки и board-auto показывают PR пачки
    "branch": ("str", False), "pr": ("str", False),
    # решение координатора у пачки (metis-0810): задачи, которые PR пачки закрыл, а в её состав (parent) они не входят —
    # «оставить вне пачки»; check о них больше не предупреждает (pantheon.batch_outside)
    "keep_outside": ("list", False),
}
# прежние ключи шапки → нынешние: читаются при разборе, при записи уходят под новым именем
LEGACY_KEYS = {"wave": "release"}
# режим: сам координатор, один исполнитель на цепочку, параллельно; пусто — как single
NO_MODE_BATCH = ("в пачку без режима нельзя: поставьте --mode self|single|parallel (и --mode-why — почему; «не решено» не годится), "
                 "режим нужен «Итогам пачек» и порядку запуска")
MODES = {"self": "сам", "single": "один исполнитель", "parallel": "параллельно"}  # значения свойства «Режим» в карточке — не менять (metis-0500)
# как режим называется на показе (таблица «Состав», строка на карточке, вид .base); ключ — mode из карточки задачи (metis-0500)
MODE_VIEW = {"self": "координатор сам", "single": "один разработчик", "parallel": "несколько разработчиков параллельно"}
MODE_UNSET = "не решено"
EXECUTORS = ("auto", "claude", "codex")
# metis-0505: «не решено» — законное значение у задачи вне пачки (ставит разовая pantheon task migrate-mode открытым
# задачам без mode); пачке и порядку запуска оно не годится — там нужен решённый режим (mode_decided)
UNDECIDED = "undecided"
MODES[UNDECIDED] = "не решено"


def mode_decided(head):
    """Режим решён: self, single или parallel. Пусто и «не решено» (undecided) — нет."""
    return head.get("mode") in MODES and head.get("mode") != UNDECIDED


# итог приёмки утром: как у приоритета — значение из перечня, иное — ошибка шапки
ACCEPTANCE = ("принято", "вернуть", "к владельцу")
# откуда взялась задача: слово владельца · отчёт · ревью · остаток (task split) · план · найдено по ходу чужой работы
FROM_VALUES = ("слово владельца", "отчёт", "ревью", "остаток", "план", "по ходу")
REST_TAG = "остаток"
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
    if any(x in ("", ".", "..") for x in parts):  # путь собран кодом, это страховка
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
_OPT_CUT = re.compile(r"≈\s*[)\s]*(\)|$)")
_OPT_DOLLAR = re.compile(r"\$(?!\d)")


def _opt_cut(o):
    """Обрезанная сумма: «≈ )» или «$» без числа ни до, ни после. «20$», «20 $», «20  $» и «20\u00a0$» — валюта, не
    съеденная оболочкой: пробелы любой длины (и неразрывные) до «$» после числа не в счёт (metis-0240)."""
    return bool(_OPT_CUT.search(o)) or any(not o[:m.start()].rstrip()[-1:].isdigit() for m in _OPT_DOLLAR.finditer(o))
_OPT_RISKY = re.compile(r"[₽$€]|\bруб|деньг|оплат|платеж|платёж|списан|необратим|удал|безвозврат", re.I)


def goal_released(head, tasks=None):
    """Уходит ли задача из цели окна (metis-0714): «ждёт» (waiting) владельца с вопросом — waiting_on=human и непустой
    question — или другую задачу, которая её правда держит. tasks — хранилище {id: (путь, шапка, тело)} из load_tasks
    (WORK_TYPES); без него «ждёт задачу» цель не отпускает. Блокер должен быть в хранилище и не done/dropped; блокер
    сам в «ждёт» держит, только если goal_released верно и для него. Цепочка идёт по посещённым: своя задача, цикл
    (c1↔c2), несуществующий id (metis-9999, чужое athena-0042) — задача в цели. Любое другое «ждёт», doing, todo — в цели."""
    head = head or {}
    tasks = tasks or {}
    seen = set()
    while head.get("status") == "waiting":
        on = str(head.get("waiting_on") or "").strip()
        if on == "human":
            return bool(str(head.get("question") or "").strip())
        seen.add(head.get("id"))
        if not ID_RE.fullmatch(on) or on in seen or on not in tasks:
            return False
        head = tasks[on][1] or {}
        if head.get("status") in ("done", "dropped") or head.get("status") not in STATUSES:
            return False
        if head.get("status") != "waiting":
            return True
    return False


def goal_state(head, tasks=None, window=None, elsewhere=None):
    """Строка цели окна по задаче на эту минуту (metis-0725, metis-0738): (снята ли, почему). Её печатает
    `pantheon task goal`, а WAITING_GOAL велит проверяющей модели цели верить свежей такой строке. Снята: закрыта
    (done, dropped), вернули во входящие, ведёт другая сессия — elsewhere(head, window) даёт owner, если задачу ведёт
    не окно window и не его команда (watch.owner_elsewhere), — или «ждёт» по goal_released. Окно не названо — owner не
    сверяется. Остальное — в цели: в работе, в очереди, на проверке, «ждёт» без основания или с закрытым блокером."""
    head = head or {}
    tasks = tasks or {}
    st = head.get("status")
    if st in ("done", "dropped"):
        return True, f"закрыта ({st})"
    o = elsewhere(head, window) if window and elsewhere else None
    if o:
        return True, f"ведёт {o}"
    if st == "inbox":
        return True, "вернули во входящие"
    if st == "waiting":
        on = str(head.get("waiting_on") or "").strip()
        if goal_released(head, tasks):
            return True, "ждёт ответа владельца на вопрос" if on == "human" else f"ждёт задачу {on}"
        if on in tasks and on != head.get("id"):
            return False, f"блокер {on} {(tasks[on][1] or {}).get('status')}"
        return False, "«ждёт» без вопроса владельцу и без задачи, которая её держит"
    return False, LABELS[st].lower() if st in LABELS else f"статус {st or 'не указан'}"


def goal_held_dependents(tid, tasks):
    """Задачи в «ждёт», чья цепочка waiting_on проходит через tid и которых цель теперь держит (metis-0714, argus-280b):
    [(id, её блокер, статус блокера)]. `task set` по tid печатает про каждую строку GOAL_IN — иначе последней строкой о
    задаче остаётся старое «снята с цели окна», хотя блокер уже done/dropped или сам ждёт без основания."""
    tasks = tasks or {}
    out = []
    for did in sorted(tasks):
        head = tasks[did][1] or {}
        if did == tid or head.get("status") != "waiting":
            continue
        on, seen = str(head.get("waiting_on") or "").strip(), {did}
        while on != tid and on in tasks and on not in seen:
            seen.add(on)
            nxt = tasks[on][1] or {}
            on = str(nxt.get("waiting_on") or "").strip() if nxt.get("status") == "waiting" else ""
        if on == tid and not goal_released(head, tasks):
            blk = str(head.get("waiting_on") or "").strip()
            out.append((did, blk, (tasks[blk][1] or {}).get("status")))
    return out

def option_warns(head):
    """Предупреждения по тексту options: пустые скобки, обрезанная сумма, «(совет)» в варианте про деньги или необратимое
    (совет — отдельным полем recommend, после вариантов). Не ошибка: задача пишется, автор видит строку."""
    out = []
    for o in head.get("options") or []:
        o = str(o)
        if not o.strip():
            out.append("пустой вариант --option \"\" — проверьте переменную в кавычках: она пуста")
            continue
        if _OPT_EMPTY.search(o) or _opt_cut(o):
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
    if head.get("from") not in (None, *FROM_VALUES):
        errs.append(f"from «{head.get('from')}» — не из {', '.join(FROM_VALUES)}")
    if head.get("source") and head.get("source") == head.get("id"):
        errs.append("source ссылается на саму задачу")
    if head.get("source") and not head.get("from"):
        errs.append("source без from — не сказано, чем является ссылка (слово владельца · отчёт · ревью · остаток · план · по ходу)")
    if head.get("pr") is not None and not STORY_PR_RE.fullmatch(str(head["pr"])):
        errs.append(f"pr «{head['pr']}» — нужен вид «владелец/репозиторий#N»")
    if head.get("branch") is not None and not BRANCH_RE.fullmatch(str(head["branch"])):
        errs.append(f"branch «{head['branch']}» — имя ветки git без пробелов, до 200 знаков")
    if head.get("mode") is not None and head.get("mode") not in MODES:
        errs.append(f"mode «{head.get('mode')}» — не из {', '.join(MODES)}")
    if head.get("mode") == "parallel" and not head.get("touches"):
        warns.append("mode parallel без touches — области неизвестны, самозапуск не проверит пересечение файлов с идущими задачами")
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


DONE_WHEN = "Готово, когда"
DONE_WHEN_HEAD = f"## {DONE_WHEN}"
DONE_WHEN_HINT = "(впишите проверяемые пункты: что должно работать и как это проверить)"
# metis-0503: правило «нельзя закрыть с неотмеченными пунктами» — только для задач, созданных с этого дня
# (старые чек-листы не вели; константой пользуется и metis-0505).
CRITERIA_FROM = "2026-10-27"
CLOSE_EXEMPT_ACTORS = ("владелец", "плановый проход", "pantheon role")  # карточки заявок и слово владельца этим правилом не режем
_DW_LINE = re.compile(rf"^\s*(?:#{{1,6}}\s*)?{DONE_WHEN}\s*:?\s*$", re.IGNORECASE)
_DW_ITEM = re.compile(r"^\s*[-*]\s*\[([ xXхХ])\]\s*(.*?)\s*$")


def _is_stub(text):
    """Текст пункта — заглушка шаблона (DONE_WHEN_HINT), с любыми пробелами внутри и по краям (metis-0711). Единственное
    место сравнения: unchecked_criteria, criteria_count, no_criteria и split узнают заглушку одинаково."""
    return " ".join(str(text).split()) == DONE_WHEN_HINT


def done_criteria(body):
    """Пункты «Готово, когда» в теле → [(отмечен, текст)]. Раздел — строка «## Готово, когда» или «Готово, когда:», дальше
    чек-лист; кончается заголовком или любой строкой не из списка. Подсказка-заглушка считается пунктом: её отсекают
    те, кто считает (_is_stub) — unchecked_criteria, criteria_count, no_criteria, split (metis-0712, metis-0711)."""
    out, on = [], False
    for ln in (body or "").split("\n"):
        if not on:
            on = bool(_DW_LINE.match(ln))
            continue
        m = _DW_ITEM.match(ln)
        if m:
            out.append((m.group(1) != " ", m.group(2)))
        elif ln.strip():
            break
    return out


def unchecked_criteria(head, body):
    """Число неотмеченных пунктов «Готово, когда»; заглушка шаблона (_is_stub, с любыми пробелами) не пункт, metis-0712;
    0 — у задач, созданных до CRITERIA_FROM. Одна функция для autoclose и `task set status=done`."""
    if str(head.get("created") or "") < CRITERIA_FROM:
        return 0
    return sum(1 for done, text in done_criteria(body) if not done and not _is_stub(text))


def done_when_section(items):
    """Раздел «## Готово, когда» с чек-листом; нет пунктов — одна подсказка вместо них."""
    items = [" ".join(str(x).split()) for x in (items or []) if str(x).strip()]
    return DONE_WHEN_HEAD + "\n\n" + "\n".join(f"- [ ] {x}" for x in (items or [DONE_WHEN_HINT])) + "\n\n"


def check_source(pantheon, tid, source):
    """source вида id задачи (ID_RE) — такая задача должна быть и не быть самой собой; путь отчёта/ревью — как есть."""
    if source and ID_RE.fullmatch(str(source)):
        if source == tid:
            raise ValueError("source ссылается на саму задачу")
        if source not in load_tasks(pantheon, WORK_TYPES):
            raise ValueError(f"source {source}: нет такой задачи")


def parent_problem(tasks, tid, par):
    """parent — только id пачки (type story), иначе карточка выпадает из всех пачек и видов (metis-0802). → текст отказа
    или None; пустой parent — None (открепить можно)."""
    if not par:
        return None
    if par == tid:
        return f"parent {par} — сама карточка"
    if par not in tasks:
        return f"parent {par}: нет такой пачки"
    kind = tasks[par][1].get("type")
    if kind != "story":
        return (f"parent {par} — не пачка (type {kind}): parent — только id карточки type story, иначе задача не видна "
                "ни в одной пачке; связь с задачей — source или depends_on")
    # цикл пачек (metis-0810, проба argus B #305): A.parent=B, B.parent=A — обе вечно doing; tid среди предков par — отказ
    path, cur = [par], tasks[par][1].get("parent")
    while cur and cur in tasks and cur not in path:
        path.append(cur)
        if cur == tid:
            return f"parent {par} замыкает пачки в цикл: {' → '.join([tid] + path)}"
        cur = tasks[cur][1].get("parent")
    return None


def keep_outside_problem(tasks, tid, ids):
    """keep_outside — только у пачки (type story) и только id задач (metis-0810). → текст отказа или None."""
    if (tasks.get(tid) or (None, {}, ""))[1].get("type") != "story":
        return "keep_outside — поле пачки (type story): задачи, оставленные вне её состава"
    bad = [i for i in ids if (tasks.get(i) or (None, {}, ""))[1].get("type") != "task"]
    return f"keep_outside: {', '.join(map(str, bad))} — не задача" if bad else None


def task_new(pantheon, t, direction, title, project=None, actor="агент", text=None, kind="task", done_when=None, created_note=None, need_story_criteria=False, **fields):
    """kind — task или story (пачка, metis-0069). done_when — пункты «Готово, когда» (metis-0502): критерии пишет автор при
    создании; раздел есть всегда, без пунктов — с подсказкой. need_story_criteria (CLI `task new`, metis-0766): story без
    проверяемого пункта — отказ, заглушка DONE_WHEN_HINT пачку не закроет."""
    if kind not in WORK_TYPES:
        raise ValueError(f"тип {kind!r} — только {', '.join(WORK_TYPES)}")
    if not DIRECTION_RE.fullmatch(str(direction)):
        raise ValueError(f"направление не по образцу: {direction!r}")
    if direction != "inbox" and not os.path.isdir(os.path.join(pantheon, "directions", direction)):
        raise ValueError(f"нет направления {direction}")
    if fields.get("depends_on"):
        check_depends(load_tasks(pantheon, WORK_TYPES), None, fields["depends_on"])  # новая задача в цикл не входит
    if fields.get("source"):
        check_source(pantheon, None, fields["source"])
    if fields.get("parent"):
        bad = parent_problem(load_tasks(pantheon, WORK_TYPES), None, fields["parent"])
        if bad:
            raise ValueError(bad)
    if done_when and (done_criteria(escape_desc(text)) or DONE_WHEN_HEAD in escape_desc(text).split("\n")):
        raise ValueError("в тексте уже есть «Готово, когда» с пунктами — пишите их либо там, либо в --done-when, не в обоих местах")
    if need_story_criteria and kind == "story" and not (
            [x for x in (done_when or []) if str(x).strip()]
            or [x for _, x in done_criteria(escape_desc(text)) if not _is_stub(x)]):
        raise ValueError("у пачки (story) нет проверяемых пунктов «Готово, когда»: добавьте --done-when \"пункт\" "
                         "(повторяемый) или раздел «## Готово, когда» с «- [ ] пункт» в --body; заглушка пачку не закроет (metis-0766)")
    project = resolve_project(pantheon, direction, project)  # metis-0323: только имя проекта из directions.toml
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
    if head.get("batch") and not mode_decided(head):
        errs.append(NO_MODE_BATCH)
    par = head.get("parent")
    if par and not mode_decided(head) and load_tasks(pantheon, WORK_TYPES).get(par, ("", {}))[1].get("type") == "story":
        errs.append(NO_MODE_BATCH)
    if errs:
        remove(path)
        raise ValueError("; ".join(errs))
    desc = escape_desc(text)
    # свой раздел — всегда, кроме случая, когда пункты уже в тексте (старый образец «Готово, когда:» со списком)
    dw = "" if done_criteria(desc) or DONE_WHEN_HEAD in desc.split("\n") else done_when_section(done_when)
    try:
        write_task(path, head, f"\n# {title.strip()}\n\n" + (desc + "\n\n" if desc else "") + dw
                   + f"## Журнал\n\n- {now_iso(t)[:16].replace('T', ' ')} — {actor}: создана"
                   + (f" — {created_note}" if created_note else "") + "\n")
    except ValueError:
        remove(path)  # заготовку create_excl не оставляем
        raise
    return tid, path


# Время в начале строки журнала, которую передал агент (--note «23:45 — сделал»): строку журнала датирует код
# (now_iso, часы системы), а своё время агента читалось бы как время записи — 05.11 оно уходило вперёд на 2 ч
# (metis-0868, п. 5). Убирается только время с разделителем после него («ЧЧ:ММ —», «ГГГГ-ММ-ДД ЧЧ:ММ:», «05.11 23:30 ·»):
# «15:00 созвон» — содержание, а не отметка, и остаётся.
NOTE_STAMP_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?|\d{1,2}\.\d{1,2}(?:\.\d{2,4})?\s+\d{1,2}:\d{2}"
                           r"|\d{1,2}:\d{2}(?::\d{2})?)\s*(?:—|–|-|:|·|\|)\s+")


def note_stamp(note):
    """→ (строка без времени в начале, снятое время или None). После снятия пусто — строка как есть."""
    m = NOTE_STAMP_RE.match(str(note or ""))
    if not m or not str(note)[m.end():].strip():
        return note, None
    return str(note)[m.end():], m.group(1)


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


def task_set(pantheon, t, tid, changes, note=None, actor="агент", precheck=None, body=None, keep_updated=False, force=None):
    """body — новый текст задачи (между заголовком «# …» и «## Журнал», «Заметки владельца» остаются; metis-0402):
    прежний заменяется, в журнал — строка «текст задачи заменён».
    keep_updated — служебная правка, не движение работы (migrate-project): прежнее updated остаётся, иначе
    доска, «Готово за сутки» и тревога «застряла» приняли бы её за работу (metis-0323).
    force — причина закрытия (done) при неотмеченных пунктах «Готово, когда»; уходит строкой в журнал (metis-0503)."""
    tasks = load_tasks(pantheon, WORK_TYPES)
    if tid not in tasks:
        raise ValueError(f"нет задачи {tid} (или её шапка не проходит проверку)")
    if changes.get("depends_on"):
        check_depends(tasks, tid, changes["depends_on"])
    if changes.get("parent"):  # прежний неверный parent не мешает другим правкам — его показывает check (metis-0802)
        bad = parent_problem(tasks, tid, changes["parent"])
        if bad:
            raise ValueError(f"{tid}: {bad}")
    # в пачку — только с решённым режимом; и снять или сделать «не решено» режим у задачи пачки нельзя (metis-0505)
    par = changes.get("parent", tasks[tid][1].get("parent")) if "parent" in changes or "mode" in changes else None
    mode = changes["mode"] if "mode" in changes else tasks[tid][1].get("mode")
    if par and tasks.get(par, ("", {}))[1].get("type") == "story" and not mode_decided({"mode": mode}):
        raise ValueError(f"{tid}: {NO_MODE_BATCH}")
    if changes.get("source"):
        check_source(pantheon, tid, changes["source"])
    if changes.get("keep_outside"):
        bad = keep_outside_problem(tasks, tid, changes["keep_outside"])
        if bad:
            raise ValueError(f"{tid}: {bad}")
    with dir_lock(os.path.dirname(tasks[tid][0])):
        return _task_set_locked(tasks[tid][0], t, tid, changes, note, actor, precheck, body, keep_updated, force,
                                pantheon)


def rest_ids(pantheon, tid):
    """id задач-остатков tid (source=tid, тег «остаток»)."""
    return [i for i, (_, h, _b) in load_tasks(pantheon, WORK_TYPES).items()
            if h.get("source") == tid and REST_TAG in (h.get("tags") or [])]


def task_split(pantheon, t, tid, title, done_when=None, text=None, actor="агент", mode=None, mode_why=None):
    """Остаток задачи tid — новой задачей одной командой (metis-0502): то же направление, проект, пачка и режим, from=остаток,
    source=tid, тег «остаток»; пункты — done_when, иначе неотмеченные пункты исходной. В журнале обеих — строка со ссылкой.
    → (id новой, путь)."""
    tasks = load_tasks(pantheon, WORK_TYPES)
    if tid not in tasks:
        raise ValueError(f"нет задачи {tid} (или её шапка не проходит проверку)")
    path0, h0, b0 = tasks[tid]
    if h0.get("type") != "task":
        raise ValueError(f"{tid} — не задача: остаток выносится только из задачи")
    folder = os.path.basename(os.path.dirname(os.path.dirname(path0)))
    if h0.get("direction") != folder:  # guard проверяет папку файла, остаток заводится по шапке: расхождение — подмена направления
        raise ValueError(f"{tid}: в шапке direction={h0.get('direction')}, а файл лежит в «{folder}» — остаток не заведён; "
                         "верните direction задачи в направление её папки")
    if not str(title or "").strip():
        raise ValueError("нужен --title: название остатка")
    items = [x for x in (done_when or []) if str(x).strip()] or [x for done, x in done_criteria(b0) if not done and not _is_stub(x)]
    fields = {k: h0[k] for k in ("owner", "parent", "mode", "mode_why", "priority", "executor") if h0.get(k) is not None}
    if parent_problem(tasks, tid, fields.get("parent")):  # неверный parent исходной в остаток не переносим (metis-0802)
        fields.pop("parent")
    fields.update({k: v for k, v in (("mode", mode), ("mode_why", mode_why)) if v})  # у исходной в пачке нет режима — задаётся здесь
    fields.update({"from": "остаток", "source": tid, "tags": sorted({*(h0.get("tags") or []), REST_TAG})})
    desc = text if text else f"Остаток задачи {tid} «{h0.get('title')}»."
    nid, p = task_new(pantheon, t, h0["direction"], title, project=h0.get("project"), actor=actor, text=desc,
                      done_when=items, created_note=f"остаток задачи {tid}", **fields)
    try:
        res = h0.get("result")  # result ссылается на остаток: по нему ручной done проходит без --force (metis-0503)
        task_set(pantheon, t, tid, {"result": f"{res}; остаток в {nid}" if res else f"остаток в {nid}"},
                 note=f"остаток вынесен в {nid}: {' '.join(str(title).split())}", actor=actor)
    except Exception:
        remove(p)  # исходная не записана — новая без пары в журнале не остаётся
        raise
    return nid, p


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


def escape_desc(text):
    """Текст задачи: строка «## …» внутри него экранируется, иначе она стала бы разделом (журналом) задачи. Исключение —
    первая строка «## Готово, когда»: это раздел критериев, он остаётся разделом (metis-0591); второй такой — экранируется."""
    out, seen = [], False
    for ln in (text or "").strip().split("\n"):
        if ln == DONE_WHEN_HEAD and not seen:
            seen = True
        elif ln.startswith("## "):
            ln = "\\" + ln
        out.append(ln)
    return "\n".join(out).strip()


def replace_desc(body, text):
    """Текст задачи между первым «# …» и «## Журнал» (или концом) заменён на text, раздел «## Заметки владельца» там же
    остаётся (metis-0402). → (новое тело, длина прежнего текста в знаках); нет заголовка — ValueError."""
    lines = body.split("\n")
    h = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), None)
    if h is None:
        raise ValueError("в задаче нет заголовка «# …» — текст некуда вставить")
    e = next((i for i in range(h + 1, len(lines)) if lines[i].startswith("## Журнал")), len(lines))
    keep, old, in_notes = [], [], False
    for ln in lines[h + 1:e]:
        if ln.startswith("## "):
            in_notes = ln.startswith(OWNER_NOTES)
        (keep if in_notes else old).append(ln)
    while keep and not keep[-1].strip():
        keep.pop()
    desc = escape_desc(text)
    new = lines[:h + 1] + [""] + ([desc, ""] if desc else []) + (keep + [""] if keep else []) + lines[e:]
    return "\n".join(new), len("\n".join(old).strip())


def _task_set_locked(path, t, tid, changes, note, actor, precheck, new_body=None, keep_updated=False, force=None, pantheon=None):
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
    # dropped → done — тоже закрытие: правило критериев действует (metis-0543 Д1); done → done его не повторяет
    if changes.get("status") == "done" and head.get("status") != "done" and actor not in CLOSE_EXEMPT_ACTORS:
        left = unchecked_criteria(head, new_body if new_body is not None else body)
        rest = rest_ids(pantheon, tid) if left and pantheon else []
        if left and force is not None and not " ".join(str(force).split()):
            raise ValueError("--force: нужна причина текстом")
        if left and force is None and not any(r in str(changes.get("result", head.get("result")) or "") for r in rest):
            raise ValueError(f"{tid}: неотмечено {left} пунктов «{DONE_WHEN}»: отметьте их или вынесите остаток "
                             "(pantheon task split), либо --force \"причина\"")
        if left and force is not None:
            note = f"закрыта с неотмеченными ({left}), --force: {' '.join(str(force).split())}" + (f"; {note}" if note else "")
    for k, v in changes.items():
        if k not in FIELDS or k in ("type", "id", "created", "schema_version"):
            raise ValueError(f"поле {k} так не меняется")
        head[k] = v
    if head.get("status") != "waiting":
        head["waiting_on"] = None
    if head.get("status") in ("done", "dropped"):
        head["question"], head["options"], head["requested"] = None, None, None
        if not was_closed and not changes.get("closed"):  # дату слияния PR тик ставит сам (metis-0308)
            head["closed"] = now_iso(t)[:10]
    elif was_closed:
        head["closed"] = None
    if not head.get("question"):
        head["question_at"] = None
    elif head.get("question") != old_q:
        head["question_at"] = now_iso(t)
    if changes.get("batch") and not mode_decided(head):
        raise ValueError(NO_MODE_BATCH)
    if not (keep_updated and head.get("updated")):
        head["updated"] = now_iso(t)
    errs, _ = check_head(head)
    if errs:
        raise ValueError("; ".join(errs))
    if new_body is not None:  # прежний текст остаётся в истории Пританея, в журнале — строка о замене (argus b)
        crit_was = [x for _, x in done_criteria(body)]
        body, was = replace_desc(body, new_body)
        body = append_log(body, f"{now_iso(t)[:16].replace('T', ' ')} — {actor}: текст задачи заменён "
                                f"(было {was} знаков, стало {len(escape_desc(new_body))})")
        crit_now = [x for _, x in done_criteria(body)]
        if crit_was != crit_now:  # критерии фиксируются при создании; правка — только с записью (metis-0502)
            body = append_log(body, f"{now_iso(t)[:16].replace('T', ' ')} — {actor}: критерии «{DONE_WHEN}» изменены "
                                    f"(было пунктов {len(crit_was)}, стало {len(crit_now)})")
    if note:
        note = note_stamp(note)[0]  # время записи — от кода, не от агента (metis-0868, п. 5)
        body = append_log(body, f"{now_iso(t)[:16].replace('T', ' ')} — {actor}: {' '.join(str(note).split())}")
    write_task(path, head, body)
    return path, head



# --- закрытие по слиянию и поля «Итогов пачек» (metis-0308) ---------------------------------------------------------
# Тик закрывает задачу при слиянии её PR (lib/autoclose.py) и пишет в журнал строку с CLOSED_BY_MERGE: по ней check
# знает, что release и actual обязаны быть. Остальное считается здесь, по всем задачам, без участия ролей.

CLOSED_BY_MERGE = "закрыта по слиянию"
NO_PR_HOURS = 24
PR_REF_RE = re.compile(r"#\d{1,6}\b|/pull/\d{1,6}\b|\bPR\s*\d{1,6}\b")
NO_PR = "review без PR"
NO_ACCEPT = "нет приёмки"


def in_pack(head, tasks=None):
    """Задача входит в пачку: прикреплена к карточке story (parent) или старое поле batch."""
    if head.get("type") != "task":
        return False
    sid = head.get("parent")
    if sid and tasks is not None:
        return sid in tasks and tasks[sid][1].get("type") == "story"
    return bool(sid or head.get("batch"))


def night_end_ts(head, tasks, night_end="08:00"):
    """Конец ночи задачи: дата вечера из night (своего, иначе пачки) → следующее утро в night_end. Нет даты — None."""
    d = head.get("night")
    if not d and head.get("parent") in (tasks or {}):
        d = tasks[head["parent"]][1].get("night")
    base = ts_of(d[:10]) if isinstance(d, str) else None
    m = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", night_end or "")
    if base is None or not m:
        return None
    return datetime.fromtimestamp(base + 86400 + 3600).replace(hour=int(m.group(1)), minute=int(m.group(2)),
                                                                 second=0, microsecond=0).timestamp()


def extra_attention(head, body, tasks, t, night_end="08:00", open_prs=None):
    """Слова «внимания» по задаче, которые видны только в целом: review больше суток без PR (open_prs — id задач с
    открытым PR из прохода автозакрытия; None — не знаем, тогда смотрим только ссылки на PR в тексте задачи) и задача
    пачки, готовая после конца своей ночи без приёмки."""
    out = []
    tid = head.get("id")
    if head.get("type") == "task" and head.get("status") == "review":
        upd = ts_of(head.get("updated"))
        if (upd is not None and t - upd > NO_PR_HOURS * 3600 and not PR_REF_RE.search(body or "")
                and not (open_prs and tid in open_prs)):
            out.append(NO_PR)
    if head.get("status") == "done" and not head.get("acceptance") and in_pack(head, tasks):
        end = night_end_ts(head, tasks, night_end)
        if end is not None and t >= end:
            out.append(NO_ACCEPT)
    return out


def board_problems(tasks, t, night_end="08:00", open_prs=None):
    """Сверка по всем задачам → (ошибки, предупреждения), каждое — (id, текст). Ошибки: задача пачки без mode;
    done без closed; закрытая по слиянию без release или actual. Предупреждения — слова extra_attention, открытая карточка
    с parent не на пачку (metis-0802) и хвосты в журнале без задачи (tail_lines)."""
    errs, warns = [], []
    for tid, (_, h, b) in sorted(tasks.items()):
        if h.get("type") == "task" and in_pack(h, tasks) and not mode_decided(h):
            errs.append((tid, "задача пачки без mode (self|single|parallel; «не решено» не годится) — поле нужно «Итогам пачек»"))
        if h.get("status") == "done" and not h.get("closed"):
            errs.append((tid, "status done без closed — дата закрытия берётся из updated"))
        if h.get("status") == "done" and CLOSED_BY_MERGE in (b or ""):
            for k in ("release", "actual"):
                if not h.get(k):
                    errs.append((tid, f"закрыта по слиянию, а поле {k} пусто — его пишет плановый проход, «Итоги пачек» без него неполны"))
        warns += [(tid, w) for w in extra_attention(h, b, tasks, t, night_end, open_prs)]
        bad = parent_problem(tasks, tid, h.get("parent")) if h.get("status") not in ("done", "dropped") else None
        if bad:  # metis-0802: задача с parent не на пачку не видна ни в одной пачке
            warns.append((tid, f"{bad}; поправить — pantheon task attach {tid} <пачка> или task set {tid} parent="))
    warns += [(tid, f"хвост в журнале без задачи: {ln}") for tid, ln in tail_lines(tasks, t)]  # metis-0504, не блок
    warns += pack_title_warns(tasks)  # metis-0505
    return errs, warns


# --- единая структура по направлениям (metis-0505) -------------------------------------
# Уровни: Проект → Цель (если в ней две и больше пачки) → Пачка → Задача; цель и пачка — обе type story. Цель — story с
# пачками внутри или с названием «Цель: …»; остальные story — пачки: «Пачка: <результат одной фразой>», без номера
# (порядок — поле order или срок). Правила названий — для story с created от CRITERIA_FROM: старые не штрафуем.
PACK_PREFIX, GOAL_PREFIX = "Пачка: ", "Цель: "
_PACK_TITLE = re.compile(r"^Пачка: (?!№?\s*\d+(?:\W|$))\S")
_NUMBERED = re.compile(r"^\s*(?:П\s*\d+|Пачка\s*№?\s*\d+)(?:\W|$)")


def is_goal(sid, tasks):
    """story — цель: в ней есть другие story (parent) или название начинается с «Цель: »."""
    h = tasks.get(sid, ("", {}, ""))[1]
    return h.get("type") == "story" and (str(h.get("title") or "").startswith(GOAL_PREFIX) or any(
        x.get("type") == "story" and x.get("parent") == sid for _, x, _ in tasks.values()))


def pack_title_warns(tasks):
    """Названия открытых пачек и целей → [(id, текст)]: новая пачка не «Пачка: <результат>» или с номером, новая цель
    с «Пачка» в названии, две открытые story одного направления с одним названием (любой давности)."""
    out, seen = [], {}
    for sid, (_, h, _) in sorted(tasks.items()):
        if h.get("type") != "story" or h.get("status") in ("done", "dropped"):
            continue
        title = " ".join(str(h.get("title") or "").split())
        key = (h.get("direction"), title.casefold())
        if key in seen:
            out.append((sid, f"то же название, что у {seen[key]}: «{title[:60]}» — назовите пачку её результатом"))
        else:
            seen[key] = sid
        if str(h.get("created") or "") < CRITERIA_FROM:
            continue
        if is_goal(sid, tasks):
            if title.startswith("Пачка") or _NUMBERED.match(title):
                out.append((sid, "цель (в ней пачки) называется «Цель: <результат>», без «Пачка» и номера"))
        elif not _PACK_TITLE.match(title):
            out.append((sid, f"название пачки «{title[:60]}» — нужно «{PACK_PREFIX}<результат одной фразой>», без номера: "
                             "порядок — поле order или срок (schema.md)"))
    return out


SUMMARY_KEYS = ("open", "no_pack", "no_criteria", "no_mode", "undecided", "rest_open")


def direction_names(pantheon, dirs=None):
    """Направления для сводки: папки directions/<имя> и записи реестра (без inbox) — и те, где задач нет."""
    d = os.path.join(pantheon, "directions")
    names = {x for x in list_dir(d) if DIRECTION_RE.fullmatch(x) and os.path.isdir(os.path.join(d, x))}
    names |= {x["name"] for x in dirs or [] if isinstance(x, dict) and isinstance(x.get("name"), str)
              and DIRECTION_RE.fullmatch(x["name"]) and x["name"] != "inbox"}
    return sorted(names)


def direction_summary(tasks, names=()):
    """Сводка по открытым задачам (type task, не done/dropped) каждого направления → {направление: счётчики SUMMARY_KEYS и
    no_mode_ids}. no_criteria — нет пунктов «Готово, когда» (одна заглушка-подсказка — тоже нет); no_mode — mode пуст;
    undecided — «не решено»; rest_open — открытые остатки (тег «остаток»). names — направления, показанные и с нулём."""
    blank = lambda: dict(dict.fromkeys(SUMMARY_KEYS, 0), no_mode_ids=[])  # noqa: E731
    out = {n: blank() for n in names}
    for tid, (_, h, b) in sorted(tasks.items()):
        if h.get("type") != "task" or h.get("status") in ("done", "dropped") or h.get("direction") == "inbox":
            continue
        c = out.setdefault(str(h.get("direction")), blank())
        c["open"] += 1
        c["no_pack"] += not in_pack(h, tasks)
        c["no_criteria"] += not [x for _, x in done_criteria(b) if not _is_stub(x)]
        if h.get("mode") in (None, ""):
            c["no_mode"] += 1
            c["no_mode_ids"].append(tid)
        c["undecided"] += h.get("mode") == UNDECIDED
        c["rest_open"] += REST_TAG in (h.get("tags") or [])
    return out


def summary_line(direction, c):
    return (f"сводка · {direction}: открытых {c['open']} · без пачки {c['no_pack']} · без «{DONE_WHEN}» {c['no_criteria']}"
            f" · без «Кто делает» {c['no_mode']} · «не решено» {c['undecided']} · остатков открытых {c['rest_open']}")


def fix_closed(pantheon, t, tasks=None):
    """done без closed → closed из updated (дата), строка в журнал. → id починенных."""
    tasks = tasks if tasks is not None else load_tasks(pantheon, WORK_TYPES)
    fixed = []
    for tid, (_, h, _) in sorted(tasks.items()):
        if h.get("status") == "done" and not h.get("closed"):
            day = str(h.get("updated") or "")[:10]
            if not DATE_RE.fullmatch(day):
                day = now_iso(t)[:10]
            task_set(pantheon, t, tid, {"closed": day}, note=f"closed {day} проставлен из updated (check: done без closed)",
                     actor="check")
            fixed.append(tid)
    return fixed


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


# --- пересечение внутри направления перед раздачей (metis-0665) ------------------------------------------------------
# plan_batch сверяет touches только с идущими задачами других направлений. Внутри направления координатор раздаёт
# задачи субагентам параллельно: 02.11 #246 и #248 правили одни файлы от одного main — у второго 20 конфликтов и лишний
# круг двух argus. Здесь — сверка с живыми задачами своего направления и с файлами открытых PR его репозиториев.
OVERLAP_LIVE = ("doing", "review")


def _common(xs, ys):
    """Общие области двух списков путей: из пересекающейся пары — более узкая (файл, а не его папка)."""
    return sorted({_area(x) if len(_area(x)) >= len(_area(y)) else _area(y) for x in xs for y in ys if paths_cross(x, y)})


def overlap_tasks(tasks, tid):
    """Живые (doing, review) задачи направления tid с пересечением touches → [(id, статус, owner, [общие области])].
    У задачи без touches — []: пересечение не проверить, об этом скажет overlap_text."""
    head = tasks[tid][1]
    mine, out = head.get("touches") or [], []
    for oid, (_, h, _) in sorted(tasks.items()):
        if oid == tid or h.get("type", "task") != "task" or h.get("direction") != head.get("direction"):
            continue
        if h.get("status") not in OVERLAP_LIVE:
            continue
        common = _common(mine, h.get("touches") or [])
        if common:
            out.append((oid, h.get("status"), h.get("owner") or "", common))
    return out


# Ветка, репозиторий и пути PR приходят из gh или кэша — чужой текст (автор PR): в готовые команды и строки вывода
# идут только по строгому шаблону. Ветка не по шаблону → «<ветка PR>» и строка «отклонено»; путь с управляющим
# знаком, переводом строки или длиннее OVERLAP_PATH_MAX — отброшен, число отброшенных — в строке PR.
OVERLAP_BRANCH_RE = re.compile(r"[A-Za-z0-9._/-]{1,200}")
OVERLAP_REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9._-]{1,100}")
OVERLAP_PATH_MAX = 400
_LINE_BREAKS = {"\x7f", "\x85", "\u2028", "\u2029"}


def overlap_name_ok(name, rx):
    """Имя ветки или репозитория для команды: целиком по шаблону, без ведущего «-» (флаг) и без «..»."""
    return isinstance(name, str) and bool(rx.fullmatch(name)) and not name.startswith("-") and ".." not in name


def overlap_path_ok(path):
    """Путь файла PR для вывода: строка до OVERLAP_PATH_MAX знаков без управляющих знаков и переводов строк."""
    return (isinstance(path, str) and 0 < len(path) <= OVERLAP_PATH_MAX
            and not any(ord(c) < 32 or c in _LINE_BREAKS for c in path))


def overlap_prs(tid, head, prs):
    """Открытые PR с файлами в областях задачи → [(pr, [общие файлы])]. prs — [{repo, number, branch, files, ids,
    closes}]; PR самой задачи (её id в ветке или теле), PR без списка файлов и с номером не числом пропускаются. pr в
    ответе — копия: branch и repo не по шаблону → None, files — только годные пути, dropped — сколько отброшено."""
    mine, out = head.get("touches") or [], []
    for pr in prs or []:
        n = pr.get("number")
        if tid in (pr.get("ids") or []) or not isinstance(pr.get("files"), list) or not isinstance(n, int) or isinstance(n, bool):
            continue
        files = [f for f in pr["files"] if overlap_path_ok(f)]
        common = sorted({_area(f) for f in files if any(paths_cross(f, m) for m in mine)})
        if common:
            out.append((dict(pr, files=files, dropped=len(pr["files"]) - len(files) + int(pr.get("dropped") or 0),
                             branch=pr.get("branch") if overlap_name_ok(pr.get("branch"), OVERLAP_BRANCH_RE) else None,
                             repo=pr.get("repo") if overlap_name_ok(pr.get("repo"), OVERLAP_REPO_RE) else None), common))
    return out


def _list(xs, n=6):
    return ", ".join(xs[:n]) + (f" и ещё {len(xs) - n}" if len(xs) > n else "")


def overlap_text(tid, head, cross_tasks, cross_prs, notes=()):
    """Предупреждение о пересечении строками (пусто — пересечений нет и сказать нечего). notes — строки о том, что не
    проверено (gh не ответил, взят кэш, репозитории не заданы): их не глушим — «не молчать». Выбор с готовыми
    командами: очередь (ждать слияния) или ветка от ветки PR (stacked PR) с argus только на дельту."""
    lines = []
    if not head.get("touches"):
        lines.append(f"у {tid} нет touches — пересечение с соседями не проверить: задай области "
                     f"(pantheon task set {tid} touches=путь,путь) и повтори pantheon task overlap {tid}")
    lines += [f"не проверено: {n}" for n in notes]
    if not cross_tasks and not cross_prs:
        return lines
    by_task = {}
    for pr, _ in cross_prs:
        for i in pr.get("ids") or []:
            by_task.setdefault(i, []).append(pr)
    lines.append(f"{tid} пересекается по файлам — это предупреждение, не запрет:")
    for oid, st, owner, common in cross_tasks:
        prs = by_task.get(oid) or []
        lines.append(f"- задача {oid} ({st}{', ' + owner if owner else ''}"
                     f"{', PR ' + ', '.join('#' + str(p.get('number')) for p in prs) if prs else ', открытого PR нет'}): {_list(common)}")
    for pr, common in cross_prs:
        ids = [i for i in pr.get("ids") or [] if i != tid]
        lines.append(f"- PR #{pr.get('number')} {pr.get('repo') or '<репозиторий>'} (ветка {pr.get('branch') or '<ветка PR>'}"
                     f"{', ' + ', '.join(ids) if ids else ''}): {_list(common)}"
                     + (f" (отброшено путей не по форме: {pr['dropped']})" if pr.get("dropped") else ""))
        if not pr.get("branch"):
            lines.append(f"  имя ветки PR #{pr.get('number')} отклонено (не по шаблону) — в командах «<ветка PR>», "
                         "возьми её из gh pr view")
        if not pr.get("repo"):
            lines.append(f"  имя репозитория PR #{pr.get('number')} отклонено (не owner/name) — в командах «<репозиторий>»")
    lines.append("Выбор — один из двух, параллельно от main не начинать:")

    def dep(*oids):  # depends_on= заменяет список: прежние зависимости остаются в команде
        return ",".join(dict.fromkeys([*(head.get("depends_on") or []), *oids]))
    for pr, _ in cross_prs:
        n, repo, br = pr.get("number"), pr.get("repo") or "<репозиторий>", pr.get("branch") or "<ветка PR>"
        lines += [f"  А — очередь: ждать слияния PR #{n}, затем начать от свежего main.",
                  f"      gh pr view {n} -R {repo} --json state,mergedAt",
                  "      git fetch origin && git switch -c " + tid + " origin/main"]
        closes = [i for i in pr.get("closes") or [] if i != tid]
        if closes:
            lines.append(f"      пока ждёт: pantheon task set {tid} status=todo depends_on={dep(closes[0])}")
        lines += [f"  Б — ветка от ветки (stacked PR): начать от ветки PR #{n}, свой PR — с базой его ветки.",
                  f"      git fetch origin && git switch -c {tid} origin/{br}",
                  f"      gh pr create -R {repo} --base {br} --title … --body-file …",
                  f"      argus — только дельта своего PR: git diff origin/{br}...HEAD",
                  f"      после слияния #{n} (--merge): gh pr edit <свой N> -R {repo} --base main — head тот же, записи "
                  "шлюза в силе; конфликт с main — git merge origin/main, не rebase",
                  f"      #{n} слит squash или rebase — «принять» на новый head не переносится: узкий круг argus на ту же дельту"]
    bare = [oid for oid, _, _, _ in cross_tasks if not by_task.get(oid)]
    if bare:
        lines += [f"  Без открытого PR: {_list(bare)} — очередь: pantheon task set {tid} status=todo depends_on={dep(*bare)}",
                  f"      или одному исполнителю по порядку; ветка от ветки — когда у задачи будет открытый PR (повтори "
                  f"pantheon task overlap {tid})"]
    return lines


def open_deps(head, tasks):
    """Незакрытые зависимости задачи: id из depends_on, которые не done и не dropped (нет такой задачи — тоже ждёт)."""
    return [d for d in head.get("depends_on") or []
            if d not in tasks or tasks[d][1].get("status") not in ("done", "dropped")]


PARALLEL_MAX = 3      # потолок параллельных исполнителей за ночь (metis-0248, поправка 6); `AUTOSTART_MAX` в watch.py — жёстче: потолок самозапуска, не больше двух направлений сразу
STALE_HOURS = 24      # предшественник без изменений дольше — «зависший» (допущение плана, поправим по замеру)


def deps_cycle(tasks, tid, extra=None):
    """Цикл по depends_on, достижимый из tid: список id по кругу (первый повторён в конце) или []. extra —
    {id: [зависимости]} поверх записанных (проверка до записи)."""
    extra = extra or {}
    deps = lambda i: extra[i] if i in extra else (tasks[i][1].get("depends_on") or [] if i in tasks else [])  # noqa: E731
    state, path = {}, []

    def walk(i):
        state[i] = 1
        path.append(i)
        for d in deps(i):
            if state.get(d) == 1:
                return path[path.index(d):] + [d]
            if d not in state:
                got = walk(d)
                if got:
                    return got
        state[i] = 2
        path.pop()
        return []
    return walk(tid)


def check_depends(tasks, tid, deps):
    """Отказ при записи (поправка 1): --depends-on с несуществующим id, пачкой (зависеть можно от задачи), самой
    собой или циклом — ValueError. Цикл — если tid достижим из новых зависимостей (старый цикл в стороне не мешает)."""
    bad = [d for d in deps or [] if d not in tasks]
    if bad:
        raise ValueError(f"depends_on: нет задачи {', '.join(bad)}")
    story = [d for d in deps or [] if tasks[d][1].get("type", "task") != "task"]
    if story:
        raise ValueError(f"depends_on: {', '.join(story)} — не задача (пачка); зависеть можно от задач")
    if not tid:
        return
    prev, stack = {}, list(deps or [])
    for d in stack:
        prev[d] = tid
    while stack:
        cur = stack.pop()
        if cur == tid:
            path = [tid]
            while path[-1] != tid or len(path) == 1:
                path.append(prev[path[-1]])
                if len(path) > len(prev) + 2:
                    break
            raise ValueError("depends_on замыкается в цикл: " + " → ".join(reversed(path)))
        for d in tasks[cur][1].get("depends_on") or [] if cur in tasks else []:
            if d not in prev:
                prev[d] = cur
                stack.append(d)


def plan_batch(tasks, tids, t, busy=None, stale_h=STALE_HOURS):
    """Что из отметок владельца (tids, по порядку отметок) можно отдать одному исполнителю сейчас (metis-0248, шаг 2).
    busy — {id: направление} задач, которые идут у других исполнителей (параллельно с этой цепочкой).
    Порядок: сначала зависимости, при равенстве — порядок отметок. Не отдаётся (и не стоит в go):
      cycle  {id: круг}      — задача в цикле depends_on или зависит от него: тревога, без запуска;
      stuck  {id: pred}      — предшественник waiting/dropped/удалён или (вне пачки) без изменений > stale_h: тревога;
      wait   {id: причина}   — предшественник не в пачке, явное пересечение непустых touches с идущей у другого
                               направления задачей (пустой touches соседа не глушит: у разных направлений разные
                               репозитории; внутри направления всё идёт одной сессией), потолок PARALLEL_MAX исполнителей.
    go — id в порядке выдачи; цепочка (зависимые) уходит этому же исполнителю целиком."""
    busy = busy or {}
    out = {"go": [], "cycle": {}, "stuck": {}, "wait": {}}
    pos = {tid: n for n, tid in enumerate(tids)}
    ok = [i for i in tids if i in tasks]
    for i in ok:
        cyc = deps_cycle(tasks, i)
        if cyc:
            out["cycle"][i] = cyc
    left = {i for i in ok if i not in out["cycle"]}
    inb = set(left)
    dep_of = lambda i: tasks[i][1].get("depends_on") or []  # noqa: E731
    order = []
    while left:
        free = [i for i in left if not any(d in left for d in dep_of(i))]
        nxt = min(free or left, key=lambda i: pos[i])
        order.append(nxt)
        left.discard(nxt)
    if len(set(busy.values())) >= PARALLEL_MAX:
        for i in order:
            out["wait"][i] = f"уже идут {PARALLEL_MAX} исполнителя (потолок)"
        return out
    for i in order:
        h, why = tasks[i][1], None
        for d in dep_of(i):
            if d in out["go"]:
                continue
            dh = tasks[d][1] if d in tasks else None
            if dh is not None and dh.get("status") == "done":
                continue
            if dh is None or dh.get("status") in ("waiting", "dropped") or d in out["stuck"]:
                out["stuck"][i] = out["stuck"].get(d, d)
                break
            ts = ts_of(dh.get("updated"))
            if d not in inb and ts is not None and t - ts > stale_h * 3600:
                out["stuck"][i] = d
                break
            why = why or f"ждёт {d}"
        if i in out["stuck"]:
            continue
        if not why:
            for b in sorted(busy):
                bh = tasks[b][1] if b in tasks else {}
                if any(paths_cross(x, y) for x in h.get("touches") or [] for y in bh.get("touches") or []):
                    why = f"ждёт {b}: общие файлы"
                if why:
                    break
        if why:
            out["wait"][i] = why
        else:
            out["go"].append(i)
    return out


def outcomes(tasks):
    """{id: [id задач, у которых source — эта задача]}: «Что вышло» на карточке (metis-0506), по порядку id."""
    out = {}
    for i, (_, h, _) in sorted(tasks.items()):
        src = h.get("source")
        if isinstance(src, str) and src in tasks and src != i:
            out.setdefault(src, []).append(i)
    return out


def criteria_count(body):
    """«N из M» отмеченных пунктов «Готово, когда» (metis-0506); только заглушка-подсказка — «не заданы»; раздела нет — None."""
    items = done_criteria(body)
    real = [ok for ok, text in items if not _is_stub(text)]
    if real:
        return f"{sum(real)} из {len(real)}"
    return "не заданы" if items else None


GH_REPO = r"[A-Za-z0-9][\w.-]{0,99}/[\w.-]{1,100}"
_SHA = r"[0-9a-f]{7,40}"
# поле pr пачки (metis-0757): «latark/agent-kit#290»; branch — имя ветки без пробелов и управляющих знаков
STORY_PR_RE = re.compile(r"(" + GH_REPO + r")#([1-9]\d{0,5})")  # как boardtext.STORY_PR_RE (тот грузится без tasks); #0 нет
BRANCH_RE = re.compile(r"[\w][\w./-]{0,199}")


def story_pr(head):
    """PR пачки из поля pr → (репозиторий, номер) или None."""
    m = STORY_PR_RE.fullmatch(str(head.get("pr") or ""))
    return (m.group(1), int(m.group(2))) if m else None
# PR в строке журнала: «PR #163 (latark/agent-kit)», «latark/agent-kit#163», «github.com/latark/agent-kit/pull/163», «PR #163»
_PR_EXPLICIT = re.compile(r"\bPR\s*#?(\d{1,6})\s*\((" + GH_REPO + r")\)|(?<![\w/.-])(" + GH_REPO + r")#(\d{1,6})\b"
                          r"|github\.com/(" + GH_REPO + r")/pull/(\d{1,6})\b")
_PR_BARE = re.compile(r"\bPR\s*#?(\d{1,6})\b")
_PR_EVENT = re.compile(r"слит|открыт|squash|merge|влит", re.I)
_COMMIT = re.compile(r"(?:\bsquash|коммит|\bcommit|→)\s+(" + _SHA + r")\b|github\.com/(" + GH_REPO + r")/commit/(" + _SHA + r")\b",
                     re.I)


def work_links(head, body, idx, repos):
    """PR и коммиты задачи для карточки (metis-0501 [zeus-pr-link]) → ([(repo, номер, слит: True|False|None)],
    [(repo, sha)]). Источники: idx — autoclose.pr_index по кэшу gh; поле release «PR #N → sha»; журнал. Репозиторий —
    только из репозиториев направления (repos: направление → [repo], [merge_repos] политики): строка журнала чужой
    репозиторий ссылкой не сделает. «PR #N» без репозитория — только если у направления он один и в строке слит/открыт/squash."""
    own = [r.lower() for r in (repos or {}).get(head.get("direction")) or [] if isinstance(r, str)]
    single = own[0] if len(own) == 1 else None
    prs, commits = {}, []

    def add_commit(repo, sha):
        if repo in own and (repo, sha) not in commits and not any(r == repo and (c.startswith(sha) or sha.startswith(c))
                                                                  for r, c in commits):
            commits.append((repo, sha))
    for x in (idx or {}).get(head.get("id")) or []:
        if x.get("repo") in own:
            prs[(x["repo"], x["number"])] = bool(x.get("merged")) or prs.get((x["repo"], x["number"])) or False
            if x.get("sha"):
                add_commit(x["repo"], x["sha"][:7])
    rel = str(head.get("release") or "")
    lines = [(rel, True)] + [(x[2], False) for x in _journal(body)]
    for text, is_rel in lines:
        found = []
        for m in _PR_EXPLICIT.finditer(text):
            n, repo = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3)) if m.group(4) else (m.group(6), m.group(5))
            found.append((repo.lower(), int(n)))  # [merge_repos] и кэш gh — в нижнем регистре (metrics.Ctx)
        if not found and single and (is_rel or _PR_EVENT.search(text)):
            found = [(single, int(n)) for n in _PR_BARE.findall(text)]
        for repo, n in found:
            if repo in own:
                prs.setdefault((repo, n), None)
        for m in _COMMIT.finditer(text):
            if m.group(1):
                repo = found[0][0] if found else single
                if repo:
                    add_commit(repo, m.group(1)[:7])
            else:
                add_commit(m.group(2).lower(), m.group(3)[:7])
    return [(r, n, v) for (r, n), v in prs.items()], commits


def links_lines(links):
    """Строки раздела «PR и коммиты»: markdown-ссылки на GitHub."""
    prs, commits = links
    state = {True: " · слит", False: " · открыт", None: ""}
    return ([f"- [PR #{n}](https://github.com/{r}/pull/{n}) · {r}{state[v]}" for r, n, v in prs]
            + [f"- [коммит {c}](https://github.com/{r}/commit/{c}) · {r}" for r, c in commits])


def merged_wait(head, body, links, pr_days=None):
    """Задача в review со слитым PR (metis-0826) → «PR #N слит DD.MM, ждёт пунктов Готово, когда: k из n» (k — неотмеченных,
    n — всего пунктов без заглушки); не review, не задача или слитого PR нет — None. links — work_links, pr_days —
    {(репозиторий, номер): 'ГГГГ-ММ-ДД'} дня слияния (autoclose.pr_index, поле day). Пункты сам проход не отмечает:
    приёмку делает argus или владелец («без самоприёмки»)."""
    if head.get("type") != "task" or head.get("status") != "review" or not links:
        return None
    got = [((pr_days or {}).get((r, n)) or "", n) for r, n, v in links[0] if v is True]
    if not got:
        return None
    day, n = max(got)
    dd = f" {day[8:10]}.{day[5:7]}" if re.fullmatch(r"\d{4}-\d\d-\d\d", day) else ""
    crit = [done for done, text in done_criteria(body) if not _is_stub(text)]
    total, left = len(crit), crit.count(False)  # не unchecked_criteria: у задач до CRITERIA_FROM она даёт 0, а total считает пункты
    return f"PR #{n} слит{dd}, " + (f"ждёт пунктов Готово, когда: {left} из {total}" if total else "пунктов «Готово, когда» нет")


def id_link(i, names):
    """Ссылка на карточку задачи `[[<имя файла>|<id>]]`; карточки нет — голый id (metis-0322)."""
    return f"[[{names[i]}|{i}]]" if names.get(i) else i


def card_ctx(tid, head, tasks, names, cross, t=None, night_end="08:00", open_prs=None, outs=None, links=None, tails=None,
             pr_days=None):
    """Что карточке задачи нужно знать о других: незакрытые зависимости, пересечения, пачка и место в ней, слова
    «внимания» по всему (review без PR, готово без приёмки). outs — outcomes(tasks): что из задачи вышло; links —
    work_links (PR и коммиты); tails — {id: [текст]} хвостов последнего pantheon check (metis-0506, metis-0572)."""
    ctx = {"waits": [id_link(i, names) for i in open_deps(head, tasks)],
           "cross": [id_link(i, names) for i in cross.get(tid) or []],
           "outcome": [id_link(i, names) for i in (outs or {}).get(tid) or []],
           "links": links or ([], []), "tails": [str(x) for x in (tails or {}).get(tid) or [] if x]}
    if t is not None:
        ctx["flags"] = extra_attention(head, tasks[tid][2] if tid in tasks else "", tasks, t, night_end, open_prs)
        mw = merged_wait(head, tasks[tid][2] if tid in tasks else "", links, pr_days)
        if mw:
            ctx["flags"].append(mw)
    sid = head.get("parent")
    if sid in tasks and tasks[sid][1].get("type") == "story":
        ctx["story"] = names.get(sid) or card_name(tasks[sid][1])
        ids = story_order(sid, tasks)
        ctx["order"] = ids.index(tid) + 1 if tid in ids else None
    return ctx


# --- пачка (story, metis-0069) ------------------------------------------------------
# Story — карточка type story: название, ночь или день (night, due), бюджет (estimate). Задачи прикрепляются полем
# parent (pantheon task attach/detach); сумма их оценок считается, а не вводится руками.

# число берём только перед «%» (пробел, в т. ч. неразрывный, необязателен): «17 ч ≈ 15 % доли» → 15, часы и даты — нет (metis-0654)
PCT_RE = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)[ \u00a0\u202f]*%")


def pct(v):
    """Оценка «0,5 % недели» → 0.5; без числа перед «%» — None."""
    m = PCT_RE.search(str(v or ""))
    return float(m.group(1).replace(",", ".")) if m else None


def pct_text(x):
    """0.9 → «0,9 %»."""
    return ("%.2f" % x).rstrip("0").rstrip(".").replace(".", ",") + " %"


def story_children(sid, tasks):
    """Задачи пачки и её дети-пачки (пачка пачек, metis-0322): у ребёнка-пачки parent или batch равен id этой пачки."""
    return [tid for tid, (_, h, _) in tasks.items() if tid != sid and (
        h.get("parent") == sid and h.get("type") in ("task", "story")
        or h.get("type") == "story" and h.get("batch") == sid)]


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
            "unknown": [i for i in ids if heads[i].get("type") != "story" and not heads[i].get("touches")],
            "total": sum(1 for i in ids if heads[i].get("type") != "story")}


def over_budget(inf):
    return inf["budget"] is not None and inf["sum"] > inf["budget"] + 1e-9


NO_ESTIMATES = "оценок нет"


def story_asks(sid, tasks):
    """Карточки внутри пачки, которые ждут ответа владельца (needs_answer, колонка «Нужен ответ»), — с вложенными пачками
    (metis-0801): сама пачка не в «Нужен ответ», а вопрос в её составе на Пульте не был виден. → [id] по порядку."""
    out, seen, todo = [], {sid}, list(story_children(sid, tasks))
    while todo:
        i = todo.pop(0)
        if i in seen:
            continue
        seen.add(i)
        h = tasks[i][1]
        if needs_answer(h):
            out.append(i)
        if h.get("type") == "story":
            todo += story_children(i, tasks)
    return sorted(out)


def sum_text(inf):
    """«Сумма оценок» пачки: сумма оценок детей в процентах недели — расход против бюджета, а не доля сделанного
    (metis-0800). Ни у одного ребёнка нет оценки — «оценок нет», а не «0 %»: ноль читался как «прогресс 0 %»."""
    return NO_ESTIMATES if len(inf["no_estimate"]) == len(inf["ids"]) else pct_text(inf["sum"])


BATCH_BRANCH = "batch/"  # ветка пачки — batch/<story-id> (AGENTS.md, pantheon batch pr)


def batch_pr(sid, prs, own=None):
    """PR пачки по её ветке batch/<sid> из кэша gh (metis-0799): поле pr пишет `pantheon batch pr`, но PR, открытый
    иначе, его не ставит, и пачка оставалась без PR. prs — autoclose.batch_prs (одно правило «PR пачки» для карточки,
    board-auto и check, metis-0810: ветка, не форк, «часть» — PR пачки без закрытых задач), own — репозитории
    направления пачки (в нижнем регистре; None — любые). Выбор — как autoclose.batch_pick: первый (открытый важнее
    слитого, из нескольких — с большим номером) из own. → (репозиторий, номер, слит, [id задач, которые PR закрывает,
    кроме самой пачки]) или None."""
    rows = (prs or {}).get(sid) if isinstance(prs, dict) else None
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, (tuple, list)) or len(r) != 4 or not isinstance(r[0], str) or not isinstance(r[1], int) \
                or isinstance(r[1], bool):
            continue
        if own is None or r[0] in own:
            return r[0], r[1], bool(r[2]), sorted(i for i in r[3] or [] if isinstance(i, str) and i != sid)
    return None


def story_text(sid, tasks):
    """Состав пачки строками — для pantheon task show."""
    inf = story_info(sid, tasks)
    lines = [f"Пачка {sid}: задач {len(inf['ids'])}, закрыто {len(inf['closed'])}"]
    for n, i in enumerate(inf["ids"], 1):
        h = tasks[i][1]
        lines.append(f"{n}. {i} · {label_of(h)} · {h.get('estimate') or 'без оценки'} · "
                     f"{MODE_VIEW.get(h.get('mode')) or 'кто делает: ' + MODE_UNSET} · {one_line(h.get('title'))}")
    lines.append((NO_ESTIMATES if sum_text(inf) == NO_ESTIMATES else f"сумма {sum_text(inf)}")
                 + (f" из бюджета {pct_text(inf['budget'])}" if inf["budget"] is not None else " (бюджет не задан)")
                 + (" — больше бюджета" if over_budget(inf) else "")
                 + (f"; без оценки: {', '.join(inf['no_estimate'])}" if inf["no_estimate"] else ""))
    if inf["cross"]:
        lines.append("пересечения: " + "; ".join(inf["cross"]))
    return "\n".join(lines)


def task_attach(pantheon, t, tid, sid, actor="агент", only_loose=False):
    """Прикрепить задачу к пачке: parent у задачи и строка в журнал обеих. Была в другой пачке — переносится,
    строка и в журнал прежней. only_loose (автоматика: плановый проход, --apply, metis-0960) — переносить нельзя:
    предложение считалось по задачам без parent, а пока шёл расчёт, пачку могли поставить руками; parent уже есть —
    отказ ValueError до записи. → прежняя пачка или None."""
    tasks = load_tasks(pantheon, WORK_TYPES)
    if tid not in tasks or tasks[tid][1].get("type") != "task":
        raise ValueError(f"нет задачи {tid}")
    if sid not in tasks or tasks[sid][1].get("type") != "story":
        raise ValueError(f"{sid} — не пачка: прикреплять можно только к карточке type story")
    old = tasks[tid][1].get("parent")
    if old == sid:
        raise ValueError(f"{tid} уже в пачке {sid}")
    if only_loose and old:
        raise ValueError(f"{tid} уже в пачке {old} — предложение устарело, не переношу")
    if not mode_decided(tasks[tid][1]):
        raise ValueError(f"{tid}: {NO_MODE_BATCH}")
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


def migrate_modes(pantheon, t, dry_run=False, actor="агент"):
    """Разовая миграция (metis-0505): открытые задачи всех направлений без mode → mode undecided («не решено»). Пачки (story),
    закрытые, входящие (inbox/) и задачи пачек не трогаются: в пачке режим решает координатор, а «не решено» там — ошибка
    check. Запись — task_set со строкой в журнал и прежним updated (как migrate_projects): это не движение работы.
    Повтор ничего не меняет. → (строки плана, сбои)."""
    tasks = load_tasks(pantheon, WORK_TYPES)
    root = os.path.join(pantheon, "directions") + os.sep
    lines, failed = [], 0
    for tid, (p, h, _) in sorted(tasks.items()):
        if (h.get("type") != "task" or h.get("status") in ("done", "dropped") or h.get("mode") not in (None, "")
                or not p.startswith(root)):
            continue
        if in_pack(h, tasks):
            lines.append(f"{tid}: в пачке {h.get('parent') or h.get('batch')} без mode — пропущена, режим решает координатор")
            continue
        lines.append(f"{tid}: mode пуст → {UNDECIDED} («{MODES[UNDECIDED]}»)")
        if not dry_run:
            try:
                task_set(pantheon, t, tid, {"mode": UNDECIDED}, actor=actor, keep_updated=True,
                         note=f"«Кто делает»: {MODES[UNDECIDED]} (разовая миграция mode, metis-0505)")
            except (ValueError, OSError) as e:
                lines.append(f"  не записано: {e}")
                failed += 1
    return lines, failed


NOT_STARTED = ("inbox", "todo", None, "")  # не начатые звенья пачки «ждут» прошлое; inbox — тоже (metis-0457)


def render_story_card(head, body, src_rel, t, tasks, project=None, **kw):
    """Карточка пачки: та же, что у задачи (вопрос, ответ, заметки работают так же), плюс состав, сумма оценок против
    бюджета, цепочка, параллельно, пересечения. project — имя заметки проекта на пульте: ссылка на неё нужна виду
    «Пачки проекта»."""
    names = kw.get("names") or {}
    child_links = kw.pop("child_links", None) or {}  # {id задачи: work_links} — список PR задач пачки ([zeus-pr-link])
    bpr = kw.pop("batch_pr", None)  # batch_pr: PR с ветки batch/<id> по кэшу gh — когда поля pr нет (metis-0799)
    card, text = render_card(head, body, src_rel, t, **kw)
    inf = story_info(head.get("id"), tasks)
    spr = story_pr(head) or (bpr[:2] if bpr else None)
    bpr = bpr if bpr and (bpr[0].lower(), bpr[1]) == (spr[0].lower(), spr[1]) else None
    # закрытые PR пачки задачи с другим parent: в состав (он — по parent) не входят, но их видно (metis-0799)
    asks = story_asks(head.get("id"), tasks)
    outside = [i for i in (bpr[3] if bpr else []) if i not in inf["ids"] and i in tasks and tasks[i][1].get("type") == "task"]
    # состояние PR пачки — из кэша gh (pr_index по ветке batch/<id>: номер пачки в имени ветки); нет в кэше — без пометки
    sstate = bpr[2] if bpr else next((v for r, n, v in (child_links.get(head.get("id")) or ([], []))[0]
                                      if spr and (r, n) == (spr[0].lower(), spr[1])), None)
    spr_url = f"https://github.com/{spr[0]}/pull/{spr[1]}" if spr else None
    over = over_budget(inf)
    for k in ("Пачка", "Порядок", "Режим", "Режим почему", "Зависит от", "Области", "Пересечения"):
        card.pop(k, None)
    lk = lambda i: id_link(i, names)  # noqa: E731
    cross_l = [re.sub(r"^(\S+) и (\S+):", lambda m: f"{lk(m.group(1))} и {lk(m.group(2))}:", x) for x in inf["cross"]]
    unknown = f"у {len(inf['unknown'])} из {inf['total']}" if inf["unknown"] else None
    card.update({"Пульт": link(f"{PROJECTS_DIR}/{project}|{project}") if project else None,
                 "Когда": _date(head.get("night"), 10) or _date(head.get("due"), 10),
                 "Бюджет": head.get("estimate") if inf["budget"] is not None else None,
                 "Сумма оценок": sum_text(inf) + (" ⚠ больше бюджета" if over else ""),
                 "Закрыто": f"{len(inf['closed'])} из {len(inf['ids'])}",
                 "Цепочка": [lk(i) for i in inf["chain"]] or None, "Параллельно": [lk(i) for i in inf["parallel"]] or None,
                 "Пересечения": cross_l or None, "Области не указаны": unknown,
                 "Ветка": head.get("branch") if BRANCH_RE.fullmatch(str(head.get("branch") or ""))
                 else BATCH_BRANCH + head["id"] if bpr and BRANCH_RE.fullmatch(BATCH_BRANCH + str(head.get("id"))) else None,
                 "Вопросов": len(asks) or None,
                 "PR пачки": spr_url, "Вне состава": [lk(i) for i in outside] or None, "Тип": "пачка"})
    summary = ("> **Пачка:** " + (NO_ESTIMATES if sum_text(inf) == NO_ESTIMATES else f"сумма оценок {sum_text(inf)}")
               + (f" из бюджета {pct_text(inf['budget'])}" if inf["budget"] is not None else " · бюджет не задан")
               + (" · ⚠ больше бюджета" if over else "") + f" · закрыто {card['Закрыто']}"
               + (f"\n> **Нужен ответ владельца внутри пачки:** {len(asks)} — {', '.join(lk(i) for i in asks)}" if asks else "")
               + (f"\n> **Цепочка одному исполнителю:** {' → '.join(lk(i) for i in inf['chain'])}" if inf["chain"] else "")
               + (f"\n> **Параллельно:** {', '.join(lk(i) for i in inf['parallel'])}" if inf["parallel"] else "")
               + (f"\n> **Пересечения по файлам:** {'; '.join(cross_l)}" if inf["cross"] else "")
               + (f"\n> **Области не указаны:** {unknown}" if unknown else "")
               + (f"\n> **PR пачки:** [PR #{spr[1]}]({spr_url}) · {spr[0]}"
                  + {True: " · слит", False: " · открыт", None: ""}[sstate]
                  + (f" · ветка `{card['Ветка']}`" if card.get("Ветка") else "") if spr
                  else f"\n> **Ветка пачки:** `{card['Ветка']}` · PR ещё нет" if card.get("Ветка") else "")
               + (f"\n> **PR пачки закрыл и задачи вне её состава** (их parent — другая пачка или пусто): "
                  f"{', '.join(lk(i) for i in outside)}" if outside else ""))
    rows = []
    cell = lambda i: f"[[{names[i]}\\|{i}]]" if names.get(i) else i  # noqa: E731  (в таблице «|» экранируется)
    for n, i in enumerate(inf["ids"], 1):
        h = tasks[i][1]
        # «Зависимость»: открытые depends_on и ближайшее незакрытое прошлое звено цепочки (только у не начатых: todo или пусто); «ничего» — законно пусто
        waits = [cell(d) for d in open_deps(h, tasks)]
        k = inf["chain"].index(i) if i in inf["chain"] else 0
        prev = next((j for j in reversed(inf["chain"][:k]) if j not in inf["closed"]), None)  # ближайшее незакрытое
        if prev and cell(prev) not in waits and h.get("status") in NOT_STARTED:
            waits.append(cell(prev))
        mode = MODE_VIEW.get(h.get("mode")) or ("—" if h.get("type") == "story" else MODE_UNSET)
        rows.append(f"| {n} | {cell(i)} | {_plain(one_line(h.get('title'))).replace('|', '/')} | {label_of(h)} | "
                    f"{_plain(h.get('estimate') or '—').replace('|', '/')} | {mode} | "
                    f"{', '.join(waits) or 'нет'} |")
    table = ("## Состав\n\n| № | Задача | Название | Статус | Оценка | Кто делает | Зависимость |\n|---|---|---|---|---|---|---|\n"
             + ("\n".join(rows) if rows else "| — | задач пока нет | | | | | |"))
    prl = []
    for i in inf["ids"]:
        prs, commits = child_links.get(i) or ([], [])
        if prs or commits:
            prl.append(f"- {id_link(i, names)}: " + ", ".join(
                [f"[PR #{n}](https://github.com/{r}/pull/{n})" for r, n, _ in prs]
                + [f"[{c}](https://github.com/{r}/commit/{c})" for r, c in commits]))
    if prl:
        table += "\n\n## PR задач\n\n" + "\n".join(prl)
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
        if h.get("type") in ("task", "story"):  # «Ждёт вас» = колонка «Нужен ответ» доски, пачки тоже (metis-0801)
            c["Ждёт вас"] += needs_answer(h)
        if h.get("type") == "story":
            c["Пачек"] += 1
            continue
        if h.get("type") != "task":
            continue
        c["Открыто"] += 1
        c["В работе"] += h.get("status") == "doing"
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
    """Записи [[direction]] реестра → {проект: {directions, mark, rank, goal, budget, status, coordinator, hq_led}}.
    Проект — поле project, иначе имя направления; ранг — поле rank, иначе порядок в реестре. hq_led — у направления
    координатора проекта `coordinator = false` (metis-0155): его ведёт Пританей."""
    out = {}
    for n, d in enumerate(dirs or [], 1):
        if not isinstance(d, dict) or not isinstance(d.get("name"), str) or not d["name"] or d["name"] == "inbox":
            continue
        p = one_line(d.get("project") or d["name"])
        rank = d.get("rank") if isinstance(d.get("rank"), int) and not isinstance(d.get("rank"), bool) else n
        e = out.setdefault(p, {"directions": [], "mark": d.get("mark"), "rank": rank, "goal": d.get("goal"),
                               "budget": d.get("budget"), "status": d.get("status") or "активный",
                               "coordinator": d["name"], "hq_led": d.get("coordinator") is False})
        e["directions"].append(d["name"])
    return out


HQ_LED = "ведёт Пританей"  # метка проекта на пульте, когда у направления coordinator = false (metis-0155)
# дата «ДД.ММ» или «ДД.ММ.ГГГГ» в цели и бюджете реестра (metis-0828): «~28–30.10», «до 30.10 12:00»; «1.0» — не дата
REG_DATE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?(?![\d.]*\d)(?!\s*(?:ч\b|час|мин|сек|%|дн|нед|[гмк]б\b|млн|тыс|руб|₽))", re.I)


def reg_dates(text, t):
    """Даты из строки реестра → [datetime]; без года — ближайшая к t: год t, а дальше полугода вперёд или назад —
    прошлый или следующий год."""
    now = datetime.fromtimestamp(t)
    out = []
    for d, m, y in REG_DATE.findall(str(text or "")):
        try:
            x = datetime(int(y) if y else now.year, int(m), int(d))
        except ValueError:
            continue
        if not y and (x - now).days > 183:
            x = x.replace(year=x.year - 1)
        elif not y and (now - x).days > 183:  # «15.01» в ноябре — следующий январь
            x = x.replace(year=x.year + 1)
        out.append(x)
    return out


def stale_mark(text, t):
    """Цель или бюджет из directions.toml, все даты которых прошли (последняя — раньше сегодняшнего дня), → строка
    с пометкой «устарело ДД.ММ» спереди: пульт не выдаёт её за текущую. Дат нет или срок не прошёл — как есть."""
    s = one_line(text) if text not in (None, "") else text
    dates = reg_dates(s, t)
    if not dates:
        return s
    last = max(dates)
    if datetime.fromtimestamp(t).date() <= last.date():
        return s
    return f"устарело {last:%d.%m} · {s}"


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
    # metis-0155: координатор выключен — направление ведёт Пританей, метка вместо ссылки на сессию координатора
    coord = HQ_LED if reg.get("hq_led") else link(node)
    mark = project_mark(p, {p: reg.get("mark")} if reg.get("mark") else None)
    budget = reg.get("budget")
    head = {"Тип": "проект", "Направление": ", ".join(reg["directions"]), "Значок": mark,
            "Статус проекта": one_line(reg.get("status")), "Ранг": reg["rank"], "Координатор": coord,
            "Цель": stale_mark(one_line(reg.get("goal")), t) or None, "Здоровье": hl, "Цвет": color,
            "Обновлено": upd or None,
            "Бюджет недели": stale_mark(budget, t) if budget not in (None, "") else None, **c}
    body = (f"\n> Заметку пишет плановый проход по `directions.toml` и задачам. Не правьте её: счётчики сверяет "
            f"`pantheon check`.\n\n# {mark} {p}\n\n**Здоровье:** {hl} · **Координатор:** {coord}"
            + (f" · **Цель:** {head['Цель']}" if head["Цель"] else "")
            + f"\n\nОткрыто {c['Открыто']} · в работе {c['В работе']} · нужен ответ {c['Ждёт вас']} · просрочено "
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
  mode_view: 'if(note["Режим"].isEmpty(), "не решено", if(note["Режим"] == "параллельно", "⇉ несколько разработчиков параллельно", if(note["Режим"] == "сам", "● координатор сам", "→ один разработчик")))'
  waits: 'if(note["Зависит от"].isEmpty(), "", "⏳ ждёт " + note["Зависит от"].join(", "))'
  cross: 'if(note["Пересечения"].isEmpty(), "", "✂ " + note["Пересечения"].join(", "))'
  areas: 'if(note["Области"].isEmpty(), "❔ не указаны", note["Области"].join(", "))'
  sum_budget: '[note["Сумма оценок"], note["Бюджет"]].filter(value.isTruthy()).join(" / ")'
properties:
  file.name:
    displayName: Карточка
  formula.sum_budget:
    displayName: Оценки / бюджет (не прогресс)
  note.Ждёт вас:
    displayName: Нужен ответ
  note.id:
    displayName: №
  formula.mode_view:
    displayName: Кто делает
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
      - note.Вопросов
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
  - type: table
    name: Учёт недели
    filters:
      and:
        - 'note["Тип"] == "учёт"'
        - 'note["Период"] == "неделя"'
    sort:
      - property: note.Срез
        direction: ASC
      - property: note.Задач
        direction: DESC
    order:
      - note.Срез
      - note.Исполнитель
      - note.Модель
      - note.Effort
      - note.Направление
      - note.Задач
      - note.Отменено
      - note.С первого круга
      - note.Кругов
      - note.Токенов на задачу
      - note.Долларов на задачу
      - note.Возвратов
      - note.После слияния
      - note.Часов
      - note.Из них оценка
  - type: table
    name: Учёт с начала
    filters:
      and:
        - 'note["Тип"] == "учёт"'
        - 'note["Период"] == "с начала"'
    sort:
      - property: note.Срез
        direction: ASC
      - property: note.Задач
        direction: DESC
    order:
      - note.Срез
      - note.Исполнитель
      - note.Модель
      - note.Effort
      - note.Направление
      - note.Задач
      - note.Отменено
      - note.С первого круга
      - note.Кругов
      - note.Токенов на задачу
      - note.Долларов на задачу
      - note.Возвратов
      - note.После слияния
      - note.Часов
      - note.Из них оценка
"""
PULT_VERSION = hashlib.sha256(PULT_FILE.encode("utf-8")).hexdigest()[:12]  # сменился шаблон — тик перепишет Пульт.base


# --- доска владельца ------------------------------------------------------------

CARD_ORDER = ["Статус", "Проект", "Внимание", "Вопрос", "Приоритет", "Срок", "Кому", "Дальше", "Ждёт", "Создана", "Откуда", "Из чего", "Критерии", "Хвост", "Вопрос задан",
              "Закрыта", "Выпуск", "Пачка", "Пульт", "Ночь", "Оценка", "Факт", "Приёмка", "Порядок", "Режим", "Режим почему",
              "Зависит от", "Области", "Пересечения",
              # карточка пачки (story) и заметка проекта (пульт)
              "Когда", "Бюджет", "Сумма оценок", "Закрыто", "Цепочка", "Параллельно", "Области не указаны",
              "Вопросов", "Ветка", "PR пачки", "Вне состава", "Тип", "id", "tags"]
# типы свойств карточек для Obsidian (.obsidian/types.json хранилища): тик ставит свои ключи, чужие не трогает
PROP_TYPES = {"Внимание": "multitext", "Приоритет": "number", "Срок": "date", "Создана": "date",
              "Вопрос задан": "datetime", "Откуда": "text", "Из чего": "text", "Критерии": "text", "Хвост": "multitext", "Вопрос": "text", "Закрыта": "date", "Кому": "text", "tags": "tags",
              "Выпуск": "text", "Пачка": "text", "Ночь": "date", "Оценка": "text", "Факт": "text", "Приёмка": "text",
              "Порядок": "number", "Режим": "text", "Зависит от": "multitext", "Области": "multitext",
              "Пересечения": "multitext", "Цепочка": "multitext", "Параллельно": "multitext", "Области не указаны": "text",
              "Вопросов": "number", "Ветка": "text", "PR пачки": "text", "Вне состава": "multitext",
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


def needs_answer(head):
    """Ждёт ответа владельца — колонка «Нужен ответ» доски: waiting и waiting_on human (metis-0801). Одно определение
    для колонки, счётчика «Нужен ответ» заметки проекта на Пульте, «Вопросов» пачки и «Нужен ответ» board-auto
    (boardtext.owner_cards — копия, модуль без tasks; равенство сверяет тест)."""
    return head.get("status") == "waiting" and head.get("waiting_on") == "human"


def label_of(head):
    st = head.get("status")
    if needs_answer(head):
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
        "talos": "Талос", "clio": "Клио", "iris": "Ирида", "hestia": "Гестия", "palamedes": "Паламед"}
OWNER_SLUGS = ("вы", "владелец", "owner", "human")
OWNER_NODE, HQ_NODE = "Владелец", "Зевс"


def owner_addressed(head):
    """Задача адресована владельцу — тем же правилом, что вид «От меня нужно»: «Кому» содержит «Владелец»
    (note["Кому"].toString().contains), а не равно ему: узел «Владелец · гость» вид считает, и счётчик сводки — тоже (metis-0240)."""
    return OWNER_NODE in Roles(()).name(assignee(head))
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


ATTENTION_WORDS = ("конфликт", "подтвердите словом", "вопрос к вам", "долго ждёт", "просрочено", "срок скоро",
                   NO_PR, NO_ACCEPT)


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
            "Внимание": (attention(head, t, conflict, long_wait) or []) + list(ctx.get("flags") or []) or None,
            # «Срок» — свойство-дата Bases: только дата; время срока — в выноске карточки
            "Приоритет": prio if isinstance(prio, int) and not isinstance(prio, bool) else None,
            "Срок": _date(head.get("due"), 10),
            "Кому": link(node), "Дальше": None if closed else head.get("next"),
            "Ждёт": head.get("waiting_on") if head.get("waiting_on") not in (None, "human") else None,
            "Создана": _date(head.get("created"), 10),
            # «Откуда» — вид появления (from), по нему группирует «Новое за неделю»; «Из чего» — ссылка на источник (metis-0506)
            "Откуда": head.get("from") or None,
            "Из чего": (id_link(head["source"], names or {}) if ID_RE.fullmatch(str(head.get("source") or ""))
                        else head.get("source")) or None,
            "Критерии": criteria_count(body), "Хвост": list(ctx.get("tails") or []) or None,
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
            # «не решено» — пустое свойство: вид .base показывает пустой режим сам (metis-0500), а не «один исполнитель»
            "Режим": MODES.get(head.get("mode")) if mode_decided(head) else None, "Режим почему": head.get("mode_why"),
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
        parts[-1] += f"\n> **Кто делает:** {MODE_VIEW.get(head.get('mode'), card['Режим'])}" + (f" — **Почему так:** {head['mode_why']}" if head.get("mode_why") else "")
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
    if card["Хвост"]:
        parts.append("> [!warning] Хвост\n" + "\n".join(f"> - {x}" for x in card["Хвост"]))
    origin = [f"**Из чего возникла:** {card['Из чего']}" + (f" ({card['Откуда']})" if card["Откуда"] else "")
              if card["Из чего"] else (f"**Из чего возникла:** {card['Откуда']}" if card["Откуда"] else "")]
    if ctx.get("outcome"):
        origin.append(f"**Что вышло:** {', '.join(ctx['outcome'])}")
    if any(origin):
        parts.append("\n".join(x for x in origin if x))
    lk = links_lines(ctx.get("links") or ([], []))
    if lk:
        parts.append("## PR и коммиты\n\n" + "\n".join(lk))
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
    - file.name != "Хвосты"
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
  mode_view: 'if(note["Режим"].isEmpty(), "не решено", if(note["Режим"] == "параллельно", "⇉ несколько разработчиков параллельно", if(note["Режим"] == "сам", "● координатор сам", "→ один разработчик")))'
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
    displayName: Оценки / бюджет (не прогресс)
  note.id:
    displayName: №
  formula.status_view:
    displayName: Статус
  formula.prio_view:
    displayName: Приоритет
  formula.mode_view:
    displayName: Кто делает
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
    order: [file.name, note.Закрыто, note.Вопросов, formula.sum_budget, note.Цепочка]
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
    order: [note.id, file.name, formula.status_view, formula.prio_view, note.Внимание, note.Кому, note.Срок, note.Дальше, note.Создана, note.Закрыта, note.Откуда, note.Критерии]
    columnSize:
      note.id: 150
  - type: table
    name: Новое за неделю
    filters:
      and:
        - 'note["Создана"] >= today() - "7d"'
        - 'note["Статус"] != "Отменено"'
    groupBy:
      property: note.Откуда
      direction: ASC
    sort:
      - property: formula.cr_n
        direction: DESC
    order: [note.id, file.name, formula.status_view, note.Откуда, note.Из чего, note.Критерии, note.Кому, note.Создана]
  - type: table
    name: Хвосты
    filters:
      and:
        - 'note["Статус"] != "Отменено"'
        - or:
            - '!note["Хвост"].isEmpty()'
            - and:
                - or:
                    - 'note["Откуда"] == "остаток"'
                    - 'note["Откуда"] == "ревью"'
                - 'note["Статус"] != "Готово"'
    sort:
      - property: formula.urgency
        direction: ASC
      - property: formula.cr_n
        direction: ASC
    order: [note.id, file.name, formula.status_view, note.Хвост, note.Откуда, note.Из чего, note.Критерии, note.Кому]
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
    "Пачки": "Пачки (наборы задач на ночь) по статусам; готовые — 7 дней. «Закрыто N из M» — сделанное, «Вопросов» — "
             "задачи пачки, ждущие вашего ответа, «Оценки / бюджет» — сумма оценок против бюджета, не прогресс. Что "
             "делать: ответить на вопросы внутри пачки, следить за бюджетом и пересечениями по файлам.",
    "Итоги пачек": "Задачи из пачек, которые дошли до проверки, готовы или ждут приёмки, по пачкам. Что делать: принять "
                   "результат ночи.",
    "Все задачи": "Вообще все задачи и пачки, включая готовые, по проектам. Что делать: искать то, чего нет в других видах.",
    "Новое за неделю": "Задачи и пачки, заведённые за 7 дней, по тому, откуда взялись: ваше слово, отчёт, ревью, остаток, "
                       "план, по ходу. Что делать: проверить, что новое — то, что вы просили.",
    "Хвосты": "Что застряло или потерялось: задачи со свойством «Хвост» (последний pantheon check: застой doing/review "
              "больше 2 суток, вы ответили, а задача ждёт, PR слит, а задача открыта) и открытые остатки и находки ревью. "
              "Полный список — Хвосты.md. Что делать: закрыть, вернуть в очередь или поручить.",
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


def _summary(tasks, t, inbox=None, names=None, long_ids=None, queue=None, accept=None):
    """names — id → имя файла карточки (как его записал проход доски); ссылки — с подписью-заголовком.
    long_ids — решения «долго ждёт»; queue — что политика уведомлений отложила без пинга за сутки; accept — {id: «PR #N слит …»}
    задач в review со слитым PR (metis-0826): отдельный раздел «Слито, ждёт приёмки», не вперемешку с «на проверке»."""
    names, long_ids = names or {}, long_ids or set()
    rows = {"wait": [], "overdue": [], "doing": [], "done": [], "accept": [],
            "inbox": [f"[[Доска/{names.get(cid) or card_name({'title': it['title']})}|{_plain(it['title'])}]] · "
                      f"{it['direction']}" for cid, it in (inbox or {}).items()]}
    wait = []
    mine = set()  # вид «От меня нужно»: ждут ответа, адресованы Владельцу или приёмка «к владельцу»; без двойного счёта
    for tid, (p, h, _) in sorted(tasks.items()):
        if (h.get("status") == "waiting" and h.get("waiting_on") == "human") or (
                h.get("status") not in ("done", "dropped")
                and (owner_addressed(h) or h.get("acceptance") == "к владельцу")):
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
        if tid in (accept or {}) and h.get("status") == "review":
            rows["accept"].append(f"{name} · {one_line(accept[tid])}")
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
                f" · 🟡 В работе {len(rows['doing'])} · 🟢 Готово за сутки {len(rows['done'])}"
                + (f" · 🔵 Слито, ждёт приёмки: {len(rows['accept'])}" if rows["accept"] else ""))
    done_fold = (f"> [!success]- 🟢 Готово за сутки ({len(rows['done'])})\n"
                 + ("\n".join(f"> - {x}" for x in rows["done"]) if rows["done"] else "> —") + "\n")
    return ("# Сводка\n\n" + counters + "\n\n" + render_views_section() + "\n"
            + "Проекты и пачки — [[Пульт.base|пульт]].\n\n"
            + sec(f"🔴 {HUMAN_WAIT}", top, len(wait)) + "\n"
            + sec("⏰ Просрочено", rows["overdue"]) + "\n"
            + sec("📥 Входящие заявки направлениям", rows["inbox"]) + "\n"
            + sec("🟡 В работе", rows["doing"]) + "\n"
            + (sec("🔵 Слито, ждёт приёмки", rows["accept"]) + "\n" if rows["accept"] else "") + done_fold
            + ("\n" + sec("🔕 Без уведомления за сутки", quiet) if quiet else "")
            + "\n✍️ Написать агенту — текстом в раздел «Ваши заметки» внизу карточки. Перенести — перетащите карточку на доске. "
              "Готовые карточки уходят с доски через 7 дней.\n"), rows




def view_file_url(view_dir, rel):
    """Ссылка Obsidian на файл копии вида: obsidian://open?path=<абсолютный путь> (metis-0318). Документация Obsidian
    URI: path перекрывает vault и file, хранилище ищется по пути, имя хранилища и последний открытый файл не нужны;
    «/» кодируется как %2F, пробел — %20. Единственное место построения ссылки: card_url, pantheon.board_url."""
    from urllib.parse import quote
    return "obsidian://open?path=" + quote(os.path.join(os.path.abspath(view_dir), rel), safe="")


def card_url(view_dir, name):
    """Ссылка на карточку Доска/<name>.md в копии вида view_dir (name — как у card_name, без «.md»)."""
    return view_file_url(view_dir, "Доска/" + name + ".md")


NOTICE_MARK = "Уведомление, а не находка:"
NOTICE_NAME_RE = re.compile(r"\d{4}-\d\d-\d\d-\d{4}-task-([a-z0-9][a-z0-9-]{0,60})\.md")


def is_task_notice(d, name, f, text):
    """Уведомление `task new` узнаётся только по точной форме (argus b): имя «…-task-<id>.md», первая строка
    «# Новая задача <id>: …», пометка NOTICE_MARK, и задача <id> в этом направлении есть. Находка, которая лишь
    цитирует пометку, остаётся находкой и карточку на доске не теряет."""
    m = NOTICE_NAME_RE.fullmatch(f)
    return bool(m and text.startswith(f"# Новая задача {m.group(1)}: ") and NOTICE_MARK in text
                and os.path.isfile(os.path.join(d, name, "tasks", m.group(1) + ".md")))


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
            if is_task_notice(d, name, f, text):  # уведомление о новой задаче (task new) — не заявка, карточки нет
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
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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


CSS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "share", "pantheon-view-obsidian",
                        "snippets", "pantheon.css")
OLD_CSS_HASHES = {"b07338ca44d6892d"}  # сниппет до 0.11.53 (metis-0306): нетронутый — не правка владельца


def _sync_snippet(vault, state, state_path, t, alert, src=None, old_hashes=None):
    """.obsidian/snippets/pantheon.css хранилища (metis-0306): view-sync.sh кладёт образец только в копию без .obsidian,
    поэтому новый сниппет доставляем отдельно, по образцу _sync_base: версия сменилась — записать; владелец правил файл —
    его версию сохранить в папку состояния и одна тревога. Нет .obsidian — не трогаем (образец положит view-sync.sh)."""
    src = CSS_PATH if src is None else src
    old_hashes = OLD_CSS_HASHES if old_hashes is None else old_hashes
    if not os.path.isdir(os.path.join(vault, ".obsidian")):
        return
    try:
        with open(src, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError):
        return
    version = _sha(text)
    p = os.path.join(vault, ".obsidian", "snippets", "pantheon.css")
    try:
        with open(p, "rb") as fh:
            cur = fh.read()
    except FileNotFoundError:
        cur = None
    except OSError as e:
        alert("board-css", type(e).__name__, f"доска: {p} не читается ({e}) — сниппет не обновлён", "board")
        return
    if cur is not None and state.get("css_version") == version:
        return
    new = text.encode("utf-8")
    try:
        if cur is not None and cur != new and _sha(cur) != state.get("css_hash") and _sha(cur) not in old_hashes:
            keep = os.path.join(os.path.dirname(os.path.abspath(state_path)),
                                f"board-css-{datetime.fromtimestamp(t).strftime('%Y%m%d-%H%M%S')}.css")
            os.makedirs(os.path.dirname(keep), exist_ok=True)
            with open(keep, "wb") as fh:
                fh.write(cur)
            alert(f"board-css-{version}", version, f"pantheon.css обновлён, ваша версия сохранена в {keep}", "board")
        if cur != new:
            _write_plain(p, text)
    except OSError as e:
        alert("board-css", type(e).__name__, f"доска: {p} не записать ({e}) — сниппет не обновлён", "board")
        return
    state["css_version"], state["css_hash"] = version, version


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


BOOKMARKS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "share",
                              "pantheon-view-obsidian", "bookmarks.json")


# Закладки образца до metis-0324 (его выдавал view-sync.sh): у кого bookmarks.json уже есть, а «bookmarks_seen» ещё нет,
# эти пути считаются выданными — удалённую владельцем первый тик не возвращает; досыпает только новые.
BOOKMARKS_LEGACY = ("Доска/Сводка.md", "Доска/Доска.base", "Кто есть кто.md", "Доска/Проблемы.md")


def _bookmark_files(items):
    """Все закладки-файлы дерева (группы вложены)."""
    out = []
    for it in items:
        if isinstance(it, dict) and it.get("type") == "group" and isinstance(it.get("items"), list):
            out += _bookmark_files(it["items"])
        elif isinstance(it, dict) and it.get("type") == "file":
            out.append(it)
    return out


def _sync_bookmarks(vault, state, alert, src=None):
    """.obsidian/bookmarks.json хранилища (metis-0324): набор закладок по умолчанию (share/…/bookmarks.json — он же образец
    для view-sync.sh) — часть вида. Как Доска.base: недостающие свои добавляет, закладки владельца и их порядок не трогает;
    свою, удалённую владельцем, не возвращает — в состоянии «bookmarks_seen» пути, уже выданные или найденные у владельца.
    Битый JSON — файл не тронут, одна тревога, состояние не меняется (поправит — тик продолжит). Запись атомарная.
    Нет .obsidian — не трогаем (образец положит view-sync.sh). Новый вид или справка — строка в образце, в том же PR."""
    if not os.path.isdir(os.path.join(vault, ".obsidian")):
        return
    try:
        with open(BOOKMARKS_PATH if src is None else src, encoding="utf-8") as fh:
            wanted = json.load(fh)["items"]
        if not isinstance(wanted, list):
            return
    except (OSError, ValueError, KeyError, TypeError):
        return
    p = os.path.join(vault, ".obsidian", "bookmarks.json")
    try:
        with open(p, encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        raw = None
    except (OSError, UnicodeDecodeError) as e:
        alert("board-bookmarks", "unreadable", f"доска: {p} не читается ({e}) — закладки не обновлены", "board")
        return
    data = {"items": []}
    if raw is not None:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.setdefault("items", []), list):
                raise ValueError("нет списка items")
        except ValueError as e:
            alert("board-bookmarks", _sha(raw), f"доска: {p} — битый JSON ({e}); закладки не обновлены, файл не тронут",
                  "board")
            return
    seen = state.get("bookmarks_seen")
    seen = {x for x in seen if isinstance(x, str)} if isinstance(seen, list) else set()
    if "bookmarks_seen" not in state and raw is not None:
        seen |= set(BOOKMARKS_LEGACY)
    have = {it["path"] for it in _bookmark_files(data["items"]) if isinstance(it.get("path"), str)}
    changed = False
    for grp in wanted:
        if not isinstance(grp, dict) or not isinstance(grp.get("items"), list):
            continue
        add = [dict(f) for f in grp["items"] if f.get("path") not in have and f.get("path") not in seen]
        if not add:
            continue
        mine = next((g for g in data["items"] if isinstance(g, dict) and g.get("type") == "group"
                     and g.get("title") == grp.get("title") and isinstance(g.get("items"), list)), None)
        if mine is None:
            mine = {k: v for k, v in grp.items() if k != "items"}
            mine["items"] = []
            data["items"].append(mine)
        mine["items"] += add
        changed = True
    try:
        if changed:
            _write_plain(p, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError) as e:  # ValueError: одиночный суррогат в названии закладки не кодируется в utf-8
        alert("board-bookmarks", type(e).__name__, f"доска: {p} не записать ({e}) — закладки не обновлены", "board")
        return
    state["bookmarks_seen"] = sorted(seen | {f.get("path") for g in wanted if isinstance(g, dict)
                                             for f in g.get("items", []) if f.get("path")})


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
    try:
        _write_plain(p, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError) as e:
        alert("board-types", type(e).__name__, f"доска: {p} не записать ({e}) — типы свойств не обновлены", "board")


def _deferral_api():
    """Функции tasks для lib/deferral.py (модуль грузят и под другим именем, импортом его не достать)."""
    return type("TasksApi", (), {"owner_answers_all": staticmethod(owner_answers_all), "_live": staticmethod(_live),
                                 "one_line": staticmethod(one_line), "task_new": staticmethod(task_new)})


def board_sync(pantheon, board, state_path, log_path, t, alert=None, notify=None, primary=True, projects=None,
               policy=None, marks=None, registry=None, night_end="08:00", open_prs=None, pr_index=None, repos=None,
               tails=None, batch_prs=None):
    """Один проход доски. → список строк «что сделано» (для журнала тика). policy — политика уведомлений
    (lib/notify.py, её передаёт pantheon.py): решает, что показать, что отложить в сводку. Без неё — без
    уведомлений; notify — прежний параметр, не используется. registry — проекты для пульта (project_registry);
    без него — из projects и marks. pr_index — autoclose.pr_index, repos — направление → [repo]: ссылки на PR и коммиты
    в карточках; tails — {id: [текст]} хвостов последнего pantheon check (свойство «Хвост»); batch_prs —
    autoclose.batch_prs: PR пачки по ветке batch/<id> для карточки пачки (metis-0810)."""
    alert = alert or (lambda *a, **k: None)
    projects = projects or {}
    if registry is None:
        registry = project_registry([{"name": d, "project": p, "mark": (marks or {}).get(p)} for d, p in projects.items()])
    vault = os.path.dirname(os.path.abspath(board))  # папка копии вида: card_url строит по ней путь
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
        if not f.endswith(".md") or f.startswith((".", "_")) or f in ("Сводка.md", "Проблемы.md", "Хвосты.md"):
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
    held = _deferral.hold(_deferral_api(), pantheon, t, tasks, cards, log_path, registry, primary, policy,
                          alert, done_lines)
    if policy is not None:
        decs = []
        for tid, (_, h, _) in tasks.items():
            if tid in held:
                continue  # отложен DEFER_LIMIT раз: тот же вопрос пингом больше не идёт
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
    outs = outcomes(tasks)
    wl = {i: work_links(h, b, pr_index, repos) for i, (_, h, b) in tasks.items()} if repos else {}
    pr_days = {(x["repo"], x["number"]): x.get("day") for xs in (pr_index or {}).values() for x in xs if x.get("merged")}
    accept = {i: w for i, (_, h, b) in tasks.items() if i in wl for w in [merged_wait(h, b, wl[i], pr_days)] if w}
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
                own = [r.lower() for r in (repos or {}).get(h.get("direction")) or [] if isinstance(r, str)]
                card, cbody = render_story_card(h, b, rel(src), t, tasks, project=pn, child_links=wl,
                                                batch_pr=batch_pr(cid, batch_prs, own) if repos else None, **kw)
            else:
                card, cbody = render_card(h, b, rel(src), t, ctx=card_ctx(cid, h, tasks, names, cross, t, night_end, open_prs,
                                                                          outs, wl.get(cid), tails, pr_days), **kw)
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
    _, rows = _summary(tasks, t, inbox, names, long_ids, accept=accept)
    if policy is not None:
        # digest_day прежнего board.json (до 0.11.15) — политике: в день обновления второго утреннего не будет
        # закрыто с прошлой сводки (digest_t), не старше суток (metis-0851); closed — дата, поэтому сравнение по дню,
        # а задачи, уже посчитанные прошлой сводкой, политика вычитает сама — каждая в одной сводке
        since_day = now_iso(policy.done_since())[:10]
        done_n = [i for i, (_, h, _) in tasks.items() if h.get("status") == "done" and str(h.get("closed") or "") >= since_day]
        policy.run((len(rows["wait"]), len(rows["overdue"]), len(rows["inbox"])),
                   lambda tid: card_url(vault, names.get(tid, "Сводка")), card_url(vault, "Сводка"),
                   legacy_digest_day=state.pop("digest_day", None), done=done_n)
    text, rows = _summary(tasks, t, inbox, names, long_ids, policy.queue_view() if policy is not None else None, accept)
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
    _sync_bookmarks(os.path.dirname(os.path.abspath(board)), state, alert)
    _sync_snippet(os.path.dirname(os.path.abspath(board)), state, state_path, t, alert)
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


# --- ничего не теряем (metis-0402 п. 7): задача без описания и решение без задачи --------------------------------------
# Тик (check --quiet) поднимает две тревоги. Первая: открытая задача больше NO_BODY_HOURS часов только с заголовком и
# журналом — цели и «готово, когда» нет, исполнитель не поймёт, что делать. Вторая: слово владельца с [id] (запись
# decisions.md или вопрос окна вопросов в owner-log) старше UNLINKED_MIN минут, а задачи с таким id или с [id] в теле
# нет и в decisions.md нет отдельной строки «не задача: [id] — причина». Тревога — один раз на id и только о новых:
# что было на первом проходе, запоминается без тревоги (check в pantheon.py, файл unlinked-seen.json).

NO_BODY_HOURS = 1
UNLINKED_MIN = 30
UNLINKED_DAYS = 7  # старше — разбор уже не по тику, а ревизией
OPEN_STATUSES = ("todo", "doing", "review", "waiting")
DEC_ID_RE = re.compile(r"\[([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\](?!\()")
DEC_LINE_RE = re.compile(r"^\s*[-*] (\d{1,2})\.(\d{2})(?: (\d{1,2}):(\d)([\dx]))?")
CREATED_LOG_RE = re.compile(r"^- (\d{4}-\d\d-\d\d \d\d:\d\d) — [^:\n]*: создана", re.M)


def has_description(body):
    """Есть ли у задачи текст кроме заголовка и журнала: что-то между «# …» и первым «## …» или раздел кроме журнала."""
    lines = (body or "").split("\n")
    h = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), -1)
    in_log = in_dw = False
    for ln in lines[h + 1:]:
        if ln.startswith("## "):
            in_dw = ln.startswith(DONE_WHEN_HEAD)  # раздел критериев с подсказкой описанием не считается (metis-0502)
            if not in_dw and not ln.startswith("## Журнал"):
                return True
            in_log = in_log or ln.startswith("## Журнал")
        elif ln.strip() and not in_log and not in_dw:
            return True
    return False


def created_ts(head, body):
    m = CREATED_LOG_RE.search(body or "")
    return ts_of(m.group(1).replace(" ", "T") + ":00") if m else ts_of(head.get("created"))


def is_full_question(head):
    """Вопрос владельцу, суть которого в полях: question, why и не меньше двух вариантов (writing.part)."""
    opts = [o for o in head.get("options") or [] if str(o).strip()]  # пустые --option "" не варианты (argus b2)
    return bool(head.get("question") and head.get("why") and len(opts) >= 2)


def bodyless_tasks(tasks, t, hours=NO_BODY_HOURS):
    """Открытые задачи старше hours часов без описания (полный вопрос владельцу — не в счёт: суть в его полях)."""
    out = []
    for tid, (_, head, body) in sorted(tasks.items()):
        if head.get("type") != "task" or head.get("status") not in OPEN_STATUSES or is_full_question(head):
            continue
        made = created_ts(head, body)
        if made is not None and t - made > hours * 3600 and not has_description(body):
            out.append(tid)
    return out


def _dec_time(m, t):
    day, mon = int(m.group(1)), int(m.group(2))
    hh = int(m.group(3)) if m.group(3) else 0
    mm = int(m.group(4) + m.group(5).replace("x", "0")) if m.group(4) else 0
    year = datetime.fromtimestamp(t).year
    try:
        ts = datetime(year, mon, day, hh, mm).timestamp()
        return ts if ts <= t + 86400 else datetime(year - 1, mon, day, hh, mm).timestamp()
    except ValueError:
        return None


def owner_ids(decisions_text, zeus_log_text, board_lines, t):
    """[(метка времени, id)] из слов владельца: строки decisions.md с временем, вопросы окна вопросов и ответы в чате,
    ответы на доске."""
    out = []
    for ln in (decisions_text or "").split("\n"):
        m = DEC_LINE_RE.match(ln)
        ts = _dec_time(m, t) if m else None
        if ts is not None:
            out += [(ts, i) for i in DEC_ID_RE.findall(ln)]
    # ответ — пометки «окно вопросов» и «ответ в чате» (lib/answers.py HEADS, metis-0405); «… не распознан» — не ответ
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) · (?:окно вопросов|ответ в чате)\s*$",
                             zeus_log_text or "", re.M))
    for k, m in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else len(zeus_log_text)
        q = re.match(r"\s*вопрос: \[([a-z0-9][a-z0-9-]{0,40})\]", zeus_log_text[m.end():end])
        ts = ts_of(m.group(1).replace(" ", "T"))
        if q and ts is not None:
            out.append((ts, q.group(1)))
    for line in board_lines or []:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        ts = ts_of(rec.get("time", "")[:19]) if isinstance(rec, dict) else None
        if ts is not None and rec.get("kind") == "answer" and isinstance(rec.get("id"), str):
            out.append((ts, rec["id"]))
    return out


# id пометки — тот же набор знаков, что у вопроса окна вопросов в owner_ids (без дефиса и с цифры тоже бывает)
NOTASK_RE = re.compile(r"^\s*(?:[-*]\s+)?не задача: \[([a-z0-9][a-z0-9-]{0,40})\] [—–-] \S")
WORD_RE = re.compile(r"[\w-]+")


def task_words(body):
    """Слова текста задачи до «## Журнал»: id в теле связывает задачу со словом владельца, упоминание в журнале — нет."""
    m = re.search(r"^## Журнал", body or "", re.M)
    return WORD_RE.findall((body or "")[:m.start()] if m else (body or ""))


def unlinked_decisions(tasks, decisions_text, zeus_log_text, board_lines, t, minutes=UNLINKED_MIN, days=UNLINKED_DAYS):
    """id слов владельца старше minutes минут (и не старше days дней) без задачи: нет задачи с этим id, id нет в теле
    ни одной задачи до «## Журнал» (статус любой, dropped — тоже решение) и в decisions.md нет отдельной строки
    «не задача: [id] — причина». Слова владельца, цитаты и другие формы слова пометкой не считаются (argus a, b)."""
    cands = {i for ts, i in owner_ids(decisions_text, zeus_log_text, board_lines, t)
             if minutes * 60 < t - ts <= days * 86400}
    words = set()
    for _, _, b in tasks.values():  # один проход по задачам, а не регулярка на каждую пару id × задача
        words.update(task_words(b))
    notask = {m.group(1) for m in map(NOTASK_RE.match, (decisions_text or "").split("\n")) if m}
    return sorted(i for i in cands if i not in tasks and i not in words and i not in notask)


# --- хвосты не теряются (metis-0504, исследование 26.10 разд. 5 пп. 6–7) ---------------------------------------------
# Три тревоги тика рядом с «слово владельца без задачи» (стиль тот же: один раз на ключ, только о новых, первый проход
# — одна сводная тревога без перечня, metis-0572; check в pantheon.py, файл tail-seen.json). (а) Строка журнала задачи со словами «хвост / остаток / не
# сделано / вынесен / позже» без id задачи в этой строке — только предупреждение (эвристика шумит), не блок.
# (б) Файл knowledge/inbox старше суток, на имя которого не ссылается ни одна задача (source/from или текст);
# отчёт с `findings: 0` в шапке — исключение. (в) directions/*/review-*.md с находкой класса Д (строка начинается с «Д»),
# на имя которого не ссылается ни одна задача; тот же срок, что у (б): лид заводит задачи после слияния, не сразу.

TAIL_DAYS = 7  # строка журнала старше — уже не для тика
TAIL_FILE_HOURS = 24
# «остаток недели / лимита / дня» — запас времени или денег, а не недоделанная работа (metis-0572); \b после слова — иначе
# «остатком недели» обходит просмотр откатом \w+ на «остатко»; основы просмотра — только формы существительного:
# «остаток недельного плана», «минутной проверки», «бюджетного модуля», «токенизатора», «временных файлов», «часть» — хвост
TAIL_RE = re.compile(r"хвост\w*|остат(?:ок|к\w+)\b(?!\s+(?:недел(?:ь|я|и|е|ю|ей|ям|ями|ях)\b|дн(?:я|ей|ю|и|ям|ями|ях)\b|месяц(?:а|ы|е|у|ем|ев|ам|ами|ах)?\b|лимит(?:а|ы|е|у|ом|ов|ам|ами|ах)?\b|времени\b|бюджет(?:а|ы|е|у|ом|ов)?\b|токен(?:а|ы|е|у|ом|ов|ам|ами|ах)?\b|минут(?:а|ы|е|у|ой|ам|ами|ах)?\b|час(?:а|ов)?\b))"
                     r"|не сделан\w*|вынесен\w*|позже", re.I)
TAIL_ID_RE = re.compile(r"(?<![\w-])[a-z][a-z0-9]*-\d{2,}(?!\w)")
JOURNAL_LINE_RE = re.compile(r"^- (\d{4}-\d\d-\d\d \d\d:\d\d) — ([^:\n]*): (.*)$")
TAIL_SKIP_ACTORS = ("check",)  # записи самого тика — не слова агента
FINDINGS_ZERO_RE = re.compile(r"^findings:\s*0\s*$", re.M)
D_FINDING_RE = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)?\**Д\d*(?![\w])\**\s*[·.:—–)-]?\s*\S")


TAIL_CLOSED_RE = re.compile(r"(?:закрыт|снят|устранён|устранен|выполнен|доделан|погашен)\w*", re.I)
TAIL_CLEAR_RE = re.compile(r"^(?:→|->|не задача:)", re.I)  # строка-погашение: «→ <id>» или «не задача: …» (metis-0572)
TAIL_BARE_RE = re.compile(r"(?<![\w.-])\d{3,4}(?![\w.-])")  # id без префикса: «0366»
TAIL_OPEN = ("todo", "doing", "review", "waiting")
# строка открытой задачи «из ревью …» / «из review-…» дописывает в неё саму находки ревью, а не оставляет хвост
TAIL_SELF_RE = re.compile(r"^(?:[\d.]+\s+[\d:x]+\s+)?из (?:ревью|review)(?![^\W\d_])", re.I)


def _journal(body):
    """[(время, актор, текст, строка)] журнала задачи: после «## Журнал» до следующего «## »."""
    m = re.search(r"^## Журнал[^\n]*\n", body or "", re.M)
    out = []
    if not m:
        return out
    for ln in (body[m.end():]).split("\n"):
        if ln.startswith("## "):
            break
        jm = JOURNAL_LINE_RE.match(ln)
        if jm:
            out.append((ts_of(jm.group(1).replace(" ", "T") + ":00"), jm.group(2).strip(), jm.group(3), ln.strip()))
    return out


JOURNAL_FUTURE_SLACK = 10 * 60  # с: часы Mac и правка руками расходятся на минуты, а не на часы


def journal_future(tasks, t, slack=JOURNAL_FUTURE_SLACK):
    """Строки журнала открытых задач со временем позже «сейчас» больше чем на slack (metis-0868, п. 5): время строки
    ставит код, а такую дописали руками и время проставили на глаз. → [(id, строка)]."""
    out = []
    for tid, (_, h, body) in sorted(tasks.items()):
        if h.get("status") in ("done", "dropped"):
            continue
        for ts, _, _, ln in _journal(body):
            if ts is not None and ts > t + slack:
                out.append((tid, ln))
    return out


FAILURE_CLASSES = ("непонятная задача", "неверный подход", "не хватило контекста", "трудная логика")
FAILURE_RE = re.compile(r"^провал:\s*([^—\n]*?)\s*(?:—|$)")


def failure_counts(tasks, t, days=7):
    """metis-0859: строки журнала «провал: <класс> — <довод>» за days дней → {класс: [id задач по строкам]}.
    Класс вне четырёх — «прочее». Все четыре ключа есть всегда."""
    out = {c: [] for c in FAILURE_CLASSES}
    since = t - days * 86400
    for tid in sorted(tasks):
        for when, _actor, text, _ln in _journal(tasks[tid][2]):
            m = FAILURE_RE.match(text.strip())
            if not m or when is None or when < since:
                continue
            out.setdefault(m.group(1) if m.group(1) in FAILURE_CLASSES else "прочее", []).append(tid)
    return out


def tail_lines(tasks, t, days=TAIL_DAYS):
    """[(id задачи, строка журнала)] со словами хвоста, не старше days дней. Строки самого тика (actor check) не считаются.
    Не хвост (metis-0572): в строке id другой существующей задачи (в том числе без префикса — «0366», если такая задача
    одна) или «не задача:»; строка открытой задачи о ней самой — её id в строке или «из ревью …» в начале (находки
    дописаны в эту задачу); «остаток недели / лимита / дня» — запас, не работа; остаток закрыт позже в той же задаче
    (строка со словом хвоста и «закрыт/снят/устранён/выполнен…»; такая строка и сама не хвост); позже в той же задаче есть строка «→ …» или «не задача: …»
    — она гасит все прежние хвосты задачи (старую строку править не нужно)."""
    suffix = {}
    for i in tasks:
        suffix.setdefault(i.rsplit("-", 1)[-1], []).append(i)
    out = []
    for tid, (_, head, body) in sorted(tasks.items()):
        if head.get("type") != "task":
            continue
        jl = [x for x in _journal(body) if x[1] not in TAIL_SKIP_ACTORS]
        is_open = head.get("status") in TAIL_OPEN
        for k, (ts, _, text, ln) in enumerate(jl):
            if ts is None or t - ts > days * 86400 or not TAIL_RE.search(text):
                continue
            if is_open and TAIL_SELF_RE.match(text.strip()):  # находки ревью дописаны в саму задачу (metis-0572)
                continue
            # id гасит тревогу, только если такая задача есть и это не сама задача (review-113, x86-64, свой id — не хвост)
            if any(i != tid and i in tasks for i in TAIL_ID_RE.findall(text)):
                continue
            if any(len(suffix.get(b, [])) == 1 and suffix[b][0] != tid for b in TAIL_BARE_RE.findall(text)):
                continue
            if "не задача:" in text.lower() or TAIL_CLOSED_RE.search(text):  # строка о закрытии хвоста — не хвост
                continue
            if is_open and tid in TAIL_ID_RE.findall(text):
                continue
            if any((TAIL_RE.search(x[2]) and TAIL_CLOSED_RE.search(x[2])) or TAIL_CLEAR_RE.match(x[2].strip())
                   for x in jl[k + 1:]):
                continue
            out.append((tid, ln))
    return out


PART_STALL_HOURS = 24
PART_NOTE_RE = re.compile(r"PR #\d+ \([^)]*\) слит, в теле «часть»")


def part_stalled(tasks, t, hours=PART_STALL_HOURS):
    """[(id, строка)] открытые задачи, у которых последняя запись журнала (кроме тика) — «PR слит, в теле «часть»» и она
    старше hours часов: автозакрытие оставило задачу открытой без сигнала (metis-0572, 0503). Любая позже запись
    (агента, владельца) — движение, тревоги нет."""
    out = []
    for tid, (_, head, body) in sorted(tasks.items()):
        if head.get("type") != "task" or head.get("status") not in TAIL_OPEN:
            continue
        jl = [x for x in _journal(body) if x[1] not in TAIL_SKIP_ACTORS]
        # запись плановый проход ставит сам — «движение» после неё только от других авторов
        last = jl[-1] if jl else None
        if last and last[0] is not None and PART_NOTE_RE.search(last[2]) and t - last[0] > hours * 3600:
            out.append((tid, last[3]))
    return out



def part_no_items(tasks):
    """[(id, строка)] открытые задачи, которые слитый PR с «часть» оставил открытыми (строка PART_NOTE_RE в журнале), а
    неотмеченных пунктов «Готово, когда» у них нет (заглушка — не пункт): что осталось сделать, не записано (metis-0615).
    Не тревога и не по времени, как part_stalled: строка в Хвосты.md и свойство «Хвост» карточки, пока у задачи нет
    пункта остатка (вписать его) или она не закрыта. Строка — последняя запись «часть» в журнале."""
    out = []
    for tid, (_, head, body) in sorted(tasks.items()):
        if head.get("type") != "task" or head.get("status") not in TAIL_OPEN:
            continue
        parts = [x for x in _journal(body) if PART_NOTE_RE.search(x[2])]
        if parts and not any(not ok and not _is_stub(text) for ok, text in done_criteria(body)):
            out.append((tid, parts[-1][3]))
    return out

STALL_DAYS = 2
STALL_STATUSES = ("doing", "review")


def stalled(tasks, t, days=STALL_DAYS):
    """[(id, статус, суток)] задачи doing/review без записи в журнале дольше days суток (metis-0583): слито и забыто,
    ждёт живой проверки, брошено. Записи самого check не движение; журнала нет — по updated. Не тревога на каждую:
    список — в Доска/Хвосты.md, на карточку («Хвост») и строкой в сводку pantheon check."""
    out = []
    for tid, (_, head, body) in sorted(tasks.items()):
        if head.get("type") != "task" or head.get("status") not in STALL_STATUSES:
            continue
        marks = [x[0] for x in _journal(body) if x[1] not in TAIL_SKIP_ACTORS and x[0] is not None]
        last = max(marks) if marks else ts_of(head.get("updated"))
        if last is not None and t - last > days * 86400:
            out.append((tid, head["status"], int((t - last) // 86400)))
    return out


def _task_refs(tasks):
    """Слова, на которые ссылаются задачи: поля source и from, заголовок и тело (до и после «## Журнал») целиком."""
    parts = []
    for _, head, body in tasks.values():
        parts += [str(head.get(k) or "") for k in ("source", "from", "title")]
        parts.append(body or "")
    text = "\n".join(parts)
    return text, set(re.findall(r"[\w.-]+", text))


def _file_linked(name, text, words):
    stem = os.path.splitext(name)[0]
    return name in words or stem in words or (("." in stem) and stem in text)


def _listing(d, pattern=None):
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    return [n for n in names if not n.startswith(".") and (pattern is None or pattern.match(n))
            and os.path.isfile(os.path.join(d, n))]


def _old_enough(p, t, hours):
    try:
        return t - os.stat(p).st_mtime > hours * 3600
    except OSError:
        return False


def inbox_orphans(tasks, inbox_dir, t, hours=TAIL_FILE_HOURS):
    """[(путь, 1)] файлы inbox старше hours часов, на имя которых не ссылается ни одна задача; findings: 0 — исключение."""
    text, words = _task_refs(tasks)
    out = []
    for n in _listing(inbox_dir):
        p = os.path.join(inbox_dir, n)
        if not _old_enough(p, t, hours) or _file_linked(n, text, words):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                if FINDINGS_ZERO_RE.search("".join(fh.readline() for _ in range(40))):
                    continue
        except (OSError, UnicodeDecodeError):
            pass  # не текст — ссылки на него всё равно нет
        out.append((p, 1))
    return out


def review_debts(tasks, pantheon, t, hours=TAIL_FILE_HOURS):
    """[(путь, строка первой Д-находки)] из <pantheon>/directions/*/review-*.md, старше hours часов, без ссылки из задач."""
    text, words = _task_refs(tasks)
    rx = re.compile(r"review-.*\.md$")
    out = []
    base = os.path.join(pantheon, "directions")
    for dn in _listing_dirs(base):
        for n in _listing(os.path.join(base, dn), rx):
            p = os.path.join(base, dn, n)
            if not _old_enough(p, t, hours) or _file_linked(n, text, words):
                continue
            try:
                with open(p, encoding="utf-8") as fh:
                    for i, ln in enumerate(fh, 1):
                        if D_FINDING_RE.match(ln):
                            out.append((p, i))
                            break
            except (OSError, UnicodeDecodeError):
                continue
    return out


def _listing_dirs(d):
    try:
        return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)))
    except OSError:
        return []


# --- поле project — только имя проекта из directions.toml (metis-0323) ---------------------------------------------
INBOX_PROJECT = "входящие"  # у карточек владельца и входящих задач своего направления в реестре нет


def load_directions(pantheon):
    """Записи [[direction]] из <pantheon>/directions.toml → список; None — реестра нет, нечитаем или нет tomllib
    (Python < 3.11): тогда project не сверяется, как до metis-0323."""
    try:
        import tomllib
        with open(os.path.join(pantheon, "directions.toml"), "rb") as fh:
            dirs = tomllib.load(fh).get("direction")
    except (ImportError, OSError, ValueError):
        return None
    return [d for d in dirs if isinstance(d, dict)] if isinstance(dirs, list) and dirs else None


def known_projects(dirs):
    return set(project_registry(dirs)) | {INBOX_PROJECT}


def direction_project(dirs, direction):
    """Проект направления по реестру; входящие — «входящие»; направления нет в реестре — None."""
    if direction == "inbox":
        return INBOX_PROJECT
    return next((p for p, r in project_registry(dirs).items() if direction in r["directions"]), None)


def resolve_project(pantheon, direction, project):
    """project новой задачи: пусто → проект направления; чужое имя → ошибка, но направление вне реестра может
    назвать своё имя — как project_ok в check. Реестра нет или он пуст — как раньше."""
    dirs = load_directions(pantheon)
    if dirs is None:
        return project or direction
    if project and not project_ok({"project": project, "direction": direction}, dirs, known_projects(dirs)):
        raise ValueError(f"project «{project[:60]}» — не проект из directions.toml (есть: "
                         f"{', '.join(sorted(known_projects(dirs)))}); без --project берётся проект направления")
    return project or direction_project(dirs, direction) or direction


def project_ok(h, dirs, known):
    """project карточки допустим: имя из реестра, а у направления без записи в реестре — его собственное имя."""
    p, d = h.get("project"), h.get("direction")
    return p in known or (p == d and direction_project(dirs, d) is None)


def project_problems(tasks, dirs):
    """Задачи с project не из реестра → [(id, текст)]. tasks — load_tasks(...)."""
    known = known_projects(dirs)
    return [(tid, f"project «{str(h.get('project'))[:60]}» — не проект из directions.toml; "
                  f"исправить: pantheon task migrate-project")
            for tid, (_, h, _) in sorted(tasks.items()) if not project_ok(h, dirs, known)]


def project_aliases(dirs):
    """Прежнее имя → проект реестра: имена направлений и последние части их папок. Имя, которое ведёт к двум разным
    проектам, и имя, уже являющееся проектом, не берутся."""
    known, found = known_projects(dirs), {}
    for p, r in project_registry(dirs).items():
        names = list(r["directions"])
        for d in dirs:
            if d.get("name") in r["directions"] and isinstance(d.get("folders"), list):
                names += [os.path.basename(str(f).rstrip("/")) for f in d["folders"] if isinstance(f, str)]
        for n in names:
            if n and n not in known:
                found.setdefault(n, set()).add(p)
    return {n: next(iter(ps)) for n, ps in found.items() if len(ps) == 1}


def migrate_projects(pantheon, t, dirs, dry_run=True, actor="агент"):
    """Карточки с project не из реестра → проект по прежнему имени (направление, папка), иначе проект направления
    карточки. Запись — task_set со строкой в журнал и прежним updated: перенос не движение работы, старые закрытые
    карточки не возвращаются на доску и в «Готово за сутки». Повтор ничего не меняет. → (строки «id: было → станет», сбои)."""
    tasks = load_tasks(pantheon, WORK_TYPES)
    known, alias = known_projects(dirs), project_aliases(dirs)
    lines, failed = [], 0
    for tid, (_, h, _) in sorted(tasks.items()):
        old = h.get("project")
        if project_ok(h, dirs, known):
            continue
        new = alias.get(old) or direction_project(dirs, h.get("direction"))
        if new is None:
            lines.append(f"{tid}: {old!r:.70} → не определить (направление {h.get('direction')} не в реестре)")
            failed += 1
            continue
        lines.append(f"{tid}: {old!r:.70} → {new}")
        if not dry_run:
            try:
                task_set(pantheon, t, tid, {"project": new}, note=f"project «{old}» → «{new}» (по directions.toml)",
                         actor=actor, keep_updated=True)
            except ValueError as e:
                lines.append(f"  не записано: {e}")
                failed += 1
    return lines, failed
