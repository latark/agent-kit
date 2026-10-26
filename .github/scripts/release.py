#!/usr/bin/env python3
"""Выпуск плагинов agent-kit на main (metis-0512, вариант Б): номер версии поднимает Action после слияния, а не PR.

PR `version` в plugins/<плагин>/.claude-plugin/plugin.json и файл .claude-plugin/releases.json не трогают (шлюз guard
такой PR не сливает): иначе после каждого слияния у соседних PR конфликт в version, новый head и новый круг ревью.
Номер поднимает workflow .github/workflows/release.yml на каждый push в main:

  python3 -I .github/scripts/release.py [--push] [--remote origin] [--branch main]

Без состояния: каждый запуск считает «что изменилось с прошлого выпуска», а не «что слито в этом запуске», поэтому
отменённый или упавший запуск покрывает следующий.
1. Прошлый выпуск плагина — последний коммит первой родительской линии HEAD, где менялась строка "version" его
   plugin.json (коммит выпуска Action или, до metis-0512, слияние PR, поднявшего номер сам).
2. Плагин тронут, если `git diff <прошлый выпуск> HEAD -- plugins/<плагин>/` не пуст (любой файл, plugin.json тоже).
   Тронутому version +1 в последней части (0.11.127 → 0.11.128); в файле меняется только эта строка.
3. .claude-plugin/releases.json — {"v": 1, "plugins": {имя: {"version", "tree"}}} для всех плагинов: tree — sha256
   дерева папки плагина после подъёма, тем же счётом, что _tree_hash плагина pantheon. Плановый проход ставит новую
   версию, только если запись совпала с каталогом: слито, а выпуска ещё нет — не ставит (окно «номер ещё старый»).
4. Перед коммитом — сверка: изменены только plugin.json тронутых плагинов (и в них только version) и releases.json.
   Один коммит «выпуск: <плагин> <версия>, …» от github-actions[bot].
5. --push: git push <remote> HEAD:<branch>. Отказ (main ушёл вперёд — второе слияние подряд) — fetch, сброс на
   свежий <branch> и пересчёт с шага 1, до трёх попыток: свежий запуск покрывает и новое слияние.

Привилегированная цепочка (contents: write) — только этот файл и release.yml, оба в ядре шлюза (.github целиком,
CORE_DIR в merge_gate.py): PR, правящий их, сливает владелец. Скрипт ничего не импортирует из репозитория.

Коды: 0 — готово или поднимать нечего; 1 — отказ (дерево не чистое, version не разобрать, сверка не сошлась, push не
прошёл за три попытки); 2 — неверный вызов. Последняя строка вывода — итог или причина.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

RELEASES = ".claude-plugin/releases.json"
RELEASES_V = 1
VERSION_LINE = re.compile(r'("version"\s*:\s*")([^"\\]*)(")')
VERSION_G = '"version"[[:space:]]*:'  # -G git: строка version добавлена или убрана в plugin.json
BOT = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")
ATTEMPTS = 3
USAGE = "release.py [--push] [--remote <имя>] [--branch <ветка>]"


class Refuse(Exception):
    pass


def git(root, *args, check=True):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
    if check and r.returncode != 0:
        raise Refuse(f"git {' '.join(args)} — код {r.returncode}: {(r.stderr or r.stdout).strip()}")
    return r


def manifest(name):
    return f"plugins/{name}/.claude-plugin/plugin.json"


def plugin_names(root):
    top = os.path.join(root, "plugins")
    names = sorted(os.listdir(top)) if os.path.isdir(top) else []
    return [n for n in names if os.path.isfile(os.path.join(root, manifest(n)))]


def tree_hash(root):
    """sha256 дерева плагина — тот же счёт, что _tree_hash в plugins/pantheon/lib/pantheon.py (совпадение сверяет
    .github/scripts/test_release.py): относительные пути и содержимое, ссылки — по тексту ссылки, без .git и
    __pycache__ на любой глубине и без точечных файлов и папок верхнего уровня, кроме .claude-plugin."""
    h = hashlib.sha256()

    def walk(d, rel):
        for e in sorted(os.scandir(d), key=lambda e: e.name):
            if e.name in (".git", "__pycache__") or (not rel and e.name.startswith(".") and e.name != ".claude-plugin"):
                continue
            r = f"{rel}/{e.name}" if rel else e.name
            if e.is_symlink():
                h.update(b"L\0" + r.encode() + b"\0" + os.readlink(e.path).encode() + b"\0")
            elif e.is_dir():
                walk(e.path, r)
            elif e.is_file():
                fh = hashlib.sha256()
                with open(e.path, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        fh.update(chunk)
                h.update(b"F\0" + r.encode() + b"\0" + fh.hexdigest().encode() + b"\0")

    walk(root, "")
    return h.hexdigest()


def bump(v):
    parts = v.split(".") if isinstance(v, str) else []
    if not parts or not all(re.fullmatch(r"[0-9]+", x) for x in parts):
        raise Refuse(f"version «{v}» не разобрать — нужны числа через точку")
    return ".".join(parts[:-1] + [str(int(parts[-1]) + 1)])


def strict_json(text):
    """JSON-объект без повторных ключей; иначе Refuse (json.loads молча берёт последний ключ)."""
    def pairs(items):
        keys = [k for k, _v in items]
        if len(keys) != len(set(keys)):
            raise ValueError("повторный ключ")
        return dict(items)
    try:
        data = json.loads(text, object_pairs_hook=pairs)
    except ValueError as e:
        raise Refuse(f"не JSON-объект: {e}")
    if not isinstance(data, dict):
        raise Refuse("не JSON-объект")
    return data


def last_release(root, name):
    """Коммит прошлого выпуска плагина: последний на первой родительской линии HEAD, где менялась строка version."""
    out = git(root, "log", "--first-parent", "--diff-merges=first-parent", "--no-patch", "-1", "--format=%H", "-G", VERSION_G,
              "--", manifest(name)).stdout.strip()
    if not out:
        raise Refuse(f"у {manifest(name)} в истории нет строки version — выпуск не найти (история неполная?)")
    return out


def read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return fh.read()


def plan(root):
    """[(плагин, старая, новая, текст после)] тронутых плагинов."""
    out = []
    for n in plugin_names(root):
        text = read(root, manifest(n))
        cur = strict_json(text).get("version")
        if not isinstance(cur, str):
            raise Refuse(f"в {manifest(n)} нет строки version")
        rel = last_release(root, n)
        if not git(root, "diff", "--name-only", rel, "HEAD", "--", f"plugins/{n}/").stdout.strip():
            continue
        if len(VERSION_LINE.findall(text)) != 1:
            raise Refuse(f"в {manifest(n)} не одна строка version")
        new = bump(cur)
        out.append((n, cur, new, VERSION_LINE.sub(lambda m: m.group(1) + new + m.group(3), text)))
    return out


def records(root):
    return {"v": RELEASES_V, "plugins": {n: {"version": strict_json(read(root, manifest(n)))["version"],
                                             "tree": tree_hash(os.path.join(root, "plugins", n))}
                                         for n in plugin_names(root)}}


def release_once(root):
    """Поднять номера и записать releases.json одним коммитом → текст итога или None (поднимать нечего)."""
    if git(root, "status", "--porcelain", "--untracked-files=all").stdout.strip():
        raise Refuse("дерево не чистое — выпуск делается только с чистого main")
    todo = plan(root)
    for n, _old, _new, fixed in todo:
        with open(os.path.join(root, manifest(n)), "w", encoding="utf-8") as fh:
            fh.write(fixed)
    rec = records(root)
    path = os.path.join(root, RELEASES)
    old = None
    if os.path.lexists(path):
        if os.path.islink(path) or not os.path.isfile(path):
            raise Refuse(f"{RELEASES} — не обычный файл")
        try:
            old = json.loads(read(root, RELEASES))
        except ValueError:
            old = None  # битый файл — перепишем
    if not todo and old == rec:
        return None
    if old != rec:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    # сверка: только version тронутых plugin.json и releases.json
    allowed = {manifest(n) for n, *_r in todo} | {RELEASES}
    changed = set(git(root, "status", "--porcelain", "--untracked-files=all", "--no-renames").stdout.splitlines())
    paths = {ln[3:] for ln in changed}
    if not paths <= allowed:
        raise Refuse(f"сверка: изменено лишнее — {', '.join(sorted(paths - allowed))}")
    for n, _old, new, _f in todo:
        before = strict_json(git(root, "show", f"HEAD:{manifest(n)}").stdout)
        after = strict_json(read(root, manifest(n)))
        if after.get("version") != new or {k: v for k, v in before.items() if k != "version"} \
                != {k: v for k, v in after.items() if k != "version"}:
            raise Refuse(f"сверка: правка {manifest(n)} задела не только version")
    git(root, "add", "--", *sorted(paths))
    what = ", ".join(f"{n} {new}" for n, _o, new, _f in todo) or f"запись {RELEASES}"
    git(root, "-c", f"user.name={BOT[0]}", "-c", f"user.email={BOT[1]}", "commit", "-q", "--no-verify",
        "-m", f"выпуск: {what}", "-m", "Номер версии поднял workflow release после слияния (metis-0512).")
    return what


def main(argv):
    push, remote, branch = False, "origin", "main"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--push":
            push = True
        elif a in ("--remote", "--branch") and i + 1 < len(argv) and re.fullmatch(r"[A-Za-z0-9_.-]+", argv[i + 1]):
            remote, branch = (argv[i + 1], branch) if a == "--remote" else (remote, argv[i + 1])
            i += 1
        else:
            print(f"release: неверный вызов. {USAGE}", file=sys.stderr)
            return 2
        i += 1
    r = git(os.getcwd(), "rev-parse", "--show-toplevel", check=False)
    if r.returncode != 0:
        print("release: не репозиторий git", file=sys.stderr)
        return 1
    root = r.stdout.strip()
    try:
        for attempt in range(1, ATTEMPTS + 1 if push else 2):
            if push:
                git(root, "fetch", "-q", remote, branch)
                git(root, "checkout", "-q", "-B", branch, "FETCH_HEAD")
            what = release_once(root)
            if what is None:
                print("release: поднимать нечего — выпуск совпадает с деревом")
                return 0
            sha = git(root, "rev-parse", "HEAD").stdout.strip()
            if not push:
                print(f"release: {what} — коммит {sha}")
                return 0
            p = git(root, "push", "-q", remote, f"HEAD:{branch}", check=False)
            if p.returncode == 0:
                print(f"release: {what} — коммит {sha} в {remote}/{branch}")
                return 0
            print(f"release: push попытка {attempt} не прошла ({(p.stderr or p.stdout).strip()[:200]}) — пересчёт "
                  f"на свежем {branch}")
        print(f"release: push в {remote}/{branch} не прошёл за {ATTEMPTS} попытки — номер не поднят", file=sys.stderr)
        return 1
    except Refuse as e:
        print(f"release: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
