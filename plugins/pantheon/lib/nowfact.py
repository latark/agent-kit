"""«Сейчас» из факта (metis-1005, п. 2 metis-0829): время журнала STATUS.md и разбор ручных разделов с датой.

Журнал STATUS.md — раздел «Ход», «Начато / сделано» или «Журнал»: строки вида «13:5x текст», «08.11 12:56 текст»,
«- 06.11 06:23 начато: …», «До 08.11 12:56 — архив». Время без даты — дата ближайшей выше строки с датой (без неё —
дата правки файла). Минуты «5x» — последняя из возможных (59), как в lib/watch.py now_section_time. Переход через
полночь модуль не угадывает: берётся самое позднее время среди строк. Год — текущий, дата из будущего больше чем на
сутки — прошлого года.

- `journal_time(text, mtime, t)` — время последней строки журнала или None (журнала нет / строк со временем нет);
- `display(ts)` — «ДД.ММ ЧЧ:Мx» (десятки минут: так пишут руками, и шапка не переписывается каждую минуту);
- `retime_head(text, stamp)` — текст с заголовком `## Сейчас (ДД.ММ ЧЧ:Мx)` по времени журнала; заголовок с чужим
  суффиксом не трогается; `(новый текст, изменён ли)`;
- `dated_manual(text, t)` — ручные разделы с датой: `[(название, время)]` — заголовки «## … (ДД.ММ [ЧЧ:ММ])» кроме
  «Сейчас», журнала и указателей на archive/, и строки «Обновлено ДД.ММ [ЧЧ:ММ]» вне «Сейчас» (дата без времени — конец
  дня, как в boardmd);
- `stale_manual(text, mtime, t, hours)` — те из них, что старше журнала больше чем на hours часов (журнала нет — пусто).

Только стандартная библиотека; файлов не читает и не пишет (это делают watch.py и pantheon.py).
"""
import re
from datetime import datetime

STALE_HOURS = 6
JOURNAL_HEADS = ("Ход", "Начато / сделано", "Журнал")
HEAD = re.compile(r"^##[ \t]+(.*?)[ \t]*$")
LINE = re.compile(r"^[ \t]*(?:[-*][ \t]+)?\**(?:До[ \t]+)?(?:(\d{1,2})\.(\d{2})(?:\.\d{4})?[ \t,]+)?"
                  r"(\d{1,2}):([0-5])([\dxXхХ])(?!\d)")
NOW_RE = re.compile(r"^Сейчас(?:[ \t]*\([^)]*\))?$")
DATED_HEAD = re.compile(r"\((\d{1,2})\.(\d{2})(?:\.(\d{4}))?(?:[ \t]+(\d{1,2}):([0-5])([\dxXхХ]))?[^)]*\)")
UPDATED = re.compile(r"Обновлено\s+(\d{1,2})\.(\d{2})(?:\.(\d{4}))?(?:\s+(\d{1,2}):([0-5])([\dxXхХ]))?")
SKIP_HEADS = ("Ранее",)


def _stamp(day, mon, year, hh, m10, m1, t, end_of_day=False):
    now = datetime.fromtimestamp(t)
    try:
        if hh is None:
            h, m = (23, 59) if end_of_day else (0, 0)
        else:
            h, m = int(hh), int(m10) * 10 + (int(m1) if m1.isdigit() else 9)
        d = datetime(int(year) if year else now.year, int(mon), int(day), h, m)
    except ValueError:
        return None
    if not year and d.timestamp() > t + 86400:
        d = d.replace(year=d.year - 1)
    return d.timestamp()


def journal_time(text, mtime, t):
    """Время последней строки журнала (самое позднее) или None."""
    lines = text.split("\n")
    out = None
    for i, ln in enumerate(lines):
        m = HEAD.match(ln)
        if not (m and m.group(1) in JOURNAL_HEADS):
            continue
        day, mon = datetime.fromtimestamp(mtime).strftime("%d.%m").split(".")
        for row in lines[i + 1:]:
            if HEAD.match(row):
                break
            k = LINE.match(row)
            if not k:
                continue
            if k.group(1):
                day, mon = k.group(1), k.group(2)
            ts = _stamp(day, mon, None, k.group(3), k.group(4), k.group(5), t)
            if ts is not None and (out is None or ts > out):
                out = ts
    return out


def display(ts):
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")[:-1] + "x"


def retime_head(text, stamp):
    """Заголовок `## Сейчас` / `## Сейчас (дата)` → `## Сейчас (display(stamp))`. → (текст, изменён)."""
    if stamp is None:
        return text, False
    lines = text.split("\n")
    want = f"## Сейчас ({display(stamp)})"
    for i, ln in enumerate(lines):
        m = HEAD.match(ln)
        if m and NOW_RE.match(m.group(1)):
            if ln == want:
                return text, False
            lines[i] = want
            return "\n".join(lines), True
    return text, False


def dated_manual(text, t):
    """[(название, время)] ручных разделов с датой; см. шапку модуля."""
    out = []
    section = None
    for ln in text.split("\n"):
        h = HEAD.match(ln)
        if h:
            section = h.group(1)
            if NOW_RE.match(section) or section in JOURNAL_HEADS or "archive" in section \
                    or section.split(" ")[0] in SKIP_HEADS:
                section = None
                continue
            d = DATED_HEAD.search(section)
            ts = _stamp(*d.groups(), t, True) if d else None
            if ts is not None:
                out.append((section.split(" (")[0].strip(), ts))
            continue
        u = UPDATED.search(ln) if section is not None else None
        ts = _stamp(*u.groups(), t, True) if u else None
        if ts is not None:
            out.append((section.split(" (")[0].strip(), ts))
    return out


def stale_manual(text, mtime, t, hours=STALE_HOURS):
    j = journal_time(text, mtime, t)
    if j is None:
        return []
    return [(n, ts) for n, ts in dated_manual(text, t) if j - ts > hours * 3600]
