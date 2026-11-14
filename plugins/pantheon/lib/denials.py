#!/usr/bin/env python3
"""pantheon denials — журнал и отчёт отказов окон ролей (metis-1135, часть Д).

Цель: видеть, где окна упираются в классификатор auto mode и в песочницу, и править правила классами, а не по одному
случаю. Модуль самостоятельный (без P): его зовут и хук, и команда, и плановый проход.

  denials.py hook                       хук PermissionDenied (hooks.json): событие со stdin → строка отказа классификатора;
                                        отказ песочницы приходит из refusal.py fail (PostToolUseFailure) через record().
                                        Любой сбой — код 0 без вывода: журнал не должен мешать работе.
  pantheon denials report [--since ДАТА] [--days N] [--until ДАТА]
                                        сводка по классам, окнам и источникам, по убыванию (по умолчанию 7 дней).
  pantheon denials backfill --since ДАТА --until ДАТА
                                        строит журнал из транскриптов окон (~/.claude/projects/**.jsonl): берёт только
                                        tool_result-ошибки с отказом классификатора или песочницы. В вывод идут только
                                        счётчики; текст переписки не читается дальше проверки на отказ и в журнал не
                                        идёт. Повтор безопасен: строка с тем же id (tool_use_id) не дублируется.

Журнал: STATE/denials/<ГГГГ-ММ-ДД>.jsonl, строка = {t, window, role, tool, cls, reason, source[, id]}.
  cls — имя инструмента, а для Bash первое слово команды (без env-присваиваний и пути); текста команды в журнале нет.
  reason — причина до 200 знаков, из неё вырезаны ключи, токены, длинные случайные строки и домашний путь.
  source — classifier | sandbox. Отказы песочницы guard не видит (они случаются при выполнении команды): их пишет
  refusal.py fail, увидевший ошибку после выполнения.
Плановый проход (tick) по понедельникам кладёт отчёт за 7 дней в STATE/denials/report-<ГГГГ-ММ-ДД>.md.
"""
import contextlib
import importlib.util
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

LIB = os.path.dirname(os.path.realpath(__file__))
REASON_MAX = 200
SOURCES = ("classifier", "sandbox")
CLS_RE = re.compile(r"[\w.+:-]{1,60}")
WINDOW_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
ENV_ASSIGN = re.compile(r"[A-Za-z_]\w*=")
SECRET_RX = (
    re.compile(r"(?i)\b(?:basic|bearer)\s+\S+"),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]*@"),                       # https://user:pass@host
    re.compile(r"(?<!\S)(?:-u|--user)(?:\s+|=)\S+"),                    # curl -u user:pass
    re.compile(r"(?i)[\w-]*(?:key|secret|passw(?:or)?d|token|authorization)\s*[=:]\s*\S+"),   # PGPASSWORD=, *_KEY=
    re.compile(r"\b(?:sk|pk|ghp|gho|ghs|github_pat|xox[abpr]|AKIA|AIza)[-_A-Za-z0-9]{8,}"),
    re.compile(r"[A-Za-z0-9+/_=-]{24,}"),
    re.compile(r"/Users/[^/\s]+"),
)
# отказ классификатора в тексте tool_result (транскрипты); отказ песочницы — handoff.refusal_source
CLASSIFIER_RX = re.compile(r"auto mode classifier|classifier (?:has )?(?:blocked|denied)|"
                           r"permission for this action (?:has been |was )?denied|denied by (?:the )?auto mode", re.I)
# причина — только из шаблона отказа классификатора, а не после любого «reason:» в выводе
REASON_RX = re.compile(r"permission for this action (?:has been |was )?denied[^\n]*?\breason:\s*(.+)", re.I | re.S)


def home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def state_dir(state=None):
    base = state or os.environ.get("PANTHEON_STATE") or os.path.join(home(), ".local", "state", "pantheon")
    return os.path.join(os.path.realpath(base), "denials")


def scrub(text, limit=REASON_MAX):
    t = " ".join(str(text or "").split())
    for rx in SECRET_RX:
        t = rx.sub(lambda m: "~" if m.group(0).startswith("/Users/") else "‹скрыто›", t)
    return t[:limit]


def cls_of(tool, command=None):
    """Класс отказа: имя инструмента; для Bash — первое слово команды (имя без пути, без env-присваиваний)."""
    tool = str(tool or "")
    if tool == "Bash" and isinstance(command, str):
        for w in command.split():
            if ENV_ASSIGN.match(w):
                continue
            w = os.path.basename(w.strip("\"'("))
            return w if CLS_RE.fullmatch(w) else "bash"
        return "bash"
    return tool if CLS_RE.fullmatch(tool) else "tool"


def row(t, source, tool, cls, reason, window=None, role=None, rid=None):
    e = {"t": round(float(t), 3), "window": window if isinstance(window, str) and WINDOW_RE.fullmatch(window) else "",
         "role": role if isinstance(role, str) and WINDOW_RE.fullmatch(role) else "",
         "tool": tool if isinstance(tool, str) and CLS_RE.fullmatch(tool) else "tool",
         "cls": cls, "reason": scrub(reason), "source": source if source in SOURCES else "classifier"}
    if rid:
        e["id"] = str(rid)[:80]
    return e


def day_of(t):
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d")


def append(e, state=None):
    d = state_dir(state)
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(d, day_of(e["t"]) + ".jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
                 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def window_role():
    role = os.environ.get("PANTHEON_ROLE") or None
    tmp = os.environ.get("PANTHEON_TMP")
    win = os.path.basename(os.path.dirname(os.path.realpath(tmp))) if tmp else None
    return win, role


def record(source, ev, reason="", now=None):
    """Строка отказа из события хука (tool_name, tool_input). Сбой записи → False, не исключение."""
    try:
        ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
        tool = str(ev.get("tool_name") or "")
        win, role = window_role()
        append(row(now if now is not None else time.time(), source, tool, cls_of(tool, ti.get("command")),
                   reason, win, role))
        return True
    except Exception:
        return False


def read(since_day, until_day, state=None):
    """Строки журнала за дни [since_day, until_day] (строки ГГГГ-ММ-ДД)."""
    out = []
    d = state_dir(state)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        day = n[:-6]
        if not n.endswith(".jsonl") or not DAY_RE.fullmatch(day) or not since_day <= day <= until_day:
            continue
        with contextlib.suppress(OSError), open(os.path.join(d, n), encoding="utf-8") as fh:
            for ln in fh:
                with contextlib.suppress(ValueError):
                    e = json.loads(ln)
                    if isinstance(e, dict) and isinstance(e.get("cls"), str):
                        out.append(e)
    return out


def _table(title, counts, head):
    lines = [f"### {title}", "", f"| {head} | отказов |", "|---|---|"]
    lines += [f"| {k} | {n} |" for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return lines + [""]


def report(since_day, until_day, state=None):
    rows = read(since_day, until_day, state)
    out = [f"# Отказы окон за {since_day} — {until_day}", "", f"Всего: {len(rows)}", ""]
    if not rows:
        return "\n".join(out + ["Отказов в журнале нет."]) + "\n"
    by_cls, by_win, by_src, by_pair = {}, {}, {}, {}
    for e in rows:
        w = e.get("window") or "—"
        c = str(e.get("cls"))
        by_cls[c] = by_cls.get(c, 0) + 1
        by_win[w] = by_win.get(w, 0) + 1
        s = str(e.get("source") or "?")
        by_src[s] = by_src.get(s, 0) + 1
        k = f"{c} @ {w}"
        by_pair[k] = by_pair.get(k, 0) + 1
    out += _table("По классам", by_cls, "класс") + _table("По окнам", by_win, "окно")
    out += _table("По источникам", by_src, "источник")
    top = dict(sorted(by_pair.items(), key=lambda kv: (-kv[1], kv[0]))[:10])
    return "\n".join(out + _table("Топ-10: класс @ окно", top, "класс @ окно")) + "\n"


def _day_arg(v):
    if not DAY_RE.fullmatch(v or ""):
        raise ValueError(f"дата «{v}» не по образцу ГГГГ-ММ-ДД")
    return date.fromisoformat(v).isoformat()


def _opts(rest, names):
    o, i = {}, 0
    while i < len(rest):
        if rest[i] in names and i + 1 < len(rest):
            o[rest[i]] = rest[i + 1]
            i += 2
        else:
            raise ValueError(f"не понял «{rest[i]}»")
    return o


def cmd_report(rest, state, now):
    o = _opts(rest, ("--since", "--days", "--until"))
    today = date.fromtimestamp(now)
    until = _day_arg(o["--until"]) if "--until" in o else today.isoformat()
    if "--since" in o:
        since = _day_arg(o["--since"])
    else:
        days = int(o.get("--days", "7"))
        if days < 1:
            raise ValueError("--days меньше 1")
        since = (date.fromisoformat(until) - timedelta(days=days - 1)).isoformat()
    print(report(since, until, state), end="")
    return 0


# --- backfill из транскриптов ------------------------------------------------------------------------------------

def _handoff():
    spec = importlib.util.spec_from_file_location("pantheon_handoff_denials", os.path.join(LIB, "handoff.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return ""


def denial_of(text, H):
    """(источник, причина) по тексту ошибки tool_result; None — не отказ."""
    if CLASSIFIER_RX.search(text):
        m = REASON_RX.search(text)
        return "classifier", m.group(1) if m else ""
    if H.refusal_source(text) == "sandbox":
        feat = H.refusal_line(text)   # без признака (одно слово «sandbox») — обычный вывод, не отказ для журнала
        return ("sandbox", feat) if feat else None
    return None


def _ts(rec):
    v = rec.get("timestamp")
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def window_of(path):
    """Окно транскрипта: папка проекта (у субагента — через два уровня выше), без домашнего пути и имени пользователя."""
    d = os.path.dirname(path)
    if os.path.basename(d) == "subagents":   # <проект>/<сессия>/subagents/agent-*.jsonl
        d = os.path.dirname(os.path.dirname(d))
    slug = lambda x: re.sub(r"[^a-z0-9-]", "-", x.lower()).strip("-")  # noqa: E731
    name, hs = slug(os.path.basename(d)), slug(home())
    if hs and name.startswith(hs + "-"):
        name = name[len(hs) + 1:]
    else:
        name = re.sub(r"^(?:users|home)-[^-]+-", "", name)
    name = re.sub(r"^projects-", "", name)
    return name[-41:].lstrip("-")


def scan_file(path, t0, t1, H, seen):
    """Отказы одного транскрипта в [t0, t1). Строки без tool_use/tool_result даже не разбираются."""
    uses, found = {}, []
    win = window_of(path)
    with open(path, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            has_use, has_res = '"tool_use"' in ln, '"tool_result"' in ln
            if not (has_use or has_res):
                continue
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            msg = rec.get("message") if isinstance(rec, dict) else None
            blocks = msg.get("content") if isinstance(msg, dict) else None
            if not isinstance(blocks, list):
                continue
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and isinstance(b.get("id"), str):
                    ti = b.get("input") if isinstance(b.get("input"), dict) else {}
                    uses[b["id"]] = (str(b.get("name") or ""), cls_of(b.get("name"), ti.get("command")))
                elif b.get("type") == "tool_result" and b.get("is_error") is True:
                    t = _ts(rec)
                    rid = b.get("tool_use_id")
                    if t is None or not t0 <= t < t1 or not isinstance(rid, str) or rid in seen:
                        continue
                    d = denial_of(_result_text(b.get("content")), H)
                    if d:
                        tool, cls = uses.get(rid, ("", "tool"))
                        found.append(row(t, d[0], tool, cls, d[1], win, None, rid))
    return found


def cmd_backfill(rest, state):
    o = _opts(rest, ("--since", "--until"))
    if "--since" not in o or "--until" not in o:
        raise ValueError("нужны --since и --until (ГГГГ-ММ-ДД)")
    since, until = _day_arg(o["--since"]), _day_arg(o["--until"])
    if since > until:
        raise ValueError("--since позже --until")
    t0 = datetime.fromisoformat(since).timestamp()
    t1 = (datetime.fromisoformat(until) + timedelta(days=1)).timestamp()
    H = _handoff()
    seen = {e["id"] for e in read(since, until, state) if e.get("id")}
    root = os.path.join(home(), ".claude", "projects")
    files = new = 0
    for dp, _dn, fns in os.walk(root):
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            try:
                if not fn.endswith(".jsonl") or os.path.getmtime(p) < t0:
                    continue
                files += 1
                for e in scan_file(p, t0, t1, H, seen):
                    append(e, state)
                    seen.add(e["id"])
                    new += 1
            except OSError:
                continue
    print(f"denials backfill: файлов {files}, новых строк отказов {new} ({since} — {until})")
    return 0


# --- хук и плановый проход ---------------------------------------------------------------------------------------

def hook():
    with contextlib.suppress(Exception):
        ev = json.loads(sys.stdin.read() or "{}")
        if isinstance(ev, dict):
            record("classifier", ev, str(ev.get("reason") or ""))
    return 0


def tick(t, state=None):
    """Плановый проход: по понедельникам отчёт за 7 дней → STATE/denials/report-<дата>.md, раз за день."""
    if os.environ.get("PANTHEON_DRYRUN") == "1" or datetime.fromtimestamp(t).weekday() != 0:
        return None
    today = day_of(t)
    path = os.path.join(state_dir(state), f"report-{today}.md")
    if os.path.exists(path):
        return None
    since = (date.fromisoformat(today) - timedelta(days=6)).isoformat()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(report(since, today, state))
    os.replace(tmp, path)
    return f"denials: отчёт {path}"


def main(argv, state=None, now=None):
    cmd = argv[0] if argv else ""
    if cmd == "hook":
        return hook()
    now = time.time() if now is None else now
    try:
        if cmd == "report":
            return cmd_report(argv[1:], state, now)
        if cmd == "backfill":
            return cmd_backfill(argv[1:], state)
        print("pantheon denials: report [--since ДАТА] [--days N] [--until ДАТА] | backfill --since ДАТА --until ДАТА",
              file=sys.stderr)
        return 2
    except (ValueError, OSError) as e:
        print(f"pantheon denials: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
