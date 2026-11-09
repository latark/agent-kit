"""Проверка и архив ~/ai/pantheon/board.md (metis-0769).

`problems(text, t, journal=None)` — тревоги `pantheon check`: раздел «Сейчас» длиннее NOW_MAX знаков; ручное «Обновлено
ДД.ММ ЧЧ:ММ» в нём старше свежего журнала STATUS (journal — его время; больше NOW_BEHIND_HOURS часов отставания,
metis-1005) или, когда журнала нет, старше суток; пункты «По датам» с прошедшей датой срока. Даты в ручном разделе
не требуется: время «Сейчас» собирает board-auto.md (lib/boardtext.py now_line).
`split(text, t, days)` — блоки старше days дней из разделов ARCHIVE_SECTIONS: (оставшийся текст, {ГГГГ-ММ: [строки]}).
Без потерь: оставшийся текст и перенесённые строки вместе дают все строки исходного. Блок — строка списка с датой
в начале («- 03.11 03:17 …», «- 2026-11-03 …») и следующие за ней строки с отступом.

Только стандартная библиотека; файлы не читает и не пишет (это делает pantheon.py: board_md_check, board_archive).
"""
import re
from datetime import datetime, timedelta

NOW_MAX = 9000                       # знаков в разделе «Сейчас»
STALE_HOURS = 24                     # «Обновлено» старше — тревога (журнала STATUS нет)
NOW_BEHIND_HOURS = 6                 # «Обновлено» старше свежего журнала STATUS на столько — тревога (metis-1005)
ARCHIVE_SECTIONS = ("Сейчас", "Сессии и хозяйство")  # где лежит журнал датированных блоков
DEFAULT_DAYS = 7
HEAD_RE = re.compile(r"^##[ \t]+(.*?)[ \t]*$")
UPD_RE = re.compile(r"Обновлено\s+(\d{1,2})\.(\d{2})(?:\.(\d{4}))?(?:\s+(\d{1,2}):(\d{2}))?")
DATE_RU = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{2})(?:\.(\d{4}))?(?![\d.])")
RANGE_RU = re.compile(r"(?<![\d.])(\d{1,2})\s*[–-]\s*(\d{1,2})\.(\d{2})(?![\d.])")
BLOCK_START = re.compile(r"^[-*][ \t]+(?:\*\*)?(?:(\d{4})-(\d{2})-(\d{2})|(\d{1,2})\.(\d{2})(?:\.(\d{4}))?(?![\d.]))")


def sections(text):
    """[(заголовок, первая строка, после последней строки)] по строкам `## …`; строки — индексы в text.split('\\n')."""
    lines = text.split("\n")
    heads = [(i, m.group(1)) for i, ln in enumerate(lines) if (m := HEAD_RE.match(ln))]
    return [(name, i, heads[k + 1][0] if k + 1 < len(heads) else len(lines)) for k, (i, name) in enumerate(heads)]


def section(text, name):
    """Текст раздела `## name` (с заголовком до следующего `## `), нет раздела — None."""
    lines = text.split("\n")
    for n, a, b in sections(text):
        if n == name or n.startswith(name + " "):
            return "\n".join(lines[a:b])
    return None


def _date(day, mon, year, t, due=False):
    """Дата без года — текущего года. Метка времени («Обновлено»), уехавшая в будущее больше чем на сутки, — прошлого года;
    срок (due), ушедший в прошлое больше чем на 300 дней, — следующего (в декабре «15.01» ещё впереди). ГГГГ из текста — как есть."""
    now = datetime.fromtimestamp(t)
    try:
        d = datetime(int(year) if year else now.year, int(mon), int(day))
    except ValueError:
        return None
    if not year and not due and d > now + timedelta(days=1):
        d = d.replace(year=d.year - 1)
    if not year and due and d < now - timedelta(days=300):
        d = d.replace(year=d.year + 1)
    return d


def due_date(cell, t):
    """Последняя дата ячейки «Срок» («27.10», «15–17.10», «9.11 (или 18.11)»); дат нет («после беты», «январь 2027») — None."""
    found = []
    for m in RANGE_RU.finditer(cell):
        found.append(_date(m.group(2), m.group(3), None, t, True))
    spans = [m.span() for m in RANGE_RU.finditer(cell)]
    for m in DATE_RU.finditer(cell):
        if not any(a <= m.start() < b or a < m.end() <= b for a, b in spans):
            found.append(_date(m.group(1), m.group(2), m.group(3), t, True))
    found = [d for d in found if d]
    return max(found) if found else None


def dated_rows(text):
    """Пункты «По датам»: [(ячейка срока, остаток строки)] — строки таблицы и пункты списка."""
    sec = section(text, "По датам")
    out = []
    for ln in (sec or "").split("\n")[1:]:
        s = ln.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) >= 2 and not re.fullmatch(r"[-: ]+", cells[0]) and cells[0].strip("* ") != "Срок":
                out.append((cells[0], cells[1]))
        elif re.match(r"^[-*][ \t]+", s):
            body = re.sub(r"^[-*][ \t]+", "", s)
            out.append((body[:40], body[40:]))
    return out


def problems(text, t, journal=None):
    """→ [(ключ, значение, сообщение)]: значение меняется, когда меняется суть (новая тревога), ключ — вид проверки."""
    out = []
    now_sec = section(text, "Сейчас")
    if now_sec is not None:
        n = len(now_sec)
        if n > NOW_MAX:
            out.append(("size", str(n // 1000), f"board.md: раздел «Сейчас» {n} знаков при пределе {NOW_MAX} — "
                        "старое вынести: pantheon board archive"))
        m = UPD_RE.search(now_sec)
        d = _date(m.group(1), m.group(2), m.group(3), t) if m else None
        if d is not None:
            d = d.replace(hour=int(m.group(4)), minute=int(m.group(5))) if m.group(4) and int(m.group(4)) < 24 \
                and int(m.group(5)) < 60 else d.replace(hour=23, minute=59)  # дата без времени — конец дня
        if d is not None:
            ref, hours = (journal, NOW_BEHIND_HOURS) if journal is not None else (t, STALE_HOURS)
            if ref - d.timestamp() > hours * 3600:
                stamp = d.strftime("%d.%m %H:%M")
                out.append(("updated", stamp, f"board.md: «Обновлено {stamp}» старше {STALE_HOURS} ч — обновить раздел «Сейчас»"
                            if journal is None else f"board.md: «Обновлено {stamp}» старше свежего журнала STATUS "
                            f"({datetime.fromtimestamp(journal).strftime('%d.%m %H:%M')}) больше чем на {hours} ч — владелец "
                            "файла (Зевс): обновить раздел «Сейчас» или убрать старое: pantheon board archive"))
    today = datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0, microsecond=0)
    late = []
    for cell, rest in dated_rows(text):
        d = due_date(cell, t)
        if d is not None and d < today:
            late.append(f"{cell.strip('* ')[:30]} — {rest.strip()[:40]}")
    if late:
        out.append(("dates", "|".join(late), f"board.md «По датам»: срок прошёл у {len(late)} пунктов — "
                    + "; ".join(late[:3]) + (f" и ещё {len(late) - 3}" if len(late) > 3 else "")))
    return out


def block_date(line, t):
    m = BLOCK_START.match(line)
    if not m:
        return None
    if m.group(1):
        return _date(m.group(3), m.group(2), m.group(1), t)
    return _date(m.group(4), m.group(5), m.group(6), t)


def split(text, t, days=DEFAULT_DAYS, only=ARCHIVE_SECTIONS):
    """→ (оставшийся текст, {ГГГГ-ММ: [строки перенесённых блоков]}). Блок старше days дней — датой в начале строки."""
    lines = text.split("\n")
    take = set()
    cutoff = datetime.fromtimestamp(t).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
    moved = {}
    for name, a, b in sections(text):
        if name not in only:
            continue
        i = a + 1
        while i < b:
            d = block_date(lines[i], t)
            if d is None or d >= cutoff:
                i += 1
                continue
            j = i + 1
            while j < b and lines[j][:1] in (" ", "\t") and lines[j].strip():
                j += 1
            take.update(range(i, j))
            moved.setdefault(d.strftime("%Y-%m"), []).extend(lines[i:j])
            i = j
    kept = [ln for k, ln in enumerate(lines) if k not in take]
    return "\n".join(kept), moved
