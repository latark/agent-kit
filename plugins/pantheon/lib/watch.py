"""Дежурный Пантеона без модели и управление сессиями (шаг 1.4).

  pantheon watch [--dry-run]  задача тика раз в 5 мин (SCHED-09): снимок `claude agents` для строки статуса и
                            `pantheon who` (COMM-14), ждущие и упавшие сессии Пантеона, давно не обновлённый и длинный
                            STATUS.md, swap и открытые подключения (COMM-13), виновники памяти в красной зоне — своп,
                            давление, нагрузка: процесс → чей → память → возраст, раз на эпизод (lib/culprits.py,
                            metis-0568), копии worktree (QA-05; node_modules и .next при проверке ссылок наружу — по верхнему уровню, metis-0616),
                            кэши песочниц ~/Library/Caches/pantheon-sandbox/<окно>/{tmp,npm,corepack,logs} старше 7 дн. без процессов
                            и потолок 5 ГБ с тревогой (metis-0620), смена версии
                            Claude Code (SCOUT-05, SEC-16), паузы по нагрузке (COST-04), самозапуск координаторов
                            (задачу с owner другой сессии не отдаёт, metis-0564), окна по вашему выбору «Да — запустить|перезапустить
                            <имя>» на вопрос pantheon launch-question в окне вопросов (metis-0523),
                            метка технического перезапуска, передача «ждёт вас» Зевсу (metis-0277), перезапуск свободных окон после обновления плагинов
                            (metis-0181), уборка: claude rm сессий Пантеона, закончивших ход или остановленных
                            больше 2 ч назад (metis-0250); раз в сутки — журналы ваших слов (COMM-10).
                            --dry-run — только показать, кого самозапуск поднял бы и почему нет, ничего не меняя
                            Самозапуск по отметкам отдаёт задачи сначала по depends_on, при равенстве — priority, порядок пачки (order), запас последним, затем порядок отметок
                            (tasks.plan_batch, metis-0248). Не отдаёт: с незакрытым предшественником вне пачки; с зависшим
                            (waiting/dropped/удалён или без изменений > 24 ч) — тревога «ждёт зависший»; в цикле — тревога,
                            без запуска; с пересечением непустых touches с идущей в другом направлении (пустой touches
                            ничего не блокирует); любое ожидание — тревога «<id> — ждёт <id>…». Потолок — 3 параллельных исполнителя (`AUTOSTART_MAX` жёстче: потолок самозапуска — не больше двух направлений сразу)
                            Цель окна (/goal самозапуска) держит задачу, которую передали другой сессии (owner),
                            перенесли, вернули во входящие или отменили — окно перезапускается свежей сессией с новой
                            целью; очереди нет или подъём закрыт и своих задач нет — останавливается; имя держит
                            другая сессия — смена отложена (metis-0631, goal_release, goal_block)
                            Поручения во входящих (lib/awake.py inbox_wake, metis-0276): координатор закончил ход или
                            его сессии нет, а в inbox/ — поручение Зевса после конца хода и по вашему слову ему —
                            новая сессия с /goal по поручению (pantheon start --from tick), под теми же шлюзами
  pantheon agents           только снимок `claude agents` (задача тика на каждый проход: строка статуса)
  pantheon revisits         задача тика раз в сутки (SCHED-10, DOC-03): «пора пересмотреть …» в alerts.md
  pantheon stop <имя>|--all, pantheon resume <имя>|--all                                      (SCHED-12)
                            stop — метка «остановлено вами», claude stop и claude rm: сессия уходит из фоновых
                            сессий Claude Code (metis-0239), переписка остаётся
  pantheon pause <имя>|--all --reason limit|swap|manual ["почему"], pantheon pause --off [<имя>|--all]   (COST-04)
  pantheon restart --prepare [причина]|--status|--go [--force]|--done|--cancel, pantheon saved --by <имя> --state <путь>
                            технический перезапуск всей системы (SCHED-15, слово владельца 15.10); --done и --status
                            (все перезапущены, Зевс поднят заново) закрывают завершённый перезапуск (metis-0338); pantheon saved без
                            техперезапуска — метка «можно» для перезапуска после обновления плагинов (metis-0181)
  pantheon who              координаторы: состояние, short из реестра, давность (COMM-14)
  pantheon wake <имя> ["задание"]   поднять уснувшую сессию направления и сказать «посмотри входящие» (COMM-04);
                            задание из окна роли — только по слову владельца в окне Зевса за 15 мин, иначе код 2
                            (metis-0261 А); строка замера в capacity.jsonl — у подъёма и у отказа; недельный потолок
                            владельца достигнут — отказ, код 2 (--over-cap — только ваш терминал, metis-0444)
  pantheon infra-check      лёгкая проверка опор системы после обновления Claude Code (SEC-16)

Всё, что дежурный находит, — строка в ~/ai/pantheon/alerts.md один раз на состояние (alert_once) и, где нужно вас,
уведомление; в «ждёт вас» на доске переносит штаб. Модель дежурный зовёт только одним путём: «ждёт вас» (blocked) он передаёт живому
простаивающему Зевсу — push + `claude respawn`, раз на пункт и не чаще раза в 15 мин на сессию, за проход одним
сообщением, не при метке техперезапуска, паузе и лимитах, relay.json (metis-0277). Каждая проверка идёт отдельно: сбой одной
— тревога «проверка X упала», остальные работают; время прохода — ~/.local/state/pantheon/watch-last (строка статуса и
`pantheon status` показывают, что дежурный жив). Основания — исследование
~/ai/knowledge/inbox/research-2026-10-15-supervisor-watchdog.md и план ~/ai/pantheon/handoff/army-setup/step-1.4-plan.md.
"""
import contextlib
import errno
import glob
import hashlib
import json
import os
import random
import shutil
import stat
import re
import subprocess
import sys
import tarfile
import tempfile
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
STALE_NOW_HOURS = 6          # раздел «Сейчас» в STATUS.md окна, у которого были ходы, старше — тревога и напоминание (metis-0707)
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
STALE_NOW_TEXT = ("[Пантеон: «Сейчас» в STATUS.md устарел] Раздел «Сейчас» в STATUS.md направления не обновлялся "
                  "больше {hours} ч, а ты работаешь. Обнови его по фактам (слитые PR, закрытые и взятые задачи) и "
                  "продолжай. Это не ответ владельца и не согласие.")
NOW_HEAD = re.compile(r"^##[ \t]+Сейчас\b(.*)$", re.M)
NOW_STAMP = re.compile(r"\(\s*(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d)([\dxXхХ]|\d)\s*\)")


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


LIVE_SUBAGENT_MAX = 3 * 3600   # субагент без записи журнала дольше — мёртв (metis-0864): ожидание outside test — до 2 ч
LIVE_SUBAGENT_GRACE = 120      # с после старта процесса: журналы, закрытые прежним процессом при его снятии, — до этого


def live_subagents(a, t):
    """Живые субагенты окна по subagents/*.meta.json (metis-0864): без «finished», журнал писался после старта нынешнего
    процесса (+ LIVE_SUBAGENT_GRACE) и не раньше LIVE_SUBAGENT_MAX назад. Субагенты, оборванные перезапуском, остаются
    без «finished» навсегда, но их журнал старше старта процесса. Старт — P.session_started (Д2 ревью #332): startedAt
    claude agents без видимого процесса — createdAt задания, он старше прошлых перезапусков. → отсортированные имена."""
    tp = P.transcript_path(a)
    if not tp:
        return []
    started = P.session_started(a, t)
    out = []
    try:
        it = os.scandir(os.path.join(tp[:-len(".jsonl")], "subagents"))
    except OSError:
        return []
    with it:
        for e in it:
            if not (e.name.startswith("agent-") and e.name.endswith(".meta.json")):
                continue
            meta = P.read_json(e.path, {})
            if not isinstance(meta, dict) or meta.get("finished"):
                continue
            mt = 0.0
            for f in (e.path, e.path[:-len(".meta.json")] + ".jsonl"):
                with contextlib.suppress(OSError):
                    mt = max(mt, os.path.getmtime(f))
            if mt <= started + LIVE_SUBAGENT_GRACE or t - mt > LIVE_SUBAGENT_MAX:
                continue
            out.append(clean_why(meta.get("name") or e.name[len("agent-"):-len(".meta.json")])[:40])
    return sorted(out)


def live_work(a, t):
    """Почему окно сейчас нельзя поднимать заново (claude respawn обрывает его ход и субагентов), или None (metis-0864).
    05.11 окно metis-pantheon четыре раза ждало вашего «да» на команду, а возобновление ждущих (wake-waiting) раз в час
    перезапускало его: вопрос пропадал, субагенты гибли. Работа окна — ждёт разрешения или ответа на вопрос (tool_use
    последнего ответа без tool_result, pending_tool), живые субагенты и фоновые задачи (claude agents, inFlight из state.json, meta.json
    субагентов). Процесса нет (noProcess) — обрывать нечего."""
    if a.get("noProcess"):
        return None
    if "permission" in str(a.get("waitingFor") or "").lower():
        return "ждёт разрешения"
    tool = pending_tool(a)
    if tool:
        return f"ход не закончен: {tool}"
    if a.get("subagents") or a.get("backgroundTasks"):
        return "субагенты или фоновые задачи (claude agents)"
    fl = awake().session_state(a).get("inFlight")
    if isinstance(fl, dict) and (fl.get("tasks") or fl.get("queued")):
        return f"фоновые задачи: {fl.get('tasks') or 0}, в очереди {fl.get('queued') or 0}"
    names = live_subagents(a, t)
    if names:
        return "живые субагенты: " + ", ".join(names[:5]) + (f" и ещё {len(names) - 5}" if len(names) > 5 else "")
    return None


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
    # metis-0662 Д2: призрак с вопросом не держит имя (процесса нет), но и не поднимается без ответа владельца — ни
    # самозапуском, ни разовым запуском, ни после паузы, ни wake; pantheon start отказывает так же (sessions.py)
    alias = P.name_alias(name)
    asks = [a for a in agents if P.asks_owner(a) and alias.fullmatch(str(a.get("name") or ""))]
    if asks:
        return f"ждёт вашего ответа (процесс умер, вопрос остался): claude attach {asks[0].get('id')}"
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
              ("сессии", lambda: sessions(agents, doms, t)),
              ("STATUS.md", lambda: status_files(doms, t, agents, reg)),
              ("swap", lambda: swap(agents, t)),
              ("виновники памяти", lambda: P.culprits_mod().watch_check(agents, t)),
              ("worktree", lambda: worktrees(agents, reg, doms, t)),
              ("кэши песочниц", lambda: sandbox_sweep(t)),
              ("версия Claude Code", lambda: cc_version(t)),
              ("памятка Кто есть кто", lambda: P.who_is_who_alert()),
              ("паузы по нагрузке", lambda: pauses_clear(agents, reg, t)),
              ("очистка Зевса", lambda: zeus_clean(agents, t)),
              ("перезапуск после обновления плагинов", lambda: plugins_respawn(agents, doms, t)),
              ("ночь", lambda: P.night_mod().watch(agents, reg, doms, t)),
              ("заявки Зевса на запуск", lambda: P.take_start_requests(doms, t)),  # metis-0771: до разовых
              ("разовые запуски", lambda: oneshots(agents, reg, doms, t)),
              # после разовых (они чистят ONESHOT_STARTED), до самозапуска: поднятое здесь самозапуск не тронет
              ("окна по вашему ответу", lambda: word_launch(agents, reg, doms, t)),
              ("самозапуск", lambda: autostart(agents, reg, doms, t)),
              ("возобновление после недельного лимита", lambda: awake().limit_resume(agents, reg, doms, t)),
              ("возобновление ждущих сессий", lambda: awake().wake_waiting(agents, reg, doms, t)),
              ("поручения во входящих", lambda: awake().inbox_wake(agents, reg, doms, t)),
              ("запрет сна Mac", lambda: awake().keep_awake(agents, reg, doms, t)),
              ("журналы ваших слов", lambda: daily(t)),
              # последней: сессии, которые она уберёт, в этом проходе ещё в списке — подъём выше их уже не тронет
              ("уборка Гестии", lambda: hestia_reap(agents, t)),
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


RELAY_EVERY = 900  # metis-0277: «ждёт вас» уходит живому Зевсу не чаще раза в 15 мин на сессию и раз на пункт
WHY_LIMIT = 120
GENERIC_WHY = re.compile(r"(?:permission(?: prompt)?|input needed|waiting(?: for (?:input|permission))?|blocked)\W*",
                         re.I)
TARGET_KEYS = ("file_path", "path", "command", "url", "cwd", "name", "pattern", "query", "description")


def clean_why(v):
    """Текст сессии — данные (SEC-13): без переводов строк и лишних пробелов, не длиннее WHY_LIMIT."""
    return " ".join(str(v or "").split())[:WHY_LIMIT]


def pending_tool(a):
    """Чего ждёт сессия по её журналу: tool_use последнего ответа (message assistant) без tool_result → «Инструмент →
    цель» или None. Открытым считается только tool_use последнего ответа (ревью argus #332 Д1): tool_use-сирота
    раньше в хвосте (оборванный ход, после которого сессия жила дальше) — не работа, иначе окно числилось бы занятым
    навсегда. Один ответ — записи журнала с одним message.id (параллельные вызовы Claude Code пишет по записи на блок);
    без id запись — отдельный ответ. Ответом считается только запись type=assistant с model ≠ <synthetic>. Записи боковой ветки (isSidechain) не в счёт."""
    tp = P.transcript_path(a)
    if not tp:
        return None
    try:
        C = P.ctx_mod()
        used, results, order, last = {}, set(), [], None
        for n, d in enumerate(C.entries(C.tail_lines(tp, 1_000_000))):
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            items = msg.get("content")
            if msg.get("role") == "assistant" and (d.get("type") != "assistant" or msg.get("model") == "<synthetic>"):
                continue  # ревью argus #337: ответ — только type=assistant; <synthetic> (ошибка API, прерывание) не ответ
            if msg.get("role") == "assistant" and not d.get("isSidechain"):
                mid = msg.get("id") or ("entry", n)
                if mid != last:  # новый ответ: tool_use прежних ответов уже не «ход не закончен»
                    used, order, last = {}, [], mid
            elif msg.get("role") == "assistant":
                continue
            for x in items if isinstance(items, list) else []:
                if not isinstance(x, dict):
                    continue
                if x.get("type") == "tool_use" and x.get("id") and msg.get("role") == "assistant":
                    used[x["id"]] = x
                    order.append(x["id"])
                elif x.get("type") == "tool_result":
                    results.add(x.get("tool_use_id"))
        open_ids = [i for i in order if i not in results]
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if not open_ids:
        return None
    u = used[open_ids[-1]]
    inp = u.get("input") if isinstance(u.get("input"), dict) else {}
    target = next((str(inp[k]) for k in TARGET_KEYS if inp.get(k)), "")
    name = clean_why(u.get("name"))
    return clean_why(f"{name} → {target}" if target else name) or None


def blocked_why(a):
    """Что ждёт сессия, одной строкой: инструмент и цель из журнала, иначе waitingFor из claude agents, если это не
    общее «permission prompt»; иначе «причина неизвестна»."""
    tool = pending_tool(a)
    if tool:
        return tool
    wf = clean_why(a.get("waitingFor"))
    if wf and not GENERIC_WHY.fullmatch(wf):
        return wf
    return "причина неизвестна"


def relay_block(t):
    """Почему «ждёт вас» сейчас нельзя передавать Зевсу, или None. Передача — ход Зевса, то есть расход модели, поэтому
    те же запреты, что у автоматического подъёма (wake_block): техперезапуск (SCHED-15), пауза планировщика, пятичасовой
    лимит, недельный и недельный потолок владельца — оба в night.gate("respawn") ([limits.owner_cap], metis-0403)."""
    if os.environ.get("PANTHEON_DRYRUN") == "1" or dry():
        return "пробный запуск"
    if P.maintenance_active():
        return "идёт технический перезапуск"
    if os.path.exists(P.path("paused")):
        return "весь планировщик на паузе"
    pct, lim = P.limit_pct(), threshold("limit_max_pct", 70)
    if pct is not None and pct >= lim:
        return f"пятичасовой лимит {pct:.0f} % ≥ {lim:g} %"
    ok, why = P.night_mod().gate("respawn", t)
    if not ok:
        return f"недельный лимит: {why}"
    return None


def _relay_rec(v):
    """Запись relay.json: {"t": когда, "item": пункт, "sent": дошло ли}; старая числовая — отправленная без пункта."""
    if isinstance(v, dict) and isinstance(v.get("t"), (int, float)):
        return {"t": v["t"], "item": str(v.get("item") or ""), "sent": bool(v.get("sent", True))}
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return {"t": v, "item": "", "sent": True}
    return None


def relay_zeus(agents, items, t):
    """«Ждёт вас» сразу в живую сессию Зевса тем же путём, что передача задания (push + claude respawn). items — все
    blocked-сессии прохода [(имя, sid, что ждёт)]: за проход не больше одной передачи, одним сообщением (второй respawn
    оборвал бы ход, который первый только что начал). Один пункт — одна передача: тот же вопрос той же сессии повторно
    не будит, новая — когда пункт сменился или сессия вышла из blocked и вернулась (запись в relay.json снимает
    sessions()); и не чаще RELAY_EVERY на сессию. Зевса нет, остановлен или занят ходом, а также relay_block — ничего
    (остаются тревога и уведомление). → True, если передано."""
    items = [i for i in items if not i[0].startswith("zeus")]
    if not items or os.path.exists(P.path("stopped", "zeus")) or relay_block(t):
        return False
    st = P.read_json(P.path("relay.json"), {})
    st = st if isinstance(st, dict) else {}
    due = []
    for name, sid, why in items:
        rec = _relay_rec(st.get(sid))
        if rec is None or (t - rec["t"] >= RELAY_EVERY and (not rec["sent"] or rec["item"] != why)):
            due.append((name, sid, why))
    if not due:
        return False

    def pick(ags):
        zs = [z for z in ags if z.get("name") == "zeus" and z.get("id") and z.get("sessionId")
              and z.get("kind") in (None, "background")]
        z = max(zs, key=lambda x: x.get("startedAt") or 0) if zs else None
        return z if z and idle_holder(z) else None
    if not pick(agents):
        return False
    # та же блокировка, что у pantheon start zeus и resume_session: под ней свежий claude agents — Зевса могли поднять
    # или он взял ход после снимка прохода
    with P.lock("start-zeus", block=False) as got:
        if not got:
            return False
        fresh = P.agents_all()
        z = pick(fresh) if fresh else None
        if not z:
            return False
        if len(due) == 1:
            name, sid, why = due[0]
            text = f"{P.START_MARK} {name} ({sid}) ждёт вас: {why} — claude attach {sid}"
        else:
            text = f"{P.START_MARK} ждут вас {len(due)} сессии: " + "; ".join(
                f"{name} ({sid}): {why} — claude attach {sid}" for name, sid, why in due)
        pushed = P.push_text(z["sessionId"], text)
        if not pushed:
            return False
        r = subprocess.run([P.claude_bin(), "respawn", z["id"]], env=P.claude_env(), capture_output=True, text=True, timeout=180)
        P.start_log(f"relay\tzeus\t{z['id']}\t{','.join(d[1] for d in due)}\t{r.returncode}")
        ok = r.returncode == 0
        if not ok:
            with contextlib.suppress(OSError):
                os.remove(pushed)
        st = {k: v for k, v in st.items() if (_relay_rec(v) or {"t": 0})["t"] > t - 86400}
        for _, sid, why in due:  # неудача тоже в запись: повтор не чаще RELAY_EVERY, а не каждый проход
            st[sid] = {"t": t, "item": why, "sent": ok}
        P.write_json(P.path("relay.json"), st)
        return ok


def sessions(agents, doms, t=None):
    """Ждёт вас (blocked) или упала (failed) — тревога один раз на состояние сессии; уведомление — сбой «скоро»
    каждый проход, пока состояние держится (политика решает: macOS, когда вас нет, не чаще раза в час на событие).
    blocked дополнительно сразу уходит живому Зевсу (metis-0277): все ждущие прохода одним сообщением, с инструментом и
    целью запроса."""
    t = P.now() if t is None else t
    word = {"blocked": "ждёт вас", "failed": "упала"}
    waiting = []  # blocked этого прохода: [(имя, sid, что ждёт)] — Зевсу одним сообщением
    for a in agents:
        name, sid, state = a.get("name") or "", a.get("id") or a.get("sessionId") or "", a.get("state")
        if not sid or not is_pantheon(name, doms):
            continue
        key = f"watch-state-{sid}"
        # metis-0250: снятая Claude Code без вопроса — не «ждёт вас» и без тревоги, и призраком тоже (metis-0662 Д1):
        # ждать ей нечего, а поднимают её самозапуск, wake и pantheon start (заменяет новой)
        if state not in word or a.get("noProcess"):
            P.clear_once(key)
            P.clear_fault(*(f"watch-{s}-{sid}" for s in word))  # состояние снялось — следующее снова macOS
            continue
        why = blocked_why(a) if state == "blocked" else clean_why(a.get("waitingFor"))
        ghost_asks = P.asks_owner(a)  # вопрос — needs или waitingFor записи, а не detail задания (argus-249a Б1)
        if ghost_asks:  # призрак с вопросом владельцу по-прежнему «ждёт вас» (metis-0250): состояние для уведомления
            state = "blocked"  # считается до clear_fault, иначе каждый проход сбрасывал бы «watch-blocked-…» (ревью argus Б2)
        P.clear_fault(*(f"watch-{s}-{sid}" for s in word if s != state))
        if a.get("ghost"):  # metis-0651: процесс умер, запись осталась — одна тревога на сессию, пока призрак виден
            P.alert_once(key, "ghost", f"{name} ({sid}): процесс умер, в claude agents осталась запись "
                         f"«{a.get('listedState')}»" + (f", ждала: {why}" if why else "")
                         # metis-0662 С1: с вопросом wake и start не поднимают — совет тот же, что у отказа start
                         + (f" — ждёт вашего ответа: claude attach {sid}" if ghost_asks
                            else f" — имя свободно, поднять: pantheon wake {name}"), "watch")
            if not ghost_asks:
                continue
        else:
            P.alert_once(key, state, f"{name} ({sid}) {word[state]}" + (f": {why}" if why else "")
                         + f" — claude attach {sid}", "watch")
        # ключ события — сессия и состояние: «упала» после «ждёт вас» — своё уведомление, вид — один на сессию
        P.notify_soon(f"watch-{state}-{sid}", f"{name} {word[state]}" + (f": {why[:80]}" if why else ""),
                      group=f"session-{name}", once=True)
        if state == "blocked":
            waiting.append((name, sid, why))
    relay_zeus(agents, waiting, t)
    # вышла из blocked — запись снимаем: вернётся в blocked, будет новый пункт (передача раз на пункт)
    st = P.read_json(P.path("relay.json"), {})
    if isinstance(st, dict) and st:
        keep = {k: v for k, v in st.items() if k in {w[1] for w in waiting}}
        if keep != st:
            P.write_json(P.path("relay.json"), keep)


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
        reason = P.rm_session(sid, tries=1, name=name, why="auto-rm")
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


def hestia_reap(agents, t):
    """Уборка Гестии (metis-0671): служебная сессия hestia после задачи висит в claude agents (призрак без процесса,
    закончившая ход). Убираем claude stop + rm (P.stop_and_rm, как pantheon stop) БЕЗ метки stopped/hestia: с ней
    следующий wake hestia отказал бы «остановлена вами». Убираем, если (а) процесса нет вовсе (ghost, либо
    done/stopped/failed без pid) или (б) задача окна (PANTHEON_TASK из settings/run/hestia.json, куда её кладёт wake
    hestia) закрыта (done|dropped) либо неизвестна, а сессия не working. Working с открытой задачей, blocked с живым процессом и
    открытой задачей, запись моложе минуты и подъём под start-hestia — не трогаем. Переписка остаётся. Пауза
    планировщика и техперезапуск — как у auto_rm."""
    if dry() or P.maintenance_active() or os.path.exists(P.path("paused")):
        return
    cands = [a for a in agents if a.get("name") == "hestia" and a.get("kind") in (None, "background")
             and re.fullmatch(r"[0-9a-zA-Z-]{4,64}", str(a.get("id") or "")) and not P.just_listed(a)]
    if not cands:
        return
    tid = ((P.read_json(P.path("settings", "run", "hestia.json"), {}).get("env") or {}).get("PANTHEON_TASK") or "")
    head = None
    if tid and P.tasks_mod().ID_RE.fullmatch(str(tid)):
        head = (P.tasks_mod().load_tasks(P.PANTHEON).get(tid) or (None, None, None))[1]
    is_open = bool(head) and head.get("status") not in ("done", "dropped")  # waiting/inbox — открыта (metis-0677)
    with P.lock("start-hestia", block=False) as got:
        if not got:
            return  # wake hestia поднимает сессию прямо сейчас
        for a in cands:
            sid = str(a["id"])
            dead = (a.get("ghost")
                    or (a.get("state") in ("done", "stopped", "failed") and not a.get("pid")))
            if not dead and (a.get("state") == "working" or is_open):
                continue
            has_process = a.get("state") in ("working", "blocked") or a.get("ghost") or a.get("pid")
            reason = P.stop_and_rm("hestia", sid, "hestia-reap") if has_process \
                else P.rm_session(sid, tries=1, name="hestia", why="hestia-reap")
            why = "нет процесса" if dead else f"задача {tid or '—'} не открыта"
            P.start_log(f"hestia-reap\thestia\t{sid}\t{a.get('state')}\t{why}" + (f"\t{reason}" if reason else ""))
            if reason:
                P.alert_once(f"hestia-reap-{sid}", reason[:80], f"hestia: сессия {sid} осталась среди фоновых сессий "
                             f"Claude Code (уборка, {P.refused_by(reason)}): {reason}", "watch")
            else:
                P.alert(f"уборка: Гестия {sid} убрана из фоновых сессий Claude Code ({why}); переписка осталась — "
                        "claude --resume", "watch")


def now_section_time(text, mtime, t):
    """Когда обновлён раздел «Сейчас» STATUS.md (metis-0707): время из заголовка «## Сейчас (ДД.ММ ЧЧ:ММ)» (минуты
    «Мx» — последняя из возможных, чтобы не тревожить зря); заголовок есть, а даты в нём нет — mtime файла; раздела
    нет — None (нечего считать устаревшим). Год — текущий, дата из будущего — прошлого года."""
    m = NOW_HEAD.search(text)
    if not m:
        return None
    d = NOW_STAMP.search(m.group(1))
    if not d:
        return mtime
    day, mon, hh, m10, m1 = d.groups()
    mm = int(m10) * 10 + (int(m1) if m1.isdigit() else 9)
    now = datetime.fromtimestamp(t)
    try:
        stamp = datetime(now.year, int(mon), int(day), int(hh), mm)
        if stamp.timestamp() > t + 86400:
            stamp = stamp.replace(year=now.year - 1)
    except ValueError:
        return mtime  # дата не календарная — как заголовок без даты
    return stamp.timestamp()


def window_turned_since(name, agents, registry, since):
    """У окна name были ходы после since: транскрипт (иначе updatedAt из state.json) любого держателя имени новее."""
    for a in holders(name, agents, registry):
        if not a.get("sessionId"):
            continue
        last = None
        tp = P.transcript_path(a)
        if tp:
            with contextlib.suppress(OSError):
                last = os.path.getmtime(tp)
        if last is None:
            last = awake().parse_time(awake().session_state(a).get("updatedAt"))
        if last is not None and last >= since:
            return True
    return False


def stale_now(name, text, mtime, agents, registry, t):
    """Раздел «Сейчас» окна, которое работает, старше STALE_NOW_HOURS (metis-0707): тревога один раз на заголовок и
    сутки и напоминание роли (STALE_NOW_TEXT) — простаивающей живой сессии, тоже раз на заголовок и сутки; работающей
    или ждущей вас напоминание не шлём: тревога есть. Окно без ходов за срок и обновлённый «Сейчас» — отметки снимаем."""
    key, push, fail = f"watch-now-{name}", f"watch-now-push-{name}", f"watch-now-fail-{name}"
    stamp = now_section_time(text, mtime, t)
    limit = STALE_NOW_HOURS * 3600
    if stamp is None or t - stamp <= limit or not window_turned_since(name, agents, registry, t - limit):
        P.clear_once(key)
        P.clear_once(push)
        P.clear_once(fail)
        return
    head = NOW_HEAD.search(text).group(0).strip()
    value = f"{today(t)}-{head}"
    hours = (t - stamp) / 3600
    P.alert_once(key, value, f"STATUS.md {name}: раздел «Сейчас» не обновлялся {hours:.0f} ч ({head}), а окно работает "
                 "— обновить по фактам", "watch")
    hold = holders(name, agents, registry)
    poke = nudge_target(hold)
    try:
        if poke is None or open(P.once_path(push)).read() == value:
            return
    except OSError:
        if poke is None:
            return
    if recheck(name, True, nudge=True)():
        return  # будить сейчас нельзя (пауза, лимит, не главный Mac) — напомним в следующем проходе
    rc = P.resume_session(name, poke, STALE_NOW_TEXT.format(hours=STALE_NOW_HOURS), "stale-now",
                          recheck=recheck(name, True, nudge=True))[0]
    if rc in (P.NO_WINDOW, P.SKIPPED):
        return
    # отметка и при неудаче: иначе каждый проход заново будит роль и шлёт новую тревогу (не чаще раза на заголовок и сутки)
    os.makedirs(P.path("once"), exist_ok=True)
    open(P.once_path(push), "w").write(value)
    if rc != 0:
        P.alert_once(fail, value, f"STATUS.md {name}: напоминание про «Сейчас» не доставлено (код {rc})", "watch")


def status_files(doms, t, agents=(), registry=()):
    """STATUS.md направления: с задачей «В работе» давно не обновлялся — состояние могло потеряться; длиннее 200 строк
    — координатору перенести закрытое в archive/ (STATE-14); «Сейчас» старше STALE_NOW_HOURS у работающего окна —
    тревога и напоминание роли (metis-0707)."""
    doing = set()
    with contextlib.suppress(Exception):
        doing = {h.get("direction") for _, h, _ in P.tasks_mod().load_tasks(P.PANTHEON).values()
                 if h.get("status") == "doing"}
    for name in doms:
        p = os.path.join(P.PANTHEON, "directions", name, "STATUS.md")
        try:
            st = os.stat(p)
            text = open(p, encoding="utf-8", errors="replace").read()
            n = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        except OSError:
            continue
        try:
            stale_now(name, text, st.st_mtime, agents, registry, t)
        except Exception as ex:  # сбой одного направления (таймаут resume_session и т. п.) не обрывает остальные
            P.alert_once(f"watch-now-err-{name}", today(t), f"STATUS.md {name}: проверка «Сейчас» упала: "
                         f"{type(ex).__name__}: {str(ex)[:120]}", "watch")
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
LINK_SKIP = ("node_modules", ".next", ".venv", "venv", ".turbo", ".cache")   # зависимости и сборка: большие, считаются отдельно (metis-0616)
DEPS_LIMIT = 300000                     # записей внутри LINK_SKIP; больше — «не знаю» (None), копия не удаляется


def outward_links(wt):
    """Символические ссылки копии, чья цель (realpath) лежит вне неё. Обход без перехода по ссылкам, папку .git
    копии пропускаем. Записи внутри LINK_SKIP (node_modules, .next, .venv и т. п.; у слитой копии BA ~45 тыс. файлов) считаются отдельно, под
    DEPS_LIMIT, остальные — под WALK_LIMIT. Превышение любого лимита — копия считается небезопасной (None, «не знаю»)
    и не удаляется. Возвращает (число, первая как (путь относительно копии, цель)) или None."""
    root = os.path.realpath(wt)
    n, first, seen, deps = 0, None, 0, 0
    for d, dirs, files in os.walk(root, followlinks=False):
        if d == root and ".git" in dirs:
            dirs.remove(".git")
        inside = any(part in LINK_SKIP for part in os.path.relpath(d, root).split(os.sep))
        for name in dirs + files:
            if inside:
                deps += 1
                if deps > DEPS_LIMIT:
                    return None
            else:
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


# --- уборка копий .claude/worktrees (QA-05, metis-0616, metis-0835) --------------------------------------------------

WORKTREE_EMPTY_MIN = 30     # мин: пустая чистая копия (HEAD в основной ветке, своих коммитов нет) — без суток (metis-0835, б)
WT_REQ_DAYS = 7             # заявку `pantheon wt done`, которую так и не исполнить (копия занята), снимаем через столько дней
UNTRACKED_MAX_MB = 200      # неотслеживаемое грязной копии больше — архив не собираем, копию не убираем
WT_REQ_DIR = "wt-req"       # заявки `pantheon wt done`: STATE/wt-req (ваши сессии), <кэш окна>/wt-req (окно роли)
AGENT_LOCK = re.compile(r"claude agent (agent-[0-9a-f]{6,40}) \(pid \d+")   # lock, который Claude Code вешает на копию субагента
AGENT_DIR = re.compile(r"agent-[0-9a-f]{6,40}")
REQ_FILE = re.compile(r"[0-9a-f]{16}\.json")
REQ_MAX = 4096


def wt_archive(*parts):
    """Архив уборки копий: STATE/wt-archive/{removed-<день>.txt, patches/, untracked/}."""
    return P.path("wt-archive", *parts)


def _has_inside(wt, paths):
    """Есть ли среди путей сама копия или папка внутри неё."""
    return any(c == wt or c.startswith(wt + os.sep) for c in paths)


def proc_cwds():
    """Текущие папки всех процессов (lsof -d cwd), настоящими путями; None — lsof не ответил: тогда копий не убираем."""
    try:
        r = subprocess.run(["lsof", "-a", "-d", "cwd", "-nP", "-Fn"], capture_output=True, text=True, timeout=60,
                           errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    if not r.stdout:
        return None
    return {os.path.realpath(ln[1:]) for ln in r.stdout.splitlines() if ln.startswith("n/")}


def subagent_live(agent, wt, t):
    """Субагент копии ещё работает (metis-0835): его ~/.claude/projects/*/*/subagents/[*/[*/]]<agent>.meta.json (как
    review_find_transcripts) без finished, worktreePath — эта копия, а журнал или meta писались не раньше
    LIVE_SUBAGENT_MAX назад. Субагент, оборванный перезапуском родителя, остаётся без finished навсегда, но его журнал
    стареет. → True | False | None — meta не найден (решает вызывающий: под замком субагента это не «мёртв»)."""
    base = os.path.join(glob.escape(P.HOME), ".claude", "projects", "*", "*", "subagents")
    metas = set()
    for sub in ((), ("*",), ("*", "*")):
        metas.update(glob.glob(os.path.join(base, *sub, glob.escape(agent) + ".meta.json")))
    if not metas:
        return None
    for m in sorted(metas):
        meta = P.read_json(m, {})
        if not isinstance(meta, dict) or meta.get("finished"):
            continue
        wp = meta.get("worktreePath")
        if isinstance(wp, str) and wp and os.path.realpath(wp) != wt:
            continue
        mt = 0.0
        for f in (m, m[:-len(".meta.json")] + ".jsonl"):
            with contextlib.suppress(OSError):
                mt = max(mt, os.path.getmtime(f))
        if t - mt <= LIVE_SUBAGENT_MAX:
            return True
    return False


QUIET_LIMIT = 50000   # записей копии (без LINK_SKIP) для _quiet_since; больше — «не знаю», копия считается занятой


def _quiet_since(wt, since):
    """Ни одна запись копии (папки и файлы, без LINK_SKIP, без перехода по ссылкам) не менялась после since. Обход
    длиннее QUIET_LIMIT или ошибка чтения — False: при сомнении копию не трогаем."""
    stack, n = [wt], 0
    while stack:
        d = stack.pop()
        try:
            if os.lstat(d).st_mtime > since:
                return False
            with os.scandir(d) as it:
                for e in it:
                    n += 1
                    if n > QUIET_LIMIT:
                        return False
                    st = e.stat(follow_symlinks=False)
                    if st.st_mtime > since:
                        return False
                    if e.is_dir(follow_symlinks=False) and e.name not in LINK_SKIP:
                        stack.append(e.path)
        except OSError:
            return False
    return True


def merged_branches(root):
    """Ветки слитых PR репозитория root по кэшу `pantheon autoclose fetch` (STATE/autoclose-prs.json, ключ merged;
    репозиторий — по origin основной копии). В сеть не ходит; кэша нет — пусто."""
    url = _git("-C", root, "config", "--get", "remote.origin.url").stdout.strip()
    m = re.search(r"github\.com[:/]+([^/\s]+/[^/\s]+?)(?:\.git)?/?$", url)
    cache = P.read_json(P.path("autoclose-prs.json"), {})
    merged = cache.get("merged") if isinstance(cache, dict) else None
    if not m or not isinstance(merged, dict):
        return set()
    out = set()
    for repo, rows in merged.items():
        if str(repo).lower() == m.group(1).lower() and isinstance(rows, list):
            out |= {r["headRefName"] for r in rows if isinstance(r, dict) and isinstance(r.get("headRefName"), str)
                    and r["headRefName"]}
    return out


class WtCtx:
    """Общее на проход уборки: сессии (live — с процессом, known — все, о ком знает Claude Code), папки процессов
    (lsof — один раз и только когда есть что решать), основная ветка и ветки слитых PR каждого репозитория."""

    def __init__(self, agents, registry, t):
        both = [a for a in list(agents) + list(registry) if isinstance(a, dict) and isinstance(a.get("cwd"), str)
                and a.get("cwd")]
        self.live = [os.path.realpath(a["cwd"]) for a in both if a.get("pid")]
        self.known = [os.path.realpath(a["cwd"]) for a in both]
        self.t = t
        self._procs, self._base, self._prs = False, {}, {}

    def procs(self):
        if self._procs is False:
            self._procs = proc_cwds()
        return self._procs

    def base(self, root):
        if root not in self._base:
            self._base[root] = _base_ref(root)
        return self._base[root]

    def prs(self, root):
        if root not in self._prs:
            self._prs[root] = merged_branches(root)
        return self._prs[root]


def merged_why(root, head, branch, base, ctx):
    """Чистая копия со своими коммитами слита (metis-0835): PR её ветки слит (кэш gh), HEAD есть на origin или все её
    коммиты уже в основной ветке (`git cherry` без «+»). → причина словами или None."""
    if branch and branch in ctx.prs(root):
        return "PR слит"
    r = _git("-C", root, "for-each-ref", "--contains", head, "--count=1", "--format=%(refname:short)", "refs/remotes/origin")
    if r.returncode == 0 and r.stdout.strip():
        return f"есть на {r.stdout.strip()}"
    if base:
        c = _git("-C", root, "cherry", base, head)
        if c.returncode == 0 and c.stdout.strip() and not any(ln.startswith("+") for ln in c.stdout.splitlines()):
            return "коммиты уже в основной ветке"
    return None


def _git_bytes(*args, env=None, timeout=120):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", **(env or {}))
    return subprocess.run(["git", *GIT_SAFE, *args], capture_output=True, timeout=timeout, env=env)


def _untracked(wt, env):
    """Неотслеживаемые файлы копии без зависимостей и кэшей (LINK_SKIP) → [(путь, имя в архиве)] или None (git не
    ответил). Вложенный репозиторий git выдаёт папкой «x/» — её файлы берём обходом без перехода по ссылкам. Ссылки,
    устройства и каналы отсеивает _tar_regular при записи архива (O_NOFOLLOW и fstat — без гонки проверки и чтения)."""
    r = _git_bytes("-C", wt, "ls-files", "-o", "--exclude-standard", "-z", env=env)
    if r.returncode != 0:
        return None
    skip = lambda rel: any(part in LINK_SKIP for part in rel.split("/"))  # noqa: E731

    out = []
    for raw in r.stdout.split(b"\0"):
        rel = os.fsdecode(raw)
        if not rel or skip(rel):
            continue
        p = os.path.join(wt, rel)
        if rel.endswith("/") and os.path.isdir(p) and not os.path.islink(p.rstrip("/")):
            for d, dirs, files in os.walk(p, followlinks=False):
                dirs[:] = [x for x in dirs if x not in LINK_SKIP]
                for f in files:
                    q = os.path.join(d, f)
                    out.append((q, os.path.relpath(q, wt)))
        else:
            out.append((p.rstrip("/"), rel.rstrip("/")))
    return out


def _free_stem(name):
    """Имя архива копии: <имя>, <имя>-2, …: прежний патч и архив той же копии не затираем."""
    for i in range(1, 100):
        stem = name if i == 1 else f"{name}-{i}"
        if not (os.path.lexists(wt_archive("patches", stem + ".patch"))
                or os.path.lexists(wt_archive("untracked", stem + ".tar.gz"))):
            return stem
    return f"{name}-{int(time.time())}"


class _TooBig(Exception):
    """Прочитанное неотслеживаемое превысило UNTRACKED_MAX_MB."""


def _tar_regular(tf, src, arc, budget):
    """Обычный файл src → член arc архива tf. Открывается без перехода по ссылке (O_NOFOLLOW), fstat — обычный файл,
    иначе пропуск; размер в архиве — сколько байт прочитано, а не lstat: файл, выросший после подсчёта, предел не
    обойдёт. → прочитано байт; больше budget — _TooBig."""
    try:
        fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENOENT):
            return 0  # подменён ссылкой или пропал после списка — не наш файл
        raise
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            return 0
        buf, n = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024), 0
        with buf:
            while chunk := fh.read(1024 * 1024):
                n += len(chunk)
                if n > budget:
                    raise _TooBig()
                buf.write(chunk)
            buf.seek(0)
            ti = tarfile.TarInfo(arc)
            ti.size, ti.mtime, ti.mode = n, int(st.st_mtime), stat.S_IMODE(st.st_mode)
            tf.addfile(ti, buf)
    return n


def wt_save(wt, env):
    """Грязная копия до удаления (metis-0835): `git diff HEAD --binary` → wt-archive/patches/<имя>.patch и
    неотслеживаемое (без LINK_SKIP) → wt-archive/untracked/<имя>.tar.gz. → (True, [пути]) или (False, причина):
    архив не собрался, неотслеживаемого больше UNTRACKED_MAX_MB или сохранить нечего (status грязный, а патч и список
    пусты) — тогда копию не убираем, недописанные файлы архива снимаются."""
    d = _git_bytes("-C", wt, "diff", "HEAD", "--binary", "--no-ext-diff", "--no-textconv", env=env)
    if d.returncode != 0:
        return False, "git diff HEAD не прошёл"
    files = _untracked(wt, env)
    if files is None:
        return False, "список неотслеживаемого не прочитан"
    total = 0
    for p, _ in files:
        with contextlib.suppress(OSError):
            total += os.lstat(p).st_size
    if total > UNTRACKED_MAX_MB * 1024 * 1024:
        return False, f"неотслеживаемого {total / 1048576:.0f} МБ — больше предела {UNTRACKED_MAX_MB} МБ"
    stem = _free_stem(os.path.basename(wt))
    made = []
    try:
        if d.stdout:
            p = wt_archive("patches", stem + ".patch")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            made.append(p)
            with os.fdopen(fd, "wb") as fh:
                fh.write(d.stdout)
        if files:
            p = wt_archive("untracked", stem + ".tar.gz")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            budget = UNTRACKED_MAX_MB * 1024 * 1024
            with tarfile.open(p, "x:gz") as tf:  # «x» — O_EXCL: чужой файл на этом месте не затрём и не снимем
                made.append(p)
                for src, arc in files:
                    budget -= _tar_regular(tf, src, arc, budget)
                members = len(tf.getmembers())
            if not members:  # в списке были только ссылки и каналы — архив пуст
                made.remove(p)
                os.remove(p)
    except _TooBig:
        _unmake(made)
        return False, f"неотслеживаемого больше предела {UNTRACKED_MAX_MB} МБ (по прочитанному)"
    except (OSError, tarfile.TarError) as e:
        _unmake(made)
        return False, f"архив не собрался ({getattr(e, 'strerror', None) or e})"
    if not made:
        return False, "грязная, а сохранить нечего: патч пуст, неотслеживаемое — только ссылки, каналы, зависимости и кэши"
    return True, made


def _unmake(made):
    for p in made:
        with contextlib.suppress(OSError):
            os.remove(p)


def _archive_branch(root, name, head):
    """Ветка archive/wt-<имя> на HEAD копии без ветки (detached): коммиты не теряются. Такая ветка уже есть на другом
    коммите — archive/wt-<имя>-2 и т. д. → имя ветки или None."""
    for i in range(1, 20):
        b = f"archive/wt-{name}" + (f"-{i}" if i > 1 else "")
        cur = _git("-C", root, "rev-parse", "--verify", "--quiet", f"refs/heads/{b}^{{commit}}")
        if cur.returncode == 0:
            if cur.stdout.strip() == head:
                return b
            continue
        return b if _git("-C", root, "branch", b, head).returncode == 0 else None
    return None


def wt_journal(t, root, wt, branch, head, kind, saved):
    """Строка убранной копии в STATE/wt-archive/removed-<день>.txt: время, репозиторий, копия, ветка, HEAD, почему,
    архивы. → путь журнала или None (не записался — копия уже убрана, это скажет итог)."""
    p = wt_archive(f"removed-{today(t)}.txt")
    line = "\t".join([datetime.fromtimestamp(t).strftime("%H:%M"), root.replace(P.HOME, "~"), os.path.basename(wt),
                      branch or "detached", head, kind, " ".join(x.replace(P.HOME, "~") for x in saved)])
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        return None
    return p


def wt_one(root, wt, block, ctx, requested=False, dry=False):
    """Одна копия <root>/.claude/worktrees/<имя> (metis-0835). block — её запись `git worktree list --porcelain`.
    → (итог, текст):
      live    — в копии живая сессия (cwd), процесс (lsof) или работающий субагент: не трогаем ни при каком условии;
      wait    — рано по возрасту (или lsof не ответил);
      keep    — пора, но убрать нельзя: текст — причина для тревоги;
      plan    — убрал бы (dry: ничего не меняет);
      removed — убрана, текст — для сводки.
    Сроки по mtime папки копии: пустая чистая (HEAD в основной ветке) — WORKTREE_EMPTY_MIN (копия, в которой Claude
    Code знает сессию без процесса, — WORKTREE_CLEAN_HOURS); чистая слитая (merged_why) — WORKTREE_CLEAN_HOURS;
    чистая неслитая и грязная — WORKTREE_DAYS. requested (`pantheon wt done`) — без сроков. Замок «claude agent …»
    без живого субагента не держит; lock с другой причиной — держит. Ветку не удаляем (кроме `branch -d` пустой: git
    сам откажет, если она не слита); detached со своими коммитами — сначала ветка archive/wt-<имя>; грязную — сначала
    в патч и архив (wt_save)."""
    t = ctx.t
    if _has_inside(wt, ctx.live):
        return "live", "живая сессия в копии"
    procs = ctx.procs()
    if procs is None:
        return "wait", "lsof не ответил — папки процессов неизвестны"
    if _has_inside(wt, procs):
        return "live", "процесс с текущей папкой в копии"
    lm = re.search(r"^locked(?: (.*))?$", block, re.M)
    reason = (lm.group(1) or "").strip() if lm else ""
    am = AGENT_LOCK.match(reason) if lm else None
    name = os.path.basename(wt)
    agent = am.group(1) if am else (name if AGENT_DIR.fullmatch(name) else None)
    alive = subagent_live(agent, wt, t) if agent else False
    if alive:
        return "live", f"субагент {agent} ещё работает"
    if alive is None and am and not _quiet_since(wt, t - LIVE_SUBAGENT_MAX):
        # lock называет субагента, а его meta не найден: жив ли он — неизвестно; ждём, пока копия затихнет
        return "live", f"lock субагента {agent}: meta не найден, в копии правки моложе {LIVE_SUBAGENT_MAX / 3600:g} ч"
    try:
        age = (t - os.stat(wt).st_mtime) / 3600
    except OSError:
        return "wait", "копия не читается"
    late = "keep" if requested or age > WORKTREE_DAYS * 24 else "wait"
    if lm and not am:
        return late, f"lock не субагента ({reason or 'без причины'})"
    hm = re.search(r"^HEAD ([0-9a-f]{40})$", block, re.M)
    bm = re.search(r"^branch refs/heads/(.+)$", block, re.M)
    if not hm:
        return late, "нет HEAD"
    head, branch = hm.group(1), (bm.group(1) if bm else None)
    env = wt_env(root, wt)
    bad = unsafe_config(wt, env)
    if bad:
        return late, f"конфигурация git: {bad}"
    st = _git("-C", wt, "status", "--porcelain", "--ignore-submodules=all", env=env)
    if st.returncode != 0:
        return late, "git status не прошёл"
    clean = st.stdout.strip() == ""
    base = ctx.base(root)
    empty = bool(base) and _git("-C", root, "merge-base", "--is-ancestor", head, base).returncode == 0
    on_origin = False  # HEAD есть на ветке origin: коммиты не потеряются и без archive/wt-<имя>
    if clean and empty:
        kind = "пустая"
        need = WORKTREE_CLEAN_HOURS if _has_inside(wt, ctx.known) else WORKTREE_EMPTY_MIN / 60
    elif clean:
        why = merged_why(root, head, branch, base, ctx)
        on_origin = bool(why) and why.startswith("есть на ")
        kind, need = (f"слитая: {why}", WORKTREE_CLEAN_HOURS) if why else ("неслитая", WORKTREE_DAYS * 24)
    else:
        kind, need = "грязная", WORKTREE_DAYS * 24
    if not requested and age <= need:
        return "wait", f"{kind}, {age:.1f} ч из {need:g}"
    out = outward_links(wt)
    if out is None or out[0]:
        what = ("обход длиннее лимита (%d / %d записей)" % (WALK_LIMIT, DEPS_LIMIT) if out is None else
                "ссылки наружу (%d, первая: %s → %s)" % (out[0], out[1][0], out[1][1].replace(P.HOME, "~")))
        return "keep", f"в ней {what}"
    archive = branch is None and not empty and not on_origin
    if dry:
        return "plan", (f"убрал бы: {kind}, {age / 24:.1f} дн." + (", lock субагента снять" if am else "")
                        + (f", сначала ветка archive/wt-{name}" if archive else "")
                        + (", сначала патч и архив неотслеживаемого" if not clean else ""))
    if archive:
        made = _archive_branch(root, name, head)
        if not made:
            return "keep", f"ветка archive/wt-{name} не создана"
        branch = made
    saved = []
    if not clean:
        ok, res = wt_save(wt, env)
        if not ok:
            return "keep", res
        saved = res
    if am and _git("-C", root, "worktree", "unlock", wt).returncode != 0:
        return "keep", "lock субагента не снят"
    # чистоту и состав смотрел свой status по записанному каталогу; без --force git проверил бы её ещё раз своим
    # status — уже по конфигурации, которую мы не смотрели
    rm = _git("-C", root, "worktree", "remove", "--force", wt, timeout=300)
    if rm.returncode != 0:
        return "keep", f"git worktree remove: {(rm.stderr or rm.stdout).strip()[:160]}"
    if empty and branch:
        _git("-C", root, "branch", "-d", branch)
    j = wt_journal(t, root, wt, branch, head, kind, saved)
    return "removed", f"{name} ({kind}" + (f", ветка {branch}" if branch else "") + \
        (", архив: " + ", ".join(os.path.basename(x) for x in saved) if saved else "") + \
        ("" if j else ", журнал не записан") + ")"


def _req_dirs(doms):
    """[(папка заявок, папки реестра, которые ей можно)]: STATE/wt-req — ваши сессии (все папки реестра);
    <кэш окна>/wt-req — окно роли, только папки направления с его именем (как у `pantheon outside`)."""
    real = lambda fs: [os.path.realpath(os.path.expanduser(f)) for f in (fs if isinstance(fs, list) else [])  # noqa: E731
                       if isinstance(f, str)]
    out = [(P.path(WT_REQ_DIR), [r for fs in doms.values() for r in real(fs)])]
    with contextlib.suppress(OSError):
        for name in sorted(os.listdir(sandbox_root())):
            d = os.path.join(sandbox_root(), name, WT_REQ_DIR)
            with contextlib.suppress(OSError):
                if stat.S_ISDIR(os.lstat(d).st_mode):
                    out.append((d, real(doms.get(name))))
    return out


def _req_open(d):
    """Папка заявок без перехода по ссылке → fd папки или None: подложенная ссылка на чужую папку не читается и в ней
    ничего не удаляется (все unlink — относительно этого fd). _open_dir — общий с уборкой кэшей окон."""
    try:
        fd = _open_dir(d)
    except OSError:
        return None
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    return fd


def wt_requests(doms, t):
    """Заявки `pantheon wt done` → {путь копии: [(папка заявок, имя файла)]}. Битые, подложенные (ссылка, не обычный
    файл), старше WT_REQ_DAYS и на копию вне папок, которые этой папке заявок можно, снимаются сразу. Папка и файлы —
    через fd папки (O_NOFOLLOW): подменённая ссылкой папка пропускается. Имена с точки — недописанные заявки окна, их
    не трогаем."""
    out = {}
    for d, roots in _req_dirs(doms):
        dfd = _req_open(d)
        if dfd is None:
            continue
        try:
            for n in os.listdir(dfd):
                if n.startswith("."):
                    continue
                data = None
                if REQ_FILE.fullmatch(n):
                    with contextlib.suppress(OSError, ValueError):
                        fd = os.open(n, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
                        with os.fdopen(fd, "rb") as fh:
                            if stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                                data = json.loads(fh.read(REQ_MAX + 1)[:REQ_MAX] or b"null")
                wt = data.get("path") if isinstance(data, dict) else None
                when = data.get("time") if isinstance(data, dict) else None
                ok = (isinstance(wt, str) and isinstance(when, (int, float)) and t - when <= WT_REQ_DAYS * 86400
                      and any(os.path.dirname(os.path.realpath(wt)) == os.path.join(r, ".claude", "worktrees")
                              for r in roots))
                if ok:
                    out.setdefault(os.path.realpath(wt), []).append((d, n))
                else:
                    with contextlib.suppress(OSError):
                        os.unlink(n, dir_fd=dfd)
        except OSError:
            pass
        finally:
            os.close(dfd)
    return out


def _drop(items):
    """Снять заявки [(папка, имя)] — через fd папки без перехода по ссылке."""
    for d, n in items or ():
        dfd = _req_open(d)
        if dfd is None:
            continue
        try:
            with contextlib.suppress(OSError):
                os.unlink(n, dir_fd=dfd)
        finally:
            os.close(dfd)


def _copies(root):
    """Записи `git worktree list --porcelain` репозитория root, кроме основной копии: [(настоящий путь, запись)]."""
    r = _git("-C", root, "worktree", "list", "--porcelain")
    out = []
    for block in r.stdout.split("\n\n"):
        m = re.search(r"^worktree (.+)$", block, re.M)
        if m and os.path.realpath(m.group(1)) != root:
            out.append((os.path.realpath(m.group(1)), block))
    return out


def _in_worktrees(wt):
    return os.sep + os.path.join(".claude", "worktrees") + os.sep in wt + os.sep


def worktrees(agents, registry, doms, t):
    """Копии .claude/worktrees/* (QA-05, metis-0616, metis-0835) — решает wt_one: дежурный убирает сам пустые (почти
    сразу), слитые (через сутки), неслитые (ветка остаётся) и грязные (сначала патч и архив) — без живой сессии,
    процесса и субагента в копии. Заявки `pantheon wt done` (wt_requests) — без сроков, с теми же проверками; занятая
    копия ждёт в заявке. Пора, но нельзя (ссылки наружу, чужой lock, архив не собрался …) — тревога координатору.
    Убранное — строкой в STATE/wt-archive/removed-<день>.txt, в alerts.md — одна сводка в день.
    Копии вне .claude/worktrees (кроме основного checkout) — только тревога после WORKTREE_DAYS без сессии, никогда
    не удаляются. Записи с пропавшей папкой чистит один `git worktree prune` на репозиторий; решает _prune_state по пути из gitdir,
    как git: недоступная копия (в том числе с chmod 000 на ней самой) или живая сессия в пропавшей папке блокирует
    prune во всём репозитории (он глобален и снёс бы живую запись), недоступная — ещё и тревога."""
    ctx = WtCtx(agents, registry, t)
    reqs = wt_requests(doms, t)
    removed = []
    seen = set()
    with P.lock("worktrees"):
        for name, folders in doms.items():
            for f in folders if isinstance(folders, list) else []:
                root = os.path.realpath(os.path.expanduser(f))
                if root in seen or not os.path.isdir(os.path.join(root, ".git")):
                    continue
                seen.add(root)
                for wt, block in _copies(root):
                    try:
                        os.lstat(wt)
                    except OSError:
                        continue  # пропавшую или недоступную копию дальше не трогаем; prune решает _prune_state
                    short = wt.replace(P.HOME, "~")
                    if not _in_worktrees(wt):
                        # копия вне штатной папки: только тревога, никогда не удаляем
                        if _has_inside(wt, ctx.live):
                            continue
                        try:
                            out_age = (t - os.stat(wt).st_mtime) / 3600
                        except OSError:
                            continue
                        if out_age > WORKTREE_DAYS * 24:
                            P.alert_once(f"watch-wt-{wt}", "1", f"копия вне штатной папки {short} ({name}, "
                                         f"{out_age / 24:.0f} дн. без сессии) — координатору: слить или убрать", "watch")
                        continue
                    req = reqs.pop(wt, None)
                    verdict, text = wt_one(root, wt, block, ctx, requested=bool(req))
                    if verdict == "removed":
                        removed.append(text)
                        P.clear_once(f"watch-wt-{wt}")
                        _drop(req)
                    elif verdict == "keep":
                        P.alert_once(f"watch-wt-{wt}", text, f"копия {short} ({name}) не убрана: {text} — "
                                     "координатору: разобрать и убрать вручную", "watch")
                        _drop(req)
                need_prune, blockers = _prune_state(root, ctx.live)
                for path, ex in blockers:
                    P.alert_once(f"watch-prune-{path}", "unreadable", f"запись копии {path.replace(P.HOME, '~')} "
                                 f"недоступна ({ex}) — prune отложен", "watch")
                if need_prune and not blockers:
                    # без --expire: git worktree prune по умолчанию убирает записи без папки сразу (срок
                    # gc.worktreePruneExpire — только у gc); locked-записи git не трогает
                    _git("-C", root, "worktree", "prune")
    for left in reqs.values():  # копии больше нет в списке git — заявка исполнена или не нужна
        _drop(left)
    if removed:
        P.alert_once("watch-wt-removed", today(t), f"уборка копий: убрано {len(removed)} — " + "; ".join(removed[:3])
                     + (f" и ещё {len(removed) - 3}" if len(removed) > 3 else "")
                     + f"; журнал дня — {wt_archive('removed-' + today(t) + '.txt').replace(P.HOME, '~')}", "watch")


def _find_copy(path, roots):
    """Путь → (корень, копия, запись git) для копии <корень>/.claude/worktrees/<имя> одного из roots; иначе причина."""
    wt = os.path.realpath(os.path.expanduser(path))
    parent = os.path.dirname(wt)
    root = os.path.dirname(os.path.dirname(parent))
    if os.path.basename(parent) != "worktrees" or os.path.basename(os.path.dirname(parent)) != ".claude":
        return None, f"{path}: не копия .claude/worktrees/<имя> — такие эта команда не трогает"
    if root not in roots:
        return None, f"{path}: репозиторий {root.replace(P.HOME, '~')} не из папок реестра (directions.toml)"
    for w, block in _copies(root):
        if w == wt:
            return (root, wt, block), None
    return None, f"{path}: такой копии нет в `git worktree list` репозитория {root.replace(P.HOME, '~')}"


def wt_cmd(rest):
    """pantheon wt done <путь> [--dry-run] | pantheon wt plan [<папка> …] (metis-0835).
    done — убрать копию .claude/worktrees/<имя> сразу после отчёта субагента или слияния PR, без вопроса и без сырого
    git: те же проверки, что у дежурного (wt_one), но без сроков. В окне роли (есть PANTHEON_TMP) запись в STATE и
    чужие процессы закрыты — команда кладёт заявку в <кэш окна>/wt-req, её исполняет плановый проход (раз в 5 мин).
    Вне окна — сразу; копия занята (живая сессия, субагент ещё работает) — заявка в STATE/wt-req, проход уберёт её,
    когда освободится. Код: 0 — убрана или заявка принята, 1 — убрать нельзя (причина последней строкой), 2 — не тот
    вызов или не та папка. plan — сухой прогон: что дежурный сделал бы с каждой копией папок (по умолчанию — всех
    папок реестра); ничего не меняет."""
    if rest[:1] == ["plan"]:
        return wt_plan(rest[1:])
    args = [a for a in rest[1:] if a != "--dry-run"]
    if rest[:1] != ["done"] or len(args) != 1 or args[0].startswith("-"):
        print("использование: pantheon wt done <путь копии .claude/worktrees/<имя>> [--dry-run] | "
              "pantheon wt plan [<папка репозитория> …]", file=sys.stderr)
        return 2
    dry_run = "--dry-run" in rest
    t = P.now()
    wt = os.path.realpath(os.path.expanduser(args[0]))
    tmp = os.environ.get("PANTHEON_TMP")
    if tmp and not dry_run:
        parent = os.path.dirname(wt)
        if os.path.basename(parent) != "worktrees" or os.path.basename(os.path.dirname(parent)) != ".claude" \
                or not os.path.isdir(wt):
            print(f"{args[0]}: не копия .claude/worktrees/<имя> — такие эта команда не трогает", file=sys.stderr)
            return 2
        d = os.path.join(os.path.dirname(os.path.realpath(tmp)), WT_REQ_DIR)
        name = hashlib.sha1(wt.encode()).hexdigest()[:16] + ".json"
        try:
            os.makedirs(d, mode=0o700, exist_ok=True)
            tmpf = os.path.join(d, f".{name}.{os.getpid()}")
            with open(tmpf, "x", encoding="utf-8") as fh:
                json.dump({"path": wt, "time": t}, fh)
            os.replace(tmpf, os.path.join(d, name))
        except OSError as e:
            print(f"заявка не записана: {e.strerror or e}", file=sys.stderr)
            return 1
        print(f"заявка принята: плановый проход (раз в 5 мин) уберёт {wt.replace(P.HOME, '~')}, когда в ней нет живой "
              "сессии и субагента; грязную — сначала в патч и архив. Итог — STATE/wt-archive/removed-<день>.txt, "
              "отказ — строкой в alerts.md")
        return 0
    roots = [os.path.realpath(os.path.expanduser(f)) for fs in domains().values()
             for f in (fs if isinstance(fs, list) else []) if isinstance(f, str)]
    found, why = _find_copy(args[0], roots)
    if not found:
        print(why, file=sys.stderr)
        return 2
    root, wt, block = found
    agents = P.agents_all()
    if agents is None:
        print("claude agents --json не ответил — живые сессии неизвестны, копию не трогаю", file=sys.stderr)
        return 1
    with P.lock("worktrees"):
        verdict, text = wt_one(root, wt, block, WtCtx(agents, P.sessions_registry(), t), requested=True, dry=dry_run)
    short = wt.replace(P.HOME, "~")
    if verdict == "removed":
        print(f"убрана: {text}")
        P.clear_once(f"watch-wt-{wt}")
        return 0
    if verdict == "plan":
        print(f"{short}: {text}")
        return 0
    if verdict in ("live", "wait"):
        if dry_run:
            print(f"{short}: занята — {text}")
            return 0
        d = P.path(WT_REQ_DIR)
        try:
            os.makedirs(d, exist_ok=True)
            P.write_json(os.path.join(d, hashlib.sha1(wt.encode()).hexdigest()[:16] + ".json"), {"path": wt, "time": t})
        except OSError as e:
            print(f"{short}: занята ({text}), заявка не записана: {e.strerror or e}", file=sys.stderr)
            return 1
        print(f"{short}: занята ({text}) — заявка оставлена, плановый проход уберёт копию, когда она освободится")
        return 0
    print(f"{short}: не убрана — {text}", file=sys.stderr)
    return 1


def wt_plan(folders):
    """Сухой прогон уборки (metis-0616, 0835): для каждой копии .claude/worktrees папок — итог wt_one(dry=True) строкой
    «итог<TAB>копия<TAB>почему». Ничего не меняет: git только читает (GIT_OPTIONAL_LOCKS=0), обход — без записи."""
    roots = [os.path.realpath(os.path.expanduser(f)) for f in folders] or \
        [os.path.realpath(os.path.expanduser(f)) for fs in domains().values()
         for f in (fs if isinstance(fs, list) else []) if isinstance(f, str)]
    agents = P.agents_all()
    if agents is None:
        print("предупреждение: claude agents --json не ответил — живые сессии по cwd не учтены (процессы и субагенты учтены)",
              file=sys.stderr)
        agents = []
    ctx = WtCtx(agents, P.sessions_registry(), P.now())
    for root in dict.fromkeys(roots):
        if not os.path.isdir(os.path.join(root, ".git")):
            continue
        for wt, block in _copies(root):
            if not _in_worktrees(wt) or not os.path.lexists(wt):
                continue
            verdict, text = wt_one(root, wt, block, ctx, dry=True)
            print(f"{verdict}\t{wt.replace(P.HOME, '~')}\t{text}")
    return 0


# --- кэши песочниц (metis-0620) ---------------------------------------------------------------------------------

SANDBOX_DAYS = 7                  # запись кэша окна, которую не меняли и не держит процесс дольше, — убираем
SANDBOX_CAP_MB = 5120             # потолок всего кэша песочниц: больше после уборки — тревога
SANDBOX_PARTS = ("tmp", "npm", "corepack", "logs", "log")   # что чистим в <кэш>/<окно>/; остальное не трогаем
SANDBOX_WALK = 200000             # обход возраста записи длиннее — считаем свежей


def sandbox_root():
    return os.path.join(P.HOME, "Library", "Caches", "pantheon-sandbox")


def _open_paths():
    """Пути, которые сейчас держат процессы (lsof -Fn: файлы, cwd, сокеты), или None, если lsof не ответил —
    тогда ничего не удаляем."""
    try:
        r = subprocess.run(["lsof", "-nP", "-Fn"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if not r.stdout:
        return None
    return {ln[1:] for ln in r.stdout.splitlines() if ln.startswith("n/")}


def _tree_newer(path, lim):
    """Менялось ли что-то в записи (сама, любая вложенная) позже lim. Без перехода по ссылкам; не уложились в
    SANDBOX_WALK — считаем, что менялось."""
    n, stack = 0, [path]
    while stack:
        cur = stack.pop()
        try:
            if os.lstat(cur).st_mtime > lim:
                return True
            if not os.path.isdir(cur) or os.path.islink(cur):
                continue
            with os.scandir(cur) as it:
                for e in it:
                    n += 1
                    if n > SANDBOX_WALK:
                        return True
                    stack.append(e.path)
        except OSError:
            continue
    return False


def _open_dir(name, dir_fd=None):
    """Открыть папку без перехода по ссылке (O_NOFOLLOW): ссылка вместо папки — OSError."""
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)


def sandbox_clean(root, t, opened, days=None):
    """Убирает в <root>/<окно>/{tmp,npm,corepack,logs} прямые записи старше days дней, которых не держит процесс
    (opened — множество путей из lsof). Окно может подменить папку ссылкой между проверкой и удалением (проход идёт
    вне песочницы), поэтому корень, окно и часть открываются по дескрипторам с O_NOFOLLOW, а запись удаляется
    относительно дескриптора части (rmtree/unlink с dir_fd): подмена уже ничего не перенаправит. Запись-ссылку
    снимаем саму, цель не трогаем. Возраст и список читаем по пути — это только чтение. Возвращает (убрано записей,
    не удалось убрать)."""
    days = SANDBOX_DAYS if days is None else days
    lim = t - days * 86400
    removed, failed = 0, 0
    root = os.path.realpath(root)
    try:
        root_fd = _open_dir(root)
    except OSError:
        return 0, 0
    try:
        for role in sorted(os.listdir(root_fd)):
            try:
                role_fd = _open_dir(role, root_fd)
            except OSError:
                continue
            try:
                for part in SANDBOX_PARTS:
                    try:
                        part_fd = _open_dir(part, role_fd)
                    except OSError:
                        continue
                    try:
                        for name in sorted(os.listdir(part_fd)):
                            p = os.path.join(root, role, part, name)
                            if _tree_newer(p, lim):
                                continue
                            if any(o == p or o.startswith(p + os.sep) for o in opened):
                                continue
                            try:
                                st = os.stat(name, dir_fd=part_fd, follow_symlinks=False)
                                if stat.S_ISDIR(st.st_mode):
                                    shutil.rmtree(name, dir_fd=part_fd)
                                else:
                                    os.unlink(name, dir_fd=part_fd)
                                removed += 1
                            except OSError:
                                with contextlib.suppress(OSError):
                                    shutil.rmtree(name, ignore_errors=True, dir_fd=part_fd)
                                try:
                                    os.stat(name, dir_fd=part_fd, follow_symlinks=False)
                                    failed += 1
                                except OSError:
                                    removed += 1
                    finally:
                        os.close(part_fd)
            finally:
                os.close(role_fd)
    finally:
        os.close(root_fd)
    return removed, failed


def sandbox_mb(root):
    """Размер кэша песочниц, МБ (du -sk), или None."""
    try:
        r = subprocess.run(["du", "-sk", root], capture_output=True, text=True, timeout=120)
        return int(r.stdout.split()[0]) // 1024
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def sandbox_sweep(t):
    """Плановая уборка кэшей окон ролей (в песочнице окна удалить чужое нельзя, дежурный — вне неё). Потолок —
    SANDBOX_CAP_MB (env PANTHEON_SANDBOX_CAP_MB): после уборки больше — тревога раз в день."""
    root = sandbox_root()
    if not os.path.isdir(root):
        return
    opened = _open_paths()
    if opened is not None:
        removed, failed = sandbox_clean(root, t, opened)
        if removed or failed:
            P.alert(f"кэши песочниц: убрано записей {removed}" + (f", не удалось {failed}" if failed else "")
                    + f" (старше {SANDBOX_DAYS} дн., без процессов)", "watch")
    try:
        cap = int(os.environ.get("PANTHEON_SANDBOX_CAP_MB") or SANDBOX_CAP_MB)
    except ValueError:
        cap = SANDBOX_CAP_MB
    mb = sandbox_mb(root)
    if mb is not None and mb > cap:
        P.alert_once("watch-sandbox-cap", today(t), f"кэши песочниц {mb} МБ при потолке {cap} МБ даже после уборки "
                     f"({root.replace(P.HOME, '~')}) — координатору: посмотреть, что держит место", "watch")
    else:
        P.clear_once("watch-sandbox-cap")


def cc_version(t):
    """Claude Code сменил версию (SCOUT-05) — строка в тревоги, событие cc_updated для пересмотров и проверка опор
    (SEC-16); не в порядке — уведомление и поручение Метиде через тревогу."""
    v = os.environ.get("PANTHEON_FAKE_CC")
    if v is None:
        r = subprocess.run([P.claude_bin(), "--version"], env=P.claude_env(), capture_output=True, text=True, timeout=60)
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
            if got == P.SKIPPED:  # metis-0708: повторная проверка под блокировкой имени сказала «не надо» — не сбой
                P.alert(f"{name} после паузы: пропуск — {P.SKIP_WHY}", "watch")
                continue
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
                subprocess.run([P.claude_bin(), "stop", a["id"]], env=P.claude_env(), capture_output=True, text=True, timeout=60)
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
# Каждый самозапуск — строка в alerts.md (её Зевс несёт в сводку). Задачу, которую ведёт другая сессия (owner не пуст, не
# само направление и не его команда — TEAM_OWNERS), координатору не отдаёт: строка «не отдаю координатору» (metis-0564).
# Красная память Mac самозапуск не откладывает — pantheon start только предупреждает ([sb-simplify] п. 5).

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
            if not P.answers_mod().is_answer_head(m.group(2)):  # окно вопросов или ответ в чате (metis-0405)
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


ONESHOT_STARTED = []  # направления, поднятые разовым запуском в этом проходе: самозапуск их не трогает


def oneshots(agents, registry, doms, t):
    """Разовые запуски (metis-0284, STATE/oneshot.json — lib/night.py): пришло время — поднять направление один раз.
    Запись гасится до запуска, повторный проход её не повторит. Пока нельзя (шлюз недели и ночи, сессия занята, одна
    за проход) — ждёт до срока; после срока гаснет с тревогой. Пачка ночи, изменённая после фиксации вечером, не запускается.
    Закрытый недельный запор — запись ждёт до срока (не гасится). Код возврата запуска ≠0: запись уже погашена
    (повтора нет), владельцу — уведомление «не вышел». Пропуск под блокировкой имени (код 4, metis-0708) — не сбой:
    запись снова ждёт до срока."""
    N = P.night_mod()
    del ONESHOT_STARTED[:]
    started = False
    for it in N.oneshot_due(t):
        oid, d = it["id"], it.get("target")
        bad = None
        if d not in doms:
            bad = f"нет направления «{d}» в domains.json"
        elif it.get("pack") and N._sha(os.path.join(P.PANTHEON, it["pack"])) != it.get("sha"):
            bad = f"пачка {it['pack']} изменилась после фиксации в начале вечера — запускался бы не тот текст"
        elif it.get("night"):
            st = N.load(date.fromisoformat(it["night"]))
            if st.get("skipped"):
                bad = f"ночь пропущена ({st['skipped']})"
        if not bad and t >= float(it.get("expires") or 0):
            bad = "срок вышел" + (f", ждал: {it['wait']}" if it.get("wait") else "")
        if bad:
            if N.oneshot_update(oid, t, done_at=t, result=f"не запущен: {bad}"):
                P.alert(f"разовый запуск {oid} погашен без запуска: {bad}", "watch")
                P.notify_soon(f"oneshot-{oid}", f"Разовый запуск {d} не состоялся: {bad}", group="oneshot")
            continue
        hold = holders(d, agents, registry)
        poke = nudge_target(hold)
        why = wake_block(d, agents, registry, auto=True, nudge=bool(poke))
        if not why:
            ok, gw = N.gate("autostart", t, [a for a in agents if a not in hold], registry)
            why = None if ok else f"недельный лимит: {gw}"
        if not why and started:
            why = "одна сессия за проход — в следующий"
        if why:
            if why != it.get("wait"):
                N.oneshot_update(oid, t, wait=why)
                P.alert(f"разовый запуск {oid} ждёт: {why} (срок {P.stamp(float(it['expires']))[11:]})", "watch")
            continue
        if not N.oneshot_update(oid, t, done_at=t, result="запускается"):  # гасим до запуска: проход могут оборвать
            continue
        if poke:
            rc = P.resume_session(d, poke, it["text"], "tick", recheck=recheck(d, True, nudge=True))[0]
        else:
            rc = resume_or_start(d, agents, it["text"], origin="tick", auto=True)
        if rc == P.SKIPPED:
            # metis-0708: под блокировкой имени «не надо» (окно уже работает, его поднимает другой процесс) — задание не
            # передано, но это не сбой: запись снова ждёт до срока, без уведомления «не вышел»
            # тревога — только при смене причины ожидания, как у ожидания выше: тот же пропуск каждый проход (окно
            # занято, пока запись ждёт срока) — одна строка в alerts, а не строка на проход (metis-0708, ревью argus)
            why = f"пропуск — {P.SKIP_WHY}"
            N.oneshot_update(oid, t, done_at=None, result=None, wait=why)
            if why != it.get("wait"):
                P.alert(f"разовый запуск {oid} ждёт: {why} (срок {P.stamp(float(it['expires']))[11:]})", "watch")
            continue
        # красная память запуск больше не откладывает ([sb-simplify] п. 5): pantheon start только предупреждает
        res = ("передано задание простаивающей сессии" if poke else "запущен") if rc == 0 else f"не вышло, код {rc}"
        N.oneshot_update(oid, t, result=res)
        P.alert(f"разовый запуск {oid}: {d} — {res}" + (f" (пачка {it['pack']})" if it.get("pack") else ""), "watch")
        if rc != 0:
            P.notify_soon(f"oneshot-{oid}", f"Разовый запуск {d} не вышел: код {rc}", group="oneshot")
        else:
            awake().RESUMED.append(d)
        ONESHOT_STARTED.append(d)
        started = True


# metis-0564: кто входит в команду координатора — его лиды и исполнители (субагенты его сессии). Задачу с таким
# owner координатор и ведёт; задачу другой сессии (agent-kit-62, zeus, «вы», другое направление, мастерская daedalus-*,
# hestia) самозапуск его сессии не отдаёт.
TEAM_OWNERS = ("hephaestus", "apollo", "dev", "talos", "argus", "codex")


def owner_elsewhere(h, d):
    """owner задачи, если её ведёт не координатор направления d и не его команда; иначе None."""
    o = str(h.get("owner") or "").strip().lower()
    if not o or o == d or o.split("-")[0] in TEAM_OWNERS:
        return None
    return o


def push_key(h, pos):
    """Порядок задач в толчке самозапуска (metis-0292): основные раньше запаса, затем priority (меньше — важнее),
    порядок пачки (поле order), затем отметка владельца. Запас — order от 10**6 (migrate_batches) или место «запас»."""
    T = P.tasks_mod()
    o = T._ord(h)
    spare = (10 ** 6 <= o < 10 ** 9) or "запас" in str(h.get("batch") or "").lower()
    return (spare, T._prio(h), o, pos)


# --- цель окна на задаче, которую у окна забрали (metis-0631, слово владельца 01.11 «А — делаем») -------------------
# Самозапуск поднимает координатора с /goal: «Самозапуск дежурным …: следующая: X. Все: X, Y. …» + TASK_GOAL. Цель — это
# Stop-хук Claude Code с проверяющей моделью; она живёт в сессии и переживает respawn и --resume (документация /goal:
# «Resume with an active goal»). Сказать живой фоновой сессии «/goal clear» нечем: push отдаёт текст хуком при старте
# процесса, а не командой. Поэтому на каждом проходе: цель держателя имени — по его транскрипту (запись goal_status,
# met = false); задачу из «Все:» передали другому исполнителю (owner — не окно и не его команда), перенесли в другое
# направление, вернули во входящие или отменили — окно перезапускается свежей сессией с новой целью тем же
# механизмом, что самозапуск (fresh_start: claude stop, имя свободно, claude --bg с /goal по оставшимся и следующим
# задачам очереди). Очереди нет или подъём сейчас закрыт (лимит, пауза, ночь) — сессия останавливается и убирается из
# списка (claude stop + rm, переписка остаётся): иначе продолжение вернуло бы старую цель. «Ждёт» (waiting) задачу не
# забирает: туда её ставит сама сессия, и TASK_GOAL отпускает её отчётом «заблокировано». Сессию, которая ждёт вас
# (blocked), и вкладку не трогаем — тревога.
SELFSTART = "Самозапуск дежурным"
GOAL_IDS = re.compile(SELFSTART + r".*?Все: ([a-z][a-z0-9-]*-\d{3,}(?:, [a-z][a-z0-9-]*-\d{3,})*)", re.S)
GOAL_GONE = {"inbox": "вернули во входящие", "dropped": "отменена"}
GOAL_TAIL = 4 * 1024 * 1024  # хвост транскрипта: goal_status пишется на каждом конце хода, крутящаяся сессия — там


def session_goal(a):
    """Активная цель сессии a по её транскрипту: условие последней записи goal_status, если цель не достигнута и не
    снята (met, impossible, failed, cleared; «Goal cleared» от /goal clear). → текст или None."""
    tp = P.transcript_path(a)
    if not tp:
        return None
    cond = None
    try:
        with open(tp, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - GOAL_TAIL))
            if size > GOAL_TAIL:
                fh.readline()  # первая строка хвоста — обрывок
            for raw in fh:
                if b'"goal_status"' not in raw and b"Goal cleared" not in raw:
                    continue
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                at = d.get("attachment")
                if isinstance(at, dict) and at.get("type") == "goal_status":
                    over = at.get("met") is True or any(at.get(k) for k in ("impossible", "failed", "cleared"))
                    cond = None if over else (str(at.get("condition") or "") or None)
                    continue
                msg = d.get("message") if d.get("type") == "user" else None
                body = msg.get("content") if isinstance(msg, dict) else None
                if isinstance(body, str) and body.lstrip().startswith("<local-command-stdout>Goal cleared"):
                    cond = None
    except OSError:
        return None
    return cond


def goal_ids(cond):
    """Задачи цели самозапуска из её условия («Все: X, Y.») или [] — цель поставил не самозапуск."""
    m = GOAL_IDS.search(str(cond or ""))
    return m.group(1).split(", ") if m else []


def goal_gone(h, d):
    """Почему задачу цели окна d это окно больше не ведёт, или None (ведёт, сделана, ждёт; карточки нет)."""
    if not h:
        return None
    o = owner_elsewhere(h, d)
    if o:
        return f"ведёт {o}"
    if h.get("direction") and h.get("direction") != d:
        return f"перенесена в {h.get('direction')}"
    return GOAL_GONE.get(h.get("status"))


def goal_release(d, hold, tasks):
    """Снять ли цель окна d: → None (нечего снимать), текст (снять нельзя — почему) или {a, gone, keep}: a — держатель с
    целью, gone — {задача: почему ушла}, keep — задачи цели, которые окно ещё ведёт (todo, doing)."""
    for a in sorted(hold, key=lambda x: x.get("startedAt") or 0, reverse=True):
        ids = goal_ids(session_goal(a)) if a.get("id") and a.get("sessionId") else []
        gone = {i: w for i in ids for w in [goal_gone((tasks.get(i) or (None, {}, None))[1], d)] if w}
        if not gone:
            continue
        what = ", ".join(f"{i} ({w})" for i, w in gone.items())
        if any(not x.get("id") for x in hold):
            return f"цель окна на задачах, которые ушли: {what} — снять нельзя, имя держит вкладка"
        if any(x.get("state") == "blocked" for x in hold):
            return f"цель окна на задачах, которые ушли: {what} — сессия ждёт вас, сниму после ответа"
        keep = [i for i in ids if i not in gone and (tasks.get(i) or (None, {}, None))[1].get("status") in ("todo", "doing")]
        return {"a": a, "gone": gone, "keep": keep, "what": what}
    return None


def goal_stop(d, swap, why):
    """Снять цель без нового подъёма: claude stop + rm держателя (продолжение вернуло бы старую цель). Тревога."""
    a = swap["a"]
    left = P.stop_and_rm(d, a["id"], "goal-released")
    P.start_log(f"goal-released\t{d}\t{a['id']}\t{why}" + (f"\t{P.refused_by(left)}: {left}" if left else ""))
    P.alert_once(f"goal-released-{d}", a["id"], f"самозапуск {d}: цель окна снята — {swap['what']}; новой задачи сейчас "
                 f"нет ({why}), сессия {a['id']} остановлена" + (f", из списка не убрана ({P.refused_by(left)}: {left})"
                                                               if left else ""), "watch")


def goal_others(a, rows):
    """Строки claude agents или реестра без сессии a (по id и sessionId): её одну смена цели и заменяет."""
    return [x for x in rows if not (x.get("id") == a.get("id") or (x.get("sessionId") and
                                                                  x.get("sessionId") == a.get("sessionId")))]


def goal_block(d, a, agents, registry):
    """Почему сменить цель окна d сейчас нельзя, или None: та же wake_block, что у самозапуска, без одной сессии a.
    Другой держатель имени (владелец поднял окно вручную, копия «имя (2)») — «уже работает», как у wake_block."""
    return wake_block(d, goal_others(a, agents), goal_others(a, registry), auto=True)


def goal_recheck(d, a):
    """Повторная проверка под блокировкой имени перед сменой цели, по свежему claude agents: держит имя только a —
    иначе отказ (ревью argus: ручной запуск между снимком и блокировкой иначе погасил бы stop_copies)."""
    return lambda: goal_block(d, a, P.agents_all() or [], P.sessions_registry())


def autostart(agents, registry, doms, t, dry=False):
    say = print if dry else (lambda *_: None)
    st = {d: as_state(v) for d, v in P.read_json(P.path("autostart.json"), {}).items()}
    # pantheon resume|wake <имя> сбрасывают счётчик сбоев меткой, а не правкой autostart.json: проход идёт минутами,
    # и его запись в конце затёрла бы их правку (ревью argus)
    # метки — в STATE/hq-rw/autostart-reset; STATE/autostart-reset — от выпусков до metis-0523 (читаем, пока есть)
    for box in (P.path(P.HQ_RW, "autostart-reset"), P.path("autostart-reset")):
        with contextlib.suppress(OSError):
            for f in os.listdir(box):
                st.pop(f, None)
                if not dry:
                    with contextlib.suppress(OSError):
                        os.unlink(os.path.join(box, f))  # unlink ссылку не проходит
    if not dry:
        autostart_check(agents, registry, st, t)
    try:
        tasks = P.tasks_mod().load_tasks(P.PANTHEON)
    except Exception:
        tasks = {}
    since = sanction_since(t, preview=dry)
    marked = owner_marked(since)
    want, off, hq, other = {}, P.hq_led(), {}, {}
    for tid in marked:  # порядок отметок владельца
        h = (tasks.get(tid) or (None, {}, None))[1]
        d = h.get("direction")
        if h.get("status") in ("todo", "doing") and d in doms and owner_elsewhere(h, d):
            # metis-0564: задачу ведёт другая сессия (agent-kit-62, Зевс, вы, другое направление) — координатору
            # направления её не отдаём, и места в очереди его самозапуска она не держит
            other.setdefault(d, []).append(f"{tid} ({owner_elsewhere(h, d)})")
            continue
        if h.get("status") in ("todo", "doing") and d in doms:
            # metis-0155: координатора у направления, которое ведёт Пританей, нет — самозапуск его не поднимает
            (hq if d in off else want).setdefault(d, []).append(tid)
    for v in want.values():  # толчок идёт по важности, а не по времени отметки (metis-0292)
        pos = {x: n for n, x in enumerate(v)}
        v.sort(key=lambda x: push_key(tasks[x][1], pos[x]))
    for d, v in sorted(hq.items()):
        say(f"{d}: ведёт Пританей (coordinator = false) — самозапуск не поднимает, задачи {', '.join(v)}: "
            f"pantheon wake {d} --task <id>")
    for d, v in sorted(other.items()):
        say(f"{d}: не отдаю координатору — задачи ведёт другая сессия (owner): {', '.join(v)}")
    say(f"решения владельца учитываются с {P.stamp(since)}; задачи с ними: "
        + ("; ".join(f"{d}: {', '.join(v)}" for d, v in sorted(want.items())) or "нет"))
    release = {}  # metis-0631: окна, чья цель самозапуска держит задачу, которую у окна забрали
    for d in sorted(doms) if tasks else ():
        r = None if d in off else goal_release(d, holders(d, agents, registry), tasks)
        if isinstance(r, str):
            say(f"{d}: {r}")
            if not dry:
                P.alert_once(f"goal-stuck-{d}", r[:80], f"самозапуск {d}: {r}", "watch")
        elif r:
            release[d] = r
            if not dry:
                P.clear_once(f"goal-stuck-{d}")
            v = want.setdefault(d, [])
            v.extend(x for x in r["keep"] if x not in v)  # оставшиеся задачи цели — в новую цель, после очереди
        elif not dry:
            P.clear_once(f"goal-stuck-{d}")
    running = [d for d in doms if holders(d, agents, registry) or d in ONESHOT_STARTED]
    # ночь с одобренными пачками (metis-0284): ночью идут только пачки — их поднимают разовые запуски, а не отметки
    packs = P.night_mod().pack_night(t)
    shop = sorted({a.get("name") for a in list(agents) + list(registry) if str(a.get("name") or "").startswith("daedalus-")
                   and holders(a["name"], agents, registry)})
    started = False
    chosen = {}  # id → направление: задачи, которые этим проходом пошли (или пошли бы) параллельно (metis-0248)
    for d, tids in sorted(want.items()):
        s = st.setdefault(d, {})
        hold = holders(d, agents, registry)
        swap = release.get(d)
        # порядок и ожидание по depends_on/touches (metis-0248, шаг 2): сначала зависимости, при равенстве — отметки;
        # не отдаём ту, что ждёт незакрытую, зависшую, общие файлы с идущей у другого или стоит в цикле
        if tasks:
            T = P.tasks_mod()
            busy = dict(chosen)
            for i, (_, h, _) in tasks.items():
                if h.get("status") == "doing" and h.get("type", "task") == "task" and h.get("direction") != d \
                        and h.get("direction") in running:
                    busy[i] = h.get("direction")
            plan = T.plan_batch(tasks, tids, t, busy={k: v for k, v in busy.items() if v != d})
            if not dry:
                if plan["wait"]:
                    bits = "; ".join(f"{x} — {v}" for x, v in sorted(plan["wait"].items()))
                    P.alert_once(f"autostart-dwait-{d}", f"{today(t)}-{bits[:60]}", f"самозапуск {d}: {bits}", "watch")
                else:
                    P.clear_once(f"autostart-dwait-{d}")
                for key, msg in (("cycle", lambda x, v: f"{x} в цикле зависимостей ({' → '.join(v)}), не запущена"),
                                 ("stuck", lambda x, v: f"{x} ждёт зависший {v}, не отдана")):
                    if plan[key]:
                        bits = "; ".join(msg(x, v) for x, v in sorted(plan[key].items()))
                        P.alert_once(f"autostart-{key}-{d}", f"{today(t)}-{bits[:60]}", f"самозапуск {d}: {bits}", "watch")
                    else:
                        P.clear_once(f"autostart-{key}-{d}")
            for x, v in sorted({**plan["wait"], **{k: "ждёт зависший " + w for k, w in plan["stuck"].items()},
                                **{k: "цикл " + " → ".join(c) for k, c in plan["cycle"].items()}}.items()):
                say(f"{d}: не отдаю {x} — {v}")
            tids = plan["go"]
            if not tids:
                if swap:  # цель снимается, а дать окну нечего — остановить, чтобы не крутилось
                    say(f"{d}: цель окна снята бы — {swap['what']}; очереди нет, сессия остановилась бы")
                    if not dry:
                        goal_stop(d, swap, "очереди нет")
                continue
        # простаивающий держатель (metis-0212) — передать той же сессии то же задание, а не «уже работает»: Claude Code
        # сам перезапустил фоновую сессию и задания у неё нет (working + idle) или закончила ход с живым процессом (done)
        poke = None if swap else nudge_target(hold)
        if hold and not poke and not swap:
            say(f"{d}: уже работает")
            continue
        what = (f"{d}: закончила ход, а задачи с вашим решением ждут" if poke and poke.get("state") == "done"
                else f"{d}: Claude Code сам перезапустил фоновую сессию, задания у неё нет")
        why = (goal_block(d, swap["a"], agents, registry)
               if swap else wake_block(d, agents, registry, auto=True, nudge=bool(poke)))
        if not why and d in ONESHOT_STARTED:
            why = "поднято разовым запуском в этом проходе"
        if not why and packs:
            why = "ночью идут только одобренные пачки (" + ", ".join(p["path"] for p in packs) + ")"
        if not why and s.get("gave_up"):
            why = f"самозапуск встал после сбоев (pantheon resume {d})"
        if not why and not poke and not swap and len(running) >= AUTOSTART_MAX:  # передача места не занимает: сессия уже есть
            why = f"нет места: уже работают {', '.join(running)} (не больше {AUTOSTART_MAX} направлений)"
        if not why and not poke and not swap and len(running) + len(shop) >= SESSIONS_MAX:
            why = f"нет места: сессий Пантеона {len(running) + len(shop)} из {SESSIONS_MAX}"
        # новое дело: жёлтая зона днём, тяжёлые, ночь и её бюджет, утро после 04:00 (metis-0127); передача задания —
        # тоже новое дело, а простаивающий держатель тяжёлым не считается (его working остался от прежнего процесса)
        if not why:
            ok, gw = P.night_mod().gate("autostart", t, [a for a in agents if a not in hold], registry)
            why = None if ok else f"недельный лимит: {gw}"
        nxt = float(s.get("next") or float(s.get("last") or 0) + AUTOSTART_BACKOFF)
        if not why and t < nxt and (not swap or s.get("swap") == swap["a"].get("id")):
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
        if not why:
            chosen.update({i: d for i in tids})
        if dry and swap:
            say(f"{d}: цель окна на задачах, которые ушли: {swap['what']} — " + (
                f"перезапустил бы с новой целью (задачи {', '.join(tids[:5])})" if not why else
                ("сменю в следующий проход" if why.startswith(("одна сессия", "пауза между")) else
                 f"сессия ведёт свои {', '.join(swap['keep'])}, сниму, когда подъём откроется: {why}"
                 if swap["keep"] else f"остановил бы сессию: {why}")))
            continue
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
        if why and swap:  # смена цели закрыта: в следующий проход; свои задачи у сессии есть — ждать открытия подъёма
            if why.startswith(("одна сессия", "пауза между")):  # (пауза, лимит, ночь); своих нет — остановить
                pass
            elif swap["keep"]:  # ревью argus: не гасить сессию, у которой своя задача ещё в работе
                P.alert_once(f"goal-wait-{d}", f"{swap['a']['id']}-{why[:40]}",
                             f"самозапуск {d}: цель окна на задачах, которые ушли: {swap['what']}; сессия ведёт свои "
                             f"{', '.join(swap['keep'])} — снимем, когда подъём откроется ({why})", "watch")
            else:
                goal_stop(d, swap, why)
            continue
        if why:
            if s.get("gave_up"):  # самозапуск встал и держится — одна macOS, пока не снимут
                P.notify_soon(f"autostart-gaveup-{d}", gave_up_note(d, s), group=f"autostart-{d}", once=True)
            if why.startswith("нет доверия"):
                P.alert_once(f"autostart-trust-{d}", got[2], f"самозапуск {d} невозможен: {why}", "watch")
                P.notify_soon(f"autostart-trust-{d}", f"{d}: нужно ваше доверие к папке", group=f"autostart-{d}",
                              once=True)
            elif not why.startswith(("пауза между", "одна сессия", "не главный Mac", "недельный лимит", "ночью идут",
                                     "поднято разовым")):
                P.alert_once(f"autostart-wait-{d}", f"{today(t)}-{why[:40]}", f"самозапуск {d} ждёт: {why} (задачи "
                             f"{', '.join(tids[:3])})", "watch")
            continue
        task = (f"{SELFSTART} по задачам с вашим решением (сначала зависимости, затем приоритет, порядок пачки и ваших отметок, запас последним; "
                f"цепочку веди сама, не режь): следующая: {tids[0]}. Все: {', '.join(tids)}. Прочитай STATUS.md и "
                "задачи, продолжай с первой по приоритету; что ждёт владельца — Зевсу строкой.")
        s.update(last=t, pending=True)
        P.write_json(P.path("autostart.json"), st)  # до запуска: проход могут оборвать по таймауту
        if swap:  # metis-0631: та же сессия цель не сменит — свежая сессия с /goal по новому списку (fresh_start)
            s["swap"] = swap["a"].get("id")
            P.write_json(P.path("autostart.json"), st)
            gone = ", ".join(swap["gone"])
            text = (task + f" Задачи {swap['what']} у этого окна больше не на тебе: их не веди и не закрывай, "
                    "начатое по ним — строкой в STATUS.md.")
            rc = P.fresh_start(d, swap["a"], P.fresh_text("смена цели", d, swap["a"].get("id"), text), "tick",
                               recheck=goal_recheck(d, swap["a"]), reason=f"цель самозапуска: ушли {gone}", goal=P.TASK_GOAL)
            if rc == P.SKIPPED:  # повторная проверка под блокировкой: имя держит не только она — в следующий проход
                P.alert(f"самозапуск {d}: цель окна на задачах, которые ушли: {swap['what']} — смена отложена: "
                        f"{P.SKIP_WHY}", "watch")
                s["pending"] = False  # не запускали: не сбой и не успех
                P.write_json(P.path("autostart.json"), st)
                continue
            else:
                P.alert(f"самозапуск {d}: цель окна снята — {swap['what']}; " + (
                    f"окно перезапущено с новой целью (задачи {', '.join(tids[:5])})" if rc == 0 else
                    f"перезапуск с новой целью не вышел, код {rc}"), "watch")
        elif poke:  # тот же путь, что продолжение остановленной: claude respawn + текст для хука push (P.resume_session)
            rc = P.resume_session(d, poke, task, "tick", recheck=recheck(d, True, nudge=True))[0]
        else:
            rc = resume_or_start(d, agents, task, origin="tick", auto=True)
        if rc == P.SKIPPED:  # у смены цели (swap) пропуск разобран выше
            # metis-0708: повторная проверка под блокировкой имени сказала «не надо» — окно между проходом и подъёмом
            # получило ввод (уже работает), его остановили или поднимает другой процесс. Не запускали: не сбой и не
            # успех — без тревоги и счётчика (строка resume-skip — в start.log). Раньше это шло «код 4» и сбоем:
            # 02.11 «сбой 2 из 3» у работавшего metis-pantheon и пауза 2 ч, третий пропуск остановил бы самозапуск
            say(f"{d}: пропуск — {P.SKIP_WHY}")
            s["pending"] = False
            P.write_json(P.path("autostart.json"), st)
            if not poke:
                running.append(d)  # имя держат или поднимают — место занято
            continue
        if poke:
            P.alert(f"{what} — " + (f"передал задание (задачи {', '.join(tids[:5])})" if rc == 0 else
                                    f"передать задание не вышло, код {rc}"), "watch")
        elif not swap:
            P.alert(f"самозапуск: {d} по задачам {', '.join(tids[:5])} — " + ("запущен" if rc == 0 else
                                                                               f"не вышло, код {rc}"), "watch")
        # красная память запуск не откладывает ([sb-simplify] п. 5, metis-0523): pantheon start только предупреждает
        if rc != 0:
            fail(d, s, t, f"код запуска {rc}")
        else:  # список сессий этого прохода её ещё не видит — «запрет сна Mac» держится по этой метке
            awake().RESUMED.append(d)
        if not poke and not swap:
            running.append(d)
        started = True
    if not dry:
        P.write_json(P.path("autostart.json"), st)


# --- окна по вашему ответу в окне вопросов (metis-0523, [sb-simplify] п. 5, решение владельца 27.10 «(а)») -----------
# Вопрос — только по шаблону, его печатает `pantheon launch-question <id> запустить|перезапустить|вернуть <направление>`:
# «[<id>] Запустить <имя>?» и варианты «Да — запустить <имя>» | «Нет». Ваш выбор хук answer пишет в owner-log/zeus.md с
# пометкой «окно вопросов», выбор сообщением сразу после такого вопроса в чате хук owner-log пишет с пометкой «ответ в
# чате» (metis-0405; служебные строки «вариант:», «дословно:» сверка не видит) — роли их не подделать. Плановый проход
# (вне песочницы окон) сверяет запись целиком: строка
# вопроса точно по шаблону, ответ — точно вариант «Да — <глагол> <имя>», других строк (заметки, свой текст) нет.
# Любое отличие — отказ без запуска (ревью безопасности: намерение не выводится из свободного текста модели).
# запустить — продолжение остановленной сессии или новая (как самозапуск), перезапустить — pantheon start --restart.
# Метку «остановлено вами» запустить и перезапустить не снимают (отказ). Её снимает вернуть (решение владельца 28.10):
# «[<id>] Вернуть <имя>?» / «Да — вернуть <имя>» — та же дословная сверка, затем как `pantheon resume <имя>` (метка,
# имя в stopped-all.json и сброс самозапуска) и подъём окна, как у запустить. `pantheon resume` остаётся. Каждое
# поручение — строка word-launch в logs/start.log и строка в alerts.md; запись исполняется один раз
# (word-launch.json), только не старше WORD_LAUNCH_HOURS и не раньше включения прохода (word-launch-since: старые «да»
# после выпуска никого не поднимают). Окну Зевса и СБ команды запуска для этого не нужны.
WORD_LAUNCH_VERBS = ("запустить", "перезапустить", "вернуть")
WORD_LAUNCH_ID = r"[a-z0-9][a-z0-9-]{0,40}"
WORD_LAUNCH_NAME = r"[a-z][a-z0-9-]{0,40}"
# похоже на поручение запуска — тогда запись разбирается и при несовпадении с шаблоном даёт отказ в журнале
WORD_LAUNCH_HINT = re.compile(r"вопрос: \[([^\]\s]{1,40})\]\s*(?:запустить|перезапустить|поднять|вернуть)(?![а-яё])", re.I)
WORD_LAUNCH_HOURS = 12
WORD_LAUNCH_MAX = 3  # поручений за проход — не больше


def launch_question(qid, verb, name):
    """(вопрос, вариант «Да», вариант «Нет») — единственный вид, который исполняет word_launch."""
    return f"[{qid}] {verb.capitalize()} {name}?", f"Да — {verb} {name}", "Нет"


def word_parse(body):
    """Тело записи «окно вопросов» → (id, глагол, имя, ответ, исполнять ли, почему нет) или None — не поручение запуска."""
    lines = body.split("\n")
    if not lines or not WORD_LAUNCH_HINT.match(lines[0]):
        return None
    m = re.fullmatch(rf"вопрос: \[({WORD_LAUNCH_ID})\] (Запустить|Перезапустить|Вернуть) ({WORD_LAUNCH_NAME})\?", lines[0])
    qid0 = WORD_LAUNCH_HINT.match(lines[0]).group(1)
    ans = lines[1][len("ответ: "):] if len(lines) > 1 and lines[1].startswith("ответ: ") else ""
    if not m:
        return qid0.lower(), "?", "?", ans, False, "вопрос не по шаблону pantheon launch-question"
    qid, verb, name = m.group(1), m.group(2).lower(), m.group(3)
    if len(lines) != 2 or not ans:
        return qid, verb, name, ans, False, "в записи есть заметка или свой текст — исполняю только чистый выбор"
    if ans != launch_question(qid, verb, name)[1]:
        return qid, verb, name, ans, False, f"ответ «{ans[:60]}», а не «{launch_question(qid, verb, name)[1]}»"
    return qid, verb, name, ans, True, ""


def word_orders(t):
    """Записи «окно вопросов» в zeus.md, похожие на поручение запуска → [(ключ, время, id, глагол, имя, ответ, да, почему
    нет)], старые первыми."""
    p = P.path("word-launch-since")
    try:
        since = float(open(p).read().strip())
    except (OSError, ValueError):
        since = t
        P.write_atomic(p, f"{int(t)}\n")
    since = max(since, t - WORD_LAUNCH_HOURS * 3600)
    try:
        text = open(P.path("owner-log", "zeus.md"), encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    for i, m in enumerate(heads):
        if not P.answers_mod().is_answer_head(m.group(2)):
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue
        if ts < since or ts > t + 60:
            continue
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        # ответ в чате (metis-0405) — без служебных строк «вариант:», «дословно:»: та же дословная сверка
        w = word_parse(P.answers_mod().answer_body(m.group(2), body))
        if w:
            out.append((f"{m.group(1)}|{w[0]}|{w[2]}", m.group(1)) + w)
    return out


def launch_question_cmd(rest):
    """pantheon launch-question <id> запустить|перезапустить|вернуть <направление> — вопрос и варианты для окна вопросов."""
    doms = domains()
    if (len(rest) != 3 or not re.fullmatch(WORD_LAUNCH_ID, rest[0]) or rest[1] not in WORD_LAUNCH_VERBS
            or not re.fullmatch(WORD_LAUNCH_NAME, rest[2])):
        print("pantheon launch-question <id> запустить|перезапустить|вернуть <направление> — id и имя строчными",
              file=sys.stderr)
        return 2
    if rest[2] not in doms:
        print(f"pantheon launch-question: нет направления {rest[2]} в domains.json", file=sys.stderr)
        return 2
    q, yes, no = launch_question(*rest)
    print(f"вопрос: {q}\nварианты: {yes} | {no}\n(вопрос и варианты — дословно, без пояснений: иначе плановый проход откажет)")
    return 0


def word_launch(agents, registry, doms, t):
    """Поручения запуска из ваших ответов в окне вопросов — исполнить (см. блок выше)."""
    sp = P.path("word-launch.json")
    st = P.read_json(sp, {})
    st = st if isinstance(st, dict) else {}
    done = st.get("done") if isinstance(st.get("done"), dict) else {}
    orders = [o for o in word_orders(t) if o[0] not in done]
    n = 0
    for key, ts, qid, verb, name, ans, yes, why in orders:
        if not yes:
            res = f"не исполняю: {why}"
        elif name not in doms:
            res = "не исполняю: нет такого направления в domains.json"
        elif n >= WORD_LAUNCH_MAX:
            break  # остальные — следующим проходом
        else:
            n += 1
            res = _word_do(verb, name, qid, ts, ans, agents, registry)
        done[key] = {"t": t, "result": res}
        P.start_log(f"word-launch\t{name}\t{verb}\t{qid}\t{ts}\t{res}")
        P.alert(f"по вашему ответу в окне вопросов ({ts}, [{qid}]): {verb} {name} — {res}", "watch")
        cut = t - 2 * WORD_LAUNCH_HOURS * 3600
        st["done"] = {k: v for k, v in done.items() if float((v or {}).get("t") or 0) >= cut}
        P.write_json(sp, st)  # после каждого поручения: проход могут оборвать, повтора запуска быть не должно


def _word_task_exists(qid):
    """Есть ли задача с id вопроса. Журнал не читается — да (как раньше): ссылка на карточку лишней не бывает."""
    try:
        T = P.tasks_mod()
        return qid in T.load_tasks(P.PANTHEON, T.WORK_TYPES)
    except Exception:  # noqa: BLE001 — сбой чтения доски не должен ронять запуск по ответу
        return True


def word_text(qid, ts, ans):
    """Текст запуска по ответу. metis-0820: id вопроса — не всегда задача (hermes-review-1, zeus-wake-0511). Ссылка
    «pantheon task show <id>» без карточки входила в цель окна (/goal + TASK_GOAL), задачу с цели снять было нечем —
    проверка цели держала окно по кругу. Без карточки — ни ссылки, ни задачи в цели: так и сказано в тексте."""
    head = f"[Пантеон: запуск по ответу владельца в окне вопросов {ts}, [{qid}] — «{ans[:80]}»] Продолжай работу; "
    if _word_task_exists(qid):
        return head + f"поручение и контекст — pantheon task show {qid}, свои входящие и STATUS.md."
    return head + (f"поручение и контекст — свои входящие и STATUS.md. [{qid}] — номер вопроса, а не задачи: карточки "
                   f"с ним нет, в цель окна задача {qid} не входит.")


def _word_do(verb, name, qid, ts, ans, agents, registry):
    text = word_text(qid, ts, ans)
    if verb == "вернуть":  # как pantheon resume: метка, имя в «остановить всё», сброс самозапуска — затем подъём
        _word_unstop(name)
    if os.path.exists(P.path("stopped", name)):
        return ("не исполняю: «остановлено вами» — снимает ответ «Да — вернуть " + name + "» или ваша команда "
                "pantheon resume")
    # metis-0444: недельный потолок держит и запуск по ответу — сверх потолка только ваш терминал (--over-cap)
    cap = None if name in P.CAP_FREE else P.night_mod().launch_cap("tick")  # Гестию потолок не держит (29.10)
    if cap:
        return f"не исполняю: {cap}"
    if verb == "перезапустить":
        try:
            r = subprocess.run([os.path.join(P.PLUGIN, "bin", "pantheon"), "start", name, "--from", "tick", "--restart",
                                text], capture_output=True, text=True, timeout=start_timeout(), env=P.claude_env())
        except subprocess.TimeoutExpired:
            return f"pantheon start --restart не уложился в {start_timeout():.0f} с"
        tail = (r.stderr or r.stdout).strip().splitlines()
        if r.returncode == 0:
            ONESHOT_STARTED.append(name)
        return "перезапущено" if r.returncode == 0 else f"не вышло, код {r.returncode}" + (f": {tail[-1][:160]}" if tail else "")
    if name in ONESHOT_STARTED or name in awake().RESUMED:
        return "уже поднято этим проходом"
    if P.live_copies(name, agents, registry=registry):
        return "уже работает — не трогаю (перезапуск — ответ на «перезапустить»)"
    rc = resume_or_start(name, agents, text, origin="tick")
    if rc == P.SKIPPED:  # metis-0708: под блокировкой имени «не надо» (уже работает, поднимает другой) — не сбой
        return f"пропуск: {P.SKIP_WHY}"
    if rc == 0:
        awake().RESUMED.append(name)
        ONESHOT_STARTED.append(name)  # самозапуск этого прохода направление не тронет
        return "поднято"
    return f"не вышло, код {rc}"


def _word_unstop(name):
    """Снять «остановлено вами» с направления — по вашему ответу «Да — вернуть <имя>» (как pantheon resume)."""
    _forget_autostart(name)
    try:
        os.unlink(P.path("stopped", name))
        P.alert(f"{name}: метка «остановлено вами» снята (ваш ответ «Да — вернуть {name}» в окне вопросов)",
                "pantheon-stop")
    except OSError:  # метки нет; не снялась иначе — она остаётся, и ниже отказ с причиной, а не падение проверки
        pass
    sp = P.path("stopped-all.json")
    st = P.read_json(sp, None)
    if isinstance(st, dict) and name in (st.get("names") or []):
        st["names"] = [x for x in st["names"] if x != name]
        P.write_json(sp, st)


def resume_or_start(name, agents, text, origin, only_resume=False, auto=False):
    """Остановленная или упавшая сессия направления — продолжить её же (контекст эпика сохраняется, с её именем и
    окном — P.resume_session); нет такой — новая через pantheon start."""
    alias = P.name_alias(name)
    old = [a for a in agents if alias.fullmatch(str(a.get("name") or "")) and a.get("state") in ("stopped", "failed")
           and a.get("sessionId")]
    if old:
        # metis-0499: если сессия записала `pantheon saved` (id в метке), продолжаем именно её, а не самую свежую по
        # startedAt — ожившая остановленная копия с тем же именем иначе перехватила бы продолжение (как restart --go)
        a = saved_agent(name, old, saved_sid(name), warn=False)
        fresh = P.fresh_reason(a)  # metis-0147 п. 2: контекст большой, кэш остыл — новая сессия с файла состояния
        if fresh:
            return P.fresh_start(name, a, P.fresh_text("свежий старт", name, a.get("id"), text), origin,
                                 recheck=recheck(name, auto), reason=fresh)
        return P.resume_session(name, a, text, origin, recheck=recheck(name, auto))[0]
    if only_resume:
        return 1
    return start_new(name, text, origin)


def start_new(name, text, origin):
    """Новая сессия через `pantheon start <имя> --from <origin> <text>`: у координатора — с /goal по поручению
    (TASK_GOAL); закончившую ход прежнюю start останавливает сам. → код запуска."""
    if dry():
        print(f"[start] {name} --from {origin}")
        return 0
    limit = start_timeout()
    # metis-0261 А, круг 4 (ревью argus-b3 п. 2): дочерний pantheon start — без роли окна (claude_env снимает ROLE_ENV).
    # Иначе `pantheon watch`, запущенный из окна Зевса, получал бы на --from tick отказ «только zeus», код 2.
    try:
        r = subprocess.run([os.path.join(P.PLUGIN, "bin", "pantheon"), "start", name, "--from", origin, text],
                           capture_output=True, text=True, timeout=limit, env=P.claude_env())
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
        refused = []
        for n in names:
            if not os.path.exists(P.path("stopped", n)):
                marked.append(n)
            cnt, lft = _stop_one(n, agents, who)
            if cnt is None:
                refused.append(n)
            left_all += [(n, i, r) for i, r in lft]
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
        for n in refused:
            P.alert(_stop_refused_text(n), "pantheon-stop")
            print(f"pantheon stop: {_stop_refused_text(n)}", file=P.sys.stderr)
        return 1 if refused else 0
    if not rest or not P.SESSION_NAME.fullmatch(rest[0]):
        print("pantheon stop <направление|daedalus-задача> | --all", file=P.sys.stderr)
        return 2
    name = rest[0]
    if (not is_pantheon(name, doms) and name != "hestia") or name.startswith("zeus"):  # hestia — служебная (metis-0575)
        print(f"pantheon stop: {name} — не сессия направления или мастерской", file=P.sys.stderr)
        return 2
    n, left = _stop_one(name, agents, who)
    if n is None:
        P.alert(_stop_refused_text(name), "pantheon-stop")
        print(f"pantheon stop: {_stop_refused_text(name)}", file=P.sys.stderr)
        return 1
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
    """Та же блокировка имени, что у pantheon start и подъёма сессии: подъём, начатый до метки, не проскочит после неё.
    Замок не взят (занят дольше P.HQ_LOCK_WAIT или подложенная запись в hq-rw) — вслепую не останавливаем: ставим только
    метку «остановлено вами» (новые запуски не пойдут) и отдаём (None, []) — вызывающий выходит с кодом 1."""
    with P.lock("start-" + name) as got:
        if not got:
            os.makedirs(P.path("stopped"), exist_ok=True)
            P.write_atomic(P.path("stopped", name), f"{P.stamp()} {who}\n")
            return None, []
        return _stop_locked(name, agents, who)


def _stop_refused_text(name):
    return (f"{name} не остановлена: блокировка имени start-{name} занята (идёт запуск?) или не взята — сессии не тронуты, "
            f"метка «остановлено вами» стоит, новых запусков не будет; повторите pantheon stop {name}")


def _stop_locked(name, agents, who):
    os.makedirs(P.path("stopped"), exist_ok=True)
    P.write_atomic(P.path("stopped", name), f"{P.stamp()} {who}\n")
    n = 0
    left = []
    seen = set()
    # metis-0685: призрак (reconcile_agents: ghost=True, процесса нет) тоже убираем — иначе stop отвечает «0» и запись висит
    for a in P.live_copies(name, agents, registry=[]) + [a for a in agents if a.get("name") == name
                                                          and a.get("state") == "done" and a.get("pid")] \
            + [a for a in agents if a.get("name") == name and a.get("ghost")]:
        if a.get("id") and a["id"] not in seen:
            seen.add(a["id"])
            reason = P.stop_and_rm(name, a["id"], "stop")  # metis-0239: без rm Claude Code сам перезапускает фоновую сессию
            P.start_log(f"stop\t{name}\t{a.get('name')}\t{a['id']}\t{who}")
            if reason:
                P.start_log(f"rm-refused\t{name}\t{a['id']}\t{reason}")
                left.append((a["id"], reason))
            n += 1
    return n, left


def _left_text(name, left):
    return "".join(f"\n{name}: осталась среди фоновых сессий Claude Code: {i}, причина: {r}" for i, r in left)


def _forget_autostart(name):
    """Метка сброса счётчика самозапуска — в STATE/hq-rw/autostart-reset (туда пишет и окно Зевса): P.hq_mark не идёт по
    подложенной ссылке и не пишет в жёсткую ссылку (metis-0523, ревью безопасности)."""
    P.hq_mark("autostart-reset", name, P.stamp() + "\n")


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
#    сессию выбирает id, записанный `pantheon saved` (metis-0421), а не самый свежий startedAt; нет id — прежний выбор;
#    повтор --go не трогает уже перезапущенные; продолжение остановленной сессии (resume_or_start) тоже берёт ту, что
#    записала `pantheon saved`, если её id в метке (metis-0499). Зевс — интерактивная сессия владельца: его перезапуск —
#    `pantheon start zeus --restart` во вкладке iTerm; в песочнице окна штаба `pantheon saved` метку не пишет (STATE
#    закрыт), но для zeus* это не отказ — метка ему справочная (metis-0577). 4) Завершённый перезапуск закрывают
#    `pantheon restart --done` или `--status` (все перезапущены, Зевс поднят заново: id его сессии не тот, что в saved) —
#    тревога «технический перезапуск завершён»; иначе метка висит до срока и снимается тревогой «не завершён» (metis-0338).
#    Метка истекла — дежурный снимает её с тревогой.

def maint_path():
    return P.path("maintenance.json")


def hq_saved_clear():
    """Метки окна штаба в STATE/hq-rw/saved снимаем вместе с остальными метками saved (metis-0577)."""
    with contextlib.suppress(OSError):
        for f in os.listdir(P.path(P.HQ_RW, "saved")):
            with contextlib.suppress(OSError):
                os.remove(P.path(P.HQ_RW, "saved", f))


def maint_clear():
    hq_saved_clear()
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
# или RESPAWN_IDLE_MIN минут без записи транскрипта, журналов субагентов и worktree окна; живой субагент по meta.json
# (watch.live_subagents, metis-0864) держит окно и при метке «можно». Занятое ждёт следующего прохода, выпуски за это
# время копятся в одной отметке respawn.json — окно перезапускается один раз.

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
    subs = live_subagents(a, t)  # metis-0864: тихий субагент (ждёт тесты) не пишет журнал — простой его не видит
    if subs:
        return "живые субагенты: " + ", ".join(subs[:5])
    ok = P.read_json(respawn_path("respawn-ok", str(a.get("name")) + ".json"), {})
    # metis-0499: метка с id сессии — «можно» только ей; другая живая копия с тем же именем ждёт простоя
    if isinstance(ok, dict) and float(ok.get("t") or 0) > since and ok.get("sessionId") in (None, a.get("sessionId")):
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
            hq_saved_clear()


def saved_agent(name, mine, sid, warn=True):
    """metis-0421: сессия для restart --go — та, что записала `pantheon saved` (по id), а не самая свежая по startedAt: ожившая
    остановленная копия с тем же именем иначе перехватила бы перезапуск. Записи или id нет в списке — прежний выбор
    (самая свежая) и предупреждение в stderr (warn; продолжение остановленной сессии, metis-0499, молчит: метки saved
    у неё обычно нет)."""
    if sid:
        for a in mine:
            if a.get("sessionId") == sid:
                return a
        why = f"сохранённой сессии {sid[:8]} нет среди сессий с этим именем"
    else:
        why = "в записи saved нет id сессии"
    if warn:
        print(f"pantheon restart: {name}: {why} — беру самую свежую по startedAt", file=P.sys.stderr)
    return max(mine, key=lambda a: a.get("startedAt") or 0)


def saved_sid(name):
    """metis-0499: id сессии из последней метки `pantheon saved` этого имени — техперезапуск (STATE/maintenance/<имя>.json)
    или перезапуск после плагинов (STATE/plugins/respawn-ok/<имя>.json); None — метки или id в ней нет."""
    if not P.SESSION_NAME.fullmatch(str(name)):
        return None
    for rec in (P.read_json(P.path("maintenance", name + ".json"), {}),
                P.read_json(respawn_path("respawn-ok", name + ".json"), {}), hq_saved(name)):
        sid = rec.get("sessionId") if isinstance(rec, dict) else None
        if isinstance(sid, str) and re.fullmatch(r"[0-9a-f-]{8,64}", sid):
            return sid
    return None


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
    for n in m.get("sessions") or []:  # окно штаба пишет метку в STATE/hq-rw/saved (metis-0577)
        if n not in saved and hq_saved(n).get("time"):
            saved[n] = hq_saved(n)
    if rest[:1] == ["--done"]:  # metis-0338: перезапуск закончен — метку снять (рядом с --cancel: тот отменяет)
        return restart_close(m, done_marks, who, "по команде --done")
    if rest[:1] == ["--status"] or not rest:
        print(f"перезапуск с {m['id'][:16]} ({m.get('reason')}), метка до {P.stamp(float(m.get('expires') or 0))[11:16]}:")
        for n in m.get("sessions") or []:
            s = saved.get(n)
            print(f"  {n}: " + ("перезапущена" if n in done_marks else
                                f"сохранилась {s.get('time', '')[11:16]}, состояние — {s.get('state') or '—'}" if s
                                else "ещё нет"))
        waiting = [n for n in m.get("sessions") or [] if not n.startswith("zeus") and n not in done_marks]
        owner = [n for n in m.get("sessions") or [] if n.startswith("zeus")]
        if not waiting and (not owner or zeus_renewed(owner, saved)):
            # metis-0338: все перезапущены, а Зевс (если был) поднят заново — метка больше не нужна
            return restart_close(m, done_marks, who, "всё перезапущено" + (", Зевс поднят заново" if owner else ""))
        if not waiting:
            print("осталось: Зевс — pantheon start zeus --restart во вкладке iTerm; потом pantheon restart --status "
                  "(или --done) снимет метку")
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
            rc = P.resume_session(n, saved_agent(n, mine, (saved.get(n) or {}).get("sessionId")), RESTART_TEXT, "restart",
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
        P.alert(f"технический перезапуск {'завершён' if not skip else ''} ({who}): перезапущены {', '.join(done) or 'никто'}"
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
    print("pantheon restart --prepare [причина] | --status | --go [--force] | --done | --cancel", file=P.sys.stderr)
    return 2


def zeus_renewed(names, saved):
    """metis-0338: Зевс (zeus*) поднят заново после `pantheon saved`. Признак — у каждого есть живая сессия с этим именем
    (claude agents или реестр имён вкладок), и среди живых нет той, что записала saved (sessionId метки): после
    `pantheon start zeus --restart` id другой. Метки с id нет — не знаем, False (тогда метку снимет --done)."""
    agents, reg = P.agents_all() or [], P.sessions_registry()
    for n in names:
        sid = (saved.get(n) or {}).get("sessionId")
        live = holders(n, agents, reg)
        if not sid or not live or any(a.get("sessionId") == sid for a in live):
            return False
    return True


def restart_close(m, done_marks, who, how):
    """metis-0338: закрыть завершённый технический перезапуск — метка и отметки сняты, в тревогах «завершён» (а не
    «метка снята по сроку без restart --go» через два часа)."""
    left = [n for n in m.get("sessions") or [] if not n.startswith("zeus") and n not in done_marks]
    maint_clear()
    P.alert(f"технический перезапуск завершён ({who}, {how}): перезапущены "
            f"{', '.join(n for n in m.get('sessions') or [] if n in done_marks) or 'никто'}"
            + (f"; без перезапуска остались: {', '.join(left)} — поднять вручную: pantheon wake <имя>" if left else ""),
            "pantheon-restart")
    print("перезапуск завершён, метка снята" + (f"; без перезапуска: {', '.join(left)}" if left else ""))
    return 0


SAVED_NAME = re.compile(r"zeus[a-z0-9-]{0,36}")


def hq_saved(name):
    """metis-0577: метка `pantheon saved` окна штаба из STATE/hq-rw/saved (пишет само окно — только Зевс); {} — нет.
    Папку пишет окно, а читает проход вне песочницы: ссылка, FIFO, чужой или большой файл — не читаем (O_NOFOLLOW|O_NONBLOCK,
    обычный файл, одна ссылка, наш владелец, читаем не больше 64 КБ — длиннее не разбирается как JSON); поля проверяем по типу, а не доверяем."""
    if not SAVED_NAME.fullmatch(str(name)):
        return {}
    try:
        fd = os.open(P.path(P.HQ_RW, "saved", name + ".json"), os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return {}
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid():
            return {}
        raw = os.read(fd, 65537)
        rec = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return {}
    finally:
        os.close(fd)
    if not isinstance(rec, dict):
        return {}
    out = {}
    for k in ("time", "state", "by"):
        if isinstance(rec.get(k), str):
            out[k] = rec[k][:300]
    if isinstance(rec.get("sessionId"), str) and re.fullmatch(r"[0-9a-f-]{8,64}", rec["sessionId"]):
        out["sessionId"] = rec["sessionId"]
    return out


def _write_mark(name, p, rec):
    """Запись pantheon saved. Не записалась (PermissionError: песочница окна не пускает в STATE/maintenance и
    STATE/plugins, metis-0577) — строка в stderr и False, без трассировки. Зевс (zeus*) — интерактивная сессия владельца:
    его не перезапускает ни restart --go, ни тик, hook его не закрывает, так что метка для него справочная и её
    отсутствие работе не мешает; остальным нужна: без метки restart --go их не тронет."""
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        P.write_json(p, rec)
        return True
    except OSError as e:
        owner = name.startswith("zeus")
        kept = None
        if owner and SAVED_NAME.fullmatch(name):  # metis-0577: окно штаба пишет только в STATE/hq-rw — метка там
            try:
                P.hq_put("saved", name + ".json", json.dumps(rec, ensure_ascii=False) + "\n")
                kept = P.tilde(P.path(P.HQ_RW, "saved", name + ".json"))
            except OSError:
                pass
        print(f"pantheon saved: метка {P.tilde(p)} не записана — {type(e).__name__}: {e.strerror or e}"
              + (f"\n{name}: его перезапуск ведёт владелец (pantheon start zeus --restart), метка ему не нужна — "
                 "команда считается выполненной" + (f"; копия записана в {kept}" if kept else "") if owner else
                 "\nокно не может писать в состояние Пантеона: метку поставит тот, кто вне песочницы"),
              file=P.sys.stderr)
        return False


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
        rec = {"t": P.now(), "time": P.stamp(), "state": " ".join(state.split())[:300], "by": who}
        sid = P.os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
        if own and re.fullmatch(r"[0-9a-f-]{8,64}", sid):  # metis-0499: перезапуск после плагинов продолжит эту сессию
            rec["sessionId"] = sid
        if not _write_mark(name, respawn_path("respawn-ok", name + ".json"), rec):
            return 0 if name.startswith("zeus") else 1
        print(f"{name}: отмечено «можно перезапускать». Плановый проход перезапустит окно с новыми плагинами, когда оно закончит ход; "
              "работающее окно не тронет")
        return 0
    if name not in (m.get("sessions") or []):
        print(f"pantheon saved: {name or '(без имени)'} нет в списке перезапуска: {', '.join(m.get('sessions') or [])}",
              file=P.sys.stderr)
        return 2
    rec = {"time": P.stamp(), "state": " ".join(state.split())[:300], "by": who}
    sid = P.os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    if own and re.fullmatch(r"[0-9a-f-]{8,64}", sid):  # metis-0421: restart --go продолжит именно эту сессию
        rec["sessionId"] = sid
    if not _write_mark(name, P.path("maintenance", name + ".json"), rec):
        return 0 if name.startswith("zeus") else 1
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


def wake_one(rest, who="владелец", over=False):
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
    # metis-0261 А, круг 4 (ревью argus-b3 п. 1): задание из окна роли — запуск от её имени, как start --from zeus: только
    # по вашему слову (owner_word_ok, как у resume). Без него — отказ, код 2, respawn не зовётся. Замер — строка в
    # capacity.jsonl у каждого подъёма и у отказа (как _wake); красная зона подъём со словом не откладывает (как _wake).
    word = not (extra and os.environ.get("PANTHEON_ROLE")) or owner_word_ok()
    # metis-0444: недельный потолок владельца — отказ, код 2 (--over-cap снимает его только в вашем терминале)
    role = os.environ.get("PANTHEON_ROLE") or ""
    cap = P.night_mod().launch_cap("zeus" if role == "hq" else "tick" if role else "owner", over) if word else None
    P.capacity_note(name, "wake", agents, "allowed" if word and not cap else "refused")
    if cap:
        print(f"pantheon wake {name}: отказ — {cap}; claude не запускался", file=P.sys.stderr)
        return P.START_REFUSED
    if not word:
        print(f"pantheon wake {name}: задание из окна роли — только по слову владельца: в журнале Зевса нет его строки "
              f"за {P.OWNER_WORD_WINDOW // 60} мин (сообщение другой сессии согласием не считается); без задания "
              f"`pantheon wake {name}` будит с «продолжай»; claude не запускался", file=P.sys.stderr)
        P.alert(f"pantheon wake {name} с заданием от {who} отклонён: нет свежего слова владельца", "pantheon-wake")
        return P.START_REFUSED
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
CORPUS_MISSING = "в policy.toml нет раздела [corpus] или он пуст: правило corpus-role ничего не закрывает"
# списки раздела [corpus] (guard CORPUS_KEYS): все пустые — правило молчит, как без раздела (metis-0194)
CORPUS_LISTS = ("commands", "modules", "write_subcommands", "scripts", "keychain_prefixes")
HOOK_LAUNCHER = None  # запускатель хуков hooks/python.sh (metis-0571); тесты подменяют
HOOKS_NO_TOMLLIB = ("запускатель хуков hooks/python.sh не нашёл Python 3.11+: guard останавливает каждое действие, "
                    "остальные хуки молчат — Метиде: brew install python@3.14")


def _hook_launcher(script=None):
    """hooks/python.sh рядом со скриптом хука (guard), иначе — свой, pantheon (копии одинаковые, metis-0571)."""
    if HOOK_LAUNCHER:
        return HOOK_LAUNCHER
    if script:
        near = os.path.join(os.path.dirname(script), "python.sh")
        if os.path.isfile(near):
            return near
    return os.path.join(P.PLUGIN, "hooks", "python.sh")


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
        argv = ["/bin/sh", _hook_launcher(g), g] + (["--managed"] if _managed_guard_active() else [])
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
    # с проверенным деревом guard (merge.managed_source), как у прохода, а не с клоном маркетплейса (metis-0718); дерева
    # или поставленного файла нет — строки нет, как раньше
    with contextlib.suppress(OSError):
        cur = open(P.MANAGED, "rb").read()
        src = P.merge_mod().managed_source()
        if src is not None:
            add(cur == src[1], "управляемые настройки совпадают с guard")
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
            sec = tomllib.load(fh).get("corpus")
        # битый раздел (не таблица) guard читает как «закрыто» — это не молчание; пустой [corpus] — как его нет
        corpus = sec is not None and (not isinstance(sec, dict) or any(sec.get(k) for k in CORPUS_LISTS))
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
        add(corpus, "в policy.toml есть непустой раздел [corpus] (что закрывает правило corpus-role)")
        if corpus:
            P.clear_once("corpus-policy-missing")
        else:
            P.alert_once("corpus-policy-missing", "1", CORPUS_MISSING + " — Метиде: добавить раздел, образец — "
                         "policy.example.toml плагина guard", "watch")
    # хуки зовут Python через hooks/python.sh (metis-0571): без 3.11+ guard отказывает на каждом действии. Вне хука
    # запускатель без Python молчит с кодом 0, поэтому успех — только напечатанное «ok»
    try:
        r = subprocess.run(["/bin/sh", _hook_launcher(g), "-c", "import tomllib; print('ok')"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0 and r.stdout.strip() == "ok"
    except (OSError, subprocess.SubprocessError):
        ok = False
    add(ok, "запускатель хуков находит Python 3.11+ (tomllib)")
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
