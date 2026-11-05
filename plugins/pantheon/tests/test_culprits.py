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
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
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
        self.launchctl = os.path.join(self.tmp, "launchctl.txt")  # вывод поддельного `launchctl list`
        open(self.launchctl, "w").write("PID\tStatus\tLabel\n-\t0\tcom.apple.x\n")
        with open(os.path.join(self.bin, "launchctl"), "w") as fh:
            fh.write('#!/bin/sh\n[ "$1" = list ] || exit 64\ncat "$FAKE_LAUNCHCTL"\n')
        os.chmod(os.path.join(self.bin, "launchctl"), 0o755)
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
               "FAKE_AGENTS": self.agents_file,
               "FAKE_LAUNCHCTL": self.launchctl, "TMPDIR": _ROOT}
        env.update(extra or {})
        return env

    def reap(self, *args, extra=None):
        return subprocess.run([PY311, "-I", RUN_PY, "reap", *args], env=self.env(extra), capture_output=True, text=True,
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
        return subprocess.run([PY311, "-I", RUN_PY, "consent", "metis-9999"], env=e.env(hs), capture_output=True,
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
    c = subprocess.run([PY311, "-I", RUN_PY, "consent", "metis-9999"], env=e.env(hs), capture_output=True, text=True,
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


def auto_set(e):
    """Набор для reap --auto (metis-0617): что гасится и что нет. Возраст по умолчанию — 40 мин."""
    m = 40 * 60
    sb = os.path.join(e.home, "Library", "Caches", "pantheon-sandbox", "athena-x", "tmp", "run1")
    mp = "{py} -I -c from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=9, pipe_handle=1{n}) " \
         "--multiprocessing-fork"
    fw = "/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
    guardtmp = os.path.join(e.state, "plugins", "tmp", "guard-_9i3yizq", "base", "plugins", "guard")
    e.proc(201, mp.format(py=fw, n=1), guardtmp, age=m, ppid=1, mem=40)          # сирота mp (python.org: Python.app)
    e.proc(218, mp.format(py="python3", n=2), guardtmp, age=m, ppid=1, mem=60)   # вторая — той же строкой
    e.proc(202, mp.format(py="python3", n=3), guardtmp, age=10 * 60, ppid=1)     # моложе 30 мин
    e.proc(203, "node /x/node_modules/.bin/tsx zprobe1.ts", e.wt_gone, age=m, ppid=1)     # копия удалена
    e.proc(204, "node /x/node_modules/vitest/vitest.mjs run", e.wt_closed, age=m, ppid=1)  # задача закрыта
    e.proc(205, "node /x/node_modules/.bin/next dev", e.wt_live, age=m)          # задача открыта — не трогаем
    e.proc(206, "claude -p разбор", e.wt_gone, age=m, ppid=1)                     # claude — никогда
    e.proc(207, "node server.js", "/elsewhere/project", age=m, ppid=1)            # чужое
    e.proc(208, "/opt/homebrew/opt/node/bin/node /opt/homebrew/bin/pyright-langserver --stdio", e.wt_live, age=m,
           ppid=1)                                                # LSP прямо под launchd в живой копии — одного ppid 1 мало
    e.proc(261, "/opt/homebrew/opt/node/bin/node /opt/homebrew/bin/pyright-langserver --stdio", e.wt_gone, age=m,
           ppid=1)                                                                  # ничей LSP в удалённой копии
    e.proc(300, "claude -r 081685bd", e.wt_live, age=m, ppid=1)
    e.proc(209, "node /opt/homebrew/bin/pyright-langserver --stdio", e.repo, age=m, ppid=300)  # родитель claude жив
    e.proc(301, "/Applications/Visual Studio Code.app/Contents/MacOS/Electron", "/", age=m, ppid=1)
    e.proc(210, "/Applications/Visual Studio Code.app/Contents/Frameworks/Code Helper (Plugin).app/Contents/MacOS/"
                "Code Helper (Plugin) /x/typescript/lib/tsserver.js --serverMode partialSemantic", "/", age=m, ppid=301)
    e.proc(302, "/bin/sh /usr/local/bin/lsp-wrap.sh", "/x", age=m, ppid=1)    # обёртка, её родитель умер
    e.proc(211, "node /usr/local/bin/typescript-language-server --stdio", e.repo, age=m, ppid=302)  # через обёртку
    e.proc(247, "node /x/node_modules/typescript/lib/tsserver.js --useNodeIpc", e.repo, age=m, ppid=211)  # LSP под LSP
    e.proc(303, "nvim notes.ts", "/x", age=m, ppid=1)
    e.proc(212, "node /usr/local/bin/typescript-language-server --stdio", e.repo, age=m, ppid=303)  # родитель — редактор
    e.proc(217, "node /opt/homebrew/bin/pyright-langserver --stdio", e.repo, age=m, ppid=999)      # родителя нет в ps
    e.proc(213, "node /x/node_modules/.bin/vitest run", sb, age=m, ppid=1)       # сирота в песочнице окна
    e.proc(258, "/bin/zsh -c make check", sb, age=m, ppid=1)                    # живой родитель (не наш вид)
    e.proc(214, "node /x/node_modules/.bin/vitest run", sb, age=m, ppid=258)     # в песочнице, но родитель жив
    e.proc(219, "claude bg-pty-host --bg-pty-host /x.sock", sb, age=m, ppid=1)   # claude в песочнице с ppid 1 — никогда
    e.proc(215, "node /Applications/Google Chrome.app/Contents/Frameworks/x/helper.js", e.wt_gone, age=m,
           ppid=1)                                                                  # приложение
    e.proc(216, mp.format(py="python3", n=4), "/elsewhere/project", age=m, ppid=1)  # сирота mp вне Пантеона
    # проверка безопасности 04.11, находка 1: слово в строке — не сервер; родитель со словом — не сервер
    e.proc(240, "SCREEN -dmS tsserver", e.wt_live, age=m, ppid=1)
    e.proc(242, "python3 x.py --name tsserver", e.repo, age=m, ppid=1)
    e.proc(241, "node /usr/local/bin/typescript-language-server --stdio", e.repo, age=m, ppid=242)
    # находка 2: долгоживущий node и node с cli.js Claude Code — живые хозяева, не запускалки
    e.proc(244, "node /srv/server.js", e.repo, age=m, ppid=1)
    e.proc(243, "node /opt/homebrew/bin/pyright-langserver --stdio", e.repo, age=m, ppid=244)
    e.proc(246, "node /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js --resume x", e.repo, age=m, ppid=1)
    e.proc(245, "node /opt/homebrew/bin/pyright-langserver --stdio", e.repo, age=m, ppid=246)
    # находка 3: чьё — по cwd, не по пути в командной строке; cwd нет — не гасим
    e.proc(248, f"node /x/node_modules/.bin/tsx {e.wt_gone}/a.ts", "/elsewhere/project", age=m, ppid=1)
    e.proc(249, f"node /x/node_modules/.bin/tsx {e.wt_gone}/b.ts", None, age=m, ppid=1)
    e.proc(250, "pyright-langserver --stdio", "/opt/homebrew/Cellar/pyright/dist", age=m, ppid=1)  # LSP вне Пантеона
    # находка 4: выше по цепочке живая claude или сессия из claude agents — не гасим
    e.proc(252, "/bin/zsh -c pnpm test", e.wt_gone, age=m, ppid=300)
    e.proc(251, "node /x/node_modules/.bin/vitest run", e.wt_gone, age=m, ppid=252)
    e.proc(254, "node /x/agent-runner.js", e.wt_closed, age=m, ppid=1)
    e.proc(253, "node /x/node_modules/.bin/tsx c.ts", e.wt_closed, age=m, ppid=254)
    e.proc(255, "node /x/node_modules/.bin/vitest run", e.wt_gone, age=m, ppid=246)  # родитель — node с cli.js claude
    e.proc(256, "node /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js -p x", e.wt_gone, age=m, ppid=1)
    e.proc(257, "node /x/node_modules/.bin/tsx d.ts", e.wt_gone, age=m, ppid=4243)  # родителя нет в ps — не прослежено
    e.proc(260, "/Applications/Foo.app/Contents/Resources/bin/sh -c serve", e.repo, age=m, ppid=1)  # sh из приложения
    e.proc(259, "node /opt/homebrew/bin/pyright-langserver --stdio", e.repo, age=m, ppid=260)
    # круг 2, находка 2: вид — по исполняемому файлу, слово next/pnpm в аргументах SCREEN и tmux вида не даёт
    for i, cwd in enumerate((e.wt_closed, e.wt_gone, sb)):
        e.proc(266 + 2 * i, "SCREEN -dmS next", cwd, age=m, ppid=1)
        e.proc(267 + 2 * i, "tmux new -s pnpm", cwd, age=m, ppid=1)
    # круг 2, находка 3: окно песочницы с живой сессией — по имени сессии, по settings/run/<имя>.json, по job-<роль>
    sbw = os.path.join(e.home, "Library", "Caches", "pantheon-sandbox")
    for w in ("athena-live", "hq", "job-iris"):
        os.makedirs(os.path.join(sbw, w, "tmp"), exist_ok=True)
    e.proc(262, "node /x/node_modules/.bin/vitest run", os.path.join(sbw, "athena-live", "tmp"), age=m, ppid=1)
    e.proc(263, "node /x/node_modules/.bin/vitest run", os.path.join(sbw, "hq", "tmp"), age=m, ppid=1)
    os.makedirs(os.path.join(e.state, "settings", "run"), exist_ok=True)
    json.dump({"env": {"PANTHEON_WINDOW": "hq"}}, open(os.path.join(e.state, "settings", "run", "zeus.json"), "w"))
    e.proc(304, "claude -p --agent iris разбор", "/", age=m, ppid=1)
    e.proc(264, "node /x/node_modules/.bin/vitest run", os.path.join(sbw, "job-iris", "tmp"), age=m, ppid=1)
    # задачи launchd: сам процесс или его предок — не трогаем
    e.proc(272, "node /x/node_modules/.bin/tsx e.ts", e.wt_gone, age=m, ppid=1)
    e.proc(273, "/bin/sh /x/run-job.sh", e.wt_gone, age=m, ppid=1)
    e.proc(274, "node /x/node_modules/.bin/tsx f.ts", e.wt_gone, age=m, ppid=273)
    # mp: процесс с живым родителем-python — не сирота; multiprocessing в аргументах не-python — не mp
    e.proc(305, "python3 -I tests/test_shell_diff.py", guardtmp, age=m, ppid=1)
    e.proc(275, mp.format(py="python3", n=5), guardtmp, age=m, ppid=305)
    e.proc(277, "SCREEN -dmS w " + mp.format(py="python3", n=6), guardtmp, age=m, ppid=1)
    open(e.launchctl, "w").write("PID\tStatus\tLabel\n-\t0\tcom.apple.x\n272\t0\tcom.x.a\n273\t0\tcom.x.b\n")
    json.dump([{"id": "s254", "name": "athena-dev", "pid": 254, "kind": "interactive", "state": "working"},
               {"id": "s9001", "name": "athena-live", "pid": 9001, "kind": "interactive", "state": "working"},
               {"id": "s9002", "name": "zeus", "pid": 9002, "kind": "interactive", "state": "working"}],
              open(e.agents_file, "w"))


def test_auto_kills_only_abandoned():
    e = Env()
    auto_set(e)
    r = e.reap("--auto")
    k = e.killed()
    check(r.returncode == 0, f"reap --auto: код 0 ({r.returncode} {r.stdout[-300:]} {r.stderr[-300:]})")
    want = {201, 218, 203, 204, 261, 211, 213, 247}
    check(set(k) == want, f"reap --auto гасит только брошенное {sorted(want)}: {sorted(k)}; лишнее "
          f"{sorted(set(k) - want)}, не погашено {sorted(want - set(k))}")
    check(all(v == [int(signal.SIGTERM)] for v in k.values()), f"сигнал — SIGTERM: {k}")
    lines = [ln for ln in e.alerts().splitlines() if "· reap --auto · погашено: " in ln]
    check(len(lines) == 7, f"строка «погашено» на каждое гашение (две сироты mp одной строкой): {len(lines)} {lines}")
    mp = next((ln for ln in lines if "spawn_main" in ln), "")
    check("×2 (pid 201, 218)" in mp and "чьё: состояние Пантеона" in mp and "почему: сирота multiprocessing" in mp
          and mp.endswith(", 100 МБ"), f"строка: что, чьё, почему, МБ (40 + 60): {mp}")
    lsp = next((ln for ln in lines if "pid 261" in ln), "")
    check("lsp pyright-langserver" in lsp and "без живого родителя-claude" in lsp, f"строка о language server: {lsp}")
    vl = next((ln for ln in lines if "pid 204" in ln), "")
    check("погашено: vitest" in vl, f"вид — по скрипту node (vitest.mjs): {vl}")
    sbl = next((ln for ln in lines if "pid 213" in ln), "")
    check("песочница окна" in sbl and "ppid 1" in sbl, f"строка о сироте в песочнице: {sbl}")
    check("worktree удалён" in e.alerts() and "athena-0002 done" in e.alerts(), "причины worktree и закрытой задачи")
    r = e.reap("--auto", extra={"PANTHEON_FAKE_PROCS": json.dumps([p for p in e.procs if p["pid"] not in want])})
    check(r.returncode == 0 and "нет" in r.stdout and len([ln for ln in e.alerts().splitlines() if "погашено" in ln]) == 7,
          f"нечего гасить — код 0, без строк: {r.stdout}")


def test_auto_zeus_window_without_run_file():
    """metis-0805, Д1: окно Зевса — сессия zeus, песочница hq, запуск с settings/hq.json, файла run/zeus.json нет.
    Сирота (ppid 1) в песочнице hq при живом Зевсе не гасится: окно — по имени (zeus → hq), по --settings и --name
    живого claude из ps, по реестру имён ~/.claude/sessions. Без живого Зевса — гасится (проверка чувствительна)."""
    m = 40 * 60
    for how in ("agents", "settings", "name", "registry", "run-settings", "none"):
        e = Env()
        sb = os.path.join(e.home, "Library", "Caches", "pantheon-sandbox", "hq", "tmp")
        os.makedirs(sb)
        e.proc(263, "node /x/node_modules/.bin/vitest run", sb, age=m, ppid=1)
        if how == "agents":
            json.dump([{"id": "s9002", "name": "zeus", "pid": 9002, "kind": "background", "state": "working"}],
                      open(e.agents_file, "w"))
        elif how == "settings":
            e.proc(310, f"claude --agent hq --settings {e.state}/settings/hq.json", e.pantheon, age=m, ppid=1)
        elif how == "name":
            e.proc(310, "/Users/x/.local/bin/claude --name zeus", e.pantheon, age=m, ppid=1)
        elif how == "registry":
            os.makedirs(os.path.join(e.home, ".claude", "sessions"))
            json.dump({"pid": os.getpid(), "name": "zeus", "kind": "interactive", "cwd": e.pantheon},
                      open(os.path.join(e.home, ".claude", "sessions", f"{os.getpid()}.json"), "w"))
        elif how == "run-settings":  # файл запуска другого имени, окно в нём — hq
            os.makedirs(os.path.join(e.state, "settings", "run"))
            json.dump({"env": {"PANTHEON_WINDOW": "hq"}}, open(os.path.join(e.state, "settings", "run", "x.json"), "w"))
            e.proc(310, f"claude --settings {e.state}/settings/run/x.json", e.pantheon, age=m, ppid=1)
        check(not os.path.exists(os.path.join(e.state, "settings", "run", "zeus.json")), "файла run/zeus.json нет")
        r = e.reap("--auto")
        k = e.killed()
        if how == "none":
            check(set(k) == {263}, f"Д1: живого Зевса нет — сирота в песочнице hq гасится: {sorted(k)} {r.stdout[-300:]}")
        else:
            check(r.returncode == 0 and not k, f"Д1: живой Зевс ({how}) — сирота в песочнице hq не гасится: "
                  f"{sorted(k)} {r.returncode} {r.stderr[-300:]}")


def test_auto_outside_holds():
    """metis-0805, Д3: `run.py outside` (идущий outside test, serve, проход outside run) — держатель, как claude. Его
    дети в копии закрытой задачи не гасятся, и сирота с ppid 1 в группе его прогона (pgid) — тоже. Сирота из группы,
    где живых хозяев нет, и ребёнок другого python-скрипта со словом outside — гасятся."""
    m = 40 * 60
    e = Env()
    py = "/Library/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
    e.proc(320, f"{py} -I /c/pantheon/0.11.211/bin/../lib/run.py outside run", "/", age=m, ppid=1)
    e.proc(321, f"{py} /c/pantheon/bin/heavy /usr/bin/sandbox-exec -f /s/profile.sb pnpm test", e.wt_closed, age=m,
           ppid=320)
    e.procs[-1]["pgid"] = 321
    e.proc(322, "node /x/node_modules/.bin/vitest run", e.wt_closed, age=m, ppid=321)     # ребёнок прогона
    e.procs[-1]["pgid"] = 321
    e.proc(323, "node /x/node_modules/.bin/vitest run", e.wt_closed, age=m, ppid=1)       # ушёл к launchd, группа жива
    e.procs[-1]["pgid"] = 321
    e.proc(324, "node /x/node_modules/.bin/vitest run", e.wt_closed, age=m, ppid=1)       # группы нет — брошен
    e.procs[-1]["pgid"] = 999
    e.proc(330, "node /x/node_modules/.bin/tsx g.ts", e.wt_closed, age=m, ppid=1)         # группа без хозяина
    e.procs[-1]["pgid"] = 330
    e.proc(331, "node /x/node_modules/.bin/vitest run", e.wt_closed, age=m, ppid=1)
    e.procs[-1]["pgid"] = 330
    e.proc(326, "python3 /x/tool.py outside run", "/", age=m, ppid=1)                     # не run.py — не держатель
    e.proc(327, "node /x/node_modules/.bin/vitest run", e.wt_closed, age=m, ppid=326)
    e.proc(328, f"{py} -I /p/lib/run.py outside serve --wait 120", "/", age=m, ppid=1)    # serve — тоже держатель
    e.proc(329, "node /x/node_modules/.bin/next dev", e.wt_closed, age=m, ppid=328)
    r = e.reap("--auto")
    k = e.killed()
    want = {324, 330, 331, 327}
    check(r.returncode == 0 and set(k) == want, f"Д3: держатель outside — дети и группа прогона не гасятся, гасится "
          f"{sorted(want)}: {sorted(k)}; лишнее {sorted(set(k) - want)} {r.stderr[-300:]}")


def test_auto_lsp_family():
    """metis-0805, Д2: language server под щадимым родителем не гасится отдельно — решение за семью вместе.
    typescript-language-server прямо под launchd в живой копии жив — его tsserver тоже; молодой tsserver под ничьим
    сервером — родителя не гасим, пока ребёнок моложе AUTO_MINUTES. Ничья семья старше срока — гасится вся."""
    m = 40 * 60
    e = Env()
    e.proc(340, "node /usr/local/bin/typescript-language-server --stdio", e.wt_live, age=m, ppid=1)
    e.proc(341, "node /x/node_modules/typescript/lib/tsserver.js --useNodeIpc", e.wt_live, age=m, ppid=340)
    e.proc(342, "/bin/sh /usr/local/bin/lsp-wrap.sh", "/x", age=m, ppid=1)
    e.proc(343, "node /usr/local/bin/typescript-language-server --stdio", e.repo, age=m, ppid=342)
    e.proc(344, "node /x/node_modules/typescript/lib/tsserver.js --useNodeIpc", e.repo, age=5 * 60, ppid=343)
    e.proc(345, "/bin/sh /usr/local/bin/lsp-wrap.sh", "/x", age=m, ppid=1)
    e.proc(346, "node /usr/local/bin/typescript-language-server --stdio", e.repo, age=m, ppid=345)
    e.proc(347, "node /x/node_modules/typescript/lib/tsserver.js --useNodeIpc", e.repo, age=m, ppid=346)
    e.proc(348, "node /x/node_modules/typescript/lib/tsserver.js --useNodeIpc", e.repo, age=m, ppid=346)
    # metis-0815 (мутант M7c: корень — ближний предок, reversed(chain) → chain): pnpm (ppid 1) → language server →
    # tsserver в живой копии — корень семьи pnpm, а не ближний language server; никого не гасим
    e.proc(350, "/usr/local/bin/pnpm exec typescript-language-server --stdio", e.wt_live, age=m, ppid=1)
    e.proc(351, "node /usr/local/bin/typescript-language-server --stdio", e.wt_live, age=m, ppid=350)
    e.proc(352, "node /x/node_modules/typescript/lib/tsserver.js --useNodeIpc", e.wt_live, age=m, ppid=351)
    r = e.reap("--auto")
    k = e.killed()
    want = {346, 347, 348}
    check(r.returncode == 0 and set(k) == want, f"Д2: семья language server — вместе; гасится только ничья старше "
          f"срока {sorted(want)}: {sorted(k)}; лишнее {sorted(set(k) - want)} {r.stderr[-300:]}")
    check(not {350, 351, 352} & set(k), f"metis-0815: pnpm → language server → tsserver в живой копии — никого: {sorted(k)}")


def test_outside_like():
    code = ("import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('c', sys.argv[1]); m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "cases = ['/F/Python.app/Contents/MacOS/Python -I /c/bin/../lib/run.py outside test --wait 590',"
            " 'python3.14 -I /p/lib/run.py outside serve', 'python3 /p/lib/run.py outside', 'python3 /p/lib/run.py reap',"
            " 'python3 /x/tool.py outside run', 'node /p/lib/run.py outside test', 'sh -c python3 run.py outside',"
            " 'python3 -I /p/lib/run.py', '']\n"
            "print(json.dumps([m.outside_like(a) for a in cases]))\n")
    r = subprocess.run([PY311, "-I", "-c", code, os.path.join(ROOT, "lib", "culprits.py")], capture_output=True,
                       text=True, timeout=30)
    got = json.loads(r.stdout or "null")
    check(got == [True, True, True, False, False, False, False, False, False],
          f"outside_like — python …/run.py outside, по исполняемому файлу: {got} {r.stderr[-300:]}")


def test_auto_usage_and_errors():
    e = Env()
    auto_set(e)
    for args in (["--auto", "--apply"], ["--auto", "--pid", "203"], ["--auto", "--auto"]):
        r = e.reap(*args)
        check(r.returncode == 2 and not e.killed(), f"reap {' '.join(args)} — код 2: {r.returncode} {r.stderr}")
    r = e.reap("--auto", extra={"PANTHEON_FAKE_PROCS": "не json"})
    check(r.returncode == 3 and "не прочитан" in r.stderr.strip().splitlines()[-1] and not e.killed(),
          f"ps не прочитан — код 3: {r.returncode} {r.stderr}")
    keep = open(e.agents_file).read()
    open(e.agents_file, "w").write("не json")
    r = e.reap("--auto")
    check(r.returncode == 3 and "сессий" in r.stderr.strip().splitlines()[-1] and not e.killed()
          and "погашено" not in e.alerts(), f"claude agents не прочитан — проход пропущен, код 3: {r.returncode} {r.stderr}")
    os.remove(os.path.join(e.bin, "claude"))
    r = e.reap("--auto")
    check(r.returncode == 3 and "сессий" in r.stderr.strip().splitlines()[-1] and not e.killed(),
          f"claude не запустить — проход пропущен, код 3: {r.returncode} {r.stderr[-300:]}")
    open(e.agents_file, "w").write(keep)  # список сессий верный — сбой только в коде и выводе claude
    # круг 2, находка 1: строго — код не 0, пустой вывод, вывод из пробелов — не список
    for body, what in (('exit 1\n', "код 1 без вывода"), ('cat "$FAKE_AGENTS"; exit 1\n', "код 1 со списком"),
                       ('exit 0\n', "код 0 без вывода"), ('printf "  \\n\\t\\n"\n', "вывод из пробелов")):
        open(os.path.join(e.bin, "claude"), "w").write("#!/bin/sh\n" + body)
        os.chmod(os.path.join(e.bin, "claude"), 0o755)
        r = e.reap("--auto")
        check(r.returncode == 3 and "сессий" in r.stderr.strip().splitlines()[-1] and not e.killed(),
              f"claude agents: {what} — проход пропущен, код 3: {r.returncode} {r.stderr[-300:]}")
    open(os.path.join(e.bin, "claude"), "w").write('#!/bin/sh\ncat "$FAKE_AGENTS"\n')
    os.chmod(os.path.join(e.bin, "claude"), 0o755)
    open(e.agents_file, "w").write(keep)
    keep = open(e.launchctl).read()
    open(os.path.join(e.bin, "launchctl"), "w").write('#!/bin/sh\ncat "$FAKE_LAUNCHCTL"; exit 1\n')
    r = e.reap("--auto")
    check(r.returncode == 3 and "launchd" in r.stderr.strip().splitlines()[-1] and not e.killed(),
          f"launchctl list не прочитан — проход пропущен, код 3: {r.returncode} {r.stderr[-300:]}")
    os.remove(os.path.join(e.bin, "launchctl"))
    open(os.path.join(e.bin, "claude"), "w").write('#!/bin/sh\n/bin/cat "$FAKE_AGENTS"\n')  # PATH без /bin
    r = e.reap("--auto", extra={"PATH": e.bin})
    check(r.returncode == 3 and "launchd" in r.stderr.strip().splitlines()[-1] and not e.killed(),
          f"launchctl нет — проход пропущен, код 3: {r.returncode} {r.stderr[-300:]}")
    open(os.path.join(e.bin, "launchctl"), "w").write('#!/bin/sh\n[ "$1" = list ] || exit 64\ncat "$FAKE_LAUNCHCTL"\n')
    os.chmod(os.path.join(e.bin, "launchctl"), 0o755)
    bad = os.path.join(e.tmp, "kill-dir")
    os.makedirs(bad)
    r = e.reap("--auto", extra={"PANTHEON_FAKE_KILL_LOG": bad})
    check(r.returncode == 1 and "не погашен:" in r.stdout and "reap --auto: не погашены" in e.alerts()
          and "погашено:" not in e.alerts(), f"kill не прошёл — код 1, строка «не погашены», без «погашено»: "
          f"{r.returncode} {r.stdout[-300:]}")


def test_tick_runs_only_auto():
    code = ("import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('pantheon', sys.argv[1])\n"
            "m = importlib.util.module_from_spec(spec); sys.modules['pantheon'] = m; spec.loader.exec_module(m)\n"
            "print(m.parse_command('pantheon reap --auto') is not None, m.parse_command('pantheon reap --apply') is None,"
            " m.parse_command('pantheon reap') is None, m.parse_command('pantheon reap --auto --pid 1') is None)\n")
    e = Env()
    r = subprocess.run([PY311, "-I", "-c", code, LIB], env=e.env(), capture_output=True, text=True, timeout=60)
    check(r.stdout.split() == ["True"] * 4, f"плановый проход пускает только `pantheon reap --auto`: {r.stdout} "
          f"{r.stderr[-300:]}")


def test_watch_repeats_in_long_episode():
    """30.10: своп выше порога сутками, проходы каждые 5 мин — эпизод продлевался, строки виновников не было."""
    e = Env()
    standard(e)
    red = {"PANTHEON_FAKE_SWAP": "9"}
    for dt in range(0, 7 * 3600 + 1, 1800):  # 7 ч красной зоны, проход раз в 30 мин (меньше EPISODE_GAP)
        e.watch_check(T0 + dt, extra=red)
    a = e.alerts()
    check(a.count("виновники памяти") == 2 and "держится 6 ч" in a,
          f"красная зона 7 ч без перерыва — вторая строка через 6 ч с «держится»: {a.count('виновники памяти')}")
    check("pantheon reap --auto" in a, "в строке — что брошенное гасит плановый проход")
    e2 = Env()
    standard(e2)
    open(os.path.join(e2.state, "culprits-last"), "w").write(f"{T0 - 300}\n")
    e2.watch_check(T0, extra=red)
    check(e2.alerts().count("виновники памяти") == 1, "старая метка из одного числа — тревоги в ней нет, строка есть")


def test_kind_parse():
    code = ("import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('c', sys.argv[1]); m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "cases = [('claude --agent x', None), ('/opt/homebrew/bin/node a.js', None), ('next-server (v16.0.1)', None),"
            " ('npm exec tsx /w/a.ts', None), ('node /n/pnpm/bin/pnpm.cjs dev', None), ('/usr/bin/vim x', None),"
            " ('python3 -c from multiprocessing.resource_tracker import main;main(8)', 1),"
            " ('python3 -c from multiprocessing.resource_tracker import main;main(8)', 77),"
            " ('/opt/homebrew/opt/node/bin/node /opt/homebrew/bin/pyright-langserver --stdio', 5),"
            " ('node /n/typescript/lib/tsserver.js --useNodeIpc', 5), ('typescript-language-server --stdio', 5),"
            " ('node /p/node_modules/pyright/langserver.index.js', 5), ('node /x/tsserver-helper.js', 5),"
            " ('SCREEN -dmS tsserver', 1), ('python3 x.py --name tsserver', 1), ('node /x/run.js tsserver', 5),"
            " ('node --max-old-space-size=3072 /c/tsserver.js', 5), ('/usr/local/bin/tsserver', 5)]\n"
            "print(json.dumps([m.kind_of(a, p) for a, p in cases] + [m._etime(x) for x in ('05:24', '2:03:04', "
            "'4-01:00:00', 'x')] + [m._mb(x) for x in ('1235M', '2G+', '512K')]))\n")
    r = subprocess.run([PY311, "-I", "-c", code, os.path.join(ROOT, "lib", "culprits.py")], capture_output=True,
                       text=True, timeout=30)
    got = json.loads(r.stdout or "null")
    want = ["claude", "node", "next", "tsx", "pnpm", None, "python-mp", None, "lsp", "lsp", "lsp", "lsp", "node",
            None, None, "node", "lsp", "lsp", 324, 7384, 349200, None, 1235.0, 2048.0,
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
