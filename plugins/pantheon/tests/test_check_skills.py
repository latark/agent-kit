#!/usr/bin/env python3
"""Линтер навыков в `pantheon check` (metis-0258, Harness² п. 3).

Запуск: python3 -I plugins/pantheon/tests/test_check_skills.py  (код выхода 0 — все прошли)
Подменены HOME, PANTHEON_HOME, PANTHEON_STATE и PANTHEON_SKILL_DIRS: настоящие навыки и ~/ai/pantheon не трогаются.
Проверяет: хороший навык проходит; каждая поломка (нет шапки, не закрыта, нет name/description, name не по образцу или
не равен папке, длинное description, пустой текст, битая ссылка) — ошибка и код 1; папка без SKILL.md не навык;
`check путь/SKILL.md` проверяет один навык; тик (--quiet) молчит о хорошем и пишет строку о плохом.
Линтер (модуль skills_lint.py) проверяется напрямую, CLI — подпроцессом.
"""
import importlib.util
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import tempfile
import atexit as _atexit
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="check-skills-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib", "pantheon.py")
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def load():
    spec = importlib.util.spec_from_file_location("skills_lint_t", os.path.join(PLUGIN, "lib", "skills_lint.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


GOOD = "---\nname: good-one\ndescription: Делает дело. Use when нужно дело.\n---\n\n# Дело\n\nТекст [ссылка](ref.md) и [сайт](https://x.org).\n"


def main():
    L = load()
    root = os.path.join(_ROOT, "skills")
    write(os.path.join(root, "good-one", "SKILL.md"), GOOD)
    write(os.path.join(root, "good-one", "ref.md"), "ref\n")
    f = lambda d: os.path.join(root, d, "SKILL.md")

    cases = {  # папка → (текст SKILL.md, часть ожидаемой ошибки)
        "no-header": ("# Просто текст\n", "нет шапки"),
        "unclosed": ("---\nname: unclosed\ndescription: x\n\nтекст\n", "нет шапки"),
        "no-name": ("---\ndescription: x\n---\n\nтекст\n", "нет name"),
        "no-desc": ("---\nname: no-desc\n---\n\nтекст\n", "нет description"),
        "empty-desc": ("---\nname: empty-desc\ndescription:\n---\n\nтекст\n", "нет description"),
        "bad-name": ("---\nname: Bad_Name\ndescription: x\n---\n\nтекст\n", "не по образцу"),
        "other-name": ("---\nname: something-else\ndescription: x\n---\n\nтекст\n", "не равен имени папки"),
        "long-desc": ("---\nname: long-desc\ndescription: " + "я" * 1025 + "\n---\n\nтекст\n", "длиннее 1024"),
        "empty-body": ("---\nname: empty-body\ndescription: x\n---\n\n", "после шапки пусто"),
        "dead-link": ("---\nname: dead-link\ndescription: x\n---\n\nСм. [файл](missing/x.md).\n", "несуществующий файл"),
    }
    for d, (text, _) in cases.items():
        write(f(d), text)
    write(os.path.join(root, "synced", "note.txt"), "служебная папка без SKILL.md\n")
    write(os.path.join(root, "fence", "SKILL.md"),
          "---\nname: fence\ndescription: x\n---\n\n```\n[пример](нет-такого.md)\n```\n")
    write(os.path.join(root, "limit", "SKILL.md"),
          "---\nname: limit\ndescription: " + "я" * 1024 + "\n---\n\nтекст\n")

    check("хороший навык: ни ошибок, ни предупреждений", L.lint_file(f("good-one")) == ([], []))
    for d, (_, want) in cases.items():
        errs, _ = L.lint_file(f(d))
        check(f"{d}: ошибка «{want}»", any(want in e for e in errs))
    real = os.path.join(_ROOT, "elsewhere", "skill")  # навык-ссылка: имя берётся из имени папки-ссылки, не цели
    write(os.path.join(real, "SKILL.md"), "---\nname: linked\ndescription: x\n---\n\nтекст\n")
    os.symlink(real, os.path.join(root, "linked"))
    check("папка-ссылка: name сверяется с именем ссылки (linked), а не с её целью (skill)", L.lint_file(f("linked")) == ([], []))
    check("ссылка внутри блока кода не проверяется", L.lint_file(f("fence")) == ([], []))
    check("description ровно 1024 знака — можно", L.lint_file(f("limit"))[0] == [])
    write(f("big"), GOOD.replace("good-one", "big") + "строка\n" * 600)
    write(os.path.join(root, "big", "ref.md"), "ref\n")
    e, w = L.lint_file(f("big"))
    check("длиннее 500 строк — только предупреждение", e == [] and any("500" in x for x in w))
    names = {os.path.basename(os.path.dirname(p)) for p in L.skill_files([root])}
    check("папка без SKILL.md (synced) не навык, остальные найдены", "synced" not in names and "good-one" in names
          and "no-header" in names)
    check("нет каталога навыков — пусто, без сбоя", L.lint_dirs([os.path.join(_ROOT, "nope")]) == [])

    # CLI: pantheon check
    tmp = os.path.join(_ROOT, "cli")
    home, state = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    write(os.path.join(home, "directions.toml"), "")

    def run(skill_dirs, *args):
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
               "PANTHEON_SKILL_DIRS": skill_dirs, "PANTHEON_NO_NOTIFY": "1"}
        return subprocess.run([PY311, "-I", LIB, "check", *args], env=env, capture_output=True, text=True, timeout=120)

    clean = os.path.join(_ROOT, "clean")
    write(os.path.join(clean, "good-one", "SKILL.md"), GOOD)
    write(os.path.join(clean, "good-one", "ref.md"), "ref\n")
    r = run(clean)
    check("check: хорошие навыки — код 0, строка «навыков: 1, с ошибками: 0»",
          r.returncode == 0 and "навыков: 1, с ошибками: 0" in r.stdout and "ОШИБКА · навык" not in r.stdout)
    r = run(root)
    check("check: плохие навыки — код 1, ОШИБКА с путём и причиной на последней строке про навыки",
          r.returncode == 1 and f"ОШИБКА · навык {f('no-name')}" in r.stdout and "не равен имени папки" in r.stdout
          and "с ошибками: 10" in r.stdout)
    r = run(clean, "--quiet")
    check("check --quiet: хорошие навыки — тишина и код 0", r.returncode == 0 and r.stdout.strip() == "")
    r = run(root, "--quiet")
    check("check --quiet: плохие навыки — ошибки напечатаны, итог про навыки есть, код 0 (тревога вместо кода)",
          r.returncode == 0 and "ОШИБКА · навык" in r.stdout and "навыков:" in r.stdout)
    r = run(clean, f("dead-link"))
    check("check путь/SKILL.md — только этот навык: код 1, остальные не проверяются",
          r.returncode == 1 and "несуществующий файл" in r.stdout and "навыков: 1, с ошибками: 1" in r.stdout)
    r = run(clean, os.path.join(clean, "good-one", "SKILL.md"))
    check("check путь/SKILL.md хорошего навыка — код 0", r.returncode == 0 and "с ошибками: 0" in r.stdout)

    task_md = os.path.join(_ROOT, "plain-task.md")
    write(task_md, "# обычный файл без шапки\n")
    r = run(clean, task_md, f("dead-link"))
    check("check задача.md + плохой SKILL.md: код 1, строка «навыков: 1, с ошибками: 1»",
          r.returncode == 1 and "навыков: 1, с ошибками: 1" in r.stdout and "несуществующий файл" in r.stdout)

    # тревога планового прохода: код 0, сигнал владельцу — одна строка в alerts.md (alert_once / clear_once)
    one = os.path.join(_ROOT, "one")
    bad_text = "---\nname: other\ndescription: x\n---\n\nтекст\n"
    write(os.path.join(one, "broken", "SKILL.md"), bad_text)
    alerts = os.path.join(home, "alerts.md")
    if os.path.exists(alerts):  # прежние прогоны выше уже ставили метку и писали тревоги — начинаем с чистого
        os.remove(alerts)
    _shutil.rmtree(os.path.join(state, "once"), ignore_errors=True)

    def n_alerts():
        if not os.path.exists(alerts):
            return 0
        return len([ln for ln in open(alerts, encoding="utf-8").read().splitlines() if "навыки с битой шапкой" in ln])

    r = run(one, "--quiet")
    check("тик: плохой навык — код 0 и ровно одна тревога в alerts.md, с именем навыка",
          r.returncode == 0 and n_alerts() == 1 and "broken" in open(alerts, encoding="utf-8").read())
    r = run(one, "--quiet")
    check("тик: повтор того же состояния — тревога не дублируется", r.returncode == 0 and n_alerts() == 1)
    write(os.path.join(one, "broken", "ref.md"), "ref\n")
    write(os.path.join(one, "broken", "SKILL.md"), GOOD.replace("good-one", "broken"))
    r = run(one, "--quiet")
    check("тик: навык исправлен — тишина, новых строк нет", r.returncode == 0 and r.stdout.strip() == "" and n_alerts() == 1)
    write(os.path.join(one, "broken", "SKILL.md"), bad_text)
    r = run(one, "--quiet")
    check("тик: после исправления метка снята — новая поломка даёт вторую тревогу", n_alerts() == 2)

    # нечитаемая папка навыков — ошибка в строке, а не трассировка
    locked = os.path.join(_ROOT, "locked")
    os.makedirs(locked)
    os.chmod(locked, 0)
    try:
        if os.access(locked, os.R_OK):  # root читает всё
            print("skip нечитаемая папка: процесс читает любые папки")
        else:
            rows = L.lint_dirs([locked])
            check("lint_dirs: нечитаемая папка — строка с ошибкой, без исключения",
                  len(rows) == 1 and rows[0][0] == locked and "не читается" in rows[0][1][0])
            r = run(locked)
            check("check: нечитаемая папка навыков — код 1, ОШИБКА без Traceback",
                  r.returncode == 1 and "ОШИБКА · навык" in r.stdout and "не читается" in r.stdout
                  and "Traceback" not in r.stderr)
    finally:
        os.chmod(locked, 0o700)

    print(f"\n{sum(results)}/{len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
