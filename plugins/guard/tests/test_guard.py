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


def setup(home):
    for d in ("ai/pantheon/.git", "ai/pantheon/directions/athena-broker", "ai/pantheon/directions/hermes-alex/inbox",
              "ai/pantheon/scout", "ai/pantheon-view", ".local/state/pantheon/owner-log", ".claude/pantheon",
              "projects/brokerAssistantApp/app", "projects/alexbroker", "projects/agent-kit",
              "projects/workshop/visa", "ai/knowledge", ".claude/agents", ".claude/skills/x", ".claude/.git",
              "projects/brokerAssistantApp/.claude"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    os.makedirs(os.path.join(home, "ai/pantheon/directions/metis-pantheon/tasks"), exist_ok=True)
    os.makedirs(os.path.join(home, "ai/pantheon/directions/athena-broker/tasks"), exist_ok=True)
    # metis-0044: входящие владельца и папка доски с карточкой
    os.makedirs(os.path.join(home, "ai/pantheon/inbox/tasks"), exist_ok=True)
    os.makedirs(os.path.join(home, "ai/pantheon-view/Доска"), exist_ok=True)
    for f in ("ai/pantheon/directions/metis-pantheon/tasks/metis-0001.md", "ai/pantheon/directions/athena-broker/tasks/athena-0001.md",
              "ai/pantheon/inbox/tasks/inbox-0001.md", "ai/pantheon-view/Доска/athena-0001 Вопрос.md"):
        open(os.path.join(home, f), "w").close()
    for f in ("ai/pantheon/board.md", "ai/pantheon/alerts.md", "ai/pantheon/decision-map.md",
              "ai/pantheon/directions/hermes-alex/STATUS.md", "ai/pantheon/directions/hermes-alex/inbox/old.md"):
        open(os.path.join(home, f), "w").close()
    json.dump({"domains": {
        "athena-broker": ["~/projects/brokerAssistantApp"],
        "hermes-alex": ["~/projects/alexbroker"],
        "metis-pantheon": ["~/projects/agent-kit", "~/.claude"],
        # реестр «по ошибке» отдаёт athena папку agent-kit — привилегий Метиды это не даёт
        "athena-broker-2": ["~/projects/agent-kit/sub"],
        "themis-sources": ["~/projects/expert-corpus", "~/projects/legal-watch"],
    }}, open(os.path.join(home, ".local/state/pantheon/domains.json"), "w"))
    # guard 0.5.0 (metis-0038): внутренняя папка Метиды вне защит и сайт брокера из [merge_client] вне domains.json
    os.makedirs(os.path.join(home, "projects/other/tg-read-dev"), exist_ok=True)
    os.makedirs(os.path.join(home, "projects/broker-landing"), exist_ok=True)
    domains_file = os.path.join(home, ".local/state/pantheon/domains.json")
    domains = json.loads(_read(domains_file))
    domains["domains"]["metis-pantheon"].append("~/projects/other/tg-read-dev")
    with open(domains_file, "w") as fh:
        json.dump(domains, fh)
    # шаг 1.2: репозиторий брокера на ветке эпика, alexbroker — на main (правило push); личное в ~/ai/knowledge/me
    # 0.5.0: у каждого репозитория — remote: gh сливает в репозиторий из remote, и guard узнаёт защиты по нему
    for repo, branch, url in (("projects/brokerAssistantApp", "epic-tax", "https://github.com/latark/brokerAssistantApp"),
                              ("projects/alexbroker", "main", "git@github.com:latark/alexbroker.git"),
                              ("projects/expert-corpus", "main", "https://github.com/latark/expert-corpus.git"),
                              ("projects/legal-watch", "main", "ssh://git@github.com/latark/legal-watch"),
                              ("projects/agent-kit", "main", "https://github.com/latark/agent-kit"),
                              (".claude", "main", "git@github.com:latark/claude-config.git"),
                              ("projects/other/tg-read-dev", "main", "https://github.com/latark/tg-read"),
                              ("projects/broker-landing", "main", "https://github.com/latark/broker-landing")):
        git_repo(os.path.join(home, repo), branch, url)
    os.makedirs(os.path.join(home, "ai/knowledge/me"), exist_ok=True)
    os.makedirs(os.path.join(home, "ai/knowledge/raw"), exist_ok=True)
    open(os.path.join(home, "ai/knowledge/me/finance.md"), "w").close()
    os.makedirs(os.path.join(home, "projects/brokerAssistantApp/.claude/worktrees/agent-1"), exist_ok=True)
    open(os.path.join(home, ".claude/pantheon/policy.toml"), "w").write(
        'always = ["~/.claude/agent-memory"]\n[coordinators]\nmetis-pantheon = ["~/projects/agent-kit"]\n'
        'mnemo-brain = ["~/ai/knowledge"]\n[agent_extra]\nprometheus = ["~/ai/knowledge"]\n'
        '[merge]\nthemis-sources = ["~/projects/expert-corpus", "~/projects/legal-watch"]\n'
        '[merge_repos]\nthemis-sources = ["latark/expert-corpus", "latark/legal-watch"]\n'
        'metis-pantheon = ["latark/tg-read", "latark/agent-kit"]\nhermes-alex = ["latark/alexbroker"]\n'
        'athena-broker = ["latark/brokerassistantapp", "latark/broker-landing"]\n'
        '[merge_client]\nathena-broker = ["~/projects/brokerAssistantApp", "~/projects/broker-landing"]\n')
    write_zeus(home)
    gate_fixtures(home)


# запор слияния (guard 0.5.4): все PR 1–12 этих репозиториев проверены на SHA_OK — тесты, «принять» отдельного argus,
# talos, строка «что ушло» с откатом; поддельный gh отдаёт PR без файлов ядра. Сам запор — в test_merge_gate.py
SHA_OK = "a" * 40
GATE_REPOS = ("latark/expert-corpus", "latark/legal-watch", "latark/alexbroker", "latark/brokerassistantapp",
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
                    fh.write(json.dumps({"v": 1, "kind": kind, "repo": [repo], "pr": pr, "sha": SHA_OK,
                                         "by": dict(by, agent_type="argus" if kind == "accept" else "talos")}) + "\n")
    with open(os.path.join(home, "ai/pantheon/alerts.md"), "w") as fh:
        for repo in ("latark/brokerAssistantApp", "latark/broker-landing"):
            for pr in range(1, 13):
                fh.write(f"2026-10-15 20:00 · athena-broker · {repo}#{pr} ушло; откат: git revert x\n")
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
    git_repo(j("projects/legal-watch/akclone"), "main", "git@github.com:Latark/Agent-Kit.git")
    git_repo(j("projects/alexbroker/alias-clone"), "main", "git@gh-work:latark/agent-kit.git")
    git_repo(j("projects/alexbroker/no-remote"), "main", None)
    os.makedirs(j("projects/agent-kit/sub"), exist_ok=True)
    git_repo(j("projects/other/tg-read-dev/alias"), "main", "git@gh-work:latark/agent-kit.git")
    git_repo(j("projects/alexbroker/fork"), "main", "git@github.com:someone/agent-kit-fork.git")
    subprocess.run(["git", "-C", j("projects/alexbroker/fork"), "config", "remote.origin.gh-resolved",
                    "latark/agent-kit"], check=True)
    git_repo(j("projects/alexbroker/base-clone"), "main", "git@github.com:latark/alexbroker.git")
    subprocess.run(["git", "-C", j("projects/alexbroker/base-clone"), "config", "remote.origin.gh-resolved", "base"],
                   check=True)
    os.symlink(j("projects/agent-kit"), j("projects/alexbroker/ak-link"))
    git = ["git", "-C", j("projects/agent-kit"), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "init"], check=True)
    for wt, branch in (("projects/other/tg-read-dev/wt", "wt1"), ("wt-ak", "wt2")):
        subprocess.run(git + ["worktree", "add", "-q", "-b", branch, j(wt)], check=True, capture_output=True)


def _read(path):
    """Прочитать файл целиком до того, как его откроют на запись (open(p, "w") обнуляет сразу)."""
    with open(path) as fh:
        return fh.read()


def run(home, pdir, role, tool, tool_input, sub=False, cwd=None, python=None, raw=False, tuid=None):
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": with_head(tool, tool_input),
             "cwd": os.path.join(home, cwd if cwd is not None else pdir), "session_id": "s-test",
             "tool_use_id": tuid or "toolu_" + uuid.uuid4().hex}
    if role:
        event["agent_type"] = role
    if sub:
        event["agent_id"] = "a1"
    env = {"HOME": home, "PATH": os.path.join(home, "fake-bin") + os.pathsep + os.environ["PATH"],
           "CLAUDE_PROJECT_DIR": os.path.join(home, pdir), "TMPDIR": "/nonexistent-tmp"}
    out = subprocess.run([python or sys.executable, "-I", GUARD], input=json.dumps(event), capture_output=True,
                         text=True, env=env, timeout=10).stdout
    if raw:
        return out
    return "deny" if '"deny"' in out else "allow"


def merge_security_checks(home, MERGE_OK, cases):
    """Находка проверки безопасности 2eda45f: защиты по remote, любой сбой — отказ; лиды (metis-0054). С guard 0.5.4
    поштучного «да» владельца нет — его заменил запор (test_merge_gate.py). Возвращает число упавших проверок."""
    failed = 0
    ak, ec = "projects/agent-kit", "projects/expert-corpus"
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
            ("[private].coordinators не из строк", dict(policy_fn=lambda t: t + "\n[private]\ncoordinators = [1]\n")),
            ("[private].paths строкой", dict(policy_fn=lambda t: t + '\n[private]\npaths = "~/ai/knowledge/me"\n')),
            ("domains.json битый", dict(domains_fn=lambda t: "{не json")),
            ("domains.json: папки строкой",
             dict(domains_fn=lambda t: json.dumps({"domains": {"themis-sources": "~/projects/expert-corpus"}}))),
            ("domains.json без направлений", dict(domains_fn=lambda t: '{"domains": {}}')),
            ("два направления с одним корнем",
             dict(domains_fn=lambda t: json.dumps(dict(json.loads(t), domains=dict(
                 json.loads(t)["domains"], **{"themis-twin": ["~/projects/expert-corpus"]}))))),
    ):
        out = run(variant(**kw), ec, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, raw=True)
        check(f"сбой — отказ: {name}", deny(out) and "сбой проверки" not in out)
    # -R latark/agent-kit в чужом [merge_repos] — это защиты, а не внутреннее
    h = variant(policy_fn=lambda t: t.replace('themis-sources = ["latark/expert-corpus", "latark/legal-watch"]',
                                              'themis-sources = ["latark/expert-corpus", "latark/agent-kit"]'))
    got = (M(h, "gh pr merge 5 -R latark/agent-kit", pdir=ec), M(h, "gh pr merge 2 -R latark/expert-corpus", pdir=ec))
    check(f"защиты по -R: latark/agent-kit в [merge_repos] Фемиды — отказ, свой -R — как было: {got}",
          got == ("deny", MERGE_OK))
    # корень направления-родитель («~/projects») не открывает папку другого направления внутри
    # широкий корень — первым в реестре: проверка «по первому совпадению» отдала бы ему alexbroker
    h = variant(domains_fn=lambda t: json.dumps({"domains": dict({"zeta-wide": ["~/projects"]},
                                                                 **json.loads(t)["domains"])}),
                policy_fn=lambda t: t.replace("[merge_repos]\n", '[merge_repos]\nzeta-wide = ["latark/zz-own"]\n'))
    git_repo(os.path.join(h, "projects/zz-own"), "main", "https://github.com/latark/zz-own")
    os.makedirs(os.path.join(h, "projects/zz-plain"), exist_ok=True)
    got = (M(h, "gh pr merge 1", pdir="projects", cwd="projects/alexbroker"),
           M(h, "gh pr merge 1", pdir="projects", cwd="projects/zz-own"),
           M(h, "gh pr merge 1", pdir="projects", cwd="projects/zz-plain"))
    check(f"чужая папка: корень «~/projects» над alexbroker — отказ, своя папка — можно, не репозиторий git — отказ: {got}",
          got == ("deny", MERGE_OK, "deny"))
    # битая запись одного направления не выпадает молча: иначе его папку «унаследовал» бы широкий корень
    h = variant(domains_fn=lambda t: json.dumps({"domains": dict(json.loads(t)["domains"], **{
        "zeta-wide": ["~/projects"], "hermes-alex": "~/projects/alexbroker"})}))
    out = M(h, "gh pr merge 1", pdir="projects", cwd="projects/alexbroker", raw=True)
    check("сбой — отказ: папки одного направления строкой — широкий корень не получает его папку",
          deny(out) and ("domains.json" in out or not allow_ok))
    # ревью argus 210766a: domains.json битый или удалён — без отката на старый ~/.claude/hooks/domains.json, где
    # направление шире (broker = brokerAssistantApp + alexbroker + legal-watch): Гермес слил бы в legal-watch
    legacy = {"domains": {"broker": ["~/projects/brokerAssistantApp", "~/projects/alexbroker", "~/projects/legal-watch"]}}
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
        out = M(h, "gh pr merge 2", pdir="projects/alexbroker", cwd="projects/legal-watch", raw=True)
        check(f"старый реестр: domains.json {label}, ~/.claude/hooks/domains.json есть — Гермес в legal-watch — отказ",
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
    no_client = lambda t: t.replace('[merge_client]\nathena-broker = ["~/projects/brokerAssistantApp", '
                                    '"~/projects/broker-landing"]\n', "")
    h = variant(policy_fn=no_client)
    alex, br, lw = "projects/alexbroker", "projects/brokerAssistantApp", "projects/legal-watch"
    got = (M(h, "gh pr merge 1", pdir=ec), M(h, "gh pr merge 2 -R latark/expert-corpus", pdir=lw),
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
    tg, br, alex = "projects/other/tg-read-dev", "projects/brokerAssistantApp", "projects/alexbroker"
    os.makedirs(os.path.join(home, ak, "sub"), exist_ok=True)
    got = (M(home, "gh pr merge 5 --squash", pdir=br, cwd=ak), M(home, "gh pr merge 5", pdir=br, cwd=ak + "/sub"),
           run(home, ak, "domain-coordinator", "Bash", {"command": "gh pr merge 5"}, sub=True),
           run(home, ak, "dev-sonnet", "Bash", {"command": "gh pr merge 5"}, sub=True),
           M(home, "gh pr merge 5 --auto"), M(home, "gh pr merge 5 6"),
           M(home, "gh pr merge 3 -R latark/tg-read --auto", cwd=tg), M(home, "gh pr merge 3 -R latark/alexbroker", cwd=tg),
           M(home, f"cd {home}/{ak} && gh pr merge 5", cwd=tg), M(home, "GH_REPO=latark/agent-kit gh pr merge 5"))
    check(f"защиты: другой координатор в agent-kit, субагенты Метиды, --auto, два номера, -R вне [merge_repos], cd и "
          f"GH_REPO — отказ: {got}", got == ("deny",) * 10)
    out = M(home, "gh pr merge 5 --auto", raw=True)
    check("защиты: отказ не просит «да» владельца, а называет запор и Д3",
          deny(out) and (("запор" in out and "(Д3)" in out and "окн" not in out and "--subject" not in out)
                         or not allow_ok))

    # metis-0054: лид Метиды (hephaestus-pantheon субагентом) — по тем же правилам, что Метида
    def L(h, cmd, role="hephaestus-pantheon", pdir=ak, cwd=None, raw=False):
        return run(h, pdir, role, "Bash", {"command": cmd}, sub=True, cwd=cwd, raw=raw)
    got = (L(home, "gh pr merge 5 --squash"), L(home, "gh pr merge 3 -R latark/tg-read", cwd=tg))
    check(f"защиты: лид Метиды сливает защиты и -R из [merge_repos] по запору — можно: {got}",
          got == (MERGE_OK, MERGE_OK))
    got = (L(home, "gh pr merge 5 --auto"), L(home, "gh pr merge 5 6"), L(home, "gh pr merge 3 -R latark/alexbroker", cwd=tg),
           L(home, "gh pr merge 3 -R latark/tg-read -R latark/agent-kit", cwd=tg),
           L(home, "gh pr merge 5", pdir=br, cwd=ak), L(home, "gh pr merge 5", role="hephaestus-broker"),
           L(home, "gh pr merge 5", role="apollo-pantheon", pdir="ai/pantheon", cwd=ak))
    check(f"защиты: лид Метиды с --auto, двумя номерами, -R вне [merge_repos], двумя -R; лид Афины в "
          f"agent-kit и из своей сессии; лид в сессии штаба — отказ: {got}", got == ("deny",) * 7)
    # metis-0054: кто не лид — отказ с текстом «сливает лид или координатор, остальные — PR и отчёт лиду»
    for r in ("dev-sonnet", "argus", "talos", "prometheus", "hephaestus", "hephaestus-"):
        out = L(home, "gh pr merge 1", role=r, pdir=br, raw=True)
        check(f"merge: {r} субагентом — отказ, текст про лида и отчёт лиду",
              deny(out) and (("лид направления" in out and "отчёте лиду" in out) or not allow_ok))
    out = L(home, "gh pr merge 4", role="hephaestus-broker", pdir=alex, raw=True)
    check("merge: лид чужого направления (hephaestus-broker в сессии hermes-alex) — отказ, текст про своё направление",
          deny(out) and ("не лид направления этой сессии (hermes-alex)" in out or not allow_ok))
    out = L(home, "gh pr merge 1", role="hephaestus-broker", pdir=br, raw=True)
    check("merge: лид своего направления — можно (текст отказа не про лида)",
          (allow_ok and not deny(out)) or (not allow_ok and "не лид" not in out))
    # реестр «по ошибке» отдал agent-kit/sub Афине (athena-broker-2): его лид — hephaestus-broker-2, защиты ему закрыты
    got = (L(home, "gh pr merge 5", role="hephaestus-broker-2", pdir=ak + "/sub"),
           L(home, "gh pr merge 5 -R latark/agent-kit", role="hephaestus-broker-2", pdir=ak + "/sub"))
    check(f"merge: лид athena-broker-2 в agent-kit/sub (защиты) — отказ и с -R: {got}", got == ("deny", "deny"))
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
    br, ak, alex, ws = "projects/brokerAssistantApp", "projects/agent-kit", "projects/alexbroker", "projects/workshop/visa"
    ec, lw = "projects/expert-corpus", "projects/legal-watch"
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
        ("координатор пишет свой STATUS.md", "allow", br, "domain-coordinator", False, W(P("directions/athena-broker/STATUS.md"))),
        ("координатор не правит чужой STATUS.md", "deny", br, "domain-coordinator", False, E(P("directions/hermes-alex/STATUS.md"))),
        ("лид создаёт новый файл в чужом inbox/", "allow", br, "hephaestus-broker", True, W(P("directions/hermes-alex/inbox/new.md"))),
        ("лид не переписывает чужой файл в inbox/", "deny", br, "hephaestus-broker", True, W(P("directions/hermes-alex/inbox/old.md"))),
        ("iris не переписывает alerts.md", "deny", ".", "iris", False, W(P("alerts.md"))),
        ("iris дописывает через pantheon alert", "allow", ".", "iris", False, B('pantheon alert "новая версия Claude Code"')),
        ("iris пишет в scout/", "allow", ".", "iris", False, W(P("scout/2026-10-14.md"))),
        ("clio не пишет в scout/", "deny", ".", "clio", False, W(P("scout/x.md"))),
        ("правка в копии — отказ", "deny", br, "domain-coordinator", False, W(os.path.join(home, "ai/pantheon-view/board.md"))),
        ("запись модели в owner-log — отказ", "deny", br, "domain-coordinator", False,
         B(f"echo да >> {home}/.local/state/pantheon/owner-log/athena-broker.md")),
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
            ("файл задачи", E(P("directions/athena-broker/tasks/athena-0001.md"))),
            ("свой проект", W(os.path.join(home, br, "app/x.ts"))),
        )],
        # metis-0044, п. 2: файлы задач — только `pantheon task`, ролям и субагентам, штабу тоже
        *[(f"0044 {r}{' (субагент)' if s else ''}: {n} — отказ", "deny", d, r, s, x, *cwd) for r, s, d, n, x, *cwd in (
            ("hq", False, ".", "Edit answer в чужой задаче", E(P("directions/athena-broker/tasks/athena-0001.md"))),
            ("hq", False, ".", "Write новой задачи", W(P("directions/athena-broker/tasks/athena-0002.md"))),
            ("hq", False, ".", "Write во входящие владельца", W(P("inbox/tasks/inbox-0001.md"))),
            ("hq", False, ".", "Bash >> answer", B(f"echo 'answer: Да' >> {home}/ai/pantheon/directions/athena-broker/tasks/athena-0001.md")),
            ("hq", False, ".", "cp в папку задач", B(f"cp /tmp/t.md {home}/ai/pantheon/directions/athena-broker/tasks/")),
            ("hq", False, ".", "mv задачи", B(f"mv {home}/ai/pantheon/directions/athena-broker/tasks/athena-0001.md /tmp/")),
            ("hq", False, ".", "rm -rf папки задач", B(f"rm -rf {home}/ai/pantheon/directions/athena-broker/tasks")),
            ("hq", False, ".", "регистр TASKS", E(P("directions/athena-broker/TASKS/athena-0001.md"))),
            ("hq", False, ".", "служебный .lock", B(f"touch {home}/ai/pantheon/directions/athena-broker/tasks/.lock")),
            ("domain-coordinator", False, br, "Edit своей задачи", E(P("directions/athena-broker/tasks/athena-0001.md"))),
            ("domain-coordinator", False, br, "sed -i своей задачи",
             B("sed -i '' 's/^status: .*/status: done/' ~/ai/pantheon/directions/athena-broker/tasks/athena-0001.md")),
            ("domain-coordinator", False, br, "из cwd tasks/", B("echo 'answer: Да' >> athena-0001.md"),
             "ai/pantheon/directions/athena-broker/tasks"),
            ("hephaestus-broker", True, br, "Write своей задачи", W(P("directions/athena-broker/tasks/athena-0001.md"))),
            ("general-purpose", True, br, "Edit своей задачи", E(P("directions/athena-broker/tasks/athena-0001.md"))),
            # ревью argus f437a81: запись в папку над tasks/ целиком
            ("hq", False, ".", "cp -R в directions/", B(f"cp -R /tmp/forge/tasks {home}/ai/pantheon/directions/")),
            ("hq", False, ".", "rsync в папку направления", B(f"rsync -a /tmp/forge/ {home}/ai/pantheon/directions/athena-broker/")),
            ("hq", False, ".", "cp во входящие владельца целиком", B(f"cp -R /tmp/forge/tasks {home}/ai/pantheon/inbox/")),
            ("hq", False, ".", "tar -C в directions", B(f"tar -xf /tmp/x.tar -C {home}/ai/pantheon/directions")),
            ("domain-coordinator", False, br, "tar -C в своё направление",
             B("tar -xf /tmp/x.tar -C ~/ai/pantheon/directions/athena-broker")),
            ("domain-coordinator", False, br, "unzip -d в своё направление",
             B("unzip -o /tmp/x.zip -d ~/ai/pantheon/directions/athena-broker")),
            ("domain-coordinator", False, br, "cp в папку своего направления", B("cp /tmp/a.md ~/ai/pantheon/directions/athena-broker/")),
            ("hq", False, ".", "заглушка с другим именем", B(f"touch {home}/ai/pantheon/directions/athena-broker/tasks/.keep.md")),
        )],
        *[(f"0044 {r}: {n} — можно", "allow", d, r, False, x) for r, d, n, x in (
            ("hq", ".", "pantheon task set", B("pantheon task set athena-0001 status=todo next=x --note y")),
            ("hq", ".", "pantheon task new", B("pantheon task new --direction athena-broker --title x")),
            ("domain-coordinator", br, "pantheon task set своей", B("pantheon task set athena-0001 status=doing --note y")),
            ("domain-coordinator", br, "pantheon task claim своей", B("pantheon task claim athena-0001 --by hephaestus")),
            ("hq", ".", "mkdir tasks/ нового направления", B(f"mkdir -p {home}/ai/pantheon/directions/hermes-alex/tasks")),
            ("hq", ".", "файл tasks.md рядом с папкой", W(P("directions/athena-broker/tasks.md"))),
            ("domain-coordinator", br, "план эпика", W(P("directions/athena-broker/epic-x.md"))),
            ("hq", ".", "чтение задачи", B(f"cat {home}/ai/pantheon/directions/athena-broker/tasks/athena-0001.md")),
            # ревью argus f437a81: заглушка в tasks/ нового направления (пустую папку тик в git не положит)
            ("hq", ".", "mkdir tasks/ и .gitkeep нового направления",
             B(f"mkdir -p {home}/ai/pantheon/directions/janus-x/tasks && touch {home}/ai/pantheon/directions/janus-x/tasks/.gitkeep")),
            ("hq", ".", "Write .keep в tasks/", W(P("directions/hermes-alex/tasks/.keep"))),
            ("hq", ".", "mkdir нового направления", B(f"mkdir -p {home}/ai/pantheon/directions/janus-x")),
            ("domain-coordinator", br, "cp с именем файла в своё направление",
             B("cp /tmp/a.md ~/ai/pantheon/directions/athena-broker/a.md")),
            ("domain-coordinator", br, "mv заявки в inbox/done/", B("mv ~/ai/pantheon/directions/athena-broker/inbox/x.md "
                                                                  "~/ai/pantheon/directions/athena-broker/inbox/done/")),
        )],
        ("роль не коммитит ~/ai/pantheon", "deny", ".", "hq", False, B(f"git -C {home}/ai/pantheon commit -am x")),
        ("ваша сессия коммитит ~/ai/pantheon", "allow", ".", "", False, B(f"git -C {home}/ai/pantheon commit -am x")),
        ("Метида правит карту решений", "allow", ak, "domain-coordinator", False, E(P("decision-map.md"))),
        ("athena не правит карту решений", "deny", br, "domain-coordinator", False, E(P("decision-map.md"))),
        ("реестр не выдаёт прав Метиды", "deny", ak + "/../brokerAssistantApp", "domain-coordinator", False, E(P("decision-map.md"))),
        ("athena пишет в свой репозиторий", "allow", br, "domain-coordinator", False, W(os.path.join(home, br, "app/x.ts"))),
        ("athena — отказ на запись в alexbroker (SEC-12)", "deny", br, "domain-coordinator", False, W(os.path.join(home, alex, "x.md"))),
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
         B("pantheon task new --direction athena-broker --title x")),
        ("координатор: чужая задача — отказ", "deny", br, "domain-coordinator", False, B("pantheon task set metis-0001 status=done")),
        ("координатор: новая задача чужому направлению — отказ", "deny", br, "domain-coordinator", False,
         B("pantheon task new --direction metis-pantheon --title x")),
        ("координатор: задача, которой нет, — отказ", "deny", br, "domain-coordinator", False, B("pantheon task claim zz-0001 --by a")),
        ("субагент координатора: чужая задача — отказ", "deny", br, "hephaestus-broker", True, B("pantheon task set metis-0001 next=x")),
        ("координатор: task ready и show — можно", "allow", br, "domain-coordinator", False, B("pantheon task ready; pantheon task show metis-0001")),
        ("hq: любая задача — можно", "allow", ".", "hq", False, B("pantheon task set athena-0001 status=todo")),
        ("координатор: terminal-notifier — отказ", "deny", br, "domain-coordinator", False,
         B('terminal-notifier -title "Пантеон" -message "x"')),
        ("субагент: terminal-notifier по пути — отказ", "deny", br, "argus", True, B("/opt/homebrew/bin/terminal-notifier -message x")),
        ("ваша сессия: pantheon uninstall можно", "allow", ".", "", False, B("pantheon uninstall")),
        # роли отдельной сессией (№ 7)
        ("clio сессией: запись в alexbroker — отказ", "deny", ".", "clio", False, W(os.path.join(home, alex, "x.md"))),
        ("clio сессией: запись в ~/ai/knowledge (agent_extra нет в тестовой политике) — отказ", "deny", ".", "clio", False, W(os.path.join(home, "ai/knowledge/wiki/x.md"))),
        ("prometheus сессией: ~/ai/knowledge по agent_extra", "allow", ".", "prometheus", False, W(os.path.join(home, "ai/knowledge/raw/x.md"))),
        ("iris сессией: policy.toml — отказ", "deny", ".", "iris", False, W(os.path.join(home, ".claude/pantheon/policy.toml"))),
        ("hq пишет в alexbroker (штаб не ограничен domain)", "allow", ".", "hq", False, W(os.path.join(home, alex, "x.md"))),
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
            "RM ~/ai/PANTHEON/ALERTS.MD", "cd ~/ai/pantheon/directions/athena-broker && git commit -am x",
            "git --git-dir=$HOME/ai/pantheon/.git commit -m x", "git -c alias.x='!rm ~/ai/pantheon/alerts.md' x",
            "hash -p /bin/rm myrm; myrm ~/ai/pantheon/alerts.md", "IFS=:; X=a:$HOME/ai/pantheon/alerts.md; rm $X")],
        *[(f"обычная команда: {c!r}", "allow", br, "domain-coordinator", False, B(c)) for c in (
            "pnpm test", "cd app && pnpm lint", "mkdir -p src/{a,b}/c", "rm -rf node_modules dist",
            "sed -i '' 's/a/b/' src/a.ts", "find . -name '*.log' -delete",
            "git commit -m \"$(cat <<'EOF'\nfeat: x\n\nтело (со скобками) и 'кавычками'\nEOF\n)\"",
            "for f in src/*.ts; do sed -i '' 's/a/b/' \"$f\"; done", "echo hi # комментарий с апострофом don't",
            "set -euo pipefail; pnpm build", "OUT=/tmp/res.txt; pnpm test > \"$OUT\" 2>&1",
            "tmp=$(mktemp -d); cp src/a.ts \"$tmp\"/", "git add -A && git commit -m 'x' && git push",
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
            "cp -R ~/ai/pantheon/directions/athena-broker /tmp/backup", "ls ~/ai/pantheon")],
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
        ("protect-config: координатор коммитит в своём репозитории", "allow", br, "domain-coordinator", False, B("git commit -am x")),
        # прежние правила (№ 28)
        ("attribution: пометка Claude в коммите — отказ", "deny", br, "", False,
         B('git commit -m "x\n\nCo-' + 'Authored-By: Claude <noreply@' + 'anthropic.com>"')),
        ("cdp: свой скрипт подключения — отказ", "deny", br, "", False,
         ("Write", {"file_path": os.path.join(home, br, "c.mjs"), "content": "read DevTools" + "ActivePort"})),
        ("tg-secret: чтение ключа tg-read — отказ", "deny", br, "", False,
         B("security find-generic-" + "password -s tg-" + "read -w")),
        # --- шаг 1.2: команды пульта start/wake/roles — штаб и вы; approve — только вы ---
        ("hq: pantheon start athena-broker", "allow", "ai/pantheon", "hq", False, B("pantheon start athena-broker --from zeus")),
        ("координатор: pantheon start — отказ", "deny", br, "domain-coordinator", False, B("pantheon start hermes-alex")),
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
        ("private: chiron (субагент Зевса) читает me/", "allow", ".", "chiron", True, R(K("me/finance.md"))),
        ("private: mnemo-brain пишет в me/", "allow", "ai/knowledge", "domain-coordinator", False, W(K("me/x.md"))),
        ("push: mnemo-brain не отправляет сам (SEC-13)", "deny", "ai/knowledge", "domain-coordinator", False,
         B("git push origin wiki-sync")),
        ("push: mnemo-brain коммитит", "allow", "ai/knowledge", "domain-coordinator", False, B("git commit -qm wiki")),
        # проверка безопасности 15.10: обходы правил ролей
        ("push: + в refspec — принудительная, отказ", "deny", br, "hephaestus-broker", True, B("git push origin +epic-tax")),
        ("push: gh api PUT …/merge — отказ", "deny", br, "hephaestus-broker", True,
         B("gh api -X PUT repos/o/r/pulls/1/merge")),
        ("push: gh api -f (POST) — отказ", "deny", br, "domain-coordinator", False,
         B("gh api repos/o/r/git/refs -f ref=refs/heads/main -f sha=1")),
        ("push: gh api чтение — можно", "allow", br, "hephaestus-broker", True, B("gh api repos/o/r/pulls/1")),
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
        ("push: лид отправляет чужой репозиторий (git -C) — отказ", "deny", br, "hephaestus-broker", True,
         B("git -C ~/projects/alexbroker push origin feat")),
        ("push: координатор cd в чужой репозиторий — отказ", "deny", br, "domain-coordinator", False,
         B("cd ~/projects/alexbroker && git push origin feat")),
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
        ("cdp: hq запускает демон — отказ", "deny", ".", "hq", False, B("node ~/.claude/tools/cdp-daemon.mjs comet")),
        ("cdp: ваша сессия без роли — можно", "allow", ".", "", False, B("curl -s 127.0.0.1:9333/health")),
        ("cdp: мастерская мимо демона на 9222 — отказ", "deny", ws, "workshop", False, B("curl -s 127.0.0.1:9222/json/version")),
        ("cdp: prometheus читает DevToolsActivePort — отказ", "deny", br, "prometheus", True,
         B("cat ~/Library/Application\\ Support/Comet/DevToolsActivePort")),
        ("cdp: ws devtools/browser — отказ", "deny", br, "dev-sonnet", True,
         B("node -e \"new WebSocket('ws://127.0.0.1:9222/devtools/browser/x')\"")),
        ("cdp: ваша сессия на 9222 — можно", "allow", ".", "", False, B("curl -s 127.0.0.1:9222/json/version")),
        # --- push (DONE-07, SEC-13) ---
        ("push: координатор отправляет ветку эпика", "allow", br, "domain-coordinator", False, B("git push")),
        ("push: лид — в develop", "allow", br, "hephaestus-broker", True, B("git push origin epic-tax:develop")),
        ("push: лид — в main — отказ", "deny", br, "hephaestus-broker", True, B("git push origin develop:main")),
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
        # brokerAssistantApp — её продукт ([merge_client]): слияние открыто, talos и откат — обязанность роли
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
         B(".venv/bin/corpus channel t.me/x --author kuklin --videos")),
        ("corpus-role: python -m expert_corpus add — отказ", "deny", br, "domain-coordinator", False,
         B("python3 -m expert_corpus add https://rutube.ru/x")),
        ("corpus-role: bash -c corpus add — отказ", "deny", br, "domain-coordinator", False, B("bash -c 'corpus add u'")),
        ("corpus-role: скрипт удаления Krisp — отказ", "deny", br, "dev-sonnet", True,
         B("uv run python tools/krisp_trash.py --id 1")),
        ("corpus-role: ключ Диска из Связки — отказ", "deny", br, "domain-coordinator", False,
         B("security find-generic-password -s expert-corpus-yadisk -a token -w")),
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
        ("corpus-role: corpus channel без --videos — можно", "allow", br, "domain-coordinator", False,
         B("corpus channel t.me/x --author kuklin")),
        ("corpus-role: чтение скрипта — можно", "allow", br, "dev-sonnet", True, B("cat tools/krisp_trash.py")),
        ("corpus-role: штаб ищет в корпусе — отказ", "deny", ".", "hq", False, B("corpus search задаток")),
        ("corpus-role: ваша сессия без роли — можно", "allow", ".", "", False, B("corpus add https://youtu.be/x")),
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
         B("gh pr merge 1 -R latark/alexbroker")),
        ("merge: Фемида по ссылке — отказ", "deny", ec, "domain-coordinator", False,
         B("gh pr merge https://github.com/latark/alexbroker/pull/1")),
        ("merge: Фемида через cd в чужую папку — отказ", "deny", ec, "domain-coordinator", False,
         B(f"cd {home}/{alex} && gh pr merge 1")),
        ("merge: лид Фемиды (hephaestus-sources) — можно (metis-0054)", MERGE_OK, ec, "hephaestus-sources", True,
         B("gh pr merge 1")),
        ("merge: лид Фемиды с --admin — отказ", "deny", ec, "hephaestus-sources", True, B("gh pr merge 1 --admin")),
        ("merge: dev-sonnet Фемиды — отказ", "deny", ec, "dev-sonnet", True, B("gh pr merge 1")),
        ("merge: Фемида с GH_REPO — отказ", "deny", ec, "domain-coordinator", False,
         B("GH_REPO=latark/alexbroker gh pr merge 1")),
        ("merge: Фемида gh pr -R … merge — отказ", "deny", ec, "domain-coordinator", False,
         B("gh pr -R latark/alexbroker merge 1")),
        ("merge: Афина gh pr -R … merge — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr -R latark/alexbroker merge 1")),
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
        # --- merge -R из [merge_repos]: Фемида в legal-watch сливает PR expert-corpus (themis-0015) ---
        ("merge -R: Фемида из legal-watch в expert-corpus — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/expert-corpus --merge")),
        ("merge -R: --repo= и регистр — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 --repo=Latark/Expert-Corpus --squash")),
        ("merge -R: github.com/owner/repo — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 --repo github.com/latark/expert-corpus")),
        ("merge -R: -Rowner/repo слитно — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 -Rlatark/expert-corpus")),
        ("merge -R: gh pr -R … merge — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr -R latark/expert-corpus merge 2")),
        ("merge -R: другой репозиторий — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/alexbroker")),
        ("merge -R: похожее имя — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/expert-corpus-fork")),
        ("merge -R: чужой хост — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R evil.example/latark/expert-corpus")),
        ("merge -R: два -R, второй чужой — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/expert-corpus -R latark/alexbroker")),
        ("merge -R: без номера — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge -R latark/expert-corpus --merge")),
        ("merge -R: -R без значения — отказ", "deny", lw, "domain-coordinator", False, B("gh pr merge 2 -R")),
        ("merge -R: с --admin — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/expert-corpus --admin")),
        ("merge -R: $REPO вместо имени — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -R $REPO")),
        ("merge -R: лид Фемиды из [merge_repos] — можно", MERGE_OK, lw, "hephaestus-sources", True,
         B("gh pr merge 2 -R latark/expert-corpus")),
        ("merge -R: лид Фемиды вне [merge_repos] — отказ", "deny", lw, "hephaestus-sources", True,
         B("gh pr merge 2 -R latark/alexbroker")),
        ("merge -R: dev-sonnet Фемиды — отказ", "deny", lw, "dev-sonnet", True,
         B("gh pr merge 2 -R latark/expert-corpus")),
        ("merge -R: Афина с репо Фемиды — отказ", "deny", br, "domain-coordinator", False,
         B("gh pr merge 2 -R latark/expert-corpus")),
        ("merge -R: склеенные -dR<чужой> — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -dRlatark/alexbroker")),
        ("merge -R: склеенные -dR<чужой> из папки репозитория — отказ", "deny", ec, "domain-coordinator", False,
         B("gh pr merge 2 -dRlatark/alexbroker")),
        ("merge -R: gh pr -sR<чужой> merge — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr -sRlatark/alexbroker merge 2")),
        ("merge -R: -dR <чужой> через пробел — отказ", "deny", lw, "domain-coordinator", False,
         B("gh pr merge 2 -dR latark/alexbroker")),
        ("merge -R: склеенные -dR<свой> — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 -dRlatark/expert-corpus")),
        ("merge -R: -R=<свой> — можно", MERGE_OK, lw, "domain-coordinator", False,
         B("gh pr merge 2 -R=latark/expert-corpus")),
        ("merge: -tR… — R в заголовке, а не -R — можно", MERGE_OK, ec, "domain-coordinator", False,
         B("gh pr merge 2 -tRelease")),
        ("merge -R: Фемида с GH_REPO — по-прежнему отказ", "deny", lw, "domain-coordinator", False,
         B("GH_REPO=latark/expert-corpus gh pr merge 2")),
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
        ("merge 0.5: лид Гермеса hephaestus-alex — можно", MERGE_OK, alex, "hephaestus-alex", True, B("gh pr merge 4")),
        ("merge 0.5: лид дизайна Гермеса apollo-alex — можно", MERGE_OK, alex, "apollo-alex", True, B("gh pr merge 4")),
        ("merge 0.5: лид Гермеса в чужой папке (cwd без cd) — отказ", "deny", alex, "hephaestus-alex", True,
         B("gh pr merge 4"), br),
        ("merge 0.5: лид Гермеса в сессии Афины — отказ", "deny", br, "hephaestus-alex", True, B("gh pr merge 4")),
        ("merge 0.5: лид Афины в сессии Гермеса — отказ", "deny", alex, "hephaestus-broker", True, B("gh pr merge 4")),
        ("merge 0.5: dev-sonnet Гермеса — отказ", "deny", alex, "dev-sonnet", True, B("gh pr merge 4")),
        # продукт: [merge_client] — пропуск так же, папка из [merge_client] вне domains.json — тоже
        ("merge 0.5: Афина в brokerAssistantApp — можно", MERGE_OK, br, "domain-coordinator", False,
         B("gh pr merge 7 --squash --delete-branch")),
        ("merge 0.5: Афина в папке [merge_client] вне domains.json — можно", MERGE_OK, br, "domain-coordinator", False,
         B("gh pr merge 7"), "projects/broker-landing"),
        ("merge 0.5: лид Афины в продукте — можно", MERGE_OK, br, "hephaestus-broker", True, B("gh pr merge 7")),
        ("merge 0.5: apollo-broker в [merge_client] вне domains.json — можно", MERGE_OK, br, "apollo-broker", True,
         B("gh pr merge 7"), "projects/broker-landing"),
        ("merge 0.5: лид Гермеса в [merge_client] Афины — отказ", "deny", alex, "hephaestus-alex", True,
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
        ("merge 0.5: лид главной сессией — отказ", "deny", br, "hephaestus-broker", False, B("gh pr merge 1")),
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
        # (Д3) — только кнопкой владельца. Сам запор — test_merge_gate.py; здесь — кто, где и в каком репозитории
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
        ("защиты: лид Афины в agent-kit — отказ", "deny", br, "hephaestus-broker", True, B("gh pr merge 5"), ak),
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
         B("gh pr merge 2 -R latark/expert-corpus")),
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
        ("ssh-псевдоним: клон agent-kit через gh-work — Метида по запору — можно", MERGE_OK, ak,
         "domain-coordinator", False, B("gh pr merge 5"), "projects/other/tg-read-dev/alias"),
        ("gh-resolved: клон форка у Гермеса, set-default = latark/agent-kit — отказ", "deny", alex, "domain-coordinator",
         False, B("gh pr merge 5"), alex + "/fork"),
        ("gh-resolved: «base» — сам remote, своё слияние — можно", MERGE_OK, alex, "domain-coordinator", False,
         B("gh pr merge 5"), alex + "/base-clone"),
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
        cwd = case[6] if len(case) > 6 else None
        got = run(home, os.path.normpath(pdir), role, tool, ti, sub, cwd)
        mark = "ok  " if got == want else "FAIL"
        failed += got != want
        print(f"{mark} {name}: {got}")
    # [merge] со строкой вместо списка не открывает слияние всем (ревью argus 15.10)
    home2 = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home2)
    pol = os.path.join(home2, ".claude", "pantheon", "policy.toml")
    text = _read(pol).replace(
        'themis-sources = ["~/projects/expert-corpus", "~/projects/legal-watch"]',
        'themis-sources = "~/projects/expert-corpus"')
    open(pol, "w").write(text)
    # 0.5.0: свои папки — из domains.json, поэтому проверка — на чужой папке: строка по буквам дала бы корень «/»
    got = run(home2, ec, "domain-coordinator", "Bash", {"command": "gh pr merge 1"}, cwd=alex)
    ok = got == "deny"
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge: строка вместо списка в [merge] — чужая папка не открывается: {got}")
    # [merge_client] строкой — то же
    text = _read(pol) + '\n[merge_client]\nhermes-alex = "~/projects/alexbroker"\n'
    text = text.replace('[merge_client]\nathena-broker = ["~/projects/brokerAssistantApp", "~/projects/broker-landing"]\n', "")
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
                "продукт": ("talos", "откат", "--match-head-commit"), "защиты": ("запор", "argus", "(Д3)"),
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
    # [merge_repos] строкой — -R закрыт (подстрока «latark/expert-corpus» не должна совпасть по буквам)
    home3 = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
    setup(home3)
    pol = os.path.join(home3, ".claude", "pantheon", "policy.toml")
    text = _read(pol).replace('themis-sources = ["latark/expert-corpus", "latark/legal-watch"]',
                              'themis-sources = "latark/expert-corpus"')
    open(pol, "w").write(text)
    got = run(home3, lw, "domain-coordinator", "Bash", {"command": "gh pr merge 2 -R latark/expert-corpus"})
    ok = got == "deny"
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge -R: строка вместо списка в [merge_repos] — отказ: {got}")
    # [merge_repos] списком на верхнем уровне — -R закрыт, обычное слияние без -R работает (ревью argus 15.10)
    text = _read(pol)
    text = text[:text.index("[merge_repos]\n")] + text[text.index("[merge_client]\n"):]
    open(pol, "w").write('merge_repos = ["latark/expert-corpus"]\n' + text)  # ключ верхнего уровня — до таблиц
    got = (run(home3, lw, "domain-coordinator", "Bash", {"command": "gh pr merge 2 -R latark/expert-corpus"}),
           run(home3, ec, "domain-coordinator", "Bash", {"command": "gh pr merge 2"}))
    ok = got == ("deny", "deny")
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} merge -R: merge_repos не таблицей — закрыто и -R, и без -R (запор, 0.5.4): {got}")
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
        r = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps(ev), capture_output=True, text=True,
                           env=stop_env, timeout=10)
        ok = r.returncode == 0 and '"block"' not in r.stdout and '"deny"' not in r.stdout \
            and not os.path.exists(stop_log)
        failed += not ok
        cases.append(None)
        print(f"{'ok  ' if ok else 'FAIL'} Stop, {label}: код {r.returncode}, без блокировки и без записи в журнал сбоев")
    shutil.rmtree(stop_home, ignore_errors=True)
    # SEC-29/SEC-10: сбой всего скрипта — в окне роли (--strict) выход 2, в плагине выход 0; оба — в журнал
    env = {"HOME": home, "PATH": os.environ["PATH"], "TMPDIR": "/nonexistent-tmp"}
    for mode, want_code in (("--strict", 2), (None, 0)):
        argv = [sys.executable, "-I", GUARD] + ([mode] if mode else [])
        r = subprocess.run(argv, input="не json", capture_output=True, text=True, env=env, timeout=10)
        ok = r.returncode == want_code
        failed += not ok
        cases.append(None)
        print(f"{'ok  ' if ok else 'FAIL'} сбой скрипта, режим {mode or 'плагин'}: код {r.returncode}, ждали {want_code}")
    log = os.path.join(home, ".local/state/pantheon/logs/guard-failures.log")
    lines = open(log).read().splitlines() if os.path.exists(log) else []
    ok = any("\tstrict\tmain\tJSONDecodeError" in x for x in lines) and any("\tplugin\tmain\t" in x for x in lines) \
        and not any("не json" in x for x in lines)
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
    # hq задевает только ключ git-crypt (grep -r по ~/ai/pantheon): текст про ключ, а не «личное только hq…»
    out = run(home, "ai/pantheon", "hq", "Bash", {"command": "grep -rln слово ."}, raw=True)
    ok = '"deny"' in out and "ключ git-crypt" in out and "--exclude-dir=.git" in out and "только hq" not in out
    failed += not ok
    cases.append(None)
    print(f"{'ok  ' if ok else 'FAIL'} private: отказ hq по ключу git-crypt — понятный текст")
    print(f"\n{len(cases) - failed} из {len(cases)} прошли")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
