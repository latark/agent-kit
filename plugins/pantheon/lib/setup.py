#!/usr/bin/env python3
"""pantheon-setup: установка Пантеона для нового человека на macOS (запускает bin/pantheon-setup, который заранее
ставит uv и Python 3.14 и вызывает этот файл: `setup.py --python <путь> [--codex|--no-codex] [--markers ФАЙЛ]`).

Шаги по порядку, у каждого строка итога «ок / пропуск / не вышло: почему». До любых изменений две проверки:
Пантеон уже есть (отказ, ничего не меняем) и нет Claude Code (отказ). Режим `--add codex` — только шаг Codex на
готовой установке. К системе ходит только через platform_macos.py. Пути — от HOME и PANTHEON_HOME/PANTHEON_STATE.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

LIB = os.path.dirname(os.path.realpath(__file__))
PLUGIN = os.path.dirname(LIB)
HOME = os.path.expanduser("~")
AI_HOME = os.path.join(HOME, "ai")
PANTHEON = os.path.realpath(os.environ.get("PANTHEON_HOME") or os.path.join(AI_HOME, "pantheon"))
AGENTS = os.path.join(HOME, ".claude", "agents")
DEFAULT_MARKET = "agent-kit"
PLUGINS = ("guard", "pantheon", "project-tools")
YES = ("да", "д", "y", "yes")

failures = []


def _load(name, path):
    """Модуль из файла по пути: `python3 -I` не кладёт lib в sys.path."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PLAT = _load("pantheon_platform_macos", os.path.join(LIB, "platform_macos.py"))
PCONFIG = _load("pantheon_pconfig", os.path.join(LIB, "pconfig.py"))


def report(step, status, text=""):
    """status: ок | пропуск | не вышло."""
    if status == "не вышло":
        failures.append(step)
    line = f"[{status}] {step}" + (f": {text}" if text else "")
    print(line, flush=True)


def ask(question):
    """Вопрос в stdin. Конец ввода или любой ответ, кроме «да», — нет."""
    print(f"{question} [да/нет, по умолчанию нет] ", end="", flush=True)
    try:
        ans = input().strip().lower()
    except (EOFError, OSError):
        ans = ""
    print(flush=True)
    return ans in YES


ROLE_ENV = ("PANTHEON_ROLE", "PANTHEON_SESSION", "CLAUDE_CODE_AGENT", "PANTHEON_ORIGIN")


def claude_env():
    """Окружение для claude без переменных роли окна (как pantheon.claude_env): общий daemon не унаследует роль."""
    return {k: v for k, v in os.environ.items() if k not in ROLE_ENV}


def run(argv, env=None, timeout=900, **kw):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(argv, 127, "", str(e))


def last_line(r):
    out = (r.stderr or "").strip() or (r.stdout or "").strip()
    return out.splitlines()[-1] if out else f"код {r.returncode}"


def clone_root():
    r = run(["git", "-C", PLUGIN, "rev-parse", "--show-toplevel"])
    return os.path.realpath(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def market_name(root):
    try:
        with open(os.path.join(root, ".claude-plugin", "marketplace.json"), encoding="utf-8") as fh:
            return json.load(fh).get("name") or DEFAULT_MARKET
    except (OSError, ValueError):
        return DEFAULT_MARKET


def child_env(py):
    env = dict(os.environ)
    env["PANTHEON_HOME"] = PANTHEON
    env["PANTHEON_PYTHON"] = py
    return env


def pantheon_script():
    """pantheon.py из клона маркетплейса; нет — из этого клона. Куда смотрит ссылка current, решает сам install:
    на установленную версию из кэша плагинов, а не на клон (metis-0321)."""
    name = market_name(clone_root() or PLUGIN)
    p = os.path.join(HOME, ".claude", "plugins", "marketplaces", name, "plugins", "pantheon", "lib", "pantheon.py")
    return p if os.path.isfile(p) else os.path.join(LIB, "pantheon.py")


# --- шаги -----------------------------------------------------------------------------------------------------

def step_python(py):
    try:
        data = PCONFIG.update({"python": py})
        if not (data.get("executors") or {}).get("set"):
            PCONFIG.update({"set": ["claude"]}, "executors")
        report("Python установки", "ок", py)
    except (OSError, ValueError, RuntimeError) as e:
        report("Python установки", "не вышло", str(e))


def step_plugins(root):
    name = market_name(root)
    r = run(["claude", "plugin", "marketplace", "list"], env=claude_env())
    if r.returncode == 0 and name in (r.stdout or ""):
        report("маркетплейс", "пропуск", f"{name} уже подключён")
    else:
        o = run(["git", "-C", root, "remote", "get-url", "origin"])
        src = o.stdout.strip() if o.returncode == 0 and o.stdout.strip() else root
        r = run(["claude", "plugin", "marketplace", "add", src], env=claude_env())
        if r.returncode != 0:
            report("маркетплейс", "не вышло", last_line(r))
            return
        report("маркетплейс", "ок", f"{name} подключён")
    for p in PLUGINS:
        r = run(["claude", "plugin", "install", f"{p}@{name}"], env=claude_env())
        if r.returncode == 0:
            report(f"плагин {p}", "ок")
        else:
            report(f"плагин {p}", "не вышло", last_line(r))


def step_empty_pantheon():
    template = os.path.join(PLUGIN, "template", "pantheon")
    try:
        shutil.copytree(template, PANTHEON, dirs_exist_ok=True)
    except OSError as e:
        report("пустой Пантеон", "не вышло", str(e))
        return
    r = run(["git", "-C", PANTHEON, "init", "-q"])
    if r.returncode != 0:
        report("пустой Пантеон", "не вышло", "git init: " + last_line(r))
    else:
        report("пустой Пантеон", "ок", PANTHEON)


def step_pantheon_install(py):
    script = pantheon_script()
    # живой код и окна ролей идут только на проверенные деревья (verified.json, metis-0321): плагины, которые вы
    # поставили этим же запуском, принимаются как проверенные; уже записанные не трогаются (--new)
    a = run([py, "-I", script, "plugins", "accept", "--new"], env=child_env(py))
    report("проверенные деревья плагинов", "ок" if a.returncode == 0 else "не вышло",
           "" if a.returncode == 0 else last_line(a))
    r = run([py, "-I", script, "install"], env=child_env(py))
    report("pantheon install", "ок" if r.returncode == 0 else "не вышло",
           "" if r.returncode == 0 else last_line(r))


def step_roles(py):
    r = run([py, "-I", pantheon_script(), "roles", "build"], env=child_env(py))
    report("роли", "ок" if r.returncode == 0 else "не вышло", (r.stdout or "").strip().splitlines()[-1]
           if r.returncode == 0 and (r.stdout or "").strip() else ("" if r.returncode == 0 else last_line(r)))


def step_github():
    if not shutil.which("gh"):
        report("вход git в GitHub", "пропуск",
               "нет gh: поставьте `brew install gh`, затем `gh auth login` и `gh auth setup-git`")
        return
    if run(["gh", "auth", "status"]).returncode != 0:
        if not ask("Вы не вошли в GitHub. Войти сейчас через gh (`gh auth login`)?"):
            report("вход git в GitHub", "пропуск", "войти позже: `gh auth login`, затем `gh auth setup-git`")
            return
        r = subprocess.run(["gh", "auth", "login"])
        if r.returncode != 0:
            report("вход git в GitHub", "не вышло", "gh auth login не завершился")
            return
    if not ask("Настроить git так, чтобы он брал вход из gh (`gh auth setup-git`, правит ~/.gitconfig)?"):
        report("вход git в GitHub", "пропуск", "настроить позже: `gh auth setup-git`")
        return
    r = run(["gh", "auth", "setup-git"])
    report("вход git в GitHub", "ок" if r.returncode == 0 else "не вышло",
           "" if r.returncode == 0 else last_line(r))


def step_notifier():
    if shutil.which("terminal-notifier"):
        report("terminal-notifier", "ок", "уже стоит")
    elif PLAT.brew_path():
        ok, msg = PLAT.brew_install("terminal-notifier")
        report("terminal-notifier", "ок" if ok else "не вышло", "поставлен через Homebrew" if ok else msg)
    else:
        report("terminal-notifier", "пропуск",
               "нет Homebrew: поставьте его (https://brew.sh), затем `brew install terminal-notifier`")
    print(PLAT.NOTIFY_HELP, flush=True)


def step_traces(root, markers):
    markers = markers or os.environ.get("PANTHEON_TRACE_MARKERS")
    if not markers or not os.path.isfile(markers):
        report("проверка личных следов", "пропуск", "нет файла маркеров")
        return
    script = os.path.join(PLUGIN, "scripts", "check-traces.py")
    if not os.path.isfile(script) or not root:
        report("проверка личных следов", "не вышло", "нет scripts/check-traces.py или клон не в git")
        return
    rel = [os.path.relpath(os.path.join(p), root) for p in
           (os.path.join(PLUGIN, "bin", "pantheon-setup"), os.path.join(LIB, "setup.py"),
            os.path.join(LIB, "platform_macos.py"), os.path.join(LIB, "pconfig.py"), os.path.join(LIB, "executors.py"),
            os.path.join(PLUGIN, "scripts", "live-probe-codex-nested.sh"))
           if os.path.exists(p)]
    bad = []
    r = run([sys.executable, "-I", script, "--markers", markers, "--repo", root, "--", *rel])
    if r.returncode != 0:
        bad.append(f"файлы установщика: {last_line(r) if r.returncode == 2 else r.stdout.strip()}")
    with tempfile.TemporaryDirectory(prefix="tmp-traces-") as td:
        names = [f for f in os.listdir(AGENTS) if f.endswith(".md")] if os.path.isdir(AGENTS) else []
        for f in names:
            shutil.copy(os.path.join(AGENTS, f), os.path.join(td, f))
        if names and run(["git", "-C", td, "init", "-q"]).returncode == 0 \
                and run(["git", "-C", td, "add", "-A"]).returncode == 0:
            r = run([sys.executable, "-I", script, "--markers", markers, "--repo", td])
            if r.returncode != 0:
                bad.append(f"собранные роли: {last_line(r) if r.returncode == 2 else r.stdout.strip()}")
    if bad:
        report("проверка личных следов", "не вышло", "; ".join(bad))
    else:
        report("проверка личных следов", "ок", "следов нет")


def step_codex():
    path = os.path.join(LIB, "executors.py")
    try:
        mod = _load("pantheon_executors", path)
        fn = mod.add_codex
    except (OSError, AttributeError, ImportError):
        report("Codex", "пропуск", "модуль исполнителей не найден")
        return False
    try:
        res = fn(interactive=True, live_probe=True)
    except Exception as e:  # noqa: BLE001 — чужой модуль: любая ошибка — строка итога, установка идёт дальше
        report("Codex", "не вышло", f"{type(e).__name__}: {e}")
        return False
    if res == getattr(mod, "UNAVAILABLE", 3) and not isinstance(res, bool):
        # Codex — только дополнение (решение 175): недоступен — установка рабочая, задачи идут на Claude
        report("Codex", "пропуск", "не добавлен (причина выше), задачи пойдут на Claude; позже: `pantheon-setup --add codex`")
        return False
    if res is False or (isinstance(res, int) and not isinstance(res, bool) and res != 0):
        report("Codex", "не вышло", "проверка окружения не прошла (подробности выше)")
        return False
    report("Codex", "ок")
    return True


# --- главное --------------------------------------------------------------------------------------------------

def parse(argv):
    opts = {"python": sys.executable, "codex": None, "markers": None, "add": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--python", "--markers", "--add") and i + 1 < len(argv):
            opts[a[2:]] = argv[i + 1]
            i += 2
        elif a == "--codex":
            opts["codex"] = True
            i += 1
        elif a == "--no-codex":
            opts["codex"] = False
            i += 1
        else:
            raise ValueError(f"непонятный аргумент {a!r}. Допустимо: --python ПУТЬ, --codex, --no-codex, "
                             "--markers ФАЙЛ, --add codex")
    if opts["add"] not in (None, "codex"):
        raise ValueError("--add понимает только codex")
    return opts


def main(argv):
    try:
        o = parse(argv)
    except ValueError as e:
        print(f"pantheon-setup: {e}", file=sys.stderr)
        return 2
    if not PLAT.is_macos():
        print("pantheon-setup: пока только macOS.", file=sys.stderr)
        return 1
    if o["add"] == "codex":
        return 0 if step_codex() else 1
    if os.path.exists(PANTHEON) and (not os.path.isdir(PANTHEON) or os.listdir(PANTHEON)):
        print(f"pantheon-setup: {PANTHEON} уже есть и не пуст — установка ничего не меняет. Если Пантеон нужен "
              "заново, переименуйте или уберите эту папку сами. Добавить Codex к готовой установке: "
              "`pantheon-setup --add codex`.", file=sys.stderr)
        return 1
    if not shutil.which("claude"):
        print("pantheon-setup: сначала поставьте Claude Code (https://claude.com/claude-code) и запустите снова.",
              file=sys.stderr)
        return 1
    root = clone_root()
    if not root:
        print("pantheon-setup: запускайте из клона agent-kit (git-репозитория).", file=sys.stderr)
        return 1
    py = o["python"]
    step_python(py)
    step_plugins(root)
    step_empty_pantheon()
    step_pantheon_install(py)
    step_roles(py)
    step_github()
    step_notifier()
    step_traces(root, o["markers"])
    want = o["codex"] if o["codex"] is not None else ask("Подключить Codex (второй исполнитель задач)?")
    if want:
        step_codex()
    else:
        report("Codex", "пропуск", "не выбран (позже: `pantheon-setup --add codex`)")
    print()
    if failures:
        print("Не вышло: " + ", ".join(failures) + ". Исправьте причину и запустите нужный шаг руками "
              "(повторный запуск установщика на готовом Пантеоне откажет).")
        return 1
    bin_dir = os.path.join(HOME, ".local", "bin")
    if bin_dir not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"Команда pantheon лежит в {bin_dir.replace(HOME, '~')}, а этой папки нет в PATH: добавьте в ~/.zprofile "
              "строку `export PATH=\"$HOME/.local/bin:$PATH\"` и откройте новое окно терминала.")
    print("Готово: Пантеон установлен.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
