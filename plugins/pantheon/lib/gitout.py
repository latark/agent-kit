"""Пантеон: git мимо песочницы окна — только `pantheon git push|fetch` (metis-0972, вариант А владельца 20.11).

`pantheon git push <remote> <источник>:<ветка>...`, `pantheon git fetch [<remote> [<refspec>...]]`.
Модель угроз — reviews/threat-model-0972-git-outside.md (14 путей). Голые `git push|fetch` в excludedCommands окна
больше нет (GIT_OUT в pantheon.py), guard отказывает им в окне (правило git-out), мимо песочницы идёт только эта
команда, поэтому всё, что git мог бы исполнить или прочесть из папки окна, отсекает она сама:

- папка git — настоящая: каталог `.git` основной копии (commondir нет, git видит тот же common) или копия этого
  репозитория в `.git/worktrees/<id>`, проверенная по файлам (_verify_copy worktree.py). `.git` — ссылка, gitfile на
  чужую папку (--separate-git-dir, подмодуль), переписанный commondir — отказ 2 до git;
- в окне направления — только репозиторий своего направления (как `pantheon worktree`);
- objects/info/alternates, http-alternates, info/grafts — отказ: объекты взялись бы из чужой папки;
- конфиг репозитория читается без include (`--no-includes`), и ключи, которыми git исполняет код или уводит данные,
  — отказ: include, includeIf, url.*.insteadOf, remote.*.uploadpack|receivepack|pushurl|proxy|vcs|mirror,
  credential.*, core.hooksPath|fsmonitor|sshCommand|pager|gitProxy|askPass|alternateRefsCommand|editor|worktree,
  protocol.*, http.* (любой), extensions.worktreeConfig;
- remote — имя из конфига (не `.`, не путь и не адрес), его url — только github.com по https или ssh, звенья пути
  без ведущей точки (`/./`, `..`) — локальный путь и чужой хост не пройдут;
- push: ветка назначения — `X`, `heads/X` или `refs/heads/X`, не main и не master в любом регистре, без `+`, без
  пустого источника (удаление), без шаблонов и тегов; источник — HEAD или имя ветки; флагов нет совсем;
- fetch: назначение refspec — пусто, refs/remotes/* или refs/tags/*, то же у remote.<r>.fetch конфига (по нему git
  обновляет ветки и при явном refspec); флагов нет, --update-head-ok в том числе;
- git зовётся с --no-replace-objects, -c core.hooksPath=/dev/null, core.fsmonitor=false, core.sshCommand=ssh,
  core.pager=cat, protocol.allow=never (кроме https и ssh), --no-recurse-submodules, у push --no-verify; окружение —
  без GIT_* (кроме GIT_AUTHOR_*/GIT_COMMITTER_* NAME, EMAIL, DATE), XDG_CONFIG_HOME, PAGER и SSH_ASKPASS, с фиксированным PATH, GIT_CONFIG_NOSYSTEM=1,
  GIT_NO_REPLACE_OBJECTS=1 и GIT_TERMINAL_PROMPT=0. Глобальный ~/.gitconfig читается (вход gh для github.com).

git_window — тот же проверенный git для `pantheon batch pr` (metis-1333): она идёт мимо песочницы, потому что в окне
Связка закрыта и gh там без входа; папка, конфиг и remote origin проверяются, как у fetch, git — с теми же флагами и
окружением, а репозиторий для gh (`-R`) — из проверенного url origin.

git_hard — тот же git без хуков для ~/ai/pantheon (P.git: archive.py commit, pull и push идут мимо песочницы из
`pantheon commit`): папка .git — настоящая, окружение и флаги те же, но системный конфиг и фильтры читаются (вход
osxkeychain, git-crypt), а протоколы не сужаются.
Остаток: подмена звена пути между проверкой и git (TOCTOU) — намеренный обход, граница — песочница (README guard);
pre-push хуки проектов (git-lfs) мимо песочницы не идут.

P — модуль pantheon: его ставит загрузчик pantheon._attach до выполнения этого файла.
"""
import os
import re
import subprocess
import sys

__all__ = ["git_cmd", "git_hard", "git_window"]

GIT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
HARD = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.sshCommand=ssh", "-c", "core.pager=cat", "-c", "submodule.recurse=false"]
NET = ["-c", "protocol.allow=never", "-c", "protocol.https.allow=always", "-c", "protocol.ssh.allow=always"]
ENV_KEEP = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
            "GIT_COMMITTER_DATE")  # автор и время коммита: кода не исполняют (metis-0972, test_board_lock)
ENV_DROP = ("XDG_CONFIG_HOME", "PAGER", "SSH_ASKPASS", "SSH_ASKPASS_REQUIRE")
NAME = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}"
SEG = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}"
URLS = (re.compile(rf"https://github\.com/{SEG}/{SEG}/?"), re.compile(rf"(?:ssh://git@github\.com/|git@github\.com:){SEG}/{SEG}/?"))
REMOTE = re.compile(NAME)
BRANCH = re.compile(rf"{NAME}(?:/{NAME})*")
PROTECTED = {"main", "master"}
BAD_KEY = re.compile(r"(?:include|includeif)\..*|url\..*\.(?:insteadof|pushinsteadof)"
                     r"|remote\..*\.(?:uploadpack|receivepack|pushurl|proxy|vcs|mirror)|credential\..*"
                     r"|core\.(?:hookspath|fsmonitor|sshcommand|pager|gitproxy|askpass|alternaterefscommand|editor|worktree)"
                     r"|protocol\..*|extensions\.worktreeconfig"
                     r"|http\..*"   # любой http.* копии: прокси, TLS, адрес, cookie, заголовки (argus и проверка безопасности #507)
                     r"|fetch\.bundleuri|extensions\.partialclone|remote\..*\.promisor")  # bundle и promisor: скачивание мимо сети песочницы (argus #507)
FOREIGN_OBJECTS = ("objects/info/alternates", "objects/info/http-alternates", "info/grafts")
USAGE = ("pantheon git push <remote> <источник>:<ветка>... | fetch [<remote> [<refspec>...]] — "
         "git мимо песочницы без хуков и конфига папки окна")


class Refuse(Exception):
    pass


def _env(system=False):
    env = {k: v for k, v in os.environ.items() if (not k.startswith("GIT_") or k in ENV_KEEP) and k not in ENV_DROP}
    env.update(PATH=GIT_PATH, GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0")
    if not system:
        env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _where(cwd):
    """(репозиторий, gitdir, common, рабочее дерево) текущей папки; всё — проверенные по файлам настоящие пути."""
    d = os.path.realpath(cwd)
    while not os.path.lexists(os.path.join(d, ".git")):
        up = os.path.dirname(d)
        if up == d:
            raise Refuse("текущая папка не в git-репозитории")
        d = up
    dotgit = os.path.join(d, ".git")
    if os.path.islink(dotgit):
        raise Refuse(f"{P.tilde(dotgit)} — ссылка: git взял бы не ту папку, что проверена")
    if os.path.isdir(dotgit):
        if P.wt_repo(d) != d:
            raise Refuse(f"{P.tilde(dotgit)} — не основная копия")
        return d, dotgit, dotgit, d
    repo = P.wt_repo(os.path.dirname(d))
    return repo, P.wt_verify_copy(repo, d), os.path.join(repo, ".git"), d


def _config(common):
    r = subprocess.run(["git", "config", "--file", os.path.join(common, "config"), "--no-includes", "-z", "--list"],
                       env=_env(), capture_output=True, text=True)
    if r.returncode:
        raise Refuse(f"конфиг {P.tilde(common)}/config не читается: {(r.stderr.strip().splitlines() or [''])[-1]}")
    out = []
    for item in filter(None, r.stdout.split("\0")):
        k, _, v = item.partition("\n")
        out.append((k.lower(), v))
    return out


def _dst_ok(refspec):
    dst = refspec.lstrip("+^").partition(":")[2]
    return not dst or dst.startswith(("refs/remotes/", "refs/tags/"))


def _check_repo(common, gitdir, remote, fetch):
    for rel in FOREIGN_OBJECTS:
        if os.path.lexists(os.path.join(common, rel)):
            raise Refuse(f"в {P.tilde(common)} есть {rel}: объекты взялись бы из чужой папки — убери его сам")
    if os.path.lexists(os.path.join(common, "config.worktree")) or os.path.lexists(os.path.join(gitdir, "config.worktree")):
        raise Refuse("config.worktree в папке git: его git читает мимо проверки — убери его сам")
    conf = _config(common)
    bad = sorted({k for k, _ in conf if BAD_KEY.fullmatch(k)})
    if bad:
        raise Refuse(f"в {P.tilde(common)}/config — {', '.join(bad)}: этими ключами git исполнил бы код или увёл "
                     "данные мимо песочницы — убери их сам (git config --unset)")
    pre = f"remote.{remote.lower()}."
    urls = [v for k, v in conf if k == pre + "url"]
    if not urls:
        raise Refuse(f"remote «{remote}» нет в конфиге репозитория")
    for u in urls:
        if not any(p.fullmatch(u) for p in URLS):
            raise Refuse(f"url remote «{remote}» — «{u}»: мимо песочницы — только github.com по https или ssh, "
                         "звенья пути без ведущей точки")
    if fetch:
        wrong = [v for k, v in conf if k == pre + "fetch" and not _dst_ok(v)]
        if wrong:
            raise Refuse(f"remote.{remote}.fetch = {', '.join(wrong)}: fetch обновил бы ветку, а не refs/remotes")


def _push_spec(spec):
    if spec.startswith("+"):
        raise Refuse(f"«{spec}»: принудительный push (+) мимо песочницы не идёт")
    src, colon, dst = spec.partition(":")
    if not colon:
        if src == "HEAD":
            raise Refuse("«HEAD» без ветки: назови её — HEAD:<ветка>")
        dst = src
    if not src:
        raise Refuse(f"«{spec}»: удаление ветки (пустой источник) мимо песочницы не идёт")
    if src != "HEAD" and (".." in src or not BRANCH.fullmatch(src)):
        raise Refuse(f"источник «{src}» — только HEAD или имя ветки")
    for pre in ("refs/heads/", "heads/"):
        if dst.startswith(pre):
            dst = dst[len(pre):]
            break
    if ".." in dst or not BRANCH.fullmatch(dst) or dst.endswith((".lock", ".")) or dst.startswith("refs/"):
        raise Refuse(f"назначение «{spec.partition(':')[2] or spec}» — только ветка: X, heads/X или refs/heads/X")
    if dst.lower() in PROTECTED:
        raise Refuse(f"push в {dst} — только через шлюз слияния (PR), не из окна")
    return f"{src}:refs/heads/{dst}"


def _fetch_spec(spec):
    src = spec.lstrip("+").partition(":")[0]
    if not src or ".." in spec or not re.fullmatch(r"[A-Za-z0-9_./*+:-]+", spec) or not _dst_ok(spec):
        raise Refuse(f"refspec «{spec}»: назначение fetch — пусто, refs/remotes/* или refs/tags/*")
    return spec


def _parse(rest):
    if not rest or rest[0] not in ("push", "fetch"):
        raise Refuse(USAGE)
    sub, args = rest[0], rest[1:]
    flags = [a for a in args if a.startswith("-")]
    if flags:
        raise Refuse(f"флаги {' '.join(flags)} мимо песочницы не идут: {USAGE}")
    if sub == "fetch" and not args:
        args = ["origin"]
    remote, specs = (args[0], args[1:]) if args else ("", [])
    if not REMOTE.fullmatch(remote) or remote.strip(".") == "":
        raise Refuse(f"remote «{remote}» — только имя из конфига (не «.», не путь и не адрес): {USAGE}")
    if sub == "push":
        if not specs:
            raise Refuse(f"push без ветки: {USAGE}")
        specs = [_push_spec(s) for s in specs]
    else:
        specs = [_fetch_spec(s) for s in specs]
    return sub, remote, specs


def git_cmd(rest, cwd=None):
    try:
        sub, remote, specs = _parse(rest)
        repo, gitdir, common, wt = _where(cwd or os.getcwd())
        P.wt_own(repo)
        _check_repo(common, gitdir, remote, sub == "fetch")
    except (Refuse, P.WtRefuse) as e:
        print(f"pantheon git: {e}", file=sys.stderr)
        return 2
    cmd = ["git", "--no-replace-objects", f"--git-dir={gitdir}", f"--work-tree={wt}", *HARD, *NET, sub,
           "--no-recurse-submodules", *(["--no-verify"] if sub == "push" else []), remote, *specs]
    return subprocess.run(cmd, cwd=wt, env=_env()).returncode


def git_window(cwd, remote="origin"):
    """git папки окна мимо песочницы (pantheon batch pr, metis-1333): (run, «владелец/репозиторий» remote, None) или
    (None, None, причина). run(args) — git с проверенной папкой, без хуков, конфига системы и GIT_* окна."""
    try:
        repo, gitdir, common, wt = _where(cwd)
        P.wt_own(repo)
        _check_repo(common, gitdir, remote, False)
    except (Refuse, P.WtRefuse) as e:
        return None, None, str(e)
    url = next(v for k, v in _config(common) if k == f"remote.{remote.lower()}.url")
    slug = re.sub(r"^(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)", "", url).rstrip("/")
    slug = slug[:-4] if slug.endswith(".git") else slug

    def run(args):
        cmd = ["git", "--no-replace-objects", f"--git-dir={gitdir}", f"--work-tree={wt}", *HARD, *NET, *args]
        return subprocess.run(cmd, cwd=wt, env=_env(), capture_output=True, text=True)
    return run, slug, None


def git_hard(repo, args, check=True):
    """git в основной копии repo без хуков и env окна; папка .git — настоящий каталог, не ссылка и без commondir."""
    dotgit = os.path.join(repo, ".git")
    if os.path.islink(dotgit) or not os.path.isdir(dotgit) or os.path.lexists(os.path.join(dotgit, "commondir")):
        r = subprocess.CompletedProcess(args, 2, "", f"{P.tilde(dotgit)} — не настоящая папка .git: git не зовётся\n")
        if check:
            raise subprocess.CalledProcessError(2, args, r.stdout, r.stderr)
        return r
    cmd = ["git", "--no-replace-objects", f"--git-dir={dotgit}", f"--work-tree={repo}", *HARD, *args]
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, check=check, env=_env(system=True))
