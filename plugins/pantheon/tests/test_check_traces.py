#!/usr/bin/env python3
"""Тесты проверки личных следов scripts/check-traces.py: временный репозиторий, выдуманные маркеры.

Запуск: python3 -I plugins/pantheon/tests/test_check_traces.py  (код выхода 0 — все прошли)
"""
import os
import subprocess
import sys
import tempfile
import atexit as _atexit
import shutil as _shutil

_ROOT = tempfile.mkdtemp(prefix="traces-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "check-traces.py")
OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    if not cond:
        print(f"НЕ ПРОШЁЛ: {name} {detail}")


def sh(*cmd, cwd=None):
    subprocess.run(list(cmd), cwd=cwd, check=True, capture_output=True)


def make_repo(files):
    repo = tempfile.mkdtemp(prefix="repo-")
    sh("git", "init", "-q", repo)
    for rel, text in files.items():
        p = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    sh("git", "-C", repo, "add", "-A")
    return repo


def run(*args, env=None):
    e = {"PATH": os.environ["PATH"], "HOME": _ROOT}
    e.update(env or {})
    return subprocess.run([sys.executable, "-I", SCRIPT, *args], env=e, capture_output=True, text=True, timeout=60)


def main():
    markers = os.path.join(_ROOT, "markers.txt")
    with open(markers, "w", encoding="utf-8") as fh:
        fh.write("# выдуманные маркеры\n\nZorbaCorp\nКвазимодо\n")
    clean = make_repo({"lib/a.py": "x = 1\n"})
    r = run("--markers", markers, "--repo", clean)
    check("чистый репозиторий — «следов нет», код 0", r.returncode == 0 and "следов нет" in r.stdout, r.stdout + r.stderr)

    dirty = make_repo({"lib/a.py": "x = 1\n# автор Квазимодо\n", "lib/b.py": "y = 2\n"})
    r = run("--markers", markers, "--repo", dirty)
    check("след — код 1, «путь:строка: маркер»", r.returncode == 1 and "lib/a.py:2: Квазимодо" in r.stdout, r.stdout)
    check("печатается только совпавший маркер, не весь список", "ZorbaCorp" not in r.stdout + r.stderr)

    # исключений нет (metis-0182): ни метка в строке, ни папка guard, ни marketplace.json след не прячут
    ok = make_repo({"lib/a.py": "x = 'ZorbaCorp'  # trace-ok: 0182-core — снять в PR ядра\n"})
    r = run("--markers", markers, "--repo", ok)
    check("метка trace-ok в строке след не прячет — код 1", r.returncode == 1 and "lib/a.py:1: ZorbaCorp" in r.stdout,
          r.stdout)

    ex = make_repo({"plugins/guard/g.py": "# ZorbaCorp\n"})
    r = run("--markers", markers, "--repo", ex)
    check("plugins/guard/ проверяется — код 1", r.returncode == 1 and "plugins/guard/g.py:1" in r.stdout, r.stdout)

    mk = make_repo({".claude-plugin/marketplace.json": '{"description": "ZorbaCorp"}\n',
                    ".claude-plugin/other.json": '{"description": "чисто"}\n'})
    r = run("--markers", markers, "--repo", mk)
    check("marketplace.json проверяется — код 1", r.returncode == 1 and "marketplace.json:1" in r.stdout
          and "other.json" not in r.stdout, r.stdout)

    r = run("--markers", os.path.join(_ROOT, "нет.txt"), "--repo", dirty)
    check("нет файла маркеров — код 2 и предупреждение в stderr", r.returncode == 2 and "пропущена" in r.stderr, r.stderr)
    r = run("--repo", dirty)
    check("маркеров не задали вовсе — код 2", r.returncode == 2)
    empty = os.path.join(_ROOT, "empty.txt")
    with open(empty, "w", encoding="utf-8") as fh:
        fh.write("\n# только комментарий\n\n")
    r = run("--markers", empty, "--repo", dirty)
    check("файл без маркеров — код 2, а не «всё совпало»", r.returncode == 2, r.stdout)

    r = run("--repo", dirty, env={"PANTHEON_TRACE_MARKERS": markers})
    check("маркеры через PANTHEON_TRACE_MARKERS", r.returncode == 1 and "Квазимодо" in r.stdout, r.stdout + r.stderr)

    r = run("--markers", markers, "--repo", dirty, "--", "lib/b.py")
    check("pathspec после «--» сужает поиск", r.returncode == 0, r.stdout)

    print(f"{len(OK)} из {len(OK) + len(FAIL)} прошли")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
