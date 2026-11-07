"""metis-0834: вопрос владельцу после DEFER_LIMIT «отложить» по задаче не повторяется (вызов — шаг 5а board_sync
в tasks.py). Модуль tasks передаётся аргументом T: его грузят и под другим именем."""
import os
import re

# metis-0834: после DEFER_LIMIT «отложить» по одной задаче тот же вопрос владельцу не повторяется (athena-0205 переносили
# 11 раз, проход каждые часы снова спрашивал). Вместо этого координатору направления (Зевсу — у входящих и у
# направления без координатора) уходит задача «найти исполнителя или решение», а владельцу — строка суточной сводки.
DEFER_LIMIT = 3
DEFER_RE = re.compile(r"отлож|перенес|перенос|спроси (?:ещ[ёе]|позже|завтра|через)|напомни", re.I)
WINDOW_ANSWER_RE = re.compile(r"^## \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} · (?:окно вопросов|ответ в чате)\s*$", re.M)


def _read_zeus_log(board_log_path):
    """owner-log/zeus.md рядом с журналом доски; нет файла — пусто."""
    try:
        with open(os.path.join(os.path.dirname(board_log_path), "zeus.md"), encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def deferral_counts(board_recs, zeus_log_text=""):
    """{id задачи: сколько раз владелец отложил вопрос} — ответы доски (owner-log/board.jsonl, kind answer) и окна
    вопросов с чатом (owner-log/zeus.md: «вопрос: [id] …», «ответ: …»), в тексте ответа — слово про откладывание.
    Считается по задаче целиком, а не по текущему вопросу: новый вопрос после переноса счётчик не обнуляет."""
    out = {}
    for tid, recs in (board_recs or {}).items():
        n = sum(1 for r in recs if r.get("kind") == "answer" and DEFER_RE.search(r.get("answer") or ""))
        if n:
            out[tid] = n
    text = zeus_log_text or ""
    heads = list(WINDOW_ANSWER_RE.finditer(text))
    for k, m in enumerate(heads):
        block = text[m.end():heads[k + 1].start() if k + 1 < len(heads) else len(text)]
        q = re.match(r"\s*вопрос: \[([a-z0-9][a-z0-9-]{0,40})\]", block)
        a = re.search(r"^ответ: (.+)$", block, re.M)
        if q and a and DEFER_RE.search(a.group(1)):
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
    defers = deferral_counts(T.owner_answers_all(log_path), _read_zeus_log(log_path))
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
