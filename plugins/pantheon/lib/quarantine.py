"""Пантеон: pantheon sync-answers — ответ владельца на доске по карантину ~/.claude (SEC-15) применить сразу.

Вынесено из pantheon.py (metis-0586) без изменения поведения. P — модуль pantheon: его ставит загрузчик
pantheon._attach до выполнения этого файла, имена из __all__ становятся именами pantheon.
"""
import json
import os
import re
import subprocess
import sys
import time

__all__ = [
    "SYNC_ACT", "sync_answers",
]


SYNC_ACT = {"Отправить на другие Mac", "Отправить", "Откатить правку", "Всё в порядке — правка наша", "Откатить на всех Mac"}


def sync_answers():
    owner_log = os.path.join(P.STATE, "owner-log", "board.jsonl")
    ask_log = os.path.join(P.STATE, "owner-log", "zeus.md")
    waiting = []
    by_file = {}  # файл держания -> его задача (по первому чтению)
    for held in (".sync-held", ".sync-incoming"):
        try:
            text = open(os.path.join(P.SYNC_DIR, held), encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            continue
        m = re.search(r"^task=(\S+)$", text, re.M)
        if m:
            waiting.append(m.group(1))
            by_file[held] = m.group(1)
    if not waiting or not (os.path.exists(owner_log) or os.path.exists(ask_log)):
        return 0
    # как owner_answer в sync.sh (metis-0125): ответ — галочка на доске (board.jsonl) или выбор в окне вопросов Зевса
    # (zeus.md: пометка «· окно вопросов» или «· ответ в чате», вопрос начинается с [<id>], не старше 7 дней); из двух
    # берётся более поздний
    found = {t: [] for t in waiting}
    lines = []
    try:
        lines = open(owner_log, encoding="utf-8").read().splitlines()
    except OSError:
        pass
    for n, line in enumerate(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("kind") == "answer" and d.get("id") in found:
            try:
                t = time.mktime(time.strptime(str(d.get("time", ""))[:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                t = 0.0
            found[d["id"]].append((t, n, d.get("answer") if isinstance(d.get("answer"), str) else ""))
    try:
        text = open(ask_log, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        text = ""
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    for i, m in enumerate(heads):
        if not P.answers_mod().is_answer_head(m.group(2)):
            continue
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        q, a = re.match(r"вопрос: \[([^\]\s]{1,40})\]", body, re.I), re.search(r"^ответ: (.*)$", body, re.M)
        if not q or not a or q.group(1) not in found:
            continue
        try:
            t = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        if t >= P.now() - 7 * 86400:
            found[q.group(1)].append((t, len(lines) + i, a.group(1)))
    last = {t: re.sub(r"\s*\((?:Recommended|рекомендую)\)$", "", max(v)[2].strip()) for t, v in found.items() if v}
    if not any(last.get(t) in SYNC_ACT for t in waiting):
        return 0
    script = os.path.join(P.SYNC_DIR, "sync.sh")
    try:
        r = subprocess.run([script], capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"sync-answers: sync.sh не отработал: {e}", file=sys.stderr)
        return 1
    # metis-0226: вопрос отвечен — снять его с карточки, иначе она висит в «Ждёт вас», если sync.sh задачу не закрыл
    # (его `pantheon task set` молчит при сбое); закрытие статуса остаётся за sync.sh
    # metis-0364: «применён» — только после проверки держаний; файл не прочитан или без task= — держание остаётся
    if r.returncode != 0:  # sync.sh не отработал — вопрос остаётся в «Ждёт вас»
        print(f"sync-answers: sync.sh завершился с кодом {r.returncode} — ответ по {', '.join(waiting)} ждёт")
        return 0
    T = P.tasks_mod()
    still = set()  # держание, которое sync.sh не снял (или которое не удалось проверить), — значит, не применил
    reasons = {}
    for held in (".sync-held", ".sync-incoming"):
        try:
            text = open(os.path.join(P.SYNC_DIR, held), encoding="utf-8").read()
        except FileNotFoundError:
            continue  # файла нет — держание снято
        except (OSError, UnicodeDecodeError) as e:
            why = f"{held} не прочитан: {e.__class__.__name__}"
        else:
            m = re.search(r"^task=(\S+)$", text, re.M)
            if m:
                still.add(m.group(1))
                prev = by_file.get(held)
                if held == ".sync-held" and prev and prev != m.group(1):
                    # sync.sh снял прежнее держание и поставил другое (ветка «правка изменилась» в quarantine()):
                    # ответ по прежней задаче не применён, её вопрос остаётся. У .sync-incoming иначе: файл
                    # удаляет incoming_answer после ответа, а новый пишет incoming_check — смена task= значит «применён»
                    still.add(prev)
                    reasons[prev] = f"держание заменено (task={m.group(1)}), ответ не применён"
                continue
            why = f"{held} без task="
        # проверить нельзя: держание остаётся за своей задачей (известна по первому чтению), а без неё — за всеми
        owner = by_file.get(held)
        still.update([owner] if owner else waiting)
        reasons[owner or "*"] = why
    for tid in waiting:
        if last.get(tid) not in SYNC_ACT:
            continue
        if tid in still:
            why = reasons.get(tid) or reasons.get("*")
            print(f"sync-answers: {tid} — sync.sh не применил, вопрос остаётся" + (f" ({why})" if why else ""))
            continue
        print(f"sync-answers: ответ по {tid} применён (sync.sh, код 0)")
        try:
            head = T.load_tasks(P.PANTHEON, T.WORK_TYPES).get(tid, (None, {}, None))[1]
            if head.get("question") or head.get("options"):
                T.task_set(P.PANTHEON, P.now(), tid, {"question": None, "options": None},
                           note="ответ владельца получен — вопрос снят", actor="плановый проход")
        except (OSError, ValueError) as e:
            print(f"sync-answers: вопрос {tid} не снят: {e}", file=sys.stderr)
    return 0
