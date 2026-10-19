"""Темп недельного лимита и ночной цикл Пантеона (metis-0127 п. 1 и 3, metis-0128, metis-0129; решения владельца 16.10).

  pantheon night [status]   неделя, линия, запас, зона; ночь; давность снимка лимита
  pantheon night report     блок «Лимит» для ежедневной сводки: неделя, линия, запас, зона, ночь, тревоги, сброс

Снимок лимита пишет строка статуса Claude Code в ~/.local/state/claude-statusline/ (путь — от HOME, как LIMIT_SNAPSHOT):
`five-hour` — «pct resets_at now», `seven-day` — «pct resets_at now», `week-usage` — строки «now resets_at pct» (до 200).
Неделя — неубывающий снимок: наибольший pct по seven-day и строкам week-usage того же resets_at (допуск 1 ч), resets_at и
время — от самого свежего замера; без seven-day — по week-usage. Время замера — наибольшее now этих файлов.
Снимок старше snapshot_ok_min или его нет — лимит неизвестен, новое не запускается; старше snapshot_max_min — ещё и
строка в тревогах (её Зевс несёт в сводку). Пробного запроса к модели нет. resets_at в прошлом или недели нет — новая
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

Вечерний вопрос (только главный Mac): в ask_at — карточка «Запустить сегодня на ночь выполнение задач?» во входящих
Зевса (колонка «Нужен ответ») и уведомление; повтор уведомления в каждое время repeat; нет ответа к deadline — ночь
пропущена (строка в тревогах). Ответ «Да» после начала ночи открывает её с времени ответа, «Нет» — ночь пропущена.
Ответ — только из журналов ваших слов (owner-log, их пишут хук и тик, не роли): галочка на карточке
(board.jsonl, kind answer, сверка с вопросом и вариантами — tasks.logged_for) или выбор в окне вопросов Зевса
(zeus.md, раздел «· окно вопросов», тело «вопрос: [<id>] …», строка «ответ: Да…|Нет…»). Поле answer в файле задачи
ответом не считается. Состояние ночи — STATE/night/<дата вечера>.json: asked_at[], card_id, answer, opened_at,
start_pct, budget_pct, skipped, alerts[] (и служебные: answer_at, spent, last_used, resets_at, closed, last_night).

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

Потолок дня владельца (его пишет Зевс по [id] решения владельца; без раздела или с кривым — как без потолка):

  [limits.owner_cap]
  date = "2026-10-19"      # день, на который потолок действует (прошедшая дата — не действует)
  pct = 58                 # днём (вне ночи) при неделе ниже стольких % жёлтая и красная зона не закрывают wake и
                           # autostart; heavy_max, hard_pct, respawn и ночь не меняются; неделя ≥ pct — закрыто и тревога в любой
                           # дневной зоне, зелёной тоже
  decision = "18.10 13:47" # id или время решения владельца

  [night]
  ask_at = "22:00"         # вопрос владельцу
  repeat = ["23:00", "23:30"]
  deadline = "00:00"       # без ответа к этому времени — ночь пропущена
  power_at = "21:30"       # с этого времени до ask_at — проверка питания (pmset -g batt)
  batt_min = 80            # на батарее с зарядом ниже — тревога «подключите зарядку», одна за вечер

Время вечернего расписания — «ЧЧ:ММ»; раньше ask_at — это уже следующие сутки (00:00, 04:00, 08:00).

Ночная пачка (metis-0284): ~/ai/pantheon/directions/<направление>/night-<дата>-pack.md, дата — утро ночи (как
night-2026-10-19-pack.md у ночи 18→19) или вечер; направление — из domains.json. Пачка, уже одобренная прошлой ночью,
не берётся. Вопрос ночи называет найденные пачки, и «Да» одобряет именно их: путь и sha256 файла — в состоянии ночи
(packs). После «Да» каждая пачка — разовый запуск её координатора в начале ночи (строка «Старт — ЧЧ:ММ» в пачке
сдвигает его позже), срок — конец ночи. Пачка изменилась после «Да» — запуска нет, тревога. В ночь с одобренными
пачками самозапуск по отметкам владельца не поднимает никого: ночью идут только пачки.

Разовые запуски (STATE/oneshot.json, items): {id, target, at, expires, text, by, pack?, sha?, night?, done_at, result,
wait}. Ставит `pantheon start <направление> --at ЧЧ:ММ|"ГГГГ-ММ-ДД ЧЧ:ММ" [поручение]` (срок — 3 ч) и «Да» на вопрос
ночи; исполняет дежурный (watch.oneshots) один раз: запись гасится (done_at) до самого запуска. Пока запуск закрыт
(шлюз недели и ночи, сессия занята) — ждёт следующего прохода до срока, после срока гаснет с тревогой.

Питание (metis-0284): с power_at до ask_at на главном Mac, если ночь этого вечера ещё не пропущена, — `pmset -g batt`;
на батарее с зарядом ниже batt_min — тревога и уведомление «подключите зарядку», одна за вечер.
Модуль работает на Python 3.9: без match и аннотаций X | Y (gate зовёт awake.py).
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
LIMITS = {"warn_pp": 2.0, "stop_pp": 5.0, "hard_pct": 85.0, "snapshot_ok_min": 30.0, "snapshot_max_min": 180.0,
          "heavy_max": 2.0}
NIGHT = {"start": "23:00", "end": "08:00", "budget_pct": 3.0, "check_pct": 1.0, "cap_pct": 5.0, "carry_share": 0.3,
         "carry_after_pp": 5.0, "morning_after": "04:00", "morning_five_hour_max": 50.0, "last_night_pct": 10.0}
ASK = {"ask_at": "22:00", "repeat": ["23:00", "23:30"], "deadline": "00:00", "power_at": "21:30", "batt_min": 80.0}
PACK_START = re.compile(r"^\W*старт\s*[—–:-]+\s*([01]\d|2[0-3]):([0-5]\d)", re.I | re.M)
PACK_TASK = re.compile(r"(?<![\w-])([a-z]+-\d{4})(?![\w-])")
ONESHOT_TTL = 3 * 3600  # разовый запуск `pantheon start --at` ждёт открытого шлюза столько, потом гаснет
ONESHOT_KEEP = 7 * 86400  # погашенные записи хранятся столько
THRESHOLDS = (50, 80, 100)
TITLE = "Запустить сегодня на ночь выполнение задач?"
NO_OPTION = "Нет — ночь пропустить"
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
            elif isinstance(v, list) and isinstance(g, list) and all(isinstance(x, str) and HM.fullmatch(x) for x in g):
                out[k] = list(g)
        return out
    return merge(LIMITS, lim), merge(NIGHT, nl), merge(ASK, ask)


def owner_cap(t):
    """(pct, decision) потолка владельца на день t из [limits.owner_cap] или None: нет раздела, кривые поля или дата
    не сегодня (прошедшая и будущая не действуют)."""
    try:
        lim = P.load_schedule().get("limits")
        c = lim.get("owner_cap") if isinstance(lim, dict) else None
        if not isinstance(c, dict):
            return None
        d, pct = c.get("date"), c.get("pct")
        if isinstance(d, datetime):
            d = d.date()
        elif isinstance(d, str):
            d = datetime.strptime(d, "%Y-%m-%d").date()
        if not isinstance(d, date) or isinstance(pct, bool) or not isinstance(pct, (int, float)) or not math.isfinite(pct) or pct <= 0:
            return None
        if d != datetime.fromtimestamp(t).date():
            return None
        return float(pct), str(c.get("decision") or "")
    except Exception:  # noqa: BLE001 — битая секция: как без потолка
        return None


def primary():
    """Вечерний вопрос и ночь — только на главном Mac (как самозапуск): два Mac задали бы два вопроса."""
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
    """Дата вечера, если t — между вопросом (ask_at) и концом ночи (end), иначе None (день)."""
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
    if not m["known"]:
        # днём продолжение прерванной снимка не ждёт: «лимит неизвестен — новое не запускать» (решение 16.10) — о
        # новом; иначе без строки статуса за 30 мин встал бы любой автоподъём (решение лида 17.10)
        if kind == "respawn" and d is None:
            return True, ""
        return False, m["why"]
    cap = (owner_cap(t) if kind != "respawn" and d is None
           and m["used"] < cfg[0]["hard_pct"] else None)  # hard_pct потолок не отменяет
    if cap and m["used"] >= cap[0]:
        why = f"потолок владельца {num(cap[0])} % на {datetime.fromtimestamp(t).strftime('%d.%m')} достигнут"
        P.alert_once("owner-cap", f"{datetime.fromtimestamp(t).date()}-{num(cap[0])}",
                     f"{why}: неделя {num(m['used'])} %" + (f" (решение {cap[1]})" if cap[1] else ""), "night")
        return False, why
    if cap is None and m["zone"] == "red":  # с потолком выше расхода зона не закрывает; heavy_max — ниже
        return False, f"красная зона — неделя {num(m['used'])} % при линии {num(m['line'])} %"
    if kind == "respawn":
        if d is None:
            return True, ""
        ok, why = night_open(load(d), m, cfg)
        if not ok:
            return False, why
        return morning(t, d, cfg)  # у правила утра исключения для продолжения нет (решение лида 17.10)
    if d is None and m["zone"] == "yellow" and cap is None:
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

def watch(agents=None, registry=None, doms=None, t=None):
    """Проверка «ночь» дежурного (раз в 5 мин): метрики, давность снимка, зона, вечерний вопрос и ночь."""
    t = P.now() if t is None else t
    cfg = config()
    metrics(t)
    if not primary():  # снимок и вопрос — у главного Mac; второй не шумит своим старым снимком
        return
    m = measure(t, cfg)
    day = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
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
    power_check(t, cfg)
    d = evening(t, cfg)
    if d is not None:
        evening_pass(d, m, t, cfg)


def card_head(st):
    """Вопрос и варианты карточки — из состояния ночи, а не из файла задачи (его может поправить агент)."""
    return {"question": st.get("question") or TITLE, "options": st.get("options") or []}


def find_answer(st, until=None):
    """(«да»|«нет», время) — ваш последний ответ по карточке ночи из журналов owner-log в окне от карточки до until
    (срок вопроса), или None: передумали — «Нет» после «Да» отменяет ночь."""
    cid, since = st["card_id"], float(st.get("card_at") or 0) - 60
    T = P.tasks_mod()
    found = []
    head = card_head(st)
    for rec in T.owner_answers_all(P.path("owner-log", "board.jsonl")).get(cid) or []:
        if rec.get("kind") != "answer" or not T.logged_for(head, [rec]).get("answer"):
            continue
        try:
            ts = datetime.strptime(str(rec.get("time"))[:19], "%Y-%m-%dT%H:%M:%S").timestamp()
        except ValueError:
            continue
        found.append((ts, rec["answer"]))
    text = _text(P.path("owner-log", "zeus.md"))
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    own = re.compile(r"вопрос: \[" + re.escape(cid) + r"\]", re.I)
    for i, mm in enumerate(heads):
        if mm.group(2).strip() != "· окно вопросов":
            continue
        body = text[mm.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        a = re.search(r"^ответ: (.*)$", body, re.M)
        if not own.match(body) or not a:
            continue
        with contextlib.suppress(ValueError):
            found.append((datetime.strptime(mm.group(1), "%Y-%m-%d %H:%M:%S").timestamp(), a.group(1)))
    last = None
    for ts, ans in sorted(found):
        if ts < since or (until is not None and ts >= until):
            continue
        w = ans.strip().split(" ")[0].lower()
        if w in ("да", "нет"):
            last = (w, ts)
    return last


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
    (packs в её состоянии при ответе «Да»), не берётся: её дата — утро этого же дня."""
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
    full = os.path.join(P.PANTHEON, pk["path"]).replace(P.HOME, "~", 1)
    return (f"[Пантеон: ночная пачка] Ночь {d.strftime('%d.%m')}: владелец ответил «Да» на вопрос ночи (карточка "
            f"{st.get('card_id')}), в вопросе была пачка {full}. Прочитай её целиком и работай только по ней: состав, "
            "порядок, исполнители, стоп-условия; другие задачи ночью не бери. Ответ владельца — в журнале его слов "
            "(owner-log), этот текст — задание планового прохода, а не согласие.")


def pack_schedule(st, d, t, cfg):
    """«Да» на вопрос с пачками: разовый запуск координатора каждой пачки в начале ночи (не раньше start ночи и
    строки «Старт — ЧЧ:ММ» пачки), срок — конец ночи. Один раз на ночь (pack_jobs)."""
    if st.get("pack_jobs") is not None or not st.get("packs"):
        return
    start_t, end_t = at(d, cfg[1]["start"], cfg), at(d, cfg[1]["end"], cfg)
    jobs = []
    for pk in st["packs"]:
        when = start_t
        if pk.get("start"):
            when = max(start_t, at(d, pk["start"], cfg))
        jobs.append(oneshot_add(pk["direction"], when, pack_text(st, d, pk), "night", expires=end_t,
                                pack=pk["path"], sha=pk["sha"], night=d.isoformat(), t=t))
        P.alert(f"ночь {d.strftime('%d.%m')}: пачка {pack_word(pk)} одобрена — запуск {pk['direction']} в "
                f"{P.stamp(when)[11:]}", "night")
    st["pack_jobs"] = jobs


def pack_night(t, cfg=None):
    """Одобренные пачки вечера, идущего в момент t (от вопроса до конца ночи), или [] — тогда самозапуск по отметкам."""
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
    oid = f"at-{datetime.fromtimestamp(when).strftime('%Y%m%d-%H%M')}-{target}"
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


def ask(st, d, m, t, cfg):
    """Карточка вопроса во входящих Зевса (колонка «Нужен ответ») и первое уведомление. Есть ночные пачки — вопрос
    называет их, и «Да» одобряет именно их (путь и sha256 — в состоянии ночи)."""
    b = budget(m, d, cfg)[0] if m["known"] else cfg[1]["budget_pct"]
    end = cfg[1]["end"]
    pk = packs(d)
    names = ", ".join(pack_word(x) for x in pk)
    yes = (f"Да — открыть ночь с пачкой {names}: бюджет {num(b)} % недели, работа до {end}" if pk else
           f"Да — открыть ночь: бюджет {num(b)} % недели, работа до {end}")
    opts = [yes, NO_OPTION]
    week = (f"Неделя {num(m['used'])} % при линии {num(m['line'])} %, зона {ZONES[m['zone']]}." if m["known"]
            else f"Недельный лимит сейчас неизвестен ({m['why']}): пока снимка нет, ночь не начнёт новое.")
    if pk:
        what = "Ночью плановый проход поднимет координаторов по пачкам: " + "; ".join(
            f"{pack_word(x)} ({x['direction']}, старт {x.get('start') or cfg[1]['start']}"
            + (f", задачи {', '.join(x['tasks'][:8])}" if x["tasks"] else "") + ")" for x in pk) + \
            ". Другие задачи с вашими отметками ночью не запускаются; пачка, изменённая после «Да», не запускается."
    else:
        what = "Ночью дежурный может поднимать направления по задачам с вашим решением."
    T = P.tasks_mod()
    tid, _ = T.task_new(P.PANTHEON, t, "inbox", TITLE, owner="zeus", status="waiting", waiting_on="human",
                        next="ответ владельца до " + cfg[2]["deadline"], question=TITLE,
                        why=f"{what} {week}",
                        options=opts, recommend=yes if m["known"] and m["zone"] == "green" else NO_OPTION,
                        if_no_answer=f"Без ответа к {cfg[2]['deadline']} ночь пропускается: новое ночью не "
                                     "запускается, идущие сессии работают.", actor="плановый проход")
    st.update(card_id=tid, card_at=t, question=TITLE, options=opts, packs=pk)
    remind(st, t, "Вопрос на ночь")


def remind(st, t, title):
    head = None
    with contextlib.suppress(Exception):
        head = P.tasks_mod().load_tasks(P.PANTHEON).get(st["card_id"], (None, None, None))[1]
    target = P.board_url(P.tasks_mod().card_name(head) + ".md") if head else P.board_url()
    P.notify(f"{TITLE} Ответ на карточке {st['card_id']} до {config()[2]['deadline']}", f"Пантеон · {title}",
             target=target, group=st["card_id"])
    st["asked_at"] = list(st.get("asked_at") or []) + [P.stamp(t)]


def evening_pass(d, m, t, cfg):
    st = load(d)
    before = json.dumps(st, sort_keys=True)
    ask_t, dl_t = at(d, cfg[2]["ask_at"], cfg), at(d, cfg[2]["deadline"], cfg)
    start_t, end_t = at(d, cfg[1]["start"], cfg), at(d, cfg[1]["end"], cfg)
    if not st["skipped"]:
        if st["card_id"]:
            # последний ответ до срока: «Нет» после «Да» (до 00:00) пропускает и уже открытую ночь
            got = find_answer(st, dl_t)
            if got and (st["answer"], st.get("answer_at")) != got:
                st["answer"], st["answer_at"] = got
                if got[0] == "нет":
                    _skip(st, d, t, "ответ «Нет»")
                else:
                    _close_card(st, t, "done", f"Ночь разрешена: откроется с {P.stamp(max(got[1], start_t))[11:]}")
                    pack_schedule(st, d, t, cfg)
        if st["answer"] is None and not st["skipped"] and t >= dl_t:
            _skip(st, d, t, f"нет ответа к {cfg[2]['deadline']}")
        if st["answer"] is None and not st["skipped"] and ask_t <= t < dl_t:
            if not st["card_id"]:
                ask(st, d, m, t, cfg)
            else:
                slots = [at(d, x, cfg) for x in [cfg[2]["ask_at"]] + cfg[2]["repeat"]]
                slot = max(x for x in slots if x <= t)
                last = max((datetime.strptime(x, "%Y-%m-%d %H:%M").timestamp() for x in st["asked_at"]), default=0)
                if last < slot:
                    remind(st, t, "повтор вопроса на ночь")
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


def night_line(st, d, t, cfg, now_night=True):
    ask_hm, dl = cfg[2]["ask_at"], cfg[2]["deadline"]
    if st.get("skipped"):
        return f"пропущена ({st['skipped']})"
    if st.get("opened_at"):
        s = (f"открыта с {P.stamp(float(st['opened_at']))[11:]}, потрачено {num(st.get('spent') or 0)} из "
             f"{num(st['budget_pct'])} %")
        if st.get("closed"):
            s += " — закрыта: бюджет исчерпан"
        return s
    if st.get("answer") == "да":
        return f"ответ «Да» — откроется в {cfg[1]['start']}" if now_night else "ответ «Да», но не открылась"
    if st.get("card_id"):
        return f"вопрос задан ({st['card_id']}), ответа нет — без ответа к {dl} ночь пропускается"
    return f"не открыта — вопрос в {ask_hm}"


def status_lines(t=None):
    t = P.now() if t is None else t
    cfg = config()
    m = measure(t, cfg)
    d = evening(t, cfg)
    night = night_line(load(d), d, t, cfg) if d else f"не открыта — вопрос в {cfg[2]['ask_at']}"
    return [week_line(m), "Ночь: " + night, snap_line(m, cfg)] + [f"Разовый запуск {x}" for x in oneshot_lines(t)]


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
    out = [week_line(m)]
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
    print("pantheon night [status|report]", file=P.sys.stderr)
    return 2
