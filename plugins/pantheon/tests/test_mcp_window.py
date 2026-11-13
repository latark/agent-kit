#!/usr/bin/env python3
"""Хук списка разрешённых MCP в настройках окна (metis-1051): plugin_map.window_apply с guard.

Запуск: python3 -I plugins/pantheon/tests/test_mcp_window.py  (код выхода 0 — все прошли)
- mcp_extra: необязательный ключ записи окна, записи по образцу; у роли — ошибка; плохая запись — ValueError;
- window_apply с guard (путь guard.py дерева, где есть mcp_gate.py и python.sh): хук PreToolUse «mcp__.*» с
  onFailure block и списком mcp + mcp_extra; повтор — без второго хука; без guard или без mcp_gate.py рядом — хука нет;
- команда хука из настоящей карты, запущенная как есть на настоящем hooks/mcp_gate.py: окну направления
  chrome-devtools и чтение supabase можно, apply_migration и незнакомый сервер — отказ (код 2); hq — без chrome-devtools;
- `domains build` передаёт guard в window_apply у каждого окна (вызовы в pantheon.py);
- мутанты внутри теста: без вызова хука, без mcp_extra в списке, без замены прежнего хука — тест их ловит.
"""
import atexit
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib")
MAP = os.path.join(PLUGIN, "plugins-by-role.toml")
GUARD_HOOKS = os.path.join(os.path.dirname(PLUGIN), "guard", "hooks")
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="mcp-window-test-"))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))


SRC = open(os.path.join(LIB, "plugin_map.py"), encoding="utf-8").read()


def load(src=SRC):
    spec = importlib.util.spec_from_file_location("plugin_map_mcp_t", os.path.join(LIB, "plugin_map.py"))
    m = importlib.util.module_from_spec(spec)
    exec(compile(src, spec.origin, "exec"), m.__dict__)
    return m


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


M = load()
CAT = '[catalog]\nplugins = ["a@b"]\nmcp = ["qmd", "ctx"]\n'


def parse(text):
    p = os.path.join(ROOT, "m.toml")
    write(p, CAT + text)
    try:
        return M.load(p)
    except ValueError as e:
        return str(e)


pm = parse('[window.w1]\nplugins = []\nmcp = ["qmd"]\nmcp_extra = ["chrome-devtools", "supabase__list_*"]\n'
           '[window.w2]\nplugins = []\nmcp = []\n')
check("mcp_extra разобран; у записи без него ключа нет (прежний вид записи)",
      isinstance(pm, dict) and pm["window"]["w1"]["mcp_extra"] == ["chrome-devtools", "supabase__list_*"]
      and pm["window"]["w2"] == {"plugins": [], "mcp": []}, pm)
for text, what in (('[window.w1]\nplugins = []\nmcp = []\nmcp_extra = ["bad name"]\n', "пробел в записи"),
                   ('[window.w1]\nplugins = []\nmcp = []\nmcp_extra = "qmd"\n', "строка, а не список"),
                   ('[window.w1]\nplugins = []\nmcp = []\nmcp_extra = ["a___b"]\n', "тройное подчёркивание"),
                   ('[role.r1]\nmcp = []\nmcp_extra = ["x"]\n', "у роли")):
    check(f"mcp_extra: {what} — ValueError", isinstance(parse(text), str), parse(text))

# поддельное дерево guard: guard.py, python.sh и mcp_gate.py рядом
fake = os.path.join(ROOT, "guard", "hooks")
for f in ("guard.py", "python.sh", "mcp_gate.py"):
    write(os.path.join(fake, f), "# заглушка\n")
guard = os.path.join(fake, "guard.py")


def gate_groups(data):
    return [g for g in (data.get("hooks") or {}).get("PreToolUse") or [] if g.get("matcher") == "mcp__.*"]


d = M.window_apply({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}}, pm, "w1", guard=guard)
g = gate_groups(d)
cmd = g[0]["hooks"][0]["command"] if g else ""
check("window_apply с guard: один хук mcp__.* с onFailure block и timeout, прежний хук окна на месте",
      len(g) == 1 and g[0]["hooks"][0]["onFailure"] == "block" and g[0]["hooks"][0]["timeout"] == 10
      and d["hooks"]["PreToolUse"][0]["matcher"] == "Bash", d)
check("команда хука: python.sh и mcp_gate.py того же дерева, список mcp + mcp_extra одним аргументом",
      shlex.split(cmd) == ["/bin/sh", os.path.join(fake, "python.sh"), os.path.join(fake, "mcp_gate.py"),
                           "qmd,chrome-devtools,supabase__list_*"], cmd)
d2 = M.window_apply(M.window_apply({}, pm, "w1", guard=guard), pm, "w1", guard=guard)
check("повторная сборка — один хук, а не два", len(gate_groups(d2)) == 1, d2)
d = M.window_apply({}, pm, "w2", guard=guard)
check("окно с пустым списком — хук с пустым аргументом (ни одного MCP)",
      shlex.split(gate_groups(d)[0]["hooks"][0]["command"])[-1] == "" if gate_groups(d) else False, d)
check("без guard — хука нет (как раньше)", gate_groups(M.window_apply({}, pm, "w1")) == [])
check("окна нет в карте — хука нет", gate_groups(M.window_apply({}, pm, "zzz", guard=guard)) == [])
old = os.path.join(ROOT, "old", "hooks")
write(os.path.join(old, "guard.py"), "#\n")
write(os.path.join(old, "python.sh"), "#\n")
check("в дереве guard нет mcp_gate.py (выпуск старее) — хука нет",
      gate_groups(M.window_apply({}, pm, "w1", guard=os.path.join(old, "guard.py"))) == [])

# настоящая карта и настоящий mcp_gate.py: команда хука запускается как есть
real = M.load(MAP)
real_guard = os.path.join(GUARD_HOOKS, "guard.py")


def hook_run(window, tool, direction=False):
    data = M.window_apply({}, real, window, direction, real_guard)
    groups = gate_groups(data)
    if not groups:
        return None
    ev = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {}})
    return subprocess.run(groups[0]["hooks"][0]["command"], shell=True, input=ev, capture_output=True, text=True,
                          timeout=60).returncode


for tool, want in (("mcp__chrome-devtools__click", 0), ("mcp__supabase__list_tables", 0), ("mcp__qmd__query", 0),
                   ("mcp__supabase__apply_migration", 2), ("mcp__plugin_supabase_supabase__execute_sql", 2),
                   ("mcp__evil__x", 2)):
    got = hook_run("athena-x", tool, True)
    check(f"окно направления: {tool} — код {want}", got == want, got)
check("hq: chrome-devtools — отказ, qmd — можно",
      hook_run("hq", "mcp__chrome-devtools__click") == 2 and hook_run("hq", "mcp__qmd__query") == 0)
check("hestia: qmd — отказ", hook_run("hestia", "mcp__qmd__query") == 2)

# domains build: guard передан у каждого окна
PAN = open(os.path.join(LIB, "pantheon.py"), encoding="utf-8").read()
calls = re.findall(r"PLUGIN_MAP\.window_apply\(([^)]*)\)", PAN)
check("pantheon.py: каждый вызов window_apply передаёт guard (окна направлений, job-*, hestia, hq)",
      len(calls) == 4 and all(re.search(r"(?:^|,\s*)(?:guard=)?guard$", c.strip()) for c in calls), calls)


# мутанты
def mutant(old, new):
    src = SRC.replace(old, new, 1)
    assert src != SRC, old
    return load(src)


M1 = mutant("    if guard:\n        mcp_gate_hook(", "    if False:\n        mcp_gate_hook(")
check("мутант (хук не пишется) — хука нет, тест это видит", gate_groups(M1.window_apply({}, pm, "w1", guard=guard)) == [])
M2 = mutant('keep["mcp"] + keep.get("mcp_extra", [])', 'keep["mcp"]')
c2 = gate_groups(M2.window_apply({}, pm, "w1", guard=guard))[0]["hooks"][0]["command"]
check("мутант (mcp_extra не в списке) — chrome-devtools пропал, тест это видит", "chrome-devtools" not in c2
      and "chrome-devtools" in cmd)
M3 = mutant("    pre[:] = [g for g in pre if not", "    pre[:] = [g for g in pre if True or not")
check("мутант (прежний хук не заменяется) — два хука, тест это видит",
      len(gate_groups(M3.window_apply(M3.window_apply({}, pm, "w1", guard=guard), pm, "w1", guard=guard))) == 2)
M4 = mutant("if not (os.path.isfile(gate) and os.path.isfile(launcher)):", "if False:")
check("мутант (нет проверки mcp_gate.py рядом) — хук на несуществующий файл, тест это видит",
      gate_groups(M4.window_apply({}, pm, "w1", guard=os.path.join(old, "guard.py"))) != [])

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
