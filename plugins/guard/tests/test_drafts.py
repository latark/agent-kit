#!/usr/bin/env python3
"""Исполнитель без кода palamedes в guard (metis-0469): пишет только черновики.

Запуск: python3 -I plugins/guard/tests/test_drafts.py   (код выхода 0 — все прошли)

Проверяет (обвязка и HOME во временной папке — из test_guard.py):
  - draft-role: из инструментов guard palamedes открыты только Read, Grep, Glob, Write, Edit, MultiEdit;
    Bash, NotebookEdit, WebFetch, Agent, Task, Skill — отказ, и у главной сессии `--agent palamedes` (без agent_id);
  - pantheon-acl: запись только в directions/<своё направление>/drafts/** — в окне координатора по папке запуска,
    в окне Пританея (PANTHEON_ROLE=hq) — в drafts/ любого направления из domains.json, но не в inbox/ и STATUS.md;
  - обходы: drafts/../STATUS.md, симлинк из drafts наружу и симлинк самой drafts, регистр и Юникод (NFD, кириллица
    вместо латиницы), путь drafts как файл, drafts не на третьем месте пути;
  - domain: код проектов, ~/ai/knowledge, ~/.claude, память, временные папки — отказ, agent_extra из policy.toml не
    открывает ничего;
  - вторая линия без draft-role (GUARD_OFF=draft-role): Bash и NotebookEdit в drafts/ — всё равно отказ.
"""
import importlib.util
import os
import sys
import tempfile
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("guard_tests", os.path.join(HERE, "test_guard.py"))
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)  # временная корневая папка и её уборка — из test_guard.py (atexit)

IS_MAC = sys.platform == "darwin"
ROLE = "palamedes"


def main():
    home = os.path.realpath(tempfile.mkdtemp(prefix="guard-drafts-"))
    T.setup(home)
    pol = os.path.join(home, ".claude/pantheon/policy.toml")
    text = T._read(pol)
    marker = 'momus = ["~/ai/knowledge/Inbox"]\n'
    assert marker in text
    # agent_extra у palamedes не должен открывать ничего (metis-0469): ни знания, ни код
    with open(pol, "w") as fh:
        fh.write(text.replace(marker, marker + 'palamedes = ["~/ai/knowledge/Inbox", "~/projects/shopKeeperApp"]\n'))
    P = lambda rel: os.path.join(home, "ai", "pantheon", rel)
    K = lambda rel: os.path.join(home, "ai", "knowledge", rel)
    D = lambda name, rel="": P(f"directions/{name}/drafts" + (f"/{rel}" if rel else ""))
    W = lambda path: ("Write", {"file_path": path, "content": "x"})
    E = lambda path: ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"})
    M = lambda path: ("MultiEdit", {"file_path": path, "edits": [{"old_string": "a", "new_string": "b"}]})
    N = lambda path: ("NotebookEdit", {"notebook_path": path, "new_source": "x"})
    B = lambda cmd: ("Bash", {"command": cmd})
    R = lambda path: ("Read", {"file_path": path})
    G = lambda path: ("Grep", {"pattern": "x", "path": path})
    GL = lambda path: ("Glob", {"pattern": "*.md", "path": path})
    HQ = {"PANTHEON_ROLE": "hq"}
    CO = {"PANTHEON_ROLE": "athena-shop"}  # окно координатора: PANTHEON_ROLE — имя направления
    OFF = {"GUARD_OFF": "draft-role"}
    br, ak, ws, hqdir = "projects/shopKeeperApp", "projects/agent-kit", "projects/workshop/visa", "ai/pantheon"

    # фикстуры: свой drafts/ с симлинками наружу, drafts/ Метиды — симлинк на её репозиторий
    os.makedirs(D("athena-shop", "sub"), exist_ok=True)
    open(P("directions/athena-shop/STATUS.md"), "w").close()
    open(D("athena-shop", "c-1.md"), "w").close()
    os.symlink(os.path.join(home, br), D("athena-shop", "out"))
    os.symlink("../STATUS.md", D("athena-shop", "status-link.md"))
    os.symlink(K(""), D("athena-shop", "kn"))
    os.symlink(P("directions/hermes-site/inbox"), D("athena-shop", "inbox-link"))
    os.symlink(os.path.join(home, ak), P("directions/metis-pantheon/drafts"))

    nfd = unicodedata.normalize("NFD", "разбор-йод.md")  # «й» разложенной формой, как его пишет Finder
    lookalike = "drаfts"  # «а» кириллицей: другое имя и для macOS
    upper = "allow" if IS_MAC else "deny"  # на macOS DRAFTS — та же папка drafts (файловая система без регистра)

    cases = [
        # --- можно: свой черновик (субагент в окне координатора и без окна) ---
        ("Write в свой drafts/", "allow", br, True, W(D("athena-shop", "c-2.md"))),
        ("Edit своего черновика", "allow", br, True, E(D("athena-shop", "c-1.md"))),
        ("MultiEdit своего черновика", "allow", br, True, M(D("athena-shop", "c-1.md"))),
        ("Write в подпапку drafts/sub/", "allow", br, True, W(D("athena-shop", "sub/y.md"))),
        ("Write в новую подпапку drafts/a/b/", "allow", br, True, W(D("athena-shop", "a/b/z.md"))),
        ("окно координатора: свой drafts/", "allow", br, True, W(D("athena-shop", "c-3.md")), None, CO),
        ("NFD-имя файла в drafts/", "allow", br, True, W(D("athena-shop", nfd))),
        ("регистр: DRAFTS/x.md (macOS — та же папка)", upper, br, True, W(P("directions/athena-shop/DRAFTS/x.md"))),
        ("регистр: имя направления ATHENA-SHOP (macOS — та же папка)", upper, br, True,
         W(P("directions/ATHENA-SHOP/drafts/x.md"))),
        ("Read файла направления", "allow", br, True, R(P("directions/hermes-site/STATUS.md"))),
        ("Grep по направлению", "allow", br, True, G(P("directions/hermes-site"))),
        ("Glob по drafts/", "allow", br, True, GL(D("athena-shop"))),
        ("Read кода проекта", "allow", br, True, R(os.path.join(home, br, "app/x.ts"))),
        # --- главная сессия `--agent palamedes` (agent_type есть, agent_id нет) ---
        ("без agent_id: свой drafts/", "allow", br, False, W(D("athena-shop", "m-1.md"))),
        ("без agent_id: запись в репозиторий — отказ", "deny", br, False, W(os.path.join(home, br, "app/x.ts"))),
        ("без agent_id: свой STATUS.md — отказ", "deny", br, False, W(P("directions/athena-shop/STATUS.md"))),
        ("без agent_id: чужой inbox/ — отказ", "deny", br, False, W(P("directions/hermes-site/inbox/new.md"))),
        ("без agent_id: ~/ai/knowledge — отказ", "deny", br, False, W(K("Inbox/x.md"))),
        ("без agent_id: роль в ~/.claude/agents — отказ", "deny", br, False,
         W(os.path.join(home, ".claude/agents/palamedes.md"))),
        ("без agent_id: Bash — отказ", "deny", br, False, B("ls")),
        ("без agent_id: Agent — отказ", "deny", br, False, ("Agent", {"subagent_type": "Explore", "prompt": "x"})),
        ("без agent_id: временная папка — отказ", "deny", br, False, W("/tmp/pal-x.md")),
        # --- обходы пути ---
        ("drafts/../STATUS.md — отказ", "deny", br, True, W(D("athena-shop", "../STATUS.md"))),
        ("drafts/../../hermes-site/drafts/x.md — отказ", "deny", br, True,
         W(D("athena-shop", "../../hermes-site/drafts/x.md"))),
        ("drafts/../../../board.md — отказ", "deny", br, True, W(D("athena-shop", "../../../board.md"))),
        ("симлинк drafts/out → репозиторий — отказ", "deny", br, True, W(D("athena-shop", "out/app/x.ts"))),
        ("симлинк drafts/status-link.md → ../STATUS.md — отказ", "deny", br, True,
         E(D("athena-shop", "status-link.md"))),
        ("симлинк drafts/kn → ~/ai/knowledge — отказ", "deny", br, True, W(D("athena-shop", "kn/wiki/x.md"))),
        ("симлинк drafts/inbox-link → чужой inbox/ — отказ", "deny", br, True,
         W(D("athena-shop", "inbox-link/new.md"))),
        ("симлинк самой drafts/ Метиды → репозиторий — отказ", "deny", ak, True, W(D("metis-pantheon", "x.py"))),
        ("путь drafts как файл — отказ", "deny", br, True, W(D("athena-shop"))),
        ("drafts.md рядом с drafts/ — отказ", "deny", br, True, W(P("directions/athena-shop/drafts.md"))),
        ("кириллица вместо латиницы в drafts — отказ", "deny", br, True,
         W(P(f"directions/athena-shop/{lookalike}/x.md"))),
        ("регистр: STATUS.MD — отказ", "deny", br, True, W(P("directions/athena-shop/STATUS.MD"))),
        ("регистр: INBOX/x.md — отказ", "deny", br, True, W(P("directions/athena-shop/INBOX/x.md"))),
        ("drafts не на третьем месте: handoff/athena-shop/drafts/x.md — отказ", "deny", br, True,
         W(P("handoff/athena-shop/drafts/x.md"))),
        ("drafts глубже: directions/athena-shop/plans/drafts/x.md — отказ", "deny", br, True,
         W(P("directions/athena-shop/plans/drafts/x.md"))),
        # --- остальная папка направления и ~/ai/pantheon ---
        ("свой STATUS.md — отказ", "deny", br, True, W(P("directions/athena-shop/STATUS.md"))),
        ("свой inbox/x.md — отказ", "deny", br, True, W(P("directions/athena-shop/inbox/x.md"))),
        ("свой inbox/ во вложенной папке — отказ", "deny", br, True, W(P("directions/athena-shop/inbox/a/x.md"))),
        ("свой tasks/x.md — отказ", "deny", br, True, W(P("directions/athena-shop/tasks/x.md"))),
        ("свой GOALS.md — отказ", "deny", br, True, W(P("directions/athena-shop/GOALS.md"))),
        ("свой файл в корне направления — отказ", "deny", br, True, W(P("directions/athena-shop/notes.md"))),
        ("чужой drafts/ из окна координатора — отказ", "deny", br, True, W(D("hermes-site", "x.md")), None, CO),
        ("чужой drafts/ без окна — отказ", "deny", br, True, W(D("hermes-site", "x.md"))),
        ("чужой inbox/ новый файл — отказ", "deny", br, True, W(P("directions/hermes-site/inbox/new.md"))),
        ("чужой STATUS.md — отказ", "deny", br, True, E(P("directions/hermes-site/STATUS.md"))),
        ("board.md — отказ", "deny", br, True, W(P("board.md"))),
        ("system.md — отказ", "deny", br, True, W(P("system.md"))),
        ("входящие владельца inbox/x.md — отказ", "deny", br, True, W(P("inbox/x.md"))),
        ("~/ai/pantheon-view — отказ", "deny", br, True, W(os.path.join(home, "ai/pantheon-view/x.md"))),
        ("папка запуска вне направлений: drafts/ — отказ", "deny", ws, True, W(D("athena-shop", "x.md"))),
        # --- окно Пританея ---
        ("окно Пританея: drafts/ направления hermes-site", "allow", hqdir, True, W(D("hermes-site", "z-1.md")), None, HQ),
        ("окно Пританея: drafts/ направления athena-shop", "allow", hqdir, True, W(D("athena-shop", "z-2.md")), None, HQ),
        ("окно Пританея: inbox/ направления — отказ", "deny", hqdir, True,
         W(P("directions/hermes-site/inbox/new.md")), None, HQ),
        ("окно Пританея: STATUS.md направления — отказ", "deny", hqdir, True,
         W(P("directions/hermes-site/STATUS.md")), None, HQ),
        ("окно Пританея: drafts/ направления не из реестра — отказ", "deny", hqdir, True,
         W(D("no-such-dir", "x.md")), None, HQ),
        ("окно Пританея: board.md — отказ", "deny", hqdir, True, W(P("board.md")), None, HQ),
        ("окно Пританея: входящие владельца — отказ", "deny", hqdir, True, W(P("inbox/x.md")), None, HQ),
        ("окно Пританея: симлинк drafts/ Метиды — отказ", "deny", hqdir, True, W(D("metis-pantheon", "x.md")), None, HQ),
        ("окно Пританея: ~/ai/knowledge — отказ", "deny", hqdir, True, W(K("x.md")), None, HQ),
        ("окно Пританея: Bash — отказ", "deny", hqdir, True, B("ls"), None, HQ),
        ("окно Пританея без agent_id: drafts/", "allow", hqdir, False, W(D("hermes-site", "z-3.md")), None, HQ),
        # --- domain: вне ~/ai/pantheon ничего ---
        ("код проекта (cwd в репозитории) — отказ", "deny", br, True, W(os.path.join(home, br, "app/x.ts"))),
        ("guard.py из окна metis-pantheon — отказ", "deny", ak, True,
         E(os.path.join(home, ak, "plugins/guard/hooks/guard.py"))),
        ("~/ai/knowledge/Inbox (agent_extra в policy) — отказ", "deny", br, True, W(K("Inbox/x.md"))),
        ("~/ai/knowledge/wiki — отказ", "deny", br, True, W(K("wiki/x.md"))),
        ("~/.claude/agents/palamedes.md — отказ", "deny", br, True,
         W(os.path.join(home, ".claude/agents/palamedes.md"))),
        ("~/.claude/pantheon/policy.toml — отказ", "deny", br, True, E(pol)),
        ("своя память agent-memory/palamedes — отказ", "deny", br, True,
         W(os.path.join(home, ".claude/agent-memory/palamedes/n.md"))),
        ("временная папка — отказ", "deny", br, True, W("/tmp/pal-x.md")),
        # --- инструменты (draft-role) ---
        ("MultiEdit чужого STATUS.md — отказ", "deny", br, True, M(P("directions/hermes-site/STATUS.md"))),
        ("NotebookEdit в drafts/ — отказ", "deny", br, True, N(D("athena-shop", "x.ipynb"))),
        ("NotebookEdit в репозиторий — отказ", "deny", br, True, N(os.path.join(home, br, "x.ipynb"))),
        ("Bash echo > drafts/x.md — отказ", "deny", br, True, B(f"echo x > {D('athena-shop', 'x.md')}")),
        ("Bash tee в репозиторий — отказ", "deny", br, True, B("echo x | tee app/y.ts")),
        ("Bash cp в STATUS.md — отказ", "deny", br, True, B(f"cp a.md {P('directions/athena-shop/STATUS.md')}")),
        ("Bash python -c с записью — отказ", "deny", br, True, B("python3 -c \"open('x','w').write('1')\"")),
        ("Bash ls (без записи) — отказ", "deny", br, True, B("ls")),
        ("Bash git status — отказ", "deny", br, True, B("git status")),
        ("WebFetch — отказ", "deny", br, True, ("WebFetch", {"url": "https://example.com", "prompt": "x"})),
        ("Agent — отказ", "deny", br, True, ("Agent", {"subagent_type": "general-purpose", "prompt": "x"})),
        ("Task — отказ", "deny", br, True, ("Task", {"subagent_type": "Explore", "prompt": "x"})),
        ("Skill — отказ", "deny", br, True, ("Skill", {"skill": "research"})),
        # --- личное: уже закрыто private, держится и для palamedes ---
        ("Read me/ — отказ", "deny", br, True, R(K("me/finance.md"))),
        ("без agent_id: Grep по me/ — отказ", "deny", br, False, G(K("me"))),
        # --- вторая линия: draft-role выключен — Bash и NotebookEdit в drafts/ всё равно не пишут ---
        ("без draft-role: Bash > drafts/x.md — отказ", "deny", br, True, B(f"echo x > {D('athena-shop', 'x.md')}"),
         None, OFF),
        ("без draft-role: NotebookEdit в drafts/ — отказ", "deny", br, True, N(D("athena-shop", "x.ipynb")), None, OFF),
        ("без draft-role: Bash > в репозиторий — отказ", "deny", br, True, B("echo x > app/y.ts"), None, OFF),
        ("без draft-role: Write в свой drafts/ — можно", "allow", br, True, W(D("athena-shop", "c-4.md")), None, OFF),
        # --- соседи не задеты: momus и dev-sonnet ---
        ("dev-sonnet: свой STATUS.md — как было, можно", "allow", br, True, W(P("directions/athena-shop/STATUS.md")),
         None, None, "dev-sonnet"),
        ("dev-sonnet: Bash ls — как было, можно", "allow", br, True, B("ls"), None, None, "dev-sonnet"),
        ("momus: drafts/ — как было, отказ", "deny", br, True, W(D("athena-shop", "x.md")), None, None, "momus"),
    ]
    failed = 0
    for case in cases:
        name, want, pdir, sub, (tool, ti) = case[:5]
        cwd = case[5] if len(case) > 5 else None
        penv = case[6] if len(case) > 6 else None
        role = case[7] if len(case) > 7 else ROLE
        got = T.run(home, os.path.normpath(pdir), role, tool, ti, sub, cwd, penv=penv)
        failed += got != want
        print(f"{'ok  ' if got == want else 'FAIL'} {name}: {got}")

    def raw_check(name, cond):
        nonlocal failed
        failed += not cond
        print(f"{'ok  ' if cond else 'FAIL'} {name}")

    # тексты отказов: правило названо, проверка не упала (а не «сбой проверки прав»)
    out = T.run(home, br, ROLE, "Bash", {"command": "ls"}, True, raw=True)
    raw_check("текст: Bash — правило draft-role", "Правило draft-role" in out and "Bash" in out)
    out = T.run(home, br, ROLE, *N(D("athena-shop", "x.ipynb")), True, raw=True)
    raw_check("текст: NotebookEdit в drafts/ — draft-role, а не pantheon-acl", "Правило draft-role" in out)
    out = T.run(home, br, ROLE, *W(P("directions/athena-shop/STATUS.md")), True, raw=True)
    raw_check("текст: STATUS.md — pantheon-acl про drafts/", "Правило pantheon-acl" in out and "drafts/" in out)
    out = T.run(home, br, ROLE, *W(os.path.join(home, br, "app/x.ts")), True, raw=True)
    raw_check("текст: код — domain про черновики", "Правило domain" in out and "только черновики" in out)
    out = T.run(home, ws, ROLE, *W(D("athena-shop", "x.md")), True, raw=True)
    raw_check("папка вне направлений: отказ правилом, а не сбоем", "Правило pantheon-acl" in out and "сбой" not in out)
    out = T.run(home, br, ROLE, *W(D("athena-shop", "c-5.md")), True, raw=True)
    raw_check("свой черновик: пусто в выводе, код 0", out.strip() == "")

    total = len(cases) + 6
    print(f"\n{total - failed} из {total} прошли")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
