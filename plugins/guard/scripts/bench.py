#!/usr/bin/env python3
"""Замер холодного вызова хуков guard (metis-0330): каждый хук — новый процесс, как его зовёт Claude Code.

    python3 -I plugins/guard/scripts/bench.py [-n 20] [--out замер.json] [--hooks <папка hooks>] [--real-home]
    python3 -I plugins/guard/scripts/bench.py --hookd [-n 20] [--out замер.json] [--hooks <папка hooks>]

Для событий PreToolUse Bash, Read, Edit и PostToolUse Bash меряет по отдельности guard плагина (без аргумента),
--managed, --strict и taint — все через запускатель hooks/python.sh, как в hooks.json. Плюс опоры: пустой Python
(тот же, что выбирает python.sh), импорт guard_rules из кэша .pyc и пустой /bin/sh. N прогонов после 2 прогревов,
медиана и p95 (ближайший ранг) в мс. Печатает таблицу, с --out пишет её же в JSON (сравнить «до» и «после»).

Окружение замера: HOME — новая временная папка (без меток, журналов и policy.toml), PANTHEON_* и GUARD_OFF убраны,
поэтому хук плагина не молчит и делает полную проверку на любой машине. --real-home — свой HOME, как в живой сессии
(тогда хук плагина молчит, если управляемые настройки зовут guard --managed). Числа шумят от нагрузки Mac: сравнивай
прогоны подряд и смотри load average в первой строке. Скрипт ничего не ставит и в настройки не пишет.

--hookd (metis-0330, ступень 2): холодный guard против пути через демон хуков. Во временном HOME собирает клиент
(hooks/hookd-build.sh), запускает демон с --socket в ~/.cache/pantheon/hookd и меряет вперемешку (по кругу, чтобы
нагрузка Mac делилась поровну) три команды на каждое событие и режим (плагин, --strict): `python.sh guard.py`,
`hookd.sh guard` с PANTHEON_HOOKD=1 (канарейка выключена) и `hookd.sh guard` без флага (цена оболочки). Ответы путей
сверяются (код и stdout), журнал откатов должен остаться пустым — иначе код 1. Демон убивается в конце.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HOOKS_DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")


def pct(xs, p):
    s = sorted(xs)
    return s[max(0, min(len(s) - 1, -(-p * len(s) // 100) - 1))]


def python_of(launcher):
    """Интерпретатор, который выберет python.sh: он печатает sys.executable из -c."""
    r = subprocess.run(["/bin/sh", launcher, "-c", "import sys; print(sys.executable)"], capture_output=True,
                       text=True, timeout=30)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(f"bench: python.sh не нашёл Python 3.11+ (код {r.returncode}): {r.stderr.strip()[-200:]}")
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-n", type=int, default=20, help="прогонов на хук после 2 прогревов (по умолчанию 20)")
    ap.add_argument("--out", help="записать итог в JSON")
    ap.add_argument("--hooks", default=HOOKS_DEFAULT, help="папка hooks плагина guard (по умолчанию — рядом)")
    ap.add_argument("--real-home", action="store_true", help="свой HOME вместо временного")
    ap.add_argument("--hookd", action="store_true", help="холодный guard против пути через демон хуков (вперемешку)")
    a = ap.parse_args()
    if a.n < 1:
        sys.exit("bench: -n должно быть не меньше 1")
    if a.hookd:
        if a.real_home:
            sys.exit("bench: --hookd меряет только во временном HOME (демон и клиент — там же)")
        return main_hookd(a)
    hooks = os.path.abspath(a.hooks)
    launcher = os.path.join(hooks, "python.sh")
    for f in ("python.sh", "guard.py", "guard_rules.py", "taint.py"):
        if not os.path.isfile(os.path.join(hooks, f)):
            sys.exit(f"bench: нет {f} в {hooks}")
    py = python_of(launcher)
    tmp = tempfile.mkdtemp(prefix="guard-bench-")
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PANTHEON_", "GUARD_", "CLAUDE_"))}
        if not a.real_home:
            env["HOME"] = os.path.join(tmp, "home")
            os.makedirs(env["HOME"])
        res = run(a.n, hooks, launcher, py, env, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    show(res)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
    bad = [f"{k} {h}" for k, hs in res["hooks"].items() for h, v in hs.items() if v["codes"] not in ([0], [2])]
    if bad:
        sys.exit("bench: хук вернул разные или неожиданные коды: " + ", ".join(bad))


def run(n, hooks, launcher, py, env, tmp):
    # файл событий — README.md репозитория этого скрипта (не папки --hooks): «до» и «после» судят одни пути
    readme = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "README.md"))
    if not os.path.isfile(readme):
        readme = os.path.join(tmp, "README.md")
    cwd = os.path.dirname(readme)
    tools = {"Bash": {"command": "git status --short && ls -la plugins"},
             "Read": {"file_path": readme},
             "Edit": {"file_path": readme, "old_string": "agent-kit", "new_string": "agent-kit"}}
    base = {"session_id": "bench0330abcdef12", "transcript_path": os.path.join(tmp, "no-transcript.jsonl"),
            "cwd": cwd, "permission_mode": "default", "tool_use_id": "toolu_bench"}
    guard = os.path.join(hooks, "guard.py")
    cmds = {"guard-plugin": ["/bin/sh", launcher, guard],
            "guard-managed": ["/bin/sh", launcher, guard, "--managed"],
            "guard-strict": ["/bin/sh", launcher, guard, "--strict"],
            "taint": ["/bin/sh", launcher, os.path.join(hooks, "taint.py")]}
    events = {("PreToolUse", "Bash"): list(cmds), ("PreToolUse", "Read"): ["guard-plugin", "guard-managed", "guard-strict"],
              ("PreToolUse", "Edit"): list(cmds), ("PostToolUse", "Bash"): ["guard-plugin", "taint"]}
    baselines = {"python -I пустой": [py, "-I", "-c", "pass"],
                 "sh python.sh + пустой": ["/bin/sh", launcher, "-c", "pass"],
                 "import guard_rules (.pyc)": [py, "-I", "-c", f"import sys; sys.path.insert(0, {hooks!r}); "
                                                              "import guard_rules"],
                 "/bin/sh -c true": ["/bin/sh", "-c", "true"]}

    def one(argv, stdin):
        t = time.perf_counter()
        r = subprocess.run(argv, input=stdin, capture_output=True, env=env, cwd=cwd, timeout=60)
        return (time.perf_counter() - t) * 1000, r.returncode

    def series(argv, stdin):
        for _ in range(2):
            one(argv, stdin)
        got = [one(argv, stdin) for _ in range(n)]
        ms = [g[0] for g in got]
        return {"median": round(pct(ms, 50), 1), "p95": round(pct(ms, 95), 1), "codes": sorted({g[1] for g in got})}

    res = {"n": n, "python": py, "hooks_dir": hooks, "load": [round(x, 1) for x in os.getloadavg()],
           "baselines": {}, "hooks": {}}
    for name, argv in baselines.items():
        res["baselines"][name] = series(argv, b"")
    for (ev, tool), names in events.items():
        e = dict(base, hook_event_name=ev, tool_name=tool, tool_input=tools[tool])
        if ev == "PostToolUse":
            e["tool_response"] = {"stdout": "M README.md\n" * 20, "stderr": "", "interrupted": False}
        stdin = json.dumps(e).encode()
        for h in names:
            res["hooks"].setdefault(f"{ev} {tool}", {})[h] = series(cmds[h], stdin)
    res["load_end"] = [round(x, 1) for x in os.getloadavg()]
    return res


def main_hookd(a):
    hooks = os.path.abspath(a.hooks)
    for f in ("python.sh", "guard.py", "daemon.py", "hookd.sh", "hookd-build.sh"):
        if not os.path.isfile(os.path.join(hooks, f)):
            sys.exit(f"bench: нет {f} в {hooks}")
    tmp = tempfile.mkdtemp(prefix="gb")
    daemon = None
    try:
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PANTHEON_", "GUARD_", "CLAUDE_"))}
        env["HOME"] = home
        r = subprocess.run(["/bin/sh", os.path.join(hooks, "hookd-build.sh")], env=env, capture_output=True,
                           text=True, timeout=300)
        if r.returncode != 0:
            sys.exit(f"bench: клиент не собран: {r.stderr.strip()[-300:]}")
        subprocess.run([r.stdout.strip()], input=b"", capture_output=True, timeout=30)  # первая проверка файла macOS
        sock = os.path.join(home, ".cache", "pantheon", "hookd", "hookd.sock")
        if len(sock) > 103:
            sys.exit(f"bench: путь сокета длиннее 103 байт ({sock}) — задай TMPDIR короче")
        daemon = subprocess.Popen(["/bin/sh", os.path.join(hooks, "python.sh"), os.path.join(hooks, "daemon.py"),
                                   "--socket", sock], env=env, stdout=subprocess.DEVNULL,
                                  stderr=open(os.path.join(tmp, "daemon.log"), "wb"))
        end = time.monotonic() + 30
        while not os.path.exists(sock) and daemon.poll() is None and time.monotonic() < end:
            time.sleep(0.02)
        if not os.path.exists(sock):
            sys.exit("bench: демон не создал сокет")
        res = run_hookd(a.n, hooks, env, tmp)
        fb = os.path.join(home, ".local", "state", "pantheon", "logs", "hookd-fallback.log")
        res["fallbacks"] = open(fb, encoding="utf-8").read().splitlines() if os.path.exists(fb) else []
    finally:
        if daemon is not None and daemon.poll() is None:
            daemon.kill()
            daemon.wait()
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"N={res['n']} вперемешку  load {res['load'][0]} → {res['load_end'][0]}")
    for key, v in res["cases"].items():
        print(f"{key}: холодный {v['cold']['median']:6.1f} (p95 {v['cold']['p95']:6.1f})  демон {v['hookd']['median']:6.1f}"
              f" (p95 {v['hookd']['p95']:6.1f})  оболочка без флага {v['wrap-off']['median']:6.1f}  мс")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
    bad = [k for k, v in res["cases"].items() if not v["same"]]
    if bad or res["fallbacks"]:
        sys.exit(f"bench: ответы путей разошлись ({', '.join(bad)}) или были откаты ({res['fallbacks'][:3]})")


def run_hookd(n, hooks, env, tmp):
    readme = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "README.md"))
    if not os.path.isfile(readme):
        readme = os.path.join(tmp, "README.md")
    cwd = os.path.dirname(readme)
    tools = {"Bash": {"command": "git status --short && ls -la plugins"}, "Read": {"file_path": readme},
             "Edit": {"file_path": readme, "old_string": "agent-kit", "new_string": "agent-kit"}}
    base = {"session_id": "bench0330abcdef12", "transcript_path": os.path.join(tmp, "no-transcript.jsonl"),
            "cwd": cwd, "permission_mode": "default", "tool_use_id": "toolu_bench", "hook_event_name": "PreToolUse"}
    on = dict(env, PANTHEON_HOOKD="1", PANTHEON_HOOKD_CANARY="0")
    res = {"n": n, "hooks_dir": hooks, "load": [round(x, 1) for x in os.getloadavg()], "cases": {}}
    for tool, ti in tools.items():
        stdin = json.dumps(dict(base, tool_name=tool, tool_input=ti)).encode()
        for mode in ([], ["--strict"]):
            paths = {"cold": (["/bin/sh", os.path.join(hooks, "python.sh"), os.path.join(hooks, "guard.py"), *mode], env),
                     "hookd": (["/bin/sh", os.path.join(hooks, "hookd.sh"), "guard", *mode], on),
                     "wrap-off": (["/bin/sh", os.path.join(hooks, "hookd.sh"), "guard", *mode], env)}
            ms, outs = {k: [] for k in paths}, {k: set() for k in paths}
            for i in range(n + 2):
                for k, (argv, e) in paths.items():
                    t = time.perf_counter()
                    r = subprocess.run(argv, input=stdin, capture_output=True, env=e, cwd=cwd, timeout=60)
                    if i >= 2:  # два прогрева
                        ms[k].append((time.perf_counter() - t) * 1000)
                    outs[k].add((r.returncode, r.stdout))
            key = f"PreToolUse {tool} {'strict' if mode else 'plugin'}"
            res["cases"][key] = {k: {"median": round(pct(v, 50), 1), "p95": round(pct(v, 95), 1)} for k, v in ms.items()}
            res["cases"][key]["same"] = len(outs["cold"]) == 1 and outs["cold"] == outs["hookd"] == outs["wrap-off"]
    res["load_end"] = [round(x, 1) for x in os.getloadavg()]
    return res


def show(res):
    print(f"N={res['n']}  python {res['python']}  load {res['load'][0]} → {res['load_end'][0]}")
    for k, v in res["baselines"].items():
        print(f"  опора {k:28s} медиана {v['median']:6.1f}  p95 {v['p95']:6.1f}")
    for key, hs in res["hooks"].items():
        print(key)
        for h, v in hs.items():
            print(f"  {h:34s} медиана {v['median']:6.1f}  p95 {v['p95']:6.1f}  код {v['codes']}")


if __name__ == "__main__":
    main()
