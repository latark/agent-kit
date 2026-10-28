#!/usr/bin/env python3
"""pantheon traces — проверка личных следов до push (metis-0414): временные репозитории, выдуманные маркеры.

Запуск: python3 -I plugins/pantheon/tests/test_traces.py  (код выхода 0 — все прошли)
Хук проверяется настоящим git push в bare-репозиторий; команда pantheon в PATH — заглушка на lib/pantheon.py.
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="traces-local-"))
atexit.register(shutil.rmtree, ROOT, True)
PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(PLUGIN, "lib", "pantheon.py")
MARK = "zzmarker-alpha"
results = []


def check(ok, detail=""):
    """check(условие, пояснение): номер проверки берётся из порядка вызовов, пояснение — при падении."""
    name = f"№{len(results) + 1}"
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


def mk(name):
    d = os.path.join(ROOT, name)
    os.makedirs(d)
    return d


def git(*a, cwd):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True,
                          text=True)


def repo(name, files):
    r = mk(name)
    git("init", "-q", "-b", "main", cwd=r)
    for rel, text in files.items():
        p = os.path.join(r, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
    git("add", "-A", cwd=r)
    git("commit", "-q", "-m", "x", cwd=r)
    return r


HOME = mk("home")
markers = os.path.join(mk("m"), "markers.txt")
with open(markers, "w", encoding="utf-8") as fh:
    fh.write(f"# комментарий\n{MARK}\n")
BASE_ENV = {k: v for k, v in os.environ.items() if k != "PANTHEON_TRACE_MARKERS"}
BASE_ENV.update(HOME=HOME, PANTHEON_HOME=os.path.join(HOME, "ai", "pantheon"), PANTHEON_STATE=os.path.join(HOME, "st"))


def pan(*a, cwd, env=None):
    return subprocess.run([PY311, "-I", CLI, "traces", *a], cwd=cwd, capture_output=True, text=True,
                          env=env or BASE_ENV, timeout=120)


dirty = repo("dirty", {"a.txt": "чисто\n", "sub/b.txt": f"раз\nтут {MARK} и ещё\n"})
clean = repo("clean", {"a.txt": "чисто\n"})

# 1. найдено: код 1, «путь:строка», маркер не печатается
p = pan("--markers", markers, cwd=dirty)
check(p.returncode == 1 and p.stdout.strip() == "sub/b.txt:2", (p.returncode, p.stdout, p.stderr))
check(MARK not in p.stdout + p.stderr, "маркер просочился в вывод")

# 2. чисто: код 0
p = pan("--markers", markers, cwd=clean)
check(p.returncode == 0 and "следов нет" in p.stdout, (p.returncode, p.stdout, p.stderr))

# 3. из подпапки — проверяется весь репозиторий
p = pan("--markers", markers, cwd=os.path.join(dirty, "sub"))
check(p.returncode == 1 and "sub/b.txt:2" in p.stdout, (p.returncode, p.stdout))

# 4. нет файла маркеров: громкий отказ, не «зелёный»
p = pan(cwd=dirty)
check(p.returncode == 2 and "файла маркеров нет (" in p.stderr and "следов нет" not in p.stdout,
      (p.returncode, p.stdout, p.stderr))
p = pan("--markers", os.path.join(ROOT, "нет.txt"), cwd=clean)
check(p.returncode == 2 and "файла маркеров нет (" in p.stderr, (p.returncode, p.stderr))

# 5. пустой файл маркеров (только комментарии) — тоже отказ, а не «следов нет»
empty = os.path.join(ROOT, "m", "empty.txt")
with open(empty, "w", encoding="utf-8") as fh:
    fh.write("# пусто\n\n")
p = pan("--markers", empty, cwd=clean)
check(p.returncode == 2 and "следов нет" not in p.stdout and "не отработала" in p.stderr,
      (p.returncode, p.stdout, p.stderr))

# 6. источники маркеров: PANTHEON_TRACE_MARKERS, файл по умолчанию в HOME; --markers главнее
p = pan(cwd=dirty, env=dict(BASE_ENV, PANTHEON_TRACE_MARKERS=markers))
check(p.returncode == 1, ("env", p.returncode, p.stderr))
os.makedirs(os.path.join(HOME, ".config", "pantheon"))
shutil.copy(markers, os.path.join(HOME, ".config", "pantheon", "trace-markers.txt"))
p = pan(cwd=dirty)
check(p.returncode == 1 and p.stdout.strip() == "sub/b.txt:2", ("по умолчанию", p.returncode, p.stderr))
p = pan("--markers", empty, cwd=dirty, env=dict(BASE_ENV, PANTHEON_TRACE_MARKERS=markers))
check(p.returncode == 2, ("--markers главнее env", p.returncode))
os.remove(os.path.join(HOME, ".config", "pantheon", "trace-markers.txt"))

# 7. не git: отказ; плохой аргумент: 2
nogit = mk("nogit")
NOGIT_ENV = dict(BASE_ENV, GIT_CEILING_DIRECTORIES=ROOT)
p = pan("--markers", markers, cwd=nogit, env=NOGIT_ENV)
check(p.returncode == 2 and "не git" in p.stderr, (p.returncode, p.stderr))
p = pan("--что-то", cwd=clean)
check(p.returncode == 2, p.returncode)

# 8. хук: настоящий push. Заглушка pantheon в PATH
shim = mk("shim")
with open(os.path.join(shim, "pantheon"), "w", encoding="utf-8") as fh:
    fh.write(f'#!/bin/sh\nexec "{PY311}" -I "{CLI}" "$@"\n')
os.chmod(os.path.join(shim, "pantheon"), 0o755)
penv = dict(BASE_ENV, PATH=f"{shim}:/usr/bin:/bin", PANTHEON_TRACE_MARKERS=markers)
bare = mk("bare.git")
git("init", "-q", "--bare", "-b", "main", cwd=bare)
w = repo("work", {"a.txt": "чисто\n"})
git("remote", "add", "origin", bare, cwd=w)
p = pan("install-hook", cwd=w)
hook = os.path.join(w, ".git", "hooks", "pre-push")
check(p.returncode == 0 and os.access(hook, os.X_OK), (p.returncode, p.stderr))
p = pan("install-hook", cwd=w)
check(p.returncode == 0, ("повторная установка", p.returncode, p.stderr))


def push(env):
    return subprocess.run(["git", "push", "-q", "origin", "main"], cwd=w, capture_output=True, text=True, env=env)


r = push(penv)
check(r.returncode == 0, ("чистый push", r.returncode, r.stderr))
with open(os.path.join(w, "c.txt"), "w", encoding="utf-8") as fh:
    fh.write(f"{MARK}\n")
git("add", "-A", cwd=w)
git("commit", "-q", "-m", "след", cwd=w)
r = push(penv)
remote_head = git("rev-parse", "main", cwd=bare).stdout.strip()
check(r.returncode != 0 and "c.txt:1" in r.stderr + r.stdout and remote_head != git("rev-parse", "main", cwd=w).stdout.strip(),
      ("push со следом должен остановиться", r.returncode, r.stderr))
check(MARK not in r.stderr + r.stdout, "маркер в выводе хука")
# нет файла маркеров — push тоже остановлен
r = push(dict(penv, PANTHEON_TRACE_MARKERS=os.path.join(ROOT, "нет.txt")))
check(r.returncode != 0 and "файла маркеров нет (" in r.stderr, ("push без маркеров", r.returncode, r.stderr))
# нет pantheon в PATH — остановлен
r = push(dict(penv, PATH="/usr/bin:/bin"))
check(r.returncode != 0 and "pantheon" in r.stderr, ("push без pantheon", r.returncode, r.stderr))

# 9. чужой хук не затирается
w2 = repo("work2", {"a.txt": "x\n"})
os.makedirs(os.path.join(w2, ".git", "hooks"), exist_ok=True)
foreign = os.path.join(w2, ".git", "hooks", "pre-push")
with open(foreign, "w", encoding="utf-8") as fh:
    fh.write("#!/bin/sh\necho чужой\n")
p = pan("install-hook", cwd=w2)
with open(foreign, encoding="utf-8") as fh:
    left = fh.read()
check(p.returncode == 2 and "чужой" in left and "уже есть" in p.stderr, (p.returncode, p.stderr, left))
p = pan("install-hook", cwd=nogit, env=NOGIT_ENV)
check(p.returncode == 2, ("хук вне git", p.returncode))

print(f"{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
