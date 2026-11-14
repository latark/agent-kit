"""Заметка в карточку чужого направления из окна роли (metis-1187).

Окно роли пишет только в папку своего направления (песочница; блокировка .lock — tasks.dir_lock). Координатор,
проверивший у себя задачу системы, должен записать итог в её карточку без посредника. Поэтому:

  pantheon task set <чужая задача> --note "…"   из окна роли: запись в папку задач не разрешена (PermissionError
        у .lock) — заметка не теряется, а ложится заявкой <id>.req.json в task-note/ кэша окна
        (~/Library/Caches/pantheon-sandbox/<окно>/task-note, рядом с PANTHEON_TMP — как очереди config-edit и owner-edit).
        Печатается «заметка поставлена в очередь …, допишет плановый проход», код 0. Любое другое поле (status=,
        owner=, --body, --force) у такой задачи — отказ с причиной, код 1, ничего не записано: из чужого окна — только
        заметка. Вне окна роли (нет PANTHEON_TMP в кэше окон) отказ в записи — прежняя ошибка.
  pantheon task run   проход — только вне окна (тик зовёт его отдельным процессом из owner_edit_kick, пока есть
        заявки): каждая заявка — строка журнала карточки «<время> — агент (окно <имя>): заметка из чужого окна: «…»».

Имя окна — имя папки кэша, где лежит заявка, а не текст заявки. Текст заметки обезврежен (clean): управляющие и
невидимые знаки, переводы строк — пробел, «#» — «＃» (ни «## Слова владельца», ни «PR #N … →» отметок планового
прохода), «→» — «->», «/» — «∕», слово «PR» — «P‑R» (ни «PR 12 (owner/repo) слит», ни github.com/…/pull/N: связь
PR и коммита, слияние и закрытие по нему из такой строки не прочесть), ёлочки — кавычки «"», длина — до NOTE_MAX.
Разбор ссылок карточки (tasks.work_links) строки «агент (окно …)» пропускает и сам. Заявка забирается
переименованием (.taking) и только потом пишется в карточку: повторной строки при сбое удаления нет. Папку заявок
держит окно, поэтому проход открывает её по компонентам с O_NOFOLLOW и работает только через dir_fd (open_queue).
Нет задачи или заявка не по образцу — снята, итог — строка STATE/logs/task-note.jsonl; карточка занята — ждёт
следующего прохода, но не дольше REQ_TTL от min(created, mtime, ctime) файла (потом снята с тревогой).
"""
import contextlib
import json
import os
import re
import secrets
import stat
import sys
import time
import unicodedata

P = None  # модуль pantheon — ставит загрузчик pantheon._attach

__all__ = ["task_note_foreign", "task_note_pending", "task_note_run", "task_note_clean"]

SUB = "task-note"
WINDOW_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
ID_RE = re.compile(r"tn-\d{8}-\d{6}-[0-9a-f]{6}")
TASK_RE = re.compile(r"[a-z][a-z0-9]{0,30}(?:-[a-z0-9]{1,30}){0,3}-\d{1,6}")
NOTE_MAX = 2000
REQ_MAX = 64 * 1024
REQ_TTL = 24 * 3600
SKEW = 5 * 60  # с: created позже «сейчас» больше чем на SKEW — заявка не по образцу
PR_WORD = re.compile(r"\bpr(?![^\W\d_])", re.I)  # «PR 12», «PR#12», «PR12» — но не «print», «prod»
HIDDEN = ("Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp")
PREFIX = "заметка из чужого окна: "


def caches():
    return os.path.join(P.HOME, "Library", "Caches", "pantheon-sandbox")


def own_queue():
    """→ (окно, папка заявок) этого вызова или (None, None): только окно роли, чей PANTHEON_TMP лежит в кэше окон —
    иначе проход заявку не найдёт, и «поставлена в очередь» было бы неправдой."""
    tmp = os.environ.get("PANTHEON_TMP")
    if not tmp:
        return None, None
    cache = os.path.dirname(os.path.realpath(tmp))
    win = os.path.basename(cache)
    if not WINDOW_RE.fullmatch(win) or os.path.dirname(cache) != os.path.realpath(caches()):
        return None, None
    return win, os.path.join(cache, SUB)


def task_note_clean(note):
    """Текст заметки чужого окна → одна строка без разметки и отметок планового прохода (см. шапку)."""
    s = "".join(" " if unicodedata.category(c) in HIDDEN else c for c in str(note or ""))
    s = " ".join(s.split())[:NOTE_MAX]
    s = s.replace("#", "＃").replace("→", "->").replace("«", '"').replace("»", '"').replace("/", "∕")
    s = PR_WORD.sub(lambda m: m.group(0)[0] + "‑" + m.group(0)[1], s)  # «P‑R 12 … слит» — не номер PR
    return f"{PREFIX}«{s}»"


def _write_atomic(path, data):
    tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def task_note_foreign(T, tid, changes, note, body, force, exc):
    """task set из окна роли, когда папку задач tid писать нельзя (exc — PermissionError у .lock). → код выхода."""
    win, qdir = own_queue()
    if win is None:
        raise exc
    head = T.load_tasks(P.PANTHEON, T.WORK_TYPES).get(tid, ("", {}, ""))[1]
    where = f"направления {head.get('direction') or '?'}"
    extra = sorted(changes) + (["--body"] if body is not None else []) + (["--force"] if force is not None else [])
    if extra or not (note or "").strip():
        print(f"pantheon task set: {tid} — задача {where}, его папку окно {win} не пишет; из чужого окна меняется "
              f"только --note (заявкой), а {', '.join(extra) or 'пустая заметка'} — нет. Ничего не записано: поля "
              f"меняет координатор {where} или заметка без других полей", file=sys.stderr)
        return 1
    if len(" ".join(note.split())) > NOTE_MAX:
        print(f"pantheon task set: заметка длиннее {NOTE_MAX} знаков — ничего не записано", file=sys.stderr)
        return 2
    rid = f"tn-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    try:
        os.makedirs(qdir, mode=0o700, exist_ok=True)
        _write_atomic(os.path.join(qdir, f"{rid}.req.json"), {"id": rid, "task": tid, "note": note, "created": time.time()})
    except OSError as e:
        print(f"pantheon task set: заявку заметки не записать ({e}) — ничего не записано", file=sys.stderr)
        return 3
    print(f"{tid}: заметка поставлена в очередь (окно {win}, заявка {rid}) — папку задач {where} окно не пишет, "
          "в карточку её допишет плановый проход строкой «агент (окно " + win + "): …»")
    return 0


# --- проход --------------------------------------------------------------------------------------------------------

def windows():
    """Имена окон — папки кэша окон по образцу; окно — по имени папки, не из текста заявки."""
    with contextlib.suppress(OSError):
        return [n for n in sorted(os.listdir(caches())) if WINDOW_RE.fullmatch(n)]
    return []


def open_queue(win):
    """dir_fd папки заявок окна или None. Папку держит окно и может подменить ссылкой, поэтому — как
    owner_edit.open_queue: база кэша, затем <окно> и task-note по одному компоненту с O_NOFOLLOW; дальше чтение,
    переименование и удаление — только относительно этого fd, а не по пути."""
    try:
        fd = os.open(caches(), os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return None
    for part in (win, SUB):
        try:
            nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        except OSError:
            os.close(fd)
            return None
        os.close(fd)
        fd = nfd
    return fd


def _reqs(dfd):
    with contextlib.suppress(OSError):
        return sorted(n for n in os.listdir(dfd) if n.endswith(".req.json"))
    return []


def task_note_pending():
    for win in windows():
        dfd = open_queue(win)
        if dfd is not None:
            try:
                if _reqs(dfd):
                    return True
            finally:
                os.close(dfd)
    return False


def _load(name, dfd):
    """Свой обычный файл без ссылок, не больше REQ_MAX, заявка по образцу → (dict, время заявки) или None. Время —
    min(created, mtime, ctime): created пишет окно, а сдвинуть ctime файла оно не может; created в будущем — отказ."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_size > REQ_MAX:
            return None
        raw = fh.read(REQ_MAX + 1)
    try:
        req = json.loads(raw)
    except ValueError:
        return None
    ok = isinstance(req, dict) and ID_RE.fullmatch(str(req.get("id"))) and TASK_RE.fullmatch(str(req.get("task"))) \
        and isinstance(req.get("note"), str) and req["note"].strip() \
        and isinstance(req.get("created"), (int, float)) and not isinstance(req.get("created"), bool) \
        and req["created"] <= P.now() + SKEW and name == f"{req['id']}.req.json"
    return (req, min(req["created"], st.st_mtime, st.st_ctime)) if ok else None


def _journal(rec):
    os.makedirs(P.path("logs"), exist_ok=True)
    fd = os.open(P.path("logs", "task-note.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(rec, time=P.stamp()), ensure_ascii=False) + "\n")


def _process(T, win, dfd, name):
    got = _load(name, dfd)
    if got is None:
        os.unlink(name, dir_fd=dfd)
        return _journal({"window": win, "file": name, "state": "dropped", "note": "заявка не по образцу"})
    req, born = got
    take = name[:-len(".req.json")] + ".taking"
    os.replace(name, take, src_dir_fd=dfd, dst_dir_fd=dfd)
    if req["task"] not in T.load_tasks(P.PANTHEON, T.WORK_TYPES):
        os.unlink(take, dir_fd=dfd)
        return _journal({"id": req["id"], "window": win, "task": req["task"], "state": "dropped", "note": "нет задачи"})
    try:
        T.task_set(P.PANTHEON, P.card_now(), req["task"], {}, note=task_note_clean(T.note_stamp(req["note"])[0]),
                   actor=f"агент (окно {win})")
    except ValueError as e:
        if P.now() - born <= REQ_TTL:
            os.replace(take, name, src_dir_fd=dfd, dst_dir_fd=dfd)  # карточка занята или не читается — следующий проход
            return None
        os.unlink(take, dir_fd=dfd)
        _journal({"id": req["id"], "window": win, "task": req["task"], "state": "failed", "note": str(e)[:300]})
        return P.alert_once(f"task-note-{req['id']}", "ttl", f"заметка окна {win} в {req['task']} не записана за сутки: "
                            f"{e} — заявка снята", "task-note")
    os.unlink(take, dir_fd=dfd)
    return _journal({"id": req["id"], "window": win, "task": req["task"], "state": "done"})


def task_note_run():
    """pantheon task run — проход заявок заметок (только вне окна роли и Claude Code). → код выхода."""
    if os.environ.get("PANTHEON_TMP") or "CLAUDECODE" in os.environ or "CLAUDE_CODE_ENTRYPOINT" in os.environ:
        print("pantheon task run: только плановый проход, не из окна роли или Claude Code", file=sys.stderr)
        return 2
    T, rc = P.tasks_mod(), 0
    with P.lock("task-note-run", block=False) as got:
        if not got:
            return 0
        for win in windows():
            dfd = open_queue(win)
            if dfd is None:
                continue
            try:
                for name in _reqs(dfd):
                    try:
                        _process(T, win, dfd, name)
                    except Exception as e:  # noqa: BLE001 — одна заявка не останавливает остальные
                        rc = 1
                        P.alert_once("task-note-run", type(e).__name__, f"заметки чужих окон: заявка {win}/{name} — "
                                     f"{type(e).__name__}: {e}", "task-note")
            finally:
                os.close(dfd)
    return rc
