#!/usr/bin/env python3
"""Живой код и окружение запусков claude (metis-0321).

1. `pantheon install`, current и хуки окон ролей идут только на ПРОВЕРЕННОЕ дерево: installPath внутри
   ~/.claude/plugins/cache, чей хеш совпал с verified.json; иначе — последнее проверенное из записи, иначе ничего с
   тревогой. Клон маркетплейса и копия, из которой запущен install, — никогда. Тест-страж по AST.
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
import time

_ROOT = tempfile.mkdtemp(prefix="live_code-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBDIR = os.environ.get("TEST_PANTHEON_LIB") or os.path.join(ROOT, "lib")
LIB = os.path.join(LIBDIR, "pantheon.py")


RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
def pantheon_python():
    return sys.executable


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
    return subprocess.run([PY, "-I", RUN_PY, *args], env=env, capture_output=True, text=True, timeout=120)


def current(h):
    return os.path.join(h, ".local", "share", "pantheon", "current")


# --- 1. current и окна → только проверенное дерево (verified.json) ------------------------------------------------
def penv(h):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PANTHEON_", "CLAUDE_CODE_"))}
    env.update({"HOME": h, "PANTHEON_HOME": os.path.join(h, "pantheon"), "PANTHEON_STATE": os.path.join(h, "state"),
                "PANTHEON_NO_NOTIFY": "1"})
    return env


def py(h, code, *args):
    """Код с `import pantheon as P` во временном HOME; stdout строками."""
    os.makedirs(os.path.join(h, "pantheon"), exist_ok=True)
    r = subprocess.run([PY, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pantheon as P\n" + code,
                        LIBDIR, *args], env=penv(h), capture_output=True, text=True, timeout=120)
    return r.stdout.split("\n")[:-1] if r.returncode == 0 else ["ERR " + r.stderr[-300:]]


def verify(h, name, d):
    """Запись verified.json, как после успешной установки plugins-update."""
    return py(h, "P.verified_write(sys.argv[2], sys.argv[3], P._tree_hash(sys.argv[3]), '1.0.0', 'test')", name, d)


def alerts(h):
    p = os.path.join(h, "pantheon", "alerts.md")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


h, clone, cache = home()
verify(h, "pantheon", cache)
os.makedirs(os.path.dirname(current(h)))
os.symlink(clone, current(h))  # как было до metis-0321: ссылка на клон маркетплейса
r = run(h, "install")
cur = current(h)
check("install: current → проверенный кэш установленной версии, а не клон",
      r.returncode == 0 and os.path.islink(cur) and os.path.realpath(cur) == os.path.realpath(cache),
      f"{r.returncode} {r.stdout!r} {r.stderr!r} → {os.path.realpath(cur) if os.path.lexists(cur) else '-'}")
link = os.path.join(h, ".local", "bin", "pantheon")
check("install: ~/.local/bin/pantheon идёт через current в установленную",
      os.path.realpath(link) == os.path.realpath(os.path.join(cache, "bin", "pantheon")), os.path.realpath(link))
r = run(h, "install")
check("install повторно: та же ссылка, без хвостов current.new-*",
      r.returncode == 0 and os.path.realpath(cur) == os.path.realpath(cache)
      and not [x for x in os.listdir(os.path.dirname(cur)) if x.startswith("current.new-")], os.listdir(os.path.dirname(cur)))

# нет проверенного: ни клон, ни рабочая копия, ни непроверенный кэш — current не трогается, тревога
for kind, why in (("cache", "verified.json нет"), ("clone", "installPath вне кэша (клон)"),
                  ("missing", "папки установки нет"), ("broken", "verified.json не читается"),
                  ("other", "хеш установленного не совпал (ручная переустановка)")):
    h, clone, cache = home(installed_path="clone" if kind == "clone" else "missing" if kind == "missing" else "cache")
    if kind == "broken":
        write(os.path.join(h, "state", "plugins", "verified.json"), "{")
    if kind in ("clone", "missing", "other"):
        verify(h, "pantheon", clone if kind == "clone" else cache)
        if kind == "other":
            write(os.path.join(cache, "hooks", "evil.py"), "print(1)\n")
    r = run(h, "install")
    if kind == "missing":  # установленной папки нет, проверенная запись цела — последнее проверенное и тревога
        check("install: папки установки нет — current на последнем проверенном, тревога",
              r.returncode == 0 and os.path.realpath(current(h)) == os.path.realpath(cache) and "не проверено" in r.stdout,
              f"{r.stdout!r} {r.stderr!r}")
        continue
    check(f"install: {why} — current не создана, тревога о непроверенном",
          r.returncode == 0 and not os.path.lexists(current(h)) and "verified.json" in r.stderr
          and "не проверено" in r.stdout, f"{r.stdout!r} {r.stderr!r}")
h, clone, cache = home(installed=False)
r = run(h, "install")
check("install: нет installed_plugins.json — не рабочая копия, current не создана",
      r.returncode == 0 and not os.path.lexists(current(h)), r.stderr)
# проба B (ревью 90b, круг 3): current на проверенной, установлено непроверенное — install её не перевешивает
h, clone, cache = home()
old = os.path.join(os.path.dirname(cache), "0.9.0")
plugin(old, "0.9.0")
verify(h, "pantheon", old)
os.makedirs(os.path.dirname(current(h)))
os.symlink(old, current(h))
r = run(h, "install")
check("install (проба B): установлено непроверенное — current остаётся на последнем проверенном, тревога",
      r.returncode == 0 and os.path.realpath(current(h)) == os.path.realpath(old) and "не проверено" in r.stdout,
      f"{os.path.realpath(current(h))} {r.stdout!r}")
r = run(h, "plugins", "accept", "pantheon")
check("plugins accept pantheon: ваше «да» — запись в verified.json и current на установленное",
      r.returncode == 0 and os.path.realpath(current(h)) == os.path.realpath(cache)
      and json.load(open(os.path.join(h, "state", "plugins", "verified.json")))["pantheon"]["by"] == "accept", r.stderr)
r = run(h, "plugins", "accept", "--new")
check("plugins accept --new: записанный pantheon не трогает, guard без установки — строка, но код 0 (шаг setup)",
      r.returncode == 0 and "pantheon: " not in r.stdout and "guard@agent-kit" in r.stderr, f"{r.stdout!r} {r.stderr!r}")
r = run(h, "plugins", "accept", "guard")
check("plugins accept guard без установки — код 1, verified.json о guard нет",
      r.returncode == 1 and "guard" not in json.load(open(os.path.join(h, "state", "plugins", "verified.json"))),
      f"{r.stdout!r} {r.stderr!r}")

# хуки окон ролей (строгий guard, agents.py) — из проверенного дерева; клон маркетплейса — никогда (проба A)
h, clone, cache = home()
plugins = os.path.join(h, ".claude", "plugins")
gclone = os.path.join(plugins, "marketplaces", "agent-kit", "plugins", "guard", "hooks", "guard.py")
groot = os.path.join(plugins, "cache", "agent-kit", "guard", "0.1.0")
gcache = os.path.join(groot, "hooks", "guard.py")
for f in (gclone, gcache, os.path.join(clone, "hooks", "agents.py"), os.path.join(cache, "hooks", "agents.py")):
    write(f, "")
write(os.path.join(groot, ".claude-plugin", "plugin.json"), "{}")
data = json.load(open(os.path.join(plugins, "installed_plugins.json")))
data["plugins"]["guard@agent-kit"] = [{"scope": "user", "installPath": groot}]
write(os.path.join(plugins, "installed_plugins.json"), json.dumps(data))
HOOKS = "print(P.guard_script()); print(P.agents_script())"
got = py(h, HOOKS)
check("окна ролей: verified.json нет — ни клон, ни кэш, а несуществующий путь (guard-missing)",
      len(got) == 2 and not any(os.path.exists(x) for x in got) and "marketplaces" not in "".join(got), got)
verify(h, "guard", groot)
verify(h, "pantheon", cache)
got = py(h, HOOKS)
check("окна ролей: guard.py и agents.py из проверенного дерева", got == [os.path.realpath(gcache),
      os.path.realpath(os.path.join(cache, "hooks", "agents.py"))], got)
# guard переустановлен руками (другое дерево): окна на последнем проверенном
g2 = os.path.join(plugins, "cache", "agent-kit", "guard", "0.2.0")
shutil.copytree(groot, g2)
write(os.path.join(g2, "hooks", "guard.py"), "# не проверялось\n")
data["plugins"]["guard@agent-kit"] = [{"scope": "user", "installPath": g2}]
write(os.path.join(plugins, "installed_plugins.json"), json.dumps(data))
got = py(h, HOOKS)
check("окна ролей (проба A): установлено непроверенное — guard из последнего проверенного, не клон, не новое",
      got[:1] == [os.path.realpath(gcache)], got)
check("окна ролей: тревога «не проверено» о guard", "guard: установленное дерево" in alerts(h), alerts(h)[-300:])
write(gcache, "# правка проверенного\n")  # последнее проверенное тоже изменилось — проверенного нет
got = py(h, HOOKS)
check("окна ролей: последнее проверенное изменилось — несуществующий путь, а не клон",
      got and not os.path.exists(got[0]) and "marketplaces" not in got[0], got)
os.remove(os.path.join(plugins, "installed_plugins.json"))
got = py(h, HOOKS)
check("окна ролей: реестра нет — agents.py из последнего проверенного, guard — пусто; клона нет",
      got[1:] == [os.path.realpath(os.path.join(cache, "hooks", "agents.py"))] and not os.path.exists(got[0]), got)
write(os.path.join(h, "state", "plugins", "verified.json"), "не json")
got = py(h, HOOKS)
check("окна ролей: verified.json битый — оба пути несуществующие, без клона",
      len(got) == 2 and not any(os.path.exists(x) for x in got) and "marketplaces" not in "".join(got), got)
# кэш хеша по (путь, отпечаток mtime): повтор без правок — из кэша (сам _tree_hash не зовётся), правка — новый хеш
got = py(h, "a = P._tree_hash_cached(sys.argv[2]); real = P._tree_hash; P._tree_hash = None\n"
         "print(a == P._tree_hash_cached(sys.argv[2])); P._tree_hash = real\n"
         "open(sys.argv[2] + '/bin/pantheon', 'a').write('#x'); print(a != P._tree_hash_cached(sys.argv[2]))", cache)
check("хеш дерева: повтор из кэша, правка вложенного файла — новый хеш", got == ["True", "True"], got)
# ревью 90b, круг 4: подмена файла проверенного дерева с возвратом mtime (os.utime) — новый процесс с пустым кэшем
# в памяти не верит hash-cache.json (мутант: отпечаток только из mtime)
h, clone, cache = home()
plugins = os.path.join(h, ".claude", "plugins")
groot = os.path.join(plugins, "cache", "agent-kit", "guard", "0.1.0")
gcache = os.path.join(groot, "hooks", "guard.py")
write(gcache, "# guard: checked\n")
write(os.path.join(groot, ".claude-plugin", "plugin.json"), "{}")
data = json.load(open(os.path.join(plugins, "installed_plugins.json")))
data["plugins"]["guard@agent-kit"] = [{"scope": "user", "installPath": groot}]
write(os.path.join(plugins, "installed_plugins.json"), json.dumps(data))
verify(h, "guard", groot)
before = py(h, "print(P.guard_script())")  # кэш хеша записан на диск
st = os.stat(gcache)
time.sleep(0.05)
with open(gcache, "w") as fh:
    fh.write("# guard: EVIL!!!\n")  # тот же размер
os.utime(gcache, ns=(st.st_atime_ns, st.st_mtime_ns))
after = py(h, "print(P.guard_script())")
check("кэш хеша: подмена файла + os.utime на старый mtime — новый процесс отказывает (guard не найден)",
      before == [os.path.realpath(gcache)] and os.stat(gcache).st_mtime_ns == st.st_mtime_ns
      and os.stat(gcache).st_size == st.st_size and after and not os.path.exists(after[0]), f"{before} {after}")
got = py(h, "P.verified_write('x', sys.argv[2], 'digest-сверки', '1', 't'); print(P.verified_record('x')['hash'])", groot)
check("verified_write пишет переданный хеш сверки, а не пересчитанный", got == ["digest-сверки"], got)


# тест-страж: installed_dir без сверки (checked=False) — только в plugins_accept; current ведут только известные
# места, и никогда — копия, из которой запущен (PLUGIN)
def guard_calls():
    bad, seen = [], 0
    files = [os.path.join(LIBDIR, n) for n in os.listdir(LIBDIR) if n.endswith(".py")]
    hooks = os.path.join(os.path.dirname(LIBDIR), "hooks")
    files += [os.path.join(hooks, n) for n in os.listdir(hooks) if n.endswith(".py")] if os.path.isdir(hooks) else []
    for f in files:
        tree = ast.parse(open(f, encoding="utf-8").read())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call):
                    continue
                callee = ast.unparse(n.func).split(".")[-1]
                where = f"{os.path.basename(f)}:{n.lineno} {fn.name}"
                if callee == "installed_dir":
                    seen += 1
                    kw = [k for k in n.keywords if k.arg == "checked"]
                    unchecked = len(n.args) > 1 or (kw and not (isinstance(kw[0].value, ast.Constant)
                                                                and kw[0].value.value is True))
                    if unchecked and fn.name != "plugins_accept":
                        bad.append(f"{where}: installed_dir без сверки")
                if callee == "link_current" and fn.name not in ("install", "_current_sync", "_plugin_install",
                                                                 "plugins_accept"):
                    bad.append(f"{where}: link_current вне известных мест")
                if callee == "link_current" and "PLUGIN" in ast.unparse(n):
                    bad.append(f"{where}: current на копию, из которой запущен")
    return bad, seen


bad, seen = guard_calls()
check(f"тест-страж: installed_dir без сверки и link_current вне мест — нет (вызовов installed_dir: {seen})",
      not bad and seen >= 5, bad)
src = open(LIB, encoding="utf-8").read()
fn_src = src.split("def _installed_hook(", 1)[1].split("\ndef ", 1)[0]
check("тест-страж: _installed_hook, guard_script и agents_script не возвращают клон маркетплейса",
      "return market_path" not in fn_src
      and "return MARKET_" not in src.split("def guard_script(", 1)[1].split("\ndef agents_window", 1)[0], fn_src[-300:])
inst = src.split("def _plugin_install(", 1)[1].split("\ndef ", 1)[0]
check("тест-страж: успешная установка пишет verified.json до перевеса current",
      "verified_write(" in inst and inst.index("verified_write(") < inst.index("link_current("))

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


def _is_claude(e):
    """Первый элемент argv — claude: литерал "claude" или claude_bin()/claude_path()."""
    if isinstance(e, ast.Constant):
        return e.value == "claude"
    return isinstance(e, ast.Call) and ast.unparse(e.func).split(".")[-1] in ("claude_bin", "claude_path")


def all_claude_calls(path):
    """[(строка, функция, есть ли env=…claude_env…)] — любой вызов subprocess.*, os.exec*, обёрток run/_sh, у которых
    argv начинается с claude (литерал, claude_bin(), claude_path()) или идёт переменной argv из такого списка."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        claude_argv = any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "argv" for t in n.targets)
                          and isinstance(n.value, ast.List) and n.value.elts and _is_claude(n.value.elts[0])
                          for n in ast.walk(fn))
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call) or not n.args:
                continue
            f = ast.unparse(n.func)
            base = f.split(".")[-1]
            if not (f.startswith(("subprocess.", "os.exec")) or base in ("run", "_sh")):
                continue
            first = n.args[1] if f.startswith("os.exec") and len(n.args) > 1 else n.args[0]
            if base == "_sh":
                hit = _is_claude(first)
            else:
                hit = (isinstance(first, ast.List) and first.elts and _is_claude(first.elts[0])) \
                    or (isinstance(first, ast.Name) and first.id == "argv" and claude_argv)
            if not hit:
                continue
            env = [k.value for k in n.keywords if k.arg == "env"] + (n.args[2:3] if f == "os.execve" else [])
            out.append((n.lineno, fn.name, bool(env) and "claude_env" in ast.unparse(env[0])))
    return out


total = 0
for name in sorted(os.listdir(LIBDIR)):
    if not name.endswith(".py"):
        continue
    calls = all_claude_calls(os.path.join(LIBDIR, name))
    total += len(calls)
    bad = [f"{name}:{ln} {fn}" for ln, fn, ok in calls if not ok]
    check(f"{name}: все запуски claude ({len(calls)}) — с env=claude_env()", not bad, bad)
check("lib: запусков claude найдено достаточно (pantheon, watch, qmd, setup — не пустой обход)", total >= 20, total)
check("lib/read.py: child_env строится от claude_env()", "env = P.claude_env()" in open(os.path.join(LIBDIR, "read.py")).read())
check("ROLE_ENV: PANTHEON_ORIGIN входит (её ставит run_settings, читает ctx)",
      '"PANTHEON_ORIGIN"' in open(LIB, encoding="utf-8").read().split("ROLE_ENV = (", 1)[1].split(")", 1)[0])

print(f"\n{sum(results)}/{len(results)} прошли")
sys.exit(0 if all(results) else 1)
