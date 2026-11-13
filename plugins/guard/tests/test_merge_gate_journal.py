#!/usr/bin/env python3
"""Запор слияния guard, часть «journal»: журнал проверок и записи хука: тесты и «принять» на SHA, автор, ядро, роли вердикта, формат pantheon review, фоновые команды, перечень Б6 и критерии.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py; разрез metis-1119.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_journal.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403


# --- случаи ------------------------------------------------------------------------------------------------------

def t_pass_internal(h):
    """Записи через хук (PostToolUse): тесты в чистом дереве и «принять» от argus — слияние проходит."""
    sha = h.sha["tg-read"]
    h.post("pantheon review test -- python3 -I tests/run.py", "dev-opus")
    h.post(f"pantheon review accept latark/tg-read 3 {sha}{CL}", "argus", agent_id="argus1")
    recs = h.read()
    check("PostToolUse пишет tests и accept", [r["kind"] for r in recs] == ["tests", "accept"]
          and recs[0]["sha"] == sha and recs[0]["repo"] == ["latark/tg-read"] and recs[0]["pr"] is None
          and recs[1]["by"] == {"agent_type": "argus", "agent_id": "argus1", "session_id": "s-coord"}, recs)
    d = os.path.dirname(h.records)
    check("журнал: папка 0700, файл 0600", stat.S_IMODE(os.stat(d).st_mode) == 0o700
          and stat.S_IMODE(os.stat(h.records).st_mode) == 0o600)
    merge_case("accept и tests на текущий SHA — проходит", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), True)
    merge_case("--match-head-commit=SHA — тоже проходит", h.pre(f"gh pr merge 3 --match-head-commit={sha}"), True)
    # metis-0965: base PR — в записи вердикта, у gh с -R; gh не ответил — поля нет, «принять» не в счёт
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("0965: accept — поле base из gh pr view -R … --json baseRefName", recs[1].get("base") == "main"
          and "pr view 3 -R latark/tg-read --json baseRefName" in log, (recs[1], log))
    open(h.j("gh.fail"), "w").close()
    h.post(f"pantheon review reject latark/tg-read 3 {sha}{CL}", "argus", agent_id="argus2")
    os.remove(h.j("gh.fail"))
    got = h.read()[-1]
    check("0965: gh не ответил — запись есть, поля base нет", got["kind"] == "reject" and "base" not in got, got)
    with open(h.records) as fh:
        lines = fh.readlines()
    with open(h.records, "w") as fh:
        fh.writelines(lines[:-1])
    # долг #388: base нужна только «принять» (base_counts) — у «вернуть» gh pr view за base не зовётся: срок хука
    # уходит на запись, а не на поле, которое никто не читает
    h.reset_log()
    h.post(f"pantheon review reject latark/tg-read 3 {sha}{CL}", "argus", agent_id="argus2")
    got = h.read()[-1]
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("#388: «вернуть» — gh pr view за base не зовётся, поля base нет", got["kind"] == "reject"
          and "base" not in got and "--json baseRefName" not in log, (got, log))
    with open(h.records) as fh:
        lines = fh.readlines()
    with open(h.records, "w") as fh:
        fh.writelines(lines[:-1])
    # base PR сменили (gh pr edit --base): «принять» на main — не в счёт, отказ называет обе base
    h.view["tg-read"]["baseRefName"] = "release"
    h.write_view("tg-read")
    merge_case("0965: base PR сменили — «принять» на старой base не в счёт",
               h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False, "(base main) не в счёт: base PR сейчас release")


def t_returned_empty(h):
    """Д3 argus #382: «принять» с полем «вернули» без пар — повторный круг; «вернуть» другого в силе, отказ называет
    поле без пар и metis-0497."""
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"),
           rec("reject", "latark/tg-read", 3, sha, agent_id="argusr", session="s-r"),
           dict(rec("accept", "latark/tg-read", 3, sha, agent_id="argusa", session="s-a"), returned=[]))
    merge_case("Д3: поле «вернули» без пар — «вернуть» в силе, отказ называет поле",
               h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False, "поле «вернули» без пар agent8/сессия8")


def t_old_sha(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, OLD, who="dev-opus"), rec("tests", "latark/tg-read", None, sha, "dev-opus"),
           rec("accept", "latark/tg-read", 3, OLD))
    merge_case("accept на старый SHA при новом --match-head-commit — отказ",
               h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False, "нет «принять» от argus")


def t_no_tests(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, OLD, "dev-opus"), rec("accept", "latark/tg-read", 3, sha))
    merge_case("нет записи тестов на этот SHA — отказ", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False,
               "нет записи тестов")
    merge_case("отказ про тесты подсказывает не-фон и timeout 600000", h.pre(f"gh pr merge 3 --match-head-commit {sha}"),
               False, "timeout до 600000 мс")
    merge_case("отказ про тесты называет проверку вне окна (metis-0573)", h.pre(f"gh pr merge 3 --match-head-commit {sha}"),
               False, "pantheon outside test --wait 590")


def t_author_is_reviewer(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"), rec("accept", "latark/tg-read", 3, sha, agent_id="L1"))
    merge_case("автор = рецензент — отказ", h.pre(f"gh pr merge 3 --match-head-commit {sha}", role="hephaestus-pantheon",
                                                 agent_id="L1"), False, "рецензент и сливающий")
    merge_case("тот же лид, другой argus — проходит",
               h.pre(f"gh pr merge 3 --match-head-commit {sha}", role="hephaestus-pantheon", agent_id="L2"), True)


def t_argus_commit(h):
    for cmd in ("git commit -m x", "git -C . rebase main", "git cherry-pick abc", "git pull", "git commit-tree x"):
        d, why = h.pre(cmd, role="argus", agent_id="argus1")
        check(f"argus: {cmd} — отказ", d == "deny" and "argus не делает git" in why, why)
    d, why = h.pre("git log --oneline", role="argus", agent_id="argus1")
    check("argus: git log — можно", d == "allow", why)
    d, why = h.pre("git commit -m x", role="dev-opus", agent_id="d1")
    check("dev-opus: git commit — можно", d == "allow", why)


def t_admin_auto(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"), rec("accept", "latark/tg-read", 3, sha))
    merge_case("--admin — отказ", h.pre(f"gh pr merge 3 --admin --match-head-commit {sha}"), False, "без --admin")
    merge_case("--auto — отказ", h.pre(f"gh pr merge 3 --auto --match-head-commit {sha}"), False, "без --auto")
    merge_case("без номера PR — отказ", h.pre(f"gh pr merge --match-head-commit {sha}"), False, "один номер PR")
    merge_case("два номера PR — отказ", h.pre(f"gh pr merge 3 4 --match-head-commit {sha}"), False, "один номер PR")
    # флаги gh до pr (metis-0247 r4, решение Зевса 19.10): шлюз узнаёт форму `gh -R o/r pr merge` и судит её как
    # обычную; мутация «без разбора флагов до подкоманды» убита здесь
    def gate(name, cmd, why):
        d, r = h.pre(cmd)
        check(name, d == "deny" and "Правило push: gh pr merge" in r and why in r, r)
    gate("gh -R o/r pr merge 1 — шлюз: без --match-head-commit — отказ", "gh -R latark/tg-read pr merge 3",
         "нужен ровно один --match-head-commit")
    gate("gh --repo=o/r pr merge 1 --admin — отказ", f"gh --repo=latark/tg-read pr merge 3 --admin --match-head-commit {sha}",
         "без --admin")
    gate("gh -Ro/r pr merge --auto — отказ", f"gh -Rlatark/tg-read pr merge 3 --auto --match-head-commit {sha}",
         "без --auto")
    gate("gh -R o/r --admin pr merge — отказ", f"gh -R latark/tg-read --admin pr merge 3 --match-head-commit {sha}",
         "--admin")
    gate("GH_REPO=o/r gh pr merge 1 — отказ", f"GH_REPO=latark/tg-read gh pr merge 3 --match-head-commit {sha}",
         "GH_REPO")
    gate("GH_CONFIG_DIR=… gh pr merge — отказ", f"GH_CONFIG_DIR=/tmp/x gh pr merge 3 --match-head-commit {sha}",
         "GH_")
    gate("gh --hostname github.com pr merge 1 — отказ", f"gh --hostname github.com pr merge 3 --match-head-commit {sha}",
         "--hostname")
    gate("gh --hostname=github.com pr merge 1 — отказ", f"gh --hostname=github.com pr merge 3 --match-head-commit {sha}",
         "--hostname")
    gate("gh -R o/r pr merge 1 -R чужой — отказ", f"gh -R latark/tg-read pr merge 3 -R latark/other --match-head-commit {sha}",
         "[merge_repos]")
    gate("gh -R чужой pr merge — отказ", f"gh -R latark/other pr merge 3 --match-head-commit {sha}", "[merge_repos]")
    gate("gh --foo x pr merge (флаг съедает слово по cobra) — отказ", f"gh --foo x pr merge 3 --match-head-commit {sha}",
         "--foo")
    d, r = h.pre(f"gh $SUB merge 3 --match-head-commit {sha}")
    check("gh $SUB merge — подкоманду не вычислить — отказ", d == "deny" and "не вычислить" in r, r)
    d, r = h.pre("gh -R latark/tg-read api -X PUT repos/latark/tg-read/pulls/3/merge")
    check("gh -R o/r api -X PUT …/merge — отказ правилом записи gh api", d == "deny" and "gh api с записью" in r, r)
    # флаги записи до api (ревью argus 69r-a): gh применяет их к api, правило записи видит слова и до api
    for pre in ("-X PUT", "-XPUT", "--method PUT", "--method=PUT", "-f merge_method=squash", "-F merge_method=squash",
                "--input /tmp/body.json", "--input=/tmp/body.json", "--field merge_method=squash"):
        d, r = h.pre(f"gh {pre} api repos/latark/tg-read/pulls/3/merge")
        check(f"gh {pre} api …/merge — отказ правилом записи gh api", d == "deny" and "gh api с записью" in r, r)
    d, r = h.pre("gh -f query='mutation{mergePullRequest(input:{pullRequestId:\"x\"}){clientMutationId}}' api graphql")
    check("gh -f query='mutation{mergePullRequest…}' api graphql — отказ правилом записи gh api",
          d == "deny" and "gh api с записью" in r, r)
    for pre in ("-X GET", "--method=GET", "-R latark/tg-read"):
        d, r = h.pre(f"gh {pre} api repos/latark/tg-read/pulls/3")
        check(f"gh {pre} api …/pulls/3 (чтение) — правило записи не задевает", "gh api с записью" not in (r or ""), r)
    merge_case("gh -R o/r pr merge 3 --match-head-commit <SHA> — проходит, как обычная форма",
               h.pre(f"gh -R latark/tg-read pr merge 3 --match-head-commit {sha}"), True)
    merge_case("gh --repo=o/r pr merge 3 --match-head-commit <SHA> — проходит",
               h.pre(f"gh --repo=latark/tg-read pr merge 3 --match-head-commit {sha}"), True)


def t_no_head(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"), rec("accept", "latark/tg-read", 3, sha))
    merge_case("без --match-head-commit — отказ", h.pre("gh pr merge 3"), False, "нужен ровно один --match-head-commit")
    merge_case("два --match-head-commit — отказ",
               h.pre(f"gh pr merge 3 --match-head-commit {sha} --match-head-commit {sha}"), False,
               "нужен ровно один --match-head-commit")
    merge_case("короткий SHA — отказ", h.pre(f"gh pr merge 3 --match-head-commit {sha[:12]}"), False,
               "нужен ровно один --match-head-commit")


def t_not_listed(h):
    sha = h.sha["notlisted"]
    h.seed(rec("tests", "latark/notlisted", None, sha, "dev-opus"), rec("accept", "latark/notlisted", 3, sha))
    merge_case("репозиторий не из merge_repos (внутреннее, без -R) — отказ",
               h.pre(f"gh pr merge 3 --match-head-commit {sha}", pdir="projects/notlisted"), False, "[merge_repos]")
    merge_case("-R не из merge_repos — отказ",
               h.pre(f"gh pr merge 3 -R latark/other --match-head-commit {sha}"), False, "[merge_repos]")


def t_core(h):
    sha = h.sha["agent-kit"]
    h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"), rec("accept", "latark/agent-kit", 7, sha))
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    merge_case("защиты: PR не задевает ядро — проходит", h.pre(cmd, pdir="projects/agent-kit"), True)
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("gh pr view зовётся с -R и номером", "pr view 7 -R latark/agent-kit --json headRefOid,baseRefOid,baseRefName,changedFiles,statusCheckRollup"
          in log and "api repos/latark/agent-kit/pulls/7/files" in log and "--paginate" in log, log)
    check("защиты: один gh pr view на Д3 и проверки GitHub (таймаут хука 10 с)", log.count("pr view") == 1, log)
    h.gh(["README.md", "plugins/guard/hooks/merge_gate.py"])
    merge_case("защиты: PR задевает ядро (merge_gate.py) — отказ", h.pre(cmd, pdir="projects/agent-kit"), False, CORE + ": PR задевает")
    for path in ("plugins/guard/tests/x.py", "plugins/guard/README.md", "PLUGINS/Guard/x.py", "plugins/guard/hooks/guard.py"):
        h.gh(["README.md", path])
        merge_case(f"защиты: весь plugins/guard — {path} — отказ", h.pre(cmd, pdir="projects/agent-kit"), False,
                   CORE + ": PR задевает")
    h.gh([{"filename": "plugins/other/g.py", "status": "renamed", "previous_filename": "plugins/guard/hooks/guard.py"}])
    merge_case("защиты: вынос файла из plugins/guard наружу — отказ", h.pre(cmd, pdir="projects/agent-kit"), False,
               CORE + ": PR задевает plugins/guard/hooks/guard.py")
    h.gh(["plugins/pantheon/lib/tasks.py", "plugins/guardian/x.py", "plugins/pantheon/tests/test_a.py"])
    merge_case("защиты: PR только в plugins/pantheon (и plugins/guardian) — проходит",
               h.pre(cmd, pdir="projects/agent-kit"), True)
    # metis-0182 п. 4 и metis-0174: общие роли и правила autoMode окон — тоже ядро (даже если папки ещё нет на main)
    # metis-0951: пакеты окон направлений — их хуки исполняются вне песочницы
    for path in ("plugins/pantheon/roles/argus.md", "./Plugins/Pantheon/Roles/dev-opus.md", "plugins/pantheon/roles",
                 "plugins/pantheon/lib/window_rules.py", "./plugins/pantheon/lib/Window_Rules.py",
                 "plugins/pantheon/packs/x/hooks.json", "Plugins/Pantheon/Packs/legal/bin/run.sh"):
        h.gh(["README.md", path])
        merge_case(f"защиты: ядро pantheon — {path} — отказ", h.pre(cmd, pdir="projects/agent-kit"), False,
                   CORE + ": PR задевает")
    h.gh(["plugins/pantheon/rolesx/a.md", "plugins/pantheon/lib/window_rules_test.py", "plugins/pantheon/roles.md",
          "plugins/pantheon/packsx/hooks.json", "plugins/pantheon/lib/packs.py"])
    merge_case("защиты: соседи ядра pantheon (rolesx/, window_rules_test.py, roles.md, packsx/, packs.py) — проходит",
               h.pre(cmd, pdir="projects/agent-kit"), True)
    h.gh([{"filename": "plugins/pantheon/agents/argus.md", "status": "renamed",
           "previous_filename": "plugins/pantheon/roles/argus.md"}])
    merge_case("защиты: вынос роли из plugins/pantheon/roles — отказ", h.pre(cmd, pdir="projects/agent-kit"), False,
               CORE + ": PR задевает plugins/pantheon/roles/argus.md")
    h.gh([{"filename": "plugins/guard/hooks/merge_core.py", "status": "renamed",
           "previous_filename": "plugins/guard/hooks/merge_gate.py"}])
    merge_case("защиты: переименование ядра (previous_filename) — отказ", h.pre(cmd, pdir="projects/agent-kit"), False,
               CORE + ": PR задевает plugins/guard/hooks/merge_core.py, plugins/guard/hooks/merge_gate.py")
    h.gh([], raw='[{"filename": "README.md"}]\n[{"filename": "plugins/guard/hooks/protect_config.py"}]\n', count=2)
    merge_case("защиты: страницы --paginate склеены `[..][..]` — ядро видно", h.pre(cmd, pdir="projects/agent-kit"),
               False, CORE + ": PR задевает")
    h.gh([], raw='[{"filename": "README.md"}][{"filename": "a.py"}]', count=2)
    merge_case("защиты: две страницы без ядра — проходит", h.pre(cmd, pdir="projects/agent-kit"), True)
    h.gh([], raw="не json", count=1)
    merge_case("защиты: неразборный ответ gh api — отказ", h.pre(cmd, pdir="projects/agent-kit"), False, "неполон")
    h.gh(["README.md"])
    open(h.j("gh.api.fail"), "w").close()
    merge_case("защиты: gh api упал — отказ", h.pre(cmd, pdir="projects/agent-kit"), False, "неполон")
    os.remove(h.j("gh.api.fail"))
    h.gh(["plugins/guard/managed-settings.json"])
    merge_case("защиты: PR задевает managed-settings.json — отказ", h.pre(cmd, pdir="projects/agent-kit"), False,
               CORE + ": PR задевает")
    h.gh(["README.md"], count=150)
    merge_case("защиты: список файлов неполон — отказ", h.pre(cmd, pdir="projects/agent-kit"), False, "неполон")
    h.gh(["README.md", "a", "b"], count=2)
    merge_case("защиты: файлов больше, чем changedFiles — отказ", h.pre(cmd, pdir="projects/agent-kit"), False,
               "неполон")
    h.gh(["README.md"], head=OLD)
    # отказ даёт сама Д3 (текст ядра), а не только проверки GitHub на том же ответе gh pr view (argus 0297a, круг 2)
    merge_case("защиты: PR на другом коммите — отказ Д3", h.pre(cmd, pdir="projects/agent-kit"), False,
               CORE + ": PR сейчас на другом коммите")
    h.gh(["README.md"])
    open(h.j("gh.fail"), "w").close()
    merge_case("защиты: gh не ответил — отказ", h.pre(cmd, pdir="projects/agent-kit"), False, "не ответил")
    os.remove(h.j("gh.fail"))
    merge_case("защиты: сливает не Метида — отказ", h.pre(cmd, pdir="projects/agent-kit", cwd="projects/agent-kit",
                                                         role="hephaestus-shop", agent_id="L9"), False, "")


def t_verdict_role(h):
    sha = h.sha["tg-read"]
    for role in ("dev-opus", "hephaestus-pantheon", "talos", ""):
        h.post(f"pantheon review accept latark/tg-read 3 {sha}{CL}", role)
    h.post(f"pantheon review talos latark/tg-read 3 {sha}", "argus")
    check("вердикт пишет не argus (и talos не talos) — записи нет", h.read() == [], h.read())
    d, why = h.pre(f"pantheon review accept latark/tg-read 3 {sha}{CL}", role="dev-opus", agent_id="d1")
    check("PreToolUse: accept не от argus — сразу отказ", d == "deny" and "только argus" in why, why)
    d, why = h.pre(f"pantheon review talos latark/tg-read 3 {sha}", role="argus", agent_id="a1")
    check("PreToolUse: talos не от talos — сразу отказ", d == "deny" and "только talos" in why, why)
    d, why = h.pre(f"pantheon review accept latark/tg-read 3 {sha[:20]}", role="argus", agent_id="a1")
    check("PreToolUse: плохой SHA у argus — отказ", d == "deny" and "формате" in why, why)
    d, why = h.pre(f"pantheon review accept latark/tg-read 3 {sha}{CL}", role="argus", agent_id="a1")
    check("PreToolUse: accept от argus — можно", d == "allow", why)
    h.post(f"pantheon review accept latark/tg-read 3 {sha[:39]}", "argus")
    h.post(f"pantheon review accept latark 3 {sha}", "argus")
    check("плохие аргументы accept — записи нет", h.read() == [], h.read())


def t_reject_after_accept(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"), rec("accept", "latark/tg-read", 3, sha),
           rec("reject", "latark/tg-read", 3, sha, agent_id="argus2"))
    merge_case("reject после accept — отказ", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False, "«вернуть» (reject)")
    h.seed(rec("accept", "latark/tg-read", 3, sha, agent_id="argus3"))
    merge_case("accept третьего argus после reject второго — всё равно отказ (metis-0158)",
               h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False, "«вернуть» (reject)")
    h.seed(rec("accept", "latark/tg-read", 3, sha, agent_id="argus2"))
    merge_case("accept того же argus после его reject — проходит", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), True)


def t_product(h):
    sha = h.sha["broker"]
    cmd = f"gh pr merge 5 --match-head-commit {sha}"
    h.seed(rec("tests", "latark/broker", None, sha, "dev-opus"), rec("accept", "latark/broker", 5, sha))
    h.alert("2026-10-15 20:00 · athena-shop · latark/broker#5 ушло: налоги; откат: git revert abc")
    merge_case("продукт без talos — отказ", h.pre(cmd, pdir="projects/broker"), False, "нет проверки talos")
    h.seed(rec("talos", "latark/broker", 5, sha, who="talos", agent_id="t1"))
    open(h.j("ai/pantheon/alerts.md"), "w").close()
    h.alert("2026-10-15 20:00 · athena-shop · latark/broker#5 ушло: налоги")
    h.alert("2026-10-15 20:00 · athena-shop · latark/broker#50 ушло; откат: git revert abc")
    h.alert("latark/broker#5 ушло; откат: без даты")
    merge_case("продукт без строки «откат» в alerts.md — отказ", h.pre(cmd, pdir="projects/broker"), False,
               "нет строки «что ушло»")
    h.alert("2026-10-15 20:01 · athena-shop · latark/broker#5 ушло: налоги; откат: git revert abc")
    merge_case("продукт с talos и строкой alerts — проходит", h.pre(cmd, pdir="projects/broker"), True)


def t_not_simple(h):
    sha = h.sha["tg-read"]
    for cmd in (f"pantheon review accept latark/tg-read 3 {sha} ; true",
                f"pantheon review accept latark/tg-read 3 {sha} && true",
                f"pantheon review accept latark/tg-read 3 {sha} | cat",
                f"pantheon review accept latark/tg-read 3 $(echo {sha})",
                f"pantheon review accept latark/tg-read 3 {sha} > /dev/null",
                f"FOO=1 pantheon review accept latark/tg-read 3 {sha}{CL}",
                f"echo pantheon review accept latark/tg-read 3 {sha}{CL}"):
        h.post(cmd, "argus")
    h.post("pantheon review test -- true; true", "dev-opus")
    check("PostToolUse с непростой командой (… ; true и др.) — записи нет", h.read() == [], h.read())
    h.post(f"/usr/local/bin/pantheon review accept latark/tg-read 3 {sha}{CL}", "argus")
    check("путь с basename pantheon — запись есть", [r["kind"] for r in h.read()] == ["accept"], h.read())


def t_review_format(h):
    """metis-0823: отказ «только простой командой» называет знаки и где они; если они только в кавычках — даёт
    готовую команду с заменой, и она проходит; у test — объясняет, что запись берёт HEAD папки события."""
    sha = h.sha["tg-read"]
    bad = f"pantheon review accept latark/tg-read 3 {sha}" + CL.replace("merge_gate.py, README", "merge_gate.py; README > x | y")
    d, why = h.pre(bad, role="argus", agent_id="a1")
    check("формат: знаки в кавычках — отказ с готовой командой",
          d == "deny" and "внутри кавычек" in why and "Готовая команда:" in why, why)
    fixed = why.split("Готовая команда:\n", 1)[-1].strip()
    check("формат: готовая команда — без знаков, текст заменён",
          fixed.startswith("pantheon review accept") and not re.search(r"[;|&<>]", fixed) and "merge_gate.py, README → x / y" in fixed,
          fixed)
    d, why2 = h.pre(fixed, role="argus", agent_id="a1")
    check("формат: готовая команда проходит", d == "allow", why2)
    d, why = h.pre(f"pantheon review accept latark/tg-read 3 {sha}{CL} > /dev/null", role="argus", agent_id="a1")
    check("формат: знак снаружи кавычек — отказ без готовой команды",
          d == "deny" and "снаружи кавычек" in why and "Готовая команда" not in why, why)
    d, why = h.pre("cd x && pantheon review test -- true", role="dev-opus", agent_id="d1")
    check("формат: test с cd — отказ объясняет HEAD папки", d == "deny" and "HEAD папки" in why, why)


def t_failure(h):
    sha = h.sha["tg-read"]
    # с ответом словарём, как у успешной: отсекает имя события, а не отсутствие tool_response
    h.post("pantheon review test -- python3 -I tests/run.py", "dev-opus", name="PostToolUseFailure", response=dict(NORMAL))
    h.post(f"pantheon review accept latark/tg-read 3 {sha}{CL}", "argus", name="PostToolUseFailure", response=dict(NORMAL))
    check("PostToolUseFailure — записи нет", h.read() == [], h.read())
    for mode in (["--strict"], ["--managed"]):
        h.post(f"pantheon review accept latark/tg-read 3 {sha}{CL}", "argus", mode=mode)
    check("PostToolUse в режимах --strict и --managed — записи нет", h.read() == [], h.read())


def t_dirty(h):
    p = h.j("projects/tg-read")
    with open(os.path.join(p, "x.txt"), "w") as fh:
        fh.write("x")
    h.post("pantheon review test -- python3 -I tests/run.py", "dev-opus")
    os.remove(os.path.join(p, "x.txt"))
    check("tests в грязном дереве — записи нет", h.read() == [], h.read())


MANAGED_PROBE = r"""
import importlib.util, io, json, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
g.MANAGED_FILE, g.MARKET_GUARD = sys.argv[2], sys.argv[1]
print("active", g.managed_guard_active())
sys.stdin = io.StringIO(sys.argv[3])
g.main()
"""


def t_managed(h):
    sha = h.sha["tg-read"]
    mf = h.j("managed.json")
    with open(mf, "w") as fh:
        json.dump({"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "python3 guard.py --managed"}]}]}},
                  fh)
    event = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "agent_type": "argus", "agent_id": "a1",
             "session_id": "s-coord", "tool_use_id": "t1", "cwd": h.j("projects/tg-read"),
             "tool_input": {"command": f"pantheon review accept latark/tg-read 3 {sha}{CL}"}, "tool_response": NORMAL}
    r = subprocess.run([sys.executable, "-I", "-c", MANAGED_PROBE, RULES, mf, json.dumps(event)], capture_output=True,
                       text=True, env=h.env("projects/tg-read"), timeout=SUB_TIMEOUT)
    check("при активных управляемых настройках PostToolUse пишет",
          "active True" in r.stdout and [x["kind"] for x in h.read()] == ["accept"], r.stdout + r.stderr)


def t_broken_journal(h):
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"))
    with open(h.records, "a") as fh:
        fh.write("битая строка\n" + json.dumps({"v": 2, "kind": "accept"}) + "\n")
    h.seed(rec("accept", "latark/tg-read", 3, sha))
    merge_case("битые строки журнала пропускаются", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), True)
    shutil.rmtree(os.path.dirname(h.records))
    os.makedirs(h.j("elsewhere"))
    os.symlink(h.j("elsewhere"), os.path.dirname(h.records))
    h.post("pantheon review test -- python3 -I tests/run.py", "dev-opus")
    check("папка журнала — симлинк: хук не пишет", os.listdir(h.j("elsewhere")) == [])
    merge_case("папка журнала — симлинк: слияние закрыто", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False,
               "журнал проверок")
    os.remove(os.path.dirname(h.records))


def t_bg_flag(h):
    """Фон по run_in_background: PostToolUse пришёл при запуске, итога тестов ещё нет — ни одной записи."""
    sha = h.sha["tg-read"]
    h.post("pantheon review test -- python3 -I tests/run.py", "dev-opus", background=True, response=BG)
    h.post(f"pantheon review accept latark/tg-read 3 {sha}{CL}", "argus", background=True, response=BG)
    h.post(f"pantheon review talos latark/tg-read 3 {sha}", "talos", background=True, response=NORMAL)
    check("run_in_background — записи нет (tests, accept, talos)", h.read() == [], h.read())


def t_bg_task_id(h):
    """Уведённая в фон (Ctrl+B): флага во входе нет, но в ответе backgroundTaskId — записи нет."""
    sha = h.sha["tg-read"]
    h.post("pantheon review test -- python3 -I tests/run.py", "dev-opus", response=BG)
    h.post(f"pantheon review reject latark/tg-read 3 {sha}", "argus", response=BG)
    check("backgroundTaskId в tool_response — записи нет", h.read() == [], h.read())


def t_bg_task_id_value(h):
    """backgroundTaskId с null или пустой строкой — не фон: запись есть; с числом — фон."""
    for val in (None, ""):
        h.reset()
        h.post("pantheon review test -- python3 -I tests/run.py", "dev-opus", response=dict(NORMAL, backgroundTaskId=val))
        check(f"backgroundTaskId={val!r} — не фон, запись есть", len(h.read()) == 1, h.read())
    h.reset()
    h.post("pantheon review test -- python3 -I tests/run.py", "dev-opus", response=dict(NORMAL, backgroundTaskId=7))
    check("backgroundTaskId=7 — фон, записи нет", h.read() == [], h.read())


def t_bad_response(h):
    sha = h.sha["tg-read"]
    for resp in ("ok", None, ["x"], MISSING):
        h.post("pantheon review test -- python3 -I tests/run.py", "dev-opus", response=resp)
        h.post(f"pantheon review accept latark/tg-read 3 {sha}{CL}", "argus", response=resp)
    check("tool_response не словарь или его нет — записи нет", h.read() == [], h.read())


def t_fg_records(h):
    sha = h.sha["tg-read"]
    h.post("pantheon review test -- python3 -I tests/run.py", "dev-opus", response=NORMAL)
    h.post(f"pantheon review accept latark/tg-read 3 {sha}{CL}", "argus", response=NORMAL)
    check("обычный запуск (не фон, ответ словарём) — записи tests и accept есть",
          [r["kind"] for r in h.read()] == ["tests", "accept"], h.read())


def t_pre_background(h):
    sha = h.sha["tg-read"]
    ev = {"command": "pantheon review test -- python3 -I tests/run.py", "run_in_background": True}
    d, why = h.pre_input(ev, role="dev-opus", agent_id="d1")
    check("PreToolUse: review test в фоне — отказ, текст «без фона»", d == "deny" and "без фона" in why, why)
    d, why = h.pre_input({"command": f"pantheon review accept latark/tg-read 3 {sha}{CL}", "run_in_background": True},
                         role="argus", agent_id="a1")
    check("PreToolUse: review accept в фоне — отказ", d == "deny" and "без фона" in why, why)
    d, why = h.pre_input({"command": "pantheon review test -- python3 -I tests/run.py", "run_in_background": False}, role="dev-opus",
                         agent_id="d1")
    check("PreToolUse: review test без фона — можно", d == "allow", why)
    d, why = h.pre_input({"command": "pantheon review status", "run_in_background": True}, role="dev-opus",
                         agent_id="d1")
    check("PreToolUse: review status в фоне — можно (записи не делает)", d == "allow", why)


def t_pre_not_simple(h):
    sha = h.sha["tg-read"]
    for cmd in ("pantheon review test -- pytest 2>&1 | tail -5", "pantheon review test -- true; true",
                "cd x && pantheon review test -- python3 -I tests/run.py", "pantheon review test -- true > out.txt",
                "pantheon review test -- echo $(id)", "pantheon review test -- echo `id`"):
        d, why = h.pre(cmd, role="dev-opus", agent_id="d1")
        check(f"PreToolUse: непростая `{cmd}` — отказ, код не от тестов", d == "deny" and "код выхода" in why, why)
    d, why = h.pre(f"pantheon review accept latark/tg-read 3 {sha} | cat", role="argus", agent_id="a1")
    check("PreToolUse: accept с | — отказ", d == "deny" and "код выхода" in why, why)
    d, why = h.pre("pantheon review status | head", role="dev-opus", agent_id="d1")
    check("PreToolUse: status с | — можно (записи не делает)", d == "allow", why)


def t_checklist(h):
    """Б6: «принять» — только с перечнем opened, ran, unchecked; запись хранит его, запор без него не пускает."""
    sha = h.sha["tg-read"]
    base = f"pantheon review accept latark/tg-read 3 {sha}"
    h.post(base + CL, "argus")
    recs = h.read()
    check("accept с перечнем — запись с checklist (кавычки и пробелы внутри поля целы)",
          len(recs) == 1 and recs[0]["checklist"] == CHECKLIST, recs)
    h.reset()
    for cmd in (base, base + ' --opened a --ran b', base + ' --opened "" --ran b --unchecked c',
                base + " --opened '  ' --ran b --unchecked c", base + " --opened a --ran b --unchecked c --extra d",
                base + " --opened a --opened b --ran b --unchecked c", base + " --opened a --ran b --unchecked",
                base + " --opened --ran --ran --unchecked --unchecked --opened",  # имена флагов как значения (PR #25)
                base + " --opened=--ran --ran b --unchecked c", base + " --opened a --ran ' --x' --unchecked c"):
        h.post(cmd, "argus")
        d, why = h.pre(cmd, role="argus", agent_id="a1")
        check(f"accept `{cmd[len(base):] or '(без полей)'}` — PreToolUse отказ", d == "deny" and "Записи не будет" in why,
              why)
    check("accept без полного перечня — записи нет", h.read() == [], h.read())
    d, why = h.pre(base + " --opened --ran --ran --unchecked --unchecked --opened", role="argus", agent_id="a1")
    check("перечень из имён флагов — отказ «начинается с «--»»", d == "deny" and "начинается с «--»" in why, why)
    d, why = h.pre(base, role="argus", agent_id="a1")
    check("отказ без перечня называет флаги", "--opened" in why and "--unchecked" in why and "Б6" in why, why)
    h.post(f"pantheon review reject latark/tg-read 3 {sha}", "argus")
    h.post(f"pantheon review reject latark/tg-read 3 {sha} --opened a.py", "argus")
    recs = h.read()
    check("reject — поля по желанию: записи есть, перечень — только заданные поля",
          [r["kind"] for r in recs] == ["reject", "reject"] and "checklist" not in recs[0]
          and recs[1]["checklist"] == {"opened": "a.py"}, recs)
    h.reset()
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"), rec("accept", "latark/tg-read", 3, sha, checklist=None))
    merge_case("accept старого формата (без перечня) — отказ", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False,
               "без перечня проверенного (Б6)")
    merge_case("отказ подсказывает повторить accept с --opened", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False,
               "--opened")
    h.seed(rec("accept", "latark/tg-read", 3, sha, checklist=dict(CHECKLIST, unchecked=" ")))
    merge_case("accept с пустым полем перечня — отказ", h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False,
               "без перечня")
    h.seed(rec("accept", "latark/tg-read", 3, sha, agent_id="argus3"))
    merge_case("accept с перечнем другого argus старый не перекрывает — отказ (metis-0158)",
               h.pre(f"gh pr merge 3 --match-head-commit {sha}"), False, "без перечня")
    h.seed(rec("accept", "latark/tg-read", 3, sha))
    merge_case("новый accept с перечнем того же argus после старого — проходит",
               h.pre(f"gh pr merge 3 --match-head-commit {sha}"), True)


def t_criteria(h):
    """metis-1004: --criteria у accept и reject — по флагу на пункт «Готово, когда»; запись несёт их полем "criteria"
    списком строк как есть, перечень checklist — без них; шлюз их не читает (слияние как без них). У talos флага нет."""
    sha = h.sha["tg-read"]
    c1, c2 = "demo-0001#1 0123456789ab да tests/t.py:12", "demo-0001#2 ba9876543210 да t_x"
    base = f"pantheon review accept latark/tg-read 3 {sha}{CL}"
    h.post("pantheon review test -- python3 -I tests/run.py", "dev-opus")
    h.post(f'{base} --criteria "{c1}" --criteria="{c2}"', "argus")
    recs = h.read()
    check("1004: accept с двумя --criteria — запись с criteria по порядку, checklist без них",
          len(recs) == 2 and recs[1].get("criteria") == [c1, c2] and recs[1]["checklist"] == CHECKLIST, recs)
    merge_case("1004: accept с --criteria засчитан шлюзом как обычный", h.pre(f"gh pr merge 3 --match-head-commit {sha}"),
               True)
    h.reset()
    h.post(base, "argus")
    check("1004: accept без --criteria — поля criteria нет", "criteria" not in h.read()[0], h.read())
    h.reset()
    h.post(f'pantheon review reject latark/tg-read 3 {sha} --criteria "demo-0001#1 0123456789ab нет нет теста"', "argus")
    recs = h.read()
    check("1004: reject с --criteria — запись с criteria, без checklist",
          len(recs) == 1 and recs[0].get("criteria") == ["demo-0001#1 0123456789ab нет нет теста"]
          and "checklist" not in recs[0], recs)
    h.reset()
    for cmd in (f"{base} --criteria", f"{base} --criteria --opened x", f"pantheon review talos latark/tg-read 3 {sha} "
                f'--criteria "{c1}"'):
        h.post(cmd, "talos" if "talos" in cmd else "argus")
        d, why = h.pre(cmd, role="talos" if "talos" in cmd else "argus", agent_id="a1")
        check(f"1004: `{cmd[len(base):] if cmd.startswith(base) else 'talos --criteria'}` — отказ, записи нет",
              d == "deny" and h.read() == [], (why, h.read()))
    h.post(f'{base} --criteria "  "', "argus")
    check("1004: пустой --criteria не сохраняется", "criteria" not in h.read()[0], h.read())


CASES = [t_pass_internal, t_returned_empty, t_old_sha, t_no_tests, t_author_is_reviewer, t_argus_commit, t_admin_auto, t_no_head, t_not_listed, t_core, t_verdict_role, t_reject_after_accept, t_product, t_not_simple, t_review_format, t_failure, t_dirty, t_managed, t_broken_journal, t_bg_flag, t_bg_task_id, t_bg_task_id_value, t_bad_response, t_fg_records, t_pre_background, t_pre_not_simple, t_checklist, t_criteria]


if __name__ == "__main__":
    sys.exit(main(CASES))
