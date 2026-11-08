#!/usr/bin/env python3
"""Карта тестов не устаревает на main (metis-0842 п.2, lib/map_tick.py): плановый проход сам пересобирает
affected-map.json и пушит коммит «карта: …» в main.

Запуск: python3 -I plugins/pantheon/tests/test_map_tick.py  (код выхода 0 — все прошли)
Настоящий git на временных папках: голый «origin» с main; affected-map.py в репозитории — заглушка (код --check берёт из
файла рядом, --update дописывает строку в карту). Push идёт в локальный голый репозиторий, сеть и ~/.claude не
трогаются; heavy, load и запуск работника подменены (работник зовётся прямо). Проверяет:
  [устарела]  --check код 1 → коммит «карта: affected-map на <sha7>» в origin/main, меняет одну карту; строка map-tick;
  [свежая]    --check код 0 → коммита нет;
  [нагрузка]  load выше порога → пропуск без проверки (копия не создаётся);
  [история]   слияние ждёт выпуска, карта уже была после слияния → ничего; выпуск после слияния → обновляет;
              цикл «карта → выпуск → карта» не идёт;
  [сбой]      --check код 2, --update код 1, --update тронул лишний файл → тревога, коммита нет;
              main ушёл вперёд — push отклонён без тревоги;
              карта с непустым broken (упали при сборке) → не коммитится, тревога; broken из одного test_run_tests — коммитится;
  [частота]   повтор раньше 10 мин и живой работник — без проверки; PANTHEON_DRYRUN — ничего.
"""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "lib")
sys.path.insert(0, HERE)
from _py311 import mkroot  # noqa: E402

_ROOT = os.path.realpath(mkroot("map-tick-"))
atexit.register(shutil.rmtree, _ROOT, True)
os.environ.pop("PANTHEON_DRYRUN", None)
REPO = "latark/agent-kit"
T = int(time.time())
FAILS = []
CHECKS = []
MAP_REL = "plugins/pantheon/scripts/affected-map.json"


def check(name, cond, extra=""):
    CHECKS.append(name)
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f" — {extra}"))
    if not cond:
        FAILS.append(name)


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, os.path.join(LIB, file))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = load("pantheon_merge_t", "merge.py")
RT = load("pantheon_release_tick_t", "release_tick.py")
MT = load("pantheon_map_tick_t", "map_tick.py")
ORIG_SPAWN = MT.spawn


def git(d, *args, author="t"):
    env = {"PATH": os.environ["PATH"], "HOME": os.path.join(_ROOT, "home"), "GIT_AUTHOR_NAME": author,
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": "t@t"}
    r = subprocess.run(["git", "-C", d, *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


STUB = '''import os, sys
here = os.path.dirname(os.path.abspath(__file__))
mode = open(os.path.join(here, "stub-mode")).read().split()
if "--check" in sys.argv:
    print("affected-map: заглушка check")
    sys.exit(int(mode[0]))
if "--update" in sys.argv:
    import json
    broken = {"broken": ["pantheon/test_watch.py", "guard/test_refspec.py"], "broken-self": ["pantheon/test_run_tests.py"]}
    with open(os.path.join(here, "affected-map.json"), "w") as fh:
        json.dump({"note": "обновлено", "broken": broken.get(mode[1], [])}, fh, ensure_ascii=False)
    if mode[1] == "extra":
        open(os.path.join(here, "лишний.txt"), "w").write("x")
    print("affected-map: заглушка update")
    sys.exit(1 if mode[1] == "fail" else 0)
'''


class World:
    """Временный мир: origin и STATE. commits — темы коммитов после «начало» по порядку; check — код --check заглушки,
    update — ok | fail | extra."""

    def __init__(self, name, commits=("выпуск: pantheon 0.1.1", "Merge pull request #1", "выпуск: pantheon 0.1.2"),
                 check_code=1, update="ok", loadavg=0.0):
        self.root = os.path.join(_ROOT, name)
        os.makedirs(os.path.join(self.root, "home"))
        self.state = os.path.join(self.root, "state")
        self.origin = os.path.join(self.root, "origin.git")
        self.work = os.path.join(self.root, "work")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.origin], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.work], check=True)
        sdir = os.path.join(self.work, "plugins", "pantheon", "scripts")
        os.makedirs(sdir)
        open(os.path.join(sdir, "affected-map.py"), "w").write(STUB)
        open(os.path.join(sdir, "affected-map.json"), "w").write("карта\n")
        open(os.path.join(sdir, "stub-mode"), "w").write(f"{check_code} {update}\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "начало")
        for i, subj in enumerate(commits):
            open(os.path.join(self.work, f"f{i}.txt"), "w").write(str(i))
            git(self.work, "add", "-A")
            git(self.work, "commit", "-q", "-m", subj, author=MT.MAP_AUTHOR if subj.startswith("карта: affected-map на") else "t")
        git(self.work, "remote", "add", "origin", self.origin)
        git(self.work, "push", "-q", "origin", "main")
        self.sha = git(self.work, "rev-parse", "HEAD")
        self.alerts, self.cleared, self.heavy_calls = [], [], []
        home = os.path.join(self.root, "home")
        core = types.SimpleNamespace(
            HOME=home, path=lambda *p: os.path.join(self.state, *p),
            read_json=self._read_json, write_json=self._write_json,
            stamp=lambda t=None: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)),
            alert_once=lambda key, value, text, who="pantheon", **kw: self.alerts.append((key, value, text, who, kw)),
            clear_once=lambda key: self.cleared.append(key),
            pid_alive=lambda pid: pid == os.getpid(),
            merge_mod=lambda: M, release_tick_mod=lambda: RT)
        M.allowed_repos = lambda: {REPO, "latark/other"}
        RT.set_core(core)
        RT.URL = self.origin
        MT.set_core(core)
        MT.load_state = lambda: (loadavg, 24.0)
        MT.heavy_prefix = lambda: []
        MT.spawn = lambda job: (self.heavy_calls.append(job), MT.work(job))

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

    def origin_log(self):
        return git(self.origin, "log", "--first-parent", "--format=%s", "main").splitlines()

    def tick_log(self):
        p = os.path.join(self.state, "logs", "tick.log")
        return open(p).read() if os.path.exists(p) else ""


# --- [устарела] ---------------------------------------------------------------------------------------------------
w = World("stale")
out = MT.tick(T)
log = w.origin_log()
check("устарела → в origin/main коммит «карта: affected-map на <sha7>»", log[0] == f"карта: affected-map на {w.sha[:7]}",
      (log, out))
check("коммит карты меняет только карту", git(w.origin, "show", "--name-only", "--format=", "main") == MAP_REL)
check("карта в коммите обновлена заглушкой", "обновлено" in git(w.origin, "show", f"main:{MAP_REL}"))
check("строка map-tick в tick.log", "map-tick: latark/agent-kit: карта устарела" in w.tick_log(), w.tick_log())
check("работник зван один раз", len(w.heavy_calls) == 1, w.heavy_calls)
check("другой репозиторий из merge_repos не трогается", not os.path.exists(os.path.join(w.state, "map", "other")))
out2 = MT.tick(T + MT.CHECK_EVERY + 1)
check("итог работника — строка в tick.log и тревоги нет", "отправлен в main" in w.tick_log() and not w.alerts
      and w.cleared, (w.tick_log(), w.alerts))
out3 = MT.tick(T + 2 * MT.CHECK_EVERY + 2)
check("после карты (выпуска ещё нет) → повторного коммита нет", w.origin_log()[0].startswith("карта:")
      and len([s for s in w.origin_log() if s.startswith("карта:")]) == 1, (w.origin_log(), out3))
check("повтор раньше 10 мин — без проверки", MT.tick(T + 2 * MT.CHECK_EVERY + 3) is None)

# --- [цикл] карта → выпуск → проверка: второй карты нет ------------------------------------------------------------
w = World("loop", commits=("выпуск: pantheon 0.1.1", "Merge pull request #1", "выпуск: pantheon 0.1.2", "карта: affected-map на abc1234",
                           "выпуск: pantheon 0.1.3"))
out = MT.tick(T)
check("цикл: «выпуск» после «карты» без новых слияний → карта не зовётся", not w.heavy_calls and "уже обновлялась" in out, out)

# --- [свежая] -----------------------------------------------------------------------------------------------------
w = World("fresh", check_code=0)
out = MT.tick(T)
check("свежая → коммита карты нет", not w.heavy_calls and not w.origin_log()[0].startswith("карта:") and "свежая" in out, out)

# --- [нагрузка] ---------------------------------------------------------------------------------------------------
w = World("load", loadavg=99.0)
out = MT.tick(T)
check("load выше порога → пропуск без проверки и коммита", out is None and not w.heavy_calls
      and not os.path.exists(os.path.join(w.state, "map")) and not w.origin_log()[0].startswith("карта:"), (out, w.heavy_calls))
MT.load_state = lambda: (1.0, 24.0)
check("load спал → следующий тик проверяет сразу (метка частоты не ставилась)", MT.tick(T + 1) is not None and w.heavy_calls)

# --- [история] ----------------------------------------------------------------------------------------------------
w = World("pending-release", commits=("выпуск: pantheon 0.1.1", "Merge pull request #1"))
out = MT.tick(T)
check("слияние ждёт выпуска → карту не трогает", not w.heavy_calls and "ждёт выпуска" in out, out)
w = World("no-release", commits=("не выпуск",))
out = MT.tick(T)
check("коммита выпуска нет в истории → не трогает", not w.heavy_calls and "нет в" in out, out)
w = World("after-map-merge", commits=("выпуск: pantheon 0.1.1", "карта: affected-map на abc1234", "Merge pull request #2",
                                      "выпуск: pantheon 0.1.2"))
out = MT.tick(T)
check("слияние после последней карты и выпуск → карта обновляется", len(w.heavy_calls) == 1
      and w.origin_log()[0].startswith("карта:"), (out, w.origin_log()))

# --- [сбой] -------------------------------------------------------------------------------------------------------
w = World("check-fail", check_code=2)
out = MT.tick(T)
check("--check код 2 → тревога, коммита нет", not w.heavy_calls and w.alerts and "код 2" in w.alerts[0][2]
      and w.alerts[0][3] == "pantheon-tick" and not w.alerts[0][4].get("critical"), (out, w.alerts))
w = World("update-fail", update="fail")
MT.tick(T)
MT.tick(T + MT.CHECK_EVERY + 1)
check("--update код 1 → тревога, коммита нет", w.alerts and "код 1" in w.alerts[-1][2]
      and not w.origin_log()[0].startswith("карта:"), (w.alerts, w.origin_log()))
w = World("update-extra", update="extra")
MT.tick(T)
MT.tick(T + MT.CHECK_EVERY + 1)
check("--update тронул лишний файл → тревога, коммита нет", w.alerts and "лишний.txt" in w.alerts[-1][2]
      and not w.origin_log()[0].startswith("карта:"), (w.alerts, w.origin_log()))
w = World("broken", update="broken")
MT.tick(T)
MT.tick(T + MT.CHECK_EVERY + 1)
check("карта с broken → тревога с именами файлов, коммита нет", w.alerts and "test_watch.py" in w.alerts[-1][2]
      and "test_refspec.py" in w.alerts[-1][2] and not w.origin_log()[0].startswith("карта:"), (w.alerts, w.origin_log()))
check("после карты с broken main не тронут и повтор на том же sha не идёт", len(w.heavy_calls) == 1, len(w.heavy_calls))
w = World("broken-self", update="broken-self")
MT.tick(T)
check("в broken только test_run_tests → карта коммитится", w.origin_log()[0].startswith("карта:") and not w.alerts,
      (w.origin_log(), w.alerts))
w = World("race")


def advance(job):
    git(w.work, "commit", "-q", "--allow-empty", "-m", "Merge pull request #9")
    git(w.work, "push", "-q", "origin", "main")
    return MT.work(job)


MT.spawn = advance
MT.tick(T)
MT.tick(T + MT.CHECK_EVERY + 1)
check("main ушёл вперёд → push отклонён, не сбой, карта не лезет в чужую историю",
      not w.alerts and not any(s.startswith("карта:") for s in w.origin_log()) and "отклонён" in w.tick_log(),
      (w.alerts, w.origin_log(), w.tick_log()))

# --- [строгое узнавание карты] ------------------------------------------------------------------------------------
w = World("squash-title", commits=("выпуск: pantheon 0.1.1", "карта: что-то про карту (#397)", "выпуск: pantheon 0.1.2"))
out = MT.tick(T)
check("тема слияния «карта: что-то (#397)» не считается картой — карта строится", len(w.heavy_calls) == 1, out)
rows_h = [("a", "t", "выпуск: y"), ("b", "t", "карта: affected-map на abc1234"), ("c", "t", "выпуск: x")]
check("тема карты от другого автора — не карта (нужна новая)", MT.history_need(rows_h)[0] is True, MT.history_need(rows_h))
check("автор pantheon-tick, но тема не по шаблону — не карта",
      not MT.is_map(MT.MAP_AUTHOR, "карта: что-то (#397)") and not MT.is_map(MT.MAP_AUTHOR, "карта: affected-map на abc12345")
      and not MT.is_map(MT.MAP_AUTHOR, "карта: affected-map на abc123x") and MT.is_map(MT.MAP_AUTHOR, "карта: affected-map на abc1234")
      and not MT.is_map("t", "карта: affected-map на abc1234"))

# --- [сбой работника: тот же sha не повторяется] ------------------------------------------------------------------
w = World("failed-sha", update="fail")
for i in range(5):
    MT.tick(T + i * (MT.CHECK_EVERY + 1))
check("update=fail, несколько тиков → один запуск", len(w.heavy_calls) == 1, len(w.heavy_calls))
check("одна тревога на sha (одно значение)", w.alerts and len({a[1] for a in w.alerts}) == 1 and "код 1" in w.alerts[0][2],
      w.alerts)
check("в tick.log — «уже падало»", "уже падало" in w.tick_log(), w.tick_log())
git(w.work, "commit", "-q", "--allow-empty", "-m", "Merge pull request #5")
git(w.work, "commit", "-q", "--allow-empty", "-m", "выпуск: pantheon 0.1.3")
git(w.work, "push", "-q", "origin", "main")
MT.tick(T + 6 * (MT.CHECK_EVERY + 1))
check("новый sha на main → запуск снова", len(w.heavy_calls) == 2, len(w.heavy_calls))

# --- [остановка группы: TERM, пауза, KILL] ------------------------------------------------------------------------
class SlowProc:
    pid = 4242

    def __init__(self, dies_on):
        self.dies_on, self.calls = dies_on, 0

    def communicate(self, timeout=None):
        self.calls += 1
        if self.calls == 1 or (self.dies_on == "kill" and self.calls == 2):
            raise MT.subprocess.TimeoutExpired("x", timeout)
        return ("", "")


for dies_on, want in (("term", ["TERM"]), ("kill", ["TERM", "KILL"])):
    sent, proc = [], SlowProc(dies_on)
    real_killpg, real_popen = MT.os.killpg, MT.subprocess.Popen
    MT.os.killpg = lambda pid, sig, sent=sent: sent.append(MT.signal.Signals(sig).name[3:])
    MT.subprocess.Popen = lambda *a, proc=proc, **k: proc
    try:
        res = MT._run(["x"], ".", {}, 5)
    finally:
        MT.os.killpg, MT.subprocess.Popen = real_killpg, real_popen
    check(f"таймаут: группе сначала TERM{', потом KILL' if len(want) > 1 else ' (вышла сама — KILL не шлётся)'}",
          sent == want and res[0] is None and "остановлено" in res[1], (sent, res))
check("между TERM и KILL пауза TERM_GRACE (10 с)", MT.TERM_GRACE == 10)

# --- [pid ещё не записан] -----------------------------------------------------------------------------------------
w = World("no-pid")
w._write_json(os.path.join(w.state, "map-tick.json"), {"running": {"t": T, "sha": w.sha}})
check("pid ещё не записан, меньше DIED_GRACE → ждём", MT.tick(T + MT.DIED_GRACE - 1) is None and not w.alerts)
MT.tick(T + MT.DIED_GRACE + 1)
check("pid не записан дольше DIED_GRACE → погиб, тревога", w.alerts and "погиб" in w.alerts[0][2], w.alerts)

# --- [argv работника] ---------------------------------------------------------------------------------------------
w = World("argv")
os.environ["MAP_TICK_SECRET"] = "s3cret-token"
seen = {}


class FakePopen:
    def __init__(self, argv, **kw):
        seen.update(argv=argv, kw=kw)


real_popen = MT.subprocess.Popen
MT.subprocess.Popen = FakePopen
try:
    ORIG_SPAWN({"repo": REPO, "copy": w.work, "sha": w.sha, "state": os.path.join(w.state, "map-tick.json"),
                "heavy": []})
finally:
    MT.subprocess.Popen = real_popen
    os.environ.pop("MAP_TICK_SECRET")
check("argv работника не несёт окружения (ps видит всех)", "s3cret-token" not in " ".join(seen["argv"])
      and "env" not in json.loads(seen["argv"][-1]), seen["argv"])
check("окружение идёт отдельным env= Popen", seen["kw"].get("env", {}).get("MAP_TICK_SECRET") == "s3cret-token", seen["kw"])
w = World("argv-job")
MT.tick(T)
check("job из тика — без поля env", w.heavy_calls and "env" not in w.heavy_calls[0], w.heavy_calls)

# --- [частота] ----------------------------------------------------------------------------------------------------
w = World("busy")
w._write_json(os.path.join(w.state, "map-tick.json"), {"running": {"t": T, "pid": os.getpid(), "sha": w.sha}})
check("живой работник → тик ничего не делает", MT.tick(T + 3600) is None and not w.heavy_calls)
w._write_json(os.path.join(w.state, "map-tick.json"), {"running": {"t": T, "pid": 1, "sha": w.sha}})
MT.tick(T + 3600)
check("работник погиб без итога → тревога", w.alerts and "погиб" in w.alerts[0][2], w.alerts)
w = World("dryrun")
os.environ["PANTHEON_DRYRUN"] = "1"
out = MT.tick(T)
os.environ.pop("PANTHEON_DRYRUN")
check("PANTHEON_DRYRUN=1 → ничего", out is None and not w.heavy_calls and not os.path.exists(w.state))
w = World("no-repo")
M.allowed_repos = lambda: {"latark/other"}
check("agent-kit нет в merge_repos → ничего", MT.tick(T) is None and not w.heavy_calls)

print(f"\n{len(CHECKS) - len(FAILS)}/{len(CHECKS)}")
sys.exit(1 if FAILS else 0)
