#!/usr/bin/env python3
"""Запор слияния guard, часть «billing»: запасной путь без минут Actions (биллинг), PR из форка, аннотации проверок.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py; разрез metis-1119.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_billing.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403


def _owner_out(h, cmd, pdir):
    """Сырой ответ хука на PreToolUse сессии без роли (для systemMessage при пропуске)."""
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": h.j(pdir),
             "session_id": "s-owner", "tool_use_id": "toolu_" + uuid.uuid4().hex}
    return h.hook(event, pdir)


def t_ci_billing(h):
    """metis-0655: CI не запускался из-за лимита минут или оплаты GitHub Actions (сохранённый ответ PR #222: FAILURE и
    аннотация «The job was not started because …») — вместо CI нужна запись tests на этот SHA и этот репозиторий:
    есть — пропуск со строкой systemMessage, нет (или на другом SHA, другом репозитории, журнал не читается) — отказ
    с командой записи. Обычная красная (PR #225, «Process completed with exit code 1.») и сбой запроса аннотаций —
    отказ, как раньше. Сессия без роли и роль."""
    kit, sha = "projects/agent-kit", h.sha["agent-kit"]
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    owner = dict(role=None, pdir=kit)
    full = ("`pantheon review test -- heavy python3.14 -I plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard "
            "plugins/pantheon plugins/project-tools`")

    def saved(pr):
        runs = _saved(pr, "runs")
        h.runs["agent-kit"] = _runs_on(runs, sha, pr)
        h.ci(_saved(pr)["statusCheckRollup"], name="agent-kit", baseRefName="main")
        _notes_on(h, runs)

    saved(222)
    h.reset_log()
    merge_case("лимит, записи тестов нет — отказ «не запускался» с командой записи", h.pre(cmd, **owner), False,
               f"CI на latark/agent-kit#7@{sha[:12]} не запускался: лимит минут или оплата GitHub Actions")
    merge_case("лимит, записи нет — в отказе готовая команда полного набора", h.pre(cmd, **owner), False, full)
    merge_case("лимит, записи нет — основной способ в отказе: pantheon outside test --wait 590",
               h.pre(cmd, **owner), False, "`pantheon outside test --wait 590` (Bash не в фоне, timeout 600000 мс)")
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("лимит: аннотации спрошены у красных обязательных от pull_request (не у push)",
          "api repos/latark/agent-kit/check-runs/124603333231/annotations?per_page=100" in log
          and "check-runs/124603333226/annotations" in log and "124603302196" not in log, log)
    check("лимит: данные job спрошены у тех же проверок (actions/jobs/<id>)",
          "api repos/latark/agent-kit/actions/jobs/124603333231" in log
          and "api repos/latark/agent-kit/actions/jobs/124603333226" in log, log)
    h.seed(rec("accept", "latark/agent-kit", 7, sha))
    merge_case("лимит, на SHA есть только «принять» argus, записи тестов нет — отказ", h.pre(cmd, **owner), False,
               "не запускался: лимит минут")
    h.seed(full_rec("latark/agent-kit", "e" * 40))
    merge_case("лимит, запись полного набора на другом SHA — отказ", h.pre(cmd, **owner), False, "не запускался: лимит минут")
    h.seed(full_rec("latark/tg-read", sha))
    merge_case("лимит, запись полного набора на этом SHA, но другого репозитория — отказ", h.pre(cmd, **owner), False,
               "не запускался: лимит минут")
    h.seed(rec("tests", "latark/agent-kit", None, sha, ""))
    merge_case("лимит, запись тестов на SHA с другой командой (не FULL_TESTS) — отказ", h.pre(cmd, **owner), False,
               "засчитывается только эта команда")
    h.seed(full_rec("latark/agent-kit", sha, FULL_TESTS_CMD + " && true"))
    merge_case("лимит, запись: полный набор && ещё команда — отказ", h.pre(cmd, **owner), False,
               "засчитывается только эта команда")
    h.seed(full_rec("latark/agent-kit", sha, FULL_TESTS_CMD.replace("plugins/project-tools", "")))
    merge_case("лимит, запись: набор без одного плагина — отказ", h.pre(cmd, **owner), False,
               "засчитывается только эта команда")
    h.seed(full_rec("Latark/Agent-Kit", sha))
    r = _owner_out(h, cmd, kit)
    msg = json.loads(r.stdout).get("systemMessage", "") if r.stdout.strip() else ""
    check("лимит, запись тестов на этом SHA — без роли пропуск", decision(r)[0] == "allow", r.stdout + r.stderr)
    check("лимит, пропуск — systemMessage «CI не запускался … засчитан местный прогон»",
          f"CI не запускался: лимит минут GitHub Actions, засчитан местный прогон (запись полного набора тестов на "
          f"этом коммите) на latark/agent-kit#7@{sha[:12]}" in msg, r.stdout)
    check("лимит, пропуск — systemMessage не называет способ записи (review test или outside test, долг argus #248)",
          "pantheon review test" not in msg and "outside test" not in msg, msg)
    r = _hook_out(h, cmd, kit)
    check("лимит, роль с записями тестов и argus — пропуск со строкой systemMessage",
          decision(r)[0] == "allow" and "засчитан местный прогон" in r.stdout, r.stdout + r.stderr)
    # обычная красная с аннотацией «Process completed with exit code 1.» — отказ и с записью тестов
    saved(225)
    h.reset_log()
    merge_case("PR 225 (обычная красная) с записью тестов — без роли отказ", h.pre(cmd, **owner), False,
               "tests/affected красная: FAILURE")
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("PR 225: аннотации красной affected спрошены, признака лимита нет", "check-runs/124790157366/annotations"
          in log, log)
    merge_case("PR 225 с записями — роль: отказ", h.pre(cmd, pdir=kit), False, "tests/affected красная: FAILURE")
    saved(222)
    os.remove(h.j("gh.notes.124603333226"))
    merge_case("лимит, аннотации traces не получены — отказ «повтори позже», а не «почини» (metis-0813)",
               h.pre(cmd, **owner), False, "аннотации CI или данные job красной проверки не получены (сбой gh) — не "
               "лимит ли это минут GitHub Actions, не проверить: повтори слияние позже; аварийный путь — `gh pr merge` "
               "в собственном терминале владельца")   # С1 argus #381: на пути владельца — и аварийный путь
    # проверка безопасности 0655: аннотацию лимита job мог напечатать сам — нужен ещё «job не стартовал» от GitHub
    saved(222)
    os.remove(h.j("gh.jobs.124603333226"))
    d, why = h.pre(cmd, pdir=kit)
    check("лимит, данные job traces не получены — роль: отказ «повтори позже», без аварийного пути (metis-0813)",
          d == "deny" and "аннотации CI или данные job красной проверки не получены (сбой gh)" in why
          and "аварийный путь" not in why, why)
    saved(222)
    with open(h.j("gh.jobs.124603333231"), "w") as fh:
        json.dump(_saved(225, "runs")["jobs"]["124790157366"], fh)
    merge_case("лимит, аннотация есть, но job affected стартовал (раннер, 8 шагов — PR 225) — отказ",
               h.pre(cmd, **owner), False, "tests/affected красная: FAILURE")
    saved(222)
    h.seed(full_rec("latark/agent-kit", sha, FULL_TESTS_CMD.split(" -- ", 1)[1].replace("heavy ", "")
                    + "  # .pantheon-verify ветки (HEAD)"))
    merge_case("лимит, запись прохода pantheon outside test (без heavy, с хвостом-комментарием) — пропуск",
               h.pre(cmd, **owner), True)
    h.runs.clear()
    bill = _saved(222, "runs")["annotations"]["124603333231"]
    idle = _saved(222, "runs")["jobs"]["124603333231"]
    aff_b = dict(AFFECTED, conclusion="FAILURE", notes=bill, job=idle)
    tr_b = dict(TRACES, conclusion="FAILURE", notes=bill, job=idle)
    h.ci([AFFECTED, tr_b], name="agent-kit")
    merge_case("лимит только у traces, affected зелёная, запись есть — пропуск", h.pre(cmd, **owner), True)
    h.ci([aff_b, dict(TRACES, status="IN_PROGRESS", conclusion="")], name="agent-kit")
    merge_case("лимит у affected, traces идёт — отказ по красной", h.pre(cmd, **owner), False,
               "tests/affected красная: FAILURE")
    h.ci([aff_b, dict(tr_b, conclusion="TIMED_OUT")], name="agent-kit")
    merge_case("traces TIMED_OUT с аннотацией лимита — отказ", h.pre(cmd, **owner), False, "traces красная: TIMED_OUT")
    h.ci([aff_b, tr_b], name="agent-kit")
    merge_case("лимит у обеих (синтетика), запись есть — пропуск", h.pre(cmd, **owner), True)
    # С1 argus #248: на засчитанном запасном пути предупреждение о красной необязательной не теряется
    h.ci([aff_b, tr_b, dict(AFFECTED, name="full", conclusion="FAILURE")], name="agent-kit")
    for who, r in (("без роли", _owner_out(h, cmd, kit)), ("роль", _hook_out(h, cmd, kit))):
        msg = json.loads(r.stdout).get("systemMessage", "") if r.stdout.strip() else ""
        check(f"лимит + красная необязательная tests/full, {who}: пропуск, в systemMessage и лимит, и tests/full",
              decision(r)[0] == "allow" and "засчитан местный прогон" in msg
              and f"необязательная проверка GitHub tests/full красная: FAILURE на latark/agent-kit#7@{sha[:12]}" in msg,
              r.stdout + r.stderr)
    # журнал записей не читается (папка — симлинк) — отказ, а не пропуск
    d = h.j(".local/state/pantheon/merge-gate")
    shutil.rmtree(d)
    os.symlink(h.j("ai"), d)
    try:
        merge_case("лимит, журнал записей не читается — отказ", h.pre(cmd, **owner), False,
                   "журнал записей тестов ~/.local/state/pantheon/merge-gate/records.jsonl не читается")
    finally:
        os.remove(d)


def t_ci_billing_unit(h):
    """metis-0655: ci_runs несёт id и число аннотаций; ci_billing_ids и ci_billing — каждое условие признака лимита."""
    mg = _load_merge_gate("merge_gate_ci_billing")
    req = mg.required_checks("latark/agent-kit", "main")
    s222, s225 = _saved(222, "runs"), _saved(225, "runs")
    sha = "6b7a70dc2f1ee50ef12894607aab72760220636a"
    runs = mg.ci_runs(s222["workflow_runs"], s222["check_runs"], sha, 222)
    notes = {int(k): v for k, v in s222["annotations"].items()}
    jobs = {int(k): v for k, v in s222["jobs"].items()}
    started = s225["jobs"]["124790157366"]
    check("ci_runs: id и annotations проверки в каждой записи",
          {(r["name"], r["event"], r["id"], r["annotations"]) for r in runs} ==
          {("full", "pull_request", 124603334301, 0), ("affected", "pull_request", 124603333231, 1),
           ("traces", "pull_request", 124603333226, 2), ("traces", "push", 124603302196, 2)}, runs)
    check("ci_runs: output не словарь — annotations None, а не сбой разбора",
          mg.ci_runs(s222["workflow_runs"], dict(s222["check_runs"], check_runs=[
              dict(c, output="x") for c in s222["check_runs"]["check_runs"]]), sha, 222)[0]["annotations"] is None)
    ids = mg.ci_billing_ids(runs, req)
    check("PR 222: id — красные обязательные от pull_request", sorted(ids) == [124603333226, 124603333231], ids)
    check("PR 222: признак лимита есть", mg.ci_billing(runs, req, notes, jobs) is True)
    check("PR 222: без данных job признака нет", mg.ci_billing(runs, req, notes, {}) is False)
    check("PR 222: jobs не словарь — признака нет", mg.ci_billing(runs, req, notes, None) is False)
    check("PR 222: job traces стартовал — признака нет",
          mg.ci_billing(runs, req, notes, {**jobs, 124603333226: started}) is False)
    sha225 = s225["check_runs"]["check_runs"][0]["head_sha"]
    r225 = mg.ci_runs(s225["workflow_runs"], s225["check_runs"], sha225, 225)
    check("PR 225: id красной affected спрашивается", mg.ci_billing_ids(r225, req) == [124790157366],
          mg.ci_billing_ids(r225, req))
    check("PR 225: «Process completed with exit code 1.» — признака нет",
          mg.ci_billing(r225, req, {int(k): v for k, v in s225["annotations"].items()},
                        {124790157366: started}) is False)
    check("PR 225: аннотацию лимита job напечатал сам (раннер и шаги есть) — признака нет",
          mg.ci_billing(r225, req, {124790157366: notes[124603333231]}, {124790157366: started}) is False)
    check("PR 225 с аннотацией лимита и job без раннера — признак (обе части нужны)",
          mg.ci_billing(r225, req, {124790157366: notes[124603333231]}, {124790157366: jobs[124603333231]}) is True)
    idle = jobs[124603333231]
    for name, job, want in (
            ("PR 222 affected (0, \"\", [])", idle, True),
            ("runner_id null, runner_name null", dict(idle, runner_id=None, runner_name=None), True),
            ("PR 225 (раннер, 8 шагов)", started, False),
            ("runner_id не 0", dict(idle, runner_id=7), False),
            ("runner_id False", dict(idle, runner_id=False), False),
            ("runner_id строкой \"0\"", dict(idle, runner_id="0"), False),
            ("runner_name непустое", dict(idle, runner_name="GitHub Actions 1"), False),
            ("шаги есть", dict(idle, steps=[{"name": "Set up job"}]), False),
            ("steps нет", {k: v for k, v in idle.items() if k != "steps"}, False),
            ("steps None", dict(idle, steps=None), False),
            ("runner_id нет", {k: v for k, v in idle.items() if k != "runner_id"}, False),
            ("runner_name нет", {k: v for k, v in idle.items() if k != "runner_name"}, False),
            ("ответ None (сбой gh)", None, False),
            ("ответ — список", [idle], False)):
        check(f"ci_job_unstarted: {name} → {want}", mg.ci_job_unstarted(job) is want, job)
    aff = next(r for r in runs if r["name"] == "affected")
    tr = next(r for r in runs if r["name"] == "traces" and r["event"] == "pull_request")
    ok_aff, ok_tr = dict(aff, conclusion="success"), dict(tr, conclusion="success")
    cases = [
        ("required пуст", runs, (), []),
        ("runs не список (None)", None, req, []),
        ("runs — строка неполных данных", "неполные", req, []),
        ("все зелёные — FAILURE нет", [ok_aff, ok_tr], req, []),
        ("traces только от push", [aff, dict(tr, event="push")], req, []),
        ("нет traces", [aff], req, []),
        ("красная необязательная tests/full с лимитом не в счёт",
         [ok_aff, ok_tr, dict(aff, name="full", id=9)], req, []),
        ("affected идёт", [dict(aff, status="in_progress", conclusion=""), tr], req, []),
        ("affected идёт, а conclusion success", [dict(aff, status="in_progress", conclusion="success"), tr], req, []),
        ("affected идёт, а conclusion failure", [dict(aff, status="in_progress", conclusion="failure"), tr], req, []),
        ("affected TIMED_OUT", [dict(aff, conclusion="timed_out"), tr], req, []),
        ("affected CANCELLED", [dict(aff, conclusion="cancelled"), tr], req, []),
        ("affected SKIPPED", [dict(aff, conclusion="skipped"), ok_tr], req, []),
        ("id None", [dict(aff, id=None), tr], req, []),
        ("id строкой", [dict(aff, id="124603333231"), tr], req, []),
        ("id True", [dict(aff, id=True), tr], req, []),
        ("аннотаций 0", [dict(aff, annotations=0), tr], req, []),
        ("аннотаций None", [dict(aff, annotations=None), tr], req, []),
        ("аннотаций строкой", [dict(aff, annotations="1"), tr], req, []),
        ("запись не словарь", ["x", aff, tr], req, [124603333231, 124603333226]),
        ("лимит у affected, traces зелёная", [aff, ok_tr], req, [124603333231]),
        ("регистр итога не важен", [dict(aff, status="COMPLETED", conclusion="FAILURE"), ok_tr], req, [124603333231]),
    ]
    for name, rs, rq, want in cases:
        got = mg.ci_billing_ids(rs, rq)
        check(f"ci_billing_ids: {name} → {want}", got == want, got)
    one = [aff, ok_tr]
    good = notes[124603333231]
    for name, ns, want in (
            ("аннотация лимита", {124603333231: good}, True),
            ("лимит и ещё notice", {124603333231: notes[124603333226]}, True),
            ("notes не словарь", [good], False),
            ("нет ответа по id", {}, False),
            ("ответ None (сбой gh)", {124603333231: None}, False),
            ("ответ — словарь, а не список", {124603333231: good[0]}, False),
            ("ответ — число", {124603333231: 5}, False),
            ("текст начинается с «The job», но другой",
             {124603333231: [dict(good[0], message="The job was not started because the runner is offline")]}, False),
            ("уровень warning", {124603333231: [dict(good[0], annotation_level="warning")]}, False),
            ("путь не .github", {124603333231: [dict(good[0], path="tests/x.py")]}, False),
            ("текст не с начала", {124603333231: [dict(good[0], message="x " + good[0]["message"])]}, False),
            ("текст другой", {124603333231: [dict(good[0], message="Process completed with exit code 1.")]}, False),
            ("текста нет", {124603333231: [dict(good[0], message=None)]}, False),
            ("аннотация не словарь", {124603333231: ["The job was not started because"]}, False)):
        got = mg.ci_billing(one, req, ns, jobs)
        check(f"ci_billing: {name} → {want}", got is want, got)
    check("ci_billing: две красные, лимит только у одной — признака нет",
          mg.ci_billing(runs, req, {**notes, 124603333226: s225["annotations"]["124790157366"]}, jobs) is False)
    check("ci_billing: ids пуст — признака нет", mg.ci_billing([ok_aff, ok_tr], req, notes, jobs) is False)
    # full_tests_record: засчитывается только команда FULL_TESTS этого репозитория
    full = FULL_TESTS_CMD.split(" -- ", 1)[1]
    for name, repo, cmd, want in (
            ("хук: pantheon review test -- FULL", "latark/agent-kit", FULL_TESTS_CMD, True),
            ("путь к pantheon", "latark/agent-kit", "/x/bin/pantheon review test -- " + full, True),
            ("проход: сама команда", "latark/agent-kit", full, True),
            ("проход: без heavy, хвост «# …»", "latark/agent-kit",
             full.replace("heavy ", "") + "  # .pantheon-verify ветки (HEAD)", True),
            ("регистр и владелец репозитория не важны", "Other/AGENT-KIT", FULL_TESTS_CMD, True),
            ("лишние пробелы", "latark/agent-kit", FULL_TESTS_CMD.replace(" -j ", "   -j "), True),
            ("комментарий после табуляции", "latark/agent-kit", FULL_TESTS_CMD + "\t# x", True),
            ("«#» внутри слова (bash: часть слова)", "latark/agent-kit", FULL_TESTS_CMD + "#x", False),
            ("«#» внутри слова в середине", "latark/agent-kit",
             FULL_TESTS_CMD.replace("plugins/guard", "plugins/guard#x"), False),
            ("« #» в кавычках — кавычка рвётся, не засчитано", "latark/agent-kit", FULL_TESTS_CMD + " ' #x'", False),
            ("другая команда", "latark/agent-kit", "pantheon review test -- true", False),
            ("полный && ещё", "latark/agent-kit", FULL_TESTS_CMD + " && echo", False),
            ("полный ; ещё", "latark/agent-kit", FULL_TESTS_CMD + "; echo", False),
            ("без одного плагина", "latark/agent-kit", FULL_TESTS_CMD.replace(" plugins/project-tools", ""), False),
            ("ещё флаг", "latark/agent-kit", FULL_TESTS_CMD + " -k x", False),
            ("pantheon review accept", "latark/agent-kit", FULL_TESTS_CMD.replace(" test ", " accept "), False),
            ("другая программа вместо pantheon", "latark/agent-kit", "x" + FULL_TESTS_CMD, False),
            ("кавычка не закрыта", "latark/agent-kit", FULL_TESTS_CMD + " '", False),
            ("cmd нет", "latark/agent-kit", None, False),
            ("cmd пусто", "latark/agent-kit", "", False),
            ("репозитория нет в FULL_TESTS", "latark/tg-read", FULL_TESTS_CMD, False),
            ("репозиторий None", None, FULL_TESTS_CMD, False)):
        r = rec("tests", "latark/agent-kit", None, sha, "")
        if cmd is None:
            r.pop("cmd")
        else:
            r["cmd"] = cmd
        check(f"full_tests_record: {name} → {want}", mg.full_tests_record(repo, r) is want, cmd)
    check("full_tests_record: запись не словарь — нет", mg.full_tests_record("o/agent-kit", "x") is False)
    # _ci_jobs: ответ job — один объект JSON; _gh_json отдаёт его списком из одного значения
    gh_json = mg._gh_json
    for name, got, want in (("один объект", [idle], idle), ("два объекта подряд", [idle, idle], None),
                            ("пусто", [], None), ("сбой gh", None, None)):
        mg._gh_json = lambda a, got=got: got
        check(f"_ci_jobs: {name} → {'job' if want else None}", mg._ci_jobs("o/r", [5]) == {5: want})
    mg._gh_json = gh_json
    # _billing_problem: запись tests на SHA — без учёта регистра репозитория; предупреждение — строка пропуска
    mg.read_records = lambda: [full_rec("latark/agent-kit", sha)]
    got = mg._billing_problem("Latark/Agent-Kit", 7, sha)
    check("_billing_problem: -R в другом регистре (Latark/Agent-Kit) — запись засчитана",
          got[0] is None and len(got[1]) == 1, got)
    mg.read_records = lambda: [dict(rec("accept", "latark/agent-kit", 7, sha), cmd=FULL_TESTS_CMD)]
    check("_billing_problem: на SHA только «принять» (даже с командой полного набора) — отказ",
          "не запускался: лимит минут" in (mg._billing_problem("latark/agent-kit", 7, sha)[0] or ""))
    mg.read_records = lambda: [rec("tests", "latark/agent-kit", None, sha, "")]
    check("_billing_problem: запись на SHA с другой командой — отказ с командой FULL_TESTS",
          f"`{FULL_TESTS_CMD}`" in (mg._billing_problem("latark/agent-kit", 7, sha)[0] or ""))
    mg.read_records = lambda: [full_rec("o/x", sha)]
    got = mg._billing_problem("o/x", 7, sha)[0] or ""
    check("_billing_problem: репозиторий без записи в FULL_TESTS — отказ «запасного пути нет», без шаблона",
          "запасного пути у репозитория нет" in got and "pantheon review test" not in got, got)


# голова PR из форка в ответе gh pr view (metis-0649): поля как у gh 2.103 (headRepository с nameWithOwner)
FORK = {"isCrossRepository": True, "headRepository": {"id": "R_x", "name": "agent-kit", "nameWithOwner": "Ext/agent-kit"},
        "headRefName": "feat"}


def _fork_runs(rollup, repo="Ext/agent-kit", branch="feat"):
    """Записи rollup как запуски PR из форка (rest_runs): pull_requests пуст — GitHub его у форка не заполняет
    (github/docs#22501), head — форк repo и ветка branch."""
    return [dict(c, prs=(), head_repo=repo, head_branch=branch) for c in rollup]


def t_ci_fork_unit(h):
    """metis-0649: ci_fork и ci_runs для PR из форка напрямую — каждое условие сверки запуска (SHA, событие,
    репозиторий head, ветка head) и ответ «не получены», когда форк или ветка неизвестны."""
    mg = _load_merge_gate("merge_gate_ci_fork")
    check("PR_VIEW_FIELDS: есть isCrossRepository, headRepository и headRefName",
          {"isCrossRepository", "headRepository", "headRefName"} <= set(mg.PR_VIEW_FIELDS.split(",")),
          mg.PR_VIEW_FIELDS)
    check("ci_fork: isCrossRepository false — None", mg.ci_fork(dict(FORK, isCrossRepository=False)) is None)
    check("ci_fork: isCrossRepository нет — None", mg.ci_fork({"headRefName": "feat"}) is None)
    check("ci_fork: isCrossRepository строкой «true» — None", mg.ci_fork(dict(FORK, isCrossRepository="true")) is None)
    check("ci_fork: ответ не словарь — None", mg.ci_fork(None) is None)
    check("ci_fork: форк — (owner/name в нижнем регистре, ветка)", mg.ci_fork(FORK) == ("ext/agent-kit", "feat"),
          mg.ci_fork(FORK))
    check("ci_fork: headRepository нет — пустое имя", mg.ci_fork(dict(FORK, headRepository=None)) == ("", "feat"))
    check("ci_fork: nameWithOwner нет — пустое имя",
          mg.ci_fork(dict(FORK, headRepository={"name": "agent-kit"})) == ("", "feat"))
    check("ci_fork: ветка не строка — пустая ветка", mg.ci_fork(dict(FORK, headRefName=None)) == ("ext/agent-kit", ""))
    sha, fork = "a" * 40, ("ext/agent-kit", "feat")
    one = {"name": "tests", "event": "pull_request", "head_sha": sha, "pull_requests": [],
           "head_repository": {"full_name": "Ext/Agent-Kit"}, "head_branch": "feat"}
    wr = {"total_count": 6, "workflow_runs": [
        dict(one, check_suite_id=1),                                                  # засчитан: регистр имени любой
        dict(one, check_suite_id=2, head_repository={"full_name": "evil/agent-kit"}),  # чужой форк
        dict(one, check_suite_id=3, head_branch="other"),                              # чужая ветка того же форка
        dict(one, check_suite_id=4, event="push"),                                     # не pull_request
        dict(one, check_suite_id=5, head_sha="b" * 40),                                # чужой SHA у запуска
        dict(one, check_suite_id=6, head_repository={"full_name": "latark/agent-kit"},
             pull_requests=[{"number": 7}])]}                                          # base-репозиторий с номером PR
    cr = {"total_count": 6, "check_runs": [{"name": f"job{i}", "status": "completed", "conclusion": "success",
                                            "head_sha": sha, "check_suite": {"id": i}} for i in range(1, 7)]}
    got = mg.ci_runs(wr, cr, sha, 7, fork)
    check("ci_runs форк: засчитан только запуск pull_request с head этого форка и ветки на этом SHA",
          [g["name"] for g in got or []] == ["job1"], got)
    got = mg.ci_runs(wr, cr, sha, 7)
    check("ci_runs не форк: как раньше — только запуск с номером PR в pull_requests",
          [g["name"] for g in got or []] == ["job6"], got)
    for bad in (("", "feat"), ("ext/agent-kit", "")):
        got = mg.ci_runs(wr, cr, sha, 7, bad)
        check(f"ci_runs форк {bad}: форк или ветка не получены — строка «не получены»",
              isinstance(got, str) and got.startswith(mg.CI_NONE) and "из форка" in got, got)
    v = mg.ci_verdict([AFFECTED, TRACES], mg.required_checks("latark/agent-kit", "main"),
                      mg.ci_runs(wr, cr, sha, 7, ("", "feat")))
    check("ci_verdict: форк не получен — fail с этим текстом", v[0] == "fail" and "из форка" in v[1], v)
    bad = {"total_count": 1, "workflow_runs": [dict(one, check_suite_id=1, head_repository=None)]}
    check("ci_runs форк: head_repository null у запуска на этом SHA — None (не разобран)",
          mg.ci_runs(bad, cr, sha, 7, fork) is None)
    no_pr = {"total_count": 1, "workflow_runs": [dict({k: v for k, v in one.items() if k != "pull_requests"},
                                                      check_suite_id=1)]}
    check("ci_runs форк: поле pull_requests не нужно",
          [g["name"] for g in mg.ci_runs(no_pr, cr, sha, 7, fork) or []] == ["job1"])


def t_ci_fork(h):
    """metis-0649: PR из форка через хук. Зелёные запуски его head (форк и ветка) — пропуск и у роли, и в сессии без
    роли; зелёные запуски чужого форка или чужой ветки на том же SHA — отказ «не встали»; форк не получен — отказ
    «не получены»; обычный PR — как раньше, по pull_requests."""
    kit, sha = "projects/agent-kit", h.sha["agent-kit"]
    h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"), rec("accept", "latark/agent-kit", 7, sha))
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    owner = dict(role=None, pdir=kit)
    green = [AFFECTED, TRACES]
    h.ci(_fork_runs(green), name="agent-kit", **FORK)
    merge_case("форк: зелёные запуски его head — проходит", h.pre(cmd, pdir=kit), True)
    merge_case("форк: зелёные запуски его head, без роли — проходит", h.pre(cmd, **owner), True)
    h.ci(_fork_runs(green, repo="evil/agent-kit"), name="agent-kit", **FORK)
    merge_case("форк: зелёные запуски чужого форка на том же SHA — отказ", h.pre(cmd, pdir=kit), False,
               "ещё не встали")
    merge_case("форк: чужой форк, без роли — отказ", h.pre(cmd, **owner), False, "ещё не встали")
    h.ci(_fork_runs(green, branch="other"), name="agent-kit", **FORK)
    merge_case("форк: зелёные запуски чужой ветки того же форка — отказ", h.pre(cmd, pdir=kit), False,
               "ещё не встали")
    h.ci(_fork_runs(green) + [dict(TRACES, event="push", prs=(), head_repo="Ext/agent-kit", head_branch="feat")],
         name="agent-kit", **FORK)
    merge_case("форк: дубль от push рядом с зелёным pull_request — проходит", h.pre(cmd, pdir=kit), True)
    h.ci(_fork_runs([AFFECTED]) + [dict(TRACES, event="push", prs=(), head_repo="Ext/agent-kit",
                                        head_branch="feat")], name="agent-kit", **FORK)
    merge_case("форк: traces только от push — отказ", h.pre(cmd, pdir=kit), False, "check-traces/traces")
    h.ci(_fork_runs([AFFECTED, dict(TRACES, conclusion="FAILURE")]), name="agent-kit", **FORK)
    merge_case("форк: красная обязательная — отказ", h.pre(cmd, pdir=kit), False, "check-traces/traces красная")
    h.ci(_fork_runs(green), name="agent-kit", **dict(FORK, headRepository=None))
    merge_case("форк: headRepository не получен — отказ «не получены»", h.pre(cmd, pdir=kit), False,
               "PR из форка, а его репозиторий или ветка head не получены")
    h.ci(_fork_runs(green), name="agent-kit", **dict(FORK, headRefName=None))
    merge_case("форк: headRefName не получен — отказ «не получены»", h.pre(cmd, pdir=kit), False, "из форка")
    h.ci(_fork_runs(green), name="agent-kit", **dict(FORK, isCrossRepository=False))
    merge_case("не форк: запуски без номера PR (как у форка) — отказ, как раньше", h.pre(cmd, pdir=kit), False,
               "ещё не встали")
    h.ci(green, name="agent-kit", isCrossRepository=False, headRepository=None, headRefName=None)
    merge_case("не форк: обычный PR — проходит, как раньше", h.pre(cmd, pdir=kit), True)


# один процесс, несколько событий (metis-0650): main guard_rules по очереди, stdout каждого — отдельно
NOTES_DRIVER = ("import contextlib, io, json, sys\n"
                "hooks, events = sys.argv[1], sys.argv[2:]\n"
                "sys.argv = [hooks + '/guard.py']\n"
                "sys.path.insert(0, hooks)\n"
                "import guard_rules\n"
                "out = []\n"
                "for e in events:\n"
                "    buf = io.StringIO()\n"
                "    with contextlib.redirect_stdout(buf):\n"
                "        guard_rules.main(e.encode())\n"
                "    out.append(buf.getvalue())\n"
                "print(json.dumps(out))\n")


def t_notes_events(h):
    """metis-0650: предупреждение шлюза (красная необязательная проверка) едет возвратом проверки, а не списком
    модуля: несколько событий в одном процессе (как будет в демоне хуков, metis-0330) — systemMessage второго без
    предупреждений первого. И у роли, и в сессии без роли."""
    kit, sha, tg = "projects/agent-kit", h.sha["agent-kit"], h.sha["tg-read"]
    h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"), rec("accept", "latark/agent-kit", 7, sha))
    full = dict(AFFECTED, name="full", conclusion="FAILURE")
    h.ci([AFFECTED, TRACES, full], name="agent-kit")
    note = f"необязательная проверка GitHub tests/full красная: FAILURE на latark/agent-kit#7@{sha[:12]}"

    def ev(cmd, role="domain-coordinator"):
        e = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": h.j(kit),
             "session_id": "s-coord", "tool_use_id": "toolu_" + uuid.uuid4().hex}
        if role:
            e["agent_type"] = role
        return json.dumps(e)

    merge = f"gh pr merge 7 --match-head-commit {sha}"
    events = [ev(merge), ev("git status"), ev(merge, role=None), ev(f"gh pr merge 3 -R latark/tg-read "
                                                                     f"--match-head-commit {tg}", role=None)]
    r = subprocess.run([sys.executable, "-I", "-c", NOTES_DRIVER, os.path.dirname(GUARD), *events],
                       capture_output=True, text=True, env=h.env(kit), timeout=60)
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = None
    check("один процесс: четыре события разобраны без сбоя", r.returncode == 0 and isinstance(out, list)
          and len(out) == 4, r.stdout + r.stderr)
    out = out if isinstance(out, list) and len(out) == 4 else ["", "", "", ""]

    def msg(raw):
        try:
            return json.loads(raw).get("systemMessage", "") if raw.strip() else ""
        except ValueError:
            return raw

    check("один процесс: 1-е событие (роль, слияние с красной необязательной) — systemMessage с предупреждением",
          msg(out[0]).count(note) == 1 and '"deny"' not in out[0], out[0])
    check("один процесс: 2-е событие (git status) — без вывода, предупреждение 1-го не попало", out[1] == "", out[1])
    check("один процесс: 3-е событие (без роли, то же слияние) — предупреждение ровно одно, своё",
          msg(out[2]).count(note) == 1 and '"deny"' not in out[2], out[2])
    check("один процесс: 4-е событие (без роли, зелёный tg-read) — без вывода", out[3] == "", out[3])


def t_ci_fork_billing(h):
    """Долг argus #248 (проба probe_fb.py): лимит минут у PR из форка. Запуски форка без номера PR засчитываются по
    репозиторию и ветке head (metis-0649) и на запасном пути: запись полного набора есть — пропуск без роли со строкой
    systemMessage; записи нет — отказ и без роли, и у роли. Лимит у чужого форка, чужой ветки или у не-форка без номера
    PR — «ещё не встали»; форк без headRepository — «не получены»."""
    kit, sha = "projects/agent-kit", h.sha["agent-kit"]
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    owner = dict(role=None, pdir=kit)

    def fork_saved(repo="Ext/agent-kit", branch="feat", cross=True):
        runs = _saved(222, "runs")
        wr, cr = _runs_on(runs, sha, 222)
        for r in wr["workflow_runs"]:
            r["pull_requests"] = []
            r["head_repository"] = {"full_name": repo}
            r["head_branch"] = branch
        h.runs["agent-kit"] = (wr, cr)
        h.ci(_saved(222)["statusCheckRollup"], name="agent-kit", baseRefName="main",
             **dict(FORK, isCrossRepository=cross))
        _notes_on(h, runs)

    fork_saved()
    merge_case("форк + лимит, записи нет, без роли — отказ «не запускался»", h.pre(cmd, **owner), False,
               "не запускался: лимит минут")
    merge_case("форк + лимит, записи нет, роль — отказ «нет записи тестов»", h.pre(cmd, pdir=kit), False,
               "нет записи тестов")
    h.seed(full_rec("latark/agent-kit", sha))
    merge_case("форк + лимит, запись полного набора — без роли пропуск", h.pre(cmd, **owner), True)
    r = _owner_out(h, cmd, kit)
    check("форк + лимит, без роли: systemMessage «засчитан местный прогон»", "засчитан местный прогон" in r.stdout,
          r.stdout + r.stderr)
    for how, kw in (("чужого форка на том же SHA", dict(repo="evil/agent-kit")),
                    ("чужой ветки форка", dict(branch="other")),
                    ("не форк, запуски без номера PR", dict(cross=False))):
        fork_saved(**kw)
        merge_case(f"лимит у {how}, запись есть — отказ «ещё не встали»", h.pre(cmd, **owner), False, "ещё не встали")
    fork_saved()
    h.view["agent-kit"]["headRepository"] = None
    h.write_view("agent-kit")
    merge_case("форк без headRepository, лимит, запись есть — отказ «не получены»", h.pre(cmd, **owner), False,
               "не получены")
    h.runs.clear()


CASES = [t_ci_fork_billing, t_ci_fork_unit, t_ci_fork, t_notes_events, t_ci_billing, t_ci_billing_unit]


if __name__ == "__main__":
    sys.exit(main(CASES))
