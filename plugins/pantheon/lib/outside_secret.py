"""`pantheon secret` — ключ проекта направления кладёт владелец, роль его не видит (metis-1135).

  pantheon secret put <направление> <ИМЯ> [--app ИМЯ] [--repo OWNER/REPO]   значение — скрытым вводом
  pantheon secret list <направление> [--repo OWNER/REPO]                      только имена ключей
  pantheon secret ask <направление> <ИМЯ> [--app ИМЯ] [--repo OWNER/REPO] --task ID   заявка: ключ вводит владелец
        в окне Touch ID со скрытым полем (metis-1135), а не в терминале. Можно из окна роли и из окна Зевса
  pantheon secret status [ID]   заявки этого окна и итоги (без значений)
  pantheon secret run           проход заявок — только плановый проход (из окна Claude Code — отказ)

Направление — имя окна из domains.json (например dir-beta). Его папки дают owner/repo по origin клона
(как у outside serve), файл — STATE/outside/env/<owner>__<repo>.env (у --app — <owner>__<repo>__<app>.env): тот же,
что читает проход для `pantheon outside serve` и `outside login` (dev_keys). Сервер и вход получают ключ в окружении
вне окна роли; окну папка закрыта профилем (WINDOW_SECRET_DIRS), а в выводе команды — только имя, не значение.

Значение — только скрытым вводом (getpass) в терминале владельца: не аргументом (история оболочки), не из конвейера и
не из окна Claude Code (CLAUDECODE, CLAUDE_CODE_ENTRYPOINT) — там отказ с кодом 1, файл не тронут. Пустой ввод убирает
ключ. Имя — переменная окружения, не служебная (RESERVED_ENV, PANTHEON_…, DYLD_…, LD_…) и не ключ тестов (TEST_KEYS
кладёт `pantheon outside key`). Значение — одна строка. Файл — папка 700, файл 600, замена целиком (O_EXCL и rename),
свои строки файла сохраняются. Ошибка разбора — код 2, отказ — код 1, причина последней строкой.

ask/run (metis-1135, «ввод через окно Touch ID со скрытым полем»): заявка — <id>.req.json в очереди (в окне роли —
secret/ рядом с PANTHEON_TMP, кэш окна; вне окна — STATE/secret/queue), только имя ключа, направление и задача —
значения в ней нет. Тик зовёт `pantheon secret run` отдельным процессом (owner_edit_kick). Проход: заявка старше
REQ_TTL — снята; имя и проект проверены заново (name_problem, pick_repo); владельца нет у Mac — ждёт; окно Touch ID
(помощник слияния) с именем ключа, проектом, задачей и окном; палец — системное окно osascript со скрытым полем
(ask_value), значение — сразу в write_key. Отказ, отмена, пустой ввод — отклонено, файл не тронут; окно закрыто без
ответа — повтор не раньше RETRY_SEC. Итог — <id>.result.json рядом с заявкой и строка STATE/logs/secret.jsonl, оба без
значения. Роль значение не видит: оно идёт из окна владельца прямо в файл 600, окну роли папка закрыта.
"""
import contextlib
import getpass
import json
import os
import re
import secrets
import subprocess
import sys
import time

P = O = None
USAGE = ("pantheon secret put <направление> <ИМЯ> [--app ИМЯ] [--repo OWNER/REPO] | "
         "list <направление> [--repo OWNER/REPO] | ask <направление> <ИМЯ> [--app ИМЯ] [--repo OWNER/REPO] --task ID | "
         "status [ID] | run")
ID_RE = re.compile(r"sk-\d{8}-\d{6}-[0-9a-f]{6}")
REQ_TTL = 24 * 3600       # заявка старше суток — снята
RETRY_SEC = 600           # окно закрыто без ответа — следующее не раньше
ASK_WAIT = 120            # секунд ждёт окно со скрытым полем
FINAL = ("done", "declined", "refused", "dropped", "failed")
ASK_SCRIPT = """on run argv
set r to display dialog (item 1 of argv) default answer "" with hidden answer with title "Пантеон: ключ проекта" """ \
    """buttons {"Отмена", "Сохранить"} default button "Сохранить" cancel button "Отмена" """ \
    """giving up after (item 2 of argv as integer)
if gave up of r then return "-"
return "=" & (text returned of r)
end run"""
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


# --- ask / run: ввод владельцем в окне Touch ID со скрытым полем -------------------------------------------------

def E():  # noqa: N802 — owner_edit.py: очередь в кэше окна, чтение своих файлов, атомарная запись, who()
    return P.owner_edit_mod()


def own_dir():
    tmp = os.environ.get("PANTHEON_TMP")
    if tmp:
        return os.path.join(os.path.dirname(os.path.realpath(tmp)), "secret")
    return P.path("secret", "queue")


def queue_dirs():
    """[(папка, окно)]: окно None — очередь STATE, иначе имя окна по папке кэша (не из текста заявки)."""
    out = [(P.path("secret", "queue"), None)]
    with contextlib.suppress(OSError):
        for name in sorted(os.listdir(E().caches())):
            d = os.path.join(E().caches(), name, "secret")
            if E().WINDOW_RE.fullmatch(name) and E()._is_dir(d) and not os.path.islink(os.path.join(E().caches(), name)):
                out.append((d, name))
    return out


def valid(req, fname):
    return isinstance(req, dict) and ID_RE.fullmatch(str(req.get("id"))) is not None \
        and fname == f"{req['id']}.req.json" and isinstance(req.get("created"), (int, float)) \
        and re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(req.get("direction"))) is not None \
        and name_problem(str(req.get("name"))) is None and E().TASK_RE.fullmatch(str(req.get("task"))) is not None \
        and (req.get("app") is None or (APP_RE.fullmatch(str(req["app"])) is not None and ".." not in req["app"])) \
        and (req.get("repo") is None or REPO_RE.fullmatch(str(req["repo"])) is not None)


def open_queue(win):
    """Папка очереди → fd или None: каждая часть пути после корня (STATE, кэш окон) — O_NOFOLLOW, дальше файлы в ней
    — только через этот fd (dir_fd), как owner_edit.open_queue: папку, подменённую ссылкой после открытия, проход не
    видит."""
    base, parts = (P.path(), ("secret", "queue")) if win is None else (E().caches(), (win, "secret"))
    try:
        fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return None
    try:
        for part in parts:
            nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
    except OSError:
        os.close(fd)
        return None
    return fd


def read_json(d, fname, dir_fd=None):
    raw = E().read_file(fname if dir_fd is not None else os.path.join(d, fname), limit=64 * 1024, dir_fd=dir_fd)
    with contextlib.suppress(ValueError, TypeError):
        return json.loads(raw)
    return None


def cmd_ask(args):
    pos, opts = _opts(args, ("--app", "--repo", "--task"))
    if pos is None or len(pos) != 2 or not opts.get("--task"):
        err(f"pantheon secret: {USAGE}")
        return 2
    direction, name = pos
    req = {"id": f"sk-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}", "created": time.time(),
           "direction": direction, "name": name, "task": opts["--task"], "app": opts.get("--app"),
           "repo": opts["--repo"].strip().lower() if opts.get("--repo") else None}
    why = name_problem(name)
    if why or not valid(req, f"{req['id']}.req.json"):
        err(f"pantheon secret ask: {why or 'направление, --task, --app или --repo — не те'}")
        return 2
    repo, code = pick_repo("ask", direction, req["repo"])
    if code is not None:
        return code
    req["repo"] = repo
    E().write_atomic(os.path.join(own_dir(), f"{req['id']}.req.json"), req)
    print(f"заявка {req['id']}: ключ {name} проекта {repo} направления {direction} введёт владелец в окне Touch ID со "
          f"скрытым полем (плановый проход, пока он у Mac); итог — `pantheon secret status {req['id']}`, значения "
          "там нет")
    return 0


def cmd_status(args):
    want = args[0] if args else None
    rows = []
    with contextlib.suppress(OSError):
        for f in sorted(os.listdir(own_dir())):
            m = re.fullmatch(r"(sk-[0-9a-f-]+)\.(req|result)\.json", f)
            if not m or (want and m.group(1) != want):
                continue
            j = read_json(own_dir(), f) or {}
            rows.append(f"{m.group(1)}: {j.get('status', 'ждёт владельца') if m.group(2) == 'result' else 'ждёт владельца'}"
                        f" — {j.get('name')} {j.get('repo')}{(' ' + j['why']) if j.get('why') else ''}")
    print("\n".join(rows) if rows else "заявок нет")
    return 0


def touch_window(text):
    """Окно Touch ID помощника слияния → код: 0 палец, 1 отказ, 2 не показать, 3 время вышло."""
    h = P.merge_mod().helper()
    if not h:
        return 2
    try:
        return subprocess.run([h, text[:400], "120", "Не вводить"], stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=180).returncode
    except (OSError, subprocess.SubprocessError):
        return 2


def ask_value(text):
    """Системное окно со скрытым полем (osascript) → значение, "" — отмена или пусто, None — закрыто без ответа."""
    try:
        r = subprocess.run(["/usr/bin/osascript", "-e", ASK_SCRIPT, text, str(ASK_WAIT)], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=ASK_WAIT + 60)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout[:-1] if r.stdout.endswith("\n") else r.stdout
    if r.returncode != 0 or not out.startswith(("=", "-")):
        return ""
    return out[1:].strip() if out.startswith("=") else None


def settle(fd, req, win, status, why=""):
    res = {"id": req["id"], "status": status, "name": req["name"], "repo": req.get("repo"), "app": req.get("app"),
           "direction": req["direction"], "task": req["task"], "window": win, "why": why, "time": time.time()}
    if status == "waiting":
        res["retry_after"] = time.time() + RETRY_SEC
    with contextlib.suppress(OSError):
        os.makedirs(P.path("logs"), exist_ok=True)
        with open(P.path("logs", "secret.jsonl"), "a") as fh:
            fh.write(json.dumps(res, ensure_ascii=False) + "\n")
    E().write_atomic(f"{req['id']}.result.json", res, dir_fd=fd)
    if status in FINAL:
        with contextlib.suppress(OSError):
            os.unlink(f"{req['id']}.req.json", dir_fd=fd)


def handle(fd, win, fname):
    """Одна заявка (папка — fd очереди) → итог или None (ждёт: владельца нет у Mac, окно закрыто без ответа недавно)."""
    req = read_json(None, fname, dir_fd=fd)
    if not valid(req, fname):
        with contextlib.suppress(OSError):
            os.unlink(fname, dir_fd=fd)
        return "refused"
    prev = read_json(None, f"{req['id']}.result.json", dir_fd=fd) or {}
    if prev.get("status") in FINAL or prev.get("retry_after", 0) > time.time():
        return None
    with contextlib.suppress(OSError):
        if time.time() - min(req["created"], os.stat(fname, dir_fd=fd, follow_symlinks=False).st_ctime) > REQ_TTL:
            settle(fd, req, win, "dropped", "владелец не ответил за сутки")
            return "dropped"
    repo, code = pick_repo("run", req["direction"], req.get("repo"))
    if code is not None:
        settle(fd, req, win, "refused", "проект не из направления")
        return "refused"
    if P.idle_sec() > E().PRESENT_SEC:
        return None
    app = f" ({req['app']})" if req.get("app") else ""
    where = f"окно {win}" if win else "вне окна роли"
    rc = touch_window(f"Ввести ключ {req['name']} проекта {repo}{app} направления {req['direction']} — задача "
                      f"{req['task']}, {where}. Значение введёте в следующем окне, роль его не увидит.")
    if rc == 3:
        settle(fd, req, win, "waiting", "окно Touch ID закрыто без ответа")
        return None
    if rc != 0:
        settle(fd, req, win, "declined" if rc == 1 else "failed",
               "отказ в окне Touch ID" if rc == 1 else "окно Touch ID не показать")
        return "declined" if rc == 1 else "failed"
    value = ask_value(f"{req['name']} для {repo}{app} (задача {req['task']}). Ввод не виден; значение получат "
                      "`outside serve` и `outside login` вне окна роли.")
    if value is None:
        settle(fd, req, win, "waiting", "окно ввода закрыто без ответа")
        return None
    if not value or any(c in value for c in "\r\n\0"):
        settle(fd, req, win, "declined", "отмена или пустой ввод" if not value else "значение не одной строкой")
        return "declined"
    if write_key(O.env_names(repo, req.get("app"))[-1], req["name"], value) is None:
        settle(fd, req, win, "failed", "файл ключей не записан")
        return "failed"
    settle(fd, req, win, "done", "ключ записан")
    return "done"


def pending():
    for _, win in queue_dirs():
        fd = open_queue(win)
        if fd is None:
            continue
        try:
            for f in os.listdir(fd):
                if f.endswith(".req.json"):
                    res = read_json(None, f.replace(".req.json", ".result.json"), dir_fd=fd) or {}
                    if res.get("status") not in FINAL and res.get("retry_after", 0) <= time.time():
                        return True
        except OSError:
            pass
        finally:
            os.close(fd)
    return False


def cmd_run(args):
    if args:
        err(f"pantheon secret: {USAGE}")
        return 2
    if "CLAUDECODE" in os.environ or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        err("pantheon secret run: проход — только плановый проход, не окно Claude Code")
        return 1
    why = P.merge_mod().clean_env()   # HOME, STATE и PATH — с нуля, не из launchd-окружения (как owner-edit run)
    if why:
        err(f"pantheon secret run: {why} — окружение прохода подменено, прохода нет")
        return 1
    with P.lock("secret-run", block=False) as got:
        if not got:
            return 0
        for _, win in queue_dirs():
            fd = open_queue(win)
            if fd is None:
                continue
            try:
                for f in sorted(os.listdir(fd)):
                    if f.endswith(".req.json"):
                        handle(fd, win, f)
            except OSError:
                pass
            finally:
                os.close(fd)
    return 0


def cmd_secret(args):
    sub = args[0] if args else ""
    cmds = {"put": cmd_put, "list": cmd_list, "ask": cmd_ask, "status": cmd_status, "run": cmd_run}
    if sub in cmds:
        return cmds[sub](args[1:])
    err(f"pantheon secret: {USAGE}")
    return 2
