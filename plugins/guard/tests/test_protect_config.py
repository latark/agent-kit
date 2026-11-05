#!/usr/bin/env python3
"""Тесты protect-config, metis-0841: координатор и лид направления правят навыки, команды и роли своего проекта.

Запуск: python3.14 -I plugins/guard/tests/test_protect_config.py   (код выхода 0 — все прошли)
Подменённый HOME во временной папке, события PreToolUse на stdin guard.py (через _guard_shim.py, как test_guard.py).
Проверяет: окно athena-brokerassistant (координатор, его лиды hephaestus- и apollo-brokerassistant) пишет
<папка направления>/.claude/skills|commands|agents — Write, Edit, MultiEdit и простые формы Bash (heredoc, cp, mv,
mkdir, rm); отказ — чужой проект, другие роли, строка frontmatter вне класса (ключ не из списка разрешённых, форма
YAML не «ключ: значение»: тег, якорь, алиас, «? ключ», кавычки), строка !`…` и блок ```!, роль проекта с именем роли
Пантеона (файл или name, без регистра), mv жёсткой ссылки, текст, который не вычислить (sed -i, echo >,
NotebookEdit). Ревью #347: Б1–Б4. Закрыто и в своём направлении: .claude/hooks,
settings*.json, .mcp.json, .git/config и .git/hooks, сама .claude как цель cp -R/tar/rsync, копия дерева в skills.
Запись в свои skills после taint (tg-taint) — вопрос, в bypassPermissions — отказ (hooks/taint.py не менялся).
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import uuid
import atexit as _atexit
import shutil as _shutil

SUB_TIMEOUT = 60  # срок подпроцесса на нагруженном Mac (metis-0634)
_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="pc-root-"))
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(os.path.dirname(HERE), "hooks")
GUARD = os.path.join(HOOKS, "guard.py")
TAINT = os.path.join(HOOKS, "taint.py")
SHIM = os.path.join(HERE, "_guard_shim.py")

APP, ROOT_BA, SITE, AK = "projects/brokerAssistantApp/app", "projects/brokerAssistantApp", "projects/sitebuilder", \
    "projects/agent-kit"
COORD = ("domain-coordinator", False)
LEAD = ("hephaestus-brokerassistant", True)
APOLLO = ("apollo-brokerassistant", False)

failed = total = 0


def check(name, ok, detail=""):
    global failed, total
    total += 1
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if not ok and detail else ""))


def setup(home):
    # папки agents, commands, hooks не создаём: песочница окна закрывает их запись (**/.claude/agents), а guard судит
    # цель записи и без готовой папки
    for d in (APP + "/.claude/skills/x", APP + "/.claude/skills/risky", ROOT_BA + "/.claude", SITE + "/.claude",
              AK + "/.claude", ".claude/pantheon", ".local/state/pantheon", "ai/pantheon", "src"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    json.dump({"domains": {
        "athena-brokerassistant": ["~/" + APP, "~/" + ROOT_BA],
        "hermes-site": ["~/" + SITE],
        "metis-pantheon": ["~/" + AK, "~/.claude"],
    }}, open(os.path.join(home, ".local/state/pantheon/domains.json"), "w"))
    with open(os.path.join(home, ".claude/pantheon/policy.toml"), "w") as fh:
        fh.write('always = ["~/.claude/agent-memory"]\n[coordinators]\nmetis-pantheon = ["~/projects/agent-kit"]\n')
    files = {
        APP + "/.claude/skills/x/SKILL.md": "---\nname: x\ndescription: лимиты источников\n---\nбез прокси\n",
        APP + "/.claude/skills/risky/SKILL.md": "---\nname: r\nallowed-tools: Bash\n---\nтекст\n",
        "src/clean.md": "---\nname: c\ndescription: d\n---\nтело\n",
        "src/risky.md": "---\nname: c\nallowed-tools: Bash(*)\n---\nтело\n",
    }
    files["src/hard.md"] = files["src/clean.md"]
    files["src/argus.md"] = files["src/clean.md"]
    for rel, text in files.items():
        with open(os.path.join(home, rel), "w") as fh:
            fh.write(text)
    os.symlink(os.path.join(home, "src/clean.md"), os.path.join(home, "src/link.md"))
    os.link(os.path.join(home, "src/hard.md"), os.path.join(home, "src/hard-other.md"))  # жёсткая ссылка, nlink 2


def run(home, pdir, who, tool, tool_input, cwd=None):
    """→ (решение allow|deny, текст причины)."""
    role, sub = who
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
             "cwd": os.path.join(home, cwd if cwd is not None else pdir), "session_id": "s-test",
             "tool_use_id": "toolu_" + uuid.uuid4().hex}
    if role:
        event["agent_type"] = role
    if sub:
        event["agent_id"] = "a1"
    env = {"HOME": home, "PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": os.path.join(home, pdir),
           "TMPDIR": "/nonexistent-tmp"}
    r = subprocess.run([sys.executable, "-I", SHIM, GUARD], input=json.dumps(event), capture_output=True, text=True,
                       env=env, timeout=SUB_TIMEOUT)
    if r.returncode == 2:
        return "deny", r.stderr
    try:
        out = json.loads(r.stdout or "{}").get("hookSpecificOutput") or {}
    except ValueError:
        return f"сбой {r.returncode}", r.stdout + r.stderr
    return out.get("permissionDecision") or "allow", out.get("permissionDecisionReason") or ""


def taint_pre(home, tool, ti, mode=None):
    """Решение taint.py на PreToolUse сессии с флагом tg-taint."""
    state = os.path.join(home, ".local/state/tg-taint")
    os.makedirs(state, exist_ok=True)
    open(os.path.join(state, "s-taint"), "w").close()
    ev = {"hook_event_name": "PreToolUse", "session_id": "s-taint", "cwd": os.path.join(home, APP),
          "tool_name": tool, "tool_input": ti}
    if mode:
        ev["permission_mode"] = mode
    r = subprocess.run([sys.executable, "-I", TAINT], input=json.dumps(ev), capture_output=True, text=True,
                       env={"HOME": home, "PATH": os.environ["PATH"], "TMPDIR": _ROOT}, timeout=SUB_TIMEOUT)
    try:
        return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"]
    except (ValueError, KeyError, TypeError):
        return None


def main():
    home = os.path.realpath(tempfile.mkdtemp(prefix="home-"))
    setup(home)
    H = lambda rel: os.path.join(home, rel)  # noqa: E731
    W = lambda rel, text="---\nname: x\ndescription: навык\n---\nбез прокси\n": (  # noqa: E731
        "Write", {"file_path": H(rel), "content": text})
    E = lambda rel, old, new, **kw: ("Edit", {"file_path": H(rel), "old_string": old, "new_string": new, **kw})  # noqa: E731
    B = lambda cmd: ("Bash", {"command": cmd})  # noqa: E731
    skill = APP + "/.claude/skills/x/SKILL.md"
    fm = lambda body: f"---\nname: x\n{body}\n---\nтекст\n"  # noqa: E731
    cases = [
        # (имя, ожидание, папка запуска, (роль, субагент), (инструмент, вход)[, cwd])
        # --- «Готово, когда» 1: своё — можно, чужой проект — отказ ---
        ("athena-brokerassistant правит app/.claude/skills/x/SKILL.md (текст) — можно", "allow", APP, COORD, W(skill)),
        ("athena: чужой проект sitebuilder/.claude/skills — отказ", "deny", APP, COORD,
         W(SITE + "/.claude/skills/x/SKILL.md")),
        ("hermes-site: skills brokerAssistantApp — отказ (не его направление)", "deny", SITE, COORD, W(skill)),
        ("athena: agent-kit/.claude/agents (направление Метиды) — отказ", "deny", APP, COORD,
         W(AK + "/.claude/agents/x.md")),
        # --- кто: координатор и лиды направления; остальные — отказ ---
        ("лид hephaestus-brokerassistant (субагент) пишет commands/x.md — можно", "allow", APP, LEAD,
         W(APP + "/.claude/commands/x.md", "---\ndescription: команда\n---\nсделай $ARGUMENTS\n")),
        ("лид apollo-brokerassistant (главная сессия) пишет agents/x.md с model — можно", "allow", APP, APOLLO,
         W(APP + "/.claude/agents/x.md", "---\nname: x\ndescription: роль\nmodel: sonnet\n---\nты — роль\n")),
        ("dev-opus (субагент лида) — отказ", "deny", APP, ("dev-opus", True), W(skill)),
        ("лид чужого направления hephaestus-site — отказ", "deny", APP, ("hephaestus-site", True), W(skill)),
        ("domain-coordinator субагентом — отказ", "deny", APP, ("domain-coordinator", True), W(skill)),
        ("argus — отказ", "deny", APP, ("argus", True), W(skill)),
        ("hq — отказ", "deny", APP, ("hq", False), W(skill)),
        ("координатор: корень продукта brokerAssistantApp/.claude/skills — можно", "allow", APP, COORD,
         W(ROOT_BA + "/.claude/skills/y/SKILL.md")),
        ("координатор: worktree app/.claude/worktrees/w/.claude/skills — можно", "allow", APP, COORD,
         W(APP + "/.claude/worktrees/w/.claude/skills/y/SKILL.md")),
        ("лид Метиды hephaestus-pantheon: ~/.claude/agents — отказ (ядро)", "deny", AK, ("hephaestus-pantheon", True),
         W(".claude/agents/x.md")),
        ("лид Метиды hephaestus-pantheon: ~/.claude/commands — отказ (ядро)", "deny", AK,
         ("hephaestus-pantheon", True), W(".claude/commands/x.md")),
        ("лид Метиды hephaestus-pantheon: agent-kit/.claude/skills — можно", "allow", AK, ("hephaestus-pantheon", True),
         W(AK + "/.claude/skills/y/SKILL.md")),
        # --- «Готово, когда» 2: ключи frontmatter и !`cmd` — отказ ---
        ("skills: allowed-tools во frontmatter — отказ", "deny", APP, COORD, W(skill, fm("allowed-tools: Bash"))),
        ("skills: строка !`cmd` — отказ", "deny", APP, COORD,
         W(skill, "---\nname: x\n---\nТекущая ветка: !`git branch --show-current`\n")),
        *[(f"skills: ключ {k} — отказ", "deny", APP, COORD, W(skill, fm(k))) for k in (
            "hooks:\n  PreToolUse: []", "model: opus", "context: fork", "allowed_tools: Bash", "Allowed-Tools: Bash",
            '"allowed-tools": Bash', "  allowed-tools: Bash", "name: x\n  allowed-tools: Bash",
            "description: d\n    hooks: {}")],
        ("commands: allowed-tools — отказ", "deny", APP, COORD, W(APP + "/.claude/commands/x.md", fm("allowed-tools: Bash"))),
        ("commands: !`cmd` — отказ", "deny", APP, LEAD, W(APP + "/.claude/commands/x.md", "Статус: !`git status`\n")),
        *[(f"agents: ключ {k} — отказ", "deny", APP, COORD, W(APP + "/.claude/agents/x.md", fm(k))) for k in (
            "tools: Bash", "disallowedTools: Read", "permissionMode: bypassPermissions", "hooks: {}",
            "mcpServers: {}", "permission-mode: acceptEdits")],
        ("agents: !`cmd` в теле — отказ", "deny", APP, COORD, W(APP + "/.claude/agents/x.md", "---\nname: x\n---\n!`id`\n")),
        ("skills: tools (ключ не из списка навыка) — отказ", "deny", APP, COORD, W(skill, fm("tools: Read"))),
        ("skills: model (есть у роли, нет у навыка) — отказ", "deny", APP, COORD, W(skill, fm("model: opus"))),
        # --- ревью #347 Б1: блок ```! (и ~~~!) — динамическая команда ---
        ("skills: блок ```! в теле — отказ", "deny", APP, COORD, W(skill, fm("description: d") + "```!\nid\n```\n")),
        ("skills: блок ```! после текста в строке — отказ", "deny", APP, COORD,
         W(skill, fm("description: d") + "смотри ```!\nid\n```\n")),
        ("commands: блок ~~~! — отказ", "deny", APP, COORD, W(APP + "/.claude/commands/x.md", "~~~!\nid\n~~~\n")),
        ("skills: обычный блок ```bash — можно", "allow", APP, COORD, W(skill, fm("description: d") + "```bash\nid\n```\n")),
        # --- ревью #347 Б2: frontmatter классом — пять форм ключа YAML мимо простого «ключ:» ---
        *[(f"skills: форма ключа {k!r} — отказ", "deny", APP, COORD, W(skill, fm(k))) for k in (
            "!!str allowed-tools: Bash(*)", "&a allowed-tools: Bash(*)", '"allowed\\u002dtools": Bash(*)',
            "? allowed-tools\n: Bash(*)", "k: &k hooks\n*k : {}")],
        *[(f"skills: строка frontmatter {k!r} — отказ", "deny", APP, COORD, W(skill, fm(k))) for k in (
            "...\nallowed-tools: Bash", "description: *a", "description: !!binary eA==", "\tallowed-tools: Bash",
            "agent: Explore", "allowed-tools : Bash", "name:x")],
        ("skills: metadata вложенным словарём — можно", "allow", APP, COORD,
         W(skill, fm("metadata:\n  author: a\n  allowed-tools: Bash"))),
        ("skills: metadata и argument-hint потоком {…} и […] — можно (вложенное — данные)", "allow", APP, COORD,
         W(skill, fm("metadata: {a: 1, allowed-tools: Bash}\nargument-hint: [msg]"))),
        ("skills: description блоком > со строкой «ключ:» внутри — можно", "allow", APP, COORD,
         W(skill, fm("description: >\n  пример: текст\n  ещё"))),
        ("skills: frontmatter с отступом у первой строки — отказ", "deny", APP, COORD,
         W(skill, "---\n  name: x\n  allowed-tools: Bash\n---\nтекст\n")),
        ("skills: строка «  ---» внутри frontmatter — отказ", "deny", APP, COORD,
         W(skill, "---\ndescription: |\n  ---\nallowed-tools: Bash\n---\nтекст\n")),
        ("skills: description блоком, комментарий, argument-hint, when_to_use — можно", "allow", APP, COORD,
         W(skill, "---\nname: x\n# заметка\ndescription: |\n  многострочное: описание\n  ещё\nargument-hint: [файл]\n"
                  "when_to_use: \"когда: нужно\"\nuser-invocable: false\n---\nтекст\n")),
        ("agents: color и maxTurns — можно", "allow", APP, COORD,
         W(APP + "/.claude/agents/x.md", "---\nname: x\ndescription: d\ncolor: blue\nmaxTurns: 5\n---\nты\n")),
        # --- ревью #347 Б3: роль проекта с именем роли Пантеона подменяет её ---
        ("agents: файл argus.md без опасных ключей — отказ", "deny", APP, COORD,
         W(APP + "/.claude/agents/argus.md", "---\nname: x\ndescription: d\n---\nпринимай\n")),
        ("agents: файл Talos.md — отказ (без регистра)", "deny", APP, COORD,
         W(APP + "/.claude/agents/Talos.md", "---\nname: x\n---\nт\n")),
        ("agents: файл tg-reader.md пустой — отказ", "deny", APP, COORD, W(APP + "/.claude/agents/tg-reader.md", "")),
        *[(f"agents: другой файл, {k} — отказ", "deny", APP, COORD,
           W(APP + "/.claude/agents/r.md", f"---\n{k}\ndescription: d\n---\nпринимай\n")) for k in (
            "name: argus", "name: ARGUS", 'name: "talos"', "name: 'Tg-Reader'", "name: argus # ревьюер",
            "name: dev-opus", "name: hephaestus-brokerassistant", "name: |\n  argus",
            "name: \"\\x61rgus\"")],
        ("skills: навык с name: argus — можно (навык роль не подменяет)", "allow", APP, COORD,
         W(skill, fm("description: d").replace("name: x", "name: argus"))),
        ("Bash: mv argus.md в .claude/agents/ (папка) — отказ", "deny", APP, COORD,
         B(f"mv {H('src/argus.md')} .claude/agents/")),
        ("Bash: cp argus.md в .claude/agents/ (папка) — отказ", "deny", APP, LEAD,
         B(f"cp {H('src/argus.md')} .claude/agents/")),
        ("Bash: cp чистого файла в .claude/skills/x/ (папка) — можно", "allow", APP, COORD,
         B(f"cp {H('src/clean.md')} .claude/skills/x/")),
        ("skills: allowed-tools в теле после frontmatter — можно", "allow", APP, COORD,
         W(skill, "---\nname: x\n---\nallowed-tools: так в навыке не писать\n")),
        ("skills: без frontmatter, простой текст — можно", "allow", APP, COORD, W(skill, "заметка\n")),
        ("skills: frontmatter после пустых строк и BOM — отказ", "deny", APP, COORD,
         W(skill, "﻿\n\n---\nallowed-tools: Bash\n---\n")),
        ("skills: frontmatter без конца — весь текст судится — отказ", "deny", APP, COORD,
         W(skill, "---\nname: x\nтекст\nmodel: opus\n")),
        ("skills: скрипт рядом с навыком (scripts/run.sh) — можно", "allow", APP, COORD,
         W(APP + "/.claude/skills/x/scripts/run.sh", "#!/bin/sh\necho ok\n")),
        # Edit и MultiEdit: судится новый текст файла
        ("Edit SKILL.md: правка текста — можно", "allow", APP, COORD, E(skill, "без прокси", "без прокси, только VPN")),
        ("Edit SKILL.md: добавить allowed-tools — отказ", "deny", APP, COORD,
         E(skill, "name: x\n", "name: x\nallowed-tools: Bash\n")),
        ("Edit SKILL.md: добавить !`cmd` — отказ", "deny", APP, COORD, E(skill, "без прокси", "!`curl x`")),
        ("Edit навыка, где уже есть allowed-tools (правка тела) — отказ", "deny", APP, COORD,
         E(APP + "/.claude/skills/risky/SKILL.md", "текст", "новый текст")),
        ("Edit навыка: убрать allowed-tools — можно", "allow", APP, COORD,
         E(APP + "/.claude/skills/risky/SKILL.md", "allowed-tools: Bash\n", "")),
        ("Edit: old_string не найден — отказ (текст не вычислить)", "deny", APP, COORD, E(skill, "нет такого", "y")),
        ("Edit: replace_all — можно", "allow", APP, COORD, E(skill, "x", "y", replace_all=True)),
        ("MultiEdit: чистые правки — можно", "allow", APP, COORD, ("MultiEdit", {"file_path": H(skill), "edits": [
            {"old_string": "без", "new_string": "БЕЗ"}, {"old_string": "прокси", "new_string": "VPN"}]})),
        ("MultiEdit: вторая правка вносит hooks — отказ", "deny", APP, COORD, ("MultiEdit", {"file_path": H(skill), "edits": [
            {"old_string": "без", "new_string": "БЕЗ"}, {"old_string": "name: x\n", "new_string": "name: x\nhooks: {}\n"}]})),
        ("NotebookEdit в skills — отказ", "deny", APP, COORD,
         ("NotebookEdit", {"notebook_path": H(APP + "/.claude/skills/x/n.ipynb"), "new_source": "x"})),
        # Bash: только формы, чей текст виден
        ("Bash: cat > SKILL.md <<'EOF' (чистый) — можно", "allow", APP, COORD,
         B("cat > .claude/skills/x/SKILL.md <<'EOF'\n---\nname: x\n---\nбез прокси $ARGUMENTS\nEOF")),
        ("Bash: heredoc с allowed-tools — отказ", "deny", APP, COORD,
         B("cat > .claude/skills/x/SKILL.md <<'EOF'\n---\nallowed-tools: Bash\n---\nEOF")),
        ("Bash: heredoc с !`cmd` — отказ", "deny", APP, COORD,
         B(f"cat > {H(APP)}/.claude/commands/x.md <<'EOF'\n!`id`\nEOF")),
        ("Bash: heredoc без кавычек, без $ — можно", "allow", APP, COORD,
         B("cat <<EOF > .claude/skills/x/SKILL.md\nпростой текст\nEOF")),
        ("Bash: heredoc без кавычек с $X — отказ (оболочка раскроет)", "deny", APP, COORD,
         B("cat <<EOF > .claude/skills/x/SKILL.md\nтекст $X\nEOF")),
        ("Bash: cat >> к навыку с allowed-tools — отказ", "deny", APP, COORD,
         B("cat >> .claude/skills/risky/SKILL.md <<'EOF'\nещё строка\nEOF")),
        ("Bash: cat >> к чистому навыку — можно", "allow", APP, COORD,
         B("cat >> .claude/skills/x/SKILL.md <<'EOF'\nещё строка\nEOF")),
        ("Bash: cp чистого файла — можно", "allow", APP, COORD, B(f"cp -f {H('src/clean.md')} .claude/skills/x/SKILL.md")),
        ("Bash: cp файла с allowed-tools — отказ", "deny", APP, COORD, B(f"cp {H('src/risky.md')} .claude/skills/x/SKILL.md")),
        ("Bash: mv чистого файла — можно", "allow", APP, LEAD, B(f"mv {H('src/clean.md')} .claude/agents/c.md")),
        ("Bash: mv ссылки — отказ", "deny", APP, COORD, B(f"mv {H('src/link.md')} .claude/skills/x/SKILL.md")),
        # ревью #347 Б4: жёсткая ссылка переедет второй ссылкой — текст потом поменяют через src/hard-other.md
        ("Bash: mv жёсткой ссылки (nlink 2) — отказ", "deny", APP, COORD, B(f"mv {H('src/hard.md')} .claude/agents/h.md")),
        ("Bash: cp жёсткой ссылки (копия текста) — можно", "allow", APP, COORD,
         B(f"cp {H('src/hard.md')} .claude/skills/x/SKILL.md")),
        ("Bash: cp нет такого файла — отказ", "deny", APP, COORD, B("cp nope.md .claude/skills/x/SKILL.md")),
        ("Bash: mkdir -p .claude/skills/y — можно", "allow", APP, COORD, B("mkdir -p .claude/skills/y")),
        ("Bash: mkdir -p .claude/agents — можно", "allow", APP, LEAD, B("mkdir -p .claude/agents")),
        ("Bash: rm -rf .claude/skills/x — можно", "allow", APP, COORD, B("rm -rf .claude/skills/x")),
        ("Bash: echo > SKILL.md — отказ (текст не разобран)", "deny", APP, COORD, B("echo hi > .claude/skills/x/SKILL.md")),
        ("Bash: sed -i — отказ", "deny", APP, COORD, B("sed -i '' 's/a/b/' .claude/skills/x/SKILL.md")),
        ("Bash: tee — отказ", "deny", APP, COORD, B("echo hi | tee .claude/skills/x/SKILL.md")),
        ("Bash: heredoc и цепочка && — отказ", "deny", APP, COORD,
         B("cat > .claude/skills/x/SKILL.md <<'EOF'\nтекст\nEOF\ntrue && echo")),
        ("Bash: command cat (обёртка) — отказ", "deny", APP, COORD,
         B("command cat > .claude/skills/x/SKILL.md <<'EOF'\nтекст\nEOF")),
        ("Bash: cp -R в .claude/skills/ — отказ (дерево)", "deny", APP, COORD, B(f"cp -R {H('src')} .claude/skills/")),
        ("Bash: tar -xf -C .claude/skills — отказ", "deny", APP, COORD, B("tar -xf a.tar -C .claude/skills")),
        ("Bash: git checkout -- .claude/skills/x/SKILL.md — отказ", "deny", APP, COORD,
         B("git checkout -- .claude/skills/x/SKILL.md")),
        # неразобранную цель с 0823 первым режет domain/pantheon-acl: нужен отказ, правило — любое guard
        ("Bash: путь через $(…) в skills — отказ (любым правилом guard)", "deny", APP, COORD,
         B("cat > .claude/skills/$(echo x)/SKILL.md <<'EOF'\nтекст\nEOF")),
        # --- закрыто и в своём направлении ---
        ("свой проект: .claude/hooks/x.sh — отказ", "deny", APP, COORD, W(APP + "/.claude/hooks/x.sh", "echo")),
        ("свой проект: .claude/settings.json — отказ", "deny", APP, COORD, W(APP + "/.claude/settings.json", "{}")),
        ("свой проект: .claude/settings.local.json — отказ", "deny", APP, LEAD, W(APP + "/.claude/settings.local.json", "{}")),
        ("свой проект: .mcp.json — отказ", "deny", APP, COORD, W(APP + "/.mcp.json", "{}")),
        ("свой проект: .git/config — отказ", "deny", APP, COORD, W(APP + "/.git/config", "")),
        ("свой проект: .git/hooks/pre-commit — отказ", "deny", APP, COORD, W(APP + "/.git/hooks/pre-commit", "")),
        ("свой проект: cp -R x app/.claude/ — отказ", "deny", APP, COORD, B(f"cp -R {H('src')} {H(APP)}/.claude/")),
        ("свой проект: rsync -a src/ .claude — отказ", "deny", APP, COORD, B(f"rsync -a {H('src')}/ .claude")),
        ("свой проект: settings.json внутри skills/x/.claude — отказ", "deny", APP, COORD,
         W(APP + "/.claude/skills/x/.claude/settings.json", "{}")),
        ("свой проект: hooks внутри skills/x/.claude — отказ", "deny", APP, COORD,
         W(APP + "/.claude/skills/x/.claude/hooks/a.sh", "echo")),
        ("свой проект: Bash в .claude/hooks — отказ", "deny", APP, COORD,
         B("cat > .claude/hooks/a.sh <<'EOF'\necho\nEOF")),
    ]
    for case in cases:
        name, want, pdir, who, (tool, ti) = case[:5]
        got, why = run(home, pdir, who, tool, ti, *case[5:])
        ok = got == want and (want == "allow" or "protect-config" in why or "любым правилом" in name and "Правило" in why)
        check(name, ok, f"{got}: {why[:300]}")
    # причина отказа своего направления называет, что не так, и кто правит
    _, why = run(home, APP, COORD, *W(skill, fm("allowed-tools: Bash")))
    check("причина: ключ назван, правит metis-pantheon", "allowed-tools" in why and "metis-pantheon" in why, why[:300])
    _, why = run(home, APP, COORD, *B("echo hi > .claude/skills/x/SKILL.md"))
    check("причина Bash: текст не разобрать — Write или Edit", "Write или Edit" in why, why[:300])
    # --- ревью #347 Б3: собранная роль Пантеона вне списков guard (charon в ~/.claude/agents) ---
    # в процессе: ~/.claude/agents песочница окна закрывает на запись, папку ролей подменяем (ROLES_DIR)
    os.environ["HOME"] = home
    spec = importlib.util.spec_from_file_location("guard_rules_pc", os.path.join(HOOKS, "guard_rules.py"))
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    pc = sys.modules["protect_config"]
    pc.ROLES_DIR = "roles-built"
    os.makedirs(os.path.join(home, "roles-built"), exist_ok=True)
    charon = "---\nname: Charon\ndescription: d\n---\nт\n"
    check("собранной роли нет — name: charon можно", pc._text_risk(charon, {"agents"}, "r.md") is None)
    check("собранной роли нет — файл charon.md можно", pc._text_risk("т\n", {"agents"}, "charon.md") is None)
    open(os.path.join(home, "roles-built/charon.md"), "w").close()
    why = pc._text_risk(charon, {"agents"}, "r.md") or ""
    check("собранная роль charon — name: Charon отказ", "роль Пантеона" in why, why)
    why = pc._text_risk("т\n", {"agents"}, "CHARON.md") or ""
    check("собранная роль charon — файл CHARON.md отказ", "роль Пантеона" in why, why)
    check("собранная роль charon — навык с name: charon можно", pc._text_risk(charon, {"skills"}, "SKILL.md") is None)
    # --- «Готово, когда» 3: после taint запись в свои skills — вопрос, в bypassPermissions — отказ ---
    th = os.path.realpath(tempfile.mkdtemp(prefix="taint-home-"))
    setup(th)
    for name, (tool, ti) in (("Write своего SKILL.md", ("Write", {"file_path": os.path.join(th, skill), "content": "x"})),
                             ("Edit своего SKILL.md", ("Edit", {"file_path": os.path.join(th, skill),
                                                                "old_string": "a", "new_string": "b"})),
                             ("Bash heredoc в свои skills",
                              ("Bash", {"command": "cat > .claude/skills/x/SKILL.md <<'EOF'\nx\nEOF"}))):
        d = taint_pre(th, tool, ti)
        check(f"taint: {name} — вопрос (ask)", d == "ask", str(d))
        d = taint_pre(th, tool, ti, "bypassPermissions")
        check(f"taint: {name}, bypassPermissions — отказ", d == "deny", str(d))
    print(f"\n{total - failed} из {total} прошли")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
