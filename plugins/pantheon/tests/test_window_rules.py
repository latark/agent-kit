#!/usr/bin/env python3
"""lib/window_rules.py (metis-0174): правила окон для слияния через шлюз guard вынесены из pantheon.py в отдельный
модуль ядра защит. Модуль грузится сам по пути файла (python3 -I), pantheon.py берёт правила из него и сам их не
определяет; сборка autoMode и permissions окна та же; шлюз guard считает файл ядром."""
import ast
import importlib.util
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
GATE = os.path.join(os.path.dirname(ROOT), "guard", "hooks", "merge_gate.py")
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or not detail else f"  [{detail}]"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    w = load("window_rules_t", os.path.join(LIB, "window_rules.py"))
    src = open(os.path.join(LIB, "window_rules.py"), encoding="utf-8").read()
    imports = re.findall(r"^\s*(?:import|from)\s+(\S+)", src, re.M)
    check("window_rules.py: без ввода-вывода и чужих модулей — только re", imports == ["re"], imports)
    check("правила на месте: COORDINATOR_ALLOW пуст (metis-0137), GATED_MERGE_RULE, REVIEW_RECORD_RULE",
          w.COORDINATOR_ALLOW == [] and w.GATED_MERGE_RULE.startswith("Pantheon Gated Merge:")
          and w.REVIEW_RECORD_RULE.startswith("Pantheon Review Record:"))

    allow = w.coordinator_auto_allow(["b-org/kit", "a-org/app", "bad owner", 5, "a-org/app", "-x/y"])
    check("coordinator_auto_allow: \"$defaults\" первым, слияние по owner/repo (сортировка, без дублей и мусора), "
          "Review Record последним",
          allow[0] == "$defaults" and len(allow) == 3 and "(`a-org/app`, `b-org/kit`)" in allow[1]
          and "bad owner" not in allow[1] and "-x/y" not in allow[1] and allow[2] == w.REVIEW_RECORD_RULE, allow)
    for repos in ([], None, "a-org/app", ["bad owner"]):
        got = w.coordinator_auto_allow(repos)
        check(f"coordinator_auto_allow({repos!r}): без правила слияния", got == ["$defaults", w.REVIEW_RECORD_RULE],
              got)
    check("auto_mode: раздел autoMode — копия списка",
          w.auto_mode(allow) == {"allow": allow} and w.auto_mode(allow)["allow"] is not allow)

    psrc = open(os.path.join(LIB, "pantheon.py"), encoding="utf-8").read()
    own = [x for x in ("Pantheon Gated Merge:", "Pantheon Review Record:", "COORDINATOR_ALLOW = [",
                       "def coordinator_auto_allow", "MERGE_REPO_RE = re.compile", '"autoMode"] = {')
           if x in psrc]
    check("pantheon.py сам правил не определяет — только берёт из window_rules.py", not own, own)

    if sys.version_info < (3, 11):  # pantheon.py требует 3.11 (tomllib)
        print("ok   пропуск: загрузка pantheon.py требует Python 3.11+")
    else:
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="window-rules-"))
        old = {k: os.environ.get(k) for k in ("HOME", "PANTHEON_HOME", "PANTHEON_STATE")}
        try:
            os.environ.update(HOME=tmp, PANTHEON_HOME=os.path.join(tmp, "ai/pantheon"),
                              PANTHEON_STATE=os.path.join(tmp, "state"))
            p = load("pantheon_t", os.path.join(LIB, "pantheon.py"))
            check("pantheon.py: имена правил — те же объекты из window_rules.py",
                  os.path.realpath(p.WINDOW_RULES.__file__)
                  == os.path.realpath(os.path.join(LIB, "window_rules.py"))
                  and all(getattr(p, n) is getattr(p.WINDOW_RULES, n) for n in (
                      "COORDINATOR_ALLOW", "GATED_MERGE_RULE", "REVIEW_RECORD_RULE", "MERGE_REPO_RE",
                      "coordinator_auto_allow")))
            rs = p.role_settings([], None, [], os.path.join(tmp, "cache"), False, [],
                                 auto_allow=p.coordinator_auto_allow(["a-org/app"]))
            check("role_settings: autoMode окна — из window_rules.auto_mode",
                  rs.get("autoMode") == {"allow": w.coordinator_auto_allow(["a-org/app"])}, rs.get("autoMode"))
            rs = p.role_settings([], None, [], os.path.join(tmp, "cache"), False, [])
            check("role_settings без auto_allow: autoMode нет", "autoMode" not in rs, rs.get("autoMode"))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            shutil.rmtree(tmp, ignore_errors=True)

    if os.path.exists(GATE):
        tree = ast.parse(open(GATE, encoding="utf-8").read())
        core = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "CORE_FILES" for t in n.targets)]
        check("шлюз guard: window_rules.py — в CORE_FILES (ядро защит, metis-0174)",
              len(core) == 1 and "plugins/pantheon/lib/window_rules.py" in core[0], core)
    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
