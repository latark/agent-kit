#!/usr/bin/env python3
"""pantheon pr create|edit|comment|ready (metis-1334, план metis-1331 PR-2a): gh pr мимо песочницы окна, проверки Д2 —
в самой команде (lib/pr_out.py). Каждая проверка — случай здесь, и у каждой встроенный мутант: копия lib с выключенной
проверкой пускает опасную форму до gh — тест краснеет на откате.

Запуск: python3 -I plugins/pantheon/tests/test_pr_out.py  (код выхода 0 — все прошли)
"""
import os
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

# корень — не в /tmp: /tmp — разрешённая папка --body-file, а файл «снаружи» должен быть снаружи (на Linux mkdtemp
# даёт /tmp, берём /var/tmp; на macOS — /var/folders)
_base = "/var/tmp" if os.path.realpath(tempfile.gettempdir()).startswith(("/tmp", "/private/tmp")) else None
W = os.path.realpath(tempfile.mkdtemp(prefix="pr-out-test-", dir=_base))
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{str(detail)[:500]}]"))


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


try:
    home, state, view, tmpd, bindir = (os.path.join(W, x) for x in ("home", "state", "view", "tmpd", "bin"))
    for d in (home, state, view, tmpd, bindir, os.path.join(home, ".claude", "pantheon")):
        os.makedirs(d)
    phome = os.path.join(W, "pantheon")
    os.makedirs(phome)
    open(os.path.join(phome, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    open(os.path.join(phome, "directions.toml"), "w", encoding="utf-8").write(
        '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n')
    repo = os.path.join(W, "repo")
    secret = os.path.join(repo, "secret")
    open(os.path.join(home, ".claude", "pantheon", "policy.toml"), "w").write(
        '[merge_repos]\nmetis-pantheon = ["x/y"]\ndemo-other = ["a/b"]\n\n'
        f'[private]\ncoordinators = ["mnemo-brain"]\npaths = ["{secret}"]\n')
    genv = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    os.environ.update(genv)
    subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
    os.makedirs(secret)
    for name, text in (("a.txt", "a\n"), ("body.md", "тело из копии\n"), ("-x", "x\n"),
                       (os.path.join("secret", "s.md"), "личное\n")):
        open(os.path.join(repo, name), "w").write(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "remote", "add", "origin", "https://github.com/x/y.git")
    git(repo, "switch", "-q", "-c", "1334-x")
    tbody = os.path.join(tmpd, "b.md")
    open(tbody, "w").write("тело из временной папки\n")
    outside = os.path.join(W, "outside.md")
    open(outside, "w").write("снаружи\n")

    # поддельный gh: аргументы через NUL в gh.log, окружение — в gh.env; код выхода из файла gh.code (если есть)
    ghlog, ghenv, ghcode = (os.path.join(W, x) for x in ("gh.log", "gh.env", "gh.code"))
    open(os.path.join(bindir, "gh"), "w").write(
        "#!/bin/sh\n"
        f"env > '{ghenv}'\n"
        f"for a in \"$@\"; do printf '%s\\0' \"$a\"; done > '{ghlog}'\n"
        "echo https://github.com/x/y/pull/9\n"
        f"[ -f '{ghcode}' ] && exit \"$(cat '{ghcode}')\"\nexit 0\n")
    os.chmod(os.path.join(bindir, "gh"), 0o755)

    # gh ищется по GH_PATH (постоянная строка), а не по PATH окна: копия lib, где GH_PATH — папка поддельного gh
    GH_FIXED = 'GH_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"'
    GH_TEST_PATH = f"{bindir}:/usr/bin:/bin"
    src = open(os.path.join(LIB, "pr_out.py"), encoding="utf-8").read()
    check("pr_out.py: GH_PATH — постоянная строка, одна", src.count(GH_FIXED) == 1)
    src = src.replace(GH_FIXED, f'GH_PATH = "{GH_TEST_PATH}"')
    GHLIB = os.path.join(W, "lib0")
    shutil.copytree(LIB, GHLIB, ignore=shutil.ignore_patterns("__pycache__"))
    open(os.path.join(GHLIB, "pr_out.py"), "w", encoding="utf-8").write(src)

    def mutant(old, new):
        """Копия lib, где строка old проверки заменена на new (строка должна быть одна)."""
        check(f"самопроверка мутанта: строка одна — {old.strip()[:60]}", src.count(old) == 1)
        d = os.path.join(W, f"lib{len(os.listdir(W))}")
        shutil.copytree(GHLIB, d, ignore=shutil.ignore_patterns("__pycache__"))
        open(os.path.join(d, "pr_out.py"), "w", encoding="utf-8").write(src.replace(old, new))
        return d

    base_env = {"PATH": "/usr/bin:/bin", "HOME": home, "PANTHEON_HOME": phome, "PANTHEON_STATE": state,
                "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
                "PANTHEON_FAKE_IDLE": "0", "TMPDIR": tmpd, **genv}

    def cli(*a, lib=GHLIB, cwd=repo, env=None):
        for f in (ghlog, ghenv, ghcode):
            if os.path.exists(f):
                os.remove(f)
        e = dict(base_env, **(env or {}))
        e = {k: v for k, v in e.items() if v is not None}
        return subprocess.run([PY311, "-I", os.path.join(lib, "run.py"), "pr", *a], cwd=cwd, env=e,
                              capture_output=True, text=True)

    def gh_args():
        return open(ghlog).read().split("\0")[:-1] if os.path.exists(ghlog) else None

    def refused(r):
        return r.returncode == 2 and gh_args() is None and "pantheon pr:" in (r.stderr.strip().splitlines() or [""])[-1]

    def case(name, args, mut=None, env=None, cwd=repo, why=""):
        """Отказ кодом 2 до gh; с мутантом (old, new) — та же команда доходит до gh (мутант убит)."""
        r = cli(*args, env=env, cwd=cwd)
        check(f"отказ: {name}", refused(r) and why in r.stderr, r.stderr)
        if mut:
            r = cli(*args, lib=mutant(*mut), env=env, cwd=cwd)
            check(f"мутант убит: {name} — без проверки доходит до gh", gh_args() is not None, r.stderr)

    # можно: форма gh — разобранные флаги `--флаг=значение`, репозиторий из origin, тело файла — текстом
    r = cli("create", "--base", "main", "--title", "Заголовок с пробелами", "-F", tbody, "--draft")
    check("create: код 0, gh получил разобранные флаги, --body= с текстом файла и --repo=x/y последним",
          r.returncode == 0 and gh_args() == ["pr", "create", "--base=main", "--title=Заголовок с пробелами",
                                               "--body=тело из временной папки\n", "--draft", "--repo=x/y"],
          f"{gh_args()} {r.stderr}")
    r = cli("comment", "5", "--body-file=body.md", "-R", "X/Y")
    check("comment: -R того же репозитория (регистр не важен), файл своей копии — код 0",
          r.returncode == 0 and gh_args() == ["pr", "comment", "5", "--body=тело из копии\n", "--repo=x/y"],
          f"{gh_args()} {r.stderr}")
    r = cli("edit", "--title=Новый", "-b", "текст")
    check("edit по текущей ветке: короткие флаги развёрнуты", r.returncode == 0
          and gh_args() == ["pr", "edit", "--title=Новый", "--body=текст", "--repo=x/y"], f"{gh_args()} {r.stderr}")
    r = cli("ready", "1334-x", "--undo")
    check("ready по имени ветки — код 0", r.returncode == 0 and gh_args() == ["pr", "ready", "1334-x", "--undo", "--repo=x/y"],
          f"{gh_args()} {r.stderr}")
    open(ghcode, "w").write("3")
    r = subprocess.run([PY311, "-I", os.path.join(GHLIB, "run.py"), "pr", "ready", "5"], cwd=repo, env=base_env,
                       capture_output=True, text=True)
    check("код gh передаётся наружу (3)", r.returncode == 3, r.stderr)

    # окружение gh: без GH_*, GIT_* окна, EDITOR и прочих; PATH — GH_PATH
    r = cli("ready", "5", env={"EDITOR": "evil", "VISUAL": "evil", "BROWSER": "evil", "PAGER": "evil",
                               "XDG_CONFIG_HOME": W, "GIT_DIR": "/nonexistent", "GIT_CONFIG_GLOBAL": outside})
    genv_out = dict(ln.split("=", 1) for ln in open(ghenv).read().splitlines() if "=" in ln) if os.path.exists(ghenv) else {}
    check("окружение gh: нет EDITOR, VISUAL, BROWSER, PAGER, XDG_CONFIG_HOME, GIT_DIR, GIT_CONFIG_GLOBAL; PATH = GH_PATH",
          r.returncode == 0 and genv_out.get("PATH") == GH_TEST_PATH and not any(
              k in genv_out for k in ("EDITOR", "VISUAL", "BROWSER", "PAGER", "XDG_CONFIG_HOME", "GIT_DIR",
                                      "GIT_CONFIG_GLOBAL")), f"{r.stderr} {genv_out.get('PATH')}")
    m = mutant('    env["PATH"] = GH_PATH\n', "")
    r = cli("ready", "5", lib=m, env={"PATH": f"{bindir}:/usr/bin:/bin"})
    genv_out = dict(ln.split("=", 1) for ln in open(ghenv).read().splitlines() if "=" in ln) if os.path.exists(ghenv) else {}
    check("мутант убит: без PATH = GH_PATH gh получает PATH окна", genv_out.get("PATH") != GH_TEST_PATH, r.stderr)
    m = mutant('           if not k.startswith("GH_") and (not k.startswith("GIT_") or k in ENV_KEEP) and k not in ENV_DROP}',
               "           if True}")
    r = cli("ready", "5", lib=m, env={"EDITOR": "evil"})
    check("мутант убит: без чистки окружения EDITOR доходит до gh",
          os.path.exists(ghenv) and "EDITOR=evil" in open(ghenv).read(), r.stderr)

    # 1. GH_* в окружении
    case("GH_REPO в окружении", ["ready", "5"], env={"GH_REPO": "evil/x"}, why="GH_REPO",
         mut=("        if env:\n            raise PrRefuse(f\"без", "        if False:\n            raise PrRefuse(f\"без"))
    case("GH_HOST в окружении", ["comment", "5", "-b", "x"], env={"GH_HOST": "evil.example"}, why="GH_HOST")
    # 2, 4. флаги только из таблицы формы: --hostname, --editor, --web, -e, -w, чужой флаг подкоманды
    flag_mut = ("        if flag not in FORM[sub]:\n", "        if False:\n")
    case("--hostname", ["comment", "5", "--hostname", "evil.example", "-b", "x"], why="--hostname")
    case("--web", ["create", "--web"], mut=flag_mut)
    case("--editor", ["edit", "5", "--editor"], mut=flag_mut)
    case("--base у comment", ["comment", "5", "--base", "main", "-b", "x"], mut=flag_mut)
    case("-e (короткий флаг не из таблицы)", ["comment", "5", "-e"], why="-e")
    case("-w", ["create", "-w"], why="-w")
    case("склеенные короткие флаги -dw", ["create", "-dw"], why="склеенные")
    case("значение булева флага --draft=1", ["create", "--draft=1"], why="без значения")
    case("флаг без значения в конце", ["comment", "5", "--body"], why="без значения")
    case("«--»", ["comment", "--", "5"], why="«--»")
    case("значение -F начинается с «-»", ["comment", "5", "-F", "-x"], why="начинаться с «-»",
         mut=('            if flag in ("--repo", "--body-file") and val.startswith("-"):\n', "            if False:\n"))
    case("-F - (stdin)", ["comment", "5", "--body-file=-"], why="«-»")
    # 3. до подкоманды — ничего
    case("флаг до подкоманды", ["-R", "x/y", "comment", "5", "-b", "x"])
    case("неизвестная подкоманда merge", ["merge", "5"])
    case("close — не в этом PR (PR-2b)", ["close", "5"])
    # 5. позиционный — номер PR или ветка
    pos_mut = ('            if "://" in a or "#" in a or ".." in a or not SEL.fullmatch(a):\n', "            if False:\n")
    case("адрес PR позиционным", ["comment", "https://github.com/evil/x/pull/1", "-b", "x"], mut=pos_mut, why="адрес")
    case("owner/repo#N позиционным", ["ready", "evil/x#1"], mut=pos_mut)
    case("ветка с «..»", ["ready", "a..b"], mut=pos_mut)
    case("позиционный у create", ["create", "1334-x"], why="лишние",
         mut=('    if len(pos) > (0 if sub == "create" else 1):\n', '    if len(pos) > (1 if sub == "create" else 1):\n'))
    case("два позиционных", ["ready", "5", "6"], why="лишние")
    # 6. --body-file
    open(os.path.join(tmpd, "*.md"), "w").write("шаблон\n")  # файл с таким именем есть: без проверки он прочитался бы
    case("--body-file шаблоном", ["comment", "5", "-F", os.path.join(tmpd, "*.md")], why="шаблон",
         mut=('    if f == "-" or re.search(r"[*?\\[{]", f):\n', '    if f == "-":\n'))
    priv_mut = ('    if _inside(full, _private()) or ".git" in full.split(os.sep):\n', "    if False:\n")
    case("--body-file из личного ([private] paths)", ["comment", "5", "-F", "secret/s.md"], mut=priv_mut, why="личное")
    case("--body-file из .git", ["comment", "5", "-F", ".git/HEAD"], mut=priv_mut, why=".git")
    case("--body-file вне временных папок и своей копии", ["comment", "5", "-F", outside], why="только из временных",
         mut=("    if not _inside(full, tmp + [top]):\n", "    if False:\n"))
    os.symlink(outside, os.path.join(tmpd, "link.md"))
    case("--body-file — ссылка наружу (realpath)", ["comment", "5", "-F", os.path.join(tmpd, "link.md")],
         why="только из временных")
    case("--body-file нет файла", ["comment", "5", "-F", "nope.md"], why="не читается")
    r = cli("comment", "5", "-F", tbody)
    check("--body-file: gh получает текст, а не путь", r.returncode == 0 and tbody not in "\0".join(gh_args() or [])
          and "--body=тело из временной папки\n" in (gh_args() or []), f"{gh_args()} {r.stderr}")
    m = mutant('("--body=" + _body(v, cwd, top) if f == "--body-file" else f"{f}={v}")', 'f"{f}={v}"')
    r = cli("comment", "5", "-F", tbody, lib=m)
    check("мутант убит: без чтения файла командой gh получает путь", tbody in "\0".join(gh_args() or []), r.stderr)
    # 7. репозиторий — только из origin своей папки
    case("-R чужой", ["comment", "5", "-R", "evil/x", "-b", "x"], why="только в репозитории origin",
         mut=('    bad = [v for f, v in flags if f == "--repo" and v.lower() != slug.lower()]\n', "    bad = []\n"))
    case("-R=чужой", ["ready", "5", "--repo=a/b"], why="только в репозитории origin")
    m = mutant('    out.append("--repo=" + slug)\n', "")
    r = cli("ready", "5", lib=m)
    check("мутант убит: без --repo=slug gh выбрал бы репозиторий сам", (gh_args() or [""])[-1] != "--repo=x/y", gh_args())
    git(repo, "remote", "set-url", "origin", "https://github.com/evil/other.git")
    case("origin не из [merge_repos]", ["ready", "5"], why="merge_repos")
    git(repo, "remote", "set-url", "origin", W + "/origin.git")
    case("origin — локальный путь, не github.com", ["ready", "5"], why="github.com")
    git(repo, "remote", "set-url", "origin", "https://github.com/x/y.git")
    # 8. окно с личным
    pers_mut = ("    if _personal():\n", "    if False:\n")
    case("окно mnemo-brain ([private] coordinators)", ["comment", "5", "-b", "x"], env={"PANTHEON_WINDOW": "mnemo-brain"},
         mut=pers_mut, why="личным")
    open(os.path.join(state, "domains.json"), "w").write('{"domains": {"metis-pantheon": ["%s"]}}' % repo)
    case("окно, в папке которого личное ([private] paths)", ["ready", "5"], env={"PANTHEON_WINDOW": "metis-pantheon"},
         mut=pers_mut, why="личным")
    os.remove(os.path.join(state, "domains.json"))
    # ветка PR — не базовая
    br_mut = ('    if not (sub != "create" and head.isdigit()) and (head in ("", "HEAD") or head.lower() in PROTECTED '
              'or head == base):\n', "    if False:\n")
    case("create --head main", ["create", "--head", "main", "-t", "x", "-b", "y"], mut=br_mut, why="базовая")
    case("create: --head равна --base", ["create", "--base", "1334-x", "-t", "x", "-b", "y"], mut=br_mut, why="базовая")
    case("comment по ветке main", ["comment", "main", "-b", "x"], mut=br_mut, why="базовая")
    case("create --head owner:ветка", ["create", "--head", "evil:1334-x", "-t", "x", "-b", "y"], why="своей ветки",
         mut=('    if sub == "create" and "--head" in val and (head.isdigit() or ".." in head or not SEL.fullmatch(head)):\n',
              "    if False:\n"))
    git(repo, "switch", "-q", "main")
    case("create из main (текущая ветка)", ["create", "-t", "x", "-b", "y"], mut=br_mut, why="базовая")
    case("edit без номера на main", ["edit", "-t", "x"], why="базовая")
    r = cli("comment", "5", "-b", "x")
    check("comment по номеру с main — можно (номер — не ветка)", r.returncode == 0 and gh_args() is not None, r.stderr)
    git(repo, "switch", "-q", "1334-x")
finally:
    shutil.rmtree(W, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if results and all(results) else 1)
