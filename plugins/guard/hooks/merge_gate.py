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
   "tool_use_id","cmd"}, у accept (и у reject с полями) — ещё "checklist":{"opened","ran","unchecked"}, у обоих — "models":[…] или
   "models_note" (metis-0176). Подделать запись роль не может: ~/.local/state/pantheon закрыт ролям песочницей и
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
   файлы из pulls/N/files с previous_filename; PR, задевающий ядро, проходит только со строкой
   `<время> merge-approve <owner/repo>#<N> <sha>` для того же репозитория, PR и SHA в owner-log/merge-approve.log —
   её пишет тик после Touch ID владельца (metis-0285, `pantheon merge`), не старше суток. В защитах accept засчитывается, только если его ran начинается с
   «модель: claude-opus» (metis-0176): accept другой модели — как будто его нет, reject любой модели в силе.
   Незаменённый шаблон «<ID>» в ran — отказ ещё до записи. Модель сверяется и с транскриптом argus: record пишет в
   accept и reject поле "models" — значения message.model его assistant-записей; в защитах accept засчитывается,
   только если все они claude-opus и среди них модель из ran. Транскрипта нет — поле "models_note", судим по ran.
   Перенос (metis-0384, carried/same_change): записи tests и вердикты argus с прошлого head этого PR засчитываются на
   новом, если разница — только поле version в plugins/*/.claude-plugin/plugin.json и подтянутая база PR (baseRefOid):
   дерево нового head = git merge-tree прошлого head с базой, plugin.json сверяется по полям без version. Только вне
   ядра: PR задевает CORE_DIR или CORE_FILES — не переносится ничего (решение владельца 24.10). Перенос — по цепочке
   от последнего head с вердиктом: кандидат переходит, если до нового head или до уже перенесённого кандидата — только
   номер версии и подтянутая база; только по прямой линии первых родителей, вторые родители — только подтянутая база,
   без ветвлений внутри PR (решение владельца 24.10), иначе не переносится ничего.
   Прошлых head с вердиктами больше CARRY_MAX — не переносится ничего. Иначе — не
   переносятся, причина в отказе. talos не переносится; reject переносится, как и accept.
   Номер версии (metis-0384, version_problem) — при каждом слиянии через шлюз, с переносом и без, по репозиторию PR,
   а не по git папки сливающего: файлы PR — gh api pulls/N/files, plugin.json на head и на живой вершине ветки базы
   (baseRef.target, а не снимок baseRefOid) — gh api graphql.
   У каждого плагина с правками (любой файл plugins/<имя>/) version на head больше, чем на базе PR, кортежем чисел.
   Правок plugins/ нет (репозиторий не agent-kit), gh не ответил или нет доступа — проверка пропускается, причина —
   в stderr хука. pantheon merge (PR ядра) номер версии пока не сверяет — metis-0396.
   Последним во всех режимах — проверки GitHub (metis-0297), один gh pr view на Д3 и проверки: PR на этом SHA, rollup зелёный;
   красная или идущая проверка, нет ответа gh — отказ; проверок нет — пропуск, только если .github/workflows нет ни на
   head, ни на base PR.
Модель argus guard берёт из его транскрипта, а не только со слов ran (metis-0176): Claude Code не передаёт путь к
транскрипту субагента в PreToolUse/PostToolUse (agent_transcript_path — только в SubagentStop), он выводится из входа
хука — transcript_path, session_id, agent_id — по раскладке Claude Code. Это защита от ошибки шаблона и от запуска
или подмены модели (запасная модель после отметки), а не от подделки транскрипта.
Чего guard не проверяет: правдивость строки в сводке и перечня argus и то, что выбранная команда тестов — настоящие
тесты: пустую программу (true, echo…, python3 -c pass, sh -c '') он ловит по короткому списку, а придуманную
пустышку вроде `python3 -c "import os"` — нет (защита от ошибки, не от обхода).
"""

import ast
import glob
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime

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
                 "plugins/pantheon/lib/window_rules.py и .claude-plugin/marketplace.json), ждёт слияния владельцем (Д3): "
                 "заявка `pantheon merge request N -R <owner/repo>`, сливает плановый проход после Touch ID владельца.")
MERGE_OWNER = "Слияние делает владелец."
MERGE_AMBIGUOUS = "\0два направления"
MERGE_CORE = "ядро защит — PR ждёт слияния владельцем (Д3)"
MERGE_CORE_HIT = MERGE_CORE + ": PR задевает "
# согласие владельца на слияние ядра (metis-0285): строку пишет только тик после Touch ID, в owner-log роли не пишут
APPROVE_FILE = "merge-approve.log"
APPROVE_RE = re.compile(r"(\S+) merge-approve ([a-z0-9_.-]+/[a-z0-9_.-]+)#([1-9][0-9]{0,8}) ([0-9a-f]{40})")
# срок строки согласия: старше суток или из будущего (дальше пяти минут) — не в силе; время без пояса — не в силе
APPROVE_TTL = 24 * 3600
APPROVE_SKEW = 300
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
RAN_MODEL = re.compile(r"\s*модель:\s*(claude-[a-z0-9.-]*[a-z0-9])", re.I)  # ID модели из --ran
SEGMENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")  # session_id и agent_id в пути транскрипта — одним сегментом
NO_TRANSCRIPT = "транскрипта argus нет — модель по --ran"
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
    """Окружение без GIT_*: GIT_DIR подменил бы репозиторий. GIT_NO_REPLACE_OBJECTS: git replace в общей .git не
    подменяет коммит, который сверяет перенос записей (metis-0384)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    return env


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
                                f"{fmt}. Шлюз слияния пускает только «принять», где сказано, что открыто, что запущено и "
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
                "шлюз слияния пишет тесты только для настоящей команды — например, `pantheon review test -- heavy python3 -I "
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
    if rec_kind in ("accept", "reject"):  # модель argus — из данных сессии, а не со слов ran (metis-0176)
        models = agent_models(event)
        if models:
            rec["models"] = models
        else:
            rec["models_note"] = NO_TRANSCRIPT
    append_record(rec)
    return rec_kind


def agent_models(event):
    """Модели сессии argus по её транскрипту (metis-0176): отсортированные значения message.model assistant-записей,
    без «<synthetic>»; [] — моделей в нём нет, None — транскрипта нет или не прочесть. Путь у субагента —
    <папка transcript_path>/<session_id>/subagents/[<подпапка>/]agent-<agent_id>.jsonl (так Claude Code кладёт
    транскрипты субагентов), у главной сессии (agent_id нет) — сам transcript_path."""
    tp, sid, aid = (event.get(k) for k in ("transcript_path", "session_id", "agent_id"))
    if not isinstance(tp, str) or not os.path.isabs(tp):
        return None
    if aid:
        if not (isinstance(aid, str) and isinstance(sid, str) and SEGMENT_ID.fullmatch(aid)
                and SEGMENT_ID.fullmatch(sid)):
            return None
        base, name = os.path.join(os.path.dirname(tp), sid, "subagents"), f"agent-{aid}.jsonl"
        paths = [os.path.join(base, name)] + sorted(glob.glob(os.path.join(glob.escape(base), "*", name)))
    else:
        paths = [tp]
    for path in paths:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            continue
        models = set()
        with os.fdopen(fd, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"assistant"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                msg = entry.get("message") if isinstance(entry, dict) and entry.get("type") == "assistant" else None
                model = msg.get("model") if isinstance(msg, dict) else None
                if isinstance(model, str) and model.strip() and model != "<synthetic>":
                    models.add(model.strip().lower())
        return sorted(models)
    return None


def opus_problem(rec):
    """Почему «принять» в защитах не засчитан (metis-0176), или None — засчитан: ran начинается с «модель:
    claude-opus», а если в записи есть модели из транскрипта — все они claude-opus и среди них модель из ran (тот же
    ID или он с датой: claude-opus-4-1 и claude-opus-4-1-20250805)."""
    ran = rec["checklist"]["ran"]
    if not OPUS_RAN.match(ran):
        return "по --ran"
    if "models" not in rec:
        return None  # транскрипта не было (models_note) или запись до metis-0176 — судим по ran
    seen = rec["models"]
    if not isinstance(seen, list) or not seen or not all(isinstance(m, str) for m in seen):
        return "модели транскрипта не разобрать"
    if not all(m.startswith("claude-opus") for m in seen):
        return f"по транскрипту argus — {', '.join(seen)}"
    said = RAN_MODEL.match(ran)
    said = said.group(1).lower() if said else ""
    if not any(re.fullmatch(re.escape(said) + r"(-\d{8})?", m) for m in seen):
        return f"в --ran {said or '?'}, а по транскрипту argus — {', '.join(seen)}"
    return None


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


PR_VIEW_FIELDS = "headRefOid,baseRefOid,changedFiles,statusCheckRollup"


def _pr_view(repo, pr):
    """Один gh pr view на шлюз — и для Д3, и для проверок GitHub (таймаут хука 10 с): словарь или None (сбой)."""
    got = _gh_json(["pr", "view", str(pr), "-R", repo, "--json", PR_VIEW_FIELDS])
    data = got[0] if isinstance(got, list) and len(got) == 1 else None
    return data if isinstance(data, dict) else None


def _pr_files(repo, pr, sha, data):
    """Файлы PR из REST pulls/N/files (там есть status и previous_filename: переименование не прячет старый путь):
    (пути, None) или (None, причина). data — ответ _pr_view. Список неполон или PR на другом коммите — причина."""
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
        return None, FILES_NONE
    if not isinstance(head, str) or head.lower() != sha:
        return None, f"PR сейчас на другом коммите ({head}), а не на {sha}"
    return paths, None


FILES_NONE = "список файлов PR не получен или неполон"


def _core_hit(paths):
    """Пути ядра среди путей PR (CORE_DIR и CORE_FILES, casefold)."""
    core = {c.casefold() for c in CORE_FILES}
    return [p for p in paths if _is_core(p, core)]


def _core_problem(repo, pr, sha, data, files=None):
    """Д3: PR защит, который задевает ядро, ждёт слияния владельцем. data — ответ _pr_view, files — готовый ответ
    _pr_files (иначе он зовётся здесь). Список файлов неполон, PR на другом коммите — тоже отказ."""
    paths, why = files if files is not None else _pr_files(repo, pr, sha, data)
    if why:
        return f"{MERGE_CORE}: {why}" + (", ядро не проверить" if why == FILES_NONE else "")
    hit = _core_hit(paths)
    if hit:
        return f"{MERGE_CORE_HIT}{', '.join(hit)}"
    return None


# проверки GitHub на head PR (metis-0297): разбор rollup — как ci_state в pantheon/lib/merge.py (PR #79, metis-0285)
CI_OK = {"SUCCESS", "NEUTRAL", "SKIPPED"}
CI_WAIT = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", ""}
CI_NONE = "проверки GitHub не получены"


def _ci_rollup(rollup):
    """(ok|wait|fail|empty, текст) по statusCheckRollup: CheckRun — по status и conclusion, StatusContext — по state."""
    if not isinstance(rollup, list):
        return "fail", CI_NONE
    if not rollup:
        return "empty", ""
    waiting = []
    for c in rollup:
        if not isinstance(c, dict):
            return "fail", f"{CI_NONE}: проверка не разобрана"
        name = str(c.get("name") or c.get("context") or "?")[:60]
        if "conclusion" in c or "status" in c and "state" not in c:   # CheckRun
            status, concl = str(c.get("status") or "").upper(), str(c.get("conclusion") or "").upper()
            if status != "COMPLETED":
                waiting.append(name)
            elif concl not in CI_OK:
                return "fail", f"проверка GitHub {name} красная: {concl or 'нет итога'}"
        else:                                                            # StatusContext
            st = str(c.get("state") or "").upper()
            if st in CI_WAIT:
                waiting.append(name)
            elif st not in CI_OK:
                return "fail", f"проверка GitHub {name} красная: {st}"
    if waiting:
        return "wait", "проверки GitHub ещё идут: " + ", ".join(waiting)
    return "ok", ""


def _has_workflows(repo, sha):
    """Есть ли на коммите папка .github/workflows: True, False (ответ 404) или None (сбой gh или сети)."""
    env = {k: v for k, v in os.environ.items() if k not in ("GH_REPO", "GH_HOST")}
    try:
        r = subprocess.run(["gh", "api", f"repos/{repo}/contents/.github/workflows?ref={sha}"], capture_output=True,
                           text=True, timeout=GH_TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode == 0:
        try:
            return bool(json.loads(r.stdout))
        except ValueError:
            return None
    return False if "(HTTP 404)" in (r.stderr or "") else None


def _ci_problem(repo, pr, sha, data):
    """Проверки GitHub на head PR зелёные — иначе текст отказа (metis-0297: 19.10 дважды ушёл PR с красной
    check-traces). data — ответ _pr_view. PR на другом коммите, красная или идущая проверка — отказ. Проверок нет:
    пропуск, только если .github/workflows нет ни на head, ни на base PR (ответ 404 на оба): PR, который удаляет или
    переименовывает папку workflows, проверок не получает, а на base она есть (ревью argus 0297b). Сбой любого
    запроса — отказ; base спрашивается, только когда rollup пуст и на head папки нет."""
    head = data.get("headRefOid")
    if not isinstance(head, str) or head.lower() != sha:
        return f"PR сейчас на другом коммите ({head}), а не на {sha} — проверки GitHub сверяются на проверенном SHA"
    state, text = _ci_rollup(data.get("statusCheckRollup"))
    if state == "fail":
        return f"{text} на {repo}#{pr}@{sha[:12]} — почини и сделай новый коммит с новыми записями"
    if state == "wait":
        return f"{text} на {repo}#{pr}@{sha[:12]} — дождись итога и повтори слияние"
    if state == "empty":
        base = data.get("baseRefOid")
        if not isinstance(base, str) or not SHA_RE.fullmatch(base.lower()):
            return f"{CI_NONE}: проверок на {repo}#{pr} нет, а коммит base PR ({base}) не получен"
        for ref, where in ((sha, "head PR"), (base.lower(), "base PR")):
            wf = _has_workflows(repo, ref)
            if wf is None:
                return (f"{CI_NONE}: проверок на {repo}#{pr} нет, а gh api не ответил, есть ли .github/workflows "
                        f"на {where} ({ref[:12]})")
            if wf:
                return (f"проверки GitHub ещё не встали на {repo}#{pr}@{sha[:12]}: на {where} ({ref[:12]}) "
                        ".github/workflows есть, а проверок нет — дождись и повтори слияние; PR, который убирает "
                        "workflows, сливает владелец")
    return None


def approve_file():
    return os.path.join(G.STATE_DIR, "owner-log", APPROVE_FILE)


def _approve_time(token):
    """Время строки согласия (ISO 8601 с поясом, как пишет тик) → секунды эпохи; не разобрать или без пояса — None."""
    try:
        t = datetime.fromisoformat(token)
    except ValueError:
        return None
    return t.timestamp() if t.tzinfo is not None else None


def owner_approved(repo, pr, sha, now=None):
    """Строка `<время> merge-approve <owner/repo>#<N> <sha>` в owner-log/merge-approve.log (metis-0285): её пишет
    только тик после Touch ID владельца; роли в owner-log не пишут (песочница и pantheon-acl). Сверка — ровно этот
    репозиторий, этот PR и этот SHA, и строка не старше APPROVE_TTL (не из будущего дальше APPROVE_SKEW). Симлинк
    папки или файла, сбой чтения — нет согласия. now — только для тестов."""
    t_now = time.time() if now is None else now
    d = os.path.join(G.STATE_DIR, "owner-log")
    try:
        if os.path.islink(d):
            return False
        fd = os.open(approve_file(), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return False
    for ln in lines:
        m = APPROVE_RE.fullmatch(ln.strip())
        if m and m.group(2).lower() == repo.lower() and int(m.group(3)) == int(pr) and m.group(4) == sha.lower():
            t = _approve_time(m.group(1))
            if t is not None and -APPROVE_SKEW <= t_now - t <= APPROVE_TTL:
                return True
    return False


def _reviewer(rec):
    """Рецензент записи — пара (session_id, agent_id): два argus одной сессии — разные рецензенты (metis-0158)."""
    return rec["by"].get("session_id") or "", rec["by"].get("agent_id") or ""


def _who(rec):
    """Чей вердикт — для текста отказа: роль, первые 8 знаков agent_id и session_id, время записи."""
    sid, aid = _reviewer(rec)
    return (f"{rec['by'].get('agent_type') or '?'} agent {aid[:8] or '—'}, сессия {sid[:8] or '—'}, "
            f"запись {rec.get('time') if isinstance(rec.get('time'), str) else '?'}")


# --- перенос записей на новый head PR (metis-0384) ----------------------------------------------------------------
# Номер версии плагина поднимает выпуск при слиянии (plugins/pantheon/scripts/release.py), а не каждый PR: иначе
# соседние PR конфликтуют в plugin.json, и после каждого слияния у них новый head и новый круг ревью. Записи tests и
# вердикты argus (accept и reject) с прошлого head PR действуют и на новом, если новый head — прошлый плюс только
# номер версии в plugins/<плагин>/.claude-plugin/plugin.json и подтянутая база PR без своих правок, и PR не задевает
# ядро. Сверка переноса — по объектам git папки сливающего (SHA сверяет сам git, подмены git replace выключены —
# _git_env), база — baseRefOid из gh pr view, а не ветка из локальных ссылок. Отдельно, при каждом слиянии через шлюз
# (version_problem): у каждого плагина с правками в PR version на head больше, чем на базе PR (иначе соседний PR,
# слитый раньше с тем же номером, оставил бы на main код без нового номера — claude plugin update его не поставит).
# Её сверка — по репозиторию PR через gh, а не по git папки: из папки agent-kit сливают и PR соседних репозиториев.
# Запись talos не переносится: подтянутая база меняет живое приложение.
VERSION_FILE = re.compile(r"plugins/[^/]+/\.claude-plugin/plugin\.json")
CARRY_MAX = 10  # сколько прошлых head PR сверять (на каждый — десяток вызовов git); больше — не переносится ничего
CARRY_LINKS = 30  # сколько коммитов без вердикта сверять звеньями цепочки переноса; больше — не переносится ничего
CARRY_CHECKS = 60  # сколько сверок same_change на перенос (хук guard ограничен 10 с); больше — не переносится ничего
_ABSENT = object()
_CONFLICT = object()  # конфликт поля в _merge3: None — обычное значение поля (null в JSON), а не конфликт


def _git_rc(d, *args):
    """(код выхода, вывод) git в папке d; None — git не запустился или не ответил вовремя."""
    try:
        r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, timeout=3, env=_git_env())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return r.returncode, r.stdout


def _json_at(d, rev, path):
    """plugin.json на коммите rev: словарь; {} — файла на коммите нет; None — не JSON-объект или сбой git."""
    out = _git(d, "ls-tree", "-z", rev, "--", path)
    if out is None:
        return None
    entry = out.split("\0")[0]
    if not entry:
        return {}
    meta, _, name = entry.partition("\t")
    meta = meta.split()
    if name != path or len(meta) != 3 or meta[1] != "blob" or not SHA_RE.fullmatch(meta[2]):
        return None
    raw = _git(d, "cat-file", "blob", meta[2])
    try:
        data = json.loads(raw) if raw is not None else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _merge3(base, ours, theirs):
    """Слияние трёх версий plugin.json по полям, без поля version; None — одно поле изменено с обеих сторон по-разному."""
    out = {}
    for k in set(base) | set(ours) | set(theirs):
        if k == "version":
            continue
        b, o, t = base.get(k, _ABSENT), ours.get(k, _ABSENT), theirs.get(k, _ABSENT)
        v = t if o == b else o if t == b or o == t else _CONFLICT
        if v is _CONFLICT:
            return None
        if v is not _ABSENT:
            out[k] = v
    return out


def same_change(d, prev, sha, base):
    """Новый head sha — прошлый head prev плюс только номер версии и подтянутая база PR без своих правок? None — да,
    иначе текст, почему нет. Ожидаемое дерево — слияние prev с mi = merge-base(sha, base), последним подтянутым
    коммитом базы (git merge-tree); от него новый head может отличаться только полем version в VERSION_FILE.
    Само значение version здесь не сверяется: это делает version_problem при каждом слиянии.
    Сторонний merge-драйвер в настройках git папки ниже модели угроз: guard ловит ошибку агента, а не обход."""
    got = _git_rc(d, "merge-base", "--is-ancestor", prev, sha)
    if got is None or got[0] not in (0, 1):
        return "коммитов нет в git этой папки — сделай git fetch"
    if got[0] == 1:
        return "прошлый head не предок нового (история переписана)"
    mi = (_git(d, "merge-base", sha, base) or "").strip()
    b = (_git(d, "merge-base", prev, mi) or "").strip() if SHA_RE.fullmatch(mi) else ""
    if not SHA_RE.fullmatch(b):
        return "база PR не найдена в git этой папки — сделай git fetch"
    tree, conflicts = prev, []
    if b != mi:  # база подтянута: ожидаемое дерево — слияние прошлого head с ней
        got = _git_rc(d, "merge-tree", "--write-tree", "--name-only", "--no-messages", "-z", prev, mi)
        parts = got[1].split("\0") if got is not None and got[0] in (0, 1) else []
        if not parts or not SHA_RE.fullmatch(parts[0]):
            return "git merge-tree не ответил (нужен git 2.38+)"
        tree, conflicts = parts[0], [p for p in parts[1:] if p]
    out = _git(d, "diff-tree", "-r", "--name-only", "--no-renames", "-z", tree, sha)
    if out is None:
        return "git diff-tree не ответил"
    for path in sorted({p for p in out.split("\0") if p} | set(conflicts)):
        if not VERSION_FILE.fullmatch(path):
            return f"новый head меняет {path} — это не только номер версии и подтянутая база"
        new, want = _json_at(d, sha, path), [_json_at(d, r, path) for r in (b, prev, mi)]
        if not new or None in want or not isinstance(new.get("version"), str):
            return f"{path} не разобрать как plugin.json"
        if not want[1] and not want[2]:
            return f"новый head добавляет {path} — это не только номер версии и подтянутая база"
        merged = _merge3(*want)
        if merged is None or {k: v for k, v in new.items() if k != "version"} != merged:
            return f"в {path} изменено не только поле version"
    return None  # номер версии сверяет version_problem в gate_problem — по репозиторию PR, при каждом слиянии шлюзом


def _vkey(v):
    """version → кортеж чисел для сравнения; None — не «числа через точку»."""
    parts = v.split(".")
    return tuple(int(x) for x in parts) if all(re.fullmatch(r"[0-9]+", x) for x in parts) else None


PLUGIN_DIR = re.compile(r"plugins/([^/]+)/")
_BAD = object()  # ответ _gh_blobs: по пути не файл или текст не полностью


def _gh_blobs(repo, pr, sha, paths):
    """Живая вершина ветки базы PR и тексты файлов paths на sha и на ней одним запросом gh api graphql (переменные —
    полями -f/-F, без подстановки в текст запроса): (вершина базы, {(rev, path): текст | None — файла нет | _BAD}).
    База — pullRequest.baseRef.target: туда GitHub и сольёт; baseRefOid — снимок на момент последнего push в PR, и
    сосед, слитый позже с тем же номером, им не виден (argus-117b4). Файлы базы — Commit.file того же target, в том же
    ответе: вершина и тексты из одного снимка. None — сбой gh, нет доступа к репозиторию, PR или ветки базы на GitHub
    нет, коммита sha на GitHub нет (object по несуществующему коммиту — null)."""
    owner, _, name = repo.partition("/")
    decl, fields, bfields = ["$o: String!", "$n: String!", "$pr: Int!", "$hc: String!"], \
        ["hc: object(expression: $hc) { oid }"], []
    args = ["api", "graphql", "-f", f"o={owner}", "-f", f"n={name}", "-F", f"pr={int(pr)}", "-f", f"hc={sha}"]
    blob = "{ ... on Blob { text isTruncated } }"
    for i, path in enumerate(paths):
        decl += [f"$e{i}: String!", f"$p{i}: String!"]
        fields.append(f"f{i}: object(expression: $e{i}) {blob}")
        bfields.append(f"b{i}: file(path: $p{i}) {{ object {blob} }}")
        args += ["-f", f"e{i}={sha}:{path}", "-f", f"p{i}={path}"]
    fields.append(f"pr: pullRequest(number: $pr) {{ baseRef {{ target {{ oid ... on Commit {{ {' '.join(bfields)} }} }} }} }}")
    query = f"query({', '.join(decl)}) {{ repository(owner: $o, name: $n) {{ {' '.join(fields)} }} }}"
    got = _gh_json(args + ["-f", f"query={query}"])
    data = got[0].get("data") if isinstance(got, list) and len(got) == 1 and isinstance(got[0], dict) else None
    data = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(data, dict):
        return None
    obj = data.get("hc")
    if not isinstance(obj, dict) or not isinstance(obj.get("oid"), str) or obj["oid"].lower() != sha:
        return None
    target = data.get("pr")
    for key in ("baseRef", "target"):
        target = target.get(key) if isinstance(target, dict) else None
    base = target.get("oid") if isinstance(target, dict) else None
    if not isinstance(base, str) or not SHA_RE.fullmatch(base.lower()):
        return None
    base = base.lower()

    def text(o):
        return o["text"] if isinstance(o, dict) and isinstance(o.get("text"), str) and o.get("isTruncated") is False \
            else _BAD
    out = {}
    for i, path in enumerate(paths):
        obj = data.get(f"f{i}", _BAD)
        out[(sha, path)] = None if obj is None else text(obj)
        entry = target.get(f"b{i}", _BAD)
        out[(base, path)] = None if entry is None else text(entry.get("object")) if isinstance(entry, dict) else _BAD
    return base, out


def version_problem(repo, pr, sha, files, blobs=None):
    """Номер версии плагинов с правками в PR — по репозиторию PR (gh), а не по git папки сливающего: (отказ, пропуск).
    Отказ — текст или None; пропуск — почему номер не сверен (без отказа), или None. files — ответ _pr_files
    (pulls/N/files: ровно то, что слияние приносит в базу, с previous_filename). Плагины с правками — любой путь
    plugins/<имя>/ из files; у каждого, чей plugin.json есть на sha, version на sha больше, чем на живой вершине ветки
    базы PR (baseRef.target из того же запроса _gh_blobs, а не снимок baseRefOid — argus-117b4), кортежем чисел (0.11.10 > 0.11.9); плагина нет на базе — номер ставит сам PR (release.py так же), нет на sha —
    плагин удалён. Сверка не ограничена plugin.json из разницы: выпущенный head, подтянувший main с тем же номером
    без повтора release.py, оставил бы на main свой код со старым номером — claude plugin update его не поставит.
    Пропуск (решение владельца 24.10, metis-0384): в PR нет plugins/<имя>/ (репозиторий не agent-kit), список файлов
    или база PR от gh не получены, gh api graphql не ответил (нет доступа, коммита нет на GitHub). blobs — для тестов."""
    paths, why = files
    if why:
        return None, f"{why} — номер версии плагинов не сверен"
    names = sorted({m.group(1) for m in (PLUGIN_DIR.match(p) for p in paths) if m})
    if not names:
        return None, "в PR нет правок plugins/<имя>/ (репозиторий не agent-kit) — номер версии не сверяется"
    manifests = [f"plugins/{name}/.claude-plugin/plugin.json" for name in names]
    got = (blobs or _gh_blobs)(repo, pr, sha, manifests)
    if got is None:
        return None, (f"gh api graphql по {repo} не ответил или не дал вершину ветки базы PR — номер версии плагинов "
                      "не сверен")
    base, texts = got
    for name, path in zip(names, manifests):
        raw_new, raw_old = texts.get((sha, path), _BAD), texts.get((base, path), _BAD)
        if raw_new is None or (raw_old is None and raw_new is not _BAD):
            continue  # плагина нет на head (удалён, или в plugins/<имя>/ нет plugin.json) или нет на базе (новый)
        new, old = (_json_obj(x) for x in (raw_new, raw_old))
        if new is None or old is None or not isinstance(new.get("version"), str) \
                or not isinstance(old.get("version"), str):
            return f"{path} не разобрать как plugin.json (на новом head или на базе PR)", None
        nv, bv = _vkey(new["version"]), _vkey(old["version"])
        if nv is None or bv is None:
            return f"в {path} version не разобрать ({new['version']!r}, на базе PR {old['version']!r})", None
        if nv <= bv:
            return (f"в {path} version {new['version']} не больше, чем на базе PR ({old['version']}), а в PR есть "
                    f"правки плагина {name}: соседний PR слит с тем же номером — повтори release.py"), None
    return None, None


def _json_obj(raw):
    """Текст plugin.json → словарь; None — не JSON-объект или _BAD."""
    if not isinstance(raw, str):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def carried(d, repo, pr, sha, records, pr_view, pr_files):
    """Прошлые head PR, чьи записи переходят на sha, и причины отказа для остальных. Кандидаты — SHA с вердиктами argus
    на этот PR; pr_view() и pr_files() — ответы gh pr view и _pr_files, зовутся, только если кандидаты есть.
    Только вне ядра (решение владельца 24.10): PR задевает CORE_DIR или CORE_FILES — не переносится ничего.
    Перенос — от последнего head с вердиктом: кандидаты-предки sha по числу коммитов, от нового к старому; кандидат
    переходит, если от него до sha (same_change) или до любого перенесённого звена — только номер версии и
    подтянутая база. Так «вернуть» с R не теряется, когда R → A и A → sha чистые, а R → sha — нет (merge-tree по
    переименованному в базе файлу, проба p6 argus-117b3). Звенья цепочки — и коммиты без вердикта от самого
    старого кандидата до sha (два подтягивания базы без вердикта между ними, argus-117b7); звено переходит, если до
    sha или до любого уже перенесённого звена — только номер версии и подтянутая база (argus-122b9).
    Только по прямой линии (решение владельца 24.10, consent metis-0427; _bent): от самого старого кандидата до sha —
    цепочка первых родителей, вторые родители — только подтянутая база, ветвлений внутри PR нет, все кандидаты на
    линии. Иначе — подтягивание «со стороны main» (argus-122b), побочная ветка внутри PR (argus-122b9) — не
    переносится ничего: нужен свежий argus, ложный отказ допустим, пропуск — нет. Коммитов на линии больше
    CARRY_LINKS (считаются все, до обрезки окна), сверок больше CARRY_CHECKS или git их не прочитал — тоже ничего."""
    prevs = []
    for r in records:
        if r["kind"] in ("accept", "reject") and r["by"].get("agent_type") == "argus" and r["pr"] == pr \
                and r["sha"] != sha and repo in [x.lower() for x in r["repo"]] and r["sha"] not in prevs:
            prevs.append(r["sha"])
    if not prevs or not d:
        return set(), []
    if len(prevs) > CARRY_MAX:  # обрезка потеряла бы «вернуть» со старого head того же кода — не переносится ничего
        return set(), [f"прошлых head с вердиктами argus больше {CARRY_MAX} — записи не переносятся, нужны записи "
                       "на этом head"]
    view = pr_view()
    base = view.get("baseRefOid") if isinstance(view, dict) else None
    if not isinstance(base, str) or not SHA_RE.fullmatch(base.lower()):
        return set(), ["база PR (baseRefOid) от gh не получена"]
    paths, why = pr_files()
    if why:
        return set(), [f"{why} — ядро не проверить, записи не переносятся"]
    hit = _core_hit(paths)
    if hit:
        return set(), [f"PR задевает ядро ({', '.join(hit)}) — на ядре записи не переносятся, нужны записи на этом "
                       "head"]
    whys, order = [], []
    for p in prevs:
        got = _git_rc(d, "merge-base", "--is-ancestor", p, sha)
        count = _git(d, "rev-list", "--count", p) if got is not None and got[0] == 0 else None
        if got is not None and got[0] == 1:
            whys.append(f"{p[:12]} — прошлый head не предок нового (история переписана)")
        elif count is None or not count.strip().isdigit():
            whys.append(f"{p[:12]} — коммитов нет в git этой папки — сделай git fetch")
        else:
            order.append((-int(count.strip()), p))
    if not order:
        return set(), whys
    # звенья цепочки — и коммиты без вердикта от самого старого кандидата до sha (head после подтянутой базы, номер
    # версии): иначе «вернуть» с R теряется, когда R → N2 и N2 → N3 чистые, а R → N3 — нет и на N2 вердикта нет
    # (argus-117b7). Только прямая линия (решение владельца 24.10, consent metis-0427): от самого старого кандидата
    # до sha — цепочка первых родителей, вторые родители — только подтянутая база (предки baseRefOid), в PR нет
    # ветвлений, все кандидаты на этой линии; иначе не переносится ничего. Подтягивание «со стороны main» (argus-122b,
    # блокер 1) и побочная ветка внутри PR (argus-122b9) — не прямая линия. Окно — с запасом на sha и все кандидаты:
    # звеньев в нём больше CARRY_LINKS ровно тогда, когда их больше всего (argus-122b, блокер 2)
    cands, oldest = {p for _n, p in order}, max(order)[1]
    cap = f"--max-count={CARRY_LINKS + len(cands) + 2}"
    out = _git(d, "rev-list", "--first-parent", "--parents", cap, f"{oldest}..{sha}")
    rows = [r.split() for r in (out or "").splitlines() if r.strip()]
    chain = [r[0] for r in rows]
    links = [x for x in chain if x != sha and x not in cands]
    if out is None or len(links) > CARRY_LINKS:
        return set(), whys + [("git rev-list не ответил" if out is None else
                               f"между прошлым head и новым больше {CARRY_LINKS} коммитов") +
                              " — записи не переносятся, нужны записи на этом head"]
    bent = _bent(d, rows, oldest, sha, cands, base.lower(), cap)
    if bent:
        return set(), whys + [f"история от {oldest[:12]} до нового head — не прямая линия первых родителей ({bent}) "
                              "— записи не переносятся, нужны записи на этом head"]
    # от нового head к старому по линии: звено переходит, если до sha или до любого уже перенесённого звена — только
    # номер версии и подтянутая база (а не только до последнего перенесённого: побочное звено, сведённое с sha, не
    # заслоняет более новое, с которым сводится кандидат, argus-122b9). Сверок больше CARRY_CHECKS — не переносится
    # ничего: хук guard ограничен 10 с
    same, passed, checks = set(), [], 0
    for p in chain[1:] + [oldest]:
        why = None
        for q in [sha] + passed[::-1]:  # sha, затем перенесённые звенья от ближнего к дальнему
            if checks >= CARRY_CHECKS:
                return set(), whys + [f"сверок цепочки переноса больше {CARRY_CHECKS} — записи не переносятся, "
                                      "нужны записи на этом head"]
            checks += 1
            got = same_change(d, p, q, base.lower())
            if got is None:
                why = None
                break
            why = why or got  # причина отказа — по сверке с sha
        if not why:
            passed.append(p)
            if p in cands:
                same.add(p)
        elif p in cands:
            whys.append(f"{p[:12]} — {why}")
    return same, whys


def _bent(d, rows, oldest, sha, cands, base, cap):
    """Почему история от oldest до sha — не прямая линия (carried, решение владельца 24.10); None — прямая. rows —
    rev-list --first-parent --parents oldest..sha: строки «коммит родитель1 родитель2 …» от sha вниз. Прямая — первые
    родители ведут от sha ровно к oldest; вторые родители — предки базы PR (подтянутая база); все потомки oldest и
    предки sha (--ancestry-path) — на этой линии, ветвлений внутри PR нет; все кандидаты — на ней."""
    if not rows or rows[0][0] != sha or any(len(r) < 2 or not all(SHA_RE.fullmatch(x) for x in r) for r in rows):
        return "первые родители не прочитаны"
    for r, nxt in zip(rows, [x[0] for x in rows[1:]] + [oldest]):
        if r[1] != nxt:
            return f"первый родитель {r[0][:12]} — не {nxt[:12]}"
    for r in rows:
        for x in r[2:]:
            got = _git_rc(d, "merge-base", "--is-ancestor", x, base)
            if got is None or got[0] != 0:
                return f"второй родитель {r[0][:12]} — {x[:12]}, не подтянутая база PR"
    line = {r[0] for r in rows}
    out = _git(d, "rev-list", "--ancestry-path", cap, f"{oldest}..{sha}")
    if out is None or set(out.split()) != line:
        return "в PR есть ветвление: не все коммиты от прошлого head до нового — на линии первых родителей"
    off = sorted(cands - line - {oldest})
    if off:
        return f"{off[0][:12]} — прошлый head с вердиктом не на линии первых родителей"
    return None


def gate_problem(event, policy, repo_name, cmd_repos, numbers, auto, heads, advice, protect, cwd=""):
    """Запор (P1-4): то, что проверено, — ровно то, что сливается (или отличается от проверенного только номером
    версии и подтянутой базой — carried, metis-0384). Текст отказа или None."""
    if auto:
        return f"без --auto: сливается сейчас ровно проверенный PR, а не позже сам. {advice}"
    if len(numbers) != 1:
        return f"ровно один номер PR: шлюз слияния сверяет записи на этот PR. {advice}"
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
    view_box = []

    def pr_view():  # один gh pr view на шлюз: и для базы PR (перенос записей), и для Д3 и проверок GitHub
        if not view_box:
            view_box.append(_pr_view(repo, pr))
        return view_box[0]

    files_box = []

    def pr_files():  # один список файлов PR на шлюз: для переноса (ядро), номера версии и Д3
        if not files_box:
            view = pr_view()
            files_box.append(_pr_files(repo, pr, sha, view) if view is not None
                             else (None, f"gh pr view {pr} -R {repo} не ответил"))
        return files_box[0]

    same, carry_why = carried(cwd, repo, pr, sha, records, pr_view, pr_files)
    shas = {sha} | same  # head и прошлые head PR, чьи записи на него переходят (metis-0384)
    carry_note = (f" Записи с прошлых коммитов PR не перенесены (перенос — только когда новый коммит добавляет "
                  f"номер версии или подтянутую базу без своих правок): {'; '.join(carry_why)}."
                  if carry_why and not same else "")
    if not any(r["kind"] == "tests" and r["sha"] in shas and repo in [x.lower() for x in r["repo"]] for r in records):
        return (f"нет записи тестов на {repo}@{sha[:12]}: в чистом дереве на этом коммите запусти "
                f"`pantheon review test -- <команда тестов>` (запишет хук guard). Тесты долгие: запускай "
                f"`pantheon review test` не в фоне, с timeout до 600000 мс (у Bash по умолчанию 120 с).{carry_note} "
                f"{advice}")

    def mine(r, kinds, who, at=shas):
        return (r["kind"] in kinds and r["by"].get("agent_type") == who and r["pr"] == pr and r["sha"] in at
                and repo in [x.lower() for x in r["repo"]])

    verdicts = [r for r in records if mine(r, ("accept", "reject"), "argus")]
    # защиты (metis-0176): «принять» не на Opus не засчитывается — как будто его нет; «вернуть» любой модели в силе,
    # «принять» без перечня остаётся, чтобы отказ Б6 ниже сказал о перечне
    weak = [r for r in verdicts if protect and r["kind"] == "accept" and checklist_ok(r) and opus_problem(r)]
    verdicts = [r for r in verdicts if not any(r is w for w in weak)]
    if not verdicts and weak:
        unfilled = any(UNFILLED_ID.search(r["checklist"]["ran"]) for r in weak)
        return (f"«принять» на {repo}#{pr}@{sha[:12]} от {'; '.join(_who(r) + ' (' + opus_problem(r) + ')' for r in weak)}"
                " — не на Opus: в "
                "репозитории защит шлюз засчитывает только проверку argus на модели claude-opus (--ran начинается с "
                "«модель: claude-opus»). Проверку повторяет argus на Opus и записывает `pantheon review accept "
                f"{repo} {pr} {sha} --ran \"модель: claude-opus-…, что запустил\" …`."
                + (f" Кроме того, {UNFILLED_ID_HINT}." if unfilled else "") + f" {advice}")
    if not verdicts:
        return (f"нет «принять» от argus на {repo}#{pr}@{sha[:12]}: позови argus, он проверит и запишет "
                f"`pantheon review accept {repo} {pr} {sha} {CHECKLIST_HINT}`.{carry_note} {advice}")

    def lifts(x, y):  # «принять» на коммите y снимает «вернуть» того же рецензента на x: y — тот же коммит или новее
        if x == y or y == sha:
            return True
        got = _git_rc(cwd, "merge-base", "--is-ancestor", x, y) if cwd else None
        return got is not None and got[0] == 0

    # рецензент (session_id, agent_id) → его вердикт в силе; порядок — по первой записи рецензента. «Вернуть» в силе,
    # пока после него нет «принять» того же рецензента на том же коммите или новее: «принять» на прошлом head не
    # снимает «вернуть» на новом (argus-117b7, K2). Иначе в силе его последнее «принять»
    latest, held = {}, {}
    for i, r in enumerate(verdicts):
        latest[_reviewer(r)] = r
        if r["kind"] != "accept" and not any(y["kind"] == "accept" and _reviewer(y) == _reviewer(r)
                                             and lifts(r["sha"], y["sha"]) for y in verdicts[i + 1:]):
            held[_reviewer(r)] = r
    latest.update(held)
    rejects = [r for r in latest.values() if r["kind"] != "accept"]
    if rejects:
        return (f"«вернуть» (reject) на {repo}#{pr}@{sha[:12]} от {'; '.join(_who(r) for r in rejects)}: его снимает "
                "только «принять» того же рецензента, записанное после него на том же коммите или новее (верни ему "
                "исправление), или новый коммит "
                f"с правками (номер версии и подтянутая база «вернуть» не снимают) и новыми записями тестов и argus — `pantheon review accept {repo} {pr} <новый SHA>`. «Принять» "
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
        if not any(mine(r, ("talos",), "talos", {sha}) for r in records):  # talos не переносится
            return (f"продукт — нет проверки talos на {repo}#{pr}@{sha[:12]}: позови talos, он проверит живое "
                    f"приложение и запишет `pantheon review talos {repo} {pr} {sha}`. {advice}")
        if not _alert_ok(repo, pr):
            return (f"продукт — нет строки «что ушло» в ~/ai/pantheon/alerts.md со ссылкой {repo}#{pr} и словом "
                    f"«откат»: `pantheon alert \"{repo}#{pr}: что ушло; откат: <команда>\"`. {advice}")
    view = pr_view()
    if view is None:
        return (f"{CI_NONE}: gh pr view {pr} -R {repo} не ответил — без него не сверить ни проверки GitHub, ни "
                f"файлы PR (ядро), повтори позже. {advice}")
    if protect:
        why = _core_problem(repo, pr, sha, view, pr_files())
        # Д3 через Touch ID (metis-0285): палец владельца на этот PR и этот SHA — строка тика в owner-log. Пускает
        # только задетое ядро; сбой gh, неполный список файлов и другой head — отказ и со строкой
        if why and not (why.startswith(MERGE_CORE_HIT) and owner_approved(repo, pr, sha)):
            return f"{why}. {MERGE_PROTECT}"
    # номер версии — при каждом слиянии через шлюз, по репозиторию PR из gh (а не по git папки сливающего); pantheon
    # merge (PR ядра) его пока не сверяет — metis-0396
    why, skipped = version_problem(repo, pr, sha, pr_files())
    if why:
        return f"{why}. {advice}"
    if skipped:
        sys.stderr.write(f"guard: шлюз слияния {repo}#{pr}: {skipped}\n")
    why = _ci_problem(repo, pr, sha, view)
    if why:
        return f"{why}. {advice}"
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
    if re.search(r"\bGH_[A-Z0-9_]+", cmd):  # GH_REPO, GH_HOST, GH_CONFIG_DIR, GH_TOKEN — уводят gh от проверенного
        return "без переменных GH_* в команде (GH_REPO, GH_HOST и другие). " + (MERGE_PROTECT if is_metis else MERGE_INTERNAL)
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
    return gate_problem(event, policy, repo_name, cmd_repos, numbers, auto, heads, advice, protect, cwd)
