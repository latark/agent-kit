"""`pantheon outside claude-sync [--wait С]` — защищённые пути копии к проверенной версии (metis-1327).

Окну роли песочница закрывает запись в исполняемые пути копий — .claude/skills, .claude/commands, .claude/agents,
.claude/hooks, .claude/settings*.json, .mcp.json, .husky (GRANT_WRITE_DENY в pantheon.py): их хуки Claude Code и git
исполняют вне песочницы. Поэтому `git checkout` или `git merge` в worktree окна двигает HEAD, а файлы этих путей не
переписывает (EPERM): старые версии остаются, выглядят изменёнными, и следующий checkout падает. Роль подаёт заявку
этой командой из корня своей копии; исполняет её проход серверов (`outside run --serve`, вне песочницы), как
`outside serve`: та же очередь, `status`, `--wait`, и та же проверка папки — только папки реестра окна, .git-файл
только worktree клона реестра (resolve_dir, trusted_clone в outside.py).

Правило безопасности: в защищённый путь проход пишет только содержимое, прошедшее ревью, — blob ветки по умолчанию
origin, которую назвал сам сервер. Для каждого защищённого пути (шаблоны — те же GRANT_WRITE_DENY, не копия), где
рабочее дерево отличается от HEAD:
  - запись HEAD (режим и blob) равна записи того же пути на ветке по умолчанию → файл пишется (текст blob берётся
    из своего bare, а не из .git окна);
  - пути нет ни в HEAD, ни на ветке по умолчанию → файл удаляется (с пустыми папками над ним);
  - иначе (HEAD несёт свою, не слитую версию; путь есть только в одной из двух; ссылка в HEAD; на месте файла папка
    или ссылка в звене пути) → путь не тронут, строка отказа с причиной, код 1.
Ветка по умолчанию — со слов сервера, а не refs/remotes/origin/* копии: refs окно пишет само (`git update-ref`), и
сверка с ним пропустила бы свою версию навыка. Адрес — remote.origin.url клона (его .git/config окну закрыт), только
github.com (github_url); `ls-remote --symref` и `fetch --depth=1` идут в свой bare под STATE/outside/claude-sync, каждый
объект сверяется со своим хешем (lib/supabase_migrate.py: _fetch_verified, _object, _tree_entry). Нет сети или входа
к закрытому репозиторию по https без помощника учётных данных — отказ с причиной git.

Что ещё держит команда: ничего вне защищённых путей не трогается, вложенные копии .claude/worktrees/* — тоже; звенья
пути открываются без перехода по ссылке (O_NOFOLLOW от корня копии), запись — во временный файл рядом и os.replace;
индекс git не пишется (git зовётся только ls-tree и ls-files); неотслеживаемые файлы, которые копия игнорирует
(.gitignore, например settings.local.json), не трогаются. Незаконченный merge, rebase, cherry-pick или revert в копии
— отказ «закончи или отмени …» без изменений. Итог — список приведённых путей и отказов (`outside status ID`).
"""
import errno
import fnmatch
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import stat
import tempfile
import time

P = O = None
KIND = "claude-sync"
USAGE = "pantheon outside claude-sync [--wait С]"
NESTED = ".claude/worktrees/"   # вложенные копии окна — свои репозитории, их приводит своя заявка
IN_PROGRESS = (("MERGE_HEAD", "merge", "git merge --continue или --abort"),
               ("rebase-merge", "rebase", "git rebase --continue или --abort"),
               ("rebase-apply", "rebase или am", "git rebase --abort (или git am --abort)"),
               ("CHERRY_PICK_HEAD", "cherry-pick", "git cherry-pick --continue или --abort"),
               ("REVERT_HEAD", "revert", "git revert --continue или --abort"))
HASHES = {40: hashlib.sha1, 64: hashlib.sha256}
FILE_MODES = {"100644": 0o644, "100755": 0o755}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def set_core(core, outside):
    global P, O
    P, O = core, outside


_SM = []


def sm():
    """lib/supabase_migrate.py — модуль-лист без P: свой bare, ls-remote, fetch и сверка объектов по хешу."""
    if not _SM:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "supabase_migrate.py")
        spec = importlib.util.spec_from_file_location("pantheon_claude_sync_sm", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SM.append(mod)
    return _SM[0]


class Refused(Exception):
    """Отказ всей заявке: причина — в итог."""


# --- какие пути защищены ------------------------------------------------------------------------------------------

def patterns():
    """Шаблоны песочницы (GRANT_WRITE_DENY) звеньями: «/X» — от корня копии, «/**/X» — на любой глубине."""
    return [tuple(p.strip("/").split("/")) for p in P.GRANT_WRITE_DENY]


def _match(parts, pat):
    """Путь parts лежит в шаблоне pat или под ним: «**» — любое число звеньев, «*» — внутри одного звена."""
    if not pat:
        return True
    if pat[0] == "**":
        return any(_match(parts[i:], pat[1:]) for i in range(len(parts) + 1))
    return bool(parts) and fnmatch.fnmatchcase(parts[0], pat[0]) and _match(parts[1:], pat[1:])


def protected(rel, pats=None):
    if not rel or rel.startswith(NESTED) or rel.startswith("/") or ".." in rel.split("/"):
        return False
    parts = rel.split("/")
    return any(_match(parts, p) for p in (pats if pats is not None else patterns()))


# --- копия: HEAD и диск -------------------------------------------------------------------------------------------

def in_progress(gitdir):
    """Незаконченная операция git в копии → строка отказа или None (папки и файлы — в gitdir самой worktree)."""
    for name, what, how in IN_PROGRESS:
        if os.path.lexists(os.path.join(gitdir, name)):
            return f"в копии не закончен {what} ({name}) — закончи или отмени: {how}, потом повтори claude-sync"
    return None


def head_entries(d, pats):
    """{путь: (режим, sha)} записей HEAD в защищённых путях (ls-tree, индекс не читается и не пишется)."""
    out = O.git(d, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
    if out is None:
        raise Refused("git ls-tree HEAD не прошёл — у копии нет коммита или git не читает её")
    entries = {}
    for item in out.split("\0"):
        meta, _, path = item.partition("\t")
        bits = meta.split()
        if len(bits) == 3 and bits[1] in ("blob", "commit") and protected(path, pats):
            entries[path] = (bits[0], bits[2])
    return entries


def disk_paths(d, pats):
    """Пути защищённых мест, которые git видит на диске сверх HEAD: неотслеживаемые (не игнорируемые) и из индекса."""
    found = set()
    for flag in ("--others", "--cached"):
        out = O.git(d, "ls-files", "-z", flag, "--exclude-standard")
        if out is None:
            raise Refused(f"git ls-files {flag} не прошёл")
        found.update(p for p in out.split("\0") if p and not p.endswith("/") and protected(p, pats))
    return found


def _open_parent(top_fd, parts, create=False):
    """fd папки, где лежит последнее звено parts: каждое звено открыто без перехода по ссылке. OSError ELOOP/ENOTDIR —
    звено ссылка или не папка; FileNotFoundError — папки нет (create — создать)."""
    fd = os.dup(top_fd)
    try:
        for part in parts[:-1]:
            try:
                nfd = os.open(part, DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o755, dir_fd=fd)
                nfd = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = nfd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _blob_hash(data, n):
    return HASHES.get(n, hashlib.sha1)(b"blob %d\0" % len(data) + data).hexdigest()


def disk_state(top_fd, rel, n=40):
    """Состояние пути на диске: ("none",), ("file", sha, исполняемый), ("link", sha цели), ("dir",) или ("blocked",) —
    звено пути над ним ссылка или файл. Ссылки не проходятся."""
    parts = rel.split("/")
    try:
        pfd = _open_parent(top_fd, parts)
    except FileNotFoundError:
        return ("none",)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENOTDIR):
            return ("blocked",)
        raise
    try:
        try:
            st = os.stat(parts[-1], dir_fd=pfd, follow_symlinks=False)
        except FileNotFoundError:
            return ("none",)
        if stat.S_ISLNK(st.st_mode):
            return ("link", _blob_hash(os.fsencode(os.readlink(parts[-1], dir_fd=pfd)), n))
        if not stat.S_ISREG(st.st_mode):
            return ("dir",)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=pfd)
        with os.fdopen(fd, "rb") as fh:
            data = fh.read()
        return ("file", _blob_hash(data, n), bool(st.st_mode & 0o100))
    finally:
        os.close(pfd)


def same(entry, disk):
    """Диск совпадает с записью HEAD (None — записи нет). Подмодуль (160000) не сверяется: его дерево — не наше."""
    if entry is None:
        return disk == ("none",)
    mode, sha = entry
    if mode == "160000":
        return True
    if mode == "120000":
        return disk == ("link", sha)
    return disk == ("file", sha, mode == "100755")


# --- ветка по умолчанию со слов сервера ---------------------------------------------------------------------------

def origin_url(bare, d):
    """Адрес origin для сверки: remote.origin.url клона (его .git/config окну закрыт), только github.com."""
    S = sm()
    try:
        url = S.github_url(S._config_origin(bare, d.clone))
    except S.Refused as e:
        raise Refused(str(e)) from None
    if not url:
        raise Refused(f"origin клона {d.clone} — не github.com/<владелец>/<имя>: проверенной версии взять неоткуда")
    return url


class Base:
    """Ветка по умолчанию origin в своём bare: (режим, sha) пути и текст blob — каждый объект сверен с хешем."""

    def __init__(self, d):
        S = sm()
        top = O.root("claude-sync")
        os.makedirs(top, mode=0o700, exist_ok=True)
        self.bare = tempfile.mkdtemp(prefix="bare-", dir=top)
        try:
            r = S._git(self.bare, "init", "--quiet", "--bare", "--template=")
            if r.returncode != 0:
                raise Refused(f"свой bare сверки не создан ({(r.stderr or '').strip()[-200:]})")
            branch, self.tip = S._fetch_verified(self.bare, origin_url(self.bare, d))
            self.name = "origin/" + branch
        except S.Refused as e:
            self.close()
            raise Refused(str(e)) from None
        except BaseException:
            self.close()
            raise

    def close(self):
        shutil.rmtree(self.bare, ignore_errors=True)

    def entry(self, rel):
        """(режим, sha) пути rel на ветке или None — пути нет."""
        S = sm()
        head = S._object(self.bare, "commit", self.tip).split(b"\n", 1)[0]
        if not head.startswith(b"tree "):
            raise S.Refused(f"коммит {self.tip[:12]} не разобран")
        sha, n = head[5:].decode("ascii", "replace"), len(self.tip) // 2
        parts = rel.split("/")
        for i, part in enumerate(parts):
            e = S._tree_entry(S._object(self.bare, "tree", sha), os.fsencode(part), n)
            if e is None:
                return None
            mode, sha = e
            if i < len(parts) - 1 and mode != b"40000":
                return None
        return mode.decode("ascii", "replace"), sha

    def blob(self, sha):
        return sm()._object(self.bare, "blob", sha)


# --- запись и удаление --------------------------------------------------------------------------------------------

def write_file(top_fd, rel, data, mode):
    """Файл rel = data: временный файл рядом (O_EXCL, без ссылок) и os.replace; недостающие папки создаются."""
    parts = rel.split("/")
    pfd = _open_parent(top_fd, parts, create=True)
    tmp = f".{parts[-1][:80]}.claude-sync-{secrets.token_hex(4)}"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=pfd)
        try:
            with os.fdopen(fd, "wb", closefd=False) as fh:
                fh.write(data)
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
        try:
            os.replace(tmp, parts[-1], src_dir_fd=pfd, dst_dir_fd=pfd)
        except OSError:
            os.unlink(tmp, dir_fd=pfd)
            raise
    finally:
        os.close(pfd)


def delete_file(top_fd, rel):
    """Удалить rel (файл или ссылку — саму ссылку) и опустевшие папки над ним, но не корень копии."""
    parts = rel.split("/")
    pfd = _open_parent(top_fd, parts)
    try:
        os.unlink(parts[-1], dir_fd=pfd)
    finally:
        os.close(pfd)
    for k in range(len(parts) - 1, 0, -1):
        try:
            up = _open_parent(top_fd, parts[:k])
        except OSError:
            return
        try:
            os.rmdir(parts[k - 1], dir_fd=up)
        except OSError:
            return
        finally:
            os.close(up)


# --- решение по одному пути ---------------------------------------------------------------------------------------

def decide(rel, entry, disk, base):
    """Что делать с путём, который отличается от HEAD → ("write", режим, sha) | ("delete",) | ("refuse", причина)."""
    if disk in (("blocked",), ("dir",)):
        what = "звено пути — ссылка или файл" if disk == ("blocked",) else "на месте файла — папка"
        return ("refuse", f"{what}: ссылки и папки claude-sync не трогает, приведи руками")
    if entry is not None and entry[0] not in FILE_MODES:
        return ("refuse", f"в HEAD это не обычный файл (режим {entry[0]}): ссылок claude-sync не пишет")
    theirs = base.entry(rel)
    if entry is None and theirs is None:
        return ("delete",)
    if entry is None:
        return ("refuse", f"пути нет в HEAD, а на {base.name} есть: копия отстала или удаляет его своим коммитом")
    if theirs is None:
        return ("refuse", f"в HEAD своя версия, на {base.name} пути нет — не слито ревью, сначала PR")
    if tuple(entry) != tuple(theirs):
        return ("refuse", f"в HEAD своя версия ({entry[1][:12]}), на {base.name} — {theirs[1][:12]}: не слито ревью")
    return ("write", FILE_MODES[entry[0]], entry[1])


def apply(top_fd, rel, act, base):
    if act[0] == "delete":
        delete_file(top_fd, rel)
        return f"{rel}: удалён (нет ни в HEAD, ни на {base.name})"
    data = base.blob(act[2])
    write_file(top_fd, rel, data, act[1])
    return f"{rel}: приведён к HEAD {act[2][:12]} (= {base.name})"


def sync(d):
    """Привести защищённые пути копии d (Repo) → {"synced": [...], "refused": [...], "base": ...}. Refused — отказ всей
    заявке до изменений (незаконченная операция git, нет HEAD, ветку по умолчанию не получить)."""
    why = in_progress(d.gitdir)
    if why:
        raise Refused(why)
    pats = patterns()
    entries = head_entries(d, pats)
    top_fd = os.open(str(d), DIR_FLAGS)
    try:
        n = len(next(iter(entries.values()))[1]) if entries else 40
        differ = [(rel, entries.get(rel), disk_state(top_fd, rel, n))
                  for rel in sorted(set(entries) | disk_paths(d, pats))]
        differ = [x for x in differ if not same(x[1], x[2])]
        if not differ:
            return {"synced": [], "refused": [], "base": None}
        base = Base(d)
        try:
            out = {"synced": [], "refused": [], "base": f"{base.name} {base.tip[:12]}"}
            for rel, entry, disk in differ:
                act = decide(rel, entry, disk, base)
                if act[0] == "refuse":
                    out["refused"].append(f"{rel}: {act[1]}")
                    continue
                try:
                    out["synced"].append(apply(top_fd, rel, act, base))
                except OSError as e:
                    out["refused"].append(f"{rel}: не записан ({type(e).__name__}: {e.strerror or e})")
            return out
        finally:
            base.close()
    finally:
        os.close(top_fd)


def run(rid, d, req, window, qdir):
    """Заявка claude-sync прохода серверов (handle в outside.py, папка уже проверена resolve_dir) → итог."""
    try:
        out = sync(d)
    except (Refused, sm().Refused, OSError) as e:
        why = str(e) if not isinstance(e, OSError) else f"сбой файловой системы: {type(e).__name__}: {e}"
        O.log_event(id=rid, kind=KIND, window=window, dir=d, ok=False, why=why)
        return O.save_result(qdir, rid, {"state": "failed", "kind": KIND, "dir": d, "why": why})
    lines = out["synced"] + [f"отказ — {x}" for x in out["refused"]]
    note = "\n".join(lines) if lines else "защищённые пути копии совпадают с HEAD — приводить нечего"
    code = 1 if out["refused"] else 0
    O.log_event(id=rid, kind=KIND, window=window, dir=d, ok=not code, synced=len(out["synced"]),
                refused=len(out["refused"]))
    return O.save_result(qdir, rid, {"state": "done", "kind": KIND, "dir": d, "code": code, "base": out["base"],
                                     "synced": out["synced"], "refused": out["refused"], "note": note})


def cmd_claude_sync(args):
    """Заявка из корня копии (окно роли или терминал владельца) → код: 0 — приведено, 1 — отказ, 75 — итога нет."""
    f = O._flags(args, {"--wait"})
    if f is None:
        O.err(f"pantheon outside: {USAGE}")
        return 2
    try:
        wait = max(0, min(int(f.get("--wait", 0)), O.WAIT_MAX))
    except ValueError:
        O.err("pantheon outside: --wait — целое число секунд")
        return 2
    d = O.toplevel(os.getcwd())
    if not d:
        O.err("pantheon outside: папка не репозиторий git — запускай из корня своей копии")
        return 2
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    req = {"v": 1, "id": rid, "kind": KIND, "dir": d, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "by": " ".join((os.environ.get("PANTHEON_SESSION") or os.environ.get("PANTHEON_ROLE") or "").split())[:40]}
    q = O.own_qdir()
    try:
        dfd = O._open_dir(q, create=True)
        if dfd is None:
            raise OSError(f"{q} — не папка")
        try:
            O._write_in(dfd, rid + ".req.json", json.dumps(req, ensure_ascii=False))
            O._write_in(dfd, rid + ".result.json", json.dumps(
                {"id": rid, "state": "queued", "kind": KIND, "src": d, "updated": P.stamp()},
                ensure_ascii=False, indent=1))
        finally:
            os.close(dfd)
    except OSError as e:
        O.err(O.cant_write("заявку не записать", e))
        return 1
    print(f"заявка {rid}: claude-sync в {d} — её исполнит проход серверов (раз в минуту)")
    if not wait:
        print(f"итог: pantheon outside status {rid}")
        return 0
    return O.wait_result(q, rid, wait)
