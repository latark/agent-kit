"""Карта «окно или роль × плагин и MCP» (metis-0238): разбор plugins-by-role.toml и применение к настройкам окна и шапке роли.

Ядро защит (metis-0598, решение владельца 30.10): PR, который меняет модуль или карту, сливает владелец. Карта задаёт,
какие плагины и MCP окну и роли недоступны (enabledPlugins: false и правила permissions.deny mcp__<сервер> окна;
mcp__<сервер> в disallowedTools шапки роли). Модуль без состояния (ввод-вывод — ниже, в абзаце metis-1051): его
грузит pantheon.py по пути файла (python3 -I не кладёт папку скрипта в путь импорта).

Запись карты — «оставить»: названное остаётся, остальное из [catalog] выключается. Окна или роли, которых в карте нет, и
плагины и MCP вне [catalog] не трогаются — безопасный дефолт «всё включено».

Записи окон своих направлений пользователь держит не в карте плагина, а в личной части
~/.claude/pantheon/plugins-by-role.toml (overlay): только [window.<направление>], каталог — из карты плагина.

Список разрешённых MCP окна (metis-1051): необязательный ключ mcp_extra записи окна — серверы и инструменты вне
каталога («сервер» или «сервер__инструмент», в инструменте можно «*»). window_apply с guard (путь строгого guard.py
проверенного дерева) пишет окну хук PreToolUse «mcp__.*» — hooks/mcp_gate.py того же дерева со списком mcp + mcp_extra:
всё, что в нём не названо, guard отклоняет. В дереве guard нет mcp_gate.py (выпуск старее) — хука нет, как раньше.
Ввод-вывод модуля — только чтение карты и проверка, что файлы хука есть.
"""

import os
import re
import shlex
import tomllib

MCP_NAME = re.compile(r"[A-Za-z0-9_-]+")
# запись mcp_extra: тот же образец, что ENTRY в plugins/guard/hooks/mcp_gate.py (сверяет test_mcp_gate)
MCP_ENTRY = re.compile(r"[A-Za-z0-9-]+(?:_[A-Za-z0-9-]+)*(?:__[A-Za-z0-9*-]+(?:_[A-Za-z0-9*-]+)*)?")
MCP_GATE = "mcp_gate.py"
MCP_MATCHER = "mcp__.*"
PLUGIN_ID = re.compile(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+")
# Каталог, чьи плагины карта не выключает никогда: agent-kit — сами защиты (guard), Пантеон и project-tools. Такой
# плагин в [catalog] — ValueError: «оставить» без него выключило бы guard и pantheon во всех окнах.
OWN_MARKET = "agent-kit"


def load(path, windows=None, roles=None):
    """Карта из файла. ValueError с причиной: нет файла, битый TOML, не тот тип, плагин @agent-kit в каталоге, ключ
    «оставить» вне каталога (опечатка молча выключила бы нужное). windows и roles — множества известных имён окон и
    ролей (None — не сверять): запись [window.X] или [role.X] с неизвестным именем пропускается (не применяется) и
    попадает в out["skipped"] как «[window.X]»; остальная карта действует. Отвергать всю карту нельзя: одна опечатка
    или удалённое из реестра направление сняла бы ограничения со всех окон и ролей (fail-open)."""
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError(f"карта плагинов {path}: {e}") from e
    cat = raw.get("catalog")
    if not isinstance(cat, dict):
        raise ValueError("карта плагинов: нет раздела [catalog]")
    plugins, mcp = cat.get("plugins"), cat.get("mcp")
    if not (isinstance(plugins, list) and all(isinstance(x, str) and PLUGIN_ID.fullmatch(x) for x in plugins)):
        raise ValueError("карта плагинов: catalog.plugins — список «имя@каталог»")
    own = [x for x in plugins if x.rsplit("@", 1)[1].lower() == OWN_MARKET]
    if own:
        raise ValueError(f"карта плагинов: catalog.plugins: {own} — плагины @{OWN_MARKET} (guard, pantheon, "
                         "project-tools) карта не выключает, в каталоге их быть не может")
    if not (isinstance(mcp, list) and all(isinstance(x, str) and MCP_NAME.fullmatch(x) for x in mcp)):
        raise ValueError("карта плагинов: catalog.mcp — список имён серверов")
    out = {"plugins": list(plugins), "mcp": list(mcp), "window": {}, "role": {}, "skipped": []}
    for kind, keys in (("window", ("plugins", "mcp")), ("role", ("mcp",))):
        section = raw.get(kind, {})
        if not isinstance(section, dict):
            raise ValueError(f"карта плагинов: [{kind}] — таблица")
        known = windows if kind == "window" else roles
        for name, entry in section.items():
            if known is not None and name not in known:
                out["skipped"].append(f"[{kind}.{name}]")
                continue
            out[kind][name] = _entry(out, kind, name, entry, keys)
    return out


def _entry(out, kind, name, entry, keys):
    """Запись [kind.name] карты → {ключ: список}; ValueError — не те ключи, не список строк или имя вне каталога out.
    У окна ещё необязательный mcp_extra (записи MCP_ENTRY, каталог не сверяется); нет ключа — пустой список."""
    extra = kind == "window" and isinstance(entry, dict) and "mcp_extra" in entry
    if not isinstance(entry, dict) or set(entry) - set(keys) - ({"mcp_extra"} if extra else set()):
        raise ValueError(f"карта плагинов: [{kind}.{name}] — только ключи {', '.join(keys)}"
                         + (" и mcp_extra" if kind == "window" else ""))
    keep = {}
    for k in keys:
        vals = entry.get(k)
        if not isinstance(vals, list) or not all(isinstance(x, str) for x in vals):
            raise ValueError(f"карта плагинов: [{kind}.{name}] {k} — список строк (пустой — «ничего»)")
        unknown = [x for x in vals if x not in out[k]]
        if unknown:
            raise ValueError(f"карта плагинов: [{kind}.{name}] {k}: {unknown} нет в [catalog]")
        keep[k] = list(vals)
    if extra:  # ключ в записи только тогда, когда он в карте: нет его — список пуст (keep.get)
        vals = entry["mcp_extra"]
        if not isinstance(vals, list) or not all(isinstance(x, str) and MCP_ENTRY.fullmatch(x) for x in vals):
            raise ValueError(f"карта плагинов: [{kind}.{name}] mcp_extra — список записей «сервер» или "
                             "«сервер__инструмент»")
        keep["mcp_extra"] = list(vals)
    return keep


def overlay(pmap, path, allowed, system=()):
    """Личная часть карты (решение владельца 12.11: окна направлений — личные настройки): файл path только с
    [window.<направление>] поверх pmap, запись заменяет одноимённую. allowed — имена окон направлений реестра (None —
    реестр не прочитан, не сверять), system — окна системы (hq, hestia, workshop, direction, job-*): их записи только в
    карте плагина. Запись вне allowed или из system — в pmap["skipped"] с пометкой «личная часть». Каталог — из pmap:
    личная часть его не расширяет. Нет файла — pmap как есть; битый файл или запись — ValueError (вызывающий
    оставляет карту плагина без личной части)."""
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        return pmap
    except (OSError, ValueError) as e:
        raise ValueError(f"личная карта плагинов {path}: {e}") from e
    if set(raw) - {"window"} or not isinstance(raw.get("window", {}), dict):
        raise ValueError(f"личная карта плагинов {path}: только таблицы [window.<направление>]")
    got, skipped = {}, []
    for name, entry in raw.get("window", {}).items():
        if name in system or (allowed is not None and name not in allowed):
            skipped.append(f"[window.{name}] (личная часть)")
            continue
        got[name] = _entry(pmap, "window", name, entry, ("plugins", "mcp"))
    pmap["window"].update(got)  # после разбора всех записей: битая запись не оставит карту наполовину личной
    pmap["skipped"] += skipped
    return pmap


def unknown_enabled(pmap, enabled):
    """Включённые плагины из enabledPlugins пользователя, которых нет в [catalog]: карта их не выключает ни в одном
    окне. Плагины @agent-kit и встроенные @builtin не в счёт — их карта не трогает намеренно. enabled не словарь — []."""
    if not isinstance(enabled, dict):
        return []
    return sorted(p for p, on in enabled.items()
                  if isinstance(p, str) and on is not False and p not in pmap["plugins"]
                  and p.rsplit("@", 1)[-1].lower() not in (OWN_MARKET, "builtin"))


def window_key(pmap, name, direction):
    """Запись карты окна: своя по имени, иначе «direction» для окна направления; None — окна в карте нет (всё включено)."""
    if name in pmap["window"]:
        return name
    return "direction" if direction and "direction" in pmap["window"] else None


def window_apply(data, pmap, name, direction=False, guard=None):
    """Окно: enabledPlugins: false у плагинов каталога вне «оставить» и permissions.deny mcp__<сервер> у серверов вне
    «оставить»; с guard — ещё хук списка разрешённых MCP (mcp_gate_hook). Возвращает data; окна нет в карте — без
    изменений."""
    key = window_key(pmap, name, direction)
    if key is None:
        return data
    keep = pmap["window"][key]
    off = [p for p in pmap["plugins"] if p not in keep["plugins"]]
    if off:
        data.setdefault("enabledPlugins", {}).update({p: False for p in off})
    rules = data.setdefault("permissions", {}).setdefault("deny", [])
    rules.extend(r for r in (f"mcp__{m}" for m in pmap["mcp"] if m not in keep["mcp"]) if r not in rules)
    if guard:
        mcp_gate_hook(data, guard, keep["mcp"] + keep.get("mcp_extra", []))
    return data


def mcp_gate_hook(data, guard, allow):
    """Хук PreToolUse «mcp__.*» окна: hooks/mcp_gate.py рядом с guard (строгий guard.py проверенного дерева) через
    hooks/python.sh того же дерева, список allow — одним аргументом через запятую, onFailure "block". Прежний хук
    списка заменяется (повторная сборка без повторов). Нет mcp_gate.py или python.sh рядом с guard (дерево старее
    metis-1051 или его нет) — data без хука: проверенного файла для него нет."""
    hooks_dir = os.path.dirname(guard)
    gate, launcher = os.path.join(hooks_dir, MCP_GATE), os.path.join(hooks_dir, "python.sh")
    if not (os.path.isfile(gate) and os.path.isfile(launcher)):
        return data
    pre = data.setdefault("hooks", {}).setdefault("PreToolUse", [])
    pre[:] = [g for g in pre if not (g.get("matcher") == MCP_MATCHER
                                     and any(MCP_GATE in (h.get("command") or "") for h in g.get("hooks") or []))]
    cmd = " ".join(shlex.quote(x) for x in ("/bin/sh", launcher, gate, ",".join(dict.fromkeys(allow))))
    pre.append({"matcher": MCP_MATCHER, "hooks": [{"type": "command", "command": cmd, "timeout": 10,
                                                   "onFailure": "block"}]})
    return data


def role_deny(pmap, role):
    """mcp__<сервер> серверов каталога, которых роли не нужно; None — роли в карте нет (шапка как есть)."""
    entry = pmap["role"].get(role)
    return None if entry is None else [f"mcp__{m}" for m in pmap["mcp"] if m not in entry["mcp"]]


def role_header(text, pmap, role):
    """Текст роли с дописанными в disallowedTools шапки запретами карты (без повторов, прежние остаются). Роли нет в
    карте — text как есть. Строки disallowedTools в шапке нет — добавляется перед закрывающей «---». disallowedTools
    списком YAML (пустое значение и строки «- X» ниже, или «[…]») — ValueError: дописка через запятую сломала бы
    список; сборка оставляет шапку как есть и называет ошибку роли."""
    deny = role_deny(pmap, role)
    if not deny or not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 3)
    if end < 0:
        return text
    lines = text[4:end].split("\n")
    for i, ln in enumerate(lines):
        m = re.match(r"(disallowedTools\s*:)(.*)$", ln)
        if m:
            if not m.group(2).strip() or m.group(2).strip()[0] in "[-":
                raise ValueError("disallowedTools в шапке записан списком YAML — карта плагинов дописывает только в "
                                 "строку через запятую (disallowedTools: A, B); шапка не тронута")
            have = [x.strip() for x in m.group(2).split(",") if x.strip()]
            lines[i] = m.group(1) + " " + ", ".join(have + [d for d in deny if d not in have])
            break
    else:
        lines.append("disallowedTools: " + ", ".join(deny))
    return text[:4] + "\n".join(lines) + text[end:]
