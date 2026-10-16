#!/usr/bin/env python3
"""Список субагентов главной сессии окна штаба и координатора (metis-0062, P0-6 плана автономности).

Запуск: python3 -I plugins/pantheon/tests/test_agent_allowlist.py  (код выхода 0 — все прошли)
Проверяет на временных папках (HOME, PANTHEON_*, PANTHEON_CLAUDE_TMP — подменены, настоящие не трогаются):
- `pantheon domains build`: в окнах hq и направлений — хук `python3 <hooks/agents.py> <список>` (matcher
  Agent|Task|Skill) с точным списком и правила deny Agent(<тип>) — жёсткие границы окна; запись guard и правила Read
  штаба на месте; мастерская без хука; ctx.py в хуке не участвует; нет agents.py — команда окна выходит с кодом 2;
- agents.py: главная сессия зовёт только типы из списка (general-purpose и пустой тип — отказ JSON-ом), вызов
  субагента (agent_id в событии) не проверяется; любой сбой — мусор, пустой список, исключение — код 2 (блок);
- навыки с context: fork — по типу их agent:, все кандидаты: личный и проектный с одним именем, имя из поля name:,
  корень проекта при папке события ниже, CLAUDE_PROJECT_DIR, вложенное <путь>:<имя>, навык плагина (случаи ревью argus).
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
AGENTS = os.path.join(PLUGIN, "hooks", "agents.py")
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
COORD = ["argus", "talos", "prometheus", "Explore", "dev-haiku", "dev-sonnet", "dev-opus"]


def lib_python():
    """pantheon.py — Python 3.11+ (tomllib); хук agents.py — тем, чем запущен тест (на системном 3.9 — как в окнах)."""
    if sys.version_info >= (3, 11):
        return sys.executable
    for v in ("3.14", "3.13", "3.12", "3.11"):
        p = shutil.which("python" + v)
        if p:
            return p
    sys.exit("нет Python 3.11+ для pantheon.py")


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
    """(matcher, список из команды, запись хука) хука agents.py окна; None — хука нет."""
    for e in (data.get("hooks") or {}).get("PreToolUse") or []:
        for h in e.get("hooks") or []:
            argv = shlex.split(h.get("command", ""))
            if len(argv) == 3 and argv[0] == "python3" and argv[1].endswith(os.path.join("hooks", "agents.py")):
                return e.get("matcher"), argv[2].split(","), h
    return None


def agent_entries(data):
    """Записи PreToolUse с Agent в matcher, кроме строгого guard: он тоже ловит Agent|Task|Skill (guard 0.5.5)."""
    return [e for e in (data.get("hooks") or {}).get("PreToolUse") or [] if "Agent" in e.get("matcher", "")
            and not any("guard.py" in h.get("command", "") for h in e.get("hooks") or [])]


def agent_rules(data):
    return [x[len("Agent("):-1] for x in (data.get("permissions") or {}).get("deny") or [] if x.startswith("Agent(")]


def has_guard(data):
    return any("guard.py" in h.get("command", "") and "Read" in e.get("matcher", "")
               for e in (data.get("hooks") or {}).get("PreToolUse") or [] for h in e.get("hooks") or [])


def decision(r):
    """Итог хука: block:<stderr> (код 2), error:… (другой ненулевой код — Claude Code пропустил бы вызов), allow,
    deny:<причина>."""
    if r.returncode == 2:
        return "block:" + r.stderr
    if r.returncode != 0:
        return "error:%d:%s" % (r.returncode, r.stderr)
    if not r.stdout.strip():
        return "allow"
    out = json.loads(r.stdout)["hookSpecificOutput"]
    return out["permissionDecision"] + ":" + out["permissionDecisionReason"]


def run_hook(env, allowed, event, script=AGENTS):
    stdin = event if isinstance(event, str) else json.dumps(event)
    r = subprocess.run([sys.executable, "-I", script] + ([allowed] if allowed is not None else []),
                       input=stdin, env=env, capture_output=True, text=True, timeout=30)
    return decision(r)


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
        "hq": (hq, ["prometheus", "clio", "chiron", "momus", "Explore"],
               ["hephaestus-broker", "apollo-broker", "hephaestus-sources"] + MAIN),
        "athena-broker": (ab, ["hephaestus-broker", "apollo-broker"] + COORD, ["chiron"] + MAIN + ["hephaestus-sources"]),
        "themis-sources": (ts, ["hephaestus-sources"] + COORD,
                           ["chiron"] + MAIN + ["hephaestus-broker", "apollo-broker"]),
        "mnemo-brain": (mb, COORD + ["clio"],
                        ["chiron"] + MAIN + ["hephaestus-broker", "apollo-broker", "hephaestus-sources"]),
    }
    for name, (data, allowed, deny) in want.items():
        got = agents_hook(data)
        check(f"{name}: хук agents.py (Agent|Task|Skill, onFailure block) с точным списком {allowed}",
              got and got[0] == "Agent|Task|Skill" and got[1] == allowed and got[2].get("onFailure") == "block")
        check(f"{name}: deny Agent(…) — точно {deny}", agent_rules(data) == deny)
        check(f"{name}: запись guard в PreToolUse на месте", has_guard(data))
        check(f"{name}: ctx.py в хуке субагентов не участвует",
              len(agent_entries(data)) == 1 and "ctx.py" not in json.dumps(agent_entries(data)))
    check("mnemo-brain зовёт clio, другие координаторы — нет",
          "clio" in agents_hook(mb)[1] and "clio" not in agents_hook(ab)[1] and "clio" not in agents_hook(ts)[1])
    check("themis-sources (в реестре только hephaestus): apollo-* в списке нет",
          not any(x.startswith("apollo-") for x in agents_hook(ts)[1]))
    check("chiron закрыт координаторам и открыт штабу",
          all("chiron" in agent_rules(d) for d in (ab, ts, mb)) and "chiron" not in agent_rules(hq)
          and "chiron" in agents_hook(hq)[1])
    check("momus (ревизор навыка audit, metis-0095) — у штаба есть, у координаторов нет; general-purpose у штаба нет",
          "momus" in agents_hook(hq)[1] and all("momus" not in agents_hook(d)[1] for d in (ab, ts, mb))
          and "general-purpose" not in agents_hook(hq)[1] and "claude" not in agents_hook(hq)[1])
    check("чужие лиды — в deny у каждого координатора",
          "hephaestus-sources" in agent_rules(ab) and {"hephaestus-broker", "apollo-broker"} <= set(agent_rules(ts)))
    reads = [x for x in hq["permissions"]["deny"] if not x.startswith("Agent(")]
    check("hq: правила Read на месте (агентские правила — дописаны, не вместо)",
          reads and all(x.startswith("Read(") for x in reads))
    check("мастерская: без хука agents и без правил Agent(…) (вне P0-6)",
          agents_hook(ws) is None and not agent_rules(ws) and has_guard(ws))
    alerts = open(os.path.join(home, "alerts.md")).read() if os.path.exists(os.path.join(home, "alerts.md")) else ""
    check("нет agents.py в ~/.claude/plugins — тревога (окна не позовут никого)", "agents.py" in alerts)
    cmd = agents_hook(ab)[2]["command"]
    r = subprocess.run(shlex.split(cmd), input=json.dumps({"tool_name": "Agent", "tool_input": {"subagent_type": "argus"}}),
                       env=env, capture_output=True, text=True, timeout=30)
    check("команда окна без файла agents.py — код 2 (блок, а не пропуск)", r.returncode == 2)
    r = subprocess.run([sys.executable, "-I", CTX, "agents", "argus"], input="{}", env=env, capture_output=True,
                       text=True, timeout=30)
    check("старый ctx.py agents — команды больше нет (подсказка, без решения)",
          r.returncode == 0 and not r.stdout.strip() and "agents" not in r.stderr)

    # --- agents.py: Agent и Task ----------------------------------------------------------------------------------------
    cenv = dict(env)
    br = os.path.join(tmp, "projects", "br")
    lst = ",".join(want["athena-broker"][1])
    agent = lambda **ti: {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Agent",  # noqa: E731
                          "cwd": br, "tool_input": dict(ti, prompt="x")}
    gp = agent(subagent_type="general-purpose")
    res = run_hook(cenv, lst, gp)
    check("general-purpose из главной сессии — отказ JSON-ом с причиной и списком", res.startswith("deny:")
          and "general-purpose" in res and "prometheus" in res and "P0-6" in res)
    check("без subagent_type (это general-purpose) — отказ", run_hook(cenv, lst, agent()).startswith("deny:"))
    check("пустой subagent_type — отказ", run_hook(cenv, lst, agent(subagent_type="")).startswith("deny:"))
    check("свой лид — пропуск", run_hook(cenv, lst, agent(subagent_type="hephaestus-broker")) == "allow")
    check("dev-haiku, dev-sonnet, dev-opus из окна координатора — пропуск",
          all(run_hook(cenv, lst, agent(subagent_type=t)) == "allow" for t in ("dev-haiku", "dev-sonnet", "dev-opus")))
    check("codex-dev, лид чужого направления и hq-агенты (zeus-*, chiron, clio, momus) — отказ",
          all(run_hook(cenv, lst, agent(subagent_type=t)).startswith("deny:")
              for t in ("codex-dev", "hephaestus-sources", "zeus-hq", "zeus", "chiron", "clio", "momus", "dev-sonnet2")))
    check("окно штаба dev-* не получает",
          not any(t.startswith("dev-") for t in agents_hook(hq)[1]))
    check("Explore — пропуск; explore (другой регистр) — отказ",
          run_hook(cenv, lst, agent(subagent_type="Explore")) == "allow"
          and run_hook(cenv, lst, agent(subagent_type="explore")).startswith("deny:"))
    check("tool_name Task — та же проверка", run_hook(cenv, lst, dict(gp, tool_name="Task")).startswith("deny:"))
    check("general-purpose с agent_id (зовёт субагент окна) — пропуск",
          run_hook(cenv, lst, dict(gp, agent_id="a1", agent_type="hephaestus-broker")) == "allow")
    # сбой — код 2: на 2.1.292 onFailure: block не работает, код 1 и таймаут пропускают вызов
    check("тип не строка — код 2", run_hook(cenv, lst, agent(subagent_type=["argus"])).startswith("block:"))
    check("tool_input не объект — код 2", run_hook(cenv, lst, dict(gp, tool_input="argus")).startswith("block:"))
    res = run_hook(cenv, lst, "{не json")
    check("мусор на stdin — код 2 и причина в stderr", res.startswith("block:") and "P0-6" in res)
    check("событие не объект или пустое — код 2",
          run_hook(cenv, lst, "[1, 2]").startswith("block:") and run_hook(cenv, lst, "{}").startswith("block:"))
    check("пустой список — код 2 всем, и своим тоже",
          run_hook(cenv, "", agent(subagent_type="argus")).startswith("block:")
          and run_hook(cenv, None, agent(subagent_type="argus")).startswith("block:")
          and run_hook(cenv, ",", agent(subagent_type="argus")).startswith("block:"))
    res = run_hook(cenv, lst, {"tool_name": "Skill", "cwd": "/x\u0000y", "tool_input": {"skill": "aud"}})
    check("исключение внутри хука (NUL в cwd) — код 2 с именем исключения", res.startswith("block:")
          and "ValueError" in res)

    # --- навыки с context: fork -----------------------------------------------------------------------------------------
    def skill_file(root, folder, head, name=None):
        p = os.path.join(root, ".claude", "skills", folder, "SKILL.md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(f"---\nname: {name or folder}\ndescription: d\n{head}---\n\n# Навык\n\ncontext: fork\n")
        return p

    sk = lambda name, cwd=br, **kw: dict({  # noqa: E731
        "session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Skill", "cwd": cwd,
        "tool_input": {"skill": name, "args": "x"}}, **kw)
    skill_file(tmp, "aud", "context: fork\nagent: general-purpose\n")
    res = run_hook(cenv, lst, sk("aud"))
    check("навык с context: fork и agent: general-purpose — отказ координатору",
          res.startswith("deny:") and "навык aud" in res and "general-purpose" in res)
    check("тот же навык как /aud — отказ", run_hook(cenv, lst, sk("/aud")).startswith("deny:"))
    check("тот же навык из субагента (agent_id) — пропуск", run_hook(cenv, lst, sk("aud", agent_id="a1")) == "allow")
    skill_file(tmp, "aud", "context: fork\nagent: momus\n")
    hq_lst = ",".join(want["hq"][1])
    check("навык с fork и agent: momus (как audit) — штабу пропуск, координатору отказ",
          run_hook(cenv, hq_lst, sk("aud")) == "allow" and run_hook(cenv, lst, sk("aud")).startswith("deny:"))
    skill_file(tmp, "aud", "context: fork\nagent: general-purpose\n")
    check("навык с fork и agent: general-purpose — штабу тоже отказ", run_hook(cenv, hq_lst, sk("aud")).startswith("deny:"))
    skill_file(tmp, "aud", "context: 'fork'\nagent: \"Explore\"\n")
    check("навык с fork и agent: Explore — пропуск", run_hook(cenv, lst, sk("aud")) == "allow")
    skill_file(tmp, "aud", "context: fork\n")
    check("навык с fork без agent: — это general-purpose, отказ", run_hook(cenv, lst, sk("aud")).startswith("deny:"))
    skill_file(tmp, "plain", "")
    check("обычный навык без fork — пропуск (и строка context: fork в тексте, не в шапке, не в счёт)",
          run_hook(cenv, lst, sk("plain")) == "allow")
    check("навыка нет — пропуск", run_hook(cenv, lst, sk("nope")) == "allow")
    check("имя не по образцу — пропуск (не навык)",
          run_hook(cenv, lst, sk("../aud")) == "allow" and run_hook(cenv, lst, sk("app:")) == "allow")
    check("имя навыка не строка — код 2", run_hook(cenv, lst, dict(sk("x"), tool_input={"skill": 1})).startswith("block:"))
    skill_file(br, "proj", "context: fork\nagent: claude\n")
    check("навык проекта (папка события) с fork — отказ", run_hook(cenv, lst, sk("proj")).startswith("deny:"))

    # случаи ревью argus (PoC /tmp/claude-501/argus-0062): каждый раньше пропускался
    skill_file(tmp, "dup", "context: fork\n")
    skill_file(br, "dup", "")
    check("личный dup с fork и проектный dup без fork — отказ (Claude Code берёт личный)",
          run_hook(cenv, lst, sk("dup")).startswith("deny:"))
    skill_file(tmp, "dup2", "")
    skill_file(br, "dup2", "context: fork\n")
    check("и наоборот: личный без fork, проектный с fork — отказ (проверяются все кандидаты)",
          run_hook(cenv, lst, sk("dup2")).startswith("deny:"))
    skill_file(br, "deploy-staging", "context: fork\nagent: general-purpose\n", name="dstage")
    check("имя из поля name: (dstage в папке deploy-staging) — отказ",
          run_hook(cenv, lst, sk("dstage")).startswith("deny:")
          and run_hook(cenv, lst, sk("deploy-staging")).startswith("deny:"))
    skill_file(br, "rootfork", "context: fork\n")
    os.makedirs(os.path.join(br, "app", "sub"))
    check("навык в корне проекта, папка события ниже (br/app/sub) — отказ",
          run_hook(cenv, lst, sk("rootfork", cwd=os.path.join(br, "app", "sub"))).startswith("deny:"))
    skill_file(os.path.join(br, "app"), "nf", "context: fork\n")
    check("вложенное имя app:nf из корня проекта — отказ", run_hook(cenv, lst, sk("app:nf")).startswith("deny:"))
    skill_file(os.path.join(br, "apps", "web"), "deploy", "context: fork\n")
    check("вложенное имя apps/web:deploy — отказ", run_hook(cenv, lst, sk("apps/web:deploy")).startswith("deny:"))
    elsewhere = os.path.join(tmp, "projects", "src")
    check("app:nf из другой папки, но с CLAUDE_PROJECT_DIR — отказ; без него — пропуск",
          run_hook(dict(cenv, CLAUDE_PROJECT_DIR=br), lst, sk("app:nf", cwd=elsewhere)).startswith("deny:")
          and run_hook(cenv, lst, sk("app:nf", cwd=elsewhere)) == "allow")
    check("rootfork из другой папки с CLAUDE_PROJECT_DIR — отказ",
          run_hook(dict(cenv, CLAUDE_PROJECT_DIR=br), lst, sk("rootfork", cwd=elsewhere)).startswith("deny:"))
    p = os.path.join(tmp, ".claude", "plugins", "cache", "mk", "plug", "1.0", "skills", "forky", "SKILL.md")
    os.makedirs(os.path.dirname(p))
    open(p, "w").write("---\nagent: general-purpose\ncontext: fork\n---\n")
    check("навык плагина plug:forky с fork — отказ", run_hook(cenv, lst, sk("plug:forky")).startswith("deny:"))
    p = os.path.join(tmp, ".claude", "plugins", "cache", "mk", "plug", "1.0", "skills", "other", "SKILL.md")
    os.makedirs(os.path.dirname(p))
    open(p, "w").write("---\nname: renamed\ncontext: fork\n---\n")
    check("навык плагина по полю name: (plug:renamed) — отказ", run_hook(cenv, lst, sk("plug:renamed")).startswith("deny:"))
    fifo = os.path.join(tmp, ".claude", "skills", "fifo", "SKILL.md")
    os.makedirs(os.path.dirname(fifo))
    os.mkfifo(fifo)
    check("SKILL.md — FIFO: не виснет, пропуск", run_hook(cenv, lst, sk("fifo")) == "allow")
    many = os.path.join(tmp, "projects", "kn")
    for i in range(2001):
        os.makedirs(os.path.join(many, ".claude", "skills", "s%04d" % i))
    res = run_hook(cenv, lst, sk("nope", cwd=many))
    check("больше 2000 навыков — код 2 (не проверить за время хука)", res.startswith("block:") and "2000" in res)

    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
