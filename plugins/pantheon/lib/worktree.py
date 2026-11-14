"""Пантеон: worktree окна направления (metis-1225, вариант Б владельца 15.11).

`pantheon worktree add <имя> [--branch B] [--base REF]`, `pantheon worktree remove <имя>`, `pantheon worktree list`.
Claude Code (2.1.325) в песочнице закрывает запись в .git/worktrees, кроме worktree своей сессии, а EnterWorktree
окнам направлений закрыт (WORKTREE_TOOLS, П9b) — `git worktree add|remove` из Bash окна падает EPERM на полпути. Мимо
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
- remove — только зарегистрированная worktree под `.claude/worktrees/`, без --force: грязную git не уберёт.
Остаток: подмена звена пути между проверкой и git (TOCTOU) — намеренный обход, граница — песочница (README guard).

P — модуль pantheon: его ставит загрузчик pantheon._attach до выполнения этого файла.
"""
import os
import re
import subprocess
import sys

__all__ = ["WT_NAME", "worktree_cmd"]

WT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")
WT_MAX = 120
GIT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
GIT_SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
USAGE = ("pantheon worktree add <имя> [--branch B] [--base REF] | remove <имя> | list — worktree репозитория "
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
    return subprocess.run(["git", *GIT_SAFE, *args], cwd=cwd, env=env, capture_output=True, text=True)


def _under(p, top):
    return p == top or p.startswith(top.rstrip("/") + "/")


def _repo(cwd):
    """Настоящий путь основной копии репозитория текущей папки; cwd — внутри неё (и её .claude/worktrees)."""
    r = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    common = r.stdout.strip().rstrip("/")
    if r.returncode != 0 or not common:
        raise Refuse("текущая папка не в git-репозитории")
    common = os.path.realpath(common)
    if os.path.basename(common) != ".git" or not os.path.isdir(common):
        raise Refuse(f"{P.tilde(common)}: не папка .git основной копии (голый репозиторий или gitdir снаружи)")
    repo = os.path.dirname(common)
    if not _under(os.path.realpath(cwd), repo):
        raise Refuse(f"текущая папка вне основной копии {P.tilde(repo)} — сначала cd в репозиторий")
    return repo


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
    target = _target(repo, name, create=False)
    if os.path.lexists(target):
        raise Refuse(f"{P.tilde(target)} уже есть — другое имя или `pantheon worktree remove {name}`")
    if _git(["check-ref-format", "--branch", branch], repo).returncode != 0:
        raise Refuse(f"ветка «{branch}» — не имя ветки git")
    have = _branch_exists(repo, branch)
    if have and base:
        raise Refuse(f"ветка {branch} уже есть — без --base (worktree возьмёт её) или другая ветка")
    if not have and _git(["rev-parse", "--verify", "--quiet", (base or "HEAD") + "^{commit}"], repo).returncode != 0:
        raise Refuse(f"база «{base or 'HEAD'}» — не коммит")
    target = _target(repo, name, create=True)
    args = ["worktree", "add", target, branch] if have else ["worktree", "add", "-b", branch, target, base or "HEAD"]
    r = _git(args, repo)
    if r.returncode != 0:
        print(f"pantheon worktree add: git worktree add не прошёл: {r.stderr.strip()[-400:]}", file=sys.stderr)
        return 1
    print(f"worktree {P.tilde(target)} — ветка {branch}" + ("" if have else f" от {base or 'HEAD'}"))
    return 0


def _listed(repo):
    r = _git(["worktree", "list", "--porcelain"], repo)
    return [os.path.realpath(ln[9:]) for ln in r.stdout.splitlines() if ln.startswith("worktree ")] \
        if r.returncode == 0 else []


def _remove(repo, name):
    target = _target(repo, name, create=False)
    if not os.path.isdir(target) or os.path.islink(target):
        raise Refuse(f"{P.tilde(target)} — нет такой папки worktree")
    if os.path.realpath(target) not in _listed(repo):
        raise Refuse(f"{P.tilde(target)} — не worktree этого репозитория (git worktree list)")
    r = _git(["worktree", "remove", target], repo)
    if r.returncode != 0:
        print(f"pantheon worktree remove: git worktree remove не прошёл (без --force: незакоммиченное не "
              f"удаляется): {r.stderr.strip()[-400:]}", file=sys.stderr)
        return 1
    print(f"worktree {P.tilde(target)} убрана (ветка осталась)")
    return 0


def _parse_add(rest):
    if not rest:
        raise Refuse("нужно имя worktree")
    name, opts, it = _ok_name(rest[0], "имя"), {}, iter(rest[1:])
    for a in it:
        if a not in ("--branch", "--base") or a in opts:
            raise Refuse(f"лишнее слово «{a}» — только --branch B и --base REF, по разу")
        v = next(it, None)
        if v is None:
            raise Refuse(f"после {a} нужно значение")
        opts[a] = _ok_name(v, "ветка" if a == "--branch" else "база")
    return name, opts.get("--branch") or name, opts.get("--base")


def worktree_cmd(rest, cwd=None):
    sub, rest = (rest[0], rest[1:]) if rest else ("", [])
    try:
        cwd = cwd or os.getcwd()
        if sub == "add":
            name, branch, base = _parse_add(rest)
            repo = _repo(cwd)
            _own(repo)
            return _add(repo, name, branch, base)
        if sub == "remove" and len(rest) == 1:
            name = _ok_name(rest[0], "имя")
            repo = _repo(cwd)
            _own(repo)
            return _remove(repo, name)
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
