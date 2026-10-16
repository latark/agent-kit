#!/usr/bin/env python3
"""pantheon instructions: дойдут ли инструкции до агента целиком — Codex (лимит байт на путь от корня git),
MEMORY.md автопамяти (200 строк / 25 КБ), CLAUDE.md с импортами длиннее 200 строк. Временный HOME и CODEX_HOME."""
import os
import shutil
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import tempfile
# Все временные папки файла — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение);
# TMPDIR — для подпроцессов, которые тоже создают временные папки. Общий TMPDIR остаётся чистым.
import atexit as _atexit
import os as _os
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="instructions-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="instructions-test-"))
    home, state, codex = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state"), os.path.join(tmp, "codex")
    proj = os.path.join(tmp, "projects", "demo")
    app = os.path.join(proj, "app")
    os.makedirs(os.path.join(app, ".git"))
    write(os.path.join(home, "directions.toml"),
          '[[direction]]\nname = "iris-demo"\nfolders = ["~/projects/demo"]\n')
    write(os.path.join(app, "AGENTS.md"), "x\n" * 10000)                     # 20 000 байт
    write(os.path.join(app, "web", "AGENTS.md"), "y\n" * 7000)               # +14 000 на пути app/web
    write(os.path.join(app, "CLAUDE.md"), "@AGENTS.md\n")
    write(os.path.join(proj, "other", ".git", "HEAD"), "")
    write(os.path.join(proj, "other", "AGENTS.md"), "z\n" * 100)
    write(os.path.join(app, "node_modules", "pkg", "AGENTS.md"), "n\n" * 30000)  # не считается
    env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_NO_NOTIFY": "1", "CODEX_HOME": codex}
    run = lambda *a: subprocess.run([PY311, "-I", LIB, *a], env=env, capture_output=True, text=True)
    alerts = lambda: open(os.path.join(home, "alerts.md"), encoding="utf-8").read() \
        if os.path.exists(os.path.join(home, "alerts.md")) else ""

    r = run("instructions")
    check("Codex на этом Mac нет — срез видно, но без тревоги и rc 0",
          r.returncode == 0 and "Codex*" in r.stdout and "app/web" in r.stdout and "Codex на этом Mac: нет" in r.stdout)
    check("node_modules не обходится", "node_modules" not in r.stdout)
    check("CLAUDE.md с импортом AGENTS.md — 10001 строк, длинно", "app — 10001 строк" in r.stdout)
    run("instructions", "--quiet")
    check("без Codex тревоги о срезе нет, о длине — есть", "Codex:" not in alerts() and "длиннее 200" in alerts())

    os.makedirs(codex)
    r = run("instructions")
    check("Codex есть — цепочка app → app/web (34 000 байт) сверх 32 КиБ: СРЕЗ, rc 1",
          r.returncode == 1 and "СРЕЗ    Codex: инструкции до ~/projects/demo/app/web — 33 КиБ" in r.stdout)
    check("корень app сам по себе (20 000 байт) в лимите", "до ~/projects/demo/app —" not in r.stdout)
    check("свой git у other — цепочка с нуля, в лимите", "other" not in r.stdout.split("ДЛИННО")[0])
    run("instructions", "--quiet")
    a1 = alerts()
    check("тревога о срезе Codex", "Codex: инструкции до ~/projects/demo/app/web" in a1)
    run("instructions", "--quiet")
    check("повтор того же состояния молчит", alerts() == a1)

    write(os.path.join(codex, "config.toml"), "project_doc_max_bytes = 65536\n")
    r = run("instructions")
    check("лимит из config.toml Codex (64 КиБ) — среза нет", "СРЕЗ" not in r.stdout and r.returncode == 0)
    write(os.path.join(codex, "AGENTS.md"), "g" * 40000)
    r = run("instructions")
    check("глобальный ~/.codex/AGENTS.md считается в тот же бюджет", "СРЕЗ    Codex" in r.stdout)
    shutil.rmtree(codex)

    mem = os.path.join(tmp, ".claude", "projects", "-x-demo", "memory", "MEMORY.md")
    write(mem, "- строка\n" * 150)
    r = run("instructions")
    check("MEMORY.md 150 строк — в пределе", "MEMORY.md" not in r.stdout)
    write(mem, "- строка\n" * 250)
    role = os.path.join(tmp, ".claude", "agent-memory", "athena", "MEMORY.md")
    write(role, "ж" * 30000)
    r = run("instructions")
    check("MEMORY.md 250 строк — СРЕЗ Claude, rc 1 (тревога и без Codex)",
          r.returncode == 1 and "СРЕЗ    Claude: ~/.claude/projects/-x-demo/memory/MEMORY.md — 250 строк" in r.stdout)
    check("память роли 60 КБ одной строкой — тоже СРЕЗ по байтам", "agent-memory/athena/MEMORY.md" in r.stdout)
    run("instructions", "--quiet")
    check("тревога о MEMORY.md", "MEMORY.md — 250 строк" in alerts())

    print(f"{sum(results)} из {len(results)} прошли")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
