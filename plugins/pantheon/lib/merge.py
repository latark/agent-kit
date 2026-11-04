"""Слияние PR ядра одним Touch ID (metis-0285; владелец выбрал Touch ID, Зевс 19.10).

PR ядра защит (Д3) агенты не сливают: его сливает владелец. Чтобы не набирать gh в терминале, роль ставит заявку, а
плановый проход (launchd, сессия владельца, вне песочницы окон) показывает системное окно Touch ID и после пальца
сливает ровно проверенный коммит.

  pantheon merge request <N> -R <owner/repo>   заявка: STATE/merge-queue/<owner>__<repo>__<N>.json (папка 0700,
                                                файл 0600) с head SHA PR сейчас. Репозиторий — из [merge_repos]
                                                metis-pantheon (policy.toml); шлюз проверяется сразу (кроме CI в работе)
  pantheon merge request <N1> <N2> … -R <owner/repo>   пачка (metis-0668, до MAX_BATCH PR одного репозитория):
                                                по заявке на каждый PR с полем batch — номера в порядке слияния;
                                                шлюз не пройден хоть у одного — заявок нет ни на один
  pantheon merge run [--click]   проход по заявкам: зовёт его тик (из окна Claude Code — отказ, guard ролям тоже не даёт);
                                 --click — щелчок по уведомлению запасного пути: владелец у Mac
  pantheon merge status          заявки: репозиторий#N, SHA, возраст, отметки
  pantheon merge cancel <N> -R <owner/repo>    снять заявку (из пачки — вместе со всей пачкой)

Проход по каждой заявке (одна заявка — одно применение):
  1. Старше REQUEST_TTL (24 ч) — снята.
  2. PR сейчас (gh pr view): не OPEN, черновик или head не тот SHA, что в заявке, — снята (новый коммит — новая заявка).
  3. Репозиторий всё ещё в [merge_repos] metis-pantheon. Шлюз заново на тот же head: запись тестов шлюза на SHA; у
     каждого рецензента argus последний вердикт — «принять» с полным перечнем и на Opus (по ran и, если хук guard
     записал их, по моделям транскрипта argus — metis-0176), рецензентов-«принять» не
     меньше двух, «вернуть» нет; проверки GitHub (CI) — тот же разбор ci_verdict, что у шлюза guard (metis-0633):
     обязательные из REQUIRED_CHECKS — запуск Actions от pull_request на этом SHA с SUCCESS (ci_runs_fetch, дубль —
     худший итог; PR из форка — запуск с head_repository и head_branch его форка и ветки, ci_fork, metis-0649), у
     репозитория без записи — все проверки rollup. CI ещё идёт, обязательной или любых проверок пока
     нет, запуски не получены — заявка ждёт; красная или SKIPPED — снята с тревогой, кроме CI, который не
     запускался из-за лимита минут или оплаты GitHub Actions (ci_billing по аннотациям красных и данным их job —
     job не стартовал, metis-0655): тогда вместо CI засчитывается запись тестов шлюза на SHA с командой полного
     набора FULL_TESTS (full_tests_record); нет такой — снята с тревогой.
     Список файлов PR (REST pulls/N/files) полон — иначе ждёт: окно показывает задетые файлы ядра, без списка их не
     показать. PR правит version в plugin.json плагина или трогает
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

Пачка (metis-0668, process_batch) — одно окно на все её PR: в тексте — сначала задетое ядро всех и число файлов, затем
каждый PR с SHA и вердиктом шлюза по порядку, заголовки последними. До окна пункты 1–3 — у каждого: неполна (одну заявку сняли или заменили) или
шлюз не пройден хоть у одного — сняты все с тревогой, ждёт один — ждут все. После пальца — по очереди, каждый как
одна заявка в п. 4 (шлюз заново под замком, строка согласия, `gh pr merge --match-head-commit` своего SHA). Не слит
один (шлюз, сбой gh, заявку сняли) — следующие не трогаются: ни согласия, ни слияния; их заявки сняты, тревога
с итогом по каждому. Отказ, время вышло, уведомление — сразу на всю пачку.

Управляемые настройки guard (metis-0710, «да» владельца 02.11 21:57). Тот же проход, под тем же замком: файл
P.MANAGED (/Library/…/managed-settings.json) не совпал с managed-settings.json проверенного дерева guard
(installed_dir: хеш дерева = verified.json) — владелец у Mac — системное окно прав администратора (osascript … with
administrator privileges: Touch ID или пароль) «Обновить управляемые настройки guard до версии X». После касания root
копирует файл рядом, сверяет sha256 с прочитанным проходом и переносит на место (root:wheel, 644). Отказ или
MANAGED_WAIT без касания — карточка «Руками» с командой sudo install и тревога; окно на ту же версию — не чаще
MANAGED_RETRY (STATE/managed-update.json; попытка пишется до окна, и оборванный после окна проход её не теряет).
Файл совпал (по касанию или командой) — тик закрывает карточку. Файла в
/Library нет — не отставание: первый раз его ставит владелец. Тик зовёт проход и без заявок, когда отстали
(managed_check).
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
MAX_BATCH = 5                        # PR в одной пачке: их номера, SHA и ядро — в окне не длиннее 400 знаков
# вердикт шлюза на запасном пути (metis-0655); в окне пачки он короче — BILLING_SHORT (argus-263a Б1)
BILLING_OK = "CI не запускался (лимит минут GitHub Actions) — засчитан местный прогон тестов на "
BILLING_SHORT = "CI: лимит, тесты ✓"
USAGE = ("pantheon merge request <N> [<N2> …] -R <owner/repo> | cancel <N> -R <owner/repo> | run [--click] | "
         "status")


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
    if "batch" in data and not valid_batch(data["batch"], data["pr"]):
        return None
    return data


def valid_batch(batch, pr):
    """Пачка заявки (metis-0668): список номеров PR одного репозитория в порядке слияния, от 2 до MAX_BATCH, без
    повторов, с номером самой заявки."""
    return isinstance(batch, list) and 2 <= len(batch) <= MAX_BATCH and pr in batch \
        and all(type(n) is int and PR_RE.fullmatch(str(n)) for n in batch) and len(set(batch)) == len(batch)


def batch_key(req):
    """Чья пачка: (репозиторий, номера по порядку, время постановки) или None — заявка одна. Заявки одной пачки
    ставятся одним `merge request` под одним замком: ключ у них общий, у заявок другой постановки — свой."""
    return (req["repo"], tuple(req["batch"]), req["created"]) if req.get("batch") else None


def batch_members(req):
    """Заявки пачки req в очереди сейчас, по порядку слияния: только с тем же ключом (batch_key). Звать под замком
    merge-queue."""
    out = []
    for n in req["batch"]:
        p = req_file(req["repo"], n)
        cur = read_req(p) if os.path.lexists(p) else None
        if cur and batch_key(cur) == batch_key(req):
            out.append(cur)
    return out


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
    """{headRefOid, state, isDraft, title, baseRefName, statusCheckRollup, changedFiles, isCrossRepository,
    headRepository, headRefName} или None — gh не ответил. Последние три — голова PR из форка (ci_fork, metis-0649)."""
    try:
        r = subprocess.run([gh_path(), "pr", "view", str(pr), "-R", repo, "--json",
                            "headRefOid,state,isDraft,title,baseRefName,statusCheckRollup,changedFiles,"
                            "isCrossRepository,headRepository,headRefName"],
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


# проверки GitHub на head PR (metis-0285, 0633, 0649, 0655): ci_verdict, ci_runs, ci_fork, ci_billing_ids,
# ci_billing, ci_job_unstarted, full_tests_record, required_checks, optional_checks, REQUIRED_CHECKS, OPTIONAL_CHECKS,
# CI_RUNS_API, CI_BILLING, CI_ANNOTATIONS_API, CI_JOBS_API, FULL_TESTS, CI_OK, CI_WAIT и CI_NONE —
# дословно те же, что в шлюзе guard (plugins/guard/hooks/merge_gate.py): плагины порознь,
# друг друга не импортируют, совпадение сверяет test_merge по AST. Правишь — правь оба
CI_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
CI_WAIT = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", ""}
CI_NONE = "проверки GitHub не получены"
# обязательные проверки (metis-0633): имя репозитория без владельца → (workflow, job, ветка base PR или None — любая).
# Имена — из .github/workflows репозитория: tests.yml гоняет job affected только на PR в main (job full на PR всегда
# SKIPPED — его здесь нет), check-traces.yml — job traces на любой PR (и на push: две записи traces на одном SHA).
# Совпадение с файлами workflows сверяет test_merge_gate. Обязательная засчитывается только по запуску Actions от
# события pull_request на этом head (ci_runs) и только с итогом SUCCESS: SKIPPED закрыл бы её job, который не
# запускался, push-запуск проверяет ветку без слияния с base, а NEUTRAL у job Actions не бывает — его ставят
# сторонние приложения проверок. Нет такого запуска — «ещё не встала», а не пропуск. Другие проверки репозитория:
# красная из OPTIONAL_CHECKS — предупреждение, красная любая другая — отказ (Д1 argus #235: новый job на PR, не
# внесённый ни в один список, не проходит шлюз молча). Репозиторий без записи — обязательна каждая проверка его rollup
# (SUCCESS/NEUTRAL/SKIPPED).
REQUIRED_CHECKS = {"agent-kit": (("tests", "affected", "main"), ("check-traces", "traces", None))}
# необязательные проверки (Д1 argus #235): имя репозитория без владельца → (workflow, job, почему необязательна — с
# номером задачи). Каждый job workflows, который идёт на pull_request, — в REQUIRED_CHECKS или здесь: сверяет
# test_merge_gate по файлам .github/workflows
OPTIONAL_CHECKS = {"agent-kit": (("tests", "full", "metis-0633: на pull_request всегда SKIPPED, идёт после слияния"),)}
# запуски Actions на head SHA: два GET REST (GraphQL — POST, его правило push ролям закрывает), связь — check_suite_id
CI_RUNS_API = ("repos/{repo}/actions/runs?head_sha={sha}&per_page=100",
               "repos/{repo}/commits/{sha}/check-runs?per_page=100")
# CI не запускался из-за лимита минут или оплаты GitHub Actions (metis-0655). Признак — по ответам GitHub, а не по
# памяти: в документации текста нет (docs.github.com: «usage is blocked», check-runs: conclusion и output), поэтому —
# по сохранённому ответу PR #222 (31.10, plugins/guard/tests/fixtures/ci-runs-pr222.json):
# проверка от Actions завершена с FAILURE, аннотация уровня failure на путь .github с этим текстом (запрос
# CI_ANNOTATIONS_API — только к таким проверкам).
# Текст поменяется — признака нет и отказ, как на любой красной.
# Аннотацию с тем же текстом может напечатать и сам job PR (`::error file=.github::…`), поэтому второе условие —
# job не стартовал (CI_JOBS_API, id проверки = id job): раннера не было и шагов нет. Это поле пишет GitHub, а не код
# job (docs.github.com/en/rest/actions/workflow-jobs: runner_id «integer or null», runner_name «string or null»,
# steps — массив; у заблокированных job PR #222 — 0, "" и [], у обычной красной PR #225 — номер раннера и 8 шагов)
CI_BILLING = ("The job was not started because recent account payments have failed or your spending limit needs to be "
              "increased")
CI_ANNOTATIONS_API = "repos/{repo}/check-runs/{id}/annotations?per_page=100"
CI_JOBS_API = "repos/{repo}/actions/jobs/{id}"
# полный набор тестов для записи на запасном пути (metis-0655): имя репозитория без владельца → команда после
# `pantheon review test --`. Засчитывается только запись с этой командой (full_tests_record); нет строки — запасного
# пути у репозитория нет, отказ
FULL_TESTS = {"agent-kit": ("heavy python3.14 -I plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard "
                            "plugins/pantheon plugins/project-tools")}


def required_checks(repo, base):
    """Обязательные (workflow, job) для PR в repo (owner/name) с веткой base; base не строка — все записи."""
    got = REQUIRED_CHECKS.get(str(repo or "").rsplit("/", 1)[-1].lower(), ())
    return tuple((w, j) for w, j, b in got if b is None or not isinstance(base, str) or b == base)


def ci_fork(view):
    """Голова PR из форка по ответу gh pr view (metis-0649): None — isCrossRepository не true (PR из того же
    репозитория), иначе (owner/name форка в нижнем регистре, ветка head) из headRepository.nameWithOwner и
    headRefName; поле не строка — пустая строка на его месте, и ci_runs отвечает «не получены»."""
    if not isinstance(view, dict) or view.get("isCrossRepository") is not True:
        return None
    repo, branch = view.get("headRepository"), view.get("headRefName")
    name = repo.get("nameWithOwner") if isinstance(repo, dict) else None
    return (name.lower() if isinstance(name, str) else "", branch if isinstance(branch, str) else "")


def optional_checks(repo):
    """Необязательные (workflow, job) repo (owner/name) из OPTIONAL_CHECKS: их красная — только предупреждение."""
    return tuple((w, j) for w, j, _ in OPTIONAL_CHECKS.get(str(repo or "").rsplit("/", 1)[-1].lower(), ()))


def ci_runs(workflow_runs, check_runs, sha, pr, fork=None):
    """Запуски Actions PR pr на коммите sha с событием: [{workflowName, name, status, conclusion, event, id,
    annotations}] (id проверки и число её аннотаций — для ci_billing, metis-0655) по ответам
    CI_RUNS_API (actions/runs и check-runs). Не идут в список: проверка без запуска Actions с тем же check_suite_id
    (стороннее приложение с тем же именем), чужой head_sha и запуск, в pull_requests которого нет этого PR (запуск
    чужого PR на том же SHA). PR из форка (fork — ответ ci_fork, metis-0649): у его запусков GitHub pull_requests не
    заполняет, поэтому засчитывается запуск от pull_request, у которого head_repository.full_name и head_branch —
    форк и ветка этого PR (фильтру REST не верим, поля сверяются здесь); форк или ветка не получены — строка «не
    получены». Ответ неполон (total_count больше полученного: per_page=100 без пагинации, скрытой может быть красная
    запись) — строка «неполные данные CI»; не разобран — None."""
    if fork is not None and not all(fork):
        return f"{CI_NONE}: PR из форка, а его репозиторий или ветка head не получены (gh pr view)"
    try:
        wr, cr = workflow_runs["workflow_runs"], check_runs["check_runs"]
        if workflow_runs["total_count"] > len(wr) or check_runs["total_count"] > len(cr):
            return (f"{CI_NONE}: неполные данные CI — запусков {workflow_runs['total_count']} и проверок "
                    f"{check_runs['total_count']}, а получено {len(wr)} и {len(cr)}")
        if fork is None:
            suites = {r["check_suite_id"]: r for r in wr
                      if r["head_sha"] == sha and str(pr) in [str(p["number"]) for p in r["pull_requests"]]}
        else:
            suites = {r["check_suite_id"]: r for r in wr
                      if r["head_sha"] == sha and r["event"] == "pull_request"
                      and r["head_repository"]["full_name"].lower() == fork[0] and r["head_branch"] == fork[1]}
        out = []
        for c in cr:
            run = suites.get(c["check_suite"]["id"])
            if run is not None and c["head_sha"] == sha:
                info = c.get("output") if isinstance(c.get("output"), dict) else {}
                out.append({"workflowName": str(run.get("name") or ""), "name": str(c.get("name") or ""),
                            "status": str(c.get("status") or ""), "conclusion": str(c.get("conclusion") or ""),
                            "event": str(run.get("event") or ""), "id": c.get("id"),
                            "annotations": info.get("annotations_count")})
        return out
    except (TypeError, KeyError, AttributeError):
        return None


def ci_billing_ids(runs, required):
    """id проверок, чьи аннотации нужны для признака «CI не запускался: лимит минут или оплата» (metis-0655): каждая
    обязательная (required) есть среди runs от pull_request, у каждой её запись завершена с SUCCESS или с FAILURE,
    id — целое и аннотации есть; хоть одна FAILURE. Иначе пусто: признака нет, и запросов аннотаций шлюз не делает."""
    if not isinstance(runs, list):
        return []
    must, seen, ids = [tuple(r) for r in required], set(), []
    for c in runs:
        if not isinstance(c, dict) or c.get("event") != "pull_request":
            continue
        key = (str(c.get("workflowName") or ""), str(c.get("name") or ""))
        if key not in must:
            continue
        seen.add(key)
        status, concl = str(c.get("status") or "").upper(), str(c.get("conclusion") or "").upper()
        if status == "COMPLETED" and concl == "SUCCESS":
            continue
        n = c.get("annotations")
        if status != "COMPLETED" or concl != "FAILURE" or type(c.get("id")) is not int or type(n) is not int or n < 1:
            return []
        ids.append(c["id"])
    return ids if all(k in seen for k in must) else []


def ci_job_unstarted(job):
    """Job не стартовал (metis-0655): ответ CI_JOBS_API — словарь, где runner_id 0 или null, runner_name пусто или
    null и steps — пустой список. Ключа нет, тип другой, ответа нет — стартовал (признака лимита нет)."""
    if not isinstance(job, dict) or "runner_id" not in job or "runner_name" not in job:
        return False
    rid = job["runner_id"]
    return (rid is None or type(rid) is int and rid == 0) and job["runner_name"] in (None, "") \
        and job.get("steps") == []


def ci_billing(runs, required, notes, jobs):
    """CI не запускался из-за лимита минут или оплаты (metis-0655): ci_billing_ids не пуст и у каждой такой проверки
    в notes ({id: ответ CI_ANNOTATIONS_API — список}) есть аннотация уровня failure на путь .github, текст которой
    начинается с CI_BILLING, и её job в jobs ({id: ответ CI_JOBS_API}) не стартовал (ci_job_unstarted). Ответа нет
    (сбой gh) или он не того типа — признака нет."""
    ids = ci_billing_ids(runs, required)
    return bool(ids) and isinstance(notes, dict) and isinstance(jobs, dict) and all(
        isinstance(notes.get(i), list) and any(
            isinstance(a, dict) and a.get("annotation_level") == "failure" and a.get("path") == ".github"
            and str(a.get("message") or "").startswith(CI_BILLING) for a in notes[i])
        and ci_job_unstarted(jobs.get(i)) for i in ids)


def full_tests_record(repo, rec):
    """Запись tests — полный прогон этого репозитория (metis-0655): её команда — FULL_TESTS репозитория (имя без
    владельца, регистр не важен). Хук guard пишет всю команду `pantheon review test -- <команда>`, проход `pantheon
    outside test` — саму команду; `heavy` впереди не важен — проход ставит его сам. Комментарий — как в bash, только
    «#» в начале слова (после пробела): хвост ` # …` снимается, а `слово#…` — часть слова, и команда уже другая.
    Другая команда, лишние слова (`&& …`, `; …`), нет строки в FULL_TESTS — не засчитывается."""
    want = FULL_TESTS.get(str(repo or "").rsplit("/", 1)[-1].lower())
    cmd = rec.get("cmd") if isinstance(rec, dict) else None
    if not want or not isinstance(cmd, str):
        return False
    try:
        got, need = shlex.split(re.sub(r"\s#.*\Z", "", cmd, flags=re.S)), shlex.split(want)
    except ValueError:
        return False
    if len(got) > 3 and os.path.basename(got[0].rstrip("/")) == "pantheon" and got[1:4] == ["review", "test", "--"]:
        got = got[4:]
    got = got[1:] if got[:1] and os.path.basename(got[0]) == "heavy" else got
    need = need[1:] if need[:1] and os.path.basename(need[0]) == "heavy" else need
    return got == need


def ci_verdict(rollup, required=(), runs=None, optional=()):
    """(ok|wait|fail|empty, текст, предупреждения) по statusCheckRollup head PR. CheckRun — по status и conclusion,
    StatusContext — по state; ключ проверки — (workflowName, name) или context. Итог ключа — худший из его записей:
    дубль имени (push и pull_request на одном SHA) не прячет красную запись зелёной. required — обязательные
    (workflow, job): судятся только по runs (ci_runs) от события pull_request, зелёный итог — только SUCCESS; красная
    или пропущенная — fail, нет такого запуска или идёт — wait, runs не получены или неполны (строка) — fail.
    Остальные проверки rollup: красная из optional (optional_checks) — предупреждение, красная любая другая — fail
    (Д1 argus #235). required пуст — обязательна каждая проверка rollup (SUCCESS, NEUTRAL, SKIPPED), пустой rollup —
    empty."""
    if not isinstance(rollup, list) or required and not isinstance(runs, (list, str)):
        return "fail", CI_NONE, []
    if required and isinstance(runs, str):
        return "fail", runs, []
    rank = {"ok": 0, "wait": 1, "fail": 2}
    seen, pr_runs = {}, {}  # ключ → (итог, слово итога, имя для текста)
    for c in rollup:
        if not isinstance(c, dict):
            return "fail", f"{CI_NONE}: проверка не разобрана", []
        if "conclusion" in c or "status" in c and "state" not in c:   # CheckRun
            status, concl = str(c.get("status") or "").upper(), str(c.get("conclusion") or "").upper()
            res = "wait" if status != "COMPLETED" else "ok" if concl in CI_OK else "fail"
            word = (status or "нет статуса") if res == "wait" else (concl or "нет итога")
            key = (str(c.get("workflowName") or ""), str(c.get("name") or ""))
        else:                                                            # StatusContext
            st = str(c.get("state") or "").upper()
            res = "wait" if st in CI_WAIT else "ok" if st in CI_OK else "fail"
            word = st or "нет статуса"
            key = ("", str(c.get("context") or ""))
        if key not in seen or rank[res] > rank[seen[key][0]]:
            seen[key] = (res, word, ("/".join(k for k in key if k) or "?")[:60])
    for c in runs or ():
        if not isinstance(c, dict) or c.get("event") != "pull_request":
            continue
        status, concl = str(c.get("status") or "").upper(), str(c.get("conclusion") or "").upper()
        res = "wait" if status != "COMPLETED" else "ok" if concl == "SUCCESS" else "fail"
        word = (status or "нет статуса") if res == "wait" else (concl or "нет итога")
        key = (str(c.get("workflowName") or ""), str(c.get("name") or ""))
        if key not in pr_runs or rank[res] > rank[pr_runs[key][0]]:
            pr_runs[key] = (res, word, "/".join(key)[:60])
    must = [tuple(r) for r in required] or list(seen)
    judge = pr_runs if required else seen
    if not must:
        return "empty", "", []
    opt = [tuple(r) for r in optional]
    notes = [f"необязательная проверка GitHub {v[2]} красная: {v[1]}" for k, v in seen.items()
             if k not in must and k in opt and v[0] == "fail"]
    red = [f"проверка GitHub {judge[k][2]} {'красная' if judge[k][1] not in CI_OK else 'не прошла'}: {judge[k][1]}"
           for k in must if k in judge and judge[k][0] == "fail"]
    red += [f"проверка GitHub {v[2]} красная: {v[1]} (её нет ни в обязательных, ни в необязательных — красная любая "
            "проверка на PR — отказ)" for k, v in seen.items() if k not in must and k not in opt and v[0] == "fail"]
    if red:
        return "fail", "; ".join(red), notes
    missing = ["/".join(k) for k in must if k not in judge]
    if missing:
        return ("wait", "обязательные проверки GitHub ещё не встали (засчитывается запуск от pull_request на этом "
                "коммите): " + ", ".join(missing), notes)
    going = [judge[k][2] for k in must if judge[k][0] == "wait"]
    if going:
        return "wait", "проверки GitHub ещё идут: " + ", ".join(going), notes
    return "ok", "", notes


def ci_runs_fetch(repo, pr, sha, fork=None):
    """Запуски Actions на head SHA с событием (metis-0633): два GET REST по CI_RUNS_API, список ci_runs или None —
    gh не ответил или ответ не разобран; fork — голова PR из форка (ci_fork, metis-0649)."""
    got = []
    for api in CI_RUNS_API:
        try:
            r = subprocess.run([gh_path(), "api", api.format(repo=repo, sha=sha)], capture_output=True, text=True,
                               timeout=GH_TIMEOUT, env=gh_env())
            got.append(json.loads(r.stdout) if r.returncode == 0 else None)
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        if got[-1] is None:
            return None
    return ci_runs(got[0], got[1], sha, pr, fork)


def ci_notes_fetch(repo, ids):
    """Аннотации проверок ids (metis-0655): {id: список по CI_ANNOTATIONS_API или None — gh не ответил или ответ не
    разобран}. ids — из ci_billing_ids; пусто — запросов нет."""
    out = {}
    for i in ids:
        try:
            r = subprocess.run([gh_path(), "api", CI_ANNOTATIONS_API.format(repo=repo, id=i)], capture_output=True,
                               text=True, timeout=GH_TIMEOUT, env=gh_env())
            out[i] = json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, ValueError, subprocess.SubprocessError):
            out[i] = None
    return out


def ci_jobs_fetch(repo, ids):
    """Данные job проверок ids (metis-0655): {id: ответ CI_JOBS_API или None — gh не ответил или ответ не разобран};
    id проверки = id job. ids — из ci_billing_ids; пусто — запросов нет."""
    out = {}
    for i in ids:
        try:
            r = subprocess.run([gh_path(), "api", CI_JOBS_API.format(repo=repo, id=i)], capture_output=True,
                               text=True, timeout=GH_TIMEOUT, env=gh_env())
            out[i] = json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, ValueError, subprocess.SubprocessError):
            out[i] = None
    return out


def ci_state(rollup, required=(), runs=None, optional=()):
    """(ok|wait|fail, текст, предупреждения о красных необязательных) по ci_verdict. Проверок нет — wait: они ещё не
    встали; по 24 ч заявка всё равно гаснет. Обязательные есть, а запуски Actions не получены (runs None) — тоже wait:
    сбой gh не снимает заявку."""
    if required and runs is None:
        return "wait", "запуски Actions на head PR не получены", []
    state, why, notes = ci_verdict(rollup, required, runs, optional)
    if state == "empty":
        return "wait", "проверок GitHub пока нет", notes
    if state == "ok":
        return "ok", f"CI ✓ ({len(rollup)})", notes
    return state, why, notes


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
    required = required_checks(repo, view.get("baseRefName"))
    runs = ci_runs_fetch(repo, pr, sha, ci_fork(view)) if required else None
    state, why, notes = ci_state(view.get("statusCheckRollup"), required, runs, optional_checks(repo))
    # красные необязательные (OPTIONAL_CHECKS) — в тексте пропуска, и на запасном пути тоже (С1 argus #248)
    warn = "".join(f"; {n}" for n in notes)
    if state == "fail":
        # CI не запускался из-за лимита минут или оплаты (metis-0655): вместо CI засчитывается запись тестов на этот
        # SHA с командой полного набора FULL_TESTS (full_tests_record), как в шлюзе guard (_billing_problem); нет
        # такой записи или FULL_TESTS у репозитория — заявка снята по красной
        ids = ci_billing_ids(runs, required)
        if ci_billing(runs, required, ci_notes_fetch(repo, ids), ci_jobs_fetch(repo, ids)):
            if any(r.get("kind") == "tests" and r.get("sha") == sha and full_tests_record(repo, r) for r in recs):
                return "ok", f"argus ×{len(latest)} ✓, {BILLING_OK}{sha[:12]}{warn}"
            return "fail", (f"{why}; CI не запускался (лимит минут GitHub Actions), а записи полного набора тестов "
                            f"(FULL_TESTS) на {sha[:12]} нет")
    if state != "ok":
        return state, why
    return "ok", f"argus ×{len(latest)} ✓, CI ✓{warn}"


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


def nums(reqs):
    """«#7, #8» — номера PR заявок."""
    return ", ".join("#%d" % r["pr"] for r in reqs)


def batch_window_text(reqs, views, whys, paths):
    """Текст окна пачки (metis-0668): сначала задетые файлы ядра всех PR и число файлов — их владелец и
    подтверждает, затем номер, SHA и вердикт шлюза каждого PR в порядке слияния (его пишет проход, не автор PR),
    заголовки авторов — последними, в кавычках и коротко. Не длиннее 400 знаков — предел помощника окна. Ядро и
    номера с SHA всех PR влезают при MAX_BATCH PR и любых вердиктах (argus-263a Б1): ядру — место за вычетом номеров
    и коротких вердиктов, вердиктам — что осталось, поровну, вердикт запасного пути — коротко (BILLING_SHORT)."""
    n = len(reqs)
    head = f"Слить по очереди {n} PR {reqs[0]['repo']}, отказ шлюза у одного останавливает следующие."
    every = [x for p in paths for x in p]
    core = [x for x in dict.fromkeys(every) if is_core(x)]
    pre = [f"#{r['pr']} {r['sha'][:7]}" for r in reqs]
    fixed = len(" Вердикты: .") + sum(len(x) + 3 for x in pre)   # «#N sha7 » и «; » у каждого
    room = max(400 - len(head) - fixed - n * len(f"argus ×2 ✓, {BILLING_SHORT}") - 40, 60)
    shown, size = [], 0
    for x in core:
        if shown and size + len(x) > room:
            break
        shown.append(x)
        size += len(x) + 2
    more = f" и ещё {len(core) - len(shown)}" if len(core) > len(shown) else ""
    hit = f"ядро: {', '.join(shown)}{more}" if core else "ядро не задето"
    top = f"{head} Файлов {len(set(every))}, {hit}."
    per = min(48, max((400 - len(top) - fixed) // n, 0))
    short = [re.sub(re.escape(BILLING_OK) + r"[0-9a-f]+", BILLING_SHORT, " ".join(str(w).split()))[:per]
             for w in whys]
    items = "; ".join(f"{x} {w}".rstrip() for x, w in zip(pre, short))
    titles = "; ".join(f"#{r['pr']} «{' '.join(str(v.get('title') or '').split())[:40]}»" for r, v in zip(reqs, views))
    return f"{top} Вердикты: {items}. Заголовки: {titles}"[:400]


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


# --- управляемые настройки guard (metis-0710) ---------------------------------------------------------------------
# Решение владельца 02.11 (metis-managed-auto, «А — да, Touch ID»): файл /Library/…/managed-settings.json (P.MANAGED)
# отстал от проверенного дерева guard (verified.json, installed_dir) — проход показывает системное окно прав
# администратора macOS (Touch ID или пароль входа) «Обновить управляемые настройки guard до версии X». Права root даёт
# только это окно: окно LocalAuthentication (touchid.swift) подтверждает владельца, но root не даёт. Файл ставит
# скрипт root после касания: копия во временный файл рядом, сверка sha256 с проверенным файлом, chown, chmod, mv.
# Отказ, время вышло или окно не показать — карточка «Руками» с командой sudo и тревога; на ту же версию окно снова не
# раньше MANAGED_RETRY. Окно роли сюда не доходит: проход запускает только тик (cmd_run — отказ из окна Claude Code,
# `pantheon merge run` ролям закрыт guard), а песочница окна не даёт ни osascript, ни записи в /Library.
MANAGED_RETRY = 6 * 3600             # на ту же версию окно не чаще раза в 6 часов
MANAGED_WAIT = 120                   # сколько окно ждёт пальца
MANAGED_STATE = "managed-update.json"   # STATE: {sha, version, asked, result, task} и installed — что поставлено
OSASCRIPT = "/usr/bin/osascript"     # абсолютный путь: PATH прохода подменяем (launchctl setenv)
ROOT_OWNER = "0:0"                   # root:wheel; тестовая обвязка ставит свой uid:gid
ASK_ROOT = ("on run argv", "do shell script (item 1 of argv) with prompt (item 2 of argv) with administrator privileges",
            "end run")


def managed_source():
    """Проверенный файл: (путь, байты, версия) managed-settings.json из дерева guard, чей хеш совпал с verified.json
    (installed_dir). Клон маркетплейса — никогда; проверенного дерева или файла нет — None. Записи о guard в
    verified.json нет (guard не ставили) — None без тревоги installed_dir."""
    d = P.installed_dir("guard") if P.verified_record("guard") else None
    if not d:
        return None
    src = os.path.join(d, "managed-settings.json")
    try:
        with open(src, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    version = "?"
    with contextlib.suppress(OSError, ValueError, AttributeError):
        with open(os.path.join(d, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            version = str(json.load(fh).get("version") or "?")[:40]
    return src, data, version


def _managed_now():
    """(проверенный файл или None, байты поставленного или None — его нет или не прочитать). Поставленного нет — дерево
    guard не сверяется вовсе."""
    try:
        with open(P.MANAGED, "rb") as fh:
            cur = fh.read()
    except OSError:
        return None, None
    return managed_source(), cur


def _mstate():
    st = P.read_json(P.path(MANAGED_STATE), {})
    return st if isinstance(st, dict) else {}


def _close_card(tid, result):
    if tid:
        with contextlib.suppress(Exception):   # карточку закрыли или удалили руками — не беда
            P.tasks_mod().task_set(P.PANTHEON, P.now(), tid, {"status": "done", "result": result},
                                   actor="плановый проход", force=result)


def _settled(st, src, how):
    """Поставленный файл совпал с проверенным: записать версию, закрыть карточку «Руками», если она была."""
    _close_card(st.get("task"), f"управляемые настройки поставлены {how}")
    P.write_json(P.path(MANAGED_STATE), {"installed": {"version": src[2], "sha": hashlib.sha256(src[1]).hexdigest(),
                                                       "at": int(P.now()), "how": how}})


def managed_check():
    """Для тика: нужен ли проход ради управляемых настроек — поставленный файл есть, не совпадает с проверенным, и на
    эту версию окна не было последние MANAGED_RETRY. Файла в /Library нет — не отставание: первый раз его ставит
    владелец (README guard). Совпал, а карточка «Руками» открыта (поставили командой) — закрыть её.
    → проверенный файл (путь, байты, версия), если проход нужен, иначе None."""
    src, cur = _managed_now()
    if not src:   # поставленного нет или не прочитать — src тоже None (_managed_now)
        return None
    st = _mstate()
    if cur == src[1]:
        if st.get("task"):
            _settled(st, src, "командой")
        return None
    asked = st.get("asked")
    recent = isinstance(asked, (int, float)) and 0 <= P.now() - asked < MANAGED_RETRY
    return None if st.get("sha") == hashlib.sha256(src[1]).hexdigest() and recent else src


def root_script(src, dest, sha):
    """Скрипт root: копия проверенного файла во временный рядом с dest, sha256 копии — тот, что сверил проход (файл
    подменили после сверки — код 65, ничего не поставлено), владелец ROOT_OWNER, 644, замена одной операцией mv."""
    q = shlex.quote
    return (f"set -eu; umask 022; d={q(os.path.dirname(dest))}; /bin/mkdir -p \"$d\"; "
            "t=$(/usr/bin/mktemp \"$d/.managed-settings.XXXXXX\"); trap '/bin/rm -f \"$t\"' EXIT; "
            f"/bin/cat < {q(src)} > \"$t\"; "
            f"[ \"$(/usr/bin/shasum -a 256 < \"$t\" | /usr/bin/cut -c1-64)\" = {sha} ] || exit 65; "
            f"/usr/sbin/chown {ROOT_OWNER} \"$t\"; /bin/chmod 644 \"$t\"; /bin/mv -f \"$t\" {q(dest)}")


def manual_command(src, dest):
    q = shlex.quote
    return (f"sudo mkdir -p {q(os.path.dirname(dest))} && sudo install -m 644 -o root -g wheel {q(src)} {q(dest)}")


def ask_root(script, text):
    """Окно прав администратора и скрипт от root после касания → ok | refused | timeout | no-window (код N)."""
    argv = [OSASCRIPT] + [a for line in ASK_ROOT for a in ("-e", line)] + [script, text]
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=MANAGED_WAIT)
    except subprocess.TimeoutExpired:   # osascript убит — окно закрыто, касание позже не засчитывается
        return "timeout"
    except OSError as e:
        return f"no-window ({type(e).__name__})"
    if r.returncode == 0:
        return "ok"
    if "(-128)" in (r.stderr or ""):   # «Отменить» в окне: User canceled
        return "refused"
    return f"no-window (код {r.returncode}: {' '.join((r.stderr or '').split())[-120:]})"


WHY_RU = {"refused": "вы отменили окно", "timeout": f"окно {MANAGED_WAIT} с ждало касания"}


def managed_pass():
    """Шаг прохода: отставание → окно → установка; без касания — карточка «Руками» и тревога. → строка для журнала."""
    src = managed_check()
    if not src:
        return "в порядке или окно на эту версию уже было"
    if P.idle_sec() > PRESENT_SEC:
        return "отстали — ждёт: вас нет у Mac"
    path_, data, version = src
    sha = hashlib.sha256(data).hexdigest()
    st = _mstate()
    # попытка засчитана до окна (ревью argus-274b, Д1): проход оборвали после окна (срок тика, сбой карточки) — следующий
    # не покажет окно на ту же версию раньше MANAGED_RETRY, а не каждую минуту
    P.write_json(P.path(MANAGED_STATE), dict(st, sha=sha, version=version, asked=int(P.now()), result="окно показано"))
    res = ask_root(root_script(path_, P.MANAGED, sha), f"Обновить управляемые настройки guard до версии {version}")
    if res == "ok":
        try:
            with open(P.MANAGED, "rb") as fh:
                res = "ok" if fh.read() == data else "после касания файл не тот"
        except OSError as e:
            res = f"после касания файла нет ({type(e).__name__})"
    if res == "ok":
        _settled(st, src, "по касанию")
        return f"обновлены до версии {version}"
    cmd = manual_command(path_, P.MANAGED)
    why = WHY_RU.get(res, res)
    tid = st.get("task")
    if tid and st.get("sha") != sha:   # карточка прошлой версии: команда в ней уже не та
        _close_card(tid, f"заменена карточкой версии {version}")
        tid = None
    if not tid:
        with contextlib.suppress(OSError, ValueError):
            tid, _ = P.tasks_mod().task_new(
                P.PANTHEON, P.now(), MERGE_DIRECTION, f"Обновить управляемые настройки guard до {version}",
                owner="owner", actor="плановый проход", priority=1,
                text=(f"Управляемые настройки ({P.MANAGED}) отстали от проверенной версии guard {version}. Окно прав "
                      f"администратора не дало установить: {why}. Плановый проход спросит снова не раньше чем через "
                      f"{MANAGED_RETRY // 3600} ч. Или в своём терминале:\n\n    {cmd}\n\n"
                      "Карточка закроется сама, когда файл совпадёт с проверенным."))
    P.write_json(P.path(MANAGED_STATE), dict(st, sha=sha, version=version, asked=int(P.now()), result=res, task=tid))
    P.alert(f"управляемые настройки guard отстали от версии {version}: окно не дало установить ({why})"
            + (f" — карточка {tid}" if tid else "") + f"; команда: {cmd}", "pantheon-managed")
    return f"не обновлены ({why})" + (f", карточка {tid}" if tid else "")


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


def parse_targets(args):
    """<N> [<N2> …] -R <owner/repo>, -R в любом месте → (repo, [номера по порядку]) или None. Номеров от 1 до
    MAX_BATCH, без повторов."""
    if args.count("-R") != 1:
        return None
    i = args.index("-R")
    repo = args[i + 1].lower() if i + 1 < len(args) else ""
    rest = [a for j, a in enumerate(args) if j not in (i, i + 1)]
    if not 1 <= len(rest) <= MAX_BATCH or not all(PR_RE.fullmatch(a) for a in rest) or len(set(rest)) != len(rest) \
            or not REPO_RE.fullmatch(repo):
        return None
    return repo, [int(a) for a in rest]


def cmd_request(args):
    """Заявка на один PR или пачку (metis-0668: одно окно Touch ID на все). Пачка ставится целиком или никак: шлюз
    не пройден хоть у одного — заявок нет ни на один."""
    target = parse_targets(args)
    if not target:
        err(USAGE)
        return 2
    repo, prs = target
    if repo not in allowed_repos():
        err(f"pantheon merge request: {repo} не из [merge_repos] {MERGE_DIRECTION} в policy.toml — заявки нет")
        return 2
    heads, bad, waits = {}, [], []
    for pr in prs:
        view = pr_view(repo, pr)
        if view is None:
            err(f"pantheon merge request: gh pr view {pr} -R {repo} не ответил — заявки нет")
            return 1
        sha = str(view.get("headRefOid") or "").lower()
        if not SHA_RE.fullmatch(sha):
            err(f"pantheon merge request: у PR #{pr} нет head SHA — заявки нет")
            return 1
        state, why = gate(repo, pr, sha, view)
        if state == "fail":
            bad.append(f"#{pr}: {why}" if len(prs) > 1 else why)
        elif state != "ok":
            waits.append(why.lower() if len(prs) == 1 else f"#{pr}: {why}")
        heads[pr] = sha
    if bad:
        err(f"pantheon merge request: шлюз не пройден — {'; '.join(bad)}. Заявки нет"
            + (" ни на один PR пачки" if len(prs) > 1 else ""))
        return 1
    who = " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "владелец").split())[:40]
    created = int(P.now())
    reqs = [{"repo": repo, "pr": pr, "sha": heads[pr], "by": who, "created": created} for pr in prs]
    if len(prs) > 1:
        for req in reqs:
            req["batch"] = list(prs)
    with P.lock("merge-queue"):
        olds = [read_req(req_file(repo, pr)) if os.path.lexists(req_file(repo, pr)) else None for pr in prs]
        if all(o and o["sha"] == heads[o["pr"]] and o.get("batch") == r.get("batch") for o, r in zip(olds, reqs)) \
                and len({o["created"] for o in olds}) == 1:
            what = f"заявка {repo}#{prs[0]} ({heads[prs[0]][:7]})" if len(prs) == 1 else \
                f"пачка {repo} {', '.join(f'#{n}' for n in prs)}"
            print(f"{what} уже стоит")
            return 0
        for req in reqs:
            write_req(req)
    for req in reqs:
        log(req, "request", batch=",".join(map(str, prs)) if len(prs) > 1 else None)
    later = ("" if not waits else f" и {'; '.join(waits)} закончатся" if len(prs) == 1
             else f", а у PR закончится ожидание ({'; '.join(waits)})")
    if len(prs) == 1:
        print(f"Заявка {repo}#{prs[0]} ({heads[prs[0]][:7]}) поставлена. Окно Touch ID покажет плановый проход, когда вы "
              f"у Mac{later}; без ответа за {REQUEST_TTL // 3600} ч заявка гаснет.")
    else:
        print(f"Пачка {repo}: {', '.join(f'#{n} ({heads[n][:7]})' for n in prs)} поставлена. Одно окно Touch ID на все "
              f"покажет плановый проход, когда вы у Mac{later}; сливает по очереди, отказ одного останавливает "
              f"следующие; без ответа за {REQUEST_TTL // 3600} ч пачка гаснет.")
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


def finger(req, rc=0):
    """После пальца — одна заявка: (слит ли, текст итога). Окно было открыто до двух минут, а у пачки перед этой
    заявкой ещё шли слияния прежних: отмена, новый «вернуть», новый коммит или правка [merge_repos] за это время — не
    сливать. Сверка шлюза, строка согласия и снятие заявки — под замком merge-queue, как у request и cancel; слияние —
    `gh pr merge --match-head-commit` того SHA, что в заявке."""
    with P.lock("merge-queue"):
        if not same_req(req):
            return False, gone(req, rc)
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
        return False, f"снята: {bad}"
    code, out = gh_merge(req)
    log(req, "merged" if code == 0 else "merge-failed", rc=code)
    if code != 0:
        P.alert(f"слияние {req['repo']}#{req['pr']} ({req['sha'][:7]}) после Touch ID не прошло: {out}. Согласие "
                "записано — шлюз guard пустит слияние этого SHA в течение суток", "pantheon-merge")
        return False, f"палец есть, gh pr merge упал ({code})"
    return True, "слит"


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
        return finger(req, rc)[1]
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


def drop_batch(reqs, event, why, warn=False):
    """Снять все заявки пачки (каждую — только если в очереди та же, drop) и одной тревогой, если warn."""
    out = [(r, drop(r, event, why)) for r in reqs]
    if warn:
        P.alert(f"слияние пачки {reqs[0]['repo']} {nums(reqs)} по Touch ID: заявки сняты — {why}", "pantheon-merge")
    return out


def process_batch(reqs, click):
    """Пачка заявок одной постановки (metis-0668) → [(заявка, итог)] по каждой. Как process, но окно одно на всю
    пачку: в нём ядро всех PR и список PR с SHA и вердиктами шлюза. До окна: пачка в очереди неполна (одну сняли или заменили), шлюз
    не пройден хоть у одного — сняты все с тревогой; ждёт хоть один — ждут все. После пальца — по очереди, каждый
    через finger (шлюз заново, строка согласия, gh pr merge --match-head-commit своего SHA); не слит один — следующие
    не трогаются: ни согласия, ни слияния, заявки сняты (палец был на всю пачку — нужна новая заявка)."""
    t, batch = P.now(), reqs[0]["batch"]
    if len(reqs) != len(batch):
        have = {r["pr"] for r in reqs}
        miss = ", ".join("#%d" % n for n in batch if n not in have)
        return drop_batch(reqs, "batch-broken", f"пачка неполна: заявку на {miss} сняли или заменили", warn=True)
    if t - reqs[0]["created"] > REQUEST_TTL:
        return drop_batch(reqs, "expired", f"{REQUEST_TTL // 3600} ч без ответа", warn=True)
    if not click and max(r.get("wait_until", 0) for r in reqs) > t:
        return [(r, "ждёт: окно закрыто без ответа, повтор позже") for r in reqs]
    if not click and any(r.get("notified") for r in reqs):
        return [(r, "ждёт щелчка по уведомлению") for r in reqs]
    views, whys, paths, waits = [], [], [], []
    for r in reqs:
        state, why, view, files = check_all(r)   # заново, на тот же head, у каждого PR пачки
        if state == "fail":
            return drop_batch(reqs, "gate", f"#{r['pr']}: {why}", warn=True)
        if state == "wait":
            waits.append(f"#{r['pr']}: {why}")
        views.append(view)
        whys.append(why)
        paths.append(files or [])
    if waits:
        return [(r, "ждёт: " + "; ".join(waits)) for r in reqs]
    if not click and P.idle_sec() > PRESENT_SEC:
        return [(r, "ждёт: вас нет у Mac") for r in reqs]
    text = batch_window_text(reqs, views, whys, paths)
    rc = ask(text)
    if rc is None:
        P.alert_once("merge-helper", "1", "слияние по Touch ID: помощник окна не собран (swiftc) — заявки ждут; "
                     "собрать: pantheon install", "pantheon-merge")
        return [(r, "ждёт: помощника окна нет") for r in reqs]
    for r in reqs:
        log(r, "window", rc=rc, click=click, batch=",".join(map(str, batch)))
    if rc == 0:
        out, merged, untouched, stop = [], [], [], None
        for r in reqs:
            if stop:
                untouched.append(r)
                out.append((r, drop(r, "batch-stopped", f"не слит: пачка остановлена на {stop}")))
                continue
            ok, res = finger(r, rc)
            out.append((r, res))
            if ok:
                merged.append(r)
            else:
                stop = f"#{r['pr']} ({res})"
        if untouched:
            P.alert(f"слияние пачки {reqs[0]['repo']} по Touch ID остановлено на {stop}. Слиты: "
                    f"{nums(merged) or 'ни один'}; не тронуты — согласия и слияния нет, заявки сняты, нужна новая: "
                    f"{nums(untouched)}", "pantheon-merge")
        return out
    if rc == 1:
        return drop_batch(reqs, "refused", "вы отказали")
    if rc == 3:
        out = []
        for r in reqs:
            r["wait_until"] = int(t + RETRY_SEC)
            out.append((r, "окно закрыто без ответа — повтор позже" if keep(r) else gone(r, rc)))
        return out
    if rc == 2 and not click:
        with P.lock("merge-queue"):
            still = all(same_req(r) for r in reqs)
        if not still:   # сняли или заменили, пока помощник пробовал окно, — и уведомления нет
            return [(r, gone(r, rc)) for r in reqs]
        if fallback_notify(reqs[0], text):
            out = []
            for r in reqs:
                r["notified"] = int(t)
                if keep(r):
                    log(r, "notified")
                    out.append((r, "окно из прохода не показать — уведомление, ждёт щелчка"))
                else:
                    out.append((r, gone(r, rc)))
            return out
        return drop_batch(reqs, "no-window", "окно Touch ID не показать и уведомление не ушло", warn=True)
    return drop_batch(reqs, "no-window", f"окно Touch ID не показано (код {rc})", warn=True)


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
    with P.lock("merge-run", block=False) as got:
        if not got:
            print("pantheon merge run: идёт другой проход")
            return 0
        rc, seen = 0, set()
        for f in sorted(os.listdir(r)) if _real_dir(r) else []:
            p = os.path.join(r, f)
            # заявку пачки уже разобрали с её первой — её файла может и не быть (слита, снята): не «битая» (argus-263a)
            if not FILE_RE.fullmatch(f) or f in seen:
                continue
            with P.lock("merge-queue"):
                req = read_req(p)
                if req is None:
                    with contextlib.suppress(OSError):
                        os.remove(p)
                # пачка (metis-0668) — вся сразу, по порядку слияния, когда встретилась первая её заявка
                group = batch_members(req) if req is not None and req.get("batch") else [req]
            if req is None:
                print(f"{f}: битая заявка — удалена")
                continue
            seen.update(os.path.basename(req_file(g["repo"], g["pr"])) for g in group)
            try:
                if req.get("batch"):
                    for g, res in process_batch(group, click):
                        print(f"{g['repo']}#{g['pr']}: {res}")
                else:
                    print(f"{req['repo']}#{req['pr']}: {process(req, click)}")
            except Exception as e:  # одна заявка не останавливает другие; сбойная снимается — окно не повторяется
                rc = 1
                for g in group:
                    with contextlib.suppress(Exception):
                        drop(g, "error", f"сбой прохода ({type(e).__name__}: {e})", warn=True)
                    print(f"{g['repo']}#{g['pr']}: сбой ({type(e).__name__}) — заявка снята")
        try:   # управляемые настройки guard (metis-0710) — тем же проходом, под тем же замком
            print(f"управляемые настройки guard: {managed_pass()}")
        except Exception as e:  # сбой не роняет проход; тревога — с причиной, повтор — следующим проходом
            rc = 1
            with contextlib.suppress(Exception):
                P.alert(f"управляемые настройки guard: сбой прохода ({type(e).__name__}: {e})", "pantheon-managed")
            print(f"управляемые настройки guard: сбой ({type(e).__name__})")
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
                if req.get("batch"):
                    marks += " пачка " + ",".join("#%d" % n for n in req["batch"])
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
        # пачка (metis-0668) без одной заявки не сливается: снимаются и остальные заявки той же постановки
        rest = [m for m in batch_members(req) if m["pr"] != pr] if req.get("batch") else []
        os.remove(p)
        for m in rest:
            os.remove(req_file(m["repo"], m["pr"]))
    for m in [req] + rest:
        log(m, "cancelled")
    print(f"заявка {repo}#{pr} снята" + (f", с ней — вся пачка: {nums(rest)}" if rest else ""))
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
