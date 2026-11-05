#!/usr/bin/env python3
"""Дозапуск после красного полного набора (metis-0735, lib/outside.py: rerun_plan, run_failed, журнал full.jsonl).

Запуск: python3 -I plugins/pantheon/tests/test_outside_rerun.py  (код выхода 0 — все прошли)
Временный репозиторий с настоящим run-tests.py (копия из scripts/, лежит в tools/ — вне FULL раннера, так что правку
раннера и карты ловит именно проверка дозапуска), пять файлов тестов и карта affected-map.json. sandbox-exec подменён
заглушкой, которая пишет команду и исполняет её. Проверяет: красный полный прогон пишет список упавших в full.jsonl
(не в журнал шлюза); следующий HEAD той же ветки гонит `--only` упавших и затронутых диффом; опора — полный прогон, а не
дозапуск; зелёный дозапуск пишет запись tests с cmd полного набора и rerun_of/files/map, шлюз guard её читает; каждое
условие «весь набор вместо дозапуска»; разбор вывода run-tests (run_failed); причина красного по файлу в full.jsonl
(run_causes) и тревога, если красных полных прогонов за сутки больше 30 % (red_share, alert_red_share; metis-0696).
"""
import atexit
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import subprocess as _sp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311  # noqa: E402,F401  pantheon.py — только на Python 3.11+

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="outside-rerun-"))
tempfile.tempdir = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIBDIR = os.path.join(os.path.dirname(HERE), "lib")
RUNNER = os.path.join(os.path.dirname(HERE), "scripts", "run-tests.py")
GUARD_HOOKS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "hooks")
HOME = os.path.join(_ROOT, "home")
STATE = os.path.join(HOME, ".local", "state", "pantheon")
os.makedirs(STATE)
os.makedirs(os.path.join(HOME, "ai", "pantheon"))
for k in [k for k in os.environ if k.startswith(("PANTHEON_", "GIT_", "CLAUDE"))]:
    os.environ.pop(k)
os.environ.update({"HOME": HOME, "PANTHEON_STATE": STATE, "PANTHEON_HOME": os.path.join(HOME, "ai", "pantheon"),
                   "PANTHEON_NO_NOTIFY": "1", "PANTHEON_TEST": "1", "TMPDIR": _ROOT})
sys.path.insert(0, LIBDIR)
import pantheon as P  # noqa: E402
O = P.outside_mod()

FAILS, TOTAL = [], [0]


def check(name, cond, extra=""):
    TOTAL[0] += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{str(extra)[-800:]}]"))
    if not cond:
        FAILS.append(name)


# заглушка sandbox-exec: пишет команду и исполняет её
REC = os.path.join(_ROOT, "calls.jsonl")
FAKE = os.path.join(_ROOT, "fake-sandbox-exec")
with open(FAKE, "w") as fh:
    fh.write(f"#!{sys.executable}\nimport json, os, sys\ncmd = sys.argv[3:]\n"
             f"with open({REC!r}, 'a') as fh:\n    fh.write(json.dumps(cmd) + '\\n')\nos.execvp(cmd[0], cmd)\n")
os.chmod(FAKE, 0o755)
O.SANDBOX_EXEC = FAKE
O.HEAVY = None


def last_cmd():
    with open(REC) as fh:
        return json.loads(fh.read().splitlines()[-1])


def ncalls():
    try:
        with open(REC) as fh:
            return len(fh.read().splitlines())
    except OSError:
        return 0


def git(*args, d=None):
    r = subprocess.run(["git", "-C", d or RK, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        *args], capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def put(files):
    for name, text in files.items():
        p = os.path.join(RK, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)


def commit(files, msg):
    put(files)
    git("add", "-A")
    git("commit", "-q", "-m", msg)
    return git("rev-parse", "HEAD")


RK = os.path.join(HOME, "projects", "rk")
os.makedirs(RK)
git("init", "-q", "-b", "feat")
git("remote", "add", "origin", "git@github.com:latark/rk.git")
NAMES = "abcde"
LABELS = [f"kit/test_{x}.py" for x in NAMES]
TEST_SRC = ("import sys\nv = open('lib/{x}.txt').read().strip()\n"
            "if v.startswith('good'):\n    print('ok   {x}')\n    print('1 из 1')\n"
            "else:\n    print('FAIL {x}')\n    print('0 из 1')\n    sys.exit(1)\n")
with open(RUNNER) as fh:
    RUNNER_SRC = fh.read()
LINE = f"{sys.executable} -I tools/run-tests.py -j 2 plugins/kit"
files = {f"plugins/kit/tests/test_{x}.py": TEST_SRC.format(x=x) for x in NAMES}
files.update({f"plugins/kit/lib/{x}.txt": "good\n" for x in NAMES})
files.update({"tools/run-tests.py": RUNNER_SRC, "plugins/kit/tests/_h.py": "# общий модуль тестов\n",
              "plugins/kit/bin/heavy": "#!/bin/sh\nexec \"$@\"\n", "README.md": "rk\n",
              ".pantheon-verify": f"# полный набор\nheavy {LINE}\n"})


def make_map():
    """Карта как у affected-map.py: связи файлов с тестами и sha256 каждого файла тестов. heavy, _h.py, раннер и
    .pantheon-verify в ней есть — дозапуск по одной карте их бы пропустил; их ловит своя проверка."""
    def h(x):
        with open(os.path.join(RK, "plugins", "kit", "tests", f"test_{x}.py"), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    fl = {f"plugins/kit/lib/{x}.txt": [i] for i, x in enumerate(NAMES)}
    fl.update({"plugins/kit/bin/heavy": [0], "plugins/kit/tests/_h.py": [0], "tools/run-tests.py": [],
               "tools/affected-map.json": [], ".pantheon-verify": [], "README.md": []})
    return json.dumps({"version": 3, "head": "x", "python": "3", "tests": LABELS, "broken": [],
                       "hashes": {lb: h(x) for lb, x in zip(LABELS, NAMES)}, "files": fl}, indent=1)


put(files)
files["tools/affected-map.json"] = make_map()
files["plugins/kit/lib/a.txt"] = "bad\n"
C1 = commit(files, "c1: a красный")
P.merge_mod().FULL_TESTS["rk"] = f"heavy {LINE}"
REPOS = ["latark/rk"]
N = [0]


def run():
    N[0] += 1
    rid = f"20261103-{N[0]:06d}-abcdef"
    return O.run_test(rid, RK, None, "metis-r", None, [RK])


def full_log():
    return O.read_full()


def gate_records():
    code = ("import sys, json; sys.path.insert(0, %r); import guard_rules, merge_gate as m; "
            "print(json.dumps(m.read_records()))" % GUARD_HOOKS)
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                       env={"HOME": HOME, "PATH": os.environ["PATH"]})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def tests_for(sha):
    return [r for r in gate_records() if r["kind"] == "tests" and r["sha"] == sha]


def plan():
    argv, line = O.command(RK, "test")
    return O.rerun_plan(RK, git("rev-parse", "HEAD"), argv, line, O.remotes(RK))


# --- 1. красный полный прогон: список упавших — в full.jsonl, записи шлюза нет --------------------------------------
n0 = ncalls()
r1 = run()
R1 = r1.get("id")
e1 = full_log()[-1] if full_log() else {}
check("красный полный: весь набор (без --only), причина — нет прошлого прогона ветки",
      r1.get("code") == 1 and ncalls() == n0 + 1 and "--only" not in last_cmd()[-1]
      and "ещё нет полного прогона" in r1.get("full_why", ""), (r1, last_cmd()))
check("красный полный: строка full.jsonl — упавший kit/test_a.py, ветка, код, без rerun_of",
      e1.get("rid") == R1 and e1.get("failed") == ["kit/test_a.py"] and e1.get("branch") == "feat"
      and e1.get("code") == 1 and e1.get("sha") == C1 and "rerun_of" not in e1 and e1.get("cmd") == r1.get("cmd")
      and e1.get("env") == O.run_env(r1["cmd"]) and e1.get("tree") == git("rev-parse", f"{C1}^{{tree}}"), e1)
check("красный полный: в журнал шлюза не пишется", not tests_for(C1))
check("красный полный: причина по файлу в full.jsonl — провал, «код 1», первая строка не ok (metis-0696)",
      e1.get("causes") == {"kit/test_a.py": {"kind": "провал", "why": "код 1", "line": "FAIL a"}}
      and "cause" not in e1, e1.get("causes"))
with open(r1["log"]) as fh:
    LOG1 = fh.read()
check("run_failed: настоящий вывод run-tests — ok b–e, FAIL a",
      O.run_failed(LOG1) == (LABELS[1:], LABELS[:1]), O.run_failed(LOG1))

# --- 2. красный дозапуск: упавшие и затронутые, опорой он не станет ---------------------------------------------------
C2 = commit({"plugins/kit/lib/b.txt": "good2\n"}, "c2: b правка, a ещё красный")
n0 = ncalls()
r2 = run()
e2 = full_log()[-1]
check("дозапуск: --only упавших (a) и затронутых диффом (b), rerun_of — красный полный",
      r2.get("rerun_of") == R1 and r2.get("files") == LABELS[:2] and ncalls() == n0 + 1
      and last_cmd()[-1].endswith(" --only kit/test_a.py,kit/test_b.py") and r2.get("code") == 1
      and not r2.get("record"), (r2, last_cmd()))
check("красный дозапуск: в full.jsonl с rerun_of и своим списком упавших; записи шлюза нет",
      e2.get("rerun_of") == R1 and e2.get("failed") == ["kit/test_a.py"] and e2.get("files") == LABELS[:2]
      and not tests_for(C2), e2)

# --- 3. зелёный дозапуск: опора — полный R1, а не дозапуск; запись шлюза с rerun_of/files/map ----------------------
C3 = commit({"plugins/kit/lib/a.txt": "good\n"}, "c3: a починен")
n0 = ncalls()
r3 = run()
rec3 = tests_for(C3)
with open(os.path.join(RK, "tools", "affected-map.json"), "rb") as fh:
    MAPH = hashlib.sha256(fh.read()).hexdigest()
check("не цепочкой: опора — полный R1 (дифф от C1: b тоже), а не красный дозапуск C2",
      r3.get("rerun_of") == R1 and r3.get("files") == LABELS[:2], r3)
check("зелёный дозапуск: код 0, запись tests, один прогон с --only",
      r3.get("code") == 0 and r3.get("record") and ncalls() == n0 + 1 and "--only" in last_cmd()[-1], r3)
check("запись шлюза: cmd полного набора, rerun_of, files, map = sha256 карты HEAD, tree и env",
      len(rec3) == 1 and rec3[0]["cmd"] == r3["cmd"] and rec3[0].get("rerun_of") == R1
      and rec3[0].get("files") == LABELS[:2] and rec3[0].get("map") == MAPH
      and rec3[0].get("tree") == git("rev-parse", f"{C3}^{{tree}}") and rec3[0]["by"]["agent_type"] == "pantheon-outside",
      rec3)
check("запись шлюза — полный набор глазами full_tests_record", P.merge_mod().full_tests_record("latark/rk", rec3[0]))
out = io.StringIO()
with contextlib.redirect_stdout(out):
    O.show(r3)
check("status: строка дозапуска с файлами", f"дозапуск после красного полного набора {R1}" in out.getvalue(),
      out.getvalue())

# --- 3б. Д1: перенос по дереву сохраняет поля дозапуска ----------------------------------------------------------
C3B = git("commit-tree", f"{C3}^{{tree}}", "-p", C3, "-m", "c3b: то же дерево")
git("reset", "-q", "--hard", C3B)
n0 = ncalls()
r3b = run()
rec3b = tests_for(C3B)
check("перенос по дереву: без прогона, запись на новом коммите — дозапуск (rerun_of, files, map)",
      r3b.get("by_tree") == C3 and ncalls() == n0 and len(rec3b) == 1 and rec3b[0].get("rerun_of") == R1
      and rec3b[0].get("files") == LABELS[:2] and rec3b[0].get("map") == MAPH and rec3b[0].get("by_tree") == C3,
      (r3b, rec3b))

# --- 3в. Б1: хвост-комментарий в строке проверки не прячет --only -------------------------------------------------
C3C = commit({"plugins/kit/lib/c.txt": "good3c\n"}, "c3c: c правка")
_cmd = O.command
O.command = lambda d, kind, script=None: (lambda a: (a[0][:2] + [a[0][2] + " # коммент"], a[1]) if a[0] else a)(
    _cmd(d, kind, script))
n0 = ncalls()
r3c = run()
O.command = _cmd
rec3c = tests_for(C3C)
check("хвост « # коммент» в строке: ключ --only вне комментария, гонится только план, запись tests есть",
      r3c.get("rerun_of") == R1 and r3c.get("code") == 0 and r3c.get("record") and ncalls() == n0 + 1
      and "# коммент" not in last_cmd()[-1] and last_cmd()[-1].endswith(" --only kit/test_a.py,kit/test_b.py,kit/test_c.py")
      and len(rec3c) == 1 and rec3c[0].get("rerun_of") == R1, (r3c, last_cmd(), rec3c))
git("reset", "-q", "--hard", C3)

# --- 4. вывод дозапуска не сошёлся со списком файлов — записи нет ---------------------------------------------------
C4 = commit({"plugins/kit/lib/c.txt": "good3\n"}, "c4: c правка")
_rf = O.run_failed
O.run_failed = lambda text: (lambda g: g and (g[0] + ["kit/test_zz.py"], g[1]))(_rf(text))
r4 = run()
O.run_failed = _rf
check("дозапуск зелёный, но строки ok — не ровно его файлы: записи tests нет, причина",
      r4.get("rerun_of") == R1 and r4.get("code") == 0 and not r4.get("record") and "не сошёлся" in r4.get("why", "")
      and not tests_for(C4), r4)
p4, why = plan()
check("опора та же после зелёного дозапуска: R1, дифф от C1 — a, b, c",
      p4 and p4["rerun_of"] == R1 and p4["files"] == LABELS[:3] and p4["ancestor"] is True, (p4, why))

# --- 4б. Д2: код 0, а итога run-tests в выводе нет — записи нет ---------------------------------------------------
C4B = commit({"plugins/kit/lib/d.txt": "good5\n"}, "c4b: d правка")
_rf = O.run_failed
O.run_failed = lambda text: None
r4b = run()
O.run_failed = _rf
check("дозапуск, код 0, вывод без итога (run_failed None): записи tests нет, причина",
      r4b.get("rerun_of") == R1 and r4b.get("code") == 0 and not r4b.get("record") and "не сошёлся" in r4b.get("why", "")
      and not tests_for(C4B), r4b)

# --- 4в. Д3: команда изменила HEAD / дерево, или таймаут — строки в full.jsonl и записи нет ----------------------------
_hs, _wp = O.head_state, O.wait_proc
FLAG = []


def fake_wait(proc, timeout, tick=None, **kw):
    FLAG.append(1)
    if FAKE_MODE[0] == "timeout":
        raise _sp.TimeoutExpired("x", 1)
    return _wp(proc, timeout, tick, **kw)


def fake_head(d):
    s, c = _hs(d)
    if not FLAG:
        return s, c
    return {"sha": ("0" * 40, c), "dirty": (s, False)}.get(FAKE_MODE[0], (s, c))


FAKE_MODE = ["sha"]
for mode in ("sha", "dirty", "timeout"):
    git("reset", "-q", "--hard", C4B)
    C4X = commit({"plugins/kit/lib/e.txt": f"good-{mode}\n"}, f"c4x: {mode}")
    FLAG.clear()
    FAKE_MODE[0] = mode
    O.wait_proc = fake_wait
    O.head_state = fake_head
    nfull = len(full_log())
    rx = run()
    O.head_state, O.wait_proc = _hs, _wp
    check(f"{mode}: в full.jsonl строки нет, записи tests нет", len(full_log()) == nfull and not tests_for(C4X)
          and not rx.get("record"), (rx, len(full_log()), nfull))
    check(f"{mode}: причина в итоге", ("дольше" if mode == "timeout" else "изменила HEAD") in rx.get("why", ""), rx)
git("reset", "-q", "--hard", C4)

# --- 5. весь набор вместо дозапуска: каждое условие ----------------------------------------------------------------


def cond(label, files, need, extra_git=None):
    put(files)
    git("add", "-A")
    git("commit", "-q", "-m", label)
    p, why = plan()
    check(f"весь набор: {label}", p is None and need in (why or ""), (p, why))
    git("reset", "-q", "--hard", C4)


cond("дифф задевает файл вне карты", {"plugins/kit/lib/new.txt": "x"}, "нет в карте")
cond("дифф задевает раннер", {"tools/run-tests.py": RUNNER_SRC + "# правка\n"}, "дифф задевает tools/run-tests.py")
cond("дифф задевает карту", {"tools/affected-map.json": make_map() + "\n"}, "дифф задевает tools/affected-map.json")
cond("дифф задевает bin/heavy", {"plugins/kit/bin/heavy": "#!/bin/sh\nexit 0\n"}, "дифф задевает plugins/kit/bin/heavy")
cond("дифф задевает tests/_*.py", {"plugins/kit/tests/_h.py": "X = 1\n"}, "дифф задевает plugins/kit/tests/_h.py")
cond("дифф задевает .pantheon-verify", {".pantheon-verify": f"# полный набор, правка\nheavy {LINE}\n"},
     "дифф задевает .pantheon-verify")
cond("карта устарела (файл тестов изменён после сборки)",
     {"plugins/kit/tests/test_d.py": TEST_SRC.format(x="d") + "# правка\n"}, "карта устарела: 1")

# опора с другими свойствами: подложить строку full.jsonl последней на ветке, затем вернуть журнал
with open(O.full_file()) as fh:
    FULL0 = fh.read()


def with_prev(label, need, **kw):
    e = {k: v for k, v in e1.items() if k not in ("v", "time")}
    e.update(kw)
    O.append_full(e)
    p, why = plan()
    with open(O.full_file(), "w") as fh:
        fh.write(FULL0)
    if need is None:
        check(f"дозапуск: {label}", p is not None and why is None, (p, why))
        return p
    check(f"весь набор: {label}", p is None and need in (why or ""), (p, why))
    return None


with_prev("последний полный прогон ветки зелёный", "зелёный", code=0, failed=[])
with_prev("у опоры другая команда", "другая команда или env", cmd="python3 t.py")
with_prev("у опоры другой env (python)", "другая команда или env", env={**e1["env"], "python": "/other/python3.15"})
with_prev("в опоре нет списка упавших (старая запись, итог не разобран)", "нет списка упавших", failed=None)
with_prev("в опоре пустой список упавших при красном коде", "нет списка упавших", failed=[])
with_prev("коммита опоры нет в клоне", "нет в клоне", sha="1" * 40)
with_prev("упавших больше половины (3 из 5)", "больше половины", failed=LABELS[:3])
pb = with_prev("упавших ровно 2 из 5 — не больше половины (опора на HEAD, дифф пуст)", None, failed=LABELS[3:], sha=C4)
check("дозапуск 2 из 5: только упавшие d, e", pb and pb["files"] == LABELS[3:], pb)
with_prev("дозапуск — весь набор (упавшие d, e и затронутые a, b, c)", "весь набор", failed=LABELS[3:])
with_prev("упавшие удалены, дифф пуст — дозапускать нечего", "дозапускать нечего", failed=["kit/test_zz.py"], sha=C4)
pr = with_prev("последняя строка ветки — дозапуск (rerun_of): опора — полный R1 до неё", None, rid="inj-rerun",
               rerun_of="x", failed=LABELS[1:2], sha=C4)
check("опора не дозапуск: rerun_of R1, дифф от C1 (a, b, c)", pr and pr["rerun_of"] == R1 and pr["files"] == LABELS[:3],
      pr)

pO = with_prev("строка другого репозитория на той же ветке опорой не становится", None, rid="inj-other",
               repo=["latark/other"], failed=LABELS[3:], sha=C4)
check("опора — R1, а не строка чужого repo", pO and pO["rerun_of"] == R1 and pO["files"] == LABELS[:3], pO)
STAMP = "%Y-%m-%dT%H:%M:%S%z"
with_prev("опоре больше суток", "больше 24 ч", rid="inj-old", failed=LABELS[3:], sha=C4,
          time=time.strftime(STAMP, time.localtime(time.time() - 25 * 3600)))
with_prev("время опоры не разобрать", "время не разобрать", rid="inj-bad", failed=LABELS[3:], sha=C4, time="вчера")
with_prev("опоре 23 часа — дозапуск", None, rid="inj-fresh", failed=LABELS[3:], sha=C4,
          time=time.strftime(STAMP, time.localtime(time.time() - 23 * 3600)))

git("checkout", "-q", "--detach")
p, why = plan()
check("весь набор: HEAD без ветки", p is None and "без ветки" in (why or ""), (p, why))
git("checkout", "-q", "-b", "other")
p, why = plan()
check("весь набор: на другой ветке нет полного прогона", p is None and "ещё нет полного прогона" in (why or ""), (p, why))

# run-tests.py в HEAD без --only: опора на том же коммите (дифф пуст)
C5 = commit({"tools/run-tests.py": RUNNER_SRC.replace("--only", "--xonly")}, "старый раннер")
O.append_full({**{k: v for k, v in e1.items() if k not in ("v", "time")}, "branch": "other", "sha": C5})
p, why = plan()
check("весь набор: run-tests.py в HEAD не знает --only", p is None and "не знает --only" in (why or ""), (p, why))

# прошлый head не предок нового (rebase): дифф двух коммитов как есть
git("checkout", "-q", "-b", "rb", C1)
C6 = commit({"plugins/kit/lib/e.txt": "good4\n"}, "rb: e правка поверх C1")
O.append_full({**{k: v for k, v in e1.items() if k not in ("v", "time")}, "branch": "rb", "sha": C3})
p, why = plan()
check("прошлый head не предок: дозапуск, дифф C3→C6 как есть (a, b, e), ancestor False",
      p and p["ancestor"] is False and p["files"] == ["kit/test_a.py", "kit/test_b.py", "kit/test_e.py"], (p, why))
r6 = run()
check("прошлый head не предок: дозапуск идёт, в итоге пометка", r6.get("rerun_of") == R1 and "не предок" in
      r6.get("note", "") and r6.get("code") == 1, r6)   # a на C1 красный — дозапуск честно красный

# сбой расчёта — весь набор, а не отказ
_rm = O.runner_mod
O.runner_mod = lambda: (_ for _ in ()).throw(RuntimeError("карта сломалась"))
git("checkout", "-q", "feat")
git("reset", "-q", "--hard", C4)
r7 = run()
O.runner_mod = _rm
check("сбой расчёта дозапуска — весь набор с причиной",
      "--only" not in last_cmd()[-1] and "дозапуск не рассчитан" in r7.get("full_why", "") and r7.get("code") == 0
      and r7.get("record"), r7)
check("зелёный полный прогон — в full.jsonl с пустым списком упавших; следующий — весь набор (опора зелёная)",
      full_log()[-1].get("failed") == [] and full_log()[-1].get("code") == 0
      and "зелёный" in (plan()[1] or ""), full_log()[-1])

# команда не run-tests.py — весь набор
p, why = O.rerun_plan(RK, C4, ["/bin/sh", "-c", "python3 t.py"], "python3 t.py", REPOS)
check("весь набор: команда — не run-tests.py", p is None and "не run-tests.py" in why, why)
for bad in ("x -I tools/run-tests.py --affected plugins/kit", "x tools/run-tests.py", "x /abs/run-tests.py plugins/kit",
            "x tools/run-tests.py ../kit", "x tools/run-tests.py -j"):
    check(f"runner_args: «{bad}» — None", O.runner_args(bad) is None, O.runner_args(bad))
check("runner_args: папки и ключи с значением", O.runner_args(LINE) == ("tools/run-tests.py", ["plugins/kit"]))

# --- 6. run_failed: разбор вывода -------------------------------------------------------------------------------------
GOOD = ("run-tests: 2 файлов\nok   kit/test_a.py · 0.1 с · проверок 1\nFAIL kit/test_b.py · 0.1 с · проверок 1 · код 1\n"
        "\n===== kit/test_b.py · код 1 · последние 3 строк =====\nok   kit/test_x.py · 1 с\nFAIL kit/test_y.py · 1 с\n"
        "итого: файлов 9, ok 9, FAIL 0\n\nмедленные: …\nитого: файлов 2, ok 1, FAIL 1; проверок 2; 0 с, воркеров 1\n")
check("run_failed: строки ok/FAIL из хвоста упавшего не в счёт", O.run_failed(GOOD) == (["kit/test_a.py"],
                                                                                      ["kit/test_b.py"]),
      O.run_failed(GOOD))
check("run_failed: нет итога (прерван) — None", O.run_failed(GOOD.rsplit("итого", 1)[0]) is None)
check("run_failed: итог не последней строкой — None", O.run_failed(GOOD + "heavy: ещё строка\n") is None)
check("run_failed: числа итога не сошлись со строками — None",
      O.run_failed(GOOD.replace("файлов 2, ok 1, FAIL 1", "файлов 3, ok 2, FAIL 1")) is None)
check("run_failed: файлов в итоге больше, чем ok + FAIL — None",
      O.run_failed(GOOD.replace("файлов 2, ok 1, FAIL 1", "файлов 3, ok 1, FAIL 1")) is None)
check("run_failed: FAIL-строк меньше, чем в итоге — None",
      O.run_failed(GOOD.replace("файлов 2, ok 1, FAIL 1", "файлов 2, ok 0, FAIL 2")) is None)
check("run_failed: FAIL в итоге больше FAIL-строк при сошедшихся ok и сумме — None",
      O.run_failed(GOOD.replace("файлов 2, ok 1, FAIL 1", "файлов 3, ok 1, FAIL 2")) is None)
check("run_failed: один файл и ok, и FAIL — None",
      O.run_failed(GOOD.replace("FAIL kit/test_b.py · 0.1", "FAIL kit/test_a.py · 0.1")) is None)
check("run_failed: пусто — None", O.run_failed("") is None)

# --- 7. run_causes: причина красного по файлу (metis-0696) ----------------------------------------------------------
CAUSES = ("run-tests: 5 файлов\n"
          "FAIL kit/test_a.py · 600.0 с · проверок 3 · таймаут\n"
          "FAIL kit/test_b.py · 1.0 с · проверок 0 · сигнал 9\n"
          "FAIL kit/test_c.py · 1.0 с · проверок 2 · код 1\n"
          "FAIL kit/test_d.py · 1.0 с · проверок 2 · код 1\n"
          "ok   kit/test_e.py · 1.0 с · проверок 2\n"
          "\n===== kit/test_c.py · код 1 · строки не ok: 3 =====\n"
          "пропущено: проба под песочницей — sandbox-exec: Operation not permitted\n"
          "FAIL report --out вне $TMPDIR — код 2\n"
          "FAIL kit/test_zz.py · 1 с · проверок 1 · код 1\n"
          "\n===== kit/test_d.py · код 1 · строки не ok: 2 =====\n"
          "FAIL сумма " + "х" * 300 + "\n"
          "пропущено: sandbox-exec нет — Operation not permitted\n"
          "----- последние 2 строк -----\nPermissionError: хвост после списка не в счёт\n"
          "\nмедленные: …\nитого: файлов 5, ok 1, FAIL 4; проверок 9; 600 с, воркеров 2\n")
rc = O.run_causes(CAUSES)
check("run_causes: таймаут и сигнал — по строке FAIL раннера",
      rc.get("kit/test_a.py") == {"kind": "таймаут", "why": "таймаут", "line": ""}
      and rc.get("kit/test_b.py") == {"kind": "сигнал", "why": "сигнал 9", "line": ""}, rc)
check("run_causes: отказ песочницы в строках не ok — «среда», первая строка не ok — строка пропуска",
      rc.get("kit/test_c.py", {}).get("kind") == "среда" and rc["kit/test_c.py"]["why"] == "код 1"
      and rc["kit/test_c.py"]["line"].startswith("пропущено"), rc.get("kit/test_c.py"))
check("run_causes: «Operation not permitted» только в строке пропуска и PermissionError после «-----» — провал, "
      "строка до CAUSE_LINE знаков", rc.get("kit/test_d.py", {}).get("kind") == "провал"
      and len(rc["kit/test_d.py"]["line"]) == O.CAUSE_LINE, rc.get("kit/test_d.py"))
check("run_causes: строки FAIL из хвоста упавшего — не файлы раннера; ok — не причина",
      sorted(rc) == ["kit/test_a.py", "kit/test_b.py", "kit/test_c.py", "kit/test_d.py"], sorted(rc))
check("run_causes: пусто — {}", O.run_causes("") == {})

# --- 8. доля красных полных прогонов за сутки: тревога с разбивкой (metis-0696) ---------------------------------------
NOW = time.time()


def ent(ago, code, failed=None, causes=None):
    e = {"rid": f"r{ago}", "repo": REPOS, "code": code, "failed": failed,
         "time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(NOW - ago))}
    if causes is not None:
        e["causes"] = causes
    return e


MG = "guard/test_merge_gate.py"
RED = [ent(60, 1, [MG], {MG: {"kind": "провал", "why": "код 1", "line": "FAIL r6"}}),
       ent(120, 1, [MG, "pantheon/test_read.py"], {MG: {"kind": "таймаут"}, "pantheon/test_read.py": {"kind": "таймаут"}}),
       ent(180, -9, None)]
GREEN = [ent(240, 0, []), ent(300, 0, [])]
OLD = [ent(O.RED_WINDOW + 60, 1, [MG], {MG: {"kind": "провал"}})] * 5
total, red, kinds, files_ = O.red_share(RED + GREEN + OLD, t=NOW)
check("red_share: только за сутки, красный — код не 0, причины по видам и файлам",
      (total, red) == (5, 3) and kinds == {"провал": 1, "таймаут": 2, "итог не разобран": 1}
      and files_ == {MG: {"провал": 1, "таймаут": 1}, "pantheon/test_read.py": {"таймаут": 1}}, (total, red, kinds, files_))
check("red_share: запись без causes (до metis-0696) — «причина не записана»",
      O.red_share([ent(10, 1, [MG])], t=NOW)[2] == {"причина не записана": 1})
ALERTS = os.path.join(HOME, "ai", "pantheon", "alerts.md")


def alerts_text():
    try:
        with open(ALERTS) as fh:
            return fh.read()
    except OSError:
        return ""


_rf_full = O.read_full
try:
    for name, rows, want in (("3 из 3 — меньше RED_MIN_RUNS, тревоги нет", RED, False),
                             ("1 из 4 (25 %) — не выше порога, тревоги нет", RED[:1] + GREEN + [ent(360, 0, [])], False),
                             ("красные старше суток не в счёт", OLD + GREEN, False),
                             ("3 из 10 — ровно 30 %, не выше порога", RED[:2] + [ent(30, 1, [MG])]
                              + [ent(400 + i, 0, []) for i in range(7)], False)):
        O.read_full = lambda rows=rows: rows
        a0 = alerts_text()
        check(f"тревога по доле: {name}", O.alert_red_share(t=NOW) is want and alerts_text() == a0, alerts_text()[len(a0):])
    O.read_full = lambda: RED + GREEN
    a0 = alerts_text()
    got = O.alert_red_share(t=NOW)
    new = alerts_text()[len(a0):]
    check("тревога по доле: 3 из 5 (60 %) — строка в alerts.md с долей, видами причин и файлами",
          got is True and "pantheon-outside" in new and "3 из 5 (60 %" in new and "таймаут 2" in new
          and "итог не разобран 1" in new and f"{MG} — " in new and "pantheon/test_read.py — таймаут 1" in new, new)
    a1 = alerts_text()
    check("тревога по доле: в те же сутки повтора нет", O.alert_red_share(t=NOW) is True and alerts_text() == a1)
    O.read_full = lambda: RED[:2] + GREEN
    check("тревога по доле: 2 из 4 — RED_MIN_RUNS прогонов хватает, доля выше порога",
          O.alert_red_share(t=NOW) is True and alerts_text() == a1)
    # проход тестов зовёт подсчёт после очереди; сбой подсчёта не роняет проход и виден в журнале
    calls_ = []
    saved = {k: getattr(O, k) for k in ("watchdog", "recover_results", "drop_test_work", "alert_overdue",
                                        "run_test_queue", "prune", "alert_red_share")}
    for k in saved:
        setattr(O, k, lambda *a, k=k, **kw: calls_.append(k))
    try:
        rc1 = O.cmd_run()

        def boom(*_a, **_k):
            raise ValueError("сломано")
        O.alert_red_share = boom
        rc2 = O.cmd_run()
    finally:
        for k, v in saved.items():
            setattr(O, k, v)
    ev = os.path.join(STATE, "logs", "outside.jsonl")
    evs = open(ev).read() if os.path.exists(ev) else ""
    check("cmd_run: подсчёт доли красных после очереди тестов; сбой — код 0 и запись red-share-error",
          rc1 == 0 and rc2 == 0 and "alert_red_share" in calls_
          and calls_.index("alert_red_share") > calls_.index("run_test_queue")
          and '"red-share-error"' in evs and "сломано" in evs, (calls_, evs[-300:]))
finally:
    O.read_full = _rf_full

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
