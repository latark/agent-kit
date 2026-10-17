"""Замер минут владельца на систему (ММВ, metis-0169): только время событий, текст журналов не читается.

События — поле time в owner-log/board.jsonl и заголовки «## ГГГГ-ММ-ДД ЧЧ:ММ:СС …» в owner-log/*.md (местное время).
ММВ за день = сумма промежутков между соседними событиями, не длиннее 5 мин (длиннее — перерыв, в минуты не идёт),
плюс 45 с на каждый вход (первое событие после перерыва). Промежуток через полночь делится по дням, вход
записывается на день своего события. Модуль самостоятельный (без pantheon.py): путь к STATE передаёт вызывающий.
"""
import contextlib
import glob
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

BREAK = 300
ENTRY = 45
HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", re.M)


def _ts(s, fmt):
    try:
        return time.mktime(time.strptime(s, fmt))
    except (ValueError, TypeError, OverflowError):
        return None


def events(state):
    """Отсортированные метки времени (секунды) из журналов владельца; битые строки пропускаются."""
    out = []
    log = os.path.join(state, "owner-log")
    with contextlib.suppress(OSError):
        with open(os.path.join(log, "board.jsonl"), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    s = json.loads(line).get("time", "")[:19]
                except (ValueError, AttributeError, TypeError):
                    continue
                t = _ts(s, "%Y-%m-%dT%H:%M:%S") if isinstance(s, str) else None
                if t is not None:
                    out.append(t)
    for p in sorted(glob.glob(os.path.join(log, "*.md"))):
        with contextlib.suppress(OSError):
            with open(p, encoding="utf-8", errors="replace") as fh:
                for m in HEAD.finditer(fh.read()):
                    t = _ts(m.group(1), "%Y-%m-%d %H:%M:%S")
                    if t is not None:
                        out.append(t)
    return sorted(out)


def _midnight(d):
    return time.mktime((d + timedelta(days=1)).timetuple())


def by_day(ts):
    """{date: {"sec": секунд, "entries": входов, "events": событий}}."""
    days = {}

    def row(d):
        return days.setdefault(d, {"sec": 0.0, "entries": 0, "events": 0})

    prev = None
    for t in ts:
        d = datetime.fromtimestamp(t).date()
        row(d)["events"] += 1
        if prev is None or t - prev > BREAK:
            r = row(d)
            r["entries"] += 1
            r["sec"] += ENTRY
        else:
            a = prev
            while True:
                da = datetime.fromtimestamp(a).date()
                cut = min(t, _midnight(da))
                row(da)["sec"] += cut - a
                if cut >= t:
                    break
                a = cut
        prev = t
    return days


def rows(state, days=None, today=None):
    """Строки по дням, по возрастанию даты; days — последние N календарных дней по сегодня (с нулевыми)."""
    d = by_day(events(state))
    today = today or date.today()
    if days is None:
        keys = sorted(d)
    else:
        keys = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    out = []
    for k in keys:
        r = d.get(k) or {"sec": 0.0, "entries": 0, "events": 0}
        out.append({"date": k.isoformat(), "min": round(r["sec"] / 60, 2), "entries": r["entries"],
                    "events": r["events"]})
    return out


def save(state, new):
    """Дописать/обновить строки в STATE/mmv.jsonl по дате (дни без событий не затирают прежнее)."""
    p = os.path.join(state, "mmv.jsonl")
    cur = {}
    with contextlib.suppress(OSError):
        for line in open(p, encoding="utf-8"):
            with contextlib.suppress(ValueError, TypeError, KeyError):
                r = json.loads(line)
                cur[r["date"]] = r
    for r in new:
        if r["events"] or r["date"] not in cur:
            cur[r["date"]] = r
    os.makedirs(state, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for k in sorted(cur):
            fh.write(json.dumps(cur[k], ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def fmt(m):
    return f"{m:.1f}".replace(".", ",")


def line(state, days=7, today=None):
    """Одна строка для `pantheon night report`: вчера и среднее за days дней (без записи в файл)."""
    rs = rows(state, days + 1, today)
    yest, rest = rs[-2], rs[:-1]
    avg = sum(r["min"] for r in rest[-days:]) / max(1, len(rest[-days:]))
    return (f"ММВ (минуты владельца): вчера {fmt(yest['min'])} мин ({yest['entries']} входов), "
            f"среднее за {days} дн. {fmt(avg)} мин")


def main(rest, state):
    days = 7
    if rest[:1] == ["--days"]:
        try:
            days = int(rest[1])
            assert days > 0
        except (IndexError, ValueError, AssertionError):
            print("pantheon mmv [--days N]", file=sys.stderr)
            return 2
    elif rest:
        print("pantheon mmv [--days N]", file=sys.stderr)
        return 2
    rs = rows(state, days)
    save(state, rs)
    print("День         Минут  Входов  Событий")
    for r in rs:
        print(f"{r['date']}  {fmt(r['min']):>6}  {r['entries']:>6}  {r['events']:>7}")
    return 0
