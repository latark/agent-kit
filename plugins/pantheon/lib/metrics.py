"""Учёт по задаче (metis-0294): во что обошлась задача и какой исполнитель×модель работает лучше.

При закрытии задачи (done или dropped) — одна строка в ~/ai/pantheon/metrics/tasks.jsonl: исполнитель, модель, effort,
токены и $ (цены и разбор usage — scripts/usage.py), круги argus, возвраты, правки владельца, возврат после слияния,
часы от взятия до закрытия. Пишет её `pantheon task set … status=done|dropped`; роль в песочнице в metrics/ писать не
может — тогда строку дописывает плановый проход доски (sync: закрытые за последние дни без строки). Задним числом —
`pantheon metrics backfill --from ДАТА`: те же строки с пометкой estimate (на Пульте — «оценка»).

Связка задача → расход:
- субагент, в первом сообщении которого (поручение) назван id задачи, — весь его транскрипт; названо несколько
  известных id — расход делится поровну (shared = их число);
- записи любой сессии, у которых ветка (gitBranch) или папка (cwd) содержит id: worktree и ветка metis-0294-…;
- claimed_by — исполнитель, если транскриптов не нашлось.
Из транскриптов берутся только поля usage, модель, effort, ветка, папка и id задач из поручения — текст переписки
не сохраняется и не выводится.

Круги argus — вердикты шлюза слияния (STATE/merge-gate/records.jsonl) по PR, названным в журнале задачи, и файлы
review-*.md направления с id в заголовке (строка «модель: …» перед заголовком пропускается). Круг — один head (SHA):
два argus и повторные вердикты на тот же SHA — один круг; «с первого круга» — итог первого SHA (metis-0393). SHA файла —
из «Head: <sha>» шапки; «прошлый head <sha>» из поручения узкого повтора за него не считается.
Возвраты — круги с итогом «вернуть» и переносы карточки владельцем назад (owner-log/board.jsonl); правки владельца —
его заметки, ответы и переносы; возврат после слияния — другие задачи со словами revert, hotfix, «откатили» в одной
строке с id.

Замер «Лимит» (metis-0390): в своде недели — цена принятой задачи (токены и $ всех кругов, разработчик + argus, на
принятую: последний круг argus «принять» или PR слит) и вмешательства владельца на принятую (заметки, ответы, переносы,
возвраты, доля без вмешательства) по неделям; меньше 20 принятых — «мало данных».

Свод — по исполнителю×модели×effort и по направлениям, за неделю и с начала: metrics/week-<ГГГГ-Wнн>.md и заметки
Доска/Учёт/*.md для видов «Учёт недели» и «Учёт с начала» на Пульте. Модуль без tomllib: идёт и на системном 3.9.
"""
import fcntl
import glob
import importlib.util
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

PLUGIN = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
REVIEWERS = ("argus", "talos", "momus")
CLOSED = ("done", "dropped")
ID_RE = re.compile(r"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")
ID_BRE = re.compile(rb"(?<![\w-])[a-z][a-z0-9]{1,11}-\d{3,}(?![\w])")
JOURNAL_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) — ")
# ссылка на PR: owner/repo#N, github.com/owner/repo/pull/N (repo известен) или «PR #N», /pull/N (repo — направления)
PR_RE = re.compile(r"(?<![\w./-])([\w.-]+/[\w.-]+)#(\d{1,6})\b|github\.com/([\w.-]+/[\w.-]+)/pull/(\d{1,6})\b"
                   r"|(?:\bPR\s*#?|/pull/)(\d{1,6})\b")
VERDICT_RE = re.compile(r"Вердикт:?\**:?\s*\**\s*(принять|вернуть)", re.I)
# head ревью в файле: «Head: <sha>» или «Head <sha>»; нет — конец дельты «A..<sha>», затем SHA в заголовке
# («… на 3eb43c1»). SHA — 7–40 hex с цифрой: слова из букв a–f за него не сойдут
SHA_TOKEN = r"(?=[0-9a-f]*\d)([0-9a-f]{7,40})(?![0-9a-z])"
HEAD_RES = (re.compile(r"\bhead\b[^\n0-9a-f]{0,30}?" + SHA_TOKEN, re.I), re.compile(r"\.\." + SHA_TOKEN, re.I))
TITLE_SHA_RE = re.compile(r"(?<![0-9a-z])" + SHA_TOKEN, re.I)
MODEL_LINE_RE = re.compile(r"^\W*модель\s*:", re.I)
PREV_HEAD_RE = re.compile(r"\b(?:прошл|предыдущ|previous|prev|old)\w*\W{0,3}$", re.I)
REVERT_RE = re.compile(r"\brevert(?:ed)?\b|hotfix|хотфикс|откатил|откатили|возврат после слияния|сломал[аио]? после слияния",
                       re.I)
BACK_SRC = ("На проверке", "Готово")
BACK_DST = ("В работе", "Очередь", "Входящие")
SYNC_DAYS = 3  # плановый проход дописывает строки задачам, закрытым за столько последних дней
DIR_NAME = "Учёт"  # папка заметок свода на доске (Доска/Учёт/)
NOTE_TYPE = "учёт"


class Ctx:
    """Где что лежит: pantheon — ~/ai/pantheon, state — ~/.local/state/pantheon, home — HOME (транскрипты
    home/.claude/projects), board — ~/ai/pantheon-view/Доска (None — без заметок), t — «сейчас» (epoch),
    repos — {направление: [owner/repo]} из [merge_repos] policy.toml: чей PR назван в журнале просто номером."""

    def __init__(self, pantheon, state, home, t, board=None, repos=None):
        self.pantheon, self.state, self.home, self.t, self.board = pantheon, state, home, t, board
        self.repos = {k: [str(r).lower() for r in v] for k, v in (repos or {}).items() if isinstance(v, list)}

    @property
    def rows_path(self):
        return os.path.join(self.pantheon, "metrics", "tasks.jsonl")

    @property
    def projects(self):
        return os.path.join(self.home, ".claude", "projects")


_USAGE = None


def usage_mod():
    """scripts/usage.py — цены и разбор поля usage (тот же расчёт, что в pantheon usage)."""
    global _USAGE
    if _USAGE is None:
        spec = importlib.util.spec_from_file_location("pantheon_usage", os.path.join(PLUGIN, "scripts", "usage.py"))
        _USAGE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_USAGE)
    return _USAGE


# --- время ------------------------------------------------------------------------------------------------------

def epoch(s):
    """ISO-строка (с поясом или местная, «Z» тоже) или дата → epoch; не разобрать — None."""
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def week_of(t):
    y, w, _ = datetime.fromtimestamp(t).isocalendar()
    return f"{y}-W{w:02d}"


def week_start(t):
    d = datetime.fromtimestamp(t)
    return (datetime(d.year, d.month, d.day) - timedelta(days=d.weekday())).timestamp()


def journal(body):
    """Строки журнала задачи → [(epoch, текст)] по порядку."""
    out = []
    for line in (body or "").split("\n"):
        m = JOURNAL_RE.match(line)
        if m:
            t = epoch(f"{m.group(1)}T{m.group(2)}")
            if t is not None:
                out.append((t, line[m.end():]))
    return out


def task_times(head, body):
    """→ (начало, источник начала, закрытие). Начало — первая аренда («взял … до»), иначе создание."""
    jr = journal(body)
    start, src = None, "created"
    for t, text in jr:
        if "взял " in text:
            start, src = t, "claim"
            break
    if start is None:
        start = jr[0][0] if jr else epoch(str(head.get("created") or ""))
    closed = str(head.get("closed") or "")
    upd = str(head.get("updated") or "")
    if closed and upd[:10] == closed:
        end = epoch(upd)
    else:  # шапку правили после закрытия: последняя строка журнала в день закрытия, иначе конец того дня
        same = [t for t, _ in jr if closed and iso(t)[:10] == closed]
        end = same[-1] if same else epoch(closed + "T23:59:00") if closed else epoch(upd)
    return start, src, end


# --- расход по транскриптам ------------------------------------------------------------------------------------

def _prompt_ids(f, known):
    """id известных задач из первого сообщения user субагента (его поручение); сам текст не сохраняется."""
    try:
        fh = open(f, errors="replace")
    except OSError:
        return []
    with fh:
        for n, line in enumerate(fh):
            if n > 400:
                break
            if '"user"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "user":
                continue
            c = (d.get("message") or {}).get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text") for x in c if isinstance(x, dict) and isinstance(x.get("text"), str))
            if not isinstance(c, str):
                return []
            return [i for i in dict.fromkeys(ID_RE.findall(c)) if i in known]
    return []


def _new_agg():
    return {"usd": 0.0, "requests": 0, "tokens": Counter(), "roles": defaultdict(
        lambda: {"usd": 0.0, "requests": 0, "tokens": 0, "models": Counter(), "efforts": Counter()}),
        "sessions": set(), "links": set(), "shared": 1, "unknown_models": 0}


def usage_for(projects, tids, since, known):
    """Один проход по транскриптам, изменённым не раньше since: {tid: расход}. tids — для каких задач считать,
    known — все id задач (делёж поручения на несколько задач)."""
    U = usage_mod()
    tids = set(tids)
    out = {tid: _new_agg() for tid in tids}
    seen = {tid: set() for tid in tids}
    for f in glob.glob(os.path.join(projects, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(f) < since:
                continue
            with open(f, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        sub = "/subagents/" in f
        whole, share, role = [], 1.0, None
        if sub:
            ids = _prompt_ids(f, known)
            whole = [i for i in ids if i in tids]
            share = 1.0 / len(ids) if ids else 1.0
            role = U.sub_role(f) or "субагент без типа"
        # один проход регулярки по файлу, а не поиск каждого id: при задним числом их сотни, транскриптов — гигабайты
        if len(tids) <= 20:  # при закрытии одной задачи поиск подстроки быстрее регулярки
            hit = sorted(t for t in tids - set(whole) if t.encode() in data)
        else:
            hit = sorted({x.decode() for x in ID_BRE.findall(data)} & tids - set(whole))
        hitb = [h.encode() for h in hit]
        if not whole and not hit:
            continue
        if role is None:
            try:
                role = U.main_role(f) or "без роли"
            except OSError:
                role = "без роли"
        sid = U.session_of(f)
        for raw in data.split(b"\n"):
            # ветка и папка — поля той же записи assistant: без id в её байтах разбирать незачем
            if b'"assistant"' not in raw or not (whole or any(b in raw for b in hitb)):
                continue
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if d.get("type") != "assistant":
                continue
            m = d.get("message") or {}
            u = m.get("usage")
            if not isinstance(u, dict):
                continue
            where = f"{d.get('gitBranch') or ''} {d.get('cwd') or ''}"
            targets = [(tid, share, "поручение") for tid in whole]
            targets += [(tid, 1.0, "ветка/папка") for tid in hit if tid in where]
            if not targets:
                continue
            fam = U.family(m.get("model"))
            key = d.get("requestId") or m.get("id")
            for tid, w, link in targets:
                if key in seen[tid]:
                    continue
                seen[tid].add(key)
                a = out[tid]
                if not fam:
                    a["unknown_models"] += 1
                    continue
                c, tk = U.cost(fam, u)
                usd = sum(c.values()) * w
                a["usd"] += usd
                a["requests"] += 1
                for k in ("input", "write", "read", "output"):
                    a["tokens"][k] += tk[k] * w
                r = a["roles"][role]
                r["usd"] += usd
                r["requests"] += 1
                r["tokens"] += sum(tk[k] for k in ("input", "write", "read", "output")) * w
                r["models"][fam] += usd or 1e-9
                r["efforts"][d.get("effort") or "-"] += usd or 1e-9
                a["sessions"].add(sid)
                a["links"].add(link)
                if w < 1:
                    a["shared"] = max(a["shared"], round(1 / w))
    return out


# --- круги argus, владелец, возврат после слияния ------------------------------------------------------------------

def _jsonl(path):
    out = []
    try:
        with open(path, "rb") as fh:
            for raw in fh:
                try:
                    d = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except OSError:
        pass
    return out


def review_title(text):
    """Заголовок файла ревью — первая непустая строка, кроме строки «модель: …»: argus пишет её и до заголовка."""
    for line in text.split("\n")[:10]:
        if line.strip() and not MODEL_LINE_RE.match(line):
            return line
    return ""


def review_sha(text, title):
    """SHA проверенного head из шапки файла ревью (первые 7 знаков, нижний регистр) или None."""
    top = text[:2000]
    for rx in HEAD_RES:
        for m in rx.finditer(top):
            # «прошлый head <sha>» из поручения узкого повтора — не проверенный head: берём следующее совпадение
            if not PREV_HEAD_RE.search(top[max(0, m.start() - 16):m.start()]):
                return m.group(1)[:7].lower()
    m = TITLE_SHA_RE.search(title)
    return m.group(1)[:7].lower() if m else None


def review_files(pantheon):
    """review-*.md направлений → [(mtime, заголовок, вердикт «принять»/«вернуть» или None, SHA head или None)]."""
    out = []
    for f in glob.glob(os.path.join(pantheon, "directions", "*", "review-*.md")):
        try:
            text = open(f, encoding="utf-8", errors="replace").read(20000)
            mt = os.path.getmtime(f)
        except OSError:
            continue
        m = VERDICT_RE.search(text)
        title = review_title(text)
        out.append((mt, title, m.group(1).lower() if m else None, review_sha(text, title)))
    return sorted(out, key=lambda x: (x[0], x[1]))


def pr_refs(body):
    """PR из журнала задачи → ({(owner/repo, N)} с названным repo, {N} без repo). owner/repo#N и ссылка github.com —
    свой repo; «PR #N» и /pull/N без repo — голый номер: чей он, решает argus_info по вердикты шлюза."""
    named, bare = set(), set()
    for full, n1, url, n2, n3 in PR_RE.findall(body or ""):
        if full or url:
            named.add(((full or url).lower(), int(n1 or n2)))
        else:
            bare.add(int(n3))
    return named, bare


def argus_info(tid, body, gate, reviews, repos=None):
    """→ {rounds, first_pass, rejects}: вердикты шлюза по PR из журнала задачи (repo и номер, pr_refs) и review-*.md
    с id в заголовке. Нет ни того ни другого — rounds 0, first_pass None (неизвестно). Голый «PR #N» относим к repo
    направления (repos), только если вердикты на номер N есть ровно у одного из них: номера у разных репозиториев
    совпадают, и при двух кандидатах чужие круги не считаем."""
    named, bare = pr_refs(body)
    verdicts = [r for r in gate if r.get("kind") in ("accept", "reject")]

    def repos_of(r):
        rr = r.get("repo")
        return [str(x).lower() for x in ([rr] if isinstance(rr, str) else rr if isinstance(rr, list) else [])]

    mine = {str(x).lower() for x in repos or []}
    refs = set(named)
    for n in bare:
        with_gate = {x for r in verdicts if r.get("pr") == n for x in repos_of(r) if x in mine}
        if len(with_gate) == 1:
            refs.add((next(iter(with_gate)), n))
    # круг — один проверенный head (metis-0393): все вердикты на тот же SHA — один круг, сколько бы argus его ни
    # смотрели. Итог круга — «вернуть», если последний вердикт хоть одного argus на этом SHA «вернуть» (так считает и
    # шлюз). PR в журнале бывает несколько (упомянуты чужие) — берём тот, где кругов больше всего
    per = defaultdict(dict)
    for r in sorted(verdicts, key=lambda r: epoch(str(r.get("time"))) or 0):
        by = r.get("by") if isinstance(r.get("by"), dict) else {}
        for repo in repos_of(r):
            key = (repo, r.get("pr"))
            if key in refs:
                per[key].setdefault(str(r.get("sha")), {})[str(by.get("agent_id") or "")] = r["kind"]
    kinds = max(([("вернуть" if "reject" in v.values() else "принять") for v in shas.values()]
                 for shas in per.values()), key=len, default=[])
    # файлы ревью: два файла на один head (два argus, повтор с перечнем) — один круг; без SHA — круг на файл
    files = {}
    for i, rec in enumerate(reviews):
        _, title, v, sha = (tuple(rec) + (None,))[:4]
        if v and re.search(rf"(?<![\w-]){re.escape(tid)}(?!\d)", title):
            files.setdefault(sha or ("file", i), []).append(v)
    rv = [("вернуть" if "вернуть" in vs else "принять") for vs in files.values()]
    seq = kinds if len(kinds) >= len(rv) else rv
    return {"rounds": len(seq), "first_pass": (seq[0] == "принять") if seq else None,
            "rejects": seq.count("вернуть")}


def owner_info(tid, owner_log):
    recs = [r for r in owner_log if r.get("id") == tid]
    moves = [r for r in recs if r.get("kind") == "move"]
    return {"notes": sum(1 for r in recs if r.get("kind") == "note"),
            "answers": sum(1 for r in recs if r.get("kind") in ("answer", "request")),
            "moves": len(moves),
            "returns": sum(1 for r in moves if r.get("src") in BACK_SRC and r.get("dst") in BACK_DST)}


def post_merge_index(tasks):
    """{id: [задачи, где в одной строке со словом revert/hotfix/«откатили» назван этот id]}; себя не считаем."""
    out = defaultdict(list)
    for oid, (_, h, body) in tasks.items():
        for line in [str(h.get("title") or "")] + (body or "").split("\n"):
            if not REVERT_RE.search(line):
                continue
            for x in set(ID_RE.findall(line)):
                if x != oid and x in tasks and oid not in out[x]:
                    out[x].append(oid)
    return dict(out)


# --- строка учёта -------------------------------------------------------------------------------------------------

def build_row(ctx, tid, path, head, body, use, gate, reviews, owner_log, post, estimate=False):
    start, start_src, end = task_times(head, body)
    roles = {}
    for r, a in sorted(use["roles"].items(), key=lambda x: -x[1]["usd"]):
        roles[r] = {"usd": round(a["usd"], 4), "requests": a["requests"], "tokens": int(a["tokens"]),
                    "model": a["models"].most_common(1)[0][0] if a["models"] else None,
                    "effort": a["efforts"].most_common(1)[0][0] if a["efforts"] else None}
    work = {r: a for r, a in roles.items() if r not in REVIEWERS}
    if work:
        executor = max(work, key=lambda r: work[r]["usd"])
        model, effort = work[executor]["model"], work[executor]["effort"]
    else:
        executor = "codex" if head.get("executor") == "codex" else (head.get("claimed_by") or head.get("owner")
                                                                       or head.get("direction"))
        model = "codex" if executor == "codex" else None
        effort = None
    ar = argus_info(tid, body, gate, reviews, ctx.repos.get(head.get("direction")))
    ow = owner_info(tid, owner_log)
    tok = {k: int(v) for k, v in use["tokens"].items()}
    return {
        "v": 1, "id": tid, "direction": head.get("direction"), "project": head.get("project"),
        "title": str(head.get("title") or "")[:120], "status": head.get("status"), "closed": head.get("closed"),
        "closed_at": iso(end) if end else None, "start_at": iso(start) if start else None, "start_source": start_src,
        "hours": round((end - start) / 3600, 2) if start and end and end >= start else None,
        "executor": executor, "model": model or "—", "effort": effort or "—", "executor_field": head.get("executor"),
        "claimed_by": head.get("claimed_by"),
        "usd": round(use["usd"], 4), "tokens": tok, "tokens_total": sum(tok.values()), "requests": use["requests"],
        "review_usd": round(sum(a["usd"] for r, a in roles.items() if r in REVIEWERS), 4),
        "roles": roles, "sessions": len(use["sessions"]), "link": sorted(use["links"]) or ["нет"],
        "shared": use["shared"],
        "argus_rounds": ar["rounds"], "argus_first_pass": ar["first_pass"], "argus_rejects": ar["rejects"],
        "owner_notes": ow["notes"], "owner_answers": ow["answers"], "owner_moves": ow["moves"],
        "owner_returns": ow["returns"], "returns": ar["rejects"] + ow["returns"],
        "post_merge": post.get(tid, []), "estimate": bool(estimate), "recorded_at": iso(ctx.t),
        "path": os.path.relpath(path, ctx.pantheon) if path else None,
    }


def read_rows(path):
    return [r for r in _jsonl(path) if isinstance(r.get("id"), str)]


def append_rows(path, rows):
    """Дописать строки под блокировкой файла (несколько проходов разом строк не перемешают). Ключи (id, closed)
    перечитываются под той же блокировкой: закрытие и плановый проход проверяют «строки нет» до долгого чтения
    транскриптов, и строку, которую другой успел записать за это время, второй раз не пишем. → дописанные строки."""
    if not rows:
        return []
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        have = _have(read_rows(path))
        new = []
        for r in rows:
            k = (r.get("id"), r.get("closed"))
            if k not in have:
                have.add(k)
                new.append(r)
        if new:
            data = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in new)
            os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)
    return new


def _closed_tasks(tasks):
    return {tid: v for tid, v in tasks.items() if v[1].get("status") in CLOSED and v[1].get("closed")}


def make_rows(ctx, tasks, tids, estimate=False):
    """Строки для задач tids (все закрыты): один проход по транскриптам с самого раннего начала минус сутки."""
    if not tids:
        return []
    starts = [task_times(tasks[t][1], tasks[t][2])[0] for t in tids]
    since = min([s for s in starts if s] or [ctx.t - 30 * 86400]) - 86400
    use = usage_for(ctx.projects, tids, since, set(tasks))
    gate = _jsonl(os.path.join(ctx.state, "merge-gate", "records.jsonl"))
    owner_log = _jsonl(os.path.join(ctx.state, "owner-log", "board.jsonl"))
    reviews = review_files(ctx.pantheon)
    post = post_merge_index(tasks)
    return [build_row(ctx, t, tasks[t][0], tasks[t][1], tasks[t][2], use[t], gate, reviews, owner_log, post, estimate)
            for t in sorted(tids)]


def _have(rows):
    return {(r.get("id"), r.get("closed")) for r in rows}


def since(ctx):
    """День начала учёта (metrics/since; нет — сегодня, и записать): закрытое раньше — только «оценка»."""
    p = os.path.join(os.path.dirname(ctx.rows_path), "since")
    try:
        with open(p, encoding="utf-8") as fh:
            d = fh.read().strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            return d
    except OSError:
        pass
    d = time.strftime("%Y-%m-%d", time.localtime(ctx.t))
    write_if_changed(p, d + "\n")
    return d


def record(ctx, tasks, tid):
    """Строка закрытой задачи tid (если её ещё нет) → tasks.jsonl. → строка или None (уже есть / не закрыта)."""
    v = tasks.get(tid)
    if not v or v[1].get("status") not in CLOSED or not v[1].get("closed"):
        return None
    if (tid, v[1].get("closed")) in _have(read_rows(ctx.rows_path)):
        return None
    # писать некуда (песочница роли) — понять до чтения транскриптов, а не после
    os.makedirs(os.path.dirname(ctx.rows_path), exist_ok=True)
    os.close(os.open(ctx.rows_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644))
    rows = append_rows(ctx.rows_path, make_rows(ctx, tasks, [tid], estimate=str(v[1]["closed"]) < since(ctx)))
    return rows[0] if rows else None


def sync(ctx, tasks, days=SYNC_DAYS):
    """Закрытые за последние days дней без строки → строки (так доходят закрытия ролей из песочницы и с доски).
    Закрытые до начала учёта (since) — с пометкой «оценка», как у backfill."""
    edge = time.strftime("%Y-%m-%d", time.localtime(ctx.t - days * 86400))
    have = _have(read_rows(ctx.rows_path))
    tids = [t for t, (_, h, _) in _closed_tasks(tasks).items()
            if str(h["closed"]) >= edge and (t, h["closed"]) not in have]
    if not tids:
        return []
    start = since(ctx)
    old = [t for t in tids if str(tasks[t][1]["closed"]) < start]
    rows = make_rows(ctx, tasks, [t for t in tids if t not in old]) + make_rows(ctx, tasks, old, estimate=True)
    return append_rows(ctx.rows_path, rows)


def backfill(ctx, tasks, frm, to=None, dry=False, out=None):
    """Задним числом: закрытые с frm по to (включительно) без строки → строки с estimate=True («оценка»)."""
    to = to or time.strftime("%Y-%m-%d", time.localtime(ctx.t))
    have = _have(read_rows(ctx.rows_path))
    tids = [t for t, (_, h, _) in _closed_tasks(tasks).items()
            if frm <= str(h["closed"]) <= to and (t, h["closed"]) not in have]
    rows = make_rows(ctx, tasks, tids, estimate=True)
    if not dry:
        append_rows(out or ctx.rows_path, rows)
    return rows


# --- свод -------------------------------------------------------------------------------------------------------

def latest(rows):
    """Последняя строка на задачу (переоткрыли и закрыли снова — считается последнее закрытие)."""
    by = {}
    for r in rows:
        k = r.get("id")
        if k not in by or (str(r.get("closed") or ""), str(r.get("recorded_at") or "")) >= \
                (str(by[k].get("closed") or ""), str(by[k].get("recorded_at") or "")):
            by[k] = r
    return list(by.values())


MERGED_RE = re.compile(r"\bPR\b.*\bслит[аоы]?\b|\bслит[аоы]?\b.*\bPR\b|\bPR\b.*\bmerged\b", re.I)
NOT_MERGED_RE = re.compile(r"\bне\s+слит|\bnot\s+merged", re.I)
FEW = 20  # меньше принятых задач в ячейке — «мало данных» (решение владельца [metis-0389] «А», 23.10)


def merged_index(tasks):
    """{id задач, в журнале которых есть строка «PR … слит»} — слитый PR принимает задачу и без вердикта argus."""
    out = set()
    for tid, (_, _, body) in tasks.items():
        if any(MERGED_RE.search(ln) and not NOT_MERGED_RE.search(ln) for ln in (body or "").split("\n")):
            out.add(tid)
    return out


def accepted(r, merged=()):
    """Задача принята (metis-0390): закрыта done и либо последний круг argus «принять» (кругов больше нуля и не все
    «вернуть»), либо PR слит (id в merged). Отменённые и закрытые без проверки и слияния не принятые."""
    if r.get("status") != "done":
        return False
    rounds = r.get("argus_rounds") or 0
    return (rounds > 0 and (r.get("argus_rejects") or 0) < rounds) or r.get("id") in merged


def _group(rows, merged=()):
    done = [r for r in rows if r.get("status") == "done"]
    known = [r for r in done if r.get("argus_first_pass") is not None]
    rounds = [r["argus_rounds"] for r in done if r.get("argus_rounds")]
    used = [r for r in rows if r.get("tokens_total")]
    hours = sorted(r["hours"] for r in done if isinstance(r.get("hours"), (int, float)))
    acc = [r for r in done if accepted(r, merged)]
    acc_used = [r for r in acc if r.get("tokens_total")]
    n = len(acc)
    own = lambda k: sum(r.get(k) or 0 for r in acc)
    return {
        # цена принятой задачи: расход принятых (разработчик + argus всех кругов) / принятые; «всего» — весь расход
        # группы, в том числе отменённых и не принятых, на принятую: сколько стоит принятая вместе с браком
        "accepted": n, "few": n < FEW,
        "acc_tokens": int(sum(r["tokens_total"] for r in acc_used) / len(acc_used)) if acc_used else None,
        "acc_usd": round(sum(r.get("usd") or 0 for r in acc_used) / len(acc_used), 2) if acc_used else None,
        "all_usd_per_acc": round(sum(r.get("usd") or 0 for r in rows) / n, 2) if n else None,
        "owner_notes": round(own("owner_notes") / n, 2) if n else None,
        "owner_answers": round(own("owner_answers") / n, 2) if n else None,
        "owner_moves": round(own("owner_moves") / n, 2) if n else None,
        "owner_returns": round(own("owner_returns") / n, 2) if n else None,
        "no_owner": (sum(1 for r in acc if not any(r.get(k) for k in (
            "owner_notes", "owner_answers", "owner_moves", "owner_returns"))) / n) if n else None,
        "tasks": len(done), "dropped": len(rows) - len(done),
        "first_pass": sum(1 for r in known if r["argus_first_pass"]), "first_known": len(known),
        "rounds_avg": round(sum(rounds) / len(rounds), 2) if rounds else None,
        "tokens_per_task": int(sum(r["tokens_total"] for r in used) / len(used)) if used else None,
        "usd_per_task": round(sum(r.get("usd") or 0 for r in used) / len(used), 2) if used else None,
        "with_usage": len(used), "usd": round(sum(r.get("usd") or 0 for r in rows), 2),
        "returns": sum(r.get("returns") or 0 for r in rows),
        "post_merge": sum(1 for r in rows if r.get("post_merge")),
        "hours_median": hours[len(hours) // 2] if hours else None,
        "estimate": sum(1 for r in rows if r.get("estimate")),
    }


def summary(rows, t, post=None, merged=()):
    """Свод: {"week": …, "all": …}, в каждом {"by_executor": {(исполнитель, модель, effort): группа},
    "by_direction": {направление: группа}}. post — свежий индекс возвратов после слияния (заменяет записанный)."""
    rows = latest(rows)
    if post is not None:
        rows = [dict(r, post_merge=post.get(r["id"], r.get("post_merge") or [])) for r in rows]
    w0 = week_start(t)
    week = [r for r in rows if (epoch(str(r.get("closed_at") or "")) or 0) >= w0]
    out = {"week_name": week_of(t)}
    byweek = defaultdict(list)
    for r in rows:
        c = epoch(str(r.get("closed_at") or ""))
        if c:
            byweek[week_of(c)].append(r)
    out["weeks"] = {k: _group(v, merged) for k, v in sorted(byweek.items())}
    for name, rs in (("week", week), ("all", rows)):
        ex, di = defaultdict(list), defaultdict(list)
        for r in rs:
            ex[(r.get("executor") or "—", r.get("model") or "—", r.get("effort") or "—")].append(r)
            di[r.get("direction") or "—"].append(r)
        out[name] = {"by_executor": {k: _group(v, merged) for k, v in ex.items()},
                     "by_direction": {k: _group(v, merged) for k, v in di.items()}, "total": _group(rs, merged)}
    return out


def _cell(g):
    fp = f"{g['first_pass']} из {g['first_known']}" if g["first_known"] else "—"
    num = lambda v, f="{}": f.format(v) if v is not None else "—"
    return [str(g["tasks"]), str(g["dropped"]), fp, num(g["rounds_avg"]),
            num(g["tokens_per_task"] and round(g["tokens_per_task"] / 1000), "{}K"),
            num(g["usd_per_task"], "{:.2f}"), str(g["returns"]), str(g["post_merge"]), num(g["hours_median"]),
            str(g["estimate"])]


HEAD = ["задач", "отменено", "с первого круга", "кругов", "токенов/задачу", "$/задачу", "возвратов",
        "после слияния", "часов (медиана)", "из них оценка"]


def _table(first, groups):
    lines = ["| " + " | ".join(first + HEAD) + " |", "|" + "---|" * (len(first) + len(HEAD))]
    for k, g in sorted(groups.items(), key=lambda x: (-x[1]["tasks"], str(x[0]))):
        ks = list(k) if isinstance(k, tuple) else [k]
        lines.append("| " + " | ".join(ks + _cell(g)) + " |")
    return "\n".join(lines)


def _limit_table(weeks, base=("2026-W42", "2026-W43")):
    """Таблица замера «Лимит» (metis-0390): по неделям; база «до пачки» — W42 и W43. Меньше FEW принятых — «мало данных»."""
    f = lambda v, fm: fm.format(v) if v is not None else "—"
    head = ["неделя", "принято", "токенов/принятую", "$/принятую", "$ всего/принятую", "заметок", "ответов",
            "переносов", "возвратов владельцем", "без вмешательства", "примечание"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for w, g in sorted(weeks.items()):
        note = ["база до пачки"] if w in base else []
        if g["few"]:
            note.append("мало данных")
        lines.append("| " + " | ".join([
            w, str(g["accepted"]), f(g["acc_tokens"] and round(g["acc_tokens"] / 1000), "{}K"),
            f(g["acc_usd"], "{:.2f}"), f(g["all_usd_per_acc"], "{:.2f}"), f(g["owner_notes"], "{:.2f}"),
            f(g["owner_answers"], "{:.2f}"), f(g["owner_moves"], "{:.2f}"), f(g["owner_returns"], "{:.2f}"),
            f(g["no_owner"] is not None and round(g["no_owner"] * 100), "{}%"), ", ".join(note) or "—"]) + " |")
    return "\n".join(lines)


def week_md(s, t):
    parts = [f"# Учёт задач: неделя {s['week_name']}", "",
             "Собрано из metrics/tasks.jsonl (pantheon metrics, metis-0294). "
             "«Оценка» — строки, восстановленные задним числом по журналам: расход и круги там неполные.", "",
             "Столбцы: «с первого круга» — итог первого проверенного head «принять» у всех argus, из задач, где он "
             "известен; «кругов» — среднее число проверенных head (SHA), а не вердиктов; токены и $ — среднее по "
             "задачам, где расход нашёлся; «возвратов» — круги с итогом «вернуть» и переносы владельцем назад; «после слияния» — задачи, на которые ссылается revert или hotfix.", ""]
    parts += ["## Замер пачки «Лимит»: цена принятой задачи и вмешательства владельца (metis-0390)", "",
              "Принятая — закрыта done, и последний круг argus «принять» либо PR слит. Токены и $ — среднее по принятым: "
              "все круги (разработчик + argus); «$ всего/принятую» — весь расход недели, включая отменённые и не "
              f"принятые, на принятую. Вмешательства — среднее на принятую задачу. Меньше {FEW} принятых — «мало "
              "данных». «% недели на задачу» в учёте не хранится — только токены и $ (оценка).", "",
              _limit_table(s.get("weeks", {})), ""]
    for name, label in (("week", f"Неделя {s['week_name']}"), ("all", "С начала учёта")):
        parts += [f"## {label}", "", "### По исполнителю × модели × effort", "",
                  _table(["исполнитель", "модель", "effort"], s[name]["by_executor"]), "",
                  "### По направлениям", "", _table(["направление"], s[name]["by_direction"]), ""]
    return "\n".join(parts)


def _slug(s):
    s = re.sub(r"[^\w.-]+", "-", str(s), flags=re.U).strip("-")
    return s[:60] or "x"


def _yaml(v):
    if v is None:
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return json.dumps(str(v), ensure_ascii=False)


def pult_notes(s, t):
    """{имя файла: текст} заметок Доска/Учёт/ для видов «Учёт недели» и «Учёт с начала» на Пульте."""
    notes = {}
    for name, period in (("week", "неделя"), ("all", "с начала")):
        for cut, key, groups in (("исполнитель", "by_executor", s[name]["by_executor"]),
                                 ("направление", "by_direction", s[name]["by_direction"])):
            for k, g in groups.items():
                ex, model, eff = k if isinstance(k, tuple) else ("", "", "")
                dirn = "" if isinstance(k, tuple) else k
                props = {"Тип": NOTE_TYPE, "Период": period, "Неделя": s["week_name"], "Срез": cut,
                         "Исполнитель": ex or None, "Модель": model or None, "Effort": eff or None,
                         "Направление": dirn or None, "Задач": g["tasks"], "Отменено": g["dropped"],
                         "С первого круга": (f"{g['first_pass']} из {g['first_known']}" if g["first_known"] else None),
                         "Кругов": g["rounds_avg"], "Токенов на задачу": g["tokens_per_task"],
                         "Долларов на задачу": g["usd_per_task"], "Возвратов": g["returns"],
                         "После слияния": g["post_merge"], "Часов": g["hours_median"], "Из них оценка": g["estimate"]}
                fname = _slug(f"{'неделя' if name == 'week' else 'всё'}-{cut}-" + "-".join(
                    x for x in (ex, model, eff, dirn) if x)) + ".md"
                text = "---\n" + "".join(f"{p}: {_yaml(v)}\n" for p, v in props.items() if v is not None) + "---\n"
                notes[fname] = text
    return notes


def write_if_changed(path, text):
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return True


def sync_pult(board, notes):
    """Свои заметки в Доска/Учёт/ — записать изменившиеся, убрать свои устаревшие (Тип: учёт); чужие не трогать."""
    d = os.path.join(board, DIR_NAME)
    changed = 0
    for n, text in notes.items():
        changed += write_if_changed(os.path.join(d, n), text)
    for f in os.listdir(d) if os.path.isdir(d) else []:
        p = os.path.join(d, f)
        if f in notes or not f.endswith(".md") or os.path.islink(p) or not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                first = fh.read(400)
        except (OSError, UnicodeDecodeError):
            continue
        if first.startswith("---\n") and f"\nТип: {_yaml(NOTE_TYPE)}\n" in first:
            os.remove(p)
            changed += 1
    return changed


def publish(ctx, tasks):
    """Свод → metrics/week-<неделя>.md и заметки Пульта (если задана доска). → свод."""
    s = summary(read_rows(ctx.rows_path), ctx.t, post_merge_index(tasks), merged_index(tasks))
    write_if_changed(os.path.join(ctx.pantheon, "metrics", f"week-{s['week_name']}.md"), week_md(s, ctx.t))
    if ctx.board and os.path.isdir(ctx.board):
        sync_pult(ctx.board, pult_notes(s, ctx.t))
    return s
