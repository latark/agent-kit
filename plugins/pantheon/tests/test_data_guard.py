#!/usr/bin/env python3
"""Данные не в git (metis-0846): плановый коммит ~/ai/pantheon не берёт большие файлы и архивы/таблицы из inbox.

Запуск: python3 -I plugins/pantheon/tests/test_data_guard.py  (код выхода 0 — все прошли)
Настоящий git во временной папке, без remote; настоящий ~/ai/pantheon не трогается.
"""
import atexit
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311, mkroot  # noqa: E402

ROOT = os.path.realpath(mkroot("data-guard-"))
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


home = os.path.join(ROOT, "home")
state = os.path.join(ROOT, "state")
GENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
n = [0]


def fresh():
    """Новая папка плана с одним закоммиченным файлом."""
    n[0] += 1
    pan = os.path.join(ROOT, f"pan{n[0]}")
    os.makedirs(os.path.join(pan, "directions", "d1", "inbox"))
    os.makedirs(os.path.join(pan, "inbox"))
    os.makedirs(home, exist_ok=True)
    os.makedirs(state, exist_ok=True)
    env = {"PATH": os.environ["PATH"], "HOME": home, **GENV}
    subprocess.run(["git", "-C", pan, "init", "-q", "-b", "main"], env=env, check=True)
    open(os.path.join(pan, "a.md"), "w").write("a\n")
    subprocess.run(["git", "-C", pan, "add", "-A"], env=env, check=True)
    subprocess.run(["git", "-C", pan, "commit", "-q", "-m", "init"], env=env, check=True)
    return pan


def put(pan, rel, size):
    p = os.path.join(pan, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.write(b"x" * size)


def commit(pan, times=1):
    env = {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pan, "PANTHEON_STATE": state,
           "PANTHEON_NOTIFY_LOG": os.path.join(ROOT, "notify.log"), **GENV}
    code = f"import sys; sys.path.insert(0, {LIB!r}); import pantheon as p\n" + "p.commit()\n" * times
    r = subprocess.run([PY311, "-I", "-c", code], env=env, capture_output=True, text=True, timeout=60)
    if r.returncode:
        print(r.stdout, r.stderr)
    tracked = subprocess.run(["git", "-C", pan, "ls-files"], env=env, capture_output=True, text=True).stdout.split("\n")
    alerts = open(os.path.join(pan, "alerts.md")).read() if os.path.exists(os.path.join(pan, "alerts.md")) else ""
    return tracked, alerts


def gi(pan, rel="directions/d1/inbox"):
    try:
        return open(os.path.join(pan, rel, ".gitignore")).read()
    except OSError:
        return ""


MB = 1024 * 1024
D1 = "directions/d1/inbox/"

# 6 МБ файл в inbox направления
pan = fresh()
put(pan, D1 + "big.bin", 6 * MB)
tracked, alerts = commit(pan, times=2)  # второй проход — тревога не повторяется
check("6 МБ в inbox: не в коммите", D1 + "big.bin" not in tracked, tracked)
check("6 МБ в inbox: строка в .gitignore той же папки", "/big.bin" in gi(pan).split("\n"), gi(pan))
check("6 МБ в inbox: .gitignore в коммите", D1 + ".gitignore" in tracked, tracked)
check("6 МБ в inbox: тревога одна, с путём и размером",
      alerts.count("данные не в git: " + D1 + "big.bin, 6.0 МБ") == 1, alerts)

# маленький .md коммитится как раньше
pan = fresh()
put(pan, D1 + "note.md", 100)
put(pan, "inbox/n2.txt", 100)
tracked, alerts = commit(pan)
check("маленький .md и .txt в inbox коммитятся", D1 + "note.md" in tracked and "inbox/n2.txt" in tracked, tracked)
check("маленькие файлы: .gitignore не создан, тревоги нет", gi(pan) == "" and "данные не в git" not in alerts, alerts)

# .csv любого размера, и в inbox/ верхнего уровня; регистр расширения не важен
pan = fresh()
put(pan, D1 + "t.csv", 10)
put(pan, "inbox/T.ZIP", 10)
put(pan, "inbox/x.parquet", 0)
tracked, alerts = commit(pan)
check("csv, zip (верхний регистр) и parquet нулевого размера в inbox не в коммите",
      not any(t.endswith(("t.csv", "T.ZIP", "x.parquet")) for t in tracked), tracked)
check("csv: строка в .gitignore", "/t.csv" in gi(pan).split("\n"), gi(pan))
check("верхний inbox/: свой .gitignore", "/T.ZIP" in gi(pan, "inbox").split("\n") and "/x.parquet" in gi(pan, "inbox"), gi(pan, "inbox"))
check("тревога на каждый файл по одной", alerts.count("данные не в git") == 3, alerts)

# csv вне inbox — не данные inbox: коммитится (правило расширений только для inbox)
pan = fresh()
put(pan, "notes/t.csv", 10)
tracked, alerts = commit(pan)
check("csv вне inbox коммитится", "notes/t.csv" in tracked and "данные не в git" not in alerts, tracked)

# большой файл вне inbox тоже не уходит в историю; ровно 5 МБ — ещё можно
pan = fresh()
put(pan, "notes/huge.bin", 6 * MB)
put(pan, "notes/edge.bin", 5 * MB)
tracked, alerts = commit(pan)
check("6 МБ вне inbox не в коммите", "notes/huge.bin" not in tracked, tracked)
check("ровно 5 МБ коммитится (порог — больше 5 МБ)", "notes/edge.bin" in tracked, tracked)

# уже закоммиченное не трогаем; .gitignore дописывается, а не затирается
pan = fresh()
put(pan, D1 + "old.csv", 10)
env = {"PATH": os.environ["PATH"], "HOME": home, **GENV}
subprocess.run(["git", "-C", pan, "add", "-f", D1 + "old.csv"], env=env, check=True)
subprocess.run(["git", "-C", pan, "commit", "-q", "-m", "old"], env=env, check=True)
open(os.path.join(pan, D1, ".gitignore"), "w").write("keep-me")  # без перевода строки в конце
put(pan, D1 + "new.csv", 10)
tracked, alerts = commit(pan)
check("закоммиченный csv остаётся в индексе, без тревоги о нём", D1 + "old.csv" in tracked and "old.csv" not in alerts, (tracked, alerts))
check("существующий .gitignore дополнен: старая строка цела, новая на своей строке",
      gi(pan).split("\n")[:2] == ["keep-me", "/new.csv"], gi(pan))

# уже игнорируемый файл: ни повторной строки, ни тревоги
pan = fresh()
open(os.path.join(pan, D1, ".gitignore"), "w").write("/seen.csv\n")
put(pan, D1 + "seen.csv", 10)
tracked, alerts = commit(pan)
check("уже в .gitignore: строка не дублируется, тревоги нет",
      gi(pan) == "/seen.csv\n" and "данные не в git" not in alerts, (gi(pan), alerts))

# имя со спецзнаками: файл действительно игнорируется
pan = fresh()
put(pan, D1 + "my data [1] #2.csv", 10)
tracked, alerts = commit(pan)
st = subprocess.run(["git", "-C", pan, "status", "--porcelain", "-uall"], env=env, capture_output=True, text=True).stdout
check("имя с пробелом, [] и #: игнорируется и не в коммите",
      not any("my data" in t for t in tracked) and "my data" not in st, (tracked, st))

print("\n%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
