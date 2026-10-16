#!/usr/bin/env python3
"""[private] policy.toml в sandbox_build читается по правилу guard 0.5.9 (metis-0163, часть pantheon).

Запуск: python3 -I plugins/pantheon/tests/test_private_conf.py  (код выхода 0 — все прошли)
- private_conf: не таблица или ключа нет — умолчание; значение не список — умолчание; список — только строки из него
  (strip, пустые убраны); roles и coordinators: пустой список — никого; paths: пустой список или без строк — умолчание;
- окно (`pantheon domains build` на временном HOME): [private] coordinators = [] — окно mnemo-brain личное не открывает,
  умолчание — открывает; paths из policy.toml попадают в denyRead остальных окон, мусор в paths — умолчание.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib", "pantheon.py")
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="private-conf-test-"))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def py311():
    if sys.version_info >= (3, 11):
        return sys.executable
    for v in ("3.14", "3.13", "3.12", "3.11"):
        p = shutil.which("python" + v)
        if p:
            return p
    sys.exit("нет Python 3.11+ для pantheon.py")


PROBE = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("pantheon", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print(json.dumps([m.private_conf(p) for p in json.loads(sys.argv[2])] + [m.DEFAULT_PRIVATE]))
"""

DEFAULT_ROLES, DEFAULT_COORD = ["hq", "chiron"], ["mnemo-brain"]


def conf_all(policies):
    r = subprocess.run([py311(), "-I", "-c", PROBE, LIB, json.dumps(policies)], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "HOME": ROOT})
    if r.returncode != 0:
        print(r.stderr)
        sys.exit("зонд private_conf упал")
    return json.loads(r.stdout)


def main():
    cases = [
        {},                                                   # 0: ключа нет
        {"private": "строка"},                                # 1: не таблица
        {"private": []},                                      # 2: не таблица
        {"private": {"roles": "hq", "coordinators": 5, "paths": {"a": 1}}},  # 3: значения не списки
        {"private": {"roles": [], "coordinators": [], "paths": []}},         # 4: пустые списки
        {"private": {"roles": ["x", 1, " y ", "", "  "], "coordinators": ["a-b", None, " c-d "],
                     "paths": ["~/p/one", 7, " ~/p/two ", ""]}},             # 5: смесь
        {"private": {"paths": [1, "", "   "]}},               # 6: paths без строк
        {"private": {"coordinators": [1, 2]}},                # 7: список без строк — никого
    ]
    got = conf_all(cases)
    default = got[-1]
    c = got[:-1]
    check("умолчание: roles, coordinators и четыре пути как у guard 0.5.9",
          default["roles"] == DEFAULT_ROLES and default["coordinators"] == DEFAULT_COORD
          and len(default["paths"]) == 4 and "~/ai/knowledge/me" in default["paths"])
    check("ключа [private] нет — всё по умолчанию", c[0] == default)
    check("[private] не таблица (строка, список) — всё по умолчанию", c[1] == default and c[2] == default)
    check("значение не список (строка, число, таблица) — умолчание по каждому ключу", c[3] == default)
    check("roles и coordinators пустым списком — никого; paths пустой — умолчание",
          c[4]["roles"] == [] and c[4]["coordinators"] == [] and c[4]["paths"] == default["paths"])
    check("список — только строки из него, strip, пустые убраны",
          c[5]["roles"] == ["x", "y"] and c[5]["coordinators"] == ["a-b", "c-d"]
          and c[5]["paths"] == ["~/p/one", "~/p/two"])
    check("paths без единой строки — умолчание", c[6]["paths"] == default["paths"] and c[6]["roles"] == default["roles"])
    check("coordinators списком без строк — никого, а не умолчание", c[7]["coordinators"] == [])

    # --- окна на временном HOME ---------------------------------------------------------------------------------------
    def build(tag, private_toml):
        tmp = os.path.join(ROOT, tag)
        home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
        os.makedirs(home)
        for d in ("projects/br", "ai/knowledge", "ai/knowledge/me", "projects/lone"):
            os.makedirs(os.path.join(tmp, d), exist_ok=True)
        with open(os.path.join(home, "directions.toml"), "w") as fh:
            fh.write('[[direction]]\nname = "athena-broker"\nfolders = ["~/projects/br"]\n'
                     '[[direction]]\nname = "mnemo-brain"\nfolders = ["~/ai/knowledge"]\n')
        os.makedirs(os.path.join(tmp, ".claude", "pantheon"))
        with open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w") as fh:
            fh.write(private_toml)
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
               "PANTHEON_NO_NOTIFY": "1"}
        r = subprocess.run([py311(), "-I", LIB, "domains", "build"], env=env, capture_output=True, text=True,
                           timeout=120)
        win = lambda n: json.load(open(os.path.join(state, "settings", n + ".json")))  # noqa: E731
        return r, win, tmp

    def reads(w):
        return w["sandbox"]["filesystem"]["denyRead"]

    me = lambda tmp: os.path.realpath(os.path.join(tmp, "ai/knowledge/me"))  # noqa: E731

    r, win, tmp = build("default", "")
    check("без policy.toml-ключа: окно mnemo-brain личное читает, окно athena-broker — нет (умолчание guard)",
          r.returncode == 0 and "~/ai/knowledge/me" not in reads(win("mnemo-brain"))
          and "~/ai/knowledge/me" in reads(win("athena-broker")) and "~/ai/knowledge/me" in reads(win("workshop")))
    r, win, tmp = build("empty", '[private]\ncoordinators = []\n')
    check("coordinators = [] — никого: и окно mnemo-brain личное не читает",
          "~/ai/knowledge/me" in reads(win("mnemo-brain")))
    r, win, tmp = build("garbage", '[private]\ncoordinators = "mnemo-brain"\npaths = 5\n')
    check("coordinators строкой, paths числом — умолчание (mnemo-brain читает, остальные нет)",
          "~/ai/knowledge/me" not in reads(win("mnemo-brain")) and "~/ai/knowledge/me" in reads(win("athena-broker")))
    r, win, tmp = build("custom", '[private]\ncoordinators = ["athena-broker"]\npaths = ["~/projects/lone", "no-tilde"]\n')
    check("свои coordinators и paths: athena-broker читает, mnemo-brain и мастерская — нет; путь без ~/ пропущен",
          "~/projects/lone" not in reads(win("athena-broker")) and "~/projects/lone" in reads(win("mnemo-brain"))
          and "~/projects/lone" in reads(win("workshop")) and "no-tilde" not in json.dumps(win("workshop")))

    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
