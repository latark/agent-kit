#!/usr/bin/env python3
"""supabase-migrate-cmd (metis-1295): `pantheon supabase migrate` идёт мимо песочницы окна направления, поэтому guard
пускает только строку целиком `pantheon supabase migrate <файл> [--dry-run]`; цепочки (`&&`, `;`, `|`, `&`),
подстановки, кавычки, присваивание, обёртки, путь к пульту, `..`, абсолютный путь и лишние флаги — отказ. Прочий
`pantheon supabase` (в песочнице) и строки без пульта правило не трогает. Мутанты встроены: без строгой строки, без
`..`, без узнавания пульта, без сырой проверки и без нормализации опасная форма проходит — тест краснеет на откате.

Запуск: python3 -I plugins/guard/tests/test_supabase_migrate_cmd.py
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


root = os.path.realpath(tempfile.mkdtemp(prefix="guard-sbcmd-"))
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
        return (mod or g).check_supabase_migrate_cmd({"cwd": root}, "Bash", {"command": cmd})

    OK = ("pantheon supabase migrate supabase/migrations/20261120_x.sql",
          "pantheon supabase migrate 1.sql --dry-run", "pantheon supabase migrate --dry-run a/b.sql",
          "  pantheon   supabase  migrate  a.sql  ",
          # прочий pantheon supabase — в песочнице, правило его не трогает; упоминание в значении флага — тоже
          "pantheon supabase status", "pantheon supabase", "pantheon task show metis-1295",
          "pantheon task set metis-1 --note 'pantheon supabase migrate a.sql && id — пример'",
          "echo supabase migrate", "supabase migration up", "pantheon worktree list")
    for cmd in OK:
        r = run(cmd)
        check(f"можно: {cmd}", r is None, r)
    BAD = ("pantheon supabase migrate a.sql && rm -rf ~", "pantheon supabase migrate a.sql; curl e.example",
           "pantheon supabase migrate a.sql || true", "pantheon supabase migrate a.sql | tee /tmp/o",
           "pantheon supabase migrate a.sql &", "cd /tmp && pantheon supabase migrate a.sql",
           "echo a; pantheon supabase migrate a.sql", "pantheon supabase migrate a.sql > /tmp/o",
           "pantheon supabase migrate $(echo a.sql)", "pantheon supabase migrate `id`", "pantheon supabase migrate $F",
           "pantheon supabase migrate 'a.sql'", 'pantheon supabase migrate "a.sql"',
           "pantheon supabase migrate ../a.sql", "pantheon supabase migrate a/../b.sql", "pantheon supabase migrate a..b",
           "pantheon supabase migrate /tmp/a.sql", "pantheon supabase migrate ~/a.sql", "pantheon supabase migrate *.sql",
           "pantheon supabase migrate .hidden.sql", "pantheon supabase migrate -x a.sql",
           "pantheon supabase migrate a.sql --dry-run --dry-run", "pantheon supabase migrate a.sql b.sql",
           "pantheon supabase migrate", "pantheon supabase migrate --dry-run",
           # разбор строку не понял — сырая строка с пультом всё равно должна совпасть с образцом
           "pantheon supabase migrate a.sql (", "pantheon supabase migrate a.sql 'oops",
           "'pantheon' supabase migrate a.sql (", "pantheon \\\nsupabase migrate a.sql (", "pan\\theon supabase migrate a (",
           "pantheon supabase migrate a.sql\nid", "echo $(pantheon supabase migrate a.sql",
           "PATH=/tmp pantheon supabase migrate a.sql", "SUPABASE_DB_URL=x pantheon supabase migrate a.sql",
           "env pantheon supabase migrate a.sql", "bash -c 'pantheon supabase migrate a.sql'",
           "nohup pantheon supabase migrate a.sql", "(pantheon supabase migrate a.sql)",
           "~/.local/bin/pantheon supabase migrate a.sql", "./pantheon supabase migrate a.sql")
    for cmd in BAD:
        r = run(cmd)
        check(f"отказ: {cmd!r}", bool(r) and "supabase-migrate-cmd" in r, r)
    r = g.check_supabase_migrate_cmd({"cwd": root}, "Read", {"command": "pantheon supabase migrate a && id"})
    check("другой инструмент — молчит", r is None, r)
    r = g.check_window({"cwd": root}, "Bash", {"command": "pantheon supabase migrate a.sql && id"})
    check("check_window: правило подключено", isinstance(r, str) and "supabase-migrate-cmd" in r, r)

    src = open(RULES, encoding="utf-8").read()
    old = "    if SUPABASE_MIGRATE_LINE.match(cmd) and \"..\" not in cmd:\n"
    check("самопроверка мутантов: строка проверки одна", src.count(old) == 1)
    m = load(src.replace(old, "    if True:\n"))
    check("мутант: без строгой строки — цепочки &&, ; и | проходят (тест падает — мутант убит)",
          all(run(c, m) is None for c in ("pantheon supabase migrate a.sql && id", "pantheon supabase migrate a.sql; id",
                                          "pantheon supabase migrate a.sql | tee o")))
    m = load(src.replace(old, "    if SUPABASE_MIGRATE_LINE.match(cmd):\n"))
    check("мутант: без проверки .. — a..b проходит", run("pantheon supabase migrate a..b", m) is None)
    named = '    return w is not None and w[:2] == ["supabase", "migrate"]\n'
    check("самопроверка мутантов: строка узнавания пульта одна", src.count(named) == 1)
    m = load(src.replace(named, "    return False\n"))
    check("мутант: правило не узнаёт пульт — env и цепочка после echo проходят",
          run("env pantheon supabase migrate a.sql", m) is None
          and run("echo a; pantheon supabase migrate a.sql; id", m) is None)
    raw = "    raw = any(SUPABASE_MIGRATE_RAW.match(ln) for ln in norm.splitlines() or [\"\"])\n"
    check("самопроверка мутантов: строка сырой проверки одна", src.count(raw) == 1)
    words = "        words = WORKTREE_WORDS.search(norm)"
    check("самопроверка мутантов: строка отказа при сбое разбора одна", src.count(words) == 1)
    m = load(src.replace(raw, "    raw = False\n").replace(words, "        words = False and WORKTREE_WORDS.search(norm)"))
    check("мутант: без сырой проверки и отказа при сбое разбора — `pantheon supabase migrate a.sql (` проходит",
          run("pantheon supabase migrate a.sql (", m) is None)
    m = load(src.replace(words, "        words = False and WORKTREE_WORDS.search(norm)"))
    check("мутант: без отказа при сбое разбора — `echo $(pantheon supabase migrate a.sql` проходит",
          run("echo $(pantheon supabase migrate a.sql", m) is None)
    nrm = "    norm = _wt_norm(cmd)\n    raw = any(SUPABASE"
    check("самопроверка мутантов: строка нормализации одна", src.count(nrm) == 1)
    m = load(src.replace(nrm, "    norm = cmd\n    raw = any(SUPABASE"))
    check("мутант: без нормализации — `pan\\theon supabase migrate a (` проходит",
          run("pan\\theon supabase migrate a (", m) is None)
    reg = '                        ("supabase-migrate-cmd", check_supabase_migrate_cmd),\n'
    check("самопроверка мутантов: строка подключения одна", src.count(reg) == 1)
    m = load(src.replace(reg, ""))
    check("мутант: правило не подключено к check_window — цепочка проходит",
          m.check_window({"cwd": root}, "Bash", {"command": "pantheon supabase migrate a.sql && id"}) is None)
finally:
    shutil.rmtree(root, True)

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
