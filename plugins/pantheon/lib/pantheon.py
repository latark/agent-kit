#!/usr/bin/env python3
"""Пантеон: планировщик pantheon-tick и команда pantheon.

Всё, что Пантеон делает сам по времени, идёт через одну задачу launchd `pantheon-tick` (раз в 60 с).
Список задач — ~/ai/pantheon/schedule.toml (правит штаб); метки запусков — ~/.local/state/pantheon/
(свои у каждого Mac). Что пора запускать, тик решает по меткам, а не по часам: пропуски за сон Mac
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
  pantheon plugins update [--quiet]     новые версии плагинов agent-kit (тик раз в 10 мин): тесты новой и
                                        установленной версии; нет новых падений — claude plugin update, есть — тревога
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
  pantheon status                       один экран для отладки: тик, сессии, вопросы к вам, тревоги, защиты, sync, места heavy, версии
  pantheon sync-answers                 ваш ответ на доске по карантину ~/.claude — применить сразу (sync.sh), без новой сессии
  pantheon check [файл…]                проверить шапки задач по схеме v1 (schema.md)
  pantheon task new --direction D --title T [--status S --priority N --due ГГГГ-ММ-ДД[TЧЧ:ММ] --next X --owner O
                    --project P --waiting-on W --question Q --why W --option "А — … Цена: …" --option …
                    --recommend "А — потому что …" --if-no-answer "…" --depends-on ID]
                    без --owner «Кому» — координатор направления; owner= (пусто) в task set — отказ
  pantheon task set ID поле=значение … [--option "вариант" …] [--note "строка в журнал"]   pantheon task show ID
  pantheon task ready [--direction D] [--owner O]   pantheon task claim ID --by КТО [--hours 1]
  pantheon start <направление> [поручение]   координатор: фоновая сессия domain-coordinator в окне направления
  pantheon start workshop <задача> [поручение]   мастерская: daedalus-<задача> в ~/projects/workshop/<задача>
  pantheon start zeus                   штаб: ваша сессия hq в ~/ai/pantheon с окном hq.json   (--from zeus|tick|owner)
  pantheon wake [--dry-run]             поднять прерванные сессии Пантеона с открытой задачей и сказать «продолжай»
  pantheon watch [--dry-run]            дежурный (тик раз в 5 мин): сессии, STATUS.md, swap, worktree, версия Claude Code,
                                        паузы, самозапуск по вашим решениям; --dry-run — кого поднял бы и почему нет
  pantheon agents | who                 снимок claude agents для строки статуса | таблица координаторов
  pantheon revisits                     пересмотры к сроку и по событиям (тик раз в сутки)
  pantheon wake <имя> ["толчок"]        поднять уснувшую сессию направления той же сессией
  pantheon stop <имя>|--all, resume <имя>|--all   остановить (метка «остановлено вами») и вернуть
  pantheon pause <имя>|--all --reason limit|swap|manual ["почему"], pause --off [<имя>|--all]   пауза по нагрузке
  pantheon restart --prepare [причина]|--status|--go [--force]|--cancel   технический перезапуск всех сессий
  pantheon saved --by <имя> --state <путь>   сессия сохранилась перед техперезапуском
  pantheon infra-check                  опоры системы после обновления Claude Code
  pantheon usage [дней]                 отчёт расхода в ~/ai/pantheon/metrics/usage/ (тик раз в неделю)
  pantheon roles build                  роли ~/.claude/agents/*.md из шаблонов *.tmpl и частей _parts/*.part
  pantheon approve [list] | add --site S --allow "…" [--limits "…"] | remove N   заранее разрешённое (только вы)
  pantheon consent <id> [--days N]      ваш ответ Зевсу на вопрос <id> (журнал owner-log Зевса, по умолчанию 7 дней) —
                                        для исполнителя: согласие, данное в окне Зевса
  pantheon review test -- <команда…>    тесты для запора слияния (guard 0.5.4): в чистом дереве git запустить
                                        команду (без оболочки); HEAD и дерево после неё те же — выход с её кодом
                                        и SHA; запись в журнал делает хук guard (PostToolUse), сама команда не пишет
  pantheon review accept|reject|talos <owner/repo> <PR> <SHA>   вердикт argus (accept, reject) или проверка talos на
                                        этот SHA; проверяет формат, запись — хук guard и только по роли
  pantheon review status [<owner/repo> <PR>]   записи журнала ~/.local/state/pantheon/merge-gate/records.jsonl
  pantheon commit                       commit → pull без rebase → push ~/ai/pantheon
  pantheon install | uninstall          поставить или снять задачу launchd com.latark.pantheon-tick
  pantheon tick                         один проход планировщика (его вызывает launchd)
Уведомления (lib/notify.py): присутствие по простою, тихие часы, утренний дайджест, повтор и «долго ждёт», склейка
по id решения, бюджет в день; пороги — таблица [notify] в schedule.toml, состояние и журнал — notify.json и
notify-log.jsonl в ~/.local/state/pantheon/.
Для синтетических тестов: PANTHEON_HOME, PANTHEON_STATE, PANTHEON_NOW — «сейчас», PANTHEON_HOST,
PANTHEON_FAKE_WAKE, PANTHEON_FAKE_AC, PANTHEON_FAKE_IDLE — простой в секундах, PANTHEON_FAKE_LIMIT, PANTHEON_DRYRUN,
PANTHEON_NO_NOTIFY — без уведомлений, PANTHEON_NOTIFY_LOG — уведомления строкой «заголовок|текст|ссылка|группа» в файл.
"""
import collections
import contextlib
import fcntl
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
    sys.exit("pantheon: нужен Python 3.11 или новее (tomllib)")
import tomllib

HOME = os.path.expanduser("~")
AI_HOME = os.path.join(HOME, "ai")  # рабочие папки системы: pantheon, pantheon-view, knowledge (переезд 14.10)
PANTHEON = os.path.realpath(os.environ.get("PANTHEON_HOME") or os.path.join(AI_HOME, "pantheon"))
STATE = os.path.realpath(os.environ.get("PANTHEON_STATE") or os.path.join(HOME, ".local", "state", "pantheon"))
VIEW = os.environ.get("PANTHEON_VIEW") or os.path.join(AI_HOME, "pantheon-view")
VIEW_INBOX = os.environ.get("PANTHEON_VIEW_INBOX") or os.path.join(PANTHEON, "inbox-view")
LIB = os.path.dirname(os.path.realpath(__file__))
PLUGIN = os.path.dirname(LIB)
LABEL = "com.latark.pantheon-tick"
# Неизменный путь к плагину: на него смотрят задача launchd, команда ~/.local/bin/pantheon и обработчики слияния
# в ~/ai/pantheon/.git/config. `pantheon install` перевешивает ссылку на ту копию плагина, из которой запущен
# (до шага 0.4 — рабочая копия agent-kit, с 0.4 — клон маркетплейса), поэтому обновление плагина путей не ломает.
CURRENT = os.path.join(HOME, ".local", "share", "pantheon", "current")
TEMPFAIL = 75   # задача ждёт (нет сети): не сбой, тревоги нет
ALERTED = 76    # сбой, о котором задача уже сообщила сама: вторую тревогу не давать
PLIST = os.path.join(HOME, "Library", "LaunchAgents", LABEL + ".plist")
LIMIT_SNAPSHOT = os.path.join(HOME, ".local", "state", "claude-statusline", "five-hour")
DEFAULTS = {"heavy_gap_min": 2, "wake_quiet_min": 10, "idle_min": 10, "limit_max_pct": 70}


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
    os.makedirs(path("locks"), exist_ok=True)
    fh = open(path("locks", name + ".lock"), "a")
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
                         "В «ждёт вас» на доске переносит штаб; старше 30 дней уносит `pantheon archive`.\n\n")
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
                    "instructions", "agents", "usage", "qmd", "plugins"}
CLAUDE_VALUE_FLAGS = {"--agent", "--model", "--max-turns", "--name"}


def parse_command(cmd):
    """Команда задачи из schedule.toml → argv без оболочки, или None (задача не идёт). Разрешено только:
      pantheon <view|commit|domains|watch|revisits|scout|board|sync-answers|…> [аргументы без спецсимволов];
      claude -p --agent <роль> [--model M] [--max-turns N] [--name N] "<поручение>" — без флагов прав и настроек;
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
        return argv
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


def launch(name, t):
    """Запуск задачи отдельным процессом (или запись в журнал решений при PANTHEON_DRYRUN)."""
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        st = job_state(name)
        st.update(last_start=t, last_end=t, last_rc=0, waiting=None)
        save_job_state(name, st)
        with open(path("dryrun.log"), "a") as fh:
            fh.write(f"{int(t)} {name}\n")
        return
    subprocess.Popen([sys.executable, "-I", os.path.realpath(__file__), "run-job", name],
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
        heavy = []
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
            if job.get("class", "light") == "heavy":
                heavy.append((job, st, due_at))
            else:
                launch(name, t)
        if heavy:
            tick_heavy(sched, heavy, t)
        try:
            services_sync(sched)
        except Exception as e:  # сбой служб не должен останавливать задачи тика
            alert_once("svc-sync", type(e).__name__, f"службы: сверка с launchd упала ({type(e).__name__}: {e})",
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
# своя задача launchd com.latark.pantheon-svc.<имя> с KeepAlive; запускает её `pantheon service-run <имя>`, который
# перечитывает schedule.toml и проверяет команду (только `pantheon …` или скрипт плагина). Тик сверяет launchd с
# расписанием: нужна и не запущена — поднять, пауза, выключена, убрана из расписания или чужой Mac — снять.

SVC_PREFIX = "com.latark.pantheon-svc."
SVC_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>{bin}</string><string>service-run</string><string>{name}</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProcessType</key><string>Background</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>{path}</string></dict>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


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


def _svc_path():
    """PATH служб — тот же, что у задачи тика (python3 из него запускает pantheon): от того, каким python вызван
    `pantheon jobs`, plist не меняется и служба не перезапускается зря (ревью argus 15.10)."""
    import plistlib
    with contextlib.suppress(OSError, ValueError, KeyError, TypeError, plistlib.InvalidFileException):
        with open(PLIST, "rb") as fh:
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
    env_path = _svc_path()
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
        text = SVC_TMPL.format(label=SVC_PREFIX + name, bin=os.path.join(CURRENT, "bin", "pantheon"), name=name,
                               path=env_path, log=path("logs", f"svc-{name}.log"))
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
    os.chdir(HOME)
    os.execve(argv[0], argv, run_env())


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
        with (lock("heavy-run", block=False) if heavy else contextlib.nullcontext(True)) as hgot:
            if not hgot:
                return 0
            st = job_state(name)
            st.update(last_start=now())
            save_job_state(name, st)
            os.makedirs(path("logs"), exist_ok=True)
            log = path("logs", name + ".log")
            started = time.time()
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
            if os.path.getsize(log) > 400_000:
                data = open(log, encoding="utf-8", errors="ignore").read()[-200_000:]
                open(log, "w", encoding="utf-8").write(data)
            st = job_state(name)
            st.update(last_end=now(), last_rc=rc)
            st.pop("running", None)
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
        return "на ближайшем тике"
    if job.get("every", "tick") == "tick":
        return "каждый тик"
    left = st["last_start"] + every_sec(job) - t
    if left <= 60:
        return "на ближайшем тике"
    return f"через {int(left // 60)} мин" if left < 5400 else stamp(st["last_start"] + every_sec(job))


def jobs_show():
    lt = None
    with contextlib.suppress(OSError, ValueError):
        lt = float(open(path("last-tick")).read())
    tick_line = f"тик: {ago(lt)}" if lt else "тик: ещё не шёл (pantheon install)"
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
        every = "каждый тик" if job.get("every", "tick") == "tick" else f"{job['every']} мин"
        if job.get("enabled") is False or st.get("disabled"):
            state = "выключена"
        elif st.get("paused"):
            state = f"пауза{': ' + st['paused_reason'] if st.get('paused_reason') else ''}"
        elif locked("job-" + job["name"]):
            state = "идёт"
        elif parse_command(job.get("command")) is None:
            state = "команда не разрешена — пропускается"
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
            state = (f"идёт, pid {pid}" if pid else "не идёт — тик поднимет") if ok else why
            if not ok and pid:
                state += f" (ещё идёт, pid {pid}: тик снимет)"
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
        warn.append("тик стоит")
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
            if ok and not svc_running(svc["name"]):
                lines.append(f"служба {svc['name']}: НЕ ИДЁТ — журнал ~/.local/state/pantheon/logs/svc-{svc['name']}.log")
                warn.append(f"служба {svc['name']}")
            elif not ok and why in ("пауза", "команда не разрешена"):
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
    section("Тик", lines)

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
            by.setdefault(a.get("state") or "?", []).append(a)
        order = ("interactive", "working", "blocked", "failed", "done", "stopped")
        word = {"interactive": "открыты в терминале", "working": "фоновые работают", "blocked": "ждут вас",
                "failed": "упали", "done": "закончили ход", "stopped": "остановлены"}
        lines.append(" · ".join(f"{word.get(k, k)}: {len(by[k])}" for k in sorted(by, key=lambda k: (
            order.index(k) if k in order else 9))) or "фоновых сессий нет")
        for k in ("blocked", "failed"):
            for a in by.get(k, []):
                why = a.get("waitingFor") or a.get("status") or ""
                lines.append(f"{word[k]}: {a.get('name') or a.get('id')} — {str(why)[:80]}")
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
    marks = {".sync-held": "карантин правок — ответ на доске", ".sync-incoming": "правка с другого Mac — на доске",
             ".sync-conflict": "конфликт с другим Mac", ".sync-error": "ошибка синхронизации"}
    for f, what in marks.items():
        if os.path.exists(os.path.join(cfg, f)):
            lines.append(what)
            warn.append("sync")
    section("Синхронизация ~/.claude", lines or ["в порядке"])

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
                alert_once("merge-conflict", theirs, f"~/ai/pantheon: конфликт слияния с другим Mac "
                           f"({', '.join(files) or 'файлы не названы'}); локальный коммит цел, слияние отменено — "
                           "разобрать вручную", "pantheon-commit", note="~/ai/pantheon: конфликт слияния, нужен разбор")
                return ALERTED
            return offline(pull.stderr)
        clear_once("merge-conflict")
        ahead = git("rev-list", "--count", "@{u}..HEAD", check=False).stdout.strip()
        if ahead and ahead != "0":
            push = git("push", "-q", check=False)
            if push.returncode != 0:
                return offline(push.stderr)
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
        watched = (reg_path, policy_path, os.path.join(HOME, ".claude", "projects"), AGENTS,
                   CLAUDE_TMP)
        newest = max([os.path.getmtime(p) for p in watched if os.path.exists(p)] + [roles_newest()])
        if built >= newest:
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
    domains, stores = {}, {}
    for d in reg.get("direction") or []:
        name = d.get("name", "")
        if not re.fullmatch(r"[a-z0-9-]+", name):
            print(f"пропущено направление с именем не по образцу: {name!r}", file=sys.stderr)
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
    write_json(path("domains.json"), {
        "_comment": "Собрано `pantheon domains build` из ~/ai/pantheon/directions.toml. Руками не править.",
        "built": stamp(), "built_ts": now(), "domains": domains})
    built = sandbox_build(domains, policy_path, stores)
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
# .git/config и .git/hooks закрыты для записи: сетевой git у направлений с SSH-remote и gh идут мимо песочницы.
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
# Мимо песочницы: gh (в ней не работает — TLS Go на macOS) — только эти подкоманды; дописать тревогу
SANDBOX_EXCLUDED = ["gh pr *", "gh issue *", "gh run *", "gh repo view *", "gh api *", "gh auth status",
                    "pantheon alert *", "pantheon consent *", "pantheon saved *"]
# git по SSH в песочнице macOS не работает: у направлений с таким remote сетевые команды git — мимо неё
GIT_NETWORK = ["git push", "git push *", "git fetch", "git fetch *", "git pull", "git pull *"]
COORDINATOR_COMPACT = 200000
# Окну координатора направления — слияние PR без вопроса классификатора режима auto (metis-0050). Каждое слияние
# по-прежнему проверяет guard (merge_problem): только главная сессия domain-coordinator, свои папки, без --admin и
# --auto. Мастерской и штабу правила нет.
COORDINATOR_ALLOW = ["Bash(gh pr merge *)"]
# Роли главных сессий: их память в песочницу не добавляется, даже если в шапке есть memory:
MAIN_ROLES = ("hq", "domain-coordinator", "workshop")
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


# корпус и его копии: индексы qmd и самого корпуса хранят полный текст, переписка сессий Фемиды — выдержки.
# legal-watch/cache и inbox (P0-1, metis-0060): там выгрузки Telegram-каналов (cache/telegram) и входящие сырые
# материалы — чужой текст, как корпус; штабу его не читать (у Зевса личное и действия наружу). Вопросы по праву и
# каналам — Фемиде (themis-sources) поручением; коллекцию qmd legal штабу закрывает хук qmd-query
HQ_CLOSED_DIRS = ["~/projects/expert-corpus", "~/.cache/expert-corpus", "~/.cache/qmd",
                  "~/.claude/projects/*expert-corpus*", "~/projects/legal-watch/cache", "~/projects/legal-watch/inbox"]


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


def role_settings(folders, own_dir, extra_write, cache, ssh, deny_read, compact=None, guard=None):
    allow = list(folders) + ([own_dir] if own_dir else []) + list(extra_write) + [cache]
    # .git/config и .git/hooks — внутри каждой разрешённой папки (её настоящим путём) и под ~ в целом
    deny_write = ["~/**/.git/config", "~/**/.git/hooks"] + [f"{r}{sub}" for r in allow for sub in
                                                             ("/.git/config", "/.git/hooks", "/**/.git/config", "/**/.git/hooks")]
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


def sandbox_build(domains, policy_path, stores=None):
    """domains.json и policy.toml → ~/.local/state/pantheon/settings/<направление>.json и workshop.json."""
    try:
        with open(policy_path, "rb") as fh:
            policy = tomllib.load(fh)
    except (OSError, ValueError):
        policy = {}
    extra = policy.get("sandbox_write") or {}
    private = policy.get("private") or {}
    private_paths = [p for p in private.get("paths") or [] if isinstance(p, str) and p.startswith("~/")]
    private_dirs = set(private.get("coordinators") or [])
    caches = "~/Library/Caches/pantheon-sandbox"
    out_dir = path("settings")
    guard = guard_script()
    if not os.path.isfile(guard):
        alert_once("guard-missing", guard, f"нет {guard.replace(HOME, '~')}: окна ролей не пропустят ни одной записи "
                   "(строгий guard, SEC-29) — переустановить плагин guard", "pantheon")
    os.makedirs(out_dir, exist_ok=True)

    memory = memory_dirs()

    def one(name, folders, own, compact, deny, allow=None):
        real = [_real_dir(f, SANDBOX_ROOTS[:1], strict=True) or _real_dir(f, SANDBOX_ROOTS[1:]) for f in folders]
        skipped = [f for f, r in zip(folders, real) if not r]
        if skipped:
            print(f"песочница {name}: вне ~/projects и ~/ai/knowledge, ссылка или нет папки — только через Write/Edit: "
                  f"{skipped}", file=sys.stderr)
        own_real = os.path.realpath(own) if os.path.isdir(own) and not os.path.islink(own) else None
        write = [r for r in (_real_dir(p, ["~/.cache", "~/Library/Caches"], strict=True) for p in extra.get(name, [])) if r] + memory
        cache = _real_dir(f"{caches}/{name}", [caches], strict=True, create=True)
        ok = [r for r in real if r]
        data = role_settings(ok, own_real, write, cache, any(ssh_remote(r) for r in ok), deny, compact, guard)
        if name == "metis-pantheon":
            # навык new-direction (metis-0042): `pantheon direction init` создаёт ~/projects/<новое> — вне папок окна
            # Метиды, в песочнице упал бы. Мимо неё — только эта подкоманда и только у Метиды; ворота у команды свои:
            # галочка владельца в журнале доски owner-log, который пишет тик, — роли её не подделают.
            data["sandbox"]["excludedCommands"].append("pantheon direction init *")
        if allow:
            data.setdefault("permissions", {}).setdefault("allow", []).extend(allow)
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

    built = []
    for name, folders in domains.items():
        one(name, folders, os.path.join(PANTHEON, "directions", name), COORDINATOR_COMPACT,
            [] if name in private_dirs else private_paths, COORDINATOR_ALLOW)
        built.append(name)
    # мастерская пишет в папку запуска (~/projects/workshop/<задача>) и в workshop/ доски
    one("workshop", ["~/projects/workshop"], os.path.join(PANTHEON, "workshop"), None, private_paths)
    # местные порты мастерской закрыты: на macOS allowLocalBinding открывает все порты 127.0.0.1, в том числе демон CDP
    # с входами владельца; браузеры владельца — только у роли Харон (решение владельца 15.10, отмена metis-0053)
    built.append("workshop")
    # штаб (SEC-26, вариант А): Зевс пишет только в ~/ai/pantheon, кроме .git и alerts.md; сеть закрыта (в веб он не
    # ходит, SEC-13); мимо песочницы — только `pantheon start|wake|alert`: запуск сессий и тревоги. Личное ему открыто
    # (SEC-11), кроме ключей git-crypt.
    hq_cache = _real_dir(f"{caches}/hq", [caches], strict=True, create=True)
    root = os.path.realpath(PANTHEON)
    keys = [p for p in private_paths if "/.git/git-crypt" in p + "/"]  # ключи — не штабу: ~/ai/pantheon коммитит тик
    hq = role_settings([root], None, memory, hq_cache, False, keys, None, guard)
    hq["sandbox"]["excludedCommands"] = list(HQ_EXCLUDED)
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
    closed = HQ_CLOSED_DIRS + [f"{caches}/{n}" for n in sorted(cache_dirs)]
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
    return data if isinstance(data, list) else data.get("agents") if isinstance(data, dict) else None


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
    """Живые сессии с этим именем и его копии. Живая — работает (working), ждёт (blocked), открыта во вкладке (нет
    state) или закончила ход с живым процессом (done и pid — такую новый запуск останавливает сам, CTX-10, поэтому
    здесь её нет). Остановленная (stopped, claude stop), упавшая (failed) и закрытая (done без процесса) имени не держат
    (15.10: claude agents даёт после claude stop именно stopped, metis-0041). Плюс интерактивные вкладки из реестра
    ~/.claude/sessions, которых нет в claude agents."""
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
            return 1, None
        why = recheck() if recheck else None
        if why:
            start_log(f"resume-skip\t{name}\t{a.get('id')}\t{origin}\t{why}")
            return 1, None
        return _resume_session(name, a, text, origin)


def _resume_session(name, a, text, origin):
    target, rest = (("workshop", [name[len("daedalus-"):]]) if name.startswith("daedalus-") else (name, []))
    got = start_target(target, rest)
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        print(f"[resume] {name} {a.get('id')} {origin}")
        return 0, None
    run = run_settings(name, got[1], got[3], origin) if not isinstance(got, str) else None
    sid = a.get("sessionId")
    if not str(text).startswith(START_MARK):
        text = f"{START_MARK} поручение от {origin}] {text}"
    pushed = push_text(sid, text) if a.get("id") else None
    if pushed:  # без текста respawn поднял бы сессию молча — тогда сразу запасной путь, он текст передаёт
        r = subprocess.run([claude_bin(), "respawn", a["id"]], capture_output=True, text=True, timeout=180)
        start_log(f"respawn\t{name}\t{a['id']}\t{origin}\t{r.returncode}")
        if r.returncode == 0:
            return 0, None
        with contextlib.suppress(OSError):
            os.remove(pushed)
    argv = [claude_bin(), "--resume", sid or a.get("id"), "--bg", "--name", name] + (["--settings", run] if run else []) \
        + [text]
    r = subprocess.run(argv, cwd=a.get("cwd") or HOME, capture_output=True, text=True, timeout=180)
    m = COPY_NOTE.search((r.stdout or "") + (r.stderr or ""))
    start_log(f"resume\t{name}\t{a.get('id')}\t{origin}\t{r.returncode}" + (f"\tcopy {m.group(1)}" if m else ""))
    if m:
        alert(f"{name}: --resume сделал копию {m.group(1)} — исходная сессия {a.get('id')} ещё числится живой; проверить "
              f"claude agents, лишнюю остановить", "pantheon")
    return r.returncode, (m.group(1) if m else None)


def copies_message(name, live):
    tab = [a for a in live if not a.get("id")]
    if tab:
        return (f"{name} открыта во вкладке терминала (pid {tab[0].get('pid')}) — перейдите в неё или закройте её и "
                "запустите снова")
    ids = ", ".join(f"{a.get('name')} {a['id']} ({a.get('state')})" for a in live)
    return (f"{name} уже работает: {ids}. Поручение — сообщением ей (SendMessage, адрес {name}) или claude attach "
            f"{live[0]['id']}; начать заново — тот же запуск с --restart")


def stop_copies(name, live):
    for a in live:
        subprocess.run([claude_bin(), "stop", a["id"]], capture_output=True, text=True, timeout=60)
        start_log(f"stop-restart\t{name}\t{a.get('name')}\t{a['id']}")


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


def start(rest):
    """pantheon start <направление> [поручение] | workshop <задача> [поручение] | zeus [--restart]  [--from кто] [--dry-run]"""
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
            print("нет окна штаба — сначала pantheon domains build", file=sys.stderr)
            return 1
        if not sys.stdin.isatty():
            print("штаб запускается в вашем терминале: pantheon start zeus", file=sys.stderr)
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
    if live and not dry:
        stop_copies(name, live)
    # CTX-10: эпик закончен — сессия «done» ещё висит в списке; новый эпик — новая сессия с тем же именем, а старая
    # останавливается (переписка сохраняется: claude attach <id>), иначе Claude Code назовёт новую «имя (2)»
    for a in same:
        if a.get("state") == "done" and a.get("pid") and not dry:
            subprocess.run([claude_bin(), "stop", a.get("id")], capture_output=True, text=True, timeout=60)
            start_log(f"stop-done\t{name}\t{a.get('id')}")
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
    run_settings(name, role, window, origin)
    r = subprocess.run(argv, cwd=folder, capture_output=True, text=True, timeout=180)
    start_log(f"{name}\t{origin}\t{folder}\t{r.returncode}")
    if origin == "zeus" and r.returncode == 0 and not owner_spoke_recently("zeus", OWNER_WORD_WINDOW):
        alert(f"запуск {name} по поручению Зевса без вашего слова в его окне за {OWNER_WORD_WINDOW // 60} мин — "
              "возможно, по сообщению другой сессии (лазейка на время доработки, decisions.md 15.10)", "pantheon-start")
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


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


def wake_recheck(name):
    """Под блокировкой имени перед подъёмом: метка, пауза, техперезапуск, живая копия «имя (2)» (ревью argus)."""
    if os.path.exists(path("stopped", name)):
        return "остановлено вами"
    if load_pause(name):
        return "пауза по нагрузке"
    if maintenance_active():
        return "технический перезапуск"
    if live_copies(name, agents_all() or []):
        return "уже работает"
    return None


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
    done = 0
    for a in agents:
        name, state = a.get("name") or "", a.get("state")
        if state not in ("failed", "stopped") or not (name in domains or name.startswith("daedalus-")):
            continue
        if os.path.exists(path("stopped", name)) or load_pause(name):
            continue
        newer = [b for b in agents if b.get("name") == name and (b.get("startedAt") or 0) > (a.get("startedAt") or 0)]
        if newer:
            continue  # эпик уже продолжен новой сессией с тем же именем
        tasks = open_tasks(name)
        if not tasks:
            continue
        print(f"{'будет поднята' if dry else 'поднимаю'}: {name} ({a.get('id')}, {state}) — задачи {', '.join(tasks[:3])}")
        if dry:
            continue
        rc, _ = resume_session(name, a, WAKE_TEXT, "wake", recheck=lambda n=name: wake_recheck(n))
        if rc:
            alert(f"pantheon wake: {name} не поднялась (код {rc})", "pantheon")
        done += 1
    if not done:
        print("будить некого")
    return 0


# --- роли (ROLE-15, ROLE-16, ROLE-17) -------------------------------------------------------
# Источник ролей — шаблоны ~/.claude/agents/<роль>.tmpl и общие части ~/.claude/agents/_parts/<часть>.part (их
# синхронизирует claude-config; правит только metis-pantheon — guard protect-config). Сборка кладёт рядом <роль>.md —
# то, что читает Claude Code; собранные файлы claude-config не синхронизирует (строки в ~/.claude/.gitignore): на каждом
# Mac их собирает тик вместе с domains.json, когда меняется шаблон, часть или реестр.
#   {{> часть}}         — текст части (одна общая формулировка: отчёт, находка, внешние действия, доведение до конца);
#   hephaestus, apollo  — роли лидов: по одной на направление с этим лидом в поле leads реестра,
#                         hephaestus-<коротко> (athena-broker → broker), подстановки {{direction}} {{short}}
#                         {{project}} {{folders}}.
# Свой файл узнаётся по строке-метке после шапки; файл без метки (свой ли, чужой ли) сборка не трогает, собранный файл
# без шаблона — убирает. Ошибка в шаблоне (нет части, осталась {{…}}) — роль не пишется, старая версия остаётся.
AGENTS = os.path.join(HOME, ".claude", "agents")
PARTS = os.path.join(AGENTS, "_parts")
LEAD_ROLES = ("hephaestus", "apollo")
ROLE_MARK = "<!-- собрано pantheon roles build из {tmpl} — правят шаблон, а не этот файл -->"
ROLE_NAME = re.compile(r"[a-z][a-z0-9-]{0,40}")
# значения из реестра в шаблон лида: одна строка без разметки YAML. Реестр может править штаб из песочницы, а шапка
# роли (hooks, mcpServers) запускает команды вне её — перевод строки в project дописал бы в шапку хук (проверка
# безопасности 15.10). Сверх образца — сверка ключей шапки до и после подстановки.
ROLE_PROJECT = re.compile(r"[\w][\w .,()«»+-]{0,59}")
ROLE_FOLDER = re.compile(r"~?/[\w.-]+(?:/[\w.-]+)*")


def _head_keys(text):
    end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
    return [ln.split(":", 1)[0] for ln in text[4:end].splitlines() if re.match(r"[A-Za-z_]", ln)] if end > 0 else None


def _role_text(tmpl_text):
    def part(m):
        p = os.path.join(PARTS, m.group(1) + ".part")
        if not ROLE_NAME.fullmatch(m.group(1)) or not os.path.isfile(p):
            raise ValueError(f"нет части {m.group(1)}")
        return open(p, encoding="utf-8").read().rstrip("\n")
    return re.sub(r"\{\{>\s*([\w-]+)\s*\}\}", part, tmpl_text)


def _marked(text, tmpl):
    """Метка — сразу после шапки YAML: файл роли должен начинаться с ---."""
    end = text.find("\n---\n", 3) if text.startswith("---\n") else -1
    if end < 0:
        raise ValueError("нет шапки YAML (--- … ---)")
    return text[:end + 5] + ROLE_MARK.format(tmpl=tmpl) + "\n" + text[end + 5:]


def roles_build():
    with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
        reg = tomllib.load(fh)
    want, errors = {}, []
    tmpls = sorted(f for f in os.listdir(AGENTS) if f.endswith(".tmpl")) if os.path.isdir(AGENTS) else []
    for f in tmpls:
        base = f[:-5]
        if not ROLE_NAME.fullmatch(base):
            errors.append(f"{f}: имя не по образцу")
            continue
        try:
            text = _role_text(open(os.path.join(AGENTS, f), encoding="utf-8").read())
        except (OSError, ValueError) as e:
            errors.append(f"{f}: {e}")
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
                errors.append(f"{f} → {base}-{short}.md: project или folders направления {name} не по образцу")
                continue
            out_text = (text.replace("{{direction}}", name).replace("{{short}}", short)
                        .replace("{{project}}", project).replace("{{folders}}", ", ".join(folders)))
            if _head_keys(out_text) != _head_keys(text):
                errors.append(f"{f} → {base}-{short}.md: подстановка поменяла шапку роли")
                continue
            want[f"{base}-{short}.md"] = (f, out_text)
    made = []
    for fname, (tmpl, text) in sorted(want.items()):
        out = os.path.join(AGENTS, fname)
        try:
            if "{{" in text:
                raise ValueError("осталась подстановка {{…}}")
            text = _marked(text, tmpl)
        except ValueError as e:
            errors.append(f"{tmpl} → {fname}: {e}")
            continue
        old = open(out, encoding="utf-8").read() if os.path.exists(out) else None
        if old is not None and "pantheon roles build" not in old[:2000]:
            errors.append(f"{fname} есть и написан не сборкой — не трогаю (убрать его или шаблон {tmpl})")
            continue
        if old != text:
            write_atomic(out, text)
            made.append(fname)
    for f in sorted(os.listdir(AGENTS)) if os.path.isdir(AGENTS) else []:
        p = os.path.join(AGENTS, f)
        if f.endswith(".md") and f not in want and not os.path.islink(p) and os.path.isfile(p):
            if "pantheon roles build" in open(p, encoding="utf-8").read(2000):
                os.remove(p)
                made.append(f"-{f}")
    for e in errors:
        print(f"roles build: {e}", file=sys.stderr)
    if errors:
        alert_once("roles-build", "\n".join(errors), f"pantheon roles build: {errors[0]}"
                   + (f" (и ещё {len(errors) - 1})" if len(errors) > 1 else ""), "pantheon")
    return made


def roles_newest():
    files = [os.path.join(PANTHEON, "directions.toml")]
    for d in (AGENTS, PARTS):
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
# Пишет только команда владельца `pantheon approve` (роли и штаб её запустить не могут — guard). Мастерская читает этот
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
    add(DIRECTION_NAME.fullmatch(name) and len(name) <= 40,
        f"имя «{name}» по образцу <бог>-<проект>: латиница, цифры, дефис, до 40 знаков")
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
    try:
        names = open(os.path.join(PARTS, "names.part"), encoding="utf-8").read()
    except OSError:
        names = ""
    add(f"({name})" in names, f"бог направления ({god}) и его род — в _parts/names.part")
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
    except OSError:
        text = ""
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
        board_lines = open(path("owner-log", "board.jsonl"), encoding="utf-8").read().splitlines()
    except OSError:
        board_lines = []
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
    print(f"Ответы владельца на {qid} (журналы пишут хук и тик, не роли; сверь, что ответ — на твой вопрос и твоё действие):")
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
    build_app()
    uid = os.getuid()
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
    subprocess.run(["plutil", "-replace", "CFBundleIdentifier", "-string", "com.latark.pantheon-board", plist],
                   capture_output=True)
    if not _notifier():
        print("для уведомлений с переходом в карточку: brew install terminal-notifier", file=sys.stderr)
    subprocess.run(["codesign", "--force", "--sign", "-", APP], capture_output=True)


def uninstall():
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    agents = os.path.dirname(PLIST)
    with contextlib.suppress(OSError):
        for f in os.listdir(agents):
            if f.startswith(SVC_PREFIX) and f.endswith(".plist"):
                subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{f[:-6]}"], capture_output=True)
                os.remove(os.path.join(agents, f))
    for p in (PLIST, os.path.join(HOME, ".local", "bin", "pantheon"), os.path.join(HOME, ".local", "bin", "heavy")):
        with contextlib.suppress(FileNotFoundError):
            os.remove(p)
    print("снято: задачи launchd (тик и службы) и команды pantheon и heavy (метки в ~/.local/state/pantheon остались)")
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
SYNC_ACT = {"Отправить на другие Mac", "Откатить правку", "Всё в порядке — правка наша", "Откатить на всех Mac"}


def sync_answers():
    owner_log = os.path.join(STATE, "owner-log", "board.jsonl")
    waiting = []
    for held in (".sync-held", ".sync-incoming"):
        try:
            text = open(os.path.join(SYNC_DIR, held), encoding="utf-8").read()
        except OSError:
            continue
        m = re.search(r"^task=(\S+)$", text, re.M)
        if m:
            waiting.append(m.group(1))
    if not waiting or not os.path.exists(owner_log):
        return 0
    last = {}
    for line in open(owner_log, encoding="utf-8"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("kind") == "answer" and d.get("id") in waiting:
            last[d["id"]] = d.get("answer") or ""
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


def board():
    """Доска владельца: ходы → задачи и журнал владельца, карточки ← задачи. Только на этом Mac, под блокировкой."""
    T = tasks_mod()
    sched = load_schedule()
    primary = not sched.get("primary_host") or sched.get("primary_host") == host()
    with lock("board", block=False) as got:
        if not got:
            return 0
        try:
            with open(os.path.join(PANTHEON, "directions.toml"), "rb") as fh:
                projects = {d.get("name"): d.get("project") for d in tomllib.load(fh).get("direction") or []}
        except (OSError, ValueError):
            projects = {}
        # политика уведомлений — под своей блокировкой на весь проход: сбои из run-job ждут, а не теряются
        with lock("notify"):
            pol = notify_policy(sched)
            lines = T.board_sync(PANTHEON, BOARD, path("board.json"), path("owner-log", "board.jsonl"), now(),
                                 alert=lambda k, v, text, who="board", note=None: alert_once(k, v, text, who, note,
                                                                                            policy=pol),
                                 primary=primary, projects=projects, policy=pol)
            pol.save()
        once_dir = path("once")  # отметки «уже сообщали» старше 90 дней — убрать: папка не растёт без конца
        for f in os.listdir(once_dir) if os.path.isdir(once_dir) else []:
            fp = os.path.join(once_dir, f)
            if now() - os.path.getmtime(fp) > 90 * 86400:
                os.remove(fp)
    for ln in lines:
        print(ln)
    return 0


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
    if not quiet or bad:
        print(f"задач: {n}, с ошибками: {len(bad)}, без шапки: {noheader}")
    if quiet:  # тик: одна тревога на набор проблем, а не сбой задачи каждые 5 минут
        if bad:
            alert_once("check-problems", ",".join(sorted(f for f, _, _ in bad)),
                       f"задачи с битой шапкой: {len(bad)} — список в Доска/Проблемы.md", "check")
        else:
            clear_once("check-problems")
        return 0
    return 1 if bad else 0


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
                      "waiting_on": opt("--waiting-on"), "question": opt("--question"), "why": opt("--why"),
                      "recommend": opt("--recommend"), "if_no_answer": opt("--if-no-answer"),
                      "options": opt("--option", True) or None, "depends_on": opt("--depends-on", True) or None,
                      "risky": True if "--risky" in args else None}
            if not opt("--direction") or not opt("--title"):
                print("pantheon task new: нужны --direction и --title", file=sys.stderr)
                return 2
            if opt("--direction") == "inbox":
                print("pantheon task new: входящие создаёт только доска владельца; Зевс заводит задачу сразу в направлении",
                      file=sys.stderr)
                return 2
            tid, p = T.task_new(PANTHEON, now(), opt("--direction"), opt("--title"), project=opt("--project"),
                                text=opt("--text"), **fields)
            print(f"{tid} {os.path.relpath(p, PANTHEON)}")
        elif sub == "set" and args:
            tid, changes, note, i = args[0], {}, None, 1
            while i < len(args):
                if args[i] == "--note" and i + 1 < len(args):
                    note, i = args[i + 1], i + 2
                    continue
                if args[i] == "--option" and i + 1 < len(args):  # варианты с запятыми и кавычками (metis-0037)
                    changes["options"] = (changes.get("options") or []) + [args[i + 1]]  # и после options= (argus)
                    i += 2
                    continue
                k, eq, v = args[i].partition("=")
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
                i += 1
            p, head = T.task_set(PANTHEON, now(), tid, changes, note=note)
            print(f"{tid}: {head.get('status')} · {os.path.relpath(p, PANTHEON)}")
        elif sub == "show" and args:
            tasks = T.load_tasks(PANTHEON)
            if args[0] not in tasks:
                print(f"нет задачи {args[0]}", file=sys.stderr)
                return 1
            print(open(tasks[args[0]][0], encoding="utf-8").read())
            words = T.owner_words(path("owner-log", "board.jsonl"), args[0])
            print("## Слова владельца (журнал владельца — только это подтверждает его решение)\n")
            for w in words or [{"time": "—", "kind": "нет записей"}]:
                print(f"- {w.get('time', '')[:16].replace('T', ' ')} · {w.get('kind')} · "
                      f"{w.get('dst') or w.get('answer') or w.get('text') or w.get('title') or ''}")
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
        alert(f"обновлён {name} {old} → {new}, сессии увидят после перезапуска", "plugins-update")
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
        pythons = _test_pythons()
        with open(log, "w", encoding="utf-8") as fh:
            fh.write(f"{stamp()} {name}: новая {new} из {src} (хеш {digest}), база {old} из "
                     f"{base_dir and base or '—'}; python: {', '.join(pythons)}\n")
            got_new = _run_plugin_tests(new_dir, pythons, tmp, fh, f"новая {new}", deadline)
            fresh = got_new - _run_plugin_tests(base_dir, pythons, tmp, fh, f"база {old}", deadline)
            for k, n in got_new.items():  # не успевшее у новой не гасится тем, что не успело и у базы
                if k[2].endswith(": срок прогона"):
                    fresh[k] = n
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


# --- review: записи для запора слияния guard (P1-4, guard 0.5.4) -------------------------------------------------
# Сама команда ничего не пишет: журнал STATE/merge-gate/records.jsonl пишет хук guard на PostToolUse по успешной
# простой команде `pantheon review …` и по agent_type сессии (accept, reject — argus, talos — talos). Поэтому
# запись нельзя сделать текстом команды от чужой роли, а сама команда только проверяет условия и формат.
REVIEW_SHA = re.compile(r"[0-9a-f]{40}")
REVIEW_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
REVIEW_PR = re.compile(r"[1-9][0-9]{0,8}")
REVIEW_USAGE = ("pantheon review test -- <команда…> | accept|reject|talos <owner/repo> <PR> <SHA 40 знаков> | "
                "status [<owner/repo> <PR>]")


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
    """Записи журнала запора (битые строки пропускаются); файл — симлинк или не читается — пусто."""
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


def review_cmd(rest):
    sub = rest[0] if rest else ""
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
        args = rest[1:]
        if len(args) != 3 or not REVIEW_REPO.fullmatch(args[0]) or not REVIEW_PR.fullmatch(args[1]) \
                or not REVIEW_SHA.fullmatch(args[2].lower()):
            print(f"pantheon review {sub} <owner/repo> <номер PR> <SHA 40 знаков> — аргументы не в этом формате "
                  "(SHA — полный: gh pr view N --json headRefOid)", file=sys.stderr)
            return 2
        who = "argus" if sub != "talos" else "talos"
        print(f"pantheon review {sub}: {args[0].lower()}#{args[1]} @ {args[2].lower()} — записано хуком guard, "
              f"если роль подходит ({who})")
        return 0
    if sub == "status":
        args = rest[1:]
        if args and (len(args) != 2 or not REVIEW_REPO.fullmatch(args[0]) or not REVIEW_PR.fullmatch(args[1])):
            print("pantheon review status [<owner/repo> <номер PR>]", file=sys.stderr)
            return 2
        recs = review_records(args[0] if args else None, int(args[1]) if args else None)
        if not recs:
            print("pantheon review status: записей нет")
        for r in recs:
            by = r.get("by") if isinstance(r.get("by"), dict) else {}
            pr = f"#{r['pr']}" if r.get("pr") else ""
            print(f"{r.get('time', '?')}  {r.get('kind', '?'):<6}  {','.join(map(str, r['repo']))}{pr}  "
                  f"{str(r.get('sha', ''))[:12]}  {by.get('agent_type') or '—'}")
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
    if cmd == "start":
        return start(rest)
    if cmd == "wake":
        if rest and not rest[0].startswith("-"):
            return watch_cmd("wake", rest)
        return wake(rest)
    if cmd == "roles" and rest[:1] == ["build"]:
        made = roles_build()
        print(f"роли: {', '.join(made) if made else 'без изменений'}")
        return 0
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
