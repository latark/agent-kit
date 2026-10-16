"""protect-config (SEC-14) — часть ядра защит guard (Д3): этот файл, merge_gate.py и managed-settings.json агенты
не сливают, только кнопка владельца.

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
в любом репозитории — .claude/settings*.json, .mcp.json, .git/hooks и .git/config.
"""

import os

G = None  # модуль guard.py: присваивает guard.py при загрузке

CLAUDE_ITEMS = ("hooks", "agents", "plugins", "pantheon", "settings.json", "settings.local.json", "sync.sh",
                "statusline.sh", "bootstrap.sh", ".sync-held", ".sync-incoming", ".git", "tools", "CLAUDE.md", "rules",
                "commands", "output-styles")
HOME_ITEMS = (".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bashrc", ".bash_profile", ".profile", ".gitconfig",
              ".config/git", ".ssh", ".claude.json", ".local/share/pantheon", ".local/bin", "Library/LaunchAgents")
SETTINGS_NAMES = {"settings.json", "settings.local.json"}


def protected():
    """Защищённые пути (realpath) для текущего HOME."""
    home = G.HOME
    return ([os.path.realpath(os.path.join(home, ".claude", x)) for x in CLAUDE_ITEMS] +
            [os.path.realpath(os.path.join(home, x)) for x in HOME_ITEMS])


def _settings_file(p):
    """Настройки, которые меняют разрешения, хуки или запускают код в любом репозитории: .claude/settings*.json,
    .claude/agents/ (роли проекта), .mcp.json, .git/hooks/… и .git/config."""
    key = G._key
    parent, base = os.path.split(p)
    if key(base) in SETTINGS_NAMES and key(os.path.basename(parent)) == ".claude":
        return True
    if key(base) == ".mcp.json":
        return True
    parts = [key(x) for x in p.split("/")]
    # роли проекта: `<репо>/.claude/agents/<имя>.md` перекрывает пользовательскую роль (metis-0057), в том числе
    # в worktree `.claude/worktrees/<x>/.claude/agents/`; сама папка тоже (mkdir)
    for i, x in enumerate(parts[:-1]):
        if x == ".claude" and parts[i + 1] == "agents":
            return True
    for i, x in enumerate(parts[:-1]):
        if x == ".git" and (parts[i + 1] == "hooks" or (parts[i + 1] == "config" and i + 2 == len(parts))):
            return True
    return False


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
    bad = [p for p in targets
           if G._inside(p, prot) or _settings_file(p) or any(G._inside(x, [p]) for x in prot)]
    if not bad:
        return None
    return (f"Правило protect-config: роль «{role or 'субагент'}»{' (субагент)' if sub else ''} не правит защиты "
            f"({', '.join(p.replace(G.HOME, '~') for p in bad[:3])}): хуки, роли (в том числе проекта: <репо>/.claude/agents), плагины, policy.toml, настройки, "
            "sync.sh и ~/.zshrc меняет только metis-pantheon в своей сессии после «да» владельца. "
            "Нужна правка — опиши её координатору metis-pantheon файлом в ~/ai/pantheon/directions/metis-pantheon/inbox/.")
