#!/usr/bin/env python3
"""Stop исполнителя без кода palamedes (metis-0224, аудит v2 §12.6): без итога-файла с источниками работу не сдать.

Подключён в шапке роли palamedes (поле hooks: Stop — у субагента Claude Code превращает его в SubagentStop). Образец —
dev-stop-verify.py разработчиков, но проверка другая: у текста, юридического разбора и синтеза нет тестов и worktree.

Что проверяет — по отчёту исполнителя (поле last_assistant_message события, иначе последний текст ассистента в
agent_transcript_path) и файлу, который отчёт называет:
  1. в отчёте есть строка «Итог: <путь к файлу .md или .txt>» (путь абсолютный или от ~), файл есть и не пустой;
  2. в файле есть таблица Markdown «утверждение → источник»: в шапке столбцы со словами «утверждение» и «источник»,
     хотя бы одна строка, и у каждой строки обе ячейки заполнены — не пусто, не «—», не «?», не «нет»;
  3. в файле нет запрещённых слов: заглушек и следов черновика (TODO, TBD, FIXME, XXX, lorem ipsum, «[источник]»,
     «[вставить …]», «как языковая модель»).
Не так — выход 2 и что поправить; не больше трёх возвратов подряд на одного исполнителя: дальше хук отпускает, а
исполнитель пишет в отчёте «заблокировано».

Хук только читает: файл итога не запускает и не печатает его текст — только номера строк и найденное слово.
Python 3.9+ (хуки запускает python3 из PATH). Состояние — ~/.local/state/pantheon/ctx/text-stop/<agent_id>.
PANTHEON_TEXT_STOP_OFF=1 — выключить (как PANTHEON_DEV_STOP_OFF у разработчиков).
"""
import json
import os
import re
import sys

HOME = os.path.expanduser("~")
STATE = os.path.realpath(os.environ.get("PANTHEON_STATE") or os.path.join(HOME, ".local", "state", "pantheon"))
MAX_RETURNS = 3
MAX_BYTES = 2 * 1024 * 1024
SUFFIXES = (".md", ".txt")
# «Итог: ~/путь.md», «- **Итог:** `путь с пробелами.md`»; путь с пробелами — только в обратных кавычках
RESULT_LINE = re.compile(r"^[ \t>*_-]*\**[ \t]*Итог[ \t]*\**[ \t]*:[ \t]*\**[ \t]*(?:`([^`\n]+)`|([^`\s]+))[ \t]*\**[ \t]*$",
                         re.I | re.M)
EMPTY_CELL = {"", "-", "—", "–", "?", "…", "...", "нет", "n/a", "na", "tbd", "todo"}
FORBIDDEN = [
    (re.compile(r"\bTODO\b", re.I), "TODO"),
    (re.compile(r"\bTBD\b", re.I), "TBD"),
    (re.compile(r"\bFIXME\b", re.I), "FIXME"),
    (re.compile(r"\bXXX\b"), "XXX"),
    (re.compile(r"lorem\s+ipsum", re.I), "lorem ipsum"),
    (re.compile(r"\[\s*источник\s*\]", re.I), "[источник]"),
    (re.compile(r"[\[<{]\s*вставить", re.I), "[вставить …]"),
    (re.compile(r"как\s+(?:языковая\s+модель|ии\b|искусственный\s+интеллект)", re.I), "как языковая модель"),
    (re.compile(r"\bas\s+an\s+ai\b", re.I), "as an AI"),
]


def report_text(ev):
    """Последний текст исполнителя: поле события или транскрипт. None — взять неоткуда."""
    msg = ev.get("last_assistant_message")
    if isinstance(msg, str) and msg.strip():
        return msg
    path = ev.get("agent_transcript_path") or ev.get("transcript_path") or ""
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return None
    last = None
    with fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "assistant":
                continue
            content = (d.get("message") or {}).get("content")
            if isinstance(content, str):
                texts = [content]
            elif isinstance(content, list):
                texts = [x.get("text") or "" for x in content if isinstance(x, dict) and x.get("type") == "text"]
            else:
                texts = []
            if any(t.strip() for t in texts):
                last = "\n".join(texts)
    return last


def cells(line):
    s = line.strip()
    if "|" not in s:
        return None
    s = s.strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def is_separator(row):
    return bool(row) and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in row)


def blank(cell):
    c = re.sub(r"[*_`]", "", cell).strip().lower()
    return c in EMPTY_CELL


def source_table(lines):
    """→ (номер строки шапки, [(номер строки, утверждение, источник)]) первой таблицы «утверждение → источник»
    или None."""
    for i, line in enumerate(lines[:-1]):
        head = cells(line) if "|" in line else None
        if not head:
            continue
        low = [h.lower() for h in head]
        ci = next((k for k, h in enumerate(low) if "утвержден" in h), None)
        si = next((k for k, h in enumerate(low) if "источник" in h), None)
        if ci is None or si is None or ci == si or not is_separator(cells(lines[i + 1]) or []):
            continue
        rows = []
        for j in range(i + 2, len(lines)):
            if "|" not in lines[j]:
                break
            row = cells(lines[j]) or []
            rows.append((j + 1, row[ci] if ci < len(row) else "", row[si] if si < len(row) else ""))
        return i + 1, rows
    return None


def problems(report):
    """→ (путь итога или None, [что не так])."""
    m = list(RESULT_LINE.finditer(report or ""))
    if not m:
        return None, ["в отчёте нет строки «Итог: <путь к файлу итога>» — допиши её в «Подробности»"]
    raw = (m[-1].group(1) or m[-1].group(2)).strip()
    path = os.path.expanduser(raw.replace("$HOME", HOME))
    if not os.path.isabs(path):
        return None, [f"путь итога «{raw}» не абсолютный — пиши его от / или ~"]
    real = os.path.realpath(path)
    if not real.lower().endswith(SUFFIXES):
        return real, [f"итог «{raw}» — не .md и не .txt"]
    if not os.path.isfile(real):
        return real, [f"файла итога «{raw}» нет — сначала запиши черновик"]
    if os.path.getsize(real) > MAX_BYTES:
        return real, [f"итог «{raw}» больше {MAX_BYTES // (1024 * 1024)} МБ — это не черновик"]
    text = open(real, encoding="utf-8", errors="replace").read()
    if not text.strip():
        return real, [f"файл итога «{raw}» пуст"]
    out = []
    lines = text.splitlines()
    table = source_table(lines)
    if table is None:
        out.append("в итоге нет таблицы «утверждение → источник» (шапка | Утверждение | Источник |, под ней |---|---|)")
    else:
        at, rows = table
        if not rows:
            out.append(f"таблица «утверждение → источник» (строка {at}) пустая — добавь строки")
        bad = [n for n, claim, src in rows if blank(claim) or blank(src)]
        if bad:
            out.append("в таблице «утверждение → источник» не заполнены строки " + ", ".join(map(str, bad[:10]))
                       + (" и ещё" if len(bad) > 10 else "")
                       + " — у каждого утверждения источник: файл:строка, статья, ссылка; без источника — убери "
                       "утверждение из текста")
    found = []
    for n, line in enumerate(lines, 1):
        for rx, word in FORBIDDEN:
            if rx.search(line):
                found.append(f"«{word}» (строка {n})")
    if found:
        out.append("запрещённые слова: " + ", ".join(found[:10]) + (" и ещё" if len(found) > 10 else ""))
    return real, out


def counter(agent_id, value=None):
    d = os.path.join(STATE, "ctx", "text-stop")
    p = os.path.join(d, re.sub(r"[^\w-]", "_", agent_id or "none"))
    if value is None:
        try:
            return int(open(p).read().strip() or 0)
        except (OSError, ValueError):
            return 0
    os.makedirs(d, exist_ok=True)
    with open(p, "w") as fh:
        fh.write(str(value))
    return value


def main():
    try:
        ev = json.load(sys.stdin)
    except ValueError:
        return 0
    if os.environ.get("PANTHEON_TEXT_STOP_OFF") == "1" or not isinstance(ev, dict):
        return 0
    report = report_text(ev)
    if report is None:
        return 0  # ни поля, ни транскрипта — проверить нечем, не держим
    agent = ev.get("agent_id") or ev.get("session_id") or ""
    _, why = problems(report)
    if not why:
        counter(agent, 0)
        return 0
    n = counter(agent) + 1
    if n > MAX_RETURNS:
        counter(agent, 0)
        print(f"Итог не прошёл проверку после {MAX_RETURNS} возвратов — отпускаю. В отчёте статус «заблокировано»: "
              + "; ".join(why), file=sys.stderr)
        return 0
    counter(agent, n)
    print(f"СТОП ({n} из {MAX_RETURNS}): итог не сдан — " + "; ".join(why) + ". Поправь файл итога и отчёт. Если "
          "причина вне твоей задачи — опиши её в отчёте и закончи со статусом «заблокировано».", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # сбой хука не держит исполнителя, но остаётся в журнале
        try:
            os.makedirs(os.path.join(STATE, "logs"), exist_ok=True)
            with open(os.path.join(STATE, "logs", "ctx-hooks.log"), "a") as fh:
                fh.write(f"text-stop-verify\t{type(e).__name__}: {e}\n")
        except OSError:
            pass
        sys.exit(0)
