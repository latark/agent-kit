#!/usr/bin/env python3
"""Тест словаря терминов glossary.toml: запрещённые слова не должны попадать в тексты, которые видит человек.

Что проверяется (решение лида metis-0205): README.md репозитория и плагина, skills/**/*.md, описание plugin.json — все
строки; *.py в lib/, hooks/, scripts/, bin/ — только строковые литералы (через ast), без комментариев и докстрингов
(кроме печатаемых справкой: докстринг модуля с `print(__doc__)` и функций с `<имя>.__doc__`); *.sh — строки без «#» в начале.
Ещё все строки roles/*.tmpl, roles/_parts/*.part, template/pantheon/*, plugins/guard/README.md и policy.example.toml,
строковые литералы plugins/guard/hooks/*.py (пути в находках и [[allow]] — «guard/…»).
Вне проверки: tests/ и функция sandbox_build (ядро, отдельный PR).
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

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
OK, FAIL = [], []

SKIP_FILES = set()
SKIP_FUNCS = {("lib/pantheon.py", "sandbox_build")}


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    if not cond:
        print(f"НЕ ПРОШЁЛ: {name} {detail}")


# --- чтение glossary.toml: tomllib (3.11+) или свой разбор подмножества (3.9) ---

STR_RE = r"""'[^']*'|"(?:[^"\\]|\\.)*\""""


def parse_mini(text):
    """Подмножество TOML словаря: [[таблица]], ключ = 'строка' | "строка" | [список строк в одной строке]."""
    out, cur = {}, None

    def one(s):
        return s[1:-1] if s[0] == "'" else json.loads(s)

    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"\[\[(\w+)\]\]", line)
        if m:
            cur = {}
            out.setdefault(m.group(1), []).append(cur)
            continue
        m = re.fullmatch(r"(\w+)\s*=\s*(.*)", line)
        if not m or cur is None:
            raise ValueError(f"glossary.toml:{n}: не разобрать: {raw}")
        key, val = m.group(1), m.group(2)
        if val.startswith("["):
            if re.sub(STR_RE, "", val).replace(",", "").replace(" ", "") != "[]":
                raise ValueError(f"glossary.toml:{n}: список не разобрать: {raw}")
            cur[key] = [one(s) for s in re.findall(STR_RE, val)]
        elif re.fullmatch(STR_RE, val):
            cur[key] = one(val)
        else:
            raise ValueError(f"glossary.toml:{n}: значение не разобрать: {raw}")
    return out


def load_glossary(path):
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")
    mini = parse_mini(text)
    try:
        import tomllib
    except ImportError:
        return mini, None
    return mini, tomllib.loads(text)


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
    for pattern in (("roles", "*.tmpl"), ("roles", "_parts", "*.part"), ("template", "pantheon", "*")):
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
    mini, real = load_glossary(path)
    if real is not None:
        check("свой разбор toml совпадает с tomllib", mini == real)
    else:
        print("tomllib нет (Python < 3.11): словарь читает свой разбор")
    gloss = real or mini
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
    finally:
        shutil.rmtree(tmp, True)


if __name__ == "__main__":
    main()
    print(f"тестов: {len(OK)} прошло, {len(FAIL)} не прошло")
    sys.exit(1 if FAIL else 0)
