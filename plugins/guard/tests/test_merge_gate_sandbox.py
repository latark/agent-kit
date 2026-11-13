#!/usr/bin/env python3
"""Запор слияния guard, часть «sandbox»: ядро по сборке окон: песочница, списки запуска и сессий.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py; разрез metis-1119.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_sandbox.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403


# --- сборка окон в pantheon.py — ядро (metis-0404) ------------------------------------------------------------------
SB = "plugins/pantheon/lib/pantheon.py"
SB_SRC = '''import os
HOME = os.environ.get("HOME", "")
SANDBOX_DOMAINS = ["pypi.org"]
JOB_ROLES = {"iris": {"write": []}}


def role_settings(folders):
    return {"sandbox": {"domains": list(SANDBOX_DOMAINS), "write": folders}, "jobs": sorted(JOB_ROLES)}


def sandbox_build(domains):
    # окна направлений
    return {n: role_settings(f) for n, f in domains.items()}


def domains_build():
    return sandbox_build({"x": [HOME]})


def run_settings(name):
    return name


def task_cmd(argv):
    out = []
    out.append(len(argv))
    return out
'''
# head от базы: имя, замена (было → стало), ядро ли
SB_VARIANTS = (
    ("sb", ("return {n: role_settings(f)", "return {n: role_settings(f + ['/'])"), True),
    ("helper", ('"write": folders}', '"write": folders + ["/"]}'), True),
    ("const", ('["pypi.org"]', '["pypi.org", "evil.example"]'), True),
    ("mutate", ("    out = []\n", "    SANDBOX_DOMAINS.append('evil.example')\n    out = []\n"), True),
    ("glob", ("    out = []\n", "    global JOB_ROLES\n    JOB_ROLES = {}\n    out = []\n"), True),
    ("toplevel", ("\n\ndef role_settings", "\nJOB_ROLES.update(x={})\n\n\ndef role_settings"), True),
    ("caller", ('[HOME]})', '[HOME, "/"]})'), True),
    ("run", ("    return name\n", "    return name + '.json'\n"), True),
    ("rename", ("def sandbox_build(domains):", "def build_windows(domains):"), True),
    ("syntax", ("def task_cmd(argv):", "def task_cmd(argv:"), True),
    ("other", ("out.append(len(argv))", "out.append(len(argv) + 1)"), False),
    ("comment", ("    # окна направлений\n", "    # окна направлений, другой комментарий\n"), False),
    ("local", ("    out = []\n", "    out = []\n    out.extend([1])\n"), False),
    ("newfn", ("\n\ndef task_cmd", "\n\ndef board_cmd():\n    return 1\n\n\ndef task_cmd"), False),
)
# Б1 ревью argus-b PR #160: в base после ответвления PR слит соседний PR — sandbox_build стала звать task_cmd,
# а PR (вариант «other») правит task_cmd. На merge-base и head task_cmd вне сборки, на вершине base — внутри
SB_TIP = ("    return {n: role_settings(f) for n, f in domains.items()}",
          "    task_cmd([])\n    return {n: role_settings(f) for n, f in domains.items()}")
# metis-0951: запуск окна (придёт с PR #360) — корень сборки; на main его ещё нет, поэтому SB_SRC без него
WL_SRC = '''

def launch_args(name):
    return ["claude", "--settings", run_settings(name)]


def window_launch(name):
    return launch_args(name)
'''
WL_VARIANTS = (
    ("body", ("    return launch_args(name)\n", "    return launch_args(name) + ['--dangerously-skip-permissions']\n")),
    ("helper", ('["claude", "--settings"', '["claude", "--yolo", "--settings"')),
)


def t_core_sandbox_unit(h):
    """sandbox_build_changes напрямую: правка сборки окон и того, что она пишет, — имена; правка другой функции,
    комментарий — пусто; не разобрать или нет корня — None. И на настоящем pantheon.py репозитория."""
    mg = _load_merge_gate("merge_gate_sb")
    for name, (a, b), core in SB_VARIANTS:
        check(f"сборка окон: замена «{name}» есть в образце", a in SB_SRC)
        got = mg.sandbox_build_changes(SB_SRC, SB_SRC.replace(a, b, 1))
        check(f"сборка окон: {name} — {'ядро' if core else 'не ядро'}", (got is None or bool(got)) == core, got)
    check("сборка окон: имя правки — role_settings",
          mg.sandbox_build_changes(SB_SRC, SB_SRC.replace(*SB_VARIANTS[1][1])) == ["role_settings"])
    other, tip = SB_SRC.replace(*SB_VARIANTS[10][1]), SB_SRC.replace(*SB_TIP)
    check("сборка окон Б1: вызов есть в образце вершины", SB_TIP[0] in SB_SRC and SB_VARIANTS[10][0] == "other")
    check("сборка окон Б1: без вершины base правка task_cmd — не ядро", mg.sandbox_build_changes(SB_SRC, other) == [])
    check("сборка окон Б1: вершина base зовёт task_cmd, PR правит task_cmd — ядро",
          mg.sandbox_build_changes(SB_SRC, other, tip) == ["task_cmd"], mg.sandbox_build_changes(SB_SRC, other, tip))
    check("сборка окон Б1: вершина base без нового вызова — не ядро",
          mg.sandbox_build_changes(SB_SRC, other, SB_SRC) == [])
    check("сборка окон Б1: вершину base не разобрать — None",
          mg.sandbox_build_changes(SB_SRC, other, "def (") is None)
    # metis-0951: запуск окна window_launch — корень сборки; пока его нет в файле (SB_SRC), проверка идёт по остальным
    check("запуск окна: window_launch — в корнях сборки", "window_launch" in mg.SANDBOX_BUILD_ROOTS)
    check("запуск окна: файла без window_launch проверка не ломает (замыкание есть)", mg._defs_closure(SB_SRC) is not None)
    check("запуск окна: без обязательного корня run_settings — по-прежнему None (ядро)",
          mg._defs_closure(SB_SRC.replace("def run_settings(name):", "def run_cfg(name):")) is None)
    wl = SB_SRC + WL_SRC
    for name, (a, b) in WL_VARIANTS:
        check(f"запуск окна: замена «{name}» есть в образце", a in wl)
        got = mg.sandbox_build_changes(wl, wl.replace(a, b, 1))
        check(f"запуск окна: {name} — ядро", bool(got), got)
    check("запуск окна: правка тела — имя window_launch",
          mg.sandbox_build_changes(wl, wl.replace(*WL_VARIANTS[0][1], 1)) == ["window_launch"])
    check("запуск окна: появился в PR — ядро", mg.sandbox_build_changes(SB_SRC, wl) == ["launch_args", "window_launch"],
          mg.sandbox_build_changes(SB_SRC, wl))
    check("запуск окна: удалён в PR — ядро", bool(mg.sandbox_build_changes(wl, SB_SRC)))
    check("запуск окна: правка другой функции при window_launch в файле — не ядро",
          mg.sandbox_build_changes(wl, wl.replace(*SB_VARIANTS[10][1], 1)) == [])
    real_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(GUARD))), "pantheon", "lib", "pantheon.py")
    real = open(real_path, encoding="utf-8").read()
    got = mg._defs_closure(real)
    check("настоящий pantheon.py: разбирается, корни на месте", got is not None)
    seen = got[1] if got else set()
    want = {"sandbox_build", "role_settings", "agents_window", "JOB_ROLES", "SANDBOX_DOMAINS", "GH_PR_WRITE",
            "HESTIA_EXCLUDED", "COORDINATOR_AGENTS", "WINDOW_RULES", "run_settings", "domains_build"}
    check("настоящий pantheon.py: в сборке окон — role_settings, JOB_ROLES, SANDBOX_DOMAINS…", want <= seen,
          sorted(want - seen))
    check("настоящий pantheon.py: без правки — пусто", mg.sandbox_build_changes(real, real) == [])
    check("настоящий pantheon.py: новая функция в конце — не ядро",
          mg.sandbox_build_changes(real, real + "\n\ndef _metis_0404_probe():\n    return 1\n") == [])
    import ast
    tree = ast.parse(real)
    fn = next(st for st in tree.body if isinstance(st, ast.FunctionDef) and st.name == "role_settings")
    lines = real.splitlines(True)
    first = fn.body[0]
    indent = lines[first.lineno - 1][:first.col_offset]
    probe = "".join(lines[:first.lineno - 1] + [indent + "_probe = 1\n"] + lines[first.lineno - 1:])
    check("настоящий pantheon.py: правка role_settings — ядро",
          mg.sandbox_build_changes(real, probe) == ["role_settings"], mg.sandbox_build_changes(real, probe))


# metis-0411, 0552: запуск окон с --settings — корни с полным замыканием, как у сборки; сужения 0550 нет: имя модуля
# через import — данные, локальное имя тянет одноимённую функцию модуля, барьеров нет
LAUNCH_SRC = SB_SRC + """

def _resume_session(sid):
    return ["claude", "--resume", sid, "--settings", run_settings(sid)]


def parse_command(text):
    return task_cmd([text, "--settings"])


def alert_once(msg):
    return task_cmd([msg])
"""
SS_SRC = """import os
SESSIONS = {}


def _argv(name):
    return ["claude", "--name", name]


def _fresh_start(name):
    return _argv(name) + ["--settings", name + ".json"]


def _start_session(name):
    SESSIONS[name] = 1
    return ["claude", "--settings", name + ".json"]


def start(rest):
    return _start_session(rest)


def list_sessions():
    os.environ["PANTHEON_X"] = "1"
    return sorted(SESSIONS)
"""


def t_core_lists_unit(h):
    """Ядро — как текст роли «Ядро защит» (metis-0411): merge.py, window_rules.py, ctx.py (hq_policy) — файлы ядра;
    снятие --settings в запуске окон pantheon.py и sessions.py — ядро (0552); корни запуска идут с полным замыканием,
    без барьеров: правка того, что они зовут и читают, правка os в функции и функции с именем локальной переменной
    сборки — ядро, как на base 45f35bac (сужение 0550 вырезано)."""
    mg = _load_merge_gate("merge_gate_lists")
    sha = "a" * 40
    for path in ("plugins/pantheon/lib/merge.py", "plugins/pantheon/lib/window_rules.py",
                 "plugins/pantheon/hooks/ctx.py", "./plugins/pantheon//lib/../lib/merge.py"):
        mg._gh_json = lambda args, path=path: [{"filename": path, "status": "modified"}]
        why = mg._core_problem("latark/agent-kit", 7, sha, {"headRefOid": sha, "changedFiles": 1})
        check(f"ядро: PR правит {path} — ядро", why and mg.MERGE_CORE in why, why)
    # sessions.py — тот же путь шлюза, что pantheon.py: _sandbox_problem с path файла
    calls = []
    mg._sandbox_problem = lambda *a: calls.append(a[-1]) or f"{a[-1]}: start"
    mg._gh_json = lambda args: [{"filename": mg.SESSIONS_FILE, "status": "modified"}]
    why = mg._core_problem("latark/agent-kit", 7, sha, {"headRefOid": sha, "changedFiles": 1})
    check("запуск окон: PR правит sessions.py — сверка сборки по sessions.py", calls == [mg.SESSIONS_FILE], calls)
    check("запуск окон: правка запуска в sessions.py — ядро", why and "sessions.py: start" in why, why)
    mg = _load_merge_gate("merge_gate_lists2")
    # pantheon.py: _resume_session и parse_command — корни с замыканием
    for name, (a, b) in (("_resume_session", ('"--settings", run_settings(sid)]', 'run_settings(sid)]')),
                         ("parse_command", ('[text, "--settings"]', '[text]'))):
        check(f"запуск окон: замена в {name} есть в образце", a in LAUNCH_SRC)
        got = mg.sandbox_build_changes(LAUNCH_SRC, LAUNCH_SRC.replace(a, b, 1))
        check(f"запуск окон: снятие --settings в {name} — ядро", got == [name], got)
    got = mg.sandbox_build_changes(LAUNCH_SRC, LAUNCH_SRC.replace(*SB_VARIANTS[10][1], 1))
    check("запуск окон: правка task_cmd, которую зовёт parse_command, — ядро (замыкание)", got == ["task_cmd"], got)
    check("запуск окон: _resume_session удалён в PR — ядро",
          bool(mg.sandbox_build_changes(LAUNCH_SRC, LAUNCH_SRC.replace("def _resume_session(sid):", "def _rs(sid):"))))
    # барьеров нет: тревога alert_once в сборке — её правка ядро, правка того, что она зовёт, — тоже
    stop = LAUNCH_SRC.replace("def role_settings(folders):\n", "def role_settings(folders):\n    alert_once('x')\n") \
        + "\n\ndef _al_help(m):\n    return [m]\n"
    stop = stop.replace("    return task_cmd([msg])", "    return _al_help(msg)")
    got = mg.sandbox_build_changes(stop, stop.replace("    return _al_help(msg)", "    return _al_help(msg + '!')"))
    check("без барьера: правка alert_once из сборки — ядро", got == ["alert_once"], got)
    got = mg.sandbox_build_changes(stop, stop.replace("    return [m]\n", "    return [m, 1]\n"))
    check("без барьера: правка того, что зовёт только alert_once из сборки, — ядро", got == ["_al_help"], got)
    # как на base: os пришёл импортом и читается в сборке — правка os.environ в посторонней функции ядро
    osenv = ("    out = []\n", "    os.environ['PANTHEON_X'] = '1'\n    out = []\n")
    got = mg.sandbox_build_changes(SB_SRC, SB_SRC.replace(*osenv, 1))
    check("как на base: os.environ в посторонней функции — ядро", "task_cmd" in (got or []), got)
    # как на base: локальное имя check в сборке тянет функцию модуля check
    loc = SB_SRC.replace("    # окна направлений\n", "    # окна направлений\n    check = len(domains)\n") + \
        "\n\ndef check(x):\n    return x\n"
    got = mg.sandbox_build_changes(loc, loc.replace("    return x\n", "    return x + 1\n"))
    check("как на base: функция модуля с именем локальной переменной сборки — ядро", got == ["check"], got)
    glob = loc.replace("    check = len(domains)\n", "    check(len(domains))\n")
    got = mg.sandbox_build_changes(glob, glob.replace("    return x\n", "    return x + 1\n"))
    check("0550: та же функция, которую сборка зовёт, — ядро", got == ["check"], got)
    # sessions.py: корни _start_session, _fresh_start, start — с замыканием
    P = mg.SESSIONS_FILE
    for name, (a, b) in (("_fresh_start", (' + ["--settings", name + ".json"]', '')),
                         ("_start_session", ('["claude", "--settings", name + ".json"]', '["claude"]')),
                         ("start", ("return _start_session(rest)", "return _fresh_start(rest)"))):
        check(f"sessions.py: замена в {name} есть в образце", a in SS_SRC)
        got = mg.sandbox_build_changes(SS_SRC, SS_SRC.replace(a, b, 1), path=P)
        # _start_session меняет SESSIONS — его правка задевает и это имя данных
        check(f"sessions.py: правка запуска {name} — ядро", got and name in got, got)
    got = mg.sandbox_build_changes(SS_SRC, SS_SRC.replace('"PANTHEON_X"] = "1"', '"PANTHEON_X"] = "2"'), path=P)
    check("sessions.py: os.environ в функции, до которой запуск не доходит, — не ядро", got == [], got)
    got = mg.sandbox_build_changes(SS_SRC, SS_SRC.replace('"--name", name]', '"--name", name, "-v"]'), path=P)
    check("sessions.py: правка помощника _argv, которого зовёт _fresh_start, — ядро", got == ["_argv"], got)
    check("sessions.py: без корня start — None (ядро)",
          mg.sandbox_build_changes(SS_SRC, SS_SRC.replace("def start(rest):", "def begin(rest):"), path=P) is None)
    # настоящий sessions.py: снятие --settings в каждом из трёх запусков — ядро. С metis-0933 argv окна собирает
    # P.window_launch (pantheon.py): снять --settings в sessions.py — значит собрать argv в обход window_launch
    real_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(GUARD))), "pantheon", "lib", "sessions.py")
    real = open(real_path, encoding="utf-8").read()
    check("настоящий sessions.py: без правки — пусто", mg.sandbox_build_changes(real, real, path=P) == [])
    for name, a, b in (("_fresh_start", "P.window_launch(role, name, window, win, text)",
                        '[P.claude_bin(), "--bg", "--agent", role, "--name", name, text]'),
                       ("start", 'P.window_launch("hq", "zeus", None, P.path("settings", "hq.json"), bg=False)',
                        '[P.claude_bin(), "--agent", "hq", "--name", "zeus"]'),
                       ("_start_session", "P.window_launch(role, name, window, run, prompt)",
                        '[P.claude_bin(), "--bg", "--agent", role, "--name", name, prompt]')):
        check(f"настоящий sessions.py: запуск через window_launch в {name} есть", real.count(a) == 1)
        got = mg.sandbox_build_changes(real, real.replace(a, b, 1), path=P)
        check(f"настоящий sessions.py: снятие --settings в {name} — ядро", got == [name], got)
    # сам --settings — в window_launch (pantheon.py): его снятие там — ядро
    pan_path = os.path.join(os.path.dirname(real_path), "pantheon.py")
    pan = open(pan_path, encoding="utf-8").read()
    a = '*window_flags(window, name), "--settings", settings]'
    check("настоящий pantheon.py: --settings в window_launch есть", pan.count(a) == 1)
    got = mg.sandbox_build_changes(pan, pan.replace(a, "*window_flags(window, name)]", 1))
    check("настоящий pantheon.py: снятие --settings в window_launch — ядро", got == ["window_launch"], got)
    check("настоящий sessions.py: новая функция в конце — не ядро",
          mg.sandbox_build_changes(real, real + "\n\ndef _metis_0552_probe():\n    return 1\n", path=P) == [])
    # Б1 обоих argus PR #394: защиты запуска — мелкие корни; на base 45f35bac были ядром через os, после 0550 выпали
    got = mg.sandbox_build_changes(real, real.replace("    P.allow_gate(name)", "    pass", 1), path=P)
    check("настоящий sessions.py: fresh_target без allow_gate — ядро", got == ["fresh_target"], got)
    for name, a, b in (("CLAUDE_VALUE_FLAGS", '"--name"}', '"--name", "--permission-mode"}'),
                       ("ROLE_ENV", 'ROLE_ENV = ("PANTHEON_ROLE", ', "ROLE_ENV = (")):
        check(f"настоящий pantheon.py: {name} есть", pan.count(a) == 1)
        got = mg.sandbox_build_changes(pan, pan.replace(a, b, 1))
        check(f"настоящий pantheon.py: правка {name} — ядро", got == [name], got)
    # Б1 и Б2 argus R3-2 PR #394: данные, которые читают корни запуска, — ядро (замыкание, как на base 45f35bac)
    for name, a, b in (("NO_WINDOW", "\nNO_WINDOW = 3\n", "\nNO_WINDOW = 0\n"),
                       ("TICK_SUBCOMMANDS", 'TICK_SUBCOMMANDS = {"view", ', 'TICK_SUBCOMMANDS = {"merge", "view", ')):
        check(f"настоящий pantheon.py: {name} есть", pan.count(a) == 1)
        got = mg.sandbox_build_changes(pan, pan.replace(a, b, 1))
        check(f"настоящий pantheon.py: правка {name} — ядро", got == [name], got)
    for name in ("job_window_problem", "cwd_allow_problems", "claude_env", "start_target", "live_copies",
                 "stop_copies", "agents_all"):
        m = re.search(r'^def %s\(.*?\):\n(    """.*?"""\n)?' % name, pan, re.M | re.S)
        check(f"настоящий pantheon.py: def {name} есть", m is not None)
        if m:
            got = mg.sandbox_build_changes(pan, pan[:m.end()] + "    return None\n" + pan[m.end():])
            check(f"настоящий pantheon.py: {name} → return None — ядро", got == [name], got)
    # Б2 обоих argus R2 PR #394: окно direction_target, бинарь и окружение claude, помощники запуска из sessions.py —
    # на base 45f35bac ядро; claude_bin, run_env, clean_path, nvm_bin, installed_plugin_dir — через сборку (мелкий
    # корень не барьер), остальные — мелкие корни
    for name in ("direction_target", "claude_bin", "run_env", "clean_path", "nvm_bin", "installed_plugin_dir",
                 "window_missing", "no_window_reason", "rm_previous", "push_text", "lock"):
        m = re.search(r'^def %s\(.*?\):\n(    """.*?"""\n)?' % name, pan, re.M | re.S)
        check(f"настоящий pantheon.py: def {name} есть", m is not None)
        if m:
            got = mg.sandbox_build_changes(pan, pan[:m.end()] + "    return None\n" + pan[m.end():])
            check(f"настоящий pantheon.py: {name} → return None — ядро", got and name in got, got)
    for title, a, b, name in (
            ("окно мастерской workshop → hq", '"workshop", folder, "workshop",', '"workshop", folder, "hq",',
             "direction_target"),
            ("окно координатора → hq", '(target, "domain-coordinator", folder, target,', '(target, "hq", folder, "hq",',
             "direction_target"),
            ("PATH окна с /tmp первым", "    extra = [own_bin, ", '    extra = ["/tmp", own_bin, ', "run_env"),
            ("PANTHEON_ROLE в окружении окна", '    env["PANTHEON_PYTHON"] = sys.executable',
             '    env["PANTHEON_ROLE"] = "zeus"\n    env["PANTHEON_PYTHON"] = sys.executable', "run_env"),
            ("подмена бинаря claude", "def claude_bin():\n", 'def claude_bin():\n    return "/tmp/x/claude"\n',
             "claude_bin")):
        check(f"настоящий pantheon.py: замена «{title}» есть", pan.count(a) == 1)
        got = mg.sandbox_build_changes(pan, pan.replace(a, b, 1))
        check(f"настоящий pantheon.py: {title} — ядро", got == [name], got)
    # project_allow_stop — не барьер: то, что он зовёт из сборки, — в замыкании
    pas = LAUNCH_SRC.replace("def role_settings(folders):\n", "def role_settings(folders):\n    project_allow_stop('x')\n") \
        + "\n\ndef project_allow_stop(name):\n    return _pa_text(name)\n\n\ndef _pa_text(name):\n    return [name, 'pa']\n"
    got = mg.sandbox_build_changes(pas, pas.replace("[name, 'pa']", "[name, 'pa!']"))
    check("Б1: правка того, что зовёт project_allow_stop из сборки, — ядро", got == ["_pa_text"], got)
    # мелкие корни без вызова из сборки: своя правка — ядро, правка того, что они зовут, — тоже (замыкание)
    lc = LAUNCH_SRC + "".join(f"\n\ndef {n}(x):\n    return _lc_help(x, '{n}')\n"
                              for n in ("live_copies", "stop_copies", "agents_all")) + \
        "\n\ndef _lc_help(x, n):\n    return [x, n]\n"
    for n in ("live_copies", "stop_copies", "agents_all"):
        got = mg.sandbox_build_changes(lc, lc.replace(f"_lc_help(x, '{n}')", f"_lc_help(x, '{n}!')"))
        check(f"мелкий корень {n} вне сборки: его правка — ядро", got == [n], got)
    got = mg.sandbox_build_changes(lc, lc.replace("return [x, n]", "return [n, x]"))
    check("мелкие корни: правка того, что зовут live_copies/stop_copies/agents_all, — ядро", got == ["_lc_help"], got)
    # Б1 и Д2 argus R2-1 PR #394: мелкий корень, вызванный из сборки, — не барьер: правка его помощника — ядро
    lcb = lc.replace("def role_settings(folders):\n", "def role_settings(folders):\n    stop_copies('x')\n")
    got = mg.sandbox_build_changes(lcb, lcb.replace("return [x, n]", "return [n, x]"))
    check("мелкий корень stop_copies вызван из сборки: правка его помощника — ядро", got == ["_lc_help"], got)
    got = mg.sandbox_build_changes(SS_SRC, SS_SRC + "\n\ndef fresh_target(name):\n    return name\n", path=P)
    check("sessions.py: fresh_target появился — правка имени, ядро", got == ["fresh_target"], got)


def t_core_sandbox(h):
    """Шлюз: PR, который правит сборку окон в pantheon.py, — ядро, лид его не сливает; правка другой функции —
    проходит; сборку не проверить (не клон, нет коммита, переименование, другой регистр) — ядро; Touch ID — проходит."""
    p, kit = h.j("projects/agent-kit"), "projects/agent-kit"
    H = Hist(p)
    H.br("t-sb-base", h.sha["agent-kit"])
    base = H.put({SB: SB_SRC}, "база сборки окон")
    heads = {}
    for name, (a, b), _ in SB_VARIANTS:
        H.br("t-sb-" + name, base)
        heads[name] = H.put({SB: SB_SRC.replace(a, b, 1)}, name)
    H.br("t-sb-gone", base)
    heads["gone"] = H.put({SB: None}, "pantheon.py удалён, а gh пишет modified")
    H.br("t-sb-tip", base)
    tip = H.put({SB: SB_SRC.replace(*SB_TIP)}, "соседний PR: sandbox_build зовёт task_cmd (Б1)")
    H.br("t-sb-tip-other", base)
    tip_other = H.put({SB: SB_SRC.replace(*SB_VARIANTS[13][1])}, "соседний PR: новая функция вне сборки")
    git(p, "checkout", "-q", "-f", "main")
    git(p, "clean", "-qfdx")

    def case(title, name, allow, why="", files=None, sha=None, role="hephaestus-pantheon", agent_id="L1", cwd=None,
             cmd=None, tip_sha=None, vbase=None, bname="main"):
        sha = sha or heads[name]
        h.reset()
        h.gh(files or [SB], head=sha)
        h.view["agent-kit"].update(baseRefOid=vbase or base, baseRefName=bname)
        if tip_sha:
            h.tip["agent-kit"] = tip_sha
        h.write_view("agent-kit")
        h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"), rec("accept", "latark/agent-kit", 7, sha))
        got = h.pre(cmd or f"gh pr merge 7 --match-head-commit {sha}", role=role, agent_id=agent_id, pdir=kit, cwd=cwd)
        merge_case(title, got, allow, why)
        return got

    for name, _, core in SB_VARIANTS:
        case(f"сборка окон, лид: {name} — {'отказ (ядро)' if core else 'проходит'}", name, not core,
             CORE + ": PR задевает " + SB)
    case("сборка окон, координатор: правка sandbox_build — отказ", "sb", False, CORE + ": PR задевает " + SB,
         role="domain-coordinator", agent_id=None)
    case("window_rules.py — ядро, как и раньше", "other", False, CORE + ": PR задевает plugins/pantheon/lib/window_rules.py",
         files=["plugins/pantheon/lib/window_rules.py"])
    case("сборка окон: слияние -R не из клона — не проверить, отказ", "other", False, "сборку окон не проверить",
         cwd="projects/tg-read", cmd=f"gh pr merge 7 -R latark/agent-kit --match-head-commit {heads['other']}")
    case("сборка окон: коммита head нет в git — отказ, подсказка git fetch", "other", False, "git fetch", sha="e" * 40)
    case("сборка окон: переименование в pantheon.py — отказ", "other", False, "переименован",
         files=[{"filename": SB, "status": "renamed", "previous_filename": "plugins/pantheon/lib/old.py"}])
    case("сборка окон: файла нет в head, хотя gh пишет modified — отказ", "gone", False, "файла нет до или после")
    case("сборка окон: путь в другом регистре — отказ", "other", False, "в другом регистре",
         files=["plugins/Pantheon/lib/pantheon.py"])
    # Б1 (argus-b PR #160): вершина base ушла вперёд, соседний PR добавил в sandbox_build вызов task_cmd
    case("сборка окон Б1: baseRefOid — merge-base, вершина base зовёт task_cmd, PR правит task_cmd — отказ (ядро)",
         "other", False, "сборка окон: task_cmd", tip_sha=tip)
    case("сборка окон Б1: baseRefOid и вершина — коммит с вызовом task_cmd, PR правит task_cmd — отказ (ядро)",
         "other", False, "сборка окон: task_cmd", vbase=tip)
    case("сборка окон Б1: вершина base с правкой вне сборки — правка task_cmd проходит", "other", True,
         tip_sha=tip_other)
    case("сборка окон Б1: gh не дал вершину base — отказ", "other", False, "не получить от gh", tip_sha="fail")
    case("сборка окон Б1: вершины base нет в git папки — отказ, подсказка git fetch", "other", False,
         "вершины base dddddddddddd нет в git папки", tip_sha="d" * 40)
    case("сборка окон Б1: имя ветки base не по формату — отказ", "other", False, "не получить от gh", bname="../x")
    # metis-0974: «принять» на другом коммите с тем же кодом — вершину base берут и перенос «принять», и сборка
    # окон; у gh она спрашивается один раз на шлюз
    H.br("t-sb-other-again", base)
    again = H.put({SB: SB_SRC.replace(*dict((n, ab) for n, ab, _ in SB_VARIANTS)["other"], 1)}, "other ещё раз")
    git(p, "checkout", "-q", "-f", "main")
    git(p, "clean", "-qfdx")
    for tip_sha, allow in ((tip_other, True), ("fail", False)):
        h.reset()
        h.gh([SB], head=heads["other"])
        h.view["agent-kit"].update(baseRefOid=base, baseRefName="main")
        h.tip["agent-kit"] = tip_sha
        h.write_view("agent-kit")
        h.seed(rec("tests", "latark/agent-kit", None, heads["other"], "dev-opus"),
               rec("accept", "latark/agent-kit", 7, again))
        got = h.pre(f"gh pr merge 7 --match-head-commit {heads['other']}", role="hephaestus-pantheon",
                    agent_id="L1", pdir=kit)
        merge_case(f"0974: «принять» перенесено, вершина base {'есть' if allow else 'сбой gh'} — "
                   f"{'проходит' if allow else 'отказ'}", got, allow, "" if allow else "не получить от gh")
        log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
        check(f"0974: вершина base ({tip_sha[:8]}) — один запрос gh на шлюз", log.count("/git/ref/heads/") == 1, log)
    h.reset()
    h.approve(f"{ts()} merge-approve latark/agent-kit#7 {heads['sb']}")
    h.gh([SB], head=heads["sb"])
    h.view["agent-kit"]["baseRefOid"] = base
    h.write_view("agent-kit")
    h.seed(rec("tests", "latark/agent-kit", None, heads["sb"], "dev-opus"),
           rec("accept", "latark/agent-kit", 7, heads["sb"]))
    merge_case("сборка окон: строка Touch ID владельца — проходит",
               h.pre(f"gh pr merge 7 --match-head-commit {heads['sb']}", role="hephaestus-pantheon", agent_id="L1",
                     pdir=kit), True)


CASES = [t_core_sandbox_unit, t_core_lists_unit, t_core_sandbox]


if __name__ == "__main__":
    sys.exit(main(CASES))
