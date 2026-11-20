#!/usr/bin/env python3
"""Изоляция подменного claude от интерпретатора теста (metis-1308): run_env ставит папку sys.executable в PATH дочерних
`pantheon start` раньше PATH теста. Тест, запущенный python3.14 из папки с настоящим claude (~/.local/bin: uv кладёт
туда ссылку на Python), отдавал самозапуску настоящий claude, и окно мимо подмены не поднималось. PY311
(_py311.python_without_claude) берёт тогда realpath интерпретатора. Папка «Python рядом с claude» здесь строится
сама, поэтому случай проверяется на любой машине, а не только там, где ~/.local/bin такой."""
# ruff: noqa: F403, F405
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403
from _py311 import python_without_claude  # noqa: E402

PY_REAL = os.path.realpath(sys.executable)

_WHICH = r"""
import importlib.util, shutil, sys
spec = importlib.util.spec_from_file_location("pantheon_lib", sys.argv[1])
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
print(shutil.which("claude", path=P.run_env()["PATH"]))
"""


def _shadow_bin(e):
    """Папка «Python рядом с настоящим claude», как ~/.local/bin после uv: ссылка python3.14 на интерпретатор теста и
    claude, который пишет свой вызов в отдельный журнал (настоящий claude подмены не пишет) → (путь python, журнал)."""
    d = os.path.join(e.tmp, "shadow-bin")
    os.makedirs(d)
    py = os.path.join(d, "python3.14")
    os.symlink(PY_REAL, py)
    log = os.path.join(e.tmp, "shadow-claude.log")
    open(os.path.join(d, "claude"), "w").write(f'#!/bin/sh\necho "$@" >> "{log}"\necho "[]"\n')
    os.chmod(os.path.join(d, "claude"), 0o755)
    return py, log


def test_python_without_claude_picks_clean_dir_1308():
    """metis-1308: рядом с интерпретатором есть claude — берётся realpath (папка без claude); рядом нет — путь как был."""
    e = Env()
    py, _ = _shadow_bin(e)
    got = python_without_claude(py)
    check(got == PY_REAL and not os.path.lexists(os.path.join(os.path.dirname(got), "claude")),
          f"1308: интерпретатор рядом с claude не заменён: {got!r}, ждали {PY_REAL!r}")
    check(python_without_claude(PY_REAL) == PY_REAL, f"1308: чистый путь изменён: {python_without_claude(PY_REAL)!r}")


def test_python_without_claude_refuses_when_both_shadowed_1308():
    """metis-1308: claude и рядом со ссылкой, и рядом с realpath — код 1 и причина последней строкой, а не тихий запуск
    тестов с настоящим claude."""
    e = Env()
    real_dir = os.path.join(e.tmp, "real-bin")
    os.makedirs(real_dir)
    real_py = os.path.join(real_dir, "python3.14")
    open(real_py, "w").write("")
    open(os.path.join(real_dir, "claude"), "w").write("")
    link_dir = os.path.join(e.tmp, "link-bin")
    os.makedirs(link_dir)
    os.symlink(real_py, os.path.join(link_dir, "python3.14"))
    open(os.path.join(link_dir, "claude"), "w").write("")
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from _py311 import python_without_claude; "
            "python_without_claude(sys.argv[2])")
    r = subprocess.run([PY_REAL, "-I", "-c", code, os.path.dirname(os.path.abspath(__file__)),
                        os.path.join(link_dir, "python3.14")], capture_output=True, text=True, timeout=60)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    check(r.returncode == 1 and "metis-1308" in last, f"1308: оба места с claude — код {r.returncode}, {last!r}")


def test_run_env_finds_fake_claude_1308():
    """metis-1308: дочерний процесс на интерпретаторе python_without_claude(Python рядом с claude) — PATH run_env
    находит подменный claude теста, а не тот, что лежит рядом с интерпретатором."""
    e = Env()
    py, _ = _shadow_bin(e)
    r = e.run(LIB, argv=[python_without_claude(py), "-I", "-c", _WHICH])
    got = r.stdout.strip()
    check(got == os.path.join(e.bin, "claude"), f"1308: run_env нашёл не подменный claude: {got!r} {r.stderr[-300:]!r}")


def test_autostart_uses_fake_claude_1308():
    """metis-1308: самозапуск плановым проходом на интерпретаторе python_without_claude(Python рядом с claude) поднимает
    окно подменным claude (`--bg` в журнале подмены), а claude рядом с интерпретатором не зовётся ни разу."""
    e = Env()
    py, log = _shadow_bin(e)
    argv = [python_without_claude(py), "-I", RUN_PY]
    e.direction("sb-dir")
    e.task("sb-0001", "sb-dir")
    e.run("watch", t=T0, argv=argv)
    e.board("sb-0001", T0 + 10)
    n0 = len(e.calls())
    r = e.run("watch", t=T0 + 120, argv=argv)
    got = [c for c in e.calls()[n0:] if c[:1] == ["--bg"]]
    shadow = open(log).read() if os.path.exists(log) else ""
    check(got and not shadow, f"1308: самозапуск — подменный --bg {got}, claude рядом с Python: {shadow[-300:]!r} "
          f"{r.stderr[-300:]!r}")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
