#!/usr/bin/env python3
"""affected-map.py <папка плагина> … — строит карту «файл → тесты» для run-tests.py --affected (metis-0451).

  heavy python3 -I plugins/pantheon/scripts/affected-map.py plugins/guard plugins/pantheon plugins/project-tools
  -j N        воркеров (по умолчанию как у run-tests.py)
  --out ФАЙЛ  куда записать карту (по умолчанию scripts/affected-map.json рядом с раннером)

Карта — по прогону, а не по догадкам из имён и импортов: модули lib/ грузятся лениво, и какой тест что задевает, по
тексту не видно. Каждый tests/test_*.py идёт в своей копии репозитория (файлы `git ls-files` и новые вне .gitignore,
одним коммитом в новом git: установщик требует клон). В копии у каждого файла Python и скрипта sh — метка:
  - Python — `exec(…)` в конце строки docstring (или перед первой простой инструкцией), номера строк не сдвигаются:
    пишет путь файла от корня репозитория и ставит audit hook, который пишет пути из копии: открытые процессом
    (`open`, импорт тоже), запущенные им программы и их аргументы (`subprocess.Popen`, `os.exec`, `os.posix_spawn`,
    `os.spawn`) и источники копирования (`shutil.copyfile`, `shutil.copytree`);
  - sh — строка перед первой командой (после #! и шапки комментариев): `printf <путь> >> метки`.
Путь вшит в метку, поэтому копия плагина, которую тест сделал сам (кэш плагина, установка), отчитывается тем же путём.
Папка среди путей (copytree, `cp -R папка`, `git -C папка`) — все файлы под ней: тест, что копирует плагин целиком,
зависит от всего плагина.

Карта: hashes — sha256 этих файлов (run-tests по ним находит файлы, изменённые после сборки); tests — файлы тестов, по которым она строилась; broken — файлы, которые в копии упали (их пути могут быть
неполными, run-tests берёт их всегда); files — путь → номера файлов тестов в tests. Файл, который не задел ни один
тест, — с пустым списком. Код выхода не 0: нет файлов тестов, не git, таймаут или упал больше половины файлов.
Карта устаревает, когда тесты начинают задевать новые файлы: run-tests о ней не знает, поэтому после большой правки
тестов или переноса кода между файлами (разбиение pantheon.py на lib/, metis-0599) карту строят заново (около 10 мин при трёх воркерах), а полный прогон на main ловит то, что карта пропустила.
Только stdlib.
"""
import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "affected-map.json")
VERSION = 2

_spec = importlib.util.spec_from_file_location("run_tests", os.path.join(HERE, "run-tests.py"))
RT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RT)

HOOK = r'''
import os, sys
_LOG = %(log)r
_ROOTS = %(roots)r


def _rt_rec(s):
    try:
        fd = os.open(_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (s + "\n").encode("utf-8", "replace"))
        finally:
            os.close(fd)
    except Exception:
        pass


for _r in _REL:
    _rt_rec("m " + _r)
if not getattr(sys, "_rt_hooked", False):
    sys._rt_hooked = True
    _busy, _seen = [False], set()

    def _rt_rel(p):
        if isinstance(p, int):
            return None
        try:
            p = os.fsdecode(p)
        except Exception:
            return None
        if not os.path.isabs(p):
            try:
                p = os.path.join(os.getcwd(), p)
            except Exception:
                return None
        p = os.path.normpath(p)
        for r in _ROOTS:
            if p.startswith(r):
                return p[len(r):]
        return None

    def _rt_hook(ev, args):
        if _busy[0]:
            return
        if ev == "open":
            cands = args[:1]
        elif ev in ("subprocess.Popen", "os.exec", "os.posix_spawn"):
            a = args[1] if len(args) > 1 else ()
            cands = [args[0], *(a if isinstance(a, (list, tuple)) else [a])]
        elif ev == "os.spawn":
            a = args[2] if len(args) > 2 else ()
            cands = [args[1], *(a if isinstance(a, (list, tuple)) else [a])]
        elif ev in ("shutil.copyfile", "shutil.copytree"):
            cands = args[:1]
        else:
            return
        _busy[0] = True
        try:
            for c in cands:
                r = _rt_rel(c)
                if r and not r.startswith(".rt/") and r not in _seen:
                    _seen.add(r)
                    _rt_rec("o " + r)
        except Exception:
            pass
        finally:
            _busy[0] = False

    sys.addaudithook(_rt_hook)
'''


def tracked(root):
    """Пути от корня: файлы git ls-files, что есть в рабочем дереве, и новые вне .gitignore."""
    out = subprocess.run(["git", "-c", "core.quotePath=false", "ls-files", "-z", "--cached", "--others",
                          "--exclude-standard"], cwd=root, stdout=subprocess.PIPE, check=True).stdout
    return sorted({p for p in out.decode("utf-8", "replace").split("\0")
                   if p and os.path.isfile(os.path.join(root, p))})


def kind(path):
    """'py', 'sh' или None — как метить файл."""
    if path.endswith(".py"):
        return "py"
    try:
        with open(path, "rb") as fh:
            first = fh.readline(200)
    except OSError:
        return None
    if first.startswith(b"#!"):
        if b"python" in first:
            return "py"
        if re.search(rb"\b(?:sh|bash|zsh)\b", first):
            return "sh"
    return "sh" if path.endswith(".sh") else None


def mark_py(src, stmt):
    """Текст с меткой stmt без сдвига строк, или None, если файл не разобрать."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return None
    lines = src.splitlines(keepends=True)
    body = tree.body
    i = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        i = 1
    while i < len(body) and isinstance(body[i], ast.ImportFrom) and body[i].module == "__future__":
        i += 1
    if i:  # после docstring и __future__: в конец строки, где кончается последний из них
        node = body[i - 1]
        ln = node.end_lineno - 1
        line = lines[ln]
        rest = line[len(line.encode("utf-8")[:node.end_col_offset].decode("utf-8", "replace")):]
        if rest.strip() and not rest.strip().startswith("#"):
            return None
        nl = "\n" if line.endswith("\n") else ""
        lines[ln] = line[:len(line) - len(rest)] + "; " + stmt + (rest.rstrip("\n") and "  " + rest.strip()) + nl
        return "".join(lines)
    if not body:
        return src + ("\n" if src and not src.endswith("\n") else "") + stmt + "\n"
    first = body[0]
    if first.col_offset == 0 and isinstance(first, (ast.Import, ast.ImportFrom, ast.Assign, ast.Expr, ast.AnnAssign)):
        ln = first.lineno - 1
        lines[ln] = stmt + "; " + lines[ln]
        return "".join(lines)
    ln = first.lineno - 1
    lines.insert(ln, stmt + "\n")
    return "".join(lines)


def mark_sh(src, stmt):
    """Метка перед первой командой: #! и шапка комментариев остаются первыми (их читают тесты и is_python)."""
    lines = src.splitlines(keepends=True)
    at = 0
    while at < len(lines) and (lines[at].startswith("#") or not lines[at].strip()):
        at += 1
    if at == len(lines) and lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.insert(at, stmt + "\n")
    return "".join(lines)


def make_copy(repo, files, dest, hook_path, log):
    """Копия файлов files из repo в dest с метками. Файлы с одинаковым текстом (python.sh guard и pantheon) получают
    одну метку со всеми их путями: тест, что сверяет копии, остаётся зелёным."""
    same = {}
    for rel in files:
        try:
            with open(os.path.join(repo, rel), "rb") as fh:
                same.setdefault(fh.read(), []).append(rel)
        except OSError:
            pass
    twins = {rel: tuple(group) for group in same.values() for rel in group}
    for rel in files:
        src, dst = os.path.join(repo, rel), os.path.join(dest, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        k = kind(src)
        if k is None:
            continue
        try:
            with open(src, encoding="utf-8") as fh:
                text = fh.read()
        except (UnicodeDecodeError, OSError):
            continue
        if k == "py":
            stmt = ("exec(\"try:\\n exec(compile(open(%r,'rb').read(),'rt-hook','exec'),{'_REL':%r})\\n"
                    "except BaseException:\\n pass\")" % (hook_path, twins.get(rel, (rel,))))
            new = mark_py(text, stmt)
        else:
            recs = " ".join("'m %s'" % r for r in twins.get(rel, (rel,)))
            new = mark_sh(text, "{ printf '%%s\\n' %s >> '%s'; } 2>/dev/null || :" % (recs, log))
        if new is not None:
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(new)
            shutil.copystat(src, dst)


GENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "affected-map",
        "GIT_AUTHOR_EMAIL": "affected-map@localhost", "GIT_COMMITTER_NAME": "affected-map",
        "GIT_COMMITTER_EMAIL": "affected-map@localhost"}


def git_init(dest):
    """Копия — клон с одним коммитом: установщик и часть тестов требуют git-репозиторий."""
    env = {**os.environ, **GENV}
    for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "--no-verify", "-m", "копия")):
        subprocess.run(["git", *args], cwd=dest, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)


def expand(got, files):
    """Пути из меток → файлы репозитория: путь файла — он сам, путь папки — все файлы под ней."""
    fset = set(files)
    out = set()
    for p in got:
        p = p.rstrip("/")
        if p in fset:
            out.add(p)
        elif p and p != ".":
            pre = p + "/"
            out.update(f for f in files if f.startswith(pre))
    return out


def parse(argv):
    opts = {"jobs": None, "out": OUT, "dirs": []}
    it = iter(argv)
    for a in it:
        if a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif a in ("-j", "--jobs", "--out"):
            v = next(it, None)
            if v is None:
                sys.exit(f"affected-map: {a} без значения")
            if a == "--out":
                opts["out"] = v
            else:
                try:
                    opts["jobs"] = int(v)
                except ValueError:
                    sys.exit(f"affected-map: {a} {v} — не число")
                if opts["jobs"] <= 0:
                    sys.exit(f"affected-map: {a} {v} — нужно больше нуля")
        elif a.startswith("-"):
            sys.exit(f"affected-map: неизвестный ключ {a}")
        else:
            opts["dirs"].append(a)
    return opts


def main(argv):
    opts = parse(argv)
    if not opts["dirs"]:
        print(__doc__)
        return 2
    for d in opts["dirs"]:
        if not os.path.isdir(d):
            print(f"affected-map: нет папки {d}")
            return 2
    try:
        repo = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=opts["dirs"][0], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=True, text=True).stdout.strip()
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=True, text=True).stdout.strip()
        files = tracked(repo)
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"affected-map: не репозиторий git — {e}")
        return 2
    items = RT.collect(opts["dirs"])
    if not items:
        print("affected-map: ни одного файла tests/test_*.py — карту не из чего строить")
        return 1
    plugin_rel = {}
    for pdir, label in items:
        plugin_rel[label.split("/", 1)[0]] = os.path.relpath(os.path.realpath(pdir), os.path.realpath(repo))
    par, ser = RT.order(items)
    queue = par + ser
    n = opts["jobs"] or RT.workers(os.cpu_count(), RT.load1())
    print(f"affected-map: {len(queue)} файлов тестов, {len(files)} файлов репозитория, воркеров {n}", flush=True)
    env0 = {k: v for k, v in os.environ.items()
            if not k.startswith("PANTHEON_") and k not in ("FORCE_COLOR", "CLICOLOR_FORCE")}
    env0.update({"NO_COLOR": "1", "PYTHON_COLORS": "0"})
    root = tempfile.mkdtemp(prefix="affected-map-")
    hits, broken, t0, seq, running = {}, [], time.monotonic(), 0, []
    try:
        while queue or running:
            while queue and len(running) < n:
                pdir, label = queue.pop(0)
                seq += 1
                box = os.path.join(root, f"c{seq:03d}")
                copy, rt = os.path.join(box, "repo"), os.path.join(box, "rt")
                os.makedirs(rt)
                log = os.path.join(rt, "hits")
                hook = os.path.join(rt, "hook.py")
                roots = tuple(sorted({copy + os.sep, os.path.realpath(copy) + os.sep}))
                with open(hook, "w", encoding="utf-8") as fh:
                    fh.write(HOOK % {"log": log, "roots": roots})
                make_copy(repo, files, copy, hook, log)
                git_init(copy)
                cpdir = os.path.join(copy, plugin_rel[label.split("/", 1)[0]])
                job = RT.Job(cpdir, label, sys.executable, root, env0, RT.SLOW.get(label) or RT.TIMEOUT, seq)
                job.box, job.log = box, log
                running.append(job)
            for job in list(running):
                if job.exited():
                    pass
                elif time.monotonic() - job.t0 > job.timeout * 2:  # с метками медленнее
                    job.timed_out = True
                    job.kill()
                else:
                    continue
                running.remove(job)
                job.finish()
                got = set()
                try:
                    with open(job.log, encoding="utf-8", errors="replace") as fh:
                        for ln in fh:
                            ln = ln.rstrip("\n")
                            if ln[:2] in ("m ", "o "):
                                got.add(ln[2:])
                except OSError:
                    pass
                shutil.rmtree(job.box, ignore_errors=True)
                hits[job.label] = expand(got, files)
                if not job.ok:
                    broken.append(job.label)
                mark = "ok  " if job.ok else "FAIL"
                why = "" if job.ok else f" · {job.why}"
                print(f"{mark} {job.label} · {job.sec:.1f} с · файлов задето {len(hits[job.label])}{why}", flush=True)
                if not job.ok:
                    tail = [ln for ln in job.out.rstrip("\n").splitlines() if not ln.startswith("ok ")][-RT.TAIL // 4:]
                    print("\n".join("     | " + ln for ln in tail), flush=True)
            time.sleep(0.05)
    finally:
        for job in running:
            job.kill()
            job.fh.close()
        shutil.rmtree(root, ignore_errors=True)
    labels = sorted(hits)
    idx = {lb: i for i, lb in enumerate(labels)}
    fmap = {}
    for rel in files:
        users = {lb for lb in labels if rel in hits[lb]}
        fmap[rel] = sorted(idx[lb] for lb in users)
    hashes = {label: RT.test_hash(pdir, label) for pdir, label in items}
    data = {"version": VERSION, "head": head, "python": "%d.%d" % sys.version_info[:2], "tests": labels,
            "broken": sorted(broken), "files": fmap}
    body = ["{", f'  "version": {VERSION},', f'  "head": {json.dumps(head)},',
            f'  "python": {json.dumps(data["python"])},',
            '  "hashes": {', ",\n".join(f"    {json.dumps(lb, ensure_ascii=False)}: {json.dumps(hashes[lb])}" for lb in labels),
            "  },",
            '  "tests": [', ",\n".join(f"    {json.dumps(lb, ensure_ascii=False)}" for lb in labels), "  ],",
            f'  "broken": {json.dumps(data["broken"], ensure_ascii=False)},', '  "files": {',
            ",\n".join(f"    {json.dumps(rel, ensure_ascii=False)}: {json.dumps(v)}" for rel, v in fmap.items()),
            "  }", "}"]
    tmp = opts["out"] + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(body) + "\n")
    os.replace(tmp, opts["out"])
    untouched = sum(1 for v in fmap.values() if not v)
    print(f"affected-map: записано {opts['out']} — тестов {len(labels)}, упало в копии {len(broken)}"
          f"{' (' + ', '.join(broken) + ')' if broken else ''}, файлов {len(fmap)}, ни одним не задето {untouched}; "
          f"{time.monotonic() - t0:.0f} с", flush=True)
    if len(broken) * 2 > len(labels) or len(labels) != len(items):
        print("affected-map: упало больше половины файлов или не все дошли — карта ненадёжна, код 1")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
