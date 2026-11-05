#!/usr/bin/env python3
"""Доля откатов демона хуков и тревога canary-diff (F9, metis-0811): scripts/hookd-stats.py.

Запуск: python3 -I plugins/guard/tests/test_hookd_stats.py   (код выхода 0 — все прошли)
- функция stats(): всего = решения демона (hookd-calls.log) + откаты (hookd-fallback.log), доля = откаты / всего;
  причины откатов по убыванию; двойной отказ (slow-exec, slow-signal, slow-fork, usage) — отдельно, не в доле;
  canary-diff — отдельно, последние три строки; окно --hours; строки без времени и битые числа — мимо;
- командная строка: без журналов — «вызовов нет», код 0; canary-diff — код 3 и «тревога: …» последней строкой;
  --json — словарь; плохие аргументы — 64; журнал — папка (не прочесть) — код 1.
Всё — во временной папке, HOME подменён.
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
PLUGIN = os.path.dirname(HERE)
SCRIPT = os.path.join(PLUGIN, "scripts", "hookd-stats.py")
LAUNCHER = os.path.join(PLUGIN, "hooks", "python.sh")
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or info is None else "\n     " + str(info)[:900]))


def load():
    spec = importlib.util.spec_from_file_location("hookd_stats", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ts(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def write(home, name, lines):
    d = os.path.join(home, ".local", "state", "pantheon", "logs")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
        fh.write("".join(x + "\n" for x in lines))


def cli(home, *args):
    r = subprocess.run(["/bin/sh", LAUNCHER, SCRIPT, *args], env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                       "HOME": home, "LANG": "en_US.UTF-8"}, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr


def main():
    S = load()
    root = tempfile.mkdtemp(prefix="hks")
    try:
        now = time.time()
        old, new = ts(now - 30 * 3600), ts(now - 3600)
        home = os.path.join(root, "a")
        write(home, "hookd-calls.log", [f"{new}\tok\t90", f"{new}\tok\t5", f"{old}\tok\t1000", f"{new}\tok\tx",
                                        "без времени\tok\t7"])
        write(home, "hookd-fallback.log", [f"{new}\tperm", f"{new}\tperm", f"{new}\tno-client", f"{old}\tperm",
                                           f"{new}\tslow-exec", f"{new}\tusage", f"{new}\tusage",
                                           f"{new}\tcanary-diff\tabc\tslow=2:deny\tdaemon=0:allow",
                                           "мусор без табуляции"])
        s = S.stats(home=home, now=now)
        check("stats: всего = 95 решений демона + 3 отката, доля 3/98; старше суток и битые строки — мимо",
              s["daemon"] == 95 and s["fallbacks"] == 3 and s["calls"] == 98 and s["share"] == round(3 / 98, 4), s)
        check("stats: причины по убыванию (perm 2, no-client 1); двойной отказ отдельно (slow-exec 1, usage 2)",
              list(s["reasons"].items()) == [("perm", 2), ("no-client", 1)]
              and s["double"] == {"slow-exec": 1, "usage": 2}, s)
        check("stats: canary-diff 1, строка целиком", s["canary_diff"] == 1
              and s["canary"] == [f"{new}\tcanary-diff\tabc\tslow=2:deny\tdaemon=0:allow"], s)
        s48 = S.stats(home=home, hours=48, now=now)
        check("stats --hours 48: старые строки в окне (1095 решений, 4 отката)",
              s48["daemon"] == 1095 and s48["fallbacks"] == 4, s48)
        empty = S.stats(home=os.path.join(root, "none"), now=now)
        check("stats без журналов: ноль вызовов, доли нет", empty["calls"] == 0 and empty["share"] is None, empty)
        many = os.path.join(root, "m")
        write(many, "hookd-fallback.log", [f"{new}\tcanary-diff\t{i}\ts\td" for i in range(5)])
        sm = S.stats(home=many, now=now)
        check("stats: canary-diff 5 — в выводе последние три", sm["canary_diff"] == 5 and len(sm["canary"]) == 3
              and sm["canary"][-1].split("\t")[2] == "4", sm)

        code, out, err = cli(home)
        lines = out.strip().splitlines()
        check("командная строка: canary-diff — код 3, «тревога: canary-diff 1» последней строкой, доля «3,1 %»",
              code == 3 and lines[-1].startswith("тревога: canary-diff 1 за 24 ч") and "(3,1 %)" in lines[0]
              and "двойной отказ" in out and "perm 2, no-client 1" in out, (code, out, err))
        quiet = os.path.join(root, "q")
        write(quiet, "hookd-calls.log", [f"{new}\tok\t10"])
        write(quiet, "hookd-fallback.log", [f"{new}\tperm"])
        code, out, err = cli(quiet)
        check("командная строка: без canary-diff — код 0, «canary-diff: 0», тревоги нет",
              code == 0 and "canary-diff: 0" in out and "тревога" not in out and "(9,1 %)" in out, (code, out, err))
        code, out, err = cli(os.path.join(root, "none"))
        check("командная строка: журналов нет — код 0, «вызовов нет»", code == 0 and "вызовов нет" in out, (code, out))
        code, out, err = cli(home, "--json", "--hours", "48")
        try:
            js = json.loads(out)
        except ValueError:
            js = {}
        check("--json --hours 48: словарь, код 3", code == 3 and js.get("daemon") == 1095 and js.get("canary_diff") == 1,
              (code, out[:300]))
        for args in (["--hours"], ["--hours", "0"], ["--hours", "x"], ["--bogus"]):
            code, out, err = cli(home, *args)
            check(f"плохие аргументы {' '.join(args)} — код 64 и причина",
                  code == 64 and err.startswith("hookd-stats: плохие аргументы"), (code, err))
        broken = os.path.join(root, "b")
        os.makedirs(os.path.join(broken, ".local", "state", "pantheon", "logs", "hookd-calls.log"))
        code, out, err = cli(broken)
        check("журнал не прочесть (на его месте папка) — код 1, причина последней строкой",
              code == 1 and err.strip().splitlines()[-1].startswith("hookd-stats: журнал не прочесть"), (code, err))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
