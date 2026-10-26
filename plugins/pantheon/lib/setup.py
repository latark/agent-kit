#!/usr/bin/env python3
"""pantheon-setup: установка Пантеона для нового человека на macOS (запускает bin/pantheon-setup, который заранее
ставит uv и Python 3.14 и вызывает этот файл: `setup.py --python <путь> [--codex|--no-codex] [--markers ФАЙЛ]`).

Шаги по порядку, у каждого строка итога «ок / пропуск / не вышло: почему». До любых изменений две проверки:
Пантеон уже есть (отказ, ничего не меняем) и нет Claude Code (отказ). Режимы `--add codex` и `--add backup` — только
шаг Codex или шаг резервной копии (`--backup-name ИМЯ`, по умолчанию pantheon-hq) на готовой установке. К системе ходит только через platform_macos.py. Пути — от HOME и PANTHEON_HOME/PANTHEON_STATE.
"""
import base64
import importlib.util
import json
import os
import re
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


BACKUP = "резервная копия"
BACKUP_REPO = "pantheon-hq"  # «личный штаб»: не путать с agent-kit и его плагином pantheon
BACKUP_SERVICE = "pantheon-git-crypt"
BACKUP_OLD_REF = "refs/pantheon/pre-backup"  # прежняя история до снимка (пишется один раз)
BACKUP_LATER = "копии нет: при потере Mac данные пропадут; включить позже: `pantheon-setup --add backup`"
BACKUP_ATTRS = "* filter=git-crypt diff=git-crypt\n.gitattributes !filter !diff\n.gitignore !filter !diff\n"
CRYPT_HEADER = b"\x00GITCRYPT\x00"
CRYPT_EXEMPT = (".gitattributes", ".gitignore")


def pgit(*args, env=None):
    return run(["git", "-C", PANTHEON, *args], env=env, timeout=600)


def backup_plain_files(tree):
    """Файлы дерева, которые git-crypt не зашифровал (кроме .gitattributes и .gitignore). → (список, ошибка)."""
    ls = run(["git", "-C", PANTHEON, "ls-tree", "-r", "-z", tree])
    if ls.returncode != 0:
        return None, "git ls-tree: " + last_line(ls)
    blobs, plain = [], []
    for ent in ls.stdout.split("\0"):
        if not ent:
            continue
        meta, name = ent.split("\t", 1)
        mode, kind, sha = meta.split()
        if kind != "blob" or os.path.basename(name) in CRYPT_EXEMPT:
            continue
        if mode == "120000":  # ссылку фильтр не шифрует: цель ушла бы открытой
            plain.append(name)
            continue
        blobs.append((sha, name))
    if not blobs:
        return plain, None
    try:
        r = subprocess.run(["git", "-C", PANTHEON, "cat-file", "--batch"], input="".join(s + "\n" for s, _ in blobs)
                           .encode(), capture_output=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"git cat-file: {e}"
    data, pos = r.stdout, 0
    for sha, name in blobs:
        nl = data.find(b"\n", pos)
        head = data[pos:nl].split() if nl >= 0 else []
        if len(head) != 3 or head[1] != b"blob":
            return None, f"git cat-file: не прочитан {name}"
        size = int(head[2])
        if not data[nl + 1:nl + 1 + size].startswith(CRYPT_HEADER):
            plain.append(name)
        pos = nl + 1 + size + 1
    return plain, None


def backup_snapshot():
    """Коммит без родителей из текущих файлов, прошедших фильтр git-crypt, — ветка переставляется на него.
    Прежние коммиты были бы открытыми в истории push; они остаются локально в refs/pantheon/pre-backup.
    → (ветка, ошибка)."""
    branch = pgit("symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
    if not branch:
        return None, "HEAD не на ветке"
    old = pgit("rev-parse", "-q", "--verify", "HEAD").stdout.strip()
    for args in (("add", "-A"), ("add", "--renormalize", ".")):
        r = pgit(*args)
        if r.returncode != 0:
            return None, f"git {args[0]}: " + last_line(r)
    tree = pgit("write-tree")
    if tree.returncode != 0:
        return None, "git write-tree: " + last_line(tree)
    tree = tree.stdout.strip()
    plain, err = backup_plain_files(tree)
    if err:
        return None, err
    if plain:
        return None, (f"git-crypt не зашифровал {len(plain)} файл(ов) ({', '.join(plain[:3])}) — push не делаю, "
                      "чтобы они не ушли в GitHub открытыми")
    env = None
    if pgit("var", "GIT_COMMITTER_IDENT").returncode != 0:  # на новом Mac git может не знать имени
        env = dict(os.environ, GIT_AUTHOR_NAME="Pantheon", GIT_AUTHOR_EMAIL="pantheon@localhost",
                   GIT_COMMITTER_NAME="Pantheon", GIT_COMMITTER_EMAIL="pantheon@localhost")
    c = pgit("commit-tree", tree, "-m", "pantheon: резервная копия (git-crypt)", env=env)
    if c.returncode != 0:
        return None, "git commit-tree: " + last_line(c)
    if old:
        pgit("update-ref", BACKUP_OLD_REF, old, "")  # только первый раз: исходная история
    u = pgit("update-ref", f"refs/heads/{branch}", c.stdout.strip(), old)
    if u.returncode != 0:
        return None, f"ветка {branch} сдвинулась во время шага (плановый коммит?) — запустите снова: " + last_line(u)
    return branch, None


def step_backup(name=BACKUP_REPO):
    """Резервная копия ~/ai/pantheon: приватный репозиторий GitHub под git-crypt (metis-0476). Сначала всё
    локальное (git-crypt, ключ в Связке, снимок), GitHub — последним: при сбое до него снаружи ничего нет.
    → True, если копия заведена или origin уже задан."""
    if not os.path.isdir(os.path.join(PANTHEON, ".git")):
        report(BACKUP, "не вышло", f"{PANTHEON} — не git-репозиторий")
        return False
    o = pgit("remote", "get-url", "origin")
    if o.returncode == 0 and o.stdout.strip():
        report(BACKUP, "пропуск", f"origin уже задан ({o.stdout.strip()}): второй репозиторий не завожу")
        return True
    if not shutil.which("gh") or run(["gh", "auth", "status"]).returncode != 0:
        report(BACKUP, "пропуск", "gh не вошёл в GitHub (`gh auth login`); " + BACKUP_LATER)
        return False
    if not shutil.which("git-crypt"):
        report(BACKUP, "пропуск", "нет git-crypt (`brew install git-crypt`); " + BACKUP_LATER)
        return False
    if not ask(f"Завести резервную копию в приватном репозитории GitHub ({name}, файлы под шифрованием "
               f"git-crypt, ключ — в Связке ключей)? История git в {PANTHEON} заменится одним снимком: "
               f"прежние коммиты останутся только на этом Mac, в {BACKUP_OLD_REF}."):
        report(BACKUP, "пропуск", BACKUP_LATER)
        return False
    inited = os.path.isdir(os.path.join(PANTHEON, ".git", "git-crypt"))
    try:
        has_key = PLAT.keychain_has(BACKUP_SERVICE)
    except (OSError, subprocess.TimeoutExpired) as e:
        report(BACKUP, "не вышло", f"Связка ключей: {type(e).__name__}")
        return False
    if has_key and not inited:
        report(BACKUP, "не вышло", f"в Связке ключей уже есть ключ {BACKUP_SERVICE} от другой копии — новый не "
               "завожу, чтобы не потерять старый")
        return False
    if not inited:
        r = run(["git-crypt", "init"], cwd=PANTHEON)
        if r.returncode != 0:
            report(BACKUP, "не вышло", "git-crypt init: " + last_line(r))
            return False
    if not has_key:
        td = tempfile.mkdtemp(prefix="tmp-backup-key-")  # $TMPDIR, права 0700; удаляется сразу
        try:
            kf = os.path.join(td, "key")
            r = run(["git-crypt", "export-key", kf], cwd=PANTHEON)
            if r.returncode != 0 or not os.path.isfile(kf):
                report(BACKUP, "не вышло", "git-crypt export-key: " + last_line(r))
                return False
            with open(kf, "rb") as fh:
                secret = base64.b64encode(fh.read()).decode()
        finally:
            shutil.rmtree(td, ignore_errors=True)
        ok, why = PLAT.keychain_add(BACKUP_SERVICE, "pantheon", secret)
        del secret
        if not ok:
            report(BACKUP, "не вышло", f"ключ в Связку ключей ({BACKUP_SERVICE}): {why}; GitHub не тронут")
            return False
    attrs = os.path.join(PANTHEON, ".gitattributes")
    try:
        if os.path.exists(attrs):
            with open(attrs, encoding="utf-8") as fh:
                if fh.read() != BACKUP_ATTRS:
                    report(BACKUP, "не вышло", ".gitattributes уже свой — шифрование не настраиваю поверх")
                    return False
        else:
            with open(attrs, "w", encoding="utf-8") as fh:
                fh.write(BACKUP_ATTRS)
    except OSError as e:
        report(BACKUP, "не вышло", f".gitattributes: {e}")
        return False
    branch, err = backup_snapshot()
    if err:
        report(BACKUP, "не вышло", err + "; GitHub не тронут")
        return False
    r = run(["gh", "repo", "create", name, "--private"])
    if r.returncode != 0:
        report(BACKUP, "не вышло", f"gh repo create {name}: {last_line(r)}; другое имя: "
               "`pantheon-setup --add backup --backup-name ИМЯ`")
        return False
    urls = [w for w in (r.stdout or "").split() if "://" in w]
    if not urls:
        report(BACKUP, "не вышло", f"gh repo create {name}: не вернул адрес репозитория")
        return False
    a = pgit("remote", "add", "origin", urls[-1])
    if a.returncode != 0:
        report(BACKUP, "не вышло", f"репозиторий {urls[-1]} создан, git remote add: " + last_line(a))
        return False
    p = pgit("push", "-u", "origin", branch, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    if p.returncode != 0:
        report(BACKUP, "не вышло", f"репозиторий {urls[-1]} создан, push не прошёл: {last_line(p)}; повторить: "
               f"`git -C {PANTHEON.replace(HOME, '~')} push -u origin {branch}`")
        return False
    report(BACKUP, "ок", f"{urls[-1]} (приватный, git-crypt); ключ — в Связке ключей, служба {BACKUP_SERVICE}; "
           "вернуть на другом Mac — README agent-kit, пункт «Резервная копия»")
    # Связка ключей не уходит в iCloud: без копии ключа вне Mac шифрованная копия при потере Mac не читается
    print(f"Сохраните ключ вне этого Mac (менеджер паролей): его покажет `security find-generic-password -s "
          f"{BACKUP_SERVICE} -w`. Без ключа резервную копию не расшифровать.", flush=True)
    return True


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
    opts = {"python": sys.executable, "codex": None, "markers": None, "add": None, "backup-name": BACKUP_REPO}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--python", "--markers", "--add", "--backup-name") and i + 1 < len(argv):
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
                             "--markers ФАЙЛ, --add codex, --add backup, --backup-name ИМЯ")
    if opts["add"] not in (None, "codex", "backup"):
        raise ValueError("--add понимает только codex и backup")
    if not re.fullmatch(r"[A-Za-z0-9_.][A-Za-z0-9_.-]{0,99}", opts["backup-name"]):
        raise ValueError("--backup-name: только латиница, цифры, «.», «_», «-», не с «-»")
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
    if o["add"] == "backup":
        return 0 if step_backup(o["backup-name"]) else 1
    if os.path.exists(PANTHEON) and (not os.path.isdir(PANTHEON) or os.listdir(PANTHEON)):
        print(f"pantheon-setup: {PANTHEON} уже есть и не пуст — установка ничего не меняет. Если Пантеон нужен "
              "заново, переименуйте или уберите эту папку сами. Добавить к готовой установке Codex или "
              "резервную копию: `pantheon-setup --add codex`, `pantheon-setup --add backup`.", file=sys.stderr)
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
    step_backup(o["backup-name"])
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
