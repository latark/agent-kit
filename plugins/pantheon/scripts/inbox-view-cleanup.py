#!/usr/bin/env python3
"""Разовая уборка входящих копии Obsidian (~/ai/pantheon/inbox-view), metis-0920.

Что делает с каждым файлом входящих:
  - имя (после метки времени и повторов `inbox-view__`) начинается с `.claude__` — удаляет: служебная папка Claude Code;
  - пустой файл или файл, чьё содержимое совпадает с каким-либо файлом оригинала (кроме самих входящих) — удаляет;
  - остальное — переносит в архив (по умолчанию ~/ai/pantheon/archive/inbox-view-<метка>/) с тем же именем.
Без --apply только считает и печатает, ничего не меняя. Пустые папки входящих после уборки убирает.

Запуск:  python3.14 -I plugins/pantheon/scripts/inbox-view-cleanup.py [--apply] [--src ~/ai/pantheon]
         [--inbox <src>/inbox-view] [--archive <папка>]
Код выхода: 0 — готово, 2 — неверные параметры.
"""
import argparse
import hashlib
import os
import re
import shutil
import sys
import time

STAMP = re.compile(r"^\d{8}-\d{6}-")


def logical_name(name):
    """Имя без метки времени и без вложенных повторов `<метка>-inbox-view__`."""
    while True:
        m = STAMP.match(name)
        if m:
            name = name[m.end():]
            continue
        if name.startswith("inbox-view__"):
            name = name[len("inbox-view__"):]
            continue
        return name


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def src_hashes(src, inbox):
    out = set()
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if os.path.join(d, x) not in (os.path.join(src, ".git"), inbox)]
        for f in files:
            p = os.path.join(d, f)
            if not os.path.islink(p):
                try:
                    out.add(sha(p))
                except OSError:
                    pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=os.path.expanduser("~/ai/pantheon"))
    ap.add_argument("--inbox")
    ap.add_argument("--archive")
    ap.add_argument("--apply", action="store_true", help="без него — только подсчёт")
    a = ap.parse_args(argv)
    src = os.path.abspath(a.src)
    inbox = os.path.abspath(a.inbox or os.path.join(src, "inbox-view"))
    archive = os.path.abspath(a.archive or os.path.join(src, "archive", "inbox-view-" + time.strftime("%Y%m%d-%H%M%S")))
    if not os.path.isdir(inbox):
        print(f"нет папки входящих: {inbox}")
        return 0
    if archive == inbox or archive.startswith(inbox + os.sep):
        print("архив не может лежать во входящих", file=sys.stderr)
        return 2
    hashes = src_hashes(src, inbox)
    n = {"служебное .claude": 0, "копия оригинала или пусто": 0, "в архив": 0}
    for d, _dirs, files in os.walk(inbox):
        for f in files:
            p = os.path.join(d, f)
            if os.path.islink(p):
                kind = "в архив"
            elif logical_name(f).startswith(".claude__"):
                kind = "служебное .claude"
            elif os.path.getsize(p) == 0 or sha(p) in hashes:
                kind = "копия оригинала или пусто"
            else:
                kind = "в архив"
            n[kind] += 1
            if not a.apply:
                continue
            if kind == "в архив":
                os.makedirs(archive, exist_ok=True)
                dest = os.path.join(archive, os.path.relpath(p, inbox).replace(os.sep, "__"))
                i = 1
                while os.path.lexists(dest):
                    i += 1
                    dest = f"{dest}.{i}"
                shutil.move(p, dest)
            else:
                os.remove(p)
    if a.apply:
        for d, _dirs, _files in os.walk(inbox, topdown=False):
            if d != inbox:
                try:
                    os.rmdir(d)
                except OSError:
                    pass
    print(("выполнено: " if a.apply else "пробный проход, ничего не изменено: ")
          + ", ".join(f"{k} — {v}" for k, v in n.items()) + (f"; архив: {archive}" if n["в архив"] and a.apply else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
