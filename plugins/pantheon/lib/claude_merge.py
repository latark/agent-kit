"""`pantheon outside claude-sync --merge` — слияние проверенной ветки по умолчанию вне песочницы (metis-1327).

Случай: `git merge develop` в worktree окна падает EPERM в read-tree ещё до MERGE_HEAD — защищённые пути (.claude/…,
GRANT_WRITE_DENY) окну не записать. Проход серверов (claude_sync.run: папка проверена resolve_dir, d.top открыт без
ссылок, git — через проверенные gitdir и GIT_COMMON_DIR) сам делает `git merge --no-ff --no-commit
--no-overwrite-ignore -s ort -X no-renames <SHA>`, где SHA — ветка по умолчанию со слов сервера (свой bare,
claude_sync.Base), и оставляет роли конфликты. Итог: «слито без конфликтов» (код 0) или конфликтные файлы (код 1).

Отказ без слияния, если:
  - коммита базы нет в клоне (сначала `pantheon git fetch`), его сырой объект (дерево и родители) или дерево в клоне
    не равны серверу, blob защищённых путей и .gitattributes базы в клоне не совпали со своим хешем;
  - не закончен merge, rebase, cherry-pick или revert;
  - ветка со времени merge-base меняет защищённые пути (их приносит только PR в базу);
  - в дереве HEAD, базы или в индексе есть путь, защищённый для песочницы, но не буква в букву (другой регистр или
    нормализация Unicode — APFS и песочница их не различают) или во вложенной копии .claude/worktrees/*: слияние пишет
    рабочее дерево вне песочницы, такие входы прошли бы мимо снимка и сверки с базой;
  - в .gitattributes HEAD, базы или диска либо в info/attributes — merge=, filter= или diff= не из встроенных;
  - защищённые пути не приводятся к HEAD правилом claude_sync.sync; индекс или рабочее дерево отличаются от HEAD;
  - неотслеживаемый файл, который слияние создаст, не равен базе (равный убирается и, если merge не прошёл,
    возвращается своей записью — и ссылка 120000);
  - .git, commondir или gitdir-файл копии, звено пути или HEAD сменились после проверки (сверка перед каждой записью).
git — без GIT_*, глобальный конфиг /dev/null, core.hooksPath=/dev/null, rerere выключен, ident прохода свой.

Итог защищённых путей git не определяет: объекты клона, индекс и ветки пишет окно (свободный объект под чужим SHA
перекрывает pack, ref ветки окно двигает само или через commondir). Правило: при успехе под защищёнными путями ровно
база, при любом сбое — байт в байт то, что было до прохода.
  - До merge — снимок всех защищённых путей диска (свой обход без ссылок, без регистра и нормализации, и во вложенных
    копиях .claude/worktrees/*; содержимое и права в памяти, до SNAP_MAX).
  - После merge каждый путь базы сверяется по хешу и, если не равен, пишется из своего bare со сверкой хеша; новое под
    защищёнными путями, чего нет ни на базе, ни в снимке, — удаляется.
  - Сбой merge, сдвиг HEAD или ref, подмена копии, не вышло привести — откат без `git merge --abort` (он записал бы
    дерево живого HEAD — коммит окна): commondir — снова проверенный, ref ветки — на head_sha, индекс —
    `read-tree --reset head_sha` без записи файлов, MERGE_* убраны; затем все защищённые пути — к снимку своей
    записью, новое под ними (и настройки, и хуки: их до прохода не было) удаляется. Рабочее дерево git при откате не
    пишет: checkout-index записал бы вне песочницы путь из индекса окна, который сверка не узнала (регистр, вложенная
    копия). Код, который поменяло неудачное слияние, проход не трогает: его список — в итоге, вернёт роль в своей
    песочнице (git status, git checkout -- <пути>; новые неотслеживаемые — тоже в списке).
  - Обход — всегда полный: везде, в подпапках любой глубины и во вложенных копиях целиком. Предел WALK_MAX (по
    защищённым путям, не по всем файлам) — только у снимка, который держит содержимое; упёрся — отказ до первой
    записи (проверка счёта — до приведения к HEAD). Обход для удаления и сверки — без предела: содержимое он не держит.
    Папку не прочесть (OSError) — отказ громкий: «защищённые пути НЕ возвращены» и строка владельцу по шаблонам
    песочницы.
  - Вторая защита после merge: пути индекса копии (ls-files), защищённые для песочницы, которых нет ни в базе, ни в
    снимке, удаляются с диска; не вышло — откат.
  - После своей записи — `update-index -- <пути>`, чья запись индекса равна записанной (restat): иначе устаревший stat
    (другой размер) не даст роли `git merge --abort`.
"""
import errno
import os
import secrets
import stat

C = None   # claude_sync (ставит claude_sync.mm)
ATTRS = ".gitattributes"
# встроенные драйверы git: свой merge=/filter=/diff= — команда из конфига, её git запустил бы вне песочницы
BUILTIN = {"merge": {"text", "binary", "union"}, "filter": set(),
           "diff": {"ada", "bash", "bibtex", "cpp", "csharp", "css", "dts", "elixir", "fortran", "fountain", "golang",
                    "html", "java", "kotlin", "markdown", "matlab", "objc", "pascal", "perl", "php", "python", "ruby",
                    "rust", "scheme", "tex"}}
# rr-cache окно пишет само; глобального конфига нет (git_env) — ident прохода свой, иначе «empty ident name»
MERGE_CFG = ("-c", "rerere.enabled=false", "-c", "merge.verifySignatures=false",
             "-c", "user.name=pantheon-outside", "-c", "user.email=outside@localhost")
LINK = "120000"
SNAP_MAX = 64 << 20   # снимок защищённых путей в памяти — до 64 МБ


def _lines(raw):
    return [os.fsdecode(x) for x in raw.split(b"\0") if x]


def _rev(d):
    """SHA HEAD копии или None (git не ответил)."""
    r = C._run(d, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    return r.stdout.decode().strip() if r.returncode == 0 else None


# --- проверки до слияния ------------------------------------------------------------------------------------------

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


def check_attrs(d, head, theirs, base):
    """Отказ, если какой-либо .gitattributes (HEAD, базы, диска) или info/attributes назначает свой драйвер."""
    bad = []
    for rel, (mode, sha) in head.items():
        if rel.rsplit("/", 1)[-1] == ATTRS and mode in C.FILE_MODES:
            bad += bad_attrs(os.fsdecode(C._out(d, "cat-file", "blob", sha)), f"HEAD:{rel}")
    for rel, (mode, sha) in theirs.items():
        if rel.rsplit("/", 1)[-1] == ATTRS and mode in C.FILE_MODES:
            bad += bad_attrs(base.blob(sha).decode("utf-8", "replace"), f"{base.name}:{rel}")
    for rel in C.walk(d.top, lambda r: r.rsplit("/", 1)[-1] == ATTRS):
        parts = rel.split("/")
        try:
            pfd = C._open_parent(d.top, parts)
        except OSError:
            bad.append(f"{rel}: звено пути — ссылка")
            continue
        try:
            bad += bad_attrs(C._read_plain(parts[-1], pfd) or "", rel)
        except C.Refused:
            bad.append(f"{rel}: ссылка или не файл")
        finally:
            os.close(pfd)
    for gd in dict.fromkeys((d.common, d.gitdir)):
        path = os.path.join(gd, "info", "attributes")
        bad += bad_attrs(C._read_plain(path) or "", path)
    if bad:
        raise C.Refused("свой драйвер git в атрибутах — слияние запустило бы его вне песочницы: " + "; ".join(bad))


def check_objects(d, base, theirs, pats):
    """Коммит базы в клоне — тот же сырой объект, что у сервера (дерево и родители: родителями окно задало бы
    merge-base), его дерево в клоне равно дереву сервера, а blob защищённых путей и .gitattributes совпадают со своим
    хешем (cat-file хеш не сверяет: объект под чужим именем окно подложило бы)."""
    if C._run(d, "cat-file", "-t", base.tip).stdout.strip() != b"commit":
        raise C.Refused(f"в клоне нет коммита {base.tip[:12]} ({base.name}) — сначала pantheon git fetch, потом повтори")
    r = C._run(d, "cat-file", "commit", base.tip)
    if r.returncode != 0 or r.stdout != C.sm()._object(base.bare, "commit", base.tip):
        raise C.Refused(f"коммит {base.tip[:12]} в клоне не совпал с сервером (дерево или родители) — хранилище "
                        "объектов подменено (git fsck)")
    r = C._run(d, "ls-tree", "-r", "-z", "--full-tree", base.tip)   # git, сам заметивший подмену, — тоже отказ
    if r.returncode != 0 or r.stdout != base.listing():
        raise C.Refused(f"дерево {base.tip[:12]} в клоне не совпало с сервером — хранилище объектов подменено (git fsck)")
    shas = sorted({sha for rel, (mode, sha) in theirs.items() if mode in C.FILE_MODES or mode == LINK
                   if C.protected(rel, pats) or rel.rsplit("/", 1)[-1] == ATTRS})
    r = C._run(d, "cat-file", "--batch", data=b"".join(s.encode() + b"\n" for s in shas), timeout=300) if shas else None
    if r is not None and r.returncode != 0:
        raise C.Refused(f"blob базы в клоне не совпал со своим хешем (git: код {r.returncode}) — хранилище объектов "
                        "подменено (git fsck)")
    raw = r.stdout if r is not None else b""
    i = 0
    for sha in shas:
        nl = raw.find(b"\n", i)
        head = raw[i:nl].split() if nl >= 0 else []
        if len(head) != 3 or head[0].decode() != sha or head[1] != b"blob":
            raise C.Refused(f"blob {sha[:12]} в клоне не прочитан — сначала pantheon git fetch")
        size = int(head[2])
        if C._blob_hash(raw[nl + 1:nl + 1 + size], len(sha)) != sha:
            raise C.Refused(f"blob {sha[:12]} в клоне не совпал со своим хешем — хранилище объектов подменено (git fsck)")
        i = nl + 2 + size


def check_paths(d, head, theirs, pats):
    """Отказ, если в дереве HEAD, базы или в индексе есть путь, защищённый для песочницы, но не буква в букву (регистр,
    нормализация Unicode) или во вложенной копии .claude/worktrees/*: git merge записал бы его вне песочницы."""
    index = _lines(C._out(d, "ls-files", "-z", why="git ls-files"))
    bad = sorted({rel for rel in (*head, *theirs, *index) if C.odd(rel, pats)})
    if bad:
        raise C.Refused("в HEAD, базе или индексе путь, защищённый песочницей, но не буква в букву (регистр, Unicode) "
                        "или во вложенной копии .claude/worktrees/* — слияние записало бы его вне песочницы, убери "
                        "его коммитом: " + ", ".join(bad[:20]))


def check_clean(d):
    """Индекс и рабочее дерево равны HEAD (кроме защищённых путей, их привёл sync): иначе — отказ «грязный код»."""
    C.check_repo(d)
    C._run(d, "update-index", "-q", "--refresh")
    dirty = _lines(C._out(d, "diff-index", "--cached", "--name-only", "-z", "--no-renames", "HEAD"))
    dirty += _lines(C._out(d, "diff-files", "--name-only", "-z"))
    if dirty:
        raise C.Refused("в копии незакоммиченные изменения — закоммить или убери их, потом повтори: "
                        + ", ".join(sorted(set(dirty))[:20]))


def untracked_overwrites(top_fd, head, theirs):
    """Файлы на диске по путям, которые слияние создаст: равные базе байт в байт → в удаление, прочие — отказ."""
    drop, bad = [], []
    for rel, entry in sorted(theirs.items()):
        if rel in head or entry[0] == "160000":
            continue
        disk = C.disk_state(top_fd, rel, len(entry[1]))
        if disk == ("none",):
            continue
        (drop if C.same(entry, disk) else bad).append(rel)
    if bad:
        raise C.Refused("неотслеживаемые файлы, которые слияние перезапишет, отличаются от базы — убери или "
                        "закоммить: " + ", ".join(bad[:20]))
    return drop


# --- своя запись защищённых путей ---------------------------------------------------------------------------------

def write_link(top_fd, rel, target):
    """Ссылка rel → target: временная рядом и os.replace (звенья без перехода по ссылке)."""
    parts = rel.split("/")
    pfd = C._open_parent(top_fd, parts, create=True)
    tmp = f".{parts[-1][:80]}.claude-sync-{secrets.token_hex(4)}"
    try:
        os.symlink(target, tmp, dir_fd=pfd)
        try:
            os.replace(tmp, parts[-1], src_dir_fd=pfd, dst_dir_fd=pfd)
        except OSError:
            os.unlink(tmp, dir_fd=pfd)
            raise
    finally:
        os.close(pfd)


def settle(d, base, want, rels):
    """Привести rels на диске к want ({путь: (режим, sha)}, нет записи — пути быть не должно) своей записью: blob — из
    своего bare со сверкой хеша, удаление — только под skills|commands|agents → (сделано, отказы). Записанное, чья
    запись в индексе та же, — restat."""
    done, bad, wrote = [], [], {}
    for rel in rels:
        entry = want.get(rel)
        disk = C.disk_state(d.top, rel, len(base.tip))
        if C.same(entry, disk):
            continue
        try:
            if disk in (("blocked",), ("dir",)):
                bad.append(f"{rel}: на месте файла папка или ссылка в звене пути")
            elif entry and (entry[0] in C.FILE_MODES or entry[0] == LINK) and base.has(entry[1]):
                data = base.blob(entry[1])
                if entry[0] == LINK:
                    write_link(d.top, rel, os.fsdecode(data))
                else:
                    C.write_file(d.top, rel, data, C.FILE_MODES[entry[0]])
                done.append(f"{rel}: записан из своего bare ({entry[1][:12]})")
                wrote[rel] = entry
            elif disk != ("none",) and C.deletable(rel):
                C.delete_file(d.top, rel)
                done.append(f"{rel}: удалён своей записью")
            else:
                bad.append(f"{rel}: проверенной версии нет на {base.name}, а убрать его claude-sync не может")
        except OSError as e:
            bad.append(f"{rel}: не записан ({type(e).__name__}: {e.strerror or e})")
    done += restat(d, wrote)
    return done, bad


def restat(d, wrote):
    """Stat в индексе — к файлам, которые записали мы, если запись индекса (стадия 0, режим и sha) равна записанной.
    `update-index --refresh` тут не помогает: при другом размере (git записал подложенный blob) git считает файл
    изменённым без сверки содержимого, и merge --abort роли отказывает «not uptodate». Содержимое в индексе не
    меняется: на диске ровно тот blob, что уже записан в индексе. → строки итога (сбой update-index)."""
    if not wrote:
        return []
    raw = C._run(d, "ls-files", "-s", "-z", "--", *wrote).stdout
    same = []
    for item in _lines(raw):
        meta, _, rel = item.partition("\t")
        bits = meta.split()
        if len(bits) == 3 and bits[2] == "0" and tuple(bits[:2]) == tuple(wrote.get(rel, ())):
            same.append(rel)
    r = C._run(d, "update-index", "--", *same, timeout=300) if same else None
    if r is not None and r.returncode != 0:
        return [f"индекс: update-index не прошёл (код {r.returncode}) — git status покажет записанные пути "
                "изменёнными, сделай git update-index --refresh"]
    return []


# --- снимок защищённых путей и откат к нему -----------------------------------------------------------------------

def grab(top, rel):
    """Путь на диске без перехода по ссылкам: None — нет, ("file", байты, права), ("link", цель), ("other",) — папка,
    fifo и т. п., ("blocked",) — звено пути ссылка или файл."""
    parts = rel.split("/")
    try:
        pfd = C._open_parent(top, parts)
    except FileNotFoundError:
        return None
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENOTDIR):
            return ("blocked",)
        raise
    try:
        try:
            st = os.stat(parts[-1], dir_fd=pfd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(st.st_mode):
            return ("link", os.fsencode(os.readlink(parts[-1], dir_fd=pfd)))
        if not stat.S_ISREG(st.st_mode):
            return ("other",)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=pfd)
        with os.fdopen(fd, "rb") as fh:
            return ("file", fh.read(), stat.S_IMODE(st.st_mode) & 0o777)
    finally:
        os.close(pfd)


def snapshot(d, pats, drop):
    """Все защищённые пути диска (свой обход) и убираемые неотслеживаемые → {путь: grab}; больше SNAP_MAX байт, папка
    или fifo под защищённым путём — отказ до слияния."""
    snap, size = {}, 0
    for rel in sorted(set(C.walk(d.top, lambda r: C.deep(r, pats), nested=True)) | set(drop)):
        st = grab(d.top, rel)
        if st is None:
            continue
        if st[0] not in ("file", "link"):
            raise C.Refused(f"{rel}: не файл и не ссылка — снимок защищённых путей не снять, приведи руками")
        size += len(st[1])
        if size > SNAP_MAX:
            raise C.Refused(f"защищённые пути больше {SNAP_MAX >> 20} МБ — снимок для отката не снять, слияния нет")
        snap[rel] = st
    return snap


def put(top, rel, st):
    if st[0] == "link":
        write_link(top, rel, os.fsdecode(st[1]))
    else:
        C.write_file(top, rel, st[1], st[2])


def deep_walk(d, plan, bad):
    """Свой полный обход защищённых путей без предела (и во вложенных копиях); папку не прочесть — строка в bad."""
    errs = []
    found = C.walk(d.top, lambda r: C.deep(r, plan["pats"]), limit=C.NO_LIMIT, nested=True, errors=errs)
    bad += [f"обход не закончен: {x}" for x in errs]
    return found


def owner_hint(d, pats):
    """Строка владельцу из шаблонов песочницы (GRANT_WRITE_DENY) и уровней корня (ROOT_LEVELS), а не свой список."""
    kinds = sorted({"/".join(p[1:] if p[0] == "**" else p) for p in pats})
    levels = ", ".join(f"{d}{lv}" for lv in C.P.ROOT_LEVELS)
    return (f"владельцу: проверь в {levels} и глубже (и во вложенных копиях .claude/worktrees/*) пути "
            + ", ".join(kinds) + " — там может остаться чужой хук")


def to_snapshot(d, plan):
    """Защищённые пути и убранные файлы — байт в байт к снимку своей записью: нового под защищёнными путями (и
    настроек, и хуков — их до прохода не было) — удалить, бывшее — вернуть → отказы. Обход оборвался — найденное новое
    всё равно удаляется, а отказ громкий."""
    snap, bad = plan["snap"], []
    for rel in sorted(set(deep_walk(d, plan, bad)) - set(snap)):
        try:
            C.delete_file(d.top, rel)
        except OSError as e:
            bad.append(f"{rel}: не удалён ({type(e).__name__})")
    for rel, st in sorted(snap.items()):
        try:
            if grab(d.top, rel) != st:
                put(d.top, rel, st)
        except OSError as e:
            bad.append(f"{rel}: не возвращён ({type(e).__name__})")
    return bad


def repair(d):
    """Копия для git отката: commondir — снова проверенный (его пишет окно), затем check_repo → None или причина."""
    try:
        C.check_repo(d)
        return None
    except C.Refused:
        pass
    try:
        if d.gitdir != d.common:
            fix_commondir(d)
        C.check_repo(d)
        return None
    except (OSError, C.Refused) as e:
        return f"копия подменена ({e}) — ветку и индекс не трогал"


def fix_commondir(d):
    """commondir — снова путь к проверенному common: gitdir открыт звено за звеном без ссылок, переписывается только
    обычный файл (ссылку или папку — нет: check_repo откажет), временный рядом и os.replace в той же папке."""
    gfd = C.open_top(d.gitdir)
    try:
        st = os.stat("commondir", dir_fd=gfd, follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode):
            return
        tmp = f"commondir.claude-sync-{secrets.token_hex(4)}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=gfd)
        with os.fdopen(fd, "w") as fh:
            fh.write(os.path.relpath(d.common, d.gitdir) + "\n")
        os.replace(tmp, "commondir", src_dir_fd=gfd, dst_dir_fd=gfd)
    finally:
        os.close(gfd)


def git_back(d, plan):
    """Ветка — на head_sha (ref могло сдвинуть окно, merge --abort записал бы его дерево), индекс — дерево head_sha
    без записи файлов, MERGE_* — убрать. Рабочее дерево git не пишет (checkout-index записал бы путь из индекса окна,
    который сверка не узнала) → строки сбоев и список кода, который слияние оставило на диске."""
    notes, sha = [], plan["head_sha"]
    steps = ([("symbolic-ref", "HEAD", plan["branch"]), ("update-ref", "-m", "claude-sync: откат", plan["branch"], sha)]
             if plan["branch"] else [("update-ref", "--no-deref", "HEAD", sha)]) + [("read-tree", "--reset", sha)]
    for step in steps:
        r = C._run(d, *step, timeout=300)
        if r.returncode != 0:
            notes.append(f"git {step[0]} не прошёл (код {r.returncode})")
    for name in ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE", "AUTO_MERGE"):
        if os.path.lexists(os.path.join(d.gitdir, name)):
            os.unlink(os.path.join(d.gitdir, name))
    if _rev(d) != sha:
        notes.append(f"HEAD не вернулся на {sha[:12]}")
    notes += plan["notes"]
    left = left_behind(d, plan, notes)
    if left:
        notes.append(f"код, который поменяло слияние, проход не трогал ({len(left)}) — верни сам: git status, "
                     "git checkout -- <пути>, новые файлы удали: " + ", ".join(left[:20]) + (" …" if len(left) > 20 else ""))
    return notes


def untracked(d, notes):
    """Неотслеживаемые не игнорируемые файлы копии (только чтение); git не прошёл — строка в notes."""
    r = C._run(d, "ls-files", "-o", "--exclude-standard", "-z", timeout=300)
    if r.returncode != 0:
        notes.append(f"git ls-files -o не прошёл (код {r.returncode}) — список новых файлов неполный")
    return _lines(r.stdout)


def left_behind(d, plan, notes):
    """Незащищённые пути, где HEAD и база различаются (или новые неотслеживаемые), а диск уже не равен HEAD — их
    записал git merge; убранные неотслеживаемые возвращает снимок."""
    head, theirs, left = plan["head"], plan["theirs"], []
    new = set(untracked(d, notes)) - set(plan["untracked"])   # и файлы только из чужого дерева (ref сдвинут во время merge)
    for rel in sorted((set(head) | set(theirs) | new) - set(plan["drop"])):
        if (rel not in new and head.get(rel) == theirs.get(rel)) or C.deep(rel, plan["pats"]):
            continue
        try:
            if not C.same(head.get(rel), C.disk_state(d.top, rel, len(plan["head_sha"]))):
                left.append(rel)
        except OSError:
            left.append(rel)
    return left


def rollback(d, plan, why):
    """Откат без git merge --abort: копия, ветка и индекс — к head_sha (если копия не подменена), защищённые пути —
    к снимку своей записью → Refused с честной причиной."""
    why_repo = repair(d)
    notes = [why_repo] if why_repo else git_back(d, plan)
    bad = to_snapshot(d, plan)
    if not why_repo:
        C._run(d, "update-index", "-q", "--refresh", timeout=300)
    tail = (f"; защищённые пути НЕ возвращены: {'; '.join(bad)} — {owner_hint(d, plan['pats'])}" if bad else "; защищённые пути возвращены к снимку до прохода")
    raise C.Refused(f"{why} — слияние отменено" + "".join(f"; {x}" for x in notes) + tail)


# --- слияние ------------------------------------------------------------------------------------------------------

def git_merge(d, base, plan):
    """Убрать равные базе неотслеживаемые файлы и слить коммит базы; без MERGE_HEAD — откат к снимку, отказ."""
    C.check_repo(d)
    if _rev(d) != plan["head_sha"]:
        raise C.Refused("HEAD копии сдвинулся после проверки — повтори claude-sync --merge")
    for rel in plan["drop"]:
        C.delete_file(d.top, rel)
    r = C._run(d, *MERGE_CFG, "merge", "--no-ff", "--no-commit", "--no-overwrite-ignore", "--no-autostash",
               "--no-verify", "--no-edit", "--no-stat", "-s", "ort", "-X", "no-renames",
               "-m", f"Merge {base.name} {base.tip[:12]} (claude-sync --merge)", base.tip, timeout=600)
    if os.path.lexists(os.path.join(d.gitdir, "MERGE_HEAD")):
        return
    tail = os.fsdecode(r.stderr or b"").strip().splitlines()
    rollback(d, plan, "git merge ничего не слил (Already up to date), MERGE_HEAD нет" if r.returncode == 0 else
             f"git merge не прошёл (код {r.returncode}): {(tail or [''])[-1][-200:]}")


def exact(d, base, plan):
    """После своей записи: под защищёнными путями ровно база, плюс бывшее до прохода не из базы (игнорируемое) — как в
    снимке; новое — удалить → (сделано, отказы)."""
    theirs, snap, done, bad = plan["theirs"], plan["snap"], [], []
    for rel in sorted(set(deep_walk(d, plan, bad)) | set(index_deep(d, plan, bad))):
        if rel in theirs:
            continue
        try:
            if rel not in snap:
                if grab(d.top, rel) is None:
                    continue   # путь индекса, которого на диске нет
                C.delete_file(d.top, rel)
                done.append(f"{rel}: удалён — появился во время слияния, его нет ни на базе, ни до прохода")
            elif grab(d.top, rel) != snap[rel]:
                put(d.top, rel, snap[rel])
                done.append(f"{rel}: возвращён к снимку до прохода")
        except OSError as e:
            bad.append(f"{rel}: не приведён ({type(e).__name__})")
    for rel in plan["rels"]:
        if rel in theirs and not C.same(theirs[rel], C.disk_state(d.top, rel, len(base.tip))):
            bad.append(f"{rel}: не равен базе")
    return done, bad


def index_deep(d, plan, bad):
    """Вторая защита после merge: пути индекса копии, защищённые для песочницы (deep: и не буква в букву, и во
    вложенных копиях) — их сверяет exact, даже если обход их не нашёл; git не прошёл — строка в bad (откат)."""
    r = C._run(d, "ls-files", "-z", timeout=300)
    if r.returncode != 0:
        bad.append(f"git ls-files не прошёл (код {r.returncode}) — индекс после слияния не сверен")
        return []
    return [rel for rel in _lines(r.stdout) if C.deep(rel, plan["pats"])]


def after_merge(d, base, plan, out):
    """После merge: копия та же, HEAD тот же, защищённые пути — ровно база своей записью; иначе откат к снимку."""
    try:   # сначала копия: при чужом commondir git берёт ветки из него (GIT_COMMON_DIR их не покрывает) — HEAD не тот
        C.check_repo(d)
    except C.Refused as e:
        rollback(d, plan, str(e))
    if _rev(d) != plan["head_sha"]:
        rollback(d, plan, "HEAD копии сдвинулся во время слияния")
    done, bad = settle(d, base, plan["theirs"], plan["rels"])
    if bad:
        rollback(d, plan, "после слияния защищённые пути не привести к базе: " + "; ".join(bad))
    more, bad = exact(d, base, plan)
    if bad:
        rollback(d, plan, "после слияния под защищёнными путями не только база: " + "; ".join(bad))
    conflicts = sorted({p.split("\t", 1)[-1] for p in _lines(C._out(d, "ls-files", "-u", "-z"))})
    out.update(conflicts=conflicts, merged=f"{base.name} {base.tip[:12]}")
    out["synced"] += [f"{rel}: удалён (неотслеживаемый, равен {base.name})" for rel in plan["drop"]]
    out["synced"] += [f"{x} — после git merge не был равен базе" for x in done] + more
    return out


def merge(d):
    """Режим --merge → {"synced", "refused", "base", "conflicts", "merged"}; Refused — отказ (без слияния или с
    откатом к снимку)."""
    why = C.in_progress(d.gitdir)
    if why:
        raise C.Refused(why)
    pats = C.patterns()
    base = C.Base(d)
    try:
        C.check_repo(d)
        theirs = C.parse_tree(base.listing())
        check_objects(d, base, theirs, pats)
        head_sha, label = _rev(d), f"{base.name} {base.tip[:12]}"
        if not head_sha:
            raise C.Refused("у копии нет HEAD — сливать не во что")
        mb = C._out(d, "merge-base", head_sha, base.tip, why=f"merge-base HEAD и {base.name}").decode().strip()
        if mb == base.tip:
            return {"synced": [], "refused": [], "base": label, "conflicts": [], "merged": None}
        head = C.tree_entries(d, head_sha)
        check_paths(d, head, theirs, pats)
        mine = [p for p in _lines(C._out(d, "diff-tree", "-r", "--no-renames", "--name-only", "-z", mb, head_sha))
                if C.protected(p, pats)]
        if mine:
            raise C.Refused(f"ветка со времени {mb[:12]} меняет защищённые пути — их приносит только PR в базу, "
                            "слияние не даст их проверить: " + ", ".join(mine[:20]))
        check_attrs(d, head, theirs, base)
        drop = untracked_overwrites(d.top, head, theirs)
        C.walk(d.top, lambda r: C.deep(r, pats), nested=True)   # предел снимка (WALK_MAX) — до первой записи
        out = C.sync(d, base, skip=set(theirs) - set(head))
        if out["refused"]:
            raise C.Refused("защищённые пути не приведены к HEAD: " + "; ".join(out["refused"]))
        check_clean(d)
        ref = C._run(d, "symbolic-ref", "-q", "HEAD")
        plan = {"head_sha": head_sha, "head": head, "theirs": theirs, "drop": drop, "pats": pats,
                "branch": ref.stdout.decode().strip() if ref.returncode == 0 else None,
                "rels": sorted(r for r in set(theirs) | set(head) if C.protected(r, pats)),
                "snap": snapshot(d, pats, drop), "notes": []}
        plan["untracked"] = untracked(d, plan["notes"])
        git_merge(d, base, plan)
        return after_merge(d, base, plan, out)
    finally:
        base.close()
