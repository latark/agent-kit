"""metis-0834: вопрос владельцу после DEFER_LIMIT «отложить» по задаче не повторяется (вызов — шаг 5а board_sync
в tasks.py). Модуль tasks передаётся аргументом T: его грузят и под другим именем."""
import os
import re

# metis-0834: после DEFER_LIMIT «отложить» по одной задаче тот же вопрос владельцу не повторяется (athena-0205 переносили
# 11 раз, проход каждые часы снова спрашивал). Вместо этого координатору направления (Зевсу — у входящих и у
# направления без координатора) уходит задача «найти исполнителя или решение», а владельцу — строка суточной сводки.
DEFER_LIMIT = 3
# metis-0995: переносом считается ответ, у которого выбранный вариант ЦЕЛИКОМ «отложить / перенести / спроси позже /
# завтра / через N / напомни». Подстрока не годится: «не переноси», «перенос данных», «без переноса сроков»,
# «закрыть 20, отложить 33» переносом не являются.
_MARK_RE = re.compile(r"^\s*(?:[A-Za-zА-Яа-я]|\d{1,2})\s*(?:[—–-]\s+|[).:]\s*)")
_WHEN = (r"(?:до|на\s+(?:завтра|потом|позже|\d+|неделю|месяц|день|час|выходные)|ещ[ёе]|позже|потом|завтра|"
         r"через\s+\S+|вопрос|решение)")
DEFER_RE = re.compile(
    r"^(?:(?:отложи(?:ть|м)?|перенес(?:ти|и|[ёе]м)|перенеси)(?:\s+" + _WHEN + r"\b.*)?"
    r"|спроси(?:\s+меня)?\s+(?:ещ[ёе]|позже|завтра|через)\b.*"
    r"|завтра|потом|позже|через\s+\d+\s+\S+.*|напомни(?:\s+(?:позже|завтра|потом|через)\b.*)?)$", re.I)
WINDOW_ANSWER_RE = re.compile(r"^## \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} · (?:окно вопросов|ответ в чате)\s*$", re.M)


def _read_zeus_log(board_log_path):
    """owner-log/zeus.md рядом с журналом доски; нет файла — пусто."""
    try:
        with open(os.path.join(os.path.dirname(board_log_path), "zeus.md"), encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def _qkey(text):
    """Вопрос для сверки — в одну строку, без пробелов по краям (как tasks._question_key)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t[1:] if re.match(r"\\[-*+]\s*\[", t) else t


def is_defer(answer):
    """Выбранный вариант целиком — «отложить / перенести / спроси позже / завтра / через N / напомни». Буква или номер
    варианта, скобки («(совет)») и конечная пунктуация не в счёт; отрицание и перенос чего-то другого — нет."""
    t = _MARK_RE.sub("", str(answer or ""), count=1)
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .!,;")
    return bool(DEFER_RE.match(t))


def deferral_counts(board_recs, zeus_log_text="", heads=None):
    """{id задачи: сколько раз владелец отложил ТЕКУЩИЙ вопрос} — ответы доски (owner-log/board.jsonl, kind answer) и окна
    вопросов с чатом (owner-log/zeus.md: «вопрос: [id] …», «ответ: …»), где вариант целиком «отложить» (is_defer).
    heads — {id: шапка задачи}: тогда считаются только ответы на нынешний вопрос и нынешние варианты; новый вопрос
    или смена вариантов счётчик обнуляет (запись без вопроса или обрезанная — не считается). Без heads — по задаче целиком."""
    heads = heads or {}

    def current(tid, rq, ans):
        h = heads.get(tid)
        if h is None:
            return True
        q = _qkey(h.get("question"))
        opts = [_qkey(o) for o in h.get("options") or []]
        if opts and _qkey(ans) not in opts:
            return False
        return not q or (bool(_qkey(rq)) and len(rq or "") < 2000 and _qkey(rq) == q)

    out = {}
    for tid, recs in (board_recs or {}).items():
        n = sum(1 for r in recs if r.get("kind") == "answer" and is_defer(r.get("answer"))
                and current(tid, r.get("question"), r.get("answer")))
        if n:
            out[tid] = n
    text = zeus_log_text or ""
    heads_ = list(WINDOW_ANSWER_RE.finditer(text))
    for k, m in enumerate(heads_):
        block = text[m.end():heads_[k + 1].start() if k + 1 < len(heads_) else len(text)]
        q = re.match(r"\s*вопрос: \[([a-z0-9][a-z0-9-]{0,40})\]([^\n]*)", block)
        a = re.search(r"^ответ: (.+)$", block, re.M)
        if not (q and a and is_defer(a.group(1))):
            continue
        h = heads.get(q.group(1))
        if h is not None:  # в журнале окна первая строка вопроса: должна быть началом нынешнего
            hq, zq = _qkey(h.get("question")), _qkey(q.group(2))
            if hq and not (zq and hq.startswith(zq)):
                continue
        out[q.group(1)] = out.get(q.group(1), 0) + 1
    return out


def defer_escalation(T, pantheon, t, tid, head, n, registry):
    """Поручение координатору (задача task_new, как у остальных путей тика): найти исполнителя или решение вместо
    очередного вопроса владельцу. → id новой задачи."""
    d = head.get("direction")
    hq = any(d in r["directions"] and r.get("hq_led") for r in (registry or {}).values())
    owner = "zeus" if hq or d in (None, "", "inbox") else d
    title = f"Найти исполнителя или решение по {tid}: владелец отложил вопрос {n} раз"
    text = (f"Владелец {n} раз отложил вопрос по [[{tid}]] ({T.one_line(head.get('title') or tid)[:120]}). Плановый проход "
            f"больше не пингует его по этой задаче. Найди, что снимает вопрос без владельца: Харон (браузер), `pantheon "
            f"outside`, другая роль или готовое решение. Нашёл — запиши в задачу {tid} и сними вопрос; не нашёл — один "
            f"раз вернись к владельцу с новым вариантом, а не тем же вопросом. Отложенные вопросы владелец видит "
            f"одной суточной сводкой.")
    ndir = d if d and d != "inbox" and os.path.isdir(os.path.join(pantheon, "directions", d)) else "inbox"
    new, _ = T.task_new(pantheon, t, ndir, title, project=head.get("project") if ndir != "inbox" else "входящие",
                      owner=owner, actor="плановый проход", text=text, priority=2,
                      done_when=[f"по {tid} назван исполнитель или решение, либо владельцу задан один новый вопрос"])
    return new


def hold(T, pantheon, t, tasks, cards, log_path, registry, primary, policy, alert, done_lines):
    """Шаг 5а доски (T — модуль tasks): задачи, ждущие владельца и отложенные DEFER_LIMIT раз. Каждой — один раз
    поручение координатору и строка суточной сводки; → их id (пингов по ним нет)."""
    defers = deferral_counts(T.owner_answers_all(log_path), _read_zeus_log(log_path),
                             {tid: h for tid, (_, h, _) in tasks.items()})
    held = {tid for tid, (_, h, _) in tasks.items() if defers.get(tid, 0) >= DEFER_LIMIT
            and h.get("status") == "waiting" and h.get("waiting_on") == "human" and T._live(h, t)}
    for tid in sorted(held):
        st = cards.setdefault(tid, {})
        if primary and not st.get("defer_task"):  # поручение координатору — один раз на задачу
            try:
                st["defer_task"] = defer_escalation(T, pantheon, t, tid, tasks[tid][1], defers[tid], registry)
                done_lines.append(f"{tid}: вопрос отложен {defers[tid]} раз — поручение {st['defer_task']}")
            except (ValueError, OSError) as e:
                alert(f"defer-task-{tid}", "1", f"отложенный {defers[tid]} раз вопрос {tid}: поручение координатору "
                      f"не создать ({e})", "board")
        if policy is not None:  # владельцу — строка суточной сводки (очередь дайджеста), не пинг
            policy.later("defer", tid, f"↻ Отложен {defers[tid]} раз, не спрашиваю снова: "
                                       f"{T.one_line(tasks[tid][1].get('title') or tid)[:100]}"
                                       + (f" — поручение {st['defer_task']}" if st.get("defer_task") else ""))
    return held
