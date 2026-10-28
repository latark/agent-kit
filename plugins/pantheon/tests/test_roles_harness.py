#!/usr/bin/env python3
"""Harness² в ролях (metis-0258, metis-0248 ш.3): настоящие шаблоны плагина собираются, а правила на месте.

Запуск: python3 -I plugins/pantheon/tests/test_roles_harness.py  (код выхода 0 — все прошли)
Роли собираются `pantheon roles build --out <папка>` из roles/ плагина в подменённых HOME и PANTHEON_HOME — настоящие
~/.claude/agents не трогаются. Проверяет:
  - урок в память только с вердиктом по контрасту: у всех ролей с памятью (argus, momus, prometheus, hephaestus, apollo);
  - три процедурных правила: у argus и prometheus;
  - правило «сам / один / параллельно»: у координатора; прежнего «Одна сессия или команда» нет; лид не режет цепочку;
  - недельная проверка clio ловит запись памяти без вердикта.
Мутант: шаблон argus без подключения частей собирается, но правил в роли нет — проверки выше на нём краснеют.
"""
import os
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import tempfile
import atexit as _atexit
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="roles-harness-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def read(p):
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


REG = ('[[direction]]\nname = "iris-demo"\nproject = "demo"\nfolders = ["~/projects/demo"]\n'
       'does = "Демо"\ndoes_not = "Чужое — соседям"\nleads = ["hephaestus", "apollo"]\nexamples = ["раз", "два", "три"]\n')


def build(roles_dir):
    """Собрать роли из roles_dir в чистую папку; (код, папка, вывод)."""
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="build-"))
    home, out = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "out")
    os.makedirs(home)
    os.makedirs(os.path.join(tmp, ".claude"))
    with open(os.path.join(home, "directions.toml"), "w", encoding="utf-8") as fh:
        fh.write(REG)
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": os.path.join(tmp, "state"),
           "PANTHEON_PLUGIN_ROLES": roles_dir, "PANTHEON_NO_NOTIFY": "1"}
    r = subprocess.run([PY311, "-I", RUN_PY, "roles", "build", "--out", out], env=env, capture_output=True, text=True,
                       timeout=120)
    return r.returncode, out, r.stdout + r.stderr


def main():
    code, out, log = build(os.path.join(PLUGIN, "roles"))
    check("роли плагина собираются (roles build --out), нет неразобранных {{",
          code == 0 and os.path.isdir(out) and not any("{{" in read(os.path.join(out, f)) for f in os.listdir(out)))
    if code != 0:
        print(log)
    r = lambda n: read(os.path.join(out, n + ".md"))

    LESSON = "Урок в память: только с вердиктом по контрасту"
    for role in ("argus", "momus", "prometheus", "hephaestus-demo", "apollo-demo"):
        check(f"{role}: урок в память — только с вердиктом", LESSON in r(role) and "не разделить" in r(role))
    check("роль без памяти (dev-sonnet) раздела об уроках не получает", LESSON not in r("dev-sonnet"))

    PROC = "Три процедурных правила"
    for role in ("argus", "prometheus"):
        t = r(role)
        check(f"{role}: опись входов, цифра → источник, повторное открытие файла",
              PROC in t and "Опись входных данных" in t and "Каждая цифра — с источником" in t
              and "открой заново и проверь" in t)
    check("argus возвращает работу без описи входов, без источника цифры, без повторной проверки файла",
          "нет описи входов" in r("argus"))

    coord = r("domain-coordinator")
    check("координатор: правило «сам / один / параллельно», четыре «да», выбор строкой в задаче",
          "Сам, одному исполнителю или параллельно" in coord and "четырёх «да»" in coord and "`mode_why`" in coord)
    check("координатор: «сам до 3 вызовов» не распространяется на код, правку кода отдаёт исполнителю",
          "на код не распространяется" in coord and "Код сам не пишешь" in coord)
    check("прежнего «Одна сессия или команда» нет ни в одной роли",
          not any("Одна сессия или команда" in read(os.path.join(out, f)) for f in os.listdir(out)))
    check("лид кода не режет цепочку, лид дизайна тоже", "Зависимую цепочку не режь" in r("hephaestus-demo")
          and "Дизайн отдельно от кода не режь" in r("apollo-demo"))
    check("hq: режим выбирает координатор", "выбирает координатор" in r("hq"))

    check("clio: недельная проверка ловит запись памяти без вердикта по контрасту",
          "Уроки в памяти ролей" in r("clio") and "без вердикта по контрасту" in r("clio"))

    # мутант: шаблон argus без подключения частей — сборка идёт, правил в роли нет
    mut = os.path.join(_ROOT, "roles-mut")
    _shutil.copytree(os.path.join(PLUGIN, "roles"), mut)
    with open(os.path.join(mut, "argus.tmpl"), "w", encoding="utf-8") as fh:
        fh.write(read(os.path.join(PLUGIN, "roles", "argus.tmpl")).replace("{{> lesson}}", "").replace("{{> procedure}}", ""))
    c2, out2, _ = build(mut)
    argus2 = read(os.path.join(out2, "argus.md"))
    check("мутант: argus.tmpl без частей собирается, но урока и трёх правил в роли нет",
          c2 == 0 and LESSON not in argus2 and "Три процедурных правила" not in argus2)

    print(f"\n{sum(results)}/{len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
