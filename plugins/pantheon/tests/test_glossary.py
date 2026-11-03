#!/usr/bin/env python3
"""Тест словаря терминов glossary.toml: запрещённые слова не должны попадать в тексты, которые видит человек.

Что проверяется (решение лида metis-0205): README.md репозитория и плагина, skills/**/*.md, описание plugin.json — все
строки; *.py в lib/, hooks/, scripts/, bin/ — только строковые литералы (через ast), без комментариев и докстрингов
(кроме печатаемых справкой: докстринг модуля с `print(__doc__)` и функций с `<имя>.__doc__`); *.sh — строки без «#» в начале.
Ещё все строки roles/*.tmpl, roles/_parts/*.part, template/pantheon/*, plugins/guard/README.md и policy.example.toml,
строковые литералы plugins/guard/hooks/*.py (пути в находках и [[allow]] — «guard/…»).
Вне проверки: tests/.
Исключения — [[allow]] в glossary.toml (файл + фрагмент строки + причина). Лишний [[allow]], который ничего не
находит, — тоже провал: список не должен зарастать.

Находка: «файл:строка: слово → правильно», код выхода 1.
Запуск: python3 -I plugins/pantheon/tests/test_glossary.py
"""
import ast
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
OK, FAIL = [], []

SKIP_FILES = set()
SKIP_FUNCS = set()


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    if not cond:
        print(f"НЕ ПРОШЁЛ: {name} {detail}")


# --- чтение glossary.toml ---

def load_glossary(path):
    with open(path, "rb") as fh:
        return tomllib.load(fh)


# --- сбор текстов ---

def helpful_docs(tree, rel):
    """Докстринги, которые печатаются справкой: модуль с `print(__doc__)` (любой файл) и функции с `<имя>.__doc__`."""
    ids = set()
    prints_module_doc = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "print"
                            and any(isinstance(a, ast.Name) and a.id == "__doc__" for a in n.args)
                            for n in ast.walk(tree))
    if prints_module_doc and ast.get_docstring(tree, clean=False) is not None:
        ids.add(id(tree.body[0].value))
    printed = {n.value.id for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and n.attr == "__doc__" and isinstance(n.value, ast.Name)}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in printed:
            if ast.get_docstring(n, clean=False) is not None:
                ids.add(id(n.body[0].value))
    return ids


def py_texts(path, rel):
    """(строка файла, текст строки) для строковых литералов; значение режется по переводам строк."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant) \
                    and isinstance(n.body[0].value.value, str):
                docs.add(id(n.body[0].value))
    keep = helpful_docs(tree, rel)
    skip_ranges = [(n.lineno, n.end_lineno) for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and (rel, n.name) in SKIP_FUNCS]
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if id(n) in docs and id(n) not in keep:
                continue
            if any(a <= n.lineno <= b for a, b in skip_ranges):
                continue
            for i, part in enumerate(n.value.split("\n")):
                yield n.lineno + i, part


def sh_texts(path):
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            if not line.lstrip().startswith("#"):
                yield i, line.rstrip("\n")


def all_lines(path):
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            yield i, line.rstrip("\n")


def is_python(path):
    if path.endswith(".py"):
        return True
    with open(path, "rb") as fh:
        return b"python" in fh.readline()


def collect(plugin):
    """[(относительный путь, номер строки, текст)] всего, что проверяется."""
    items = []
    repo = os.path.dirname(os.path.dirname(plugin))
    for p in (os.path.join(repo, "README.md"), os.path.join(plugin, "README.md")):
        if os.path.isfile(p):
            items += [("README.md" if os.path.dirname(p) == repo else "plugin/README.md", n, t)
                      for n, t in all_lines(p)]
    for p in sorted(glob.glob(os.path.join(plugin, "skills", "**", "*.md"), recursive=True)):
        items += [(os.path.relpath(p, plugin), n, t) for n, t in all_lines(p)]
    pj = os.path.join(plugin, ".claude-plugin", "plugin.json")
    if os.path.isfile(pj):
        with open(pj, encoding="utf-8") as fh:
            desc = json.load(fh).get("description", "")
        items.append((".claude-plugin/plugin.json", 1, desc))
    # роли, части ролей и шаблон ~/ai/pantheon читает человек (или они становятся его окном): все строки
    for pattern in (("roles", "*.tmpl"), ("roles", "_parts", "*.part"), ("roles", "_ref", "*.md"), ("template", "pantheon", "*")):
        for p in sorted(glob.glob(os.path.join(plugin, *pattern))):
            if os.path.isfile(p):
                items += [(os.path.relpath(p, plugin), n, t) for n, t in all_lines(p)]
    for sub in ("lib", "hooks", "scripts", "bin"):
        for p in sorted(glob.glob(os.path.join(plugin, sub, "*"))):
            rel = os.path.relpath(p, plugin)
            if not os.path.isfile(p) or rel in SKIP_FILES or p.endswith((".applescript", ".json")):
                continue
            if is_python(p):
                items += [(rel, n, t) for n, t in py_texts(p, rel)]
            else:
                items += [(rel, n, t) for n, t in sh_texts(p)]
    # guard: README и пример политики читает человек (все строки), тексты отказов — строковые литералы hooks/*.py
    guard = os.path.join(repo, "plugins", "guard")
    for name in ("README.md", "policy.example.toml"):
        p = os.path.join(guard, name)
        if os.path.isfile(p):
            items += [("guard/" + name, n, t) for n, t in all_lines(p)]
    for p in sorted(glob.glob(os.path.join(guard, "hooks", "*.py"))):
        rel = "guard/hooks/" + os.path.basename(p)
        items += [(rel, n, t) for n, t in py_texts(p, rel)]
    return items


def scan(plugin, gloss, allow):
    """-> (находки [(rel, line, слово, правильно, текст)], индексы неиспользованных allow)."""
    rules = []
    for t in gloss.get("term", []):
        for pat in t.get("patterns", []):
            rules.append((re.compile(pat, re.IGNORECASE), t["right"]))
    used, found = set(), []
    for rel, n, text in collect(plugin):
        for rx, right in rules:
            for m in rx.finditer(text):
                hit = [i for i, a in enumerate(allow) if a["file"] == rel and a["text"] in text]
                if hit:
                    used.update(hit)
                    continue
                found.append((rel, n, m.group(0), right, text.strip()))
    return found, [i for i in range(len(allow)) if i not in used]


def main():
    path = os.path.join(PLUGIN, "glossary.toml")
    check("glossary.toml есть", os.path.isfile(path), path)
    if FAIL:
        return
    gloss = load_glossary(path)
    allow = gloss.get("allow", [])
    check("у каждого [[allow]] есть file, text и reason",
          all(a.get("file") and a.get("text") and a.get("reason") for a in allow))
    check("у каждого термина есть right, forbidden, patterns, where",
          all(k in t for t in gloss.get("term", []) for k in ("right", "forbidden", "patterns", "where")))

    found, unused = scan(PLUGIN, gloss, allow)
    for rel, n, word, right, text in found:
        FAIL.append(f"{rel}:{n}")
        print(f"FAIL {rel}:{n}: {word} → {right}    | {text[:100]}")
    for i in unused:
        FAIL.append(f"allow#{i}")
        print(f"FAIL glossary.toml [[allow]] {allow[i]['file']} «{allow[i]['text']}»: ничего не находит — убрать")
    check("в проверяемых текстах нет запрещённых слов", not found, f"({len(found)} находок)")

    # само правило ловит: подложенный текст в копии плагина
    tmp = tempfile.mkdtemp(prefix="glossary-")
    try:
        fake = os.path.join(tmp, "plugins", "pantheon")
        os.makedirs(os.path.join(fake, "lib"))
        os.makedirs(os.path.join(fake, "skills", "x"))
        with open(os.path.join(fake, "lib", "a.py"), "w", encoding="utf-8") as fh:
            fh.write('"""Тик в докстринге не в счёт."""\n# запор в комментарии не в счёт\nprint("снять запор слияния")\n')
        with open(os.path.join(fake, "skills", "x", "SKILL.md"), "w", encoding="utf-8") as fh:
            fh.write("чисто\nНажми кнопку\n")
        f, u = scan(fake, gloss, [])
        got = sorted((r, n) for r, n, *_ in f)
        check("находка: файл и строка", got == [("lib/a.py", 3), ("skills/x/SKILL.md", 2)], str(got))
        f, u = scan(fake, gloss, [{"file": "lib/a.py", "text": "снять запор", "reason": "x"}])
        check("[[allow]] гасит находку", [r for r, *_ in f] == ["skills/x/SKILL.md"] and u == [], str((f, u)))
        f, u = scan(fake, gloss, [{"file": "lib/a.py", "text": "нет такого", "reason": "x"}])
        check("allow без совпадений попадает в неиспользованные", u == [0], str(u))
        # новые ветки сбора: роли, части ролей, шаблон ~/ai/pantheon, guard (README и литералы hooks), «подтолкни»
        for d in (("roles",), ("roles", "_parts"), ("template", "pantheon")):
            os.makedirs(os.path.join(fake, *d), exist_ok=True)
        gdir = os.path.join(tmp, "plugins", "guard")
        os.makedirs(os.path.join(gdir, "hooks"))
        seeds = {
            ("roles", "r.tmpl"): "чисто\nТы — штаб\n",
            ("roles", "_parts", "p.part"): "чисто\nпишет штаб\n",
            ("template", "pantheon", "t.md"): "чисто\nштаб решил\n",
        }
        for parts, text in seeds.items():
            with open(os.path.join(fake, *parts), "w", encoding="utf-8") as fh:
                fh.write(text)
        with open(os.path.join(gdir, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("чисто\nзакрыто штабу\n")
        with open(os.path.join(gdir, "hooks", "h.py"), "w", encoding="utf-8") as fh:
            fh.write('# штаб в комментарии не в счёт\nprint("отказ: штаб")\n')
        f, u = scan(fake, gloss, [])
        got = sorted((r, n) for r, n, *_ in f)
        want = sorted([("lib/a.py", 3), ("skills/x/SKILL.md", 2), ("roles/r.tmpl", 2), ("roles/_parts/p.part", 2),
                       ("template/pantheon/t.md", 2), ("guard/README.md", 2), ("guard/hooks/h.py", 2)])
        check("находки в roles, _parts, template/pantheon и guard", got == want, str(got))
        # мутанты (metis-0785): цвет у мутанта — находка; «убит/выжил» рядом с цветом теста — чисто
        mfile = os.path.join(fake, "roles", "_parts", "m.part")
        with open(mfile, "w", encoding="utf-8") as fh:
            fh.write("мутант строки 5 → тест красный\nтест красный на мутанте\nмутация «без -R» краснеет здесь\n"
                     "Мутант выжил — тесты зелёные, в тестах дыра.\nОткат → тест красный, мутант строки 5 → убит.\n"
                     "мутант строки 7 → тест красный, мутант строки 9 убит\nмутант красный; выжить сложно\n"
                     "тесты зелёные, мутации нет\nтест краснеет на откате правки и на мутанте\n")
        f, u = scan(fake, gloss, [])
        got = sorted(n for r, n, *_ in f if r == "roles/_parts/m.part")
        check("мутант в цвете — находка, «убит/выжил» у того же мутанта — чисто", got == [1, 2, 3, 6, 7, 9], str(got))
        os.remove(mfile)
        with open(os.path.join(fake, "lib", "b.py"), "w", encoding="utf-8") as fh:
            fh.write('x = "подтолкни сессию"\ny = "вытолкнуть"\nz = "протолкнул"\nw = "толкаем"\n')
        f, u = scan(fake, gloss, [])
        got = sorted(n for r, n, *_ in f if r == "lib/b.py")
        check("«подтолкни», «вытолкнуть», «протолкнул», «толкаем» — находки", got == [1, 2, 3, 4], str(got))
        # metis-0251: «подталкивать», «выталкивать» — находки
        with open(os.path.join(fake, "lib", "c.py"), "w", encoding="utf-8") as fh:
            fh.write('x = "подталкивать сессию"\ny = "выталкивать"\n')
        f, u = scan(fake, gloss, [])
        got = sorted(n for r, n, *_ in f if r == "lib/c.py")
        check("«подталкивать», «выталкивать» — находки", got == [1, 2], str(got))
        # metis-0251, [zeus-term-core]: «ядро Пантеона» и «правка ядра» проходят, «ядро окон» и похожее — находка
        with open(os.path.join(fake, "lib", "d.py"), "w", encoding="utf-8") as fh:
            fh.write('a = "ядро Пантеона"\nb = "правка ядра Пантеона"\nc = "PR: правка ядра"\nd = "права окна"\n'
                     'e = "ядро окон"\nf = "ядро окна"\ng = "Ядро окнами"\nh = "ядро защит"\n')
        f, u = scan(fake, gloss, [])
        got = sorted(n for r, n, *_ in f if r == "lib/d.py")
        check("«ядро Пантеона», «правка ядра», «права окна», «ядро защит» проходят; «ядро окон/окна» — находка",
              got == [5, 6], str(got))
    finally:
        shutil.rmtree(tmp, True)


if __name__ == "__main__":
    main()
    print(f"тестов: {len(OK)} прошло, {len(FAIL)} не прошло")
    sys.exit(1 if FAIL else 0)
