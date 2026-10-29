"""Пантеон: pantheon instructions — дойдут ли инструкции целиком (Codex, MEMORY.md, CLAUDE.md с импортами).

Вынесено из pantheon.py (metis-0586) без изменения поведения. P — модуль pantheon: его ставит загрузчик
pantheon._attach до выполнения этого файла, имена из __all__ становятся именами pantheon.
"""
import os
import tomllib

__all__ = [
    "MEMORY_LINES", "MEMORY_BYTES", "memory_files", "instructions_check",
]


MEMORY_LINES, MEMORY_BYTES = 200, 25 * 1024   # MEMORY.md автопамяти: дальше при старте не грузится


def memory_files():
    """MEMORY.md автопамяти проектов и памяти ролей → [(файл, строк, байт)]."""
    res = []
    for base, pattern in ((os.path.join(P.HOME, ".claude", "projects"), ("memory", "MEMORY.md")),
                          (os.path.join(P.HOME, ".claude", "agent-memory"), ("MEMORY.md",))):
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for n in names:
            f = os.path.join(base, n, *pattern)
            if os.path.isfile(f):
                res.append((f, P._lines(f), os.path.getsize(f)))
    return res


def instructions_check(quiet=False):
    """pantheon instructions: дойдут ли инструкции до агента целиком (Claude и Codex). Тик — раз в сутки.
    Срез (Codex сверх лимита, MEMORY.md сверх 200 строк или 25 КБ) — тревога на каждый файл; длинные CLAUDE.md —
    одна тревога на набор."""
    try:
        with open(os.path.join(P.PANTHEON, "directions.toml"), "rb") as fh:
            reg = tomllib.load(fh).get("direction") or []
    except (OSError, ValueError):
        reg = []
    roots = []
    for d in reg:
        for f in d.get("folders") or []:
            r = os.path.realpath(os.path.expanduser(f))
            if os.path.isdir(r) and not any(r == x or r.startswith(x.rstrip("/") + "/") for x in roots):
                roots = [x for x in roots if not x.startswith(r.rstrip("/") + "/")] + [r]
    here, limit, glob_size = P.codex_setup()
    short = lambda p: p.replace(P.HOME, "~")
    cut, long_ = [], []
    for root in sorted(roots):
        for d, chain, lines in P.instruction_files(root):
            total = chain + glob_size
            if chain and total > limit:
                msg = (f"Codex: инструкции до {short(d)} — {total // 1024} КиБ при лимите {limit // 1024} КиБ: "
                       "сверх Codex молча обрезает. Общее — в корневой AGENTS.md, подробности — во вложенные AGENTS.md "
                       "папок, процедуры — в навыки")
                cut.append(("codex-" + d, total, msg, here))
            if lines > P.CLAUDE_LINES:
                long_.append(f"{short(d)} — {lines} строк")
    for f, n, b in memory_files():
        if n > MEMORY_LINES or b > MEMORY_BYTES:
            cut.append(("memory-" + f, f"{n}/{b}", f"Claude: {short(f)} — {n} строк, {b // 1024} КБ: дальше "
                        f"{MEMORY_LINES} строк или {MEMORY_BYTES // 1024} КБ при старте не грузится. Сжать: строка на "
                        "запись, подробности — в файлы тем", True))
    if not quiet:
        print(f"Codex на этом Mac: {'да' if here else 'нет'}; лимит {limit // 1024} КиБ"
              + (f", глобальный AGENTS.md {glob_size // 1024} КиБ" if glob_size else ""))
        for _, _, msg, alerting in cut:
            print(("СРЕЗ    " if alerting else "Codex*  ") + msg)
        for x in long_:
            print(f"ДЛИННО  Claude: {x} (с импортами; больше {P.CLAUDE_LINES} — хуже соблюдается)")
        if not cut and not long_:
            print("всё доходит целиком")
        if any(not a for *_, a in cut):
            print("* Codex на этом Mac нет — без тревоги; у того, кто работает в Codex, тревога будет")
        return 1 if any(a for *_, a in cut) else 0
    for key, value, msg, alerting in cut:
        if alerting:
            P.alert_once("instr-" + key, value, msg, "instructions")
    if long_:
        P.alert_once("instr-long", ",".join(sorted(long_)), f"Claude: инструкции длиннее {P.CLAUDE_LINES} строк (хуже "
                   f"соблюдаются): {'; '.join(long_)} — разнести по .claude/rules или вложенным файлам", "instructions")
    else:
        P.clear_once("instr-long")
    return 0
