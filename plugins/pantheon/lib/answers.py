"""Ответ владельца на вопрос с [id]: в окне вопросов и в чате (metis-0405, решение владельца 01.11 «Засчитывать
ответ в чате»). Только стандартная библиотека: модуль грузят хук (hooks/ctx.py) и pantheon (lib/*).

Записи ответа в журнале owner-log (`## <время> · <пометка>`, пометку ставит только хук, ввод владельца её не получает):
- «окно вопросов» — выбор в окне вопросов (хук answer): «вопрос: [id] …», «ответ: <вариант>», иногда «заметка: …»;
- «ответ в чате» — однозначный выбор варианта обычным сообщением прямо после вопроса Зевса (хук owner-log):
  «вопрос: [id] …», «ответ: <вариант>», «вариант: <буква или номер>», «дословно: <ваше сообщение>»;
- «ответ в чате не распознан» — после вопроса с [id] и вариантами ваше сообщение не выбрало ровно один вариант или
  сам вопрос неоднозначен: «вопрос: [id] …», «причина: …», «дословно: …». Это не ответ: ни consent, ни другие
  читатели журнала её не берут.

Вопрос в чате — последнее сообщение ассистента перед вашим, из транскрипта этой сессии: строка, которая начинается с
«[<id>]» (перед ним можно «Нужно решить:» и разметку **, #, >, -), и под ней варианты, каждый своей строкой: «А — …»,
«а) …», «(а) …», «1. …», «**Б.** …». Нет такой строки или вариантов — ответа не ждём, записи нет. Ответ на него
засчитывается, только если вопрос однозначен, иначе любой ответ — «не распознан» с причиной:
- строка с [id] в сообщении одна (их несколько — «не распознан» по каждому id);
- буквы вариантов идут подряд с А (или A), номера — с 1;
- знаков «?» нет нигде, кроме строк вопроса и вариантов, и после вариантов нет второй группы вариантов — иначе «да»
  могло бы относиться к другому вопросу того же сообщения.

Ответ — выбор ровно одного варианта: буква или номер варианта («а», «Б», «2»), порядковое слово («второй»), то же с
«вариант» и вежливыми словами в начале («давай вариант а», «беру б», «а, пожалуйста»), «[id] А», «А — <начало текста
варианта>»; «да» (и «ок», «давай», «согласен») — при одном варианте или когда ровно один вариант начинается словом «да»;
«нет» — когда ровно один вариант начинается словом «нет». Всё прочее — не ответ: два варианта, отрицание («не а»),
встречный вопрос (есть «?»), «не знаю», лишние слова и условия («а, но потом»). Общее «да» при нескольких вариантах,
ни один из которых не начинается словом «да», — тоже не ответ.

Цитата варианта (metis-0843) — тоже выбор: метка и начало текста варианта, в кавычках или без, целиком или до «…», и
после неё — ничего или короткое подтверждение не длиннее трёх слов: «"А — да, все три части (совет)." - да»,
«1. Да — … убери да» (на вариант «Да — убери …»), «"А — …" - этот вариант». Каждое слово подтверждения — «да», «ок»,
«давай», «согласен», «этот вариант», вежливое слово или слово из текста этого варианта. Любое другое слово — условие:
«А — давай завтра», «А — ок, после ревью», «"А — …" да, частично» — не ответ, как и подтверждение с отрицанием («нет»,
«но», «только», «если», «или») и текст после метки, который не начало этого варианта. Сообщение, набранное в английской раскладке
вместо русской («f», «- 'njn dfhbfyn»), разбирается ещё раз по клавишам ЙЦУКЕН: латинские слова — как русские.

Остаток (модель угроз — README guard): «да», «ок», «давай» выбирают вариант без буквы, если вариант один или ровно
один начинается словом «да». Владелец мог ответить «да» не на вопрос, а на текст вокруг него; это сужено правилами
выше (одна строка с [id], ни одного «?» вне вопроса и вариантов), но не снято — решение владельца 01.11 этот риск
принимает. Текст вопроса пишет Зевс, как и в окне вопросов: подменить вопрос может только тот, кто пишет его сообщения.
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
# цитата варианта (metis-0843): кавычки перед ней, хвост после неё — подтверждение не длиннее QUOTE_TAIL слов
QUOTES = "\"'«»“”„‘’@ "
QUOTE_TAIL = 3
QUOTE_OK = {"этот", "эта", "это", "вот", "его", "так"} | HEAD_FILLERS | TAIL_FILLERS | VARIANT_WORDS
QUOTE_STOP = {"не", "но", "если", "кроме", "без", "только", "или", "либо", "потом", "позже", "однако", "пока",
              "сначала", "сперва"}
# английская раскладка вместо русской (ЙЦУКЕН, как на PC): буквы и знаки на месте русских букв; «@» — кавычка
_EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`" + "QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>~" + "@&/"
_RU = "йцукенгшщзхъфывапролджэячсмитьбюё" + "ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮЁ" + "\"?."
EN_RU = str.maketrans(_EN, _RU)


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


WHY_MANY = "в сообщении несколько вопросов с [id]"
WHY_ORDER = "варианты не по порядку"
WHY_GROUPS = "после вариантов вторая группа вариантов"
WHY_OTHER = "в сообщении есть другой вопрос (знак «?» вне вопроса и вариантов)"
WHY_REPLY = "ответ не выбирает ровно один вариант"


def _question_text(lines, qi, qm, upto):
    q_from = lines[qi][qm.start(1) - 1:]  # с «[id]»: «Нужно решить:» и разметку слева не берём
    return _one_line(_strip_md(" ".join([q_from] + lines[qi + 1:upto])))


def scan_question(text):
    """Сообщение ассистента → None (в нём нет вопроса с [id] и вариантами — ответа ждать не от чего),
    ("ok", id, вопрос одной строкой с «[id]» в начале, [(метка, текст варианта)]) или
    ("unclear", [(id, вопрос)], причина) — вопрос с [id] и вариантами есть, но какой выбор чем считать, однозначно не
    понять (правила шапки модуля): тогда любой ответ — «не распознан», а не согласие."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    qs = [(i, m) for i, m in ((i, QUESTION_RE.match(ln)) for i, ln in enumerate(lines)) if m]
    if not qs:
        return None
    qi, qm = qs[0]
    first = next((i for i in range(qi + 1, len(lines)) if OPTION_RE.match(lines[i])), None)
    if first is None:
        return None  # [id] без вариантов — не вопрос с выбором
    if len(qs) > 1:
        # несколько вопросов с [id] — к какому относится «да», не понять; каждый id получит «не распознан»
        return "unclear", [(m.group(1).lower(), _question_text(lines, i, m, i + 1)) for i, m in qs], WHY_MANY
    question = _question_text(lines, qi, qm, first)
    unclear = ("unclear", [(qm.group(1).lower(), question)])
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
    if not _sequence_ok([o[0] for o in opts]):
        return unclear + (WHY_ORDER,)
    tail = lines[end + 1:]
    if any(OPTION_RE.match(ln) for ln in tail):
        return unclear + (WHY_GROUPS,)  # к какой группе относится ответ, не понять
    if any("?" in ln for ln in lines[:qi] + tail):
        return unclear + (WHY_OTHER,)  # «да» могло быть ответом на другой вопрос
    return "ok", qm.group(1).lower(), question, opts


def parse_question(text):
    """Сообщение ассистента → (id, вопрос, [(метка, текст варианта)]) — однозначный вопрос с [id] и вариантами, иначе
    None (см. scan_question)."""
    q = scan_question(text)
    return q[1:] if q and q[0] == "ok" else None


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


def _from_en_layout(s):
    """Текст, набранный в английской раскладке вместо русской («'njn dfhbfyn» → «этот вариант»): слова с латинскими
    буквами — по клавишам ЙЦУКЕН, остальное (кириллица, вставленная цитата, тире, «…») — как есть."""
    def word(m):
        t = m.group(0)
        body = t.rstrip(".,")  # точка и запятая в конце слова — знак, а не «ю» и «б»
        return body.translate(EN_RU) + t[len(body):]
    return re.sub(r"\S*[A-Za-z]\S*", word, s)


def _quote_pick(r, labels, opts):
    """Ответ — цитата варианта с меткой и, может быть, короткое подтверждение после неё (metis-0843):
    «"А — да, все три части (совет)." - да», «1. Да — … убери да», «"А — …" - этот вариант», «А — в чате». Кавычки в
    начале не мешают. Текст после метки до «…» (или, без «…», сколько совпало по словам) — начало текста этого варианта;
    хвост после него — пусто или подтверждение не больше QUOTE_TAIL слов, и каждое его слово — «да» (и «ок», «давай»,
    «согласен»), «этот вариант», «вот этот», вежливое слово или слово из текста этого же варианта («убери да» на «Да —
    убери …»). Любое другое слово — условие («давай завтра», «ок, после ревью», «да, частично») и не выбор; отрицание и
    условия («нет», «но», «только», «кроме», «если», «или»…) — не выбор, даже если они есть в тексте варианта.
    → (True, индекс) — выбор; (True, None) — цитата варианта, но не выбор; (False, None) — это не цитата варианта."""
    m = re.match(r"^\(?([а-яa-z]|\d{1,2})\)?\s*[—–\-.:)]\s*(\S.*)$", r.lstrip(QUOTES))
    if not m or _norm_label(m.group(1)) not in labels:
        return False, None
    k = labels.index(_norm_label(m.group(1)))
    have = _words(opts[k][1].lower().replace("ё", "е"))
    cut = re.search(r"…|\.\.\.", m.group(2))
    if cut:
        said, tail = _words(m.group(2)[:cut.start()]), _words(m.group(2)[cut.end():])
        if have[:len(said)] != said:
            return True, None  # до «…» — не начало текста этого варианта
    else:
        said = _words(m.group(2))
        n = 0
        while n < min(len(said), len(have)) and said[n] == have[n]:
            n += 1
        said, tail = said[:n], said[n:]
    if not tail:
        return True, (k if said or cut else None)
    if len(tail) > QUOTE_TAIL or any(w in QUOTE_STOP or w in NO for w in tail):
        return True, None
    if all(w in YES or w in QUOTE_OK or w in have for w in tail):
        return True, k  # хвост — только подтверждение и слова этого варианта; «завтра», «частично» — условие
    return True, None


def pick(reply, qid, opts):
    """Ваше сообщение → индекс выбранного варианта в opts или None (не однозначный выбор одного варианта). Набранное
    в английской раскладке («f», «'njn dfhbfyn») разбирается ещё раз в русской."""
    k = _pick(reply, qid, opts)
    if k is None and re.search(r"[A-Za-z]", reply or ""):
        conv = _from_en_layout(reply)
        if conv != reply:
            k = _pick(conv, qid, opts)
    return k


def _pick(reply, qid, opts):
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
    # «А — <начало текста варианта>» и цитата варианта с подтверждением после неё
    quoted, k = _quote_pick(r, labels, opts)
    if quoted:
        return k
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
    """Последнее сообщение ассистента и ваш ответ → [(пометка, тело записи)] — по записи на запись журнала; пусто —
    сообщение не вопрос с [id] и вариантами (тогда ваш текст — обычная строка журнала, без записи об ответе)."""
    q = scan_question(assistant_text)
    if q is None:
        return []
    said = re.sub(r"\s+", " ", reply or "").strip()
    if q[0] == "unclear":
        return [(CHAT_NONE_NOTE, "вопрос: %s\nпричина: %s\nдословно: %s" % (question, q[2], said))
                for _, question in q[1]]
    _, qid, question, opts = q
    k = pick(reply, qid, opts)
    if k is None:
        return [(CHAT_NONE_NOTE, "вопрос: %s\nпричина: %s\nдословно: %s" % (question, WHY_REPLY, said))]
    label, text = opts[k]
    # буква — часть варианта, как в окне вопросов («А — …»); номер — лишь нумерация списка, ответ — текст варианта
    answer = text if label.isdigit() else "%s — %s" % (label, text)
    return [(CHAT_NOTE, "вопрос: %s\nответ: %s\nвариант: %s\nдословно: %s" % (question, _one_line(answer), label, said))]
