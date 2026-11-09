#!/usr/bin/env python3
"""Корень тестов в окне роли (metis-0941, metis-0670): mkroot, fs_ok и own_dir из tests/_py311.py и их копия в
plugins/guard/tests/_py311.py.

Запуск: python3 -I plugins/pantheon/tests/test_mkroot.py  (код выхода 0 — все прошли)
- копии в двух плагинах одинаковы текстом (блок от SPARE до конца файла);
- fs_ok: обычная папка — да; запрет на `.claude/agents`, `.git/hooks` или `.git/config` (как песочница под кэшем окна,
  имитация подменой os.makedirs и open модуля) — нет; папку не создать (права 0o500) — нет; проба за собой убрана;
- mkroot: TMPDIR годится — корень в нём; TMPDIR режет `.claude/agents` — корень в запасной своей папке; first раньше
  TMPDIR; запасная чужая (не тот uid), открытая на запись группе или остальным, ссылка — не берётся (Д ревью PR #279);
  ни одна не годится — обычный mkdtemp (тест упадёт на своём месте);
- вживую (macOS, sandbox-exec): под профилем, который режет `.claude/agents` под TMPDIR, как правило окна denyWrite
  `<кэш>/**/.claude/agents`, mkroot уводит корень в запасную папку, и `.claude/agents` в нём создаётся. Нет
  sandbox-exec или он не запускается внутри другой песочницы — строка «пропущено».
"""
import builtins
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD_PY311 = os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "tests", "_py311.py")
sys.path.insert(0, HERE)
from _py311 import mkroot  # noqa: E402 — свой корень: в окне роли TMPDIR (кэш окна) пробу fs_ok не проходит

ROOT = os.path.realpath(mkroot("mkroot-test-"))
tempfile.tempdir = ROOT
os.environ["TMPDIR"] = ROOT
results = []


def check(name, cond, info=None):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or info is None else f"\n     {info!r}"[:800]))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def under(p, base):
    p, base = os.path.realpath(p), os.path.realpath(base)
    return p.startswith(base.rstrip("/") + "/")


class Deny:
    """Имитация denyWrite песочницы: os.makedirs и open модуля падают с EPERM на путях под base с одним из хвостов."""

    def __init__(self, mod, base, tails):
        self.mod, self.base, self.tails = mod, os.path.realpath(base), tails
        self.real_makedirs = os.makedirs

    def _bad(self, p):
        p = os.path.realpath(p)
        return p.startswith(self.base + "/") and any(("/" + t + "/") in (p + "/") for t in self.tails)

    def __enter__(self):
        real_open, real_md = builtins.open, self.real_makedirs

        def md(p, *a, **k):
            if self._bad(p):
                raise PermissionError(1, "Operation not permitted", p)
            return real_md(p, *a, **k)

        def op(p, *a, **k):
            if isinstance(p, str) and self._bad(p):
                raise PermissionError(1, "Operation not permitted", p)
            return real_open(p, *a, **k)

        os.makedirs = md
        self.mod.open = op  # глобальное имя модуля находится раньше builtins
        return self

    def __exit__(self, *exc):
        os.makedirs = self.real_makedirs
        del self.mod.open


def fresh(name, mode=0o700):
    d = os.path.join(ROOT, name)
    os.makedirs(d)
    os.chmod(d, mode)
    return d


def run_cases(M, tag):
    base = fresh(f"{tag}-plain")
    check(f"{tag}: fs_ok — обычная папка годится", M.fs_ok(base) is True)
    check(f"{tag}: fs_ok — пробная папка за собой убрана", os.listdir(base) == [], os.listdir(base))
    for tail in (".claude/agents", ".git/hooks", ".git/config"):
        with Deny(M, base, [tail]):
            got = M.fs_ok(base)
        check(f"{tag}: fs_ok — запись в {tail} закрыта (как под кэшем окна) — не годится", got is False)
    check(f"{tag}: fs_ok — после запретов проба тоже убрана", os.listdir(base) == [], os.listdir(base))
    ro = fresh(f"{tag}-ro", 0o500)
    check(f"{tag}: fs_ok — папку не создать (0o500) — не годится", M.fs_ok(ro) is False)
    os.chmod(ro, 0o700)

    # mkroot: TMPDIR («кэш окна») режет .claude/agents → корень в запасной своей папке
    cache, spare = fresh(f"{tag}-cache"), fresh(f"{tag}-spare")
    saved = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = cache
    try:
        r = M.mkroot("t-", spare=[spare])
        check(f"{tag}: mkroot — TMPDIR годится: корень в TMPDIR, запасная не нужна", under(r, cache), r)
        with Deny(M, cache, [".claude/agents"]):
            r = M.mkroot("t-", spare=[spare])
        check(f"{tag}: mkroot — TMPDIR режет .claude/agents (metis-0941): корень в запасной своей папке",
              under(r, spare), r)
        with Deny(M, cache, [".git/hooks"]):
            r = M.mkroot("t-", spare=[spare])
        check(f"{tag}: mkroot — TMPDIR режет .git/hooks (metis-0715): корень в запасной", under(r, spare), r)
        first = fresh(f"{tag}-first")
        r = M.mkroot("t-", first=first, spare=[spare])
        check(f"{tag}: mkroot — first раньше TMPDIR", under(r, first), r)
        # запасная не своя: открыта на запись остальным / группе, ссылка, чужой uid — не берётся
        wide, grp = fresh(f"{tag}-wide", 0o777), fresh(f"{tag}-grp", 0o770)
        link = os.path.join(ROOT, f"{tag}-link")
        os.symlink(spare, link)
        for what, sp in (("открыта на запись всем (0o777)", wide), ("открыта на запись группе (0o770)", grp),
                         ("ссылка на свою папку", link)):
            with Deny(M, cache, [".claude/agents"]):
                r = M.mkroot("t-", spare=[sp])
            check(f"{tag}: mkroot — запасная {what} не берётся (metis-0670): обычный mkdtemp, как без запасных",
                  under(r, tempfile.gettempdir()) and not under(r, sp) and not under(r, spare), r)
        real_uid = os.getuid
        os.getuid = lambda: real_uid() + 1
        try:
            with Deny(M, cache, [".claude/agents"]):
                r = M.mkroot("t-", spare=[spare])
        finally:
            os.getuid = real_uid
        check(f"{tag}: mkroot — запасная с другим владельцем (uid) не берётся (metis-0670)",
              under(r, tempfile.gettempdir()) and not under(r, spare), r)
        check(f"{tag}: own_dir — своя 0o700 да, 0o777 / ссылка / нет папки — нет",
              M.own_dir(spare) and not M.own_dir(wide) and not M.own_dir(link)
              and not M.own_dir(os.path.join(ROOT, "нет")))
        check(f"{tag}: SPARE — свой TMPDIR песочницы Claude Code /tmp/claude-<uid>",
              [s % 501 for s in M.SPARE] == ["/tmp/claude-501", "/private/tmp/claude-501"], M.SPARE)
    finally:
        if saved is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = saved


SB_CHILD = """import os, sys
sys.path.insert(0, sys.argv[1])
from _py311 import fs_ok, mkroot
root = mkroot("live-", spare=[sys.argv[2]])
os.makedirs(os.path.join(root, "h", ".claude", "agents"))
print("FSOK", fs_ok(os.environ["TMPDIR"]))
print("ROOT", root)
"""


def live(tag, dirpath):
    sbx = shutil.which("sandbox-exec") if sys.platform == "darwin" else None
    if not sbx:
        print(f"пропущено: {tag} вживую — нужен macOS с sandbox-exec")
        return
    # внутри другой песочницы (окно роли) sandbox-exec не применяет профиль: «sandbox_apply: Operation not permitted»
    ok = subprocess.run([sbx, "-p", "(version 1)(allow default)", "/usr/bin/true"], capture_output=True, text=True,
                        timeout=60)
    if ok.returncode:
        print(f"пропущено: {tag} вживую — sandbox-exec не запускается здесь ({ok.stderr.strip()[-120:]})")
        return
    cache, spare = fresh(f"{tag}-live-cache"), fresh(f"{tag}-live-spare")
    rc = os.path.realpath(cache)
    prof = ('(version 1)(allow default)(deny file-write* (regex #"^%s/(.*/)?\\.claude/agents(/|$)"))' % rc.replace(".", "\\."))
    env = dict(os.environ, TMPDIR=cache)
    probe = subprocess.run([sbx, "-p", prof, "/bin/mkdir", "-p", os.path.join(rc, "p", ".claude", "agents")],
                           capture_output=True, text=True, timeout=60)
    check(f"{tag} вживую: профиль режет .claude/agents под TMPDIR (как denyWrite кэша окна) — mkdir падает",
          probe.returncode != 0, probe.stderr)
    child = os.path.join(ROOT, f"{tag}-child.py")
    open(child, "w").write(SB_CHILD)
    r = subprocess.run([sbx, "-p", prof, sys.executable, "-I", child, dirpath, spare], env=env, capture_output=True,
                       text=True, timeout=120)
    root = next((x[5:] for x in r.stdout.splitlines() if x.startswith("ROOT ")), "")
    check(f"{tag} вживую: fs_ok(TMPDIR) — нет, mkroot — корень в запасной, .claude/agents в нём создан, код 0",
          r.returncode == 0 and "FSOK False" in r.stdout and under(root, spare), (r.returncode, r.stdout, r.stderr[-400:]))


def main():
    P = load(os.path.join(HERE, "_py311.py"), "py311_pantheon")
    G = load(GUARD_PY311, "py311_guard")
    mark = "# Запасные корни тестов"
    tp, tg = open(os.path.join(HERE, "_py311.py")).read(), open(GUARD_PY311).read()
    check("копии в pantheon и guard одинаковы (блок SPARE … mkroot)",
          mark in tp and mark in tg and tp[tp.index(mark):] == tg[tg.index(mark):])
    for M, tag, d in ((P, "pantheon", HERE), (G, "guard", os.path.dirname(GUARD_PY311))):
        run_cases(M, tag)
        live(tag, d)
    shutil.rmtree(ROOT, ignore_errors=True)
    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
