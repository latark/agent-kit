"""Запор слияния guard (P1-4, Д2, Д3, guard 0.5.4) — часть ядра защит: ядро — весь plugins/guard/**, общие роли
plugins/pantheon/roles/**, CI .github/** и правила окон plugins/pantheon/lib/window_rules.py, casefold; файлы из
pulls/N/files с previous_filename. PR, задевающий ядро, агенты не сливают: он ждёт слияния владельцем (Д3).
PR защит, который правит version в plugins/*/.claude-plugin/plugin.json или трогает .claude-plugin/releases.json, не
проходит совсем (metis-0512, _version_problem): номер поднимает workflow release на main после слияния.

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
   "models_note" (metis-0176), у пустого "models": [] — оба (metis-0413). Подделать запись роль не может:
   ~/.local/state/pantheon закрыт ролям песочницей и pantheon-acl, а вид записи хук берёт из agent_type события, а не
   из текста команды. Битые строки при чтении пропускаются: битая запись может только не дать разрешения.
2. merge_problem — правило gh pr merge: кто сливает (координатор или его лид), чьё направление, защиты, затем запор:
   один номер PR, без --auto и --admin, ровно один --match-head-commit <SHA> (его сверяет GitHub), все репозитории
   команды — из [merge_repos] направления, запись tests на (repo, SHA), вердикты argus на (repo, PR, SHA): рецензент —
   пара (session_id, agent_id), у каждого считается его последний вердикт; пускает, только если рецензент есть,
   последний вердикт каждого — accept с полным перечнем проверенного (Б6) и ни один рецензент не тот, кто сливает.
   reject привязан к PR, на каком бы head он ни был (metis-0415, решение владельца 24.10): его снимает только
   записанное после него accept с перечнем (_lifts): 1) того же рецензента на том же head; 2) на сливаемый SHA при
   reject на другом head — того же рецензента или другого argus, если коды reject и сливаемого SHA посчитаны и
   различаются (0415b: accept другого argus на код, равный коду reject, reject не снимает; код не посчитан — тоже);
   3) на третьем head с другим кодом от той же merge-base, если код сливаемого SHA — не код reject (_held; metis-0158:
   два argus на одном head — accept и reject в любом порядке дают отказ). Перенос accept: accept с перечнем на
   прошлом head PR засчитывается на новом SHA, если собственный дифф PR (merge-base с base PR..head) тот же —
   отпечаток _fingerprint по содержимому файлов (решение владельца 25.10 23:05): `git diff --raw -z --no-abbrev
   --no-renames --no-relative --ignore-submodules=none` без pathspec — режим, sha блоба или gitlink, статус и путь
   каждого файла; фильтр plugin.json и сортировка по пути — в Python, plugin.json плагинов сверяется по канону без
   version с учётом режима. Настройки git (diff.*, core.abbrev, submodule.*.ignore, атрибуты, GIT_* окружения) на
   отпечаток не влияют: окружение без GIT_*, явный --git-dir. Вывод --raw разбирается строго (формат, \0 в конце,
   путь один раз), иначе отпечатка нет. Цена (решение владельца 25.10): main правил файл, который правит и PR, —
   переноса нет, нужен argus. Засчитывается — и прямо на своём head, и переносом — только accept, записанное позже
   каждого reject PR, кроме reject, снятого accept с перечнем того же рецензента на том же head (_floor, _carried,
   #134 п.2, argus-b r2): иначе откат к коду, принятому до reject (force-push на старый head после снятия reject
   правилом 3), прошёл бы по старому accept; отказ называет такое accept и reject. Сверяются CARRY_HEADS последних head за
   CARRY_BUDGET секунд, у git — таймаут 3 с. Нет отпечатка — нет переноса: папка слияния не клон репозитория PR,
   shallow, info/grafts, нет коммита base или head, не одна merge-base, вывод --raw не разобрать, plugin.json — не
   файл, сбой или таймаут git; git replace не действует. Тесты и talos не
   переносятся; каждый перенос — строка в STATE_DIR/merge-gate/carry.jsonl, не записалась — отказ; продукт — ещё запись talos и строка в ~/ai/pantheon/alerts.md со ссылкой
   owner/repo#N и словом «откат»; защиты — ещё Д3: PR не задевает ядро (CORE_DIR и CORE_FILES, сборка окон в pantheon.py по AST — metis-0404), casefold;
   файлы из pulls/N/files с previous_filename; PR, задевающий ядро, проходит только со строкой
   `<время> merge-approve <owner/repo>#<N> <sha>` для того же репозитория, PR и SHA в owner-log/merge-approve.log —
   её пишет тик после Touch ID владельца (metis-0285, `pantheon merge`), не старше суток. В защитах accept засчитывается, только если его ran начинается с
   «модель: claude-opus» (metis-0176) — но лишь в PR, который задевает ядро (или ядро не проверить): вне ядра один
   argus на любой модели, в том числе Sonnet (упрощение п. 9, 27.10). accept другой модели в PR ядра — как будто его
   нет, reject любой модели в силе.
   Незаменённый шаблон «<ID>» в ran — отказ ещё до записи. Модель сверяется и с транскриптом argus: record пишет в
   accept и reject поле "models" — значения message.model его assistant-записей; в PR ядра accept засчитывается,
   только если все они claude-opus и среди них модель из ran. Транскрипта нет — поле "models_note", судим по ran;
   транскрипт найден, а моделей в нём нет — "models": [] и пометка NO_MODELS, в PR ядра accept не в счёт (metis-0413).
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
import hashlib
import json
import os
import re
import shlex
import subprocess
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
                 f"{MERGE_CMD}; PR, который задевает ядро защит (весь plugins/guard/, plugins/pantheon/roles/, .github/, "
                 "plugins/pantheon/lib/window_rules.py, сборка окон sandbox_build в plugins/pantheon/lib/pantheon.py и "
                 ".claude-plugin/marketplace.json), ждёт слияния владельцем (Д3): "
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
CORE_DIR = ("plugins/guard", "plugins/pantheon/roles",
            # CI с правом записи в main (metis-0512): workflow release и его скрипт .github/scripts/release.py
            ".github")
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
# PR ядра: «принять» засчитывается, только если argus проверял на Opus — поле ran начинается с «модель: claude-opus»
# (metis-0176; вне ядра модель не проверяется — упрощение п. 9). Незаменённый шаблон «<ID>» в ran — ошибка шаблона роли, а не модель
OPUS_RAN = re.compile(r"\s*модель:\s*claude-opus", re.I)
UNFILLED_ID = re.compile(r"<\s*id\s*>", re.I)
RAN_MODEL = re.compile(r"\s*модель:\s*(claude-[a-z0-9.-]*[a-z0-9])", re.I)  # ID модели из --ran
SEGMENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")  # session_id и agent_id в пути транскрипта — одним сегментом
NO_TRANSCRIPT = "транскрипта argus нет — модель по --ran"
NO_MODELS = "транскрипт argus найден, но моделей в нём нет — модель не подтвердить"  # metis-0413: не молча как NO_TRANSCRIPT
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
        if models is None:
            rec["models_note"] = NO_TRANSCRIPT
        else:  # [] — транскрипт найден, моделей нет (сменился формат?): в защитах не в счёт, а не «как без транскрипта»
            rec["models"] = models
            if not models:
                rec["models_note"] = NO_MODELS
    append_record(rec)
    return rec_kind


def agent_models(event):
    """Модели сессии argus по её транскрипту (metis-0176): отсортированные значения message.model assistant-записей,
    без «<synthetic>»; [] — моделей в нём нет, None — транскрипта нет или не прочесть. Путь у субагента —
    <папка transcript_path>/<session_id>/subagents/agent-<agent_id>.jsonl, у агента из Workflow — на две подпапки
    глубже, subagents/workflows/<runId>/agent-<agent_id>.jsonl (transcriptSubdir Claude Code, metis-0413); ищется и
    одна подпапка. У главной сессии (agent_id нет) — сам transcript_path. Свой файл субагента не нашёлся — None, а не
    главный transcript_path: он чужой (сессия того, кто позвал argus)."""
    tp, sid, aid = (event.get(k) for k in ("transcript_path", "session_id", "agent_id"))
    if not isinstance(tp, str) or not os.path.isabs(tp):
        return None
    if aid:
        if not (isinstance(aid, str) and isinstance(sid, str) and SEGMENT_ID.fullmatch(aid)
                and SEGMENT_ID.fullmatch(sid)):
            return None
        base, name = os.path.join(os.path.dirname(tp), sid, "subagents"), f"agent-{aid}.jsonl"
        paths = [os.path.join(base, name)] + [p for sub in (("*",), ("*", "*")) for p in
                                              sorted(glob.glob(os.path.join(glob.escape(base), *sub, name)))]
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
    ID или он с датой: claude-opus-4-1 и claude-opus-4-1-20250805). Транскрипт найден, а моделей нет ("models": []) —
    не засчитан с причиной NO_MODELS (metis-0413)."""
    ran = rec["checklist"]["ran"]
    if not OPUS_RAN.match(ran):
        return "по --ran"
    if "models" not in rec:
        return None  # транскрипта не было (models_note) или запись до metis-0176 — судим по ran
    seen = rec["models"]
    if seen == []:
        return NO_MODELS  # metis-0413: транскрипт без моделей не равен «транскрипта нет»
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


# Сборка окон в pantheon.py — тоже ядро (metis-0404, «да» владельца 27.10): sandbox_build пишет settings/<окно>.json —
# песочницу, permissions и env окон ролей. Признак — не весь файл, а то, от чего зависит записанное: функции
# SANDBOX_BUILD_ROOTS (сборка, её вызов с папками и лидами из реестра, файл запуска окна) и всё, на что они ссылаются по
# именам, транзитивно в пределах файла (role_settings, JOB_ROLES, SANDBOX_DOMAINS…). Правка — инструкция верхнего уровня
# с другим AST (комментарии не в счёт), которая задаёт или меняет такое имя: def и class — своё имя, global, запись в
# элемент или поле, метод-мутатор; прочие инструкции — все свои имена. Файл до и после — из git папки слияния
# (merge-base PR и head, как у переноса «принять»). Имена сборки — объединение замыканий на merge-base, head, base PR
# и живой вершине ветки base (gh api …/git/ref/heads/<base>): соседний PR, слитый в base после ответвления, мог
# добавить в сборку вызов функции, которую правит этот PR (ревью argus-b PR #160, Б1). Не получить, не разобрать, нет
# корня, файл переименован или в другом регистре — ядро. Вне признака: обращения по строке (getattr, globals()), псевдоним изменяемого значения, другие файлы
# (window_rules.py — в CORE_FILES)
SANDBOX_BUILD_FILE = "plugins/pantheon/lib/pantheon.py"
SANDBOX_BUILD_ROOTS = ("sandbox_build", "domains_build", "run_settings")
MUTATORS = frozenset({"append", "extend", "insert", "update", "setdefault", "pop", "popitem", "remove", "clear", "add",
                      "discard", "sort", "reverse", "__setitem__", "__delitem__", "__iadd__", "__ior__"})
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _base_name(n):
    """Имя в основании a.b[c].d — или None."""
    while isinstance(n, (ast.Attribute, ast.Subscript)):
        n = n.value
    return n.id if isinstance(n, ast.Name) else None


def _mutated(node):
    """Имена, которые node меняет на месте: global/nonlocal, запись и del в элемент или поле, метод-мутатор."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
        elif isinstance(n, (ast.Attribute, ast.Subscript)) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(_base_name(n))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in MUTATORS:
            out.add(_base_name(n.func.value))
    out.discard(None)
    return out


def _all_names(node):
    """Все имена в node: Name, имена def и class, import."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, _DEFS):
            out.add(n.name)
        elif isinstance(n, ast.alias):
            out.add((n.asname or n.name).split(".")[0])
    return out


def _touched(st, data):
    """Имена, которые задаёт или меняет инструкция верхнего уровня st; data — имена данных модуля (у def и class
    засчитывается изменение только их, а не своих локальных переменных)."""
    if isinstance(st, _DEFS):
        return {st.name} | (_mutated(st) & data)
    if isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
        targets = st.targets if isinstance(st, (ast.Assign, ast.Delete)) else [st.target]
        out = _mutated(st)
        for t in targets:
            out |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}
        return out
    # import, выражение, if/try/for/with верхнего уровня: что в них присваивается, объявляется и меняется на месте
    out = _mutated(st)
    for n in ast.walk(st):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, _DEFS):
            out.add(n.name)
        elif isinstance(n, ast.alias):
            out.add((n.asname or n.name).split(".")[0])
    return out


def _defs_closure(src):
    """Исходник → (имя → дампы его инструкций по порядку, замыкание SANDBOX_BUILD_ROOTS) или None: не разобрать,
    нет корня функцией верхнего уровня."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None
    defs, dumps = {}, {}
    data = set()
    for st in tree.body:
        if not isinstance(st, _DEFS):
            data |= _touched(st, set())
    for st in tree.body:
        for name in _touched(st, data):
            defs.setdefault(name, []).append(st)
    if not all(any(isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)) and st.name == r for st in tree.body)
               for r in SANDBOX_BUILD_ROOTS):
        return None
    seen, todo = set(), list(SANDBOX_BUILD_ROOTS)
    while todo:
        name = todo.pop()
        if name in seen or name not in defs:
            continue
        seen.add(name)
        for st in defs[name]:
            todo.extend(_all_names(st))
    memo = {id(st): ast.dump(st) for st in tree.body}
    for name, sts in defs.items():
        dumps[name] = [memo[id(st)] for st in sts]
    return dumps, seen


def sandbox_build_changes(old, new, *tips):
    """Исходники pantheon.py до и после → имена сборки окон, которые PR задевает (отсортированы), или None — не
    разобрать или нет корня: тогда ядро. tips — исходники на вершинах base: их замыкания тоже в счёт (Б1 PR #160 —
    в base после ответвления PR сборка стала звать функцию, которую PR правит)."""
    a, b = _defs_closure(old), _defs_closure(new)
    more = [_defs_closure(t) for t in tips]
    if a is None or b is None or any(c is None for c in more):
        return None
    names = a[1] | b[1]
    for c in more:
        names |= c[1]
    return sorted(n for n in names if a[0].get(n, []) != b[0].get(n, []))


def _blob(gd, rev, path):
    """Текст обычного файла path в коммите rev из git gd или None (нет, ссылка, подмодуль, не UTF-8, сбой)."""
    out = _git_bytes(gd, "ls-tree", "-z", rev, "--", path)
    m = re.fullmatch(rb"(100644|100755) blob ([0-9a-f]{40,64})\t([^\0]*)\0", out or b"")
    if not m or m.group(3) != path.encode():
        return None
    raw = _git_bytes(gd, "cat-file", "blob", m.group(2).decode())
    try:
        return raw.decode("utf-8") if raw is not None else None
    except UnicodeDecodeError:
        return None


BRANCH_RE = re.compile(r"(?!.*\.\.)(?!/)(?!.*//)[A-Za-z0-9._/-]{1,200}(?<![/.])")


def _base_tip(repo, branch):
    """Живая вершина ветки branch в repo (gh api …/git/ref/heads/<branch>) — SHA коммита или None (сбой gh, не та
    ветка, не коммит, имя ветки не по формату)."""
    if not isinstance(branch, str) or not BRANCH_RE.fullmatch(branch):
        return None
    got = _gh_json(["api", f"repos/{repo}/git/ref/heads/{branch}"])
    ref = got[0] if isinstance(got, list) and len(got) == 1 and isinstance(got[0], dict) else {}
    obj = ref.get("object") if isinstance(ref.get("object"), dict) else {}
    sha = obj.get("sha")
    if ref.get("ref") != "refs/heads/" + branch or obj.get("type") != "commit" or not isinstance(sha, str) \
            or not SHA_RE.fullmatch(sha.lower()):
        return None
    return sha.lower()


def _sandbox_problem(cwd, repo, base, sha, branch=None):
    """PR правит pantheon.py: ядро ли это (metis-0404) — текст для списка задетого ядра или None (сборку окон не
    задевает). base — baseRefOid, branch — baseRefName: замыкание берётся и на живой вершине ветки (Б1 PR #160)."""
    gd, why = _carry_git(cwd, repo, base)
    if gd is None:
        return f"{SANDBOX_BUILD_FILE} (сборку окон не проверить: {why})"
    if _git_bytes(gd, "cat-file", "-e", sha + "^{commit}") is None:
        return f"{SANDBOX_BUILD_FILE} (сборку окон не проверить: коммита {sha[:12]} нет в git папки — сделай git fetch)"
    out = _git_bytes(gd, "merge-base", "--all", base.lower(), sha)
    mbs = out.split() if out is not None else []
    if len(mbs) != 1:
        return f"{SANDBOX_BUILD_FILE} (сборку окон не проверить: у {sha[:12]} и base PR нет единственной merge-base)"
    tip = _base_tip(repo, branch)
    if tip is None:
        return f"{SANDBOX_BUILD_FILE} (сборку окон не проверить: вершину ветки base PR ({branch}) не получить от gh)"
    if _git_bytes(gd, "cat-file", "-e", tip + "^{commit}") is None:
        return f"{SANDBOX_BUILD_FILE} (сборку окон не проверить: вершины base {tip[:12]} нет в git папки — сделай " \
               f"git fetch)"
    mb = mbs[0].decode("ascii", "replace")
    old, new = _blob(gd, mb, SANDBOX_BUILD_FILE), _blob(gd, sha, SANDBOX_BUILD_FILE)
    tips = [_blob(gd, r, SANDBOX_BUILD_FILE) for r in dict.fromkeys((base.lower(), tip)) if r != mb]
    ok = old is not None and new is not None and all(t is not None for t in tips)
    got = sandbox_build_changes(old, new, *tips) if ok else None
    if got is None:
        return f"{SANDBOX_BUILD_FILE} (сборку окон не проверить: файла нет до или после, не разобрать или нет " \
               f"{'/'.join(SANDBOX_BUILD_ROOTS)})"
    if got:
        shown = ", ".join(got[:8]) + (f" и ещё {len(got) - 8}" if len(got) > 8 else "")
        return f"{SANDBOX_BUILD_FILE} (сборка окон: {shown})"
    return None


PR_VIEW_FIELDS = "headRefOid,baseRefOid,baseRefName,changedFiles,statusCheckRollup"


def _pr_view(repo, pr):
    """Один gh pr view на шлюз — и для Д3, и для проверок GitHub (таймаут хука 10 с): словарь или None (сбой)."""
    got = _gh_json(["pr", "view", str(pr), "-R", repo, "--json", PR_VIEW_FIELDS])
    data = got[0] if isinstance(got, list) and len(got) == 1 else None
    return data if isinstance(data, dict) else None


def _pr_files(repo, pr):
    """Файлы PR из REST pulls/N/files (status, previous_filename, patch) — список или None (сбой gh)."""
    return _gh_json(["api", f"repos/{repo}/pulls/{pr}/files?per_page=100", "--paginate", "--jq", ".[]"])


_FETCH = object()  # _core_problem без files: список запросить здесь


def _core_problem(repo, pr, sha, data, files=_FETCH, cwd=None):
    """Д3: PR защит, который задевает ядро, ждёт слияния владельцем. data — ответ _pr_view. Файлы — из REST
    pulls/N/files (там есть status и previous_filename: переименование ядра не прячет старый путь); files — уже
    полученный ответ _pr_files, в том числе None (сбой gh — отказ, без второго запроса: argus-b PR #153 Б1), без
    него — запрос здесь. Список файлов неполон, PR на другом коммите — тоже отказ."""
    count, head = data.get("changedFiles"), data.get("headRefOid")
    if files is _FETCH:
        files = _pr_files(repo, pr)
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
    # сборка окон в pantheon.py (metis-0404): ядро, если PR задевает её имена; переименование и другой регистр — ядро
    norm = [p.strip("/").casefold() for p in paths]
    while any(p.startswith("./") for p in norm):
        norm = [p[2:].lstrip("/") if p.startswith("./") else p for p in norm]
    if SANDBOX_BUILD_FILE in norm:
        own = [f for f in files if SANDBOX_BUILD_FILE in [str(n).strip("/").casefold().lstrip("./")
                                                          for n in (f.get("filename"), f.get("previous_filename"))]]
        if len(own) != 1 or own[0].get("filename") != SANDBOX_BUILD_FILE or own[0].get("previous_filename") is not None:
            hit.append(f"{SANDBOX_BUILD_FILE} (переименован, удалён, добавлен или путь в другом регистре)")
        else:
            why = _sandbox_problem(cwd, repo, data.get("baseRefOid"), sha, data.get("baseRefName"))
            if why:
                hit.append(why)
    if hit:
        return f"{MERGE_CORE_HIT}{', '.join(hit)}"
    return None


# номер версии плагина поднимает workflow release на main после слияния (metis-0512, вариант Б): PR его не трогает,
# иначе соседние PR конфликтуют в plugin.json после каждого слияния. Отказ — и с Touch ID владельца: коммиты выпуска
# Action идут в main мимо PR, а номер в PR — всегда ошибка автора
PLUGIN_MANIFEST_RE = re.compile(r"plugins/[^/]+/\.claude-plugin/plugin\.json")
RELEASES_FILE = ".claude-plugin/releases.json"
JSON_STR_RE = re.compile(r'"(?:[^"\\]|\\.)*"')
MERGE_VERSION = ("номер версии поднимает workflow release на main после слияния (metis-0512): убери из PR правку "
                 "version в plugin.json и файл .claude-plugin/releases.json; новый коммит — новые записи тестов и argus")


def _touches_version(patch):
    """В строках +/- патча есть JSON-строка "version" (и с \\u-экранированием, без учёта регистра) — True."""
    for line in patch.splitlines():
        if line[:1] not in ("+", "-"):
            continue
        for m in JSON_STR_RE.finditer(line[1:]):
            try:
                val = json.loads(m.group(0))
            except ValueError:
                return True  # строку не разобрать — считаем правкой номера
            if isinstance(val, str) and val.strip().casefold() == "version":
                return True
    return False


def _version_problem(files):
    """metis-0512: PR правит version в plugins/*/.claude-plugin/plugin.json или трогает .claude-plugin/releases.json —
    текст отказа, иначе None. files — ответ _pr_files; сбой и неполный список решает _core_problem. Новый и удалённый
    plugin.json (новый плагин или его удаление) — можно. Патча нет — отказ: правку version не проверить."""
    if not isinstance(files, list):
        return None
    hit = []
    for f in files:
        if not isinstance(f, dict):
            return None
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


# перенос «принять» после подтягивания main (metis-0415, решение владельца 24.10 17:54 [metis-0384b]): «принять»
# с прошлого head переходит на новый, только если собственный дифф PR от merge-base с base PR тот же — по содержимому
# файлов (git diff --raw, решение владельца 25.10 23:05), кроме строки version в plugin.json; сбой git и неполная
# история — не переходит
CARRY_HEADS = 8  # сколько прошлых head с вердиктами сверять (кроме нового); старые — без отпечатка
CARRY_BUDGET = 4  # с на все отпечатки одного шлюза: дальше — без отпечатка (таймаут хука 10 с, ещё gh pr view и CI)
PLUGIN_JSON_RE = re.compile(rb"plugins/[^/]*/\.claude-plugin/plugin\.json")
# дифф без pathspec и без текста: от конфига git (diff.*, core.abbrev, атрибуты, diff.submodule) вывод не зависит,
# orderFile меняет только порядок строк — сортировка в Python (threat-134-carry п.2)
RAW_FLAGS = ("--raw", "-z", "--no-abbrev", "--no-renames", "--no-relative", "--ignore-submodules=none")
# «:режим режим sha sha статус» строки --raw; --no-renames — статус одной буквой без процента, sha1 или sha256
RAW_META_RE = re.compile(rb":([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40}(?:[0-9a-f]{24})?) ([0-9a-f]{40}(?:[0-9a-f]{24})?) "
                         rb"([ADMT])")


def _git_bytes(gd, *args, input=None):
    """Вывод git (байты) в git dir gd без рабочего дерева, без подмен git replace; None — сбой, таймаут, код не 0."""
    env = dict(_git_env(), GIT_NO_REPLACE_OBJECTS="1")
    try:
        r = subprocess.run(["git", "-C", gd, "--git-dir=" + gd, "--no-replace-objects", "-c", "core.quotePath=true",
                            *args], input=input, capture_output=True, timeout=3, env=env)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _carry_git(cwd, repo, base):
    """Git папки слияния для сверки диффов → (git dir, None) или (None, почему не переносится). Нужны: папка — клон
    repo (remote), полная история (не shallow, без info/grafts) и коммит base PR в git папки."""
    remotes = _git_remotes(cwd) if cwd else None
    if remotes is None or repo not in {_repo_tail(r) for r in remotes}:
        return None, f"папка слияния — не клон {repo}, диффы не сверить (сливай из клона {repo})"
    out = _git(cwd, "rev-parse", "--absolute-git-dir")
    gd = (out or "").strip()
    if not gd:
        return None, "git папки слияния не ответил"
    shallow = _git_bytes(gd, "rev-parse", "--is-shallow-repository")
    if shallow is None or shallow.strip() != b"false":
        return None, "неполная история в git папки (shallow clone, git fetch --depth) — сделай git fetch --unshallow"
    grafts = _git_bytes(gd, "rev-parse", "--git-path", "info/grafts")
    if grafts is None:
        return None, "git папки слияния не ответил"
    if os.path.lexists(os.path.join(gd, os.fsdecode(grafts.strip()))):
        return None, "в git папки есть info/grafts — история подменена"
    if not isinstance(base, str) or not SHA_RE.fullmatch(base.lower()) \
            or _git_bytes(gd, "cat-file", "-e", base.lower() + "^{commit}") is None:
        return None, f"коммита base PR ({str(base)[:12]}) нет в git папки — сделай git fetch"
    return gd, None


def _manifest_canon(raw):
    """plugin.json без поля version — каноничная строка; не JSON-объект, два одинаковых ключа или version не
    строкой — ValueError."""
    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("два одинаковых ключа")
        return dict(items)
    obj = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    if not isinstance(obj, dict) or not isinstance(obj.get("version", ""), str):
        raise ValueError("не объект или version не строкой")
    obj.pop("version", None)
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _raw_entries(gd, mb, head):
    """git diff --raw mb..head без pathspec → [(режим, режим, sha, sha, статус, путь)] (байты) или None: сбой git
    или вывод не по формату (строгий разбор: лишнее поле или статус — None)."""
    out = _git_bytes(gd, "diff", *RAW_FLAGS, mb, head)
    if out is None:
        return None
    if not out:
        return []
    if not out.endswith(b"\0"):
        return None
    parts = out[:-1].split(b"\0")
    if len(parts) % 2:
        return None
    entries = []
    for meta, path in zip(parts[::2], parts[1::2]):
        m = RAW_META_RE.fullmatch(meta)
        if not m or not path:
            return None
        entries.append(m.groups() + (path,))
    if len({e[5] for e in entries}) != len(entries):
        return None
    return entries


def _manifests(gd, entries):
    """Правки plugin.json плагинов (из _raw_entries) без строки version → список строк или None (не разобрать).
    Пропускается только правка, где поменялся один номер версии: режим тот же, канон без version тот же."""
    out = []
    for om, nm, osha, nsha, st, path in entries:
        sides = {b"A": (nsha,), b"D": (osha,), b"M": (osha, nsha)}.get(st)
        if sides is None:
            return None
        canon = []
        for blob_sha in sides:
            blob = _git_bytes(gd, "cat-file", "blob", blob_sha)
            if blob is None:
                return None
            try:
                canon.append(_manifest_canon(blob))
            except (ValueError, UnicodeDecodeError, RecursionError):
                return None
        if st == b"M" and om == nm and canon[0] == canon[1]:
            continue  # поменялся только номер версии
        out.append("\0".join((st.decode(), om.decode(), nm.decode(), os.fsdecode(path), *canon)))
    return sorted(out)


def _fingerprint(gd, base, head):
    """Отпечаток собственного диффа PR: merge-base(base, head)..head — строки git diff --raw (режимы, sha блобов и
    gitlink, статус, путь; решение владельца 25.10 23:05), сортированные по пути, кроме plugin.json плагинов — их
    правки без строки version → (отпечаток, merge-base) или (None, почему не посчитан)."""
    if not SHA_RE.fullmatch(head) or _git_bytes(gd, "cat-file", "-e", head + "^{commit}") is None:
        return None, f"коммита {head[:12]} нет в git папки"
    out = _git_bytes(gd, "merge-base", "--all", base, head)
    mbs = out.split() if out is not None else []
    if len(mbs) != 1:
        return None, f"у {head[:12]} и base PR нет единственной merge-base"
    mb = mbs[0].decode("ascii", "replace")
    entries = _raw_entries(gd, mb, head)
    if entries is None:
        return None, f"git diff --raw на {head[:12]} не ответил или не разобрать"
    plugins = _manifests(gd, [e for e in entries if PLUGIN_JSON_RE.fullmatch(e[5])])
    if plugins is None:
        return None, f"plugin.json на {head[:12]} не разобрать (не JSON, два ключа, version не строкой, не файл)"
    rows = sorted((e for e in entries if not PLUGIN_JSON_RE.fullmatch(e[5])), key=lambda e: e[5])
    h = hashlib.sha256(b"carry-v3\0" + b"".join(b" ".join(e[:5]) + b"\0" + e[5] + b"\0" for e in rows) + b"\0"
                       + "\0".join(plugins).encode("utf-8"))
    return h.hexdigest(), mb


def _carry_heads(verdicts, sha):
    """Head, у которых считается отпечаток: sha и CARRY_HEADS последних (по последней записи) других head."""
    order = []
    for r in reversed(verdicts):
        if r["sha"] != sha and r["sha"] not in order:
            order.append(r["sha"])
    return {sha, *order[:CARRY_HEADS]}


def _self_lift(a, r):
    """«Принять» a с перечнем того же рецензента на том же head, что «вернуть» r: рецензент сам снял своё «вернуть»
    (правило 1 _lifts и отсечка _carried; без перечня не снимает — metis-0415, Зевс 25.10 23:10)."""
    return _reviewer(a) == _reviewer(r) and a["sha"] == r["sha"] and checklist_ok(a)


def _lifts(a, r, sha, fp):
    """Снимает ли «принять» a (записано после «вернуть» r) это «вернуть» для слияния sha. fp(head) → (отпечаток,
    merge-base) или None. Все правила — только «принять» с перечнем (Б6). 1: тот же рецензент на том же head.
    2: на sha, r — на другом head: тот же рецензент — снимает; другой argus — только если код sha посчитан и не
    равен коду r (решение 25.10 23:10, 0415b: иначе «вернуть» обходится выбором рецензента; код не посчитан — не
    снимает). 3: на третьем head с другим кодом от той же merge-base, если код sha — не код r."""
    if not checklist_ok(a):
        return False
    if _self_lift(a, r):
        return True
    if a["sha"] == sha:
        if r["sha"] == sha:
            return False
        if _reviewer(a) == _reviewer(r):
            return True
        fr, fs = fp(r["sha"]), fp(sha)
        return bool(fr and fs) and fs[0] != fr[0]
    if r["sha"] == sha or a["sha"] == r["sha"]:
        return False
    fr, fa, fs = fp(r["sha"]), fp(a["sha"]), fp(sha)
    return bool(fr and fa and fs) and fr[1] == fa[1] and fr[0] != fa[0] and fs[0] != fr[0]


def _held(verdicts, sha, fp):
    """«Вернуть» на PR (любой head), которые в силе: ни одно «принять», записанное после, их не сняло (_lifts)."""
    return [r for i, r in enumerate(verdicts) if r["kind"] == "reject"
            and not any(a["kind"] == "accept" and _lifts(a, r, sha, fp) for a in verdicts[i + 1:])]


def _floor(verdicts):
    """Отсечка (#134 п.2, argus-b r2): номер последнего «вернуть» PR, которое не снял тот же рецензент «принять» с
    перечнем на том же head (_self_lift), или -1. «Принять», записанное до отсечки, не засчитывается ни прямо на своём
    head, ни переносом: иначе откат к коду, принятому до «вернуть» (force-push на старый head), прошёл бы по старому
    «принять», если «вернуть» снято «принять» на другом коде (правило 3 _lifts)."""
    floor = -1
    for i, r in enumerate(verdicts):
        if r["kind"] == "reject" and not any(a["kind"] == "accept" and _self_lift(a, r) for a in verdicts[i + 1:]):
            floor = i
    return floor


def _carried(verdicts, sha, fp, cut=None):
    """«Принять» с перечнем на других head того же PR, чей отпечаток равен отпечатку sha, записанные позже отсечки
    _floor. cut — список: в него пары («принять», отсёкшее его «вернуть») с тем же отпечатком, но записанные раньше
    отсечки (для текста отказа)."""
    fs = fp(sha)
    if not fs:
        return []
    floor = _floor(verdicts)
    out = []
    for i, a in enumerate(verdicts):
        if a["kind"] == "accept" and a["sha"] != sha and checklist_ok(a):
            fa = fp(a["sha"])
            if fa and fa[0] == fs[0]:
                if i > floor:
                    out.append(a)
                elif cut is not None:
                    cut.append((a, verdicts[floor]))
    return out


class _Prints:
    """Отпечатки head для одного шлюза: git папки и base PR — один раз, отпечаток — по запросу и только для
    _carry_heads; why — почему чего-то не посчитали (для текста отказа)."""

    def __init__(self, cwd, repo, sha, verdicts, view):
        self.cwd, self.repo, self.sha, self.view = cwd, repo, sha, view
        self.allowed = _carry_heads(verdicts, sha)
        self.memo, self.why, self.gd, self.base, self.ready = {}, [], None, None, False
        self.t0 = time.monotonic()

    def _note(self, why):
        if why and why not in self.why:
            self.why.append(why)

    def __call__(self, head):
        if head not in self.allowed:
            self._note(f"head {head[:12]} старше {CARRY_HEADS} последних — не сверялся")
            return None
        if not self.ready:
            self.ready = True
            v = self.view()
            base = v.get("baseRefOid") if isinstance(v, dict) else None
            if base is None:
                self._note("gh pr view не ответил — base PR неизвестна")
            else:
                self.gd, why = _carry_git(self.cwd, self.repo, base)
                self.base = base.lower() if self.gd else None
                self._note(why)
        if not self.gd:
            return None
        if head not in self.memo and time.monotonic() - self.t0 > CARRY_BUDGET:
            self._note(f"сверка дольше {CARRY_BUDGET} с — остановлена (таймаут хука 10 с)")
            return None
        if head not in self.memo:
            got = _fingerprint(self.gd, self.base, head)
            self.memo[head] = got if got[0] else None
            if not got[0]:
                self._note(got[1])
        return self.memo[head]


def carry_file():
    """Журнал переносов «принять» (metis-0415) — отдельно от records.jsonl: тот читают pantheon review status и
    метрики, вида carry там нет."""
    return os.path.join(gate_dir(), "carry.jsonl")


def append_carry(rec):
    d = gate_dir()
    if os.path.islink(d):
        raise OSError("merge-gate — симлинк")
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    fd = os.open(carry_file(), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def _reviewer(rec):
    """Рецензент записи — пара (session_id, agent_id): два argus одной сессии — разные рецензенты (metis-0158)."""
    return rec["by"].get("session_id") or "", rec["by"].get("agent_id") or ""


def _who(rec):
    """Чей вердикт — для текста отказа: роль, первые 8 знаков agent_id и session_id, время записи."""
    sid, aid = _reviewer(rec)
    return (f"{rec['by'].get('agent_type') or '?'} agent {aid[:8] or '—'}, сессия {sid[:8] or '—'}, "
            f"запись {rec.get('time') if isinstance(rec.get('time'), str) else '?'}")


def gate_problem(event, policy, repo_name, cmd_repos, numbers, auto, heads, advice, protect, cwd=None):
    """Запор (P1-4): то, что проверено, — ровно то, что сливается. Текст отказа или None."""
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
    if not any(r["kind"] == "tests" and r["sha"] == sha and repo in [x.lower() for x in r["repo"]] for r in records):
        return (f"нет записи тестов на {repo}@{sha[:12]}: в чистом дереве на этом коммите запусти "
                f"`pantheon review test -- <команда тестов>` (запишет хук guard). Тесты долгие: запускай "
                f"`pantheon review test` не в фоне, с timeout до 600000 мс (у Bash по умолчанию 120 с). {advice}")

    def mine(r, kinds, who, any_sha=False):
        return (r["kind"] in kinds and r["by"].get("agent_type") == who and r["pr"] == pr
                and (any_sha or r["sha"] == sha) and repo in [x.lower() for x in r["repo"]])

    # вердикты argus на PR — на любом head (metis-0415): «вернуть» привязано к PR, «принять» переносится по отпечатку
    pr_verdicts = [r for r in records if mine(r, ("accept", "reject"), "argus", any_sha=True)]
    seen_view = []
    seen_files = []

    def pr_view():
        if not seen_view:
            seen_view.append(_pr_view(repo, pr))
        return seen_view[0]

    def pr_files():
        # один запрос файлов на шлюз: сбой (None) не повторяется в _core_problem, а даёт там отказ — иначе удачный
        # второй запрос пропустил бы PR с правкой version мимо _version_problem (argus-b PR #153 Б1)
        if not seen_files:
            seen_files.append(_pr_files(repo, pr))
        return seen_files[0]

    # защиты (metis-0176, simplify п. 9): «принять» не на Opus не засчитывается — как будто его нет — только в PR,
    # который задевает ядро; вне ядра один argus на любой модели. «Вернуть» любой модели в силе, «принять» без перечня
    # остаётся, чтобы отказ Б6 ниже сказал о перечне. Ядро ли — по тому же _core_problem, что и Д3; не удалось
    # проверить (gh не ответил, список файлов неполон) — считаем ядром: строже, а отказ Д3 ниже всё равно будет
    weak = [r for r in pr_verdicts if protect and r["kind"] == "accept" and checklist_ok(r) and opus_problem(r)]
    if weak:
        view = pr_view()
        if view is not None and _core_problem(repo, pr, sha, view, pr_files(), cwd) is None:
            weak = []
    verdicts = [r for r in pr_verdicts if not any(r is w for w in weak)]

    fp = _Prints(cwd, repo, sha, pr_verdicts, pr_view)

    def why_fp():
        return (" Перенос не сверен: " + "; ".join(fp.why) + ".") if fp.why else ""

    held = _held(verdicts, sha, fp)
    if held:
        return (f"«вернуть» (reject) на {repo}#{pr} от {'; '.join(_who(r) + ' на ' + r['sha'][:12] for r in held)}: "
                "«вернуть» привязано к PR, а не к коммиту. Его снимает «принять» с перечнем, записанное после него: "
                "того же рецензента (верни ему исправление) или свежее «принять» argus на новый коммит "
                f"{sha[:12]} с другим кодом — `pantheon review accept {repo} {pr} {sha} {CHECKLIST_HINT}`. «Принять» "
                "другого argus на тот же коммит, на коммит с тем же кодом, что у «вернуть» (и на сливаемый), или с "
                "другой merge-base «вернуть» не перекрывает; код не посчитан — тоже."
                + why_fp() + f" {advice}")
    latest = {}  # рецензент (session_id, agent_id) → его последний вердикт на sha; порядок — по первой записи
    for r in verdicts:
        if r["sha"] == sha:
            latest[_reviewer(r)] = r
    # прямое «принять» на sha — тоже только после отсечки (argus-b r2): откат force-push на head, принятый до «вернуть»
    floor = _floor(verdicts)
    pos = {id(r): i for i, r in enumerate(verdicts)}
    cut = [(r, verdicts[floor]) for r in latest.values() if r["kind"] == "accept" and pos[id(r)] <= floor]
    direct = [r for r in latest.values() if r["kind"] == "accept" and pos[id(r)] > floor]
    carried = [] if direct else _carried(verdicts, sha, fp, cut)
    if not direct and not carried:
        fs = fp(sha) if weak else None
        weak_used = [r for r in weak if r["sha"] == sha or (fs and fp(r["sha"]) and fp(r["sha"])[0] == fs[0])]
        if weak_used:
            unfilled = any(UNFILLED_ID.search(r["checklist"]["ran"]) for r in weak_used)
            return (f"«принять» на {repo}#{pr}@{sha[:12]} от "
                    f"{'; '.join(_who(r) + ' на ' + r['sha'][:12] + ' (' + opus_problem(r) + ')' for r in weak_used)}"
                    " — не на Opus: "
                    "в PR, который задевает ядро защит (или ядро не проверить), шлюз засчитывает только проверку argus "
                    "на модели claude-opus (--ran начинается с «модель: claude-opus»). Проверку повторяет argus на Opus и записывает `pantheon review accept "
                    f"{repo} {pr} {sha} --ran \"модель: claude-opus-…, что запустил\" …`."
                    + (f" Кроме того, {UNFILLED_ID_HINT}." if unfilled else "") + f" {advice}")
        return (f"нет «принять» от argus на {repo}#{pr}@{sha[:12]}: позови argus, он проверит и запишет "
                f"`pantheon review accept {repo} {pr} {sha} {CHECKLIST_HINT}`. «Принять» с прошлого head PR переходит "
                "на новый, только если собственный дифф PR от merge-base с base PR тот же (кроме номера версии в "
                "plugin.json) и «принять» записано после каждого «вернуть» PR." + why_fp()
                + (f" Дифф тот же у «принять» {'; '.join(_who(a) + ' на ' + a['sha'][:12] for a, _ in cut)}, но оно "
                   f"записано раньше «вернуть» {_who(cut[0][1])} на {cut[0][1]['sha'][:12]}: после «вернуть» старое "
                   "«принять» не засчитывается ни на своём head, ни переносом (откат к принятому коду), нужен свежий "
                   "argus." if cut else "")
                + f" {advice}")
    old = [r for r in direct if not checklist_ok(r)]
    if old:
        return (f"«принять» на {repo}#{pr}@{sha[:12]} от {'; '.join(_who(r) for r in old)} — без перечня "
                f"проверенного (Б6): запись старого формата или неполная. Тот же argus, повтори `pantheon review "
                f"accept {repo} {pr} {sha} {CHECKLIST_HINT}`. {advice}")
    me = ((event or {}).get("session_id") or "", (event or {}).get("agent_id") or "")
    if me in latest or me in {_reviewer(r) for r in carried}:
        return (f"рецензент и сливающий — одна и та же сессия: «принять» должен дать отдельный argus, а среди "
                f"рецензентов {repo}#{pr}@{sha[:12]} — и сливающий. {advice}")
    if advice == MERGE_PRODUCT:
        if not any(mine(r, ("talos",), "talos") for r in records):
            return (f"продукт — нет проверки talos на {repo}#{pr}@{sha[:12]}: позови talos, он проверит живое "
                    f"приложение и запишет `pantheon review talos {repo} {pr} {sha}` (talos не переносится "
                    f"с прошлого head). {advice}")
        if not _alert_ok(repo, pr):
            return (f"продукт — нет строки «что ушло» в ~/ai/pantheon/alerts.md со ссылкой {repo}#{pr} и словом "
                    f"«откат»: `pantheon alert \"{repo}#{pr}: что ушло; откат: <команда>\"`. {advice}")
    view = pr_view()
    if view is None:
        return (f"{CI_NONE}: gh pr view {pr} -R {repo} не ответил — без него не сверить ни проверки GitHub, ни "
                f"файлы PR (ядро), повтори позже. {advice}")
    if protect:
        files = pr_files()
        why = _version_problem(files)
        if why:
            return f"{why}. {MERGE_VERSION}. {advice}"
        why = _core_problem(repo, pr, sha, view, files, cwd)
        # Д3 через Touch ID (metis-0285): палец владельца на этот PR и этот SHA — строка тика в owner-log. Пускает
        # только задетое ядро; сбой gh, неполный список файлов и другой head — отказ и со строкой
        if why and not (why.startswith(MERGE_CORE_HIT) and owner_approved(repo, pr, sha)):
            return f"{why}. {MERGE_PROTECT}"
    why = _ci_problem(repo, pr, sha, view)
    if why:
        return f"{why}. {advice}"
    if carried:
        try:
            append_carry({"v": RECORD_V, "kind": "carry", "repo": [repo], "pr": pr, "sha": sha, "base": fp.base,
                          "fp": fp(sha)[0], "by": {"session_id": me[0], "agent_id": me[1]},
                          "from": [{"sha": r["sha"], "by": r["by"], "time": r.get("time")} for r in carried],
                          "time": datetime.now().astimezone().isoformat(timespec="seconds")})
        except (OSError, TypeError, ValueError) as e:
            return (f"перенос «принять» на {repo}#{pr}@{sha[:12]} не записать в журнал "
                    f"~/.local/state/pantheon/merge-gate/carry.jsonl ({e}) — без записи переноса шлюз не пускает. "
                    f"{MERGE_OWNER}")
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
        # без политики (нет policy.toml или он не разбирается) guard не знает папок защит — закрыто всем
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
    return gate_problem(event, policy, repo_name, cmd_repos, numbers, auto, heads, advice, protect, cwd=cwd)
