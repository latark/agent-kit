#!/usr/bin/env python3
"""Тесты проверки ролей проекта после хода (metis-0883) и флага GUARD_BRANCH в правилах (metis-1227).

Запуск: python3.14 -I plugins/guard/tests/test_agents_after.py   (код выхода 0 — все прошли)
Подменённый HOME во временной папке (mkroot: в окне роли песочница режет .claude/agents под кэшем окна), события
PostToolUse Bash на stdin guard.py через _guard_shim.py, как test_protect_config.py. Файл роли проекта в
<папка направления>/.claude/agents, изменённый мимо Write/Edit (скрипт, git), после команды Bash судит тот же
_text_risk: находка — {"decision": "block"} с причиной и строка в logs/guard-agents.log; метка сессии
STATE/guard-agents/<sid> не сдвигается, пока файл не исправлен. Без находки, у чужого направления, у координатора
с привилегией, с негодным session_id и для путей защит (~/.claude/agents) — ничего.
GUARD_BRANCH=1: хук плагина при управляемых настройках не выходит раньше правил (проба guard ветки, metis-1227).
"""
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _py311 import mkroot  # noqa: E402 — корень, где тест пишет .claude/agents, и в окне роли (metis-0941)

SUB_TIMEOUT = 60
HOOKS = os.path.join(os.path.dirname(HERE), "hooks")
GUARD = os.path.join(HOOKS, "guard.py")
SHIM = os.path.join(HERE, "_guard_shim.py")

APP, ROOT_BA, SITE, AK = "projects/projAApp/app", "projects/projAApp", "projects/sitebuilder", "projects/agent-kit"
COORD = ("domain-coordinator", False)
LEAD = ("hephaestus-proja", True)
CLEAN = "---\nname: c\ndescription: d\n---\nтело\n"
RISKY = "---\nname: c\nallowed-tools: Bash(*)\n---\nтело\n"

failed = total = 0


def check(name, ok, detail=""):
    global failed, total
    total += 1
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if not ok and detail else ""))


ROOT = os.path.realpath(mkroot("agents-after-"))
_n = 0


def fresh(privileged=True):
    """Новый HOME с domains.json и policy.toml; privileged — у metis-pantheon есть запись coordinators."""
    global _n
    _n += 1
    home = os.path.join(ROOT, f"h{_n}")
    for d in (APP + "/.git", ROOT_BA + "/nogit", SITE, AK, ".claude/pantheon", ".local/state/pantheon"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    json.dump({"domains": {
        "athena-proja": ["~/" + APP, "~/" + ROOT_BA],
        "hermes-site": ["~/" + SITE],
        "metis-pantheon": ["~/" + AK, "~/.claude"],
    }}, open(os.path.join(home, ".local/state/pantheon/domains.json"), "w"))
    with open(os.path.join(home, ".claude/pantheon/policy.toml"), "w") as fh:
        fh.write('always = ["~/.claude/agent-memory"]\n')
        if privileged:
            fh.write('[coordinators]\nmetis-pantheon = ["~/projects/agent-kit"]\n')
    return home


def put(home, rel, text):
    p = os.path.join(home, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def post(home, pdir, who, sid="s-after-0001", extra=None):
    """→ (код, decision, reason) PostToolUse Bash хука плагина."""
    role, sub = who
    event = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"},
             "tool_response": {"stdout": "", "stderr": ""}, "cwd": os.path.join(home, pdir), "session_id": sid,
             "tool_use_id": "toolu_" + uuid.uuid4().hex}
    if role:
        event["agent_type"] = role
    if sub:
        event["agent_id"] = "a1"
    env = {"HOME": home, "PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": os.path.join(home, pdir),
           "TMPDIR": ROOT, **(extra or {})}
    r = subprocess.run([sys.executable, "-I", SHIM, GUARD], input=json.dumps(event), capture_output=True, text=True,
                       env=env, timeout=SUB_TIMEOUT)
    try:
        out = json.loads(r.stdout or "{}")
    except ValueError:
        return r.returncode, "сбой", r.stdout + r.stderr
    return r.returncode, out.get("decision"), out.get("reason") or ""


def mark_of(home, sid="s-after-0001"):
    return os.path.join(home, ".local/state/pantheon/guard-agents", sid)


try:
    # --- чистый файл: ничего, метка 0600 в папке 0700 ---------------------------------------------------------------
    h = fresh()
    put(h, APP + "/.claude/agents/ok.md", CLEAN)
    rc, dec, why = post(h, APP, COORD)
    check("чистая роль проекта после хода — без отказа", rc == 0 and dec is None, (rc, dec, why))
    m = mark_of(h)
    check("метка сессии — файл 0600, папка 0700", os.path.isfile(m) and oct(os.stat(m).st_mode & 0o777) == "0o600"
          and oct(os.stat(os.path.dirname(m)).st_mode & 0o777) == "0o700")
    m0 = os.stat(m).st_mtime
    # --- опасная роль после метки: отказ, лог, метка не двигается --------------------------------------------------
    time.sleep(0.05)
    bad = put(h, APP + "/.claude/agents/bad.md", RISKY)
    rc, dec, why = post(h, APP, COORD)
    check("роль с allowed-tools, записанная мимо Write/Edit, — decision block с путём и правилом",
          rc == 0 and dec == "block" and "protect-config" in why and "bad.md" in why and "metis-0883" in why,
          (rc, dec, why))
    check("метка с находкой не сдвинулась", os.stat(m).st_mtime == m0, (os.stat(m).st_mtime, m0))
    log = os.path.join(h, ".local/state/pantheon/logs/guard-agents.log")
    lines = open(log, encoding="utf-8").read().splitlines() if os.path.isfile(log) else []
    check("строка в logs/guard-agents.log: сессия, роль, путь", len(lines) == 1
          and lines[0].split("\t")[1:4] == ["s-after-0001", "domain-coordinator", os.path.realpath(bad)], lines)
    rc, dec, why = post(h, APP, COORD)
    check("следующая команда той же сессии — снова отказ, пока файл не исправлен", dec == "block", (rc, dec, why))
    put(h, APP + "/.claude/agents/bad.md", CLEAN)
    rc, dec, why = post(h, APP, COORD)
    check("файл исправлен — отказа нет", rc == 0 and dec is None, (rc, dec, why))
    check("без находки метка сдвинулась вперёд", os.stat(m).st_mtime > m0, (os.stat(m).st_mtime, m0))
    put(h, APP + "/.claude/agents/bad.md", RISKY)
    t = time.time() + 120
    os.utime(m, (t, t))
    rc, dec, why = post(h, APP, COORD)
    check("файл изменён раньше метки сессии — не судится", rc == 0 and dec is None, (rc, dec, why))

    # --- где ищутся .claude/agents: подпапка первого уровня и worktree ----------------------------------------------
    for label, rel in (("подпапка первого уровня папки направления", ROOT_BA + "/nogit/.claude/agents/r.md"),
                       ("worktree папки направления", APP + "/.claude/worktrees/w/.claude/agents/r.md"),
                       ("вложенная папка внутри agents", APP + "/.claude/agents/team/r.md")):
        h = fresh()
        put(h, rel, RISKY)
        rc, dec, why = post(h, APP, COORD)
        check(f"{label} — отказ", dec == "block" and "r.md" in why, (rc, dec, why))
    h = fresh()
    put(h, APP + "/.claude/agents/notes.txt", RISKY)
    rc, dec, why = post(h, APP, COORD)
    check("не .md в agents — не судится", dec is None, (rc, dec, why))
    h = fresh()
    put(h, APP + "/.claude/agents/unreadable.md", "x" * (2 * 1024 * 1024))
    rc, dec, why = post(h, APP, COORD)
    check("текст не прочесть (больше предела) — отказ «текст не прочесть»", dec == "block" and "не прочесть" in why,
          (rc, dec, why))
    h = fresh()
    put(h, APP + "/.claude/agents/argus.md", CLEAN)
    rc, dec, why = post(h, APP, LEAD)
    check("лид направления, роль проекта с именем роли Пантеона — отказ", dec == "block" and "argus.md" in why,
          (rc, dec, why))

    # --- кого не судим ----------------------------------------------------------------------------------------------
    h = fresh()
    put(h, APP + "/.claude/agents/bad.md", RISKY)
    for label, pdir, who, sid in (
            ("чужое направление (hermes-site)", SITE, COORD, "s-after-0002"),
            ("сессия без роли Пантеона", APP, ("", False), "s-after-0003"),
            ("короткий session_id", APP, COORD, "s1"),
            ("путь в session_id", APP, COORD, "../../x-escape"),
            ("роль направления без своих папок (apollo чужого)", APP, ("apollo-site", False), "s-after-0004")):
        rc, dec, why = post(h, pdir, who, sid)
        check(f"{label} — без отказа", rc == 0 and dec is None, (rc, dec, why))
    check("негодный session_id — метки нет", not os.path.exists(mark_of(h, "s1"))
          and not os.path.exists(os.path.join(h, ".local/state/x-escape")))
    h = fresh()
    put(h, APP + "/.claude/agents/bad.md", RISKY)
    rc, dec, why = post(h, APP, COORD, extra={"GUARD_OFF": "protect-config"})
    off_ok = dec is None
    put(h, AK + "/.claude/agents/bad.md", RISKY)
    rc, dec, why = post(h, AK, COORD, "s-after-0005")
    check("координатор metis-pantheon с привилегией (policy.toml) — без отказа", rc == 0 and dec is None,
          (rc, dec, why))
    h2 = fresh(privileged=False)
    put(h2, AK + "/.claude/agents/bad.md", RISKY)
    rc, dec, why = post(h2, AK, COORD, "s-after-0005")
    check("тот же координатор без записи coordinators — отказ (привилегия решает)", dec == "block", (rc, dec, why))
    # путь защит: .claude/agents проекта — ссылка на ~/.claude/agents (собранные роли), их судит проверка до хода
    h = fresh()
    put(h, ".claude/agents/bad.md", RISKY)
    os.makedirs(os.path.join(h, APP, ".claude"), exist_ok=True)
    os.symlink(os.path.join(h, ".claude/agents"), os.path.join(h, APP, ".claude/agents"))
    rc, dec, why = post(h, APP, COORD)
    check("agents проекта — ссылка в путь защит (~/.claude/agents) — не судится", rc == 0 and dec is None,
          (rc, dec, why))

    # --- сбой проверки: журнал сбоев, ход не ломается --------------------------------------------------------------
    h = fresh()
    put(h, APP + "/.claude/agents/bad.md", RISKY)
    rc, dec, why = post(h, APP, COORD, extra={"GUARD_SHIM_BOOM": "protect_config.agents_after"})
    fail_log = os.path.join(h, ".local/state/pantheon/logs/guard-failures.log")
    flog = open(fail_log, encoding="utf-8").read() if os.path.isfile(fail_log) else ""
    check("сбой agents_after — код 0 без отказа, строка в журнале сбоев", rc == 0 and dec is None
          and "agents_after" in flog, (rc, dec, why, flog))

    # --- GUARD_BRANCH=1: правила плагина не выходят раньше при управляемых настройках (metis-1227) -----------------
    h = fresh()
    mf = os.path.join(h, "managed.json")
    json.dump({"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 guard.py --managed"}]}]}},
              open(mf, "w"))
    target = os.path.join(h, APP, ".claude/agents/new.md")
    ev = {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": target, "content": RISKY},
          "cwd": os.path.join(h, APP), "session_id": "s-after-0009", "agent_type": "domain-coordinator",
          "tool_use_id": "toolu_" + uuid.uuid4().hex}

    def pre(extra):
        env = {"HOME": h, "PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": os.path.join(h, APP), "TMPDIR": ROOT,
               "GUARD_SHIM_MANAGED": mf, **extra}
        r = subprocess.run([sys.executable, "-I", SHIM, GUARD], input=json.dumps(ev), capture_output=True, text=True,
                           env=env, timeout=SUB_TIMEOUT)
        try:
            return (json.loads(r.stdout or "{}").get("hookSpecificOutput") or {}).get("permissionDecision")
        except ValueError:
            return "сбой"
    check("плагин при управляемых без флага — правила выходят сразу (решения нет)", pre({}) is None)
    check("GUARD_BRANCH=1 при управляемых — правила ветки судят (deny роли с allowed-tools)",
          pre({"GUARD_BRANCH": "1"}) == "deny")
    check("GUARD_BRANCH=0 — как без флага", pre({"GUARD_BRANCH": "0"}) is None)
    check("GUARD_OFF=protect-config — проверка после хода выключена вместе с правилом", off_ok)
finally:
    shutil.rmtree(ROOT, True)

print(f"\n{total - failed}/{total} прошло")
sys.exit(1 if failed else 0)
