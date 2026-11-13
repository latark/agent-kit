# ruff: noqa: F401, F403, F405  (импорты общей части нужны частям через import *)
"""Общая часть test_merge*.py (образец metis-0750, план 1.0 Т2): поддельные gh, Touch ID и osascript, Box, помощники. Сами случаи — в test_merge.py и test_merge_<часть>.py; здесь тестов нет."""
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
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
GUARD_HOOKS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "hooks")
T0 = 1_792_000_000
REPO = "latark/agent-kit"
FULL_TESTS_CMD = ("pantheon review test -- heavy python3.14 -I plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard "
                  "plugins/pantheon plugins/project-tools")
PR = 7
SHA = "abcdef1" + "0" * 33
SHA2 = "1234567" + "f" * 33
SHA3 = "9abcdef" + "e" * 33
TITLE = "guard: шлюз по Touch ID"

# gh: view — из rec/gh-view.json (нет файла — код 1), merge — код из rec/gh-merge-rc; argv — в rec/gh-argv.jsonl
FAKE_GH = r'''
import json, os, sys
rec = os.environ["FAKE_REC"]
with open(os.path.join(rec, "gh-argv.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "env": sorted(k for k in os.environ if k.startswith("GH_")),
                         "keys": sorted(os.environ)}) + "\n")
def one(name, n):
    # ответ на PR n (пачка, metis-0668): файл rec/<имя>-<n>.<расш>, если есть, иначе общий rec/<имя>.<расш>
    stem, ext = os.path.splitext(name)
    p = os.path.join(rec, f"{stem}-{n}{ext}")
    return p if os.path.exists(p) else os.path.join(rec, name)


def view_by_sha(sha):
    # ответ gh pr view того PR, чей head — sha: файлы rec/gh-view-<n>.json пачки, иначе общий rec/gh-view.json
    for f in sorted(os.listdir(rec)):
        if f.startswith("gh-view-") and f.endswith(".json"):
            v = json.load(open(os.path.join(rec, f)))
            if v.get("headRefOid") == sha:
                return v
    return json.load(open(os.path.join(rec, "gh-view.json")))


if sys.argv[1:3] == ["pr", "view"] and os.path.exists(os.path.join(rec, "gh-view-side")):
    # побочное действие первого gh pr view (metis-0959): дописать текст в файл — «владелец передумал» во время прохода
    side = os.path.join(rec, "gh-view-side")
    target, text = open(side, encoding="utf-8").read().split("\n", 1)
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(text)
    os.remove(side)
if sys.argv[1:3] == ["pr", "view"]:
    p = one("gh-view.json", sys.argv[3])
    if not os.path.exists(p):
        sys.exit(1)
    # как настоящий gh: только поля из --json (pr_view без baseRefName не получит его и из файла, argus М41)
    raw, want = open(p).read(), sys.argv[sys.argv.index("--json") + 1].split(",") if "--json" in sys.argv else None
    try:
        v = json.loads(raw)
    except ValueError:
        v = None
    # rec/unknown-once — номера PR: следующий gh pr view каждого из них один раз отдаёт mergeable UNKNOWN, как GitHub
    # после сдвига base (Б1 argus #381: mergeable считается лениво)
    uo = os.path.join(rec, "unknown-once")
    if isinstance(v, dict) and os.path.exists(uo) and sys.argv[3] in open(uo).read().split():
        v = dict(v, mergeable="UNKNOWN", mergeStateStatus="UNKNOWN")
        left = [n for n in open(uo).read().split() if n != sys.argv[3]]
        open(uo, "w").write(" ".join(left))
    print(json.dumps({k: x for k, x in v.items() if k in want}) if isinstance(v, dict) and want else raw)
    sys.exit(0)
if sys.argv[1:3] == ["pr", "merge"] and os.path.exists(os.path.join(rec, "base-moves")):
    # rec/base-moves — номера PR пачки: слияние одного сдвигает base, у остальных mergeable снова UNKNOWN
    left = [n for n in open(os.path.join(rec, "base-moves")).read().split() if n != sys.argv[3]]
    open(os.path.join(rec, "unknown-once"), "w").write(" ".join(left))
if sys.argv[1:3] == ["pr", "merge"]:
    p = one("gh-merge-rc", sys.argv[3])
    sys.exit(int(open(p).read()) if os.path.exists(p) else 0)
if sys.argv[1] == "api" and ("/actions/runs?" in sys.argv[2] or "/check-runs?" in sys.argv[2]):
    # запуски Actions (metis-0633): по rollup из gh-view.json, событие — поле "event" записи (по умолчанию
    # pull_request), PR — поле "prs" (по умолчанию 7), репозиторий и ветка head — "head_repo" и "head_branch" (PR из
    # форка, metis-0649); с gh-runs-fail — сбой, gh-runs-total — total_count запусков
    if os.path.exists(os.path.join(rec, "gh-runs-fail")):
        sys.exit(1)
    import re
    v = view_by_sha(re.search(r"[0-9a-f]{40}", sys.argv[2]).group(0))
    sha, runs, checks = v.get("headRefOid"), [], []
    for i, c in enumerate(v.get("statusCheckRollup") or []):
        if isinstance(c, dict) and "context" not in c:
            runs.append({"name": c.get("workflowName"), "event": c.get("event", "pull_request"), "head_sha": sha,
                         "check_suite_id": 1000 + i, "pull_requests": [{"number": n} for n in c.get("prs", [v.get("_pr", 7)])],
                         "head_repository": {"full_name": c.get("head_repo", "latark/agent-kit")},
                         "head_branch": c.get("head_branch", "main")})
            checks.append({"name": c.get("name"), "status": str(c.get("status") or "").lower(),
                           "conclusion": str(c["conclusion"]).lower() if c.get("conclusion") else None,
                           "head_sha": sha, "check_suite": {"id": 1000 + i}, "id": 5000 + i,
                           "output": {"annotations_count": len(c.get("notes") or [])}})
    total = os.path.join(rec, "gh-runs-total")
    total = int(open(total).read()) if os.path.exists(total) else len(runs)
    print(json.dumps({"total_count": total, "workflow_runs": runs} if "/actions/runs?" in sys.argv[2]
                     else {"total_count": len(checks), "check_runs": checks}))
    sys.exit(0)
if sys.argv[1] == "api" and "/check-runs/" in sys.argv[2] and "/annotations" in sys.argv[2]:
    # аннотации проверки (metis-0655): id 5000+i — поле "notes" записи i rollup; с gh-notes-fail — сбой
    if os.path.exists(os.path.join(rec, "gh-notes-fail")):
        sys.exit(1)
    i = int(sys.argv[2].split("/check-runs/")[1].split("/")[0]) - 5000
    v = json.load(open(os.path.join(rec, "gh-view.json")))
    print(json.dumps(v["statusCheckRollup"][i].get("notes") or []))
    sys.exit(0)
if sys.argv[1] == "api" and "/actions/jobs/" in sys.argv[2]:
    # данные job (metis-0655): id 5000+i — поле "job" записи i rollup, без поля — job стартовал (раннер и шаг);
    # с gh-jobs-fail — сбой
    if os.path.exists(os.path.join(rec, "gh-jobs-fail")):
        sys.exit(1)
    i = int(sys.argv[2].rsplit("/", 1)[1]) - 5000
    v = json.load(open(os.path.join(rec, "gh-view.json")))
    print(json.dumps(v["statusCheckRollup"][i].get("job") or {"runner_id": 5, "runner_name": "r5",
                                                              "steps": [{"name": "Set up job"}]}))
    sys.exit(0)
if sys.argv[1] == "api" and "/git/ref/heads/" in sys.argv[2]:
    # вершина ветки base (code_facts, metis-0966): rec/gh-tip — SHA (по умолчанию b×40, как base_oid Box.decide),
    # с gh-tip-fail — сбой
    if os.path.exists(os.path.join(rec, "gh-tip-fail")):
        sys.exit(1)
    t = os.path.join(rec, "gh-tip")
    print(json.dumps({"ref": "refs/heads/" + sys.argv[2].split("/git/ref/heads/")[1],
                      "object": {"sha": open(t).read().strip() if os.path.exists(t) else "b" * 40, "type": "commit"}}))
    sys.exit(0)
if sys.argv[1] == "api" and "/compare/" in sys.argv[2] and "--jq" not in sys.argv:
    # сравнение прошлого head с новым целиком (delta_gh_problem, metis-0784): rec/gh-cmp.json — {"base...sha": ответ};
    # пары нет — код 1
    t = os.path.join(rec, "gh-cmp.json")
    got = json.load(open(t)).get(sys.argv[2].split("/compare/")[1]) if os.path.exists(t) else None
    if got is None:
        sys.exit(1)
    print(json.dumps(got))
    sys.exit(0)
if sys.argv[1] == "api" and "/compare/" in sys.argv[2]:
    # merge-base head и base (narrow_gh_problem, metis-1050): rec/gh-mb — SHA (по умолчанию c×40); gh-mb-fail — сбой
    if os.path.exists(os.path.join(rec, "gh-mb-fail")):
        sys.exit(1)
    t = os.path.join(rec, "gh-mb")
    print(open(t).read().strip() if os.path.exists(t) else "c" * 40)
    sys.exit(0)
if sys.argv[1] == "api" and "/contents/" in sys.argv[2]:
    # сырой файл карты в дереве head (narrow_gh_problem, metis-1050): rec/gh-map; нет файла — код 1
    t = os.path.join(rec, "gh-map")
    if not os.path.exists(t):
        sys.exit(1)
    sys.stdout.write(open(t).read())
    sys.exit(0)
if sys.argv[1] == "api" and "/pulls/" in sys.argv[2] and sys.argv[2].split("?")[0].endswith("/files"):
    p = one("gh-files.jsonl", sys.argv[2].split("/pulls/")[1].split("/")[0])
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
o = os.path.join(rec, "touchid-out")
if os.path.exists(o):
    print(open(o).read())
p = os.path.join(rec, "touchid-rc")
sys.exit(int(open(p).read()) if os.path.exists(p) else 0)
'''

# Тестовая обвязка прохода: подмены — атрибутом merge.TEST в её процессе (из окружения launchd его не включить),
# переменные для прохода — из MERGE_TEST, который читает только обвязка
# attrs — подмены атрибутов модулей в процессе обвязки (metis-0710): "p" — pantheon (MANAGED), "m" — merge
# (OSASCRIPT, ROOT_OWNER, MANAGED_WAIT); /Library и настоящий osascript тесты не трогают
HARNESS = ("import json, os, sys; sys.path.insert(0, %r); import pantheon as p; m = p.merge_mod(); "
           "m.TEST = json.loads(os.environ.pop('MERGE_TEST')); "
           "[setattr(mod, k, v) for mod, key in ((p, 'p'), (m, 'm')) "
           "for k, v in (m.TEST.get('attrs') or {}).get(key, {}).items()]; "
           "sys.exit(p.main(sys.argv[1:]))" % LIBDIR)

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


# первые три проверки — обязательные agent-kit (REQUIRED_CHECKS, metis-0633 и metis-1111): tests/affected,
# check-traces/traces и tests/full (полный набор на macos-15)
CI_NAMES = (("tests", "affected"), ("check-traces", "traces"), ("tests", "full"))


def ci(*states):
    """Rollup по состояниям проверок в порядке CI_NAMES, дальше — other/job<i>. Ровно два состояния — affected и
    traces, а обязательная tests/full (metis-1111) дописывается зелёной: случаи до 1111 судят первые две."""
    if len(states) == 2:
        states = (*states, "SUCCESS")
    return [{"__typename": "CheckRun", "workflowName": CI_NAMES[i][0] if i < len(CI_NAMES) else "other",
             "name": CI_NAMES[i][1] if i < len(CI_NAMES) else f"job{i}",
             "status": "COMPLETED" if s != "PENDING" else "IN_PROGRESS",
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

    def cli(self, args, t=T0, extra=None, evil=None, attrs=None):
        env = self.env(t, extra)
        if args[:2] == ["merge", "run"]:
            # проход — через обвязку HARNESS: подмены (поддельный gh в PATH, часы, простой, журнал уведомлений) —
            # только атрибутом merge.TEST в её процессе (metis-0303). evil — то, что дописало бы в окружение
            # прохода launchd (launchctl setenv): проход его не берёт
            cmd = [PY311, "-I", "-c", HARNESS] + args
            env = dict(env, **(evil or {}), MERGE_TEST=json.dumps({"env": env, "attrs": attrs or {}}))
        else:
            cmd = [PY311, "-I", RUN_PY] + args
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
        self.outs.append(r.stdout + r.stderr)
        return r

    def request(self, pr=PR, repo=REPO, t=T0):
        return self.cli(["merge", "request", str(pr), "-R", repo], t=t)

    def run(self, t=T0, click=False, extra=None, evil=None, attrs=None):
        return self.cli(["merge", "run"] + (["--click"] if click else []), t=t, extra=extra, evil=evil, attrs=attrs)

    def view(self, sha, state="OPEN", draft=False, checks=None, title=TITLE, files=None, count=None, base="main",
             head=None, pr=None, mergeable="MERGEABLE", merge_state="CLEAN"):
        """Ответ gh pr view и REST pulls/N/files: files — имена или словари; count — changedFiles (по умолчанию
        len(files)); base — baseRefName (None — поля нет); head — поля головы PR (isCrossRepository и др.); pr —
        ответ только этого PR (пачка, metis-0668), иначе общий для всех; mergeable, merge_state — mergeable и
        mergeStateStatus (None — поля нет, metis-0819)."""
        sfx = "" if pr is None else f"-{pr}"
        files = FILES if files is None else files
        recs = [f if isinstance(f, dict) else {"filename": f, "status": "modified"} for f in files]
        with open(os.path.join(self.rec, f"gh-view{sfx}.json"), "w") as fh:
            json.dump({"headRefOid": sha, "state": state, "isDraft": draft, "title": title,
                       **({} if pr is None else {"_pr": pr}),
                       **({} if base is None else {"baseRefName": base}),
                       **({} if mergeable is None else {"mergeable": mergeable}),
                       **({} if merge_state is None else {"mergeStateStatus": merge_state}),
                       "statusCheckRollup": ci("SUCCESS", "SUCCESS") if checks is None else checks,
                       "changedFiles": len(recs) if count is None else count, **(head or {})}, fh)
        with open(os.path.join(self.rec, f"gh-files{sfx}.jsonl"), "w") as fh:
            fh.write("".join(json.dumps(r) + "\n" for r in recs))

    def set(self, name, value):
        with open(os.path.join(self.rec, name), "w") as fh:
            fh.write(str(value))

    def add(self, kind, sha=SHA, pr=PR, who="argus", sid="s1", aid="a1", ran="модель: claude-opus-5-5, тесты",
            models=None, cmd=None, base="main", **extra):
        rec = {"v": 1, "kind": kind, "repo": [REPO], "pr": None if kind == "tests" else pr, "sha": sha,
               "by": {"agent_type": who, "agent_id": aid, "session_id": sid}}
        if kind == "tests":   # команда полного набора — на запасном пути при лимите минут засчитывается только она
            rec["cmd"] = FULL_TESTS_CMD if cmd is None else cmd
        if kind in ("accept", "reject"):
            rec["checklist"] = {"opened": "diff", "ran": ran, "unchecked": "ничего"}
            if base is not None:   # base PR при записи вердикта (metis-0965); None — запись до 0965
                rec["base"] = base
        if models is not None:   # модели транскрипта argus, как их пишет хук guard (metis-0176)
            rec["models"] = models
        rec.update(extra)   # поля хука guard: returned и reported (metis-0497)
        self.records.append(rec)
        d = os.path.join(self.state, "merge-gate")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "records.jsonl"), "w") as fh:
            fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.records))

    def decide(self, sha=SHA, same=(), differs=(), base="main", t=T0, pr=PR, **extra):
        """Решение шлюза guard о коде head (metis-0966) — строка kind "decision" в carry.jsonl, как её пишет
        merge_gate.request_decisions при `pantheon merge request`; t — время записи."""
        from datetime import datetime as _dt
        rec = {"v": 1, "kind": "decision", "repo": [REPO], "pr": pr, "sha": sha, "base": base, "base_oid": "b" * 40,
               "same": list(same), "differs": list(differs), "why": [],
               "by": {"agent_type": "dev-opus", "session_id": "s-lead", "agent_id": ""},
               "time": _dt.fromtimestamp(t).astimezone().isoformat(timespec="seconds"), **extra}
        d = os.path.join(self.state, "merge-gate")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "carry.jsonl"), "a") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def gate_ok(self, sha, pr=PR, base="main"):
        self.add("tests", sha=sha, who="")
        self.add("accept", sha=sha, pr=pr, sid="s1", aid="a1", base=base)
        self.add("accept", sha=sha, pr=pr, sid="s2", aid="a2", base=base)

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
    code = ("import sys; sys.path.insert(0, %r); import guard_rules; import merge_gate as m; "
            "print(m.owner_approved(%r, %d, %r, now=%r))" % (GUARD_HOOKS, repo, pr, sha, now))
    r = subprocess.run([sys.executable, "-I", "-c", code], env={"HOME": b.home, "PATH": "/usr/bin:/bin"},
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip() == "True", r.stdout + r.stderr


EVIL = r'''
import os, sys
open(os.path.join(os.environ["FAKE_REC"], "evil"), "a").write("x\n")
sys.exit(0)
'''


def window_script(body, rc):
    """Поддельный помощник: делает body (то, что случилось, пока окно открыто), пишет argv и выходит с кодом rc."""
    return ("import json, os, sys\nrec = os.environ['FAKE_REC']\nstate = os.environ['PANTHEON_STATE']\n"
            "open(os.path.join(rec, 'touchid-argv.jsonl'), 'a').write(json.dumps({'argv': sys.argv[1:]}) + '\\n')\n"
            + body + "\nsys.exit(%d)\n" % rc)


CANCEL_BODY = ("q = os.path.join(state, 'merge-queue')\n"
               "[os.remove(os.path.join(q, f)) for f in os.listdir(q) if f.endswith('.json')]")


def jsonl(b):
    p = os.path.join(b.state, "logs", "merge.jsonl")
    return [json.loads(ln) for ln in open(p)] if os.path.exists(p) else []


FORK = {"isCrossRepository": True, "headRepository": {"id": "R_x", "name": "agent-kit", "nameWithOwner": "Ext/agent-kit"},
        "headRefName": "feat"}


BILLING = ("The job was not started because recent account payments have failed or your spending limit needs to be "
           "increased. Please check the 'Billing & plans' section in your settings")


def billing_note(message=BILLING, level="failure", path=".github"):
    """Аннотация проверки, как её отдаёт GitHub (сохранённый ответ PR #222, plugins/guard/tests/fixtures)."""
    return {"path": path, "start_line": 1, "end_line": 1, "annotation_level": level, "title": "", "message": message,
            "raw_details": ""}


# job, который не стартовал из-за лимита (GET actions/jobs/<id> заблокированной проверки PR #222, 02.11)
JOB_IDLE = {"status": "completed", "conclusion": "failure", "runner_id": 0, "runner_name": "", "runner_group_id": 0,
            "runner_group_name": None, "steps": []}


PJ = "plugins/pantheon/.claude-plugin/plugin.json"
# случаи номера версии (metis-0512): (файлы PR, отказ?) — общие для прохода и шлюза guard
VERSION_CASES = [
    ([{"filename": PJ, "status": "modified", "patch": '@@ -2 +2 @@\n-  "version": "0.11.1",\n+  "version": "0.11.2",'}],
     True),
    ([{"filename": PJ, "status": "modified", "patch": '@@ -3 +3 @@\n-  "description": "a",\n+  "description": "b",'}],
     False),
    ([{"filename": PJ, "status": "modified", "patch": '@@ -2 +2 @@\n+  "\\u0076ersion": "9.9.9",'}], True),
    ([{"filename": PJ, "status": "modified", "patch": '@@ -2 +2 @@\n+  "VERSION": "9.9.9",'}], True),
    ([{"filename": PJ, "status": "modified"}], True),
    ([{"filename": PJ, "status": "added", "patch": '+{"version": "0.1.0"}'}], False),
    ([{"filename": PJ, "status": "removed", "patch": '-{"version": "0.1.0"}'}], False),
    ([{"filename": "plugins/new/.claude-plugin/plugin.json", "previous_filename": PJ, "status": "renamed",
       "patch": '-  "version": "1",\n+  "version": "2",'}], True),
    ([{"filename": ".claude-plugin/releases.json", "status": "modified", "patch": "+{}"}], True),
    ([{"filename": ".Claude-Plugin/Releases.JSON", "status": "added", "patch": "+{}"}], True),
    ([{"filename": "x.json", "previous_filename": ".claude-plugin/releases.json", "status": "renamed"}], True),
    ([{"filename": "README.md", "status": "modified", "patch": '+ "version": "1"'}], False),
    ([{"filename": "plugins/pantheon/x/plugin.json", "status": "modified", "patch": '+ "version": "1"'}], False),
]


# --- управляемые настройки guard по Touch ID (metis-0710) ------------------------------------------------------------

# окно прав администратора: argv — в rec/osascript-argv.jsonl; режим — rec/osascript-mode: ok (по умолчанию) —
# скрипт root через /bin/sh -c, как do shell script; cancel — «Отменить» (-128); sleep — ответа нет; swap — после
# сверки проходом проверенный файл подменили, затем скрипт root
FAKE_OSASCRIPT = r"""
import json, os, shutil, subprocess, sys, time
rec = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0]))), "rec")
with open(os.path.join(rec, "osascript-argv.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:]}) + "\n")
p = os.path.join(rec, "osascript-mode")
mode = open(p).read().strip() if os.path.exists(p) else "ok"
if mode == "cancel":
    sys.stderr.write("0:150: execution error: User canceled. (-128)\n")
    sys.exit(1)
if mode == "sleep":
    time.sleep(30)
    sys.exit(0)
if mode == "lie":   # окно ответило «да», а файл не поставлен
    sys.exit(0)
if mode == "die":   # окно закрыли «Отменить», а проход в ту же минуту оборвали (срок тика) — SIGKILL родителю
    import signal
    os.kill(os.getppid(), signal.SIGKILL)
    sys.exit(1)
script = sys.argv[-2]
if mode == "swap":
    with open(open(os.path.join(rec, "managed-src")).read(), "w") as fh:
        fh.write('{"evil": true}\n')
if not os.path.exists("/usr/sbin/chown"):   # Linux CI: chown не в /usr/sbin
    script = script.replace("/usr/sbin/chown", shutil.which("chown"))
sys.exit(subprocess.run(["/bin/sh", "-c", script]).returncode)
"""
M_NEW = b'{"hooks": {"PreToolUse": []}, "v": "new"}\n'
M_OLD = b'{"hooks": {}, "v": "old"}\n'
M_VER = "0.5.99"


def managed_box(installed=M_OLD):
    """Коробка с проверенным деревом guard (installed_plugins.json и verified.json с его хешем), файлом «/Library»
    во временной папке и поддельным osascript; installed=None — файла нет."""
    b = Box()
    tree = os.path.join(b.home, ".claude", "plugins", "cache", "agent-kit", "guard", M_VER)
    os.makedirs(os.path.join(tree, ".claude-plugin"))
    with open(os.path.join(tree, ".claude-plugin", "plugin.json"), "w") as fh:
        json.dump({"name": "guard", "version": M_VER}, fh)
    with open(os.path.join(tree, "managed-settings.json"), "wb") as fh:
        fh.write(M_NEW)
    with open(os.path.join(b.home, ".claude", "plugins", "installed_plugins.json"), "w") as fh:
        json.dump({"plugins": {"guard@agent-kit": [{"scope": "user", "installPath": tree}]}}, fh)
    b.tree = tree
    mverify(b)
    os.makedirs(os.path.join(b.pantheon, "directions", "metis-pantheon", "tasks"))
    b.msrc = os.path.join(tree, "managed-settings.json")
    b.set("managed-src", b.msrc)
    b.mdest = os.path.join(b.tmp, "Library", "ClaudeCode", "managed-settings.json")
    os.makedirs(os.path.dirname(b.mdest))
    if installed is not None:
        with open(b.mdest, "wb") as fh:
            fh.write(installed)
    b.osa = script(os.path.join(b.bin, "osascript-fake"), FAKE_OSASCRIPT)
    b.mattrs = {"p": {"MANAGED": b.mdest},
                "m": {"OSASCRIPT": b.osa, "ROOT_OWNER": f"{os.getuid()}:{os.getgid()}", "MANAGED_WAIT": 3}}
    return b


def mverify(b, version=M_VER):
    """verified.json: дерево b.tree проверено (хеш считает сам pantheon)."""
    code = ("import sys; sys.path.insert(0, %r); import pantheon as p; print(p._tree_hash(%r))"
            % (LIBDIR, os.path.realpath(b.tree)))
    r = subprocess.run([PY311, "-I", "-c", code], env=b.env(T0), capture_output=True, text=True, timeout=60)
    os.makedirs(os.path.join(b.state, "plugins"), exist_ok=True)
    with open(os.path.join(b.state, "plugins", "verified.json"), "w") as fh:
        json.dump({"guard": {"hash": r.stdout.strip(), "path": b.tree, "version": version}}, fh)


def mrun(b, t=T0, extra=None):
    return b.run(t=t, extra=extra, attrs=b.mattrs)


def mstate(b):
    p = os.path.join(b.state, "managed-update.json")
    return json.load(open(p)) if os.path.exists(p) else {}


def mcards(b):
    """Карточки направления защит: [(путь, текст)]."""
    d = os.path.join(b.pantheon, "directions", "metis-pantheon", "tasks")
    return [(os.path.join(d, f), open(os.path.join(d, f), encoding="utf-8").read()) for f in sorted(os.listdir(d))
            if f.endswith(".md")]


def mdest(b):
    return open(b.mdest, "rb").read() if os.path.exists(b.mdest) else None


def mkick(b, t=T0):
    """Тик: merge_kick с файлом «/Library» коробки → (результат, строки dryrun.log этого вызова)."""
    code = ("import sys; sys.path.insert(0, %r); import pantheon as p; p.MANAGED = %r; p.merge_kick()"
            % (LIBDIR, b.mdest))
    r = subprocess.run([PY311, "-I", "-c", code], env=b.env(t, {"PANTHEON_DRYRUN": "1"}), capture_output=True,
                       text=True, timeout=60)
    p = os.path.join(b.state, "dryrun.log")
    log = open(p).read() if os.path.exists(p) else ""
    if os.path.exists(p):
        os.remove(p)
    return r, log


# --- пачка: одно окно на несколько PR (metis-0668) ----------------------------------------------------------------------

BATCH_SHA = {7: SHA, 8: SHA2, 9: SHA3}


def merge_argv(pr):
    return ["pr", "merge", str(pr), "-R", REPO, "--match-head-commit", BATCH_SHA[pr], "--merge"]


def batch_box(prs=(7, 8)):
    """Коробка с PR prs: у каждого свой head (BATCH_SHA), свой ответ gh и пройденный шлюз на своём SHA."""
    b = Box()
    for pr in prs:
        b.view(BATCH_SHA[pr], pr=pr, title=f"PR {pr}", files=["README.md", CORE_FILE] if pr == 7 else ["docs.md"])
        if pr != PR:
            b.gate_ok(BATCH_SHA[pr], pr=pr)
    return b


def request_batch(b, prs=(7, 8)):
    return b.cli(["merge", "request"] + [str(n) for n in prs] + ["-R", REPO])


# --- согласие фразой «слей #N <hex>» (metis-0959) ---------------------------------------------------------------------
AWAY = {"PANTHEON_FAKE_IDLE": "900"}   # владельца нет у Mac: окна Touch ID не будет, фразе это не мешает
CTX_HOOK = os.path.join(os.path.dirname(HERE), "hooks", "ctx.py")


def say(b, text, t, note="", name="zeus", folder=None):
    """Запись журнала ваших слов в формате append_owner_line (hooks/ctx.py): заголовок с местным временем."""
    from datetime import datetime as _dt
    d = folder or os.path.join(b.state, "owner-log")
    os.makedirs(d, mode=0o700, exist_ok=True)
    body = "\n".join((" " + ln) if ln.startswith("##") else ln for ln in text.split("\n"))
    with open(os.path.join(d, name + ".md"), "a", encoding="utf-8") as fh:
        fh.write("## %s%s\n%s\n\n" % (_dt.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"),
                                      (" · " + note) if note else "", body))


def merge_recs(b):
    p = os.path.join(b.state, "logs", "merge.jsonl")
    return [json.loads(ln) for ln in open(p)] if os.path.exists(p) else []


def phrase_box(text=None, t=T0 + 60, **kw):
    b = Box()
    b.request()
    if text is not None:
        say(b, text, t, **kw)
    return b


def merged_once(b):
    return b.merges() == [["pr", "merge", str(PR), "-R", REPO, "--match-head-commit", SHA, "--merge"]]


def untouched(b):
    """Фраза не подействовала: слияния и строки согласия нет, заявка ждёт."""
    return not b.merges() and not b.approve_lines() and b.req() is not None


def _hook(b, ev, wait="1"):
    env = {"PATH": "/usr/bin:/bin", "HOME": b.home, "PANTHEON_HOME": b.pantheon, "PANTHEON_STATE": b.state,
           "PANTHEON_VIEW": os.path.join(b.home, "ai", "pantheon-view"), "CLAUDE_PID": str(os.getpid()),
           "CLAUDE_CODE_ENTRYPOINT": "cli", "PANTHEON_CONFIRM_WAIT": wait, "TMPDIR": _ROOT}
    return subprocess.run([PY311, "-I", CTX_HOOK, "owner-log"], input=json.dumps(ev), env=env, capture_output=True,
                          text=True, timeout=60)


__all__ = [k for k in list(globals()) if not k.startswith("__")]   # всё, включая _помощники: части берут их через import *
