#!/usr/bin/env python3
"""metis-0718: status() и infra_check сверяют управляемые настройки с ПРОВЕРЕННЫМ деревом guard (verified.json,
merge.managed_source — как плановый проход), а не с клоном маркетплейса.

Запуск: python3 -I plugins/pantheon/tests/test_managed_compare.py  (код выхода 0 — все прошли)
Сценарии (HOME, PANTHEON_HOME, PANTHEON_STATE — временные; claude agents и guard подменены):
- файл «/Library» = проверенный, клон маркетплейса впереди → «совпадают» и в status, и в infra_check;
- файл «/Library» = клон, проверенный другой → «отстали» (status) и НЕТ (infra_check);
- проверенного дерева нет (записи в verified.json нет) → status «сверить не с чем», infra_check строки не даёт;
- файла «/Library» нет → status «НЕ установлены».
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
VERIFIED = b'{"v": "verified"}\n'
CLONE = b'{"v": "clone-ahead"}\n'

SCRIPT = r"""
import importlib.util, io, json, sys, contextlib
sys.path.insert(0, sys.argv[1])
import pantheon as P
spec = importlib.util.spec_from_file_location("watch_t", sys.argv[1] + "/watch.py")
w = importlib.util.module_from_spec(spec); spec.loader.exec_module(w); w.set_core(P)
P.MANAGED = sys.argv[2]
P.agents_all = lambda: []
P.guard_script = lambda: None
P.alert_once = P.clear_once = lambda *a, **k: None
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    P.status()
_, lines = w.infra_check()
print(json.dumps({"status": buf.getvalue(), "infra": lines}))
"""

fails, done = [], []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f" {extra}" if not cond else ""))
    done.append(name)
    if not cond:
        fails.append(name)


def box(installed, verified=True, clone=CLONE):
    """Домашняя папка: клон маркетплейса с файлом clone, проверенное дерево guard (если verified), файл «/Library»."""
    home = os.path.realpath(tempfile.mkdtemp(prefix="mancmp-"))
    os.makedirs(os.path.join(home, "ai", "pantheon"))
    state = os.path.join(home, "state")
    os.makedirs(os.path.join(state, "plugins"))
    mk = os.path.join(home, ".claude", "plugins", "marketplaces", "agent-kit", "plugins", "guard")
    os.makedirs(mk)
    with open(os.path.join(mk, "managed-settings.json"), "wb") as fh:
        fh.write(clone)
    tree = os.path.join(home, ".claude", "plugins", "cache", "agent-kit", "guard", "0.5.99")
    os.makedirs(os.path.join(tree, ".claude-plugin"))
    with open(os.path.join(tree, ".claude-plugin", "plugin.json"), "w") as fh:
        json.dump({"name": "guard", "version": "0.5.99"}, fh)
    with open(os.path.join(tree, "managed-settings.json"), "wb") as fh:
        fh.write(VERIFIED)
    with open(os.path.join(home, ".claude", "plugins", "installed_plugins.json"), "w") as fh:
        json.dump({"plugins": {"guard@agent-kit": [{"scope": "user", "installPath": tree}]}}, fh)
    env = {"HOME": home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "PANTHEON_HOME": os.path.join(home, "ai", "pantheon"),
           "PANTHEON_STATE": state, "PANTHEON_TEST": "1"}
    if verified:
        code = "import sys; sys.path.insert(0, %r); import pantheon as p; print(p._tree_hash(%r))" % (LIB, os.path.realpath(tree))
        h = subprocess.run([PY311, "-I", "-c", code], env=env, capture_output=True, text=True, timeout=60).stdout.strip()
        with open(os.path.join(state, "plugins", "verified.json"), "w") as fh:
            json.dump({"guard": {"hash": h, "path": tree, "version": "0.5.99"}}, fh)
    managed = os.path.join(home, "Library", "managed-settings.json")
    os.makedirs(os.path.dirname(managed))
    if installed is not None:
        with open(managed, "wb") as fh:
            fh.write(installed)
    return env, managed


def run(installed, verified=True):
    env, managed = box(installed, verified)
    r = subprocess.run([PY311, "-I", "-c", SCRIPT, LIB, managed], env=env, capture_output=True, text=True, timeout=120)
    if r.returncode not in (0, 1) or not r.stdout.strip().startswith("{"):
        print(r.stdout[-800:], r.stderr[-1500:])
        return {"status": "", "infra": []}
    return json.loads(r.stdout.strip().splitlines()[-1])


def managed_line(out):
    return next((ln.strip() for ln in out["status"].splitlines() if ln.strip().startswith("управляемые настройки:")), "")


def infra_line(out):
    return [ln for ln in out["infra"] if "управляемые настройки совпадают" in ln]


out = run(VERIFIED)
check("= проверенный, клон впереди: status «совпадают»", "совпадают с guard" in managed_line(out), managed_line(out))
check("= проверенный, клон впереди: infra_check «готово»", len(infra_line(out)) == 1 and infra_line(out)[0].startswith("готово"),
      infra_line(out))

out = run(CLONE)
check("= клон, проверенный другой: status «отстали»", "отстали" in managed_line(out), managed_line(out))
check("= клон, проверенный другой: infra_check «НЕТ»", len(infra_line(out)) == 1 and infra_line(out)[0].startswith("НЕТ"),
      infra_line(out))

out = run(VERIFIED, verified=False)
check("проверенного дерева нет: status «сверить не с чем»", "сверить не с чем" in managed_line(out), managed_line(out))
check("проверенного дерева нет: infra_check без строки о сверке", infra_line(out) == [], infra_line(out))

out = run(None)
check("файла /Library нет: status «НЕ установлены»", "НЕ установлены" in managed_line(out), managed_line(out))
check("файла /Library нет: infra_check без строки о сверке", infra_line(out) == [], infra_line(out))

print(f"\n{len(done) - len(fails)} из {len(done)} прошли")  # итог с числом: его требует run-tests.py
sys.exit(1 if fails else 0)
