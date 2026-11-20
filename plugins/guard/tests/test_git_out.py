#!/usr/bin/env python3
"""Правило git-out (metis-0972): мимо песочницы окна идёт только `pantheon git push|fetch` — одной строкой из
простых слов; в окне (PANTHEON_ROLE, кроме hestia) голый git push|fetch|pull — отказ с подсказкой обёртки; строка
`pantheon git …` судится правилами push и fetch, как голый git (check_push и окно без роли). Каждая ветка — с
мутантом: копия hooks/ с подменённой строкой, тот же случай на ней должен дать другой ответ.
Запуск: python3 -I plugins/guard/tests/test_git_out.py   (код 0 — все прошли)
"""
import importlib.util
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import mkroot  # noqa: E402  (git init там, где песочница даёт .git/hooks, metis-0729)

HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
           GIT_AUTHOR_EMAIL="t@localhost", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@localhost")
results = []
_n = [0]


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or info is None else f"  [{info}]"))


def load(root, pairs=()):
    """guard_rules из копии hooks/ с подменами pairs (каждая строка — ровно один раз)."""
    _n[0] += 1
    d = os.path.join(root, f"guard-{_n[0]}")  # копия плагина целиком: правила читают и соседние файлы
    shutil.copytree(os.path.dirname(HOOKS), d, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    p = os.path.join(d, "hooks", "guard_rules.py")
    src = open(p, encoding="utf-8").read()
    for old, new in pairs:
        assert src.count(old) == 1, f"мутант: {old!r} найден {src.count(old)} раз"
        src = src.replace(old, new)
    open(p, "w", encoding="utf-8").write(src)
    spec = importlib.util.spec_from_file_location(f"guard_git_out_{_n[0]}", p)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


def role(env):
    if env:
        os.environ["PANTHEON_ROLE"] = env
    else:
        os.environ.pop("PANTHEON_ROLE", None)


def out(g, cmd, cwd, env=""):
    role(env)
    return g.check_git_out({"cwd": cwd}, "Bash", {"command": cmd})


FORM_OK = ["pantheon git push origin HEAD:feat-x", "pantheon git push origin feat", "pantheon git fetch",
           "pantheon git fetch origin main", "pantheon git fetch origin main:refs/remotes/origin/main"]
FORM_BAD = ["pantheon git push origin feat && rm -rf x", "pantheon git push --force origin feat",
            "pantheon git push origin +feat", "pantheon git fetch origin ../x", "X=1 pantheon git push origin feat",
            "pantheon git push origin $(echo feat)", "env pantheon git push origin feat", "pantheon git pull",
            "pantheon git status", "pantheon git push origin 'feat'", "pantheon git push origin feat; ls",
            "pantheon git push origin feat > /tmp/x", "~/.local/bin/pantheon git push origin feat"]
BARE_BAD = ["git push origin feat", "git -C sub fetch origin", "git pull", "git fetch", "git -c a.b=c push",
            'for d in a b; do git -C "$d" push origin feat; done', "git $X push origin feat"]
BARE_OK = ["git status", "git commit -m 'git push later'", "git log --oneline -3", "git merge origin/main",
           "pantheon task set x --note 'pantheon git push origin main'"]
FORM = ('        if GIT_OUT_LINE.match(cmd) and ".." not in cmd:\n            return None\n        return GIT_OUT_FORM',
        '        if True:\n            return None\n        return GIT_OUT_FORM')
BARE = ("        if p[1] in GIT_NET:\n            return GIT_OUT_BARE.format(sub=p[1])",
        "        if False:\n            return GIT_OUT_BARE.format(sub=p[1])")
HESTIA = ('    if not win or win == "hestia":\n        return None\n    if failed and GIT_WORD',
          '    if not win:\n        return None\n    if failed and GIT_WORD')
UNRES = ("            if None in t or any(x in GIT_NET for x in t if x):", "            if False:")
WIRED = ('                        ("git-out", check_git_out),\n', "")
MAP_ROLE = ('        name, texts = _git_out_as_git(name, texts)\n        if name == "gh" and _gh_parse(texts)[0]:',
            '        if name == "gh" and _gh_parse(texts)[0]:')
MAP_OWNER = ('        name, texts = _git_out_as_git(name, texts)\n        if name == "git":  # push в принятый PR',
             '        if name == "git":  # push в принятый PR')


def main():
    root = os.path.realpath(mkroot("guard-git-out-"))
    os.environ["HOME"] = root
    saved = os.environ.get("PANTHEON_ROLE")
    try:
        repo = os.path.join(root, "repo")
        os.makedirs(repo)
        for a in (("init", "-q", "-b", "main"), ("commit", "-q", "--allow-empty", "-m", "a"),
                  ("switch", "-q", "-c", "feat"), ("remote", "add", "origin", "https://github.com/o/r.git")):
            subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=ENV)
        g = load(root)
        mut = {k: load(root, [v]) for k, v in (("form", FORM), ("bare", BARE), ("hestia", HESTIA), ("unres", UNRES),
                                                ("wired", WIRED), ("map_role", MAP_ROLE), ("map_owner", MAP_OWNER))}
        # форма обёртки — в любой сессии, и без роли
        for cmd in FORM_OK:
            why = out(g, cmd, repo)
            check(f"форма: {cmd} — можно", why is None, why)
        for cmd in FORM_BAD:
            why = out(g, cmd, repo)
            check(f"форма: {cmd} — отказ", isinstance(why, str) and why.startswith("Правило git-out"), why)
            m = out(mut["form"], cmd, repo)
            check(f"  мутант «форма не сверяется»: {cmd} — пропуск", m is None, m)
        # голый git в окне
        for cmd in BARE_BAD:
            why = out(g, cmd, repo, "metis-pantheon")
            check(f"окно: {cmd} — отказ", isinstance(why, str) and "pantheon git" in why, why)
            check(f"без роли: {cmd} — правило молчит", out(g, cmd, repo) is None)
        for cmd in BARE_OK:
            why = out(g, cmd, repo, "metis-pantheon")
            check(f"окно: {cmd} — можно", why is None, why)
        for cmd in ("git push origin feat", "git -C sub fetch origin", "git pull"):
            m = out(mut["bare"], cmd, repo, "metis-pantheon")
            check(f"  мутант «подкоманда не судится»: {cmd} — пропуск", m is None, m)
        m = out(mut["unres"], "git $X push origin feat", repo, "metis-pantheon")
        check("  мутант «невычислимое слово до подкоманды»: git $X push — пропуск", m is None, m)
        why = out(g, "git push origin feat", repo, "hestia")
        check("hestia: git push — своё правило (consent), git-out молчит", why is None, why)
        m = out(mut["hestia"], "git push origin feat", repo, "hestia")
        check("  мутант «hestia как все»: git push — отказ", isinstance(m, str), m)
        # правило подключено к check_window
        role("metis-pantheon")
        ev = {"cwd": repo}
        why = g.check_window(ev, "Bash", {"command": "git push origin feat"})
        check("check_window: голый git push в окне — отказ git-out", isinstance(why, str) and "git-out" in why, why)
        m = mut["wired"].check_window(ev, "Bash", {"command": "git push origin feat"})
        check("  мутант «правило не подключено»: пропуск", not (isinstance(m, str) and "git-out" in m), m)
        why = g.check_window(ev, "Bash", {"command": "pantheon git push origin HEAD:feat-x"})
        check("check_window: pantheon git push в рабочую ветку — можно", not isinstance(why, str), why)
        # pantheon git судится правилами push и fetch, как голый git
        os.environ["CLAUDE_PROJECT_DIR"] = repo
        lead = {"cwd": repo, "agent_type": "hephaestus-shop", "agent_id": "a1"}
        for cmd, deny in (("pantheon git push origin feat:main", True), ("pantheon git push origin feat:heads/main", True),
                          ("pantheon git push origin feat", False)):
            role("")
            why = g.check_push(lead, "Bash", {"command": cmd})
            got = isinstance(why, str) and why.startswith("Правило push")
            check(f"check_push лид: {cmd} — {'отказ' if deny else 'можно'}", got == deny, why)
        role("")
        m = mut["map_role"].check_push(lead, "Bash", {"command": "pantheon git push origin feat:main"})
        check("  мутант «pantheon git не как git» (роли): feat:main — пропуск", not isinstance(m, str), m)
        role("metis-pantheon")
        why = g.check_push(ev, "Bash", {"command": "pantheon git fetch origin main:main"})
        check("check_push окно без agent_type: pantheon git fetch main:main — отказ",
              isinstance(why, str) and why.startswith("Правило fetch"), why)
        m = mut["map_owner"].check_push(ev, "Bash", {"command": "pantheon git fetch origin main:main"})
        check("  мутант «pantheon git не как git» (окно): fetch main:main — пропуск", not isinstance(m, str), m)
    finally:
        if saved is None:
            os.environ.pop("PANTHEON_ROLE", None)
        else:
            os.environ["PANTHEON_ROLE"] = saved
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} прошли")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
