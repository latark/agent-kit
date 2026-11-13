"""Правила окон Пантеона для слияния через шлюз guard: permissions.allow и autoMode.allow окон координаторов.

Часть ядра защит (metis-0174): шлюз слияния guard (merge_gate.py, CORE_FILES) не даёт агентам слить PR, который
задевает этот файл, — он ждёт слияния владельцем. Правила разрешают окну слияние и запись вердиктов без вопроса
классификатора режима auto, поэтому их правка — правка защит. Модуль без состояния и без ввода-вывода: его грузит
pantheon.py (`pantheon domains build`) по пути файла — python3 -I не кладёт папку скрипта в путь импорта.
"""

import re
import shlex

# permissions.allow окон координаторов — пусто (metis-0137). Раньше здесь стояло Bash(gh pr merge *) (metis-0050), но
# правило allow срабатывает раньше классификатора режима auto, а формы --admin и --auto классификатор не судит: слияние
# в обход запора шло без проверки. Разрешённую форму слияния пропускает autoMode-правило GATED_MERGE_RULE
# (coordinator_auto_allow), а каждое слияние по-прежнему проверяет guard (merge_problem): главная сессия
# domain-coordinator или лид её направления (metis-0054), свои папки, без --admin и --auto. Мастерской и штабу правила нет.
# Но .claude/settings.json проекта папки запуска сливается с --settings окна (флага --setting-sources нет), и allow
# вроде Bash(gh *) в нём возвращает тот же обход: такое окно не собирается (project_allow_problems, sandbox_build),
# `pantheon check` и `direction check` показывают то же предупреждение.
COORDINATOR_ALLOW = []
# Исключения классификатора режима auto окнам координаторов направлений, Метиды в их числе (metis-0098; решения
# владельца 15.10 «Б» и Зевса 16.10 «А»). Классификатор не видит журнал запора guard и считал слияние через запор
# «Merge Without Review», а за ним — и gh pr view, git fetch той же сессии. Правило описывает ровно то, что пускает
# запор guard 0.5.6 (README guard, «Слияние PR»), и ничего сверх: --admin, --auto, слияние без --match-head-commit,
# gh api по-прежнему судит встроенное правило. "$defaults" — встроенные исключения остаются: список без него их
# заменяет (проверено пробой metis-0071). Классификатор читает autoMode из --settings (документация Claude Code,
# auto-mode-config: «--settings flag»), из .claude/settings.json проекта — нет. Штабу и мастерской правил нет.
# Репозитории в правиле слияния — только из [merge_repos] направления в policy.toml (решение владельца 16.10): в тексте
# правил нет имён владельца, направлений и репозиториев, у другой установки правило собирается из её policy.toml.
# LEAD_DELIVERY_RULE (metis-0215) — сдача работы лидом без отказа классификатора; слияние остаётся за Gated Merge.
# Направлению без [merge_repos] правил слияния и сдачи нет: запор guard его слияние и так не пустит.
MERGE_REPO_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9._-]+")
# Ядро защит — те же списки, что CORE_DIR и CORE_FILES шлюза guard (merge_gate.py) и merge.py; совпадение сверяют
# test_window_rules и test_merge. Правило слияния ниже называет их все: прежний неполный список в тексте правила
# расходился с шлюзом (metis-0601, Д3)
CORE_FILES = ("plugins/guard/hooks/merge_gate.py", "plugins/guard/hooks/protect_config.py",
              "plugins/guard/managed-settings.json", "plugins/pantheon/lib/window_rules.py",
              "plugins/pantheon/hooks/ctx.py", "plugins/pantheon/hooks/hooks.json", "plugins/pantheon/lib/merge.py",
              "plugins/pantheon/lib/plugin_map.py", "plugins/pantheon/plugins-by-role.toml",
              "plugins/pantheon/lib/review_rules.py", "plugins/pantheon/lib/answers.py",
              "plugins/pantheon/lib/supabase_migrate.py", ".claude-plugin/marketplace.json")
CORE_DIR = ("plugins/guard", "plugins/pantheon/roles", ".github", "plugins/pantheon/packs")
CORE_TEXT = ("any path under " + ", ".join(f"`{d}/`" for d in CORE_DIR) + ", or one of the files "
             + ", ".join(f"`{f}`" for f in CORE_FILES))
GATED_MERGE_RULE = (
    "Pantheon Gated Merge: In a Pantheon direction window (a coordinator main session or its lead subagent "
    "`hephaestus-*` or `apollo-*`), `gh pr merge <N> --match-head-commit <40-hex sha>` with the repository given "
    "explicitly as `-R <owner/repo>` or `--repo <owner/repo>` (also `-R=`/`--repo=`), optionally with `--merge`, "
    "`--squash` or `--rebase`, `--delete-branch`, `--subject` and `--body`, on one of this direction's repositories "
    "({repos}), is NOT Merge Without Review. The owner replaced human approval with a local "
    "merge gate: the guard PreToolUse hook runs before this classifier and lets the command through only when a "
    "passing project test record exists for that exact head SHA, the independent reviewer role `argus` recorded "
    "«accept» on that exact repository, PR and head SHA with a full checklist of what it opened, what it ran and "
    "what it did not check, the reviewer is not the session that merges, the repository is listed for the "
    "direction, and client products also have a `talos` check and a rollback line in the owner's summary; GitHub "
    "itself rejects the merge if the PR head moved away from `--match-head-commit`. A merge the gate let through is "
    "a reviewed merge: the session's follow-up commands after it (`gh pr view`, `gh pr checks`, `git fetch`, "
    "`git merge`, `git log`) are routine, not a continuation of an unreviewed merge. PRs that touch the protection "
    "core — " + CORE_TEXT + " — wait for the owner to merge them himself: guard refuses them, and this exception "
    "does not cover merging them any other way. It "
    "covers only the command shape above: `--admin`, `--auto`, a merge without `--match-head-commit` or without an "
    "explicit `-R`/`--repo`, a merge through `gh api`, `GH_REPO`/`GH_HOST` overrides, `cd` or chained commands, "
    "or a repository outside this list are still judged by Merge Without Review.")
LEAD_DELIVERY_RULE = (
    "Pantheon Lead Delivery: In a Pantheon direction window (a coordinator main session or its lead subagent "
    "`hephaestus-*` or `apollo-*`), the following steps of the coordinator's written assignment are the delegated "
    "task itself, NOT Auto-Mode Bypass: (1) `git push origin <commit-or-branch>:refs/heads/<branch>` or `git push "
    "origin <branch>` (optionally `-u`) to the `origin` remote of one of this direction's repositories ({repos}), "
    "where <branch> is a work branch and not `main`, `master` or the repository's default branch. It does not "
    "cover `--force`, `-f`, `--force-with-lease`, a `+` refspec, deleting a branch (`--delete`, `:<branch>`), "
    "`--mirror`, `--all`, `--tags`, any other remote or URL, `cd` or chained commands. (2) launching the "
    "independent reviewer subagent `argus` to review that branch or PR; its verdict is recorded only by the guard "
    "hook (see Pantheon Review Record), and the session that launches it cannot record a verdict itself. (3) "
    "`pantheon night report`: a read-only local report of the night budget and alerts; it changes nothing outside "
    "the owner's own Pantheon state. (4) `gh pr create -R <owner/repo> --base <default branch> --head <branch> "
    "--title … --body …` for a branch pushed under (1), on one of this direction's repositories. A merge is still "
    "covered only by Pantheon Gated Merge; anything else is judged by the built-in rules.")
REVIEW_RECORD_RULE = (
    "Pantheon Review Record: `pantheon review test -- <test command>` (runs the project tests in a clean git tree "
    "and reports their exit code), `pantheon review accept|reject <owner/repo> <N> <sha> --opened \"…\" --ran "
    "\"…\" --unchecked \"…\"` run by the reviewer role `argus`, `pantheon review talos <owner/repo> <N> <sha>` run "
    "by the role `talos` and `pantheon review status` are local records of an independent check in the owner's "
    "own agent system — not Self-Approval and not CI Bypass. The record is written by the guard PostToolUse hook "
    "from the hook event's agent type, not by the command; guard refuses a verdict from any other role, an "
    "«accept» without all three checklist fields and a test command that does nothing (`true`, `echo`, `sleep`). "
    "This exception does not cover editing the record file under `~/.local/state/pantheon/merge-gate/` or the "
    "guard plugin. This exception covers only the `pantheon review` recording wrapper itself: the command after "
    "`--` must be the project's own test runner (`heavy <test runner>`, `pytest`, `pnpm test`, `python3 -I tests/…`) and is "
    "judged by every other rule exactly as if it were run on its own. A merge, push, deploy, `gh` or network "
    "command, a file-changing command, an `sh -c`/`python3 -c` one-liner, or anything that checks nothing after "
    "`--` is never a test command and stays Self-Approval or CI Bypass where it fits.")


# Правила autoMode.allow окна направления на команды его репозиториев, которые раньше разрешал permissions.allow
# проекта (metis-0933: окну permissions.allow не даётся). Решение владельца 06.11 21:55 «Б — все восемь»: шесть
# команд чтения mailkeeper, uv sync и git remote. Пакет окна права только сужает — поэтому текст правил здесь, в ядре. Имени
# направления в тексте правил нет (решение 16.10): правило попадает только в окно своего направления. Какому окну какие
# правила — данные пользователя (решение владельца 12.11: у каждого свои направления): раздел [auto_rules]
# ~/.claude/pantheon/policy.toml, «направление = [имена из DIRECTION_RULES]»; правит его, как и другие привилегии,
# только владелец (owner-edit).
MAILKEEPER_READ_RULE = (
    "Pantheon Mailkeeper Read: In this Pantheon direction window, `mailkeeper status`, `mailkeeper rules`, "
    "`mailkeeper scan`, `mailkeeper report`, `mailkeeper plan` and `mailkeeper logs` (with their own options) are the "
    "owner's own local mail-sorting CLI run for the coordinator's task; it runs outside the sandbox by the window's "
    "sandbox.excludedCommands and only reads or plans, it does not move, label or delete mail. It does not cover "
    "`mailkeeper apply`, `undo`, `run`, `auth`, `daemon`, `service`, `on`, `off`, `resume` or `excerpt`, `cd` or "
    "chained commands; those are judged by the built-in rules.")
UV_SYNC_RULE = (
    "Pantheon Uv Sync: In this Pantheon direction window, `uv sync` (optionally with `--frozen`, `--locked`, "
    "`--all-extras`, `--extra <name>`, `--group <name>` or `--dev`) inside one of this direction's repositories installs "
    "the project's own locked dependencies into its `.venv`, as the project's settings allowed before. It does not "
    "cover `uv pip`, `uv add`, `uv remove`, `uv tool`, `uv run`, another index or source URL, `cd` or chained "
    "commands.")
GIT_REMOTE_RULE = (
    "Pantheon Git Remote: In this Pantheon direction window, `git remote` (`-v`, `show`, `get-url`, `add`, "
    "`set-url`, `rename`, `remove`, `prune`, `update`) in one of this direction's repositories is routine repository "
    "upkeep for the coordinator's task, as the project's settings allowed before. It covers only `git remote` itself: "
    "a push, a fetch from a new URL, `cd` or chained commands are judged by the built-in rules.")
DIRECTION_RULES = {"mailkeeper-read": MAILKEEPER_READ_RULE, "uv-sync": UV_SYNC_RULE, "git-remote": GIT_REMOTE_RULE}


def direction_rules(names):
    """Строка [auto_rules] policy.toml → (тексты правил по порядку DIRECTION_RULES, без повторов; [неизвестные или
    кривые записи]). Не список — ничего (окно без правил направления), кривое — названо, а не взято."""
    if names is None:
        return [], []
    if not isinstance(names, list):
        return [], [repr(names)]
    bad = [repr(n) for n in names if not isinstance(n, str) or n not in DIRECTION_RULES]
    return [r for k, r in DIRECTION_RULES.items() if k in names], bad


def coordinator_auto_allow(repos, rules=None):
    """autoMode.allow окна координатора: "$defaults", правило слияния и правило сдачи работы лида (push рабочей ветки,
    argus, night report, gh pr create; metis-0215) по репозиториям направления из [merge_repos] (только вида
    owner/repo; нет таких — обоих правил нет), правила направления — имена DIRECTION_RULES из его строки [auto_rules]
    policy.toml (metis-0933; direction_rules) — и правило записей проверок."""
    ok = sorted({r for r in repos if isinstance(r, str) and MERGE_REPO_RE.fullmatch(r)}) if isinstance(repos, list) else []
    names = ", ".join(f"`{r}`" for r in ok)
    gated = [GATED_MERGE_RULE.format(repos=names)] if ok else []
    lead = [LEAD_DELIVERY_RULE.format(repos=names)] if ok else []
    return ["$defaults"] + gated + lead + direction_rules(rules)[0] + [REVIEW_RECORD_RULE]


def auto_mode(auto_allow):
    """Раздел autoMode настроек окна координатора: исключения классификатора auto под шлюз слияния."""
    return {"allow": list(auto_allow)}


# Пакет окна направления (~/.claude/pantheon/packs/<направление>, metis-0933) — данные пользователя, а его хуки и
# серверы MCP идут вне песочницы окна. Поэтому ядро берёт плагин и mcp.json пакета в окно, только если они такого вида
# (ревью argus #425 Б1, Б2 и проверка безопасности #425): хук — prompt или команда, которую shlex разбирает целиком:
# без ; & | ` ( ) < >, перевода строки, { } * ? [ ] ~ # \ ! (metis-1101) и $ кроме $HOME, ${HOME} и
# ${CLAUDE_PLUGIN_ROOT}; это in_repo.py пакета (скрипт репозитория по эталону хеша), до его «--» — репозиторий и только
# флаги обёртки, а за «--» — только bash .claude/hooks/<имя>, python3 -I .claude/hooks/<имя> или
# python3 -I ${CLAUDE_PLUGIN_ROOT}/../_bin/<имя>.py (pack_hook_problem). Сервер MCP — только через env_from.py пакета, а
# за его «--» — только npx -y <пакет>@x.y.z: программа по пути вне песочницы окна исполнила бы и скрипт или бинарь из
# папки, которую окно пишет; http, sse и ws — без headersHelper. Поля plugin.json, которые сами запускают код мимо
# hooks.json, запрещены. Нарушение в mcp.json — MCP пакета в окно не идёт, в плагине — ни плагин, ни MCP; строка в
# alerts.md (pantheon.pack_admit).
PACK_BIN_MARK = "${PANTHEON_PACK_BIN}"
PACK_HOOK_BIN = "${CLAUDE_PLUGIN_ROOT}/../_bin/"
PACK_HOOK_LEAD = ["python3", "-I", PACK_HOOK_BIN + "in_repo.py"]
# знаки оболочки, которые цепляют вторую команду, подставляют вывод или перенаправляют, и $ кроме трёх переменных;
# и те, что /bin/sh разворачивает или режет иначе, чем shlex (metis-1101, ревью #425 Д1): скобки {a,b} и глоб * ? [ ]
# превращают одно слово в несколько ({--,bash,-c,…} — свой «--» до настоящего), ~ — в путь, # — начало комментария,
# \ и ! — экранирование и история. Три разрешённые переменные вырезаются до поиска (PACK_HOOK_VARS): их { } — не знак
PACK_HOOK_VARS = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}|\$\{HOME\}|\$HOME(?![A-Za-z0-9_])")
PACK_HOOK_META = re.compile(r"[;&|`()<>\n\r{}*?\[\]~#\\!$]")
# что in_repo.py принимает до «--» после репозитория (его шапка); другое слово там — не флаг обёртки, а подложенный
# аргумент: отказ
PACK_HOOK_FLAG = re.compile(r"--(?:always|file-arg|ok|cmd-prefix=[^\n]+|plain=[A-Za-z0-9_.,/-]+)")
PACK_HOOK_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")  # одно имя файла: без /, не с точки (не ..)
# что разрешено за «--» in_repo.py: (начало, папка скрипта, окончание имени)
PACK_HOOK_RUN = ((["bash"], ".claude/hooks/", ""), (["python3", "-I"], ".claude/hooks/", ""),
                 (["python3", "-I"], PACK_HOOK_BIN, ".py"))
PACK_MCP_PREFIX = ["-I", PACK_BIN_MARK + "/env_from.py"]
PACK_MANIFEST_EXEC = ("hooks", "mcpServers", "lspServers")
PACK_STDIO_KEYS = {"type", "command", "args", "env"}
PACK_REMOTE_KEYS = {"type", "url", "headers"}
PACK_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
# переменные, которые меняют, что и откуда запустится, — не из пакета
PACK_ENV_DENY = re.compile(r"PATH|HOME|TMPDIR|SHELL|ENV|BASH_ENV|ZDOTDIR|DYLD_.*|LD_.*|NODE_.*|NPM_CONFIG_.*|PYTHON.*"
                           r"|.*_PROXY|GUARD_.*|ANTHROPIC_.*|CLAUDE.*")
NPX_PINNED = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*@\d+\.\d+\.\d+")


def pack_problems(manifest, hooks, mcp):
    """Нарушения пакета окна (см. выше) → [причина]. manifest, hooks, mcp — разобранные plugin.json, hooks/hooks.json
    и mcp.json пакета; None — файла нет."""
    out = []
    if manifest is not None:
        if not isinstance(manifest, dict):
            out.append("plugin.json: не объект JSON")
        else:
            out += [f"plugin.json: поле {k} запускает код мимо hooks.json" for k in PACK_MANIFEST_EXEC if k in manifest]
    if hooks is not None:
        events = hooks.get("hooks") if isinstance(hooks, dict) else None
        if not isinstance(events, dict):
            out.append("hooks.json: нет объекта hooks")
        for ev, groups in (events.items() if isinstance(events, dict) else ()):
            for g in groups if isinstance(groups, list) else [None]:
                hs = g.get("hooks") if isinstance(g, dict) else None
                for h in hs if isinstance(hs, list) else [None]:
                    kind = h.get("type") if isinstance(h, dict) else None
                    cmd = h.get("command") if kind == "command" else None
                    why = "не command и не prompt" if kind not in ("command", "prompt") else (
                        pack_hook_problem(cmd) if kind == "command" else None)
                    if why:
                        out.append(f"hooks.json {ev}: {why} — {str(cmd or kind)[:160]}")
    if mcp is not None:
        servers = mcp.get("mcpServers") if isinstance(mcp, dict) else None
        if not isinstance(servers, dict):
            out.append("mcp.json: нет объекта mcpServers")
        for n, s in (servers.items() if isinstance(servers, dict) else ()):
            why = pack_server_problem(s)
            if why:
                out.append(f"mcp.json {n}: {why}")
    return out


def pack_server_problem(s):
    """Причина, по которой сервер MCP пакета s не годится (см. выше), или None."""
    if not isinstance(s, dict):
        return "не объект JSON"
    if "command" not in s:
        if s.get("type") in ("http", "sse", "ws") and isinstance(s.get("url"), str) and set(s) <= PACK_REMOTE_KEYS:
            return None
        return f"удалённый сервер — только type http, sse или ws, url и headers; есть {sorted(s)}"
    args, env = s.get("args"), s.get("env") or {}
    if set(s) - PACK_STDIO_KEYS or s.get("type", "stdio") != "stdio":
        return f"лишние поля {sorted(set(s) - PACK_STDIO_KEYS) or s.get('type')}"
    if not isinstance(env, dict) or [k for k, v in env.items() if not isinstance(v, str)
                                     or not PACK_ENV_NAME.fullmatch(k) or PACK_ENV_DENY.fullmatch(k)]:
        return f"env — только свои имена, без PATH, HOME, NODE_*, PYTHON* и подобных: {env}"[:200]
    if (s["command"] != "python3" or not isinstance(args, list) or args[:2] != PACK_MCP_PREFIX or "--" not in args
            or not all(isinstance(a, str) for a in args)):
        return f"не через env_from.py пакета (python3 -I {PACK_BIN_MARK}/env_from.py … -- <команда>): {s['command']} {args}"[:240]
    run = args[args.index("--") + 1:]
    if run[:2] == ["npx", "-y"] and len(run) > 2 and NPX_PINNED.fullmatch(run[2]):
        return None
    return f"за «--» — только `npx -y <пакет>@x.y.z`: {' '.join(run)[:160] or 'пусто'}"


def pack_hook_problem(cmd):
    """Причина, по которой команда хука пакета cmd не годится (см. выше), или None."""
    if not isinstance(cmd, str):
        return "нет строки command"
    bad = PACK_HOOK_META.search(PACK_HOOK_VARS.sub("", cmd))
    if bad:
        return (f"знак оболочки {bad.group()!r}: хук — одна команда без цепочек, подстановок, перенаправлений, скобок "
                "и глоба")
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return "строку не разобрать (кавычки)"
    if argv[:3] != PACK_HOOK_LEAD or "--" not in argv:
        return f"хук не через in_repo.py пакета (python3 -I \"{PACK_HOOK_BIN}in_repo.py\" … -- <скрипт>)"
    cut = argv.index("--")
    # argv[3] — репозиторий («--» на его месте — тоже отказ), дальше до «--» — только флаги in_repo.py
    if argv[3].startswith("-") or not all(PACK_HOOK_FLAG.fullmatch(f) for f in argv[4:cut]):
        return ("до «--» — репозиторий и только флаги in_repo.py: --always, --file-arg, --ok, --cmd-prefix=…, "
                "--plain=<папки>")
    run = argv[cut + 1:]
    for lead, folder, ext in PACK_HOOK_RUN:
        n = len(lead)
        if run[:n] == lead and len(run) > n and run[n].startswith(folder):
            name = run[n][len(folder):]
            if PACK_HOOK_NAME.fullmatch(name) and name.endswith(ext):
                return None
    return ("за «--» — только bash .claude/hooks/<имя>, python3 -I .claude/hooks/<имя> или "
            f"python3 -I {PACK_HOOK_BIN}<имя>.py")
