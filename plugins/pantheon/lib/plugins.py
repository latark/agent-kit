"""Пантеон: pantheon plugins update|accept — новые версии плагинов agent-kit (metis-0052) и принятие
установленного дерева как проверенного (verified.json, metis-0321).

Вынесено из pantheon.py (metis-0586) без изменения поведения. P — модуль pantheon: его ставит загрузчик
pantheon._attach до выполнения этого файла, имена из __all__ становятся именами pantheon.
"""
import contextlib
import json
import os
import shutil
import subprocess
import sys

__all__ = [
    "_unchecked_path", "verified_write", "_plugins_journal", "_version_newer", "_plugins_installed", "_catalog_root",
    "_plugins_catalog", "_plugins_respawn_mark", "_plugin_install", "plugins_update", "_memory_pressure",
    "_current_sync", "_release_problem", "_gh_bin", "_main_ci_check", "_plugins_update", "plugins_accept",
    "plugins_cmd",
]


def _unchecked_path():
    """Запись критической ветки plugins-update: что встало непроверенным (для разбора). Решений по ней не принимают —
    решает только verified.json."""
    return P.path("plugins", "unchecked.json")


def verified_write(name, root, digest, version, by):
    """digest — хеш, с которым дерево сверили (а не пересчёт: между сверкой и записью дерево могли подменить)."""
    data = P.read_json(P._verified_path(), {})
    data = data if isinstance(data, dict) else {}
    data[name] = {"hash": digest, "path": os.path.realpath(root), "version": version, "at": P.stamp(), "by": by}
    P.write_json(P._verified_path(), data)


def _plugins_journal(line):
    os.makedirs(P.path("plugins"), exist_ok=True)
    with open(P.path("plugins", "journal.log"), "a", encoding="utf-8") as fh:
        fh.write(f"{P.stamp()} {line}\n")


def _version_newer(new, old):
    """Новее ли версия каталога установленной: сравнение кортежей чисел; не разобрать — новая, если строки разные."""
    try:
        return tuple(int(x) for x in str(new).split(".")) > tuple(int(x) for x in str(old).split("."))
    except ValueError:
        return str(new) != str(old)


def _known_version(name, installed_version):
    """«Старая» версия для сравнения с каталогом (metis-0922): последняя проверенная по verified.json, а не установленная.
    Claude Code 2.1.319 сам ставит выпуск при `marketplace update`, и установленная уже равна каталогу, а живой код
    (current, окна) стоит на проверенной. Записи нет или версия в ней не разбирается — установленная."""
    rec = P.verified_record(name) or {}
    ver = rec.get("version")
    if isinstance(ver, str) and ver and all(x.isdigit() for x in ver.split(".")):
        return ver
    return installed_version


def _plugins_installed():
    """{имя: {version, installPath}} — плагины agent-kit уровня пользователя по `claude plugin list --json`; None — сбой."""
    try:
        r = subprocess.run([P.claude_bin(), "plugin", "list", "--json"], env=P.claude_env(), capture_output=True, text=True, timeout=120)
        data = json.loads(r.stdout or "null")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if isinstance(data, dict):
        data = data.get("plugins")
    if r.returncode != 0 or not isinstance(data, list):
        return None
    out = {}
    for p in data:
        if not isinstance(p, dict) or p.get("scope") != "user":
            continue
        name, _, mkt = str(p.get("id", "")).partition("@")
        if mkt == P.MARKETPLACE and name:
            out[name] = {"version": str(p.get("version", "")), "installPath": p.get("installPath")}
    return out


def _catalog_root():
    """Корень клона каталога agent-kit (installLocation из known_marketplaces.json, иначе папка по умолчанию)."""
    known = P.read_json(os.path.join(P.HOME, ".claude", "plugins", "known_marketplaces.json"))
    entry = known.get(P.MARKETPLACE) if isinstance(known, dict) else None
    loc = entry.get("installLocation") if isinstance(entry, dict) else None
    if not isinstance(loc, str) or not os.path.isdir(loc):
        loc = os.path.join(P.HOME, ".claude", "plugins", "marketplaces", P.MARKETPLACE)
    return os.path.realpath(loc)


def _plugins_catalog():
    """{имя: (версия, папка плагина)} из клона каталога agent-kit."""
    root = _catalog_root()
    mkt = P.read_json(os.path.join(root, ".claude-plugin", "marketplace.json"))
    out = {}
    for p in (mkt.get("plugins") or []) if isinstance(mkt, dict) else []:
        if not isinstance(p, dict) or not isinstance(p.get("source"), str) or not p.get("name"):
            continue
        d = os.path.realpath(os.path.join(root, p["source"]))
        if not d.startswith(root + os.sep):
            continue  # источник вне клона каталога (абсолютный путь, ../) — не наш
        meta = P.read_json(os.path.join(d, ".claude-plugin", "plugin.json"))
        ver = meta.get("version") if isinstance(meta, dict) else None
        if ver:
            out[str(p["name"])] = (str(ver), d)
    return out


def _plugins_respawn_mark(name):
    """metis-0181: отметка «нужен перезапуск» для тика (watch.plugins_respawn). since — время последней установки:
    окна, поднятые раньше, тик перезапускает, когда они свободны; done — уже перезапущенные сессии, новая установка
    его обнуляет (их версия этого плагина тоже старая)."""
    with P.lock("plugins-respawn"):
        cur = P.read_json(P.path("plugins", "respawn.json"), {})
        cur = cur if isinstance(cur, dict) else {}
        plugins = sorted({str(x) for x in cur.get("plugins") or []} | {name})
        P.write_json(P.path("plugins", "respawn.json"), {"since": P.now(), "at": P.stamp(), "plugins": plugins, "done": []})


def _plugin_install(name, old, new, quiet, digest):
    """claude plugin update без -y (новая команда установки в каталоге должна требовать человека) и сверка того, что
    встало, с выпущенным деревом каталога: версия и хеш дерева installPath."""
    try:
        r = subprocess.run([P.claude_bin(), "plugin", "update", f"{name}@{P.MARKETPLACE}", "-s", "user"],
                           env=P.claude_env(), capture_output=True, text=True, timeout=P.PLUGIN_INSTALL_TIMEOUT)
        ok = r.returncode == 0
        why = f"код {r.returncode}: {' '.join((r.stderr or r.stdout or '').split())[:200]}"
    except (OSError, subprocess.TimeoutExpired) as e:
        ok, why = False, type(e).__name__
    row = (_plugins_installed() or {}).get(name) or {}
    got = row.get("version")
    if got == new and P._tree_hash(row.get("installPath")) == digest:
        # разрешение: это дерево прошло CI до слияния и совпало с записью выпуска — живой код и окна идут только на
        # него (metis-0321)
        verified_write(name, row["installPath"], digest, new, "plugins-update")
        um = P.read_json(_unchecked_path(), {}) or {}
        if um.pop(name, None) is not None:
            P.write_json(_unchecked_path(), um)
        if name == "pantheon" and row.get("installPath"):
            # живой код тика и команды pantheon — только проверенная и вставшая версия (metis-0321)
            try:
                P.link_current(os.path.realpath(row["installPath"]))
            except OSError as e:
                P.alert(f"pantheon: current не перевесилась на {row['installPath']}: {type(e).__name__} {e}", "plugins-update")
        _plugins_journal(f"{name} {old} → {new}: обновлён")
        _plugins_respawn_mark(name)
        P.alert(f"обновлён {name} {old} → {new}, плановый проход перезапустит свободные окна (Зевса — вы сами: pantheon start zeus "
              "--restart); окно, готовое раньше: pantheon saved --by <имя> --state <путь>", "plugins-update")
        if not quiet:
            print(f"{name}: обновлён {old} → {new}")
        return 0
    if got == old or (got is None and not ok):
        # ничего не встало — пробуем на следующих проходах; тревога одна на версию
        if ok:
            why = f"после update версия {got}, а не {new}"
        _plugins_journal(f"{name} {old} → {new}: установка не удалась ({why})")
        P.alert_once(f"plugins-update-{name}", new, f"{name} {new}: claude plugin update не поставил выпуск "
                   f"({why}). Руками: claude plugin update {name}@{P.MARKETPLACE}", "plugins-update")
        if not quiet:
            print(f"{name}: {new} — установка не удалась ({why})")
        return P.ALERTED
    # встало не то, что выпущено: другая версия или другое содержимое (update сам обновил каталог)
    bad = P._tree_hash(row.get("installPath"))
    if bad:  # запись для разбора; живой код его и так не возьмёт — хеша нет в verified.json
        um = P.read_json(_unchecked_path(), {}) or {}
        um[name] = {"hash": bad, "version": got, "path": os.path.realpath(row.get("installPath")), "at": P.stamp()}
        P.write_json(_unchecked_path(), um)
    seen = got or "неизвестна"
    _plugins_journal(f"{name} {old} → {seen}: встала непроверенная версия (выпуск {new}, хеш {digest})")
    text = (f"встала непроверенная версия {name} {seen} (выпуск {new}) — живой код и окна остаются на последнем "
            "проверенном дереве; что делать — README agent-kit, «Живой код»")
    P.alert("КРИТИЧНО: " + text, "plugins-update")
    P.notify(text, title="Пантеон · критично", group="critical")
    if not quiet:
        print(f"{name}: КРИТИЧНО — {text}")
    return P.ALERTED


def plugins_update(quiet=False):
    with P.lock("plugins-update", block=False) as got:
        return _plugins_update(quiet) if got else 0


def _memory_pressure():
    """Давление памяти: сначала сам sysctl; не прочитался (окно роли) — свежий замер планового прохода (metis-0537)."""
    level = P._memory_pressure_direct()
    if level is None:
        v = P.probe_value("pressure")
        level = v if v in (1, 2, 4) else None
    return level


def _current_sync():
    """Новее нет (например, версию поставили руками `claude plugin update`): current должна вести в установленную папку.
    Отстала или повисла — перевесить на installed_dir (версия та же, что у поставленной); сбой — тревога."""
    want = P.installed_dir("pantheon")  # проверенное дерево или последнее проверенное; тревогу даёт installed_dir
    if not want:
        return
    try:
        if os.path.realpath(P.CURRENT) == want and os.path.isdir(P.CURRENT):
            return
        P.link_current(want)
        _plugins_journal(f"pantheon: current перевешена на установленную {want}")
    except OSError as e:
        P.alert(f"pantheon: current не перевесилась на {want}: {type(e).__name__} {e}", "plugins-update")


def _release_problem(name, ver, digest):
    """metis-0512 (вариант Б): номер версии поднимает workflow release на main после слияния и пишет
    .claude-plugin/releases.json — {"v": 1, "plugins": {имя: {"version", "tree"}}}, tree — _tree_hash папки плагина
    в коммите выпуска. Между слиянием PR и коммитом выпуска в каталоге новый код под прошлым номером: ставить его
    нельзя (номер уже занят другим деревом). Поэтому новая версия ставится, только если запись выпуска совпала с
    каталогом — та же версия и то же дерево (digest). Текст причины или None. Файла нет — тоже причина: локального
    прогона тестов больше нет, и без записи выпуска не видно, что дерево прошло CI и workflow release. Клон каталога
    неглубокий, поэтому сверка по записи, а не по истории git."""
    p = os.path.join(_catalog_root(), ".claude-plugin", "releases.json")
    try:
        if not os.path.lexists(p):
            raise ValueError("файла нет")
        if os.path.islink(p) or not os.path.isfile(p):
            raise ValueError("не обычный файл")
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        why = f"releases.json каталога не разобрать ({e}) — выпуск не сверить"
    else:
        rec = data.get("plugins", {}).get(name) if isinstance(data, dict) and data.get("v") == 1 \
            and isinstance(data.get("plugins"), dict) else None
        if not isinstance(rec, dict):
            why = "в releases.json каталога нет записи выпуска — слито, выпуска ещё нет"
        elif rec.get("version") != ver:
            why = f"слито, выпуска ещё нет: в releases.json {rec.get('version')!r}, в каталоге {ver}"
        elif not digest or rec.get("tree") != digest:
            why = f"слито после выпуска {ver}: дерево каталога не то, что выпущено, — жду следующий выпуск"
        else:
            return None
    # строка в журнал выпусков — один раз на состояние, а не на каждый плановый проход
    seen = P.read_json(P.path("plugins", "unreleased.json"))
    seen = seen if isinstance(seen, dict) else {}
    if seen.get(name) != f"{ver} {why}":
        _plugins_journal(f"{name} {ver}: не ставлю — {why}")
        with contextlib.suppress(OSError):
            P.write_json(P.path("plugins", "unreleased.json"), {**seen, name: f"{ver} {why}"})
    return why


def _gh_bin():
    return shutil.which("gh", path=(os.environ.get("PATH") or "") + ":/opt/homebrew/bin:/usr/local/bin")


def _main_ci_check():
    """metis-0587 (вариант Б): выпуск не стопорится, но красный tests на main не должен пройти молча. Берём последний
    завершённый прогон tests.yml на main (`gh run list`): failure — одна тревога на коммит (alert_once по headSha) со
    ссылкой на прогон. Нет прогонов, startup_failure (Actions не стартовали, биллинг), cancelled, gh нет или упал —
    не тревога: строка в журнал выпусков раз в день. Сбой gh тик не ломает."""
    why = None
    try:
        gh = _gh_bin()
        if not gh:
            raise OSError("gh не найден")
        r = subprocess.run([gh, "run", "list", "--repo", "latark/agent-kit", "--workflow", "tests.yml",
                            "--branch", "main", "--limit", "10", "--json", "headSha,conclusion,status,url"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise OSError(f"gh код {r.returncode}")
        runs = json.loads(r.stdout)
        done = [x for x in runs if isinstance(x, dict) and x.get("status") == "completed"] \
            if isinstance(runs, list) else []
        if not done:
            why = "нет завершённых прогонов tests на main"
        elif done[0].get("conclusion") == "failure":
            sha, url = str(done[0].get("headSha") or "?"), done[0].get("url") or ""
            P.alert_once("main-ci-red", sha, f"pantheon: tests красные на main, коммит {sha[:10]} — {url} "
                       "(выпуск идёт; разобрать и чинить следующим PR)", "plugins-update")
        elif done[0].get("conclusion") != "success":
            why = f"последний прогон tests на main: {done[0].get('conclusion')!r} — Actions не отработали"
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        why = f"статус tests на main не прочитан: {type(e).__name__} {e}"
    if why:
        day = P.stamp()[:10]
        mark = P.path("plugins", "ci-nodata")
        with contextlib.suppress(OSError):
            if open(mark).read() == day:
                return
        _plugins_journal(f"tests на main: {why}")
        with contextlib.suppress(OSError):
            os.makedirs(P.path("plugins"), exist_ok=True)
            open(mark, "w").write(day)


def _plugins_update(quiet):
    try:
        ok = subprocess.run([P.claude_bin(), "plugin", "marketplace", "update", P.MARKETPLACE],
                            env=P.claude_env(), capture_output=True, text=True,
                            timeout=P.PLUGINS_CATALOG_TIMEOUT).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if not ok:  # нет сети или каталог недоступен — подождём следующего раза, без тревоги
        if not quiet:
            print(f"каталог {P.MARKETPLACE} не обновился — попробую в следующий раз")
        return P.TEMPFAIL
    installed = _plugins_installed()
    if installed is None:
        print("pantheon plugins update: не прочитал claude plugin list --json", file=sys.stderr)
        return 1
    catalog = _plugins_catalog()
    rc = 0
    checked = False
    for name in sorted(installed):
        if name not in catalog:
            continue
        old, (new, src) = _known_version(name, installed[name]["version"]), catalog[name]
        if _version_newer(new, old) and not checked:  # новый выпуск: заодно смотрим tests на main (metis-0587)
            checked = True
            _main_ci_check()
        if not _version_newer(new, old):
            if name == "pantheon":
                _current_sync()
            if not quiet:
                print(f"{name}: {old}, новее нет")
            continue
        digest = P._tree_hash(src)
        why = _release_problem(name, new, digest)
        if why:  # metis-0512: слито в main, а workflow release номер ещё не поднял — код не ставим
            if not quiet:
                print(f"{name}: {new} не ставлю — {why}")
            continue
        rc = max(rc, _plugin_install(name, old, new, quiet, digest))
    return rc


def plugins_accept(names, new_only=False):
    """Ваше «да» установленному дереву без прохода тестов (новая машина, первый выпуск с verified.json, ручная
    переустановка): его хеш и путь — в verified.json. Только руками: задача тика эту команду не запускает, окна ролей
    в состояние не пишут. new_only (--new, pantheon-setup) — только плагины, о которых записи ещё нет."""
    rc = 0
    for name in names or ["guard", "pantheon"]:
        if new_only and P.verified_record(name):
            continue
        raw = P.installed_dir(name, checked=False)
        if not raw:
            # --new (pantheon-setup): неустановленный плагин — не ошибка этого шага, установку проверяет свой шаг
            print(f"pantheon plugins accept: {name}@{P.MARKETPLACE} не установлен в ~/.claude/plugins/cache", file=sys.stderr)
            rc = rc if new_only else 1
            continue
        version = (P.read_json(os.path.join(raw, ".claude-plugin", "plugin.json"), {}) or {}).get("version", "?")
        verified_write(name, raw, P._tree_hash(raw), version, "accept")
        _plugins_journal(f"{name} {version}: принято руками (pantheon plugins accept) — {raw}")
        print(f"{name}: {version} принят — {raw.replace(P.HOME, '~')}")
        if name == "pantheon":
            P.link_current(raw)
    return rc


def plugins_cmd(rest):
    if rest[:1] == ["update"] and all(a == "--quiet" for a in rest[1:]):
        return plugins_update(quiet="--quiet" in rest)
    if rest[:1] == ["accept"] and all(a in ("guard", "pantheon", "--new") for a in rest[1:]):
        return plugins_accept([a for a in rest[1:] if a != "--new"], new_only="--new" in rest)
    print("pantheon plugins: update [--quiet] | accept [--new] [guard] [pantheon]", file=sys.stderr)
    return 2
