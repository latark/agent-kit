"""Ответ владельца на вопрос с [id]: в окне вопросов и в чате (metis-0405, решение владельца 01.11 «Засчитывать
ответ в чате»). Только стандартная библиотека: модуль грузят хук (hooks/ctx.py) и pantheon (lib/*).

Записи ответа в журнале owner-log (`## <время> · <пометка>`, пометку ставит только хук, ввод владельца её не получает):
- «окно вопросов» — выбор в окне вопросов (хук answer): «вопрос: [id] …», «ответ: <вариант>», иногда «заметка: …»;
- «ответ в чате» — однозначный выбор варианта обычным сообщением прямо после вопроса Зевса (хук owner-log):
  «вопрос: [id] …», «ответ: <вариант>», «вариант: <буква или номер>», «дословно: <ваше сообщение>»;
- «ответ в чате не распознан» — после такого вопроса ваше сообщение не выбрало ровно один вариант: «вопрос: [id] …»,
  «дословно: …». Это не ответ: ни consent, ни другие читатели журнала её не берут.

Вопрос в чате (последнее сообщение ассистента перед вашим, из транскрипта этой сессии) засчитывается, только если:
- ровно одна строка начинается с «[<id>]» (перед ним можно «Нужно решить:» и разметку **, #, >, -);
- после неё — варианты, каждый своей строкой: «А — …», «а) …», «(а) …», «1. …», «**Б.** …»; буквы идут подряд с
  А (или A), номера — с 1; вариантов хотя бы один;
- знаков «?» нет нигде, кроме строк вопроса и вариантов, и после вариантов нет второй группы вариантов — иначе «да»
  могло бы относиться к другому вопросу того же сообщения.

Ответ — выбор ровно одного варианта: буква или номер варианта («а», «Б», «2»), порядковое слово («второй»), то же с
«вариант» и вежливыми словами в начале («давай вариант а», «беру б», «а, пожалуйста»), «[id] А», «А — <начало текста
варианта>»; «да» (и «ок», «давай», «согласен») — при одном варианте или когда ровно один вариант начинается словом «да»;
«нет» — когда ровно один вариант начинается словом «нет». Всё прочее — не ответ: два варианта, отрицание («не а»),
встречный вопрос (есть «?»), «не знаю», лишние слова и условия («а, но потом»).
"""
import re

WINDOW_NOTE = "окно вопросов"
CHAT_NOTE = "ответ в чате"
CHAT_NONE_NOTE = "ответ в чате не распознан"
HEADS = ("· " + WINDOW_NOTE, "· " + CHAT_NOTE)   # хвост заголовка записи, которая считается ответом
CHAT_META = ("вариант: ", "дословно: ")          # служебные строки записи «ответ в чате» после «ответ: …»

QID = r"[a-z0-9][a-z0-9-]{0,40}"
QUESTION_RE = re.compile(r"^[\s*_#>\-•]*(?:нужно решить\s*:?[\s*_]*)?\[(" + QID + r")\]", re.I)
OPTION_RE = re.compile(
    r"^\s*(?:[-*+•]\s+)?(?:\*\*|__)?"
    r"(?:\((?P<l1>[а-яёa-z]|\d{1,2})\)|(?P<l2>[а-яёa-z]|\d{1,2})(?:\*\*|__)?\s*[.)—–:-])"
    r"(?:\*\*|__)?\s*(?:[—–-]\s*)?(?P<text>\S.*)$", re.I)
CYR = "абвгдежзиклмнопрстуфхцчшщэюя"
LAT = "abcdefghijklmnopqrstuvwxyz"
ORDINALS = {"перв": 1, "втор": 2, "трет": 3, "четверт": 4, "пят": 5, "шест": 6, "седьм": 7, "восьм": 8}
ORD_END = ("ый", "ой", "ий", "ая", "ья", "ое", "ье", "ую", "ью")
HEAD_FILLERS = {"давай", "давайте", "ну", "ок", "окей", "хорошо", "выбираю", "беру", "тогда", "пусть", "лучше",
                "значит", "мой", "ответ", "выбор"}
TAIL_FILLERS = {"пожалуйста", "спасибо", "плиз"}
VARIANT_WORDS = {"вариант", "варианта", "варианту", "вариантом", "пункт"}
YES = {"да", "давай", "давайте", "ок", "окей", "ok", "согласен", "согласна", "yes", "годится", "идет"}
NO = {"нет", "no"}


def is_answer_head(rest):
    """Хвост заголовка записи журнала (всё после времени) → это ответ (окно вопросов или ответ в чате)."""
    return (rest or "").strip() in HEADS


def answer_body(rest, body):
    """Тело записи ответа в том виде, какой разбирают строгие читатели (запуск окон, ночь, выгрузка): у записи «ответ в
    чате» без служебных строк «вариант:» и «дословно:» — ровно «вопрос: …» и «ответ: …», как у окна вопросов. Строки
    в другом порядке или лишние — тело как есть (строгий читатель откажет)."""
    if (rest or "").strip() != "· " + CHAT_NOTE:
        return body
    lines = (body or "").split("\n")
    if len(lines) == 4 and lines[1].startswith("ответ: ") and lines[2].startswith(CHAT_META[0]) \
            and lines[3].startswith(CHAT_META[1]):
        return "\n".join(lines[:2])
    return body


def _one_line(s):
    """Как у хука answer: «→» и ёлочки — пробел, все пробелы и переводы строк — один пробел."""
    return re.sub(r"\s+", " ", re.sub(r"[→«»]", " ", s or "")).strip()


def _strip_md(s):
    return re.sub(r"(\*\*|__)", "", s).strip()


def _label(m):
    return m.group("l1") or m.group("l2")


def _norm_label(s):
    """Буква без регистра, ё как е; латинская a — как кириллическая а (одна и та же буква на вид и первая в обоих)."""
    s = s.lower().replace("ё", "е")
    return "а" if s == "a" else s


def _sequence_ok(labels):
    """Метки идут подряд с начала: 1, 2, 3… или А, Б, В… (A, B, C…)."""
    if all(x.isdigit() for x in labels):
        return [int(x) for x in labels] == list(range(1, len(labels) + 1))
    low = [x.lower().replace("ё", "е") for x in labels]
    for abc in (CYR, LAT):
        if low == list(abc[:len(low)]):
            return True
    return False


def parse_question(text):
    """Сообщение ассистента → (id, вопрос одной строкой с «[id]» в начале, [(метка, текст варианта)]) или None —
    не вопрос с [id] и вариантами по правилам шапки модуля."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    qs = [(i, m) for i, m in ((i, QUESTION_RE.match(ln)) for i, ln in enumerate(lines)) if m]
    if len(qs) != 1:
        return None  # вопроса с [id] нет или их несколько — какой из них отвечен, не понять
    qi, qm = qs[0]
    first = next((i for i in range(qi + 1, len(lines)) if OPTION_RE.match(lines[i])), None)
    if first is None:
        return None
    opts, end = [], first
    for i in range(first, len(lines)):
        m = OPTION_RE.match(lines[i])
        if m:
            opts.append((_label(m), _strip_md(m.group("text"))))
            end = i
        elif lines[i][:1] in (" ", "\t") and lines[i].strip() and end == i - 1:
            opts[-1] = (opts[-1][0], opts[-1][1] + " " + _strip_md(lines[i]))  # продолжение варианта с отступом
            end = i
        elif lines[i].strip():
            break
    labels = [o[0] for o in opts]
    if not _sequence_ok(labels):
        return None
    tail = lines[end + 1:]
    if any(OPTION_RE.match(ln) for ln in tail):
        return None  # вторая группа вариантов — к какой относится ответ, не понять
    if any("?" in ln for ln in lines[:qi] + tail):
        return None  # другой вопрос в сообщении — «да» могло быть ответом на него
    q_from = lines[qi][qm.start(1) - 1:]  # с «[id]»: «Нужно решить:» и разметку слева не берём
    question = _one_line(_strip_md(" ".join([q_from] + lines[qi + 1:first])))
    return qm.group(1).lower(), question, opts


def _words(s):
    return re.findall(r"[\w]+(?:-[\w]+)*", s)


def _ordinal(w):
    for stem, n in ORDINALS.items():
        if w.startswith(stem) and w[len(stem):] in ORD_END:
            return n
    return None


def _starts_with(text, word):
    ws = _words(text.lower().replace("ё", "е"))
    return bool(ws) and ws[0] == word


def pick(reply, qid, opts):
    """Ваше сообщение → индекс выбранного варианта в opts или None (не однозначный выбор одного варианта)."""
    r = (reply or "").strip()
    if not r or "?" in r or "\n" in r.strip():
        return None  # встречный вопрос или многострочный текст — не выбор
    r = r.lower().replace("ё", "е")
    m = re.match(r"^\[(" + QID + r")\]\s*", r)
    if m:
        if m.group(1) != qid:
            return None  # ответ с чужим id
        r = r[m.end():]
    r = r.strip(" \t.!;,)")
    labels = [_norm_label(o[0]) for o in opts]
    # «А — <начало текста варианта>»: текст после метки должен совпасть с началом текста этого варианта
    m = re.match(r"^\(?([а-яa-z]|\d{1,2})\)?\s*[—–\-.:)]\s*(\S.*)$", r)
    if m and _norm_label(m.group(1)) in labels:
        k = labels.index(_norm_label(m.group(1)))
        said, have = _words(m.group(2)), _words(opts[k][1].lower().replace("ё", "е"))
        return k if said and have[:len(said)] == said else None
    ws = _words(r)
    while len(ws) > 1 and ws[0] in HEAD_FILLERS:
        ws = ws[1:]
    while len(ws) > 1 and ws[-1] in TAIL_FILLERS:
        ws = ws[:-1]
    if len(ws) > 1 and ws[0] in VARIANT_WORDS:
        ws = ws[1:]
    elif len(ws) > 1 and ws[-1] in VARIANT_WORDS:
        ws = ws[:-1]
    if len(ws) != 1:
        return None  # два варианта, отрицание, условие, «не знаю» — не выбор одного
    w = _norm_label(ws[0])
    if w in labels:
        return labels.index(w)
    n = _ordinal(w)
    if n is not None:
        return n - 1 if n <= len(opts) else None
    if w in YES or w in NO:
        if w in YES and len(opts) == 1:
            return 0
        word = "да" if w in YES else "нет"
        hit = [k for k, o in enumerate(opts) if _starts_with(o[1], word)]
        return hit[0] if len(hit) == 1 else None
    return None


def chat_record(assistant_text, reply):
    """Последнее сообщение ассистента и ваш ответ → (пометка, тело записи) или None — сообщение не вопрос с [id] и
    вариантами (тогда ваш текст — обычная строка журнала, без записи об ответе)."""
    q = parse_question(assistant_text)
    if q is None:
        return None
    qid, question, opts = q
    said = re.sub(r"\s+", " ", reply or "").strip()
    k = pick(reply, qid, opts)
    if k is None:
        return CHAT_NONE_NOTE, "вопрос: %s\nдословно: %s" % (question, said)
    label, text = opts[k]
    # буква — часть варианта, как в окне вопросов («А — …»); номер — лишь нумерация списка, ответ — текст варианта
    answer = text if label.isdigit() else "%s — %s" % (label, text)
    return CHAT_NOTE, "вопрос: %s\nответ: %s\nвариант: %s\nдословно: %s" % (question, _one_line(answer), label, said)
