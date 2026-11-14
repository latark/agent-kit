#!/usr/bin/env python3
"""Общая часть тестов запора слияния guard 0.5.4 (P1-4, Д2, Д3): журнал merge-gate пишет хук на PostToolUse, gh pr
merge проходит только с записями тестов и «принять» от argus на этот SHA (--match-head-commit), продукт — ещё talos и
строка «откат», защиты — ещё Д3 (поддельный gh в PATH). Подменённый HOME во временной папке, всё убирается в конце.

Здесь — поддельный HOME и gh (Home), записи журнала, помощники истории git и main(cases) — прогон случаев части.
Сами случаи — в частях test_merge_gate_{journal,core,opus,ci,billing,narrow,returned,carry,r4,sandbox,gh,limits}.py
(разрез metis-1119: целый файл шёл 349 с в GitHub Actions). Каждая часть запускается сама:
python3 -I plugins/guard/tests/test_merge_gate_<часть>.py   (код 0 — все прошли)
"""
import hashlib  # noqa: F401  (нужен частям через import *: narrow)
import json
import os
import re  # noqa: F401  (нужен частям через import *)
import shutil
import stat  # noqa: F401  (нужен частям через import *)
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import mkroot  # noqa: E402  (metis-0729)
from _par import run_cases  # noqa: E402  (metis-0544)

# Срок подпроцессов теста: на нагруженном Mac (проход outside, -j3, load 11-20) 10-30 с не хватает (metis-0634).
SUB_TIMEOUT = 60
# Сроки внутри хука (metis-0719): под той же нагрузкой хук порой не укладывался в DEADLINE 8 с, а git в нём — в
# timeout=3, и 1-3 случая из 1662 краснели не по своей вине. Загрузчик _cached_main поднимает их только вызовам из
# теста (GUARD_TEST_DEADLINE, GUARD_TEST_SUB_TIMEOUT); код guard и бой не меняются. HOOK_DEADLINE < SUB_TIMEOUT: хук
# успевает отказать сам, раньше, чем тест его погасит. merge_gate, загруженный в процесс теста (_load_merge_gate: r4,
# carry), получает тот же HOOK_SUB_TIMEOUT через _SlowSubprocess.
HOOK_DEADLINE = 40
HOOK_SUB_TIMEOUT = 20
SLOW_GIT = 50  # с: «медленный git» дольше и HOOK_SUB_TIMEOUT, и HOOK_DEADLINE
# бюджет сверки отпечатков в хуке (metis-0696, «А: запас только в тестах»): боевые 4 с под нагрузкой Mac r6 не
# укладывал, 15 с не хватило при load 200+ в полном наборе (metis-0989, r6 ctl2) — взят предел CARRY_BUDGET_MAX.
# Зависший git (r4 шлюз) гаснет по HOOK_SUB_TIMEOUT, остаток бюджета идёт на остальные отпечатки, хук укладывается
# в HOOK_DEADLINE
HOOK_CARRY_BUDGET = 15
import tempfile
import time
import uuid

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard.py")
RULES = os.path.join(os.path.dirname(GUARD), "guard_rules.py")  # правила; guard.py — короткий вход (metis-0148)
CACHED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cached_main.py")  # guard из .pyc (metis-0544)
OLD = "b" * 40
CORE = "ядро защит — PR ждёт слияния владельцем (Д3)"
# перечень проверенного в «принять» (Б6, guard 0.5.6): кавычки и пробелы внутри поля, обе формы флага
# ran начинается с модели: в репозиториях защит шлюз засчитывает только argus на Opus (metis-0176)
CL = (' --opened "merge_gate.py, README (раздел «запор»)"'
      ' --ran=\'модель: claude-opus-5-5, heavy python3 -I tests/test_merge_gate.py "84 из 84"\' --unchecked "живой gh"')
CHECKLIST = {"opened": "merge_gate.py, README (раздел «запор»)",
             "ran": 'модель: claude-opus-5-5, heavy python3 -I tests/test_merge_gate.py "84 из 84"',
             "unchecked": "живой gh"}
results = []
# statusCheckRollup: CheckRun (status, conclusion) и StatusContext (state)
RUN_OK = {"__typename": "CheckRun", "name": "check-traces", "status": "COMPLETED", "conclusion": "SUCCESS"}
GREEN = [RUN_OK, {"__typename": "StatusContext", "context": "ci/legacy", "state": "SUCCESS"}]
# обязательные проверки agent-kit (REQUIRED_CHECKS, metis-0633): job affected из tests.yml и traces из check-traces.yml
AFFECTED = {"__typename": "CheckRun", "workflowName": "tests", "name": "affected", "status": "COMPLETED",
            "conclusion": "SUCCESS"}
TRACES = dict(AFFECTED, workflowName="check-traces", name="traces")
GREEN_KIT = GREEN + [AFFECTED, TRACES]
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
BASE = "c" * 40  # baseRefOid в ответе gh pr view


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))


def git(path, *args):
    return subprocess.run(["git", "-C", path, "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


NORMAL = {"stdout": "", "stderr": "", "interrupted": False, "isImage": False}  # ответ обычной команды
BG = dict(NORMAL, backgroundTaskId="bxyz")  # ответ фоновой: PostToolUse приходит при запуске (ревью argus PR #18)
MISSING = object()


def rest_runs(view):
    """Ответы REST actions/runs?head_sha и commits/SHA/check-runs по rollup ответа gh pr view (metis-0633): каждая
    CheckRun — свой запуск Actions своего workflow; событие — поле "event" записи (по умолчанию pull_request), head —
    headRefOid, PR — поле "prs" записи (по умолчанию 7, номер PR agent-kit в тестах), репозиторий и ветка head —
    поля "head_repo" и "head_branch" (по умолчанию latark/agent-kit и main; PR из форка, metis-0649); StatusContext в
    REST запусков нет. Проверка i — id 5000+i, её аннотации — поле "notes" записи (metis-0655, файл gh.notes.<id>), данные
    её job — поле "job" (файл gh.jobs.<id>)."""
    sha, rollup, runs, checks = view.get("headRefOid"), view.get("statusCheckRollup"), [], []
    for i, c in enumerate(rollup if isinstance(rollup, list) else []):
        if not isinstance(c, dict) or not ("conclusion" in c or "status" in c and "state" not in c):
            continue
        runs.append({"id": i, "name": c.get("workflowName"), "event": c.get("event", "pull_request"), "head_sha": sha,
                     "check_suite_id": 1000 + i, "pull_requests": [{"number": n} for n in c.get("prs", (7,))],
                     "head_repository": {"full_name": c.get("head_repo", "latark/agent-kit")},
                     "head_branch": c.get("head_branch", "main")})
        checks.append({"name": c.get("name"), "status": str(c.get("status") or "").lower(),
                       "conclusion": str(c["conclusion"]).lower() if c.get("conclusion") else None, "head_sha": sha,
                       "check_suite": {"id": 1000 + i}, "id": 5000 + i,
                       "output": {"annotations_count": len(c.get("notes") or ())}})
    return {"total_count": len(runs), "workflow_runs": runs}, {"total_count": len(checks), "check_runs": checks}


class Home:
    def __init__(self, root):
        self.root = root
        self.carry_budget = HOOK_CARRY_BUDGET  # GUARD_TEST_CARRY_BUDGET хуку; t_carry_r6 поднимает до предела
        self.core = False  # reset(): PR agent-kit#7 задевает ядро (со строкой согласия владельца) — см. CASES_CORE
        j = self.j
        for d in ("ai/pantheon", ".local/state/pantheon", ".claude/pantheon", "bin"):
            os.makedirs(j(d), exist_ok=True)
        self.sha = {}
        for name, url in (("agent-kit", "https://github.com/latark/agent-kit"),
                          ("tg-read", "git@github.com:latark/tg-read.git"),
                          ("broker", "https://github.com/latark/broker"),
                          ("notlisted", "https://github.com/latark/notlisted")):
            p = j("projects/" + name)
            os.makedirs(p)
            subprocess.run(["git", "init", "-q", "-b", "main", p], check=True)
            git(p, "remote", "add", "origin", url)
            git(p, "commit", "-q", "--allow-empty", "-m", "init")
            self.sha[name] = git(p, "rev-parse", "HEAD")
        with open(j(".local/state/pantheon/domains.json"), "w") as fh:
            json.dump({"domains": {"metis-pantheon": ["~/projects/agent-kit", "~/projects/tg-read",
                                                      "~/projects/notlisted"],
                                   "athena-shop": ["~/projects/broker"]}}, fh)
        with open(j(".claude/pantheon/policy.toml"), "w") as fh:
            fh.write('[coordinators]\nmetis-pantheon = ["~/projects/agent-kit"]\n'
                     '[merge_client]\nathena-shop = ["~/projects/broker"]\n'
                     '[merge_repos]\nmetis-pantheon = ["latark/agent-kit", "latark/tg-read"]\n'
                     'athena-shop = ["latark/broker"]\n')
        # поддельный gh: вызовы — в $HOME/gh.log, с $HOME/gh.fail — сбой любого вызова.
        # pr view N -R owner/repo … — $HOME/gh.view.<repo> ($5), с gh.ci.fail — сбой; один вызов на шлюз (metis-0297).
        # api …/contents/.github/workflows?ref=<sha> — с gh.wf.fail.<sha> 502, с gh.wf.<sha> его текст (код 0), иначе 404;
        # api …/pulls/N/files — $HOME/gh.files, с gh.api.fail — сбой, с gh.api.fail1 — сбой один раз (файл убирается)
        # api repos/o/<repo>/git/ref/heads/<ветка> — $HOME/gh.ref.<repo> (вершина base, metis-0404 Б1), нет файла — сбой
        # api repos/o/<repo>/actions/runs?head_sha=… и …/commits/<sha>/check-runs — $HOME/gh.runs.<repo> и
        # gh.checkruns.<repo> (rest_runs по rollup, metis-0633), нет файла — сбой
        # api repos/o/<repo>/check-runs/<id>/annotations — $HOME/gh.notes.<id> (metis-0655), нет файла — сбой
        with open(j("bin/gh"), "w") as fh:
            fh.write('#!/bin/sh\necho "$@" >> "$HOME/gh.log"\n[ -f "$HOME/gh.fail" ] && exit 1\n'
                     'case "$*" in\n'
                     '"pr view "*) [ -f "$HOME/gh.ci.fail" ] && exit 1; cat "$HOME/gh.view.$(basename "$5")"; exit 0;;\n'
                     '*contents/.github/workflows*) ref="${2##*ref=}"; '
                     '[ -f "$HOME/gh.wf.fail.$ref" ] && { echo "gh: Bad Gateway (HTTP 502)" >&2; exit 1; }; '
                     '[ -f "$HOME/gh.wf.$ref" ] && { cat "$HOME/gh.wf.$ref"; exit 0; }; '
                     'echo \'{"message":"Not Found","status":"404"}\'; echo "gh: Not Found (HTTP 404)" >&2; exit 1;;\n'
                     '*/git/ref/heads/*) r="$HOME/gh.ref.$(basename "${2%%/git/ref/*}")"; '
                     '[ -f "$r" ] || exit 1; cat "$r"; exit 0;;\n'
                     '*/actions/jobs/*) r="$HOME/gh.jobs.$(basename "$2")"; [ -f "$r" ] || exit 1; cat "$r"; exit 0;;\n'
                     '*/actions/runs*) r="$HOME/gh.runs.$(basename "${2%%/actions/runs*}")"; '
                     '[ -f "$r" ] || exit 1; cat "$r"; exit 0;;\n'
                     '*/check-runs/*/annotations*) x="${2#*/check-runs/}"; r="$HOME/gh.notes.${x%%/*}"; '
                     '[ -f "$r" ] || exit 1; cat "$r"; exit 0;;\n'
                     '*/check-runs*) r="$HOME/gh.checkruns.$(basename "${2%%/commits/*}")"; '
                     '[ -f "$r" ] || exit 1; cat "$r"; exit 0;;\n'
                     'esac\n'
                     'if [ "$1" = api ]; then [ -f "$HOME/gh.api.fail1" ] && { rm -f "$HOME/gh.api.fail1"; exit 1; }; '
                     '[ -f "$HOME/gh.api.fail" ] && exit 1; cat "$HOME/gh.files"; exit 0; fi\n'
                     'exit 1\n')
        os.chmod(j("bin/gh"), 0o755)

    def j(self, rel):
        return os.path.join(self.root, rel)

    @property
    def records(self):
        return self.j(".local/state/pantheon/merge-gate/records.jsonl")

    def reset(self):
        """Перед каждым случаем: пустой журнал, пустая сводка, gh отвечает PR без ядра на текущем SHA, проверки зелёные."""
        shutil.rmtree(self.j(".local/state/pantheon/merge-gate"), ignore_errors=True)
        shutil.rmtree(self.j(".local/state/pantheon/owner-log"), ignore_errors=True)
        for f in os.listdir(self.root):
            if f.startswith(("gh.fail", "gh.log", "gh.api.fail", "gh.ci.fail", "gh.wf.", "gh.view.", "gh.ref.",
                             "gh.runs.", "gh.checkruns.", "gh.notes.", "gh.jobs.")):
                os.remove(self.j(f))
        open(self.j("ai/pantheon/alerts.md"), "w").close()
        self.runs = {}  # ответы REST запусков Actions (имя → (runs, check-runs) или "fail"); без записи — rest_runs
        self.tip = {}  # вершина ветки base от gh api …/git/ref/heads (имя → SHA, "fail" — сбой); без записи — baseRefOid
        self.view = {name: {"headRefOid": self.sha[name], "baseRefOid": BASE, "baseRefName": "main", "changedFiles": 0,
                            "statusCheckRollup": GREEN_KIT if name == "agent-kit" else GREEN} for name in self.sha}
        for name in self.sha:
            self.write_view(name)
        self.gh(["README.md", "plugins/pantheon/lib/tasks.py"])  # pantheon.py — ядро по сборке окон (t_core_sandbox),
        # merge.py — ядро с metis-0598
        if self.core:  # PR ядра со строкой согласия владельца: «не на Opus» проверяется на нём, а не отпадает как не ядро
            self.gh(["README.md", "plugins/guard/hooks/merge_gate.py"])
            self.approve(f"{ts()} merge-approve latark/agent-kit#7 {self.sha['agent-kit']}")

    def reset_log(self):
        if os.path.exists(self.j("gh.log")):
            os.remove(self.j("gh.log"))

    def reset_wf(self):
        for f in os.listdir(self.root):
            if f.startswith("gh.wf."):
                os.remove(self.j(f))

    def write_view(self, name, raw=None):
        with open(self.j("gh.view." + name), "w") as fh:
            fh.write(raw if raw is not None else json.dumps(self.view[name]))
        for f in ("gh.runs." + name, "gh.checkruns." + name):
            if os.path.exists(self.j(f)):
                os.remove(self.j(f))
        got = getattr(self, "runs", {}).get(name) or rest_runs(self.view[name])
        rollup = self.view[name].get("statusCheckRollup")
        for i, c in enumerate(rollup if isinstance(rollup, list) else []):
            if isinstance(c, dict) and "notes" in c:
                with open(self.j(f"gh.notes.{5000 + i}"), "w") as fh:
                    json.dump(c["notes"], fh)
            if isinstance(c, dict) and "job" in c:
                with open(self.j(f"gh.jobs.{5000 + i}"), "w") as fh:
                    json.dump(c["job"], fh)
        if got != "fail":
            for f, body in zip(("gh.runs." + name, "gh.checkruns." + name), got):
                with open(self.j(f), "w") as fh:
                    fh.write(body if isinstance(body, str) else json.dumps(body))
        tip = self.tip.get(name, self.view[name].get("baseRefOid"))
        if os.path.exists(self.j("gh.ref." + name)):
            os.remove(self.j("gh.ref." + name))
        if tip != "fail":
            with open(self.j("gh.ref." + name), "w") as fh:
                json.dump({"ref": "refs/heads/" + str(self.view[name].get("baseRefName")),
                           "object": {"sha": tip, "type": "commit"}}, fh)

    def ci(self, rollup, name="tg-read", head=None, raw=None, **fields):
        """Проверки GitHub (statusCheckRollup) и head в ответе gh pr view для latark/<name>; raw — сырой ответ;
        fields — другие поля (значение None убирает поле)."""
        v = self.view[name]
        v.update(statusCheckRollup=rollup, headRefOid=head or self.sha[name], **fields)
        for k in [k for k, x in fields.items() if x is None]:
            del v[k]
        self.write_view(name, raw)

    def wf(self, ref, text=None, fail=False):
        """Ответ gh api …/contents/.github/workflows?ref=<ref>: text — код 0 с этим текстом, fail — 502, иначе 404."""
        with open(self.j(("gh.wf.fail." if fail else "gh.wf.") + ref), "w") as fh:
            fh.write(text or "")

    def gh(self, files, count=None, head=None, raw=None, extra=None):
        """Д3 для latark/agent-kit: files — имена или словари REST (filename, status, previous_filename); raw — сырой
        вывод gh api; extra — ещё поля ответа gh pr view (тело PR, коммиты)."""
        old = self.view["agent-kit"]
        self.view["agent-kit"] = dict({"changedFiles": len(files) if count is None else count,
                                       "headRefOid": head or self.sha["agent-kit"], "baseRefOid": old.get("baseRefOid", BASE),
                                       "baseRefName": old.get("baseRefName", "main"),
                                       "statusCheckRollup": old["statusCheckRollup"]}, **(extra or {}))
        self.write_view("agent-kit")
        recs = [f if isinstance(f, dict) else {"filename": f, "status": "modified"} for f in files]
        with open(self.j("gh.files"), "w") as fh:
            fh.write(raw if raw is not None else "".join(json.dumps(x) + "\n" for x in recs))

    def seed(self, *recs):
        os.makedirs(os.path.dirname(self.records), mode=0o700, exist_ok=True)
        with open(self.records, "a") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")

    @property
    def approve_path(self):
        return self.j(".local/state/pantheon/owner-log/merge-approve.log")

    def approve(self, line, fresh=False):
        """Строка согласия владельца (metis-0285) — как её пишет тик; fresh — файл заново."""
        os.makedirs(os.path.dirname(self.approve_path), mode=0o700, exist_ok=True)
        with open(self.approve_path, "w" if fresh else "a") as fh:
            fh.write(line + "\n")

    def read(self):
        if not os.path.exists(self.records):
            return []
        with open(self.records) as fh:
            return [json.loads(x) for x in fh if x.strip()]

    def alert(self, line):
        with open(self.j("ai/pantheon/alerts.md"), "a") as fh:
            fh.write(line + "\n")

    def env(self, pdir):
        return {"HOME": self.root, "PATH": self.j("bin") + os.pathsep + os.environ["PATH"],
                "CLAUDE_PROJECT_DIR": self.j(pdir), "TMPDIR": "/nonexistent-tmp",
                "GUARD_TEST_DEADLINE": str(HOOK_DEADLINE), "GUARD_TEST_SUB_TIMEOUT": str(HOOK_SUB_TIMEOUT),
                "GUARD_TEST_CARRY_BUDGET": str(self.carry_budget)}

    def hook(self, event, pdir, mode=(), extra_env=None):
        return subprocess.run([sys.executable, "-I", CACHED, GUARD, *mode], input=json.dumps(event), capture_output=True,
                              text=True, env=dict(self.env(pdir), **(extra_env or {})), timeout=SUB_TIMEOUT)

    def pre(self, cmd, role="domain-coordinator", pdir="projects/tg-read", cwd=None, agent_id=None, session="s-coord",
            extra_env=None):
        """PreToolUse → (решение, причина); extra_env — окружение окна (PANTHEON_ROLE и т. п.)."""
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
                 "cwd": self.j(cwd or pdir), "session_id": session, "tool_use_id": "toolu_" + uuid.uuid4().hex,
                 "agent_type": role}
        if role is None:
            del event["agent_type"]  # главная сессия окна: agent_type в её событиях нет
        if agent_id:
            event["agent_id"] = agent_id
        return decision(self.hook(event, pdir, extra_env=extra_env))

    def pre_input(self, tool_input, role, agent_id=None, pdir="projects/tg-read"):
        """PreToolUse с полным tool_input (run_in_background и т. п.) → (решение, причина)."""
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": tool_input, "cwd": self.j(pdir),
                 "session_id": "s-coord", "tool_use_id": "toolu_" + uuid.uuid4().hex, "agent_type": role}
        if agent_id:
            event["agent_id"] = agent_id
        return decision(self.hook(event, pdir))

    def post(self, cmd, role, cwd="projects/tg-read", agent_id="x1", session="s-coord", name="PostToolUse", mode=(),
             background=False, response=NORMAL, transcript=None):
        tool_input = {"command": cmd}
        if background:
            tool_input["run_in_background"] = True
        event = {"hook_event_name": name, "tool_name": "Bash", "tool_input": tool_input, "cwd": self.j(cwd),
                 "session_id": session, "tool_use_id": "toolu_" + uuid.uuid4().hex, "agent_type": role}
        if transcript:
            event["transcript_path"] = transcript  # главной сессии, как его даёт Claude Code и в событиях субагента
        if agent_id:
            event["agent_id"] = agent_id
        if name == "PostToolUseFailure":
            event["error"] = "Exit code 1"
        if response is not MISSING and (name != "PostToolUseFailure" or response is not NORMAL):
            event["tool_response"] = dict(response) if isinstance(response, dict) else response
        return self.hook(event, cwd, mode)


def decision(r):
    """(решение, причина) по ответу хука; код 2 (сбой, metis-0094) Claude Code понимает как отказ с причиной из stderr."""
    if r.returncode == 2:
        return "deny", r.stderr
    if '"deny"' not in r.stdout:
        return "allow", ""
    return "deny", json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def rec(kind, repo, pr, sha, who="argus", agent_id="argus1", session="s-coord", checklist=MISSING, base="main"):
    """Запись журнала; у accept по умолчанию — полный перечень Б6, checklist=None — запись старого формата. base —
    base PR при записи вердикта (metis-0965), None — поля нет (запись до 0965)."""
    r = {"v": 1, "kind": kind, "repo": [repo], "pr": pr, "sha": sha,
         "by": {"agent_type": who, "agent_id": agent_id, "session_id": session}, "cwd": "/x",
         "time": "2026-10-15T20:00:00+0300", "tool_use_id": "t", "cmd": "pantheon review"}
    if kind in ("accept", "reject") and base is not None:
        r["base"] = base
    if checklist is MISSING and kind == "accept":
        checklist = dict(CHECKLIST)
    if checklist is not MISSING and checklist is not None:
        r["checklist"] = checklist
    return r


def merge_case(name, got, allow, why=""):
    """Решение по слиянию: allow — пропуск, иначе отказ с why в причине."""
    decision, reason = got
    if allow:
        check(name, decision == "allow", reason)
    else:
        check(name, decision == "deny" and why in reason, reason)


class _SlowSubprocess:
    """subprocess для merge_gate, загруженного в процесс теста (metis-0719): timeout у run не меньше HOOK_SUB_TIMEOUT,
    как у хука через загрузчик _cached_main. Без этого git в _git_bytes (timeout=3) под нагрузкой outside не успевал,
    и r4 видел отпечаток None вместо хеша. Остальное — настоящий subprocess."""

    def __getattr__(self, name):
        return getattr(subprocess, name)

    @staticmethod
    def run(*args, **kw):
        if kw.get("timeout") is not None:
            kw["timeout"] = max(kw["timeout"], HOOK_SUB_TIMEOUT)
        return subprocess.run(*args, **kw)


def _load_merge_gate(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(GUARD), "merge_gate.py"))
    mg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mg)
    mg.subprocess = _SlowSubprocess()  # только этот модуль: подпроцессы самого теста — с прежними сроками
    return mg


def _hook_out(h, cmd, pdir):
    """Сырой stdout хука на PreToolUse главной сессии координатора (для systemMessage при пропуске)."""
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": h.j(pdir),
             "session_id": "s-coord", "tool_use_id": "toolu_" + uuid.uuid4().hex, "agent_type": "domain-coordinator"}
    return h.hook(event, pdir)


def _saved(pr, kind="rollup"):
    """Сохранённый ответ GitHub по PR (шаг 0 metis-0633): rollup — gh pr view, runs — REST запусков Actions."""
    with open(os.path.join(FIXTURES, f"ci-{kind}-pr{pr}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _runs_on(saved, sha, pr):
    """Сохранённые ответы REST запусков с head_sha, заменённым на sha, и PR pr, заменённым на 7 (PR в тесте)."""
    head = saved["check_runs"]["check_runs"][0]["head_sha"]
    wr, cr = json.loads(json.dumps([saved["workflow_runs"], saved["check_runs"]]).replace(head, sha))
    for r in wr["workflow_runs"]:
        r["pull_requests"] = [{"number": 7} if p["number"] == pr else p for p in r["pull_requests"]]
    return wr, cr


def _notes_on(h, saved):
    """Аннотации и данные job из сохранённого ответа (metis-0655) — в файлы поддельного gh: gh.notes.<id>,
    gh.jobs.<id>."""
    for kind, key in (("notes", "annotations"), ("jobs", "jobs")):
        for i, body in saved.get(key, {}).items():
            with open(h.j(f"gh.{kind}.{i}"), "w") as fh:
                json.dump(body, fh)


FULL_TESTS_CMD = ("pantheon review test -- heavy python3.14 -I plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard "
                  "plugins/pantheon plugins/project-tools")


def full_rec(repo, sha, cmd=FULL_TESTS_CMD):
    """Запись tests с командой полного набора (metis-0655: на запасном пути засчитывается только она)."""
    return dict(rec("tests", repo, None, sha, ""), cmd=cmd)


def ts(shift=0):
    """Время строки согласия, как её пишет тик: ISO 8601 с поясом, сейчас + shift секунд."""
    import datetime
    return datetime.datetime.fromtimestamp(time.time() + shift).astimezone().isoformat(timespec="seconds")


# --- перенос «принять» после подтягивания main (metis-0415) -------------------------------------------------------
# Решение владельца 24.10 17:54 [metis-0384b]: «вернуть» привязано к PR (любой head) и снимается только более поздним
# «принять»; «принять» переносится, только если собственный дифф PR от merge-base совпал (git diff --raw по содержимому
# файлов с 25.10, без строки version в plugin.json); сбой git или неполная история — не переносится. Тесты на
# новом head — всегда свои.
# Таблица «блокер прошлых кругов → тест» — в отчёте задачи; имена блокеров стоят в названиях проверок.

PJ = "plugins/pantheon/.claude-plugin/plugin.json"
GJ = "plugins/guard/.claude-plugin/plugin.json"
CODE = "def f():\n    x = {}\n    return x\n\n\ndef g():\n    return 0\n"
README = "".join(f"r{i}\n" for i in range(1, 13))
G_PY = "".join(f"def g{i}():\n    return {i}\n\n\n" for i in range(6))


def _man(name, ver, **kw):
    return json.dumps(dict({"name": name, "version": ver}, **kw), indent=2) + "\n"


class Hist:
    """Коммиты на своих ветках репозитория p; в конце сборки — снова main (HEAD и дерево — как были)."""

    def __init__(self, p):
        self.p, self.s = p, {}

    def put(self, files, msg, amend=False, mode=None):
        for rel, text in files.items():
            f = os.path.join(self.p, rel)
            if text is None:
                os.remove(f)
                continue
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "wb" if isinstance(text, bytes) else "w") as fh:
                fh.write(text)
        if mode:
            os.chmod(os.path.join(self.p, mode), 0o755)
        git(self.p, "add", "-A")
        git(self.p, "commit", "-q", "--allow-empty", "-m", msg, *(["--amend"] if amend else []))
        return git(self.p, "rev-parse", "HEAD")

    def br(self, name, start):
        git(self.p, "checkout", "-q", "-B", name, start)

    def merge(self, other, extra=None):
        git(self.p, "merge", "-q", "--no-edit", "--no-ff", other)
        if extra:
            return self.put(extra, "правка внутри слияния", amend=True)
        return git(self.p, "rev-parse", "HEAD")


def kit_history(h):
    """История PR в projects/agent-kit (один раз на прогон). B — база; M1 — main после соседнего PR (MAIN.md — файл
    не из PR: отпечаток — по содержимому файлов PR, решение 25.10 23:05; новый файл, удалён gone.py, g.py переименован в h.py, version 0.11.85); M2 — ещё один PR в main. P — проверенный
    head PR (code.py и README вверху); N1 = P + подтянутый M1 + номер версии; N2 = N1 + подтянутый M2 + номер."""
    if getattr(h, "hist", None):
        return h.hist
    p = h.j("projects/agent-kit")
    H = Hist(p)
    s = H.s
    H.br("t-base", h.sha["agent-kit"])
    s["B"] = H.put({PJ: _man("pantheon", "0.11.84"), GJ: _man("guard", "0.5.17"), "README.md": README,
                    "code.py": CODE.format(1), "g.py": G_PY, "gone.py": "g = 1\n", "bin.dat": b"\x00\x01bin\x00",
                    ".claude-plugin/marketplace.json": "{}\n", "MAIN.md": README}, "B")
    H.br("t-main", s["B"])
    s["M1"] = H.put({PJ: _man("pantheon", "0.11.85"), "MAIN.md": README.replace("r12", "r12m"), "other.py": "y = 1\n",
                     "gone.py": None, "g.py": None, "h.py": G_PY}, "main: соседний PR и выпуск")
    s["M2"] = H.put({PJ: _man("pantheon", "0.11.86"), "other2.py": "z = 1\n"}, "main: ещё один PR")
    H.br("t-pr", s["B"])
    s["P"] = H.put({"code.py": CODE.format(2), "README.md": README.replace("r1\n", "r1p\n")}, "PR")
    s["Pv"] = H.put({PJ: _man("pantheon", "0.11.85"), GJ: _man("guard", "0.5.18")}, "выпуск без main")
    H.br("t-pr-a", s["P"])
    s["A1"] = H.merge(s["M1"])
    s["N1"] = H.put({PJ: _man("pantheon", "0.11.86"), GJ: _man("guard", "0.5.18")}, "выпуск после main")
    s["N2m"] = H.merge(s["M2"])
    s["N2"] = H.put({PJ: _man("pantheon", "0.11.87")}, "выпуск после второго main")
    # плохие head от N1: правка вне version
    for name, files, mode in (
            ("out", {"code.py": CODE.format(3)}, None),
            ("ws", {"code.py": CODE.format(2).replace("return x", "return x ")}, None),
            # отступ в строке, которую PR и так правит (у patch-id без --verbatim строки -/+ были бы те же)
            ("wsin", {"code.py": CODE.format(2).replace("    x = 2", "  x = 2")}, None),
            ("bin", {"bin.dat": b"\x00\x02bin\x00"}, None),
            ("field", {PJ: _man("pantheon", "0.11.86", description="другое")}, None),
            ("dup", {PJ: '{"name": "pantheon", "version": "0.11.86", "version": "0.11.86"}\n'}, None),
            ("numver", {PJ: _man("pantheon", 86)}, None),
            ("mjson", {".claude-plugin/marketplace.json": '{"x": 1}\n'}, None),
            ("mode", {}, "code.py"),
            ("newfile", {"empty.txt": ""}, None)):
        H.br("t-" + name, s["N1"])
        s[name] = H.put(files, name, mode=mode)
    H.br("t-evil", s["P"])
    s["evil"] = H.merge(s["M1"], extra={"code.py": CODE.format(9)})  # правка внутри коммита слияния (117-a7)
    H.br("t-moddel", s["P"])
    s["moddel"] = H.merge(s["M1"], extra={"gone.py": "g = 1\n"})  # вернул файл, который main удалил (117-b3)
    H.br("t-side0", s["B"])
    side = H.put({"evil.py": "e = 1\n"}, "побочная ветка не из main")
    H.br("t-side", s["N1"])
    s["side"] = H.merge(side)
    # обратное слияние: первый родитель — main (122-b9)
    H.br("t-rev", s["M1"])
    s["Arev"] = H.merge(s["P"])
    # «вернуть» → исправление → main (122-a11-1): R и A от одной merge-base
    H.br("t-fix", s["P"])
    s["R"] = H.put({"code.py": CODE.format(5)}, "правка, которую вернули")
    s["A"] = H.put({"code.py": CODE.format(7)}, "исправление")
    s["NA"] = H.merge(s["M1"])
    # откат правки после «вернуть» (122-a11-2)
    H.br("t-revert", s["N1"])
    s["Rx"] = H.put({"x.py": "bad\n"}, "правка, которую вернули")
    s["Nrev"] = H.put({"x.py": None, PJ: _man("pantheon", "0.11.87")}, "откат правки и выпуск")
    # amend и повтор слияния после reset (122-a10, 122-b10)
    H.br("t-amend", s["A1"])
    s["Ram"] = H.put({PJ: _man("pantheon", "0.11.86")}, "выпуск, который вернули")
    s["Nam"] = H.put({}, "выпуск (amend)", amend=True)
    H.br("t-redo", s["P"])
    H.merge(s["M1"])
    s["Nredo"] = H.put({PJ: _man("pantheon", "0.11.86"), GJ: _man("guard", "0.5.18")}, "выпуск заново")
    # длинная история (122-b-2): 35 пустых коммитов
    H.br("t-long", s["P"])
    for i in range(35):
        H.put({}, f"пустой коммит {i}")
    H.merge(s["M1"])
    s["Nlong"] = H.put({PJ: _man("pantheon", "0.11.86")}, "выпуск")
    # переименование в main (117-b3-2): Q правит g.py, M1 переносит g.py в h.py
    H.br("t-q", s["B"])
    s["Q"] = H.put({"g.py": G_PY.replace("return 3", "return 33")}, "PR правит g.py")
    s["QA"] = H.merge(s["M1"])
    s["QN"] = H.merge(s["M2"])
    git(p, "checkout", "-q", "--orphan", "t-orphan")
    s["orphan"] = H.put({}, "без общей истории")
    git(p, "checkout", "-q", "-f", "main")
    git(p, "clean", "-qfdx")
    h.hist = s
    return s


def kit_pr(h, head, base, core=False):
    """gh pr view для latark/agent-kit: PR на head, base PR — base, файлы без ядра (core — с ядром)."""
    h.gh(["README.md", "plugins/guard/hooks/merge_gate.py" if core else "code.py"], head=head)
    h.view["agent-kit"]["baseRefOid"] = base
    h.write_view("agent-kit")


def carry_file(h):
    return h.j(".local/state/pantheon/merge-gate/carry.jsonl")


def carry_lines(h):
    if not os.path.exists(carry_file(h)):
        return []
    with open(carry_file(h)) as fh:
        return [json.loads(x) for x in fh if x.strip()]


def opus(sha, agent_id="argus1", kind="accept", session="s-a", repo="latark/agent-kit", pr=7, **kw):
    return rec(kind, repo, pr, sha, agent_id=agent_id, session=session, **kw)


def plumb(p, parents, changes, msg, src=None):
    """Коммит без рабочего дерева (read-tree, update-index, commit-tree): changes — путь → None (удалить) или
    (режим, байты) — для 160000 вместо байтов sha gitlink. Дерево — от src или первого родителя."""
    idx = os.path.join(p, ".git", "plumb-index")
    env = dict(os.environ, GIT_INDEX_FILE=idx)

    def run(*a, inp=None):
        return subprocess.run(["git", "-C", p, "-c", "user.name=t", "-c", "user.email=t@example.com", *a], input=inp,
                              env=env, check=True, capture_output=True).stdout.decode().strip()
    run("read-tree", src or parents[0])
    for path, v in changes.items():
        if v is None:
            run("update-index", "--force-remove", path)
            continue
        mode, data = v
        sha = data if mode == "160000" else run("hash-object", "-w", "--stdin", inp=data)
        run("update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}")
    tree = run("write-tree")
    c = run("commit-tree", tree, *sum((["-p", x] for x in parents), []), "-m", msg)
    os.remove(idx)
    return c


class _Env:
    """Временное окружение процесса: kv — переменная → значение или None (убрать)."""

    def __init__(self, **kv):
        self.kv, self.old = kv, {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.old[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def __exit__(self, *a):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main(cases, cases_core=()):
    """Прогон случаев части: cases — список функций t_*(h), cases_core — те из них, где PR agent-kit#7 — ядро."""
    # корень подменённого HOME не должен лежать в /tmp: guard считает /tmp временной папкой, и на Linux (mkdtemp -> /tmp)
    # ~/.ssh, cwd без .git и $HOME с .git становились «внутри временных папок» — gh-out их пропускал. На macOS
    # mkdtemp даёт /var/folders/…, вне /tmp; на Linux берём /var/tmp (его нет в TEMP_ROOTS)
    base = None if not os.path.realpath(tempfile.gettempdir()).startswith(("/tmp", "/private/tmp")) else "/var/tmp"
    # в окне роли под песочницей git init в TMPDIR падает (код 128) — mkroot берёт папку, где он работает (metis-0729)
    tmp = os.path.realpath(mkroot("merge-gate-test-", first=base))
    try:  # HOME собирается раз — шаблон tmp/home; случай идёт в своём fork на своей копии (metis-0544, _par.py)
        h = Home(os.path.join(tmp, "home"))
        def one(case):  # копия шаблона: git и файлы — как после Home(), прошлые случаи их не меняли
            h.root, h.core = shutil.copytree(h.root, os.path.join(tmp, case.__name__), symlinks=True), case in cases_core
            h.reset()
            case(h)
        run_cases([(c.__name__, lambda c=c: one(c)) for c in cases if c.__name__ in (sys.argv[1:] or [c.__name__])],
                  results, lambda name, err: results.append(False))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if results and all(results) else 1


__all__ = [k for k in list(globals()) if not k.startswith("__")]   # всё, включая _помощники: части берут их через import *
