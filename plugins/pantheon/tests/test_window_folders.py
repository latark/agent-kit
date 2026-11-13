#!/usr/bin/env python3
"""Папки направления — рабочие папки его окна (metis-0911, решение Зевса 06.11).

Запуск: python3 -I plugins/pantheon/tests/test_window_folders.py  (код выхода 0 — все прошли)
- `pantheon domains build` на временном HOME: окно направления получает permissions.additionalDirectories — все
  свои папки из directions.toml настоящими путями (cd туда сохраняется, EnterWorktree в их .claude/worktrees/ Claude
  Code пускает без вопроса владельцу); папок чужого направления в нём нет;
- мастерская и окна без направления additionalDirectories не получают;
- allow_gate по всем папкам окна (ревью argus 2 PR #360): allow с gh pr merge во второй папке — окно не собрано, и
  при --if-changed; no_window_reason и direction check называют эту папку;
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
import time

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
    for d in ("projects/repo-law", "projects/repo-corp", "projects/br", "ai/knowledge", "projects/workshop",
              ".claude/pantheon"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    with open(os.path.join(home, "directions.toml"), "w") as fh:
        fh.write('[[direction]]\nname = "themis-repos"\nfolders = ["~/projects/repo-law", "~/projects/repo-corp"]\n'
                 '[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1", "PANTHEON_CLAUDE_TMP": os.path.join(tmp, "ctmp")}  # общий /tmp/claude-<uid> меняется
    os.makedirs(env["PANTHEON_CLAUDE_TMP"])  # сам: иначе --if-changed пересобирал бы всегда
    r = subprocess.run([sys.executable, "-I", RUN_PY, "domains", "build"], env=env, capture_output=True, text=True,
                       timeout=120)
    check("сборка прошла", r.returncode == 0, r.stderr)
    win = lambda n: json.load(open(os.path.join(state, "settings", n + ".json")))  # noqa: E731
    real = lambda p: os.path.realpath(os.path.join(tmp, p))  # noqa: E731
    th, at, ws = win("themis-repos"), win("athena-shop"), win("workshop")
    got = (th.get("permissions") or {}).get("additionalDirectories")
    check("окно направления: все свои папки — рабочие (additionalDirectories), настоящими путями, по порядку реестра",
          got == [real("projects/repo-law"), real("projects/repo-corp")], got)
    check("окно направления: папок чужого направления в рабочих нет",
          real("projects/br") not in (got or []) and (at.get("permissions") or {}).get("additionalDirectories")
          == [real("projects/br")], (got, at.get("permissions")))
    check("мастерская additionalDirectories не получает",
          "additionalDirectories" not in (ws.get("permissions") or {}), ws.get("permissions"))
    matchers = [g["matcher"] for g in th["hooks"]["PreToolUse"]
                if any("guard.py" in h.get("command", "") for h in g.get("hooks") or [])]
    check("строгий guard окна ловит EnterWorktree (worktree-own)",
          len(matchers) == 1 and "EnterWorktree" in matchers[0].split("|"), matchers)

    # allow_gate по всем папкам окна (ревью argus 2 PR #360): вторая папка с allow, пускающим gh pr merge, — окно не
    # собирается, как и при таком allow в папке запуска (metis-0137)
    ifc = lambda: subprocess.run([sys.executable, "-I", RUN_PY, "domains", "build", "--if-changed"], env=env,  # noqa: E731
                                 capture_output=True, text=True, timeout=120)
    built = lambda: json.load(open(os.path.join(state, "domains.json"))).get("built_ts")  # noqa: E731
    ifc()  # сборка ролей дописывает файлы после отметки: одна доводка, дальше тихо (как test_plugin_map)
    b0 = built()
    ifc()
    check("--if-changed без правок — пересборки нет (иначе проверка ниже ничего не доказывает)", built() == b0)
    second = os.path.join(tmp, "projects/repo-corp/.claude")
    os.makedirs(second)
    with open(os.path.join(second, "settings.json"), "w") as fh:
        json.dump({"permissions": {"allow": ["Bash(gh pr *)", "Bash(mailkeeper scan *)"]},
                   "sandbox": {"excludedCommands": ["mailkeeper *"]}}, fh)
    os.utime(os.path.join(second, "settings.json"), (time.time() + 5,) * 2)  # новее built_ts: --if-changed заметит
    r = subprocess.run([sys.executable, "-I", RUN_PY, "domains", "build", "--if-changed"], env=env, capture_output=True,
                       text=True, timeout=120)
    gone = not os.path.exists(os.path.join(state, "settings", "themis-repos.json"))
    check("вторая папка с allow gh pr merge — окно направления не собрано, причина названа",
          gone and "repo-corp/.claude/settings.json" in r.stderr and "gh pr merge" in r.stderr, (gone, r.stderr))
    check("чужое направление при этом собрано", os.path.exists(os.path.join(state, "settings", "athena-shop.json")))
    sys.path.insert(0, os.path.join(PLUGIN, "lib"))
    os.environ.update(HOME=tmp, PANTHEON_HOME=home, PANTHEON_STATE=state, PANTHEON_NO_NOTIFY="1")
    import pantheon as P  # noqa: E402 — после HOME: модуль берёт пути при загрузке
    folders = ["~/projects/repo-law", "~/projects/repo-corp", "~/projects/repo-law"]
    check("window_folders: папка запуска первой, остальные по реестру, без повторов",
          P.window_folders(folders) == [real("projects/repo-law"), real("projects/repo-corp")],
          P.window_folders(folders))
    reason = P.no_window_reason("themis-repos")
    check("no_window_reason называет allow второй папки", "repo-corp" in reason and "gh pr merge" in reason, reason)
    line = [t for ok, t in P.direction_check("themis-repos") if "gh pr merge" in t]
    check("direction check: allow второй папки — пункт не готов, с путём",
          len(line) == 1 and "repo-corp/.claude/settings.json" in line[0]
          and not dict((t, ok) for ok, t in P.direction_check("themis-repos"))[line[0]], line)
    os.remove(os.path.join(second, "settings.json"))
    r = subprocess.run([sys.executable, "-I", RUN_PY, "domains", "build"], env=env, capture_output=True, text=True,
                       timeout=120)
    check("allow убран — окно снова собрано", os.path.exists(os.path.join(state, "settings", "themis-repos.json")),
          r.stderr)
    return all(results)


if __name__ == "__main__":
    ok = main()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if ok else 1)
