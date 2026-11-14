#!/usr/bin/env python3
"""Хук: отказ роли → подсказка, кто это умеет (metis-0832; маршруты и журнал — lib/handoff.py).

  refusal.py fail     PostToolUseFailure (Bash): ошибка похожа на отказ песочницы («Operation not permitted», EPERM,
                      sandbox) или «команда не найдена» — additionalContext с подсказкой и строка в журнал отказов
                      STATE/logs/handoff.jsonl. Обычный сбой (красный тест, синтаксис) — без вывода.
  refusal.py denied   PermissionDenied (классификатор auto mode отклонил действие): у события нет канала к модели,
                      поэтому — отметка STATE/handoff/hint/<CLAUDE_PID>.<session_id>.json с подсказкой и строка в
                      журнал. Выдаёт её следующий PostToolBatch той же сессии и того же агента.
  refusal.py batch    PostToolBatch: отметка своей сессии и агента → additionalContext, отметка снята. Python
                      запускается, только когда отметка процесса есть (проверка — в hooks.json, без Python).
Подсказка — handoff.hint(): кому передать (Харон, Гестия, outside, read, Touch ID, «да» через Зевса) и запрет давать
владельцу команды для терминала. Любой сбой хука — код 0 без вывода: подсказка не должна мешать работе.
"""
import contextlib
import importlib.util
import json
import os
import re
import sys
import time

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "lib")
CMD_MAX = 2000


def load():
    spec = importlib.util.spec_from_file_location("pantheon_handoff_hook", os.path.join(LIB, "handoff.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_denials():
    spec = importlib.util.spec_from_file_location("pantheon_denials_hook", os.path.join(LIB, "denials.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def emit(event, text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}, ensure_ascii=False))


def pid():
    p = os.environ.get("CLAUDE_PID", "")
    return p if p.isdigit() else "nopid"


def sid_of(ev):
    return re.sub(r"[^\w-]", "", str(ev.get("session_id") or ""))[:80]


def who():
    role = os.environ.get("PANTHEON_ROLE") or None
    tmp = os.environ.get("PANTHEON_TMP")
    win = os.path.basename(os.path.dirname(os.path.realpath(tmp))) if tmp else None
    return win, role


def command(ev):
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    parts = [str(ev.get("tool_name") or "")] + [str(ti.get(k)) for k in ("command", "url", "file_path", "path")
                                                  if ti.get(k)]
    return " ".join(parts)[:CMD_MAX]


def mark_path(H, ev):
    return H.state("handoff", "hint", f"{pid()}.{sid_of(ev)}.json")


def cmd_fail(H, ev):
    err = str(ev.get("error") or "")[:CMD_MAX]
    src = H.refusal_source(err)
    if not src or ev.get("is_interrupt"):
        return
    text = f"{command(ev)} {err}"
    key, _, outcome, _ = H.route(text)
    win, role = who()
    H.log(src, key, outcome, window=win, role=role)
    feat = H.refusal_line(err) if src == "sandbox" else ""
    if feat:   # журнал отказов по классам (metis-1135 Д): guard отказ песочницы не видит, этот хук — видит
        with contextlib.suppress(Exception):
            load_denials().record("sandbox", ev, feat)
    emit("PostToolUseFailure", H.hint(text, src))


def cmd_denied(H, ev):
    text = f"{command(ev)} {str(ev.get('reason') or '')[:CMD_MAX]}"
    key, _, outcome, _ = H.route(text)
    win, role = who()
    H.log("classifier", key, outcome, window=win, role=role)
    p = mark_path(H, ev)
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    tmp = f"{p}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"t": time.time(), "agent_id": ev.get("agent_id"), "hint": H.hint(text, "classifier")}, fh,
                  ensure_ascii=False)
    os.replace(tmp, p)


def cmd_batch(H, ev):
    p = mark_path(H, ev)
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return
    with os.fdopen(fd, encoding="utf-8") as fh:
        mark = json.load(fh)
    if not isinstance(mark, dict) or mark.get("agent_id") != ev.get("agent_id"):
        return   # отметка субагента — его PostToolBatch, не главной сессии (и наоборот)
    taken = f"{p}.{os.getpid()}.taken"
    try:
        os.rename(p, taken)   # забрать атомарно: два хука одной пачки выдадут подсказку один раз
    except OSError:
        return
    os.unlink(taken)
    if time.time() - float(mark.get("t") or 0) <= H.HINT_TTL and isinstance(mark.get("hint"), str):
        emit("PostToolBatch", mark["hint"][:2000])


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    with contextlib.suppress(Exception):
        ev = json.loads(sys.stdin.read() or "{}")
        if not isinstance(ev, dict):
            return 0
        H = load()
        {"fail": cmd_fail, "denied": cmd_denied, "batch": cmd_batch}.get(cmd, lambda *_: None)(H, ev)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
