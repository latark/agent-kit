#!/usr/bin/env python3
"""Список разрешённых MCP окна — hooks/mcp_gate.py (metis-1051).

Запуск: python3 -I plugins/guard/tests/test_mcp_gate.py  (код выхода 0 — все прошли)
- разрешённый сервер и инструмент по шаблону — код 0; неразрешённый — код 2, причина последней строкой stderr;
- сервер «qmd__x» не проходит под записью «qmd»; пустой список — ни одного MCP; не mcp__ — не наше дело (0);
- плохой вход, нет аргумента списка, запись не по образцу — код 2 (защита не пропускает непонятное);
- каждая запись mcp и mcp_extra окон настоящей карты plugins-by-role.toml проходит образец хука;
- мутанты внутри теста: без проверки «__» в имени инструмента, без шаблона, с пропуском отказа — тест их ловит.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(os.path.dirname(HERE), "hooks", "mcp_gate.py")
MAP = os.path.join(os.path.dirname(os.path.dirname(HERE)), "pantheon", "plugins-by-role.toml")
PY = sys.executable
results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))


def load(src=None):
    """Модуль хука; src — подменённый текст (мутант)."""
    spec = importlib.util.spec_from_file_location("mcp_gate_t", GATE)
    m = importlib.util.module_from_spec(spec)
    if src is None:
        spec.loader.exec_module(m)
    else:
        exec(compile(src, GATE, "exec"), m.__dict__)
    return m


def ev(tool, name="PreToolUse"):
    return json.dumps({"hook_event_name": name, "tool_name": tool, "tool_input": {}}).encode()


def run(argv, raw, env=None):
    return subprocess.run([PY, "-I", GATE, *argv], input=raw, capture_output=True, timeout=30,
                          env={**os.environ, **(env or {})})


LIST = "qmd,chrome-devtools,supabase__list_*,supabase__execute_sql"
G = load()

r = run([LIST], ev("mcp__qmd__query"))
check("сервер из списка — код 0, без вывода", r.returncode == 0 and not r.stderr, r.stderr)
r = run([LIST], ev("mcp__chrome-devtools__click"))
check("сервер с дефисом — код 0", r.returncode == 0, r.stderr)
r = run([LIST], ev("mcp__supabase__list_tables"))
check("инструмент по шаблону supabase__list_* — код 0", r.returncode == 0, r.stderr)
r = run([LIST], ev("mcp__supabase__apply_migration"), {"PANTHEON_WINDOW": "athena-x"})
last = r.stderr.decode().strip().splitlines()[-1] if r.stderr.strip() else ""
check("supabase__apply_migration вне списка — код 2, причина последней строкой с окном и подсказкой",
      r.returncode == 2 and "mcp__supabase__apply_migration" in last and "athena-x" in last
      and "pantheon supabase migrate" in last, r.stderr)
r = run([LIST], ev("mcp__plugin_supabase_supabase__execute_sql"))
check("сервер вне списка (plugin_supabase_supabase) — код 2", r.returncode == 2, r.stderr)
r = run([LIST], ev("mcp__upstash__redis_delete"))
check("сервер вне списка (upstash) — код 2", r.returncode == 2, r.stderr)
r = run([LIST], ev("mcp__qmd__x__query"))
check("сервер «qmd__x» под записью «qmd» не проходит — код 2", r.returncode == 2, r.stderr)
r = run([LIST], ev("mcp__qmdx__query"))
check("сервер с тем же началом имени (qmdx) — код 2", r.returncode == 2, r.stderr)
r = run([LIST], ev("mcp__qmd__"))
check("пустое имя инструмента — код 2", r.returncode == 2, r.stderr)
r = run([LIST], ev("mcp__SUPABASE__list_tables"))
check("регистр имени сервера учитывается — код 2", r.returncode == 2, r.stderr)
r = run([""], ev("mcp__qmd__query"))
check("пустой список — ни одного MCP (код 2)", r.returncode == 2 and "ни одного" in r.stderr.decode(), r.stderr)
r = run([LIST], ev("Bash"))
check("не mcp__ — код 0 (matcher его не шлёт)", r.returncode == 0, r.stderr)
r = run([], ev("mcp__qmd__query"))
check("нет аргумента списка — код 2", r.returncode == 2 and "список" in r.stderr.decode(), r.stderr)
r = run([LIST, "лишний"], ev("mcp__qmd__query"))
check("два аргумента — код 2", r.returncode == 2, r.stderr)
r = run(["qmd,bad name"], ev("mcp__qmd__query"))
check("запись не по образцу — код 2 и её имя в причине", r.returncode == 2 and "bad name" in r.stderr.decode(), r.stderr)
r = run(["qmd,a___b"], ev("mcp__qmd__query"))
check("тройное подчёркивание в записи — не по образцу, код 2", r.returncode == 2, r.stderr)
for raw, what in ((b"not json", "не JSON"), (ev("mcp__qmd__query", "PostToolUse"), "не PreToolUse"),
                  (json.dumps({"hook_event_name": "PreToolUse"}).encode(), "нет tool_name"),
                  (b"\xff\xfe", "не UTF-8")):
    r = run([LIST], raw)
    check(f"плохой вход ({what}) — код 2", r.returncode == 2, r.stderr)

# образец записи карты — тот же
with open(MAP, "rb") as fh:
    real = tomllib.load(fh)
entries = [x for w in real["window"].values() for x in w.get("mcp", []) + w.get("mcp_extra", [])]
bad = [x for x in entries if not G.ENTRY.fullmatch(x)]
check("каждая запись mcp и mcp_extra окон настоящей карты проходит образец хука", entries and not bad, bad)
d = real["window"]["direction"]
allow = G.parse(",".join(d["mcp"] + d.get("mcp_extra", [])))
want_ok = ["mcp__qmd__query", "mcp__chrome-devtools__take_snapshot", "mcp__next-devtools__nextjs_index",
           "mcp__supabase__execute_sql", "mcp__plugin_supabase_supabase__list_tables", "mcp__upstash__redis_get",
           "mcp__claude_ai_Claude_Docs__read", "mcp__plugin_context7_context7__query-docs"]
want_no = ["mcp__plugin_supabase_supabase__execute_sql", "mcp__plugin_supabase_supabase__apply_migration",
           "mcp__supabase__apply_migration", "mcp__supabase__deploy_edge_function", "mcp__plugin_Notion_notion__search",
           "mcp__computer-use__click", "mcp__claude_ai_Gmail__send"]
check("окно направления: нужные серверы разрешены (chrome-devtools, next-devtools, чтение supabase, upstash)",
      all(G.allowed(t, allow) for t in want_ok), [t for t in want_ok if not G.allowed(t, allow)])
check("окно направления: запись supabase, Notion, computer-use и незнакомый сервер — нет",
      not any(G.allowed(t, allow) for t in want_no), [t for t in want_no if G.allowed(t, allow)])
h = real["window"]["hestia"]
check("Гестия: ни одного MCP", not G.allowed("mcp__qmd__query", G.parse(",".join(h["mcp"] + h.get("mcp_extra", [])))))

# мутанты: каждая ветка решения нужна
SRC = open(GATE, encoding="utf-8").read()


def mutant(old, new):
    src = SRC.replace(old, new, 1)
    assert src != SRC, old
    return load(src)


M1 = mutant('if not name or "__" in name:', "if not name:")
check("мутант (нет проверки «__» в имени инструмента) пускает сервер qmd__x — тест это видит",
      M1.allowed("mcp__qmd__x__query", M1.parse("qmd")) and not G.allowed("mcp__qmd__x__query", G.parse("qmd")))
M2 = mutant("if pat is None or fnmatch.fnmatchcase(name, pat):", "if True:")
check("мутант (шаблон инструмента не сверяется) пускает apply_migration — тест это видит",
      M2.allowed("mcp__supabase__apply_migration", M2.parse("supabase__list_*"))
      and not G.allowed("mcp__supabase__apply_migration", G.parse("supabase__list_*")))
M3 = mutant('if not rest.startswith(server + "__"):', 'if not rest.startswith(server):')
check("мутант (имя сервера без «__») пускает qmdx — тест это видит",
      M3.allowed("mcp__qmdx__query", M3.parse("qmd")) and not G.allowed("mcp__qmdx__query", G.parse("qmd")))
M4 = mutant("    if allowed(tool, entries):\n        return 0, \"\"", "    if True:\n        return 0, \"\"")
check("мутант (отказ пропущен) — decide даёт 0 там, где настоящий даёт 2",
      M4.decide([LIST], ev("mcp__upstash__x"))[0] == 0 and G.decide([LIST], ev("mcp__upstash__x"))[0] == 2)
M5 = mutant('return 2, "guard mcp: событие не разобрано', 'return 0, "guard mcp: событие не разобрано')
check("мутант (плохой вход пропущен) — тест это видит", M5.decide([LIST], b"x")[0] == 0 and G.decide([LIST], b"x")[0] == 2)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
