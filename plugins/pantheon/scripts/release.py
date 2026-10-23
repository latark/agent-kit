#!/usr/bin/env python3
"""Выпуск плагинов agent-kit (metis-0384): номер версии поднимает выпуск при слиянии, а не каждый PR.

Параллельные PR plugin.json не трогают: иначе после каждого слияния у соседей конфликт в version, новый head и новый
круг ревью. Номер версии поднимает тот, кто сливает, — в ветке PR после ревью, перед `gh pr merge`:

  python3 -I plugins/pantheon/scripts/release.py [--base <ref>] [--dry-run] [плагин…]

1. База (по умолчанию origin/main — сначала git fetch) не в ветке — git merge базы без своих правок. Конфликт только
   в plugin.json (PR старого порядка сам поднял version) решается в пользу базы; другой конфликт — слияние
   отменяется, код 1.
2. Плагины — названные, иначе те, у которых в ветке свои правки относительно базы (git diff база...HEAD, кроме
   самого plugin.json).
3. version каждого = version на базе + 1 в последней части (0.11.84 → 0.11.85). В файле меняется только эта строка.
4. Коммит «<плагин> <версия>[, …]: выпуск». Дальше git push и слияние как обычно: шлюз guard переносит записи tests и
   вердикты argus с проверенного head на новый (merge_gate.carried), потому что разница — только номер версии и
   подтянутая база. Сливает PR ядра владелец (pantheon merge): там записи пока не переносятся — выпуск до
   последнего круга ревью (AGENTS.md, «Выпуск»).

Коды: 0 — готово или поднимать нечего; 1 — отказ (дерево не чистое, базы нет, конфликт, плагин не найден, version
не разобрать); 2 — неверный вызов.
"""
import json
import os
import re
import subprocess
import sys

VERSION_FILE = re.compile(r"plugins/([^/]+)/\.claude-plugin/plugin\.json")
VERSION_LINE = re.compile(r'("version"\s*:\s*")([^"\\]*)(")')
USAGE = "release.py [--base <ref>] [--dry-run] [плагин…]"


def git(root, *args, check=True):
    r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
    if check and r.returncode != 0:
        raise SystemExit(f"release: git {' '.join(args)} — код {r.returncode}: {(r.stderr or r.stdout).strip()}")
    return r


def manifest(name):
    return f"plugins/{name}/.claude-plugin/plugin.json"


def version_at(root, rev, name):
    """version плагина на коммите rev; None — файла там нет."""
    r = git(root, "show", f"{rev}:{manifest(name)}", check=False)
    if r.returncode != 0:
        return None
    v = json.loads(r.stdout).get("version")
    if not isinstance(v, str):
        raise SystemExit(f"release: в {manifest(name)} на {rev} нет строки version")
    return v


def bump(v):
    parts = v.split(".")
    if not parts[-1].isdigit():
        raise SystemExit(f"release: version «{v}» не разобрать — последняя часть не число")
    return ".".join(parts[:-1] + [str(int(parts[-1]) + 1)])


def pull_base(root, base, dry):
    """База не в ветке — слить её; конфликт только в plugin.json — в пользу базы. → True, если было слияние."""
    if git(root, "merge-base", "--is-ancestor", base, "HEAD", check=False).returncode == 0:
        return False
    if dry:
        print(f"release: база {base} не в ветке — будет git merge {base}")
        return True
    r = git(root, "merge", "--no-edit", "--no-ff", base, check=False)
    if r.returncode == 0:
        return True
    conflicted = [p for p in git(root, "diff", "--name-only", "--diff-filter=U").stdout.splitlines() if p]
    if not conflicted or not all(VERSION_FILE.fullmatch(p) for p in conflicted):
        git(root, "merge", "--abort", check=False)
        raise SystemExit(f"release: слияние базы {base} с конфликтом не только в plugin.json "
                         f"({', '.join(conflicted) or r.stderr.strip()}) — слияние отменено; реши конфликт сам, "
                         "это уже правка PR и новый круг ревью")
    git(root, "checkout", "--theirs", "--", *conflicted)
    git(root, "add", "--", *conflicted)
    git(root, "commit", "--no-edit")
    print(f"release: конфликт номера версии в {', '.join(conflicted)} решён в пользу базы")
    return True


def changed_plugins(root, base):
    out = git(root, "diff", "--name-only", f"{base}...HEAD").stdout.splitlines()
    names = []
    for p in out:
        m = re.match(r"plugins/([^/]+)/", p)
        if m and not VERSION_FILE.fullmatch(p) and m.group(1) not in names:
            names.append(m.group(1))
    return names


def main(argv):
    base, dry, names = "origin/main", False, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--base" and i + 1 < len(argv):
            base, i = argv[i + 1], i + 1
        elif a.startswith("--base="):
            base = a[7:]
        elif a == "--dry-run":
            dry = True
        elif a.startswith("-") or not re.fullmatch(r"[a-z0-9_.-]+", a):
            print(f"release: неверный вызов. {USAGE}", file=sys.stderr)
            return 2
        else:
            names.append(a)
        i += 1
    r = git(os.getcwd(), "rev-parse", "--show-toplevel", check=False)
    if r.returncode != 0:
        print("release: не репозиторий git", file=sys.stderr)
        return 1
    root = r.stdout.strip()
    if git(root, "status", "--porcelain").stdout.strip():
        print("release: дерево не чистое — сначала коммит или отмена правок", file=sys.stderr)
        return 1
    if git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", check=False).returncode != 0:
        print(f"release: базы {base} нет — git fetch или --base <ref>", file=sys.stderr)
        return 1
    for n in names:
        if not os.path.isfile(os.path.join(root, manifest(n))):
            print(f"release: нет {manifest(n)}", file=sys.stderr)
            return 1
    merged = pull_base(root, base, dry)
    names = names or changed_plugins(root, base)
    plan = []
    for n in names:
        old = version_at(root, base, n)
        if old is None:
            print(f"release: {n} — нового плагина нет на базе, version остаётся как в ветке")
            continue
        new = bump(old)
        path = os.path.join(root, manifest(n))
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        if json.loads(text).get("version") == new:
            print(f"release: {n} уже {new}")
            continue
        if len(VERSION_LINE.findall(text)) != 1:
            print(f"release: в {manifest(n)} не одна строка version — правь руками", file=sys.stderr)
            return 1
        plan.append((n, path, text, VERSION_LINE.sub(lambda m: m.group(1) + new + m.group(3), text), new))
    if not plan:
        print("release: поднимать нечего" + (" (база подтянута)" if merged and not dry else ""))
        return 0
    if dry:
        for n, _p, _t, _x, new in plan:
            print(f"release: {n} → {new}")
        return 0
    for n, path, text, fixed, new in plan:
        a, b = json.loads(text), json.loads(fixed)
        a.pop("version", None)
        b.pop("version", None)
        if a != b:
            print(f"release: правка {manifest(n)} задела не только version — отмена", file=sys.stderr)
            return 1
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(fixed)
    git(root, "add", "--", *[manifest(n) for n, *_ in plan])
    git(root, "commit", "-q", "-m", ", ".join(f"{n} {new}" for n, *_r, new in plan) + ": выпуск")
    sha = git(root, "rev-parse", "HEAD").stdout.strip()
    print(f"release: {', '.join(f'{n} {new}' for n, *_r, new in plan)} — коммит {sha}")
    print(f"дальше: git push, затем gh pr merge <N> -R <owner/repo> --match-head-commit {sha} --merge")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
