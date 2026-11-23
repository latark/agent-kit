"""Пантеон: `pantheon pr create|edit|comment|ready` — gh pr мимо песочницы окна (metis-1334, план metis-1331 PR-2a).

В окне Связка закрыта, и gh там без входа (metis-1333). Окно открывает и правит свой PR этой командой: она идёт мимо
песочницы (excludedCommands, PR_OUT в pantheon.py), поэтому всё, что раньше держало правило gh-out guard для голого
gh, проверяет она сама (Д2 плана):

1. без GH_* в окружении (GH_REPO, GH_HOST …); присваивание в строке и обёртки отсекает guard (правило pr-cmd);
2. без --hostname — его нет в таблице флагов;
3. до подкоманды — ничего: `pantheon pr <подкоманда> …`;
4. флаги — только из таблицы формы подкоманды (FORM); значение -R и -F/--body-file не начинается с «-»; -e/--editor
   и -w/--web нет совсем: редактор и браузер мимо песочницы исполнили бы чужой код;
5. позиционный — только номер PR или имя ветки (без URL и owner/repo#N); у create позиционных нет;
6. -F/--body-file: без шаблонов, не «-»; realpath — только во временных папках и своей копии репозитория, не из личного
   ([private] paths) и не из .git. Файл читает команда и отдаёт gh текстом (--body), gh путь не получает;
7. репозиторий — из проверенного url origin своей папки (git_window в gitout.py: своя копия, origin только github.com
   и из [merge_repos] своего направления); -R можно не писать, а если он есть — только этот же репозиторий;
8. окну с личным (координатор из [private] coordinators или личная папка среди папок окна) — отказ (SEC-13);
9. слова до подкоманды и `env -S` — форма строки, их держит guard (pr-cmd): строка целиком `pantheon pr …` без
   цепочек, подстановок, присваивания и обёрток.

Ещё: ветка PR — не базовая (create: --head или текущая ветка не main/master и не --base; edit, comment, ready по
ветке — не main/master). gh получает разобранные флаги в форме `--флаг=значение` (разбор gh и команды не расходится),
окружение без GH_*, GIT_* окна, XDG_CONFIG_HOME, EDITOR, VISUAL, BROWSER и PAGER, постоянный PATH (GH_PATH).
`pantheon batch pr` ходит сюда же: pr_write — запись, gh_read — `gh pr list`.
Код выхода: 2 — отказ (причина последней строкой stderr), иначе код gh.

P — модуль pantheon: его ставит загрузчик pantheon._attach до выполнения этого файла.
"""
import os
import re
import subprocess
import sys

__all__ = ["pr_cmd", "pr_write", "gh_read", "PrRefuse"]

GH_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"  # gh мимо песочницы — не из PATH окна (как GIT_PATH в gitout)
ENV_DROP = ("XDG_CONFIG_HOME", "EDITOR", "VISUAL", "BROWSER", "PAGER", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR")
ENV_KEEP = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")
USAGE = "pantheon pr create|edit|comment|ready [<номер PR|ветка>] [флаги gh pr]"
SHORT = {"R": "--repo", "F": "--body-file", "b": "--body", "t": "--title", "B": "--base", "H": "--head",
         "a": "--assignee", "l": "--label", "m": "--milestone", "p": "--project", "r": "--reviewer", "T": "--template",
         "d": "--draft", "f": "--fill"}
VALUE = {"--repo", "--body-file", "--body", "--title", "--base", "--head", "--assignee", "--label", "--milestone",
         "--project", "--reviewer", "--template", "--add-assignee", "--add-label", "--add-project", "--add-reviewer",
         "--remove-assignee", "--remove-label", "--remove-project", "--remove-reviewer"}
FORM = {
    "create": {"--repo", "--body-file", "--body", "--title", "--base", "--head", "--assignee", "--label", "--milestone",
               "--project", "--reviewer", "--template", "--draft", "--fill", "--fill-first", "--fill-verbose",
               "--no-maintainer-edit", "--dry-run"},
    "edit": {"--repo", "--body-file", "--body", "--title", "--base", "--milestone", "--add-assignee", "--add-label",
             "--add-project", "--add-reviewer", "--remove-assignee", "--remove-label", "--remove-project",
             "--remove-reviewer", "--remove-milestone"},
    "comment": {"--repo", "--body-file", "--body", "--edit-last", "--delete-last", "--create-if-none", "--yes"},
    "ready": {"--repo", "--undo"},
}
SEL = re.compile(r"[1-9][0-9]{0,8}|[A-Za-z0-9][A-Za-z0-9_.-]{0,99}(?:/[A-Za-z0-9][A-Za-z0-9_.-]{0,99})*")
PROTECTED = {"main", "master"}
BODY_MAX = 256 * 1024


class PrRefuse(Exception):
    pass


def _env():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GH_") and (not k.startswith("GIT_") or k in ENV_KEEP) and k not in ENV_DROP}
    env["PATH"] = GH_PATH
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _parse(sub, args):
    """[(флаг, значение|None)] и позиционные; отказ — PrRefuse (пункты 2–5 Д2)."""
    flags, pos, k = [], [], 0
    while k < len(args):
        a, k = args[k], k + 1
        if a.startswith("--"):
            flag, eq, val = a.partition("=")
            if flag == "--":
                raise PrRefuse("«--» не принимается: позиционный — номер PR или ветка")
        elif a.startswith("-") and len(a) > 1:
            if a[1] not in SHORT:
                raise PrRefuse(f"флаг {a} не из таблицы формы gh pr {sub}")
            flag, val = SHORT[a[1]], a[2:]
            if flag in VALUE:
                val = val[1:] if val.startswith("=") else val
                eq = "=" if val else ""
            elif val:
                raise PrRefuse(f"флаг {a}: склеенные короткие флаги — раздельно")
            else:
                eq = ""
        else:
            if "://" in a or "#" in a or ".." in a or not SEL.fullmatch(a):
                raise PrRefuse(f"«{a}»: позиционный — только номер PR или имя ветки (адрес и owner/repo#N — нет)")
            pos.append(a)
            continue
        if flag not in FORM[sub]:
            raise PrRefuse(f"флаг {flag} не из таблицы формы gh pr {sub}")
        if flag in VALUE:
            if not eq:
                if k >= len(args):
                    raise PrRefuse(f"флаг {flag} без значения в конце команды")
                val, k = args[k], k + 1
            if flag in ("--repo", "--body-file") and val.startswith("-"):
                raise PrRefuse(f"значение {flag} не может начинаться с «-» ({val})")
            flags.append((flag, val))
        elif eq:
            raise PrRefuse(f"флаг {flag} без значения, а дано «{a}»")
        else:
            flags.append((flag, None))
    if len(pos) > (0 if sub == "create" else 1):
        raise PrRefuse(f"лишние слова {' '.join(pos)}: {USAGE}")
    return flags, pos


def _policy():
    try:
        with open(os.path.join(P.HOME, ".claude", "pantheon", "policy.toml"), "rb") as fh:
            return P.tomllib.load(fh)
    except (OSError, ValueError):
        return {}


def _private():
    return [os.path.realpath(os.path.expanduser(p)) for p in P.private_conf(_policy())["paths"]]


def _inside(p, roots):
    return any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots)


def _personal():
    """Окно с личным (пункт 8): координатор из [private] coordinators или личная папка внутри папки окна."""
    win = os.environ.get("PANTHEON_WINDOW") or ""
    if not win:
        return False
    if win in P.private_conf(_policy())["coordinators"]:
        return True
    doms = (P.read_json(P.path("domains.json"), {}) or {}).get("domains") or {}
    dirs = doms.get(win) if isinstance(doms, dict) else None
    folders = [os.path.realpath(os.path.expanduser(d)) for d in (dirs if isinstance(dirs, list) else [])
               if isinstance(d, str)]
    return any(_inside(x, folders) for x in _private())


def _body(f, cwd, top):
    """Текст файла --body-file (пункт 6) — его читает команда, gh путь не получает."""
    if f == "-" or re.search(r"[*?\[{]", f):
        raise PrRefuse(f"--body-file {f}: шаблон и «-» (stdin) не принимаются — имя файла целиком")
    full = os.path.realpath(os.path.join(cwd, os.path.expanduser(f)))
    if _inside(full, _private()) or ".git" in full.split(os.sep):
        raise PrRefuse(f"--body-file {f}: личное ([private] policy.toml) и файлы из .git на GitHub не выносятся")
    tmp = [os.path.realpath(p) for p in (os.environ.get("TMPDIR", ""), "/tmp", "/private/tmp") if p]
    if not _inside(full, tmp + [top]):
        raise PrRefuse(f"--body-file {f}: читать можно только из временных папок и своей копии репозитория (realpath)")
    try:
        with open(full, "rb") as fh:
            data = fh.read(BODY_MAX + 1)
    except OSError as e:
        raise PrRefuse(f"--body-file {f} не читается ({type(e).__name__})") from None
    if len(data) > BODY_MAX:
        raise PrRefuse(f"--body-file {f} больше {BODY_MAX // 1024} КБ")
    return data.decode("utf-8", "replace")


def pr_write(sub, args, cwd, capture=False):
    """Проверить и выполнить gh pr <sub> мимо песочницы: CompletedProcess; отказ — PrRefuse."""
    if sub not in FORM:
        raise PrRefuse(USAGE)
    flags, pos = _parse(sub, args)
    if _personal():
        raise PrRefuse(f"gh pr {sub} окну с личным закрыт (SEC-13): PR и комментарий откроет лид или владелец")
    git, slug, why = P.git_window(cwd)
    if git is None:
        raise PrRefuse(why)
    bad = [v for f, v in flags if f == "--repo" and v.lower() != slug.lower()]
    if bad:
        raise PrRefuse(f"-R {bad[0]}: PR только в репозитории origin своей папки ({slug})")
    top = git(["rev-parse", "--show-toplevel"]).stdout.strip()
    cur = git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if not top:
        raise PrRefuse("корень копии не найден (git rev-parse --show-toplevel)")
    val = {f: v for f, v in flags}
    head = val.get("--head", cur) if sub == "create" else (pos[0] if pos else cur)
    base = val.get("--base") if sub == "create" else None
    if sub == "create" and "--head" in val and (head.isdigit() or ".." in head or not SEL.fullmatch(head)):
        raise PrRefuse(f"--head «{head}» — только имя своей ветки (без owner:)")
    if not (sub != "create" and head.isdigit()) and (head in ("", "HEAD") or head.lower() in PROTECTED or head == base):
        raise PrRefuse(f"ветка PR «{head or '?'}» — базовая или не ветка: PR только из своей ветки")
    out = ["gh", "pr", sub, *pos]
    for f, v in flags:
        if f == "--repo":
            continue
        out.append(f if v is None else ("--body=" + _body(v, cwd, top) if f == "--body-file" else f"{f}={v}"))
    out.append("--repo=" + slug)
    return subprocess.run(out, cwd=top, env=_env(), stdout=subprocess.PIPE if capture else None, text=True)


def gh_read(args, cwd):
    """gh pr list|view мимо песочницы с тем же окружением (pantheon batch pr); репозиторий даёт вызывающий (-R)."""
    if args[:2] not in (["pr", "list"], ["pr", "view"]):
        raise PrRefuse("gh_read — только gh pr list|view")
    return subprocess.run(["gh", *args], cwd=cwd, env=_env(), capture_output=True, text=True)


def pr_cmd(rest, cwd=None):
    """pantheon pr create|edit|comment|ready … — код gh, отказ — 2."""
    try:
        if not rest or rest[0] not in FORM:
            raise PrRefuse(USAGE)
        env = sorted(k for k in os.environ if k.startswith("GH_"))
        if env:
            raise PrRefuse(f"без {', '.join(env)} в окружении — репозиторий и хост только из origin своей папки")
        return pr_write(rest[0], rest[1:], cwd or os.getcwd()).returncode
    except PrRefuse as e:
        print(f"pantheon pr: {e}", file=sys.stderr)
        return 2
