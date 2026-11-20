#!/usr/bin/env python3
"""[private] policy.toml в sandbox_build читается по правилу guard 0.5.9 (metis-0163, часть pantheon).

Запуск: python3 -I plugins/pantheon/tests/test_private_conf.py  (код выхода 0 — все прошли)
- private_conf: не таблица или ключа нет — умолчание; значение не список — умолчание; список — только строки из него
  (strip, пустые убраны); roles и coordinators: пустой список — никого; paths: пустой список или без строк — умолчание;
- окно (`pantheon domains build` на временном HOME): [private] coordinators = [] — окно mnemo-brain личное не открывает,
  умолчание — открывает; paths из policy.toml попадают в denyRead остальных окон, мусор в paths — умолчание;
- DEFAULT_PRIVATE сверяется с guard_rules.py рядом; в копии одного плагина (проверка установки) его нет — skip.
"""
import ast
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="private-conf-test-"))
atexit.register(shutil.rmtree, ROOT, True)
results = []


def check(name, cond):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name)


def py311():
    return sys.executable


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
    check("умолчание: roles, coordinators и семь путей (metis-0894: + Self, Areas, People)",
          default["roles"] == DEFAULT_ROLES and default["coordinators"] == DEFAULT_COORD
          and len(default["paths"]) == 7 and "~/ai/knowledge/me" in default["paths"])
    # metis-0894: каждая личная папка из PERSONAL (lib/moved.py) закрыта умолчанием, не только строкой policy.toml
    moved_py = os.path.join(os.path.dirname(LIB), "moved.py")
    personal = None
    with open(moved_py, encoding="utf-8") as fh:
        for node in ast.parse(fh.read()).body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "PERSONAL" for t in node.targets):
                personal = ast.literal_eval(node.value)
    check("умолчание paths покрывает каждую папку PERSONAL (me, Self, Areas, People)",
          personal and set(personal) >= {"me", "Self", "Areas", "People"}
          and all(f"~/ai/knowledge/{x}" in default["paths"] for x in personal))
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
            fh.write('[[direction]]\nname = "athena-shop"\nfolders = ["~/projects/br"]\n'
                     '[[direction]]\nname = "mnemo-brain"\nfolders = ["~/ai/knowledge"]\n')
        os.makedirs(os.path.join(tmp, ".claude", "pantheon"))
        with open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w") as fh:
            fh.write(private_toml)
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
               "PANTHEON_NO_NOTIFY": "1"}
        r = subprocess.run([py311(), "-I", RUN_PY, "domains", "build"], env=env, capture_output=True, text=True,
                           timeout=120)
        win = lambda n: json.load(open(os.path.join(state, "settings", n + ".json")))  # noqa: E731
        return r, win, tmp

    def reads(w):
        return w["sandbox"]["filesystem"]["denyRead"]


    r, win, tmp = build("default", "")
    check("без policy.toml-ключа: окно mnemo-brain личное читает, окно athena-shop — нет (умолчание guard)",
          r.returncode == 0 and "~/ai/knowledge/me" not in reads(win("mnemo-brain"))
          and "~/ai/knowledge/me" in reads(win("athena-shop")) and "~/ai/knowledge/me" in reads(win("workshop")))
    check("без policy.toml-ключа: Self, Areas, People закрыты окну athena-shop и мастерской, mnemo-brain — открыты "
          "(metis-0894)",
          all(f"~/ai/knowledge/{x}" in reads(win("athena-shop")) and f"~/ai/knowledge/{x}" in reads(win("workshop"))
              and f"~/ai/knowledge/{x}" not in reads(win("mnemo-brain")) for x in ("Self", "Areas", "People")))
    r, win, tmp = build("empty", '[private]\ncoordinators = []\n')
    check("coordinators = [] — никого: и окно mnemo-brain личное не читает",
          "~/ai/knowledge/me" in reads(win("mnemo-brain")))
    r, win, tmp = build("garbage", '[private]\ncoordinators = "mnemo-brain"\npaths = 5\n')
    check("coordinators строкой, paths числом — умолчание (mnemo-brain читает, остальные нет)",
          "~/ai/knowledge/me" not in reads(win("mnemo-brain")) and "~/ai/knowledge/me" in reads(win("athena-shop")))
    r, win, tmp = build("custom", '[private]\ncoordinators = ["athena-shop"]\npaths = ["~/projects/lone", "no-tilde"]\n')
    check("свои coordinators и paths: athena-shop читает, mnemo-brain и мастерская — нет; путь без ~/ пропущен",
          "~/projects/lone" not in reads(win("athena-shop")) and "~/projects/lone" in reads(win("mnemo-brain"))
          and "~/projects/lone" in reads(win("workshop")) and "no-tilde" not in json.dumps(win("workshop")))

    # --- metis-0894: check — личная папка есть, а [private] paths её не покрывают -------------------------------------
    def cover(tag, private_toml, quiet=False):
        tmp = os.path.join(ROOT, "cover-" + tag)
        home, state = os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "state")
        for d in ("ai/pantheon", "ai/knowledge/me", "ai/knowledge/Self", "ai/knowledge/Areas/sub", "ai/knowledge/raw",
                  ".claude/pantheon"):
            os.makedirs(os.path.join(tmp, d), exist_ok=True)
        with open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w") as fh:
            fh.write(private_toml)
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
               "PANTHEON_NO_NOTIFY": "1"}
        r = subprocess.run([py311(), "-I", RUN_PY, "check", *(["--quiet"] if quiet else [])], env=env,
                           capture_output=True, text=True, timeout=120)
        al = os.path.join(home, "alerts.md")
        return r.stdout + r.stderr, (open(al, encoding="utf-8").read() if os.path.isfile(al) else "")

    # тексты ролей о личном называют каждую папку PERSONAL, а не только me/
    for role in ("chiron", "clio", "momus"):
        with open(os.path.join(PLUGIN, "roles", role + ".tmpl"), encoding="utf-8") as fh:
            tmpl = fh.read()
        check(f"роль {role}: текст о личном называет каждую папку PERSONAL",
              personal and all(f"{x}/" in tmpl for x in personal))

    warn = "не покрыто [private] paths"
    out, _ = cover("narrow", '[private]\npaths = ["~/ai/knowledge/me"]\n')
    check("check: Self/ и Areas/ есть, а paths = только me/ — предупреждение с обеими, без People (её нет) и me",
          "предупреждение · личное ~/ai/knowledge/{Self,Areas} " + warn in out and "People" not in out)
    out, _ = cover("default", "")
    check("check: [private] paths нет — умолчание покрывает все, предупреждения нет", warn not in out)
    out, _ = cover("parent", '[private]\npaths = ["~/ai/knowledge"]\n')
    check("check: paths = вся ~/ai/knowledge — папки внутри покрыты, предупреждения нет", warn not in out)
    out, _ = cover("sibling", '[private]\npaths = ["~/ai/knowledge/Sel", "~/ai/knowledge/me", "~/ai/knowledge/Areas"]\n')
    check("check: ~/ai/knowledge/Sel — не предок Self/ (сравнение по частям пути)",
          "{Self} " + warn in out)
    _, al = cover("quiet", '[private]\npaths = ["~/ai/knowledge/me", "~/ai/knowledge/Areas"]\n', quiet=True)
    check("check --quiet: тревога в alerts.md о непокрытой Self/", "{Self} " + warn in al)

    # умолчание окна и умолчание guard не расходятся: guard_rules.py (правила guard, metis-0148) только читаем (ast)
    # Проверка установки (plugins-update) берёт копию одного плагина pantheon: соседнего guard там нет — сверку
    # пропускаем, а не падаем. В репозитории guard рядом есть, и сверка идёт; GUARD_PY задан — файл обязателен.
    guard_py = os.environ.get("GUARD_PY") or os.path.join(os.path.dirname(PLUGIN), "guard", "hooks", "guard_rules.py")
    if not os.environ.get("GUARD_PY") and not os.path.isfile(guard_py):
        print("skip DEFAULT_PRIVATE: guard_rules.py рядом нет (копия одного плагина)")
    else:
        gdef = None
        with open(guard_py, encoding="utf-8") as fh:
            for node in ast.parse(fh.read()).body:
                if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "DEFAULT_PRIVATE" for t in node.targets):
                    gdef = ast.literal_eval(node.value)
        check("DEFAULT_PRIVATE pantheon.py равен DEFAULT_PRIVATE guard_rules.py (roles, coordinators, paths)",
              gdef is not None and default == gdef)

    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
