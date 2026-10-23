"""Автоблок текстовой доски board.md (metis-0397): PR, пачки, свежие STATUS.md и решения владельца — без ручной
правки Зевса. Собирает плановый проход доски (`pantheon board`, задача тика) тем же путём, что виды доски
(metis-0234, 0069, 0248); модель не зовёт, в сеть не ходит. Входы не менялись — тик пропускает проход (metis-0149),
блок не изменился — файл не пишется.

Блок стоит между строками-маркерами BEGIN и END в разделе «## Сейчас». Всё вне маркеров — строки Зевса: код их не
меняет ни при каком входе. Маркеров нет — блок вставляется под заголовок «## Сейчас» (строки Зевса остаются как были,
ниже блока). Маркеры сломаны (один без пары, повтор, конец раньше начала), раздела нет или файла нет — файл не
пишется, причина в ответе (тревога у тика).

Входы — только файлы:
- открытые PR — кэш `pantheon autoclose fetch` (STATE/autoclose-prs.json, ключ open_prs: номер, head, задачи, ядро);
  ядро — сливает владелец, не ядро — «принять» Зевса;
- вердикты argus — directions/*/review-<N>-argus*.md: строка «Вердикт: …» и head из первых строк; у каждой дорожки
  (a, b, без буквы) — самый свежий файл; вердикт на другом head помечен «старый head»;
- пачки — карточки type story не done/dropped, у которых есть задачи в doing, review или waiting;
- неделя — целые проценты снимка лимита (их даёт вызывающий);
- STATUS.md направлений, правленные за сутки, — время правки и последняя строка;
- решения владельца — журнал owner-log: выбор в окне вопросов на вопрос «[id] …» (zeus.md, пометку ставит хук) и
  ответ галочкой на карточке (board.jsonl), за сутки. Текст файлов и задач решением не считается. Блок — сводка для
  глаз, а не согласие: согласие проверяет только `pantheon consent <id>`.

Размер блока ограничен (строк каждого вида и знаков в строке), поэтому он не раздувает файл. Подрезку ручных строк
сверх 9 000 знаков код не делает: строки Зевса вне маркеров не трогаются (решение по metis-0397).

stale_reminder — проверка для хука Stop у Зевса: ручные строки «Сейчас» (вне блока) старше правки STATUS.md Метиды на
STALE_GAP и больше → текст напоминания; это не отказ.

Только стандартная библиотека и Python 3.9: модуль грузит и хук (hooks/ctx.py).
"""
import glob
import json
import os
import re
import time
from datetime import datetime

BEGIN = "<!-- pantheon:auto — блок собирает плановый проход (pantheon board); правки внутри затрутся -->"
END = "<!-- /pantheon:auto -->"
BEGIN_MARK, END_MARK = "<!-- pantheon:auto", "<!-- /pantheon:auto"
NOW_HEAD = re.compile(r"## Сейчас[ \t]*\r?\n?")
DAY = 86400
STALE_GAP = 30 * 60          # «Сейчас» старше правки STATUS.md Метиды на столько — напоминание на Stop
STALE_SOURCE = "metis-pantheon"  # направление, чей STATUS.md сверяется на Stop (там PR и пачки)
MAX_PR, MAX_BATCH, MAX_STATUS, MAX_DECISION, LINE_MAX = 8, 3, 4, 5, 220
REVIEW_RE = re.compile(r"review-([1-9]\d{0,5})-argus(?:-?([a-z]?)(\d*))?\.md")
VERDICT_RE = re.compile(r"Вердикт\**\s*:\s*\**\s*([А-Яа-яЁё]+)")
HEAD_RE = re.compile(r"\bHead\b\**:?\**\s*`?([0-9a-f]{7,40})\b")
REPO_RE = re.compile(r"([\w.-]+/[\w.-]+)#(\d+)")
WORK = ("doing", "review", "waiting")
STATUS_RU = {"doing": "в работе", "review": "на проверке", "waiting": "ждёт"}
OWN_Q = re.compile(r"вопрос: \[([a-z0-9][a-z0-9-]{0,40})\]", re.I)
STAMP_RE = re.compile(r"(?<!\d)(\d{2})\.(\d{2})(?:\.\d{2,4})?,?\s+(\d{1,2}):(\d{2})(?!\d)")


def one_line(s, n=LINE_MAX):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def hm(t):
    return datetime.fromtimestamp(t).strftime("%d.%m %H:%M")


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
    """Открытые PR из кэша autoclose fetch: [{repo, number, head, ids, core}] по репозиторию и номеру; нет данных — None."""
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
            if isinstance(p, dict) and isinstance(p.get("number"), int):
                out.append({"repo": str(repo), "number": p["number"], "head": str(p.get("head") or ""),
                            "ids": [str(i) for i in p.get("ids") or [] if isinstance(i, str)], "core": bool(p.get("core"))})
    return sorted(out, key=lambda p: (p["repo"], p["number"]))


def review_files(pantheon):
    return sorted(glob.glob(os.path.join(pantheon, "directions", "*", "review-*-argus*.md")))


def reviews(pantheon):
    """{номер PR: {дорожка: {verdict, head, repo, mtime}}} — у дорожки самый свежий файл ревью."""
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
        rec = {"verdict": v.group(1).lower() if v else "", "head": h.group(1) if h else "",
               "repo": r.group(1) if r and r.group(2) == m.group(1) else "", "mtime": mt}
        cur = out.setdefault(int(m.group(1)), {}).get(lane)
        if cur is None or mt > cur["mtime"]:
            out[int(m.group(1))][lane] = rec
    return out


def batches(tasks):
    """Пачки в работе: [(id, заголовок, [(id задачи, статус)], закрыто, всего)]. tasks — load_tasks: id → (путь, шапка, …)."""
    kids = {}
    for tid, rec in tasks.items():
        h = rec[1]
        if h.get("type") == "task" and h.get("parent"):
            kids.setdefault(h["parent"], []).append((tid, h.get("status")))
    out = []
    for sid, rec in tasks.items():
        h = rec[1]
        if h.get("type") != "story" or h.get("status") in ("done", "dropped"):
            continue
        ks = sorted(kids.get(sid) or [])
        work = [(i, s) for i, s in ks if s in WORK]
        if work:
            out.append((h.get("priority", 2) if isinstance(h.get("priority"), int) else 2, sid, h.get("title") or "",
                        work, sum(1 for _, s in ks if s in ("done", "dropped")), len(ks)))
    out.sort()
    return [x[1:] for x in out[:MAX_BATCH]]


def status_files(pantheon):
    return sorted(glob.glob(os.path.join(pantheon, "directions", "*", "STATUS.md")))


def statuses(pantheon, t):
    """STATUS.md, правленные за сутки: [(направление, время правки, последняя строка)] — свежие первыми."""
    out = []
    for p in status_files(pantheon):
        mt = _mtime(p)
        if mt is None or t - mt > DAY:
            continue
        lines = [ln for ln in (_read(p) or "").splitlines() if ln.strip()]
        out.append((os.path.basename(os.path.dirname(p)), mt, lines[-1] if lines else ""))
    out.sort(key=lambda x: -x[1])
    return out[:MAX_STATUS]


def decisions(zeus_md, board_jsonl, t):
    """Решения владельца за сутки: [(время, id, ответ, откуда)] — свежие первыми. Только журнал owner-log: выбор в
    окне вопросов на вопрос «[id] …» и ответ галочкой на карточке (как у `pantheon consent`)."""
    out = []
    text = _read(zeus_md) or ""
    heads = list(re.finditer(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(.*)$", text, re.M))
    for i, m in enumerate(heads):
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        q = OWN_Q.match(body)
        if m.group(2).strip() != "· окно вопросов" or not q:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue
        a = re.search(r"^ответ: (.*)$", body, re.M)
        if a and 0 <= t - ts <= DAY:
            out.append((ts, q.group(1).lower(), a.group(1), "окно вопросов"))
    for line in (_read(board_jsonl) or "").splitlines():
        try:
            rec = json.loads(line)
            ts = time.mktime(time.strptime(rec.get("time", "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, TypeError, AttributeError):
            continue
        q, a = rec.get("question"), rec.get("answer")
        if rec.get("kind") != "answer" or not isinstance(rec.get("id"), str) or not isinstance(q, str) \
                or not isinstance(a, str) or re.search(r"%%|<", q) or not 0 <= t - ts <= DAY:
            continue
        out.append((ts, rec["id"], a, "доска"))
    out.sort(key=lambda x: -x[0])
    return out[:MAX_DECISION]


def collect(pantheon, state, tasks, t, week=None):
    """Все входы блока одним словарём (его же пишет отпечаток тика)."""
    return {"prs": open_prs(os.path.join(state, "autoclose-prs.json")), "reviews": reviews(pantheon),
            "batches": batches(tasks), "week": week, "statuses": statuses(pantheon, t),
            "decisions": decisions(os.path.join(state, "owner-log", "zeus.md"),
                                   os.path.join(state, "owner-log", "board.jsonl"), t)}


# --- блок -------------------------------------------------------------------------------------------------------

def _q(s, n=120):
    return "«" + one_line(re.sub(r"[«»]", '"', str(s)), n) + "»"


def pr_line(p, revs):
    lanes = revs.get(p["number"]) or {}
    lanes = {k: v for k, v in lanes.items() if not v["repo"] or v["repo"] == p["repo"]}
    parts = []
    for lane in sorted(lanes):
        r = lanes[lane]
        old = p["head"] and r["head"] and not p["head"].startswith(r["head"]) and not r["head"].startswith(p["head"])
        parts.append((lane + " " if lane else "") + (_q(r["verdict"]) if r["verdict"] else "без вердикта")
                     + (f" на старом head {r['head'][:7]}" if old else ""))
    who = "ядро → сливает владелец" if p["core"] else "не ядро → «принять» Зевса"
    ids = f" ({', '.join(p['ids'][:3])})" if p["ids"] else ""
    return one_line(f"- PR #{p['number']} {p['repo'].rsplit('/', 1)[-1]}{ids} · head {p['head'][:7] or '?'} · argus: "
                    + (", ".join(parts) if parts else "ревью нет") + f" · {who}")


def build(data):
    """Текст блока с маркерами. Каждая строка внутри начинается с «- » или «**»: вход не может подделать маркер."""
    out = [BEGIN, "**Сводка прохода** — собирает код из кэша PR, ревью, задач и журнала владельца. Согласие владельца "
           "проверяет только `pantheon consent <id>`.", ""]
    w = data.get("week")
    out.append(f"- Неделя: {w} %." if isinstance(w, int) else "- Неделя: расход неизвестен.")
    prs = data.get("prs")
    if prs is None:
        out.append("- PR: кэша открытых PR нет — задача autoclose-fetch ещё не прошла.")
    elif not prs:
        out.append("- Открытых PR нет.")
    else:
        out += [pr_line(p, data.get("reviews") or {}) for p in prs[:MAX_PR]]
        if len(prs) > MAX_PR:
            out.append(f"- …и ещё PR: {len(prs) - MAX_PR}.")
    for sid, title, work, closed, total in data.get("batches") or []:
        out.append(one_line(f"- Пачка {sid} {_q(title, 60)}: "
                            + ", ".join(f"{i} ({STATUS_RU.get(s, s)})" for i, s in work) + f"; закрыто {closed} из {total}."))
    for name, mt, last in data.get("statuses") or []:
        out.append(one_line(f"- STATUS {name}, правка {hm(mt)}: {_q(last, 160)}"))
    for ts, qid, ans, src in data.get("decisions") or []:
        out.append(one_line(f"- Решение владельца {hm(ts)} [{qid}] ({src}): {_q(ans)}"))
    out.append(END)
    return "\n".join(out) + "\n"


# --- запись -----------------------------------------------------------------------------------------------------

def markers(lines):
    b = [i for i, ln in enumerate(lines) if ln.startswith(BEGIN_MARK)]
    e = [i for i, ln in enumerate(lines) if ln.startswith(END_MARK)]
    return b, e


def splice(text, block):
    """Новый текст файла: блок между маркерами (или под «## Сейчас»), остальное — байт в байт как было.
    → (текст, "") или (None, причина)."""
    lines = text.splitlines(True)
    b, e = markers(lines)
    if len(b) == 1 and len(e) == 1 and b[0] < e[0]:
        tail = lines[e[0]][len(lines[e[0]].rstrip("\r\n")):] or ("\n" if e[0] + 1 < len(lines) else "")
        return "".join(lines[:b[0]]) + block.rstrip("\n") + tail + "".join(lines[e[0] + 1:]), ""
    if b or e:
        return None, (f"маркеры автоблока сломаны (начало: {len(b)}, конец: {len(e)}) — блок не записан; поправить "
                      f"руками: одна строка «{BEGIN_MARK} …» и после неё одна «{END}»")
    h = [i for i, ln in enumerate(lines) if NOW_HEAD.fullmatch(ln)]
    if len(h) != 1:
        return None, "в board.md нет одного раздела «## Сейчас» — блок не записан"
    i = h[0]
    head = lines[i] if lines[i].endswith("\n") else lines[i] + "\n"
    return "".join(lines[:i]) + head + "\n" + block + ("\n" if i + 1 < len(lines) else "") + "".join(lines[i + 1:]), ""


def sync(board_md, block):
    """Записать блок в board.md, если он изменился. → ("written"|"same", "") или ("skip", причина).
    Перед заменой файл перечитывается: Зевс правил его во время прохода — пропуск, следующий проход допишет."""
    old = _read(board_md)
    if old is None:
        return "skip", "board.md не прочитать — блок не записан"
    new, why = splice(old, block)
    if new is None:
        return "skip", why
    if new == old:
        return "same", ""
    tmp = f"{board_md}.auto.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(new)
        try:
            os.chmod(tmp, os.stat(board_md).st_mode & 0o7777)
        except OSError:
            pass
        if _read(board_md) != old:
            return "skip", "board.md правили во время прохода — блок запишет следующий проход"
        os.replace(tmp, board_md)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return "written", ""


# --- напоминание на Stop ----------------------------------------------------------------------------------------

def manual_now(text):
    """Раздел «## Сейчас» без автоблока — только строки Зевса."""
    lines = text.splitlines(True)
    b, e = markers(lines)
    if len(b) == 1 and len(e) == 1 and b[0] < e[0]:
        lines = lines[:b[0]] + lines[e[0] + 1:]
    out, inside = [], False
    for ln in lines:
        if ln.startswith("## "):
            inside = bool(NOW_HEAD.fullmatch(ln))
            continue
        if inside:
            out.append(ln)
    return "".join(out)


def newest_stamp(text, ref):
    """Самое позднее «ДД.ММ ЧЧ:ММ» в тексте; год — от ref (дата позже ref больше чем на 2 дня — прошлый год)."""
    best = None
    year = datetime.fromtimestamp(ref).year
    for m in STAMP_RE.finditer(text):
        d, mo, h, mi = (int(x) for x in m.groups())
        for y in (year, year - 1):
            try:
                ts = datetime(y, mo, d, h, mi).timestamp()
            except ValueError:
                break
            if ts <= ref + 2 * DAY:
                best = ts if best is None or ts > best else best
                break
    return best


def stale_reminder(board_md, status_md, gap=STALE_GAP):
    """«Сейчас» (строки Зевса) старше правки STATUS.md на gap и больше → (текст, время правки STATUS), иначе None.
    Нет файла или в «Сейчас» нет ни одного «ДД.ММ ЧЧ:ММ» — None: сравнивать не с чем."""
    st = _mtime(status_md)
    text = _read(board_md)
    if st is None or text is None:
        return None
    last = newest_stamp(manual_now(text), st)
    if last is None or st - last < gap:
        return None
    return (f"board.md: раздел «Сейчас» отстал — последняя ваша строка там за {hm(last)}, а STATUS.md "
            f"{os.path.basename(os.path.dirname(status_md))} правлен в {hm(st)} (на {int((st - last) // 60)} мин позже). "
            "Перенеси в «Сейчас» строки после этого времени; PR, пачки и решения владельца блок между маркерами "
            "пишет сам. Это напоминание хука, а не владельца.", st)
