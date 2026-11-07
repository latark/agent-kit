#!/usr/bin/env python3
"""Назначение refspec у git push и git fetch (metis-0983): guard понимает его по правилам git, а не по строке.
push в main/master отказ при любой записи назначения (heads/main, refs/heads/main, +main, X:main, HEAD:refs/heads/main,
--all, --mirror и их сокращения); fetch и pull — отказ с --update-head-ok (-u), --stdin и с refspec или --refmap,
который пишет не в refs/remotes/* и не в теги (refs/heads/*, refs/replace/*, refs/notes/*); refs/remotes/* и
теги — можно. Слово до подкоманды не вычислить (`git -C "$d"`): push в окне — отказ, fetch — по словам после fetch,
прочее — пропуск. Разбор — тот же, что у хука: bash_analysis → push_problem
и fetch_problem; HEAD берётся из временного репозитория на ветке feat.
Запуск: python3 -I plugins/guard/tests/test_refspec.py   (код 0 — все прошли)
"""
import importlib.util
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import mkroot  # noqa: E402  (git init там, где песочница даёт .git/hooks, metis-0729)

RULES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard_rules.py")
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
           GIT_AUTHOR_EMAIL="t@localhost", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@localhost")
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or info is None else f"  [{info}]"))


def git(d, *args):
    subprocess.run(["git", "-C", d, *args], check=True, capture_output=True, env=ENV)


def words(g, cmd, cwd):
    """Аргументы первой команды git из строки — как их видит хук."""
    return next(t for n, t in g.bash_analysis(cmd, cwd)[1] if n == "git")


PUSH_DENY = [
    "git push origin main", "git push origin heads/main", "git push origin refs/heads/main",
    "git push origin feat:main", "git push origin feat:heads/main", "git push origin feat:refs/heads/main",
    "git push origin HEAD:refs/heads/main", "git push origin HEAD:heads/main", "git push origin @:main",
    "git push origin feat:master", "git push origin feat:heads/master", "git push origin feat:MAIN",
    "git push origin feat:Heads/Main", "git push origin feat:refs/heads/MAIN", "git push origin heads/feat:heads/main",
    "git push origin feat:refs/heads/*", "git push origin +main", "git push origin +feat:heads/main",
    "git push --all origin", "git push --mirror origin", "git push --branches origin", "git push --al origin",
    "git push --mirr origin", "git push --bra origin", "git push --forc origin feat", "git push --del origin x",
    "git push origin :feat", "git push origin feat:",
    # связки коротких флагов с цифрой (Д4 argus-2 #380)
    "git push -4f origin feat", "git push -4d origin feat", "git push -6f origin feat", "git push -f4 origin feat",
]
PUSH_ALLOW = [
    "git push origin feat", "git push origin feat:feat", "git push origin HEAD", "git push origin HEAD:feat",
    "git push origin feat:heads/feat", "git push origin feat:refs/heads/feat", "git push origin feat:mainline",
    "git push origin feat:main-x", "git push origin feat:refs/tags/main", "git push origin v1:tags/main",
    "git push --dry-run origin feat", "git push --atomic origin feat", "git push -u origin feat",
    "git push --follow-tags origin feat", "git push -4 origin feat", "git push -6q origin feat",
]
FETCH_DENY = [
    "git fetch --update-head-ok origin main:feat", "git fetch -u origin main:feat", "git fetch -qu origin main:feat",
    "git fetch --update-h origin main:feat", "git fetch --update-head-ok origin", "git fetch -u origin",
    "git fetch -qu origin main", "git pull -u", "git fetch --stdin origin",
    "git fetch origin main:feat", "git fetch origin main:main", "git fetch origin +main:main",
    "git fetch origin main:heads/x", "git fetch origin main:refs/heads/x", "git fetch origin main:Refs/Heads/x",
    "git fetch origin 'refs/heads/*:refs/heads/*'", "git fetch origin '+refs/heads/*:refs/heads/*'",
    "git fetch . feat:main", "git fetch /tmp/x main:feat",
    "git fetch --refmap=+refs/heads/*:refs/heads/rm/* origin main", "git fetch --refmap +refs/heads/*:refs/heads/* origin",
    "git fetch --depth 1 origin main:feat", "git fetch origin -- main:feat", "git -C . fetch origin main:feat",
    "git pull origin main:main", "git pull -u origin main:feat",
    # слово до подкоманды не вычислить — судятся слова после fetch и pull (Д1 argus #380)
    'for d in a b; do git -C "$d" fetch -u . feat:main; done', 'for d in a b; do git -C "$d" fetch origin main:feat; done',
    'for d in a b; do git -C "$d" fetch --stdin origin; done', 'for d in a b; do git -C "$d" pull --update-h; done',
    'for d in a b; do git -C "$d" fetch "$d" main:feat; done',
    # назначение — только refs/remotes/* и теги (Д2 argus-2 #380)
    "git fetch origin main:refs/replace/0123abcd", "git fetch origin main:refs/notes/commits",
    "git fetch origin main:refs/x/y", "git fetch --refmap=+refs/heads/*:refs/notes/* origin main",
]
FETCH_ALLOW = [
    "git fetch", "git fetch origin", "git fetch origin main", "git fetch --prune origin", "git fetch --all",
    "git fetch origin main:refs/remotes/origin/main", "git fetch origin '+refs/heads/*:refs/remotes/origin/*'",
    "git fetch origin refs/tags/v1:refs/tags/v1", "git fetch origin tag v1", "git fetch --tags origin",
    "git fetch --refmap= origin main", "git fetch --refmap=+refs/heads/*:refs/remotes/o/* origin main",
    "git fetch --depth 1 origin main", "git fetch git@github.com:o/r.git main", "git fetch https://x/o/r main",
    "git fetch origin ^refs/heads/x", "git pull", "git pull --rebase origin main", "git pull -s ours origin main",
    "git fetch origin main:remotes/origin/zz", "git fetch origin main:", "git status", "git push origin feat",
    'for d in a b; do git -C "$d" fetch origin; done', 'for d in a b; do git -C "$d" pull --rebase origin main; done',
    'for d in a b; do git -C "$d" status; done', 'for d in a b; do git -C "$d" log --grep x -- a:refs/heads/b; done',
    "git fetch origin v1:tags/v1", "git fetch origin main:Refs/Remotes/o/main",
]


def main():
    root = os.path.realpath(mkroot("guard-refspec-"))
    os.environ["HOME"] = root
    try:
        spec = importlib.util.spec_from_file_location("guard_under_test", RULES)
        g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(g)
        repo = os.path.join(root, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q", "-b", "main")
        git(repo, "commit", "-q", "--allow-empty", "-m", "a")
        git(repo, "switch", "-q", "-c", "feat")
        for cmd in PUSH_DENY:
            why = g.push_problem(words(g, cmd, repo), repo, False)
            check(f"push отказ: {cmd}", why, why)
        for cmd in PUSH_ALLOW:
            why = g.push_problem(words(g, cmd, repo), repo, False)
            check(f"push можно: {cmd}", not why, why)
        # шлюз push в принятый PR получает имя ветки, а не запись назначения
        got = g._push_parse(words(g, "git push origin feat:heads/feat", repo), repo, False)
        check("push: heads/feat → ветка feat для push_accepted", got[2] == [("feat", "feat")], got)
        got = g._push_parse(words(g, "git push -4f origin feat", repo), repo, False, force=True)
        check("push: -4f для push_accepted — принудительная отправка в feat", isinstance(got, tuple)
              and got[2] == [("feat", "feat")], got)
        git(repo, "switch", "-q", "main")
        for cmd in ("git push", "git push origin", "git push origin HEAD", "git push origin HEAD:HEAD"):
            why = g.push_problem(words(g, cmd, repo), repo, False)
            check(f"push с HEAD на main — отказ: {cmd}", why, why)
        for cmd in FETCH_DENY:
            why = g.fetch_problem(words(g, cmd, repo))
            check(f"fetch отказ: {cmd}", why, why)
        for cmd in FETCH_ALLOW:
            why = g.fetch_problem(words(g, cmd, repo))
            check(f"fetch можно: {cmd}", not why, why)
        # через правило хука check_push: лид-субагент, главная сессия окна (PANTHEON_ROLE без agent_type), владелец
        os.environ["CLAUDE_PROJECT_DIR"] = repo
        lead = {"cwd": repo, "agent_type": "hephaestus-shop", "agent_id": "a1"}
        win = {"cwd": repo}
        for ev, env, cmd, deny in (
                (lead, "", "git push origin feat:heads/main", True), (lead, "", "git push --mirr origin", True),
                (lead, "", "git push origin feat", False), (lead, "", "git fetch -u . feat:main", True),
                (lead, "", "git fetch origin main:refs/remotes/origin/main", False),
                (win, "metis-pantheon", "git fetch --update-head-ok origin main:main", True),
                (win, "metis-pantheon", "git fetch origin 'refs/heads/*:refs/heads/*'", True),
                (win, "metis-pantheon", "git fetch origin", False), (win, "", "git fetch origin main:main", False),
                (win, "metis-pantheon", 'for d in a b; do git -C "$d" fetch -u . feat:main; done', True),
                (win, "metis-pantheon", 'for d in a b; do git -C "$d" fetch origin; done', False),
                (lead, "", 'for d in a b; do git -C "$d" fetch origin main:feat; done', True)):
            os.environ["PANTHEON_ROLE"] = env
            why = g.check_push(ev, "Bash", {"command": cmd})
            got = isinstance(why, str) and why.startswith(("Правило push", "Правило fetch"))
            who = "окно" if ev is win and env else "владелец" if ev is win else "лид"
            check(f"check_push {who}: {cmd} — {'отказ' if deny else 'можно'}", got == deny, why)
        # push главной сессии окна — по push_problem, но только в репозиториях [merge_repos] или с невычислимым remote
        os.makedirs(os.path.join(root, ".claude", "pantheon"))
        with open(os.path.join(root, ".claude", "pantheon", "policy.toml"), "w") as fh:
            fh.write('[merge_repos]\nmetis-pantheon = ["latark/agent-kit"]\n')
        git(repo, "remote", "add", "origin", "https://github.com/latark/agent-kit.git")
        git(repo, "remote", "add", "store", "git@github.com:latark/pantheon.git")
        git(repo, "remote", "add", "bare", "")
        # push идёт по pushurl, а не по url (Д2 argus #380)
        git(repo, "remote", "add", "pu", "https://github.com/latark/pantheon.git")
        git(repo, "config", "remote.pu.pushurl", "https://github.com/latark/agent-kit.git")
        git(repo, "remote", "add", "pu2", "https://github.com/latark/agent-kit.git")
        git(repo, "config", "remote.pu2.pushurl", "git@github.com:latark/pantheon.git")
        for env, cmd, deny in (
                ("metis-pantheon", "git push pu feat:main", True),
                ("metis-pantheon", "git push pu2 feat:main", False),
                # слово до подкоманды не вычислить: судится, только если среди слов есть push (Б1 argus #380)
                ("metis-pantheon", 'for d in a b; do git -C "$d" status; done', False),
                ("metis-pantheon", 'git -C "$(git rev-parse --show-toplevel)" log -1', False),
                ("metis-pantheon", 'for g in a b; do git --git-dir="$g" log; done', False),
                ("metis-pantheon", 'for d in a b; do git -C "$d" push origin feat:main; done', True),
                ("metis-pantheon", 'for d in a b; do git -C "$d" push origin feat; done', True),
                ("metis-pantheon", "git push origin feat:main", True),
                ("metis-pantheon", "git push origin HEAD:refs/heads/feat-x", False),
                ("metis-pantheon", "git push origin feat:heads/main", True),
                ("metis-pantheon", "git push https://github.com/Latark/agent-kit feat:main", True),
                ("metis-pantheon", "git push -C . origin feat:main", True),
                ("metis-pantheon", "git push bare feat:main", True),
                ("metis-pantheon", "git push store feat:main", False),
                ("metis-pantheon", "git push https://github.com/latark/pantheon feat:main", False),
                ("metis-pantheon", "git push $R feat:main", True),
                ("metis-pantheon", "git push origin --force feat", True),
                ("", "git push origin feat:main", False)):
            os.environ["PANTHEON_ROLE"] = env
            why = g.check_push(win, "Bash", {"command": cmd})
            got = isinstance(why, str) and why.startswith("Правило push")
            who = "окно" if env else "владелец"
            check(f"check_push {who}: {cmd} — {'отказ' if deny else 'можно'}", got == deny, why)
        os.environ.pop("PANTHEON_ROLE", None)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} прошли")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
