"""Проверки вне окна роли ([sb-simplify] п. 7, «да» владельца 27.10): тесты и dev-сервер без модели и без СБ.

Окну роли песочница Claude Code не даёт местных портов (allowLocalBinding открыл бы весь localhost — местный прокси и
порты браузеров), поэтому dev-сервер и тесты, которым нужен порт, роль сама не запустит. Она пишет одну команду, а
плановый проход (launchd, вне песочницы окон) запускает проверку проекта под своим профилем sandbox-exec и отдаёт
результат. Образец — `pantheon merge request|run`: заявка роли → проход тика отдельным процессом.

  pantheon outside test [--script ИМЯ] [--wait С]    проверка проекта на HEAD этой папки (дерево чистое; неотслеживаемый .claude/worktrees/ не в счёт): команда —
                                         первая строка .pantheon-verify (из origin/HEAD, иначе из HEAD), иначе скрипт
                                         test/check package.json, иначе pytest; --script — скрипт package.json
  pantheon outside serve [--script ИМЯ] [--minutes N] [--wait С]   dev-сервер (скрипт dev или --script) → адрес
                                         http://127.0.0.1:<порт 3200–3299>; гаснет сам через N минут (30, не больше 120)
  pantheon outside status [ID]           итог заявки: состояние, код, адрес, хвост журнала (без ID — последние)
  pantheon outside stop ID               погасить свой сервер раньше срока
  pantheon outside run                   проход по заявкам — только плановый проход (из окна Claude Code — отказ)
--wait С — ждать итога до С секунд (не больше 590: у Bash окна предел 10 минут) и напечатать его; код выхода — код
команды тестов, у сервера 0 — адрес готов, отказ — 1, итога не дождался — 75. Оба места heavy заняты тяжёлыми
командами — serve стоит в очереди heavy до конца --wait (без --wait ~6 с), не дождался — итог failed с причиной и код 75. Без --wait — номер заявки, итог —
`pantheon outside status ID`.

Куда пишет заявка. В окне роли (есть PANTHEON_TMP — папка tmp кэша окна ~/Library/Caches/pantheon-sandbox/<окно>) —
в соседнюю папку outside/ кэша: туда окно пишет само, а итог проход кладёт туда же, окно его читает. Вне окна — в
STATE/outside/queue. Имя окна проход берёт из места папки, а не из текста заявки: окну направления можно только его
папки из реестра (domains.json ← ~/ai/pantheon/directions.toml), очереди STATE — любые папки реестра; кэш окна не
направления (мастерская, задачи) — отказ. Папка заявки — корень репозитория git внутри этих папок, с remote.

Проход (`outside run`, его запускает тик, когда есть дело; замок outside-run — по одному):
  1. Серверы: срок вышел, есть заявка «стоп» (<ID>.stop в той же папке) или процесс умер — группа процессов гаснет
     (SIGTERM, через 5 с SIGKILL) вместе с потомками, ушедшими в свою группу (turbo ставит её каждой задаче, next dev
     в ней), итог «stopped»; порт после этого ещё отвечает — пометка в итоге. Номер процесса сервера занял чужой
     (время старта по ps не то, что записано при запуске) — запись снимается без гашения. Пока проход занят тестами или ждёт
     порт нового сервера, он смотрит серверы каждые 2 с (SWEEP_EVERY): «стоп» не ждёт конца прогонов (metis-0606).
  2. Заявки — по времени, сначала серверы, потом тесты. Заявка удаляется до запуска: одна заявка — один запуск.
  3. Тесты после «принять» argus: в журнале шлюза слияния (STATE/merge-gate/records.jsonl) «принять» не старше суток
     на (repo, SHA), а записи tests на этот SHA нет — проход ищет копию: корень папки реестра или его worktree внутри
     папок реестра с HEAD = SHA и чистым деревом; нет такой, а коммит в клоне есть — временный worktree в
     ~/Library/Caches/pantheon-outside/wt (после прогона снимается; без node_modules сначала
     `<pm> install --frozen-lockfile`). Каждая пара (repo, SHA) — один раз (STATE/outside/auto.json); красные тесты и
     «нет копии» — тревога.
  4. Уборка: итоги <ID>.result.json и брошенные <ID>.stop в папках заявок (кэш окна, STATE/outside/queue) старше
     суток (RESULT_TTL, по mtime) удаляются; файлы живого сервера — нет. Журналы в STATE/outside/runs не трогаются.
Запуск: [heavy] sandbox-exec -f STATE/outside/profile.sb <команда> в папке репозитория, окружение с нуля (HOME, PATH с
node из nvm, TMPDIR — своя временная папка, у тестов CI=1, у сервера PORT). Тесты — не дольше TEST_TIMEOUT. Профиль:
всё разрешено, кроме чтения ключей (.env*, кроме шаблонов .env.example, .env.sample, .env.template — они открыты
на чтение, на запись нет; secrets/, ~/.ssh, ~/.config/cdp-daemon, ~/.config/gh, ~/.gnupg, ~/.aws,
~/.netrc, ~/.git-credentials, ~/.npmrc, ~/Library/Keychains и служба Связки ключей com.apple.SecurityServer), записи в
состояние и ядро (STATE, ~/ai/pantheon, ~/.claude, ~/.local/bin, ~/.local/share/pantheon, ~/Library/LaunchAgents,
профили оболочки, ~/.gitconfig, ~/.nvm, кэши окон ~/Library/Caches/pantheon-sandbox, .git/config и
.git/hooks папок реестра) и сети к портам браузеров (9222, 9333–9339) и
местного прокси (6152, 6153) на любом адресе.

Запись tests для шлюза слияния — только у проверки проекта (без --script; у serve её нет никогда): тесты кончились
кодом 0, HEAD и дерево до и после те же, команда не пустая (true, echo… — отказ; у скрипта package.json — по его
телу). Команда видна в записи (cmd), argus её сверяет: у скрипта package.json — с телом («pnpm run test  # package.json:
vitest run»), строка .pantheon-verify из файла ветки (в клоне нет origin/HEAD, origin/main, origin/master с этим
файлом) — с пометкой «# .pantheon-verify ветки (HEAD)»: эти файлы PR меняет сам, остаток — README guard. Проход дописывает в STATE/merge-gate/records.jsonl строку того же формата, что пишет хук guard
(kind tests, repo — remote папки, pr null, sha), by.agent_type = "pantheon-outside". Пишет только проход: роль в
своём окне STATE не пишет, а команда под профилем — тоже (deny file-write STATE). Хук guard на `pantheon review test`
по-прежнему пишет свою запись; шлюз принимает любую из двух.
Журналы: STATE/outside/runs/<ID>.log (вывод команды) и <ID>.json (итог), STATE/logs/outside.jsonl.
"""
import contextlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()

ID_RE = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
SCRIPT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,59}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
KINDS = ("test", "serve")
FINAL = ("done", "failed", "serving", "stopped")
DENY_PORTS = (9222,) + tuple(range(9333, 9340)) + (6152, 6153)   # браузеры с входами и местный прокси
SERVER_PORTS = range(3200, 3300)    # разработчики в своих worktree берут 3100–3199
SERVE_MIN, SERVE_MAX = 30, 120      # срок сервера, минуты
TEST_TIMEOUT = 7200                 # с
READY_SEC = 90                      # сервер должен открыть порт за это время
KILL_WAIT = 5
SWEEP_EVERY = 2                     # с: так часто проход смотрит «стоп» и срок серверов, пока идут его тесты (metis-0606)
SERVE_QUEUE_MIN = 6                  # без --wait (или он вышел) heavy ждёт место столько секунд (metis-0593)
AUTO_TTL = 24 * 3600                # «принять» старше суток тесты сам не зовёт
RESULT_TTL = 24 * 3600              # итоги <ID>.result.json и брошенные <ID>.stop в папках заявок — сутки
WAIT_MAX = 590
TAIL_LINES, TAIL_CHARS = 40, 4000
REQ_MAX = 64 * 1024
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
HEAVY = "default"                   # путь heavy; "default" — PLUGIN/bin/heavy; None — без heavy (тесты)
# пустые команды тестов (как EMPTY_TEST_PROGRAMS шлюза guard): записи tests не дают
EMPTY = {"true", ":", "echo", "printf", "exit", "test", "[", "sleep", "yes", "false"}
SAFE_PATH = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
USAGE = ("pantheon outside test [--script ИМЯ] [--wait С] | serve [--script ИМЯ] [--minutes N] [--wait С] | "
         "status [ID] | stop ID | run")


def set_core(mod):
    global P
    P = mod


def err(text):
    print(text, file=sys.stderr)


# --- пути ---------------------------------------------------------------------------------------------------------

def root(*parts):
    return os.path.join(P.STATE, "outside", *parts)


def caches():
    return os.path.join(P.HOME, "Library", "Caches", "pantheon-sandbox")


def wt_root():
    """Временные worktree тестов после «принять»: вне STATE — профиль запрещает запись в STATE, а тестам нужна запись
    в свою папку (node_modules, .next, кэши)."""
    return os.path.join(P.HOME, "Library", "Caches", "pantheon-outside", "wt")


def heavy_bin():
    return os.path.join(P.PLUGIN, "bin", "heavy") if HEAVY == "default" else HEAVY


def pass_env():
    """Окружение прохода, который запускает тик: с нуля, как у merge run (metis-0303) — HOME, PATH тика (git, node),
    интерпретатор, своё STATE; без launchd-окружения и ключей."""
    env = {"HOME": P.HOME, "PATH": P.run_env()["PATH"], "PANTHEON_PYTHON": sys.executable}
    for k in ("PANTHEON_STATE", "PANTHEON_HOME", "AI_HOME", "PANTHEON_NO_NOTIFY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def own_qdir():
    """Папка заявок этого вызова: в окне роли — outside/ рядом с PANTHEON_TMP (кэш окна), иначе STATE/outside/queue."""
    tmp = os.environ.get("PANTHEON_TMP")
    if tmp:
        return os.path.join(os.path.dirname(os.path.realpath(tmp)), "outside")
    return root("queue")


def queue_dirs():
    """[(папка заявок, окно)]: окно None — очередь STATE (ваши сессии), иначе имя окна по папке кэша."""
    out = [(root("queue"), None)]
    try:
        names = sorted(os.listdir(caches()))
    except OSError:
        names = []
    for name in names:
        d = os.path.join(caches(), name, "outside")
        if _is_dir(d):
            out.append((d, name))
    return out


def _is_dir(p):
    try:
        return stat.S_ISDIR(os.lstat(p).st_mode)
    except OSError:
        return False


def _open_dir(d, create=False):
    """Дескриптор настоящей папки d (не ссылки); None — нет или подложено."""
    if create and not os.path.lexists(d):
        os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return None
    st = os.fstat(fd)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        os.close(fd)
        return None
    return fd


def _read_in(dfd, name, limit=REQ_MAX):
    """Обычный файл name в папке dfd (без ссылок, одна жёсткая ссылка) → текст; иначе None."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > limit:
            return None
        return os.read(fd, limit + 1).decode("utf-8", "replace")
    finally:
        os.close(fd)


def _write_in(dfd, name, text):
    """Файл name в папке dfd: новый временный (O_EXCL, без ссылок) и rename — подложенная ссылка на месте имени
    заменяется, а не пишется насквозь."""
    tmp = f".{name}.{os.getpid()}.{secrets.token_hex(3)}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)


def _unlink_in(dfd, name):
    with contextlib.suppress(OSError):
        os.unlink(name, dir_fd=dfd)


def log_event(**kw):
    with contextlib.suppress(OSError):
        os.makedirs(os.path.join(P.STATE, "logs"), exist_ok=True)
        with open(os.path.join(P.STATE, "logs", "outside.jsonl"), "a") as fh:
            fh.write(json.dumps({"time": P.stamp(), **kw}, ensure_ascii=False) + "\n")


# --- реестр и git -------------------------------------------------------------------------------------------------

def registry(window=None):
    """Папки реестра (настоящие пути): окно направления — только его, None — все. Окно не направление — []."""
    domains = P.read_json(P.path("domains.json"), {}).get("domains") or {}
    out = []
    for name, folders in domains.items():
        if window is not None and name != window:
            continue
        for f in folders if isinstance(folders, list) else []:
            if isinstance(f, str):
                r = os.path.realpath(os.path.expanduser(f))
                if os.path.isdir(r) and r not in out:
                    out.append(r)
    return out


def inside(p, roots):
    return any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots)


def git(d, *args, timeout=30):
    """Вывод git в папке d (без GIT_* окружения); None — сбой."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def remote_id(url):
    """Адрес remote → owner/repo в нижнем регистре, как _remote_id + _repo_tail шлюза guard."""
    u = (url or "").strip()
    m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:]+)(?::\d*)?/+(.+)$", u, re.I) or \
        re.match(r"^(?:[^@/:]+@)?([^/:]+):(?!/)(.+)$", u)
    if not m:
        return "/".join(u.lower().split("/")[-2:])
    path = re.sub(r"(?:\.git)?/*$", "", m.group(2).lower()).strip("/")
    return "/".join(path.split("/")[-2:])


def remotes(d):
    out = git(d, "remote", "-v")
    if out is None:
        return []
    return sorted({remote_id(ln.split()[1]) for ln in out.splitlines() if len(ln.split()) >= 2})


# Живые worktree субагентов Claude Code лежат в .claude/worktrees/ и для git неотслеживаемые; грязью их не считаем.
# Только строка `?? ` с этим путём от корня репозитория: `.claude/worktrees-x/` и `a/.claude/worktrees/` не подходят.
WORKTREES_UNTRACKED = "?? .claude/worktrees/"


def head_state(d):
    """(HEAD, дерево чистое) папки d; HEAD None — не git или нет коммитов."""
    h = (git(d, "rev-parse", "HEAD") or "").strip().lower()
    st = git(d, "status", "--porcelain")
    clean = st is not None and all(ln.startswith(WORKTREES_UNTRACKED) for ln in st.splitlines() if ln.strip())
    return (h if SHA_RE.fullmatch(h) else None), clean


def toplevel(d):
    t = (git(d, "rev-parse", "--show-toplevel") or "").strip()
    return os.path.realpath(t) if t else None


# --- команда проверки ---------------------------------------------------------------------------------------------

def _show(d, rev, name):
    return git(d, "show", f"{rev}:{name}")


def base_rev(d):
    """Ветка по умолчанию клона (origin/HEAD, origin/main, origin/master) — откуда брать .pantheon-verify: PR не
    ослабит проверку своей же правкой. Нет — HEAD."""
    for ref in ("refs/remotes/origin/HEAD", "refs/remotes/origin/main", "refs/remotes/origin/master"):
        if git(d, "rev-parse", "--verify", "-q", ref) is not None:
            return ref
    return "HEAD"


def _pkg(d):
    try:
        with open(os.path.join(d, "package.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def package_manager(d, pkg):
    pm = str(pkg.get("packageManager") or "").split("@")[0]
    if pm in ("pnpm", "npm", "yarn", "bun"):
        return pm
    for lock, name in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun")):
        if os.path.exists(os.path.join(d, lock)):
            return name
    return "npm"


def command(d, kind, script=None):
    """→ (argv для запуска, строка для журнала) или (None, причина)."""
    pkg = _pkg(d)
    if script or kind == "serve":
        name = script or "dev"
        scripts = (pkg or {}).get("scripts") or {}
        if not isinstance(scripts, dict) or name not in scripts:
            return None, f"в package.json папки нет скрипта «{name}»"
        pm = package_manager(d, pkg)
        return [pm, "run", name], f"{pm} run {name}"
    base = base_rev(d)
    text, own = _show(d, base, ".pantheon-verify"), base == "HEAD"
    if not text and not own:
        text, own = _show(d, "HEAD", ".pantheon-verify"), True
    if text:
        line = next((x.strip() for x in text.splitlines() if x.strip() and not x.lstrip().startswith("#")), "")
        if line:
            words = line.split()
            while words and words[0] in ("heavy", "--server"):   # heavy проход ставит сам, снаружи профиля
                words = words[1:]
            line = line.split(None, len(line.split()) - len(words))[-1] if words else ""
            if not line:
                return None, ".pantheon-verify без команды"
            # строка из файла ветки (нет origin/HEAD, origin/main, origin/master или там файла нет) — видна в записи tests
            return ["/bin/sh", "-c", line], line + ("  # .pantheon-verify ветки (HEAD)" if own else "")
    if pkg:
        scripts = pkg.get("scripts") or {}
        name = "test" if "test" in scripts else "check" if "check" in scripts else None
        if name:
            pm = package_manager(d, pkg)
            # тело скрипта — в строке записи tests: package.json ветки PR меняет сам, argus сверяет команду
            body = " ".join(str(scripts[name]).split())[:300]
            return [pm, "run", name], f"{pm} run {name}  # package.json: {body}"
    try:
        with open(os.path.join(d, "pyproject.toml"), encoding="utf-8") as fh:
            py = fh.read()
    except OSError:
        py = ""
    if re.search(r"^\[tool\.pytest", py, re.M):
        argv = ["uv", "run", "pytest"] if os.path.exists(os.path.join(d, "uv.lock")) else ["python3", "-m", "pytest"]
        return argv, " ".join(argv)
    return None, "нечем проверить: нет .pantheon-verify, скрипта test/check в package.json и pytest в pyproject.toml"


def empty_command(line):
    """Пустая команда тестов (true, echo ok, CI=1 true): записи tests не будет. У скрипта package.json — его тело."""
    line, _, note = line.partition("  # ")
    if note.startswith("package.json: "):
        line = note[len("package.json: "):]
    try:
        words = shlex.split(line)
    except ValueError:
        return False
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words = words[1:]
    return not words or os.path.basename(words[0]) in EMPTY


# --- профиль и окружение ------------------------------------------------------------------------------------------

def _q(p):
    return '"' + p.replace("\\", "\\\\").replace('"', '\\"') + '"'


def profile_text(roots=()):
    """Профиль sandbox-exec: всё, кроме ключей, записи в состояние и ядро и портов браузеров и прокси."""
    h = os.path.realpath(P.HOME)
    secret_dirs = [".ssh", ".config/cdp-daemon", ".config/gh", ".gnupg", ".aws", "Library/Keychains"]
    # ~/.npmrc — ключи реестров (_authToken); npm и pnpm без него работают: проба 28.10, metis-0573
    secret_files = [".netrc", ".git-credentials", ".npmrc"]
    read = [f"(subpath {_q(os.path.join(h, x))})" for x in secret_dirs] + \
           [f"(literal {_q(os.path.join(h, x))})" for x in secret_files] + \
           ['(regex #"/\\.env[^/]*$")', '(regex #"/secrets(/|$)")']
    wdirs = [P.STATE, P.PANTHEON, os.path.join(h, ".claude"), os.path.join(h, ".local", "bin"),
             os.path.join(h, ".local", "share", "pantheon"), os.path.join(h, "Library", "LaunchAgents"),
             os.path.join(h, ".config", "git"), os.path.join(h, ".nvm"),
             os.path.join(h, "Library", "Caches", "pantheon-sandbox")]   # node владельца и кэши окон ролей
    wfiles = [os.path.join(h, x) for x in (".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bashrc", ".bash_profile",
                                          ".profile", ".gitconfig")]
    write = [f"(subpath {_q(os.path.realpath(x))})" for x in wdirs] + [f"(literal {_q(x)})" for x in wfiles]
    for r in roots:
        write.append(f'(regex #"^{re.escape(r)}/(.*/)?\\.git/(config|hooks)(/|$)")')
    net = [f'(remote ip "*:{p}")' for p in DENY_PORTS]
    return "\n".join([
        "(version 1)",
        "(allow default)",
        "(deny file-read* file-write*\n  " + "\n  ".join(read) + ")",
        # шаблоны без секретов читаются (metis-0578); поздние правила сильнее; запись в них закрыта deny выше
        '(allow file-read* (regex #"/\\.env\\.(example|sample|template)$"))',
        '(deny file-read* (regex #"/secrets(/|$)"))',   # secrets/ закрыта целиком, и шаблон в ней тоже
        '(deny mach-lookup (global-name "com.apple.SecurityServer"))',
        "(deny file-write*\n  " + "\n  ".join(write) + ")",
        "(deny network-outbound\n  " + "\n  ".join(net) + ")",
    ]) + "\n"


def write_profile(roots):
    os.makedirs(root(), mode=0o700, exist_ok=True)
    p = root("profile.sb")
    tmp = f"{p}.{os.getpid()}"
    with open(tmp, "w") as fh:
        fh.write(profile_text(roots))
    os.replace(tmp, p)
    return p


def sandbox_env(tmpdir, kind, port=None, heavy_wait=None):
    """Окружение команды с нуля: ни ключей окружения тика, ни GH_*, ни переменных launchd."""
    path = [x for x in [P.nvm_bin(), os.path.join(P.PLUGIN, "bin"), os.path.join(P.HOME, ".local", "bin")] if x]
    env = {"HOME": os.path.realpath(P.HOME), "PATH": ":".join(path + SAFE_PATH), "LANG": "en_US.UTF-8",
           "TMPDIR": tmpdir, "PANTHEON_STATE": P.STATE, "NEXT_TELEMETRY_DISABLED": "1", "DO_NOT_TRACK": "1"}
    if kind == "test":
        env["CI"] = "1"
    if port:
        env["PORT"] = str(port)
    if heavy_wait:   # metis-0593: heavy ждёт места не дольше остатка --wait роли, не 6 с
        env["HEAVY_WAIT_MAX"] = str(int(heavy_wait))
    return env


def wrap(argv, profile, server=False):
    hv = heavy_bin()
    return ([hv] + (["--server"] if server else []) if hv else []) + [SANDBOX_EXEC, "-f", profile] + argv


def tail(log):
    try:
        with open(log, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 64 * 1024))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-TAIL_LINES:])[-TAIL_CHARS:]


def strays(pid):
    """[(pid, pgid)] потомков группы pid, ушедших в свою группу процессов: turbo ставит каждой задаче свою, и next dev
    в ней переживал killpg группы сервера (metis-0606). Собирать до сигнала: после него сироты уходят к launchd.
    Начало обхода — только члены группы pid: pid не глава (номер достался чужому процессу) и группы нет — [], как у
    killpg, который такой группе ничего не шлёт."""
    try:
        out = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,pgid="], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    kids, pgid = {}, {}
    for ln in out.splitlines():
        try:
            p, pp, g = (int(x) for x in ln.split())
        except ValueError:
            continue
        kids.setdefault(pp, []).append(p)
        pgid[p] = g
    seen, todo = set(), [p for p, g in pgid.items() if g == pid]
    while todo:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        todo.extend(kids.get(p, ()))
    return [(p, pgid[p]) for p in sorted(seen) if p in pgid and pgid[p] != pid]


def _signal(pid, extra, sig):
    """sig группе pid и ушедшим потомкам: группе, если её глава — наш потомок, иначе самому процессу."""
    own = {p for p, _ in extra} | {pid}
    for target, group in [(pid, True)] + [(g, True) if g in own else (p, False) for p, g in extra]:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            (os.killpg if group else os.kill)(target, sig)


def _any_alive(pid, extra):
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, os.WNOHANG)
    for target, fn in [(pid, os.killpg)] + [(p, os.kill) for p, _ in extra]:
        try:
            fn(target, 0)
            return True
        except (ProcessLookupError, PermissionError):
            continue
    return False


def kill_group(pid):
    """SIGTERM группе процессов и её потомкам в своих группах (strays), через KILL_WAIT с — SIGKILL."""
    extra = strays(pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not _any_alive(pid, extra):
            return
        _signal(pid, extra, sig)
        deadline = time.monotonic() + (KILL_WAIT if sig == signal.SIGTERM else 1)
        while time.monotonic() < deadline:
            if not _any_alive(pid, extra):
                return
            time.sleep(0.1)


def wait_proc(proc, timeout):
    """proc.wait(timeout), а каждые SWEEP_EVERY с — sweep_quiet(): проход держит замок outside-run, пока идут тесты
    (после «принять» — подряд, часами), и тик его не зовёт; без этого «стоп» и срок сервера ждали конца всех прогонов
    (metis-0606). TimeoutExpired — как у proc.wait."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return proc.wait(timeout=max(0.01, min(SWEEP_EVERY, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                raise
        sweep_quiet()


_SWEEP_ERR = []


def sweep_quiet():
    """sweep() посреди чужой работы прохода: его сбой не роняет прогон тестов, в журнал — один раз."""
    try:
        sweep()
    except Exception as e:  # noqa: BLE001 — прогон тестов важнее; сам сбой виден в журнале и на следующем sweep()
        if not _SWEEP_ERR:
            _SWEEP_ERR.append(e)
            log_event(kind="sweep-error", why=f"{type(e).__name__}: {e}")


def started(pid):
    """Время старта процесса по ps (lstart, LC_ALL=C, TZ=UTC: смена пояса или летнего времени за жизнь сервера иначе
    меняет строку, и живой сервер сочли бы чужим) или None — процесса нет."""
    try:
        r = subprocess.run(["/bin/ps", "-o", "lstart=", "-p", str(int(pid))], capture_output=True, text=True,
                           timeout=10, env={"LC_ALL": "C", "TZ": "UTC", "PATH": "/usr/bin:/bin"})
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return " ".join(r.stdout.split()) or None


def foreign(pid, when):
    """Номер pid сервера занял другой процесс: жив, а время старта не то, что записано при запуске. Такой не гасить —
    только снять запись (metis-0606). Записи без времени (до этой правки) и умерший pid — не чужие."""
    if not pid or not when:
        return False
    now = started(pid)
    return now is not None and now != when


def alive(pid):
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, os.WNOHANG)
    try:
        os.killpg(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# --- запись tests для шлюза слияния ------------------------------------------------------------------------------

def records_file():
    return os.path.join(P.STATE, "merge-gate", "records.jsonl")


def read_records():
    try:
        fd = os.open(records_file(), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return []
    out = []
    with os.fdopen(fd, "rb") as fh:
        for raw in fh:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(rec, dict) and isinstance(rec.get("repo"), list) and isinstance(rec.get("sha"), str):
                out.append(rec)
    return out


def append_tests(repos, sha, cwd, line, window, rid):
    """Строка tests в журнал шлюза — формат записи хука guard (merge_gate.record), by — проход."""
    d = os.path.dirname(records_file())
    if os.path.islink(d):
        raise OSError("merge-gate — ссылка")
    os.makedirs(d, mode=0o700, exist_ok=True)
    rec = {"v": 1, "kind": "tests", "repo": repos, "pr": None, "sha": sha,
           "by": {"agent_type": "pantheon-outside", "agent_id": "", "session_id": "", "window": window or "",
                  "request": rid},
           "cwd": cwd, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tool_use_id": "", "cmd": line}
    fd = os.open(records_file(), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        pre = os.fstat(fd).st_mtime
        os.write(fd, (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        post = os.fstat(fd).st_mtime
    finally:
        os.close(fd)
    a = P.read_json(root("auto.json"), {})
    if a.get("mtime") == pre:   # своя строка — не повод тику снова смотреть журнал; чужая новая — повод
        a["mtime"] = post
        P.write_json(root("auto.json"), a)
    return rec


# --- итоги --------------------------------------------------------------------------------------------------------

def save_result(qdir, rid, res):
    """Итог — в STATE/outside/runs/<ID>.json и, если заявка из папки, в <ID>.result.json рядом с ней."""
    res = {"id": rid, "updated": P.stamp(), **res}
    text = json.dumps(res, ensure_ascii=False, indent=1)
    os.makedirs(root("runs"), mode=0o700, exist_ok=True)
    P.write_json(root("runs", rid + ".json"), res)
    if qdir:
        dfd = _open_dir(qdir)
        if dfd is not None:
            try:
                with contextlib.suppress(OSError):
                    _write_in(dfd, rid + ".result.json", text)
            finally:
                os.close(dfd)
    return res


def new_log(rid):
    os.makedirs(root("runs"), mode=0o700, exist_ok=True)
    p = root("runs", rid + ".log")
    return p, os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)


# --- тесты --------------------------------------------------------------------------------------------------------

def run_test(rid, d, script, window, qdir, roots, record=True):
    """Проверка проекта в папке d на её HEAD → итог. Запись tests — при коде 0 и том же чистом HEAD, только у проверки
    проекта: с --script записи нет."""
    record = record and not script
    sha, clean = head_state(d)
    if not sha:
        return save_result(qdir, rid, {"state": "failed", "kind": "test", "why": "папка не репозиторий git или нет коммитов"})
    if not clean:
        return save_result(qdir, rid, {"state": "failed", "kind": "test", "sha": sha,
                                       "why": "дерево не чистое — тесты идут на коммит: закоммить правки"})
    argv, line = command(d, "test", script)
    if not argv:
        return save_result(qdir, rid, {"state": "failed", "kind": "test", "sha": sha, "why": line})
    save_result(qdir, rid, {"state": "running", "kind": "test", "sha": sha, "cmd": line, "dir": d})
    log, fd = new_log(rid)
    tmp = tempfile.mkdtemp(prefix="outside-")
    code, timed_out = None, False
    try:
        with contextlib.suppress(OSError):
            os.write(fd, f"$ {line}  (папка {d}, {sha})\n".encode())
        try:
            proc = subprocess.Popen(wrap(argv, write_profile(roots)), cwd=d, env=sandbox_env(tmp, "test"),
                                    stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, start_new_session=True)
        except OSError as e:
            return save_result(qdir, rid, {"state": "failed", "kind": "test", "sha": sha, "cmd": line,
                                           "why": f"команда не запустилась: {e}", "log": log})
        try:
            code = wait_proc(proc, TEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_group(proc.pid)
            code = proc.wait()
    finally:
        os.close(fd)
        shutil.rmtree(tmp, ignore_errors=True)
    sha2, clean2 = head_state(d)
    res = {"state": "done", "kind": "test", "sha": sha, "code": code, "cmd": line, "dir": d, "log": log,
           "tail": tail(log), "record": False}
    if timed_out:
        res["why"] = f"тесты дольше {TEST_TIMEOUT} с — остановлены"
    elif sha2 != sha or not clean2:
        res["why"] = f"команда изменила HEAD или дерево (стало {sha2 or '?'}, чистое: {'да' if clean2 else 'нет'}) — записи нет"
    elif code == 0 and not record:
        res["note"] = "запись tests для шлюза — только у проверки проекта (без --script)"
    elif code == 0:
        repos = remotes(d)
        if empty_command(line):
            res["why"] = f"команда «{line}» ничего не проверяет — записи tests нет"
        elif not repos:
            res["why"] = "у репозитория нет remote — записи tests нет"
        else:
            try:
                append_tests(repos, sha, d, line, window, rid)
                res["record"] = True
            except OSError as e:
                res["why"] = f"запись tests не сделана: {e}"
    log_event(id=rid, kind="test", window=window, dir=d, sha=sha, code=code, record=res["record"])
    return save_result(qdir, rid, res)


# --- серверы ------------------------------------------------------------------------------------------------------

def servers():
    s = P.read_json(root("servers.json"), {})
    return s if isinstance(s, dict) else {}


def save_servers(s):
    os.makedirs(root(), mode=0o700, exist_ok=True)
    P.write_json(root("servers.json"), s)


def port_free(port):
    s = socket.socket()
    try:
        # без SO_REUSEADDR: с ним macOS даёт занять 127.0.0.1:порт, когда его уже держит слушатель на 0.0.0.0 (metis-0592)
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def port_open(port):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_port(taken):
    return next((p for p in SERVER_PORTS if p not in taken and port_free(p)), None)


def heavy_busy_why(log, waited):
    """Причина отказа heavy (код 75) по его последней строке в журнале: слоты заняты тестами или сервер уже есть."""
    line = next((x for x in reversed(tail(log).splitlines()) if x.startswith("heavy:")), "")
    m = re.search(r"за (\d+) с", line)
    n = m.group(1) if m else str(int(waited))
    if "оба места" in line:
        return f"оба места heavy заняты тяжёлыми командами, не дождалась за {n} с — повтори, когда прогоны закончатся"
    return (f"место для сервера занято: heavy --server держит один долгий процесс на Mac, не дождалась за {n} с — "
            "погаси прежний (pantheon outside stop ID) или дождись его срока")


def serve_wait(req):
    """Сколько секунд heavy ждёт место: остаток --wait роли с момента заявки (без --wait — SERVE_QUEUE_MIN)."""
    w = req.get("wait")
    if not isinstance(w, int) or isinstance(w, bool) or w <= 0:
        return SERVE_QUEUE_MIN
    t = _epoch(req)
    left = w - (P.now() - t if t else 0)
    return max(1, min(w, int(left)))   # время заявки в будущем не растит ожидание сверх --wait (metis-0604)


def run_serve(rid, d, script, minutes, window, qdir, roots, wait=SERVE_QUEUE_MIN):
    argv, line = command(d, "serve", script)
    if not argv:
        return save_result(qdir, rid, {"state": "failed", "kind": "serve", "why": line})
    srv = servers()
    port = pick_port({int(v.get("port") or 0) for v in srv.values()})
    if not port:
        return save_result(qdir, rid, {"state": "failed", "kind": "serve", "why": "нет свободного порта 3200–3299"})
    log, fd = new_log(rid)
    tmp = tempfile.mkdtemp(prefix="outside-")
    with contextlib.suppress(OSError):
        os.write(fd, f"$ PORT={port} {line}  (папка {d})\n".encode())
    try:
        proc = subprocess.Popen(wrap(argv, write_profile(roots), server=True), cwd=d,
                                env=sandbox_env(tmp, "serve", port, wait if heavy_bin() else None), stdin=subprocess.DEVNULL, stdout=fd, stderr=fd,
                                start_new_session=True)
    except OSError as e:
        os.close(fd)
        return save_result(qdir, rid, {"state": "failed", "kind": "serve", "why": f"сервер не запустился: {e}", "log": log})
    os.close(fd)
    t_start = last = time.monotonic()
    deadline = t_start + READY_SEC + (wait if heavy_bin() else 0)   # очередь heavy + сами READY_SEC
    while time.monotonic() < deadline and proc.poll() is None and not port_open(port):
        time.sleep(0.5)
        if time.monotonic() - last >= SWEEP_EVERY:   # очередь heavy — до 10 минут, «стоп» прежних не ждёт её
            sweep_quiet()
            last = time.monotonic()
    if proc.poll() is not None or not port_open(port):
        busy = proc.poll() == 75 and bool(heavy_bin())
        why = (heavy_busy_why(log, time.monotonic() - t_start) if busy
               else f"сервер вышел с кодом {proc.returncode}" if proc.poll() is not None
               else f"порт {port} не открылся за {READY_SEC} с")
        kill_group(proc.pid)
        log_event(id=rid, kind="serve", window=window, dir=d, port=port, ok=False)
        return save_result(qdir, rid, {"state": "failed", "kind": "serve", "cmd": line, "dir": d, "why": why,
                                       "log": log, "tail": tail(log), **({"busy": True} if busy else {})})
    until = P.now() + minutes * 60
    srv = servers()   # заново: sweep_quiet в ожидании порта мог погасить и убрать прежние
    srv[rid] = {"pid": proc.pid, "started": started(proc.pid), "port": port, "until": until, "qdir": qdir,
                "window": window, "dir": d, "tmp": tmp}
    save_servers(srv)
    log_event(id=rid, kind="serve", window=window, dir=d, port=port, ok=True, minutes=minutes)
    return save_result(qdir, rid, {"state": "serving", "kind": "serve", "cmd": line, "dir": d, "port": port,
                                   "url": f"http://127.0.0.1:{port}", "until": P.stamp(until), "log": log,
                                   "tail": tail(log)})


def _stop_asked(qdir, rid):
    if not qdir:
        return os.path.exists(root("queue", rid + ".stop"))
    dfd = _open_dir(qdir)
    if dfd is None:
        return False
    try:
        os.lstat(os.path.join(qdir, rid + ".stop"))
        return True
    except OSError:
        return False
    finally:
        os.close(dfd)


def sweep(t=None):
    """Серверы со сроком, заявкой «стоп» или умершим процессом — погасить. → число погашенных."""
    t = P.now() if t is None else t
    srv, n = servers(), 0
    for rid, s in list(srv.items()):
        pid = int(s.get("pid") or 0)
        alien = foreign(pid, s.get("started"))
        why = ("срок вышел" if t >= float(s.get("until") or 0) else "заявка «стоп»" if _stop_asked(s.get("qdir"), rid)
               else "процесс завершился" if not pid or alien or not alive(pid) else None)
        if not why:
            continue
        if pid and not alien:
            kill_group(pid)
        if s.get("tmp"):
            shutil.rmtree(s["tmp"], ignore_errors=True)
        qdir = s.get("qdir")
        if qdir:
            dfd = _open_dir(qdir)
            if dfd is not None:
                _unlink_in(dfd, rid + ".stop")
                os.close(dfd)
        else:
            with contextlib.suppress(OSError):
                os.remove(root("queue", rid + ".stop"))
        del srv[rid]
        n += 1
        port = int(s.get("port") or 0)
        busy = bool(port) and port_open(port)
        log_event(id=rid, kind="stop", why=why, **({"port_busy": port} if busy else {}))
        save_result(qdir, rid, {"state": "stopped", "kind": "serve", "port": s.get("port"), "why": why,
                                "log": root("runs", rid + ".log"), "tail": tail(root("runs", rid + ".log")),
                                **({"note": f"порт {port} после гашения ещё отвечает: его держит процесс вне дерева "
                                            "сервера"} if busy else {})})
    if n:
        save_servers(srv)
    return n


def sweep_due(t=None):
    t = P.now() if t is None else t
    for rid, s in servers().items():
        pid = int(s.get("pid") or 0)
        if (t >= float(s.get("until") or 0) or _stop_asked(s.get("qdir"), rid) or not pid or not alive(pid)
                or foreign(pid, s.get("started"))):
            return True
    return False


def _stale(t=None):
    """[(папка заявок, имя)] — итоги <ID>.result.json и брошенные <ID>.stop старше RESULT_TTL (по mtime, обычные
    файлы, не ссылки); у живого сервера его файлы не трогаем."""
    t = P.now() if t is None else t
    live, out = set(servers()), []
    for qdir, _ in queue_dirs():
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            for name in os.listdir(dfd):
                rid, _, ext = name.partition(".")
                if ext not in ("result.json", "stop") or not ID_RE.fullmatch(rid) or rid in live:
                    continue
                try:
                    st = os.lstat(name, dir_fd=dfd)
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode) and t - st.st_mtime > RESULT_TTL:
                    out.append((qdir, name))
        finally:
            os.close(dfd)
    return out


def prune(t=None):
    """Уборка папок заявок (кэш окна и STATE/outside/queue): итоги и «стоп» старше суток — удалить. → число."""
    n = 0
    for qdir, name in _stale(t):
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            st = os.lstat(name, dir_fd=dfd)
            if stat.S_ISREG(st.st_mode):
                _unlink_in(dfd, name)
                n += 1
        except OSError:
            pass
        finally:
            os.close(dfd)
    if n:
        log_event(kind="prune", removed=n)
    return n


# --- заявки -------------------------------------------------------------------------------------------------------

def requests():
    """[(время, вид, qdir, окно, id, заявка)] по всем папкам; битые и подложенные — удаляются с итогом failed."""
    out = []
    for qdir, window in queue_dirs():
        dfd = _open_dir(qdir)
        if dfd is None:
            continue
        try:
            for name in sorted(os.listdir(dfd)):
                if not name.endswith(".req.json"):
                    continue
                rid = name[:-len(".req.json")]
                text = _read_in(dfd, name)
                _unlink_in(dfd, name)   # одна заявка — один запуск
                if not ID_RE.fullmatch(rid):
                    continue
                try:
                    req = json.loads(text) if text is not None else None
                except ValueError:
                    req = None
                why = check_request(req, rid)
                if why:
                    save_result(qdir, rid, {"state": "failed", "why": why})
                    log_event(id=rid, kind="refused", window=window, why=why)
                    continue
                out.append((str(req.get("time") or ""), req["kind"], qdir, window, rid, req))
        finally:
            os.close(dfd)
    out.sort(key=lambda x: (x[1] != "serve", x[0]))
    return out


FUTURE_SLACK = 60                   # заявка со временем позже now+60 с отклоняется (metis-0604)


def check_request(req, rid):
    if not isinstance(req, dict) or req.get("v") != 1 or req.get("id") != rid:
        return "заявка не в формате (v1, id = имя файла)"
    if req.get("kind") not in KINDS:
        return f"вид заявки «{req.get('kind')}» — только test или serve"
    if not isinstance(req.get("dir"), str) or not os.path.isabs(req["dir"]):
        return "в заявке нет папки"
    s = req.get("script")
    if s is not None and not (isinstance(s, str) and SCRIPT_RE.fullmatch(s)):
        return "имя скрипта не по образцу (буквы, цифры, : _ . -)"
    m = req.get("minutes", SERVE_MIN)
    if not isinstance(m, int) or isinstance(m, bool) or not 1 <= m <= SERVE_MAX:
        return f"срок сервера — от 1 до {SERVE_MAX} минут"
    w = req.get("wait", 0)
    if not isinstance(w, int) or isinstance(w, bool) or not 0 <= w <= WAIT_MAX:
        return f"ожидание заявки — от 0 до {WAIT_MAX} секунд"
    if req.get("time") is not None and (_epoch(req) or 0) > P.now() + FUTURE_SLACK:
        return "время заявки — позже, чем сейчас на часах прохода"
    return None


def resolve_dir(req_dir, window):
    """Папка заявки → (корень репозитория, папки реестра окна) или (None, причина)."""
    roots = registry(window)
    if not roots:
        return None, (f"окно «{window}» — не направление из реестра: проверки вне окна только для папок направлений"
                      if window else "в реестре (domains.json) нет папок")
    d = os.path.realpath(req_dir)
    if not inside(d, roots):
        return None, f"папка {d} — не из папок {'направления ' + window if window else 'реестра'}"
    top = toplevel(d)
    if top != d:
        return None, f"папка {d} — не корень репозитория git"
    if not remotes(d):
        return None, f"у репозитория {d} нет remote — это не копия репозитория владельца"
    return d, roots


def handle(qdir, window, rid, req):
    d, roots = resolve_dir(req["dir"], window)
    if d is None:
        log_event(id=rid, kind="refused", window=window, why=roots)
        return save_result(qdir, rid, {"state": "failed", "kind": req["kind"], "why": roots})
    if req["kind"] == "serve":
        return run_serve(rid, d, req.get("script"), req.get("minutes", SERVE_MIN), window, qdir, roots,
                         serve_wait(req))
    return run_test(rid, d, req.get("script"), window, qdir, registry(None) or roots, record=not req.get("script"))


# --- тесты после «принять» ----------------------------------------------------------------------------------------

def _epoch(rec):
    """Время записи или заявки в секундах: «ГГГГ-ММ-ДД ЧЧ:ММ» (P.stamp, так пишет CLI) или «…T…:%S%z» (журнал шлюза);
    не разобрать — None."""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(rec.get("time")), fmt).timestamp()
        except ValueError:
            pass
    return None


def auto_todo(recs=None, t=None):
    """[(repo, sha)] — «принять» argus не старше AUTO_TTL, записи tests на (repo, SHA) нет, проход ещё не брался."""
    t = P.now() if t is None else t
    recs = read_records() if recs is None else recs
    done = (P.read_json(root("auto.json"), {}).get("done") or {})
    tested = {(str(x).lower(), r["sha"].lower()) for r in recs if r.get("kind") == "tests" for x in r["repo"]}
    out = []
    for r in recs:
        by = r.get("by") if isinstance(r.get("by"), dict) else {}
        if r.get("kind") != "accept" or by.get("agent_type") != "argus" or not SHA_RE.fullmatch(r["sha"].lower()):
            continue
        e = _epoch(r)
        if e is None or not 0 <= t - e <= AUTO_TTL:
            continue
        for repo in r["repo"]:
            key = (str(repo).lower(), r["sha"].lower())
            if key not in tested and f"{key[0]}@{key[1]}" not in done and key not in out:
                out.append(key)
    return out


def auto_due():
    """Тику: журнал шлюза менялся с прошлого прохода — пора смотреть «принять» без тестов."""
    try:
        m = os.stat(records_file()).st_mtime
    except OSError:
        return False
    return m != P.read_json(root("auto.json"), {}).get("mtime")


def find_checkout(repo, sha):
    """Копия repo на sha с чистым деревом внутри папок реестра → (папка, клон, None); нет — (None, клон|None, причина)."""
    roots = registry(None)
    clones = []
    for r in roots:
        top = toplevel(r)
        if top and top not in clones and inside(top, roots) and repo in remotes(top):
            clones.append(top)
    for top in clones:
        wt = git(top, "worktree", "list", "--porcelain") or ""
        for block in wt.split("\n\n"):
            fields = dict(ln.split(" ", 1) for ln in block.splitlines() if " " in ln)
            p = os.path.realpath(fields.get("worktree", ""))
            if fields.get("HEAD", "").lower() == sha and p and inside(p, roots):
                h, clean = head_state(p)
                if h == sha and clean:
                    return p, top, None
    for top in clones:
        if git(top, "cat-file", "-e", f"{sha}^{{commit}}") is not None:
            return None, top, None
    return None, None, (f"нет копии {repo} в папках реестра" if not clones else f"коммита {sha[:12]} нет в клоне {clones[0]}")


def run_auto(repo, sha):
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    d, clone, why = find_checkout(repo, sha)
    temp = None
    if not d and clone:
        temp = os.path.join(wt_root(), rid)
        os.makedirs(os.path.dirname(temp), mode=0o700, exist_ok=True)
        if git(clone, "worktree", "add", "--detach", temp, sha, timeout=120) is None:
            temp, why = None, f"worktree на {sha[:12]} в {clone} не создан"
        else:
            d = temp
    try:
        if not d:
            res = save_result(None, rid, {"state": "failed", "kind": "test", "auto": f"{repo}@{sha}", "why": why})
        else:
            if temp:
                prepare(temp, rid)
            res = run_test(rid, d, None, None, None, registry(None))
            res["auto"] = f"{repo}@{sha}"
            save_result(None, rid, res)
    finally:
        if temp:
            git(clone, "worktree", "remove", "--force", temp, timeout=120)
    a = P.read_json(root("auto.json"), {})
    a.setdefault("done", {})[f"{repo}@{sha}"] = {"time": P.stamp(), "id": rid, "state": res.get("state"),
                                                "code": res.get("code"), "record": res.get("record", False)}
    P.write_json(root("auto.json"), a)
    if not res.get("record"):
        P.alert(f"тесты после «принять» {repo}@{sha[:12]}: "
                + (f"код {res.get('code')}" if res.get("code") is not None else "не запущены")
                + (f" — {res['why']}" if res.get("why") else "") + f"; журнал: pantheon outside status {rid}",
                "pantheon-outside")
    return res


def prepare(d, rid):
    """Свежий worktree без node_modules: зависимости ставит `<pm> install --frozen-lockfile` под тем же профилем."""
    pkg = _pkg(d)
    if not pkg or os.path.exists(os.path.join(d, "node_modules")):
        return
    pm = package_manager(d, pkg)
    argv = [pm, "install", "--frozen-lockfile"] if pm in ("pnpm", "yarn") else [pm, "ci"]
    log, fd = new_log(rid)
    tmp = tempfile.mkdtemp(prefix="outside-")
    try:
        os.write(fd, f"$ {' '.join(argv)}  (зависимости свежего worktree)\n".encode())
        proc = subprocess.Popen(wrap(argv, write_profile(registry(None))), cwd=d, env=sandbox_env(tmp, "test"),
                                stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, start_new_session=True)
        try:
            wait_proc(proc, TEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            kill_group(proc.pid)
            proc.wait()
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        os.close(fd)
        shutil.rmtree(tmp, ignore_errors=True)


def auto_pass(t=None):
    try:
        m = os.stat(records_file()).st_mtime
    except OSError:
        m = None
    todo = auto_todo(t=t)
    a = P.read_json(root("auto.json"), {})
    a["mtime"] = m
    os.makedirs(root(), mode=0o700, exist_ok=True)
    P.write_json(root("auto.json"), a)
    return [run_auto(repo, sha) for repo, sha in todo]


# --- тик и проход -------------------------------------------------------------------------------------------------

def pending():
    """Тику: есть ли дело проходу — заявки, «стоп», серверы к гашению, новые записи шлюза, старые итоги."""
    for qdir, _ in queue_dirs():
        try:
            if any(n.endswith(".req.json") for n in os.listdir(qdir)):
                return True
        except OSError:
            continue
    return sweep_due() or auto_due() or bool(_stale())


def cmd_run():
    if "CLAUDECODE" in os.environ or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        err("pantheon outside run: только плановый проход, не из окна Claude Code")
        return 2
    with P.lock("outside-run", block=False) as got:
        if not got:
            return 0
        sweep()
        for _t, _k, qdir, window, rid, req in requests():
            handle(qdir, window, rid, req)
            sweep()
        if auto_due():
            auto_pass()
        prune()
    return 0


# --- команды роли -------------------------------------------------------------------------------------------------

def _flags(args, allowed):
    out, i = {}, 0
    while i < len(args):
        a = args[i]
        if a not in allowed or i + 1 >= len(args):
            return None
        out[a] = args[i + 1]
        i += 2
    return out


def cmd_request(kind, args):
    f = _flags(args, {"--script", "--wait"} | ({"--minutes"} if kind == "serve" else set()))
    if f is None:
        err(f"pantheon outside: {USAGE}")
        return 2
    try:
        wait = max(0, min(int(f.get("--wait", 0)), WAIT_MAX))
        minutes = int(f.get("--minutes", SERVE_MIN))
    except ValueError:
        err("pantheon outside: --wait и --minutes — целые числа")
        return 2
    d = toplevel(os.getcwd())
    if not d:
        err("pantheon outside: папка не репозиторий git — запускай из корня копии проекта")
        return 2
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    req = {"v": 1, "id": rid, "kind": kind, "dir": d, "time": P.stamp(),
           "by": " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "").split())[:40]}
    if f.get("--script"):
        req["script"] = f["--script"]
    if kind == "serve":
        req["minutes"] = minutes
        req["wait"] = wait
    why = check_request(req, rid)
    if why:
        err(f"pantheon outside: {why}")
        return 2
    q = own_qdir()
    try:
        dfd = _open_dir(q, create=True)
        if dfd is None:
            raise OSError(f"{q} — не папка")
        try:
            _write_in(dfd, rid + ".req.json", json.dumps(req, ensure_ascii=False))
        finally:
            os.close(dfd)
    except OSError as e:
        err(f"pantheon outside: заявку не записать ({e})")
        return 1
    print(f"заявка {rid}: {kind} в {d} — её исполнит плановый проход (раз в минуту)")
    if not wait:
        print(f"итог: pantheon outside status {rid}")
        return 0
    return wait_result(q, rid, wait)


def load_result(q, rid):
    dfd = _open_dir(q)
    if dfd is None:
        return None
    try:
        text = _read_in(dfd, rid + ".result.json", 1024 * 1024)
    finally:
        os.close(dfd)
    try:
        res = json.loads(text) if text else None
    except ValueError:
        return None
    return res if isinstance(res, dict) else None


def show(res):
    print(f"{res.get('id')}: {res.get('state')}" + (f", код {res['code']}" if res.get("code") is not None else "")
          + (f", {res['sha'][:12]}" if res.get("sha") else "") + (f" — {res['cmd']}" if res.get("cmd") else ""))
    if res.get("url"):
        print(f"адрес: {res['url']} до {res.get('until')} (погасить раньше: pantheon outside stop {res['id']})")
    if res.get("record"):
        print("запись tests для шлюза слияния сделана")
    if res.get("why"):
        print(f"причина: {res['why']}")
    if res.get("note"):
        print(res["note"])
    if res.get("tail"):
        print("--- хвост журнала ---\n" + res["tail"])


def result_code(res):
    if res.get("state") == "serving":
        return 0
    if res.get("state") == "failed" and res.get("busy"):
        return 75   # места heavy заняты, очередь не дождалась — как истёкшее ожидание
    if res.get("state") == "done" and isinstance(res.get("code"), int) and not res.get("why"):
        return res["code"]
    return 1


def wait_result(q, rid, wait):
    deadline = time.monotonic() + wait
    res = None
    while time.monotonic() < deadline:
        res = load_result(q, rid)
        if res and res.get("state") in FINAL:
            show(res)
            return result_code(res)
        time.sleep(2)
    print(f"итога за {wait} с нет (состояние: {(res or {}).get('state', 'в очереди')}) — pantheon outside status {rid}")
    return 75


def cmd_status(args):
    q = own_qdir()
    if args:
        if len(args) != 1 or not ID_RE.fullmatch(args[0]):
            err("pantheon outside status [ID]")
            return 2
        res = load_result(q, args[0]) or (P.read_json(root("runs", args[0] + ".json"), None)
                                           if q == root("queue") else None)
        if not res:
            print(f"{args[0]}: итога нет (заявка ещё в очереди или не из этого окна)")
            return 1
        show(res)
        return 0
    try:
        names = sorted((n for n in os.listdir(q) if n.endswith(".result.json")), reverse=True)[:10]
    except OSError:
        names = []
    if q == root("queue"):
        try:
            names = sorted((n[:-5] + ".result.json" for n in os.listdir(root("runs")) if n.endswith(".json")),
                           reverse=True)[:10]
        except OSError:
            pass
    if not names:
        print("итогов нет")
    for n in names:
        rid = n[:-len(".result.json")]
        res = load_result(q, rid) or P.read_json(root("runs", rid + ".json"), {})
        print(f"{rid}  {res.get('state', '?'):<8} {res.get('kind', '')}  "
              + (res.get("url") or (f"код {res['code']}" if res.get("code") is not None else res.get("why", ""))))
    return 0


def cmd_stop(args):
    if len(args) != 1 or not ID_RE.fullmatch(args[0]):
        err("pantheon outside stop ID")
        return 2
    q = own_qdir()
    dfd = _open_dir(q, create=True)
    if dfd is None:
        err(f"pantheon outside: {q} — не папка")
        return 1
    try:
        _write_in(dfd, args[0] + ".stop", "")
    finally:
        os.close(dfd)
    print(f"{args[0]}: сервер погаснет на следующем проходе (до минуты)")
    return 0


def main(rest):
    sub = rest[0] if rest else ""
    if sub in KINDS:
        return cmd_request(sub, rest[1:])
    if sub == "status":
        return cmd_status(rest[1:])
    if sub == "stop":
        return cmd_stop(rest[1:])
    if sub == "run" and len(rest) == 1:
        return cmd_run()
    err(f"pantheon outside: {USAGE}")
    return 2
