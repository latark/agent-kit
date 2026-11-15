#!/usr/bin/env python3
"""Вызов guard внутри процесса теста (_guard_inproc.call, metis-1148 Т3): решение то же, что у настоящего процесса, и
вызовы не видят друг друга и родителя.

Запуск: python3 -I plugins/guard/tests/test_guard_inproc.py   (код выхода 0 — все прошли)

Проверяет:
  - те же код, stdout и решение, что у `python3 -I _guard_shim.py guard.py` (отказ, пропуск, неразобранный вход,
    --strict), и у входа guard.py (entry) — что у `_cached_main.py guard.py` (отдельным процессом: входы не смешивают);
  - окружение вызова — ровно env: GUARD_OFF и PANTHEON_ROLE родителя до ребёнка не доходят;
  - HOME и кэши разбора у каждого вызова свои: два HOME подряд дают каждый своё решение, глобальные модуля правил в
    родителе после вызовов прежние (configure и кэши разбора — только в ребёнке);
  - срок: висящий вызов — subprocess.TimeoutExpired за срок, ребёнок погашен.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _guard_common as C  # noqa: E402
import _guard_inproc as I  # noqa: E402

CACHED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cached_main.py")
failed, total = 0, 0


def check(name, ok, detail=""):
    global failed, total
    total += 1
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f": {detail}"))


def event(home, cmd=None, write=None, role="domain-coordinator"):
    ti = {"command": cmd} if cmd is not None else {"file_path": write, "content": "x"}
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash" if cmd is not None else "Write", "tool_input": ti,
            "cwd": os.path.join(home, C.br), "session_id": "s-test", "tool_use_id": "toolu_inproc",
            "agent_type": role}


def env_of(home, **extra):
    return {"HOME": home, "PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": os.path.join(home, C.br),
            "TMPDIR": "/nonexistent-tmp", **extra}


def same(a, b):
    return (a.returncode, a.stdout) == (b.returncode, b.stdout)


def shim_checks(home):
    alerts = os.path.join(home, "ai/pantheon/alerts.md")
    evs = [("отказ pantheon-acl", [], json.dumps(event(home, write=alerts))),
           ("пропуск ls", [], json.dumps(event(home, cmd="ls"))),
           ("неразобранный вход", [], "не json"),
           ("--strict, отказ", ["--strict"], json.dumps(event(home, write=alerts)))]
    for name, argv, stdin in evs:
        a = I.call(argv, env_of(home), stdin)
        b = C.hook(argv, env_of(home), stdin, proc=True)
        check(f"как процесс: {name} — код {a.returncode}", same(a, b), f"{a} против {b}")
    deny = json.dumps(event(home, write=alerts))
    check("предусловие: отказ — правилом pantheon-acl, GUARD_OFF=pantheon-acl его снимает",
          '"deny"' in I.call([], env_of(home), deny).stdout
          and '"deny"' not in I.call([], env_of(home, GUARD_OFF="pantheon-acl"), deny).stdout)
    os.environ["GUARD_OFF"] = "pantheon-acl"
    os.environ["PANTHEON_ROLE"] = "hq"
    try:
        r = I.call([], env_of(home), deny)
    finally:
        del os.environ["GUARD_OFF"], os.environ["PANTHEON_ROLE"]
    check("окружение — ровно env: GUARD_OFF и PANTHEON_ROLE родителя не доходят (отказ остался)",
          '"deny"' in r.stdout, r)
    other = C.new_home(merge=False)
    pol = os.path.join(other, ".claude/pantheon/policy.toml")
    os.remove(pol)  # без политики gh pr merge закрыт всем
    m = os.path.join(home, C.ak)
    ev = lambda h: json.dumps(dict(event(h, cmd="gh pr merge 1"), cwd=os.path.join(h, C.alex)))  # noqa: E731
    got = [I.call([], env_of(h), ev(h)).stdout for h in (home, other, home)]
    want = [C.hook([], env_of(h), ev(h), proc=True).stdout for h in (home, other, home)]
    check("два HOME подряд — у каждого своё решение, как у процессов", got == want and len(set(got)) == 2,
          f"{got} / {want} ({m})")
    g = I._loaded(False)
    check("родитель после вызовов не тронут: HOME модуля правил и кэши разбора — как после загрузки",
          g.HOME != home and g.HOME != other and not g._ANALYSIS, f"HOME {g.HOME}, кэш {len(g._ANALYSIS)}")
    t0 = time.monotonic()
    env = env_of(home, GUARD_SHIM_HANG="check_domain", GUARD_SHIM_DEADLINE="30")
    try:
        I.call([], env, json.dumps(event(home, cmd="ls")), timeout=1)
        check("срок: висящий вызов — TimeoutExpired", False, "вернулся")
    except subprocess.TimeoutExpired:
        took = time.monotonic() - t0
        kids = subprocess.run(["pgrep", "-P", str(os.getpid())], capture_output=True, text=True).stdout.split()
        check(f"срок: висящий вызов — TimeoutExpired за {took:.1f} с, ребёнок погашен", took < 5 and not kids, kids)


def entry_checks(home):
    """Вход guard.py (entry) против _cached_main.py guard.py — в своём процессе: модуль guard тут — правила шима."""
    alerts = os.path.join(home, "ai/pantheon/alerts.md")
    out = []
    for name, stdin in (("отказ", json.dumps(event(home, write=alerts))), ("пропуск", json.dumps(event(home, cmd="ls"))),
                        ("неразобранный вход", "не json")):
        a = I.call([], env_of(home), stdin, entry=True)
        b = subprocess.run([sys.executable, "-I", CACHED, I.GUARD], input=stdin, capture_output=True, text=True,
                           env=env_of(home), timeout=C.SUB_TIMEOUT)
        out.append([f"вход guard.py как процесс: {name} — код {a.returncode}", same(a, b), f"{a} против {b}"])
    print(json.dumps(out, ensure_ascii=False))


def main():
    if sys.argv[1:2] == ["--entry"]:
        return entry_checks(sys.argv[2])
    home = C.new_home()
    shim_checks(home)
    r = subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "--entry", home], capture_output=True,
                       text=True, timeout=C.SUB_TIMEOUT * 3)
    try:
        rows = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        rows = [["вход guard.py: проба", False, f"код {r.returncode} {r.stderr[-300:]}"]]
    for name, ok, detail in rows:
        check(name, ok, detail)
    print(f"\n{total - failed} из {total} прошли")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
