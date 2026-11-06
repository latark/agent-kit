#!/usr/bin/env python3
"""worktree-own (metis-0911): окно направления (PANTHEON_WINDOW из domains.json) входит EnterWorktree с path только в
.claude/worktrees/ папок своего направления, и только когда сессия стоит в той же папке — так Claude Code пускает без
вопроса владельцу. Своя папка из другой точки, своя папка не под .claude/worktrees/, папка чужого направления и путь
вне папок направлений — отказ с подсказкой (cd, pantheon start <направление>, задача ему). Без path, вне окна
направления и в окне, которого нет в domains.json, правило молчит. Хук целиком (guard.py --strict и плагин) ловит
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
    for d in ("projects/legal-watch/.claude/worktrees/a", "projects/expert-corpus/.claude/worktrees/themis-0020",
              "projects/expert-corpus/src", "projects/brokerAssistantApp/.claude/worktrees/x",
              "projects/stray/.claude/worktrees/y", ".local/state/pantheon", "links",
              "projects/legal-watch/data/.claude/worktrees/z", "projects/brokerAssistantApp/fin/.claude/worktrees/q"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    os.symlink(os.path.join(root, "projects/brokerAssistantApp"), os.path.join(root, "links/ba"))
    with open(os.path.join(root, ".local/state/pantheon/domains.json"), "w") as fh:
        json.dump({"domains": {"themis-sources": ["~/projects/legal-watch", "~/projects/expert-corpus",
                                                  "~/projects/legal-watch/data"],
                               "athena-brokerassistant": ["~/projects/brokerAssistantApp"],
                               "plutus-finance": ["~/projects/brokerAssistantApp/fin"]}}, fh)
    spec = importlib.util.spec_from_file_location("guard_under_test", RULES)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    LW = os.path.join(root, "projects/legal-watch")
    EC = os.path.join(root, "projects/expert-corpus")
    BA = os.path.join(root, "projects/brokerAssistantApp")
    WT = EC + "/.claude/worktrees/themis-0020"

    def run(inp, cwd=LW, win="themis-sources"):
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
          bool(r) and "athena-brokerassistant" in r and "pantheon start athena-brokerassistant" in r
          and "directions/athena-brokerassistant/inbox/" in r, r)
    r = run({"path": BA + "/.claude/worktrees/x"}, cwd=BA)
    check("4 чужое направление и из его папки — отказ", bool(r) and "athena-brokerassistant" in r, r)
    r = run({"path": os.path.join(root, "links/ba/.claude/worktrees/x")}, cwd=LW)
    check("4 ссылка в чужой репозиторий — отказ (realpath)", bool(r) and "athena-brokerassistant" in r, r)
    r = run({"path": "~/projects/brokerAssistantApp/.claude/worktrees/x"}, cwd=LW)
    check("4 путь с ~ — отказ чужого направления", bool(r) and "athena-brokerassistant" in r, r)
    r = run({"path": LW + "/data/.claude/worktrees/z"}, cwd=LW + "/data")
    check("1 вложенная своя папка — берётся самая глубокая, пропуск", r is None, r)
    r = run({"path": BA + "/fin/.claude/worktrees/q"}, cwd=LW)
    check("4 вложенная чужая папка — называет самое глубокое направление",
          bool(r) and "pantheon start plutus-finance" in r and "athena-brokerassistant" not in r, r)
    r = run({"path": os.path.join(root, "projects/stray/.claude/worktrees/y")}, cwd=LW)
    check("5 вне папок направлений — отказ", bool(r) and "worktree-own" in r and "themis-sources" in r, r)
    r = run({"name": "themis-0021"}, cwd=LW)
    check("6 EnterWorktree с name — молчит", r is None, r)
    r = run({"path": ""}, cwd=LW)
    check("6 пустой path — молчит", r is None, r)
    r = run({"path": BA + "/.claude/worktrees/x"}, win="")
    check("7 вне окна (нет PANTHEON_WINDOW) — молчит", r is None, r)
    r = run({"path": BA + "/.claude/worktrees/x"}, win="workshop")
    check("7 окно не из domains.json (мастерская) — молчит", r is None, r)
    os.environ["PANTHEON_WINDOW"] = "themis-sources"
    r = g.check_worktree_own({"cwd": LW}, "Bash", {"path": BA + "/.claude/worktrees/x"})
    check("8 другой инструмент — молчит", r is None, r)
    os.environ["PANTHEON_WINDOW"] = "themis-sources"
    r = g.check_window({"cwd": LW}, "EnterWorktree", {"path": BA + "/.claude/worktrees/x"})
    check("9 check_window: правило подключено", isinstance(r, str) and "worktree-own" in r, r)
    check("9 EnterWorktree — инструмент окна (WINDOW_ONLY_TOOLS)", "EnterWorktree" in g.WINDOW_ONLY_TOOLS)
    with open(os.path.join(HOOKS, "hooks.json")) as fh:
        matchers = [x["matcher"] for x in json.load(fh)["hooks"]["PreToolUse"]
                    if any("hookd.sh" in h["command"] or "guard.py" in h["command"] for h in x["hooks"])]
    check("9 хук плагина ловит EnterWorktree", any("EnterWorktree" in m.split("|") for m in matchers), matchers)

    # хук целиком: guard.py --strict и без аргумента (хук плагина) — deny на чужой репозиторий, пропуск на свой
    def hook(path, cwd, *argv):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": root, "PANTHEON_WINDOW": "themis-sources",
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
