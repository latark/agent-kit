#!/usr/bin/env python3
"""Общая часть синтетических тестов guard: подменённый HOME во временной папке, события PreToolUse хуку.

Части (разрез test_guard.py, metis-1148, план 1.0 Т2: целый файл шёл 160–220 с локально и до 720 с под нагрузкой):
test_guard_{acl,roles,cdp,merge,protect,hooks}.py — карта прав ~/ai/pantheon (pantheon-acl), правило domain для
координаторов и мастерской, привилегии из policy.toml, protect-config, слияние, входы хука и сбои. Каждая часть
запускается сама: python3 -I plugins/guard/tests/test_guard_<часть>.py   (код 0 — все прошли)

Здесь — фикстуры HOME (setup, gate_fixtures, write_zeus, merge_fixtures), run() — решение guard по событию, прогон
таблицы случаев (run_table) и итог части (finish). Этим же пользуются test_drafts.py и pantheon/test_coord_switch.py.

Вызов хука (metis-1148, Т3): решение guard — внутри процесса теста (_guard_inproc.call: правила загружены один раз,
каждый вызов — fork со своим HOME, окружением и аргументами), а не новый интерпретатор на случай (1,3–1,8 с). Настоящий
процесс (`python3 -I _guard_shim.py guard.py`) — run(..., proc=True) и hook(..., proc=True): первый случай каждой
таблицы и входы хука в test_guard_hooks.py (режимы plugin, --managed, --strict; PreToolUse, PostToolUse, Stop; сбой
загрузки; старый Python).
"""
import atexit as _atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _guard_inproc import call  # noqa: E402  (metis-1148)
from _par import run_cases  # noqa: E402  (metis-0544)
from _py311 import mkroot  # noqa: E402  (metis-0729)

# Срок подпроцессов теста: на нагруженном Mac (проход outside, -j3, load 11-20) 10-30 с не хватает (metis-0634).
# Срок самого guard (DEADLINE) это не меняет и им не проверяется.
SUB_TIMEOUT = 60
# Все временные папки части — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение);
# TMPDIR — для подпроцессов, которые тоже создают временные папки. Общий TMPDIR остаётся чистым. Корень — mkroot:
# тесты делают git init, а в окне роли под TMPDIR песочница его режет (metis-0941).
_ROOT = mkroot("guard-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(shutil.rmtree, _ROOT, True)

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard.py")
RULES = os.path.join(os.path.dirname(GUARD), "guard_rules.py")  # правила; guard.py — короткий вход (metis-0148)
SHIM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_guard_shim.py")  # запуск guard без зависимости от места тестов
# папки и окна случаев (как в прежнем main() test_guard.py)
HQ = {"PANTHEON_ROLE": "hq"}  # env окна штаба (pantheon start zeus), guard 0.5.5
HS = {"PANTHEON_ROLE": "hestia"}  # env окна Гестии (pantheon wake hestia --task, metis-0245)
TL = {"PANTHEON_ROLE": "themis-library"}  # env окна координатора (tg-role, metis-0267)
TGR = "tg_read" + ".py"  # имя скрипта tg-read: так этот файл не задевает правило tg-secret живого хука
br, ak, alex, ws = "projects/shopKeeperApp", "projects/agent-kit", "projects/sitebuilder", "projects/workshop/visa"
ec, lw = "projects/lecture-notes", "projects/law-feed"


# имена корпуса для corpus-role — только из [corpus] policy.toml (metis-0182); здесь выдуманный корпус lecture-notes
CORPUS_SECTION = (
    '[corpus]\ncommands = ["corpus"]\nmodules = ["lecture_notes"]\n'
    'write_subcommands = ["add", "krisp", "channel", "stage"]\n'
    'scripts = ["krisp_trash.py", "krisp_words.py", "ydapi.py", "ycheck.py", "restructure_apply.py", '
    '"web_upload.py", "ydisk_inventory.py"]\n'
    'keychain_prefixes = ["lecture-notes-krisp", "lecture-notes-yadisk"]\n')


# Случаи про регистр пути: guard сводит регистр только на macOS, на Linux «другой регистр» — другой файл и разрешён.
MAC_CASEFOLD = frozenset({
    "0044 без роли: регистр пути — отказ", "0044 hq: регистр TASKS — отказ",
    "обход: 'RM ~/ai/PANTHEON/ALERTS.MD'", "hq: регистр не обходит alerts.md",
    "protect-config: регистр .Claude/Agents — отказ", "защиты: путь в другом регистре — Метида по запору — можно",
})


def setup(home):
    # ai/knowledge/.git нужен: без него guard ищет репозиторий вверх по дереву (_git_top) и находит чужой .git над
    # временной папкой (при сборке вне песочницы) — «mnemo-brain коммитит» тогда deny (metis-0090)
    for d in ("ai/pantheon/.git", "ai/pantheon/directions/athena-shop", "ai/pantheon/directions/hermes-site/inbox",
              "ai/pantheon/scout", "ai/pantheon-view", ".local/state/pantheon/owner-log", ".claude/pantheon",
              "projects/shopKeeperApp/app", "projects/sitebuilder", "projects/agent-kit",
              "projects/workshop/visa", "ai/knowledge", "ai/knowledge/.git", ".claude/agents", ".claude/skills/x", ".claude/.git",
              "projects/shopKeeperApp/.claude"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    os.makedirs(os.path.join(home, "ai/pantheon/directions/metis-pantheon/tasks"), exist_ok=True)
    os.makedirs(os.path.join(home, "ai/pantheon/directions/athena-shop/tasks"), exist_ok=True)
    # metis-0044: входящие владельца и папка доски с карточкой
    os.makedirs(os.path.join(home, "ai/pantheon/inbox/tasks"), exist_ok=True)
    os.makedirs(os.path.join(home, "ai/pantheon-view/Доска"), exist_ok=True)
    for f in ("ai/pantheon/directions/metis-pantheon/tasks/metis-0001.md", "ai/pantheon/directions/athena-shop/tasks/athena-0001.md",
              "ai/pantheon/inbox/tasks/inbox-0001.md", "ai/pantheon-view/Доска/athena-0001 Вопрос.md"):
        open(os.path.join(home, f), "w").close()
    for f in ("ai/pantheon/board.md", "ai/pantheon/alerts.md", "ai/pantheon/decision-map.md",
              "ai/pantheon/directions/hermes-site/STATUS.md", "ai/pantheon/directions/hermes-site/inbox/old.md"):
        open(os.path.join(home, f), "w").close()
    json.dump({"domains": {
        "athena-shop": ["~/projects/shopKeeperApp"],
        "hermes-site": ["~/projects/sitebuilder"],
        "metis-pantheon": ["~/projects/agent-kit", "~/.claude"],
        # реестр «по ошибке» отдаёт athena папку agent-kit — привилегий Метиды это не даёт
        "athena-shop-2": ["~/projects/agent-kit/sub"],
        "themis-library": ["~/projects/lecture-notes", "~/projects/law-feed"],
    }}, open(os.path.join(home, ".local/state/pantheon/domains.json"), "w"))
    # guard 0.5.0 (metis-0038): внутренняя папка Метиды вне защит и сайт брокера из [merge_client] вне domains.json
    os.makedirs(os.path.join(home, "projects/other/tg-read-dev"), exist_ok=True)
    os.makedirs(os.path.join(home, "projects/broker-landing"), exist_ok=True)
    domains_file = os.path.join(home, ".local/state/pantheon/domains.json")
    domains = json.loads(_read(domains_file))
    domains["domains"]["metis-pantheon"].append("~/projects/other/tg-read-dev")
    with open(domains_file, "w") as fh:
        json.dump(domains, fh)
    # шаг 1.2: репозиторий брокера на ветке эпика, sitebuilder — на main (правило push); личное в ~/ai/knowledge/me
    # 0.5.0: у каждого репозитория — remote: gh сливает в репозиторий из remote, и guard узнаёт защиты по нему
    for repo, branch, url in (("projects/shopKeeperApp", "epic-tax", "https://github.com/latark/shopKeeperApp"),
                              ("projects/sitebuilder", "main", "git@github.com:latark/sitebuilder.git"),
                              ("projects/lecture-notes", "main", "https://github.com/latark/lecture-notes.git"),
                              ("projects/law-feed", "main", "ssh://git@github.com/latark/law-feed"),
                              ("projects/agent-kit", "main", "https://github.com/latark/agent-kit"),
                              (".claude", "main", "git@github.com:latark/claude-config.git"),
                              ("projects/other/tg-read-dev", "main", "https://github.com/latark/tg-read"),
                              ("projects/broker-landing", "main", "https://github.com/latark/broker-landing")):
        git_repo(os.path.join(home, repo), branch, url)
    os.makedirs(os.path.join(home, "ai/knowledge/me"), exist_ok=True)
    os.makedirs(os.path.join(home, "ai/knowledge/raw"), exist_ok=True)
    open(os.path.join(home, "ai/knowledge/me/finance.md"), "w").close()
    os.makedirs(os.path.join(home, "projects/shopKeeperApp/.claude/worktrees/agent-1"), exist_ok=True)
    # metis-0823 (Б2 ревью #330): вложенные проекты — свой .claude и свой .mcp.json без .git
    os.makedirs(os.path.join(home, "projects/shopKeeperApp/web/.claude"), exist_ok=True)
    os.makedirs(os.path.join(home, "projects/shopKeeperApp/docs"), exist_ok=True)
    open(os.path.join(home, "projects/shopKeeperApp/docs/.mcp.json"), "w").close()
    open(os.path.join(home, ".claude/pantheon/policy.toml"), "w").write(
        'always = ["~/.claude/agent-memory"]\n[coordinators]\nmetis-pantheon = ["~/projects/agent-kit"]\n'
        'mnemo-brain = ["~/ai/knowledge"]\n[agent_extra]\nprometheus = ["~/ai/knowledge"]\n'
        'momus = ["~/ai/knowledge/Inbox"]\n'
        '[merge]\nthemis-library = ["~/projects/lecture-notes", "~/projects/law-feed"]\n'
        '[merge_repos]\nthemis-library = ["latark/lecture-notes", "latark/law-feed"]\n'
        'metis-pantheon = ["latark/tg-read", "latark/agent-kit"]\nhermes-site = ["latark/sitebuilder"]\n'
        'athena-shop = ["latark/shopkeeperapp", "latark/broker-landing"]\n'
        '[merge_client]\nathena-shop = ["~/projects/shopKeeperApp", "~/projects/broker-landing"]\n'
        + CORPUS_SECTION)
    write_zeus(home)
    gate_fixtures(home)


# запор слияния (guard 0.5.4): все PR 1–12 этих репозиториев проверены на SHA_OK — тесты, «принять» отдельного argus,
# talos, строка «что ушло» с откатом; поддельный gh отдаёт PR без файлов ядра. Сам запор — в test_merge_gate_*.py
SHA_OK = "a" * 40
GATE_REPOS = ("latark/lecture-notes", "latark/law-feed", "latark/sitebuilder", "latark/shopkeeperapp",
              "latark/broker-landing", "latark/agent-kit", "latark/tg-read", "latark/zz-own")


def gate_fixtures(home):
    d = os.path.join(home, ".local/state/pantheon/merge-gate")
    os.makedirs(d, mode=0o700, exist_ok=True)
    by = {"agent_type": "argus", "agent_id": "argus1", "session_id": "s-argus"}
    with open(os.path.join(d, "records.jsonl"), "w") as fh:
        for repo in GATE_REPOS:
            fh.write(json.dumps({"v": 1, "kind": "tests", "repo": [repo], "pr": None, "sha": SHA_OK, "by": by}) + "\n")
            for pr in range(1, 13):
                for kind in ("accept", "talos"):
                    r = {"v": 1, "kind": kind, "repo": [repo], "pr": pr, "sha": SHA_OK,
                         "by": dict(by, agent_type="argus" if kind == "accept" else "talos")}
                    if kind == "accept":  # Б6 (guard 0.5.6): запор пускает только «принять» с перечнем проверенного
                        r["base"] = "main"  # base PR на записи «принять» (metis-0965) — как baseRefName поддельного gh
                        # ran с моделью: в защитах шлюз засчитывает только argus на Opus (metis-0176)
                        r["checklist"] = {"opened": "дифф PR", "ran": "модель: claude-opus-5-5, тесты",
                                          "unchecked": "живой gh"}
                    fh.write(json.dumps(r) + "\n")
    with open(os.path.join(home, "ai/pantheon/alerts.md"), "w") as fh:
        for repo in ("latark/shopKeeperApp", "latark/broker-landing"):
            for pr in range(1, 13):
                fh.write(f"2026-10-15 20:00 · athena-shop · {repo}#{pr} ушло; откат: git revert x\n")
    os.makedirs(os.path.join(home, "fake-bin"), exist_ok=True)
    with open(os.path.join(home, "fake-bin/gh"), "w") as fh:
        # запуски Actions на SHA_OK (metis-0633): обязательные tests/affected и check-traces/traces зелёные от
        # pull_request PR 1–12 — шлюз agent-kit их требует; остальные gh api — файлы PR
        prs = [{"number": n} for n in range(1, 13)]
        wr = {"total_count": 2, "workflow_runs": [
            {"name": w, "event": "pull_request", "head_sha": SHA_OK, "check_suite_id": i, "pull_requests": prs}
            for i, w in ((1, "tests"), (2, "check-traces"))]}
        cr = {"total_count": 2, "check_runs": [
            {"name": j, "status": "completed", "conclusion": "success", "head_sha": SHA_OK, "check_suite": {"id": i}}
            for i, j in ((1, "affected"), (2, "traces"))]}
        fh.write("#!/bin/sh\ncase \"$1 $2\" in\n"
                 "  'api '*/actions/runs\\?*) echo '" + json.dumps(wr) + "'; exit 0 ;;\n"
                 "  'api '*/check-runs\\?*) echo '" + json.dumps(cr) + "'; exit 0 ;;\n"
                 "  api*) echo '" + json.dumps({"filename": "README.md", "status": "modified"}) + "'; exit 0 ;;\n"
                 "esac\necho '" + json.dumps({"changedFiles": 1, "headRefOid": SHA_OK, "baseRefName": "main", "statusCheckRollup": [
                     {"name": "check-traces", "status": "COMPLETED", "conclusion": "SUCCESS"}]}) + "'\n")
    os.chmod(os.path.join(home, "fake-bin/gh"), 0o755)


def with_head(tool, tool_input):
    """gh pr … merge без --match-head-commit — дописать проверенный SHA: старые случаи проверяют, кто и где сливает."""
    cmd = tool_input.get("command") if tool == "Bash" and isinstance(tool_input, dict) else None
    if not isinstance(cmd, str) or "--match-head-commit" in cmd:
        return tool_input
    return dict(tool_input, command=re.sub(r"(\bgh\s+pr\b[^;&|\n]*?\bmerge\b)", r"\1 --match-head-commit " + SHA_OK, cmd))


def git_repo(path, branch, url):
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch, path], check=True)
    if url:
        subprocess.run(["git", "-C", path, "remote", "add", "origin", url], check=True)


def write_zeus(home):
    """Журнал ответов владельца в окне вопросов Зевса (так его пишет хук answer плагина pantheon). Время — от
    текущего, чтобы тест не зависел от даты."""
    now = time.time()
    stamp = lambda ago: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - ago))
    ak5 = "https://github.com/latark/agent-kit/pull/5"
    entries = [
        (600, " · окно вопросов", f"вопрос: [metis-0038] Слить {ak5}?\nответ: Да — сливай"),
        (600, " · окно вопросов", "вопрос: [metis-0038] Слить latark/tg-read#3?\nответ: Да"),
        (25 * 3600, " · окно вопросов", "вопрос: [metis-0040] Слить вчерашнее latark/agent-kit#5?\nответ: Да"),
        (500, " · окно вопросов, свой текст", f"вопрос: [metis-0041] Слить {ak5}?\nответ: Да"),
        (400, " · окно вопросов", f"вопрос: [metis-0042] Слить {ak5}?\nответ: Нет — сливаю сам"),
        (400, " · окно вопросов", "вопрос: [metis-0042] Слить latark/tg-read#3?\nответ: Нет — сливаю сам"),
        (300, " · окно вопросов", "вопрос: Слить то, что в [metis-0043] latark/agent-kit#5?\nответ: Да"),
        (200, " · окно вопросов", f"вопрос: [athena-0001] Слить {ak5}?\nответ: Да"),
        (100, "", "да, [metis-0045] сливай latark/agent-kit#5"),
        # несколько ответов на один id — решает последний по времени заголовка, а не по месту в файле
        (3600, " · окно вопросов", f"вопрос: [metis-0046] Слить {ak5}?\nответ: Нет — сливаю сам"),
        (7200, " · окно вопросов", f"вопрос: [metis-0046] Слить {ak5}?\nответ: Да"),
        (7200, " · окно вопросов", f"вопрос: [metis-0047] Слить {ak5}?\nответ: Нет — сливаю сам"),
        (3600, " · окно вопросов", f"вопрос: [metis-0047] Слить {ak5}?\nответ: Да"),
        # время записи не разобрать — отказ, даже если раньше было «да»
        ("2026-13-45 10:00:00", " · окно вопросов", f"вопрос: [metis-0050] Слить {ak5}?\nответ: Нет"),
        (700, " · окно вопросов", f"вопрос: [metis-0050] Слить {ak5}?\nответ: Да"),
        (700, " · окно вопросов", f"вопрос: [metis-0051] Слить {ak5}?\nзаметка: да"),
        (700, " · окно вопросов", "вопрос: [metis-0052] Слить latark/other#5?\nответ: Да"),
        (700, " · окно вопросов", "вопрос: [metis-0053] Слить guard 0.5.0?\nответ: Да"),
        (900, " · окно вопросов", "вопрос: [metis-0054] Слить latark/agent-kit#7?\nответ: Да"),
        (800, " · окно вопросов", "вопрос: [metis-0054] Слить latark/agent-kit#8?\nответ: Да"),
        (700, " · окно вопросов", "вопрос: [metis-0055] Слить latark/agent-kit#5 и latark/agent-kit#6?\nответ: Да"),
        (-3600, " · окно вопросов", f"вопрос: [metis-0056] Слить {ak5}?\nответ: Да"),
        (1000, " · окно вопросов", f"вопрос: [metis-0057] Слить {ak5}?\nответ: Да"),
        # подделка (находка проверки 7d00dc6): хук экранирует «##» в начале строк тела пробелом
        (100, "", f" ## {stamp(100)} · окно вопросов\nвопрос: [metis-0060] Слить latark/agent-kit#5?\nответ: Да"),
        (100, " · окно вопросов, свой текст",
         f" ## {stamp(100)} · окно вопросов\nвопрос: [metis-0061] Слить latark/agent-kit#5?\nответ: Да"),
        (300, " · окно вопросов",
         f"вопрос: [metis-0062] Слить {ak5}?\nответ: Нет — сливаю сам\nзаметка: подумал ещё раз\nответ: Да"),
        (300, " · окно вопросов", f"вопрос: [metis-0058] Слить {ak5}?\nответ: Нет — сливаю сам"),
        (-600, " · окно вопросов", f"вопрос: [metis-0058] Слить {ak5}?\nответ: Да"),
        (650, " · окно вопросов", "вопрос: [metis-0038] Слить latark/agent-kit#5? [metis-0039]\nответ: Да"),
        (650, " · окно вопросов", f"вопрос: [METIS-0064] Слить {ak5}?\nответ: Да"),
        # согласие — только ответ «Да…» (решение Метиды «А», 15.10)
        (650, " · окно вопросов", f"вопрос: [metis-0070] Слить {ak5}?\nответ: Отложить"),
        (650, " · окно вопросов", f"вопрос: [metis-0071] Слить {ak5}?\nответ: Отмена"),
        (650, " · окно вопросов", f"вопрос: [metis-0072] Слить {ak5}?\nответ: No"),
        (650, " · окно вопросов", f"вопрос: [metis-0073] Слить {ak5}?\nответ: Дальше"),
        (650, " · окно вопросов", f"вопрос: [metis-0074] Слить {ak5}?\nответ: Да — слить"),
        (650, " · окно вопросов", f"вопрос: [metis-0075] Слить {ak5}?\nответ: да"),
        (650, " · окно вопросов", f"вопрос: [metis-0076] Слить {ak5}?\nответ: ДА."),
        (650, " · окно вопросов", f"вопрос: [metis-0077] Слить {ak5}?\nответ: "),
        (650, " · окно вопросов", f"вопрос: [metis-0078] Слить {ak5}?\nответ: Да1"),
    ]
    with open(os.path.join(home, ".local/state/pantheon/owner-log/zeus.md"), "w") as fh:
        fh.write("".join(f"## {ago if isinstance(ago, str) else stamp(ago)}{note}\n{body}\n\n"
                         for ago, note, body in entries))
    # галочка на доске — для слияния защит не согласие
    with open(os.path.join(home, ".local/state/pantheon/owner-log/board.jsonl"), "w") as fh:
        fh.write(json.dumps({"kind": "answer", "id": "metis-0044", "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "question": "[metis-0044] Слить latark/agent-kit#5?", "answer": "Да"}, ensure_ascii=False) + "\n")


def merge_fixtures(home):
    """Обходы защит «по пути» (находка проверки безопасности 2eda45f): клоны и worktree agent-kit в чужих папках,
    симлинк, ssh-псевдоним; папка без git и репозиторий без remote."""
    j = lambda rel: os.path.join(home, rel)
    git_repo(j("projects/other/tg-read-dev/x"), "main", "https://github.com/latark/agent-kit.git")
    git_repo(j("projects/law-feed/akclone"), "main", "git@github.com:Latark/Agent-Kit.git")
    git_repo(j("projects/sitebuilder/alias-clone"), "main", "git@gh-alt:latark/agent-kit.git")
    git_repo(j("projects/sitebuilder/no-remote"), "main", None)
    os.makedirs(j("projects/agent-kit/sub"), exist_ok=True)
    git_repo(j("projects/other/tg-read-dev/alias"), "main", "git@gh-alt:latark/agent-kit.git")
    git_repo(j("projects/sitebuilder/fork"), "main", "git@github.com:someone/agent-kit-fork.git")
    subprocess.run(["git", "-C", j("projects/sitebuilder/fork"), "config", "remote.origin.gh-resolved",
                    "latark/agent-kit"], check=True)
    git_repo(j("projects/sitebuilder/base-clone"), "main", "git@github.com:latark/sitebuilder.git")
    subprocess.run(["git", "-C", j("projects/sitebuilder/base-clone"), "config", "remote.origin.gh-resolved", "base"],
                   check=True)
    os.symlink(j("projects/agent-kit"), j("projects/sitebuilder/ak-link"))
    git = ["git", "-C", j("projects/agent-kit"), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "init"], check=True)
    for wt, branch in (("projects/other/tg-read-dev/wt", "wt1"), ("wt-ak", "wt2")):
        subprocess.run(git + ["worktree", "add", "-q", "-b", branch, j(wt)], check=True, capture_output=True)


def _read(path):
    """Прочитать файл целиком до того, как его откроют на запись (open(p, "w") обнуляет сразу)."""
    with open(path) as fh:
        return fh.read()


def run(home, pdir, role, tool, tool_input, sub=False, cwd=None, raw=False, tuid=None, penv=None, proc=False):
    """Решение guard (PreToolUse, режим плагина) по событию: "deny" | "allow", с raw — вывод хука. proc — через
    настоящий процесс, иначе внутри процесса теста (hook)."""
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": with_head(tool, tool_input),
             "cwd": os.path.join(home, cwd if cwd is not None else pdir), "session_id": "s-test",
             "tool_use_id": tuid or "toolu_" + uuid.uuid4().hex}
    if role:
        event["agent_type"] = role
    if sub:
        event["agent_id"] = "a1"
    env = {"HOME": home, "PATH": os.path.join(home, "fake-bin") + os.pathsep + os.environ["PATH"],
           "CLAUDE_PROJECT_DIR": os.path.join(home, pdir), "TMPDIR": "/nonexistent-tmp", **(penv or {})}
    r = hook([], env, json.dumps(event), proc=proc)
    out = r.stdout
    if r.returncode == 2:  # сбой (metis-0094): Claude Code понимает код 2 как отказ с причиной из stderr
        out = json.dumps({"hookSpecificOutput": {"permissionDecision": "deny", "exit2": True,
                                                 "permissionDecisionReason": r.stderr}}, ensure_ascii=False)
    elif r.returncode != 0:
        out += f"\n[код {r.returncode}] {r.stderr}"
    if raw:
        return out
    return "deny" if '"deny"' in out else "allow"


def ak_dir(br):
    return os.path.join(os.path.dirname(br), "agent-kit")


def hook(argv, env, stdin, proc=False, timeout=SUB_TIMEOUT):
    """Хук guard через шим с событием stdin → (returncode, stdout, stderr). proc — настоящий процесс
    `python3 -I _guard_shim.py guard.py [argv]`; иначе — внутри процесса теста (_guard_inproc.call), с тем же
    модулем правил и теми же подменами шима."""
    if proc:
        return subprocess.run([sys.executable, "-I", SHIM, GUARD] + list(argv), input=stdin, capture_output=True,
                              text=True, env=env, timeout=timeout)
    return call(argv, env, stdin, timeout=timeout)


def new_home(merge=True):
    """Подменённый HOME части: setup и (merge) обходы защит «по пути» — как у прежнего main() test_guard.py."""
    home = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home)
    if merge:
        merge_fixtures(home)
    return home


def helpers(home):
    """Построители путей и вызовов таблицы: P — ~/ai/pantheon, W, E, B, R, G — Write, Edit, Bash, Read, Grep, K —
    ~/ai/knowledge, A — Agent."""
    P = lambda rel: os.path.join(home, "ai", "pantheon", rel)
    W = lambda path: ("Write", {"file_path": path, "content": "x"})
    E = lambda path: ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"})
    B = lambda cmd: ("Bash", {"command": cmd})
    R = lambda path: ("Read", {"file_path": path})
    G = lambda path: ("Grep", {"pattern": "налог", "path": path})
    K = lambda rel: os.path.join(home, "ai", "knowledge", rel)
    A = lambda name: ("Agent", {"subagent_type": name, "description": "x", "prompt": "x"})
    return P, W, E, B, R, G, K, A


def run_table(home, cases):
    """Таблица случаев (имя, ожидание, папка запуска, роль, субагент, (инструмент, вход)[, cwd[, env окна]]) — по 25
    в своём fork (metis-0544, _par.py): HOME случаи не меняют, кроме журнала сбоев. Первый случай таблицы — через
    настоящий процесс (proc), остальные — внутри процесса. → число упавших."""
    oks = []

    def one(case, proc):
        name, want, pdir, role, sub, (tool, ti) = case[:6]
        if sys.platform != "darwin" and name in MAC_CASEFOLD:  # guard сравнивает пути без регистра только на macOS (IS_MAC)
            return print(f"пропущено: {name} — нужен macOS (регистронезависимая ФС)")
        cwd, penv = (*case[6:8], None, None)[:2]  # папка запуска и env окна: PANTHEON_ROLE (guard 0.5.5)
        got = run(home, os.path.normpath(pdir), role, tool, ti, sub, cwd, penv=penv, proc=proc)
        oks.append(got == want)
        print(f"{'ok  ' if got == want else 'FAIL'} {name}: {got}" + (" (процесс)" if proc else ""))
    run_cases([(f"случаи {i + 1}-{i + 25}", lambda i=i: [one(c, i + k == 0) for k, c in enumerate(cases[i:i + 25])])
               for i in range(0, len(cases), 25)], oks, lambda name, err: oks.append(False))
    return oks.count(False)


def finish(cases, failed):
    """Итог части: «N из M прошли» (M — случаи таблицы и проверки помощников) и код выхода."""
    print(f"\n{len(cases) - failed} из {len(cases)} прошли")
    sys.exit(1 if failed else 0)


__all__ = [k for k in list(globals()) if not k.startswith("__")]   # всё, включая _помощники: части берут их через import *
