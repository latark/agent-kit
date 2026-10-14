#!/usr/bin/env python3
"""project-tools — инструменты проекта по карте стеков (TOOL-07, MEM-04).

Карта ../stacks.json: признак в проекте (зависимость в package.json или файл) → какие MCP-серверы и плагины нужны.
Команды:
  project-tools check [--dir D]                    что подключить или поправить; ничего не меняет
  project-tools apply [--dir D] [--update ИМЯ]…    записать .mcp.json, одобрения, плагины, блок Codex
  project-tools hint                               хук SessionStart: одна строка в контекст, если чего-то нет
  project-tools outdated                           закреплённые версии против свежих в npm
  project-tools map                                карта стеков

Пишет только записи из карты рядом с этим файлом: другой карты команда не принимает, поэтому произвольный сервер
через неё не подключить. В окнах ролей запись в .mcp.json и .claude/settings*.json запрещают песочница Claude Code
(protected paths) и guard (SEC-14): там роль запускает только check и спрашивает владельца.

Куда пишет apply (корень проекта — вершина git-репозитория, иначе папка):
  .mcp.json                     серверы из карты; чужие записи не трогает, отличие от карты меняет только --update
  .claude/settings.local.json   enabledMcpjsonServers — тогда Claude не спрашивает одобрения; enableAllProjectMcpServers
                                заменяет явным списком (иначе любой новый сервер из репозитория запустится без вопроса)
  .claude/settings.json         enabledPlugins: плагины из карты; плагины, которые заменяет сервер из карты, — false
  .codex/config.toml            блок [mcp_servers.*], если Codex установлен или папка .codex уже есть
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from collections import deque

if sys.version_info < (3, 11):
    sys.exit("project-tools: нужен Python 3.11 или новее (tomllib)")
import tomllib

PLUGIN = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MAP = os.path.join(PLUGIN, "stacks.json")
HOME = os.path.realpath(os.path.expanduser("~"))
LOG = os.path.join(HOME, ".local", "state", "pantheon", "logs", "project-tools.log")
SKIP_DIRS = {"node_modules", "dist", "build", "out", "coverage", "vendor", "venv", "env", "__pycache__", "target",
             "Pods", "DerivedData"}
SCAN_DEPTH, SCAN_LIMIT = 3, 400
CODEX_BEGIN = "# >>> project-tools (agent-kit): блок пишет `project-tools apply`, руками не править"
CODEX_END = "# <<< project-tools"


class Broken(Exception):
    """Файл настроек не читается или стоит не там: apply не пишет ничего."""


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


def scan(root):
    """Зависимости из всех package.json и имена файлов до SCAN_DEPTH уровней вглубь (монорепозитории: apps/*,
    packages/*). Скрытые папки, node_modules и сборки пропускает. → ({зависимость: [(версия, папка)]}, {файлы})."""
    deps, files = {}, set()
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
                elif (e.is_dir(follow_symlinks=False) and level < SCAN_DEPTH and not e.name.startswith(".")
                      and e.name not in SKIP_DIRS):
                    queue.append((e.path, level + 1))
            except OSError:
                continue
    return deps, files


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


def detect(cmap, root):
    """Какие стеки есть в проекте и какие инструменты им нужны. → ([подписи стеков], {инструмент: стек})."""
    deps, files = scan(root)
    stacks, tools = [], {}
    for st in cmap["stacks"]:
        if st.get("dependency"):
            found = deps.get(st["dependency"])
            if not found:
                continue
            majors = [major(spec, folder, st["dependency"], root) for spec, folder in found]
        elif st.get("file"):
            if st["file"] not in files:
                continue
            majors = []
        else:
            continue
        known = [m for m in majors if m is not None]
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


def same_server(cur, want):
    """Запись совпадает с картой: «-y» у npx и "type": "stdio" смысла не меняют."""
    def norm(cfg):
        if not isinstance(cfg, dict):
            return cfg
        cfg = {k: v for k, v in cfg.items() if not (k == "type" and v == "stdio")}
        if os.path.basename(str(cfg.get("command", ""))) == "npx":
            cfg["args"] = [a for a in cfg.get("args") or [] if a not in ("-y", "--yes")]
        return cfg
    return norm(cur) == norm(want)


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
        self.changes, self.notes, self.missing = [], [], []
        self.writes = {}  # путь → новое содержимое (текст)

    def path(self, *parts):
        return os.path.join(self.root, *parts)


def make_plan(root, is_git, update=(), tolerant=False):
    """Что apply запишет в проект. tolerant — для подсказки: битый ~/.claude.json не мешает."""
    cmap = load_map()
    p = Plan(root, is_git)
    p.stacks, p.wanted = detect(cmap, root)
    unknown = [u for u in update if u not in cmap["tools"]]
    if unknown:
        raise Broken(f"нет в карте: {', '.join(unknown)}")
    if os.path.islink(p.path(".claude")):
        raise Broken(f"{short(p.path('.claude'))} — символическая ссылка: настройки проекта не пишу")

    mcp_doc = read_json(p.path(".mcp.json"))
    servers = mcp_doc.get("mcpServers") if isinstance(mcp_doc.get("mcpServers"), dict) else {}
    shared = read_json(p.path(".claude", "settings.json"))
    local = read_json(p.path(".claude", "settings.local.json"))
    user = read_json_quiet(os.path.join(HOME, ".claude", "settings.json"))
    try:
        cj = read_json(os.path.join(HOME, ".claude.json"))
    except Broken as e:
        if not tolerant:
            raise
        cj = {}
    user_servers = cj.get("mcpServers") or {}
    proj = (cj.get("projects") or {}).get(root) or {}
    local_servers = proj.get("mcpServers") or {}
    toggled_off = set(proj.get("disabledMcpServers") or [])
    rejected = set()
    for layer in (local, shared, user):
        rejected |= set(layer.get("disabledMcpjsonServers") or [])

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
                was = " ".join([str(cur.get("command", ""))] + [str(a) for a in cur.get("args") or []])
                p.notes.append(f"{name}: в .mcp.json не как в карте ({was}) — заменить: "
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
        p.writes[p.path(".mcp.json")] = json_text(p.path(".mcp.json"), doc, True)

    # одобрения: явный список вместо «одобрять всё», без имён, которых в .mcp.json нет
    new_local = dict(local)
    before = set(local.get("enabledMcpjsonServers") or [])
    approved = set(before)
    if local.get("enableAllProjectMcpServers") is True:
        approved |= set(new_servers) - rejected
        del new_local["enableAllProjectMcpServers"]
        p.changes.append(".claude/settings.local.json: enableAllProjectMcpServers заменён явным списком "
                         f"({', '.join(sorted(set(new_servers) - rejected)) or 'пусто'}) — новый сервер из "
                         "репозитория больше не запустится без вашего одобрения")
    approved |= approve
    stale = approved - set(new_servers)
    if stale:
        p.changes.append(f".claude/settings.local.json: сняты одобрения серверов, которых нет в .mcp.json: "
                         f"{', '.join(sorted(stale))}")
    approved -= stale
    if approve - before:
        p.changes.append(f".claude/settings.local.json: одобрены {', '.join(sorted(approve - before))}")
    if approved or "enabledMcpjsonServers" in local:
        new_local["enabledMcpjsonServers"] = sorted(approved)
    if new_local_plugins != (local.get("enabledPlugins") or {}):
        new_local["enabledPlugins"] = new_local_plugins
    if new_local != local:
        p.writes[p.path(".claude", "settings.local.json")] = json_text(p.path(".claude", "settings.local.json"),
                                                                         new_local, False)
    if shared.get("enableAllProjectMcpServers") is True:
        p.notes.append(".claude/settings.json: enableAllProjectMcpServers одобряет любой сервер из репозитория — "
                       "уберите (project-tools общие настройки сам не чистит)")

    if new_shared_plugins != (shared.get("enabledPlugins") or {}):
        new_shared = dict(shared)
        new_shared["enabledPlugins"] = new_shared_plugins
        p.writes[p.path(".claude", "settings.json")] = json_text(p.path(".claude", "settings.json"), new_shared, False)

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
            p.writes[cpath] = new
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


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.project-tools-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    if os.path.exists(path) and not os.path.islink(path):
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
    os.replace(tmp, path)


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
    return root in (HOME, "/", os.path.dirname(HOME))


def guard_root(root):
    if not_project(root):
        raise Broken(f"{short(root)}: это не папка проекта")


def cmd_check(args):
    root, is_git = project_root(args.dir)
    guard_root(root)
    p = make_plan(root, is_git, args.update or ())
    report(p, applied=False)
    return 3 if p.changes else 0


def cmd_apply(args):
    root, is_git = project_root(args.dir)
    guard_root(root)
    p = make_plan(root, is_git, args.update or ())
    for path, text in p.writes.items():
        write_atomic(path, text)
    report(p, applied=True)
    shared = sorted(os.path.relpath(x, root) for x in p.writes if not x.endswith("settings.local.json"))
    if p.writes:
        print("Серверы подключатся в новой сессии." + (f" Для коммита: {', '.join(shared)}." if shared else ""))
    return 0


def cmd_hint(_args):
    """SessionStart: одна строка в контекст, если по карте чего-то не хватает. Сбой — молча, запись в журнал."""
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        event = json.loads(raw) if raw.strip() else {}
        root, is_git = project_root(event.get("cwd") or os.getcwd())
        if not_project(root):
            return 0
        if not is_git and not os.path.isfile(os.path.join(root, "package.json")):
            return 0
        p = make_plan(root, is_git, tolerant=True)
        if not p.missing:
            return 0
        line = (f"project-tools: в проекте {', '.join(p.stacks)}; по карте стеков не подключены: "
                f"{', '.join(p.missing)}. Один раз предложи владельцу: «Подключить инструменты проекта?» "
                "(навык project-tools, команда `project-tools apply`). В окне роли Пантеона не подключай — "
                "`project-tools check` и вопрос владельцу.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": line}},
                         ensure_ascii=False))
    except Exception:
        try:
            os.makedirs(os.path.dirname(LOG), exist_ok=True)
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} hint {os.getcwd()}\n{traceback.format_exc()}\n")
        except OSError:
            pass
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
    for name in ("hint", "outdated", "map"):
        sub.add_parser(name)
    args = ap.parse_args(argv)
    try:
        return {"check": cmd_check, "apply": cmd_apply, "hint": cmd_hint, "outdated": cmd_outdated,
                "map": cmd_map}[args.cmd](args)
    except Broken as e:
        print(f"project-tools: {e}. Ничего не записано.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
