#!/usr/bin/env python3
"""Синтетические тесты guard: подменённый HOME во временной папке, события PreToolUse на stdin.

Запуск: python3 -I plugins/guard/tests/test_guard.py   (код выхода 0 — все прошли)
Проверяет карту прав ~/pantheon (pantheon-acl), правило domain для координаторов и мастерской,
привилегии из policy.toml и что прежние правила (dev-server) не сломались.
"""
import json
import os
import subprocess
import sys
import tempfile

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard.py")


def setup(home):
    for d in ("pantheon/directions/athena-broker", "pantheon/directions/hermes-alex/inbox",
              "pantheon/scout", "pantheon-view", ".local/state/pantheon/owner-log", ".claude/pantheon",
              "projects/brokerAssistantApp/app", "projects/alexbroker", "projects/agent-kit",
              "projects/workshop/visa", "knowledge"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    for f in ("pantheon/board.md", "pantheon/alerts.md", "pantheon/decision-map.md",
              "pantheon/directions/hermes-alex/STATUS.md", "pantheon/directions/hermes-alex/inbox/old.md"):
        open(os.path.join(home, f), "w").close()
    json.dump({"domains": {
        "athena-broker": ["~/projects/brokerAssistantApp"],
        "hermes-alex": ["~/projects/alexbroker"],
        "metis-pantheon": ["~/projects/agent-kit"],
        # реестр «по ошибке» отдаёт athena папку agent-kit — привилегий Метиды это не даёт
        "athena-broker-2": ["~/projects/agent-kit/sub"],
    }}, open(os.path.join(home, ".local/state/pantheon/domains.json"), "w"))
    open(os.path.join(home, ".claude/pantheon/policy.toml"), "w").write(
        'always = ["~/.claude/agent-memory"]\n[coordinators]\nmetis-pantheon = ["~/projects/agent-kit"]\n'
        'mnemo-brain = ["~/knowledge"]\n[agent_extra]\nprometheus = ["~/knowledge"]\n')


def run(home, pdir, role, tool, tool_input, sub=False, cwd=None, python=None):
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
             "cwd": os.path.join(home, cwd if cwd is not None else pdir)}
    if role:
        event["agent_type"] = role
    if sub:
        event["agent_id"] = "a1"
    env = {"HOME": home, "PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": os.path.join(home, pdir),
           "TMPDIR": "/nonexistent-tmp"}
    out = subprocess.run([python or sys.executable, "-I", GUARD], input=json.dumps(event), capture_output=True,
                         text=True, env=env, timeout=10).stdout
    return "deny" if '"deny"' in out else "allow"


def main():
    home = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home)
    P = lambda rel: os.path.join(home, "pantheon", rel)
    W = lambda path: ("Write", {"file_path": path, "content": "x"})
    E = lambda path: ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"})
    B = lambda cmd: ("Bash", {"command": cmd})
    br, ak, alex, ws = "projects/brokerAssistantApp", "projects/agent-kit", "projects/alexbroker", "projects/workshop/visa"
    cases = [
        # (имя, ожидание, папка запуска, роль, субагент, (инструмент, вход))
        ("hq пишет доску", "allow", ".", "hq", False, W(P("board.md"))),
        ("субагент не hq — отказ на board.md", "deny", br, "argus", True, W(P("board.md"))),
        ("субагент штаба (chiron) — отказ на board.md", "deny", ".", "chiron", True, E(P("board.md"))),
        ("ваша сессия без роли пишет доску", "allow", ".", "", False, W(P("board.md"))),
        ("координатор пишет свой STATUS.md", "allow", br, "domain-coordinator", False, W(P("directions/athena-broker/STATUS.md"))),
        ("координатор не правит чужой STATUS.md", "deny", br, "domain-coordinator", False, E(P("directions/hermes-alex/STATUS.md"))),
        ("лид создаёт новый файл в чужом inbox/", "allow", br, "hephaestus-broker", True, W(P("directions/hermes-alex/inbox/new.md"))),
        ("лид не переписывает чужой файл в inbox/", "deny", br, "hephaestus-broker", True, W(P("directions/hermes-alex/inbox/old.md"))),
        ("iris не переписывает alerts.md", "deny", ".", "iris", False, W(P("alerts.md"))),
        ("iris дописывает через pantheon alert", "allow", ".", "iris", False, B('pantheon alert "новая версия Claude Code"')),
        ("iris пишет в scout/", "allow", ".", "iris", False, W(P("scout/2026-10-14.md"))),
        ("clio не пишет в scout/", "deny", ".", "clio", False, W(P("scout/x.md"))),
        ("правка в копии — отказ", "deny", br, "domain-coordinator", False, W(os.path.join(home, "pantheon-view/board.md"))),
        ("запись модели в owner-log — отказ", "deny", br, "domain-coordinator", False,
         B(f"echo да >> {home}/.local/state/pantheon/owner-log/athena-broker.md")),
        ("роль не коммитит ~/pantheon", "deny", ".", "hq", False, B(f"git -C {home}/pantheon commit -am x")),
        ("ваша сессия коммитит ~/pantheon", "allow", ".", "", False, B(f"git -C {home}/pantheon commit -am x")),
        ("Метида правит карту решений", "allow", ak, "domain-coordinator", False, E(P("decision-map.md"))),
        ("athena не правит карту решений", "deny", br, "domain-coordinator", False, E(P("decision-map.md"))),
        ("реестр не выдаёт прав Метиды", "deny", ak + "/../brokerAssistantApp", "domain-coordinator", False, E(P("decision-map.md"))),
        ("athena пишет в свой репозиторий", "allow", br, "domain-coordinator", False, W(os.path.join(home, br, "app/x.ts"))),
        ("athena — отказ на запись в alexbroker (SEC-12)", "deny", br, "domain-coordinator", False, W(os.path.join(home, alex, "x.md"))),
        ("мастерская пишет в папку задачи", "allow", ws, "workshop", False, W(os.path.join(home, ws, "form.md"))),
        ("мастерская — отказ вне папки задачи", "deny", ws, "workshop", False, W(os.path.join(home, alex, "x.md"))),
        ("prometheus пишет в ~/knowledge (agent_extra)", "allow", br, "prometheus", True, W(os.path.join(home, "knowledge/raw/a.md"))),
        ("dev-server по-прежнему запрещён", "deny", br, "", False, B("pnpm run dev")),
        # обходы через Bash (ревизия шага 0.3, № 5): роль координатора, cwd = ~/pantheon
        ("Bash: >> alerts.md из ~/pantheon", "deny", br, "domain-coordinator", False, B("echo x >> alerts.md"), "pantheon"),
        ("Bash: sed -i board.md из ~/pantheon", "deny", br, "domain-coordinator", False, B("sed -i '' 's/a/b/' board.md"), "pantheon"),
        ("Bash: cd ~/pantheon && sed -i", "deny", br, "domain-coordinator", False, B(f"cd {home}/pantheon && sed -i '' 's/a/b/' board.md")),
        ("Bash: > \"$HOME/pantheon/board.md\"", "deny", br, "domain-coordinator", False, B('echo x > "$HOME/pantheon/board.md"')),
        ("Bash: tee \"$HOME/…\"", "deny", br, "domain-coordinator", False, B('echo x | tee "$HOME/pantheon/board.md"')),
        ("Bash: mv доски как источника", "deny", br, "domain-coordinator", False, B(f"mv {home}/pantheon/board.md /tmp/b.md")),
        ("Bash: (cd ~/pantheon; git commit)", "deny", br, "domain-coordinator", False, B(f"(cd {home}/pantheon; git commit -am x)")),
        ("Bash: git -C ~/pantheon -c k=v commit", "deny", br, "domain-coordinator", False, B(f"git -C {home}/pantheon -c user.name=x commit -m y")),
        ("Bash: чтение ~/pantheon можно", "allow", br, "domain-coordinator", False, B(f"cat {home}/pantheon/board.md && git -C {home}/pantheon log -1")),
        ("Bash: вывод во временную папку можно", "allow", br, "domain-coordinator", False, B("grep x board.md > /tmp/out.txt 2>&1"), "pantheon"),
        ("Bash: heredoc с > внутри текста — не цель", "allow", br, "domain-coordinator", False,
         B("cat > /tmp/note.md <<'EOF'\nстрелка > ~/pantheon/board.md в тексте\nEOF")),
        # команды пульта (№ 6)
        ("координатор: pantheon archive — отказ", "deny", br, "domain-coordinator", False, B("pantheon archive")),
        ("координатор: pantheon jobs pause --all — отказ", "deny", br, "domain-coordinator", False, B("pantheon jobs pause --all")),
        ("координатор: pantheon jobs и alert можно", "allow", br, "domain-coordinator", False, B("pantheon jobs; pantheon alert 'x' --from athena")),
        ("hq: pantheon archive можно", "allow", ".", "hq", False, B("pantheon archive")),
        ("ваша сессия: pantheon uninstall можно", "allow", ".", "", False, B("pantheon uninstall")),
        # роли отдельной сессией (№ 7)
        ("clio сессией: запись в alexbroker — отказ", "deny", ".", "clio", False, W(os.path.join(home, alex, "x.md"))),
        ("clio сессией: запись в ~/knowledge (agent_extra нет в тестовой политике) — отказ", "deny", ".", "clio", False, W(os.path.join(home, "knowledge/wiki/x.md"))),
        ("prometheus сессией: ~/knowledge по agent_extra", "allow", ".", "prometheus", False, W(os.path.join(home, "knowledge/raw/x.md"))),
        ("iris сессией: policy.toml — отказ", "deny", ".", "iris", False, W(os.path.join(home, ".claude/pantheon/policy.toml"))),
        ("hq пишет в alexbroker (штаб не ограничен domain)", "allow", ".", "hq", False, W(os.path.join(home, alex, "x.md"))),
        ("субагент без agent_type — отказ на board.md (№ 27)", "deny", br, "", True, W(P("board.md"))),
        ("встроенный субагент — тоже под картой прав ~/pantheon", "deny", "pantheon", "general-purpose", True, W(P("handoff/x/r.md"))),
        ("встроенный субагент координатора — отказ на board.md", "deny", br, "general-purpose", True, B("echo x >> ~/pantheon/board.md")),
        # расхождения разбора (проверка безопасности коммитов)
        ("bash -c с записью в ~/pantheon", "deny", br, "domain-coordinator", False, B('bash -c "echo x > ~/pantheon/board.md"')),
        ("eval с записью в ~/pantheon", "deny", br, "domain-coordinator", False, B('eval "echo x > ~/pantheon/board.md"')),
        ("переменная из той же команды", "deny", br, "domain-coordinator", False, B("P=~/pantheon; echo x > $P/board.md")),
        ("шаблон пути ~/pant*on", "deny", br, "domain-coordinator", False, B("echo x > ~/pant*on/board.md")),
        ("$(…) в цели записи — не разобрать", "deny", br, "domain-coordinator", False, B("echo x > $(echo ~/pantheon)/board.md")),
        ("find -delete в ~/pantheon", "deny", br, "domain-coordinator", False, B("find ~/pantheon -name board.md -delete")),
        ("xargs rm — не разобрать", "deny", br, "domain-coordinator", False, B("ls | xargs rm")),
        ("$(…) в тексте коммита — можно", "allow", br, "domain-coordinator", False, B('git commit -m "$(cat /tmp/msg)"')),
        # прежние правила (№ 28)
        ("attribution: пометка Claude в коммите — отказ", "deny", br, "", False,
         B('git commit -m "x\n\nCo-' + 'Authored-By: Claude <noreply@' + 'anthropic.com>"')),
        ("cdp: свой скрипт подключения — отказ", "deny", br, "", False,
         ("Write", {"file_path": os.path.join(home, br, "c.mjs"), "content": "read DevTools" + "ActivePort"})),
        ("tg-secret: чтение ключа tg-read — отказ", "deny", br, "", False,
         B("security find-generic-" + "password -s tg-" + "read -w")),
    ]
    failed = 0
    for case in cases:
        name, want, pdir, role, sub, (tool, ti) = case[:6]
        cwd = case[6] if len(case) > 6 else None
        got = run(home, os.path.normpath(pdir), role, tool, ti, sub, cwd)
        mark = "ok  " if got == want else "FAIL"
        failed += got != want
        print(f"{mark} {name}: {got}")
    # № 1: на системном Python 3.9 (без tomllib) guard не падает и прежние правила работают
    if os.path.exists("/usr/bin/python3"):
        got = run(home, br, "", "Bash", {"command": "pnpm run dev"}, python="/usr/bin/python3")
        ok = got == "deny"
        failed += not ok
        cases.append(None)
        print(f"{'ok  ' if ok else 'FAIL'} системный Python 3.9: dev-server запрещён: {got}")
    print(f"\n{len(cases) - failed} из {len(cases)} прошли")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
