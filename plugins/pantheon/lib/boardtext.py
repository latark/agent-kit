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
- пачки — карточки type story не done/dropped с задачами в doing, review или waiting (только id, счёт и номер PR пачки
  из поля pr — metis-0757; поля нет — PR с ветки batch/<id> из того же кэша, metis-0799);
- неделя — целые проценты снимка лимита (их даёт вызывающий);
- «Ждёт вас» и «Руками» (metis-0402 п. 4, metis-0801) — «Ждёт вас»: все открытые карточки колонки «Нужен ответ»
  доски (waiting и waiting_on human) при любом «Кому», входящие Зевса тоже, и карточки с «Кому» = Владелец с полем
  question; «Руками» — остальные открытые карточки с «Кому» = Владелец; только id. Текстовые строки этих разделов в board.md блок не
  читает: пункт без карточки сюда не попадёт — заведите карточку (`pantheon task new --owner owner`);
- «PR слит, задача открыта» (metis-0768) — data["merged_open"] от вызывающего (lib/boardmerged.py: кэш слитых PR и журнал
  карточки, без gh): «metis-XXXX: PR #N слит D дн. назад, задача doing/review, неотмечено K», не больше MAX_MERGED строк;
- STATUS.md направлений, правленные за сутки, — только имя направления и время правки;
- отказы ролей за сутки (metis-0832) — журнал STATE/logs/handoff.jsonl (lib/handoff.py): источник, вид → кому передано
  и итоги, только из словарей HANDOFF_*; заявка Touch ID — одна, по последнему итогу;
- ответы владельца — журнал owner-log: выбор в окне вопросов или в чате на вопрос «[id] …» (zeus.md, пометку ставит хук) и ответ
  галочкой на карточке (board.jsonl), за сутки — [id], время и буква варианта (или да/нет). Блок — сводка для глаз, а не
  согласие: согласие проверяет только `pantheon consent <id>`.

Свежесть: watch_files — файлы, по которым тик сверяет, что сборка прошла после изменения входов (тревога, если входы
менялись, а сборки нет 10 мин и больше — pantheon.py board_auto_watch).

Тот же проход пишет и «Ждёт владельца» каждого направления — directions/<имя>/waiting-auto.md (metis-0829,
waiting_sync): карточки направления, PR ядра и заявки очереди слияния; STATUS.md встраивает его строкой WAIT_EMBED.

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
MAX_MERGED = 5  # строк «PR слит, задача открыта» (metis-0768)
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


def pr_stale(cache_path):
    """Репозитории, по которым gh не ответил в последнем fetch (errors без «#N»), → [(репозиторий, время последнего
    успешного ответа или None)] (metis-0808): строки их PR в кэше — прежние, блок говорит об этом, а не «Открытых PR нет»."""
    try:
        with open(cache_path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        return []
    errs = st.get("errors") if isinstance(st, dict) and isinstance(st.get("errors"), dict) else {}
    stale = st.get("stale") if isinstance(st, dict) and isinstance(st.get("stale"), dict) else {}
    out = []
    for repo in sorted(r for r in errs if isinstance(r, str) and "#" not in r):
        ts = stale.get(repo)
        out.append((repo, ts if isinstance(ts, (int, float)) and not isinstance(ts, bool) and ts > 0 else None))
    return out


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


STORY_PR_RE = re.compile(r"[A-Za-z0-9][\w.-]{0,99}/[\w.-]{1,100}#([1-9]\d{0,5})")  # поле pr пачки = tasks.STORY_PR_RE (boardtext грузится без tasks — общий импорт нельзя; равенство держит test_board_text)


def _autoclose():
    """lib/autoclose.py рядом — правило «PR пачки» (batch_prs, batch_pick) одно с карточкой и check (metis-0810).
    Только стандартная библиотека, как этот модуль; грузится лениво: хуку (hooks/ctx.py) оно не нужно."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pantheon_autoclose_bt", os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "autoclose.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def batch_branch_prs(cache_path, own_of=None):
    """{id пачки: номер PR} по ветке batch/<id> из кэша autoclose fetch (metis-0799): PR пачки, открытый не через
    `pantheon batch pr`, поля pr не ставит. Правило — autoclose.batch_prs и batch_pick, одно с карточкой пачки и check
    (metis-0810): ветка ровно batch/<id>, не форк, «часть» не мешает; открытый важнее слитого, из нескольких — больший
    номер; own_of(id пачки) — репозитории её направления в нижнем регистре (None — любые; own_of нет — любые).
    Нет кэша или он битый — {}."""
    try:
        with open(cache_path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        return {}
    A = _autoclose()
    out = {}
    for sid, rows in A.batch_prs(st).items():
        best = A.batch_pick(rows, own_of(sid) if own_of else None)
        if best:
            out[sid] = best[1]
    return out


def batches(tasks, branch_prs=None):
    """Пачки в работе: [(id, [(id задачи, статус)], закрыто, всего, номер PR пачки или None)]. tasks — load_tasks:
    id → (путь, шапка, …). Заголовок пачки — свободный текст, в блок не идёт; из поля pr — только номер, нет поля —
    номер PR с ветки batch/<id> (branch_prs — batch_branch_prs, metis-0799)."""
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
        m = STORY_PR_RE.fullmatch(h["pr"]) if isinstance(h.get("pr"), str) else None
        if work:
            out.append((h.get("priority", 2) if isinstance(h.get("priority"), int) else 2, sid,
                        work, sum(1 for _, s in ks if s in ("done", "dropped")), len(ks),
                        int(m.group(1)) if m else (branch_prs or {}).get(sid)))
    out.sort()
    return [x[1:] for x in out[:MAX_BATCH]]


def needs_answer(h):
    """= tasks.needs_answer (metis-0801): колонка «Нужен ответ» доски — waiting и waiting_on human. Модуль грузит хук, без
    tasks; равенство сверяет test_board_sync."""
    return h.get("status") == "waiting" and h.get("waiting_on") == "human"


def owner_cards(tasks, is_owner):
    """{"ask": [id], "do": [id]}, только id: заголовок — свободный текст (metis-0402 п. 4, metis-0801). «Ждёт вас» (ask)
    — все карточки колонки «Нужен ответ» доски (needs_answer) при любом «Кому»: входящие Зевса (inbox-…, owner zeus)
    ждут ответа владельца так же; плюс карточки с «Кому» = Владелец и полем question в другом статусе. Поэтому «Ждёт
    вас» ≥ колонки «Нужен ответ», а не другое число. «Руками» (do) — остальные открытые карточки с «Кому» = Владелец."""
    out = {"ask": [], "do": []}
    rows = []
    for tid, rec in tasks.items():
        h = rec[1]
        if h.get("status") in ("done", "dropped") or not _ok(ID_RE, tid):
            continue
        mine = is_owner(h)
        ask = needs_answer(h) or (mine and bool(h.get("question")))
        if not ask and not mine:
            continue
        prio = h.get("priority") if isinstance(h.get("priority"), int) and not isinstance(h.get("priority"), bool) else 2
        rows.append((prio, tid, "ask" if ask else "do"))
    for _, tid, kind in sorted(rows):
        out[kind].append(tid)
    return out


# --- «Ждёт владельца» направления (metis-0829) --------------------------------------------------------------------
# Файл directions/<имя>/waiting-auto.md рядом со STATUS.md: тот же проход и тот же один писатель, что у board-auto.md.
# STATUS.md код не пишет (его ведёт координатор): строку встраивания WAIT_EMBED ставит координатор в раздел «Ждёт
# владельца». Пункты — только id и номера (SEC-13): карточки «Ждёт ответа» и «Руками» направления (owner_cards по его
# задачам), PR ядра (сливает владелец) с задачами направления из кэша autoclose и заявки на слияние из очереди
# STATE/merge-queue (ждут Touch ID). Пункт, ставший неправдой (карточка закрыта, PR слит и ушёл из кэша, заявка снята),
# пропадает на следующем проходе: файл собирается целиком из входов. Штамп «собрано» — время сборки, давшей текст.
WAIT_NAME = "waiting-auto.md"
WAIT_EMBED = "![[directions/{name}/waiting-auto]]"
WAIT_HEAD = ("<!-- файл собирает плановый проход (pantheon board, metis-0829) из задач, кэша PR и очереди слияния; "
             "руками не править — перезапишется -->")
QUEUE_RE = re.compile(r"([A-Za-z0-9._-]+)__([A-Za-z0-9._-]+)__([1-9]\d{0,6})\.json")


def merge_queue(state):
    """Заявки на слияние в очереди (ждут Touch ID владельца): [(репозиторий, номер)] по имени файла и его содержимому."""
    out = []
    for p in sorted(glob.glob(os.path.join(state, "merge-queue", "*.json"))):
        m = QUEUE_RE.fullmatch(os.path.basename(p))
        if not m or os.path.islink(p):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                req = json.load(fh)
        except (OSError, ValueError):
            continue
        repo = f"{m.group(1)}/{m.group(2)}"
        if isinstance(req, dict) and req.get("repo") == repo and req.get("pr") == int(m.group(3)):
            out.append((repo, int(m.group(3))))
    return out


def waiting(pantheon, state, tasks, is_owner, prs):
    """{направление: {"ask", "do", "prs", "queue"}} для каждой папки directions/<имя> со STATUS.md. prs — open_prs
    (None — кэша нет: PR не показываем). PR идёт в направление, если среди его задач есть задача этого направления."""
    queued = set(merge_queue(state))
    out = {}
    for p in status_files(pantheon):
        d = os.path.basename(os.path.dirname(p))
        if not _ok(NAME_RE, d):
            continue
        own = owner_cards({tid: rec for tid, rec in tasks.items() if rec[1].get("direction") == d}, is_owner)
        mine = [x for x in prs or [] if any((tasks.get(i) or (None, {}))[1].get("direction") == d for i in x["ids"])]
        out[d] = {"ask": own["ask"], "do": own["do"], "prs": [x for x in mine if x["core"]],
                  "queue": [x["number"] for x in mine if (x["repo"], x["number"]) in queued]}
    return out


def waiting_render(item, t, files=0):
    lines = [WAIT_HEAD, f"**Ждёт владельца · собрано {hm(t)} из {int(files)} файлов**", ""]
    for kind, label in (("ask", "Ждёт ответа"), ("do", "Руками")):
        ids = [i for i in item.get(kind) or [] if _ok(ID_RE, i)]
        if ids:
            more = f" и ещё {len(ids) - MAX_OWNER}" if len(ids) > MAX_OWNER else ""
            lines.append(f"- **{label}** ({len(ids)}): " + ", ".join(ids[:MAX_OWNER]) + more + ".")
    for n in item.get("queue") or []:
        lines.append(f"- Заявка на слияние PR #{n} ждёт Touch ID.")
    for p in (item.get("prs") or [])[:MAX_PR]:
        repo = p["repo"].rsplit("/", 1)[-1]
        ids = f" ({', '.join(p['ids'][:MAX_IDS])})" if p["ids"] else ""
        lines.append(f"- PR #{p['number']} {repo if _ok(NAME_RE, repo) else '?'}{ids} · ядро → сливает владелец.")
    if len(lines) == 3:
        lines.append("- Ничего не ждёт.")
    return "\n".join(clean(x) for x in lines) + "\n"


def waiting_sync(pantheon, state, tasks, is_owner, t):
    """Записать waiting-auto.md каждого направления → [направления, где файл переписан]. Текст без штампа тот же —
    файл не трогается (same)."""
    prs = open_prs(os.path.join(state, "autoclose-prs.json"))
    made = []
    for d, item in sorted(waiting(pantheon, state, tasks, is_owner, prs).items()):
        if sync(os.path.join(pantheon, "directions", d, WAIT_NAME), waiting_render(item, t, len(tasks))) == "written":
            made.append(d)
    return made


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


# журнал отказов ролей (metis-0832, lib/handoff.py): только перечислимые значения — вид, кому, итог, источник.
# Словари = handoff.ROUTE_KEYS, OUTCOME_RU и SOURCE_RU (boardtext грузится без handoff; равенство держит test_handoff)
HANDOFF_TO = {"payment": "оплата → владелец руками", "important-form": "важная форма → владелец руками",
              "guard": "защиты → шлюз слияния", "batch-delete": "удаление пачки → «да» словами",
              "touch": "белый список → Touch ID", "browser": "браузер → Харон", "telegram": "Telegram → read",
              "outside": "тесты и серверы → outside", "hestia": "окна и процессы → Гестия", "ask": "прочее → «да» через Зевса"}
HANDOFF_OUT = {"handed": "передано", "waiting": "ждёт Touch ID", "done": "сделано", "failed": "не вышло",
               "declined": "отклонено", "owner": "только владелец", "yes": "только «да»", "merge": "только шлюз",
               "refused": "отказ", "dropped": "снято"}
HANDOFF_SRC = {"sandbox": "песочница", "classifier": "классификатор", "nocmd": "нет команды", "guard": "guard",
               "role": "роль"}
HANDOFF_TAIL = 256 * 1024
MAX_HANDOFF = 4


def handoff_log(state):
    return os.path.join(state, "logs", "handoff.jsonl")


def handoffs(state, t):
    """Отказы за сутки: [(вид, всего, {итог: n})] по убыванию числа и {источник: n}. Строки заявок Touch ID (у них
    id) складываются в одну по последнему итогу заявки: «ждёт» и «сделано» одной заявки — одно действие."""
    raw = _read(handoff_log(state))
    if not raw:
        return [], {}
    raw = raw[-HANDOFF_TAIL:]
    last, plain, src = {}, [], {}
    for ln in raw.splitlines():
        try:
            e = json.loads(ln)
            ts = float(e.get("t"))
        except (ValueError, TypeError, AttributeError):
            continue
        if not isinstance(e, dict) or not -60 <= t - ts <= DAY or e.get("kind") not in HANDOFF_TO \
                or e.get("outcome") not in HANDOFF_OUT:
            continue
        rid = e.get("id")
        one = isinstance(rid, str) and re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", rid)
        if (not one or rid not in last) and e.get("source") in HANDOFF_SRC:
            src[e["source"]] = src.get(e["source"], 0) + 1     # заявка — один отказ, сколько бы строк ни дала
        if one:
            last[rid] = e
        else:
            plain.append(e)
    groups = {}
    for e in plain + list(last.values()):
        g = groups.setdefault(e["kind"], {})
        g[e["outcome"]] = g.get(e["outcome"], 0) + 1
    rows = sorted(((k, sum(v.values()), v) for k, v in groups.items()), key=lambda r: (-r[1], r[0]))
    return rows, src


def handoff_line(rows, src):
    """«- Отказы за сутки (песочница 2, классификатор 1): браузер → Харон ×2 — передано 2; …»."""
    rows = [r for r in rows or [] if r[0] in HANDOFF_TO]
    if not rows:
        return None
    s_ = ", ".join(f"{HANDOFF_SRC[k]} {n}" for k, n in sorted((src or {}).items()) if k in HANDOFF_SRC)
    parts = [f"{HANDOFF_TO[k]} ×{n} — " + ", ".join(f"{HANDOFF_OUT[o]} {c}" for o, c in sorted(v.items())
                                                 if o in HANDOFF_OUT) for k, n, v in rows[:MAX_HANDOFF]]
    more = f"; и ещё видов: {len(rows) - MAX_HANDOFF}" if len(rows) > MAX_HANDOFF else ""
    return f"- Отказы за сутки ({s_}): " + "; ".join(parts) + more + "." if s_ else \
        "- Отказы за сутки: " + "; ".join(parts) + more + "."


def owner_log(state):
    return [os.path.join(state, "owner-log", "zeus.md"), os.path.join(state, "owner-log", "board.jsonl")]


def watch_files(pantheon, state):
    """Файлы входов для отпечатка свежести (без задач и кэша PR — их отпечаток по содержимому даёт вызывающий):
    ревью, STATUS.md, decisions.md, журнал владельца (у него — только размер и время правки)."""
    return review_files(pantheon) + status_files(pantheon) + [os.path.join(pantheon, "decisions.md")] + owner_log(state) \
        + [handoff_log(state)]


def collect(pantheon, state, tasks, t, week=None, owner=None, own_of=None):
    """Все входы блока одним словарём; files — сколько файлов прочитано (для штампа). owner — шапка → на владельце
    ли карточка (tasks.Roles и assignee у вызывающего); без него разделов «Ждёт вас» и «Руками» нет. own_of — id пачки →
    репозитории её направления (batch_branch_prs; None — любые)."""
    cache = os.path.join(state, "autoclose-prs.json")
    zeus_md, board_jsonl = owner_log(state)
    files = len(review_files(pantheon)) + len(status_files(pantheon)) + len(tasks) \
        + sum(1 for p in (cache, zeus_md, board_jsonl) if os.path.isfile(p))
    return {"prs": open_prs(cache), "pr_stale": pr_stale(cache), "reviews": reviews(pantheon), "batches": batches(tasks, batch_branch_prs(cache, own_of)), "week": week,
            "statuses": statuses(pantheon, t), "decisions": decisions(zeus_md, board_jsonl, t), "files": files,
            "broken": ["autoclose-prs.json"] if cache_broken(cache) else [],
            "owner": owner_cards(tasks, owner) if owner else None, "handoffs": handoffs(state, t)}


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


def _merged_ok(r):
    """Строка merged_open (lib/boardmerged.py): id, номер PR, дни, статус, неотмечено — каждое по своему шаблону."""
    ints = lambda *v: all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in v)
    return isinstance(r, (tuple, list)) and len(r) == 5 and _ok(ID_RE, r[0]) and ints(r[1], r[2], r[4]) \
        and r[3] in ("doing", "review")


def pr_stale_line(stale):
    """Строка «PR: данные от HH:MM, gh недоступен (репозитории)» (metis-0808); сбоя нет — пустая. Время — самого давнего
    успеха среди сбойных; ни у одного прежних данных нет — «данных нет»."""
    items = [(r, ts) for r, ts in stale or [] if _ok(NAME_RE, str(r).rsplit("/", 1)[-1])] if isinstance(stale, (list, tuple)) else []
    if not items:
        return ""
    names = ", ".join(r.rsplit("/", 1)[-1] for r, _ in items[:MAX_IDS]) + (f" и ещё {len(items) - MAX_IDS}" if len(items) > MAX_IDS else "")
    seen = [ts for _, ts in items if isinstance(ts, (int, float)) and not isinstance(ts, bool)]
    return f"- PR: данные от {hm(min(seen))}, gh недоступен ({names})." if seen \
        else f"- PR: gh недоступен ({names}), данных нет."


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
    stale = pr_stale_line(data.get("pr_stale"))
    if prs is None:
        pass
    elif not prs:
        out.append(stale or "- Открытых PR нет.")
        stale = ""
    else:
        out += [pr_line(p, data.get("reviews") or {}) for p in prs[:MAX_PR]]
        if len(prs) > MAX_PR:
            out.append(f"- …и ещё PR: {len(prs) - MAX_PR}.")
    if stale and prs is not None:
        out.append(stale)
    merged = [r for r in data.get("merged_open") or [] if _merged_ok(r)]
    for tid, num, days, st, left in merged[:MAX_MERGED]:
        out.append(f"- {tid}: PR #{num} слит {days} дн. назад, задача {st}, неотмечено {left}")
    if len(merged) > MAX_MERGED:
        out.append(f"- …и ещё слитых PR с открытой задачей: {len(merged) - MAX_MERGED}.")
    for sid, work, closed, total, *pr in data.get("batches") or []:
        num = pr[0] if pr and isinstance(pr[0], int) and not isinstance(pr[0], bool) else None
        out.append(f"- Пачка {sid}" + (f" (PR #{num})" if num else "") + ": "
                   + ", ".join(f"{i} ({STATUS_RU.get(s, s)})" for i, s in work) + f"; закрыто {closed} из {total}.")
    st = data.get("statuses") or []
    if st:
        out.append("- STATUS правлены: " + ", ".join(f"{n} {hm(mt)}" for n, mt in st) + ".")
    for ts, qid, var, src in data.get("decisions") or []:
        out.append(f"- Ответ владельца [{qid}] {hm(ts)} ({src}): " + (var or "ответ дан") + ".")
    ho = data.get("handoffs")
    line = handoff_line(*ho) if isinstance(ho, (tuple, list)) and len(ho) == 2 else None
    if line:
        out.append(line)
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
