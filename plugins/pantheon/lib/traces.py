"""pantheon traces — проверка личных следов до push (metis-0414): та же проверка, что CI check-traces.

  pantheon traces [--markers ФАЙЛ] [--repo ПАПКА]   проверить отслеживаемые файлы репозитория (по умолчанию — текущего)
  pantheon traces install-hook [--repo ПАПКА]       поставить pre-push хук, который зовёт эту проверку

Маркеры — файл вне репозитория: --markers, иначе PANTHEON_TRACE_MARKERS, иначе ~/.config/pantheon/trace-markers.txt
(по одному на строку, как секрет TRACE_MARKERS в CI). Сам поиск — scripts/check-traces.py, он один на CI и на машину.
В вывод идёт только «путь:строка», совпавший маркер не печатается.
Коды выхода: 0 — следов нет; 1 — найдены; 2 — отказ (нет файла маркеров, он пуст, не git, поиск не отработал):
«зелёным» отсутствие маркеров не считается, хук в этом случае тоже останавливает push.
"""
import os
import subprocess
import sys

PLUGIN = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SCRIPT = os.path.join(PLUGIN, "scripts", "check-traces.py")
DEFAULT_MARKERS = os.path.join(".config", "pantheon", "trace-markers.txt")  # от HOME
HOOK_TAG = "# pantheon traces (metis-0414)"
HOOK = f"""#!/bin/sh
{HOOK_TAG}: личные следы до push; поставлен `pantheon traces install-hook`
command -v pantheon >/dev/null 2>&1 || {{
    echo "pre-push: команды pantheon нет в PATH — личные следы не проверены, push остановлен" >&2
    exit 1
}}
exec pantheon traces
"""


def _err(text):
    print(f"pantheon traces: {text}", file=sys.stderr)


def _repo_root(path):
    r = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _parse(rest):
    opts, i = {}, 0
    while i < len(rest):
        if rest[i] in ("--markers", "--repo") and i + 1 < len(rest):
            opts[rest[i][2:]] = rest[i + 1]
            i += 2
        else:
            return None
    return opts


def check(opts):
    markers = opts.get("markers") or os.environ.get("PANTHEON_TRACE_MARKERS") \
        or os.path.join(os.environ.get("HOME") or os.path.expanduser("~"), DEFAULT_MARKERS)
    repo = _repo_root(opts.get("repo") or os.getcwd())
    if repo is None:
        _err("отказ — это не git-репозиторий (--repo ПАПКА)")
        return 2
    if not os.path.isfile(markers):
        _err(f"отказ — файла маркеров нет ({markers}): положите маркеры по одному на строку или укажите --markers; "
             "без них проверка ничего не значит")
        return 2
    r = subprocess.run([sys.executable, "-I", SCRIPT, "--markers", markers, "--repo", repo],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print("следов нет")
        return 0
    if r.returncode == 1:
        for ln in r.stdout.splitlines():
            print(":".join(ln.split(":")[:2]))  # путь:строка, маркер отсекаем
        _err("найдены личные следы (путь:строка выше) — push остановлен")
        return 1
    tail = (r.stderr.strip().splitlines() or ["без пояснения"])[-1]
    _err(f"отказ — проверка не отработала: {tail}")
    return 2


def install_hook(opts):
    repo = _repo_root(opts.get("repo") or os.getcwd())
    if repo is None:
        _err("отказ — это не git-репозиторий (--repo ПАПКА)")
        return 2
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--path-format=absolute", "--git-path", "hooks/pre-push"],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        _err("отказ — не нашёл папку хуков репозитория")
        return 2
    path = r.stdout.strip()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                ours = HOOK_TAG in fh.read()
        except (OSError, UnicodeDecodeError):
            ours = False
        if not ours:
            _err(f"отказ — {path} уже есть и не наш: добавьте туда вызов `pantheon traces` сами")
            return 2
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(HOOK)
    os.chmod(path, 0o755)
    print(f"хук поставлен: {path}")
    return 0


def main(rest):
    if rest[:1] == ["install-hook"]:
        opts = _parse(rest[1:])
        fn = install_hook
    else:
        opts = _parse(rest)
        fn = check
    if opts is None:
        _err("непонятные аргументы. " + (__doc__ or "").splitlines()[0])
        return 2
    return fn(opts)
