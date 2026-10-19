#!/usr/bin/env python3
"""Живой код и окружение запусков claude (metis-0321).

1. `pantheon install` вешает ~/.local/share/pantheon/current на УСТАНОВЛЕННУЮ версию — installPath из
   installed_plugins.json внутри ~/.claude/plugins/cache, — а не на клон маркетплейса (его plugins-update пересоздаёт
   головой main) и не на копию, из которой запущен. Нет установки или путь вне кэша — прежнее поведение (копия install).
2. Запуски claude из pantheon идут без PANTHEON_ROLE, PANTHEON_SESSION и CLAUDE_CODE_AGENT: иначе `claude daemon`,
   поднятый первым вызовом, раздал бы роль окна (hq) всем фоновым окнам. Проверка вживую (заглушка claude пишет своё
   окружение) и по коду: каждый subprocess/exec с claude_bin() передаёт env=claude_env().

Запуск: python3 -I plugins/pantheon/tests/test_live_code.py  (код 0 — все прошли). Временный HOME, настоящие ~/.claude и
~/.local не трогаются. TEST_PANTHEON_LIB — другая копия lib (проба: сломанное правило должно покраснеть).
"""
import ast
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

_ROOT = tempfile.mkdtemp(prefix="live_code-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBDIR = os.environ.get("TEST_PANTHEON_LIB") or os.path.join(ROOT, "lib")
LIB = os.path.join(LIBDIR, "pantheon.py")


def pantheon_python():
    if sys.version_info >= (3, 11):
        return sys.executable
    py = shutil.which("python3")
    ok = py and subprocess.run([py, "-c", "import sys; print(sys.version_info >= (3, 11))"], capture_output=True,
                               text=True).stdout.strip() == "True"
    if not ok:
        sys.exit("нужен python3 3.11+ в PATH: pantheon.py на системном python не идёт")
    return py


PY = pantheon_python()
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond or not detail else f"\n     {detail}"))


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


def plugin(d, version):
    write(os.path.join(d, ".claude-plugin", "plugin.json"), json.dumps({"name": "pantheon", "version": version}))
    write(os.path.join(d, "bin", "pantheon"), "#!/bin/sh\n")


def home(installed_path="cache", installed=True):
    """Временный HOME: клон маркетплейса 2.0.0 (голова main), кэш установленной 1.0.0, installed_plugins.json."""
    t = tempfile.mkdtemp(prefix="home-")
    plugins = os.path.join(t, ".claude", "plugins")
    clone = os.path.join(plugins, "marketplaces", "agent-kit", "plugins", "pantheon")
    cache = os.path.join(plugins, "cache", "agent-kit", "pantheon", "1.0.0")
    plugin(clone, "2.0.0")
    plugin(cache, "1.0.0")
    where = {"cache": cache, "clone": clone, "missing": cache + "-gone"}[installed_path]
    if installed:
        rows = [{"scope": "project", "installPath": clone, "version": "2.0.0"},
                {"scope": "user", "installPath": where, "version": "1.0.0"}]
        write(os.path.join(plugins, "installed_plugins.json"),
              json.dumps({"version": 2, "plugins": {"pantheon@agent-kit": rows, "guard@agent-kit": []}}))
    return t, clone, cache


def run(h, *args, extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PANTHEON_", "CLAUDE_CODE_"))}
    env.update({"HOME": h, "PANTHEON_HOME": os.path.join(h, "pantheon"), "PANTHEON_STATE": os.path.join(h, "state"),
                "PANTHEON_NO_NOTIFY": "1", "PANTHEON_DRYRUN": "1"})
    env.update(extra or {})
    os.makedirs(env["PANTHEON_HOME"], exist_ok=True)
    return subprocess.run([PY, "-I", LIB, *args], env=env, capture_output=True, text=True, timeout=120)


def current(h):
    return os.path.join(h, ".local", "share", "pantheon", "current")


# --- 1. current → установленная версия ------------------------------------------------------------------------------
h, clone, cache = home()
os.makedirs(os.path.dirname(current(h)))
os.symlink(clone, current(h))  # как было до metis-0321: ссылка на клон маркетплейса
r = run(h, "install")
cur = current(h)
check("install: current → кэш установленной версии, а не клон",
      r.returncode == 0 and os.path.islink(cur) and os.path.realpath(cur) == os.path.realpath(cache),
      f"{r.returncode} {r.stdout!r} {r.stderr!r} → {os.path.realpath(cur) if os.path.lexists(cur) else '-'}")
link = os.path.join(h, ".local", "bin", "pantheon")
check("install: ~/.local/bin/pantheon идёт через current в установленную",
      os.path.realpath(link) == os.path.realpath(os.path.join(cache, "bin", "pantheon")), os.path.realpath(link))
r = run(h, "install")
check("install повторно: та же ссылка, без хвостов current.new-*",
      r.returncode == 0 and os.path.realpath(cur) == os.path.realpath(cache)
      and not [x for x in os.listdir(os.path.dirname(cur)) if x.startswith("current.new-")], os.listdir(os.path.dirname(cur)))

for kind, why in (("clone", "installPath вне кэша (клон)"), ("missing", "папки установки нет")):
    h, clone, cache = home(installed_path=kind)
    r = run(h, "install")
    check(f"install: {why} — ни клон, ни пустота, а копия, из которой запущен install",
          r.returncode == 0 and os.path.realpath(current(h)) == os.path.realpath(os.path.dirname(LIBDIR)),
          f"{r.stderr!r} → {os.path.realpath(current(h))}")
h, clone, cache = home(installed=False)
r = run(h, "install")
check("install: нет installed_plugins.json — копия, из которой запущен (разработка)",
      r.returncode == 0 and os.path.realpath(current(h)) == os.path.realpath(os.path.dirname(LIBDIR)), r.stderr)

# хуки окон ролей (строгий guard, agents.py) — из установленной версии, а не из клона
h, clone, cache = home()
plugins = os.path.join(h, ".claude", "plugins")
gclone = os.path.join(plugins, "marketplaces", "agent-kit", "plugins", "guard", "hooks", "guard.py")
gcache = os.path.join(plugins, "cache", "agent-kit", "guard", "0.1.0", "hooks", "guard.py")
for f in (gclone, gcache, os.path.join(clone, "hooks", "agents.py"), os.path.join(cache, "hooks", "agents.py")):
    write(f, "")
write(os.path.join(os.path.dirname(os.path.dirname(gcache)), ".claude-plugin", "plugin.json"), "{}")
data = json.load(open(os.path.join(plugins, "installed_plugins.json")))
data["plugins"]["guard@agent-kit"] = [{"scope": "user", "installPath": os.path.dirname(os.path.dirname(gcache))}]
write(os.path.join(plugins, "installed_plugins.json"), json.dumps(data))
probe = ("import sys; sys.path.insert(0, sys.argv[1]); import pantheon as P; "
         "print(P.guard_script()); print(P.agents_script())")
env = {k: v for k, v in os.environ.items() if not k.startswith("PANTHEON_")}
env.update({"HOME": h, "PANTHEON_HOME": os.path.join(h, "pantheon"), "PANTHEON_STATE": os.path.join(h, "state")})
got = subprocess.run([PY, "-I", "-c", probe, LIBDIR], env=env, capture_output=True, text=True).stdout.split()
check("окна ролей: guard.py и agents.py из установленной версии, не из клона",
      got == [os.path.realpath(gcache), os.path.realpath(os.path.join(cache, "hooks", "agents.py"))], got)
os.remove(os.path.join(plugins, "installed_plugins.json"))
got = subprocess.run([PY, "-I", "-c", probe, LIBDIR], env=env, capture_output=True, text=True).stdout.split()
check("окна ролей: установки нет — клон, как раньше", got == [os.path.realpath(gclone),
      os.path.realpath(os.path.join(clone, "hooks", "agents.py"))], got)

# --- 2. запуски claude без роли окна ------------------------------------------------------------------------------
h, clone, cache = home()
stub = os.path.join(h, "stub")
write(os.path.join(stub, "claude"), '#!/bin/sh\nenv >> "$STUB_ENV"\necho "--" >> "$STUB_ENV"\nexit 1\n')
os.chmod(os.path.join(stub, "claude"), 0o755)
envlog = os.path.join(h, "claude-env.log")
r = run(h, "plugins", "update", "--quiet", extra={
    "PATH": stub + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"), "STUB_ENV": envlog,
    "PANTHEON_ROLE": "hq", "PANTHEON_SESSION": "zeus", "CLAUDE_CODE_AGENT": "hq", "PANTHEON_DRYRUN": "0"})
seen = open(envlog, encoding="utf-8").read() if os.path.exists(envlog) else ""
check("plugins update из окна hq: claude вызван", "PATH=" in seen, f"{r.returncode} {r.stderr!r}")
check("claude без PANTHEON_ROLE, PANTHEON_SESSION, CLAUDE_CODE_AGENT (демон не унаследует роль окна)",
      seen and not any(f"\n{k}=" in "\n" + seen for k in ("PANTHEON_ROLE", "PANTHEON_SESSION", "CLAUDE_CODE_AGENT")),
      [ln for ln in seen.splitlines() if ln.startswith(("PANTHEON_", "CLAUDE_CODE_"))])
check("остальное окружение на месте (STUB_ENV, HOME)", f"STUB_ENV={envlog}" in seen and f"HOME={h}" in seen)


def claude_calls(path):
    """[(строка, есть ли env=claude_env())] — subprocess.run/Popen и os.exec* с claude_bin() в списке аргументов
    или с переменной argv, собранной из claude_bin() в той же функции."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        claude_argv = False
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "argv" for t in n.targets) \
                    and isinstance(n.value, ast.List) and n.value.elts and "claude_bin" in ast.unparse(n.value.elts[0]):
                claude_argv = True
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call) or not n.args:
                continue
            f = ast.unparse(n.func)
            if f not in ("subprocess.run", "subprocess.Popen", "os.execv", "os.execve"):
                continue
            first = n.args[1] if f.startswith("os.exec") and len(n.args) > 1 else n.args[0]
            is_claude = (isinstance(first, ast.List) and first.elts and "claude_bin" in ast.unparse(first.elts[0])) \
                or (isinstance(first, ast.Name) and first.id == "argv" and claude_argv)
            if not is_claude:
                continue
            env = [k.value for k in n.keywords if k.arg == "env"] + (n.args[2:3] if f == "os.execve" else [])
            out.append((n.lineno, fn.name, bool(env) and "claude_env" in ast.unparse(env[0])))
    return out


for name in ("pantheon.py", "watch.py"):
    calls = claude_calls(os.path.join(LIBDIR, name))
    bad = [f"{name}:{ln} {fn}" for ln, fn, ok in calls if not ok]
    check(f"{name}: все запуски claude ({len(calls)}) — с env=claude_env()", calls and not bad, bad)

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
