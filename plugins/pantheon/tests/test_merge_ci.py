#!/usr/bin/env python3
"""Слияние по Touch ID, часть 3: проверки CI и их биллинг, версия, тик, состояние окружения (общая часть — _merge_common.py)."""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_common import *  # noqa: F403


def test_ci_matches_guard():
    """metis-0633, 0649, 0655: разбор проверок GitHub один — ci_verdict, ci_runs, ci_fork, ci_billing_ids, ci_billing,
    ci_job_unstarted, full_tests_record, required_checks, optional_checks, narrow_tests_record, narrow_map_path
    (metis-1050),
    pair_match, returned_lie, returned_lifts (поле «вернули», metis-0497), base_counts (metis-0965),
    REQUIRED_CHECKS, OPTIONAL_CHECKS (Д1 argus #235), CI_RUNS_API, CI_BILLING, CI_ANNOTATIONS_API, CI_JOBS_API,
    FULL_TESTS, MAP_HASH_RE, CI_OK, CI_WAIT, CI_NONE, delta_problem и DELTA_* (metis-0784) в merge.py
    дословно те же, что в шлюзе guard (merge_gate.py): сверка по AST, без запуска кода."""
    import ast

    def parts(path):
        tree = ast.parse(open(path, encoding="utf-8").read())
        got = {}
        for n in tree.body:
            if isinstance(n, ast.FunctionDef) and n.name in ("ci_verdict", "ci_runs", "ci_fork", "ci_billing_ids",
                                                             "ci_billing", "ci_job_unstarted", "full_tests_record",
                                                             "required_checks", "optional_checks",
                                                             "narrow_tests_record", "narrow_map_path",
                                                             "pair_match", "returned_lie",
                                                             "returned_lifts", "base_counts", "delta_problem"):
                got[n.name] = ast.dump(n)
            elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                    and n.targets[0].id in ("REQUIRED_CHECKS", "OPTIONAL_CHECKS", "CI_RUNS_API", "CI_BILLING",
                                            "CI_ANNOTATIONS_API", "CI_JOBS_API", "FULL_TESTS", "MAP_HASH_RE", "CI_OK",
                                            "CI_WAIT", "CI_NONE", "DELTA_MAX_LINES", "DELTA_DEPTH",
                                            "DELTA_GATE_FILES", "DELTA_RENAME"):
                got[n.targets[0].id] = ast.dump(n.value)
        return got

    mine, gate = parts(os.path.join(LIBDIR, "merge.py")), parts(os.path.join(GUARD_HOOKS, "merge_gate.py"))
    names = ("ci_verdict", "ci_runs", "ci_fork", "ci_billing_ids", "ci_billing", "ci_job_unstarted",
             "full_tests_record", "required_checks", "optional_checks", "narrow_tests_record", "narrow_map_path",
             "pair_match",
             "returned_lie", "returned_lifts", "base_counts", "REQUIRED_CHECKS",
             "OPTIONAL_CHECKS", "CI_RUNS_API", "CI_BILLING", "CI_ANNOTATIONS_API", "CI_JOBS_API", "FULL_TESTS",
             "MAP_HASH_RE", "CI_OK", "CI_WAIT", "CI_NONE", "delta_problem", "DELTA_MAX_LINES", "DELTA_DEPTH",
             "DELTA_GATE_FILES", "DELTA_RENAME")
    check("merge.py и merge_gate.py: все части разбора CI есть в обоих", all(k in mine and k in gate for k in names),
          (sorted(mine), sorted(gate)))
    for k in names:
        check(f"merge.py {k} == merge_gate.py {k}", mine.get(k) == gate.get(k) and k in mine, k)
    code = ("import sys, importlib.util\n"
            "s = importlib.util.spec_from_file_location('m', %r); m = importlib.util.module_from_spec(s); "
            "s.loader.exec_module(m)\n"
            "req = m.required_checks('o/agent-kit', 'main')\n"
            "ok = [{'workflowName': w, 'name': j, 'status': 'COMPLETED', 'conclusion': 'SUCCESS', "
            "'event': 'pull_request'} for w, j in req]\n"
            "print(m.ci_state([], req)[0], m.ci_state([], req, [])[0], m.ci_state([], req, ok)[0], "
            "m.ci_state([], req, [dict(ok[0], conclusion='SKIPPED'), ok[1]])[0], "
            "m.ci_state([], ())[0], m.ci_state([{'name': 'x', 'status': 'COMPLETED', 'conclusion': 'SUCCESS'}])[1])"
            % os.path.join(LIBDIR, "merge.py"))
    r = subprocess.run([PY311, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    check("ci_state: обязательные без запусков (None) — wait, запусков нет — wait, зелёные от pull_request — ok, "
          "SKIPPED — fail; пусто без обязательных — wait, зелёное — «CI ✓ (1)»",
          r.stdout.split() == ["wait", "wait", "ok", "fail", "wait", "CI", "✓", "(1)"], r.stdout + r.stderr)


def test_ci_state_no_workflows():
    """metis-1207: пустой rollup у репозитория без REQUIRED_CHECKS — ok, если ни на head PR, ни на base-ветке нет
    workflows, от которых встанут проверки: триггер pull_request(_target) или push без branches/branches-ignore. Есть
    такой workflow на head или на base — wait (как шлюз guard: PR, удаливший workflows, от CI не уходит, а PR,
    добавивший их, ждёт своих проверок). Сбой gh, не-JSON, нечитаемый файл, коммит head или ветка base не ответили
    200, 404 не точным ответом gh последней строкой — wait (сбой не пропускает)."""
    code = (
        "import sys, json, base64, importlib.util, subprocess\n"
        "s = importlib.util.spec_from_file_location('m', %r); m = importlib.util.module_from_spec(s); "
        "s.loader.exec_module(m)\n"
        "def wf(text): return {'encoding': 'base64', 'content': base64.b64encode(text.encode()).decode()}\n"
        "H = 'a' * 40\n"
        "B = {'repos/o/app/branches/main': {'name': 'main'}, 'repos/o/app/commits/' + H: {'sha': H}}\n"
        "def run_with(table, base='main', head=H):\n"
        "    def fake(argv, **kw):\n"
        "        key = argv[2]\n"
        "        if key not in table: return subprocess.CompletedProcess(argv, 1, '', 'gh: Not Found (HTTP 404)\\n')\n"
        "        v = table[key]\n"
        "        if v == 'FAIL': return subprocess.CompletedProcess(argv, 1, '', 'gh: HTTP 502')\n"
        "        if v == 'ODD404': return subprocess.CompletedProcess(argv, 1, '', 'error 404 in proxy (HTTP 502)')\n"
        "        if v == 'NOTLAST': return subprocess.CompletedProcess(argv, 1, '', "
        "'gh: Not Found (HTTP 404)\\nproxy: upstream reset, retry\\n')\n"
        "        if v == 'RAW': return subprocess.CompletedProcess(argv, 0, '<html>', '')\n"
        "        return subprocess.CompletedProcess(argv, 0, json.dumps(v), '')\n"
        "    m.subprocess.run = fake\n"
        "    return m.ci_state([], (), None, (), 'o/app', base, head)[0]\n"
        "D = 'repos/o/app/contents/.github/workflows'\n"
        "L = [{'name': 'lint.yml'}, {'name': 'README.md'}]\n"
        "def on_base(text): return {**B, D + '?ref=main': L, D + '/lint.yml?ref=main': wf(text)}\n"
        "def on_head(text): return {**B, D + '?ref=' + H: L, D + '/lint.yml?ref=' + H: wf(text)}\n"
        "out = [run_with(dict(B)),\n"
        "  run_with(on_base('on:\\n  push:\\n    branches: [main]\\n')),\n"
        "  run_with(on_base('on:\\n  pull_request:\\n')),\n"
        "  run_with(on_base('# on: pull_request\\non:\\n  push:\\n    branches-ignore: [x]\\n')),\n"
        "  run_with({**B, D + '?ref=main': 'FAIL'}), run_with({**B, D + '?ref=main': 'RAW'}),\n"
        "  run_with({**B, D + '?ref=main': L, D + '/lint.yml?ref=main': 'FAIL'}),\n"
        "  run_with({}), run_with({**B, D + '?ref=main': 'ODD404'}), run_with({**B, D + '?ref=main': 'NOTLAST'}),\n"
        "  run_with(dict(B), base=None), run_with(dict(B), head=None), run_with(dict(B), head='abc'),\n"
        "  run_with(on_head('on:\\n  pull_request_target:\\n')),\n"
        "  run_with({'repos/o/app/branches/main': {'name': 'main'}}),\n"
        "  run_with(on_base('on: push\\n')), run_with(on_base('on: [push, workflow_dispatch]\\n')),\n"
        "  run_with(on_base('on:\\n  push:\\n    tags: [v*]\\njobs:\\n  a:\\n    branches: x\\n')),\n"
        "  run_with(on_base('on: {push: {branches: [main]}}\\n')), run_with(on_head('on:\\n  push:\\n'))]\n"
        "m.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(OSError('нет gh'))\n"
        "out.append(m.ci_state([], (), None, (), 'o/app', 'main', H)[0])\n"
        "out.append(m.ci_state([], ())[0])\n"
        "print(*out)\n" % os.path.join(LIBDIR, "merge.py"))
    r = subprocess.run([PY311, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    want = {"нет каталога workflows ни на head, ни на base": "ok", "на base push только в main": "ok",
            "на base pull_request": "wait", "триггер в комментарии, push с branches-ignore": "ok",
            "сбой gh на каталоге": "wait", "не-JSON": "wait", "сбой чтения файла": "wait",
            "коммит и ветка не ответили": "wait", "404 не точным ответом": "wait",
            "(HTTP 404) не последней строкой stderr": "wait", "base нет": "wait", "head нет": "wait",
            "head не SHA": "wait", "на head pull_request_target, на base нет": "wait",
            "коммит head не ответил 200": "wait", "на base on: push": "wait", "на base on: [push, …]": "wait",
            "на base push только с tags (branches у job не в счёт)": "wait", "на base {push: {branches}}": "ok",
            "на head push без branches": "wait", "gh не найден": "wait", "без repo/base/head — как раньше": "wait"}
    got = r.stdout.split()
    check("ci_state без CI: " + "; ".join(f"{k} — {v}" for k, v in want.items()),
          got == list(want.values()), [(k, v, g) for (k, v), g in zip(want.items(), got) if v != g] or r.stdout + r.stderr)


def test_gate_no_ci_window():
    """metis-1207, Б1 argus #475: у репозитория без CI вердикт шлюза — «CI нет у репозитория», и в окне Touch ID тоже,
    а не «CI ✓» (billing_verdict не подменяет NO_CI). gate передаёт ci_state repo, base и head: без них вердикт был бы
    «проверок GitHub пока нет» — wait."""
    code = (
        "import sys, json, importlib.util, subprocess, types\n"
        "s = importlib.util.spec_from_file_location('m', %r); m = importlib.util.module_from_spec(s); "
        "s.loader.exec_module(m)\n"
        "H = 'a' * 40\n"
        "ok = {'repos/o/app/branches/main', 'repos/o/app/commits/' + H}\n"
        "seen = []\n"
        "def fake(argv, **kw):\n"
        "    seen.append(argv[2])\n"
        "    if argv[2] in ok: return subprocess.CompletedProcess(argv, 0, '{}', '')\n"
        "    return subprocess.CompletedProcess(argv, 1, '', 'gh: Not Found (HTTP 404)\\n')\n"
        "m.subprocess.run = fake\n"
        "def acc(sid): return {'kind': 'accept', 'pr': 7, 'sha': H, 'base': 'main',\n"
        "                      'by': {'agent_type': 'argus', 'session_id': sid, 'agent_id': sid}}\n"
        "recs = [{'kind': 'tests', 'sha': H}, acc('s1'), acc('s2')]\n"
        "m.P = types.SimpleNamespace(review_records=lambda repo: recs, review_accept_counts=lambda r: True)\n"
        "m.code_facts = lambda *a: (set(), set(), [])\n"
        "view = {'headRefOid': H, 'state': 'OPEN', 'isDraft': False, 'baseRefName': 'main', "
        "'statusCheckRollup': [], 'title': 'T'}\n"
        "state, why = m.gate('o/app', 7, H, view)\n"
        "req = {'repo': 'o/app', 'pr': 7, 'sha': H}\n"
        "print(json.dumps({'state': state, 'why': why, 'win': m.window_text(req, view, why, ['README.md']),\n"
        "                  'batch': m.batch_window_text([req], [view], [why], [['README.md']]),\n"
        "                  'head': any('ref=' + H in k for k in seen)}, ensure_ascii=False))\n"
        % os.path.join(LIBDIR, "merge.py"))
    r = subprocess.run([PY311, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = {}
    check("gate без CI → ok «CI нет у репозитория», не «CI ✓»",
          got.get("state") == "ok" and "CI нет у репозитория" in got.get("why", "")
          and "CI ✓" not in got.get("why", ""), r.stdout + r.stderr)
    check("окно Touch ID пишет «CI нет у репозитория», не «CI ✓»",
          "CI нет у репозитория" in got.get("win", "") and "CI ✓" not in got.get("win", ""), got)
    check("окно пачки — тоже «CI нет у репозитория»",
          "CI нет у репозитория" in got.get("batch", "") and "CI ✓" not in got.get("batch", ""), got)
    check("gate смотрит workflows и на head PR", got.get("head") is True, got)


def test_ci_billing():
    """metis-0655: CI не запускался из-за лимита минут или оплаты (FAILURE с аннотацией лимита у красных
    обязательных) — проход засчитывает вместо CI запись тестов шлюза на SHA (она нужна и так) и сливает; окно
    говорит об этом. Обычная красная, аннотация не та, сбой запроса аннотаций — заявка снята, как раньше."""
    blocked = [dict(c, conclusion="FAILURE", notes=[billing_note()], job=JOB_IDLE) for c in ci("SUCCESS", "SUCCESS")]
    b = Box()
    b.request()
    b.view(SHA, checks=blocked)
    b.run()
    w = b.windows()
    check("лимит минут, запись тестов на SHA → окно и слияние",
          len(w) == 1 and len(b.merges()) == 1 and "CI не запускался (лимит минут GitHub Actions) — засчитан местный "
          f"прогон тестов на {SHA[:12]}" in w[0][0], (w, b.outs[-1]))
    calls = [json.loads(x)["argv"] for x in open(os.path.join(b.rec, "gh-argv.jsonl"))]
    check("аннотации спрошены по id каждой красной обязательной",
          [f"repos/{REPO}/check-runs/5000/annotations?per_page=100"] in [a[1:] for a in calls]
          and [f"repos/{REPO}/check-runs/5001/annotations?per_page=100"] in [a[1:] for a in calls], calls)
    check("данные job спрошены по id каждой красной обязательной",
          [f"repos/{REPO}/actions/jobs/5000"] in [a[1:] for a in calls]
          and [f"repos/{REPO}/actions/jobs/5001"] in [a[1:] for a in calls], calls)
    b = Box()
    b.request()
    b.view(SHA, checks=[ci("SUCCESS", "SUCCESS")[0], blocked[1]])
    b.run()
    check("лимит только у traces, affected зелёная → окно и слияние", len(b.merges()) == 1, b.outs[-1])
    for name, checks, setup in (
            ("обычная красная (Process completed with exit code 1.)",
             [dict(blocked[0], notes=[billing_note("Process completed with exit code 1.")]), blocked[1]], None),
            ("аннотация лимита уровня warning", [dict(blocked[0], notes=[billing_note(level="warning")]), blocked[1]],
             None),
            ("красная без аннотаций", [dict(blocked[0], notes=[]), blocked[1]], None),
            ("TIMED_OUT с аннотацией лимита", [dict(blocked[0], conclusion="TIMED_OUT"), blocked[1]], None),
            ("аннотацию лимита напечатал сам job (раннер и шаги есть)",
             [{k: v for k, v in blocked[0].items() if k != "job"}, blocked[1]], None)):
        b = Box()
        b.request()
        b.view(SHA, checks=checks)
        if setup:
            b.set(setup, "")
        b.run()
        check(f"{name} → окна нет, заявка снята с тревогой",
              not b.windows() and not b.merges() and b.req() is None and "красная" in b.alerts(), b.alerts())
    b = Box()
    b.request()
    b.view(SHA, checks=[blocked[0], dict(blocked[1], status="IN_PROGRESS", conclusion="")])
    b.run()
    check("лимит у affected, traces идёт → не сливает", not b.windows() and not b.merges(), b.outs[-1])
    b = Box()
    b.records = []
    b.add("accept", sid="s1", aid="a1")
    b.add("accept", sid="s2", aid="a2")
    b.add("tests", sha=SHA, who="")
    b.request()                       # заявка принята на записи этого SHA, к проходу запись тестов только на SHA2
    b.records = [r for r in b.records if r["kind"] != "tests"]
    b.add("tests", sha=SHA2, who="")
    b.view(SHA, checks=blocked)
    b.run()
    check("лимит, запись тестов только на другом SHA → окна нет, заявка снята",
          not b.windows() and not b.merges() and "нет записи тестов шлюза" in b.alerts(), b.alerts())
    for name, cmd in (("другая команда", "pantheon review test -- true"),
                      ("полный набор && ещё", FULL_TESTS_CMD + " && true")):
        b = Box()
        b.records = []
        b.add("accept", sid="s1", aid="a1")
        b.add("accept", sid="s2", aid="a2")
        b.add("tests", sha=SHA, who="", cmd=cmd)
        b.request()
        b.view(SHA, checks=blocked)
        b.run()
        check(f"лимит, запись тестов на SHA — {name}, не FULL_TESTS → окна нет, заявка снята",
              not b.windows() and not b.merges() and "записи полного набора тестов (FULL_TESTS)" in b.alerts(),
              b.alerts())
    b = Box()                         # Б1 argus #248: запись тестов на SHA есть (узкая), полный набор — только на SHA2
    b.records = []
    b.add("accept", sid="s1", aid="a1")
    b.add("accept", sid="s2", aid="a2")
    b.add("tests", sha=SHA, who="", cmd="pantheon review test -- python3.14 -I plugins/guard/tests/test_guard.py")
    b.add("tests", sha=SHA2, who="")
    b.request()
    b.view(SHA, checks=blocked)
    b.run()
    check("лимит, на SHA узкая запись tests, полный набор только на SHA2 → окна нет, заявка снята",
          not b.windows() and not b.merges() and b.req() is None
          and "записи полного набора тестов (FULL_TESTS)" in b.alerts(), b.alerts())
    b = Box()
    b.records = []
    b.add("accept", sid="s1", aid="a1")
    b.add("accept", sid="s2", aid="a2")
    b.add("tests", sha=SHA, who="", cmd=FULL_TESTS_CMD.split(" -- ", 1)[1].replace("heavy ", "")
          + "  # .pantheon-verify ветки (HEAD)")
    b.request()
    b.view(SHA, checks=blocked)
    b.run()
    check("лимит, запись прохода outside test (без heavy, с хвостом) → окно и слияние", len(b.merges()) == 1,
          b.outs[-1])


def test_ci_billing_gh_fail():
    """metis-0813: сбой gh на аннотациях или job (TLS из окна) — признак лимита не проверить: ждёт, а не снята."""
    blocked = [dict(c, conclusion="FAILURE", notes=[billing_note()], job=JOB_IDLE) for c in ci("SUCCESS", "SUCCESS")]
    for name, setup in (("аннотации не получены", "gh-notes-fail"), ("данные job не получены", "gh-jobs-fail")):
        b = Box()
        b.request()
        b.view(SHA, checks=blocked)
        b.set(setup, "")
        b.run()
        check(f"лимит, {name} (сбой gh) → окна нет, заявка ждёт без тревоги",
              not b.windows() and not b.merges() and b.req() is not None and not b.alerts()
              and "ждёт: аннотации CI не получены (сбой gh)" in b.outs[-1], (b.outs[-1], b.alerts()))
        os.remove(os.path.join(b.rec, setup))
        b.run(t=T0 + 60)
        check(f"лимит, {name}, сбой прошёл → следующий проход: окно и слияние",
              len(b.windows()) == 1 and len(b.merges()) == 1, b.outs[-1])
    b = Box()
    b.request()
    b.view(SHA, checks=[dict(blocked[0], notes=[billing_note("Process completed with exit code 1.")]), blocked[1]])
    b.set("gh-jobs-fail", "")
    b.run()
    check("обычная красная, данные job не получены → тоже ждёт (признак не проверить), заявка цела",
          not b.windows() and b.req() is not None and "аннотации CI не получены" in b.outs[-1], b.outs[-1])


def test_ci_fork_billing():
    """Долг argus #248: лимит минут у PR из форка. Запуски форка (pull_requests пуст) засчитываются по репозиторию и
    ветке head и на запасном пути: запись полного набора на SHA — окно и слияние; только узкая запись — заявка снята.
    Лимит у чужого форка, чужой ветки, у не-форка без номера PR — ждёт; nameWithOwner не получен — заявка снята."""
    def fork_blocked(repo="Ext/agent-kit", branch="feat"):
        return [dict(c, conclusion="FAILURE", notes=[billing_note()], job=JOB_IDLE, prs=[], head_repo=repo,
                     head_branch=branch) for c in ci("SUCCESS", "SUCCESS")]

    b = Box()
    b.request()
    b.view(SHA, checks=fork_blocked(), head=FORK)
    b.run()
    w = b.windows()
    check("форк + лимит, запись полного набора → окно и слияние",
          len(w) == 1 and len(b.merges()) == 1 and "засчитан местный прогон" in w[0][0], (w, b.outs[-1]))
    b = Box()
    b.records = []
    b.add("accept", sid="s1", aid="a1")
    b.add("accept", sid="s2", aid="a2")
    b.add("tests", sha=SHA, who="", cmd="pantheon review test -- python3.14 -I plugins/guard/tests/test_guard.py")
    b.request()
    b.view(SHA, checks=fork_blocked(), head=FORK)
    b.run()
    check("форк + лимит, только узкая запись tests → окна нет, заявка снята",
          not b.windows() and not b.merges() and b.req() is None
          and "записи полного набора тестов (FULL_TESTS)" in b.alerts(), b.alerts())
    for how, checks, head in (("чужого форка", fork_blocked(repo="evil/agent-kit"), FORK),
                              ("чужой ветки форка", fork_blocked(branch="x"), FORK),
                              ("не форка, запуски без номера PR", fork_blocked(), dict(FORK, isCrossRepository=False))):
        b = Box()
        b.request()
        b.view(SHA, checks=checks, head=head)
        b.run()
        check(f"лимит у {how}, запись есть → окна нет, ждёт", not b.windows() and not b.merges()
              and b.req() is not None, b.outs[-1])
    b = Box()
    b.request()
    b.view(SHA, checks=fork_blocked(), head=dict(FORK, headRepository={"id": "R_x"}))
    b.run()
    check("форк без nameWithOwner + лимит → окна нет, заявка снята с тревогой «из форка»",
          not b.windows() and not b.merges() and b.req() is None and "из форка" in b.alerts(), b.alerts())


def test_ci_optional_notes():
    """С1 argus #248: красная необязательная (tests/full из OPTIONAL_CHECKS) не теряется — текст пропуска в окне
    называет её и на обычном пути с зелёным CI, и на запасном пути при лимите минут."""
    full = dict(ci("SUCCESS")[0], name="full", conclusion="FAILURE")
    blocked = [dict(c, conclusion="FAILURE", notes=[billing_note()], job=JOB_IDLE) for c in ci("SUCCESS", "SUCCESS")]
    for how, checks, mark in (("зелёный CI", ci("SUCCESS", "SUCCESS") + [full], "CI ✓"),
                              ("лимит минут, запись полного набора", blocked + [full], "засчитан местный прогон")):
        b = Box()
        b.request()
        b.view(SHA, checks=checks)
        b.run()
        w = b.windows()
        check(f"{how} + красная tests/full → окно и слияние, в тексте окна и итог, и tests/full",
              len(w) == 1 and len(b.merges()) == 1 and mark in w[0][0]
              and "необязательная проверка GitHub tests/full красная: FAILURE" in w[0][0], (w, b.outs[-1]))


def test_version_matches_guard():
    """metis-0512: version_problem прохода и _version_problem шлюза guard отвечают одинаково на общих случаях."""
    code = ("import sys, json, importlib.util; sys.path.insert(0, %r); import merge_gate as g\n"
            "s = importlib.util.spec_from_file_location('m', %r); m = importlib.util.module_from_spec(s); "
            "s.loader.exec_module(m)\ncases = json.loads(sys.stdin.read())\n"
            "print(json.dumps([[bool(g._version_problem(f)), bool(m.version_problem(f))] for f, _w in cases]))"
            % (GUARD_HOOKS, os.path.join(LIBDIR, "merge.py")))
    r = subprocess.run([sys.executable, "-I", "-c", code], input=json.dumps(VERSION_CASES), capture_output=True,
                       text=True, timeout=60)
    try:
        got = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        got = []
    check("version: случаев столько же", len(got) == len(VERSION_CASES), r.stdout + r.stderr)
    for i, ((files, want), pair) in enumerate(zip(VERSION_CASES, got)):
        check(f"version {i}: {files[0]['filename']} {files[0].get('status')} — отказ {want} у guard и прохода",
              pair == [want, want], (pair, files))


def test_version_pr_dropped():
    """metis-0512: PR ядра правит version в plugin.json — окна Touch ID нет, слияния нет, заявка снята."""
    for files in (VERSION_CASES[0][0], VERSION_CASES[8][0]):
        b = Box()
        b.view(SHA, files=["README.md", CORE_FILE] + files)
        b.request()
        b.set("touchid-rc", 0)
        b.run()
        check(f"version: {files[0]['filename']} — окна нет, слияния и согласия нет, заявка снята",
              not b.windows() and not b.merges() and not b.approve_lines() and b.req() is None
              and "номер версии" in b.outs[-1], b.outs[-1])
    b = Box()
    b.view(SHA, files=["README.md", CORE_FILE] + VERSION_CASES[1][0])
    b.request()
    b.set("touchid-rc", 1)
    b.run()
    check("version: plugin.json без правки version — окно есть", len(b.windows()) == 1, b.outs[-1])


def test_approve_expires():
    """argus-b 3: строка согласия в силе сутки; старая, из будущего и без разборного времени — нет."""
    b = Box()
    b.request()
    b.run()
    check("строка согласия записана", len(b.approve_lines()) == 1, b.approve_lines())
    for dt, want in ((0, True), (23 * 3600, True), (24 * 3600 + 60, False), (-3600, False)):
        ok, out = guard_approves(b, REPO, PR, SHA, now=T0 + dt)
        check(f"шлюз guard: строка через {dt // 60} мин — {'в силе' if want else 'не в силе'}", ok == want, out)
    d = os.path.join(b.state, "owner-log", "merge-approve.log")
    for line in (f"2020-01-01T00:00:00+03:00 merge-approve {REPO}#{PR} {SHA}",
                 f"x merge-approve {REPO}#{PR} {SHA}",
                 f"2026-10-14T00:00:00 merge-approve {REPO}#{PR} {SHA}"):
        with open(d, "w") as fh:
            fh.write(line + "\n")
        ok, out = guard_approves(b, REPO, PR, SHA)
        check(f"шлюз guard: строка «{line[:25]}…» — не в силе", not ok, out)


def test_status_cancel_and_bad_files():
    b = Box()
    b.request()
    r = b.cli(["merge", "status"])
    check("status: заявка видна", f"{REPO}#{PR}" in r.stdout and SHA[:12] in r.stdout, r.stdout)
    r = b.request()
    check("повтор заявки на тот же SHA — одна заявка", r.returncode == 0 and "уже стоит" in r.stdout, r.stdout)
    r = b.cli(["merge", "cancel", str(PR), "-R", REPO])
    check("cancel: снята", r.returncode == 0 and b.req() is None, r.stdout + r.stderr)
    r = b.cli(["merge", "status"])
    check("status: заявок нет", "заявок нет" in r.stdout, r.stdout)
    b.request()
    with open(b.req_path(), "w") as fh:
        fh.write('{"repo": "latark/agent-kit", "pr": 8, "sha": "%s", "created": %d}' % (SHA, T0))
    b.run()
    check("битая заявка (номер не совпадает с именем файла) — удалена, окна нет",
          not b.windows() and not os.path.exists(b.req_path()), b.outs[-1])
    os.makedirs(os.path.join(b.state, "owner-log"), exist_ok=True)
    os.rmdir(os.path.join(b.state, "owner-log"))
    target = os.path.join(b.tmp, "elsewhere")
    os.makedirs(target)
    os.symlink(target, os.path.join(b.state, "owner-log"))
    b.request()
    b.run()
    check("owner-log — ссылка → согласие не пишется, слияния нет, заявка снята с тревогой (окно не повторяется)",
          not b.merges() and not os.listdir(target) and b.req() is None and "сбой прохода" in b.alerts(),
          (b.outs[-1], os.listdir(target)))
    b.run()
    check("owner-log — ссылка: второго окна нет", len(b.windows()) == 1, b.windows())


def test_tick_kick():
    def kick(b):
        code = "import sys; sys.path.insert(0, %r); import pantheon as p; p.merge_kick()" % LIBDIR
        r = subprocess.run([PY311, "-I", "-c", code], env=b.env(T0, {"PANTHEON_DRYRUN": "1"}), capture_output=True,
                           text=True, timeout=60)
        p = os.path.join(b.state, "dryrun.log")
        return r, open(p).read() if os.path.exists(p) else ""
    b = Box()
    r, log = kick(b)
    check("тик: заявок нет — проход не запускается", r.returncode == 0 and "merge-run" not in log, r.stderr + log)
    b.request()
    r, log = kick(b)
    check("тик: есть заявка — проход запускается", r.returncode == 0 and "merge-run" in log, r.stderr + log)


def test_parse_command_not_tick():
    code = ("import sys; sys.path.insert(0, %r); import pantheon as p; "
            "print(p.parse_command('pantheon merge run') is None)" % LIBDIR)
    b = Box()
    r = subprocess.run([PY311, "-I", "-c", code], env=b.env(T0), capture_output=True, text=True, timeout=60)
    check("pantheon merge run — не подкоманда тика по расписанию (её запускает только сам тик)",
          r.stdout.strip() == "True", r.stdout + r.stderr)



# --- окружение прохода из launchd (metis-0303, review-79d-argus проба A) -----------------------------------------------
# Окружение тика и щелчка задаёт launchd, а его меняет любой процесс владельца (launchctl setenv). Проход берёт
# окружение с нуля: HOME (это домашняя папка учётной записи) и постоянный PATH; STATE и папка Пантеона — от HOME.

def test_env_state_probe_a():
    """Проба A: чужой STATE с поддельным помощником «палец есть», записями шлюза и заявкой — слияния нет."""
    b = Box()   # своя очередь пуста
    evil = os.path.join(b.tmp, "evil-state")
    os.makedirs(os.path.join(evil, "bin"), mode=0o700)
    script(os.path.join(evil, "bin", "pantheon-touchid"), EVIL)
    with open(os.path.join(evil, "bin", "pantheon-touchid.sha256"), "w") as fh:
        fh.write(hashlib.sha256(open(os.path.join(LIBDIR, "touchid.swift"), "rb").read()).hexdigest() + "\n")
    _shutil.copytree(os.path.join(b.state, "merge-gate"), os.path.join(evil, "merge-gate"))
    os.makedirs(os.path.join(evil, "merge-queue"), mode=0o700)
    with open(os.path.join(evil, "merge-queue", "latark__agent-kit__7.json"), "w") as fh:
        json.dump({"repo": REPO, "pr": PR, "sha": SHA, "by": "роль", "created": T0}, fh)
    b.run(evil={"PANTHEON_STATE": evil})
    check("PANTHEON_STATE из launchd: заявка, помощник и шлюз чужого STATE не берутся — окна, согласия и слияния нет",
          not b.merges() and not os.path.exists(os.path.join(b.rec, "evil"))
          and not os.path.exists(os.path.join(evil, "owner-log", "merge-approve.log")), (b.outs[-1], b.merges()))


def test_env_notify_log():
    b = Box()
    b.request()
    b.set("touchid-rc", 2)
    evil = os.path.join(b.tmp, "evil-notify.log")
    b.run(extra={"PANTHEON_NOTIFY_LOG": None, "PANTHEON_NO_NOTIFY": "1"}, evil={"PANTHEON_NOTIFY_LOG": evil})
    check("PANTHEON_NOTIFY_LOG из launchd: строку с заголовком PR в чужой файл проход не пишет",
          not os.path.exists(evil) and not os.path.exists(b.notify_log), b.outs[-1])


def test_env_fake():
    b = Box()
    b.request()
    fakes = {"PANTHEON_FAKE_IDLE": "5", "PANTHEON_FAKE_AC": "1", "PANTHEON_FAKE_WAKE": "1", "PANTHEON_FAKE_LIMIT": "1"}
    b.run(extra={"PANTHEON_FAKE_IDLE": "99999"}, evil=fakes)
    check("PANTHEON_FAKE_IDLE из launchd: простой не подменён — владельца нет, окна нет, заявка ждёт",
          not b.windows() and b.req() is not None, (b.outs[-1], b.windows()))
    leaked = sorted({k for c in b.calls("gh") for k in c.get("keys", []) if k in fakes and k != "PANTHEON_FAKE_IDLE"})
    check("PANTHEON_FAKE_* из launchd до gh не доходят", b.calls("gh") and not leaked, leaked)


def test_env_path():
    b = Box()
    b.request()
    ebin = os.path.join(b.tmp, "evil-bin")
    os.makedirs(ebin)
    script(os.path.join(ebin, "gh"), EVIL)
    b.run(evil={"PATH": ebin + ":/usr/bin:/bin"})
    check("PATH из launchd: gh не из него — поддельный gh не запускался, слит своим",
          not os.path.exists(os.path.join(b.rec, "evil")) and len(b.merges()) == 1, (b.outs[-1], b.merges()))


def test_env_gh_config():
    b = Box()
    b.request()
    bad = {"GH_CONFIG_DIR": os.path.join(b.tmp, "evil-gh"), "GH_TOKEN": "x", "GITHUB_TOKEN": "x",
           "GH_ENTERPRISE_TOKEN": "x", "XDG_CONFIG_HOME": os.path.join(b.tmp, "evil-xdg")}
    b.run(evil=bad)
    leaked = sorted({k for c in b.calls("gh") for k in c.get("keys", []) if k in bad})
    check("GH_CONFIG_DIR, токены и XDG_CONFIG_HOME из launchd до gh не доходят",
          len(b.merges()) == 1 and not leaked, leaked)


def test_env_python():
    """PANTHEON_PYTHON: тик не берёт его (и config.toml из PANTHEON_STATE), проход и щелчок — интерпретатор тика.
    PYTHONEXECUTABLE (на macOS задаёт sys.executable даже при -I) интерпретатор прохода не подменяет (argus-b 0303c)."""
    b = Box()
    b.request()
    b.set("touchid-rc", 2)
    # проход: PANTHEON_PYTHON ему ставит bin/pantheon из pass_env тика; sys.executable подменён PYTHONEXECUTABLE
    b.run(extra={"PANTHEON_PYTHON": PY311}, evil={"PYTHONEXECUTABLE": os.path.join(b.tmp, "evil-python")})
    note = open(b.notify_log).read() if os.path.exists(b.notify_log) else ""
    cmd = note.rstrip().split("|execute:", 1)[-1].rsplit("|", 1)[0] if "|execute:" in note else ""
    words = shlex.split(cmd) if cmd else []
    py = [w[len("PANTHEON_PYTHON="):] for w in words if w.startswith("PANTHEON_PYTHON=")]
    check("щелчок: /usr/bin/env -i, HOME, постоянный PATH и PANTHEON_PYTHON прохода, а не окружение уведомления",
          words[:2] == ["/usr/bin/env", "-i"] and f"HOME={os.path.realpath(b.home)}" in words
          and any(w.startswith("PATH=/usr/bin:/bin") for w in words) and len(py) == 1
          and os.path.realpath(py[0]) == os.path.realpath(PY311) and words[-2:] == ["run", "--click"], cmd)

    # тик: интерпретатор из PANTHEON_PYTHON, из config.toml чужого PANTHEON_STATE и из config.toml от HOME (HOME тоже
    # задаёт launchd; argus-b 0303, п. 1) не запускается. Тик — копия с заглушкой lib/run.py: config.toml он читает
    # от настоящей домашней папки учётной записи, и найденный там интерпретатор запустит только заглушку, а не тик.
    # PATH — только нужные утилиты, без python
    tools = os.path.join(b.tmp, "tools")
    os.makedirs(tools)
    for u in ("dirname", "readlink", "sed", "head", "date", "cat", "mkdir"):
        os.symlink(_shutil.which(u, path="/usr/bin:/bin"), os.path.join(tools, u))
    evil_py = script(os.path.join(b.tmp, "evil-python"), EVIL)
    evil_state = os.path.join(b.tmp, "evil-state")
    os.makedirs(evil_state)
    for d in (evil_state, b.state):   # b.state = HOME/.local/state/pantheon
        with open(os.path.join(d, "config.toml"), "w") as fh:
            fh.write(f'python = "{evil_py}"\n')
    plug = os.path.join(b.tmp, "plugin")
    os.makedirs(os.path.join(plug, "bin"))
    os.makedirs(os.path.join(plug, "lib"))
    tick = os.path.join(plug, "bin", "pantheon-tick")
    _shutil.copy2(os.path.join(os.path.dirname(HERE), "bin", "pantheon-tick"), tick)
    _shutil.copy2(os.path.join(LIBDIR, "find-python.sh"), os.path.join(plug, "lib", "find-python.sh"))
    with open(os.path.join(plug, "lib", "run.py"), "w") as fh:
        fh.write("import json, os, sys\nopen(os.path.join(os.environ['FAKE_REC'], 'tick-ran'), 'a').write(json.dumps("
                 "[sys.executable, os.environ.get('PANTHEON_PYTHON'), os.environ.get('PYTHONEXECUTABLE')]) + '\\n')\n")
    for name, extra in (("PANTHEON_PYTHON", {"PANTHEON_PYTHON": evil_py}),
                        ("config.toml из PANTHEON_STATE", {"PANTHEON_STATE": evil_state}),
                        ("config.toml от HOME", {})):
        env = {"PATH": tools, "HOME": b.home, "PANTHEON_HOME": b.pantheon, "FAKE_REC": b.rec, "TMPDIR": _ROOT,
               "PANTHEON_PY_DIRS": os.path.join(b.tmp, "nowhere")}
        env.update(extra)
        r = subprocess.run(["/bin/sh", tick], env=env, capture_output=True, text=True, timeout=60)
        check(f"тик: {name} из launchd — интерпретатор не запускается",
              not os.path.exists(os.path.join(b.rec, "evil")), (r.returncode, r.stderr[-300:]))
    os.unlink(os.path.join(b.state, "config.toml"))
    # тик снимает PYTHONEXECUTABLE до запуска python: иначе sys.executable тика (и pass_env, run_env его задач) —
    # заглушка из launchd. PANTHEON_PY_DIRS тик не берёт: кандидата оттуда он даже не проверяет (проверка его запускает)
    pydir = os.path.join(b.tmp, "pydir")
    os.makedirs(pydir)
    os.symlink(PY311, os.path.join(pydir, "python3"))
    ran = os.path.join(b.rec, "tick-ran")
    if os.path.exists(ran):
        os.unlink(ran)
    env = {"PATH": tools + ":" + pydir, "HOME": b.home, "PANTHEON_HOME": b.pantheon, "FAKE_REC": b.rec,
           "TMPDIR": _ROOT, "PYTHONEXECUTABLE": evil_py}
    r = subprocess.run(["/bin/sh", tick], env=env, capture_output=True, text=True, timeout=60)
    rows = [json.loads(x) for x in open(ran).read().splitlines()] if os.path.exists(ran) else []
    check("тик: PYTHONEXECUTABLE из launchd снят — sys.executable тика = PANTHEON_PYTHON тика, не заглушка",
          len(rows) == 1 and rows[0][1]
          and os.path.realpath(rows[0][0]) == os.path.realpath(rows[0][1]) != os.path.realpath(evil_py)
          and rows[0][2] is None
          and not os.path.exists(os.path.join(b.rec, "evil")), (rows, r.returncode, r.stderr[-300:]))
    evil_dir = os.path.join(b.tmp, "evil-dir")
    os.makedirs(evil_dir)
    for v in ("3.14", "3.13", "3.12", "3.11"):
        script(os.path.join(evil_dir, "python" + v), EVIL)
    env = {"PATH": tools, "HOME": b.home, "PANTHEON_HOME": b.pantheon, "FAKE_REC": b.rec, "TMPDIR": _ROOT,
           "PANTHEON_PY_DIRS": evil_dir}
    r = subprocess.run(["/bin/sh", tick], env=env, capture_output=True, text=True, timeout=60)
    check("тик: PANTHEON_PY_DIRS из launchd — кандидат оттуда не запускается",
          not os.path.exists(os.path.join(b.rec, "evil")), (r.returncode, r.stderr[-300:]))
    # домашняя папка учётной записи не определилась: config.toml тик ищет в /nonexistent, а не от HOME из launchd
    plug2 = os.path.join(b.tmp, "plugin2")
    os.makedirs(os.path.join(plug2, "lib"))
    _shutil.copytree(os.path.join(plug, "bin"), os.path.join(plug2, "bin"))
    _shutil.copy2(os.path.join(plug, "lib", "run.py"), os.path.join(plug2, "lib", "run.py"))
    with open(os.path.join(plug2, "lib", "find-python.sh"), "w") as fh:
        fh.write(f'. "{os.path.join(LIBDIR, "find-python.sh")}"\naccount_home() {{ return 1; }}\n')
    with open(os.path.join(b.state, "config.toml"), "w") as fh:
        fh.write(f'python = "{evil_py}"\n')
    env = {"PATH": tools, "HOME": b.home, "PANTHEON_HOME": b.pantheon, "FAKE_REC": b.rec, "TMPDIR": _ROOT}
    r = subprocess.run(["/bin/sh", os.path.join(plug2, "bin", "pantheon-tick")], env=env, capture_output=True,
                       text=True, timeout=60)
    check("тик: account_home не сработал — config.toml от HOME из launchd не читается",
          not os.path.exists(os.path.join(b.rec, "evil")), (r.returncode, r.stderr[-300:]))
    os.unlink(os.path.join(b.state, "config.toml"))
    # а config.toml тик берёт от домашней папки учётной записи (account_home): её realpath, не HOME и не CDPATH
    import pwd
    r = subprocess.run(["/bin/sh", "-c", '. "$1"; account_home', "sh", os.path.join(LIBDIR, "find-python.sh")],
                       env={"PATH": tools, "HOME": b.home, "CDPATH": b.tmp}, capture_output=True, text=True, timeout=30)
    check("тик: домашняя папка для config.toml — realpath pw_dir учётной записи, не HOME из launchd",
          r.stdout.strip() == os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir), (r.stdout, r.stderr))
    # pw_dir — ссылка: account_home отдаёт её realpath (pwd -P); pw_dir не определился — пусто и код не 0
    acct_link = os.path.join(b.tmp, "acct-link")
    os.symlink(b.home, acct_link)
    fp = os.path.join(LIBDIR, "find-python.sh")
    r = subprocess.run(["/bin/sh", "-c", '. "$1"; L=$2; _account_dir() { printf "%s\\n" "$L"; }; account_home', "sh", fp,
                        acct_link], env={"PATH": tools, "HOME": b.tmp}, capture_output=True, text=True, timeout=30)
    check("account_home: pw_dir-ссылка — её realpath", r.stdout.strip() == os.path.realpath(b.home), (r.stdout, r.stderr))
    r = subprocess.run(["/bin/sh", "-c", '. "$1"; _account_dir() { return 1; }; account_home', "sh", fp],
                       env={"PATH": tools, "HOME": b.home}, capture_output=True, text=True, timeout=30)
    check("account_home: pw_dir не определился — пусто и код не 0", r.returncode != 0 and r.stdout == "",
          (r.returncode, r.stdout))

    # тик → проход: окружение с нуля, PANTHEON_PYTHON — интерпретатор, который нашёл тик (он ставит PANTHEON_PYTHON
    # сам), а не sys.executable: его подменяет PYTHONEXECUTABLE из launchd
    code = ("import json, sys; sys.path.insert(0, %r); import pantheon as p; got = []\n"
            "p.subprocess.Popen = lambda argv, **kw: got.append(kw.get('env'))\n"
            "p.merge_kick(); print(json.dumps([got, %r]))" % (LIBDIR, PY311))
    bad = {"PANTHEON_FAKE_IDLE": "5", "PANTHEON_NOTIFY_LOG": "/x", "GH_CONFIG_DIR": "/x", "PANTHEON_PYTHON": PY311,
           "PYTHONEXECUTABLE": evil_py}
    r = subprocess.run([PY311, "-I", "-c", code], env=b.env(T0, bad), capture_output=True, text=True, timeout=60)
    try:
        got, exe = json.loads(r.stdout.strip().splitlines()[-1])
        env = got[0] if len(got) == 1 else {}
    except (ValueError, IndexError):
        env, exe = {}, None
    check("тик → проход: окружение — HOME, постоянный PATH и PANTHEON_PYTHON тика, ничего из launchd",
          isinstance(env, dict) and sorted(env) == ["HOME", "PANTHEON_PYTHON", "PATH"] and env["PANTHEON_PYTHON"] == exe
          and env["PATH"].startswith("/usr/bin:/bin") and b.bin not in env["PATH"], r.stdout + r.stderr)


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544); исключение — провал случая
    run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)], FAILS,
              lambda name, err: FAILS.append(name))
    print(f"\n{'ПРОВАЛ: ' + ', '.join(FAILS) if FAILS else 'все прошли'}")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
