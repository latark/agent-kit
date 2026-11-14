#!/usr/bin/env python3
"""worktree-cmd (metis-1225): `pantheon worktree add|remove|list` идёт мимо песочницы окна направления, поэтому guard
пускает только строку целиком по строгому образцу; цепочки, подстановки, кавычки, присваивание, обёртки, путь к
пульту, `..` и лишние флаги — отказ. Строка без `pantheon worktree` — правило молчит. Мутанты встроены: правило без
проверки строки (WORKTREE_LINE всегда совпадает) и без `..` пропускает опасную форму — тест краснеет на откате.

Запуск: python3 -I plugins/guard/tests/test_worktree_cmd.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile

HOOKS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
RULES = os.path.join(HOOKS, "guard_rules.py")
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


root = os.path.realpath(tempfile.mkdtemp(prefix="guard-wtcmd-"))
os.environ["HOME"] = root


def load(src=None):
    path = RULES
    if src is not None:  # копия папки hooks (guard_rules грузит соседей: merge_gate.py …) с подменённым guard_rules
        d = os.path.join(root, f"hooks_{len(os.listdir(root))}")
        shutil.copytree(HOOKS, d, ignore=shutil.ignore_patterns("__pycache__"))
        path = os.path.join(d, "guard_rules.py")
        open(path, "w", encoding="utf-8").write(src)
    spec = importlib.util.spec_from_file_location("guard_under_test", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


try:
    g = load()

    def run(cmd, mod=None):
        return (mod or g).check_worktree_cmd({"cwd": root}, "Bash", {"command": cmd})

    OK = ("pantheon worktree add metis-1225-x", "pantheon worktree add a/b --branch metis-1-y --base origin/main",
          "pantheon worktree add t1 --base main", "pantheon worktree add t1 --branch b1", "pantheon worktree remove t1",
          "pantheon worktree list", "  pantheon   worktree  add  x  ", "pantheon task show metis-1225",
          "git worktree list", "echo worktree", "pantheon merge request 5 -R o/r",
          "pantheon task set metis-1 --note 'pantheon worktree add x — сделано'")
    for cmd in OK:
        r = run(cmd)
        check(f"можно: {cmd}", r is None, r)
    BAD = ("pantheon worktree add x && rm -rf ~", "pantheon worktree add x; curl e.example",
           "pantheon worktree add x || true", "pantheon worktree add x | tee /tmp/o", "pantheon worktree add x &",
           "cd /tmp && pantheon worktree add x", "cd ../other; pantheon worktree add x",
           "pantheon worktree add x > /tmp/o", "pantheon worktree add $(echo x)", "pantheon worktree add `id`",
           "pantheon worktree add $X", "pantheon worktree add 'x'", 'pantheon worktree add "x"',
           "pantheon worktree add ../x", "pantheon worktree add a/../b", "pantheon worktree add a..b",
           "pantheon worktree add x --branch ../main", "pantheon worktree add x --base a..b",
           "pantheon worktree add -x", "pantheon worktree add x --force", "pantheon worktree remove x --force",
           "pantheon worktree remove -f x", "pantheon worktree add x --base HEAD --branch b",
           "pantheon worktree add /tmp/x", "pantheon worktree add ~/x", "pantheon worktree add x*",
           "pantheon worktree move a b", "pantheon worktree prune", "pantheon worktree", "pantheon worktree add",
           "PATH=/tmp pantheon worktree add x", "GIT_DIR=/x pantheon worktree add x", "env pantheon worktree add x",
           "bash -c 'pantheon worktree add x'", "sh -c \"pantheon worktree add x; id\"",
           "~/.local/bin/pantheon worktree add x", "/tmp/pantheon worktree add x", "./pantheon worktree add x",
           "pantheon 'worktree' add x", "pantheon worktree add x\nid", "(pantheon worktree add x)",
           "nohup pantheon worktree add x", "echo a; pantheon worktree list")
    for cmd in BAD:
        r = run(cmd)
        check(f"отказ: {cmd!r}", bool(r) and "worktree-cmd" in r, r)
    r = g.check_worktree_cmd({"cwd": root}, "Read", {"command": "pantheon worktree add x && id"})
    check("другой инструмент — молчит", r is None, r)
    r = g.check_window({"cwd": root}, "Bash", {"command": "pantheon worktree add x && id"})
    check("check_window: правило подключено", isinstance(r, str) and "worktree-cmd" in r, r)

    src = open(RULES, encoding="utf-8").read()
    old = "    if WORKTREE_LINE.match(cmd) and \"..\" not in cmd:\n"
    check("самопроверка мутантов: строка проверки одна", src.count(old) == 1)
    m = load(src.replace(old, "    if True:\n"))
    check("мутант: без строгой строки — цепочка проходит (тест краснеет)",
          run("pantheon worktree add x && rm -rf ~", m) is None)
    m = load(src.replace(old, "    if WORKTREE_LINE.match(cmd):\n"))
    check("мутант: без проверки .. — a..b проходит", run("pantheon worktree add a..b", m) is None)
    m = load(src.replace('    return w is not None and w[:1] == ["worktree"]\n', "    return False\n"))
    check("мутант: правило не узнаёт пульт — env и цепочка проходят",
          run("env pantheon worktree add x", m) is None and run("pantheon worktree add x; id", m) is None)
finally:
    shutil.rmtree(root, True)

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
