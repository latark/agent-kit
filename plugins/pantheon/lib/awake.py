"""Ночной цикл Пантеона: запрет сна Mac, возобновление после недельного лимита, возобновление ждущих сессий
(metis-0126, 0127 п. 2, 0132).

Модуль зовёт дежурный (lib/watch.py, `pantheon watch` раз в 5 мин) тремя проверками, `pantheon status` — строкой
«Запрет сна Mac: …», `pantheon wake` — признаком «сессия спит на лимите». Подкоманда `pantheon reboot-reminder` —
напоминание перезагрузить Mac раз в неделю (пятница, после 09:30).

  запрет сна Mac
      свой `caffeinate -i -t <интервал дежурного + 120 с>` отдельной группой процессов; pid и срок — STATE/awake.json.
      Держать, пока есть работа; тик умер — caffeinate истекает сам.
  возобновление после недельного лимита
      сессия Пантеона стоит «rate limited · resets <время>»: после сброса + 10 мин — один `claude respawn` с толчком;
      перед ним шлюз запуска ночного модуля (night.gate("respawn")).
  возобновление ждущих сессий
      сессия направления «ждёт вас», а в его очереди есть задача todo без блокера — разбудить (night.gate("wake")),
      не чаще раза в час на сессию.

Без sudo и pmset на запись: только `caffeinate`, `pmset -g batt`, `sysctl`, `ps`.
"""
import contextlib
import os
import re
import signal
import subprocess
import time
from datetime import date, datetime, timedelta

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()


def set_core(mod):
    global P
    P = mod


CAFFEINATE = os.environ.get("PANTHEON_CAFFEINATE") or "/usr/bin/caffeinate"
HOLD_MARGIN = 120        # новый caffeinate, когда до конца старого осталось не больше
WATCH_DEFAULT = 300      # интервал дежурного по умолчанию, с
BATT_MIN = 30            # на батарее держим только при заряде выше
LIMIT_GRACE = 600        # после сброса лимита ждём ещё (и держим Mac), с
SOON = 1800              # «в ближайшие 30 мин» для задач расписания и самозапуска
WAKE_REPEAT = 3600       # возобновление ждущей сессии — не чаще раза в час на сессию
LIMIT_TRIES = 3          # попыток подъёма на один сброс (шлюз запуска отказал — не попытка)
REBOOT_AT = (9, 30)      # пятница, после этого времени напоминание можно слать
RESUME_LIMIT_TEXT = "[Пантеон: лимит сброшен] продолжай с файла состояния"
RESUME_TASK_TEXT = "[Пантеон: есть задача без блокера] возьми {tid} из очереди"

LIMIT_WORD = re.compile(r"rate.?limit|limit", re.I)
RESETS = re.compile(r"resets?\s+(?:(?:on\s+)?([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(?:at\s+)?)?"
                    r"(\d{1,2})(?::(\d{2}))?\s*([ap]m)", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                          "dec"))}
BLOCKER = re.compile(r"владелец:\s*([^\n]*)", re.I)
TASK_ID = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*-\d{3,5}")


# --- общее ---------------------------------------------------------------------------

def marks_path():
    return P.path("awake-marks.json")


def read_marks():
    m = P.read_json(marks_path(), {})
    return m if isinstance(m, dict) else {}


def hhmm(t):
    return datetime.fromtimestamp(t).strftime("%H:%M")


def pantheon_name(name, doms):
    return bool(name) and (name in doms or name.startswith("daedalus-") or re.fullmatch(r"zeus(?:[- ].*)?", name)
                           is not None)


def session_state(a):
    """state.json сессии: ~/.claude/jobs/<короткий id>/state.json (его пишет Claude Code, мы только читаем)."""
    short = str(a.get("id") or str(a.get("sessionId") or "")[:8])
    if not re.fullmatch(r"[0-9a-zA-Z-]{4,64}", short):
        return {}
    d = P.read_json(os.path.join(P.HOME, ".claude", "jobs", short, "state.json"), {})
    return d if isinstance(d, dict) else {}


def parse_time(v):
    """updatedAt: ISO с Z или число (с или мс) → метка времени, иначе None."""
    if isinstance(v, (int, float)):
        return float(v) / 1000 if v > 1e11 else float(v)
    if isinstance(v, str) and v:
        with contextlib.suppress(ValueError):
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    return None


def night_mod():
    """lib/night.py — шлюз запуска ночного цикла. Файла нет — None: тогда шлюз запуска — отказ. Модуль берём у ядра (P.night_mod):
    один экземпляр с set_core на всех, а не вторая копия без ядра."""
    global _NIGHT
    if _NIGHT is not _UNSET:
        return _NIGHT
    mod = None
    p = os.path.join(P.LIB, "night.py")
    if os.path.isfile(p):
        mod = P.night_mod()
    _NIGHT = mod
    return mod


_UNSET = object()
_NIGHT = _UNSET


def gate(kind, t, agents=None, registry=None):
    """(можно ли, причина отказа). Шлюз запуска сломался или его нет — отказ, а не «можно»."""
    try:
        mod = night_mod()
    except Exception as e:  # noqa: BLE001
        return False, f"ночной модуль не загрузился ({type(e).__name__}: {str(e)[:100]})"
    if mod is None:
        return False, "ночной модуль не найден"
    try:
        ok, why = mod.gate(kind, t, agents=agents, registry=registry, heavy=None)
    except Exception as e:  # noqa: BLE001
        return False, f"шлюз запуска упал ({type(e).__name__}: {str(e)[:100]})"
    return bool(ok), why


def recheck(name):
    """Под блокировкой имени перед подъёмом: метка, пауза, техперезапуск. «Уже работает» тут не причина: сессия на
    лимите и ждущая «живы» для claude agents, их и будим."""
    if os.path.exists(P.path("stopped", name)):
        return "остановлено вами"
    if P.load_pause(name):
        return "пауза по нагрузке"
    if P.maintenance_active():
        return "технический перезапуск"
    return None


def scheduler_paused():
    return os.path.exists(P.path("paused")) or bool(P.load_pause("_all"))


# --- запрет сна Mac (0126) -----------------------------------------------------------------

def watch_interval():
    with contextlib.suppress(Exception):
        for j in P.load_schedule().get("job") or []:
            if j.get("name") == "watch" and j.get("every", "tick") != "tick":
                return float(j["every"]) * 60
    return float(WATCH_DEFAULT)


def batt_pct():
    """Заряд батареи, %: `pmset -g batt` (только чтение); None — нет батареи или не прочитать."""
    if os.environ.get("PANTHEON_FAKE_BATT") is not None:
        with contextlib.suppress(ValueError):
            return float(os.environ["PANTHEON_FAKE_BATT"])
        return None
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    m = re.search(r"(\d+)%", out)
    return float(m.group(1)) if m else None


def limit_info(a):
    """Сессия стоит на лимите: (время сброса, текст) или None. Признак — в state.json needs/detail «rate limited» и
    «resets <время>»; время сброса — ближайшее будущее относительно updatedAt (местное время)."""
    s = session_state(a)
    if a.get("state") != "blocked" and s.get("state") != "blocked":
        return None
    text = " ".join(str(x) for x in (s.get("needs"), s.get("detail"), a.get("waitingFor"), a.get("status")) if x)
    m = RESETS.search(text)
    if not m or not LIMIT_WORD.search(text):
        return None
    base = parse_time(s.get("updatedAt")) or parse_time(a.get("updatedAt")) or (a.get("startedAt") or 0) / 1000
    if not base:
        return None
    mon, day, hh, mi, ap = m.group(1), m.group(2), int(m.group(3)), int(m.group(4) or 0), m.group(5).lower()
    if not 1 <= hh <= 12:
        return None
    hh = hh % 12 + (12 if ap == "pm" else 0)
    b = datetime.fromtimestamp(base)
    try:
        if mon and mon[:3].lower() in MONTHS:
            cand = datetime(b.year, MONTHS[mon[:3].lower()], int(day), hh, mi)
            if cand.timestamp() <= base:
                cand = cand.replace(year=b.year + 1)
        else:
            cand = datetime(b.year, b.month, b.day, hh, mi)
            if cand.timestamp() <= base:
                cand += timedelta(days=1)
    except ValueError:
        return None
    return cand.timestamp(), text[:120]


def limit_sleeping(a, t=None):
    """Сессия на лимите, сброс которого уже прошёл — для `pantheon wake` она спящая. → время сброса или None."""
    li = limit_info(a)
    t = P.now() if t is None else t
    return li[0] if li and t >= li[0] else None


def jobs_soon(t):
    """Задача расписания, которая стартует в ближайшие 30 мин: тяжёлая или `claude -p …` (лёгкие pantheon-задачи каждые
    5 мин Mac не будят и проход дежурного — не причина держать). → название задачи или None."""
    try:
        sched = P.load_schedule()
    except (OSError, ValueError):
        return None
    me, primary = P.host(), sched.get("primary_host")
    for job in sched.get("job") or []:
        st = P.job_state(job["name"])
        if job.get("enabled") is False or st.get("disabled") or st.get("paused") or job.get("every", "tick") == "tick":
            continue
        if job.get("hosts", "all") == "primary" and me != primary:
            continue
        cmd = str(job.get("command") or "")
        if job.get("class", "light") != "heavy" and not cmd.startswith("claude "):
            continue
        if st.get("waiting"):
            continue
        _, due_at = P.due(job, st, t)
        if due_at - t <= SOON:
            return job["name"]
    return None


def autostart_soon(t):
    """Самозапуск направления в ближайшие 30 мин: autostart.json → next (не раньше и не позже окна), не «встал»."""
    for d, v in P.read_json(P.path("autostart.json"), {}).items():
        if isinstance(v, dict) and not v.get("gave_up"):
            with contextlib.suppress(TypeError, ValueError):
                nxt = float(v.get("next") or 0)
                if t < nxt <= t + SOON:
                    return d
    return None


def hold_reason(agents, doms, t):
    """Первая причина запретить сон Mac или None; вторым значением — причина отказа, если держать нельзя."""
    if scheduler_paused():
        return None, "планировщик на паузе"
    why = None
    for a in agents:
        name, state = a.get("name") or "", a.get("state")
        if not pantheon_name(name, doms) or state in ("stopped", "failed"):
            continue
        if os.path.exists(P.path("stopped", name)) or P.load_pause(name):
            continue
        s = session_state(a)
        fl = s.get("inFlight") if isinstance(s.get("inFlight"), dict) else {}
        li = limit_info(a)
        if li is not None:
            if t < li[0] + LIMIT_GRACE:
                why = why or f"{name} ждёт сброса лимита до {hhmm(li[0] + LIMIT_GRACE)}"
            continue
        if state == "working" or s.get("state") == "working":
            why = why or f"{name} работает"
        elif fl.get("tasks") or fl.get("queued"):
            why = why or f"у {name} идут фоновые субагенты или команды"
    if why:
        return why, None
    if RESUMED:
        return "поднята " + ", ".join(RESUMED), None
    job = jobs_soon(t)
    if job:
        return f"в ближайшие 30 мин задача расписания {job}", None
    d = autostart_soon(t)
    if d:
        return f"в ближайшие 30 мин самозапуск {d}", None
    return None, "все простаивают или ждут вас"


RESUMED = []  # кого этот проход уже поднял: его состояние в списке сессий устарело


def proc_comm(pid):
    """Имя команды процесса (`ps -p <pid> -o comm=`); пусто — процесса нет. Тесты подменяют эту функцию."""
    try:
        return subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def pid_is_ours(pid):
    """Живой процесс с этим pid — caffeinate (а не чужой, взявший pid после нас)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 1:
        return False
    out = proc_comm(pid)
    return bool(out) and os.path.basename(out) == os.path.basename(CAFFEINATE)


def kill_ours(pid):
    if pid_is_ours(pid):
        with contextlib.suppress(OSError):
            os.kill(int(pid), signal.SIGTERM)


def keep_awake(agents, registry, doms, t):
    """Одна проверка дежурного «запрет сна Mac»: запретить сон, если есть причина, иначе снять запрет."""
    path = P.path("awake.json")
    st = P.read_json(path, {})
    reason, nothing = hold_reason(agents, doms, t)
    low = None
    if reason and not P.on_ac():
        pct = batt_pct()
        if pct is not None and pct <= BATT_MIN:
            low, reason, nothing = pct, None, f"батарея {pct:.0f} %"
    if low is not None:
        P.notify_soon("awake-batt", f"Mac на батарее ({low:.0f} %): подключите зарядку — запрет сна снят, "
                      "ночная работа встанет", group="awake-batt", once=True)
    elif P.on_ac() or (batt_pct() or 100) > BATT_MIN:
        P.clear_fault("awake-batt")
    alive = pid_is_ours(st.get("pid"))
    if not reason:
        if alive:
            kill_ours(st.get("pid"))
        P.write_json(path, {"released": t, "why": nothing, "low_batt": low})
        return
    if alive and float(st.get("until") or 0) - t > HOLD_MARGIN:
        st.update(reason=reason, low_batt=None)
        P.write_json(path, st)
        return
    hold = watch_interval() + HOLD_MARGIN
    proc = subprocess.Popen([CAFFEINATE, "-i", "-t", str(int(hold))], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    if alive:
        kill_ours(st.get("pid"))
    P.write_json(path, {"pid": proc.pid, "until": t + hold, "since": t, "reason": reason})


def status_line(t=None):
    """Строка раздела Mac в `pantheon status`: только читает awake.json."""
    t = P.now() if t is None else t
    st = P.read_json(P.path("awake.json"), {})
    if st.get("pid") and float(st.get("until") or 0) > t and pid_is_ours(st["pid"]):
        return f"Запрет сна Mac: {st.get('reason') or 'есть работа'} (до {hhmm(float(st['until']))})"
    if st.get("low_batt") is not None:
        return f"Mac может спать: батарея {float(st['low_batt']):.0f} % — подключите зарядку"
    return "Mac может спать" + (f": {st['why']}" if st.get("why") else "")


# --- напоминание о перезагрузке (решение владельца 16.10) --------------------------------

def boot_time():
    if os.environ.get("PANTHEON_FAKE_BOOT"):
        return float(os.environ["PANTHEON_FAKE_BOOT"])
    out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True).stdout
    m = re.search(r"sec = (\d+)", out)
    return float(m.group(1)) if m else None


def swap_used_gb():
    if os.environ.get("PANTHEON_FAKE_SWAP"):
        return float(os.environ["PANTHEON_FAKE_SWAP"])
    out = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    m = re.search(r"used = ([\d.,]+)M", out)
    return float(m.group(1).replace(",", ".")) / 1024 if m else None


def last_friday(t):
    """Прошлая пятница 00:00 (местное): последняя строго раньше даты t (в пятницу — неделю назад)."""
    d = date.fromtimestamp(t)
    d -= timedelta(days=(d.weekday() - 4) % 7 or 7)
    return time.mktime(datetime(d.year, d.month, d.day).timetuple())


def reboot_reminder(rest=(), t=None):
    """pantheon reboot-reminder [--now]: загрузка была после прошлой пятницы 00:00 — молчит; иначе карточка «Перезагрузить
    Mac» и уведомление, не больше одной карточки на неделю. Без --now работает только в пятницу после 09:30: расписание
    знает лишь «раз в N минут», час дня — здесь."""
    t = P.now() if t is None else t
    if "--now" not in rest:
        lt = datetime.fromtimestamp(t)
        if lt.weekday() != 4 or (lt.hour, lt.minute) < REBOOT_AT:
            return 0
    fri = last_friday(t)
    boot = boot_time()
    if boot is None or boot >= fri:
        return 0
    mp = P.path("reboot-reminder.json")
    mark = P.read_json(mp, {})
    iso = datetime.fromtimestamp(t).isocalendar()
    week = f"{iso[0]}-W{iso[1]:02d}"
    if mark.get("week") == week:
        return 0
    days = (t - boot) / 86400
    sw = swap_used_gb()
    swap_txt = f"{sw:.1f} ГБ" if sw is not None else "неизвестен"
    text = f"аптайм {days:.0f} суток, своп {swap_txt}"
    T = P.tasks_mod()
    tid, _ = T.task_new(P.PANTHEON, t, "inbox", "Перезагрузить Mac", actor="pantheon", owner="zeus", status="waiting",
                        waiting_on="human",
                        text=f"Mac не перезагружался с {P.stamp(boot)[:10]}: {text}. Перезагрузите и после выполните "
                             "`claude respawn --all`.")
    P.write_json(mp, {"week": week, "task": tid, "at": t})
    P.notify(f"Перезагрузите Mac: {text}; после — claude respawn --all", group="reboot-reminder")
    print(f"{tid}: карточка «Перезагрузить Mac» заведена ({text})")
    return 0


# --- возобновление после недельного лимита (0132) -------------------------------------------------

def limit_resume(agents, registry, doms, t):
    """Сессия Пантеона стоит на лимите, сброс + 10 мин прошли — шлюз запуска respawn, один подъём на один сброс."""
    marks = read_marks()
    lim = marks.setdefault("limit", {})
    changed = False
    for a in agents:
        name, sid = a.get("name") or "", a.get("sessionId") or a.get("id") or ""
        if not sid or not pantheon_name(name, doms) or a.get("state") == "working":
            continue
        li = limit_info(a)
        if li is None or t < li[0] + LIMIT_GRACE:
            continue
        mk = lim.get(sid) if isinstance(lim.get(sid), dict) else {}
        if mk.get("reset") == li[0] and (mk.get("done") or int(mk.get("tries") or 0) >= LIMIT_TRIES):
            continue
        why = recheck(name) or ("планировщик на паузе" if scheduler_paused() else None)
        if why:
            continue
        ok, reason = gate("respawn", t, agents=agents, registry=registry)
        if not ok:
            P.start_log(f"limit-gate\t{name}\t{a.get('id')}\t{reason}")
            continue
        prev = int(mk.get("tries") or 0) if mk.get("reset") == li[0] else 0
        mk = {"reset": li[0], "tries": prev + 1, "at": t}
        rc, _ = P.resume_session(name, a, RESUME_LIMIT_TEXT, "limit", recheck=lambda n=name: recheck(n))
        if rc in (P.NO_WINDOW, P.SKIPPED):  # SKIPPED (metis-0291) — пропуск, не попытка; окна нет: тревога о причине уже одна (window_missing), попытку не засчитываем
            mk["tries"] = prev
        mk["done"] = rc == 0
        lim[sid] = mk
        changed = True
        if rc == 0:
            RESUMED.append(name)
        elif rc not in (P.NO_WINDOW, P.SKIPPED):
            P.alert(f"возобновление после недельного лимита: {name} не поднялась (код {rc}, попытка {mk['tries']} "
                    f"из {LIMIT_TRIES})", "watch")
    if changed:
        P.write_json(marks_path(), marks)


# --- возобновление ждущих сессий (0127 п. 2) --------------------------------------------------------

def owner_blockers(direction):
    """id задач, названных в STATUS.md направления строкой «владелец: <id> …»: их без владельца не берут."""
    try:
        text = open(os.path.join(P.PANTHEON, "directions", direction, "STATUS.md"), encoding="utf-8").read()
    except OSError:
        return set()
    return {i for m in BLOCKER.finditer(text) for i in TASK_ID.findall(m.group(1))}


def free_task(direction, t):
    """Первая задача направления, которую можно взять: todo, без чужой аренды и незакрытых depends_on (tasks.ready), без
    waiting_on, не названная блокером в STATUS.md. Допущение: «трогает файлы ждущего PR» выражается waiting_on/depends_on."""
    try:
        T = P.tasks_mod()
        ready = T.ready(P.PANTHEON, t, direction=direction)
    except Exception:  # noqa: BLE001
        return None
    blocked = owner_blockers(direction)
    for tid, head in ready:
        if tid in blocked or head.get("waiting_on"):
            continue
        return tid
    return None


def wake_waiting(agents, registry, doms, t):
    """Сессия направления «ждёт вас» (blocked), а в очереди есть задача без блокера — разбудить, не чаще раза в час."""
    marks = read_marks()
    last = marks.setdefault("wake", {})
    changed = False
    for a in agents:
        name = a.get("name") or ""
        if name not in doms or a.get("state") != "blocked" or not a.get("sessionId"):
            continue
        if limit_info(a) is not None:  # на лимите — это возобновление после недельного лимита, а не ждущая
            continue
        if t - float(last.get(name) or 0) < WAKE_REPEAT:
            continue
        tid = free_task(name, t)
        if not tid or recheck(name) or scheduler_paused():
            continue
        ok, reason = gate("wake", t, agents=agents, registry=registry)
        if not ok:
            P.start_log(f"wake-gate\t{name}\t{a.get('id')}\t{reason}")
            continue
        last[name] = t
        changed = True
        rc, _ = P.resume_session(name, a, RESUME_TASK_TEXT.format(tid=tid), "wake-waiting",
                                 recheck=lambda n=name: recheck(n))
        if rc == 0:
            RESUMED.append(name)
        elif rc not in (P.NO_WINDOW, P.SKIPPED):
            P.alert(f"возобновление ждущих сессий: {name} не поднялась (код {rc}), задача {tid}", "watch")
    if changed:
        P.write_json(marks_path(), marks)
