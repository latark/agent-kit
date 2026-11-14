#!/usr/bin/env python3
"""guard, часть «hooks»: входы хука через настоящий процесс и внутри процесса: Stop без транскрипта, сбой — код 2 во всех режимах (metis-0094), журнал сбоев, управляемые настройки, сбой проверки окна, перезапуск со старого Python (metis-0571).

Общее (подменённый HOME, фикстуры, вызов хука внутри процесса и через процесс, прогон таблицы) — _guard_common.py;
разрез test_guard.py — metis-1148 (план 1.0, Т2).
Запуск: python3 -I plugins/guard/tests/test_guard_hooks.py   (код выхода 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _guard_common import *  # noqa: E402, F403


OLD_PYTHON = "/usr/bin/python3"  # на macOS — 3.9 из Command Line Tools


def old_python_checks(home, br, cases):
    """metis-0571: управляемые настройки, поставленные раньше, и окна до пересборки зовут guard голым python3. Если это
    системный 3.9, guard перезапускается запускателем hooks/python.sh и работает целиком: corpus-role читает [corpus]
    policy.toml (до metis-0571 на 3.9 правило молча пропускало). Круг (запускатель вернул старый Python) — код 2."""
    failed = 0
    old = subprocess.run([OLD_PYTHON, "-c", "import sys; print(sys.version_info < (3, 11))"], capture_output=True,
                         text=True, timeout=SUB_TIMEOUT).stdout.strip() if os.path.exists(OLD_PYTHON) else ""
    if old != "True":
        print(f"пропуск: {OLD_PYTHON} нет или он 3.11+ — перезапуск guard со старого Python не проверить")
        return 0
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "agent_type": "domain-coordinator",
             "tool_input": {"command": "corpus add https://youtu.be/x"}, "cwd": os.path.join(home, br),
             "session_id": "s-test", "tool_use_id": "toolu_" + uuid.uuid4().hex}
    env = {"HOME": home, "PATH": "/usr/bin:/bin:" + os.path.dirname(sys.executable), "TMPDIR": "/nonexistent-tmp",
           "CLAUDE_PROJECT_DIR": os.path.join(home, br)}
    for label, extra in (("плагин", []), ("--managed", ["--managed"]), ("--strict", ["--strict"])):
        r = subprocess.run([OLD_PYTHON, GUARD] + extra, input=json.dumps(event), capture_output=True, text=True,
                           env=env, timeout=SUB_TIMEOUT)
        ok = r.returncode == 0 and '"deny"' in r.stdout and "corpus-role" in r.stdout
        failed += not ok
        cases.append(None)
        print(f"{'ok  ' if ok else 'FAIL'} {OLD_PYTHON} (3.9) {label}: guard перезапущен на 3.11+, corpus-role закрыт"
              + ("" if ok else f": код {r.returncode} {r.stdout[:200]} {r.stderr[:300]}"))
    r = subprocess.run([OLD_PYTHON, GUARD], input=json.dumps(event), capture_output=True, text=True,
                       env=dict(env, GUARD_PY_REEXEC="1"), timeout=SUB_TIMEOUT)
    ok = r.returncode == 2 and "нужен Python 3.11+" in r.stderr
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} старый Python после перезапуска (круг) — код 2 с причиной"
          + ("" if ok else f": код {r.returncode} {r.stderr[:300]}"))
    return failed


def failure_checks(home, env, cases):
    """metis-0094: искусственный сбой в каждом хуке guard → код 2 и причина в stderr (Stop — код 0). Подмена функций —
    через GUARD_SHIM_BOOM / GUARD_SHIM_HANG в _guard_shim.py. Возвращает число упавших проверок.
    Внутри процесса теста (_guard_inproc.call, те же подмены шима) — подмены функций; настоящим процессом (proc) —
    неразобранный вход в каждом режиме, PostToolUse без сбоя, Stop и обычный отказ (metis-1148)."""
    failed = 0
    ak = "projects/agent-kit"
    mf = os.path.join(home, "managed-fail.json")  # управляемые настройки вызывают guard --managed
    with open(mf, "w") as fh:
        fh.write('{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 guard.py --managed"}]}]}}')

    def hook(stdin, mode=None, role="", tool="Bash", ti=None, name="PreToolUse", penv=None, extra=None, proc=False):
        if stdin is None:
            ev = {"hook_event_name": name, "session_id": "s-test", "cwd": os.path.join(home, ak),
                  "tool_use_id": "toolu_" + uuid.uuid4().hex}
            if tool:
                ev.update(tool_name=tool, tool_input=ti if ti is not None else {"command": "ls"})
            if role:
                ev["agent_type"] = role
            ev.update(extra or {})
            stdin = json.dumps(ev)
        e = dict(env, CLAUDE_PROJECT_DIR=os.path.join(home, ak), **(penv or {}))
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, "-I", SHIM, GUARD] + ([mode] if mode else []), input=stdin,
                           capture_output=True, text=True, env=e, timeout=SUB_TIMEOUT) if proc \
            else call([mode] if mode else [], e, stdin)
        return r, time.monotonic() - t0

    def check(name, ok, r=None):
        nonlocal failed
        failed += not ok
        cases.append(None)
        tail = f" — код {r.returncode}, stderr {r.stderr.strip()[:160]!r}" if (r is not None and not ok) else ""
        print(f"{'ok  ' if ok else 'FAIL'} сбой (metis-0094): {name}{tail}")

    def blocked(r, word):
        return r.returncode == 2 and word in r.stderr and "Traceback" not in r.stderr and '"deny"' not in r.stdout

    # неразобранный вход — во всех режимах, и у хука плагина при активных управляемых настройках (раньше молчал)
    for label, mode, penv in (("плагин", None, None), ("--managed", "--managed", None), ("--strict", "--strict", None),
                              ("плагин при управляемых настройках", None, {"GUARD_SHIM_MANAGED": mf})):
        r, _ = hook("не json", mode, penv=penv, proc=True)
        check(f"событие не JSON, {label} — код 2 и причина", blocked(r, "не JSON"), r)
    for label, stdin in (("массив", "[1, 2]"), ("строка", '"x"'), ("объект без hook_event_name", "{}")):
        r, _ = hook(stdin)
        check(f"событие не объект события ({label}) — код 2", blocked(r, "не разобрать"), r)
    # PreToolUse: исключение в проверке прав — блок и в вашей сессии без роли, во всех режимах
    for label, boom, mode, tool, ti in (
            ("domain, ваша сессия", "check_domain", None, "Bash", None),
            ("pantheon-acl, --managed", "check_pantheon", "--managed", "Bash", None),
            ("карта прав (check_roles), --strict", "check_roles", "--strict", "Read", {"file_path": "/etc/hosts"}),
            ("protect_config.py", "check_protect_config", None, "Write",
             {"file_path": os.path.join(home, ak, "x.txt"), "content": "x"}),
            ("tg-secret", "check_tg_secret_bash", None, "Bash", None)):
        r, _ = hook(None, mode, tool=tool, ti=ti, penv={"GUARD_SHIM_BOOM": boom})
        check(f"PreToolUse, {label} — код 2 и причина", blocked(r, "сбой проверки"), r)
    # merge_gate.py в PreToolUse: gh pr merge координатора — сбой запора не пропускает
    r, _ = hook(None, role="domain-coordinator", ti={"command": "gh pr merge 5 --match-head-commit " + "a" * 40},
                penv={"GUARD_SHIM_BOOM": "merge_gate.merge_problem"})  # правила зовут его через _mg() (metis-0330)
    check("PreToolUse, merge_gate.py (gh pr merge) — код 2", blocked(r, "сбой проверки прав"), r)
    # окно (hq-telegram, chiron): и в окне штаба, и в вашей сессии без роли — блок (раньше у вас — пропуск)
    for label, penv in (("окно штаба", {"PANTHEON_ROLE": "hq"}), ("ваша сессия", {})):
        r, _ = hook(None, tool="Agent", ti={"subagent_type": "x", "prompt": "x"},
                    penv=dict(penv, GUARD_SHIM_BOOM="check_hq_telegram"))
        check(f"PreToolUse Agent, сбой проверки окна, {label} — код 2", blocked(r, "сбой проверки окна"), r)
    # аргументы вызова не объект — сбой скрипта, код 2
    r, _ = hook(None, ti=["ls"])
    check("PreToolUse, tool_input не объект — код 2", blocked(r, "сбой хука"), r)
    # свой срок: проверка висит — код 2 до таймаута хука, а не пропуск по таймауту Claude Code
    r, took = hook(None, penv={"GUARD_SHIM_HANG": "check_domain", "GUARD_SHIM_DEADLINE": "1"})
    check(f"PreToolUse, проверка висит — код 2 за {took:.1f} с", blocked(r, "не уложилась") and took < 8, r)
    # подсказка (dev-server) при сбое пропускает к остальным проверкам — обычная команда проходит
    r, _ = hook(None, penv={"GUARD_SHIM_BOOM": "check_dev_server"})
    check("PreToolUse, сбой подсказки dev-server — пропуск к остальным проверкам (код 0)",
          r.returncode == 0 and r.stdout.strip() == "", r)
    # PostToolUse: сбой записи журнала запора — код 2 (команда уже выполнена, причина — агенту); без сбоя — 0
    post = {"tool_response": {"stdout": "", "stderr": "", "interrupted": False, "isImage": False}}
    r, _ = hook(None, name="PostToolUse", extra=post, penv={"GUARD_SHIM_BOOM": "merge_gate.record"})
    check("PostToolUse, сбой merge_gate.record — код 2 и причина", blocked(r, "журнала шлюза слияния"), r)
    r, _ = hook(None, name="PostToolUse", extra=post, proc=True)
    check("PostToolUse без сбоя — код 0", r.returncode == 0 and r.stderr == "", r)
    # Stop: сбой — код 0 (код 2 не дал бы закончить ход), причина в stderr и строка в журнале
    r, _ = hook(None, name="Stop", tool=None, extra={"transcript_path": os.path.join(home, "none.jsonl")},
                penv={"GUARD_SHIM_BOOM": "soft"}, proc=True)
    check("Stop, сбой — код 0, без трассировки, с причиной", r.returncode == 0 and "Stop" in r.stderr
          and "Traceback" not in r.stderr and '"block"' not in r.stdout, r)
    # сбой загрузки самого guard (рядом нет merge_gate.py; нет модуля правил guard_rules.py у входа guard.py,
    # metis-0148) — тоже код 2 с причиной, на Stop — 0; запуск как у хука
    pc = os.path.join(os.path.dirname(RULES), "protect_config.py")
    for what, files in (("нет merge_gate.py", (GUARD, RULES, pc)), ("нет protect_config.py", (GUARD, RULES)),
                        ("нет guard_rules.py", (GUARD,))):
        lone = tempfile.mkdtemp(prefix="guard-lone-")
        for f in files:
            shutil.copy(f, lone)
        for label, ev, want in (("PreToolUse", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                                "tool_input": {"command": "ls"}}, 2),
                                ("Stop", {"hook_event_name": "Stop"}, 0)):
            r = subprocess.run([sys.executable, "-I", os.path.join(lone, "guard.py")], input=json.dumps(ev),
                               capture_output=True, text=True, env=env, timeout=SUB_TIMEOUT)
            check(f"сбой загрузки guard ({what}), {label} — код {want} и причина",
                  r.returncode == want and "сбой загрузки" in r.stderr and "Traceback" not in r.stderr, r)
        shutil.rmtree(lone, ignore_errors=True)
    # обычные отказ и пропуск прежние: отказ — JSON и код 0
    r, _ = hook(None, role="domain-coordinator", ti={"command": "tmux send-keys -t 0 'да' Enter"}, proc=True)
    check("обычный отказ — JSON deny и код 0, как раньше", r.returncode == 0 and '"deny"' in r.stdout, r)
    return failed


def stop_checks(cases):
    """metis-0079: Stop без транскрипта — через настоящий процесс. → число упавших."""
    failed = 0
    # metis-0079: Stop без транскрипта (файла нет / по пути папка) — без сбоя в журнале и без блокировки
    stop_home = tempfile.mkdtemp(prefix="guard-stop-")
    stop_log = os.path.join(stop_home, ".local/state/pantheon/logs/guard-failures.log")
    stop_env = {"HOME": stop_home, "PATH": os.environ["PATH"], "TMPDIR": "/nonexistent-tmp"}
    good = os.path.join(stop_home, "good.jsonl")
    with open(good, "w") as fh:
        fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "привет"}}) + "\n")
    os.makedirs(os.path.join(stop_home, "dir.jsonl"))
    for label, tp in (("файла нет", os.path.join(stop_home, "gone.jsonl")),
                      ("по пути папка", os.path.join(stop_home, "dir.jsonl")),
                      ("обычный транскрипт", good)):
        if os.path.exists(stop_log):  # свой журнал на каждый случай: FAIL достаётся тому, кто его вызвал
            os.remove(stop_log)
        ev ={"hook_event_name": "Stop", "transcript_path": tp, "session_id": "s-test", "cwd": stop_home}
        r = subprocess.run([sys.executable, "-I", SHIM, GUARD], input=json.dumps(ev), capture_output=True, text=True,
                           env=stop_env, timeout=SUB_TIMEOUT)
        ok = r.returncode == 0 and '"block"' not in r.stdout and '"deny"' not in r.stdout \
            and not os.path.exists(stop_log)
        failed += not ok
        cases.append(None)
        print(f"{'ok  ' if ok else 'FAIL'} Stop, {label}: код {r.returncode}, без блокировки и без записи в журнал сбоев")
    shutil.rmtree(stop_home, ignore_errors=True)
    return failed


def managed_checks(home, env, cases):
    """Управляемые настройки и сбой проверки окна — пробы своим процессом с подменой модуля. → число упавших."""
    failed = 0
    # управляемые настройки вызывают guard (--managed) — хук плагина молчит; без них — работает
    probe = os.path.join(home, "managed-probe.py")
    with open(probe, "w") as fh:
        fh.write("import sys, json, importlib.util\n"
                 "spec = importlib.util.spec_from_file_location('g', sys.argv[1]); g = importlib.util.module_from_spec(spec)\n"
                 "spec.loader.exec_module(g)\n"
                 "g.MANAGED_FILE, g.MARKET_GUARD = sys.argv[2], sys.argv[1]\n"
                 "print(g.managed_guard_active())\n")
    mf = os.path.join(home, "managed.json")
    results = []
    for content in ('{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 guard.py --managed"}]}]}}',
                    '{"permissions": {"deny": ["Bash(x)"]}}', "битый json"):
        open(mf, "w").write(content)
        results.append(subprocess.run([sys.executable, "-I", probe, RULES, mf], capture_output=True, text=True,
                                      env=env, timeout=SUB_TIMEOUT).stdout.strip())
    ok = results == ["True", "False", "False"]
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} управляемые настройки: хук плагина молчит только при guard --managed: {results}")
    # P0-1: при управляемых настройках с guard --managed хук плагина Agent, Task и Skill всё равно проверяет
    # (управляемые настройки их guard не передают), а Bash — пропускает (его проверяет хук --managed)
    probe2 = os.path.join(home, "managed-main.py")
    with open(probe2, "w") as fh:
        fh.write("import sys, io, importlib.util\n"
                 "spec = importlib.util.spec_from_file_location('g', sys.argv[1]); g = importlib.util.module_from_spec(spec)\n"
                 "spec.loader.exec_module(g)\n"
                 "g.MANAGED_FILE, g.MARKET_GUARD, g.MODE = sys.argv[2], sys.argv[1], 'plugin'\n"
                 "sys.stdin = io.StringIO(sys.argv[3])\n"
                 "g.main()\n")
    open(mf, "w").write('{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 guard.py --managed"}]}]}}')
    menv = dict(env, PANTHEON_ROLE="hq")
    outs = {}
    for label, tool, ti in (("Agent", "Agent", {"subagent_type": "tg-reader", "prompt": "x"}),
                            ("Skill", "Skill", {"skill": "telegram-read"}),
                            ("Bash", "Bash", {"command": "pnpm dev"})):
        ev = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti, "session_id": "s-test",
              "cwd": os.path.join(home, "ai/pantheon"), "agent_type": "hq"}
        outs[label] = subprocess.run([sys.executable, "-I", probe2, RULES, mf, json.dumps(ev)], capture_output=True,
                                     text=True, env=menv, timeout=SUB_TIMEOUT).stdout
    ok = '"deny"' in outs["Agent"] and "hq-telegram" in outs["Agent"] and '"deny"' in outs["Skill"] \
        and outs["Bash"].strip() == ""
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} управляемые настройки: хук плагина проверяет Agent и Skill (hq-telegram), Bash — нет")
    # сбой проверки окна — отказ и в главной сессии окна роли без agent_type (strict_window)
    probe3 = os.path.join(home, "window-fail.py")
    with open(probe3, "w") as fh:
        fh.write("import sys, io, importlib.util\n"
                 "spec = importlib.util.spec_from_file_location('g', sys.argv[1]); g = importlib.util.module_from_spec(spec)\n"
                 "spec.loader.exec_module(g)\n"
                 "def boom(*a):\n    raise RuntimeError('x')\n"
                 "g.check_hq_telegram = boom\n"
                 "g.MANAGED_FILE = sys.argv[2]\n"
                 "sys.stdin = io.StringIO(sys.argv[3])\n"
                 "g.run_hook()\n")
    ev = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": {"subagent_type": "x", "prompt": "x"},
          "session_id": "s-test", "cwd": os.path.join(home, "ai/pantheon")}
    got = [subprocess.run([sys.executable, "-I", probe3, RULES, os.path.join(home, "no-managed.json"), json.dumps(ev)],
                          capture_output=True, text=True, env=e, timeout=SUB_TIMEOUT) for e in (menv, env)]
    ok = all(r.returncode == 2 and "сбой проверки окна" in r.stderr for r in got)
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} сбой проверки окна: и в окне роли, и в вашей сессии без роли — код 2 (metis-0094)")
    return failed


def main():
    home = new_home()
    br = "projects/shopKeeperApp"
    cases, failed = [], 0
    failed += old_python_checks(home, br, cases)
    failed += stop_checks(cases)
    # metis-0094: любой сбой — код 2 и причина в stderr во всех режимах (плагин, --managed, --strict), в вашей сессии
    # тоже; ни выхода 0 (пропуск), ни трассировки с кодом 1. Исключение — Stop (код 2 не дал бы закончить ход)
    env = {"HOME": home, "PATH": os.environ["PATH"], "TMPDIR": "/nonexistent-tmp"}
    failed += failure_checks(home, env, cases)
    log = os.path.join(home, ".local/state/pantheon/logs/guard-failures.log")
    lines = open(log).read().splitlines() if os.path.exists(log) else []
    ok = any("\tstrict\tmain\tJSONDecodeError" in x for x in lines) and any("\tplugin\tmain\t" in x for x in lines) \
        and any("\tmanaged\tmain\t" in x for x in lines) and not any("не json" in x for x in lines)
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} журнал сбоев: {len(lines)} строк, без текста ввода")
    failed += managed_checks(home, env, cases)
    finish(cases, failed)


if __name__ == "__main__":
    main()
