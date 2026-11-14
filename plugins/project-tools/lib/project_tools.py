#!/usr/bin/env python3
"""project-tools — инструменты проекта по карте стеков (TOOL-07, MEM-04).

Карта ../stacks.json: признак в проекте (зависимость в package.json, pyproject.toml или
requirements*.txt, либо файл) → какие MCP-серверы и плагины нужны.
Команды:
  project-tools check [--dir D] [--json] [--no-net] [--probe]
                                                   что подключить или поправить; ничего не меняет (--json: только
                                                   стеки и не подключённые инструменты, для pantheon direction check).
                                                   Раздел «Серверы MCP»: HTTP-серверы .mcp.json, одобренные вами, —
                                                   initialize и tools/list (lib/mcp_probe.py); stdio не запускает, ключей
                                                   не шлёт; OAuth — «не проверен — нужен вход». --no-net — без сети;
                                                   --json проверяет сеть только с --probe (поле servers). Код выхода
                                                   проверка сети не меняет
  project-tools apply [--dir D] [--update ИМЯ]… [--accept ИМЯ]…
                                                   записать .mcp.json, одобрения, плагины, блок Codex
  project-tools skip ИМЯ… [--dir D]                ваше «не надо»: отказ от сервера или плагина, подсказка замолкает
  project-tools hint                               хук SessionStart: строка в контекст, если чего-то нет или
                                                   одобренный сервер изменился
  project-tools outdated                           закреплённые версии против свежих в npm
  project-tools map                                карта стеков

Добавляет только записи из карты рядом с этим файлом: другой карты команда не принимает, поэтому произвольный
сервер через неё не подключить. В окнах ролей запись в .mcp.json и .claude/settings*.json запрещают песочница Claude Code
(protected paths) и guard (SEC-14): там роль запускает только check и спрашивает владельца.

Куда пишет apply (корень проекта — вершина git-репозитория, иначе папка):
  .mcp.json                     серверы из карты; чужие записи не трогает, отличие от карты меняет только --update
  .claude/settings.json         enabledMcpjsonServers: серверы из карты поимённо — тогда Claude не спрашивает одобрения;
                                файл общий и идёт в тот же PR, что .mcp.json: после слияния сервер одобрен в окне роли
                                и на другом Mac без ручного шага (решение владельца 14.11, metis-1047). Имена, которых
                                в .mcp.json нет, снимает. enableAllProjectMcpServers здесь не ставит.
                                enabledPlugins: плагины из карты; плагины, которые заменяет сервер из карты, — false
  .claude/settings.local.json   личный, только чистится: enableAllProjectMcpServers заменяет списком серверов, которые
                                уже лежат в .mcp.json (их вы одобрили этим флагом), — новый сервер из репозитория без
                                вопроса больше не запустится; снимает одобрения имён, которых в .mcp.json нет
  .codex/config.toml            блок [mcp_servers.*], если Codex установлен или папка .codex уже есть

Одобрение в Claude Code — по имени сервера: после git pull под тем же именем может прийти другая команда, и она
запустится без вопроса. Общее одобрение в .claude/settings.json это не меняет: сторож — отпечатки. Поэтому apply запоминает отпечаток каждой одобренной записи (на этом Mac, вне репозитория),
а подсказка при старте сессии говорит вам и Claude, если запись изменилась. Принять — apply --accept ИМЯ,
отказаться — skip ИМЯ.
"""
import argparse
import fnmatch
import json
import os
import pwd
import re
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from collections import deque

if sys.version_info < (3, 11):  # обёртка bin/project-tools ищет 3.11+; сюда попадает только прямой запуск
    sys.exit(0 if sys.argv[1:2] == ["hint"] else "project-tools: нужен Python 3.11 или новее (tomllib)")
import tomllib

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # -I не кладёт папку скрипта в sys.path
import mcp_probe  # noqa: E402 — после проверки версии и пути

PLUGIN = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MAP = os.path.join(PLUGIN, "stacks.json")
HOME = os.path.realpath(os.path.expanduser("~"))
REAL_HOME = os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)  # подмена $HOME не делает домашнюю папку проектом
LOG = os.path.join(HOME, ".local", "state", "pantheon", "logs", "project-tools.log")
APPROVED = os.path.join(HOME, ".local", "state", "pantheon", "project-tools", "approved.json")
SKIP_DIRS = {"node_modules", "dist", "build", "out", "coverage", "vendor", "venv", "env", "__pycache__", "target",
             "Pods", "DerivedData"}
SCAN_DEPTH, SCAN_LIMIT = 3, 400
CODEX_BEGIN = "# >>> project-tools (agent-kit): блок пишет `project-tools apply`, руками не править"
CODEX_END = "# <<< project-tools"


class Broken(Exception):
    """Файл настроек не читается или стоит не там: apply не пишет ничего."""


class PartlyWritten(Broken):
    """Запись оборвалась на середине: в сообщении — что уже записано."""


def short(path):
    return path.replace(HOME, "~", 1) if path.startswith(HOME) else path


def read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def read_json(path):
    text = read_text(path)
    if text is None or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as e:
        raise Broken(f"{short(path)}: не JSON ({e})")
    if not isinstance(data, dict):
        raise Broken(f"{short(path)}: ожидался объект JSON")
    return data


def load_map():
    with open(MAP, encoding="utf-8") as fh:
        return json.load(fh)


def project_root(start):
    """Вершина git-репозитория, иначе сама папка; второе значение — есть ли git."""
    start = os.path.realpath(start)
    try:
        r = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                           timeout=5)
        top = r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        top = ""
    return (os.path.realpath(top), True) if top else (start, False)


def package_deps(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    deps = {}
    for key in ("dependencies", "devDependencies"):
        if isinstance(data.get(key), dict):
            deps.update(data[key])
    return deps


def py_name(name):
    """Имя Python-пакета по PEP 503: регистр, «_», «.» и «-» не различаются."""
    return re.sub(r"[-_.]+", "-", name).lower()


def req_name(line):
    """Имя пакета из строки требования («supabase[x]>=2; python_version>"3.9"»); None — не требование."""
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
    return py_name(m.group(1)) if m else None


def pyproject_deps(path):
    """Имена зависимостей из pyproject.toml: [project].dependencies и optional-dependencies, [dependency-groups]
    (строки; вложенные {include-group} пропускаются), [tool.poetry.dependencies] и группы poetry."""
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, ValueError):
        return set()
    out = set()

    def take(items):
        for it in items if isinstance(items, list) else []:
            if isinstance(it, str) and req_name(it):
                out.add(req_name(it))

    proj = data.get("project") if isinstance(data.get("project"), dict) else {}
    take(proj.get("dependencies"))
    for group in (proj.get("optional-dependencies") or {}).values() if isinstance(
            proj.get("optional-dependencies"), dict) else []:
        take(group)
    groups = data.get("dependency-groups")
    for group in groups.values() if isinstance(groups, dict) else []:
        take(group)
    poetry = (data.get("tool") or {}).get("poetry") if isinstance(data.get("tool"), dict) else None
    poetry = poetry if isinstance(poetry, dict) else {}
    tables = [poetry.get("dependencies"), poetry.get("dev-dependencies")]
    for g in (poetry.get("group") or {}).values() if isinstance(poetry.get("group"), dict) else []:
        tables.append(g.get("dependencies") if isinstance(g, dict) else None)
    for t in tables:
        if isinstance(t, dict):
            out |= {py_name(k) for k in t if k.lower() != "python"}
    return out


def requirements_deps(path):
    """Имена пакетов из requirements*.txt (без -r/-e/--флагов и комментариев)."""
    text = read_text_quiet(path)
    return {n for n in (req_name(line) for line in text.splitlines()) if n}


def read_text_quiet(path):
    try:
        return read_text(path) or ""
    except (OSError, ValueError):
        return ""


def scan(root):
    """Зависимости из всех package.json, pyproject.toml и requirements*.txt и имена файлов до SCAN_DEPTH уровней
    вглубь (монорепозитории: apps/*, packages/*). Скрытые папки, node_modules и сборки пропускает.
    → ({зависимость: [(версия, папка)]}, {файлы}, {имя Python-пакета})."""
    deps, files, pydeps = {}, set(), set()
    queue, seen = deque([(root, 0)]), 0
    while queue and seen < SCAN_LIMIT:
        folder, level = queue.popleft()
        seen += 1
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_file(follow_symlinks=False):
                    files.add(e.name)
                    if e.name == "package.json":
                        for name, spec in package_deps(e.path).items():
                            deps.setdefault(name, []).append((str(spec), folder))
                    elif e.name == "pyproject.toml":
                        pydeps |= pyproject_deps(e.path)
                    elif re.fullmatch(r"requirements[\w.-]*\.txt", e.name):
                        pydeps |= requirements_deps(e.path)
                elif (e.is_dir(follow_symlinks=False) and level < SCAN_DEPTH and not e.name.startswith(".")
                      and e.name not in SKIP_DIRS):
                    queue.append((e.path, level + 1))
            except OSError:
                continue
    return deps, files, pydeps


def major(spec, folder, name, root):
    """Старшая версия зависимости: из записи в package.json, иначе (workspace:, catalog:, latest) — из
    установленного пакета; None — не узнать."""
    m = re.match(r"^\s*(?:npm:[^@\s]+@)?[\^~>=<v\s]*(\d+)", spec)
    if m:
        return int(m.group(1))
    for base in (folder, root):
        try:
            with open(os.path.join(base, "node_modules", name, "package.json"), encoding="utf-8") as fh:
                m = re.match(r"(\d+)", str(json.load(fh).get("version", "")))
        except (OSError, ValueError, AttributeError):
            continue
        if m:
            return int(m.group(1))
    return None


def as_list(v):
    return [v] if isinstance(v, str) else list(v or [])


def detect(cmap, root):
    """Какие стеки есть в проекте и какие инструменты им нужны. Признак стека — любой из: npm-зависимость
    (`dependency`), Python-пакет из pyproject.toml или requirements*.txt (`python_dependency`), файл по имени или
    маске (`file`). → ([подписи стеков], {инструмент: стек})."""
    deps, files, pydeps = scan(root)
    stacks, tools = [], {}
    for st in cmap["stacks"]:
        found = [(n, hit) for n in as_list(st.get("dependency")) for hit in deps.get(n) or []]
        by_file = any(fnmatch.fnmatchcase(f, pat) for pat in as_list(st.get("file")) for f in files)
        by_py = any(py_name(n) in pydeps for n in as_list(st.get("python_dependency")))
        if not (found or by_file or by_py):
            continue
        majors = [major(spec, folder, n, root) for n, (spec, folder) in found]
        known = [m for m in majors if m is not None] if st.get("show_version") is not False else []
        label = f"{st['name']} {max(known)}" if known else st["name"]
        stacks.append(label)
        for name, cond in st["tools"].items():
            need = cond.get("min_major")
            if need is not None and majors and not any(m is None or m >= need for m in majors):
                continue
            tools.setdefault(name, label)
    return stacks, tools


def plugin_value(name, *layers):
    """Значение enabledPlugins по старшинству: первый слой, где плагин назван (local → проект → пользователь)."""
    for layer in layers:
        v = (layer.get("enabledPlugins") or {}).get(name)
        if v is not None:
            return bool(v)
    return None


def installed_plugins():
    data = read_json_quiet(os.path.join(HOME, ".claude", "plugins", "installed_plugins.json"))
    return set((data.get("plugins") if isinstance(data.get("plugins"), dict) else data).keys())


def read_json_quiet(path):
    try:
        return read_json(path)
    except Broken:
        return {}


def norm_server(cfg):
    """Для сравнения с картой: "type": "stdio" и «-y» самого npx (до имени пакета) смысла записи не меняют.
    Аргументы после пакета идут серверу и не трогаются."""
    if not isinstance(cfg, dict):
        return cfg
    cfg = {k: v for k, v in cfg.items() if not (k == "type" and v == "stdio")}
    if os.path.basename(str(cfg.get("command", ""))) == "npx" and isinstance(cfg.get("args"), list):
        args, i = list(cfg["args"]), 0
        while i < len(args) and str(args[i]).startswith("-"):
            i += 1
        cfg["args"] = [a for a in args[:i] if a not in ("-y", "--yes")] + args[i:]
    return cfg


def same_server(cur, want):
    return norm_server(cur) == norm_server(want)


def fingerprint(cfg):
    """Отпечаток одобренной записи — как она лежит в файле, без нормализации: любая правка заметна."""
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def safe_name(name):
    """Имя сервера из чужого .mcp.json в выводе агенту и в терминал: только безопасные символы, иначе — лишь
    отпечаток, чтобы имя не стало ни инструкцией модели, ни управляющей последовательностью терминала."""
    name = str(name)
    if re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", name):
        return name
    return f"«имя с недопустимыми символами #{hashlib.sha256(name.encode()).hexdigest()[:6]}»"


def names(items):
    return ", ".join(safe_name(x) for x in sorted(items))


def clip(text, limit=80):
    """Строка из репозитория в выводе агенту: без управляющих символов и не длиннее limit."""
    text = "".join(ch if ch.isprintable() else "?" for ch in str(text))
    return text if len(text) <= limit else text[:limit] + "…"


def describe(cfg):
    if not isinstance(cfg, dict):
        return clip(cfg)
    if cfg.get("url"):
        return clip(cfg["url"])
    return clip(" ".join([str(cfg.get("command", ""))] + [str(a) for a in cfg.get("args") or []]))


def toml_value(v):
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def codex_block(servers):
    lines = [CODEX_BEGIN]
    for name, cfg in servers.items():
        lines += ["", f"[mcp_servers.{name}]", f"command = {toml_value(cfg['command'])}",
                  f"args = {toml_value(cfg.get('args') or [])}"]
        if cfg.get("env"):
            lines.append("env = { " + ", ".join(f"{k} = {toml_value(v)}" for k, v in cfg["env"].items()) + " }")
    return "\n".join(lines + ["", CODEX_END]) + "\n"


def strip_codex_block(text):
    if text.count(CODEX_BEGIN) != text.count(CODEX_END):
        raise Broken("в .codex/config.toml оборван блок project-tools (нет одной из меток) — поправьте руками")
    pattern = re.compile(r"\n*" + re.escape(CODEX_BEGIN) + r".*?" + re.escape(CODEX_END) + r"\n?", re.S)
    return pattern.sub("\n", text)


def dumps(obj, inline_arrays, level=0):
    """JSON с отступом 2, как пишет сам Claude Code; inline_arrays — короткие массивы строк одной строкой, как в
    файле, оформленном вручную (["-y", "pkg@1"]), чтобы дифф показывал только правку."""
    pad = "  " * level
    if isinstance(obj, dict) and obj:
        items = [f"{pad}  {json.dumps(k, ensure_ascii=False)}: {dumps(v, inline_arrays, level + 1)}"
                 for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(obj, list) and obj:
        if inline_arrays and all(not isinstance(x, (dict, list)) for x in obj):
            one = "[" + ", ".join(json.dumps(x, ensure_ascii=False) for x in obj) + "]"
            if len(pad) + len(one) <= 100:
                return one
        items = [f"{pad}  {dumps(x, inline_arrays, level + 1)}" for x in obj]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(obj, ensure_ascii=False)


def json_text(path, data, new_style_inline):
    """Новое содержимое файла в его же стиле: массивы в строку, если так было (или файла нет и new_style_inline)."""
    old = read_text(path)
    inline = bool(re.search(r'\[[ \t]*["\d]', old)) if old else new_style_inline
    return dumps(data, inline) + "\n"


class Plan:
    def __init__(self, root, is_git):
        self.root, self.is_git = root, is_git
        self.stacks, self.wanted = [], {}
        self.changes, self.notes, self.missing, self.drift, self.unrecorded = [], [], [], [], []
        self.writes = {}  # путь → новое содержимое (текст)
        self.originals = {}  # путь → содержимое при чтении: apply не пишет, если файл успели изменить
        self.fingerprints = {}  # одобренный сервер → отпечаток записи, который apply запомнит

    def write(self, path, text):
        self.originals[path] = read_text(path)
        self.writes[path] = text

    def path(self, *parts):
        return os.path.join(self.root, *parts)


def load_approved():
    """Отпечатки одобренных записей. Битый файл — отказ, а не «пусто»: иначе проверка подмены тихо выключится."""
    if not os.path.lexists(APPROVED):
        return {}
    if os.path.islink(APPROVED):
        raise Broken(f"{short(APPROVED)} — символическая ссылка")
    return read_json(APPROVED)


def plan_approvals(p, local, shared, present, rejected, approve):
    """Одобрения .mcp.json: серверы из карты — поимённо в общий .claude/settings.json (уходит в PR вместе с
    .mcp.json, решение владельца 14.11, metis-1047: после слияния окно роли и другой Mac запускают их без вопроса);
    личный settings.local.json только чистится: «одобрять всё» → явный список, без имён, которых в .mcp.json нет.
    Возвращает (новый settings.local.json, личные одобрения, общие одобрения)."""
    new_local = dict(local)
    local_approved = set(local.get("enabledMcpjsonServers") or [])
    if local.get("enableAllProjectMcpServers") is True:
        local_approved |= present - rejected
        del new_local["enableAllProjectMcpServers"]
        p.changes.append(".claude/settings.local.json: enableAllProjectMcpServers заменён явным списком "
                         f"({names(present - rejected) or 'пусто'}) — новый сервер из "
                         "репозитория больше не запустится без вашего одобрения")
    stale = local_approved - present
    if stale:
        p.changes.append(f".claude/settings.local.json: сняты одобрения серверов, которых нет в .mcp.json: "
                         f"{names(stale)}")
    local_approved -= stale
    if local_approved or "enabledMcpjsonServers" in local:
        new_local["enabledMcpjsonServers"] = sorted(local_approved)
    shared_before = set(shared.get("enabledMcpjsonServers") or [])
    shared_approved = (shared_before | approve) & present
    if shared_before - shared_approved:
        p.changes.append(f".claude/settings.json: сняты одобрения серверов, которых нет в .mcp.json: "
                         f"{names(shared_before - shared_approved)}")
    if approve - shared_before:
        p.changes.append(f".claude/settings.json: одобрены {names(approve - shared_before)}")
    return new_local, local_approved, shared_approved


def make_plan(root, is_git, update=(), accept=(), tolerant=False):
    """Что apply запишет в проект. tolerant — для подсказки: битый ~/.claude.json не мешает."""
    cmap = load_map()
    p = Plan(root, is_git)
    p.stacks, p.wanted = detect(cmap, root)
    unknown = [u for u in update if u not in cmap["tools"]]
    if unknown:
        raise Broken(f"нет в карте: {', '.join(unknown)}")
    check_no_links(root)

    mcp_doc = read_json(p.path(".mcp.json"))
    servers = mcp_doc.get("mcpServers") if isinstance(mcp_doc.get("mcpServers"), dict) else {}
    shared = read_json(p.path(".claude", "settings.json"))
    local = read_json(p.path(".claude", "settings.local.json"))
    user = read_json_quiet(os.path.join(HOME, ".claude", "settings.json"))
    try:
        cj = read_json(os.path.join(HOME, ".claude.json"))
    except Broken:
        if not tolerant:
            raise
        cj = {}
    user_servers = cj.get("mcpServers") or {}
    proj = (cj.get("projects") or {}).get(root) or {}
    local_servers = proj.get("mcpServers") or {}
    toggled_off = set(proj.get("disabledMcpServers") or [])
    rejected = set()
    for layer in (local, shared, user, proj):
        rejected |= set(layer.get("disabledMcpjsonServers") or [])
    if user.get("enableAllProjectMcpServers") is True:
        p.notes.append("~/.claude/settings.json: enableAllProjectMcpServers одобряет любой сервер любого репозитория — "
                       "уберите")

    new_servers = dict(servers)
    approve, codex = set(), {}
    new_shared_plugins = dict(shared.get("enabledPlugins") or {})
    new_local_plugins = dict(local.get("enabledPlugins") or {})
    have_plugins = None

    for name in p.wanted:
        tool = cmap["tools"][name]
        if "mcp" in tool:
            want = tool["mcp"]
            if name in rejected:
                p.notes.append(f"{name}: отклонён вами (disabledMcpjsonServers) — не подключаю")
                continue
            if name in toggled_off:
                p.notes.append(f"{name}: выключен вами в /mcp для этого проекта — не подключаю")
                continue
            if name in user_servers:
                p.notes.append(f"{name}: подключён для всех проектов в ~/.claude.json — уберите оттуда "
                               f"(`claude mcp remove {name} -s user`), тогда apply подключит его в проект")
                continue
            if name in local_servers:
                p.notes.append(f"{name}: подключён только у вас (local scope в ~/.claude.json) — не дублирую")
                continue
            cur = servers.get(name)
            if cur is None:
                new_servers[name] = want
                p.changes.append(f".mcp.json: {name} — добавлен ({' '.join([want['command']] + want.get('args', []))})")
                p.missing.append(name)
                approve.add(name)
                codex[name] = want
            elif same_server(cur, want):
                approve.add(name)
                codex[name] = want
            elif name in update:
                new_servers[name] = want
                p.changes.append(f".mcp.json: {name} — заменён по карте ({' '.join([want['command']] + want.get('args', []))})")
                approve.add(name)
                codex[name] = want
            else:
                p.notes.append(f"{name}: в .mcp.json не как в карте ({describe(cur)}) — заменить: "
                               f"`project-tools apply --update {name}`")
            for plugin in tool.get("replaces_plugins", []):
                if name in new_servers and plugin_value(plugin, {"enabledPlugins": new_local_plugins},
                                                         {"enabledPlugins": new_shared_plugins}, user):
                    target = new_local_plugins if new_local_plugins.get(plugin) else new_shared_plugins
                    target[plugin] = False
                    where = "settings.local.json" if target is new_local_plugins else "settings.json"
                    p.changes.append(f".claude/{where}: плагин {plugin} выключен — его заменяет {name} из .mcp.json")
        elif "plugin" in tool:
            plugin = tool["plugin"]
            state = plugin_value(plugin, local, shared, user)
            if state:
                continue
            if (local.get("enabledPlugins") or {}).get(plugin) is False or \
                    (shared.get("enabledPlugins") or {}).get(plugin) is False:
                p.notes.append(f"{name}: плагин {plugin} выключен в настройках проекта — не включаю")
                continue
            new_shared_plugins[plugin] = True
            p.changes.append(f".claude/settings.json: плагин {plugin} включён")
            p.missing.append(name)
            if have_plugins is None:
                have_plugins = installed_plugins()
            if plugin not in have_plugins:
                p.notes.append(f"{name}: плагин {plugin} не установлен — `claude plugin install {plugin}`")

    # .mcp.json
    if new_servers != servers:
        doc = dict(mcp_doc)
        doc["mcpServers"] = new_servers
        p.write(p.path(".mcp.json"), json_text(p.path(".mcp.json"), doc, True))

    new_local, local_approved, shared_approved = plan_approvals(p, local, shared, set(new_servers), rejected,
                                                                approve)
    approved = local_approved | shared_approved

    # одобренные записи против запомненных отпечатков: подмена команды под одобренным именем
    remembered = load_approved().get(root) or {}
    live = (approved | set(proj.get("enabledMcpjsonServers") or [])) - rejected - toggled_off
    for name in sorted(live & set(new_servers)):
        now = fingerprint(new_servers[name])
        was = remembered.get(name)
        if was and was != now and name not in accept and name not in update:
            p.drift.append(name)
            p.fingerprints[name] = was
            shown = safe_name(name)
            p.notes.append(f"⚠ {shown}: запись в .mcp.json изменилась после одобрения, теперь «{describe(new_servers[name])}». "
                           f"Проверьте `git log -p .mcp.json`; ваше — `project-tools apply --accept {shown}`, "
                           f"не ваше — `project-tools skip {shown}`")
        else:
            p.fingerprints[name] = now
            if not was:
                p.unrecorded.append(name)
    if p.unrecorded:
        p.notes.append(f"отпечатки одобренных серверов не записаны на этом Mac: {names(p.unrecorded)} — apply запомнит "
                       "их, и подсказка заметит подмену после git pull")
    if new_local_plugins != (local.get("enabledPlugins") or {}):
        new_local["enabledPlugins"] = new_local_plugins
    if new_local != local:
        p.write(p.path(".claude", "settings.local.json"),
                json_text(p.path(".claude", "settings.local.json"), new_local, False))
    if shared.get("enableAllProjectMcpServers") is True:
        p.notes.append(".claude/settings.json: enableAllProjectMcpServers одобряет любой сервер из репозитория — "
                       "уберите (project-tools общие настройки сам не чистит)")

    new_shared = dict(shared)
    if new_shared_plugins != (shared.get("enabledPlugins") or {}):
        new_shared["enabledPlugins"] = new_shared_plugins
    if shared_approved or "enabledMcpjsonServers" in shared:
        new_shared["enabledMcpjsonServers"] = sorted(shared_approved)
    if new_shared != shared:
        p.write(p.path(".claude", "settings.json"), json_text(p.path(".claude", "settings.json"), new_shared, False))

    # Codex: тот же набор серверов из карты, своим блоком
    if os.path.isdir(p.path(".codex")) or shutil.which("codex"):
        cpath = p.path(".codex", "config.toml")
        old = read_text(cpath) or ""
        rest = strip_codex_block(old).strip("\n")
        try:
            theirs = (tomllib.loads(rest).get("mcp_servers") or {}) if rest else {}
        except tomllib.TOMLDecodeError as e:
            raise Broken(f"{short(cpath)}: не TOML ({e})")
        for name in [n for n in codex if n in theirs]:
            p.notes.append(f"{name}: в .codex/config.toml уже описан вами — блок project-tools его не дублирует")
            del codex[name]
        new = "\n\n".join(([rest + "\n"] if rest else []) + ([codex_block(codex)] if codex else []))
        if new.strip() != old.strip():
            p.write(cpath, new)
            p.changes.append(f".codex/config.toml: серверы для Codex — {', '.join(codex) or 'блок убран'}")

    if p.writes and not is_git and not os.path.isfile(p.path("package.json")):
        p.notes.append("папка не git-репозиторий и без package.json — проверьте, что это корень проекта")
    tracked = p.path(".claude", "settings.local.json")
    if is_git and tracked in p.writes and _tracked(root, ".claude/settings.local.json"):
        p.notes.append(".claude/settings.local.json лежит в git: одобрения из него Claude применит только после "
                       "доверия к папке, и они уйдут в репозиторий — уберите файл из git")
    return p


def _tracked(root, rel):
    try:
        return subprocess.run(["git", "-C", root, "ls-files", "--error-unmatch", rel], capture_output=True,
                              timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# Всё, что команда читает и пишет в проекте. Ссылка среди них — отказ: .mcp.json → ~/.claude.json дал бы прочитать
# ваш файл с ключами и записать его содержимое в проект (оттуда — в коммит), а ссылка-папка увела бы запись наружу.
OWN_PATHS = (".mcp.json", ".claude", ".claude/settings.json", ".claude/settings.local.json", ".codex",
             ".codex/config.toml")


def check_no_links(root):
    for rel in OWN_PATHS:
        path = os.path.join(root, rel)
        if os.path.islink(path):
            raise Broken(f"{short(path)} — символическая ссылка: настройки проекта не читаю и не пишу")
        if os.path.lexists(path) and not os.path.realpath(path).startswith(root + os.sep):
            raise Broken(f"{short(path)} ведёт за пределы проекта")


def write_atomic(path, text):
    """Запись через временный файл рядом: mkstemp создаёт его заново (O_EXCL), чужая ссылка с тем же именем не
    сработает; os.replace меняет запись в папке, не идя по ссылке."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    if os.path.islink(path) or os.path.islink(folder):
        raise Broken(f"{short(path)} — символическая ссылка: не пишу")
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".project-tools-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if os.path.exists(path):
            os.chmod(tmp, os.stat(path).st_mode & 0o777)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def report(p, applied):
    print(f"Проект: {short(p.root)}{'' if p.is_git else ' (не git)'}")
    print(f"Стек: {', '.join(p.stacks) if p.stacks else 'по карте ничего не найдено'}")
    if p.changes:
        print("Записано:" if applied else "Нужно:")
        for c in p.changes:
            print(f"  + {c}")
    else:
        print("Менять нечего: всё по карте.")
    for n in p.notes:
        print(f"  · {n}")
    if p.changes and not applied:
        print("Подключить: project-tools apply" + ("" if p.root == os.path.realpath(os.getcwd()) else
                                                   f" --dir {short(p.root)}"))


def not_project(root):
    return root in (HOME, REAL_HOME, "/", os.path.dirname(HOME), os.path.dirname(REAL_HOME))


def guard_root(root):
    if not_project(root):
        raise Broken(f"{short(root)}: это не папка проекта")


PROBE_MARK = {"ok": "+", "auth": "?", "fail": "!", "skip": "·"}


def probe_servers(root):
    """Серверы .mcp.json проекта → [(имя, kind, итог)] (mcp_probe.check_servers): HTTP — по сети, только одобренные
    и не выключенные, как их запускает Claude Code; stdio — «не запускаю»."""
    doc = read_json_quiet(os.path.join(root, ".mcp.json"))
    servers = doc.get("mcpServers") if isinstance(doc.get("mcpServers"), dict) else {}
    if not servers:
        return []
    cj = read_json_quiet(os.path.join(HOME, ".claude.json"))
    proj = (cj.get("projects") or {}).get(root) or {}
    approved, off = mcp_probe.approved_names(read_json_quiet(os.path.join(root, ".claude", "settings.json")),
                                             read_json_quiet(os.path.join(root, ".claude", "settings.local.json")),
                                             proj, read_json_quiet(os.path.join(HOME, ".claude", "settings.json")))
    return mcp_probe.check_servers(servers, approved, off)


def probe_report(results):
    if not results:
        return
    print("Серверы MCP (.mcp.json):")
    for name, kind, got in results:
        print(f"  {PROBE_MARK[got['state']]} {safe_name(name)} ({kind}): {got['why']}")


def cmd_check(args):
    root, is_git = project_root(args.dir)
    guard_root(root)
    if args.json:
        # для `pantheon direction check`: стек есть, а инструмента нет (то, что apply подключил бы). Только имена.
        p = make_plan(root, is_git, tolerant=True)
        out = {"stacks": p.stacks, "missing": [{"tool": n, "stack": p.wanted[n]} for n in p.missing]}
        if args.probe and not args.no_net:
            out["servers"] = [{"name": n, "kind": k, **got} for n, k, got in probe_servers(root)]
        print(json.dumps(out, ensure_ascii=False))
        return 0
    p = make_plan(root, is_git, args.update or ())
    report(p, applied=False)
    if not args.no_net:
        probe_report(probe_servers(root))
    return 3 if p.changes or p.drift or p.unrecorded else 0


def save_approved(root, fingerprints):
    data = load_approved()
    if (data.get(root) or {}) == fingerprints:
        return
    data[root] = fingerprints
    write_atomic(APPROVED, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def cmd_apply(args):
    root, is_git = project_root(args.dir)
    guard_root(root)
    p = make_plan(root, is_git, args.update or (), args.accept or ())
    changed = [x for x, old in p.originals.items() if read_text(x) != old]
    if changed:
        raise Broken(f"{', '.join(short(x) for x in changed)} изменился во время работы — повторите")
    done = []
    for path, text in p.writes.items():
        try:
            write_atomic(path, text)
        except OSError as e:
            raise PartlyWritten(f"запись {short(path)} не удалась ({e.strerror or e}); "
                                + (f"уже записано: {', '.join(short(x) for x in done)}" if done else "ничего не записано"))
        done.append(path)
    try:
        save_approved(root, p.fingerprints)
        if p.unrecorded:
            p.notes = [n for n in p.notes if not n.startswith("отпечатки одобренных серверов не записаны")]
            p.notes.append(f"отпечатки одобренных серверов запомнены: {names(p.unrecorded)}")
    except (OSError, Broken) as e:
        p.notes.append(f"отпечатки одобрений не запомнены ({e}) — подсказка не заметит подмену")
    report(p, applied=True)
    shared = sorted(os.path.relpath(x, root) for x in p.writes if not x.endswith("settings.local.json"))
    if p.writes:
        print("Серверы подключатся в новой сессии." + (f" Для коммита: {', '.join(shared)}." if shared else ""))
    return 0


def cmd_skip(args):
    """Ваше «не надо»: сервер — в disabledMcpjsonServers (Claude его не запустит), плагин — false; всё в
    settings.local.json, подсказка о нём больше не говорит."""
    root, is_git = project_root(args.dir)
    guard_root(root)
    check_no_links(root)
    cmap = load_map()
    lpath = os.path.join(root, ".claude", "settings.local.json")
    local = read_json(lpath)
    servers = read_json(os.path.join(root, ".mcp.json")).get("mcpServers") or {}
    new, done = dict(local), []
    for name in args.names:
        tool = cmap["tools"].get(name) or {}
        if "plugin" in tool:
            new["enabledPlugins"] = {**(new.get("enabledPlugins") or {}), tool["plugin"]: False}
            done.append(f"плагин {tool['plugin']} выключен")
        elif name in servers or "mcp" in tool:
            new["disabledMcpjsonServers"] = sorted(set(new.get("disabledMcpjsonServers") or []) | {name})
            if name in (new.get("enabledMcpjsonServers") or []):
                new["enabledMcpjsonServers"] = [x for x in new["enabledMcpjsonServers"] if x != name]
            done.append(f"{safe_name(name)} отклонён (disabledMcpjsonServers)")
        else:
            raise Broken(f"{safe_name(name)}: нет ни в карте, ни в .mcp.json")
    if new != local:
        original = read_text(lpath)
        text = json_text(lpath, new, False)
        if read_text(lpath) != original:
            raise Broken(f"{short(lpath)} изменился во время работы — повторите")
        write_atomic(lpath, text)
    print(f"Проект: {short(root)}")
    for d in done:
        print(f"  − .claude/settings.local.json: {d}")
    print("Серверы и плагины перестанут запускаться в новой сессии; вернуть — убрать запись из settings.local.json.")
    return 0


def hint_warning(reason):
    msg = f"project-tools: ⚠ настройки MCP проекта не проверить ({clip(reason, 160)}). Проверьте: project-tools check"
    print(json.dumps({"systemMessage": msg, "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": msg + ". Скажи владельцу; серверы из .mcp.json не вызывай, пока он не ответит."}},
        ensure_ascii=False))


def cmd_hint(_args):
    """SessionStart: строка в контекст, если по карте чего-то не хватает или одобренная запись изменилась. Вне
    проекта и без .mcp.json сбой — молча (запись в журнал); при .mcp.json любой сбой — предупреждение вам: молчание
    выключило бы проверку подмены."""
    root = None
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        event = json.loads(raw) if raw.strip() else {}
        root, is_git = project_root(event.get("cwd") or os.getcwd())
        if not_project(root):
            return 0
        if not is_git and not os.path.isfile(os.path.join(root, "package.json")):
            return 0
        try:
            p = make_plan(root, is_git, tolerant=True)
        except Broken as e:
            if os.path.lexists(os.path.join(root, ".mcp.json")):
                hint_warning(e)
            return 0
        if not (p.missing or p.drift or p.changes or p.unrecorded):
            return 0
        lines, out = [], {}
        if p.drift:
            lines.append(f"project-tools: ⚠ в .mcp.json после одобрения изменились серверы {names(p.drift)}, "
                         "и Claude Code уже запустил их без вопроса. Сразу скажи владельцу и покажи "
                         "`project-tools check`; сам эти серверы не вызывай, пока он не ответит.")
            out["systemMessage"] = (f"project-tools: ⚠ в .mcp.json изменились одобренные серверы: {names(p.drift)}. "
                                    "Проверьте: project-tools check")
        if p.missing:
            lines.append(f"project-tools: в проекте {', '.join(p.stacks)}; по карте стеков не подключены: "
                         f"{', '.join(p.missing)}. Один раз предложи владельцу: «Подключить инструменты проекта?» "
                         "(навык project-tools, команда `project-tools apply`; «не надо» — `project-tools skip`). "
                         "В окне роли Пантеона не подключай — `project-tools check` и вопрос владельцу.")
        elif p.changes or p.unrecorded:
            # например, другой Mac: .mcp.json пришёл из git, а одобрений и отпечатков здесь нет
            why = ([f"{len(p.changes)} правок по карте"] if p.changes else []) + \
                  ([f"не записаны отпечатки: {names(p.unrecorded)}"] if p.unrecorded else [])
            lines.append(f"project-tools: настройки MCP проекта на этом Mac не по карте ({'; '.join(why)}). Один раз "
                         "предложи владельцу `project-tools apply` (что поменяется — `project-tools check`). "
                         "В окне роли Пантеона не применяй — только вопрос владельцу.")
        out["hookSpecificOutput"] = {"hookEventName": "SessionStart", "additionalContext": " ".join(lines)}
        print(json.dumps(out, ensure_ascii=False))
    except Exception as e:
        try:
            os.makedirs(os.path.dirname(LOG), exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} hint {root or os.getcwd()}\n{traceback.format_exc()}\n")
        except OSError:
            pass
        if root and not not_project(root) and os.path.lexists(os.path.join(root, ".mcp.json")):
            hint_warning(f"сбой проверки: {type(e).__name__}; подробности — {short(LOG)}")
    return 0


def pinned_version(tool):
    for a in (tool.get("mcp") or {}).get("args", []):
        if a.startswith(tool["npm"] + "@"):
            return a.split("@", 1)[1]
    return None


def cmd_outdated(_args):
    cmap, behind = load_map(), 0
    for name, tool in cmap["tools"].items():
        if not tool.get("npm"):
            continue
        pinned = pinned_version(tool)
        try:
            r = subprocess.run(["npm", "view", tool["npm"], "version"], capture_output=True, text=True, timeout=30)
            latest = r.stdout.strip() if r.returncode == 0 else "?"
        except (OSError, subprocess.SubprocessError):
            latest = "?"
        mark = "" if latest in (pinned, "?") else "  ← есть новее"
        behind += bool(mark)
        print(f"{name:18} {tool['npm']:22} в карте {pinned or '—':10} в npm {latest}{mark}")
    return 3 if behind else 0


def cmd_map(_args):
    cmap = load_map()
    for st in cmap["stacks"]:
        sign = f"зависимость {st['dependency']}" if st.get("dependency") else f"файл {st.get('file')}"
        tools = ", ".join(n + (f" (с {c['min_major']})" if c.get("min_major") else "") for n, c in st["tools"].items())
        print(f"{st['name']} — {sign} → {tools}")
    print()
    for name, tool in cmap["tools"].items():
        how = "плагин " + tool["plugin"] if "plugin" in tool else " ".join([tool["mcp"]["command"]] + tool["mcp"]["args"])
        print(f"{name}: {tool.get('about', '')}\n  {how}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="project-tools", description="Инструменты проекта по карте стеков")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "apply"):
        s = sub.add_parser(name)
        s.add_argument("--dir", default=os.getcwd())
        s.add_argument("--update", action="append", metavar="ИМЯ", help="заменить запись .mcp.json по карте")
        if name == "check":
            s.add_argument("--json", action="store_true", help="только стеки и не подключённые инструменты, JSON")
            s.add_argument("--no-net", action="store_true", help="не проверять HTTP-серверы MCP по сети")
            s.add_argument("--probe", action="store_true", help="с --json: проверить HTTP-серверы (поле servers)")
        if name == "apply":
            s.add_argument("--accept", action="append", metavar="ИМЯ",
                           help="принять изменённую после одобрения запись .mcp.json как вашу")
    s = sub.add_parser("skip")
    s.add_argument("names", nargs="+", metavar="ИМЯ")
    s.add_argument("--dir", default=os.getcwd())
    for name in ("hint", "outdated", "map"):
        sub.add_parser(name)
    args = ap.parse_args(argv)
    try:
        return {"check": cmd_check, "apply": cmd_apply, "skip": cmd_skip, "hint": cmd_hint, "outdated": cmd_outdated,
                "map": cmd_map}[args.cmd](args)
    except PartlyWritten as e:
        print(f"project-tools: {e}.", file=sys.stderr)
        return 2
    except Broken as e:
        print(f"project-tools: {e}. Ничего не записано.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
