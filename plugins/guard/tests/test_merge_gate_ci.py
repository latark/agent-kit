#!/usr/bin/env python3
"""Запор слияния guard, часть «ci»: проверки GitHub: statusCheckRollup, обязательные проверки agent-kit (REQUIRED_CHECKS), ci_verdict.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py; разрез metis-1119.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_ci.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403


def t_ci(h):
    """metis-0297: шлюз пускает gh pr merge только при зелёных проверках GitHub на head PR (statusCheckRollup)."""
    sha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, sha, "dev-opus"), rec("accept", "latark/tg-read", 3, sha))
    cmd = f"gh pr merge 3 --match-head-commit {sha}"
    merge_case("CI: зелёные проверки — проходит", h.pre(cmd), True)
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("CI: gh pr view зовётся с -R, номером и statusCheckRollup",
          "pr view 3 -R latark/tg-read --json headRefOid,baseRefOid,baseRefName,changedFiles,statusCheckRollup" in log, log)
    check("CI: зелёные — один вызов gh, workflows не спрашивает", log.count("\n") == 1, log)
    red = dict(RUN_OK, conclusion="FAILURE")
    h.ci([GREEN[1], red])
    merge_case("CI: красная CheckRun — отказ с именем проверки", h.pre(cmd), False, "check-traces красная: FAILURE")
    for concl in ("CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", None):
        h.ci([dict(RUN_OK, conclusion=concl)])
        merge_case(f"CI: CheckRun с итогом {concl} — отказ", h.pre(cmd), False, "красная")
    h.ci([RUN_OK, {"context": "ci/legacy", "state": "FAILURE"}])
    merge_case("CI: красный StatusContext — отказ с именем", h.pre(cmd), False, "ci/legacy красная: FAILURE")
    h.ci([RUN_OK, {"context": "ci/legacy", "state": "ERROR"}])
    merge_case("CI: StatusContext ERROR — отказ", h.pre(cmd), False, "ci/legacy красная: ERROR")
    for status in ("IN_PROGRESS", "QUEUED", "PENDING", "WAITING"):
        h.ci([dict(RUN_OK, status=status, conclusion="")])
        merge_case(f"CI: CheckRun {status} — отказ «ещё идут»", h.pre(cmd), False, "ещё идут: check-traces")
    h.ci([RUN_OK, {"context": "ci/legacy", "state": "PENDING"}])
    merge_case("CI: StatusContext PENDING — отказ «ещё идут»", h.pre(cmd), False, "ещё идут: ci/legacy")
    h.ci([dict(RUN_OK, conclusion="SKIPPED"), dict(RUN_OK, name="lint", conclusion="NEUTRAL")])
    merge_case("CI: SKIPPED и NEUTRAL — проходит", h.pre(cmd), True)
    open(h.j("gh.ci.fail"), "w").close()
    merge_case("CI: gh не ответил (нет сети) — отказ с текстом", h.pre(cmd), False, "проверки GitHub не получены")
    os.remove(h.j("gh.ci.fail"))
    h.ci(None, raw="не json")
    merge_case("CI: неразборный ответ gh — отказ", h.pre(cmd), False, "проверки GitHub не получены")
    h.ci(None, raw=json.dumps({"headRefOid": sha, "baseRefOid": BASE, "baseRefName": "main"}))
    merge_case("CI: нет statusCheckRollup в ответе — отказ", h.pre(cmd), False, "проверки GitHub не получены")
    h.ci(["x"])
    merge_case("CI: проверка не словарь — отказ", h.pre(cmd), False, "проверки GitHub не получены")
    h.ci(GREEN, head=OLD)
    merge_case("CI: чужой headRefOid — отказ", h.pre(cmd), False, f"на другом коммите ({OLD})")
    h.ci(GREEN, head=sha.upper())
    merge_case("CI: headRefOid в верхнем регистре — тот же SHA, проходит", h.pre(cmd), True)
    h.ci([])
    merge_case("CI: проверок нет и .github/workflows нет (404) ни на head, ни на base — проходит", h.pre(cmd), True)
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("CI: при пустом rollup спрашивает .github/workflows на head и на base PR",
          f"api repos/latark/tg-read/contents/.github/workflows?ref={sha}" in log
          and f"api repos/latark/tg-read/contents/.github/workflows?ref={BASE}" in log, log)
    h.wf(sha, '[{"name": "check-traces.yml", "type": "file"}]')
    h.reset_log()
    merge_case("CI: проверок нет, а .github/workflows на head есть — отказ «не встали»", h.pre(cmd), False,
               "ещё не встали")
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("CI: workflows на head есть — base не спрашивает", f"ref={BASE}" not in log, log)
    h.reset_wf()
    h.wf(BASE, '[{"name": "check-traces.yml", "type": "file"}]')
    merge_case("CI: head 404, а на base PR .github/workflows есть (PR убирает workflows) — отказ", h.pre(cmd), False,
               f"на base PR ({BASE[:12]}) .github/workflows есть")
    h.reset_wf()
    h.wf(sha, fail=True)
    merge_case("CI: проверок нет, gh api на head упал не на 404 — отказ", h.pre(cmd), False,
               "проверки GitHub не получены")
    h.reset_wf()
    h.wf(BASE, fail=True)
    merge_case("CI: head 404, gh api на base упал — отказ", h.pre(cmd), False, "проверки GitHub не получены")
    h.reset_wf()
    h.wf(sha, "не json")
    merge_case("CI: gh api workflows с кодом 0 и не-JSON — отказ, а не 404", h.pre(cmd), False,
               "проверки GitHub не получены")
    h.reset_wf()
    h.wf(BASE, "не json")
    merge_case("CI: head 404, base — код 0 и не-JSON — отказ", h.pre(cmd), False, "проверки GitHub не получены")
    h.reset_wf()
    h.ci([], baseRefOid=None)
    merge_case("CI: пусто и нет baseRefOid — отказ", h.pre(cmd), False, "коммит base PR (None) не получен")
    h.ci([], baseRefOid="main")
    merge_case("CI: пусто и baseRefOid не SHA — отказ", h.pre(cmd), False, "проверки GitHub не получены")
    h.ci(GREEN, baseRefOid=None)
    merge_case("CI: зелёные, baseRefOid не нужен — проходит", h.pre(cmd), True)
    # защиты: проверки после Д3, отказ с советом защит
    h.reset()
    kit = h.sha["agent-kit"]
    h.seed(rec("tests", "latark/agent-kit", None, kit, "dev-opus"), rec("accept", "latark/agent-kit", 7, kit))
    h.ci([AFFECTED, dict(TRACES, conclusion="FAILURE")], name="agent-kit")
    merge_case("CI: защиты, PR без ядра, красная проверка — отказ", h.pre(f"gh pr merge 7 --match-head-commit {kit}",
               pdir="projects/agent-kit"), False, "check-traces/traces красная")
    # сами проверки CI — напрямую, без шлюза
    mg = _load_merge_gate("merge_gate_ci")
    check("ci_verdict: зелёный", mg.ci_verdict(GREEN)[0] == "ok")
    check("ci_verdict: FAILURE — fail", mg.ci_verdict([dict(RUN_OK, conclusion="FAILURE")])[0] == "fail")
    check("ci_verdict: StatusContext FAILURE — fail", mg.ci_verdict([{"context": "c", "state": "FAILURE"}])[0] == "fail")
    check("ci_verdict: идёт — wait", mg.ci_verdict([dict(RUN_OK, status="QUEUED", conclusion=None)])[0] == "wait")
    check("ci_verdict: пусто — empty", mg.ci_verdict([])[0] == "empty")
    check("ci_verdict: None — fail", mg.ci_verdict(None)[0] == "fail")
    asked = []

    def answer(view, wf=None):
        """wf — {ref: True | False | None} ответов _has_workflows; по умолчанию 404 везде."""
        asked.clear()
        mg._has_workflows = lambda repo, ref: asked.append(ref) or (wf or {}).get(ref, False)
        why, notes = mg._ci_problem("latark/tg-read", 3, sha, dict({"baseRefOid": BASE}, **view))
        check("_ci_problem: возврат (текст, предупреждения) — без красной необязательной предупреждений нет",
              notes == (), notes)
        return why

    check("_ci_problem: зелёный — None", answer({"headRefOid": sha, "statusCheckRollup": GREEN}) is None)
    check("_ci_problem: зелёный — workflows не спрашивает", asked == [], asked)
    why = answer({"headRefOid": sha, "statusCheckRollup": [dict(RUN_OK, conclusion="FAILURE")]})
    check("_ci_problem: красный — отказ с именем", why and "check-traces" in why, why)
    why = answer({"headRefOid": sha, "statusCheckRollup": [dict(RUN_OK, status="PENDING")]})
    check("_ci_problem: идёт — отказ с командой ожидания", why and "ждать — командой вне хука" in why, why)
    why = answer({"headRefOid": sha})
    check("_ci_problem: нет rollup — «проверки GitHub не получены»", why and "проверки GitHub не получены" in why, why)
    empty = {"headRefOid": sha, "statusCheckRollup": []}
    check("_ci_problem: пусто, 404 на head и base — None", answer(empty) is None)
    check("_ci_problem: пусто — спрашивает head, затем base", asked == [sha, BASE], asked)
    why = answer(empty, {sha: True})
    check("_ci_problem: пусто, workflows на head — отказ", why and "ещё не встали" in why and "head PR" in why, why)
    check("_ci_problem: workflows на head — base не спрашивает", asked == [sha], asked)
    why = answer(empty, {BASE: True})
    check("_ci_problem: пусто, head 404, workflows на base — отказ", why and "ещё не встали" in why
          and "base PR" in why, why)
    why = answer(empty, {sha: None})
    check("_ci_problem: пусто, api на head упал — отказ", why and "не получены" in why, why)
    why = answer(empty, {BASE: None})
    check("_ci_problem: пусто, api на base упал — отказ", why and "не получены" in why and "base PR" in why, why)
    why = answer(dict(empty, baseRefOid=None))
    check("_ci_problem: пусто, нет baseRefOid — отказ без запросов", why and "не получены" in why and asked == [],
          (why, asked))
    why = answer({"headRefOid": OLD, "statusCheckRollup": GREEN})
    check("_ci_problem: чужой headRefOid — отказ", why and "другом коммите" in why, why)
    # _pr_view — один вызов gh pr view со всеми полями; сбой и не-объект — None
    calls = []
    mg._gh_json = lambda args: calls.append(args) or [{"headRefOid": sha}]
    check("_pr_view: объект ответа", mg._pr_view("latark/tg-read", 3) == {"headRefOid": sha})
    check("_pr_view: один вызов gh pr view с headRefOid,baseRefOid,baseRefName,changedFiles,statusCheckRollup и полями "
          "головы PR из форка (metis-0649)",
          calls == [["pr", "view", "3", "-R", "latark/tg-read", "--json",
                     "headRefOid,baseRefOid,baseRefName,changedFiles,statusCheckRollup,isCrossRepository,"
                     "headRepository,headRefName"]], calls)
    for got in (None, [], [["x"]], [{"a": 1}, {"b": 2}]):
        mg._gh_json = lambda args: got
        check(f"_pr_view: ответ {got!r} — None", mg._pr_view("latark/tg-read", 3) is None)
    # Д3 сверяет headRefOid сама, не полагаясь на _ci_problem (argus 0297a, круг 2, п. 3)
    mg._gh_json = lambda args: [{"filename": "README.md", "status": "modified"}]
    view = {"headRefOid": sha, "changedFiles": 1}
    check("_core_problem: тот же SHA, без ядра — None", mg._core_problem("latark/agent-kit", 7, sha, view) is None)
    for head in (OLD, None, 7):
        why = mg._core_problem("latark/agent-kit", 7, sha, dict(view, headRefOid=head))
        check(f"_core_problem: headRefOid {head!r} — отказ «на другом коммите»", why and "на другом коммите" in why,
              why)
    # _has_workflows — через поддельный gh: 404 → False, список → True, 502 → None
    mg = _load_merge_gate("merge_gate_wf")
    saved = {k: os.environ.get(k) for k in ("HOME", "PATH")}
    os.environ.update(HOME=h.root, PATH=h.j("bin") + os.pathsep + os.environ["PATH"])
    try:
        got = [mg._has_workflows("latark/tg-read", sha)]
        h.wf(sha, '[{"name": "ci.yml"}]')
        got.append(mg._has_workflows("latark/tg-read", sha))
        h.wf(sha, "не json")
        got.append(mg._has_workflows("latark/tg-read", sha))
        h.reset_wf()
        h.wf(sha, fail=True)
        got.append(mg._has_workflows("latark/tg-read", sha))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check("_has_workflows: 404 → False, список → True, код 0 и не-JSON → None, 502 → None",
          got == [False, True, None, None], got)


def _pr_runs(rollup):
    """Запуски для ci_verdict по записям CheckRun rollup: событие — поле "event" записи, по умолчанию pull_request."""
    return [{"workflowName": str(c.get("workflowName") or ""), "name": str(c.get("name") or ""),
             "status": str(c.get("status") or ""), "conclusion": str(c.get("conclusion") or ""),
             "event": c.get("event", "pull_request")} for c in rollup if isinstance(c, dict) and "context" not in c]


def t_ci_required(h):
    """metis-0633: обязательные проверки agent-kit по имени (REQUIRED_CHECKS) — только запуск Actions от
    pull_request на этом SHA и только SUCCESS: нет его (или только push) = «не встала», идёт = «дождись» с командой
    ожидания вне хука, красная или SKIPPED = отказ; дубль имени — худший итог; необязательная красная — пропуск с
    предупреждением systemMessage. Шаг 0: сохранённые ответы PR 223 и 225 (слиты при красном CI) — отказ."""
    kit, sha = "projects/agent-kit", h.sha["agent-kit"]
    h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"), rec("accept", "latark/agent-kit", 7, sha))
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    watch = "gh pr checks 7 -R latark/agent-kit --watch"
    full = dict(AFFECTED, name="full", conclusion="SKIPPED")
    merge_case("required: affected и traces зелёные, full пропущен — проходит", h.pre(cmd, pdir=kit), True)
    h.ci([TRACES, full], name="agent-kit")
    merge_case("required: нет tests/affected — отказ «не встали»", h.pre(cmd, pdir=kit), False,
               "обязательные проверки GitHub ещё не встали (засчитывается запуск от pull_request на этом "
               "коммите): tests/affected")
    merge_case("required: нет affected — в отказе команда ожидания вне хука", h.pre(cmd, pdir=kit), False, watch)
    h.ci([AFFECTED], name="agent-kit")
    merge_case("required: нет check-traces/traces — отказ", h.pre(cmd, pdir=kit), False,
               "коммите): check-traces/traces")
    h.reset_log()
    h.ci([], name="agent-kit")
    merge_case("required: rollup пуст — отказ «не встали», а не пропуск по 404 workflows", h.pre(cmd, pdir=kit), False,
               "коммите): tests/affected, check-traces/traces")
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("required: rollup пуст — .github/workflows не спрашивает", "contents/.github/workflows" not in log, log)
    for status in ("QUEUED", "IN_PROGRESS", "PENDING", "WAITING"):
        h.ci([dict(AFFECTED, status=status, conclusion=""), TRACES], name="agent-kit")
        merge_case(f"required: affected {status} — отказ «ещё идут» с командой ожидания", h.pre(cmd, pdir=kit), False,
                   f"проверки GitHub ещё идут: tests/affected на latark/agent-kit#7@{sha[:12]} — ждать")
    h.ci([dict(AFFECTED, status="IN_PROGRESS", conclusion=""), TRACES], name="agent-kit")
    merge_case("required: идёт — в отказе gh pr checks --watch", h.pre(cmd, pdir=kit), False, watch)
    red_pr = dict(TRACES, conclusion="FAILURE")
    for rollup, how in (([AFFECTED, red_pr, TRACES], "красная первой"), ([AFFECTED, TRACES, red_pr], "красная второй")):
        h.ci(rollup, name="agent-kit")
        merge_case(f"required: дубль traces от pull_request (красная и зелёная, {how}) — отказ по худшей",
                   h.pre(cmd, pdir=kit), False, "check-traces/traces красная: FAILURE")
    # событие: обязательную закрывает только запуск от pull_request (push проверяет ветку без слияния с base)
    h.ci([AFFECTED, dict(TRACES, event="push")], name="agent-kit")
    merge_case("required: traces только от push — отказ «не встали»", h.pre(cmd, pdir=kit), False,
               "не встали (засчитывается запуск от pull_request на этом коммите): check-traces/traces")
    h.ci([dict(AFFECTED, event="push"), dict(AFFECTED, event="workflow_dispatch"), TRACES], name="agent-kit")
    merge_case("required: affected от push и workflow_dispatch — отказ «не встали»", h.pre(cmd, pdir=kit), False,
               "этом коммите): tests/affected на")
    h.ci([AFFECTED, dict(TRACES, event="push", conclusion="FAILURE"), TRACES], name="agent-kit")
    merge_case("required: push-запуск traces красный, от pull_request зелёный — проходит", h.pre(cmd, pdir=kit), True)
    # итог: обязательную закрывает только SUCCESS — SKIPPED (job не запускался) и NEUTRAL — отказ
    for concl in ("SKIPPED", "NEUTRAL"):
        h.ci([dict(AFFECTED, conclusion=concl), TRACES], name="agent-kit")
        merge_case(f"required: affected {concl} — отказ", h.pre(cmd, pdir=kit), False,
                   f"проверка GitHub tests/affected не прошла: {concl}")
    h.ci([AFFECTED, TRACES, dict(AFFECTED, conclusion="SKIPPED", event="push")], name="agent-kit")
    merge_case("required: SKIPPED от push при зелёном от pull_request — проходит", h.pre(cmd, pdir=kit), True)
    # запуски берутся по SHA из --match-head-commit, два GET REST; сбой — отказ «не получены», а не пропуск
    h.ci(GREEN_KIT, name="agent-kit")
    h.reset_log()
    merge_case("required: зелёные — проходит", h.pre(cmd, pdir=kit), True)
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("required: запуски спрошены по SHA — actions/runs?head_sha и commits/SHA/check-runs",
          f"api repos/latark/agent-kit/actions/runs?head_sha={sha}&per_page=100" in log
          and f"api repos/latark/agent-kit/commits/{sha}/check-runs?per_page=100" in log, log)
    h.runs["agent-kit"] = "fail"
    h.ci(GREEN_KIT, name="agent-kit")
    merge_case("required: запуски Actions не получены — отказ", h.pre(cmd, pdir=kit), False,
               "проверки GitHub не получены на latark/agent-kit#7")
    merge_case("required: запуски не получены — «повтори позже», а не «почини»", h.pre(cmd, pdir=kit), False,
               "повтори слияние позже")
    h.runs["agent-kit"] = ('{"workflow_runs": [', "{}")
    h.ci(GREEN_KIT, name="agent-kit")
    merge_case("required: ответ запусков не JSON — отказ", h.pre(cmd, pdir=kit), False, "проверки GitHub не получены")
    runs, checks = rest_runs(h.view["agent-kit"])
    alien = [dict(c, check_suite={"id": 1}) for c in checks["check_runs"]]
    h.runs["agent-kit"] = (runs, dict(checks, check_runs=alien))
    h.ci(GREEN_KIT, name="agent-kit")
    merge_case("required: проверка не от запуска Actions (чужой check_suite) — не засчитана, отказ",
               h.pre(cmd, pdir=kit), False, "не встали")
    other = [dict(r, head_sha="f" * 40) for r in runs["workflow_runs"]]
    h.runs["agent-kit"] = (dict(runs, workflow_runs=other), checks)
    h.ci(GREEN_KIT, name="agent-kit")
    merge_case("required: запуски на другом SHA — не засчитаны, отказ", h.pre(cmd, pdir=kit), False, "не встали")
    h.runs["agent-kit"] = (dict(runs, total_count=101), checks)
    h.ci(GREEN_KIT, name="agent-kit")
    merge_case("required: запусков больше, чем получено (total_count > len) — отказ «неполные данные»",
               h.pre(cmd, pdir=kit), False, "неполные данные CI — запусков 101 и проверок 3, а получено 3 и 3")
    merge_case("required: неполные данные — «повтори позже», а не «почини»", h.pre(cmd, pdir=kit), False,
               "повтори слияние позже")
    h.runs["agent-kit"] = (runs, dict(checks, total_count=4))
    h.ci(GREEN_KIT, name="agent-kit")
    merge_case("required: проверок больше, чем получено — отказ «неполные данные»", h.pre(cmd, pdir=kit), False,
               "неполные данные CI — запусков 3 и проверок 4")
    h.runs.clear()
    h.ci([dict(AFFECTED, prs=(8,)), dict(TRACES, prs=(8,))], name="agent-kit")
    merge_case("required: зелёные запуски чужого PR #8 на том же SHA — не засчитаны, отказ", h.pre(cmd, pdir=kit),
               False, "не встали (засчитывается запуск от pull_request на этом коммите): tests/affected, check-traces")
    h.ci([dict(AFFECTED, prs=()), dict(TRACES, prs=())], name="agent-kit")
    merge_case("required: запуски без PR (pull_requests пуст) — не засчитаны, отказ", h.pre(cmd, pdir=kit), False,
               "не встали")
    h.ci([dict(AFFECTED, prs=(8, 7)), TRACES], name="agent-kit")
    merge_case("required: запуск с несколькими PR, среди них этот — засчитан", h.pre(cmd, pdir=kit), True)
    h.ci([AFFECTED, TRACES, dict(AFFECTED, prs=(8,), conclusion="FAILURE")], name="agent-kit")
    merge_case("required: красный запуск чужого PR на том же SHA — не мешает", h.pre(cmd, pdir=kit), True)
    h.ci([AFFECTED, TRACES, dict(TRACES, status="QUEUED", conclusion="")], name="agent-kit")
    merge_case("required: дубль traces (зелёная и идущая) — отказ «ещё идут»", h.pre(cmd, pdir=kit), False,
               "ещё идут: check-traces/traces")
    h.ci([dict(AFFECTED, conclusion="FAILURE"), dict(TRACES, conclusion="TIMED_OUT")], name="agent-kit")
    merge_case("required: две красные — обе в отказе", h.pre(cmd, pdir=kit), False,
               "tests/affected красная: FAILURE; проверка GitHub check-traces/traces красная: TIMED_OUT")
    h.ci([dict(AFFECTED, conclusion="FAILURE"), dict(TRACES, status="QUEUED", conclusion="")], name="agent-kit")
    merge_case("required: красная и идущая — отказ по красной", h.pre(cmd, pdir=kit), False, "affected красная: FAILURE")
    h.ci([dict(AFFECTED, conclusion="FAILURE"), TRACES], name="agent-kit")
    d, why = h.pre(cmd, pdir=kit)
    check("required: роль, красная — «новый коммит с новыми записями», без аварийного пути (Д2 argus #235)",
          d == "deny" and "почини и сделай новый коммит с новыми записями" in why and "аварийный путь" not in why, why)
    h.ci([{"__typename": "StatusContext", "context": "affected", "state": "SUCCESS"}, TRACES], name="agent-kit")
    merge_case("required: StatusContext «affected» обязательную не заменяет — отказ", h.pre(cmd, pdir=kit), False,
               "коммите): tests/affected")
    h.ci([dict(AFFECTED, workflowName="other"), TRACES], name="agent-kit")
    merge_case("required: job affected другого workflow не засчитывается — отказ", h.pre(cmd, pdir=kit), False,
               "коммите): tests/affected")
    h.ci([dict(AFFECTED, workflowName=None), TRACES], name="agent-kit")
    merge_case("required: affected без workflowName не засчитывается — отказ", h.pre(cmd, pdir=kit), False,
               "коммите): tests/affected")
    # ветка base: affected гоняется только на PR в main (tests.yml) — PR в другую ветку его не ждёт, traces — ждёт.
    # «Принять» — на той же base, что у PR (metis-0965)
    h.seed(rec("accept", "latark/agent-kit", 7, sha, base="feature-x"))
    h.ci([TRACES], name="agent-kit", baseRefName="feature-x")
    merge_case("required: PR не в main — affected не обязателен, traces зелёная — проходит", h.pre(cmd, pdir=kit), True)
    h.ci([], name="agent-kit", baseRefName="feature-x")
    merge_case("required: PR не в main, rollup пуст — отказ по traces", h.pre(cmd, pdir=kit), False,
               "коммите): check-traces/traces")
    h.ci([TRACES], name="agent-kit", baseRefName=None)
    merge_case("required: baseRefName нет — «принять» с base не сверить (metis-0965), отказ", h.pre(cmd, pdir=kit),
               False, "base PR сейчас неизвестна")
    # необязательная красная — пропуск и строка systemMessage; при отказе строки нет
    h.ci([AFFECTED, TRACES, dict(full, conclusion="FAILURE")], name="agent-kit", baseRefName="main")
    r = _hook_out(h, cmd, kit)
    check("required: необязательная tests/full красная — проходит", decision(r)[0] == "allow", r.stdout + r.stderr)
    msg = json.loads(r.stdout).get("systemMessage", "") if r.stdout.strip() else ""
    lint = dict(AFFECTED, workflowName="lint", name="lint", conclusion="FAILURE")
    h.ci([AFFECTED, TRACES, lint], name="agent-kit", baseRefName="main")
    merge_case("required: красный lint (нет ни в одном списке) — отказ (Д1 argus #235)", h.pre(cmd, pdir=kit), False,
               "lint/lint красная: FAILURE (её нет ни в обязательных")
    merge_case("без роли: красный lint — отказ", h.pre(cmd, role=None, pdir=kit), False, "lint/lint красная")
    check("required: необязательная красная — systemMessage с её именем",
          f"необязательная проверка GitHub tests/full красная: FAILURE на latark/agent-kit#7@{sha[:12]}" in msg,
          r.stdout)
    h.ci([AFFECTED, TRACES, full], name="agent-kit")
    r = _hook_out(h, cmd, kit)
    check("required: всё зелёное — пропуск без вывода", decision(r)[0] == "allow" and not r.stdout.strip(), r.stdout)
    h.ci([dict(AFFECTED, conclusion="FAILURE"), TRACES, dict(full, conclusion="FAILURE")], name="agent-kit")
    r = _hook_out(h, cmd, kit)
    check("required: отказ — systemMessage нет", decision(r)[0] == "deny" and "systemMessage" not in r.stdout, r.stdout)
    # шаг 0: сохранённые ответы gh pr view и REST запусков PR 223 и 225 (01.11 слиты при красном CI сессией без роли)
    for pr, want in ((223, "tests/affected красная: FAILURE; проверка GitHub check-traces/traces красная: FAILURE"),
                     (225, "tests/affected красная: FAILURE")):
        h.runs["agent-kit"] = _runs_on(_saved(pr, "runs"), sha, pr)
        h.ci(_saved(pr)["statusCheckRollup"], name="agent-kit", baseRefName="main")
        merge_case(f"required: сохранённые ответы PR {pr} — отказ", h.pre(cmd, pdir=kit), False, want)
    h.runs.clear()
    # сессия без роли (окно владельца, решение 01.11 «Да, проверять CI»): только CI, без записей тестов и argus
    owner = dict(role=None, pdir=kit)
    for pr, want in ((223, "tests/affected красная"), (225, "tests/affected красная: FAILURE")):
        h.runs["agent-kit"] = _runs_on(_saved(pr, "runs"), sha, pr)
        h.ci(_saved(pr)["statusCheckRollup"], name="agent-kit", baseRefName="main")
        merge_case(f"без роли: сохранённые ответы PR {pr} (слит так 01.11) — отказ", h.pre(cmd, **owner), False, want)
    h.runs.clear()
    merge_case("без роли: отказ называет правило сессии без роли", h.pre(cmd, **owner), False,
               "слияние из сессии без роли проверяет только CI")
    nine = [dict(AFFECTED, prs=(9,)), dict(TRACES, prs=(9,))]
    h.ci(nine, name="agent-kit")
    c9 = f"gh pr merge 9 --match-head-commit {sha} --merge"
    merge_case("без роли: PR 9 без записей тестов и argus, CI зелёный — проходит", h.pre(c9, **owner), True)
    merge_case("роль на том же PR 9 без записей — отказ (записи ей нужны)", h.pre(c9, pdir=kit), False)
    for c, how in (("gh pr merge 9 --merge", "без --match-head-commit (head PR)"),
                   ("gh pr merge --admin 9 --squash", "с --admin перед номером"),
                   ("gh pr merge 9 -R latark/agent-kit --merge", "с -R"),
                   (f"cd {h.j(kit)} && gh pr merge 9 -R latark/agent-kit", "cd и -R")):
        merge_case(f"без роли: {how}, CI зелёный — проходит", h.pre(c, **owner), True)
    merge_case("без роли: из папки tg-read с -R latark/agent-kit — судится agent-kit, зелёный — проходит",
               h.pre("gh pr merge 9 -R latark/agent-kit", role=None), True)
    h.ci([dict(nine[0], conclusion="FAILURE"), nine[1]], name="agent-kit")
    merge_case("без роли: красная обязательная — отказ", h.pre(c9, **owner), False, "tests/affected красная: FAILURE")
    merge_case("без роли: без --match-head-commit красная — отказ", h.pre("gh pr merge 9 --merge", **owner), False,
               "tests/affected красная")
    merge_case("без роли: из tg-read с -R latark/agent-kit красная — отказ",
               h.pre("gh pr merge 9 -R latark/agent-kit", role=None), False, "tests/affected красная")
    h.ci([nine[0], dict(nine[1], status="IN_PROGRESS", conclusion="")], name="agent-kit")
    merge_case("без роли: обязательная идёт — отказ с командой ожидания", h.pre(c9, **owner), False,
               "`gh pr checks 9 -R latark/agent-kit --watch`")
    h.ci(nine, name="agent-kit")
    merge_case("без роли: без номера PR — отказ", h.pre("gh pr merge --squash", **owner), False,
               "укажи один номер PR")
    merge_case("без роли: cd без -R — отказ", h.pre(f"cd {h.j(kit)} && gh pr merge 9", **owner), False,
               "с cd в команде укажи репозиторий")
    merge_case("без роли: --match-head-commit не SHA — отказ", h.pre("gh pr merge 9 --match-head-commit x", **owner),
               False, "один SHA из 40 знаков")
    merge_case("без роли: PR на другом коммите — отказ", h.pre(f"gh pr merge 9 --match-head-commit {'e' * 40}",
                                                                **owner), False, "PR сейчас на другом коммите")
    merge_case("без роли: подкоманда gh не вычисляется, в команде merge — отказ",
               h.pre("gh $SUB merge 9", **owner), False, "слово до подкоманды не вычислить")
    for c, how in ((f"GH_REPO=latark/tg-read {c9}", "GH_REPO= перед gh"), (f"env GH_HOST=h {c9}", "env GH_HOST="),
                   (f"export GH_REPO=x; {c9}", "export GH_REPO")):
        merge_case(f"без роли: {how} — отказ", h.pre(c, **owner), False, "без переменных GH_*")
    for var in ("GH_REPO", "GH_HOST", "GH_CONFIG_DIR"):
        merge_case(f"без роли: {var} в окружении — отказ", h.pre(c9, extra_env={var: "x"}, **owner), False,
                   "без переменных GH_*")
    merge_case("без роли: GH_TOKEN в окружении (не уводит) — проходит", h.pre(c9, extra_env={"GH_TOKEN": "x"}, **owner),
               True)
    h.reset_log()
    merge_case("без роли: не слияние (gh pr view) — можно", h.pre("gh pr view 9", **owner), True)
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("без роли: не слияние — gh не спрашивается", log == "", log)
    h.ci(nine, name="agent-kit", raw="не json")
    merge_case("без роли: gh pr view не ответил — отказ «повтори позже»", h.pre(c9, **owner), False,
               "не ответил — повтори позже")
    # Д2 и Д4' argus #235: в пути без роли записей не просят — в отказе аварийный путь (терминал владельца)
    h.ci([dict(nine[0], conclusion="FAILURE"), nine[1]], name="agent-kit")
    d, why = h.pre(c9, **owner)
    check("без роли: красная — без «новых записей», с аварийным путём в терминале владельца",
          d == "deny" and "почини и сделай новый коммит; аварийный путь — `gh pr merge` в собственном терминале "
          "владельца" in why and "с новыми записями" not in why, why)
    tg = h.sha["tg-read"]
    h.ci([], name="tg-read")
    h.reset_wf()
    h.wf(BASE, '[{"name": "check-traces.yml", "type": "file"}]')
    d, why = h.pre("gh pr merge 3 -R latark/tg-read", role=None)
    check("без роли: PR убирает workflows — аварийный путь вместо «сливает владелец»",
          d == "deny" and "PR, который убирает workflows, — аварийный путь" in why and "сливает владелец" not in why,
          why)
    h.reset_wf()
    # Д3 argus #235: что сливается — не понять (несколько номеров, несколько репозиториев, сбой gh-resolved) — отказ
    h.ci(nine, name="agent-kit")
    merge_case("без роли: два номера PR — отказ", h.pre("gh pr merge 9 10 --merge", **owner), False,
               "укажи один номер PR")
    merge_case("без роли: два разных -R — отказ", h.pre("gh pr merge 9 -R latark/agent-kit -R latark/tg-read",
                                                        **owner), False, "репозиторий не один")
    merge_case("без роли: -R дважды один и тот же — проходит",
               h.pre("gh pr merge 9 -R latark/agent-kit --repo latark/agent-kit", **owner), True)
    git(h.j(kit), "remote", "add", "up", "https://github.com/latark/tg-read")
    try:
        merge_case("без роли: у папки два remote разных репозиториев — отказ", h.pre("gh pr merge 9", **owner), False,
                   "репозиторий не один")
    finally:
        git(h.j(kit), "remote", "remove", "up")
    git(h.j(kit), "config", "remote.origin.gh-resolved", "")
    try:
        merge_case("без роли: gh-resolved не разобрать (сбой git config) — отказ", h.pre("gh pr merge 9", **owner), False,
                   "не понять репозиторий папки")
    finally:
        git(h.j(kit), "config", "--unset", "remote.origin.gh-resolved")
    merge_case("без роли: gh-resolved убран — снова проходит", h.pre("gh pr merge 9", **owner), True)
    # Д1' argus #235: невычисленное слово (переменная, xargs) — отказ с понятным текстом, а не исключение в хуке
    for c, how in (("gh pr merge $PR --merge", "номер — переменная"),
                   ("gh pr merge 9 --match-head-commit $SHA", "SHA — переменная"),
                   ("gh pr merge 9 -R $REPO", "-R — переменная"),
                   ("gh pr merge 9 $(echo --squash)", "флаг — $(…)")):
        d, why = h.pre(c, **owner)
        check(f"без роли: {how} — отказ «слово не вычислить», не сбой хука",
              d == "deny" and "слово команды не вычислить" in why and "check_roles" not in why, why)
    d, why = h.pre("echo 9 | xargs gh pr merge", **owner)
    check("без роли: xargs gh pr merge — отказ, не сбой хука", d == "deny" and "check_roles" not in why, why)
    # Д2' argus #235: два слияния в одной команде — судится каждое: зелёный 9 и красный 10 — отказ
    ten = [dict(AFFECTED, prs=(10,), conclusion="FAILURE"), dict(TRACES, prs=(10,))]
    h.ci(nine + ten, name="agent-kit")
    merge_case("без роли: одно слияние PR 9 при красном PR 10 рядом — проходит", h.pre(c9, **owner), True)
    merge_case("без роли: зелёный 9 && красный 10 — отказ по 10",
               h.pre(f"{c9} && gh pr merge 10 --match-head-commit {sha} --merge", **owner), False,
               "tests/affected красная: FAILURE на latark/agent-kit#10@")
    merge_case("без роли: красный 10 && зелёный 9 — отказ по 10",
               h.pre(f"gh pr merge 10 --match-head-commit {sha} --merge && {c9}", **owner), False,
               "tests/affected красная: FAILURE на latark/agent-kit#10@")
    h.ci(nine, name="agent-kit")
    # Д3 argus #235: ответ запусков из двух JSON подряд — не один ответ, отказ (а не первый документ)
    runs, checks = rest_runs(dict(h.view["agent-kit"], statusCheckRollup=GREEN_KIT))
    h.runs["agent-kit"] = (json.dumps(runs) + json.dumps(runs), checks)
    h.ci(GREEN_KIT, name="agent-kit")
    merge_case("required: ответ запусков из двух JSON подряд — отказ «не получены»", h.pre(cmd, pdir=kit), False,
               "проверки GitHub не получены")
    h.runs["agent-kit"] = (runs, json.dumps(checks) + "\n" + json.dumps(checks))
    h.ci(GREEN_KIT, name="agent-kit")
    merge_case("required: ответ check-runs из двух JSON подряд — отказ", h.pre(cmd, pdir=kit), False,
               "проверки GitHub не получены")
    h.runs.clear()
    # Д2 argus #235: CI пропустил с предупреждением, а отказ дала следующая проверка — systemMessage не печатается
    h.ci([AFFECTED, TRACES, dict(full, conclusion="FAILURE")], name="agent-kit")
    r = _hook_out(h, f"{cmd} && touch {h.records}", kit)
    check("required: красная необязательная, отказ дала pantheon-acl — только отказ, без systemMessage",
          decision(r)[0] == "deny" and "systemMessage" not in r.stdout and "pantheon-acl" in decision(r)[1], r.stdout)
    # другой репозиторий без записи в REQUIRED_CHECKS — как до 0633: обязательна каждая его проверка
    tg = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, tg, "dev-opus"), rec("accept", "latark/tg-read", 3, tg))
    tcmd = f"gh pr merge 3 --match-head-commit {tg}"
    h.ci([RUN_OK])
    merge_case("required: tg-read без записи — его check-traces зелёная, проходит", h.pre(tcmd), True)
    h.ci([RUN_OK, dict(full, conclusion="FAILURE")])
    merge_case("required: tg-read без записи — любая красная (tests/full) — отказ", h.pre(tcmd), False,
               "tests/full красная: FAILURE")
    h.ci([RUN_OK, dict(RUN_OK, conclusion="FAILURE")])
    merge_case("required: tg-read — дубль имени, зелёная и красная — отказ", h.pre(tcmd), False,
               "check-traces красная: FAILURE")


def t_ci_verdict_unit(h):
    """metis-0633: ci_verdict и required_checks напрямую — каждая ветка разбора; REQUIRED_CHECKS сверены с
    .github/workflows репозитория (имя workflow, job и ветка PR)."""
    mg = _load_merge_gate("merge_gate_ci_req")
    req = mg.required_checks("latark/agent-kit", "main")

    opt = mg.optional_checks("latark/agent-kit")

    def V(rollup, required, optional=()):
        return mg.ci_verdict(rollup, required, _pr_runs(rollup), optional)

    check("required_checks: agent-kit в main — affected и traces",
          req == (("tests", "affected"), ("check-traces", "traces")), req)
    check("required_checks: регистр репозитория и владелец не важны",
          mg.required_checks("Someone/Agent-Kit", "main") == req, mg.required_checks("Someone/Agent-Kit", "main"))
    check("required_checks: PR не в main — только traces",
          mg.required_checks("latark/agent-kit", "dev") == (("check-traces", "traces"),))
    check("required_checks: base не строка — все", mg.required_checks("latark/agent-kit", None) == req)
    check("required_checks: другой репозиторий — пусто", mg.required_checks("latark/tg-read", "main") == ())
    check("required_checks: repo None — пусто", mg.required_checks(None, "main") == ())
    v = V([AFFECTED, TRACES], req)
    check("ci_verdict: обязательные зелёные — ok без предупреждений", v == ("ok", "", []), v)
    v = V([TRACES], req)
    check("ci_verdict: нет обязательной — wait «не встали»", v[0] == "wait" and "коммите): tests/affected" in v[1], v)
    v = V([], req)
    check("ci_verdict: пусто при обязательных — wait, а не empty", v[0] == "wait" and "не встали" in v[1], v)
    v = V([dict(AFFECTED, status="IN_PROGRESS", conclusion=None), TRACES], req)
    check("ci_verdict: обязательная идёт — wait «ещё идут»", v[0] == "wait" and "ещё идут: tests/affected" in v[1], v)
    v = V([AFFECTED, TRACES, dict(TRACES, conclusion="FAILURE")], req)
    check("ci_verdict: дубль — худший (fail)", v[0] == "fail" and "check-traces/traces красная" in v[1], v)
    v = V([AFFECTED, dict(TRACES, conclusion="FAILURE"), TRACES], req)
    check("ci_verdict: дубль, зелёная после красной — всё равно fail", v[0] == "fail", v)
    v = V([AFFECTED, dict(TRACES, status="QUEUED", conclusion=None), TRACES], req)
    check("ci_verdict: дубль, идущая и зелёная — wait", v[0] == "wait", v)
    v = V([dict(AFFECTED, conclusion="FAILURE"), dict(TRACES, status="QUEUED", conclusion=None)], req)
    check("ci_verdict: красная важнее идущей", v[0] == "fail", v)
    v = V([dict(AFFECTED, conclusion="FAILURE")], req)
    check("ci_verdict: красная важнее отсутствующей", v[0] == "fail", v)
    v = V([AFFECTED, TRACES, dict(RUN_OK, conclusion="FAILURE")], req, [("", "check-traces")])
    check("ci_verdict: необязательная (в optional) красная — ok и предупреждение",
          v[0] == "ok" and v[2] == ["необязательная проверка GitHub check-traces красная: FAILURE"], v)
    # Д1 argus #235: красная проверка вне обязательных и вне optional (новый job lint на PR) — отказ, а не пропуск
    v = V([AFFECTED, TRACES, dict(RUN_OK, conclusion="FAILURE")], req)
    check("ci_verdict: красная вне обязательных и необязательных — fail с её именем",
          v[0] == "fail" and "проверка GitHub check-traces красная: FAILURE (её нет ни в обязательных" in v[1]
          and v[2] == [], v)
    lint = dict(AFFECTED, workflowName="lint", name="lint", conclusion="FAILURE")
    v = V([AFFECTED, TRACES, lint], req, opt)
    check("ci_verdict: красный lint (его нет в списках agent-kit) — fail",
          v[0] == "fail" and "lint/lint красная" in v[1], v)
    v = V([AFFECTED, TRACES, dict(AFFECTED, name="full", conclusion="FAILURE")], req, opt)
    check("ci_verdict: красная tests/full из OPTIONAL_CHECKS — ok и предупреждение",
          v[0] == "ok" and v[2] == ["необязательная проверка GitHub tests/full красная: FAILURE"], v)
    v = V([AFFECTED, TRACES, dict(lint, conclusion="SKIPPED"), dict(lint, name="x", status="QUEUED", conclusion=None)],
          req, opt)
    check("ci_verdict: проверка вне списков SKIPPED или идёт — ok (судится только красная)", v == ("ok", "", []), v)
    v = V([dict(AFFECTED, conclusion="FAILURE"), TRACES, lint], req, opt)
    check("ci_verdict: красные обязательная и вне списков — обе в тексте отказа",
          v[0] == "fail" and "tests/affected красная" in v[1] and "lint/lint красная" in v[1], v)
    # metis-1111: части matrix (affected-shard, full-shard) необязательны, их итог держат собирающие affected и full
    for name in ("full-shard (2/3)", "affected-shard (1/4)"):
        v = V([AFFECTED, TRACES, dict(AFFECTED, name=name, conclusion="FAILURE")], req, opt)
        check(f"ci_verdict: красная часть matrix tests/{name} — ok и предупреждение (её итог держит собирающий job)",
              v[0] == "ok" and v[2] == [f"необязательная проверка GitHub tests/{name} красная: FAILURE"], v)
    for name in ("full-shardx (1/3)", "full-shard 1/3", "full-shard (1/3", "lint (1/3)"):
        v = V([AFFECTED, TRACES, dict(AFFECTED, name=name, conclusion="FAILURE")], req, opt)
        check(f"ci_verdict: красная tests/{name} — не часть необязательного job, fail", v[0] == "fail" and v[2] == [], v)
    v = V([AFFECTED, TRACES, dict(AFFECTED, workflowName="other", name="full-shard (1/3)", conclusion="FAILURE")],
          req, opt)
    check("ci_verdict: часть с именем необязательного job в другом workflow — fail", v[0] == "fail", v)
    v = V([dict(AFFECTED, name="affected (1/4)"), TRACES], req, opt)
    check("ci_verdict: зелёная «affected (1/4)» обязательную affected не закрывает — wait",
          v[0] == "wait" and "tests/affected" in v[1], v)
    check("optional_checks: agent-kit — tests/full и части full-shard, affected-shard; регистр и владелец не важны, "
          "другой репозиторий — пусто",
          opt == (("tests", "full"), ("tests", "full-shard"), ("tests", "affected-shard"))
          and mg.optional_checks("X/Agent-Kit") == opt
          and mg.optional_checks("latark/tg-read") == () and mg.optional_checks(None) == (), opt)
    check("OPTIONAL_CHECKS: у каждой необязательной есть причина с номером задачи",
          all(re.search(r"\b[a-z]+-\d{4}\b", why) for rows in mg.OPTIONAL_CHECKS.values() for _, _, why in rows),
          mg.OPTIONAL_CHECKS)
    v = V([AFFECTED, TRACES, dict(RUN_OK, status="QUEUED", conclusion=None)], req)
    check("ci_verdict: необязательная идёт — ok без предупреждения", v == ("ok", "", []), v)
    v = V([dict(AFFECTED, conclusion="FAILURE"), TRACES, dict(RUN_OK, conclusion="FAILURE")], req,
          [("", "check-traces")])
    check("ci_verdict: при отказе предупреждение тоже отдаётся", v[0] == "fail" and len(v[2]) == 1, v)
    v = mg.ci_verdict([dict(RUN_OK, conclusion="FAILURE"), RUN_OK])
    check("ci_verdict: без обязательных — дубль зелёная после красной — fail", v[0] == "fail", v)
    v = mg.ci_verdict([RUN_OK, {"context": "ci/legacy", "state": "PENDING"}])
    check("ci_verdict: без обязательных — StatusContext PENDING — wait", v[0] == "wait" and "ci/legacy" in v[1], v)
    v = V([dict(AFFECTED, conclusion="SKIPPED"), dict(TRACES, conclusion="NEUTRAL")], req)
    check("ci_verdict: SKIPPED и NEUTRAL у обязательных — fail «не прошла», обе названы",
          v[0] == "fail" and "tests/affected не прошла: SKIPPED" in v[1]
          and "check-traces/traces не прошла: NEUTRAL" in v[1], v)
    v = mg.ci_verdict([dict(AFFECTED, conclusion="SKIPPED"), dict(TRACES, conclusion="NEUTRAL")])
    check("ci_verdict: без обязательных SKIPPED и NEUTRAL — ok (как до 0633)", v[0] == "ok", v)
    v = mg.ci_verdict([AFFECTED, TRACES], req)
    check("ci_verdict: обязательные есть, запусков нет (None) — fail «не получены»",
          v[0] == "fail" and v[1] == mg.CI_NONE, v)
    v = mg.ci_verdict([AFFECTED, TRACES], req, [])
    check("ci_verdict: запусков пусто — wait «не встали» по обеим",
          v[0] == "wait" and "tests/affected, check-traces/traces" in v[1], v)
    v = mg.ci_verdict([AFFECTED, TRACES], req, _pr_runs([AFFECTED, dict(TRACES, event="push")]))
    check("ci_verdict: traces только от push — wait «не встали»", v[0] == "wait" and "check-traces/traces" in v[1]
          and "tests/affected" not in v[1], v)
    v = mg.ci_verdict([AFFECTED, TRACES], req,
                      _pr_runs([AFFECTED, TRACES, dict(TRACES, event="push", conclusion="FAILURE")]))
    check("ci_verdict: красный push-запуск при зелёном от pull_request — ok", v == ("ok", "", []), v)
    v = mg.ci_verdict([AFFECTED, TRACES], req, _pr_runs([AFFECTED, TRACES]) + ["x", None])
    check("ci_verdict: мусор в запусках пропускается", v == ("ok", "", []), v)
    v = mg.ci_verdict([], req, _pr_runs([AFFECTED, TRACES]))
    check("ci_verdict: rollup пуст, запуски от pull_request зелёные — ok", v[0] == "ok", v)
    v = mg.ci_verdict([AFFECTED, TRACES, dict(TRACES, conclusion="FAILURE")], req, _pr_runs([AFFECTED, TRACES]))
    check("ci_verdict: красная обязательная в rollup (push), запуски от pull_request зелёные — ok без предупреждения",
          v == ("ok", "", []), v)
    v = mg.ci_verdict([AFFECTED, TRACES], (), _pr_runs([dict(AFFECTED, conclusion="FAILURE")]))
    check("ci_verdict: без обязательных запуски не читаются", v == ("ok", "", []), v)
    # ci_runs: связь check-runs с запусками Actions по check_suite_id и head_sha
    sha = "a" * 40
    mine = [{"number": 7}]
    wr = {"total_count": 5, "workflow_runs": [
        {"name": "tests", "event": "pull_request", "head_sha": sha, "check_suite_id": 5, "pull_requests": mine},
        {"name": "check-traces", "event": "push", "head_sha": sha, "check_suite_id": 6, "pull_requests": mine},
        {"name": "tests", "event": "pull_request", "head_sha": "b" * 40, "check_suite_id": 7, "pull_requests": mine},
        {"name": "tests", "event": "pull_request", "head_sha": sha, "check_suite_id": 8,
         "pull_requests": [{"number": 70}]},
        {"name": "tests", "event": "pull_request", "head_sha": sha, "check_suite_id": 9, "pull_requests": []}]}
    cr = {"total_count": 7, "check_runs": [
                         {"name": "affected", "status": "completed", "conclusion": "failure", "head_sha": sha,
                          "check_suite": {"id": 8}},
                         {"name": "affected", "status": "completed", "conclusion": "failure", "head_sha": sha,
                          "check_suite": {"id": 9}},{"name": "affected", "status": "completed", "conclusion": "success", "head_sha": sha,
                          "check_suite": {"id": 5}},
                         {"name": "traces", "status": "in_progress", "conclusion": None, "head_sha": sha,
                          "check_suite": {"id": 6}},
                         {"name": "affected", "status": "completed", "conclusion": "success", "head_sha": sha,
                          "check_suite": {"id": 99}},
                         {"name": "affected", "status": "completed", "conclusion": "success", "head_sha": sha,
                          "check_suite": {"id": 7}},
                         {"name": "affected", "status": "completed", "conclusion": "success", "head_sha": "c" * 40,
                          "check_suite": {"id": 5}}]}
    got = mg.ci_runs(wr, cr, sha, 7)
    check("ci_runs: запуск Actions этого PR на этом SHA — workflow, job, итог и событие (чужой PR и без PR — нет)",
          got == [{"workflowName": "tests", "name": "affected", "status": "completed", "conclusion": "success",
                   "event": "pull_request", "id": None, "annotations": None},
                  {"workflowName": "check-traces", "name": "traces", "status": "in_progress", "conclusion": "",
                   "event": "push", "id": None, "annotations": None}], got)
    got = mg.ci_runs(wr, cr, sha, "7")
    check("ci_runs: номер PR строкой — тот же итог", len(got or []) == 2, got)
    check("ci_runs: другой PR — пусто", mg.ci_runs(wr, cr, sha, 8) == [], mg.ci_runs(wr, cr, sha, 8))
    one = {"head_sha": sha, "check_suite_id": 5, "pull_requests": mine}
    for bad, how in ((None, "None"), ({}, "без workflow_runs"), ({"workflow_runs": []}, "без total_count"),
                     ({"total_count": 1, "workflow_runs": [{"name": "x"}]}, "без check_suite_id"),
                     ({"total_count": 1, "workflow_runs": [{"head_sha": sha, "check_suite_id": 5}]},
                      "без pull_requests"),
                     ({"total_count": 1, "workflow_runs": [dict(one, pull_requests=[7])]}, "PR не словарь"),
                     ({"total_count": "x", "workflow_runs": [one]}, "total_count не число"),
                     ({"total_count": 1, "workflow_runs": ["x"]}, "не словарь"),
                     ({"total_count": 1, "workflow_runs": {"a": 1}}, "словарь вместо списка")):
        check(f"ci_runs: ответ запусков {how} — None", mg.ci_runs(bad, cr, sha, 7) is None, mg.ci_runs(bad, cr, sha, 7))
    for bad, how in (({"total_count": 1, "check_runs": [{"name": "x", "head_sha": sha}]}, "без check_suite"),
                     ({"check_runs": []}, "без total_count"), ([], "список вместо словаря")):
        check(f"ci_runs: ответ check-runs {how} — None", mg.ci_runs(wr, bad, sha, 7) is None,
              mg.ci_runs(wr, bad, sha, 7))
    check("ci_runs: пустые ответы — пустой список",
          mg.ci_runs({"total_count": 0, "workflow_runs": []}, {"total_count": 0, "check_runs": []}, sha, 7) == [])
    for w, c, how in ((dict(wr, total_count=6), cr, "запусков"), (wr, dict(cr, total_count=8), "проверок"),
                      (dict(wr, total_count=200), dict(cr, total_count=150), "обоих")):
        got = mg.ci_runs(w, c, sha, 7)
        check(f"ci_runs: total_count {how} больше полученного — строка «неполные данные CI»",
              isinstance(got, str) and got.startswith(mg.CI_NONE) and "неполные данные CI" in got, got)
    got = mg.ci_runs(dict(wr, total_count=200), cr, sha, 7)
    v = mg.ci_verdict([AFFECTED, TRACES], req, got)
    check("ci_verdict: неполные данные при обязательных — fail с этим текстом", v == ("fail", got, []), v)
    v = mg.ci_verdict([AFFECTED, TRACES], (), got)
    check("ci_verdict: неполные данные без обязательных — не читаются", v == ("ok", "", []), v)
    check("ci_runs: total_count меньше полученного — разбор как обычно",
          len(mg.ci_runs(dict(wr, total_count=1), cr, sha, 7) or []) == 2)
    v = V([AFFECTED, TRACES, "x"], req)
    check("ci_verdict: не словарь — fail", v[0] == "fail" and "не разобрана" in v[1], v)
    for pr, red, events in ((223, ["tests/affected", "check-traces/traces"], ["pull_request", "pull_request", "push"]),
                            (225, ["tests/affected"], ["pull_request", "pull_request", "push"])):
        saved, runs = _saved(pr), _saved(pr, "runs")
        head = saved["headRefOid"]
        got = mg.ci_runs(runs["workflow_runs"], runs["check_runs"], head, pr)
        check(f"ci_runs: сохранённые запуски PR {pr} — 4 проверки, события как на GitHub",
              got is not None and len(got) == 4 and sorted({(g["workflowName"], g["event"]) for g in got}) ==
              sorted({("tests", "pull_request"), ("check-traces", "pull_request"), ("check-traces", "push")}), got)
        v = mg.ci_verdict(saved["statusCheckRollup"], mg.required_checks("latark/agent-kit", saved["baseRefName"]), got)
        check(f"ci_verdict: сохранённые ответы PR {pr} — fail по {', '.join(red)}",
              v[0] == "fail" and all(f"{n} красная" in v[1] for n in red) and v[1].count("красная") == len(red), v)
        check(f"ci_runs: запуски PR {pr} на чужом SHA — пусто", mg.ci_runs(runs["workflow_runs"], runs["check_runs"],
                                                                         "0" * 40, pr) == [])
        check(f"ci_runs: запуски PR {pr} для другого номера PR — пусто",
              mg.ci_runs(runs["workflow_runs"], runs["check_runs"], head, pr + 1) == [])
    # обязательные имена — настоящие job workflows репозитория (сверка с файлами .github/workflows)
    wf_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(GUARD)))), ".github",
                          "workflows")
    texts = {}
    for f in sorted(os.listdir(wf_dir)):
        if f.endswith((".yml", ".yaml")):
            text = open(os.path.join(wf_dir, f), encoding="utf-8").read()
            m = re.search(r"^name:\s*(\S+)\s*$", text, re.M)
            if m:
                texts[m.group(1)] = text
    for wf, job, base in mg.REQUIRED_CHECKS["agent-kit"]:
        text = texts.get(wf, "")
        jobs = text.split("\njobs:\n", 1)[1] if "\njobs:\n" in text else ""
        check(f"REQUIRED_CHECKS: workflow {wf} есть и в нём job {job}",
              re.search(rf"^  {re.escape(job)}:\s*$", jobs, re.M) is not None, sorted(texts))
        on = text.split("\njobs:\n", 1)[0]
        pr_on = re.search(r"^  pull_request:\s*\n((?:    .*\n)*)", on, re.M)
        if base is None:
            check(f"REQUIRED_CHECKS: {wf} идёт на любой PR (pull_request без branches)",
                  pr_on is not None and "branches" not in pr_on.group(1), on)
        else:
            check(f"REQUIRED_CHECKS: {wf} идёт на PR в {base}",
                  pr_on is not None and re.search(rf"branches:\s*\[\s*{re.escape(base)}\s*\]", pr_on.group(1)), on)
    # обратная сверка (Д1 argus #235): каждый job workflow, который идёт на pull_request, — в REQUIRED_CHECKS или в
    # OPTIONAL_CHECKS; новый job (lint) без строки в одном из списков краснеет здесь, а не проходит шлюз молча
    listed = {(w, j) for w, j, _ in mg.REQUIRED_CHECKS["agent-kit"] + mg.OPTIONAL_CHECKS["agent-kit"]}
    pr_jobs = set()
    for wf, text in texts.items():
        on, _, jobs = text.partition("\njobs:\n")
        if re.search(r"^  pull_request:", on, re.M) or re.search(r"^on:.*\bpull_request\b", on, re.M):
            pr_jobs |= {(wf, j) for j in re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", jobs, re.M)}
    check("workflows: каждый job на pull_request — в REQUIRED_CHECKS или OPTIONAL_CHECKS",
          pr_jobs and pr_jobs <= listed, sorted(pr_jobs - listed))
    check("OPTIONAL_CHECKS: каждая строка — настоящий job на pull_request",
          {(w, j) for w, j, _ in mg.OPTIONAL_CHECKS["agent-kit"]} <= pr_jobs, sorted(pr_jobs))


CASES = [t_ci, t_ci_required, t_ci_verdict_unit]


if __name__ == "__main__":
    sys.exit(main(CASES))
