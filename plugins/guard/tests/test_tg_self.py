#!/usr/bin/env python3
"""check_tg_secret_file не задевает файлы самого плагина guard в любой копии, но не шире (metis-0115 п.1).

Исключение (код правила tg-secret описывает импорт скрипта tg-read) действовало только для os.path.realpath(__file__) —
копии в маркетплейсе. Теперь: hooks/<файл>.py плагина guard в репозитории agent-kit (над plugins/ — маркетплейс
с name agent-kit: клон, worktree, копия маркетплейса) и в кэше ~/.claude/plugins/cache/agent-kit/guard/<версия>/hooks/.
Не шире: другое дерево с таким хвостом пути, вложенная папка в hooks/, tests/ — по-прежнему проверяются.

Запуск: python3 -I plugins/guard/tests/test_tg_self.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard.py")
IMPORT = "import tg_" + "read"  # так этот файл не задевает правило живого хука
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:600]))


root = os.path.realpath(tempfile.mkdtemp(prefix="tg-self-"))
home = os.path.join(root, "home")
os.makedirs(home)
os.environ["HOME"] = home
spec = importlib.util.spec_from_file_location("guard_under_test", GUARD)
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


def tree(base, marketplace):
    """base/plugins/guard/hooks/ + base/.claude-plugin/marketplace.json (или без него, если marketplace None)."""
    os.makedirs(os.path.join(base, "plugins", "guard", "hooks", "sub"))
    os.makedirs(os.path.join(base, "plugins", "guard", "tests"))
    if marketplace:
        os.makedirs(os.path.join(base, ".claude-plugin"))
        with open(os.path.join(base, ".claude-plugin", "marketplace.json"), "w") as fh:
            json.dump({"name": marketplace}, fh)
    return os.path.join(base, "plugins", "guard")


def verdict(path):
    return g.check_tg_secret_file({"file_path": path, "content": IMPORT + "\n"})


try:
    clone = tree(os.path.join(root, "clone"), "agent-kit")
    worktree = tree(os.path.join(root, "clone", ".claude", "worktrees", "w1"), "agent-kit")
    market = tree(os.path.join(home, ".claude", "plugins", "marketplaces", "agent-kit"), "agent-kit")
    evil = tree(os.path.join(root, "evil"), "other")
    bare = tree(os.path.join(root, "bare"), None)
    cache = os.path.join(home, ".claude", "plugins", "cache", "agent-kit", "guard", "0.5.6", "hooks")
    os.makedirs(os.path.join(cache, "sub"))
    elsewhere = os.path.join(home, ".claude", "plugins", "cache", "other", "guard", "1.0", "hooks")
    os.makedirs(elsewhere)

    check("контроль: правило срабатывает на обычном .py", verdict(os.path.join(root, "x.py")) == g.TG_IMPORT_REASON)
    for label, base in (("клон agent-kit", clone), ("worktree agent-kit", worktree), ("копия маркетплейса", market)):
        check(f"{label}: hooks/guard.py — исключение", verdict(os.path.join(base, "hooks", "guard.py")) is None)
        check(f"{label}: hooks/merge_gate.py — исключение", verdict(os.path.join(base, "hooks", "merge_gate.py")) is None)
        check(f"{label}: tests/x.py — проверяется", verdict(os.path.join(base, "tests", "x.py")) == g.TG_IMPORT_REASON)
        check(f"{label}: hooks/sub/x.py — глубже hooks/, проверяется",
              verdict(os.path.join(base, "hooks", "sub", "x.py")) == g.TG_IMPORT_REASON)
    check("кэш плагина: <версия>/hooks/guard.py — исключение", verdict(os.path.join(cache, "guard.py")) is None)
    check("кэш плагина: hooks/sub/x.py — проверяется", verdict(os.path.join(cache, "sub", "x.py")) == g.TG_IMPORT_REASON)
    check("кэш чужого плагина — проверяется", verdict(os.path.join(elsewhere, "x.py")) == g.TG_IMPORT_REASON)
    check("чужое дерево с хвостом plugins/guard/hooks — проверяется",
          verdict(os.path.join(evil, "hooks", "guard.py")) == g.TG_IMPORT_REASON)
    check("дерево без marketplace.json — проверяется", verdict(os.path.join(bare, "hooks", "guard.py")) == g.TG_IMPORT_REASON)
    # ключ в коде плагина исключение не снимает: оно только про импорт, а не про чтение ключа из Связки
    secret = {"file_path": os.path.join(clone, "hooks", "guard.py"),
              "content": "security find-generic-" + "password -s tg-" + "read -w\n"}
    check("ключ tg-read в файле плагина — по-прежнему отказ", g.check_tg_secret_file(secret) == g.TG_SECRET_REASON)
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(0 if all(results) else 1)
