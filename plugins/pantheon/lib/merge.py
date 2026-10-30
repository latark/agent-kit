"""Слияние PR ядра одним Touch ID (metis-0285; владелец выбрал Touch ID, Зевс 19.10).

PR ядра защит (Д3) агенты не сливают: его сливает владелец. Чтобы не набирать gh в терминале, роль ставит заявку, а
плановый проход (launchd, сессия владельца, вне песочницы окон) показывает системное окно Touch ID и после пальца
сливает ровно проверенный коммит.

  pantheon merge request <N> -R <owner/repo>   заявка: STATE/merge-queue/<owner>__<repo>__<N>.json (папка 0700,
                                                файл 0600) с head SHA PR сейчас. Репозиторий — из [merge_repos]
                                                metis-pantheon (policy.toml); шлюз проверяется сразу (кроме CI в работе)
  pantheon merge run [--click]   проход по заявкам: зовёт его тик (из окна Claude Code — отказ, guard ролям тоже не даёт);
                                 --click — щелчок по уведомлению запасного пути: владелец у Mac
  pantheon merge status          заявки: репозиторий#N, SHA, возраст, отметки
  pantheon merge cancel <N> -R <owner/repo>    снять заявку

Проход по каждой заявке (одна заявка — одно применение):
  1. Старше REQUEST_TTL (24 ч) — снята.
  2. PR сейчас (gh pr view): не OPEN, черновик или head не тот SHA, что в заявке, — снята (новый коммит — новая заявка).
  3. Репозиторий всё ещё в [merge_repos] metis-pantheon. Шлюз заново на тот же head: запись тестов шлюза на SHA; у
     каждого рецензента argus последний вердикт — «принять» с полным перечнем и на Opus (по ran и, если хук guard
     записал их, по моделям транскрипта argus — metis-0176), рецензентов-«принять» не
     меньше двух, «вернуть» нет; проверки GitHub (CI) — все SUCCESS/NEUTRAL/SKIPPED. CI ещё идёт или проверок пока
     нет — заявка ждёт; иначе снята с тревогой. Список файлов PR (REST pulls/N/files) полон — иначе ждёт: окно
     показывает задетые файлы ядра, без списка их не показать. PR правит version в plugin.json плагина или трогает
     .claude-plugin/releases.json — снята с тревогой (metis-0512: номер поднимает workflow release после слияния).
  4. Владелец у Mac (простой меньше PRESENT_SEC) — окно Touch ID: помощник pantheon-touchid (lib/touchid.swift,
     LocalAuthentication), в тексте — задетые файлы ядра, заголовок PR последним. После пальца, под замком
     merge-queue: заявка в очереди та же (не снята и не заменена), репозиторий в [merge_repos], шлюз заново — только
     тогда строка `<время> merge-approve <owner/repo>#<N> <sha>` в owner-log/merge-approve.log (её сверяет шлюз guard:
     PR ядра проходит только с ней, не старше суток), заявка снята, `gh pr merge <N> -R <repo> --match-head-commit
     <sha> --merge`. «Не сливать» — снята. Окно закрыто без ответа — ждёт RETRY_SEC. Окно не показать (код 2: процесс
     launchd не в сессии владельца) — запасной путь: уведомление один раз, щелчок по нему запускает
     `pantheon merge run --click` от имени владельца, и окно Touch ID показывается уже оттуда. Заявку сняли или
     заменили, пока окно открыто, — проход её не трогает: ни согласия, ни слияния, ни записи обратно.
Журнал — STATE/logs/merge.jsonl (репозиторий, номер, SHA, событие). Помощник — только STATE/bin/pantheon-touchid с
отметкой sha256 исходника lib/touchid.swift рядом (иначе его пересобирает /usr/bin/swiftc с чистым окружением).

Окружение прохода (metis-0303). Его задаёт launchd, а launchd-окружение меняет любой процесс владельца (launchctl
setenv). Поэтому проход строит окружение с нуля (clean_env): HOME — realpath домашней папки учётной записи (pw_dir;
HOME окружения не она — отказ), PATH — постоянный SAFE_PATH (gh — из него), STATE, папка Пантеона и current — от HOME.
PANTHEON_STATE, PANTHEON_HOME, PANTHEON_NOTIFY_LOG, PANTHEON_FAKE_*, PANTHEON_NOW, GH_* (GH_CONFIG_DIR, GH_TOKEN),
XDG_* и всё прочее он не берёт.
Интерпретатор: тик не берёт PANTHEON_PYTHON, PANTHEON_PY_DIRS и PYTHONEXECUTABLE, а config.toml читает от домашней
папки учётной записи, не от HOME и не из PANTHEON_STATE (bin/pantheon-tick); проход тик запускает с окружением
pass_env (PANTHEON_PYTHON — найденный тиком интерпретатор, не sys.executable), щелчок — через /usr/bin/env -i с ним же.
Тестовые подмены — только атрибутом TEST, его ставит тестовая обвязка в своём процессе; из окружения он не
включается. Остальной тик PANTHEON_STATE ещё берёт, а DYLD_* и прочее launchd-окружение доходит до интерпретатора
тика: целиком это закрывает только запрет ролям launchctl setenv (metis-0298).
"""
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from datetime import datetime

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()

REPO_RE = re.compile(r"[a-z0-9_.-]+/[a-z0-9_.-]+")
PR_RE = re.compile(r"[1-9][0-9]{0,8}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
FILE_RE = re.compile(r"([a-z0-9_.-]+)__([a-z0-9_.-]+)__([1-9][0-9]{0,8})\.json")
MERGE_DIRECTION = "metis-pantheon"   # чьи [merge_repos] — репозитории защит
REQUEST_TTL = 24 * 3600
RETRY_SEC = 600                      # окно закрыто без ответа — следующее не раньше
PRESENT_SEC = 300                    # владелец у Mac: простой меньше 5 минут
WINDOW_WAIT = 120                    # сколько окно ждёт пальца
MIN_ACCEPTS = 2
GH_TIMEOUT = 30
MERGE_TIMEOUT = 120
APPROVE_FILE = "merge-approve.log"
CI_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
CI_WAIT = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", ""}
SWIFTC = "/usr/bin/swiftc"           # абсолютный путь: PATH прохода подменяем (launchctl setenv)
SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"   # PATH прохода, не из окружения
# Тестовые подмены прохода: {"env": {имя: значение}} — переменные, которые проход берёт поверх чистого окружения, и
# HOME без сверки с учётной записью. Ставит только тестовая обвязка в своём процессе (tests/test_merge.py, HARNESS);
# из окружения launchd не включается. В бою — None
TEST = None
# ядро защит (Д3) — как CORE_FILES и CORE_DIR шлюза guard (merge_gate.py); совпадение сверяет test_merge
CORE_FILES = ("plugins/guard/hooks/merge_gate.py", "plugins/guard/hooks/protect_config.py",
              "plugins/guard/managed-settings.json", "plugins/pantheon/lib/window_rules.py",
              "plugins/pantheon/hooks/ctx.py", "plugins/pantheon/hooks/hooks.json", "plugins/pantheon/lib/merge.py",
              "plugins/pantheon/lib/plugin_map.py", "plugins/pantheon/plugins-by-role.toml",
              ".claude-plugin/marketplace.json")
CORE_DIR = ("plugins/guard", "plugins/pantheon/roles", ".github")
USAGE = "pantheon merge request|cancel <N> -R <owner/repo> | run [--click] | status"


def set_core(mod):
    global P
    P = mod


def err(text):
    print(text, file=sys.stderr)


# --- окружение прохода (metis-0303) -------------------------------------------------------------------------------

def clean_env():
    """Окружение прохода с нуля: HOME и SAFE_PATH, STATE и папка Пантеона — от HOME. Окружение задаёт launchd, а его
    меняет любой процесс владельца (launchctl setenv): из него проход не берёт ничего, кроме PANTHEON_PYTHON — его
    ставит bin/pantheon прохода из pass_env тика (own_python). HOME — домашняя папка учётной
    записи (pw_dir), HOME окружения только сверяется с ней: не она — отказ. Дальше идёт realpath, а не путь как есть:
    ссылку можно перевесить после сверки (argus-b 0303, п. 2) — так в окружение, gh, P.CURRENT и команду щелчка.
    → None или причина отказа."""
    if TEST is None:
        import pwd
        try:
            owner = pwd.getpwuid(os.getuid()).pw_dir
        except (KeyError, OSError):
            owner = None
        if not owner or os.path.realpath(owner) != os.path.realpath(P.HOME):
            return f"HOME ({P.HOME}) — не домашняя папка учётной записи"
        home = os.path.realpath(owner)
    else:
        home = os.path.realpath(P.HOME)
    env = {"HOME": home, "PATH": SAFE_PATH}
    py = own_python()
    if py:   # интерпретатор прохода — для команды щелчка (pass_env); его поставил bin/pantheon из pass_env тика
        env["PANTHEON_PYTHON"] = py
    if TEST is not None:
        env.update(TEST.get("env") or {})
    os.environ.clear()
    os.environ.update(env)
    P.HOME = home
    P.AI_HOME = os.path.join(home, "ai")
    P.CURRENT = os.path.join(home, ".local", "share", "pantheon", "current")
    P.STATE = os.path.realpath(os.path.join(home, ".local", "state", "pantheon"))
    P.PANTHEON = os.path.realpath(os.path.join(P.AI_HOME, "pantheon"))
    return None


def own_python():
    """Интерпретатор прохода — PANTHEON_PYTHON: в тике его ставит bin/pantheon-tick после find_python, в проходе —
    bin/pantheon из pass_env тика. Не sys.executable: на macOS его задаёт PYTHONEXECUTABLE даже при -I, а окружение
    тика — launchd (argus-b 0303c, п. 1). Не абсолютный путь — None."""
    py = os.environ.get("PANTHEON_PYTHON", "")
    return py if os.path.isabs(py) else None


def pass_env():
    """Окружение, с которым тик запускает проход, а щелчок по уведомлению — `merge run --click`: HOME, SAFE_PATH и
    свой интерпретатор (own_python; bin/pantheon берёт PANTHEON_PYTHON), без launchd-окружения. Интерпретатора
    нет — без PANTHEON_PYTHON: bin/pantheon найдёт его сам в чистом окружении."""
    env = {"HOME": P.HOME, "PATH": SAFE_PATH}
    py = own_python()
    if py:
        env["PANTHEON_PYTHON"] = py
    return env


# --- пути и файлы -------------------------------------------------------------------------------------------------

def root():
    return os.path.join(P.STATE, "merge-queue")


def _real_dir(p):
    try:
        return stat.S_ISDIR(os.lstat(p).st_mode)
    except OSError:
        return False


def ensure_dir(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if not os.path.lexists(p):
        os.mkdir(p, 0o700)
    if not _real_dir(p):
        raise ValueError(f"{p} — не папка (или ссылка)")
    os.chmod(p, 0o700)
    return p


def req_file(repo, pr):
    owner, name = repo.split("/")
    return os.path.join(root(), f"{owner}__{name}__{int(pr)}.json")


def read_req(p):
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not REPO_RE.fullmatch(str(data.get("repo", ""))) \
            or not isinstance(data.get("pr"), int) or not SHA_RE.fullmatch(str(data.get("sha", ""))) \
            or not isinstance(data.get("created"), (int, float)):
        return None
    if os.path.basename(p) != os.path.basename(req_file(data["repo"], data["pr"])):
        return None
    return data


def write_req(req):
    """Заявка — атомарно: временный файл без перехода по ссылке, затем rename."""
    d = ensure_dir(root())
    p = req_file(req["repo"], req["pr"])
    tmp = os.path.join(d, f".tmp.{os.getpid()}")
    with contextlib.suppress(FileNotFoundError):
        os.remove(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(req, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def same_req(req):
    """Заявка в очереди всё ещё эта: тот же SHA и то же время постановки. Звать под замком merge-queue."""
    p = req_file(req["repo"], req["pr"])
    cur = read_req(p) if os.path.lexists(p) else None
    return bool(cur) and cur["sha"] == req["sha"] and cur["created"] == req["created"]


def gone(req, rc=None):
    """Заявку сняли (cancel) или заменили новой, пока шёл проход: её не трогаем — ни согласия, ни записи обратно."""
    log(req, "gone", rc=rc)
    return "заявку сняли или заменили во время прохода — не трогаю"


def keep(req):
    """Отметку (wait_until, notified) — обратно в очередь, только если там та же заявка."""
    with P.lock("merge-queue"):
        if not same_req(req):
            return False
        write_req(req)
    return True


def drop(req, event, why=None, warn=False):
    """Снять заявку — только если в очереди та же: новую, поставленную во время прохода, не трогает."""
    with P.lock("merge-queue"):
        if not same_req(req):
            return gone(req)
        with contextlib.suppress(FileNotFoundError):
            os.remove(req_file(req["repo"], req["pr"]))
    log(req, event)
    if warn:
        P.alert(f"слияние {req['repo']}#{req['pr']} ({req['sha'][:7]}) по Touch ID: заявка снята — {why}", "pantheon-merge")
    return f"снята: {why or event}"


def log(req, event, **extra):
    rec = {"time": P.stamp(), "repo": req.get("repo"), "pr": req.get("pr"), "sha": req.get("sha"), "event": event}
    rec.update({k: v for k, v in extra.items() if isinstance(v, (int, float, bool, str)) or v is None})
    os.makedirs(P.path("logs"), exist_ok=True)
    with open(P.path("logs", "merge.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def allowed_repos():
    p = os.path.join(P.HOME, ".claude", "pantheon", "policy.toml")
    try:
        with open(p, "rb") as fh:
            pol = P.tomllib.load(fh)
    except (OSError, ValueError):
        return set()
    repos = (pol.get("merge_repos") or {}).get(MERGE_DIRECTION) if isinstance(pol.get("merge_repos"), dict) else None
    return {r.strip().lower() for r in repos if isinstance(r, str)} if isinstance(repos, list) else set()


# --- GitHub ---------------------------------------------------------------------------------------------------------

def gh_env():
    return {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}


def gh_path():
    # щелчок по уведомлению запускает проход с коротким PATH — gh из Homebrew ищется и там
    return shutil.which("gh", path=(os.environ.get("PATH") or "") + ":/opt/homebrew/bin:/usr/local/bin") or "gh"


def pr_view(repo, pr):
    """{headRefOid, state, isDraft, title, statusCheckRollup, changedFiles} или None — gh не ответил."""
    try:
        r = subprocess.run([gh_path(), "pr", "view", str(pr), "-R", repo, "--json",
                            "headRefOid,state,isDraft,title,statusCheckRollup,changedFiles"],
                           capture_output=True, text=True, timeout=GH_TIMEOUT, env=gh_env())
        data = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return data if isinstance(data, dict) else None


def pr_files(repo, pr, view, raw=None):
    """Пути файлов PR (и previous_filename, как у шлюза guard) из REST pulls/N/files или None — gh не ответил или
    список неполон (не равен changedFiles). raw — список: в него кладутся сами записи файлов (для version_problem)."""
    count = view.get("changedFiles") if isinstance(view, dict) else None
    if not isinstance(count, int) or isinstance(count, bool):
        return None
    try:
        r = subprocess.run([gh_path(), "api", f"repos/{repo}/pulls/{pr}/files?per_page=100", "--paginate", "--jq",
                            ".[]"], capture_output=True, text=True, timeout=GH_TIMEOUT, env=gh_env())
        files = [json.loads(ln) for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if not isinstance(files, list) or len(files) != count or not all(isinstance(f, dict) for f in files):
        return None
    if raw is not None:
        raw.extend(files)
    paths = []
    for f in files:
        for k in ("filename", "previous_filename"):
            if f.get(k) is not None:
                if not isinstance(f[k], str):
                    return None
                paths.append(f[k])
    return paths


# номер версии поднимает workflow release на main после слияния (metis-0512) — как _version_problem шлюза guard:
# совпадение ответов на общих случаях сверяет test_merge. Проход сливает PR ядра мимо хука guard, поэтому сверка здесь
PLUGIN_MANIFEST_RE = re.compile(r"plugins/[^/]+/\.claude-plugin/plugin\.json")
RELEASES_FILE = ".claude-plugin/releases.json"
JSON_STR_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _touches_version(patch):
    for line in patch.splitlines():
        if line[:1] not in ("+", "-"):
            continue
        for m in JSON_STR_RE.finditer(line[1:]):
            try:
                val = json.loads(m.group(0))
            except ValueError:
                return True
            if isinstance(val, str) and val.strip().casefold() == "version":
                return True
    return False


def version_problem(files):
    """PR правит version в plugins/*/.claude-plugin/plugin.json (не новый и не удалённый файл; патча нет — тоже) или
    трогает .claude-plugin/releases.json — текст, иначе None."""
    hit = []
    for f in files:
        names = [n for n in (f.get("filename"), f.get("previous_filename")) if isinstance(n, str)]
        norm = [n.strip("/").casefold() for n in names]
        if not names:
            continue
        if RELEASES_FILE in norm:
            hit.append(f"{names[0]} (пишет только workflow release)")
        elif not any(PLUGIN_MANIFEST_RE.fullmatch(n) for n in norm) or f.get("status") in ("added", "removed"):
            continue
        elif not isinstance(f.get("patch"), str):
            hit.append(f"{names[0]} (патча нет — правку version не проверить)")
        elif _touches_version(f["patch"]):
            hit.append(f"{names[0]} (меняет version)")
    return f"PR трогает номер версии: {', '.join(hit)}" if hit else None


def is_core(path):
    """Ядро — как _is_core шлюза guard: папки CORE_DIR целиком и файлы CORE_FILES, без учёта регистра."""
    p = path.strip("/").casefold()
    while p.startswith("./"):
        p = p[2:].lstrip("/")
    return p in {c.casefold() for c in CORE_FILES} or any(p == d or p.startswith(d + "/") for d in CORE_DIR)


def ci_state(rollup):
    """(ok|wait|fail, текст). Проверок нет — wait: они ещё не встали; по 24 ч заявка всё равно гаснет."""
    if not isinstance(rollup, list):
        return "fail", "список проверок GitHub не получен"
    if not rollup:
        return "wait", "проверок GitHub пока нет"
    waiting = []
    for c in rollup:
        if not isinstance(c, dict):
            return "fail", "проверка GitHub не разобрана"
        name = str(c.get("name") or c.get("context") or "?")[:60]
        if "conclusion" in c or "status" in c and "state" not in c:   # CheckRun
            status, concl = str(c.get("status") or "").upper(), str(c.get("conclusion") or "").upper()
            if status != "COMPLETED":
                waiting.append(name)
            elif concl not in CI_OK:
                return "fail", f"проверка {name}: {concl or 'нет итога'}"
        else:                                                            # StatusContext
            st = str(c.get("state") or "").upper()
            if st in CI_WAIT:
                waiting.append(name)
            elif st not in CI_OK:
                return "fail", f"проверка {name}: {st}"
    if waiting:
        return "wait", "проверки GitHub ещё идут: " + ", ".join(waiting)
    return "ok", f"CI ✓ ({len(rollup)})"


# --- шлюз -----------------------------------------------------------------------------------------------------------

def gate(repo, pr, sha, view):
    """Шлюз на этот head заново: (ok|wait|fail, текст). Записи шлюза пишет только хук guard (роли их не подделают)."""
    if not isinstance(view, dict):
        return "wait", "gh pr view не ответил"
    if str(view.get("state") or "").upper() != "OPEN":
        return "fail", f"PR не открыт ({view.get('state')})"
    if view.get("isDraft"):
        return "fail", "PR — черновик"
    head = str(view.get("headRefOid") or "").lower()
    if head != sha:
        return "fail", f"у PR новый коммит {head[:7] or '?'} — нужна новая заявка"
    recs = P.review_records(repo)
    if not any(r.get("kind") == "tests" and r.get("sha") == sha for r in recs):
        return "fail", f"нет записи тестов шлюза на {sha[:12]}"
    latest = {}
    for r in recs:
        by = r.get("by") if isinstance(r.get("by"), dict) else {}
        if r.get("kind") in ("accept", "reject") and by.get("agent_type") == "argus" and r.get("pr") == pr \
                and r.get("sha") == sha:
            # «принять» без перечня или не на Opus не засчитывается — как будто его нет; «вернуть» любой модели в силе.
            # Правило общее с итогом `pantheon review status` (P.review_accept_counts, metis-0393)
            if r["kind"] == "accept" and not P.review_accept_counts(r):
                continue
            latest[(by.get("session_id") or "", by.get("agent_id") or "")] = r
    if any(r["kind"] != "accept" for r in latest.values()):
        return "fail", "у argus последний вердикт — «вернуть»"
    if len(latest) < MIN_ACCEPTS:
        return "fail", f"«принять» от argus на Opus — {len(latest)} из {MIN_ACCEPTS}"
    state, why = ci_state(view.get("statusCheckRollup"))
    if state != "ok":
        return state, why
    return "ok", f"argus ×{len(latest)} ✓, CI ✓"


# --- помощник Touch ID ----------------------------------------------------------------------------------------------

def helper():
    """Путь к помощнику окна или None. Только свой бинарник — STATE/bin/pantheon-touchid с отметкой sha256 исходника
    lib/touchid.swift рядом; отметка не та — пересборка. Переменной на подмену помощника нет (metis-0285, argus), а
    STATE проход берёт от HOME, не из PANTHEON_STATE (clean_env, metis-0303): окружение прохода задаёт launchd, а его
    меняет любой процесс владельца (launchctl setenv)."""
    return build_helper()


def build_helper(quiet=True):
    src = os.path.join(P.LIB, "touchid.swift")
    d = P.path("bin")
    out, mark = os.path.join(d, "pantheon-touchid"), os.path.join(d, "pantheon-touchid.sha256")
    try:
        want = hashlib.sha256(open(src, "rb").read()).hexdigest()
        ensure_dir(d)
        with contextlib.suppress(OSError):
            if open(mark).read().strip() == want and os.access(out, os.X_OK) and not os.path.islink(out):
                return out
        if not os.access(SWIFTC, os.X_OK):
            raise OSError("нет swiftc (Xcode Command Line Tools)")
        tmp, cache = out + f".new.{os.getpid()}", os.path.join(d, ".swift-cache")
        # окружение чистое: DEVELOPER_DIR, SDKROOT, TOOLCHAINS из launchctl setenv подменили бы компилятор
        r = subprocess.run([SWIFTC, "-O", "-module-cache-path", cache, "-o", tmp, src], capture_output=True,
                           text=True, timeout=300, env={"PATH": "/usr/bin:/bin", "HOME": P.HOME})
        if r.returncode != 0:
            raise OSError((r.stderr or r.stdout).strip().splitlines()[-1:] or ["swiftc упал"])
        os.chmod(tmp, 0o700)
        os.replace(tmp, out)
        with open(mark, "w") as fh:
            fh.write(want + "\n")
        return out
    except (OSError, ValueError, subprocess.SubprocessError) as e:   # ValueError: STATE/bin — ссылка или не папка
        if not quiet:
            err(f"помощник Touch ID не собран: {e}")
        return None


def window_text(req, view, why, paths):
    """Текст окна: сначала задетые файлы ядра (их владелец и подтверждает), заголовок автора PR — последним, в
    кавычках и коротко: он не перекроет список."""
    core = [p for p in dict.fromkeys(paths) if is_core(p)]
    shown, size = [], 0
    for p in core:
        if shown and size + len(p) > 200:
            break
        shown.append(p)
        size += len(p) + 2
    more = f" и ещё {len(core) - len(shown)}" if len(core) > len(shown) else ""
    hit = f"ядро: {', '.join(shown)}{more}" if core else "ядро не задето"
    title = " ".join(str(view.get("title") or "").split())[:60]
    return (f"Слить {req['repo']}#{req['pr']} ({req['sha'][:7]}), файлов {len(set(paths))}, {hit}. {why}. "
            f"Заголовок: «{title}»")[:400]


def ask(text):
    """Код помощника: 0 — палец, 1 — отказ, 2 — окно не показать, 3 — время вышло; None — помощника нет."""
    h = helper()
    if not h:
        return None
    try:
        return subprocess.run([h, text, str(WINDOW_WAIT)], stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=WINDOW_WAIT + 60).returncode
    except (OSError, subprocess.SubprocessError):
        return 2


def approve(req):
    """Строка согласия владельца — её сверяет шлюз guard. Пишет только этот проход, после пальца."""
    d = P.path("owner-log")
    if os.path.islink(d):
        raise OSError("owner-log — ссылка")
    ensure_dir(d)
    line = (f"{datetime.fromtimestamp(P.now()).astimezone().isoformat(timespec='seconds')} merge-approve "
            f"{req['repo']}#{req['pr']} {req['sha']}\n")
    fd = os.open(os.path.join(d, APPROVE_FILE), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(line)


def gh_merge(req):
    try:
        r = subprocess.run([gh_path(), "pr", "merge", str(req["pr"]), "-R", req["repo"], "--match-head-commit",
                            req["sha"], "--merge"], capture_output=True, text=True, timeout=MERGE_TIMEOUT, env=gh_env())
        return r.returncode, " ".join((r.stderr or r.stdout).split())[:200]
    except (OSError, subprocess.SubprocessError) as e:
        return 1, type(e).__name__


def fallback_notify(req, window):
    """Запасной путь: уведомление, щелчок по которому запускает `pantheon merge run --click` от имени владельца.
    window — текст окна (задетое ядро, заголовок PR)."""
    # путь программы — realpath: ссылку current после проверки не перевесить (argus-b 0303, п. 2)
    base = os.path.realpath(P.CURRENT if os.path.isdir(P.CURRENT) else P.PLUGIN)
    # щелчок запускает команду в окружении уведомления (launchd): окружение и интерпретатор — свои, через env -i
    env = " ".join(shlex.quote(f"{k}={v}") for k, v in pass_env().items())
    cmd = f"/usr/bin/env -i {env} {shlex.quote(os.path.join(base, 'bin', 'pantheon'))} merge run --click"
    text = f"{window[:300]}. Щёлкните — откроется окно Touch ID"
    line = f"Слияние ядра|{text}|execute:{cmd}|merge\n"
    if os.environ.get("PANTHEON_NOTIFY_LOG"):   # только из TEST: clean_env окружение launchd сняла
        with open(os.environ["PANTHEON_NOTIFY_LOG"], "a", encoding="utf-8") as fh:
            fh.write(line)
        return True
    tn = P._notifier()
    if not tn or os.environ.get("PANTHEON_NO_NOTIFY"):
        return False
    if P.notify_offscreen():   # STATE не настоящая (тест, проба) — на экран владельца не показывать
        with open(P.path("notify-test.log"), "a", encoding="utf-8") as fh:
            fh.write(line)
        return True
    r = subprocess.run([tn, "-title", "Слияние ядра", "-message", text, "-execute", cmd, "-group", "pantheon-merge"],
                       capture_output=True, timeout=15)
    return r.returncode == 0


# --- команды --------------------------------------------------------------------------------------------------------

def parse_target(args):
    """<N> -R <owner/repo> в любом порядке → (repo, pr) или None."""
    if len(args) != 3 or "-R" not in args[:2]:
        return None
    i = args.index("-R")
    repo = args[i + 1].lower() if i + 1 < len(args) else ""
    rest = [a for j, a in enumerate(args) if j not in (i, i + 1)]
    if len(rest) != 1 or not PR_RE.fullmatch(rest[0]) or not REPO_RE.fullmatch(repo):
        return None
    return repo, int(rest[0])


def cmd_request(args):
    target = parse_target(args)
    if not target:
        err(USAGE)
        return 2
    repo, pr = target
    if repo not in allowed_repos():
        err(f"pantheon merge request: {repo} не из [merge_repos] {MERGE_DIRECTION} в policy.toml — заявки нет")
        return 2
    view = pr_view(repo, pr)
    if view is None:
        err(f"pantheon merge request: gh pr view {pr} -R {repo} не ответил — заявки нет")
        return 1
    sha = str(view.get("headRefOid") or "").lower()
    if not SHA_RE.fullmatch(sha):
        err("pantheon merge request: у PR нет head SHA — заявки нет")
        return 1
    state, why = gate(repo, pr, sha, view)
    if state == "fail":
        err(f"pantheon merge request: шлюз не пройден — {why}. Заявки нет")
        return 1
    who = " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "владелец").split())[:40]
    req = {"repo": repo, "pr": pr, "sha": sha, "by": who, "created": int(P.now())}
    with P.lock("merge-queue"):
        old = read_req(req_file(repo, pr)) if os.path.lexists(req_file(repo, pr)) else None
        if old and old["sha"] == sha:
            print(f"заявка {repo}#{pr} ({sha[:7]}) уже стоит")
            return 0
        write_req(req)
    log(req, "request")
    print(f"Заявка {repo}#{pr} ({sha[:7]}) поставлена. Окно Touch ID покажет плановый проход, когда вы у Mac"
          + ("" if state == "ok" else f" и {why.lower()} закончатся") + f"; без ответа за {REQUEST_TTL // 3600} ч "
          "заявка гаснет.")
    return 0


def check_all(req):
    """Все условия заново: (ok|wait|fail, текст, view, пути файлов). Репозиторий — из [merge_repos] сейчас, шлюз — на
    тот же head, список файлов PR полон (окно показывает задетое ядро)."""
    if req["repo"] not in allowed_repos():
        return "fail", f"{req['repo']} больше не в [merge_repos] {MERGE_DIRECTION}", None, None
    view = pr_view(req["repo"], req["pr"])
    state, why = gate(req["repo"], req["pr"], req["sha"], view)
    if state != "ok":
        return state, why, view, None
    raw = []
    paths = pr_files(req["repo"], req["pr"], view, raw)
    if paths is None:
        return "wait", "список файлов PR не получен или неполон", view, None
    bad = version_problem(raw)
    if bad:
        return "fail", f"{bad} — номер поднимает workflow release после слияния (metis-0512)", view, None
    return "ok", why, view, paths


def process(req, click):
    t = P.now()
    if t - req["created"] > REQUEST_TTL:
        return drop(req, "expired", f"{REQUEST_TTL // 3600} ч без ответа", warn=True)
    if not click and req.get("wait_until", 0) > t:
        return "ждёт: окно закрыто без ответа, повтор позже"
    if not click and req.get("notified"):
        return "ждёт щелчка по уведомлению"
    state, why, view, paths = check_all(req)  # заново, на тот же head (Решено, бриф 0285)
    if state == "fail":
        return drop(req, "gate", why, warn=True)
    if state == "wait":
        return f"ждёт: {why}"
    if not click and P.idle_sec() > PRESENT_SEC:
        return "ждёт: вас нет у Mac"
    text = window_text(req, view, why, paths)
    rc = ask(text)
    if rc is None:
        P.alert_once("merge-helper", "1", "слияние по Touch ID: помощник окна не собран (swiftc) — заявки ждут; "
                     "собрать: pantheon install", "pantheon-merge")
        return "ждёт: помощника окна нет"
    log(req, "window", rc=rc, click=click)
    if rc == 0:
        # окно было открыто до двух минут: отмена, новый «вернуть», новый коммит или правка [merge_repos] за это
        # время — не сливать. Сверка и снятие заявки — под замком merge-queue, как у request и cancel
        with P.lock("merge-queue"):
            if not same_req(req):
                return gone(req, rc)
            state, why, _, _ = check_all(req)
            if state != "ok":
                os.remove(req_file(req["repo"], req["pr"]))
                bad = f"после пальца условия изменились — {why}"
            else:
                bad = None
                approve(req)
                os.remove(req_file(req["repo"], req["pr"]))   # одно применение — до слияния, сбой gh её не вернёт
        if bad:
            log(req, "gate-after")
            P.alert(f"слияние {req['repo']}#{req['pr']} ({req['sha'][:7]}) по Touch ID: не слито, заявка снята — {bad}",
                    "pantheon-merge")
            return f"снята: {bad}"
        code, out = gh_merge(req)
        log(req, "merged" if code == 0 else "merge-failed", rc=code)
        if code != 0:
            P.alert(f"слияние {req['repo']}#{req['pr']} ({req['sha'][:7]}) после Touch ID не прошло: {out}. Согласие "
                    "записано — шлюз guard пустит слияние этого SHA в течение суток", "pantheon-merge")
            return f"палец есть, gh pr merge упал ({code})"
        return "слит"
    if rc == 1:
        return drop(req, "refused", "вы отказали")
    if rc == 3:
        req["wait_until"] = int(t + RETRY_SEC)
        if not keep(req):
            return gone(req, rc)
        return "окно закрыто без ответа — повтор позже"
    if rc == 2 and not click:
        with P.lock("merge-queue"):
            still = same_req(req)
        if not still:   # сняли, пока помощник пробовал окно, — и уведомления нет
            return gone(req, rc)
        if fallback_notify(req, text):
            req["notified"] = int(t)
            if not keep(req):
                return gone(req, rc)
            log(req, "notified")
            return "окно из прохода не показать — уведомление, ждёт щелчка"
        return drop(req, "no-window", "окно Touch ID не показать и уведомление не ушло", warn=True)
    return drop(req, "no-window", f"окно Touch ID не показано (код {rc})", warn=True)


def cmd_run(click=False):
    # переменная есть, пусть и пустая, — окно Claude Code: сливает только проход или щелчок владельца
    if "CLAUDECODE" in os.environ or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        err("pantheon merge run: только плановый проход или щелчок по уведомлению, не из окна Claude Code")
        return 2
    why = clean_env()
    if why:
        err(f"pantheon merge run: {why} — окружение прохода подменено (launchctl setenv?), прохода нет")
        return 2
    r = root()
    if not _real_dir(r):
        return 0
    with P.lock("merge-run", block=False) as got:
        if not got:
            print("pantheon merge run: идёт другой проход")
            return 0
        rc = 0
        for f in sorted(os.listdir(r)):
            p = os.path.join(r, f)
            if not FILE_RE.fullmatch(f):
                continue
            with P.lock("merge-queue"):
                req = read_req(p)
                if req is None:
                    with contextlib.suppress(OSError):
                        os.remove(p)
            if req is None:
                print(f"{f}: битая заявка — удалена")
                continue
            try:
                print(f"{req['repo']}#{req['pr']}: {process(req, click)}")
            except Exception as e:  # одна заявка не останавливает другие; сбойная снимается — окно не повторяется
                rc = 1
                with contextlib.suppress(Exception):
                    drop(req, "error", f"сбой прохода ({type(e).__name__}: {e})", warn=True)
                print(f"{req['repo']}#{req['pr']}: сбой ({type(e).__name__}) — заявка снята")
        return rc


def pending():
    """Есть ли заявки — для тика: процесс прохода запускается, только когда есть что делать."""
    r = root()
    try:
        return _real_dir(r) and any(FILE_RE.fullmatch(f) for f in os.listdir(r))
    except OSError:
        return False


def cmd_status():
    r, rows, t = root(), [], P.now()
    if _real_dir(r):
        for f in sorted(os.listdir(r)):
            req = read_req(os.path.join(r, f)) if FILE_RE.fullmatch(f) else None
            if req:
                marks = (" уведомление" if req.get("notified") else "") + (" повтор позже" if req.get("wait_until", 0) > t else "")
                rows.append(f"{req['repo']}#{req['pr']}\t{req['sha'][:12]}\t{int((t - req['created']) // 60)} мин\t"
                            f"{req.get('by', '?')}{marks}")
    print("\n".join(rows) if rows else "заявок нет")
    return 0


def cmd_cancel(args):
    target = parse_target(args)
    if not target:
        err(USAGE)
        return 2
    repo, pr = target
    p = req_file(repo, pr)
    with P.lock("merge-queue"):
        if not os.path.lexists(p):
            print(f"заявки {repo}#{pr} нет")
            return 0
        req = read_req(p) or {"repo": repo, "pr": pr, "sha": None}
        os.remove(p)
    log(req, "cancelled")
    print(f"заявка {repo}#{pr} снята")
    return 0


def main(rest):
    sub = rest[0] if rest else ""
    if sub == "request":
        return cmd_request(rest[1:])
    if sub == "cancel":
        return cmd_cancel(rest[1:])
    if sub == "run" and rest[1:] in ([], ["--click"]):
        return cmd_run(click=rest[1:] == ["--click"])
    if sub == "status" and len(rest) == 1:
        return cmd_status()
    if sub == "build" and len(rest) == 1:   # помощник окна — pantheon install зовёт сам
        out = build_helper(quiet=False)
        print(out or "не собран")
        return 0 if out else 1
    err(USAGE)
    return 2
