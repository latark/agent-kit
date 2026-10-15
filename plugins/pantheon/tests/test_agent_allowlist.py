#!/usr/bin/env python3
"""Список субагентов главной сессии окна штаба и координатора (metis-0062, P0-6 плана автономности).

Запуск: python3 -I plugins/pantheon/tests/test_agent_allowlist.py  (код выхода 0 — все прошли)
Проверяет на временных папках (HOME, PANTHEON_*, PANTHEON_CLAUDE_TMP — подменены, настоящие не трогаются):
- `pantheon domains build`: в окнах hq и направлений — хук `ctx.py agents <список>` (matcher Agent|Task|Skill) с
  точным списком и правила deny Agent(<тип>) — жёсткие границы окна; запись guard и правила Read штаба на месте;
  мастерская без хука;
- ctx.py agents: главная сессия зовёт только типы из списка (general-purpose и пустой тип — отказ), вызов субагента
  (agent_id в событии) не проверяется, мусор и пустой список — отказ; навык с context: fork — по типу его agent:.
"""
import atexit
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(PLUGIN, "lib", "pantheon.py")
CTX = os.path.join(PLUGIN, "hooks", "ctx.py")
ROOT = os.path.realpath(tempfile.mkdtemp(prefix="agent-allowlist-test-"))
atexit.register(shutil.rmtree, ROOT, True)

REGISTRY = """
[[direction]]
name = "athena-broker"
folders = ["~/projects/br"]
leads = ["hephaestus", "apollo"]

[[direction]]
name = "themis-sources"
folders = ["~/projects/src"]
leads = ["hephaestus"]

[[direction]]
name = "mnemo-brain"
folders = ["~/projects/kn"]
leads = []
"""
MAIN = ["hq", "domain-coordinator", "workshop"]


def lib_python():
    """pantheon.py — Python 3.11+ (tomllib); хук ctx.py — тем, чем запущен тест (на системном 3.9 — как в окнах)."""
    if sys.version_info >= (3, 11):
        return sys.executable
    for v in ("3.14", "3.13", "3.12", "3.11"):
        p = shutil.which("python" + v)
        if p:
            return p
    sys.exit("нет Python 3.11+ для pantheon.py")
COORD = ["argus", "talos", "prometheus", "Explore"]


def setup(tmp):
    home, state = os.path.join(tmp, "pantheon"), os.path.join(tmp, "state")
    os.makedirs(home)
    open(os.path.join(home, "directions.toml"), "w").write(REGISTRY)
    for p in ("br", "src", "kn"):
        os.makedirs(os.path.join(tmp, "projects", p))
    os.makedirs(os.path.join(tmp, ".claude", "pantheon"))
    open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w").write("")
    tasks = os.path.join(tmp, "ctmp", f"claude-{os.getuid()}")
    os.makedirs(tasks)
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_CLAUDE_TMP": tasks, "PANTHEON_NO_NOTIFY": "1"}
    return home, state, env


def agents_hook(data):
    """(matcher, список из команды) хука agents окна; None — хука нет."""
    for e in (data.get("hooks") or {}).get("PreToolUse") or []:
        for h in e.get("hooks") or []:
            argv = shlex.split(h.get("command", ""))
            if len(argv) >= 4 and argv[1].endswith("ctx.py") and argv[2] == "agents":
                return e.get("matcher"), argv[3].split(","), h
    return None


def agent_rules(data):
    return [x[len("Agent("):-1] for x in (data.get("permissions") or {}).get("deny") or [] if x.startswith("Agent(")]


def has_guard(data):
    return any("guard.py" in h.get("command", "") and "Read" in e.get("matcher", "")
               for e in (data.get("hooks") or {}).get("PreToolUse") or [] for h in e.get("hooks") or [])


def run_ctx(env, allowed, event):
    stdin = event if isinstance(event, str) else json.dumps(event)
    r = subprocess.run([sys.executable, "-I", CTX, "agents"] + ([allowed] if allowed is not None else []),
                       input=stdin, env=env, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return "error:" + r.stderr
    if not r.stdout.strip():
        return "allow"
    out = json.loads(r.stdout)["hookSpecificOutput"]
    return out["permissionDecision"] + ":" + out["permissionDecisionReason"]


def main():
    results = []

    def check(name, cond):
        cond = bool(cond)
        results.append(cond)
        print(("ok  " if cond else "FAIL") + " " + name)

    tmp = os.path.join(ROOT, "a")
    os.makedirs(tmp)
    home, state, env = setup(tmp)
    r = subprocess.run([lib_python(), "-I", LIB, "domains", "build"], env=env, capture_output=True, text=True,
                       timeout=120)
    check("сборка прошла", r.returncode == 0)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        return 1
    win = lambda n: json.load(open(os.path.join(state, "settings", n + ".json")))  # noqa: E731
    hq, ab, ts, mb, ws = (win(n) for n in ("hq", "athena-broker", "themis-sources", "mnemo-brain", "workshop"))

    # --- окна ---------------------------------------------------------------------------------------------------------
    want = {
        "hq": (hq, ["prometheus", "clio", "chiron", "Explore"],
               ["hephaestus-broker", "apollo-broker", "hephaestus-sources"] + MAIN),
        "athena-broker": (ab, ["hephaestus-broker", "apollo-broker"] + COORD, ["chiron"] + MAIN + ["hephaestus-sources"]),
        "themis-sources": (ts, ["hephaestus-sources"] + COORD,
                           ["chiron"] + MAIN + ["hephaestus-broker", "apollo-broker"]),
        "mnemo-brain": (mb, COORD + ["clio"],
                        ["chiron"] + MAIN + ["hephaestus-broker", "apollo-broker", "hephaestus-sources"]),
    }
    for name, (data, allowed, deny) in want.items():
        got = agents_hook(data)
        check(f"{name}: хук agents (Agent|Task|Skill, отказ при сбое) с точным списком {allowed}",
              got and got[0] == "Agent|Task|Skill" and got[1] == allowed and got[2].get("onFailure") == "block")
        check(f"{name}: deny Agent(…) — точно {deny}", agent_rules(data) == deny)
        check(f"{name}: запись guard в PreToolUse на месте", has_guard(data))
    check("mnemo-brain зовёт clio, другие координаторы — нет",
          "clio" in agents_hook(mb)[1] and "clio" not in agents_hook(ab)[1] and "clio" not in agents_hook(ts)[1])
    check("themis-sources (в реестре только hephaestus): apollo-* в списке нет",
          not any(x.startswith("apollo-") for x in agents_hook(ts)[1]))
    check("chiron закрыт координаторам и открыт штабу",
          all("chiron" in agent_rules(d) for d in (ab, ts, mb)) and "chiron" not in agent_rules(hq)
          and "chiron" in agents_hook(hq)[1])
    check("чужие лиды — в deny у каждого координатора",
          "hephaestus-sources" in agent_rules(ab) and {"hephaestus-broker", "apollo-broker"} <= set(agent_rules(ts)))
    reads = [x for x in hq["permissions"]["deny"] if not x.startswith("Agent(")]
    check("hq: правила Read на месте (агентские правила — дописаны, не вместо)",
          reads and all(x.startswith("Read(") for x in reads))
    check("мастерская: без хука agents и без правил Agent(…) (вне P0-6)",
          agents_hook(ws) is None and not agent_rules(ws) and has_guard(ws))
    alerts = open(os.path.join(home, "alerts.md")).read() if os.path.exists(os.path.join(home, "alerts.md")) else ""
    check("нет ctx.py в ~/.claude/plugins — тревога (окна не позовут никого)", "ctx.py" in alerts)

    # --- ctx.py agents --------------------------------------------------------------------------------------------------
    cenv = dict(env)
    lst = ",".join(want["athena-broker"][1])
    agent = lambda **ti: {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Agent",  # noqa: E731
                          "cwd": os.path.join(tmp, "projects", "br"), "tool_input": dict(ti, prompt="x")}
    gp = agent(subagent_type="general-purpose")
    res = run_ctx(cenv, lst, gp)
    check("general-purpose из главной сессии — отказ с причиной по-русски и списком", res.startswith("deny:")
          and "general-purpose" in res and "prometheus" in res and "P0-6" in res)
    check("без subagent_type (это general-purpose) — отказ", run_ctx(cenv, lst, agent()).startswith("deny:"))
    check("пустой subagent_type — отказ", run_ctx(cenv, lst, agent(subagent_type="")).startswith("deny:"))
    check("свой лид — пропуск", run_ctx(cenv, lst, agent(subagent_type="hephaestus-broker")) == "allow")
    check("Explore — пропуск; explore (другой регистр) — отказ",
          run_ctx(cenv, lst, agent(subagent_type="Explore")) == "allow"
          and run_ctx(cenv, lst, agent(subagent_type="explore")).startswith("deny:"))
    check("tool_name Task — та же проверка", run_ctx(cenv, lst, dict(gp, tool_name="Task")).startswith("deny:"))
    check("general-purpose с agent_id (зовёт субагент окна) — пропуск",
          run_ctx(cenv, lst, dict(gp, agent_id="a1", agent_type="hephaestus-broker")) == "allow")
    check("тип не строка — отказ", run_ctx(cenv, lst, agent(subagent_type=["argus"])).startswith("deny:"))
    check("tool_input не объект — отказ", run_ctx(cenv, lst, dict(gp, tool_input="argus")).startswith("deny:"))
    check("мусор на stdin — отказ", run_ctx(cenv, lst, "{не json").startswith("deny:"))
    check("событие не объект — отказ", run_ctx(cenv, lst, "[1, 2]").startswith("deny:"))
    check("пустой список — отказ всем",
          run_ctx(cenv, "", agent(subagent_type="argus")).startswith("deny:")
          and run_ctx(cenv, None, agent(subagent_type="argus")).startswith("deny:"))

    # --- навыки с context: fork -----------------------------------------------------------------------------------------
    def skill_file(p, head):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(f"---\nname: x\ndescription: d\n{head}---\n\n# Навык\n\ncontext: fork\n")

    sk = lambda name, **kw: dict({"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Skill",  # noqa: E731
                                  "cwd": os.path.join(tmp, "projects", "br"),
                                  "tool_input": {"skill": name, "args": "x"}}, **kw)
    aud = os.path.join(tmp, ".claude", "skills", "aud", "SKILL.md")
    skill_file(aud, "context: fork\nagent: general-purpose\n")
    res = run_ctx(cenv, lst, sk("aud"))
    check("навык с context: fork и agent: general-purpose — отказ координатору",
          res.startswith("deny:") and "навык aud" in res and "general-purpose" in res)
    check("тот же навык как /aud — отказ", run_ctx(cenv, lst, sk("/aud")).startswith("deny:"))
    check("тот же навык из субагента (agent_id) — пропуск", run_ctx(cenv, lst, sk("aud", agent_id="a1")) == "allow")
    skill_file(aud, "context: 'fork'\nagent: \"Explore\"\n")
    check("навык с fork и agent: Explore — пропуск", run_ctx(cenv, lst, sk("aud")) == "allow")
    skill_file(aud, "context: fork\n")
    check("навык с fork без agent: — это general-purpose, отказ", run_ctx(cenv, lst, sk("aud")).startswith("deny:"))
    skill_file(os.path.join(tmp, ".claude", "skills", "plain", "SKILL.md"), "")
    check("обычный навык без fork — пропуск (и строка context: fork в тексте, не в шапке, не в счёт)",
          run_ctx(cenv, lst, sk("plain")) == "allow")
    check("навыка нет — пропуск", run_ctx(cenv, lst, sk("nope")) == "allow")
    check("имя не по образцу — пропуск (не навык)", run_ctx(cenv, lst, sk("../aud")) == "allow")
    skill_file(os.path.join(tmp, "projects", "br", ".claude", "skills", "proj", "SKILL.md"),
               "context: fork\nagent: claude\n")
    check("навык проекта (папка события) с fork — отказ", run_ctx(cenv, lst, sk("proj")).startswith("deny:"))
    skill_file(os.path.join(tmp, ".claude", "plugins", "cache", "mk", "plug", "1.0", "skills", "forky", "SKILL.md"),
               "agent: general-purpose\ncontext: fork\n")
    check("навык плагина plug:forky с fork — отказ", run_ctx(cenv, lst, sk("plug:forky")).startswith("deny:"))
    fifo = os.path.join(tmp, ".claude", "skills", "fifo", "SKILL.md")
    os.makedirs(os.path.dirname(fifo))
    os.mkfifo(fifo)
    check("SKILL.md — FIFO: не виснет, пропуск", run_ctx(cenv, lst, sk("fifo")) == "allow")

    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
