#!/usr/bin/env python3
"""Мелкие правила guard 0.5.9: PY_LOADER (metis-0115) и умолчания [private] (metis-0163).

Запуск: python3 -I plugins/guard/tests/test_misc.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard.py")
TGR = "tg_" + "read"  # так этот файл не задевает правило живого хука
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


root = os.path.realpath(tempfile.mkdtemp(prefix="guard-misc-"))
os.environ["HOME"] = root
try:
    spec = importlib.util.spec_from_file_location("guard_under_test", GUARD)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)

    # --- PY_LOADER: compile( и exec( — только не после точки и не внутри имени ---
    f = TGR + ".py"
    check("re.compile( рядом с именем скрипта — не загрузка", not g.loads_tg_read(f"x = re.compile('a')  # {f}"))
    check("pattern.compile( — не загрузка", not g.loads_tg_read(f"p.compile(1); echo {f}"))
    check("recompile( внутри имени — не загрузка", not g.loads_tg_read(f"recompile(1); {f}"))
    check("compile(open(скрипт).read()) — загрузка",
          g.loads_tg_read(f'compile(open("{f}").read(), "x", "exec")'))
    check("exec( — загрузка", g.loads_tg_read(f'exec(open("{f}").read())'))
    check("builtins.exec( — загрузка", g.loads_tg_read(f'import builtins; builtins.exec(open("{f}").read())'))
    check("__builtins__.compile( — загрузка",
          g.loads_tg_read(f'__builtins__.compile(open("{f}").read(), "x", "exec")'))
    check("exec ( после точки с запятой — загрузка", g.loads_tg_read(f'a=1; exec (open("{f}").read())'))
    check("importlib — загрузка, как раньше", g.loads_tg_read(f"import importlib; importlib.x('{f}')"))
    check("runpy — загрузка, как раньше", g.loads_tg_read(f"python3 -m runpy {f}"))

    # --- private_conf: умолчания ---
    D = g.DEFAULT_PRIVATE
    roles = lambda priv: g.private_conf({"private": priv})["roles"]
    coord = lambda priv: g.private_conf({"private": priv})["coordinators"]
    paths = lambda priv: g.private_conf({"private": priv})["paths"]
    check("[private] нет — всё по умолчанию", g.private_conf({}) == D)
    check("private = строка — всё по умолчанию", g.private_conf({"private": "x"}) == D)
    check("private = список — всё по умолчанию", g.private_conf({"private": ["roles"]}) == D)
    check('roles = ["mnemo-brain"] — ровно он', roles({"roles": ["mnemo-brain"]}) == ["mnemo-brain"])
    check("roles = строка — умолчание (не подстрока)", roles({"roles": "mnemo-brain"}) == D["roles"])
    check('roles = [" mnemo-brain"] — strip', roles({"roles": [" mnemo-brain"]}) == ["mnemo-brain"])
    check('roles = ["mnemo-brain", 5] — число выброшено', roles({"roles": ["mnemo-brain", 5]}) == ["mnemo-brain"])
    check("roles = [] — никого", roles({"roles": []}) == [])
    check('roles = [5, " "] — после фильтра пусто: никого', roles({"roles": [5, " "]}) == [])
    check("roles нет — умолчание", roles({"coordinators": ["a"]}) == D["roles"])
    check("coordinators = [] — никого", coord({"coordinators": []}) == [])
    check("coordinators = строка — умолчание", coord({"coordinators": "mnemo-brain"}) == D["coordinators"])
    check('coordinators = [" a "] — strip', coord({"coordinators": [" a "]}) == ["a"])
    check("paths = [] — ничего, как у шлюза слияния (metis-0177)", paths({"paths": []}) == [])
    check("paths = [5] — после фильтра пусто: умолчание", paths({"paths": [5]}) == D["paths"])
    check("paths = строка — умолчание", paths({"paths": "~/ai/knowledge/me"}) == D["paths"])
    check('paths = ["~/x"] — только он', paths({"paths": ["~/x"]}) == ["~/x"])
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(0 if all(results) else 1)
