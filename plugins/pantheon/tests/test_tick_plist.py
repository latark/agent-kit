#!/usr/bin/env python3
"""Шаблон plist тика (PLIST_TMPL в lib/pantheon.py, metis-0728): ProcessType Standard, а не Background — иначе весь
плановый проход (и тесты в нём) сидит в QoS background на E-ядрах, `taskpolicy -c utility` изнутри это не снимает
(замер 03.11: 1522 с против 1515 с). Шаблон служб SVC_TMPL остаётся Background: службы и должны быть фоновыми.
Шаблон читается из исходника (ast), код pantheon.py не исполняется; launchd и ~/Library не трогаются.

Запуск: python3 -I plugins/pantheon/tests/test_tick_plist.py  (код выхода 0 — все прошли)
"""
import ast
import os
import re
import sys

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{str(detail)[:600]}]"))


def template(src, name):
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def process_type(tmpl):
    m = re.search(r"<key>ProcessType</key>\s*<string>([^<]*)</string>", tmpl or "")
    return m.group(1) if m else None


def tick_ok(src):
    return process_type(template(src, "PLIST_TMPL")) == "Standard"


with open(LIB, encoding="utf-8") as fh:
    SRC = fh.read()
check("plist тика: ProcessType Standard", tick_ok(SRC), process_type(template(SRC, "PLIST_TMPL")))
check("plist тика: нет слова Background", "Background" not in (template(SRC, "PLIST_TMPL") or "Background"))
check("plist служб: ProcessType Background (службы фоновые)", process_type(template(SRC, "SVC_TMPL")) == "Background",
      process_type(template(SRC, "SVC_TMPL")))
# мутанты: проверка должна краснеть, если в шаблоне тика снова Background или ProcessType убран
STD = "<key>ProcessType</key><string>Standard</string>"
BG = "<key>ProcessType</key><string>Background</string>"
mutant = SRC.replace(STD, BG, 1)
check("мутант (Background в тике) отлавливается", mutant != SRC and not tick_ok(mutant))
mutant2 = SRC.replace(STD + "\n", "", 1)
check("мутант (ProcessType убран) отлавливается", mutant2 != SRC and not tick_ok(mutant2))

print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
