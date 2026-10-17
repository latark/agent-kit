"""Запор слияния guard (P1-4, Д2, Д3, guard 0.5.4) — часть ядра защит: ядро — весь plugins/guard/**, общие роли
plugins/pantheon/roles/** и правила окон plugins/pantheon/lib/window_rules.py, casefold; файлы из pulls/N/files с
previous_filename. PR, задевающий ядро, агенты не сливают: он ждёт слияния владельцем (Д3).

Модуль без своего состояния: общие помощники guard.py (load_policy, privileged, private_conf, _inside, _norm, _key,
STATE_DIR, PANTHEON, HOME, DOMAINS_FILE…) берутся через G — его присваивает guard.py при загрузке
(`merge_gate.G = <модуль guard>`). Пути считаются при вызове, а не при импорте: тесты подменяют HOME.

Две части.
1. Журнал проверок STATE_DIR/merge-gate/records.jsonl. Пишет только хук guard на PostToolUse (record): команда
   Bash успешно завершилась, она простая (без ; | & && || $( ` и перенаправлений) и это `pantheon review <вид> …`.
     tests          — `pantheon review test -- <команда>`: SHA — HEAD папки cwd, дерево чистое; repo — её remote;
                      программа после обёрток (heavy, env VAR=…, time, nice, timeout N, uv run) и присваиваний VAR=x — не
                      пустая (true, echo…, python3 -c pass, sh -c '', node без скрипта); неразобранное слово
                      (`$UNSET/t.py`) и относительный путь (`./test`) пустыми не считаются; саму команду после -- guard судит как голую (guard.py, 0.5.8);
     accept, reject — `pantheon review accept|reject <owner/repo> <PR> <SHA> [--opened … --ran … --unchecked …]`,
                      только agent_type argus; у accept все три поля перечня (Б6) обязательны и непусты;
     talos          — `pantheon review talos <owner/repo> <PR> <SHA>`, только agent_type talos.
   Строка: {"v":1,"kind","repo":[owner/repo…],"pr":N|null,"sha","by":{agent_type,agent_id,session_id},"cwd","time",
   "tool_use_id","cmd"}, у accept (и у reject с полями) — ещё "checklist":{"opened","ran","unchecked"}. Подделать запись роль не может: ~/.local/state/pantheon закрыт ролям песочницей и
   pantheon-acl, а вид записи хук берёт из agent_type события, а не из текста команды. Битые строки при чтении
   пропускаются: битая запись может только не дать разрешения.
2. merge_problem — правило gh pr merge: кто сливает (координатор или его лид), чьё направление, защиты, затем запор:
   один номер PR, без --auto и --admin, ровно один --match-head-commit <SHA> (его сверяет GitHub), все репозитории
   команды — из [merge_repos] направления, запись tests на (repo, SHA), вердикты argus на (repo, PR, SHA): рецензент —
   пара (session_id, agent_id), у каждого считается его последний вердикт; пускает, только если рецензент есть,
   последний вердикт каждого — accept с полным перечнем проверенного (Б6) и ни один рецензент не тот, кто сливает.
   reject снимает только accept того же рецензента после него или новый коммит (metis-0158: два argus на одном
   head — accept и reject в любом порядке дают отказ); продукт — ещё запись talos и строка в ~/ai/pantheon/alerts.md со ссылкой
   owner/repo#N и словом «откат»; защиты — ещё Д3: PR не задевает ядро (CORE_DIR и CORE_FILES), casefold;
   файлы из pulls/N/files с previous_filename. В защитах accept засчитывается, только если его ran начинается с
   «модель: claude-opus» (metis-0176): accept другой модели — как будто его нет, reject любой модели в силе.
   Незаменённый шаблон «<ID>» в ran — отказ ещё до записи.
Правдивость поля ran (модель argus) guard не проверяет: это защита от ошибки шаблона и запуска не той модели.
Чего guard не проверяет: правдивость строки в сводке и перечня argus и то, что выбранная команда тестов — настоящие
тесты: пустую программу (true, echo…, python3 -c pass, sh -c '') он ловит по короткому списку, а придуманную
пустышку вроде `python3 -c "import os"` — нет (защита от ошибки, не от обхода).
"""

import ast
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
# форма команды слияния в подсказках — с -R: правило autoMode «Pantheon Gated Merge» покрывает только её (metis-0154)
MERGE_CMD = "gh pr merge N -R <owner/repo> --match-head-commit <SHA> --merge"
MERGE_INTERNAL = ("Внутреннее сливай после записей шлюза слияния: тесты (`pantheon review test -- <команда>`) и "
                  f"«принять» от argus на этот SHA, затем {MERGE_CMD}.")
MERGE_PRODUCT = ("Продукт для клиентов сливай после записей шлюза слияния: тесты, «принять» от argus и проверка talos "
                 "на этот SHA, строка в сводке «что ушло» со ссылкой owner/repo#N и откатом (`pantheon alert`), затем "
                 f"{MERGE_CMD}.")
MERGE_PROTECT = ("Защиты сливает только Метида или её лид через шлюз слияния: тесты и «принять» от argus на этот SHA, "
                 f"{MERGE_CMD}; PR, который задевает ядро защит (весь plugins/guard/, plugins/pantheon/roles/, "
                 "plugins/pantheon/lib/window_rules.py и .claude-plugin/marketplace.json), ждёт слияния владельцем (Д3).")
MERGE_OWNER = "Слияние делает владелец."
MERGE_AMBIGUOUS = "\0два направления"
MERGE_CORE = "ядро защит — PR ждёт слияния владельцем (Д3)"
# ядро защит (Д3): эти файлы агенты не сливают — гарантия, что запор не ослабит сам себя
CORE_FILES = ("plugins/guard/hooks/merge_gate.py", "plugins/guard/hooks/protect_config.py",
              "plugins/guard/managed-settings.json",
              # правила autoMode и permissions окон: разрешают слияние через шлюз и запись вердиктов (metis-0174)
              "plugins/pantheon/lib/window_rules.py",
              ".claude-plugin/marketplace.json")  # откуда ставятся плагины: подмена источника guard (metis-0115)
# и папки целиком: весь плагин guard (metis-0092) — код, тесты, README, настройки; общие роли Пантеона — в них
# правила ролей, которые guard проверяет по agent_type (metis-0182). Папки может ещё не быть в main — путь всё равно ядро
CORE_DIR = ("plugins/guard", "plugins/pantheon/roles")
GH_TIMEOUT = 6
SHA_RE = re.compile(r"[0-9a-f]{40}")
REPO_RE = re.compile(r"[a-z0-9_.-]+/[a-z0-9_.-]+")
PR_RE = re.compile(r"[1-9][0-9]{0,8}")
RECORD_V = 1
REVIEW_KINDS = {"accept": "argus", "reject": "argus", "talos": "talos"}  # вид записи → кто её пишет
# простая команда: без цепочек, конвейеров, подстановок и перенаправлений (разбор guard для неё не нужен)
NOT_SIMPLE = re.compile(r"[;|&<>`\n\r]|\$\(")
# перечень проверенного в «принять» (Б6): что argus открыл, что запустил, чего не проверял — поля записи и флаги
CHECKLIST = ("opened", "ran", "unchecked")
CHECKLIST_HINT = '--opened "<что открыл>" --ran "<что запустил>" --unchecked "<что не проверял>"'
# защиты: «принять» засчитывается, только если argus проверял на Opus — поле ran начинается с «модель: claude-opus»
# (metis-0176). Незаменённый шаблон «<ID>» в ran — ошибка шаблона роли, а не модель
OPUS_RAN = re.compile(r"\s*модель:\s*claude-opus", re.I)
UNFILLED_ID = re.compile(r"<\s*id\s*>", re.I)
UNFILLED_ID_HINT = ("в --ran остался шаблон «<ID>»: подставь ID своей модели из системной подсказки — "
                    "`--ran \"модель: claude-opus-…, что запустил\"`")
# пустая команда тестов: программа, которая ничего не проверяет (защита от ошибки, список короткий и явный); ещё
# python без скрипта или с пустым -c и оболочка без скрипта или с пустым -c (metis-0157, guard 0.5.8)
EMPTY_TEST_PROGRAMS = {"true", ":", "echo", "printf", "exit", "test", "[", "sleep", "yes"}
EMPTY_PYTHON = re.compile(r"python[0-9.]*t?|pypy[0-9.]*")  # и python3.14t (free-threaded), pypy3
EMPTY_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
# обёртки перед программой тестов: имя → флаги, за которыми идёт отдельное значение
TEST_WRAPPERS = {"heavy": set(), "env": {"-u", "--unset", "-C", "--chdir"}, "time": set(),
                 "nice": {"-n", "--adjustment"}, "timeout": {"-s", "--signal", "-k", "--kill-after"},
                 # `uv run <программа>` (metis-0177): uv run python без скрипта — такой же пустой python
                 "uv run": {"--with", "--with-editable", "--with-requirements", "-p", "--python", "--project",
                            "--directory", "--package", "--extra", "--group", "--only-group", "--no-group",
                            "--env-file", "--index", "--default-index", "-w"}}
# присваивание перед программой (`CI=1 true`): оболочка его не запускает — судим программу за ним (metis-0177)
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# node без скрипта или с -e/-p из литералов, process.exit и console.log литерала — ничего не проверяет (metis-0177)
EMPTY_NODE = {"node", "nodejs"}
NODE_NOOP_ARGS = {"-", "-v", "--version", "-h", "--help"}
NODE_EVAL = {"-e", "--eval", "-p", "--print"}
_JS_LIT = r"""(?:-?\d+(?:\.\d+)?|true|false|null|undefined|'[^'\\]*'|"[^"\\]*")"""
NODE_NOOP_CODE = re.compile(rf"\s*(?:(?:{_JS_LIT}|process\.exit\(\s*{_JS_LIT}?\s*\)|console\.log\(\s*{_JS_LIT}?\s*\))"
                            r"\s*(?:;\s*)?)*")


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
    """owner/repo без хоста: псевдоним ssh (git@gh-alias:org/repo) gh понимает как github.com, поэтому
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
    направления шире, и с ним координатор слил бы в чужой репозиторий (ревью argus 210766a)."""
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


def verdict_parse(kind, args):
    """Аргументы `pantheon review accept|reject|talos …` → ((repo, pr, sha), перечень {поле: значение}, None) или
    (None, None, текст ошибки). Флаги перечня (Б6) — только у accept и reject, в любом месте, `--ran X` или
    `--ran=X`; у accept все три обязательны и непусты, у reject — по желанию (пустые не сохраняются)."""
    flags = kind in ("accept", "reject")
    fmt = f"`pantheon review {kind} <owner/repo> <номер PR> <SHA 40 знаков>" + (
        f" {CHECKLIST_HINT}`" if kind == "accept" else " [--opened … --ran … --unchecked …]`" if flags else "`")
    pos, checklist, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if not isinstance(a, str):
            return None, None, f"{fmt} — аргументы не в этом формате"
        if flags and a.startswith("--") and len(a) > 2:
            name, eq, val = a[2:].partition("=")
            if name not in CHECKLIST:
                return None, None, f"{fmt} — неизвестный флаг --{name}"
            if name in checklist:
                return None, None, f"{fmt} — --{name} указан дважды"
            if not eq:
                if i + 1 >= len(args) or not isinstance(args[i + 1], str):
                    return None, None, f"{fmt} — у --{name} нет значения"
                i += 1
                val = args[i]
            if val.strip().startswith("--"):  # `--opened --ran …`: имя флага — не значение (ревью argus, PR #25)
                return None, None, f"{fmt} — значение --{name} начинается с «--»: похоже, пропущено значение"
            checklist[name] = val.strip()
        else:
            pos.append(a)
        i += 1
    parsed = verdict_args(pos)
    if parsed is None:
        return None, None, f"{fmt} — аргументы не в этом формате (SHA — полный, из `gh pr view N --json headRefOid`)"
    if kind == "accept":
        missing = [f"--{k}" for k in CHECKLIST if not checklist.get(k)]
        if missing:
            return None, None, (f"«принять» без перечня проверенного (Б6): нет или пусто {', '.join(missing)}. Формат: "
                                f"{fmt}. Запор пускает только «принять», где сказано, что открыто, что запущено и "
                                "чего argus не проверял")
        if UNFILLED_ID.search(checklist.get("ran", "")):
            return None, None, f"«принять» не записан: {UNFILLED_ID_HINT}"
    return parsed, {k: v for k, v in checklist.items() if v}, None


def checklist_ok(rec):
    """У записи accept — полный перечень Б6: словарь с непустыми строками opened, ran, unchecked."""
    c = rec.get("checklist")
    return isinstance(c, dict) and all(isinstance(c.get(k), str) and c[k].strip() for k in CHECKLIST)


def _prog(word):
    """Имя программы в нижнем регистре (macOS не различает регистр: TRUE — это true); None — слово не разобрано
    (разбор Bash отдаёт None для `$UNSET`, `${X:-y}`): неизвестно, что запустится (metis-0164)."""
    return os.path.basename(word.rstrip("/")).lower() if isinstance(word, str) else None


def _program_at(argv):
    """Индекс программы после обёрток TEST_WRAPPERS и присваиваний VAR=x; None — после них ничего нет."""
    i = 0
    while i < len(argv):
        if isinstance(argv[i], str) and ASSIGNMENT.match(argv[i]):
            i += 1
            continue
        name = _prog(argv[i])
        if name == "uv":
            j = i + 1
            while j < len(argv) and isinstance(argv[j], str) and argv[j].startswith("-") and argv[j] != "--":
                j += 1  # общие флаги uv (--quiet, --offline)
            if j >= len(argv) or argv[j] != "run":
                return i  # uv pip, uv sync … — сама программа uv
            i, name = j, "uv run"
        elif name not in TEST_WRAPPERS:
            return i
        takes, i = TEST_WRAPPERS[name], i + 1
        while i < len(argv):
            a = argv[i]
            if not isinstance(a, str):
                break  # неразобранное слово: дальше судить нечего, его и считаем программой (неизвестной)
            if a == "--":
                i += 1
                break
            if a in takes:
                i += 2
            elif a.startswith("-") or (name == "env" and "=" in a):
                i += 1
            else:
                break
        if name == "timeout":
            i += 1  # длительность
    return None


def _py_code(args):
    """Аргументы python → тело -c; "" — ни скрипта, ни -c, ни -m (читает stdin); None — скрипт, модуль (-m) или
    неразобранное слово (`$UNSET/t.py`): что запустится, неизвестно, — не пусто."""
    i = 0
    while i < len(args):
        a = args[i]
        if not isinstance(a, str):
            return None
        if a == "--":
            return None if i + 1 < len(args) else ""
        if not a.startswith("-"):
            return None  # скрипт
        if a == "-" or a.startswith("--"):
            i += 1
            continue
        for j, c in enumerate(a[1:], 2):
            if c in "cm":
                if c == "m":
                    return None
                body = a[j:] if a[j:] else (args[i + 1] if i + 1 < len(args) else "")
                return body if isinstance(body, str) else None
            if c in "WX":  # флаг со значением: остаток токена или следующее слово
                i += 0 if a[j:] else 1
                break
        i += 1
    return ""


def _py_empty(code):
    """Тело python -c из pass, литералов и print/exit/quit с литералами — ничего не проверяет."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return False

    def noop(n):
        if isinstance(n, ast.Pass):
            return True
        if not isinstance(n, ast.Expr):
            return False
        v = n.value
        if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id in ("print", "exit", "quit"):
            return not v.keywords and all(isinstance(x, ast.Constant) for x in v.args)
        return isinstance(v, ast.Constant)
    return all(noop(n) for n in tree.body)


def _sh_code(args):
    """Аргументы sh/bash/zsh → тело -c; "" — ни -c, ни скрипта (читает stdin); None — скрипт из файла или
    неразобранное слово (`bash $UNSET/run.sh`, `sh -c "$UNSET"`): не пусто."""
    i, want_c = 0, False
    while i < len(args):
        a = args[i]
        if not isinstance(a, str):
            return None
        if a == "--":
            i += 1
            break
        if a in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            i += 2
            continue
        if a[:1] in "-+" and len(a) > 1:
            want_c = want_c or (a[0] == "-" and not a.startswith("--") and "c" in a[1:])
            i += 1
            continue
        break
    if want_c:
        return (args[i] if isinstance(args[i], str) else None) if i < len(args) else ""
    return None if i < len(args) else ""


def _relative(word):
    """Путь со «/», но не абсолютный: `./test`, `script/test` — скрипт проекта. `/usr/bin/true` судится по имени."""
    return "/" in word and not word.startswith("/")


def _node_empty(args):
    """Аргументы node без скрипта: только флаги из NODE_NOOP_ARGS и -e/-p с пустым кодом (`node -e 0`)."""
    i = 0
    while i < len(args):
        a = args[i]
        if not isinstance(a, str):
            return False
        if a in NODE_EVAL:
            code = args[i + 1] if i + 1 < len(args) else ""
            if not isinstance(code, str) or not NODE_NOOP_CODE.fullmatch(code):
                return False
            i += 2
        elif a in NODE_NOOP_ARGS:
            i += 1
        else:
            return False  # скрипт, --test, --require … — что запустится, не судим
    return True


def _empty_run(argv, depth=0):
    """Команда ничего не проверяет → имя программы для текста отказа («нет» — пусто); иначе None. Пусто: программы
    EMPTY_TEST_PROGRAMS, python без скрипта или с -c из pass/литералов/print/exit, оболочка без скрипта или с -c,
    где каждая команда пустая (`sh -c ''`, `bash -c 'true'`). Неразобранное слово (None) — неизвестно, не пусто;
    относительный путь (`./test`, `bin/test`) — скрипт проекта, а не программа из списка (metis-0164)."""
    i = _program_at(argv)
    if i is None:
        return "нет"
    word, rest = argv[i], argv[i + 1:]
    prog = _prog(word)
    if prog is None:
        return None
    if not prog or (prog in EMPTY_TEST_PROGRAMS and not _relative(word)):
        return prog or "нет"
    if prog in EMPTY_NODE and _node_empty(rest):
        return f"{prog} без тестов"
    if EMPTY_PYTHON.fullmatch(prog):
        code = _py_code(rest)
        return f"{prog} без тестов" if code is not None and _py_empty(code) else None
    if prog in EMPTY_SHELLS and depth < 3:
        code = _sh_code(rest)
        if code is None or re.search(r"[;|&`<>(\n]", code):
            return None  # скрипт из файла или цепочка, конвейер, подстановка — не судим (review test их и так не пустит)
        try:
            words = shlex.split(code)
        except ValueError:
            return None
        if not words or _empty_run(words, depth + 1):
            return f"{prog} без тестов"
    return None


def empty_test_problem(argv):
    """Команда тестов ничего не проверяет (true, echo ok, heavy :, env X=1 timeout 5 sleep 1, python3 -c pass,
    sh -c '', bash -c 'true') — текст отказа; иначе None. Защита от ошибки, а не от обхода: список короткий и явный."""
    prog = _empty_run(argv)
    if prog:
        shown = " ".join(w if isinstance(w, str) else "?" for w in argv)  # None — неразобранное слово
        return (f"команда тестов `{shown or 'пусто'}` ничего не проверяет (программа «{prog}»): "
                "запор пишет тесты только для настоящей команды — например, `pantheon review test -- heavy python3 -I "
                "tests/test_x.py` или `pantheon review test -- heavy pnpm test`")
    return None


BARE_VAR = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})")


def vanishing_test_problem(cmd):
    """`pantheon review test -- python3 -I $TESTFILE`: слово `$X`/`${X}` целиком и без кавычек при незаданной
    переменной исчезает (окружение между вызовами Bash не сохраняется — частая ошибка агента). Команду судим так,
    будто его нет: пустая → текст отказа; иначе None. Разбор Bash отдаёт None и для `$X`, и для `$X/t.py` — их
    различает только исходный текст: токены с кавычками (posix=False) и сравнение с BARE_VAR (metis-0164)."""
    try:
        raw = shlex.split(cmd or "", posix=False)
    except ValueError:
        return None
    k = next((i for i in range(len(raw) - 2) if raw[i:i + 3] == ["review", "test", "--"]), None)
    if k is None:
        return None
    rest = raw[k + 3:]
    gone = [t for t in rest if BARE_VAR.fullmatch(t)]
    if not gone:
        return None
    try:
        words = shlex.split(" ".join(t for t in rest if not BARE_VAR.fullmatch(t)))
    except ValueError:
        return None
    prog = _empty_run(words)
    if not prog:
        return None
    return (f"в команде тестов `{' '.join(rest)}` слово {', '.join(gone)} без кавычек при незаданной переменной "
            f"исчезает, и остаётся `{' '.join(words) or 'пусто'}` — ничего не проверяет (программа «{prog}»). "
            "Окружение между вызовами Bash не сохраняется — пиши путь буквально: `pantheon review test -- heavy "
            "python3 -I tests/test_x.py`")


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


def _bg_id(resp):
    """Фоновая — только если backgroundTaskId непустой (строка или число); null и пустое — не фон."""
    v = resp.get("backgroundTaskId")
    return (isinstance(v, str) and bool(v.strip())) or (isinstance(v, (int, float)) and not isinstance(v, bool))


def record(event):
    """PostToolUse (только успешная команда): запись в журнал проверок или ничего."""
    if event.get("tool_name") != "Bash":
        return None
    tool_input, resp = event.get("tool_input") or {}, event.get("tool_response")
    # фоновая команда: Claude Code шлёт PostToolUse при запуске, а не по итогу, и PostToolUseFailure не будет
    # (ревью argus PR #18) — по ней ничего не пишем; уведённую в фон (Ctrl+B) выдаёт backgroundTaskId в ответе
    if not isinstance(tool_input, dict) or tool_input.get("run_in_background") \
            or not isinstance(resp, dict) or _bg_id(resp):
        return None
    # упавшая команда приходит PostToolUseFailure; если код выхода всё же есть в ответе и он не 0 — тоже не пишем
    if any(resp.get(k) not in (0, None) for k in ("exit_code", "exitCode", "returnCode")):
        return None
    cmd = tool_input.get("command") or ""
    words = simple_review(cmd)
    if not words:
        return None
    kind, args = words[1], words[2:]
    role = event.get("agent_type") or ""
    cwd = os.path.realpath(event.get("cwd") or "")
    if kind == "test":
        if len(args) < 2 or args[0] != "--" or empty_test_problem(args[1:]) or vanishing_test_problem(cmd):
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
        parsed, checklist, _ = verdict_parse(kind, args)
        if not parsed:
            return None
        repo, pr, sha = parsed
        rec_kind, repos = kind, [repo]
    else:
        return None
    rec = {"v": RECORD_V, "kind": rec_kind, "repo": repos, "pr": pr, "sha": sha,
           "by": {"agent_type": role, "agent_id": event.get("agent_id") or "",
                  "session_id": event.get("session_id") or ""},
           "cwd": cwd, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "tool_use_id": event.get("tool_use_id") or "", "cmd": cmd}
    if rec_kind in ("accept", "reject") and checklist:
        rec["checklist"] = checklist
    append_record(rec)
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
    if kind == "accept" and UNFILLED_ID.search(cmd or ""):  # раньше NOT_SIMPLE: в «<ID>» есть < и >
        return f"«принять» не записан: {UNFILLED_ID_HINT}. Записи не будет."
    if NOT_SIMPLE.search(cmd or ""):
        return (f"`pantheon review {kind}` — только отдельной простой командой, без `;`, `|`, `&`, `<`, `>`, `$(`, "
                "обратных кавычек и переводов строки: иначе код выхода был бы не от тестов, и запись не сделается.")
    if kind == "test":
        why = empty_test_problem(args[3:]) if len(args) >= 4 and args[2] == "--" else None
        why = why or vanishing_test_problem(cmd)
        return f"{why}. Записи не будет." if why else None
    need = REVIEW_KINDS[kind]
    if role != need:
        return (f"`pantheon review {kind}` записывает только {need}: хук guard пишет вердикт по роли, у роли "
                f"«{role or 'субагент'}» записи не будет. Позови {need} — он проверит и запишет сам.")
    _, _, why = verdict_parse(kind, args[2:])
    return f"{why}. Записи не будет." if why else None


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


def _gh_json(args):
    """Вывод gh как список JSON-значений подряд (--paginate склеивает страницы: `[..][..]` или объекты по строкам);
    None — сбой gh или неразборный ответ."""
    env = {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}
    try:
        r = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=GH_TIMEOUT, env=env)
        if r.returncode != 0:
            return None
        dec, text, pos, out = json.JSONDecoder(), r.stdout, 0, []
        while True:
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if pos >= len(text):
                return out
            val, pos = dec.raw_decode(text, pos)
            if isinstance(val, list):
                out.extend(val)
            else:
                out.append(val)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _is_core(path, core_files):
    """Ядро (metis-0092, решение владельца 15.10): папки CORE_DIR целиком без учёта регистра и отдельные файлы вне них."""
    p = path.strip("/").casefold()
    while p.startswith("./"):
        p = p[2:].lstrip("/")
    return p in core_files or any(p == d or p.startswith(d + "/") for d in CORE_DIR)


def _core_problem(repo, pr, sha):
    """Д3: PR защит, который задевает ядро, ждёт слияния владельцем. Файлы — из REST pulls/N/files (там есть
    status и previous_filename: переименование ядра не прячет старый путь). Ответа gh нет, список файлов неполон,
    PR на другом коммите — тоже отказ."""
    heads = _gh_json(["pr", "view", str(pr), "-R", repo, "--json", "headRefOid,changedFiles"])
    data = heads[0] if isinstance(heads, list) and len(heads) == 1 else None
    if not isinstance(data, dict):
        return f"{MERGE_CORE}: gh pr view {pr} -R {repo} не ответил, а без списка файлов PR ядро не проверить"
    count, head = data.get("changedFiles"), data.get("headRefOid")
    files = _gh_json(["api", f"repos/{repo}/pulls/{pr}/files?per_page=100", "--paginate", "--jq", ".[]"])
    paths = None
    if isinstance(files, list) and all(isinstance(f, dict) for f in files):
        paths = []
        for f in files:
            paths.append(f.get("filename"))
            if f.get("previous_filename") is not None:
                paths.append(f.get("previous_filename"))
    if paths is None or not all(isinstance(p, str) for p in paths) or not isinstance(count, int) \
            or isinstance(count, bool) or len(files) != count:
        return f"{MERGE_CORE}: список файлов PR не получен или неполон, ядро не проверить"
    if not isinstance(head, str) or head.lower() != sha:
        return f"{MERGE_CORE}: PR сейчас на другом коммите ({head}), а не на {sha}"
    core = {c.casefold() for c in CORE_FILES}
    hit = [p for p in paths if _is_core(p, core)]
    if hit:
        return f"{MERGE_CORE}: PR задевает {', '.join(hit)}"
    return None


def _reviewer(rec):
    """Рецензент записи — пара (session_id, agent_id): два argus одной сессии — разные рецензенты (metis-0158)."""
    return rec["by"].get("session_id") or "", rec["by"].get("agent_id") or ""


def _who(rec):
    """Чей вердикт — для текста отказа: роль, первые 8 знаков agent_id и session_id, время записи."""
    sid, aid = _reviewer(rec)
    return (f"{rec['by'].get('agent_type') or '?'} agent {aid[:8] or '—'}, сессия {sid[:8] or '—'}, "
            f"запись {rec.get('time') if isinstance(rec.get('time'), str) else '?'}")


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
                f"<owner/repo> --match-head-commit {sha} --merge. {advice}")
    repo = tails[0]
    records = read_records()
    if records is None:
        return ("журнал проверок ~/.local/state/pantheon/merge-gate/records.jsonl не читается (симлинк или сбой) — "
                f"записи не сверить. {MERGE_OWNER}")
    if not any(r["kind"] == "tests" and r["sha"] == sha and repo in [x.lower() for x in r["repo"]] for r in records):
        return (f"нет записи тестов на {repo}@{sha[:12]}: в чистом дереве на этом коммите запусти "
                f"`pantheon review test -- <команда тестов>` (запишет хук guard). Тесты долгие: запускай "
                f"`pantheon review test` не в фоне, с timeout до 600000 мс (у Bash по умолчанию 120 с). {advice}")

    def mine(r, kinds, who):
        return (r["kind"] in kinds and r["by"].get("agent_type") == who and r["pr"] == pr and r["sha"] == sha
                and repo in [x.lower() for x in r["repo"]])

    verdicts = [r for r in records if mine(r, ("accept", "reject"), "argus")]
    # защиты (metis-0176): «принять» не на Opus не засчитывается — как будто его нет; «вернуть» любой модели в силе,
    # «принять» без перечня остаётся, чтобы отказ Б6 ниже сказал о перечне
    weak = [r for r in verdicts if protect and r["kind"] == "accept" and checklist_ok(r)
            and not OPUS_RAN.match(r["checklist"]["ran"])]
    verdicts = [r for r in verdicts if not any(r is w for w in weak)]
    if not verdicts and weak:
        unfilled = any(UNFILLED_ID.search(r["checklist"]["ran"]) for r in weak)
        return (f"«принять» на {repo}#{pr}@{sha[:12]} от {'; '.join(_who(r) for r in weak)} — не на Opus: в "
                "репозитории защит шлюз засчитывает только проверку argus на модели claude-opus (--ran начинается с "
                "«модель: claude-opus»). Проверку повторяет argus на Opus и записывает `pantheon review accept "
                f"{repo} {pr} {sha} --ran \"модель: claude-opus-…, что запустил\" …`."
                + (f" Кроме того, {UNFILLED_ID_HINT}." if unfilled else "") + f" {advice}")
    if not verdicts:
        return (f"нет «принять» от argus на {repo}#{pr}@{sha[:12]}: позови argus, он проверит и запишет "
                f"`pantheon review accept {repo} {pr} {sha} {CHECKLIST_HINT}`. {advice}")
    latest = {}  # рецензент (session_id, agent_id) → его последний вердикт; порядок — по первой записи рецензента
    for r in verdicts:
        latest[_reviewer(r)] = r
    rejects = [r for r in latest.values() if r["kind"] != "accept"]
    if rejects:
        return (f"«вернуть» (reject) на {repo}#{pr}@{sha[:12]} от {'; '.join(_who(r) for r in rejects)}: его снимает "
                "только «принять» того же рецензента, записанное после него (верни ему исправление), или новый коммит "
                f"с новыми записями тестов и argus — `pantheon review accept {repo} {pr} <новый SHA>`. «Принять» "
                f"другого argus «вернуть» не перекрывает. {advice}")
    old = [r for r in latest.values() if not checklist_ok(r)]
    if old:
        return (f"«принять» на {repo}#{pr}@{sha[:12]} от {'; '.join(_who(r) for r in old)} — без перечня "
                f"проверенного (Б6): запись старого формата или неполная. Тот же argus, повтори `pantheon review "
                f"accept {repo} {pr} {sha} {CHECKLIST_HINT}`. {advice}")
    me = ((event or {}).get("session_id") or "", (event or {}).get("agent_id") or "")
    if me in latest:
        return (f"рецензент и сливающий — одна и та же сессия: «принять» должен дать отдельный argus, а среди "
                f"рецензентов {repo}#{pr}@{sha[:12]} — и сливающий. {advice}")
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
    папки запуска после первого «-» (apollo-shop → shop). Дальше лид проверяется как координатор: личное, Метида,
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
    # guard читает [private] мягко (0163: неверное значение — умолчание), а шлюз слияния на неверном [private] закрыт:
    # опечатка в списке coordinators не должна молча открыть слияние координатору с личным. Пустой список [] — как у
    # guard: roles и coordinators — никого, paths — умолчание (ревью PR #35)
    raw = policy.get("private", {})
    if not isinstance(raw, dict) or any(
            k in raw and _str_list(raw[k]) is None and raw[k] != [] for k in G.DEFAULT_PRIVATE):
        ppaths = None
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
        # -R — только репозиторий из [merge_repos] направления: сессия координатора стоит в одном
        # репозитории, а сливает и PR соседнего репозитория направления (решение владельца 15.10). Сверка по точному owner/repo на github.com
        allowed = policy.get("merge_repos")
        allowed = allowed.get(repo_name) if isinstance(allowed, dict) and repo_name else None
        allowed = {r.strip().lower() for r in allowed if isinstance(r, str)} if isinstance(allowed, list) else set()
        if not all(_merge_repo_ok(r, allowed) for r in repos):
            return f"без чужого репозитория (-R): только из [merge_repos] своего направления. {advice}"
        if not numbers:
            return f"с -R PR указывай номером. {advice}"
    return gate_problem(event, policy, repo_name, cmd_repos, numbers, auto, heads, advice, protect)
