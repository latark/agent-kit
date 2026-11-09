#!/usr/bin/env python3
"""Зависимости ядра защит — тоже ядро (metis-0858, ревизия архитектуры 05.11).

Ядро (Д3) — CORE_FILES и папки CORE_DIR шлюза guard (merge_gate.py): PR, который его задевает, сливает только
владелец. Если файл ядра берёт правило из файла вне ядра, агент меняет правило обычным PR, и граница течёт. Тест
читает по AST каждый файл ядра на Python (тесты не в счёт: это не путь защиты) и находит, откуда он берёт код:
  1. import и from … import — модуль рядом с файлом (каталог скрипта первым в sys.path) или пакет рядом;
     стандартная библиотека (sys.stdlib_module_names) — не зависимость;
  2. загрузка по пути — spec_from_file_location с литералом имени файла (`os.path.join(lib, "answers.py")`) —
     файл с этим именем в том же плагине; загрузка без литерала имени не проверяется — FAIL;
  3. P.<имя> в файлах ядра pantheon — модуль, где имя определено: lib/<модуль>.py, который pantheon.py подключает
     через _attach("<модуль>") (имена его __all__), или сам pantheon.py (имя верхнего уровня). Имя определено в
     нескольких местах — в счёт каждое: копия правила вне ядра перекрыла бы ядро.
Источник вне ядра — FAIL с причиной; исключения — явный список ниже, у каждого причина. Ещё: имена модулей ядра из
lib (review_rules.py) не определены верхним уровнем в других файлах lib — копия правила одна; пробные тексты
проверяют, что разбор ловит каждый путь.

Запуск: python3 -I plugins/guard/tests/test_core_deps.py   (код 0 — все прошли)
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MERGE_GATE = os.path.join(ROOT, "plugins", "guard", "hooks", "merge_gate.py")
PANTHEON_LIB = "plugins/pantheon/lib"
PANTHEON_PY = PANTHEON_LIB + "/pantheon.py"

# Файл вне ядра, который ядро берёт по пути или импортом, — с причиной, почему это не защита.
EXEMPT_FILES = {
    "plugins/pantheon/lib/statelen.py": "длина файлов состояния (ctx.py state-len): подсказка о размере, не защита "
                                        "(решение владельца 05.11, metis-0858: statelen.py не ядро)",
    "plugins/pantheon/lib/live_subagent.py": "правило «живой субагент» (ctx.py: подсказка /clear, список после /clear, "
                                             "resume; watch: перезапуск окна, уборка копий) — не защита "
                                             "(решение владельца 06.11, metis-0904: вариант А)",
}
# Имена P.<имя> из pantheon.py (не ядро), которыми пользуется ядро pantheon, — с причиной. Новое имя здесь — только
# после разбора: правило, от которого зависит решение шлюза или согласие владельца, место в модуле ядра.
_PATHS = "пути и время: HOME, STATE и папки Пантеона от них ставит сам merge.clean_env, тесты подменяют"
_IO = "обвязка ввода-вывода (замок, json, журнал, тревога владельцу): решений шлюза не принимает"
_NOTIFY = "уведомление владельцу о заявке: текст и показ, решение шлюза не меняет"
_MANAGED = ("управляемые настройки guard (metis-0710): какое дерево guard проверено — verified.json пишет плановый "
            "проход; вне задачи metis-0858 («А узко»), кандидат в ядро отдельной задачей")
_TASKS = "карточка «Руками» об управляемых настройках: сообщение владельцу, не решение"
EXEMPT_NAMES = {
    PANTHEON_PY: {
        "HOME": _PATHS, "AI_HOME": _PATHS, "CURRENT": _PATHS, "STATE": _PATHS, "PANTHEON": _PATHS, "LIB": _PATHS,
        "PLUGIN": _PATHS, "MANAGED": _PATHS, "path": _PATHS, "now": _PATHS, "stamp": _PATHS, "idle_sec": _PATHS,
        "lock": _IO, "alert": _IO, "alert_once": _IO, "read_json": _IO, "write_json": _IO,
        "_notifier": _NOTIFY, "notify_offscreen": _NOTIFY,
        "installed_dir": _MANAGED, "verified_record": _MANAGED,
        "tasks_mod": _TASKS,
    },
}

results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok or not info else "\n     " + str(info)[:3000]))


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def core_lists(src):
    """CORE_FILES и CORE_DIR из исходника merge_gate.py — литералом, без выполнения модуля."""
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("CORE_FILES", "CORE_DIR"):
            out[node.targets[0].id] = tuple(ast.literal_eval(node.value))
    return out.get("CORE_FILES", ()), out.get("CORE_DIR", ())


def in_core(path, files, dirs):
    return path in files or any(path == d or path.startswith(d + "/") for d in dirs)


def is_test(path):
    parts = path.split("/")
    return "tests" in parts[:-1] or parts[-1].startswith("test_")


def core_python(files, dirs):
    """Файлы ядра на Python, кроме тестов."""
    out = {f for f in files if f.endswith(".py") and os.path.isfile(os.path.join(ROOT, f))}
    for d in dirs:
        for top, subdirs, names in os.walk(os.path.join(ROOT, d)):
            subdirs[:] = [s for s in subdirs if s not in ("__pycache__", ".git")]
            out.update(rel(os.path.join(top, n)) for n in names if n.endswith(".py"))
    return sorted(p for p in out if not is_test(p))


def resolve_module(path, name, level):
    """import name (level — точки relative import) → путь файла в репозитории, «stdlib» или None (не найден)."""
    top = name.split(".")[0] if name else ""
    if level == 0 and top in sys.stdlib_module_names:
        return "stdlib"
    base = os.path.dirname(os.path.join(ROOT, path))
    for _ in range(max(level - 1, 0)):
        base = os.path.dirname(base)
    if not top:
        return rel(os.path.join(base, "__init__.py"))
    for cand in (os.path.join(base, top + ".py"), os.path.join(base, top, "__init__.py")):
        if os.path.isfile(cand):
            return rel(cand)
    return None


def plugin_of(path):
    parts = path.split("/")
    return "/".join(parts[:2]) if parts[0] == "plugins" and len(parts) > 2 else os.path.dirname(path)


def resolve_by_name(path, literal):
    """Литерал имени файла из spec_from_file_location → файлы с таким концом пути в том же плагине (кроме тестов)."""
    tail = literal.replace(os.sep, "/").lstrip("./")
    found = []
    for top, subdirs, names in os.walk(os.path.join(ROOT, plugin_of(path))):
        subdirs[:] = [s for s in subdirs if s not in ("__pycache__", ".git")]
        for n in names:
            p = rel(os.path.join(top, n))
            if (p == tail or p.endswith("/" + tail)) and not is_test(p):
                found.append(p)
    return found


def py_literals(node):
    """Литералы имени файла .py в вызове; «.py» без имени (name + ".py") — не имя."""
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.endswith(".py") and os.path.basename(n.value) != ".py"]


def call_name(node):
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def p_names():
    """Имя → [файлы, где оно определено] для P.<имя>: pantheon.py (верхний уровень) и модули его _attach (__all__)."""
    src_path = os.path.join(ROOT, PANTHEON_PY)
    tree = ast.parse(open(src_path, encoding="utf-8").read())
    where = {}

    def add(name, f):
        where.setdefault(name, [])
        if f not in where[name]:
            where[name].append(f)

    attached = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add(node.name, PANTHEON_PY)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        add(n.id, PANTHEON_PY)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                name = a.asname or a.name.split(".")[0]
                mod = a.name if isinstance(node, ast.Import) else (node.module or "")
                add(name, "stdlib" if mod.split(".")[0] in sys.stdlib_module_names else PANTHEON_PY)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and call_name(node.value) == "_attach" \
                and node.value.args and isinstance(node.value.args[0], ast.Constant):
            attached.append(node.value.args[0].value)
    # globals().update(... __all__) в _attach — имена модуля поверх имён pantheon.py: в счёт оба места
    for m in attached:
        f = f"{PANTHEON_LIB}/{m}.py"
        mt = ast.parse(open(os.path.join(ROOT, f), encoding="utf-8").read())
        for node in mt.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__"
                                                    for t in node.targets):
                for name in ast.literal_eval(node.value):
                    add(name, f)
    return where


def deps(path, names, src=None):
    """Зависимости файла ядра: [(откуда в файле, источник или None, текст ошибки или None)]. src — текст вместо файла
    (проба разбора)."""
    if src is None:
        src = open(os.path.join(ROOT, path), encoding="utf-8").read()
    tree = ast.parse(src, path)
    out = []
    uses_p = path.startswith("plugins/pantheon/") and any(
        isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "P" for t in n.targets)
        for n in tree.body)
    for node in ast.walk(tree):
        line = f"{path}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Import):
            for a in node.names:
                src = resolve_module(path, a.name, 0)
                out.append((f"{line} import {a.name}", src, None if src else f"модуль {a.name} не найден рядом"))
        elif isinstance(node, ast.ImportFrom):
            src = resolve_module(path, node.module or "", node.level)
            what = "." * node.level + (node.module or "")
            out.append((f"{line} from {what} import", src, None if src else f"модуль {what} не найден рядом"))
        elif isinstance(node, ast.Call) and call_name(node) in ("spec_from_file_location", "SourceFileLoader",
                                                                  "run_path", "import_module"):
            if call_name(node) == "import_module":
                lit = [n.value for n in node.args[:1] if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                src = resolve_module(path, lit[0], 0) if lit else None
                out.append((f"{line} import_module", src,
                            None if src else "import_module без литерала имени или модуль не найден"))
                continue
            lits = py_literals(node)
            if not lits:
                out.append((f"{line} {call_name(node)}", None, "загрузка по пути без литерала имени файла .py"))
            for lit in lits:
                found = resolve_by_name(path, lit)
                if len(found) != 1:
                    out.append((f"{line} {call_name(node)} «{lit}»", None,
                                f"файл «{lit}» в плагине {plugin_of(path)}: найдено {len(found)}, нужен ровно один"))
                else:
                    out.append((f"{line} {call_name(node)} «{lit}»", found[0], None))
        elif uses_p and isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == "P" and isinstance(node.ctx, ast.Load):
            srcs = names.get(node.attr)
            if not srcs:
                out.append((f"{line} P.{node.attr}", None, f"P.{node.attr} не определён в pantheon.py и его _attach"))
            for s in srcs or ():
                out.append((f"{line} P.{node.attr}", s, None))
    return out


def file_problems(path, names, files, dirs, src=None):
    bad = []
    for where, dep, error in deps(path, names, src):
        if error:
            bad.append(f"{where}: {error}")
            continue
        if dep == "stdlib" or in_core(dep, files, dirs) or dep in EXEMPT_FILES:
            continue
        attr = where.rsplit(" P.", 1)[1] if " P." in where else None
        if attr and attr in EXEMPT_NAMES.get(dep, {}):
            continue
        bad.append(f"{where} → {dep}: не ядро (нет в CORE_FILES и CORE_DIR merge_gate.py)")
    return bad


def problems(files, dirs, names):
    return [b for path in core_python(files, dirs) for b in file_problems(path, names, files, dirs)]


def top_names(path):
    """Имена верхнего уровня файла: def, class и присваивания."""
    out = set()
    for node in ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                out.update(n.id for n in ast.walk(t) if isinstance(n, ast.Name))
    return out


def copies(files, dirs, names):
    """Имена модулей ядра из lib (их __all__), которые ещё где-то в lib определены верхним уровнем, — копия правила
    вне ядра: её мог бы взять review status или любой другой путь мимо ядра."""
    core_mods = {f for ns in names.values() for f in ns if f.startswith(PANTHEON_LIB + "/") and in_core(f, files, dirs)}
    rule = {n: f for n, ns in names.items() for f in ns if f in core_mods}
    lib = os.path.join(ROOT, PANTHEON_LIB)
    out = []
    for fn in sorted(os.listdir(lib)):
        f = f"{PANTHEON_LIB}/{fn}"
        if fn.endswith(".py") and f not in core_mods:
            out += [f"{f}: {n} — копия из {rule[n]}" for n in sorted(top_names(f) & set(rule))]
    return out


def probes(files, dirs, names):
    """Разбор не слепой: на пробных текстах ловит каждый из путей и пропускает stdlib, ядро и запись P.x = …"""
    ctx, merge, gate = "plugins/pantheon/hooks/ctx.py", "plugins/pantheon/lib/merge.py", "plugins/guard/hooks/merge_gate.py"
    load = "import importlib.util, os\nspec = importlib.util.spec_from_file_location('x', os.path.join(lib, {}))\n"
    cases = [
        ("загрузка по пути: statelen.py — исключение, answers.py — ядро", ctx,
         load.format('"statelen.py"') + load.format('"answers.py"'), []),
        ("загрузка по пути файла вне ядра — FAIL", ctx, load.format('"consent.py"'), ["consent.py: не ядро"]),
        ("загрузка по пути без литерала — FAIL", ctx, load.format("name + '.py'"), ["без литерала"]),
        ("загрузка по пути: имени нет в плагине — FAIL", ctx, load.format('"nosuch_zz.py"'), ["найдено 0"]),
        ("import: stdlib и соседний файл ядра проходят", gate, "import json\nimport guard_rules\n", []),
        ("import: модуля нет рядом — FAIL", gate, "import nosuch_zz\n", ["nosuch_zz не найден"]),
        ("P.<имя> из review.py (не ядро) — FAIL", merge, "P = None\nP.review_cmd([])\n", ["review.py: не ядро"]),
        ("P.<имя> из review_rules.py (ядро) и исключение из pantheon.py проходят", merge,
         "P = None\nP.review_accept_counts({})\nP.lock('x')\n", []),
        ("P.<имя> из pantheon.py без исключения — FAIL", merge, "P = None\nP.sandbox_build()\n",
         ["pantheon.py: не ядро"]),
        ("P.<неизвестное> — FAIL", merge, "P = None\nP.nosuch_zz\n", ["не определён"]),
        ("запись P.x = … — не зависимость", merge, "P = None\nP.review_cmd = 1\n", []),
    ]
    for title, path, src, want in cases:
        if path.startswith("plugins/pantheon/") and not names:
            continue
        got = file_problems(path, names, files, dirs, src)
        check(f"проба: {title}", len(got) == len(want) and all(w in g for w, g in zip(want, got)), got)
    if names:
        dup = dict(names, review_accept_counts=names["review_accept_counts"] + [PANTHEON_LIB + "/review.py"])
        got = file_problems(merge, dup, files, dirs, "P = None\nP.review_accept_counts({})\n")
        check("проба: имя определено и в ядре, и вне (копия перекрыла бы ядро) — FAIL",
              len(got) == 1 and "review.py: не ядро" in got[0], got)


def main():
    files, dirs = core_lists(open(MERGE_GATE, encoding="utf-8").read())
    check("CORE_FILES и CORE_DIR прочитаны из merge_gate.py", files and dirs, (files, dirs))
    if not os.path.isfile(os.path.join(ROOT, PANTHEON_PY)):
        print(f"skip pantheon: нет {PANTHEON_PY} (рядом нет плагина)")
        names = {}
    else:
        names = p_names()
        check("pantheon.py: P.<имя> разобраны (_attach и верхний уровень)", "review_cmd" in names and "STATE" in names)
    bad = problems(files, dirs, names)
    check("зависимости файлов ядра — тоже ядро (или в списке исключений с причиной)", not bad, "\n     ".join(bad))
    if names:
        cp = copies(files, dirs, names)
        check("правило ядра одной копией: имена модулей ядра lib не определены в других файлах lib", not cp, cp)
        check("review_rules.py — модуль ядра с правилом вердиктов, review.py его не копирует",
              names.get("review_accept_counts") == [PANTHEON_LIB + "/review_rules.py"]
              and names.get("review_records") == [PANTHEON_LIB + "/review_rules.py"], names.get("review_accept_counts"))
    # исключения не стареют молча: файл есть, имя ещё определено там, где указано
    stale = [f for f in EXEMPT_FILES if not os.path.isfile(os.path.join(ROOT, f))]
    if names:
        stale += [f"{src}: {n}" for src, ns in EXEMPT_NAMES.items() for n in ns if src not in names.get(n, [])]
    check("исключения живые: файлы есть, имена определены там, где указано", not stale, stale)
    probes(files, dirs, names)
    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
