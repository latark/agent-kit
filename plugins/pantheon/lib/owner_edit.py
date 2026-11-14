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
  pantheon policy set <раздел> <ключ> <значение>... --task ID [--why "зачем"] [--list]
        (metis-1122) та же заявка на ~/.claude/pantheon/policy.toml, но текст собирает команда: ключ раздела = значение
        (true/false и числа — как есть, остальное — строка; несколько значений или --list — массив). Строка ключа
        заменена, нет ключа — дописан в конец раздела, нет раздела — раздел в конец файла; прочий текст не тронут.
        Значение ключа на нескольких строках — отказ (правка — owner-edit propose). Применяет тот же проход.

Какие файлы (FILES, путь от HOME, ссылки и чужие файлы — отказ): ~/.claude/pantheon/policy.toml и
~/.claude/agents/_parts/<имя>.part — только уже существующие. settings.json здесь нет: autoMode.environment — PR-2,
права и хуки — никогда. Новый текст — UTF-8 без NUL и без невидимых, управляющих и bidi-знаков (HIDDEN, кроме \\n и
\\t; --why — тоже, и ещё не длиннее WHY_MAX и без лишних пробелов: why_ok, его повторяет и valid() прохода). .toml —
сравнение по смыслу (toml_keys): старый и новый текст разобраны tomllib, каждый изменённый ключ правит своя строка
«-»/«+» (тронутый заголовок таблицы правит её ключи, только если таблица добавлена или убрана: «[ private ]» — нет);
ключ сменился без своей строки (строку контекста проглотила многострочная строка, удалён заголовок таблицы) или текст
не TOML — отказ в propose и в проходе. Правка в вопросе и окне — shown(): строки «-»/«+» через « ⏎ » (⏎ внутри строки
экранирован), каждая с разделом (у «-» — раздел старого текста): у policy.toml — таблица TOML «[coordinators]
+строка», у .part — заголовок «[## Можно] +строка». У policy.toml за ними «Ключи, изменено N: путь: старое → новое»
(key_rows) — смысл правки целиком. Знаки: у policy.toml в строках и ключах каждый знак вне печатного ASCII — \\uXXXX
(esc: «е» кириллицей в латинском пути видна); у .part русский текст как есть, слово из двух алфавитов — «[смешаны
алфавиты: m\\u0430in]», прочее вне ASCII и русского — \\uXXXX (mark); строка-комментарий policy.toml — тоже mark. --why — последним, «Пояснение роли: …». Вопрос в
чате — через md (каждый знак ASCII-пунктуации с «\\»: `, *, ~, [ ] видны буквально), окно Touch ID — без md. Разделы
.part — по CommonMark: «#» с отступом до 3 пробелов, setext, блоки ``` и ~~~.

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
import string
import subprocess
import sys
import tomllib
import unicodedata
from datetime import datetime, timedelta

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()


def set_core(mod):
    global P
    P = mod


FILES = re.compile(r"\.claude/pantheon/(?:policy|grants)\.toml|\.claude/agents/_parts/[a-z0-9][a-z0-9_-]{0,60}\.part")
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
PART_ROOT = "(вне разделов)"   # раздел строк .part до первого заголовка «#»
MISSING = object()        # ключа нет в старом или новом тексте (toml_changes)
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
        raise Refuse(f"{rel}: не из списка файлов владельца (policy.toml, grants.toml, ~/.claude/agents/_parts/*.part)")
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
        if rel == GRANTS_REL:   # grants.toml заводит первая заявка pantheon grant request (metis-0680)
            return b""
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


def _dotted(path):
    """Путь ключа «a.b."в"» только печатным ASCII: ключ в кавычках — JSON с \\uXXXX (кириллица в ключе видна)."""
    return ".".join(k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k) for k in path if k is not None)


RU = re.compile(r"[А-Яа-яЁё]")
TYPO = frozenset("«»—–…№“”„‘’→")   # знаки русского текста .part, которые показываются как есть


def _u(c):
    return f"\\u{ord(c):04x}" if ord(c) <= 0xFFFF else f"\\U{ord(c):08x}"


def esc(s):
    """Каждый знак вне печатного ASCII — \\uXXXX: «е» кириллицей в латинском пути видна (ревью PR #362, R3 Б1)."""
    return "".join(c if " " <= c <= "~" else _u(c) for c in s)


MD_PUNCT = frozenset(string.punctuation)   # вся ASCII-пунктуация: CommonMark экранирует её «\» (раздел 2.4)


def md(s):
    """Текст из файла для вопроса в чате: каждый знак ASCII-пунктуации — с «\\» перед ним. Отрисовка Markdown (CommonMark,
    GFM) выдаёт его буквально: ни `код`, ни *курсив*, ни ~зачёркнутое~, ни [ссылка](…) не прячут знаков, а «**» и «__»,
    которые сверка ответа в чате вырезает (answers._strip_md), в тексте не остаются (ревью PR #362, R4-2 Б1). Окну Touch
    ID — без md: оно Markdown не рисует."""
    return "".join("\\" + c if c in MD_PUNCT else c for c in s)


def _script(c):
    return unicodedata.name(c, "?").split(" ")[0]


def mark(s):
    """Строка .part для вопроса и окна: русский текст законен и остаётся читаемым, поэтому экранируется не всё (как esc),
    а только чужое. Слово, где буквы двух алфавитов (латиница и кириллица, греческие), — «[смешаны алфавиты: m\\u0430in]»;
    знак вне печатного ASCII, русского алфавита и TYPO — \\uXXXX (і, ѕ, ο и прочие двойники латиницы)."""
    def word(m):
        w = m[0]
        return f"[смешаны алфавиты: {esc(w)}]" if len({_script(c) for c in w if c.isalpha()}) > 1 else w
    s = re.sub(r"\w+", word, s)
    return "".join(c if " " <= c <= "~" or RU.fullmatch(c) or c in TYPO else _u(c) for c in s)


def _label(path):
    if not path:
        return ROOT
    return ("[[{}]]" if path[-1] is None else "[{}]").format(_dotted(path))


def toml_paths(text):
    """Таблица TOML каждой строки text (элементы splitlines(True)) → [(путь, заголовок ли)] или None: text не TOML.
    Путь — кортеж ключей, None — элемент массива таблиц «[[…]]», () — до первой таблицы. Заголовок — строка «[…]»,
    после которой вставленный ключ-проба ложится в таблицу (tomllib): «[x]» внутри многострочной строки или массива — не
    заголовок."""
    if text is None:
        return None
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    elems, key = text.splitlines(True), "oe_probe"
    while key in text:
        key += "_"
    out, cur = [], ()
    for i, ln in enumerate(elems):
        head = False
        if ln.lstrip().startswith("["):
            probe = "".join(elems[:i + 1]) + ("" if ln.endswith("\n") else "\n") + f"{key} = 1\n" + "".join(elems[i + 1:])
            with contextlib.suppress(tomllib.TOMLDecodeError):
                path = _probe_path(tomllib.loads(probe), key)
                if path:
                    cur, head = path, True
        out.append((cur, head))
    return out


def toml_sections(text):
    """Раздел TOML каждой строки text → [подпись «[таблица]», «[[массив]]» или ROOT] или None: text не TOML."""
    paths = toml_paths(text)
    return None if paths is None else [_label(p) for p, _ in paths]


def _key_of(line):
    """Путь ключа строки «ключ = …» (голый, в кавычках, через точку) или None. Ключ — разбор tomllib начала строки до
    одного из «=»: «=» внутри кавычек ключа такое начало не разбирает."""
    s = line.strip()
    if not s or s[0] in "#[":
        return None
    for m in re.finditer("=", s):
        try:
            obj = tomllib.loads(s[:m.start()] + "= 0\n")
        except tomllib.TOMLDecodeError:
            continue
        path = ()
        while isinstance(obj, dict) and len(obj) == 1:
            k, obj = next(iter(obj.items()))
            path += (k,)
        return path or None
    return None


def _exists(obj, path):
    if not path:
        return True
    if path[0] is None:
        return isinstance(obj, list) and any(_exists(e, path[1:]) for e in obj)
    return isinstance(obj, dict) and path[0] in obj and _exists(obj[path[0]], path[1:])


def _leaves(obj, path=()):
    """(путь, значение) каждого ключа-листа: таблицы раскрыты, массив (и массив таблиц) — одно значение, пустая таблица
    — лист {}."""
    if isinstance(obj, dict) and (obj or not path):
        for k, v in obj.items():
            yield from _leaves(v, path + (k,))
    else:
        yield path, obj


def _canon(v, ascii_=False):
    """Значение TOML одной строкой JSON: тип различим (1, 1.0, true, "1", дата), невидимые знаки — экранированы."""
    s = json.dumps(v, ensure_ascii=ascii_, sort_keys=True, default=lambda o: {"$" + type(o).__name__: o.isoformat()})
    return _canon(v, True) if not ascii_ and hidden_at(s, "") else s


def _owner(lines, secs, obj, i):
    """Ключ (путь), который правит строка i диффа: заголовок таблицы — её путь; иначе ближайшая строка «ключ = …» на i
    или выше в той же таблице, чей ключ в разборе этого текста есть (строка внутри многострочного значения — его ключ).
    Не нашёлся — None."""
    for j in range(i, -1, -1):
        sec, head = secs[j]
        if head:
            return sec if j == i else None
        key = _key_of(lines[j])
        if key and _exists(obj, sec + key):
            return sec + key
    return None


def toml_changes(old, new):
    """Изменённые ключи двух текстов TOML (разбор tomllib) → [(путь, старое, новое)], MISSING — ключа нет. Порядок —
    как в старом тексте, новые ключи — в конце. Текст не TOML — TOMLDecodeError."""
    lo, ln = dict(_leaves(tomllib.loads(old))), dict(_leaves(tomllib.loads(new)))
    return [(p, lo.get(p, MISSING), ln.get(p, MISSING)) for p in list(lo) + [p for p in ln if p not in lo]
            if p not in lo or p not in ln or _canon(lo[p]) != _canon(ln[p])]


def key_row(path, old, new):
    """«путь: старое → новое»; путь и значения — только печатным ASCII (не-ASCII — \\uXXXX, R3 Б1)."""
    show = (lambda v: "нет" if v is MISSING else _canon(v, True))
    return f"{_dotted(path)}: {show(old)} → {show(new)}"


def toml_keys(rel, old, new, diff=None):
    """Правка .toml по смыслу (ревью PR #362, R2 Б1): старый и новый текст разобраны tomllib, каждый изменённый ключ
    должен править своя строка «-»/«+» диффа (_owner: строка «ключ = …», строка его многострочного значения, заголовок
    его таблицы). Ключ сменился без своей строки — строка контекста ушла в другой ключ или раздел (её проглотила
    добавленная многострочная строка, удалён заголовок таблицы) — Refuse; текст не TOML — Refuse. → строки «путь: старое
    → новое» (key_row) — их владелец видит в вопросе и окне Touch ID: смысл правки показан целиком, даже если сверка
    строк что-то пропустит."""
    try:
        changed = toml_changes(old, new)
        secs = {"-": toml_paths(old), "+": toml_paths(new)}
        objs = {"-": tomllib.loads(old), "+": tomllib.loads(new)}
    except tomllib.TOMLDecodeError as e:
        raise Refuse(f"~/{rel}: старый или новый текст не TOML ({e}) — ключи не сравнить, не правлю")
    lines = {"-": old.splitlines(True), "+": new.splitlines(True)}
    heads = {s: [p for p, h in secs[s] if h] for s in secs}
    owners = []
    for ln, i in walk(make_diff(rel, old, new) if diff is None else diff):
        if i is not None and 0 <= i < len(lines[ln[0]]):
            sec, head = secs[ln[0]][i]
            if head and heads["-"].count(sec) == heads["+"].count(sec):
                continue   # заголовок тронут, а таблица та же («[ private ]») — ключи таблицы он не правит (R3-1 Д1)
            k = _owner(lines[ln[0]], secs[ln[0]], objs[ln[0]], i)
            if k is not None:
                owners.append(k[:k.index(None)] if None in k else k)
    loose = [p for p, _, _ in changed if not any(p[:len(k)] == k or k[:len(p)] == p for k in owners)]
    if loose:
        raise Refuse(f"~/{rel}: правка меняет {', '.join(_dotted(p) for p in loose[:5])} без своей строки «-»/«+» — "
                     "строка контекста ушла в другой ключ или раздел (многострочная строка, заголовок таблицы); не правлю")
    return [key_row(*c) for c in changed]


def key_rows(req):
    """Изменённые ключи заявки для вопроса и окна: у .toml — key_row каждого (старый текст — из нового и диффа), не
    сравнить — ["?"]; у .part — None."""
    if not req["file"].endswith(".toml"):
        return None
    new = req.get("new")
    old = old_text(req["file"], new, req["diff"]) if isinstance(new, str) else None
    try:
        return [key_row(*c) for c in toml_changes(old, new)] if old is not None else ["?"]
    except tomllib.TOMLDecodeError:
        return ["?"]


def keys_text(req, fix=str):
    rows = key_rows(req)
    if rows is None:
        return ""
    return f". Ключи, изменено {len(rows)}: " + (f" {SEP} ".join(fix(r) for r in rows) if rows else "нет")


FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)$")
ATX_RE = re.compile(r" {0,3}#{1,6}(?:[ \t]|$)")
SETEXT_RE = re.compile(r" {0,3}(=+|-+)[ \t]*$")
BREAK_RE = re.compile(r" {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
BLOCK_RE = re.compile(r" {0,3}(?:>|[-+*](?:[ \t]|$)|\d{1,9}[.)](?:[ \t]|$))|    |\t")


def part_sections(text):
    """Раздел .part каждой строки text → [«[## Заголовок]» (mark) или PART_ROOT до первого] по правилам CommonMark:
    заголовок «#…» с отступом до 3 пробелов и setext — абзац, подчёркнутый «===» (как «#») или «---» (как «##»); строки
    заголовка — его раздел. Внутри блока ``` или ~~~ (закрывает тот же знак, не короче) заголовков нет; строка с отступом
    4 пробела — код; «---» после пустой строки, пункта списка или цитаты — черта, а не заголовок (R4-2 Д1). text None —
    None."""
    if text is None:
        return None
    lines = text.splitlines()
    out, cur, fence, para, other = [], PART_ROOT, None, None, False
    for i, ln in enumerate(lines):
        out.append(cur)
        f = FENCE_RE.match(ln)
        if fence:
            if f and f[1][0] == fence[0] and len(f[1]) >= len(fence) and not f[2].strip():
                fence = None
            continue
        if not ln.strip():
            para, other = None, False
        elif f and not (f[1][0] == "`" and "`" in f[2]):
            fence, para, other = f[1], None, False
        elif ATX_RE.match(ln):
            cur = out[-1] = f"[{mark(ln.strip())}]"
            para, other = None, False
        elif SETEXT_RE.match(ln) and para is not None:
            head = " ".join(x.strip() for x in lines[para:i])
            cur = f"[{'#' if ln.strip()[0] == '=' else '##'} {mark(head)}]"
            out[para:] = [cur] * (i + 1 - para)
            para = None
        elif BREAK_RE.match(ln):
            para, other = None, False
        elif para is None and not other:
            if BLOCK_RE.match(ln):
                other = True
            else:
                para = i
        elif para is not None and BLOCK_RE.match(ln) and not ln.startswith(("    ", "\t")):
            para, other = None, True   # пункт списка или цитата прерывают абзац: «---» под ними — черта
    return out


def toml_comment(text, i, base=None):
    """Строка i текста TOML — целиком комментарий: начинается с «#», и без неё разбор tomllib тот же («#» внутри
    многострочной строки — часть значения, не комментарий). base — готовый разбор text."""
    lines = text.splitlines(True)
    if not 0 <= i < len(lines) or not lines[i].lstrip().startswith("#"):
        return False
    try:
        return tomllib.loads("".join(lines[:i] + lines[i + 1:])) == (tomllib.loads(text) if base is None else base)
    except tomllib.TOMLDecodeError:
        return False


def shown(req):
    """Строки правки, как их видит владелец, по одной, с разделом: у policy.toml — «[таблица] +строка» (одна строка в
    [sandbox_write] и в [coordinators] даёт разные права, ревью PR #362, круг 2, Б), у .part — «[## Можно] +строка»
    (перенос строки из «## Нельзя» в «## Можно» виден, R3-2 Д1). У «-» — раздел в старом тексте, у «+» — в новом; не
    определить — «[?]». Сама строка у .toml — esc (каждый знак вне печатного ASCII — \\uXXXX: в TOML любой знак может
    быть путём; строка-комментарий toml_comment — mark, русский комментарий читаем, R4-1 Д1), у .part — mark (русский
    текст как есть, смешанные алфавиты помечены). SEP внутри строки — экранирован."""
    new = req.get("new")
    old = old_text(req["file"], new, req["diff"]) if isinstance(new, str) else None
    toml = req["file"].endswith(".toml")
    split = toml_sections if toml else part_sections
    texts = {"+": new if isinstance(new, str) else None, "-": old}
    secs = {s: split(t) for s, t in texts.items()}

    def sec(ln, i):
        s = secs[ln[0]]
        return s[i] if s is not None and i is not None and 0 <= i < len(s) else "[?]"

    base = {}

    def comment(ln, i):
        t = texts[ln[0]]
        if t is None or i is None or not ln[1:].lstrip().startswith("#"):
            return False
        with contextlib.suppress(tomllib.TOMLDecodeError):
            if ln[0] not in base:
                base[ln[0]] = tomllib.loads(t)
            return toml_comment(t, i, base[ln[0]])
        return False

    def fix(ln, i):
        return esc(ln) if toml and not comment(ln, i) else mark(ln)
    return [f"{sec(ln, i)} {fix(ln, i)}".replace(SEP, "\\u23ce") for ln, i in walk(req["diff"])]


def one_line(s):
    """Как хук окна вопросов и ответ в чате пишут вопрос в owner-log (answers._one_line): «→» и ёлочки — пробел, все
    пробелы и переводы строк — один пробел."""
    return re.sub(r"\s+", " ", re.sub(r"[→«»]", " ", s or "")).strip()


def window_text(req):
    """Текст окна Touch ID — правка целиком, или None: окно её целиком не покажет (тогда только «да» в окне вопросов)."""
    rows = shown(req)
    text = (f"Правка ~/{req['file']} (заявка {req['id']}, {req.get('window') or 'вне окна'}, {req['task']}, sha "
            f"{req['diff_sha'][:SHORT]}), строк {len(rows)}: " + f" {SEP} ".join(rows) + keys_text(req))
    return text if P.handoff_mod().showable(text) and len(text) <= WINDOW_MAX else None


def question(req):
    """Вопрос для Зевса: [id], файл, sha диффа, правка строками (shown) через « ⏎ », ключи и последним — «Пояснение
    роли: …» (--why, mark): после правки и с меткой он не подделает её начало «Правка, строк 0: …» (R3-2 С). Вопрос —
    одна строка (хук окна вопросов сводит переводы строк в пробел), а SEP внутри строки правки экранирован — «ok;
    -Правило» не читается как вторая строка (ревью PR #362, круг 2, Д). Вопрос идёт в чат, а чат рисует Markdown: всё,
    что пришло из файла и от роли (путь, строки правки с разделами, ключи, --why), — через md, каждый знак ASCII-
    пунктуации экранирован и виден буквально (R4-2 Б1). «[id]» в начале — как есть: по нему сверка ищет вопрос."""
    why = f". Пояснение роли: {md(mark(req['why']))}" if req.get("why") else ""
    rows = [md(r) for r in shown(req)]
    return (f"[{req['id']}] Применить правку {md('~/' + req['file'])} (задача {req['task']}, sha диффа "
            f"{req['diff_sha'][:SHORT]})? Правка, строк {len(rows)}: " + f" {SEP} ".join(rows) + keys_text(req, md)
            + why)


def facts(req):
    """Сверка заявки с файлом сейчас: sha до тот же, дифф и sha диффа сходятся. → байты файла; иначе Refuse."""
    cur = read_target(req["file"])
    if sha(cur) != req["before"]:
        raise Refuse(f"~/{req['file']} изменился после заявки (sha {sha(cur)[:12]}, в заявке {req['before'][:12]}) — "
                     "новая заявка от нового текста")
    check_text(req["file"], req["new"])
    after = sha(req["new"])
    old = cur.decode("utf-8", "replace")
    diff = make_diff(req["file"], old, req["new"])
    if after != req["after"] or diff != req["diff"] or diff_sha(req["file"], req["before"], after, diff) != req["diff_sha"]:
        raise Refuse("заявка не сходится с файлом и новым текстом (дифф или sha диффа) — не применяю")
    if req["file"].endswith(".toml"):
        toml_keys(req["file"], old, req["new"], diff)   # и у заявки, положенной в очередь мимо propose (R2 Б1)
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


def why_ok(why):
    """--why годится в вопрос владельцу: не длиннее WHY_MAX, без невидимых, управляющих и bidi-знаков (\\n и \\t — тоже),
    пробелы — по одному и не по краям (так его сводит propose). Проверяют и propose, и проход (valid): заявку, записанную
    прямо в очередь мимо propose, тоже (ревью PR #362, R2 Б2)."""
    return len(why) <= WHY_MAX and hidden_at(why, "") is None and why == " ".join(why.split())


def valid(req, name):
    return isinstance(req, dict) and ID_RE.fullmatch(str(req.get("id"))) is not None \
        and name == f"{req['id']}.req.json" and FILES.fullmatch(str(req.get("file"))) is not None \
        and all(HEX64.fullmatch(str(req.get(k))) for k in ("before", "after", "diff_sha")) \
        and all(isinstance(req.get(k), str) for k in ("new", "diff", "task", "why")) \
        and TASK_RE.fullmatch(req["task"]) is not None and isinstance(req.get("created"), (int, float)) \
        and why_ok(req["why"])


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
    except Refuse as e:
        return err(f"pantheon owner-edit propose: отказ — {e}")
    return _propose(rel, new, kv["--task"], why, "pantheon owner-edit propose")


def _propose(rel, new, task, why, prog, cur=None):
    """Заявка на новый текст файла владельца (общая часть owner-edit propose и policy set) → код выхода."""
    try:
        check_text(rel, new)
        cur = read_target(rel) if cur is None else cur
        try:
            old = cur.decode("utf-8")
        except UnicodeDecodeError:
            raise Refuse(f"~/{rel}: не UTF-8")
        if rel.endswith(".toml") and old != new:
            toml_keys(rel, old, new)
    except Refuse as e:
        return err(f"{prog}: отказ — {e}")
    if old == new:
        return err(f"{prog}: новый текст совпадает с ~/{rel} — править нечего")
    win, role = who()
    before, after = sha(cur), sha(new)
    diff = make_diff(rel, old, new)
    req = {"id": "oe-" + datetime.fromtimestamp(P.now()).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3),
           "file": rel, "before": before, "after": after, "diff": diff, "diff_sha": diff_sha(rel, before, after, diff),
           "new": new, "task": task, "why": why, "role": role, "created": P.now()}
    try:
        write_atomic(os.path.join(own_dir(), f"{req['id']}.req.json"), req)
    except OSError as e:
        return err(f"{prog}: заявку не записать ({e})", 3)
    touch = window_text(dict(req, window=win))
    print(f"заявка {req['id']}: ~/{rel}, sha до {before[:12]}, sha диффа {req['diff_sha']}\n\n{diff}\n"
          f"Вопрос Зевсу (окно вопросов, варианты «А — Да, применить» и «Б — Нет»), строка целиком:\n  {question(req)}\n"
          + ("Или Touch ID: плановый проход покажет окно с этой правкой, когда владелец у Mac.\n" if touch else
             "Окно Touch ID правку целиком не покажет — только «да» в окне вопросов.\n")
          + f"Применит плановый проход, если ~/{rel} до того не изменится. Итог — pantheon owner-edit status {req['id']}")
    return 0


# --- pantheon policy set: одна правка policy.toml заявкой (metis-1122) ----------------------------------------------

POLICY_REL = ".claude/pantheon/policy.toml"
POLICY_USAGE = ("pantheon policy set <раздел> <ключ> <значение>... --task ID [--why \"зачем\"] [--list]")
SECTION_RE = re.compile(r"[A-Za-z0-9_-]{1,60}(?:\.[A-Za-z0-9_-]{1,60}){0,3}")
KEY_RE = re.compile(r"[A-Za-z0-9_-]{1,80}")
HEADER_RE = re.compile(r"\s*\[\s*([^\[\]#]*?)\s*\]\s*(?:#.*)?")


def toml_literal(v):
    """Значение из командной строки → текст TOML: true/false и числа — как есть, остальное — строка в кавычках.
    Перевод строки, \\r и другие знаки HIDDEN — Refuse: «число» с переводом строки дописало бы в policy.toml чужие
    ключи и разделы (ревью PR #437, Б1)."""
    bad = hidden_at(v, "")
    if bad:
        raise Refuse(f"значение {v[:40]!r}: перевод строки или невидимый знак U+{ord(bad[1]):04X} — "
                     "одно значение пишется в одну строку")
    try:
        got = tomllib.loads(f"v = {v}")["v"]
    except tomllib.TOMLDecodeError:
        got = None
    if isinstance(got, (bool, int, float)) and v.strip() == v:
        return v
    return json.dumps(v, ensure_ascii=False)


def policy_text(old, section, key, values, as_list=False):
    """policy.toml с ключом key раздела section = values (одно — скаляр, несколько или as_list — массив). Остальной
    текст — как был: строка ключа заменена, нет ключа — дописан в конец раздела, нет раздела — раздел в конец файла.
    Значение ключа на нескольких строках — Refuse: такую правку — owner-edit propose."""
    if not SECTION_RE.fullmatch(section) or not KEY_RE.fullmatch(key):
        raise Refuse(f"раздел {section!r} или ключ {key!r} не по образцу (латиница, цифры, «_», «-»; раздел — с «.»)")
    if not values or any(not str(v).strip() for v in values):
        raise Refuse("нет значения: pantheon policy set <раздел> <ключ> <значение>...")
    lits = [toml_literal(str(v)) for v in values]
    value = f"[{', '.join(lits)}]" if as_list or len(lits) > 1 else lits[0]
    line = f"{key} = {value}\n"
    lines = old.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    head = next((i for i, ln in enumerate(lines)
                 if (m := HEADER_RE.fullmatch(ln.rstrip("\n"))) and m[1].replace(" ", "") == section), None)
    if head is None:
        lines += (["\n"] if lines and lines[-1].strip() else []) + [f"[{section}]\n", line]
    else:
        end = next((i for i in range(head + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
        kre = re.compile(r"\s*(?:" + re.escape(key) + r'|"' + re.escape(key) + r'")\s*=')
        at = next((i for i in range(head + 1, end) if kre.match(lines[i])), None)
        if at is not None:
            try:
                tomllib.loads(lines[at])
            except tomllib.TOMLDecodeError:
                raise Refuse(f"[{section}] {key}: значение на нескольких строках — правьте через pantheon owner-edit "
                             "propose")
            lines[at] = line
        else:
            last = max([i for i in range(head, end) if lines[i].strip()] or [head])
            lines.insert(last + 1, line)
    new = "".join(lines)
    # сверка целиком: новый файл равен старому всюду, кроме [section][key] (ревью PR #437, Б1)
    try:
        want = tomllib.loads(old)
        got = want
        for part in section.split("."):
            got = got.setdefault(part, {})
        got[key] = tomllib.loads(f"v = {value}")["v"]
        ok = tomllib.loads(new) == want
    except (tomllib.TOMLDecodeError, KeyError, TypeError, AttributeError) as e:
        raise Refuse(f"[{section}] {key}: правка не легла в TOML ({type(e).__name__}: {e})")
    if not ok:
        raise Refuse(f"[{section}] {key}: после правки файл отличается не только этим ключом — правьте через "
                     "pantheon owner-edit propose")
    return new


def cmd_policy(rest):
    """pantheon policy set: роль не пишет policy.toml — команда кладёт заявку owner-edit, применяет плановый проход по
    «да» владельца на вопрос с [id] или по Touch ID (как owner-edit propose)."""
    prog = "pantheon policy set"
    if rest[:1] != ["set"]:
        return err("вызов: " + POLICY_USAGE)
    args = [a for a in rest[1:] if a != "--list"]
    try:
        pos, kv = parse_opts(args, ("--task", "--why"))
    except ValueError as e:
        return err(f"{prog}: {e}")
    if len(pos) < 3 or not TASK_RE.fullmatch(kv.get("--task", "")):
        return err("вызов: " + POLICY_USAGE)
    why = " ".join(kv.get("--why", "").split())
    try:
        if len(why) > WHY_MAX or hidden_at(why, ""):
            raise Refuse(f"--why длиннее {WHY_MAX} знаков или с невидимым знаком")
        cur = read_target(POLICY_REL)
        try:
            old = cur.decode("utf-8")
        except UnicodeDecodeError:
            raise Refuse(f"~/{POLICY_REL}: не UTF-8")
        new = policy_text(old, pos[0], pos[1], pos[2:], "--list" in rest[1:])
    except Refuse as e:
        return err(f"{prog}: отказ — {e}")
    return _propose(POLICY_REL, new, kv["--task"], why, prog, cur)


# --- pantheon grant request: право окну заявкой, а не пересказом владельцу (metis-0680) ----------------------------

GRANTS_REL = ".claude/pantheon/grants.toml"
GRANT_USAGE = ("pantheon grant request [--write <путь>]... [--allow <правило>]... [--domain <домен>]... [--days N] "
               "--task ID --why \"зачем\"")
GRANT_FLAGS = {"--write": "write", "--allow": "allow", "--domain": "domains"}
GRANT_DAYS_MAX = 30


def grant_text(old, win, lists, until, task, why):
    """grants.toml с новой записью [[grant]] в конце; прочий текст не тронут."""
    lines = [f"\n[[grant]]   # {task}, заявка из окна {win}", f"window = {json.dumps(win)}", f"until = \"{until}\"",
             f"why = {json.dumps(why, ensure_ascii=False)}"]
    lines += [f"{k} = [{', '.join(json.dumps(x, ensure_ascii=False) for x in v)}]" for k, v in lists.items() if v]
    return (old if not old or old.endswith("\n") else old + "\n") + "\n".join(lines) + "\n"


def cmd_grant(rest):
    """pantheon grant request: роль не пишет grants.toml — команда кладёт заявку owner-edit с одной записью [[grant]]
    своему окну; «да» в окне вопросов Зевса или Touch ID — проход пишет файл, сборка окна применяет право до срока."""
    prog = "pantheon grant request"
    if rest[:1] != ["request"]:
        return err("вызов: " + GRANT_USAGE)
    lists, kv, args, i = {v: [] for v in GRANT_FLAGS.values()}, {}, rest[1:], 0
    while i < len(args):
        a = args[i]
        if i + 1 >= len(args) or not (a in GRANT_FLAGS or a in ("--days", "--task", "--why")) or a in kv:
            return err(f"{prog}: {a} — неизвестный флаг, повтор или нет значения. Вызов: {GRANT_USAGE}")
        if a in GRANT_FLAGS:
            lists[GRANT_FLAGS[a]].append(args[i + 1])
        else:
            kv[a] = args[i + 1]
        i += 2
    why = " ".join(kv.get("--why", "").split())
    win = who()[0]
    try:
        if not win:
            raise Refuse("только из окна роли: право выдаётся окну, где идёт заявка")
        if not TASK_RE.fullmatch(kv.get("--task", "")) or not why or not why_ok(why) or not any(lists.values()):
            raise Refuse(f"нужны --task, --why (до {WHY_MAX} знаков) и хоть одно из --write, --allow, --domain")
        if any(hidden_at(x, "") for v in lists.values() for x in v):
            raise Refuse("невидимый или управляющий знак в значении")
        days = int(kv.get("--days", "7")) if kv.get("--days", "7").isdigit() else 0
        if not 1 <= days <= GRANT_DAYS_MAX:
            raise Refuse(f"--days — целое от 1 до {GRANT_DAYS_MAX}")
        until = (datetime.fromtimestamp(P.now()) + timedelta(days=days - 1)).strftime("%Y-%m-%d")
        cur = read_target(GRANTS_REL)
        try:
            old = cur.decode("utf-8")
        except UnicodeDecodeError:
            raise Refuse(f"~/{GRANTS_REL}: не UTF-8")
        new = grant_text(old, win, lists, until, kv["--task"], why)
        _, _, errors, _ = P.grants_load(new[len(old):])   # та же проверка, что у сборки окна: ключи, конфиг — нет
        if errors:
            raise Refuse("; ".join(errors))
    except Refuse as e:
        return err(f"{prog}: отказ — {e}")
    return _propose(GRANTS_REL, new, kv["--task"], why, prog, cur)


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
            mode = stat.S_IMODE(os.lstat(p).st_mode) if os.path.lexists(p) else 0o644   # grants.toml — первой заявкой
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
