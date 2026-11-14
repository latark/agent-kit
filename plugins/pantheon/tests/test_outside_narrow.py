#!/usr/bin/env python3
"""Узкий набор вне окна (metis-0734, lib/outside.py: narrow_plan, run_test с base, cmd_request --affected).

Запуск: python3 -I plugins/pantheon/tests/test_outside_narrow.py  (код выхода 0 — все прошли)
Временный репозиторий с настоящим run-tests.py (копия из scripts/ в tools/), пять файлов тестов и карта
affected-map.json; sandbox-exec подменён заглушкой, которая пишет команду и исполняет её. Проверяет: заявка
`test --affected` берёт вершину origin/main (или --base) при заявке; проход гонит run-tests.py с `--affected --base
<merge-base вершины и коммита>` — дифф от развилки, а не от ушедшего вперёд main; зелёный прогон пишет запись tests с
этой командой, files (прогнанные метки) и map (sha256 карты), и шлюз guard её засчитывает (narrow_tests_record,
_narrow_problem); красный, «гонять нечего» (код 3), нет карты, не одна merge-base, команда не run-tests.py — записи нет.
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311, mkroot  # noqa: E402,F401  pantheon.py — только на Python 3.11+

_ROOT = os.path.realpath(mkroot("outside-narrow-"))  # окно роли: metis-0941
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


REC = os.path.join(_ROOT, "calls.jsonl")
FAKE = os.path.join(_ROOT, "fake-sandbox-exec")
with open(FAKE, "w") as fh:
    fh.write(f"#!{sys.executable}\nimport json, os, sys\ncmd = sys.argv[3:]\n"
             f"with open({REC!r}, 'a') as fh:\n    fh.write(json.dumps(cmd) + '\\n')\nos.execvp(cmd[0], cmd)\n")
os.chmod(FAKE, 0o755)
O.SANDBOX_EXEC = FAKE
O.HEAVY = None
# нагрузка машины тесту не нужна (metis-1117, как в _outside_common.py): полный набор при load выше 3.0 × ядер ждёт
# спада по 30 с (wait_load) — на раннере CI macos-15 файл шёл 522 с против 6 с на Linux
O.load_state = lambda: (0.0, 24.0)


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


def commit(files, msg):
    for name, text in files.items():
        p = os.path.join(RK, name)
        if text is None:
            os.remove(p)
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(text)
    git("add", "-A")
    git("commit", "-q", "-m", msg)
    return git("rev-parse", "HEAD")


RK = os.path.join(HOME, "projects", "rk")
os.makedirs(RK)
git("init", "-q", "-b", "main")
git("remote", "add", "origin", "git@github.com:latark/rk.git")
NAMES = "abcde"
LABELS = [f"kit/test_{x}.py" for x in NAMES]
TEST_SRC = ("import sys\nv = open('lib/{x}.txt').read().strip()\n"
            "if v.startswith('good'):\n    print('ok   {x}')\n    print('1 из 1')\n"
            "else:\n    print('FAIL {x}')\n    print('0 из 1')\n    sys.exit(1)\n")
with open(RUNNER) as fh:
    RUNNER_SRC = fh.read()
LINE = f"{sys.executable} -I tools/run-tests.py -j 2 plugins/kit"
FILES = {f"plugins/kit/tests/test_{x}.py": TEST_SRC.format(x=x) for x in NAMES}
FILES.update({f"plugins/kit/lib/{x}.txt": "good\n" for x in NAMES})
FILES.update({"tools/run-tests.py": RUNNER_SRC, "README.md": "rk\n", ".pantheon-verify": f"heavy {LINE}\n"})


def test_hash(x):
    return hashlib.sha256(FILES[f"plugins/kit/tests/test_{x}.py"].encode()).hexdigest()


fl = {f"plugins/kit/lib/{x}.txt": [i] for i, x in enumerate(NAMES)}
fl.update({"tools/run-tests.py": [], "tools/affected-map.json": [], ".pantheon-verify": [], "README.md": []})
FILES["tools/affected-map.json"] = json.dumps({"version": 3, "head": "x", "python": "3", "tests": LABELS, "broken": [],
                                               "hashes": {lb: test_hash(x) for lb, x in zip(LABELS, NAMES)},
                                               "files": fl}, indent=1)
MAPH = hashlib.sha256(FILES["tools/affected-map.json"].encode()).hexdigest()
B0 = commit(FILES, "b0: всё зелёное")
M1 = commit({"plugins/kit/lib/e.txt": "good-main\n"}, "m1: main ушёл вперёд (e)")
git("update-ref", "refs/remotes/origin/main", M1)
git("checkout", "-q", "-b", "feat", B0)
F1 = commit({"plugins/kit/lib/b.txt": "good2\n"}, "f1: правка b")
FULL = f"heavy {LINE}"
P.merge_mod().FULL_TESTS["rk"] = FULL
N = [0]


def run(base=M1):
    N[0] += 1
    rid = f"20261105-{N[0]:06d}-abcdef"
    return O.run_test(rid, RK, None, "metis-r", None, [RK], base=base)


def gate(code):
    """Шлюз guard в отдельном процессе (как хук): FULL_TESTS["rk"] — команда проверки репозитория."""
    src = ("import sys, json; sys.path.insert(0, %r); import guard_rules, merge_gate as m; "
           "m.FULL_TESTS['rk'] = %r; " % (GUARD_HOOKS, FULL)) + code
    r = subprocess.run([sys.executable, "-I", "-c", src], capture_output=True, text=True,
                       env={"HOME": HOME, "PATH": os.environ["PATH"]})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def tests_for(sha):
    return [r for r in gate("print(json.dumps(m.read_records()))") if r["kind"] == "tests" and r["sha"] == sha]


def gate_view(rec, sha, base_oid):
    """(narrow_tests_record, _narrow_problem) шлюза для записи rec на head sha с base PR base_oid; папка — RK."""
    return gate("r = json.loads(%r); got = m.narrow_tests_record('latark/rk', r); "
                "print(json.dumps([got, got and m._narrow_problem(%r, 'latark/rk', %r, %r, got[0], got[1]), "
                "m.full_tests_record('latark/rk', r)]))" % (json.dumps(rec), RK, sha, base_oid))


# --- 1. зелёный узкий прогон: дифф от развилки B0, а не от ушедшего вперёд main; запись — узкая ----------------------
n0 = ncalls()
r1 = run()
rec1 = tests_for(F1)
check("узкий: команда раннера — проверка проекта с --affected --base <merge-base B0>, один прогон",
      ncalls() == n0 + 1 and last_cmd()[-1] == f"{LINE} --affected --base {B0}", last_cmd())
check("узкий: код 0, запись tests, итог несёт base (вершину заявки) и строку «узкий набор … файлов 1»",
      r1.get("code") == 0 and r1.get("record") and r1.get("base") == M1
      and f"узкий набор (--affected) от merge-base {B0[:12]}: файлов 1" in r1.get("note", ""), r1)
check("запись шлюза: cmd — команда прогона, files — только b (e правил main, не PR), map — sha256 карты, без rerun_of",
      len(rec1) == 1 and rec1[0]["cmd"] == r1["cmd"] == f"{LINE} --affected --base {B0}"
      and rec1[0].get("files") == ["kit/test_b.py"] and rec1[0].get("map") == MAPH and "rerun_of" not in rec1[0]
      and rec1[0]["by"]["agent_type"] == "pantheon-outside", rec1)
got = gate_view(rec1[0], F1, M1)
check("шлюз guard: узкая запись (база B0, карта), база — merge-base head и main, карта — из дерева head; не полный набор",
      got == [[B0, MAPH], None, False], got)
got = gate_view(rec1[0], F1, F1)
check("шлюз guard: при другом base PR (merge-base другая) — отказ «посчитан от»",
      got[0] == [B0, MAPH] and "узкий набор посчитан от" in (got[1] or ""), got)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    O.show(r1)
check("status: строка узкого набора и записи", "узкий набор (--affected)" in out.getvalue()
      and "запись tests для шлюза слияния сделана" in out.getvalue(), out.getvalue())
check("полный набор не тронут: запись узкая — не в full.jsonl (опора дозапуска — только полный прогон)",
      not any(e.get("sha") == F1 for e in O.read_full()), O.read_full())

# --- 2. красный узкий — записи нет ------------------------------------------------------------------------------------
F2 = commit({"plugins/kit/lib/c.txt": "bad\n"}, "f2: c красный")
r2 = run()
check("красный узкий (c): код 1, записи нет, гонялись b и c", r2.get("code") == 1 and not r2.get("record")
      and not tests_for(F2) and "файлов 2" in r2.get("note", ""), r2)

# --- 3. файл вне карты — раннер гонит весь набор; запись узкая со всеми метками ----------------------------------------
F3 = commit({"plugins/kit/lib/c.txt": "good3\n", "plugins/kit/new.txt": "x\n"}, "f3: c починен, файл вне карты")
r3 = run()
rec3 = tests_for(F3)
check("файл вне карты: раннер гонит весь набор, запись — узкая команда, files — все пять меток",
      r3.get("code") == 0 and len(rec3) == 1 and rec3[0].get("files") == LABELS
      and "--affected" in rec3[0]["cmd"], (r3, rec3))
_rf = O.run_failed
O.run_failed = lambda text: None
r3b = run()
O.run_failed = _rf
check("зелёный узкий, но итог run-tests не разобран — записи нет, причина",
      r3b.get("code") == 0 and not r3b.get("record") and "итог run-tests не разобран" in r3b.get("why", "")
      and len(tests_for(F3)) == 1, r3b)
O.run_failed = lambda text: (lambda g: g and (g[0], g[1] + ["kit/test_zz.py"], g[2]))(_rf(text))
r3c = run()
O.run_failed = _rf
check("зелёный узкий, но в итоге есть FAIL — записи нет", not r3c.get("record") and len(tests_for(F3)) == 1, r3c)

# --- 4. гонять нечего (код 3) — записи нет ---------------------------------------------------------------------------
git("checkout", "-q", "-b", "readme", B0)
F4 = commit({"README.md": "rk 2\n"}, "f4: только README")
n0 = ncalls()
r4 = run()
check("гонять нечего (README по карте без тестов): код 3, записи нет, причина «код 3»",
      r4.get("code") == 3 and not r4.get("record") and "гонять нечего (код 3)" in r4.get("why", "")
      and not tests_for(F4) and ncalls() == n0 + 1, r4)

# --- 5. узкий набор не собрать — failed без прогона ------------------------------------------------------------------
F5 = commit({"tools/affected-map.json": None, "plugins/kit/lib/a.txt": "good5\n"}, "f5: карты нет")
n0 = ncalls()
r5 = run()
check("карты нет в дереве: failed без прогона, причина «карту … не прочесть»",
      r5.get("state") == "failed" and ncalls() == n0 and "карту tools/affected-map.json не прочесть" in r5.get("why", "")
      and r5.get("base") == M1, r5)
git("checkout", "-q", "--orphan", "lone")
F6 = commit({}, "f6: без общей истории с main")
n0 = ncalls()
r6 = run()
check("нет общей истории с base: failed без прогона, «merge-base … не одна или не посчитана»",
      r6.get("state") == "failed" and ncalls() == n0 and "не одна или не посчитана" in r6.get("why", ""), r6)
git("checkout", "-q", "-f", "feat")

# --- 5б. история подменена (shallow, info/grafts, refs/replace) — полный набор вместо узкого, запись полная ----------
GITDIR = os.path.join(RK, ".git")


def _file(name, text):
    def put():
        with open(os.path.join(GITDIR, name), "w") as fh:
            fh.write(text)
    return put, lambda: os.remove(os.path.join(GITDIR, name))


git("checkout", "-q", "-b", "hist", F3)
for label, word, (setup, undo) in (
        ("shallow", "shallow", _file("shallow", B0 + "\n")),
        ("info/grafts", "info/grafts", _file("info/grafts", F3 + "\n")),
        ("refs/replace", "refs/replace", (lambda: git("replace", F1, B0), lambda: git("replace", "-d", F1)))):
    # своё дерево на каждый случай: полный набор на том же дереве перенёсся бы без прогона (tree_record)
    hx = commit({f"plugins/kit/hist-{len(word)}.txt": word + "\n"}, f"hist: {label}")
    setup()
    try:
        n0, k0 = ncalls(), len(tests_for(hx))
        rx = run()
        recs = tests_for(hx)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            O.show(rx)
    finally:
        undo()
    check(f"{label}: полный набор вместо узкого — команда без --affected, итог без base, narrow_why «{word}»",
          ncalls() == n0 + 1 and last_cmd()[-1] == LINE and "base" not in rx and word in rx.get("narrow_why", "")
          and rx.get("code") == 0 and rx.get("record"), rx)
    check(f"{label}: запись полная (без --affected) — её шлюз засчитает и ядру; status называет причину",
          len(recs) == k0 + 1 and "--affected" not in recs[-1]["cmd"] and "полный набор, а не узкий" in out.getvalue(),
          (recs[-1:], out.getvalue()))
check("история снова целая — narrow_history_problem None", O.narrow_history_problem(RK) is None)
git("checkout", "-q", "feat")
_cmd = O.command
O.command = lambda d, kind, script=None: (["/bin/sh", "-c", "python3 t.py"], "python3 t.py")
n0 = ncalls()
r7 = run()
O.command = _cmd
check("команда проверки — не run-tests.py: failed без прогона", r7.get("state") == "failed" and ncalls() == n0
      and "только у проверки run-tests.py" in r7.get("why", ""), r7)
argv, line = O.command(RK, "test")
p, why = O.narrow_plan(RK, F3, argv, line, M1)
check("narrow_plan: план — команда с ключами, merge-base, карта и её путь",
      p and p["argv"] == ["/bin/sh", "-c", f"{LINE} --affected --base {B0}"] and p["mb"] == B0 and p["map"] == MAPH
      and p["mp"] == "tools/affected-map.json" and why is None, (p, why))
p, _ = O.narrow_plan(RK, F3, ["/bin/sh", "-c", LINE + "  # хвост"], LINE + "  # хвост  # .pantheon-verify", M1)
check("narrow_plan: хвост-комментарий строки — после ключей в записи и срезан в команде",
      p["argv"][2] == f"{LINE} --affected --base {B0}"
      and p["line"] == f"{LINE} --affected --base {B0}  # .pantheon-verify", p)
gv = gate_view(dict(rec1[0], cmd=p["line"]), F1, M1)
check("шлюз: запись с хвостом-комментарием — та же узкая запись", gv[0] == [B0, MAPH] and gv[1] is None, gv)
# перекрёстные слияния: у вершины базы и коммита две merge-base — дифф «от развилки» не определён
_t = git("rev-parse", f"{B0}^{{tree}}")
_xa, _xb = (git("commit-tree", _t, "-p", B0, "-m", m) for m in ("xa", "xb"))
_ca = git("commit-tree", _t, "-p", _xa, "-p", _xb, "-m", "ca")
_cb = git("commit-tree", _t, "-p", _xb, "-p", _xa, "-m", "cb")
p, why = O.narrow_plan(RK, _cb, argv, line, _ca)
check("narrow_plan: две merge-base (перекрёстные слияния) — плана нет, «не одна»",
      p is None and "не одна или не посчитана" in (why or ""), (p, why))

# --- 6. заявка: --affected, --base, проверка заявки ------------------------------------------------------------------
git("checkout", "-q", "feat")
cwd = os.getcwd()
os.chdir(RK)
try:
    def request(*args):
        e, o = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(e), contextlib.redirect_stdout(o):
            code = O.cmd_request("test", list(args))
        return code, o.getvalue() + e.getvalue()

    def queued():
        q = O.own_qdir()
        return [json.load(open(os.path.join(q, n))) for n in sorted(os.listdir(q)) if n.endswith(".req.json")]

    code, text = request("--affected")
    reqs = queued()
    check("test --affected: заявка с base — вершиной origin/main (полный SHA) при заявке",
          code == 0 and len(reqs) == 1 and reqs[0].get("base") == M1 and reqs[0].get("sha") == F3, (code, text, reqs))
    code, text = request("--affected")
    check("тот же коммит и та же база — новой заявки нет (live_test сцепляет)", code == 0 and len(queued()) == 1
          and "уже в очереди" in text, text)
    code, text = request()
    check("обычная заявка на тот же коммит — своя (база не та)", code == 0 and len(queued()) == 2, text)
    code, text = request("--affected", "--base", "readme")
    check("--base ветка: вершина этой ветки, новая заявка", code == 0 and len(queued()) == 3
          and any(r.get("base") == F5 for r in queued()), (text, queued()))
    for args, want in ((["--base", "main"], "--base — только с --affected"),
                       (["--affected", "--base", "nope"], "не коммит этой копии"),
                       (["--affected", "--base", "-x"], "не коммит этой копии"),
                       (["--affected", "--base"], "pantheon outside: pantheon outside test"),
                       (["--affected", "--script", "t"], "base — коммит из 40 знаков")):
        n = len(queued())
        code, text = request(*args)
        check(f"test {' '.join(args)}: код 2, заявки нет — «{want}»", code == 2 and len(queued()) == n and want in text,
              (code, text))
    e = io.StringIO()
    with contextlib.redirect_stderr(e), contextlib.redirect_stdout(io.StringIO()):
        code = O.cmd_request("serve", ["--affected"])
    check("serve --affected: код 2 (ключ только у test)", code == 2, e.getvalue())
    _registry, O.registry = O.registry, lambda window=None: [os.path.dirname(RK)]   # реестра (domains.json) тут нет
    try:
        n = O.drop_dupes(O.own_qdir(), "20261105-000000-ffffff", {"base": M1}, RK, F3)
    finally:
        O.registry = _registry
    left = queued()
    check("drop_dupes: снята только ждущая заявка с той же базой; обычная и с другой базой остались",
          n == 1 and len(left) == 2 and not any(r.get("base") == M1 for r in left)
          and any(r.get("base") is None for r in left) and any(r.get("base") == F5 for r in left), (n, left))
finally:
    os.chdir(cwd)

# --- 7. проход: handle несёт base заявки в run_test и в run_test_at (test --sha --affected) --------------------------
_registry, O.registry = O.registry, lambda window=None: [os.path.dirname(RK)]
try:
    n0 = ncalls()
    rh = O.handle(O.own_qdir(), None, "20261105-100000-aaaaaa",
                  {"v": 1, "id": "20261105-100000-aaaaaa", "kind": "test", "dir": RK, "time": "2026-11-05T10:00:00+0300",
                   "base": M1})
    check("handle: заявка с base — узкий прогон на HEAD (F3) от merge-base B0",
          rh.get("base") == M1 and rh.get("sha") == F3 and ncalls() == n0 + 1
          and last_cmd()[-1] == f"{LINE} --affected --base {B0}", (rh, last_cmd()))
    rp = O.handle(O.own_qdir(), None, "20261105-100001-aaaaaa",
                  {"v": 1, "id": "20261105-100001-aaaaaa", "kind": "test", "dir": RK, "time": "2026-11-05T10:00:00+0300",
                   "sha": F1, "pin": True, "base": M1})
    check("handle test --sha: копия на F1, узкий прогон от merge-base B0, итог несёт base",
          rp.get("base") == M1 and rp.get("sha") == F1 and ncalls() == n0 + 2
          and last_cmd()[-1] == f"{LINE} --affected --base {B0}", (rp, last_cmd()))
finally:
    O.registry = _registry
ok = {"v": 1, "id": "r", "kind": "test", "dir": RK, "time": "2026-11-05T10:00:00+0300"}
check("check_request: base — 40 знаков у test", O.check_request(dict(ok, base=M1), "r") is None)
for name, extra in (("короткий", {"base": M1[:12]}), ("заглавные", {"base": M1.upper()}), ("не строка", {"base": 1}),
                    ("у serve", {"base": M1, "kind": "serve"}), ("со --script", {"base": M1, "script": "t"})):
    check(f"check_request: base {name} — отказ", O.check_request(dict(ok, **extra), "r"), extra)

# --- 8. карантин раннера (metis-1050): упал файл из QUARANTINE — код 0, итог разобран, запись tests есть ------------
git("checkout", "-q", "-b", "quar", B0)
assert RUNNER_SRC.count("QUARANTINE = {") == 1
Q1 = commit({"tools/run-tests.py": RUNNER_SRC.replace("QUARANTINE = {", 'QUARANTINE = {"kit/test_c.py": "metis-0000",'),
             "plugins/kit/lib/c.txt": "bad\n"}, "q1: c красный, но в карантине раннера")
rq = run()
recq = tests_for(Q1)
check("узкий: упал только файл карантина — код 0, запись tests, files — c, итог разобран",
      rq.get("code") == 0 and rq.get("record") and "не разобран" not in rq.get("why", "")
      and "файлов 1" in rq.get("note", "") and len(recq) == 1 and recq[0].get("files") == ["kit/test_c.py"],
      (rq, recq))
with open(rq["log"]) as fh:
    QLOG = fh.read()
check("вывод настоящего раннера: строка «карантин kit/test_c.py», итог «…, карантин 1»",
      "\nкарантин kit/test_c.py · " in QLOG and ", FAIL 0, карантин 1;" in QLOG, QLOG[-600:])
Q2 = commit({"plugins/kit/lib/a.txt": "good-q2\n"}, "q2: своё дерево для полного набора")
rqf = run(base=None)
eq = next((e for e in O.read_full() if e.get("sha") == Q2), {})
check("полный: упал только файл карантина — код 0, запись tests; full.jsonl failed [] (не null), quarantine — c",
      rqf.get("code") == 0 and rqf.get("record") and eq.get("failed") == [] and eq.get("quarantine") == ["kit/test_c.py"]
      and "cause" not in eq, (rqf, eq))

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
