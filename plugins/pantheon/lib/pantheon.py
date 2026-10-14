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
  pantheon alert "<строка>" [--from кто]   дописать строку в ~/ai/pantheon/alerts.md
  pantheon archive                      «Сделано» доски старше 7 дней и тревоги старше 30 — в archive/
  pantheon domains build                ~/ai/pantheon/directions.toml → ~/.local/state/pantheon/domains.json
                                        и настройки окон ролей с песочницей …/settings/<направление>.json
  pantheon view [--quiet]               обновить копию ~/ai/pantheon-view для Obsidian
  pantheon board                        доска владельца ~/ai/pantheon-view/Доска: карточки, ваши ходы, сводка
  pantheon check [файл…]                проверить шапки задач по схеме v1 (schema.md)
  pantheon task new --direction D --title T [--status S --priority N --due ГГГГ-ММ-ДД --next X --owner O
                    --project P --waiting-on W --question Q --option A --option B --depends-on ID]
  pantheon task set ID поле=значение … [--note "строка в журнал"]   pantheon task show ID
  pantheon task ready [--direction D] [--owner O]   pantheon task claim ID --by КТО [--hours 1]
  pantheon commit                       commit → pull без rebase → push ~/ai/pantheon
  pantheon install | uninstall          поставить или снять задачу launchd com.latark.pantheon-tick
  pantheon tick                         один проход планировщика (его вызывает launchd)
Для синтетических тестов: PANTHEON_HOME, PANTHEON_STATE, PANTHEON_NOW, PANTHEON_HOST,
PANTHEON_FAKE_WAKE, PANTHEON_FAKE_AC, PANTHEON_FAKE_IDLE, PANTHEON_FAKE_LIMIT, PANTHEON_DRYRUN,
PANTHEON_NO_NOTIFY.
"""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
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
    jobs = []
    for j in sched.get("job") or []:
        if isinstance(j, dict) and JOB_NAME.fullmatch(str(j.get("name", ""))):
            jobs.append(j)
        else:
            sched.setdefault("bad_names", []).append(str(j.get("name") if isinstance(j, dict) else j))
    sched["job"] = jobs
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


def alert_once(key, value, text, who="pantheon", note=None):
    """Тревога (и уведомление note) один раз на значение value: повтор того же состояния молчит."""
    mark = once_path(key)
    try:
        if open(mark).read() == str(value):
            return
    except OSError:
        pass
    alert(text, who)
    if note:
        notify(note)
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
TICK_SUBCOMMANDS = {"view", "commit", "domains", "watch", "revisits", "scout", "board", "check"}
CLAUDE_VALUE_FLAGS = {"--agent", "--model", "--max-turns", "--name"}


def parse_command(cmd):
    """Команда задачи из schedule.toml → argv без оболочки, или None (задача не идёт). Разрешено только:
      pantheon <view|commit|domains|watch|revisits|scout> [аргументы без спецсимволов];
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


def notify(text, title="Пантеон"):
    if os.environ.get("PANTHEON_NO_NOTIFY") or os.environ.get("PANTHEON_DRYRUN") == "1":
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
    d = sched["defaults"]
    if overdue:
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
            alert_once("badname-" + re.sub(r"[^\w-]", "_", bad)[:40], bad, f"schedule.toml: задача с именем не по образцу "
                       f"({bad[:60]!r}; только a-z, 0-9, дефис) — пропущена", "pantheon-tick")
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
                notify(f"Задача {name} на паузе: аренда истекла")
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
                    notify(f"Задача {name} упала (код {rc})")
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
    job = next((j for j in sched.get("job") or [] if j["name"] == name), None)
    if not job:
        print(f"нет задачи {name}; список — pantheon jobs", file=sys.stderr)
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
        newest = max((os.path.getmtime(p) for p in (reg_path, policy_path) if os.path.exists(p)), default=0)
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
    domains = {}
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
    write_json(path("domains.json"), {
        "_comment": "Собрано `pantheon domains build` из ~/ai/pantheon/directions.toml. Руками не править.",
        "built": stamp(), "built_ts": now(), "domains": domains})
    built = sandbox_build(domains, policy_path)
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
# Хранилище pnpm не подменяется: node_modules помнит своё хранилище, и разные хранилища у координатора и ваших
# сессий в одной папке ломают pnpm («Unexpected store location»). Общее хранилище направления — store-dir в
# .npmrc внутри папки направления (решается при запуске координатора, SEC-19).
# Координаторам там же — окно сжатия 200k (CTX-04).
SANDBOX_ROOTS = ["~/projects", "~/ai/knowledge"]   # папки направлений для песочницы — только внутри этих
SANDBOX_DOMAINS = ["registry.npmjs.org", "registry.yarnpkg.com", "pypi.org", "files.pythonhosted.org",
                   "github.com", "api.github.com", "codeload.github.com", "objects.githubusercontent.com",
                   "raw.githubusercontent.com"]
# Мимо песочницы: gh (в ней не работает — TLS Go на macOS) — только эти подкоманды; дописать тревогу
SANDBOX_EXCLUDED = ["gh pr *", "gh issue *", "gh run *", "gh repo view *", "gh api *", "gh auth status",
                    "pantheon alert *"]
# git по SSH в песочнице macOS не работает: у направлений с таким remote сетевые команды git — мимо неё
GIT_NETWORK = ["git push", "git push *", "git fetch", "git fetch *", "git pull", "git pull *"]
COORDINATOR_COMPACT = 200000


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


def _deny_forms(paths):
    """Запрет и в виде «~/…», и настоящим путём: правила разрешений — настоящие пути, запреты должны совпасть."""
    out = []
    for p in paths:
        for x in (p, os.path.realpath(os.path.expanduser(p))):
            if x not in out:
                out.append(x)
    return out


def role_settings(folders, own_dir, extra_write, cache, ssh, deny_read, compact=None):
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
                "denyRead": _deny_forms(deny_read),
            },
            "network": {"allowedDomains": SANDBOX_DOMAINS},
        },
    }
    if compact:
        data["autoCompactWindow"] = compact
    return data


def sandbox_build(domains, policy_path):
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
    os.makedirs(out_dir, exist_ok=True)

    def one(name, folders, own, compact, deny):
        real = [_real_dir(f, SANDBOX_ROOTS[:1], strict=True) or _real_dir(f, SANDBOX_ROOTS[1:]) for f in folders]
        skipped = [f for f, r in zip(folders, real) if not r]
        if skipped:
            print(f"песочница {name}: вне ~/projects и ~/ai/knowledge, ссылка или нет папки — только через Write/Edit: "
                  f"{skipped}", file=sys.stderr)
        own_real = os.path.realpath(own) if os.path.isdir(own) and not os.path.islink(own) else None
        write = [r for r in (_real_dir(p, ["~/.cache", "~/Library/Caches"], strict=True) for p in extra.get(name, [])) if r]
        cache = _real_dir(f"{caches}/{name}", [caches], strict=True, create=True)
        ok = [r for r in real if r]
        write_json(os.path.join(out_dir, name + ".json"),
                   role_settings(ok, own_real, write, cache, any(ssh_remote(r) for r in ok), deny, compact))

    built = []
    for name, folders in domains.items():
        one(name, folders, os.path.join(PANTHEON, "directions", name), COORDINATOR_COMPACT,
            [] if name in private_dirs else private_paths)
        built.append(name)
    # мастерская пишет в папку запуска (~/projects/workshop/<задача>) и в workshop/ доски
    one("workshop", ["~/projects/workshop"], os.path.join(PANTHEON, "workshop"), None, private_paths)
    built.append("workshop")
    for f in os.listdir(out_dir):
        if f.endswith(".json") and f[:-5] not in built:
            os.remove(os.path.join(out_dir, f))
    return built


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
    link = os.path.join(HOME, ".local", "bin", "pantheon")
    os.makedirs(os.path.dirname(link), exist_ok=True)
    if os.path.islink(link) or os.path.exists(link):
        os.remove(link)
    os.symlink(os.path.join(CURRENT, "bin", "pantheon"), link)
    if os.path.isdir(os.path.join(PANTHEON, ".git")):
        merge = os.path.join(CURRENT, "scripts", "git-crypt-merge.sh")
        git("config", "merge.gitcrypt-text.name", "git-crypt text merge")
        git("config", "merge.gitcrypt-text.driver", f"{merge} %O %A %B")
        git("config", "merge.gitcrypt-union.name", "git-crypt union merge (дописываемые файлы)")
        git("config", "merge.gitcrypt-union.driver", f"{merge} --union %O %A %B")
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", PLIST], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr.strip(), file=sys.stderr)
        return r.returncode
    print(f"установлено: {PLIST.replace(HOME, '~')} и команда {link.replace(HOME, '~')} → "
          f"{CURRENT.replace(HOME, '~')} → {PLUGIN.replace(HOME, '~')}")
    return 0


def uninstall():
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    for p in (PLIST, os.path.join(HOME, ".local", "bin", "pantheon")):
        with contextlib.suppress(FileNotFoundError):
            os.remove(p)
    print("снято: задача launchd и команда pantheon (метки в ~/.local/state/pantheon остались)")
    return 0


_TASKS = None


def tasks_mod():
    """lib/tasks.py — схема задач и доска владельца (python3 -I не кладёт папку скрипта в путь импорта)."""
    global _TASKS
    if _TASKS is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("pantheon_tasks", os.path.join(LIB, "tasks.py"))
        _TASKS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_TASKS)
    return _TASKS


BOARD = os.path.join(VIEW, "Доска")


def board():
    """Доска владельца: ходы → задачи и журнал владельца, карточки ← задачи. Только на этом Mac, под блокировкой."""
    T = tasks_mod()
    sched = load_schedule()
    primary = not sched.get("primary_host") or sched.get("primary_host") == host()
    with lock("board", block=False) as got:
        if not got:
            return 0
        lines = T.board_sync(PANTHEON, BOARD, path("board.json"), path("owner-log", "board.jsonl"), now(),
                             alert=lambda k, v, text, who="board", note=None: alert_once(k, v, text, who, note),
                             notify=notify, primary=primary)
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
                      "waiting_on": opt("--waiting-on"), "question": opt("--question"),
                      "options": opt("--option", True) or None, "depends_on": opt("--depends-on", True) or None}
            if not opt("--direction") or not opt("--title"):
                print("pantheon task new: нужны --direction и --title", file=sys.stderr)
                return 2
            tid, p = T.task_new(PANTHEON, now(), opt("--direction"), opt("--title"), project=opt("--project"), **fields)
            print(f"{tid} {os.path.relpath(p, PANTHEON)}")
        elif sub == "set" and args:
            tid, changes, note, i = args[0], {}, None, 1
            while i < len(args):
                if args[i] == "--note" and i + 1 < len(args):
                    note, i = args[i + 1], i + 2
                    continue
                k, eq, v = args[i].partition("=")
                if not eq:
                    print(f"pantheon task set: «{args[i]}» — нужно поле=значение", file=sys.stderr)
                    return 2
                kind = T.FIELDS.get(k, ("str",))[0]
                changes[k] = None if v in ("", "null") else int(v) if kind == "int" else \
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
        elif sub == "ready":
            for tid, h in T.ready(PANTHEON, now(), opt("--direction"), opt("--owner")):
                print(f"{tid}\t{T.PRIORITY.get(h.get('priority', 2), '')}\t{h.get('due') or '—'}\t{h.get('title')}")
        elif sub == "claim" and args and opt("--by"):
            until = T.now_iso(now() + 3600 * float(opt("--hours") or 1))
            tasks = T.load_tasks(PANTHEON)
            h = tasks.get(args[0], (None, {}, None))[1]
            if h.get("claimed_by") not in (None, opt("--by")) and (h.get("claimed_until") or "") > T.now_iso(now()):
                print(f"{args[0]} уже взята: {h['claimed_by']} до {h['claimed_until']}", file=sys.stderr)
                return 1
            T.task_set(PANTHEON, now(), args[0], {"claimed_by": opt("--by"), "claimed_until": until,
                                                  "status": "doing" if h.get("status") == "todo" else h.get("status")},
                       note=f"взял {opt('--by')} до {until[11:16]}")
            print(f"{args[0]}: взята {opt('--by')} до {until}")
        else:
            print(f"pantheon task: не понял «{' '.join(rest)}»", file=sys.stderr)
            return 2
    except ValueError as e:
        print(f"pantheon task: {e}", file=sys.stderr)
        return 1
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
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
        if not " ".join(rest).strip():
            print("pantheon alert: пустая строка", file=sys.stderr)
            return 2
        alert(" ".join(rest), who)
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
    if cmd == "check":
        return check([a for a in rest if not a.startswith("-")] or None, quiet="--quiet" in rest)
    if cmd == "task":
        return task_cmd(rest)
    if cmd == "install":
        return install()
    if cmd == "uninstall":
        return uninstall()
    print(f"pantheon: не понял «{' '.join(argv)}». Справка — pantheon help", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
