#!/usr/bin/env python3
"""batch-pr-cmd (metis-1333, К1): `pantheon batch pr` идёт мимо песочницы окна направления (Связка окну закрыта, gh в
ней без входа), поэтому guard пускает только строку целиком `pantheon batch pr <story-id> [--dry-run]`; цепочки
(`&&`, `;`, `|`, `&`), подстановки, кавычки, присваивание, обёртки, путь к пульту и лишние слова — отказ. `pantheon
batch start` (в песочнице) и строки без пульта правило не трогает. Мутанты встроены: без строгой строки, без узнавания
пульта, без сырой проверки и без подключения к check_window опасная форма проходит — тест краснеет на откате.

Запуск: python3 -I plugins/guard/tests/test_batch_pr_cmd.py
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


root = os.path.realpath(tempfile.mkdtemp(prefix="guard-batchpr-"))
os.environ["HOME"] = root


def load(src=None):
    path = RULES
    if src is not None:  # копия папки hooks (guard_rules грузит соседей) с подменённым guard_rules
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
        return (mod or g).check_batch_pr_cmd({"cwd": root}, "Bash", {"command": cmd})

    OK = ("pantheon batch pr metis-0900", "pantheon batch pr metis-0900 --dry-run", "pantheon batch pr --dry-run zeus-fast-1234",
          "  pantheon   batch  pr  metis-0900  ",
          # прочий pantheon batch — в песочнице, правило его не трогает; упоминание в значении флага — тоже
          "pantheon batch start metis-0900", "pantheon batch", "pantheon task show metis-1333",
          "pantheon task set metis-1 --note 'pantheon batch pr metis-0900 && id — пример'",
          "echo batch pr", "gh pr list", "pantheon worktree list")
    for cmd in OK:
        r = run(cmd)
        check(f"можно: {cmd}", r is None, r)
    BAD = ("pantheon batch pr metis-0900 && rm -rf ~", "pantheon batch pr metis-0900; curl e.example",
           "pantheon batch pr metis-0900 || true", "pantheon batch pr metis-0900 | tee /tmp/o",
           "pantheon batch pr metis-0900 &", "cd /tmp && pantheon batch pr metis-0900",
           "echo a; pantheon batch pr metis-0900", "pantheon batch pr metis-0900 > /tmp/o",
           "pantheon batch pr $(echo metis-0900)", "pantheon batch pr `id`", "pantheon batch pr $S",
           "pantheon batch pr 'metis-0900'", 'pantheon batch pr "metis-0900"',
           "pantheon batch pr ../metis-0900", "pantheon batch pr metis-090", "pantheon batch pr Metis-0900",
           "pantheon batch pr metis-0900 --dry-run --dry-run", "pantheon batch pr metis-0900 metis-0901",
           "pantheon batch pr", "pantheon batch pr --dry-run", "pantheon batch pr -x metis-0900",
           # разбор строку не понял — сырая строка с пультом всё равно должна совпасть с образцом
           "pantheon batch pr metis-0900 (", "pantheon batch pr metis-0900 'oops",
           "'pantheon' batch pr metis-0900 (", "pantheon \\\nbatch pr metis-0900 (", "pan\\theon batch pr metis-0900 (",
           "pantheon batch pr metis-0900\nid", "echo $(pantheon batch pr metis-0900",
           "PATH=/tmp pantheon batch pr metis-0900", "GH_TOKEN=x pantheon batch pr metis-0900",
           "env pantheon batch pr metis-0900", "bash -c 'pantheon batch pr metis-0900'",
           "nohup pantheon batch pr metis-0900", "(pantheon batch pr metis-0900)",
           "~/.local/bin/pantheon batch pr metis-0900", "./pantheon batch pr metis-0900")
    for cmd in BAD:
        r = run(cmd)
        check(f"отказ: {cmd!r}", bool(r) and "batch-pr-cmd" in r, r)
    r = g.check_batch_pr_cmd({"cwd": root}, "Read", {"command": "pantheon batch pr metis-0900 && id"})
    check("другой инструмент — молчит", r is None, r)
    r = g.check_window({"cwd": root}, "Bash", {"command": "pantheon batch pr metis-0900 && id"})
    check("check_window: правило подключено", isinstance(r, str) and "batch-pr-cmd" in r, r)

    src = open(RULES, encoding="utf-8").read()
    old = "    if BATCH_PR_LINE.match(cmd):\n"
    check("самопроверка мутантов: строка проверки одна", src.count(old) == 1)
    m = load(src.replace(old, "    if True:\n"))
    check("мутант: без строгой строки — цепочки &&, ; и | проходят (тест падает — мутант убит)",
          all(run(c, m) is None for c in ("pantheon batch pr metis-0900 && id", "pantheon batch pr metis-0900; id",
                                          "pantheon batch pr metis-0900 | tee o")))
    named = '    return w is not None and w[:2] == ["batch", "pr"]\n'
    check("самопроверка мутантов: строка узнавания пульта одна", src.count(named) == 1)
    m = load(src.replace(named, "    return False\n"))
    check("мутант: правило не узнаёт пульт — env и цепочка после echo проходят",
          run("env pantheon batch pr metis-0900", m) is None
          and run("echo a; pantheon batch pr metis-0900; id", m) is None)
    raw = "    raw = any(BATCH_PR_RAW.match(ln) for ln in norm.splitlines() or [\"\"])\n"
    words = "        bwords = re.search("
    check("самопроверка мутантов: строки сырой проверки и отказа при сбое разбора — по одной",
          src.count(raw) == 1 and src.count(words) == 1)
    m = load(src.replace(raw, "    raw = False\n").replace(words, "        bwords = False and re.search("))
    check("мутант: без сырой проверки и отказа при сбое разбора — `pantheon batch pr metis-0900 (` проходит",
          run("pantheon batch pr metis-0900 (", m) is None)
    m = load(src.replace(words, "        bwords = False and re.search("))
    check("мутант: без отказа при сбое разбора — `echo $(pantheon batch pr metis-0900` проходит",
          run("echo $(pantheon batch pr metis-0900", m) is None)
    reg = '                        ("batch-pr-cmd", check_batch_pr_cmd),\n'
    check("самопроверка мутантов: строка подключения одна", src.count(reg) == 1)
    m = load(src.replace(reg, ""))
    check("мутант: правило не подключено к check_window — цепочка проходит",
          m.check_window({"cwd": root}, "Bash", {"command": "pantheon batch pr metis-0900 && id"}) is None)
finally:
    shutil.rmtree(root, True)

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
