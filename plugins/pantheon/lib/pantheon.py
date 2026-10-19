#!/usr/bin/env python3
"""Пантеон: планировщик pantheon-tick и команда pantheon.

Всё, что Пантеон делает сам по времени, идёт через одну задачу launchd `pantheon-tick` (раз в 60 с).
Список задач — ~/ai/pantheon/schedule.toml (правит Пританей); метки запусков — ~/.local/state/pantheon/
(свои у каждого Mac). Что пора запускать, плановый проход решает по меткам, а не по часам: пропуски за сон Mac
сливаются в один запуск. Лёгкие задачи (копия, коммит, дежурный) идут сразу; тяжёлые — по одной,
с паузой, не в первые минуты после пробуждения, от сети, а задачи на Claude — ещё при простое и
свободном пятичасовом лимите; предел ожидания max_delay снимает эти условия. Задачи с
hosts = "primary" идут только на главном Mac (primary_host).

Команды:
  pantheon jobs                         что установлено, когда шло, что дальше и почему ждёт
  pantheon jobs pause|resume|disable|enable <задача>   (--all — весь планировщик)
  pantheon jobs renew <задача> [дней]   продлить аренду задачи
                                        (службы [[service]] — те же pause|resume|disable|enable: launchd снимается сразу)
  pantheon qmd config|update|embed|serve|install|status   общий поиск qmd: index.yml из ~/ai/pantheon/qmd.toml,
                                        освежить индекс, сервер MCP (служба), подключить к Claude на этом Mac
  pantheon plugins update [--quiet]     новые версии плагинов agent-kit (плановый проход раз в 10 мин): тесты новой и
                                        установленной версии; нет новых падений — claude plugin update, есть — тревога;
                                        после установки плановый проход перезапускает свободные окна (metis-0181)
  pantheon direction check <имя>        что готово у нового направления (навык new-direction): реестр, «да»,
                                        папки, STATUS.md, domains.json, AGENTS.md, доверие, autoMode
  pantheon direction init <имя>         папка ~/projects/<имя> по вашей галочке: git init, AGENTS.md, локальный
                                        коммит; без remote
  pantheon instructions [--quiet]       дойдут ли инструкции целиком: Codex (лимит на путь), MEMORY.md
                                        (200 строк / 25 КБ), CLAUDE.md с импортами длиннее 200 строк
  pantheon alert "<строка>" [--from кто] [--critical]   дописать строку в ~/ai/pantheon/alerts.md
                                          (--critical — ещё и уведомление macOS: COMM-08)
  pantheon archive                      «Сделано» доски старше 7 дней и тревоги старше 30 — в archive/
  pantheon domains build                ~/ai/pantheon/directions.toml → ~/.local/state/pantheon/domains.json
                                        и настройки окон ролей с песочницей …/settings/<направление>.json
  pantheon view [--quiet]               обновить копию ~/ai/pantheon-view для Obsidian
  pantheon board                        доска владельца ~/ai/pantheon-view/Доска: карточки, ваши ходы, сводка
  pantheon status                       один экран для отладки: плановый проход, сессии, вопросы к вам, тревоги, защиты, sync, места heavy, версии
  pantheon night [status|report]        недельный лимит: неделя, линия, запас, зона, ночь, снимок; report — блок
                                        «Лимит» для сводки (вечерний вопрос и ночь ведёт дежурный, lib/night.py)
  pantheon read request|run|status|cancel   чтение личного чата по заявке (metis-0267, lib/read.py): заявка → ваше
                                        «да» на [read-<rid>] → выгрузка и разбор плановым проходом → вы одобряете пункты
  pantheon mmv [--days N]               минуты владельца на систему по дням (по меткам owner-log) → STATE/mmv.jsonl
  pantheon sync-answers                 ваш ответ на доске по карантину ~/.claude — применить сразу (sync.sh), без новой сессии
  pantheon check [файл…]                проверить шапки задач по схеме v1 (schema.md)
  pantheon task new --direction D --title T [--type task|story --status S --priority N --due ГГГГ-ММ-ДД[TЧЧ:ММ]
                    --next X --owner O --release R --batch X --night ГГГГ-ММ-ДД --estimate X --actual X
                    --acceptance принято|вернуть|к владельцу --mode self|single|parallel --mode-why X --touches ПУТЬ …
                    --project P --waiting-on W --question Q --why W --option "А — … Цена: …" --option …
                    --recommend "А — потому что …" --if-no-answer "…" --depends-on ID --executor auto|claude|codex]
                    без --owner «Кому» — координатор направления; owner= (пусто) в task set — отказ;
                    --batch без --mode (и без mode в шапке) — отказ: режим обязателен при сборке пачки (metis-0308)
  pantheon task set ID поле=значение … [--option "вариант" …] [--note "строка в журнал"]   pantheon task show ID
  pantheon task ready [--direction D] [--owner O]   pantheon task claim ID --by КТО [--hours 1]
  pantheon task migrate-batches [--dry-run]   поле batch «имя · место» → пачка (story) «имя», задача прикреплена по месту
  pantheon task attach ID ПАЧКА | detach ID   задача в пачку (story) и обратно; show ПАЧКА — состав и сумма оценок
  pantheon executors                    набор исполнителей кода (Claude всегда, Codex — дополнение) и включён ли Codex
  pantheon executors check              проверить Codex: на PATH → вход (CODEX_HOME роли) → hello-проба
  pantheon executors --add codex | --remove <имя>   добавить Codex (через проверку, без входа) | убрать (Claude — отказ)
  pantheon executors pick <id задачи> [--kind mechanics|code|hard]   кто пишет задачу: dev-* или codex-dev
  pantheon exec codex <worktree> <файл поручения>   запуск Codex для codex-dev: среда без секретов, монитор тишины,
                                        защищённые пути, коммит с трейлером Executor: codex; push — никогда
  pantheon start <направление> [поручение]   координатор: фоновая сессия domain-coordinator в окне направления
  pantheon start workshop <задача> [поручение]   мастерская: daedalus-<задача> в ~/projects/workshop/<задача>
  pantheon start zeus                   Пританей: ваша сессия hq в ~/ai/pantheon с окном hq.json   (--from zeus|tick|owner)
  pantheon start <направление> --at ЧЧ:ММ [поручение]   разовый запуск плановым проходом вместо sleep в сессии;
                                        --at-list — записи, --at-cancel <id> — отменить (lib/night.py)
  pantheon wake [--dry-run]             поднять прерванные сессии Пантеона с открытой задачей и сказать «продолжай»
  pantheon watch [--dry-run]            дежурный (плановый проход раз в 5 мин): сессии, STATUS.md, swap, worktree, версия Claude Code,
                                        паузы, самозапуск по вашим решениям; --dry-run — кого поднял бы и почему нет
  pantheon reboot-reminder [--now]      пятница после 09:30: Mac не перезагружался с прошлой пятницы — карточка и уведомление
  pantheon agents | who                 снимок claude agents для строки статуса | таблица координаторов
  pantheon revisits                     пересмотры к сроку и по событиям (плановый проход раз в сутки)
  pantheon wake <имя> ["задание"]        поднять уснувшую сессию направления той же сессией
  pantheon wake hestia --task <id>      Гестия: всегда отказ (код 2) — окно песочницы появится в metis-0245
  pantheon stop <имя>|--all, resume <имя>|--all   остановить (метка «остановлено вами», claude stop и claude rm —
                                        сессия уходит из фоновых сессий Claude Code) и вернуть
  pantheon pause <имя>|--all --reason limit|swap|manual ["почему"], pause --off [<имя>|--all]   пауза по нагрузке
  pantheon restart --prepare [причина]|--status|--go [--force]|--cancel   технический перезапуск всех сессий
  pantheon saved --by <имя> --state <путь>   сессия сохранилась перед техперезапуском; без техперезапуска —
                                        метка «можно» для перезапуска после обновления плагинов
  pantheon infra-check                  опоры системы после обновления Claude Code
  pantheon usage [дней]                 отчёт расхода в ~/ai/pantheon/metrics/usage/ (плановый проход раз в неделю)
  pantheon metrics sync|summary|run     учёт по задачам: строки закрытых задач в ~/ai/pantheon/metrics/tasks.jsonl
                                        (пишет и `task set status=done|dropped`), свод недели — week-<неделя>.md
                                        и заметки Пульта; summary — свод в окно
  pantheon metrics backfill --from ГГГГ-ММ-ДД [--to ГГГГ-ММ-ДД] [--dry-run]   задним числом: строки закрытых за
                                        эти дни задач с пометкой «оценка» (у кого строки нет)
  pantheon roles build                  роли ~/.claude/agents/*.md из общих шаблонов плагина (roles/*.tmpl,
                                        roles/_parts/*.part) и личного слоя ~/.claude/agents (*.tmpl, _parts/*.part
                                        перекрывают общие по имени); подстановки — из [person] directions.toml
  pantheon roles build --out <папка> [--src <папка шаблонов>]   проба: собрать роли в --out, личный слой — из
                                        --src (по умолчанию ~/.claude/agents) поверх общего; живые роли не трогает,
                                        сигналов нет; --out в ~/.claude/agents или внутри — отказ (код 2)
  pantheon role propose <имя> --direction D   заявка на личную роль (metis-0262): черновик ~/ai/pantheon/roles/
                                        proposed/<имя>.tmpl → карточка «Применить роль <имя> [<sha256>]?» Да/Нет,
                                        статус proposed в ~/.local/state/pantheon/roles/status.jsonl
  pantheon role apply <имя>             поставить роль по вашей галочке «Да» (журнал доски, ≤ 14 дней, на карточке
                                        заявки, тот же полный sha256 черновика): имя не общей роли и не лида, ≤ 5 КБ,
                                        без hooks/settings/mcpServers/permissionMode и повторов ключей в шапке →
                                        пробная сборка, шапка собранной роли сверяется так же → <имя>.tmpl в
                                        ~/.claude/agents → roles build; плановый проход делает это сам, «Нет» — rejected
  pantheon role status [<имя>] | cancel <имя>   заявки на роли | отозвать открытую заявку
  pantheon approve [list] | add --site S --allow "…" [--limits "…"] | remove N   заранее разрешённое (только вы)
  pantheon consent <id> [--days N]      ваш ответ Зевсу на вопрос <id> (журнал owner-log Зевса, по умолчанию 7 дней) —
                                        для исполнителя: согласие, данное в окне Зевса
  pantheon review test -- <команда…>    тесты для шлюза слияния (guard 0.5.9): в чистом дереве git запустить
                                        команду (без оболочки); HEAD и дерево после неё те же — выход с её кодом
                                        и SHA; запись в журнал делает хук guard (PostToolUse), сама команда не пишет;
                                        пустая программа (true, echo, heavy :…) записи не даёт
  pantheon review accept <owner/repo> <PR> <SHA> --opened "<что открыл>" --ran "<что запустил>"
                                        --unchecked "<что не проверял>"   «принять» argus с перечнем проверенного
                                        (без трёх полей шлюз не пускает); reject — те же флаги по желанию;
                                        talos <owner/repo> <PR> <SHA> — проверка talos. Команда проверяет формат,
                                        запись — хук guard и только по роли (accept, reject — argus). Шлюз считает
                                        последний вердикт каждого рецензента (сессия + агент) на (repo, PR, SHA) и
                                        пускает, только если последний у каждого — «принять» с полным перечнем и ни
                                        один рецензент не сливающий
  pantheon review begin <owner/repo> <PR> <SHA 40 знаков>   метка «ревью идёт» (argus позван, вердикта нет), чтобы
                                        второго argus не звали одновременно. Пишет только
                                        STATE/review-pending/<owner>__<repo>__<PR>.json; это НЕ вердикт и НЕ согласие,
                                        шлюз её не читает. Гаснет по вердикту (accept/reject) на этот PR и через 2 часа
  pantheon review status [<owner/repo> <PR>]   записи журнала ~/.local/state/pantheon/merge-gate/records.jsonl и
                                        метки «ревью идёт»
  pantheon commit                       commit → pull без rebase → push ~/ai/pantheon
  pantheon install | uninstall          поставить или снять задачу launchd pantheon.tick
  pantheon tick                         один проход планировщика (его вызывает launchd)
Уведомления (lib/notify.py): присутствие по простою, тихие часы, утренний дайджест, повтор и «долго ждёт», склейка
по id решения, бюджет в день; пороги — таблица [notify] в schedule.toml, состояние и журнал — notify.json и
notify-log.jsonl в ~/.local/state/pantheon/.
Для синтетических тестов: PANTHEON_HOME, PANTHEON_STATE, PANTHEON_NOW — «сейчас», PANTHEON_HOST,
PANTHEON_FAKE_WAKE, PANTHEON_FAKE_AC, PANTHEON_FAKE_IDLE — простой в секундах, PANTHEON_FAKE_LIMIT, PANTHEON_DRYRUN,
PANTHEON_NO_NOTIFY — без уведомлений, PANTHEON_NOTIFY_LOG — уведомления строкой «заголовок|текст|ссылка|группа» в файл.
Тест или проба (PANTHEON_TEST или папка состояния не настоящая) на экран уведомлений не шлёт: они идут строкой
в STATE/notify-test.log (metis-0307).
"""
import collections
import contextlib
import fcntl
import fnmatch
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta

if sys.version_info < (3, 11):
    sys.exit("pantheon: нужен Python 3.11+ (здесь %d.%d, нет tomllib)" % sys.version_info[:2])
import tomllib

HOME = os.path.expanduser("~")
AI_HOME = os.path.join(HOME, "ai")  # рабочие папки системы: pantheon, pantheon-view, knowledge (переезд 14.10)
PANTHEON = os.path.realpath(os.environ.get("PANTHEON_HOME") or os.path.join(AI_HOME, "pantheon"))
STATE = os.path.realpath(os.environ.get("PANTHEON_STATE") or os.path.join(HOME, ".local", "state", "pantheon"))
VIEW = os.environ.get("PANTHEON_VIEW") or os.path.join(AI_HOME, "pantheon-view")
VIEW_INBOX = os.environ.get("PANTHEON_VIEW_INBOX") or os.path.join(PANTHEON, "inbox-view")
LIB = os.path.dirname(os.path.realpath(__file__))
PLUGIN = os.path.dirname(LIB)
LABEL = "pantheon.tick"
# Неизменный путь к плагину: на него смотрят задача launchd, команда ~/.local/bin/pantheon и обработчики слияния
# в ~/ai/pantheon/.git/config. `pantheon install` перевешивает ссылку на ту копию плагина, из которой запущен
# (до шага 0.4 — рабочая копия agent-kit, с 0.4 — клон маркетплейса), поэтому обновление плагина путей не ломает.
CURRENT = os.path.join(HOME, ".local", "share", "pantheon", "current")
TEMPFAIL = 75   # задача ждёт (нет сети): не сбой, тревоги нет
ALERTED = 76    # сбой, о котором задача уже сообщила сама: вторую тревогу не давать
PLIST = os.path.join(HOME, "Library", "LaunchAgents", LABEL + ".plist")
LIMIT_SNAPSHOT = os.path.join(HOME, ".local", "state", "claude-statusline", "five-hour")
DEFAULTS = {"heavy_gap_min": 2, "wake_quiet_min": 10, "idle_min": 10, "limit_max_pct": 70}
# Подъём свежей сессией вместо продолжения (metis-0147 п. 2, «да» владельца 16.10): контекст больше FRESH_CTX и простой
# с последнего хода дольше FRESH_IDLE_MIN — кэш подсказок давно остыл, и respawn/--resume перечитал бы весь контекст по
# полной цене. Тогда — новая сессия с тем же именем и окном, которая читает файл состояния (fresh_start).
FRESH_CTX = 100_000
FRESH_IDLE_MIN = 60


# --- общее --------------------------------------------------------------------

def now():
    return float(os.environ.get("PANTHEON_NOW") or time.time())


def stamp(t=None):
    return datetime.fromtimestamp(t if t is not None else now()).strftime("%Y-%m-%d %H:%M")


_HOST = None


def host():
    """Имя Mac — LocalHostName (не меняется от сети, в отличие от имени ядра)."""
    global _HOST
    if os.environ.get("PANTHEON_HOST"):
        return os.environ["PANTHEON_HOST"]
    if _HOST is None:
        out = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True).stdout.strip()
        _HOST = out or socket.gethostname().split(".")[0]
    return _HOST


def path(*parts):
    return os.path.join(STATE, *parts)


@contextlib.contextmanager
def lock(name, block=True):
    """flock на файле в ~/.local/state/pantheon/locks/. Отдаёт True, если блокировка взята."""
    try:
        os.makedirs(path("locks"), exist_ok=True)
        fh = open(path("locks", name + ".lock"), "a")
    except PermissionError as e:
        # окно Зевса не пишет в locks/ (metis-0078): ждущую блокировку имени сессии pantheon stop берёт, чтобы подъём,
        # начатый до метки «остановлено», не проскочил после неё. Без права записи метка stopped/<имя> всё равно
        # ставится первой, а проскочить может только подъём, уже прошедший проверку метки в ту же секунду, — stop
        # идёт без блокировки с предупреждением. Замок alerts — тоже: строка тревоги дописывается одним write в режиме
        # append, она не рвётся. Неблокирующие замки (start, тик) и git без файла не берутся.
        if not (block and (name.startswith("start-") or name == "alerts")):
            raise
        print(f"pantheon: нет права записи в {path('locks').replace(HOME, '~')} ({e.strerror}) — работаю без "
              f"блокировки {name}: подъём этой же сессии в ту же секунду может проскочить", file=sys.stderr)
        yield True
        return
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | (0 if block else fcntl.LOCK_NB))
        got = True
    except BlockingIOError:
        got = False
    try:
        yield got
    finally:
        if got:
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def locked(name):
    with lock(name, block=False) as got:
        return not got


def read_json(p, default=None):
    try:
        with open(p) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {} if default is None else default


def write_json(p, data):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}"
    with open(tmp, "w") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _job_name(name):
    if not JOB_NAME.fullmatch(str(name)):
        raise ValueError(f"имя задачи не по образцу: {name!r}")
    return name


def job_state(name):
    return read_json(path("jobs", _job_name(name) + ".json"))


def save_job_state(name, st):
    write_json(path("jobs", _job_name(name) + ".json"), st)


def load_schedule():
    """schedule.toml; задачи с именем не по образцу [a-z0-9-] отбрасываются (имя идёт в пути меток и блокировок)."""
    p = os.path.join(PANTHEON, "schedule.toml")
    with open(p, "rb") as fh:
        sched = tomllib.load(fh)
    sched["defaults"] = {**DEFAULTS, **(sched.get("defaults") or {})}
    sched["notify"] = notify_mod().settings(sched.get("notify"))
    jobs = []
    for j in sched.get("job") or []:
        if isinstance(j, dict) and JOB_NAME.fullmatch(str(j.get("name", ""))):
            jobs.append(j)
        else:
            sched.setdefault("bad_names", []).append(str(j.get("name") if isinstance(j, dict) else j))
    sched["job"] = jobs
    # Службы (SCHED-05): постоянные процессы под launchd с KeepAlive — имена общие с задачами (одна метка состояния)
    services, names = [], {j["name"] for j in jobs}
    for s in sched.get("service") or []:
        if isinstance(s, dict) and JOB_NAME.fullmatch(str(s.get("name", ""))) and s["name"] not in names:
            services.append(s)
            names.add(s["name"])
        else:
            sched.setdefault("bad_names", []).append(str(s.get("name") if isinstance(s, dict) else s))
    sched["service"] = services
    return sched


def run_env():
    env = dict(os.environ)
    extra = [os.path.join(PLUGIN, "bin"), os.path.dirname(sys.executable), "/opt/homebrew/bin",
             os.path.join(HOME, ".local", "bin")]
    env["PATH"] = ":".join(extra + [env.get("PATH") or "/usr/bin:/bin:/usr/sbin:/sbin"])
    env["PANTHEON_PYTHON"] = sys.executable  # bin/pantheon дочерних задач берёт тот же интерпретатор (lib/find-python.sh)
    return env


def alert(text, who="pantheon"):
    """Строка в ~/ai/pantheon/alerts.md: время · кто · что. Файл только дописывается."""
    text, who = " ".join(str(text).split()), " ".join(str(who).split()) or "pantheon"
    if os.environ.get("PANTHEON_DRYRUN") == "1" and not os.environ.get("PANTHEON_ALERTS_IN_DRYRUN"):
        print(f"[alert] {who} · {text}")
        return
    p = os.path.join(PANTHEON, "alerts.md")
    with lock("alerts"):
        new = not os.path.exists(p)
        with open(p, "a", encoding="utf-8") as fh:
            if new:
                fh.write("# Тревоги\n\nТолько дописывание: `pantheon alert`. Строка — время · кто · что. "
                         "В «ждёт вас» на доске переносит Пританей; старше 30 дней уносит `pantheon archive`.\n\n")
            fh.write(f"{stamp()} · {who} · {text}\n")


def alert_once(key, value, text, who="pantheon", note=None, group=None, policy=None, critical=False):
    """Тревога (и уведомление note — сбой класса «скоро», через политику уведомлений) один раз на значение value:
    повтор того же состояния молчит. group — вид уведомления: новое того же вида заменяет прежнее в Центре
    уведомлений и считается тем же сбоем для повтора (по умолчанию — ключ тревоги). policy — политика, уже взятая
    под lock("notify") (проход доски), иначе берётся своя. critical — класс COMM-08 (подделка журнала ваших слов и
    т. п.): уведомление сразу, и ночью, и когда вы у Mac — в счёт бюджета и в журнал."""
    mark = once_path(key)
    try:
        if open(mark).read() == str(value):
            return
    except OSError:
        pass
    alert(text, who)
    if note and critical:
        notify_critical(note, group=group or key, policy=policy)
    elif note:
        notify_soon(key, note, group=group or key, policy=policy)
    os.makedirs(path("once"), exist_ok=True)
    open(mark, "w").write(str(value))


def once_path(key):
    safe = re.sub(r"[^\w.-]", "_", key)[:60]
    return path("once", f"{safe}-{hashlib.sha1(key.encode()).hexdigest()[:8]}")


def clear_once(key):
    with contextlib.suppress(FileNotFoundError):
        os.remove(once_path(key))


JOB_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
# Подкоманды pantheon, которые может запускать тик. Пульт (install, uninstall, jobs, run-job, tick, archive) — нет.
TICK_SUBCOMMANDS = {"view", "commit", "domains", "watch", "revisits", "scout", "board", "sync-answers", "check",
                    "instructions", "agents", "usage", "qmd", "plugins", "reboot-reminder", "read"}
CLAUDE_VALUE_FLAGS = {"--agent", "--model", "--max-turns", "--name"}
# Окна задач расписания (P0-3, metis-0063): `claude -p --agent <роль>` из schedule.toml идёт с песочницей
# settings/job-<роль>.json (собирает sandbox_build), а не без неё. Роль вне таблицы тик не запускает. write — куда
# пишет Bash роли (сверх памяти ролей и своей папки кэша); model — модель задачи вместо любой из команды: у iris в
# шапке haiku, а задаче разведчика нужен sonnet. agents — субагенты, которых роль задачи зовёт по своему шаблону
# (хук agents.py, как у штаба и координаторов, P0-6): шаблоны clio, prometheus и iris субагентов не зовут — пусто.
JOB_ROLES = {
    "clio": {"write": [os.path.join(AI_HOME, "knowledge")], "agents": []},
    "prometheus": {"write": [os.path.join(AI_HOME, "knowledge")], "agents": []},
    "iris": {"write": [os.path.join(PANTHEON, "scout")], "model": "sonnet", "agents": []},
}
JOB_EXCLUDED = ["pantheon alert *"]
# Пустой список agents.py считает сбоем и закрывает всё, и навыки без context: fork тоже (у clio — claude-md-improver).
# Поэтому пустое окно задачи получает имя-заглушку: такого субагента нет, Agent любого типа и навык-fork — отказ, а
# обычный навык идёт. Оно же — в тексте отказа («Этому окну можно: никого»)
JOB_NO_AGENTS = "никого"
# Встроенные типы Claude Code — в deny окна задачи вместе с ролями из ~/.claude/agents и лидами реестра
BUILTIN_AGENTS = ["general-purpose", "claude", "Explore", "Plan", "statusline-setup", "claude-code-guide"]


def job_window(role):
    return path("settings", f"job-{role}.json")


def job_window_problem(argv):
    """Окно песочницы задачи `claude -p` (P0-3): None — обычный файл на месте или задача не claude; иначе причина."""
    if not argv or argv[0] != "claude":
        return None
    if "--settings" not in argv[:-1]:
        return "нет окна песочницы (--settings)"
    p = argv[argv.index("--settings") + 1]
    try:
        st = os.lstat(p)
    except OSError:
        return f"нет окна песочницы {p.replace(HOME, '~')}"
    if not stat.S_ISREG(st.st_mode):
        return f"окно песочницы {p.replace(HOME, '~')} — не обычный файл"
    return None


def parse_command(cmd):
    """Команда задачи из schedule.toml → argv без оболочки, или None (задача не идёт). Разрешено только:
      pantheon <view|commit|domains|watch|revisits|scout|board|sync-answers|…> [аргументы без спецсимволов];
      claude -p --agent <роль> [--model M] [--max-turns N] [--name N] "<поручение>" — без флагов прав и настроек,
        роль — из JOB_ROLES; argv получает --settings <окно задачи роли> (и --model из таблицы, если он там есть);
      скрипт из bin/ или scripts/ самого плагина."""
    if not isinstance(cmd, str) or re.search(r"[;&|`$<>\n\\]", cmd):
        return None
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None
    if not argv:
        return None
    if argv[0] == "pantheon":
        if len(argv) < 2 or argv[1] not in TICK_SUBCOMMANDS:
            return None
        if argv[1] == "qmd" and argv[2:3] not in (["update"], ["embed"], ["serve"]):
            return None  # install (claude mcp add уровня пользователя) и прочее — только руками
        if argv[1] == "plugins" and (argv[2:3] != ["update"] or any(a != "--quiet" for a in argv[3:])):
            return None
        if argv[1] == "read" and argv[2:] != ["run"]:
            return None  # заявку подаёт окно, а не задача прохода; проход — только `read run`
        return [os.path.join(PLUGIN, "bin", "pantheon")] + argv[1:]
    if argv[0] == "claude":
        if argv[1:2] != ["-p"]:
            return None
        seen, j = {}, 2
        while j < len(argv) - 1:
            flag = argv[j]
            if flag not in CLAUDE_VALUE_FLAGS or flag in seen or argv[j + 1].startswith("-"):
                return None
            seen[flag] = argv[j + 1]
            j += 2
        if j != len(argv) - 1 or argv[-1].startswith("-") or not JOB_NAME.fullmatch(seen.get("--agent", "")):
            return None
        conf = JOB_ROLES.get(seen["--agent"])
        if conf is None:
            return None  # роль без окна задачи — без песочницы не идёт (P0-3)
        if conf.get("model"):
            seen["--model"] = conf["model"]
        out = ["claude", "-p", "--settings", job_window(seen["--agent"])]
        for flag, value in seen.items():
            out += [flag, value]
        return out + [argv[-1]]
    real = os.path.realpath(os.path.expanduser(argv[0]))
    if any(real.startswith(os.path.join(PLUGIN, d) + os.sep) for d in ("bin", "scripts")):
        return [real] + argv[1:]
    return None


APP = os.path.join(HOME, "Applications", "Доска.app")


def board_url(name="Доска.base"):
    from urllib.parse import quote
    return f"obsidian://open?vault={quote(os.path.basename(VIEW))}&file={quote('Доска/' + name)}"


def _notifier():
    for c in ("/opt/homebrew/bin/terminal-notifier", "/usr/local/bin/terminal-notifier"):
        if os.path.exists(c):
            return c
    return None


def notify_offscreen():
    """Уведомление не для экрана: признак теста PANTHEON_TEST или папка состояния — не настоящая (временный
    PANTHEON_STATE или временный HOME). Настоящая — ~/.local/state/pantheon домашней папки владельца из учётной
    записи, а не из HOME: тесты подменяют HOME. Так тест, забывший PANTHEON_NOTIFY_LOG, не покажет владельцу
    ложную тревогу (metis-0307: «push не проходит» и «давно не синхронизируется» из test_commit_push)."""
    if os.environ.get("PANTHEON_TEST"):
        return True
    import pwd
    try:
        owner_home = pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, OSError):
        return True
    real = os.path.realpath(os.path.join(owner_home, ".local", "state", "pantheon"))
    cur = os.path.realpath(os.environ.get("PANTHEON_STATE") or
                           os.path.join(os.path.expanduser("~"), ".local", "state", "pantheon"))
    return STATE != real or cur != real


def notify(text, title="Пантеон", target=None, group=None):
    """Уведомление macOS. Через terminal-notifier 3 (UserNotifications): щелчок открывает target — карточку или доску,
    group заменяет прежнее уведомление о том же. Без него — обычное уведомление без перехода."""
    if os.environ.get("PANTHEON_NOTIFY_LOG"):  # для тестов: что и куда ушло бы
        with open(os.environ["PANTHEON_NOTIFY_LOG"], "a", encoding="utf-8") as fh:
            fh.write(f"{title}|{text}|{target or ''}|{group or ''}\n")
        return
    if os.environ.get("PANTHEON_NO_NOTIFY") or os.environ.get("PANTHEON_DRYRUN") == "1":
        return
    text = " ".join(str(text).split())
    if notify_offscreen():  # тест или проба: на экран владельца — никогда, только в файл (metis-0307)
        with contextlib.suppress(OSError):
            os.makedirs(STATE, exist_ok=True)
            with open(os.path.join(STATE, "notify-test.log"), "a", encoding="utf-8") as fh:
                fh.write(f"{title}|{text}|{target or ''}|{group or ''}\n")
        return
    tn = _notifier()
    if tn:
        args = [tn, "-title", title, "-message", text, "-open", target or board_url()]
        if group:
            args += ["-group", "pantheon-" + re.sub(r"[^\w.-]", "_", group)[:60]]
        r = subprocess.run(args, capture_output=True, timeout=15)
        if r.returncode == 0:
            return
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(["osascript", "-e", f'display notification "{esc(text)}" with title "{esc(title)}"'],
                   capture_output=True, timeout=10)


# --- состояние Mac: пробуждение, питание, простой, лимит ------------------------

def wake_time():
    if os.environ.get("PANTHEON_FAKE_WAKE"):
        return float(os.environ["PANTHEON_FAKE_WAKE"])
    best = 0.0
    for key in ("kern.waketime", "kern.boottime"):
        out = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True).stdout
        m = re.search(r"sec = (\d+)", out)
        if m:
            best = max(best, float(m.group(1)))
    return best


def on_ac():
    if os.environ.get("PANTHEON_FAKE_AC") is not None:
        return os.environ["PANTHEON_FAKE_AC"] == "1"
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    return "AC Power" in out or "Battery Power" not in out


def idle_sec():
    if os.environ.get("PANTHEON_FAKE_IDLE"):
        return float(os.environ["PANTHEON_FAKE_IDLE"])
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], capture_output=True, text=True).stdout
    m = re.search(r'"HIDIdleTime" = (\d+)', out)
    return int(m.group(1)) / 1e9 if m else 0.0


def limit_pct():
    """Пятичасовой лимит по снимку строки статуса; None — снимка нет."""
    if os.environ.get("PANTHEON_FAKE_LIMIT"):
        return float(os.environ["PANTHEON_FAKE_LIMIT"])
    try:
        pct, resets_at, _ = open(LIMIT_SNAPSHOT).read().split()[:3]
    except (OSError, ValueError):
        return None
    return 0.0 if now() > float(resets_at) else float(pct)


# --- тик ------------------------------------------------------------------------

def every_sec(job):
    every = job.get("every", "tick")
    return 0 if every == "tick" else float(every) * 60


def due(job, st, t):
    """(пора ли, с какого момента пора). У задачи, которая ещё не шла, опоздание считается с первого
    тика, на котором она ждала, — иначе max_delay для неё никогда бы не наступал."""
    if st.get("last_start") is None:
        return True, st.get("waiting_since", t)
    period = every_sec(job)
    due_at = st["last_start"] + period
    return t >= due_at - 5, due_at


def lease_expired(job, st, t):
    return bool(job.get("lease_days")) and st.get("lease_until") is not None and t > st["lease_until"]


def heavy_wait_reason(job, sched, t, overdue):
    """Почему тяжёлая задача ждёт. max_delay (overdue) снимает все условия, кроме лимита у задач на Claude: сессия
    `claude -p` при упоре в лимит обрывается на середине (TOOL-04), поэтому её тик переносит, а не запускает."""
    d = sched["defaults"]
    if overdue:
        pct = limit_pct() if job.get("claude") else None
        if pct is not None and pct >= d["limit_max_pct"]:
            return f"пятичасовой лимит {pct:.0f} % ≥ {d['limit_max_pct']} % (задача на Claude ждёт и после max_delay)"
        return None
    if t - wake_time() < d["wake_quiet_min"] * 60:
        return f"первые {d['wake_quiet_min']} мин после пробуждения — только лёгкие"
    if not on_ac():
        return "ждёт питания от сети"
    if job.get("claude"):
        idle = idle_sec()
        if idle < d["idle_min"] * 60:
            return f"ждёт простоя {d['idle_min']} мин (сейчас {int(idle // 60)} мин)"
        pct = limit_pct()
        if pct is not None and pct >= d["limit_max_pct"]:
            return f"пятичасовой лимит {pct:.0f} % ≥ {d['limit_max_pct']} %"
    return None


# --- пропуск прогонов тика без изменений (metis-0149) ---------------------------------------------------
# Четыре задачи тика идут каждую минуту, а почти всегда ничего не находят: каждая — запуск Python и обход папок. Тик
# пропускает такую задачу, если её входы не менялись с прошлого удачного прогона. Только по отпечатку stat
# (путь, размер, время изменения), содержимое не читается. Пропуск — только из тика: ручной `pantheon <команда>` и
# `pantheon run-job` идут всегда. Раз в TICK_SKIP_MAX секунд задача идёт в любом случае — ловит то, чего отпечаток не
# видит (время, внешние процессы). Задача вне таблицы или с другими аргументами идёт как раньше.
#
# Вход каждой команды (что она читает; свои же выходы в отпечаток не входят, иначе он менялся бы после каждого прогона):
#   команда (аргументы)       вход                                                           не входит
#   view --quiet              дерево PANTHEON без .git (размер, время) + «лишние» файлы      сама копия VIEW: rsync
#                             копии VIEW вне оригинала, вне .obsidian и Доска/ (их разбирает  меняет её после прогона
#                             view-sync.sh)
#   board                     карточки VIEW/Доска/*.md; задачи (task_dirs: inbox/tasks,       board.json, журнал
#                             directions/*/tasks); входящие directions/*/inbox; directions.toml, владельца и политика
#                             schedule.toml (primary, уведомления)                            уведомлений — выходы
#   sync-answers              HOME/.claude/.sync-held и .sync-incoming, owner-log/board.jsonl и zeus.md  —
#   agents                    HOME/.claude/daemon/roster.json, sessions/*.json (имя, pid),     ответ `claude agents`
#                             jobs/*/* — признаки, по которым демон Claude меняет список       (снимок нужен лишь как
#                                                                                              запасной вариант)
TICK_SKIP_MAX = 900


def _stat_rec(rel, p):
    try:
        s = os.lstat(p)
    except OSError:
        return (rel, None, None)
    return (rel, s.st_size, s.st_mtime_ns)


def _fp_tree(root, skip_dirs=(".git",)):
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in skip_dirs)
        for f in sorted(files):
            p = os.path.join(d, f)
            out.append(_stat_rec(os.path.relpath(p, root), p))
    return out


def _fp_files(paths):
    return [_stat_rec(p, p) for p in paths]


def _fp_dir(d, depth=2):
    """Список d и (при depth 2) файлов на уровень глубже; без обхода всего дерева."""
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return [(d, None, None)]
    for n in names:
        p = os.path.join(d, n)
        out.append(_stat_rec(p, p))
        if depth > 1 and os.path.isdir(p) and not os.path.islink(p):
            out += _fp_dir(p, depth - 1)
    return out


def _fp_view_extras():
    """Файлы копии VIEW, которых нет в оригинале (кроме .obsidian, Доска/ и служебных с точкой): view-sync.sh их
    переносит или удаляет. После обычного прогона их нет, поэтому отпечаток от прогона не зависит."""
    out = []
    if not os.path.isdir(VIEW):
        return [("view-missing", None, None)]
    for d, dirs, files in os.walk(VIEW):
        rel_d = os.path.relpath(d, VIEW)
        dirs[:] = [x for x in dirs if not (rel_d == "." and x in (".obsidian", "Доска"))]
        for f in files:
            rel = os.path.normpath(os.path.join(rel_d, f))
            if not f.startswith(".") and not os.path.exists(os.path.join(PANTHEON, rel)):
                out.append(_stat_rec(rel, os.path.join(VIEW, rel)))
    return out


def _fp_board_inputs():
    T = tasks_mod()
    out = _fp_files(sorted(T.task_files(PANTHEON)))
    out += _fp_files(sorted(glob.glob(os.path.join(PANTHEON, "directions", "*", "inbox", "*.md"))))
    out += _fp_files(sorted(glob.glob(os.path.join(BOARD, "*.md"))))
    out += _fp_files([os.path.join(PANTHEON, "directions.toml"), os.path.join(PANTHEON, "schedule.toml")])
    return out


TICK_SKIP = {
    ("view", "--quiet"): lambda: _fp_tree(PANTHEON) + _fp_view_extras(),
    ("board",): _fp_board_inputs,
    ("sync-answers",): lambda: _fp_files([os.path.join(SYNC_DIR, ".sync-held"), os.path.join(SYNC_DIR, ".sync-incoming"),
                                          os.path.join(STATE, "owner-log", "board.jsonl"),
                                          os.path.join(STATE, "owner-log", "zeus.md")]),
    ("agents",): lambda: (_fp_files([os.path.join(HOME, ".claude", "daemon", "roster.json")])
                          + _fp_files(sorted(glob.glob(os.path.join(HOME, ".claude", "sessions", "*.json"))))
                          + _fp_dir(os.path.join(HOME, ".claude", "jobs"))),
}


def tick_fingerprint(job):
    """Отпечаток входов задачи из TICK_SKIP или None (задачи нет в таблице — пропуску не подлежит)."""
    argv = parse_command(job.get("command"))
    if not argv or os.path.basename(argv[0]) != "pantheon":
        return None
    fn = TICK_SKIP.get(tuple(argv[1:]))
    if fn is None:
        return None
    try:
        return hashlib.sha1(repr(fn()).encode("utf-8", "replace")).hexdigest()
    except Exception:  # любой сбой разбора — не пропускать, а запустить
        return None


def tick_skippable(job, st, t):
    fp, at = st.get("skip_fp"), st.get("skip_at")
    if not fp or at is None or not 0 <= t - float(at) < TICK_SKIP_MAX or st.get("last_rc") != 0:
        return False
    return tick_fingerprint(job) == fp


def launch(name, t):
    """Запуск задачи отдельным процессом (или запись в журнал решений при PANTHEON_DRYRUN)."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        st = job_state(name)
        st.update(last_start=t, last_end=t, last_rc=0, waiting=None)
        save_job_state(name, st)
        with open(path("dryrun.log"), "a") as fh:
            fh.write(f"{int(t)} {name}\n")
        return
    # загрузчик run.py (модуль, .pyc из lib/__pycache__), тот же интерпретатор, что у тика
    subprocess.Popen([sys.executable, "-I", os.path.join(LIB, "run.py"), "run-job", name],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, env=run_env(), cwd=HOME)


def tick():
    os.makedirs(STATE, exist_ok=True)
    with lock("tick", block=False) as got:
        if not got:
            return
        t = now()
        with open(path("last-tick"), "w") as fh:
            fh.write(f"{int(t)}\n")
        if os.path.exists(path("paused")):
            return
        try:
            sched = load_schedule()
        except (OSError, ValueError) as e:
            mark = path("schedule-error")
            if not os.path.exists(mark):
                open(mark, "w").write(str(e))
                alert(f"schedule.toml не читается: {e}", "pantheon-tick")
            return
        with contextlib.suppress(FileNotFoundError):
            os.remove(path("schedule-error"))
        me, primary = host(), sched.get("primary_host")
        for bad in sched.get("bad_names") or []:
            alert_once("badname-" + re.sub(r"[^\w-]", "_", bad)[:40], bad, f"schedule.toml: задача или служба с именем не по образцу "
                       f"или повтором имени ({bad[:60]!r}; только a-z, 0-9, дефис, имена не повторяются) — пропущена", "pantheon-tick")
        heavy, skipped = [], []
        for job in sched.get("job") or []:
            name = job["name"]
            st = job_state(name)
            if job.get("enabled") is False or st.get("disabled"):
                continue
            if job.get("hosts", "all") == "primary":
                if not primary:
                    alert_once("no-primary", "1", "в schedule.toml нет primary_host: задачи с общим результатом "
                               "(hosts = \"primary\") не идут ни на одном Mac", "pantheon-tick")
                    continue
                if me != primary:
                    continue
            if parse_command(job.get("command")) is None:
                alert_once("badcmd-" + name, job.get("command"), f"задача {name}: команда не разрешённого вида "
                           "(только pantheon …, claude -p …, скрипт плагина; без ; & | $ > <) — пропущена",
                           "pantheon-tick", note=f"Задача {name} пропущена: команда не разрешена")
                continue
            if st.get("paused"):
                continue
            if job.get("lease_days") and st.get("lease_until") is None:
                st["lease_until"] = t + float(job["lease_days"]) * 86400
                save_job_state(name, st)
            if lease_expired(job, st, t):
                st.update(paused=True, paused_reason="аренда истекла")
                save_job_state(name, st)
                alert(f"задача {name}: аренда истекла, поставлена на паузу — продлить: pantheon jobs renew {name}",
                      "pantheon-tick")
                notify_soon("lease-" + name, f"Задача {name} на паузе: аренда истекла")
                continue
            is_due, due_at = due(job, st, t)
            if not is_due or locked("job-" + name):
                continue
            if tick_skippable(job, st, t):  # входы не менялись с прошлого удачного прогона (metis-0149)
                skipped.append(name)
                continue
            if job.get("class", "light") == "heavy":
                heavy.append((job, st, due_at))
            else:
                launch(name, t)
        if heavy:
            tick_heavy(sched, heavy, t)
        write_json(path("tick-skipped.json"), {"time": t, "skipped": skipped})
        try:
            services_sync(sched)
        except Exception as e:  # сбой служб не должен останавливать задачи тика
            alert_once("svc-sync", type(e).__name__, f"службы: сверка с launchd упала ({type(e).__name__}: {e})",
                       "pantheon-tick")
        try:
            roles_tick()  # личные роли по вашей галочке на доске (metis-0262 PR 4)
        except Exception as e:  # сбой ролей не должен останавливать тик
            alert_once("roles-tick", type(e).__name__, f"личные роли: проход упал ({type(e).__name__}: {e})",
                       "pantheon-tick")
        if not primary or me == primary:  # общий результат (задачи, gh) — на одном Mac
            try:
                autoclose_tick(t)
            except Exception as e:  # сбой автозакрытия не должен останавливать тик
                alert_once("autoclose-tick", type(e).__name__, f"автозакрытие задач: проход упал ({type(e).__name__}: {e})",
                           "pantheon-tick")


def tick_heavy(sched, heavy, t):
    gap = sched["defaults"]["heavy_gap_min"] * 60
    hs = read_json(path("heavy.json"))
    # heavy-cmd-1/2 — два места общей блокировки тяжёлых команд направлений (обёртка `heavy`, MEM-03, шаг 1.2)
    busy = (locked("heavy-run") or locked("heavy-cmd-1") or locked("heavy-cmd-2")
            or (hs.get("last_end") is not None and t - hs["last_end"] < gap))
    heavy.sort(key=lambda x: (-int(x[0].get("priority", 0)), x[2]))
    started = False
    for job, st, due_at in heavy:
        overdue = job.get("max_delay") is not None and t - due_at >= float(job["max_delay"]) * 60
        reason = ("идёт другая тяжёлая задача, сборка или тесты направления, или пауза между ними"
                  if (busy or started) else heavy_wait_reason(job, sched, t, overdue))
        if reason:
            st["waiting"] = reason
            st.setdefault("waiting_since", t)
            save_job_state(job["name"], st)
            continue
        st.pop("waiting", None)
        st.pop("waiting_since", None)
        save_job_state(job["name"], st)
        launch(job["name"], t)
        if os.environ.get("PANTHEON_DRYRUN") == "1":
            write_json(path("heavy.json"), {"last_end": t})
        started = True


# --- службы (SCHED-05) ------------------------------------------------------------------
# [[service]] в schedule.toml — постоянный процесс (сервер qmd, позже бот одобрения, Pixel Agents, «Пульт»). Каждая —
# своя задача launchd pantheon.svc.<имя> с KeepAlive; запускает её `pantheon service-run <имя>`, который
# перечитывает schedule.toml и проверяет команду (только `pantheon …` или скрипт плагина). Тик сверяет launchd с
# расписанием: нужна и не запущена — поднять, пауза, выключена, убрана из расписания или чужой Mac — снять.
# Служба по требованию (ключ `socket = <порт>`, metis-0151) — без KeepAlive: порт 127.0.0.1:<порт> слушает launchd
# (ключ Sockets), первое соединение запускает службу, после простоя (`idle_min`, по умолчанию 30 мин) она выходит
# сама. «Загружена, процесса нет» для неё — обычное ожидание запроса, а не сбой: тик её не толкает и не тревожит.

SVC_PREFIX = "pantheon.svc."
# Прежние метки (com.<кто-то>.pantheon-tick и com.<кто-то>.pantheon-svc.<имя>) узнаём по маске файлов, без имён в коде:
# тик и `pantheon install` снимают их и удаляют plist, пока не поднялись новые (иначе две копии службы дерутся за порт)
OLD_TICK_GLOB = "com.*.pantheon-tick.plist"
OLD_SVC_GLOB = "com.*.pantheon-svc.*.plist"
SVC_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>{bin}</string><string>service-run</string><string>{name}</string></array>
{launch}
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>{path}</string></dict>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


SVC_KEEPALIVE = """  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>"""
SVC_SOCKET = """  <key>Sockets</key>
  <dict><key>Listeners</key><dict>
    <key>SockNodeName</key><string>127.0.0.1</string>
    <key>SockServiceName</key><string>{port}</string>
    <key>SockType</key><string>stream</string>
    <key>SockFamily</key><string>IPv4</string>
  </dict></dict>"""
SVC_IDLE_MIN = 30


def svc_socket(svc):
    """Порт службы по требованию (ключ socket) или None — обычная служба с KeepAlive. Плохое значение — ValueError."""
    v = svc.get("socket")
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not 1024 <= v <= 65535:
        raise ValueError(f"socket: нужен порт 1024–65535, а не {v!r}")
    return v


def svc_idle(svc):
    """Простой службы по требованию до выхода, в секундах (ключ idle_min, минуты)."""
    v = svc.get("idle_min", SVC_IDLE_MIN)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 24 * 60:
        raise ValueError(f"idle_min: нужно число минут больше 0 и не больше суток, а не {v!r}")
    return float(v) * 60


def svc_on_demand(svc):
    with contextlib.suppress(ValueError):
        return svc_socket(svc) is not None
    return False


def parse_service_command(cmd):
    """Команда службы: как у задачи, но без `claude -p` — служба живёт постоянно, а сессия Claude — нет."""
    argv = parse_command(cmd)
    if argv is None or argv[0] == "claude":
        return None
    return argv


def service_wanted(svc, sched, st=None):
    """(нужна ли служба на этом Mac, почему нет)."""
    st = job_state(svc["name"]) if st is None else st
    if svc.get("enabled") is False or st.get("disabled"):
        return False, "выключена"
    if st.get("paused"):
        return False, "пауза"
    if svc.get("hosts", "all") == "primary" and host() != sched.get("primary_host"):
        return False, "не этот Mac"
    if parse_service_command(svc.get("command")) is None:
        return False, "команда не разрешена"
    try:
        svc_socket(svc)
        svc_idle(svc)
    except ValueError as e:
        return False, str(e)
    return True, ""


def _svc_plist(name):
    return os.path.join(HOME, "Library", "LaunchAgents", SVC_PREFIX + name + ".plist")


def svc_running(name):
    """pid службы по launchctl print, 0 — загружена, но не идёт, None — не загружена."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        return read_json(path("svc-dry.json")).get(name)
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{SVC_PREFIX}{name}"], capture_output=True,
                       text=True, timeout=15)
    if r.returncode != 0:
        return None
    m = re.search(r"^\s*pid = (\d+)", r.stdout, re.M)
    return int(m.group(1)) if m else 0


def svc_last_exit(name):
    """Последний код выхода службы по launchctl print («last exit code»); не выходила или не узнать — None."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        return (read_json(path("svc-dry.json")).get("exit") or {}).get(name)
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{SVC_PREFIX}{name}"], capture_output=True,
                       text=True, timeout=15)
    m = re.search(r"^\s*last exit code = (-?\d+)", r.stdout, re.M) if r.returncode == 0 else None
    return int(m.group(1)) if m else None


def _launchctl(verb, target, name):
    """launchctl bootstrap|bootout|kickstart; при PANTHEON_DRYRUN — строка в dryrun.log и мнимое состояние."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        with open(path("dryrun.log"), "a") as fh:
            fh.write(f"{int(now())} svc-{verb} {name}\n")
        dry = read_json(path("svc-dry.json"))
        if verb == "bootout":
            dry.pop(name, None)
        else:
            dry[name] = 4242
        write_json(path("svc-dry.json"), dry)
        return True, ""
    r = subprocess.run(["launchctl", verb, *target], capture_output=True, text=True, timeout=30)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def old_plists(pattern):
    """Файлы ~/Library/LaunchAgents по маске прежних меток (OLD_TICK_GLOB, OLD_SVC_GLOB)."""
    agents = os.path.join(HOME, "Library", "LaunchAgents")
    with contextlib.suppress(OSError):
        return sorted(os.path.join(agents, f) for f in os.listdir(agents) if fnmatch.fnmatchcase(f, pattern))
    return []


def drop_old(pattern):
    """bootout и удаление plist прежних меток. → число снятых (не снятая — загружена после неудачного bootout — не
    считается, её plist остаётся). При PANTHEON_DRYRUN — строка `old-bootout` в dryrun.log."""
    n = 0
    for p in old_plists(pattern):
        label = os.path.basename(p)[:-len(".plist")]
        if os.environ.get("PANTHEON_DRYRUN") == "1":
            with open(path("dryrun.log"), "a") as fh:
                fh.write(f"{int(now())} old-bootout {label}\n")
        else:
            target = f"gui/{os.getuid()}/{label}"
            r = subprocess.run(["launchctl", "bootout", target], capture_output=True, timeout=30)
            if r.returncode != 0 and subprocess.run(["launchctl", "print", target], capture_output=True,
                                                    timeout=15).returncode == 0:
                # bootout не снял, а задача загружена: plist оставляем — иначе службу никто не найдёт, а новая
                # встанет рядом (две копии дерутся за порт)
                print(f"pantheon: прежняя служба {label} не снимается (launchctl bootout, код {r.returncode}); "
                      f"plist оставлен, снимите её вручную", file=sys.stderr)
                continue
        with contextlib.suppress(FileNotFoundError):
            os.remove(p)
        n += 1
    return n


def _svc_path():
    """PATH служб — тот же, что у задачи тика (python3 из него запускает pantheon): от того, каким python вызван
    `pantheon jobs`, plist не меняется и служба не перезапускается зря (ревью argus 15.10)."""
    import plistlib
    with contextlib.suppress(OSError, ValueError, KeyError, TypeError, plistlib.InvalidFileException):
        with open(next((p for p in [PLIST, *old_plists(OLD_TICK_GLOB)] if os.path.exists(p)), PLIST), "rb") as fh:
            return str(plistlib.load(fh)["EnvironmentVariables"]["PATH"])
    return ":".join([os.path.dirname(sys.executable), "/opt/homebrew/bin", os.path.join(HOME, ".local", "bin"),
                     "/usr/bin:/bin:/usr/sbin:/sbin"])


def services_sync(sched, only=None):
    """Сверить задачи launchd служб с расписанием. only — одна служба (пульт: пауза снимает её сразу). Тик и пульт
    сверяют под одной блокировкой — иначе двойной bootstrap и ложная тревога."""
    with lock("svc"):
        _services_sync(sched, only)


def _services_sync(sched, only):
    uid = os.getuid()
    env_path = _svc_path()  # до снятия прежних plist: PATH берётся и из прежнего тика
    # прежние службы — до запуска новых: две копии одной службы дерутся за порт; при only — только эта служба
    drop_old(f"com.*.pantheon-svc.{glob.escape(only)}.plist" if only else OLD_SVC_GLOB)
    want = {}
    for svc in sched.get("service") or []:
        ok, _ = service_wanted(svc, sched)
        if ok:
            want[svc["name"]] = svc
    agents = os.path.join(HOME, "Library", "LaunchAgents")
    have = set()
    with contextlib.suppress(OSError):
        have = {f[len(SVC_PREFIX):-6] for f in os.listdir(agents) if f.startswith(SVC_PREFIX) and f.endswith(".plist")}
    for name in sorted(have | set(want)):
        if only and name != only:
            continue
        plist = _svc_plist(name)
        if name not in want:
            if svc_running(name) is not None:
                _launchctl("bootout", [f"gui/{uid}/{SVC_PREFIX}{name}"], name)
            with contextlib.suppress(FileNotFoundError):
                os.remove(plist)
            continue
        port = svc_socket(want[name])
        launch = SVC_KEEPALIVE if port is None else SVC_SOCKET.format(port=port)
        text = SVC_TMPL.format(label=SVC_PREFIX + name, bin=os.path.join(CURRENT, "bin", "pantheon"), name=name,
                               path=env_path, log=path("logs", f"svc-{name}.log"), launch=launch)
        try:
            same = open(plist).read() == text
        except OSError:
            same = False
        state = svc_running(name)
        if not same:
            os.makedirs(agents, exist_ok=True)
            os.makedirs(path("logs"), exist_ok=True)
            with open(plist, "w") as fh:
                fh.write(text)
            if state is not None:
                _launchctl("bootout", [f"gui/{uid}/{SVC_PREFIX}{name}"], name)
            state = None
        if state is None:
            ok, err = _launchctl("bootstrap", [f"gui/{uid}", plist], name)
            if not ok and svc_running(name) is None:
                alert_once("svc-" + name, err[:80], f"служба {name}: launchd не принял ({err[:160]})", "pantheon-tick",
                           note=f"Служба {name} не запустилась")
                continue
            clear_once("svc-" + name)
        elif state == 0 and port is not None:
            # служба по требованию ждёт соединения на сокете launchd — так и должно быть, если последний запуск
            # кончился чисто (прокси выходит по простою с кодом 0); ненулевой код — служба падает при запуске
            code = svc_last_exit(name)
            if code:
                alert_once("svc-down-" + name, f"exit-{code}", f"служба по требованию {name} падает при запуске: "
                           f"последний код выхода {code}; журнал {path('logs', f'svc-{name}.log').replace(HOME, '~')}",
                           "pantheon-tick", note=f"Служба {name} падает при запуске")
            else:
                clear_once("svc-down-" + name)
        elif state == 0:
            # загружена, но процесса нет (KeepAlive сдался после частых падений) — толкнуть, раз в тик
            _launchctl("kickstart", [f"gui/{uid}/{SVC_PREFIX}{name}"], name)
            alert_once("svc-down-" + name, "down", f"служба {name} не работает — launchd её перезапускает; журнал "
                       f"{path('logs', f'svc-{name}.log').replace(HOME, '~')}", "pantheon-tick",
                       note=f"Служба {name} не работает")
        else:
            clear_once("svc-down-" + name)


def service_run(name):
    """Точка входа службы для launchd: перечитать расписание, проверить и заменить себя командой."""
    try:
        sched = load_schedule()
    except (OSError, ValueError) as e:
        print(f"schedule.toml не читается: {e}", file=sys.stderr)
        time.sleep(60)
        return 1
    svc = next((s for s in sched.get("service") or [] if s["name"] == name), None)
    ok, why = service_wanted(svc, sched) if svc else (False, "нет в schedule.toml")
    if not ok:
        print(f"{stamp()} служба {name} не идёт: {why}", file=sys.stderr)
        time.sleep(60)  # KeepAlive перезапустит; тик снимет задачу launchd за минуту
        return 0
    argv = parse_service_command(svc.get("command"))
    print(f"{stamp()} служба {name}: {' '.join(argv)}", file=sys.stderr, flush=True)
    env = run_env()
    if svc_socket(svc) is not None:
        # служба по требованию: сокет ждёт у launchd (запись Listeners в plist), простой — до выхода
        env["PANTHEON_SVC_SOCKET"] = "Listeners"
        env["PANTHEON_SVC_IDLE"] = str(int(svc_idle(svc)))
    os.chdir(HOME)
    os.execve(argv[0], argv, env)


def run_job(name):
    sched = load_schedule()
    job = next((j for j in sched.get("job") or [] if j["name"] == name), None)
    if not job:
        return 2
    argv = parse_command(job.get("command"))
    if argv is None:
        return 2
    heavy = job.get("class") == "heavy"
    with lock("job-" + name, block=False) as got:
        if not got:
            return 0
        # задача на Claude — только в песочнице своего окна (P0-3): окна нет — не запускать, а не запускать без неё.
        # Запуск считается сбоем: срок задачи сдвигается, тяжёлые задачи за ней не ждут каждый тик
        bad = job_window_problem(argv)
        if bad:
            alert_once("job-window-" + name, bad, f"задача {name} не идёт: {bad}. Окна задач собирает `pantheon domains "
                       "build`", "pantheon-tick",
                       note=f"Задача {name} не идёт: нет окна песочницы")
            st = job_state(name)
            st.update(last_start=now(), last_end=now(), last_rc=ALERTED, fails=int(st.get("fails") or 0) + 1)
            st.pop("waiting", None)
            save_job_state(name, st)
            return ALERTED
        clear_once("job-window-" + name)
        with (lock("heavy-run", block=False) if heavy else contextlib.nullcontext(True)) as hgot:
            if not hgot:
                return 0
            fp0 = tick_fingerprint(job)  # до прогона: что изменилось за время работы, поймает следующий тик
            st = job_state(name)
            st.update(last_start=now())
            save_job_state(name, st)
            os.makedirs(path("logs"), exist_ok=True)
            log = path("logs", name + ".log")
            started = time.time()
            started_at = now()
            timeout = float(job.get("timeout", 600))
            # Своя группа процессов: по таймауту гасится вся задача, а не только первый процесс.
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env=run_env(), cwd=HOME, start_new_session=True)
            try:
                out, _ = proc.communicate(timeout=timeout)
                rc = proc.returncode
            except subprocess.TimeoutExpired:
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, sig)
                    try:
                        out, _ = proc.communicate(timeout=5)
                        break
                    except subprocess.TimeoutExpired:
                        out = ""
                rc, out = 124, f"таймаут {int(timeout)} с, группа процессов остановлена\n{out or ''}"
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(f"--- {stamp()} rc={rc} {time.time() - started:.1f} с\n{(out or '')[-4000:]}")
            trim_log(log)
            st = job_state(name)
            st.update(last_end=now(), last_rc=rc)
            st.pop("running", None)
            if rc == 0 and fp0:
                st.update(skip_fp=fp0, skip_at=started_at)
            else:
                st.pop("skip_fp", None)
                st.pop("skip_at", None)
            if rc == TEMPFAIL:
                st["waiting"] = "нет сети или GitHub недоступен"
            else:
                st.pop("waiting", None)
                st["fails"] = 0 if rc == 0 else int(st.get("fails") or 0) + 1
            save_job_state(name, st)
            if heavy:
                write_json(path("heavy.json"), {"last_end": now()})
            if rc not in (0, TEMPFAIL, ALERTED) and st["fails"] in (1, 5, 20):
                tail = (out or "").strip().splitlines()[-1:] or [""]
                alert(f"задача {name} упала (код {rc}, подряд {st['fails']}): {tail[0][:200]} — журнал {log.replace(HOME, '~')}",
                      "pantheon-tick")
                if job.get("notify", True):
                    notify_soon("job-" + name, f"Задача {name} упала (код {rc})")
            return rc


# --- пульт задач -------------------------------------------------------------------

def ago(t):
    if not t:
        return "—"
    s = now() - t
    return f"{int(s)} с назад" if s < 90 else f"{int(s // 60)} мин назад" if s < 5400 else stamp(t)


def next_run(job, st, t):
    if job.get("enabled") is False or st.get("disabled") or st.get("paused"):
        return "—"
    if locked("job-" + job["name"]):
        return "идёт"
    if st.get("waiting"):
        return "ждёт условий"
    if st.get("last_start") is None:
        return "на ближайшем плановом проходе"
    if job.get("every", "tick") == "tick":
        return "каждый плановый проход"
    left = st["last_start"] + every_sec(job) - t
    if left <= 60:
        return "на ближайшем плановом проходе"
    return f"через {int(left // 60)} мин" if left < 5400 else stamp(st["last_start"] + every_sec(job))


def jobs_show():
    lt = None
    with contextlib.suppress(OSError, ValueError):
        lt = float(open(path("last-tick")).read())
    tick_line = f"плановый проход: {ago(lt)}" if lt else "плановый проход: ещё не шёл (pantheon install)"
    if not os.path.exists(PLIST) and old_plists(OLD_TICK_GLOB):
        tick_line += " — старая метка launchd: выполните `pantheon install`"
    if lt and now() - lt > 180:
        tick_line += " — ПЛАНИРОВЩИК СТОИТ"
    if os.path.exists(path("paused")):
        tick_line += " · весь планировщик на паузе (pantheon jobs resume --all)"
    sched = load_schedule()
    print(f"{tick_line} · этот Mac: {host()} · главный: {sched.get('primary_host') or '—'}\n")
    rows = [("задача", "класс", "где", "как часто", "последний запуск", "дальше", "состояние")]
    t = now()
    for job in sched.get("job") or []:
        st = job_state(job["name"])
        every = "каждый плановый проход" if job.get("every", "tick") == "tick" else f"{job['every']} мин"
        if job.get("enabled") is False or st.get("disabled"):
            state = "выключена"
        elif st.get("paused"):
            state = f"пауза{': ' + st['paused_reason'] if st.get('paused_reason') else ''}"
        elif locked("job-" + job["name"]):
            state = "идёт"
        elif parse_command(job.get("command")) is None:
            state = "команда не разрешена — пропускается"
        elif job_window_problem(parse_command(job.get("command"))):
            state = f"не идёт: {job_window_problem(parse_command(job.get('command')))} (pantheon domains build)"
        elif st.get("waiting"):
            state = f"ждёт: {st['waiting']}"
        elif st.get("last_rc") not in (None, 0):
            state = f"упала, код {st['last_rc']}"
        else:
            state = "ок"
        if st.get("lease_until"):
            state += f" · аренда до {stamp(st['lease_until'])[:10]}"
        last = ago(st.get("last_start")) if st.get("last_start") else "—"
        rows.append((job["name"], job.get("class", "light"), job.get("hosts", "all"), every, last,
                     next_run(job, st, t), state))
    widths = [max(len(r[i]) for r in rows) for i in range(6)]
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r[:6], widths)) + "  " + r[6])
    if sched.get("service"):
        print()
        rows = [("служба", "где", "состояние", "что")]
        for svc in sched["service"]:
            ok, why = service_wanted(svc, sched)
            pid = svc_running(svc["name"])
            if ok and svc_on_demand(svc):
                where = f"127.0.0.1:{svc_socket(svc)}"
                state = (f"идёт по запросу, pid {pid}; выйдет после простоя {int(svc_idle(svc) // 60)} мин" if pid
                         else f"по требованию: ждёт запроса на {where}" if pid == 0
                         else "не загружена — плановый проход поднимет")
            else:
                state = (f"идёт, pid {pid}" if pid else "не идёт — плановый проход поднимет") if ok else why
            if not ok and pid:
                state += f" (ещё идёт, pid {pid}: плановый проход снимет)"
            rows.append((svc["name"], svc.get("hosts", "all"), state, str(svc.get("description", ""))[:70]))
        widths = [max(len(r[i]) for r in rows) for i in range(3)]
        for r in rows:
            print("  ".join(c.ljust(w) for c, w in zip(r[:3], widths)) + "  " + r[3])


# --- pantheon status: один экран для отладки --------------------------------------------------------------------
# Только читает: тик, задачи тика, сессии, вопросы к владельцу, тревоги, guard, карантин ~/.claude, места heavy,
# управляемые настройки, версии, память. Первая строка — итог: «всё в порядке» или число того, что требует внимания.
MANAGED = "/Library/Application Support/ClaudeCode/managed-settings.json"


def _sh(*cmd, timeout=20):
    try:
        r = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _plugin_version(name):
    d = os.path.join(HOME, ".claude", "plugins", "marketplaces", "agent-kit", "plugins", name, ".claude-plugin",
                     "plugin.json")
    with contextlib.suppress(OSError, ValueError):
        return json.load(open(d)).get("version", "?")
    return "?"


def status():
    t = now()
    warn, sections = [], []

    def section(title, lines):
        sections.append((title, lines or ["—"]))

    # тик и его задачи
    lt = None
    with contextlib.suppress(OSError, ValueError):
        lt = float(open(path("last-tick")).read())
    lines = [f"последний проход: {ago(lt)}" if lt else "ещё не шёл (pantheon install)"]
    if not lt or t - lt > 180:
        warn.append("плановый проход стоит")
        lines[0] += " — СТОИТ"
    if os.path.exists(path("paused")):
        lines.append("весь планировщик на паузе (pantheon jobs resume --all)")
    try:
        jobs_list = load_schedule().get("job") or []
    except (OSError, ValueError) as e:
        jobs_list = []
        lines.append(f"schedule.toml не прочитать: {type(e).__name__}")
        warn.append("schedule.toml")
    for job in jobs_list:
        st = job_state(job["name"])
        if job.get("enabled") is False or st.get("disabled"):
            continue
        if parse_command(job.get("command")) is None:
            bad = "команда не разрешена"
        elif job_window_problem(parse_command(job.get("command"))):
            bad = job_window_problem(parse_command(job.get("command")))
        elif st.get("paused"):
            bad = "на паузе"
        elif st.get("last_rc") not in (None, 0):
            bad = f"упала, код {st['last_rc']} ({ago(st.get('last_start'))})"
        else:
            continue
        lines.append(f"{job['name']}: {bad}")
        warn.append(f"задача {job['name']}")
    with contextlib.suppress(OSError, ValueError):
        sched_s = load_schedule()
        for svc in sched_s.get("service") or []:
            ok, why = service_wanted(svc, sched_s)
            if ok and svc_on_demand(svc):
                if svc_running(svc["name"]) is None:
                    lines.append(f"служба {svc['name']}: НЕ ЗАГРУЖЕНА (по требованию) — журнал "
                                 f"~/.local/state/pantheon/logs/svc-{svc['name']}.log")
                    warn.append(f"служба {svc['name']}")
            elif ok and not svc_running(svc["name"]):
                lines.append(f"служба {svc['name']}: НЕ ИДЁТ — журнал ~/.local/state/pantheon/logs/svc-{svc['name']}.log")
                warn.append(f"служба {svc['name']}")
            elif not ok and (why in ("пауза", "команда не разрешена") or why.startswith(("socket:", "idle_min:"))):
                lines.append(f"служба {svc['name']}: {why}")
    # дежурный (watch.py): время прохода и упавшие проверки; метка техперезапуска; паузы по нагрузке
    wl = read_json(path("watch-last"), None)
    if wl and wl.get("time"):
        line = f"дежурный: {ago(wl['time'])}"
        if t - float(wl["time"]) > 900:
            line += " — НЕ ХОДИТ (задача watch раз в 5 мин)"
            warn.append("дежурный")
        if wl.get("failed"):
            line += f"; упали проверки: {', '.join(wl['failed'])}"
            warn.append("проверки дежурного")
        lines.append(line)
    m = maintenance_active()
    if m:
        lines.append(f"технический перезапуск: с {str(m.get('id'))[11:16]} ({m.get('reason')}) — pantheon restart --status")
        warn.append("техперезапуск")
    with contextlib.suppress(OSError):
        ps = sorted(f[:-5] for f in os.listdir(path("pauses")) if f.endswith(".json"))
        if ps:
            lines.append("пауза по нагрузке: " + ", ".join("все" if p == "_all" else p for p in ps))
    section("Плановый проход", lines)

    # сессии
    data = agents_all()
    lines = []
    if data is None:
        lines.append("claude agents не ответил")
        warn.append("claude agents")
    else:
        by = {}
        for a in data:
            if a.get("kind") == "interactive":
                by.setdefault("interactive", []).append(a)
                continue
            # metis-0250: «ждёт вас» без процесса и без вопроса — не ждёт, а снята Claude Code (reconcile_agents)
            by.setdefault("gone" if a.get("noProcess") else a.get("state") or "?", []).append(a)
        order = ("interactive", "working", "blocked", "failed", "gone", "done", "stopped")
        word = {"interactive": "открыты в терминале", "working": "фоновые работают", "blocked": "ждут вас",
                "failed": "упали", "gone": "без процесса", "done": "закончили ход", "stopped": "остановлены"}
        lines.append(" · ".join(f"{word.get(k, k)}: {len(by[k])}" for k in sorted(by, key=lambda k: (
            order.index(k) if k in order else 9))) or "фоновых сессий нет")
        for k in ("blocked", "failed", "gone"):
            for a in by.get(k, []):
                # пустая причина — без тире (metis-0250 п. 4); у «без процесса» — что сделать
                why = " ".join(str(a.get("waitingFor") or a.get("status") or "").split())[:80]
                if k == "gone":
                    why = f"ждать нечего, процесс снял Claude Code — убрать: claude rm {a.get('id')}"
                lines.append(f"{word[k]}: {a.get('name') or a.get('id')}" + (f" — {why}" if why else ""))
                if k != "gone":
                    warn.append(f"сессия {a.get('name') or a.get('id')}")
    section("Сессии", lines)

    # вопросы к владельцу на доске
    lines = []
    with contextlib.suppress(Exception):
        waiting = [(tid, head) for tid, (_, head, _) in tasks_mod().load_tasks(PANTHEON).items()
                   if head.get("status") == "waiting" and head.get("waiting_on") == "human"]
        lines = [f"{len(waiting)} на доске"] + [f"{tid}: {str(h.get('title'))[:70]}" for tid, h in waiting[:5]]
    section("Ждут вас", lines)

    # тревоги за сутки
    lines = []
    day = stamp(t - 86400)[:16].replace("T", " ")
    with contextlib.suppress(OSError):
        recent = [ln.strip() for ln in open(os.path.join(PANTHEON, "alerts.md"), encoding="utf-8")
                  if re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d · ", ln) and ln[:16] >= day]
        lines = [f"за сутки: {len(recent)}"] + [ln[:110] for ln in recent[-3:]]
    section("Тревоги", lines)

    # guard и защиты
    lines = []
    n_fail = 0
    with contextlib.suppress(OSError):
        since = stamp(t - 86400)[:19]
        n_fail = sum(1 for ln in open(path("logs", "guard-failures.log"), encoding="utf-8") if ln[:19] >= since)
    lines.append(f"сбоев guard за сутки: {n_fail}")
    if n_fail:
        warn.append("сбои guard")
    plug = os.path.join(HOME, ".claude", "plugins", "marketplaces", "agent-kit", "plugins", "guard", "managed-settings.json")
    if not os.path.exists(MANAGED):
        lines.append("управляемые настройки: НЕ установлены (README guard, sudo)")
        warn.append("управляемые настройки")
    elif open(MANAGED, "rb").read() != (open(plug, "rb").read() if os.path.exists(plug) else b""):
        lines.append("управляемые настройки: отстали от guard — обновить той же командой sudo")
        warn.append("управляемые настройки")
    else:
        lines.append("управляемые настройки: установлены, совпадают с guard")
    section("Защиты", lines)

    # синхронизация ~/.claude
    lines, cfg = [], os.path.join(HOME, ".claude")
    marks = {".sync-held": "карантин правок — ответ на доске", ".sync-incoming": "правка с другого компьютера — на доске",
             ".sync-conflict": "конфликт с другим компьютером", ".sync-error": "ошибка синхронизации"}
    for f, what in marks.items():
        if os.path.exists(os.path.join(cfg, f)):
            lines.append(what)
            warn.append("sync")
    section("Синхронизация ~/.claude", lines or ["в порядке"])

    # недельный лимит и ночь (metis-0127, 0129)
    try:
        lines = night_mod().status_lines(t)
    except Exception as e:  # noqa: BLE001 — сбой расчёта не ломает остальной экран
        lines = [f"не посчитать: {type(e).__name__}: {str(e)[:120]}"]
    if any(ln.startswith("лимит неизвестен") or "зона: красная" in ln or "зона: жёлтая" in ln for ln in lines):
        warn.append("лимит")
    section("Лимит и ночь", lines)

    # места heavy, память, версии
    lines = []
    for name in ("heavy-cmd-1", "heavy-cmd-2", "heavy-server"):
        p = path("locks", name + ".lock")
        if not os.path.exists(p):
            lines.append(f"{name}: нет (pantheon install)")
            continue
        try:
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
                lines.append(f"{name}: свободно")
            except OSError:
                lines.append(f"{name}: занято")
            finally:
                os.close(fd)
        except OSError:
            lines.append(f"{name}: не открыть")
    sw = re.search(r"used = ([\d.,]+)M", _sh("sysctl", "vm.swapusage"))
    if sw:
        used = float(sw.group(1).replace(",", "."))
        lines.append(f"swap: {used / 1024:.1f} ГБ")
        if used > 4096:
            warn.append("swap")
    with contextlib.suppress(Exception):
        lines.append(awake_mod().status_line())
    lines.append(f"Claude Code {(_sh('claude', '--version').split() or ['?'])[0]} · guard {_plugin_version('guard')} · "
                 f"pantheon {_plugin_version('pantheon')}")
    section("Mac", lines)

    head = "всё в порядке" if not warn else f"требует внимания: {len(warn)} — " + ", ".join(dict.fromkeys(warn))
    print(f"Пантеон · {host()} · {stamp(t)[:16].replace('T', ' ')} · {head}\n")
    for title, lines in sections:
        print(title)
        for ln in lines:
            print(f"  {ln}")
        print()
    return 0 if not warn else 1


def jobs_set(action, name, arg=None):
    if name == "--all":
        if action not in ("pause", "resume"):
            print("--all бывает только у pause и resume", file=sys.stderr)
            return 2
        if action == "pause":
            open(path("paused"), "w").write(stamp())
            alert("весь планировщик на паузе (pantheon jobs pause --all)", "pantheon")
        elif action == "resume":
            with contextlib.suppress(FileNotFoundError):
                os.remove(path("paused"))
        return 0
    sched = load_schedule()
    job = next((j for j in (sched.get("job") or []) + (sched.get("service") or []) if j["name"] == name), None)
    if not job:
        print(f"нет задачи или службы {name}; список — pantheon jobs", file=sys.stderr)
        return 2
    is_svc = job in (sched.get("service") or [])
    if is_svc and action == "renew":
        print("у служб нет аренды", file=sys.stderr)
        return 2
    st = job_state(name)
    if action == "pause":
        st.update(paused=True, paused_reason="вы")
    elif action == "resume":
        st.update(paused=False, paused_reason=None)
    elif action == "disable":
        st["disabled"] = True
    elif action == "enable":
        st["disabled"] = False
    elif action == "renew":
        days = float(arg or job.get("lease_days") or 30)
        st.update(lease_until=now() + days * 86400, paused=False, paused_reason=None)
    save_job_state(name, st)
    if is_svc:
        services_sync(sched, only=name)  # служба встаёт или поднимается сразу, а не на следующем тике
    return 0


# --- задачи ------------------------------------------------------------------------

def view(quiet=False):
    if not os.path.isdir(PANTHEON):
        return 0
    with lock("view"):
        rc = subprocess.run(["/bin/zsh", os.path.join(LIB, "view-sync.sh"), PANTHEON, VIEW, VIEW_INBOX],
                            capture_output=quiet).returncode
    return rc


def git(*args, check=True):
    return subprocess.run(["git", "-C", PANTHEON, *args], capture_output=True, text=True, check=check,
                          env=run_env())


# push большого коммита по HTTPS упирается в буфер git (по умолчанию 1 МБ → «RPC failed; HTTP 400/413»): буфер 150 МБ
# задаётся ключом -c на каждый push, ~/.gitconfig не правится (metis-0133)
PUSH_POST_BUFFER = 157286400
PUSH_FAIL_LIMIT = 3
# отказ сервера, а не отсутствие сети: HTTP 4xx/5xx, RPC failed, обрыв при передаче пакета
PUSH_SERVER_ERR = re.compile(r"returned error: [45]\d\d|\bHTTP/?[\d.]*\s*[45]\d\d|RPC failed|"
                             r"remote end hung up|pack-objects died|send-pack: unexpected disconnect", re.I)


def push_failed(stderr):
    """Неудача push, не похожая на «нет сети», считается подряд: на 3-й — тревога (ошибка не исчезнет сама,
    как исчезает отсутствие сети); без сети счётчик не растёт и не сбрасывается."""
    if not PUSH_SERVER_ERR.search(stderr or ""):
        return
    f = path("push-fail.json")
    n = int(read_json(f).get("n") or 0) + 1
    write_json(f, {"n": n, "t": now()})
    if n >= PUSH_FAIL_LIMIT:
        alert_once("push-fail", PUSH_FAIL_LIMIT, f"~/ai/pantheon: push не проходит {n} раза подряд "
                   f"({(stderr.strip().splitlines() or [''])[-1][:200]}) — это не обрыв сети, нужен разбор",
                   "pantheon-commit", note="~/ai/pantheon: push не проходит несколько раз подряд")


def clear_push_failures():
    with contextlib.suppress(OSError):
        os.remove(path("push-fail.json"))
    clear_once("push-fail")


def commit():
    """commit → pull без rebase → push, как Obsidian Git. Слияние шифрованных файлов — git-crypt-merge.sh
    (дописываемые файлы — объединением). Без сети — код TEMPFAIL и тишина; тревога, только если синхронизации
    нет дольше 6 часов. Конфликт — слияние отменяется, тревога одна на каждый новый коммит другого Mac."""
    if not os.path.isdir(os.path.join(PANTHEON, ".git")):
        return 0
    with lock("pantheon-git"):
        if git("status", "--porcelain").stdout.strip():
            git("add", "-A")
            git("commit", "-q", "-m", f"pantheon: {host()} {stamp()}")
        if not git("remote", check=False).stdout.strip():
            return 0

        def offline(stderr):
            ok = read_json(path("commit-ok.json")).get("t") or 0
            if now() - ok > 6 * 3600:
                alert_once("commit-offline", int(ok), "~/ai/pantheon не синхронизируется с GitHub больше 6 часов: "
                           f"{(stderr.strip().splitlines() or [''])[-1][:200]}", "pantheon-commit",
                           note="~/ai/pantheon давно не синхронизируется с GitHub")
            print(stderr.strip(), file=sys.stderr)
            return TEMPFAIL

        pull = git("pull", "--no-rebase", "--no-edit", "-q", check=False)
        if pull.returncode != 0:
            if os.path.exists(os.path.join(PANTHEON, ".git", "MERGE_HEAD")):
                files = git("diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
                theirs = git("rev-parse", "MERGE_HEAD", check=False).stdout.strip()
                git("merge", "--abort", check=False)
                alert_once("merge-conflict", theirs, f"~/ai/pantheon: конфликт слияния с другим компьютером "
                           f"({', '.join(files) or 'файлы не названы'}); локальный коммит цел, слияние отменено — "
                           "разобрать вручную", "pantheon-commit", note="~/ai/pantheon: конфликт слияния, нужен разбор")
                return ALERTED
            return offline(pull.stderr)
        clear_once("merge-conflict")
        ahead = git("rev-list", "--count", "@{u}..HEAD", check=False).stdout.strip()
        if ahead and ahead != "0":
            push = git("-c", f"http.postBuffer={PUSH_POST_BUFFER}", "push", "-q", check=False)
            if push.returncode != 0:
                push_failed(push.stderr)
                return offline(push.stderr)
            clear_push_failures()
        write_json(path("commit-ok.json"), {"t": now()})
        clear_once("commit-offline")
    return 0


DONE_HEAD = re.compile(r"^##\s+Сделано\s*$")
DATE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
DATE_RU = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{2})(?:\.(\d{4}))?(?![\d.])")


def line_date(line, t):
    """Первая корректная дата строки: сначала ГГГГ-ММ-ДД, потом ДД.ММ[.ГГГГ] (версии вроде 2.1.12 — не даты)."""
    for m in DATE_ISO.finditer(line):
        with contextlib.suppress(ValueError):
            return datetime(int(m[1]), int(m[2]), int(m[3]))
    for m in DATE_RU.finditer(line):
        year = int(m[3]) if m[3] else datetime.fromtimestamp(t).year
        with contextlib.suppress(ValueError):
            d = datetime(year, int(m[2]), int(m[1]))
            return d if d <= datetime.fromtimestamp(t) + timedelta(days=1) else d.replace(year=year - 1)
    return None


def write_atomic(p, text):
    tmp = f"{p}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, p)


def archive():
    """Раздел «Сделано» доски старше 7 дней и строки alerts.md старше 30 дней — в ~/ai/pantheon/archive/.
    Запускает Зевс при утренней сводке, поэтому у доски остаётся один писатель."""
    t = now()
    today = datetime.fromtimestamp(t)
    moved = {"board": 0, "alerts": 0}
    lk = lock("pantheon-git")  # коммит тика не захватит доску посреди переписывания
    lk.__enter__()
    os.makedirs(os.path.join(PANTHEON, "archive"), exist_ok=True)

    def append(name, lines):
        with open(os.path.join(PANTHEON, "archive", name), "a", encoding="utf-8") as fh:
            fh.writelines(lines)

    board = os.path.join(PANTHEON, "board.md")
    if os.path.exists(board):
        lines = open(board, encoding="utf-8").read().splitlines(keepends=True)
        out, old, in_done, item_old = [], {}, False, False
        for ln in lines:
            if ln.startswith("## "):
                in_done = bool(DONE_HEAD.match(ln.strip()))
                out.append(ln)
                continue
            if in_done and re.match(r"^\s*[-*] ", ln) and not ln.startswith((" ", "\t")):
                d = line_date(ln, t)
                item_old = bool(d and (today - d).days > 7)
            if in_done and item_old and ln.strip():
                key = (line_date(ln, t) or today).strftime("%Y-%m")
                old.setdefault(key, []).append(ln)
                moved["board"] += 1
            else:
                out.append(ln)
        for key, items in sorted(old.items()):
            append(f"board-{key}.md", items)
        if moved["board"]:
            write_atomic(board, "".join(out))
    alerts = os.path.join(PANTHEON, "alerts.md")
    if os.path.exists(alerts):
        with lock("alerts"):
            lines = open(alerts, encoding="utf-8").read().splitlines(keepends=True)
            out, old = [], {}
            for ln in lines:
                m = re.match(r"^(\d{4})-(\d{2})-(\d{2}) \d{2}:\d{2} · ", ln)
                if m and (today - datetime(int(m[1]), int(m[2]), int(m[3]))).days > 30:
                    old.setdefault(f"{m[1]}-{m[2]}", []).append(ln)
                    moved["alerts"] += 1
                else:
                    out.append(ln)
            for key, items in sorted(old.items()):
                append(f"alerts-{key}.md", items)
            if moved["alerts"]:
                write_atomic(alerts, "".join(out))
    lk.__exit__(None, None, None)
    print(f"в архив: доска — {moved['board']} строк, тревоги — {moved['alerts']} строк")
    return 0


# Имена окон, которые не направления: sandbox_build пишет settings/hq.json, workshop.json и job-<роль>.json; направление
# с таким именем записало бы свои настройки в чужой файл — а при сбое второй записи они там и остались бы (metis-0163)
RESERVED_DIRECTIONS = ("hq", "workshop")


def reserved_direction(name):
    """Текст ошибки, если имя направления зарезервировано под окно hq, workshop или job-*; иначе None."""
    if isinstance(name, str) and (name in RESERVED_DIRECTIONS or name.startswith("job-")):
        return (f"имя «{name}» зарезервировано под окна системы (hq, workshop, job-*): настройки направления "
                "записались бы в чужой файл окна — выберите другое имя")
    return None


def domains_build(if_changed=False):
    """Реестр направлений → domains.json для guard. Привилегий тут нет: они в ~/.claude/pantheon/policy.toml.
    Папку привилегированного координатора (из [coordinators] policy.toml) чужое направление получить не может:
    такая папка пропускается с тревогой — иначе правкой реестра можно было бы отдать чужому код guard или me/."""
    reg_path = os.path.join(PANTHEON, "directions.toml")
    policy_path = os.path.join(HOME, ".claude", "pantheon", "policy.toml")
    if if_changed:
        built = read_json(path("domains.json")).get("built_ts") or 0
        # и новые папки сессий: правило Read окна штаба закрывает чужие шаблонами по префиксам — новый префикс тоже должен
        # попасть в hq.json
        # и каталог ролей: новая роль с memory: должна попасть в песочницу окон (metis-0051). Цикла нет: roles_build
        # пишет файл, только если текст изменился, — пересборка одна, следующий тик уже тихий
        # и проектные настройки папок запуска направлений: allow с gh pr merge роняет окно (metis-0137)
        launches = [launch_folder(fs) for fs in (read_json(path("domains.json")).get("domains") or {}).values()]
        watched = (reg_path, policy_path, os.path.join(HOME, ".claude", "projects"), AGENTS, CLAUDE_TMP,
                   *(os.path.join(l, ".claude", fn) for l in launches if l for fn in PROJECT_SETTINGS_FILES))
        newest = max([os.path.getmtime(p) for p in watched if os.path.exists(p)] + [roles_newest()])
        # и пропавшее окно задачи расписания (P0-3): без него задача не идёт — в том числе сразу после обновления
        if built >= newest and all(os.path.isfile(job_window(r)) for r in JOB_ROLES):
            return 0
    with open(reg_path, "rb") as fh:
        reg = tomllib.load(fh)
    try:
        with open(policy_path, "rb") as fh:
            priv = tomllib.load(fh).get("coordinators") or {}
    except (OSError, ValueError):
        priv = {}
    norm = lambda p: os.path.realpath(os.path.expanduser(p))
    overlap = lambda a, b: a == b or a.startswith(b.rstrip("/") + "/") or b.startswith(a.rstrip("/") + "/")
    domains, stores, leads = {}, {}, {}
    for d in reg.get("direction") or []:
        name = d.get("name", "")
        if not re.fullmatch(r"[a-z0-9-]+", name):
            print(f"пропущено направление с именем не по образцу: {name!r}", file=sys.stderr)
            continue
        bad = reserved_direction(name)
        if bad:
            print(f"пропущено направление: {bad}", file=sys.stderr)
            alert_once(f"direction-reserved-{name}", "1", f"directions.toml: {bad}", "pantheon")
            continue
        folders = []
        for f in d.get("folders") or []:
            owner = next((o for o, ps in priv.items() if o != name and any(overlap(norm(f), norm(p)) for p in ps)), None)
            if owner:
                alert_once(f"domains-{name}-{f}", "1", f"directions.toml: папка {f} отдана направлению {name}, "
                           f"но это папка {owner} (policy.toml) — пропущена при сборке domains.json", "pantheon")
                continue
            folders.append(f)
        domains[name] = folders
        if isinstance(d.get("pnpm_store"), str):
            stores[name] = d["pnpm_store"]
        # лиды направления — субагенты его окна (P0-6); имена как у roles_build
        bases = d.get("leads") if isinstance(d.get("leads"), list) else []
        if re.fullmatch(r"[a-z0-9]+-[a-z0-9-]+", name):
            short = name.split("-", 1)[1]
            leads[name] = [f"{b}-{short}" for b in LEAD_ROLES if b in bases]
    write_json(path("domains.json"), {
        "_comment": "Собрано `pantheon domains build` из ~/ai/pantheon/directions.toml. Руками не править.",
        "built": stamp(), "built_ts": now(), "domains": domains})
    # живую сессию с проблемой проектных allow останавливает только путь тика (--if-changed): ручная сборка и тесты
    # зовут её с настоящим claude в PATH — claude stop из них остановил бы ваши сессии
    built = sandbox_build(domains, policy_path, stores, leads, stop_live=if_changed)
    os.makedirs(path("locks"), exist_ok=True)
    for slot in ("heavy-cmd-1", "heavy-cmd-2", "heavy-server"):  # места обёртки heavy: роль в песочнице сама их не создаст
        open(path("locks", slot + ".lock"), "a").close()
    roles = roles_build()
    if roles:
        print(f"роли: {', '.join(roles)}")
    if not if_changed:
        print(f"domains.json: {len(domains)} направлений → {path('domains.json').replace(HOME, '~')}; "
              f"настройки окон ролей: {', '.join(built)} → {path('settings').replace(HOME, '~')}/")
    return 0


# Песочница окон ролей (SEC-19): файл для `claude … --settings <файл>` у каждого направления и у мастерской.
# Строгий вид: без отката мимо песочницы, без неё сессия не стартует. Писать можно в папку запуска, папки
# направления внутри ~/projects и ~/ai/knowledge, своё ~/ai/pantheon/directions/<имя>/, свою папку кэшей и временную
# папку. Общие кэши инструментов закрыты: ими пользуются ваши сессии без песочницы, поэтому кэши направления
# (npm, pnpm, uv, pip, corepack, ~/.cache через XDG_CACHE_HOME) — свои, через переменные окружения. Сверх
# этого — только [sandbox_write] из policy.toml (правит Метида), не из реестра: правкой реестра права не выдать.
# .git/config и .git/hooks закрыты для записи: сетевой git направлений (и мастерской с SSH-remote) и gh идут мимо песочницы.
# Личное из [private] policy.toml закрыто для чтения всем, кроме координаторов с этой привилегией.
# Сеть — через прокси песочницы: хосты вне списка проверяет классификатор режима auto.
# Пути в файле — настоящие абсолютные (свои у каждого Mac): ссылка, подставленная позже, их не сдвинет.
# Хранилище pnpm по умолчанию не подменяется: node_modules помнит своё хранилище, и разные хранилища у координатора и
# ваших сессий в одной папке ломают pnpm (вопрос «modules directory will be removed», без терминала — код 0 и ничего не
# поставлено). Общее хранилище направления — поле pnpm_store реестра (путь внутри папок направления): окно получает
# npm_config_store_dir, а ваш терминал — тот же store-dir в .npmrc проекта (вариант А athena-0001, 15.10). Переменная
# нужна копиям разработчиков: .npmrc вне git в них не попадает.
# Координаторам там же — окно сжатия 200k (CTX-04).
SANDBOX_ROOTS = ["~/projects", "~/ai/knowledge"]   # папки направлений для песочницы — только внутри этих
SANDBOX_DOMAINS = ["registry.npmjs.org", "registry.yarnpkg.com", "pypi.org", "files.pythonhosted.org",
                   "github.com", "api.github.com", "codeload.github.com", "objects.githubusercontent.com",
                   "raw.githubusercontent.com"]
# Мимо песочницы: gh (в ней не работает — TLS Go на macOS) — только эти подкоманды; дописать тревогу. Всё, что не
# исключено, в песочнице просто падает — это и есть отказ (P0-4, metis-0064): `gh api` и `gh issue` (любые записи в
# GitHub) не выпускаются; из `gh pr` и `gh run` — только чтение (`gh run cancel|rerun|delete` падают). Голые формы —
# отдельно: шаблон «… *» их не покрывает
GH_PR_READ = [f"gh pr {c}{tail}" for c in ("view", "checks", "diff", "list") for tail in ("", " *")]
GH_RUN_READ = [f"gh run {c}{tail}" for c in ("view", "list", "watch") for tail in ("", " *")]
SANDBOX_EXCLUDED = GH_PR_READ + GH_RUN_READ + ["gh repo view *", "gh auth status",
                                 "pantheon alert *", "pantheon consent *", "pantheon saved *"]
# PR создают и правят (заголовок, описание, метки — `gh pr edit`, metis-0247) лиды, сливает координатор или лид —
# только окна направлений; кто и что сливает, проверяет guard (merge_problem). Мастерской — нет
GH_PR_WRITE = ["gh pr create *", "gh pr edit *", "gh pr merge *"]
# штаб (metis-0247, «да» владельца 19.10 [zeus-0247-yes]): сети у окна нет, а gh в песочнице всё равно падает (TLS Go,
# x509 -26276) — мимо неё только чтение PR и правка. Слияния здесь нет (решение Зевса 19.10, metis-0247 r4): gh pr
# merge, gh api и прочий gh остаются в песочнице без сети и падают; guard (hq-gh) вдобавок отказывает слиянию в любой
# форме — `gh -R o/r pr merge`, GH_REPO=…, gh api …/merge
HQ_GH = [f"gh pr {c}{tail}" for c in ("view", "checks") for tail in ("", " *")] + ["gh pr edit *"]
# git по SSH в песочнице macOS не работает, по HTTPS push упирается в помощник учётных данных: окну каждого направления
# сетевые команды git — мимо неё; мастерской — только при SSH-remote. push в main/master, --force и --delete не
# пускает guard (_PUSH_BAD)
GIT_NETWORK = ["git push", "git push *", "git fetch", "git fetch *", "git pull", "git pull *"]
COORDINATOR_COMPACT = 200000


# Правила слияния через шлюз guard (permissions.allow и autoMode.allow окон координаторов) — в lib/window_rules.py:
# он в ядре защит (metis-0174), его PR ждёт слияния владельцем. Имена здесь — для прежних вызовов и тестов
def _window_rules():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_window_rules", os.path.join(LIB, "window_rules.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


WINDOW_RULES = _window_rules()
COORDINATOR_ALLOW = WINDOW_RULES.COORDINATOR_ALLOW
MERGE_REPO_RE = WINDOW_RULES.MERGE_REPO_RE
GATED_MERGE_RULE = WINDOW_RULES.GATED_MERGE_RULE
LEAD_DELIVERY_RULE = WINDOW_RULES.LEAD_DELIVERY_RULE
REVIEW_RECORD_RULE = WINDOW_RULES.REVIEW_RECORD_RULE
coordinator_auto_allow = WINDOW_RULES.coordinator_auto_allow

# Роли главных сессий: их память в песочницу не добавляется, даже если в шапке есть memory:
MAIN_ROLES = ("hq", "domain-coordinator", "workshop")
# Субагенты главной сессии окна (P0-6; SEC-09, SEC-13, ROLE-32): штаб и координатор зовут только этих — general-purpose
# и claude (веб и все инструменты) обошли бы запреты окна. Проверяет хук hooks/agents.py и только у главной сессии (в
# её событии нет agent_id): tools: Agent(…) в шаблоне роли и permissions.deny действуют и на субагентов окна — лид не
# позвал бы своих dev-*, навык audit — general-purpose. В deny окна — только жёсткие границы, не нужные и лидам.
# Координатору — ещё свои лиды (из реестра). Explore — только чтение: без него координатор читает код в свой контекст
# (CTX-09); веба через него не больше, чем через prometheus и лидов. clio зовут Зевс и mnemo-brain (роль clio).
# momus — ревизор навыка audit (metis-0095, решение владельца 15.10): только чтение и веб, пишет лишь свой отчёт в
# ~/ai/knowledge/Inbox. Координаторам его нет — без отдельного слова владельца.
HQ_AGENTS = ["prometheus", "clio", "chiron", "momus", "Explore"]
# dev-haiku, dev-sonnet, dev-opus — разработчики: координатор отдаёт им мелкие правки сам, не гоняя лида (эпик
# «Альфа»); codex-dev сюда не входит — его зовёт только лид по правилу executor.
COORDINATOR_AGENTS = ["argus", "talos", "prometheus", "Explore", "dev-haiku", "dev-sonnet", "dev-opus"]
COORDINATOR_EXTRA_AGENTS = {"mnemo-brain": ["clio"]}
# Skill — навык с context: fork идёт субагентом своего agent: мимо инструмента Agent (Claude Code 2.1.292)
AGENT_MATCHER = "Agent|Task|Skill"
# копия из ~/.claude/plugins, а не рабочая копия agent-kit — довод как у MARKET_GUARD (guard_script)
# Отдельный файл, а не команда ctx.py: старая копия ctx.py без команды пропускала бы всё, а отсутствующий agents.py
# — код 2 у python, то есть блок (onFailure: block работает только с Claude Code 2.1.295).
MARKET_AGENTS = os.path.join(HOME, ".claude", "plugins", "marketplaces", "agent-kit", "plugins", "pantheon", "hooks",
                             "agents.py")
# terminal-notifier по щелчку открывает ссылку или выполняет команду — от имени владельца, вне песочницы. Ролям его
# не прочитать, а значит и не запустить: уведомления Пантеона шлёт только тик (поддельное «от Пантеона» не пройдёт).
NOTIFIER_PATHS = ["/opt/homebrew/Cellar/terminal-notifier", "/opt/homebrew/opt/terminal-notifier",
                  "/usr/local/Cellar/terminal-notifier", "/usr/local/opt/terminal-notifier"]


def ssh_remote(folder):
    """Есть ли у репозитория в папке (или в её подпапках первого уровня) remote по SSH."""
    root = os.path.expanduser(folder)
    repos = [root] + ([os.path.join(root, x) for x in sorted(os.listdir(root))] if os.path.isdir(root) else [])
    for r in repos:
        if not os.path.exists(os.path.join(r, ".git")):
            continue
        out = subprocess.run(["git", "-C", r, "remote", "-v"], capture_output=True, text=True).stdout
        if re.search(r"\s(ssh://|[\w.-]+@[\w.-]+:)", out):
            return True
    return False


def _real_dir(p, roots, strict=False, create=False):
    """Папка от ~/ внутри одной из roots → её настоящий абсолютный путь; None — вне них, ссылка или папки нет.
    В настройки идёт настоящий путь, а не «~/…»: подмена папки ссылкой после сборки не сдвинет границу."""
    if not isinstance(p, str) or not p.startswith("~/") or "*" in p or ".." in p.split("/"):
        return None
    x = os.path.expanduser(p)
    if create and not os.path.lexists(x):
        os.makedirs(x, exist_ok=True)
    if os.path.islink(x) or not os.path.isdir(x):
        return None
    k = os.path.realpath(x)
    for r in roots:
        rk = os.path.realpath(os.path.expanduser(r))
        if k.startswith(rk + "/") or (k == rk and not strict):
            return k
    return None


# закрытые штабу папки (индексы qmd, копии больших корпусов, сырые выгрузки — чужой текст; штабу его не читать: у
# штаба личное и действия наружу) — [hq].closed_dirs policy.toml, в коде их нет (metis-0182, разбор — hq_policy в
# hooks/ctx.py). Вопросы по ним — координатору направления поручением; коллекции qmd штабу закрывает хук qmd-query


# выводы фоновых задач и TMPDIR песочницы всех сессий Claude Code: /tmp/claude-<uid> (на macOS по умолчанию). Не из
# CLAUDE_CODE_TMPDIR: внутри сессии Claude Code ставит его уже с /claude-<uid> на конце. PANTHEON_CLAUDE_TMP — тестам
CLAUDE_TMP = os.path.realpath(os.environ.get("PANTHEON_CLAUDE_TMP") or os.path.join("/tmp", f"claude-{os.getuid()}"))
# Seatbelt не собирает профиль больше 64 КБ: Bash окна не запускается совсем («sandbox-exec: data object length …
# exceeds maximum (65535)», hq 15.10 — 4359 путей). Оценка — сумма байтов путей песочницы окна; это не размер
# профиля: 15.10 hq с 985 путями (~150 КБ путей) Bash запускал, а 4359 путей дали 69 833 байт, — порог с запасом в
# безопасную сторону. Списки ~/.claude/settings.json, которые сливаются с окном, не учтены. Выше порога окно не
# пересобирается (остаётся прежний файл) и приходит тревога
try:
    SANDBOX_SIZE_LIMIT = int(os.environ.get("PANTHEON_SANDBOX_LIMIT") or 48 * 1024)
except ValueError:
    SANDBOX_SIZE_LIMIT = 48 * 1024
GLOB_SAFE = re.compile(r"[A-Za-z0-9._-]+")


def _others_globs(names, own, keep=()):
    """Папки чужих сессий среди names → немного шаблонов «<префикс>*» (и точных имён), ни один из которых не совпадает
    со своими: own, own--claude-worktrees-* и имена на префиксы keep (они остаются открыты). Префикс — до первой
    буквы, где имя расходится со всеми своими, поэтому тысячи guard-test-* дают один «g*»: список не растёт с числом
    папок. Имя с символами шаблона пропускается — вернётся в skipped."""
    wt = own + "--claude-worktrees-"
    mine = (own, wt) + tuple(keep)
    out, skipped = set(), []
    for n in names:
        if n == own or n.startswith(wt) or n.startswith(tuple(keep)):
            continue
        p = next((n[:i] for i in range(1, len(n) + 1) if not any(m.startswith(n[:i]) for m in mine)), None)
        x = n if p is None else p + "*"
        if GLOB_SAFE.fullmatch(n if p is None else p):
            out.add(x)
        else:
            skipped.append(n)
    return sorted(out), skipped


def sandbox_size(data):
    """Байты путей песочницы окна: списки filesystem и правила Read/Edit (Claude Code добавляет их в песочницу)."""
    fs = (data.get("sandbox") or {}).get("filesystem") or {}
    perms = data.get("permissions") or {}
    items = [x for k in ("allowWrite", "denyWrite", "denyRead", "allowRead") for x in fs.get(k) or []]
    items += [x for k in ("deny", "allow", "ask") for x in perms.get(k) or [] if x.startswith(("Read(", "Edit("))]
    return sum(len(x.encode()) + 1 for x in items)


def write_window(out_dir, name, data):
    """Файл окна, если его песочница в пределах SANDBOX_SIZE_LIMIT; иначе тревога и прежний файл остаётся."""
    size, key = sandbox_size(data), f"sandbox-size-{name}"
    if size > SANDBOX_SIZE_LIMIT:
        print(f"песочница {name}: {size} байт путей > {SANDBOX_SIZE_LIMIT} — окно не пересобрано", file=sys.stderr)
        alert_once(key, "over", f"песочница окна {name}: {size} байт путей, предел {SANDBOX_SIZE_LIMIT} (профиль Seatbelt "
                   "до 64 КБ, иначе Bash окна не запускается) — окно не пересобрано, оставлен прежний файл. Сжать "
                   "списки в sandbox_build (каталоги и шаблоны вместо перечисления)", "pantheon",
                   note=f"Песочница окна {name} не помещается в предел — окно не пересобрано")
        return False
    clear_once(key)
    write_json(os.path.join(out_dir, name + ".json"), data)
    return True


def _deny_forms(paths):
    """Запрет и в виде «~/…», и настоящим путём: правила разрешений — настоящие пути, запреты должны совпасть."""
    out = []
    for p in paths:
        for x in (p, os.path.realpath(os.path.expanduser(p))):
            if x not in out:
                out.append(x)
    return out


# Строгий guard окна роли (SEC-29): тот же guard.py, но с --strict и onFailure "block" — сбой, таймаут, плохой вход
# или пропавший файл защиты останавливают действие, а не пропускают. Путь — только клон маркетплейса внутри
# ~/.claude/plugins (туда ролям писать нельзя: protect-config), а не «рядом с этим плагином»: рабочая копия
# ~/projects/agent-kit — папка metis-pantheon, её правят субагенты, и подменённый там guard стал бы защитой окон
# (находка проверки безопасности 14.10). Ваших сессий без роли это не касается. Agent|Task|Skill — правила
# hq-telegram и chiron (P0-1, P0-2): штабу — ни tg-reader, ни telegram-read; коуч с личным — только у Зевса.
GUARD_MATCHER = "Bash|Write|Edit|MultiEdit|NotebookEdit|Read|Grep|Glob|Agent|Task|Skill"
MARKET_GUARD = os.path.join(HOME, ".claude", "plugins", "marketplaces", "agent-kit", "plugins", "guard", "hooks", "guard.py")


def guard_script():
    if os.path.isfile(MARKET_GUARD) and not os.path.islink(MARKET_GUARD):
        return os.path.realpath(MARKET_GUARD)
    return MARKET_GUARD  # файла нет — окно роли не пустит ни одной записи (отказ при сбое), тревога в sandbox_build


def agents_script():
    if os.path.isfile(MARKET_AGENTS) and not os.path.islink(MARKET_AGENTS):
        return os.path.realpath(MARKET_AGENTS)
    return MARKET_AGENTS  # файла нет — python выйдет с кодом 2, окно не позовёт никого; тревога в sandbox_build


def agents_window(data, allowed, deny, script):
    """Окну (P0-6): хук `agents.py <список>` для главной сессии и правила deny Agent(<тип>) на всё окно. Запись
    guard и прежние правила (Read у штаба) остаются; без дублей, порядок стабильный."""
    uniq = lambda xs: list(dict.fromkeys(xs))  # noqa: E731
    data.setdefault("hooks", {}).setdefault("PreToolUse", []).append({"matcher": AGENT_MATCHER, "hooks": [{
        "type": "command", "command": f"python3 {shlex.quote(script)} {shlex.quote(','.join(uniq(allowed)))}",
        "timeout": 10, "onFailure": "block"}]})
    rules = data.setdefault("permissions", {}).setdefault("deny", [])
    rules.extend([r for r in uniq(f"Agent({x})" for x in deny) if r not in rules])
    return data


def role_settings(folders, own_dir, extra_write, cache, ssh, deny_read, compact=None, guard=None, auto_allow=None):
    allow = list(folders) + ([own_dir] if own_dir else []) + list(extra_write) + [cache]
    # .git/config и .git/hooks — внутри каждой разрешённой папки (её настоящим путём) и под ~ в целом
    # .claude/agents — роли агентов репозитория: guard protect-config закрывает запись хуком (guard 0.5.6, #26), но
    # Bash-запись мимо хука останавливает только песочница (metis-0140); и в worktree внутри репозитория тоже
    deny_write = ["~/**/.git/config", "~/**/.git/hooks"] + [f"{r}{sub}" for r in allow for sub in (
        "/.git/config", "/.git/hooks", "/**/.git/config", "/**/.git/hooks", "/.claude/agents", "/**/.claude/agents")]
    data = {
        "_comment": "Собрано `pantheon domains build` из ~/ai/pantheon/directions.toml и policy.toml (SEC-19). Руками не править.",
        "env": {
            "XDG_CACHE_HOME": os.path.join(cache, "xdg"),
            "npm_config_cache": os.path.join(cache, "npm"),
            "npm_config_devdir": os.path.join(cache, "node-gyp"),
            "COREPACK_HOME": os.path.join(cache, "corepack"),
            "UV_CACHE_DIR": os.path.join(cache, "uv"),
            "PIP_CACHE_DIR": os.path.join(cache, "pip"),
            "NEXT_TELEMETRY_DISABLED": "1",
            "TURBO_TELEMETRY_DISABLED": "1",
            "DO_NOT_TRACK": "1",
        },
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": SANDBOX_EXCLUDED + (GIT_NETWORK if ssh else []),
            "filesystem": {
                "allowWrite": allow,
                "denyWrite": deny_write,
                "denyRead": _deny_forms(deny_read) + NOTIFIER_PATHS,
            },
            "network": {"allowedDomains": SANDBOX_DOMAINS},
        },
    }
    if guard:
        data["hooks"] = {"PreToolUse": [{"matcher": GUARD_MATCHER, "hooks": [{
            "type": "command", "command": f"python3 {shlex.quote(guard)} --strict", "timeout": 10,
            "onFailure": "block"}]}]}
    if compact:
        # координатор: окно сжатия 200k (CTX-04); фоновая сессия уходит в свою worktree, и worktree работников лида
        # ответвляются от неё (HEAD ветки эпика), а не от основной ветки (по умолчанию — "fresh")
        data["autoCompactWindow"] = compact
        data["worktree"] = {"baseRef": "head"}
    if auto_allow:
        # окна координаторов: исключения классификатора auto под шлюз слияния (coordinator_auto_allow, metis-0098)
        data["autoMode"] = WINDOW_RULES.auto_mode(auto_allow)
    return data


def _read_small_regular(p, limit=8 << 20):
    """Текст обычного файла не больше limit, иначе None. Папки проекта пишут роли, а читает тик вне песочницы:
    FIFO, устройство или ссылка вместо файла не должны его повесить, огромный файл — съесть память."""
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        with os.fdopen(fd, "rb", closefd=False) as fh:
            return fh.read(limit).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def memory_dirs():
    """Папки ~/.claude/agent-memory/<роль> ролей-субагентов с ключом memory: в шапке (metis-0051): их Bash-запись
    песочнице окна иначе недоступна. Настоящие пути; папку создаёт, ссылку вместо папки пропускает."""
    out = []
    try:
        names = sorted(os.listdir(AGENTS))
    except OSError:
        return out
    for f in names:
        role = f[:-3]
        if not f.endswith(".md") or not ROLE_NAME.fullmatch(role) or role in MAIN_ROLES:
            continue
        text = _read_small_regular(os.path.join(AGENTS, f))
        if text is None or "memory" not in (_head_keys(text) or []):
            continue
        d = _real_dir(f"~/.claude/agent-memory/{role}", ["~/.claude/agent-memory"], strict=True, create=True)
        if d:
            out.append(d)
    return out


def pnpm_store_check(name, folders, store):
    """node_modules на этом Mac собраны с другим хранилищем (store-dir в .npmrc не в git — на другой Mac не приезжает):
    pnpm в окне спросит, сносить ли node_modules, и без терминала молча ничего не поставит — тревога с командой."""
    for f in folders:
        try:
            subs = sorted(os.path.join(f, x) for x in os.listdir(f) if not x.startswith(".")
                          and stat.S_ISDIR(os.lstat(os.path.join(f, x)).st_mode))
        except OSError:
            subs = []
        for d in [f] + subs:
            text = _read_small_regular(os.path.join(d, "node_modules", ".modules.yaml"))
            if text is None:
                continue
            m = re.search(r"^storeDir:\s*(\S+)", text, re.M)
            got = os.path.realpath(m.group(1)) if m else ""
            if got and got != store and os.path.dirname(got) != store:
                alert_once(f"pnpm-store-{name}-{d}", got, f"{name}: {d.replace(HOME, '~')}/node_modules собраны с "
                           f"хранилищем {got.replace(HOME, '~')}, а у направления {store.replace(HOME, '~')} — pnpm в окне "
                           f"ничего не поставит. В {d.replace(HOME, '~')}: .npmrc со строкой store-dir={store} (в "
                           ".git/info/exclude), затем CI=true pnpm install --frozen-lockfile", "pantheon")


# [private] из policy.toml читается по правилу guard 0.5.9 (metis-0163): окно и guard не должны расходиться во мнении,
# у кого личное. Умолчание — то же, что DEFAULT_PRIVATE у guard.
DEFAULT_PRIVATE = {"roles": ["hq", "chiron"], "coordinators": ["mnemo-brain"],
                   "paths": ["~/ai/knowledge/me", "~/ai/knowledge/.git/git-crypt", "~/ai/pantheon/.git/git-crypt",
                             "~/.local/state/pantheon/owner-log/zeus.md"]}


def private_conf(policy):
    """[private]: не таблица — всё по умолчанию; ключа нет или значение не список — умолчание; список — только его
    строки (strip, пустые убраны). roles и coordinators: пустой список — никого; paths: пустой список или без строк —
    умолчание."""
    p = policy.get("private") if isinstance(policy, dict) else None
    if not isinstance(p, dict):
        p = {}
    conf = {}
    for k, v in DEFAULT_PRIVATE.items():
        val = p.get(k)
        if not isinstance(val, list):
            conf[k] = list(v)
            continue
        items = [x.strip() for x in val if isinstance(x, str) and x.strip()]
        conf[k] = items if items or k != "paths" else list(v)
    return conf


# Образцы команд слияния в обход шлюза слияния: правило allow, которому подходит любая из них, срабатывает раньше
# классификатора режима auto, и формы --admin и --auto классификатор не судит (metis-0137)
MERGE_SAMPLES = ("gh pr merge 12 --admin", "gh pr merge 12 --auto --merge")
MERGE_CMD = "gh pr merge"
PROJECT_SETTINGS_FILES = ("settings.json", "settings.local.json")


# Обёртки, запускающие любую команду: правило `env *` пускает и `env gh pr merge 12 --admin`. У оболочек обёртка —
# только `-c` (`bash ./run.sh *` — свой скрипт); флаги env с аргументом снимаются вместе с ним
WRAP_SHELLS = ("bash", "sh", "zsh")
ENV_ARG_FLAGS = ("-u", "-c", "-p")
ASSIGN_RX = r"[a-z_][a-z0-9_]*=\S*"


def unwrap_rule(inner):
    """(остаток, была ли обёртка): снимает с начала шаблона VAR=значение, путь к программе (`/x/y/gh` → `gh`) и
    обёртки env, command, xargs, eval, `bash|sh|zsh -c` с необязательной кавычкой. Остаток None — `command -v …`:
    поиск программы, а не запуск."""
    wrapped = False
    while True:
        words = inner.split(" ") if inner else []
        while len(words) > 1 and re.fullmatch(ASSIGN_RX, words[0]):
            words = words[1:]
        if not words:
            return "", wrapped
        prefix, slash, base = words[0].rpartition("/")
        if slash and base and not base.startswith("*") and "*" not in prefix:
            words[0] = base
        first, words = words[0], words[1:]
        if first == "env":  # VAR= после флагов снимет следующий проход цикла
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ENV_ARG_FLAGS else words[1:]
        elif first in ("command", "xargs"):
            while words and words[0].startswith("-"):
                if first == "command" and "v" in words[0]:
                    return None, True
                words = words[1:]
        elif first in WRAP_SHELLS:
            short = lambda w: w.startswith("-") and not w.startswith("--")  # noqa: E731
            while words and short(words[0]) and "c" not in words[0]:
                words = words[1:]
            if words and short(words[0]):
                words = words[1:]
            elif not (words and words[0].startswith("*")):  # не -c и не звёздочка на его месте — запуск скрипта
                return " ".join([first, *words]), wrapped
            if words and words[0][:1] in ("'", '"'):
                q, words[0] = words[0][0], words[0][1:]
                if words[-1].endswith(q):
                    words[-1] = words[-1][:-1]
                words = [w for w in words if w]
        elif first != "eval":
            return " ".join([first, *words]), wrapped
        wrapped = True
        inner = " ".join(words)


def allow_rule_merges(rule):
    """Пускает ли правило permissions.allow `gh pr merge`: "Bash", "Bash(*)", Bash(<шаблон>), где буквальное начало
    шаблона до первой звёздочки — начало «gh pr merge» или само начинается с «gh pr merge» (флаги в любом порядке,
    точная форма без звёздочки тоже), либо шаблон как glob подходит к одному из MERGE_SAMPLES. Пробелы схлопываются,
    регистр не важен, «:*» на конце — « *». Перед проверкой unwrap_rule снимает ведущие VAR=значение, путь к
    программе (`/opt/homebrew/bin/gh *` — это `gh *`) и обёртки, пускающие любую команду: env с флагами и VAR=,
    command, xargs с флагами, eval, `bash|sh|zsh -c`. Поэтому `env *`, `bash -c *`, `command /x/gh *` ловятся, а
    обёртка без звёздочки и без команды после неё (`env`, `command -v gh`) — нет. Не ловятся свои скрипты-обёртки
    (`./run.sh *`), sudo, nohup, timeout, `exec gh *`, `time gh *`, `nice gh *` и подобное: граница — песочница и
    guard (README)."""
    if not isinstance(rule, str):
        return False
    rule = rule.strip()
    if rule == "Bash":
        return True
    if not (rule.startswith("Bash(") and rule.endswith(")")):
        return False
    inner = rule[5:-1].strip()
    if inner.endswith(":*"):
        inner = inner[:-2] + " *"
    inner = " ".join(inner.split()).lower()
    inner, wrapped = unwrap_rule(inner)
    if inner is None or (wrapped and not inner):
        return False
    head = inner.split("*", 1)[0]
    if MERGE_CMD.startswith(head) or head.startswith(MERGE_CMD):
        return True
    rx = ".*".join(re.escape(x) for x in inner.split("*"))
    return any(re.fullmatch(rx, smp) for smp in MERGE_SAMPLES)


def project_allow_problems(launch):
    """[(файл, правило)] — allow в .claude/settings.json и settings.local.json папки запуска, пускающие `gh pr merge`."""
    found = []
    for fn in PROJECT_SETTINGS_FILES:
        f = os.path.join(launch, ".claude", fn)
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        perms = data.get("permissions") if isinstance(data, dict) else None
        allow = perms.get("allow") if isinstance(perms, dict) else None
        for r in allow if isinstance(allow, list) else []:
            if allow_rule_merges(r):
                found.append((f, r))
    return found


def project_allow_text(name, problems):
    shown = lambda f: f.replace(HOME, "~", 1) if f.startswith(HOME + os.sep) else f  # noqa: E731
    return (f"направление {name}: " + "; ".join(f"{shown(f)} — allow «{r}» пускает gh pr merge" for f, r in problems)
            + " — правило срабатывает раньше классификатора auto и открывает слияние --admin/--auto мимо шлюза "
            "слияния: убрать правило или сузить его до нужных команд gh (gh pr view *, gh pr checks *…)")


def drop_window(name):
    """Убрать оба файла окна: settings/<имя>.json и файл запуска settings/run/<имя>.json — `claude respawn` берёт
    прежние флаги с путём к нему (ревью argus PR #32). Без файла окна не поднимают ни pantheon start, ни wake, ни
    дежурный."""
    for f in (path("settings", name + ".json"), path("settings", "run", name + ".json")):
        with contextlib.suppress(OSError):
            os.remove(f)


def allow_gate(name, folders=None):
    """Проектные allow папки запуска направления name (metis-0137): есть правило с gh pr merge — оба файла окна
    убираются. Зовут сборка, тик (check) и каждый подъём сессии: сборка по --if-changed сравнивает только mtime, а
    файл со старым mtime (cp -p, rsync -a, tar) её не запускает (ревью argus PR #32). folders — папки из domains.json;
    не направление (мастерская, штаб) — проверки нет. → список проблем."""
    if folders is None:
        folders = (read_json(path("domains.json"), {}).get("domains") or {}).get(name)
    problems = project_allow_problems(launch_folder(folders)) if folders else []
    if problems:
        drop_window(name)
    return problems


def project_allow_report(name, problems, quiet=True):
    """Проблемы папки запуска направления (allow_gate): тревога (quiet) или строка в stdout; без проблем тревога
    снимается. → список проблем."""
    key = "project-allow-" + name
    if problems:
        text = project_allow_text(name, problems)
        if quiet:
            alert_once(key, json.dumps(problems), text, "pantheon")
        else:
            print(f"предупреждение · {text}")
    else:
        clear_once(key)
    return problems


def project_allow_stop(name, problems):
    """Тик нашёл у направления allow с gh pr merge: Claude Code перечитывает настройки на ходу, и в работающем окне
    правило уже действует — живую сессию (и её копии «имя (2)») останавливаем claude stop, с тревогой. Окно уже
    убрано, поэтому поднять её снова не даст никто (pantheon start, wake, дежурный). Вкладку терминала claude stop не
    остановит — она в тревоге. → id остановленных."""
    live = live_copies(name, agents_all() or [])
    if not live:
        clear_once("project-allow-stop-" + name)
        return []
    ids = [a for a in live if a.get("id")]
    tabs = [a for a in live if not a.get("id")]
    stop_copies(name, ids, "stop-project-allow")
    text = (f"{name}: остановлена работающая сессия ({', '.join(a['id'] for a in ids) or '—'}) — "
            + project_allow_text(name, problems)
            + (f"; открыта во вкладке терминала (pid {', '.join(str(a.get('pid')) for a in tabs)}) — её закройте сами"
               if tabs else "")
            + ". Поднять снова — после правки и pantheon domains build")
    alert_once("project-allow-stop-" + name, ",".join(str(a.get("id") or a.get("pid")) for a in live), text, "pantheon")
    return [a["id"] for a in ids]


def sandbox_build(domains, policy_path, stores=None, leads=None, stop_live=False):
    """domains.json и policy.toml → ~/.local/state/pantheon/settings/<направление>.json и workshop.json.
    leads — {направление: ["hephaestus-<коротко>", "apollo-<коротко>"]}: субагенты окна (P0-6). stop_live — путь тика
    (domains build --if-changed): живую сессию направления с проблемой проектных allow остановить."""
    try:
        with open(policy_path, "rb") as fh:
            policy = tomllib.load(fh)
    except (OSError, ValueError):
        policy = {}
    extra = policy.get("sandbox_write") or {}
    private = private_conf(policy)
    private_paths = [p for p in private["paths"] if p.startswith("~/")]
    private_dirs = set(private["coordinators"])
    caches = "~/Library/Caches/pantheon-sandbox"
    out_dir = path("settings")
    guard = guard_script()
    if not os.path.isfile(guard):
        alert_once("guard-missing", guard, f"нет {guard.replace(HOME, '~')}: окна ролей не пропустят ни одной записи "
                   "(строгий guard, SEC-29) — переустановить плагин guard", "pantheon")
    agents_py = agents_script()
    if not os.path.isfile(agents_py):
        alert_once("agents-missing", agents_py, f"нет {agents_py.replace(HOME, '~')}: окна Пританея и координаторов не позовут ни одного "
                   "субагента (хук agents.py, P0-6) — переустановить плагин pantheon", "pantheon")
    leads = leads or {}
    all_leads = [x for n in leads for x in leads[n]]
    os.makedirs(out_dir, exist_ok=True)

    memory = memory_dirs()

    def one(name, folders, own, compact, deny, allow=None, agents=None, direction=False, auto_allow=None):
        if direction:
            # проектные allow папки запуска с gh pr merge (metis-0137): окно не собирается, оба прежних файла окна
            # убирает allow_gate
            problems = project_allow_report(name, allow_gate(name, folders))
            if problems:
                print(f"песочница {name}: окно не собрано — {project_allow_text(name, problems)}", file=sys.stderr)
                if stop_live:
                    project_allow_stop(name, problems)
                return False
        real = [_real_dir(f, SANDBOX_ROOTS[:1], strict=True) or _real_dir(f, SANDBOX_ROOTS[1:]) for f in folders]
        skipped = [f for f, r in zip(folders, real) if not r]
        if skipped:
            print(f"песочница {name}: вне ~/projects и ~/ai/knowledge, ссылка или нет папки — только через Write/Edit: "
                  f"{skipped}", file=sys.stderr)
        own_real = os.path.realpath(own) if os.path.isdir(own) and not os.path.islink(own) else None
        write = [r for r in (_real_dir(p, ["~/.cache", "~/Library/Caches"], strict=True) for p in extra.get(name, [])) if r] + memory
        cache = _real_dir(f"{caches}/{name}", [caches], strict=True, create=True)
        ok = [r for r in real if r]
        # сетевой git: окну направления — всегда, мастерской — при SSH-remote (P0-4, metis-0064)
        data = role_settings(ok, own_real, write, cache, direction or any(ssh_remote(r) for r in ok), deny, compact,
                             guard, auto_allow)
        if direction:
            data["sandbox"]["excludedCommands"] += GH_PR_WRITE
        if name == "metis-pantheon":
            # навык new-direction (metis-0042): `pantheon direction init` создаёт ~/projects/<новое> — вне папок окна
            # Метиды, в песочнице упал бы. Мимо неё — только эта подкоманда и только у Метиды; ворота у команды свои:
            # галочка владельца в журнале доски owner-log, который пишет тик, — роли её не подделают.
            data["sandbox"]["excludedCommands"].append("pantheon direction init *")
        if name == "workshop":
            # Unix-сокеты офлайн-тестов (metis-0278, решение владельца «А» 19.10) — только в своём кэше окна: не
            # $TMPDIR (/tmp/claude-<uid> общий у всех сессий, там их сокеты); allowLocalBinding — нет, см. ниже
            data["sandbox"]["network"]["allowUnixSockets"] = [cache]
        if allow:
            data.setdefault("permissions", {}).setdefault("allow", []).extend(allow)
        if agents:
            agents_window(data, agents[0], agents[1], agents_py)
        store = (stores or {}).get(name)
        if store:
            st = os.path.realpath(os.path.expanduser(store))
            if any(st.startswith(r.rstrip("/") + "/") for r in ok):
                data["env"]["npm_config_store_dir"] = st
                pnpm_store_check(name, ok, st)
            else:
                alert_once(f"pnpm-store-{name}", store, f"directions.toml: pnpm_store {store} направления {name} — вне "
                           "его папок, окно его не получит", "pantheon")
        write_window(out_dir, name, data)
        return True

    merge_repos = policy.get("merge_repos") if isinstance(policy.get("merge_repos"), dict) else {}
    built = []
    for name, folders in domains.items():
        mine = leads.get(name, [])
        # chiron видит личное (me/) — только Зевсу (P0-2); главные роли и чужие лиды не нужны и лидам окна
        agents = (mine + COORDINATOR_AGENTS + COORDINATOR_EXTRA_AGENTS.get(name, []),
                  ["chiron"] + list(MAIN_ROLES) + [x for x in all_leads if x not in mine])
        if one(name, folders, os.path.join(PANTHEON, "directions", name), COORDINATOR_COMPACT,
               [] if name in private_dirs else private_paths, COORDINATOR_ALLOW, agents, direction=True,
               # окну с доступом к личному правило слияния не выдаётся — его PR сливает владелец (metis-0156)
               auto_allow=coordinator_auto_allow([] if name in private_dirs else merge_repos.get(name))):
            built.append(name)
    # мастерская пишет в папку запуска (~/projects/workshop/<задача>) и в workshop/ доски; список субагентов — вне P0-6
    one("workshop", ["~/projects/workshop"], os.path.join(PANTHEON, "workshop"), None, private_paths)
    # местные порты мастерской закрыты: на macOS allowLocalBinding открывает все порты 127.0.0.1, в том числе демон CDP
    # с входами владельца; браузеры владельца — только у роли Харон (решение владельца 15.10, отмена metis-0053)
    built.append("workshop")
    # окна задач расписания (P0-3, metis-0063): `claude -p --agent <роль>` тика (parse_command добавляет --settings).
    # Пишет только своё (JOB_ROLES), память ролей и свой кэш; личное закрыто на чтение и запись; сети Bash нет (веб у
    # prometheus и iris — инструменты WebFetch/WebSearch, не Bash); мимо песочницы — только `pantheon alert`. Строгий
    # guard — как у остальных окон. Кэш задачи в списке built — штаб его не читает (выдача из веба)
    try:
        known = sorted(f[:-3] for f in os.listdir(AGENTS) if f.endswith(".md") and ROLE_NAME.fullmatch(f[:-3]))
    except OSError:
        known = []
    for role, conf in JOB_ROLES.items():
        name = "job-" + role
        own = []
        for p in conf["write"]:
            if os.path.isdir(p) and not os.path.islink(p):
                own.append(os.path.realpath(p))
            else:
                print(f"песочница {name}: нет папки или ссылка — Bash туда не пишет: {p.replace(HOME, '~')}",
                      file=sys.stderr)
        cache = _real_dir(f"{caches}/{name}", [caches], strict=True, create=True)
        job = role_settings(own, None, memory, cache, False, private_paths, None, guard)
        job["sandbox"]["excludedCommands"] = list(JOB_EXCLUDED)
        job["sandbox"]["network"]["allowedDomains"] = []
        job["sandbox"]["filesystem"]["denyWrite"] += _deny_forms(private_paths)
        job["env"]["PANTHEON_ROLE"] = role  # хукам: роль окна, как у штаба
        # субагенты (P0-6): главная сессия задачи зовёт только своих (хук agents.py); deny — все известные типы,
        # кроме своих: встроенные, роли из ~/.claude/agents, лиды реестра и главные роли
        mine = list(conf.get("agents") or [])
        agents_window(job, mine or [JOB_NO_AGENTS],
                      [x for x in BUILTIN_AGENTS + known + all_leads + list(MAIN_ROLES) if x not in mine], agents_py)
        write_window(out_dir, name, job)
        built.append(name)
    # что закрыто штабу — [hq] policy.toml. Битый раздел — ошибка, а не «пусто»: окно Пританея не пересобираем, остаётся
    # прежнее (его файл не удаляется), и тревога — пока раздел не исправят
    try:
        hq_pol = ctx_mod().hq_policy(policy_path)
    except ValueError as e:
        alert_once("hq-policy-broken", str(e), f"policy.toml: {e} — окно Пританея не пересобрано, действует прежнее; "
                   "исправить раздел [hq] (Метида)", "pantheon")
        built.append("hq")
        for f in os.listdir(out_dir):
            if f.endswith(".json") and f[:-5] not in built:
                os.remove(os.path.join(out_dir, f))
        return built
    clear_once("hq-policy-broken")
    # штаб (SEC-26, вариант А): Зевс пишет только в ~/ai/pantheon, кроме .git и alerts.md; сеть закрыта (в веб он не
    # ходит, SEC-13); мимо песочницы — только `pantheon start|wake|alert`: запуск сессий и тревоги, и gh PR (HQ_GH).
    # Личное ему открыто (SEC-11), кроме ключей git-crypt.
    hq_cache = _real_dir(f"{caches}/hq", [caches], strict=True, create=True)
    root = os.path.realpath(PANTHEON)
    keys = [p for p in private_paths if "/.git/git-crypt" in p + "/"]  # ключи — не штабу: ~/ai/pantheon коммитит тик
    hq = role_settings([root], None, memory, hq_cache, False, keys, None, guard)
    hq["sandbox"]["excludedCommands"] = list(HQ_EXCLUDED) + HQ_GH
    hq["sandbox"]["filesystem"]["denyWrite"] += [os.path.join(root, ".git"), os.path.join(root, "alerts.md")]
    hq["sandbox"]["network"]["allowedDomains"] = []
    # корпус лекций — чужой контент (SEC-13, metis-0025): у Зевса уже есть личное и действия наружу, поэтому корпус ему
    # закрыт (решение владельца 15.10) — guard corpus-role (команда corpus), хук qmd-query (поиск), а здесь — чтение
    # файлов: Read (Claude Code применяет его и к Grep, Glob) и cat/grep в песочнице
    # и временные файлы других ролей (их TMPDIR и кэши — песочные папки окон, в том числе брошенные после
    # переименования роли): у Фемиды там выдача корпуса
    cache_dirs = set(built)
    with contextlib.suppress(OSError):
        cache_dirs |= {n for n in os.listdir(os.path.expanduser(caches)) if n != "hq"}
    closed = hq_pol["closed_dirs"] + [f"{caches}/{n}" for n in sorted(cache_dirs)]
    # переписка сессий (координаторы зовут corpus search — выдача оседает в *.jsonl), большие выводы (tool-results) и
    # выводы фоновых задач и TMPDIR (CLAUDE_TMP) всех сессий, кроме своих. Своё — папка штаба и его worktree (имя как
    # у Claude Code: всё, кроме букв и цифр, → «-»); открыты свои выводы, автопамять (memory/*.md) и задачи штаба.
    # Не перечислением папок (15.10 их было 4121 — мусор тестов, профиль Seatbelt вырос за 64 КБ и Bash штаба не
    # запускался), а постоянным числом записей:
    # - шаблоны по префиксам, которые расходятся со своим именем (_others_globs): их число не растёт с числом папок.
    #   Одни и те же записи — правилом Read (инструменты Read, Grep, Glob) и в denyRead песочницы (Claude Code и так
    #   вливает правила Read в песочницу);
    # - закрыто содержимое чужих папок CLAUDE_TMP («<префикс>*/*» и «<префикс>*/*/**»), а не сами имена: CLAUDE_TMP —
    #   и общий $TMPDIR песочницы, в его корне лежат временные файлы Bash (heredoc zsh — $TMPPREFIX, mktemp, tempfile).
    #   Шаблон «<префикс>*» закрыл бы и их, а Claude Code срезает хвост «/**» и запрет-шаблон закрывает всё поддерево.
    #   Имена на «tmp» не закрываются: это временные папки самого штаба (mktemp -d — tmp.XXXX, tempfile — tmpXXXX),
    #   новая закрылась бы с момента создания. Цена — чужие tmp*-папки открыты (в 0.11.16 так же до пересборки);
    #   Корень открыт, как было до 0.11.17; allowRead не нужен (разрешение-шаблон в Seatbelt — точное имя, без поддерева)
    dash = lambda p: re.sub(r"[^A-Za-z0-9]", "-", p)  # noqa: E731
    own, home_d = dash(os.path.realpath(PANTHEON)), dash(os.path.realpath(HOME))
    tasks, projects = CLAUDE_TMP, os.path.join(HOME, ".claude", "projects")
    files = ["~/.claude/projects/**/*.jsonl", f"~/.claude/projects/{home_d}-projects-*/**/tool-results/**",
             f"{tasks}/{home_d}-projects-*/*", f"{tasks}/{home_d}-projects-*/*/**"]
    for base, short, tails, keep in ((projects, "~/.claude/projects", ("/**/tool-results/**",), ()),
                                     (tasks, tasks, ("/*", "/*/**"), ("tmp",))):
        try:
            names = os.listdir(base)
        except OSError:
            names = []
        globs, skipped = _others_globs(names, own, keep)
        files += [f"{short}/{g}{tail}" for g in globs for tail in tails]
        if skipped:
            print(f"песочница hq: имена с символами шаблона в {short} не закрыты: {skipped[:5]}",
                  file=sys.stderr)
    fsys = hq["sandbox"]["filesystem"]
    fsys["denyRead"] += _deny_forms(closed) + _deny_forms(files)
    rule = lambda x: f"Read({x})" if x.startswith("~") else f"Read(/{x})"  # noqa: E731 — «//» — абсолютный путь
    hq.setdefault("permissions", {}).setdefault("deny", []).extend(
        [rule(x + "/**") for x in _deny_forms(closed)] + [rule(x) for x in _deny_forms(files)])
    # P0-6: код — поручение направлению, а не лид в окне штаба
    agents_window(hq, HQ_AGENTS, all_leads + list(MAIN_ROLES), agents_py)
    hq["env"]["PANTHEON_ROLE"] = "hq"  # хукам: в событиях фоновой сессии agent_type нет (15.10)
    write_window(out_dir, "hq", hq)
    built.append("hq")
    for f in os.listdir(out_dir):
        if f.endswith(".json") and f[:-5] not in built:
            os.remove(os.path.join(out_dir, f))
    return built


# --- запуск сессий (SEC-26, COMM-10, ROLE-01, ROLE-02) -----------------------------------
# Сессии Пантеона запускает только `pantheon start`: флаги — здесь, в коде, а не в файлах, которые пишет Зевс; настройки
# окна — из ~/.local/state/pantheon/settings/ (собирает `pantheon domains build`, Зевсу и ролям туда не записать). Флагов
# обхода разрешений нет и не будет. Поручение идёт позиционным аргументом и начинается с пометки «[Пантеон: …]»: хук
# журнала ваших слов (ctx.py owner-log) такую строку не пишет, а ваш первый ответ сессии — пишет. Та же пометка — у
# сообщения `pantheon wake`. Сессии с пометкой «остановлено вами» (~/.local/state/pantheon/stopped/<имя>, ставит
# `pantheon stop`, шаг 1.4) не будит никто.
# команды пульта штаба, которые пишут вне ~/ai/pantheon (alerts.md, ~/.local/state/pantheon) или запускают сессии со
# своей песочницей; guard проверяет их и здесь (pantheon-acl)
HQ_EXCLUDED = ["pantheon alert *", "pantheon start *", "pantheon wake", "pantheon wake *", "pantheon archive",
               "pantheon jobs *", "pantheon domains build", "pantheon roles build", "pantheon stop *",
               "pantheon resume *", "pantheon pause *", "pantheon restart *", "pantheon saved *", "pantheon who",
               "pantheon agents"]
START_MARK = "[Пантеон:"
WAKE_TEXT = (START_MARK + " пробуждение] Тебя прервало выключение или перезапуск. Сверь файл состояния и «начато» без "
             "«сделано» (не повторяй внешнее действие, пока не проверишь, что оно не ушло), затем продолжай задачу.")
COORDINATOR_GOAL = ("Цель достигнута, когда последний отчёт сессии — по формату отчёта роли, и либо «Статус: готово» и все "
                    "пункты чек-листа эпика в STATUS.md отмечены сделанными, либо «Статус: заблокировано» с названным "
                    "блокером и вопросом владельцу или Зевсу.")
# поручение названо явно (одна задача, проверка) — цель по нему, а не по эпику: иначе Stop-хук не отпустит сессию, пока
# не закрыт весь чек-лист, и короткая проверка разрастается в эпик (живой запуск athena-0001 15.10)
TASK_GOAL = ("Цель достигнута, когда последний отчёт сессии — по формату отчёта роли, и либо «Статус: готово» и выполнен "
             "критерий «готово» этого поручения, либо «Статус: заблокировано» с названным блокером и вопросом владельцу "
             "или Зевсу. Другие задачи и пункты эпика в эту цель не входят.")
SESSION_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
WORKSHOP = os.path.join(HOME, "projects", "workshop")
OPEN_STATUSES = {"todo", "doing", "review"}  # «ждёт» не будят: ответа ещё нет


def claude_bin():
    import shutil
    return shutil.which("claude") or os.path.join(HOME, ".local", "bin", "claude")


def agents_all():
    r = subprocess.run([claude_bin(), "agents", "--json", "--all"], capture_output=True, text=True, timeout=60)
    try:
        data = json.loads(r.stdout or "[]")
    except ValueError:
        return None
    data = data if isinstance(data, list) else data.get("agents") if isinstance(data, dict) else None
    return reconcile_agents(data) if isinstance(data, list) else data


def daemon_workers():
    """Процессы фоновых сессий из реестра демона Claude Code ~/.claude/daemon/roster.json: короткий id → pid. Читаем
    только pid (в записи есть и жетоны — их не берём). None — реестра нет или он не читается: тогда о процессах
    ничего не утверждаем."""
    d = read_json(os.path.join(HOME, ".claude", "daemon", "roster.json"), None)
    if not isinstance(d, dict) or not isinstance(d.get("workers"), dict):
        return None
    return {str(k): w.get("pid") for k, w in d["workers"].items() if isinstance(w, dict)}


def claude_job_state(short):
    """state.json задания ~/.claude/jobs/<короткий id>/state.json (его пишет Claude Code, мы только читаем)."""
    if not re.fullmatch(r"[0-9a-zA-Z-]{4,64}", str(short or "")):
        return {}
    d = read_json(os.path.join(HOME, ".claude", "jobs", str(short), "state.json"), {})
    return d if isinstance(d, dict) else {}


def reconcile_agents(data, workers=None):
    """Сверка `claude agents --json --all` с заданием (jobs/<id>/state.json) и процессом (реестр демона), metis-0250.
    (1) Из окна с песочницей `claude agents` не видит живой процесс (kill(pid, 0) там — EPERM) и пишет живую сессию
    «failed» без pid (19.10: zeus и metis-pantheon «упали», а state.json — working). Процесс из реестра демона жив,
    задание working/blocked — берём состояние задания, pid — из реестра; прежнее состояние — в listedState.
    (2) Обратный случай: «blocked» без процесса и без вопроса (needs в state.json) — сессию снял Claude Code, ждать
    ей нечего (18.10, координатор без процесса весь день «ждёт вас»): noProcess. С вопросом — по-прежнему ждёт вас:
    ответ дойдёт через claude attach, он поднимет процесс.
    (3) Причина для сводки: нет waitingFor — needs задания (blocked) или detail (failed)."""
    workers = daemon_workers() if workers is None else workers
    for a in data:
        if not isinstance(a, dict) or a.get("kind") not in (None, "background") or not a.get("id"):
            continue
        js = claude_job_state(a["id"])
        wpid = (workers or {}).get(str(a["id"]))
        alive = bool(wpid) and pid_alive(wpid)
        if alive and not a.get("pid"):
            a["pid"] = wpid
        if a.get("state") == "failed" and alive and js.get("state") in ("working", "blocked"):
            a["listedState"], a["state"] = "failed", js["state"]
        if (a.get("state") == "blocked" and workers is not None and not alive and not a.get("pid")
                and js and not js.get("needs")):
            a["noProcess"] = True
        if not a.get("waitingFor"):
            why = js.get("needs") if a.get("state") == "blocked" else js.get("detail") if a.get("state") == "failed" else None
            if why:
                a["waitingFor"] = " ".join(str(why).split())[:200]
    return data


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError) as e:
        return isinstance(e, PermissionError)
    return True


def sessions_registry():
    """Реестр имён Claude Code ~/.claude/sessions/<pid>.json: в нём и интерактивные вкладки, которых нет в
    `claude agents --json` (15.10 имя zeus держал забытый процесс вкладки). Только записи с живым процессом; ключи
    жетонов не читаются."""
    out, d = [], os.path.join(HOME, ".claude", "sessions")
    with contextlib.suppress(OSError):
        for f in os.listdir(d):
            if not re.fullmatch(r"\d+\.json", f):
                continue
            rec = read_json(os.path.join(d, f), {})
            if not isinstance(rec, dict) or not pid_alive(rec.get("pid")):
                continue
            out.append({"name": rec.get("name"), "sessionId": rec.get("sessionId"), "pid": rec.get("pid"),
                        "kind": "interactive" if rec.get("kind") == "interactive" else "background",
                        "cwd": rec.get("cwd"), "registry": True})
    return out


def name_alias(name):
    """Имя и копии, которым Claude Code дал другое имя, потому что это было занято: «имя (2)», «имя-два-слова»."""
    return re.compile(re.escape(name) + r"(?: \(\d+\)|-[a-z]+-[a-z]+)?")


def live_copies(name, agents, registry=None):
    """Живые сессии с этим именем и его копии: работает (working), ждёт (blocked), открыта во вкладке (нет state) —
    плюс интерактивные вкладки из реестра ~/.claude/sessions, которых нет в claude agents. Сюда не входят остановленная
    (stopped — так claude agents пишет после claude stop, 15.10, metis-0041), упавшая (failed) и закончившая ход (done:
    с живым процессом её новый запуск останавливает сам, CTX-10). Имя держит не запись в claude agents, а живой процесс
    в реестре: пока остановленная копия не вышла, имя ещё занято — это ждёт wait_name_free."""
    alias = name_alias(name)
    out = [a for a in agents or [] if alias.fullmatch(str(a.get("name") or ""))
           and a.get("state") not in ("done", "stopped", "failed")]
    known = {a.get("sessionId") for a in agents or []}
    for r in sessions_registry() if registry is None else registry:
        if r.get("kind") == "interactive" and r.get("sessionId") not in known and alias.fullmatch(str(r.get("name") or "")):
            out.append({k: v for k, v in r.items() if k != "registry"})
    return out


def maintenance_active():
    """Метка технического перезапуска (SCHED-15), если она стоит и не истекла: пока она есть, дежурный и
    pantheon wake никого не будят."""
    m = read_json(path("maintenance.json"), None)
    if not isinstance(m, dict) or not m:
        return None
    if now() > float(m.get("expires") or 0):
        return None
    return m


def load_pause(name):
    """Пауза по нагрузке (COST-04) этого направления или общая (_all): запись или None."""
    for n in (name, "_all"):
        p = read_json(path("pauses", n + ".json"), None)
        if isinstance(p, dict) and p:
            return p
    return None


def run_settings(name, role, window, origin):
    """Окно этого запуска: настройки окна + PANTHEON_ORIGIN (кто запустил), имя и роль — переменные сессии и её
    хуков. → путь файла или None (окна нет: pantheon domains build)."""
    win = path("settings", window + ".json")
    if not os.path.isfile(win):
        return None
    data = read_json(win, {})
    data.setdefault("env", {})["PANTHEON_ORIGIN"] = origin
    data["env"]["PANTHEON_SESSION"] = name
    data["env"]["PANTHEON_ROLE"] = role
    run = path("settings", "run", name + ".json")
    write_json(run, data)
    return run


COPY_NOTE = re.compile(r"started a copy as ([0-9a-f]{8})")
PUSH_MAX_AGE = 30 * 60


def push_text(session_id, text):
    """Текст, который хук ctx.py push отдаст сессии при следующем старте её процесса (SessionStart + asyncRewake):
    `claude respawn` сам хода не начинает, а команды «сказать фоновой сессии» у Claude Code нет (проверено 15.10)."""
    if not re.fullmatch(r"[0-9a-f-]{8,64}", str(session_id or "")) or not str(text).startswith(START_MARK):
        return None
    os.makedirs(path("push"), mode=0o700, exist_ok=True)
    p = path("push", session_id + ".txt")
    fd = os.open(p + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(str(text)[:4000])
    os.replace(p + ".tmp", p)
    return p


def resume_session(name, a, text, origin, recheck=None):
    """Продолжить сессию направления или мастерской той же сессией (контекст эпика сохраняется). Есть в claude agents
    (остановлена, упала, закончила ход) — `claude respawn <id>`: тот же id, имя и флаги запуска, в том числе окно
    --settings, новые плагины и Claude Code; текст ей отдаёт хук push при старте процесса. Нет её там (удалена из
    списка) — `claude --resume <сессия> --bg --name <имя> --settings <окно>`: без --name имя теряется, без --settings —
    окно с песочницей. `--resume` на сессии, которую Claude Code ещё считает живой, делает копию («started a copy as
    <id>», 15.10 так было и после claude stop) — это строка в тревогах. → (код, id копии или None)."""
    # та же блокировка имени, что у pantheon start и pantheon stop: Зевс, тик и вы не поднимут две копии и не
    # разбудят сессию, которую в эту минуту останавливают; под ней — повторная проверка «можно ли будить» (ревью argus)
    with lock("start-" + name, block=False) as got_lock:
        if not got_lock:
            start_log(f"resume-busy\t{name}\t{a.get('id')}\t{origin}")
            return skipped("другой процесс уже поднимает"), None
        why = recheck() if recheck else None
        if why:
            start_log(f"resume-skip\t{name}\t{a.get('id')}\t{origin}\t{why}")
            return skipped(why), None
        # metis-0207: правило свежего старта (metis-0147 п. 2) действует на любом пути возобновления, а не только в
        # resume_or_start и pantheon wake: ждущая сессия, после недельного лимита, техперезапуск, снятие паузы
        fresh = fresh_reason(a)
        if fresh:
            return _fresh_start(name, a, fresh_text("свежий старт", name, a.get("id"), text), origin, fresh), None
        return _resume_session(name, a, text, origin)


# Код отказа «нет окна»: сессию направления или мастерской без файла окна не поднимаем ни respawn, ни --resume, ни
# свежим стартом — без --settings она ушла бы без песочницы окна (ревью argus PR #32). Тревога — одна на причину
# (alert_once), поэтому wake и дежурный не повторяют свою тревогу о коде каждые 5 минут
NO_WINDOW = 3
# Код «пропуск» (metis-0291): под блокировкой имени выяснилось, что будить не нужно или нельзя по обычной причине (уже
# работает, остановлено вами, пауза, технический перезапуск, имя занято другим подъёмом). Не сбой: wake печатает
# «пропуск: <имя> — <причина>», выходит с 0, без тревоги. Причина — в SKIP_WHY (последний пропуск процесса)
SKIPPED = 4
SKIP_WHY = ""


def skipped(why):
    global SKIP_WHY
    SKIP_WHY = str(why)
    return SKIPPED


def window_missing(name, origin, why, how):
    """Отказ поднять name без окна: строка start.log «<how>-skip», тревога один раз на причину. → NO_WINDOW."""
    start_log(f"{how}-skip\t{name}\t{origin}\tнет окна: {why}")
    alert_once("no-window-" + name, why, f"{name}: не поднимаю ({origin}) — {why}. Без файла окна сессия ушла бы без "
               "песочницы окна; поднимет следующий запуск после сборки окна", "pantheon")
    return NO_WINDOW


def no_window_reason(window):
    """Почему нет окна window: allow проекта в папке запуска (metis-0137) или окно не собрано."""
    folders = (read_json(path("domains.json"), {}).get("domains") or {}).get(window)
    problems = project_allow_problems(launch_folder(folders)) if folders else []
    if problems:
        return "окно не собрано: " + project_allow_text(window, problems)
    return f"нет окна {tilde(path('settings', window + '.json'))} — pantheon domains build"


def cwd_allow_problems(name, a, role, launch, origin):
    """respawn и --resume поднимают сессию в её прежней папке (cwd из claude agents), а окно проверено по папке
    запуска. Папка координатора другая и её allow пускает gh pr merge — не поднимаем: строка resume-skip, тревога одна
    на причину. Окно не снимается: pantheon start и свежий старт идут из папки запуска. → NO_WINDOW или 0."""
    cwd = os.path.realpath(a["cwd"]) if role == "domain-coordinator" and isinstance(a.get("cwd"), str) and a["cwd"] else ""
    problems = project_allow_problems(cwd) if cwd and cwd != launch else []
    key = "project-allow-cwd-" + name
    if not problems:
        clear_once(key)
        return 0
    text = project_allow_text(name, problems)
    start_log(f"resume-skip\t{name}\t{origin}\tпапка сессии {tilde(cwd)}: allow пускает gh pr merge")
    alert_once(key, json.dumps(problems), f"{name}: не поднимаю ({origin}) — сессия работала в {tilde(cwd)}, не в папке "
               f"запуска: {text}. Свежий старт (pantheon start {name}) пойдёт из папки запуска", "pantheon")
    return NO_WINDOW


def _resume_session(name, a, text, origin):
    target, rest = (("workshop", [name[len("daedalus-"):]]) if name.startswith("daedalus-") else (name, []))
    got = start_target(target, rest)
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        print(f"[resume] {name} {a.get('id')} {origin}")
        return 0, None
    if not isinstance(got, str):
        allow_gate(name)  # allow со старым mtime сборка не заметила — окно снимается здесь (ревью argus PR #32)
        bad = cwd_allow_problems(name, a, got[1], got[2], origin)
        if bad:
            return bad, None
    run = run_settings(name, got[1], got[3], origin) if not isinstance(got, str) else None
    if not run:  # ни respawn (прежние флаги с прежним файлом запуска), ни --resume без --settings
        return window_missing(name, origin, got if isinstance(got, str) else no_window_reason(got[3]), "resume"), None
    clear_once("no-window-" + name)
    sid = a.get("sessionId")
    if not str(text).startswith(START_MARK):
        text = f"{START_MARK} поручение от {origin}] {text}"
    pushed = push_text(sid, text) if a.get("id") else None
    if pushed:  # без текста respawn поднял бы сессию молча — тогда сразу запасной путь, он текст передаёт
        r = subprocess.run([claude_bin(), "respawn", a["id"]], capture_output=True, text=True, timeout=180)
        start_log(f"respawn\t{name}\t{a['id']}\t{origin}\t{r.returncode}")
        if r.returncode == 0:
            rm_previous(name, "respawn", keep={a["id"]}, wait=True)
            return 0, None
        with contextlib.suppress(OSError):
            os.remove(pushed)
    # --resume не наследует роль (metis-0208): без --agent сессия поднялась бы голым Claude. Роль — та же, что у start и
    # свежего старта; штаб (zeus) — hq, хотя сюда он сегодня не доходит (start_target не знает zeus — отказ выше)
    role = "hq" if name == "zeus" else got[1]
    argv = [claude_bin(), "--resume", sid or a.get("id"), "--bg", "--agent", role, "--name", name, "--settings", run, text]
    before = {x.get("id") for x in agents_all() or [] if x.get("id")}
    r = subprocess.run(argv, cwd=a.get("cwd") or HOME, capture_output=True, text=True, timeout=180)
    m = COPY_NOTE.search((r.stdout or "") + (r.stderr or ""))
    start_log(f"resume\t{name}\t{a.get('id')}\t{origin}\t{r.returncode}" + (f"\tcopy {m.group(1)}" if m else ""))
    if m:
        alert(f"{name}: --resume сделал копию {m.group(1)} — исходная сессия {a.get('id')} ещё числится живой; проверить "
              f"claude agents, лишнюю остановить", "pantheon")
    elif r.returncode == 0:  # копию (исходная ещё живая) не разбираем сами — тревога выше, решает Зевс
        rm_previous(name, "--resume", before=before, keep={a.get("id")}, wait=True)
    return r.returncode, (m.group(1) if m else None)


# --- свежий старт вместо продолжения (metis-0147 п. 2, metis-0136) ---------------------------------
# `claude respawn` перезапускает процесс той же сессии с тем же разговором, `--resume` — тоже: контекст не уходит.
# Очистить окно можно только новой сессией: старую остановить (разговор сохраняется — claude attach <id>), имя
# дождаться свободным и поднять `claude --bg --agent <роль> --name <имя> --settings <окно роли>` с текстом
# «[Пантеон: …] прочитай <файл состояния>, продолжай».

_CTX = None


def ctx_mod():
    """hooks/ctx.py — замер контекста тот же, что у Stop-хука «пора очистить» (context_tokens, порог AT), и его метки."""
    global _CTX
    if _CTX is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_ctx", os.path.join(PLUGIN, "hooks", "ctx.py"))
        _CTX = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_CTX)
    return _CTX


def transcript_path(a):
    """Транскрипт сессии из claude agents: ~/.claude/projects/<папка, где не буквы и цифры — «-»>/<sessionId>.jsonl;
    не нашёлся там (папку переименовали) — тот же файл в любой папке проектов. → путь или None."""
    sid = str(a.get("sessionId") or "")
    if not re.fullmatch(r"[0-9a-f-]{8,64}", sid):
        return None
    root = os.path.join(HOME, ".claude", "projects")
    if a.get("cwd"):
        p = os.path.join(root, re.sub(r"[^A-Za-z0-9]", "-", str(a["cwd"])), sid + ".jsonl")
        if os.path.isfile(p):
            return p
    with contextlib.suppress(OSError):
        for d in sorted(os.listdir(root)):
            p = os.path.join(root, d, sid + ".jsonl")
            if os.path.isfile(p):
                return p
    return None


def session_context(a):
    """(контекст в токенах по последнему ответу, время последней записи транскрипта) или (None, None)."""
    p = transcript_path(a)
    if not p:
        return None, None
    with contextlib.suppress(OSError):
        return ctx_mod().context_tokens(p), os.path.getmtime(p)
    return None, None


def fresh_reason(a, t=None):
    """Поднимать ли сессию свежей, а не продолжением: контекст > FRESH_CTX и простой > FRESH_IDLE_MIN. → текст или None."""
    n, last = session_context(a)
    if not n or last is None:
        return None
    idle = (now() if t is None else t) - last
    if n > FRESH_CTX and idle > FRESH_IDLE_MIN * 60:
        return f"контекст {n // 1000} тыс., простой {int(idle // 60)} мин"
    return None


def latest_zeus_handoff():
    """Последний по времени ~/ai/pantheon/handoff/zeus-*/HANDOFF.md или None."""
    best = None
    with contextlib.suppress(OSError):
        for d in os.listdir(os.path.join(PANTHEON, "handoff")):
            p = os.path.join(PANTHEON, "handoff", d, "HANDOFF.md")
            if d.startswith("zeus-") and os.path.isfile(p) and (best is None or os.path.getmtime(p) > os.path.getmtime(best)):
                best = p
    return best


def state_files(name):
    """Файлы состояния, с которых свежая сессия продолжает: направление — STATUS.md, мастерская — файл задачи,
    Зевс — доска и последний handoff/zeus-*/HANDOFF.md."""
    if name == "zeus":
        return [os.path.join(PANTHEON, "board.md")] + [p for p in [latest_zeus_handoff()] if p]
    if name.startswith("daedalus-"):
        return [os.path.join(PANTHEON, "workshop", name[len("daedalus-"):] + ".md")]
    return [os.path.join(PANTHEON, "directions", name, "STATUS.md")]


def tilde(p):
    for h in (HOME, os.path.realpath(HOME)):  # PANTHEON — настоящим путём, HOME — как в окружении
        if p == h or p.startswith(h + "/"):
            return "~" + p[len(h):]
    return p


def fresh_text(kind, name, old_id, tail=""):
    """«[Пантеон: <kind>] … прочитай <файл состояния>, продолжай» — текст свежей сессии; tail — поручение вызывающего,
    дословно со своей пометкой: задание «[Пантеон: задание от …]» должен остаться подписанным (ревью argus)."""
    files = " и ".join(tilde(p) for p in state_files(name))
    tail = str(tail or "").strip()
    return (f"{START_MARK} {kind}] Ты — новая сессия {name} с чистым контекстом: прошлая ({old_id or '?'}) остановлена, "
            f"её разговор сохранён (claude attach {old_id or '<id>'}). Прочитай {files}, продолжай со следующего шага. "
            "Сверь «начато» без «сделано»: внешнее действие не повторяй, пока не проверишь, что оно не ушло. "
            + (tail + " " if tail else "") + "Это не слова владельца и не согласие.")


def fresh_target(name, origin):
    """→ (роль, папка запуска, окно --settings) или текст ошибки, в том числе «нет окна»."""
    if name == "zeus":
        win = path("settings", "hq.json")  # то же окно, что у pantheon start zeus
        return ("hq", PANTHEON, win) if os.path.isfile(win) else "нет окна Пританея — pantheon domains build"
    target, rest = (("workshop", [name[len("daedalus-"):]]) if name.startswith("daedalus-") else (name, []))
    got = start_target(target, rest)
    if isinstance(got, str):
        return got
    _, role, folder, window, _ = got
    allow_gate(name)  # allow со старым mtime сборка не заметила — окно снимается здесь (ревью argus PR #32)
    run = run_settings(name, role, window, origin)
    return (role, folder, run) if run else no_window_reason(window)


def fresh_start(name, a, text, origin, recheck=None, reason=None):
    """Поднять имя свежей сессией (новый контекст, то же имя, окно роли) с текстом text. a — прежняя сессия из claude
    agents (её id — в журнале и тексте); reason — почему свежей, в строку fresh-start журнала start.log. Та же
    блокировка имени и повторная проверка, что у resume_session. → код."""
    with lock("start-" + name, block=False) as got_lock:
        if not got_lock:
            start_log(f"fresh-busy\t{name}\t{a.get('id')}\t{origin}")
            return skipped("другой процесс уже поднимает")
        why = recheck() if recheck else None
        if why:
            start_log(f"fresh-skip\t{name}\t{a.get('id')}\t{origin}\t{why}")
            return skipped(why)
        return _fresh_start(name, a, text, origin, reason)


def _fresh_start(name, a, text, origin, reason=None):
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        print(f"[fresh] {name} {a.get('id')} {origin}")
        return 0
    got = fresh_target(name, origin)
    if isinstance(got, str):  # старую копию не останавливаем: новую без окна всё равно не поднять
        return window_missing(name, origin, got, "fresh")
    clear_once("no-window-" + name)
    role, folder, win = got
    if not str(text).startswith(START_MARK):
        text = f"{START_MARK} поручение от {origin}] {text}"
    if role == "domain-coordinator":
        text = "/goal " + text + " " + COORDINATOR_GOAL  # как у pantheon start: Stop-хук с целью эпика (DONE-02)
    agents = agents_all() or []
    live = live_copies(name, agents)
    if any(not x.get("id") for x in live):
        why = copies_message(name, live)
        start_log(f"fresh-tab\t{name}\t{origin}")
        alert(f"{name}: свежий старт не сделан — {why}", "pantheon")
        return 1
    stopped = list(live)
    stop_copies(name, live, "stop-fresh")
    for x in agents:  # закончившая ход с живым процессом держит имя (CTX-10)
        if x.get("name") == name and x.get("state") == "done" and x.get("pid") and x.get("id") \
                and x["id"] not in {s.get("id") for s in stopped}:
            stop_copies(name, [x], "stop-fresh-done")
            stopped.append(x)
    why = wait_name_free(name, stopped) if stopped else None
    if why:
        start_log(f"fresh-skip\t{name}\t{a.get('id')}\t{origin}\tимя не освободилось после claude stop")
        alert(f"{name}: свежий старт не сделан — {why}", "pantheon")
        return 1
    before = {x.get("id") for x in agents_all() or [] if x.get("id")}
    argv = [claude_bin(), "--bg", "--agent", role, "--name", name, "--settings", win, text]
    r = subprocess.run(argv, cwd=folder, capture_output=True, text=True, timeout=180)
    start_log(f"fresh-start\t{name}\t{a.get('id')}\t{origin}\t{r.returncode}" + (f"\t{reason}" if reason else ""))
    if r.returncode != 0:
        return r.returncode
    wrong = check_new_name(name, before)
    if wrong:
        alert(wrong, "pantheon")
        return 1
    rm_previous(name, "свежий старт", before=before)
    return 0


def copies_message(name, live):
    tab = [a for a in live if not a.get("id")]
    if tab:
        return (f"{name} открыта во вкладке терминала (pid {tab[0].get('pid')}) — перейдите в неё или закройте её и "
                "запустите снова")
    ids = ", ".join(f"{a.get('name')} {a['id']} ({a.get('state')})" for a in live)
    return (f"{name} уже работает: {ids}. Поручение — сообщением ей (SendMessage, адрес {name}) или claude attach "
            f"{live[0]['id']}; начать заново — тот же запуск с --restart")


def stop_and_rm(name, sid):
    """claude stop, затем claude rm <id> (metis-0239): остановленную сессию Claude Code сам перезапускает
    (daemon.log: settled (killed) → claimed-spare (fleet)), пока она в его списке. rm убирает из списка фоновую сессию
    (и её worktree, если он чистый); переписка остаётся, вернуть — pantheon start / resume. Без --discard-unpushed и
    --force-remove-worktree: сессию с неотправленной работой не удаляем насильно. Возвращает None или причину отказа."""
    try:
        st = subprocess.run([claude_bin(), "stop", sid], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return f"claude stop не выполнился: {e}"[:200]
    if st.returncode != 0:  # не остановилась — rm не зовём (rm сносит сессию, а она ещё может работать)
        return ("claude stop: " + (" ".join(((st.stderr or "") + " " + (st.stdout or "")).split())
                                   or f"код {st.returncode}"))[:200]
    return rm_session(sid)


def rm_session(sid, tries=2):
    """claude rm <id> без --discard-unpushed и --force-remove-worktree (metis-0239; уборка дежурного metis-0250):
    сессию с неотправленной работой в worktree Claude Code не удаляет, и мы не настаиваем. → None или причина отказа."""
    r = None
    for attempt in range(tries):  # stop возвращается раньше, чем процесс ушёл: rm на ещё живую сессию может отказать
        try:
            r = subprocess.run([claude_bin(), "rm", sid], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            return f"claude rm не выполнился: {e}"[:200]
        if r.returncode == 0:
            return None
        if attempt + 1 < tries:
            time.sleep(1)
    return " ".join(((r.stderr or "") + " " + (r.stdout or "")).split())[:200] or f"код {r.returncode}"


def refused_by(reason):
    """Кто отказал в stop_and_rm — для тревоги: «stop отказал» (сессия не остановилась, rm не звали) или «rm отказал»
    (ревью argus к #53: при коде stop ≠ 0 тревога писала «rm отказал»)."""
    return "stop отказал" if str(reason or "").startswith("claude stop") else "rm отказал"


def rm_previous(name, how, before=None, keep=(), loud=False, wait=False):
    """После успешного старта под именем name (pantheon start, свежий старт, продолжение wake/техперезапуска/дежурного):
    прежние фоновые сессии этого имени — `claude rm` (процесса нет) или claude stop + rm (процесс есть), чтобы в
    claude agents у имени осталась одна строка (metis-0250, слово владельца 19.10 через Зевса). Новая не трогается:
    новая — id, которого не было в before (снимок id до запуска; None — все нынешние старые), и id из keep (продолженная respawn/--resume сессия), если
    она живая. Пока живой новой с этим именем нет, ничего не удаляем (старт не подтвердился — прежние добьёт уборка
    дежурного); wait — подождать её появления PANTHEON_NAME_WAIT (10 с). Отказ rm (неотправленное в worktree) —
    start.log, тревога и, при loud, строка в stderr. → список (id, причина) отказов."""
    keep = set(keep)
    limit = 0.0
    if wait:
        limit = 10.0
        with contextlib.suppress(ValueError, TypeError):
            limit = max(0.0, float(os.environ.get("PANTHEON_NAME_WAIT") or limit))
    _, poll, _ = stop_wait_knobs()
    started = time.monotonic()
    while True:
        agents = agents_all()
        if agents is None:
            return []
        same = [a for a in agents if a.get("name") == name and a.get("id") and a.get("kind") in (None, "background")]
        old = {a["id"] for a in same} if before is None else before  # без снимка — нового нет, только keep
        kept = {a["id"] for a in same if a["id"] not in old
                or (a["id"] in keep and a.get("state") not in DOWN_STATES)}
        if not any(a["id"] not in kept for a in same):
            return []  # убирать нечего — и ждать нечего
        if any(a.get("state") not in DOWN_STATES for a in same if a["id"] in kept):
            break
        if time.monotonic() - started >= limit:
            start_log(f"rm-previous-skip\t{name}\t{how}\tновая сессия не видна живой")
            return []
        time.sleep(poll)
    left = []
    for a in same:
        if a["id"] in kept:
            continue
        has_process = a.get("state") in ("working", "blocked") or (a.get("pid") and a.get("state") not in ("stopped", "failed"))
        reason = stop_and_rm(name, a["id"]) if has_process else rm_session(a["id"])
        start_log(f"rm-previous\t{name}\t{a['id']}\t{a.get('state')}\t{how}")
        if reason:
            start_log(f"rm-refused\t{name}\t{a['id']}\t{reason}")
            alert(f"{name}: прежняя сессия {a['id']} осталась среди фоновых сессий Claude Code ({how}, "
                  f"{refused_by(reason)}): {reason}", "pantheon-stop")
            if loud:
                print(f"pantheon start: {name}: прежняя сессия {a['id']} осталась среди фоновых сессий Claude Code, "
                      f"причина: {reason}", file=sys.stderr)
            left.append((a["id"], reason))
    return left


def stop_copies(name, live, why="stop-restart"):
    # без rm (metis-0239): здесь сессию поднимают снова или оставляют для claude attach — rm её бы удалил
    for a in live:
        subprocess.run([claude_bin(), "stop", a["id"]], capture_output=True, text=True, timeout=60)
        start_log(f"{why}\t{name}\t{a.get('name')}\t{a['id']}")


DOWN_STATES = ("done", "stopped", "failed")


def stop_wait_knobs():
    """После claude stop: сколько ждать освобождения имени (с), как часто спрашивать claude agents и сколько имя
    должно простоять свободным (15.10 остановленная Фемида ожила через 7 с). Подменяются в тестах."""
    def num(var, default):
        with contextlib.suppress(ValueError, TypeError):
            v = float(os.environ.get(var) or default)
            if v >= 0:
                return v
        return default
    return num("PANTHEON_STOP_WAIT", 30.0), num("PANTHEON_STOP_POLL", 1.5), num("PANTHEON_STOP_SETTLE", 10.0)


def name_holders(name, agents, registry):
    """Кто держит имя: живые копии (live_copies) и любой живой процесс реестра ~/.claude/sessions с этим именем или
    его копией — фоновый тоже. Реестр — источник правды об именах Claude Code (15.10): после claude stop claude
    agents уже пишет stopped, а процесс ещё выходит и имя держит; новый запуск в эту секунду получит «имя-два-слова»."""
    out = live_copies(name, agents, registry)
    seen = {a.get("sessionId") for a in out if a.get("sessionId")}
    alias = name_alias(name)
    for r in registry:
        if r.get("sessionId") not in seen and alias.fullmatch(str(r.get("name") or "")):
            out.append({k: v for k, v in r.items() if k != "registry"})
    return out


def _holder_text(a):
    who = a.get("id") or f"pid {a.get('pid')}"
    return f"{a.get('name')} {who} ({a.get('state') or a.get('kind') or 'процесс'})"


def wait_name_free(name, stopped):
    """После claude stop: ждать, пока остановленные копии отпустят имя — в claude agents нет живых копий и в реестре
    нет живого процесса с этим именем (name_holders), и так держится settle секунд. Ожившая копия (была
    stopped/done/failed или пропала из списка, а снова working/blocked — 15.10 так оживала Фемида) — повторный claude
    stop один раз, ожила снова — отказ. Новая живая копия, которую мы не останавливали (вкладка, чужой запуск), —
    отказ с copies_message. → None (имя свободно) или текст отказа; запуск при отказе не делается."""
    wait, poll, settle = stop_wait_knobs()
    ids = {a["id"] for a in stopped if a.get("id")}
    down, restopped, started, free_since = set(), set(), time.monotonic(), None
    while True:
        agents = agents_all()
        registry = sessions_registry()
        live = live_copies(name, agents, registry)
        if agents is not None:
            listed = {a.get("id"): a for a in agents}
            down |= {i for i in ids if i not in listed or listed[i].get("state") in DOWN_STATES}
        revived = [a for a in live if a.get("id") in down]
        again = [a for a in revived if a["id"] in restopped]
        if again:
            start_log(f"stop-revived-again\t{name}\t{again[0]['id']}\t{again[0].get('state')}")
            return (f"{name}: копия {again[0]['id']} ожила и после повторного claude stop (сейчас "
                    f"{again[0].get('state')}) — новую не запускаю, иначе будет две. Закройте открытые окна просмотра "
                    f"claude agents, остановите её (claude stop {again[0]['id']}) и повторите запуск с --restart")
        if revived:
            stop_copies(name, revived, "stop-revived")
            restopped |= {a["id"] for a in revived}
            down -= restopped
        foreign = [a for a in live if a.get("id") not in ids]
        if foreign:
            start_log(f"stop-wait-foreign\t{name}\t{_holder_text(foreign[0])}")
            return copies_message(name, foreign)
        holders = name_holders(name, agents, registry) if agents is not None else None
        t = time.monotonic()
        spent = t - started
        if holders == [] and not revived:
            free_since = t if free_since is None else free_since
            if t - free_since >= settle:
                start_log(f"stop-wait-free\t{name}\t{spent:.1f}")
                return None
            time.sleep(poll)
            continue
        free_since = None
        if spent >= wait:
            held = "; ".join(_holder_text(a) for a in holders) if holders else "claude agents не ответил"
            start_log(f"stop-wait-timeout\t{name}\t{wait:.0f}\t{held}")
            return (f"{name}: за {wait:.0f} с остановленные копии не отпустили имя ({held}) — новую не запускаю: "
                    f"Claude Code назвал бы её «{name}-два-слова», и сообщения на {name} до неё не дойдут. Проверьте "
                    f"claude agents и повторите запуск с --restart")
        time.sleep(poll)


def check_new_name(name, before):
    """После `claude --bg --name <имя>`: новая живая сессия (её id не было в списке до запуска) получила ровно это имя,
    а не «имя-два-слова» или «имя (2)». → None или текст тревоги. Чужую копию не останавливает — решает Зевс. Не
    появилась за PANTHEON_NAME_WAIT (10 с) — строка в start.log и None: claude --bg отработал, а «не появилась» дежурный
    проверяет сам (autostart_check)."""
    _, poll, _ = stop_wait_knobs()
    wait = 10.0
    with contextlib.suppress(ValueError, TypeError):
        wait = max(0.0, float(os.environ.get("PANTHEON_NAME_WAIT") or wait))
    alias, started = name_alias(name), time.monotonic()
    while True:
        new = [a for a in agents_all() or [] if a.get("id") and a.get("id") not in before
               and a.get("state") not in DOWN_STATES and alias.fullmatch(str(a.get("name") or ""))]
        wrong = [a for a in new if a.get("name") != name]
        if wrong:
            ids = ", ".join(f"{a['id']} «{a.get('name')}»" for a in wrong)
            start_log(f"name-mismatch\t{name}\t{ids}")
            return (f"{name}: новая сессия получила чужое имя — {ids}: имя «{name}» держала другая сессия, сообщения на "
                    f"{name} до неё не дойдут. Что сделать: claude agents — найти, кто держит «{name}», лишнее "
                    f"остановить и повторить запуск с --restart (он остановит и {wrong[0]['id']}); pantheon её не "
                    "останавливал")
        if new:
            start_log(f"name-ok\t{name}\t{new[0]['id']}")
            return None
        if time.monotonic() - started >= wait:
            start_log(f"name-unseen\t{name}")
            print(f"pantheon start: новой сессии {name} за {wait:.0f} с нет в claude agents — имя не проверено",
                  file=sys.stderr)
            return None
        time.sleep(poll)


def start_log(line):
    os.makedirs(path("logs"), exist_ok=True)
    with open(path("logs", "start.log"), "a") as fh:
        fh.write(f"{stamp()}\t{line}\n")


def launch_folder(folders):
    """Папка запуска координатора — одно правило для start, direction check и direction init: первая существующая
    папка записи (настоящим путём), иначе первая в списке, иначе ""."""
    real = [os.path.realpath(os.path.expanduser(f)) for f in folders or [] if isinstance(f, str) and f]
    return next((f for f in real if os.path.isdir(f)), real[0] if real else "")


def start_target(target, rest):
    """→ (имя сессии, роль, папка запуска, файл окна, поручение по умолчанию) или текст ошибки."""
    domains = read_json(path("domains.json"), {}).get("domains") or {}
    if target == "workshop":
        if not rest or not SESSION_NAME.fullmatch(rest[0]):
            return "pantheon start workshop <задача> [поручение]: имя задачи — a-z, 0-9, дефис"
        task, folder = rest[0], os.path.join(WORKSHOP, rest[0])
        os.makedirs(folder, exist_ok=True)
        if os.path.islink(folder) or not os.path.realpath(folder).startswith(os.path.realpath(WORKSHOP) + "/"):
            return f"папка задачи мастерской {folder} — ссылка или вне ~/projects/workshop"
        return (f"daedalus-{task}", "workshop", folder, "workshop",
                f"Прочитай ~/ai/pantheon/workshop/{task}.md и выполни задачу. Внешние действия — только по "
                "approvals.toml или после «да» владельца в этой сессии.")
    if target not in domains:
        return f"нет направления «{target}» в domains.json (реестр ~/ai/pantheon/directions.toml → pantheon domains build)"
    folder = launch_folder(domains[target])
    if not os.path.isdir(folder):
        return f"у направления {target} нет папки на этом Mac: {domains[target]}"
    return (target, "domain-coordinator", folder, target,
            f"Прочитай ~/ai/pantheon/directions/{target}/STATUS.md и inbox/, затем продолжай текущий эпик по нему.")


def start_at(rest, origin, dry):
    """Разовый запуск плановым проходом вместо `sleep` в сессии (metis-0284): запись в STATE/oneshot.json, исполняет
    дежурный один раз (lib/watch.py oneshots). Та же подкоманда start — те же права, что у запуска."""
    N = night_mod()
    t = now()
    if rest == ["--at-list"]:
        for ln in N.oneshot_lines(t) or ["разовых запусков нет"]:
            print(ln)
        return 0
    if rest[:1] == ["--at-cancel"] and len(rest) == 2:
        if N.oneshot_cancel(rest[1], t, f"pantheon start --at-cancel ({origin})"):
            print(f"разовый запуск {rest[1]} отменён")
            return 0
        print(f"pantheon start: разового запуска {rest[1]} нет или он уже погашен", file=sys.stderr)
        return 1
    i = rest.index("--at") if "--at" in rest else -1
    if i < 0 or i + 1 >= len(rest) or "--at-list" in rest or "--at-cancel" in rest:
        print("pantheon start <направление> --at ЧЧ:ММ|\"ГГГГ-ММ-ДД ЧЧ:ММ\" [поручение] | --at-list | --at-cancel <id>",
              file=sys.stderr)
        return 2
    when_s, rest = rest[i + 1], rest[:i] + rest[i + 2:]
    if not rest:
        print("pantheon start --at: кого запустить — направление", file=sys.stderr)
        return 2
    target, text = rest[0], " ".join(rest[1:]).strip()
    domains = read_json(path("domains.json"), {}).get("domains") or {}
    if target not in domains:
        print(f"pantheon start --at: «{target}» — не направление из domains.json (разовый запуск — только направлений)",
              file=sys.stderr)
        return 2
    try:
        when = N.parse_at(when_s, t)
    except ValueError as e:
        print(f"pantheon start --at: {e}", file=sys.stderr)
        return 2
    got = start_target(target, [])
    text = text or (got[4] if not isinstance(got, str) else "")
    if dry:
        print(f"[at] {target} в {stamp(when)} — {text}")
        return 0
    oid = N.oneshot_add(target, when, text, origin, t=t)
    print(f"разовый запуск {oid}: {target} в {stamp(when)} — исполнит плановый проход (pantheon watch), срок "
          f"{N.ONESHOT_TTL // 3600} ч; отмена — pantheon start --at-cancel {oid}")
    return 0


def start(rest):
    """pantheon start <направление> [поручение] | workshop <задача> [поручение] | zeus [--restart]  [--from кто] [--dry-run]
    pantheon start <направление> --at ЧЧ:ММ|"ГГГГ-ММ-ДД ЧЧ:ММ" [поручение] | --at-list | --at-cancel <id>   разовый запуск
                                                                                    плановым проходом (вместо sleep)"""
    dry = "--dry-run" in rest
    restart = "--restart" in rest
    rest = [a for a in rest if a not in ("--dry-run", "--restart")]
    origin = "owner"
    if "--from" in rest:
        i = rest.index("--from")
        if i + 1 >= len(rest) or rest[i + 1] not in ("zeus", "tick", "owner"):
            print("pantheon start: --from zeus | tick | owner", file=sys.stderr)
            return 2
        origin, rest = rest[i + 1], rest[:i] + rest[i + 2:]
    if any(a in ("--at", "--at-list", "--at-cancel") for a in rest):
        return start_at(rest, origin, dry)
    if not rest:
        print(start.__doc__, file=sys.stderr)
        return 2
    target, rest = rest[0], rest[1:]
    if target == "zeus":
        # штаб — ваша интерактивная сессия в iTerm: команда заменяет себя на claude в ~/ai/pantheon
        argv = [claude_bin(), "--agent", "hq", "--name", "zeus", "--settings", path("settings", "hq.json")]
        if dry:
            print(shlex.join(argv), f"(папка {PANTHEON})")
            return 0
        if not os.path.isfile(path("settings", "hq.json")):
            print("нет окна Пританея — сначала pantheon domains build", file=sys.stderr)
            return 1
        if not sys.stdin.isatty():
            print("Пританей запускается в вашем терминале: pantheon start zeus", file=sys.stderr)
            return 2
        # Зевс — одна сессия. Вкладка iTerm — только окно к фоновой сессии: закрыть вкладку или убить её процесс
        # мало, сессия живёт дальше, и новый запуск становится «zeus-<два слова>» (15.10 так появилось два Зевса)
        with lock("start-zeus", block=False) as got:
            if not got:
                print("Зевс уже запускается другой командой", file=sys.stderr)
                return 1
            live = live_copies("zeus", agents_all())
            if live and (not restart or any(not a.get("id") for a in live)):
                print(f"pantheon start: {copies_message('zeus', live)}", file=sys.stderr)
                return 1
            stop_copies("zeus", live)
            # execv заменяет процесс — имя после запуска не проверить, поэтому до запуска ждём, пока старый Зевс
            # отпустит имя (15.10 без ожидания новый стал zeus-sparkling-cat, metis-0041)
            why = wait_name_free("zeus", live) if live else None
            if why:
                print(f"pantheon start: {why}", file=sys.stderr)
                return 1
        start_log(f"zeus\t{origin}\t{PANTHEON}")
        os.chdir(PANTHEON)
        os.execv(argv[0], argv)
    got = start_target(target, rest)
    if isinstance(got, str):
        print(f"pantheon start: {got}", file=sys.stderr)
        return 2
    name, role, folder, window, default_task = got
    if target == "workshop":
        rest = rest[1:]
    win = path("settings", window + ".json")
    problems = allow_gate(name)  # allow со старым mtime сборка не заметила (ревью argus PR #32)
    if problems:
        print(f"pantheon start: окно не собрано — {project_allow_text(name, problems)}", file=sys.stderr)
        return 1
    if not os.path.isfile(win):
        print(f"pantheon start: нет окна {win.replace(HOME, '~')} — pantheon domains build", file=sys.stderr)
        return 1
    if os.path.exists(path("stopped", name)):
        print(f"pantheon start: {name} остановлена вами (pantheon resume {name})", file=sys.stderr)
        return 1
    # одна сессия на имя (Temporal: conflict policy «fail» по умолчанию, «terminate existing» — по --restart);
    # проверка и запуск — под блокировкой имени: тик и Зевс не запустят две копии одновременно
    with lock("start-" + name, block=False) as got:
        if not got:
            print(f"pantheon start: {name} уже запускается другой командой", file=sys.stderr)
            return 1
        return _start_session(name, role, folder, window, default_task, rest, origin, dry, restart, win)


def _start_session(name, role, folder, window, default_task, rest, origin, dry, restart, win):
    agents = agents_all()
    same = [a for a in agents or [] if a.get("name") == name]
    live = live_copies(name, agents)
    if live and not dry and (not restart or any(not a.get("id") for a in live)):
        print(f"pantheon start: {copies_message(name, live)}", file=sys.stderr)
        return 1
    stopped = []
    if live and not dry:
        stop_copies(name, live)
        stopped += live
    # CTX-10: эпик закончен — сессия «done» ещё висит в списке; новый эпик — новая сессия с тем же именем, а старая
    # останавливается и убирается из списка (claude rm, metis-0239; переписка остаётся: claude --resume <сессия>),
    # иначе Claude Code назовёт новую «имя (2)»
    # (claude rm прежних — только после успешного старта новой, rm_previous, metis-0250)
    for a in same:
        if a.get("state") == "done" and a.get("pid") and a.get("id") and not dry:
            stop_copies(name, [a], "stop-done")
            stopped.append(a)
    # остановленная копия отпускает имя не сразу и может ожить (metis-0041): запуск — только когда имя свободно
    why = wait_name_free(name, stopped) if stopped else None
    if why:
        print(f"pantheon start: {why}", file=sys.stderr)
        return 1
    run = path("settings", "run", name + ".json")
    task = " ".join(rest).strip() or default_task
    prompt = f"{START_MARK} поручение от {origin}] {task}"
    if role == "domain-coordinator":
        # DONE-02: /goal первым словом поручения — Stop-хук сессии с отдельной проверяющей моделью: координатор не
        # закончит, пока условие не выполнено (проверено вживую 15.10: `claude --bg "/goal …"` включает цель)
        prompt = "/goal " + prompt + " " + (TASK_GOAL if " ".join(rest).strip() else COORDINATOR_GOAL)
    argv = [claude_bin(), "--bg", "--agent", role, "--name", name, "--settings", run, prompt]
    if dry:
        print(shlex.join(argv), f"(папка {folder})")
        return 0
    if run_settings(name, role, window, origin) != run:  # окно пропало после проверки — прежний файл запуска не берём
        print(f"pantheon start: нет окна {win.replace(HOME, '~')} — pantheon domains build", file=sys.stderr)
        return 1
    before = {a.get("id") for a in agents_all() or [] if a.get("id")}
    r = subprocess.run(argv, cwd=folder, capture_output=True, text=True, timeout=180)
    start_log(f"{name}\t{origin}\t{folder}\t{r.returncode}")
    if origin == "zeus" and r.returncode == 0 and not owner_spoke_recently("zeus", OWNER_WORD_WINDOW):
        alert(f"запуск {name} по поручению Зевса без вашего слова в его окне за {OWNER_WORD_WINDOW // 60} мин — "
              "возможно, по сообщению другой сессии (лазейка на время доработки, decisions.md 15.10)", "pantheon-start")
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        return r.returncode
    wrong = check_new_name(name, before)
    if wrong:
        alert(wrong, "pantheon-start")
        print(f"pantheon start: {wrong}", file=sys.stderr)
        return 1
    rm_previous(name, "start", before=before, loud=True)
    return 0


# Лазейка на время доработки (ваше решение 15.10): Зевс запускает направления и по сообщениям других сессий. Чтобы это
# было видно, запуск «от Зевса» без вашей строки в его журнале owner-log за последние минуты — строка в тревогах.
OWNER_WORD_WINDOW = 15 * 60
OWNER_HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", re.M)


def owner_spoke_recently(session, window):
    """Есть ли в ~/.local/state/pantheon/owner-log/<session>.md запись владельца не старше window секунд."""
    try:
        with open(path("owner-log", session + ".md"), "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 65536))
            heads = OWNER_HEAD.findall(fh.read().decode("utf-8", "replace"))
    except OSError:
        return False
    if not heads:
        return False
    try:
        last = datetime.strptime(heads[-1], "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return False
    return now() - last <= window


def open_tasks(name):
    """Открытые задачи, которые ведёт сессия: её направление, владелец или аренда."""
    out = []
    for tid, (_, head, _) in tasks_mod().load_tasks(PANTHEON).items():
        if head.get("status") not in OPEN_STATUSES:
            continue
        if name in (head.get("owner"), head.get("claimed_by"), head.get("direction")):
            out.append(tid)
    return out


def wake_recheck(name, state=None):
    """Под блокировкой имени перед подъёмом: метка, пауза, техперезапуск, живая копия «имя (2)» (ревью argus).
    state == "blocked" — сессия на лимите: «живая» для claude agents, её и будим, копии не ищем."""
    if state == "blocked":
        return awake_mod().recheck(name)
    if os.path.exists(path("stopped", name)):
        return "остановлено вами"
    if load_pause(name):
        return "пауза по нагрузке"
    if maintenance_active():
        return "технический перезапуск"
    if live_copies(name, agents_all() or []):
        return "уже работает"
    return None


def wake_hestia(rest):
    """pantheon wake hestia [--task <id>] (metis-0217, шаг 1): запуск Гестии отказывает всегда, код 2. Роль собирается, но
    у неё нет окна песочницы (hestia не в guard PANTHEON_ROLES, `claude -p --agent hestia` шёл бы сессией владельца
    без границы прав), поэтому claude не зовётся. Запуск откроет metis-0245 (окно песочницы) отдельным PR ядра после «да» владельца."""
    print("pantheon wake hestia: отказ — нет окна песочницы (metis-0245); claude не запускался", file=sys.stderr)
    return 2


def wake(rest):
    """pantheon wake [--dry-run]: прерванные сессии Пантеона (failed, stopped) с открытой задачей — поднять и сказать
    «продолжай». Свои метки «остановлено вами» и чужие сессии (не направление и не daedalus-*) не трогает."""
    dry = "--dry-run" in rest
    with lock("wake", block=False) as got:
        if not got:
            print("pantheon wake: уже идёт в другом процессе")
            return 0
        return _wake(dry)


def _wake(dry):
    m = maintenance_active()
    if m:
        print(f"идёт технический перезапуск ({m.get('reason')}) — будить некого до pantheon restart --go")
        return 0
    agents = agents_all()
    if agents is None:
        print("pantheon wake: claude agents --json не ответил", file=sys.stderr)
        return 1
    domains = read_json(path("domains.json"), {}).get("domains") or {}
    done = failed = 0
    for a in agents:
        name, state = a.get("name") or "", a.get("state")
        asleep = state in ("failed", "stopped")
        if not asleep and state == "blocked":  # стоит на недельном лимите, сброс прошёл (metis-0132) — тоже спит
            with contextlib.suppress(Exception):
                asleep = awake_mod().limit_sleeping(a) is not None
        if not asleep or not (name in domains or name.startswith("daedalus-")):
            continue
        if os.path.exists(path("stopped", name)) or load_pause(name):
            continue
        newer = [b for b in agents if b.get("name") == name and (b.get("startedAt") or 0) > (a.get("startedAt") or 0)]
        if newer:
            continue  # эпик уже продолжен новой сессией с тем же именем
        tasks = open_tasks(name)
        if not tasks:
            continue
        fresh = fresh_reason(a)  # metis-0147 п. 2: большой контекст и остывший кэш — новая сессия с файла состояния
        how = (f"; свежей сессией ({fresh}), прочитает {' и '.join(tilde(p) for p in state_files(name))}" if fresh
               else "")
        line = f"{name} ({a.get('id')}, {state}) — задачи {', '.join(tasks[:3])}" + how
        if dry:
            print(f"будет поднята: {line}")
            continue
        if fresh:
            rc = fresh_start(name, a, fresh_text("пробуждение", name, a.get("id")), "wake",
                             recheck=lambda n=name, s=state: wake_recheck(n, s), reason=fresh)
        else:
            rc, _ = resume_session(name, a, WAKE_TEXT, "wake", recheck=lambda n=name, s=state: wake_recheck(n, s))
        if rc == SKIPPED:  # metis-0291: пропуск — не сбой, ни «поднимаю», ни тревоги
            print(f"пропуск: {name} — {SKIP_WHY}")
            done += 1
            continue
        done += 1
        if rc == NO_WINDOW:  # «нет окна» — своя тревога, одна на причину; владельцу не говорим, что подняли (metis-0189)
            print(f"не поднимаю: {name} ({a.get('id')}, {state}) — см. тревогу")
            failed += 1
        elif rc:  # настоящий сбой подъёма: тревога и код 1 (metis-0291)
            print(f"не поднялась: {name} ({a.get('id')}, {state}) — код {rc}", file=sys.stderr)
            alert(f"pantheon wake: {name} не поднялась (код {rc})", "pantheon")
            failed += 1
        else:
            print(f"поднимаю: {line}")
    if not done:
        print("будить некого")
    return 1 if failed else 0


# --- роли (ROLE-15, ROLE-16, ROLE-17) -------------------------------------------------------
# Два слоя шаблонов (metis-0182). Общий — в плагине: PLUGIN/roles/<роль>.tmpl и PLUGIN/roles/_parts/<часть>.part, без
# проектов, коллекций, браузера и имён владельца; приходит с выпуском плагина. Личный — ~/.claude/agents/ (у владельца
# его синхронизирует claude-config; правит только metis-pantheon — guard protect-config): личный <роль>.tmpl перекрывает
# общий по имени, личная _parts/<часть>.part — общую часть. Набор ролей — объединение слоёв. Сборка кладёт в
# ~/.claude/agents <роль>.md — то, что читает Claude Code; собранные файлы claude-config не синхронизирует (строки в
# ~/.claude/.gitignore): на каждом Mac их собирает тик вместе с domains.json, когда меняется шаблон, часть или реестр.
#   {{> часть}}         — текст части (одна общая формулировка: отчёт, находка, внешние действия, доведение до конца);
#   {{qmd_collections}} {{browser}} — во всех ролях, после вставки частей, из раздела [person] реестра (PERSON_*).
#                         Пустое значение или нет раздела — строка шаблона с подстановкой выпадает целиком, вместе с
#                         переводом строки. Поэтому в шаблонах такая подстановка стоит в своей строке-фразе, а текст
#                         вокруг неё связен и без неё;
#   hephaestus, apollo  — роли лидов: по одной на направление с этим лидом в поле leads реестра,
#                         hephaestus-<коротко> (example-site → site), подстановки {{direction}} {{short}}
#                         {{project}} {{folders}}.
# Свой файл узнаётся по строке-метке после шапки; файл без метки (свой ли, чужой ли) сборка не трогает, собранный файл
# без шаблона — убирает. Ошибка в шаблоне (нет части, осталась {{…}}, значение реестра не по образцу) — роль не
# пишется, старая версия остаётся.
AGENTS = os.path.join(HOME, ".claude", "agents")
PARTS = os.path.join(AGENTS, "_parts")
# общий слой; PANTHEON_PLUGIN_ROLES подменяет его в тестах
PLUGIN_ROLES = os.path.realpath(os.environ.get("PANTHEON_PLUGIN_ROLES") or os.path.join(PLUGIN, "roles"))
PLUGIN_PARTS = os.path.join(PLUGIN_ROLES, "_parts")
LEAD_ROLES = ("hephaestus", "apollo")
ROLE_MARK = "<!-- собрано pantheon roles build из {tmpl} — правят шаблон, а не этот файл -->"
ROLE_NAME = re.compile(r"[a-z][a-z0-9-]{0,40}")
# значения из реестра в шаблон лида: одна строка без разметки YAML. Реестр может править штаб из песочницы, а шапка
# роли (hooks, mcpServers) запускает команды вне её — перевод строки в project дописал бы в шапку хук (проверка
# безопасности 15.10). Сверх образца — сверка ключей шапки до и после подстановки.
ROLE_PROJECT = re.compile(r"[\w][\w .,()«»+-]{0,59}")
ROLE_FOLDER = re.compile(r"~?/[\w.-]+(?:/[\w.-]+)*")
# [person] реестра → текст всех ролей. Довод тот же, что у ROLE_PROJECT (реестр правит штаб из песочницы, а текст
# попадает в роли всех): одна строка из букв, цифр, пробела и простой пунктуации — без {{ }}, обратных кавычек, < >,
# перевода строки; «---» запрещён отдельно (граница шапки YAML).
#   qmd_collections = ["имя" | "имя (что в ней)", …] — в роли через запятую;
#   browser = "одна строка" — браузер владельца для сайтов со входом и, если нужно, адрес демона CDP.
PERSON_ITEM = re.compile(r"[\w][\w .,:;()«»+/~—–-]{0,79}")
PERSON_TEXT = re.compile(r"[\w][\w .,:;()«»\"'+/~!?%#№—–-]{0,199}")
PERSON_KEYS = ("qmd_collections", "browser")
PERSON_MAX_ITEMS = 20


def _head_keys(text):
    end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
    return [ln.split(":", 1)[0] for ln in text[4:end].splitlines() if re.match(r"[A-Za-z_]", ln)] if end > 0 else None


def _role_text(tmpl_text, parts=None):
    """Вставка частей {{> x}}: сначала <parts>/x.part (личный слой), потом общая часть плагина."""
    def part(m):
        if ROLE_NAME.fullmatch(m.group(1)):
            for d in (parts or PARTS, PLUGIN_PARTS):
                p = os.path.join(d, m.group(1) + ".part")
                if os.path.isfile(p):
                    return open(p, encoding="utf-8").read().rstrip("\n")
        raise ValueError(f"нет части {m.group(1)}")
    return re.sub(r"\{\{>\s*([\w-]+)\s*\}\}", part, tmpl_text)


def person_values(reg):
    """[person] реестра → ({ключ: текст или ""}, {ключ: ошибка}). Значение не по образцу — ошибка, а не пустота:
    роль с этой подстановкой не собирается, её старая версия остаётся."""
    person, values, bad = reg.get("person"), {k: "" for k in PERSON_KEYS}, {}
    if person is None:
        return values, bad
    if not isinstance(person, dict):
        return values, {k: "раздел [person] реестра — не таблица" for k in PERSON_KEYS}

    def ok(v, rx):
        return isinstance(v, str) and (not v.strip() or ("---" not in v and bool(rx.fullmatch(v.strip()))))
    cols = person.get("qmd_collections", [])
    if isinstance(cols, list) and len(cols) <= PERSON_MAX_ITEMS and all(ok(c, PERSON_ITEM) for c in cols):
        values["qmd_collections"] = ", ".join(c.strip() for c in cols if c.strip())
    else:
        bad["qmd_collections"] = "[person] qmd_collections в реестре не по образцу"
    browser = person.get("browser", "")
    if ok(browser, PERSON_TEXT):
        values["browser"] = browser.strip()
    else:
        bad["browser"] = "[person] browser в реестре не по образцу"
    return values, bad


def _person_text(text, values, bad):
    """Подстановки [person] построчно: строка с пустой подстановкой выпадает целиком; плохое значение — ValueError.
    В шапке YAML (между первыми ---) подстановка [person] запрещена целиком, и с пустым значением: в шапке живут
    хуки роли, они идут вне песочницы, а образец значений пропускает кавычки и «;» — значение стало бы командой."""
    end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
    head = text[:end + 5] if end > 0 else ""
    in_head = [k for k in PERSON_KEYS if "{{" + k + "}}" in head]
    if in_head:
        raise ValueError("подстановка [person] в шапке роли запрещена: "
                         + ", ".join("{{" + k + "}}" for k in in_head))
    lines = []
    for ln in text.splitlines(keepends=True):
        keys = [k for k in PERSON_KEYS if "{{" + k + "}}" in ln]
        for k in keys:
            if k in bad:
                raise ValueError(bad[k])
        if any(not values[k] for k in keys):
            continue
        for k in keys:
            ln = ln.replace("{{" + k + "}}", values[k])
        lines.append(ln)
    out = "".join(lines)
    if _head_keys(out) != _head_keys(text):
        raise ValueError("подстановка [person] поменяла шапку роли")
    return out


def _marked(text, tmpl):
    """Метка — сразу после шапки YAML: файл роли должен начинаться с ---."""
    end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
    if end < 0:
        raise ValueError("нет шапки YAML (--- … ---)")
    return text[:end + 5] + ROLE_MARK.format(tmpl=tmpl) + "\n" + text[end + 5:]


# Шаблоны, которые build пока не собирает (metis-0217, review-51-bypass): роль, которую нельзя звать до окна
# песочницы, не должна лежать в ~/.claude/agents — иначе её поднимет субагент мимо отказа wake. Убрать строку —
# когда слит metis-0245. Уже собранный файл с меткой build убирает как устаревшую роль.
ROLES_DEFERRED = {"hestia": "metis-0245"}


def roles_build(src=None, out=None, role_errors=None):
    """Роли из общих шаблонов плагина (PLUGIN_ROLES) и личного слоя src (по умолчанию ~/.claude/agents; перекрывает
    общий по имени шаблона и части) в папку out (по умолчанию ~/.claude/agents). Режим с out — проба
    (metis-0097): пишет и чистит только в out, владельцу сигнал не шлёт; out в ~/.claude/agents или внутри — ValueError.
    role_errors — словарь {шаблон.tmpl: [ошибки]}: сюда же ошибки по ролям (role apply сверяет свою роль); печать в
    stderr и тревога — как без него, возвращается по-прежнему список изменённых файлов."""
    probe = out is not None
    src = src or AGENTS
    if probe:
        real_out, real_agents = os.path.realpath(os.path.expanduser(out)), os.path.realpath(AGENTS)
        if real_out == real_agents or real_out.startswith(real_agents + os.sep):
            raise ValueError(f"--out {out} совпадает с {AGENTS} или лежит внутри: пробная сборка живые роли не трогает")
        out = real_out
    else:
        out = AGENTS
    parts = os.path.join(src, "_parts")
    with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
        reg = tomllib.load(fh)
    person, person_bad = person_values(reg)
    want, errors = {}, []

    def err(tmpl, text):
        errors.append(text)
        if role_errors is not None:
            role_errors.setdefault(tmpl, []).append(text)

    # роли, чей шаблон или подстановка с ошибкой: старую собранную версию не убирать (имя или начало имени лида)
    kept, kept_leads = set(), set()
    layer = {}  # объединение слоёв: личный шаблон из src перекрывает общий из плагина по имени
    for d in (PLUGIN_ROLES, src):
        for f in os.listdir(d) if os.path.isdir(d) else []:
            if f.endswith(".tmpl"):
                layer[f] = os.path.join(d, f)
    for f in sorted(layer):
        base = f[:-5]
        if base in ROLES_DEFERRED:
            continue
        if not ROLE_NAME.fullmatch(base):
            err(f, f"{f}: имя не по образцу")
            continue
        try:
            text = _person_text(_role_text(open(layer[f], encoding="utf-8").read(), parts), person, person_bad)
        except (OSError, ValueError) as e:
            err(f, f"{f}: {e}")
            if base in LEAD_ROLES:
                kept_leads.add(base + "-")
            else:
                kept.add(base + ".md")
            continue
        if base not in LEAD_ROLES:
            want[base + ".md"] = (f, text)
            continue
        for d in reg.get("direction") or []:
            name = d.get("name", "")
            if base not in (d.get("leads") or []) or not re.fullmatch(r"[a-z0-9]+-[a-z0-9-]+", name):
                continue
            short = name.split("-", 1)[1]
            project, folders = d.get("project", ""), d.get("folders") or []
            if not (isinstance(project, str) and (not project or ROLE_PROJECT.fullmatch(project))) \
                    or not isinstance(folders, list) \
                    or not all(isinstance(x, str) and ROLE_FOLDER.fullmatch(x) for x in folders):
                err(f, f"{f} → {base}-{short}.md: project или folders направления {name} не по образцу")
                kept.add(f"{base}-{short}.md")
                continue
            out_text = (text.replace("{{direction}}", name).replace("{{short}}", short)
                        .replace("{{project}}", project).replace("{{folders}}", ", ".join(folders)))
            if _head_keys(out_text) != _head_keys(text):
                err(f, f"{f} → {base}-{short}.md: подстановка поменяла шапку роли")
                kept.add(f"{base}-{short}.md")
                continue
            want[f"{base}-{short}.md"] = (f, out_text)
    made = []
    if want:  # и на новой машине: ~/.claude/agents ещё нет, а общие роли плагина собрать надо
        os.makedirs(out, exist_ok=True)
    for fname, (tmpl, text) in sorted(want.items()):
        out_file = os.path.join(out, fname)
        try:
            if "{{" in text:
                raise ValueError("осталась подстановка {{…}}")
            text = _marked(text, tmpl)
        except ValueError as e:
            err(tmpl, f"{tmpl} → {fname}: {e}")
            continue
        old = open(out_file, encoding="utf-8").read() if os.path.exists(out_file) else None
        if old is not None and "pantheon roles build" not in old[:2000]:
            err(tmpl, f"{fname} есть и написан не сборкой — не трогаю (убрать его или шаблон {tmpl})")
            continue
        if old != text:
            write_atomic(out_file, text)
            made.append(fname)
    for f in sorted(os.listdir(out)) if os.path.isdir(out) else []:
        p = os.path.join(out, f)
        if f in kept or any(f.startswith(x) for x in kept_leads):
            continue
        if f.endswith(".md") and f not in want and not os.path.islink(p) and os.path.isfile(p):
            if "pantheon roles build" in open(p, encoding="utf-8").read(2000):
                os.remove(p)
                made.append(f"-{f}")
    for e in errors:
        print(f"roles build: {e}", file=sys.stderr)
    if errors and not probe:
        alert_once("roles-build", "\n".join(errors), f"pantheon roles build: {errors[0]}"
                   + (f" (и ещё {len(errors) - 1})" if len(errors) > 1 else ""), "pantheon")
    if not probe:
        memo_line = who_is_who_alert()
        if memo_line:
            print(f"roles build: {memo_line}", file=sys.stderr)
    return made


# --- личная роль: заявка и установка по вашей галочке (metis-0262 PR 4, решения [zeus-role-apply], [zeus-role-board]) ---
# Черновик роли готовит агент: ~/ai/pantheon/roles/proposed/<имя>.tmpl. `pantheon role propose <имя> --direction D`
# заводит карточку «Применить роль <имя> [<sha256>]?» с вариантами Да/Нет и статус proposed в STATE/roles/status.jsonl
# (вне ~/ai/pantheon; файл пишут только команды role и тик). sha256 черновика — полный, все 64 знака: правка черновика
# после галочки меняет хеш, и старая галочка его не ставит; урезанный хеш агент подобрал бы вторым черновиком
# (argus-70b). Ваш ответ тик переносит в owner-log/board.jsonl (роли туда не пишут); `role apply` и тик верят только
# ему и только на карточке из статуса заявки. В ~/.claude/agents пишет только `role apply` (её зовёт и тик):
# ворота → пробная сборка во временной папке → сверка шапки собранной роли → <имя>.tmpl в личный слой → `roles build`.
ROLE_PROPOSED = os.path.join(PANTHEON, "roles", "proposed")
ROLE_STATUS = ("proposed", "applied", "rejected", "cancelled")
ROLE_MAX_BYTES = 5 * 1024
ROLE_APPROVE_DAYS = 14
ROLE_NEW_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
# ключи шапки, с которыми роль выходит из песочницы или меняет права окна: хуки идут вне песочницы, mcpServers поднимают
# процессы, permissionMode снимает вопросы; settings — на будущее (сравнение без учёта регистра)
ROLE_HEAD_DENY = ("hooks", "settings", "mcpservers", "permissionmode")
# имена, которые знают guard и хуки (роли окон, системные субагенты, встроенные типы Claude Code) — личной роли не даём
# (встроенные агенты Claude Code: general-purpose, Explore, Plan, statusline-setup, claude-code-guide, output-style-setup,
# claude, fork; на будущие встроенные — весь claude-*)
ROLE_RESERVED = {"hq", "zeus", "workshop", "domain-coordinator", "tg-reader", "general-purpose", "explore", "plan",
                 "statusline-setup", "claude-code-guide", "output-style-setup", "claude", "fork"}
ROLE_RESERVED_PREFIX = tuple(b + "-" for b in LEAD_ROLES) + ("dev-", "codex-", "daedalus-", "claude-")


def role_sha(data):
    """Полный sha256 черновика (64 знака): по нему вопрос карточки, статус заявки и сверка галочки."""
    return hashlib.sha256(data).hexdigest()


def role_question(name, sha):
    return f"Применить роль {name} [{sha}]?"


def role_status_all():
    """STATE/roles/status.jsonl → {имя: [запись, …]} по порядку; действующий статус — последняя запись."""
    out = {}
    try:
        with open(path("roles", "status.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and isinstance(rec.get("name"), str) and rec.get("status") in ROLE_STATUS:
                    out.setdefault(rec["name"], []).append(rec)
    except OSError:
        pass
    return out


def role_last(name):
    return (role_status_all().get(name) or [None])[-1]


def role_status_add(name, status, **rec):
    os.makedirs(path("roles"), exist_ok=True)
    rec = {"time": datetime.fromtimestamp(now()).strftime("%Y-%m-%dT%H:%M:%S"), "name": name, "status": status, **rec}
    fd = os.open(path("roles", "status.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def role_name_problem(name):
    """Почему имя не годится для личной роли, или None."""
    if not (isinstance(name, str) and ROLE_NEW_NAME.fullmatch(name) and 2 <= len(name) <= 40):
        return f"имя «{name}» не по образцу: латиница в нижнем регистре, цифры, дефис между словами, 2–40 знаков"
    if os.path.isfile(os.path.join(PLUGIN_ROLES, name + ".tmpl")) or name in ROLES_DEFERRED or name in LEAD_ROLES:
        return f"«{name}» — общая роль Пантеона: личная роль с этим именем не ставится"
    if name in ROLE_RESERVED or name.startswith(ROLE_RESERVED_PREFIX):
        return (f"имя «{name}» занято системой (роли окон, лиды hephaestus-/apollo-, dev-*, codex-*, встроенные агенты "
                f"Claude Code, claude-*)")
    return None


def _role_head_end(text):
    return text.find("\n---\n", 3) if text.startswith("---\n") else -1


def role_head_problem(text):
    """Шапка YAML роли: есть, в ней name и нет запрещённых ключей, повторов ключа и строк не по образцу «ключ:
    значение». → текст или None. Строки с отступом и «- » — продолжение значения ключа выше; ключ в кавычках, «<<:»,
    «? » — отказ. Повтор ключа — отказ: Claude Code разбирает шапку Bun.YAML.parse, где побеждает последний ключ, а
    ворота сверяют первый (argus-70b: «name: foo» и ниже «name: argus» заняли бы имя общей роли)."""
    end = _role_head_end(text)
    if end < 0:
        return "нет шапки YAML (--- … ---) в начале"
    seen = set()
    for ln in text[4:end].splitlines():
        if not ln.strip() or ln.lstrip().startswith("#") or ln[:1] in (" ", "\t") or ln.startswith("- "):
            continue
        m = re.match(r"([A-Za-z][\w-]*)\s*:(?:\s|$)", ln)
        if not m:
            return f"строка шапки не по образцу «ключ: значение»: {ln[:60]!r}"
        if m.group(1).lower() in ROLE_HEAD_DENY:
            return (f"в шапке запрещённый ключ {m.group(1)} (hooks, settings, mcpServers, permissionMode: работают "
                    f"вне песочницы или меняют права)")
        if m.group(1).lower() in seen:
            return f"ключ {m.group(1)} в шапке повторён: Claude Code возьмёт последний, ворота — первый"
        seen.add(m.group(1).lower())
    return None if "name" in seen else "в шапке нет name:"


def role_head_name(text):
    """Значение name: из шапки роли (без кавычек и комментария) или «»."""
    end = _role_head_end(text)
    m = re.search(r"(?m)^name\s*:(.*)$", text[:end]) if end >= 0 else None
    return re.sub(r"\s+#.*$", "", m.group(1)).strip().strip("'\"") if m else ""


def role_head_check(text, name):
    """Шапка без запрещённого и повторов, и name: в ней — ровно name. → текст ошибки или None. Зовут на черновик и на
    собранную роль: часть ({{> …}}) или подстановка могут вставить в шапку то, чего в черновике не было."""
    bad = role_head_problem(text)
    if bad:
        return bad
    given = role_head_name(text)
    return None if given == name else f"name: в шапке «{given}», а имя роли — «{name}»"


def role_draft(name):
    """Черновик роли → (байты, ошибка). Обычный файл, не ссылка, не больше ROLE_MAX_BYTES."""
    p = os.path.join(ROLE_PROPOSED, name + ".tmpl")
    shown = p.replace(HOME, "~")
    try:
        st = os.lstat(p)
    except OSError:
        return None, f"нет черновика {shown}"
    if not stat.S_ISREG(st.st_mode):
        return None, f"черновик {shown} — не обычный файл (ссылка?)"
    with open(p, "rb") as fh:
        data = fh.read(ROLE_MAX_BYTES + 1)
    if len(data) > ROLE_MAX_BYTES:
        return None, f"черновик больше {ROLE_MAX_BYTES // 1024} КБ ({st.st_size} байт)"
    return data, None


def role_static_gate(name):
    """Ворота без вашей галочки: имя, черновик, размер, шапка, name: в шапке = имя. → (байты, sha256, [ошибки])."""
    bad = role_name_problem(name)
    if bad:
        return None, None, [bad]
    data, bad = role_draft(name)
    if bad:
        return None, None, [bad]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, None, ["черновик не в UTF-8"]
    bad = role_head_check(text, name)
    return data, role_sha(data), [bad] if bad else []


def role_answers(name, req, days=ROLE_APPROVE_DAYS):
    """Ваши ответы на карточку заявки req (запись статуса proposed: card, time) «Применить роль <имя> [<sha256>]?» из
    owner-log/board.jsonl (его пишет тик по вашей галочке, роли туда не пишут), не старше days дней и не раньше заявки,
    по времени: [(время, sha256, «да»|«нет», запись)]. Засчитывается только ответ на карточке req["card"]: «Да» на
    чужой карточке с тем же вопросом, на отозванной заявке или на прежней, после которой роль удалили руками, — не
    галочка (argus-70a, argus-70b). Вопрос — ровно этот текст; скрытый текст Obsidian в нём (%%…%%, <!-- -->) — не
    ответ, как в owner_approved."""
    card = (req or {}).get("card")
    try:
        asked = time.mktime(time.strptime(str((req or {}).get("time") or "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return []
    if not isinstance(card, str) or not card:
        return []
    ask = re.compile(rf"Применить роль {re.escape(name)} \[([0-9a-f]{{64}})\]\?")
    yes = re.compile(r"да(?![а-яёa-z0-9])", re.I)
    no = re.compile(r"нет(?![а-яёa-z0-9])", re.I)
    since, out = max(now() - days * 86400, asked), []
    try:
        lines = open(path("owner-log", "board.jsonl"), encoding="utf-8").read().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
            ts = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, AttributeError):
            continue
        q, a = rec.get("question"), str(rec.get("answer") or "").strip()
        if rec.get("kind") != "answer" or rec.get("id") != card or ts < since or not isinstance(q, str) \
                or re.search(r"%%|<", q):
            continue
        m = ask.fullmatch(q.strip())
        word = "да" if yes.match(a) else "нет" if no.match(a) else None
        if m and word:
            out.append((ts, m.group(1), word, rec))
    out.sort(key=lambda x: x[0])
    return out


def _role_card_close(card, status, result):
    """Карточку заявки — в «Готово» или «Отменено» с итогом; сбой (карточку убрали, шапка битая) не мешает делу."""
    if not card:
        return
    with contextlib.suppress(Exception):
        tasks_mod().task_set(PANTHEON, now(), card, {"status": status, "result": result}, actor="pantheon role")


def role_apply(name, by="pantheon role apply"):
    """Поставить личную роль по вашей галочке. → (код, текст): 0 — поставлена или уже стоит, 1 — отказ."""
    with lock("roles"):
        return _role_apply(name, by)


def _role_apply(name, by):
    data, sha, errs = role_static_gate(name)
    if errs:
        return 1, "; ".join(errs)
    last = role_last(name)
    tmpl, md = os.path.join(AGENTS, name + ".tmpl"), os.path.join(AGENTS, name + ".md")
    if last and last["status"] == "applied" and last.get("sha") == sha and os.path.isfile(md) \
            and os.path.isfile(tmpl) and open(tmpl, "rb").read() == data:
        return 0, f"роль {name} [{sha}] уже стоит"
    if not last or last["status"] != "proposed":
        return 1, (f"нет открытой заявки на роль {name} (статус: {last['status'] if last else 'нет'}) — "
                   f"сначала pantheon role propose {name} --direction <направление>")
    answers = role_answers(name, last)
    mine = [a for a in answers if a[1] == sha]
    if not mine:
        other = [a for a in answers if a[2] == "да"]
        if other:
            return 1, (f"галочка «Да» стоит на другой версии черновика [{other[-1][1]}], сейчас [{sha}]: черновик "
                       f"правлен после галочки — новая заявка: pantheon role propose {name} --direction <направление>")
        return 1, (f"нет вашей галочки «Да» на карточке {last.get('card')} «{role_question(name, sha)}» за "
                   f"{ROLE_APPROVE_DAYS} дней (журнал доски owner-log/board.jsonl)")
    _, _, word, rec = mine[-1]
    if word != "да":
        return 1, f"ваш последний ответ на «{role_question(name, sha)}» — «Нет»"
    if os.path.lexists(md) and (os.path.islink(md) or "pantheon roles build" not in
                                open(md, encoding="utf-8", errors="replace").read(2000)):
        return 1, f"{md.replace(HOME, '~')} есть и написан не сборкой — не трогаю"
    old = None
    if os.path.lexists(tmpl):
        old = None if os.path.islink(tmpl) else open(tmpl, "rb").read()
        ours = any(r["status"] == "applied" for r in role_status_all().get(name) or [])
        if old is None or (old != data and not ours):
            return 1, f"в личном слое уже есть свой {tmpl.replace(HOME, '~')} — не перекрываю"
    # пробная сборка: личный слой как есть + черновик, во временной папке; живые роли она не трогает
    with tempfile.TemporaryDirectory(prefix="role-apply-") as tmp:
        src, out = os.path.join(tmp, "src"), os.path.join(tmp, "out")
        os.makedirs(os.path.join(src, "_parts"))
        for d, dst, ext in ((AGENTS, src, ".tmpl"), (PARTS, os.path.join(src, "_parts"), ".part")):
            for f in os.listdir(d) if os.path.isdir(d) else []:
                p = os.path.join(d, f)
                if f.endswith(ext) and os.path.isfile(p) and not os.path.islink(p):
                    shutil.copyfile(p, os.path.join(dst, f))
        with open(os.path.join(src, name + ".tmpl"), "wb") as fh:
            fh.write(data)
        role_errs = {}
        with open(os.devnull, "w") as null, contextlib.redirect_stderr(null):
            roles_build(src, out, role_errors=role_errs)
        built = os.path.join(out, name + ".md")
        if role_errs.get(name + ".tmpl") or not os.path.isfile(built):
            return 1, "пробная сборка: " + "; ".join(role_errs.get(name + ".tmpl") or ["роль не собралась"])
        bad = role_head_check(open(built, encoding="utf-8").read(), name)
        if bad:
            return 1, f"пробная сборка (после вставки частей): {bad}"
    os.makedirs(AGENTS, exist_ok=True)
    part = f"{tmpl}.{os.getpid()}.tmp"
    with open(part, "wb") as fh:
        fh.write(data)
    os.replace(part, tmpl)
    role_errs = {}
    # живая сборка: ошибка по роли, нет .md, шапка .md не прошла сверку или исключение (диск, права) — откат шаблона
    try:
        roles_build(role_errors=role_errs)
        why = role_errs.get(name + ".tmpl") or ([] if os.path.isfile(md) else ["роль не собралась"])
        bad = None if why else role_head_check(open(md, encoding="utf-8").read(), name)
        why = why or ([f"шапка собранной роли: {bad}"] if bad else [])
    except Exception as e:  # noqa: BLE001 — любой сбой сборки оставлял бы непроверенный шаблон в личном слое
        why = [f"сбой {type(e).__name__}: {e}"]
    if why:
        if old is None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(tmpl)
        else:
            with open(part, "wb") as fh:
                fh.write(old)
            os.replace(part, tmpl)
        with contextlib.suppress(Exception):
            roles_build()
        return 1, "сборка в личном слое: " + "; ".join(why) + " — шаблон возвращён как был"
    role_status_add(name, "applied", sha=sha, by=by, card=last.get("card"), answer_time=rec.get("time"),
                    answer_card=rec.get("id"))
    _role_card_close(last.get("card"), "done", f"Роль {name} [{sha}] поставлена в личный слой ~/.claude/agents")
    return 0, (f"роль {name} [{sha}] поставлена: ~/.claude/agents/{name}.tmpl → {name}.md "
               f"(ваша галочка {str(rec.get('time') or '')[:16].replace('T', ' ')})")


def role_propose(name, direction):
    """Заявка: ворота без галочки, карточка с вопросом и статус proposed. Повтор с тем же черновиком — та же карточка;
    с правленым — новая, прежняя уходит в «Отменено». → (код, текст)."""
    with lock("roles"):
        data, sha, errs = role_static_gate(name)
        if errs:
            return 1, "; ".join(errs)
        last = role_last(name)
        if last and last["status"] == "proposed" and last.get("sha") == sha:
            return 0, f"заявка на роль {name} [{sha}] уже есть: карточка {last.get('card')}"
        q = role_question(name, sha)
        tid, _ = tasks_mod().task_new(
            PANTHEON, now(), direction, f"Применить личную роль {name}", actor="pantheon role", status="waiting",
            waiting_on="human", question=q,
            why=f"Черновик роли готов: roles/proposed/{name}.tmpl, {len(data)} байт. Галочка «Да» ставит его в ваш "
                f"личный слой ~/.claude/agents; правка черновика после галочки её отменяет.",
            options=[f"Да — поставить роль {name} в личный слой", "Нет — отклонить заявку"],
            recommend="Да — если черновик прочитан и роль нужна", if_no_answer="Роль не ставится, заявка ждёт.",
            text=f"Черновик: `~/ai/pantheon/roles/proposed/{name}.tmpl`, хеш {sha}.\n"
                 f"Поставить из терминала: `pantheon role apply {name}` — тоже только по галочке «Да».")
        if last and last["status"] == "proposed":
            _role_card_close(last.get("card"), "dropped", f"Заменена заявкой {tid}: черновик правлен")
        role_status_add(name, "proposed", sha=sha, card=tid, direction=direction)
        return 0, f"заявка на роль {name} [{sha}]: карточка {tid} «{q}»"


def role_cancel(name):
    with lock("roles"):
        last = role_last(name)
        if not last or last["status"] != "proposed":
            return 1, f"у роли {name} нет открытой заявки (статус: {last['status'] if last else 'нет'})"
        role_status_add(name, "cancelled", sha=last.get("sha"), card=last.get("card"))
        _role_card_close(last.get("card"), "dropped", f"Заявка на роль {name} отозвана")
        return 0, f"заявка на роль {name} отозвана"


def roles_tick():
    """Плановый проход: заявка proposed с вашим ответом на её черновик — «Да» ставит роль (role apply), «Нет» — статус
    rejected. Отказ apply — тревога (раз на причину), заявка остаётся до ответа или отзыва."""
    for name, recs in sorted(role_status_all().items()):
        last = recs[-1]
        if last["status"] != "proposed" or role_name_problem(name):
            continue
        answers = [a for a in role_answers(name, last) if a[1] == last.get("sha")]
        if not answers:
            continue
        _, sha, word, rec = answers[-1]
        if word == "нет":
            with lock("roles"):
                if (role_last(name) or {}).get("status") == "proposed":
                    role_status_add(name, "rejected", sha=sha, by="tick", card=last.get("card"),
                                    answer_time=rec.get("time"))
                    _role_card_close(last.get("card"), "dropped", f"Роль {name} отклонена вашим ответом «Нет»")
            continue
        code, text = role_apply(name, by="tick")
        if code:
            alert_once("role-apply-" + name, text, f"pantheon role apply {name}: {text}", "pantheon-tick")
        else:
            clear_once("role-apply-" + name)


def role_cmd(rest):
    usage = "pantheon role propose <имя> --direction D | apply <имя> | status [<имя>] | cancel <имя>"
    sub, args = (rest[0], rest[1:]) if rest else ("", [])
    if sub == "status" and len(args) <= 1:
        allst = role_status_all()
        names = args or sorted(allst)
        if not names:
            print("заявок на роли нет")
        for n in names:
            last = (allst.get(n) or [None])[-1]
            print(f"{n}: {last['status']} [{last.get('sha') or ''}] {str(last.get('time') or '')[:16].replace('T', ' ')}"
                  + (f" · карточка {last['card']}" if last.get("card") else "") if last else f"{n}: заявки нет")
        return 0
    ok = (sub == "propose" and len(args) == 3 and args[1] == "--direction") \
        or (sub in ("apply", "cancel") and len(args) == 1)
    if not ok or args[0].startswith("-"):
        print(usage, file=sys.stderr)
        return 2
    name = args[0]
    try:
        code, text = (role_propose(name, args[2]) if sub == "propose" else role_apply(name) if sub == "apply"
                      else role_cancel(name))
    except (OSError, ValueError) as e:
        code, text = 1, str(e)
    if code:
        print(f"role {sub}: отказ — {text}", file=sys.stderr)
    else:
        print(text)
    return code


# --- сверка памятки «Кто есть кто.md» с ролями и реестром (metis-0120) ----------------------------
WHO_MEMO = "Кто есть кто.md"
# Роли окон названы по функции, а в памятке — именем бога: hq — `zeus`, workshop — `daedalus-<задача>`; роль
# domain-coordinator — это все координаторы, отдельного имени у неё в памятке нет.
WHO_ALIAS = {"hq": ("zeus",), "workshop": ("daedalus",)}
WHO_ANY_DIRECTION = ("domain-coordinator",)
# «Лишнее» ищем только среди имён, начинающихся с бога: такой код в обратных кавычках — имя роли или направления.
# Остальной код (команды, пути, `claude agents`) под образец не подходит. Список — боги из карты имён и прошлых
# направлений; нового бога дописать сюда (иначе его удалённая роль не будет найдена как лишняя).
WHO_GODS = ("zeus", "athena", "hermes", "themis", "calliope", "mnemo", "proteus", "metis", "janus", "daedalus",
            "apollo", "hephaestus", "argus", "chiron", "prometheus", "talos", "clio", "iris", "momus", "charon", "hestia")
WHO_TOKEN = re.compile(r"`([^`\n]+)`")
WHO_WORD = re.compile(r"[a-z][a-z0-9-]*")
# Ещё места, где роли названы (metis-0252): холст «Кто есть кто.canvas» — по-русски (имя бога или слово), system.md —
# именем роли. Роль без строки здесь — «+имя (файл)» в той же тревоге. Новую роль без бога в холсте искать по её имени.
WHO_CANVAS_RU = {"hq": "Зевс", "workshop": "Дедал", "argus": "Аргус", "momus": "Мом", "prometheus": "Прометей",
                 "chiron": "Хирон", "clio": "Клио", "iris": "Ирида", "talos": "Талос", "hestia": "Гестия",
                 "hephaestus": "Гефест", "apollo": "Аполлон", "dev": "Разработчик", "codex-dev": "Codex",
                 "tg-reader": "Telegram", "domain-coordinator": "координатор"}


def who_is_who_names(text, roles, canvas=False):
    """Имена ролей, которых нет в тексте холста (canvas=True) или system.md. Лидам хватает приставки роли."""
    low = text.lower()
    words = {w.strip("-") for w in WHO_WORD.findall(low)}
    out = []
    for r in sorted(roles):
        keys = [r, r.split("-")[0]] if r.split("-")[0] in LEAD_ROLES or r.startswith("dev-") else [r]
        if canvas:
            ru = [WHO_CANVAS_RU[k].lower() for k in keys if k in WHO_CANVAS_RU] or ([] if r in WHO_CANVAS_RU else [r])
            def has(x):  # граница слева, справа — падежное окончание: «мом» в «Момент» — не роль (metis-0252)
                return re.search(r"(?<!\w)" + re.escape(x) + r"(?:а|у|е|ом|ы|и|ов|ам|ами|ах)?(?!\w)", low) is not None
            ok = any(has(x) for x in ru) or (r.startswith("dev-") and has("разработчик"))
        else:
            ok = any(k in words for k in keys)
        if not ok:
            out.append(r)
    return out


def who_is_who_diff(memo_text, roles, directions):
    """([нет в памятке], [лишнее в памятке]) — имена. roles — стебли файлов ролей, directions — имена направлений."""
    tokens = set(WHO_TOKEN.findall(memo_text))

    def prefix(pre):
        return any(t == pre or t.startswith(pre + "-") for t in tokens)
    missing = []
    for r in sorted(roles):
        if r in WHO_ANY_DIRECTION:
            ok = bool(set(directions) & tokens)
        elif r in WHO_ALIAS:
            ok = r in tokens or any(prefix(a) for a in WHO_ALIAS[r])
        elif r.split("-")[0] in LEAD_ROLES:
            ok = prefix(r.split("-")[0])
        else:
            ok = r in tokens
        if not ok:
            missing.append(r)
    missing += sorted(d for d in directions if d not in tokens)
    known = set(roles) | set(directions) | {"zeus"}
    lead_pre = {r.split("-")[0] for r in roles if r.split("-")[0] in LEAD_ROLES}
    aliases = {a for al in WHO_ALIAS.values() for a in al}
    extra = []
    for t in sorted(tokens):
        if not ROLE_NAME.fullmatch(t) or t.split("-")[0] not in WHO_GODS or t in known:
            continue
        if t in lead_pre or t in aliases or t.startswith("daedalus-"):
            continue
        extra.append(t)
    return missing, extra


def who_is_who_check(memo=None, agents=None, reg_path=None):
    """Сверка памятки. Нет памятки, папки ролей или реестра — None (проверять нечего). Иначе (нет, лишнее)."""
    memo = memo or os.path.join(PANTHEON, WHO_MEMO)
    agents = agents or AGENTS
    reg_path = reg_path or os.path.join(PANTHEON, "directions.toml")
    if not (os.path.isfile(memo) and os.path.isdir(agents) and os.path.isfile(reg_path)):
        return None
    try:
        with open(reg_path, "rb") as fh:
            reg = tomllib.load(fh)
        text = open(memo, encoding="utf-8").read()
    except (OSError, ValueError):
        return None
    roles = {f[:-3] for f in os.listdir(agents)
             if f.endswith(".md") and os.path.isfile(os.path.join(agents, f))}
    # роли из общих шаблонов плагина, ещё не собранные в agents (новая роль сразу после слияния), минус отложенные
    if os.path.isdir(PLUGIN_ROLES):
        roles |= {f[:-5] for f in os.listdir(PLUGIN_ROLES)
                  if f.endswith(".tmpl") and f[:-5] not in ROLES_DEFERRED
                  and os.path.isfile(os.path.join(PLUGIN_ROLES, f))}
    roles = sorted(roles)
    dirs = [d.get("name") for d in reg.get("direction") or [] if isinstance(d.get("name"), str)]
    missing, extra = who_is_who_diff(text, roles, dirs)
    base = os.path.dirname(memo)
    for fname, canvas in (("Кто есть кто.canvas", True), ("system.md", False)):
        try:
            other = open(os.path.join(base, fname), encoding="utf-8").read()
        except OSError:
            continue  # файла нет — не проверяем
        missing += [f"{n} ({fname.rsplit('.', 1)[-1] if canvas else fname})"
                    for n in who_is_who_names(other, roles, canvas)]
    return missing, extra


def who_is_who_alert(**kw):
    """Сверка + тревога штабу «памятку обновить: +имя / −имя» один раз на состояние; совпало — тревога снята.
    Возвращает строку расхождения или ""."""
    got = who_is_who_check(**kw)
    if got is None:
        return ""
    missing, extra = got
    if not (missing or extra):
        clear_once("who-is-who")
        return ""
    sysm = [n for n in missing if n.endswith("(system.md)")]
    rest = [f"+{n}" for n in missing if n not in sysm] + [f"−{n}" for n in extra]
    parts = (["памятку обновить: " + " / ".join(rest)] if rest else [])
    if sysm:  # system.md — не памятка: в тексте тревоги называем его самим именем (metis-0252)
        parts.append("system.md обновить: " + " / ".join("+" + n[:-len(" (system.md)")] for n in sysm))
    line = "; ".join(parts)
    alert_once("who-is-who", line, f"Кто есть кто.md: {line}", "pantheon")
    return line


def roles_newest():
    files = [os.path.join(PANTHEON, "directions.toml")]
    for d in (AGENTS, PARTS, PLUGIN_ROLES, PLUGIN_PARTS):
        if os.path.isdir(d):
            files += [os.path.join(d, f) for f in os.listdir(d) if f.endswith((".tmpl", ".part"))]
    return max((os.path.getmtime(p) for p in files if os.path.exists(p)), default=0)


# --- заранее разрешённые действия (DONE-11, SEC-26: красный флаг исследования) ------------------
# approvals.toml — ваше согласие заранее, поэтому он лежит вне зоны записи Зевса и ролей: ~/.claude/pantheon/ (песочница
# и guard protect-config), а пишет его только эта команда, которую guard не даёт ни одной роли, даже штабу. Вы набираете
# её сами: в своём терминале или в окне Зевса после «!». Деньги, новые публикации, сообщения людям и удаление сюда не
# вносятся — всегда отдельное «да».
APPROVALS = os.path.join(HOME, ".claude", "pantheon", "approvals.toml")
APPROVALS_HEAD = """# Заранее разрешённые действия мастерской на сайтах (DONE-11 карты решений).
# Пишет только команда владельца `pantheon approve` (роли и Пританей её запустить не могут — guard). Мастерская читает этот
# файл перед действием на сайте; деньги, новые публикации, сообщения людям, удаление и всё, чего тут нет, — отдельное «да».
"""


def owner_approved(name, days=14):
    """Ваше «да» новому направлению: в журнале доски owner-log/board.jsonl (его пишет тик по вашей галочке, роли туда
    не пишут) ответ «Да…» на вопрос «Завести направление <имя>?»; ответу не больше days дней. Текст вопроса тик берёт
    из отмеченной вами карточки (её рисует тик) — правка файла задачи до или после ответа ничего не меняет."""
    since = now() - days * 86400
    # вопрос — ровно «Завести направление <имя>?» в начале, без скрытого Obsidian текста (%%…%%, <!-- -->, теги):
    # имя должно быть там, где вы его видите; ответ — «Да» отдельным словом («Давай позже» — не согласие)
    ask = re.compile(rf"Завести направление [`«\"]?{re.escape(name)}[`»\"]?(?![\w-])")
    yes = re.compile(r"да(?![а-яёa-z0-9])", re.I)
    try:
        lines = open(path("owner-log", "board.jsonl"), encoding="utf-8").read().splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            rec = json.loads(line)
            ts = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, AttributeError):
            continue
        q = rec.get("question")
        if (rec.get("kind") == "answer" and ts >= since and isinstance(q, str) and ask.match(q.strip())
                and not re.search(r"%%|<", q) and yes.match(str(rec.get("answer") or "").strip())):
            return True
    return False


# Пределы инструкций (исследование 15.10, ~/ai/knowledge/inbox/research-2026-10-15-agents-md.md; docs Claude Code memory).
CLAUDE_LINES = 200          # CLAUDE.md длиннее хуже соблюдается (рекомендация документации, файл грузится целиком)
MEMORY_LINES, MEMORY_BYTES = 200, 25 * 1024   # MEMORY.md автопамяти: дальше при старте не грузится
CODEX_DEFAULT = 32 * 1024   # Codex project_doc_max_bytes: сверх — молча обрезает
SKIP_DIRS = {"node_modules", "vendor", "dist", "build", "target", "__pycache__", "venv", ".venv", "coverage"}


def codex_setup():
    """→ (Codex на этом Mac, лимит байт, байт глобального AGENTS.md). Глобальный файл считаем в тот же бюджет:
    документация Codex говорит о «combined size» без уточнения — берём худший случай."""
    home = os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")
    here = os.path.isdir(home) or bool(shutil.which("codex"))
    limit = CODEX_DEFAULT
    try:
        with open(os.path.join(home, "config.toml"), "rb") as fh:
            limit = int(tomllib.load(fh).get("project_doc_max_bytes") or CODEX_DEFAULT)
    except (OSError, ValueError, TypeError):
        pass
    glob_size = 0
    for n in ("AGENTS.override.md", "AGENTS.md"):
        f = os.path.join(home, n)
        if os.path.isfile(f):
            glob_size = os.path.getsize(f)
            break
    return here, limit, glob_size


def _lines(f):
    try:
        with open(f, "rb") as fh:
            return fh.read(4 << 20).count(b"\n")
    except OSError:
        return 0


def _claude_lines(f, depth=0, seen=None):
    """Строки CLAUDE.md вместе с импортами @файл (как грузит Claude Code: до четырёх переходов)."""
    seen = seen if seen is not None else set()
    rf = os.path.realpath(f)
    if rf in seen or depth > 4 or not os.path.isfile(rf):
        return 0
    seen.add(rf)
    n = _lines(rf)
    try:
        text = open(rf, encoding="utf-8", errors="replace").read(1 << 20)
    except OSError:
        return n
    for m in re.finditer(r"(?m)^\s*@(\S+\.md)\s*$", text):
        target = os.path.expanduser(m.group(1))
        n += _claude_lines(target if os.path.isabs(target) else os.path.join(os.path.dirname(rf), target), depth + 1, seen)
    return n


def instruction_files(root, max_depth=5, max_dirs=5000):
    """Папки с инструкциями внутри root → [(папка, байт цепочки Codex от корня git, строк CLAUDE.md с импортами)].
    Codex склеивает AGENTS.override.md (или AGENTS.md) каждой папки от корня git до текущей."""
    out, count = [], 0
    stack = [(os.path.realpath(root), 0, 0)]
    while stack and count < max_dirs:
        d, depth, chain = stack.pop()
        count += 1
        if os.path.isdir(os.path.join(d, ".git")):
            chain = 0
        agents = next((os.path.join(d, n) for n in ("AGENTS.override.md", "AGENTS.md")
                       if os.path.isfile(os.path.join(d, n))), None)
        if agents:
            chain += os.path.getsize(agents)
        claude_md = os.path.join(d, "CLAUDE.md")
        cl = _claude_lines(claude_md) if os.path.isfile(claude_md) else (_lines(agents) if agents else 0)
        if agents or os.path.isfile(claude_md):
            out.append((d, chain, cl))
        if depth >= max_depth:
            continue
        try:
            subs = [e for e in os.scandir(d) if e.is_dir(follow_symlinks=False)
                    and not e.name.startswith(".") and e.name not in SKIP_DIRS]
        except OSError:
            subs = []
        stack.extend((e.path, depth + 1, chain) for e in subs)
    return out


def memory_files():
    """MEMORY.md автопамяти проектов и памяти ролей → [(файл, строк, байт)]."""
    res = []
    for base, pattern in ((os.path.join(HOME, ".claude", "projects"), ("memory", "MEMORY.md")),
                          (os.path.join(HOME, ".claude", "agent-memory"), ("MEMORY.md",))):
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for n in names:
            f = os.path.join(base, n, *pattern)
            if os.path.isfile(f):
                res.append((f, _lines(f), os.path.getsize(f)))
    return res


def instructions_check(quiet=False):
    """pantheon instructions: дойдут ли инструкции до агента целиком (Claude и Codex). Тик — раз в сутки.
    Срез (Codex сверх лимита, MEMORY.md сверх 200 строк или 25 КБ) — тревога на каждый файл; длинные CLAUDE.md —
    одна тревога на набор."""
    try:
        with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
            reg = tomllib.load(fh).get("direction") or []
    except (OSError, ValueError):
        reg = []
    roots = []
    for d in reg:
        for f in d.get("folders") or []:
            r = os.path.realpath(os.path.expanduser(f))
            if os.path.isdir(r) and not any(r == x or r.startswith(x.rstrip("/") + "/") for x in roots):
                roots = [x for x in roots if not x.startswith(r.rstrip("/") + "/")] + [r]
    here, limit, glob_size = codex_setup()
    short = lambda p: p.replace(HOME, "~")
    cut, long_ = [], []
    for root in sorted(roots):
        for d, chain, lines in instruction_files(root):
            total = chain + glob_size
            if chain and total > limit:
                msg = (f"Codex: инструкции до {short(d)} — {total // 1024} КиБ при лимите {limit // 1024} КиБ: "
                       "сверх Codex молча обрезает. Общее — в корневой AGENTS.md, подробности — во вложенные AGENTS.md "
                       "папок, процедуры — в навыки")
                cut.append(("codex-" + d, total, msg, here))
            if lines > CLAUDE_LINES:
                long_.append(f"{short(d)} — {lines} строк")
    for f, n, b in memory_files():
        if n > MEMORY_LINES or b > MEMORY_BYTES:
            cut.append(("memory-" + f, f"{n}/{b}", f"Claude: {short(f)} — {n} строк, {b // 1024} КБ: дальше "
                        f"{MEMORY_LINES} строк или {MEMORY_BYTES // 1024} КБ при старте не грузится. Сжать: строка на "
                        "запись, подробности — в файлы тем", True))
    if not quiet:
        print(f"Codex на этом Mac: {'да' if here else 'нет'}; лимит {limit // 1024} КиБ"
              + (f", глобальный AGENTS.md {glob_size // 1024} КиБ" if glob_size else ""))
        for _, _, msg, alerting in cut:
            print(("СРЕЗ    " if alerting else "Codex*  ") + msg)
        for x in long_:
            print(f"ДЛИННО  Claude: {x} (с импортами; больше {CLAUDE_LINES} — хуже соблюдается)")
        if not cut and not long_:
            print("всё доходит целиком")
        if any(not a for *_, a in cut):
            print("* Codex на этом Mac нет — без тревоги; у того, кто работает в Codex, тревога будет")
        return 1 if any(a for *_, a in cut) else 0
    for key, value, msg, alerting in cut:
        if alerting:
            alert_once("instr-" + key, value, msg, "instructions")
    if long_:
        alert_once("instr-long", ",".join(sorted(long_)), f"Claude: инструкции длиннее {CLAUDE_LINES} строк (хуже "
                   f"соблюдаются): {'; '.join(long_)} — разнести по .claude/rules или вложенным файлам", "instructions")
    else:
        clear_once("instr-long")
    return 0


DIRECTION_NAME = re.compile(r"[a-z]+-[a-z0-9]+(?:-[a-z0-9]+)*")


def direction_gate(name):
    """Ворота нового направления — общие у `direction check` и `direction init`: имя по образцу, ваше «да» в
    decisions.md, ваша галочка в журнале доски, запись в directions.toml. → ([(готово, что)], запись реестра)."""
    res = []
    add = lambda ok, text: res.append((bool(ok), text))
    add(DIRECTION_NAME.fullmatch(name) and len(name) <= 40 and not reserved_direction(name),
        reserved_direction(name) or f"имя «{name}» по образцу <бог>-<проект>: латиница, цифры, дефис, до 40 знаков")
    try:
        dec = open(os.path.join(PANTHEON, "decisions.md"), encoding="utf-8").read()
    except OSError:
        dec = ""
    said = [l for l in dec.splitlines() if l.startswith("|") and re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", l)
            and "Ваши слова" in l]
    add(said, "ваше «да» в decisions.md: строка с именем направления и «Ваши слова»")
    # decisions.md пишет Зевс — сама строка не доказательство; текст реплики тоже (простое «да» подошло бы к любому
    # вопросу). Доказательство — ваша галочка на карточке «Завести направление <имя>?» в журнале доски.
    add(owner_approved(name), "ваша галочка «Да…» на карточке с этим именем в журнале доски (не старше 14 дней)")
    try:
        with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
            reg = {d.get("name"): d for d in tomllib.load(fh).get("direction") or []}
    except (OSError, ValueError):
        reg = {}
    d = reg.get(name) or {}
    add(d, "запись в directions.toml")
    return res, d


def direction_check(name):
    """Навык new-direction (ROLE-05, STATE-11): всё ли готово у направления. → [(готово, что)]."""
    res, d = direction_gate(name)
    add = lambda ok, text: res.append((bool(ok), text))
    god = name.split("-", 1)[0]
    add(d.get("does") and d.get("does_not") and 3 <= len(d.get("examples") or []) <= 6,
        "в записи есть does, does_not и 3–5 examples (ROLE-11)")
    folders = [os.path.realpath(os.path.expanduser(f)) for f in d.get("folders") or []]
    add(folders and all(os.path.isdir(f) for f in folders), "папки направления есть на этом Mac")
    launch = launch_folder(d.get("folders"))
    home_dir = os.path.join(PANTHEON, "directions", name)
    add(all(os.path.exists(os.path.join(home_dir, x)) for x in ("STATUS.md", "inbox", "tasks")),
        f"~/ai/pantheon/directions/{name}/: STATUS.md, inbox/, tasks/ (STATE-07)")
    dom = (read_json(path("domains.json"), {}).get("domains") or {}).get(name)
    add(dom, "направление в domains.json (pantheon domains build) — guard его знает")
    add(os.path.isfile(path("settings", name + ".json")), "окно роли settings/" + name + ".json")
    bad_allow = project_allow_problems(launch) if launch else []
    add(not bad_allow, "проектные allow папки запуска не пускают gh pr merge (иначе окно не соберётся, metis-0137)"
        + (": " + "; ".join(f"{os.path.basename(f)} «{r}»" for f, r in bad_allow) if bad_allow else ""))
    agents = os.path.join(launch, "AGENTS.md")
    claude_md = os.path.join(launch, "CLAUDE.md")
    cm = open(claude_md, encoding="utf-8").read(200) if os.path.isfile(claude_md) else None
    add(os.path.isfile(agents) and (cm is None or cm.lstrip().startswith("@AGENTS.md")),
        "AGENTS.md в папке запуска; CLAUDE.md нет или начинается с @AGENTS.md (STATE-12)")
    if os.path.isdir(launch):
        here, limit, glob_size = codex_setup()
        found = instruction_files(launch)
        worst = max((c + glob_size for _, c, _ in found), default=0)
        add(not here or worst <= limit, f"Codex: инструкции до {limit // 1024} КиБ на путь (сейчас {worst // 1024} КиБ"
            + ("" if here else "; Codex на этом Mac нет — не блокирует") + "): сверх Codex молча обрезает")
        longest = max((n for _, _, n in found), default=0)
        add(longest <= CLAUDE_LINES, f"Claude: CLAUDE.md с импортами до {CLAUDE_LINES} строк (сейчас {longest})")
    try:
        cj = json.load(open(os.path.join(HOME, ".claude.json"), encoding="utf-8"))
    except (OSError, ValueError):
        cj = {}
    add(((cj.get("projects") or {}).get(launch) or {}).get("hasTrustDialogAccepted"),
        f"доверие к {launch.replace(HOME, '~')} — владелец, одна интерактивная сессия (без него claude --bg не стартует)")
    remote = ""
    if os.path.isdir(os.path.join(launch, ".git")):
        r = subprocess.run(["git", "-C", launch, "remote", "get-url", "origin"], capture_output=True, text=True)
        remote = r.stdout.strip() if r.returncode == 0 else ""
    owner = re.search(r"[:/]([\w.-]+)/[\w.-]+?(?:\.git)?$", remote)
    try:
        env = "\n".join(json.load(open(os.path.join(HOME, ".claude", "settings.json"), encoding="utf-8"))
                        .get("autoMode", {}).get("environment") or [])
    except (OSError, ValueError):
        env = ""
    add(not remote or (owner and (owner.group(1) + "/") in env),
        "владелец remote в autoMode.environment (" + (remote or "remote нет") + ")")
    # действующая часть имён — как в roles_build: личная перекрывает общую из плагина целиком
    mine = os.path.join(PARTS, "names.part")
    names_path = mine if os.path.isfile(mine) else os.path.join(PLUGIN_PARTS, "names.part")
    try:
        names = open(names_path, encoding="utf-8").read()
    except OSError:
        names = ""
    add(f"({name})" in names, f"бог направления ({god}) и его род — в _parts/names.part"
        + ("" if names_path == mine else " (личной нет: скопировать общую из плагина в ~/.claude/agents/_parts/ и дописать)"))
    for lead in d.get("leads") or []:
        short = name.split("-", 1)[-1]
        add(os.path.isfile(os.path.join(AGENTS, f"{lead}-{short}.md")), f"роль лида {lead}-{short} (pantheon roles build)")
    return res


# `pantheon direction init` (metis-0042): папку нового направления создаёт команда, а не Метида — её окну guard и
# песочница не дают писать в ~/projects/<новое>. Ворота — те же, что у check (ваша галочка в журнале доски). Создаёт
# только ровно ~/projects/<x>; существующие папки не трогает, ссылки и «..» — отказ; сначала проверяет все папки
# записи, потом создаёт. Повтор доделывает прерванный запуск и ничего не меняет у готового.
INIT_OWN = {".git", "AGENTS.md"}   # что оставляет init: папка только с этим — начатая им, её можно доделать
INIT_COMMIT = "AGENTS.md (pantheon direction init)"


def _git_env():
    """Окружение git без переменных, которые увели бы его в чужой репозиторий (вызов из хука git)."""
    return {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}


def _init_own(p):
    """Папка пуста или в ней только то, что оставляет init: .git — папка, AGENTS.md — обычный файл, без ссылок; у
    репозитория нет remote и нет коммитов, кроме одного своего (INIT_COMMIT). Пустой клон с remote или чужой коммит —
    чужое, не трогаем. git — с явным --git-dir: сломанный .git не уведёт его в репозиторий выше."""
    try:
        names = os.listdir(p)
    except OSError:
        return False
    if not set(names) <= INIT_OWN:
        return False
    git, agents = os.path.join(p, ".git"), os.path.join(p, "AGENTS.md")
    if os.path.lexists(agents) and (os.path.islink(agents) or not os.path.isfile(agents)):
        return False
    if not os.path.lexists(git):
        return True
    if os.path.islink(git) or not os.path.isdir(git):
        return False
    env = _git_env()
    run = lambda *a: subprocess.run(["git", "--git-dir=" + git, *a], capture_output=True, text=True, env=env)
    r = run("config", "--local", "--get-regexp", r"^remote\.")
    if r.returncode != 1 or r.stdout.strip():   # 1 — ничего не найдено; 0 — есть remote; другое — не репозиторий
        return False
    if run("rev-parse", "--verify", "-q", "HEAD").returncode:
        return True
    return (run("rev-list", "--count", "HEAD").stdout.strip() == "1"
            and run("log", "-1", "--format=%s", "HEAD").stdout.strip() == INIT_COMMIT)


def direction_init(name):
    """pantheon direction init <имя>: папка нового направления по вашей галочке. → код выхода."""
    res, d = direction_gate(name)
    if not all(ok for ok, _ in res):
        for ok, text in res:
            print(("готово  " if ok else "НЕТ     ") + text)
        print("ничего не создано: ворота не пройдены")
        return 1
    folders = d.get("folders") or []
    if not isinstance(folders, list) or not folders:
        print(f"в записи {name} в directions.toml нет folders — нечего создавать")
        return 1
    projects = os.path.join(HOME, "projects")
    short = lambda p: "~" + p[len(HOME):] if p == HOME or p.startswith(HOME + "/") else p

    def new_ok(p):
        """Создавать можно только ровно ~/projects/<x>: один компонент, не скрытый, ~/projects — не ссылка в сторону
        (сравнение с настоящим путём HOME: сам HOME может быть ссылкой, как /var → /private/var)."""
        base = os.path.basename(p)
        return (os.path.dirname(p) == projects and base and not base.startswith(".")
                and os.path.realpath(projects) == os.path.join(os.path.realpath(HOME), "projects"))

    plan, bad = [], []   # plan: (путь, create | resume | skip | busy)
    for f in folders:
        if not isinstance(f, str) or not f.strip():
            bad.append(f"{f!r}: пустая строка вместо папки — не создаю")
            continue
        if ".." in f.split("/"):
            bad.append(f"{f}: «..» в пути — не создаю")
            continue
        p = os.path.normpath(os.path.expanduser(f))
        if not os.path.isabs(p):
            bad.append(f"{f}: не абсолютный путь и не от ~/ — не создаю")
        elif os.path.islink(p):
            bad.append(f"{short(p)}: ссылка — не создаю и не трогаю")
        elif os.path.isdir(p):
            if not new_ok(p):
                plan.append((p, "skip"))
            elif _init_own(p):
                plan.append((p, "resume"))
            else:
                plan.append((p, "busy"))
        elif os.path.lexists(p):
            bad.append(f"{short(p)}: есть, но не папка — не трогаю")
        elif new_ok(p):
            plan.append((p, "create"))
        else:
            bad.append(f"{short(p)}: вне ~/projects — не создаю (новая папка — только ~/projects/<имя>)")
    if bad:
        for x in bad:
            print("отказ   " + x)
        print("ничего не создано: сначала поправить folders в directions.toml")
        return 1

    # папка запуска — по правилу start (launch_folder): первая существующая папка записи; после init есть все, значит
    # это первая папка записи. git init, AGENTS.md и коммит — только если её создаёт или доделывает init
    launch = plan[0][0]
    note = " — папка запуска: AGENTS.md в ней дописывает координатор направления"
    rc = 0
    for p, kind in plan:
        if kind == "skip":
            print(f"есть, пропущено {short(p)}" + (note if p == launch else ""))
            continue
        if kind == "busy":
            print(f"есть, не пуста — не трогаю {short(p)}" + (note if p == launch else ""))
            continue
        if kind == "create":
            try:
                os.makedirs(projects, exist_ok=True)
                os.mkdir(p)
            except OSError as e:
                print(f"отказ   {short(p)}: не создана ({e.strerror or e})")
                return 1
        if p != launch:
            print(f"создано {short(p)}" if kind == "create" else f"есть, пропущено {short(p)}")
            continue
        done, err = _init_launch(p, name, d)
        if kind == "create":
            print(f"создано {short(p)}" + (": " + ", ".join(done) if done else ""))
        elif done:
            print(f"доделано {short(p)}: " + ", ".join(done))
        elif not err:
            print(f"есть, пропущено {short(p)}")
        if err:
            print(f"сбой    {short(p)}: {err}")
            rc = 1
    return rc


def _init_launch(p, name, d):
    """Папка запуска: git init, стартовый AGENTS.md, первый коммит — только недостающее. → ([что сделано], ошибка)."""
    env = _git_env()
    git = lambda *a: subprocess.run(["git", "-C", p, *a], capture_output=True, text=True, env=env)
    done = []
    if not os.path.lexists(os.path.join(p, ".git")):
        r = git("init", "-q", "-b", "main")
        if r.returncode:
            return done, "git init: " + (r.stderr.strip() or f"код {r.returncode}")
        done.append("git init")
    agents = os.path.join(p, "AGENTS.md")
    if not os.path.lexists(agents):
        text = (f"# {d.get('project') or os.path.basename(p)}\n\n"
                f"Направление Пантеона `{name}`.\n\n"
                f"Что делает: {d.get('does') or '—'}\n\n"
                f"Чего не делает: {d.get('does_not') or '—'}\n\n"
                "Команды сборки и тестов — дополнит координатор.\n")
        try:
            with open(agents, "x", encoding="utf-8") as fh:   # "x": не перезапишет и не пройдёт по ссылке
                fh.write(text)
        except OSError as e:
            return done, f"AGENTS.md: {e.strerror or e}"
        done.append("AGENTS.md")
    if git("rev-parse", "--verify", "-q", "HEAD").returncode:
        r = git("add", "AGENTS.md")
        if r.returncode == 0:
            r = git("commit", "-q", "-m", INIT_COMMIT)
        if r.returncode:
            return done, "git commit: " + ((r.stderr or r.stdout).strip() or f"код {r.returncode}") + \
                " — повтор `pantheon direction init` доделает"
        done.append("коммит")
    return done, ""


def direction(rest):
    """pantheon direction check <имя> — что готово у нового направления (навык new-direction).
    pantheon direction init <имя>  — папка ~/projects/<имя> по вашей галочке: git init, AGENTS.md, локальный коммит;
                                     без remote."""
    if len(rest) != 2 or rest[0] not in ("check", "init"):
        print(direction.__doc__, file=sys.stderr)
        return 2
    if rest[0] == "init":
        return direction_init(rest[1])
    res = direction_check(rest[1])
    for ok, text in res:
        print(("готово  " if ok else "НЕТ     ") + text)
    return 0 if all(ok for ok, _ in res) else 1


# --- согласие через Зевса (metis-0022, решение 15.10) ---------------------------------
# Вопрос владельцу задаёт Зевс (окном вопросов или карточкой «Нужен ответ» на доске). Ответ пишут не роли: хук — в
# owner-log/zeus.md (ввод владельца, выбор в окне вопросов), тик — в owner-log/board.jsonl (галочка на карточке; текст
# вопроса тик берёт из отмеченной карточки). Журналы личные — роли их не читают; эта команда отдаёт исполнителю только
# записи с номером его вопроса.
CONSENT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
CONSENT_MAX = 1500


def consent(rest):
    if not rest or not CONSENT_ID.fullmatch(rest[0]):
        print("pantheon consent <id> [--days N] — id задачи вида metis-0032 или tbankrot-8057746", file=sys.stderr)
        return 2
    qid, days = rest[0], 7.0
    if "--days" in rest:
        try:
            days = min(30.0, max(0.1, float(rest[rest.index("--days") + 1])))
        except (IndexError, ValueError):
            print("pantheon consent: --days — число дней", file=sys.stderr)
            return 2
    try:
        with open(path("owner-log", "zeus.md"), encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = ""
    except (OSError, UnicodeDecodeError) as e:
        print(f"pantheon consent: журнал не читается ({e}) — ответ проверить нельзя", file=sys.stderr)
        return 3
    word = re.compile(r"(?<![\w-])" + re.escape(qid) + r"(?![\w-])", re.I)
    # ответ — только выбор в окне вопросов (пометку «окно вопросов» ставит хук answer, ввод владельца её не получает)
    # на вопрос, который начинается с [<id>]; id в свободном тексте, цитате или заметке к чужому вопросу — не ответ
    own = re.compile(r"вопрос: \[" + re.escape(qid) + r"\]", re.I)
    since, found, mentions = now() - days * 86400, [], 0
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    for i, m in enumerate(heads):
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        try:
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue
        if t < since:
            continue
        if m.group(2).strip() == "· окно вопросов" and own.match(body):
            found.append((t, m.group(1) + " · окно вопросов у Зевса", body))
        elif word.search(body):
            mentions += 1
    try:
        with open(path("owner-log", "board.jsonl"), encoding="utf-8") as fh:
            board_lines = fh.read().splitlines()
    except FileNotFoundError:
        board_lines = []
    except (OSError, UnicodeDecodeError) as e:
        print(f"pantheon consent: журнал доски не читается ({e}) — ответ проверить нельзя", file=sys.stderr)
        return 3
    for line in board_lines:
        try:
            rec = json.loads(line)
            t = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, AttributeError):
            continue
        q, a = rec.get("question"), rec.get("answer")
        # скрытый текст Obsidian (%%…%%, <!-- -->) в вопросе — вы его не видели, такой ответ не согласие (как owner_approved)
        if rec.get("kind") != "answer" or rec.get("id") != qid or t < since or not isinstance(q, str) \
                or not isinstance(a, str) or re.search(r"%%|<", q):
            continue
        found.append((t, rec["time"][:19].replace("T", " ") + " · доска, галочка на карточке (деньги, публикации, "
                      "сообщения людям, удаление — не по галочке, только окном вопросов)",
                      f"вопрос: {q.strip()}\nответ: {a.strip()}"))
    found.sort(key=lambda x: x[0])
    found = [(head, body if len(body) <= CONSENT_MAX else body[:CONSENT_MAX] + "…") for _, head, body in found]
    hint = (f"\nУпоминаний {qid} в словах владельца без окна вопросов: {mentions} — это не ответ; попроси Зевса "
            f"переспросить окном вопросов «[{qid}] …»." if mentions else "")
    if not found:
        print(f"ответа владельца на {qid} в окне вопросов Зевса и на доске за {days:g} дн. нет{hint}")
        return 1
    print(f"Ответы владельца на {qid} (журналы пишут хук и плановый проход, не роли; сверь, что ответ — на твой вопрос и твоё действие):")
    for t, body in found:
        print(f"\n## {t}\n{body}")
    if hint:
        print(hint)
    return 0


def approvals_load():
    try:
        with open(APPROVALS, "rb") as fh:
            return tomllib.load(fh).get("approval") or []
    except (OSError, ValueError):
        return []


def toml_str(s):
    return json.dumps(str(s), ensure_ascii=False)


def approve(rest):
    """pantheon approve [list] | add --site S --allow "что можно" [--limits "граница"] | remove N"""
    items = approvals_load()
    if not rest or rest[0] == "list":
        if not items:
            print("заранее разрешённых действий нет")
        for i, a in enumerate(items, 1):
            print(f"{i}. {a.get('site')}: {a.get('allow')}" + (f" (граница: {a['limits']})" if a.get("limits") else "")
                  + f" — с {a.get('added', '?')}")
        return 0
    if rest[0] == "add":
        def opt(k):
            return rest[rest.index(k) + 1] if k in rest and rest.index(k) + 1 < len(rest) else None
        site, allow, limits = opt("--site"), opt("--allow"), opt("--limits")
        if not site or not allow:
            print(approve.__doc__, file=sys.stderr)
            return 2
        if re.search(r"оплат|плат[её]ж|перевод денег|удал|публикац|сообщени|письм", allow, re.I):
            print("деньги, удаление, публикации и сообщения людям заранее не разрешаются — только отдельное «да»",
                  file=sys.stderr)
            return 2
        items.append({"site": site, "allow": allow, "limits": limits or "", "added": stamp(), "host": host()})
    elif rest[0] == "remove" and len(rest) > 1 and rest[1].isdigit() and 1 <= int(rest[1]) <= len(items):
        items.pop(int(rest[1]) - 1)
    else:
        print(approve.__doc__, file=sys.stderr)
        return 2
    body = APPROVALS_HEAD + "".join(
        f"\n[[approval]]\nsite = {toml_str(a.get('site'))}\nallow = {toml_str(a.get('allow'))}\n"
        f"limits = {toml_str(a.get('limits', ''))}\nadded = {toml_str(a.get('added', ''))}\nhost = {toml_str(a.get('host', ''))}\n"
        for a in items)
    os.makedirs(os.path.dirname(APPROVALS), exist_ok=True)
    write_atomic(APPROVALS, body)
    start_log(f"approve\t{rest[0]}\t{len(items)}")
    return approve(["list"])


# --- установка ----------------------------------------------------------------------

PLIST_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>{tick}</string></array>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>AbandonProcessGroup</key><true/>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>{path}</string></dict>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


def install():
    """Задача launchd, команда pantheon и обработчики слияния ~/ai/pantheon — через неизменную ссылку CURRENT."""
    os.makedirs(path("logs"), exist_ok=True)
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    os.makedirs(os.path.dirname(CURRENT), exist_ok=True)
    if os.path.islink(CURRENT) or os.path.exists(CURRENT):
        os.remove(CURRENT)
    os.symlink(PLUGIN, CURRENT)
    tick_bin = os.path.join(CURRENT, "bin", "pantheon-tick")
    env_path = ":".join([os.path.dirname(sys.executable), "/opt/homebrew/bin",
                         os.path.join(HOME, ".local", "bin"), "/usr/bin:/bin:/usr/sbin:/sbin"])
    with open(PLIST, "w") as fh:
        fh.write(PLIST_TMPL.format(label=LABEL, tick=tick_bin, path=env_path, log=path("logs", "tick.log")))
    for cmd in ("pantheon", "heavy"):  # heavy — обёртка тяжёлых команд для ролей (MEM-03)
        link = os.path.join(HOME, ".local", "bin", cmd)
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(os.path.join(CURRENT, "bin", cmd), link)
    link = os.path.join(HOME, ".local", "bin", "pantheon")
    os.makedirs(path("locks"), exist_ok=True)
    for slot in ("heavy-cmd-1", "heavy-cmd-2", "heavy-server"):
        open(path("locks", slot + ".lock"), "a").close()
    if os.path.isdir(os.path.join(PANTHEON, ".git")):
        merge = os.path.join(CURRENT, "scripts", "git-crypt-merge.sh")
        git("config", "merge.gitcrypt-text.name", "git-crypt text merge")
        git("config", "merge.gitcrypt-text.driver", f"{merge} %O %A %B")
        git("config", "merge.gitcrypt-union.name", "git-crypt union merge (дописываемые файлы)")
        git("config", "merge.gitcrypt-union.driver", f"{merge} --union %O %A %B")
    uid = os.getuid()
    drop_old(OLD_TICK_GLOB)  # тик под прежней меткой — снять, пока не встал новый
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        with open(path("dryrun.log"), "a") as fh:
            fh.write(f"{int(now())} install-bootstrap {LABEL}\n")
        print(f"установлено (dryrun): {PLIST.replace(HOME, '~')}")
        return 0
    build_app()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", PLIST], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr.strip(), file=sys.stderr)
        return r.returncode
    print(f"установлено: {PLIST.replace(HOME, '~')} и команда {link.replace(HOME, '~')} → "
          f"{CURRENT.replace(HOME, '~')} → {PLUGIN.replace(HOME, '~')}")
    return 0


def build_app():
    """~/Applications/Доска.app: Spotlight «Доска» и значок в Dock открывают доску в Obsidian."""
    import tempfile
    with open(os.path.join(LIB, "board-app.applescript"), encoding="utf-8") as fh:
        src = fh.read().replace("BOARD_URL", board_url())
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, "app.applescript")
        with open(sp, "w", encoding="utf-8") as fh:
            fh.write(src)
        os.makedirs(os.path.dirname(APP), exist_ok=True)
        r = subprocess.run(["osacompile", "-o", APP, sp], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"программа «Доска» не собрана: {r.stderr.strip()}", file=sys.stderr)
        return
    plist = os.path.join(APP, "Contents", "Info.plist")
    subprocess.run(["plutil", "-replace", "CFBundleIdentifier", "-string", "pantheon.board", plist],
                   capture_output=True)
    if not _notifier():
        print("для уведомлений с переходом в карточку: brew install terminal-notifier", file=sys.stderr)
    subprocess.run(["codesign", "--force", "--sign", "-", APP], capture_output=True)


def uninstall():
    dry = os.environ.get("PANTHEON_DRYRUN") == "1"
    if dry:
        with open(path("dryrun.log"), "a") as fh:
            fh.write(f"{int(now())} uninstall-bootout {LABEL}\n")
    else:
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    drop_old(OLD_TICK_GLOB)
    drop_old(OLD_SVC_GLOB)
    agents = os.path.dirname(PLIST)
    with contextlib.suppress(OSError):
        for f in os.listdir(agents):
            if f.startswith(SVC_PREFIX) and f.endswith(".plist"):
                if not dry:
                    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{f[:-6]}"], capture_output=True)
                os.remove(os.path.join(agents, f))
    for p in (PLIST, os.path.join(HOME, ".local", "bin", "pantheon"), os.path.join(HOME, ".local", "bin", "heavy")):
        with contextlib.suppress(FileNotFoundError):
            os.remove(p)
    print("снято: задачи launchd (плановый проход и службы) и команды pantheon и heavy (метки в ~/.local/state/pantheon остались)")
    return 0


_TASKS = None
_NOTIFY = None


def notify_mod():
    """lib/notify.py — политика уведомлений (загрузка как у tasks_mod: python3 -I не кладёт папку скрипта в путь)."""
    global _NOTIFY
    if _NOTIFY is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_notify", os.path.join(LIB, "notify.py"))
        _NOTIFY = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_NOTIFY)
    return _NOTIFY


_AWAKE = None


def awake_mod():
    """lib/awake.py — запрет сна Mac, возобновление после недельного лимита, возобновление ждущих сессий (ночной цикл,
    metis-0126/0127/0132)."""
    global _AWAKE
    if _AWAKE is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_awake", os.path.join(LIB, "awake.py"))
        _AWAKE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_AWAKE)
        _AWAKE.set_core(sys.modules[__name__])
    return _AWAKE


_METRICS = None


def metrics_mod():
    """lib/metrics.py — учёт по задачам: исполнитель, модель, расход, круги argus (metis-0294)."""
    global _METRICS
    if _METRICS is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_metrics", os.path.join(LIB, "metrics.py"))
        _METRICS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_METRICS)
    return _METRICS


def metrics_ctx():
    """Ctx учёта; repos — [merge_repos] из policy.toml: чей PR, названный в журнале задачи просто номером."""
    try:
        with open(os.path.join(HOME, ".claude", "pantheon", "policy.toml"), "rb") as fh:
            repos = tomllib.load(fh).get("merge_repos")
    except (OSError, ValueError, tomllib.TOMLDecodeError):  # ValueError — в том числе UnicodeDecodeError
        repos = None
    return metrics_mod().Ctx(PANTHEON, STATE, HOME, now(), BOARD, repos if isinstance(repos, dict) else None)


def metrics_on_close(T, tid):
    """Строка учёта при закрытии задачи. Не вышло (песочница роли не пускает в metrics/) — смена статуса остаётся,
    строку допишет плановый проход доски."""
    if os.environ.get("PANTHEON_METRICS") == "0":
        return
    try:
        metrics_mod().record(metrics_ctx(), T.load_tasks(PANTHEON, T.WORK_TYPES), tid)
    except Exception as e:  # noqa: BLE001 — учёт не должен ломать закрытие задачи
        print(f"предупреждение · учёт {tid} не записан ({type(e).__name__}): допишет плановый проход доски",
              file=sys.stderr)


def metrics_cmd(rest):
    M, T = metrics_mod(), tasks_mod()
    sub, args = (rest[0] if rest else ""), rest[1:]
    if sub == "run":
        return metrics_run()
    tasks = T.load_tasks(PANTHEON, T.WORK_TYPES)
    ctx = metrics_ctx()
    if sub == "sync":
        rows = M.sync(ctx, tasks)
        M.publish(ctx, tasks)
        print(f"учёт: строк дописано {len(rows)}; свод — {tilde(os.path.dirname(ctx.rows_path))}")
        return 0
    if sub == "summary":
        print(M.week_md(M.summary(M.read_rows(ctx.rows_path), ctx.t, M.post_merge_index(tasks)), ctx.t))
        return 0
    if sub == "backfill":
        opts, dry, i = {}, False, 0
        while i < len(args):
            if args[i] == "--dry-run":
                dry, i = True, i + 1
            elif args[i] in ("--from", "--to") and i + 1 < len(args) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", args[i + 1]):
                opts[args[i][2:]], i = args[i + 1], i + 2
            else:
                print(f"pantheon metrics backfill: непонятно «{args[i]}» — нужно --from ГГГГ-ММ-ДД [--to ГГГГ-ММ-ДД] "
                      "[--dry-run]", file=sys.stderr)
                return 2
        if "from" not in opts:
            print("pantheon metrics backfill: нужно --from ГГГГ-ММ-ДД", file=sys.stderr)
            return 2
        rows = M.backfill(ctx, tasks, opts["from"], opts.get("to"), dry=dry)
        for r in rows:
            print(f"{r['id']}\t{r['closed']}\t{r['executor']}\t{r['model']}\t{r['effort']}\t${r['usd']:.2f}\t"
                  f"кругов {r['argus_rounds']}\tоценка")
        print(f"задним числом: {len(rows)} строк" + (" (проба, не записано)" if dry else f" → {tilde(ctx.rows_path)}"))
        if not dry:
            M.publish(ctx, tasks)
        return 0
    print("pantheon metrics sync | summary | run | backfill --from ГГГГ-ММ-ДД [--to ГГГГ-ММ-ДД] [--dry-run]", file=sys.stderr)
    return 2


def owner_acts():
    """→ (ответы, переносы в «Нужен ответ»), оба {id: [метка времени, …]}. Ответы — из журнала доски (answer и
    request с вариантом, move не в «Нужен ответ») и окна вопросов Зевса (вопрос «[id] …»); перенос карточки в «Нужен
    ответ» вами самими — не ответ, а знак «пингов не надо». Только журналы, которые пишут хук и тик: поле answer
    файла задачи и текст других сессий ответом не считаются."""
    out, put = {}, {}
    try:
        lines = open(path("owner-log", "board.jsonl"), encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            rec = json.loads(line)
            t = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, AttributeError):
            continue
        kind, tid = rec.get("kind"), rec.get("id")
        if not isinstance(tid, str):
            continue
        if (kind in ("answer", "request") and isinstance(rec.get("answer"), str) and rec["answer"].strip()
                or kind == "move" and rec.get("dst") not in ("Нужен ответ", "Ждёт вас")):
            out.setdefault(tid, []).append(t)
        elif kind == "move":
            put.setdefault(tid, []).append(t)
    try:
        with open(path("owner-log", "zeus.md"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    # как consent: пометку «окно вопросов» ставит хук answer, ответ — на вопрос, который начинается с [<id>]
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    for i, m in enumerate(heads):
        if m.group(2).strip() != "· окно вопросов":
            continue
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        q = re.match(r"вопрос: \[([^\]\s]{1,40})\]", body, re.I)
        if not q:
            continue
        try:
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue
        out.setdefault(q.group(1).lower(), []).append(t)
    return out, put


def owner_log_fns():
    """→ (answered, owner_put). answered(id, since) — время (ISO) первого ответа владельца по id не раньше since,
    иначе None; owner_put(id, since) — вы сами перенесли карточку в «Нужен ответ» не раньше since. Журналы читаются
    один раз за проход и лениво — после того, как проход доски записал новые ходы."""
    cache = []

    def acts():
        if not cache:
            cache.append(owner_acts())
        return cache[0]

    def answered(tid, since):
        hits = sorted(x for x in acts()[0].get(tid, []) if x >= int(since))
        return notify_mod().iso(hits[0]) if hits else None

    def owner_put(tid, since):
        return any(x >= int(since) for x in acts()[1].get(tid, []))
    return answered, owner_put


def notify_policy(sched=None):
    """Политика уведомлений на этот проход; вызывать под lock("notify") и закончить save()."""
    N = notify_mod()
    if sched is None:
        try:
            sched = load_schedule()
        except (OSError, ValueError):
            sched = {}
    answered, owner_put = owner_log_fns()
    return N.Policy(path("notify.json"), path("notify-log.jsonl"), sched.get("notify") or N.settings(), now(),
                    idle=idle_sec, send=lambda text, title, target, group: notify(text, title, target, group),
                    answered=answered, owner_put=owner_put)


def notify_critical(text, title="Пантеон · критично", group="critical", policy=None):
    """Критичное (COMM-08): уведомление сразу, мимо блокировки прохода доски; учёт в бюджете и журнале — под
    lock("notify"), не взяли за 5 с — без учёта (отправка уже ушла). policy — уже взятая под блокировкой."""
    if policy is not None:
        policy.critical(text, title, group=group)
        return
    notify(text, title=title, group=group)
    deadline = time.time() + 5
    while True:
        with lock("notify", block=False) as got:
            if got:
                pol = notify_policy()
                pol.critical(text, title, send=False, group=group)
                pol.save()
                return
        if time.time() > deadline:
            return
        time.sleep(0.1)


def notify_soon(key, text, group=None, policy=None, once=False):
    """Сбой класса «скоро»: macOS только если вас нет у Mac, не ночью и в бюджете, одна на ключ события за час; иначе —
    в утреннюю сводку. key — событие (по нему повтор), group — вид в Центре уведомлений (заменяет прежнее того же
    вида). Событие, которое держится, вызывать каждый проход: дойдёт, когда вы уйдёте от Mac. policy — уже взятая под
    lock("notify") (flock в том же процессе второй раз не взять). once — событие, которое держится: одна macOS, пока
    его не снимет clear_fault."""
    if policy is not None:
        policy.fault(key, text, group=group, once=once)
        return
    with lock("notify"):
        pol = notify_policy()
        pol.fault(key, text, group=group, once=once)
        pol.save()


def clear_fault(*keys):
    """Событие снято — сбросить его в политике уведомлений (следующее такое — снова macOS). Без записи, если сбрасывать
    нечего: дежурный зовёт это на каждом проходе."""
    st = read_json(path("notify.json"))
    if not any(k in (st.get("faults") or {}) for k in keys):
        return
    with lock("notify"):
        pol = notify_policy()
        if any([pol.clear_fault(k) for k in keys]):
            pol.save()


def qmd_mod():
    """lib/qmd.py — общий поиск qmd (шаг 1.5)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_qmd", os.path.join(LIB, "qmd.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.set_core(sys.modules[__name__])
    return m


def executors_mod():
    """lib/executors.py — исполнители кода (Claude, Codex) и обёртка pantheon exec codex."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_executors", os.path.join(LIB, "executors.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _task_head(tid):
    got = tasks_mod().load_tasks(PANTHEON).get(tid)
    return got[1] if got else None


_NIGHT = None


def night_mod():
    """lib/night.py — темп недельного лимита и ночной цикл (metis-0127, 0128, 0129)."""
    global _NIGHT
    if _NIGHT is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_night", os.path.join(LIB, "night.py"))
        _NIGHT = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_NIGHT)
        _NIGHT.set_core(sys.modules[__name__])
    return _NIGHT


_READ = None


def read_mod():
    """lib/read.py — чтение личного чата по заявке с согласием владельца (metis-0267)."""
    global _READ
    if _READ is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_read", os.path.join(LIB, "read.py"))
        _READ = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_READ)
        _READ.set_core(sys.modules[__name__])
    return _READ


_MMV = None


def mmv_mod():
    """lib/mmv.py — замер минут владельца (metis-0169); самостоятельный модуль, STATE передаётся при вызове."""
    global _MMV
    if _MMV is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_mmv", os.path.join(LIB, "mmv.py"))
        _MMV = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MMV)
    return _MMV


def tasks_mod():
    """lib/tasks.py — схема задач и доска владельца (python3 -I не кладёт папку скрипта в путь импорта)."""
    global _TASKS
    if _TASKS is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_tasks", os.path.join(LIB, "tasks.py"))
        _TASKS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_TASKS)
        _TASKS.set_root(PANTHEON)  # внутри ~/ai/pantheon — ввод-вывод без перехода по ссылкам
    return _TASKS


BOARD = os.path.join(VIEW, "Доска")


# --- ответ владельца по карантину ~/.claude (SEC-15) ---------------------------------------------------------
# sync.sh читает ответ с доски только при своём запуске — на старте сессии. Тик после board проверяет: есть
# держание (.sync-held или .sync-incoming), а в журнале ваших слов (owner-log/board.jsonl) по его задаче — ответ
# «отправить» или «откатить»; тогда запускает sync.sh сам. Решает по-прежнему sync.sh по тому же журналу; здесь —
# только «пора». Без ответа или «пока держать» — ничего не запускает.
SYNC_DIR = os.path.join(HOME, ".claude")
SYNC_ACT = {"Отправить на другие Mac", "Отправить", "Откатить правку", "Всё в порядке — правка наша", "Откатить на всех Mac"}


def sync_answers():
    owner_log = os.path.join(STATE, "owner-log", "board.jsonl")
    ask_log = os.path.join(STATE, "owner-log", "zeus.md")
    waiting = []
    for held in (".sync-held", ".sync-incoming"):
        try:
            text = open(os.path.join(SYNC_DIR, held), encoding="utf-8").read()
        except OSError:
            continue
        m = re.search(r"^task=(\S+)$", text, re.M)
        if m:
            waiting.append(m.group(1))
    if not waiting or not (os.path.exists(owner_log) or os.path.exists(ask_log)):
        return 0
    # как owner_answer в sync.sh (metis-0125): ответ — галочка на доске (board.jsonl) или выбор в окне вопросов Зевса
    # (zeus.md: пометка «· окно вопросов», вопрос начинается с [<id>], не старше 7 дней); из двух берётся более поздний
    found = {t: [] for t in waiting}
    lines = []
    try:
        lines = open(owner_log, encoding="utf-8").read().splitlines()
    except OSError:
        pass
    for n, line in enumerate(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("kind") == "answer" and d.get("id") in found:
            try:
                t = time.mktime(time.strptime(str(d.get("time", ""))[:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                t = 0.0
            found[d["id"]].append((t, n, d.get("answer") if isinstance(d.get("answer"), str) else ""))
    try:
        text = open(ask_log, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        text = ""
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    for i, m in enumerate(heads):
        if m.group(2).strip() != "· окно вопросов":
            continue
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        q, a = re.match(r"вопрос: \[([^\]\s]{1,40})\]", body, re.I), re.search(r"^ответ: (.*)$", body, re.M)
        if not q or not a or q.group(1) not in found:
            continue
        try:
            t = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        if t >= now() - 7 * 86400:
            found[q.group(1)].append((t, len(lines) + i, a.group(1)))
    last = {t: re.sub(r"\s*\((?:Recommended|рекомендую)\)$", "", max(v)[2].strip()) for t, v in found.items() if v}
    if not any(last.get(t) in SYNC_ACT for t in waiting):
        return 0
    script = os.path.join(SYNC_DIR, "sync.sh")
    try:
        r = subprocess.run([script], capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"sync-answers: sync.sh не отработал: {e}", file=sys.stderr)
        return 1
    print(f"sync-answers: ответ по {', '.join(waiting)} применён (sync.sh, код {r.returncode})")
    return 0


def board_registry(T):
    """directions.toml → (направление → проект, проект → значок, проекты пульта). Один разбор для тика и check:
    счётчики заметок проектов сверяются по тому же реестру, по которому их писали."""
    try:
        with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
            dirs = tomllib.load(fh).get("direction") or []
    except (OSError, ValueError):
        return {}, {}, {}
    projects = {d.get("name"): d.get("project") for d in dirs}
    marks = {}  # значок проекта — поле `mark` направления; ключ — project, иначе name
    for d in dirs:
        if isinstance(d.get("mark"), str):
            marks.setdefault(d.get("project") or d.get("name"), d["mark"])
    return projects, marks, T.project_registry(dirs)


def board():
    """Доска владельца: ходы → задачи и журнал владельца, карточки ← задачи. Только на этом Mac, под блокировкой."""
    T = tasks_mod()
    sched = load_schedule()
    primary = not sched.get("primary_host") or sched.get("primary_host") == host()
    with lock("board", block=False) as got:
        if not got:
            return 0
        projects, marks, registry = board_registry(T)
        # политика уведомлений — под своей блокировкой на весь проход: сбои из run-job ждут, а не теряются
        with lock("notify"):
            pol = notify_policy(sched)
            night_end = "08:00"
            with contextlib.suppress(Exception):
                night_end = night_mod().config()[1]["end"]
            lines = T.board_sync(PANTHEON, BOARD, path("board.json"), path("owner-log", "board.jsonl"), now(),
                                 night_end=night_end, open_prs=autoclose_mod().open_pr_tasks(path("autoclose.json")),
                                 alert=lambda k, v, text, who="board", note=None: alert_once(k, v, text, who, note,
                                                                                            policy=pol),
                                 primary=primary, projects=projects, policy=pol, marks=marks, registry=registry)
            pol.save()
        once_dir = path("once")  # отметки «уже сообщали» старше 90 дней — убрать: папка не растёт без конца
        for f in os.listdir(once_dir) if os.path.isdir(once_dir) else []:
            fp = os.path.join(once_dir, f)
            if now() - os.path.getmtime(fp) > 90 * 86400:
                os.remove(fp)
    for ln in lines:
        print(ln)
    if primary and os.environ.get("PANTHEON_METRICS") != "0":
        board_metrics(T)
    return 0


def autoclose_mod():
    """lib/autoclose.py — закрытие задач при слиянии их PR (metis-0308)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_autoclose", os.path.join(LIB, "autoclose.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def autoclose_actual(T, tid):
    """Расход по закрытой задаче из учёта (metrics/tasks.jsonl, metis-0294) → строка actual; нет замера — None."""
    if os.environ.get("PANTHEON_METRICS") == "0":
        return None
    M, A = metrics_mod(), autoclose_mod()
    ctx = metrics_ctx()
    with contextlib.suppress(Exception):  # строки закрытия допишет плановый проход доски
        M.record(ctx, T.load_tasks(PANTHEON, T.WORK_TYPES), tid)
    rows = [r for r in M.read_rows(ctx.rows_path) if r.get("id") == tid]
    return A.actual_text(rows[-1]) if rows else None


def autoclose_tick(t):
    """Слитые PR из [merge_repos] → закрытие задач; ошибки gh — одна тревога на репозиторий, пока не починится."""
    A, T = autoclose_mod(), tasks_mod()
    repos = sorted({r for v in metrics_ctx().repos.values() for r in v})
    if not repos:
        return
    log, errors = A.run(PANTHEON, path("autoclose.json"), t, repos, T, env=run_env(),
                        actual_for=lambda tid: autoclose_actual(T, tid))
    for ln in log:
        print(f"автозакрытие · {ln}")
    for repo in repos:
        key = "autoclose-" + re.sub(r"[^\w-]", "_", repo)[:50]
        bad = {k: v for k, v in errors.items() if k == repo or k.startswith(repo + "#")}
        if bad:
            alert_once(key, "|".join(sorted(bad)), "автозакрытие задач: " + "; ".join(f"{k}: {v}" for k, v in sorted(bad.items()))[:300],
                       "pantheon-tick")
        else:
            clear_once(key)


METRICS_EVERY = 30 * 60  # не чаще раза в 30 минут: учёт читает транскрипты за неделю (metis-0320)


def metrics_pass(T):
    """Один проход учёта: строки закрытий, которые роль из песочницы записать не смогла, и свод недели на Пульт.
    Первый проход после выпуска читает гигабайты транскриптов — дольше минуты, поэтому только из фонового процесса."""
    if os.environ.get("PANTHEON_METRICS_TEST_SLEEP"):  # проба в тестах: учёт, который долго работает
        time.sleep(float(os.environ["PANTHEON_METRICS_TEST_SLEEP"]))
    if os.environ.get("PANTHEON_METRICS_TEST_LOG"):
        with open(os.environ["PANTHEON_METRICS_TEST_LOG"], "a") as fh:
            fh.write(f"{os.getpid()}\n")
    M, tasks = metrics_mod(), T.load_tasks(PANTHEON, T.WORK_TYPES)
    ctx = metrics_ctx()
    M.sync(ctx, tasks)
    M.publish(ctx, tasks)


def trim_log(log_path, limit=400_000, keep=200_000):
    """Журнал дописывается; выше предела остаётся хвост в keep символов."""
    try:
        if os.path.getsize(log_path) > limit:
            with open(log_path, encoding="utf-8", errors="ignore") as fh:
                data = fh.read()[-keep:]
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write(data)
    except OSError:
        pass


def metrics_run():
    """pantheon metrics run — фоновый проход под блокировкой metrics; занята — тихо выходит."""
    with lock("metrics", block=False) as got:
        if not got:
            return 0
        try:
            metrics_pass(tasks_mod())
        except Exception as e:  # noqa: BLE001 — сбой учёта не ломает ничего, кроме самого учёта
            alert_once("metrics", type(e).__name__, f"учёт по задачам: проход упал ({type(e).__name__}: {e})",
                       "board")
    return 0


def board_metrics(T):
    """Учёт по задачам после прохода доски — отдельным процессом: проход доски (таймаут 60 с) не ждёт транскрипты
    (metis-0320). Не чаще раза в 30 минут (отметка metrics-spawn) и не при занятой блокировке metrics. stdin/stdout/
    stderr — не pipe: процесс-сирота держал бы полный pipe."""
    stamp_p = path("metrics-spawn")
    try:
        if now() - os.path.getmtime(stamp_p) < METRICS_EVERY:
            return
    except OSError:
        pass
    if locked("metrics"):
        return
    try:
        os.makedirs(os.path.dirname(stamp_p), exist_ok=True)
        with open(stamp_p, "w") as fh:
            fh.write(stamp() + "\n")
        try:
            trim_log(path("metrics-run.log"))
            log = open(path("metrics-run.log"), "a")
        except OSError:
            log = subprocess.DEVNULL
        subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "metrics", "run"], stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, start_new_session=True, close_fds=True)
    except Exception as e:  # noqa: BLE001 — сбой запуска учёта не ломает доску
        alert_once("metrics", type(e).__name__, f"учёт по задачам: не запустился ({type(e).__name__}: {e})", "board")


def statelen_mod():
    """lib/statelen.py — длина файлов состояния, общая с хуком (hooks/ctx.py state-len)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_statelen", os.path.join(LIB, "statelen.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


STATE_FILE_LIMIT = statelen_mod().STATE_FILE_LIMIT


def _check_long_state(quiet):
    """STATUS.md направлений и board.md штаба длиннее STATE_FILE_LIMIT знаков (символов, не байт): одна строка на
    файл. Без --quiet — печать; с ним (тик) — alert_once на файл, не чаще раза на новый размер."""
    sl = statelen_mod()
    for f in sl.state_files(PANTHEON):
        n = sl.length(f)
        if n is None:
            continue
        key = "state-long-" + re.sub(r"[^\w-]", "_", os.path.relpath(f, PANTHEON))[:60]
        if n <= STATE_FILE_LIMIT:
            if quiet:
                clear_once(key)
            continue
        shown = f.replace(HOME, "~", 1) if f.startswith(HOME + os.sep) else f
        text = (f"{shown}: {n} знаков при пределе {STATE_FILE_LIMIT} — после сжатия контекста хук кладёт только "
                f"первые ~9 800, хвост теряется: сократить, старое — в archive/")
        if quiet:
            alert_once(key, n, text, "check")
        else:
            print(f"предупреждение · {text}")


def check(paths=None, quiet=False):
    T = tasks_mod()
    files = paths or list(T.task_files(PANTHEON))
    bad, noheader, n = [], 0, 0
    for f in files:
        kind, errs, warns = T.check_file(f)
        n += 1
        if kind == "noheader":
            noheader += 1
        elif kind in ("broken", "error"):
            bad.append((f, errs, warns))
        elif warns and not quiet:
            print(f"предупреждение · {os.path.relpath(f, PANTHEON)}: {'; '.join(warns)}")
    for f, errs, _ in bad:
        print(f"ОШИБКА · {os.path.relpath(f, PANTHEON) if f.startswith(PANTHEON) else f}: {'; '.join(errs)}")
    if not paths and os.path.isdir(BOARD):
        text = "# Проблемы задач\n\nФайлы, которые выпали из доски: шапка не по схеме (schema.md).\n\n" + (
            "\n".join(f"- `{os.path.relpath(f, PANTHEON)}` — {'; '.join(e)}" for f, e, _ in bad) or "Нет — всё в порядке.") + "\n"
        pp = os.path.join(BOARD, "Проблемы.md")
        old = open(pp, encoding="utf-8").read() if os.path.exists(pp) else ""
        if old != text:
            with open(pp, "w", encoding="utf-8") as fh:
                fh.write(text)
    if not paths:
        _check_long_state(quiet)
        for dname, fs in sorted((read_json(path("domains.json"), {}).get("domains") or {}).items()):
            # allow со старым mtime сборка по --if-changed не видит: check снимает окно сам, иначе следующий wake поднял
            # бы сессию снова (ревью argus PR #32)
            problems = project_allow_report(dname, allow_gate(dname, fs), quiet)
            if problems and quiet:  # тик (check --quiet): окно могла убрать ручная сборка, а сессия ещё работает
                project_allow_stop(dname, problems)
    # счётчики на пульте пишет тик — вторая копия данных: расхождение с задачами — ошибка (metis-0069)
    drift = []
    if not paths and os.path.isdir(BOARD):
        drift = T.check_projects(BOARD, T.load_tasks(PANTHEON, T.WORK_TYPES), now(), board_registry(T)[2])
        for d in drift:
            print(f"ОШИБКА · Доска/{d}")
    field_errs, field_warns = [], []
    if not paths:  # поля «Итогов пачек» и ожидание PR/приёмки (metis-0308)
        night_end = "08:00"
        with contextlib.suppress(Exception):
            night_end = night_mod().config()[1]["end"]
        tasks_now = T.load_tasks(PANTHEON, T.WORK_TYPES)
        fixed = T.fix_closed(PANTHEON, now(), tasks_now)
        if fixed:
            tasks_now = T.load_tasks(PANTHEON, T.WORK_TYPES)
        field_errs, field_warns = T.board_problems(tasks_now, now(), night_end, autoclose_mod().open_pr_tasks(path("autoclose.json")))
        field_errs = [(i, f"status done без closed — проставлен из updated") for i in fixed] + field_errs
        for tid, text in field_errs:
            print(f"ОШИБКА · {tid}: {text}")
        for tid, text in field_warns:
            if not quiet:
                print(f"внимание · {tid}: {text}")
    view_drift = T.check_views(BOARD) if not paths else []  # у каждого вида Доска.base — строка «что здесь» (metis-0288)
    for d in view_drift:
        print(f"ОШИБКА · {d}")
    if not quiet or bad:
        print(f"задач: {n}, с ошибками: {len(bad)}, без шапки: {noheader}")
    if quiet:  # тик: одна тревога на набор проблем, а не сбой задачи каждые 5 минут
        if bad:
            alert_once("check-problems", ",".join(sorted(f for f, _, _ in bad)),
                       f"задачи с битой шапкой: {len(bad)} — список в Доска/Проблемы.md", "check")
        else:
            clear_once("check-problems")
        if drift:
            alert_once("check-projects", "|".join(drift), f"пульт: счётчики проекта расходятся с задачами — {drift[0]}"
                       + (f" и ещё {len(drift) - 1}" if len(drift) > 1 else ""), "check")
        else:
            clear_once("check-projects")
        if view_drift:
            alert_once("check-views", "|".join(view_drift), f"доска: {view_drift[0]}", "check")
        else:
            clear_once("check-views")
        if field_errs:
            alert_once("check-fields", "|".join(i for i, _ in field_errs),
                       f"задачи с пустыми полями «Итогов пачек» или done без closed: {', '.join(sorted({i for i, _ in field_errs}))[:200]}",
                       "check")
        else:
            clear_once("check-fields")
        return 0
    return 1 if bad or drift or view_drift or field_errs else 0


def task_cmd(rest):
    T = tasks_mod()
    if not rest:
        print("pantheon task new|set|show|ready|claim — справка: pantheon help", file=sys.stderr)
        return 2
    sub, args = rest[0], rest[1:]

    def opt(name, many=False):
        vals = [args[i + 1] for i, a in enumerate(args[:-1]) if a == name]
        return vals if many else (vals[-1] if vals else None)

    try:
        if sub == "new":
            fields = {"status": opt("--status"), "priority": int(opt("--priority")) if opt("--priority") else None,
                      "due": opt("--due"), "next": opt("--next"), "owner": opt("--owner"),
                      "release": opt("--release") or opt("--wave"), "batch": opt("--batch"),
                      "mode": opt("--mode"), "mode_why": opt("--mode-why"), "touches": opt("--touches", True) or None,
                      "night": opt("--night"), "estimate": opt("--estimate"), "actual": opt("--actual"),
                      "acceptance": opt("--acceptance"),
                      "waiting_on": opt("--waiting-on"), "question": opt("--question"), "why": opt("--why"),
                      "recommend": opt("--recommend"), "if_no_answer": opt("--if-no-answer"),
                      "options": opt("--option", True) or None, "depends_on": opt("--depends-on", True) or None,
                      "risky": True if "--risky" in args else None, "executor": opt("--executor")}
            if not opt("--direction") or not opt("--title"):
                print("pantheon task new: нужны --direction и --title", file=sys.stderr)
                return 2
            if opt("--direction") == "inbox":
                print("pantheon task new: входящие создаёт только доска владельца; Зевс заводит задачу сразу в направлении",
                      file=sys.stderr)
                return 2
            if (opt("--type") or "task") not in T.WORK_TYPES:
                print(f"pantheon task new: --type {opt('--type')} — только {' или '.join(T.WORK_TYPES)}", file=sys.stderr)
                return 2
            tid, p = T.task_new(PANTHEON, now(), opt("--direction"), opt("--title"), project=opt("--project"),
                                text=opt("--text"), kind=opt("--type") or "task", **fields)
            print(f"{tid} {os.path.relpath(p, PANTHEON)}")
            for w in T.option_warns(fields):
                print(f"предупреждение · {w}", file=sys.stderr)
        elif sub == "set" and args:
            tid, changes, note, i = args[0], {}, None, 1
            # --wave — прежнее имя --release (metis-0069): выпуск строкой «pantheon 0.11.50»
            night_flags = {"--release": "release", "--wave": "release", "--batch": "batch", "--night": "night", "--estimate": "estimate",
                           "--actual": "actual", "--acceptance": "acceptance", "--mode": "mode", "--mode-why": "mode_why"}  # ночной цикл: флаги как у --due
            while i < len(args):
                if args[i] == "--note" and i + 1 < len(args):
                    note, i = args[i + 1], i + 2
                    continue
                if args[i] == "--option" and i + 1 < len(args):  # варианты с запятыми и кавычками (metis-0037)
                    changes["options"] = (changes.get("options") or []) + [args[i + 1]]  # и после options= (argus)
                    i += 2
                    continue
                if args[i] in night_flags and i + 1 < len(args):
                    k, v, eq, step = night_flags[args[i]], args[i + 1], "=", 2
                else:
                    k, eq, v = args[i].partition("=")
                    k = T.LEGACY_KEYS.get(k, k)
                    step = 1
                if not eq:
                    print(f"pantheon task set: «{args[i]}» — нужно поле=значение", file=sys.stderr)
                    return 2
                if k in T.OWNER_ONLY_FIELDS:
                    print(f"pantheon task set: поле {k} ставит только доска владельца", file=sys.stderr)
                    return 2
                if k == "options" and v not in ("", "null"):
                    print("pantheon task set: варианты — повторяемым --option \"…\" (в тексте бывают запятые); "
                          "options= только чтобы очистить", file=sys.stderr)
                    return 2
                kind = T.FIELDS.get(k, ("str",))[0]
                changes[k] = None if v in ("", "null") else int(v) if kind == "int" else (v == "true") if kind == "bool" else \
                    [x.strip() for x in v.split(",") if x.strip()] if kind == "list" else v
                i += step
            p, head = T.task_set(PANTHEON, now(), tid, changes, note=note)
            print(f"{tid}: {head.get('status')} · {os.path.relpath(p, PANTHEON)}")
            if changes.get("status") in ("done", "dropped"):
                metrics_on_close(T, tid)
            for w in T.option_warns({"options": changes.get("options")}):
                print(f"предупреждение · {w}", file=sys.stderr)
        elif sub == "show" and args:
            tasks = T.load_tasks(PANTHEON, T.WORK_TYPES)
            if args[0] not in tasks:
                print(f"нет задачи {args[0]}", file=sys.stderr)
                return 1
            print(open(tasks[args[0]][0], encoding="utf-8").read())
            if tasks[args[0]][1].get("type") == "story":
                print("## Состав пачки\n\n" + T.story_text(args[0], tasks) + "\n")
            words = T.owner_words(path("owner-log", "board.jsonl"), args[0])
            print("## Слова владельца (журнал владельца — только это подтверждает его решение)\n")
            for w in words or [{"time": "—", "kind": "нет записей"}]:
                print(f"- {w.get('time', '')[:16].replace('T', ' ')} · {w.get('kind')} · "
                      f"{w.get('dst') or w.get('answer') or w.get('text') or w.get('title') or ''}")
        elif sub == "attach" and len(args) == 2:
            old = T.task_attach(PANTHEON, now(), args[0], args[1])
            print(f"{args[0]} → пачка {args[1]}" + (f" (была в {old})" if old else ""))
        elif sub == "migrate-batches":
            if any(a != "--dry-run" for a in args):
                print(f"pantheon task migrate-batches: не понял «{' '.join(args)}» — допустим только --dry-run", file=sys.stderr)
                return 2
            dry = "--dry-run" in args
            plan = T.migrate_batches(PANTHEON, now(), dry_run=dry)
            print("\n".join(plan) if plan else "переносить нечего")
            if dry and plan:
                print("(--dry-run: ничего не записано)")
        elif sub == "detach" and len(args) == 1:
            sid = T.task_detach(PANTHEON, now(), args[0])
            print(f"{args[0]}: откреплена от пачки {sid}")
        elif sub == "ready":
            for tid, h in T.ready(PANTHEON, now(), opt("--direction"), opt("--owner")):
                print(f"{tid}\t{T.PRIORITY.get(h.get('priority', 2), '')}\t{h.get('due') or '—'}\t{h.get('title')}")
        elif sub == "claim" and args and opt("--by"):
            p, head = T.task_claim(PANTHEON, now(), args[0], opt("--by"), float(opt("--hours") or 1))
            print(f"{args[0]}: взята {opt('--by')} до {head.get('claimed_until')}")
        else:
            print(f"pantheon task: не понял «{' '.join(rest)}»", file=sys.stderr)
            return 2
    except ValueError as e:
        print(f"pantheon task: {e}", file=sys.stderr)
        return 1
    return 0


# --- дежурный и управление сессиями (шаг 1.4) — lib/watch.py ---------------------------------------------------------
WATCH_CMDS = {"watch", "agents", "revisits", "stop", "resume", "pause", "restart", "saved", "who", "infra-check"}


def watch_cmd(cmd, rest):
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_watch", os.path.join(LIB, "watch.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    w.set_core(sys.modules[__name__])
    who = " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "владелец").split())[:40]
    if cmd == "wake":
        return w.wake_one(rest, who)
    return {"watch": lambda: w.watch(dry="--dry-run" in rest), "agents": w.agents_cmd, "revisits": w.revisits,
            "stop": lambda: w.stop(rest, who), "resume": lambda: w.resume(rest, who), "pause": lambda: w.pause(rest, who),
            "restart": lambda: w.restart(rest, who), "saved": lambda: w.saved_cmd(rest, who), "who": w.who,
            "infra-check": w.infra_cmd}[cmd]()


def usage_report(rest):
    """pantheon usage [дней] — отчёт расхода (scripts/usage.py) в ~/ai/pantheon/metrics/usage/<дата>.txt, строка в
    тревогах (SCHED-11: раз в неделю)."""
    days = rest[0] if rest and rest[0].isdigit() else "7"
    r = subprocess.run([sys.executable, "-I", os.path.join(PLUGIN, "scripts", "usage.py"), days], capture_output=True,
                       text=True, timeout=600)
    if r.returncode:
        print(r.stderr[-2000:], file=sys.stderr)
        return r.returncode
    out = os.path.join(PANTHEON, "metrics", "usage", stamp()[:10] + ".txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    write_atomic(out, r.stdout)
    total = next((ln for ln in r.stdout.splitlines() if ln.startswith("Итого")), "").strip()
    alert(f"отчёт расхода за {days} дн.: {total or 'готов'} — {out.replace(HOME, '~')}", "usage")
    print(out)
    return 0


# --- обновления плагинов agent-kit (metis-0052) ----------------------------------------------------------------
# Тик раз в 10 минут, вне песочницы: каталог agent-kit → новые версии установленных плагинов → тесты новой версии и
# установленной (база) на одних и тех же python → есть новые падения — не ставим, тревога; нет — claude plugin update.
# База нужна, чтобы падения от места запуска (временная папка, python 3.9) не держали обновление вечно.
# Хеш дерева проверенной копии сверяется с тем, что встало: update сам обновляет каталог и может поставить версию
# новее проверенной. Метка testing ловит прерванный прогон (таймаут задачи тика, сбой): такая версия — красная.

MARKETPLACE = "agent-kit"
PLUGIN_TEST_TIMEOUT = 600    # один файл тестов
PLUGIN_RUN_LIMIT = 1800      # весь прогон плагина (новая + база, все python) — меньше timeout задачи в schedule.toml
NO_TESTS = "нет тестов"
_TMP_RE = None
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-_])")


def _plugins_journal(line):
    os.makedirs(path("plugins"), exist_ok=True)
    with open(path("plugins", "journal.log"), "a", encoding="utf-8") as fh:
        fh.write(f"{stamp()} {line}\n")


def _plugins_safe(s):
    return re.sub(r"[^\w.+-]", "_", str(s))[:80] or "_"


def _version_newer(new, old):
    """Новее ли версия каталога установленной: сравнение кортежей чисел; не разобрать — новая, если строки разные."""
    try:
        return tuple(int(x) for x in str(new).split(".")) > tuple(int(x) for x in str(old).split("."))
    except ValueError:
        return str(new) != str(old)


def _plugins_installed():
    """{имя: {version, installPath}} — плагины agent-kit уровня пользователя по `claude plugin list --json`; None — сбой."""
    try:
        r = subprocess.run([claude_bin(), "plugin", "list", "--json"], capture_output=True, text=True, timeout=120)
        data = json.loads(r.stdout or "null")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if isinstance(data, dict):
        data = data.get("plugins")
    if r.returncode != 0 or not isinstance(data, list):
        return None
    out = {}
    for p in data:
        if not isinstance(p, dict) or p.get("scope") != "user":
            continue
        name, _, mkt = str(p.get("id", "")).partition("@")
        if mkt == MARKETPLACE and name:
            out[name] = {"version": str(p.get("version", "")), "installPath": p.get("installPath")}
    return out


def _plugins_catalog():
    """{имя: (версия, папка плагина)} из клона каталога agent-kit."""
    known = read_json(os.path.join(HOME, ".claude", "plugins", "known_marketplaces.json"))
    entry = known.get(MARKETPLACE) if isinstance(known, dict) else None
    loc = entry.get("installLocation") if isinstance(entry, dict) else None
    if not isinstance(loc, str) or not os.path.isdir(loc):
        loc = os.path.join(HOME, ".claude", "plugins", "marketplaces", MARKETPLACE)
    root = os.path.realpath(loc)
    mkt = read_json(os.path.join(root, ".claude-plugin", "marketplace.json"))
    out = {}
    for p in (mkt.get("plugins") or []) if isinstance(mkt, dict) else []:
        if not isinstance(p, dict) or not isinstance(p.get("source"), str) or not p.get("name"):
            continue
        d = os.path.realpath(os.path.join(root, p["source"]))
        if not d.startswith(root + os.sep):
            continue  # источник вне клона каталога (абсолютный путь, ../) — не наш
        meta = read_json(os.path.join(d, ".claude-plugin", "plugin.json"))
        ver = meta.get("version") if isinstance(meta, dict) else None
        if ver:
            out[str(p["name"])] = (str(ver), d)
    return out


def _tree_hash(root):
    """sha256 дерева плагина: относительные пути и содержимое, ссылки — по тексту ссылки. Без .git и __pycache__ на
    любой глубине и без точечных файлов и папок верхнего уровня, кроме .claude-plugin (в кэше лишний `.in_use`).
    None — папки нет."""
    if not isinstance(root, str) or not os.path.isdir(root):
        return None
    h = hashlib.sha256()

    def walk(d, rel):
        for e in sorted(os.scandir(d), key=lambda e: e.name):
            if e.name in (".git", "__pycache__") or (not rel and e.name.startswith(".") and e.name != ".claude-plugin"):
                continue
            r = f"{rel}/{e.name}" if rel else e.name
            if e.is_symlink():
                h.update(b"L\0" + r.encode() + b"\0" + os.readlink(e.path).encode() + b"\0")
            elif e.is_dir():
                walk(e.path, r)
            elif e.is_file():
                fh = hashlib.sha256()
                with open(e.path, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        fh.update(chunk)
                h.update(b"F\0" + r.encode() + b"\0" + fh.hexdigest().encode() + b"\0")

    walk(root, "")
    return h.hexdigest()


def _test_pythons():
    """python3 из PATH и системный /usr/bin/python3 — если он есть, инструменты командной строки установлены
    (иначе macOS покажет окно установки) и это не тот же python."""
    first = shutil.which("python3") or sys.executable
    out = [first]
    sysp = "/usr/bin/python3"
    if os.path.exists(sysp) and os.path.realpath(sysp) != os.path.realpath(first):
        try:
            ok = subprocess.run(["xcode-select", "-p"], capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if ok:
            out.append(sysp)
    return out


def _py_ge311(py):
    try:
        return subprocess.run([py, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"],
                              capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _pythons_for(name):
    """Тесты плагина pantheon идут только интерпретаторами 3.11+ (tomllib); guard — на всех: его хуки идут на python3
    из PATH, в том числе на системном 3.9."""
    pythons = _test_pythons()
    return [py for py in pythons if _py_ge311(py)] if name == "pantheon" else pythons


def _tmp_re():
    """Пути во временных папках — до <tmp>: у новой версии и базы они разные, а падение одно."""
    global _TMP_RE
    if _TMP_RE is None:
        pre = {"/private/tmp/", "/tmp/", "/private/var/folders/", "/var/folders/"}
        for t in (tempfile.gettempdir(), path("plugins", "tmp")):
            for v in (t, os.path.realpath(t)):
                pre.add(v.rstrip("/") + "/")
        alts = "|".join(re.escape(p) for p in sorted(pre, key=len, reverse=True))
        _TMP_RE = re.compile(rf"(?:{alts})[^\s'\"(),:;]*")
    return _TMP_RE


def _failure_signatures(fname, out, rc):
    """Подписи падений одного файла тестов: строки FAIL, исключение в конце вывода, ненулевой код (всегда — иначе
    гибель по сигналу прячется за старой строкой FAIL); rc None — таймаут, rc "срок" — не успел в срок прогона."""
    out = ANSI.sub("", out)
    sigs = [_tmp_re().sub("<tmp>", ln.strip()) for ln in out.splitlines() if ln.lstrip().startswith("FAIL")]
    if rc is None:
        return sigs + [f"{fname}: таймаут"]
    if rc == "срок":
        return sigs + [f"{fname}: срок прогона"]
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if "Traceback (most recent call last):" in out and lines and not lines[-1][:1].isspace():
        m = re.match(r"([A-Za-z_][\w.]*)(?::|$)", lines[-1])
        if m:
            sigs.append(f"{fname}: исключение {m.group(1)}")
    if rc != 0:
        sigs.append(f"{fname}: код {rc}")
    return sigs


def _fresh_failures(got_new, got_base):
    """Новые падения = подписи новой версии минус подписи базы. Файл, который у базы кончился таймаутом или сроком
    прогона, — не «чистый» и не «такой же сбой»: о нём ничего не известно, поэтому у новой версии в нём ничто не
    гасится (в том числе её собственный таймаут) — падение остаётся падением. Отдаёт (Counter, {(python, файл)})."""
    unknown = {(py, f) for (py, f, s) in got_base if s.endswith((": срок прогона", ": таймаут"))}
    known_base = collections.Counter({k: n for k, n in got_base.items() if (k[0], k[1]) not in unknown})
    fresh = got_new - known_base
    for k, n in got_new.items():  # не успевшее у новой не гасится тем, что не успело и у базы
        if k[2].endswith(": срок прогона"):
            fresh[k] = n
    return fresh, unknown


def _test_files(pdir):
    tests_dir = os.path.join(pdir, "tests") if pdir else ""
    return sorted(f for f in os.listdir(tests_dir) if f.startswith("test_") and f.endswith(".py")) \
        if tests_dir and os.path.isdir(tests_dir) else []


def _run_plugin_tests(pdir, pythons, tmp, log, label, deadline):
    """tests/test_*.py папки pdir по одному на каждом python → Counter подписей (python, файл, подпись)."""
    sigs = collections.Counter()
    env0 = {k: v for k, v in os.environ.items()
            if not k.startswith("PANTHEON_") and k not in ("FORCE_COLOR", "CLICOLOR_FORCE")}
    env0.update({"NO_COLOR": "1", "PYTHON_COLORS": "0"})
    for py in pythons:
        for f in _test_files(pdir):
            left = deadline - time.monotonic()
            if left <= 0:
                out, rc = "", "срок"
            else:
                home = tempfile.mkdtemp(prefix="home-", dir=tmp)
                # TMPDIR внутри папки прогона: временные папки тестов уходят вместе с ней, а не копятся в общем TMPDIR
                tdir = tempfile.mkdtemp(prefix="tmpdir-", dir=tmp)
                limit = min(PLUGIN_TEST_TIMEOUT, left)
                try:
                    r = subprocess.run([py, "-I", os.path.join("tests", f)], cwd=pdir, env={**env0, "HOME": home, "TMPDIR": tdir},
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       timeout=limit)
                    out, rc = r.stdout, r.returncode
                except subprocess.TimeoutExpired as e:
                    out, rc = e.stdout or b"", None if limit >= PLUGIN_TEST_TIMEOUT else "срок"
                except OSError as e:
                    out, rc = str(e), 127
                out = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
            state = {None: "таймаут", "срок": "срок прогона"}.get(rc, f"код {rc}")
            log.write(f"\n===== {label} · {py} · {f} · {state} =====\n{out}")
            log.flush()
            for s in _failure_signatures(f, out, rc):
                sigs[(py, f, s)] += 1
    return sigs


def _plugins_mark(marks, name, mark):
    """Метка сразу после каждого шага: следующий может упасть, а сделанное не повторяется."""
    if mark is None:
        marks.pop(name, None)
    else:
        marks[name] = {**mark, "at": stamp()}
    write_json(path("plugins", "marks.json"), marks)


def _plugins_respawn_mark(name):
    """metis-0181: отметка «нужен перезапуск» для тика (watch.plugins_respawn). since — время последней установки:
    окна, поднятые раньше, тик перезапускает, когда они свободны; done — уже перезапущенные сессии, новая установка
    его обнуляет (их версия этого плагина тоже старая)."""
    with lock("plugins-respawn"):
        cur = read_json(path("plugins", "respawn.json"), {})
        cur = cur if isinstance(cur, dict) else {}
        plugins = sorted({str(x) for x in cur.get("plugins") or []} | {name})
        write_json(path("plugins", "respawn.json"), {"since": now(), "at": stamp(), "plugins": plugins, "done": []})


def _plugin_install(name, old, new, log, marks, quiet, digest):
    """claude plugin update без -y (новая команда установки в каталоге должна требовать человека) и сверка того, что
    встало, с проверенной копией: версия и хеш дерева installPath."""
    try:
        r = subprocess.run([claude_bin(), "plugin", "update", f"{name}@{MARKETPLACE}", "-s", "user"],
                           capture_output=True, text=True, timeout=600)
        ok = r.returncode == 0
        why = f"код {r.returncode}: {' '.join((r.stderr or r.stdout or '').split())[:200]}"
    except (OSError, subprocess.TimeoutExpired) as e:
        ok, why = False, type(e).__name__
    row = (_plugins_installed() or {}).get(name) or {}
    got = row.get("version")
    if got == new and _tree_hash(row.get("installPath")) == digest:
        _plugins_mark(marks, name, None)
        _plugins_journal(f"{name} {old} → {new}: обновлён")
        _plugins_respawn_mark(name)
        alert(f"обновлён {name} {old} → {new}, плановый проход перезапустит свободные окна (Зевса — вы сами: pantheon start zeus "
              "--restart); окно, готовое раньше: pantheon saved --by <имя> --state <путь>", "plugins-update")
        if not quiet:
            print(f"{name}: обновлён {old} → {new}")
        return 0
    if got == old or (got is None and not ok):
        # ничего не встало: тесты зелёные, установка не удалась — пробуем на следующих запусках без тестов
        if ok:
            why = f"после update версия {got}, а не {new}"
        _plugins_mark(marks, name, {"version": new, "result": "green", "log": log, "hash": digest})
        _plugins_journal(f"{name} {old} → {new}: тесты зелёные, установка не удалась ({why})")
        alert_once(f"plugins-update-{name}", new, f"{name} {new}: тесты прошли, но claude plugin update не поставил "
                   f"({why}). Руками: claude plugin update {name}@{MARKETPLACE}", "plugins-update")
        if not quiet:
            print(f"{name}: {new} — тесты прошли, установка не удалась ({why})")
        return ALERTED
    # встало не то, что проверяли: другая версия или другое содержимое (update сам обновил каталог)
    _plugins_mark(marks, name, None)
    seen = got or "неизвестна"
    _plugins_journal(f"{name} {old} → {seen}: встала непроверенная версия (проверялась {new}, хеш {digest})")
    text = f"встала непроверенная версия {name} {seen} (проверялась {new})"
    alert("КРИТИЧНО: " + text, "plugins-update")
    notify(text, title="Пантеон · критично", group="critical")
    if not quiet:
        print(f"{name}: КРИТИЧНО — {text}")
    return ALERTED


def _plugin_check(name, old, new, src, base, marks):
    """Тесты новой версии против установленной. Отдаёт (лог, хеш проверенной копии, новые подписи)."""
    log = path("plugins", f"{_plugins_safe(name)}-{_plugins_safe(new)}.log")
    tmp = tempfile.mkdtemp(prefix=f"{_plugins_safe(name)}-", dir=path("plugins", "tmp"))
    deadline = time.monotonic() + PLUGIN_RUN_LIMIT
    try:
        ign = shutil.ignore_patterns(".git", "__pycache__")
        new_dir = os.path.join(tmp, "new", _plugins_safe(name))
        shutil.copytree(src, new_dir, symlinks=True, ignore=ign)
        digest = _tree_hash(new_dir)
        _plugins_mark(marks, name, {"version": new, "result": "testing", "log": log, "hash": digest})
        base_dir = None
        if isinstance(base, str) and os.path.isdir(base):
            base_dir = os.path.join(tmp, "base", _plugins_safe(name))
            shutil.copytree(base, base_dir, symlinks=True, ignore=ign)
        pythons = _pythons_for(name)
        with open(log, "w", encoding="utf-8") as fh:
            fh.write(f"{stamp()} {name}: новая {new} из {src} (хеш {digest}), база {old} из "
                     f"{base_dir and base or '—'}; python: {', '.join(pythons)}\n")
            got_new = _run_plugin_tests(new_dir, pythons, tmp, fh, f"новая {new}", deadline)
            got_base = _run_plugin_tests(base_dir, pythons, tmp, fh, f"база {old}", deadline)
            fresh, unknown = _fresh_failures(got_new, got_base)
            for py, f in sorted(unknown):
                fh.write(f"база не досчитана: {py} · {f} — файл базы не дошёл до конца (таймаут или срок прогона), "
                         "падения новой версии в нём считаются новыми\n")
            if not _test_files(new_dir):  # без тестов зелёного нет, даже если их нет и у базы
                fresh[("-", "-", NO_TESTS)] = 1
            fh.write(f"\n===== новых падений: {sum(fresh.values())} =====\n")
            for (py, f, s) in sorted(fresh):
                fh.write(f"{py} · {f} · {s}\n")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return log, digest, fresh


def plugins_update(quiet=False):
    with lock("plugins-update", block=False) as got:
        return _plugins_update(quiet) if got else 0


def _plugins_red(marks, name, old, new, log, what):
    _plugins_mark(marks, name, {"version": new, "result": "red", "log": log})
    _plugins_journal(f"{name} {old} → {new}: {what}, не ставлю ({log})")
    alert(f"{name} {new} не поставлен: {what}. Лог: {log.replace(HOME, '~')}", "plugins-update")
    return ALERTED


def _plugins_update(quiet):
    # остатки прогона, прерванного таймаутом задачи или сбоем (блокировка взята — чужого прогона нет)
    shutil.rmtree(path("plugins", "tmp"), ignore_errors=True)
    os.makedirs(path("plugins", "tmp"), exist_ok=True)
    try:
        ok = subprocess.run([claude_bin(), "plugin", "marketplace", "update", MARKETPLACE],
                            capture_output=True, text=True, timeout=300).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ok = False
    if not ok:  # нет сети или каталог недоступен — подождём следующего раза, без тревоги
        if not quiet:
            print(f"каталог {MARKETPLACE} не обновился — попробую в следующий раз")
        return TEMPFAIL
    installed = _plugins_installed()
    if installed is None:
        print("pantheon plugins update: не прочитал claude plugin list --json", file=sys.stderr)
        return 1
    catalog = _plugins_catalog()
    marks = read_json(path("plugins", "marks.json"))
    rc, tested = 0, False
    for name in sorted(installed):
        if name not in catalog:
            continue
        old, (new, src) = installed[name]["version"], catalog[name]
        if not _version_newer(new, old):
            if not quiet:
                print(f"{name}: {old}, новее нет")
            continue
        mark = marks.get(name) if isinstance(marks.get(name), dict) else {}
        same = mark.get("version") == new
        log = mark.get("log") or path("plugins", f"{_plugins_safe(name)}-{_plugins_safe(new)}.log")
        if same and mark.get("result") == "red":
            if not quiet:
                print(f"{name}: {new} не ставлю — тесты были красные ({mark.get('log')})")
            continue
        if same and mark.get("result") == "testing":
            rc = max(rc, _plugins_red(marks, name, old, new, log, "прогон тестов прерван — таймаут задачи или сбой"))
            if not quiet:
                print(f"{name}: {new} не ставлю — прошлый прогон тестов прерван")
            continue
        if same and mark.get("result") == "green" and mark.get("hash") and _tree_hash(src) == mark["hash"]:
            rc = max(rc, _plugin_install(name, old, new, log, marks, quiet, mark["hash"]))
            continue
        if tested:  # тесты — не больше одного плагина за запуск: иначе не уложиться в timeout задачи
            if not quiet:
                print(f"{name}: {new} — проверю на следующем запуске")
            continue
        tested = True
        log, digest, fresh = _plugin_check(name, old, new, src, installed[name].get("installPath"), marks)
        if not fresh:
            rc = max(rc, _plugin_install(name, old, new, log, marks, quiet, digest))
            continue
        # одна подпись на двух python — одна строка в тревоге
        first = list(dict.fromkeys(s if s.startswith(f + ":") or f == "-" else f"{f}: {s}"
                                   for (py, f, s) in sorted(fresh)))[:3]
        rc = _plugins_red(marks, name, old, new, log,
                          f"новые падения тестов ({sum(fresh.values())}) — {'; '.join(first)}")
        if not quiet:
            print(f"{name}: {new} не ставлю — новые падения тестов, лог {log}")
    return rc


def plugins_cmd(rest):
    if rest[:1] == ["update"] and all(a == "--quiet" for a in rest[1:]):
        return plugins_update(quiet="--quiet" in rest)
    print("pantheon plugins: есть только update [--quiet]", file=sys.stderr)
    return 2


# --- review: записи для шлюза слияния guard (P1-4, guard 0.5.4) -------------------------------------------------
# Сама команда ничего не пишет: журнал STATE/merge-gate/records.jsonl пишет хук guard на PostToolUse по успешной
# простой команде `pantheon review …` и по agent_type сессии (accept, reject — argus, talos — talos). Поэтому
# запись нельзя сделать текстом команды от чужой роли, а сама команда только проверяет условия и формат.
REVIEW_SHA = re.compile(r"[0-9a-f]{40}")
REVIEW_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
REVIEW_PR = re.compile(r"[1-9][0-9]{0,8}")
REVIEW_USAGE = ("pantheon review test -- <команда…> | accept <owner/repo> <PR> <SHA 40 знаков> --opened \"<что "
                "открыл>\" --ran \"<что запустил>\" --unchecked \"<что не проверял>\" | reject <owner/repo> <PR> <SHA> "
                "[те же флаги] | talos <owner/repo> <PR> <SHA> | begin <owner/repo> <PR> <SHA> | status [<owner/repo> <PR>]")
# перечень проверенного в «принять» (Б6, guard 0.5.6): у accept все три поля обязательны и непусты, у reject — по
# желанию. Тот же разбор — в merge_gate.verdict_parse плагина guard (он и решает, будет ли запись)
REVIEW_CHECKLIST = {"opened": "открыл", "ran": "запустил", "unchecked": "не проверял"}


def _review_verdict(sub, args):
    """accept|reject|talos: → (позиционные [repo, PR, SHA], перечень {поле: значение}, None) или (…, текст ошибки)."""
    flags = sub in ("accept", "reject")
    fmt = f"pantheon review {sub} <owner/repo> <номер PR> <SHA 40 знаков>" + (
        ' --opened "<что открыл>" --ran "<что запустил>" --unchecked "<что не проверял>"' if sub == "accept"
        else " [--opened … --ran … --unchecked …]" if flags else "")
    pos, checklist, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if flags and a.startswith("--") and len(a) > 2:
            name, eq, val = a[2:].partition("=")
            if name not in REVIEW_CHECKLIST:
                return pos, {}, f"неизвестный флаг --{name}. Формат: {fmt}"
            if name in checklist:
                return pos, {}, f"--{name} указан дважды. Формат: {fmt}"
            if not eq:
                if i + 1 >= len(args):
                    return pos, {}, f"у --{name} нет значения. Формат: {fmt}"
                i += 1
                val = args[i]
            if val.strip().startswith("--"):  # `--opened --ran …`: имя флага — не значение
                return pos, {}, f"значение --{name} начинается с «--»: похоже, пропущено значение. Формат: {fmt}"
            checklist[name] = val.strip()
        else:
            pos.append(a)
        i += 1
    if len(pos) != 3 or not REVIEW_REPO.fullmatch(pos[0]) or not REVIEW_PR.fullmatch(pos[1]) \
            or not REVIEW_SHA.fullmatch(pos[2].lower()):
        return pos, {}, f"аргументы не в формате {fmt} (SHA — полный: gh pr view N --json headRefOid)"
    if sub == "accept":
        missing = [f"--{k}" for k in REVIEW_CHECKLIST if not checklist.get(k)]
        if missing:
            return pos, {}, (f"«принять» без перечня проверенного (Б6): нет или пусто {', '.join(missing)}. Формат: "
                             f"{fmt}. Шлюз слияния guard пускает только «принять», где сказано, что открыто, что "
                             "запущено и чего не проверял")
    return pos, {k: v for k, v in checklist.items() if v}, None


def _review_git(*args):
    """Вывод git в текущей папке (без переменных GIT_*); None — не репозиторий или сбой."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _review_state():
    """(HEAD, дерево чистое) текущей папки; HEAD None — не git или коммитов нет."""
    head = (_review_git("rev-parse", "HEAD") or "").strip().lower()
    status = _review_git("status", "--porcelain")
    return (head if REVIEW_SHA.fullmatch(head) else None), (status is not None and not status.strip())


def review_records(repo=None, pr=None):
    """Записи журнала шлюза слияния (битые строки пропускаются); файл — симлинк или не читается — пусто."""
    try:
        fd = os.open(os.path.join(STATE, "merge-gate", "records.jsonl"), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return []
    out = []
    with os.fdopen(fd, "rb") as fh:
        for raw in fh:
            try:
                rec = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(rec, dict) or not isinstance(rec.get("repo"), list):
                continue
            if repo and repo.lower() not in [str(x).lower() for x in rec["repo"]]:
                continue
            if pr is not None and rec.get("pr") not in (pr, None):
                continue
            out.append(rec)
    return out


REVIEW_PENDING_TTL = 2 * 3600  # метка «ревью идёт» устаревает через 2 часа


def _review_pending_path(repo, pr):
    return path("review-pending", f"{repo.lower().replace('/', '__')}__{pr}.json")


def _record_epoch(rec):
    try:
        d = datetime.fromisoformat(str(rec.get("time")))
        return d.timestamp()  # без пояса — местное время, как пишет хук guard
    except ValueError:
        return None


def review_pending(repo, pr, recs=None):
    """Метка «ревью идёт» для (repo, PR) или None: нет метки, старше 2 ч, или после неё есть вердикт на этот PR."""
    d = read_json(_review_pending_path(repo, pr), None)
    if not isinstance(d, dict) or not isinstance(d.get("t"), (int, float)):
        return None
    if not 0 <= now() - d["t"] < REVIEW_PENDING_TTL:
        return None
    for r in review_records(repo, int(pr)) if recs is None else recs:
        if r.get("kind") in ("accept", "reject") and (_record_epoch(r) or 0) >= d["t"] - 1 \
                and repo.lower() in [str(x).lower() for x in r.get("repo") or []]:
            return None  # вердикт на тот же sha — ревью кончилось; на другой — head сменился, метка устарела
    return d


def review_cmd(rest):
    sub = rest[0] if rest else ""
    if sub == "begin":
        args, _, why = _review_verdict("talos", rest[1:])  # тот же разбор: repo, PR, SHA без флагов
        if why:
            print(f"pantheon review begin: {why.replace('review talos', 'review begin')}", file=sys.stderr)
            return 2
        repo, pr, sha = args[0].lower(), args[1], args[2].lower()
        who = " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "").split())[:40]
        write_json(_review_pending_path(repo, pr), {"repo": repo, "pr": int(pr), "sha": sha, "t": now(),
                                                    "time": stamp(), "by": who or None})
        print(f"pantheon review begin: ревью {repo}#{pr} @ {sha[:8]} помечено «идёт» (не вердикт и не согласие; "
              f"шлюз метку не читает)")
        return 0
    if sub == "test":
        if len(rest) < 3 or rest[1] != "--":
            print(f"pantheon review: {REVIEW_USAGE}", file=sys.stderr)
            return 2
        head, clean = _review_state()
        if head is None:
            print("pantheon review test: папка не репозиторий git или в нём нет коммитов", file=sys.stderr)
            return 2
        if not clean:
            print("pantheon review test: дерево не чистое — закоммить или убери правки: тесты пишутся на коммит, "
                  "а не на незакоммиченное", file=sys.stderr)
            return 2
        try:
            rc = subprocess.run(rest[2:]).returncode
        except OSError as e:
            print(f"pantheon review test: команда не запустилась: {e}", file=sys.stderr)
            return 127
        head2, clean2 = _review_state()
        if head2 != head or not clean2:
            print(f"pantheon review test: команда изменила HEAD или дерево (было {head}, стало {head2 or '?'}, "
                  f"чистое: {'да' if clean2 else 'нет'}) — запись не делается", file=sys.stderr)
            return 3
        print(head)
        print(f"pantheon review test: код {rc} на {head}" + (" — запись тестов сделает хук guard" if rc == 0 else
                                                             " — тесты не прошли, записи не будет"))
        return rc
    if sub in ("accept", "reject", "talos"):
        args, checklist, why = _review_verdict(sub, rest[1:])
        if why:
            print(f"pantheon review {sub}: {why}", file=sys.stderr)
            return 2
        who = "argus" if sub != "talos" else "talos"
        print(f"pantheon review {sub}: {args[0].lower()}#{args[1]} @ {args[2].lower()} — записано хуком guard, "
              f"если роль подходит ({who})")
        for k, v in checklist.items():
            print(f"  {REVIEW_CHECKLIST[k]}: {v}")
        return 0
    if sub == "status":
        args = rest[1:]
        if args and (len(args) != 2 or not REVIEW_REPO.fullmatch(args[0]) or not REVIEW_PR.fullmatch(args[1])):
            print("pantheon review status [<owner/repo> <номер PR>]", file=sys.stderr)
            return 2
        recs = review_records(args[0] if args else None, int(args[1]) if args else None)
        pend = []
        if args:
            pend = [review_pending(args[0], args[1])]
        else:
            for f in sorted(glob.glob(path("review-pending", "*.json"))):
                d = read_json(f, None)
                if isinstance(d, dict) and d.get("repo") and d.get("pr"):
                    pend.append(review_pending(d["repo"], d["pr"]))
        for d in (x for x in pend if x):
            print(f"ревью идёт с {stamp(d['t'])[11:]} ({d['repo']}#{d['pr']}, head {str(d['sha'])[:8]}"
                  + (f", {d['by']}" if d.get("by") else "") + ") — второго argus не звать")
        if not recs:
            print("pantheon review status: записей нет")
        for r in recs:
            by = r.get("by") if isinstance(r.get("by"), dict) else {}
            pr = f"#{r['pr']}" if r.get("pr") else ""
            print(f"{r.get('time', '?')}  {r.get('kind', '?'):<6}  {','.join(map(str, r['repo']))}{pr}  "
                  f"{str(r.get('sha', ''))[:12]}  {by.get('agent_type') or '—'}")
            cl = r.get("checklist") if isinstance(r.get("checklist"), dict) else {}
            if r.get("kind") == "accept" and not all(isinstance(cl.get(k), str) and cl[k].strip()
                                                     for k in REVIEW_CHECKLIST):
                print("    без перечня проверенного (Б6) — шлюз слияния такое «принять» не пускает")
            for k, label in REVIEW_CHECKLIST.items():
                if isinstance(cl.get(k), str) and cl[k].strip():
                    print(f"    {label}: {cl[k]}")
        return 0
    print(f"pantheon review: {REVIEW_USAGE}", file=sys.stderr)
    return 2


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "review":
        return review_cmd(rest)
    if cmd == "tick":
        tick()
        return 0
    if cmd == "run-job":
        if not rest or not JOB_NAME.fullmatch(rest[0]):
            print("pantheon run-job: имя задачи не по образцу", file=sys.stderr)
            return 2
        return run_job(rest[0])
    if cmd == "jobs":
        if not rest:
            jobs_show()
            return 0
        if rest[0] in ("pause", "resume", "disable", "enable", "renew") and len(rest) >= 2:
            return jobs_set(rest[0], rest[1], rest[2] if len(rest) > 2 else None)
    if cmd == "alert" and rest:
        who = "agent"
        if "--from" in rest:
            i = rest.index("--from")
            if i + 1 >= len(rest):
                print("pantheon alert: после --from нужно имя", file=sys.stderr)
                return 2
            who, rest = rest[i + 1], rest[:i] + rest[i + 2:]
        critical = "--critical" in rest
        rest = [a for a in rest if a != "--critical"]
        if not " ".join(rest).strip():
            print("pantheon alert: пустая строка", file=sys.stderr)
            return 2
        alert(("КРИТИЧНО: " if critical else "") + " ".join(rest), who)
        if critical:  # COMM-08: безопасность, деньги, данные клиентов, юридическое, прод, контракт — сразу владельцу
            # отправителя называет он сам (--from, PANTHEON_ROLE — переменные вызова): заголовок не утверждает, кто
            # прислал, имя — в тексте со словами «со слов». Сразу всегда (и ночью), но в счёт бюджета и в журнал
            notify_critical(f"{' '.join(rest)[:200]} (со слов: {' '.join(who.split())[:40]})")
        return 0
    if cmd == "archive":
        return archive()
    if cmd == "domains" and rest[:1] == ["build"]:
        return domains_build(if_changed="--if-changed" in rest)
    if cmd == "view":
        return view(quiet="--quiet" in rest)
    if cmd == "commit":
        return commit()
    if cmd == "board":
        return board()
    if cmd == "sync-answers":
        return sync_answers()
    if cmd == "status":
        return status()
    if cmd == "check":
        return check([a for a in rest if not a.startswith("-")] or None, quiet="--quiet" in rest)
    if cmd == "task":
        return task_cmd(rest)
    if cmd == "executors":
        return executors_mod().cli(rest, _task_head)
    if cmd == "exec":
        return executors_mod().exec_cli(rest)
    if cmd == "start":
        return start(rest)
    if cmd == "wake":
        if rest[:1] == ["hestia"]:
            return wake_hestia(rest)
        if rest and not rest[0].startswith("-"):
            return watch_cmd("wake", rest)
        return wake(rest)
    if cmd == "roles" and rest[:1] == ["build"]:
        src = out = None
        flags = rest[1:]
        try:
            if flags:
                if len(flags) % 2 or any(a not in ("--out", "--src") for a in flags[::2]) \
                        or len(set(flags[::2])) != len(flags) // 2 or "--out" not in flags[::2]:
                    raise ValueError("roles build [--out <папка> [--src <папка шаблонов>]]")
                kv = dict(zip(flags[::2], flags[1::2]))
                out, src = kv["--out"], kv.get("--src")
            made = roles_build(src, out)
        except ValueError as e:
            print(f"roles build: {e}", file=sys.stderr)
            return 2
        print(f"роли: {', '.join(made) if made else 'без изменений'}")
        return 0
    if cmd == "role":
        return role_cmd(rest)
    if cmd == "direction":
        return direction(rest)
    if cmd == "instructions":
        return instructions_check(quiet="--quiet" in rest)
    if cmd == "approve":
        return approve(rest)
    if cmd == "consent":
        return consent(rest)
    if cmd in WATCH_CMDS:
        return watch_cmd(cmd, rest)
    if cmd == "usage":
        return usage_report(rest)
    if cmd == "metrics":
        return metrics_cmd(rest)
    if cmd == "reboot-reminder":
        return awake_mod().reboot_reminder(rest)
    if cmd == "night":
        return night_mod().main(rest)
    if cmd == "read":
        return read_mod().main(rest)
    if cmd == "mmv":
        return mmv_mod().main(rest, STATE, now())
    if cmd == "qmd":
        return qmd_mod().main(rest)
    if cmd == "plugins":
        return plugins_cmd(rest)
    if cmd == "service-run":
        if len(rest) != 1 or not JOB_NAME.fullmatch(rest[0]):
            print("pantheon service-run: имя службы не по образцу", file=sys.stderr)
            return 2
        return service_run(rest[0])
    if cmd == "install":
        return install()
    if cmd == "uninstall":
        return uninstall()
    print(f"pantheon: не понял «{' '.join(argv)}». Справка — pantheon help", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
