#!/usr/bin/env python3
"""Новая заявка test снимает ждущие заявки той же папки на старых head (metis-0852, lib/outside.py: replace_older).

Запуск: python3 -I plugins/pantheon/tests/test_outside_replace.py  (код выхода 0 — все прошли)
Временный репозиторий с коммитами A → B (B — потомок) и веткой C от A, заявки подаются так же, как из окна роли
(`pantheon outside test [--sha]` → outside.main с PANTHEON_TMP окна) и из терминала владельца (очередь STATE). Проход
не запускается: проверяется только очередь. Проверяет: заявка на потомке снимает ждущую на предке — итог stopped
«заменена заявкой <ID> на <sha>», .req.json нет; не предок (другая ветка той же папки) — обе ждут; начатая (проход
снял .req.json, итог running) — не тронута; другая папка (worktree того же клона), другое окно, другая проверка
(--script, --sha против обычной) — не тронуты; терминал владельца — итог и в STATE/outside/runs.
"""
import atexit
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import PY311  # noqa: E402,F401  pantheon.py — только на Python 3.11+

_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="outside-replace-"))
tempfile.tempdir = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIBDIR = os.path.join(os.path.dirname(HERE), "lib")
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


def git(*args, d=None):
    r = subprocess.run(["git", "-C", d or RP, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                        *args], capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def commit(name, d=None):
    with open(os.path.join(d or RP, "f.txt"), "a") as fh:
        fh.write(name + "\n")
    git("add", "-A", d=d)
    git("commit", "-q", "-m", name, d=d)
    return git("rev-parse", "HEAD", d=d)


RP = os.path.join(HOME, "projects", "rp")
os.makedirs(RP)
git("init", "-q", "-b", "main")
git("remote", "add", "origin", "git@github.com:latark/rp.git")
A = commit("a")
B = commit("b")
git("switch", "-q", "-c", "side", A)
C = commit("c: ветка от A, не потомок B")
git("switch", "-q", "main")
WT = os.path.join(HOME, "projects", "rp-wt")
git("worktree", "add", "-q", "--detach", WT, B)
CACHE = os.path.join(HOME, "Library", "Caches", "pantheon-sandbox")
for w in ("win-a", "win-b"):
    os.makedirs(os.path.join(CACHE, w, "tmp"))


def qdir(window):
    return os.path.join(CACHE, window, "outside") if window else O.root("queue")


def submit(window, cwd, *args):
    """`pantheon outside test …` из окна window (None — терминал владельца) → (код, ID новой заявки или None, вывод)."""
    q = qdir(window)
    before = set(os.listdir(q)) if os.path.isdir(q) else set()
    if window:
        os.environ["PANTHEON_TMP"] = os.path.join(CACHE, window, "tmp")
    old, buf = os.getcwd(), io.StringIO()
    os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(buf):
            rc = O.main(["test", *args])
    finally:
        os.chdir(old)
        os.environ.pop("PANTHEON_TMP", None)
    new = sorted(n[:-9] for n in set(os.listdir(q)) - before if n.endswith(".req.json"))
    return rc, (new[-1] if new else None), buf.getvalue()


def queued(window, rid):
    return os.path.isfile(os.path.join(qdir(window), rid + ".req.json"))


def result(window, rid):
    return O.load_result(qdir(window), rid) or {}


def clear(window):
    q = qdir(window)
    if os.path.isdir(q):
        shutil.rmtree(q)


# --- 1. две заявки одной папки, вторая на потомке: первая stopped со ссылкой на вторую ----------------------------
rc1, r1, _ = submit("win-a", RP, "--sha", A)
rc2, r2, out2 = submit("win-a", RP, "--sha", B)
res1 = result("win-a", r1)
check("--sha: заявка на потомке B снимает ждущую на предке A — .req.json нет, итог stopped",
      rc1 == 0 and rc2 == 0 and r1 and r2 and not queued("win-a", r1) and queued("win-a", r2)
      and res1.get("state") == "stopped" and res1.get("record") is False, (r1, r2, res1))
check("итог снятой: «заменена заявкой <ID> на <sha>», replaced_by и sha старой заявки",
      res1.get("why") == f"заменена заявкой {r2} на {B[:12]}" and res1.get("replaced_by") == r2
      and res1.get("sha") == A, res1)
check("CLI печатает, какая заявка снята и чем заменена", f"{r1}: заявка на {A[:12]}" in out2 and r2 in out2, out2)
check("новая заявка ждёт как обычно (queued)", result("win-a", r2).get("state") == "queued", result("win-a", r2))
clear("win-a")

# обычная заявка (без --sha) на HEAD папки: HEAD ушёл A → B — первая снята
git("checkout", "-q", "--detach", A)
_, r1, _ = submit("win-a", RP)
git("checkout", "-q", "main")
_, r2, _ = submit("win-a", RP)
check("обычная заявка: HEAD A → B, ждущая на A снята новой на B",
      r1 and r2 and not queued("win-a", r1) and result("win-a", r1).get("state") == "stopped"
      and result("win-a", r1).get("replaced_by") == r2, (r1, r2, result("win-a", r1)))
clear("win-a")

# --- 2. sha не предок (другая ветка той же папки) — обе остаются ---------------------------------------------------
_, r1, _ = submit("win-a", RP, "--sha", B)
_, r2, _ = submit("win-a", RP, "--sha", C)
check("не предок: B и C (ветка от A) — обе заявки ждут, итог первой queued",
      r1 and r2 and queued("win-a", r1) and queued("win-a", r2) and result("win-a", r1).get("state") == "queued",
      (r1, r2, result("win-a", r1)))
# новая заявка на предке старую на потомке не снимает
_, r3, _ = submit("win-a", RP, "--sha", A)
check("новая на предке A: заявка на потомке B ждёт", r3 and queued("win-a", r1) and queued("win-a", r3), (r1, r3))
clear("win-a")

# --- 3. заявка уже идёт (проход снял .req.json, итог running) — не снимается ----------------------------------------
_, r1, _ = submit("win-a", RP, "--sha", A)
os.remove(os.path.join(qdir("win-a"), r1 + ".req.json"))
run1 = {"id": r1, "state": "running", "kind": "test", "sha": A, "src": RP, "pin": True, "updated": P.stamp()}
with open(os.path.join(qdir("win-a"), r1 + ".result.json"), "w") as fh:
    json.dump(run1, fh)
_, r2, _ = submit("win-a", RP, "--sha", B)
check("идущая заявка на предке не снята: итог running как был, новая ждёт",
      r2 and result("win-a", r1).get("state") == "running" and "replaced_by" not in result("win-a", r1)
      and queued("win-a", r2), (result("win-a", r1), r2))
clear("win-a")

# --- 4. чужое не трогает: другое окно, другая папка того же клона, другая проверка --------------------------------
_, rb, _ = submit("win-b", RP, "--sha", A)
_, ra, _ = submit("win-a", RP, "--sha", B)
check("другое окно: его заявка на предке ждёт", rb and ra and queued("win-b", rb)
      and result("win-b", rb).get("state") == "queued", result("win-b", rb))
clear("win-a")
clear("win-b")
_, r1, _ = submit("win-a", RP, "--sha", A)
_, r2, _ = submit("win-a", WT, "--sha", B)
check("другая папка (worktree того же клона): заявка папки RP на предке ждёт", r1 and r2 and queued("win-a", r1)
      and queued("win-a", r2), (r1, r2))
clear("win-a")
git("checkout", "-q", "--detach", A)
_, r1, _ = submit("win-a", RP)
git("checkout", "-q", "main")
_, r2, _ = submit("win-a", RP, "--sha", B)
check("обычная на A и --sha на B — разные проверки (metis-0796): обычная ждёт", r1 and r2 and queued("win-a", r1),
      (r1, r2))
git("checkout", "-q", "--detach", A)
_, r3, _ = submit("win-a", RP, "--affected", "--base", "side")
git("checkout", "-q", "main")
_, r4, _ = submit("win-a", RP)
check("--affected на A и обычная на B — разные проверки (--base): --affected ждёт", r3 and r4 and queued("win-a", r3)
      and queued("win-a", r4), (r3, r4))
clear("win-a")
git("checkout", "-q", "--detach", A)
_, r5, _ = submit("win-a", RP, "--script", "lint")
git("checkout", "-q", "main")
_, r6, _ = submit("win-a", RP)
check("--script lint на A и обычная на B — разные проверки: --script ждёт", r5 and r6 and queued("win-a", r5),
      (r5, r6))
_, r7, _ = submit("win-a", RP, "--script", "lint")
check("--script lint на B снимает --script lint на A", r7 and not queued("win-a", r5)
      and result("win-a", r5).get("replaced_by") == r7 and queued("win-a", r6), (r5, r7, result("win-a", r5)))
clear("win-a")

# --- 5. терминал владельца (очередь STATE): итог и в STATE/outside/runs -------------------------------------------
_, r1, _ = submit(None, RP, "--sha", A)
_, r2, _ = submit(None, RP, "--sha", B)
saved = P.read_json(O.root("runs", r1 + ".json"), None) or {}
check("терминал владельца: снята, итог stopped в очереди и в STATE/outside/runs",
      r1 and r2 and not queued(None, r1) and result(None, r1).get("state") == "stopped"
      and saved.get("state") == "stopped" and saved.get("replaced_by") == r2, (result(None, r1), saved))
clear(None)

# --- 6. прямой вызов: не test, без sha, битая заявка рядом — ничего ------------------------------------------------
check("replace_older: заявка serve или без sha — ничего не снимает",
      O.replace_older(qdir("win-a"), "x", {"kind": "serve", "sha": B}, RP) == []
      and O.replace_older(qdir("win-a"), "x", {"kind": "test"}, RP) == [])
_, r1, _ = submit("win-a", RP, "--sha", A)
bad = "20261107-000000-badbad"
with open(os.path.join(qdir("win-a"), bad + ".req.json"), "w") as fh:
    fh.write("{не json")
_, r2, _ = submit("win-a", RP, "--sha", B)
check("битая заявка рядом не мешает и не снимается: старая снята, битая лежит",
      not queued("win-a", r1) and queued("win-a", bad) and result("win-a", r1).get("replaced_by") == r2)
clear("win-a")

print(f"{TOTAL[0] - len(FAILS)} из {TOTAL[0]} прошли")
sys.exit(1 if FAILS else 0)
