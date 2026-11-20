#!/usr/bin/env python3
"""pantheon git push|fetch (metis-0972): git мимо песочницы окна без хуков и конфига папки — 14 путей модели угроз.

Модель — ~/ai/pantheon/directions/metis-pantheon/reviews/threat-model-0972-git-outside.md. На каждый путь — случай и
встроенный мутант: копия lib с откатом защиты, на которой тот же случай проходит (тест краснеет на откате).
- хуки (.git/hooks/pre-push, reference-transaction) — не исполняются: настоящий push в локальный голый remote;
- core.fsmonitor, core.sshCommand, core.hooksPath, core.pager, include и includeIf, credential.*, url.*.insteadOf,
  remote.*.receivepack в конфиге репозитория — отказ 2 до git; флаги -c core.* в команде git;
- gitfile и --separate-git-dir, подменённый .git копии, .git-ссылка — отказ 2; настоящая копия — gitdir копии;
- refs/replace — --no-replace-objects и GIT_NO_REPLACE_OBJECTS=1; alternates — отказ;
- fetch --update-head-ok и назначение в refs/heads (в refspec и в remote.*.fetch) — отказ;
- push X:main, X:heads/main, refs/heads/MAIN, +, удаление, тег, шаблон — отказ; X:heads/feat — refs/heads/feat;
- remote с /./ и чужим хостом, remote-адрес вместо имени — отказ; push в «.», в путь и в remote с локальным url — отказ;
- archive.py (P.git: commit, pull, push ~/ai/pantheon) — хуки и fsmonitor репозитория не исполняются;
- GIT_* окна (GIT_CONFIG_GLOBAL с receivepack) не доходят до git; репозиторий чужого направления — отказ.
Сеть не нужна: копия lib ECHO печатает команду и окружение git вместо запуска, копия EXEC пускает file://.

Запуск: python3 -I plugins/pantheon/tests/test_gitout.py  (код выхода 0 — все прошли)
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311, mkroot  # CLI pantheon — только на Python 3.11+

ROOT = os.path.realpath(mkroot("tmp-gitout-"))
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
results = []
N = [0]


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{str(detail)[-400:]}]"))


def mlib(base, pairs, f="gitout.py"):
    """Копия lib base с заменами в f; каждая замена — ровно одна (иначе мутант не тот)."""
    N[0] += 1
    d = os.path.join(ROOT, f"lib{N[0]}")
    shutil.copytree(base, d, ignore=shutil.ignore_patterns("__pycache__"))
    p = os.path.join(d, f)
    s = open(p, encoding="utf-8").read()
    for old, new in pairs:
        assert s.count(old) == 1, (f, old, s.count(old))
        s = s.replace(old, new)
    open(p, "w", encoding="utf-8").write(s)
    return d


RUN = "    return subprocess.run(cmd, cwd=wt, env=_env()).returncode\n"
ECHO = mlib(LIB, [(RUN, '    print(__import__("json").dumps({"cmd": cmd, "env": _env()}))\n    return 0\n')])
URL_LINE = 'URLS = (re.compile(rf"https://github\\.com/{SEG}/{SEG}/?"), re.compile(rf"(?:ssh://git@github\\.com/|git@github\\.com:){SEG}/{SEG}/?"))'
NET_LINE = '"protocol.allow=never"'
EXEC = mlib(LIB, [(URL_LINE, 'URLS = (re.compile(r"file:///.*"),)'), (NET_LINE, '"protocol.allow=always"')])

genv = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True,
                          env={**os.environ, **genv}).stdout.strip()


home = os.path.join(ROOT, "home")
state = os.path.join(home, ".local", "state", "pantheon")
os.makedirs(state)
json.dump({"domains": {"themis-x": ["~/projects"], "athena-y": ["~/other"]}},
          open(os.path.join(state, "domains.json"), "w"))
env = {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": os.path.join(home, "ai", "pantheon"),
       "PANTHEON_STATE": state, "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "TMPDIR": ROOT, **genv}
GH = "https://github.com/latark/agent-kit.git"


def mkrepo(p, url=GH):
    os.makedirs(p)
    git(p, "init", "-q", "-b", "main")
    open(os.path.join(p, "a.txt"), "w").write("a\n")
    git(p, "add", "a.txt")
    git(p, "commit", "-q", "-m", "init")
    git(p, "remote", "add", "origin", url)
    return p


def cli(cwd, *a, lib=ECHO, extra=None):
    return subprocess.run([PY311, "-I", os.path.join(lib, "run.py"), "git", *a], cwd=cwd,
                          env={**env, **(extra or {})}, capture_output=True, text=True, timeout=120)


def echoed(r):
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


def proj(name, url=GH):
    return mkrepo(os.path.join(home, "projects", name), url)


def both(name, case, lib, mutant):
    """Случай проходит на lib и не проходит на мутанте — тест краснеет на откате."""
    check(name, case(lib))
    check(name + " — мутант (откат) краснеет", not case(mutant))


def refused(cwd, *a):
    return lambda lib: (lambda r: r.returncode == 2 and "pantheon git:" in r.stderr.strip().splitlines()[-1])(
        cli(cwd, *a, lib=lib))


# --- успех и форма команды
base = proj("base")
r = cli(base, "push", "origin", "HEAD:heads/feat")
e = echoed(r)
cmd, genv_seen = e.get("cmd") or [], e.get("env") or {}
check("push: код 0, refs/heads/feat, --no-verify и --no-recurse-submodules", r.returncode == 0
      and cmd[-3:] == ["--no-verify", "origin", "HEAD:refs/heads/feat"] and "--no-recurse-submodules" in cmd, r.stderr)
check("push: --git-dir и --work-tree — настоящие пути основной копии",
      f"--git-dir={os.path.join(base, '.git')}" in cmd and f"--work-tree={base}" in cmd, cmd)
need = ["core.hooksPath=/dev/null", "core.fsmonitor=false", "core.sshCommand=ssh", "core.pager=cat",
        "protocol.allow=never", "protocol.https.allow=always", "protocol.ssh.allow=always"]
check("push: -c core.* и protocol.* перед подкомандой", all(x in cmd[:cmd.index("push")] for x in need), cmd)
check("окружение: фиксированный PATH, NOSYSTEM, без GIT_* окна (кроме автора)", genv_seen.get("PATH", "").startswith(
      "/opt/homebrew") and genv_seen.get("GIT_CONFIG_NOSYSTEM") == "1" and "GIT_CONFIG_GLOBAL" not in genv_seen, genv_seen)
r = cli(base, "fetch")
check("fetch без аргументов — origin, код 0", r.returncode == 0 and echoed(r).get("cmd", [])[-1] == "origin", r.stderr)


def flag_case(flag, mut_pairs):
    def case(lib):
        c = echoed(cli(base, "push", "origin", "HEAD:feat", lib=lib)).get("cmd") or []
        return flag in c
    both(f"флаг {flag} в команде git", case, ECHO, mlib(ECHO, mut_pairs))


# --- 1. хуки: настоящий push в локальный голый remote, pre-push и reference-transaction не исполняются
bare = os.path.join(ROOT, "remote.git")
git(ROOT, "init", "-q", "--bare", bare)
hooked = proj("hooked", "file://" + bare)
MARK = os.path.join(ROOT, "hook-ran")
for h in ("pre-push", "reference-transaction"):
    hp = os.path.join(hooked, ".git", "hooks", h)
    open(hp, "w").write(f"#!/bin/sh\necho {h} >> {MARK}\nexit 0\n")
    os.chmod(hp, 0o755)


def hooks_case(lib):
    if os.path.exists(MARK):
        os.remove(MARK)
    r = cli(hooked, "push", "origin", "HEAD:feat", lib=lib)
    pushed = subprocess.run(["git", "--git-dir", bare, "rev-parse", "-q", "--verify", "refs/heads/feat"],
                            capture_output=True, text=True).returncode == 0
    subprocess.run(["git", "--git-dir", bare, "update-ref", "-d", "refs/heads/feat"], capture_output=True)
    return r.returncode == 0 and pushed and not os.path.exists(MARK)


both("1 хуки: push прошёл, pre-push и reference-transaction не исполнились", hooks_case, EXEC,
     mlib(EXEC, [('"-c", "core.hooksPath=/dev/null", ', "")]))


# --- конфиг репозитория: ключи, которыми git исполняет код — отказ 2 до git
def conf_case(name, entries, bad_part, label):
    p = proj(name)
    for k, v in entries:
        git(p, "config", "--add", k, v)
    both(label, refused(p, "push", "origin", "HEAD:feat"), ECHO, mlib(ECHO, [(bad_part, "")]))


conf_case("fsm", [("core.fsmonitor", f"touch {MARK}")], "|fsmonitor|sshcommand", "2 core.fsmonitor в конфиге — отказ")
flag_case("core.fsmonitor=false", [('"-c", "core.fsmonitor=false", ', "")])
conf_case("sshc", [("core.sshCommand", f"touch {MARK}")], "sshcommand|", "3 core.sshCommand в конфиге — отказ")
flag_case("core.sshCommand=ssh", [('"-c", "core.sshCommand=ssh", ', "")])
conf_case("hpath", [("core.hooksPath", ".husky")], "hookspath|", "4 core.hooksPath в конфиге — отказ")
conf_case("pager", [("core.pager", f"touch {MARK}")], "|pager|gitproxy", "5 core.pager в конфиге — отказ")
flag_case("core.pager=cat", [('"-c", "core.pager=cat", ', "")])
conf_case("incif", [("includeIf.gitdir:/.path", os.path.join(ROOT, "evil.cfg"))], "(?:include|includeif)\\..*|",
          "8 includeIf в конфиге — отказ")
conf_case("inc", [("include.path", os.path.join(ROOT, "evil.cfg"))], "(?:include|includeif)\\..*|",
          "8 include.path в конфиге — отказ")
conf_case("cred", [("credential.helper", f"!touch {MARK}")], "|credential\\..*", "9 credential.helper в конфиге — отказ")
conf_case("insteadof", [("url./tmp/x.insteadOf", "https://github.com/")], "url\\..*\\.(?:insteadof|pushinsteadof)",
          "url.*.insteadOf в конфиге — отказ")
conf_case("recvpack", [("remote.origin.receivepack", f"touch {MARK}")],
          "(?:uploadpack|receivepack|", "remote.*.receivepack в конфиге — отказ")
conf_case("sslverify", [("http.https://github.com/.sslVerify", "false")],
          "|http\\..*", "http.*.sslVerify в конфиге — отказ")
conf_case("resolve", [("http.curloptResolve", "github.com:443:127.0.0.1")],
          "|http\\..*", "http.curloptResolve в конфиге — отказ")
conf_case("cookie", [("http.saveCookies", "true"), ("http.cookieFile", "/tmp/x")],
          "|http\\..*", "http.saveCookies/cookieFile в конфиге — отказ")
conf_case("bundle", [("fetch.bundleURI", "https://example.com/x.bundle")],
          "|fetch\\.bundleuri|extensions\\.partialclone|remote\\..*\\.promisor", "fetch.bundleURI в конфиге — отказ")

# --- 6. gitfile и --separate-git-dir, подменённый .git копии, ссылка
sep_wt = os.path.join(ROOT, "sepwt")
git(ROOT, "init", "-q", "-b", "main", "--separate-git-dir", os.path.join(ROOT, "sep.git"), sep_wt)
open(os.path.join(sep_wt, "a.txt"), "w").write("a\n")
git(sep_wt, "add", "a.txt")
git(sep_wt, "commit", "-q", "-m", "init")
git(sep_wt, "remote", "add", "origin", GH)
FOLLOW = ('    repo = P.wt_repo(os.path.dirname(d))\n    return repo, P.wt_verify_copy(repo, d), os.path.join(repo, ".git"), d\n',
          '    gd = os.path.realpath(open(dotgit).read().split(":", 1)[1].strip())\n    return d, gd, gd, d\n')
FOLLOW_LIB = mlib(ECHO, [FOLLOW])
both("6 --separate-git-dir (gitfile на чужую папку) — отказ", refused(sep_wt, "push", "origin", "HEAD:feat"), ECHO,
     FOLLOW_LIB)
copy = os.path.join(base, ".claude", "worktrees", "c1")
git(base, "worktree", "add", "-q", "-b", "c1", copy)
r = cli(copy, "push", "origin", "HEAD:c1")
check("6 копия репозитория: код 0, --git-dir — её gitdir в .git/worktrees",
      r.returncode == 0 and f"--git-dir={os.path.join(base, '.git', 'worktrees', 'c1')}" in echoed(r).get("cmd", []),
      r.stderr)
open(os.path.join(copy, ".git"), "w").write(f"gitdir: {os.path.join(ROOT, 'sep.git')}\n")
both("6 .git копии подменён на чужую папку git — отказ", refused(copy, "push", "origin", "HEAD:c1"), ECHO, FOLLOW_LIB)
linked = os.path.join(ROOT, "linked")
os.makedirs(linked)
os.symlink(os.path.join(base, ".git"), os.path.join(linked, ".git"))
both("6 .git — ссылка — отказ", refused(linked, "push", "origin", "HEAD:feat"), ECHO,
     mlib(ECHO, [("    if os.path.islink(dotgit):\n", "    if False:\n"), ("        if P.wt_repo(d) != d:\n", "        if False:\n")]))


# --- 7. refs/replace и alternates
def replace_case(lib):
    e = echoed(cli(base, "push", "origin", "HEAD:feat", lib=lib))
    return "--no-replace-objects" in (e.get("cmd") or []) and (e.get("env") or {}).get("GIT_NO_REPLACE_OBJECTS") == "1"


both("7 refs/replace: --no-replace-objects и GIT_NO_REPLACE_OBJECTS=1", replace_case, ECHO,
     mlib(ECHO, [('"git", "--no-replace-objects", f"--git-dir={gitdir}"', '"git", f"--git-dir={gitdir}"'),
                 ('GIT_NO_REPLACE_OBJECTS="1", ', "")]))
alt = proj("alt")
open(os.path.join(alt, ".git", "objects", "info", "alternates"), "w").write(os.path.join(ROOT, "sep.git", "objects"))
both("7 objects/info/alternates — отказ", refused(alt, "push", "origin", "HEAD:feat"), ECHO,
     mlib(ECHO, [('FOREIGN_OBJECTS = ("objects/info/alternates", ', 'FOREIGN_OBJECTS = (')]))

# --- 10. fetch --update-head-ok и назначение в refs/heads
NOFLAGS = mlib(ECHO, [("    if flags:\n", "    if False:\n")])
both("10 fetch --update-head-ok — отказ", refused(base, "fetch", "origin", "--update-head-ok", "main:refs/remotes/x"),
     ECHO, NOFLAGS)
DSTANY = mlib(ECHO, [('    return not dst or dst.startswith(("refs/remotes/", "refs/tags/"))\n', "    return True\n")])
for spec in ("main:main", "main:heads/main", "+main:refs/heads/x"):
    both(f"10 fetch {spec} — отказ", refused(base, "fetch", "origin", spec), ECHO, DSTANY)
r = cli(base, "fetch", "origin", "main:refs/remotes/origin/main")
check("10 fetch main:refs/remotes/origin/main — код 0", r.returncode == 0, r.stderr)
mirror = proj("mirror")
git(mirror, "config", "remote.origin.fetch", "+refs/heads/*:refs/heads/*")
both("10 remote.origin.fetch в refs/heads — отказ и при явном refspec",
     refused(mirror, "fetch", "origin", "main:refs/remotes/origin/main"), ECHO, DSTANY)

# --- 11. push в main мимо шлюза
for spec in ("HEAD:main", "HEAD:refs/heads/main", "HEAD:master", "main"):
    both(f"11 push {spec} — отказ", refused(base, "push", "origin", spec), ECHO,
         mlib(ECHO, [("    if dst.lower() in PROTECTED:\n", "    if False:\n")]))
both("11 push X:heads/main — отказ", refused(base, "push", "origin", "HEAD:heads/main"), ECHO,
     mlib(ECHO, [('    for pre in ("refs/heads/", "heads/"):\n', '    for pre in ("refs/heads/",):\n')]))
both("11 push X:MAIN (регистр) — отказ", refused(base, "push", "origin", "HEAD:MAIN"), ECHO,
     mlib(ECHO, [("    if dst.lower() in PROTECTED:\n", "    if dst in PROTECTED:\n")]))
SRC_CHECK = '    if src != "HEAD" and (".." in src or not BRANCH.fullmatch(src)):\n'
FORCE = [('    if spec.startswith("+"):\n', "    if False:\n"), ('    return f"{src}:refs/heads/{dst}"\n', "    return spec\n"),
         ('    src, colon, dst = spec.partition(":")\n', '    src, colon, dst = spec.lstrip("+").partition(":")\n')]
DELETE = [("    if not src:\n", "    if False:\n"), (SRC_CHECK, SRC_CHECK.replace("if src != ", "if src and src != "))]
for spec, pairs in (("+HEAD:feat", FORCE), (":feat", DELETE)):
    both(f"11 push {spec} — отказ", refused(base, "push", "origin", spec), ECHO, mlib(ECHO, pairs))
for spec in ("HEAD:refs/tags/v1", "HEAD:refs/heads/*", "HEAD", "HEAD:a..b"):
    check(f"11 push {spec} — отказ", refused(base, "push", "origin", spec)(ECHO))
check("11 push без refspec — отказ", refused(base, "push", "origin")(ECHO))

# --- 12. remote с /./ и чужим хостом
WIDE_URL = mlib(ECHO, [('rf"https://github\\.com/{SEG}/{SEG}/?"', 'rf"https://.*"')])
for i, url in enumerate(("https://github.com/latark/./agent-kit", "https://github.com/latark/../x",
                         "https://github.com.evil.io/a/b", "https://github.com/a/b/c", "https://github.com/a/.b")):
    p = proj(f"u{i}", url)
    both(f"12 url {url} — отказ", refused(p, "push", "origin", "HEAD:feat"), ECHO, WIDE_URL)
check("12 адрес вместо имени remote — отказ", refused(base, "push", GH, "HEAD:feat")(ECHO))

# --- 13. push в локальный путь
NOREMOTE = mlib(ECHO, [('    if not REMOTE.fullmatch(remote) or remote.strip(".") == "":\n', "    if not remote:\n"),
                       ("    if not urls:\n", "    if False:\n")])
for rem in (".", "../base", base):
    both(f"13 push в «{os.path.basename(rem) if rem != '.' else '.'}» — отказ", refused(base, "push", rem, "HEAD:feat"),
         ECHO, NOREMOTE)
git(base, "remote", "add", "local", bare)
git(base, "remote", "add", "fileurl", "file://" + bare)
ANYURL = mlib(ECHO, [(URL_LINE, 'URLS = (re.compile(r".*"),)')])
for rem in ("local", "fileurl"):
    both(f"13 remote {rem} с локальным url — отказ", refused(base, "push", rem, "HEAD:feat"), ECHO, ANYURL)

# --- окружение окна и своё направление
GCONF = os.path.join(ROOT, "evil-global.cfg")
open(GCONF, "w").write(f"[remote \"origin\"]\n\treceivepack = touch {MARK}; git-receive-pack\n")


def env_case(lib):
    if os.path.exists(MARK):
        os.remove(MARK)
    r = cli(hooked, "push", "origin", "HEAD:envx", lib=lib, extra={"GIT_CONFIG_GLOBAL": GCONF})
    return r.returncode == 0 and not os.path.exists(MARK)


both("GIT_CONFIG_GLOBAL окна (receivepack) не доходит до git", env_case, EXEC,
     mlib(EXEC, [('if (not k.startswith("GIT_") or k in ENV_KEEP) and k not in ENV_DROP', "if k not in ENV_DROP")]))


def author_case(lib):
    r = cli(hooked, "push", "origin", "HEAD:envy", lib=lib,
            extra={"GIT_AUTHOR_NAME": "an", "GIT_COMMITTER_EMAIL": "ce@t", "GIT_AUTHOR_DATE": "2026-11-03T12:00:00",
                   "GIT_SSH_COMMAND": "touch x", "GIT_ASKPASS": "/tmp/evil"})
    if r.returncode:
        return False
    env = json.loads(r.stdout.strip().splitlines()[-1])["env"]
    return (env.get("GIT_AUTHOR_NAME") == "an" and env.get("GIT_COMMITTER_EMAIL") == "ce@t"
            and env.get("GIT_AUTHOR_DATE") == "2026-11-03T12:00:00"
            and not any(k in env for k in ("GIT_SSH_COMMAND", "GIT_ASKPASS")))


both("GIT_AUTHOR_*/GIT_COMMITTER_* доходят до git, GIT_SSH_COMMAND/GIT_ASKPASS — нет (board_lock)", author_case, ECHO,
     mlib(ECHO, [('(not k.startswith("GIT_") or k in ENV_KEEP) and k not in ENV_DROP', 'not k.startswith("GIT_") and k not in ENV_DROP')]))
r = cli(base, "push", "origin", "HEAD:feat", extra={"PANTHEON_WINDOW": "athena-y"})
check("окно athena-y, репозиторий themis-x — отказ 2", r.returncode == 2 and "направления" in r.stderr, r.stderr)
r = cli(base, "push", "origin", "HEAD:feat", lib=mlib(ECHO, [("        P.wt_own(repo)\n", "")]),
        extra={"PANTHEON_WINDOW": "athena-y"})
check("окно athena-y — мутант без wt_own пропускает (тест краснеет на откате)", r.returncode == 0, r.stderr)

# --- 14. archive.py: P.git ~/ai/pantheon без хуков и fsmonitor
hq = os.path.join(ROOT, "hq.git")
git(ROOT, "init", "-q", "--bare", "-b", "main", hq)
seed = mkrepo(os.path.join(ROOT, "seed"), hq)
git(seed, "push", "-q", "origin", "main")
git(seed, "branch", "-q", "-u", "origin/main")
PROBE = """
import sys
sys.path.insert(0, sys.argv[1])
import pantheon as p
print("rc", p.commit())
"""
HQ_MARK = os.path.join(ROOT, "hq-hook-ran")


def hq_case(lib):
    pan = os.path.join(ROOT, f"pan{N[0]}")
    N[0] += 1
    git(ROOT, "clone", "-q", hq, pan)
    git(pan, "config", "user.name", "t")
    git(pan, "config", "user.email", "t@t")
    git(pan, "config", "core.fsmonitor", os.path.join(pan, ".git", "hooks", "fsm"))
    for h in ("pre-commit", "post-merge", "pre-push", "post-commit", "reference-transaction", "fsm"):
        hp = os.path.join(pan, ".git", "hooks", h)
        open(hp, "w").write(f"#!/bin/sh\necho {h} >> {HQ_MARK}\nexit 0\n")
        os.chmod(hp, 0o755)
    git(seed, "pull", "-q", "--ff-only")  # прошлый прогон (lib или мутант) уже отправил коммит в hq
    open(os.path.join(seed, "b.txt"), "a").write("b\n")
    git(seed, "add", "b.txt")
    git(seed, "commit", "-q", "-m", "seed")
    git(seed, "push", "-q", "origin", "main")
    open(os.path.join(pan, "c.txt"), "w").write("c\n")
    if os.path.exists(HQ_MARK):
        os.remove(HQ_MARK)
    st = os.path.join(ROOT, f"st{N[0]}")
    os.makedirs(st)
    r = subprocess.run([PY311, "-I", "-c", PROBE, lib], capture_output=True, text=True, timeout=120,
                       env={"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pan, "PANTHEON_STATE": st,
                            "PANTHEON_NOTIFY_LOG": os.path.join(ROOT, "notify.log"), "TMPDIR": ROOT})
    merged = subprocess.run(["git", "--git-dir", hq, "log", "--format=%s", "main"], capture_output=True,
                            text=True).stdout
    ok = "rc 0" in r.stdout and "pantheon:" in merged and not os.path.exists(HQ_MARK)
    if not ok:
        print(r.stdout[-300:], r.stderr[-600:], open(HQ_MARK).read() if os.path.exists(HQ_MARK) else "")
    return ok


both("14 archive commit: коммит, pull и push прошли, хуки и fsmonitor не исполнились", hq_case, LIB,
     mlib(LIB, [('f"--work-tree={repo}", *HARD, *args]', 'f"--work-tree={repo}", *args]')]))

print(f"\n{sum(results)}/{len(results)} прошли", flush=True)  # os._exit не сбрасывает буфер stdout
os._exit(0 if all(results) else 1)
