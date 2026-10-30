#!/usr/bin/env python3
"""Вход hooks/guard.py (metis-0148): короткий файл, правила — модуль guard_rules.py из кэша .pyc, одна полная проверка
на вызов.

Запуск: python3 -I plugins/guard/tests/test_entry.py   (код выхода 0 — все прошли)
- вход не держит правил: короткий, а guard_rules.py после первого запуска лежит в __pycache__ и не пересобирается;
- постоянные входа совпадают с guard_rules.py, managed_guard_active — те же ответы на одних файлах;
- решения «молчать» (правила подменены заглушкой, которая печатает RULES): хук плагина при управляемых настройках —
  как раньше, Agent/Task/Skill и PostToolUse — не молчит; метка строгого guard: молчит только хук плагина своей
  сессии, своего окна и инструмента, который строгий guard уже проверил, а --managed проверяет всегда; ссылка вместо метки,
  чужое окно, другая сессия, нет окна, WebFetch, Stop, плохой session_id, метка старше 10 мин — полная проверка;
  уборка старых меток;
- живой запуск через hooks/python.sh: --strict отказывает и ставит метку, затем хук плагина той же сессии молчит,
  а --managed той же сессии и хук плагина с другим окном отказывают сами;
- свой срок на чтение события: stdin не закрыт — код 2 с причиной, а не пропуск по таймауту Claude Code.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(os.path.dirname(HERE), "hooks")
GUARD = os.path.join(HOOKS, "guard.py")
RULES = os.path.join(HOOKS, "guard_rules.py")
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# Пробник решений входа: guard.py грузится модулем (без __main__ он ничего не запускает), постоянные — из argv,
# guard_rules подменён заглушкой: если вход не замолчал, заглушка печатает RULES и событие.
PROBE = r"""
import importlib.util, json, os, sys, types
guard, conf = sys.argv[1], json.loads(sys.argv[2])
stub = types.ModuleType("guard_rules")
def run_hook(raw=None):
    sys.stdout.write("RULES " + raw.decode("utf-8", "replace"))
    sys.stdout.flush()
    os._exit(0)
stub.run_hook = run_hook
sys.modules["guard_rules"] = stub
spec = importlib.util.spec_from_file_location("guard_entry", guard)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
for k, v in conf.get("set", {}).items():
    setattr(g, k, v)
g.run(conf.get("argv", []))
"""

root = os.path.realpath(tempfile.mkdtemp(prefix="guard-entry-"))
home = os.path.join(root, "home")
os.makedirs(home)
os.environ["HOME"] = home
try:
    # --- вход короткий, правила — модуль из .pyc ------------------------------------------------------------------
    with open(GUARD, encoding="utf-8") as fh:
        src = fh.read()
    check("guard.py — короткий вход (< 250 строк), правил в нём нет",
          src.count("\n") < 250 and "def check_" not in src and "import guard_rules" in src, src.count("\n"))
    copy = os.path.join(root, "hooks-copy")
    shutil.copytree(HOOKS, copy, ignore=shutil.ignore_patterns("__pycache__"))
    ev = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": home,
          "session_id": "s-entry-0001"}
    env = {"HOME": home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMPDIR": root}

    def entry(args, event, folder=HOOKS, extra=None):
        data = event if isinstance(event, str) else json.dumps(event)
        return subprocess.run(["/bin/sh", os.path.join(folder, "python.sh"), os.path.join(folder, "guard.py")] + args,
                              input=data, capture_output=True, text=True, env=dict(env, **(extra or {})), timeout=30)

    r = entry([], ev, copy)
    tag = sys.implementation.cache_tag
    pyc = os.path.join(copy, "__pycache__", f"guard_rules.{tag}.pyc")
    check("первый запуск: код 0, guard_rules.py скомпилирован в __pycache__", r.returncode == 0 and os.path.isfile(pyc),
          (r.returncode, r.stderr, os.listdir(copy)))
    m0 = os.stat(pyc).st_mtime_ns if os.path.isfile(pyc) else None
    time.sleep(0.05)
    r = entry([], ev, copy)
    check("второй запуск берёт .pyc: файл кэша не пересобран", r.returncode == 0 and os.path.isfile(pyc)
          and os.stat(pyc).st_mtime_ns == m0, r.stderr)
    check("guard.py сам в кэш не попадает: он скрипт, а не модуль",
          not any(x.startswith("guard.") for x in os.listdir(os.path.join(copy, "__pycache__"))))

    # --- постоянные и managed_guard_active совпадают с guard_rules.py ----------------------------------------------
    E = load(GUARD, "guard_entry_consts")
    R = load(RULES, "guard_rules_consts")
    check("MANAGED_FILE, MARKET_GUARD, FAIL_LOG, DEADLINE входа — как у guard_rules.py",
          (E.MANAGED_FILE, E.MARKET_GUARD, E.FAIL_LOG, E.DEADLINE) == (R.MANAGED_FILE, R.MARKET_GUARD, R.FAIL_LOG,
                                                                       R.DEADLINE))
    check("WINDOW_ONLY_TOOLS входа — как у guard_rules.py", set(E.WINDOW_ONLY_TOOLS) == set(R.WINDOW_ONLY_TOOLS),
          (E.WINDOW_ONLY_TOOLS, R.WINDOW_ONLY_TOOLS))
    mf = os.path.join(root, "managed.json")
    market = os.path.join(root, "market-guard.py")
    open(market, "w").write("# guard\n")
    hook = lambda cmd, ev="PreToolUse": json.dumps({"hooks": {ev: [{"hooks": [{"type": "command", "command": cmd}]}]}})  # noqa: E731
    variants = [
        ("guard.py --managed на PreToolUse", hook("python3 guard.py --managed"), market, True),
        ("только на Stop", hook("python3 guard.py --managed", "Stop"), market, False),
        ("guard.py без --managed", hook("python3 guard.py"), market, False),
        ("нет hooks", '{"permissions": {}}', market, False),
        ("битый JSON", "{", market, False),
        ("файла guard в маркетплейсе нет", hook("python3 guard.py --managed"), os.path.join(root, "нет.py"), False),
    ]
    for label, content, mg, want in variants:
        open(mf, "w").write(content)
        got = []
        for mod in (E, R):
            mod.MANAGED_FILE, mod.MARKET_GUARD = mf, mg
            got.append(mod.managed_guard_active())
        check(f"managed_guard_active: {label} — {want} у входа и у правил", got == [want, want], got)
    os.remove(mf)

    # --- решения «молчать» (заглушка правил) -------------------------------------------------------------------------
    open(mf, "w").write(hook("python3 guard.py --managed"))
    active = {"MANAGED_FILE": mf, "MARKET_GUARD": market}
    inactive = {"MANAGED_FILE": os.path.join(root, "нет-managed.json"), "MARKET_GUARD": market}
    strict_dir = os.path.join(home, ".local", "state", "pantheon", "guard-strict")

    def probe(argv, event, conf=None, window=None, raw=None):
        e = dict(env)
        if window is not None:
            e["PANTHEON_WINDOW"] = window
        data = raw if raw is not None else json.dumps(event)
        r = subprocess.run([sys.executable, "-I", "-c", PROBE, GUARD, json.dumps({"argv": argv, "set": conf or {}})],
                           input=data, capture_output=True, text=True, env=e, timeout=30)
        return r

    def ran(r):
        return r.returncode == 0 and r.stdout.startswith("RULES ")

    def quiet(r):
        return r.returncode == 0 and r.stdout == "" and r.stderr == ""

    def pre(tool, sid="s-entry-0001"):
        return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {}, "session_id": sid, "cwd": home}

    # хук плагина при управляемых настройках — как раньше
    r = probe([], pre("Bash"), active)
    check("плагин, управляемые настройки с guard --managed, Bash — молчит, правила не грузятся", quiet(r), r)
    for tool in ("Agent", "Task", "Skill"):
        r = probe([], pre(tool), active)
        check(f"плагин, управляемые настройки, {tool} — проверяет (управляемые {tool} не передают)", ran(r), r)
    r = probe([], {"hook_event_name": "Stop", "session_id": "s-entry-0001"}, active)
    check("плагин, управляемые настройки, Stop — молчит (Stop проверяет управляемая копия)", quiet(r), r)
    r = probe([], {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "s-entry-0001"}, active)
    check("плагин, управляемые настройки, PostToolUse — не молчит (журнал запора слияния)", ran(r), r)
    r = probe([], pre("Bash"), inactive)
    check("плагин без управляемых настроек — проверяет", ran(r), r)
    for mode in (["--managed"], ["--strict"]):
        r = probe(mode, pre("Bash"), active)
        check(f"{mode[0]} при управляемых настройках — проверяет (молчит только плагин)", ran(r), r)
    r = probe([], None, active, raw="не json")
    check("событие не JSON — решает guard_rules (код 2 у правил), вход не молчит", ran(r) and "не json" in r.stdout, r)
    r = probe([], None, active, raw='{"tool_name": "Bash"}')
    check("событие без hook_event_name — решает guard_rules", ran(r), r)

    # метка строгого guard
    sid = "s-strict-0001"
    marker = os.path.join(strict_dir, sid)
    r = probe(["--strict"], pre("Bash", sid), inactive, window="w1")
    with open(marker, encoding="utf-8") if os.path.isfile(marker) else open(os.devnull) as fh:
        lines = fh.read().splitlines()
    check("--strict в окне: проверяет и ставит метку «окно\\tинструмент»", ran(r) and lines == ["w1\tBash"], (r, lines))
    check("метка — файл 0600, папка 0700", oct(os.stat(marker).st_mode & 0o777) == "0o600"
          and oct(os.stat(strict_dir).st_mode & 0o777) == "0o700")
    r = probe(["--strict"], pre("Bash", sid), inactive, window="w1")
    check("--strict повторно: проверяет снова (строгий никогда не молчит), строка метки не дублируется",
          ran(r) and open(marker).read().splitlines() == ["w1\tBash"], r)
    r = probe(["--managed"], pre("Bash", sid), inactive, window="w1")
    r2 = probe(["--managed"], pre("Bash", sid), active, window="w1")
    check("--managed той же сессии, окна и инструмента — всё равно проверяет (управляемая не молчит никогда)",
          ran(r) and ran(r2), (r, r2))
    r = probe([], pre("Bash", sid), inactive, window="w1")
    check("плагин (без управляемых) той же сессии, окна и инструмента — молчит", quiet(r), r)
    t = time.time() - 900
    os.utime(marker, (t, t))
    r = probe([], pre("Bash", sid), inactive, window="w1")
    check("метка старше 10 мин (строгий хук пропал из сессии) — плагин проверяет сам", ran(r), r)
    r = probe(["--strict"], pre("Bash", sid), inactive, window="w1")
    r2 = probe([], pre("Bash", sid), inactive, window="w1")
    check("строгий обновил метку повторным вызовом — плагин снова молчит",
          ran(r) and quiet(r2) and os.stat(marker).st_mtime > time.time() - 60, (r, r2))
    r = probe([], pre("Read", sid), inactive, window="w1")
    check("плагин, инструмент, который строгий ещё не проверял (Read), — проверяет", ran(r), r)
    r = probe([], pre("Bash", sid), inactive, window="w2")
    check("плагин, другое окно (PANTHEON_WINDOW) — проверяет", ran(r), r)
    r = probe([], pre("Bash", sid), inactive)
    check("плагин без PANTHEON_WINDOW (ваша сессия, `claude -r` без окна) — проверяет", ran(r), r)
    r = probe([], pre("Bash", "s-strict-0002"), inactive, window="w1")
    check("плагин, другая сессия (вложенный claude) — проверяет", ran(r), r)
    r = probe([], {"hook_event_name": "Stop", "session_id": sid}, inactive, window="w1")
    check("плагин без управляемых, Stop той же сессии — проверяет (у строгого guard Stop нет)", ran(r), r)
    r = probe([], pre("WebFetch", sid), inactive, window="w1")
    check("плагин без управляемых, WebFetch (строгий его не проверяет, метки нет) — проверяет", ran(r), r)
    r = probe([], {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": sid}, inactive, window="w1")
    check("плагин, PostToolUse той же сессии — не молчит (журнал запора слияния)", ran(r), r)
    r = probe(["--strict"], pre("Agent", sid), inactive, window="w1")
    r2 = probe([], pre("Agent", sid), active, window="w1")
    check("плагин при управляемых, Agent после строгого — молчит (Agent проверил строгий)", ran(r) and quiet(r2), (r, r2))
    for label, bad in (("путь в session_id", "../../x-escape"), ("короткий session_id", "s1"),
                       ("session_id не строка", 12345678)):
        r = probe(["--strict"], pre("Bash", bad), inactive, window="w1")
        r2 = probe([], pre("Bash", bad), inactive, window="w1")
        check(f"{label}: метки нет, строгий и плагин проверяют", ran(r) and ran(r2) and sorted(os.listdir(strict_dir)) == [sid],
              (r, r2, os.listdir(strict_dir)))
    r = probe(["--strict"], pre("Bash", "s-strict-0004"), inactive)
    r2 = probe([], pre("Bash", "s-strict-0004"), inactive)
    check("--strict без PANTHEON_WINDOW — метки нет, плагин проверяет",
          ran(r) and ran(r2) and not os.path.exists(os.path.join(strict_dir, "s-strict-0004")), (r, r2))
    r = probe(["--strict"], {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "s-strict-0005"},
              inactive, window="w1")
    check("--strict на событии не PreToolUse — проверяет, метки нет",
          ran(r) and not os.path.exists(os.path.join(strict_dir, "s-strict-0005")), r)
    r = probe(["--strict"], pre("Bash", "s-strict-0003"), inactive, window="w1\tBash")
    check("окно с табуляцией — метки нет", ran(r) and not os.path.exists(os.path.join(strict_dir, "s-strict-0003")), r)
    # ссылка вместо метки (O_NOFOLLOW): не читается и не пишется — полная проверка
    target = os.path.join(root, "fake-marker")
    open(target, "w").write("w1\tBash\n")
    os.symlink(target, os.path.join(strict_dir, "s-strict-link1"))
    r = probe([], pre("Bash", "s-strict-link1"), inactive, window="w1")
    r2 = probe(["--strict"], pre("Read", "s-strict-link1"), inactive, window="w1")
    check("метка-ссылка: плагин проверяет, --strict не пишет через ссылку и проверяет",
          ran(r) and ran(r2) and open(target).read() == "w1\tBash\n", (r, r2))
    # метка — папка: --strict не падает, проверяет
    os.makedirs(os.path.join(strict_dir, "s-strict-dir01"))
    r = probe(["--strict"], pre("Bash", "s-strict-dir01"), inactive, window="w1")
    r2 = probe([], pre("Bash", "s-strict-dir01"), inactive, window="w1")
    check("метка — папка: строгий и плагин проверяют, без сбоя", ran(r) and ran(r2), (r, r2))
    # уборка: при новой метке старые (старше 2 суток) удаляются, свежие остаются
    old = os.path.join(strict_dir, "s-strict-old01")
    open(old, "w").write("w1\tBash\n")
    t = time.time() - 3 * 86400
    os.utime(old, (t, t))
    r = probe(["--strict"], pre("Bash", "s-strict-new01"), inactive, window="w1")
    check("новая метка убирает метки старше 2 суток, свежая метка сессии остаётся",
          ran(r) and not os.path.exists(old) and os.path.isfile(marker)
          and os.path.isfile(os.path.join(strict_dir, "s-strict-new01")), os.listdir(strict_dir))
    # папку меток не создать (на её месте файл) — строгий проверяет, остальные тоже
    shutil.rmtree(strict_dir)
    os.makedirs(os.path.dirname(strict_dir), exist_ok=True)
    open(strict_dir, "w").write("x")
    r = probe(["--strict"], pre("Bash", sid), inactive, window="w1")
    r2 = probe([], pre("Bash", sid), inactive, window="w1")
    check("метку не записать (папки нет, на её месте файл) — строгий и плагин проверяют, без сбоя", ran(r) and ran(r2), (r, r2))
    os.remove(strict_dir)

    # --- живой запуск: строгий отказывает и ставит метку, хук плагина той же сессии молчит, управляемый — нет -------
    deny_ev = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "agent_type": "domain-coordinator",
               "tool_input": {"command": "tmux send-keys -t 0 x Enter"}, "cwd": home, "session_id": "s-live-0001"}
    r = entry(["--strict"], deny_ev, extra={"PANTHEON_WINDOW": "w1"})
    check("живой --strict: отказ правила terminal и метка", r.returncode == 0 and '"deny"' in r.stdout
          and os.path.isfile(os.path.join(strict_dir, "s-live-0001")), (r.returncode, r.stdout[:200], r.stderr))
    r = entry([], deny_ev, extra={"PANTHEON_WINDOW": "w1"})
    check("живой хук плагина той же сессии и окна — молчит (проверку сделал строгий)",
          r.returncode == 0 and r.stdout == "" and r.stderr == "", (r.returncode, r.stdout[:200], r.stderr))
    r = entry(["--managed"], deny_ev, extra={"PANTHEON_WINDOW": "w1"})
    check("живой --managed той же сессии и окна, метка есть — всё равно отказывает сам",
          r.returncode == 0 and '"deny"' in r.stdout, (r.returncode, r.stdout[:200], r.stderr))
    r = entry([], deny_ev, extra={"PANTHEON_WINDOW": "w2"})
    check("живой хук плагина с другим окном — отказывает сам", r.returncode == 0 and '"deny"' in r.stdout,
          (r.returncode, r.stdout[:200], r.stderr))
    r = entry([], dict(deny_ev, session_id="s-live-0002"), extra={"PANTHEON_WINDOW": "w1"})
    check("живой хук плагина другой сессии — отказывает сам", r.returncode == 0 and '"deny"' in r.stdout,
          (r.returncode, r.stdout[:200], r.stderr))

    r = entry([], "не json")
    check("живой вход, событие не JSON — код 2 и причина от правил (событие передано guard_rules байтами)",
          r.returncode == 2 and "не JSON" in r.stderr and "Traceback" not in r.stderr, (r.returncode, r.stderr))
    r = entry(["--managed"], {"hook_event_name": "Stop", "session_id": "s-live-0001", "cwd": home,
                              "transcript_path": os.path.join(home, "нет.jsonl")}, extra={"PANTHEON_WINDOW": "w1"})
    check("живой --managed, Stop — код 0 без вывода", r.returncode == 0 and r.stdout == "", (r.returncode, r.stderr))

    # --- свой срок на чтение события: stdin не закрыт -------------------------------------------------------------
    t0 = time.monotonic()
    p = subprocess.Popen([sys.executable, "-I", "-c", PROBE, GUARD, json.dumps({"argv": [], "set": {"DEADLINE": 1}})],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
    took = time.monotonic() - t0
    err = p.stderr.read()
    p.stdin.close()
    p.stdout.close()
    p.stderr.close()
    check(f"stdin не закрыт — код 2 за {took:.1f} с и причина «не уложилась» (свой срок, а не таймаут хука)",
          p.returncode == 2 and "не уложилась" in err and took < 8, (p.returncode, err))
finally:
    shutil.rmtree(root, ignore_errors=True)

print(f"\n{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
