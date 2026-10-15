"""Умные уведомления Пантеона (metis-0023): не пиликать зря и не оставлять без внимания.

Модуль решает, что показать уведомлением macOS сейчас, что отложить в утреннюю сводку, а что оставить только на
доске. Основа — раздел 6 исследования 15.10 (присутствие, тихие часы, дайджест, склейка по id, бюджет, журнал).

- Присутствие — по простою клавиатуры и мыши: «здесь», «рядом», «нет». macOS по решениям и сбоям — только при «нет».
- Решение — карточка «Нужен ответ». Цикл по id: ответ владельца закрывает его, повторов больше нет; срок прошёл —
  «истекло»; карточка ушла без ответа — «закрыто». Повтор не раньше repeat_min, после long_wait_min — «долго ждёт»
  и тишина. Срочное (срок близко) — сразу и с напоминаниями.
- Тихие часы и сверх бюджета — в очередь: утренний дайджест при первом движении и раздел сводки.
- Журнал notify-log.jsonl: исход только «answer», «expired», «closed»; «answer» — только по журналу владельца.

Пороги — DEFAULTS, переопределение — таблица [notify] в schedule.toml. Состояние — STATE/notify.json (пишется под
lock("notify") в pantheon.py). Про задачи и доску модуль ничего не знает: решения передаёт tasks.py словарями,
отправку и «ответил ли владелец» — pantheon.py. Push на телефон не делаем (phone = false, точка вызова пустая).
"""
import json
import os
import re
import time
from datetime import datetime, timedelta

DEFAULTS = {
    "quiet_start": "23:00",       # тихие часы — по часовому поясу Mac
    "quiet_end": "08:00",
    "present_min": 2,             # простой меньше — «здесь»: только окно сессии и доска
    "away_min": 10,               # простой меньше — «рядом»: только доска; больше — «нет»: macOS
    "repeat_min": 60,             # повтор по тому же решению или сбою — не раньше
    "long_wait_min": 120,         # без ответа столько — «долго ждёт»: дальше без пингов, только доска и сводка
    "urgent_hours": 4,            # срок ближе — срочно: сразу, мимо присутствия и бюджета
    "urgent_remind_min": [60, 30],  # напоминания срочного — за столько минут до срока
    "daily_budget": 5,            # прерывающих уведомлений в день
    "phone": False,               # push на телефон — выключено: нужно отдельное «да» владельца
}
OUTCOMES = ("answer", "expired", "closed")
LEVELS = ("normal", "urgent", "long", "fault", "critical", "digest")
HUMAN_WAIT = "Нужен ответ"
DAY = 86400
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?")


def _hm(v):
    """«ЧЧ:ММ» → минуты от полуночи, иначе None."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", v) if isinstance(v, str) else None
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def settings(raw=None):
    """DEFAULTS поверх таблицы [notify]: неизвестный ключ не берётся, плохое значение — порог по умолчанию."""
    cfg = dict(DEFAULTS, urgent_remind_min=list(DEFAULTS["urgent_remind_min"]))
    if not isinstance(raw, dict):
        return cfg
    for k in DEFAULTS:
        if k not in raw:
            continue
        v = raw[k]
        if k in ("quiet_start", "quiet_end"):
            ok = _hm(v) is not None
        elif k == "phone":
            ok = isinstance(v, bool)
        elif k == "urgent_remind_min":
            ok = isinstance(v, list) and all(_num(x) and 0 < x <= 1440 for x in v)
            v = sorted(v, reverse=True) if ok else v
        elif k == "daily_budget":
            ok = isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1000
        else:
            ok = _num(v) and 0 <= v <= 100000
        if ok:
            cfg[k] = v
    return cfg


def presence(idle, cfg=None):
    """Простой в секундах → «здесь» | «рядом» | «нет» (here | near | away)."""
    cfg = cfg or DEFAULTS
    if idle < cfg["present_min"] * 60:
        return "here"
    if idle < cfg["away_min"] * 60:
        return "near"
    return "away"


def is_quiet(t, cfg=None):
    cfg = cfg or DEFAULTS
    d = datetime.fromtimestamp(t)
    m, a, b = d.hour * 60 + d.minute, _hm(cfg["quiet_start"]), _hm(cfg["quiet_end"])
    if a == b:
        return False
    return (m >= a or m < b) if a > b else (a <= m < b)


def quiet_until(t, cfg=None):
    """Конец текущих тихих часов (метка времени); вне тихих часов — t."""
    cfg = cfg or DEFAULTS
    if not is_quiet(t, cfg):
        return t
    b = _hm(cfg["quiet_end"])
    d = datetime.fromtimestamp(t)
    end = d.replace(hour=b // 60, minute=b % 60, second=0, microsecond=0)
    if end.timestamp() <= t:
        end += timedelta(days=1)
    return end.timestamp()


def _after_end(t, cfg):
    """Сегодня уже прошёл конец тихих часов (утро наступило) и сейчас не тихие часы."""
    d = datetime.fromtimestamp(t)
    return not is_quiet(t, cfg) and d.hour * 60 + d.minute >= _hm(cfg["quiet_end"])


def iso(t):
    return datetime.fromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%S") if t is not None else None


def day_of(t):
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d")


def journal(path, t, id, level, shown=None, outcome=None, answered=None):
    """Строка журнала уведомлений: показ (shown — время показа) или закрытие цикла (outcome).
    Исход — только answer | expired | closed. answered — время ответа владельца по его журналу, только при answer;
    без него answer записать нельзя. Текста ответа в журнале нет: «да» без явного ответа не записывается."""
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError(f"исход «{outcome}» — только {', '.join(OUTCOMES)}")
    if outcome == "answer" and not (isinstance(answered, str) and ISO_RE.fullmatch(answered)):
        raise ValueError("исход answer — только со временем ответа из журнала владельца")
    if answered is not None and outcome != "answer":
        raise ValueError("answered — только при исходе answer")
    if level not in LEVELS:
        raise ValueError(f"уровень «{level}» — не из {', '.join(LEVELS)}")
    if shown is not None and not (isinstance(shown, str) and ISO_RE.fullmatch(shown)):
        raise ValueError("shown — время показа")
    rec = {"time": iso(t), "id": str(id)[:80], "level": level, "shown": shown}
    if outcome is not None:
        rec["outcome"] = outcome
    if answered is not None:
        rec["answered"] = answered
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if os.path.getsize(path) > 1_000_000:  # журнал не растёт без конца: оставить вторую половину
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.writelines(lines[len(lines) // 2:])
        os.replace(tmp, path)
    return rec


class Policy:
    """Политика одного прохода. send(text, title, target, group) — уведомление macOS; answered(id, since) — время
    первого ответа владельца по id после since (ISO) или None; idle — простой в секундах (число или функция).
    Вызывающий держит lock("notify") от создания до save()."""

    def __init__(self, state_path, log_path, cfg=None, t=None, idle=0, send=None, answered=None, owner_put=None):
        self.cfg = cfg or settings()
        self.t = time.time() if t is None else t
        self._idle = idle
        self._presence = None
        self.send_fn = send or (lambda *a, **k: None)
        self.answered = answered or (lambda tid, since: None)
        # owner_put(id, since) — вы сами перенесли карточку в «Нужен ответ» не раньше since: цикл без пингов
        self.owner_put = owner_put or (lambda tid, since: False)
        self.state_path, self.log_path = state_path, log_path
        try:
            with open(state_path, encoding="utf-8") as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            st = {}
        self.st = st if isinstance(st, dict) else {}
        for k, v in (("cycles", {}), ("faults", {}), ("queue", [])):
            if not isinstance(self.st.get(k), type(v)):
                self.st[k] = v
        self.today = day_of(self.t)
        if self.st.get("day") != self.today:  # бюджет — на календарный день
            self.st["day"], self.st["used"] = self.today, 0
        self.long, self._cur = set(), {}
        self.sent = []  # что ушло в этом проходе: (уровень, текст)

    # --- общее ---
    @property
    def presence(self):
        if self._presence is None:
            idle = self._idle() if callable(self._idle) else self._idle
            self._presence = presence(float(idle or 0), self.cfg)
        return self._presence

    @property
    def quiet(self):
        return is_quiet(self.t, self.cfg)

    def budget_left(self):
        return int(self.st.get("used") or 0) < self.cfg["daily_budget"]

    def _send(self, text, level, ids, target=None, group=None, title="Пантеон"):
        self.send_fn(text, title, target, group)
        self.st["used"] = int(self.st.get("used") or 0) + 1
        self.sent.append((level, text))
        for i in ids:
            journal(self.log_path, self.t, i, level, shown=iso(self.t))

    def _enqueue(self, kind, key, text):
        q = self.st["queue"]
        if any(x.get("id") == key and x.get("text") == text and self.t - x.get("t", 0) < DAY for x in q):
            return
        q.append({"t": self.t, "kind": kind, "id": key, "text": " ".join(str(text).split())[:300]})

    def later(self, kind, key, text):
        """Без пинга — в очередь дайджеста и раздел сводки (конфликт карточки и прочее «может подождать»)."""
        self._enqueue(kind, key, text)

    def queue_view(self):
        """Очередь за сутки, новые сверху: [(время ЧЧ:ММ, вид, id, текст)]."""
        out = [x for x in self.st["queue"] if self.t - x.get("t", 0) < DAY]
        return [(datetime.fromtimestamp(x["t"]).strftime("%d.%m %H:%M"), x.get("kind"), x.get("id"), x.get("text"))
                for x in sorted(out, key=lambda x: -x["t"])]

    def _phone(self, what):
        """Место для push на телефон (раздел 6.3: эскалация «долго ждёт», срочное). Пока ничего не делает:
        Remote Control и настройки Claude Code — отдельное «да» владельца (план эпика, п. 10)."""
        if self.cfg.get("phone"):
            pass

    # --- решения ---
    def _ref(self, d):
        """Опорное время срока для пингов (срочно и напоминания). Срок-дата (due_day) — начало тихих часов дня срока:
        напоминать вечером, а не ночью. Истечение и «просрочено» — по самому сроку (у даты — конец дня)."""
        due = d.get("due")
        if due is None or not d.get("due_day"):
            return due
        a, b = _hm(self.cfg["quiet_start"]), _hm(self.cfg["quiet_end"])
        if a <= b:  # тихие часы не переходят через полночь (00:30–08:00): конец дня срока не тихий — опора сам срок
            return due
        ref = datetime.fromtimestamp(due).replace(hour=a // 60, minute=a % 60, second=0, microsecond=0).timestamp()
        return min(ref, due)

    def _urgent(self, d):
        """Срочно: в тихие часы — только срок раньше их конца; вне тихих часов — срок ближе urgent_hours."""
        ref = self._ref(d)
        if ref is None or self.t >= ref:
            return False
        if self.quiet:
            return ref < quiet_until(self.t, self.cfg)
        return ref - self.t <= self.cfg["urgent_hours"] * 3600

    def _close(self, tid, c, outcome, answered=None):
        c["out"] = outcome
        journal(self.log_path, self.t, tid, c.get("level") or "normal", shown=iso(c.get("last")),
                outcome=outcome, answered=answered)

    def _outcome(self, tid, c):
        ans = self.answered(tid, c["since"])
        if ans:
            return "answer", ans
        if c.get("due") is not None and self.t >= c["due"]:
            return "expired", None
        return "closed", None

    def decisions(self, decs):
        """decs — карточки «Нужен ответ»: {id, sig, since, due, title, due_text, recommend}. Обновляет циклы и
        закрывает ушедшие. → id «долго ждёт» (для «Внимания» карточки и сводки)."""
        cyc, t = self.st["cycles"], self.t
        self._cur = {d["id"]: d for d in decs}
        for tid, c in list(cyc.items()):
            if tid not in self._cur:
                if not c.get("out"):
                    self._close(tid, c, *self._outcome(tid, c))
                del cyc[tid]
        for d in decs:
            tid = d["id"]
            c = cyc.get(tid)
            if c and c.get("sig") != d.get("sig"):  # новый вопрос — новый цикл
                if not c.get("out"):
                    self._close(tid, c, *self._outcome(tid, c))
                c = None
            if not c:
                since = d.get("since")
                c = cyc[tid] = {"sig": d.get("sig"), "since": t if since is None or since > t else since,
                                "shown": 0, "last": None, "level": "normal", "rem": [], "queued": False}
            c["due"] = d.get("due")
            if c.get("out"):
                continue
            if not c.get("owner_put") and self.owner_put(tid, c["since"]):
                c["owner_put"] = True  # не ответ: исход при уходе — по обычным правилам
            ans = self.answered(tid, c["since"])
            if ans:
                self._close(tid, c, "answer", ans)
                continue
            if c["due"] is not None and t >= c["due"]:
                self._close(tid, c, "expired")
                continue
            if t - c["since"] >= self.cfg["long_wait_min"] * 60:
                self.long.add(tid)
                if c["level"] == "normal":
                    c["level"] = "long"
                    self._phone(("long", tid))
        return set(self.long)

    def _decision_text(self, d, urgent):
        title = d.get("title") or d["id"]
        if urgent:
            return f"⏰ Срочно, срок {d.get('due_text') or ''}: {title}"
        text = f"❓ Вопрос к вам: {title}"
        if d.get("due_text"):
            text += f" · срок {d['due_text']}"
        if d.get("recommend"):
            rec = " ".join(str(d["recommend"]).split())
            text += " · совет: " + (rec if len(rec) <= 80 else rec[:79] + "…")
        return text

    def run(self, counts=None, url=None, summary_url=None, legacy_digest_day=None):
        """Утренний дайджест и пинги по решениям этого прохода. counts — (нужен ответ, просрочено, входящих);
        url(id) — ссылка на карточку. legacy_digest_day — digest_day прежнего board.json (до 0.9.30): в день
        обновления второго утреннего не будет."""
        url = url or (lambda tid: None)
        if "digest_day" not in self.st and legacy_digest_day:
            self.st["digest_day"] = legacy_digest_day
        self._digest(counts or (0, 0, 0), summary_url)
        self._ping_decisions(url, summary_url)

    def _digest(self, counts, summary_url):
        if self.st.get("digest_day") == self.today or not _after_end(self.t, self.cfg) or self.presence != "here":
            return
        self.st["digest_day"] = self.today
        since = max(self.st.get("digest_t") or 0, self.t - DAY)
        held = sum(1 for x in self.st["queue"] if x.get("t", 0) > since)
        self.st["digest_t"] = self.t
        for c in self.st["cycles"].values():  # ночное отложенное вышло дайджестом: отсчёт повтора — от него
            if c.pop("night", None):
                c["last"], c["queued"] = self.t, False
        n, overdue, inbox = counts
        if not (n or overdue or inbox or held):
            return
        text = f"Доброе утро. {HUMAN_WAIT}: {n}, просрочено: {overdue}, входящих заявок: {inbox}."
        if held:
            text += f" Отложено: {held} — в сводке."
        self._send(text, "digest", ["digest"], summary_url, "digest")

    def _ping_decisions(self, url, summary_url):
        t, cfg, ping = self.t, self.cfg, []
        for tid, c in self.st["cycles"].items():
            d = self._cur.get(tid)
            if d is None or c.get("out"):
                continue
            if c.get("owner_put"):
                continue  # карточку в «Нужен ответ» перенесли вы сами: только доска и сводка
            if self._urgent(d):
                ref = self._ref(d)
                crossed = [m for m in cfg["urgent_remind_min"] if t >= ref - m * 60 and m not in c["rem"]]
                if not c.get("urgent") or crossed:
                    c["urgent"], c["level"] = True, "urgent"
                    c["rem"] = sorted(set(c["rem"]) | set(crossed), reverse=True)
                    ping.append((tid, True))
                    self._phone(("urgent", tid))
                continue
            if tid in self.long:
                continue  # долго ждёт: только доска и сводка
            if self.quiet:
                if not c.get("queued"):
                    self._enqueue("decision", tid, self._decision_text(d, False))
                    c["queued"] = True
                c["night"] = True  # ждёт утреннего дайджеста
                continue
            if c.get("night") or self.presence != "away":
                continue
            if c.get("last") is not None and t - c["last"] < cfg["repeat_min"] * 60:
                continue
            ping.append((tid, False))
        normal = [x for x in ping if not x[1]]
        if normal and not self.budget_left() and not any(x[1] for x in ping):
            for tid, _ in normal:  # сверх бюджета — в очередь дайджеста
                c = self.st["cycles"][tid]
                if not c.get("queued"):
                    self._enqueue("decision", tid, self._decision_text(self._cur[tid], False))
                    c["queued"] = True
            return
        if not ping:
            return
        urgent = any(x[1] for x in ping)
        ids = [x[0] for x in ping]
        if len(ids) == 1:
            text = self._decision_text(self._cur[ids[0]], urgent)
            target, group = url(ids[0]), ids[0]
        else:
            titles = [self._cur[i].get("title") or i for i in ids]
            text = f"{'⏰ ' if urgent else ''}{HUMAN_WAIT}: {len(ids)} — " + "; ".join(titles[:3]) + (
                " …" if len(titles) > 3 else "")
            target, group = summary_url, "decisions"
        self._send(text, "urgent" if urgent else "normal", ids, target, group)
        for tid in ids:
            c = self.st["cycles"][tid]
            c["shown"] = int(c.get("shown") or 0) + 1
            c["last"] = t

    # --- сбои и критичное ---
    def fault(self, key, text, target=None, group=None):
        """Сбой класса «скоро» (задача упала, аренда, сессия ждёт вас, тревога с note): macOS только при «нет», не
        ночью, в бюджете, одна на ключ события за repeat_min; сейчас нельзя — в очередь дайджеста. Повтор считается
        по key (событие), group только заменяет уведомление в Центре уведомлений (по умолчанию key). faults[key] —
        время последней ОТПРАВКИ: событие, которое держится (вызывают каждый проход), дойдёт macOS, когда вы уйдёте.
        → "sent" | "queued" | "skip"."""
        rec = self.st["faults"].get(key)
        last, last_text = (rec.get("t"), rec.get("text")) if isinstance(rec, dict) else (rec, None)
        flat = " ".join(str(text).split())
        if isinstance(last, (int, float)) and 0 <= self.t - last < self.cfg["repeat_min"] * 60:
            if flat == last_text:
                return "skip"
            self._enqueue("fault", key, text)  # недавно отправляли, а текст новый — без macOS, но в сводку
            return "queued"
        if self.quiet or self.presence != "away" or not self.budget_left():
            self._enqueue("fault", key, text)  # дубли по key+text отсекает _enqueue
            return "queued"
        self._send(text, "fault", [key], target, group or key)
        self.st["faults"][key] = {"t": self.t, "text": flat}
        return "sent"

    def critical(self, text, title="Пантеон · критично", send=True, group="critical"):
        """COMM-08: сразу и всегда (ночью тоже — менять это может только владелец); в счёт бюджета и в журнал.
        send=False — уведомление уже ушло мимо блокировки (notify_critical в pantheon.py), здесь только учёт."""
        if send:
            self._send(text, "critical", ["critical"], None, group, title)
            return
        self.st["used"] = int(self.st.get("used") or 0) + 1
        self.sent.append(("critical", text))
        journal(self.log_path, self.t, "critical", "critical", shown=iso(self.t))

    def save(self):
        t = self.t
        self.st["queue"] = [x for x in self.st["queue"] if isinstance(x, dict) and t - x.get("t", 0) < 2 * DAY]
        stamp = lambda v: v.get("t") if isinstance(v, dict) else v
        self.st["faults"] = {k: v for k, v in self.st["faults"].items()
                             if isinstance(stamp(v), (int, float)) and t - stamp(v) < DAY}
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        tmp = f"{self.state_path}.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.st, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)
