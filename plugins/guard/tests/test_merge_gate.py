#!/usr/bin/env python3
"""Запор слияния guard 0.5.4 (P1-4, Д2, Д3): журнал merge-gate пишет хук на PostToolUse, gh pr merge проходит только
с записями тестов и «принять» от argus на этот SHA (--match-head-commit), продукт — ещё talos и строка «откат»,
защиты — ещё Д3 (поддельный gh в PATH). Подменённый HOME во временной папке, всё убирается в конце.

Запуск: python3 -I plugins/guard/tests/test_merge_gate.py   (код 0 — все прошли)
На Python без tomllib (3.9) policy.toml не читается и слияние закрыто всем: проверки, которым нужна политика,
там проверяют именно этот отказ.
"""
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard.py")
HAVE_TOML = sys.version_info >= (3, 11)
OLD = "b" * 40
CORE = "ядро защит — только кнопка владельца (Д3)"
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))


def git(path, *args):
    return subprocess.run(["git", "-C", path, "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


NORMAL = {"stdout": "", "stderr": "", "interrupted": False, "isImage": False}  # ответ обычной команды
BG = dict(NORMAL, backgroundTaskId="bxyz")  # ответ фоновой: PostToolUse приходит при запуске (ревью argus PR #18)
MISSING = object()


class Home:
    def __init__(self, root):
        self.root = root
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
                                   "athena-broker": ["~/projects/broker"]}}, fh)
        with open(j(".claude/pantheon/policy.toml"), "w") as fh:
            fh.write('[coordinators]\nmetis-pantheon = ["~/projects/agent-kit"]\n'
                     '[merge_client]\nathena-broker = ["~/projects/broker"]\n'
                     '[merge_repos]\nmetis-pantheon = ["latark/agent-kit", "latark/tg-read"]\n'
                     'athena-broker = ["latark/broker"]\n')
        # поддельный gh: pr view отдаёт $HOME/gh.json, с $HOME/gh.fail — сбой; вызовы — в $HOME/gh.log
        with open(j("bin/gh"), "w") as fh:
            fh.write('#!/bin/sh\necho "$@" >> "$HOME/gh.log"\n[ -f "$HOME/gh.fail" ] && exit 1\n'
                     'cat "$HOME/gh.json"\n')
        os.chmod(j("bin/gh"), 0o755)

    def j(self, rel):
        return os.path.join(self.root, rel)

    @property
    def records(self):
        return self.j(".local/state/pantheon/merge-gate/records.jsonl")

    def reset(self):
        """Перед каждым случаем: пустой журнал, пустая сводка, gh отвечает PR без ядра на текущем SHA agent-kit."""
        shutil.rmtree(self.j(".local/state/pantheon/merge-gate"), ignore_errors=True)
        for f in ("gh.fail", "gh.log"):
            if os.path.exists(self.j(f)):
                os.remove(self.j(f))
        open(self.j("ai/pantheon/alerts.md"), "w").close()
        self.gh(["README.md", "plugins/guard/hooks/guard.py"])

    def gh(self, files, count=None, head=None):
        with open(self.j("gh.json"), "w") as fh:
            json.dump({"files": [{"path": f} for f in files], "changedFiles": len(files) if count is None else count,
                       "headRefOid": head or self.sha["agent-kit"]}, fh)

    def seed(self, *recs):
        os.makedirs(os.path.dirname(self.records), mode=0o700, exist_ok=True)
        with open(self.records, "a") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")

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
                "CLAUDE_PROJECT_DIR": self.j(pdir), "TMPDIR": "/nonexistent-tmp"}

    def hook(self, event, pdir, mode=()):
        return subprocess.run([sys.executable, "-I", GUARD, *mode], input=json.dumps(event), capture_output=True,
                              text=True, env=self.env(pdir), timeout=20)

    def pre(self, cmd, role="domain-coordinator", pdir="projects/tg-read", cwd=None, agent_id=None, session="s-coord"):
        """PreToolUse → (решение, причина)."""
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd},
                 "cwd": self.j(cwd or pdir), "session_id": session, "tool_use_id": "toolu_" + uuid.uuid4().hex,
                 "agent_type": role}
        if agent_id:
            event["agent_id"] = agent_id
        out = self.hook(event, pdir).stdout
        if '"deny"' not in out:
            return "allow", ""
        return "deny", json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]

    def pre_input(self, tool_input, role, agent_id=None, pdir="projects/tg-read"):
        """PreToolUse с полным tool_input (run_in_background и т. п.) → (решение, причина)."""
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": tool_input, "cwd": self.j(pdir),
                 "session_id": "s-coord", "tool_use_id": "toolu_" + uuid.uuid4().hex, "agent_type": role}
        if agent_id:
            event["agent_id"] = agent_id
        out = self.hook(event, pdir).stdout
        if '"deny"' not in out:
            return "allow", ""
        return "deny", json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]

    def post(self, cmd, role, cwd="projects/tg-read", agent_id="x1", session="s-coord", name="PostToolUse", mode=(),
             background=False, response=NORMAL):
        tool_input = {"command": cmd}
        if background:
            tool_input["run_in_background"] = True
        event = {"hook_event_name": name, "tool_name": "Bash", "tool_input": tool_input, "cwd": self.j(cwd),
                 "session_id": session, "tool_use_id": "toolu_" + uuid.uuid4().hex, "agent_type": role}
        if agent_id:
            event["agent_id"] = agent_id
        if name == "PostToolUseFailure":
            event["error"] = "Exit code 1"
        if response is not MISSING and (name != "PostToolUseFailure" or response is not NORMAL):
            event["tool_response"] = dict(response) if isinstance(response, dict) else response
        return self.hook(event, cwd, mode)


def rec(kind, repo, pr, sha, who="argus", agent_id="argus1", session="s-coord"):
    return {"v": 1, "kind": kind, "repo": [repo], "pr": pr, "sha": sha,
            "by": {"agent_type": who, "agent_id": agent_id, "session_id": session}, "cwd": "/x",
            "time": "2026-10-15T20:00:00+0300", "tool_use_id": "t", "cmd": "pantheon review"}


def merge_case(name, got, allow, why=""):
    """Решение по слиянию: на Python без tomllib — отказ «политика не прочиталась» для любого случая."""
    decision, reason = got
    if not HAVE_TOML:
        check(name + " (без tomllib — слияние закрыто)", decision == "deny" and "не прочиталась" in reason, reason)
    elif allow:
        check(name, decision == "allow", reason)
    else:
        check(name, decision == "deny" and why in reason, reason)


# --- случаи ------------------------------------------------------------------------------------------------------

def t_pass_internal(h):
    """Записи через хук (PostToolUse): тесты в чистом дереве и «принять» от argus — слияние проходит."""
    sha = h.sha["tg-read"]
    h.post("pantheon review test -- true", "dev-opus")
    h.post(f"pantheon review accept latark/tg-read 3 {sha}", "argus", agent_id="argus1")
    recs = h.read()
    check("PostToolUse пишет tests и accept", [r["kind"] for r in recs] == ["tests", "accept"]
          and recs[0]["sha"] == sha and recs[0]["repo"] == ["latark/tg-read"] and recs[0]["pr"] is None
          and recs[1]["by"] == {"agent_type": "argus", "agent_id": "argus1", "session_id": "s-coord"}, recs)
    d = os.path.dirname(h.records)
    check("журнал: папка 0700, файл 0600", stat.S_IMODE(os.stat(d).st_mode) == 0o700
          and stat.S_IMODE(os.stat(h.records).st_mode) == 0o600)
    merge_case("accept и tests на текущий SHA — проходит", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), True)
    merge_case("--match-head-commit=SHA — тоже проходит", h.pre(f"gh pr merge 3 --match-head-commit={sha}"), True)


def t_old_sha(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, OLD, who="dev-opus"), rec("tests", "latark/tg-read", None, sha, "dev-opus"),
           rec("accept", "latark/tg-read", 3, OLD))
    merge_case("accept на старый SHA при новом --match-head-commit — отказ",
               h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False, "нет «принять» от argus")


def t_no_tests(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, OLD, "dev-opus"), rec("accept", "latark/tg-read", 3, sha))
    merge_case("нет записи тестов на этот SHA — отказ", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False,
               "нет записи тестов")


def t_author_is_reviewer(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"), rec("accept", "latark/tg-read", 3, sha, agent_id="L1"))
    merge_case("автор = рецензент — отказ", h.pre(f"gh pr merge 3 --match-head-commit {sha}", role="hephaestus-pantheon",
                                                 agent_id="L1"), False, "рецензент и сливающий")
    merge_case("тот же лид, другой argus — проходит",
               h.pre(f"gh pr merge 3 --match-head-commit {sha}", role="hephaestus-pantheon", agent_id="L2"), True)


def t_argus_commit(h):
    for cmd in ("git commit -m x", "git -C . rebase main", "git cherry-pick abc", "git pull", "git commit-tree x"):
        d, why = h.pre(cmd, role="argus", agent_id="argus1")
        check(f"argus: {cmd} — отказ", d == "deny" and "argus не делает git" in why, why)
    d, why = h.pre("git log --oneline", role="argus", agent_id="argus1")
    check("argus: git log — можно", d == "allow", why)
    d, why = h.pre("git commit -m x", role="dev-opus", agent_id="d1")
    check("dev-opus: git commit — можно", d == "allow", why)


def t_admin_auto(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"), rec("accept", "latark/tg-read", 3, sha))
    merge_case("--admin — отказ", h.pre(f"gh pr merge 3 --admin --match-head-commit {sha}"), False, "без --admin")
    merge_case("--auto — отказ", h.pre(f"gh pr merge 3 --auto --match-head-commit {sha}"), False, "без --auto")
    merge_case("без номера PR — отказ", h.pre(f"gh pr merge --match-head-commit {sha}"), False, "один номер PR")
    merge_case("два номера PR — отказ", h.pre(f"gh pr merge 3 4 --match-head-commit {sha}"), False, "один номер PR")


def t_no_head(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"), rec("accept", "latark/tg-read", 3, sha))
    merge_case("без --match-head-commit — отказ", h.pre("gh pr merge 3"), False, "нужен ровно один --match-head-commit")
    merge_case("два --match-head-commit — отказ",
               h.pre(f"gh pr merge 3 --match-head-commit {sha} --match-head-commit {sha}"), False,
               "нужен ровно один --match-head-commit")
    merge_case("короткий SHA — отказ", h.pre(f"gh pr merge 3 --match-head-commit {sha[:12]}"), False,
               "нужен ровно один --match-head-commit")


def t_not_listed(h):
    sha = h.sha["notlisted"]
    h.seed(rec("tests", "latark/notlisted", None, sha, "dev-opus"), rec("accept", "latark/notlisted", 3, sha))
    merge_case("репозиторий не из merge_repos (внутреннее, без -R) — отказ",
               h.pre(f"gh pr merge 3 --match-head-commit {sha}", pdir="projects/notlisted"), False, "[merge_repos]")
    merge_case("-R не из merge_repos — отказ",
               h.pre(f"gh pr merge 3 -R latark/other --match-head-commit {sha}"), False, "[merge_repos]")


def t_core(h):
    sha = h.sha["agent-kit"]
    h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"), rec("accept", "latark/agent-kit", 7, sha))
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    merge_case("защиты: PR не задевает ядро — проходит", h.pre(cmd, pdir="projects/agent-kit"), True)
    if HAVE_TOML:
        log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
        check("gh pr view зовётся с -R и номером", "pr view 7 -R latark/agent-kit --json files,changedFiles,headRefOid"
              in log, log)
    h.gh(["README.md", "plugins/guard/hooks/merge_gate.py"])
    merge_case("защиты: PR задевает ядро (merge_gate.py) — отказ", h.pre(cmd, pdir="projects/agent-kit"), False, CORE + ": PR задевает")
    h.gh(["plugins/guard/managed-settings.json"])
    merge_case("защиты: PR задевает managed-settings.json — отказ", h.pre(cmd, pdir="projects/agent-kit"), False,
               CORE + ": PR задевает")
    h.gh(["README.md"], count=150)
    merge_case("защиты: список файлов неполон — отказ", h.pre(cmd, pdir="projects/agent-kit"), False, "неполон")
    h.gh(["README.md"], head=OLD)
    merge_case("защиты: PR на другом коммите — отказ", h.pre(cmd, pdir="projects/agent-kit"), False,
               "на другом коммите")
    h.gh(["README.md"])
    open(h.j("gh.fail"), "w").close()
    merge_case("защиты: gh не ответил — отказ", h.pre(cmd, pdir="projects/agent-kit"), False, "не ответил")
    os.remove(h.j("gh.fail"))
    merge_case("защиты: сливает не Метида — отказ", h.pre(cmd, pdir="projects/agent-kit", cwd="projects/agent-kit",
                                                         role="hephaestus-broker", agent_id="L9"), False, "")


def t_verdict_role(h):
    sha = h.sha["tg-read"]
    for role in ("dev-opus", "hephaestus-pantheon", "talos", ""):
        h.post(f"pantheon review accept latark/tg-read 3 {sha}", role)
    h.post(f"pantheon review talos latark/tg-read 3 {sha}", "argus")
    check("вердикт пишет не argus (и talos не talos) — записи нет", h.read() == [], h.read())
    d, why = h.pre(f"pantheon review accept latark/tg-read 3 {sha}", role="dev-opus", agent_id="d1")
    check("PreToolUse: accept не от argus — сразу отказ", d == "deny" and "только argus" in why, why)
    d, why = h.pre(f"pantheon review talos latark/tg-read 3 {sha}", role="argus", agent_id="a1")
    check("PreToolUse: talos не от talos — сразу отказ", d == "deny" and "только talos" in why, why)
    d, why = h.pre(f"pantheon review accept latark/tg-read 3 {sha[:20]}", role="argus", agent_id="a1")
    check("PreToolUse: плохой SHA у argus — отказ", d == "deny" and "формате" in why, why)
    d, why = h.pre(f"pantheon review accept latark/tg-read 3 {sha}", role="argus", agent_id="a1")
    check("PreToolUse: accept от argus — можно", d == "allow", why)
    h.post(f"pantheon review accept latark/tg-read 3 {sha[:39]}", "argus")
    h.post(f"pantheon review accept latark 3 {sha}", "argus")
    check("плохие аргументы accept — записи нет", h.read() == [], h.read())


def t_reject_after_accept(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"), rec("accept", "latark/tg-read", 3, sha),
           rec("reject", "latark/tg-read", 3, sha, agent_id="argus2"))
    merge_case("reject после accept — отказ", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False, "«вернуть» (reject)")
    h.seed(rec("accept", "latark/tg-read", 3, sha, agent_id="argus3"))
    merge_case("accept после reject — проходит", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), True)


def t_product(h):
    sha = h.sha["broker"]
    cmd = f"gh pr merge 5 --match-head-commit {sha}"
    h.seed(rec("tests", "latark/broker", None, sha, "dev-opus"), rec("accept", "latark/broker", 5, sha))
    h.alert("2026-10-15 20:00 · athena-broker · latark/broker#5 ушло: налоги; откат: git revert abc")
    merge_case("продукт без talos — отказ", h.pre(cmd, pdir="projects/broker"), False, "нет проверки talos")
    h.seed(rec("talos", "latark/broker", 5, sha, who="talos", agent_id="t1"))
    open(h.j("ai/pantheon/alerts.md"), "w").close()
    h.alert("2026-10-15 20:00 · athena-broker · latark/broker#5 ушло: налоги")
    h.alert("2026-10-15 20:00 · athena-broker · latark/broker#50 ушло; откат: git revert abc")
    h.alert("latark/broker#5 ушло; откат: без даты")
    merge_case("продукт без строки «откат» в alerts.md — отказ", h.pre(cmd, pdir="projects/broker"), False,
               "нет строки «что ушло»")
    h.alert("2026-10-15 20:01 · athena-broker · latark/broker#5 ушло: налоги; откат: git revert abc")
    merge_case("продукт с talos и строкой alerts — проходит", h.pre(cmd, pdir="projects/broker"), True)


def t_not_simple(h):
    sha = h.sha["tg-read"]
    for cmd in (f"pantheon review accept latark/tg-read 3 {sha} ; true",
                f"pantheon review accept latark/tg-read 3 {sha} && true",
                f"pantheon review accept latark/tg-read 3 {sha} | cat",
                f"pantheon review accept latark/tg-read 3 $(echo {sha})",
                f"pantheon review accept latark/tg-read 3 {sha} > /dev/null",
                f"FOO=1 pantheon review accept latark/tg-read 3 {sha}",
                f"echo pantheon review accept latark/tg-read 3 {sha}"):
        h.post(cmd, "argus")
    h.post("pantheon review test -- true; true", "dev-opus")
    check("PostToolUse с непростой командой (… ; true и др.) — записи нет", h.read() == [], h.read())
    h.post(f"/usr/local/bin/pantheon review accept latark/tg-read 3 {sha}", "argus")
    check("путь с basename pantheon — запись есть", [r["kind"] for r in h.read()] == ["accept"], h.read())


def t_failure(h):
    sha = h.sha["tg-read"]
    # с ответом словарём, как у успешной: отсекает имя события, а не отсутствие tool_response
    h.post("pantheon review test -- true", "dev-opus", name="PostToolUseFailure", response=dict(NORMAL))
    h.post(f"pantheon review accept latark/tg-read 3 {sha}", "argus", name="PostToolUseFailure", response=dict(NORMAL))
    check("PostToolUseFailure — записи нет", h.read() == [], h.read())
    for mode in (["--strict"], ["--managed"]):
        h.post(f"pantheon review accept latark/tg-read 3 {sha}", "argus", mode=mode)
    check("PostToolUse в режимах --strict и --managed — записи нет", h.read() == [], h.read())


def t_dirty(h):
    p = h.j("projects/tg-read")
    with open(os.path.join(p, "x.txt"), "w") as fh:
        fh.write("x")
    h.post("pantheon review test -- true", "dev-opus")
    os.remove(os.path.join(p, "x.txt"))
    check("tests в грязном дереве — записи нет", h.read() == [], h.read())


MANAGED_PROBE = r"""
import importlib.util, io, json, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
g.MANAGED_FILE, g.MARKET_GUARD = sys.argv[2], sys.argv[1]
print("active", g.managed_guard_active())
sys.stdin = io.StringIO(sys.argv[3])
g.main()
"""


def t_managed(h):
    sha = h.sha["tg-read"]
    mf = h.j("managed.json")
    with open(mf, "w") as fh:
        json.dump({"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 guard.py --managed"}]}]}},
                  fh)
    event = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "agent_type": "argus", "agent_id": "a1",
             "session_id": "s-coord", "tool_use_id": "t1", "cwd": h.j("projects/tg-read"),
             "tool_input": {"command": f"pantheon review accept latark/tg-read 3 {sha}"}, "tool_response": NORMAL}
    r = subprocess.run([sys.executable, "-I", "-c", MANAGED_PROBE, GUARD, mf, json.dumps(event)], capture_output=True,
                       text=True, env=h.env("projects/tg-read"), timeout=20)
    check("при активных управляемых настройках PostToolUse пишет",
          "active True" in r.stdout and [x["kind"] for x in h.read()] == ["accept"], r.stdout + r.stderr)


def t_broken_journal(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"))
    with open(h.records, "a") as fh:
        fh.write("битая строка\n" + json.dumps({"v": 2, "kind": "accept"}) + "\n")
    h.seed(rec("accept", "latark/tg-read", 3, sha))
    merge_case("битые строки журнала пропускаются", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), True)
    shutil.rmtree(os.path.dirname(h.records))
    os.makedirs(h.j("elsewhere"))
    os.symlink(h.j("elsewhere"), os.path.dirname(h.records))
    h.post("pantheon review test -- true", "dev-opus")
    check("папка журнала — симлинк: хук не пишет", os.listdir(h.j("elsewhere")) == [])
    merge_case("папка журнала — симлинк: слияние закрыто", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False,
               "журнал проверок")
    os.remove(os.path.dirname(h.records))


def t_bg_flag(h):
    """Фон по run_in_background: PostToolUse пришёл при запуске, итога тестов ещё нет — ни одной записи."""
    sha = h.sha["tg-read"]
    h.post("pantheon review test -- true", "dev-opus", background=True, response=BG)
    h.post(f"pantheon review accept latark/tg-read 3 {sha}", "argus", background=True, response=BG)
    h.post(f"pantheon review talos latark/tg-read 3 {sha}", "talos", background=True, response=NORMAL)
    check("run_in_background — записи нет (tests, accept, talos)", h.read() == [], h.read())


def t_bg_task_id(h):
    """Уведённая в фон (Ctrl+B): флага во входе нет, но в ответе backgroundTaskId — записи нет."""
    sha = h.sha["tg-read"]
    h.post("pantheon review test -- true", "dev-opus", response=BG)
    h.post(f"pantheon review reject latark/tg-read 3 {sha}", "argus", response=BG)
    check("backgroundTaskId в tool_response — записи нет", h.read() == [], h.read())


def t_bad_response(h):
    sha = h.sha["tg-read"]
    for resp in ("ok", None, ["x"], MISSING):
        h.post("pantheon review test -- true", "dev-opus", response=resp)
        h.post(f"pantheon review accept latark/tg-read 3 {sha}", "argus", response=resp)
    check("tool_response не словарь или его нет — записи нет", h.read() == [], h.read())


def t_fg_records(h):
    sha = h.sha["tg-read"]
    h.post("pantheon review test -- true", "dev-opus", response=NORMAL)
    h.post(f"pantheon review accept latark/tg-read 3 {sha}", "argus", response=NORMAL)
    check("обычный запуск (не фон, ответ словарём) — записи tests и accept есть",
          [r["kind"] for r in h.read()] == ["tests", "accept"], h.read())


def t_pre_background(h):
    sha = h.sha["tg-read"]
    ev = {"command": "pantheon review test -- true", "run_in_background": True}
    d, why = h.pre_input(ev, role="dev-opus", agent_id="d1")
    check("PreToolUse: review test в фоне — отказ, текст «без фона»", d == "deny" and "без фона" in why, why)
    d, why = h.pre_input({"command": f"pantheon review accept latark/tg-read 3 {sha}", "run_in_background": True},
                         role="argus", agent_id="a1")
    check("PreToolUse: review accept в фоне — отказ", d == "deny" and "без фона" in why, why)
    d, why = h.pre_input({"command": "pantheon review test -- true", "run_in_background": False}, role="dev-opus",
                         agent_id="d1")
    check("PreToolUse: review test без фона — можно", d == "allow", why)
    d, why = h.pre_input({"command": "pantheon review status", "run_in_background": True}, role="dev-opus",
                         agent_id="d1")
    check("PreToolUse: review status в фоне — можно (записи не делает)", d == "allow", why)


def t_pre_not_simple(h):
    sha = h.sha["tg-read"]
    for cmd in ("pantheon review test -- pytest 2>&1 | tail -5", "pantheon review test -- true; true",
                "cd x && pantheon review test -- true", "pantheon review test -- true > out.txt",
                "pantheon review test -- echo $(id)", "pantheon review test -- echo `id`"):
        d, why = h.pre(cmd, role="dev-opus", agent_id="d1")
        check(f"PreToolUse: непростая `{cmd}` — отказ, код не от тестов", d == "deny" and "код выхода" in why, why)
    d, why = h.pre(f"pantheon review accept latark/tg-read 3 {sha} | cat", role="argus", agent_id="a1")
    check("PreToolUse: accept с | — отказ", d == "deny" and "код выхода" in why, why)
    d, why = h.pre("pantheon review status | head", role="dev-opus", agent_id="d1")
    check("PreToolUse: status с | — можно (записи не делает)", d == "allow", why)


CASES = [t_pass_internal, t_old_sha, t_no_tests, t_author_is_reviewer, t_argus_commit, t_admin_auto, t_no_head,
         t_not_listed, t_core, t_verdict_role, t_reject_after_accept, t_product, t_not_simple, t_failure, t_dirty,
         t_managed, t_broken_journal, t_bg_flag, t_bg_task_id, t_bad_response, t_fg_records, t_pre_background,
         t_pre_not_simple]


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="merge-gate-test-"))
    try:
        h = Home(tmp)
        only = set(sys.argv[1:])
        for case in CASES:
            if only and case.__name__ not in only:
                continue
            h.reset()
            case(h)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
