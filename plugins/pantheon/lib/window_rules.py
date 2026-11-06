"""Правила окон Пантеона для слияния через шлюз guard: permissions.allow и autoMode.allow окон координаторов.

Часть ядра защит (metis-0174): шлюз слияния guard (merge_gate.py, CORE_FILES) не даёт агентам слить PR, который
задевает этот файл, — он ждёт слияния владельцем. Правила разрешают окну слияние и запись вердиктов без вопроса
классификатора режима auto, поэтому их правка — правка защит. Модуль без состояния и без ввода-вывода: его грузит
pantheon.py (`pantheon domains build`) по пути файла — python3 -I не кладёт папку скрипта в путь импорта.
"""

import re

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
              ".claude-plugin/marketplace.json")
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
    "`git pull`, `git log`) are routine, not a continuation of an unreviewed merge. PRs that touch the protection "
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


def coordinator_auto_allow(repos):
    """autoMode.allow окна координатора: "$defaults", правило слияния и правило сдачи работы лида (push рабочей ветки,
    argus, night report, gh pr create; metis-0215) по репозиториям направления из [merge_repos] (только вида
    owner/repo; нет таких — обоих правил нет) и правило записей проверок."""
    ok = sorted({r for r in repos if isinstance(r, str) and MERGE_REPO_RE.fullmatch(r)}) if isinstance(repos, list) else []
    names = ", ".join(f"`{r}`" for r in ok)
    gated = [GATED_MERGE_RULE.format(repos=names)] if ok else []
    lead = [LEAD_DELIVERY_RULE.format(repos=names)] if ok else []
    return ["$defaults"] + gated + lead + [REVIEW_RECORD_RULE]


def auto_mode(auto_allow):
    """Раздел autoMode настроек окна координатора: исключения классификатора auto под шлюз слияния."""
    return {"allow": list(auto_allow)}
