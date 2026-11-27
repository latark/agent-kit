#!/usr/bin/env python3
"""pantheon pr create|edit|comment|ready (metis-1334, план metis-1331 PR-2a), close|reopen|update-branch (metis-1335,
PR-2b): gh pr мимо песочницы окна, проверки Д2 —
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
from _py311 import PY311, mkroot  # CLI pantheon — только на Python 3.11+

_TMP = ("/tmp", "/private/tmp")
# корень — mkroot (AGENTS.md «Как проверять»): в окне роли песочница режет `.git/hooks` вне своего TMPDIR. Первым —
# /var/tmp, если tempdir в /tmp (Linux); в окне корень ляжет в /tmp/claude-<uid>
_base = "/var/tmp" if os.path.realpath(tempfile.gettempdir()).startswith(_TMP) else None
W = os.path.realpath(mkroot("pr-out-test-", first=_base))


def _outside_root():
    """Папка файла «снаружи»: не в /tmp — /tmp разрешена --body-file. Только простой файл, git не нужен: годится и
    PANTHEON_TMP окна (кэш окна), где `.git/hooks` закрыт. Ни одной — отказ последней строкой."""
    for b in (W, _base, os.environ.get("PANTHEON_TMP"), tempfile.gettempdir()):
        if b and os.path.isdir(b) and not os.path.realpath(b).startswith(_TMP):
            try:
                return os.path.realpath(tempfile.mkdtemp(prefix="pr-out-outside-", dir=b))
            except OSError:
                continue
    shutil.rmtree(W, ignore_errors=True)
    sys.exit("test_pr_out: нет папки вне /tmp для файла «снаружи» — задай PANTHEON_TMP или TMPDIR вне /tmp")


OUT = _outside_root()
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
    outside = os.path.join(OUT, "outside.md")
    open(outside, "w").write("снаружи\n")

    # поддельный gh: аргументы через NUL в gh.log, окружение — в gh.env; код выхода из файла gh.code (если есть)
    ghlog, ghenv, ghcode = (os.path.join(W, x) for x in ("gh.log", "gh.env", "gh.code"))
    ghview, ghhead = os.path.join(W, "gh.view"), os.path.join(W, "gh.head")
    open(ghhead, "w").write("1334-x\n")
    open(os.path.join(bindir, "gh"), "w").write(
        "#!/bin/sh\n"
        # metis-1348: `gh pr view` (ветка PR для update-branch) — ответ из gh.head, код из gh.viewcode; журнал не трогает
        f"if [ \"$1 $2\" = 'pr view' ]; then echo \"$@\" > '{ghview}'; cat '{ghhead}'; "
        f"[ -f '{ghview}.code' ] && exit \"$(cat '{ghview}.code')\"; exit 0; fi\n"
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

    mutants = []

    def mutant(old, new):
        """Копия lib, где строка old проверки заменена на new (строка должна быть одна)."""
        check(f"самопроверка мутанта: строка одна — {old.strip()[:60]}", src.count(old) == 1)
        # номер — свой счётчик, а не число файлов в W: gh.log, gh.env, gh.code появляются и исчезают между вызовами
        mutants.append(old)
        d = os.path.join(W, f"mut{len(mutants)}")
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
    # PATH окна — другая строка, чем GH_TEST_PATH (иначе мутант неотличим), но с поддельным gh первым
    win_path = f"{bindir}:/bin:/usr/bin"
    r = cli("ready", "5", lib=m, env={"PATH": win_path})
    genv_out = dict(ln.split("=", 1) for ln in open(ghenv).read().splitlines() if "=" in ln) if os.path.exists(ghenv) else {}
    check("мутант убит: без PATH = GH_PATH gh получает PATH окна", genv_out.get("PATH") == win_path,
          f"{r.stderr} {genv_out.get('PATH')}")
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
    case("неизвестная подкоманда update (есть только update-branch)", ["update", "5"])
    case("неизвестная подкоманда review", ["review", "5", "--approve"])
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
    priv_line = '    if _inside(full, _private(), _key) or any(_key(c) == ".git" for c in full.split(os.sep)):\n'
    priv_mut = (priv_line, "    if False:\n")
    case("--body-file из личного ([private] paths)", ["comment", "5", "-F", "secret/s.md"], mut=priv_mut, why="личное")
    case("--body-file из .git", ["comment", "5", "-F", ".git/HEAD"], mut=priv_mut, why=".git")
    # metis-1334: APFS не различает регистр, realpath его не сводит — `.GIT/config` это `.git/config`. На
    # регистрозависимой ФС (Linux CI) файлы свои, чтобы без свёртки команда дошла до gh, а не упала на «не читается»
    for rel in (os.path.join(".GIT", "HEAD"), os.path.join(".Git", "config"), os.path.join("SECRET", "s.md")):
        if not os.path.exists(os.path.join(repo, rel)):
            os.makedirs(os.path.join(repo, os.path.dirname(rel)), exist_ok=True)
            open(os.path.join(repo, rel), "w").write("x\n")
    fold_mut = ('    return unicodedata.normalize("NFC", p).casefold()\n', "    return p\n")
    undo_mut = (priv_line, '    if _inside(full, _private()) or ".git" in full.split(os.sep):\n')  # откат правки
    for name, rel, why in ((".GIT/HEAD", os.path.join(".GIT", "HEAD"), ".git"),
                           (".Git/config", os.path.join(".Git", "config"), ".git"),
                           ("личное другим регистром", os.path.join("SECRET", "s.md"), "личное")):
        case(f"--body-file {name} (регистр)", ["comment", "5", "-F", rel], mut=fold_mut, why=why)
        case(f"--body-file {name} (регистр, откат)", ["comment", "5", "-F", rel], mut=undo_mut, why=why)
    case("--body-file вне своего $TMPDIR и своей копии", ["comment", "5", "-F", outside], why="только из своего",
         mut=("    if not _inside(full, tmp + [top]):\n", "    if False:\n"))
    os.symlink(outside, os.path.join(tmpd, "link.md"))
    case("--body-file — ссылка наружу (realpath)", ["comment", "5", "-F", os.path.join(tmpd, "link.md")],
         why="только из своего")
    # metis-1348: общий /tmp и /private/tmp — чужие сессии; файл там вне своего TMPDIR (и вне копии) не читается
    shared = os.path.join("/tmp", f"pr-out-shared-{os.getpid()}.md")
    try:
        open(shared, "w").write("чужое в /tmp\n")
    except OSError:
        shared = None
    if shared and not os.path.realpath(shared).startswith(W + os.sep):
        tmp_line = '    tmp = [os.path.realpath(p) for p in (os.environ.get("TMPDIR", ""),) if p]\n'
        tmp_mut = (tmp_line, '    tmp = [os.path.realpath(p) for p in (os.environ.get("TMPDIR", ""), "/tmp", "/private/tmp") if p]\n')
        case("--body-file из общего /tmp (не свой TMPDIR)", ["comment", "5", "-F", shared], mut=tmp_mut,
             why="только из своего")
        os.remove(shared)
    # metis-1348: denyRead сборки окна (settings/<окно>.json): путь внутри своего TMPDIR, но закрытый окну, не читается
    os.makedirs(os.path.join(tmpd, "deny-me"))
    os.makedirs(os.path.join(state, "settings"))
    closed_f = os.path.join(tmpd, "deny-me", "c.md")
    open(closed_f, "w").write("закрыто\n")
    open(os.path.join(tmpd, "ok.md"), "w").write("можно\n")
    deny_forms = {"win-abs": [f"{tmpd}/deny-me/**"], "win-dir": [f"{tmpd}/deny-me"], "win-glob": [f"{tmpd}/deny-*/*"],
                  "win-name": ["deny-me"]}
    deny_mut = ("    if _read_closed(full):\n", "    if False:\n")
    import json
    for win, items in deny_forms.items():
        json.dump({"sandbox": {"filesystem": {"denyRead": items}}}, open(os.path.join(state, "settings", win + ".json"), "w"))
        case(f"--body-file закрыт denyRead окна ({win}: {items[0][-24:]})", ["comment", "5", "-F", closed_f],
             env={"PANTHEON_WINDOW": win}, mut=deny_mut, why="закрыт окну на чтение")
        r = cli("comment", "5", "-F", os.path.join(tmpd, "ok.md"), env={"PANTHEON_WINDOW": win})
        check(f"--body-file вне denyRead окна ({win}) — код 0", r.returncode == 0, r.stderr)
    r = cli("comment", "5", "-F", closed_f, env={"PANTHEON_WINDOW": "win-none"})
    check("окно без файла настроек: закрытого нет — код 0", r.returncode == 0, r.stderr)
    # metis-1348: правило Read(.env*) из permissions.deny управляемых настроек (MANAGED_FILE) закрывает файл так же,
    # как denyRead окна: без этого `pantheon pr comment -F .env.local` отправлял бы файл на GitHub
    managed = os.path.join(W, "managed-settings.json")
    json.dump({"permissions": {"deny": ["Read(.env*)", "Read(./secrets/**)", "Bash(rm:*)"]}}, open(managed, "w"))
    man_old = "MANAGED_FILE = P.MANAGED"
    man_rule = "            items += _read_rule(m.group(1), top) if m else []\n"
    check("самопроверка: MANAGED_FILE и разбор Read(...) — по одной строке", src.count(man_old) == 1 and src.count(man_rule) == 1)

    def managed_lib(name, rule_new=None):
        """Копия lib, где управляемые настройки — managed-settings.json теста; rule_new — мутант разбора правил Read(...)."""
        text = src.replace(man_old, f"MANAGED_FILE = {managed!r}")
        d = os.path.join(W, name)
        shutil.copytree(GHLIB, d, ignore=shutil.ignore_patterns("__pycache__"))
        open(os.path.join(d, "pr_out.py"), "w", encoding="utf-8").write(text if rule_new is None else text.replace(man_rule, rule_new))
        return d

    mlib, mlib_mut = managed_lib("lib-managed"), managed_lib("lib-managed-mut", "            items += []\n")
    open(os.path.join(repo, ".env.local"), "w").write("KEY=secret\n")
    for flag in ("-F", "--body-file"):
        r = cli("comment", "5", flag, ".env.local", lib=mlib)
        check(f"managed deny Read(.env*): {flag} .env.local — отказ", refused(r) and "закрыт окну на чтение" in r.stderr, r.stderr)
        r = cli("comment", "5", flag, ".env.local", lib=mlib_mut)
        check(f"мутант убит: {flag} .env.local без разбора Read(...) доходит до gh", gh_args() is not None, r.stderr)
    r = cli("comment", "5", "-F", "body.md", lib=mlib)
    check("managed deny Read(.env*): обычный файл копии — код 0", r.returncode == 0, r.stderr)
    os.remove(os.path.join(repo, ".env.local"))
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
    for sub in ("close", "reopen", "update-branch"):  # metis-1335: без номера на main — ветка PR базовая
        case(f"{sub} без номера на main", [sub], mut=br_mut, why="базовая")
    r = cli("close", "5")
    check("close по номеру с main — можно", r.returncode == 0 and gh_args() == ["pr", "close", "5", "--repo=x/y"],
          f"{gh_args()} {r.stderr}")
    git(repo, "switch", "-q", "1334-x")

    # metis-1335 (план metis-1331 PR-2b): close, reopen, update-branch — по образцу create/edit
    r = cli("close", "5", "-c", "дубль #6")
    check("close: -c — это --comment (своя таблица коротких флагов), код 0",
          r.returncode == 0 and gh_args() == ["pr", "close", "5", "--comment=дубль #6", "--repo=x/y"],
          f"{gh_args()} {r.stderr}")
    m = mutant("            short = SHORT_SUB.get(sub, SHORT)\n", "            short = SHORT\n")
    r = cli("close", "5", "-c", "дубль #6", lib=m)
    check("мутант убит: без SHORT_SUB -c у close не узнан — отказ до gh", refused(r), r.stderr)
    r = cli("reopen", "1334-x", "--comment=снова")
    check("reopen по ветке с --comment=… — код 0",
          r.returncode == 0 and gh_args() == ["pr", "reopen", "1334-x", "--comment=снова", "--repo=x/y"],
          f"{gh_args()} {r.stderr}")
    m = mutant('"--remove-assignee", "--remove-label", "--remove-project", "--remove-reviewer", "--comment"}',
               '"--remove-assignee", "--remove-label", "--remove-project", "--remove-reviewer"}')
    r = cli("reopen", "1334-x", "--comment=снова", lib=m)
    check("мутант убит: --comment не в VALUE — «--comment=…» отказ (булев флаг со значением)", refused(r), r.stderr)
    r = cli("update-branch", "5", "--rebase", "-R", "x/y")
    check("update-branch с --rebase и своим -R — код 0",
          r.returncode == 0 and gh_args() == ["pr", "update-branch", "5", "--rebase", "--repo=x/y"],
          f"{gh_args()} {r.stderr}")
    check("update-branch по номеру: gh pr view спрошен по тому же репозиторию",
          os.path.exists(ghview) and open(ghview).read().split() == ["pr", "view", "5", "--repo=x/y", "--json",
                                                                       "headRefName", "--jq", ".headRefName"],
          open(ghview).read() if os.path.exists(ghview) else "нет вызова view")
    # metis-1348: update-branch по номеру — ветка PR main/master отказ; сбой view — отказ; мутант — доходит до gh
    view_mut = ("        if pr_head.lower() in PROTECTED:\n", "        if False:\n")
    for hd in ("main", "Master"):
        open(ghhead, "w").write(hd + "\n")
        case(f"update-branch 5, у PR ветка {hd}", ["update-branch", "5"], mut=view_mut, why="базовая")
    open(ghhead, "w").write("\n")
    case("update-branch 5, gh pr view без ветки", ["update-branch", "5"], why="ветку PR не узнать",
         mut=('        if view.returncode != 0 or not pr_head:\n', "        if False:\n"))
    open(ghhead, "w").write("1334-x\n")
    open(ghview + ".code", "w").write("1")
    case("update-branch 5, gh pr view упал (код 1) при ветке в выводе — отказ", ["update-branch", "5"],
         why="ветку PR не узнать", mut=('        if view.returncode != 0 or not pr_head:\n', "        if not pr_head:\n"))
    os.remove(ghview + ".code")
    open(ghhead, "w").write("1334-x\n")
    os.remove(ghview)
    r = cli("update-branch", "1334-x")
    check("update-branch по имени ветки — код 0, gh pr view не зовётся", r.returncode == 0 and not os.path.exists(ghview),
          r.stderr)
    r = cli("update-branch")
    check("update-branch по текущей ветке (не базовой) — код 0",
          r.returncode == 0 and gh_args() == ["pr", "update-branch", "--repo=x/y"], f"{gh_args()} {r.stderr}")
    case("close -d (--delete-branch — удаление ветки необратимо)", ["close", "5", "-d"], mut=flag_mut,
         why="--delete-branch")
    case("close --delete-branch", ["close", "5", "--delete-branch"], mut=flag_mut, why="--delete-branch")
    case("close --body (не из таблицы close)", ["close", "5", "--body", "x"], mut=flag_mut, why="не из таблицы")
    case("close -b (короткий флаг create)", ["close", "5", "-b", "x"], why="-b")
    case("update-branch --comment", ["update-branch", "5", "--comment", "x"], mut=flag_mut, why="не из таблицы")
    case("update-branch -c", ["update-branch", "5", "-c", "x"], why="-c")
    case("reopen -d", ["reopen", "5", "-d"], why="-d")
    case("close -R чужой", ["close", "5", "-R", "evil/x"], why="только в репозитории origin")
    case("close по ветке main", ["close", "main"], mut=br_mut, why="базовая")
    case("reopen по ветке master", ["reopen", "master"], mut=br_mut, why="базовая")
    case("update-branch: адрес PR позиционным", ["update-branch", "https://github.com/evil/x/pull/1"], mut=pos_mut,
         why="адрес")
    case("close: два позиционных", ["close", "5", "6"], why="лишние")
    case("close в окне mnemo-brain", ["close", "5"], env={"PANTHEON_WINDOW": "mnemo-brain"}, mut=pers_mut, why="личным")
    case("close с GH_REPO в окружении", ["close", "5"], env={"GH_REPO": "evil/x"}, why="GH_REPO")
finally:
    shutil.rmtree(W, ignore_errors=True)
    if not OUT.startswith(W + os.sep):
        shutil.rmtree(OUT, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if results and all(results) else 1)
