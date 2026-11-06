"""Правка файла владельца по «да» в окне вопросов Зевса или по Touch ID — без окна роли (metis-0910, план 0907 (а)).

Слово владельца 06.11 08:53: одно действие на выбор — ответ в окне вопросов Зевса ИЛИ Touch ID, не оба. Роль файл не
пишет: она кладёт заявку, применяет плановый проход (вне окна), и только если файл с заявки не изменился.

  pantheon owner-edit propose <файл> --from <новый текст> --task ID [--why "зачем"]
        заявка: файл из списка FILES, sha256 его байтов сейчас, новый текст целиком (из файла --from), дифф и «sha
        диффа» — sha256 от [файл, sha до, sha после, дифф]. Печатает вопрос для Зевса «[<id>] …» с первыми SHORT
        знаками sha диффа (ответ сверяется по всему тексту вопроса). Заявка из окна роли — owner-edit/ рядом с
        PANTHEON_TMP (кэш окна), вне окна — STATE/owner-edit/queue
  pantheon owner-edit status [ID]   заявки и итоги
  pantheon owner-edit cancel ID     снять свою заявку
  pantheon owner-edit run           проход — только плановый проход (из окна Claude Code — отказ)

Какие файлы (FILES, путь от HOME, ссылки и чужие файлы — отказ): ~/.claude/pantheon/policy.toml и
~/.claude/agents/_parts/<имя>.part — только уже существующие. settings.json здесь нет: autoMode.environment — PR-2,
права и хуки — никогда. Новый текст — UTF-8 без NUL и без невидимых, управляющих и bidi-знаков (HIDDEN, кроме \\n и
\\t; --why — тоже), .toml — разбирается tomllib. Правка в вопросе и окне — shown(): строки «-»/«+» через « ⏎ » (⏎ внутри
строки экранирован), у policy.toml каждая с разделом TOML — «[coordinators] +строка» (у «-» раздел старого текста).

Проход (тик зовёт его отдельным процессом, пока есть заявки; окружение — merge.clean_env, как у слияния). Папка
очереди открыта один раз (open_queue: части пути без ссылок), дальше файлы в ней — только через её fd (dir_fd).
  1. У id заявки уже есть итог в журнале — отказ: та же заявка, положенная снова, второй раз не применяется. Время
     заявки — не позже ctime её файла (дата из текста не продлевает её). Заявка старше REQ_TTL (24 ч) — снята. Файл
     сейчас: sha256 не тот, что в заявке, — отказ «файл изменился после заявки»; дифф и sha диффа пересчитаны из файла
     и нового текста — не сошлись с заявкой — отказ.
  2. «Да» в окне вопросов: consent_found(<id>) — только ответы у Зевса (окно вопросов, ответ в чате; галочка на доске
     не в счёт) не раньше заявки, решает последний. «Да» на вопрос дословно question(заявки) (правка строками и sha
     диффа; пробелы и ёлочки — как пишет хук) — применить; «да» на другой текст (пересказ, другая правка) — отказ;
     не «да» — отклонено.
  3. Иначе Touch ID: владелец у Mac (простой меньше PRESENT_SEC), окно покажет правку целиком (каждая строка «-»/«+»
     диффа после первого «@@», не длиннее WINDOW_MAX, без невидимых знаков) — окно помощника слияния (merge.helper).
     Палец — заявка перечитана, байты те же — строка `<время> owner-edit-approve <id> <sha диффа>` в
     owner-log/owner-edit-approve.log и применить. Отказ — отклонено; время вышло — повтор через RETRY_SEC; окно не
     показать — ждёт «да».
  4. Применить: заявка забирается переименованием, под замком файл перечитан — sha256 тот же, что в заявке (иначе
     отказ без записи), журнал открывается на дописывание (не открыть — файл не трогается), новый текст — атомарно
     (временный файл рядом, права прежние, os.replace), записанное перечитано. Журнал STATE/logs/owner-edit.jsonl
     (пишется первым): id, файл, sha до и после, sha диффа, как согласовано (consent | touchid), итог. Итог роли —
     <id>.result.json рядом с заявкой; не записать — тревога, журнал уже есть.
"""
import contextlib
import difflib
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tomllib
import unicodedata
from datetime import datetime

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()


def set_core(mod):
    global P
    P = mod


FILES = re.compile(r"\.claude/pantheon/policy\.toml|\.claude/agents/_parts/[a-z0-9][a-z0-9_-]{0,60}\.part")
REQ_TTL = 24 * 3600       # заявка старше суток — снята: владелец не ответил
RETRY_SEC = 600           # окно Touch ID закрыто без ответа — следующее не раньше
PRESENT_SEC = 300         # владелец у Mac: простой меньше 5 минут
RESULT_TTL = 7 * 86400
WINDOW_MAX = 400          # предел текста окна у помощника touchid.swift
NEW_MAX = 256 * 1024      # новый текст файла
REQ_MAX = 3 * NEW_MAX + 64 * 1024
WHY_MAX = 160
SHORT = 16                # знаков sha диффа в вопросе Зевса и в окне Touch ID
ID_RE = re.compile(r"oe-\d{8}-\d{6}-[0-9a-f]{6}")
TASK_RE = re.compile(r"[a-z][a-z0-9]{0,30}(?:-[a-z0-9]{1,30}){0,3}-\d{1,6}")
WINDOW_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
ROLE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
HIDDEN = ("Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp")   # как handoff.BAD_CHARS: окно Touch ID их не покажет
SEP = "⏎"            # «⏎» — между строками правки в вопросе и окне; внутри строки — экранирован
ROOT = "(вне таблиц)"     # раздел строк policy.toml до первой таблицы
FINAL = ("done", "failed", "declined", "refused", "dropped")
CANCEL_LABEL = "Не применять"
USAGE = ("pantheon owner-edit propose <файл> --from <новый текст> --task ID [--why \"зачем\"] | status [ID] | "
         "cancel ID | run")


class Refuse(Exception):
    """Заявка не годится: текст — роли и в журнал."""


def err(text, code=2):
    print(text, file=sys.stderr)
    return code


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


# --- файл и дифф -------------------------------------------------------------------------------------------------

def rel_of(arg):
    """Путь из командной строки → путь от HOME из списка FILES или None. «~/…» — от HOME, абсолютный — внутри HOME."""
    if arg.startswith("~/"):
        rel = arg[2:]
    elif os.path.isabs(arg):
        a = os.path.normpath(arg)
        rel = next((a[len(h) + 1:] for h in (P.HOME, os.path.realpath(P.HOME)) if a.startswith(h + "/")), "")
    else:
        rel = arg
    return rel if FILES.fullmatch(rel) else None


def target(rel):
    """Абсолютный путь файла: только из FILES, без ссылок на пути (папки — настоящие, внутри HOME)."""
    if not FILES.fullmatch(rel or ""):
        raise Refuse(f"{rel}: не из списка файлов владельца (policy.toml, ~/.claude/agents/_parts/*.part)")
    home = os.path.realpath(P.HOME)
    p = os.path.join(home, rel)
    if os.path.realpath(os.path.dirname(p)) != os.path.dirname(p):
        raise Refuse(f"~/{rel}: в пути ссылка — не правлю")
    return p


def read_target(rel):
    """Байты файла: обычный файл владельца без ссылки, не больше NEW_MAX. Иначе Refuse."""
    p = target(rel)
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise Refuse(f"~/{rel}: файла нет (новые файлы — не этой командой)")
    except OSError as e:
        raise Refuse(f"~/{rel}: не читается ({e.strerror or type(e).__name__})")
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1:
            raise Refuse(f"~/{rel}: не обычный свой файл")
        data = fh.read(NEW_MAX + 1)
    if len(data) > NEW_MAX:
        raise Refuse(f"~/{rel}: больше {NEW_MAX // 1024} КБ")
    return data


def hidden_at(text, keep="\n\t"):
    """Первый невидимый, управляющий или bidi-знак (категории HIDDEN, кроме keep) → (номер строки, знак) или None.
    Такой знак вопрос Зевсу и окно Touch ID не покажут, а в файл он ляжет (ревью PR #362, круг 2, Д)."""
    for i, c in enumerate(text):
        if c not in keep and unicodedata.category(c) in HIDDEN:
            return text.count("\n", 0, i) + 1, c
    return None


def check_text(rel, new):
    """Новый текст годится для файла: UTF-8 без NUL, не больше NEW_MAX, без невидимых и bidi-знаков (кроме \\n и \\t);
    .toml — разбирается."""
    if not isinstance(new, str) or "\x00" in new or len(new.encode("utf-8")) > NEW_MAX:
        raise Refuse(f"новый текст ~/{rel}: не текст, с NUL или больше {NEW_MAX // 1024} КБ")
    bad = hidden_at(new)
    if bad:
        raise Refuse(f"новый текст ~/{rel}, строка {bad[0]}: невидимый или управляющий знак U+{ord(bad[1]):04X} — "
                     "вопрос и окно Touch ID его не покажут")
    if rel.endswith(".toml"):
        try:
            tomllib.loads(new)
        except tomllib.TOMLDecodeError as e:
            raise Refuse(f"новый текст ~/{rel} — не TOML: {e}")


def make_diff(rel, old, new):
    """Унифицированный дифф старого и нового текста; строка без перевода в конце — с пометкой, как у diff."""
    def lines(text):
        out = text.splitlines(True)
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n\\ нет перевода строки в конце\n"
        return out
    return "".join(difflib.unified_diff(lines(old), lines(new), "a/~/" + rel, "b/~/" + rel, n=2))


def diff_sha(rel, before, after, diff):
    """«sha диффа»: sha256 от файла, sha до, sha после и самого диффа — связывает показанное с тем, что запишется."""
    return sha(json.dumps([rel, before, after, diff], ensure_ascii=False))


def walk(diff):
    """[(строка «-»/«+» диффа без перевода, её номер от 0 в старом тексте у «-» / в новом у «+», или None)]. Заголовки
    ---/+++ — только до первого «@@»: дальше «+++ …» — добавленная строка «++ …», а не заголовок, и её владелец видит
    (ревью PR #362, Б1). Номера — от заголовка ханка «@@ -a,b +c,d @@» (у пустого диапазона difflib пишет начало − 1)."""
    out, o, n, body = [], None, None, False
    for ln in diff.splitlines():
        if ln.startswith("@@"):
            body, m = True, HUNK.match(ln)
            o = n = None
            if m:
                o = int(m[1]) - (m[2] != "0")
                n = int(m[3]) - (m[4] != "0")
        elif body and ln[:1] in "+-":
            i = o if ln[0] == "-" else n
            out.append((ln, i))
            if i is not None:
                if ln[0] == "-":
                    o += 1
                else:
                    n += 1
        elif body and ln[:1] == " " and o is not None:
            o, n = o + 1, n + 1
    return out


def changes(diff):
    """Строки «-»/«+» диффа, переводы строк сняты (порядок и набор — как в walk)."""
    return [ln for ln, _ in walk(diff)]


def old_text(rel, new, diff):
    """Старый текст из нового и диффа (обратно по ханкам) или None: make_diff от него не даёт тот же дифф."""
    newl, rows = new.splitlines(True), diff.splitlines()
    out, pos, body = [], 0, False
    for k, ln in enumerate(rows):
        m = HUNK.match(ln) if ln.startswith("@@") else None
        if ln.startswith("@@"):
            if not m:
                return None
            start = int(m[3]) - (m[4] != "0")
            out += newl[pos:start]
            pos, body = start, True
        elif body and ln[:1] in " -":
            out.append(ln[1:] + ("" if k + 1 < len(rows) and rows[k + 1].startswith("\\") else "\n"))
            pos += ln[0] == " "
        elif body and ln[:1] == "+":
            pos += 1
    old = "".join(out + newl[pos:])
    return old if make_diff(rel, old, new) == diff else None


def _probe_path(obj, key, path=()):
    """Путь таблицы, где лежит ключ-проба key, или None."""
    if isinstance(obj, dict):
        if key in obj and path:
            return path
        items = obj.items()
    elif isinstance(obj, list):
        items = ((None, v) for v in obj)
    else:
        return None
    for k, v in items:
        got = _probe_path(v, key, path + (k,))
        if got is not None:
            return got
    return None


def _label(path):
    parts = [k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=bool(hidden_at(k, "")))
             for k in path if k is not None]
    return ("[[{}]]" if path[-1] is None else "[{}]").format(".".join(parts))


def toml_sections(text):
    """Раздел TOML каждой строки text (элементы splitlines(True)) → [подпись] или None: text не TOML. Заголовок — строка
    «[…]», после которой вставленный ключ-проба ложится в таблицу (tomllib): «[x]» внутри многострочной строки или
    массива — не заголовок. До первой таблицы — ROOT."""
    if text is None:
        return None
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    elems, key = text.splitlines(True), "oe_probe"
    while key in text:
        key += "_"
    out, cur = [], ROOT
    for i, ln in enumerate(elems):
        if ln.lstrip().startswith("["):
            probe = "".join(elems[:i + 1]) + ("" if ln.endswith("\n") else "\n") + f"{key} = 1\n" + "".join(elems[i + 1:])
            with contextlib.suppress(tomllib.TOMLDecodeError):
                path = _probe_path(tomllib.loads(probe), key)
                if path:
                    cur = _label(path)
        out.append(cur)
    return out


def shown(req):
    """Строки правки, как их видит владелец, по одной: у policy.toml — с разделом TOML «[таблица] +строка» (у «-» —
    раздел в старом тексте, у «+» — в новом; не определить — «[?]»): одна строка в [sandbox_write] и в [coordinators]
    даёт разные права (ревью PR #362, круг 2, Б). Знак-разделитель SEP внутри строки — экранирован."""
    rows = walk(req["diff"])
    if req["file"].endswith(".toml"):
        new = req.get("new")
        secs = {"+": toml_sections(new) if isinstance(new, str) else None,
                "-": toml_sections(old_text(req["file"], new, req["diff"])) if isinstance(new, str) else None}

        def sec(ln, i):
            s = secs[ln[0]]
            return s[i] if s is not None and i is not None and 0 <= i < len(s) else "[?]"
        rows = [(f"{sec(ln, i)} {ln}", i) for ln, i in rows]
    return [ln.replace(SEP, "\\u23ce") for ln, _ in rows]


def one_line(s):
    """Как хук окна вопросов и ответ в чате пишут вопрос в owner-log (answers._one_line): «→» и ёлочки — пробел, все
    пробелы и переводы строк — один пробел."""
    return re.sub(r"\s+", " ", re.sub(r"[→«»]", " ", s or "")).strip()


def window_text(req):
    """Текст окна Touch ID — правка целиком, или None: окно её целиком не покажет (тогда только «да» в окне вопросов)."""
    rows = shown(req)
    text = (f"Правка ~/{req['file']} (заявка {req['id']}, {req.get('window') or 'вне окна'}, {req['task']}, sha "
            f"{req['diff_sha'][:SHORT]}), строк {len(rows)}: " + f" {SEP} ".join(rows))
    return text if P.handoff_mod().showable(text) and len(text) <= WINDOW_MAX else None


def question(req):
    """Вопрос для Зевса: [id], файл, sha диффа, зачем, правка строками (shown) через « ⏎ »: вопрос — одна строка (хук
    окна вопросов сводит переводы строк в пробел), а SEP внутри строки правки экранирован — «ok; -Правило» не читается
    как вторая строка (ревью PR #362, круг 2, Д)."""
    why = f" Зачем: {req['why']}." if req.get("why") else ""
    rows = shown(req)
    return (f"[{req['id']}] Применить правку ~/{req['file']} (задача {req['task']}, sha диффа "
            f"{req['diff_sha'][:SHORT]})?{why} Правка, строк {len(rows)}: " + f" {SEP} ".join(rows))


def facts(req):
    """Сверка заявки с файлом сейчас: sha до тот же, дифф и sha диффа сходятся. → байты файла; иначе Refuse."""
    cur = read_target(req["file"])
    if sha(cur) != req["before"]:
        raise Refuse(f"~/{req['file']} изменился после заявки (sha {sha(cur)[:12]}, в заявке {req['before'][:12]}) — "
                     "новая заявка от нового текста")
    check_text(req["file"], req["new"])
    after = sha(req["new"])
    diff = make_diff(req["file"], cur.decode("utf-8", "replace"), req["new"])
    if after != req["after"] or diff != req["diff"] or diff_sha(req["file"], req["before"], after, diff) != req["diff_sha"]:
        raise Refuse("заявка не сходится с файлом и новым текстом (дифф или sha диффа) — не применяю")
    return cur


# --- очередь ------------------------------------------------------------------------------------------------------

def own_dir():
    """Папка заявок этого вызова: в окне роли — owner-edit/ рядом с PANTHEON_TMP (кэш окна), иначе STATE."""
    tmp = os.environ.get("PANTHEON_TMP")
    if tmp:
        return os.path.join(os.path.dirname(os.path.realpath(tmp)), "owner-edit")
    return P.path("owner-edit", "queue")


def caches():
    return os.path.join(P.HOME, "Library", "Caches", "pantheon-sandbox")


def _is_dir(p):
    try:
        return stat.S_ISDIR(os.lstat(p).st_mode)
    except OSError:
        return False


def queue_dirs():
    """[(папка, окно)]: окно None — очередь STATE, иначе имя окна по папке кэша (не из текста заявки)."""
    out = [(P.path("owner-edit", "queue"), None)]
    with contextlib.suppress(OSError):
        for name in sorted(os.listdir(caches())):
            d = os.path.join(caches(), name, "owner-edit")
            if WINDOW_RE.fullmatch(name) and _is_dir(d) and not os.path.islink(os.path.join(caches(), name)):
                out.append((d, name))
    return out


def open_queue(win):
    """Папка очереди (окно None — STATE/owner-edit/queue, иначе кэш окна <win>/owner-edit) → fd или None: открыта один
    раз, каждая часть пути после корня (STATE, кэш окон) — O_NOFOLLOW; файлы в ней read_file проверяет на «свой».
    Дальше проход пишет и удаляет только через этот fd (dir_fd): папку, подменённую ссылкой после открытия, он не
    видит (ревью PR #362, Д dir_fd)."""
    base, parts = (P.path(), ("owner-edit", "queue")) if win is None else (caches(), (win, "owner-edit"))
    try:
        fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return None
    try:
        for part in parts:
            nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
    except OSError:
        os.close(fd)
        return None
    return fd


def read_file(path, limit=REQ_MAX, dir_fd=None):
    """Обычный свой файл без ссылок → байты; иначе None. dir_fd — path от этой папки."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_size > limit:
            return None
        return fh.read(limit + 1)


def valid(req, name):
    return isinstance(req, dict) and ID_RE.fullmatch(str(req.get("id"))) is not None \
        and name == f"{req['id']}.req.json" and FILES.fullmatch(str(req.get("file"))) is not None \
        and all(HEX64.fullmatch(str(req.get(k))) for k in ("before", "after", "diff_sha")) \
        and all(isinstance(req.get(k), str) for k in ("new", "diff", "task", "why")) \
        and TASK_RE.fullmatch(req["task"]) is not None and isinstance(req.get("created"), (int, float))


def load_req(path, dir_fd=None):
    raw = read_file(path, dir_fd=dir_fd)
    if raw is None:
        return None, None
    with contextlib.suppress(ValueError):
        req = json.loads(raw)
        if valid(req, os.path.basename(path)):
            return req, raw
    return None, raw


def write_atomic(path, data, dir_fd=None):
    """JSON атомарно: временный файл со случайным хвостом рядом (O_EXCL, без ссылок), os.replace. dir_fd — path от
    этой папки, папку не создаёт. Сбой — временный файл убран, исключение дальше."""
    if dir_fd is None:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp, dir_fd=dir_fd)
        raise


def who():
    role = os.environ.get("PANTHEON_ROLE") or ""
    tmp = os.environ.get("PANTHEON_TMP")
    win = os.path.basename(os.path.dirname(os.path.realpath(tmp))) if tmp else None
    return (win if win and WINDOW_RE.fullmatch(win) else None), (role if ROLE_RE.fullmatch(role) else None)


def journal_open():
    """Журнал STATE/logs/owner-edit.jsonl на дописывание (без ссылки). Не открыть — OSError."""
    os.makedirs(P.path("logs"), exist_ok=True)
    fd = os.open(P.path("logs", "owner-edit.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "a", encoding="utf-8")


def journal(rec):
    rec = dict(rec, time=datetime.fromtimestamp(P.now()).astimezone().isoformat(timespec="seconds"))
    with journal_open() as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def finished(rid):
    """У заявки rid уже есть итог в журнале (любой из FINAL): ту же заявку, положенную снова, проход не применяет —
    одно «да» или палец — одно применение (ревью PR #362, повтор). Журнала нет — False; не читается — OSError дальше:
    без журнала повтор не отличить, заявка ждёт."""
    try:
        fh = open(P.path("logs", "owner-edit.jsonl"), encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False
    with fh:
        for ln in fh:
            if rid not in ln:
                continue
            with contextlib.suppress(ValueError):
                rec = json.loads(ln)
                if isinstance(rec, dict) and rec.get("id") == rid and rec.get("state") in FINAL:
                    return True
    return False


def finish(dfd, req, state, note, **extra):
    """Итог: сначала журнал (он — правда о применении), потом <id>.result.json роли в папке очереди (dfd). Итог роли не
    записать (на месте папка, нет места) — тревога, журнал уже есть (ревью PR #362, Д1)."""
    journal(dict({"id": req["id"], "file": req.get("file"), "task": req.get("task"), "role": req.get("role"),
                  "window": req.get("window"), "diff_sha": req.get("diff_sha"), "state": state,
                  "note": str(note)[:400]}, **extra))
    try:
        write_atomic(f"{req['id']}.result.json", {"id": req["id"], "state": state, "note": str(note)[:400],
                                                  "t": P.now()}, dir_fd=dfd)
    except OSError as e:
        P.alert_once("owner-edit-result", type(e).__name__, f"правка файла владельца: итог {req['id']} ({state}) роли "
                     f"не записан — {type(e).__name__}: {e}; в журнале logs/owner-edit.jsonl он есть", "owner-edit")


# --- команды роли -------------------------------------------------------------------------------------------------

def parse_opts(args, known):
    pos, kv, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if a in known:
            if i + 1 >= len(args) or a in kv:
                raise ValueError(f"{a}: нужно одно значение")
            kv[a] = args[i + 1]
            i += 1
        elif a.startswith("--"):
            raise ValueError(f"неизвестный флаг {a}")
        else:
            pos.append(a)
        i += 1
    return pos, kv


def cmd_propose(args):
    try:
        pos, kv = parse_opts(args, ("--from", "--task", "--why"))
    except ValueError as e:
        return err(f"pantheon owner-edit propose: {e}")
    if len(pos) != 1 or "--from" not in kv or not TASK_RE.fullmatch(kv.get("--task", "")):
        return err("вызов: " + USAGE.split(" | ")[0])
    rel = rel_of(pos[0])
    why = " ".join(kv.get("--why", "").split())
    try:
        if rel is None:
            raise Refuse(f"{pos[0]}: не из списка файлов владельца (~/.claude/pantheon/policy.toml, "
                         "~/.claude/agents/_parts/<имя>.part)")
        if len(why) > WHY_MAX:
            raise Refuse(f"--why длиннее {WHY_MAX} знаков")
        if hidden_at(why, ""):
            raise Refuse(f"--why: невидимый или управляющий знак U+{ord(hidden_at(why, '')[1]):04X} — вопрос его не "
                         "покажет")
        raw_new = read_file(kv["--from"], NEW_MAX)
        if raw_new is None:
            raise Refuse(f"{kv['--from']}: не читается, ссылка или больше {NEW_MAX // 1024} КБ")
        try:
            new = raw_new.decode("utf-8")
        except UnicodeDecodeError:
            raise Refuse(f"{kv['--from']}: не UTF-8")
        check_text(rel, new)
        cur = read_target(rel)
        try:
            old = cur.decode("utf-8")
        except UnicodeDecodeError:
            raise Refuse(f"~/{rel}: не UTF-8")
    except Refuse as e:
        return err(f"pantheon owner-edit propose: отказ — {e}")
    if old == new:
        return err(f"pantheon owner-edit propose: новый текст совпадает с ~/{rel} — править нечего")
    win, role = who()
    before, after = sha(cur), sha(new)
    diff = make_diff(rel, old, new)
    req = {"id": "oe-" + datetime.fromtimestamp(P.now()).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3),
           "file": rel, "before": before, "after": after, "diff": diff, "diff_sha": diff_sha(rel, before, after, diff),
           "new": new, "task": kv["--task"], "why": why, "role": role, "created": P.now()}
    try:
        write_atomic(os.path.join(own_dir(), f"{req['id']}.req.json"), req)
    except OSError as e:
        return err(f"pantheon owner-edit propose: заявку не записать ({e})", 3)
    touch = window_text(dict(req, window=win))
    print(f"заявка {req['id']}: ~/{rel}, sha до {before[:12]}, sha диффа {req['diff_sha']}\n\n{diff}\n"
          f"Вопрос Зевсу (окно вопросов, варианты «А — Да, применить» и «Б — Нет»), строка целиком:\n  {question(req)}\n"
          + ("Или Touch ID: плановый проход покажет окно с этой правкой, когда владелец у Mac.\n" if touch else
             "Окно Touch ID правку целиком не покажет — только «да» в окне вопросов.\n")
          + f"Применит плановый проход, если ~/{rel} до того не изменится. Итог — pantheon owner-edit status {req['id']}")
    return 0


def read_result(d, rid):
    raw = read_file(os.path.join(d, f"{rid}.result.json"), 64 * 1024)
    with contextlib.suppress(TypeError, ValueError):
        r = json.loads(raw)
        return r if isinstance(r, dict) else None
    return None


def cmd_status(args):
    rows = []
    for d, win in queue_dirs() if not os.environ.get("PANTHEON_TMP") else [(own_dir(), who()[0])]:
        with contextlib.suppress(OSError):
            for n in sorted(os.listdir(d)):
                m = re.fullmatch(r"(oe-\d{8}-\d{6}-[0-9a-f]{6})\.(req|result)\.json", n)
                if not m or (args and m.group(1) != args[0]):
                    continue
                if m.group(2) == "req":
                    req, _ = load_req(os.path.join(d, n))
                    if req:
                        rows.append(f"{m.group(1)}  ждёт «да» или Touch ID  {win or 'вне окна'}  ~/{req['file']}  "
                                    f"sha диффа {req['diff_sha'][:SHORT]}")
                else:
                    res = read_result(d, m.group(1)) or {}
                    rows.append(f"{m.group(1)}  {res.get('state')}  {win or 'вне окна'}  {str(res.get('note'))[:200]}")
    print("\n".join(rows) if rows else "заявок нет")
    return 0


def cmd_cancel(args):
    if len(args) != 1 or not ID_RE.fullmatch(args[0]):
        return err("вызов: pantheon owner-edit cancel ID")
    try:
        os.unlink(os.path.join(own_dir(), f"{args[0]}.req.json"))
    except OSError:
        return err(f"заявки {args[0]} в своей очереди нет", 1)
    print(f"заявка {args[0]} снята")
    return 0


# --- проход -------------------------------------------------------------------------------------------------------

def ask(text):
    """Окно Touch ID помощника слияния: 0 палец, 1 отказ, 2 не показать, 3 время вышло, None — помощника нет."""
    M = P.merge_mod()
    h = M.helper()
    if not h:
        return None
    try:
        return subprocess.run([h, text, str(M.WINDOW_WAIT), CANCEL_LABEL], stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=M.WINDOW_WAIT + 60).returncode
    except (OSError, subprocess.SubprocessError):
        return 2


def consent_decision(req):
    """Последний ответ владельца у Зевса на «[<id>] …» не раньше заявки → (вердикт, заголовок) или None — ответа нет.
    Вердикт: yes — «да», и вопрос дословно question(req) (с правкой строками и sha диффа); wrong — «да» на другой текст
    (пересказ правки с верным sha — тоже: ревью PR #362, Д2); no — не «да». Сверка — после one_line с обеих сторон:
    так хук пишет вопрос в owner-log."""
    days = min(30.0, max(0.1, (P.now() - req["created"]) / 86400 + 0.01))
    found, _, _ = P.consent_found(req["id"], days)
    own = [(t, head, body) for t, head, body in found if head.endswith(" у Зевса") and t >= int(req["created"])]
    if not own:
        return None
    _, head, body = own[-1]
    if not P.consent_is_yes(body):
        return "no", head
    q = one_line(body.split("\nответ:")[0].removeprefix("вопрос:"))
    if q != one_line(question(req)):
        return "wrong", head
    return "yes", head


def approve_line(req):
    d = P.path("owner-log")
    if os.path.islink(d):
        raise OSError("owner-log — ссылка")
    os.makedirs(d, mode=0o700, exist_ok=True)
    line = (f"{datetime.fromtimestamp(P.now()).astimezone().isoformat(timespec='seconds')} owner-edit-approve "
            f"{req['id']} {req['diff_sha']}\n")
    fd = os.open(os.path.join(d, "owner-edit-approve.log"), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
                 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(line)


def apply(dfd, name, req, how, evidence):
    """Одно применение: заявка забрана переименованием, под замком файл тот же (sha до) и журнал пишется — новый текст
    атомарно."""
    taken = f"{name}.taken"
    try:
        os.rename(name, taken, src_dir_fd=dfd, dst_dir_fd=dfd)
    except OSError:
        return None
    try:
        with P.lock("owner-edit-apply"):
            facts(req)
            journal_open().close()   # журнал не дописать — файл не трогаю: правка без записи в журнале (Д1)
            if how == "touchid":
                approve_line(req)
            p = target(req["file"])
            mode = stat.S_IMODE(os.lstat(p).st_mode)
            tmp = os.path.join(os.path.dirname(p), f".{os.path.basename(p)}.owner-edit.{os.getpid()}")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(req["new"].encode("utf-8"))
            os.chmod(tmp, mode)
            os.replace(tmp, p)
            got = sha(read_target(req["file"]))   # в журнал — то, что легло на диск, а не то, что ждали
        return finish(dfd, req, "done", f"применено ({'«да» в окне вопросов' if how == 'consent' else 'Touch ID'}): "
                      f"~/{req['file']} sha {req['before'][:12]} → {got[:12]}", how=how, before=req["before"],
                      after=got, evidence=evidence)
    except Refuse as e:
        return finish(dfd, req, "refused", str(e), how=how)
    except OSError as e:
        return finish(dfd, req, "failed", f"{type(e).__name__}: {e}"[:300], how=how)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(taken, dir_fd=dfd)


def retry_mark(req):
    return P.path("owner-edit", "retry", req["id"])


def drop(dfd, name, req, state, note):
    with contextlib.suppress(OSError):
        os.unlink(name, dir_fd=dfd)
    return finish(dfd, req, state, note)


def process(dfd, win, name):
    req, raw = load_req(name, dir_fd=dfd)
    if req is None:
        with contextlib.suppress(OSError):
            os.unlink(name, dir_fd=dfd)
        return None
    req["window"] = win   # окно — по месту папки заявки, не из её текста
    if finished(req["id"]):
        return drop(dfd, name, req, "refused", "итог этой заявки уже в журнале — та же заявка второй раз не "
                    "применяется; новая правка — новая заявка и новый вопрос")
    # время заявки — не позже времени её файла (ctime ставит система, окно его вперёд не сдвинет): дата из текста
    # заявки в будущем не держит её дольше REQ_TTL (ревью PR #362, Д created)
    try:
        req["created"] = min(req["created"], os.stat(name, dir_fd=dfd, follow_symlinks=False).st_ctime)
    except OSError:
        return None
    if P.now() - req["created"] > REQ_TTL:
        return drop(dfd, name, req, "dropped", f"заявка старше {REQ_TTL // 3600} ч без ответа — снята")
    try:
        facts(req)
    except Refuse as e:
        return drop(dfd, name, req, "refused", str(e))
    try:
        said = consent_decision(req)
    except P.ConsentLogError as e:
        P.alert_once("owner-edit-consent", type(e).__name__, f"правка файла владельца: {e}", "owner-edit")
        said = None
    if said and said[0] == "yes":
        return apply(dfd, name, req, "consent", said[1])
    if said and said[0] == "no":
        return drop(dfd, name, req, "declined", f"владелец ответил не «да» ({said[1]})")
    if said:
        return drop(dfd, name, req, "refused", f"«да» на вопрос не дословно из propose (sha диффа "
                    f"{req['diff_sha'][:SHORT]}) — это ответ не на эту правку; новая заявка и вопрос строкой целиком")
    text = window_text(req)
    if text is None or P.idle_sec() > PRESENT_SEC:
        return None
    with contextlib.suppress(OSError):
        if P.now() - os.stat(retry_mark(req)).st_mtime < RETRY_SEC:
            return None
    code = ask(text)
    if code is None or code == 2:
        P.alert_once("owner-edit-window", str(code), "правка файла владельца: окно Touch ID не показать — заявки ждут "
                     "«да» в окне вопросов", "owner-edit")
        return None
    if code == 3:
        os.makedirs(os.path.dirname(retry_mark(req)), mode=0o700, exist_ok=True)
        with open(retry_mark(req), "w"):
            pass
        return None
    if code != 0:
        return drop(dfd, name, req, "declined", "владелец отказал в окне Touch ID")
    req2, raw2 = load_req(name, dir_fd=dfd)
    if req2 is None or raw2 != raw:
        return drop(dfd, name, req, "dropped", "заявку сменили или сняли, пока окно было открыто — палец не засчитан")
    req2["window"] = win   # байты те же — и текст окна тот же, что видел владелец
    return apply(dfd, name, req2, "touchid", "Touch ID")


def sweep(dfd):
    with contextlib.suppress(OSError):
        for n in os.listdir(dfd):
            if n.endswith(".result.json"):
                with contextlib.suppress(OSError):
                    if P.now() - os.stat(n, dir_fd=dfd, follow_symlinks=False).st_mtime > RESULT_TTL:
                        os.unlink(n, dir_fd=dfd)


def pending():
    """Есть заявка для прохода."""
    for d, _ in queue_dirs():
        with contextlib.suppress(OSError):
            if any(n.endswith(".req.json") for n in os.listdir(d)):
                return True
    return False


def cmd_run():
    if "CLAUDECODE" in os.environ or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        return err("pantheon owner-edit run: только плановый проход, не из окна Claude Code")
    why = P.merge_mod().clean_env()   # HOME, STATE и PATH — с нуля, не из launchd-окружения (как у слияния)
    if why:
        return err(f"pantheon owner-edit run: {why} — окружение прохода подменено, прохода нет")
    rc = 0
    with P.lock("owner-edit-run", block=False) as got:
        if not got:
            return 0
        for _, win in queue_dirs():
            dfd = open_queue(win)   # папка — один раз, дальше только dir_fd: ссылка вместо неё не уводит запись
            if dfd is None:
                continue
            try:
                names = sorted(n for n in os.listdir(dfd) if n.endswith(".req.json"))
                for n in names:
                    try:
                        process(dfd, win, n)
                    except Exception as e:  # noqa: BLE001 — одна заявка не останавливает остальные
                        rc = 1
                        P.alert_once("owner-edit-run", type(e).__name__, f"правка файла владельца: заявка {n} — "
                                     f"{type(e).__name__}: {e}", "owner-edit")
                sweep(dfd)
            except OSError:
                continue
            finally:
                os.close(dfd)
    return rc


def main(rest):
    if not rest:
        return err(USAGE)
    cmd, args = rest[0], rest[1:]
    if cmd == "propose":
        return cmd_propose(args)
    if cmd == "status":
        return cmd_status(args)
    if cmd == "cancel":
        return cmd_cancel(args)
    if cmd == "run" and not args:
        return cmd_run()
    return err(USAGE)
