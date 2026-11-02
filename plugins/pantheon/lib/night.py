"""Темп недельного лимита и ночной цикл Пантеона (metis-0127 п. 1 и 3, metis-0128, metis-0129; решения владельца 16.10).

  pantheon night [status]   неделя, линия, запас, зона; ночь; давность снимка лимита; потолок владельца и запас до него
  pantheon night report     блок «Лимит» для ежедневной сводки: неделя, потолок, линия, запас, зона, ночь, тревоги, сброс
  pantheon night ask <id> <направление> [ГГГГ-ММ-ДД]   вопрос о ночной пачке для окна вопросов Зевса (ниже)
  pantheon night agent-gate хук PreToolUse Agent|Task окон координаторов и штаба: отказ новому субагенту при потолке (ниже)

Снимок лимита пишет строка статуса Claude Code в ~/.local/state/claude-statusline/ (путь — от HOME, как LIMIT_SNAPSHOT):
`five-hour` — «pct resets_at now», `seven-day` — «pct resets_at now», `week-usage` — строки «now resets_at pct» (до 200).
Неделя — неубывающий снимок: наибольший pct по seven-day и строкам week-usage того же resets_at (допуск 1 ч), resets_at и
время — от самого свежего замера; без seven-day — по week-usage. Время замера — наибольшее now этих файлов.
Снимок старше snapshot_ok_min или его нет — лимит неизвестен, новое не запускается; старше snapshot_max_min — ещё и
строка в тревогах (её Зевс несёт в сводку). Пробный запрос (metis-0459): снимок старше snapshot_max_min (или его нет), а
ночь одобрена («да», не пропущена, не закрыта) и идёт с start минус 30 мин до end — проход раз в 30 мин зовёт
`claude -p` на Haiku (probe_run), чтобы строка статуса записала свежий снимок, и мерит заново; не освежилось — тревога
«зонд не освежил снимок», ночь не открывается. Работает ли `claude -p` как зонд, не проверено. resets_at в прошлом или недели нет — новая
неделя с неизвестным расходом: закрыто, пока строка статуса не запишет новый снимок.

Линия L = 100 × (t − (resets_at − 7 д)) / 7 д — сколько процентов недели «положено» к этому моменту; запас over =
used − L (п. п.). Зона: зелёная — over ≤ warn_pp; жёлтая — warn_pp < over ≤ stop_pp (днём новое не запускается,
одно уведомление с числами на зону в день); красная — over > stop_pp или used ≥ hard_pct (новое не запускается,
идущее не трогаем).

Ночь — с start до end по местному времени (P.now(), учитывает PANTHEON_NOW); «вечер D» — ночь, что начинается в дату
D. Бюджет ночи — budget_pct недели, из него check_pct — запас на проверки, на работу — budget_pct − check_pct. Перенос:
если L − used > carry_after_pp, к бюджету прибавляется carry_share × (L − used − carry_after_pp), всего не больше
cap_pct. Последняя ночь перед сбросом недели — сброс наступает в пределах 24 ч от начала ночи (раньше начала
следующей ночи): бюджет до last_night_pct, но used + бюджет ≤ hard_pct; перенос и cap_pct тогда не применяются. В долг
ночью не берём: бюджет считается один раз при открытии и не растёт, а занимать у будущих дней недели нельзя. Расход
ночи — used сейчас − used при открытии (сбросилась неделя посреди ночи — расход прошлой недели до сброса плюс новой).
Тревоги на 50, 80 и 100 % бюджета ночи — по одной на порог за ночь (P.alert_once); на 100 % ночь закрыта для нового.
После morning_after новое запускается, только если пятичасовой лимит не выше morning_five_hour_max.

Вечер (только главный Mac, [sb-simplify] п. 10, решение владельца 28.10, вариант Б): фиксированного вопроса в 22:00 нет,
ночь открывается только вашим ответом на вопрос о ночной пачке. Вопрос печатает `pantheon night ask <id> <направление>`:
«[<id>] Ночь <ГГГГ-ММ-ДД>: пачка <путь от ~/ai/pantheon> sha256 <64 hex>?», варианты «Да — ночь <ГГГГ-ММ-ДД>» | «Нет»
(дата — вечер ночи). Хук answer пишет выбор в owner-log/zeus.md с пометкой «окно вопросов», хук owner-log — выбор
варианта сообщением сразу после такого вопроса в чате с пометкой «ответ в чате» (metis-0405; служебные строки
«вариант:», «дословно:» сверка не видит, lib/answers.py). С ask_at до конца ночи
проход сверяет запись целиком: вопрос точно по шаблону, ответ — точно «Да — ночь <дата>», других строк нет, пачка по
этому пути есть и её sha256 сейчас тот же, что в вопросе. Тогда пачка одобрена (packs), ночь разрешена (answer «да»,
answer_at — время первого такого ответа) и открывается в start (ответ позже — в момент ответа). Любое отличие —
отказ и строка в тревогах, пачка изменилась после вопроса — тоже отказ: нужен новый вопрос. Каждая запись разбирается
один раз (answers_seen). Без такого ответа ночь не открывается: ночью новое не запускается. От расхода держат бюджет
ночи, зоны недели и потолок владельца (ниже). Карточку вопроса, заданного до выпуска, проход снимает. Состояние ночи —
STATE/night/<дата вечера>.json: answer, packs, opened_at, start_pct, budget_pct, skipped, alerts[] (и служебные:
answer_at, answers_seen, pack_jobs, spent, last_used, resets_at, closed, last_night; asked_at, card_id и auto — от
старых выпусков).

Метрики (STATE/metrics): новые строки week-usage дописываются в week-usage.log (только дописывание, без повторов —
по последнему скопированному now); смена resets_at — строка в weeks.jsonl: итог прошлой недели и её ночи.

Пороги — schedule.toml, без раздела или ключа — значения по умолчанию:

  [limits]
  warn_pp = 2              # запас выше — жёлтая зона
  stop_pp = 5              # запас выше — красная зона
  hard_pct = 85            # неделя на столько и выше — красная зона при любом запасе
  snapshot_ok_min = 30     # снимок старше — лимит неизвестен, новое не запускается
  snapshot_max_min = 180   # снимок старше — ещё и строка в тревогах
  heavy_max = 2            # тяжёлых (сессии направлений в работе и тяжёлые задачи тика) столько — новое не запускается

  [limits.night]
  start = "23:00"          # ночь с …
  end = "08:00"            # … до
  budget_pct = 3           # бюджет ночи, % недели
  check_pct = 1            # из него запас на проверки
  cap_pct = 5              # бюджет с переносом — не больше
  carry_share = 0.3        # доля переноса
  carry_after_pp = 5       # перенос — с отставания от линии больше стольких п. п.
  morning_after = "04:00"  # после — правило пятичасового лимита
  morning_five_hour_max = 50
  last_night_pct = 10      # последняя ночь перед сбросом недели

Недельный потолок владельца (metis-0403; его пишет Зевс по [id] решения владельца; без раздела — потолка нет):

  [limits.owner_cap]
  pct = 50                 # неделя ≥ стольких % — новое не начинается: autostart, wake и respawn днём и ночью
                           # (отказ с причиной), новые субагенты из окон координаторов и штаба (хук PreToolUse
                           # Agent, ниже), задачи `claude -p` тика и ручные start и wake (ниже, metis-0444)
  decision = "zeus-limit-budget"  # [id] решения владельца
  # срок — одно из (без них потолок стоит каждую неделю, пока запись есть):
  until = "2026-11-30"     # каждую неделю по эту дату включительно
  until = "reset"          # до сброса недели, в которую попал since (since обязателен)
  since = "2026-10-24"     # не раньше: дата — с начала суток (для until = "reset" — по конец этих суток: запись в день
                           # сброса после его часа держит до следующего сброса), «ГГГГ-ММ-ДД ЧЧ:ММ» или дата-время TOML — с момента
  date = "2026-10-19"      # старый вид: только этот день

Потолок только сужает: жёлтую и красную зону, heavy_max, hard_pct и ночь не снимает (решение 25.10; дневной потолок
metis-0275 работал как разрешение). Достигнут — неделя по снимку ≥ pct при сбросе в будущем; старый снимок тоже
годится: в пределах недели расход не убывает. Кривая запись (pct не число в (0, 100], nan, until = "reset" без since,
кривая дата) не действует, а `pantheon night status` пишет почему; кривая или истёкшая запись — ещё и одна тревога
в watch (причина в тексте). При достижении (главный Mac, дежурный или шлюз) —
одна строка в тревогах с уведомлением и одна карточка Зевсу «Ждёт вас» на неделю и pct (STATE/owner-cap.json):
стоять до сброса или поднять до pct + 10 %. Идущее не рвём: отказ — только новому.

Хук `pantheon night agent-gate` (hooks.json, PreToolUse Agent|Task): в окне координатора (PANTHEON_ROLE
domain-coordinator или workshop, и у его субагентов — лидов) и в окне штаба (hq, metis-0444) при достигнутом потолке
запуск субагента — отказ (permissionDecision deny) с причиной. Окна задач тика субагентов не зовут (agents.py), ваш
терминал хук не трогает. Python не запускается, пока в schedule.toml нет owner_cap (проверка оболочкой). Сбой
расчёта или битая запись — не отказ (как без потолка), код 1 и причина в stderr.

Ручные запуски и окна тика (metis-0444, launch_cap): при достигнутом потолке отказ, код 2, с причиной получают
`pantheon start <направление>|workshop`, `pantheon wake` (общий), `pantheon wake <имя>`, `wake <направление> --task`
и исполнение вашего ответа «Да — запустить|перезапустить|вернуть» плановым проходом; задача `claude -p`
тика не запускается и ждёт («ждёт: недельный потолок…» в `pantheon jobs`), срок не сдвигается. Пробный запуск
(--dry-run) не проверяется. `pantheon start zeus` потолок не держит: штаб — ваше окно, в нём вы и отвечаете на
вопрос о потолке. Гестию (`wake hestia`, ответ «Да — … hestia») потолок тоже не держит — решение владельца 29.10 по
PR #193: служебная роль ставит выпуски и чинит окна, в том числе исправление самого потолка. Запустить сверх потолка можно только из вашего терминала (без PANTHEON_ROLE) флагом --over-cap;
в окне роли (hq, координатор, плановый проход) флаг не действует — там только поднять потолок вашим словом. Сбой
расчёта — не отказ (как у хука): строка в stderr и одна тревога в день.

  [night]
  ask_at = "22:00"         # начало вечера: с него проход сверяет ваши ответы на вопросы о пачках
  power_at = "21:30"       # с этого времени до ask_at — проверка питания (pmset -g batt)
  batt_min = 80            # на батарее с зарядом ниже — тревога «подключите зарядку», одна за вечер

Время вечернего расписания — «ЧЧ:ММ»; раньше ask_at — это уже следующие сутки (00:00, 04:00, 08:00).

Ночная пачка (metis-0284): ~/ai/pantheon/directions/<направление>/night-<дата>-pack.md, дата — утро ночи (как
night-2026-10-19-pack.md у ночи 18→19) или вечер; направление — из domains.json. Пачка, уже одобренная прошлой ночью,
не берётся. Одобрена — только вашим ответом на её вопрос (выше): путь и sha256 файла — в состоянии ночи (packs). Каждая
пачка — разовый запуск её координатора в начале ночи (строка «Старт — ЧЧ:ММ» в пачке сдвигает его позже), срок —
конец ночи. Пачка изменилась после ответа — запуска нет, тревога. Ночью идут только одобренные пачки: самозапуск по
отметкам владельца ночь с пачками не трогает, а без пачки ночь не открыта.

Разовые запуски (STATE/oneshot.json, items): {id, target, at, expires, text, by, pack?, sha?, night?, done_at, result,
wait}. Ставит `pantheon start <направление> --at ЧЧ:ММ|"ГГГГ-ММ-ДД ЧЧ:ММ" [поручение]` (срок — 3 ч) и пачки ночи
(pack_schedule); исполняет дежурный (watch.oneshots) один раз: запись гасится (done_at) до самого запуска. Пока запуск закрыт
(шлюз недели и ночи, сессия занята) — ждёт следующего прохода до срока, после срока гаснет с тревогой.

Питание (metis-0284): с power_at до ask_at на главном Mac, если ночь этого вечера ещё не пропущена, — `pmset -g batt`;
на батарее с зарядом ниже batt_min — тревога и уведомление «подключите зарядку», одна за вечер.
"""
import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
from datetime import date, datetime, time as dtime, timedelta

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()


def set_core(mod):
    global P
    P = mod


WEEK = 7 * 86400
KINDS = ("autostart", "wake", "respawn")
CAP_ROLES = ("domain-coordinator", "workshop", "hq")  # окна, чьи новые субагенты держит потолок владельца (agent-gate)
OVER_CAP = "--over-cap"  # ручной запуск сверх потолка — только из терминала владельца (launch_cap, metis-0444)
LIMITS = {"warn_pp": 2.0, "stop_pp": 5.0, "hard_pct": 85.0, "snapshot_ok_min": 30.0, "snapshot_max_min": 180.0,
          "heavy_max": 2.0}
NIGHT = {"start": "23:00", "end": "08:00", "budget_pct": 3.0, "check_pct": 1.0, "cap_pct": 5.0, "carry_share": 0.3,
         "carry_after_pp": 5.0, "morning_after": "04:00", "morning_five_hour_max": 50.0, "last_night_pct": 10.0}
ASK = {"ask_at": "22:00", "power_at": "21:30", "batt_min": 80.0}
PACK_START = re.compile(r"^\W*старт\s*[—–:-]+\s*([01]\d|2[0-3]):([0-5]\d)", re.I | re.M)
PACK_TASK = re.compile(r"(?<![\w-])([a-z]+-\d{4})(?![\w-])")
ONESHOT_TTL = 3 * 3600  # разовый запуск `pantheon start --at` ждёт открытого шлюза столько, потом гаснет
ONESHOT_KEEP = 7 * 86400  # погашенные записи хранятся столько
THRESHOLDS = (50, 80, 100)
HM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
DAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
ZONES = {"green": "зелёная", "yellow": "жёлтая", "red": "красная"}


# --- настройки ---------------------------------------------------------------------------------------------------

def config():
    """(limits, night, ask) из schedule.toml поверх значений по умолчанию; кривое значение — по умолчанию."""
    try:
        sched = P.load_schedule()
    except Exception:  # noqa: BLE001 — нет или битый schedule.toml: пороги по умолчанию, лимит всё равно считается
        sched = {}
    lim = sched.get("limits") if isinstance(sched.get("limits"), dict) else {}
    nl = lim.get("night") if isinstance(lim.get("night"), dict) else {}
    ask = sched.get("night") if isinstance(sched.get("night"), dict) else {}

    def merge(base, got):
        out = dict(base)
        for k, v in base.items():
            g = got.get(k)
            if isinstance(v, float) and isinstance(g, (int, float)) and not isinstance(g, bool):
                out[k] = float(g)
            elif isinstance(v, str) and isinstance(g, str) and HM.fullmatch(g):
                out[k] = g
        return out
    return merge(LIMITS, lim), merge(NIGHT, nl), merge(ASK, ask)


def _cap_moment(v):
    """Поле срока потолка → (начало, конец): дата — сутки целиком; дата-время TOML или «ГГГГ-ММ-ДД ЧЧ:ММ» — этот
    момент (начало = конец). Иначе ValueError."""
    if isinstance(v, datetime):  # раньше date: datetime — его подкласс
        return v.timestamp(), v.timestamp()
    if isinstance(v, date):
        return (datetime.combine(v, dtime()).timestamp(),
                datetime.combine(v + timedelta(days=1), dtime()).timestamp())
    if isinstance(v, str):
        s = v.strip().replace("T", " ")
        with contextlib.suppress(ValueError):
            return _cap_moment(datetime.strptime(s, "%Y-%m-%d %H:%M"))
        with contextlib.suppress(ValueError):
            return _cap_moment(datetime.strptime(s, "%Y-%m-%d").date())
    raise ValueError(f"срок {str(v)[:40]!r} — не дата")


def cap_read(t, m=None):
    """(потолок, пометка) из [limits.owner_cap] на момент t. Потолок — {"pct", "decision", "scope"} или None; пометка —
    почему не действует ("" — раздела нет). m — замер (нужен сброс недели для until = "reset"), иначе считается."""
    try:
        lim = P.load_schedule().get("limits")
    except Exception as e:  # noqa: BLE001 — нет или битый schedule.toml: как без потолка
        return None, f"schedule.toml не прочитать ({type(e).__name__})"
    c = lim.get("owner_cap") if isinstance(lim, dict) else None
    if c is None:
        return None, ""
    if not isinstance(c, dict):
        return None, "запись [limits.owner_cap] не разобрана: не таблица"
    pct = c.get("pct")
    if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not math.isfinite(pct) or not 0 < pct <= 100:
        return None, "запись [limits.owner_cap] не разобрана: pct — не число от 0 до 100"
    cap = {"pct": float(pct), "decision": " ".join(str(c.get("decision") or "").split())[:80], "scope": "каждую неделю"}
    try:
        if c.get("date") is not None:  # старый вид (metis-0275): один день
            a, b = _cap_moment(c["date"])
            if not a <= t < b:
                return None, f"потолок на {datetime.fromtimestamp(a).strftime('%d.%m')} — не сегодня"
            cap["scope"] = f"на {datetime.fromtimestamp(a).strftime('%d.%m')}"
            return cap, ""
        since = _cap_moment(c["since"]) if c.get("since") is not None else None
        if since and t < since[0]:
            return None, f"действует с {P.stamp(since[0])}"
        u = c.get("until")
        if u is None:
            return cap, ""
        if u == "reset":
            if since is None:
                return None, "запись [limits.owner_cap] не разобрана: until = \"reset\" без since — неизвестно, какая неделя"
            r = (m if m is not None else measure(t)).get("resets")
            # неделя началась позже конца since (дата — конец суток, время — этот момент; допуск часа: сброс в снимке
            # гуляет) — потолок прошлой недели истёк. Дата дня сброса, записанная после часа сброса, держит до
            # следующего сброса: потолок только сужает, неоднозначный день лучше продлить (metis-0403, argus B)
            if r and r - WEEK > since[1] + 3600:
                return None, f"истёк: до сброса недели после {P.stamp(since[0])[:10]}"
            cap["scope"] = "до сброса недели" + (f" ({when(r)})" if r and r > t else "")
            return cap, ""
        a, b = _cap_moment(u)
        if t >= b:
            return None, f"истёк {datetime.fromtimestamp(b - 1).strftime('%d.%m')}"
        cap["scope"] = f"каждую неделю по {datetime.fromtimestamp(b - 1).strftime('%d.%m')}"
        return cap, ""
    except (ValueError, TypeError, OverflowError, OSError) as e:
        return None, f"запись [limits.owner_cap] не разобрана: {str(e)[:80]}"


def owner_cap(t, m=None):
    """Действующий потолок владельца на момент t ({"pct", "decision", "scope"}) или None."""
    return cap_read(t, m)[0]


def cap_hit(m, cap, t):
    """Потолок достигнут: неделя по снимку ≥ pct, сброс в будущем. Старый снимок годится — расход недели не убывает."""
    return (bool(cap) and m.get("used") is not None and bool(m.get("resets")) and m["resets"] > t
            and m["used"] >= cap["pct"])


def cap_why(m, cap):
    return (f"недельный потолок владельца {num(cap['pct'])} % достигнут: неделя {num(m['used'])} %"
            + (f" (решение {cap['decision']})" if cap["decision"] else ""))


def cap_notice(t, m, cap):
    """Одна тревога (с уведомлением) и одна карточка Зевсу «Ждёт вас» на неделю и pct: стоять до сброса или поднять
    до pct + 10 %. Только главный Mac и не пробный запуск. → id карточки или None."""
    if os.environ.get("PANTHEON_DRYRUN") == "1" or not primary():
        return None
    key = f"{round(m['resets'] / 3600)}-{num(cap['pct'])}"
    why = cap_why(m, cap)
    reset = when(m["resets"])
    up = min(100.0, cap["pct"] + 10)
    tid = None
    with P.lock("owner-cap"):
        sp = P.path("owner-cap.json")
        st = P.read_json(sp, {})
        st = st if isinstance(st, dict) else {}
        if st.get("key") == key:
            return st.get("card_id")
        title = f"Решить: стоять до сброса недели или поднять потолок до {num(up)} %"
        stay = f"А — стоять до сброса недели ({reset}): новых запусков и исполнителей нет, идущие доделывают шаг"
        raise_ = (f"Б — поднять потолок до {num(up)} %: потолок перестанет закрывать запуски раньше {num(up)} % недели; "
                  f"самозапуск и подъём окон при этом открыты только в зелёной зоне недели, исполнители окон — до "
                  f"{num(up)} %. Цена: меньше запаса до сброса")
        try:
            tid, _ = P.tasks_mod().task_new(
                P.PANTHEON, t, "inbox", title, owner="zeus", status="waiting", waiting_on="human",
                next="ответ владельца: стоять или поднять потолок", question=title,
                why=(f"Неделя {num(m['used'])} % при вашем потолке {num(cap['pct'])} % ({cap['scope']}"
                     + (f", решение {cap['decision']}" if cap["decision"] else "") + "). Самозапуск, подъём окон и "
                     "новые исполнители и argus из окон координаторов стоят; начатое не прерывается."),
                options=[stay, raise_], recommend=stay.split(" — ")[0] + " — так вы решили" + (
                    f" [{cap['decision']}]" if cap["decision"] else ""),
                if_no_answer=f"Без ответа новые запуски стоят до сброса недели ({reset}); на новой неделе потолок "
                             "снова действует.", actor="плановый проход")
        except Exception as e:  # noqa: BLE001 — шлюз не падает из-за карточки; повтор — следующим проходом
            P.alert_daily("owner-cap-card", f"карточку о потолке владельца не завести: {type(e).__name__}: "
                                            f"{str(e)[:120]}", "night")
        else:
            P.write_json(sp, {"key": key, "card_id": tid, "at": P.stamp(t), "pct": cap["pct"], "used": m["used"]})
    text = f"{why} — новые запуски стоят до сброса недели ({reset})" + (f", вопрос владельцу {tid}" if tid else "")
    P.alert_once("owner-cap", key, text, "night", note=text)
    return tid


def primary():
    """Вечер и ночь — только на главном Mac (как самозапуск): два Mac открыли бы две ночи и запустили пачки дважды."""
    try:
        ph = P.load_schedule().get("primary_host")
    except Exception:  # noqa: BLE001
        ph = None
    return bool(ph) and P.host() == ph


# --- снимок лимита -----------------------------------------------------------------------------------------------

def _text(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _nums(line):
    parts = line.split()
    try:
        vals = [float(x) for x in parts[:3]]
    except ValueError:
        return None
    return vals if len(vals) == 3 else None


def statusline_dir():
    return os.path.dirname(P.LIMIT_SNAPSHOT)


def week_lines():
    """Строки week-usage: [(now, resets_at, pct)] в порядке файла, кривые пропущены."""
    out = []
    for ln in _text(os.path.join(statusline_dir(), "week-usage")).splitlines():
        v = _nums(ln)
        if v:
            out.append(tuple(v))
    return out


def snapshot():
    """{"five": (pct, resets, at)|None, "week": (pct, resets, at)|None, "at": время замера|None}.
    Неделя не убывает в пределах окна сброса: pct — максимум по seven-day и строкам week-usage с тем же resets_at
    (допуск 1 ч), resets и at — от самого свежего замера (простаивающее окно пишет старый pct позже других)."""
    five = _nums(_text(P.LIMIT_SNAPSHOT).strip())
    sd = _nums(_text(os.path.join(statusline_dir(), "seven-day")).strip())
    rows = [(pct, resets, now_) for now_, resets, pct in week_lines()]
    if sd:
        rows.append(tuple(sd))
    week = None
    if rows:
        # сброс с наибольшим resets_at: простаивающее окно после досрочного сброса пишет старый resets_at позже
        # новых строк, и перенос базы недели не должен идти назад (metis-0246)
        last = max(rows, key=lambda r: (round(r[1] / 3600), r[2]))
        same = [r[0] for r in rows if abs(r[1] - last[1]) <= 3600]
        week = (max(same), last[1], last[2])
    ats = [x[2] for x in (five, week) if x]
    return {"five": tuple(five) if five else None, "week": week, "at": max(ats) if ats else None}


def measure(t, cfg=None):
    """Состояние недели на момент t: known (можно ли решать по снимку), why (почему нет), stale (строка в тревоги),
    age_min, used, resets, line, over, zone."""
    lim = (cfg or config())[0]
    s = snapshot()
    m = {"known": False, "stale": False, "age_min": None, "used": None, "resets": None, "line": None, "over": None,
         "zone": None, "why": ""}
    if s["at"] is None:
        m.update(stale=True, why="лимит неизвестен (снимка нет)")
        return m
    age = max(0.0, (t - s["at"]) / 60)
    m["age_min"] = age
    m["stale"] = age > lim["snapshot_max_min"]
    w = s["week"]
    if w:
        m["used"], m["resets"] = w[0], w[1]
    if age > lim["snapshot_ok_min"]:
        m["why"] = f"лимит неизвестен ({age:.0f} мин)"
        return m
    if not w or w[1] <= t:
        m["used"], m["resets"] = None, None
        m["why"] = "новая неделя, расход неизвестен"
        return m
    line = min(100.0, max(0.0, 100.0 * (t - (w[1] - WEEK)) / WEEK))
    over = round(w[0] - line, 6)
    if over > lim["stop_pp"] or w[0] >= lim["hard_pct"]:
        zone = "red"
    elif over > lim["warn_pp"]:
        zone = "yellow"
    else:
        zone = "green"
    m.update(known=True, line=line, over=over, zone=zone)
    return m


# --- календарь ночи ----------------------------------------------------------------------------------------------

def _hm(s):
    h, mi = HM.fullmatch(s).groups()
    return int(h), int(mi)


def at(d, hm, cfg):
    """Время «ЧЧ:ММ» вечера d: раньше ask_at — уже следующие сутки."""
    h, mi = _hm(hm)
    dt = datetime.combine(d, dtime(h, mi))
    if (h, mi) < _hm(cfg[2]["ask_at"]):
        dt += timedelta(days=1)
    return dt.timestamp()


def evening(t, cfg):
    """Дата вечера, если t — между началом вечера (ask_at) и концом ночи (end), иначе None (день)."""
    lt = datetime.fromtimestamp(t)
    d = lt.date() if (lt.hour, lt.minute) >= _hm(cfg[2]["ask_at"]) else lt.date() - timedelta(days=1)
    return d if at(d, cfg[2]["ask_at"], cfg) <= t < at(d, cfg[1]["end"], cfg) else None


def night_of(t, cfg):
    """Дата вечера, если t — в ночных часах (start ≤ t < end), иначе None."""
    d = evening(t, cfg)
    return d if d and at(d, cfg[1]["start"], cfg) <= t else None


def last_evening(t, cfg):
    """Ночь для сводки: идущая (вечер или ночь) или прошлая."""
    return evening(t, cfg) or datetime.fromtimestamp(t).date() - timedelta(days=1)


def state_path(d):
    return P.path("night", f"{d.isoformat()}.json")


def load(d):
    st = P.read_json(state_path(d), {})
    base = {"asked_at": [], "card_id": None, "answer": None, "opened_at": None, "start_pct": None,
            "budget_pct": None, "skipped": None, "alerts": []}
    return {**base, **st} if isinstance(st, dict) else base


def budget(m, d, cfg):
    """(бюджет ночи в % недели, последняя ли ночь) по замеру m в момент открытия."""
    lim, nl = cfg[0], cfg[1]
    if m["resets"] - at(d, nl["start"], cfg) <= 86400:
        return round(max(0.0, min(nl["last_night_pct"], lim["hard_pct"] - m["used"])), 2), True
    total = nl["budget_pct"]
    gap = m["line"] - m["used"]
    if gap > nl["carry_after_pp"]:
        total += nl["carry_share"] * (gap - nl["carry_after_pp"])
    return round(min(total, nl["cap_pct"]), 2), False


def used_mono(st, m):
    """Расход недели без скачков назад: в том же окне сброса не меньше st["last_used"]."""
    u = m["used"]
    if (u is not None and st.get("last_used") is not None and st.get("resets_at") and m.get("resets")
            and abs(m["resets"] - float(st["resets_at"])) <= 3600):
        return max(u, float(st["last_used"]))
    return u


def spent(st, m):
    """Расход ночи в п. п. недели; неделя сбросилась посреди ночи — прошлая до сброса плюс новая."""
    if not m["known"] or st.get("start_pct") is None:
        return float(st.get("spent") or 0.0)
    if st.get("resets_at") and m["resets"] - float(st["resets_at"]) > 3600:
        sp = float(st.get("last_used") or st["start_pct"]) - float(st["start_pct"]) + m["used"]
    else:
        sp = used_mono(st, m) - float(st["start_pct"])
    return round(max(0.0, sp), 3)


def night_open(st, m, cfg):
    """(можно ли новое ночью, почему нет)."""
    if st.get("skipped"):
        return False, f"ночь пропущена ({st['skipped']})"
    if not st.get("opened_at"):
        return False, "ночь не открыта"
    if st.get("closed") or 100 in (st.get("alerts") or []):
        return False, "ночь закрыта: бюджет исчерпан"
    b = float(st.get("budget_pct") or 0)
    work = max(0.0, b - cfg[1]["check_pct"])
    sp = spent(st, m)
    if sp >= work:
        return False, f"бюджет работы ночи исчерпан: {num(sp)} из {num(work)} %"
    return True, ""


# --- запреты (контракт с awake.py) -------------------------------------------------------------------------------

def _held(name):
    """Блокировка STATE/locks/<name>.lock занята (файл не создаём: окна без записи в locks/ тоже спрашивают)."""
    try:
        fd = os.open(P.path("locks", name + ".lock"), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def heavy_count(agents=None, registry=None):
    """Тяжёлых сейчас: сессии направлений Пантеона в состоянии working (и их копии «имя (2)») плюс идущие задачи
    тика класса heavy (их блокировка job-<имя> занята). registry — для совместимости контракта: у вкладок нет
    состояния, работают ли они, не видно."""
    if agents is None:
        agents = P.agents_all() or []
    doms = P.read_json(P.path("domains.json"), {}).get("domains") or {}
    pats = [P.name_alias(d) for d in doms]
    n = sum(1 for a in agents if a.get("state") == "working"
            and any(p.fullmatch(str(a.get("name") or "")) for p in pats))
    try:
        jobs = P.load_schedule().get("job") or []
    except Exception:  # noqa: BLE001
        jobs = []
    n += sum(1 for j in jobs if j.get("class") == "heavy" and _held("job-" + j["name"]))
    return n


def gate(kind, t, agents=None, registry=None, heavy=None):
    """Можно ли сейчас начать новое: (ok, reason). kind — autostart (самозапуск), wake (подъём уснувшей), respawn
    (продолжение прерванной). reason — короткая фраза, почему нельзя (или пустая)."""
    if kind not in KINDS:
        return False, f"неизвестный вид запуска {kind}"
    cfg = config()
    m = measure(t, cfg)
    d = night_of(t, cfg)
    # недельный потолок владельца (metis-0403) — первым и для всех трёх видов, днём и ночью: только сужает, поэтому
    # ниже зоны и ночь проверяются как без него. Старый снимок годится: расход недели не убывает
    cap = owner_cap(t, m)
    if cap_hit(m, cap, t):
        cap_notice(t, m, cap)
        return False, cap_why(m, cap)
    if not m["known"]:
        # днём продолжение прерванной снимка не ждёт: «лимит неизвестен — новое не запускать» (решение 16.10) — о
        # новом; иначе без строки статуса за 30 мин встал бы любой автоподъём (решение лида 17.10)
        if kind == "respawn" and d is None:
            return True, ""
        return False, m["why"]
    if m["zone"] == "red":
        return False, f"красная зона — неделя {num(m['used'])} % при линии {num(m['line'])} %"
    if kind == "respawn":
        if d is None:
            return True, ""
        ok, why = night_open(load(d), m, cfg)
        if not ok:
            return False, why
        return morning(t, d, cfg)  # у правила утра исключения для продолжения нет (решение лида 17.10)
    if d is None and m["zone"] == "yellow":
        return False, f"жёлтая зона днём — неделя {num(m['used'])} % при линии {num(m['line'])} %"
    if heavy is None:
        heavy = heavy_count(agents, registry)
    hmax = cfg[0]["heavy_max"]
    if heavy >= hmax:
        return False, f"тяжёлых уже {heavy} из {hmax:g}"
    if d is not None:
        ok, why = night_open(load(d), m, cfg)
        if not ok:
            return False, why
        return morning(t, d, cfg)
    return True, ""


def morning(t, d, cfg):
    """После morning_after ночи d — новое только при пятичасовом лимите не выше morning_five_hour_max."""
    if t >= at(d, cfg[1]["morning_after"], cfg):
        five, top = P.limit_pct(), cfg[1]["morning_five_hour_max"]
        if five is None:
            return False, f"после {cfg[1]['morning_after']} пятичасовой лимит неизвестен"
        if five > top:
            return False, f"после {cfg[1]['morning_after']} пятичасовой лимит {num(five)} % > {top:g} %"
    return True, ""


# --- проход дежурного ----------------------------------------------------------------------------------------------

PROBE_GAP = 1800  # пробный запрос не чаще раза в 30 мин
PROBE_TIMEOUT = 120


def probe_run():
    """Один короткий запрос к дешёвой модели: строка статуса по его итогу пишет свежий снимок лимита. → код выхода.
    В тестах подменяется заглушкой; настоящий claude — только вне PANTHEON_DRYRUN."""
    import shutil
    import subprocess
    exe = shutil.which("claude", path=P.claude_env().get("PATH"))
    if os.environ.get("PANTHEON_DRYRUN") == "1" or not exe:
        return 127
    try:
        return subprocess.run([exe, "-p", "ok", "--model", "haiku", "--no-session-persistence"],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, env=P.claude_env(),
                              cwd=P.HOME, timeout=PROBE_TIMEOUT).returncode
    except (OSError, subprocess.SubprocessError):
        return 124


def probe_due(d, m, t, cfg):
    """Нужен ли пробный запрос: снимок старше snapshot_max_min (или нет), ночь вечера d одобрена и ещё идёт."""
    if not m["stale"]:
        return False
    st = load(d)
    if st.get("answer") != "да" or st.get("skipped") or st.get("closed"):
        return False
    return at(d, cfg[1]["start"], cfg) - 1800 <= t < at(d, cfg[1]["end"], cfg)


def probe(d, m, t, cfg):
    """Пробный запрос при старом снимке (не чаще PROBE_GAP). → новое измерение недели."""
    if not probe_due(d, m, t, cfg):
        return m
    path = os.path.join(P.STATE, "night", "probe.json")
    last = 0.0
    with contextlib.suppress(OSError, ValueError, TypeError, AttributeError):
        last = float(json.load(open(path, encoding="utf-8")).get("at") or 0)
    if 0 <= t - last < PROBE_GAP:
        return m
    os.makedirs(os.path.dirname(path), exist_ok=True)
    P.write_json(path, {"at": t})  # до запуска: упавший или зависший зонд не повторяется чаще PROBE_GAP
    rc = probe_run()
    m2 = measure(t, cfg)
    if m2["stale"]:
        P.alert_once("night-probe", d.isoformat(), f"зонд не освежил снимок недельного лимита (код {rc}, снимок "
                     + (f"{m2['age_min']:.0f} мин" if m2["age_min"] is not None else "не найден")
                     + ") — ночь " + d.strftime("%d.%m") + " не открывается, пока строка статуса не запишет снимок", "night")
    else:
        P.clear_once("night-probe")
    return m2


def watch(agents=None, registry=None, doms=None, t=None):
    """Проверка «ночь» дежурного (раз в 5 мин): метрики, давность снимка, зона, вечер и ночь."""
    t = P.now() if t is None else t
    cfg = config()
    metrics(t)
    if not primary():  # снимок и ночь — у главного Mac; второй не шумит своим старым снимком
        return
    m = measure(t, cfg)
    day = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
    d0 = evening(t, cfg)
    if d0 is not None:
        m = probe(d0, m, t, cfg)
    if m["stale"]:
        P.alert_once("limit-snapshot", day, "снимок недельного лимита "
                     + (f"не обновлялся {m['age_min']:.0f} мин" if m["age_min"] is not None else "не найден")
                     + " — новые запуски стоят; жива ли строка статуса (~/.local/state/claude-statusline)?", "night")
    elif m["age_min"] is not None:
        P.clear_once("limit-snapshot")
    if m["known"] and m["zone"] in ("yellow", "red"):
        what = ("днём новых запусков нет" if m["zone"] == "yellow" else "новых запусков нет, идущие работают")
        text = (f"Недельный лимит: {num(m['used'])} % при линии {num(m['line'])} % (запас {signed(m['over'])} п.п.) — "
                f"зона {ZONES[m['zone']]}: {what}")
        P.alert_once(f"limit-zone-{m['zone']}", day, text, "night", note=text)
    cap, note = cap_read(t, m)
    if note.startswith(("запись [limits.owner_cap] не разобрана", "истёк")):  # решение владельца не должно пропасть молча
        P.alert_once("owner-cap-note", note, f"потолок владельца не действует: {note}", "night", note=note)
    else:
        P.clear_once("owner-cap-note")
    if cap_hit(m, cap, t):  # карточка и тревога — и без попытки запуска в этом проходе (одна на неделю и pct)
        cap_notice(t, m, cap)
    power_check(t, cfg)
    d = evening(t, cfg)
    if d is not None:
        evening_pass(d, m, t, cfg)


def _close_card(st, t, status, result):
    with contextlib.suppress(ValueError, OSError):
        P.tasks_mod().task_set(P.PANTHEON, t, st["card_id"], {"status": status, "result": result},
                               note=result, actor="плановый проход")


def _skip(st, d, t, why):
    st["skipped"] = why
    P.alert(f"ночь {d.strftime('%d.%m')} пропущена: {why}", "night")
    if st.get("card_id"):
        _close_card(st, t, "dropped", f"Ночь пропущена: {why}")
    for oid in st.get("pack_jobs") or []:  # одобренные пачки этой ночи не запускаются
        oneshot_cancel(oid, t, f"ночь пропущена: {why}")


# --- ночные пачки (metis-0284) -------------------------------------------------------------------------------------

def _sha(p):
    try:
        with open(p, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def packs(d):
    """Ночные пачки вечера d: [{direction, path (от ~/ai/pantheon), sha, start «ЧЧ:ММ»|None, tasks}] — по одной на
    направление из domains.json: directions/<направление>/night-<d+1 или d>-pack.md. Пачка, одобренная прошлой ночью
    (packs в её состоянии), не берётся: её дата — утро этого же дня."""
    doms = P.read_json(P.path("domains.json"), {}).get("domains") or {}
    prev = load(d - timedelta(days=1))
    used = {p.get("path") for p in prev.get("packs") or []} if prev.get("answer") == "да" else set()
    out = []
    for name in sorted(doms):
        for dd in (d + timedelta(days=1), d):
            rel = f"directions/{name}/night-{dd.isoformat()}-pack.md"
            full = os.path.join(P.PANTHEON, rel)
            if rel in used or os.path.islink(full) or not os.path.isfile(full):
                continue
            text = _text(full)
            mm = PACK_START.search(text)
            ids = []
            for ln in text.splitlines():
                if ln.lstrip().startswith("|"):
                    ids += [x for x in PACK_TASK.findall(ln) if x not in ids]
            out.append({"direction": name, "path": rel, "sha": _sha(full),
                        "start": f"{mm.group(1)}:{mm.group(2)}" if mm else None, "tasks": ids[:20]})
            break
    return out


def pack_word(pk):
    return pk["path"].split("/", 1)[-1]  # <направление>/night-…-pack.md


def pack_text(st, d, pk):
    """Задание координатору: одобренная пачка. Согласие владельца — его ответ в журнале owner-log, а не этот текст."""
    full = os.path.join(P.PANTHEON, pk["path"])
    home = P.HOME.rstrip(os.sep) + os.sep
    if full.startswith(home):  # только приставка: HOME в середине пути не трогаем
        full = "~/" + full[len(home):]
    return (f"[Пантеон: ночная пачка] Ночь {d.strftime('%d.%m')}: плановый проход запускает пачку {full} (её одобрил "
            "владелец ответом в окне вопросов, sha256 сверен; держат бюджет ночи и потолок недели). Прочитай её целиком и работай только "
            "по ней: состав, порядок, исполнители, стоп-условия; другие задачи ночью не бери. Этот текст — задание "
            "планового прохода, а не согласие владельца: решения, которые требуют его слова, — вопросом Зевсу.")


def pack_schedule(st, d, t, cfg):
    """Одобренные пачки вечера: разовый запуск координатора каждой пачки в начале ночи (не раньше start ночи и
    строки «Старт — ЧЧ:ММ» пачки), срок — конец ночи. Один раз на пачку: pack_jobs[i] — запуск packs[i]."""
    jobs = list(st.get("pack_jobs") or [])
    if len(jobs) >= len(st.get("packs") or []):
        return
    start_t, end_t = at(d, cfg[1]["start"], cfg), at(d, cfg[1]["end"], cfg)
    for pk in st["packs"][len(jobs):]:
        when = start_t
        if pk.get("start"):
            when = max(start_t, at(d, pk["start"], cfg))
        jobs.append(oneshot_add(pk["direction"], when, pack_text(st, d, pk), "night", expires=end_t,
                                pack=pk["path"], sha=pk["sha"], night=d.isoformat(), t=t))
        P.alert(f"ночь {d.strftime('%d.%m')}: пачка {pack_word(pk)} одобрена — запуск {pk['direction']} в "
                f"{P.stamp(when)[11:]}", "night")
    st["pack_jobs"] = jobs


# --- вопрос о ночной пачке (решение владельца 28.10, вариант Б) -----------------------------------------------------
NIGHT_ID = r"[a-z0-9][a-z0-9-]{0,40}"
NIGHT_PACK = r"directions/[a-z][a-z0-9-]{0,40}/night-\d{4}-\d{2}-\d{2}-pack\.md"
# похоже на вопрос о ночи — тогда запись разбирается и при несовпадении с шаблоном даёт отказ в тревогах
NIGHT_HINT = re.compile(r"вопрос: \[([^\]\s]{1,40})\]\s*ночь(?![а-яё])", re.I)


def night_question(qid, d, rel, sha):
    """(вопрос, вариант «Да», вариант «Нет») — единственный вид, по которому открывается ночь."""
    ds = d.isoformat()
    return f"[{qid}] Ночь {ds}: пачка {rel} sha256 {sha}?", f"Да — ночь {ds}", "Нет"


def night_parse(body, d):
    """Тело записи «окно вопросов» → (id, путь, sha, да, почему нет) или None — не вопрос о ночи вечера d."""
    lines = body.split("\n")
    h = NIGHT_HINT.match(lines[0]) if lines else None
    if not h:
        return None
    m = re.fullmatch(rf"вопрос: \[({NIGHT_ID})\] Ночь (\d{{4}}-\d{{2}}-\d{{2}}): пачка ({NIGHT_PACK}) sha256 ([0-9a-f]{{64}})\?",
                     lines[0])
    ans = lines[1][len("ответ: "):] if len(lines) > 1 and lines[1].startswith("ответ: ") else ""
    if not m:
        return h.group(1).lower(), "?", "", False, "вопрос не по шаблону pantheon night ask"
    qid, ds, rel, sha = m.groups()
    if ds != d.isoformat():
        return None  # вопрос о другой ночи
    yes = night_question(qid, d, rel, sha)[1]
    if len(lines) != 2 or not ans:
        return qid, rel, sha, False, "в записи есть заметка или свой текст — исполняю только чистый выбор"
    if ans == "Нет":
        return qid, rel, sha, False, ""
    if ans != yes:
        return qid, rel, sha, False, f"ответ «{ans[:60]}», а не «{yes}»"
    return qid, rel, sha, True, ""


def night_answers(d, t):
    """Записи «окно вопросов» о ночи вечера d из zeus.md (с полуночи накануне вечера до t) → [(ключ, «ГГГГ-ММ-ДД
    ЧЧ:ММ:СС», время, id, путь, sha, да, почему нет)], старые первыми."""
    try:
        text = open(P.path("owner-log", "zeus.md"), encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        return []
    lo = datetime.combine(d - timedelta(days=1), dtime(0, 0)).timestamp()
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    out = []
    for i, m in enumerate(heads):
        if not P.answers_mod().is_answer_head(m.group(2)):
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue
        if ts < lo or ts > t + 60:
            continue
        # ответ в чате (metis-0405) — без служебных строк «вариант:», «дословно:»: сверка та же, что у окна вопросов
        r = night_parse(P.answers_mod().answer_body(
            m.group(2), text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()), d)
        if r:
            out.append((f"{m.group(1)}|{r[0]}|{r[1]}", m.group(1), ts) + r)
    return out


def night_approve(st, d, t):
    """Ваши ответы о пачках этой ночи → одобренные пачки (packs) и answer «да». Каждая запись — один раз."""
    seen = list(st.get("answers_seen") or [])
    cur = {pk["path"]: pk for pk in packs(d)}
    have = {pk.get("path") for pk in st.get("packs") or []}
    dd = d.strftime("%d.%m")
    for key, stamp, ts, qid, rel, sha, yes, why in night_answers(d, t):
        if key in seen:
            continue
        seen.append(key)
        if not yes:
            if why:
                P.alert(f"ночь {dd}: ответ в окне вопросов ({stamp}, [{qid}]) не исполняю: {why}", "night")
            continue
        if rel in have:
            continue
        pk = cur.get(rel)
        if pk is None:
            P.alert(f"ночь {dd}: ответ «да» ({stamp}, [{qid}]) — пачки {rel} нет или она уже шла прошлой ночью; "
                    "ночь по ней не открываю", "night")
            continue
        if pk["sha"] != sha:
            P.alert(f"ночь {dd}: пачка {pack_word(pk)} изменилась после вашего ответа ({stamp}, [{qid}]) — не запускаю; "
                    "нужен новый вопрос (pantheon night ask)", "night")
            continue
        st["packs"] = list(st.get("packs") or []) + [pk]
        have.add(rel)
        if st.get("answer") != "да":
            st.update(answer="да", answer_at=ts)
        P.alert(f"ночь {dd}: пачка {pack_word(pk)} одобрена вашим ответом ({stamp}, [{qid}])", "night")
    st["answers_seen"] = seen[-200:]


def night_ask_cmd(rest, t=None):
    """pantheon night ask <id> <направление> [ГГГГ-ММ-ДД] — вопрос и варианты для окна вопросов Зевса."""
    t = P.now() if t is None else t
    cfg = config()
    if (not 2 <= len(rest) <= 3 or not re.fullmatch(NIGHT_ID, rest[0])
            or not re.fullmatch(r"[a-z][a-z0-9-]{0,40}", rest[1])):
        print("pantheon night ask <id> <направление> [ГГГГ-ММ-ДД] — id и имя строчными", file=P.sys.stderr)
        return 2
    try:
        d = date.fromisoformat(rest[2]) if len(rest) == 3 else (evening(t, cfg) or datetime.fromtimestamp(t).date())
    except ValueError:
        print(f"pantheon night ask: дата «{rest[2]}» не ГГГГ-ММ-ДД", file=P.sys.stderr)
        return 2
    pk = [x for x in packs(d) if x["direction"] == rest[1]]
    if not pk or not pk[0]["sha"]:
        print(f"pantheon night ask: у {rest[1]} нет ночной пачки на ночь {d.isoformat()} "
              f"(directions/{rest[1]}/night-<дата>-pack.md, направление — из domains.json)", file=P.sys.stderr)
        return 2
    q, yes, no = night_question(rest[0], d, pk[0]["path"], pk[0]["sha"])
    print(f"вопрос: {q}\nварианты: {yes} | {no}\n(вопрос и варианты — дословно, без пояснений: иначе плановый проход "
          "откажет; пачку после вопроса не менять — изменённая не запускается)")
    return 0


def pack_night(t, cfg=None):
    """Одобренные пачки вечера, идущего в момент t (от ask_at до конца ночи), или [] — тогда самозапуск по отметкам."""
    cfg = cfg or config()
    d = evening(t, cfg)
    if d is None:
        return []
    st = load(d)
    return list(st.get("packs") or []) if st.get("answer") == "да" and not st.get("skipped") else []


# --- разовые запуски (metis-0284) ----------------------------------------------------------------------------------

def oneshot_path():
    return P.path("oneshot.json")


def oneshot_items():
    items = P.read_json(oneshot_path(), {}).get("items")
    return [x for x in items if isinstance(x, dict) and x.get("id")] if isinstance(items, list) else []


def _oneshot_save(items, t):
    keep = [x for x in items if not x.get("done_at") or t - float(x["done_at"]) < ONESHOT_KEEP]
    P.write_json(oneshot_path(), {"items": keep})


def oneshot_add(target, when, text, by, expires=None, t=None, **extra):
    """Записать разовый запуск; тот же id ещё не погашен — вернуть его, второй не ставить. → id."""
    t = P.now() if t is None else t
    # номер зависит от источника: пачка ночи (by=night) — «pack-…», ручной --at — «at-…»; иначе ручной запуск на ту же
    # минуту и цель молча съедал бы пачку (ревью argus, #78): запись возвращалась чужая, без pack и sha
    oid = f"{'pack' if by == 'night' else 'at'}-{datetime.fromtimestamp(when).strftime('%Y%m%d-%H%M')}-{target}"
    with P.lock("oneshot"):
        items = oneshot_items()
        if any(x["id"] == oid and not x.get("done_at") for x in items):
            return oid
        items = [x for x in items if x["id"] != oid]
        items.append({"id": oid, "target": target, "at": float(when),
                      "expires": float(expires if expires is not None else when + ONESHOT_TTL), "text": text,
                      "by": by, "created": P.stamp(t), "done_at": None, "result": None, "wait": None, **extra})
        _oneshot_save(items, t)
    return oid


def oneshot_update(oid, t, **fields):
    """Поправить запись под блокировкой. Погасить — done_at; погашенную второй раз не гасим: → False."""
    with P.lock("oneshot"):
        items = oneshot_items()
        hit = next((x for x in items if x["id"] == oid), None)
        if hit is None or (fields.get("done_at") and hit.get("done_at")):
            return False
        hit.update(fields)
        _oneshot_save(items, t)
    return True


def oneshot_cancel(oid, t, why):
    return oneshot_update(oid, t, done_at=t, result=f"отменён: {why}")


def oneshot_due(t):
    """Непогашенные записи, чьё время пришло, по времени."""
    return sorted((x for x in oneshot_items() if not x.get("done_at") and float(x.get("at") or 0) <= t),
                  key=lambda x: float(x["at"]))


def parse_at(s, t):
    """«ЧЧ:ММ» — ближайшее такое время после t; «ГГГГ-ММ-ДД ЧЧ:ММ» (или через T) — это время, не в прошлом."""
    s = s.strip().replace("T", " ")
    if HM.fullmatch(s):
        h, mi = _hm(s)
        dt = datetime.combine(datetime.fromtimestamp(t).date(), dtime(h, mi))
        if dt.timestamp() <= t:
            dt += timedelta(days=1)
        return dt.timestamp()
    try:
        when = datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()
    except ValueError:
        raise ValueError(f"время «{s}» — ЧЧ:ММ или ГГГГ-ММ-ДД ЧЧ:ММ") from None
    if when <= t:
        raise ValueError(f"время {s} уже прошло")
    return when


def oneshot_lines(t=None):
    t = P.now() if t is None else t
    out = []
    for x in sorted(oneshot_items(), key=lambda x: float(x.get("at") or 0)):
        if x.get("done_at"):
            if t - float(x["done_at"]) < 86400:
                out.append(f"{x['id']}: {x.get('result') or 'погашен'}")
            continue
        out.append(f"{x['id']}: {x['target']} в {P.stamp(float(x['at']))}, срок {P.stamp(float(x['expires']))[11:]}"
                   + (f" — ждёт: {x['wait']}" if x.get("wait") else ""))
    return out


# --- питание (metis-0284) ------------------------------------------------------------------------------------------

def power():
    """(заряд %|None, на зарядке) по `pmset -g batt`; PANTHEON_FAKE_AC/PANTHEON_FAKE_BATT — подмена в тестах.
    Не прочитать — (None, True): тревоги нет."""
    if os.environ.get("PANTHEON_FAKE_AC") is not None or os.environ.get("PANTHEON_FAKE_BATT") is not None:
        pct = None
        with contextlib.suppress(ValueError):
            pct = float(os.environ.get("PANTHEON_FAKE_BATT") or "")
        return pct, os.environ.get("PANTHEON_FAKE_AC", "1") == "1"
    import subprocess
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None, True
    m = re.search(r"(\d{1,3})%", out)
    return (float(m.group(1)) if m else None), ("AC Power" in out or "Battery Power" not in out)


def power_check(t, cfg):
    """С power_at до ask_at, если ночь вечера не пропущена: на батарее ниже batt_min — тревога и уведомление, одна
    за вечер."""
    ask = cfg[2]
    d = datetime.fromtimestamp(t).date()
    a = datetime.combine(d, dtime(*_hm(ask["power_at"]))).timestamp()
    if not (a <= t < at(d, ask["ask_at"], cfg)) or load(d).get("skipped"):
        return
    pct, ac = power()
    if ac or pct is None or pct >= ask["batt_min"]:
        return
    text = (f"Mac на батарее, заряд {pct:.0f} % — подключите зарядку до ночи: без неё ночная работа встанет "
            f"(порог {ask['batt_min']:g} %)")
    P.alert_once("night-power", d.isoformat(), text, "night", note=text)


def evening_pass(d, m, t, cfg):
    st = load(d)
    before = json.dumps(st, sort_keys=True)
    ask_t = at(d, cfg[2]["ask_at"], cfg)
    start_t, end_t = at(d, cfg[1]["start"], cfg), at(d, cfg[1]["end"], cfg)
    if not st["skipped"] and ask_t <= t < end_t and st.get("answer") in (None, "да"):
        # решение владельца 28.10 (вариант Б): ночь — только по вашему ответу на вопрос о пачке (pantheon night ask);
        # пачка с другим sha256, чем в вопросе, не одобряется, изменённая после этого — не запускается (oneshots)
        if st.get("card_id") and not st.get("card_closed"):  # карточка вопроса, заданного до выпуска: снимаем
            _close_card(st, t, "dropped", "Вопрос на ночь снят: ночь — по вашему ответу на вопрос о ночной пачке")
            st["card_closed"] = True
        night_approve(st, d, t)
        pack_schedule(st, d, t, cfg)
    if st["answer"] == "да" and not st["skipped"] and not st["opened_at"] and start_t <= t < end_t and m["known"]:
        b, last_night = budget(m, d, cfg)
        if b <= 0:
            _skip(st, d, t, "бюджета нет: неделя у порога")
        else:
            st.update(opened_at=max(float(st["answer_at"]), start_t), start_pct=m["used"], budget_pct=b,
                      resets_at=m["resets"], last_used=m["used"], spent=0.0, last_night=last_night)
            P.alert(f"ночь {d.strftime('%d.%m')} открыта с {P.stamp(st['opened_at'])[11:]}: бюджет {num(b)} % недели"
                    + (" (последняя ночь перед сбросом)" if last_night else ""), "night")
    # замер со сбросом раньше сохранённого больше чем на час — старая неделя (простаивающее окно, усечённый
    # week-usage): расход ночи не пересчитываем (только вперёд, metis-0246)
    backward = bool(st.get("resets_at") and m["resets"] and m["resets"] < float(st["resets_at"]) - 3600)
    if st["opened_at"] and not st["skipped"] and m["known"] and not backward:
        st["spent"] = spent(st, m)
        if st.get("resets_at") and m["resets"] - float(st["resets_at"]) > 3600:  # только вперёд (metis-0246)
            # неделя сбросилась посреди ночи: база переносится, чтобы следующие проходы считали used − start_pct
            st["start_pct"] = float(st["start_pct"]) - float(st.get("last_used") or st["start_pct"])
        st["last_used"], st["resets_at"] = used_mono(st, m), m["resets"]
        b = float(st["budget_pct"])
        for th in THRESHOLDS:
            if st["spent"] >= b * th / 100 - 1e-9 and th not in st["alerts"]:
                st["alerts"].append(th)
                text = (f"Ночь {d.strftime('%d.%m')}: потрачено {num(st['spent'])} из {num(b)} % недели ({th} %)"
                        + (" — ночь закрыта для нового" if th == 100 else ""))
                P.alert_once(f"night-{d.isoformat()}-{th}", d.isoformat(), text, "night", note=text)
                if th == 100:
                    st["closed"] = True
    if json.dumps(st, sort_keys=True) != before:
        P.write_json(state_path(d), st)


# --- метрики -----------------------------------------------------------------------------------------------------

def metrics(t):
    """week-usage → STATE/metrics/week-usage.log (дописывание, по последнему now); смена недели → weeks.jsonl."""
    log = P.path("metrics", "week-usage.log")
    last = None
    for ln in reversed(_text(log).splitlines()):
        v = _nums(ln)
        if v:
            last = v[0]
            break
    new = [w for w in week_lines() if last is None or w[0] > last]
    if new:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            for w in new:
                fh.write(f"{w[0]:.0f} {w[1]:.0f} {w[2]:g}\n")
    w = snapshot()["week"]
    if not w:
        return
    pct, resets, seen = w
    cp = P.path("metrics", "week-current.json")
    cur = P.read_json(cp, {})
    if cur.get("resets_at") and resets - float(cur["resets_at"]) > 3600:
        rec = {"week_end": P.stamp(float(cur["resets_at"])), "resets_at": float(cur["resets_at"]),
               "final_pct": cur.get("pct"), "seen_at": P.stamp(float(cur.get("at") or 0)),
               "nights": nights_between(float(cur["resets_at"]) - WEEK, float(cur["resets_at"]))}
        with open(P.path("metrics", "weeks.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        cur = {}
    if not cur or (seen > float(cur.get("at") or 0) and abs(resets - float(cur["resets_at"])) <= 3600):
        P.write_json(cp, {"resets_at": resets, "pct": pct, "at": seen})


def nights_between(a, b):
    cfg = config()
    out = []
    with contextlib.suppress(OSError):
        for f in sorted(os.listdir(P.path("night"))):
            mm = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.json", f)
            if not mm:
                continue
            d = date.fromisoformat(mm.group(1))
            if a <= at(d, cfg[1]["start"], cfg) < b:
                st = load(d)
                out.append({"date": d.isoformat(), "opened": bool(st.get("opened_at")), "skipped": st.get("skipped"),
                            "budget_pct": st.get("budget_pct"), "spent": st.get("spent"), "alerts": st.get("alerts")})
    return out


# --- вывод ---------------------------------------------------------------------------------------------------------

def num(x):
    """Число по-русски: 1,2 · 3 · −2."""
    s = f"{float(x):.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return ("−" + s[1:] if s.startswith("-") else s) if s not in ("-0", "−0") else "0"


def signed(x):
    s = num(x)
    return s if s.startswith("−") or s == "0" else "+" + s


def when(ts):
    lt = datetime.fromtimestamp(ts)
    return f"{DAYS[lt.weekday()]} {lt.strftime('%H:%M')}"


def week_line(m):
    if m["known"]:
        return (f"Неделя: {num(m['used'])} % · линия {num(m['line'])} % · запас {signed(m['over'])} п.п. · "
                f"зона: {ZONES[m['zone']]} · сброс {when(m['resets'])}")
    if m["used"] is not None and m["resets"]:
        return f"Неделя: {num(m['used'])} % по старому снимку · зона неизвестна · сброс {when(m['resets'])}"
    return "Неделя: расход неизвестен — новые запуски стоят"


NIGHT_CLOSED = "не открыта — только по вашему ответу на вопрос о пачке (pantheon night ask)"


def night_line(st, d, t, cfg, now_night=True):
    if st.get("skipped"):
        return f"пропущена ({st['skipped']})"
    if st.get("opened_at"):
        s = (f"открыта с {P.stamp(float(st['opened_at']))[11:]}, потрачено {num(st.get('spent') or 0)} из "
             f"{num(st['budget_pct'])} %")
        if st.get("closed"):
            s += " — закрыта: бюджет исчерпан"
        return s
    if st.get("answer") == "да":
        return (f"откроется в {cfg[1]['start']}, пачки: {', '.join(pack_word(x) for x in st.get('packs') or [])}"
                if now_night else "не открылась (лимит недели неизвестен)")
    return NIGHT_CLOSED


def status_lines(t=None):
    t = P.now() if t is None else t
    cfg = config()
    m = measure(t, cfg)
    d = evening(t, cfg)
    night = night_line(load(d), d, t, cfg) if d else NIGHT_CLOSED
    return ([week_line(m), "Ночь: " + night, snap_line(m, cfg), cap_line(t, m)]
            + [f"Разовый запуск {x}" for x in oneshot_lines(t)])


def cap_line(t, m):
    """Потолок владельца и запас до него (п. п.) — или почему его нет."""
    cap, note = cap_read(t, m)
    if cap is None:
        return "Потолок владельца: " + (f"не действует — {note}" if note else "нет")
    s = f"Потолок владельца: {num(cap['pct'])} % {cap['scope']}" + (
        f" · решение {cap['decision']}" if cap["decision"] else "")
    if cap_hit(m, cap, t):
        return s + f" · достигнут (неделя {num(m['used'])} %) — новые запуски и исполнители стоят"
    if m["used"] is None or not m["resets"] or m["resets"] <= t:
        return s + " · запас неизвестен (расхода недели нет)"
    return s + f" · запас {num(cap['pct'] - m['used'])} п.п."


def agent_gate(t=None):
    """Хук PreToolUse Agent|Task: причина отказа запуску субагента в окне координатора или штаба при достигнутом
    потолке или None. Окно — по PANTHEON_ROLE (CAP_ROLES: domain-coordinator, workshop, hq); окна задач и терминал
    владельца — None."""
    role = os.environ.get("PANTHEON_ROLE") or ""
    if role not in CAP_ROLES:
        return None
    t = P.now() if t is None else t
    m = measure(t)
    cap = owner_cap(t, m)
    if not cap_hit(m, cap, t):
        return None
    if role == "hq":  # Зевс — он: отвечает владельцу сам, без субагентов
        return (f"Пантеон: {cap_why(m, cap)}. Субагентов не запускай до сброса недели ({when(m['resets'])}) или "
                "нового слова владельца: отвечай владельцу сам, без них. Поднять потолок может только владелец — "
                "вопрос ему уже на доске.")
    return (f"Пантеон: {cap_why(m, cap)}. Новых исполнителей, лидов и argus не запускай до сброса недели "
            f"({when(m['resets'])}) или нового слова владельца: доделай текущий шаг без них, запиши в файл состояния, "
            "где остановилась и что ждёт запуска. Поднять потолок может только владелец — вопрос ему уже на доске.")


def launch_cap(origin, over=False, t=None):
    """Ручной запуск и задача `claude -p` тика при достигнутом потолке (metis-0444): причина отказа или None.
    origin — owner (ваш терминал), zeus (окно штаба), tick (плановый проход и другие окна ролей). over — флаг
    --over-cap: снимает отказ только у owner. Достигнут — ещё карточка и тревога (cap_notice, одна на неделю и pct).
    Сбой расчёта — не отказ: строка в stderr и одна тревога в день (как у agent-gate)."""
    t = P.now() if t is None else t
    try:
        m = measure(t)
        cap = owner_cap(t, m)
        if not cap_hit(m, cap, t) or (over and origin == "owner"):
            return None
        cap_notice(t, m, cap)
        why = f"{cap_why(m, cap)}, новые запуски стоят до сброса недели ({when(m['resets'])})"
    except Exception as e:  # noqa: BLE001 — потолок не проверен: запуск идёт, сбой виден
        text = f"потолок владельца не проверен ({type(e).__name__}: {str(e)[:120]}) — запуск идёт без него"
        print(f"pantheon: {text}", file=P.sys.stderr)
        with contextlib.suppress(Exception):
            P.alert_daily("owner-cap-check", text, "night")
        return None
    if origin == "owner":
        return f"{why}; запустить сверх потолка — та же команда с {OVER_CAP}"
    return (f"{why}; поднять потолок может только владелец (вопрос ему на доске)"
            + (f", {OVER_CAP} действует только в его терминале" if over else ""))


def snap_line(m, cfg):
    if m["age_min"] is None:
        return "лимит неизвестен (снимка нет)"
    if m["age_min"] <= cfg[0]["snapshot_ok_min"]:
        return f"Снимок лимита: {m['age_min']:.0f} мин назад"
    return f"лимит неизвестен ({m['age_min']:.0f} мин)"


def report_lines(t=None):
    """Блок «Лимит» ежедневной сводки: неделя, линия, запас, зона; ночь (идущая или прошлая) — открыта или пропущена,
    потрачено X из Y %, тревоги; сброс недели; давность снимка."""
    t = P.now() if t is None else t
    cfg = config()
    m = measure(t, cfg)
    d = last_evening(t, cfg)
    st = load(d)
    out = [week_line(m), cap_line(t, m)]
    nl = night_line(st, d, t, cfg, now_night=evening(t, cfg) is not None)
    al = st.get("alerts") or []
    out.append(f"Ночь {d.strftime('%d.%m')}: {nl}" + (f" · тревоги: {', '.join(f'{x} %' for x in al)}" if al else
                                                       (" · тревог нет" if st.get("opened_at") else "")))
    if m["resets"]:
        hours = max(0.0, (m["resets"] - t) / 3600)
        out.append(f"Сброс недели: {when(m['resets'])} (через {hours:.0f} ч)")
    else:
        out.append("Сброс недели: неизвестен")
    with contextlib.suppress(Exception):  # замер ММВ не должен ронять сводку
        out.append(P.mmv_mod().line(P.STATE, t=t))
    out.append(snap_line(m, cfg) + (" — снимок старше 3 ч, строка статуса не пишет?" if m["stale"] else ""))
    return out


def main(rest):
    sub = rest[0] if rest else "status"
    if sub == "status":
        for ln in status_lines():
            print(ln)
        return 0
    if sub == "report":
        print("Лимит")
        for ln in report_lines():
            print(f"  {ln}")
        return 0
    if sub == "agent-gate":  # хук PreToolUse (hooks.json): событие в stdin не нужно — решает окно и потолок
        with contextlib.suppress(OSError, ValueError):
            P.sys.stdin.read()
        try:
            why = agent_gate()
        except Exception as e:  # noqa: BLE001 — сбой расчёта не отказ (как битая запись), но виден: код 1
            print(f"pantheon night agent-gate: потолок не проверен ({type(e).__name__}: {str(e)[:120]})",
                  file=P.sys.stderr)
            return 1
        if why:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                     "permissionDecisionReason": why}}, ensure_ascii=False))
        return 0
    if sub == "ask":
        return night_ask_cmd(rest[1:])
    print("pantheon night [status|report|ask|agent-gate]", file=P.sys.stderr)
    return 2
