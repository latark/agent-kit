"""Пантеон: согласие через Зевса (pantheon consent, metis-0022) и заранее разрешённые действия (pantheon approve,
DONE-11).

Вынесено из pantheon.py (metis-0586) без изменения поведения. P — модуль pantheon: его ставит загрузчик
pantheon._attach до выполнения этого файла, имена из __all__ становятся именами pantheon.
"""
import json
import os
import re
import sys
import time
import tomllib
from datetime import datetime

__all__ = [
    "HESTIA_CONSENT_DAYS", "APPROVALS", "APPROVALS_HEAD", "CONSENT_ID", "CONSENT_MAX", "CONSENT_REAP_Q",
    "CONSENT_ANSWER", "CONSENT_YES", "CONSENT_NO", "consent_is_yes", "consent", "approvals_load", "toml_str",
    "approve",
]


HESTIA_CONSENT_DAYS = 1.0       # ответ владельца для метки Гестии — не старше суток


# --- заранее разрешённые действия (DONE-11, SEC-26: красный флаг исследования) ------------------
# approvals.toml — ваше согласие заранее, поэтому он лежит вне зоны записи Зевса и ролей: ~/.claude/pantheon/ (песочница
# и guard protect-config), а пишет его только эта команда, которую guard не даёт ни одной роли, даже штабу. Вы набираете
# её сами: в своём терминале или в окне Зевса после «!». Деньги, новые публикации, сообщения людям и удаление сюда не
# вносятся — всегда отдельное «да».
APPROVALS = os.path.join(P.HOME, ".claude", "pantheon", "approvals.toml")
APPROVALS_HEAD = """# Заранее разрешённые действия мастерской на сайтах (DONE-11 карты решений).
# Пишет только команда владельца `pantheon approve` (роли и Пританей её запустить не могут — guard). Мастерская читает этот
# файл перед действием на сайте; деньги, новые публикации, сообщения людям, удаление и всё, чего тут нет, — отдельное «да».
"""


# --- согласие через Зевса (metis-0022, решение 15.10) ---------------------------------
# Вопрос владельцу задаёт Зевс (окном вопросов, сообщением с вариантами или карточкой «Нужен ответ» на доске). Ответ
# пишут не роли: хук — в owner-log/zeus.md (ввод владельца, выбор в окне вопросов, ответ в чате — metis-0405, решение
# владельца 01.11), тик — в owner-log/board.jsonl (галочка на карточке; текст вопроса тик берёт из отмеченной
# карточки). Журналы личные — роли их не читают; эта команда отдаёт исполнителю только записи с номером его вопроса.
CONSENT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
CONSENT_MAX = 1500
# вопрос `pantheon reap --apply` об остальном своём (lib/culprits.py): «да» на него — метка <id>.reap со списком pid
# из вопроса, а не метка push (metis-0568: согласия на push и на гашение не путаются)
CONSENT_REAP_Q = "Погасить процессы Пантеона"


CONSENT_ANSWER = re.compile(r"^ответ:[ \t]*(.*)$", re.M)
CONSENT_YES = re.compile(r"да(?![\w-])", re.I)
CONSENT_NO = re.compile(r"(?<![\w-])(?:не|нет|no)(?![\w-])", re.I)


def consent_is_yes(body):
    """Явное «да» владельца в записи ответа: строка «ответ: …» начинается словом «да» и в ней нет «не», «нет»
    («Да — отправить», «Да, по consent» — да; «Нет», «Да, но не сегодня», «Другое» — нет)."""
    m = CONSENT_ANSWER.search(body or "")
    ans = m.group(1).strip() if m else ""
    return bool(CONSENT_YES.match(ans)) and not CONSENT_NO.search(ans)


def consent(rest):
    if not rest or not CONSENT_ID.fullmatch(rest[0]):
        print("pantheon consent <id> [--days N] — id задачи вида metis-0032 или tbankrot-8057746", file=sys.stderr)
        return 2
    qid, days = rest[0], 7.0
    if "--days" in rest:
        try:
            days = min(30.0, max(0.1, float(rest[rest.index("--days") + 1])))
        except (IndexError, ValueError):
            print("pantheon consent: --days — число дней", file=sys.stderr)
            return 2
    hestia = os.environ.get("PANTHEON_ROLE") == "hestia"
    if hestia:
        days = min(days, HESTIA_CONSENT_DAYS)
        # окно Гестии одно на задачу (wake hestia --task): согласие — только на id этой задачи (metis-0562)
        if not CONSENT_ID.fullmatch(os.environ.get("PANTHEON_TASK") or "") or qid != os.environ["PANTHEON_TASK"]:
            print(f"pantheon consent: из окна hestia — только по своей задаче ({os.environ.get('PANTHEON_TASK') or 'не задана'}), "
                  f"не по {qid}", file=sys.stderr)
            return 2
    try:
        with open(P.path("owner-log", "zeus.md"), encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = ""
    except (OSError, UnicodeDecodeError) as e:
        print(f"pantheon consent: журнал не читается ({e}) — ответ проверить нельзя", file=sys.stderr)
        return 3
    word = re.compile(r"(?<![\w-])" + re.escape(qid) + r"(?![\w-])", re.I)
    # ответ — выбор в окне вопросов (пометка «окно вопросов», хук answer) или однозначный выбор варианта сообщением прямо
    # после вопроса Зевса с вариантами (пометка «ответ в чате», хук owner-log; lib/answers.py). Пометки ставит хук, ввод
    # владельца их не получает. Вопрос начинается с [<id>]; id в свободном тексте, цитате, заметке к чужому вопросу и в
    # записи «ответ в чате не распознан» — не ответ
    own = re.compile(r"вопрос: \[" + re.escape(qid) + r"\]", re.I)
    since, found, mentions, unclear = P.now() - days * 86400, [], 0, 0
    A = P.answers_mod()
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    for i, m in enumerate(heads):
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        try:
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue
        if t < since:
            continue
        if A.is_answer_head(m.group(2)) and own.match(body):
            found.append((t, m.group(1) + " " + m.group(2).strip() + " у Зевса", body))
        elif word.search(body):
            mentions += 1
            unclear += m.group(2).strip() == "· " + A.CHAT_NONE_NOTE and bool(own.match(body))
    try:
        with open(P.path("owner-log", "board.jsonl"), encoding="utf-8") as fh:
            board_lines = fh.read().splitlines()
    except FileNotFoundError:
        board_lines = []
    except (OSError, UnicodeDecodeError) as e:
        print(f"pantheon consent: журнал доски не читается ({e}) — ответ проверить нельзя", file=sys.stderr)
        return 3
    for line in board_lines:
        try:
            rec = json.loads(line)
            t = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, AttributeError):
            continue
        q, a = rec.get("question"), rec.get("answer")
        # скрытый текст Obsidian (%%…%%, <!-- -->) в вопросе — вы его не видели, такой ответ не согласие (как owner_approved)
        if rec.get("kind") != "answer" or rec.get("id") != qid or t < since or not isinstance(q, str) \
                or not isinstance(a, str) or re.search(r"%%|<", q):
            continue
        found.append((t, rec["time"][:19].replace("T", " ") + " · доска, галочка на карточке (деньги, публикации, "
                      "сообщения людям, удаление — не по галочке, только окном вопросов или ответом в чате)",
                      f"вопрос: {q.strip()}\nответ: {a.strip()}"))
    found.sort(key=lambda x: x[0])
    said_yes = any(consent_is_yes(body) for _, _, body in found)
    last_yes = next(((head, body) for _, head, body in reversed(found) if consent_is_yes(body)), ("", ""))
    reap_q = last_yes[1].split("\nответ:")[0]
    reap_q = reap_q if CONSENT_REAP_Q in reap_q else None
    found = [(head, body if len(body) <= CONSENT_MAX else body[:CONSENT_MAX] + "…") for _, head, body in found]
    hint = (f"\nУпоминаний {qid} в словах владельца, которые не ответ: {mentions} (ответ — выбор в окне вопросов или "
            f"одного варианта сообщением сразу после вопроса «[{qid}] …» с вариантами"
            + (f"; ответ в чате не распознан: {unclear}" if unclear else "")
            + f"); попроси Зевса переспросить окном вопросов «[{qid}] …»." if mentions else "")
    if not found:
        print(f"ответа владельца на {qid} в окне вопросов, в чате Зевса и на доске за {days:g} дн. нет{hint}")
        return 1
    if hestia and not said_yes:
        print(f"Ответ на {qid} есть, но это не «да» — метки для окна нет; наружу не иди, отчёт Зевсу.")
        for t, body in found:
            print(f"\n## {t}\n{body}")
        return 1
    if hestia and reap_q is not None and not last_yes[0].endswith(" у Зевса"):
        print(f"«Да» на {qid} о гашении процессов — галочкой на доске, а не в окне вопросов или в чате: метки нет, "
              "отчёт Зевсу.")
        return 1
    if hestia:
        # метка «владелец ответил «да»»: по ней guard пускает окно Гестии в push и запись в PR на 2 часа, только для
        # этой задачи (metis-0562). Нет метки (запись не удалась) — код 3, а не «согласие есть». «Да» на вопрос о
        # гашении — своя метка <id>.reap с pid из вопроса: её читает только pantheon reap (metis-0568)
        try:
            d = os.path.join(P.STATE, "hestia-consent")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, qid + (".reap" if reap_q is not None else "")), "w", encoding="utf-8") as fh:
                fh.write(f"{P.stamp()} {qid}\n")
                if reap_q is not None:
                    fh.write("pids: " + " ".join(re.findall(r"\bpid (\d+)", reap_q)) + "\n")
        except OSError as e:
            print(f"pantheon consent: метку для окна записать не удалось ({e}) — наружу не пустят", file=sys.stderr)
            return 3
    print(f"Ответы владельца на {qid} (журналы пишут хук и плановый проход, не роли; сверь, что ответ — на твой вопрос и твоё действие):")
    for t, body in found:
        print(f"\n## {t}\n{body}")
    if hint:
        print(hint)
    return 0


def approvals_load():
    try:
        with open(APPROVALS, "rb") as fh:
            return tomllib.load(fh).get("approval") or []
    except (OSError, ValueError):
        return []


def toml_str(s):
    return json.dumps(str(s), ensure_ascii=False)


def approve(rest):
    """pantheon approve [list] | add --site S --allow "что можно" [--limits "граница"] | remove N"""
    items = approvals_load()
    if not rest or rest[0] == "list":
        if not items:
            print("заранее разрешённых действий нет")
        for i, a in enumerate(items, 1):
            print(f"{i}. {a.get('site')}: {a.get('allow')}" + (f" (граница: {a['limits']})" if a.get("limits") else "")
                  + f" — с {a.get('added', '?')}")
        return 0
    if rest[0] == "add":
        def opt(k):
            return rest[rest.index(k) + 1] if k in rest and rest.index(k) + 1 < len(rest) else None
        site, allow, limits = opt("--site"), opt("--allow"), opt("--limits")
        if not site or not allow:
            print(approve.__doc__, file=sys.stderr)
            return 2
        if re.search(r"оплат|плат[её]ж|перевод денег|удал|публикац|сообщени|письм", allow, re.I):
            print("деньги, удаление, публикации и сообщения людям заранее не разрешаются — только отдельное «да»",
                  file=sys.stderr)
            return 2
        items.append({"site": site, "allow": allow, "limits": limits or "", "added": P.stamp(), "host": P.host()})
    elif rest[0] == "remove" and len(rest) > 1 and rest[1].isdigit() and 1 <= int(rest[1]) <= len(items):
        items.pop(int(rest[1]) - 1)
    else:
        print(approve.__doc__, file=sys.stderr)
        return 2
    body = APPROVALS_HEAD + "".join(
        f"\n[[approval]]\nsite = {toml_str(a.get('site'))}\nallow = {toml_str(a.get('allow'))}\n"
        f"limits = {toml_str(a.get('limits', ''))}\nadded = {toml_str(a.get('added', ''))}\nhost = {toml_str(a.get('host', ''))}\n"
        for a in items)
    os.makedirs(os.path.dirname(APPROVALS), exist_ok=True)
    P.write_atomic(APPROVALS, body)
    P.start_log(f"approve\t{rest[0]}\t{len(items)}")
    return approve(["list"])
