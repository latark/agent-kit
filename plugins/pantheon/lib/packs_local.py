"""Пакеты окон направлений — личные настройки пользователя, а не код плагина (решение владельца 12.11).

Пакет направления (схема А, metis-0933) — window.json, mcp.json, .claude-plugin/plugin.json и hooks/hooks.json в
~/.claude/pantheon/packs/<направление>/, рядом с approved.json того же направления. У каждого пользователя Пантеона
свои проекты, поэтому в репозитории пакетов нет: там только общий код пакетов (plugins/pantheon/packs/_bin).

Перенос (migrate): до выпуска 12.11 пакеты лежали в плагине, в packs/<направление>/. Плановый проход при сборке
окон (`pantheon domains build`) один раз копирует их из прежней версии плагина в кэше (папки версий рядом с нынешней)
в ~/.claude/pantheon/packs: окна не теряют хуков и серверов MCP. Берётся одна версия — самая новая, где пакеты есть.
Направление, у которого в новой папке уже есть хоть один файл пакета, не трогается; файл пишется только новым
(O_EXCL), существующее не затирается. Личные записи карты plugins-by-role.toml ([window.<направление>]) — туда же,
в ~/.claude/pantheon/plugins-by-role.toml, если этого файла ещё нет. После переноса — отметка .migrated.json: пакет,
который владелец потом удалил сам, из старой версии не вернётся. Вручную — `pantheon packs migrate [--from ПАПКА]`
(без отметки, тоже без затирания).

Модуль-лист: без состояния ядра (P), пути приходят аргументами; грузит его pantheon.py по пути файла.
"""

import json
import os
import re
import tomllib

PACK_FILES = ("window.json", "mcp.json", ".claude-plugin/plugin.json", "hooks/hooks.json")
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
MARK = ".migrated.json"
MAP_FILE = "plugins-by-role.toml"
FILE_LIMIT = 1 << 20


def has_pack(d):
    """Есть ли в папке d хоть один файл пакета (или ссылка на его месте)."""
    return any(os.path.lexists(os.path.join(d, f)) for f in PACK_FILES)


def names(packs):
    """Имена направлений с пакетом в папке packs (по образцу имени, без «_» и «.»)."""
    try:
        got = sorted(os.listdir(packs))
    except OSError:
        return []
    return [n for n in got if NAME.fullmatch(n) and has_pack(os.path.join(packs, n))]


def newest(packs):
    """Самое позднее время изменения в папке пакетов: сама папка, папки направлений и их файлы пакета; нет — 0. Для
    сборки окон по --if-changed: правка window.json или hooks.json пересобирает окно."""
    out = 0
    for p in [packs] + [os.path.join(packs, n, x) for n in names(packs) for x in ("",) + PACK_FILES]:
        try:
            out = max(out, os.lstat(p).st_mtime)
        except OSError:
            pass
    return out


def _version_key(name):
    parts = name.split(".")
    return (1, tuple(int(x) for x in parts)) if all(x.isdigit() for x in parts) else (0, (name,))


def legacy_root(plugin, src=None):
    """Корень плагина, откуда переносить: src (папка плагина с packs/ или сама папка пакетов) или самая новая из
    версий рядом с plugin (кэш: …/pantheon/<версия>) и сам plugin, где в packs/ есть хоть один пакет. → (папка пакетов,
    корень плагина или None) или (None, None)."""
    if src:
        src = os.path.abspath(os.path.expanduser(src))
        if names(os.path.join(src, "packs")):
            return os.path.join(src, "packs"), src
        return (src, None) if names(src) else (None, None)
    up = os.path.dirname(os.path.abspath(plugin))
    try:
        sibs = [os.path.join(up, n) for n in sorted(os.listdir(up), key=_version_key, reverse=True)]
    except OSError:
        sibs = []
    for root in sibs + [plugin]:
        if os.path.isdir(root) and not os.path.islink(root) and names(os.path.join(root, "packs")):
            return os.path.join(root, "packs"), root
    return None, None


def _read(p):
    """Байты обычного файла p (не ссылки) не больше FILE_LIMIT или None."""
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        data = os.read(fd, FILE_LIMIT + 1)
        return data if len(data) <= FILE_LIMIT else None
    finally:
        os.close(fd)


def _write_new(p, data):
    """Записать p, только если его нет (O_EXCL, ссылку не проходит). → записан ли."""
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return True


def map_entries(root, directions, base_windows):
    """Личные записи [window.<имя>] карты plugins-by-role.toml прежнего плагина root: имя — направление реестра
    (directions), которого нет в нынешней карте (base_windows). → {имя: {plugins, mcp}}."""
    try:
        with open(os.path.join(root, MAP_FILE), "rb") as fh:
            raw = tomllib.load(fh).get("window")
    except (OSError, ValueError):
        return {}
    out = {}
    for n, e in (raw.items() if isinstance(raw, dict) else ()):
        if n in directions and n not in base_windows and NAME.fullmatch(n) and isinstance(e, dict):
            keep = {k: e[k] for k in ("plugins", "mcp")
                    if isinstance(e.get(k), list) and all(isinstance(x, str) for x in e[k])}
            if keep:
                out[n] = keep
    return out


def map_text(entries, note):
    """Личная часть карты в TOML: строка-пометка и по таблице [window.<имя>] на запись."""
    rows = [f"# Личная часть карты plugins-by-role.toml: окна ваших направлений ({note}).",
            "# Запись [window.<направление>] заменяет запись карты плагина для этого окна; другие окна не берутся."]
    for n, e in sorted(entries.items()):
        rows += ["", f"[window.{n}]"] + [f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in sorted(e.items())]
    return "\n".join(rows) + "\n"


def migrate(packs, plugin, map_local, directions=(), base_windows=(), stamp="", src=None, mark=False):
    """Перенос пакетов и личных записей карты в данные пользователя (см. шапку). → {"from": корень или папка
    источника или None, "copied": [направления], "kept": [направления, где пакет уже есть], "map": [окна карты]}.
    mark — автоматический путь: отметка MARK в packs после переноса; уже есть отметка — ничего не делает."""
    res = {"from": None, "copied": [], "kept": [], "map": []}
    if mark and os.path.lexists(os.path.join(packs, MARK)):
        return res
    src_packs, root = legacy_root(plugin, src)
    if src_packs is None:
        if mark:  # прежних пакетов нет (новая установка, кэш очищен): искать их на каждой сборке незачем
            _write_new(os.path.join(packs, MARK), json.dumps({**res, "at": stamp}, ensure_ascii=False).encode())
        return res
    res["from"] = root or src_packs
    for n in names(src_packs):
        dst = os.path.join(packs, n)
        if has_pack(dst):
            res["kept"].append(n)
            continue
        wrote = False
        for f in PACK_FILES:
            data = _read(os.path.join(src_packs, n, f))
            if data is not None:
                wrote = _write_new(os.path.join(dst, f), data) or wrote
        if wrote:
            res["copied"].append(n)
    entries = map_entries(root, set(directions), set(base_windows)) if root and map_local else {}
    # личная карта, которая уже есть, не затирается: _write_new пишет только новый файл (O_EXCL)
    if entries and _write_new(map_local, map_text(entries, f"перенесено из {res['from']} {stamp}").encode()):
        res["map"] = sorted(entries)
    if mark:
        _write_new(os.path.join(packs, MARK), json.dumps({**res, "at": stamp}, ensure_ascii=False).encode())
    return res


def report(res, tilde, packs, map_local, quiet=False):
    """Строки итога migrate для человека. quiet (шаг сборки окон) — только когда что-то перенесено."""
    if quiet and not (res["copied"] or res["map"]):
        return []
    out = []
    if res["from"] is not None:
        out.append(f"пакеты направлений: источник {tilde(res['from'])}")
    out += [f"перенесён пакет {n} → {tilde(os.path.join(packs, n))}" for n in res["copied"]]
    out += [f"пакет {n} уже есть в {tilde(os.path.join(packs, n))} — не тронут" for n in res["kept"]]
    if res["map"]:
        out.append(f"личная карта плагинов {tilde(map_local)}: окна {', '.join(res['map'])}")
    return out
