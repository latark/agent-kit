"""Правило «живой субагент» (metis-0904): одно для хука ctx (подсказка /clear, список после /clear и resume) и
дежурного watch (окно не перезапускать, копию worktree не убирать). Только stdlib: хук грузит модуль по пути
<плагин>/lib/live_subagent.py (ctx.rule), watch — так же, рядом с собой.

Субагент — пара файлов Claude Code: <папка>/agent-<id>.jsonl (журнал) и agent-<id>.meta.json. Он живой, если:
  - не закончил (done): нет stoppedByUser; нет finished — или finished есть, но своя фоновая команда субагента ещё без
    итога (background_pending: Bash ушёл в фон сам через 180 с или с run_in_background, субагент закончил ход и
    получил finished, а итог команды будит его снова); последний ответ субагента — не сдача SubagentHandback
    (handed_back: сданный и снова поднятый SendMessage субагент пишет ответы после сдачи — он снова живой);
  - писал недавно: позднее из времён записи журнала и meta.json (stamp) не старше LIVE_MAX;
  - он нынешнего процесса (after_start): старт неизвестен (0), запись позднее старта + LIVE_GRACE или первая запись
    журнала позднее старта (born_after — запущен в первые LIVE_GRACE секунд процесса).
До metis-0904 ctx и watch решали это по-разному: watch не знал фоновой команды, born_after и stoppedByUser, ctx — времени
meta.json. Правило взяло признаки жизни обоих (время — по любому из двух файлов, born_after) и признаки конца ctx.

Фоновая команда: запущенная — по ответу Bash с ID только в tool_result записей user (не в тексте ассистента и не в
поручении: цитата «running in background with ID: …» команды не запускает); законченная — по task-notification с этим ID
или вызову TaskStop/KillShell/KillBash.
"""
import json
import os
import re
from datetime import datetime

LIVE_MAX = 3 * 3600   # живой субагент писал не раньше этого, с: ожидание outside test — до 2 ч (metis-0864)
LIVE_GRACE = 120      # с после старта процесса: журналы, закрытые прежним процессом при его снятии, — до этого
TAIL = 400000         # хвост журнала субагента, где ищутся фоновые команды и сдача, байт

BG_STARTED = re.compile(r"running in background with ID: ([\w-]+)|moved to the background \(ID: ([\w-]+)\)")
BG_ENDED = re.compile(rb"<task-id>([\w-]+)</task-id>|\"name\":\s*\"(?:TaskStop|KillShell|KillBash)\",\s*\"input\":\s*\{"
                      rb"[^}]*\"(?:task_id|shell_id)\":\s*\"([\w-]+)\"")
_BG_HINT = (b"running in background with ID: ", b"moved to the background (ID: ")


def mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return -1


def meta_path(jl):
    """agent-<id>.jsonl → agent-<id>.meta.json рядом."""
    return jl[:-len(".jsonl")] + ".meta.json" if jl.endswith(".jsonl") else jl + ".meta.json"


def stamp(jl):
    """Последняя запись субагента: позднее из времён журнала и meta.json; -1 — нет обоих."""
    return max(mtime(jl), mtime(meta_path(jl)))


def iso_ts(s):
    """Время записи журнала (ISO, UTC с Z) → секунды; None — не время."""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def tail_lines(path, nbytes=TAIL):
    """Строки хвоста файла (≤ nbytes с конца); сбой чтения — []."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            data = f.read()
    except OSError:
        return []
    lines = data.split(b"\n")
    return lines[1:] if size > nbytes else lines  # первая строка хвоста обрезана


def _record(raw):
    try:
        d = json.loads(raw)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _content(d):
    m = d.get("message")
    c = m.get("content") if isinstance(m, dict) else None
    return c if isinstance(c, list) else []


def _result_texts(d):
    """Тексты tool_result записи user (содержимое — строка или список блоков text)."""
    if d.get("type") != "user":
        return
    for c in _content(d):
        if not isinstance(c, dict) or c.get("type") != "tool_result":
            continue
        body = c.get("content")
        if isinstance(body, str):
            yield body
        elif isinstance(body, list):
            for b in body:
                if isinstance(b, dict) and isinstance(b.get("text"), str):
                    yield b["text"]


def background_pending(jl):
    """У субагента есть своя фоновая команда без итога (metis-0839, Д1 metis-0904): запущенные — по ответу Bash с ID в
    tool_result записей user, законченные — по task-notification с этим ID или вызову TaskStop."""
    started, ended = set(), set()
    for raw in tail_lines(jl):
        if any(h in raw for h in _BG_HINT):
            d = _record(raw)
            for text in _result_texts(d) if d else ():
                for m in BG_STARTED.finditer(text):
                    started.add(m.group(1) or m.group(2))
        for m in BG_ENDED.finditer(raw):
            ended.add((m.group(1) or m.group(2)).decode())
    return bool(started - ended)


def agent_done(meta, jl):
    """Закончил по meta.json: finished без своей фоновой команды в работе."""
    return bool(meta.get("finished")) and not background_pending(jl)


def _handback(d):
    """Сообщение вызова SubagentHandback в записи ассистента; None — вызова нет."""
    if d.get("type") != "assistant":
        return None
    for c in reversed(_content(d)):
        if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "SubagentHandback":
            msg = c.get("input").get("message") if isinstance(c.get("input"), dict) else None
            return msg.strip() if isinstance(msg, str) else ""
    return None


def agent_report(jl):
    """Отчёт субагента (metis-0839): поле message последнего вызова SubagentHandback в хвосте его журнала; '' — нет.
    Субагент Пантеона сдаёт работу этим вызовом, его текст и есть отчёт, который получило окно."""
    for raw in reversed(tail_lines(jl)):
        if b"SubagentHandback" not in raw:
            continue
        d = _record(raw)
        msg = _handback(d) if d else None
        if msg:
            return msg
    return ""


def handed_back(jl):
    """Последняя запись ассистента в хвосте журнала — вызов SubagentHandback: субагент сдал работу и после сдачи не
    отвечал. Сданный, но снова поднятый (SendMessage, итог фоновой команды) пишет ответы после сдачи — не сдан."""
    for raw in reversed(tail_lines(jl)):
        if b'"assistant"' not in raw:
            continue
        d = _record(raw)
        if d and d.get("type") == "assistant":
            return _handback(d) is not None
    return False


def done(meta, jl):
    """Субагент закончил: остановлен вами, finished без своей фоновой команды или сдал работу последним ответом."""
    return bool(meta.get("stoppedByUser")) or agent_done(meta, jl) or handed_back(jl)


def born_after(jl, started):
    """Первая запись журнала субагента позже старта процесса: его запустил нынешний процесс."""
    try:
        with open(jl, encoding="utf-8", errors="replace") as f:
            first = f.readline(65536)
        t = iso_ts(json.loads(first).get("timestamp"))
    except (OSError, ValueError, AttributeError):
        return False
    return t is not None and t > started


def after_start(jl, t, started):
    """Субагент — нынешнего процесса: старт неизвестен, запись позже старта + LIVE_GRACE или запущен после старта.
    Без последнего условия субагент, запущенный в первые LIVE_GRACE секунд процесса, не считался живым (проба
    metis-0839: подсказка /clear при живом)."""
    return not started or t > started + LIVE_GRACE or born_after(jl, started)


def live(meta, jl, started, now):
    """Живой ли субагент с meta.json meta и журналом jl (правило — шапка модуля). started — старт нынешнего процесса
    окна, 0 — неизвестен (тогда только по сроку); now — нынешнее время. Дешёвые проверки — первыми: хвост журнала
    читается только у недавнего субагента нынешнего процесса."""
    if not isinstance(meta, dict):
        return False
    t = stamp(jl)
    if t < 0 or now - t > LIVE_MAX or not after_start(jl, t, started):
        return False
    return not done(meta, jl)
