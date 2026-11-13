#!/usr/bin/env python3
"""Список разрешённых инструментов MCP окна роли (metis-1051, ревизия автономности 09.11 F1, решение владельца
[metis-1049-supabase] «А»).

Серверы MCP идут вне песочницы окна, а правила permissions.deny окна закрывают только серверы из [catalog] карты
plugins-by-role.toml. Сервер из .mcp.json проекта, пакета направления или плагина (supabase с записью в базу проекта)
шёл мимо всего. Этот хук — список «разрешено», а не «запрещено»: всё, что в нём не названо, — отказ.

Запуск — хук PreToolUse окна с matcher «mcp__.*» и onFailure "block" (его пишет `pantheon domains build`,
plugin_map.window_apply, из проверенного дерева guard рядом со строгим guard.py):
    /bin/sh hooks/python.sh hooks/mcp_gate.py "<запись>,<запись>,…"
Запись списка — «сервер» (все его инструменты) или «сервер__инструмент», в имени инструмента можно «*»
(«supabase__list_*»). Список окна — ключи mcp (серверы каталога) и mcp_extra (остальное) его записи в карте.

Решение по tool_name события «mcp__<сервер>__<инструмент>»:
  - «сервер» пускает mcp__<сервер>__<инструмент>, если в <инструмент> нет «__»: иначе сервер «qmd__x» из чужого
    .mcp.json прошёл бы под записью «qmd»;
  - «сервер__шаблон» — то же, и <инструмент> подходит под шаблон (fnmatch с учётом регистра).
Код 0 — разрешено (или инструмент не mcp__: matcher его не шлёт); код 2 и причина последней строкой stderr — отказ.
Плохой вход (не JSON, не PreToolUse, нет tool_name), нет аргумента списка или запись не по образцу — тоже код 2:
защита, которая не поняла вызов, его не пропускает. Пустой список («») — окну не разрешён ни один MCP.

Только stdlib; Python 3.11+ (hooks/python.sh). Образец записи — тот же, что MCP_ENTRY в plugins/pantheon/lib/plugin_map.py
(связей между плагинами нет, храповик metis-0854): test_mcp_gate сверяет, что каждая запись настоящей карты проходит.
"""
import fnmatch
import json
import os
import re
import sys

# сервер — слова из [A-Za-z0-9-] через одиночное «_» (plugin_supabase_supabase, claude_ai_Claude_Docs); после «__» —
# шаблон инструмента, в нём ещё «*»
SERVER = r"[A-Za-z0-9-]+(?:_[A-Za-z0-9-]+)*"
ENTRY = re.compile(rf"({SERVER})(?:__([A-Za-z0-9*-]+(?:_[A-Za-z0-9*-]+)*))?")


def parse(arg):
    """Строка «а,б,в» → [(сервер, шаблон или None)]; ValueError — запись не по образцу. Пустая строка — []."""
    out = []
    for item in arg.split(",") if arg else []:
        m = ENTRY.fullmatch(item.strip())
        if not m:
            raise ValueError(f"запись «{item}» списка MCP не по образцу «сервер» или «сервер__инструмент»")
        out.append((m.group(1), m.group(2)))
    return out


def allowed(tool, entries):
    """True, если инструмент tool («mcp__сервер__инструмент») разрешён одной из записей entries (parse)."""
    if not tool.startswith("mcp__"):
        return False
    rest = tool[len("mcp__"):]
    for server, pat in entries:
        if not rest.startswith(server + "__"):
            continue
        name = rest[len(server) + 2:]
        if not name or "__" in name:
            continue
        if pat is None or fnmatch.fnmatchcase(name, pat):
            return True
    return False


def decide(argv, raw):
    """(код, причина) для аргументов хука argv и байтов события raw."""
    if len(argv) != 1:
        return 2, "guard mcp: хуку не передан список разрешённых MCP — вызов остановлен (пересобери окна: pantheon domains build)."
    try:
        entries = parse(argv[0])
    except ValueError as e:
        return 2, f"guard mcp: {e} — вызов остановлен (карта plugins-by-role.toml, пересборка окон)."
    try:
        ev = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        ev = None
    if not isinstance(ev, dict) or ev.get("hook_event_name") != "PreToolUse" or not isinstance(ev.get("tool_name"), str):
        return 2, "guard mcp: событие не разобрано (нужен PreToolUse с tool_name) — вызов остановлен."
    tool = ev["tool_name"]
    if not tool.startswith("mcp__"):
        return 0, ""
    if allowed(tool, entries):
        return 0, ""
    window = os.environ.get("PANTHEON_WINDOW") or "этого окна"
    names = ", ".join(s + (f"__{p}" if p else "") for s, p in entries) or "ни одного"
    return 2, (f"guard mcp: {tool} не в списке разрешённых MCP окна {window} (разрешены: {names}). Нужен ещё "
               "инструмент — правка plugins-by-role.toml (mcp или mcp_extra окна, ядро защит: «да» владельца); "
               "миграции Supabase — `pantheon supabase migrate`, а не MCP.")


def main():
    code, why = decide(sys.argv[1:], sys.stdin.buffer.read())
    if why:
        sys.stderr.write(why + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
