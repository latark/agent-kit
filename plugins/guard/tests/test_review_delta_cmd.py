#!/usr/bin/env python3
"""review-delta-cmd (metis-1333, Д argus): `pantheon review delta` идёт мимо песочницы окна направления (Связка окну
закрыта, gh в ней без входа), поэтому guard пускает только строку целиком `pantheon review delta <owner/repo> <PR>`;
цепочки (`&&`, `;`, `|`, `&`), подстановки, кавычки, `..`, присваивание, обёртки, путь к пульту и лишние слова — отказ.
Прочий `pantheon review` и строки без пульта правило не трогает. Мутанты встроены: без строгой строки, без запрета
`..`, без узнавания пульта, без сырой проверки и без подключения к check_window опасная форма проходит — тест
краснеет на откате.

Запуск: python3 -I plugins/guard/tests/test_review_delta_cmd.py
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


root = os.path.realpath(tempfile.mkdtemp(prefix="guard-rdelta-"))
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
        return (mod or g).check_review_delta_cmd({"cwd": root}, "Bash", {"command": cmd})

    OK = ("pantheon review delta latark/agent-kit 537", "  pantheon   review  delta  latark/agent-kit  1  ",
          "pantheon review delta Owner.x/repo_y-z 123456789",
          # прочий pantheon review — правило его не трогает; упоминание в значении флага — тоже
          "pantheon review accept latark/agent-kit 537", "pantheon review status", "pantheon review",
          "pantheon task set metis-1 --note 'pantheon review delta latark/agent-kit 5 && id — пример'",
          "echo review delta", "gh pr view 5", "pantheon batch pr metis-0900")
    for cmd in OK:
        r = run(cmd)
        check(f"можно: {cmd}", r is None, r)
    BAD = ("pantheon review delta latark/agent-kit 537 && rm -rf ~", "pantheon review delta latark/agent-kit 537; id",
           "pantheon review delta latark/agent-kit 537 || true", "pantheon review delta latark/agent-kit 537 | tee o",
           "pantheon review delta latark/agent-kit 537 &", "cd /tmp && pantheon review delta latark/agent-kit 537",
           "echo a; pantheon review delta latark/agent-kit 537", "pantheon review delta latark/agent-kit 537 > o",
           "pantheon review delta $(echo latark/agent-kit) 537", "pantheon review delta latark/agent-kit `id`",
           "pantheon review delta $R 537", "pantheon review delta 'latark/agent-kit' 537",
           'pantheon review delta latark/agent-kit "537"', "pantheon review delta ../.. 537",
           "pantheon review delta latark/../x 537", "pantheon review delta latark 537",
           "pantheon review delta latark/agent-kit 0537", "pantheon review delta latark/agent-kit 537 538",
           "pantheon review delta latark/agent-kit", "pantheon review delta", "pantheon review delta -x latark/a 5",
           "pantheon review delta latark/agent-kit 537 --out /tmp/x",
           # разбор строку не понял — сырая строка с пультом всё равно должна совпасть с образцом
           "pantheon review delta latark/agent-kit 537 (", "pantheon review delta latark/agent-kit 537 'oops",
           "'pantheon' review delta latark/a 5 (", "pantheon \\\nreview delta latark/a 5 (",
           "pan\\theon review delta latark/a 5 (", "pantheon review delta latark/a 5\nid",
           "echo $(pantheon review delta latark/a 5",
           "PATH=/tmp pantheon review delta latark/a 5", "GH_TOKEN=x pantheon review delta latark/a 5",
           "env pantheon review delta latark/a 5", "bash -c 'pantheon review delta latark/a 5'",
           "nohup pantheon review delta latark/a 5", "(pantheon review delta latark/a 5)",
           "~/.local/bin/pantheon review delta latark/a 5", "./pantheon review delta latark/a 5")
    for cmd in BAD:
        r = run(cmd)
        check(f"отказ: {cmd!r}", bool(r) and "review-delta-cmd" in r, r)
    r = g.check_review_delta_cmd({"cwd": root}, "Read", {"command": "pantheon review delta latark/a 5 && id"})
    check("другой инструмент — молчит", r is None, r)
    r = g.check_window({"cwd": root}, "Bash", {"command": "pantheon review delta latark/a 5 && id"})
    check("check_window: правило подключено", isinstance(r, str) and "review-delta-cmd" in r, r)

    src = open(RULES, encoding="utf-8").read()
    old = '    if REVIEW_DELTA_LINE.match(cmd) and ".." not in cmd:\n'
    check("самопроверка мутантов: строка проверки одна", src.count(old) == 1)
    m = load(src.replace(old, "    if True:\n"))
    check("мутант: без строгой строки — цепочки &&, ; и | проходят (тест падает — мутант убит)",
          all(run(c, m) is None for c in ("pantheon review delta latark/a 5 && id",
                                          "pantheon review delta latark/a 5; id",
                                          "pantheon review delta latark/a 5 | tee o")))
    m = load(src.replace(old, "    if REVIEW_DELTA_LINE.match(cmd):\n"))
    check("мутант: без запрета `..` — `pantheon review delta ../.. 5` проходит",
          run("pantheon review delta ../.. 5", m) is None)
    named = '    return w is not None and w[:2] == ["review", "delta"]\n'
    check("самопроверка мутантов: строка узнавания пульта одна", src.count(named) == 1)
    m = load(src.replace(named, "    return False\n"))
    check("мутант: правило не узнаёт пульт — env и цепочка после echo проходят",
          run("env pantheon review delta latark/a 5", m) is None
          and run("echo a; pantheon review delta latark/a 5; id", m) is None)
    raw = "    hit = any(REVIEW_DELTA_RAW.match(ln) for ln in norm.splitlines() or [\"\"])\n"
    words = "        rwords = WORKTREE_WORDS.search(norm) and re.search("
    check("самопроверка мутантов: строки сырой проверки и отказа при сбое разбора — по одной",
          src.count(raw) == 1 and src.count(words) == 1)
    m = load(src.replace(raw, "    hit = False\n").replace(words, "        rwords = False and re.search("))
    check("мутант: без сырой проверки и отказа при сбое разбора — `pantheon review delta latark/a 5 (` проходит",
          run("pantheon review delta latark/a 5 (", m) is None)
    m = load(src.replace(words, "        rwords = False and re.search("))
    check("мутант: без отказа при сбое разбора — `echo $(pantheon review delta latark/a 5` проходит",
          run("echo $(pantheon review delta latark/a 5", m) is None)
    reg = '                        ("review-delta-cmd", check_review_delta_cmd),\n'
    check("самопроверка мутантов: строка подключения одна", src.count(reg) == 1)
    m = load(src.replace(reg, ""))
    check("мутант: правило не подключено к check_window — цепочка проходит",
          m.check_window({"cwd": root}, "Bash", {"command": "pantheon review delta latark/a 5 && id"}) is None)
finally:
    shutil.rmtree(root, True)

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
