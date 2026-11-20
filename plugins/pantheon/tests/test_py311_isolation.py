#!/usr/bin/env python3
"""Изоляция подменного claude от интерпретатора теста (metis-1308): run_env ставит папку sys.executable в PATH дочерних
`pantheon start` раньше PATH теста. Тест, запущенный python3.14 из папки с настоящим claude (~/.local/bin: uv кладёт
туда ссылку на Python), отдавал самозапуску настоящий claude, и окно мимо подмены не поднималось. PY311
(_py311.python_without_claude) берёт тогда realpath интерпретатора. Папка «Python рядом с claude» здесь строится
сама, поэтому случай проверяется на любой машине, а не только там, где ~/.local/bin такой.

Тот же класс — настоящий codex (metis-1308, 20.11): npm кладёт его в bin nvm рядом с node, этот bin есть в PATH теста,
а run_env ставит bin nvm (NVM_DIR) раньше PATH теста. Тест «Codex нет» находил настоящий codex, и тот шёл входить в
OpenAI. Импорт _py311 изолирует процесс теста (isolate_env): папки PATH с claude или codex — зеркалом без них, NVM_DIR —
пустой. Папка nvm с codex здесь тоже строится сама."""
# ruff: noqa: F403, F405
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _watch_common import *  # noqa: F403
import json  # noqa: E402
import shutil  # noqa: E402
from _py311 import isolate_env, isolate_path, python_without_claude  # noqa: E402

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


_WHICH_TOOLS = r"""
import importlib.util, json, os, shutil, sys
spec = importlib.util.spec_from_file_location("pantheon_lib", sys.argv[1])
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
path = P.run_env()["PATH"]
print(json.dumps({t: shutil.which(t, path=path) for t in ("codex", "node")}))
"""


def _fake_nvm(e):
    """Папка nvm, как на Mac владельца с 19.11: в bin версии node по умолчанию рядом с node лежит настоящий codex из npm
    (здесь — заглушка, которая пишет свой вызов в журнал) → (NVM_DIR, bin версии)."""
    root = os.path.join(e.tmp, "nvm")
    b = os.path.join(root, "versions", "node", "v22.0.0", "bin")
    os.makedirs(b)
    for n in ("codex", "node"):
        open(os.path.join(b, n), "w").write(f'#!/bin/sh\necho "{n} $@" >> "{e.tmp}/real-tools.log"\n')
        os.chmod(os.path.join(b, n), 0o755)
    return root, b


def _which_tools(e, extra):
    r = e.run(LIB, argv=[PY_REAL, "-I", "-c", _WHICH_TOOLS], extra=extra)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        return {"error": r.stdout[-300:] + r.stderr[-300:]}


def test_run_env_puts_real_codex_first_without_isolation_1308():
    """metis-1308, воспроизведение: bin nvm с codex в NVM_DIR и в PATH теста — run_env ставит его раньше PATH теста, и
    дочерний процесс находит этот codex. Без этого случая проверка изоляции ниже ничего бы не доказывала."""
    e = Env()
    nvm, b = _fake_nvm(e)
    got = _which_tools(e, {"NVM_DIR": nvm, "PATH": f"{b}:/usr/bin:/bin"})
    check(got.get("codex") == os.path.join(b, "codex"), f"1308: без изоляции codex из nvm не найден: {got}")


def test_isolate_env_hides_real_codex_keeps_node_1308():
    """metis-1308: isolate_env — дочерний run_env не находит codex ни в PATH теста, ни в bin nvm, который run_env ставит
    первым; node из той же папки остаётся (ссылка на настоящий файл)."""
    e = Env()
    nvm, b = _fake_nvm(e)
    env = {"NVM_DIR": nvm, "PATH": f"{b}:/usr/bin:/bin"}
    root = os.path.join(e.tmp, "iso")
    os.makedirs(root)
    isolate_env(env, root)
    got = _which_tools(e, env)
    # node — по PATH самого теста: run_env ставит /opt/homebrew/bin раньше, и там может быть свой node
    node = shutil.which("node", path=env["PATH"])
    check(got.get("codex") is None and node and os.path.realpath(node) == os.path.realpath(os.path.join(b, "node"))
          and env["NVM_DIR"] != nvm, f"1308: изоляция — {got}, NVM_DIR {env['NVM_DIR']!r}")


def test_isolate_path_only_touches_dirs_with_tools_1308():
    """metis-1308: папка без claude и codex остаётся в PATH как была и на своём месте; папка с claude — зеркало без него."""
    e = Env()
    clean = os.path.join(e.tmp, "clean-bin")
    dirty = os.path.join(e.tmp, "dirty-bin")
    for d in (clean, dirty):
        os.makedirs(d)
        open(os.path.join(d, "tool-" + os.path.basename(d)), "w").close()
    open(os.path.join(dirty, "claude"), "w").close()
    root = os.path.join(e.tmp, "iso")
    os.makedirs(root)
    parts = isolate_path(f"{clean}:{dirty}:/usr/bin", root).split(":")
    check(parts[0] == clean and parts[2] == "/usr/bin" and parts[1] != dirty
          and sorted(os.listdir(parts[1])) == ["tool-dirty-bin"], f"1308: isolate_path — {parts}")


def test_py311_import_isolates_process_env_1308():
    """metis-1308: сам импорт _py311 (его делает каждый тест pantheon) изолирует окружение процесса теста: codex из
    PATH не находится, NVM_DIR — не тот, что был. Так тест «Codex нет» и его дочерние run_env не видят настоящий codex."""
    e = Env()
    nvm, b = _fake_nvm(e)
    code = ("import json, os, shutil, sys; sys.path.insert(0, sys.argv[1]); import _py311; "
            "print(json.dumps([shutil.which('codex'), shutil.which('node'), os.environ.get('NVM_DIR')]))")
    env = {"PATH": f"{b}:/usr/bin:/bin", "NVM_DIR": nvm, "HOME": e.home, "TMPDIR": e.tmp}
    r = subprocess.run([PY_REAL, "-I", "-c", code, os.path.dirname(os.path.abspath(__file__))], env=env,
                       capture_output=True, text=True, timeout=60)
    try:
        codex, node, nvm_dir = json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        codex, node, nvm_dir = "?", None, nvm
    check(codex is None and node and nvm_dir != nvm, f"1308: импорт _py311 — {r.stdout[-300:]!r} {r.stderr[-300:]!r}")


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(ROOT), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544)
    n = run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")], FAILS,
                  lambda name, err: FAILS.append(f"{name}: {err}"))
    print(f"тестов: {n}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
