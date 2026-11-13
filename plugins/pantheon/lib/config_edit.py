"""Настройки, хуки и .mcp.json проекта — по подтверждению владельца, привязанному к sha256 (metis-0844).

Решение владельца 14.11 (вариант А): роль направления сама эти файлы не пишет — guard protect-config и песочница окна
их закрывают. Она кладёт заявку с новым текстом, владелец подтверждает «да» в окне вопросов Зевса или Touch ID
(одно на выбор), а файл пишет плановый проход — вне окна, в worktree роли, и только если файл с заявки не изменился.
Дальше роль коммитит его в свою ветку, и правка идёт обычным PR через шлюз. Образец — owner_edit.py (metis-0910):
его разбор диффа, вопрос с md и окно помощника слияния используются отсюда.

  pantheon config request <файл>=<новый текст> [<файл>=<новый текст> …] --task ID [--why "зачем"]
        заявка из окна направления: <файл> — путь в linked worktree проекта (.mcp.json, .claude/settings.json,
        .claude/settings.local.json, .claude/hooks/<путь>; FILES), <новый текст> — файл, откуда взять текст целиком.
        Файлов — до MAX_FILES, все из одной worktree. Файла может не быть — тогда он новый (права 644). Печатает вопрос
        для Зевса «[<id>] …» с первыми SHORT знаками sha заявки. Заявка — config-edit/ рядом с PANTHEON_TMP (кэш окна)
  pantheon config status [ID]       заявки и итоги (в окне — свои)
  pantheon config cancel ID         снять свою заявку
  pantheon config run               проход — только плановый проход (из окна Claude Code — отказ)

Что проверяется — и в заявке, и в проходе, и ещё раз под замком перед записью (facts):
  - окно — по папке кэша, где лежит заявка, а не из её текста; вне окна направления заявки нет;
  - worktree — linked (в корне .git — файл «gitdir: …»), основной репозиторий и сама worktree внутри папок окна по
    domains.json. Основная копия проекта — отказ: она папка запуска окна, правка там действует сразу, мимо PR;
  - пути — без ссылок: каждая папка от корня worktree до файла — настоящая (O_NOFOLLOW через dir_fd);
  - файл сейчас — тот же, что при заявке (sha256 или «нет файла»), дифф и sha заявки пересчитаны и сошлись;
  - новый текст — UTF-8 без NUL и невидимых знаков, не больше NEW_MAX; .json — объект JSON;
  - taint (guard tg-taint): у сессии заявки (CLAUDE_CODE_SESSION_ID) стоит флаг сырого текста Telegram — отказ, и
    с подтверждением. Сессия не опознана — тоже отказ: taint не проверить.
«Sha заявки» — sha256 от [worktree, [файл, sha до, sha после, дифф] каждого]: «да» и палец относятся ровно к этим
байтам.

Подтверждение (process):
  1. «Да» в окне вопросов: последний ответ у Зевса на «[id] …» не раньше заявки; вопрос — дословно question(заявки)
     (после one_line). «Да» на другой текст — отказ; не «да» — отклонено.
  2. Иначе Touch ID, когда владелец у Mac: окно помощника слияния с проектом, worktree, файлами, ключами JSON (что
     влезет) и коротким sha; полный дифф — путь STATE/config-edit/diffs/<id>.diff (его проход пишет до окна). Палец —
     заявка перечитана, байты те же — строка `<время> config-edit-approve <id> <sha>` в
     owner-log/config-edit-approve.log, запись. Отказ — отклонено; время вышло — повтор через RETRY_SEC.
  3. Запись: заявка забрана переименованием, под замком facts заново, журнал STATE/logs/config-edit.jsonl открывается
     до записи, каждый файл — атомарно (временный рядом, os.replace), права прежние, у нового — 644. Итог роли —
     <id>.result.json рядом с заявкой. Итог у id уже есть в журнале — та же заявка второй раз не применяется.
"""
import contextlib
import difflib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from datetime import datetime

P = None  # модуль pantheon (lib/pantheon.py) — ставит set_core()


def set_core(mod):
    global P
    P = mod


def O():  # noqa: E743, N802 — owner_edit.py: общие разбор диффа, md, окно Touch ID
    return P.owner_edit_mod()


_SEG = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,80}"
FILES = re.compile(rf"\.mcp\.json|\.claude/settings(?:\.local)?\.json|\.claude/hooks/{_SEG}(?:/{_SEG}){{0,2}}")
ID_RE = re.compile(r"pc-\d{8}-\d{6}-[0-9a-f]{6}")
SID_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}")   # как session_key в guard taint.py
MAX_FILES = 4
ABSENT = "absent"         # «sha до» у файла, которого нет
NEW_MODE = 0o644
JOURNAL = "config-edit.jsonl"
APPROVE_LOG = "config-edit-approve.log"
USAGE = ("pantheon config request <файл>=<новый текст> [<файл>=<новый текст> …] --task ID [--why \"зачем\"] | "
         "status [ID] | cancel ID | run")


class Refuse(Exception):
    """Заявка не годится: текст — роли и в журнал."""


def err(text, code=2):
    print(text, file=sys.stderr)
    return code


# --- worktree, окно, taint -----------------------------------------------------------------------------------------

def _inside(p, folders):
    return any(p == f or p.startswith(f.rstrip("/") + "/") for f in folders)


def window_folders(win):
    """Папки окна направления настоящими путями (domains.json); окна нет в реестре — []."""
    doms = (P.read_json(P.path("domains.json"), {}) or {}).get("domains") or {}
    got = doms.get(win) if isinstance(doms, dict) else None
    return [os.path.realpath(os.path.expanduser(f)) for f in got or [] if isinstance(f, str) and f]


def git_main(root):
    """Основной репозиторий linked worktree root (настоящий путь) или Refuse: в корне .git — обычный файл
    «gitdir: …», в папке gitdir — commondir, сам gitdir лежит в <common>/worktrees/."""
    g = os.path.join(root, ".git")
    try:
        st = os.lstat(g)
    except OSError:
        raise Refuse(f"{P.tilde(root)}: не корень git worktree (нет .git)")
    if not stat.S_ISREG(st.st_mode):
        raise Refuse(f"{P.tilde(root)}: основная копия проекта, а не worktree роли — правка в ней действует сразу, мимо "
                     "PR; заявку — из своей worktree (git worktree add)")
    try:
        with open(g, encoding="utf-8") as fh:
            line = fh.read(4096).strip()
        gd = os.path.realpath(os.path.join(root, line.removeprefix("gitdir:").strip()))
        with open(os.path.join(gd, "commondir"), encoding="utf-8") as fh:
            common = os.path.realpath(os.path.join(gd, fh.read(4096).strip()))
    except (OSError, UnicodeDecodeError):
        raise Refuse(f"{P.tilde(root)}: .git не читается как ссылка linked worktree")
    if not line.startswith("gitdir:") or os.path.dirname(gd) != os.path.join(common, "worktrees") \
            or os.path.basename(common) != ".git":
        raise Refuse(f"{P.tilde(root)}: .git не ведёт в <репозиторий>/.git/worktrees — не linked worktree")
    return os.path.dirname(common)


def worktree_of(path):
    """Корень worktree, где лежит path (абсолютный путь): ближайшая папка выше с .git. Нет — Refuse."""
    d = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            raise Refuse(f"{path}: не в git-репозитории")
        d = up


def taint_flag(sid):
    """Флаг guard tg-taint у сессии sid: True — стоит, None — сессию не опознать (taint не проверить)."""
    if not isinstance(sid, str) or not SID_RE.fullmatch(sid) or ".." in sid:
        return None
    return os.path.lexists(os.path.join(P.HOME, ".local", "state", "tg-taint", sid))


def check_owner(req):
    """Окно заявки владеет её worktree, worktree — linked, сессия без taint. Иначе Refuse."""
    win, root = req.get("window"), req["root"]
    folders = window_folders(win) if win else []
    if not folders:
        raise Refuse(f"окно {win or '(не окно роли)'}: нет папок направления в domains.json — заявка только из окна "
                     "своего направления")
    if os.path.realpath(root) != root:
        raise Refuse(f"{P.tilde(root)}: в пути ссылка")
    main = git_main(root)
    if not (_inside(root, folders) and _inside(main, folders)):
        raise Refuse(f"{P.tilde(root)}: проект не в папках окна {win} — чужой проект")
    flag = taint_flag(req.get("sid"))
    if flag is None:
        raise Refuse("сессию заявки не опознать (нет CLAUDE_CODE_SESSION_ID) — taint не проверить")
    if flag:
        raise Refuse("в сессии заявки сырой текст Telegram (guard tg-taint) — правку настроек не применяю и с "
                     "подтверждением; новая заявка — из чистой сессии")
    return main


# --- файлы через dir_fd без ссылок ---------------------------------------------------------------------------------

def _parent_fd(root, rel, create=False):
    """fd папки файла rel в worktree root: каждая часть — настоящая папка (O_NOFOLLOW); create — недостающие создать.
    Нет папки и не create — None. Ссылка или не папка — Refuse."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in rel.split("/")[:-1]:
            try:
                nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    os.close(fd)
                    return None
                os.mkdir(part, 0o755, dir_fd=fd)
                nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as e:
                raise Refuse(f"{rel}: папка «{part}» — ссылка или не папка ({e.strerror or type(e).__name__})")
            os.close(fd)
            fd = nfd
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_cur(root, rel):
    """Байты файла rel или None — файла нет. Ссылка, не свой, не обычный, больше NEW_MAX — Refuse."""
    pfd = _parent_fd(root, rel)
    if pfd is None:
        return None
    try:
        fd = os.open(os.path.basename(rel), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=pfd)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise Refuse(f"{rel}: не читается ({e.strerror or type(e).__name__})")
    finally:
        os.close(pfd)
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1:
            raise Refuse(f"{rel}: не обычный свой файл")
        data = fh.read(O().NEW_MAX + 1)
    if len(data) > O().NEW_MAX:
        raise Refuse(f"{rel}: больше {O().NEW_MAX // 1024} КБ")
    return data


def write_file(root, rel, data):
    """Файл rel атомарно: временный рядом (O_EXCL, без ссылок), права прежние или NEW_MODE, os.replace."""
    pfd = _parent_fd(root, rel, create=True)
    base = os.path.basename(rel)
    try:
        try:
            mode = stat.S_IMODE(os.stat(base, dir_fd=pfd, follow_symlinks=False).st_mode)
        except FileNotFoundError:
            mode = NEW_MODE
        tmp = f".{base}.config-edit.{os.getpid()}.{secrets.token_hex(3)}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=pfd)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.chmod(tmp, mode, dir_fd=pfd)
            os.replace(tmp, base, src_dir_fd=pfd, dst_dir_fd=pfd)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp, dir_fd=pfd)
            raise
    finally:
        os.close(pfd)


# --- текст, дифф, вопрос -------------------------------------------------------------------------------------------

def check_text(rel, new):
    oe = O()
    if not isinstance(new, str) or "\x00" in new or len(new.encode("utf-8")) > oe.NEW_MAX:
        raise Refuse(f"новый текст {rel}: не текст, с NUL или больше {oe.NEW_MAX // 1024} КБ")
    bad = oe.hidden_at(new)
    if bad:
        raise Refuse(f"новый текст {rel}, строка {bad[0]}: невидимый или управляющий знак U+{ord(bad[1]):04X} — "
                     "вопрос и окно Touch ID его не покажут")
    if rel.endswith(".json"):
        try:
            if not isinstance(json.loads(new), dict):
                raise ValueError("не объект")
        except ValueError as e:
            raise Refuse(f"новый текст {rel} — не объект JSON: {e}")


def make_diff(rel, old, new):
    def lines(text):
        out = text.splitlines(True)
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n\\ нет перевода строки в конце\n"
        return out
    return "".join(difflib.unified_diff(lines(old), lines(new), "a/" + rel, "b/" + rel, n=2))


def req_sha(root, files):
    return O().sha(json.dumps([root, [[f["rel"], f["before"], f["after"], f["diff"]] for f in files]],
                              ensure_ascii=False))


def json_keys(f):
    """Изменённые ключи .json: «путь: старое → новое» (owner_edit.key_row, массив — одно значение); иначе None."""
    if not f["rel"].endswith(".json"):
        return None
    oe = O()
    try:
        lo = dict(oe._leaves(json.loads(f["old"]))) if f["before"] != ABSENT else {}
        ln = dict(oe._leaves(json.loads(f["new"])))
    except ValueError:
        return ["?"]
    return [oe.key_row(p, lo.get(p, oe.MISSING), ln.get(p, oe.MISSING)) for p in list(lo) + [p for p in ln if p not in lo]
            if p not in lo or p not in ln or oe._canon(lo[p]) != oe._canon(ln[p])]


def labels(req):
    """(проект, worktree) для вопроса и окна: проект — ~/путь основного репозитория, worktree — путь от него."""
    main = req.get("main") or ""
    root = req["root"]
    wt = root[len(main) + 1:] if main and root.startswith(main + "/") else P.tilde(root)
    return P.tilde(main), wt


def file_rows(f, fix=str):
    oe = O()
    rows = [(oe.esc(ln) if f["rel"].endswith(".json") else oe.mark(ln)).replace(oe.SEP, "\\u23ce")
            for ln, _ in oe.walk(f["diff"])]
    keys = json_keys(f)
    head = f"{fix(f['rel'])} ({'новый файл' if f['before'] == ABSENT else 'правка'}), строк {len(rows)}: "
    tail = (f". Ключи, изменено {len(keys)}: " + f" {oe.SEP} ".join(fix(k) for k in keys)) if keys is not None else ""
    return head + f" {oe.SEP} ".join(fix(r) for r in rows) + tail


def question(req):
    """Вопрос для Зевса одной строкой: [id], проект, worktree, задача, sha заявки, каждый файл с правкой строками и
    ключами JSON, пояснение роли последним. Всё от роли и из файлов — через md (виден буквально)."""
    oe = O()
    proj, wt = labels(req)
    why = f". Пояснение роли: {oe.md(oe.mark(req['why']))}" if req.get("why") else ""
    return (f"[{req['id']}] Записать настройки проекта {oe.md(proj)} в worktree {oe.md(wt)} (задача {req['task']}, sha "
            f"{req['sha'][:oe.SHORT]})? Файлов {len(req['files'])}. "
            + f" {oe.SEP} ".join(file_rows(f, oe.md) for f in req["files"]) + why)


def diff_path(req):
    return P.path("config-edit", "diffs", f"{req['id']}.diff")


def window_text(req):
    """Текст окна Touch ID: проект, worktree, файлы, ключи JSON (сколько влезет), короткий sha и путь к полному диффу.
    Не влезает даже без ключей — None (тогда только «да» в окне вопросов)."""
    oe = O()
    proj, wt = labels(req)
    head = (f"Записать настройки {proj} в worktree {wt} ({req.get('window')}, {req['task']}, sha {req['sha'][:oe.SHORT]}). "
            f"Файлы: {', '.join(f['rel'] + (' (новый)' if f['before'] == ABSENT else '') for f in req['files'])}.")
    tail = f" Дифф целиком: {P.tilde(diff_path(req))}"
    keys = [k for f in req["files"] for k in (json_keys(f) or [])]
    text = head + tail
    for n in range(len(keys), 0, -1):
        more = f" и ещё {len(keys) - n}" if n < len(keys) else ""
        cand = head + " Ключи: " + "; ".join(keys[:n]) + more + "." + tail
        if len(cand) <= oe.WINDOW_MAX and P.handoff_mod().showable(cand):
            text = cand
            break
    return text if len(text) <= oe.WINDOW_MAX and P.handoff_mod().showable(text) else None


def facts(req):
    """Сверка заявки с диском сейчас: окно и worktree (check_owner), каждый файл тот же, что при заявке, новый текст
    годен, дифф и sha заявки сходятся. → основной репозиторий; иначе Refuse."""
    main = check_owner(req)
    oe = O()
    files = []
    for f in req["files"]:
        cur = read_cur(req["root"], f["rel"])
        before = ABSENT if cur is None else oe.sha(cur)
        if before != f["before"]:
            raise Refuse(f"{f['rel']} изменился после заявки ({before[:12]}, в заявке {f['before'][:12]}) — новая заявка")
        old = "" if cur is None else cur.decode("utf-8", "replace")
        if cur is not None and oe.sha(old) != before:
            raise Refuse(f"{f['rel']}: не UTF-8")
        check_text(f["rel"], f["new"])
        diff = make_diff(f["rel"], old, f["new"])
        if f["old"] != old or f["diff"] != diff or f["after"] != oe.sha(f["new"]):
            raise Refuse(f"заявка не сходится с {f['rel']} и новым текстом — не применяю")
        files.append(f)
    if req_sha(req["root"], files) != req["sha"] or (req.get("main") and req["main"] != main):
        raise Refuse("sha заявки не сходится с файлами — не применяю")
    return main


# --- очередь, журнал -----------------------------------------------------------------------------------------------

def own_dir():
    tmp = os.environ.get("PANTHEON_TMP")
    return os.path.join(os.path.dirname(os.path.realpath(tmp)), "config-edit") if tmp else None


def caches():
    return os.path.join(P.HOME, "Library", "Caches", "pantheon-sandbox")


def queue_dirs():
    """[(папка заявок, окно)] — только кэши окон: окно — по имени папки, не из текста заявки."""
    out = []
    with contextlib.suppress(OSError):
        for name in sorted(os.listdir(caches())):
            d = os.path.join(caches(), name, "config-edit")
            if O().WINDOW_RE.fullmatch(name) and not os.path.islink(os.path.join(caches(), name)) and \
                    os.path.isdir(d) and not os.path.islink(d):
                out.append((d, name))
    return out


def open_queue(win):
    try:
        fd = os.open(caches(), os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return None
    try:
        for part in (win, "config-edit"):
            nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
    except OSError:
        os.close(fd)
        return None
    return fd


def valid(req, name):
    oe = O()
    if not (isinstance(req, dict) and ID_RE.fullmatch(str(req.get("id"))) and name == f"{req['id']}.req.json"
            and isinstance(req.get("root"), str) and os.path.isabs(req["root"]) and isinstance(req.get("main"), str)
            and oe.HEX64.fullmatch(str(req.get("sha"))) and isinstance(req.get("created"), (int, float))
            and all(isinstance(req.get(k), str) for k in ("task", "why", "sid"))
            and oe.TASK_RE.fullmatch(req["task"]) and oe.why_ok(req["why"])
            and isinstance(req.get("files"), list) and 0 < len(req["files"]) <= MAX_FILES):
        return False
    rels = [f.get("rel") if isinstance(f, dict) else None for f in req["files"]]
    return len(set(rels)) == len(rels) and all(
        FILES.fullmatch(str(f.get("rel"))) and all(isinstance(f.get(k), str) for k in ("old", "new", "diff"))
        and (f.get("before") == ABSENT or oe.HEX64.fullmatch(str(f.get("before"))))
        and oe.HEX64.fullmatch(str(f.get("after"))) for f in req["files"])


def load_req(name, dir_fd=None):
    raw = O().read_file(name, 3 * MAX_FILES * O().NEW_MAX + 64 * 1024, dir_fd=dir_fd)
    if raw is None:
        return None, None
    with contextlib.suppress(ValueError):
        req = json.loads(raw)
        if valid(req, os.path.basename(name)):
            return req, raw
    return None, raw


def journal_open():
    os.makedirs(P.path("logs"), exist_ok=True)
    fd = os.open(P.path("logs", JOURNAL), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "a", encoding="utf-8")


def finished(rid):
    try:
        fh = open(P.path("logs", JOURNAL), encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False
    with fh:
        for ln in fh:
            if rid in ln:
                with contextlib.suppress(ValueError):
                    rec = json.loads(ln)
                    if isinstance(rec, dict) and rec.get("id") == rid and rec.get("state") in O().FINAL:
                        return True
    return False


def finish(dfd, req, state, note, **extra):
    """Итог: журнал первым (он — правда о записи), затем <id>.result.json роли; его не записать — тревога."""
    rec = dict({"id": req["id"], "window": req.get("window"), "root": req.get("root"), "task": req.get("task"),
                "files": [f.get("rel") for f in req.get("files") or [] if isinstance(f, dict)], "sha": req.get("sha"),
                "state": state, "note": str(note)[:400]}, **extra)
    rec["time"] = datetime.fromtimestamp(P.now()).astimezone().isoformat(timespec="seconds")
    with journal_open() as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    try:
        O().write_atomic(f"{req['id']}.result.json", {"id": req["id"], "state": state, "note": str(note)[:400],
                                                      "t": P.now()}, dir_fd=dfd)
    except OSError as e:
        P.alert_once("config-edit-result", type(e).__name__, f"настройки проекта: итог {req['id']} ({state}) роли не "
                     f"записан — {type(e).__name__}: {e}; в журнале logs/{JOURNAL} он есть", "config-edit")


# --- команды роли --------------------------------------------------------------------------------------------------

def parse_pairs(pos):
    """«<файл>=<новый текст>» → (корень worktree, [(путь от корня, новый текст)]); одна worktree, без повторов."""
    oe = O()
    roots, files = set(), []
    for a in pos:
        dst, src = a.split("=", 1)
        root = worktree_of(dst)
        rel = os.path.relpath(os.path.join(os.path.realpath(os.path.dirname(os.path.abspath(dst))),
                                           os.path.basename(dst)), root)
        if not FILES.fullmatch(rel):
            raise Refuse(f"{dst}: не из списка (.mcp.json, .claude/settings.json, .claude/settings.local.json, "
                         ".claude/hooks/<путь>) от корня worktree")
        raw = oe.read_file(src, oe.NEW_MAX)
        if raw is None:
            raise Refuse(f"{src}: не читается, ссылка или больше {oe.NEW_MAX // 1024} КБ")
        try:
            new = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise Refuse(f"{src}: не UTF-8")
        check_text(rel, new)
        roots.add(root)
        files.append((rel, new))
    if len(roots) != 1 or len({r for r, _ in files}) != len(files):
        raise Refuse("все файлы — из одной worktree и без повторов")
    return roots.pop(), files


def cmd_request(args):
    oe, prog = O(), "pantheon config request"
    try:
        pos, kv = oe.parse_opts(args, ("--task", "--why"))
    except ValueError as e:
        return err(f"{prog}: {e}")
    if not pos or not oe.TASK_RE.fullmatch(kv.get("--task", "")) or any("=" not in a for a in pos):
        return err("вызов: " + USAGE.split(" | ")[0])
    qdir = own_dir()
    win, role = oe.who()
    why = " ".join(kv.get("--why", "").split())
    try:
        if not qdir or not win:
            raise Refuse("только из окна направления (нет PANTHEON_TMP) — вне окна правьте файлы сами")
        if len(pos) > MAX_FILES:
            raise Refuse(f"файлов больше {MAX_FILES} — разбейте на заявки")
        if not oe.why_ok(why):
            raise Refuse(f"--why длиннее {oe.WHY_MAX} знаков или с невидимым знаком")
        root, files = parse_pairs(pos)
        req = {"id": "pc-" + datetime.fromtimestamp(P.now()).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3),
               "root": root, "main": "", "window": win, "task": kv["--task"], "why": why, "role": role,
               "sid": os.environ.get("CLAUDE_CODE_SESSION_ID") or "", "created": P.now(), "files": []}
        req["main"] = check_owner(req)
        for rel, new in files:
            cur = read_cur(root, rel)
            old = "" if cur is None else cur.decode("utf-8", "replace")
            if old == new and cur is not None:
                raise Refuse(f"{rel}: новый текст совпадает с файлом — править нечего")
            req["files"].append({"rel": rel, "before": ABSENT if cur is None else oe.sha(cur), "after": oe.sha(new),
                                 "old": old, "new": new, "diff": make_diff(rel, old, new)})
        req["sha"] = req_sha(root, req["files"])
        facts(req)
    except Refuse as e:
        return err(f"{prog}: отказ — {e}")
    req.pop("window")
    try:
        os.makedirs(qdir, mode=0o700, exist_ok=True)
        oe.write_atomic(os.path.join(qdir, f"{req['id']}.req.json"), req)
    except OSError as e:
        return err(f"{prog}: заявку не записать ({e})", 3)
    req["window"] = win
    touch = window_text(req)
    print(f"заявка {req['id']}: {P.tilde(root)}, файлов {len(req['files'])}, sha {req['sha']}\n\n"
          + "".join(f["diff"] for f in req["files"])
          + "\nВопрос Зевсу (окно вопросов, варианты «А — Да, записать» и «Б — Нет»), строка целиком:\n  "
          + question(req) + "\n"
          + ("Или Touch ID: плановый проход покажет окно с этой заявкой, когда владелец у Mac.\n" if touch else
             "Окно Touch ID заявку не покажет — только «да» в окне вопросов.\n")
          + "Запишет плановый проход в эту worktree, если файлы до того не изменятся; закоммить их сам. "
          + f"Итог — pantheon config status {req['id']}")
    return 0


def cmd_status(args):
    rows = []
    dirs = [(own_dir(), O().who()[0])] if os.environ.get("PANTHEON_TMP") else queue_dirs()
    for d, win in dirs:
        with contextlib.suppress(OSError):
            for n in sorted(os.listdir(d)):
                m = re.fullmatch(r"(pc-\d{8}-\d{6}-[0-9a-f]{6})\.(req|result)\.json", n)
                if not m or (args and m.group(1) != args[0]):
                    continue
                if m.group(2) == "req":
                    req, _ = load_req(os.path.join(d, n))
                    if req:
                        rows.append(f"{m.group(1)}  ждёт «да» или Touch ID  {win}  {P.tilde(req['root'])}  "
                                    f"{', '.join(f['rel'] for f in req['files'])}  sha {req['sha'][:O().SHORT]}")
                else:
                    res = O().read_result(d, m.group(1)) or {}
                    rows.append(f"{m.group(1)}  {res.get('state')}  {win}  {str(res.get('note'))[:200]}")
    print("\n".join(rows) if rows else "заявок нет")
    return 0


def cmd_cancel(args):
    d = own_dir()
    if len(args) != 1 or not ID_RE.fullmatch(args[0]) or not d:
        return err("вызов: pantheon config cancel ID (из окна направления)")
    try:
        os.unlink(os.path.join(d, f"{args[0]}.req.json"))
    except OSError:
        return err(f"заявки {args[0]} в своей очереди нет", 1)
    print(f"заявка {args[0]} снята")
    return 0


# --- проход --------------------------------------------------------------------------------------------------------

def ask(text):
    """Окно Touch ID помощника слияния: 0 палец, 1 отказ, 2 не показать, 3 время вышло, None — помощника нет."""
    M = P.merge_mod()
    h = M.helper()
    if not h:
        return None
    try:
        return subprocess.run([h, text, str(M.WINDOW_WAIT), O().CANCEL_LABEL], stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=M.WINDOW_WAIT + 60).returncode
    except (OSError, subprocess.SubprocessError):
        return 2


def consent_decision(req):
    """Последний ответ владельца у Зевса на «[id] …» не раньше заявки → (yes|no|wrong, заголовок) или None."""
    oe = O()
    days = min(30.0, max(0.1, (P.now() - req["created"]) / 86400 + 0.01))
    found, _, _ = P.consent_found(req["id"], days)
    own = [(t, head, body) for t, head, body in found if head.endswith(" у Зевса") and t >= int(req["created"])]
    if not own:
        return None
    _, head, body = own[-1]
    if not P.consent_is_yes(body):
        return "no", head
    q = oe.one_line(body.split("\nответ:")[0].removeprefix("вопрос:"))
    return ("yes" if q == oe.one_line(question(req)) else "wrong"), head


def approve_line(req):
    d = P.path("owner-log")
    if os.path.islink(d):
        raise OSError("owner-log — ссылка")
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd = os.open(os.path.join(d, APPROVE_LOG), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.fromtimestamp(P.now()).astimezone().isoformat(timespec='seconds')} config-edit-approve "
                 f"{req['id']} {req['sha']}\n")


def apply(dfd, name, req, how, evidence):
    """Одна запись: заявка забрана переименованием, под замком facts заново и журнал открыт — файлы атомарно."""
    taken = f"{name}.taken"
    try:
        os.rename(name, taken, src_dir_fd=dfd, dst_dir_fd=dfd)
    except OSError:
        return None
    done = []
    try:
        with P.lock("config-edit-apply"):
            facts(req)
            journal_open().close()   # журнал не дописать — файлы не трогаю
            if how == "touchid":
                approve_line(req)
            for f in req["files"]:
                write_file(req["root"], f["rel"], f["new"].encode("utf-8"))
                done.append(f["rel"])
            got = {f["rel"]: O().sha(read_cur(req["root"], f["rel"]) or b"")[:12] for f in req["files"]}
        return finish(dfd, req, "done", f"записано ({'«да» в окне вопросов' if how == 'consent' else 'Touch ID'}) в "
                      f"{P.tilde(req['root'])}: {', '.join(done)} — закоммить в свою ветку", how=how, after=got,
                      evidence=evidence)
    except Refuse as e:
        return finish(dfd, req, "refused", str(e), how=how)
    except OSError as e:
        return finish(dfd, req, "failed", f"{type(e).__name__}: {e}; записано до сбоя: {', '.join(done) or 'ничего'}",
                      how=how)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(taken, dir_fd=dfd)


def drop(dfd, name, req, state, note):
    with contextlib.suppress(OSError):
        os.unlink(name, dir_fd=dfd)
    return finish(dfd, req, state, note)


def write_diff(req):
    p = diff_path(req)
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    tmp = f"{p}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("".join(f["diff"] for f in req["files"]))
    os.replace(tmp, p)


def process(dfd, win, name):
    oe = O()
    req, raw = load_req(name, dir_fd=dfd)
    if req is None:
        with contextlib.suppress(OSError):
            os.unlink(name, dir_fd=dfd)
        return None
    req["window"] = win   # окно — по месту папки заявки, не из её текста
    if finished(req["id"]):
        return drop(dfd, name, req, "refused", "итог этой заявки уже в журнале — второй раз не применяется")
    try:
        req["created"] = min(req["created"], os.stat(name, dir_fd=dfd, follow_symlinks=False).st_ctime)
    except OSError:
        return None
    if P.now() - req["created"] > oe.REQ_TTL:
        return drop(dfd, name, req, "dropped", f"заявка старше {oe.REQ_TTL // 3600} ч без ответа — снята")
    try:
        facts(req)
    except Refuse as e:
        return drop(dfd, name, req, "refused", str(e))
    try:
        said = consent_decision(req)
    except P.ConsentLogError as e:
        P.alert_once("config-edit-consent", type(e).__name__, f"настройки проекта: {e}", "config-edit")
        said = None
    if said and said[0] == "yes":
        return apply(dfd, name, req, "consent", said[1])
    if said and said[0] == "no":
        return drop(dfd, name, req, "declined", f"владелец ответил не «да» ({said[1]})")
    if said:
        return drop(dfd, name, req, "refused", f"«да» на вопрос не дословно из заявки (sha {req['sha'][:oe.SHORT]}) — "
                    "новая заявка и вопрос строкой целиком")
    return touch(dfd, win, name, req, raw)


def touch(dfd, win, name, req, raw):
    """Touch ID, когда «да» нет: окно, когда владелец у Mac; палец — заявка перечитана, байты те же — запись."""
    oe = O()
    text = window_text(req)
    if text is None or P.idle_sec() > oe.PRESENT_SEC:
        return None
    mark = P.path("config-edit", "retry", req["id"])
    with contextlib.suppress(OSError):
        if P.now() - os.stat(mark).st_mtime < oe.RETRY_SEC:
            return None
    write_diff(req)
    code = ask(text)
    if code is None or code == 2:
        P.alert_once("config-edit-window", str(code), "настройки проекта: окно Touch ID не показать — заявки ждут «да» "
                     "в окне вопросов", "config-edit")
        return None
    if code == 3:
        os.makedirs(os.path.dirname(mark), mode=0o700, exist_ok=True)
        with open(mark, "w"):
            pass
        return None
    if code != 0:
        return drop(dfd, name, req, "declined", "владелец отказал в окне Touch ID")
    req2, raw2 = load_req(name, dir_fd=dfd)
    if req2 is None or raw2 != raw:
        return drop(dfd, name, req, "dropped", "заявку сменили или сняли, пока окно было открыто — палец не засчитан")
    req2["window"] = win
    return apply(dfd, name, req2, "touchid", "Touch ID")


def pending():
    for d, _ in queue_dirs():
        with contextlib.suppress(OSError):
            if any(n.endswith(".req.json") for n in os.listdir(d)):
                return True
    return False


def cmd_run():
    if "CLAUDECODE" in os.environ or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        return err("pantheon config run: только плановый проход, не из окна Claude Code")
    why = P.merge_mod().clean_env()
    if why:
        return err(f"pantheon config run: {why} — окружение прохода подменено, прохода нет")
    rc = 0
    with P.lock("config-edit-run", block=False) as got:
        if not got:
            return 0
        for _, win in queue_dirs():
            dfd = open_queue(win)
            if dfd is None:
                continue
            try:
                for n in sorted(n for n in os.listdir(dfd) if n.endswith(".req.json")):
                    try:
                        process(dfd, win, n)
                    except Exception as e:  # noqa: BLE001 — одна заявка не останавливает остальные
                        rc = 1
                        P.alert_once("config-edit-run", type(e).__name__, f"настройки проекта: заявка {n} — "
                                     f"{type(e).__name__}: {e}", "config-edit")
                O().sweep(dfd)
            except OSError:
                continue
            finally:
                os.close(dfd)
    return rc


def main(rest):
    if not rest:
        return err(USAGE)
    cmd, args = rest[0], rest[1:]
    if cmd == "request":
        return cmd_request(args)
    if cmd == "status":
        return cmd_status(args)
    if cmd == "cancel":
        return cmd_cancel(args)
    if cmd == "run" and not args:
        return cmd_run()
    return err(USAGE)
