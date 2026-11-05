"""protect-config (SEC-14) — часть ядра защит guard (Д3): этот файл, merge_gate.py и managed-settings.json агенты
не сливают — PR ждёт слияния владельцем.

Модуль без своего состояния: общие помощники (HOME, who, privileged, write_targets, _inside, _key…) берутся из
guard_rules.py через G — его присваивает guard_rules.py при загрузке (`protect_config.G = <модуль guard>`). Пути считаются при
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
папку над репозиториями (tar -x, unzip, ditto, cp -R, rsync -r/-a или «папка/», scp -r), и git clone в <репо>/.claude.
Файлы с известными именами (curl -O, wget без -r и -m, patch, rsync одного файла) в корне репозитория — можно.
С metis-0194 закрыты дыры ревью #35: rsync с «.», «папка/.» и -R, wget -r/-m, git checkout/restore поверх .claude, 7z -o.
С metis-0823 неразобранная цель Bash ($(…), переменная, цикл) — отказ, только если команда может задеть защищённое:
идёт в защищённую папку или над ней, называет её или настройки репозитория (unresolved_near). Иначе запись проходит.
"""

import os
import re

G = None  # модуль guard_rules.py: присваивает он сам при загрузке

CLAUDE_ITEMS = ("hooks", "agents", "plugins", "pantheon", "settings.json", "settings.local.json", "sync.sh",
                "statusline.sh", "bootstrap.sh", ".sync-held", ".sync-incoming", ".git", "tools", "CLAUDE.md", "rules",
                "commands", "output-styles")
HOME_ITEMS = (".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bashrc", ".bash_profile", ".profile", ".gitconfig",
              ".config/git", ".ssh", ".claude.json", ".local/share/pantheon", ".local/bin", "Library/LaunchAgents",
              # демон хуков guard (metis-0330): сокет и собранный клиент; plist pantheon.svc.hookd — в Library/LaunchAgents
              ".cache/pantheon/hookd")
SETTINGS_NAMES = {"settings.json", "settings.local.json"}
# <репо>/.claude/<x> в любом репозитории, кроме ~/.claude: как agents (metis-0177). У ~/.claude свой список
# CLAUDE_ITEMS: hooks и commands в нём есть, skills нет — ~/.claude/skills это правило не закрывает
PROJECT_ITEMS = {"hooks", "skills", "commands"}


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
    # запускаются или читаются как инструкции так же (metis-0177); ~/.claude здесь пропускаем — его судит
    # CLAUDE_ITEMS (hooks, commands; skills там нет)
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


# metis-0823: слова, по которым неразобранная цель может быть настройкой репозитория: <репо>/.claude как цель и его
# settings, agents, hooks, skills, commands; .mcp.json; .git/hooks и .git/config. «.claude/worktrees/…» — нет
PROTECTED_WORDS = re.compile(r"\.claude(?:/(?:settings|agents|hooks|skills|commands)|/?(?![\w./-]))|\.mcp\.json|"
                             r"\.git/(?:hooks|config)", re.I)
UNRESOLVED_PROTECTED = (" Отказ — потому что команда идёт в защищённую папку (~/.claude, профили оболочки, ~/.ssh, "
                        "~/.local/bin, LaunchAgents) или папку над ней, либо называет её или настройки репозитория "
                        "(.claude/settings*, agents, hooks, .mcp.json, .git/hooks). Без этого запись с $(…), "
                        "переменной и циклом проходит (metis-0823) — назови точный файл.")


def unresolved_near(cmd, cwd):
    """Может ли неразобранная цель записи быть защищённой (metis-0823): команда идёт в защищённой папке или над ней
    (событие, cd — так `cd ~ && … > $F` судится), называет защищённый путь или настройки репозитория. Путь из
    переменной окружения или собранный по частям — намеренный обход: его граница — песочница окна."""
    return G.near_zones(cmd, cwd, protected()) or bool(PROTECTED_WORDS.search(cmd.replace("\\", "")))


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


def _recursive(texts, flags):
    """Есть флаг рекурсии: --recursive, --archive или короткий набор с одной из букв flags (-R, -a, -av)."""
    return any(x and (x in ("--recursive", "--archive") or x[:1] == "-" and x[1:2] != "-" and set(x[1:]) & set(flags))
               for x in texts)


def _moved(cmds):
    return any(n in ("cd", "chdir", "pushd", "popd") for n, _ in cmds)


def _cd_dirs(cmds, cwd):
    """Папки, где может идти команда: папка события и цель каждого cd/chdir/pushd (относительная — от всех уже
    известных: `cd app && cd ..`; без аргумента — HOME). Объединение, как у разбора Bash, а не порядок: для команд,
    чьих целей разбор Bash не знает (7z), metis-0194. Неразобранная цель (`cd "$X"`) пропущена."""
    out = [cwd]
    for n, t in cmds:
        if n not in ("cd", "chdir", "pushd"):
            continue
        arg = next((x for x in t if x is None or not x.startswith("-") or x == "-"), "$HOME")
        if arg is None or arg == "-":
            continue  # `cd -` — прошлая папка, она уже в списке
        out += [p for p in (G._expand(arg, d) for d in list(out)) if p not in out]
    return out


def _tree_dests(cmds, cwd, targets):
    """Папки, в которые команда копирует дерево (cp -R, ditto, rsync -r/-a или источник «папка/», scp -r): последний
    операнд или -t. rsync без рекурсии и без «/» в конце источника кладёт отдельные файлы — это не дерево. После cd
    относительный путь не вычислить — тогда все цели-папки."""
    moved = _moved(cmds)
    out = []
    for name, texts in cmds:
        base = os.path.basename((name or "").rstrip("/"))
        flags = TREE_COPY_FLAG.get(base)
        if base not in TREE_COPY and not (flags and _recursive(texts, flags)):
            continue
        if any(x is None for x in texts):
            continue  # не разобрать — уже UNRESOLVED среди целей
        dest = None
        for i, x in enumerate(texts):
            if x in ("-t", "--target-directory") and i + 1 < len(texts):
                dest = texts[i + 1]
            elif x.startswith("--target-directory="):
                dest = x.split("=", 1)[1]
        ops = _rsync_operands(texts) if base == "rsync" else [x for x in texts if not x.startswith("-")]
        if base == "rsync" and not _rsync_tree(texts) and not any(
                _dir_src(x) for x in (ops if dest else ops[:-1])):
            continue  # rsync a.txt . — отдельный файл, а не дерево
        dest = dest or (ops[-1] if len(ops) > 1 else None)
        if not dest or re.match(r"[^/]*:", dest):
            continue  # нет цели или удалённая (host:path)
        w = dest.replace("${HOME}", G.HOME).replace("$HOME", G.HOME)
        if moved and not os.path.isabs(os.path.expanduser(w)):
            out += [p for p in targets if os.path.isdir(p)]
        else:
            out.append(G._expand(w, cwd))
    return out


# rsync: опции со значением отдельным словом — их значение не операнд (`rsync -a src/ . --exclude x`: папка — «.», metis-0194)
RSYNC_VALUE_OPTS = {"--exclude", "--include", "--filter", "-f", "--exclude-from", "--include-from", "--files-from",
                    "--log-file", "-e", "--rsh", "--rsync-path", "--port", "--timeout", "--contimeout", "--partial-dir",
                    "--temp-dir", "-T", "--compare-dest", "--copy-dest", "--link-dest", "--backup-dir", "--suffix",
                    "--chmod", "--chown", "--info", "--debug", "--max-size", "--min-size", "--bwlimit", "--out-format",
                    "--password-file", "--address", "--sockopts", "--modify-window", "-B", "--block-size", "--iconv",
                    "--usermap", "--groupmap", "--checksum-choice", "--cc", "--skip-compress", "--outbuf"}


def _rsync_operands(texts):
    out, skip = [], False
    for x in texts:
        if skip:
            skip = False
        elif x in RSYNC_VALUE_OPTS:
            skip = True
        elif not x.startswith("-"):
            out.append(x)
    return out


def _rsync_tree(texts):
    """rsync копирует дерево: рекурсия (-r, -a), относительные пути (-R, --relative, --files-from — они подразумевают -R:
    `rsync -R .claude/settings.json .` кладёт .claude/ в корень, metis-0194)."""
    return _recursive(texts, "raR") or any(x == "--relative" or x.startswith("--files-from") for x in texts)


def _dir_src(x):
    """Источник — папка: «.», «..», «папка/», «папка/.» или «папка/..» (без рекурсии rsync -d/--dirs кладёт её
    содержимое — судим как дерево)."""
    return x in (".", "..") or x.endswith(("/", "/.", "/.."))


def _opt_dests(texts, short, long=()):
    """Значения опции: «-C X», «-CX», «--directory X», «--directory=X»."""
    out = []
    for i, x in enumerate(texts):
        if x in (short,) + tuple(long) and i + 1 < len(texts):
            out.append(texts[i + 1])
        elif x.startswith(short) and len(x) > len(short) and not x.startswith("--"):
            out.append(x[len(short):])
        else:
            out += [x.split("=", 1)[1] for n in long if x.startswith(n + "=")]
    return out


def _unpack_dests(cmds, cwd, targets):
    """Папки, в которые распаковщик кладёт дерево с любыми именами: tar -x (-C, --directory), unzip (-d), ditto -x
    (последний операнд); без папки — cwd. Только они закрывают репозиторий и папку над ним целиком: curl -O, wget,
    patch, rsync одного файла кладут файлы с известными именами, их судят обычные правила (metis-0177)."""
    moved = _moved(cmds)
    out = []
    for name, texts in cmds:
        base = os.path.basename((name or "").rstrip("/"))
        if any(x is None for x in texts):
            continue  # не разобрать — уже UNRESOLVED среди целей
        if base in ("tar", "gtar", "bsdtar"):
            first = texts[0] if texts else ""
            modes = set(first) if first and not first.startswith("-") else set()
            for x in texts:
                if x.startswith("-") and not x.startswith("--"):
                    modes |= set(x[1:])
            if "x" not in modes and not {"--extract", "--get"} & set(texts):
                continue
            dests = _opt_dests(texts, "-C", ("--directory",)) or ["."]
        elif base == "unzip":
            if _unzip_lists(texts):
                continue  # unzip -l/-t/-Z/-v/-p — только список, проверка или вывод в stdout: файлов нет
            dests = _opt_dests(texts, "-d") or ["."]
        elif base in SEVEN_ZIP and next((x for x in texts if not x.startswith("-")), None) in ("x", "e"):
            dests = _opt_dests(texts, "-o") or ["."]  # 7z x a.7z -o<папка>; без -o — cwd (metis-0194)
            if moved:  # разбор Bash 7z не знает — целей «…» нет: относительную папку судим от каждой папки cd
                for d in dests:
                    w = d.replace("${HOME}", G.HOME).replace("$HOME", G.HOME)
                    out += [G._expand(w, c) for c in _cd_dirs(cmds, cwd)]
                continue
        elif base == "ditto" and any(x[:1] == "-" and x[1:2] != "-" and "x" in x for x in texts):
            ops = [x for x in texts if not x.startswith("-")]
            dests = ops[-1:] if len(ops) > 1 else []
        else:
            continue
        for d in dests:
            w = d.replace("${HOME}", G.HOME).replace("$HOME", G.HOME)
            if moved and not os.path.isabs(os.path.expanduser(w)):
                out += [os.path.dirname(p) for p in targets if os.path.basename(p) == G.ANY_FILE]
            else:
                out.append(G._expand(w, cwd))
    return out


SEVEN_ZIP = ("7z", "7za", "7zz", "7zr")


def _unzip_lists(texts):
    """unzip с буквой -l, -t, -Z, -v или -p: список, проверка или вывод в stdout — файлы не пишутся. Значение -d
    (слитно «-dПАПКА» или отдельным словом) не считается буквами."""
    letters = set()
    for x in texts:
        if x.startswith("-") and not x.startswith("--") and not x.startswith("-d"):
            letters |= set(x[1:])
    return bool(letters & set("ltZvp"))


def _mirror_dests(cmds, cwd, targets):
    """wget -r / -m (--mirror): сайт кладёт дерево с путями из адреса (…/.claude/settings.json → ./.claude/…; с -nH
    без папки хоста). Папка — -P или cwd (metis-0194). Одиночная загрузка (curl -O, wget без -r) — файл с известным
    именем, её судят обычные правила."""
    moved = _moved(cmds)
    out = []
    for name, texts in cmds:
        if os.path.basename((name or "").rstrip("/")) != "wget" or any(x is None for x in texts):
            continue
        if not (_recursive(texts, "rm") or "--mirror" in texts):
            continue
        for d in _opt_dests(texts, "-P", ("--directory-prefix",)) or ["."]:
            w = d.replace("${HOME}", G.HOME).replace("$HOME", G.HOME)
            if moved and not os.path.isabs(os.path.expanduser(w)):
                # цель wget у разбора Bash — «<папка>/…» от каждой папки cd (metis-0194)
                out += [os.path.dirname(p) for p in targets if os.path.basename(p) == G.ANY_FILE]
            else:
                out.append(G._expand(w, cwd))
    return out


def _git_targets(cmds, cwd):
    """git checkout и git restore переписывают пути в рабочей копии из индекса или коммита: `git checkout -- .claude/…`
    поверх защищённого файла (metis-0194). Операнды — пути (и имена веток: лишняя проверка безвредна). Только
    --staged меняет индекс, а не рабочую копию, — его не судим. `.` и папка репозитория — можно (решение лида по
    ревью #204): возвращают только то, что уже в git, как reset --hard и checkout ветки."""
    out = []
    for name, texts in cmds:
        if os.path.basename((name or "").rstrip("/")) != "git" or any(x is None for x in texts):
            continue
        parsed = G._git_sub(texts)
        if not parsed or parsed[1] not in ("checkout", "restore"):
            continue
        gdir, sub, args = parsed
        if sub == "restore" and ("--staged" in args or "-S" in args) and not ("--worktree" in args or "-W" in args):
            continue
        base = G._expand(gdir, cwd) if gdir else cwd
        out += [G._expand(x, base) for x in args if x != "--" and not x.startswith("-")]
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
    # metis-0823: неразобранная цель — отказ, только если команда может задеть защищённое (unresolved_near); запись с
    # $(…), циклом или переменной в $TMPDIR, кэш окна и свою worktree проходит
    if G.UNRESOLVED in targets and (tool != "Bash" or unresolved_near(tool_input.get("command") or "", cwd)):
        return G.UNRESOLVED_REASON + UNRESOLVED_PROTECTED
    targets = [p for p in targets if p != G.UNRESOLVED]
    prot = protected()
    mk = tool == "Bash" and bool(MKDIR_ONLY.match(tool_input.get("command") or ""))
    bad = [p for p in targets
           if G._inside(p, prot) or _settings_file(p, mk) or any(G._inside(x, [p]) for x in prot)]
    if tool == "Bash":
        cmds = G.bash_analysis(tool_input.get("command") or "", cwd)[1]
        bad += [p for p in _tree_dests(cmds, cwd, targets) if _repo_or_above(p) and p not in bad]
        # распаковка и зеркало кладут дерево и в саму папку .claude (7z x -o<репо>/.claude, metis-0194)
        bad += [p for p in _unpack_dests(cmds, cwd, targets) + _mirror_dests(cmds, cwd, targets) if p not in bad and (
            _repo_or_above(p) or _settings_file(p) or G._inside(p, prot))]
        bad += [p for p in _git_targets(cmds, cwd) if p not in bad and (
            G._inside(p, prot) or _settings_file(p) or any(G._inside(x, [p]) for x in prot))]
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
