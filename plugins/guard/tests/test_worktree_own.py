#!/usr/bin/env python3
"""worktree-own (metis-0911): окно направления (PANTHEON_WINDOW из domains.json) входит EnterWorktree с path только в
.claude/worktrees/ папок своего направления, и только когда сессия стоит в той же папке — так Claude Code пускает без
вопроса владельцу. Своя папка из другой точки, своя папка не под .claude/worktrees/, папка чужого направления и путь
вне папок направлений — отказ с подсказкой (cd, pantheon start <направление>, задача ему). Без path, вне окна
направления и в окне, которого нет в domains.json, правило молчит. Репозиторий — путь до последнего
.claude/worktrees/<имя>: папка-контейнер (ProjM/app) пропускается из app, вложенный репозиторий (LW/data →
LW/.claude/worktrees/a) — отказ. Настройки проекта вне папки запуска с allow, sandbox, hooks, env — отказ, и с name.
Хук целиком (guard.py --strict и плагин) ловит
EnterWorktree и отвечает deny.

Запуск: python3 -I plugins/guard/tests/test_worktree_own.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
GUARD = os.path.join(HOOKS, "guard.py")
RULES = os.path.join(HOOKS, "guard_rules.py")
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


root = os.path.realpath(tempfile.mkdtemp(prefix="guard-wtown-"))
saved = {k: os.environ.get(k) for k in ("HOME", "PANTHEON_WINDOW", "PANTHEON_ROLE")}
os.environ["HOME"] = root
try:
    for d in ("projects/repo-law/.claude/worktrees/a", "projects/repo-corp/.claude/worktrees/themis-0020",
              "projects/repo-corp/src", "projects/projAApp/.claude/worktrees/x",
              "projects/stray/.claude/worktrees/y", ".local/state/pantheon", "links",
              "projects/repo-law/data/.claude/worktrees/z", "projects/projAApp/fin/.claude/worktrees/q",
              "projects/ProjM/app/.claude/worktrees/p1", "projects/ProjM/app/src",
              "projects/ProjM/gpu-worker/.claude/worktrees/g1"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    # .git — у репозиториев; ProjM — контейнер без git (ревью argus PR #360), у worktree — файл .git
    for d in ("repo-law", "repo-corp", "repo-law/data", "projAApp", "projAApp/fin",
              "stray", "ProjM/app", "ProjM/gpu-worker"):
        os.makedirs(os.path.join(root, "projects", d, ".git"))
    for d in ("repo-corp/.claude/worktrees/themis-0020", "ProjM/app/.claude/worktrees/p1",
              "repo-law/data/.claude/worktrees/z"):
        with open(os.path.join(root, "projects", d, ".git"), "w") as fh:
            fh.write("gitdir: x\n")
    os.symlink(os.path.join(root, "projects/projAApp"), os.path.join(root, "links/ba"))
    with open(os.path.join(root, ".local/state/pantheon/domains.json"), "w") as fh:
        json.dump({"domains": {"themis-repos": ["~/projects/repo-law", "~/projects/repo-corp",
                                                  "~/projects/repo-law/data"],
                               "athena-proja": ["~/projects/projAApp"],
                               "plutus-finance": ["~/projects/projAApp/fin"],
                               "proteus-projm": ["~/projects/ProjM"]}}, fh)
    spec = importlib.util.spec_from_file_location("guard_under_test", RULES)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    LW = os.path.join(root, "projects/repo-law")
    EC = os.path.join(root, "projects/repo-corp")
    BA = os.path.join(root, "projects/projAApp")
    WT = EC + "/.claude/worktrees/themis-0020"

    def run(inp, cwd=LW, win="themis-repos"):
        if win:
            os.environ["PANTHEON_WINDOW"] = win
        else:
            os.environ.pop("PANTHEON_WINDOW", None)
        return g.check_worktree_own({"cwd": cwd}, "EnterWorktree", inp)

    r = run({"path": WT}, cwd=EC)
    check("1 своя папка, сессия в том же репозитории — пропуск", r is None, r)
    r = run({"path": ".claude/worktrees/themis-0020"}, cwd=EC)
    check("1 относительный path от папки сессии — пропуск", r is None, r)
    r = run({"path": WT}, cwd=EC + "/.claude/worktrees/themis-0020")
    check("1 сессия уже в worktree того же репозитория — пропуск", r is None, r)
    r = run({"path": LW + "/.claude/worktrees/a"}, cwd=LW)
    check("1 папка запуска — пропуск", r is None, r)
    r = run({"path": WT}, cwd=LW)
    check("2 своя папка, сессия в другом репозитории — отказ с подсказкой cd",
          bool(r) and "worktree-own" in r and f"cd {EC}" in r and "владельца" in r, r)
    r = run({"path": EC}, cwd=EC)
    check("3 корень своего репозитория (не .claude/worktrees/) — отказ", bool(r) and "worktree-own" in r
          and ".claude/worktrees/" in r, r)
    r = run({"path": EC + "/.claude/worktrees"}, cwd=EC)
    check("3 сама папка .claude/worktrees — отказ", bool(r) and "worktree-own" in r, r)
    r = run({"path": EC + "/src"}, cwd=EC)
    check("3 подпапка своего репозитория вне worktrees — отказ", bool(r) and "worktree-own" in r, r)
    r = run({"path": BA + "/.claude/worktrees/x"}, cwd=LW)
    check("4 репозиторий чужого направления — отказ с именем, pantheon start и задачей",
          bool(r) and "athena-proja" in r and "pantheon start athena-proja" in r
          and "directions/athena-proja/inbox/" in r, r)
    r = run({"path": BA + "/.claude/worktrees/x"}, cwd=BA)
    check("4 чужое направление и из его папки — отказ", bool(r) and "athena-proja" in r, r)
    r = run({"path": os.path.join(root, "links/ba/.claude/worktrees/x")}, cwd=LW)
    check("4 ссылка в чужой репозиторий — отказ (realpath)", bool(r) and "athena-proja" in r, r)
    r = run({"path": "~/projects/projAApp/.claude/worktrees/x"}, cwd=LW)
    check("4 путь с ~ — отказ чужого направления", bool(r) and "athena-proja" in r, r)
    r = run({"path": LW + "/data/.claude/worktrees/z"}, cwd=LW + "/data")
    check("1 вложенная своя папка — берётся самая глубокая, пропуск", r is None, r)
    r = run({"path": BA + "/fin/.claude/worktrees/q"}, cwd=LW)
    check("4 вложенная чужая папка — называет самое глубокое направление",
          bool(r) and "pantheon start plutus-finance" in r and "athena-proja" not in r, r)
    r = run({"path": BA + "/fin/.claude/worktrees/q"}, cwd=BA, win="athena-proja")
    check("4 вложенная чужая папка внутри своей — отказ чужого направления, не пропуск",
          bool(r) and "pantheon start plutus-finance" in r, r)

    # папка направления — контейнер репозиториев (ревью argus 1 PR #360, Б): репозиторий — путь до .claude/worktrees
    MS = os.path.join(root, "projects/ProjM")
    r = run({"path": MS + "/app/.claude/worktrees/p1"}, cwd=MS + "/app", win="proteus-projm")
    check("11 контейнер: worktree репозитория app из app — пропуск", r is None, r)
    r = run({"path": ".claude/worktrees/p1"}, cwd=MS + "/app", win="proteus-projm")
    check("11 контейнер: относительный path из app — пропуск", r is None, r)
    r = run({"path": MS + "/app/.claude/worktrees/p1"}, cwd=MS + "/app/src", win="proteus-projm")
    check("11 контейнер: из подпапки app — пропуск", r is None, r)
    r = run({"path": MS + "/app/.claude/worktrees/p1"}, cwd=MS, win="proteus-projm")
    check("11 контейнер: из самого контейнера — отказ с подсказкой cd в app",
          bool(r) and f"cd {MS}/app`" in r, r)
    r = run({"path": MS + "/gpu-worker/.claude/worktrees/g1"}, cwd=MS + "/app", win="proteus-projm")
    check("11 контейнер: worktree соседнего репозитория из app — отказ с cd в gpu-worker",
          bool(r) and f"cd {MS}/gpu-worker`" in r, r)
    r = run({"path": MS + "/app/.claude/worktrees/p1"}, cwd=MS + "/app/.claude/worktrees/p1", win="proteus-projm")
    check("11 контейнер: сессия уже в worktree app — пропуск", r is None, r)
    # вложенный репозиторий (Д): сессия в LW/data, path в worktree родителя LW — Claude Code спросил бы владельца
    r = run({"path": LW + "/.claude/worktrees/a"}, cwd=LW + "/data")
    check("12 вложенный репозиторий: из LW/data в LW/.claude/worktrees/a — отказ с cd в LW",
          bool(r) and f"cd {LW}`" in r, r)
    r = run({"path": LW + "/.claude/worktrees/a"}, cwd=LW + "/data/.claude/worktrees/z")
    check("12 вложенный репозиторий: из worktree LW/data — отказ", bool(r) and f"cd {LW}`" in r, r)

    # настройки проекта не папки запуска (ревью argus 2 PR #360, Б): allow, sandbox, hooks, env расширили бы окно
    def settings(folder, data, fn="settings.json"):
        os.makedirs(os.path.join(folder, ".claude"), exist_ok=True)
        f = os.path.join(folder, ".claude", fn)
        with open(f, "w") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))
        return f
    f = settings(EC, {"permissions": {"allow": ["Bash(mailkeeper scan *)"]},
                      "sandbox": {"excludedCommands": ["mailkeeper *"]}})
    r = run({"path": WT}, cwd=EC)
    check("13 вторая папка с allow и excludedCommands — отказ worktree-own с ключами",
          bool(r) and "worktree-own" in r and "permissions.allow" in r and "sandbox.excludedCommands" in r, r)
    r = run({"name": "themis-0099"}, cwd=EC + "/src")
    check("13 то же с name из второй папки — отказ", bool(r) and "permissions.allow" in r, r)
    for data, key in (({"hooks": {"Stop": [{"hooks": []}]}}, "hooks"), ({"env": {"PATH": "/x"}}, "env"),
                      ({"sandbox": {"enabled": False}}, "sandbox.enabled"),
                      ({"sandbox": {"filesystem": {"allowWrite": ["/"]}}}, "sandbox.filesystem"),
                      ({"permissions": {"defaultMode": "bypassPermissions"}}, "permissions.defaultMode"),
                      ({"enabledMcpjsonServers": ["x"]}, "enabledMcpjsonServers"), ("{не json", "?"),
                      ({"permissions": ["Bash(*)"]}, "permissions")):
        settings(EC, data)
        r = run({"path": WT}, cwd=EC)
        check(f"13 ключ {key} во второй папке — отказ", bool(r) and f": {key}" in r, r)
    settings(EC, {"permissions": {"deny": ["Bash(rm *)"], "ask": ["Bash(git push *)"]},
                  "sandbox": {"autoAllowBashIfSandboxed": True, "enabled": True}, "model": "opus", "hooks": {}})
    r = run({"path": WT}, cwd=EC)
    check("13 только сужающие и пустые ключи — пропуск", r is None, r)
    os.remove(f)
    f = settings(WT, {"env": {"X": "1"}}, "settings.local.json")
    r = run({"path": WT}, cwd=EC)
    check("13 настройки в самой worktree — отказ", bool(r) and "env" in r and WT in r, r)
    os.remove(f)
    f = settings(LW, {"hooks": {"Stop": [{"hooks": []}]}, "permissions": {"allow": ["Bash(ls)"]}})
    r = run({"path": LW + "/.claude/worktrees/a"}, cwd=LW)
    check("13 папка запуска со своими настройками — пропуск (окно их приняло)", r is None, r)
    r = run({"name": "themis-0100"}, cwd=LW)
    check("13 name в папке запуска — пропуск", r is None, r)
    os.remove(f)
    r = run({"path": WT}, cwd=EC)
    check("13 настройки убраны — снова пропуск", r is None, r)

    r = run({"path": os.path.join(root, "projects/stray/.claude/worktrees/y")}, cwd=LW)
    check("5 вне папок направлений — отказ", bool(r) and "worktree-own" in r and "themis-repos" in r, r)
    r = run({"name": "themis-0021"}, cwd=LW)
    check("6 EnterWorktree с name — молчит", r is None, r)
    r = run({"path": ""}, cwd=LW)
    check("6 пустой path — молчит", r is None, r)
    r = run({"path": BA + "/.claude/worktrees/x"}, win="")
    check("7 вне окна (нет PANTHEON_WINDOW) — молчит", r is None, r)
    r = run({"path": BA + "/.claude/worktrees/x"}, win="workshop")
    check("7 окно не из domains.json (мастерская) — молчит", r is None, r)
    os.environ["PANTHEON_WINDOW"] = "themis-repos"
    r = g.check_worktree_own({"cwd": LW}, "Bash", {"path": BA + "/.claude/worktrees/x"})
    check("8 другой инструмент — молчит", r is None, r)
    os.environ["PANTHEON_WINDOW"] = "themis-repos"
    r = g.check_window({"cwd": LW}, "EnterWorktree", {"path": BA + "/.claude/worktrees/x"})
    check("9 check_window: правило подключено", isinstance(r, str) and "worktree-own" in r, r)
    check("9 EnterWorktree — инструмент окна (WINDOW_ONLY_TOOLS)", "EnterWorktree" in g.WINDOW_ONLY_TOOLS)
    with open(os.path.join(HOOKS, "hooks.json")) as fh:
        matchers = [x["matcher"] for x in json.load(fh)["hooks"]["PreToolUse"]
                    if any("hookd.sh" in h["command"] or "guard.py" in h["command"] for h in x["hooks"])]
    check("9 хук плагина ловит EnterWorktree", any("EnterWorktree" in m.split("|") for m in matchers), matchers)

    # хук целиком: guard.py --strict и без аргумента (хук плагина) — deny на чужой репозиторий, пропуск на свой
    def hook(path, cwd, *argv):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": root, "PANTHEON_WINDOW": "themis-repos",
               "PANTHEON_ROLE": "domain-coordinator", "CLAUDE_PROJECT_DIR": LW}
        ev = {"hook_event_name": "PreToolUse", "tool_name": "EnterWorktree", "tool_input": {"path": path},
              "cwd": cwd, "session_id": "sess-wtown-" + ("strict" if argv else "plugin")}
        p = subprocess.run([sys.executable, "-I", GUARD, *argv], input=json.dumps(ev), capture_output=True, text=True,
                           env=env, timeout=60)
        out = json.loads(p.stdout) if p.stdout.strip() else {}
        return p.returncode, (out.get("hookSpecificOutput") or {}), p.stderr
    for argv in (("--strict",), ()):
        code, out, err = hook(BA + "/.claude/worktrees/x", LW, *argv)
        check(f"10 хук {' '.join(argv) or 'плагина'}: чужой репозиторий — deny worktree-own",
              code == 0 and out.get("permissionDecision") == "deny" and "worktree-own" in out.get("permissionDecisionReason", ""),
              (code, out, err))
        code, out, err = hook(WT, EC, *argv)
        check(f"10 хук {' '.join(argv) or 'плагина'}: свой репозиторий из его папки — пропуск",
              code == 0 and not out, (code, out, err))
finally:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(root, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
