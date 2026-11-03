#!/usr/bin/env python3
"""Контекст вызова хуков guard (metis-0330, ступень 1): всё, что зависит от аргументов и окружения, считается в
configure() модуля и пересчитывается заново — guard.set_context в процессе, который судит много вызовов (демон хуков).

Запуск: python3 -I plugins/guard/tests/test_context.py   (код выхода 0 — все прошли)
- разбор AST hooks/*.py: чтений sys.argv, os.environ, os.getenv, os.path.expanduser при загрузке модуля (строки
  модуля, тела классов, значения по умолчанию и декораторы) вне configure() и блока `if __name__ == "__main__"` нет;
  копий `from guard_rules|taint|guard import <имя контекста>` в плагинах нет. Сам разбор проверен на образцах с
  нарушениями;
- значения: после set_context в загруженном процессе имена контекста guard, guard_rules и taint — те же, что у нового
  процесса с этими argv и окружением (по каждому контексту, подряд в одном процессе);
- решения: набор событий в нескольких контекстах (plugin, --managed, --strict; два HOME; TMPDIR и без него;
  GUARD_OFF; роль окна) — новый процесс через hooks/python.sh против одного долгоживущего процесса с fork на событие
  (set_context в родителе — контекст меняется много раз подряд; и в ребёнке — как будущий демон): код, stdout и
  stderr совпадают. Набор различает контексты — проверено: GUARD_OFF, HOME и TMPDIR меняют решения, а строгий guard
  отказывает там, где хук плагина при управляемых настройках молчит (дыра прототипа: MODE из argv при загрузке);
- кэш разбора Bash (по команде и папке) сбрасывается при смене контекста: `~` раскрывается от нового HOME.
"""
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(os.path.dirname(HERE), "hooks")
PLUGINS = os.path.dirname(os.path.dirname(HERE))
RUNNER = os.path.join(HERE, "_ctx_runner.py")
LAUNCHER = os.path.join(HOOKS, "python.sh")
MANAGED_FILE = "/Library/Application Support/ClaudeCode/managed-settings.json"
SUB_TIMEOUT = 120
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:900]))


# --- разбор AST ---------------------------------------------------------------------------------------------------

def _is_main_cmp(t):
    return (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__"
            and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in t.comparators))


def _is_main_guard(node):
    """`if __name__ == "__main__"` или `if … and __name__ == "__main__"`: тело — запуск скриптом, не загрузка."""
    t = node.test if isinstance(node, ast.If) else None
    return _is_main_cmp(t) or (isinstance(t, ast.BoolOp) and isinstance(t.op, ast.And)
                               and any(_is_main_cmp(v) for v in t.values))


def _env_reads(node):
    """Чтения контекста в узле: sys.argv, os.environ, os.getenv, environ, getenv, expanduser (любая запись)."""
    out = []
    for n in ast.walk(node):
        name = None
        if isinstance(n, ast.Attribute) and n.attr in ("argv", "environ", "getenv", "environb", "expanduser"):
            name = n.attr
        elif isinstance(n, ast.Name) and n.id in ("environ", "getenv", "environb", "expanduser", "argv"):
            name = n.id
        if name:
            out.append((n.lineno, name))
    return out


def import_time_reads(src):
    """(строка, что) — чтения контекста, которые выполняются при загрузке модуля, вне configure()."""
    tree = ast.parse(src)
    found = []

    def visit(stmts):
        for st in stmts:
            if isinstance(st, ast.If) and _is_main_guard(st):
                visit(st.orelse)
                continue
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if st.name == "configure":
                    continue
                parts = list(st.decorator_list) + list(st.args.defaults) + [d for d in st.args.kw_defaults if d]
                for p in parts:
                    found.extend(_env_reads(p))
                continue
            if isinstance(st, ast.ClassDef):
                for p in list(st.decorator_list) + list(st.bases):
                    found.extend(_env_reads(p))
                visit(st.body)
                continue
            if isinstance(st, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                head = [getattr(st, a) for a in ("test", "iter", "target") if getattr(st, a, None) is not None]
                head += [i.context_expr for i in getattr(st, "items", [])]
                for h in head:
                    found.extend(_env_reads(h))
                for a in ("body", "orelse", "finalbody"):
                    visit(getattr(st, a, []) or [])
                for h in getattr(st, "handlers", []):
                    visit(h.body)
                continue
            found.extend(_env_reads(st))
    visit(tree.body)
    return sorted(set(found))


def context_names(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "configure":
            return {n for g in ast.walk(node) if isinstance(g, ast.Global) for n in g.names}
    return set()


def test_ast():
    samples = {
        "HOME = os.path.expanduser('~')\n": True,
        "MODE = 'strict' if '--strict' in sys.argv[1:] else 'plugin'\n": True,
        "from os import environ\nX = environ.get('A')\n": True,
        "X = os.getenv('A')\n": True,
        "class K:\n    H = os.environ['HOME']\n": True,
        "def f(h=os.path.expanduser('~')):\n    pass\n": True,
        "try:\n    T = os.environ['TMPDIR']\nexcept KeyError:\n    T = ''\n": True,
        "if os.environ.get('X'):\n    pass\n": True,
        "def configure():\n    global H\n    H = os.path.expanduser('~')\n": False,
        "def f():\n    return os.environ.get('A')\n": False,
        "if __name__ == '__main__':\n    run(sys.argv[1:])\n": False,
        "if sys.version_info < (3, 11) and __name__ == '__main__':\n    os.environ['X'] = '1'\n": False,
        "if sys.version_info < (3, 11) or __name__ == '__main__':\n    os.environ['X'] = '1'\n": True,
    }
    bad = [s for s, want in samples.items() if bool(import_time_reads(s)) != want]
    check("разбор AST ловит чтения окружения при загрузке и пропускает configure(), функции и __main__ (образцы)",
          not bad, bad)
    files = sorted(f for f in os.listdir(HOOKS) if f.endswith(".py"))
    check("hooks/*.py — guard.py, guard_rules.py, merge_gate.py, protect_config.py, taint.py на месте",
          {"guard.py", "guard_rules.py", "merge_gate.py", "protect_config.py", "taint.py"} <= set(files), files)
    for f in files:
        src = open(os.path.join(HOOKS, f), encoding="utf-8").read()
        got = import_time_reads(src)
        check(f"{f}: нет чтений argv и окружения при загрузке вне configure()", not got, got)
    names = {}
    for m in ("guard", "guard_rules", "taint"):
        names[m] = context_names(os.path.join(HOOKS, m + ".py"))
        check(f"{m}.py: configure() есть и пересчитывает HOME", "HOME" in names[m], sorted(names[m]))
    check("guard_rules.configure: MODE, OFF, FAIL_LOG, TEMP_ROOTS, STATE_DIR, PANTHEON, MARKET_GUARD",
          {"MODE", "OFF", "FAIL_LOG", "TEMP_ROOTS", "STATE_DIR", "PANTHEON", "MARKET_GUARD"} <= names["guard_rules"])
    # копия имени контекста через from-импорт не обновится при set_context
    copies = []
    for root, _, fs in os.walk(PLUGINS):
        for f in fs:
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            try:
                tree = ast.parse(open(p, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom) and n.module in names:
                    hit = [a.name for a in n.names if a.name in names[n.module] or a.name == "*"]
                    if hit:
                        copies.append(f"{os.path.relpath(p, PLUGINS)}:{n.lineno} {n.module} {hit}")
    check("нет копий имён контекста `from guard_rules|taint|guard import …` в плагинах", not copies, copies)


# --- значения и решения -------------------------------------------------------------------------------------------

def python_of():
    r = subprocess.run(["/bin/sh", LAUNCHER, "-c", "import sys; print(sys.executable)"], capture_output=True,
                       text=True, timeout=SUB_TIMEOUT)
    return r.stdout.strip()


def managed_active():
    """Управляемые настройки этого Mac зовут guard --managed — хук плагина при MARKET_GUARD на месте молчит."""
    try:
        data = json.load(open(MANAGED_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any("guard.py" in (h.get("command") or "") and "--managed" in (h.get("command") or "")
               for g in ((data.get("hooks") or {}).get("PreToolUse") or []) for h in g.get("hooks") or [])


class World:
    """Файлы одного прохода: два HOME, TMPDIR, рабочая папка. reset() — то же состояние перед каждым проходом."""

    def __init__(self, root):
        self.root = root
        self.ha, self.hb = os.path.join(root, "homeA"), os.path.join(root, "homeB")
        self.t1, self.work = os.path.join(root, "t1"), os.path.join(root, "work")

    def reset(self):
        for d in (self.ha, self.hb, self.t1, self.work):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
        market = os.path.join(self.hb, ".claude", "plugins", "marketplaces", "agent-kit", "plugins", "guard", "hooks")
        os.makedirs(market)
        open(os.path.join(market, "guard.py"), "w").close()
        with open(os.path.join(self.work, "a.txt"), "w") as fh:
            fh.write("agent-kit\n")


def contexts(w):
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "en_US.UTF-8"}
    return {
        "plugin-A": ([], dict(base, HOME=w.ha, TMPDIR=w.t1)),
        "strict-B": (["--strict"], dict(base, HOME=w.hb)),
        "plugin-B": ([], dict(base, HOME=w.hb)),
        "managed-A": (["--managed"], dict(base, HOME=w.ha)),
        "managed-B": (["--managed"], dict(base, HOME=w.hb, TMPDIR=w.t1)),
        "managed-A-off": (["--managed"], dict(base, HOME=w.ha, GUARD_OFF="attribution,protect-config")),
        "hestia-tmp": (["--strict"], dict(base, HOME=w.ha, TMPDIR=w.t1, PANTHEON_ROLE="hestia")),
        "hestia-notmp": (["--strict"], dict(base, HOME=w.ha, PANTHEON_ROLE="hestia")),
    }


def events(w):
    co = "Co-" + "Authored-By: " + "Cla" + "ude <noreply@anthropic.com>"
    pre = {"session_id": "ctx0330abcdef1234", "transcript_path": os.path.join(w.root, "none.jsonl"), "cwd": w.work,
           "permission_mode": "default", "hook_event_name": "PreToolUse", "tool_use_id": "toolu_ctx"}

    def ev(tool, ti, name="PreToolUse", **kw):
        return dict(pre, hook_event_name=name, tool_name=tool, tool_input=ti, **kw)
    role = {"agent_type": "dev-opus"}  # protect-config судит роли Пантеона: защищённое — от HOME контекста
    return {
        "git-status": ev("Bash", {"command": "git status"}),
        "attribution": ev("Bash", {"command": f"git commit -m fix -m '{co}'"}),
        "zshrc-A": ev("Bash", {"command": f"touch {w.ha}/.zshrc"}, **role),
        "zshrc-tilde": ev("Bash", {"command": "touch ~/.zshrc"}, **role),
        "settings-A": ev("Write", {"file_path": os.path.join(w.ha, ".claude", "settings.json"), "content": "{}"},
                         **role),
        "write-t1": ev("Bash", {"command": f"touch {w.t1}/x.txt"}),
        "read-a": ev("Read", {"file_path": os.path.join(w.work, "a.txt")}),
        "edit-a": ev("Edit", {"file_path": os.path.join(w.work, "a.txt"), "old_string": "agent-kit",
                              "new_string": "agent-kit"}),
        "post-bash": ev("Bash", {"command": "git status"}, name="PostToolUse",
                        tool_response={"stdout": "", "stderr": "", "interrupted": False}),
    }


def taint_jobs(w):
    """tg-taint: флаг — в HOME контекста; GUARD_OFF=tg-taint выключает."""
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "en_US.UTF-8"}
    pre = {"session_id": "taint0330abcdef12", "transcript_path": os.path.join(w.root, "none.jsonl"), "cwd": w.work,
           "permission_mode": "default", "tool_use_id": "toolu_t"}
    source = dict(pre, hook_event_name="PostToolUse", tool_name="Bash",
                  tool_input={"command": "python3 ~/projects/other/tg-read/tg_read.py history chat -o -"},
                  tool_response={"stdout": "x", "stderr": "", "interrupted": False})
    fetch = dict(pre, hook_event_name="PreToolUse", tool_name="WebFetch",
                 tool_input={"url": "https://example.com", "prompt": "x"})
    ea, eb = dict(base, HOME=w.ha), dict(base, HOME=w.hb)
    eoff = dict(base, HOME=w.ha, GUARD_OFF="tg-taint")
    out = []
    for name, env, ev in (("taint-src-A", ea, source), ("taint-fetch-B", eb, fetch), ("taint-fetch-A", ea, fetch),
                          ("taint-fetch-A-off", eoff, fetch)):
        out.append((name, {"hook": "taint", "argv": [], "env": env, "cwd": w.work, "event": ev}))
    return out


def jobs_of(w):
    ctx, evs = contexts(w), events(w)
    out = []
    for en, ev in evs.items():  # контекст меняется на каждом задании: ловит то, что от прошлого вызова осталось
        for cn, (argv, env) in ctx.items():
            out.append((f"{cn} {en}", {"hook": "guard", "argv": argv, "env": env, "cwd": w.work, "event": ev}))
    return out + taint_jobs(w)


def fresh(py_unused, job):
    hook = os.path.join(HOOKS, "guard.py" if job["hook"] == "guard" else "taint.py")
    r = subprocess.run(["/bin/sh", LAUNCHER, hook, *job["argv"]], input=json.dumps(job["event"], ensure_ascii=False).encode(),
                       capture_output=True, env=job["env"], cwd=job["cwd"], timeout=SUB_TIMEOUT)
    return [r.returncode, r.stdout.decode(), r.stderr.decode()]


def forked(py, w, jobs, where):
    out_dir = os.path.join(w.root, "runner-" + where)
    os.makedirs(out_dir, exist_ok=True)
    jf, of = os.path.join(out_dir, "jobs.json"), os.path.join(out_dir, "out.json")
    with open(jf, "w", encoding="utf-8") as fh:
        json.dump([j for _, j in jobs], fh, ensure_ascii=False)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.path.join(w.root, "runner-home"),
           "LANG": "en_US.UTF-8"}
    r = subprocess.run([py, "-I", RUNNER, "run", HOOKS, jf, of, where], capture_output=True, text=True, env=env,
                       timeout=SUB_TIMEOUT * 3)
    if r.returncode != 0:
        return None, r.stderr[-800:]
    return json.load(open(of, encoding="utf-8")), ""


def dec(res):
    code, out, _ = res
    if code == 2 or '"deny"' in out:
        return "deny"
    return "ask" if '"ask"' in out else "allow"


def test_values(py, w):
    w.reset()
    ctx = contexts(w)
    diffs = []
    for cn, (argv, env) in ctx.items():
        a = subprocess.run([py, "-I", RUNNER, "dump", HOOKS, *argv], capture_output=True, text=True, env=env,
                           timeout=SUB_TIMEOUT)
        # загруженный процесс в другом контексте (homeB, --strict без TMPDIR) — затем set_context в этот
        other = dict(env, HOME=w.hb if env["HOME"] == w.ha else w.ha, GUARD_OFF="push")
        other.pop("TMPDIR", None)
        set_env = dict(other, CTX_SET=json.dumps({"argv": argv, "env": env}))
        b = subprocess.run([py, "-I", RUNNER, "dump", HOOKS, "--strict" if "--strict" not in argv else "--managed"],
                           capture_output=True, text=True, env=set_env, timeout=SUB_TIMEOUT)
        if a.returncode or b.returncode or a.stdout != b.stdout:
            diffs.append((cn, a.returncode, b.returncode, a.stderr[-300:], b.stderr[-300:],
                          _first_diff(a.stdout, b.stdout)))
    check(f"значения контекста после set_context — как у нового процесса ({len(ctx)} контекстов)", not diffs, diffs)


def _first_diff(a, b):
    try:
        ja, jb = json.loads(a), json.loads(b)
    except ValueError:
        return (a[:200], b[:200])
    return [(m, k, ja[m][k], jb[m].get(k)) for m in ja for k in ja[m] if ja[m][k] != jb[m].get(k)][:3]


def test_decisions(py, w):
    jobs = jobs_of(w)
    w.reset()
    want = [fresh(py, j) for _, j in jobs]
    by = {name: r for (name, _), r in zip(jobs, want)}
    for where in ("parent", "child"):
        w.reset()
        got, err = forked(py, w, jobs, where)
        if got is None:
            check(f"процесс с fork ({where}) отработал", False, err)
            continue
        bad = [(name, a, b) for (name, _), a, b in zip(jobs, want, got) if a != b]
        check(f"решения одного процесса с set_context в {'родителе' if where == 'parent' else 'ребёнке'} — как у "
              f"нового процесса: {len(jobs)} заданий, код, stdout и stderr", not bad,
              [(n, a[0], a[1][:160], a[2][:160], "≠", b[0], b[1][:160], b[2][:160]) for n, a, b in bad[:3]])
    # набор различает контексты — иначе совпадение ничего не доказывает
    d = {k: dec(v) for k, v in by.items()}
    check("GUARD_OFF меняет решение: attribution — отказ у managed-A, пропуск у managed-A-off",
          (d["managed-A attribution"], d["managed-A-off attribution"]) == ("deny", "allow"),
          (d["managed-A attribution"], d["managed-A-off attribution"]))
    check("HOME меняет решение: touch <homeA>/.zshrc у роли — отказ при HOME=homeA, пропуск при HOME=homeB",
          (d["managed-A zshrc-A"], d["managed-B zshrc-A"]) == ("deny", "allow"),
          (d["managed-A zshrc-A"], d["managed-B zshrc-A"]))
    tmp_real = os.path.realpath(w.t1)
    if any(tmp_real.startswith(r + "/") for r in ("/tmp", "/private/tmp")):
        print("пропущено: TMPDIR различает решения, только когда временная папка теста вне /tmp")
    else:
        check("TMPDIR меняет решение: запись в t1 у окна hestia — пропуск с TMPDIR=t1, отказ без него",
              (d["hestia-tmp write-t1"], d["hestia-notmp write-t1"]) == ("allow", "deny"),
              (d["hestia-tmp write-t1"], d["hestia-notmp write-t1"]))
    check("tg-taint: флаг в HOME контекста — WebFetch спрашивает при HOME=homeA, без флага в homeB и с GUARD_OFF "
          "— пропуск", (d["taint-fetch-A"], d["taint-fetch-B"], d["taint-fetch-A-off"]) == ("ask", "allow", "allow"),
          (d["taint-fetch-A"], d["taint-fetch-B"], d["taint-fetch-A-off"]))
    if managed_active():
        check("режим из argv: --strict отказывает (attribution), хук плагина того же HOME при управляемых настройках "
              "молчит", (d["strict-B attribution"], d["plugin-B attribution"]) == ("deny", "allow"),
              (d["strict-B attribution"], d["plugin-B attribution"]))
    else:
        print("пропущено: управляемые настройки этой машины не зовут guard --managed — режим различает только "
              "через них (нужен macOS с ними)")
        check("режим из argv: --strict отказывает (attribution)", d["strict-B attribution"] == "deny",
              d["strict-B attribution"])


def test_cache(py, w):
    w.reset()
    # одна и та же команда в одной папке (ключ кэша), меняется только HOME
    code = ("import json, os, sys; sys.path.insert(0, sys.argv[1]); import guard, guard_rules as g; out = []; a = sys.argv[:]\n"
            "for h in a[3:]:\n"
            "    guard.set_context([], {'HOME': h, 'PATH': os.environ['PATH']})\n"
            "    out.append(g.bash_targets('touch ~/.zshrc', a[2]))\n"
            "print(json.dumps(out))")
    r = subprocess.run([py, "-I", "-c", code, HOOKS, w.work, w.ha, w.hb], capture_output=True, text=True,
                       timeout=SUB_TIMEOUT,
                       env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": w.ha})
    try:
        got = json.loads(r.stdout)
    except ValueError:
        got = None
    want = [[os.path.join(os.path.realpath(h), ".zshrc")] for h in (w.ha, w.hb)]
    ok = got is not None and [[os.path.realpath(p) for p in t] for t in got] == want
    check("разбор Bash после set_context — заново: ~ раскрывается от нового HOME (кэш по команде и папке сброшен)",
          ok, (got, want, r.stderr[-300:]))


def main():
    test_ast()
    py = python_of()
    if not py:
        check("python.sh нашёл Python 3.11+", False)
    else:
        root = os.path.realpath(tempfile.mkdtemp(prefix="guard-ctx-"))
        try:
            w = World(root)
            test_values(py, w)
            test_decisions(py, w)
            test_cache(py, w)
        finally:
            shutil.rmtree(root, ignore_errors=True)
    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
