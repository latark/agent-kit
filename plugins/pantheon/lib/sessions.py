"""Пантеон: запуск и подъём сессий — pantheon start (направление, мастерская, zeus, --at), pantheon wake (прерванные,
hestia, лид направления без координатора), свежий старт вместо продолжения (metis-0147), потолок владельца и замер
ёмкости (capacity.jsonl). Окна запуска (run_settings, _resume_session) остаются в pantheon.py: они в сборке окон
(ядро guard, metis-0404).

Вынесено из pantheon.py (metis-0586) без изменения поведения. P — модуль pantheon: его ставит загрузчик
pantheon._attach до выполнения этого файла, имена из __all__ становятся именами pantheon.
"""
import contextlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from datetime import datetime

__all__ = [
    "FRESH_CTX", "FRESH_IDLE_MIN", "WAKE_TEXT", "NEW_ORDER_GOAL", "WAITING_GOAL", "COORDINATOR_GOAL", "TASK_GOAL", "OPEN_STATUSES",
    "load_pause",
    "PUSH_MAX_AGE", "resume_session", "transcript_path", "session_context", "fresh_reason", "latest_zeus_handoff",
    "state_files", "fresh_text", "fresh_target", "fresh_start", "_fresh_start", "copies_message", "name_holders",
    "_holder_text", "wait_name_free", "check_new_name", "start_at", "start", "_start_session", "OWNER_WORD_WINDOW",
    "OWNER_HEAD", "owner_word_heads", "owner_spoke_recently", "owner_spoke_before", "CAPACITY_SESSIONS_DONE",
    "capacity_probe", "capacity_log", "NO_WORD_WHY", "START_REQ", "START_REQ_KEYS", "start_request", "take_start_requests",
    "START_REFUSED", "START_DEFERRED", "OVER_CAP", "CAP_FREE", "start_gate", "open_tasks", "wake_recheck",
    "wake_hestia", "wake_lead", "wake", "capacity_note", "_wake",
]


# Подъём свежей сессией вместо продолжения (metis-0147 п. 2, «да» владельца 16.10): контекст больше FRESH_CTX и простой
# с последнего хода дольше FRESH_IDLE_MIN — кэш подсказок давно остыл, и respawn/--resume перечитал бы весь контекст по
# полной цене. Тогда — новая сессия с тем же именем и окном, которая читает файл состояния (fresh_start).
FRESH_CTX = 100_000
FRESH_IDLE_MIN = 60


WAKE_TEXT = (P.START_MARK + " пробуждение] Тебя прервало выключение или перезапуск. Сверь файл состояния и «начато» без "
             "«сделано» (не повторяй внешнее действие, пока не проверишь, что оно не ушло), затем продолжай задачу.")
# metis-0276: новое поручение посреди сессии входит в цель. Сменить /goal живой фоновой сессии извне нечем (push отдаёт
# текст хуком, а не командой; сообщение SendMessage — тоже текст), а проверяющая модель цели видит всю переписку. Поэтому
# условие само говорит, что поручение Зевса или владельца, пришедшее позже, — часть цели, а «готово» с «перехожу к …»
# цель не закрывает (19.10: план дня пришёл сообщением, отчёт «готово, перехожу к плану» отпустил сессию, работа встала)
NEW_ORDER_GOAL = (" Поручение Зевса или владельца, пришедшее в сессию после её начала (сообщение или задание "
                  "«[Пантеон: …]»), входит в цель: пока оно не сделано и не названо заблокированным, цель не достигнута. "
                  "Отчёт «готово», который объявляет следующий шаг («перехожу к …»), а не делает его, цель не достигает.")
# metis-0714: задачу цели, которая ждёт владельца с вопросом или другую задачу, цель не держит. Иначе проверяющая
# модель Stop-хука /goal видит её в поручении («Все: X, Y») и возвращает сессию брать её снова (02.11: окно Метиды
# тянуло metis-0233, waiting до решения по плану 1.0). «Ждёт» с блокером, который сессия назвала сама, задачу не
# отпускает (argus-280b, вариант А): решает строка `pantheon task set` (GOAL_OUT/GOAL_IN в lib/tasks.py), а не слово сессии.
# «Снята» устаревает: блокер закрыт — `task set` блокера печатает GOAL_IN про ждущих; плановый проход сам возвращает
# задачу в doing и в транскрипт не пишет (argus-280a, Д1) — поэтому верна только на момент записи.
# metis-0738: GOAL_IN от `task set` блокера попадает в транскрипт той сессии, что его закрыла (другая сессия, плановый
# проход при слиянии PR, владелец на доске), а не ждущей. Поэтому «снята» засчитывается только свежей — в ходе
# последнего отчёта; проверка по хранилищу на эту минуту — `pantheon task goal <id>` (goal_state в lib/tasks.py).
# metis-0725: задачу, которую ведёт другая сессия (owner — не окно и не его команда, как у самозапуска, metis-0564),
# цель не держит, даже если она в поручении или в чек-листе эпика: 03.11 окно Метиды тянуло metis-0272 (owner
# agent-kit-47). Строку «снята — ведёт <owner>» печатают `task goal` и `task set owner=…` из окна (PANTHEON_SESSION).
WAITING_GOAL = (" Задача уходит из цели, только если `pantheon task set` или `pantheon task goal <id>` ответил строкой "
                "«<id>: снята с цели окна» — так бывает, когда задача ждёт ответа владельца на вопрос или другую задачу, "
                "закрыта или её ведёт другая сессия (owner — не это окно и не его команда), даже если она в поручении, "
                "в чек-листе эпика, в работе или в очереди. Строка «остаётся в цели окна» или её нет — задача в цели, "
                "как в работе (doing). Верь последней такой строке по этой задаче: «остаётся» после «снята» возвращает "
                "её в цель. «Снята» засчитывается, только если напечатана в том же ходе, что и последний отчёт сессии "
                "(после последнего сообщения, пришедшего в сессию): блокер мог закрыть, а owner сменить кто-то другой — "
                "более ранняя «снята» устарела, задача в цели, пока свежая `pantheon task goal <id>` снова не скажет "
                "«снята». Задачи в работе (doing) и в очереди (todo) — в цели.")
COORDINATOR_GOAL = ("Цель достигнута, когда последний отчёт сессии — по формату отчёта роли, и либо «Статус: готово» и все "
                    "пункты чек-листа эпика в STATUS.md отмечены сделанными, либо «Статус: заблокировано» с названным "
                    "блокером и вопросом владельцу или Зевсу." + WAITING_GOAL + NEW_ORDER_GOAL)
# поручение названо явно (одна задача, проверка) — цель по нему, а не по эпику: иначе Stop-хук не отпустит сессию, пока
# не закрыт весь чек-лист, и короткая проверка разрастается в эпик (живой запуск athena-0001 15.10)
TASK_GOAL = ("Цель достигнута, когда последний отчёт сессии — по формату отчёта роли, и либо «Статус: готово» и выполнен "
             "критерий «готово» этого поручения, либо «Статус: заблокировано» с названным блокером и вопросом владельцу "
             "или Зевсу. Другие задачи и пункты эпика в эту цель не входят — кроме нового поручения." + WAITING_GOAL
             + NEW_ORDER_GOAL)


OPEN_STATUSES = {"todo", "doing", "review"}  # «ждёт» не будят: ответа ещё нет


def load_pause(name):
    """Пауза по нагрузке (COST-04) этого направления или общая (_all): запись или None."""
    for n in (name, "_all"):
        p = P.read_json(P.path("pauses", n + ".json"), None)
        if isinstance(p, dict) and p:
            return p
    return None


PUSH_MAX_AGE = 30 * 60


def resume_session(name, a, text, origin, recheck=None):
    """Продолжить сессию направления или мастерской той же сессией (контекст эпика сохраняется). Есть в claude agents
    (остановлена, упала, закончила ход) — `claude respawn <id>`: тот же id, имя и флаги запуска, в том числе окно
    --settings, новые плагины и Claude Code; текст ей отдаёт хук push при старте процесса. Нет её там (удалена из
    списка) — `claude --resume <сессия> --bg --name <имя> --settings <окно>`: без --name имя теряется, без --settings —
    окно с песочницей. `--resume` на сессии, которую Claude Code ещё считает живой, делает копию («started a copy as
    <id>», 15.10 так было и после claude stop) — это строка в тревогах. → (код, id копии или None)."""
    # та же блокировка имени, что у pantheon start и pantheon stop: Зевс, тик и вы не поднимут две копии и не
    # разбудят сессию, которую в эту минуту останавливают; под ней — повторная проверка «можно ли будить» (ревью argus)
    with P.lock("start-" + name, block=False) as got_lock:
        if not got_lock:
            P.start_log(f"resume-busy\t{name}\t{a.get('id')}\t{origin}")
            return P.skipped("другой процесс уже поднимает"), None
        why = recheck() if recheck else None
        if why:
            P.start_log(f"resume-skip\t{name}\t{a.get('id')}\t{origin}\t{why}")
            return P.skipped(why), None
        # metis-0207: правило свежего старта (metis-0147 п. 2) действует на любом пути возобновления, а не только в
        # resume_or_start и pantheon wake: ждущая сессия, после недельного лимита, техперезапуск, снятие паузы
        fresh = P.fresh_reason(a)
        if fresh:
            return _fresh_start(name, a, fresh_text("свежий старт", name, a.get("id"), text), origin, fresh), None
        return P._resume_session(name, a, text, origin)


def transcript_path(a):
    """Транскрипт сессии из claude agents: ~/.claude/projects/<папка, где не буквы и цифры — «-»>/<sessionId>.jsonl;
    не нашёлся там (папку переименовали) — тот же файл в любой папке проектов. → путь или None."""
    sid = str(a.get("sessionId") or "")
    if not re.fullmatch(r"[0-9a-f-]{8,64}", sid):
        return None
    root = os.path.join(P.HOME, ".claude", "projects")
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
        return P.ctx_mod().context_tokens(p), os.path.getmtime(p)
    return None, None


def fresh_reason(a, t=None):
    """Поднимать ли сессию свежей, а не продолжением: контекст > FRESH_CTX и простой > FRESH_IDLE_MIN. → текст или None."""
    n, last = session_context(a)
    if not n or last is None:
        return None
    idle = (P.now() if t is None else t) - last
    if n > FRESH_CTX and idle > FRESH_IDLE_MIN * 60:
        return f"контекст {n // 1000} тыс., простой {int(idle // 60)} мин"
    return None


def latest_zeus_handoff():
    """Последний по времени ~/ai/pantheon/handoff/zeus-*/HANDOFF.md или None."""
    best = None
    with contextlib.suppress(OSError):
        for d in os.listdir(os.path.join(P.PANTHEON, "handoff")):
            p = os.path.join(P.PANTHEON, "handoff", d, "HANDOFF.md")
            if d.startswith("zeus-") and os.path.isfile(p) and (best is None or os.path.getmtime(p) > os.path.getmtime(best)):
                best = p
    return best


def state_files(name):
    """Файлы состояния, с которых свежая сессия продолжает: направление — STATUS.md, мастерская — файл задачи,
    Зевс — доска и последний handoff/zeus-*/HANDOFF.md."""
    if name == "zeus":
        return [os.path.join(P.PANTHEON, "board.md")] + [p for p in [latest_zeus_handoff()] if p]
    if name.startswith("daedalus-"):
        return [os.path.join(P.PANTHEON, "workshop", name[len("daedalus-"):] + ".md")]
    return [os.path.join(P.PANTHEON, "directions", name, "STATUS.md")]


def fresh_text(kind, name, old_id, tail=""):
    """«[Пантеон: <kind>] … прочитай <файл состояния>, продолжай» — текст свежей сессии; tail — поручение вызывающего,
    дословно со своей пометкой: задание «[Пантеон: задание от …]» должен остаться подписанным (ревью argus)."""
    files = " и ".join(P.tilde(p) for p in P.state_files(name))
    tail = str(tail or "").strip()
    return (f"{P.START_MARK} {kind}] Ты — новая сессия {name} с чистым контекстом: прошлая ({old_id or '?'}) остановлена, "
            f"её разговор сохранён (claude attach {old_id or '<id>'}). Прочитай {files}, продолжай со следующего шага. "
            "Сверь «начато» без «сделано»: внешнее действие не повторяй, пока не проверишь, что оно не ушло. "
            + (tail + " " if tail else "") + "Это не слова владельца и не согласие.")


def fresh_target(name, origin):
    """→ (роль, папка запуска, окно --settings) или текст ошибки, в том числе «нет окна»."""
    if name == "zeus":
        win = P.path("settings", "hq.json")  # то же окно, что у pantheon start zeus
        return ("hq", P.PANTHEON, win) if os.path.isfile(win) else "нет окна Пританея — pantheon domains build"
    target, rest = (("workshop", [name[len("daedalus-"):]]) if name.startswith("daedalus-") else (name, []))
    got = P.start_target(target, rest)
    if isinstance(got, str):
        return got
    _, role, folder, window, _ = got
    P.allow_gate(name)  # allow со старым mtime сборка не заметила — окно снимается здесь (ревью argus PR #32)
    run = P.run_settings(name, role, window, origin)
    return (role, folder, run) if run else P.no_window_reason(window)


def fresh_start(name, a, text, origin, recheck=None, reason=None, goal=None):
    """Поднять имя свежей сессией (новый контекст, то же имя, окно роли) с текстом text. a — прежняя сессия из claude
    agents (её id — в журнале и тексте); reason — почему свежей, в строку fresh-start журнала start.log; goal —
    условие цели координатора (по умолчанию COORDINATOR_GOAL, цель эпика; смена цели самозапуска — TASK_GOAL). Та же
    блокировка имени и повторная проверка, что у resume_session. → код."""
    with P.lock("start-" + name, block=False) as got_lock:
        if not got_lock:
            P.start_log(f"fresh-busy\t{name}\t{a.get('id')}\t{origin}")
            return P.skipped("другой процесс уже поднимает")
        why = recheck() if recheck else None
        if why:
            P.start_log(f"fresh-skip\t{name}\t{a.get('id')}\t{origin}\t{why}")
            return P.skipped(why)
        return _fresh_start(name, a, text, origin, reason, goal)


def _fresh_start(name, a, text, origin, reason=None, goal=None):
    if os.environ.get("PANTHEON_DRYRUN") == "1":
        print(f"[fresh] {name} {a.get('id')} {origin}")
        return 0
    got = fresh_target(name, origin)
    if isinstance(got, str):  # старую копию не останавливаем: новую без окна всё равно не поднять
        return P.window_missing(name, origin, got, "fresh")
    P.clear_once("no-window-" + name)
    role, folder, win = got
    if not str(text).startswith(P.START_MARK):
        text = f"{P.START_MARK} поручение от {origin}] {text}"
    if role == "domain-coordinator":
        text = "/goal " + text + " " + (goal or COORDINATOR_GOAL)  # как у pantheon start: Stop-хук с целью (DONE-02)
    agents = P.agents_all() or []
    live = P.live_copies(name, agents)
    if any(not x.get("id") for x in live):
        why = copies_message(name, live)
        P.start_log(f"fresh-tab\t{name}\t{origin}")
        P.alert(f"{name}: свежий старт не сделан — {why}", "pantheon")
        return 1
    stopped = list(live)
    P.stop_copies(name, live, "stop-fresh")
    for x in agents:  # закончившая ход с живым процессом держит имя (CTX-10)
        if x.get("name") == name and x.get("state") == "done" and x.get("pid") and x.get("id") \
                and x["id"] not in {s.get("id") for s in stopped}:
            P.stop_copies(name, [x], "stop-fresh-done")
            stopped.append(x)
    why = wait_name_free(name, stopped) if stopped else None
    if why:
        P.start_log(f"fresh-skip\t{name}\t{a.get('id')}\t{origin}\tимя не освободилось после claude stop")
        P.alert(f"{name}: свежий старт не сделан — {why}", "pantheon")
        return 1
    before = {x.get("id") for x in P.agents_all() or [] if x.get("id")}
    argv = [P.claude_bin(), "--bg", "--agent", role, "--name", name, "--settings", win, text]
    r = subprocess.run(argv, cwd=folder, env=P.claude_env(), capture_output=True, text=True, timeout=180)
    P.start_log(f"fresh-start\t{name}\t{a.get('id')}\t{origin}\t{r.returncode}" + (f"\t{reason}" if reason else ""))
    if r.returncode != 0:
        return r.returncode
    wrong = check_new_name(name, before)
    if wrong:
        P.alert(wrong, "pantheon")
        return 1
    P.rm_previous(name, "свежий старт", before=before)
    return 0


def copies_message(name, live, again=None):
    """again — готовая команда «начать заново» (у wake hestia сообщение сессии не доходит: blocked без сокета)."""
    tab = [a for a in live if not a.get("id")]
    if tab:
        return (f"{name} открыта во вкладке терминала (pid {tab[0].get('pid')}) — перейдите в неё или закройте её и "
                "запустите снова")
    ids = ", ".join(f"{a.get('name')} {a['id']} ({a.get('state')})" for a in live)
    if again:
        return f"{name} уже работает: {ids}. Убрать её и поднять новую — {again}; или claude attach {live[0]['id']}"
    return (f"{name} уже работает: {ids}. Поручение — сообщением ей (SendMessage, адрес {name}) или claude attach "
            f"{live[0]['id']}; начать заново — тот же запуск с --restart")


def name_holders(name, agents, registry):
    """Кто держит имя: живые копии (live_copies) и любой живой процесс реестра ~/.claude/sessions с этим именем или
    его копией — фоновый тоже. Реестр — источник правды об именах Claude Code (15.10): после claude stop claude
    agents уже пишет stopped, а процесс ещё выходит и имя держит; новый запуск в эту секунду получит «имя-два-слова»."""
    out = P.live_copies(name, agents, registry)
    seen = {a.get("sessionId") for a in out if a.get("sessionId")}
    alias = P.name_alias(name)
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
    wait, poll, settle = P.stop_wait_knobs()
    ids = {a["id"] for a in stopped if a.get("id")}
    down, restopped, started, free_since = set(), set(), time.monotonic(), None
    while True:
        agents = P.agents_all()
        registry = P.sessions_registry()
        live = P.live_copies(name, agents, registry)
        if agents is not None:
            listed = {a.get("id"): a for a in agents}
            down |= {i for i in ids if i not in listed or listed[i].get("state") in P.DOWN_STATES}
        revived = [a for a in live if a.get("id") in down]
        again = [a for a in revived if a["id"] in restopped]
        if again:
            P.start_log(f"stop-revived-again\t{name}\t{again[0]['id']}\t{again[0].get('state')}")
            return (f"{name}: копия {again[0]['id']} ожила и после повторного claude stop (сейчас "
                    f"{again[0].get('state')}) — новую не запускаю, иначе будет две. Закройте открытые окна просмотра "
                    f"claude agents, остановите её (claude stop {again[0]['id']}) и повторите запуск с --restart")
        if revived:
            P.stop_copies(name, revived, "stop-revived")
            restopped |= {a["id"] for a in revived}
            down -= restopped
        foreign = [a for a in live if a.get("id") not in ids]
        if foreign:
            P.start_log(f"stop-wait-foreign\t{name}\t{_holder_text(foreign[0])}")
            return copies_message(name, foreign)
        holders = name_holders(name, agents, registry) if agents is not None else None
        t = time.monotonic()
        spent = t - started
        if holders == [] and not revived:
            free_since = t if free_since is None else free_since
            if t - free_since >= settle:
                P.start_log(f"stop-wait-free\t{name}\t{spent:.1f}")
                return None
            time.sleep(poll)
            continue
        free_since = None
        if spent >= wait:
            held = "; ".join(_holder_text(a) for a in holders) if holders else "claude agents не ответил"
            P.start_log(f"stop-wait-timeout\t{name}\t{wait:.0f}\t{held}")
            return (f"{name}: за {wait:.0f} с остановленные копии не отпустили имя ({held}) — новую не запускаю: "
                    f"Claude Code назвал бы её «{name}-два-слова», и сообщения на {name} до неё не дойдут. Проверьте "
                    f"claude agents и повторите запуск с --restart")
        time.sleep(poll)


def check_new_name(name, before):
    """После `claude --bg --name <имя>`: новая живая сессия (её id не было в списке до запуска) получила ровно это имя,
    а не «имя-два-слова» или «имя (2)». → None или текст тревоги. Чужую копию не останавливает — решает Зевс. Не
    появилась за PANTHEON_NAME_WAIT (10 с) — строка в start.log и None: claude --bg отработал, а «не появилась» дежурный
    проверяет сам (autostart_check)."""
    _, poll, _ = P.stop_wait_knobs()
    wait = 10.0
    with contextlib.suppress(ValueError, TypeError):
        wait = max(0.0, float(os.environ.get("PANTHEON_NAME_WAIT") or wait))
    alias, started = P.name_alias(name), time.monotonic()
    while True:
        new = [a for a in P.agents_all() or [] if a.get("id") and a.get("id") not in before
               and a.get("state") not in P.DOWN_STATES and alias.fullmatch(str(a.get("name") or ""))]
        wrong = [a for a in new if a.get("name") != name]
        if wrong:
            ids = ", ".join(f"{a['id']} «{a.get('name')}»" for a in wrong)
            P.start_log(f"name-mismatch\t{name}\t{ids}")
            return (f"{name}: новая сессия получила чужое имя — {ids}: имя «{name}» держала другая сессия, сообщения на "
                    f"{name} до неё не дойдут. Что сделать: claude agents — найти, кто держит «{name}», лишнее "
                    f"остановить и повторить запуск с --restart (он остановит и {wrong[0]['id']}); pantheon её не "
                    "останавливал")
        if new:
            P.start_log(f"name-ok\t{name}\t{new[0]['id']}")
            return None
        if time.monotonic() - started >= wait:
            P.start_log(f"name-unseen\t{name}")
            print(f"pantheon start: новой сессии {name} за {wait:.0f} с нет в claude agents — имя не проверено",
                  file=sys.stderr)
            return None
        time.sleep(poll)


def start_at(rest, origin, dry):
    """Разовый запуск плановым проходом вместо `sleep` в сессии (metis-0284): запись в STATE/oneshot.json, исполняет
    дежурный один раз (lib/watch.py oneshots). Та же подкоманда start — те же права, что у запуска."""
    N = P.night_mod()
    t = P.now()
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
    domains = P.read_json(P.path("domains.json"), {}).get("domains") or {}
    if target not in domains:
        print(f"pantheon start --at: «{target}» — не направление из domains.json (разовый запуск — только направлений)",
              file=sys.stderr)
        return 2
    try:
        when = N.parse_at(when_s, t)
    except ValueError as e:
        print(f"pantheon start --at: {e}", file=sys.stderr)
        return 2
    got = P.start_target(target, [])
    if isinstance(got, str) and target in P.hq_led():  # metis-0155: разовый запуск координатора, которого нет, — отказ
        print(f"pantheon start --at: {got}", file=sys.stderr)
        return 2
    text = text or (got[4] if not isinstance(got, str) else "")
    if dry:
        print(f"[at] {target} в {P.stamp(when)} — {text}")
        return 0
    if origin == "zeus" and not owner_spoke_recently("zeus", OWNER_WORD_WINDOW):  # слово — при постановке, не при запуске
        print(f"pantheon start --at: отказ — {NO_WORD_WHY}", file=sys.stderr)
        capacity_log({"t": round(P.now(), 1), "at": P.stamp(), "target": target, "origin": origin, "result": "refused",
                      "kind": "at"})
        return START_REFUSED
    oid = N.oneshot_add(target, when, text, origin, t=t)
    print(f"разовый запуск {oid}: {target} в {P.stamp(when)} — исполнит плановый проход (pantheon watch), срок "
          f"{N.ONESHOT_TTL // 3600} ч; отмена — pantheon start --at-cancel {oid}")
    return 0


# metis-0771 (слово владельца 03.11 19:17): `pantheon start <направление>` без других слов в окне Пританея — заявка.
# Пританей не делает работу направления сам, а поднимает окно координатора: заявка — строка JSON в
# STATE/hq-rw/start-req/<имя>.req (окну hq туда можно писать), плановый проход вне окна (take_start_requests) проверяет её
# и ставит разовый запуск — его исполняет oneshots по своим правилам (занятость, недельный шлюз, один за проход).
# С поручением или флагами — прежний путь: запуск сразу, только по вашему слову в owner-log (start_gate).
START_REQ = "start-req"
START_REQ_KEYS = {"target", "time", "by"}
START_REQ_MAX = 4096


def _start_req_problem(target, doms):
    """Имя для заявки: только направление из реестра (domains.json), не то, что ведёт Пританей. → причина или None."""
    if not P.SESSION_NAME.fullmatch(target or "") or target not in doms:
        return f"«{target}» нет в реестре направлений (domains.json)"
    if target in P.hq_led():
        return P.hq_led_why(target)
    return None


def start_request(target, dry=False):
    """Заявка окна Пританея на запуск окна координатора → 0 (принята), START_REFUSED (имя не из реестра), 1 (не записана)."""
    bad = _start_req_problem(target, P.read_json(P.path("domains.json"), {}).get("domains") or {})
    if bad:
        print(f"pantheon start: заявка не принята — {bad}", file=sys.stderr)
        return START_REFUSED
    if dry:
        print(f"pantheon start: заявка на {target} была бы принята (--dry-run)")
        return 0
    line = json.dumps({"target": target, "time": P.stamp(P.now()), "by": "zeus"}, ensure_ascii=False) + "\n"
    if not P.hq_mark(START_REQ, target + ".req", line):
        return 1
    print(f"pantheon start: заявка принята, окно {target} поднимется на следующем проходе")
    return 0


def _start_req_read(dfd, fname):
    """Содержимое заявки или причина отказа: только обычный файл владельца, одна ссылка, не больше START_REQ_MAX."""
    try:
        fd = os.open(fname, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    except OSError as e:
        return None, f"не открыть ({e.strerror})"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid() or st.st_size > START_REQ_MAX:
            return None, f"не обычный файл, ссылок {st.st_nlink}, владелец {st.st_uid} или больше {START_REQ_MAX} байт"
        return os.read(fd, START_REQ_MAX + 1), None
    finally:
        os.close(fd)


def take_start_requests(doms, t):
    """Плановый проход (вне окна): заявки Зевса → разовые запуски. Файл заявки снимается всегда; подложенный (ссылка,
    лишние ключи, чужое имя, не из реестра) — тревога без запуска. → [(имя, id разового запуска или причина)]."""
    try:
        dfd = os.open(P.path(P.HQ_RW, START_REQ), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        return []
    out = []
    try:
        for fname in sorted(os.listdir(dfd)):
            if not fname.endswith(".req"):
                continue
            target = fname[:-4]
            data, bad = _start_req_read(dfd, fname)
            with contextlib.suppress(OSError):
                os.unlink(fname, dir_fd=dfd)
            bad = bad or _start_req_problem(target, doms)
            if not bad:
                try:
                    items = [json.loads(x) for x in data.decode().splitlines() if x.strip()]
                except (ValueError, UnicodeDecodeError):
                    items = None
                if not items or any(not isinstance(x, dict) or set(x) - START_REQ_KEYS or x.get("target") != target
                                    or x.get("by") != "zeus" for x in items):
                    bad = "не по образцу: строки JSON с ключами target, time, by, имя — как у файла"
            if bad:
                P.alert(f"заявка Зевса на запуск {target} отклонена: {bad}", "watch")
                out.append((target, bad))
                continue
            text = (f"Прочитай ~/ai/pantheon/directions/{target}/STATUS.md и inbox/, затем продолжай текущий эпик по "
                    "нему.")
            oid = P.night_mod().oneshot_add(target, t, text, "zeus-request", t=t)
            P.alert(f"заявка Зевса: окно {target} — разовый запуск {oid} на этом проходе", "watch")
            out.append((target, oid))
    finally:
        os.close(dfd)
    return out


def start(rest):
    """pantheon start <направление> [поручение] | workshop <задача> [поручение] | zeus [--restart]  [--from кто] [--dry-run]
    pantheon start <направление> --at ЧЧ:ММ|"ГГГГ-ММ-ДД ЧЧ:ММ" [поручение] | --at-list | --at-cancel <id>   разовый запуск
                                                                                    плановым проходом (вместо sleep)
    Запуск сессии пишет замер в STATE/capacity.jsonl (сессий Пантеона, давление памяти, свободно %, своп). Откуда запуск:
    --from, а без него по окну — PANTHEON_ROLE=hq это zeus, другая роль tick, без роли owner; в окне роли --from owner
    и любой --from, не совпадающий с origin окна (hq → zeus, иная роль → tick), не принимаются (код 2). Отказ, код 2: zeus без вашего слова в owner-log/zeus.md за 15 мин (и у --at при постановке).
    Красный замер (своп выше порога дежурного, давление не «норма») или «нет сигнала» — только предупреждение
    (строка в stderr, тревога раз в день, red в замере): запуск не откладывается ([sb-simplify] п. 5, metis-0523).
    Код 4 — пропуск, не сбой: у --from tick проигранная гонка за имя (блокировка занята другим процессом — start-busy, или под
    блокировкой уже стоит живая копия с id — start-skip, строки в start.log); у owner/zeus, вкладки без id, --restart и
    подложенной записи блокировки — код 1 (metis-0717).
    Разовый запуск (--at) исполняется по правилам планового прохода, слово при постановке не переносится."""
    dry = "--dry-run" in rest
    restart = "--restart" in rest
    over = OVER_CAP in rest  # metis-0444: сверх недельного потолка — только ваш терминал (launch_cap)
    rest = [a for a in rest if a not in ("--dry-run", "--restart", OVER_CAP)]
    # откуда запуск, по окну вызова (metis-0261 А, ревью argus): в окне роли PANTHEON_ROLE задан, и владелец там не
    # говорит — окно Пританея (hq) считается Зевсом, остальные — плановым проходом (tick); без роли — терминал владельца
    role = os.environ.get("PANTHEON_ROLE") or ""
    origin = "zeus" if role == "hq" else "tick" if role else "owner"
    if "--from" in rest:
        i = rest.index("--from")
        if i + 1 >= len(rest) or rest[i + 1] not in ("zeus", "tick", "owner"):
            print("pantheon start: --from zeus | tick | owner", file=sys.stderr)
            return 2
        if role and rest[i + 1] == "owner":
            print(f"pantheon start: --from owner не принимается в окне роли ({role}) — слово владельца там проверяется "
                  "по owner-log (--from zeus)", file=sys.stderr)
            return 2
        if role and rest[i + 1] != origin:  # круг 3: явный --from в окне роли — только свой origin (hq → zeus, роль → tick)
            print(f"pantheon start: в окне роли ({role}) --from только {origin} (окно задаёт происхождение), "
                  f"не {rest[i + 1]}", file=sys.stderr)
            return 2
        origin, rest = rest[i + 1], rest[:i] + rest[i + 2:]
    if any(a in ("--at", "--at-list", "--at-cancel") for a in rest):
        return start_at(rest, origin, dry)
    if not rest:
        print(start.__doc__, file=sys.stderr)
        return 2
    target, rest = rest[0], rest[1:]
    if role == "hq" and target not in ("zeus", "workshop") and not rest:
        return start_request(target, dry)  # metis-0771: из окна Пританея — заявка, окно поднимет плановый проход
    if target == "zeus":
        if not dry:  # сессии не считаем: лишний claude agents ломает сценарии ожидания имени; слово и память — да
            code, why = start_gate(target, origin, None)
            if why:
                print(f"pantheon start: отказ — {why}", file=sys.stderr)
                return code
        # штаб — ваша интерактивная сессия в iTerm: команда заменяет себя на claude в ~/ai/pantheon
        argv = [P.claude_bin(), "--agent", "hq", "--name", "zeus", "--settings", P.path("settings", "hq.json")]
        if dry:
            print(shlex.join(argv), f"(папка {P.PANTHEON})")
            return 0
        if not os.path.isfile(P.path("settings", "hq.json")):
            print("нет окна Пританея — сначала pantheon domains build", file=sys.stderr)
            return 1
        if not sys.stdin.isatty():
            print("Пританей запускается в вашем терминале: pantheon start zeus", file=sys.stderr)
            return 2
        # Зевс — одна сессия. Вкладка iTerm — только окно к фоновой сессии: закрыть вкладку или убить её процесс
        # мало, сессия живёт дальше, и новый запуск становится «zeus-<два слова>» (15.10 так появилось два Зевса)
        with P.lock("start-zeus", block=False) as got:
            if not got:
                print("Зевс уже запускается другой командой", file=sys.stderr)
                return 1
            live = P.live_copies("zeus", P.agents_all())
            if live and (not restart or any(not a.get("id") for a in live)):
                print(f"pantheon start: {copies_message('zeus', live)}", file=sys.stderr)
                return 1
            P.stop_copies("zeus", live)
            # execv заменяет процесс — имя после запуска не проверить, поэтому до запуска ждём, пока старый Зевс
            # отпустит имя (15.10 без ожидания новый стал zeus-sparkling-cat, metis-0041)
            why = wait_name_free("zeus", live) if live else None
            if why:
                print(f"pantheon start: {why}", file=sys.stderr)
                return 1
        P.start_log(f"zeus\t{origin}\t{P.PANTHEON}")
        os.chdir(P.PANTHEON)
        os.execve(argv[0], argv, P.claude_env())
    got = P.start_target(target, rest)
    if isinstance(got, str):
        print(f"pantheon start: {got}", file=sys.stderr)
        return 2
    name, role, folder, window, default_task = got
    if target == "workshop":
        rest = rest[1:]
    win = P.path("settings", window + ".json")
    problems = P.allow_gate(name)  # allow со старым mtime сборка не заметила (ревью argus PR #32)
    if problems:
        print(f"pantheon start: окно не собрано — {P.project_allow_text(name, problems)}", file=sys.stderr)
        return 1
    if not os.path.isfile(win):
        print(f"pantheon start: нет окна {win.replace(P.HOME, '~')} — pantheon domains build", file=sys.stderr)
        return 1
    if os.path.exists(P.path("stopped", name)):
        print(f"pantheon start: {name} остановлена вами (pantheon resume {name})", file=sys.stderr)
        return 1
    # одна сессия на имя (Temporal: conflict policy «fail» по умолчанию, «terminate existing» — по --restart);
    # проверка и запуск — под блокировкой имени: тик и Зевс не запустят две копии одновременно
    with P.lock("start-" + name, block=False) as got:
        if not got:
            if origin == "tick" and P.LOCK_CONTENDED == "start-" + name:
                # metis-0717: плановый проход проверил снимок и пошёл запускать, а имя уже поднимает другой процесс —
                # он проиграл гонку, это пропуск (код 4, как у resume_session), а не сбой; подложенная запись замка
                # (LOCK_CONTENDED не выставлен) по-прежнему код 1
                P.start_log(f"start-busy\t{name}\t{origin}")
                print(f"pantheon start: {name} — пропуск, другой процесс уже поднимает", file=sys.stderr)
                return P.SKIPPED
            print(f"pantheon start: {name} — блокировка имени не взята: уже запускается другой командой или запись блокировки "
                  f"подложена (строка выше)", file=sys.stderr)
            return 1
        return _start_session(name, role, folder, window, default_task, rest, origin, dry, restart, win,
                              over_cap=over, race_skip=(origin == "tick"))


def _start_session(name, role, folder, window, default_task, rest, origin, dry, restart, win, need_word=False,
                   cmd="pantheon start", extra_env=None, again=None, over_cap=False, race_skip=False):
    agents = P.agents_all()
    if not dry:  # metis-0261 А: слово владельца, потолок и замер — до любых действий; список сессий тот же, что ниже
        code, why = start_gate(name, origin, agents, need_word, over_cap)
        if why:
            print(f"{cmd}: отказ — {why}", file=sys.stderr)
            return code
    same = [a for a in agents or [] if a.get("name") == name]
    live = P.live_copies(name, agents)
    # metis-0348: «blocked» без процесса и без вопроса (noProcess, reconcile_agents) — сессию снял Claude Code, ждать
    # ей нечего: она мёртвая и запуску не мешает, --restart и владелец не нужны. Её `claude rm` — rm_previous после
    # успешного старта новой. С вопросом (needs) noProcess не ставится — такая по-прежнему ждёт вас (отказ ниже).
    # metis-0651: призрак (ghost) в списке уже failed и в live не входит: призрак с вопросом (был blocked, вопрос виден)
    # по-прежнему ждёт вас — отказ как раньше; без вопроса он мёртвый и заменяется новой.
    alias = P.name_alias(name)
    ghosts = [a for a in agents or [] if a.get("ghost") and a.get("id") and alias.fullmatch(str(a.get("name") or ""))]
    live += [a for a in ghosts if P.asks_owner(a)]  # detail задания вопросом не считается (argus-249a Б1)
    dead = [a for a in live + ghosts if a.get("noProcess") and a.get("id")]
    dead = [a for i, a in enumerate(dead) if a not in dead[:i]]
    if dead:
        live = [a for a in live if a not in dead]
        if not dry:
            for a in dead:
                P.start_log(f"dead-blocked\t{name}\t{a['id']}\tнет процесса и вопроса — заменяется новой")
    if live and not dry and (not restart or any(not a.get("id") for a in live)):
        print(f"{cmd}: {copies_message(name, live, again)}", file=sys.stderr)
        if race_skip and not restart and all(a.get("id") for a in live):
            # metis-0717: плановый проход видел имя свободным (снимок до блокировки), под блокировкой его уже держат —
            # проигранная гонка, пропуск (код 4), а не сбой; вкладка терминала (без id) и --restart — как раньше
            P.start_log(f"start-skip\t{name}\t{origin}\tуже работает")
            return P.skipped("уже работает")
        return 1
    stopped = []
    if live and not dry:
        P.stop_copies(name, live)
        stopped += live
    # CTX-10: эпик закончен — сессия «done» ещё висит в списке; новый эпик — новая сессия с тем же именем, а старая
    # останавливается и убирается из списка (claude rm, metis-0239; переписка остаётся: claude --resume <сессия>),
    # иначе Claude Code назовёт новую «имя (2)»
    # (claude rm прежних — только после успешного старта новой, rm_previous, metis-0250)
    for a in same:
        if a.get("state") == "done" and a.get("pid") and a.get("id") and not dry:
            P.stop_copies(name, [a], "stop-done")
            stopped.append(a)
    # остановленная копия отпускает имя не сразу и может ожить (metis-0041): запуск — только когда имя свободно
    why = wait_name_free(name, stopped) if stopped else None
    if why:
        print(f"pantheon start: {why}", file=sys.stderr)
        return 1
    run = P.path("settings", "run", name + ".json")
    task = " ".join(rest).strip() or default_task
    prompt = f"{P.START_MARK} поручение от {origin}] {task}"
    if role == "domain-coordinator":
        # DONE-02: /goal первым словом поручения — Stop-хук сессии с отдельной проверяющей моделью: координатор не
        # закончит, пока условие не выполнено (проверено вживую 15.10: `claude --bg "/goal …"` включает цель)
        prompt = "/goal " + prompt + " " + (TASK_GOAL if " ".join(rest).strip() else COORDINATOR_GOAL)
    argv = [P.claude_bin(), "--bg", "--agent", role, "--name", name, "--settings", run, prompt]
    if dry:
        print(shlex.join(argv), f"(папка {folder})")
        return 0
    if P.run_settings(name, role, window, origin, extra_env) != run:  # окно пропало после проверки — прежний файл запуска не берём
        print(f"pantheon start: нет окна {win.replace(P.HOME, '~')} — pantheon domains build", file=sys.stderr)
        return 1
    before = {a.get("id") for a in P.agents_all() or [] if a.get("id")}
    r = subprocess.run(argv, cwd=folder, env=P.claude_env(), capture_output=True, text=True, timeout=180)
    P.start_log(f"{name}\t{origin}\t{folder}\t{r.returncode}")
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        return r.returncode
    wrong = check_new_name(name, before)
    if wrong:
        P.alert(wrong, "pantheon-start")
        print(f"pantheon start: {wrong}", file=sys.stderr)
        return 1
    P.rm_previous(name, "start", before=before, loud=True)
    return 0


# metis-0261 (А): лазейка 15.10 закрыта. Запуск «от Зевса» (--from zeus) без вашей строки в его журнале owner-log за
# последние минуты — отказ, код 2 (раньше только тревога). Соседний путь `wake <имя> "задание"` из окна роли —
# тот же отказ (watch.py wake_one, owner_word_ok; круг 4). Ваше слово — запись в owner-log/zeus.md, её пишет хук.
OWNER_WORD_WINDOW = 15 * 60
OWNER_HEAD = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", re.M)


def owner_word_heads(session):
    """Заголовки записей владельца «## ГГГГ-ММ-ДД ЧЧ:ММ:СС» в ~/.local/state/pantheon/owner-log/<session>.md (хвост
    64 КБ), по порядку файла. Файла нет — []."""
    try:
        with open(P.path("owner-log", session + ".md"), "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 65536))
            return OWNER_HEAD.findall(fh.read().decode("utf-8", "replace"))
    except OSError:
        return []


def owner_spoke_recently(session, window):
    """Есть ли в ~/.local/state/pantheon/owner-log/<session>.md запись владельца не старше window секунд."""
    heads = owner_word_heads(session)
    if not heads:
        return False
    try:
        last = datetime.strptime(heads[-1], "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return False
    return P.now() - last <= window


def owner_spoke_before(session, t, window, slack=60):
    """Сказал ли владелец в окне <session> что-то за window секунд до момента t (slack — запас на часы и запись хука).
    metis-0276: поручение Зевса во входящих будит координатора, только если файл написан по свежему слову владельца —
    то же правило, что у pantheon start --from zeus (metis-0261 А), но на время файла, а не на время подъёма."""
    for h in owner_word_heads(session):
        with contextlib.suppress(ValueError):
            if t - window <= datetime.strptime(h, "%Y-%m-%d %H:%M:%S").timestamp() <= t + slack:
                return True
    return False


CAPACITY_SESSIONS_DONE = ("stopped", "failed", "done")


def capacity_probe(agents):
    """Замер загрузки Mac для pantheon start (metis-0261 А): agents — список claude agents (или None); сессий Пантеона, давление памяти (kern.memorystatus_vm_pressure_level:
    1 норма, 2 предупреждение, 4 критично), свободно % (memory_pressure), своп ГБ. Чего не удалось прочитать — None.
    Красный (red): своп выше SWAP_ALERT_GB (порог дежурного, watch.py) или давление не «норма» — новых чисел нет."""
    w = P.watch_mod()
    out = {"sessions": None, "pressure": None, "free_pct": None, "swap_gb": None}
    if agents is not None:
        doms = w.domains()
        out["sessions"] = sum(1 for a in agents if a.get("state") not in CAPACITY_SESSIONS_DONE
                              and w.is_pantheon(a.get("name"), doms))
    with contextlib.suppress(Exception):
        out["swap_gb"] = w.swap_gb()
    if out["swap_gb"] is None:  # в окне роли sysctl даёт EPERM: берём замер тика (metis-0537)
        out["swap_gb"] = P.probe_value("swap_gb")
    # через _memory_pressure: она понимает подмену PANTHEON_FAKE_PRESSURE — прямой sysctl тут давал тестам давление
    # настоящего Mac, и при «предупреждении» у владельца test_watch падал целиком (36 из 85)
    out["pressure"] = P._memory_pressure()
    with contextlib.suppress(Exception):
        r = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10)
        m = re.search(r"free percentage:\s*(\d+)%", r.stdout)
        if m:
            out["free_pct"] = int(m.group(1))
    if out["free_pct"] is None:
        out["free_pct"] = P.probe_value("free_pct")
    limit = w.threshold("swap_alert_gb", w.SWAP_ALERT_GB)
    reasons = []
    if out["swap_gb"] is not None and out["swap_gb"] > limit:
        reasons.append(f"своп {out['swap_gb']:.1f} ГБ > {limit:g} ГБ")
    if out["pressure"] is not None and out["pressure"] >= 2:
        reasons.append(f"давление памяти {'критичное' if out['pressure'] >= 4 else 'предупреждение'}")
    out["red"] = reasons
    out["unknown"] = out["swap_gb"] is None and out["pressure"] is None  # нет ни одного сигнала памяти
    return out


def capacity_log(row):
    """Строка замера в STATE/capacity.jsonl; запись не должна ронять запуск."""
    with contextlib.suppress(OSError):
        os.makedirs(P.STATE, exist_ok=True)
        fd = os.open(P.path("capacity.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (json.dumps(row, ensure_ascii=False) + "\n").encode())
        finally:
            os.close(fd)


NO_WORD_WHY = (f"запуск от Зевса без вашего слова в его окне за {OWNER_WORD_WINDOW // 60} мин "
               "(сообщение другой сессии согласием не считается)")
START_REFUSED = 2   # отказ: нет слова владельца (--from zeus) — повтор бесполезен
START_DEFERRED = 5  # было «отложено по красной памяти»; с [sb-simplify] п. 5 start_gate его не отдаёт (код занят)
# (3 и 4 заняты: NO_WINDOW и SKIPPED у resume_session, те же числа дошли бы до дежурного как коды запуска)


OVER_CAP = "--over-cap"  # то же, что night.OVER_CAP: ручной запуск сверх недельного потолка (metis-0444)
# недельный потолок их не держит (metis-0444): zeus — окно владельца; hestia — служебная, ставит выпуски и чинит окна
# (решение владельца 29.10 по PR #193, «Б: Гестию оставить»)
CAP_FREE = ("zeus", "hestia")


def start_gate(target, origin, agents, need_word=False, over_cap=False):
    """pantheon start, перед запуском сессии (metis-0261 А): замер в capacity.jsonl (строка — у каждого не-dry start,
    дошедшего до этого шага; ранние выходы — «остановлено вами», «нет окна», занятое имя — и продолжение через
    resume_session строки не пишут). → (код, причина); (0, None) — можно.
    Слово владельца: --from owner (по умолчанию) — он сам; --from zeus — его свежая запись в owner-log/zeus.md (без неё
    отказ, код 2, всегда); tick слова не имеет.
    need_word (wake hestia из окна роли, не hq): запуск с поручением из окна роли — только по свежей записи в zeus.md,
    без неё отказ, код 2, в любой зоне (как wake <имя> "задание").
    Недельный потолок владельца достигнут (metis-0444, night.launch_cap) — отказ, код 2, у любого target, кроме CAP_FREE
    (zeus — окно владельца, hestia — служебная); over_cap (--over-cap) снимает отказ только при origin owner.
    Память (своп, давление) — только предупреждение для любого origin: строка в stderr и тревога раз в день, запуск идёт
    ([sb-simplify] п. 5, metis-0523; было — код 5 «отложено»)."""
    m = capacity_probe(agents)
    word = origin == "owner" or (origin == "zeus" and owner_spoke_recently("zeus", OWNER_WORD_WINDOW))
    code, why = 0, None
    if origin == "zeus" and not word:
        code, why = START_REFUSED, NO_WORD_WHY
    elif need_word and origin != "owner" and not owner_spoke_recently("zeus", OWNER_WORD_WINDOW):
        code, why = START_REFUSED, (f"поручение из окна роли — только по вашему слову: в журнале Зевса нет вашей строки "
                                    f"за {OWNER_WORD_WINDOW // 60} мин (сообщение другой сессии согласием не считается)")
    elif target not in CAP_FREE and (cap := P.night_mod().launch_cap(origin, over_cap)):
        code, why = START_REFUSED, cap
    elif m["red"] or m["unknown"]:
        # [sb-simplify] п. 5 (metis-0523): своп и давление памяти — только предупреждение, запуск не откладывается.
        # Строка в stderr и одна тревога в день; от расхода держит потолок недели (night.gate), а не замер памяти
        reasons = "; ".join(m["red"]) if m["red"] else "нет сигнала: своп и давление памяти не прочитаны"
        print(f"pantheon start: предупреждение — память Mac в красной зоне ({reasons}), {target} запускается",
              file=sys.stderr)
        with contextlib.suppress(OSError):  # тревога — подсказка: её сбой запуск не держит
            P.alert_once("start-memory-red", P.stamp()[:10], f"запуски идут при красной памяти Mac ({reasons}) — "
                       f"предупреждение, не отказ; первый за день: {target}", "pantheon-start")
    capacity_log({"t": round(P.now(), 1), "at": P.stamp(), "target": target, "origin": origin, "sessions": m["sessions"],
                  "pressure": m["pressure"], "free_pct": m["free_pct"], "swap_gb": None if m["swap_gb"] is None
                  else round(m["swap_gb"], 2), "red": bool(m["red"]),
                  "unknown": m["unknown"], "result": {0: "allowed", START_REFUSED: "refused", START_DEFERRED: "deferred"}[code]}
                 | ({"over_cap": True} if over_cap and origin == "owner" else {}))
    return code, why


def open_tasks(name):
    """Открытые задачи, которые ведёт сессия: её направление, владелец или аренда."""
    out = []
    for tid, (_, head, _) in P.tasks_mod().load_tasks(P.PANTHEON).items():
        if head.get("status") not in OPEN_STATUSES:
            continue
        if name in (head.get("owner"), head.get("claimed_by"), head.get("direction")):
            out.append(tid)
    return out


def wake_recheck(name, state=None):
    """Под блокировкой имени перед подъёмом: метка, пауза, техперезапуск, живая копия «имя (2)» (ревью argus).
    state == "blocked" — сессия на лимите: «живая» для claude agents, её и будим, копии не ищем."""
    if state == "blocked":
        return P.awake_mod().recheck(name)
    if os.path.exists(P.path("stopped", name)):
        return "остановлено вами"
    if load_pause(name):
        return "пауза по нагрузке"
    if P.maintenance_active():
        return "технический перезапуск"
    if P.live_copies(name, P.agents_all() or []):
        return "уже работает"
    return None


def wake_hestia(rest):
    """pantheon wake hestia --task <id> [--restart] [--dry-run] (metis-0217, metis-0245): Гестия — фоновой сессией `hestia` в своём
    окне песочницы (settings/hestia.json, собирает sandbox_build; PANTHEON_ROLE=hestia — правило guard hestia), папка
    запуска — её кэш. Одна задача — одна сессия: без задачи, с id не по образцу, несуществующей или не открытой задачей
    — отказ «нет задачи», код 2, claude не зовётся. Нет окна, кэша или роли (~/.claude/agents/hestia.md) — код 1 с
    командой сборки. Метка «остановлено вами», технический перезапуск и живая копия — отказ, как у start.
    Откуда — как у start: hq → zeus, иная роль → tick, без роли → owner; из окна роли без вашего слова в
    owner-log/zeus.md за 15 мин — отказ, код 2, строка refused в capacity.jsonl, claude не зовётся. Недельный потолок
    владельца Гестию не держит (CAP_FREE, решение владельца 29.10)."""
    dry = "--dry-run" in rest
    restart = "--restart" in rest  # metis-0575: зависшую прежнюю Гестию стопит и убирает (claude stop, затем rm_previous)
    args = [a for a in rest[1:] if a not in ("--dry-run", "--restart")]
    tid = args[1] if len(args) == 2 and args[0] == "--task" else None
    head = None
    if tid and P.tasks_mod().ID_RE.fullmatch(tid):
        head = (P.tasks_mod().load_tasks(P.PANTHEON).get(tid) or (None, None, None))[1]
    if not head or head.get("status") not in OPEN_STATUSES:
        why = ("укажи --task <id> открытой задачи (todo, doing, review)" if head is None
               else f"задача {tid} не открыта ({head.get('status')})")
        print(f"pantheon wake hestia: отказ — нет задачи: {why}; claude не запускался", file=sys.stderr)
        return 2
    win = P.path("settings", "hestia.json")
    folder = P._real_dir("~/Library/Caches/pantheon-sandbox/hestia", ["~/Library/Caches/pantheon-sandbox"], strict=True)
    if not os.path.isfile(win) or not folder:
        print(f"pantheon wake hestia: нет окна {win.replace(P.HOME, '~')} или его папки — pantheon domains build",
              file=sys.stderr)
        return 1
    if not os.path.isfile(os.path.join(P.AGENTS, "hestia.md")):
        print("pantheon wake hestia: нет роли ~/.claude/agents/hestia.md — pantheon roles build", file=sys.stderr)
        return 1
    if os.path.exists(P.path("stopped", "hestia")):
        print("pantheon wake hestia: hestia остановлена вами (pantheon resume hestia)", file=sys.stderr)
        return 1
    m = P.maintenance_active()
    if m and not dry:
        print(f"pantheon wake hestia: идёт технический перезапуск ({m.get('reason')}) — после pantheon restart --go",
              file=sys.stderr)
        return 1
    # откуда запуск — как в start() (metis-0261 А, ревью argus-b5): hq → zeus, иная роль → tick, без роли → owner.
    # Поручение Гестии из окна роли — только по вашему слову в owner-log/zeus.md (как wake <имя> "задание"), иначе код 2
    role = os.environ.get("PANTHEON_ROLE") or ""
    origin = "zeus" if role == "hq" else "tick" if role else "owner"
    task = (f"Задача {tid}: прочитай её карточку (pantheon task show {tid}) и сделай ровно то, что в ней. Отчёт — по "
            "формату роли, каждое действие — строкой журнала в нём.")
    with P.lock("start-hestia", block=False) as got:
        if not got:
            print("pantheon wake hestia: hestia уже запускается другой командой", file=sys.stderr)
            return 1
        return _start_session("hestia", "hestia", folder, "hestia", task, [], origin, dry, restart, win,
                              need_word=bool(role), cmd="pantheon wake hestia",
                              again=f"pantheon wake hestia --task {tid} --restart",
                              extra_env={"PANTHEON_TASK": tid, "PANTHEON_TASK_DIRECTION": str(head.get("direction") or "")})


def wake_lead(rest, over=False):
    """pantheon wake <направление> --task <id> [--dry-run] (metis-0155, вариант Б): направление с coordinator = false
    ведёт Пританей, а задачу направления делает фоновое окно лида кода `hephaestus-<коротко>`. Окно — то же, что у
    координатора: settings/<направление>.json (песочница направления, её собирает sandbox_build — здесь не меняется),
    папка запуска координатора, PANTHEON_ROLE=domain-coordinator и определение роли `--agent domain-coordinator`;
    отличаются только имя сессии (hephaestus-<коротко>) и поручение — одна задача. Роль — координатора, а не лида: guard
    и шлюз слияния судят по agent_type, и главную сессию с agent_type лида они не пускают ни в gh pr merge, ни в STATUS.md
    направления (ревью argus PR #125, круг 1). Новых прав у Пританея нет: PR окно сливает через шлюз, как координатор.
    Отказ, код 2, claude не зовётся: не направление; у направления свой координатор; задачи нет, она не открыта или
    другого направления. Код 1: нет лида hephaestus в leads, роли ~/.claude/agents/hephaestus-<коротко>.md, окна или
    папки; allow проекта роняет окно; метка «остановлено вами» у лида или направления; технический перезапуск.
    Откуда и слово владельца — как у wake hestia: hq → zeus (без вашего слова за 15 мин — отказ), иная роль → tick
    (только по вашему слову), без роли → owner."""
    dry = "--dry-run" in rest
    args = [a for a in rest if a != "--dry-run"]
    target = args[0]
    cmd = f"pantheon wake {target}"
    domains = P.read_json(P.path("domains.json"), {}).get("domains") or {}
    if target not in domains:
        print(f"{cmd}: отказ — «{target}» не направление из domains.json; claude не запускался", file=sys.stderr)
        return 2
    entry = P.hq_led().get(target)
    if entry is None:
        print(f"{cmd}: отказ — у направления {target} свой координатор (coordinator = false не стоит): задачу ему — "
              f"pantheon start {target} \"<поручение>\"; claude не запускался", file=sys.stderr)
        return 2
    tid = args[2] if len(args) == 3 and args[1] == "--task" else None
    head = None
    if tid and P.tasks_mod().ID_RE.fullmatch(tid):
        head = (P.tasks_mod().load_tasks(P.PANTHEON).get(tid) or (None, None, None))[1]
    if not head or head.get("status") not in OPEN_STATUSES or head.get("direction") != target:
        why = ("укажи --task <id> открытой задачи направления (todo, doing, review)" if head is None
               else f"задача {tid} не открыта ({head.get('status')})" if head.get("status") not in OPEN_STATUSES
               else f"задача {tid} — направления {head.get('direction')}, не {target}")
        print(f"{cmd}: отказ — нет задачи: {why}; claude не запускался", file=sys.stderr)
        return 2
    lead = P.lead_session(target, entry)
    if not lead:
        print(f"{cmd}: у направления нет лида кода — в его записи directions.toml нужен leads = [\"hephaestus\"] "
              "(и имя вида бог-коротко), затем pantheon domains build", file=sys.stderr)
        return 1
    if not os.path.isfile(os.path.join(P.AGENTS, lead + ".md")):
        print(f"{cmd}: нет роли ~/.claude/agents/{lead}.md — pantheon roles build", file=sys.stderr)
        return 1
    got = P.direction_target(target, [], domains)
    if isinstance(got, str):
        print(f"{cmd}: {got}", file=sys.stderr)
        return 1
    _, role, folder, window, _ = got
    win = P.path("settings", window + ".json")
    problems = P.allow_gate(target)
    if problems:
        print(f"{cmd}: окно не собрано — {P.project_allow_text(target, problems)}", file=sys.stderr)
        return 1
    if not os.path.isfile(win):
        print(f"{cmd}: нет окна {win.replace(P.HOME, '~')} — pantheon domains build", file=sys.stderr)
        return 1
    for n in (lead, target):
        if os.path.exists(P.path("stopped", n)):
            print(f"{cmd}: {n} остановлено вами (pantheon resume {n})", file=sys.stderr)
            return 1
    m = P.maintenance_active()
    if m and not dry:
        print(f"{cmd}: идёт технический перезапуск ({m.get('reason')}) — после pantheon restart --go", file=sys.stderr)
        return 1
    role_env = os.environ.get("PANTHEON_ROLE") or ""
    origin = "zeus" if role_env == "hq" else "tick" if role_env else "owner"
    task = (f"Задача {tid} направления {target}. Координатора у направления нет — его ведёт Пританей, ты работаешь в окне "
            f"направления вместо координатора. Прочитай карточку (pantheon task show {tid}) и сделай ровно её: план, "
            "работа dev-*, ревью argus, PR и слияние через шлюз — как обычно. Отчёт — по формату роли разделом "
            f"«{tid}» в ~/ai/pantheon/directions/{target}/STATUS.md (его читает Пританей) и последним сообщением.")
    with P.lock("start-" + lead, block=False) as got:
        if not got:
            print(f"{cmd}: {lead} уже запускается другой командой", file=sys.stderr)
            return 1
        return _start_session(lead, role, folder, window, task, [task], origin, dry, False, win,
                              need_word=bool(role_env), cmd=cmd, over_cap=over)


def wake(rest, over=False):
    """pantheon wake [--dry-run] [--over-cap]: прерванные сессии Пантеона (failed, stopped) с открытой задачей — поднять
    и сказать «продолжай». Свои метки «остановлено вами» и чужие сессии (не направление и не daedalus-*) не трогает.
    Недельный потолок владельца достигнут — отказ, код 2, никого не поднимает (metis-0444; --over-cap — только ваш
    терминал); --dry-run потолок не проверяет."""
    dry = "--dry-run" in rest
    with P.lock("wake", block=False) as got:
        if not got:
            print("pantheon wake: уже идёт в другом процессе")
            return 0
        return _wake(dry, over)


def capacity_note(target, origin, agents, result="allowed"):
    """Только строка замера в capacity.jsonl, без отказа (pantheon wake: подъём прерванной сессии не откладываем).
    result — что решил вызвавший: "allowed" или "refused" (wake <имя> с заданием без слова владельца, metis-0261 А)."""
    m = capacity_probe(agents)
    capacity_log({"t": round(P.now(), 1), "at": P.stamp(), "target": target, "origin": origin, "sessions": m["sessions"],
                  "pressure": m["pressure"], "free_pct": m["free_pct"], "swap_gb": None if m["swap_gb"] is None
                  else round(m["swap_gb"], 2), "red": bool(m["red"]), "unknown": m["unknown"], "result": result})


def _wake(dry, over=False):
    m = P.maintenance_active()
    if m:
        print(f"идёт технический перезапуск ({m.get('reason')}) — будить некого до pantheon restart --go")
        return 0
    if not dry:
        role = os.environ.get("PANTHEON_ROLE") or ""
        cap = P.night_mod().launch_cap("zeus" if role == "hq" else "tick" if role else "owner", over)
        if cap:
            print(f"pantheon wake: отказ — {cap}; никого не поднимаю", file=sys.stderr)
            return START_REFUSED
    agents = P.agents_all()
    if agents is None:
        print("pantheon wake: claude agents --json не ответил", file=sys.stderr)
        return 1
    domains = P.read_json(P.path("domains.json"), {}).get("domains") or {}
    off = P.hq_led()  # metis-0155: координатора направления, которое ведёт Пританей, не поднимаем (pantheon check предупредит)
    done = failed = 0
    for a in agents:
        name, state = a.get("name") or "", a.get("state")
        asleep = state in ("failed", "stopped")
        if not asleep and state == "blocked":  # стоит на недельном лимите, сброс прошёл (metis-0132) — тоже спит
            with contextlib.suppress(Exception):
                asleep = P.awake_mod().limit_sleeping(a) is not None
        if not asleep or not (name in domains or name.startswith("daedalus-")) or name in off:
            continue
        if os.path.exists(P.path("stopped", name)) or load_pause(name):
            continue
        newer = [b for b in agents if b.get("name") == name and (b.get("startedAt") or 0) > (a.get("startedAt") or 0)]
        if newer:
            continue  # эпик уже продолжен новой сессией с тем же именем
        tasks = open_tasks(name)
        if not tasks:
            continue
        if P.asks_owner(a):  # metis-0662: призрак с вопросом поднимает ответ владельца, как у отказа pantheon start
            print(f"пропуск: {name} — ждёт вашего ответа: claude attach {a.get('id')}")
            continue
        fresh = P.fresh_reason(a)  # metis-0147 п. 2: большой контекст и остывший кэш — новая сессия с файла состояния
        how = (f"; свежей сессией ({fresh}), прочитает {' и '.join(P.tilde(p) for p in P.state_files(name))}" if fresh
               else "")
        line = f"{name} ({a.get('id')}, {state}) — задачи {', '.join(tasks[:3])}" + how
        if dry:
            print(f"будет поднята: {line}")
            continue
        capacity_note(name, "wake", agents)
        if fresh:
            rc = P.fresh_start(name, a, fresh_text("пробуждение", name, a.get("id")), "wake",
                             recheck=lambda n=name, s=state: wake_recheck(n, s), reason=fresh)
        else:
            rc, _ = P.resume_session(name, a, WAKE_TEXT, "wake", recheck=lambda n=name, s=state: wake_recheck(n, s))
        if rc == P.SKIPPED:  # metis-0291: пропуск — не сбой, ни «поднимаю», ни тревоги
            print(f"пропуск: {name} — {P.SKIP_WHY}")
            done += 1
            continue
        done += 1
        if rc == P.NO_WINDOW:  # «нет окна» — своя тревога, одна на причину; владельцу не говорим, что подняли (metis-0189)
            print(f"не поднимаю: {name} ({a.get('id')}, {state}) — см. тревогу")
            failed += 1
        elif rc:  # настоящий сбой подъёма: тревога и код 1 (metis-0291)
            print(f"не поднялась: {name} ({a.get('id')}, {state}) — код {rc}", file=sys.stderr)
            P.alert(f"pantheon wake: {name} не поднялась (код {rc})", "pantheon")
            failed += 1
        else:
            print(f"поднимаю: {line}")
    if not done:
        print("будить некого")
    return 1 if failed else 0
