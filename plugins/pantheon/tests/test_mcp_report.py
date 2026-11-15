#!/usr/bin/env python3
"""Итог проверки серверов MCP — координатору во входящие сам (metis-1047, часть 4; lib/mcp_report.py).

Запуск: python3 -I plugins/pantheon/tests/test_mcp_report.py  (код выхода 0 — все прошли)
Ядро pantheon — заглушка с временными STATE, ~/ai/pantheon и HOME; `project-tools check` подменён скриптом, который
отвечает из файла .fake.json папки и пишет свои аргументы в журнал. Сети и настоящего ~/.claude тест не трогает.
Проверяет:
  [новый]     папка направления с .mcp.json и HTTP-сервером → проба `check --json --probe --dir <папка>`, файл во
              входящих направления с итогом и шапкой «От: плановый проход», строка mcp-report: в tick.log;
  [тот же]    вход проверки не сменился → ни пробы, ни файла; сменился, итог тот же → проба без файла; итог другой →
              новый файл; вход — .mcp.json, .claude/settings.json, .claude/settings.local.json и отпечатки project-tools;
  [повтор]    fail — повтор не раньше RETRY и не дольше RETRY_FOR; fail → ok — новый файл;
  [stdio]     впервые одни stdio — без файла, затем HTTP — файл; серверы убраны — без файла;
  [за проход] не больше PER_TICK проб: вторая папка — следующим проходом;
  [сбой]      project-tools упал — тревога mcp-report-<направление>, файла нет, повтор через RETRY, успех снимает
              тревогу; inbox — ссылка → файл не пишется мимо, тревога; PANTHEON_DRYRUN — ничего; без .mcp.json — пробы нет;
  [проводка]  pantheon.release_ticks зовёт mcp_report_mod;
  [мутанты]   откат каждой ветки (сверка входа, сроки повтора, тот же итог, первый stdio, убранные серверы, PER_TICK,
              ссылка inbox, вход проверки, --probe, снятие тревоги) краснит свой сценарий.
"""
import atexit
import json
import os
import shutil
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
LIB = os.path.join(PLUGIN, "lib")
sys.path.insert(0, HERE)
from _py311 import mkroot  # noqa: E402

_ROOT = os.path.realpath(mkroot("mcp-report-"))
atexit.register(shutil.rmtree, _ROOT, True)
os.environ.pop("PANTHEON_DRYRUN", None)
SRC = open(os.path.join(LIB, "mcp_report.py"), encoding="utf-8").read()
T = 1_800_000_000
FAILS, CHECKS = [], []

FAKE = f"""#!{sys.executable} -I
import json, os, sys
with open(os.environ["FAKE_PT_LOG"], "a") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
d = sys.argv[sys.argv.index("--dir") + 1]
spec = json.load(open(os.path.join(d, ".fake.json")))
sys.stdout.write(json.dumps({{"stacks": [], "missing": [], "servers": spec.get("servers", [])}}))
sys.exit(spec.get("code", 0))
"""
FAKE_CMD = os.path.join(_ROOT, "project-tools")
with open(FAKE_CMD, "w") as fh:
    fh.write(FAKE)
os.chmod(FAKE_CMD, 0o755)

OK = {"name": "ctx", "kind": "http", "state": "ok", "why": "подключается: initialize и tools/list ответили, инструментов 2"}
FAIL = {"name": "ctx", "kind": "http", "state": "fail", "why": "не подключается: initialize — HTTP 502, не ответ MCP"}
AUTH = {"name": "sentry", "kind": "http", "state": "auth", "why": "не проверен — нужен вход (OAuth)"}
STDIO = {"name": "next", "kind": "stdio", "state": "skip", "why": "stdio — процесс не запускаю"}


def check(name, cond, extra=""):
    CHECKS.append(name)
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f" — {extra}"))
    if not cond:
        FAILS.append(name)


def load(src):
    mod = types.ModuleType(f"pantheon_mcp_report_{len(CHECKS)}")
    exec(compile(src, os.path.join(LIB, "mcp_report.py"), "exec"), mod.__dict__)
    return mod


class World:
    def __init__(self, mod, dirs=("athena-x",)):
        self.mod = mod
        self.root = os.path.join(_ROOT, f"w{len(os.listdir(_ROOT))}")
        self.state = os.path.join(self.root, "state")
        self.pantheon = os.path.join(self.root, "pantheon")
        self.home = os.path.join(self.root, "home")
        self.log = os.path.join(self.root, "calls.log")
        self.alerts, self.cleared = [], []
        self.folders = {}
        for d in dirs:
            os.makedirs(os.path.join(self.pantheon, "directions", d))
            f = os.path.join(self.root, "projects", d)
            os.makedirs(f)
            self.folders[d] = f
        os.makedirs(self.state)
        with open(os.path.join(self.state, "domains.json"), "w") as fh:
            json.dump({"domains": {d: [f] for d, f in self.folders.items()}}, fh)
        os.environ["FAKE_PT_LOG"] = self.log
        mod.set_core(types.SimpleNamespace(
            HOME=self.home, PANTHEON=self.pantheon, path=lambda *p: os.path.join(self.state, *p),
            read_json=self._read_json, write_json=self._write_json, tilde=lambda p: p,
            stamp=lambda t=None: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)),
            alert_once=lambda key, value, text, who="pantheon", **kw: self.alerts.append((key, text)),
            clear_once=self.cleared.append, project_tools_cmd=lambda: FAKE_CMD))

    @staticmethod
    def _read_json(p, default=None):
        try:
            with open(p) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {} if default is None else default

    @staticmethod
    def _write_json(p, data):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            json.dump(data, fh)

    def put(self, d, rel, text):
        p = os.path.join(self.folders[d], rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)

    def servers(self, d, rows, code=0, mcp=True):
        self.put(d, ".fake.json", json.dumps({"servers": rows, "code": code}))
        if mcp:   # .mcp.json с новым содержимым — вход проверки сменился
            self.put(d, ".mcp.json", json.dumps({"mcpServers": {r["name"]: {"type": r["kind"]} for r in rows},
                                                 "n": len(self.calls()) + len(self.inbox(d))}))

    def calls(self):
        return open(self.log).read().splitlines() if os.path.exists(self.log) else []

    def inbox(self, d="athena-x"):
        ib = os.path.join(self.pantheon, "directions", d, "inbox")
        return sorted(os.listdir(ib)) if os.path.isdir(ib) else []

    def text(self, name, d="athena-x"):
        return open(os.path.join(self.pantheon, "directions", d, "inbox", name), encoding="utf-8").read()

    def tick(self, t=T):
        return self.mod.tick(t)


# --- сценарии: каждый на своём мире, → (прошёл, подробности) --------------------------------------------------------

def s_new(mod):
    w = World(mod)
    w.servers("athena-x", [OK])
    out = w.tick()
    files = w.inbox()
    if len(files) != 1:
        return False, ("файлов", files, w.calls())
    body = w.text(files[0])
    tick_log = open(os.path.join(w.state, "logs", "tick.log")).read() if os.path.exists(
        os.path.join(w.state, "logs", "tick.log")) else ""
    ok = (w.calls() == [f"check --json --probe --dir {w.folders['athena-x']}"]
          and "+ ctx (http): подключается" in body and "\nОт: плановый проход" in body and "-mcp-" in files[0]
          and "zeus" not in files[0] and "zeus" not in body.lower().split("\n\n")[0]
          and out and "mcp-report: athena-x" in tick_log and "inbox/" + files[0] in tick_log)
    return ok, (w.calls(), body, out, tick_log)


def s_same(mod):
    w = World(mod)
    w.servers("athena-x", [OK])
    w.tick()
    n = len(w.calls())
    out = w.tick(T + 600)
    return len(w.calls()) == n and len(w.inbox()) == 1 and out is None, (w.calls(), w.inbox(), out)


def s_change_same_rows(mod):
    w = World(mod)
    w.servers("athena-x", [OK])
    w.tick()
    w.put("athena-x", ".mcp.json", '{"mcpServers": {"ctx": {"type": "http", "url": "https://b"}}}')
    w.tick(T + 600)
    return len(w.calls()) == 2 and len(w.inbox()) == 1, (w.calls(), w.inbox())


def s_change_rows(mod):
    w = World(mod)
    w.servers("athena-x", [OK])
    w.tick()
    w.servers("athena-x", [FAIL, AUTH])
    w.tick(T + 600)
    files = w.inbox()
    body = w.text(files[-1]) if len(files) == 2 else ""
    return (len(files) == 2 and "! ctx (http): не подключается" in body and "? sentry (http)" in body
            and "повторится сама" in body and "Authorize" in body), (files, body)


def s_inputs(mod):
    """Вход проверки — и настройки одобрения папки, и отпечатки project-tools на этом Mac."""
    w = World(mod)
    w.servers("athena-x", [OK])
    w.tick()
    seen = [len(w.calls())]
    for i, (base, rel) in enumerate(((w.folders["athena-x"], os.path.join(".claude", "settings.json")),
                                     (w.folders["athena-x"], os.path.join(".claude", "settings.local.json")),
                                     (w.home, os.path.join(".local", "state", "pantheon", "project-tools",
                                                           "approved.json"))), 1):
        p = os.path.join(base, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write('{"enabledMcpjsonServers": ["ctx"]}')
        w.tick(T + 600 * i)
        seen.append(len(w.calls()))
    return seen == [1, 2, 3, 4], seen


def s_retry_early(mod):
    w = World(mod)
    w.servers("athena-x", [FAIL])
    w.tick()
    w.tick(T + mod.RETRY - 1)
    return len(w.calls()) == 1, w.calls()


def s_retry(mod):
    w = World(mod)
    w.servers("athena-x", [FAIL])
    w.tick()
    w.servers("athena-x", [OK], mcp=False)
    w.tick(T + mod.RETRY)
    files = w.inbox()
    return (len(w.calls()) == 2 and len(files) == 2 and "+ ctx (http): подключается" in w.text(files[-1]),
            (w.calls(), files))


def s_retry_stops(mod):
    w = World(mod)
    w.servers("athena-x", [FAIL])
    w.tick()
    w.tick(T + mod.RETRY_FOR - 1)
    n = len(w.calls())
    w.tick(T + mod.RETRY_FOR + mod.RETRY)
    return n == 2 and len(w.calls()) == 2, w.calls()


def s_stdio_first(mod):
    w = World(mod)
    w.servers("athena-x", [STDIO])
    w.tick()
    quiet = len(w.calls()) == 1 and not w.inbox()
    w.servers("athena-x", [OK, STDIO])
    w.tick(T + 600)
    files = w.inbox()
    body = w.text(files[0]) if files else ""
    return quiet and len(files) == 1 and "· next (stdio)" in body and "/mcp" in body, (quiet, files, body)


def s_removed(mod):
    w = World(mod)
    w.servers("athena-x", [OK])
    w.tick()
    w.servers("athena-x", [])
    w.tick(T + 600)
    return len(w.calls()) == 2 and len(w.inbox()) == 1, (w.calls(), w.inbox())


def s_per_tick(mod):
    w = World(mod, dirs=("athena-x", "hermes-y"))
    w.servers("athena-x", [OK])
    w.servers("hermes-y", [OK])
    w.tick()
    first = len(w.calls())
    w.tick(T + 300)
    return (first == 1 and len(w.calls()) == 2 and len(w.inbox("athena-x")) == 1 and len(w.inbox("hermes-y")) == 1,
            (first, w.calls()))


def s_error(mod):
    w = World(mod)
    w.servers("athena-x", [OK], code=2)
    out = w.tick()
    failed = (not w.inbox() and [k for k, _ in w.alerts] == ["mcp-report-athena-x"] and out and "код 2" in out
              and not w.cleared)
    w.tick(T + 60)
    early = len(w.calls()) == 1
    w.servers("athena-x", [OK], mcp=False)
    w.tick(T + mod.RETRY)
    return (failed and early and len(w.calls()) == 2 and len(w.inbox()) == 1 and w.cleared == ["mcp-report-athena-x"],
            (failed, early, w.calls(), w.inbox(), w.alerts, w.cleared, out))


def s_symlink(mod):
    w = World(mod)
    outside = os.path.join(w.root, "outside")
    os.makedirs(outside)
    os.symlink(outside, os.path.join(w.pantheon, "directions", "athena-x", "inbox"))
    w.servers("athena-x", [OK])
    out = w.tick()
    return (not os.listdir(outside) and w.alerts and w.alerts[0][0] == "mcp-report-athena-x" and out
            and "не записан" in out), (os.listdir(outside), w.alerts, out)


def s_dryrun(mod):
    w = World(mod)
    w.servers("athena-x", [OK])
    os.environ["PANTHEON_DRYRUN"] = "1"
    try:
        out = w.tick()
    finally:
        del os.environ["PANTHEON_DRYRUN"]
    return out is None and not w.calls() and not w.inbox(), (out, w.calls())


def s_no_mcp(mod):
    w = World(mod)
    w.put("athena-x", ".fake.json", json.dumps({"servers": [OK]}))
    out = w.tick()
    return out is None and not w.calls() and not w.inbox(), (out, w.calls())


SCENARIOS = [
    ("[новый] HTTP-сервер → проба --json --probe, файл во входящих с итогом, шапка не Зевса, строка tick.log", s_new),
    ("[тот же] вход не сменился → ни пробы, ни файла", s_same),
    ("[тот же] вход сменился, итог тот же → проба без файла", s_change_same_rows),
    ("[тот же] итог другой → новый файл с ! и ?, советы по ним", s_change_rows),
    ("[тот же] вход — settings.json, settings.local.json, отпечатки project-tools", s_inputs),
    ("[повтор] fail — не раньше RETRY", s_retry_early),
    ("[повтор] fail → через RETRY проба, ok → новый файл", s_retry),
    ("[повтор] не дольше RETRY_FOR", s_retry_stops),
    ("[stdio] впервые одни stdio — без файла, затем HTTP — файл", s_stdio_first),
    ("[stdio] серверы убраны — без файла", s_removed),
    ("[за проход] не больше PER_TICK проб, вторая папка — следующим проходом", s_per_tick),
    ("[сбой] project-tools упал — тревога, без файла, повтор через RETRY, успех снимает тревогу", s_error),
    ("[сбой] inbox — ссылка → мимо не пишет, тревога", s_symlink),
    ("[сбой] PANTHEON_DRYRUN — ничего", s_dryrun),
    ("[сбой] без .mcp.json — пробы нет", s_no_mcp),
]


def run(fn, src=SRC):
    try:
        return fn(load(src))
    except Exception as e:  # noqa: BLE001 — мутант может уронить сценарий: это тоже «красный»
        return False, f"{type(e).__name__}: {e}"


for name, fn in SCENARIOS:
    ok, info = run(fn)
    check(name, ok, info)

core = open(os.path.join(LIB, "pantheon.py"), encoding="utf-8").read()
check("[проводка] release_ticks зовёт mcp_report_mod, загрузчик ставит ядро",
      '"итог проверки MCP координаторам", mcp_report_mod)' in core and "def mcp_report_mod():" in core
      and 'os.path.join(LIB, "mcp_report.py")' in core)

MUTANTS = [
    ("сверка входа", 'or rec.get("key") != key:', "or False:", s_change_rows),
    ("повтор не раньше RETRY", "t - probed >= RETRY and", "True and", s_retry_early),
    ("повтор не дольше RETRY_FOR", "and t - since < RETRY_FOR", "and True", s_retry_stops),
    ("тот же итог — без файла", 'if rows == new["reported"]:', "if False:", s_change_same_rows),
    ("первый раз одни stdio — без файла", 'new["reported"] is None and not any(', "False and not any(", s_stdio_first),
    ("серверы убраны — без файла", "if not rows or (", "if (", s_removed),
    ("PER_TICK", "or probes >= PER_TICK:", "or False:", s_per_tick),
    ("ссылка inbox", "if os.path.islink(ib) or (", "if (", s_symlink),
    ("вход — settings.local.json", ', os.path.join(".claude", "settings.local.json"))', ")", s_inputs),
    ("вход — отпечатки project-tools", '+ [("approved", _read(approved_file()))]', "", s_inputs),
    ("--probe", '"--json", "--probe",', '"--json",', s_new),
    ("снятие тревоги", "    P.clear_once(alert)\n", "", s_error),
    ("сбой проверки", "    if err:\n", "    if False:\n", s_error),
]
for name, old, new, fn in MUTANTS:
    mutant = SRC.replace(old, new, 1)
    ok, info = run(fn, mutant) if mutant != SRC else (True, "подмена не нашлась")
    check(f"[мутанты] {name}: откат краснит сценарий", mutant != SRC and not ok, info)

print(f"\n{len(CHECKS) - len(FAILS)}/{len(CHECKS)}")
sys.exit(1 if FAILS else 0)
