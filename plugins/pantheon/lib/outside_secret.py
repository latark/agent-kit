"""`pantheon secret` — ключ проекта направления кладёт владелец, роль его не видит (metis-1135).

  pantheon secret put <направление> <ИМЯ> [--app ИМЯ] [--repo OWNER/REPO]   значение — скрытым вводом
  pantheon secret list <направление> [--repo OWNER/REPO]                      только имена ключей

Направление — имя окна из domains.json (например athena-brokerassistant). Его папки дают owner/repo по origin клона
(как у outside serve), файл — STATE/outside/env/<owner>__<repo>.env (у --app — <owner>__<repo>__<app>.env): тот же,
что читает проход для `pantheon outside serve` и `outside login` (dev_keys). Сервер и вход получают ключ в окружении
вне окна роли; окну папка закрыта профилем (WINDOW_SECRET_DIRS), а в выводе команды — только имя, не значение.

Значение — только скрытым вводом (getpass) в терминале владельца: не аргументом (история оболочки), не из конвейера и
не из окна Claude Code (CLAUDECODE, CLAUDE_CODE_ENTRYPOINT) — там отказ с кодом 1, файл не тронут. Пустой ввод убирает
ключ. Имя — переменная окружения, не служебная (RESERVED_ENV, PANTHEON_…, DYLD_…, LD_…) и не ключ тестов (TEST_KEYS
кладёт `pantheon outside key`). Значение — одна строка. Файл — папка 700, файл 600, замена целиком (O_EXCL и rename),
свои строки файла сохраняются. Ошибка разбора — код 2, отказ — код 1, причина последней строкой.
"""
import contextlib
import getpass
import os
import re
import sys

P = O = None
USAGE = ("pantheon secret put <направление> <ИМЯ> [--app ИМЯ] [--repo OWNER/REPO] | "
         "list <направление> [--repo OWNER/REPO]")
REPO_RE = re.compile(r"[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*")
APP_RE = re.compile(r"@?[A-Za-z0-9][A-Za-z0-9._/-]*")


def set_core(p, o):
    global P, O
    P, O = p, o


def err(text):
    print(text, file=sys.stderr)


def _opts(args, names):
    """[позиционные], {--имя: значение}; неизвестный флаг или флаг без значения — None."""
    pos, opts, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            if a not in names or i + 1 >= len(args):
                return None, None
            opts[a] = args[i + 1]
            i += 2
            continue
        pos.append(a)
        i += 1
    return pos, opts


def repos_of(direction):
    """owner/repo папок направления из domains.json (origin клона), по порядку, без повторов."""
    out = []
    for f in O.registry(direction):
        common = os.path.join(f, ".git")
        rid = O.origin_id(common) if os.path.isdir(common) else None
        if rid and rid not in out:
            out.append(rid)
    return out


def pick_repo(cmd, direction, want):
    """→ (owner/repo, None) или (None, код выхода) с причиной в stderr."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", direction or ""):
        err(f"pantheon secret {cmd}: «{direction}» — не имя направления (окно из domains.json)")
        return None, 2
    repos = repos_of(direction)
    if not repos:
        err(f"pantheon secret {cmd}: у направления {direction} нет папки с origin в domains.json — ключ некуда класть")
        return None, 1
    if want:
        want = want.strip().lower()
        if want not in repos:
            err(f"pantheon secret {cmd}: {want} не из проектов направления {direction} ({', '.join(repos)})")
            return None, 1
        return want, None
    if len(repos) > 1:
        err(f"pantheon secret {cmd}: у направления {direction} проектов {len(repos)} ({', '.join(repos)}) — "
            "назовите --repo OWNER/REPO")
        return None, 2
    return repos[0], None


def name_problem(name):
    if not O.ENV_KEY_RE.fullmatch(name or ""):
        return f"«{name}» — не имя переменной окружения (латиница, цифры, _)"
    if name in O.RESERVED_ENV or name.startswith(O.RESERVED_ENV_PREFIX):
        return f"{name} — служебное имя, окружение сервера его не отдаст"
    if name in O.TEST_KEYS:
        return f"{name} — ключ тестов, его кладёт `pantheon outside key OWNER/REPO {name}`"
    return None


def write_key(fname, name, value):
    """Строка NAME='value' в O.env_dir()/fname (пусто — строка убрана), прочие строки файла целы. Папка 700, файл 600,
    замена целиком: O_EXCL, O_NOFOLLOW и rename. → путь файла или None (причина в stderr)."""
    d = O.env_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    if os.path.islink(d) or not os.path.isdir(d):
        err(f"pantheon secret put: {d} — не папка; файл не тронут")
        return None
    os.chmod(d, 0o700)
    keep = [ln for ln in (O._env_file(fname, d) or "").splitlines()
            if not re.match(rf"\s*(?:export\s+)?{re.escape(name)}\s*=", ln)]
    lines = keep + ([f"{name}='{value}'"] if value else [])
    tmp = os.path.join(d, f".{fname}.{os.getpid()}")
    with contextlib.suppress(FileNotFoundError):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))
    os.replace(tmp, os.path.join(d, fname))
    return os.path.join(d, fname)


def cmd_put(args):
    pos, opts = _opts(args, ("--app", "--repo"))
    if pos is None or len(pos) != 2:
        err(f"pantheon secret: {USAGE}")
        return 2
    direction, name = pos
    app = opts.get("--app")
    if app is not None and (not APP_RE.fullmatch(app) or ".." in app):
        err(f"pantheon secret put: --app «{app}» — не имя приложения")
        return 2
    why = name_problem(name)
    if why:
        err(f"pantheon secret put: {why}")
        return 2
    if "CLAUDECODE" in os.environ or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        err("pantheon secret put: ключ кладёт владелец в своём терминале, не окно Claude Code; файл не тронут")
        return 1
    if not sys.stdin.isatty():
        err("pantheon secret put: нужен терминал — значение вводится скрыто, не из конвейера; файл не тронут")
        return 1
    repo, code = pick_repo("put", direction, opts.get("--repo"))
    if code is not None:
        return code
    try:
        value = getpass.getpass(f"{name} для {repo}{' (' + app + ')' if app else ''} "
                                "(ввод не виден; пусто — убрать ключ): ").strip()
    except (EOFError, KeyboardInterrupt):
        err("pantheon secret put: отменено, файл не тронут")
        return 1
    if any(c in value for c in "\r\n\0"):
        err(f"pantheon secret put: {name} — значение одной строкой; файл не тронут")
        return 1
    path = write_key(O.env_names(repo, app)[-1], name, value)
    if path is None:
        return 1
    print(f"{'записан' if value else 'убран'} ключ {name} проекта {repo}{' (' + app + ')' if app else ''} "
          f"направления {direction}: {path} (значение не показано; его получат в окружении "
          "`pantheon outside serve` и `outside login` этого проекта вне окна роли)")
    return 0


def cmd_list(args):
    pos, opts = _opts(args, ("--repo",))
    if pos is None or len(pos) != 1:
        err(f"pantheon secret: {USAGE}")
        return 2
    repo, code = pick_repo("list", pos[0], opts.get("--repo"))
    if code is not None:
        return code
    base = O.env_names(repo)[0][:-len(".env")]
    rows = []
    with contextlib.suppress(OSError):
        for f in sorted(os.listdir(O.env_dir())):
            if f == base + ".env" or (f.startswith(base + "__") and f.endswith(".env")):
                keys, _ = O.parse_env(O._env_file(f) or "")
                rows.append(f"{f}: {', '.join(sorted(keys)) or '—'}")
    print(f"ключи проекта {repo} (только имена):\n" + ("\n".join(rows) if rows else "нет"))
    return 0


def cmd_secret(args):
    sub = args[0] if args else ""
    if sub == "put":
        return cmd_put(args[1:])
    if sub == "list":
        return cmd_list(args[1:])
    err(f"pantheon secret: {USAGE}")
    return 2
