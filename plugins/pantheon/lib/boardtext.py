"""Автоблок доски — отдельный файл ~/ai/pantheon/board-auto.md (metis-0397, исследование 24.10 разд. 5, решение Зевса
«вариант Б»): открытые PR и вердикты argus, пачки, неделя, свежие STATUS.md и ответы владельца — без ручной правки
Зевса. Собирает плановый проход доски (`pantheon board`, задача тика) тем же путём, что виды доски (metis-0234, 0069,
0248); модель не зовёт, в сеть не ходит. Входы не менялись — тик пропускает проход (metis-0149); текст не изменился —
файл не пишется.

У файла один писатель — этот проход: board.md код не пишет вовсе, поэтому строки Зевса целы при любом входе и гонки с
его правкой нет. В board.md вверху одна строка `![[board-auto]]` (её ставит Зевс): Obsidian показывает блок внутри
доски, а хук после сжатия и /clear кладёт файл в контекст Зевса (hooks/ctx.py, file_for_context). Строки встраивания
вверху board.md нет — тревога у тика (embed_ok).

В блок идут только числа, SHA, перечисления, [id] и буква варианта (SEC-13): свободного текста из STATUS.md, ревью,
задач и журнала владельца в нём нет — ни заголовков пачек, ни последних строк STATUS, ни слов ответа. Каждое значение
проходит свой шаблон, а строка — чистку от управляющих и bidi-знаков (clean). Весь файл — до BLOCK_MAX знаков: не
вошедшие строки сводятся в «…не вошло строк: N». Штамп «собрано ДД.ММ ЧЧ:ММ из N файлов» — время сборки, давшей этот
текст; одна смена штампа файл не переписывает. Запись — уникальный временный файл рядом и rename.

Входы — только файлы:
- открытые PR — кэш `pantheon autoclose fetch` (STATE/autoclose-prs.json, ключ open_prs из `gh pr list --state open`:
  номер, head, задачи, задето ли ядро); ядро — сливает владелец, не ядро — «принять» Зевса;
- вердикты argus — directions/*/review-<N>-argus*.md: «Вердикт: …» и head из начала файла; у каждой дорожки (a, b, без
  буквы) — самый свежий файл; вердикт на другом head помечен «старый head»;
- пачки — карточки type story не done/dropped с задачами в doing, review или waiting (только id и счёт);
- неделя — целые проценты снимка лимита (их даёт вызывающий);
- «Ждёт вас» и «Руками» (metis-0402 п. 4) — карточки задач с «Кому» = Владелец, не закрытые: с вопросом (question или
  ждёт человека) — «Ждёт вас», остальные — «Руками»; только id. Текстовые строки этих разделов в board.md блок не
  читает: пункт без карточки сюда не попадёт — заведите карточку (`pantheon task new --owner owner`);
- STATUS.md направлений, правленные за сутки, — только имя направления и время правки;
- ответы владельца — журнал owner-log: выбор в окне вопросов или в чате на вопрос «[id] …» (zeus.md, пометку ставит хук) и ответ
  галочкой на карточке (board.jsonl), за сутки — [id], время и буква варианта (или да/нет). Блок — сводка для глаз, а не
  согласие: согласие проверяет только `pantheon consent <id>`.

Свежесть: watch_files — файлы, по которым тик сверяет, что сборка прошла после изменения входов (тревога, если входы
менялись, а сборки нет 10 мин и больше — pantheon.py board_auto_watch).

Только стандартная библиотека: модуль грузит и хук (hooks/ctx.py).
"""
import glob
import json
import os
import re
import tempfile
import time
import unicodedata
from datetime import datetime

AUTO_NAME = "board-auto.md"
EMBED = "![[board-auto]]"
EMBED_LINES = 30             # строка встраивания — среди первых строк board.md («вверху»)
DAY = 86400
WATCH_GAP = 10 * 60          # входы менялись, а сборки нет столько — тревога
BLOCK_MAX = 1200             # знаков во всём файле
MAX_PR, MAX_BATCH, MAX_STATUS, MAX_DECISION, MAX_IDS = 8, 3, 6, 5, 3
MAX_OWNER = 10  # id карточек владельца в строке «Ждёт вас» / «Руками»
REVIEW_RE = re.compile(r"review-([1-9]\d{0,5})-argus(?:-?([a-z]?)(\d*))?\.md")
VERDICT_RE = re.compile(r"Вердикт\**\s*:\s*\**\s*([А-Яа-яЁё]+)")
VERDICTS = ("принять", "вернуть", "частично", "отклонить")
HEAD_RE = re.compile(r"\bHead\b\**:?\**\s*`?([0-9a-f]{7,40})\b")
REPO_RE = re.compile(r"([\w.-]+/[\w.-]+)#(\d+)")
ID_RE = re.compile(r"[a-z][a-z0-9]{0,30}(?:-[a-z0-9]{1,30}){0,4}")
SHA_RE = re.compile(r"[0-9a-f]{4,40}")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,60}")
VARIANT_RE = re.compile(r"\s*([А-ЯЁA-Z]\d?)\s*(?:$|[.,;:!)—–-])")  # «А», «Б1 — …»; не «В пятницу»
YESNO_RE = re.compile(r"\s*(да|нет)\s*(?:$|[.,;:!—–-])", re.I)
WORK = ("doing", "review", "waiting")
STATUS_RU = {"doing": "в работе", "review": "на проверке", "waiting": "ждёт"}
OWN_Q = re.compile(r"вопрос: \[([a-z0-9][a-z0-9-]{0,40})\]", re.I)
ANSWER_HEADS = ("· окно вопросов", "· ответ в чате")  # = lib/answers.py HEADS (metis-0405; сверяет test_chat_answer)
HEAD_LINE = "<!-- файл собирает плановый проход (pantheon board, metis-0397); руками не править — перезапишется -->"
STAMP_RE = re.compile(r" · собрано \d\d\.\d\d \d\d:\d\d из \d+ файл\w*")


def hm(t):
    return datetime.fromtimestamp(t).strftime("%d.%m %H:%M")


def clean(s):
    """Строка без управляющих, bidi и прочих невидимых знаков (категории C*), пробелы схлопнуты."""
    s = "".join(ch if unicodedata.category(ch)[0] != "C" else " " for ch in str(s))
    return re.sub(r"\s+", " ", s).strip()


def _ok(rx, s):
    return isinstance(s, str) and rx.fullmatch(s) is not None


def _read(p, n=None):
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            return fh.read(n) if n else fh.read()
    except OSError:
        return None


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return None


# --- входы ------------------------------------------------------------------------------------------------------

def open_prs(cache_path):
    """Открытые PR из кэша autoclose fetch: [{repo, number, head, ids, core}] по репозиторию и номеру; нет данных — None.
    Значения не по шаблону (имя репозитория, head, id задачи) отбрасываются."""
    try:
        with open(cache_path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        return None
    by_repo = st.get("open_prs") if isinstance(st, dict) else None
    if not isinstance(by_repo, dict):
        return None
    out = []
    for repo, prs in sorted(by_repo.items()):
        for p in prs if isinstance(prs, list) else []:
            if isinstance(p, dict) and isinstance(p.get("number"), int) and not isinstance(p.get("number"), bool):
                head = p.get("head") if _ok(SHA_RE, p.get("head")) else ""
                out.append({"repo": str(repo), "number": p["number"], "head": head,
                            "ids": [i for i in p.get("ids") or [] if _ok(ID_RE, i)], "core": p.get("core") is True})
    return sorted(out, key=lambda p: (p["repo"], p["number"]))


def cache_broken(cache_path):
    """Кэш PR есть, но не JSON-объект (оборван, испорчен) — сломанный вход: тревога у тика. Нет файла или нет ключа
    open_prs (fetch ещё не прошёл после выпуска) — не сбой."""
    try:
        with open(cache_path, encoding="utf-8") as fh:
            return not isinstance(json.load(fh), dict)
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True


def review_files(pantheon):
    return sorted(glob.glob(os.path.join(pantheon, "directions", "*", "review-*-argus*.md")))


def reviews(pantheon):
    """{номер PR: {дорожка: {verdict, head, repo, mtime}}} — у дорожки самый свежий файл ревью. Вердикт вне VERDICTS —
    «иное»: слово из файла в блок не идёт."""
    out = {}
    for p in review_files(pantheon):
        m = REVIEW_RE.fullmatch(os.path.basename(p))
        mt = _mtime(p)
        if not m or mt is None:
            continue
        lane = m.group(2) if m.group(2) and m.group(2) != "r" else ""
        text = _read(p, 6000) or ""
        v = VERDICT_RE.search(text)
        h = HEAD_RE.search(text)
        r = REPO_RE.search(text.split("\n", 1)[0])
        verdict = (v.group(1).lower() if v.group(1).lower() in VERDICTS else "иное") if v else ""
        rec = {"verdict": verdict, "head": h.group(1) if h else "",
               "repo": r.group(1) if r and r.group(2) == m.group(1) else "", "mtime": mt}
        cur = out.setdefault(int(m.group(1)), {}).get(lane)
        if cur is None or mt > cur["mtime"]:
            out[int(m.group(1))][lane] = rec
    return out


def batches(tasks):
    """Пачки в работе: [(id, [(id задачи, статус)], закрыто, всего)]. tasks — load_tasks: id → (путь, шапка, …).
    Заголовок пачки — свободный текст, в блок не идёт."""
    kids = {}
    for tid, rec in tasks.items():
        h = rec[1]
        if h.get("type") == "task" and h.get("parent"):
            kids.setdefault(h["parent"], []).append((tid, h.get("status")))
    out = []
    for sid, rec in tasks.items():
        h = rec[1]
        if h.get("type") != "story" or h.get("status") in ("done", "dropped") or not _ok(ID_RE, sid):
            continue
        ks = sorted(kids.get(sid) or [])
        work = [(i, s) for i, s in ks if s in WORK and _ok(ID_RE, i)]
        if work:
            out.append((h.get("priority", 2) if isinstance(h.get("priority"), int) else 2, sid,
                        work, sum(1 for _, s in ks if s in ("done", "dropped")), len(ks)))
    out.sort()
    return [x[1:] for x in out[:MAX_BATCH]]


def owner_cards(tasks, is_owner):
    """Карточки на владельце (Кому = Владелец, не закрыты; metis-0402 п. 4): {"ask": [id], "do": [id]} — вопрос (есть
    question или ждёт человека) идёт в «Ждёт вас», остальное — в «Руками». Только id: заголовок — свободный текст."""
    out = {"ask": [], "do": []}
    rows = []
    for tid, rec in tasks.items():
        h = rec[1]
        if h.get("status") in ("done", "dropped") or not _ok(ID_RE, tid) or not is_owner(h):
            continue
        ask = bool(h.get("question")) or (h.get("status") == "waiting" and h.get("waiting_on") == "human")
        prio = h.get("priority") if isinstance(h.get("priority"), int) and not isinstance(h.get("priority"), bool) else 2
        rows.append((prio, tid, "ask" if ask else "do"))
    for _, tid, kind in sorted(rows):
        out[kind].append(tid)
    return out


def status_files(pantheon):
    return sorted(glob.glob(os.path.join(pantheon, "directions", "*", "STATUS.md")))


def statuses(pantheon, t):
    """STATUS.md, правленные за сутки: [(направление, время правки)] — свежие первыми. Текст файла в блок не идёт."""
    out = []
    for p in status_files(pantheon):
        mt = _mtime(p)
        name = os.path.basename(os.path.dirname(p))
        if mt is None or t - mt > DAY or not _ok(NAME_RE, name):
            continue
        out.append((name, mt))
    out.sort(key=lambda x: -x[1])
    return out[:MAX_STATUS]


def variant(answer):
    """Буква варианта («А», «Б1») или да/нет из начала ответа; иначе "" — слова ответа в блок не идут."""
    if not isinstance(answer, str):
        return ""
    m = VARIANT_RE.match(answer) or YESNO_RE.match(answer)
    return m.group(1).lower() if m and m.re is YESNO_RE else (m.group(1) if m else "")


def decisions(zeus_md, board_jsonl, t):
    """Ответы владельца за сутки: [(время, id, вариант, откуда)] — свежие первыми. Только журнал owner-log: выбор в
    окне вопросов или в чате на вопрос «[id] …» и ответ галочкой на карточке (как у `pantheon consent`)."""
    out = []
    text = _read(zeus_md) or ""
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    for i, m in enumerate(heads):
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        q = OWN_Q.match(body)
        if m.group(2).strip() not in ANSWER_HEADS or not q:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue
        a = re.search(r"^ответ: (.*)$", body, re.M)
        if a and 0 <= t - ts <= DAY:
            out.append((ts, q.group(1).lower(), variant(a.group(1)), m.group(2).strip()[2:]))
    for line in (_read(board_jsonl) or "").splitlines():
        try:
            rec = json.loads(line)
            ts = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, AttributeError):
            continue
        q, a = rec.get("question"), rec.get("answer")
        if rec.get("kind") != "answer" or not _ok(ID_RE, rec.get("id")) or not isinstance(q, str) \
                or not isinstance(a, str) or re.search(r"%%|<", q) or not 0 <= t - ts <= DAY:
            continue
        out.append((ts, rec["id"], variant(a), "доска"))
    out.sort(key=lambda x: -x[0])
    return out[:MAX_DECISION]


def owner_log(state):
    return [os.path.join(state, "owner-log", "zeus.md"), os.path.join(state, "owner-log", "board.jsonl")]


def watch_files(pantheon, state):
    """Файлы входов для отпечатка свежести (без задач и кэша PR — их отпечаток по содержимому даёт вызывающий):
    ревью, STATUS.md, decisions.md, журнал владельца (у него — только размер и время правки)."""
    return review_files(pantheon) + status_files(pantheon) + [os.path.join(pantheon, "decisions.md")] + owner_log(state)


def collect(pantheon, state, tasks, t, week=None, owner=None):
    """Все входы блока одним словарём; files — сколько файлов прочитано (для штампа). owner — шапка → на владельце
    ли карточка (tasks.Roles и assignee у вызывающего); без него разделов «Ждёт вас» и «Руками» нет."""
    cache = os.path.join(state, "autoclose-prs.json")
    zeus_md, board_jsonl = owner_log(state)
    files = len(review_files(pantheon)) + len(status_files(pantheon)) + len(tasks) \
        + sum(1 for p in (cache, zeus_md, board_jsonl) if os.path.isfile(p))
    return {"prs": open_prs(cache), "reviews": reviews(pantheon), "batches": batches(tasks), "week": week,
            "statuses": statuses(pantheon, t), "decisions": decisions(zeus_md, board_jsonl, t), "files": files,
            "broken": ["autoclose-prs.json"] if cache_broken(cache) else [],
            "owner": owner_cards(tasks, owner) if owner else None}


# --- блок -------------------------------------------------------------------------------------------------------

def pr_line(p, revs):
    lanes = revs.get(p["number"]) or {}
    lanes = {k: v for k, v in lanes.items() if not v["repo"] or v["repo"] == p["repo"]}
    parts = []
    for lane in sorted(lanes):
        r = lanes[lane]
        old = p["head"] and r["head"] and not p["head"].startswith(r["head"]) and not r["head"].startswith(p["head"])
        parts.append((lane + " " if lane else "") + (r["verdict"] or "без вердикта")
                     + (f" на старом head {r['head'][:7]}" if old else ""))
    who = "ядро → сливает владелец" if p["core"] else "не ядро → «принять» Зевса"
    ids = f" ({', '.join(p['ids'][:MAX_IDS])})" if p["ids"] else ""
    repo = p["repo"].rsplit("/", 1)[-1]
    repo = repo if _ok(NAME_RE, repo) else "?"
    return (f"- PR #{p['number']} {repo}{ids} · head {p['head'][:7] or '?'} · argus: "
            + (", ".join(parts) if parts else "ревью нет") + f" · {who}")


def lines(data):
    """Строки блока без штампа (в порядке важности: неделя, PR, пачки, STATUS, ответы владельца)."""
    out = []
    w = data.get("week")
    out.append(f"- Неделя: {w} %." if isinstance(w, int) and not isinstance(w, bool) else "- Неделя: расход неизвестен.")
    own = data.get("owner")
    if isinstance(own, dict):
        for kind, label in (("ask", "Ждёт вас"), ("do", "Руками")):
            ids = [i for i in own.get(kind) or [] if _ok(ID_RE, i)]
            more = f" и ещё {len(ids) - MAX_OWNER}" if len(ids) > MAX_OWNER else ""
            out.append(f"- **{label}** ({len(ids)}): " + (", ".join(ids[:MAX_OWNER]) + more if ids else "карточек нет") + ".")
    prs = data.get("prs")
    if prs is None and "autoclose-prs.json" in (data.get("broken") or []):
        out.append("- PR: кэш открытых PR не читается — список PR неизвестен.")
    elif prs is None:
        out.append("- PR: кэша открытых PR нет — задача autoclose-fetch ещё не прошла.")
    elif not prs:
        out.append("- Открытых PR нет.")
    else:
        out += [pr_line(p, data.get("reviews") or {}) for p in prs[:MAX_PR]]
        if len(prs) > MAX_PR:
            out.append(f"- …и ещё PR: {len(prs) - MAX_PR}.")
    for sid, work, closed, total in data.get("batches") or []:
        out.append(f"- Пачка {sid}: " + ", ".join(f"{i} ({STATUS_RU.get(s, s)})" for i, s in work)
                   + f"; закрыто {closed} из {total}.")
    st = data.get("statuses") or []
    if st:
        out.append("- STATUS правлены: " + ", ".join(f"{n} {hm(mt)}" for n, mt in st) + ".")
    for ts, qid, var, src in data.get("decisions") or []:
        out.append(f"- Ответ владельца [{qid}] {hm(ts)} ({src}): " + (var or "ответ дан") + ".")
    return [clean(x) for x in out]


def render(data, t):
    """Текст файла: строка-пометка, штамп, строки блока; длиннее BLOCK_MAX — хвост строк сводится в «…не вошло»."""
    head = [HEAD_LINE, f"**Сводка прохода · собрано {hm(t)} из {int(data.get('files') or 0)} файлов**", ""]
    body = lines(data)
    text = "\n".join(head + body) + "\n"
    while len(text) > BLOCK_MAX and body:
        body = body[:-1]
        more = f"- …не вошло строк: {len(lines(data)) - len(body)}."
        text = "\n".join(head + body + [more]) + "\n"
    return text


def same(a, b):
    """Тексты равны без штампа времени и числа файлов."""
    return a is not None and b is not None and STAMP_RE.sub("", a) == STAMP_RE.sub("", b)


def sync(auto_md, text):
    """Записать файл автоблока, если текст (без штампа) изменился. → "written" | "same".
    Запись — уникальный временный файл в той же папке и rename: читатель видит либо старый файл, либо новый."""
    if same(_read(auto_md), text):
        return "same"
    d = os.path.dirname(auto_md) or "."
    fd, tmp = tempfile.mkstemp(prefix=".board-auto.", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, auto_md)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return "written"


def embed_ok(board_md):
    """Строка `![[board-auto]]` среди первых EMBED_LINES строк board.md. → True/False; board.md нет — None."""
    text = _read(board_md)
    if text is None:
        return None
    return any(ln.strip() == EMBED for ln in text.splitlines()[:EMBED_LINES])
