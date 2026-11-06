#!/usr/bin/env python3
"""Папки направления — рабочие папки его окна (metis-0911, решение Зевса 06.11).

Запуск: python3 -I plugins/pantheon/tests/test_window_folders.py  (код выхода 0 — все прошли)
- `pantheon domains build` на временном HOME: окно направления получает permissions.additionalDirectories — все
  свои папки из directions.toml настоящими путями (cd туда сохраняется, EnterWorktree в их .claude/worktrees/ Claude
  Code пускает без вопроса владельцу); папок чужого направления в нём нет;
- мастерская и окна без направления additionalDirectories не получают;
- строгий guard окна ловит EnterWorktree (matcher): чужой репозиторий закрывает правило worktree-own
  (plugins/guard/tests/test_worktree_own.py).
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN_PY = os.path.join(PLUGIN, "lib", "run.py")  # загрузчик, как bin/pantheon
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="winfold-"))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond, info=None):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or info is None else "\n     " + str(info)[-1500:]))


def main():
    tmp = os.path.join(ROOT, "h")
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    for d in ("projects/legal-watch", "projects/expert-corpus", "projects/br", "ai/knowledge", "projects/workshop",
              ".claude/pantheon"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "themis-sources"\nfolders = ["~/projects/legal-watch", "~/projects/expert-corpus"]\n'
                 '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1"}
    r = subprocess.run([sys.executable, "-I", RUN_PY, "domains", "build"], env=env, capture_output=True, text=True,
                       timeout=120)
    check("сборка прошла", r.returncode == 0, r.stderr)
    win = lambda n: json.load(open(os.path.join(state, "settings", n + ".json")))  # noqa: E731
    real = lambda p: os.path.realpath(os.path.join(tmp, p))  # noqa: E731
    th, at, ws = win("themis-sources"), win("athena-shop"), win("workshop")
    got = (th.get("permissions") or {}).get("additionalDirectories")
    check("окно направления: все свои папки — рабочие (additionalDirectories), настоящими путями, по порядку реестра",
          got == [real("projects/legal-watch"), real("projects/expert-corpus")], got)
    check("окно направления: папок чужого направления в рабочих нет",
          real("projects/br") not in (got or []) and (at.get("permissions") or {}).get("additionalDirectories")
          == [real("projects/br")], (got, at.get("permissions")))
    check("мастерская additionalDirectories не получает",
          "additionalDirectories" not in (ws.get("permissions") or {}), ws.get("permissions"))
    matchers = [g["matcher"] for g in th["hooks"]["PreToolUse"]
                if any("guard.py" in h.get("command", "") for h in g.get("hooks") or [])]
    check("строгий guard окна ловит EnterWorktree (worktree-own)",
          len(matchers) == 1 and "EnterWorktree" in matchers[0].split("|"), matchers)
    return all(results)


if __name__ == "__main__":
    ok = main()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if ok else 1)
