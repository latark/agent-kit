"""Отказ роли → тот, кто умеет; владельцу — только «да» или Touch ID на одно показанное действие (metis-0832, 0775).

Роль упирается в песочницу, классификатор Claude Code или в отсутствие команды. Раньше она писала владельцу «не умею,
сделайте сами» и давала команду для терминала. Теперь у отказа есть маршрут: кто это умеет и как передать ему поручение.
Владельцу уходит только вопрос «да/нет» (окно вопросов Зевса) или окно Touch ID — и то только там, где это безопасно.

  pantheon handoff route [--source S] [--task ID] [--] <текст отказа>   кто умеет и как передать; строка в журнал
                                         отказов. S — sandbox | classifier | nocmd | guard | role (по умолчанию role)
  pantheon handoff touch <вид> <цель> --task ID [--why "зачем"] [--wait С]   заявка на действие из белого списка:
                                         плановый проход покажет владельцу окно Touch ID с этим действием целиком и
                                         после пальца исполнит его один раз; --wait — ждать итога до С секунд (≤590)
  pantheon handoff status [ID]           заявки и итоги
  pantheon handoff cancel ID             снять свою заявку
  pantheon handoff run                   проход по заявкам — только плановый проход (из окна Claude Code — отказ)

Кто что умеет (ROUTES, первый подходящий по тексту отказа и команде):
  оплата                → только владелец руками: ни «да», ни Touch ID не действуют, роль пишет в отчёт что и где
  важная форма          → только владелец руками (вход, код из СМС, смена почты, телефона, пароля, договор и подпись,
                          заявка на торги, перевод денег, удаление аккаунта, госкабинеты)
  правка защит          → только PR и шлюз слияния (`pantheon merge request`); Touch ID вне шлюза её не разрешает
  удаление пачки        → только «да» владельца словами (вопрос через Зевса)
  белый список Touch ID → `pantheon handoff touch` (удалить worktree без своего, deploy.sh слитого коммита,
                          перезапуск демона CDP)
  браузер владельца     → Харон: карточка Зевсу «Харону: …», Зевс зовёт charon
  Telegram              → `pantheon read request`
  тесты и серверы       → `pantheon outside test|serve`
  окна и процессы       → Гестия: карточка Зевсу «Гестии: …», Зевс будит её `pantheon wake hestia --task`
  остальное             → вопрос владельцу «да/нет» через Зевса (`pantheon task new … --question … --option …`)
Подсказку роль получает сама: хук hooks/refusal.py на отказ песочницы и «команда не найдена» (PostToolUseFailure)
и на отказ классификатора (PermissionDenied → отметка → PostToolBatch); на отказ guard — `pantheon handoff route`.

Где Touch ID НЕ действует (touch_refusal, перечень — README guard, раздел «Touch ID: где не действует»):
  оплата — только руками владельца; важная форма — только руками; удаление пачки — только «да» словами; правка самих
  защит и настроек guard — только шлюз слияния; всё, что окно не может показать целиком (текст длиннее WINDOW_MAX,
  управляющие, невидимые и bidi-знаки, перенос строки, цель из нескольких путей) — только «да» словами; вид вне белого
  списка — отказ с подсказкой, кто это умеет.

Окно Touch ID (одно действие, один раз, по хешу текста):
  1. Роль пишет заявку: вид, цель, задача, зачем. Заявка из окна роли — в handoff/ рядом с PANTHEON_TMP (кэш окна, туда
     окно пишет само), вне окна — STATE/handoff/queue. Кто просит — имя окна по месту папки заявки (не из текста) и
     роль со слов заявки. Текст окна собирает describe() из живых фактов: путь, ветка и HEAD worktree, хеш deploy.sh
     и ветка origin, где есть HEAD, порт демона. Факты не те (коммит только здесь, ссылка, путь вне ~/projects, чужой
     gitdir, HEAD не слит) — отказ сразу.
     git у владельца идёт вне песочницы и config роли не читает: частный GIT_DIR в STATE (свой config, копия HEAD,
     refs и объекты роли — только как данные), глобальный и системный config выключены, защитные ключи — через
     GIT_CONFIG_COUNT (private_git). Config роли — копией байтов через `git config --file --no-includes`; ключ вне
     белого списка GIT_KEYS_OK — отказ. До вопроса — только чтение объектов (rev-parse, cat-file, ls-tree,
     for-each-ref); status с неотслеживаемыми — после пальца, до действия. deploy — только основная копия (не
     worktree, не .claude/, не кэш окна) и только слитый HEAD: он есть в ветке по умолчанию origin (цель
     refs/remotes/origin/HEAD, без неё — main, потом master) по уже известным ссылкам, без fetch; не слит или
     ссылки нет — отказ «только шлюз», окно показывает «HEAD … есть в origin/<ветка>». Исполняются байты deploy.sh из
     коммита HEAD (`cat-file blob`), чей хеш показан, через bash -s; дерево проверяется до и после запуска.
  2. Проход (тик, вне окна): заявка старше REQ_TTL — снята. Текст собирается заново; не равен тексту заявки — снята
     («изменилось с заявки — новая заявка»). Владелец не у Mac (простой больше PRESENT_SEC) — ждёт.
  3. Окно Touch ID — помощник слияния (merge.ask, lib/touchid.swift; merge.py не правится). Текст окна — ровно этот
     текст. Палец → под замком заявка перечитывается, текст собирается в третий раз; sha256 не равен показанному —
     снята без действия («изменилось после пальца — новый вопрос»). Равен — заявка забирается переименованием (второй
     раз не исполнится), строка `<время> handoff-approve <id> <sha256>` в owner-log/handoff-approve.log, действие
     исполняется, итог — <id>.result.json рядом с заявкой и строка в журнал отказов.
  4. Отказ («Не сливать» в окне) — снята, итог declined. Время вышло — ждёт RETRY_SEC. Окно не показать или помощника
     нет — ждёт, тревога один раз: «да» словами тут не замена — исполнителя по «да» у белого списка нет.

Журнал отказов — STATE/logs/handoff.jsonl: время, источник, вид, кому передано, итог (передано | ждёт Touch ID |
сделано | не вышло | отклонено | только владелец | только «да»), окно, роль, задача, id заявки. Хуки пишут туда сами
(они вне песочницы); `handoff route` и заявка из окна — в свой кэш окна (handoff/log.jsonl), проход переносит строки в
STATE. Доска (board-auto.md, boardtext.handoffs) показывает строку «Отказы за сутки: источник → кому ×N (итоги)».

Только стандартная библиотека: модуль грузит и хук hooks/refusal.py — без pantheon.py (P = None), пути от
PANTHEON_STATE и HOME.
"""
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core(); хук работает без него


def set_core(mod):
    global P
    P = mod


WINDOW_MAX = 400          # предел текста окна у помощника touchid.swift
REQ_TTL = 3600            # заявка Touch ID старше часа — снята: роль уже не ждёт
RETRY_SEC = 600           # окно закрыто без ответа — следующее не раньше
PRESENT_SEC = 300         # владелец у Mac: простой меньше 5 минут
RESULT_TTL = 86400
REQ_MAX = 16 * 1024
WHY_MAX = 160
WAIT_MAX = 590
DEPLOY_TIMEOUT = 1800
HINT_TTL = 3600           # отметка подсказки после отказа классификатора живёт час
ID_RE = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
TASK_RE = re.compile(r"[a-z][a-z0-9]{0,30}(?:-[a-z0-9]{1,30}){0,3}-\d{1,6}")
WINDOW_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
ROLE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
FINAL = ("done", "failed", "declined", "refused", "dropped")

SOURCES = ("sandbox", "classifier", "nocmd", "guard", "role")
SOURCE_RU = {"sandbox": "песочница", "classifier": "классификатор", "nocmd": "нет команды", "guard": "guard",
             "role": "роль"}
OUTCOME_RU = {"handed": "передано", "waiting": "ждёт Touch ID", "done": "сделано", "failed": "не вышло",
              "declined": "отклонено", "owner": "только владелец", "yes": "только «да»", "merge": "только шлюз",
              "refused": "отказ", "dropped": "снято"}

# --- кто умеет: маршрут отказа ------------------------------------------------------------------------------------

_DIR = "--direction <своё направление>"
NO_TERMINAL = ("Владельцу — только вопрос «да/нет» (через Зевса) или окно Touch ID; команду для его терминала и файл "
               "для правки ему не пиши.")
# (ключ, кому, признак в тексте отказа и команде, итог в журнал, как передать)
ROUTES = (
    ("payment", "владелец руками", re.compile(
        r"оплат|(?<![\w])плат[её]ж|checkout|(?<![\w])/pay(?:ment)?\b|\bcvv\b|\bcvc\b|номер\w*\s+карты|cc-(?:number|exp|csc)"
        r"|(?<![\w])купить(?![\w])|перевод\w*\s+(?:денег|средств)", re.I), "owner",
     "Оплата, покупка и перевод денег — только владелец сам, руками: ни «да», ни Touch ID их не разрешают. В отчёт — "
     "что и где оплатить, без команды."),
    ("important-form", "владелец руками", re.compile(
        r"форм\w*\s+(?:входа|логина)|код\w*\s+из\s+смс|смс-код|sms[- ]?code|смен\w*\s+(?:почты|телефона|пароля)"
        r"|подпис\w*\s+договор|договор\w*\s+и\s+подпис|электронн\w+\s+подпис|заявк\w*\s+на\s+участие"
        r"|удален\w*\s+аккаунт|госуслуг|gosuslugi\.ru|nalog\.ru|lk\.rosreestr", re.I), "owner",
     "Важная форма (вход, код из СМС, смена почты, телефона или пароля, договор и подпись, заявка на торги, удаление "
     "аккаунта, госкабинет) — только владелец сам; «да» и Touch ID не действуют. В отчёт — ссылка и что ввести."),
    ("guard", "шлюз слияния", re.compile(
        r"plugins/guard|managed-settings|\.claude/settings[\w.-]*\.json|\.claude/pantheon/|policy\.toml|grants\.toml"
        r"|approvals\.toml|hooks\.json|guard_rules|window_rules|protect_config", re.I), "merge",
     "Правка защит и настроек guard — только PR и шлюз слияния: `pantheon merge request <N> -R <owner/repo>` (Touch "
     "ID владельца — в шлюзе, на проверенный коммит). Отдельный Touch ID вне шлюза её не разрешает."),
    ("batch-delete", "«да» словами", re.compile(
        r"(?<![\w-])rm\s+(?:-\w+\s+)*[^\s;|&]*[*?\[]|(?<![\w-])rm\s+(?:-\w+\s+)*[^\s;|&-]\S*\s+(?!\d*>)[^\s;|&-]"
        r"|xargs\s+(?:-\S+\s+)*rm\b|-delete\b|удал\w*\s+(?:все|всё|выбранн\w+|\d+\s)", re.I), "yes",
     "Удаление пачки — только «да» владельца словами: вопрос через Зевса (`pantheon task new " + _DIR + " --owner zeus "
     "--question \"…\" --why \"…\" --option \"А — да …\" --option \"Б — нет …\"`). Touch ID его не разрешает."),
    ("touch", "Touch ID владельца", re.compile(
        r"git\s+(?:-C\s+\S+\s+)?worktree\s+remove|deploy\.sh|(?:перезапуск|перезапуст\w*|restart)\W+(?:\w+\W+)?"
        r"(?:демон\w*\s+)?(?:cdp|comet|chrome)|cdp-daemon\S*\s+(?:comet|chrome)", re.I), "waiting",
     "Копию .claude/worktrees/<имя> после отчёта субагента или слияния PR убирает без Touch ID `pantheon wt done <путь>` "
     "(metis-0835). Остальное — из белого списка Touch ID: `pantheon handoff touch <вид> <цель> --task <id> --why \"зачем\"` — плановый "
     "проход покажет владельцу окно Touch ID с этим действием и исполнит его один раз. Виды: worktree-remove <путь>, "
     "deploy <папка репозитория>, cdp-restart comet|chrome."),
    ("browser", "Харон", re.compile(
        r"comet|chrome|cdp|devtoolsactiveport|(?<!\d)(?:9222|933[3-9])(?!\d)|браузер|avito|доступ ограничен"
        r"|chrome-devtools|claude-in-chrome", re.I), "handed",
     "Браузер владельца (со входами) — Харон. Поручение — карточкой Зевсу: `pantheon task new " + _DIR +
     " --owner zeus --title \"Харону: <что прочитать>\" --text \"<адрес и что нужно>\"`; Зевс зовёт charon, итог "
     "придёт в задачу. К демону, его порту и паролю сам не подключайся."),
    ("telegram", "read", re.compile(r"telegram|tg[-_]read|(?<![\w.])t\.me/|телеграм", re.I), "handed",
     "Telegram — `pantheon read request " + _DIR + " --chat <чат> --since ГГГГ-ММ-ДД --until ГГГГ-ММ-ДД`: проход "
     "найдёт чаты и сам спросит у владельца «да» на их список."),
    ("outside", "outside", re.compile(
        r"eaddrinuse|listen\s+eperm|(?<![\w])bind\b|localhost|127\.0\.0\.1|(?<![\w])port\b|порт|unix\s+socket|сокет"
        r"|dev[- ]server|(?:pnpm|npm|yarn)\s+(?:run\s+)?dev\b|next\s+dev|vitest|playwright|pytest", re.I), "handed",
     "Тесты и серверы с портом или сокетом — вне окна: из корня worktree `pantheon outside test --wait 590` или "
     "`pantheon outside serve --wait 120` (Bash не в фоне, timeout 600000)."),
    ("hestia", "Гестия", re.compile(
        r"launchctl|osascript|(?<![\w-])p?kill(?:all)?\b|процесс|окн[оа]\b|tmux|iterm|claude\s+plugin|pantheon\s+"
        r"(?:restart|domains\s+build|plugins\s+update)|перезапуст", re.I), "handed",
     "Окна, процессы, перезапуск и выпуски — Гестия. Поручение — карточкой Зевсу: `pantheon task new " + _DIR +
     " --owner zeus --title \"Гестии: <что сделать>\" --text \"…\"`; Зевс поднимет её `pantheon wake hestia --task "
     "<id>`."),
)
ASK = ("ask", "«да» владельца", None, "handed",
       "Нужного исполнителя нет — вопрос владельцу «да/нет» через Зевса: `pantheon task new " + _DIR + " --owner zeus "
       "--question \"…\" --why \"…\" --option \"А — …\" --option \"Б — …\" --recommend \"А — потому что …\"`.")
ROUTE_KEYS = tuple(r[0] for r in ROUTES) + (ASK[0],)

# признаки отказа в тексте ошибки инструмента (PostToolUseFailure): обычный красный тест подсказки не получает
SANDBOX_RX = re.compile(r"operation not permitted|\beperm\b|sandbox|read-only file system|deny\(\d+\)|"
                        r"permission denied", re.I)
NOCMD_RX = re.compile(r"command not found|no such file or directory: ['\"]?[\w./-]+['\"]?$|not found in path|"
                      r"неизвестная команда|не понял «", re.I | re.M)


def refusal_source(text):
    """Источник отказа по тексту ошибки: sandbox | nocmd | None (обычный сбой — без подсказки)."""
    t = str(text or "")
    if SANDBOX_RX.search(t):
        return "sandbox"
    if NOCMD_RX.search(t):
        return "nocmd"
    return None


def refusal_line(text):
    """Строка ошибки с признаком отказа песочницы (журнал отказов, metis-1135): остальной вывод в журнал не идёт."""
    for ln in str(text or "").splitlines():
        if refusal_source(ln) == "sandbox":
            return ln.strip()
    return ""


def route(text):
    """(ключ, кому, итог, как передать) — первый маршрут, чей признак есть в тексте отказа и команде."""
    t = str(text or "")
    for key, who, rx, outcome, how in ROUTES:
        if rx.search(t):
            return key, who, outcome, how
    return ASK[0], ASK[1], ASK[3], ASK[4]


def hint(text, source="role"):
    """Подсказка роли: кто умеет, как передать, и запрет давать владельцу команды."""
    key, who, _, how = route(text)
    src = SOURCE_RU.get(source, source)
    return f"Пантеон (metis-0832): отказ ({src}) — это умеет {who}. {how} {NO_TERMINAL}"


# --- журнал отказов --------------------------------------------------------------------------------------------------

def home():
    return P.HOME if P is not None else os.environ.get("HOME") or os.path.expanduser("~")


def state(*parts):
    if P is not None:
        return P.path(*parts)
    base = os.environ.get("PANTHEON_STATE") or os.path.join(home(), ".local", "state", "pantheon")
    return os.path.join(os.path.realpath(base), *parts)


def now():
    if P is not None:
        return P.now()
    with contextlib.suppress(ValueError):
        return float(os.environ["PANTHEON_NOW"]) if os.environ.get("PANTHEON_NOW") else time.time()
    return time.time()


def log_path():
    return state("logs", "handoff.jsonl")


def own_dir():
    """Папка заявок и журнала этого вызова: в окне роли — handoff/ рядом с PANTHEON_TMP (кэш окна), иначе
    STATE/handoff/queue."""
    tmp = os.environ.get("PANTHEON_TMP")
    if tmp:
        return os.path.join(os.path.dirname(os.path.realpath(tmp)), "handoff")
    return state("handoff", "queue")


def caches():
    return os.path.join(home(), "Library", "Caches", "pantheon-sandbox")


def entry(source, key, outcome, **kw):
    e = {"t": round(now(), 3), "source": source if source in SOURCES else "role",
         "kind": key if key in ROUTE_KEYS else "ask", "outcome": outcome if outcome in OUTCOME_RU else "handed"}
    for k in ("window", "role", "task", "id"):
        v = kw.get(k)
        rx = {"window": WINDOW_RE, "role": ROLE_RE, "task": TASK_RE, "id": ID_RE}[k]
        if isinstance(v, str) and rx.fullmatch(v):
            e[k] = v
    return e


def _append(path, e):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def log(source, key, outcome, local=False, **kw):
    """Строка журнала отказов. local — из окна роли: в кэш окна (STATE окну закрыт), проход перенесёт."""
    e = entry(source, key, outcome, **kw)
    try:
        _append(os.path.join(own_dir(), "log.jsonl") if local else log_path(), e)
    except OSError:
        return None
    return e


def read_log(path=None, since=None):
    out = []
    try:
        with open(path or log_path(), encoding="utf-8") as fh:
            for ln in fh:
                with contextlib.suppress(ValueError):
                    e = json.loads(ln)
                    if isinstance(e, dict) and (since is None or float(e.get("t", 0)) >= since):
                        out.append(e)
    except OSError:
        pass
    return out


# --- где Touch ID не действует ---------------------------------------------------------------------------------------

TOUCH_KINDS = ("worktree-remove", "deploy", "cdp-restart")
# вид или признак → (канал, почему): owner — только руками владельца; yes — только «да» словами; merge — только шлюз
NO_TOUCH = {
    "payment": ("owner", "оплата — только владелец руками: ни «да», ни Touch ID"),
    "important-form": ("owner", "важная форма — только владелец сам: «да» и Touch ID не действуют"),
    "batch-delete": ("yes", "удаление пачки — только «да» владельца словами, не Touch ID"),
    "guard": ("merge", "правка защит и настроек guard — только PR и шлюз слияния, не Touch ID вне него"),
    "unshowable": ("yes", "окно Touch ID не покажет действие целиком — только «да» владельца словами"),
}
BAD_CHARS = ("Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp")


def showable(text):
    """Окно покажет текст целиком: не длиннее WINDOW_MAX, без управляющих, невидимых и bidi-знаков и переносов."""
    t = str(text)
    return 0 < len(t) <= WINDOW_MAX and not any(unicodedata.category(c) in BAD_CHARS for c in t)


class Refuse(Exception):
    """Отказ заявке: channel — owner | yes | merge | route | bad; key — вид отказа для журнала; текст — роли."""

    def __init__(self, channel, text, key="touch"):
        super().__init__(text)
        self.channel, self.key = channel, key


def no_touch(key, extra=""):
    ch, text = NO_TOUCH[key]
    return Refuse(ch, text + extra, key if key in ROUTE_KEYS else "touch")


def touch_refusal(kind, target, why=""):
    """None — Touch ID может разрешить; иначе Refuse с каналом и причиной. Признаки оплаты, важной формы, защит и
    пачки ищутся в виде, цели и «зачем» — Touch ID не снимает их и в белом списке."""
    if kind in NO_TOUCH:
        return no_touch(kind)
    blob = f"{kind} {target} {why}"
    for key in ("payment", "important-form", "guard", "batch-delete"):
        rx = next(r[2] for r in ROUTES if r[0] == key)
        if rx.search(blob):
            return no_touch(key)
    if kind not in TOUCH_KINDS:
        return Refuse("route", f"«{kind}» вне белого списка Touch ID ({', '.join(TOUCH_KINDS)}). {hint(blob)}",
                      route(blob)[0])
    if re.search(r"[*?\[\]{}]", str(target)):
        return no_touch("batch-delete", " (цель — шаблон, а не один путь)")
    if not showable(target) or not showable(why or "-") or any(c.isspace() for c in str(target)):
        return no_touch("unshowable")
    return None


# --- факты действия: текст окна собирается из них, а не из слов роли --------------------------------------------------

# git у владельца идёт вне песочницы, на репозитории, которым управляет роль. Config роли он не читает вовсе: каждый
# вызов — с частным GIT_DIR (своя папка в STATE: свой config, HEAD — копия, refs и packed-refs — ссылки на чтение,
# объекты — GIT_OBJECT_DIRECTORY), глобальный и системный config выключены, защитные ключи — через GIT_CONFIG_COUNT,
# replace-объекты выключены. Config роли читается только копией байтов (`git config --file <копия> --list -z
# --no-includes`): ключ вне белого списка GIT_KEYS_OK — отказ. До вопроса — только чтение объектов и ссылок (rev-parse,
# cat-file, ls-tree, for-each-ref); status — только после пальца, тем же частным GIT_DIR.
GIT_KEYS_OK = re.compile(
    r"core\.(?:repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks|"
    r"hookspath|fsmonitor|untrackedcache|autocrlf|eol|safecrlf|checkstat|trustctime|quotepath)"
    r"|remote\.[^\n]+\.(?:url|pushurl|fetch|push|tagopt|prune|mirror)"
    r"|branch\.[^\n]+\.(?:remote|pushremote|merge|rebase|description|vscode-merge-base)"
    r"|user\.(?:name|email|signingkey)|init\.defaultbranch|pull\.(?:rebase|ff)|push\.(?:default|autosetupremote)"
    r"|fetch\.prune|gc\.auto|extensions\.worktreeconfig|lfs\.repositoryformatversion|submodule\.[^\n]+\.(?:url|active)",
    re.I)
GIT_KEYS_COPY = ("core.ignorecase", "core.precomposeunicode", "core.filemode", "core.symlinks")
GIT_SAFE_KV = (("core.hooksPath", "/dev/null"), ("core.fsmonitor", "false"), ("core.pager", "cat"),
               ("diff.external", ""), ("core.untrackedCache", "false"), ("core.sshCommand", "false"))
CONFIG_MAX = 1024 * 1024
SCRIPT_MAX = 1024 * 1024


def git_env(gitdir=None, **kw):
    env = {"HOME": home(), "PATH": SAFE_PATH, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_PAGER": "cat",
           "GIT_NO_REPLACE_OBJECTS": "1", "LANG": "C", "GIT_CONFIG_COUNT": str(len(GIT_SAFE_KV))}
    for i, (k, v) in enumerate(GIT_SAFE_KV):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = k, v
    if gitdir:
        env["GIT_DIR"] = gitdir
        env["GIT_CEILING_DIRECTORIES"] = os.path.dirname(gitdir)
    env.update({k: v for k, v in kw.items() if v})
    return env


def run_git(args, env, cwd, timeout=30):
    """git → stdout байтами; код не 0 — Refuse("bad")."""
    r = subprocess.run(["git", "--no-optional-locks", *args], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise Refuse("bad", f"git {args[0]}: {r.stderr.decode('utf-8', 'replace').strip()[:160]}")
    return r.stdout


def git_dirs(p):
    """(git-dir, common-dir) корня репозитория p — по .git и commondir как текст, без git; иначе Refuse."""
    dot = os.path.join(p, ".git")
    try:
        st = os.lstat(dot)
    except OSError:
        raise Refuse("bad", "цель — корень git-репозитория (в ней нет .git)") from None
    if stat.S_ISDIR(st.st_mode):
        gd = dot
    elif stat.S_ISREG(st.st_mode):
        m = re.fullmatch(r"gitdir: *(\S[^\n]*?)\s*", read_file(dot, 4096) or "")
        if not m:
            raise Refuse("bad", ".git — не строка gitdir")
        gd = os.path.realpath(os.path.join(p, m.group(1)))
    else:
        raise Refuse("bad", ".git — ссылка")
    common = gd
    if os.path.lexists(os.path.join(gd, "commondir")):
        cd = read_file(os.path.join(gd, "commondir"), 4096)
        if cd is None or not cd.strip():
            raise Refuse("bad", "commondir не читается")
        common = os.path.realpath(os.path.join(gd, cd.strip()))
    return gd, common


def config_keys(files, env, cwd):
    """{ключ: значение} config роли: байты — в частную копию, git читает только её (--no-includes). Ключ вне белого
    списка, файл-ссылка или чужой — отказ."""
    out = {}
    for f in files:
        if not os.path.lexists(f):
            continue
        data = read_file(f, CONFIG_MAX, raw=True)
        if data is None or len(data) > CONFIG_MAX:
            raise Refuse("bad", f"{os.path.basename(f)} репозитория — не обычный свой файл")
        copy = os.path.join(cwd, "role-config")
        with open(copy, "wb") as fh:
            fh.write(data)
        raw = run_git(["config", "--file", copy, "--list", "-z", "--no-includes"], env, cwd)
        os.unlink(copy)
        for item in raw.split(b"\0"):
            if item:
                k, _, v = item.decode("utf-8", "replace").partition("\n")
                if not GIT_KEYS_OK.fullmatch(k):
                    raise Refuse("bad", f"в git config ключ {k[:60]} вне белого списка — git у владельца здесь не "
                                        "запускаю")
                out[k.lower()] = v
    return out


@contextlib.contextmanager
def private_git(p):
    """Частный GIT_DIR для корня репозитория p (основная копия или worktree): {gd, common, env, dir}."""
    gd, common = git_dirs(p)
    base = state("handoff", "git")
    os.makedirs(base, mode=0o700, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="g-", dir=base)
    try:
        T = os.path.join(tmp, "gitdir")
        os.mkdir(T, 0o700)
        conf = os.path.join(T, "config")
        with open(conf, "w", encoding="utf-8") as fh:
            fh.write("[core]\n\trepositoryformatversion = 0\n\tbare = false\n")
        head = read_file(os.path.join(gd, "HEAD"), 4096, raw=True)
        if head is None:
            raise Refuse("bad", "HEAD репозитория не читается")
        with open(os.path.join(T, "HEAD"), "wb") as fh:
            fh.write(head)
        os.symlink(os.path.join(common, "refs"), os.path.join(T, "refs"))
        if os.path.lexists(os.path.join(common, "packed-refs")):
            os.symlink(os.path.join(common, "packed-refs"), os.path.join(T, "packed-refs"))
        env = git_env(T, GIT_OBJECT_DIRECTORY=os.path.join(common, "objects"))
        keys = config_keys(dict.fromkeys((os.path.join(common, "config"), os.path.join(common, "config.worktree"),
                                          os.path.join(gd, "config.worktree"))), env, tmp)
        with open(conf, "a", encoding="utf-8") as fh:
            for k in GIT_KEYS_COPY:
                if keys.get(k) in ("true", "false"):
                    fh.write(f"\t{k.split('.')[1]} = {keys[k]}\n")
        yield {"gd": gd, "common": common, "env": env, "dir": tmp}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def gitc(g, args):
    return run_git(args, g["env"], g["dir"]).decode("utf-8", "replace").strip()


def dirty(g, work):
    """После пальца: незакоммиченное и неотслеживаемое в рабочем дереве (status тем же частным GIT_DIR) → текст."""
    if os.path.lexists(os.path.join(work, ".gitmodules")):
        return ".gitmodules — подмодули не проверяю"
    env = dict(g["env"], GIT_WORK_TREE=work, GIT_INDEX_FILE=os.path.join(g["gd"], "index"))
    out = run_git(["status", "--porcelain", "--untracked-files=all", "--ignore-submodules=all"], env, work, 120)
    return out.decode("utf-8", "replace").strip()[:200] or None


def projects_root():
    return os.path.realpath(os.path.join(home(), "projects"))


def tilde(p):
    h = os.path.realpath(home())
    return "~" + p[len(h):] if p == h or p.startswith(h + "/") else p


def inside_projects(target):
    """Настоящий путь цели внутри ~/projects, не ссылка; иначе Refuse."""
    if not isinstance(target, str) or not target.startswith(("/", "~")):
        raise Refuse("bad", "цель — абсолютный путь")
    p = os.path.normpath(os.path.join(home(), target[2:]) if target.startswith("~/") else target)
    real = os.path.realpath(p)
    if real != p:
        raise Refuse("bad", "в пути цели есть ссылка или «..»: только настоящий путь")
    if not real.startswith(projects_root() + "/") or not os.path.isdir(real):
        raise Refuse("bad", "цель — папка внутри ~/projects")
    return real


def worktree_links(p, gd, common):
    """Связанная worktree: её gitdir — <common>/worktrees/<имя>, gitdir указывает обратно на p/.git, основная копия —
    папка над common; не заперта. Иначе Refuse."""
    if gd == common:
        raise Refuse("bad", "цель — основная копия, а не связанная worktree")
    if os.path.dirname(gd) != os.path.join(common, "worktrees"):
        raise Refuse("bad", "gitdir worktree лежит не в <репозиторий>/.git/worktrees")
    back = read_file(os.path.join(gd, "gitdir"), 4096)
    if back is None or os.path.realpath(back.strip()) != os.path.join(p, ".git"):
        raise Refuse("bad", "gitdir worktree не указывает обратно на неё")
    main = os.path.dirname(common)
    if os.path.basename(common) != ".git" or not os.path.isdir(main):
        raise Refuse("bad", "основная копия не найдена")
    if os.path.lexists(os.path.join(gd, "locked")):
        raise Refuse("yes", "worktree заперта (git worktree lock) — только «да» владельца словами")
    return main


def facts_worktree(target):
    """Удалить worktree «без своего»: связанная worktree, HEAD есть в ветке remote. Чистоту дерева проверяет
    exec_worktree после пальца (status до вопроса не запускается)."""
    p = inside_projects(target)
    with private_git(p) as g:
        main = worktree_links(p, g["gd"], g["common"])
        head = gitc(g, ["rev-parse", "--verify", "HEAD^{commit}"])
        remote = gitc(g, ["for-each-ref", "--contains", head, "--count=1", "--format=%(refname:short)",
                          "refs/remotes"])
        if not remote:
            raise Refuse("yes", "коммиты worktree есть только в ней — это не «без своего»: только «да» владельца словами")
        branch = gitc(g, ["rev-parse", "--abbrev-ref", "HEAD"])
        return {"path": p, "main": main, "gd": g["gd"], "head": head,
                "desc": f"удалить worktree {tilde(p)} (ветка {branch}, HEAD {head[:7]} есть в {remote}; "
                        "с незакоммиченным не удалю)"}


ORIGIN_REFS = "refs/remotes/origin/"


def merged_into(g, head):
    """Ветка по умолчанию origin, в которой есть head, — по уже известным ссылкам (без fetch). Ветка — цель
    refs/remotes/origin/HEAD, без неё — main, потом master. Цель origin/HEAD висит — git её не перечисляет, и ветка
    тоже main или master. Ссылки нет или head в ней нет — Refuse("merge")."""
    refs = {}
    for line in gitc(g, ["for-each-ref", "--format=%(refname) %(symref)", "refs/remotes/origin"]).splitlines():
        name, _, sym = line.partition(" ")
        refs[name] = sym
    sym = refs.get(ORIGIN_REFS + "HEAD") or ""
    if sym:
        base = sym[len(ORIGIN_REFS):] if sym.startswith(ORIGIN_REFS) else ""
    else:
        base = next((b for b in ("main", "master") if ORIGIN_REFS + b in refs), "")
    if not base:
        raise Refuse("merge", "нет ссылки origin на ветку по умолчанию (origin/HEAD, origin/main, origin/master) — не "
                              "видно, слит ли HEAD: deploy только слитого через шлюз")
    ref = ORIGIN_REFS + base
    if ref not in gitc(g, ["for-each-ref", "--contains", head, "--format=%(refname)", ref]).splitlines():
        raise Refuse("merge", f"HEAD {head[:7]} не слит в origin/{base} — deploy только слитого через шлюз: сначала "
                              "PR и слияние")
    return base


def facts_deploy(target):
    """Выкладка: основная копия (не worktree, не .claude/ и не кэш окна); HEAD слит в ветку по умолчанию origin
    (merged_into); deploy.sh — байты из коммита HEAD (`git cat-file blob`), обычный файл в дереве. Исполняются ровно
    они (exec_deploy, bash -s)."""
    p = inside_projects(target)
    if "/.claude/" in p + "/" or p.startswith(caches() + "/"):
        raise Refuse("bad", "deploy — не из папки .claude/ и не из кэша окна роли")
    with private_git(p) as g:
        if g["gd"] != g["common"]:
            raise Refuse("bad", "deploy — только из основной копии репозитория, не из worktree")
        head = gitc(g, ["rev-parse", "--verify", "HEAD^{commit}"])
        base = merged_into(g, head)
        tree = gitc(g, ["ls-tree", head, "--", "deploy.sh"])
        if not re.match(r"100(?:644|755) blob [0-9a-f]{40}\tdeploy\.sh$", tree):
            raise Refuse("bad", "в коммите HEAD нет deploy.sh обычным файлом")
        data = run_git(["cat-file", "blob", f"{head}:deploy.sh"], g["env"], g["dir"])
        if len(data) > SCRIPT_MAX:
            raise Refuse("bad", "deploy.sh больше 1 МБ")
        branch = gitc(g, ["rev-parse", "--abbrev-ref", "HEAD"])
    digest = hashlib.sha256(data).hexdigest()
    return {"path": p, "head": head, "script": digest, "bytes": data,
            "desc": f"выложить {tilde(p)}: deploy.sh {digest[:12]} из коммита, ветка {branch}, HEAD {head[:7]} есть "
                    f"в origin/{base}"}


CDP_PORTS = {"comet": 9333, "chrome": 9334}   # = browser.BROWSERS (сверяет test_handoff)


def facts_cdp(target):
    if target not in CDP_PORTS:
        raise Refuse("bad", f"демон — {' или '.join(CDP_PORTS)}")
    return {"browser": target, "port": CDP_PORTS[target],
            "desc": f"перезапустить демон CDP {target} (порт {CDP_PORTS[target]}); {target} спросит «Разрешить»"}


FACTS = {"worktree-remove": facts_worktree, "deploy": facts_deploy, "cdp-restart": facts_cdp}


def describe(req):
    """(текст окна, факты) по заявке: факты — живые, на момент вызова. Кто просит — окно по месту папки."""
    kind, target = req.get("kind"), req.get("target")
    bad = touch_refusal(kind, target, req.get("why") or "")
    if bad:
        raise bad
    facts = FACTS[kind](target)
    who = req.get("window") or "сессия владельца"
    role = f" ({req['role']} со слов заявки)" if req.get("role") else ""
    why = f" Зачем: {req['why']}." if req.get("why") else ""
    text = (f"{facts['desc'][0].upper()}{facts['desc'][1:]}. Просит {who}{role}, задача {req.get('task')}.{why} "
            "Палец разрешит только это действие, один раз.")
    if not showable(text):
        raise no_touch("unshowable", f" (текст окна {len(text)} знаков, предел {WINDOW_MAX})")
    return text, facts


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- исполнение после пальца -----------------------------------------------------------------------------------------

def exec_worktree(req, facts):
    """Факты только что собраны заново (process → describe): gitdir, commondir, config.worktree самой worktree
    проверены. Здесь — HEAD тот же и дерево чистое (status частным GIT_DIR), затем папка worktree и её gitdir
    удаляются (как `git worktree remove`, но без git с config роли)."""
    p = facts["path"]
    with private_git(p) as g:
        worktree_links(p, g["gd"], g["common"])
        if g["gd"] != facts["gd"] or gitc(g, ["rev-parse", "--verify", "HEAD^{commit}"]) != facts["head"]:
            raise Refuse("bad", "HEAD или gitdir worktree сменились после пальца")
        d = dirty(g, p)
        if d:
            raise Refuse("yes", f"в worktree есть своё ({d.splitlines()[0][:80]}) — не удаляю: только «да» словами")
        shutil.rmtree(p)
        shutil.rmtree(g["gd"], ignore_errors=True)
    return f"worktree {tilde(p)} удалена"


def exec_deploy(req, facts):
    """Дерево чистое до запуска, исполняются байты deploy.sh из коммита (хеш = показанный) через bash -s; после
    запуска дерево проверяется снова — изменения попадают в итог."""
    p = facts["path"]
    data = facts["bytes"]
    if hashlib.sha256(data).hexdigest() != facts["script"]:
        raise Refuse("bad", "байты deploy.sh не те, что показаны")
    with private_git(p) as g:
        if gitc(g, ["rev-parse", "--verify", "HEAD^{commit}"]) != facts["head"]:
            raise Refuse("bad", "HEAD сменился после пальца")
        d = dirty(g, p)
        if d:
            raise Refuse("yes", f"в репозитории незакоммиченное ({d.splitlines()[0][:80]}) — выкладка только с чистого "
                                "коммита")
    os.makedirs(state("handoff", "runs"), mode=0o700, exist_ok=True)
    out = state("handoff", "runs", f"{req['id']}.log")
    env = {"HOME": home(), "PATH": (P.run_env()["PATH"] if P is not None else SAFE_PATH), "LANG": "en_US.UTF-8"}
    with open(out, "a", encoding="utf-8") as fh:
        # ровно показанные байты из коммита через stdin (bash -s), а не файл с диска
        r = subprocess.run(["/bin/bash", "-s"], input=data, cwd=p, stdout=fh, stderr=subprocess.STDOUT,
                           timeout=DEPLOY_TIMEOUT, env=env)
    if r.returncode != 0:
        raise Refuse("bad", f"deploy.sh упал с кодом {r.returncode}, журнал {tilde(out)}")
    with private_git(p) as g:
        after = dirty(g, p)
    tail = f"; после выкладки дерево изменилось: {after.splitlines()[0][:80]}" if after else ""
    return f"deploy.sh прошёл, журнал {tilde(out)}{tail}"


def exec_cdp(req, facts):
    port, browser = facts["port"], facts["browser"]
    r = subprocess.run(["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True,
                       text=True, timeout=10)
    for pid in {int(x) for x in r.stdout.split() if x.isdigit()}:
        cmd = subprocess.run(["/bin/ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                             timeout=10).stdout
        if "cdp-daemon.mjs" not in cmd:
            raise Refuse("bad", f"порт {port} держит не демон CDP — не трогаю")
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and subprocess.run(
            ["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True,
            timeout=10).stdout.strip():
        time.sleep(0.5)
    B = P.browser_mod()
    with contextlib.suppress(OSError):
        os.unlink(B.root(f"start-{browser}"))          # отметка «запуск был недавно» — палец владельца её снимает
    try:
        B.ensure_daemon(browser, "Перезапуск демона по Touch ID владельца")
    except Exception as e:  # noqa: BLE001 — Fail браузера и сбой запуска — итог «не вышло»
        raise Refuse("bad", str(e)[:200]) from None
    return f"демон {browser} перезапущен"


EXEC = {"worktree-remove": exec_worktree, "deploy": exec_deploy, "cdp-restart": exec_cdp}


# --- заявки ----------------------------------------------------------------------------------------------------------

def err(text, code=2):
    print(text, file=sys.stderr)
    return code


def new_id():
    return datetime.fromtimestamp(now()).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)


def _is_dir(p):
    try:
        return stat.S_ISDIR(os.lstat(p).st_mode)
    except OSError:
        return False


def queue_dirs():
    """[(папка заявок, окно)]: окно None — очередь STATE, иначе имя окна по папке кэша (не из текста заявки)."""
    out = [(state("handoff", "queue"), None)]
    with contextlib.suppress(OSError):
        for name in sorted(os.listdir(caches())):
            d = os.path.join(caches(), name, "handoff")
            if WINDOW_RE.fullmatch(name) and _is_dir(d) and not os.path.islink(os.path.join(caches(), name)):
                out.append((d, name))
    return out


def read_file(path, limit=REQ_MAX, raw=False):
    """Обычный свой файл без ссылок → текст (raw — байты); иначе None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_size > limit:
            return None
        data = fh.read(limit + 1)
        return data if raw else data.decode("utf-8", "replace")


def load_req(path):
    raw = read_file(path)
    if raw is None:
        return None, None
    with contextlib.suppress(ValueError):
        req = json.loads(raw)
        if isinstance(req, dict) and ID_RE.fullmatch(str(req.get("id"))) and \
                os.path.basename(path) == f"{req['id']}.req.json":
            return req, raw
    return None, raw


def write_atomic(path, data):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, path)


def parse_opts(args, known, flags=()):
    pos, kv, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a in flags:
            kv[a] = True
        elif a in known:
            if i + 1 >= len(args) or a in kv:
                raise ValueError(f"{a}: нужно одно значение")
            kv[a] = args[i + 1]
            i += 1
        elif a.startswith("--"):
            raise ValueError(f"неизвестный флаг {a}")
        else:
            pos.append(a)
        i += 1
    return pos, kv


def who():
    role = os.environ.get("PANTHEON_ROLE") or ""
    win = None
    tmp = os.environ.get("PANTHEON_TMP")
    if tmp:
        win = os.path.basename(os.path.dirname(os.path.realpath(tmp)))
    return (win if win and WINDOW_RE.fullmatch(win) else None), (role if ROLE_RE.fullmatch(role) else None)


def cmd_route(args):
    try:
        pos, kv = parse_opts(args, ("--source", "--task"))
    except ValueError as e:
        return err(f"pantheon handoff route: {e}")
    text = " ".join(pos).strip()
    src = kv.get("--source", "role")
    if not text or src not in SOURCES:
        return err("вызов: pantheon handoff route [--source " + "|".join(SOURCES) + "] [--task ID] [--] <текст отказа>")
    key, _, outcome, _ = route(text)
    win, role = who()
    log(src, key, outcome, local=bool(os.environ.get("PANTHEON_TMP")), window=win, role=role, task=kv.get("--task"))
    print(hint(text, src))
    return 0


def cmd_touch(args):
    try:
        pos, kv = parse_opts(args, ("--task", "--why", "--wait"))
        wait = min(int(kv.get("--wait", "0")), WAIT_MAX)
        if wait < 0:
            raise ValueError("--wait: секунды, 0 и больше")
    except ValueError as e:
        return err(f"pantheon handoff touch: {e}")
    if len(pos) != 2 or not TASK_RE.fullmatch(kv.get("--task", "")):
        return err("вызов: pantheon handoff touch <вид> <цель> --task ID [--why \"зачем\"] [--wait С]; виды: "
                   + ", ".join(TOUCH_KINDS))
    win, role = who()
    req = {"id": new_id(), "kind": pos[0], "target": pos[1], "task": kv["--task"], "why": kv.get("--why", "").strip(),
           "role": role, "created": now()}
    in_window = bool(os.environ.get("PANTHEON_TMP"))
    try:
        if len(req["why"]) > WHY_MAX:
            raise no_touch("unshowable", f" («зачем» длиннее {WHY_MAX} знаков — короче)")
        text, _ = describe(dict(req, window=win))
    except Refuse as e:
        log("role", e.key, e.channel if e.channel in OUTCOME_RU else "refused", local=in_window, window=win,
            role=role, task=req["task"])
        print(f"pantheon handoff touch: отказ — {e}. {NO_TERMINAL}", file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError) as e:
        return err(f"pantheon handoff touch: факты не собрать ({type(e).__name__}: {e})")
    req["text"], req["sha"] = text, sha(text)
    d = own_dir()
    write_atomic(os.path.join(d, f"{req['id']}.req.json"), req)
    log("role", "touch", "waiting", local=in_window, window=win, role=role, task=req["task"], id=req["id"])
    print(f"заявка {req['id']}: владелец увидит окно Touch ID с текстом:\n  {text}\n"
          f"Итог — pantheon handoff status {req['id']}")
    if wait:
        return wait_result(d, req["id"], wait)
    return 0


def wait_result(d, rid, wait):
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        res = read_result(d, rid)
        if res and res.get("state") in FINAL:
            print(f"итог {rid}: {res['state']} — {res.get('note', '')}")
            return 0 if res["state"] == "done" else 1
        time.sleep(2)
    print(f"итога {rid} ещё нет — pantheon handoff status {rid}")
    return 75


def read_result(d, rid):
    raw = read_file(os.path.join(d, f"{rid}.result.json"))
    with contextlib.suppress(TypeError, ValueError):
        r = json.loads(raw)
        return r if isinstance(r, dict) else None
    return None


def cmd_status(args):
    rows = []
    for d, win in queue_dirs():
        with contextlib.suppress(OSError):
            for n in sorted(os.listdir(d)):
                m = re.fullmatch(r"(\d{8}-\d{6}-[0-9a-f]{6})\.(req|result)\.json", n)
                if not m or (args and m.group(1) != args[0]):
                    continue
                if m.group(2) == "req":
                    req, _ = load_req(os.path.join(d, n))
                    if req:
                        rows.append(f"{m.group(1)}  ждёт Touch ID  {win or 'владелец'}  {str(req.get('text'))[:160]}")
                else:
                    res = read_result(d, m.group(1)) or {}
                    rows.append(f"{m.group(1)}  {res.get('state')}  {win or 'владелец'}  {str(res.get('note'))[:160]}")
    print("\n".join(rows) if rows else "заявок нет")
    return 0


def cmd_cancel(args):
    if len(args) != 1 or not ID_RE.fullmatch(args[0]):
        return err("вызов: pantheon handoff cancel ID")
    p = os.path.join(own_dir(), f"{args[0]}.req.json")
    try:
        os.unlink(p)
    except OSError:
        return err(f"заявки {args[0]} в своей очереди нет", 1)
    print(f"заявка {args[0]} снята")
    return 0


# --- проход ----------------------------------------------------------------------------------------------------------

def ask(text):
    """Окно Touch ID — помощник слияния (lib/merge.py ask: 0 палец, 1 отказ, 2 не показать, 3 время, None нет)."""
    return P.merge_mod().ask(text)


def finish(d, req, st, note, outcome, win):
    write_atomic(os.path.join(d, f"{req['id']}.result.json"),
                 {"id": req["id"], "state": st, "note": str(note)[:400], "t": now()})
    log("role", "touch", outcome, window=win, role=req.get("role"), task=req.get("task"), id=req.get("id"))


def approve_line(req, digest):
    d = state("owner-log")
    if os.path.islink(d):
        raise OSError("owner-log — ссылка")
    os.makedirs(d, mode=0o700, exist_ok=True)
    line = (f"{datetime.fromtimestamp(now()).astimezone().isoformat(timespec='seconds')} handoff-approve "
            f"{req['id']} {digest}\n")
    fd = os.open(os.path.join(d, "handoff-approve.log"), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(line)


def retry_mark(req):
    return state("handoff", "retry", req["id"])


def ingest_logs():
    """Строки журнала отказов из кэшей окон → STATE (окно STATE не пишет)."""
    for d, win in queue_dirs()[1:]:
        p = os.path.join(d, "log.jsonl")
        taken = f"{p}.{os.getpid()}.taken"
        try:
            os.rename(p, taken)
        except OSError:
            continue
        raw = read_file(taken, limit=1024 * 1024) or ""
        with contextlib.suppress(OSError):
            os.unlink(taken)
        for ln in raw.splitlines():
            with contextlib.suppress(ValueError, TypeError):
                e = json.loads(ln)
                if isinstance(e, dict):
                    clean = entry(e.get("source"), e.get("kind"), e.get("outcome"), role=e.get("role"),
                                  task=e.get("task"), id=e.get("id"), window=win)   # окно — по месту, не из строки
                    clean["t"] = min(float(e.get("t", now())), now())
                    _append(log_path(), clean)


def process(d, win, name):
    path = os.path.join(d, name)
    req, raw = load_req(path)
    if req is None:
        with contextlib.suppress(OSError):
            os.unlink(path)
        return
    req["window"] = win
    if now() - float(req.get("created") or 0) > REQ_TTL:
        with contextlib.suppress(OSError):
            os.unlink(path)
        return finish(d, req, "dropped", f"заявка старше {REQ_TTL // 60} мин — снята, подай заново", "dropped", win)
    try:
        text, _ = describe(req)
    except Refuse as e:
        with contextlib.suppress(OSError):
            os.unlink(path)
        return finish(d, req, "refused", str(e), e.channel if e.channel in OUTCOME_RU else "refused", win)
    except (OSError, subprocess.SubprocessError) as e:
        with contextlib.suppress(OSError):
            os.unlink(path)
        return finish(d, req, "failed", f"факты не собрать: {type(e).__name__}", "failed", win)
    if text != req.get("text") or sha(text) != req.get("sha"):
        with contextlib.suppress(OSError):
            os.unlink(path)
        return finish(d, req, "dropped", "действие изменилось с заявки — подай новую заявку", "dropped", win)
    with contextlib.suppress(OSError):
        if now() - os.stat(retry_mark(req)).st_mtime < RETRY_SEC:
            return None
    if P.idle_sec() > PRESENT_SEC:
        return None
    shown = sha(text)
    code = ask(text)
    if code is None or code == 2:
        P.alert_once("handoff-window", str(code), "Touch ID для действий роли: окно не показать (помощника нет или "
                     "проход не в сессии владельца) — заявки ждут", "handoff")
        return None
    if code == 3:
        os.makedirs(os.path.dirname(retry_mark(req)), mode=0o700, exist_ok=True)
        with open(retry_mark(req), "w"):
            pass
        return None
    if code != 0:
        with contextlib.suppress(OSError):
            os.unlink(path)
        return finish(d, req, "declined", "владелец отказал в окне Touch ID", "declined", win)
    # палец: заявка та же (байты), факты те же (текст, его sha256 = показанный) — иначе новый вопрос
    req2, raw2 = load_req(path)
    if req2 is None or raw2 != raw:
        with contextlib.suppress(OSError):
            os.unlink(path)
        return finish(d, req, "dropped", "заявку сменили или сняли, пока окно было открыто — палец не засчитан",
                      "dropped", win)
    req2["window"] = win
    try:
        text2, facts = describe(req2)
    except (Refuse, OSError, subprocess.SubprocessError) as e:
        with contextlib.suppress(OSError):
            os.unlink(path)
        return finish(d, req, "dropped", f"изменилось после пальца — новый вопрос ({e})", "dropped", win)
    if sha(text2) != shown:
        with contextlib.suppress(OSError):
            os.unlink(path)
        return finish(d, req, "dropped", "действие изменилось после пальца — новый вопрос", "dropped", win)
    taken = f"{path}.taken"
    try:
        os.rename(path, taken)   # одно применение: второй проход эту заявку уже не найдёт
    except OSError:
        return None
    try:
        approve_line(req2, shown)
        note = EXEC[req2["kind"]](req2, facts)
        finish(d, req2, "done", note, "done", win)
    except Refuse as e:
        finish(d, req2, "failed", str(e), "failed", win)
    except Exception as e:  # noqa: BLE001 — сбой исполнителя — итог роли, проход идёт дальше
        finish(d, req2, "failed", f"{type(e).__name__}: {e}"[:300], "failed", win)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(taken)
    return None


def sweep(d):
    with contextlib.suppress(OSError):
        for n in os.listdir(d):
            if n.endswith(".result.json"):
                p = os.path.join(d, n)
                with contextlib.suppress(OSError):
                    if now() - os.lstat(p).st_mtime > RESULT_TTL:
                        os.unlink(p)


def pending():
    """Есть дело для прохода: заявка или строки журнала в кэше окна."""
    for d, win in queue_dirs():
        with contextlib.suppress(OSError):
            for n in os.listdir(d):
                if n.endswith(".req.json") or (win and n == "log.jsonl"):
                    return True
    return False


def cmd_run():
    if "CLAUDECODE" in os.environ or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        return err("pantheon handoff run: только плановый проход, не из окна Claude Code")
    with P.lock("handoff-run", block=False) as got:
        if not got:
            return 0
        ingest_logs()
        for d, win in queue_dirs():
            try:
                names = sorted(n for n in os.listdir(d) if n.endswith(".req.json"))
            except OSError:
                continue
            for n in names:
                try:
                    process(d, win, n)
                except Exception as e:  # noqa: BLE001 — одна заявка не останавливает остальные
                    P.alert_once("handoff-run", type(e).__name__, f"handoff: заявка {n} — {type(e).__name__}: {e}",
                                 "handoff")
            sweep(d)
    return 0


USAGE = ("pantheon handoff route [--source S] [--task ID] [--] <текст отказа> | touch <вид> <цель> --task ID "
         "[--why …] [--wait С] | status [ID] | cancel ID | run")


def main(rest):
    if not rest:
        return err(USAGE)
    cmd, args = rest[0], rest[1:]
    if cmd == "route":
        return cmd_route(args)
    if cmd == "touch":
        return cmd_touch(args)
    if cmd == "status":
        return cmd_status(args)
    if cmd == "cancel":
        return cmd_cancel(args)
    if cmd == "run" and not args:
        return cmd_run()
    return err(USAGE)
