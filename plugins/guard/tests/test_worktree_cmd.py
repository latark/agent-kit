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
          # Д2: флаги в любом порядке; --detach; remove --force (detached проверяет сама команда)
          "pantheon worktree add x --base HEAD --branch b", "pantheon worktree add tmp-1 --detach --base origin/main",
          "pantheon worktree add tmp-1 --base origin/main --detach", "pantheon worktree add tmp-1 --detach",
          "pantheon worktree remove tmp-1 --force",
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
           "pantheon worktree add -x", "pantheon worktree add x --force", "pantheon worktree remove x --force --force",
           "pantheon worktree remove -f x", "pantheon worktree remove --force x",
           "pantheon worktree add x --detach --base a --branch b --detach", "pantheon worktree add x --detach=1",
           # F1: разбор строку не понял — сырая строка с пультом всё равно должна совпасть с образцом
           "pantheon worktree add x (", "pantheon worktree add x {", "pantheon worktree add x 'oops",
           "'pantheon' worktree add x", "~/.local/bin/pantheon.py worktree add x (", "pantheon  worktree\tadd x )",
           # продолжение строки и обратные слэши (фоновая проверка #488): нормализация до сырой проверки
           "pantheon \\\nworktree add x", "pantheon \\\nworktree add x (", "pantheon worktree \\\nadd x; id",
           "pan\\theon worktree add x (", "p'ant'heon worktree add x (",
           # разбор упал целиком, а пульт не первым словом — слова pantheon и worktree в тексте
           "echo $(pantheon worktree add x", "echo `pantheon worktree add x", "echo ok (pantheon worktree add x",
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
    check("мутант: правило не узнаёт пульт — env и цепочка после echo проходят",
          run("env pantheon worktree add x", m) is None and run("echo a; pantheon worktree add x; id", m) is None)
    raw = "    raw = any(WORKTREE_RAW.match(ln) for ln in norm.splitlines() or [\"\"])\n"
    check("самопроверка мутантов: строка сырой проверки одна", src.count(raw) == 1)
    fl0 = "        failed = not cmds and targets == [UNRESOLVED]\n"
    m = load(src.replace(raw, "    raw = False\n").replace(fl0, "        failed = False\n"))
    check("мутант F1: без сырой проверки и отказа при сбое разбора — `pantheon worktree add x (` проходит",
          run("pantheon worktree add x (", m) is None)
    nrm = "    norm = _wt_norm(cmd)\n"
    check("самопроверка мутантов: строка нормализации одна", src.count(nrm) == 1)
    m = load(src.replace(nrm, "    norm = cmd\n"))
    check("мутант: без нормализации — `pan\\theon worktree add x (` проходит",
          run("pan\\theon worktree add x (", m) is None)
    fl = "        failed = not cmds and targets == [UNRESOLVED]\n"
    check("самопроверка мутантов: строка сбоя разбора одна", src.count(fl) == 1)
    m = load(src.replace(fl, "        failed = False\n"))
    check("мутант: без отказа при сбое разбора — `echo $(pantheon worktree add x` проходит",
          run("echo $(pantheon worktree add x", m) is None)
    m = load(src.replace("|--detach)){0,3})", "|--detach)){0,4})"))
    check("мутант Д2: четыре флага вместо трёх — образец пропускает",
          run("pantheon worktree add x --detach --base a --branch b --detach", m) is None)
finally:
    shutil.rmtree(root, True)

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
