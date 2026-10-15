"""Запор слияния guard (P1-4, Д2, Д3, guard 0.5.4) — часть ядра защит: этот файл, protect_config.py и
managed-settings.json агенты не сливают, только кнопка владельца (Д3).

Модуль без своего состояния: общие помощники guard.py (load_policy, privileged, private_conf, _inside, _norm, _key,
STATE_DIR, PANTHEON, HOME, DOMAINS_FILE…) берутся через G — его присваивает guard.py при загрузке
(`merge_gate.G = <модуль guard>`). Пути считаются при вызове, а не при импорте: тесты подменяют HOME.

Две части.
1. Журнал проверок STATE_DIR/merge-gate/records.jsonl. Пишет только хук guard на PostToolUse (record): команда
   Bash успешно завершилась, она простая (без ; | & && || $( ` и перенаправлений) и это `pantheon review <вид> …`.
     tests          — `pantheon review test -- <команда>`: SHA — HEAD папки cwd, дерево чистое; repo — её remote;
     accept, reject — `pantheon review accept|reject <owner/repo> <PR> <SHA>`, только agent_type argus;
     talos          — `pantheon review talos <owner/repo> <PR> <SHA>`, только agent_type talos.
   Строка: {"v":1,"kind","repo":[owner/repo…],"pr":N|null,"sha","by":{agent_type,agent_id,session_id},"cwd","time",
   "tool_use_id","cmd"}. Подделать запись роль не может: ~/.local/state/pantheon закрыт ролям песочницей и
   pantheon-acl, а вид записи хук берёт из agent_type события, а не из текста команды. Битые строки при чтении
   пропускаются: битая запись может только не дать разрешения.
2. merge_problem — правило gh pr merge: кто сливает (координатор или его лид), чьё направление, защиты, затем запор:
   один номер PR, без --auto и --admin, ровно один --match-head-commit <SHA> (его сверяет GitHub), все репозитории
   команды — из [merge_repos] направления, запись tests на (repo, SHA), последний вердикт argus на (repo, PR, SHA) —
   accept, рецензент — не тот, кто сливает; продукт — ещё запись talos и строка в ~/ai/pantheon/alerts.md со ссылкой
   owner/repo#N и словом «откат»; защиты — ещё Д3: PR не задевает файлы ядра (gh pr view).
Чего guard не проверяет: правдивость строки в сводке и то, что выбранная команда тестов — настоящие тесты.
"""

import json
import os
import re
import shlex
import subprocess
import time

G = None  # модуль guard.py: присваивает guard.py при загрузке

MERGE_CLOSED = ("слияние делает лид направления (hephaestus-*, apollo-* субагентом) или главная сессия его "
                "координатора. Вместо него отправь свою ветку, открой PR (gh pr create) и в отчёте лиду напиши, что "
                "проверено и что меняется.")
MERGE_LEADS = ("hephaestus", "apollo")  # лиды: <база>-<направление после первого «-»>, как их собирает pantheon roles build
MERGE_INTERNAL = ("Внутреннее сливай после записей запора: тесты (`pantheon review test -- <команда>`) и «принять» "
                  "от argus на этот SHA, затем gh pr merge N --match-head-commit <SHA>.")
MERGE_PRODUCT = ("Продукт для клиентов сливай после записей запора: тесты, «принять» от argus и проверка talos на этот "
                 "SHA, строка в сводке «что ушло» со ссылкой owner/repo#N и откатом (`pantheon alert`), затем "
                 "gh pr merge N --match-head-commit <SHA>.")
MERGE_PROTECT = ("Защиты сливает только Метида или её лид через запор: тесты и «принять» от argus на этот SHA, "
                 "gh pr merge N --match-head-commit <SHA>; PR, который задевает ядро защит (merge_gate.py, "
                 "protect_config.py, managed-settings.json), сливает только владелец кнопкой (Д3).")
MERGE_OWNER = "Слияние делает владелец."
MERGE_AMBIGUOUS = "\0два направления"
MERGE_CORE = "ядро защит — только кнопка владельца (Д3)"
# ядро защит (Д3): эти файлы агенты не сливают — гарантия, что запор не ослабит сам себя
CORE_FILES = ("plugins/guard/hooks/merge_gate.py", "plugins/guard/hooks/protect_config.py",
              "plugins/guard/managed-settings.json")
GH_TIMEOUT = 6
SHA_RE = re.compile(r"[0-9a-f]{40}")
REPO_RE = re.compile(r"[a-z0-9_.-]+/[a-z0-9_.-]+")
PR_RE = re.compile(r"[1-9][0-9]{0,8}")
RECORD_V = 1
REVIEW_KINDS = {"accept": "argus", "reject": "argus", "talos": "talos"}  # вид записи → кто её пишет
# простая команда: без цепочек, конвейеров, подстановок и перенаправлений (разбор guard для неё не нужен)
NOT_SIMPLE = re.compile(r"[;|&<>`\n\r]|\$\(")


def _str_list(v):
    """Непустой список непустых строк — или None: строка вместо списка перебиралась бы по буквам, и корнем стал бы «/»."""
    return v if isinstance(v, list) and v and all(isinstance(x, str) and x.strip() for x in v) else None


def _repo_arg(value):
    """Значение -R/--repo → owner/repo (github.com) или host/owner/repo, в нижнем регистре."""
    v = (value or "").strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = re.sub(r"^(?:www\.)?github\.com/", "", v)
    return re.sub(r"(?:\.git)?/*$", "", v)


def _remote_id(url):
    """Адрес remote → owner/repo (github.com) или host/owner/repo, в нижнем регистре. git@github.com:o/r.git,
    https://github.com/o/r(.git), ssh://git@github.com/o/r; локальный путь и прочее — как есть."""
    u = (url or "").strip()
    m = re.match(r"^[a-z][a-z0-9+.-]*://(?:[^@/]*@)?([^/:]+)(?::\d*)?/+(.+)$", u, re.I) or \
        re.match(r"^(?:[^@/:]+@)?([^/:]+):(?!/)(.+)$", u)
    if not m:
        return u.lower()
    host, path = m.group(1).lower(), re.sub(r"(?:\.git)?/*$", "", m.group(2).lower()).strip("/")
    return path if host in ("github.com", "www.github.com") else f"{host}/{path}"


def _repo_tail(repo):
    """owner/repo без хоста: псевдоним ssh (git@gh-work:latark/agent-kit) gh понимает как github.com, поэтому
    репозитории сравниваются по двум последним частям, а не по хосту."""
    return "/".join(repo.split("/")[-2:])


def _git_env():
    """Окружение без GIT_*: GIT_DIR подменил бы репозиторий."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(d, *args):
    """Вывод git в папке d; None — git не ответил (не репозиторий, сбой, таймаут)."""
    try:
        r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, timeout=3, env=_git_env())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _git_remotes(d):
    """Адреса remote репозитория в папке d; None — git не ответил (не репозиторий, сбой, таймаут)."""
    out = _git(d, "remote", "-v")
    if out is None:
        return None
    return sorted({_remote_id(ln.split()[1]) for ln in out.splitlines() if len(ln.split()) >= 2})


def _gh_resolved(d):
    """Значения remote.<имя>.gh-resolved (gh repo set-default): gh может слить туда, а не в remote. «base» — это
    сам remote, его пропускаем. → список owner/repo; код 1 (ключей нет) — пусто; другой сбой — None."""
    try:
        r = subprocess.run(["git", "-C", d, "config", "--get-regexp", r"^remote\..*\.gh-resolved$"],
                           capture_output=True, text=True, timeout=3, env=_git_env())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if r.returncode == 1 and not r.stdout.strip():
        return []
    if r.returncode != 0:
        return None
    out = []
    for ln in r.stdout.splitlines():
        parts = ln.split(None, 1)
        if len(parts) != 2:
            return None
        if parts[1].strip().lower() != "base":
            out.append(_repo_arg(parts[1]))
    return out


def _merge_domains():
    """Реестр направлений для слияния: {имя: [корни]}; None — реестр пуст или битый (тогда слияние закрыто).
    Только domains.json, без отката на старый ~/.claude/hooks/domains.json, как у load_domains(): в старом реестре
    направления шире, и с ним Гермес слил бы в legal-watch (ревью argus 210766a)."""
    try:
        with open(G.DOMAINS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    dom = data.get("domains") if isinstance(data, dict) else None
    if not isinstance(dom, dict) or not dom:
        return None
    out = {}
    for name, paths in dom.items():
        paths = _str_list(paths)
        if paths is None:
            return None
        out[name] = G._norm(paths)
    return out


def _merge_owner(domains, path):
    """Направление папки — по самому длинному совпавшему корню: корень «~/projects» у одного направления не
    открывает папку другого внутри. Два направления с одним корнем — MERGE_AMBIGUOUS (не совпадёт ни с кем)."""
    best, size = None, -1
    for name, roots in domains.items():
        for r in roots:
            if G._inside(path, [r]):
                n = len(G._key(r).rstrip("/"))
                if n > size:
                    best, size = name, n
                elif n == size and name != best:
                    best = MERGE_AMBIGUOUS
    return best


def _merge_args(args):
    """Разбор флагов gh pr merge: (ошибка, [значения -R], [номера PR], --auto, [значения --match-head-commit])."""
    takes_value = {"--body", "--body-file", "--author-email", "--subject"}
    nxt = None  # чьё значение — следующее слово: "repo", "head" или "skip"
    repos, numbers, heads, auto = [], [], [], False
    for a in args:
        if nxt:
            if nxt == "repo":
                repos.append(a)
            elif nxt == "head":
                heads.append(a or "")
            nxt = None
            continue
        if not a:
            return "PR указывай номером", repos, numbers, auto, heads
        if a == "--admin" or a.startswith("--admin="):  # gh принимает --admin=true (ревью argus 15.10)
            return "без --admin", repos, numbers, auto, heads
        if a == "--auto" or a.startswith("--auto="):
            auto = True
        elif a == "--repo":
            nxt = "repo"
        elif a.startswith("--repo="):
            repos.append(a[7:])
        elif a == "--match-head-commit":
            nxt = "head"
        elif a.startswith("--match-head-commit="):
            heads.append(a[20:])
        elif a.startswith("-") and not a.startswith("--") and len(a) > 1:
            # короткие флаги склеиваются (pflag): -dR<репо> — это -d и -R <репо>, -st<текст> — -s и -t <текст>
            for i, c in enumerate(a[1:]):
                rest = a[2 + i:]
                if c in "RtbFA":  # флаг со значением: остаток токена — его значение
                    if c == "R":
                        rest = rest[1:] if rest.startswith("=") else rest
                    kind = "repo" if c == "R" else "skip"
                    if not rest:
                        nxt = kind
                    elif kind == "repo":
                        repos.append(rest)
                    break
                if c not in "dsmr":
                    break
        elif a in takes_value or a.split("=", 1)[0] in takes_value:
            nxt = "skip" if "=" not in a else None
        elif a.isdigit():
            numbers.append(int(a))
        elif not a.startswith("-"):
            return "PR указывай номером", repos, numbers, auto, heads
    if nxt == "repo":
        return "-R без репозитория", repos, numbers, auto, heads
    if nxt == "head":
        heads.append("")
    return None, repos, numbers, auto, heads


def _merge_repo_ok(value, repos):
    """-R для gh pr merge: owner/repo (или github.com/owner/repo) ровно из [merge_repos] направления."""
    v = (value or "").strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = re.sub(r"^github\.com/", "", v)
    v = re.sub(r"(?:\.git)?/?$", "", v)
    return bool(REPO_RE.fullmatch(v)) and v in repos


# --- журнал проверок --------------------------------------------------------------------------------------------

def gate_dir():
    return os.path.join(G.STATE_DIR, "merge-gate")


def records_file():
    return os.path.join(gate_dir(), "records.jsonl")


def _valid(rec):
    """Строка журнала в формате v1 — иначе пропускается."""
    if not isinstance(rec, dict) or rec.get("v") != RECORD_V or rec.get("kind") not in ("tests", "accept", "reject",
                                                                                          "talos"):
        return False
    repo, pr, sha, by = rec.get("repo"), rec.get("pr"), rec.get("sha"), rec.get("by")
    if not (isinstance(repo, list) and repo and all(isinstance(r, str) for r in repo)):
        return False
    if not (isinstance(sha, str) and SHA_RE.fullmatch(sha)):
        return False
    if rec["kind"] == "tests":
        if pr is not None:
            return False
    elif not (isinstance(pr, int) and not isinstance(pr, bool) and pr > 0):
        return False
    return isinstance(by, dict) and all(isinstance(by.get(k, ""), str) for k in ("agent_type", "agent_id", "session_id"))


def read_records():
    """Записи журнала по порядку; нет файла — пусто; папка или файл — симлинк, файл не читается — None."""
    d = gate_dir()
    if os.path.islink(d):
        return None
    try:
        fd = os.open(records_file(), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return []
    except OSError:
        return None
    out = []
    with os.fdopen(fd, "rb") as fh:
        for raw in fh:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if _valid(rec):
                out.append(rec)
    return out


def append_record(rec):
    d = gate_dir()
    if os.path.islink(d):
        raise OSError("merge-gate — симлинк")
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    fd = os.open(records_file(), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def verdict_args(args):
    """<owner/repo> <PR> <SHA 40 знаков> → (repo, pr, sha) в нижнем регистре; None — не тот формат."""
    if len(args) != 3 or any(not isinstance(a, str) for a in args):
        return None
    repo, pr, sha = args[0].lower(), args[1], args[2].lower()
    if not REPO_RE.fullmatch(repo) or not PR_RE.fullmatch(pr) or not SHA_RE.fullmatch(sha):
        return None
    return repo, int(pr), sha


def _is_pantheon(word):
    return isinstance(word, str) and os.path.basename(word.rstrip("/")) == "pantheon"


def simple_review(cmd):
    """Простая команда `pantheon review <вид> …` → список слов после pantheon; иначе None."""
    if not cmd or NOT_SIMPLE.search(cmd):
        return None
    try:
        words = shlex.split(cmd)
    except ValueError:
        return None
    if len(words) < 3 or not _is_pantheon(words[0]) or words[1] != "review":
        return None
    return words[1:]


def record(event):
    """PostToolUse (только успешная команда): запись в журнал проверок или ничего."""
    if event.get("tool_name") != "Bash":
        return None
    tool_input, resp = event.get("tool_input") or {}, event.get("tool_response")
    # фоновая команда: Claude Code шлёт PostToolUse при запуске, а не по итогу, и PostToolUseFailure не будет
    # (ревью argus PR #18) — по ней ничего не пишем; уведённую в фон (Ctrl+B) выдаёт backgroundTaskId в ответе
    if not isinstance(tool_input, dict) or tool_input.get("run_in_background") \
            or not isinstance(resp, dict) or "backgroundTaskId" in resp:
        return None
    cmd = tool_input.get("command") or ""
    words = simple_review(cmd)
    if not words:
        return None
    kind, args = words[1], words[2:]
    role = event.get("agent_type") or ""
    cwd = os.path.realpath(event.get("cwd") or "")
    if kind == "test":
        if len(args) < 2 or args[0] != "--":
            return None
        sha = (_git(cwd, "rev-parse", "HEAD") or "").strip().lower()
        status = _git(cwd, "status", "--porcelain")
        remotes = _git_remotes(cwd)
        if not SHA_RE.fullmatch(sha) or status is None or status.strip() or not remotes:
            return None
        rec_kind, repos, pr = "tests", sorted({_repo_tail(r) for r in remotes}), None
    elif kind in REVIEW_KINDS:
        if role != REVIEW_KINDS[kind]:
            return None
        parsed = verdict_args(args)
        if not parsed:
            return None
        repo, pr, sha = parsed
        rec_kind, repos = kind, [repo]
    else:
        return None
    append_record({"v": RECORD_V, "kind": rec_kind, "repo": repos, "pr": pr, "sha": sha,
                   "by": {"agent_type": role, "agent_id": event.get("agent_id") or "",
                          "session_id": event.get("session_id") or ""},
                   "cwd": cwd, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "tool_use_id": event.get("tool_use_id") or "", "cmd": cmd})
    return rec_kind


def review_problem(role, args, cmd="", background=False):
    """PreToolUse: `pantheon review test|accept|reject|talos …`, после которой записи не будет, — сразу отказ, чем
    команда пройдёт, а запись не появится: в фоне, не простой командой, не той ролью, с плохими аргументами.
    args — слова после pantheon, cmd — вся команда Bash, background — run_in_background."""
    if len(args) < 2 or args[0] != "review" or (args[1] != "test" and args[1] not in REVIEW_KINDS):
        return None
    kind = args[1]
    if background:
        return (f"`pantheon review {kind}` в фоне (run_in_background) записи не даст: фоновую команду хук видит при "
                "запуске, а не по итогу. Запусти без фона — запись делается по итогу команды.")
    if NOT_SIMPLE.search(cmd or ""):
        return (f"`pantheon review {kind}` — только отдельной простой командой, без `;`, `|`, `&`, `<`, `>`, `$(`, "
                "обратных кавычек и переводов строки: иначе код выхода был бы не от тестов, и запись не сделается.")
    if kind == "test":
        return None
    need = REVIEW_KINDS[kind]
    if role != need:
        return (f"`pantheon review {kind}` записывает только {need}: хук guard пишет вердикт по роли, у роли "
                f"«{role or 'субагент'}» записи не будет. Позови {need} — он проверит и запишет сам.")
    if verdict_args(args[2:]) is None:
        return (f"`pantheon review {kind} <owner/repo> <номер PR> <SHA 40 знаков>` — аргументы не в этом формате "
                "(SHA — полный, из `gh pr view N --json headRefOid`).")
    return None


# --- запор gh pr merge ------------------------------------------------------------------------------------------

def _alert_ok(repo, pr):
    """Строка «что ушло» в ~/ai/pantheon/alerts.md: `YYYY-MM-DD HH:MM · кто · текст` со ссылкой owner/repo#N и
    словом «откат». Правдивость строки guard не проверяет."""
    try:
        fd = os.open(os.path.join(G.PANTHEON, "alerts.md"), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return False
    ref = re.compile(r"(?<![\w.-])" + re.escape(repo) + "#" + str(pr) + r"(?!\d)", re.I)
    head = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} · ")
    return any(head.match(ln) and ref.search(ln) and "откат" in ln.lower() for ln in lines)


def _core_problem(repo, pr, sha):
    """Д3: PR защит, который задевает ядро, — только кнопка владельца. Ответа gh нет, список файлов неполон,
    PR на другом коммите — тоже отказ."""
    env = {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}
    try:
        r = subprocess.run(["gh", "pr", "view", str(pr), "-R", repo, "--json", "files,changedFiles,headRefOid"],
                           capture_output=True, text=True, timeout=GH_TIMEOUT, env=env)
        data = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        data = None
    if not isinstance(data, dict):
        return f"{MERGE_CORE}: gh pr view {pr} -R {repo} не ответил, а без списка файлов PR ядро не проверить"
    files, count, head = data.get("files"), data.get("changedFiles"), data.get("headRefOid")
    paths = [f.get("path") for f in files if isinstance(f, dict)] if isinstance(files, list) else None
    if paths is None or not all(isinstance(p, str) for p in paths) or not isinstance(count, int) \
            or len(paths) != count:
        return f"{MERGE_CORE}: список файлов PR неполон (gh отдаёт до 100), ядро не проверить"
    if not isinstance(head, str) or head.lower() != sha:
        return f"{MERGE_CORE}: PR сейчас на другом коммите ({head}), а не на {sha}"
    core = {c.casefold() for c in CORE_FILES}
    hit = [p for p in paths if p.strip("/").casefold() in core]
    if hit:
        return f"{MERGE_CORE}: PR задевает {', '.join(hit)}"
    return None


def gate_problem(event, policy, repo_name, cmd_repos, numbers, auto, heads, advice, protect):
    """Запор (P1-4): то, что проверено, — ровно то, что сливается. Текст отказа или None."""
    if auto:
        return f"без --auto: сливается сейчас ровно проверенный PR, а не позже сам. {advice}"
    if len(numbers) != 1:
        return f"ровно один номер PR: запор сверяет записи на этот PR. {advice}"
    if len(heads) != 1 or not SHA_RE.fullmatch((heads[0] or "").lower()):
        return ("нужен ровно один --match-head-commit <SHA 40 знаков> — коммит, который проверили тесты и argus "
                f"(GitHub сольёт, только если PR на нём). {advice}")
    sha, pr = heads[0].lower(), numbers[0]
    allowed = policy.get("merge_repos")
    allowed = allowed.get(repo_name) if isinstance(allowed, dict) and repo_name else None
    allowed = {r.strip().lower() for r in allowed if isinstance(r, str)} if isinstance(allowed, list) else set()
    tails = sorted({_repo_tail(r) for r in cmd_repos})
    bad = [t for t in tails if t not in allowed]
    if bad:
        return (f"репозиторий {', '.join(bad)} не из [merge_repos] направления {repo_name or '?'} в policy.toml: "
                f"сливать можно только перечисленные там. Нужен — попроси Метиду добавить. {advice}")
    if len(tails) != 1:
        return (f"у папки несколько репозиториев ({', '.join(tails)}) — укажи нужный: gh pr merge {pr} -R "
                f"<owner/repo> --match-head-commit {sha}. {advice}")
    repo = tails[0]
    records = read_records()
    if records is None:
        return ("журнал проверок ~/.local/state/pantheon/merge-gate/records.jsonl не читается (симлинк или сбой) — "
                f"записи не сверить. {MERGE_OWNER}")
    if not any(r["kind"] == "tests" and r["sha"] == sha and repo in [x.lower() for x in r["repo"]] for r in records):
        return (f"нет записи тестов на {repo}@{sha[:12]}: в чистом дереве на этом коммите запусти "
                f"`pantheon review test -- <команда тестов>` (запишет хук guard). {advice}")

    def mine(r, kinds, who):
        return (r["kind"] in kinds and r["by"].get("agent_type") == who and r["pr"] == pr and r["sha"] == sha
                and repo in [x.lower() for x in r["repo"]])

    verdicts = [r for r in records if mine(r, ("accept", "reject"), "argus")]
    if not verdicts:
        return (f"нет «принять» от argus на {repo}#{pr}@{sha[:12]}: позови argus, он проверит и запишет "
                f"`pantheon review accept {repo} {pr} {sha}`. {advice}")
    last = verdicts[-1]
    if last["kind"] != "accept":
        return (f"последний вердикт argus на {repo}#{pr}@{sha[:12]} — «вернуть» (reject): исправь, проверь заново "
                f"и получи новое `pantheon review accept {repo} {pr} <новый SHA>`. {advice}")
    me = ((event or {}).get("session_id") or "", (event or {}).get("agent_id") or "")
    if (last["by"].get("session_id") or "", last["by"].get("agent_id") or "") == me:
        return f"рецензент и сливающий — одна и та же сессия: «принять» должен дать отдельный argus. {advice}"
    if advice == MERGE_PRODUCT:
        if not any(mine(r, ("talos",), "talos") for r in records):
            return (f"продукт — нет проверки talos на {repo}#{pr}@{sha[:12]}: позови talos, он проверит живое "
                    f"приложение и запишет `pantheon review talos {repo} {pr} {sha}`. {advice}")
        if not _alert_ok(repo, pr):
            return (f"продукт — нет строки «что ушло» в ~/ai/pantheon/alerts.md со ссылкой {repo}#{pr} и словом "
                    f"«откат»: `pantheon alert \"{repo}#{pr}: что ушло; откат: <команда>\"`. {advice}")
    if protect:
        why = _core_problem(repo, pr, sha)
        if why:
            return f"{why}. {MERGE_PROTECT}"
    return None


def merge_problem(role, sub, pdir, cwd, moved, args, cmd="", event=None):
    """gh pr merge (metis-0038, guard 0.5.0; запор P1-4, guard 0.5.4). Сливает главная сессия координатора
    направления или его лид (metis-0054): субагент hephaestus-<short> или apollo-<short>, где short — имя направления
    папки запуска после первого «-» (hermes-alex → alex). Дальше лид проверяется как координатор: личное, Метида,
    защиты — те же правила. Режим: защиты — cwd в папках [coordinators] metis-pantheon или репозиторий команды (-R или
    remote папки cwd) совпадает с remote этих папок: только Метида или её лид; продукт ([merge_client]) и внутреннее
    (своё направление по domains.json, для совместимости — [merge]). Затем во всех режимах — запор (gate_problem).
    Любой сбой (политика, реестр, git, журнал, gh) — отказ. Возвращает текст отказа (с тем, что делать) или None."""
    lead = bool(sub) and role.startswith(G.PANTHEON_ROLE_PREFIXES)
    if not lead and (role != "domain-coordinator" or sub):
        return MERGE_CLOSED
    lead_role = role
    if lead:
        role = "domain-coordinator"  # лид сливает за координатора: privileged() ниже — по роли координатора
    policy = G.load_policy()
    coords = policy.get("coordinators")
    if not isinstance(coords, dict):
        # без политики (нет tomllib на Python 3.9 или нет policy.toml) guard не знает папок защит — закрыто всем
        return "политика ~/.claude/pantheon/policy.toml не прочиталась, а без неё папки защит неизвестны. " + MERGE_OWNER
    metis = _str_list(coords.get("metis-pantheon"))
    if metis is None:
        return ("в policy.toml нет списка папок [coordinators] metis-pantheon, а без него папки защит неизвестны. "
                + MERGE_OWNER)
    metis_roots = G._norm(metis)
    conf = G.private_conf(policy)
    ppaths, pcoords = _str_list(conf["paths"]), conf["coordinators"]
    if ppaths is None or not isinstance(pcoords, list) or not all(isinstance(c, str) for c in pcoords):
        return "[private] в policy.toml не разобрать, а без него неизвестно, у кого личное. " + MERGE_OWNER
    if any(G._inside(x, [pdir]) for x in G._norm(ppaths)) or any(G.privileged(policy, c, role, pdir) for c in pcoords):
        return ("координатор с доступом к личному не сливает: третье свойство (наружу) ему закрыто, как и push "
                "(SEC-13). " + MERGE_OWNER)
    domains = _merge_domains()
    if domains is None:
        return "реестр направлений ~/.local/state/pantheon/domains.json пуст или не разбирается. " + MERGE_OWNER
    name = _merge_owner(domains, pdir)
    if lead:
        # лид — только своего направления: имя роли собирает pantheon roles build из имени направления
        short = name.split("-", 1)[1] if name and name != MERGE_AMBIGUOUS and "-" in name else None
        if not short or lead_role not in {f"{b}-{short}" for b in MERGE_LEADS}:
            where = (name if short else f"у направления {name} нет лидов по имени" if name and name != MERGE_AMBIGUOUS
                     else "направление не установлено")
            return (f"{lead_role} — не лид направления этой сессии ({where}): "
                    "лид сливает только PR своего направления. " + MERGE_CLOSED)
    # лид получает права Метиды только как лид metis-pantheon: папка из её [coordinators], которую реестр по ошибке
    # отдал другому направлению, лиду того направления защиты не открывает
    metis_ok = G.privileged(policy, "metis-pantheon", role, pdir) and (not lead or name == "metis-pantheon")
    is_metis = metis_ok or name == "metis-pantheon"
    if moved:
        return "только из папки своего репозитория, без cd в команде. " + (MERGE_PROTECT if is_metis else MERGE_INTERNAL)
    if re.search(r"\bGH_(?:REPO|HOST)\b", cmd):
        return "без чужого репозитория (GH_REPO, GH_HOST). " + (MERGE_PROTECT if is_metis else MERGE_INTERNAL)
    why, repos, numbers, auto, heads = _merge_args(args)
    # репозитории защит — remote папок metis-pantheon: gh сливает в репозиторий из remote папки, а не в папку, и клон
    # agent-kit в своей папке иначе слился бы как внутреннее
    protect_repos = set()
    for r in metis_roots:
        if os.path.lexists(os.path.join(r, ".git")):
            remotes = _git_remotes(r)
            if remotes is None:
                return (f"у папки защит {r.replace(G.HOME, '~')} не читается git remote — репозитории защит не "
                        "установить. " + MERGE_OWNER)
            protect_repos |= {_repo_tail(x) for x in remotes}
    if repos:
        cmd_repos = [_repo_arg(r) for r in repos]
    else:
        cmd_repos = _git_remotes(cwd)
        if not cmd_repos:
            return ("не понять репозиторий: папка не репозиторий git, у него нет remote или git не ответил. "
                    + (MERGE_PROTECT if is_metis else MERGE_INTERNAL))
        resolved = _gh_resolved(cwd)
        if resolved is None:
            return ("не понять репозиторий: git config (gh-resolved, gh repo set-default) не читается. "
                    + (MERGE_PROTECT if is_metis else MERGE_INTERNAL))
        cmd_repos = sorted(set(cmd_repos) | set(resolved))
    # защиты — по пути и по репозиторию, раньше реестра: domains.json может по ошибке отдать agent-kit другому
    protect = G._inside(cwd, metis_roots) or any(_repo_tail(r) in protect_repos for r in cmd_repos)
    repo_name = name  # чей [merge_repos]: направление по domains.json (в режиме 0.4.7 — имя из [merge])
    if protect:
        if not metis_ok:
            return ("это защиты (папка или репозиторий metis-pantheon), а сессия запущена не Метидой. " + MERGE_PROTECT +
                    " Нужна правка защит — опиши её Метиде файлом в ~/ai/pantheon/directions/metis-pantheon/inbox/.")
        advice = MERGE_PROTECT
    elif not isinstance(policy.get("merge_client"), dict):
        # новая схема включается строкой [merge_client] в policy.toml (шаг Метиды); до неё — как в 0.4.7: сливают
        # только направления из [merge], в его папках, -R — из [merge_repos] по имени из [merge]
        merge = policy.get("merge")
        found = next(((n, G._norm(v)) for n, v in (merge.items() if isinstance(merge, dict) else ())
                      if _str_list(v) and G._inside(pdir, G._norm(v))), None)
        if not found:
            return ("слияние делает владелец: новая схема не включена ([merge_client] в policy.toml нет), а "
                    "направления нет в [merge]. " + MERGE_INTERNAL)
        repo_name, roots = found
        if not G._inside(cwd, roots):
            return "только из папки своего репозитория из [merge]. " + MERGE_INTERNAL
        advice = MERGE_INTERNAL
    else:
        def listed(table):
            t = policy.get(table)
            v = _str_list(t.get(name)) if isinstance(t, dict) and name else None
            return G._norm(v) if v else []
        client = listed("merge_client")
        owner = _merge_owner(domains, cwd)
        mine = owner == name if owner is not None else G._inside(cwd, listed("merge") + client)
        if not name or name == MERGE_AMBIGUOUS or not mine:
            return ("только в папках своего направления (domains.json), а это чужая папка — её сливает свой "
                    "координатор или владелец. " + MERGE_INTERNAL)
        advice = MERGE_PRODUCT if G._inside(cwd, client) else MERGE_INTERNAL
    if why:
        return f"{why}. {advice}"
    if repos:
        # -R — только репозиторий из [merge_repos] направления: сессия Фемиды стоит в legal-watch, а сливает и
        # PR expert-corpus (themis-0015, ответ владельца 15.10 «А и Б»). Сверка по точному owner/repo на github.com
        allowed = policy.get("merge_repos")
        allowed = allowed.get(repo_name) if isinstance(allowed, dict) and repo_name else None
        allowed = {r.strip().lower() for r in allowed if isinstance(r, str)} if isinstance(allowed, list) else set()
        if not all(_merge_repo_ok(r, allowed) for r in repos):
            return f"без чужого репозитория (-R): только из [merge_repos] своего направления. {advice}"
        if not numbers:
            return f"с -R PR указывай номером. {advice}"
    return gate_problem(event, policy, repo_name, cmd_repos, numbers, auto, heads, advice, protect)
