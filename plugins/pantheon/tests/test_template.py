#!/usr/bin/env python3
"""Шаблон пустого Пантеона (template/pantheon/): все файлы на месте, directions.toml читается и содержит [person].

Запуск: python3 -I plugins/pantheon/tests/test_template.py  (код выхода 0 — все прошли)
"""
import os
import sys

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "template", "pantheon")
OK, FAIL = [], []


def check(name, cond, detail=""):
    (OK if cond else FAIL).append(name)
    if not cond:
        print(f"НЕ ПРОШЁЛ: {name} {detail}")


def main():
    for f in ("directions.toml", "schema.md", "board.md", "decisions.md"):
        p = os.path.join(TPL, f)
        check(f"шаблон: {f} есть и не пуст", os.path.isfile(p) and os.path.getsize(p) > 0)
    for d in ("directions", "inbox"):
        check(f"шаблон: папка {d}/ есть", os.path.isdir(os.path.join(TPL, d)))
    check("шаблон: board.md и decisions.md с шапкой",
          open(os.path.join(TPL, "board.md"), encoding="utf-8").read().startswith("# Доска")
          and open(os.path.join(TPL, "decisions.md"), encoding="utf-8").read().startswith("# Журнал решений"))
    if sys.version_info < (3, 11):
        print("tomllib нет (Python < 3.11) — проверка directions.toml пропущена")
    else:
        import tomllib
        with open(os.path.join(TPL, "directions.toml"), "rb") as fh:
            data = tomllib.load(fh)
        person = data.get("person")
        check("directions.toml читается и содержит [person]", isinstance(person, dict))
        check("[person]: qmd_collections = [] и browser = \"\"",
              isinstance(person, dict) and person.get("qmd_collections") == [] and person.get("browser") == "")
        check("пример направления закомментирован — реестр пуст", not data.get("direction"))
    print(f"{len(OK)} из {len(OK) + len(FAIL)} прошли")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
