#!/usr/bin/env python3
"""Входящие копии Obsidian (metis-0920): view-sync.sh не переносит .claude и не копирует inbox-view в копию, тревога
при разрастании входящих, разовая уборка scripts/inbox-view-cleanup.py. Только временные папки.

Запуск: python3 -I plugins/pantheon/tests/test_view_inbox.py  (код выхода 0 — все прошли)
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311

_ROOT = tempfile.mkdtemp(prefix="view-inbox-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib")
RUN_PY = os.path.join(LIB, "run.py")
CLEAN = os.path.join(PLUGIN, "scripts", "inbox-view-cleanup.py")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def put(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def sync(src, dst, inbox):
    return subprocess.run(["/bin/zsh", os.path.join(LIB, "view-sync.sh"), src, dst, inbox], capture_output=True,
                          text=True, timeout=300)


def sync_tests():
    t = tempfile.mkdtemp(prefix="sync-")
    src, dst = os.path.join(t, "src"), os.path.join(t, "dst")
    inbox = os.path.join(src, "inbox-view")
    put(os.path.join(src, "board.md"), "доска\n")
    put(os.path.join(inbox, "20261103-120000-старое.md"), "во входящих\n")
    # копия: следы старого круга + служебная .claude + настоящая лишняя заметка
    put(os.path.join(dst, "inbox-view", "20261103-120000-старое.md"), "во входящих\n")
    put(os.path.join(dst, "inbox-view", "вложенное", "a.md"), "a\n")
    put(os.path.join(dst, ".claude", "scheduled_tasks.json"), "{}\n")
    put(os.path.join(dst, ".claude", "worktrees", "w", "f.txt"), "w\n")
    put(os.path.join(dst, "Новая заметка.md"), "моя заметка\n")
    r = sync(src, dst, inbox)
    check("sync: rc 0", r.returncode == 0, r.stderr)
    check("sync: .claude в копии остаётся (не удаляется rsync)", os.path.isfile(os.path.join(dst, ".claude", "scheduled_tasks.json"))
          and os.path.isfile(os.path.join(dst, ".claude", "worktrees", "w", "f.txt")))
    check("sync: .claude не уходит во входящие",
          not any(".claude" in f for f in os.listdir(inbox)), str(os.listdir(inbox)))
    check("sync: .claude в копии остаётся записываемым (права не сняты)",
          os.access(os.path.join(dst, ".claude", "scheduled_tasks.json"), os.W_OK))
    check("sync: inbox-view из копии убран", not os.path.exists(os.path.join(dst, "inbox-view")))
    check("sync: обычная лишняя заметка по-прежнему уходит во входящие",
          any(f.endswith("-Новая заметка.md") for f in os.listdir(inbox)) and not os.path.exists(os.path.join(dst, "Новая заметка.md")))
    check("sync: оригинал копируется", os.path.isfile(os.path.join(dst, "board.md")))
    n0 = len(os.listdir(inbox))
    sync(src, dst, inbox)
    sync(src, dst, inbox)
    check("sync: повторные проходы входящие не растят и в копию не кладут",
          len(os.listdir(inbox)) == n0 and not os.path.exists(os.path.join(dst, "inbox-view")))
    # входящие в нестандартном месте внутри оригинала
    inbox2 = os.path.join(src, "обмен", "in")
    put(os.path.join(inbox2, "z.md"), "z\n")
    put(os.path.join(src, "обмен", "keep.md"), "k\n")
    sync(src, dst, inbox2)
    check("sync: входящие по другому пути внутри оригинала тоже не копируются",
          not os.path.exists(os.path.join(dst, "обмен", "in")) and os.path.isfile(os.path.join(dst, "обмен", "keep.md")))
    # входящие снаружи оригинала: обычный оригинал с папкой inbox-view всё равно не копируется
    put(os.path.join(src, "inbox-view", "k.md"), "k\n")
    sync(src, dst, os.path.join(t, "вне"))
    check("sync: inbox-view оригинала не копируется и при входящих снаружи", not os.path.exists(os.path.join(dst, "inbox-view")))


def view_tests():
    t = tempfile.mkdtemp(prefix="view-")
    home, state, view = (os.path.join(t, x) for x in ("pantheon", "state", "view"))
    os.makedirs(os.path.join(home, "inbox-view"))
    os.makedirs(view)
    env = {"PATH": os.environ["PATH"], "HOME": t, "PANTHEON_HOME": home, "PANTHEON_STATE": state, "PANTHEON_VIEW": view,
           "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1", "TZ": "Europe/Moscow"}

    def go():
        r = subprocess.run([PY311, "-I", RUN_PY, "view", "--quiet"], env=env, capture_output=True, text=True, timeout=300)
        return r.returncode, r.stdout + r.stderr

    def fill(n, start=0):
        for i in range(start, start + n):
            put(os.path.join(home, "inbox-view", f"f{i}.md"))
    rc, out = go()
    check("тревога: пустые входящие — тихо", rc == 0 and "view-inbox" not in out and "входящ" not in out.lower(), out)
    fill(5)
    rc, out = go()
    check("тревога: рост на 5 (меньше порога роста) — тихо", "файлов" not in out, out)
    fill(25, 5)
    rc, out = go()
    check("тревога: рост за проход на 25 — тревога", "30 файлов" in out and "было 5" in out, out)
    fill(300, 100)
    rc, out = go()
    check("тревога: больше 200 файлов — тревога", "330 файлов" in out, out)
    # нет роста, ниже предела: тихо
    for f in os.listdir(os.path.join(home, "inbox-view")):
        os.remove(os.path.join(home, "inbox-view", f))
    fill(150)
    go()
    rc, out = go()
    check("тревога: 150 без роста — тихо", "файлов" not in out, out)
    for k in range(3):  # медленный рост по 15 за проход: порог роста не берёт, предел — берёт на 210
        fill(15, 150 + 15 * k)
        rc, out = go()
        check(f"тревога: {165 + 15 * k} файлов медленным ростом — тихо", "файлов" not in out, out)
    fill(15, 195)
    rc, out = go()
    check("тревога: 210 файлов медленным ростом — тревога по пределу", "210 файлов" in out, out)


def cleanup_tests():
    t = tempfile.mkdtemp(prefix="clean-")
    src = os.path.join(t, "pantheon")
    inbox = os.path.join(src, "inbox-view")
    arch = os.path.join(t, "arch")
    put(os.path.join(src, "a", "orig.md"), "оригинал\n")
    put(os.path.join(inbox, "20261103-120000-a__orig.md"), "оригинал\n")                       # совпадает
    put(os.path.join(inbox, "20261103-120001-inbox-view__20261103-120000-a__orig.md"), "оригинал\n")  # вложенное, совпадает
    put(os.path.join(inbox, "20261103-120002-.claude__worktrees__w.txt"), "служебное, другое\n")   # .claude
    put(os.path.join(inbox, "20261103-120003-inbox-view__20261103-120002-.claude__s.json"), "{}\n")  # вложенное .claude
    put(os.path.join(inbox, "20261103-120004-пусто.md"), "")                                      # пустое
    put(os.path.join(inbox, "20261103-120005-Моя заметка.md"), "ценное\n")                        # в архив
    put(os.path.join(inbox, "sub", "20261103-120006-глубоко.md"), "ценное 2\n")                   # в архив
    # inbox внутри src не должен считаться «оригиналом»: файл с уникальным содержимым только во входящих
    r = subprocess.run([sys.executable, "-I", CLEAN, "--src", src, "--archive", arch], capture_output=True, text=True)
    check("уборка: без --apply rc 0, считает 2 служебных, 3 дубля/пустых, 2 в архив",
          r.returncode == 0 and "служебное .claude — 2" in r.stdout and "пусто — 3" in r.stdout and "в архив — 2" in r.stdout, r.stdout)
    check("уборка: без --apply ничего не меняет", len(os.listdir(inbox)) == 7 and not os.path.exists(arch))
    r = subprocess.run([sys.executable, "-I", CLEAN, "--src", src, "--archive", arch, "--apply"], capture_output=True, text=True)
    left = [f for _d, _s, fs in os.walk(inbox) for f in fs]
    check("уборка: --apply убрал всё из входящих", r.returncode == 0 and left == [], f"{r.stdout} {left}")
    saved = sorted(os.listdir(arch)) if os.path.isdir(arch) else []
    check("уборка: ценное — в архиве с содержимым", len(saved) == 2 and any(
        open(os.path.join(arch, f), encoding="utf-8").read() == "ценное\n" for f in saved), str(saved))
    check("уборка: оригинал цел", open(os.path.join(src, "a", "orig.md"), encoding="utf-8").read() == "оригинал\n")
    r = subprocess.run([sys.executable, "-I", CLEAN, "--src", src, "--archive", os.path.join(inbox, "в"), "--apply"],
                       capture_output=True, text=True)
    check("уборка: архив внутри входящих — отказ, код 2", r.returncode == 2 and "архив" in r.stderr, r.stderr)


def main():
    if os.path.exists("/bin/zsh"):
        sync_tests()
    else:
        print("пропущено: нужен macOS — view-sync.sh запускается как /bin/zsh")
    view_tests() if os.path.exists("/bin/zsh") else None
    cleanup_tests()
    bad = results.count(False)
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
