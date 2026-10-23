#!/usr/bin/env python3
"""Тесты scripts/release.py (metis-0384): номер версии плагина поднимает выпуск при слиянии, а не каждый PR.

Запуск: python3 -I plugins/pantheon/tests/test_release.py  (код выхода 0 — все прошли; идёт и на системном 3.9)
Каждый случай — временный репозиторий с origin/main и веткой PR; настоящий репозиторий не трогается.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

_ROOT = tempfile.mkdtemp(prefix="release-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "release.py")
ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
ENV.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e",
           GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
PJ = "plugins/{}/.claude-plugin/plugin.json"
fails = []
count = 0


def g(d, *args, check=True):
    r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, env=ENV)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


def put(d, rel, text):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def manifest(name, ver, extra=""):
    return '{\n  "name": "%s",\n  "version": "%s",%s\n  "description": "d"\n}\n' % (name, ver, extra)


def version(d, name):
    with open(os.path.join(d, PJ.format(name)), encoding="utf-8") as fh:
        return json.load(fh)["version"]


def repo():
    """origin (голый) с main: guard 0.5.17, pantheon 0.11.84; клон на ветке pr от main."""
    base = tempfile.mkdtemp(prefix="rel-")
    seed, origin, work = (os.path.join(base, n) for n in ("seed", "origin.git", "work"))
    subprocess.run(["git", "init", "-q", "-b", "main", seed], check=True, env=ENV)
    put(seed, PJ.format("guard"), manifest("guard", "0.5.17"))
    put(seed, PJ.format("pantheon"), manifest("pantheon", "0.11.84"))
    put(seed, "plugins/guard/hooks/a.py", "a = 1\n")
    put(seed, "plugins/pantheon/lib/b.py", "b = 1\n")
    put(seed, "README.md", "r\n")
    g(seed, "add", "-A")
    g(seed, "commit", "-qm", "init")
    subprocess.run(["git", "clone", "-q", "--bare", seed, origin], check=True, env=ENV)
    subprocess.run(["git", "clone", "-q", origin, work], check=True, env=ENV)
    g(work, "checkout", "-qb", "pr")
    return work


def advance_main(work, rel, text, msg="main"):
    """Новый коммит в origin/main (через отдельную ветку клона) — соседний PR уже слит."""
    head = g(work, "rev-parse", "--abbrev-ref", "HEAD")
    g(work, "checkout", "-q", "-B", "m", "origin/main")
    put(work, rel, text)
    g(work, "add", "-A")
    g(work, "commit", "-qm", msg)
    g(work, "push", "-q", "origin", "m:main")
    g(work, "fetch", "-q", "origin")
    g(work, "checkout", "-q", head)


def commit(work, rel, text, msg="pr"):
    put(work, rel, text)
    g(work, "add", "-A")
    g(work, "commit", "-qm", msg)


def run(work, *args):
    r = subprocess.run([sys.executable, "-I", SCRIPT, *args], cwd=work, capture_output=True, text=True, env=ENV)
    return r.returncode, r.stdout + r.stderr


def check(name, cond, info=""):
    global count
    count += 1
    if not cond:
        fails.append(f"{name}: {info}")


def t_bump_changed_only():
    w = repo()
    commit(w, "plugins/guard/hooks/a.py", "a = 2\n")
    rc, out = run(w)
    check("bump: код 0", rc == 0, out)
    check("bump: guard поднят", version(w, "guard") == "0.5.18", out)
    check("bump: pantheon без правок не тронут", version(w, "pantheon") == "0.11.84", out)
    check("bump: в коммите только plugin.json guard",
          g(w, "diff", "--name-only", "HEAD~1", "HEAD") == PJ.format("guard"), out)
    check("bump: сообщение", g(w, "log", "-1", "--format=%s") == "guard 0.5.18: выпуск", out)
    check("bump: SHA в выводе", g(w, "rev-parse", "HEAD") in out, out)
    diff = g(w, "diff", "-U0", "HEAD~1", "HEAD")
    check("bump: изменена одна строка", diff.count("\n+  ") == 1 and diff.count("\n-  ") == 1, diff)
    rc, out = run(w)
    check("bump: повтор — поднимать нечего, без коммита", rc == 0 and "уже 0.5.18" in out
          and g(w, "log", "-1", "--format=%s") == "guard 0.5.18: выпуск", out)


def t_pull_base():
    """main ушёл вперёд (соседний выпуск guard 0.5.18) — база подтягивается, версия от базы."""
    w = repo()
    commit(w, "plugins/guard/hooks/a.py", "a = 2\n")
    advance_main(w, PJ.format("guard"), manifest("guard", "0.5.18"))
    advance_main(w, "README.md", "r2\n")
    rc, out = run(w)
    check("pull: код 0", rc == 0, out)
    check("pull: main в ветке", subprocess.run(["git", "-C", w, "merge-base", "--is-ancestor", "origin/main", "HEAD"],
                                              env=ENV).returncode == 0, out)
    check("pull: версия = база + 1", version(w, "guard") == "0.5.19", out)
    check("pull: от базы к head — только plugin.json guard",
          g(w, "diff", "--name-only", "origin/main", "HEAD") == "\n".join(sorted([PJ.format("guard"),
                                                                                "plugins/guard/hooks/a.py"])), out)


def t_old_style_conflict():
    """PR старого порядка сам поднял version, main тоже — конфликт только в plugin.json решается в пользу базы."""
    w = repo()
    commit(w, "plugins/guard/hooks/a.py", "a = 2\n")
    commit(w, PJ.format("guard"), manifest("guard", "0.5.18"))
    advance_main(w, PJ.format("guard"), manifest("guard", "0.5.20"))
    rc, out = run(w)
    check("old: код 0", rc == 0, out)
    check("old: конфликт решён в пользу базы", "в пользу базы" in out, out)
    check("old: версия 0.5.21", version(w, "guard") == "0.5.21", out)
    check("old: дерево чистое", g(w, "status", "--porcelain") == "", out)


def t_real_conflict():
    w = repo()
    commit(w, "plugins/guard/hooks/a.py", "a = 2\n")
    advance_main(w, "plugins/guard/hooks/a.py", "a = 3\n")
    before = g(w, "rev-parse", "HEAD")
    rc, out = run(w)
    check("conflict: код 1", rc == 1, out)
    check("conflict: причина в последней строке", "plugins/guard/hooks/a.py" in out.strip().splitlines()[-1], out)
    check("conflict: слияние отменено", g(w, "rev-parse", "HEAD") == before and g(w, "status", "--porcelain") == ""
          and not os.path.exists(os.path.join(w, ".git", "MERGE_HEAD")), out)


def t_refusals():
    w = repo()
    commit(w, "plugins/guard/hooks/a.py", "a = 2\n")
    put(w, "plugins/guard/hooks/a.py", "a = 5\n")
    rc, out = run(w)
    check("dirty: код 1", rc == 1 and "не чистое" in out, out)
    g(w, "checkout", "--", ".")
    rc, out = run(w, "--base", "origin/nope")
    check("nobase: код 1", rc == 1 and "базы origin/nope нет" in out, out)
    rc, out = run(w, "nosuch")
    check("noplugin: код 1", rc == 1 and "нет plugins/nosuch" in out, out)
    rc, out = run(w, "--bogus")
    check("usage: код 2", rc == 2, out)
    rc, out = run(w, "--dry-run")
    check("dry: план без коммита", rc == 0 and "guard → 0.5.18" in out
          and g(w, "log", "-1", "--format=%s") == "pr" and version(w, "guard") == "0.5.17", out)
    rc, out = run(w, "pantheon")
    check("named: поднят названный", rc == 0 and version(w, "pantheon") == "0.11.85"
          and version(w, "guard") == "0.5.17", out)


def t_only_version_and_new_plugin():
    w = repo()
    put(w, PJ.format("newp"), manifest("newp", "0.1.0"))
    put(w, "plugins/newp/x.py", "x\n")
    put(w, PJ.format("guard"), manifest("guard", "0.5.17", '\n  "keywords": ["k"],'))
    commit(w, "plugins/guard/hooks/a.py", "a = 2\n")
    rc, out = run(w)
    check("newp: код 0", rc == 0, out)
    check("newp: новый плагин не тронут", version(w, "newp") == "0.1.0" and "нового плагина нет на базе" in out, out)
    with open(os.path.join(w, PJ.format("guard")), encoding="utf-8") as fh:
        data = json.load(fh)
    check("newp: прочие поля целы", data.get("keywords") == ["k"] and data["version"] == "0.5.18", out)


def t_version_only_not_plugin_change():
    """Правка только plugin.json (номер версии старого порядка) — не правка плагина: его не поднимаем."""
    w = repo()
    commit(w, PJ.format("pantheon"), manifest("pantheon", "0.11.90"))
    commit(w, "plugins/guard/hooks/a.py", "a = 2\n")
    rc, out = run(w)
    check("veronly: код 0", rc == 0, out)
    check("veronly: pantheon не тронут", version(w, "pantheon") == "0.11.90" and version(w, "guard") == "0.5.18", out)


CASES = [t_version_only_not_plugin_change, t_bump_changed_only, t_pull_base, t_old_style_conflict, t_real_conflict, t_refusals,
         t_only_version_and_new_plugin]

if __name__ == "__main__":
    for case in CASES:
        try:
            case()
        except Exception as e:  # noqa: BLE001 — случай падает целиком, остальные идут
            count += 1
            fails.append(f"{case.__name__}: исключение {e!r}")
    for f in fails:
        print("ПРОВАЛ", f)
    print(f"{count - len(fails)} из {count} прошли")
    sys.exit(1 if fails else 0)
