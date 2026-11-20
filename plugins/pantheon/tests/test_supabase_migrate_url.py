#!/usr/bin/env python3
"""`pantheon supabase migrate` в окне — в git идёт только канонический адрес GitHub (metis-1295, круг 5 argus #521).

Запуск: python3 -I plugins/pantheon/tests/test_supabase_migrate_url.py  (код выхода 0 — все прошли)
Находка: `https://evil-host.invalid?@github.com/latark/x.git` разбор GITHUB читал как github.com/latark/x
(`[^@/]+@` пропускал «?»), а git шёл на evil-host.invalid: «?» у git начинает запрос, а не имя пользователя.
Проверяется:
- github_url: адреса с «?@», «#@», «\\@», «%40», пробелом, «@» в нескольких местах, «..» в owner/name — "" (не
  GitHub); остальное — только https://github.com/<o>/<n>.git или git@github.com:<o>/<n>.git, owner/name из
  [a-z0-9._-]; мутанты «старый разбор [^@/]+@» и «без отказа на ..» пойманы;
- record_origins: в список идёт канонический адрес, а не записанная окном строка; адрес с «?@» не закреплён;
  мутант «сырой адрес в список» пойман;
- pinned_remote и migrate --dry-run в окне: закреплённая строка с именем пользователя (git по ней шёл бы на evil —
  url.insteadOf в GIT_GLOBAL теста) сверяется по каноническому адресу (origin): слитый файл — код 0, файл только из
  evil — отказ «не из ветки»; закреплённый «?@» — отказ «не адрес github.com»; мутант «сырой адрес в git»
  пропускает файл из evil — тест это видит.
Сети нет: оба адреса уводит на голые репозитории рядом url.insteadOf своего глобального конфига git модуля (GIT_GLOBAL).
"""
import atexit
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import mkroot  # noqa: E402 — путь теста выше

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(PLUGIN, "lib", "supabase_migrate.py")
ROOT = os.path.realpath(mkroot("supabase-migrate-url-", "/var/tmp" if sys.platform.startswith("linux") else None))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "HOME": ROOT}


def git(cwd, *args):
    r = subprocess.run(["git", "-c", "init.defaultBranch=main", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd,
                       capture_output=True, text=True, env={**os.environ, **GIT_ENV}, timeout=60)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout


# ORIGIN — настоящий репозиторий (в main только MIG), EVIL — чужой (в main ещё и LOCAL); рабочая копия — клон EVIL
ORIGIN, EVIL, WORK, REPO = (os.path.join(ROOT, n) for n in ("origin.git", "evil.git", "work", "dir-u"))
MIG = "supabase/migrations/20260101000000_init.sql"
LOCAL = "supabase/migrations/20260102000000_local.sql"
for bare in (ORIGIN, EVIL):
    git(ROOT, "init", "--bare", bare)
git(ROOT, "clone", ORIGIN, WORK)
write(os.path.join(WORK, MIG), "create table t (id int);\n")
git(WORK, "add", "-A")
git(WORK, "commit", "-m", "init")
git(WORK, "push", "origin", "main")
git(WORK, "push", EVIL, "main")
write(os.path.join(WORK, LOCAL), "drop table t;\n")
git(WORK, "add", "-A")
git(WORK, "commit", "-m", "evil")
git(WORK, "push", EVIL, "main")
git(ROOT, "clone", EVIL, REPO)

CANON = "https://github.com/t/r4.git"
RAW = "https://user@github.com/T/R4.git"  # закреплённая строка с именем пользователя: git по ней шёл бы на EVIL
QMARK = "https://evil-host.invalid?@github.com/t/r4.git"
PINCFG = os.path.join(ROOT, "pin.gitconfig")  # глобальный конфиг git модуля: канонический → ORIGIN, сырые → EVIL
write(PINCFG, f'[url "{ORIGIN}"]\n\tinsteadOf = {CANON}\n[url "{EVIL}"]\n\tinsteadOf = {RAW}\n'
      f"\tinsteadOf = {QMARK}\n")
SRC = open(MOD, encoding="utf-8").read()
GLOBAL_LINE = "GIT_GLOBAL = os.devnull\n"


def load(src=SRC):
    assert src.count(GLOBAL_LINE) == 1, "в модуле нет строки GIT_GLOBAL = os.devnull"
    spec = importlib.util.spec_from_file_location("supabase_migrate_url_t", MOD)
    m = importlib.util.module_from_spec(spec)
    exec(compile(src.replace(GLOBAL_LINE, f"GIT_GLOBAL = {PINCFG!r}\n"), MOD, "exec"), m.__dict__)
    return m


def mutant(old, new):
    src = SRC.replace(old, new, 1)
    assert src != SRC, old
    return load(src)


RM = load()

# --- github_url: отказ или канонический адрес ---
BAD = ["https://evil-host.invalid?@github.com/latark/x.git", "https://evil#@github.com/t/r4.git",
       "https://evil\\@github.com/t/r4.git", "https://evil%40@github.com/t/r4.git",
       "https://github.com%40evil/t/r4.git", "https://ev il@github.com/t/r4.git", "https://github.com/t /r4.git",
       "https://a@b@github.com/t/r4.git", "https://a@github.com@evil/t/r4.git", "https://github.com/t/r4.git@evil",
       "https://github.com/t/r4?x=1", "https://github.com/t/r4#x", "ssh://evil?@github.com/t/r4.git",
       "ssh://a@b@github.com/t/r4.git", "evil?@github.com:t/r4.git", "a@b@github.com:t/r4.git",
       "git@github.com:t/../r4.git", "https://github.com/../r4.git", "https://github.com/t/..", "https://github.com/t/.",
       "https://github.com/t/r..x.git", "https://github.com:443/t/r4.git", "https://github.com.evil/t/r4.git",
       "http://github.com/t/r4.git", "file:///github.com/t/r4.git", "/github.com/t/r4.git", "", None]
GOOD = {"https://github.com/t/r4.git": CANON, RAW: CANON, "https://x-access_token.1@github.com/t/r4": CANON,
        "https://github.com/T/R4/": CANON, "ssh://git@github.com/t/r4.git": "git@github.com:t/r4.git",
        "ssh://git@github.com:22/T/r4": "git@github.com:t/r4.git", "git@github.com:t/r4.git": "git@github.com:t/r4.git",
        "github.com:t/r4": "git@github.com:t/r4.git", "https://github.com/t/.github.git": "https://github.com/t/.github.git"}
SHAPE = re.compile(r"(?:https://github\.com/|git@github\.com:)[a-z0-9._-]+/[a-z0-9._-]+\.git")
got_bad = {u: RM.github_url(u) for u in BAD}
check("github_url: «?@», «#@», «\\@», «%40», пробел, «@» в нескольких местах, «..», чужой хост — не GitHub (\"\")",
      not any(got_bad.values()), {u: v for u, v in got_bad.items() if v})
got_good = {u: RM.github_url(u) for u in GOOD}
check("github_url: адрес GitHub — канонический из owner/name, без имени пользователя и порта",
      got_good == GOOD, got_good)
check("github_url: любой непустой итог — только https://github.com/<o>/<n>.git или git@github.com:<o>/<n>.git, без «..»",
      all(SHAPE.fullmatch(v) and ".." not in v for v in got_good.values() if v))
OLD_RE = mutant("(?:https://(?:{_PART}@)?github", "(?:https://(?:[^@/]+@)?github")
check("мутант (старый разбор [^@/]+@) принимает «?@», «#@», «\\@», «%40» — тест это видит",
      all(OLD_RE.github_url(u) for u in BAD[:4]), [OLD_RE.github_url(u) for u in BAD[:4]])
NO_DOTS = mutant('    if not m or any(".." in g or g == "." for g in m.groups()):', "    if not m:")
check("мутант (без отказа на «..» в owner/name) принимает t/.. — тест это видит",
      NO_DOTS.github_url("https://github.com/t/..") != "" and NO_DOTS.github_url("https://github.com/../r4.git") != "")

# --- record_origins: в список — канонический адрес ---
TOP = os.path.join(ROOT, "top")
REC = {n: os.path.join(TOP, n) for n in ("raw", "qmark")}
for n, url in (("raw", RAW), ("qmark", QMARK)):
    git(ROOT, "clone", ORIGIN, REC[n])
    git(REC[n], "remote", "set-url", "origin", url)
REC_DENY = [d + "/.git/config" for d in REC.values()]
REC_STATE = os.path.join(ROOT, "state-rec")
out = RM.record_origins(REC_STATE, "w-r", [TOP], REC_DENY, ["t/r4"])
check("record_origins: адрес с именем пользователя закреплён каноническим, «?@» не закреплён",
      out == {REC["raw"]: CANON}
      and json.load(open(os.path.join(REC_STATE, "repo-origins", "w-r.json"), encoding="utf-8"))["repos"] == out, out)
RAW_REC = mutant("                out[d] = github_url(url)", "                out[d] = url")
check("мутант record_origins (сырой адрес окна в список) — тест это видит",
      RAW_REC.record_origins(REC_STATE, "w-m", [TOP], REC_DENY, ["t/r4"]).get(REC["raw"]) == RAW)

# --- migrate --dry-run в окне: git идёт только по каноническому адресу ---
STATE = os.path.join(ROOT, "state")
write(os.path.join(STATE, "domains.json"), json.dumps({"domains": {"w-u": [REPO]}}))


def pin(url):
    write(os.path.join(STATE, "repo-origins", "w-u.json"), json.dumps({"repos": {REPO: url}}))


def call(rel, mod=None):
    """main модуля в окне w-u из папки REPO → (код, stdout, stderr)."""
    keep, here = dict(os.environ), os.getcwd()
    os.environ.update({**GIT_ENV, "PANTHEON_WINDOW": "w-u"})
    os.chdir(REPO)
    o, e = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(o), redirect_stderr(e):
            code = (mod or RM).main(["migrate", rel, "--dry-run"], STATE)
    finally:
        os.chdir(here)
        os.environ.clear()
        os.environ.update(keep)
    return code, o.getvalue(), e.getvalue()


def last(err):
    return (err.strip().splitlines() or [""])[-1]


pin(RAW)
code, so, se = call(MIG)
check("закреплён RAW: слитый файл сверен по каноническому адресу (origin) — код 0", code == 0 and "проверено" in so,
      (code, se))
code, so, se = call(LOCAL)
check("закреплён RAW: файл только из evil — код 1, «не из ветки» (git не шёл по сырой строке)",
      code == 1 and "не из ветки по умолчанию" in last(se), (code, se))
RAW_GIT = mutant("    canon = github_url(url)  #", "    canon = url  #")
check("мутант (сырой закреплённый адрес в git) берёт evil и пропускает файл из evil — тест это видит",
      call(LOCAL, RAW_GIT)[0] == 0)
pin(QMARK)
code, so, se = call(LOCAL)
check("закреплён «?@» — код 1, «не адрес github.com» последней строкой", code == 1 and "не адрес github.com" in last(se),
      (code, se))
check("мутант (сырой адрес в git) с закреплённым «?@» идёт на evil — тест это видит", call(LOCAL, RAW_GIT)[0] == 0)
check("свои bare удалены после вызовов",
      not os.listdir(os.path.join(STATE, "supabase-migrate", "git")) if os.path.isdir(
          os.path.join(STATE, "supabase-migrate", "git")) else True)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
