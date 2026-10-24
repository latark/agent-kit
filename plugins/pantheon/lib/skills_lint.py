"""Линтер навыков для `pantheon check` (metis-0258, Harness² п. 3).

Навык — папка с SKILL.md: шапка `---` с `name` и `description`, потом текст. Битая шапка не падает громко: навык
молча не загружается или не находится по описанию. Проверяем то, что ломает загрузку (ошибка) и что ухудшает
(предупреждение):
  ошибка:  нет закрытой шапки; нет name или description; name не по образцу (a-z, 0-9, дефис, до 64) или не равен
           имени папки; description длиннее 1024 знаков; пустой текст после шапки; относительная ссылка
           `[..](путь)` на файл, которого нет.
  внимание: SKILL.md длиннее 500 строк (держи основное в SKILL.md, остальное — в соседних файлах).
Функции чистые: читают файлы, ничего не пишут. Каталоги навыков задаёт вызывающий (pantheon.py: skills плагина и
~/.claude/skills).
"""
import os
import re

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DESC_MAX = 1024
NAME_MAX = 64
LINES_WARN = 500
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def parse_header(text):
    """(поля шапки, текст после неё) или (None, text), если шапки нет или она не закрыта."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fields = {}
            for ln in lines[1:i]:
                m = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", ln)
                if m:
                    v = m.group(2).strip()
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                        v = v[1:-1]
                    fields[m.group(1)] = v
            return fields, "\n".join(lines[i + 1:])
    return None, text


def lint_file(path):
    """(ошибки, предупреждения) одного SKILL.md."""
    errs, warns = [], []
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as e:
        return [f"файл не читается: {e.__class__.__name__}"], warns
    fields, body = parse_header(text)
    folder = os.path.basename(os.path.dirname(os.path.abspath(path)))  # имя папки-ссылки, не её цели
    if fields is None:
        return ["нет шапки `---` в начале файла или она не закрыта"], warns
    name = fields.get("name", "")
    if not name:
        errs.append("в шапке нет name")
    elif not NAME_RE.match(name) or len(name) > NAME_MAX:
        errs.append(f"name «{name}» не по образцу: строчные латинские буквы, цифры и дефис, до {NAME_MAX} знаков")
    elif name != folder:
        errs.append(f"name «{name}» не равен имени папки «{folder}»")
    desc = fields.get("description", "")
    if not desc:
        errs.append("в шапке нет description (по нему навык находят)")
    elif len(desc) > DESC_MAX:
        errs.append(f"description длиннее {DESC_MAX} знаков ({len(desc)})")
    if not body.strip():
        errs.append("после шапки пусто")
    base = os.path.dirname(os.path.realpath(path))
    in_fence = False
    for ln in body.split("\n"):
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
        if in_fence:
            continue
        for target in LINK_RE.findall(ln):
            if re.match(r"^([a-z][a-z0-9+.-]*:|#|/|~)", target):
                continue  # ссылка наружу, якорь или абсолютный путь — не проверяем
            rel = target.split("#", 1)[0]
            if rel and not os.path.exists(os.path.join(base, rel)):
                errs.append(f"ссылка на несуществующий файл: {target}")
    n = text.count("\n") + 1
    if n > LINES_WARN:
        warns.append(f"SKILL.md длиннее {LINES_WARN} строк ({n}): вынеси подробности в соседние файлы")
    return errs, warns


def skill_files(dirs):
    """SKILL.md всех навыков в каталогах dirs (папка/<навык>/SKILL.md). Папка без SKILL.md — не навык (например,
    служебная `synced` sessync), её пропускаем."""
    out = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            sub = os.path.join(d, name)
            if name.startswith(".") or not os.path.isdir(sub):
                continue
            f = os.path.join(sub, "SKILL.md")
            if os.path.isfile(f):
                out.append(f)
    return out


def lint_dirs(dirs):
    """[(путь, ошибки, предупреждения)] по всем навыкам каталогов."""
    res = []
    for f in skill_files(dirs):
        e, w = lint_file(f)
        res.append((f, e, w))
    return res
