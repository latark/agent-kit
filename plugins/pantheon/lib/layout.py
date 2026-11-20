"""Раскладка папок (metis-0899): карта «что где» одним местом и проверка «папка вне раскладки».

Решение владельца 06.11 [metis-0895]: ~/ai — владелец и система, ~/projects — только рабочие проекты, ~/projects/other —
прочее, ~/projects/archive — старое, вне работы; ~/ai/life — папка без .git, у каждой области свой git (06.11 06:49).

  pantheon layout   карта «что где» (LAYOUT) и папки вне неё; код 1 — есть папки вне раскладки, 0 — нет.
  pantheon check    те же папки — предупреждением, в плановом проходе — тревогой раз на набор (check_layout); код check не меняет.
  pantheon direction check <имя>   строка «папки по карте „что где“» для папок направления (folder_ok).

Вне раскладки (problems):
  - ~/ai/<x>, которой нет в карте;
  - .git у самой ~/ai/life; область ~/ai/life/<x> без своего .git или ссылкой;
  - ~/projects/<x> не из папок directions.toml, не other/ и не archive/ (старая папка несделанного переноса из
    lib/moved.py — ещё по карте: переезжает по плану 0899);
  - папка направления в directions.toml вне карты (не ~/projects/…, не папка системы в ~/ai, не ~/ai/life/<x>/…, не
    ~/.claude) или в ~/projects/archive.
Скрытые имена и файлы не смотрит; содержимое областей ~/ai/life не читает — только имена их папок и наличие .git.
problems() — без P и без диска сверх listdir/lexists: тест гоняет её и её мутанты напрямую.
"""
import os
import sys
import tomllib

# P — модуль pantheon: его ставит загрузчик pantheon._attach до exec_module (F821 для lib/ выключен в ruff.toml)
__all__ = ["layout_cmd", "check_layout", "layout_folder_ok"]

# Карта «что где»: (путь от HOME частями, что лежит, git). Части, а не «~/…» строкой — как MOVES в lib/moved.py.
LAYOUT = (
    (("ai", "pantheon"), "Пританей: доска, задачи, STATUS, реестр", "свой"),
    (("ai", "pantheon-view"), "вид доски", "свой"),
    (("ai", "knowledge"), "база знаний; me, Self, Areas, People — личное", "свой"),
    (("ai", "agent-kit"), "плагины Пантеона (до переноса — в ~/projects)", "свой"),
    (("ai", "workshop"), "мастерская Дедала, <задача>/ (до переноса — в ~/projects)", "по задаче"),
    (("ai", "life"), "личное владельца: <область>/ — финансы, карьера, здоровье, английский", "у папки нет, у области свой"),
    (("projects",), "рабочие проекты, <имя>/ на верхнем уровне — в папках своего направления (directions.toml)", "свои"),
    (("projects", "other"), "прочее: инструменты системы и мелкие утилиты", "свои"),
    (("projects", "archive"), "старое, вне работы", "—"),
    ((".claude",), "настройки Claude Code, роли, память ролей", "—"),
)
AI_KNOWN = {p[1] for p, _, _ in LAYOUT if p[0] == "ai"}
PROJECTS_OWN = {"other", "archive"}


def _dirs(d):
    """Нескрытые папки и ссылки в d: [(имя, путь)]; нет папки или нет доступа (окно роли) — пусто."""
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(d, n)
        if not n.startswith(".") and (os.path.islink(p) or os.path.isdir(p)):
            out.append((n, p))
    return out


def _under(p, root):
    return p == root or p.startswith(root + os.sep)


def folder_ok(f, home):
    """Папка направления по карте: ~/projects/… (не archive), папка системы в ~/ai, ~/ai/life/<x>/…, ~/.claude."""
    p = os.path.normpath(os.path.join(home, f[2:]) if f.startswith("~/") else f)
    j = lambda *a: os.path.join(home, *a)
    if _under(p, j("projects", "archive")):
        return False
    if p != j("projects") and _under(p, j("projects")):
        return True
    if any(_under(p, j("ai", x)) for x in AI_KNOWN - {"life"}):
        return True
    if p != j("ai", "life") and _under(p, j("ai", "life")):
        return True
    return _under(p, j(".claude"))


def problems(home, reg, pending):
    """Папки вне раскладки. reg — {направление: [папки как в directions.toml]}, pending — старые папки несделанных
    переносов (полные пути). → [(ключ, текст)]."""
    out = []
    short = lambda p: "~" + p[len(home):] if _under(p, home) else p
    real = lambda f: os.path.realpath(os.path.join(home, f[2:]) if f.startswith("~/") else f)
    for n, p in _dirs(os.path.join(home, "ai")):
        if n not in AI_KNOWN:
            out.append((short(p), f"{short(p)}: нет в карте «что где» — ~/ai только для системы и личного (life/)"))
    life = os.path.join(home, "ai", "life")
    if os.path.lexists(os.path.join(life, ".git")):
        out.append((short(life) + "/.git", f"{short(life)}: свой .git — у ~/ai/life git нет, у каждой области свой"))
    for _, p in _dirs(life):
        if os.path.islink(p):
            out.append((short(p), f"{short(p)}: ссылка — область только настоящей папкой"))
        elif not os.path.lexists(os.path.join(p, ".git")):
            out.append((short(p), f"{short(p)}: область без своего git — pantheon direction init или git init в ней"))
    used = [real(f) for fs in reg.values() for f in fs if isinstance(f, str) and f]
    for n, p in _dirs(os.path.join(home, "projects")):
        rp = os.path.realpath(p)
        if n in PROJECTS_OWN or p in pending or any(_under(u, rp) for u in used):
            continue
        out.append((short(p), f"{short(p)}: нет в папках направлений directions.toml — работа: строка в folders "
                              "направления; инструмент — в ~/projects/other; старое — в ~/projects/archive"))
    for name, fs in sorted(reg.items()):
        for f in fs:
            if isinstance(f, str) and f and not folder_ok(f, home):
                out.append((f"{name}:{f}", f"папка {f} направления {name}: вне карты «что где» (pantheon layout)"))
    return out


def _registry():
    try:
        with open(os.path.join(P.PANTHEON, "directions.toml"), "rb") as fh:
            dirs = tomllib.load(fh).get("direction") or []
    except (OSError, ValueError):
        return {}
    return {d.get("name") or "?": [f for f in d.get("folders") or [] if isinstance(f, str)]
            for d in dirs if isinstance(d, dict) and isinstance(d.get("folders") or [], list)}


def _found():
    M = P.moved_mod()
    pending = {M.paths(n, P.HOME)[0] for n in M.MOVES if not M.done(n, P.HOME)}
    return problems(P.HOME, _registry(), pending)


def layout_folder_ok(f):
    return folder_ok(f, P.HOME)


def check_layout(quiet):
    """pantheon check: папки вне раскладки — предупреждение, в плановом проходе — тревога раз на набор. → список проблем."""
    found = _found()
    if not quiet:
        for _, text in found:
            print(f"предупреждение · раскладка · {text}")
    elif found:
        P.alert_once("check-layout", "|".join(k for k, _ in found),
                     f"папки вне раскладки: {len(found)} — {found[0][1]}" + (" и др." if len(found) > 1 else "")
                     + "; список — pantheon layout", "check")
    else:
        P.clear_once("check-layout")
    return found


def layout_cmd(rest):
    """pantheon layout — карта «что где» и папки вне неё. Код 1 — есть папки вне раскладки."""
    if rest:
        print("pantheon layout — без аргументов", file=sys.stderr)
        return 2
    print("| Папка | Что лежит | git |\n|---|---|---|")
    for parts, what, git in LAYOUT:
        print(f"| ~/{'/'.join(parts)} | {what} | {git} |")
    found = _found()
    print()
    for _, text in found:
        print(f"вне раскладки · {text}")
    print(f"папок вне раскладки: {len(found)}" if found else "все папки по карте")
    return 1 if found else 0
