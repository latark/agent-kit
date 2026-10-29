"""Карта «окно или роль × плагин и MCP» (metis-0238): разбор plugins-by-role.toml и применение к настройкам окна и шапке роли.

Ядро защит (metis-0598, решение владельца 30.10): PR, который меняет модуль или карту, сливает владелец. Карта задаёт,
какие плагины и MCP окну и роли недоступны (enabledPlugins: false и правила permissions.deny mcp__<сервер> окна;
mcp__<сервер> в disallowedTools шапки роли). Модуль без состояния и ввода-вывода, кроме чтения файла карты: его
грузит pantheon.py по пути файла (python3 -I не кладёт папку скрипта в путь импорта).

Запись карты — «оставить»: названное остаётся, остальное из [catalog] выключается. Окна или роли, которых в карте нет, и
плагины и MCP вне [catalog] не трогаются — безопасный дефолт «всё включено».
"""

import re
import tomllib

MCP_NAME = re.compile(r"[A-Za-z0-9_-]+")
PLUGIN_ID = re.compile(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+")
# Каталог, чьи плагины карта не выключает никогда: agent-kit — сами защиты (guard), Пантеон и project-tools. Такой
# плагин в [catalog] — ValueError: «оставить» без него выключило бы guard и pantheon во всех окнах.
OWN_MARKET = "agent-kit"


def load(path):
    """Карта из файла. ValueError с причиной: нет файла, битый TOML, не тот тип, плагин @agent-kit в каталоге, ключ
    «оставить» вне каталога (опечатка молча выключила бы нужное)."""
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
    out = {"plugins": list(plugins), "mcp": list(mcp), "window": {}, "role": {}}
    for kind, keys in (("window", ("plugins", "mcp")), ("role", ("mcp",))):
        section = raw.get(kind, {})
        if not isinstance(section, dict):
            raise ValueError(f"карта плагинов: [{kind}] — таблица")
        for name, entry in section.items():
            if not isinstance(entry, dict) or set(entry) - set(keys):
                raise ValueError(f"карта плагинов: [{kind}.{name}] — только ключи {', '.join(keys)}")
            keep = {}
            for k in keys:
                vals = entry.get(k)
                if not isinstance(vals, list) or not all(isinstance(x, str) for x in vals):
                    raise ValueError(f"карта плагинов: [{kind}.{name}] {k} — список строк (пустой — «ничего»)")
                unknown = [x for x in vals if x not in out[k]]
                if unknown:
                    raise ValueError(f"карта плагинов: [{kind}.{name}] {k}: {unknown} нет в [catalog]")
                keep[k] = list(vals)
            out[kind][name] = keep
    return out


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


def window_apply(data, pmap, name, direction=False):
    """Окно: enabledPlugins: false у плагинов каталога вне «оставить» и permissions.deny mcp__<сервер> у серверов вне
    «оставить». Возвращает data; окна нет в карте — без изменений."""
    key = window_key(pmap, name, direction)
    if key is None:
        return data
    keep = pmap["window"][key]
    off = [p for p in pmap["plugins"] if p not in keep["plugins"]]
    if off:
        data.setdefault("enabledPlugins", {}).update({p: False for p in off})
    rules = data.setdefault("permissions", {}).setdefault("deny", [])
    rules.extend(r for r in (f"mcp__{m}" for m in pmap["mcp"] if m not in keep["mcp"]) if r not in rules)
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
