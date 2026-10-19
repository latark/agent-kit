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
  3. Шлюз заново на тот же head: запись тестов шлюза на SHA; у каждого рецензента argus последний вердикт — «принять»
     с полным перечнем и на Opus, рецензентов-«принять» не меньше двух, «вернуть» нет; проверки GitHub (CI) — все
     SUCCESS/NEUTRAL/SKIPPED. CI ещё идёт или проверок пока нет — заявка ждёт; иначе снята с тревогой.
  4. Владелец у Mac (простой меньше PRESENT_SEC) — окно Touch ID: помощник pantheon-touchid (lib/touchid.swift,
     LocalAuthentication). Палец → строка `<время> merge-approve <owner/repo>#<N> <sha>` в
     owner-log/merge-approve.log (её сверяет шлюз guard: PR ядра проходит только с ней), затем
     `gh pr merge <N> -R <repo> --match-head-commit <sha> --merge`, заявка снята. «Не сливать» — снята. Окно закрыто
     без ответа — ждёт RETRY_SEC. Окно не показать (код 2: процесс launchd не в сессии владельца) — запасной путь:
     уведомление один раз, щелчок по нему запускает `pantheon merge run --click` от имени владельца, и окно Touch ID
     показывается уже оттуда.
Журнал — STATE/logs/merge.jsonl (репозиторий, номер, SHA, событие). Пути для тестов: PANTHEON_TOUCHID — помощник
(иначе STATE/bin/pantheon-touchid, его собирает swiftc из lib/touchid.swift), gh — из PATH.
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
CHECKLIST = ("opened", "ran", "unchecked")
OPUS_RAN = re.compile(r"\s*модель:\s*claude-opus", re.I)   # как в шлюзе guard (metis-0176)
CI_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
CI_WAIT = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", ""}
USAGE = "pantheon merge request|cancel <N> -R <owner/repo> | run [--click] | status"


def set_core(mod):
    global P
    P = mod


def err(text):
    print(text, file=sys.stderr)


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


def drop(req, event, why=None, warn=False):
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
    """{headRefOid, state, isDraft, title, statusCheckRollup} или None — gh не ответил."""
    try:
        r = subprocess.run([gh_path(), "pr", "view", str(pr), "-R", repo, "--json",
                            "headRefOid,state,isDraft,title,statusCheckRollup"],
                           capture_output=True, text=True, timeout=GH_TIMEOUT, env=gh_env())
        data = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return data if isinstance(data, dict) else None


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

def _full_checklist(r):
    c = r.get("checklist")
    return isinstance(c, dict) and all(isinstance(c.get(k), str) and c[k].strip() for k in CHECKLIST)


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
            # «принять» не на Opus не засчитывается — как будто его нет; «вернуть» любой модели в силе
            if r["kind"] == "accept" and not (_full_checklist(r) and OPUS_RAN.match(r["checklist"]["ran"])):
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
    """Путь к помощнику окна или None. Свой бинарник — STATE/bin/pantheon-touchid, пересобирается, когда меняется
    lib/touchid.swift (хеш исходника рядом)."""
    if os.environ.get("PANTHEON_TOUCHID"):
        h = os.environ["PANTHEON_TOUCHID"]
        return h if os.access(h, os.X_OK) else None
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
        swiftc = shutil.which("swiftc", path=os.environ.get("PATH", "") + ":/usr/bin")
        if not swiftc:
            raise OSError("нет swiftc (Xcode Command Line Tools)")
        tmp, cache = out + f".new.{os.getpid()}", os.path.join(d, ".swift-cache")
        r = subprocess.run([swiftc, "-O", "-module-cache-path", cache, "-o", tmp, src], capture_output=True,
                           text=True, timeout=300)
        if r.returncode != 0:
            raise OSError((r.stderr or r.stdout).strip().splitlines()[-1:] or ["swiftc упал"])
        os.chmod(tmp, 0o700)
        os.replace(tmp, out)
        with open(mark, "w") as fh:
            fh.write(want + "\n")
        return out
    except (OSError, subprocess.SubprocessError) as e:
        if not quiet:
            err(f"помощник Touch ID не собран: {e}")
        return None


def window_text(req, view, why):
    title = " ".join(str(view.get("title") or "").split())[:80]
    return f"Слить {req['repo']}#{req['pr']} ({req['sha'][:7]}): {title}. {why}"[:400]


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


def fallback_notify(req, view):
    """Запасной путь: уведомление, щелчок по которому запускает `pantheon merge run --click` от имени владельца."""
    base = P.CURRENT if os.path.isdir(P.CURRENT) else P.PLUGIN
    cmd = f"{shlex.quote(os.path.join(base, 'bin', 'pantheon'))} merge run --click"
    title = " ".join(str(view.get("title") or "").split())[:80]
    text = f"Слить {req['repo']}#{req['pr']} ({req['sha'][:7]}): {title}. Щёлкните — откроется окно Touch ID"
    if os.environ.get("PANTHEON_NOTIFY_LOG"):
        with open(os.environ["PANTHEON_NOTIFY_LOG"], "a", encoding="utf-8") as fh:
            fh.write(f"Слияние ядра|{text}|execute:{cmd}|merge\n")
        return True
    tn = P._notifier()
    if not tn or os.environ.get("PANTHEON_NO_NOTIFY"):
        return False
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
    old = read_req(req_file(repo, pr)) if os.path.lexists(req_file(repo, pr)) else None
    if old and old["sha"] == sha:
        print(f"заявка {repo}#{pr} ({sha[:7]}) уже стоит")
        return 0
    who = " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "владелец").split())[:40]
    req = {"repo": repo, "pr": pr, "sha": sha, "by": who, "created": int(P.now())}
    with P.lock("merge-queue"):
        write_req(req)
    log(req, "request")
    print(f"Заявка {repo}#{pr} ({sha[:7]}) поставлена. Окно Touch ID покажет плановый проход, когда вы у Mac"
          + ("" if state == "ok" else f" и {why.lower()} закончатся") + f"; без ответа за {REQUEST_TTL // 3600} ч "
          "заявка гаснет.")
    return 0


def process(req, click):
    t = P.now()
    if t - req["created"] > REQUEST_TTL:
        return drop(req, "expired", f"{REQUEST_TTL // 3600} ч без ответа", warn=True)
    if not click and req.get("wait_until", 0) > t:
        return "ждёт: окно закрыто без ответа, повтор позже"
    if not click and req.get("notified"):
        return "ждёт щелчка по уведомлению"
    view = pr_view(req["repo"], req["pr"])
    state, why = gate(req["repo"], req["pr"], req["sha"], view)  # заново, на тот же head (Решено, бриф 0285)
    if state == "fail":
        return drop(req, "gate", why, warn=True)
    if state == "wait":
        return f"ждёт: {why}"
    if not click and P.idle_sec() > PRESENT_SEC:
        return "ждёт: вас нет у Mac"
    rc = ask(window_text(req, view, why))
    if rc is None:
        P.alert_once("merge-helper", "1", "слияние по Touch ID: помощник окна не собран (swiftc) — заявки ждут; "
                     "собрать: pantheon install", "pantheon-merge")
        return "ждёт: помощника окна нет"
    log(req, "window", rc=rc, click=click)
    if rc == 0:
        approve(req)
        with contextlib.suppress(FileNotFoundError):
            os.remove(req_file(req["repo"], req["pr"]))   # одно применение — до слияния, сбой gh её не вернёт
        code, out = gh_merge(req)
        log(req, "merged" if code == 0 else "merge-failed", rc=code)
        if code != 0:
            P.alert(f"слияние {req['repo']}#{req['pr']} ({req['sha'][:7]}) после Touch ID не прошло: {out}. Согласие "
                    "записано — шлюз guard пустит слияние этого SHA", "pantheon-merge")
            return f"палец есть, gh pr merge упал ({code})"
        return "слит"
    if rc == 1:
        return drop(req, "refused", "вы отказали")
    if rc == 3:
        req["wait_until"] = int(t + RETRY_SEC)
        write_req(req)
        return "окно закрыто без ответа — повтор позже"
    if rc == 2 and not click:
        if fallback_notify(req, view or {}):
            req["notified"] = int(t)
            write_req(req)
            log(req, "notified")
            return "окно из прохода не показать — уведомление, ждёт щелчка"
        return drop(req, "no-window", "окно Touch ID не показать и уведомление не ушло", warn=True)
    return drop(req, "no-window", f"окно Touch ID не показано (код {rc})", warn=True)


def cmd_run(click=False):
    # переменная есть, пусть и пустая, — окно Claude Code: сливает только проход или щелчок владельца
    if "CLAUDECODE" in os.environ or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        err("pantheon merge run: только плановый проход или щелчок по уведомлению, не из окна Claude Code")
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
            req = read_req(p)
            if req is None:
                with contextlib.suppress(OSError):
                    os.remove(p)
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
