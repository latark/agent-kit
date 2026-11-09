"""Помощник test_context.py (metis-0330): решения хуков guard в одном долгоживущем процессе, как их будет принимать
демон хуков, — модули загружены один раз, а контекст каждого вызова (argv, окружение, папка) ставит guard.set_context.

    python3 -I _ctx_runner.py run <папка hooks> <задания.json> <итог.json> <parent|child>
    python3 -I _ctx_runner.py dump <папка hooks> [аргументы хука…]

run: задания — список {"hook": "guard"|"taint", "argv": […], "env": {…}, "cwd": …, "event": {…}}. На каждое задание —
fork, ребёнок отдаёт событие хуку на stdin и выходит его кодом (guard.run и taint.run_hook не возвращаются). Режим
parent: set_context зовёт сам процесс перед fork — контекст меняется много раз подряд в одном процессе. Режим child:
процесс остаётся в своём контексте загрузки, set_context зовёт ребёнок — как будущий демон. Итог — список
[код, stdout, stderr] по порядку заданий.
dump: значения всех имён контекста (глобальные из configure() модулей guard, guard_rules, taint) — после загрузки в
окружении и с аргументами этого процесса; печатает JSON. С переменной CTX_SET (JSON {"argv", "env"}) — после
set_context в уже загруженном процессе.
"""
import ast
import json
import os
import sys

MODULES = ("guard", "guard_rules", "taint")


def load(hooks):
    sys.path.insert(0, hooks)
    import guard  # noqa: F401 — вход; его configure() — при загрузке
    import guard_rules  # noqa: F401
    import taint  # noqa: F401
    return sys.modules


def context_names(path):
    """Имена из `global` функции configure() модуля — то, что она пересчитывает."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "configure":
            return sorted({n for g in ast.walk(node) if isinstance(g, ast.Global) for n in g.names})
    return []


def _plain(v):
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def dump(hooks):
    mods = load(hooks)
    ctx = os.environ.get("CTX_SET")
    if ctx:
        c = json.loads(ctx)
        mods["guard"].set_context(c["argv"], c["env"])
    out = {}
    for m in MODULES:
        mod = mods[m]
        out[m] = {n: _plain(getattr(mod, n)) for n in context_names(mod.__file__)}
    sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True) + "\n")


def run(hooks, jobs_file, out_file, where):
    mods = load(hooks)
    guard, taint = mods["guard"], mods["taint"]
    jobs = json.load(open(jobs_file, encoding="utf-8"))
    work = os.path.dirname(os.path.abspath(out_file))
    res = []
    for i, job in enumerate(jobs):
        evf, of, ef = (os.path.join(work, f"job{i}.{x}") for x in ("in", "out", "err"))
        with open(evf, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(job["event"], ensure_ascii=False))
        if where == "parent":
            guard.set_context(job["argv"], job["env"])
        sys.stdout.flush()
        sys.stderr.flush()
        pid = os.fork()
        if pid == 0:
            try:
                os.chdir(job["cwd"])
                os.dup2(os.open(evf, os.O_RDONLY), 0)
                os.dup2(os.open(of, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 1)
                os.dup2(os.open(ef, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 2)
                if where == "child":
                    guard.set_context(job["argv"], job["env"])
                if job["hook"] == "guard":
                    guard.run(job["argv"])
                else:
                    taint.run_hook()
            finally:
                os._exit(99)  # хук вернулся, а не вышел сам — такого быть не должно
        _, st = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(st)
        res.append([code, open(of, encoding="utf-8").read(), open(ef, encoding="utf-8").read()])
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False)


if __name__ == "__main__":
    if sys.argv[1] == "dump":
        dump(os.path.abspath(sys.argv[2]))
    else:
        run(os.path.abspath(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5])
