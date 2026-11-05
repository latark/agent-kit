#!/usr/bin/env python3
"""Храповик качества agent-kit (metis-0854): размер файлов, сложность функций и связи импорта не растут.

Запуск из корня репозитория:
  python3 -I plugins/pantheon/scripts/lint_ratchet.py            проверка против базы
  python3 -I plugins/pantheon/scripts/lint_ratchet.py --update   опустить базу до нынешнего (только после чистой проверки)
  --root ПАПКА    корень репозитория (по умолчанию — три уровня над скриптом)
  --baseline Ф    файл базы (по умолчанию lint-baseline.json рядом со скриптом в корне: вне ядра
                  guard, опустить базу после разбиения — обычный PR; рост базы видят дифф и argus)
  --ruff "КОМАНДА"  чем звать ruff (по умолчанию ruff на PATH той версии, что в .github/ruff-requirements.txt, иначе
                  `uvx ruff@<версия>`); без ключа — из LINT_RATCHET_RUFF, если задана (тесты run-tests.py)
  --init          записать базу впервые; есть база — отказ (поднять базу — только ручной правкой файла, она видна в диффе)

Файлы — все *.py из `git ls-files` и новые вне .gitignore. Правила (пороги — константы ниже, не в базе):
  0. Сначала обычный `ruff check .` по ruff.toml репозитория (кроме --init): ошибка — отказ. Так ruff идёт и в
     run-tests.py, то есть в .pantheon-verify и на запасном пути слияния, а не только в CI.
  1. Файл длиннее OLD_MAX строк не растёт против базы. Новый файл (его нет в базе) — не длиннее NEW_MAX строк.
  2. Сложность функций — ruff C901 (McCabe > 15), PLR0915 (операторов > 50), PLR0912 (ветвей > 12) с этими порогами
     только здесь: основной ruff.toml их не включает, иначе старый код краснеет. Ruff зовётся с --isolated и
     --ignore-noqa: ни ruff.toml, ни `# noqa` храповик не выключают. Ключ базы — файл, правило и имя функции
     (Класс.метод, внешняя.внутренняя), значение — число из сообщения ruff. Отказ: новая функция над порогом или число
     выросло. Так «одну починил, одну новую добавил» не проходит. Функция, перенесённая в другой файл с тем же именем и не
     большим числом, проходит: запись в старом файле исчезла (разбиение больших модулей, ревизия 18.10).
  3. Импорты: граф между файлами кода (без tests/ и test_*.py). Связь — `import X` и `from X import` с файлом X.py в
     репозитории (сначала в той же папке), загрузка файла по имени (spec_from_file_location, run_path, SourceFileLoader:
     строки «X.py» в той же функции; `_attach("X")`), обращение к имени P в plugins/pantheon/lib (загрузчик ставит туда
     модуль pantheon — обратная связь на pantheon.py), `sys.modules.get("X")` и `sys.modules["X"]`, обратная ссылка
     `B.X = <не константа>` из A, где X — глобальное имя модуля B (так guard_rules ставит G в хуки guard): связь B → A.
     Импорт под `if TYPE_CHECKING:` — не связь.
     Отказ: новый цикл — старые модули, которые в базе не были в одном цикле, теперь в одном; или цикл из одних новых.
     Новый модуль, вошедший в уже существующий цикл (вынос из pantheon.py с P), проходит. Отказ и на новую связь между
     плагинами (plugins/guard, plugins/pantheon, plugins/project-tools, .github): плагины ставятся отдельно.
  4. Обращения к ядру через обратную ссылку — `P.x` в plugins/pantheon/lib и `G.x` в plugins/guard/hooks (без тестов):
     в файле из базы их не больше, в сумме по репозиторию тоже — новый модуль берёт не больше, чем ушло из старых.
База только опускается: --update пишет нынешнее состояние, но строк — не больше, чем было, и только если проверка
чистая. Запись ниже базы — не отказ, а подсказка `--update` последней строкой.
Коды: 0 — чисто; 1 — отказ (причина и «что делать» — последней строкой); 2 — нет ruff, базы, git или ruff упал.
Только stdlib, Python 3.11+.
"""
import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

OLD_MAX = 1500
NEW_MAX = 800
RULES = {
    "C901": ("lint.mccabe.max-complexity", 15, "сложность McCabe"),
    "PLR0915": ("lint.pylint.max-statements", 50, "операторов"),
    "PLR0912": ("lint.pylint.max-branches", 12, "ветвей"),
}
BASELINE = os.path.join("plugins", "pantheon", "scripts", "lint-baseline.json")
RUFF_REQ = os.path.join(".github", "ruff-requirements.txt")
SELF = "python3 -I plugins/pantheon/scripts/lint_ratchet.py"
# Плагин загрузчика pantheon: в этой папке имя P — модуль pantheon (pantheon._attach и set_core).
CORE_BACKREF = ("plugins/pantheon/lib/", "P", "plugins/pantheon/lib/pantheon.py")
LOADERS = {"spec_from_file_location", "run_path", "SourceFileLoader"}
ATTACH = "_attach"
# Обратная ссылка на ядро по папке: P — модуль pantheon в lib (загрузчик), G — guard_rules в хуках guard. Число
# обращений `P.x`/`G.x` — скрытая связность (research 05.11: 88 % ошибок pyright), его храповик держит отдельно.
BACKREFS = {"plugins/pantheon/lib/": "P", "plugins/guard/hooks/": "G"}
PY_NAME = re.compile(r"([A-Za-z_][\w-]*)\.py")


class Fatal(Exception):
    """Ошибка окружения: код 2."""


def git_files(root):
    r = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.py"],
                       capture_output=True, text=True)
    if r.returncode:
        raise Fatal(f"git ls-files не прошёл в {root}: {r.stderr.strip()}")
    return sorted({p for p in r.stdout.split("\0") if p and os.path.isfile(os.path.join(root, p))})


def read(root, path):
    with open(os.path.join(root, path), "rb") as fh:
        return fh.read().decode("utf-8", "replace")


def count_lines(text):
    return len(text.splitlines())


def pinned_version(root):
    try:
        text = open(os.path.join(root, RUFF_REQ), encoding="utf-8").read()
    except OSError:
        return None
    m = re.search(r"^ruff==(\S+)", text, re.M)
    return m.group(1) if m else None


def ruff_command(root, given):
    """Команда ruff списком: --ruff, ruff на PATH закреплённой версии или uvx ruff@версия."""
    given = given or os.environ.get("LINT_RATCHET_RUFF")
    if given:
        return shlex.split(given)
    ver = pinned_version(root)
    if not ver:
        raise Fatal(f"нет версии ruff в {RUFF_REQ} — передай --ruff \"КОМАНДА\"")
    exe = shutil.which("ruff")
    if exe:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True)
        if r.stdout.split()[-1:] == [ver]:
            return [exe]
    if shutil.which("uvx"):
        return ["uvx", f"ruff@{ver}"]
    raise Fatal(f"нет ruff {ver}: поставь `pip install -r {RUFF_REQ}` или uv (uvx), либо передай --ruff")


def run_ruff(cmd, root, files):
    """Нарушения ruff по правилам RULES: [(файл от корня, правило, строка, число)]."""
    args = ["check", "--isolated", "--select", ",".join(RULES), "--config", 'target-version="py314"',
            "--ignore-noqa", "--exit-zero", "--no-cache", "--output-format", "json"]
    for key, limit, _ in RULES.values():
        args += ["--config", f"{key}={limit}"]
    out = []
    for i in range(0, len(files), 400):
        r = subprocess.run(cmd + args + files[i:i + 400], cwd=root, capture_output=True, text=True)
        try:
            items = json.loads(r.stdout)
        except ValueError:
            raise Fatal(f"ruff не дал JSON (код {r.returncode}): {(r.stderr or r.stdout).strip()[-300:]}")
        out += items
    real = os.path.realpath(root)
    res = []
    for it in out:
        m = re.search(r"\((\d+) > \d+\)", it.get("message") or "")
        if it.get("code") not in RULES or not m:
            continue
        rel = os.path.relpath(os.path.realpath(it["filename"]), real)
        res.append((rel, it["code"], it["location"]["row"], int(m.group(1))))
    return res


def run_lint(cmd, root):
    """Обычный `ruff check .` по ruff.toml репозитория → [«файл:строка: КОД сообщение»]."""
    r = subprocess.run(cmd + ["check", "--no-cache", "--exit-zero", "--output-format", "json", "."], cwd=root,
                       capture_output=True, text=True)
    try:
        items = json.loads(r.stdout)
    except ValueError:
        raise Fatal(f"ruff check . не дал JSON (код {r.returncode}): {(r.stderr or r.stdout).strip()[-300:]}")
    real = os.path.realpath(root)
    return [f"{os.path.relpath(os.path.realpath(it['filename']), real)}:{it['location']['row']}: {it.get('code')} "
            f"{it.get('message')}" for it in items]


def def_names(tree):
    """{строка def: Класс.метод / внешняя.внутренняя} — так ruff показывает функцию строкой её имени."""
    names = {}

    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + ch.name
                if not isinstance(ch, ast.ClassDef):
                    names[ch.lineno] = q
                walk(ch, q + ".")
            else:
                walk(ch, prefix)
    walk(tree, "")
    return names


def parse(root, path, cache):
    if path not in cache:
        try:
            cache[path] = ast.parse(read(root, path))
        except (SyntaxError, ValueError):
            cache[path] = None
    return cache[path]


def violations(found, root, cache):
    """{файл: {правило: {функция: число}}}: одинаковые имена в файле — с #2, #3."""
    res = {}
    for path, rule, row, value in sorted(found):
        tree = parse(root, path, cache)
        name = (def_names(tree).get(row) if tree else None) or f"строка {row}"
        rules = res.setdefault(path, {}).setdefault(rule, {})
        key, n = name, 1
        while key in rules:
            n += 1
            key = f"{name}#{n}"
        rules[key] = value
    return res


def is_type_checking(node):
    t = node.test
    return isinstance(t, ast.Name) and t.id == "TYPE_CHECKING" or isinstance(t, ast.Attribute) and t.attr == "TYPE_CHECKING"


def callee(call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None


def loaded_names(scope):
    """Имена модулей, которые область (функция или модуль без вложенных функций) грузит по имени файла."""
    names, calls, consts = set(), False, set()
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(n, ast.Call):
            calls = calls or callee(n) in LOADERS
            if callee(n) == ATTACH and n.args and isinstance(n.args[0], ast.Constant):
                names.add(str(n.args[0].value))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and PY_NAME.fullmatch(n.value):
            consts.add(n.value[:-3])
        stack.extend(ast.iter_child_nodes(n))
    return names | (consts if calls else set())


def sys_modules_name(n):
    """«X» из sys.modules.get("X") и sys.modules["X"] — модуль берут из уже загруженных (G в merge_gate.py)."""
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
        holder, arg = n.func.value, n.args[0] if n.args else None
    elif isinstance(n, ast.Subscript):
        holder, arg = n.value, n.slice
    else:
        return None
    if isinstance(holder, ast.Attribute) and holder.attr == "modules" and isinstance(arg, ast.Constant) \
            and isinstance(arg.value, str):
        return arg.value.split(".")[0]
    return None


def pokes(n):
    """{(имя, атрибут)} из `имя.атрибут = <не константа>`: так модуль ставит себя в чужой (protect_config.G = _SELF)."""
    if not isinstance(n, ast.Assign) or isinstance(n.value, ast.Constant):
        return set()
    return {(t.value.id, t.attr) for t in n.targets if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)}


def module_refs(tree, path):
    """Что файл берёт у других: names — имена модулей (импорт, загрузка по имени, sys.modules); core — обращение к P в
    папке загрузчика; aliases — {имя в файле: модуль} из import; pokes — {(имя, атрибут)} присвоенные в чужом модуле."""
    refs = {"names": set(), "core": False, "aliases": {}, "pokes": set()}
    stack = [tree]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.If) and is_type_checking(n):
            stack.extend(n.orelse)
            continue
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)):
            refs["names"] |= loaded_names(n)
        if isinstance(n, ast.Import):
            for a in n.names:
                refs["names"].add(a.name.split(".")[0])
                refs["aliases"][a.asname or a.name.split(".")[0]] = a.name.split(".")[0]
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            refs["names"].add(n.module.split(".")[0])
        elif isinstance(n, ast.Name) and n.id == CORE_BACKREF[1] and isinstance(n.ctx, ast.Load):
            refs["core"] = True
        refs["names"] |= {x for x in [sys_modules_name(n)] if x}
        refs["pokes"] |= pokes(n)
        stack.extend(ast.iter_child_nodes(n))
    refs["core"] = refs["core"] and path.startswith(CORE_BACKREF[0]) and path != CORE_BACKREF[2]
    return refs


def module_slots(tree):
    """Глобальные имена модуля (присваивания верхнего уровня) — куда другой модуль может поставить ссылку на себя."""
    out = set()
    for n in tree.body:
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        out |= {t.id for t in targets if isinstance(t, ast.Name)}
    return out


def is_code(path):
    parts = path.split("/")
    return "tests" not in parts[:-1] and not parts[-1].startswith("test_")


def resolve(by_name, path, name):
    """Файл модуля name для файла path: сначала в той же папке, иначе единственный в репозитории; None — нет или неоднозначно."""
    cands = by_name.get(name, [])
    pick = [c for c in cands if os.path.dirname(c) == os.path.dirname(path)] or cands
    return pick[0] if len(pick) == 1 and pick[0] != path else None


def import_graph(root, files, cache):
    """{файл: [файлы, от которых он зависит]} по файлам кода (без тестов). Обратная ссылка `B.X = <модуль A>` из A,
    где X — глобальное имя B, — связь B → A: B зовёт A через X (G в guard, как P в pantheon/lib)."""
    code = [p for p in files if is_code(p) and parse(root, p, cache) is not None]
    by_name = {}
    for p in code:
        by_name.setdefault(os.path.basename(p)[:-3], []).append(p)
    graph = {}
    for p in code:
        refs = module_refs(cache[p], p)
        out = graph.setdefault(p, set())
        if refs["core"] and CORE_BACKREF[2] in code:
            out.add(CORE_BACKREF[2])
        out |= {t for t in (resolve(by_name, p, nm) for nm in refs["names"]) if t}
        for local, attr in refs["pokes"]:
            target = resolve(by_name, p, refs["aliases"].get(local, ""))
            if target and attr in module_slots(cache[target]):
                graph.setdefault(target, set()).add(p)
    return {p: sorted(ts) for p, ts in sorted(graph.items()) if ts}


def sccs(graph):
    """Сильно связные компоненты больше одного узла (Тарьян без рекурсии), каждая — отсортированный список."""
    index, low, on, stack, res, counter = {}, {}, set(), [], [], [0]
    nodes = sorted(set(graph) | {t for ts in graph.values() for t in ts})
    for start in nodes:
        if start in index:
            continue
        work = [(start, iter(graph.get(start, ())))]
        index[start] = low[start] = counter[0]
        counter[0] += 1
        stack.append(start)
        on.add(start)
        while work:
            v, it = work[-1]
            nxt = next(it, None)
            if nxt is None:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    if len(comp) > 1:
                        res.append(sorted(comp))
            elif nxt not in index:
                index[nxt] = low[nxt] = counter[0]
                counter[0] += 1
                stack.append(nxt)
                on.add(nxt)
                work.append((nxt, iter(graph.get(nxt, ()))))
            elif nxt in on:
                low[v] = min(low[v], index[nxt])
    return sorted(res)


def path_between(graph, a, b, inside):
    """Кратчайший путь a → … → b по узлам inside (BFS), список узлов."""
    prev, queue = {a: None}, [a]
    for v in queue:
        for t in graph.get(v, ()):
            if t in inside and t not in prev:
                prev[t] = v
                queue.append(t)
    if b not in prev:
        return [a, b]
    out, v = [], b
    while v is not None:
        out.append(v)
        v = prev[v]
    return out[::-1]


def component(path):
    """Плагин (plugins/<имя>) или папка верхнего уровня (.github); файл в корне — «.»."""
    parts = path.split("/")
    if parts[0] == "plugins" and len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0] if len(parts) > 1 else "."


def scan(root, ruff):
    """Нынешнее состояние в формате базы."""
    files = git_files(root)
    cache = {}
    found = run_ruff(ruff, root, files)
    viol = violations(found, root, cache)
    state = {}
    for p in files:
        entry = {"lines": count_lines(read(root, p))}
        entry.update({r: viol[p][r] for r in RULES if r in viol.get(p, {})})
        n = backref_count(root, p, cache)
        if n:
            entry["backrefs"] = n
        state[p] = entry
    graph = import_graph(root, files, cache)
    return {"files": state, "imports": graph, "cycles": sccs(graph)}


def backref_count(root, path, cache):
    """Число обращений `P.x` (pantheon/lib) или `G.x` (guard/hooks) в файле кода; вне этих папок и в тестах — 0."""
    name = next((v for d, v in BACKREFS.items() if path.startswith(d)), None)
    tree = parse(root, path, cache) if name and is_code(path) else None
    if tree is None:
        return 0
    return sum(1 for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
               and n.value.id == name)


def check_backrefs(base, cur):
    """Обращения P./G.: в файле из базы не растут, в сумме по репозиторию тоже (новый модуль берёт не больше, чем ушло)."""
    fails = []
    for p, e in sorted(cur["files"].items()):
        old = base["files"].get(p)
        if old is not None and e.get("backrefs", 0) > old.get("backrefs", 0):
            fails.append(f"{p}: обращений к ядру через P./G. {e['backrefs']}, в базе {old.get('backrefs', 0)}. Что делать: "
                         "нужное ядро импортируй из модуля-листа (без P/G) или передай аргументом")
    total = {k: sum(e.get("backrefs", 0) for e in d["files"].values()) for k, d in (("base", base), ("cur", cur))}
    if not fails and total["cur"] > total["base"]:
        new = sorted(p for p, e in cur["files"].items() if p not in base["files"] and e.get("backrefs"))
        fails.append(f"обращений к ядру через P./G. стало {total['cur']}, в базе {total['base']} (новые модули: "
                     f"{', '.join(new) or '—'}). Что делать: в новом модуле бери нужное импортом модуля-листа, а не через P/G")
    return fails


def check_sizes(base, cur):
    fails = []
    for p, e in sorted(cur["files"].items()):
        n, old = e["lines"], base["files"].get(p)
        if old is None and n > NEW_MAX:
            fails.append(f"{p}: новый файл, {n} строк — больше {NEW_MAX}. Что делать: разбей его на модули до {NEW_MAX} "
                         f"строк по связности (кто кого вызывает)")
        elif old is not None and n > OLD_MAX and n > old["lines"]:
            fails.append(f"{p}: {n} строк, в базе {old['lines']} — файл длиннее {OLD_MAX} строк не растёт. Что делать: "
                         f"новое — в новый модуль рядом (до {NEW_MAX} строк), сюда только импорт; или вынеси столько "
                         f"же строк из этого файла")
    return fails


def orphans(base, cur):
    """{(правило, функция): [(файл, число)]} — записи базы, которых в их файле больше нет (функцию убрали или перенесли)."""
    out = {}
    for p, e in base["files"].items():
        now = cur["files"].get(p, {})
        for rule in RULES:
            for fn, v in e.get(rule, {}).items():
                if fn not in now.get(rule, {}):
                    out.setdefault((rule, fn), []).append((p, v))
    return out


def check_complexity(base, cur):
    fails, free = [], orphans(base, cur)
    for p, e in sorted(cur["files"].items()):
        old = base["files"].get(p, {})
        for rule, (_, limit, what) in RULES.items():
            for fn, v in sorted(e.get(rule, {}).items()):
                was = old.get(rule, {}).get(fn)
                if was is not None and v <= was:
                    continue
                moved = [(q, w) for q, w in free.get((rule, fn), []) if w >= v]
                if was is None and moved:
                    free[(rule, fn)].remove(moved[0])
                    continue
                head = f"{p}: {fn} — {rule} {v} {what} при пороге {limit}"
                tail = (f"в базе {was}. Что делать: не наращивай эту функцию — новую ветку вынеси в отдельную функцию"
                        if was is not None else
                        "в базе такой функции нет. Что делать: разбей функцию на части (ветки и шаги — в функции-помощники), "
                        f"чтобы {rule} не срабатывал")
                fails.append(f"{head}, {tail}")
    return fails


def check_cycles(base, cur):
    graph = cur["imports"]
    known = set(base["files"])
    knot = {n: i for i, comp in enumerate(sccs(base["imports"])) for n in comp}
    fails = []
    for comp in cur["cycles"]:
        old = [n for n in comp if n in known]
        loose = [n for n in old if n not in knot]
        ids = sorted({knot[n] for n in old if n in knot})
        inside = set(comp)
        if loose:
            a = loose[0]
            other = next(t for t in graph.get(a, ()) if t in inside)
            ring = path_between(graph, a, other, inside)[:-1] + path_between(graph, other, a, inside)
        elif len(ids) > 1:
            a = next(n for n in old if knot[n] == ids[0])
            b = next(n for n in old if knot[n] == ids[1])
            ring = path_between(graph, a, b, inside)[:-1] + path_between(graph, b, a, inside)
        elif not old:
            a = comp[0]
            other = next(t for t in graph.get(a, ()) if t in inside)
            ring = path_between(graph, a, other, inside)[:-1] + path_between(graph, other, a, inside)
        else:
            continue
        fails.append("новый цикл импорта: " + " → ".join(ring) + ". Что делать: общее у них вынеси в новый модуль-лист, "
                     "который не импортирует ни одного из них, и импортируй его с обеих сторон")
    return fails


def check_cross(base, cur):
    fails = []
    for a, ts in sorted(cur["imports"].items()):
        was = set(base["imports"].get(a, ()))
        for t in ts:
            if component(a) != component(t) and t not in was:
                fails.append(f"{a} → {t}: новая связь между плагинами ({component(a)} → {component(t)}), а плагины ставятся "
                             "отдельно. Что делать: нужный помощник — копией в своём плагине или вызов отдельным "
                             "процессом (subprocess)")
    return fails


def check(base, cur):
    return (check_sizes(base, cur) + check_complexity(base, cur) + check_backrefs(base, cur) + check_cycles(base, cur)
            + check_cross(base, cur))


def lowered(base, cur):
    """Новая база: нынешнее состояние, строк файла — не больше, чем было (база только опускается)."""
    files = {}
    for p, e in cur["files"].items():
        e = dict(e)
        if p in base["files"]:
            e["lines"] = min(e["lines"], base["files"][p]["lines"])
        files[p] = e
    return {"files": files, "imports": cur["imports"], "cycles": cur["cycles"]}


def stale(base, new):
    """Чем новая база ниже старой — строки для подсказки --update (мелкое укорачивание файлов до OLD_MAX не в счёт)."""
    out = []
    gone = sorted(set(base["files"]) - set(new["files"]))
    added = sorted(set(new["files"]) - set(base["files"]))
    if gone:
        out.append(f"файлов нет: {len(gone)}")
    if added:
        out.append(f"новых файлов: {len(added)}")
    for p, e in new["files"].items():
        old = base["files"].get(p)
        if old is None:
            continue
        if old["lines"] > OLD_MAX and e["lines"] < old["lines"]:
            out.append(f"{p}: {old['lines']} → {e['lines']} строк")
        for rule in (*RULES, "backrefs"):
            if old.get(rule, {}) != e.get(rule, {}):
                out.append(f"{p}: {rule} ниже базы")
    if base["imports"] != new["imports"]:
        out.append("связи импорта изменились")
    return out


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise Fatal(f"нет базы {path}: впервые — {SELF} --init")
    except (OSError, ValueError) as e:
        raise Fatal(f"база {path} не читается: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict) or not isinstance(data.get("imports"), dict):
        raise Fatal(f"база {path} не в том виде: нужны files и imports")
    return data


def save(path, data):
    out = {"about": "База храповика (metis-0854): только опускается через --update; поднять — ручной правкой с причиной "
                    "в PR. Пороги и правила — в plugins/pantheon/scripts/lint_ratchet.py.",
           "version": 1, **data}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def parse_args(argv):
    opts = {"root": os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "baseline": None, "ruff": None, "mode": "check"}
    it = iter(argv)
    for a in it:
        if a in ("--root", "--baseline", "--ruff"):
            val = next(it, None)
            if val is None:
                raise Fatal(f"{a}: нужно значение")
            opts[a[2:]] = val
        elif a in ("--update", "--init"):
            opts["mode"] = a[2:]
        elif a in ("-h", "--help"):
            opts["mode"] = "help"
        else:
            raise Fatal(f"неизвестный аргумент {a}; справка — --help")
    opts["baseline"] = opts["baseline"] or os.path.join(opts["root"], BASELINE)
    return opts


def run(opts):
    path = opts["baseline"]
    if opts["mode"] == "init" and os.path.exists(path):
        raise Fatal(f"база {path} уже есть: опустить — --update, поднять — только ручной правкой файла")
    ruff = ruff_command(opts["root"], opts["ruff"])
    cur = scan(opts["root"], ruff)
    if opts["mode"] == "init":
        save(path, cur)
        print(f"храповик: база записана — {path}")
        return 0
    base = load(path)
    fails = [f"ruff: {x}. Что делать: поправь (подробно — ruff check . версии из {RUFF_REQ}); намеренный приём — "
             "`# noqa: КОД` с причиной" for x in run_lint(ruff, opts["root"])] + check(base, cur)
    for f in fails:
        print(f)
    if fails:
        more = f" (и ещё {len(fails) - 1} выше)" if len(fails) > 1 else ""
        print(f"храповик: отказ{more} — {fails[0]}. Поднять базу можно только ручной правкой {BASELINE} с причиной в PR")
        return 1
    new = lowered(base, cur)
    diff = stale(base, new)
    if opts["mode"] == "update":
        save(path, new)
        print(f"храповик: база опущена ({'; '.join(diff[:5]) or 'без изменений по правилам'}) — {path}")
        return 0
    if diff:
        print(f"храповик: чисто; база устарела ({'; '.join(diff[:3])}{' …' if len(diff) > 3 else ''}). "
              f"Что делать: {SELF} --update и закоммить {BASELINE}")
        return 0
    print(f"храповик: чисто — {len(cur['files'])} файлов, циклов импорта {len(cur['cycles'])}")
    return 0


def main(argv):
    try:
        opts = parse_args(argv)
        if opts["mode"] == "help":
            print(__doc__)
            return 0
        return run(opts)
    except Fatal as e:
        print(f"храповик: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
