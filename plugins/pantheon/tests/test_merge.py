#!/usr/bin/env python3
"""Слияние PR ядра по Touch ID (metis-0285, lib/merge.py): поддельные gh и помощник окна.

Запуск: python3 -I plugins/pantheon/tests/test_merge.py  (код выхода 0 — все прошли)
Проверяет на временных папках: палец → строка merge-approve в owner-log и `gh pr merge N --match-head-commit <sha>
--merge`, заявка снята (одно применение); отказ, новый head, 24 ч → слияния нет, заявка снята; шлюз заново на тот же
head перед окном (новый «вернуть», нет тестов) → окна нет; CI идёт, владельца нет → ждёт; окно без ответа — повтор
позже; окно не показать → уведомление с `merge run --click`, щелчок сливает; из окна Claude Code — отказ; строку
согласия принимает шлюз guard (настоящий merge_gate.owner_approved); тик запускает проход, только когда есть заявки.
"""
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import tempfile
import atexit as _atexit
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="merge-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

HERE = os.path.dirname(os.path.abspath(__file__))
LIBDIR = os.path.join(os.path.dirname(HERE), "lib")
LIB = os.path.join(LIBDIR, "pantheon.py")
GUARD_HOOKS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "hooks")
T0 = 1_792_000_000
REPO = "latark/agent-kit"
PR = 7
SHA = "abcdef1" + "0" * 33
SHA2 = "1234567" + "f" * 33
TITLE = "guard: шлюз по Touch ID"

# gh: view — из rec/gh-view.json (нет файла — код 1), merge — код из rec/gh-merge-rc; argv — в rec/gh-argv.jsonl
FAKE_GH = r'''
import json, os, sys
rec = os.environ["FAKE_REC"]
with open(os.path.join(rec, "gh-argv.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "env": sorted(k for k in os.environ if k.startswith("GH_")),
                         "keys": sorted(os.environ)}) + "\n")
if sys.argv[1:3] == ["pr", "view"]:
    p = os.path.join(rec, "gh-view.json")
    if not os.path.exists(p):
        sys.exit(1)
    print(open(p).read())
    sys.exit(0)
if sys.argv[1:3] == ["pr", "merge"]:
    p = os.path.join(rec, "gh-merge-rc")
    sys.exit(int(open(p).read()) if os.path.exists(p) else 0)
if sys.argv[1] == "api" and "/pulls/" in sys.argv[2] and sys.argv[2].split("?")[0].endswith("/files"):
    p = os.path.join(rec, "gh-files.jsonl")
    if not os.path.exists(p):
        sys.exit(1)
    print(open(p).read(), end="")
    sys.exit(0)
sys.exit(2)
'''
CORE_FILE = "plugins/guard/hooks/merge_gate.py"
FILES = ["README.md", CORE_FILE]

# помощник окна: код — из rec/touchid-rc (по умолчанию 0); argv — в rec/touchid-argv.jsonl
FAKE_TOUCHID = r'''
import json, os, sys
rec = os.environ["FAKE_REC"]
with open(os.path.join(rec, "touchid-argv.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:]}) + "\n")
p = os.path.join(rec, "touchid-rc")
sys.exit(int(open(p).read()) if os.path.exists(p) else 0)
'''

# Тестовая обвязка прохода: подмены — атрибутом merge.TEST в её процессе (из окружения launchd его не включить),
# переменные для прохода — из MERGE_TEST, который читает только обвязка
HARNESS = ("import json, os, sys; sys.path.insert(0, %r); import pantheon as p; m = p.merge_mod(); "
           "m.TEST = json.loads(os.environ.pop('MERGE_TEST')); sys.exit(p.main(sys.argv[1:]))" % LIBDIR)

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f" — {detail}"))
    if not cond:
        FAILS.append(name)


def script(path, body):
    with open(path, "w") as fh:
        fh.write("#!" + sys.executable + "\n" + body)
    os.chmod(path, 0o755)
    return path


def ci(*states):
    return [{"__typename": "CheckRun", "name": f"job{i}", "status": "COMPLETED" if s != "PENDING" else "IN_PROGRESS",
             "conclusion": s if s != "PENDING" else ""} for i, s in enumerate(states)]


class Box:
    def __init__(self, repos=(REPO,)):
        self.tmp = tempfile.mkdtemp(prefix="box-")
        self.home = os.path.join(self.tmp, "home")
        self.pantheon = os.path.join(self.home, "ai", "pantheon")
        self.state = os.path.join(self.home, ".local", "state", "pantheon")
        self.rec = os.path.join(self.tmp, "rec")
        self.bin = os.path.join(self.tmp, "bin")
        for d in (self.pantheon, self.state, self.rec, self.bin, os.path.join(self.home, ".claude", "pantheon")):
            os.makedirs(d, exist_ok=True)
        script(os.path.join(self.bin, "gh"), FAKE_GH)
        # поддельный помощник окна — только там, где его берёт проход: STATE/bin с отметкой sha256 исходника
        sbin = os.path.join(self.state, "bin")
        os.makedirs(sbin, mode=0o700)
        self.touchid = script(os.path.join(sbin, "pantheon-touchid"), FAKE_TOUCHID)
        with open(os.path.join(sbin, "pantheon-touchid.sha256"), "w") as fh:
            fh.write(hashlib.sha256(open(os.path.join(LIBDIR, "touchid.swift"), "rb").read()).hexdigest() + "\n")
        self.notify_log = os.path.join(self.rec, "notify.log")
        with open(os.path.join(self.home, ".claude", "pantheon", "policy.toml"), "w") as fh:
            fh.write("[merge_repos]\n\"metis-pantheon\" = [%s]\n\"athena-shop\" = [\"latark/shop\"]\n"
                     % ", ".join(f'"{r}"' for r in repos))
        self.view(SHA)
        self.records = []
        self.gate_ok(SHA)
        self.outs = []

    def env(self, t, extra=None):
        env = {"PATH": self.bin + ":/usr/bin:/bin", "HOME": self.home, "PANTHEON_HOME": self.pantheon,
               "PANTHEON_STATE": self.state, "PANTHEON_NOW": str(t), "PANTHEON_HOST": "mac-a",
               "PANTHEON_NOTIFY_LOG": self.notify_log, "PANTHEON_FAKE_IDLE": "5",
               "FAKE_REC": self.rec, "TMPDIR": _ROOT, "GH_REPO": "evil/repo", "GH_HOST": "evil.example"}
        env.update(extra or {})
        return {k: v for k, v in env.items() if v is not None}

    def cli(self, args, t=T0, extra=None, evil=None):
        env = self.env(t, extra)
        if args[:2] == ["merge", "run"]:
            # проход — через обвязку HARNESS: подмены (поддельный gh в PATH, часы, простой, журнал уведомлений) —
            # только атрибутом merge.TEST в её процессе (metis-0303). evil — то, что дописало бы в окружение
            # прохода launchd (launchctl setenv): проход его не берёт
            cmd = [PY311, "-I", "-c", HARNESS] + args
            env = dict(env, **(evil or {}), MERGE_TEST=json.dumps({"env": env}))
        else:
            cmd = [PY311, "-I", LIB] + args
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        self.outs.append(r.stdout + r.stderr)
        return r

    def request(self, pr=PR, repo=REPO, t=T0):
        return self.cli(["merge", "request", str(pr), "-R", repo], t=t)

    def run(self, t=T0, click=False, extra=None, evil=None):
        return self.cli(["merge", "run"] + (["--click"] if click else []), t=t, extra=extra, evil=evil)

    def view(self, sha, state="OPEN", draft=False, checks=None, title=TITLE, files=None, count=None):
        """Ответ gh pr view и REST pulls/N/files: files — имена или словари; count — changedFiles (по умолчанию
        len(files))."""
        files = FILES if files is None else files
        recs = [f if isinstance(f, dict) else {"filename": f, "status": "modified"} for f in files]
        with open(os.path.join(self.rec, "gh-view.json"), "w") as fh:
            json.dump({"headRefOid": sha, "state": state, "isDraft": draft, "title": title,
                       "statusCheckRollup": ci("SUCCESS", "SKIPPED") if checks is None else checks,
                       "changedFiles": len(recs) if count is None else count}, fh)
        with open(os.path.join(self.rec, "gh-files.jsonl"), "w") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in recs))

    def set(self, name, value):
        with open(os.path.join(self.rec, name), "w") as fh:
            fh.write(str(value))

    def add(self, kind, sha=SHA, pr=PR, who="argus", sid="s1", aid="a1", ran="модель: claude-opus-5-5, тесты"):
        rec = {"v": 1, "kind": kind, "repo": [REPO], "pr": None if kind == "tests" else pr, "sha": sha,
               "by": {"agent_type": who, "agent_id": aid, "session_id": sid}}
        if kind in ("accept", "reject"):
            rec["checklist"] = {"opened": "diff", "ran": ran, "unchecked": "ничего"}
        self.records.append(rec)
        d = os.path.join(self.state, "merge-gate")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "records.jsonl"), "w") as fh:
            fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.records))

    def gate_ok(self, sha):
        self.add("tests", sha=sha, who="")
        self.add("accept", sha=sha, sid="s1", aid="a1")
        self.add("accept", sha=sha, sid="s2", aid="a2")

    def calls(self, name):
        p = os.path.join(self.rec, name + "-argv.jsonl")
        return [json.loads(ln) for ln in open(p)] if os.path.exists(p) else []

    def merges(self):
        return [c["argv"] for c in self.calls("gh") if c["argv"][:2] == ["pr", "merge"]]

    def windows(self):
        return [c["argv"] for c in self.calls("touchid")]

    def req_path(self, pr=PR, repo=REPO):
        o, n = repo.split("/")
        return os.path.join(self.state, "merge-queue", f"{o}__{n}__{pr}.json")

    def req(self, pr=PR):
        p = self.req_path(pr)
        return json.load(open(p)) if os.path.exists(p) else None

    def approve_lines(self):
        p = os.path.join(self.state, "owner-log", "merge-approve.log")
        return open(p).read().splitlines() if os.path.exists(p) else []

    def alerts(self):
        p = os.path.join(self.pantheon, "alerts.md")
        return open(p).read() if os.path.exists(p) else ""

    def log(self):
        p = os.path.join(self.state, "logs", "merge.jsonl")
        return [json.loads(ln)["event"] for ln in open(p)] if os.path.exists(p) else []


def guard_approves(b, repo, pr, sha, now=T0):
    """Настоящий шлюз guard: принимает ли строку согласия из owner-log этой коробки (часы шлюза — now)."""
    code = ("import sys; sys.path.insert(0, %r); import guard; import merge_gate as m; "
            "print(m.owner_approved(%r, %d, %r, now=%r))" % (GUARD_HOOKS, repo, pr, sha, now))
    r = subprocess.run([sys.executable, "-I", "-c", code], env={"HOME": b.home, "PATH": "/usr/bin:/bin"},
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip() == "True", r.stdout + r.stderr


# --- случаи -----------------------------------------------------------------------------------------------------------

def test_finger_merges_exact_sha():
    b = Box()
    r = b.request()
    req = b.req()
    check("заявка: стоит, SHA — head PR сейчас, файл 0600, папка 0700",
          r.returncode == 0 and req and req["sha"] == SHA and req["pr"] == PR
          and oct(os.stat(b.req_path()).st_mode & 0o777) == "0o600"
          and oct(os.stat(os.path.dirname(b.req_path())).st_mode & 0o777) == "0o700", b.outs[-1])
    check("заявка: окна и слияния нет — только плановый проход", not b.windows() and not b.merges(), b.calls("gh"))
    r = b.run()
    w = b.windows()
    check("палец: одно окно «Слить repo#N (sha7), файлов N, ядро: <файлы>. argus ×2 ✓, CI ✓. Заголовок: «…»»",
          len(w) == 1 and w[0][0] == f"Слить {REPO}#{PR} ({SHA[:7]}), файлов 2, ядро: {CORE_FILE}. argus ×2 ✓, "
          f"CI ✓. Заголовок: «{TITLE}»" and w[0][1] == "120", w)
    check("палец: gh pr merge N -R repo --match-head-commit <sha> --merge — ровно один раз",
          b.merges() == [["pr", "merge", str(PR), "-R", REPO, "--match-head-commit", SHA, "--merge"]], b.merges())
    check("gh: GH_REPO и GH_HOST из окружения убраны",
          all(c["env"] == [] for c in b.calls("gh")), b.calls("gh"))
    lines = b.approve_lines()
    check("палец: строка «<время> merge-approve repo#N sha» в owner-log/merge-approve.log, файл 0600",
          len(lines) == 1 and re.fullmatch(r"\S+ merge-approve " + re.escape(f"{REPO}#{PR} {SHA}"), lines[0])
          and oct(os.stat(os.path.join(b.state, "owner-log", "merge-approve.log")).st_mode & 0o777) == "0o600", lines)
    ok, out = guard_approves(b, REPO, PR, SHA)
    check("шлюз guard принимает строку согласия на этот SHA", ok, out)
    ok2, out2 = guard_approves(b, REPO, PR, SHA2)
    check("шлюз guard не принимает её для другого SHA", not ok2, out2)
    check("палец: заявка снята, журнал — window, merged", b.req() is None and b.log()[-2:] == ["window", "merged"],
          b.log())
    b.run()
    check("одно применение: второй проход не сливает и окна не показывает",
          len(b.merges()) == 1 and len(b.windows()) == 1, (b.merges(), b.windows()))


def test_refusal():
    b = Box()
    b.request()
    b.set("touchid-rc", 1)
    b.run()
    check("отказ: окно было, слияния нет, строки согласия нет, заявка снята",
          len(b.windows()) == 1 and not b.merges() and not b.approve_lines() and b.req() is None, b.outs[-1])
    b.set("touchid-rc", 0)
    b.run()
    check("отказ: следующий проход окна не показывает (заявки нет)", len(b.windows()) == 1 and not b.merges())


def test_new_head():
    b = Box()
    b.request()
    b.view(SHA2)
    b.gate_ok(SHA2)   # и шлюз на новом коммите пройден — всё равно новая заявка
    b.run()
    check("новый head: окна и слияния нет, заявка снята, тревога «новая заявка»",
          not b.windows() and not b.merges() and b.req() is None and "нужна новая заявка" in b.alerts(),
          (b.outs[-1], b.alerts()))


def test_expired():
    b = Box()
    b.request()
    b.run(t=T0 + 24 * 3600 + 1)
    check("24 ч: окна и слияния нет, заявка снята, тревога",
          not b.windows() and not b.merges() and b.req() is None and "24 ч" in b.alerts(), b.outs[-1])
    b2 = Box()
    b2.request()
    b2.run(t=T0 + 24 * 3600 - 60)
    check("до 24 ч — сливает", len(b2.merges()) == 1, b2.outs[-1])


def test_gate_rechecked():
    b = Box()
    b.request()
    b.add("reject", sid="s3", aid="a3")
    b.run()
    check("шлюз заново: «вернуть» после заявки → окна нет, слияния нет, заявка снята",
          not b.windows() and not b.merges() and b.req() is None and "вернуть" in b.alerts(), b.outs[-1])
    b = Box()
    b.request()
    b.add("reject", sid="s1", aid="a1")   # тот же рецензент передумал
    b.run()
    check("шлюз заново: последний вердикт рецензента — «вернуть» → окна нет", not b.windows() and not b.merges())
    b = Box()
    b.request()
    b.view(SHA, draft=True)
    b.run()
    check("шлюз заново: PR стал черновиком → окна нет", not b.windows() and not b.merges() and b.req() is None)
    b = Box()
    b.request()
    b.view(SHA, state="MERGED")
    b.run()
    check("PR уже слит → окна нет, заявка снята", not b.windows() and not b.merges() and b.req() is None)
    b = Box()
    b.request()
    b.view(SHA, checks=ci("SUCCESS", "FAILURE"))
    b.run()
    check("CI упал → окна нет, заявка снята", not b.windows() and not b.merges() and b.req() is None
          and "FAILURE" in b.alerts(), b.alerts())


def test_request_refusals():
    b = Box()
    r = b.request(repo="latark/shop")
    check("заявка: репозиторий не из [merge_repos] metis-pantheon → отказ, файла нет",
          r.returncode != 0 and not os.path.exists(os.path.join(b.state, "merge-queue")), r.stderr)
    b = Box()
    b.records = []
    b.add("tests")
    b.add("accept", sid="s1", aid="a1")
    r = b.request()
    check("заявка: один «принять» из двух → отказ", r.returncode != 0 and b.req() is None and "1 из 2" in r.stderr,
          r.stderr)
    b = Box()
    b.records = []
    b.add("tests")
    b.add("accept", sid="s1", aid="a1")
    b.add("accept", sid="s2", aid="a2", ran="модель: claude-sonnet-4-6, тесты")
    r = b.request()
    check("заявка: «принять» не на Opus не засчитан → отказ", r.returncode != 0 and b.req() is None, r.stderr)
    b = Box()
    b.records = []
    b.add("tests")
    b.add("accept", sid="s1", aid="a1")
    b.add("accept", sid="s2", aid="a2", pr=PR + 1)   # тот же SHA, но вердикт на другой PR
    r = b.request()
    check("заявка: «принять» на другой PR тем же SHA не засчитан → отказ", r.returncode != 0 and b.req() is None
          and "1 из 2" in r.stderr, r.stderr)
    b = Box()
    b.records = []
    b.add("accept", sid="s1", aid="a1")
    b.add("accept", sid="s2", aid="a2")
    r = b.request()
    check("заявка: нет записи тестов шлюза → отказ", r.returncode != 0 and "тестов" in r.stderr, r.stderr)
    b = Box()
    os.remove(os.path.join(b.rec, "gh-view.json"))
    r = b.request()
    check("заявка: gh не ответил → отказ", r.returncode != 0 and b.req() is None, r.stderr)
    b = Box()
    for args in (["merge", "request", "7"], ["merge", "request", "x", "-R", REPO], ["merge", "request", "7", "-R",
                 "../x"], ["merge", "request", "7", "-R", REPO, "--x"], ["merge", "run", "--now"], ["merge"]):
        r = b.cli(args)
        check(f"разбор: {' '.join(args[1:]) or '(пусто)'} → код 2", r.returncode == 2, r.stdout + r.stderr)


def test_ci_pending_and_presence():
    b = Box()
    b.view(SHA, checks=ci("SUCCESS", "PENDING"))
    r = b.request()
    check("заявка при идущем CI ставится", r.returncode == 0 and b.req() is not None, r.stderr)
    b.run()
    check("CI идёт → окна нет, заявка ждёт", not b.windows() and b.req() is not None, b.outs[-1])
    b.view(SHA, checks=[])
    b.run()
    check("проверок ещё нет → ждёт", not b.windows() and b.req() is not None, b.outs[-1])
    b.view(SHA)
    b.run(extra={"PANTHEON_FAKE_IDLE": "900"})
    check("владельца нет у Mac (простой 15 мин) → окна нет, ждёт", not b.windows() and b.req() is not None, b.outs[-1])
    b.run()
    check("CI зелёный и владелец у Mac → окно и слияние", len(b.windows()) == 1 and len(b.merges()) == 1, b.outs[-1])


def test_timeout_retry():
    b = Box()
    b.request()
    b.set("touchid-rc", 3)
    b.run()
    check("окно без ответа → слияния нет, заявка ждёт с повтором", not b.merges() and b.req()
          and b.req().get("wait_until") == T0 + 600, b.req())
    b.set("touchid-rc", 0)
    b.run(t=T0 + 60)
    check("повтор не раньше 10 минут", len(b.windows()) == 1, b.windows())
    b.run(t=T0 + 601)
    check("через 10 минут — окно снова, палец сливает", len(b.windows()) == 2 and len(b.merges()) == 1)


def test_fallback_notification():
    b = Box()
    b.request()
    b.set("touchid-rc", 2)
    b.run()
    note = open(b.notify_log).read() if os.path.exists(b.notify_log) else ""
    check("окно не показать → уведомление со щелчком `pantheon merge run --click`, слияния нет",
          "execute:" in note and note.rstrip().endswith("merge run --click|merge") and not b.merges()
          and b.req() and b.req().get("notified"), note)
    b.run(t=T0 + 30)
    check("без щелчка следующий проход окна не показывает и уведомление не повторяет",
          len(b.windows()) == 1 and open(b.notify_log).read() == note, b.windows())
    b.set("touchid-rc", 0)
    b.run(t=T0 + 60, click=True, extra={"PANTHEON_FAKE_IDLE": "900"})
    check("щелчок → окно Touch ID и слияние этого SHA",
          len(b.windows()) == 2 and b.merges() == [["pr", "merge", str(PR), "-R", REPO, "--match-head-commit", SHA,
                                                     "--merge"]] and b.req() is None, b.outs[-1])
    b = Box()
    b.request()
    b.set("touchid-rc", 2)
    b.run(click=True)
    check("окно не показать и при щелчке → заявка снята с тревогой", b.req() is None and not b.merges()
          and "не показано" in b.alerts(), b.alerts())


def test_merge_fails():
    b = Box()
    b.request()
    b.set("gh-merge-rc", 1)
    b.run()
    check("gh pr merge упал → тревога, заявка снята (одно применение), согласие записано",
          len(b.merges()) == 1 and b.req() is None and "не прошло" in b.alerts() and len(b.approve_lines()) == 1,
          b.alerts())


def test_refused_from_claude_window():
    b = Box()
    b.request()
    for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        r = b.run(extra={var: ""})
        check(f"merge run при {var} (окно Claude Code) → отказ, окна нет", r.returncode == 2 and not b.windows(),
              r.stdout + r.stderr)
        r = b.run(click=True, extra={var: "cli"})
        check(f"merge run --click при {var} → отказ", r.returncode == 2 and not b.windows())
    check("заявка цела", b.req() is not None)


def test_no_helper():
    b = Box()
    b.request()
    # STATE/bin — ссылка на папку с исправным помощником: его не берут (и swiftc не зовут — папка не та)
    sbin = os.path.join(b.state, "bin")
    os.rename(sbin, os.path.join(b.tmp, "bin-real"))
    os.symlink(os.path.join(b.tmp, "bin-real"), sbin)
    b.run()
    check("помощника окна нет (STATE/bin — ссылка) → окна и слияния нет, заявка ждёт, тревога",
          not b.windows() and not b.merges() and b.req() is not None and "помощник" in b.alerts(), b.alerts())


EVIL = r'''
import os, sys
open(os.path.join(os.environ["FAKE_REC"], "evil"), "a").write("x\n")
sys.exit(0)
'''


def test_helper_not_from_env():
    """argus-b 1: помощник окна из переменной окружения (launchctl setenv) не берётся — только STATE/bin."""
    b = Box()
    b.request()
    evil = script(os.path.join(b.tmp, "evil-touchid"), EVIL)
    b.set("touchid-rc", 1)   # настоящий (поддельный в STATE/bin) — «Не сливать»
    b.run(extra={"PANTHEON_TOUCHID": evil})
    check("PANTHEON_TOUCHID в окружении прохода не подменяет помощника: окно из STATE/bin, слияния нет",
          len(b.windows()) == 1 and not b.merges() and not os.path.exists(os.path.join(b.rec, "evil"))
          and not b.approve_lines(), (b.outs[-1], b.windows()))


def test_helper_mark_and_swiftc():
    """Помощник с отметкой не того исходника не берётся — пересборка /usr/bin/swiftc с чистым окружением. swiftc в
    тесте подменён в процессе (subprocess.run), настоящий компилятор и окно не запускаются."""
    b = Box()
    with open(os.path.join(b.state, "bin", "pantheon-touchid.sha256"), "w") as fh:
        fh.write("0" * 64 + "\n")
    script(os.path.join(b.bin, "swiftc"), "import sys; sys.exit(1)\n")   # swiftc из PATH прохода — не берётся
    code = ("import sys, json, types; sys.path.insert(0, %r); import pantheon as p; m = p.merge_mod(); calls = []\n"
            "def fake(argv, **kw):\n"
            "    calls.append([argv[0], sorted((kw.get('env') or {}).keys())])\n"
            "    return types.SimpleNamespace(returncode=1, stdout='', stderr='сборка в тесте')\n"
            "m.subprocess.run = fake\n"
            "print(json.dumps([m.helper(), calls]))" % LIBDIR)
    r = subprocess.run([PY311, "-I", "-c", code], env=b.env(T0, {"DEVELOPER_DIR": b.tmp, "SDKROOT": b.tmp}),
                       capture_output=True, text=True, timeout=60)
    try:
        got, calls = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got, calls = "?", None
    want = [["/usr/bin/swiftc", ["HOME", "PATH"]]] if os.access("/usr/bin/swiftc", os.X_OK) else []
    check("отметка sha256 не та → помощник не берётся, пересборка /usr/bin/swiftc без DEVELOPER_DIR/SDKROOT",
          got is None and calls == want, r.stdout + r.stderr)


def window_script(body, rc):
    """Поддельный помощник: делает body (то, что случилось, пока окно открыто), пишет argv и выходит с кодом rc."""
    return ("import json, os, sys\nrec = os.environ['FAKE_REC']\nstate = os.environ['PANTHEON_STATE']\n"
            "open(os.path.join(rec, 'touchid-argv.jsonl'), 'a').write(json.dumps({'argv': sys.argv[1:]}) + '\\n')\n"
            + body + "\nsys.exit(%d)\n" % rc)


CANCEL_BODY = ("q = os.path.join(state, 'merge-queue')\n"
               "[os.remove(os.path.join(q, f)) for f in os.listdir(q) if f.endswith('.json')]")


def test_cancel_during_window():
    """argus-a 1, argus-b 2: заявку сняли, пока окно открыто, — ни согласия, ни слияния, ни записи обратно."""
    for rc in (0, 3, 2):
        b = Box()
        b.request()
        script(b.touchid, window_script(CANCEL_BODY, rc))
        b.run()
        check(f"отмена во время окна, код {rc}: слияния и строки согласия нет, заявка не ожила, журнал gone",
              not b.merges() and not b.approve_lines() and b.req() is None and b.log()[-1] == "gone"
              and not os.path.exists(b.notify_log), (b.outs[-1], b.log()))
        script(b.touchid, FAKE_TOUCHID)
        b.run(t=T0 + 601)
        check(f"отмена во время окна, код {rc}: через 10 минут окна нет", len(b.windows()) == 1, b.windows())


def test_replaced_during_window():
    """Во время окна роль поставила заявку заново (новое время): проход старую не сливает и новую не удаляет."""
    body = ("p = os.path.join(state, 'merge-queue', 'latark__agent-kit__7.json')\nd = json.load(open(p))\n"
            "d['created'] += 5\njson.dump(d, open(p, 'w'))")
    for rc in (0, 1, 3):
        b = Box()
        b.request()
        script(b.touchid, window_script(body, rc))
        b.run()
        req = b.req()
        check(f"заявку заменили во время окна, код {rc}: слияния нет, новая заявка цела и без отметок",
              not b.merges() and not b.approve_lines() and req is not None and req["created"] == T0 + 5
              and "wait_until" not in req, (b.outs[-1], req))


def test_reject_during_window():
    """argus-a 1, argus-b 2: новый «вернуть» argus, пока окно открыто, — после пальца не сливать."""
    rej = {"v": 1, "kind": "reject", "repo": [REPO], "pr": PR, "sha": SHA,
           "by": {"agent_type": "argus", "agent_id": "a9", "session_id": "s9"},
           "checklist": {"opened": "x", "ran": "y", "unchecked": "z"}}
    body = "open(os.path.join(state, 'merge-gate', 'records.jsonl'), 'a').write(%r)" % (json.dumps(rej) + "\n")
    b = Box()
    b.request()
    script(b.touchid, window_script(body, 0))
    b.run()
    check("«вернуть» во время окна: палец есть, но слияния и строки согласия нет, заявка снята с тревогой",
          len(b.windows()) == 1 and not b.merges() and not b.approve_lines() and b.req() is None
          and "после пальца" in b.alerts() and "вернуть" in b.alerts(), (b.outs[-1], b.alerts()))
    body = ("v = json.load(open(os.path.join(rec, 'gh-view.json'))); v['headRefOid'] = '1234567' + 'f' * 33\n"
            "json.dump(v, open(os.path.join(rec, 'gh-view.json'), 'w'))")
    b = Box()
    b.request()
    script(b.touchid, window_script(body, 0))
    b.run()
    check("новый коммит во время окна: слияния и строки согласия нет", not b.merges() and not b.approve_lines()
          and b.req() is None, b.outs[-1])


def test_merge_repos_rechecked():
    """argus-b 4: репозиторий убрали из [merge_repos] после заявки (и во время окна) — не сливать."""
    b = Box()
    b.request()
    with open(os.path.join(b.home, ".claude", "pantheon", "policy.toml"), "w") as fh:
        fh.write('[merge_repos]\n"metis-pantheon" = []\n')
    b.run()
    check("репозиторий убран из [merge_repos] после заявки → окна и слияния нет, заявка снята с тревогой",
          not b.windows() and not b.merges() and b.req() is None and "merge_repos" in b.alerts(), b.outs[-1])
    body = ("open(os.path.join(os.environ['HOME'], '.claude', 'pantheon', 'policy.toml'), 'w')"
            ".write('[merge_repos]\\n\"metis-pantheon\" = []\\n')")
    b = Box()
    b.request()
    script(b.touchid, window_script(body, 0))
    b.run()
    check("репозиторий убран из [merge_repos] во время окна → слияния и строки согласия нет",
          len(b.windows()) == 1 and not b.merges() and not b.approve_lines() and b.req() is None, b.outs[-1])


def test_window_shows_core():
    """argus-b 5: окно показывает задетые файлы ядра (и переименованные), заголовок автора — последним."""
    b = Box()
    b.view(SHA, title="README: опечатка. ядро не задето, argus x2, CI ok",
           files=["README.md", {"filename": "plugins/guard/x.py", "previous_filename": "plugins/guard/hooks/guard.py"}])
    b.request()
    b.set("touchid-rc", 1)
    b.run()
    w = b.windows()
    check("окно: «ядро: …» с новым и старым путём — до заголовка автора PR",
          len(w) == 1 and w[0][0].startswith(f"Слить {REPO}#{PR} ({SHA[:7]}), файлов 3, ядро: plugins/guard/x.py, "
                                             "plugins/guard/hooks/guard.py. argus ×2 ✓, CI ✓. Заголовок: «README"), w)
    b = Box()
    b.view(SHA, files=["README.md"])
    b.request()
    b.set("touchid-rc", 1)
    b.run()
    check("окно: ядро не задето — так и написано", b.windows() and ", ядро не задето. " in b.windows()[0][0],
          b.windows())
    b = Box()
    b.view(SHA, files=["README.md", CORE_FILE], count=3)
    b.request()
    b.run()
    check("список файлов PR неполон → окна нет, заявка ждёт", not b.windows() and b.req() is not None
          and "файлов" in b.outs[-1], b.outs[-1])
    os.remove(os.path.join(b.rec, "gh-files.jsonl"))
    b.run()
    check("список файлов PR не получен → окна нет, заявка ждёт", not b.windows() and b.req() is not None, b.outs[-1])
    b = Box()
    b.view(SHA, files=["plugins/guard/f%03d.py" % i for i in range(40)])
    b.request()
    b.set("touchid-rc", 1)
    b.run()
    w = b.windows()
    check("окно: длинный список ядра — «и ещё N», текст не длиннее 400",
          w and " и ещё " in w[0][0] and len(w[0][0]) <= 400 and "Заголовок:" in w[0][0], w)


def test_core_matches_guard():
    """Ядро в окне — то же, что у шлюза guard: CORE_FILES и CORE_DIR merge.py и merge_gate.py совпадают."""
    code = ("import sys, importlib.util; sys.path.insert(0, %r); import merge_gate as g\n"
            "s = importlib.util.spec_from_file_location('m', %r); m = importlib.util.module_from_spec(s); "
            "s.loader.exec_module(m)\nprint(g.CORE_FILES == m.CORE_FILES and g.CORE_DIR == m.CORE_DIR)"
            % (GUARD_HOOKS, os.path.join(LIBDIR, "merge.py")))
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    check("ядро merge.py == ядро merge_gate.py", r.stdout.strip() == "True", r.stdout + r.stderr)


def test_approve_expires():
    """argus-b 3: строка согласия в силе сутки; старая, из будущего и без разборного времени — нет."""
    b = Box()
    b.request()
    b.run()
    check("строка согласия записана", len(b.approve_lines()) == 1, b.approve_lines())
    for dt, want in ((0, True), (23 * 3600, True), (24 * 3600 + 60, False), (-3600, False)):
        ok, out = guard_approves(b, REPO, PR, SHA, now=T0 + dt)
        check(f"шлюз guard: строка через {dt // 60} мин — {'в силе' if want else 'не в силе'}", ok == want, out)
    d = os.path.join(b.state, "owner-log", "merge-approve.log")
    for line in (f"2020-01-01T00:00:00+03:00 merge-approve {REPO}#{PR} {SHA}",
                 f"x merge-approve {REPO}#{PR} {SHA}",
                 f"2026-10-14T00:00:00 merge-approve {REPO}#{PR} {SHA}"):
        with open(d, "w") as fh:
            fh.write(line + "\n")
        ok, out = guard_approves(b, REPO, PR, SHA)
        check(f"шлюз guard: строка «{line[:25]}…» — не в силе", not ok, out)


def test_status_cancel_and_bad_files():
    b = Box()
    b.request()
    r = b.cli(["merge", "status"])
    check("status: заявка видна", f"{REPO}#{PR}" in r.stdout and SHA[:12] in r.stdout, r.stdout)
    r = b.request()
    check("повтор заявки на тот же SHA — одна заявка", r.returncode == 0 and "уже стоит" in r.stdout, r.stdout)
    r = b.cli(["merge", "cancel", str(PR), "-R", REPO])
    check("cancel: снята", r.returncode == 0 and b.req() is None, r.stdout + r.stderr)
    r = b.cli(["merge", "status"])
    check("status: заявок нет", "заявок нет" in r.stdout, r.stdout)
    b.request()
    with open(b.req_path(), "w") as fh:
        fh.write('{"repo": "latark/agent-kit", "pr": 8, "sha": "%s", "created": %d}' % (SHA, T0))
    b.run()
    check("битая заявка (номер не совпадает с именем файла) — удалена, окна нет",
          not b.windows() and not os.path.exists(b.req_path()), b.outs[-1])
    os.makedirs(os.path.join(b.state, "owner-log"), exist_ok=True)
    os.rmdir(os.path.join(b.state, "owner-log"))
    target = os.path.join(b.tmp, "elsewhere")
    os.makedirs(target)
    os.symlink(target, os.path.join(b.state, "owner-log"))
    b.request()
    b.run()
    check("owner-log — ссылка → согласие не пишется, слияния нет, заявка снята с тревогой (окно не повторяется)",
          not b.merges() and not os.listdir(target) and b.req() is None and "сбой прохода" in b.alerts(),
          (b.outs[-1], os.listdir(target)))
    b.run()
    check("owner-log — ссылка: второго окна нет", len(b.windows()) == 1, b.windows())


def test_tick_kick():
    def kick(b):
        code = "import sys; sys.path.insert(0, %r); import pantheon as p; p.merge_kick()" % LIBDIR
        r = subprocess.run([PY311, "-I", "-c", code], env=b.env(T0, {"PANTHEON_DRYRUN": "1"}), capture_output=True,
                           text=True, timeout=60)
        p = os.path.join(b.state, "dryrun.log")
        return r, open(p).read() if os.path.exists(p) else ""
    b = Box()
    r, log = kick(b)
    check("тик: заявок нет — проход не запускается", r.returncode == 0 and "merge-run" not in log, r.stderr + log)
    b.request()
    r, log = kick(b)
    check("тик: есть заявка — проход запускается", r.returncode == 0 and "merge-run" in log, r.stderr + log)


def test_parse_command_not_tick():
    code = ("import sys; sys.path.insert(0, %r); import pantheon as p; "
            "print(p.parse_command('pantheon merge run') is None)" % LIBDIR)
    b = Box()
    r = subprocess.run([PY311, "-I", "-c", code], env=b.env(T0), capture_output=True, text=True, timeout=60)
    check("pantheon merge run — не подкоманда тика по расписанию (её запускает только сам тик)",
          r.stdout.strip() == "True", r.stdout + r.stderr)



# --- окружение прохода из launchd (metis-0303, review-79d-argus проба A) -----------------------------------------------
# Окружение тика и щелчка задаёт launchd, а его меняет любой процесс владельца (launchctl setenv). Проход берёт
# окружение с нуля: HOME (это домашняя папка учётной записи) и постоянный PATH; STATE и папка Пантеона — от HOME.

def test_env_state_probe_a():
    """Проба A: чужой STATE с поддельным помощником «палец есть», записями шлюза и заявкой — слияния нет."""
    b = Box()   # своя очередь пуста
    evil = os.path.join(b.tmp, "evil-state")
    os.makedirs(os.path.join(evil, "bin"), mode=0o700)
    script(os.path.join(evil, "bin", "pantheon-touchid"), EVIL)
    with open(os.path.join(evil, "bin", "pantheon-touchid.sha256"), "w") as fh:
        fh.write(hashlib.sha256(open(os.path.join(LIBDIR, "touchid.swift"), "rb").read()).hexdigest() + "\n")
    _shutil.copytree(os.path.join(b.state, "merge-gate"), os.path.join(evil, "merge-gate"))
    os.makedirs(os.path.join(evil, "merge-queue"), mode=0o700)
    with open(os.path.join(evil, "merge-queue", "latark__agent-kit__7.json"), "w") as fh:
        json.dump({"repo": REPO, "pr": PR, "sha": SHA, "by": "роль", "created": T0}, fh)
    b.run(evil={"PANTHEON_STATE": evil})
    check("PANTHEON_STATE из launchd: заявка, помощник и шлюз чужого STATE не берутся — окна, согласия и слияния нет",
          not b.merges() and not os.path.exists(os.path.join(b.rec, "evil"))
          and not os.path.exists(os.path.join(evil, "owner-log", "merge-approve.log")), (b.outs[-1], b.merges()))


def test_env_notify_log():
    b = Box()
    b.request()
    b.set("touchid-rc", 2)
    evil = os.path.join(b.tmp, "evil-notify.log")
    b.run(extra={"PANTHEON_NOTIFY_LOG": None, "PANTHEON_NO_NOTIFY": "1"}, evil={"PANTHEON_NOTIFY_LOG": evil})
    check("PANTHEON_NOTIFY_LOG из launchd: строку с заголовком PR в чужой файл проход не пишет",
          not os.path.exists(evil) and not os.path.exists(b.notify_log), b.outs[-1])


def test_env_fake():
    b = Box()
    b.request()
    fakes = {"PANTHEON_FAKE_IDLE": "5", "PANTHEON_FAKE_AC": "1", "PANTHEON_FAKE_WAKE": "1", "PANTHEON_FAKE_LIMIT": "1"}
    b.run(extra={"PANTHEON_FAKE_IDLE": "99999"}, evil=fakes)
    check("PANTHEON_FAKE_IDLE из launchd: простой не подменён — владельца нет, окна нет, заявка ждёт",
          not b.windows() and b.req() is not None, (b.outs[-1], b.windows()))
    leaked = sorted({k for c in b.calls("gh") for k in c.get("keys", []) if k in fakes and k != "PANTHEON_FAKE_IDLE"})
    check("PANTHEON_FAKE_* из launchd до gh не доходят", b.calls("gh") and not leaked, leaked)


def test_env_path():
    b = Box()
    b.request()
    ebin = os.path.join(b.tmp, "evil-bin")
    os.makedirs(ebin)
    script(os.path.join(ebin, "gh"), EVIL)
    b.run(evil={"PATH": ebin + ":/usr/bin:/bin"})
    check("PATH из launchd: gh не из него — поддельный gh не запускался, слит своим",
          not os.path.exists(os.path.join(b.rec, "evil")) and len(b.merges()) == 1, (b.outs[-1], b.merges()))


def test_env_gh_config():
    b = Box()
    b.request()
    bad = {"GH_CONFIG_DIR": os.path.join(b.tmp, "evil-gh"), "GH_TOKEN": "x", "GITHUB_TOKEN": "x",
           "GH_ENTERPRISE_TOKEN": "x", "XDG_CONFIG_HOME": os.path.join(b.tmp, "evil-xdg")}
    b.run(evil=bad)
    leaked = sorted({k for c in b.calls("gh") for k in c.get("keys", []) if k in bad})
    check("GH_CONFIG_DIR, токены и XDG_CONFIG_HOME из launchd до gh не доходят",
          len(b.merges()) == 1 and not leaked, leaked)


def test_env_python():
    """PANTHEON_PYTHON: тик не берёт его (и config.toml из PANTHEON_STATE), проход и щелчок — интерпретатор тика.
    PYTHONEXECUTABLE (на macOS задаёт sys.executable даже при -I) интерпретатор прохода не подменяет (argus-b 0303c)."""
    b = Box()
    b.request()
    b.set("touchid-rc", 2)
    # проход: PANTHEON_PYTHON ему ставит bin/pantheon из pass_env тика; sys.executable подменён PYTHONEXECUTABLE
    b.run(extra={"PANTHEON_PYTHON": PY311}, evil={"PYTHONEXECUTABLE": os.path.join(b.tmp, "evil-python")})
    note = open(b.notify_log).read() if os.path.exists(b.notify_log) else ""
    cmd = note.rstrip().split("|execute:", 1)[-1].rsplit("|", 1)[0] if "|execute:" in note else ""
    words = shlex.split(cmd) if cmd else []
    py = [w[len("PANTHEON_PYTHON="):] for w in words if w.startswith("PANTHEON_PYTHON=")]
    check("щелчок: /usr/bin/env -i, HOME, постоянный PATH и PANTHEON_PYTHON прохода, а не окружение уведомления",
          words[:2] == ["/usr/bin/env", "-i"] and f"HOME={os.path.realpath(b.home)}" in words
          and any(w.startswith("PATH=/usr/bin:/bin") for w in words) and len(py) == 1
          and os.path.realpath(py[0]) == os.path.realpath(PY311) and words[-2:] == ["run", "--click"], cmd)

    # тик: интерпретатор из PANTHEON_PYTHON, из config.toml чужого PANTHEON_STATE и из config.toml от HOME (HOME тоже
    # задаёт launchd; argus-b 0303, п. 1) не запускается. Тик — копия с заглушкой lib/run.py: config.toml он читает
    # от настоящей домашней папки учётной записи, и найденный там интерпретатор запустит только заглушку, а не тик.
    # PATH — только нужные утилиты, без python
    tools = os.path.join(b.tmp, "tools")
    os.makedirs(tools)
    for u in ("dirname", "readlink", "sed", "head", "date", "cat", "mkdir"):
        os.symlink(_shutil.which(u, path="/usr/bin:/bin"), os.path.join(tools, u))
    evil_py = script(os.path.join(b.tmp, "evil-python"), EVIL)
    evil_state = os.path.join(b.tmp, "evil-state")
    os.makedirs(evil_state)
    for d in (evil_state, b.state):   # b.state = HOME/.local/state/pantheon
        with open(os.path.join(d, "config.toml"), "w") as fh:
            fh.write(f'python = "{evil_py}"\n')
    plug = os.path.join(b.tmp, "plugin")
    os.makedirs(os.path.join(plug, "bin"))
    os.makedirs(os.path.join(plug, "lib"))
    tick = os.path.join(plug, "bin", "pantheon-tick")
    _shutil.copy2(os.path.join(os.path.dirname(HERE), "bin", "pantheon-tick"), tick)
    _shutil.copy2(os.path.join(LIBDIR, "find-python.sh"), os.path.join(plug, "lib", "find-python.sh"))
    with open(os.path.join(plug, "lib", "run.py"), "w") as fh:
        fh.write("import json, os, sys\nopen(os.path.join(os.environ['FAKE_REC'], 'tick-ran'), 'a').write(json.dumps("
                 "[sys.executable, os.environ.get('PANTHEON_PYTHON'), os.environ.get('PYTHONEXECUTABLE')]) + '\\n')\n")
    for name, extra in (("PANTHEON_PYTHON", {"PANTHEON_PYTHON": evil_py}),
                        ("config.toml из PANTHEON_STATE", {"PANTHEON_STATE": evil_state}),
                        ("config.toml от HOME", {})):
        env = {"PATH": tools, "HOME": b.home, "PANTHEON_HOME": b.pantheon, "FAKE_REC": b.rec, "TMPDIR": _ROOT,
               "PANTHEON_PY_DIRS": os.path.join(b.tmp, "nowhere")}
        env.update(extra)
        r = subprocess.run(["/bin/sh", tick], env=env, capture_output=True, text=True, timeout=60)
        check(f"тик: {name} из launchd — интерпретатор не запускается",
              not os.path.exists(os.path.join(b.rec, "evil")), (r.returncode, r.stderr[-300:]))
    os.unlink(os.path.join(b.state, "config.toml"))
    # тик снимает PYTHONEXECUTABLE до запуска python: иначе sys.executable тика (и pass_env, run_env его задач) —
    # заглушка из launchd. PANTHEON_PY_DIRS тик не берёт: кандидата оттуда он даже не проверяет (проверка его запускает)
    pydir = os.path.join(b.tmp, "pydir")
    os.makedirs(pydir)
    os.symlink(PY311, os.path.join(pydir, "python3"))
    ran = os.path.join(b.rec, "tick-ran")
    if os.path.exists(ran):
        os.unlink(ran)
    env = {"PATH": tools + ":" + pydir, "HOME": b.home, "PANTHEON_HOME": b.pantheon, "FAKE_REC": b.rec,
           "TMPDIR": _ROOT, "PYTHONEXECUTABLE": evil_py}
    r = subprocess.run(["/bin/sh", tick], env=env, capture_output=True, text=True, timeout=60)
    rows = [json.loads(x) for x in open(ran).read().splitlines()] if os.path.exists(ran) else []
    check("тик: PYTHONEXECUTABLE из launchd снят — sys.executable тика = PANTHEON_PYTHON тика, не заглушка",
          len(rows) == 1 and rows[0][1]
          and os.path.realpath(rows[0][0]) == os.path.realpath(rows[0][1]) != os.path.realpath(evil_py)
          and rows[0][2] is None
          and not os.path.exists(os.path.join(b.rec, "evil")), (rows, r.returncode, r.stderr[-300:]))
    evil_dir = os.path.join(b.tmp, "evil-dir")
    os.makedirs(evil_dir)
    for v in ("3.14", "3.13", "3.12", "3.11"):
        script(os.path.join(evil_dir, "python" + v), EVIL)
    env = {"PATH": tools, "HOME": b.home, "PANTHEON_HOME": b.pantheon, "FAKE_REC": b.rec, "TMPDIR": _ROOT,
           "PANTHEON_PY_DIRS": evil_dir}
    r = subprocess.run(["/bin/sh", tick], env=env, capture_output=True, text=True, timeout=60)
    check("тик: PANTHEON_PY_DIRS из launchd — кандидат оттуда не запускается",
          not os.path.exists(os.path.join(b.rec, "evil")), (r.returncode, r.stderr[-300:]))
    # а config.toml тик берёт от домашней папки учётной записи (account_home): её realpath, не HOME и не CDPATH
    import pwd
    r = subprocess.run(["/bin/sh", "-c", '. "$1"; account_home', "sh", os.path.join(LIBDIR, "find-python.sh")],
                       env={"PATH": tools, "HOME": b.home, "CDPATH": b.tmp}, capture_output=True, text=True, timeout=30)
    check("тик: домашняя папка для config.toml — realpath pw_dir учётной записи, не HOME из launchd",
          r.stdout.strip() == os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir), (r.stdout, r.stderr))

    # тик → проход: окружение с нуля, PANTHEON_PYTHON — интерпретатор, который нашёл тик (он ставит PANTHEON_PYTHON
    # сам), а не sys.executable: его подменяет PYTHONEXECUTABLE из launchd
    code = ("import json, sys; sys.path.insert(0, %r); import pantheon as p; got = []\n"
            "p.subprocess.Popen = lambda argv, **kw: got.append(kw.get('env'))\n"
            "p.merge_kick(); print(json.dumps([got, %r]))" % (LIBDIR, PY311))
    bad = {"PANTHEON_FAKE_IDLE": "5", "PANTHEON_NOTIFY_LOG": "/x", "GH_CONFIG_DIR": "/x", "PANTHEON_PYTHON": PY311,
           "PYTHONEXECUTABLE": evil_py}
    r = subprocess.run([PY311, "-I", "-c", code], env=b.env(T0, bad), capture_output=True, text=True, timeout=60)
    try:
        got, exe = json.loads(r.stdout.strip().splitlines()[-1])
        env = got[0] if len(got) == 1 else {}
    except (ValueError, IndexError):
        env, exe = {}, None
    check("тик → проход: окружение — HOME, постоянный PATH и PANTHEON_PYTHON тика, ничего из launchd",
          isinstance(env, dict) and sorted(env) == ["HOME", "PANTHEON_PYTHON", "PATH"] and env["PANTHEON_PYTHON"] == exe
          and env["PATH"].startswith("/usr/bin:/bin") and b.bin not in env["PATH"], r.stdout + r.stderr)


def test_env_home():
    """HOME не домашняя папка учётной записи (launchctl setenv HOME) — проход не идёт. Без обвязки: как у тика."""
    b = Box()
    b.request()
    r = subprocess.run([PY311, "-I", LIB, "merge", "run"], env=b.env(T0), capture_output=True, text=True, timeout=60)
    check("HOME из launchd не домашняя папка учётной записи → отказ (код 2), окна и слияния нет, заявка цела",
          r.returncode == 2 and not b.windows() and not b.merges() and b.req() is not None, r.stdout + r.stderr)


def test_env_clean():
    """Окружение прохода с нуля: всё, что не HOME и не постоянный PATH, снято; STATE и Пантеон — от HOME."""
    b = Box()
    code = ("import json, os, sys; sys.path.insert(0, %r); import pantheon as p; m = p.merge_mod(); m.TEST = {}\n"
            "why = m.clean_env(); print(json.dumps([why, dict(os.environ), p.STATE, p.PANTHEON, m.SAFE_PATH]))" % LIBDIR)
    env = b.env(T0, {"PANTHEON_STATE": os.path.join(b.tmp, "x"), "PANTHEON_HOME": os.path.join(b.tmp, "y"),
                     "DEVELOPER_DIR": b.tmp, "GH_CONFIG_DIR": b.tmp, "PANTHEON_TEST": "1"})
    r = subprocess.run([PY311, "-I", "-c", code], env=env, capture_output=True, text=True, timeout=60)
    try:
        why, got, state, pan, safe = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        why, got, state, pan, safe = "?", {}, None, None, None
    check("clean_env: окружение = HOME и постоянный PATH, STATE и Пантеон — от HOME",
          why is None and got == {"HOME": os.path.realpath(b.home), "PATH": safe}
          and state == os.path.realpath(b.state) and pan == os.path.realpath(b.pantheon), r.stdout + r.stderr)


def test_env_home_link():
    """argus-b 0303, п. 2: HOME — ссылка на домашнюю папку учётной записи. Сверка проходит, но дальше — realpath:
    в окружение, gh, P.CURRENT и команду щелчка путь через ссылку не идёт (её можно перевесить после сверки)."""
    b = Box()
    real = os.path.realpath(b.home)
    ver = os.path.join(real, ".local", "share", "pantheon", "versions", "1")
    os.makedirs(os.path.join(ver, "bin"))
    os.symlink(ver, os.path.join(real, ".local", "share", "pantheon", "current"))
    link = os.path.join(b.tmp, "home-link")
    os.symlink(b.home, link)
    log = os.path.join(b.tmp, "notify.log")
    # без обвязки TEST: сверка с учётной записью идёт, pw_dir учётной записи — та же ссылка
    code = ("import json, os, sys, types; sys.path.insert(0, %r); import pwd\n"
            "pwd.getpwuid = lambda uid: types.SimpleNamespace(pw_dir=%r)\n"
            "import pantheon as p; m = p.merge_mod(); why = m.clean_env(); env = dict(os.environ)\n"
            "os.environ['PANTHEON_NOTIFY_LOG'] = %r; m.fallback_notify({}, 'окно')\n"
            "print(json.dumps([why, env, p.HOME, p.AI_HOME, p.CURRENT, p.STATE, m.pass_env()]))"
            % (LIBDIR, link, log))
    env = dict(b.env(T0), HOME=link)
    r = subprocess.run([PY311, "-I", "-c", code], env=env, capture_output=True, text=True, timeout=60)
    try:
        why, got, home, ai, cur, state, passed = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        why, got, home, ai, cur, state, passed = "?", {}, None, None, None, None, {}
    check("HOME-ссылка: сверка проходит, в окружение, P.HOME, AI_HOME, CURRENT, STATE и pass_env — realpath",
          why is None and got.get("HOME") == real and home == real and ai == os.path.join(real, "ai")
          and cur.startswith(real + os.sep) and state == os.path.realpath(b.state) and passed.get("HOME") == real,
          r.stdout + r.stderr)
    note = open(log).read() if os.path.exists(log) else ""
    cmd = note.rstrip().split("|execute:", 1)[-1].rsplit("|", 1)[0] if "|execute:" in note else ""
    words = shlex.split(cmd) if cmd else []
    check("HOME-ссылка: в команде щелчка HOME и bin/pantheon — realpath (current разрешён), не через ссылку",
          f"HOME={real}" in words and os.path.join(ver, "bin", "pantheon") in words
          and not any(link in w for w in words), cmd or r.stderr)

if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:  # падение одного случая — провал, остальные идут
                FAILS.append(name)
                print(f"FAIL {name} — исключение {type(e).__name__}: {e}")
    print(f"\n{'ПРОВАЛ: ' + ', '.join(FAILS) if FAILS else 'все прошли'}")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
