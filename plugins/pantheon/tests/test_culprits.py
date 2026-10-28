#!/usr/bin/env python3
"""Виновники памяти и pantheon reap (lib/culprits.py, metis-0568).

Запуск: python3 -I plugins/pantheon/tests/test_culprits.py  (код выхода 0 — все прошли)
Список процессов подменён (PANTHEON_FAKE_PROCS), kill — журналом (PANTHEON_FAKE_KILL_LOG): настоящие ps и гашение
не идут. Папки направления, worktree и задачи — во временной папке; claude — заглушка в PATH.
"""
import atexit
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

_ROOT = tempfile.mkdtemp(prefix="culprits-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "pantheon.py")
T0 = 1_792_000_000
H = 3600
FAILS = []
TOTAL = 0


def check(cond, what):
    global TOTAL
    TOTAL += 1
    print(("ok   " + what.split(": ")[0]) if cond else ("НЕ ПРОШЛО: " + what))
    if not cond:
        FAILS.append(what)


class Env:
    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="culprits-")
        self.home = os.path.realpath(os.path.join(self.tmp, "home"))
        self.pantheon = os.path.join(self.home, "ai", "pantheon")
        self.state = os.path.join(self.tmp, "state")
        self.bin = os.path.join(self.tmp, "bin")
        for d in (self.pantheon, self.state, self.bin):
            os.makedirs(d, exist_ok=True)
        self.state = os.path.realpath(self.state)
        self.agents_file = os.path.join(self.tmp, "agents.json")
        json.dump([], open(self.agents_file, "w"))
        with open(os.path.join(self.bin, "claude"), "w") as fh:
            fh.write('#!/bin/sh\ncat "$FAKE_AGENTS"\n')
        os.chmod(os.path.join(self.bin, "claude"), 0o755)
        self.kills = os.path.join(self.tmp, "kills.log")
        # направление с репозиторием и тремя копиями: живая с открытой задачей, живая с закрытой, удалённая
        self.repo = os.path.join(self.home, "projects", "athena-x")
        os.makedirs(os.path.join(self.repo, ".git"))
        json.dump({"domains": {"athena-x": [self.repo]}}, open(os.path.join(self.state, "domains.json"), "w"))
        os.makedirs(os.path.join(self.pantheon, "directions", "athena-x", "tasks"))
        self.wt_live = self.worktree("agent-live", "athena-0001-filter")
        self.wt_closed = self.worktree("agent-closed", "athena-0002-probe")
        self.wt_gone = os.path.join(self.repo, ".claude", "worktrees", "agent-gone")
        self.task("athena-0001", "doing")
        self.task("athena-0002", "done")
        self.procs = []

    def worktree(self, name, branch):
        wt = os.path.join(self.repo, ".claude", "worktrees", name)
        gd = os.path.join(self.repo, ".git", "worktrees", name)
        os.makedirs(wt)
        os.makedirs(gd)
        open(os.path.join(wt, ".git"), "w").write(f"gitdir: {gd}\n")
        open(os.path.join(gd, "HEAD"), "w").write(f"ref: refs/heads/{branch}\n")
        return wt

    def task(self, tid, status):
        p = os.path.join(self.pantheon, "directions", "athena-x", "tasks", tid + ".md")
        open(p, "w").write(f"---\ntype: task\nid: {tid}\ntitle: проба\nstatus: {status}\nproject: athena-x\n"
                           f"direction: athena-x\ncreated: 2026-10-15\nupdated: 2026-10-15T07:00:00\n"
                           f"schema_version: 1\npriority: 2\n---\n\nтекст\n")

    def proc(self, pid, args, cwd, age=3 * H, rss=512 * 1024, ppid=None, mem=None):
        self.procs.append({"pid": pid, "ppid": ppid, "age": age, "rss": rss, "args": args, "cwd": cwd, "mem": mem})

    def env(self, extra=None):
        env = {"PATH": self.bin + ":/usr/bin:/bin", "HOME": self.home, "PANTHEON_HOME": self.pantheon,
               "PANTHEON_STATE": self.state, "PANTHEON_NOW": str(T0), "PANTHEON_HOST": "mac-a",
               "PANTHEON_FAKE_SWAP": "1.0", "PANTHEON_FAKE_PRESSURE": "1", "PANTHEON_FAKE_LOAD": "0",
               "PANTHEON_FAKE_PROCS": json.dumps(self.procs), "PANTHEON_FAKE_KILL_LOG": self.kills,
               "FAKE_AGENTS": self.agents_file, "TMPDIR": _ROOT}
        env.update(extra or {})
        return env

    def reap(self, *args, extra=None):
        return subprocess.run([PY311, "-I", LIB, "reap", *args], env=self.env(extra), capture_output=True, text=True,
                              timeout=60)

    def watch_check(self, t, agents=None, extra=None):
        code = ("import importlib.util, json, sys\n"
                "spec = importlib.util.spec_from_file_location('pantheon', sys.argv[1])\n"
                "m = importlib.util.module_from_spec(spec); sys.modules['pantheon'] = m; spec.loader.exec_module(m)\n"
                "m.culprits_mod().watch_check(json.loads(sys.argv[3]), float(sys.argv[2]))\n")
        return subprocess.run([PY311, "-I", "-c", code, LIB, str(t), json.dumps(agents or [])],
                              env=self.env(dict({"PANTHEON_NOW": str(t)}, **(extra or {}))), capture_output=True,
                              text=True, timeout=60)

    def killed(self):
        if not os.path.exists(self.kills):
            return {}
        out = {}
        for ln in open(self.kills):
            pid, sig = ln.split()
            out.setdefault(int(pid), []).append(int(sig))
        return out

    def alerts(self):
        p = os.path.join(self.pantheon, "alerts.md")
        return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def standard(e):
    """Набор процессов: брошенные, своё живое, claude, чужое, молодой, сироты multiprocessing."""
    e.proc(101, "node /x/node_modules/.bin/tsx zprobe1.ts", e.wt_gone)                     # копия удалена
    e.proc(102, "node /x/node_modules/vitest/vitest.mjs run", e.wt_closed, mem=2048)        # задача закрыта
    e.proc(103, "node /x/node_modules/.bin/next dev", e.wt_live)                             # задача открыта
    e.proc(104, "claude -p разбор", e.wt_gone)                                               # claude — не гасим
    e.proc(105, "node server.js", "/elsewhere/project")                                      # чужое
    e.proc(106, "node young.ts", e.wt_gone, age=10 * 60)                                     # моложе 2 ч
    e.proc(107, "/usr/bin/python3 -I -c from multiprocessing.resource_tracker import main;main(8)",
           os.path.join(e.state, "plugins", "tmp", "guard-x"), ppid=1)                       # сирота в состоянии
    e.proc(108, "python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=9, pipe_handle=17) "
                "--multiprocessing-fork", e.repo, ppid=4242)                                 # живой пул — не наш вид
    e.proc(109, "python3 -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=9, pipe_handle=19) "
                "--multiprocessing-fork", "/elsewhere/project", ppid=1)                       # сирота чужая
    e.proc(110, "pnpm install", e.repo)                                                      # папка направления
    e.proc(111, "/usr/bin/vim notes.md", e.wt_gone)                                          # не наш вид


def test_dry_run():
    e = Env()
    standard(e)
    r = e.reap()
    out = r.stdout
    check(r.returncode == 0, f"сухой прогон: код 0 ({r.returncode} {r.stderr})")
    check(not e.killed(), f"сухой прогон ничего не гасит: {e.killed()}")
    line = {int(ln.split()[1]): ln for ln in out.splitlines() if ln.startswith("pid ")}
    check("брошен" in line.get(101, "") and "worktree удалён" in line.get(101, ""), f"101 удалённая копия: {line.get(101)}")
    check("брошен" in line.get(102, "") and "athena-0002 done" in line.get(102, ""), f"102 закрытая задача: {line.get(102)}")
    check("спросить" in line.get(103, "") and "athena-0001" in line.get(103, ""), f"103 живая копия: {line.get(103)}")
    check("спросить" in line.get(104, "") and "claude сам не гашу" in line.get(104, ""), f"104 claude: {line.get(104)}")
    check("чужое" in line.get(105, ""), f"105 чужое: {line.get(105)}")
    check(106 not in line and 108 not in line and 111 not in line, f"молодой, живой пул и vim — не в списке: {sorted(line)}")
    check("брошен" in line.get(107, "") and "multiprocessing" in line.get(107, ""), f"107 сирота: {line.get(107)}")
    check("чужое" in line.get(109, ""), f"109 сирота вне папок Пантеона — чужое: {line.get(109)}")
    check("спросить" in line.get(110, "") and "папка направления" in line.get(110, ""), f"110: {line.get(110)}")
    check("2.0 ГБ" in line.get(102, ""), f"память из top (mem) в МБ → ГБ: {line.get(102)}")


def test_apply_kills_only_abandoned():
    e = Env()
    standard(e)
    r = e.reap("--apply", extra={"PANTHEON_TASK": "metis-9999"})
    k = e.killed()
    check(r.returncode == 0, f"--apply: код 0 ({r.returncode} {r.stdout[-300:]} {r.stderr})")
    check(set(k) == {101, 102, 107}, f"--apply гасит только брошенное (101, 102, 107): {sorted(k)}")
    check(all(v == [int(signal.SIGTERM)] for v in k.values()), f"сигнал — SIGTERM: {k}")
    check("[metis-9999] Погасить процессы Пантеона" in r.stdout and "pid 103" in r.stdout and "pid 110" in r.stdout
          and "pid 105" not in r.stdout.split("вопрос")[-1], f"вопрос об остальном своём с [id]: {r.stdout[-500:]}")
    check("reap --apply --pid 103 104 110" in r.stdout, f"готовая команда после «да»: {r.stdout[-300:]}")
    a = e.alerts()
    check("погашены брошенные процессы" in a and "pid 101" in a and "pid 105" not in a, f"строка в alerts.md: {a[-400:]}")


def test_pid_needs_consent_in_hestia():
    e = Env()
    standard(e)
    hs = {"PANTHEON_ROLE": "hestia", "PANTHEON_TASK": "metis-9999"}
    r = e.reap("--apply", "--pid", "103", extra=hs)
    check(r.returncode == 2 and "pantheon consent metis-9999" in r.stderr and not e.killed(),
          f"Гестия без метки consent: код 2, ничего не гасит ({r.returncode} {r.stderr} {e.killed()})")
    d = os.path.join(e.state, "hestia-consent")
    os.makedirs(d)
    open(os.path.join(d, "metis-9999"), "w").write("x\n")
    r = e.reap("--apply", "--pid", "103", extra=hs)
    check(r.returncode == 2 and not e.killed(), f"метка push (без .reap) гасить не пускает: {r.returncode}")
    os.remove(os.path.join(d, "metis-9999"))

    def answer(question, ans, head="· окно вопросов"):
        os.makedirs(os.path.join(e.state, "owner-log"), exist_ok=True)
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(T0 - 60))
        open(os.path.join(e.state, "owner-log", "zeus.md"), "w").write(
            f"## {when} {head}\nвопрос: {question}\nответ: {ans}\n")
        return subprocess.run([PY311, "-I", LIB, "consent", "metis-9999"], env=e.env(hs), capture_output=True,
                              text=True, timeout=60)

    # «да» на вопрос о гашении — метка <id>.reap со списком pid из вопроса, метки push нет
    q = ("[metis-9999] Погасить процессы Пантеона: pid 103 next (athena-x, 512 МБ, 3 ч), pid 105 node, pid 104 claude, "
         "pid 106 node young.ts?")
    c = answer(q, "Да — погасить")
    check(c.returncode == 0 and os.path.isfile(os.path.join(d, "metis-9999.reap"))
          and not os.path.exists(os.path.join(d, "metis-9999")), f"consent на гашение — метка .reap: {c.stdout} {c.stderr}")
    r = e.reap("--apply", "--pid", "103", "105", "104", "106", "999", "110", extra=hs)
    k = e.killed()
    check(set(k) == {103, 106}, f"с меткой: гасит своё из вопроса (103, молодой 106), не чужое 105, не claude 104, "
          f"не 110 вне вопроса: {sorted(k)}")
    check(r.returncode == 1 and "отказ: pid 105" in r.stdout and "отказ: pid 104" in r.stdout
          and "отказ: pid 999" in r.stdout and "pid 110 — не из вопроса" in r.stdout,
          f"отказы названы, код 1: {r.returncode} {r.stdout[-500:]}")
    check("по «да» владельца" in e.alerts(), "строка в alerts.md о гашении по «да»")
    # метка другой задачи не годится
    os.remove(os.path.join(e.kills))
    r = e.reap("--apply", "--pid", "103", extra={"PANTHEON_ROLE": "hestia", "PANTHEON_TASK": "metis-1111"})
    check(r.returncode == 2 and not e.killed(), f"метка чужой задачи — отказ: {r.returncode}")
    # «да» на вопрос о push — метка push, не .reap
    os.remove(os.path.join(d, "metis-9999.reap"))
    c = answer("[metis-9999] Отправить ветку в PR?", "Да — отправить")
    check(c.returncode == 0 and os.path.isfile(os.path.join(d, "metis-9999"))
          and not os.path.exists(os.path.join(d, "metis-9999.reap")), f"consent на push — метка push: {c.stderr}")
    os.remove(os.path.join(d, "metis-9999"))
    os.remove(os.path.join(e.state, "owner-log", "zeus.md"))
    with open(os.path.join(e.state, "owner-log", "board.jsonl"), "w") as fh:
        fh.write(json.dumps({"kind": "answer", "id": "metis-9999", "question": q, "answer": "Да — погасить",
                             "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T0 - 60))}) + "\n")
    c = subprocess.run([PY311, "-I", LIB, "consent", "metis-9999"], env=e.env(hs), capture_output=True, text=True,
                       timeout=60)
    check(c.returncode == 1 and "галочкой на доске" in c.stdout and not os.listdir(d),
          f"гашение не по галочке доски: {c.returncode} {c.stdout} {os.listdir(d)}")


def test_usage_and_unreadable():
    e = Env()
    standard(e)
    for args in (["--pid", "103"], ["--bogus"], ["--apply", "--pid", "x"]):
        r = e.reap(*args)
        check(r.returncode == 2 and not e.killed(), f"reap {' '.join(args)} — код 2: {r.returncode} {r.stderr}")
    r = e.reap("--apply", extra={"PANTHEON_FAKE_PROCS": "не json"})
    check(r.returncode == 3 and "не прочитан" in r.stderr.strip().splitlines()[-1], f"ps не прочитан — код 3: "
          f"{r.returncode} {r.stderr}")
    w = e.watch_check(T0, extra={"PANTHEON_FAKE_SWAP": "9", "PANTHEON_FAKE_PROCS": "не json"})
    check(w.returncode != 0 and "ps" in w.stderr, f"проверка дежурного падает при нечитаемом ps: {w.stderr[-200:]}")


def test_watch_alert_once_per_episode():
    e = Env()
    standard(e)
    red = {"PANTHEON_FAKE_SWAP": "9"}
    w = e.watch_check(T0, agents=[{"pid": 103, "name": "athena-x", "state": "working"}], extra=red)
    a = e.alerts()
    check(w.returncode == 0 and a.count("виновники памяти") == 1, f"красная зона — одна тревога: {w.stderr} {a[-300:]}")
    check("своп 9.0 ГБ" in a and "→ сессия athena-x →" in a and "worktree удалён" not in a
          and "athena-x, worktree agent-gone" in a and "2.0 ГБ" in a and "3 ч" in a,
          f"таблица «процесс → чей → память → возраст»: {a[-700:]}")
    check("Брошено: 3" in a and "pantheon reap --apply" in a and "wake hestia" in a, f"что делать Зевсу: {a[-300:]}")
    check(not e.killed(), "дежурный сам ничего не гасит")
    e.watch_check(T0 + 300, extra=red)
    e.watch_check(T0 + 300 + 3000, extra=red)
    check(e.alerts().count("виновники памяти") == 1, "тот же эпизод (перерывы меньше часа) — без повтора")
    e.watch_check(T0 + 300 + 3000 + 600, extra={"PANTHEON_FAKE_SWAP": "1"})
    check(e.alerts().count("виновники памяти") == 1, "зелёная зона — без тревоги")
    e.watch_check(T0 + 300 + 3000 + 3700, extra=red)
    check(e.alerts().count("виновники памяти") == 2, "красная зона после часа без неё — новый эпизод, новая тревога")


def test_watch_red_reasons():
    e = Env()
    standard(e)
    e.watch_check(T0, extra={"PANTHEON_FAKE_LOAD": "1000"})
    check("нагрузка 1000" in e.alerts(), f"нагрузка выше порога — красная зона: {e.alerts()[-300:]}")
    e2 = Env()
    standard(e2)
    e2.watch_check(T0, extra={"PANTHEON_FAKE_PRESSURE": "4"})
    check("давление памяти критичное" in e2.alerts(), "давление памяти — красная зона")
    e3 = Env()
    standard(e3)
    e3.watch_check(T0)
    check("виновники" not in e3.alerts(), "зелёная зона — тревоги нет")
    e4 = Env()
    e4.proc(1, "node young.ts", e4.wt_gone, age=60)
    e4.watch_check(T0, extra={"PANTHEON_FAKE_SWAP": "9"})
    check("виновники" not in e4.alerts(), "красная зона без виновников старше 2 ч — строки нет")
    e4.procs = []
    e4.proc(2, "node old.ts", e4.wt_gone)
    e4.watch_check(T0 + 300, extra={"PANTHEON_FAKE_SWAP": "9"})
    check(e4.alerts().count("виновники памяти") == 1, "виновник появился в том же эпизоде — тревога одна, но есть")


def test_kind_parse():
    code = ("import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('c', sys.argv[1]); m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "cases = [('claude --agent x', None), ('/opt/homebrew/bin/node a.js', None), ('next-server (v16.0.1)', None),"
            " ('npm exec tsx /w/a.ts', None), ('node /n/pnpm/bin/pnpm.cjs dev', None), ('/usr/bin/vim x', None),"
            " ('python3 -c from multiprocessing.resource_tracker import main;main(8)', 1),"
            " ('python3 -c from multiprocessing.resource_tracker import main;main(8)', 77)]\n"
            "print(json.dumps([m.kind_of(a, p) for a, p in cases] + [m._etime(x) for x in ('05:24', '2:03:04', "
            "'4-01:00:00', 'x')] + [m._mb(x) for x in ('1235M', '2G+', '512K')]))\n")
    r = subprocess.run([PY311, "-I", "-c", code, os.path.join(ROOT, "lib", "culprits.py")], capture_output=True,
                       text=True, timeout=30)
    got = json.loads(r.stdout or "null")
    want = ["claude", "node", "next", "tsx", "pnpm", None, "python-mp", None, 324, 7384, 349200, None, 1235.0, 2048.0,
            0.5]
    check(got == want, f"виды и разбор полей ps/top: {got}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        try:
            fn()
        except Exception as ex:  # noqa: BLE001
            FAILS.append(f"{fn.__name__}: {type(ex).__name__}: {ex}")
            print("ОШИБКА:", fn.__name__, type(ex).__name__, ex)
    print(f"{TOTAL - len(FAILS)} из {TOTAL} прошли; тестов: {len(tests)}, не прошло: {len(FAILS)}")
    sys.exit(1 if FAILS else 0)
