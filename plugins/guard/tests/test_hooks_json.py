#!/usr/bin/env python3
"""onFailure=block в hooks.json guard и pantheon (metis-0094 ч.2).

Документация: https://code.claude.com/docs/en/hooks — «Block the action when a hook fails» (Claude Code ≥ 2.1.295).
Каждый обработчик PreToolUse должен иметь "onFailure": "block" (сбой хука = отказ, как exit 2); на событиях, где
поле не действует (Stop, SubagentStop, TaskCompleted, TeammateIdle, async/asyncRewake), и на PostToolUse его нет.

Запуск: python3 -I plugins/guard/tests/test_hooks_json.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # plugins/
NO_EFFECT = {"Stop", "SubagentStop", "TaskCompleted", "TeammateIdle"}
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


for plugin in ("guard", "pantheon"):
    path = os.path.join(ROOT, plugin, "hooks", "hooks.json")
    with open(path, encoding="utf-8") as f:
        hooks = json.load(f)["hooks"]
    pre = [h for g in hooks.get("PreToolUse", []) for h in g["hooks"]]
    check(f"{plugin}: PreToolUse есть", len(pre) > 0)
    bad = [h["command"][:60] for h in pre if h.get("onFailure") != "block"]
    check(f"{plugin}: каждый обработчик PreToolUse — onFailure=block ({len(pre)})", not bad, bad)
    wrong = []
    for event, groups in hooks.items():
        for g in groups:
            for h in g["hooks"]:
                if "onFailure" not in h:
                    continue
                if event != "PreToolUse" or h.get("async") or h.get("asyncRewake"):
                    wrong.append(event)
    check(f"{plugin}: onFailure только на PreToolUse, не на Stop/async/PostToolUse", not wrong, wrong)

sys.exit(0 if all(results) else 1)
