#!/usr/bin/env python3
"""Выпуск плагинов agent-kit (metis-0384): номер версии поднимает выпуск при слиянии, а не каждый PR.

Параллельные PR plugin.json не трогают: иначе после каждого слияния у соседей конфликт в version, новый head и новый
круг ревью. Номер версии поднимает тот, кто сливает, — в ветке PR после ревью, перед `gh pr merge`:

  python3 -I plugins/pantheon/scripts/release.py [--base <ref>] [--dry-run] [плагин…]

1. База (по умолчанию origin/main — сначала git fetch) не в ветке — git merge базы без своих правок. Конфликт только
   в plugin.json (PR старого порядка сам поднял version) решается по полям: version = max(база, PR) + 1, остальные
   поля сливаются трёхсторонне — правка PR в description, hooks и других полях сохраняется. Поле, изменённое с обеих
   сторон по-разному, или конфликт в другом файле — слияние отменяется, код 1 и имя файла.
2. Плагины — названные, иначе те, у которых в ветке свои правки относительно базы (git diff база...HEAD; plugin.json
   считается правкой, если в нём изменено что-то кроме version).
3. version каждого = version на базе + 1 в последней части (0.11.84 → 0.11.85); уже больше базы (после конфликта
   или поднят руками) — остаётся. В файле меняется только эта строка.
4. Коммит «<плагин> <версия>[, …]: выпуск». Дальше git push и слияние как обычно: шлюз guard переносит записи tests и
   вердикты argus с проверенного head на новый (merge_gate.carried), потому что разница — только номер версии и
   подтянутая база, а version на новом head больше, чем на базе PR. Соседний PR слит раньше с тем же номером —
   шлюз откажет, повтори release.py. Сливает PR ядра владелец (pantheon merge): там записи пока не переносятся
   (пересмотр — metis-0396) — выпуск до последнего круга ревью (AGENTS.md, «Выпуск»).

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
ABSENT = object()


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
    if not re.fullmatch(r"[0-9]+", parts[-1]):
        raise SystemExit(f"release: version «{v}» не разобрать — последняя часть не число")
    return ".".join(parts[:-1] + [str(int(parts[-1]) + 1)])


def vkey(v):
    """version → кортеж чисел для сравнения; None — не разобрать (не «числа через точку»)."""
    parts = v.split(".") if isinstance(v, str) else []
    return tuple(int(x) for x in parts) if parts and all(re.fullmatch(r"[0-9]+", x) for x in parts) else None


def merge_fields(base, ours, theirs):
    """Трёхстороннее слияние plugin.json по полям, без version (как merge_gate._merge3); None — поле изменено с обеих
    сторон по-разному (или удалено с одной и изменено с другой)."""
    out = {}
    for k in list(ours) + [k for k in theirs if k not in ours] + [k for k in base if k not in ours and k not in theirs]:
        if k == "version":
            continue
        b, o, t = base.get(k, ABSENT), ours.get(k, ABSENT), theirs.get(k, ABSENT)
        v = t if o == b else o if t == b or o == t else None
        if v is None:
            return None
        if v is not ABSENT:
            out[k] = v
    return out


def stage(root, n, path):
    """(текст, словарь) стадии n конфликта: 1 — общий предок, 2 — ветка, 3 — база; None — стадии нет или не JSON."""
    r = git(root, "show", f":{n}:{path}", check=False)
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return None
    return (r.stdout, data) if isinstance(data, dict) else None


def resolve_manifest(root, path):
    """Конфликт в plugin.json: поля — трёхстороннее слияние, version = max(база, ветка) + 1. Файл записан → (version,
    None); не сливается → (None, причина)."""
    st = [stage(root, n, path) for n in (1, 2, 3)]
    if None in st:
        return None, "не у всех сторон есть plugin.json как JSON-объект (удалён или не JSON)"
    (_tb, b), (to, o), (tt, t) = st
    merged = merge_fields(b, o, t)
    if merged is None:
        return None, "поле кроме version изменено и в ветке, и в базе, по-разному"
    vo, vt = o.get("version"), t.get("version")
    if vkey(vo) is None or vkey(vt) is None:
        return None, f"version не разобрать (ветка {vo!r}, база {vt!r})"
    new = bump(max(vo, vt, key=vkey))

    def rest(d):
        return {k: v for k, v in d.items() if k != "version"}
    # текст — той стороны, чьи поля совпали со слиянием: форма файла сохраняется; иначе файл заново
    text = tt if rest(t) == merged else to if rest(o) == merged else None
    if text is not None and len(VERSION_LINE.findall(text)) == 1:
        text = VERSION_LINE.sub(lambda m: m.group(1) + new + m.group(3), text)
    else:
        data = {}
        for k in list(o) + [k for k in merged if k not in o]:
            if k == "version" or k in merged:
                data[k] = new if k == "version" else merged[k]
        data.setdefault("version", new)
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    got = json.loads(text)
    if rest(got) != merged or got.get("version") != new:
        return None, "слияние полей не сошлось при записи"
    with open(os.path.join(root, path), "w", encoding="utf-8") as fh:
        fh.write(text)
    return new, None


def pull_base(root, base, dry):
    """База не в ветке — слить её; конфликт только в plugin.json — по полям (resolve_manifest). → True, если было
    слияние."""
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
    done = []
    for p in conflicted:
        new, why = resolve_manifest(root, p)
        if why:
            git(root, "merge", "--abort", check=False)
            raise SystemExit(f"release: конфликт в {p} не слить по полям: {why} — слияние базы {base} отменено; "
                             "реши сам, это уже правка PR и новый круг ревью")
        done.append(f"{p} (version {new})")
    git(root, "add", "--", *conflicted)
    git(root, "commit", "--no-edit")
    print(f"release: конфликт в {', '.join(done)} решён по полям — правки ветки и базы сохранены")
    return True


def manifest_rest(root, rev, path):
    """plugin.json на rev без version; None — файла нет или не JSON-объект."""
    r = git(root, "show", f"{rev}:{path}", check=False)
    try:
        data = json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        return None
    return {k: v for k, v in data.items() if k != "version"} if isinstance(data, dict) else None


def changed_plugins(root, base):
    """Плагины со своими правками в ветке: любой файл плагина; plugin.json — если изменено не только version."""
    mb = git(root, "merge-base", base, "HEAD").stdout.strip()
    names = []
    for p in git(root, "diff", "--name-only", f"{mb}..HEAD").stdout.splitlines():
        m = re.match(r"plugins/([^/]+)/", p)
        if not m or m.group(1) in names:
            continue
        if VERSION_FILE.fullmatch(p) and manifest_rest(root, mb, p) == manifest_rest(root, "HEAD", p):
            continue
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
        cur = json.loads(text).get("version")
        if vkey(cur) is not None and vkey(old) is not None and vkey(cur) > vkey(old):
            print(f"release: {n} уже {cur} (на базе {old})")
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
