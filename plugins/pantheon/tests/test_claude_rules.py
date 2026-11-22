#!/usr/bin/env python3
"""`pantheon outside claude-sync` (lib/claude_sync.py, metis-1327): правила путей и обхода без git и сервера.

Запуск: python3 -I plugins/pantheon/tests/test_claude_rules.py  (код выхода 0 — все прошли)
  - какие пути защищены (шаблоны песочницы), без регистра и нормализации Unicode, вложенные копии .claude/worktrees/*;
  - odd — защищённый для песочницы путь, который сверка буква в букву не узнаёт; что можно удалять;
  - свой драйвер в .gitattributes;
  - обход walk: предел — по найденным, а не по всем файлам (найденное до обрыва — в отказе), во вложенных копиях —
    только корень копии, .claude и .husky (не node_modules и код).
Слияние и откат — в test_claude_sync.py.
"""
import atexit
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311, mkroot  # pantheon.py — только на Python 3.11+

if sys.version_info < (3, 11):
    os.execv(PY311, [PY311, "-I", os.path.abspath(__file__)] + sys.argv[1:])

ROOT = os.path.realpath(mkroot("claude-rules-"))
atexit.register(shutil.rmtree, ROOT, True)
HOME = os.path.join(ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE"))]:
    os.environ.pop(k)
os.environ.update({"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1"})
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "lib"))
import pantheon as P  # noqa: E402

C = P.outside_mod().sub_mod("claude-sync")
M = C.mm()
FAILS, TOTAL = [], [0]


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{extra}]"))
    if not cond:
        FAILS.append(name)


def put(rel, text="x\n"):
    path = os.path.join(TOP, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


# --- шаблоны песочницы ---------------------------------------------------------------------------------------------
check("защищены навык, команда, агент, хук, настройки, .mcp.json на любой глубине",
      all(C.protected(p) for p in (".claude/skills/a/SKILL.md", ".claude/commands/c.md", ".claude/agents/x.md",
                                   ".claude/hooks/h.sh", ".claude/settings.json", ".claude/settings.local.json",
                                   ".mcp.json", "app/.mcp.json", "app/.claude/skills/b/SKILL.md", ".husky/pre-commit")))
check("не защищены README, .claude/other, вложенные копии .claude/worktrees/*",
      not any(C.protected(p) for p in ("README.md", ".claude/other.md", ".claude/worktrees/x/.claude/skills/a",
                                       "src/settings.json", "../.mcp.json")))
check("регистр и нормализация Unicode — та же защита (APFS и песочница их не различают)",
      all(C.protected(p) for p in (".Claude/Settings.json", ".mcp.JSON", ".claude/Hooks/x.sh", "a/.HUSKY/h"))
      and C.fold("e\u0301") == C.fold("\u00c9") and not C.protected(".Claude/Worktrees/x/.claude/settings.json"))
check("odd: защищено не буква в букву или во вложенной копии — да; буква в букву и код — нет",
      all(C.odd(p) for p in (".claude/Settings.local.json", ".mcp.JSON", ".claude/worktrees/y/.claude/settings.json",
                             ".Claude/worktrees/y/.mcp.json"))
      and not any(C.odd(p) for p in (".claude/settings.json", "app/.mcp.json", "README.md", ".claude/worktrees/y/a")))
check("удалять можно только навыки, команды и агентов",
      all(C.deletable(p) for p in (".claude/skills/x/SKILL.md", ".claude/commands/c.md", "a/.claude/agents/x.md")))
check("настройки, .mcp.json, хуки, .husky и настройки внутри навыка — не удаляются",
      not any(C.deletable(p) for p in (".claude/settings.json", ".claude/settings.local.json", ".mcp.json",
                                       ".claude/hooks/h.sh", ".husky/pre-commit", ".claude/skills/x/.claude/settings.json",
                                       ".claude/skills/x/.claude/hooks/h.sh")))
check("свой драйвер в атрибутах найден, встроенные — нет",
      M.bad_attrs("# c\n* merge=evil\n*.py diff=python\n*.bin -diff binary\n[attr]m filter=lfs\nx merge=union", "f")
      == ["f: merge=evil", "f: filter=lfs"], M.bad_attrs("* merge=evil\n[attr]m filter=lfs", "f"))

# --- обход: предел по найденным, вложенные копии и подпапки — целиком; папку не прочесть — громко ---------------------
TOP = os.path.join(ROOT, "copy")
FOUND = [".claude/hooks/h.sh", ".claude/worktrees/y/.mcp.json", ".claude/worktrees/q/sub/.claude/settings.json",
         ".claude/worktrees/y/app.git/hooks/x", ".claude/worktrees/y/node_modules/m/.mcp.json", "app/.mcp.json",
         "a/b/c/.claude/skills/s/SKILL.md"]
for i in range(50):
    put(f"src/f{i}.txt")
    put(f".claude/worktrees/y/node_modules/m/f{i}.js")
for rel in FOUND:
    put(rel)
top = os.open(TOP, os.O_RDONLY | os.O_DIRECTORY)
deep = lambda r: C.deep(r)   # noqa: E731
got = C.walk(top, deep, limit=len(FOUND), nested=True)
check("walk: 100 файлов кода предел не обрывают; вложенные копии и подпапки любой глубины — целиком", got == sorted(FOUND), got)
check("walk без nested: вложенные копии не обходит", C.walk(top, deep) == sorted(f for f in FOUND if ".claude/worktrees" not in f))
for i in range(10):
    put(f".claude/hooks/x{i}.sh")
try:
    C.walk(top, deep, limit=5, nested=True)
    err = None
except C.Refused as e:
    err = e
check("walk: защищённых больше предела — Refused", err is not None and "больше 5" in str(err), err)
check("walk: NO_LIMIT — без предела", len(C.walk(top, deep, limit=C.NO_LIMIT, nested=True)) == len(FOUND) + 10)
os.chmod(os.path.join(TOP, "a/b"), 0)
errs = []
got = C.walk(top, deep, limit=C.NO_LIMIT, nested=True, errors=errs)
try:
    C.walk(top, deep, nested=True)
    err = None
except C.Refused as e:
    err = e
os.chmod(os.path.join(TOP, "a/b"), 0o755)
check("walk: папку не открыть — с errors строка и обход дальше, без errors — Refused",
      errs == ["a/b/: не открыта (PermissionError)"] and ".claude/hooks/h.sh" in got and err is not None
      and "не открыта" in str(err), (errs, err))
for n in (60, 70):   # цепочка папок: линейно и с пределом глубины
    put("chain/" + "c/" * n + ".mcp.json")
t0 = time.monotonic()
errs, got = [], C.walk(top, deep, limit=C.NO_LIMIT, nested=True, errors=[])
took = time.monotonic() - t0
check("walk: цепочка в 60 звеньев — быстрее 1 с, найдено внизу", took < 1 and "chain/" + "c/" * 60 + ".mcp.json" in got, took)
C.walk(top, deep, limit=C.NO_LIMIT, nested=True, errors=errs)
try:
    C.walk(top, deep, nested=True)
    err = None
except C.Refused as e:
    err = e
check("walk: глубже DEPTH_MAX — с errors строка, без errors — Refused", errs == ["chain/" + "c/" * 64 + ": глубже 64 звеньев"]
      and err is not None and "глубже 64" in str(err), (errs, err))
errs, bad_fd = [], os.open(TOP, os.O_RDONLY | os.O_DIRECTORY)
os.close(bad_fd)   # папка открыта, а прочесть нельзя (EBADF) — как сбой чтения после открытия
items = list(C._items([bad_fd, "x/", None], errs))
try:
    C._items([bad_fd, "x/", None], None)
    err = None
except C.Refused as e:
    err = e
check("walk: папку не прочесть — с errors строка и пусто, без errors — Refused",
      items == [] and errs == ["x/: не прочитана (OSError)"] and err is not None and "не прочитана" in str(err), (errs, err))
mono, ticks, seen, errs = C.time.monotonic, [0], [], []
C.time.monotonic = lambda: ticks.__setitem__(0, ticks[0] + 1) or ticks[0]
C.DEADLINE = 40
C.walk(top, deep, limit=C.NO_LIMIT, nested=True, errors=errs, on_found=seen.append)
C.DEADLINE, C.time.monotonic = None, mono
check("walk: срок истёк — стоп и строка, найденное до него — уже в on_found", errs == [f"срок прохода ({C.PASS_MAX} с) истёк"]
      and seen, (errs, seen))
os.close(top)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} проверок")
if FAILS:
    print("FAIL: " + "; ".join(FAILS))
    sys.exit(1)
