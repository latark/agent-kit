#!/usr/bin/env python3
"""Часы в контексте ролей (metis-0281): хук ctx.py clock (UserPromptSubmit) и start (SessionStart) выдают строку
«Сейчас: ДД.ММ ЧЧ:ММ (часы Mac)» в окнах ролей Пантеона; вне их и в субагенте — нет.

Запуск: python3 -I plugins/pantheon/tests/test_ctx_clock.py  (код выхода 0 — все прошли; и на /usr/bin/python3)
Часы подменены PANTHEON_NOW (секунды с эпохи), пояс TZ=Europe/Moscow.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "ctx.py")
PY = os.environ.get("CTX_TEST_PYTHON") or sys.executable
tmp = os.path.realpath(tempfile.mkdtemp(prefix="ctx-clock-test-"))
results = []
NOW = "1792408980"  # 2026-10-19 14:23 MSK
WANT = "Сейчас: 19.10 14:23 (часы Mac)"


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


def run(cmd, ev, **env):
    e = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": os.path.join(tmp, "p"),
         "PANTHEON_STATE": os.path.join(tmp, "s"), "PANTHEON_VIEW": os.path.join(tmp, "v"),
         "CLAUDE_PID": str(os.getpid()), "CLAUDE_CODE_ENTRYPOINT": "cli", "TZ": "Europe/Moscow",
         "PANTHEON_NOW": NOW}
    for k, v in env.items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = v
    return subprocess.run([PY, "-I", HOOK, cmd], input=json.dumps(ev), env=e, capture_output=True, text=True, timeout=60)


def ctx(r, event):
    try:
        o = json.loads(r.stdout)["hookSpecificOutput"]
        return o["additionalContext"] if o["hookEventName"] == event else None
    except (ValueError, KeyError):
        return None


try:
    for role in ("hq", "domain-coordinator", "workshop"):
        r = run("clock", {"session_id": "s1", "prompt": "привет"}, PANTHEON_ROLE=role)
        check("UserPromptSubmit, роль %s: строка с подменёнными часами" % role,
              ctx(r, "UserPromptSubmit") == WANT, r.stdout + r.stderr)
        r = run("start", {"session_id": "s2", "source": "startup", "transcript_path": os.path.join(tmp, "t.jsonl")},
                PANTHEON_ROLE=role)
        check("SessionStart, роль %s: строка с подменёнными часами" % role,
              WANT in (ctx(r, "SessionStart") or ""), r.stdout + r.stderr)
    r = run("clock", {"session_id": "s3", "prompt": "x", "agent_type": "hq"}, PANTHEON_ROLE=None)
    check("роль из события (agent_type) — строка есть", ctx(r, "UserPromptSubmit") == WANT, r.stdout)
    r = run("clock", {"session_id": "s4", "prompt": "x"}, PANTHEON_ROLE=None)
    check("вне окон ролей — строки нет", r.stdout.strip() == "" and r.returncode == 0, r.stdout)
    r = run("start", {"session_id": "s5", "source": "startup"}, PANTHEON_ROLE=None)
    check("SessionStart вне окон ролей — строки нет", "Сейчас:" not in r.stdout, r.stdout)
    r = run("clock", {"session_id": "s6", "prompt": "x", "agent_id": "a1", "agent_type": "hq"}, PANTHEON_ROLE="hq")
    check("субагент — строки нет", r.stdout.strip() == "", r.stdout)
    r = run("clock", {"session_id": "s7", "prompt": "x"}, PANTHEON_ROLE="hq", PANTHEON_NOW=str(int(NOW) + 3600))
    check("часы меняются вместе с подменой (+1 ч → 15:23)",
          "19.10 15:23" in (ctx(r, "UserPromptSubmit") or ""), r.stdout)
    r = run("clock", {"session_id": "s8", "prompt": "x"}, PANTHEON_ROLE="hq", PANTHEON_NOW=None)
    cur = ctx(r, "UserPromptSubmit") or ""
    check("без подмены — настоящие часы, формат ДД.ММ ЧЧ:ММ",
          bool(re.fullmatch(r"Сейчас: \d\d\.\d\d \d\d:\d\d \(часы Mac\)", cur)), cur)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
