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
  - в .gitattributes HEAD, базы или диска либо в info/attributes — merge=, filter= или diff= не из встроенных;
  - защищённые пути не приводятся к HEAD правилом claude_sync.sync; индекс или рабочее дерево отличаются от HEAD;
  - неотслеживаемый файл, который слияние создаст, не равен базе (равный убирается и, если merge не прошёл,
    возвращается своей записью — и ссылка 120000);
  - .git, commondir или gitdir-файл копии, звено пути или HEAD сменились после проверки (сверка перед каждой записью).
git — без GIT_*, глобальный конфиг /dev/null, core.hooksPath=/dev/null, rerere выключен, ident прохода свой.

Итог защищённых путей git не определяет: объекты клона и индекс пишет окно (свободный объект под чужим SHA перекрывает
pack). После слияния каждый защищённый путь сверяется по хешу содержимого диска и, если не равен базе, пишется из
своего bare со сверкой хеша (на базе пути нет — удаляется под .claude/skills|commands|agents). Не вышло, HEAD
сдвинулся во время слияния или копия подменена — откат: `git merge --abort` (его код — в причине), затем защищённые
пути снова своей записью: версия HEAD, если её blob есть в своём bare, иначе удаление по тем же правилам, иначе путь —
в отказе.
"""
import os
import secrets

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
    if C._out(d, "ls-tree", "-r", "-z", "--full-tree", base.tip) != base.listing():
        raise C.Refused(f"дерево {base.tip[:12]} в клоне не совпало с сервером — хранилище объектов подменено (git fsck)")
    shas = sorted({sha for rel, (mode, sha) in theirs.items() if mode in C.FILE_MODES or mode == LINK
                   if C.protected(rel, pats) or rel.rsplit("/", 1)[-1] == ATTRS})
    raw = C._out(d, "cat-file", "--batch", data=b"".join(s.encode() + b"\n" for s in shas), timeout=300) if shas else b""
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
    своего bare со сверкой хеша, удаление — только под skills|commands|agents → (сделано, отказы)."""
    done, bad = [], []
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
            elif disk != ("none",) and C.deletable(rel):
                C.delete_file(d.top, rel)
                done.append(f"{rel}: удалён своей записью")
            else:
                bad.append(f"{rel}: проверенной версии нет на {base.name}, а убрать его claude-sync не может")
        except OSError as e:
            bad.append(f"{rel}: не записан ({type(e).__name__}: {e.strerror or e})")
    return done, bad


def abort(d, base, head, rels, why):
    """Откат: git merge --abort (его итог — в причине), затем защищённые пути к HEAD своей записью → Refused."""
    r = C._run(d, "merge", "--abort", timeout=300)
    note = "" if r.returncode == 0 else (f"; git merge --abort не прошёл (код {r.returncode}: "
                                         f"{os.fsdecode(r.stderr or b'').strip()[-200:]})")
    _, bad = settle(d, base, head, rels)
    tail = ("; защищённые пути не возвращены: " + "; ".join(bad)) if bad else \
        "; защищённые пути возвращены к HEAD своей записью"
    raise C.Refused(f"{why} — слияние отменено{note}{tail}")


# --- слияние ------------------------------------------------------------------------------------------------------

def git_merge(d, base, plan):
    """Убрать равные базе неотслеживаемые файлы и слить коммит базы; без MERGE_HEAD — своей записью вернуть
    защищённые пути к HEAD и убранные файлы, отказ с причиной."""
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
    bad = settle(d, base, plan["head"], plan["rels"])[1]
    bad += settle(d, base, {rel: plan["theirs"][rel] for rel in plan["drop"]}, plan["drop"])[1]
    tail = os.fsdecode(r.stderr or b"").strip().splitlines()
    why = ("git merge ничего не слил (Already up to date), MERGE_HEAD нет" if r.returncode == 0 else
           f"git merge не прошёл (код {r.returncode}): {(tail or [''])[-1][-200:]}")
    raise C.Refused(why + ("; не возвращены: " + "; ".join(bad) if bad else ""))


def after_merge(d, base, plan, out):
    """После merge: HEAD тот же, копия та же, защищённые пути — своей записью из своего bare; иначе откат."""
    head, rels = plan["head"], plan["rels"]
    if _rev(d) != plan["head_sha"]:
        abort(d, base, head, rels, "HEAD копии сдвинулся во время слияния")
    try:
        C.check_repo(d)
    except C.Refused as e:
        abort(d, base, head, rels, str(e))
    done, bad = settle(d, base, plan["theirs"], rels)
    if bad:
        abort(d, base, head, rels, "после слияния защищённые пути не привести к базе: " + "; ".join(bad))
    conflicts = sorted({p.split("\t", 1)[-1] for p in _lines(C._out(d, "ls-files", "-u", "-z"))})
    out.update(conflicts=conflicts, merged=f"{base.name} {base.tip[:12]}")
    out["synced"] += [f"{rel}: удалён (неотслеживаемый, равен {base.name})" for rel in plan["drop"]]
    out["synced"] += [f"{x} — после git merge не был равен базе" for x in done]
    return out


def merge(d):
    """Режим --merge → {"synced", "refused", "base", "conflicts", "merged"}; Refused — отказ (без слияния или с
    откатом)."""
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
        mine = [p for p in _lines(C._out(d, "diff-tree", "-r", "--no-renames", "--name-only", "-z", mb, head_sha))
                if C.protected(p, pats)]
        if mine:
            raise C.Refused(f"ветка со времени {mb[:12]} меняет защищённые пути — их приносит только PR в базу, "
                            "слияние не даст их проверить: " + ", ".join(mine[:20]))
        head = C.tree_entries(d, head_sha)
        check_attrs(d, head, theirs, base)
        drop = untracked_overwrites(d.top, head, theirs)
        out = C.sync(d, base, skip=set(theirs) - set(head))
        if out["refused"]:
            raise C.Refused("защищённые пути не приведены к HEAD: " + "; ".join(out["refused"]))
        check_clean(d)
        plan = {"head_sha": head_sha, "head": head, "theirs": theirs, "drop": drop,
                "rels": sorted(r for r in set(theirs) | set(head) if C.protected(r, pats))}
        git_merge(d, base, plan)
        return after_merge(d, base, plan, out)
    finally:
        base.close()
