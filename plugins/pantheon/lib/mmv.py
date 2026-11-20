"""Замер минут владельца на систему (ММВ, metis-0169): только время событий, текст журналов не читается.
Там же строка сводки «минуты Actions: N из 2000» (metis-1116, actions_line).

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
import shutil
import subprocess
import sys
import tempfile
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
    """Дописать/обновить строки в STATE/mmv.jsonl по дате.

    Файл есть, но не читается или не декодируется — не переписываем (иначе потеряем все дни).
    День заменяется, только если в новой записи событий не меньше прежних: пустой или неполный день
    (например, не прочитан zeus.md) полный не затирает. Дни, которых нет в new, остаются как были.
    """
    p = os.path.join(state, "mmv.jsonl")
    cur = {}
    try:
        with open(p, encoding="utf-8") as fh:
            for ln in fh:
                with contextlib.suppress(ValueError, TypeError, KeyError):
                    r = json.loads(ln)
                    cur[r["date"]] = r
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError):
        return
    for r in new:
        old = cur.get(r["date"])
        if old is None or r["events"] >= old.get("events", 0):
            cur[r["date"]] = r
    os.makedirs(state, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=state, prefix="mmv.jsonl.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for k in sorted(cur):
                fh.write(json.dumps(cur[k], ensure_ascii=False) + "\n")
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def fmt(m):
    return f"{m:.1f}".replace(".", ",")


def _today(t):
    return date.fromtimestamp(t if t is not None else time.time())


def _entries(n):
    """«1 вход / 2 входа / 5 входов»."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} вход"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} входа"
    return f"{n} входов"


def line(state, days=7, t=None):
    """Одна строка для `pantheon night report`: вчера и среднее за days дней (без записи в файл).

    t — время сводки (секунды), от него считается «сегодня»; без него — настоящее время.
    """
    rs = rows(state, days + 1, _today(t))
    yest, rest = rs[-2], rs[:-1]
    avg = sum(r["min"] for r in rest[-days:]) / max(1, len(rest[-days:]))
    return (f"ММВ (минуты владельца): вчера {fmt(yest['min'])} мин ({_entries(yest['entries'])}), "
            f"среднее за {days} дн. {fmt(avg)} мин")


ACTIONS_QUOTA = 2000  # включённые минуты Actions в месяц (план Free)
ACTIONS_NONE = "минуты Actions: нет данных"
# кратность минут к квоте: Linux 1, Windows 2, macOS 10 (docs.github.com, About billing for GitHub Actions)
ACTIONS_MULT = (("macos", 10), ("windows", 2))


def _gh_json(args, timeout=10):
    """`gh <args>` → разобранный JSON; gh нет, сбой, таймаут, код не 0 и не-JSON — None (metis-1116)."""
    exe = os.environ.get("PANTHEON_GH") or shutil.which("gh")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _gh_usage(user, year, month, timeout=10):
    """Ответ billing usage: `gh api /users/<user>/settings/billing/usage?year=&month=`. Старый `.../billing/actions`
    GitHub отключил (410) — его не вызываем."""
    return _gh_json(["api", f"/users/{user}/settings/billing/usage?year={year}&month={month}"], timeout)


def _gh_user():
    """Логин владельца: PANTHEON_GH_USER (подмена) или `gh api user -q .login`; не получен — None."""
    env = os.environ.get("PANTHEON_GH_USER")
    if env:
        return env
    exe = os.environ.get("PANTHEON_GH") or shutil.which("gh")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "api", "user", "-q", ".login"], capture_output=True, text=True, timeout=10,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


def _gh_public(user):
    """Имена публичных репозиториев user (`gh repo list <user> --visibility public --json name`); ошибка — None."""
    got = _gh_json(["repo", "list", user, "--visibility", "public", "--limit", "1000", "--json", "name"])
    if not isinstance(got, list):
        return None
    return {r["name"] for r in got if isinstance(r, dict) and isinstance(r.get("name"), str)}


def actions_line(t=None, usage=None, public=None):
    """Строка сводки «минуты Actions: N из 2000» за месяц t: сумма quantity по записям product=actions в минутах
    с кратностью SKU (macOS ×10, Windows ×2). Публичные репозитории исключены: их минуты бесплатны и квоту не едят,
    а billing/usage их тоже перечисляет (repositoryName ∈ public; запись без repositoryName считается). Край: видимость
    берётся на сегодня — репозиторий, сменивший её посреди месяца, весь месяц считается по новой. Минуты организаций
    (организации владельца) идут по их счёту и в строку не входят (запрос только `/users/<login>`).
    usage и public (множество имён) — подмена для теста; без них запрашиваются. Любой сбой (gh, логин, список
    репозиториев, вид ответа, NaN/Infinity) — «минуты Actions: нет данных»: сводку строка не роняет."""
    d = _today(t)
    try:
        if usage is None:
            user = _gh_user()
            usage = _gh_usage(user, d.year, d.month) if user else None
            public = _gh_public(user) if usage is not None else None
        if public is None:
            return ACTIONS_NONE
        total = 0.0
        for it in usage["usageItems"]:
            if it.get("product") == "actions" and it.get("unitType") == "Minutes" \
                    and it.get("repositoryName") not in public:
                sku = str(it.get("sku") or "").lower()
                total += float(it["quantity"]) * next((k for w, k in ACTIONS_MULT if w in sku), 1)
        shown = round(total)
    except (TypeError, KeyError, ValueError, AttributeError, OverflowError):
        return ACTIONS_NONE
    return f"минуты Actions: {shown} из {ACTIONS_QUOTA}"


def main(rest, state, t=None):
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
    rs = rows(state, days, _today(t))
    save(state, rs)
    print("День         Минут  Входов  Событий")
    for r in rs:
        print(f"{r['date']}  {fmt(r['min']):>6}  {r['entries']:>6}  {r['events']:>7}")
    return 0
