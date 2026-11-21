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

# --- обход: предел по найденным, вложенные копии — только звенья под шаблоны --------------------------------------
check("into_nested: корень копии, её .claude и .husky — да; код и node_modules вложенной копии — нет",
      all(C.into_nested(p) for p in ("src", ".claude/worktrees", ".claude/worktrees/y", ".claude/worktrees/y/.claude/a",
                                     ".Claude/Worktrees/y/.HUSKY", ".claude/worktrees/y/.claude/worktrees/z"))
      and not any(C.into_nested(p) for p in (".claude/worktrees/y/node_modules", ".claude/worktrees/y/app",
                                             ".claude/worktrees/y/.claude/worktrees/z/src")))
TOP = os.path.join(ROOT, "copy")
for i in range(50):
    put(f"src/f{i}.txt")
    put(f".claude/worktrees/y/node_modules/m{i}/.mcp.json")
for rel in (".claude/hooks/h.sh", ".claude/worktrees/y/.mcp.json", ".claude/worktrees/y/.claude/settings.json",
            "app/.mcp.json"):
    put(rel)
top = os.open(TOP, os.O_RDONLY | os.O_DIRECTORY)
deep = lambda r: C.deep(r)   # noqa: E731
got = C.walk(top, deep, limit=5, nested=True)
check("walk: 50 файлов кода и node_modules вложенной копии предел 5 не обрывают; найдено своё",
      got == sorted([".claude/hooks/h.sh", ".claude/worktrees/y/.mcp.json", ".claude/worktrees/y/.claude/settings.json",
                     "app/.mcp.json"]), got)
check("walk без nested: вложенные копии не обходит", C.walk(top, deep, limit=5) == [".claude/hooks/h.sh", "app/.mcp.json"])
for i in range(10):
    put(f".claude/hooks/x{i}.sh")
try:
    C.walk(top, deep, limit=5, nested=True)
    err = None
except C.Refused as e:
    err = e
check("walk: защищённых больше предела — Refused, найденное до обрыва — в found",
      err is not None and "больше 5" in str(err) and len(getattr(err, "found", [])) > 5, err)
os.close(top)
TOP = os.path.join(ROOT, "hot")   # обход оборвался — точные места хуков и настроек без предела
HOT = [".Claude/Hooks/a/b.sh", ".Claude/Settings.local.json", ".Claude/worktrees/y/.claude/hooks/z.sh",
       ".Claude/worktrees/y/.mcp.json", ".HUSKY/pre-commit", ".mcp.JSON"]
for rel in HOT + [".Claude/skills/x.md", ".Claude/worktrees/y/src/.mcp.json", "src/.mcp.json", ".Claude/other.json"]:
    put(rel)
top = os.open(TOP, os.O_RDONLY | os.O_DIRECTORY)
got = sorted(M.hot_paths(top))
check("hot_paths: хуки, settings*.json, .mcp.json, .husky в корне и во вложенных копиях — без регистра; код — нет",
      got == sorted(HOT), got)
os.close(top)

print(f"\n{TOTAL[0] - len(FAILS)}/{TOTAL[0]} проверок")
if FAILS:
    print("FAIL: " + "; ".join(FAILS))
    sys.exit(1)
