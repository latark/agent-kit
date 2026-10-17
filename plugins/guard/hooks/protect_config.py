"""protect-config (SEC-14) — часть ядра защит guard (Д3): этот файл, merge_gate.py и managed-settings.json агенты
не сливают — PR ждёт слияния владельцем.

Модуль без своего состояния: общие помощники (HOME, who, privileged, write_targets, _inside, _key…) берутся из
guard.py через G — его присваивает guard.py при загрузке (`protect_config.G = <модуль guard>`). Пути считаются при
вызове, а не при импорте: тесты подменяют HOME.

protect-config: защиты правит только metis-pantheon — главная сессия координатора, чья папка запуска в её записи
policy.toml, — задачей после вашего «да» в её сессии. Её субагенты, штаб, другие роли и любые субагенты сюда не
пишут (domain пустил бы субагентов Метиды: ~/.claude — её направление). Ваши сессии без роли не ограничены. Сюда
же — метка .sync-held, по которой sync.sh держит неодобренные правки ~/.claude (SEC-15), и .git репозитория
claude-config: коммит в обход sync.sh отправил бы правку на другие Mac без «да».
Список расширен по проверке безопасности 14.10: всё, откуда код или инструкции запускаются сами — инструменты и
глобальные правила ~/.claude, ссылка тика и команды в ~/.local, задачи launchd, профили оболочки, настройки git
(hooksPath, алиасы с «!»), ~/.ssh (authorized_keys, ProxyCommand), ~/.claude.json (MCP-серверы запускают команды);
в любом репозитории — .claude/settings*.json, .claude/agents/, hooks/, skills/, commands/, сама папка .claude как цель
записи (cp -R x <репо>/.claude/, mv, tar -C, rsync: в неё можно положить settings.json и agents), .mcp.json, .git/hooks
и .git/config. Цель выше .claude тоже (metis-0177): дерево, распакованное или скопированное в сам репозиторий или в
папку над репозиториями (tar -C, unzip -d, cp -R, ditto, rsync, scp -r), и git clone в <репо>/.claude.
"""

import os
import re

G = None  # модуль guard.py: присваивает guard.py при загрузке

CLAUDE_ITEMS = ("hooks", "agents", "plugins", "pantheon", "settings.json", "settings.local.json", "sync.sh",
                "statusline.sh", "bootstrap.sh", ".sync-held", ".sync-incoming", ".git", "tools", "CLAUDE.md", "rules",
                "commands", "output-styles")
HOME_ITEMS = (".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bashrc", ".bash_profile", ".profile", ".gitconfig",
              ".config/git", ".ssh", ".claude.json", ".local/share/pantheon", ".local/bin", "Library/LaunchAgents")
SETTINGS_NAMES = {"settings.json", "settings.local.json"}
PROJECT_ITEMS = {"hooks", "skills", "commands"}  # <репо>/.claude/<x>: как agents (metis-0177)


def protected():
    """Защищённые пути (realpath) для текущего HOME."""
    home = G.HOME
    return ([os.path.realpath(os.path.join(home, ".claude", x)) for x in CLAUDE_ITEMS] +
            [os.path.realpath(os.path.join(home, x)) for x in HOME_ITEMS])


def _settings_file(p, mkdir_only=False):
    """Настройки, которые меняют разрешения, хуки или запускают код в любом репозитории: .claude/settings*.json,
    .claude/agents/ (роли проекта), сама папка .claude (цель записи, чьё последнее звено — .claude), .mcp.json,
    .git/hooks/… и .git/config. Внутри .claude остальное (worktrees/…) не защищено этим правилом."""
    key = G._key
    parent, base = os.path.split(p)
    # tar -x -C, unzip -d, wget -P дают цель «новый файл в папке» (ANY_FILE): смотрим саму папку
    last = os.path.basename(parent) if base == G.ANY_FILE else base
    if key(last) == ".claude" and not mkdir_only:  # пустую папку mkdir ничего не запускает
        return True  # сама папка <репо>/.claude как цель (cp -R x <репо>/.claude/, mv, tar -C, rsync): внутри settings и agents
    if key(base) in SETTINGS_NAMES and key(os.path.basename(parent)) == ".claude":
        return True
    if key(base) == ".mcp.json":
        return True
    parts = [key(x) for x in p.split("/")]
    # роли проекта: `<репо>/.claude/agents/<имя>.md` перекрывает пользовательскую роль (metis-0057), в том числе
    # в worktree `.claude/worktrees/<x>/.claude/agents/`; сама папка тоже (mkdir). Хуки, навыки и команды проекта
    # запускаются или читаются как инструкции так же (metis-0177); у ~/.claude их судит список CLAUDE_ITEMS
    home_claude = key(os.path.realpath(os.path.join(G.HOME, ".claude")))
    for i, x in enumerate(parts[:-1]):
        if x == ".claude" and (parts[i + 1] == "agents" or parts[i + 1] in PROJECT_ITEMS
                               and "/".join(parts[:i + 1]) != home_claude):
            return True
    for i, x in enumerate(parts[:-1]):
        if x == ".git" and (parts[i + 1] == "hooks" or (parts[i + 1] == "config" and i + 2 == len(parts))):
            return True
    return False


# команда — одна простая mkdir (или install -d) без составных частей: создать пустую папку .claude можно (settings и
# agents в неё кладут cp, mv, tar, rsync — они по-прежнему отказ)
MKDIR_ONLY = re.compile(r"\s*(?:g?mkdir|g?install\s+-d)\b[^;&|<>\n$`()]*\Z")

# Копии дерева: в папку-цель ложится поддерево с любыми именами, в том числе .claude/settings.json (metis-0177)
TREE_COPY = {"ditto", "rsync"}
TREE_COPY_FLAG = {"cp": "rRa", "gcp": "rRa", "scp": "r"}
# git clone: опции со значением отдельным словом
CLONE_OPT_ARG = {"-o", "--origin", "-b", "--branch", "-u", "--upload-pack", "--reference", "--reference-if-able",
                 "--separate-git-dir", "--depth", "--shallow-since", "--shallow-exclude", "-c", "--config",
                 "--server-option", "-j", "--jobs", "--template", "--filter", "--bundle-uri", "--ref-format"}


def _repo_or_above(t):
    """Папка — репозиторий (в ней .git или .claude) или папка над репозиториями (такой у неё ребёнок; во временных
    папках детей не смотрим). Дерево, положенное сюда, может принести <репо>/.claude/settings.json или agents."""
    if not os.path.isdir(t):
        return False
    if any(os.path.lexists(os.path.join(t, x)) for x in (".git", ".claude")):
        return True
    if G._inside(t, G.TEMP_ROOTS):
        return False
    try:
        names = sorted(os.listdir(t))[:2000]
    except OSError:
        return False
    return any(os.path.lexists(os.path.join(t, n, x)) for n in names for x in (".git", ".claude"))


def _tree_dests(cmds, cwd, targets):
    """Папки, в которые команда копирует дерево (cp -R, ditto, rsync, scp -r): последний операнд или -t. После cd
    относительный путь не вычислить — тогда все цели-папки."""
    moved = any(n in ("cd", "chdir", "pushd", "popd") for n, _ in cmds)
    out = []
    for name, texts in cmds:
        base = os.path.basename((name or "").rstrip("/"))
        flags = TREE_COPY_FLAG.get(base)
        if base not in TREE_COPY and not (flags and any(
                x and (x in ("--recursive", "--archive") or x[:1] == "-" and x[1:2] != "-" and set(x[1:]) & set(flags))
                for x in texts)):
            continue
        if any(x is None for x in texts):
            continue  # не разобрать — уже UNRESOLVED среди целей
        dest = None
        for i, x in enumerate(texts):
            if x in ("-t", "--target-directory") and i + 1 < len(texts):
                dest = texts[i + 1]
            elif x.startswith("--target-directory="):
                dest = x.split("=", 1)[1]
        ops = [x for x in texts if not x.startswith("-")]
        dest = dest or (ops[-1] if len(ops) > 1 else None)
        if not dest or re.match(r"[^/]*:", dest):
            continue  # нет цели или удалённая (host:path)
        w = dest.replace("${HOME}", G.HOME).replace("$HOME", G.HOME)
        if moved and not os.path.isabs(os.path.expanduser(w)):
            out += [p for p in targets if os.path.isdir(p)]
        else:
            out.append(G._expand(w, cwd))
    return out


def _clone_dests(cmds, cwd):
    """Куда git clone кладёт репозиторий: второй операнд или имя из адреса."""
    out = []
    for name, texts in cmds:
        if os.path.basename((name or "").rstrip("/")) != "git":
            continue
        parsed = G._git_sub(texts)
        if not parsed or parsed[1] != "clone":
            continue
        gdir, _, args = parsed
        ops, skip = [], False
        for x in args:
            if skip:
                skip = False
            elif x is None or not x.startswith("-") or x == "-":
                ops.append(x)
            elif x in CLONE_OPT_ARG:
                skip = True
        if len(ops) < 2 and (not ops or ops[0] is None):
            continue
        dest = ops[1] if len(ops) > 1 else re.sub(r"\.git\Z", "", re.split(r"[/:]", ops[0].rstrip("/"))[-1])
        if dest is None:
            continue
        out.append(G._expand(dest, G._expand(gdir, cwd) if gdir else cwd))
    return out


def check_protect_config(event, tool, tool_input):
    role, sub, pdir = G.who(event)
    if not (G.is_pantheon_role(role) or sub):
        return None  # ваша сессия без роли или ваша собственная роль главной сессии
    if not sub and G.privileged(G.load_policy(), "metis-pantheon", role, pdir):
        return None
    cwd, targets = G.write_targets(event, tool, tool_input)
    if G.UNRESOLVED in targets:
        return G.UNRESOLVED_REASON
    prot = protected()
    mk = tool == "Bash" and bool(MKDIR_ONLY.match(tool_input.get("command") or ""))
    bad = [p for p in targets
           if G._inside(p, prot) or _settings_file(p, mk) or any(G._inside(x, [p]) for x in prot)
           or os.path.basename(p) == G.ANY_FILE and _repo_or_above(os.path.dirname(p))]
    if tool == "Bash":
        cmds = G.bash_analysis(tool_input.get("command") or "", cwd)[1]
        bad += [p for p in _tree_dests(cmds, cwd, targets) if _repo_or_above(p) and p not in bad]
        bad += [p for p in _clone_dests(cmds, cwd) if p not in bad and (
            G._inside(p, prot) or _settings_file(p) or any(G._inside(x, [p]) for x in prot))]
    if not bad:
        return None
    return (f"Правило protect-config: роль «{role or 'субагент'}»{' (субагент)' if sub else ''} не правит защиты "
            f"({', '.join(p.replace(G.HOME, '~') for p in bad[:3])}): хуки, роли (в том числе проекта: <репо>/.claude и .claude/agents), плагины, policy.toml, настройки, "
            "sync.sh и ~/.zshrc меняет только metis-pantheon в своей сессии после «да» владельца. "
            "Дерево в сам репозиторий или выше (tar -C, unzip -d, cp -R, rsync) — тоже защита: распакуй в подпапку "
            "или назови точный файл (cp a.txt <репо>/a.txt). "
            "Нужна правка — опиши её координатору metis-pantheon файлом в ~/ai/pantheon/directions/metis-pantheon/inbox/.")
