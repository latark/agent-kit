#!/usr/bin/env python3
"""guard, часть «protect»: momus (ревизор), сама папка <репо>/.claude как цель записи, цели выше .claude и git clone, hooks/skills/commands проекта, rsync/wget/7z/unzip в .claude (metis-0194), dev-server в worktree.

Общее (подменённый HOME, фикстуры, вызов хука внутри процесса и через процесс, прогон таблицы) — _guard_common.py;
разрез test_guard.py — metis-1148 (план 1.0, Т2).
Запуск: python3 -I plugins/guard/tests/test_guard_protect.py   (код выхода 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _guard_common import *  # noqa: E402, F403


def main():
    home = new_home()
    P, W, E, B, R, G, K, A = helpers(home)
    cases = [
        # (имя, ожидание, папка запуска, роль, субагент, (инструмент, вход)[, папка cwd[, env окна]])
        # --- 0122: momus (ревизор) — только agent_extra, своя память и временное; корней по cwd нет ---
        ("momus с cwd в репозитории: запись в репозиторий — отказ", "deny", br, "momus", True, W(os.path.join(home, br, "app/x.ts"))),
        ("momus с cwd в репозитории: Bash > в репозиторий — отказ", "deny", br, "momus", True, B("echo x > app/y.ts")),
        ("momus пишет в ~/ai/knowledge/Inbox (agent_extra)", "allow", br, "momus", True, W(K("Inbox/x.md"))),
        ("momus: ~/ai/knowledge вне Inbox — отказ", "deny", br, "momus", True, W(K("wiki/x.md"))),
        ("momus: новый файл в чужом inbox/ направления — отказ", "deny", br, "momus", True, W(P("directions/hermes-site/inbox/new.md"))),
        ("momus: Bash в чужой inbox/ — отказ", "deny", br, "momus", True, B(f"echo x > {P('directions/hermes-site/inbox/new.md')}")),
        ("momus: своя память — можно", "allow", br, "momus", True, W(os.path.join(home, ".claude/agent-memory/momus/n.md"))),
        ("momus: память чужой роли — отказ", "deny", br, "momus", True, W(os.path.join(home, ".claude/agent-memory/argus/n.md"))),
        ("momus: временная папка — можно", "allow", br, "momus", True, W("/tmp/momus-x.md")),
        # 0177: главная сессия `--agent momus` — agent_type есть, agent_id нет: те же границы, что у субагента
        ("0177 momus без agent_id: запись в репозиторий — отказ", "deny", br, "momus", False,
         W(os.path.join(home, br, "app/x.ts"))),
        ("0177 momus без agent_id: чужой inbox/ — отказ", "deny", br, "momus", False,
         W(P("directions/apollo-shop/inbox/new.md"))),
        ("0177 momus без agent_id: роль ~/.claude/agents — отказ", "deny", br, "momus", False,
         W(os.path.join(home, ".claude/agents/x.md"))),
        ("0177 momus без agent_id пишет в ~/ai/knowledge/Inbox", "allow", br, "momus", False, W(K("Inbox/y.md"))),
        ("0177 momus без agent_id: временная папка — можно", "allow", br, "momus", False, W("/tmp/momus-y.md")),
        # --- 0142: сама папка <репо>/.claude как цель записи (protect-config) ---
        *[(f"0142 protect-config: {n} — отказ", "deny", br, "dev-sonnet", True, B(c)) for n, c in (
            ("cp -R x .claude/ (относительный)", "cp -R x .claude/"),
            ("cp -R x <репо>/.claude/ (абсолютный)", f"cp -R x {home}/{br}/.claude/"),
            ("mv x .claude", "mv x .claude"),
            ("mv x <репо>/.claude", f"mv x {home}/{br}/.claude"),
            ("tar -xf a.tar -C .claude", "tar -xf a.tar -C .claude"),
            ("tar -xf a.tar -C <репо>/.claude", f"tar -xf a.tar -C {home}/{br}/.claude"),
            ("rsync -a x/ .claude/", "rsync -a x/ .claude/"),
            ("rsync -a x/ <репо>/.claude/", f"rsync -a x/ {home}/{br}/.claude/"),
        )],
        ("0142: запись в .claude/worktrees/x/file.txt — не защита", "allow", br, "dev-sonnet", True,
         W(os.path.join(home, br, ".claude/worktrees/x/file.txt"))),
        ("0142: mkdir .claude — пустая папка, не отказ", "allow", br, "dev-sonnet", True, B("mkdir .claude")),
        ("0142: mkdir -p <репо>/.claude — не отказ", "allow", br, "dev-sonnet", True, B(f"mkdir -p {home}/{br}/.claude")),
        ("0142: mkdir .claude/agents — по-прежнему отказ", "deny", br, "dev-sonnet", True, B("mkdir -p .claude/agents")),
        ("0142: mkdir .claude && cp -R x .claude/ — составная, отказ", "deny", br, "dev-sonnet", True,
         B("mkdir .claude && cp -R x .claude/")),
        # --- 0122: momus в окне направления: вся ветка directions закрыта ---
        ("momus в окне направления: directions/<своё>/x.md — отказ", "deny", ak, "momus", True,
         W(P("directions/metis-pantheon/x.md"))),
        ("momus в окне направления: STATUS.md — отказ", "deny", ak, "momus", True,
         W(P("directions/metis-pantheon/STATUS.md"))),
        ("0142: mkdir -p .claude/worktrees/x — не защита", "allow", br, "dev-sonnet", True, B("mkdir -p .claude/worktrees/x")),
        ("0142: mkdir -p <репо>/.claude/worktrees/x — не защита", "allow", br, "dev-sonnet", True,
         B(f"mkdir -p {home}/{br}/.claude/worktrees/x")),
        # --- 0177: цель выше .claude (дерево в репозиторий или над ним), git clone, hooks/skills/commands проекта ---
        *[(f"0177 protect-config: {n} — отказ", "deny", br, "dev-sonnet", True, B(c)) for n, c in (
            ("tar -xf a.tar -C <репо>", f"tar -xf a.tar -C {home}/{br}"),
            ("tar -xf a.tar в корне репозитория", "tar -xf a.tar"),
            ("cp -R src/.claude <репо>/", f"cp -R src/.claude {home}/{br}/"),
            ("cp -a x <репо>", f"cp -a x {home}/{br}"),
            ("rsync -a src/ <репо>/", f"rsync -a src/ {home}/{br}/"),
            ("ditto src <репо>", f"ditto src {home}/{br}"),
            ("unzip a.zip -d <репо>", f"unzip a.zip -d {home}/{br}"),
            ("cd <репо> && cp -R x ./", f"cd {home}/{br} && cp -R x ./"),
            ("git clone в <репо>/.claude", f"git clone https://github.com/x/y {home}/{br}/.claude"),
            ("git clone -b main в .claude", "git clone -b main https://github.com/x/y .claude"),
            ("git clone x/.claude.git без папки", "git clone https://github.com/x/.claude.git"),
            ("cp -R x <репо>/.claude/skills/", f"cp -R x {home}/{br}/.claude/skills/"),
            ("cp -R x <репо>/.claude/commands/", f"cp -R x {home}/{br}/.claude/commands/"),
            ("cp -R x <репо>/.claude/hooks/", f"cp -R x {home}/{br}/.claude/hooks/"),
            ("cp hooks.sh <репо>/.claude/hooks/pre.sh", f"cp hooks.sh {home}/{br}/.claude/hooks/pre.sh"),
            # предка закрывают распаковщики и копии дерева (ревью argus PR #35)
            ("tar xzf a.tgz (без дефиса) в корне", "tar xzf a.tgz"),
            ("tar --extract --directory=<репо>", f"tar --extract -f a.tar --directory={home}/{br}"),
            ("unzip a.zip в корне", "unzip a.zip"),
            ("unzip a.zip -d<репо> (слитно)", f"unzip a.zip -d{home}/{br}"),
            ("ditto -x -k a.zip <репо>", f"ditto -x -k a.zip {home}/{br}"),
            ("cd <репо> && tar -xf a.tar", f"cd {home}/{br} && tar -xf a.tar"),
            ("rsync -a dir/ . в корне", "rsync -a dir/ ."),
            ("rsync -r dir . в корне", "rsync -r dir ."),
            ("rsync dir/ . (источник-папка) в корне", "rsync dir/ ."),
            ("rsync --archive dir <репо>", f"rsync --archive dir {home}/{br}"),
        )],
        *[(f"0177 protect-config: {n} — не отказ (файл с известным именем)", "allow", br, "dev-sonnet", True, B(c))
          for n, c in (
            ("curl -sSLO в корне репозитория", "curl -sSLO https://example.com/data.json"),
            ("curl -O --output-dir <репо>", f"curl -O --output-dir {home}/{br} https://example.com/data.json"),
            ("wget в корне репозитория", "wget https://example.com/data.json"),
            ("wget -P <репо>", f"wget -P {home}/{br} https://example.com/data.json"),
            ("patch -p1 -i fix.diff в корне", "patch -p1 -i fix.diff"),
            ("rsync a.txt . (один файл)", "rsync a.txt ."),
            ("rsync -v a.txt b.txt <репо>/ (файлы)", f"rsync -v a.txt b.txt {home}/{br}/"),
            ("tar -cf a.tar src в корне (упаковка)", "tar -cf a.tar src"),
        )],
        # папка над репозиториями: субагент без роли из HOME (domain пускает весь HOME — отказ даёт только protect-config)
        ("0177 protect-config: cp -R x ~/projects/ (над репозиториями) — отказ", "deny", ".", "", True,
         B(f"cp -R x {home}/projects/")),
        ("0177 protect-config: tar -xf a.tar -C ~/projects — отказ", "deny", ".", "", True,
         B(f"tar -xf a.tar -C {home}/projects")),
        ("0177 protect-config: tar -xf a.tar -C ~/projects/workshop (не репозиторий) — не отказ", "allow", ".", "", True,
         B(f"tar -xf a.tar -C {home}/projects/workshop")),
        ("0177 protect-config: Write в <репо>/.claude/skills/x/SKILL.md — отказ", "deny", br, "dev-sonnet", True,
         W(os.path.join(home, br, ".claude/skills/x/SKILL.md"))),
        ("0177 protect-config: Write в worktree .claude/worktrees/w/.claude/commands — отказ", "deny", br, "dev-sonnet",
         True, W(os.path.join(home, br, ".claude/worktrees/w/.claude/commands/x.md"))),
        *[(f"0177 protect-config: {n} — не отказ", "allow", br, "dev-sonnet", True, B(c)) for n, c in (
            ("install -d <репо>/.claude", f"install -d {home}/{br}/.claude"),
            ("install -d -m 755 .claude", "install -d -m 755 .claude"),
            ("tar -xf a.tar -C <репо>/app (подпапка)", f"tar -xf a.tar -C {home}/{br}/app"),
            ("cp -R x <репо>/app/", f"cp -R x {home}/{br}/app/"),
            ("cp a.txt <репо>/ (файл, не дерево)", f"cp a.txt {home}/{br}/"),
            ("git clone в подпапку", "git clone https://github.com/x/y app/y"),
            ("git status", "git status"),
            ("git commit в своём репозитории", "git commit -am x"),
        )],
        ("0177 protect-config: install -d .claude/agents — по-прежнему отказ", "deny", br, "dev-sonnet", True,
         B("install -d .claude/agents")),
        # metis-0194: дыры ревью #35, которых на main не было: rsync (-d, «папка/.», -R, --files-from, опция после
        # операндов), wget -r/-m в корень, git checkout/restore поверх .claude, 7z -o, unzip -d в .claude
        *[(f"0194 protect-config: {n} — отказ", "deny", br, "dev-sonnet", True, B(c)) for n, c in (
            ("rsync -d src/. . в корне", "rsync -d src/. ."),
            ("rsync -lptgoD src/. . в корне", "rsync -lptgoD src/. ."),
            ("rsync -a src/ . --exclude x (опция после операндов)", "rsync -a src/ . --exclude x"),
            ("rsync -R .claude/settings.json . в корне", "rsync -R .claude/settings.json ."),
            ("rsync --relative a/.claude/hooks/x.sh . в корне", "rsync --relative a/.claude/hooks/x.sh ."),
            ("rsync --files-from=l src/ . в корне", "rsync --files-from=l src/ ."),
            ("wget -r -nH …/.claude/ в корне", "wget -r -nH https://example.com/.claude/"),
            ("wget -m в корне", "wget -m https://example.com/"),
            ("wget -r -P <репо>/.claude", f"wget -r -P {home}/{br}/.claude https://example.com/"),
            ("git checkout -- .claude/settings.json", "git checkout -- .claude/settings.json"),
            ("git checkout .claude/settings.json (без --)", "git checkout .claude/settings.json"),
            ("git restore -- .claude/hooks/x.py", "git restore -- .claude/hooks/x.py"),
            ("7z x a.7z -o. в корне", "7z x a.7z -o."),
            ("7z x a.7z -o<репо>/.claude", f"7z x a.7z -o{home}/{br}/.claude"),
            ("unzip a.zip -d<репо>/.claude", f"unzip a.zip -d{home}/{br}/.claude"),
            ("unzip -q a.zip в корне (распаковка)", "unzip -q a.zip"),
        )],
        # то же, что разрешено: список, только индекс, ветка, файл внутри репо, подпапка
        *[(f"0194 protect-config: {n} — не отказ", "allow", br, "dev-sonnet", True, B(c)) for n, c in (
            ("unzip -l a.zip в корне (список)", "unzip -l a.zip"),
            ("unzip -t a.zip в корне (проверка)", "unzip -t a.zip"),
            ("unzip -l a.zip -d app (список)", "unzip -l a.zip -d app"),
            ("7z x a.7z -oapp (подпапка)", "7z x a.7z -oapp"),
            ("7z a a.7z src (упаковка)", "7z a a.7z src"),
            ("rsync -a src/ app/ --exclude x (подпапка)", "rsync -a src/ app/ --exclude x"),
            ("rsync -R a.txt app/ (подпапка)", "rsync -R a.txt app/"),
            ("wget -r -P app (подпапка)", "wget -r -P app https://example.com/"),
            ("git restore --staged .claude/settings.json (только индекс)", "git restore --staged .claude/settings.json"),
            ("git checkout -b feature", "git checkout -b feature"),
            ("git checkout -- src/app.ts", "git checkout -- src/app.ts"),
            ("git status", "git status"),
            # решение лида по ревью #204: `.` возвращает только то, что уже в git, — как reset --hard
            ("git checkout -- . в корне", "git checkout -- ."),
            ("git restore . в корне", "git restore ."),
            ("git checkout abc123 -- . в корне", "git checkout abc123 -- ."),
        )],
        # ревью argus #204: после cd (основная форма агентов) — 7z, wget -r/-m от папки cd;
        # rsync с источником «.», «..», «папка/..»; --files-from без косой у источника
        *[(f"0194 protect-config: {n} — отказ", "deny", br, "dev-sonnet", True, B(c), cw) for n, c, cw in (
            ("cd <репо> && 7z x a.7z (из app)", f"cd {home}/{br} && 7z x a.7z", br + "/app"),
            ("cd app && 7z x a.7z -o..", "cd app && 7z x a.7z -o..", br),
            ("cd <репо> && wget -m (из app)", f"cd {home}/{br} && wget -m https://example.com/", br + "/app"),
            ("cd <репо> && wget -r -nH …/.claude/ (из app)", f"cd {home}/{br} && wget -r -nH https://x/.claude/",
             br + "/app"),
            ("cd <репо>/app && cd .. && 7z x a.7z (из worktree)",
             f"cd {home}/{br}/app && cd .. && 7z x a.7z", br + "/.claude/worktrees/agent-1"),
            ("cd <репо> && git checkout -- .claude/settings.json (из app)",
             f"cd {home}/{br} && git checkout -- .claude/settings.json", br + "/app"),
            ("rsync -d . ~/projects/agent-kit", f"rsync -d . {home}/projects/agent-kit", br),
            ("rsync --dirs . ~/projects/agent-kit", f"rsync --dirs . {home}/projects/agent-kit", br),
            ("rsync -d . <репо>/ (из app)", f"rsync -d . {home}/{br}/", br + "/app"),
            ("rsync --dirs . <репо> (из app)", f"rsync --dirs . {home}/{br}", br + "/app"),
            ("rsync -d . .. (из <репо>/app)", "rsync -d . ..", br + "/app"),
            ("rsync -d src/.. . в корне", "rsync -d src/.. .", br),
            ("rsync --files-from=l src . в корне", "rsync --files-from=l src .", br),
        )],
        *[(f"0194 protect-config: {n} — не отказ", "allow", br, "dev-sonnet", True, B(c), br + "/app") for n, c in (
            ("cd <репо>/app && 7z x a.7z (подпапка)", f"cd {home}/{br}/app && 7z x a.7z"),
            ("cd <репо>/app && wget -m (подпапка)", f"cd {home}/{br}/app && wget -m https://example.com/"),
            ("cd <репо> && git checkout -- . (из app)", f"cd {home}/{br} && git checkout -- ."),
            ("cd <репо> && git restore . (из app)", f"cd {home}/{br} && git restore ."),
            ("rsync a.txt . в app (файл)", "rsync a.txt ."),
        )],
        # --- dev-server: исключение для разработчика и talos в worktree (ROLE-23) ---
        ("dev-server: dev-sonnet в worktree — можно", "allow", br, "dev-sonnet", True, B("PORT=4123 pnpm dev"),
         br + "/.claude/worktrees/agent-1"),
        ("dev-server: dev-sonnet вне worktree — можно [sb-simplify]", "allow", br, "dev-sonnet", True, B("pnpm dev")),
        ("dev-server: координатор в worktree — можно [sb-simplify]", "allow", br, "domain-coordinator", False, B("pnpm dev"),
         br + "/.claude/worktrees/agent-1"),
    ]
    failed = run_table(home, cases)
    finish(cases, failed)


if __name__ == "__main__":
    main()
