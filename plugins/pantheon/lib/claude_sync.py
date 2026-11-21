"""`pantheon outside claude-sync [--merge] [--wait С]` — защищённые пути копии к проверенной версии (metis-1327).

Окну роли песочница закрывает запись в исполняемые пути копий — .claude/skills, .claude/commands, .claude/agents,
.claude/hooks, .claude/settings*.json, .mcp.json, .husky (GRANT_WRITE_DENY в pantheon.py): их хуки Claude Code и git
исполняют вне песочницы. Поэтому `git checkout` в worktree окна двигает HEAD, а файлы этих путей не переписывает
(EPERM), а `git merge` падает в read-tree ещё до MERGE_HEAD. Роль подаёт заявку этой командой из корня своей копии;
исполняет её проход серверов (`outside run --serve`, вне песочницы), как `outside serve`: та же очередь, `status`,
`--wait`, и та же проверка папки — только папки реестра окна, .git-файл только worktree клона реестра (resolve_dir).

Правило безопасности: в защищённый путь проход пишет только содержимое, прошедшее ревью, — blob ветки по умолчанию
origin, которую назвал сам сервер (не refs/remotes/origin/* копии: refs окно пишет само). Адрес — remote.origin.url
клона (его .git/config окну закрыт), только github.com; `ls-remote --symref` и `fetch --depth=1` идут в свой bare под
STATE/outside/claude-sync, объекты сверены с хешем (lib/supabase_migrate.py). Нет сети или входа — отказ с причиной.

Без --merge. Кандидаты — файлы и ссылки на диске под защищёнными путями (свой обход от корня, звенья O_NOFOLLOW, .git и
вложенные копии .claude/worktrees/* не обходятся) и записи HEAD там же (ls-tree коммита). Индекс и .gitignore копии
списка не дают: их окно правит само. Для каждого пути, где диск отличается от HEAD:
  - запись HEAD (режим и blob) равна записи на ветке по умолчанию → файл пишется (текст blob — из своего bare);
  - пути нет ни в HEAD, ни на ветке по умолчанию → удаляется, но только под .claude/skills, .claude/commands и
    .claude/agents (пропажа там снимает возможность, а не защиту) и только не игнорируемый (`git check-ignore`: правка
    .gitignore окном может лишь уберечь файл); settings*.json, .mcp.json, .claude/hooks, .husky — отказ;
  - иначе (своя версия в HEAD, путь только в одной из двух, ссылка в HEAD, папка или ссылка в звене) → отказ, код 1.
Запись — во временный файл рядом и os.replace; индекс git не пишется. Незаконченный merge, rebase, cherry-pick или
revert — отказ «закончи или отмени …» без изменений.

С --merge проход сам делает в копии `git merge --no-ff --no-commit -s ort -X no-renames <SHA ветки по умолчанию со слов
сервера>` и оставляет роли конфликты. До слияния — отказ без изменений, если: коммита нет в клоне (сначала fetch) или
его дерево в клоне не совпало с сервером, а blob защищённых путей и .gitattributes — со своим хешем; незаконченная
операция git; ветка со времени merge-base меняет защищённые пути; в .gitattributes (HEAD, базы, диска) или
info/attributes есть merge=, filter= или diff= не из встроенных; защищённые пути не приводятся правилом выше; индекс
или рабочее дерево отличаются от HEAD; неотслеживаемый файл, который слияние перезапишет, не равен базе байт в байт
(равный удаляется). git — без GIT_*, глобальный конфиг /dev/null, core.hooksPath=/dev/null, rerere выключен. После —
сверка: защищённые пути на диске равны базе, иначе `git merge --abort` и отказ. Итог: «слито без конфликтов» (код 0)
или список конфликтных файлов (код 1, MERGE_HEAD на месте).
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
import subprocess
import tempfile
import time

P = O = None
KIND = "claude-sync"
USAGE = "pantheon outside claude-sync [--merge] [--wait С]"
NESTED = ".claude/worktrees/"   # вложенные копии окна — свои репозитории, их приводит своя заявка
IN_PROGRESS = (("MERGE_HEAD", "merge", "git merge --continue или --abort"),
               ("rebase-merge", "rebase", "git rebase --continue или --abort"),
               ("rebase-apply", "rebase или am", "git rebase --abort (или git am --abort)"),
               ("CHERRY_PICK_HEAD", "cherry-pick", "git cherry-pick --continue или --abort"),
               ("REVERT_HEAD", "revert", "git revert --continue или --abort"))
HASHES = {40: hashlib.sha1, 64: hashlib.sha256}
FILE_MODES = {"100644": 0o644, "100755": 0o755}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
SOFT = ("skills", "commands", "agents")   # удаление — только здесь: пропажа файла снимает возможность, не защиту
WALK_MAX = 300000
ATTRS = ".gitattributes"
# встроенные драйверы git: свой merge=/filter=/diff= — команда из конфига, её git запустил бы вне песочницы
BUILTIN = {"merge": {"text", "binary", "union"}, "filter": set(),
           "diff": {"ada", "bash", "bibtex", "cpp", "csharp", "css", "dts", "elixir", "fortran", "fountain", "golang",
                    "html", "java", "kotlin", "markdown", "matlab", "objc", "pascal", "perl", "php", "python", "ruby",
                    "rust", "scheme", "tex"}}
MERGE_CFG = ("-c", "rerere.enabled=false", "-c", "merge.verifySignatures=false")   # rr-cache окно пишет само


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


def _run(d, *args, data=None, timeout=60):
    """git в копии d (Repo — через проверенный gitdir): GIT_SAFE (хуки /dev/null), окружение git_env (без GIT_*,
    глобальный и системный конфиг выключены) → CompletedProcess с байтами. Refused — git не запустился."""
    loc = ["-C", d] + ([f"--git-dir={d.gitdir}", f"--work-tree={d}"] if isinstance(d, O.Repo) else [])
    try:
        return subprocess.run(["git", *loc, *O.GIT_SAFE, *args], input=data, capture_output=True, timeout=timeout,
                              env=O.git_env())
    except (OSError, subprocess.SubprocessError) as e:
        raise Refused(f"git {args[-1] if args else ''} не запустился ({type(e).__name__})") from None


def _out(d, *args, why=None, **kw):
    r = _run(d, *args, **kw)
    if r.returncode != 0:
        tail = os.fsdecode(r.stderr or b"").strip()[-200:]
        raise Refused(f"{why or 'git ' + ' '.join(args[:2])} не прошёл ({tail or 'код ' + str(r.returncode)})")
    return r.stdout


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


def _soft(pat):
    return len(pat) >= 2 and pat[-2] == ".claude" and pat[-1] in SOFT


def deletable(rel, pats=None):
    """Удалять можно только под .claude/skills|commands|agents и не под другим шаблоном (настройки, хуки, .husky)."""
    parts, pats = rel.split("/"), pats if pats is not None else patterns()
    return (any(_match(parts, p) for p in pats if _soft(p)) and
            not any(_match(parts, p) for p in pats if not _soft(p)))


# --- копия: HEAD и диск -------------------------------------------------------------------------------------------

def in_progress(gitdir):
    """Незаконченная операция git в копии → строка отказа или None (папки и файлы — в gitdir самой worktree)."""
    for name, what, how in IN_PROGRESS:
        if os.path.lexists(os.path.join(gitdir, name)):
            return f"в копии не закончен {what} ({name}) — закончи или отмени: {how}, потом повтори claude-sync"
    return None


def parse_tree(raw):
    """Вывод ls-tree -r -z → {путь: (режим, sha)} (blob, ссылки и подмодули)."""
    entries = {}
    for item in raw.split(b"\0"):
        meta, _, path = item.partition(b"\t")
        bits = meta.split()
        if len(bits) == 3 and bits[1] in (b"blob", b"commit"):
            entries[os.fsdecode(path)] = (bits[0].decode(), bits[2].decode())
    return entries


def tree_entries(d, rev="HEAD"):
    """Все записи коммита rev копии (ls-tree дерева коммита: индекс не читается и не пишется)."""
    return parse_tree(_out(d, "ls-tree", "-r", "-z", "--full-tree", rev, why=f"git ls-tree {rev}"))


def head_entries(d, pats):
    return {k: v for k, v in tree_entries(d).items() if protected(k, pats)}


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


def walk(top_fd, keep, limit=WALK_MAX):
    """Файлы и ссылки на диске копии, где keep(rel): свой обход от корня — звенья открыты O_NOFOLLOW, по ссылкам не
    идёт, .git и вложенные копии .claude/worktrees/* не обходит. Refused — записей больше limit."""
    found, todo, seen = [], [""], 0
    while todo:
        pre = todo.pop()
        try:
            fd = _open_parent(top_fd, (pre + "x").split("/")) if pre else os.dup(top_fd)
        except OSError:
            continue   # звено сменилось на ссылку или пропало по ходу обхода — не идём
        try:
            with os.scandir(fd) as it:
                items = [(e.name, e.is_dir(follow_symlinks=False)) for e in it]
        finally:
            os.close(fd)
        seen += len(items)
        if seen > limit:
            raise Refused(f"в копии больше {limit} файлов — обход защищённых путей не уложился, приведи руками")
        for name, is_dir in items:
            rel = pre + name
            if not is_dir:
                if keep(rel):
                    found.append(rel)
            elif name != ".git" and rel + "/" != NESTED:
                todo.append(rel + "/")
    return sorted(found)


def ignored(d, rels):
    """Какие из rels копия игнорирует (check-ignore: .gitignore и индекс окна — но так они лишь берегут файл)."""
    if not rels:
        return set()
    r = _run(d, "check-ignore", "-z", "--stdin", data=b"".join(os.fsencode(x) + b"\0" for x in rels))
    if r.returncode not in (0, 1):
        raise Refused(f"git check-ignore не прошёл ({os.fsdecode(r.stderr or b'').strip()[-200:]})")
    return {os.fsdecode(x) for x in r.stdout.split(b"\0") if x}


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

    def listing(self):
        """Сырой ls-tree -r -z всей ветки из своего bare (объекты пришли fetch, index-pack сверил их хеши)."""
        r = sm()._git(self.bare, "ls-tree", "-r", "-z", "--full-tree", self.tip, text=False)
        if r.returncode != 0:
            raise Refused(f"дерево {self.name} в своём bare не прочитано")
        return r.stdout


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
        if deletable(rel):
            return ("delete",)
        return ("refuse", f"нет ни в HEAD, ни на {base.name}: claude-sync удаляет только в .claude/skills, commands и "
                          "agents, а настройки, .mcp.json, хуки и .husky — нет (убрать — владельцу или в .gitignore)")
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


def sync(d, base=None, skip=()):
    """Привести защищённые пути копии d (Repo) → {"synced": [...], "refused": [...], "base": ...}. Refused — отказ всей
    заявке до изменений (незаконченная операция git, нет HEAD, ветку по умолчанию не получить). base — уже взятая
    (режим --merge), её закрывает вызвавший; skip — пути, которые решает слияние (неотслеживаемые, равные базе)."""
    why = in_progress(d.gitdir)
    if why:
        raise Refused(why)
    pats = patterns()
    entries = head_entries(d, pats)
    top_fd = os.open(str(d), DIR_FLAGS)
    try:
        n = len(next(iter(entries.values()))[1]) if entries else 40
        extra = [rel for rel in walk(top_fd, lambda rel: protected(rel, pats)) if rel not in entries]
        cand = sorted((set(entries) | (set(extra) - ignored(d, extra))) - set(skip))
        differ = [(rel, entries.get(rel), disk_state(top_fd, rel, n)) for rel in cand]
        differ = [x for x in differ if not same(x[1], x[2])]
        if not differ:
            return {"synced": [], "refused": [], "base": None}
        own = base is None
        base = Base(d) if own else base
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
            if own:
                base.close()
    finally:
        os.close(top_fd)


# --- --merge: слияние проверенной ветки по умолчанию --------------------------------------------------------------

def bad_attrs(text, where):
    """Строки merge=/filter=/diff= со своим драйвером в тексте .gitattributes → ["где: ключ=значение"]."""
    bad = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        for tok in s.split()[1:]:
            key, eq, val = tok.partition("=")
            if eq and key in BUILTIN and val not in BUILTIN[key]:
                bad.append(f"{where}: {key}={val}")
    return bad


def _read_plain(path):
    """Текст обычного файла без перехода по ссылке; None — файла нет. Ссылка или не файл — Refused."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as e:
        raise Refused(f"{path} не прочитан ({type(e).__name__}) — ссылка вместо файла атрибутов") from None
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise Refused(f"{path} — не обычный файл")
        return fh.read().decode("utf-8", "replace")


def check_attrs(d, top_fd, head, theirs, base):
    """Отказ, если какой-либо .gitattributes (HEAD, базы, диска) или info/attributes назначает свой драйвер."""
    bad = []
    for rel, (mode, sha) in head.items():
        if rel.rsplit("/", 1)[-1] == ATTRS and mode in FILE_MODES:
            bad += bad_attrs(os.fsdecode(_out(d, "cat-file", "blob", sha)), f"HEAD:{rel}")
    for rel, (mode, sha) in theirs.items():
        if rel.rsplit("/", 1)[-1] == ATTRS and mode in FILE_MODES:
            bad += bad_attrs(base.blob(sha).decode("utf-8", "replace"), f"{base.name}:{rel}")
    for rel in walk(top_fd, lambda r: r.rsplit("/", 1)[-1] == ATTRS):
        parts = rel.split("/")
        pfd = _open_parent(top_fd, parts)
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=pfd)
        except OSError:
            bad.append(f"{rel}: ссылка или не файл")
            continue
        finally:
            os.close(pfd)
        with os.fdopen(fd, "rb") as fh:
            bad += bad_attrs(fh.read().decode("utf-8", "replace"), rel)
    for gd in dict.fromkeys((d.common, d.gitdir)):
        text = _read_plain(os.path.join(gd, "info", "attributes"))
        bad += bad_attrs(text or "", os.path.join(gd, "info", "attributes"))
    if bad:
        raise Refused("свой драйвер git в атрибутах — слияние запустило бы его вне песочницы: " + "; ".join(bad))


def check_objects(d, base, theirs, pats):
    """Коммит базы есть в клоне, его дерево в клоне равно дереву сервера, а blob защищённых путей и .gitattributes в
    хранилище клона совпадают со своим хешем (cat-file хеш не сверяет: объект под чужим именем окно подложило бы)."""
    if _run(d, "cat-file", "-e", base.tip + "^{commit}").returncode != 0:
        raise Refused(f"в клоне нет коммита {base.tip[:12]} ({base.name}) — сначала pantheon git fetch, потом повтори")
    if _out(d, "ls-tree", "-r", "-z", "--full-tree", base.tip) != base.listing():
        raise Refused(f"дерево {base.tip[:12]} в клоне не совпало с сервером — хранилище объектов подменено (git fsck)")
    shas = sorted({sha for rel, (mode, sha) in theirs.items() if mode in FILE_MODES or mode == "120000"
                   if protected(rel, pats) or rel.rsplit("/", 1)[-1] == ATTRS})
    raw = _out(d, "cat-file", "--batch", data=b"".join(s.encode() + b"\n" for s in shas), timeout=300) if shas else b""
    i = 0
    for sha in shas:
        nl = raw.find(b"\n", i)
        head = raw[i:nl].split() if nl >= 0 else []
        if len(head) != 3 or head[0].decode() != sha or head[1] != b"blob":
            raise Refused(f"blob {sha[:12]} в клоне не прочитан — сначала pantheon git fetch")
        size = int(head[2])
        body = raw[nl + 1:nl + 1 + size]
        if _blob_hash(body, len(sha)) != sha:
            raise Refused(f"blob {sha[:12]} в клоне не совпал со своим хешем — хранилище объектов подменено (git fsck)")
        i = nl + 2 + size


def _lines(raw):
    return [os.fsdecode(x) for x in raw.split(b"\0") if x]


def check_clean(d):
    """Индекс и рабочее дерево равны HEAD (кроме защищённых путей, их привёл sync): иначе — отказ «грязный код»."""
    _run(d, "update-index", "-q", "--refresh")
    dirty = _lines(_out(d, "diff-index", "--cached", "--name-only", "-z", "--no-renames", "HEAD"))
    dirty += _lines(_out(d, "diff-files", "--name-only", "-z"))
    if dirty:
        raise Refused("в копии незакоммиченные изменения — закоммить или убери их, потом повтори: "
                      + ", ".join(sorted(set(dirty))[:20]))


def untracked_overwrites(top_fd, head, theirs):
    """Файлы на диске по путям, которые слияние создаст: равные базе байт в байт → в удаление, прочие — отказ."""
    drop, bad = [], []
    for rel, entry in sorted(theirs.items()):
        if rel in head or entry[0] == "160000":
            continue
        disk = disk_state(top_fd, rel, len(entry[1]))
        if disk == ("none",):
            continue
        (drop if same(entry, disk) else bad).append(rel)
    if bad:
        raise Refused("неотслеживаемые файлы, которые слияние перезапишет, отличаются от базы — убери или закоммить: "
                      + ", ".join(bad[:20]))
    return drop


def git_merge(d, base, top_fd, drop):
    """Убрать равные базе неотслеживаемые файлы и слить коммит базы; сбой без MERGE_HEAD — вернуть убранные."""
    for rel in drop:
        delete_file(top_fd, rel)
    r = _run(d, *MERGE_CFG, "merge", "--no-ff", "--no-commit", "--no-overwrite-ignore", "--no-autostash",
             "--no-verify", "--no-edit", "--no-stat", "-s", "ort", "-X", "no-renames",
             "-m", f"Merge {base.name} {base.tip[:12]} (claude-sync --merge)", base.tip, timeout=600)
    if os.path.lexists(os.path.join(d.gitdir, "MERGE_HEAD")):
        return
    for rel in drop:
        e = base.entry(rel)
        if e and e[0] in FILE_MODES:
            write_file(top_fd, rel, base.blob(e[1]), FILE_MODES[e[0]])
    tail = os.fsdecode(r.stderr or b"").strip().splitlines()
    raise Refused(f"git merge не прошёл (код {r.returncode}): {(tail or [''])[-1][-200:]}")


def merge(d):
    """Режим --merge → {"synced", "refused", "base", "conflicts", "merged"}; Refused — отказ без слияния."""
    why = in_progress(d.gitdir)
    if why:
        raise Refused(why)
    pats = patterns()
    base = Base(d)
    top_fd = os.open(str(d), DIR_FLAGS)
    try:
        theirs = parse_tree(base.listing())
        check_objects(d, base, theirs, pats)
        mb = _out(d, "merge-base", "HEAD", base.tip, why=f"merge-base HEAD и {base.name}").decode().strip()
        label = f"{base.name} {base.tip[:12]}"
        if mb == base.tip:
            return {"synced": [], "refused": [], "base": label, "conflicts": [], "merged": None}
        mine = [p for p in _lines(_out(d, "diff-tree", "-r", "--no-renames", "--name-only", "-z", mb, "HEAD"))
                if protected(p, pats)]
        if mine:
            raise Refused(f"ветка со времени {mb[:12]} меняет защищённые пути — их приносит только PR в базу, "
                          "слияние не даст их проверить: " + ", ".join(mine[:20]))
        head = tree_entries(d)
        check_attrs(d, top_fd, head, theirs, base)
        drop = untracked_overwrites(top_fd, head, theirs)
        out = sync(d, base, skip=set(theirs) - set(head))
        if out["refused"]:
            raise Refused("защищённые пути не приведены к HEAD: " + "; ".join(out["refused"]))
        check_clean(d)
        git_merge(d, base, top_fd, drop)
        conflicts = sorted({p.split("\t", 1)[-1] for p in _lines(_out(d, "ls-files", "-u", "-z"))})
        wrong = [rel for rel in sorted(set(theirs) | set(head)) if protected(rel, pats)
                 and not same(theirs.get(rel), disk_state(top_fd, rel, len(base.tip)))]
        if wrong:
            _run(d, "merge", "--abort")
            raise Refused("после слияния защищённые пути не равны базе — слияние отменено (git merge --abort): "
                          + ", ".join(wrong[:20]))
        out.update(conflicts=conflicts, merged=label)
        out["synced"] += [f"{rel}: удалён (неотслеживаемый, равен {base.name})" for rel in drop]
        return out
    finally:
        os.close(top_fd)
        base.close()


def _note(out, merging):
    lines = out["synced"] + [f"отказ — {x}" for x in out["refused"]]
    if merging and out.get("merged") is None:
        lines.append(f"{out['base']} уже в HEAD — сливать нечего")
    elif merging and out["conflicts"]:
        lines.append(f"слито {out['merged']} с конфликтами — разреши и закоммить: " + ", ".join(out["conflicts"]))
    elif merging:
        lines.append(f"слито без конфликтов: {out['merged']} (MERGE_HEAD) — проверь и закоммить")
    return "\n".join(lines) if lines else "защищённые пути копии совпадают с HEAD — приводить нечего"


def run(rid, d, req, window, qdir):
    """Заявка claude-sync прохода серверов (handle в outside.py, папка уже проверена resolve_dir) → итог."""
    merging = req.get("merge") is True
    try:
        out = merge(d) if merging else sync(d)
    except (Refused, sm().Refused, OSError) as e:
        why = str(e) if not isinstance(e, OSError) else f"сбой файловой системы: {type(e).__name__}: {e}"
        O.log_event(id=rid, kind=KIND, window=window, dir=d, ok=False, why=why, merge=merging)
        return O.save_result(qdir, rid, {"state": "failed", "kind": KIND, "dir": d, "why": why})
    code = 1 if out["refused"] or out.get("conflicts") else 0
    O.log_event(id=rid, kind=KIND, window=window, dir=d, ok=not code, synced=len(out["synced"]),
                refused=len(out["refused"]), merge=merging)
    res = {"state": "done", "kind": KIND, "dir": d, "code": code, "base": out["base"], "synced": out["synced"],
           "refused": out["refused"], "note": _note(out, merging)}
    if merging:
        res.update(merged=out.get("merged"), conflicts=out.get("conflicts", []))
    return O.save_result(qdir, rid, res)


def cmd_claude_sync(args):
    """Заявка из корня копии (окно роли или терминал владельца) → код: 0 — приведено, 1 — отказ, 75 — итога нет."""
    f = O._flags(args, {"--wait"}, bools=("--merge",))
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
    if f.get("--merge"):
        req["merge"] = True
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
    what = "claude-sync --merge" if req.get("merge") else "claude-sync"
    print(f"заявка {rid}: {what} в {d} — её исполнит проход серверов (раз в минуту)")
    if not wait:
        print(f"итог: pantheon outside status {rid}")
        return 0
    return O.wait_result(q, rid, wait)
