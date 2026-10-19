#!/usr/bin/env python3
"""Синтетические тесты guard: подменённый HOME во временной папке, события PreToolUse на stdin.

Запуск: python3 -I plugins/guard/tests/test_guard.py   (код выхода 0 — все прошли)
Проверяет карту прав ~/ai/pantheon (pantheon-acl), правило domain для координаторов и мастерской,
привилегии из policy.toml и что прежние правила (dev-server) не сломались.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
# Все временные папки файла — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение);
# TMPDIR — для подпроцессов, которые тоже создают временные папки. Общий TMPDIR остаётся чистым.
import atexit as _atexit
import os as _os
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="guard-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)
import time
import uuid

GUARD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "guard.py")
SHIM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_guard_shim.py")  # запуск guard без зависимости от места тестов
try:  # привилегии из policy.toml читает tomllib (Python 3.11+); на системном 3.9 политика пуста — это безопасный отказ
    import tomllib  # noqa: F401
    HAS_TOMLLIB = True
except ImportError:
    HAS_TOMLLIB = False
# случаи, где «allow» держится только на привилегии/agent_extra из policy.toml: без tomllib guard их честно закрывает
# (тот же приём, что MERGE_OK ниже). Обвязка не ослабляет проверку: с tomllib ожидание прежнее — allow.
NEEDS_POLICY = {"Метида правит карту решений", "prometheus пишет в ~/ai/knowledge (agent_extra)",
                "prometheus сессией: ~/ai/knowledge по agent_extra", "protect-config: Метида правит роль",
                "protect-config: Метида пишет policy.toml", "private: mnemo-brain пишет в me/",
                "momus пишет в ~/ai/knowledge/Inbox (agent_extra)", "0177 momus без agent_id пишет в ~/ai/knowledge/Inbox"}


# имена корпуса для corpus-role — только из [corpus] policy.toml (metis-0182); здесь выдуманный корпус lecture-notes
CORPUS_SECTION = (
    '[corpus]\ncommands = ["corpus"]\nmodules = ["lecture_notes"]\n'
    'write_subcommands = ["add", "krisp", "channel", "stage"]\n'
    'scripts = ["krisp_trash.py", "krisp_words.py", "ydapi.py", "ycheck.py", "restructure_apply.py", '
    '"web_upload.py", "ydisk_inventory.py"]\n'
    'keychain_prefixes = ["lecture-notes-krisp", "lecture-notes-yadisk"]\n')


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
# talos, строка «что ушло» с откатом; поддельный gh отдаёт PR без файлов ядра. Сам запор — в test_merge_gate.py
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
        fh.write("#!/bin/sh\n[ \"$1\" = api ] && { echo '" + json.dumps({"filename": "README.md", "status": "modified"})
                 + "'; exit 0; }\necho '" + json.dumps({"changedFiles": 1, "headRefOid": SHA_OK}) + "'\n")
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


def run(home, pdir, role, tool, tool_input, sub=False, cwd=None, python=None, raw=False, tuid=None, penv=None):
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": with_head(tool, tool_input),
             "cwd": os.path.join(home, cwd if cwd is not None else pdir), "session_id": "s-test",
             "tool_use_id": tuid or "toolu_" + uuid.uuid4().hex}
    if role:
        event["agent_type"] = role
    if sub:
        event["agent_id"] = "a1"
    env = {"HOME": home, "PATH": os.path.join(home, "fake-bin") + os.pathsep + os.environ["PATH"],
           "CLAUDE_PROJECT_DIR": os.path.join(home, pdir), "TMPDIR": "/nonexistent-tmp", **(penv or {})}
    r = subprocess.run([python or sys.executable, "-I", SHIM, GUARD], input=json.dumps(event), capture_output=True,
                       text=True, env=env, timeout=10)
    out = r.stdout
    if r.returncode == 2:  # сбой (metis-0094): Claude Code понимает код 2 как отказ с причиной из stderr
        out = json.dumps({"hookSpecificOutput": {"permissionDecision": "deny", "exit2": True,
                                                 "permissionDecisionReason": r.stderr}}, ensure_ascii=False)
    elif r.returncode != 0:
        out += f"\n[код {r.returncode}] {r.stderr}"
    if raw:
        return out
    return "deny" if '"deny"' in out else "allow"


def corpus_policy_checks(br, cases):
    """corpus-role берёт имена только из [corpus] policy.toml (metis-0182): нет раздела или пустые списки — правило
    ничего не узнаёт; битое значение или битый TOML — ошибка разбора, ролям Bash закрыт с предупреждением."""
    failed = 0
    add = {"command": "corpus add https://youtu.be/x"}
    script = {"command": "python3 tools/ydapi.py"}
    ls = {"command": "ls"}

    def variant(text):
        h = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
        setup(h)
        pol = os.path.join(h, ".claude", "pantheon", "policy.toml")
        base = _read(pol)
        assert CORPUS_SECTION in base
        open(pol, "w").write(text(base))
        return h

    def check(name, ok, got):
        nonlocal failed
        failed += not ok
        cases.append(None)
        print(f"{'ok  ' if ok else 'FAIL'} corpus-role [corpus]: {name}: {got}")

    h = variant(lambda t: t.replace(CORPUS_SECTION, ""))
    got = tuple(run(h, br, "domain-coordinator", "Bash", x) for x in (add, script))
    check("нет раздела — правило пустое, пополнение не узнаёт", got == ("allow", "allow"), got)
    empty = "".join(f"{k} = []\n" for k in ("commands", "modules", "write_subcommands", "scripts",
                                              "keychain_prefixes"))
    h = variant(lambda t: t.replace(CORPUS_SECTION, "[corpus]\n" + empty))
    got = tuple(run(h, br, "domain-coordinator", "Bash", x) for x in (add, script))
    check("пустые списки — правило пустое", got == ("allow", "allow"), got)
    if not HAS_TOMLLIB:  # без tomllib политики нет: раздел не читается, битое значение не отличить от пустого
        return failed
    broken = [
        ("commands строкой", lambda t: t.replace('commands = ["corpus"]', 'commands = "corpus"')),
        ("в scripts не строка", lambda t: t.replace('scripts = ["krisp_trash.py"', 'scripts = [1, "krisp_trash.py"')),
        ("пустая строка в modules", lambda t: t.replace('modules = ["lecture_notes"]', 'modules = [""]')),
        ("[corpus] не таблица", lambda t: 'corpus = ["corpus"]\n' + t.replace(CORPUS_SECTION, "")),
        ("policy.toml не TOML", lambda t: t + "\n[corpus\n"),
    ]
    for name, fix in broken:
        h = variant(fix)
        outs = [run(h, br, "domain-coordinator", "Bash", x, raw=True) for x in (add, ls)]
        outs.append(run(h, br, "dev-sonnet", "Bash", ls, sub=True, raw=True))
        ok = all('"deny"' in o and "corpus-role" in o and "не прочитать" in o for o in outs)
        ok = ok and run(h, ".", "", "Bash", add) == "allow"  # ваша сессия без роли — правило её не касается
        check(f"{name} — ролям закрыто с предупреждением, без роли можно", ok, "deny" if ok else outs)
    return failed


def merge_security_checks(home, MERGE_OK, cases):
    """Находка проверки безопасности 2eda45f: защиты по remote, любой сбой — отказ; лиды (metis-0054). С guard 0.5.4
    поштучного «да» владельца нет — его заменил запор (test_merge_gate.py). Возвращает число упавших проверок."""
    failed = 0
    ak, ec = "projects/agent-kit", "projects/lecture-notes"
    allow_ok = MERGE_OK == "allow"

    def check(name, ok):
        nonlocal failed
        failed += not ok
        cases.append(None)
        print(f"{'ok  ' if ok else 'FAIL'} {name}")

    def M(h, cmd, pdir=ak, cwd=None, tuid=None, raw=False):
        return run(h, pdir, "domain-coordinator", "Bash", {"command": cmd}, cwd=cwd, tuid=tuid, raw=raw)

    def variant(policy_fn=None, domains_fn=None):
        h = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
        setup(h)
        if policy_fn:
            pol = os.path.join(h, ".claude/pantheon/policy.toml")
            text = _read(pol)
            with open(pol, "w") as fh:
                fh.write(policy_fn(text))
        if domains_fn:
            dom = os.path.join(h, ".local/state/pantheon/domains.json")
            text = _read(dom)
            with open(dom, "w") as fh:
                fh.write(domains_fn(text))
        return h

    deny = lambda out: '"deny"' in out
    # --- сбой в политике и реестре — отказ по правилу, а не пропуск и не сбой скрипта ---
    for name, kw in (
            ("нет metis-pantheon в [coordinators]",
             dict(policy_fn=lambda t: t.replace('metis-pantheon = ["~/projects/agent-kit"]\n', ""))),
            ("metis-pantheon строкой",
             dict(policy_fn=lambda t: t.replace('metis-pantheon = ["~/projects/agent-kit"]', 'metis-pantheon = "~/projects/agent-kit"'))),
            ("metis-pantheon пустой список",
             dict(policy_fn=lambda t: t.replace('metis-pantheon = ["~/projects/agent-kit"]', "metis-pantheon = []"))),
            ("metis-pantheon не из строк",
             dict(policy_fn=lambda t: t.replace('metis-pantheon = ["~/projects/agent-kit"]', "metis-pantheon = [1]"))),
            # guard читает [private] мягко (0163, проверка умолчаний — test_misc.py), а шлюз слияния на неверном — закрыт
            ("[private].coordinators не из строк", dict(policy_fn=lambda t: t + "\n[private]\ncoordinators = [1]\n")),
            ("[private].paths строкой", dict(policy_fn=lambda t: t + '\n[private]\npaths = "~/ai/knowledge/me"\n')),
            ("domains.json битый", dict(domains_fn=lambda t: "{не json")),
            ("domains.json: папки строкой",
             dict(domains_fn=lambda t: json.dumps({"domains": {"themis-library": "~/projects/lecture-notes"}}))),
            ("domains.json без направлений", dict(domains_fn=lambda t: '{"domains": {}}')),
            ("два направления с одним корнем",
             dict(domains_fn=lambda t: json.dumps(dict(json.loads(t), domains=dict(
                 json.loads(t)["domains"], **{"themis-twin": ["~/projects/lecture-notes"]}))))),
    ):
        out = run(variant(**kw), ec, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, raw=True)
        check(f"сбой — отказ: {name}", deny(out) and "сбой проверки" not in out)
    # 0163: отказ на неверном [private] — именно по [private]; пустой список coordinators — «никого», слияние как было
    out = run(variant(policy_fn=lambda t: t + "\n[private]\ncoordinators = [1]\n"), ec, "domain-coordinator", "Bash",
              {"command": "gh pr merge 1"}, raw=True)
    check("[private].coordinators = [1] — отказ называет [private]",
          deny(out) and ("[private] в policy.toml не разобрать" in out or not allow_ok))
    got = M(variant(policy_fn=lambda t: t + "\n[private]\ncoordinators = []\nroles = []\n"), "gh pr merge 1", pdir=ec)
    check(f"[private] с пустыми roles и coordinators — слияние как было: {got}", got == MERGE_OK)
    # paths = [] — умолчание, как у guard (private_conf; ревью PR #35): шлюз не закрывается, личное не открывается
    hp = variant(policy_fn=lambda t: t + "\n[private]\npaths = []\n")
    got = M(hp, "gh pr merge 1", pdir=ec)
    check(f"[private] paths = [] — слияние как было: {got}", got == MERGE_OK)
    me = os.path.join(hp, "ai/knowledge/me/finance.md")
    got = (run(hp, "projects/shopKeeperApp", "dev-sonnet", "Read", {"file_path": me}, sub=True),
           run(hp, ec, "domain-coordinator", "Bash", {"command": f"cat {me}"}))
    check(f"[private] paths = [] — личное закрыто: Read субагента и cat координатора — отказ: {got}",
          got == ("deny", "deny"))
    got = M(variant(policy_fn=lambda t: t + '\n[private]\npaths = [" "]\n'), "gh pr merge 1", pdir=ec)
    check(f'[private] paths = [" "] — отказ, как раньше: {got}', got == "deny")
    # -R latark/agent-kit в чужом [merge_repos] — это защиты, а не внутреннее
    h = variant(policy_fn=lambda t: t.replace('themis-library = ["latark/lecture-notes", "latark/law-feed"]',
                                              'themis-library = ["latark/lecture-notes", "latark/agent-kit"]'))
    got = (M(h, "gh pr merge 5 -R latark/agent-kit", pdir=ec), M(h, "gh pr merge 2 -R latark/lecture-notes", pdir=ec))
    check(f"защиты по -R: latark/agent-kit в [merge_repos] Фемиды — отказ, свой -R — как было: {got}",
          got == ("deny", MERGE_OK))
    # корень направления-родитель («~/projects») не открывает папку другого направления внутри
    # широкий корень — первым в реестре: проверка «по первому совпадению» отдала бы ему sitebuilder
    h = variant(domains_fn=lambda t: json.dumps({"domains": dict({"zeta-wide": ["~/projects"]},
                                                                 **json.loads(t)["domains"])}),
                policy_fn=lambda t: t.replace("[merge_repos]\n", '[merge_repos]\nzeta-wide = ["latark/zz-own"]\n'))
    git_repo(os.path.join(h, "projects/zz-own"), "main", "https://github.com/latark/zz-own")
    os.makedirs(os.path.join(h, "projects/zz-plain"), exist_ok=True)
    got = (M(h, "gh pr merge 1", pdir="projects", cwd="projects/sitebuilder"),
           M(h, "gh pr merge 1", pdir="projects", cwd="projects/zz-own"),
           M(h, "gh pr merge 1", pdir="projects", cwd="projects/zz-plain"))
    check(f"чужая папка: корень «~/projects» над sitebuilder — отказ, своя папка — можно, не репозиторий git — отказ: {got}",
          got == ("deny", MERGE_OK, "deny"))
    # битая запись одного направления не выпадает молча: иначе его папку «унаследовал» бы широкий корень
    h = variant(domains_fn=lambda t: json.dumps({"domains": dict(json.loads(t)["domains"], **{
        "zeta-wide": ["~/projects"], "hermes-site": "~/projects/sitebuilder"})}))
    out = M(h, "gh pr merge 1", pdir="projects", cwd="projects/sitebuilder", raw=True)
    check("сбой — отказ: папки одного направления строкой — широкий корень не получает его папку",
          deny(out) and ("domains.json" in out or not allow_ok))
    # ревью argus 210766a: domains.json битый или удалён — без отката на старый ~/.claude/hooks/domains.json, где
    # направление шире (broker = shopKeeperApp + sitebuilder + law-feed): Гермес слил бы в law-feed
    legacy = {"domains": {"broker": ["~/projects/shopKeeperApp", "~/projects/sitebuilder", "~/projects/law-feed"]}}
    for label, broken in (("битый", True), ("удалён", False)):
        h = variant()
        os.makedirs(os.path.join(h, ".claude/hooks"), exist_ok=True)
        with open(os.path.join(h, ".claude/hooks/domains.json"), "w") as fh:
            json.dump(legacy, fh)
        dom = os.path.join(h, ".local/state/pantheon/domains.json")
        if broken:
            with open(dom, "w") as fh:
                fh.write("{не json")
        else:
            os.remove(dom)
        out = M(h, "gh pr merge 2", pdir="projects/sitebuilder", cwd="projects/law-feed", raw=True)
        check(f"старый реестр: domains.json {label}, ~/.claude/hooks/domains.json есть — Гермес в law-feed — отказ",
              deny(out) and ("domains.json" in out or not allow_ok))
    # папка защит с .git, у которой remote не читается, — отказ всем; без .git — защищена только по пути
    h = variant(policy_fn=lambda t: t.replace('metis-pantheon = ["~/projects/agent-kit"]',
                                              'metis-pantheon = ["~/projects/agent-kit", "~/projects/broken-prot"]'))
    os.makedirs(os.path.join(h, "projects/broken-prot"), exist_ok=True)
    with open(os.path.join(h, "projects/broken-prot/.git"), "w") as fh:
        fh.write("gitdir: /nonexistent-gitdir\n")
    out = M(h, "gh pr merge 1", pdir=ec, raw=True)
    os.remove(os.path.join(h, "projects/broken-prot/.git"))
    got = M(h, "gh pr merge 1", pdir=ec)
    check(f"сбой git: у папки защит сломан .git — отказ всем, без .git — как было: {got}",
          deny(out) and ("не читается git remote" in out or not allow_ok) and got == MERGE_OK)
    # --- включение новой схемы строкой [merge_client]: без неё — как в 0.4.7 (решение лида, 15.10) ---
    no_client = lambda t: t.replace('[merge_client]\nathena-shop = ["~/projects/shopKeeperApp", '
                                    '"~/projects/broker-landing"]\n', "")
    h = variant(policy_fn=no_client)
    alex, br, lw = "projects/sitebuilder", "projects/shopKeeperApp", "projects/law-feed"
    got = (M(h, "gh pr merge 1", pdir=ec), M(h, "gh pr merge 2 -R latark/lecture-notes", pdir=lw),
           M(h, "gh pr merge 1", pdir=alex), M(h, "gh pr merge 1", pdir=br),
           M(h, "gh pr merge 5 --squash"), M(h, "gh pr merge 13"),
           M(h, "gh pr merge 3", cwd="projects/other/tg-read-dev"), M(h, "gh pr merge 1", pdir=ec, cwd=alex))
    check(f"без [merge_client] (схема 0.4.7): Фемида и её -R — можно, Гермес и Афина — нельзя, Метида в "
          f"agent-kit по записям запора — можно, без записей — нельзя, её внутренняя папка (нет в [merge]) — нельзя, "
          f"Фемида в чужой папке (cwd без cd) — нельзя: {got}",
          got == (MERGE_OK, MERGE_OK, "deny", "deny", MERGE_OK, "deny", "deny", "deny"))
    h = variant(policy_fn=lambda t: no_client(t) + "[merge_client]\n")
    got = (M(h, "gh pr merge 1", pdir=alex), M(h, "gh pr merge 1", pdir=br), M(h, "gh pr merge 1", pdir=ec))
    check(f"пустая [merge_client] — новая схема: Гермес, Афина и Фемида в своих папках — можно: {got}",
          got == (MERGE_OK, MERGE_OK, MERGE_OK))
    h = variant(policy_fn=lambda t: 'merge_client = "x"\n' + no_client(t))  # ключ верхнего уровня — до таблиц
    got = M(h, "gh pr merge 1", pdir=alex)
    check(f"[merge_client] не таблицей — как без неё (0.4.7): Гермес — нельзя: {got}", got == "deny")
    # --- защиты через запор (guard 0.5.4): поштучного «да» нет, остальное — как было
    tg, br, alex = "projects/other/tg-read-dev", "projects/shopKeeperApp", "projects/sitebuilder"
    os.makedirs(os.path.join(home, ak, "sub"), exist_ok=True)
    got = (M(home, "gh pr merge 5 --squash", pdir=br, cwd=ak), M(home, "gh pr merge 5", pdir=br, cwd=ak + "/sub"),
           run(home, ak, "domain-coordinator", "Bash", {"command": "gh pr merge 5"}, sub=True),
           run(home, ak, "dev-sonnet", "Bash", {"command": "gh pr merge 5"}, sub=True),
           M(home, "gh pr merge 5 --auto"), M(home, "gh pr merge 5 6"),
           M(home, "gh pr merge 3 -R latark/tg-read --auto", cwd=tg), M(home, "gh pr merge 3 -R latark/sitebuilder", cwd=tg),
           M(home, f"cd {home}/{ak} && gh pr merge 5", cwd=tg), M(home, "GH_REPO=latark/agent-kit gh pr merge 5"))
    check(f"защиты: другой координатор в agent-kit, субагенты Метиды, --auto, два номера, -R вне [merge_repos], cd и "
          f"GH_REPO — отказ: {got}", got == ("deny",) * 10)
    out = M(home, "gh pr merge 5 --auto", raw=True)
    check("защиты: отказ не просит «да» владельца, а называет шлюз слияния и Д3",
          deny(out) and (("шлюз слияния" in out and "(Д3)" in out and "окн" not in out and "--subject" not in out)
                         or not allow_ok))

    # metis-0054: лид Метиды (hephaestus-pantheon субагентом) — по тем же правилам, что Метида
    def L(h, cmd, role="hephaestus-pantheon", pdir=ak, cwd=None, raw=False):
        return run(h, pdir, role, "Bash", {"command": cmd}, sub=True, cwd=cwd, raw=raw)
    got = (L(home, "gh pr merge 5 --squash"), L(home, "gh pr merge 3 -R latark/tg-read", cwd=tg))
    check(f"защиты: лид Метиды сливает защиты и -R из [merge_repos] по запору — можно: {got}",
          got == (MERGE_OK, MERGE_OK))
    got = (L(home, "gh pr merge 5 --auto"), L(home, "gh pr merge 5 6"), L(home, "gh pr merge 3 -R latark/sitebuilder", cwd=tg),
           L(home, "gh pr merge 3 -R latark/tg-read -R latark/agent-kit", cwd=tg),
           L(home, "gh pr merge 5", pdir=br, cwd=ak), L(home, "gh pr merge 5", role="hephaestus-shop"),
           L(home, "gh pr merge 5", role="apollo-pantheon", pdir="ai/pantheon", cwd=ak))
    check(f"защиты: лид Метиды с --auto, двумя номерами, -R вне [merge_repos], двумя -R; лид Афины в "
          f"agent-kit и из своей сессии; лид в сессии штаба — отказ: {got}", got == ("deny",) * 7)
    # metis-0054: кто не лид — отказ с текстом «сливает лид или координатор, остальные — PR и отчёт лиду»
    for r in ("dev-sonnet", "argus", "talos", "prometheus", "hephaestus", "hephaestus-"):
        out = L(home, "gh pr merge 1", role=r, pdir=br, raw=True)
        check(f"merge: {r} субагентом — отказ, текст про лида и отчёт лиду",
              deny(out) and (("лид направления" in out and "отчёте лиду" in out) or not allow_ok))
    out = L(home, "gh pr merge 4", role="hephaestus-shop", pdir=alex, raw=True)
    check("merge: лид чужого направления (hephaestus-shop в сессии hermes-site) — отказ, текст про своё направление",
          deny(out) and ("не лид направления этой сессии (hermes-site)" in out or not allow_ok))
    out = L(home, "gh pr merge 1", role="hephaestus-shop", pdir=br, raw=True)
    check("merge: лид своего направления — можно (текст отказа не про лида)",
          (allow_ok and not deny(out)) or (not allow_ok and "не лид" not in out))
    # реестр «по ошибке» отдал agent-kit/sub Афине (athena-shop-2): его лид — hephaestus-shop-2, защиты ему закрыты
    got = (L(home, "gh pr merge 5", role="hephaestus-shop-2", pdir=ak + "/sub"),
           L(home, "gh pr merge 5 -R latark/agent-kit", role="hephaestus-shop-2", pdir=ak + "/sub"))
    check(f"merge: лид athena-shop-2 в agent-kit/sub (защиты) — отказ и с -R: {got}", got == ("deny", "deny"))
    # лид mnemo-brain: у направления личное — как и координатор, не сливает
    h = variant(domains_fn=lambda t: json.dumps(dict(json.loads(t), domains=dict(
        json.loads(t)["domains"], **{"mnemo-brain": ["~/ai/knowledge"]}))))
    out = L(h, "gh pr merge 1", role="hephaestus-brain", pdir="ai/knowledge", raw=True)
    check("merge: лид mnemo-brain (hephaestus-brain) — отказ, у направления личное",
          deny(out) and ("личному" in out or not allow_ok))
    # [merge_protect] больше не читается: consent = false ничего не открывает и не ломает
    h = variant(policy_fn=lambda t: t + "[merge_protect]\nconsent = false\n")
    got = (M(h, "gh pr merge 5"), M(h, "gh pr merge 13"))
    check(f"[merge_protect] consent = false не читается: по запору — можно, без записей — отказ: {got}",
          got == (MERGE_OK, "deny"))
    h = variant()
    shutil.rmtree(os.path.join(h, ".local/state/pantheon"))
    out = M(h, "gh pr merge 5", raw=True)
    check("нет папки состояния — отказ по правилу, без сбоя скрипта", deny(out) and "сбой проверки" not in out)
    return failed


def failure_checks(home, env, cases):
    """metis-0094: искусственный сбой в каждом хуке guard → код 2 и причина в stderr (Stop — код 0). Подмена функций —
    через GUARD_SHIM_BOOM / GUARD_SHIM_HANG в _guard_shim.py. Возвращает число упавших проверок."""
    failed = 0
    ak = "projects/agent-kit"
    mf = os.path.join(home, "managed-fail.json")  # управляемые настройки вызывают guard --managed
    with open(mf, "w") as fh:
        fh.write('{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 guard.py --managed"}]}]}}')

    def hook(stdin, mode=None, role="", tool="Bash", ti=None, name="PreToolUse", penv=None, extra=None):
        if stdin is None:
            ev = {"hook_event_name": name, "session_id": "s-test", "cwd": os.path.join(home, ak),
                  "tool_use_id": "toolu_" + uuid.uuid4().hex}
            if tool:
                ev.update(tool_name=tool, tool_input=ti if ti is not None else {"command": "ls"})
            if role:
                ev["agent_type"] = role
            ev.update(extra or {})
            stdin = json.dumps(ev)
        e = dict(env, CLAUDE_PROJECT_DIR=os.path.join(home, ak), **(penv or {}))
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, "-I", SHIM, GUARD] + ([mode] if mode else []), input=stdin,
                           capture_output=True, text=True, env=e, timeout=20)
        return r, time.monotonic() - t0

    def check(name, ok, r=None):
        nonlocal failed
        failed += not ok
        cases.append(None)
        tail = f" — код {r.returncode}, stderr {r.stderr.strip()[:160]!r}" if (r is not None and not ok) else ""
        print(f"{'ok  ' if ok else 'FAIL'} сбой (metis-0094): {name}{tail}")

    def blocked(r, word):
        return r.returncode == 2 and word in r.stderr and "Traceback" not in r.stderr and '"deny"' not in r.stdout

    # неразобранный вход — во всех режимах, и у хука плагина при активных управляемых настройках (раньше молчал)
    for label, mode, penv in (("плагин", None, None), ("--managed", "--managed", None), ("--strict", "--strict", None),
                              ("плагин при управляемых настройках", None, {"GUARD_SHIM_MANAGED": mf})):
        r, _ = hook("не json", mode, penv=penv)
        check(f"событие не JSON, {label} — код 2 и причина", blocked(r, "не JSON"), r)
    for label, stdin in (("массив", "[1, 2]"), ("строка", '"x"'), ("объект без hook_event_name", "{}")):
        r, _ = hook(stdin)
        check(f"событие не объект события ({label}) — код 2", blocked(r, "не разобрать"), r)
    # PreToolUse: исключение в проверке прав — блок и в вашей сессии без роли, во всех режимах
    for label, boom, mode, tool, ti in (
            ("domain, ваша сессия", "check_domain", None, "Bash", None),
            ("pantheon-acl, --managed", "check_pantheon", "--managed", "Bash", None),
            ("карта прав (check_roles), --strict", "check_roles", "--strict", "Read", {"file_path": "/etc/hosts"}),
            ("protect_config.py", "check_protect_config", None, "Write",
             {"file_path": os.path.join(home, ak, "x.txt"), "content": "x"}),
            ("tg-secret", "check_tg_secret_bash", None, "Bash", None)):
        r, _ = hook(None, mode, tool=tool, ti=ti, penv={"GUARD_SHIM_BOOM": boom})
        check(f"PreToolUse, {label} — код 2 и причина", blocked(r, "сбой проверки"), r)
    # merge_gate.py в PreToolUse: gh pr merge координатора — сбой запора не пропускает
    r, _ = hook(None, role="domain-coordinator", ti={"command": "gh pr merge 5 --match-head-commit " + "a" * 40},
                penv={"GUARD_SHIM_BOOM": "merge_problem"})
    check("PreToolUse, merge_gate.py (gh pr merge) — код 2", blocked(r, "сбой проверки прав"), r)
    # окно (hq-telegram, chiron): и в окне штаба, и в вашей сессии без роли — блок (раньше у вас — пропуск)
    for label, penv in (("окно штаба", {"PANTHEON_ROLE": "hq"}), ("ваша сессия", {})):
        r, _ = hook(None, tool="Agent", ti={"subagent_type": "x", "prompt": "x"},
                    penv=dict(penv, GUARD_SHIM_BOOM="check_hq_telegram"))
        check(f"PreToolUse Agent, сбой проверки окна, {label} — код 2", blocked(r, "сбой проверки окна"), r)
    # аргументы вызова не объект — сбой скрипта, код 2
    r, _ = hook(None, ti=["ls"])
    check("PreToolUse, tool_input не объект — код 2", blocked(r, "сбой хука"), r)
    # свой срок: проверка висит — код 2 до таймаута хука, а не пропуск по таймауту Claude Code
    r, took = hook(None, penv={"GUARD_SHIM_HANG": "check_domain", "GUARD_SHIM_DEADLINE": "1"})
    check(f"PreToolUse, проверка висит — код 2 за {took:.1f} с", blocked(r, "не уложилась") and took < 8, r)
    # подсказка (dev-server) при сбое пропускает к остальным проверкам — обычная команда проходит
    r, _ = hook(None, penv={"GUARD_SHIM_BOOM": "check_dev_server"})
    check("PreToolUse, сбой подсказки dev-server — пропуск к остальным проверкам (код 0)",
          r.returncode == 0 and r.stdout.strip() == "", r)
    # PostToolUse: сбой записи журнала запора — код 2 (команда уже выполнена, причина — агенту); без сбоя — 0
    post = {"tool_response": {"stdout": "", "stderr": "", "interrupted": False, "isImage": False}}
    r, _ = hook(None, name="PostToolUse", extra=post, penv={"GUARD_SHIM_BOOM": "merge_gate.record"})
    check("PostToolUse, сбой merge_gate.record — код 2 и причина", blocked(r, "журнала шлюза слияния"), r)
    r, _ = hook(None, name="PostToolUse", extra=post)
    check("PostToolUse без сбоя — код 0", r.returncode == 0 and r.stderr == "", r)
    # Stop: сбой — код 0 (код 2 не дал бы закончить ход), причина в stderr и строка в журнале
    r, _ = hook(None, name="Stop", tool=None, extra={"transcript_path": os.path.join(home, "none.jsonl")},
                penv={"GUARD_SHIM_BOOM": "soft"})
    check("Stop, сбой — код 0, без трассировки, с причиной", r.returncode == 0 and "Stop" in r.stderr
          and "Traceback" not in r.stderr and '"block"' not in r.stdout, r)
    # сбой загрузки самого guard (рядом нет merge_gate.py) — тоже код 2 с причиной, на Stop — 0; запуск как у хука
    lone = tempfile.mkdtemp(prefix="guard-lone-")
    shutil.copy(GUARD, lone)
    for label, ev, want in (("PreToolUse", {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                            "tool_input": {"command": "ls"}}, 2),
                            ("Stop", {"hook_event_name": "Stop"}, 0)):
        r = subprocess.run([sys.executable, "-I", os.path.join(lone, "guard.py")], input=json.dumps(ev),
                           capture_output=True, text=True, env=env, timeout=20)
        check(f"сбой загрузки guard (нет merge_gate.py), {label} — код {want} и причина",
              r.returncode == want and "сбой загрузки" in r.stderr and "Traceback" not in r.stderr, r)
    shutil.rmtree(lone, ignore_errors=True)
    # обычные отказ и пропуск прежние: отказ — JSON и код 0
    r, _ = hook(None, role="domain-coordinator", ti={"command": "tmux send-keys -t 0 'да' Enter"})
    check("обычный отказ — JSON deny и код 0, как раньше", r.returncode == 0 and '"deny"' in r.stdout, r)
    return failed


def main():
    home = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home)
    P = lambda rel: os.path.join(home, "ai", "pantheon", rel)
    W = lambda path: ("Write", {"file_path": path, "content": "x"})
    E = lambda path: ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"})
    B = lambda cmd: ("Bash", {"command": cmd})
    R = lambda path: ("Read", {"file_path": path})
    G = lambda path: ("Grep", {"pattern": "налог", "path": path})
    K = lambda rel: os.path.join(home, "ai", "knowledge", rel)
    A = lambda name: ("Agent", {"subagent_type": name, "description": "x", "prompt": "x"})
    HQ = {"PANTHEON_ROLE": "hq"}  # env окна штаба (pantheon start zeus), guard 0.5.5
    TL = {"PANTHEON_ROLE": "themis-library"}  # env окна координатора (tg-role, metis-0267)
    TGR = "tg_read" + ".py"  # имя скрипта tg-read: так этот файл не задевает правило tg-secret живого хука
    br, ak, alex, ws = "projects/shopKeeperApp", "projects/agent-kit", "projects/sitebuilder", "projects/workshop/visa"
    ec, lw = "projects/lecture-notes", "projects/law-feed"
    merge_fixtures(home)
    try:  # без tomllib (Python 3.9) политика пуста — слияние закрыто, это безопасный отказ
        import tomllib  # noqa: F401
        MERGE_OK = "allow"
    except ImportError:
        MERGE_OK = "deny"
    cases = [
        # (имя, ожидание, папка запуска, роль, субагент, (инструмент, вход))
        ("hq пишет доску", "allow", ".", "hq", False, W(P("board.md"))),
        ("субагент не hq — отказ на board.md", "deny", br, "argus", True, W(P("board.md"))),
        ("субагент штаба (chiron) — отказ на board.md", "deny", ".", "chiron", True, E(P("board.md"))),
        ("ваша сессия без роли пишет доску", "allow", ".", "", False, W(P("board.md"))),
        ("координатор пишет свой STATUS.md", "allow", br, "domain-coordinator", False, W(P("directions/athena-shop/STATUS.md"))),
        ("координатор не правит чужой STATUS.md", "deny", br, "domain-coordinator", False, E(P("directions/hermes-site/STATUS.md"))),
        ("лид создаёт новый файл в чужом inbox/", "allow", br, "hephaestus-shop", True, W(P("directions/hermes-site/inbox/new.md"))),
        ("лид не переписывает чужой файл в inbox/", "deny", br, "hephaestus-shop", True, W(P("directions/hermes-site/inbox/old.md"))),
        ("iris не переписывает alerts.md", "deny", ".", "iris", False, W(P("alerts.md"))),
        ("iris дописывает через pantheon alert", "allow", ".", "iris", False, B('pantheon alert "новая версия Claude Code"')),
        ("iris пишет в scout/", "allow", ".", "iris", False, W(P("scout/2026-10-14.md"))),
        ("clio не пишет в scout/", "deny", ".", "clio", False, W(P("scout/x.md"))),
        ("правка в копии — отказ", "deny", br, "domain-coordinator", False, W(os.path.join(home, "ai/pantheon-view/board.md"))),
        ("запись модели в owner-log — отказ", "deny", br, "domain-coordinator", False,
         B(f"echo да >> {home}/.local/state/pantheon/owner-log/athena-shop.md")),
        # metis-0044, п. 1: доска и журналы ваших слов — ни одной сессии Claude, и без роли тоже
        *[(f"0044 без роли: {n} — отказ", "deny", ".", "", False, x) for n, x in (
            ("Write карточки", W(os.path.join(home, "ai/pantheon-view/Доска/athena-0001 Вопрос.md"))),
            ("Edit галочки на карточке", E(os.path.join(home, "ai/pantheon-view/Доска/athena-0001 Вопрос.md"))),
            ("новая карточка", W(os.path.join(home, "ai/pantheon-view/Доска/new.md"))),
            ("Bash >> в карточку", B(f"echo '- [x] Да' >> '{home}/ai/pantheon-view/Доска/athena-0001 Вопрос.md'")),
            ("Bash через ~ и cd", B("cd ~/ai/pantheon-view/Доска && echo x > a.md")),
            ("rm -rf доски", B("rm -rf ~/ai/pantheon-view")),
            ("Write в owner-log", W(os.path.join(home, ".local/state/pantheon/owner-log/zeus.md"))),
            ("Edit board.jsonl", E(os.path.join(home, ".local/state/pantheon/owner-log/board.jsonl"))),
            ("sed -i в owner-log", B("sed -i '' 's/Нет/Да/' ~/.local/state/pantheon/owner-log/board.jsonl")),
            ("mv в owner-log", B("mv /tmp/forged.jsonl ~/.local/state/pantheon/owner-log/board.jsonl")),
            ("регистр пути", W(os.path.join(home, "ai/PANTHEON-VIEW/Доска/x.md"))),
        )],
        ("0044 без роли: запись из cwd доски — отказ", "deny", ".", "", False, B("echo x > a.md"), "ai/pantheon-view/Доска"),
        ("0044 субагент без agent_type: доска — отказ", "deny", ".", "", True, W(os.path.join(home, "ai/pantheon-view/Доска/x.md"))),
        ("0044 ваша роль главной сессии: owner-log — отказ", "deny", ".", "my-helper", False,
         W(os.path.join(home, ".local/state/pantheon/owner-log/board.jsonl"))),
        *[(f"0044 без роли: {n} — можно", "allow", ".", "", False, x) for n, x in (
            ("Read карточки", R(os.path.join(home, "ai/pantheon-view/Доска/athena-0001 Вопрос.md"))),
            ("cat доски и журнала", B(f"cat ~/ai/pantheon-view/Доска/*.md ~/.local/state/pantheon/owner-log/board.jsonl")),
            ("pantheon view и board", B("pantheon view; pantheon board")),
            ("pantheon task set", B("pantheon task set athena-0001 status=doing --note x")),
            ("остальной ~/.local/state/pantheon", W(os.path.join(home, ".local/state/pantheon/logs/x.log"))),
            ("cp в домашнюю папку", B("cp a.md ~/")),
            ("цель не разобрать", B("echo x > $SOMEDIR/a.md")),
            ("файл задачи", E(P("directions/athena-shop/tasks/athena-0001.md"))),
            ("свой проект", W(os.path.join(home, br, "app/x.ts"))),
        )],
        # metis-0044, п. 2: файлы задач — только `pantheon task`, ролям и субагентам, штабу тоже
        *[(f"0044 {r}{' (субагент)' if s else ''}: {n} — отказ", "deny", d, r, s, x, *cwd) for r, s, d, n, x, *cwd in (
            ("hq", False, ".", "Edit answer в чужой задаче", E(P("directions/athena-shop/tasks/athena-0001.md"))),
            ("hq", False, ".", "Write новой задачи", W(P("directions/athena-shop/tasks/athena-0002.md"))),
            ("hq", False, ".", "Write во входящие владельца", W(P("inbox/tasks/inbox-0001.md"))),
            ("hq", False, ".", "Bash >> answer", B(f"echo 'answer: Да' >> {home}/ai/pantheon/directions/athena-shop/tasks/athena-0001.md")),
            ("hq", False, ".", "cp в папку задач", B(f"cp /tmp/t.md {home}/ai/pantheon/directions/athena-shop/tasks/")),
            ("hq", False, ".", "mv задачи", B(f"mv {home}/ai/pantheon/directions/athena-shop/tasks/athena-0001.md /tmp/")),
            ("hq", False, ".", "rm -rf папки задач", B(f"rm -rf {home}/ai/pantheon/directions/athena-shop/tasks")),
            ("hq", False, ".", "регистр TASKS", E(P("directions/athena-shop/TASKS/athena-0001.md"))),
            ("hq", False, ".", "служебный .lock", B(f"touch {home}/ai/pantheon/directions/athena-shop/tasks/.lock")),
            ("domain-coordinator", False, br, "Edit своей задачи", E(P("directions/athena-shop/tasks/athena-0001.md"))),
            ("domain-coordinator", False, br, "sed -i своей задачи",
             B("sed -i '' 's/^status: .*/status: done/' ~/ai/pantheon/directions/athena-shop/tasks/athena-0001.md")),
            ("domain-coordinator", False, br, "из cwd tasks/", B("echo 'answer: Да' >> athena-0001.md"),
             "ai/pantheon/directions/athena-shop/tasks"),
            ("hephaestus-shop", True, br, "Write своей задачи", W(P("directions/athena-shop/tasks/athena-0001.md"))),
            ("general-purpose", True, br, "Edit своей задачи", E(P("directions/athena-shop/tasks/athena-0001.md"))),
            # ревью argus f437a81: запись в папку над tasks/ целиком
            ("hq", False, ".", "cp -R в directions/", B(f"cp -R /tmp/forge/tasks {home}/ai/pantheon/directions/")),
            ("hq", False, ".", "rsync в папку направления", B(f"rsync -a /tmp/forge/ {home}/ai/pantheon/directions/athena-shop/")),
            ("hq", False, ".", "cp во входящие владельца целиком", B(f"cp -R /tmp/forge/tasks {home}/ai/pantheon/inbox/")),
            ("hq", False, ".", "tar -C в directions", B(f"tar -xf /tmp/x.tar -C {home}/ai/pantheon/directions")),
            ("domain-coordinator", False, br, "tar -C в своё направление",
             B("tar -xf /tmp/x.tar -C ~/ai/pantheon/directions/athena-shop")),
            ("domain-coordinator", False, br, "unzip -d в своё направление",
             B("unzip -o /tmp/x.zip -d ~/ai/pantheon/directions/athena-shop")),
            ("domain-coordinator", False, br, "cp в папку своего направления", B("cp /tmp/a.md ~/ai/pantheon/directions/athena-shop/")),
            ("hq", False, ".", "заглушка с другим именем", B(f"touch {home}/ai/pantheon/directions/athena-shop/tasks/.keep.md")),
        )],
        *[(f"0044 {r}: {n} — можно", "allow", d, r, False, x) for r, d, n, x in (
            ("hq", ".", "pantheon task set", B("pantheon task set athena-0001 status=todo next=x --note y")),
            ("hq", ".", "pantheon task new", B("pantheon task new --direction athena-shop --title x")),
            ("domain-coordinator", br, "pantheon task set своей", B("pantheon task set athena-0001 status=doing --note y")),
            ("domain-coordinator", br, "pantheon task claim своей", B("pantheon task claim athena-0001 --by hephaestus")),
            ("hq", ".", "mkdir tasks/ нового направления", B(f"mkdir -p {home}/ai/pantheon/directions/hermes-site/tasks")),
            ("hq", ".", "файл tasks.md рядом с папкой", W(P("directions/athena-shop/tasks.md"))),
            ("domain-coordinator", br, "план эпика", W(P("directions/athena-shop/epic-x.md"))),
            ("hq", ".", "чтение задачи", B(f"cat {home}/ai/pantheon/directions/athena-shop/tasks/athena-0001.md")),
            # ревью argus f437a81: заглушка в tasks/ нового направления (пустую папку тик в git не положит)
            ("hq", ".", "mkdir tasks/ и .gitkeep нового направления",
             B(f"mkdir -p {home}/ai/pantheon/directions/janus-x/tasks && touch {home}/ai/pantheon/directions/janus-x/tasks/.gitkeep")),
            ("hq", ".", "Write .keep в tasks/", W(P("directions/hermes-site/tasks/.keep"))),
            ("hq", ".", "mkdir нового направления", B(f"mkdir -p {home}/ai/pantheon/directions/janus-x")),
            ("domain-coordinator", br, "cp с именем файла в своё направление",
             B("cp /tmp/a.md ~/ai/pantheon/directions/athena-shop/a.md")),
            ("domain-coordinator", br, "mv заявки в inbox/done/", B("mv ~/ai/pantheon/directions/athena-shop/inbox/x.md "
                                                                  "~/ai/pantheon/directions/athena-shop/inbox/done/")),
        )],
        ("роль не коммитит ~/ai/pantheon", "deny", ".", "hq", False, B(f"git -C {home}/ai/pantheon commit -am x")),
        ("ваша сессия коммитит ~/ai/pantheon", "allow", ".", "", False, B(f"git -C {home}/ai/pantheon commit -am x")),
        ("Метида правит карту решений", "allow", ak, "domain-coordinator", False, E(P("decision-map.md"))),
        ("athena не правит карту решений", "deny", br, "domain-coordinator", False, E(P("decision-map.md"))),
        ("реестр не выдаёт прав Метиды", "deny", ak + "/../shopKeeperApp", "domain-coordinator", False, E(P("decision-map.md"))),
        ("athena пишет в свой репозиторий", "allow", br, "domain-coordinator", False, W(os.path.join(home, br, "app/x.ts"))),
        ("athena — отказ на запись в sitebuilder (SEC-12)", "deny", br, "domain-coordinator", False, W(os.path.join(home, alex, "x.md"))),
        ("мастерская пишет в папку задачи", "allow", ws, "workshop", False, W(os.path.join(home, ws, "form.md"))),
        ("мастерская — отказ вне папки задачи", "deny", ws, "workshop", False, W(os.path.join(home, alex, "x.md"))),
        ("prometheus пишет в ~/ai/knowledge (agent_extra)", "allow", br, "prometheus", True, W(os.path.join(home, "ai/knowledge/raw/a.md"))),
        ("dev-server по-прежнему запрещён", "deny", br, "", False, B("pnpm run dev")),
        # обходы через Bash (ревизия шага 0.3, № 5): роль координатора, cwd = ~/ai/pantheon
        ("Bash: >> alerts.md из ~/ai/pantheon", "deny", br, "domain-coordinator", False, B("echo x >> alerts.md"), "ai/pantheon"),
        ("Bash: sed -i board.md из ~/ai/pantheon", "deny", br, "domain-coordinator", False, B("sed -i '' 's/a/b/' board.md"), "ai/pantheon"),
        ("Bash: cd ~/ai/pantheon && sed -i", "deny", br, "domain-coordinator", False, B(f"cd {home}/ai/pantheon && sed -i '' 's/a/b/' board.md")),
        ("Bash: > \"$HOME/ai/pantheon/board.md\"", "deny", br, "domain-coordinator", False, B('echo x > "$HOME/ai/pantheon/board.md"')),
        ("Bash: tee \"$HOME/…\"", "deny", br, "domain-coordinator", False, B('echo x | tee "$HOME/ai/pantheon/board.md"')),
        ("Bash: mv доски как источника", "deny", br, "domain-coordinator", False, B(f"mv {home}/ai/pantheon/board.md /tmp/b.md")),
        ("Bash: (cd ~/ai/pantheon; git commit)", "deny", br, "domain-coordinator", False, B(f"(cd {home}/ai/pantheon; git commit -am x)")),
        ("Bash: git -C ~/ai/pantheon -c k=v commit", "deny", br, "domain-coordinator", False, B(f"git -C {home}/ai/pantheon -c user.name=x commit -m y")),
        ("Bash: чтение ~/ai/pantheon можно", "allow", br, "domain-coordinator", False, B(f"cat {home}/ai/pantheon/board.md && git -C {home}/ai/pantheon log -1")),
        ("Bash: вывод во временную папку можно", "allow", br, "domain-coordinator", False, B("grep x board.md > /tmp/out.txt 2>&1"), "ai/pantheon"),
        ("Bash: heredoc с > внутри текста — не цель", "allow", br, "domain-coordinator", False,
         B("cat > /tmp/note.md <<'EOF'\nстрелка > ~/ai/pantheon/board.md в тексте\nEOF")),
        # команды пульта (№ 6)
        ("координатор: pantheon archive — отказ", "deny", br, "domain-coordinator", False, B("pantheon archive")),
        ("координатор: pantheon jobs pause --all — отказ", "deny", br, "domain-coordinator", False, B("pantheon jobs pause --all")),
        ("координатор: pantheon jobs и alert можно", "allow", br, "domain-coordinator", False, B("pantheon jobs; pantheon alert 'x' --from athena")),
        ("hq: pantheon archive можно", "allow", ".", "hq", False, B("pantheon archive")),
        ("argus: roles build --out TMPDIR/r — можно", "allow", br, "argus", False, B('pantheon roles build --out "$TMPDIR/r"')),
        ("argus: roles build --out /tmp/x --src /tmp/y — можно", "allow", br, "argus", False, B('pantheon roles build --out /tmp/x --src /tmp/y')),
        ("argus: roles build без --out — отказ", "deny", br, "argus", False, B('pantheon roles build')),
        ("argus: roles build --out вне временных папок — отказ", "deny", br, "argus", False, B("pantheon roles build --out /var/agents-x")),
        ("argus: roles build --out $(echo x) — отказ", "deny", br, "argus", False, B('pantheon roles build --out $(echo x)')),
        ("argus: roles build лишний аргумент — отказ", "deny", br, "argus", False, B('pantheon roles build --out /tmp/x --force')),
        ("argus: roles build --out /dev/null — отказ", "deny", br, "argus", False, B('pantheon roles build --out /dev/null')),
        ("argus: roles build --src без --out — отказ", "deny", br, "argus", False, B('pantheon roles build --src /tmp/y')),
        ("hephaestus-shop: roles build --out TMPDIR/r — можно", "allow", br, "hephaestus-shop", False, B('pantheon roles build --out "$TMPDIR/r"')),
        ("hephaestus-shop: roles build --out /tmp/x --src /tmp/y — можно", "allow", br, "hephaestus-shop", False, B('pantheon roles build --out /tmp/x --src /tmp/y')),
        ("hephaestus-shop: roles build без --out — отказ", "deny", br, "hephaestus-shop", False, B('pantheon roles build')),
        ("hephaestus-shop: roles build --out вне временных папок — отказ", "deny", br, "hephaestus-shop", False, B("pantheon roles build --out /var/agents-x")),
        ("hephaestus-shop: roles build --out $(echo x) — отказ", "deny", br, "hephaestus-shop", False, B('pantheon roles build --out $(echo x)')),
        ("hephaestus-shop: roles build лишний аргумент — отказ", "deny", br, "hephaestus-shop", False, B('pantheon roles build --out /tmp/x --force')),
        ("hephaestus-shop: roles build --out /dev/null — отказ", "deny", br, "hephaestus-shop", False, B('pantheon roles build --out /dev/null')),
        ("hephaestus-shop: roles build --src без --out — отказ", "deny", br, "hephaestus-shop", False, B('pantheon roles build --src /tmp/y')),
        ("hq: roles build без --out — можно (привилегированная роль)", "allow", ".", "hq", False, B("pantheon roles build")),
        # tg-secret: tg_read — только командой (правило перенесено из старого хука 14.10)
        ("tg_read командой — можно", "allow", ".", "", False, B("~/projects/other/tg-read/tg_read.py status")),
        ("python -c с импортом tg_read — отказ", "deny", ".", "", False, B('python3 -c "import tg_read; print(1)"')),
        ("код с импортом tg_read в файл — отказ", "deny", ".", "", False,
         ("Write", {"file_path": "/tmp/probe_x.py", "content": "from tg_read import client\n"})),
        ("тест tg-read с импортом — можно", "allow", ".", "", False,
         ("Write", {"file_path": os.path.join(home, "projects/other/tg-read/tests/test_x.py"), "content": "import tg_read\n"})),
        ("текст коммита про tg_read — не код", "allow", ".", "", False, B('git commit -m "import tg_read: README"')),
        ("координатор: своя задача — можно", "allow", br, "domain-coordinator", False, B("pantheon task set athena-0001 status=doing")),
        ("координатор: новая задача своего направления — можно", "allow", br, "domain-coordinator", False,
         B("pantheon task new --direction athena-shop --title x")),
        ("координатор: чужая задача — отказ", "deny", br, "domain-coordinator", False, B("pantheon task set metis-0001 status=done")),
        ("координатор: новая задача чужому направлению — отказ", "deny", br, "domain-coordinator", False,
         B("pantheon task new --direction metis-pantheon --title x")),
        ("координатор: задача, которой нет, — отказ", "deny", br, "domain-coordinator", False, B("pantheon task claim zz-0001 --by a")),
        ("субагент координатора: чужая задача — отказ", "deny", br, "hephaestus-shop", True, B("pantheon task set metis-0001 next=x")),
        ("координатор: task ready и show — можно", "allow", br, "domain-coordinator", False, B("pantheon task ready; pantheon task show metis-0001")),
        ("hq: любая задача — можно", "allow", ".", "hq", False, B("pantheon task set athena-0001 status=todo")),
        ("координатор: terminal-notifier — отказ", "deny", br, "domain-coordinator", False,
         B('terminal-notifier -title "Пантеон" -message "x"')),
        ("субагент: terminal-notifier по пути — отказ", "deny", br, "argus", True, B("/opt/homebrew/bin/terminal-notifier -message x")),
        ("ваша сессия: pantheon uninstall можно", "allow", ".", "", False, B("pantheon uninstall")),
        # роли отдельной сессией (№ 7)
        ("clio сессией: запись в sitebuilder — отказ", "deny", ".", "clio", False, W(os.path.join(home, alex, "x.md"))),
        ("clio сессией: запись в ~/ai/knowledge (agent_extra нет в тестовой политике) — отказ", "deny", ".", "clio", False, W(os.path.join(home, "ai/knowledge/wiki/x.md"))),
        ("prometheus сессией: ~/ai/knowledge по agent_extra", "allow", ".", "prometheus", False, W(os.path.join(home, "ai/knowledge/raw/x.md"))),
        ("iris сессией: policy.toml — отказ", "deny", ".", "iris", False, W(os.path.join(home, ".claude/pantheon/policy.toml"))),
        ("hq пишет в sitebuilder (штаб не ограничен domain)", "allow", ".", "hq", False, W(os.path.join(home, alex, "x.md"))),
        ("субагент без agent_type — отказ на board.md (№ 27)", "deny", br, "", True, W(P("board.md"))),
        ("встроенный субагент — тоже под картой прав ~/ai/pantheon", "deny", "ai/pantheon", "general-purpose", True, W(P("handoff/x/r.md"))),
        ("встроенный субагент координатора — отказ на board.md", "deny", br, "general-purpose", True, B("echo x >> ~/ai/pantheon/board.md")),
        # расхождения разбора (проверка безопасности коммитов)
        ("bash -c с записью в ~/ai/pantheon", "deny", br, "domain-coordinator", False, B('bash -c "echo x > ~/ai/pantheon/board.md"')),
        ("eval с записью в ~/ai/pantheon", "deny", br, "domain-coordinator", False, B('eval "echo x > ~/ai/pantheon/board.md"')),
        ("переменная из той же команды", "deny", br, "domain-coordinator", False, B("P=~/ai/pantheon; echo x > $P/board.md")),
        ("шаблон пути ~/pant*on", "deny", br, "domain-coordinator", False, B("echo x > ~/pant*on/board.md")),
        ("$(…) в цели записи — не разобрать", "deny", br, "domain-coordinator", False, B("echo x > $(echo ~/ai/pantheon)/board.md")),
        ("find -delete в ~/ai/pantheon", "deny", br, "domain-coordinator", False, B("find ~/ai/pantheon -name board.md -delete")),
        ("xargs rm — не разобрать", "deny", br, "domain-coordinator", False, B("ls | xargs rm")),
        ("$(…) в тексте коммита — можно", "allow", br, "domain-coordinator", False, B('git commit -m "$(cat /tmp/msg)"')),
        # раунд 2 проверки безопасности: расхождения разбора с bash и zsh (живая сверка — test_shell_diff.py)
        *[(f"обход: {c!r}", "deny", br, "domain-coordinator", False, B(c)) for c in (
            "echo hi\nrm ~/ai/pantheon/alerts.md", "cd ~/ai/pantheon\nrm alerts.md", "echo $'\\'' > ~/ai/pantheon/board.md #'",
            "touch {.,~/ai/pantheon}/board.md", "command -p rm ~/ai/pantheon/alerts.md", "env -i rm ~/ai/pantheon/alerts.md",
            "nice -n 5 rm ~/ai/pantheon/alerts.md", "read D <<< ~/ai/pantheon; echo x > $D/board.md",
            "echo x > ${P:-~/pantheon}/board.md", "cp -t ~/ai/pantheon a.md", "rsync -a a.md ~/ai/pantheon/board.md --exclude x",
            "sed --in-place=.bak --expression=s/a/b/ ~/ai/pantheon/board.md", "perl -pi -e 's/a/b/' ~/ai/pantheon/board.md",
            "pushd ~/ai/pantheon && rm alerts.md", "f() { rm ~/ai/pantheon/alerts.md; }; f", "if true; then rm ~/ai/pantheon/alerts.md; fi",
            "! rm ~/ai/pantheon/alerts.md", "echo x >& ~/ai/pantheon/board.md", "exec 3<> ~/ai/pantheon/board.md",
            "echo x >! ~/ai/pantheon/board.md", "=rm ~/ai/pantheon/alerts.md", "echo x > >(tee ~/ai/pantheon/board.md)",
            "cat <(rm ~/ai/pantheon/alerts.md)", "r\\\nm ~/ai/pantheon/alerts.md", "rm ~/ai/pantheon/alerts.md #\0",
            "find ~/ai/pantheon -name alerts.md -exec sh -c 'rm \"$0\"' {} \\;", "{rm ~/ai/pantheon/alerts.md}",
            "if [[ -n x ]] rm ~/ai/pantheon/alerts.md", "repeat 1 rm ~/ai/pantheon/alerts.md", "rm ~/ai/pantheon/(alerts|x).md",
            "cd ~/ai/pantheon; cd /tmp; cd -; rm alerts.md",
            "true | cd ~/ai/pantheon; rm alerts.md", "X=~/ai/pantheon; (X=/tmp); rm $X/alerts.md",
            "ln -s ~/ai/pantheon/alerts.md l && echo x > l", "echo x | sh", "sh <<< 'rm ~/ai/pantheon/alerts.md'",
            "awk 'BEGIN{print 1 > \"'$HOME'/pantheon/board.md\"}'", "sed -n 'w '$HOME'/pantheon/board.md' /dev/null",
            "RM ~/ai/PANTHEON/ALERTS.MD", "cd ~/ai/pantheon/directions/athena-shop && git commit -am x",
            "git --git-dir=$HOME/ai/pantheon/.git commit -m x", "git -c alias.x='!rm ~/ai/pantheon/alerts.md' x",
            "hash -p /bin/rm myrm; myrm ~/ai/pantheon/alerts.md", "IFS=:; X=a:$HOME/ai/pantheon/alerts.md; rm $X")],
        *[(f"обычная команда: {c!r}", "allow", br, "domain-coordinator", False, B(c)) for c in (
            "pnpm test", "cd app && pnpm lint", "mkdir -p src/{a,b}/c", "rm -rf node_modules dist",
            "sed -i '' 's/a/b/' src/a.ts", "find . -name '*.log' -delete",
            "git commit -m \"$(cat <<'EOF'\nfeat: x\n\nтело (со скобками) и 'кавычками'\nEOF\n)\"",
            "for f in src/*.ts; do sed -i '' 's/a/b/' \"$f\"; done", "echo hi # комментарий с апострофом don't",
            "set -euo pipefail; pnpm build", "OUT=/tmp/res.txt; pnpm test > \"$OUT\" 2>&1",
            "tmp=$(mktemp -d -p \"$TMPDIR\"); cp src/a.ts \"$tmp\"/", "git add -A && git commit -m 'x' && git push",
            "tar -xzf /tmp/a.tgz -C build", "touch \"$(pwd)/x.txt\"", "rsync -a ~/projects/x/ ./vendor/",
            "ln -s ../shared src/shared", "while read -r l; do echo \"$l\"; done < src/a.ts", "git -C ~/ai/pantheon log -3")],
        # раунд 3: zsh-модификаторы и квалификаторы, cdpath, опасные опции git, переменные-программы, пульт по пути
        *[(f"обход (раунд 3): {c!r}", "deny", br, "domain-coordinator", False, B(c)) for c in (
            "echo x > $PWD:h:h/pantheon/board.md", "echo x > \"$PWD:h:h\"/pantheon/board.md",
            "X=$HOME/ai/pantheon/board.md; rm $X[1,500]", "cd ~/ai/pantheon && ls *(e:'rm alerts.md':)",
            "ls ~/x(+myfunc)", "cdpath=(~); cd pantheon && rm alerts.md",
            "git diff --no-index --output=$HOME/ai/pantheon/board.md /dev/null /dev/null",
            "git grep -O'rm ~/ai/pantheon/alerts.md' x", "git -c core.pager='rm ~/ai/pantheon/alerts.md' log",
            "git ls-remote --upload-pack='rm ~/ai/pantheon/alerts.md' .", "EDITOR='rm ~/ai/pantheon/alerts.md' git commit",
            "export GIT_SSH_COMMAND='rm ~/ai/pantheon/alerts.md'; git fetch",
            "X=--output=$HOME/ai/pantheon/board.md; git log $X", "set -- --output=$HOME/ai/pantheon/board.md; git log \"$1\"",
            "sh ~/.local/bin/pantheon archive", "python3 -I ~/projects/agent-kit/plugins/pantheon/lib/pantheon.py jobs pause x",
            "cp ~/.local/bin/pantheon /tmp/p && /tmp/p archive")],
        *[(f"обычная команда (раунд 3): {c!r}", "allow", br, "domain-coordinator", False, B(c)) for c in (
            "git -c color.ui=false log --oneline -5", "git diff HEAD~1 -- src", "git log --format=%h -3",
            "cp -R ~/ai/pantheon/directions/athena-shop /tmp/backup", "ls ~/ai/pantheon")],
        ("argus не пишет в память штаба", "deny", br, "argus", True, W(os.path.join(home, ".claude/agent-memory/hq/MEMORY.md"))),
        ("argus пишет в свою память", "allow", br, "argus", True, W(os.path.join(home, ".claude/agent-memory/argus/MEMORY.md"))),
        ("hq: регистр не обходит alerts.md", "deny", ".", "hq", False, B("rm ~/ai/PANTHEON/Alerts.md")),
        ("hq: папка, внутри которой ~/ai/pantheon, — отказ", "deny", ".", "hq", False, B("find ~ -name '*.md' -delete")),
        ("hq: обычная правка доски можно", "allow", ".", "hq", False, B("cd ~/ai/pantheon && sed -i '' 's/a/b/' board.md")),
        ("сбой разбора — отказ роли", "deny", br, "domain-coordinator", False, ("Bash", {"command": ["rm", "x"]})),
        ("сбой проверки tg-secret останавливает и вашу сессию (SEC-10)", "deny", br, "", False, ("Bash", {"command": ["rm", "x"]})),
        # protect-config (SEC-14): защиты правит только главная сессия metis-pantheon
        ("protect-config: Метида правит роль", "allow", ak, "domain-coordinator", False, E(os.path.join(home, ".claude/agents/argus.md"))),
        ("protect-config: субагент Метиды не правит роль", "deny", ak, "hephaestus-pantheon", True, E(os.path.join(home, ".claude/agents/argus.md"))),
        ("protect-config: субагент Метиды правит навык (не защита)", "allow", ak, "hephaestus-pantheon", True, W(os.path.join(home, ".claude/skills/x/SKILL.md"))),
        ("protect-config: athena не правит роль", "deny", br, "domain-coordinator", False, E(os.path.join(home, ".claude/agents/argus.md"))),
        ("protect-config: штаб не правит settings.json", "deny", ".", "hq", False, E(os.path.join(home, ".claude/settings.json"))),
        ("protect-config: штаб не дописывает ~/.zshrc", "deny", ".", "hq", False, B("echo 'alias x=y' >> ~/.zshrc")),
        ("protect-config: координатор не правит настройки своего проекта", "deny", br, "domain-coordinator", False, W(os.path.join(home, br, ".claude/settings.local.json"))),
        ("protect-config: субагент Метиды не трогает метку sync", "deny", ak, "hephaestus-pantheon", True, W(os.path.join(home, ".claude/.sync-held"))),
        ("protect-config: субагент Метиды не коммитит claude-config", "deny", ak, "hephaestus-pantheon", True, B("git -C ~/.claude commit -am x")),
        ("protect-config: мастерская не стирает ~/.claude", "deny", ws, "workshop", False, B("rm -rf ~/.claude")),
        ("protect-config: Метида пишет policy.toml", "allow", ak, "domain-coordinator", False, E(os.path.join(home, ".claude/pantheon/policy.toml"))),
        ("protect-config: ваша сессия правит settings.json", "allow", ".", "", False, E(os.path.join(home, ".claude/settings.json"))),
        ("protect-config: штаб не подменяет ссылку тика", "deny", ".", "hq", False, B("ln -sfn /tmp/x ~/.local/share/pantheon/current")),
        ("protect-config: штаб не ставит задачу launchd", "deny", ".", "hq", False, W(os.path.join(home, "Library/LaunchAgents/x.plist"))),
        ("protect-config: координатор не пишет git-хук своего репозитория", "deny", br, "domain-coordinator", False, W(os.path.join(home, br, ".git/hooks/pre-commit"))),
        ("protect-config: координатор не пишет .mcp.json", "deny", br, "domain-coordinator", False, W(os.path.join(home, br, ".mcp.json"))),
        ("protect-config: субагент Метиды не правит инструмент ~/.claude/tools", "deny", ak, "hephaestus-pantheon", True, W(os.path.join(home, ".claude/tools/x.mjs"))),
        ("protect-config: штаб не правит ~/.claude.json (MCP)", "deny", ".", "hq", False, E(os.path.join(home, ".claude.json"))),
        # --- проектные роли <репо>/.claude/agents (metis-0057) ---
        ("protect-config: Write в <репо>/.claude/agents/x.md — отказ", "deny", br, "dev-sonnet", True,
         W(os.path.join(home, br, ".claude/agents/hephaestus-x.md"))),
        ("protect-config: Edit в <репо>/.claude/agents/x.md — отказ", "deny", br, "hephaestus-pantheon", True,
         E(os.path.join(home, br, ".claude/agents/hephaestus-x.md"))),
        ("protect-config: Bash echo > <репо>/.claude/agents/x.md — отказ", "deny", br, "dev-sonnet", True,
         B(f"echo x > {home}/{br}/.claude/agents/x.md")),
        ("protect-config: Bash cp в <репо>/.claude/agents/ — отказ", "deny", br, "domain-coordinator", False,
         B(f"cp a {home}/{br}/.claude/agents/")),
        ("protect-config: Bash mkdir -p <репо>/.claude/agents — отказ", "deny", br, "dev-sonnet", True,
         B(f"mkdir -p {home}/{br}/.claude/agents")),
        ("protect-config: Write в worktree .claude/worktrees/w/.claude/agents — отказ", "deny", br, "dev-sonnet", True,
         W(os.path.join(home, br, ".claude/worktrees/w/.claude/agents/x.md"))),
        ("protect-config: регистр .Claude/Agents — отказ", "deny", br, "dev-sonnet", True,
         W(os.path.join(home, br, ".Claude/Agents/x.md"))),
        ("protect-config: файл в .claude/worktrees/w/src — не задет", "allow", br, "dev-sonnet", True,
         W(os.path.join(home, br, ".claude/worktrees/w/src/a.py"))),
        ("protect-config: <репо>/agents/x.md — не задет", "allow", br, "dev-sonnet", True,
         W(os.path.join(home, br, "agents/x.md"))),
        ("protect-config: <репо>/.claude/agents без роли — не задет", "allow", ".", "", False,
         W(os.path.join(home, br, ".claude/agents/x.md"))),
        ("protect-config: координатор коммитит в своём репозитории", "allow", br, "domain-coordinator", False, B("git commit -am x")),
        # прежние правила (№ 28)
        ("attribution: пометка Claude в коммите — отказ", "deny", br, "", False,
         B('git commit -m "x\n\nCo-' + 'Authored-By: Claude <noreply@' + 'anthropic.com>"')),
        ("cdp: свой скрипт подключения — отказ", "deny", br, "", False,
         ("Write", {"file_path": os.path.join(home, br, "c.mjs"), "content": "read DevTools" + "ActivePort"})),
        ("tg-secret: чтение ключа tg-read — отказ", "deny", br, "", False,
         B("security find-generic-" + "password -s tg-" + "read -w")),
        # --- шаг 1.2: команды пульта start/wake/roles — штаб и вы; approve — только вы ---
        ("hq: pantheon start athena-shop", "allow", "ai/pantheon", "hq", False, B("pantheon start athena-shop --from zeus")),
        ("координатор: pantheon start — отказ", "deny", br, "domain-coordinator", False, B("pantheon start hermes-site")),
        ("субагент: pantheon wake — отказ", "deny", br, "general-purpose", True, B("pantheon wake")),
        ("hq: pantheon approve — отказ", "deny", "ai/pantheon", "hq", False, B("pantheon approve add --site a --allow b")),
        ("вы: pantheon approve", "allow", ".", "", False, B("pantheon approve add --site a --allow b")),
        ("мастерская: pantheon approve list — отказ", "deny", ws, "workshop", False, B("pantheon approve list")),
        # --- шаг 1.2: private (SEC-11, SEC-21) ---
        ("private: argus читает me/ — отказ", "deny", br, "argus", True, R(K("me/finance.md"))),
        ("private: prometheus Grep по всей ~/ai/knowledge — отказ", "deny", br, "prometheus", True, G(K(""))),
        ("private: prometheus Grep по raw/ — можно", "allow", br, "prometheus", True, G(K("raw"))),
        ("private: hq читает me/", "allow", ".", "hq", False, R(K("me/finance.md"))),
        ("private: hq — ключ git-crypt нет", "deny", ".", "hq", False, R(K(".git/git-crypt/keys/default"))),
        ("private: chiron — ключ git-crypt pantheon нет", "deny", ".", "chiron", True, B("cat ~/ai/pantheon/.git/git-crypt/keys/default")),
        ("private: chiron (субагент Зевса) в окне штаба читает me/", "allow", ".", "chiron", True,
         R(K("me/finance.md")), None, HQ),
        # P0-2 (metis-0061): личное chiron — только в окне штаба
        ("private: chiron в окне координатора — me/ отказ", "deny", br, "chiron", True, R(K("me/finance.md")), None,
         {"PANTHEON_ROLE": "domain-coordinator"}),
        ("private: chiron без окна (PANTHEON_ROLE нет) — me/ отказ", "deny", ".", "chiron", True, R(K("me/finance.md"))),
        ("chiron: Agent chiron из окна координатора — отказ", "deny", br, "domain-coordinator", False,
         A("chiron"), None, {"PANTHEON_ROLE": "domain-coordinator"}),
        ("chiron: Task chiron из окна координатора без agent_type — отказ", "deny", br, "", False,
         ("Task", {"subagent_type": "chiron", "prompt": "x"}), None, {"PANTHEON_ROLE": "athena-shop"}),
        ("chiron: Agent chiron из субагента лида — отказ", "deny", br, "hephaestus-shop", True, A("chiron")),
        ("chiron: Agent chiron из штаба — можно", "allow", "ai/pantheon", "hq", False, A("chiron"), None, HQ),
        ("chiron: Agent chiron из главной сессии штаба без agent_type — можно", "allow", "ai/pantheon", "", False,
         A("chiron"), None, HQ),
        ("chiron: Agent chiron из вашей сессии без роли — можно", "allow", ".", "", False, A("chiron")),
        ("chiron: Agent другой субагент из окна координатора — можно", "allow", br, "domain-coordinator", False,
         A("hephaestus-shop"), None, {"PANTHEON_ROLE": "domain-coordinator"}),
        # P0-1 (metis-0060): штабу Telegram закрыт
        ("hq-telegram: Agent tg-reader из штаба — отказ", "deny", "ai/pantheon", "hq", False, A("tg-reader"), None, HQ),
        ("hq-telegram: Task plugin:tg-reader из штаба — отказ", "deny", "ai/pantheon", "", False,
         ("Task", {"subagent_type": "x:tg-reader", "prompt": "x"}), None, HQ),
        ("hq-telegram: Skill telegram-read из штаба — отказ", "deny", "ai/pantheon", "hq", False,
         ("Skill", {"skill": "telegram-read"}), None, HQ),
        ("hq-telegram: Skill plugin:telegram-read из штаба — отказ", "deny", "ai/pantheon", "hq", False,
         ("Skill", {"skill": "tg:telegram-read", "args": "x"}), None, HQ),
        ("hq-telegram: Bash скрипт tg-read из штаба — отказ", "deny", "ai/pantheon", "hq", False,
         B("~/projects/other/tg-read/" + TGR + " dialogs"), None, HQ),
        ("hq-telegram: Bash демон tg-readd из штаба — отказ", "deny", "ai/pantheon", "hq", False,
         B("launchctl kickstart gui/501/tg-readd"), None, HQ),
        ("hq-telegram: Bash обычный из штаба — можно", "allow", "ai/pantheon", "hq", False, B("ls tg-reader-notes"),
         None, HQ),
        ("hq-telegram: Skill другой из штаба — можно", "allow", "ai/pantheon", "hq", False,
         ("Skill", {"skill": "research"}), None, HQ),
        ("hq-telegram: Agent tg-reader из окна координатора — можно", "allow", lw, "domain-coordinator", False,
         A("tg-reader"), None, {"PANTHEON_ROLE": "themis-library"}),
        ("hq-telegram: Skill telegram-read из окна координатора — можно", "allow", lw, "domain-coordinator", False,
         ("Skill", {"skill": "telegram-read"}), None, {"PANTHEON_ROLE": "themis-library"}),
        ("hq-telegram: Agent tg-reader из вашей сессии — можно", "allow", ".", "", False, A("tg-reader")),
        # metis-0267: личную переписку выгружает только исполнитель pantheon read — окну любой роли отказ
        ("tg-role: координатор history — отказ", "deny", lw, "domain-coordinator", False,
         B("~/projects/other/tg-read/" + TGR + " history 12345 --days 3"), None, TL),
        ("tg-role: главная сессия окна без agent_type, search — отказ", "deny", lw, "", False,
         B("cd ~/projects/other/tg-read && ./" + TGR + " search 'договор'"), None, TL),
        ("tg-role: координатор unread — отказ", "deny", lw, "domain-coordinator", False,
         B("uv run --project ~/projects/other/tg-read ~/projects/other/tg-read/" + TGR + " unread"), None, TL),
        ("tg-role: координатор context — отказ", "deny", lw, "domain-coordinator", False,
         B('python3 "$HOME/projects/other/tg-read/' + TGR + '" context 12345 77'), None, TL),
        ("tg-role: субагент tg-reader в окне роли, download — отказ", "deny", lw, "tg-reader", True,
         B("~/projects/other/tg-read/" + TGR + " download 12345 --files-max 3"), None, TL),
        ("tg-role: координатор к сокету tg-readd — отказ", "deny", lw, "domain-coordinator", False,
         B('nc -U "$HOME/Library/Application Support/tg-read/tg-readd.sock"'), None, TL),
        # ревью argus PR #61: форма из навыка telegram-read и обёртки — команды из bash_analysis
        ("tg-role: T=…; $T history (форма навыка) — отказ", "deny", lw, "domain-coordinator", False,
         B("T=~/projects/other/tg-read/" + TGR + "; $T history 12345 --days 7 -o x.md"), None, TL),
        ("tg-role: T=… с новой строки, $T history — отказ", "deny", lw, "domain-coordinator", False,
         B("T=~/projects/other/tg-read/" + TGR + '\n$T history "ЧАТ" --days 7'), None, TL),
        ("tg-role: C=history; tg_read.py $C — отказ", "deny", lw, "domain-coordinator", False,
         B("C=history; ~/projects/other/tg-read/" + TGR + " $C 1"), None, TL),
        ("tg-role: перенос \\ перед подкомандой — отказ", "deny", lw, "domain-coordinator", False,
         B("~/projects/other/tg-read/" + TGR + " \\\n  history 1"), None, TL),
        ("tg-role: tg_read.py -- history — отказ", "deny", lw, "domain-coordinator", False,
         B("~/projects/other/tg-read/" + TGR + " -- history 1"), None, TL),
        ("tg-role: echo history | xargs tg_read.py — отказ", "deny", lw, "domain-coordinator", False,
         B("echo history 1 | xargs ~/projects/other/tg-read/" + TGR), None, TL),
        ("tg-role: подкоманда из $(…) — отказ", "deny", lw, "domain-coordinator", False,
         B("~/projects/other/tg-read/" + TGR + " $(echo history) 1"), None, TL),
        ("tg-role: имя скрипта другим регистром — отказ", "deny", lw, "domain-coordinator", False,
         B("~/projects/other/tg-read/" + TGR.upper() + " history 1"), None, TL),
        ("tg-role: bash -c с history — отказ", "deny", lw, "domain-coordinator", False,
         B("bash -c '~/projects/other/tg-read/" + TGR + " search x'"), None, TL),
        ("tg-role: status, затем history в одной команде — отказ", "deny", lw, "domain-coordinator", False,
         B("~/projects/other/tg-read/" + TGR + " status; ~/projects/other/tg-read/" + TGR + " history 1"), None, TL),
        ("tg-role: команду не разобрать (шаблон zsh с кодом), в ней скрипт — отказ", "deny", lw, "domain-coordinator",
         False, B("~/projects/other/tg-read/" + TGR + " history *(e:true:)"), None, TL),
        ("tg-role: имя скрипта шаблоном tg_rea?.py — отказ", "deny", lw, "domain-coordinator", False,
         B("~/projects/other/tg-read/tg_rea?.py history 1"), None, TL),
        ("tg-role: сокет шаблоном tg-read/*.sock — отказ", "deny", lw, "domain-coordinator", False,
         B('nc -U "$HOME/Library/Application Support/tg-read/"*.sock'), None, TL),
        ("tg-role: чужой шаблон /tmp/*.sock — можно", "allow", lw, "domain-coordinator", False,
         B("ls /tmp/*.sock"), None, TL),
        ("tg-role: T=…; $T posts — можно", "allow", lw, "domain-coordinator", False,
         B("T=~/projects/other/tg-read/" + TGR + "; $T posts @lawfeed --days 2"), None, TL),
        ("tg-role: python3 tg_read.py posts — можно", "allow", lw, "domain-coordinator", False,
         B("python3 ~/projects/other/tg-read/" + TGR + " posts @lawfeed"), None, TL),
        ("tg-role: grep history по tg_read.py — можно", "allow", lw, "domain-coordinator", False,
         B("grep -n history ~/projects/other/tg-read/" + TGR), None, TL),
        ("tg-role: координатор posts — можно", "allow", lw, "domain-coordinator", False,
         B("~/projects/other/tg-read/" + TGR + " posts @lawfeed --days 2"), None, TL),
        ("tg-role: координатор posts со словом history в аргументах — можно", "allow", lw, "domain-coordinator", False,
         B("~/projects/other/tg-read/" + TGR + " posts @lawfeed --search history"), None, TL),
        ("tg-role: координатор status, chats, folders — можно", "allow", lw, "domain-coordinator", False,
         B("; ".join(
             "~/projects/other/tg-read/" + TGR + " " + c for c in ("status", "chats", "folders"))), None, TL),
        ("tg-role: координатор verify и split — можно", "allow", lw, "domain-coordinator", False,
         B("~/projects/other/tg-read/" + TGR + " verify a.md b.txt && ~/projects/other/tg-read/" + TGR
           + " split b.txt"), None, TL),
        ("tg-role: без роли (плановый проход) history — можно", "allow", ".", "", False,
         B("~/projects/other/tg-read/" + TGR + " history 12345 --days 3")),
        ("tg-role: без роли к сокету tg-readd — можно", "allow", ".", "", False,
         B('nc -U "$HOME/Library/Application Support/tg-read/tg-readd.sock"')),
        # metis-0047: пульт окон — только привилегированным
        ("координатор: pantheon stop --all — отказ", "deny", br, "domain-coordinator", False, B("pantheon stop --all")),
        ("координатор: pantheon resume — отказ", "deny", br, "domain-coordinator", False, B("pantheon resume athena-shop")),
        ("координатор: pantheon pause — отказ", "deny", br, "domain-coordinator", False, B("pantheon pause hermes-site")),
        ("координатор: pantheon restart — отказ", "deny", br, "domain-coordinator", False, B("pantheon restart hermes-site")),
        ("hq: pantheon stop --all можно", "allow", "ai/pantheon", "hq", False, B("pantheon stop --all")),
        ("hq: pantheon resume, pause, restart можно", "allow", "ai/pantheon", "hq", False,
         B("pantheon resume athena-shop; pantheon pause hermes-site; pantheon restart hermes-site")),
        ("координатор: pantheon saved и who можно", "allow", br, "domain-coordinator", False,
         B("pantheon saved; pantheon who")),
        ("координатор: pantheon jobs resume --all — отказ, как раньше", "deny", br, "domain-coordinator", False,
         B("pantheon jobs resume --all")),
        ("hq: pantheon jobs pause --all можно, как раньше", "allow", "ai/pantheon", "hq", False,
         B("pantheon jobs pause --all")),
        # metis-0084: hq — поиск по папке выше ключа можно, явный путь в ключ — отказ
        ("private: hq grep -rn по ~/ai/pantheon — можно", "allow", "ai/pantheon", "hq", False,
         B(f"grep -rn foo {home}/ai/pantheon"), None, HQ),
        ("private: hq Grep по ~/ai/pantheon — можно", "allow", "ai/pantheon", "hq", False, G(P("")), None, HQ),
        ("private: hq Glob **/*.md по ~/ai/pantheon — можно", "allow", "ai/pantheon", "hq", False,
         ("Glob", {"pattern": "**/*.md", "path": P("")}), None, HQ),
        ("private: hq cat ключа git-crypt — отказ", "deny", "ai/pantheon", "hq", False,
         B(f"cat {home}/ai/pantheon/.git/git-crypt/keys/default"), None, HQ),
        ("private: hq ls .git/* (шаблон раскрывается в ключ) — отказ", "deny", "ai/pantheon", "hq", False,
         B(f"ls {home}/ai/pantheon/.git/*"), None, HQ),
        ("private: hq Glob .git/git-crypt/** — отказ", "deny", "ai/pantheon", "hq", False,
         ("Glob", {"pattern": ".git/git-crypt/**", "path": P("")}), None, HQ),
        ("private: argus grep -r по ~/ai/knowledge — отказ, как раньше", "deny", br, "argus", True,
         B(f"grep -r foo {home}/ai/knowledge")),
        ("private: mnemo-brain пишет в me/", "allow", "ai/knowledge", "domain-coordinator", False, W(K("me/x.md"))),
        ("push: mnemo-brain не отправляет сам (SEC-13)", "deny", "ai/knowledge", "domain-coordinator", False,
         B("git push origin wiki-sync")),
        ("push: mnemo-brain коммитит", "allow", "ai/knowledge", "domain-coordinator", False, B("git commit -qm wiki")),
        # проверка безопасности 15.10: обходы правил ролей
        ("push: + в refspec — принудительная, отказ", "deny", br, "hephaestus-shop", True, B("git push origin +epic-tax")),
        ("push: gh api PUT …/merge — отказ", "deny", br, "hephaestus-shop", True,
         B("gh api -X PUT repos/o/r/pulls/1/merge")),
        ("push: gh api -f (POST) — отказ", "deny", br, "domain-coordinator", False,
         B("gh api repos/o/r/git/refs -f ref=refs/heads/main -f sha=1")),
        ("push: gh api чтение — можно", "allow", br, "hephaestus-shop", True, B("gh api repos/o/r/pulls/1")),
        ("private: глоб m?/ в личное — отказ", "deny", br, "dev-sonnet", True, B("cat ~/ai/knowledge/m?/finance.md")),
        ("private: глоб ~/ai/*/me — отказ", "deny", br, "argus", True, B("ls ~/ai/*/me")),
        ("private: глоб в raw/ — можно", "allow", br, "prometheus", True, B("cat ~/ai/knowledge/raw/*.md")),
        ("cdp: 127.1:9222 — отказ", "deny", br, "dev-sonnet", True, B("curl -s http://127.1:9222/json")),
        ("cdp: nc localhost 9222 — отказ", "deny", br, "dev-sonnet", True, B("nc localhost 9222")),
        ("cdp: 0x7f000001:9333 — отказ", "deny", br, "dev-sonnet", True, B("curl http://0x7f000001:9333/eval")),
        ("cdp: WebFetch на демон — отказ", "deny", br, "dev-sonnet", True,
         ("WebFetch", {"url": "http://127.0.0.1:9333/eval", "prompt": "x"})),
        ("cdp: WebFetch на имя петли (localtest.me) — отказ", "deny", br, "dev-sonnet", True,
         ("WebFetch", {"url": "http://localtest.me:9333/events", "prompt": "x"})),
        ("cdp: WebFetch на 127.0.0.1.nip.io — отказ", "deny", br, "dev-sonnet", True,
         ("WebFetch", {"url": "http://127.0.0.1.nip.io:9333/", "prompt": "x"})),
        ("cdp: 92\"22\" в кавычках — отказ", "deny", br, "dev-sonnet", True, B('curl http://127.0.0.1:92"22"/json')),
        ("private: глоб {me,x} — отказ", "deny", br, "dev-sonnet", True, B("cat ~/ai/knowledge/{me,x}/finance.md")),
        ("push: лид отправляет чужой репозиторий (git -C) — отказ", "deny", br, "hephaestus-shop", True,
         B("git -C ~/projects/sitebuilder push origin feat")),
        ("push: координатор cd в чужой репозиторий — отказ", "deny", br, "domain-coordinator", False,
         B("cd ~/projects/sitebuilder && git push origin feat")),
        ("cdp: WebFetch в интернет — можно", "allow", br, "dev-sonnet", True,
         ("WebFetch", {"url": "https://nextjs.org/docs", "prompt": "x"})),
        ("cdp: ваша сессия WebFetch localhost — можно", "allow", br, "", False,
         ("WebFetch", {"url": "http://localhost:3000/", "prompt": "x"})),
        ("private: субагент mnemo-brain — отказ", "deny", "ai/knowledge", "general-purpose", True, R(K("me/finance.md"))),
        ("private: athena после cd ~/ai/knowledge — отказ", "deny", br, "domain-coordinator", False,
         B(f"cd {home}/ai/knowledge && cat me/finance.md")),
        ("private: Метида — отказ (SEC-21)", "deny", ak, "domain-coordinator", False, R(K("me/finance.md"))),
        ("private: workshop Glob ~/ai/knowledge/me/** — отказ", "deny", ws, "workshop", False,
         ("Glob", {"pattern": f"{home}/ai/knowledge/me/**/*.md"})),
        ("private: журнал штаба zeus.md — отказ координатору", "deny", br, "domain-coordinator", False,
         R(os.path.join(home, ".local/state/pantheon/owner-log/zeus.md"))),
        ("private: ваша сессия без роли читает me/", "allow", ".", "", False, R(K("me/finance.md"))),
        ("private: rg по ~/ai/knowledge — отказ prometheus", "deny", br, "prometheus", True, B(f"rg налог {home}/ai/knowledge")),
        ("private: ls ~/ai/knowledge — можно", "allow", br, "prometheus", True, B(f"ls {home}/ai/knowledge")),
        # --- cdp-role (SEC-13, BROW-06, SEC-21) ---
        ("cdp: координатор вызывает демон — отказ", "deny", br, "domain-coordinator", False,
         B("curl -s 127.0.0.1:9333/health")),
        ("cdp: Метида вызывает демон — отказ", "deny", ak, "domain-coordinator", False,
         B("curl -s -X POST localhost:9334/eval -d '{}'")),
        ("cdp: мастерская действует через демон", "allow", ws, "workshop", False,
         B("curl -s -X POST 127.0.0.1:9333/cmd -d '{}'")),
        ("cdp: prometheus /eval — отказ (демон только мастерской)", "deny", br, "prometheus", True, B("curl -s -X POST 127.0.0.1:9333/eval -d '{}'")),
        ("cdp: prometheus curl 127.0.0.1:9333/open — отказ", "deny", br, "prometheus", True, B("curl -s -X POST 127.0.0.1:9333/open -d '{}'")),
        ("cdp: prometheus /cmd — отказ", "deny", br, "prometheus", True, B("curl -s -X POST 127.0.0.1:9333/cmd -d '{}'")),
        ("cdp: /close — отказ и мастерской", "deny", ws, "workshop", False, B("curl -s -X POST 127.0.0.1:9333/close")),
        ("cdp: hq запускает демон — отказ", "deny", ".", "hq", False, B("node ~/.claude/tools/cdp-daemon.mjs chromium")),
        ("cdp: ваша сессия без роли — можно", "allow", ".", "", False, B("curl -s 127.0.0.1:9333/health")),
        *[(f"mktemp: {c!r} — запись в $TMPDIR, можно", "allow", br, "dev-sonnet", True, B(c)) for c in (
            'f=$(mktemp -p "$TMPDIR"); echo x > $f', 'f=$(mktemp -p $TMPDIR); echo x > $f',
            'f=$(mktemp -p "${TMPDIR}"); echo x > $f', 'f=$(mktemp -d -p "$TMPDIR"); echo x > $f/a',
            'f=$(mktemp -p "$TMPDIR" -t foo); echo x > $f', 'f=$(mktemp -t foo -p "$TMPDIR"); echo x > $f')],
        *[(f"mktemp: {c!r} — не в $TMPDIR, цель не разобрать", "deny", br, "dev-sonnet", True, B(c)) for c in (
            'f=$(mktemp); echo x > $f', 'f=$(mktemp -d); echo x > $f/a', 'f=$(mktemp -t foo); echo x > $f')],
        ("mktemp: -p в личную папку — как обычная запись, отказ", "deny", br, "dev-sonnet", True,
         B(f"f=$(mktemp -p {home}/ai/pantheon); echo x > $f")),
        ("tg-readd: роль — status можно", "allow", br, "dev-sonnet", True, B("tg-readd status")),
        ("tg-readd: роль — kickstart можно", "allow", br, "dev-sonnet", True, B("tg-readd kickstart")),
        ("tg-readd: роль — logout отказ", "deny", br, "dev-sonnet", True, B("tg-readd logout")),
        ("tg-readd: роль — login отказ", "deny", br, "argus", True, B("tg-readd login")),
        ("tg-readd: роль — путь к бинарю, logout отказ", "deny", br, "dev-sonnet", True,
         B("/usr/local/opt/tg-readd/bin/tg-readd logout")),
        ("tg-readd: роль — tg-readd-update отказ", "deny", br, "dev-sonnet", True, B("tg-readd-update")),
        ("tg-readd: роль — tg-readd-uninstall отказ", "deny", br, "dev-sonnet", True, B("tg-readd-uninstall")),
        ("tg-readd: роль — tg-readd-acl-test отказ", "deny", br, "dev-sonnet", True, B("tg-readd-acl-test")),
        ("tg-readd: env tg-readd logout — отказ", "deny", br, "dev-sonnet", True, B("env tg-readd logout")),
        ("tg-readd: sh -c 'tg-readd logout' — отказ", "deny", br, "dev-sonnet", True, B("sh -c 'tg-readd logout'")),
        ("tg-readd: переменная X=logout — отказ", "deny", br, "dev-sonnet", True, B("X=logout; tg-readd $X")),
        ("tg-readd: env tg-readd status — можно", "allow", br, "dev-sonnet", True, B("env tg-readd status")),
        ("tg-readd: launchctl bootout — отказ", "deny", br, "dev-sonnet", True,
         B("launchctl bootout gui/501/local.tg-read.daemon")),
        ("tg-readd: launchctl kill — отказ", "deny", br, "dev-sonnet", True,
         B("launchctl kill TERM system/local.tg-read.daemon")),
        ("tg-readd: launchctl unload -w — отказ", "deny", br, "dev-sonnet", True,
         B("launchctl unload -w ~/Library/LaunchAgents/local.tg-read.daemon.plist")),
        ("tg-readd: sudo launchctl unload — отказ", "deny", br, "dev-sonnet", True,
         B("sudo launchctl unload /Library/LaunchDaemons/local.tg-read.daemon.plist")),
        ("tg-readd: launchctl stop — отказ", "deny", br, "dev-sonnet", True,
         B("launchctl stop local.tg-read.daemon")),
        ("tg-readd: владелец launchctl stop — можно", "allow", ".", "", False,
         B("launchctl stop local.tg-read.daemon")),
        ("tg-readd: launchctl print — можно", "allow", br, "dev-sonnet", True,
         B("launchctl print gui/501/local.tg-read.daemon")),
        ("tg-readd: sudo rm в /usr/local/opt/tg-readd — отказ", "deny", br, "dev-sonnet", True,
         B("sudo rm -rf /usr/local/opt/tg-readd")),
        ("tg-readd: сессия владельца logout — можно", "allow", ".", "", False, B("tg-readd logout")),
        ("tg-readd: владелец bootout — можно", "allow", ".", "", False,
         B("launchctl bootout gui/501/local.tg-read.daemon")),
        # launchd-env (metis-0298): окружение launchd наследует тик pantheon — роли его не меняют
        *[(f"launchd-env: {c!r} — отказ", "deny", br, "dev-opus", True, B(c)) for c in (
            "launchctl setenv PANTHEON_TOUCHID /tmp/x", "launchctl unsetenv PATH",
            "launchctl setenv PANTHEON_STATE /tmp/st", "launchctl setenv PATH /tmp/bin:/usr/bin",
            "/bin/launchctl setenv PATH /tmp/bin", "env X=1 launchctl setenv PATH /tmp/bin",
            "sudo launchctl setenv PATH /tmp/bin", "sh -c 'launchctl unsetenv PATH'",
            "A=setenv; launchctl $A PATH /tmp/bin", "launchctl config user path /tmp/bin")],
        ("launchd-env: координатор launchctl setenv — отказ", "deny", br, "domain-coordinator", False,
         B("launchctl setenv PANTHEON_TOUCHID /tmp/x")),
        *[(f"launchd-env: {c!r} — можно", "allow", br, "dev-opus", True, B(c)) for c in (
            "launchctl list", "launchctl print gui/501/pantheon.tick", "launchctl getenv PATH")],
        ("launchd-env: владелец launchctl setenv — можно", "allow", ".", "", False, B("launchctl setenv X 1")),
        *[(f"launchd-env: {c!r} — отказ", "deny", br, "dev-opus", True, B(c)) for c in (
            "swiftc x.swift", "/opt/homebrew/bin/swiftc x.swift", "xcrun swiftc x.swift", "S=swiftc; $S x.swift",
            "/usr/bin/swiftc a.swift; swiftc b.swift")],
        *[(f"launchd-env: {c!r} — можно", "allow", br, "dev-opus", True, B(c)) for c in (
            "/usr/bin/swiftc x.swift", "env A=1 /usr/bin/swiftc -o out x.swift", "grep -n swiftc merge.py")],
        ("launchd-env: владелец swiftc — можно", "allow", ".", "", False, B("swiftc x.swift")),
        ("cdp: мастерская мимо демона на 9222 — отказ", "deny", ws, "workshop", False, B("curl -s 127.0.0.1:9222/json/version")),
        ("cdp: prometheus читает DevToolsActivePort — отказ", "deny", br, "prometheus", True,
         B("cat ~/Library/Application\\ Support/Chromium/DevToolsActivePort")),
        ("cdp: ws devtools/browser — отказ", "deny", br, "dev-sonnet", True,
         B("node -e \"new WebSocket('ws://127.0.0.1:9222/devtools/browser/x')\"")),
        ("cdp: ваша сессия на 9222 — можно", "allow", ".", "", False, B("curl -s 127.0.0.1:9222/json/version")),
        # --- push (DONE-07, SEC-13) ---
        ("push: координатор отправляет ветку эпика", "allow", br, "domain-coordinator", False, B("git push")),
        ("push: лид — в develop", "allow", br, "hephaestus-shop", True, B("git push origin epic-tax:develop")),
        ("push: лид — в main — отказ", "deny", br, "hephaestus-shop", True, B("git push origin develop:main")),
        ("push: HEAD:refs/heads/master — отказ", "deny", br, "domain-coordinator", False, B("git push origin HEAD:refs/heads/master")),
        ("push: текущая ветка main — отказ", "deny", alex, "domain-coordinator", False, B("git push")),
        ("push: --force — отказ", "deny", br, "domain-coordinator", False, B("git push --force-with-lease origin epic-tax")),
        ("push: удаление ветки — отказ", "deny", br, "domain-coordinator", False, B("git push origin :develop")),
        ("push: --all — отказ", "deny", br, "domain-coordinator", False, B("git push --all")),
        ("push: dev-sonnet — отказ", "deny", br, "dev-sonnet", True, B("git push origin epic-tax")),
        ("push: argus — отказ", "deny", br, "argus", True, B("git -C . push origin x")),
        ("push: hq — отказ", "deny", ".", "hq", False, B("git push origin x")),
        ("push: cd и push без ветки — отказ", "deny", br, "domain-coordinator", False, B(f"cd {home}/{alex} && git push")),
        # до 0.5.0 здесь был отказ: Афины нет в [merge]. С 0.5.0 свои папки берутся из domains.json, и
        # shopKeeperApp — её продукт ([merge_client]): слияние открыто, talos и откат — обязанность роли
        ("push: gh pr merge Афиной в своём продукте — можно (0.5.0)", MERGE_OK, br, "domain-coordinator", False,
         B("gh pr merge 12 --merge")),
        ("push: ваша сессия в main — можно", "allow", alex, "", False, B("git push origin main")),
        ("push: git push внутри текста коммита — не отправка", "allow", br, "dev-sonnet", True,
         B("git commit -m 'не делать git push в main'")),
        # --- terminal (SEC-30) ---
        ("terminal: osascript — отказ координатору", "deny", br, "domain-coordinator", False,
         B("osascript -e 'tell application \"iTerm2\" to tell current session of current window to write text \"да\"'")),
        ("terminal: tmux send-keys — отказ", "deny", br, "dev-haiku", True, B("tmux send-keys -t 0 'да' Enter")),
        ("terminal: env osascript — отказ", "deny", ws, "workshop", False, B("env osascript -e 'beep'")),
        ("terminal: screen stuff — отказ", "deny", br, "domain-coordinator", False, B("screen -S x -X stuff 'да\\n'")),
        ("terminal: ваша сессия без роли — можно", "allow", ".", "", False, B("osascript -e 'beep'")),
        # --- corpus-role (metis-0021) ---
        ("corpus-role: corpus add — отказ координатору", "deny", br, "domain-coordinator", False,
         B("corpus add https://youtu.be/x")),
        ("corpus-role: uv run corpus krisp import — отказ", "deny", br, "dev-sonnet", True,
         B("uv run corpus krisp import a.m4a")),
        ("corpus-role: .venv/bin/corpus channel --videos — отказ", "deny", br, "domain-coordinator", False,
         B(".venv/bin/corpus channel t.me/x --author lecturer --videos")),
        ("corpus-role: python -m lecture_notes add — отказ", "deny", br, "domain-coordinator", False,
         B("python3 -m lecture_notes add https://rutube.ru/x")),
        ("corpus-role: bash -c corpus add — отказ", "deny", br, "domain-coordinator", False, B("bash -c 'corpus add u'")),
        ("corpus-role: скрипт удаления Krisp — отказ", "deny", br, "dev-sonnet", True,
         B("uv run python tools/krisp_trash.py --id 1")),
        ("corpus-role: ключ Диска из Связки — отказ", "deny", br, "domain-coordinator", False,
         B("security find-generic-password -s lecture-notes-yadisk -a token -w")),
        ("corpus-role: python3 tools/krisp_trash.py — отказ", "deny", br, "domain-coordinator", False,
         B("python3 tools/krisp_trash.py --id 1")),
        ("corpus-role: python3 -I tools/ydapi.py — отказ", "deny", br, "domain-coordinator", False,
         B("python3 -I tools/ydapi.py")),
        ("corpus-role: python3 -X dev tools/restructure_apply.py — отказ", "deny", br, "dev-sonnet", True,
         B("python3 -X dev tools/restructure_apply.py")),
        ("corpus-role: python -m tools.krisp_trash — отказ", "deny", br, "domain-coordinator", False,
         B("python -m tools.krisp_trash")),
        ("corpus-role: штаб python3 tools/ydapi.py — отказ", "deny", ".", "hq", False, B("python3 tools/ydapi.py")),
        ("corpus-role: python3 своего скрипта — можно", "allow", br, "domain-coordinator", False,
         B("python3 tools/report.py")),
        ("corpus-role: corpus search — можно", "allow", br, "domain-coordinator", False, B("corpus search задаток")),
        ("corpus-role: corpus channel без --videos — отказ (канал Telegram, metis-0065)", "deny", br,
         "domain-coordinator", False, B("corpus channel t.me/x --author lecturer")),
        ("corpus-role: чтение скрипта — можно", "allow", br, "dev-sonnet", True, B("cat tools/krisp_trash.py")),
        ("corpus-role: штаб ищет в корпусе — отказ", "deny", ".", "hq", False, B("corpus search задаток")),
        ("corpus-role: ваша сессия без роли — можно", "allow", ".", "", False, B("corpus add https://youtu.be/x")),
        ("corpus-role: stage fetch — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B('corpus stage --job a fetch https://x')),
        ("corpus-role: stage process — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B('corpus stage process --job a')),
        ("corpus-role: stage upload — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B('corpus stage upload --job a')),
        ("corpus-role: channel — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B('corpus channel t.me/x --author k')),
        ("corpus-role: в кавычках stage — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B('"corpus" stage process --job a')),
        ("corpus-role: в кавычках channel — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B("'corpus' channel t.me/x --author k")),
        ("corpus-role: ~/.local/bin/corpus stage — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B('~/.local/bin/corpus stage upload --job a')),
        ("corpus-role: $HOME/.local/bin/corpus channel — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B('$HOME/.local/bin/corpus channel t.me/x')),
        ("corpus-role: абсолютный путь — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B('/opt/x/bin/corpus stage fetch --job a u')),
        ("corpus-role: python -m lecture_notes stage — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B('python3 -m lecture_notes stage --job a fetch https://x')),
        ("corpus-role: цепочка channel — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B('echo a && corpus channel t.me/x --author k')),
        ("corpus-role: uv run stage — отказ (metis-0065)", "deny", br, "dev-sonnet", True,
         B('uv run corpus stage process --job a')),
        ("corpus-role: corpus search — можно (metis-0065)", "allow", br, "dev-sonnet", True,
         B('corpus search "x"')),
        ("corpus-role: corpus show — можно (metis-0065)", "allow", br, "dev-sonnet", True,
         B('corpus show k:1@00:01:00')),
        ("corpus-role: corpus verify — можно (metis-0065)", "allow", br, "dev-sonnet", True,
         B('corpus verify "x"')),
        ("corpus-role: corpus list — можно (metis-0065)", "allow", br, "dev-sonnet", True,
         B('corpus list')),
        ("corpus-role: ваша сессия без роли, corpus stage — можно", "allow", ".", "", False,
         B("corpus stage process --job a")),
        # --- push: gh pr merge координатору из [merge] (metis-0027) ---
        ("merge: Фемида сливает свой PR — можно", MERGE_OK, ec, "domain-coordinator", False, B("gh pr merge 1 --squash")),
        ("merge: Фемида без номера (текущая ветка) — отказ: запор сверяет записи на номер", "deny", ec,
         "domain-coordinator", False,
         B("gh pr merge --merge --delete-branch")),
        ("merge: Фемида с заголовком слияния — можно", MERGE_OK, ec, "domain-coordinator", False,
         B("gh pr merge 1 --squash --subject 'Индекс только для чтения'")),
        ("merge: Фемида с --admin — отказ", "deny", ec, "domain-coordinator", False, B("gh pr merge 1 --admin")),
        ("merge: Фемида с --admin=true — отказ", "deny", ec, "domain-coordinator", False, B("gh pr merge 1 --admin=true")),
        ("merge: Фемида в чужой репозиторий -R — отказ", "deny", ec, "domain-coordinator", False,
         B("gh pr merge 1 -R latark/sitebuilder")),
        ("merge: Фемида по ссылке — отказ", "deny", ec, "domain-coordinator", False,
         B("gh pr merge https://github.com/latark/sitebuilder/pull/1")),
        ("merge: Фемида через cd в чужую папку — отказ", "deny", ec, "domain-coordinator", False,
         B(f"cd {home}/{alex} && gh pr merge 1")),
        ("merge: лид Фемиды (hephaestus-library) — можно (metis-0054)", MERGE_OK, ec, "hephaestus-library", True,
         B("gh pr merge 1")),
        ("merge: лид Фемиды с --admin — отказ", "deny", ec, "hephaestus-library", True, B("gh pr merge 1 --admin")),
        ("merge: dev-sonnet Фемиды — отказ", "deny", ec, "dev-sonnet", True, B("gh pr merge 1")),
        ("merge: Фемида с GH_REPO — отказ", "deny", ec, "domain-coordinator", False,
         B("GH_REPO=latark/sitebuilder gh pr merge 1")),
        ("merge: Фемида gh pr -R … merge — отказ", "deny", ec, "domain-coordinator", False,
         B("gh pr -R latark/sitebuilder merge 1")),
        ("merge: Афина gh pr -R … merge — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr -R latark/sitebuilder merge 1")),
        ("merge: Фемида $N вместо номера — отказ", "deny", ec, "domain-coordinator", False, B("gh pr merge $N")),
        ("merge: Афина gh pr create --title merge — можно", "allow", br, "domain-coordinator", False,
         B("gh pr create --title merge --body x")),
        ("merge: Фемида gh pr list -S merge — можно", "allow", ec, "domain-coordinator", False, B("gh pr list -S merge")),
        ("merge: Афина gh pr checkout merge — можно", "allow", br, "domain-coordinator", False, B("gh pr checkout merge")),
        ("corpus-role: -c у скрипта, а не у python — можно", "allow", br, "domain-coordinator", False,
         B("python3 tools/report.py -c ydapi")),
        ("corpus-role: pytest -c по тестам Krisp — можно", "allow", br, "dev-sonnet", True,
         B("python3 -m pytest -c pytest.ini tests/test_krisp_trash.py")),
        ("corpus-role: python -c с runpy скрипта Krisp — отказ", "deny", br, "dev-sonnet", True,
         B("python3 -c 'import runpy; runpy.run_path(\"tools/krisp_trash.py\")'")),
        # --- merge -R из [merge_repos]: Фемида в law-feed сливает PR lecture-notes (themis-0015) ---
        ("merge -R: Фемида из law-feed в lecture-notes — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes --merge")),
        ("merge -R: --repo= и регистр — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 --repo=Latark/Lecture-Notes --squash")),
        ("merge -R: github.com/owner/repo — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 --repo github.com/latark/lecture-notes")),
        ("merge -R: -Rowner/repo слитно — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 -Rlatark/lecture-notes")),
        ("merge -R: gh pr -R … merge — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr -R latark/lecture-notes merge 2")),
        ("merge -R: другой репозиторий — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/sitebuilder")),
        ("merge -R: похожее имя — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes-fork")),
        ("merge -R: чужой хост — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R evil.example/latark/lecture-notes")),
        ("merge -R: два -R, второй чужой — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes -R latark/sitebuilder")),
        ("merge -R: без номера — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge -R latark/lecture-notes --merge")),
        ("merge -R: -R без значения — отказ", "deny", lw, "domain-coordinator", False, B("gh pr merge 2 -R")),
        ("merge -R: с --admin — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes --admin")),
        ("merge -R: $REPO вместо имени — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R $REPO")),
        ("merge -R: лид Фемиды из [merge_repos] — можно", MERGE_OK, lw, "hephaestus-library", True,
         B("gh pr merge 2 -R latark/lecture-notes")),
        ("merge -R: лид Фемиды вне [merge_repos] — отказ", "deny", lw, "hephaestus-library", True,
         B("gh pr merge 2 -R latark/sitebuilder")),
        ("merge -R: dev-sonnet Фемиды — отказ", "deny", lw, "dev-sonnet", True,
         B("gh pr merge 2 -R latark/lecture-notes")),
        ("merge -R: Афина с репо Фемиды — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes")),
        ("merge -R: склеенные -dR<чужой> — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -dRlatark/sitebuilder")),
        ("merge -R: склеенные -dR<чужой> из папки репозитория — отказ", "deny", ec, "domain-coordinator", False,
         B("gh pr merge 2 -dRlatark/sitebuilder")),
        ("merge -R: gh pr -sR<чужой> merge — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr -sRlatark/sitebuilder merge 2")),
        ("merge -R: -dR <чужой> через пробел — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -dR latark/sitebuilder")),
        ("merge -R: склеенные -dR<свой> — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 -dRlatark/lecture-notes")),
        ("merge -R: -R=<свой> — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 -R=latark/lecture-notes")),
        ("merge: -tR… — R в заголовке, а не -R — можно", MERGE_OK, ec, "domain-coordinator", False,
         B("gh pr merge 2 -tRelease")),
        ("merge -R: Фемида с GH_REPO — по-прежнему отказ", "deny", lw, "domain-coordinator", False,
         B("GH_REPO=latark/lecture-notes gh pr merge 2")),
        ("merge: Афина без [merge] — можно: папки из domains.json (0.5.0)", MERGE_OK, br, "domain-coordinator", False,
         B("gh pr merge 1")),
        ("merge: Фемида git push в main — по-прежнему отказ", "deny", ec, "domain-coordinator", False,
         B("git push origin main")),
        # --- guard 0.5.0 (metis-0038): слияние по схеме владельца ---
        # внутреннее: своё направление по domains.json
        ("merge 0.5: Гермес в своей папке — можно", MERGE_OK, alex, "domain-coordinator", False, B("gh pr merge 4 --squash")),
        ("merge 0.5: Гермес в чужой папке (cwd без cd) — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 4"), br),
        ("merge 0.5: Гермес из своей папки с cd в чужую — отказ", "deny", alex, "domain-coordinator", False,
         B(f"cd {home}/{br} && gh pr merge 4")),
        ("merge 0.5: лид Гермеса hephaestus-site — можно", MERGE_OK, alex, "hephaestus-site", True, B("gh pr merge 4")),
        ("merge 0.5: лид дизайна Гермеса apollo-site — можно", MERGE_OK, alex, "apollo-site", True, B("gh pr merge 4")),
        ("merge 0.5: лид Гермеса в чужой папке (cwd без cd) — отказ", "deny", alex, "hephaestus-site", True,
         B("gh pr merge 4"), br),
        ("merge 0.5: лид Гермеса в сессии Афины — отказ", "deny", br, "hephaestus-site", True, B("gh pr merge 4")),
        ("merge 0.5: лид Афины в сессии Гермеса — отказ", "deny", alex, "hephaestus-shop", True, B("gh pr merge 4")),
        ("merge 0.5: dev-sonnet Гермеса — отказ", "deny", alex, "dev-sonnet", True, B("gh pr merge 4")),
        # продукт: [merge_client] — пропуск так же, папка из [merge_client] вне domains.json — тоже
        ("merge 0.5: Афина в shopKeeperApp — можно", MERGE_OK, br, "domain-coordinator", False,
         B("gh pr merge 7 --squash --delete-branch")),
        ("merge 0.5: Афина в папке [merge_client] вне domains.json — можно", MERGE_OK, br, "domain-coordinator", False,
         B("gh pr merge 7"), "projects/broker-landing"),
        ("merge 0.5: лид Афины в продукте — можно", MERGE_OK, br, "hephaestus-shop", True, B("gh pr merge 7")),
        ("merge 0.5: apollo-shop в [merge_client] вне domains.json — можно", MERGE_OK, br, "apollo-shop", True,
         B("gh pr merge 7"), "projects/broker-landing"),
        ("merge 0.5: лид Гермеса в [merge_client] Афины — отказ", "deny", alex, "hephaestus-site", True,
         B("gh pr merge 7"), "projects/broker-landing"),
        ("merge 0.5: Гермес в продукте Афины — отказ", "deny", alex, "domain-coordinator", False, B("gh pr merge 7"), br),
        ("merge 0.5: Гермес в [merge_client] Афины — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 7"), "projects/broker-landing"),
        ("merge 0.5: Афина в продукте с --admin — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr merge 7 --admin")),
        ("merge 0.5: Афина в продукте с --auto — отказ (запор, 0.5.4)", "deny", br, "domain-coordinator", False,
         B("gh pr merge 7 --auto --squash")),
        # кому слияние закрыто
        ("merge 0.5: hq — отказ", "deny", ".", "hq", False, B("gh pr merge 1"), ak),
        ("merge 0.5: мастерская — отказ", "deny", ws, "workshop", False, B("gh pr merge 1")),
        ("merge 0.5: лид главной сессией — отказ", "deny", br, "hephaestus-shop", False, B("gh pr merge 1")),
        ("merge 0.5: dev-opus — отказ", "deny", br, "dev-opus", True, B("gh pr merge 1")),
        ("merge 0.5: argus — отказ", "deny", br, "argus", True, B("gh pr merge 1")),
        ("merge 0.5: talos — отказ", "deny", br, "talos", True, B("gh pr merge 1")),
        ("merge 0.5: prometheus — отказ", "deny", br, "prometheus", True, B("gh pr merge 1")),
        ("merge 0.5: лид без agent_type-префикса (general-purpose) — отказ", "deny", br, "general-purpose", True,
         B("gh pr merge 1")),
        ("merge 0.5: лид в сессии штаба (~/ai/pantheon) — отказ", "deny", "ai/pantheon", "hephaestus-pantheon", True,
         B("gh pr merge 1"), ak),
        ("merge 0.5: лид в мастерской — отказ", "deny", ws, "hephaestus-workshop", True, B("gh pr merge 1")),
        ("merge 0.5: mnemo-brain в ~/ai/knowledge — отказ", "deny", "ai/knowledge", "domain-coordinator", False,
         B("gh pr merge 1")),
        # защиты: только Метида и её лид, через запор (guard 0.5.4): поштучного «да» владельца больше нет, ядро защит
        # (Д3) — PR ждёт слияния владельцем. Сам запор — test_merge_gate.py; здесь — кто, где и в каком репозитории
        ("защиты: Метида по записям запора — можно", MERGE_OK, ak, "domain-coordinator", False, B("gh pr merge 5 --squash")),
        ("защиты: Метида с --subject — можно (заголовок больше не нужен и не мешает)", MERGE_OK, ak, "domain-coordinator",
         False, B('gh pr merge 5 --squash --subject "guard 0.5.4"')),
        ("защиты: Метида со склеенным -st — можно", MERGE_OK, ak, "domain-coordinator", False,
         B('gh pr merge 5 "-stguard 0.5.4"')),
        ("защиты: Метида без номера (текущая ветка) — отказ", "deny", ak, "domain-coordinator", False,
         B("gh pr merge --squash")),
        ("защиты: Метида на непроверенном коммите — отказ", "deny", ak, "domain-coordinator", False,
         B("gh pr merge 5 --match-head-commit " + "c" * 40)),
        ("защиты: PR без записей запора — отказ", "deny", ak, "domain-coordinator", False, B("gh pr merge 13")),
        ("защиты: --auto — отказ", "deny", ak, "domain-coordinator", False, B("gh pr merge 5 --auto")),
        ("защиты: --admin — отказ", "deny", ak, "domain-coordinator", False, B("gh pr merge 5 --admin")),
        ("защиты: субагент dev-opus Метиды — отказ", "deny", ak, "dev-opus", True, B("gh pr merge 5")),
        ("защиты: лид Метиды — можно (metis-0054)", MERGE_OK, ak, "hephaestus-pantheon", True, B("gh pr merge 5")),
        ("защиты: лид Метиды с --auto — отказ", "deny", ak, "hephaestus-pantheon", True, B("gh pr merge 5 --auto")),
        ("защиты: лид Метиды с двумя номерами — отказ", "deny", ak, "hephaestus-pantheon", True, B("gh pr merge 5 6")),
        ("защиты: apollo-pantheon — можно", MERGE_OK, ak, "apollo-pantheon", True, B("gh pr merge 5")),
        ("защиты: лид Афины в agent-kit — отказ", "deny", br, "hephaestus-shop", True, B("gh pr merge 5"), ak),
        ("Метида внутреннее: лид без -R — можно", MERGE_OK, ak, "hephaestus-pantheon", True,
         B("gh pr merge 3 --squash"), "projects/other/tg-read-dev"),
        ("Метида внутреннее: лид с -R из [merge_repos] — можно", MERGE_OK, ak, "hephaestus-pantheon", True,
         B("gh pr merge 3 -R latark/tg-read"), "projects/other/tg-read-dev"),
        ("защиты: другой координатор в agent-kit — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr merge 5"), ak),
        ("защиты: реестр отдал agent-kit/sub Афине — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr merge 5"), ak + "/sub"),
        ("защиты: Метида с cd в agent-kit — отказ", "deny", ak, "domain-coordinator", False,
         B(f"cd {home}/{ak} && gh pr merge 5"), "projects/other/tg-read-dev"),
        ("Метида внутреннее: без -R — можно", MERGE_OK, ak, "domain-coordinator", False,
         B("gh pr merge 3 --squash"), "projects/other/tg-read-dev"),
        ("Метида внутреннее: -R из [merge_repos] — можно", MERGE_OK, ak, "domain-coordinator", False,
         B("gh pr merge 3 -R latark/tg-read"), "projects/other/tg-read-dev"),
        ("Метида внутреннее: -R вне [merge_repos] — отказ", "deny", ak, "domain-coordinator", False,
         B("gh pr merge 3 -R latark/claude-config"), "projects/other/tg-read-dev"),
        ("Метида внутреннее: -R и --auto — отказ", "deny", ak, "domain-coordinator", False,
         B("gh pr merge 3 -R latark/tg-read --auto"), "projects/other/tg-read-dev"),
        ("Метида из tg-read-dev как папки запуска: -R — можно", MERGE_OK, "projects/other/tg-read-dev",
         "domain-coordinator", False, B("gh pr merge 3 -R latark/tg-read")),
        ("Фемида -R из [merge_repos] — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/lecture-notes")),
        # --- находка проверки безопасности 2eda45f: защиты по репозиторию (remote), сбой — отказ ---
        ("защиты по remote: клон agent-kit в tg-read-dev — Метида по запору — можно", MERGE_OK, ak,
         "domain-coordinator", False, B("gh pr merge 5"), "projects/other/tg-read-dev/x"),
        ("защиты по remote: клон agent-kit (другой регистр, git@) у Фемиды — отказ", "deny", lw, "domain-coordinator",
         False, B("gh pr merge 5"), lw + "/akclone"),
        ("защиты по remote: клон через псевдоним ssh у Гермеса — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 5"), alex + "/alias-clone"),
        ("защиты: симлинк на agent-kit в папке Гермеса — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 5"), alex + "/ak-link"),
        ("защиты: путь в другом регистре — Гермес — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 5"), "projects/AGENT-KIT"),
        ("защиты: путь в другом регистре — Метида по запору — можно", MERGE_OK, ak, "domain-coordinator", False,
         B("gh pr merge 5"), "projects/Agent-Kit"),
        ("защиты: worktree agent-kit во внутренней папке Метиды — по запору можно", MERGE_OK, ak, "domain-coordinator",
         False, B("gh pr merge 5"), "projects/other/tg-read-dev/wt"),
        ("защиты: worktree agent-kit вне направлений (как /tmp) — Гермес — отказ", "deny", alex, "domain-coordinator",
         False, B("gh pr merge 5"), "wt-ak"),
        ("защиты: worktree agent-kit вне направлений — Метида по запору — можно", MERGE_OK, ak, "domain-coordinator",
         False, B("gh pr merge 5"), "wt-ak"),
        ("защиты: Метида -R latark/agent-kit из agent-kit — можно (есть в [merge_repos])", MERGE_OK, ak,
         "domain-coordinator", False, B("gh pr merge 5 -R latark/agent-kit")),
        ("репозиторий: репозиторий без remote — отказ", "deny", alex, "domain-coordinator", False,
         B("gh pr merge 5"), alex + "/no-remote"),
        ("запор: два номера PR в команде — отказ", "deny", ak, "domain-coordinator", False, B("gh pr merge 5 6")),
        ("ssh-псевдоним: клон agent-kit через gh-alt — Метида по запору — можно", MERGE_OK, ak,
         "domain-coordinator", False, B("gh pr merge 5"), "projects/other/tg-read-dev/alias"),
        ("gh-resolved: клон форка у Гермеса, set-default = latark/agent-kit — отказ", "deny", alex, "domain-coordinator",
         False, B("gh pr merge 5"), alex + "/fork"),
        ("gh-resolved: «base» — сам remote, своё слияние — можно", MERGE_OK, alex, "domain-coordinator", False,
         B("gh pr merge 5"), alex + "/base-clone"),
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
        # --- dev-server: исключение для разработчика и talos в worktree (ROLE-23) ---
        ("dev-server: dev-sonnet в worktree — можно", "allow", br, "dev-sonnet", True, B("PORT=4123 pnpm dev"),
         br + "/.claude/worktrees/agent-1"),
        ("dev-server: dev-sonnet вне worktree — отказ", "deny", br, "dev-sonnet", True, B("pnpm dev")),
        ("dev-server: координатор в worktree — отказ", "deny", br, "domain-coordinator", False, B("pnpm dev"),
         br + "/.claude/worktrees/agent-1"),
    ]
    failed = 0
    for case in cases:
        name, want, pdir, role, sub, (tool, ti) = case[:6]
        if want == "allow" and name in NEEDS_POLICY and not HAS_TOMLLIB:
            want = "deny"  # без tomllib привилегий нет (см. NEEDS_POLICY)
        cwd = case[6] if len(case) > 6 else None
        penv = case[7] if len(case) > 7 else None  # env окна: PANTHEON_ROLE (guard 0.5.5)
        got = run(home, os.path.normpath(pdir), role, tool, ti, sub, cwd, penv=penv)
        mark = "ok  " if got == want else "FAIL"
        failed += got != want
        print(f"{mark} {name}: {got}")
    # tg-role (metis-0267): отказ называет путь — заявку pantheon read
    out = run(home, lw, "domain-coordinator", "Bash", {"command": "~/projects/other/tg-read/" + TGR + " history 1"},
              raw=True, penv=TL)
    ok = '"deny"' in out and "tg-role" in out and "выгрузка личного чата — через pantheon read request" in out
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} tg-role: текст отказа — через pantheon read request")
    # неразобранная команда со скриптом — отказ именно tg-role, а не только domain (ревью argus PR #61)
    out = run(home, lw, "domain-coordinator", "Bash",
              {"command": "~/projects/other/tg-read/" + TGR + " history *(e:true:)"}, raw=True, penv=TL)
    ok = '"deny"' in out and "Правило tg-role" in out
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} tg-role: команду не разобрать, а в ней скрипт — отказ правилом tg-role")
    # [merge] со строкой вместо списка не открывает слияние всем (ревью argus 15.10)
    home2 = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home2)
    pol = os.path.join(home2, ".claude", "pantheon", "policy.toml")
    text = _read(pol).replace(
        'themis-library = ["~/projects/lecture-notes", "~/projects/law-feed"]',
        'themis-library = "~/projects/lecture-notes"')
    open(pol, "w").write(text)
    # 0.5.0: свои папки — из domains.json, поэтому проверка — на чужой папке: строка по буквам дала бы корень «/»
    got = run(home2, ec, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, cwd=alex)
    ok = got == "deny"
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge: строка вместо списка в [merge] — чужая папка не открывается: {got}")
    # [merge_client] строкой — то же
    text = _read(pol) + '\n[merge_client]\nhermes-site = "~/projects/sitebuilder"\n'
    text = text.replace('[merge_client]\nathena-shop = ["~/projects/shopKeeperApp", "~/projects/broker-landing"]\n', "")
    open(pol, "w").write(text)
    got = run(home2, alex, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, cwd=br)
    ok = got == "deny"
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge: строка вместо списка в [merge_client] — чужая папка не открывается: {got}")
    # 0.5.0: тексты отказов — по режиму, с тем, что делать вместо
    texts = {
        "закрыто": run(home, br, "dev-opus", "Bash", {"command": "gh pr merge 1"}, sub=True, raw=True),
        "внутреннее": run(home, alex, "domain-coordinator", "Bash", {"command": "gh pr merge 1 --admin"}, raw=True),
        "продукт": run(home, br, "domain-coordinator", "Bash", {"command": "gh pr merge 1 --admin"}, raw=True),
        "защиты": run(home, ak, "domain-coordinator", "Bash", {"command": "gh pr merge 1 --auto"}, raw=True),
        "личное": run(home, "ai/knowledge", "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, raw=True),
    }
    if MERGE_OK == "allow":
        want = {"закрыто": ("gh pr create", "отчёте лиду"), "внутреннее": ("argus", "--admin"),
                "продукт": ("talos", "откат", "--match-head-commit"), "защиты": ("шлюз слияния", "argus", "(Д3)"),
                "личное": ("личному",)}
        ok = all('"deny"' in texts[k] and all(w in texts[k] for w in ws) for k, ws in want.items()) \
            and "talos" not in texts["внутреннее"]
    else:  # без tomllib политика пуста: всем, кроме ролей, которым слияние закрыто, — отказ «политика не прочиталась»
        ok = "gh pr create" in texts["закрыто"] and all("политика" in texts[k] for k in texts if k != "закрыто")
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge 0.5: тексты отказов по режиму (закрыто, внутреннее, продукт, защиты, личное)")
    # нет policy.toml — отказ всем, даже Фемиде
    home4 = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home4)
    os.remove(os.path.join(home4, ".claude/pantheon/policy.toml"))
    got = (run(home4, ec, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, raw=True),
           run(home4, br, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, raw=True))
    ok = all('"deny"' in x and "политика" in x for x in got)  # отказ по правилу, а не сбой скрипта
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge 0.5: нет policy.toml — отказ всем, текст про политику")
    # координатор из [private].coordinators, в чьей папке нет личного из [private].paths, — тоже не сливает
    home5 = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home5)
    pol = os.path.join(home5, ".claude", "pantheon", "policy.toml")
    text = _read(pol) + '\n[private]\ncoordinators = ["mnemo-brain"]\npaths = ["~/ai/pantheon/.git/git-crypt"]\n'
    open(pol, "w").write(text)
    out = run(home5, "ai/knowledge", "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, raw=True)
    ok = '"deny"' in out and ("личному" in out or MERGE_OK == "deny")
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge 0.5: координатор из [private].coordinators — отказ про личное")
    # [merge_repos] строкой — -R закрыт (подстрока «latark/lecture-notes» не должна совпасть по буквам)
    home3 = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home3)
    pol = os.path.join(home3, ".claude", "pantheon", "policy.toml")
    text = _read(pol).replace('themis-library = ["latark/lecture-notes", "latark/law-feed"]',
                              'themis-library = "latark/lecture-notes"')
    open(pol, "w").write(text)
    got = run(home3, lw, "domain-coordinator", "Bash", {"command": "gh pr merge 2 -R latark/lecture-notes"})
    ok = got == "deny"
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge -R: строка вместо списка в [merge_repos] — отказ: {got}")
    # [merge_repos] списком на верхнем уровне — -R закрыт, обычное слияние без -R работает (ревью argus 15.10)
    text = _read(pol)
    text = text[:text.index("[merge_repos]\n")] + text[text.index("[merge_client]\n"):]
    open(pol, "w").write('merge_repos = ["latark/lecture-notes"]\n' + text)  # ключ верхнего уровня — до таблиц
    got = (run(home3, lw, "domain-coordinator", "Bash", {"command": "gh pr merge 2 -R latark/lecture-notes"}),
           run(home3, ec, "domain-coordinator", "Bash", {"command": "gh pr merge 2"}))
    ok = got == ("deny", "deny")
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge -R: merge_repos не таблицей — закрыто и -R, и без -R (запор, 0.5.4): {got}")
    failed += corpus_policy_checks(br, cases)
    failed += merge_security_checks(home, MERGE_OK, cases)
    # № 1: на системном Python 3.9 (без tomllib) guard не падает и прежние правила работают
    if os.path.exists("/usr/bin/python3"):
        got = run(home, br, "", "Bash", {"command": "pnpm run dev"}, python="/usr/bin/python3")
        ok = got == "deny"
        failed += not ok
        cases.append(None)
        print(f"{'ok  ' if ok else 'FAIL'} системный Python 3.9: dev-server запрещён: {got}")
    # metis-0079: Stop без транскрипта (файла нет / по пути папка) — без сбоя в журнале и без блокировки
    stop_home = tempfile.mkdtemp(prefix="guard-stop-")
    stop_log = os.path.join(stop_home, ".local/state/pantheon/logs/guard-failures.log")
    stop_env = {"HOME": stop_home, "PATH": os.environ["PATH"], "TMPDIR": "/nonexistent-tmp"}
    good = os.path.join(stop_home, "good.jsonl")
    with open(good, "w") as fh:
        fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "привет"}}) + "\n")
    os.makedirs(os.path.join(stop_home, "dir.jsonl"))
    for label, tp in (("файла нет", os.path.join(stop_home, "gone.jsonl")),
                      ("по пути папка", os.path.join(stop_home, "dir.jsonl")),
                      ("обычный транскрипт", good)):
        if os.path.exists(stop_log):  # свой журнал на каждый случай: FAIL достаётся тому, кто его вызвал
            os.remove(stop_log)
        ev ={"hook_event_name": "Stop", "transcript_path": tp, "session_id": "s-test", "cwd": stop_home}
        r = subprocess.run([sys.executable, "-I", SHIM, GUARD], input=json.dumps(ev), capture_output=True, text=True,
                           env=stop_env, timeout=10)
        ok = r.returncode == 0 and '"block"' not in r.stdout and '"deny"' not in r.stdout \
            and not os.path.exists(stop_log)
        failed += not ok
        cases.append(None)
        print(f"{'ok  ' if ok else 'FAIL'} Stop, {label}: код {r.returncode}, без блокировки и без записи в журнал сбоев")
    shutil.rmtree(stop_home, ignore_errors=True)
    # metis-0094: любой сбой — код 2 и причина в stderr во всех режимах (плагин, --managed, --strict), в вашей сессии
    # тоже; ни выхода 0 (пропуск), ни трассировки с кодом 1. Исключение — Stop (код 2 не дал бы закончить ход)
    env = {"HOME": home, "PATH": os.environ["PATH"], "TMPDIR": "/nonexistent-tmp"}
    failed += failure_checks(home, env, cases)
    log = os.path.join(home, ".local/state/pantheon/logs/guard-failures.log")
    lines = open(log).read().splitlines() if os.path.exists(log) else []
    ok = any("\tstrict\tmain\tJSONDecodeError" in x for x in lines) and any("\tplugin\tmain\t" in x for x in lines) \
        and any("\tmanaged\tmain\t" in x for x in lines) and not any("не json" in x for x in lines)
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} журнал сбоев: {len(lines)} строк, без текста ввода")
    # управляемые настройки вызывают guard (--managed) — хук плагина молчит; без них — работает
    probe = os.path.join(home, "managed-probe.py")
    with open(probe, "w") as fh:
        fh.write("import sys, json, importlib.util\n"
                 "spec = importlib.util.spec_from_file_location('g', sys.argv[1]); g = importlib.util.module_from_spec(spec)\n"
                 "spec.loader.exec_module(g)\n"
                 "g.MANAGED_FILE, g.MARKET_GUARD = sys.argv[2], sys.argv[1]\n"
                 "print(g.managed_guard_active())\n")
    mf = os.path.join(home, "managed.json")
    results = []
    for content in ('{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 guard.py --managed"}]}]}}',
                    '{"permissions": {"deny": ["Bash(x)"]}}', "битый json"):
        open(mf, "w").write(content)
        results.append(subprocess.run([sys.executable, "-I", probe, GUARD, mf], capture_output=True, text=True,
                                      env=env, timeout=10).stdout.strip())
    ok = results == ["True", "False", "False"]
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} управляемые настройки: хук плагина молчит только при guard --managed: {results}")
    # metis-0084: hq grep -r по ~/ai/pantheon проходит; явный путь в ключ — отказ с текстом про ключ, а не «только hq…»
    out = run(home, "ai/pantheon", "hq", "Bash", {"command": "grep -rln слово ."}, raw=True)
    key = run(home, "ai/pantheon", "hq", "Bash", {"command": "cat .git/git-crypt/keys/default"}, raw=True)
    ok = '"deny"' not in out and '"deny"' in key and "ключ git-crypt" in key and "только hq" not in key
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} private: hq grep -r по ~/ai/pantheon можно, ключ — отказ с понятным текстом")
    # P0-1: при управляемых настройках с guard --managed хук плагина Agent, Task и Skill всё равно проверяет
    # (управляемые настройки их guard не передают), а Bash — пропускает (его проверяет хук --managed)
    probe2 = os.path.join(home, "managed-main.py")
    with open(probe2, "w") as fh:
        fh.write("import sys, io, importlib.util\n"
                 "spec = importlib.util.spec_from_file_location('g', sys.argv[1]); g = importlib.util.module_from_spec(spec)\n"
                 "spec.loader.exec_module(g)\n"
                 "g.MANAGED_FILE, g.MARKET_GUARD, g.MODE = sys.argv[2], sys.argv[1], 'plugin'\n"
                 "sys.stdin = io.StringIO(sys.argv[3])\n"
                 "g.main()\n")
    open(mf, "w").write('{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 guard.py --managed"}]}]}}')
    menv = dict(env, PANTHEON_ROLE="hq")
    outs = {}
    for label, tool, ti in (("Agent", "Agent", {"subagent_type": "tg-reader", "prompt": "x"}),
                            ("Skill", "Skill", {"skill": "telegram-read"}),
                            ("Bash", "Bash", {"command": "pnpm dev"})):
        ev = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti, "session_id": "s-test",
              "cwd": os.path.join(home, "ai/pantheon"), "agent_type": "hq"}
        outs[label] = subprocess.run([sys.executable, "-I", probe2, GUARD, mf, json.dumps(ev)], capture_output=True,
                                     text=True, env=menv, timeout=10).stdout
    ok = '"deny"' in outs["Agent"] and "hq-telegram" in outs["Agent"] and '"deny"' in outs["Skill"] \
        and outs["Bash"].strip() == ""
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} управляемые настройки: хук плагина проверяет Agent и Skill (hq-telegram), Bash — нет")
    # сбой проверки окна — отказ и в главной сессии окна роли без agent_type (strict_window)
    probe3 = os.path.join(home, "window-fail.py")
    with open(probe3, "w") as fh:
        fh.write("import sys, io, importlib.util\n"
                 "spec = importlib.util.spec_from_file_location('g', sys.argv[1]); g = importlib.util.module_from_spec(spec)\n"
                 "spec.loader.exec_module(g)\n"
                 "def boom(*a):\n    raise RuntimeError('x')\n"
                 "g.check_hq_telegram = boom\n"
                 "g.MANAGED_FILE = sys.argv[2]\n"
                 "sys.stdin = io.StringIO(sys.argv[3])\n"
                 "g.run_hook()\n")
    ev = {"hook_event_name": "PreToolUse", "tool_name": "Agent", "tool_input": {"subagent_type": "x", "prompt": "x"},
          "session_id": "s-test", "cwd": os.path.join(home, "ai/pantheon")}
    got = [subprocess.run([sys.executable, "-I", probe3, GUARD, os.path.join(home, "no-managed.json"), json.dumps(ev)],
                          capture_output=True, text=True, env=e, timeout=10) for e in (menv, env)]
    ok = all(r.returncode == 2 and "сбой проверки окна" in r.stderr for r in got)
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} сбой проверки окна: и в окне роли, и в вашей сессии без роли — код 2 (metis-0094)")
    print(f"\n{len(cases) - failed} из {len(cases)} прошли")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
