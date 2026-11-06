#!/usr/bin/env python3
"""Окно роли не читает настроек проектов (metis-0919, решение владельца 06.11 «А — окна читают только свои»).

Запуск: python3 -I plugins/pantheon/tests/test_setting_sources.py  (код выхода 0 — все прошли)
- window_flags(<окно>) → ["--settings", <окно>, "--setting-sources", "user"];
- в коде плагина (lib/, bin/, hooks/) нет списка argv со строкой "--settings" мимо window_flags: любой запуск окна —
  pantheon start, Пританей, свежий старт, wake, --resume, задачи расписания — идёт через неё (разбор AST);
- parse_command: claude -p задачи расписания получает оба флага, а --setting-sources из schedule.toml не пускает;
- живые argv запусков сверяет test_start («за весь файл: каждый запуск окна …») и test_tick (parse_command).
"""
import ast
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="setsrc-"))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond, info=None):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or info is None else "\n     " + str(info)[-1500:]))


def settings_literals(path):
    """[(строка, функция)] — списки и кортежи с элементом "--settings" вне функции window_flags."""
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    found = []

    def walk(node, func):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
            if isinstance(child, (ast.List, ast.Tuple)) and name != "window_flags" and any(
                    isinstance(e, ast.Constant) and e.value == "--settings" for e in child.elts):
                found.append((child.lineno, name))
            walk(child, name)
    walk(tree, None)
    return found


def main():
    files = [os.path.join(d, f) for sub in ("lib", "bin", "hooks", "scripts")
             for d in [os.path.join(PLUGIN, sub)] if os.path.isdir(d) for f in sorted(os.listdir(d)) if f.endswith(".py")]
    bad = {os.path.relpath(f, PLUGIN): hits for f in files for hits in [settings_literals(f)] if hits}
    check(f"argv с --settings — только через window_flags ({len(files)} файлов кода)", files and not bad, bad)
    # сам разбор ловит такой список (иначе проверка выше ничего не доказывает)
    probe = os.path.join(ROOT, "x.py")
    with open(probe, "w") as fh:
        fh.write('def go(b, w, t):\n    return [b, "--bg", "--settings", w, t]\n\n\n'
                 'def window_flags(s):\n    return ["--settings", s, "--setting-sources", "user"]\n')
    check("разбор: список argv с --settings мимо window_flags найден, внутри window_flags — нет",
          settings_literals(probe) == [(2, "go")], settings_literals(probe))

    tmp = os.path.join(ROOT, "h")
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": os.path.join(tmp, "pantheon"),
           "PANTHEON_STATE": os.path.join(tmp, "state"), "PANTHEON_NO_NOTIFY": "1"}
    os.makedirs(env["PANTHEON_HOME"])
    code = ("import json, runpy, sys\nsys.argv = [sys.argv[0]]\n"
            f"g = runpy.run_path({os.path.join(PLUGIN, 'lib', 'pantheon.py')!r}, run_name='probe')\n"
            "print(json.dumps({'flags': g['window_flags']('/w.json'), 'src': list(g['WINDOW_SOURCES']),\n"
            "  'job': g['parse_command']('claude -p --agent clio \"x\"'),\n"
            "  'own': g['parse_command']('claude -p --agent clio --setting-sources user,project \"x\"')}))\n")
    r = subprocess.run([sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = {}
    check("window_flags: --settings <окно> --setting-sources user",
          got.get("flags") == ["--settings", "/w.json", "--setting-sources", "user"] and got.get("src")
          == ["--setting-sources", "user"], (got, r.stderr[-800:]))
    job = got.get("job") or []
    check("задача расписания claude -p: --settings окна задачи и --setting-sources user",
          job[:2] == ["claude", "-p"] and "--settings" in job
          and job[job.index("--settings") + 2:job.index("--settings") + 4] == ["--setting-sources", "user"], job)
    check("задача расписания: --setting-sources из schedule.toml не пускается", "own" in got and got["own"] is None, got)
    print(f"\n{sum(results)} из {len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
