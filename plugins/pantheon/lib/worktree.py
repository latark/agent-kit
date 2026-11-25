"""Пантеон: worktree окна направления (metis-1225, вариант Б владельца 15.11).

`pantheon worktree add <имя> [--branch B | --detach] [--base REF]`, `pantheon worktree remove <имя> [--force]`,
`pantheon worktree list`.
Claude Code (2.1.325) в песочнице закрывает запись в .git/worktrees, кроме worktree своей сессии, а EnterWorktree
с name окнам направлений закрыт (guard worktree-own) — `git worktree add|remove` из Bash окна падает EPERM на полпути.
Копию заводит эта команда, а коммитить в ней окно может после EnterWorktree с path (вариант А владельца 15.11): запись в
.git/worktrees/<id> Claude Code пускает только worktree своей сессии. Мимо
песочницы окна идут только add и remove этой команды (WORKTREE_OUT в pantheon.py), поэтому всё, что они могут,
ограничивает сама команда, а форму строки — guard (правило worktree-cmd, одна команда в строке):

- репозиторий — только тот, где стоит Bash (основная копия или его worktree; cwd — внутри основной копии), и в окне
  направления (PANTHEON_WINDOW из domains.json) — только папка своего направления: самая глубокая папка направлений
  над репозиторием — его;
- путь — строго `<репозиторий>/.claude/worktrees/<имя>`; имя, ветка и база — по белому шаблону WT_NAME (буквы,
  цифры, `. _ -` и `/` между частями, без `..` и ведущего `-`); `.claude`, `.claude/worktrees` и звенья имени — не
  ссылки, настоящий путь родителя — внутри `.claude/worktrees` настоящего репозитория;
- аргументов git насквозь нет: git зовётся с фиксированным PATH, без GIT_* окна, с core.hooksPath=/dev/null и
  core.fsmonitor=false (хук post-checkout из папки окна, например .husky, мимо песочницы не исполнится);
- add --detach — копия без ветки (как `git worktree add --detach`): временная копия для прогона на слиянии не
  оставляет ветку, и повтор с тем же именем после remove проходит;
- remove — только зарегистрированная worktree под `.claude/worktrees/`, без --force: грязную git не уберёт. --force —
  только у копии, которую создала сама эта команда с --detach (метка DETACH_MARK в gitdir копии — туда окну из
  песочницы не записать), и не во время rebase, merge, bisect (rebase-merge, rebase-apply, MERGE_HEAD, BISECT_LOG):
  чужие detached-копии (outside, revert_check, другие сессии) и копию на ветке --force не убирает никогда;
- remove копии на ветке без --force, которую git не убрал (metis-1336, случай metis-1324): убирается, только если все
  коммиты ветки уже в основной ветке origin (merge-base --is-ancestor с origin/HEAD, origin/main или origin/master),
  `git diff HEAD` пуст и неотслеживаемых нет — расхождение индекса и рабочего дерева при нулевом итоге не держит;
  ветка остаётся. Копия с подмодулями (gitdir копии/modules, .gitmodules в копии или gitlink 160000 в индексе) —
  отказ всегда: git сам её не убирает, а --force стёр бы незапушенные коммиты подмодуля. Иначе — прежний отказ git
  (код 1) с причиной. Эти проверки (_settled) зовут git в основной копии с
  --git-dir проверенного gitdir копии и --work-tree копии, без внешнего diff и textconv;
- git — с GIT_CONFIG_NOSYSTEM=1: системный gitconfig мимо песочницы не читается (глобальный ~/.gitconfig читается —
  в нём git-lfs владельца; остаток — README guard);
- git в копии не зовётся никогда, кроме проверок _settled выше с явными --git-dir и --work-tree из основной копии
  (фоновая проверка #488, вариант А): окно после EnterWorktree с path пишет в gitdir
  копии и её файл .git. Репозиторий ищется по папкам вверх до настоящей папки .git, а копию перед remove и меткой
  проверяет _verify_copy по файлам, как trusted_clone в outside.py: .git — обычный файл `gitdir:` на
  <repo>/.git/worktrees/<id>, commondir ведёт на <repo>/.git, gitdir — обратно на <копия>/.git, в gitdir копии нет
  config и config.worktree и нет ссылок. Не сошлось — отказ 2, git не зовётся;
- add отказывает, если в дереве базы есть .claude/settings*.json с ключами, расширяющими окно (как guard worktree-own),
  кроме файла байт в байт как у основной копии: EnterWorktree в такую копию загрузил бы их в окно.
Остаток: подмена звена пути между проверкой и git (TOCTOU) — намеренный обход, граница — песочница (README guard).

P — модуль pantheon: его ставит загрузчик pantheon._attach до выполнения этого файла.
"""
import json
import os
import re
import stat
import subprocess
import sys

__all__ = ["WT_NAME", "worktree_cmd", "wt_repo", "wt_own", "wt_verify_copy", "WtRefuse"]

WT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")
WT_MAX = 120
GIT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
GIT_SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
DETACH_MARK = "pantheon-detach"  # метка в gitdir копии: её создал `pantheon worktree add --detach`
BUSY = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "BISECT_LOG")
# ключи настроек проекта, расширяющие окно, — как WIDEN_KEYS guard_rules.py (worktree-own); импорт между плагинами
# храповик не пускает, поэтому копия: правишь там — правь и здесь (test_worktree.py сверяет)
WIDEN_KEYS = ("hooks", "env", "enabledPlugins", "enabledMcpjsonServers", "enableAllProjectMcpServers", "apiKeyHelper",
              "statusLine", "awsAuthRefresh", "awsCredentialExport", "otelHeadersHelper")
SAFE_PERMISSIONS = ("deny", "ask")
SAFE_SANDBOX = ("autoAllowBashIfSandboxed", "failIfUnavailable", "enabled")
SETTINGS = ("settings.json", "settings.local.json")
USAGE = ("pantheon worktree add <имя> [--branch B | --detach] [--base REF] | remove <имя> [--force] | list — "
         "worktree репозитория "
         "текущей папки в <репозиторий>/.claude/worktrees/<имя>")


class Refuse(Exception):
    pass


def _ok_name(x, what):
    if not x or len(x) > WT_MAX or ".." in x or not WT_NAME.fullmatch(x) or x.endswith((".lock", ".")):
        raise Refuse(f"{what} «{x}» не по шаблону: буквы, цифры, . _ - и / между частями, без .. и ведущего «-», "
                     f"до {WT_MAX} знаков")
    return x


def _git(args, cwd):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = GIT_PATH
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return subprocess.run(["git", *GIT_SAFE, *args], cwd=cwd, env=env, capture_output=True, text=True)


def _under(p, top):
    return p == top or p.startswith(top.rstrip("/") + "/")


def _repo(cwd):
    """Настоящий путь основной копии репозитория текущей папки; cwd — внутри неё (и её .claude/worktrees).
    Ищется по папкам вверх до настоящей папки .git, а git зовётся только в найденной основной копии: в копии
    (.git — файл) его файлы и gitdir пишет окно (вариант А), её конфиг мимо песочницы не читается."""
    d, seen_file = os.path.realpath(cwd), False
    while True:
        dotgit = os.path.join(d, ".git")
        if os.path.isdir(dotgit) and not os.path.islink(dotgit):
            break
        seen_file = seen_file or os.path.lexists(dotgit)
        up = os.path.dirname(d)
        if up == d:
            raise Refuse("текущая папка вне основной копии (worktree или подмодуль снаружи) — сначала cd в репозиторий"
                         if seen_file else "текущая папка не в git-репозитории")
        d = up
    r = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], d)
    common = os.path.realpath(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else ""
    if common != dotgit or os.path.lexists(os.path.join(dotgit, "commondir")):
        raise Refuse(f"{P.tilde(dotgit)}: git видит другой common ({P.tilde(common) if common else 'нет'}) — "
                     "не папка .git основной копии")
    return d


def _own(repo):
    """В окне направления — репозиторий только своего направления (самая глубокая папка направлений над ним)."""
    win = os.environ.get("PANTHEON_WINDOW") or ""
    doms = (P.read_json(P.path("domains.json"), {}) or {}).get("domains") or {}
    if not win or not isinstance(doms.get(win), list):
        return
    hits = [(os.path.realpath(os.path.expanduser(f)), n) for n, fs in doms.items() if isinstance(fs, list)
            for f in fs if isinstance(f, str) and f]
    hits = [(f, n) for f, n in hits if _under(repo, f)]
    owner = max(hits, key=lambda x: len(x[0]))[1] if hits else None
    if owner != win:
        raise Refuse(f"{P.tilde(repo)} — " + (f"репозиторий направления {owner}" if owner else "вне папок направлений")
                     + f", а окно — {win}: worktree только в своих репозиториях")


def _target(repo, name, create):
    """<repo>/.claude/worktrees/<name>: звенья — не ссылки, родитель настоящим путём — внутри .claude/worktrees."""
    base = os.path.join(repo, ".claude", "worktrees")
    parts = [os.path.join(repo, ".claude"), base]
    segs = name.split("/")
    parts += [os.path.join(base, *segs[:i]) for i in range(1, len(segs))]
    for p in parts:
        if os.path.islink(p):
            raise Refuse(f"{P.tilde(p)} — ссылка: worktree только в настоящей папке .claude/worktrees")
        if os.path.lexists(p) and not os.path.isdir(p):
            raise Refuse(f"{P.tilde(p)} — не папка")
    target = os.path.join(base, *segs)
    if create:
        os.makedirs(os.path.dirname(target), exist_ok=True)
    parent = os.path.realpath(os.path.dirname(target))
    if not _under(parent, base) or os.path.realpath(base) != base:
        raise Refuse(f"{P.tilde(target)}: настоящий путь вне {P.tilde(base)}")
    return target


def _branch_exists(repo, b):
    return _git(["rev-parse", "--verify", "--quiet", "refs/heads/" + b], repo).returncode == 0


def _add(repo, name, branch, base):
    """branch None — копия без ветки (--detach) от base или HEAD."""
    target = _target(repo, name, create=False)
    if os.path.lexists(target):
        raise Refuse(f"{P.tilde(target)} уже есть — другое имя или `pantheon worktree remove {name}`")
    if branch is None:
        if _git(["rev-parse", "--verify", "--quiet", (base or "HEAD") + "^{commit}"], repo).returncode != 0:
            raise Refuse(f"база «{base or 'HEAD'}» — не коммит")
        _no_widening(repo, base or "HEAD")
        target = _target(repo, name, create=True)
        r = _git(["worktree", "add", "--detach", target, base or "HEAD"], repo)
        if r.returncode != 0:
            print(f"pantheon worktree add: git worktree add не прошёл: {r.stderr.strip()[-400:]}", file=sys.stderr)
            return 1
        try:
            gd = _verify_copy(repo, target)
        except Refuse as e:
            print(f"pantheon worktree add: копия {P.tilde(target)} создана, но метка не записана ({e}) — "
                  "remove --force её не уберёт", file=sys.stderr)
            return 1
        with open(os.path.join(gd, DETACH_MARK), "w", encoding="utf-8") as fh:
            fh.write("pantheon worktree add --detach\n")
        print(f"worktree {P.tilde(target)} — без ветки, от {base or 'HEAD'}")
        return 0
    if _git(["check-ref-format", "--branch", branch], repo).returncode != 0:
        raise Refuse(f"ветка «{branch}» — не имя ветки git")
    have = _branch_exists(repo, branch)
    if have and base:
        raise Refuse(f"ветка {branch} уже есть — без --base (worktree возьмёт её) или другая ветка")
    if not have and _git(["rev-parse", "--verify", "--quiet", (base or "HEAD") + "^{commit}"], repo).returncode != 0:
        raise Refuse(f"база «{base or 'HEAD'}» — не коммит")
    _no_widening(repo, ("refs/heads/" + branch) if have else (base or "HEAD"))
    target = _target(repo, name, create=True)
    args = ["worktree", "add", target, branch] if have else ["worktree", "add", "-b", branch, target, base or "HEAD"]
    r = _git(args, repo)
    if r.returncode != 0:
        print(f"pantheon worktree add: git worktree add не прошёл: {r.stderr.strip()[-400:]}", file=sys.stderr)
        return 1
    print(f"worktree {P.tilde(target)} — ветка {branch}" + ("" if have else f" от {base or 'HEAD'}"))
    return 0


def _listed(repo):
    """{настоящий путь: без ветки (detached)} по `git worktree list --porcelain`."""
    r = _git(["worktree", "list", "--porcelain"], repo)
    out, cur = {}, None
    for ln in r.stdout.splitlines() if r.returncode == 0 else []:
        if ln.startswith("worktree "):
            cur = os.path.realpath(ln[9:])
            out[cur] = False
        elif ln == "detached" and cur:
            out[cur] = True
    return out


def _small(p, limit=4096):
    """Текст обычного файла p (не ссылки, до limit байт) или None."""
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        return os.read(fd, limit + 1).decode("utf-8", "replace")
    finally:
        os.close(fd)


def _verify_copy(repo, target):
    """Настоящий gitdir копии <repo>/.git/worktrees/<id> — проверенный по файлам, без git в копии (фоновая проверка
    #488): окно после EnterWorktree с path пишет в её .git и gitdir. Не сошлось — Refuse."""
    dotgit = os.path.join(target, ".git")
    common = os.path.join(repo, ".git")
    m = re.fullmatch(r"gitdir: *(\S[^\n]*?) *\n?", _small(dotgit) or "")
    if not m:
        raise Refuse(f"{P.tilde(dotgit)} — не обычный файл `gitdir: …`: копию правили не git")
    gd = os.path.realpath(os.path.join(target, m.group(1)))
    wts = os.path.join(common, "worktrees")
    back = (_small(os.path.join(gd, "gitdir")) or "").strip()
    cdir = (_small(os.path.join(gd, "commondir")) or "").strip()
    if (os.path.dirname(gd) != wts or not cdir or os.path.realpath(os.path.join(gd, cdir)) != common
            or not back or os.path.realpath(os.path.join(gd, back)) != os.path.realpath(dotgit)):
        raise Refuse(f"{P.tilde(dotgit)} ведёт на {P.tilde(gd)} — это не gitdir копии в {P.tilde(wts)} "
                     "(commondir и gitdir не сходятся)")
    if any(os.path.islink(x) for x in (common, wts, os.path.join(wts, os.path.basename(gd)))):
        raise Refuse(f"в пути {P.tilde(gd)} — ссылка: git взял бы не ту папку, что проверена")
    if os.path.lexists(os.path.join(common, "commondir")):
        raise Refuse(f"у {P.tilde(common)} свой commondir — конфиг взялся бы из другой папки")
    planted = [n for n in ("config", "config.worktree") if os.path.lexists(os.path.join(gd, n))]
    planted += [n for n in os.listdir(gd) if os.path.islink(os.path.join(gd, n))]
    if planted:
        raise Refuse(f"в {P.tilde(gd)} — {', '.join(dict.fromkeys(planted))}: конфиг или ссылку в gitdir копии git "
                     "не пишет, а мимо песочницы git их бы прочёл — убери их сам")
    return gd


def _widen_keys(data):
    """Ключи настроек проекта, расширяющие окно (как _widening в guard_rules.py)."""
    if not isinstance(data, dict):
        return []
    keys = [k for k in WIDEN_KEYS if data.get(k)]
    for top, safe in (("permissions", SAFE_PERMISSIONS), ("sandbox", SAFE_SANDBOX)):
        sub = data.get(top)
        if isinstance(sub, dict):
            keys += [f"{top}.{k}" for k, v in sub.items() if v and k not in safe]
            if top == "sandbox" and sub.get("enabled") is False:
                keys.append("sandbox.enabled")
        elif sub:
            keys.append(top)
    return keys


def _tree_settings(repo, rev):
    """[(файл, ключи)] — .claude/settings*.json дерева rev, расширяющие окно; файл байт в байт как у основной копии —
    не в счёт (её настройки — те же, что уже в репозитории). Читает git cat-file в основной копии, без фильтров."""
    found = []
    for fn in SETTINGS:
        r = subprocess.run(["git", *GIT_SAFE, "cat-file", "blob", f"{rev}:.claude/{fn}"], cwd=repo,
                           env={**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
                                "PATH": GIT_PATH, "GIT_CONFIG_NOSYSTEM": "1"}, capture_output=True)
        if r.returncode != 0:
            continue
        mine = os.path.join(repo, ".claude", fn)
        try:
            if not os.path.islink(mine):
                with open(mine, "rb") as fh:
                    if fh.read() == r.stdout:
                        continue
        except OSError:
            pass
        try:
            keys = _widen_keys(json.loads(r.stdout.decode("utf-8")))
        except ValueError:
            keys = ["?"]
        if keys:
            found.append((f".claude/{fn}", keys))
    return found


def _no_widening(repo, rev):
    found = _tree_settings(repo, rev)
    if found:
        shown = "; ".join(f"{f}: {', '.join(k)}" for f, k in found)
        raise Refuse(f"в дереве {rev} — настройки проекта, расширяющие окно ({shown}): EnterWorktree в такую копию "
                     "загрузил бы их молча (guard worktree-own). Убери ключи в ветке или верни в отчёт — их принимает "
                     "владелец")


def _main_ref(repo):
    """Основная ветка origin: refs/remotes/origin/HEAD, иначе origin/main, origin/master; нет — None."""
    for ref in ("refs/remotes/origin/HEAD", "refs/remotes/origin/main", "refs/remotes/origin/master"):
        if _git(["rev-parse", "--verify", "--quiet", ref + "^{commit}"], repo).returncode == 0:
            return ref
    return None


def _settled(repo, gd, target):
    """Отработанная копия на ветке (metis-1336, случай metis-1324): все коммиты ветки уже в основной ветке origin,
    `git diff HEAD` пуст, неотслеживаемых нет и подмодулей нет (их коммиты --force стёр бы) — расхождение индекса и
    рабочего дерева при нулевом итоге не держит. None — можно убрать с --force (ничего несохранённого не теряется), иначе причина отказа. git — в основной копии
    с --git-dir проверенного gitdir копии (_verify_copy: в нём нет config и ссылок) и --work-tree копии, с GIT_SAFE,
    без внешнего diff и textconv."""
    busy = [b for b in BUSY if os.path.lexists(os.path.join(gd, b))]
    if busy:
        return f"идёт {', '.join(busy)}"
    base = _main_ref(repo)
    if base is None:
        return "нет origin/main — `pantheon git fetch` и повтор"
    g = ["--git-dir=" + gd, "--work-tree=" + target]
    stage = _git([*g, "ls-files", "--stage", "-z"], repo)
    if (os.path.lexists(os.path.join(gd, "modules")) or os.path.lexists(os.path.join(target, ".gitmodules"))
            or stage.returncode != 0 or any(e.startswith("160000 ") for e in stage.stdout.split("\0"))):
        return "подмодули — --force стёр бы и их незапушенные коммиты; убери копию сам"
    head = _git([*g, "rev-parse", "--verify", "--quiet", "HEAD^{commit}"], repo)
    sha = head.stdout.strip()
    if head.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", sha):
        return "HEAD копии не коммит"
    if _git(["merge-base", "--is-ancestor", sha, base], repo).returncode != 0:
        return f"коммит {sha[:8]} не в {base.removeprefix('refs/remotes/')} — ветка не слита (или `pantheon git fetch`)"
    if _git([*g, "diff", "--quiet", "--no-ext-diff", "--no-textconv", "HEAD", "--"], repo).returncode != 0:
        return "есть несохранённые правки относительно HEAD (git diff HEAD не пуст)"
    other = _git([*g, "ls-files", "--others", "--exclude-standard", "-z"], repo)
    if other.returncode != 0 or other.stdout:
        return "есть неотслеживаемые файлы"
    return None


def _remove(repo, name, force=False):
    target = _target(repo, name, create=False)
    if not os.path.isdir(target) or os.path.islink(target):
        raise Refuse(f"{P.tilde(target)} — нет такой папки worktree")
    listed = _listed(repo)
    if os.path.realpath(target) in listed:
        gd = _verify_copy(repo, target)
    if os.path.realpath(target) not in listed:
        raise Refuse(f"{P.tilde(target)} — не worktree этого репозитория (git worktree list)")
    detached = listed[os.path.realpath(target)]
    if force and not detached:
        raise Refuse(f"{P.tilde(target)} — на ветке: --force только у копии без ветки (add --detach); "
                     "закоммить или убери изменения сам")
    if force and not (gd and os.path.isfile(os.path.join(gd, DETACH_MARK))):
        raise Refuse(f"{P.tilde(target)} — копия без ветки, но создана не `pantheon worktree add --detach` (метки нет): "
                     "--force только у своих временных копий")
    busy = [b for b in BUSY if gd and os.path.lexists(os.path.join(gd, b))]
    if force and busy:
        raise Refuse(f"{P.tilde(target)} — идёт {', '.join(busy)}: --force не убирает копию посреди rebase, merge или "
                     "bisect — доведи или прерви их сам")
    r = _git(["worktree", "remove", *(["--force"] if force else []), target], repo)
    why = None
    if r.returncode != 0 and not force and not detached:
        why = _settled(repo, gd, target)
        if why is None:
            r = _git(["worktree", "remove", "--force", target], repo)
            if r.returncode == 0:
                print(f"worktree {P.tilde(target)} убрана: ветка уже в основной, итог относительно HEAD нулевой "
                      "(ветка осталась)")
                return 0
    if r.returncode != 0:
        mine = detached and os.path.isfile(os.path.join(gd, DETACH_MARK))
        hint = (" — своя копия без ветки: `pantheon worktree remove " + name + " --force`") if mine else \
            " (без --force: незакоммиченное не удаляется)"
        print(f"pantheon worktree remove: git worktree remove не прошёл{hint}: {r.stderr.strip()[-400:]}"
              + (f"; без --force не убрана: {why}" if why else ""), file=sys.stderr)
        return 1
    print(f"worktree {P.tilde(target)} убрана" + ("" if detached else " (ветка осталась)"))
    return 0


def _parse_add(rest):
    if not rest:
        raise Refuse("нужно имя worktree")
    name, opts, it = _ok_name(rest[0], "имя"), {}, iter(rest[1:])
    for a in it:
        if a not in ("--branch", "--base", "--detach") or a in opts:
            raise Refuse(f"лишнее слово «{a}» — только --branch B или --detach и --base REF, по разу")
        if a == "--detach":
            opts[a] = True
            continue
        v = next(it, None)
        if v is None:
            raise Refuse(f"после {a} нужно значение")
        opts[a] = _ok_name(v, "ветка" if a == "--branch" else "база")
    if "--detach" in opts and "--branch" in opts:
        raise Refuse("--detach и --branch вместе нельзя: копия либо без ветки, либо на ветке")
    branch = None if "--detach" in opts else (opts.get("--branch") or name)
    return name, branch, opts.get("--base")


def worktree_cmd(rest, cwd=None):
    sub, rest = (rest[0], rest[1:]) if rest else ("", [])
    try:
        cwd = cwd or os.getcwd()
        if sub == "add":
            name, branch, base = _parse_add(rest)
            repo = _repo(cwd)
            _own(repo)
            return _add(repo, name, branch, base)
        if sub == "remove" and (len(rest) == 1 or (len(rest) == 2 and rest[1] == "--force")):
            name = _ok_name(rest[0], "имя")
            repo = _repo(cwd)
            _own(repo)
            return _remove(repo, name, force=len(rest) == 2)
        if sub == "list" and not rest:
            repo = _repo(cwd)
            base = os.path.join(repo, ".claude", "worktrees")
            for p in _listed(repo):
                if _under(p, base) and p != base:
                    print(p[len(base) + 1:] + "\t" + P.tilde(p))
            return 0
        raise Refuse(USAGE)
    except (Refuse, OSError) as e:
        print(f"pantheon worktree {sub}: {e}", file=sys.stderr)
        return 2


# проверки папки git — и для `pantheon git push|fetch` (gitout.py, metis-0972)
wt_repo, wt_own, wt_verify_copy, WtRefuse = _repo, _own, _verify_copy, Refuse
