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
С metis-0823 неразобранная цель Bash ($(…), переменная) проходит, только если её буквальная часть лежит в $TMPDIR,
кэше окна или своей worktree (G.unresolved_dirs); эта папка судится как обычная цель. Папка-основа .git и папка
с настройками репозитория (корень, вложенный проект) — отказ: имя из подстановки может оказаться config, .mcp.json
(_unres_risky).
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

# metis-0841 («да» владельца 05.11 16:04 и 16:09): координатор и лид направления правят навыки, команды и роли
# проекта в папках своего направления (domains.json, его собирают из directions.toml). Отказ, если новый текст даёт
# права или запускает код без вопроса: ключи frontmatter ниже (без регистра, «-» и «_») или строка `!`команда``
# (её выполняют при загрузке навыка). Текст записи не разобрать — тоже отказ. .claude/hooks, settings, .mcp.json,
# .git и сама .claude как цель — защита и в своём направлении
OWN_ITEMS = {"skills", "commands", "agents"}
RISKY_KEYS = {"skills": {"allowedtools", "hooks", "model", "context"},
              "commands": {"allowedtools", "hooks", "model", "context"},
              "agents": {"tools", "disallowedtools", "permissionmode", "hooks", "mcpservers"}}
DYN_COMMAND = re.compile(r"!\s*`")
# ключ YAML в строке frontmatter: в начале строки (и пункта «- »), после «{» или «,»; в кавычках тоже
FM_KEY = re.compile(r"""(?:^|[{,])\s*(?:-\s+)?["']?([A-Za-z_][\w-]*)["']?\s*:""")
TEXT_LIMIT = 1 << 20  # больше — текст не разбираем, отказ


def own_folders(role, sub, pdir):
    """Папки направления, где роль правит skills, commands и agents проекта: координатор (главная сессия
    domain-coordinator) и лид направления (hephaestus-<коротко>, apollo-<коротко> — главная сессия или субагент окна).
    Направление — по папке запуска (domains.json). Иначе []: остальные роли, субагенты и чужое направление."""
    name, folders = G.direction_of(G.load_domains(), pdir)
    if not name or not folders:
        return []
    if role == "domain-coordinator" and not sub:
        return folders
    short = name.split("-", 1)[1] if "-" in name else ""
    return folders if short and role in {p + short for p in G.PANTHEON_ROLE_PREFIXES} else []


def _own_kinds(p, own):
    """Какие из OWN_ITEMS своего направления содержат путь (их ключи frontmatter судим)."""
    parts = [G._key(x) for x in p.split("/")]
    return {parts[i + 1] for i, x in enumerate(parts[:-1])
            if x == ".claude" and parts[i + 1] in OWN_ITEMS and G._inside("/".join(parts[:i + 1]), own)}


def _read_text(p):
    """Текст обычного файла (не больше TEXT_LIMIT); нет файла — ""; иначе None (не разобрать)."""
    if not os.path.lexists(p):
        return ""
    try:
        if not os.path.isfile(p) or os.path.getsize(p) > TEXT_LIMIT:
            return None
        with open(p, "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return None


def _edit_text(tool, tool_input, p):
    """Новый текст файла после Write, Edit, MultiEdit; None — не вычислить (NotebookEdit, нет old_string)."""
    if tool == "Write":
        c = tool_input.get("content")
        return c if isinstance(c, str) else None
    if tool == "Edit":
        edits = [tool_input]
    elif tool == "MultiEdit":
        edits = tool_input.get("edits")
        if not isinstance(edits, list) or not edits:
            return None
    else:
        return None
    text = _read_text(p)
    if text is None:
        return None
    for e in edits:
        old, new = (e.get("old_string"), e.get("new_string")) if isinstance(e, dict) else (None, None)
        if not isinstance(old, str) or not isinstance(new, str):
            return None
        if old == "":
            if text:
                return None
            text = new  # Edit с пустым old_string создаёт файл
        elif old not in text:
            return None
        else:
            text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
    return text


def _bash_texts(cmd, cwd, paths):
    """Новый текст каждого пути из paths после команды Bash: {путь: текст или None — файла не будет (rm, mkdir)}.
    Разбираются только простые формы одной командой: `cat > файл <<'EOF'` (и >>), `cp|mv [-fnvpi] файл цель`,
    `rm`, `rmdir`, `mkdir`; остальное (sed -i, tee, цепочки, подстановки) — None: текст не разобрать, отказ."""
    if MKDIR_ONLY.match(cmd):
        return {p: None for p in paths}
    try:
        lex = G._Lexer(cmd)
        lex.run()
    except (G._ParseError, RecursionError, ValueError):
        return None
    toks = list(lex.toks)
    while toks and toks[-1] == "\n":
        toks.pop()
    if lex.danger or any(isinstance(t, str) for t in toks):
        return None
    cmds = G.bash_analysis(cmd, cwd)[1]
    if len(cmds) != 1 or any(x is None for x in cmds[0][1]):
        return None
    name, args = cmds[0]
    words, redirs, k = [], [], 0
    while k < len(toks):
        t = toks[k]
        if isinstance(t, G._Redir):
            w = toks[k + 1] if k + 1 < len(toks) and isinstance(toks[k + 1], G._Word) else None
            redirs.append((t, w))
            k += 2 if w else 1
        else:
            words.append(t)
            k += 1
    if not words or words[0].bare() != name or len(words) != len(args) + 1:
        return None  # обёртка (command cat, env) или слово, которого разбор не отдал
    if name in ("rm", "rmdir") and not redirs:
        return {p: None for p in paths}
    if name in ("cp", "mv") and not redirs:
        flags = [x for x in args if x.startswith("-")]
        ops = [x for x in args if not x.startswith("-")]
        if len(ops) != 2 or not all(re.fullmatch(r"-[fnvpi]+", x) for x in flags):
            return None
        src = G._expand(ops[0], cwd)
        # _expand даёт realpath — ссылку смотрим по пути до раскрытия последнего звена
        raw = os.path.join(cwd, os.path.expanduser(ops[0].replace("${HOME}", G.HOME).replace("$HOME", G.HOME)))
        if name == "mv" and os.path.islink(raw.rstrip("/")):
            return None  # ссылка переедет ссылкой: текст потом поменяют мимо проверки
        text = _read_text(src) if os.path.isfile(src) else None
        return None if text is None else {p: text for p in paths}
    if name == "cat" and args in ([], ["-"]):
        docs = [(r, w) for r, w in redirs if r.op in ("<<", "<<-")]
        outs = [(r, w) for r, w in redirs if r.op in (">", ">|", ">!", ">>")]
        if len(docs) != 1 or len(outs) != 1 or len(redirs) != 2 or len(paths) != 1 or docs[0][1] is None:
            return None
        body = docs[0][0].body or ""
        if docs[0][1].bare() is not None and re.search(r"[$`\\]", body):
            return None  # ограничитель без кавычек: оболочка раскроет $…, `…` и \ — текст другой
        text = body + "\n"
        if outs[0][0].op == ">>":
            old = _read_text(paths[0])
            if old is None:
                return None
            text = old + text
        return {paths[0]: text}
    return None


def _text_risk(text, kinds):
    """Что в тексте даёт права или запускает код: ключ frontmatter из RISKY_KEYS или `!`команда``; иначе None.
    Frontmatter — от первой непустой строки «---» до строки «---» или «...»; без конца — весь текст."""
    m = DYN_COMMAND.search(text)
    if m:
        return "строка динамической команды !`…` (её выполняют при загрузке навыка)"
    lines = text.lstrip(chr(0xFEFF)).splitlines()
    i = next((n for n, x in enumerate(lines) if x.strip()), len(lines))
    if i >= len(lines) or lines[i].strip() != "---":
        return None
    risky = set().union(*(RISKY_KEYS[k] for k in kinds))
    for line in lines[i + 1:]:
        if line.strip() in ("---", "..."):
            break
        for key in FM_KEY.findall(line):
            if re.sub(r"[-_]", "", key.lower()) in risky:
                return f"во frontmatter ключ «{key}» (права или запуск кода без вопроса)"
    return None


def own_text_problem(event, tool, tool_input, paths, own):
    """Почему запись в навыки, команды и роли своего проекта нельзя: (путь, причина) или None."""
    cwd = os.path.realpath(event.get("cwd") or os.getcwd())
    if tool == "Bash":
        texts = _bash_texts(tool_input.get("command") or "", cwd, paths)
        if texts is None:
            return paths[0], ("текст записи через Bash не разобрать — запиши файл через Write или Edit "
                              "(или `cat > файл <<'EOF'`)")
    else:
        texts = {p: _edit_text(tool, tool_input, p) for p in paths}
        bad = next((p for p in paths if texts[p] is None), None)
        if bad:
            return bad, "новый текст файла не вычислить (NotebookEdit или old_string не найден)"
    for p in paths:
        why = texts.get(p) and _text_risk(texts[p], _own_kinds(p, own) or OWN_ITEMS)
        if why:
            return p, why
    return None


def protected():
    """Защищённые пути (realpath) для текущего HOME."""
    home = G.HOME
    return ([os.path.realpath(os.path.join(home, ".claude", x)) for x in CLAUDE_ITEMS] +
            [os.path.realpath(os.path.join(home, x)) for x in HOME_ITEMS])


def _settings_file(p, mkdir_only=False, own=()):
    """Настройки, которые меняют разрешения, хуки или запускают код в любом репозитории: .claude/settings*.json,
    .claude/agents/ (роли проекта), сама папка .claude (цель записи, чьё последнее звено — .claude), .mcp.json,
    .git/hooks/… и .git/config. Внутри .claude остальное (worktrees/…) не защищено этим правилом.
    own — папки своего направления (metis-0841, own_folders): в них .claude/skills, commands и agents проекта не
    считаются защитой — их текст судит own_text_problem; .claude/hooks, settings и всё прочее — как без own."""
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
            here = "/".join(parts[:i + 1])
            if own and parts[i + 1] in OWN_ITEMS and here != home_claude and G._inside(here, own):
                continue  # своё направление: навык, команда или роль проекта — дальше судит текст
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


# metis-0823: слова настроек репозитория в слове неразобранной цели (без подстановок) — отказ: <репо>/.claude как
# цель и его settings, agents, hooks, skills, commands; .mcp.json; .git/hooks и .git/config. «.claude/worktrees/…» — нет
PROTECTED_WORDS = re.compile(r"\.claude(?:/(?:settings|agents|hooks|skills|commands)|/?(?![\w./-]))|\.mcp\.json|"
                             r"\.git/(?:hooks|config)", re.I)


def _unres_risky(d):
    """metis-0823 (Б2 ревью #330): неразобранное имя в папке d может стать защищённым файлом прямо в ней —
    `.git/$(echo config)`, `./$(echo .mcp.json)`. Такая папка: .git или папка, где прямо лежат настройки репозитория
    (.git, .claude, .mcp.json: корень репозитория, вложенный проект). Подпапки worktree (out/, src/), $TMPDIR и кэш
    окна — нет. Папку, где прямо лежит путь из protected() (~/.claude, ~), unresolved_dirs уже не пускает: корни,
    над зонами, он отбрасывает."""
    if G._key(os.path.basename(d)) == ".git":
        return True
    return any(os.path.lexists(os.path.join(d, x)) for x in (".git", ".claude", ".mcp.json"))


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
    # metis-0823: неразобранная цель проходит, только если её папка в $TMPDIR, кэше окна или своей worktree —
    # и эту папку судят как обычную цель
    dirs = G.unresolved_dirs(event, tool, tool_input, protected(), PROTECTED_WORDS) if G.UNRESOLVED in targets else []
    if dirs is None:
        return G.UNRESOLVED_REASON + G.UNRESOLVED_SAFE
    if any(_unres_risky(d) for d in dirs):
        return (G.UNRESOLVED_REASON + G.UNRESOLVED_SAFE + " Корень репозитория, .git и папка с защитами — тоже отказ: "
                "имя из подстановки может оказаться .mcp.json или config. Пиши в подпапку (`out/$f`) или в $TMPDIR.")
    targets = [p for p in targets if p != G.UNRESOLVED] + dirs
    prot = protected()
    mk = tool == "Bash" and bool(MKDIR_ONLY.match(tool_input.get("command") or ""))
    bad = [p for p in targets
           if G._inside(p, prot) or _settings_file(p, mk) or any(G._inside(x, [p]) for x in prot)]
    # metis-0841: навыки, команды и роли проекта в папках своего направления — координатору и лиду, если текст
    # не даёт прав и не запускает код (own_text_problem). Копии дерева, распаковка, git checkout и clone ниже судят
    # без этого исключения: их текста не видно
    own = own_folders(role, sub, pdir) if bad else []
    opened = [p for p in bad if own and not G._inside(p, prot) and not any(G._inside(x, [p]) for x in prot)
              and not _settings_file(p, mk, own)]
    bad = [p for p in bad if p not in opened]
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
    if not bad and opened:
        problem = own_text_problem(event, tool, tool_input, opened, own)
        if problem:
            return (f"Правило protect-config: роль «{role}» правит навыки, команды и роли своего проекта, но не то, что "
                    f"даёт права или запускает код без вопроса: {problem[0].replace(G.HOME, '~')} — {problem[1]}. "
                    "allowed-tools, hooks, model, context у навыка и команды, tools, disallowedTools, permissionMode, "
                    "hooks, mcpServers у роли и строки !`…` правит только metis-pantheon после «да» владельца — опиши "
                    "правку файлом в ~/ai/pantheon/directions/metis-pantheon/inbox/.")
        return None
    if not bad:
        return None
    return (f"Правило protect-config: роль «{role or 'субагент'}»{' (субагент)' if sub else ''} не правит защиты "
            f"({', '.join(p.replace(G.HOME, '~') for p in bad[:3])}): хуки, роли (в том числе проекта: <репо>/.claude и .claude/agents), плагины, policy.toml, настройки, "
            "sync.sh и ~/.zshrc меняет только metis-pantheon в своей сессии после «да» владельца. "
            "Дерево в сам репозиторий или выше (tar -C, unzip -d, cp -R, rsync) — тоже защита: распакуй в подпапку "
            "или назови точный файл (cp a.txt <репо>/a.txt). "
            "Нужна правка — опиши её координатору metis-pantheon файлом в ~/ai/pantheon/directions/metis-pantheon/inbox/.")
