"""Дежурный Пантеона без модели и управление сессиями (шаг 1.4).

  pantheon watch [--dry-run]  задача тика раз в 5 мин (SCHED-09): снимок `claude agents` для строки статуса и
                            `pantheon who` (COMM-14), ждущие и упавшие сессии Пантеона, давно не обновлённый и длинный
                            STATUS.md, swap и открытые подключения (COMM-13), копии worktree (QA-05), смена версии
                            Claude Code (SCOUT-05, SEC-16), паузы по нагрузке (COST-04), самозапуск координаторов,
                            метка технического перезапуска, перезапуск свободных окон после обновления плагинов
                            (metis-0181), уборка: claude rm сессий Пантеона, закончивших ход или остановленных
                            больше 2 ч назад (metis-0250); раз в сутки — журналы ваших слов (COMM-10).
                            --dry-run — только показать, кого самозапуск поднял бы и почему нет, ничего не меняя
  pantheon agents           только снимок `claude agents` (задача тика на каждый проход: строка статуса)
  pantheon revisits         задача тика раз в сутки (SCHED-10, DOC-03): «пора пересмотреть …» в alerts.md
  pantheon stop <имя>|--all, pantheon resume <имя>|--all                                      (SCHED-12)
                            stop — метка «остановлено вами», claude stop и claude rm: сессия уходит из фоновых
                            сессий Claude Code (metis-0239), переписка остаётся
  pantheon pause <имя>|--all --reason limit|swap|manual ["почему"], pantheon pause --off [<имя>|--all]   (COST-04)
  pantheon restart --prepare [причина]|--status|--go [--force]|--cancel, pantheon saved --by <имя> --state <путь>
                            технический перезапуск всей системы (SCHED-15, слово владельца 15.10); pantheon saved без
                            техперезапуска — метка «можно» для перезапуска после обновления плагинов (metis-0181)
  pantheon who              координаторы: состояние, short из реестра, давность (COMM-14)
  pantheon wake <имя> ["задание"]   поднять уснувшую сессию направления и сказать «посмотри входящие» (COMM-04)
  pantheon infra-check      лёгкая проверка опор системы после обновления Claude Code (SEC-16)

Всё, что дежурный находит, — строка в ~/ai/pantheon/alerts.md один раз на состояние (alert_once) и, где нужно вас,
уведомление; в «ждёт вас» на доске переносит штаб. Модель дежурный не зовёт. Каждая проверка идёт отдельно: сбой одной
— тревога «проверка X упала», остальные работают; время прохода — ~/.local/state/pantheon/watch-last (строка статуса и
`pantheon status` показывают, что дежурный жив). Основания — исследование
~/ai/knowledge/inbox/research-2026-10-15-supervisor-watchdog.md и план ~/ai/pantheon/handoff/army-setup/step-1.4-plan.md.
"""
import contextlib
import hashlib
import json
import os
import random
import re
import subprocess
import time
import tomllib
from datetime import date, datetime, timedelta

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()


def set_core(mod):
    global P
    P = mod


# Пороги (выбрано при сборке 15.10; поменять — здесь или в [defaults] schedule.toml)
STALE_STATUS_DAYS = 2        # STATUS.md направления с задачей «В работе» не обновлялся дольше — тревога
AUTO_RM_AFTER = 2 * 3600     # уборка (metis-0250): закончила ход или остановлена дольше — claude rm
AUTO_RM_RETRY = 86400        # rm отказал (неотправленная работа в worktree) — следующая попытка через сутки
STATUS_MAX_LINES = 200       # STATUS.md длиннее — тревога (STATE-14)
SWAP_ALERT_GB = 4.0          # swap выше — тревога с открытыми подключениями (COMM-13); `pantheon status` — тот же порог
SWAP_KEEP_DAYS = 15          # замеры swap: R-two-directions смотрит «две недели ниже порога»
WORKTREE_DAYS = 3            # копия .claude/worktrees/* без живой сессии дольше — «забытая», тревога координатору
WORKTREE_CLEAN_HOURS = 24    # слитая и чистая копия старше — дежурный убирает её сам (QA-05)
AUTOSTART_MAX = 2            # самозапуск: не больше двух направлений сразу (MEM-01, решение 15.10)
SESSIONS_MAX = 3             # всего сессий Пантеона: два направления + одно место для ваших просьб (мастерская)
AUTOSTART_BACKOFF = 3600     # одно направление — не чаще раза в час; после сбоя пауза растёт: 1 ч → 2 ч → 4 ч
AUTOSTART_FAILS_MAX = 3      # три сбоя подряд — самозапуск направления встаёт, тревога и уведомление
AUTOSTART_HEALTHY = 1800     # сессия проработала столько — сбои забыты
OWNER_SANCTION_DAYS = 30     # решение владельца по задаче старше — не основание будить
MAINT_HOURS = 2              # метка технического перезапуска живёт столько, потом снимается с тревогой
REVISIT_REPEAT_DAYS = 3      # открытый пересмотр напоминает снова через столько дней, пока его не закрыли или не перенесли
OWNER_LOG_DAYS = 30          # журналы ваших слов (COMM-10)
HOOK_LOG_MAX = 400_000       # журнал сбоев хуков ctx-hooks.log, байт
WAKE_PUSH = ("[Пантеон: передача задания] Посмотри входящие: inbox/ и задачи направления, STATUS.md. Продолжай со своего "
             "следующего шага; что ждёт владельца — Зевсу строкой.")
RESTART_TEXT = ("[Пантеон: технический перезапуск завершён] Сессия перезапущена с новыми версиями плагинов и ролей. "
                "Прочитай свой файл состояния (STATUS.md направления или файл задачи мастерской) и продолжай со "
                "следующего шага. Это не ответ владельца и не согласие.")
RESPAWN_TEXT = ("[Пантеон: перезапуск после обновления плагинов] Сессия перезапущена с новыми версиями плагинов. "
                "Прочитай свой файл состояния (STATUS.md направления или файл задачи мастерской) и продолжай со "
                "следующего шага; если ждал(а) ответа или работы не было — закончи ход. Это не ответ владельца и не "
                "согласие.")
RESPAWN_IDLE_MIN = 15        # перезапуск после обновления плагинов: столько минут без записи транскрипта, субагентов
                             # и worktree окна — окно свободно (лид может ждать тесты; metis-0181)
UNPAUSE_TEXT = ("[Пантеон: пауза по нагрузке снята] Тебя останавливали из-за лимита или памяти. Прочитай STATUS.md и "
                "продолжай со следующего шага. Это не ответ владельца и не согласие.")


def defaults():
    with contextlib.suppress(Exception):
        return P.load_schedule().get("defaults") or {}
    return {}


def threshold(key, default):
    try:
        return float(defaults().get(key, default))
    except (TypeError, ValueError):
        return default


def domains():
    return P.read_json(P.path("domains.json"), {}).get("domains") or {}


def is_pantheon(name, doms):
    return bool(name) and (name in doms or name.startswith("daedalus-") or re.fullmatch(r"zeus(?:[- ].*)?", name))


def today(t=None):
    return datetime.fromtimestamp(P.now() if t is None else t).strftime("%Y-%m-%d")


def dry():
    return os.environ.get("PANTHEON_DRYRUN") == "1"


def holders(name, agents, registry):
    """Сессии, которые держат имя: работают, ждут вас, закончили ход с живым процессом, открыты во вкладке. Копии
    «имя (2)» и «имя-два-слова» — тоже (P.name_alias). Остановленная, упавшая и закрытая — не держат."""
    alias = P.name_alias(name)
    out = [a for a in agents if alias.fullmatch(str(a.get("name") or "")) and (
        a.get("state") in ("working", "blocked") or (a.get("pid") and a.get("state") not in ("stopped", "failed")))]
    known = {a.get("sessionId") for a in agents}
    out += [r for r in registry if r.get("sessionId") not in known and alias.fullmatch(str(r.get("name") or ""))]
    return out


def idle_holder(a):
    """Простаивающий держатель имени (metis-0212): закончил ход с живым процессом (`state` done) или Claude Code сам
    перезапустил фоновую сессию, и задания у неё нет (`state` working остался от прежнего процесса, `status` idle).
    Работает — `status` busy, ждёт разрешения, живые субагенты и фоновые команды (`inFlight` из state.json, как у
    запрета сна Mac) или назначено своё пробуждение (ScheduleWakeup, CronCreate, /loop): Claude Code 2.1.302 кладёт
    его в `inFlight` (вид session_cron, поле `wake`) и ставит `selfWake` в state.json.
    Вкладку и сессию из реестра не трогаем: там человек."""
    if a.get("kind") not in (None, "background") or not a.get("id") or not a.get("sessionId"):
        return False
    status = str(a.get("status") or "").lower()
    if not (a.get("state") == "done" or (a.get("state") == "working" and status == "idle")):
        return False
    if status in ("busy", "working") or "permission" in str(a.get("waitingFor") or "").lower():
        return False
    if a.get("subagents") or a.get("backgroundTasks"):
        return False
    js = awake().session_state(a)
    if a.get("selfWake") or js.get("selfWake"):
        return False
    for fl in (a.get("inFlight"), js.get("inFlight")):
        if isinstance(fl, dict) and (fl.get("tasks") or fl.get("queued") or fl.get("wake")
                                     or "session_cron" in (fl.get("kinds") or ())):
            return False
        if fl and not isinstance(fl, dict):
            return False
    return True


def nudge_target(hold):
    """Кому передать задание вместо «уже работает»: все держатели имени простаивают → самый новый из них; хоть один
    работает, ждёт вас или открыт во вкладке → None."""
    if not hold or not all(idle_holder(a) for a in hold):
        return None
    return max(hold, key=lambda a: a.get("startedAt") or 0)


def primary_reason():
    """Самозапуск и возобновление после паузы — только на главном Mac (SCHED-14): состояние, журналы и claude agents
    у каждого Mac свои, и два Mac подняли бы одно направление (ревью argus)."""
    try:
        ph = P.load_schedule().get("primary_host")
    except (OSError, ValueError):
        ph = None
    if not ph:
        return "в schedule.toml нет primary_host"
    return None if P.host() == ph else f"не главный Mac (главный — {ph})"


def wake_block(name, agents, registry, auto, nudge=False):
    """Почему сессию сейчас будить нельзя, или None. Одна проверка для всех, кто будит: самозапуск, снятие паузы,
    pantheon wake <имя> и общий pantheon wake (ревью argus). auto — будит программа, а не вы или Зевс по вашему слову:
    тогда ещё общая пауза планировщика, главный Mac и пятичасовой лимит. nudge — передача задания живой простаивающей
    сессии (metis-0212): держатели имени не мешают, пока все они простаивают (nudge_target)."""
    if os.path.exists(P.path("stopped", name)):
        return "остановлено вами"
    m = P.maintenance_active()
    if m:
        return f"идёт технический перезапуск ({m.get('reason')})"
    p = P.load_pause(name)
    if p:
        return f"пауза по нагрузке ({p.get('reason')})"
    hold = holders(name, agents, registry)
    if hold and not (nudge and nudge_target(hold)):
        return "уже работает"
    if auto:
        if os.path.exists(P.path("paused")):
            return "весь планировщик на паузе"
        why = primary_reason()
        if why:
            return why
        pct, lim = P.limit_pct(), threshold("limit_max_pct", 70)
        if pct is not None and pct >= lim:
            return f"пятичасовой лимит {pct:.0f} % ≥ {lim:g} %"
        # темп недели и ночь (metis-0127): любой автоматический подъём — как продолжение (днём только темп, ночью —
        # открытая ночь с бюджетом); самозапуск по задаче сверх того проверяет autostart()
        ok, why = P.night_mod().gate("respawn", P.now(), agents, registry)
        if not ok:
            return f"недельный лимит: {why}"
    return None


WAIT_REASONS = ("идёт технический", "пауза по нагрузке", "весь планировщик", "не главный", "в schedule.toml нет",
                "пятичасовой", "недельный лимит")


def recheck(name, auto, nudge=False):
    """Та же проверка по свежему claude agents — под блокировкой имени перед самим подъёмом."""
    return lambda: wake_block(name, P.agents_all() or [], P.sessions_registry(), auto, nudge)


# --- снимок сессий (COMM-14) ---------------------------------------------------------

def snapshot(agents, t):
    keep = ("id", "sessionId", "name", "state", "status", "pid", "cwd", "kind", "startedAt", "waitingFor")
    P.write_json(P.path("agents.json"), {"time": t, "agents": [{k: a.get(k) for k in keep if k in a}
                                                                for a in agents]})


def agents_cmd():
    agents = P.agents_all()
    if agents is None:
        print("pantheon agents: claude agents --json не ответил")
        return P.TEMPFAIL
    snapshot(agents, P.now())
    return 0


# --- дежурный (SCHED-09) -----------------------------------------------------------------

def watch(dry=False):
    with P.lock("watch", block=False) as got:
        if not got:
            print("pantheon watch: уже идёт другой проход")
            return 0
        return _watch(dry)


def _watch(dry=False):
    t = P.now()
    if dry:
        agents = P.agents_all()
        if agents is None:
            print("claude agents --json не ответил")
            return 1
        autostart(agents, P.sessions_registry(), domains(), t, dry=True)
        return 0
    agents = P.agents_all()
    if agents is None:
        P.alert_once("watch-agents", today(t), "дежурный: claude agents --json не ответил — сессии не проверены", "watch")
        P.write_json(P.path("watch-last"), {"time": t, "failed": ["claude agents"]})
        return P.ALERTED
    P.clear_once("watch-agents")
    reg = P.sessions_registry()
    doms = domains()
    checks = [("снимок", lambda: snapshot(agents, t)),
              ("метка перезапуска", lambda: maint_expire(t)),
              ("сессии", lambda: sessions(agents, doms)),
              ("STATUS.md", lambda: status_files(doms, t)),
              ("swap", lambda: swap(agents, t)),
              ("worktree", lambda: worktrees(agents, reg, doms, t)),
              ("версия Claude Code", lambda: cc_version(t)),
              ("памятка Кто есть кто", lambda: P.who_is_who_alert()),
              ("паузы по нагрузке", lambda: pauses_clear(agents, reg, t)),
              ("очистка Зевса", lambda: zeus_clean(agents, t)),
              ("перезапуск после обновления плагинов", lambda: plugins_respawn(agents, doms, t)),
              ("ночь", lambda: P.night_mod().watch(agents, reg, doms, t)),
              ("самозапуск", lambda: autostart(agents, reg, doms, t)),
              ("возобновление после недельного лимита", lambda: awake().limit_resume(agents, reg, doms, t)),
              ("возобновление ждущих сессий", lambda: awake().wake_waiting(agents, reg, doms, t)),
              ("запрет сна Mac", lambda: awake().keep_awake(agents, reg, doms, t)),
              ("журналы ваших слов", lambda: daily(t)),
              # последней: сессии, которые она уберёт, в этом проходе ещё в списке — подъём выше их уже не тронет
              ("уборка сессий", lambda: auto_rm(agents, doms, t))]
    failed = []
    for name, fn in checks:
        try:
            fn()
            P.clear_once(f"watch-fail-{name}")
        except Exception as e:  # noqa: BLE001 — сбой одной проверки не останавливает остальные
            failed.append(name)
            P.alert_once(f"watch-fail-{name}", f"{today(t)}-{type(e).__name__}",
                         f"дежурный: проверка «{name}» упала ({type(e).__name__}: {str(e)[:160]}) — остальные идут; "
                         "журнал pantheon jobs, задача watch", "watch")
    P.write_json(P.path("watch-last"), {"time": t, "failed": failed})
    return 0 if not failed else P.ALERTED


def awake():
    """lib/awake.py — ночной цикл: запрет сна Mac, возобновление после недельного лимита и ждущих сессий."""
    return P.awake_mod()


def gave_up_note(d, s):
    """Текст уведомления «самозапуск встал» — один и тот же при сбое и в каждом проходе (повтор сверяет текст)."""
    return f"Самозапуск {d} встал: {s.get('fails')} сбоя подряд"


def sessions(agents, doms):
    """Ждёт вас (blocked) или упала (failed) — тревога один раз на состояние сессии; уведомление — сбой «скоро»
    каждый проход, пока состояние держится (политика решает: macOS, когда вас нет, не чаще раза в час на событие)."""
    word = {"blocked": "ждёт вас", "failed": "упала"}
    for a in agents:
        name, sid, state = a.get("name") or "", a.get("id") or a.get("sessionId") or "", a.get("state")
        if not sid or not is_pantheon(name, doms):
            continue
        key = f"watch-state-{sid}"
        if state not in word or a.get("noProcess"):  # metis-0250: снятая Claude Code без вопроса — не «ждёт вас»
            P.clear_once(key)
            P.clear_fault(*(f"watch-{s}-{sid}" for s in word))  # состояние снялось — следующее снова macOS
            continue
        P.clear_fault(*(f"watch-{s}-{sid}" for s in word if s != state))
        why = " ".join(str(a.get("waitingFor") or "").split())[:120]
        P.alert_once(key, state, f"{name} ({sid}) {word[state]}" + (f": {why}" if why else "")
                     + f" — claude attach {sid}", "watch")
        # ключ события — сессия и состояние: «упала» после «ждёт вас» — своё уведомление, вид — один на сессию
        P.notify_soon(f"watch-{state}-{sid}", f"{name} {word[state]}" + (f": {why[:80]}" if why else ""),
                      group=f"session-{name}", once=True)


def _job_time(js):
    """Когда задание перешло в нынешнее состояние: lastTerminalAt, иначе updatedAt state.json (ISO с Z) → с или None."""
    for k in ("lastTerminalAt", "updatedAt"):
        v = js.get(k)
        if isinstance(v, (int, float)):
            return float(v) / 1000 if v > 1e11 else float(v)
        if isinstance(v, str) and v:
            with contextlib.suppress(ValueError):
                return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    return None


def auto_rm(agents, doms, t):
    """Уборка (metis-0250, поручение Зевса 18.10): фоновая сессия Пантеона закончила ход или остановлена (done/stopped),
    процесса нет и в этом состоянии она дольше AUTO_RM_AFTER — `claude rm <id>` (P.rm_session, как у pantheon stop).
    Переписка остаётся (claude --resume). Неотправленные коммиты в worktree: rm без --discard-unpushed откажет сам — тогда
    тревога один раз и новая попытка через сутки. Не трогаем: при техперезапуске, паузе планировщика и паузе по нагрузке
    (их снятие продолжает остановленную сессию той же), без state.json (время неизвестно), вкладки и чужие сессии.
    Есть живая сессия того же имени — прежнюю убираем сразу, без 2 ч: в claude agents у имени одна строка (добивает то,
    что не убрали start/wake/restart, P.rm_previous)."""
    if dry() or P.maintenance_active() or os.path.exists(P.path("paused")):
        return
    tried = P.read_json(P.path("auto-rm.json"), {})
    tried = {k: v for k, v in tried.items() if isinstance(v, (int, float)) and t - v < AUTO_RM_RETRY} \
        if isinstance(tried, dict) else {}
    gone = []
    live = {a.get("name") for a in agents if a.get("kind") in (None, "background")
            and a.get("state") in ("working", "blocked") and not a.get("noProcess")}
    for a in agents:
        name, sid = a.get("name") or "", str(a.get("id") or "")
        if (a.get("kind") not in (None, "background") or a.get("state") not in ("done", "stopped") or a.get("pid")
                or not re.fullmatch(r"[0-9a-zA-Z-]{4,64}", sid) or not is_pantheon(name, doms) or sid in tried
                or P.load_pause(name)):
            continue
        since = _job_time(P.claude_job_state(sid))
        if name not in live and (since is None or t - since < AUTO_RM_AFTER):
            continue  # у имени есть живая сессия — эта лишняя строка, убираем сразу (start/wake не добили)
        reason = P.rm_session(sid, tries=1)
        if reason is None:
            P.start_log(f"auto-rm\t{name}\t{sid}\t{a.get('state')}")
            gone.append(f"{name} {sid}")
            continue
        tried[sid] = t
        P.start_log(f"rm-refused\t{name}\t{sid}\t{reason}")
        P.alert_once(f"auto-rm-{sid}", reason[:80], f"{name}: прежняя сессия {sid} осталась среди фоновых сессий Claude "
                     f"Code (уборка, {P.refused_by(reason)}): {reason}", "watch")
    P.write_json(P.path("auto-rm.json"), tried)
    if gone:
        P.alert(f"уборка: убраны из фоновых сессий Claude Code (закончили ход или остановлены больше "
                f"{AUTO_RM_AFTER // 3600} ч назад, или у имени уже есть живая): {', '.join(gone)}; переписка осталась — "
                "claude --resume", "watch")


def status_files(doms, t):
    """STATUS.md направления: с задачей «В работе» давно не обновлялся — состояние могло потеряться; длиннее 200 строк
    — координатору перенести закрытое в archive/ (STATE-14)."""
    doing = set()
    with contextlib.suppress(Exception):
        doing = {h.get("direction") for _, h, _ in P.tasks_mod().load_tasks(P.PANTHEON).values()
                 if h.get("status") == "doing"}
    for name in doms:
        p = os.path.join(P.PANTHEON, "directions", name, "STATUS.md")
        try:
            st = os.stat(p)
            n = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
        except OSError:
            continue
        age = (t - st.st_mtime) / 86400
        if name in doing and age > STALE_STATUS_DAYS:
            P.alert_once(f"watch-status-{name}", today(t),
                         f"STATUS.md {name} не обновлялся {age:.0f} дн., а задача «В работе» есть — спросить "
                         "координатора, где он", "watch")
        if n > STATUS_MAX_LINES:
            P.alert_once(f"watch-status-long-{name}", "1", f"STATUS.md {name} — {n} строк (> {STATUS_MAX_LINES}): "
                         "координатору перенести закрытое в archive/ направления", "watch")
        else:
            P.clear_once(f"watch-status-long-{name}")


def swap_gb():
    if os.environ.get("PANTHEON_FAKE_SWAP"):
        return float(os.environ["PANTHEON_FAKE_SWAP"])
    out = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True, text=True).stdout
    m = re.search(r"used = ([\d.,]+)M", out)
    return float(m.group(1).replace(",", ".")) / 1024 if m else None


def attached():
    """Открытые подключения к фоновым сессиям: признака в claude agents --json нет (COMM-13) — по процессам."""
    if os.environ.get("PANTHEON_FAKE_PS") is not None:
        out = os.environ["PANTHEON_FAKE_PS"]
    else:
        out = subprocess.run(["ps", "-ax", "-o", "pid=,command="], capture_output=True, text=True).stdout
    found = []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*)", line)
        if m and re.search(r"(?:^|/)claude (?:attach|agents)(?:\s|$)", m.group(2)):
            found.append(f"{m.group(2)[:60]} (pid {m.group(1)})")
    return found


def swap(agents, t):
    gb = swap_gb()
    if gb is None:
        return
    log = P.path("swap.jsonl")
    lines = []
    with contextlib.suppress(OSError):
        lines = open(log, encoding="utf-8").read().splitlines()
    keep = []
    for ln in lines:
        with contextlib.suppress(ValueError, KeyError, TypeError):
            if json.loads(ln)["t"] >= t - SWAP_KEEP_DAYS * 86400:
                keep.append(ln)
    working = sum(1 for a in agents if a.get("state") == "working")
    keep.append(json.dumps({"t": t, "gb": round(gb, 2), "working": working}))
    P.write_atomic(log, "\n".join(keep) + "\n")
    limit = threshold("swap_alert_gb", SWAP_ALERT_GB)
    if gb > limit:
        att = attached()
        P.alert_once("watch-swap", today(t), f"swap {gb:.1f} ГБ > {limit:g} ГБ, работают сессий: {working}" + (
            "; держат память открытые подключения — закрыть, если разговор окончен: " + "; ".join(att[:6])
            if att else "; открытых claude attach / claude agents нет"), "watch")


# Дежурный работает вне песочницы, а worktree пишут роли: git в ней не должен исполнять чужое из конфигурации
# (core.fsmonitor, хуки, фильтры clean/process; проверки безопасности 0.10.0 и 0.10.1). fsmonitor и хуки выключены
# всегда, подмодули git не обходит; в конфигурации самого репозитория допустимы только ключи из короткого списка без
# исполняемого — с любым другим копию не трогаем (своё не убрать безопаснее, чем исполнить чужое).
GIT_SAFE = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.untrackedCache=false"]
GIT_LOCAL_OK = re.compile(
    r"core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks|autocrlf|"
    r"eol|safecrlf|sparsecheckout|sparsecheckoutcone|quotepath|checkstat|trustctime|preloadindex|abbrev)|"
    r"remote\.[^.]+\.(url|pushurl|fetch|push|tagopt|prune|mirror)|branch\.[^.]+\.(remote|merge|rebase|pushremote)|"
    r"extensions\.(worktreeconfig|objectformat|refstorage)|user\.(name|email)|pull\.(rebase|ff)|"
    r"push\.(default|autosetupremote)|fetch\.prune|init\.defaultbranch|gc\.auto")


def _git(*args, timeout=30, env=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", **(env or {}))
    return subprocess.run(["git", *GIT_SAFE, *args], capture_output=True, text=True, timeout=timeout, env=env)


def wt_env(root, wt):
    """Каталог git копии — тот, что записан в основном репозитории (.git/worktrees/<id>/gitdir указывает на wt/.git),
    а не тот, куда ведёт указатель wt/.git: его пишет роль (проверка безопасности 0.10.2). Указатель с записью
    расходится — копию не трогаем. Все команды git по копии — с этими GIT_DIR, GIT_COMMON_DIR, GIT_WORK_TREE."""
    common = os.path.join(root, ".git")
    base = os.path.join(common, "worktrees")
    with contextlib.suppress(OSError):
        for d in os.listdir(base):
            gd = os.path.join(base, d)
            try:
                to = open(os.path.join(gd, "gitdir"), encoding="utf-8").read().strip()
            except OSError:
                continue
            if os.path.realpath(os.path.dirname(to)) != wt:
                continue
            try:
                ptr = open(os.path.join(wt, ".git"), encoding="utf-8").read().strip()
            except OSError:
                return None
            if not ptr.startswith("gitdir: ") or os.path.realpath(ptr[8:]) != os.path.realpath(gd):
                return None
            return {"GIT_DIR": gd, "GIT_COMMON_DIR": common, "GIT_WORK_TREE": wt}
    return None


def unsafe_config(wt, env=None):
    """Ключи конфигурации самого репозитория (не вашей глобальной) вне списка GIT_LOCAL_OK — в той конфигурации, которую
    git прочтёт в этой копии (по указателю .git копии, с include). Вывод -z: пары «область\\0ключ\\0» — имя подраздела
    с переводом строки разбор не собьёт. Не прочиталась — тоже нельзя."""
    if env is None:
        return "каталог git копии не совпадает с записью основного репозитория"
    r = _git("-C", wt, "config", "--list", "--show-scope", "--name-only", "--includes", "-z", env=env)
    if r.returncode not in (0, 1):
        return "конфигурация git не читается"
    parts = r.stdout.split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    if len(parts) % 2:
        return "конфигурация git не разобрана"
    bad = sorted({k for sc, k in zip(parts[::2], parts[1::2])
                  if sc not in ("system", "global", "command") and not GIT_LOCAL_OK.fullmatch(k.lower())})
    if os.path.exists(os.path.join(wt, ".gitmodules")):
        bad.append("подмодули")
    ls = _git("-C", wt, "ls-files", "-s", "-z", env=env)
    if ls.returncode != 0 or any(x.startswith("160000 ") for x in ls.stdout.split("\0")):
        bad.append("подмодули в индексе")
    return ", ".join(bad) or None


def _base_ref(root):
    """Основная ветка репозитория для «слита ли копия»: origin/HEAD, иначе main или master."""
    r = _git("-C", root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    for b in ("main", "master"):
        if _git("-C", root, "rev-parse", "--verify", "--quiet", b).returncode == 0:
            return b
    return None


WALK_LIMIT = 5000


def outward_links(wt):
    """Символические ссылки копии, чья цель (realpath) лежит вне неё. Обход без перехода по ссылкам, папку .git
    копии пропускаем. Допущение: больше WALK_LIMIT записей — копия считается небезопасной (None) и не удаляется.
    Возвращает (число, первая как (путь относительно копии, цель)) или None при превышении."""
    root = os.path.realpath(wt)
    n, first, seen = 0, None, 0
    for d, dirs, files in os.walk(root, followlinks=False):
        if d == root and ".git" in dirs:
            dirs.remove(".git")
        for name in dirs + files:
            seen += 1
            if seen > WALK_LIMIT:
                return None
            p = os.path.join(d, name)
            if not os.path.islink(p):
                continue
            target = os.path.realpath(p)
            if target != root and not target.startswith(root + os.sep):
                n += 1
                first = first or (os.path.relpath(p, root), target)
    return (n, first) if n else (0, None)


def _prune_state(root, live):
    """Решение о `git worktree prune` — по тому же, что смотрит сам git: <общий .git>/worktrees/*/gitdir (путь
    <копия>/.git; для git EACCES на lstat — «файла нет», запись пойдёт под prune, хотя копия жива). Возвращает
    (есть_пропавшая, препятствия [(путь копии, ошибка)]). Препятствие — любая OSError кроме FileNotFoundError/
    NotADirectoryError (недоступна) или пропавшая запись с живой сессией в её папке: prune глобален, при любом
    препятствии не делаем его во всём репозитории. Запись с файлом locked git не трогает — пропускаем."""
    r = _git("-C", root, "rev-parse", "--git-common-dir")
    cd = r.stdout.strip()
    if r.returncode != 0 or not cd:
        return False, []
    wdir = os.path.join(root, cd)
    try:
        ids = sorted(os.listdir(os.path.join(wdir, "worktrees")))
    except (FileNotFoundError, NotADirectoryError):
        return False, []
    except OSError as ex:
        return False, [(os.path.join(wdir, "worktrees"), ex.strerror or ex)]
    need, block = False, []
    for i in ids:
        d = os.path.join(wdir, "worktrees", i)
        try:
            os.lstat(os.path.join(d, "locked"))
            continue
        except (FileNotFoundError, NotADirectoryError):
            pass
        except OSError as ex:
            block.append((d, ex.strerror or ex))
            continue
        try:
            with open(os.path.join(d, "gitdir"), encoding="utf-8", errors="replace") as fh:
                target = fh.read().strip()
        except (FileNotFoundError, NotADirectoryError):
            need = need or os.path.isdir(d)  # записи без gitdir git снимает
            continue
        except OSError as ex:
            block.append((d, ex.strerror or ex))
            continue
        if not target:
            block.append((d, "битая"))  # пустой gitdir: как недоступный — prune откладываем
            continue
        target = os.path.join(d, target)
        copy = os.path.realpath(os.path.dirname(target))
        try:
            os.lstat(target)
        except (FileNotFoundError, NotADirectoryError):
            if any(c == copy or c.startswith(copy + os.sep) for c in live):
                block.append((copy, "пропавшая папка при живой сессии"))
            else:
                need = True
        except OSError as ex:
            block.append((copy, ex.strerror or ex))
    return need, block


def worktrees(agents, registry, doms, t):
    """Копии .claude/worktrees/* (QA-05). Слитая в основную ветку и чистая (git status пуст), старше суток и без живой
    сессии в ней — дежурный убирает сам: `git worktree remove` без --force (грязную git не отдаст) и `git branch -d`
    (неслитую не удалит). Прочие без живой сессии дольше WORKTREE_DAYS — тревога координатору: в них может быть
    неотправленная работа. Копию со ссылками наружу (outward_links) не удаляем и тревожим: старые Claude Code при
    удалении сносили цель ссылки вне копии.
    Копии вне .claude/worktrees (кроме основного checkout) — только тревога после WORKTREE_DAYS без сессии, никогда
    не удаляются. Записи с пропавшей папкой чистит один `git worktree prune` на репозиторий; решает _prune_state по пути из gitdir,
    как git: недоступная копия (в том числе с chmod 000 на ней самой) или живая сессия в пропавшей папке блокирует
    prune во всём репозитории (он глобален и снёс бы живую запись), недоступная — ещё и тревога."""
    live = [os.path.realpath(a["cwd"]) for a in list(agents) + list(registry) if a.get("cwd") and a.get("pid")]
    seen = set()
    for name, folders in doms.items():
        for f in folders if isinstance(folders, list) else []:
            root = os.path.realpath(os.path.expanduser(f))
            if root in seen or not os.path.isdir(os.path.join(root, ".git")):
                continue
            seen.add(root)
            r = _git("-C", root, "worktree", "list", "--porcelain")
            base = None
            for block in r.stdout.split("\n\n"):
                m = re.search(r"^worktree (.+)$", block, re.M)
                if not m:
                    continue
                wt = os.path.realpath(m.group(1))
                if wt == root:
                    continue
                try:
                    os.lstat(wt)
                except OSError:
                    continue  # пропавшую или недоступную копию дальше не трогаем; prune решает _prune_state
                if os.sep + os.path.join(".claude", "worktrees") + os.sep not in wt + os.sep:
                    # копия вне штатной папки: только тревога, никогда не удаляем
                    if any(c == wt or c.startswith(wt + os.sep) for c in live):
                        continue
                    try:
                        out_age = (t - os.stat(wt).st_mtime) / 3600
                    except OSError:
                        continue
                    if out_age > WORKTREE_DAYS * 24:
                        P.alert_once(f"watch-wt-{wt}", "1", f"копия вне штатной папки {wt.replace(P.HOME, '~')} "
                                     f"({name}, {out_age / 24:.0f} дн. без сессии) — координатору: слить или убрать",
                                     "watch")
                    continue
                if any(c == wt or c.startswith(wt + os.sep) for c in live):
                    continue
                try:
                    age = (t - os.stat(wt).st_mtime) / 3600
                except OSError:
                    continue
                head = re.search(r"^HEAD ([0-9a-f]{40})$", block, re.M)
                branch = re.search(r"^branch refs/heads/(.+)$", block, re.M)
                short = wt.replace(P.HOME, "~")
                env = wt_env(root, wt)
                if age > WORKTREE_CLEAN_HOURS and head and "locked" not in block and not unsafe_config(wt, env):
                    base = base or _base_ref(root)
                    st = _git("-C", wt, "status", "--porcelain", "--ignore-submodules=all", env=env)
                    clean = st.returncode == 0 and st.stdout.strip() == ""
                    merged = bool(base) and _git("-C", root, "merge-base", "--is-ancestor", head.group(1),
                                                 base).returncode == 0
                    if clean and merged:
                        out = outward_links(wt)
                        if out is None or out[0]:
                            what = ("обход длиннее %d записей" % WALK_LIMIT if out is None else
                                    "ссылки наружу (%d, первая: %s → %s)" % (out[0], out[1][0],
                                                                         out[1][1].replace(P.HOME, "~")))
                            P.alert_once(f"watch-wt-{wt}", "links", f"копия {short} не убрана: в ней {what} — "
                                         "координатору: убрать ссылки и удалить вручную", "watch")
                            continue
                        # чистота уже проверена своим status по записанному каталогу; без --force git проверил бы её
                        # ещё раз своим status — уже по конфигурации, которую мы не смотрели
                        rm = _git("-C", root, "worktree", "remove", "--force", wt, timeout=60)
                        if rm.returncode == 0:
                            if branch:
                                _git("-C", root, "branch", "-d", branch.group(1))
                            P.alert(f"убрана слитая чистая копия {short} ({name}"
                                    + (f", ветка {branch.group(1)}" if branch else "") + ")", "watch")
                            P.clear_once(f"watch-wt-{wt}")
                            continue
                if age > WORKTREE_DAYS * 24:
                    P.alert_once(f"watch-wt-{wt}", "1", f"забытая копия {short} ({name}, {age / 24:.0f} дн. без "
                                 "сессии, не слита или не чистая) — координатору: слить или убрать", "watch")
            need_prune, blockers = _prune_state(root, live)
            for path, ex in blockers:
                P.alert_once(f"watch-prune-{path}", "unreadable", f"запись копии {path.replace(P.HOME, '~')} "
                             f"недоступна ({ex}) — prune отложен", "watch")
            if need_prune and not blockers:
                # без --expire: git worktree prune по умолчанию убирает записи без папки сразу (срок
                # gc.worktreePruneExpire — только у gc); locked-записи git не трогает
                _git("-C", root, "worktree", "prune")


def cc_version(t):
    """Claude Code сменил версию (SCOUT-05) — строка в тревоги, событие cc_updated для пересмотров и проверка опор
    (SEC-16); не в порядке — уведомление и поручение Метиде через тревогу."""
    v = os.environ.get("PANTHEON_FAKE_CC")
    if v is None:
        r = subprocess.run([P.claude_bin(), "--version"], capture_output=True, text=True, timeout=60)
        v = (r.stdout.split() or [""])[0]
    if not re.fullmatch(r"\d+(?:\.\d+)+", v or ""):
        return
    p = P.path("cc-version")
    old = ""
    with contextlib.suppress(OSError):
        old = open(p).read().strip()
    if old == v:
        return
    P.write_atomic(p, v + "\n")
    if not old:
        return
    event("cc_updated", t, version=v, was=old)
    ok, lines = infra_check()
    P.alert(f"Claude Code обновился: {old} → {v}; проверка опор: "
            + ("в порядке" if ok else "НЕ в порядке — " + "; ".join(x for x in lines if x.startswith("НЕТ"))[:300]
               + " — Метиде: разобрать (pantheon infra-check)")
            + "; журнал изменений сверяет iris", "watch")
    if not ok:
        P.notify_soon("infra", f"Claude Code {v}: проверка опор не прошла — pantheon infra-check")


def event(kind, t, **extra):
    with open(P.path("events.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": t, "event": kind, **extra}, ensure_ascii=False) + "\n")


def events():
    out = []
    with contextlib.suppress(OSError):
        for ln in open(P.path("events.jsonl"), encoding="utf-8"):
            with contextlib.suppress(ValueError):
                out.append(json.loads(ln))
    return out


# --- паузы по нагрузке (COST-04, MEM-01) ----------------------------------------------------------------
# ~/.local/state/pantheon/pauses/<имя>.json (или _all.json — все): {"reason": limit|swap|manual, "why", "time", "by",
# "was": [id остановленных сессий]}. Ставит штаб (`pantheon pause <имя> --reason limit|swap`) или вы. Дежурный снимает
# только свою причину: limit — когда пятичасовой лимит ниже порога, swap — когда swap ниже порога; manual — только
# `pantheon pause --off`. Сессию, которую пауза остановила, дежурный после снятия продолжает той же сессией.

def pauses():
    out = {}
    with contextlib.suppress(OSError):
        for f in os.listdir(P.path("pauses")):
            if f.endswith(".json"):
                out[f[:-5]] = P.read_json(P.path("pauses", f), {})
    return out


def paused(name):
    return P.load_pause(name)


def pauses_clear(agents, registry, t):
    old = P.path("load-pause")  # прежняя общая метка (до 0.10.0): пауза по лимиту
    if os.path.isfile(old):
        why = open(old, encoding="utf-8").read().strip()
        P.write_json(P.path("pauses", "_all.json"), {"reason": "limit", "why": why[:200], "time": P.stamp(), "by": "?",
                                                     "was": []})
        os.remove(old)
    pct, gb = P.limit_pct(), None
    for name, p in sorted(pauses().items()):
        reason = p.get("reason")
        if reason == "limit":
            ok = pct is not None and pct < threshold("limit_max_pct", 70)
            now_is = f"лимит {pct:.0f} %" if pct is not None else ""
        elif reason == "swap":
            gb = swap_gb() if gb is None else gb
            ok = gb is not None and gb < threshold("swap_alert_gb", SWAP_ALERT_GB)
            now_is = f"swap {gb:.1f} ГБ" if gb is not None else ""
        else:
            continue
        if not ok:
            continue
        with contextlib.suppress(FileNotFoundError):
            os.remove(P.path("pauses", name + ".json"))
        why = wake_block(name, agents, registry, auto=True) if p.get("was") and name != "_all" else None
        if why and why.startswith(WAIT_REASONS):
            # своя причина ушла, но будить ещё нельзя (общая пауза, техперезапуск, лимит, не главный Mac) — пауза
            # остаётся до следующего прохода, иначе остановленная ею сессия так и не продолжилась бы (ревью argus)
            P.write_json(P.path("pauses", name + ".json"), p)
            if why.startswith(("не главный", "в schedule.toml нет")):
                P.alert_once(f"pause-not-primary-{name}", today(t), f"пауза {name} ({reason}) снялась бы ({now_is}), но "
                             f"{why} — снять вручную: pantheon pause --off {name}", "watch")
            continue
        who = "все" if name == "_all" else name
        P.alert(f"пауза по нагрузке ({reason}) снята дежурным: {who}, {now_is} (была: {str(p.get('why'))[:100]})", "watch")
        if p.get("was") and name != "_all":
            if why:
                P.alert(f"{name} после паузы не продолжена: {why}", "watch")
                continue
            got = resume_or_start(name, agents, UNPAUSE_TEXT, origin="tick", only_resume=True, auto=True)
            P.alert(f"{name} после паузы: " + ("продолжена" if got == 0 else f"не поднялась, код {got}"), "watch")


def pause(rest, who):
    """pantheon pause <имя>|--all --reason limit|swap|manual ["почему"]  |  pantheon pause --off [<имя>|--all]"""
    if rest[:1] == ["--off"]:
        target = rest[1] if len(rest) > 1 else "--all"
        if target not in ("--all", "_all") and not P.SESSION_NAME.fullmatch(target):
            print("pantheon pause --off [<имя>|--all]", file=P.sys.stderr)
            return 2
        names = list(pauses()) if target == "--all" else [target]
        # вашу паузу (manual) снимает ваше слово, как и метку «остановлено вами»; лимит и swap — кто угодно
        mine = [n for n in names if (pauses().get(n) or {}).get("reason") == "manual"]
        if mine and not owner_word_ok():
            print("pantheon pause --off: ручную паузу снимает только слово владельца — в журнале Зевса нет его строки "
                  f"за {P.OWNER_WORD_WINDOW // 60} мин", file=P.sys.stderr)
            P.alert(f"pantheon pause --off {target} от {who} отклонён: нет свежего слова владельца", "pantheon-stop")
            return 1
        gone = []
        for n in names:
            with contextlib.suppress(FileNotFoundError):
                os.remove(P.path("pauses", n + ".json"))
                gone.append("все" if n == "_all" else n)
        with contextlib.suppress(FileNotFoundError):
            os.remove(P.path("load-pause"))
        if gone:
            P.alert(f"пауза по нагрузке снята ({who}): {', '.join(gone)}", "pantheon-stop")
        print(f"пауза снята: {', '.join(gone) or 'её не было'}" + ("; остановленные паузой сессии поднимет самозапуск "
                                                                      "или pantheon wake <имя>" if gone else ""))
        return 0
    reason = None
    if "--reason" in rest:
        i = rest.index("--reason")
        reason = rest[i + 1] if i + 1 < len(rest) else None
        rest = rest[:i] + rest[i + 2:]
    if not rest or reason not in ("limit", "swap", "manual"):
        print(pause.__doc__, file=P.sys.stderr)
        return 2
    target, why = rest[0], " ".join(" ".join(rest[1:]).split())
    doms = domains()
    if target == "--all":
        name = "_all"
    elif target in doms or (target.startswith("daedalus-") and P.SESSION_NAME.fullmatch(target)):
        name = target
    else:
        print(f"pantheon pause: {target} — не направление и не мастерская (--all — все)", file=P.sys.stderr)
        return 2
    was = []
    if name != "_all":
        agents = P.agents_all() or []
        for a in P.live_copies(name, agents, registry=[]):
            if a.get("id"):
                subprocess.run([P.claude_bin(), "stop", a["id"]], capture_output=True, text=True, timeout=60)
                P.start_log(f"pause-stop\t{name}\t{a['id']}\t{who}\t{reason}")
                was.append(a["id"])
    P.write_json(P.path("pauses", name + ".json"), {"reason": reason, "why": why[:200], "time": P.stamp(), "by": who,
                                                    "was": was})
    who_txt = "все направления" if name == "_all" else name
    off = {"limit": "снимет дежурный, когда лимит станет ниже порога", "swap": "снимет дежурный, когда swap станет ниже "
           "порога", "manual": "снимает только pantheon pause --off"}[reason]
    P.alert(f"пауза по нагрузке ({reason}, {who}): {who_txt}" + (f" — {why}" if why else "")
            + (f"; остановлено сессий {len(was)}" if was else "") + f"; {off}", "pantheon-stop")
    print(f"пауза стоит: {who_txt}, причина {reason}; {off}")
    return 0



# --- очистка Зевса (metis-0136) ---------------------------------------------------------------------------------
# Большой контекст штаба дорог: каждый ход перечитывает его целиком. Дежурный очищает Зевса сам, только когда ничего
# не теряется: контекст ≥ порога Stop-хука «пора очистить» (ctx.py AT, 150 тыс.); Зевс ждёт ввода, а не посреди хода;
# нет запущенных им фоновых субагентов и команд; нет открытого вопроса AskUserQuestion; доска и последний
# handoff/zeus-*/HANDOFF.md записаны после начала его последнего хода. Очистка — свежий старт (P.fresh_start: claude
# stop, ожидание имени, claude --bg --agent hq --name zeus с окном штаба), а не claude respawn: respawn поднимает ту же
# сессию с тем же контекстом. Прошлый разговор остаётся (claude attach <id>). Не сохранено только (5) — напоминание
# не чаще раза в ZEUS_REMIND_MIN: строка в тревогах (её Зевс увидит со следующим вводом) и сброс метки Stop-хука —
# в конце следующего хода он снова скажет «сверь доску». Шестое условие: с конца последнего хода прошло не меньше
# ZEUS_IDLE_MIN — иначе ни очистки, ни напоминания, ждём следующего прохода. Координаторов и СБ не трогает.

ZEUS_REMIND_MIN = 60
ZEUS_IDLE_MIN = 20          # с конца хода Зевса прошло меньше — владелец, скорее всего, читает ответ: не трогать
ZEUS_BG_MAX_AGE = 86400     # фоновая задача без уведомления о конце старше суток — считается потерянной
TASK_DONE = re.compile(r"<task-notification>.*?<tool-use-id>(toolu_[A-Za-z0-9_]+)</tool-use-id>", re.S)


def zeus_turn(transcript):
    """Разбор хвоста транскрипта Зевса. → {"turn": начало последнего хода (с) или None, "mid": ход идёт или ждёт
    разрешения, "ask": открытый AskUserQuestion, "bg": id запущенных и не закончившихся фоновых задач, "answered":
    время последней записи Зевса (с) или None}."""
    C = P.ctx_mod()
    lines = C.tail_lines(transcript, 4_000_000)
    used, results, launched, done = {}, set(), {}, set()
    turn, last, answered = None, None, None
    for raw in lines:  # уведомление о конце — во вводе, в очереди ввода или во вложении: ищем по сырой строке
        if b"task-notification" in raw:
            done.update(TASK_DONE.findall(raw.decode("utf-8", "replace")))
    for d in C.entries(lines):
        if d.get("isSidechain") or d.get("type") not in ("user", "assistant"):
            continue
        t = C.iso_ts(d.get("timestamp"))
        content = (d.get("message") or {}).get("content")
        items = content if isinstance(content, list) else []
        if d.get("type") == "assistant":
            for x in items:
                if isinstance(x, dict) and x.get("type") == "tool_use" and x.get("id"):
                    used[x["id"]] = x
            last, answered = "assistant", t if t is not None else answered
            continue
        res = [x for x in items if isinstance(x, dict) and x.get("type") == "tool_result"]
        for x in res:
            tid = x.get("tool_use_id")
            results.add(tid)
            u, tur = used.get(tid) or {}, d.get("toolUseResult")
            bash_bg = u.get("name") == "Bash" and (u.get("input") or {}).get("run_in_background") and not x.get("is_error")
            agent_bg = isinstance(tur, dict) and (tur.get("isAsync") or tur.get("status") == "async_launched")
            if tid and (bash_bg or agent_bg):
                launched[tid] = t
        if d.get("isMeta"):
            continue
        last = "user"
        if not res:
            turn = t  # ввод владельца, уведомление о конце задачи, сообщение другой сессии — начало хода
    now = P.now()
    open_uses = [u for i, u in used.items() if i not in results]
    return {"turn": turn, "answered": answered,
            "mid": last == "user" or any(u.get("name") != "AskUserQuestion" for u in open_uses),
            "ask": any(u.get("name") == "AskUserQuestion" for u in open_uses),
            "bg": sorted(i for i, at in launched.items() if i not in done and (at is None or now - at < ZEUS_BG_MAX_AGE))}


def zeus_hold():
    """Почему Зевса сейчас не трогать независимо от его состояния, или None."""
    if os.path.exists(P.path("stopped", "zeus")):
        return "остановлен вами"
    m = P.maintenance_active()
    if m:
        return f"идёт технический перезапуск ({m.get('reason')})"
    if P.load_pause("zeus"):
        return "пауза по нагрузке"
    if os.path.exists(P.path("paused")):
        return "весь планировщик на паузе"
    for held in (".sync-held", ".sync-incoming"):  # карантин ~/.claude: ответ на доске применяет старт сессии
        p = os.path.join(P.HOME, ".claude", held)
        if not os.path.exists(p):
            continue
        task, solo = quarantine_mark(p)
        if held == ".sync-held" and solo and not task:
            continue  # sync.sh держит правку без вопроса (синхронизировать пока не с кем): ответа не будет — не ждём
        return "карантин правок ~/.claude ждёт ответа" + (f" на {task}" if task else "")
    return None


def quarantine_mark(p):
    """Метка карантина sync.sh: (задача-вопрос владельцу из строки task=… или "", держание без вопроса — solo=1).
    Метку не прочитать — ("", False): считаем, что ответа ждут."""
    try:
        text = open(p, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        return "", False
    m = re.search(r"^task=(\S*)\s*$", text, re.M)
    return (m.group(1) if m else ""), bool(re.search(r"^solo=1\s*$", text, re.M))


def zeus_clean_check(a, transcript):
    """Шесть условий очистки. → (что не выполнено: список номеров с текстом, контекст в токенах, разбор хода)."""
    C = P.ctx_mod()
    n = C.context_tokens(transcript)
    info = zeus_turn(transcript)
    miss = []
    if n < C.AT:
        miss.append((1, f"контекст {n // 1000} тыс. < {C.AT // 1000} тыс."))
    busy = (a.get("state") not in ("blocked", "done") or str(a.get("status") or "").lower() in ("busy", "working")
            or "permission" in str(a.get("waitingFor") or "").lower())
    if busy or info["mid"]:
        miss.append((2, f"идёт ход ({a.get('state')}, {a.get('status')})"))
    flight = a.get("inFlight") or a.get("subagents") or a.get("backgroundTasks")
    if flight or info["bg"]:
        miss.append((3, f"фоновые задачи: {', '.join(info['bg'][:3]) or 'есть'}"))
    if info["ask"]:
        miss.append((4, "открыт вопрос AskUserQuestion"))
    turn = info["turn"]
    stale = [f for f in P.state_files("zeus") if turn is None or not os.path.isfile(f) or os.path.getmtime(f) <= turn]
    if stale:
        miss.append((5, "не сохранено после последнего хода: " + ", ".join(P.tilde(f) for f in stale)))
    if info["answered"] is None or P.now() - info["answered"] < ZEUS_IDLE_MIN * 60:
        miss.append((6, f"с конца хода меньше {ZEUS_IDLE_MIN} мин — владелец, возможно, читает ответ"))
    return miss, n, info


ZEUS_SKIP_QUIET = (2, 6)  # идёт ход, только что ответил — обычное дело: только в zeus-clean.json, не в start.log


def zeus_trace(st, stp, t, a, miss, n, result):
    """metis-0207: след каждого прохода. zeus-clean.json["last"] — исход этого прохода (всегда); строка fresh-skip в
    start.log — когда причина отказа сменилась (без «идёт ход» и «только что ответил», они бывают каждый день)."""
    sid = a.get("sessionId")
    st["last"] = {"t": t, "at": P.stamp(t), "sid": sid, "id": a.get("id"), "tokens": n, "result": result,
                  "miss": [f"({m}) {s}" for m, s in miss]}
    key = [sid] + [s if m == 0 else m for m, s in miss if m not in ZEUS_SKIP_QUIET]
    if len(key) > 1 and key != st.get("skip"):
        P.start_log(f"fresh-skip\tzeus\t{a.get('id')}\ttick\t" + "; ".join(st["last"]["miss"]))
    st["skip"] = key if len(key) > 1 else None
    P.write_json(stp, st)


def zeus_clean(agents, t):
    stp = P.path("zeus-clean.json")
    st = P.read_json(stp, {}) or {}
    zs = [a for a in agents if a.get("name") == "zeus" and a.get("id") and a.get("sessionId")
          and a.get("state") not in ("stopped", "failed")]
    if not zs:
        if (st.get("last") or {}).get("result") != "нет Зевса":
            zeus_trace(st, stp, t, {}, [], 0, "нет Зевса")  # штаба нет или он остановлен — журнал не засоряем
        return
    if len(zs) != 1 or zs[0].get("kind") not in (None, "background"):  # копии или вкладка — решает человек
        why = f"копий Зевса {len(zs)}" if len(zs) != 1 else f"Зевс открыт не фоном ({zs[0].get('kind')})"
        return zeus_trace(st, stp, t, zs[0], [(0, why + " — решает человек")], 0, "пропуск")
    a = zs[0]
    if a["sessionId"] in (st.get("cleared") or []):
        return  # эту сессию уже очищали — новая ещё не появилась в claude agents (след — в cleared)
    tp = P.transcript_path(a)
    if not tp:
        return zeus_trace(st, stp, t, a, [(0, "нет транскрипта сессии")], 0, "пропуск")
    miss, n, info = zeus_clean_check(a, tp)
    hold = zeus_hold()
    if hold:  # защиты — раньше шести условий: ни очистки, ни напоминания
        return zeus_trace(st, stp, t, a, [(0, hold)] + miss, n, "пропуск")
    if not miss:
        f = st.get("failed") or {}
        if f.get("sid") == a["sessionId"] and t - float(f.get("t") or 0) < ZEUS_REMIND_MIN * 60:
            # прошлая попытка с этой сессией не вышла — повтор не чаще раза в час
            return zeus_trace(st, stp, t, a, [(7, f"прошлая попытка в {P.stamp(float(f['t']))[11:16]} не вышла — "
                                                  f"повтор не чаще раза в {ZEUS_REMIND_MIN} мин")], n, "пропуск")
        k, held = n // 1000, []

        def again():
            """Под блокировкой имени, перед claude stop: защиты и шесть условий — по свежему claude agents (Зевс мог
            получить ввод между проверкой и остановкой)."""
            why = zeus_hold()
            if not why:
                now_a = [x for x in P.agents_all() or [] if x.get("sessionId") == a["sessionId"]]
                why = "Зевса нет в claude agents" if not now_a else "; ".join(m for _, m in zeus_clean_check(now_a[0], tp)[0])
            held.append(why)
            return why or None
        text = P.fresh_text("очистка", "zeus", a.get("id"), "Контекст был %d тыс.: дежурный очистил, когда всё было "
                            "сохранено (metis-0136)." % k)
        rc = P.fresh_start("zeus", a, text, "tick", recheck=again, reason=f"очистка Зевса, контекст {k} тыс.")
        if rc == 0:
            st["cleared"] = ((st.get("cleared") or []) + [a["sessionId"]])[-20:]
            st.pop("failed", None)
            zeus_trace(st, stp, t, a, [], n, "очищен")
            P.alert(f"Зевс очищен в {P.stamp(t)[11:16]}, контекст {k} тыс. (прошлый разговор: claude attach {a.get('id')})",
                    "watch")
            event("zeus-clean", t, id=a.get("id"), tokens=n)
            return
        if not held or held[0]:
            # имя занято другим запуском или перед остановкой условие перестало выполняться (строка fresh-busy или
            # fresh-skip уже в start.log) — проверит следующий проход
            st["last"] = {"t": t, "at": P.stamp(t), "sid": a["sessionId"], "id": a.get("id"), "tokens": n,
                          "result": "отложено", "miss": [held[0] if held else "имя занято другим запуском"]}
            P.write_json(stp, st)
            return
        st["failed"] = {"sid": a["sessionId"], "t": t}
        zeus_trace(st, stp, t, a, [], n, f"не вышла, код {rc}")
        P.alert(f"очистка Зевса не вышла, код {rc} — контекст {k} тыс.; журнал start.log", "watch")
        return
    zeus_trace(st, stp, t, a, miss, n, "пропуск")
    if [m for m, _ in miss] != [5]:
        return  # напоминание — только когда не хватает одного сохранения; (6) — тихо ждём следующего прохода
    r = st.get("remind") or {}
    if t - float(r.get("t") or 0) < ZEUS_REMIND_MIN * 60 or (r.get("sid") == a["sessionId"] and r.get("turn") == info["turn"]):
        return  # не чаще раза в час и не повторять, пока у Зевса не было нового хода (прошлое напоминание не дошло)
    with contextlib.suppress(OSError):
        os.remove(P.ctx_mod().mark_path(a["sessionId"]))
    P.alert(f"Зевс: контекст {n // 1000} тыс., дежурный очистил бы, но {miss[0][1]} — сверь доску и handoff, "
            "тогда очистка пройдёт сама", "watch")
    st["remind"] = {"t": t, "sid": a["sessionId"], "turn": info["turn"]}
    P.write_json(stp, st)


# --- самозапуск координаторов (SCHED-09, решение владельца 15.10) --------------------------------------
# Будит сам только по задачам с решением владельца: «Очередь» или «В работе», куда их перенесли вы на доске (или
# создали там карточку, ответили на её вопрос), либо ваш ответ Зевсу окном вопросов на «[id] …». Решения учитываются
# только с момента, когда дежурный включился (autostart-since): старые карточки после выпуска никого не будят. Журналы
# ваших слов пишут хук и тик, не роли, — черновик агента в «Очереди» основанием не служит. Не больше двух направлений
# сразу и трёх сессий всего, пауза выше лимита, под паузой и при техперезапуске, «остановлено вами» не будит, без
# доверия к папке — тревога вместо запуска. Сбой (сессия не стартовала или упала раньше 30 мин) — пауза растёт 1 ч →
# 2 ч → 4 ч, после трёх подряд самозапуск направления встаёт до `pantheon resume <имя>` или `pantheon wake <имя>`.
# Каждый самозапуск — строка в alerts.md (её Зевс несёт в сводку).

def sanction_since(t, preview=False):
    p = P.path("autostart-since")
    try:
        since = float(open(p).read().strip())
    except (OSError, ValueError):
        since = t
        if not (preview or dry()):  # пробный прогон до включения не сдвигает начало учёта
            P.write_atomic(p, f"{int(t)}\n")
    return max(since, t - OWNER_SANCTION_DAYS * 86400)


def owner_marked(since):
    """id задач, по которым есть ваше решение позже since: ход на доске или ответ Зевсу окном вопросов —
    списком в порядке первой отметки (по времени)."""
    first = {}  # id -> время первой отметки
    with contextlib.suppress(OSError):
        for line in open(P.path("owner-log", "board.jsonl"), encoding="utf-8"):
            try:
                rec = json.loads(line)
                ts = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
            except (ValueError, TypeError, AttributeError):
                continue
            if ts < since or not isinstance(rec.get("id"), str):
                continue
            kind = rec.get("kind")
            if kind == "move" and rec.get("dst") in ("Очередь", "В работе") or kind in ("new", "answer", "request"):
                first[rec["id"]] = min(ts, first.get(rec["id"], ts))
    with contextlib.suppress(OSError):
        text = open(P.path("owner-log", "zeus.md"), encoding="utf-8").read()
        heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
        for i, m in enumerate(heads):
            if m.group(2).strip() != "· окно вопросов":
                continue
            try:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                ts = since
            if ts < since:
                continue
            body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
            q = re.match(r"вопрос: \[([a-z][a-z0-9]*-\d{4})\]", body, re.I)
            if q:
                qid = q.group(1).lower()
                first[qid] = min(ts, first.get(qid, ts))
    return [i for i, _ in sorted(first.items(), key=lambda kv: kv[1])]  # sorted устойчива: при равном времени — порядок вставки


def trusted(folder):
    """Доверие Claude Code ищется по корню git: репозиторий — только своё «Да», папка без git наследует от
    родителя (проверено 15.10). Без доверия `claude --bg` в папке не стартует."""
    try:
        cj = json.load(open(os.path.join(P.HOME, ".claude.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return False
    proj = cj.get("projects") or {}
    ok = lambda d: bool((proj.get(d) or {}).get("hasTrustDialogAccepted"))  # noqa: E731
    d = os.path.realpath(folder)
    while True:
        if ok(d):
            return True
        if os.path.isdir(os.path.join(d, ".git")) or d in (P.HOME, os.sep):
            return False
        d = os.path.dirname(d)


def as_state(v):
    """Запись autostart.json: {last, fails, next, pending, gave_up}; до 0.10.0 там было только время запуска."""
    if isinstance(v, dict):
        return v
    try:
        return {"last": float(v)}
    except (TypeError, ValueError):
        return {}


def autostart_check(agents, registry, st, t):
    """Итог прошлых самозапусков: проработала ≥ 30 мин или закончила ход — сбои забыты; упала или не появилась —
    сбой, пауза растёт; три подряд — самозапуск направления встаёт."""
    for d, s in list(st.items()):
        if not s.get("pending"):
            continue
        last = float(s.get("last") or 0)
        hold = holders(d, agents, registry)
        if hold and nudge_target(hold) and t - last >= 60:
            # снова простаивает после запуска или передачи задания (metis-0212): успех, только если сдвинула STATUS.md;
            # иначе сбой — бесполезная передача не повторяется каждый час, три подряд — самозапуск встаёт
            moved = False
            with contextlib.suppress(OSError):
                moved = os.stat(os.path.join(P.PANTHEON, "directions", d, "STATUS.md")).st_mtime > last
            if moved or t - last >= AUTOSTART_HEALTHY:
                succeeded(s)
            else:
                fail(d, s, t, f"снова простаивает через {(t - last) / 60:.0f} мин, STATUS.md не менялся")
            continue
        if hold:
            if t - last >= AUTOSTART_HEALTHY:
                succeeded(s)
            continue
        mine = [a for a in agents if a.get("name") == d and (a.get("startedAt") or 0) / 1000 >= last - 60]
        newest = max(mine, key=lambda a: a.get("startedAt") or 0) if mine else None
        if newest and newest.get("state") in ("done", "stopped") and t - last >= 60:
            # закончила ход раньше 30 мин: успех, только если сдвинула STATUS.md (сделала и записала); иначе это сбой —
            # задача, которую координатор сделать не может, будила бы его каждый час (ревью argus)
            moved = False
            with contextlib.suppress(OSError):
                moved = os.stat(os.path.join(P.PANTHEON, "directions", d, "STATUS.md")).st_mtime > last
            if moved or t - last >= AUTOSTART_HEALTHY:
                succeeded(s)
            else:
                fail(d, s, t, f"закончила ход за {(t - last) / 60:.0f} мин, STATUS.md не менялся")
        elif t - last >= 300:
            fail(d, s, t, "сессия упала" if newest else "сессия не появилась в claude agents")


def succeeded(s):
    """Запуск или передача задания удались: сбои забыты, и пауза после сбоя (`next`) — тоже. Иначе прошедший `next`
    пускал бы следующую попытку на первом же проходе, а не через час после этой (ревью argus: 6 перезапусков за 20 мин)."""
    s.update(pending=False, fails=0)
    s.pop("next", None)


def fail(d, s, t, why):
    s["fails"] = int(s.get("fails") or 0) + 1
    s["pending"] = False
    s["next"] = t + AUTOSTART_BACKOFF * 2 ** (s["fails"] - 1) * random.uniform(0.9, 1.1)
    if s["fails"] >= AUTOSTART_FAILS_MAX:
        s["gave_up"] = True
        P.alert(f"самозапуск {d} остановлен после {s['fails']} сбоев подряд (последний: {why}) — разобраться и вернуть: "
                f"pantheon resume {d} или pantheon wake {d}", "watch")
        # новый эпизод «встал»: прежняя отметка once могла не сняться (после resume сессия жива — сброса в
        # autostart() нет), иначе повторное «встал» в течение 7 дней пропало бы без macOS и без сводки (ревью argus)
        P.clear_fault(f"autostart-gaveup-{d}")
        P.notify_soon(f"autostart-gaveup-{d}", gave_up_note(d, s), group=f"autostart-{d}", once=True)
    else:
        P.alert(f"самозапуск {d}: сбой {s['fails']} из {AUTOSTART_FAILS_MAX} ({why}); следующая попытка не раньше "
                f"{P.stamp(s['next'])[11:16]}", "watch")


def autostart(agents, registry, doms, t, dry=False):
    say = print if dry else (lambda *_: None)
    st = {d: as_state(v) for d, v in P.read_json(P.path("autostart.json"), {}).items()}
    # pantheon resume|wake <имя> сбрасывают счётчик сбоев меткой, а не правкой autostart.json: проход идёт минутами,
    # и его запись в конце затёрла бы их правку (ревью argus)
    with contextlib.suppress(OSError):
        for f in os.listdir(P.path("autostart-reset")):
            st.pop(f, None)
            if not dry:
                os.remove(P.path("autostart-reset", f))
    if not dry:
        autostart_check(agents, registry, st, t)
    try:
        tasks = P.tasks_mod().load_tasks(P.PANTHEON)
    except Exception:
        tasks = {}
    since = sanction_since(t, preview=dry)
    marked = owner_marked(since)
    want = {}
    for tid in marked:  # порядок отметок владельца
        h = (tasks.get(tid) or (None, {}, None))[1]
        d = h.get("direction")
        if h.get("status") in ("todo", "doing") and d in doms:
            want.setdefault(d, []).append(tid)
    say(f"решения владельца учитываются с {P.stamp(since)}; задачи с ними: "
        + ("; ".join(f"{d}: {', '.join(v)}" for d, v in sorted(want.items())) or "нет"))
    running = [d for d in doms if holders(d, agents, registry)]
    shop = sorted({a.get("name") for a in list(agents) + list(registry) if str(a.get("name") or "").startswith("daedalus-")
                   and holders(a["name"], agents, registry)})
    started = False
    for d, tids in sorted(want.items()):
        s = st.setdefault(d, {})
        hold = holders(d, agents, registry)
        # простаивающий держатель (metis-0212) — передать той же сессии то же задание, а не «уже работает»: Claude Code
        # сам перезапустил фоновую сессию и задания у неё нет (working + idle) или закончила ход с живым процессом (done)
        poke = nudge_target(hold)
        if hold and not poke:
            say(f"{d}: уже работает")
            continue
        what = (f"{d}: закончила ход, а задачи с вашим решением ждут" if poke and poke.get("state") == "done"
                else f"{d}: Claude Code сам перезапустил фоновую сессию, задания у неё нет")
        why = wake_block(d, agents, registry, auto=True, nudge=bool(poke))
        if not why and s.get("gave_up"):
            why = f"самозапуск встал после сбоев (pantheon resume {d})"
        if not why and not poke and len(running) >= AUTOSTART_MAX:  # передача места не занимает: сессия уже есть
            why = f"нет места: уже работают {', '.join(running)} (не больше {AUTOSTART_MAX} направлений)"
        if not why and not poke and len(running) + len(shop) >= SESSIONS_MAX:
            why = f"нет места: сессий Пантеона {len(running) + len(shop)} из {SESSIONS_MAX}"
        # новое дело: жёлтая зона днём, тяжёлые, ночь и её бюджет, утро после 04:00 (metis-0127); передача задания —
        # тоже новое дело, а простаивающий держатель тяжёлым не считается (его working остался от прежнего процесса)
        if not why:
            ok, gw = P.night_mod().gate("autostart", t, [a for a in agents if a not in hold], registry)
            why = None if ok else f"недельный лимит: {gw}"
        nxt = float(s.get("next") or float(s.get("last") or 0) + AUTOSTART_BACKOFF)
        if not why and t < nxt:
            why = f"пауза между попытками до {P.stamp(nxt)[11:16]}"
        if not why and started:
            why = "одна сессия за проход — в следующий"
        got = None
        if not why:
            got = P.start_target(d, [])
            if isinstance(got, str):
                why = got
            elif not trusted(got[2]):
                why = f"нет доверия к {got[2].replace(P.HOME, '~')} — одна интерактивная сессия claude там и «Да»"
        if dry:
            if poke:
                say(f"{what} — " + (f"передача задания ждёт: {why}" if why else
                                    f"передал бы задание сейчас (задачи {', '.join(tids[:5])})"))
            else:
                say(f"{d}: " + (f"ждёт — {why}" if why else f"поднял бы сейчас (задачи {', '.join(tids[:5])})"))
            continue
        if not s.get("gave_up"):  # сбои сняты (resume, удачный запуск) — следующий «встал» снова macOS
            P.clear_fault(f"autostart-gaveup-{d}")
        if got is not None and not isinstance(got, str) and not (why or "").startswith("нет доверия"):
            P.clear_fault(f"autostart-trust-{d}")  # доверие есть
        if why:
            if s.get("gave_up"):  # самозапуск встал и держится — одна macOS, пока не снимут
                P.notify_soon(f"autostart-gaveup-{d}", gave_up_note(d, s), group=f"autostart-{d}", once=True)
            if why.startswith("нет доверия"):
                P.alert_once(f"autostart-trust-{d}", got[2], f"самозапуск {d} невозможен: {why}", "watch")
                P.notify_soon(f"autostart-trust-{d}", f"{d}: нужно ваше доверие к папке", group=f"autostart-{d}",
                              once=True)
            elif not why.startswith(("пауза между", "одна сессия", "не главный Mac", "недельный лимит")):
                P.alert_once(f"autostart-wait-{d}", f"{today(t)}-{why[:40]}", f"самозапуск {d} ждёт: {why} (задачи "
                             f"{', '.join(tids[:3])})", "watch")
            continue
        task = (f"Самозапуск дежурным по задачам с вашим решением (в порядке ваших отметок): {', '.join(tids)}. Прочитай STATUS.md и "
                "задачи, продолжай с первой по приоритету; что ждёт владельца — Зевсу строкой.")
        s.update(last=t, pending=True)
        P.write_json(P.path("autostart.json"), st)  # до запуска: проход могут оборвать по таймауту
        if poke:  # тот же путь, что продолжение остановленной: claude respawn + текст для хука push (P.resume_session)
            rc = P.resume_session(d, poke, task, "tick", recheck=recheck(d, True, nudge=True))[0]
            P.alert(f"{what} — " + (f"передал задание (задачи {', '.join(tids[:5])})" if rc == 0 else
                                    f"передать задание не вышло, код {rc}"), "watch")
        else:
            rc = resume_or_start(d, agents, task, origin="tick", auto=True)
            P.alert(f"самозапуск: {d} по задачам {', '.join(tids[:5])} — " + ("запущен" if rc == 0 else
                                                                               f"не вышло, код {rc}"), "watch")
        if rc != 0:
            fail(d, s, t, f"код запуска {rc}")
        else:  # список сессий этого прохода её ещё не видит — «запрет сна Mac» держится по этой метке
            awake().RESUMED.append(d)
        if not poke:
            running.append(d)
        started = True
    if not dry:
        P.write_json(P.path("autostart.json"), st)


def resume_or_start(name, agents, text, origin, only_resume=False, auto=False):
    """Остановленная или упавшая сессия направления — продолжить её же (контекст эпика сохраняется, с её именем и
    окном — P.resume_session); нет такой — новая через pantheon start."""
    alias = P.name_alias(name)
    old = [a for a in agents if alias.fullmatch(str(a.get("name") or "")) and a.get("state") in ("stopped", "failed")
           and a.get("sessionId")]
    if old:
        a = max(old, key=lambda a: a.get("startedAt") or 0)
        fresh = P.fresh_reason(a)  # metis-0147 п. 2: контекст большой, кэш остыл — новая сессия с файла состояния
        if fresh:
            return P.fresh_start(name, a, P.fresh_text("свежий старт", name, a.get("id"), text), origin,
                                 recheck=recheck(name, auto), reason=fresh)
        return P.resume_session(name, a, text, origin, recheck=recheck(name, auto))[0]
    if only_resume:
        return 1
    if dry():
        print(f"[start] {name} --from {origin}")
        return 0
    limit = start_timeout()
    try:
        r = subprocess.run([os.path.join(P.PLUGIN, "bin", "pantheon"), "start", name, "--from", origin, text],
                           capture_output=True, text=True, timeout=limit, env=P.run_env())
    except subprocess.TimeoutExpired:  # metis-0141 п. 1: без трассировки — строка в тревогах и код, как у задач тика
        P.alert(f"запуск {name}: pantheon start не уложился в {limit:.0f} с и остановлен — сессия могла и подняться; "
                "не появится — следующий проход засчитает сбой", "watch")
        return 124
    return r.returncode


# metis-0141 п. 1: срок pantheon start из дежурного. Шаги _start_session по их собственным срокам: claude agents 60 с,
# claude stop копии «done» 60 с, ожидание имени PANTHEON_STOP_WAIT 30 с + устойчивость 10 с, ещё claude agents 60 с,
# claude --bg 180 с, проверка имени 10 с — около 410 с; было 300 с. Срок поднят, а не ожидание имени урезано: ожидание
# защищает от ожившей копии (15.10 Фемида ожила через 7 с, metis-0041) и большую часть срока не занимает. 420 с меньше
# срока прохода дежурного (timeout = 600 в schedule.toml). PANTHEON_START_TIMEOUT — подмена для тестов.
START_TIMEOUT = 420.0


def start_timeout():
    with contextlib.suppress(ValueError, TypeError):
        v = float(os.environ.get("PANTHEON_START_TIMEOUT") or START_TIMEOUT)
        if v > 0:
            return v
    return START_TIMEOUT


# --- раз в сутки: журналы ваших слов (COMM-10, аудит 1.1 §7) ------------------------------------------------
# Один писатель уборки — дежурный (хук только дописывает). Записи старше 30 дней уходят, в том числе у снятых
# направлений; файл без записей удаляется. Целостность: запись из будущего, заголовок без текста, права шире 0600 —
# тревога (права дежурный сужает сам). Отпечаток каждого журнала — в owner-log-hashes.json рядом, вне каталога
# журналов: если старая часть журнала изменилась не уборкой — тревога. Сбои хуков ctx-hooks.log за сутки — тревога,
# журнал длиннее HOOK_LOG_MAX — обрезается.

ENTRY_HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$")


def daily(t):
    mark = P.path("watch-daily")
    with contextlib.suppress(OSError):
        if open(mark).read().strip() == today(t):
            return
    owner_logs(t)
    hook_log(t)
    P.write_atomic(mark, today(t) + "\n")


def _log_entries(text):
    out, cur = [], None
    for ln in text.split("\n"):
        m = ENTRY_HEAD.match(ln)
        if m:
            cur = [m.group(1), m.group(2), []]
            out.append(cur)
        elif cur is not None:
            cur[2].append(ln)
    return out


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def owner_logs(t):
    base = P.path("owner-log")
    if not os.path.isdir(base):
        return
    hashes_p = P.path("owner-log-hashes.json")
    hashes = P.read_json(hashes_p, {})
    edge = datetime.fromtimestamp(t - OWNER_LOG_DAYS * 86400).strftime("%Y-%m-%d %H:%M:%S")
    future = datetime.fromtimestamp(t + 300).strftime("%Y-%m-%d %H:%M:%S")
    edge_iso = edge.replace(" ", "T")
    files = []
    for sub in ("", "unconfirmed"):
        d = os.path.join(base, sub)
        with contextlib.suppress(OSError):
            files += [os.path.join(d, f) for f in os.listdir(d) if f.endswith((".md", ".jsonl"))]
    if os.stat(base).st_mode & 0o077:
        os.chmod(base, 0o700)
        P.alert_once("owner-log-perm-dir", "1", "журналы ваших слов: каталог owner-log был открыт другим — права "
                     "сужены до 0700", "watch")
    seen = set()
    for f in sorted(files):
        key = os.path.relpath(f, base)
        seen.add(key)
        # та же блокировка, что у пишущего: журналы сессий — <файл>.lock хука ctx.py, board.jsonl — locks/board
        # (пишет pantheon board под P.lock("board")): иначе запись, дописанная во время уборки, пропала бы
        with (_file_lock(f + ".lock") if f.endswith(".md") else P.lock("board")):
            raw = open(f, "rb").read()
            prev = hashes.get(key) or {}
            if prev.get("size") and (len(raw) < prev["size"] or _sha(raw[:prev["size"]]) != prev.get("sha")):
                P.alert_once(f"owner-log-changed-{key}", _sha(raw)[:16], f"журнал ваших слов {key}: "
                             + ("укорочен" if len(raw) < prev["size"] else "изменена уже записанная часть")
                             + " — не дописывание и не уборка дежурного; проверить, кто правил", "watch",
                             note="Журнал ваших слов изменён задним числом", group="owner-log",
                             critical=True)  # подделка журнала согласия — COMM-08: сразу, и ночью
            if os.stat(f).st_mode & 0o077:
                os.chmod(f, 0o600)
                P.alert_once(f"owner-log-perm-{key}", "1", f"журнал ваших слов {key} был открыт другим — права сужены "
                             "до 0600", "watch")
            text = raw.decode("utf-8", "replace")
            if f.endswith(".jsonl"):
                # только по \n: splitlines() режет и по U+2028, U+0085, которые json.dumps не экранирует (ревью argus)
                lines = [ln for ln in text.split("\n") if ln]
                keep = [ln for ln in lines if not _old_json(ln, edge_iso)]
            else:
                items = _log_entries(text)
                if any(ts > future for ts, _, _ in items):
                    P.alert_once(f"owner-log-future-{key}", "1", f"журнал ваших слов {key}: запись с временем из "
                                 "будущего — подделка или сбой часов", "watch")
                empty = [ts for ts, _, body in items if not "\n".join(body).strip()]
                if empty:
                    P.alert_once(f"owner-log-empty-{key}", empty[-1], f"журнал ваших слов {key}: заголовок без текста "
                                 f"({empty[-1]}) — запись оборвана", "watch")
                keep_items = [x for x in items if x[0] >= edge]
                lines = items
                keep = keep_items
            if len(keep) != len(lines):
                if not keep:
                    os.remove(f)
                    hashes.pop(key, None)
                    continue
                new = ("\n".join(keep) + "\n") if f.endswith(".jsonl") else "".join(
                    f"## {ts}{note}\n" + "\n".join(body).strip("\n") + "\n\n" for ts, note, body in keep)
                tmp = f + ".tmp"
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(new)
                os.replace(tmp, f)
                raw = new.encode("utf-8")
            hashes[key] = {"size": len(raw), "sha": _sha(raw), "time": t}
    for key in list(hashes):
        if key not in seen:
            P.alert_once(f"owner-log-gone-{key}", "1", f"журнал ваших слов {key} пропал — удалён не уборкой дежурного; "
                         "проверить, кто удалил", "watch", note="Журнал ваших слов удалён", group="owner-log",
                         critical=True)
            hashes.pop(key)
    P.write_json(hashes_p, hashes)
    with contextlib.suppress(OSError):
        os.chmod(hashes_p, 0o600)


@contextlib.contextmanager
def _file_lock(p):
    import fcntl
    fd = os.open(p, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _old_json(line, edge_iso):
    try:
        return str(json.loads(line).get("time", ""))[:19] < edge_iso
    except (ValueError, AttributeError):
        return False


HOOK_FAIL = re.compile(r"\b[A-Z]\w*(?:Error|Exception|Exit)\b: |без доставки")


def hook_log(t):
    p = P.path("logs", "ctx-hooks.log")
    try:
        size = os.path.getsize(p)
    except OSError:
        return
    since = datetime.fromtimestamp(t - 86400).strftime("%Y-%m-%d %H:%M")
    recent = 0
    with contextlib.suppress(OSError):
        for ln in open(p, encoding="utf-8", errors="replace"):
            # в журнале и пояснения (пропуск, сверка по транскрипту) — тревога только на сбой хука и недоставленный текст
            recent += ln[:16] >= since and bool(re.match(r"\d{4}-\d\d-\d\d", ln)) and bool(HOOK_FAIL.search(ln))
    if recent:
        P.alert_once("ctx-hooks-log", today(t), f"хуки контекста: сбоев за сутки {recent} — "
                     "журнал ~/.local/state/pantheon/logs/ctx-hooks.log (Метиде)", "watch")
    if size > HOOK_LOG_MAX:
        data = open(p, "rb").read()[-HOOK_LOG_MAX // 2:]
        P.write_atomic(p, data.decode("utf-8", "replace").split("\n", 1)[-1])


# --- остановка (SCHED-12) -------------------------------------------------------------------

def stop(rest, who):
    doms = domains()
    agents = P.agents_all()
    if agents is None:
        print("pantheon stop: claude agents --json не ответил", file=P.sys.stderr)
        return 1
    if rest[:1] == ["--all"]:
        had_pause = os.path.exists(P.path("paused"))
        open(P.path("paused"), "w").write(P.stamp())
        names = sorted({a.get("name") for a in agents if a.get("pid") and a.get("kind") != "interactive"
                        and is_pantheon(a.get("name") or "", doms) and not (a.get("name") or "").startswith("zeus")})
        marked = []
        left_all = []
        for n in names:
            if not os.path.exists(P.path("stopped", n)):
                marked.append(n)
            left_all += [(n, i, r) for i, r in _stop_one(n, agents, who)[1]]
        prev = P.read_json(P.path("stopped-all.json"), {}).get("names") or []
        old = P.read_json(P.path("stopped-all.json"), {})
        P.write_json(P.path("stopped-all.json"), {"time": P.stamp(), "by": who, "names": sorted(set(prev) | set(marked)),
                                                  "paused": bool(old.get("paused")) or not had_pause})
        if left_all:
            P.alert("стоп всё: осталась среди фоновых сессий Claude Code ("
                    + ", ".join(sorted({P.refused_by(r) for _, _, r in left_all})) + "): "
                    + "; ".join(f"{n} {i} — {r}" for n, i, r in left_all), "pantheon-stop")
        P.alert(f"стоп всё ({who}): планировщик на паузе, остановлены: {', '.join(names) or 'никого'}; вернуть — "
                "pantheon resume --all", "pantheon-stop")
        print(f"остановлены: {', '.join(names) or 'никого'}; планировщик на паузе. Вернуть: pantheon resume --all"
              + "".join(f"\n{n}: осталась среди фоновых сессий Claude Code: {i}, причина: {r}" for n, i, r in left_all))
        return 0
    if not rest or not P.SESSION_NAME.fullmatch(rest[0]):
        print("pantheon stop <направление|daedalus-задача> | --all", file=P.sys.stderr)
        return 2
    name = rest[0]
    if not is_pantheon(name, doms) or name.startswith("zeus"):
        print(f"pantheon stop: {name} — не сессия направления или мастерской", file=P.sys.stderr)
        return 2
    n, left = _stop_one(name, agents, who)
    if left:
        P.alert(f"{name}: осталась среди фоновых сессий Claude Code ({', '.join(sorted({P.refused_by(r) for _, r in left}))}): "
                f"{'; '.join(i + ' — ' + r for i, r in left)}",
                "pantheon-stop")
    P.alert(f"{name} остановлена ({who}): сессий {n}; дежурный и Зевс её не будят — вернуть: pantheon resume {name}",
            "pantheon-stop")
    print(f"{name}: остановлено сессий {n}, метка «остановлено вами» стоит. Вернуть: pantheon resume {name}"
          + _left_text(name, left))
    return 0


def _stop_one(name, agents, who):
    # та же блокировка имени, что у pantheon start и подъёма сессии: подъём, начатый до метки, не проскочит после неё
    with P.lock("start-" + name):
        return _stop_locked(name, agents, who)


def _stop_locked(name, agents, who):
    os.makedirs(P.path("stopped"), exist_ok=True)
    P.write_atomic(P.path("stopped", name), f"{P.stamp()} {who}\n")
    n = 0
    left = []
    for a in P.live_copies(name, agents, registry=[]) + [a for a in agents if a.get("name") == name
                                                          and a.get("state") == "done" and a.get("pid")]:
        if a.get("id"):
            reason = P.stop_and_rm(name, a["id"])  # metis-0239: без rm Claude Code сам перезапускает фоновую сессию
            P.start_log(f"stop\t{name}\t{a.get('name')}\t{a['id']}\t{who}")
            if reason:
                P.start_log(f"rm-refused\t{name}\t{a['id']}\t{reason}")
                left.append((a["id"], reason))
            n += 1
    return n, left


def _left_text(name, left):
    return "".join(f"\n{name}: осталась среди фоновых сессий Claude Code: {i}, причина: {r}" for i, r in left)


def _forget_autostart(name):
    os.makedirs(P.path("autostart-reset"), exist_ok=True)
    P.write_atomic(P.path("autostart-reset", name), P.stamp() + "\n")


CLAUDE_MARKS = ("PANTHEON_ROLE", "PANTHEON_SESSION", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def owner_word_ok():
    """Снять метку «остановлено вами» или ручную паузу — ваше слово: команда из вашего терминала (не из сессии Claude)
    или при вашей строке в журнале Зевса owner-log за 15 мин (как запуск --from zeus; ревью argus 15.10). По умолчанию —
    нельзя: любой признак сессии Claude требует строки журнала (проверка безопасности 0.10.0). Убрать признаки из
    окружения роль не может, не выйдя из своей строки excludedCommands, — а в песочнице состояние ей не записать."""
    if not any(os.environ.get(k) for k in CLAUDE_MARKS):
        return True
    return P.owner_spoke_recently("zeus", P.OWNER_WORD_WINDOW)


def resume(rest, who):
    if not owner_word_ok():
        print("pantheon resume: снять метку можно только по слову владельца — в журнале Зевса нет его строки за "
              f"{P.OWNER_WORD_WINDOW // 60} мин; попросите его сказать Зевсу «верни …» или выполнить команду в своём терминале",
              file=P.sys.stderr)
        P.alert(f"pantheon resume {' '.join(rest)[:60]} от {who} отклонён: нет свежего слова владельца", "pantheon-stop")
        return 1
    if rest[:1] == ["--all"]:
        info = P.read_json(P.path("stopped-all.json"), {})
        names = []
        for n in info.get("names") or []:
            with contextlib.suppress(FileNotFoundError):
                os.remove(P.path("stopped", n))
                names.append(n)
        with contextlib.suppress(FileNotFoundError):
            os.remove(P.path("stopped-all.json"))
        if info.get("paused") or not info:  # паузу от pantheon jobs pause --all не трогает
            with contextlib.suppress(FileNotFoundError):
                os.remove(P.path("paused"))
        left = sorted(os.listdir(P.path("stopped"))) if os.path.isdir(P.path("stopped")) else []
        P.alert(f"возврат всего ({who}): планировщик снова идёт, метки «стоп всё» сняты: {', '.join(sorted(names)) or 'нет'}"
                + (f"; остановленные по одной остаются: {', '.join(left)}" if left else ""), "pantheon-stop")
        print(f"планировщик идёт; метки «стоп всё» сняты: {', '.join(sorted(names)) or 'нет'}"
              + (f"\nостановлены по одной (их снимает pantheon resume <имя>): {', '.join(left)}" if left else "")
              + "\nСессии поднимет самозапуск по задачам с вашим решением или pantheon wake <имя>")
        return 0
    if not rest or not P.SESSION_NAME.fullmatch(rest[0]):
        print("pantheon resume <имя> | --all", file=P.sys.stderr)
        return 2
    name = rest[0]
    _forget_autostart(name)
    try:
        os.remove(P.path("stopped", name))
    except FileNotFoundError:
        print(f"{name}: метки «остановлено вами» нет; счётчик сбоев самозапуска сброшен")
        return 0
    info = P.read_json(P.path("stopped-all.json"), None)
    if info and name in (info.get("names") or []):
        info["names"].remove(name)
        P.write_json(P.path("stopped-all.json"), info)
    P.alert(f"{name}: метка «остановлено вами» снята ({who})", "pantheon-stop")
    print(f"{name}: метка снята. Поднять сейчас — pantheon wake {name}")
    return 0


# --- технический перезапуск (SCHED-15) --------------------------------------------------------------
# Слово владельца 15.10: «пошли им всем уведомление о техническом перезапуске всей системы, пусть сохраняются и
# отпишутся зевсу … также наверное такое технический перезапуск нужно встроить в систему».
# 1) `pantheon restart --prepare` — метка maintenance.json (срок 2 ч) со списком живых сессий Пантеона; пока она стоит,
#    дежурный и pantheon wake никого не будят. Хук ctx.py даёт каждой из них при следующем вызове инструмента
#    указание сохраниться и выполнить `pantheon saved`; Зевс пишет каждой сообщением. После `saved` хук не даёт сессии
#    работать дальше (кроме отчёта Зевсу).
# 2) `pantheon restart --status` — кто сохранился. 3) `pantheon restart --go` — сохранившиеся останавливаются и
#    продолжаются той же сессией с её именем и окном (новые плагины, роли и Claude Code берутся при старте процесса);
#    повтор --go не трогает уже перезапущенные. Зевс — интерактивная сессия владельца: его перезапуск —
#    `pantheon start zeus --restart` во вкладке iTerm. Метка истекла — дежурный снимает её с тревогой.

def maint_path():
    return P.path("maintenance.json")


def maint_clear():
    with contextlib.suppress(FileNotFoundError):
        os.remove(maint_path())
    with contextlib.suppress(FileNotFoundError):
        for f in os.listdir(P.path("maintenance")):
            with contextlib.suppress(OSError):
                os.remove(P.path("maintenance", f))


def maint_expire(t):
    m = P.read_json(maint_path(), None)
    if isinstance(m, dict) and m and t > float(m.get("expires") or 0):
        maint_clear()
        P.alert(f"метка технического перезапуска ({m.get('reason')}, с {str(m.get('id'))[11:16]}) истекла за "
                f"{MAINT_HOURS} ч без pantheon restart --go — снята, самозапуск и wake снова работают; сохранившиеся "
                "сессии стоят — поднять: pantheon wake <имя>", "watch")
        P.notify_soon("restart", "Техперезапуск не завершён: метка снята по сроку")


# --- перезапуск свободных окон после обновления плагинов (metis-0181) ----------------------------------------------
# `pantheon plugins update` ставит plugins/respawn.json {"since", "plugins", "done"}; тик перезапускает окна Пантеона,
# поднятые раньше since, — только свободные. «Простаивает» ≠ «свободно»: координатор idle, пока ждёт фоновых лидов, а
# claude agents субагентов не показывает. Свободно = idle_holder и одно из: метка «можно» (pantheon saved) новее since
# или RESPAWN_IDLE_MIN минут без записи транскрипта, журналов субагентов и worktree окна. Занятое ждёт следующего прохода.

WT_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", ".turbo", ".cache", "dist", "build"}


def respawn_path(*parts):
    return P.path("plugins", *parts)


def _live(a):
    """Сессия с живым процессом — та же мерка, что у holders: остановленная и упавшая новые плагины возьмут при старте."""
    return a.get("state") in ("working", "blocked") or bool(a.get("pid") and a.get("state") not in ("stopped", "failed"))


def respawn_candidates(agents, doms, m):
    """Окна, которым нужен перезапуск: имя Пантеона, не Зевс (его перезапускаете вы), не остановлено вами, фоновая с id
    и sessionId, живая, поднята раньше since и ещё не перезапущена после него."""
    since, done = float(m.get("since") or 0), set(m.get("done") or [])
    out = []
    for a in agents:
        name = str(a.get("name") or "")
        if not is_pantheon(name, doms) or name.startswith("zeus") or not P.SESSION_NAME.fullmatch(name):
            continue
        if a.get("kind") not in (None, "background") or not a.get("id") or not a.get("sessionId"):
            continue
        if not _live(a) or a["sessionId"] in done or os.path.exists(P.path("stopped", name)):
            continue
        if float(a.get("startedAt") or 0) / 1000 >= since:
            continue
        out.append(a)
    return out


def _wt_recent(wt, lim):
    """Менялось ли в копии что-то позже lim: обход без .git и зависимостей, до WALK_LIMIT записей. Не уложился — считаем,
    что менялось: лучше подождать, чем убить лида."""
    n, stack = 0, [wt]
    with contextlib.suppress(OSError):
        if os.stat(wt).st_mtime > lim:
            return True
    while stack:
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for e in it:
                n += 1
                if n > WALK_LIMIT:
                    return True
                try:
                    if e.stat(follow_symlinks=False).st_mtime > lim:
                        return True
                    if e.is_dir(follow_symlinks=False) and e.name not in WT_SKIP:
                        stack.append(e.path)
                except OSError:
                    continue
    return False


def respawn_busy(a, doms, since, t):
    """Почему окно a сейчас нельзя перезапустить, или None — свободно."""
    if not idle_holder(a):
        return "занято"
    ok = P.read_json(respawn_path("respawn-ok", str(a.get("name")) + ".json"), {})
    if isinstance(ok, dict) and float(ok.get("t") or 0) > since:
        return None
    lim = t - RESPAWN_IDLE_MIN * 60
    tp = P.transcript_path(a)
    if not tp:
        return "нет транскрипта — простой не проверить"
    try:
        if os.path.getmtime(tp) > lim:
            return f"транскрипт менялся меньше {RESPAWN_IDLE_MIN} мин назад"
    except OSError:
        return "транскрипт не читается"
    with contextlib.suppress(OSError), os.scandir(os.path.join(tp[:-len(".jsonl")], "subagents")) as it:
        for e in it:
            if e.name.startswith("agent-") and e.name.endswith(".jsonl"):
                with contextlib.suppress(OSError):
                    if e.stat().st_mtime > lim:
                        return f"субагент писал меньше {RESPAWN_IDLE_MIN} мин назад"
    folders = [f for f in (doms.get(a.get("name")) or []) if isinstance(f, str)]
    if a.get("cwd"):
        folders.append(str(a["cwd"]))
    for f in dict.fromkeys(os.path.realpath(os.path.expanduser(x)) for x in folders):
        with contextlib.suppress(OSError), os.scandir(os.path.join(f, ".claude", "worktrees")) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False) and _wt_recent(e.path, lim):
                    return f"worktree {P.tilde(e.path)} менялась меньше {RESPAWN_IDLE_MIN} мин назад"
    return None


def respawn_recheck(name, sid, doms, since):
    """Под блокировкой имени перед самим перезапуском — по свежему claude agents: окно могло получить ввод."""
    def again():
        if os.path.exists(P.path("stopped", name)):
            return "остановлено вами"
        if P.maintenance_active():
            return "идёт технический перезапуск"
        now_a = [x for x in P.agents_all() or [] if x.get("sessionId") == sid]
        if not now_a:
            return "сессии нет в claude agents"
        return respawn_busy(now_a[0], doms, since, P.now())
    return again


def plugins_respawn(agents, doms, t):
    p = respawn_path("respawn.json")
    m = P.read_json(p, {})
    if not isinstance(m, dict) or not m or P.maintenance_active():
        return  # техперезапуск перезапускает всех сам
    if not agents:
        return  # пустой claude agents (сбой или перезапуск Claude Code) — не «все перезапущены»: отметку не снимаем
    since = float(m.get("since") or 0)
    done, wait = [], []
    for a in respawn_candidates(agents, doms, m):
        name, sid = a["name"], a["sessionId"]
        why = respawn_busy(a, doms, since, t)
        if why:
            wait.append(f"{name} ({why})")
            continue
        rc = P.resume_session(name, a, RESPAWN_TEXT, "plugins-respawn", recheck=respawn_recheck(name, sid, doms, since))[0]
        if rc != 0:
            wait.append(f"{name} (код {rc})")
            continue
        done.append(name)
        with P.lock("plugins-respawn"):
            cur = P.read_json(p, {})
            if not isinstance(cur, dict) or cur.get("since") != m.get("since"):
                break  # пока перезапускали, встала новая версия — отметку ведёт уже она
            cur["done"] = list(cur.get("done") or []) + [sid]
            P.write_json(p, cur)
        with contextlib.suppress(OSError):
            os.remove(respawn_path("respawn-ok", name + ".json"))
    if done:
        P.alert(f"перезапуск после обновления плагинов ({', '.join(m.get('plugins') or [])}): перезапущены "
                f"{', '.join(done)}" + (f"; ждут: {', '.join(wait)}" if wait else ""), "watch")
    if wait:
        # ждущие видны и без перезапусков в этом проходе: одна строка на набор окон (причины меняются каждый проход,
        # ключ — только имена), чтобы вечное ожидание (worktree больше WALK_LIMIT, вечный busy) не было тихим
        names = ",".join(sorted({w.split(" (", 1)[0] for w in wait}))
        P.alert_once("plugins-respawn-wait", names, f"перезапуск после обновления плагинов "
                     f"({', '.join(m.get('plugins') or [])}) ждёт: {', '.join(wait)}. Окно, готовое раньше: pantheon "
                     "saved --by <имя> --state <путь>", "watch")
        return
    P.clear_once("plugins-respawn-wait")
    with P.lock("plugins-respawn"):
        cur = P.read_json(p, {})
        if isinstance(cur, dict) and cur.get("since") == m.get("since"):
            with contextlib.suppress(OSError):
                os.remove(p)
            with contextlib.suppress(OSError):
                for f in os.listdir(respawn_path("respawn-ok")):
                    with contextlib.suppress(OSError):
                        os.remove(respawn_path("respawn-ok", f))


def restart(rest, who):
    m = P.read_json(maint_path(), None)
    if rest[:1] == ["--prepare"]:
        agents = P.agents_all()
        if agents is None:
            print("pantheon restart: claude agents --json не ответил", file=P.sys.stderr)
            return 1
        doms = domains()
        reg = P.sessions_registry()
        live = sorted({a.get("name") for a in list(agents) + reg if is_pantheon(a.get("name") or "", doms)
                       and holders(a.get("name"), agents, reg)})
        why = " ".join(" ".join(rest[1:]).split()) or "технический перезапуск"
        maint_clear()
        t = P.now()
        m = {"id": P.stamp(t), "since": t, "expires": t + MAINT_HOURS * 3600, "reason": why, "by": who,
             "sessions": live}
        P.write_json(maint_path(), m)
        P.alert(f"технический перезапуск готовится ({who}): {why}; сессии: {', '.join(live) or 'нет'}", "pantheon-restart")
        print(f"метка стоит {MAINT_HOURS} ч. Сессии ({len(live)}): {', '.join(live) or 'нет'}.\nХук скажет каждой при "
              "следующем шаге; Зевс — сообщение каждой: «сохранись, pantheon saved --by <имя> --state <путь>, отчитайся "
              "Зевсу».\nДальше: pantheon restart --status, затем pantheon restart --go")
        return 0
    if not m:
        print("технический перезапуск не готовится (pantheon restart --prepare)")
        return 1
    saved, done_marks = {}, set()
    with contextlib.suppress(FileNotFoundError):
        for f in os.listdir(P.path("maintenance")):
            if f.endswith(".json"):
                saved[f[:-5]] = P.read_json(P.path("maintenance", f), {})
            elif f.endswith(".done"):
                done_marks.add(f[:-5])
    if rest[:1] == ["--status"] or not rest:
        print(f"перезапуск с {m['id'][:16]} ({m.get('reason')}), метка до {P.stamp(float(m.get('expires') or 0))[11:16]}:")
        for n in m.get("sessions") or []:
            s = saved.get(n)
            print(f"  {n}: " + ("перезапущена" if n in done_marks else
                                f"сохранилась {s.get('time', '')[11:16]}, состояние — {s.get('state') or '—'}" if s
                                else "ещё нет"))
        return 0 if all(n in saved or n in done_marks or n.startswith("zeus") for n in m.get("sessions") or []) else 1
    if rest[:1] == ["--go"]:
        force = "--force" in rest
        agents = P.agents_all() or []
        done, skip, owner = [], [], []
        for n in m.get("sessions") or []:
            if n.startswith("zeus"):
                owner.append(n)
                continue
            if n in done_marks:
                done.append(n + " (раньше)")
                continue
            if n not in saved and not force:
                skip.append(n)
                continue
            if os.path.exists(P.path("stopped", n)):
                skip.append(n + " (остановлена вами)")
                continue
            # `claude respawn` перезапускает процесс той же сессии (живой или остановленной) с её флагами — новые
            # плагины, роли и Claude Code берутся при старте; текст отдаёт хук push (проверено 15.10)
            mine = [a for a in agents if a.get("name") == n and a.get("id") and a.get("sessionId")]
            if not mine:
                skip.append(f"{n} (нет фоновой сессии — вкладка? перезапустить вручную)")
                continue
            rc = P.resume_session(n, max(mine, key=lambda a: a.get("startedAt") or 0), RESTART_TEXT, "restart",
                                  recheck=lambda n=n: "остановлено вами" if os.path.exists(P.path("stopped", n))
                                  else None)[0]
            if rc == 0:
                os.makedirs(P.path("maintenance"), exist_ok=True)
                P.write_atomic(P.path("maintenance", n + ".done"), P.stamp() + "\n")
                with contextlib.suppress(FileNotFoundError):  # иначе хук перезапущенной сессии закрыл бы инструменты
                    os.remove(P.path("maintenance", n + ".json"))
                done.append(n)
            else:
                skip.append(f"{n} (код {rc})")
        if not skip:
            maint_clear()
        P.alert(f"технический перезапуск ({who}): перезапущены {', '.join(done) or 'никто'}"
                + (f"; не тронуты: {', '.join(skip)}" if skip else "")
                + ("; Зевс — вы сами: pantheon start zeus --restart во вкладке iTerm" if owner else ""), "pantheon-restart")
        print(f"перезапущены: {', '.join(done) or 'никто'}" + (f"\nне тронуты: {', '.join(skip)} (--force — без отметки; "
                                                              "повтор --go перезапущенные не трогает)"
                                                              if skip else "\nметка снята")
              + ("\nЗевс: pantheon start zeus --restart во вкладке iTerm (ваша сессия)" if owner else ""))
        return 0 if not skip else 1
    if rest[:1] == ["--cancel"]:
        maint_clear()
        P.alert(f"технический перезапуск отменён ({who})", "pantheon-restart")
        print("метка снята")
        return 0
    print("pantheon restart --prepare [причина] | --status | --go [--force] | --cancel", file=P.sys.stderr)
    return 2


def saved_cmd(rest, who):
    """pantheon saved --by <имя> --state <путь> — сессия сохранилась перед техническим перезапуском. Техперезапуска нет, а
    перезапуск после обновления плагинов ждёт (metis-0181) — метка «можно»: тик перезапустит окно, как только оно
    закончит ход, не дожидаясь RESPAWN_IDLE_MIN минут простоя."""
    m = P.maintenance_active()
    pend = None if m else P.read_json(respawn_path("respawn.json"), {})
    if not m and not (isinstance(pend, dict) and pend):
        print("технический перезапуск не готовится и перезапуска после обновления плагинов нет — отмечать нечего")
        return 1

    def opt(k):
        return rest[rest.index(k) + 1] if k in rest and rest.index(k) + 1 < len(rest) else None
    name, state = opt("--by") or P.os.environ.get("PANTHEON_SESSION") or "", opt("--state") or ""
    own = P.os.environ.get("PANTHEON_SESSION")
    if not P.SESSION_NAME.fullmatch(name):
        print("pantheon saved --by <имя сессии> --state <путь>", file=P.sys.stderr)
        return 2
    if own and name != own:
        print(f"pantheon saved: сессия {own} отмечает только себя, не {name}", file=P.sys.stderr)
        return 2
    if not m:
        P.write_json(respawn_path("respawn-ok", name + ".json"), {"t": P.now(), "time": P.stamp(),
                                                                  "state": " ".join(state.split())[:300], "by": who})
        print(f"{name}: отмечено «можно перезапускать». Плановый проход перезапустит окно с новыми плагинами, когда оно закончит ход; "
              "работающее окно не тронет")
        return 0
    if name not in (m.get("sessions") or []):
        print(f"pantheon saved: {name or '(без имени)'} нет в списке перезапуска: {', '.join(m.get('sessions') or [])}",
              file=P.sys.stderr)
        return 2
    os.makedirs(P.path("maintenance"), exist_ok=True)
    P.write_json(P.path("maintenance", name + ".json"), {"time": P.stamp(), "state": " ".join(state.split())[:300],
                                                          "by": who})
    print(f"{name}: отмечено «сохранилась». Отчитайся Зевсу строкой (SendMessage zeus) и жди перезапуска: дальше "
          "инструменты закрыты до pantheon restart --go")
    return 0


# --- пересмотры (SCHED-10, DOC-03) ---------------------------------------------------------------------

def _dates(v):
    return [v] if isinstance(v, str) else list(v or [])


def _after(spec, meta):
    m = re.fullmatch(r"(\w+)\+(\d+)d", str(spec).strip())
    if not m or not meta.get(m.group(1)):
        return None
    with contextlib.suppress(ValueError):
        return (date.fromisoformat(str(meta[m.group(1)])[:10]) + timedelta(days=int(m.group(2)))).isoformat()
    return None


def _map_rows():
    p = os.path.join(P.PANTHEON, "decision-map.md")
    rows = []
    with contextlib.suppress(OSError):
        for line in open(p, encoding="utf-8"):
            if line.startswith("| ") and not line.startswith(("| ---", "| ID ")):
                cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
                if re.match(r"^[A-Z]+-\d+$", cells[0]) and len(cells) >= 8:
                    rows.append(cells)
    return rows


def event_fired(ev, t):
    """(сработало ли событие, ключ срабатывания) — или (None, причина), если дежурный такое событие не видит. Ключ
    меняется с каждым новым срабатыванием (новая версия, новый день swap) — так напоминание идёт по фронту."""
    parts = ev.split(":")
    kind = parts[0]
    if kind == "cc_updated":
        evs = [e for e in events() if e.get("event") == "cc_updated"]
        return (True, f"cc-{evs[-1].get('version')}") if evs else (False, "")
    if kind == "swap_over" and len(parts) == 3:
        m = re.fullmatch(r"(\d+)/day", parts[2])
        if not m:
            return None, "формат swap_over:<ГБ>:<раз>/day"
        n = 0
        with contextlib.suppress(OSError):
            for ln in open(P.path("swap.jsonl"), encoding="utf-8"):
                with contextlib.suppress(ValueError, KeyError, TypeError):
                    r = json.loads(ln)
                    n += r["t"] >= t - 86400 and r["gb"] > float(parts[1])
        return (n >= int(m.group(1))), f"swap-{today(t)}"
    if kind == "step_done" and len(parts) == 2:
        rows = [r for r in _map_rows() if r[5] == parts[1]]
        return (bool(rows) and all(r[6] in ("проверено", "отклонено", "не сейчас") for r in rows)), "done"
    if kind == "epic_closed" and len(parts) == 3:
        with contextlib.suppress(OSError):
            for ln in open(os.path.join(P.PANTHEON, "directions", parts[1], "STATUS.md"), encoding="utf-8"):
                if parts[2] in ln and re.search(r"закрыт|closed|готов", ln, re.I):
                    return True, "done"
        return False, ""
    if kind == "tasks_done" and len(parts) == 3:
        with contextlib.suppress(Exception):
            n = sum(1 for _, h, _ in P.tasks_mod().load_tasks(P.PANTHEON).values()
                    if h.get("direction") == parts[1] and h.get("status") == "done")
            return n >= int(parts[2]), "done"
        return False, ""
    return None, f"событие «{ev}» дежурный пока не видит — сверяет Пританей"


def revisits():
    t = P.now()
    p = os.path.join(P.PANTHEON, "revisits.toml")
    try:
        with open(p, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, ValueError) as e:
        P.alert_once("revisits-read", type(e).__name__, f"revisits.toml не прочитать: {type(e).__name__}", "watch")
        return P.ALERTED
    meta, d0, fired = data.get("meta") or {}, today(t), 0
    sent = P.read_json(P.path("revisits-sent.json"), {})
    for r in data.get("revisit") or []:
        rid = str(r.get("id") or "")
        if not rid or r.get("status", "open") != "open":
            sent.pop(rid, None)
            continue
        why, keys = [], []
        dates = [x for x in _dates(r.get("due")) if re.fullmatch(r"\d{4}-\d\d-\d\d", str(x))]
        dates += [x for x in (_after(s, meta) for s in _dates(r.get("due_after"))) if x]
        if r.get("repeat") == "monthly" and dates:
            day = min(int(x[8:10]) for x in dates)
            this = f"{d0[:8]}{min(day, 28):02d}"
            dates = [x for x in dates if x > d0] + ([this] if this <= d0 else [])
            keys.append(d0[:7])
        past = sorted(x for x in dates if x <= d0)
        if past:
            why.append(f"срок {past[0]}")
            keys.append(past[0])
        for ev in _dates(r.get("event")):
            ok, key = event_fired(str(ev), t)
            if ok is None:
                P.alert_once(f"revisit-ev-{rid}-{ev}", "1", f"пересмотр {rid}: {key}", "watch")
            elif ok:
                why.append(f"событие {ev}")
                keys.append(key)
        if not why:
            sent.pop(rid, None)
            continue
        cfg = json.dumps([r.get("due"), r.get("due_after"), r.get("event"), keys], ensure_ascii=False, default=str)
        last = sent.get(rid) or {}
        if last.get("cfg") == cfg and t - float(last.get("t") or 0) < REVISIT_REPEAT_DAYS * 86400:
            continue
        again = last.get("cfg") == cfg
        P.alert(f"{'снова: ' if again else ''}пора пересмотреть {rid} ({', '.join(why)}): {r.get('what', '')} — "
                f"мерить: {r.get('measure', '—')}; итог готовит: {r.get('owner', 'Пританей')}"
                + ("; закрыть строку или перенести срок в revisits.toml" if again else ""), "watch")
        sent[rid] = {"cfg": cfg, "t": t}
        fired += 1
    P.write_json(P.path("revisits-sent.json"), sent)
    status_revisits(data)
    print(f"напоминаний о пересмотрах: {fired}")
    return 0


def status_revisits(data):
    """DOC-03: строка «пересмотр: …» в STATUS.md направления без записи в revisits.toml — штабу добавить строку."""
    known = {str(r.get("id")) for r in data.get("revisit") or []}
    base = os.path.join(P.PANTHEON, "directions")
    with contextlib.suppress(OSError):
        for d in sorted(os.listdir(base)):
            with contextlib.suppress(OSError):
                for ln in open(os.path.join(base, d, "STATUS.md"), encoding="utf-8"):
                    m = re.match(r"\s*[-*]?\s*пересмотр:\s*(.+)", ln, re.I)
                    if not m or any(k in known for k in re.findall(r"R-[\w-]+", m.group(1))):
                        continue
                    text = " ".join(m.group(1).split())[:200]
                    P.alert_once(f"revisit-new-{d}-{text}", "1", f"{d}: временное решение без строки в revisits.toml — "
                                 f"«{text}» (Пританею: строка пересмотра, ссылка R-… в STATUS.md)", "watch")


# --- who и wake <имя> (COMM-14, COMM-04) ----------------------------------------------------------------

def who():
    snap = P.read_json(P.path("agents.json"), None)
    agents = P.agents_all()
    if agents is None:
        agents = (snap or {}).get("agents") or []
    reg = P.sessions_registry()
    try:
        with open(os.path.join(P.PANTHEON, "directions.toml"), "rb") as fh:
            dirs = tomllib.load(fh).get("direction") or []
            reg_dirs = {d.get("name"): d for d in dirs}
    except (OSError, ValueError):
        reg_dirs = {}
    word = {"working": "работает", "blocked": "ждёт вас", "failed": "упала", "done": "закончила ход",
            "stopped": "остановлена", None: "открыта во вкладке"}
    rows = []
    for name in sorted(domains()):
        mine = [a for a in agents if P.name_alias(name).fullmatch(str(a.get("name") or ""))]
        tab = [r for r in reg if r.get("kind") == "interactive" and r.get("name") == name]
        a = max(mine, key=lambda a: a.get("startedAt") or 0) if mine else None
        state = ("остановлено вами" if os.path.exists(P.path("stopped", name)) else
                 f"пауза ({paused(name).get('reason')})" if paused(name) else
                 word.get(a.get("state"), a.get("state")) if a else "открыта во вкладке" if tab else "нет сессии")
        since = P.ago(a["startedAt"] / 1000) if a and a.get("startedAt") else ""
        short = str((reg_dirs.get(name) or {}).get("short") or (reg_dirs.get(name) or {}).get("does") or "")[:40]
        rows.append((name, state, short, since))
    w = [max(len(r[i]) for r in rows) if rows else 0 for i in range(3)]
    for r in rows:
        print(f"{r[0]:<{w[0]}}  {r[1]:<{w[1]}}  {r[2]:<{w[2]}}  {r[3]}")
    return 0


def wake_one(rest, who="владелец"):
    name = rest[0]
    if not P.SESSION_NAME.fullmatch(name):
        print("pantheon wake <имя> [\"задание\"]", file=P.sys.stderr)
        return 2
    agents = P.agents_all()
    if agents is None:
        print("pantheon wake: claude agents --json не ответил", file=P.sys.stderr)
        return 1
    why = wake_block(name, agents, P.sessions_registry(), auto=False)
    if why == "уже работает":
        print(f"{name} не спит (есть процесс) — передать задание сообщением: SendMessage, адрес {name}")
        return 0
    if why:
        hint = {"остановлено вами": f" — сначала pantheon resume {name}"}.get(why, "")
        print(f"пропуск: {name} — {why}{hint}")  # metis-0291: обычная причина не будить — не сбой
        return 0
    extra = " ".join(" ".join(rest[1:]).split())
    # чужой текст всегда под своей пометкой: под «[Пантеон: …]» без неё он выдал бы себя за системный (ревью argus)
    text = f"[Пантеон: задание от {who}] {extra}" if extra else WAKE_PUSH
    alias = P.name_alias(name)
    if not any(alias.fullmatch(str(a.get("name") or "")) and a.get("state") in ("stopped", "failed") for a in agents):
        print(f"пропуск: {name} — нет уснувшей сессии (новая: pantheon start {name})")
        return 0
    got = P.start_target(("workshop" if name.startswith("daedalus-") else name),
                         [name[len("daedalus-"):]] if name.startswith("daedalus-") else [])
    if not isinstance(got, str) and not trusted(got[2]):
        print(f"{name}: нет доверия к {got[2].replace(P.HOME, '~')} — одна интерактивная сессия claude там и «Да»",
              file=P.sys.stderr)
        return 1
    _forget_autostart(name)
    rc = resume_or_start(name, agents, text, origin="wake", only_resume=True)
    if rc == P.SKIPPED:  # recheck под блокировкой имени сказал «не надо»
        print(f"пропуск: {name} — {P.SKIP_WHY}")
        return 0
    print(f"{name}: " + ("поднята, задание передано" if rc == 0 else f"не поднялась, код {rc}"))
    return rc


# --- проверка опор (SEC-16) -------------------------------------------------------------------------------

def _managed_guard_active():
    """Управляемые настройки сами вызывают guard с --managed (то же условие, что managed_guard_active() в guard.py,
    файл — P.MANAGED на момент вызова): тогда и проба зовёт его так же, как живой хук."""
    try:
        with open(P.MANAGED, encoding="utf-8") as fh:
            data = json.load(fh)
        for group in ((data.get("hooks") or {}).get("PreToolUse") or []):
            for h in group.get("hooks") or []:
                cmd = h.get("command") or ""
                if "guard.py" in cmd and "--managed" in cmd:
                    return True
    except (OSError, ValueError, AttributeError, TypeError):
        return False
    return False


def _setup_python_line():
    """Строка infra-check «Python установки»: путь из config.toml (его пишет pantheon-setup) и его версия."""
    try:
        py = (_pconfig().load() or {}).get("python")
    except (OSError, ValueError, RuntimeError):
        py = None
    if not py:
        return True, "Python установки: не записан (установка без pantheon-setup)"
    try:
        r = subprocess.run([py, "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return True, f"Python установки: {py} ({r.stdout.strip()})"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False, f"Python установки: {py} записан, но не запускается"


def _pconfig():
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_pconfig", os.path.join(P.LIB, "pconfig.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HQ_MISSING = "в policy.toml нет раздела [hq]: Пританею ничего не закрыто"
CORPUS_MISSING = "в policy.toml нет раздела [corpus]: правило corpus-role ничего не закрывает"
HOOK_PYTHON = "python3"  # как в hooks.json guard; тесты подменяют
HOOKS_NO_TOMLLIB = ("python3 хуков без tomllib (Python до 3.11): guard не читает policy.toml, правило corpus-role "
                    "пусто — Метиде: python3 в PATH должен быть 3.11+")


def _corpus_declared(hq):
    """Объявлен ли корпус: в [hq] closed_dirs есть папка корпуса (составляющая пути `corpus`, `corpus-…` или
    `…-corpus`, например ~/projects/x-corpus) или в closed_collections — коллекция `corpus`."""
    for d in hq.get("closed_dirs") or []:
        if any(re.search(r"(?:^|-)corpus(?:-|$)", part.lower()) for part in d.split("/")):
            return True
    return any(c.lower() == "corpus" for c in hq.get("closed_collections") or [])


def infra_check():
    """Лёгкие проверки без модели: guard отказывает на запретном, хуки плагина на месте, claude agents отвечает,
    управляемые настройки совпадают с guard. Живые проверки (пробуждение после /clear, сообщение между сессиями,
    поднятие уснувшей) — в наборе проверок качества шага 1.6."""
    res = []

    def add(ok, text):
        res.append((bool(ok), text))

    g = P.guard_script() if hasattr(P, "guard_script") else None
    if g and os.path.exists(g):
        probe = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "agent_type": "dev-haiku",
                            "cwd": P.HOME, "tool_input": {"command": "git push --force origin main"}})
        argv = ["python3", "-I", g] + (["--managed"] if _managed_guard_active() else [])
        r = subprocess.run(argv, input=probe, capture_output=True, text=True, timeout=30)
        add(r.returncode == 2 or '"deny"' in r.stdout, "guard отказывает на git push --force (роль dev-haiku)")
    else:
        add(False, "guard найден")
    hooks = os.path.join(P.PLUGIN, "hooks", "hooks.json")
    try:
        hj = json.load(open(hooks, encoding="utf-8")).get("hooks") or {}
        add(all(k in hj for k in ("UserPromptSubmit", "Stop", "SessionStart", "PostToolUse")),
            "хуки pantheon: UserPromptSubmit, Stop, SessionStart, PostToolUse")
    except (OSError, ValueError):
        add(False, "hooks.json pantheon читается")
    add(P.agents_all() is not None, "claude agents --json отвечает")
    plug = os.path.join(P.HOME, ".claude", "plugins", "marketplaces", "agent-kit", "plugins", "guard",
                        "managed-settings.json")
    with contextlib.suppress(OSError):
        add(open(P.MANAGED, "rb").read() == open(plug, "rb").read(), "управляемые настройки совпадают с guard")
    pol = os.path.join(P.HOME, ".claude", "pantheon", "policy.toml")
    # что закрыто штабу — [hq] policy.toml, в коде значений нет (metis-0182): без раздела штабу не закрыто ничего
    try:
        hq = P.ctx_mod().hq_policy(pol)
    except ValueError as e:  # битый раздел: окно штаба не пересобирается, тревогу ставит pantheon domains build
        add(False, f"раздел [hq] policy.toml разбирается ({e})")
    else:
        add(hq["present"], "в policy.toml есть раздел [hq] (что закрыто Пританею)")
        if hq["present"]:
            P.clear_once("hq-policy-missing")
        else:
            P.alert_once("hq-policy-missing", "1", HQ_MISSING + " — Метиде: добавить раздел, образец — "
                         "policy.example.toml плагина guard", "watch")
    # [corpus] policy.toml — список правила corpus-role guard; без раздела оно не закрывает ничего (metis-0182)
    corpus = None
    try:
        with open(pol, "rb") as fh:
            corpus = "corpus" in tomllib.load(fh)  # битый раздел guard читает как «закрыто»
    except FileNotFoundError:
        corpus = False
    except (OSError, ValueError):
        pass  # файл не прочитать или не TOML — строка НЕТ уже есть у [hq]
    # тревога — только если корпус объявлен: в [hq] закрыта папка или коллекция корпуса (metis-0253, шаг 1);
    # чистая policy без корпуса ничего не теряет и не тревожит
    declared = False
    with contextlib.suppress(ValueError):
        declared = _corpus_declared(P.ctx_mod().hq_policy(pol))
    if corpus is not None and not (declared or corpus):
        P.clear_once("corpus-policy-missing")
    elif corpus is not None:
        add(corpus, "в policy.toml есть раздел [corpus] (что закрывает правило corpus-role)")
        if corpus:
            P.clear_once("corpus-policy-missing")
        else:
            P.alert_once("corpus-policy-missing", "1", CORPUS_MISSING + " — Метиде: добавить раздел, образец — "
                         "policy.example.toml плагина guard", "watch")
    # guard читает policy.toml через tomllib (Python 3.11+). Хуки зовут python3 из PATH: без tomllib guard
    # раздел [corpus] не видит и corpus-role молча пуст (metis-0182) — до перевода хуков на полный путь (0.5.11)
    try:
        ok = subprocess.run([HOOK_PYTHON, "-I", "-c", "import tomllib"], capture_output=True,
                            timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    add(ok, "python3 хуков читает policy.toml (tomllib, Python 3.11+)")
    if ok:
        P.clear_once("hooks-python-no-tomllib")
    else:
        P.alert_once("hooks-python-no-tomllib", "1", HOOKS_NO_TOMLLIB, "watch")
    add(*_setup_python_line())
    lines = [("готово  " if ok else "НЕТ     ") + text for ok, text in res]
    return all(ok for ok, _ in res), lines


def infra_cmd():
    ok, lines = infra_check()
    print("\n".join(lines))
    return 0 if ok else 1
