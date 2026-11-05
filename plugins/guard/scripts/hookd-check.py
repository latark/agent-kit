#!/usr/bin/env python3
"""Проверки службы демона хуков guard для владельца (metis-0811). Зовёт hookd-install.sh — при установке и в --check:
  python.sh hookd-check.py tcc <итог пробы.json> <pantheon-hookd>   доступ службы к папкам под TCC и как его дать
  python.sh hookd-check.py windows                                 ни одно окно Пантеона не пишет в ~/.cache/pantheon/hookd
                                                                   и не открывает его сокеты (F7)
Код 0 — в порядке; 1 — есть что исправить (что и как — в выводе, итог последней строкой); 64 — плохие аргументы.

tcc. Итог пишет `daemon.py --tcc-probe`, запущенный разовым заданием launchd через pantheon-hookd — тот же
ответственный процесс, что у службы, а не текущий терминал. Где доступа нет, демон отвечает «F perm», и вызов идёт
медленным путём с правами окна: защита не слабеет, вызов дольше. Отказ macOS помнит и второй раз не спрашивает —
поэтому вывод даёт команду, которая открывает «Конфиденциальность → Файлы и папки», и перезапуск службы после
разрешения. Ответственный процесс — не pantheon-hookd (служба поставлена старой командой через /bin/sh) — тоже
находка: разрешение тогда у Python.app, и обновление Python его сбросит.

windows. Окна ролей собирает `pantheon domains build` в ~/.local/state/pantheon/settings/*.json (и run/*.json —
файлы запущенных сессий). Запись в папку демона дала бы окну подменить клиент вместе с его меткой SHA-256 — то есть
ответ «пропустить» на всё, а сокет — говорить с демоном мимо хука. Проверяется готовый результат сборки, а не код
сборки: так видны и разрешения grants.toml, и sandbox_write policy.toml. Нарушение — allowWrite или allowUnixSockets,
которые накрывают папку (она сама, папка выше или путь внутри; шаблон — по части до первого знака шаблона) и не
перекрыты denyWrite; allowAllUnixSockets. Правки Write и Edit в эту папку держит protect-config guard (tests/test_guard).
"""
import glob
import json
import os
import plistlib
import sys

HOME = os.environ.get("HOME") or ""
# служба TCC (для tccutil) по имени папки в итоге пробы; у iCloud Drive своей строки нет — только переключатель
TCC_SERVICE = {"Desktop": "SystemPolicyDesktopFolder", "Documents": "SystemPolicyDocumentsFolder",
               "Downloads": "SystemPolicyDownloadsFolder"}
PANE_FILES = "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders"
PANE_ALL = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
LABEL = "pantheon.svc.hookd"
GLOB_CHARS = "*?[{"


def bundle_id(exe):
    """CFBundleIdentifier пакета .app, которому принадлежит exe; не пакет или не прочесть — ''."""
    k = exe.find(".app/Contents/MacOS/")
    if k < 0:
        return ""
    try:
        with open(exe[:k] + ".app/Contents/Info.plist", "rb") as fh:
            v = plistlib.load(fh).get("CFBundleIdentifier")
        return v if isinstance(v, str) else ""
    except (OSError, ValueError, AttributeError):
        return ""


def tcc(result, svc):
    try:
        with open(result, encoding="utf-8") as fh:
            res = json.load(fh)
        dirs = res["dirs"]
        if not isinstance(dirs, dict):
            raise ValueError("dirs")
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"итог пробы {result} не прочесть: {e}")
        return 1
    who = res.get("responsible") or ""
    print(f"Доступ службы {LABEL} к папкам (проба под launchd, ответственный процесс: {who or 'не узнать'}):")
    bad = []
    for name, st in dirs.items():
        if st == "ok":
            word = "есть"
        elif st == "missing":
            word = "папки нет — проверять нечего"
        elif st == "denied":
            word = "НЕТ — macOS отказала"
            bad.append(name)
        else:
            word = f"НЕ ПРОЧЕСТЬ ({st})"
            bad.append(name)
        print(f"  {name:<13} {word}")
    problems = []
    if who and os.path.realpath(who) != os.path.realpath(svc):
        problems.append("ответственный процесс не pantheon-hookd")
        print(f"Разрешение macOS даёт процессу {who}, а не {svc}: служба поставлена старой командой или проба шла "
              "не через pantheon-hookd. После обновления этой программы разрешение слетит. Переставить службу: "
              "/bin/sh <дерево guard>/scripts/hookd-install.sh")
    if bad:
        problems.append("нет доступа: " + ", ".join(bad))
        uid = os.getuid()
        print("Где доступа нет, демон отвечает «F perm», и вызов идёт медленным путём: защита та же, вызов дольше.")
        print("Окно macOS второй раз не появится — отказ записан. Разрешить потом:")
        print(f'  1. open "{PANE_FILES}"')
        print("     В списке «Файлы и папки» найти pantheon-hookd и включить нужные папки. Если его там нет —")
        print(f'     open "{PANE_ALL}" («Полный доступ к диску»), кнопка «+», ⌘⇧G и путь {svc}')
        print(f"  2. Перезапустить службу: launchctl kickstart -k gui/{uid}/{LABEL}")
        print("  3. Проверить: /bin/sh <дерево guard>/scripts/hookd-install.sh --check")
        bid = bundle_id(who)
        svcs = [TCC_SERVICE[n] for n in bad if n in TCC_SERVICE]
        if bid and svcs:
            print(f"  Или заново получить окно macOS — сбросить ответ для {bid}: "
                  + "; ".join(f"tccutil reset {s} {bid}" for s in svcs)
                  + ". Сбросит и другим заданиям launchd на этой программе; затем --check спросит снова.")
        else:
            print("  tccutil тут не поможет: он сбрасывает ответ по идентификатору пакета, а у pantheon-hookd его нет; "
                  "`tccutil reset <служба>` без идентификатора сбросил бы ответы всем программам Mac.")
    if problems:
        print("итог: " + "; ".join(problems))
        return 1
    print("итог: доступ ко всем папкам есть")
    return 0


def _home(x, home):
    """«~» и «~/…» — от HOME проверки (тесты подменяют его аргументом), а не от HOME процесса."""
    return home + x[1:] if x == "~" or x.startswith("~/") else x


def _covers(entry, target, home=None):
    """Запись песочницы entry накрывает target: та же папка, папка выше или путь внутри. Шаблон — по части до первого
    знака шаблона (с запасом в сторону «накрывает»)."""
    if not isinstance(entry, str) or not entry:
        return False
    k = min([entry.find(c) for c in GLOB_CHARS if c in entry] or [len(entry)])
    base = entry[:k]
    if k < len(entry):
        base = base[:base.rfind("/") + 1] if "/" in base else ""
    base = _home(base, home if home is not None else HOME)
    if not base.startswith("/"):
        return False
    b = os.path.realpath(base).rstrip("/") or "/"
    t = target.rstrip("/")
    return b == t or t.startswith(b.rstrip("/") + "/") or b.startswith(t + "/")


def _denied(deny, target, home=None):
    """denyWrite перекрывает target целиком: та же папка или папка выше (без шаблонов)."""
    t = target.rstrip("/")
    for x in deny or []:
        if not isinstance(x, str) or any(c in x for c in GLOB_CHARS):
            continue
        b = _home(x, home if home is not None else HOME)
        if not b.startswith("/"):
            continue
        b = os.path.realpath(b).rstrip("/") or "/"
        if b == t or t.startswith(b.rstrip("/") + "/"):
            return True
    return False


def window_problems(data, target, home=None):
    """Нарушения F7 в настройках одного окна: список строк."""
    sb = data.get("sandbox") if isinstance(data, dict) else None
    if not isinstance(sb, dict):
        return []
    fs = sb.get("filesystem") if isinstance(sb.get("filesystem"), dict) else {}
    net = sb.get("network") if isinstance(sb.get("network"), dict) else {}
    out = []
    if not _denied(fs.get("denyWrite"), target, home):
        out += [f"allowWrite {x}" for x in fs.get("allowWrite") or [] if _covers(x, target, home)]
    out += [f"allowUnixSockets {x}" for x in net.get("allowUnixSockets") or [] if _covers(x, target, home)]
    if net.get("allowAllUnixSockets") is True:
        out.append("allowAllUnixSockets: true")
    return out


def windows(state=None, home=None):
    home = home if home is not None else HOME
    state = state or os.environ.get("PANTHEON_STATE") or os.path.join(home, ".local", "state", "pantheon")
    target = os.path.realpath(os.path.join(home, ".cache", "pantheon", "hookd"))
    sdir = os.path.join(state, "settings")
    files = sorted(glob.glob(os.path.join(sdir, "*.json")) + glob.glob(os.path.join(sdir, "run", "*.json")))
    if not files:
        print(f"окна Пантеона: файлов настроек нет ({sdir}) — проверять нечего")
        return 0
    bad = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            bad.append(f"{f}: не прочесть ({e})")
            continue
        bad += [f"{os.path.relpath(f, sdir)}: {x}" for x in window_problems(data, target, home)]
    if bad:
        for x in bad:
            print("  " + x)
        print(f"итог: окнам открыта папка демона {target} ({len(bad)}) — окно с записью туда подменит клиент и его "
              "метку; убрать разрешение из grants.toml или policy.toml (sandbox_write) и пересобрать окна "
              "(pantheon domains build)")
        return 1
    print(f"окна Пантеона: {len(files)} файлов настроек, ни одному не дана запись или сокет в {target}")
    return 0


def main(argv):
    if len(argv) == 3 and argv[0] == "tcc":
        return tcc(argv[1], argv[2])
    if argv == ["windows"]:
        return windows()
    print("hookd-check: нужно tcc <итог.json> <pantheon-hookd> | windows", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
