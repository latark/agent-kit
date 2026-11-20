#!/usr/bin/env python3
"""Три отметки argus на пунктах «Готово, когда» и задача-проба после выпуска (metis-1260).

- [review]  criteria_required: неотмеченные пункты задач из Closes и ветки, «пункт N <id>» тела, у PR «часть» — ничего,
            задача чужого направления — нет; _review_criteria_problem: «проба» без опоры и с «ОПОРА» — отказ;
            criteria_accepted засчитывает «проба», criteria_probes — только её с опорой; _accept_unmarked: пункт без
            отметки — причина с его номером, сбой gh — причина; review_criteria_gap (merge request) — «fail» без
            приёмки на head, None с приёмкой на Opus и у «часть»; файлов PR нет — как ядро (не Opus не в счёт), не ядро
            — в счёт; policy.toml не прочитан — задача любого направления (metis-1266). criteria_dirs — одно приведение
            регистра для accept и merge request: policy.toml «Latark/Agent-Kit» находится по repo любого регистра.
            Правило идёт через настоящие T.* (load_tasks, done_criteria, unchecked_numbers, criterion_hash,
            parse_criterion): граница ядра для них — эти случаи (test_core_deps, исключение tasks_mod).
- [autoclose] close_pr: «да» и «проба» → задача done, «проба» → задача-проба (source, тег, пункт с опорой, PR) в
            waiting выпуска плагина, повторный проход второй не заводит; хеш не сошёлся — пробы нет; PR без плагинов —
            сразу todo; выпуск не в строке кэша — released(repo); сбой probes — PR повторим. probe_release: версия та
            же, старше или неизвестна — ждёт, новее — todo. Догон (tick_backlog) — тоже проба. merged_extra: плагины и
            releases.json на коммите слияния, из прошлого кэша, PR в done — gh не зовётся.
- [сверка]  boardmerged.probes_stuck: проба ждёт выпуска дольше 3 суток — строка, моложе и без тега — нет.
- [выпуск]  plugins.plugins_released: версии из releases.json каталога, другой репозиторий и нет файла — None.
- [cli]     fetch с поддельным gh → проход: запись argus «да» + «проба» → задача done и проба в waiting; повтор — без
            второй; новая версия в releases.json каталога → проба в todo.
Мутанты — внутри теста: модуль с подменённой строкой грузится заново, мутант убит, только если покраснел именно
названный случай (упавший шаг засчитывает лишь случаи, дошедшие до проверки).

Запуск: python3.14 -I plugins/pantheon/tests/test_criteria_probe.py  (код выхода 0 — все прошли)
"""
import json
import os
import shutil
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_criteria_tick as C  # noqa: E402 — общие make, put, verdict, подделка gh (TMPDIR — его корень)

T = C.T
LIB = C.LIB
REVIEW_PY, RULES_PY, AUTOCLOSE_PY, BOARD_PY, PLUGINS_PY = (os.path.join(LIB, f + ".py") for f in
                                                           ("review", "review_rules", "autoclose", "boardmerged",
                                                            "plugins"))
REPO = "latark/agent-kit"
H1, A1, A2, T0, DAY = C.H1, C.A1, C.A2, C.T0, 86400
crit, verdict, check, text = C.crit, C.verdict, C.check, C.text
TWO = C.TWO
ONE_DONE = "## Готово, когда\n\n- [x] первый пункт: файл a.py\n- [ ] второй пункт (тест)\n"


def load(path, src=None, P=None, name="mut"):
    """Модуль из path (src — подменённый текст) заново; P — ядро pantheon для lib-модулей с P.<имя>."""
    m = types.ModuleType(f"pantheon_{name}_{os.path.basename(path)[:-3]}")
    m.__file__ = path
    if P is not None:
        m.P = P._Core(vars(P))
    code = open(path, encoding="utf-8").read() if src is None else src
    exec(compile(code, path, "exec"), m.__dict__)
    return m


def cases(pairs):
    """[(случай, функция)] → {случай: bool}; исключение в функции — случай красный."""
    out = {}
    for name, fn in pairs:
        try:
            out[name] = bool(fn())
        except Exception:  # noqa: BLE001 — упавший случай красный
            out[name] = False
    return out


def put(home, tid, body=TWO, status="doing", direction="metis-pantheon", **extra):
    head = {"type": "task", "id": tid, "title": "Задача " + tid, "status": status, "project": "Пантеон",
            "direction": direction, "owner": "metis-pantheon", "created": "2026-11-08",
            "updated": "2026-11-08T10:00:00", "schema_version": 1, **extra}
    d = os.path.join(home, "directions", direction, "tasks")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, tid + ".md")
    lines = [f"{k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, (str, list)) else v}" for k, v in head.items()]
    open(p, "w", encoding="utf-8").write("---\n" + "\n".join(lines) + "\n---\n\n# " + head["title"] + "\n\n" + body
                                         + "\n## Журнал\n\n- 2026-11-08 10:00 — агент: создана\n")
    return p


# --- [review] ---------------------------------------------------------------------------------------------------------

def setup_review():
    tmp, home, state, gh, env = C.make()
    open(os.path.join(home, "directions.toml"), "a", encoding="utf-8").write(
        '\n[[direction]]\nname = "other"\nproject = "Другое"\n')
    put(home, "metis-0001")
    put(home, "metis-0002", status="review")
    put(home, "other-0003", direction="other", owner="other")
    put(home, "metis-0004", body=ONE_DONE)
    os.environ.update(PATH=gh + ":" + os.environ.get("PATH", ""), FAKE_GH_DIR=gh)
    P = C.load_pantheon(tmp)
    return tmp, home, state, gh, P


def scen_review(R, Q, state, gh):
    """R — review.py (_review_criteria_problem, _accept_unmarked), Q — review_rules.py, ядро: правило отметок и отказ
    merge request (criteria_required, criteria_accepted, criteria_probes, review_criteria_gap)."""
    view = os.path.join(gh, "view.json")
    probe = crit("metis-0001", 2, A2, "проба", "живая сессия")
    both = [crit("metis-0001", 1, A1), probe]
    rec = [verdict("accept", H1, criteria=both)]

    def unmarked(body, items):
        if body is None:
            if os.path.exists(view):
                os.remove(view)
        else:
            json.dump({"body": body, "headRefName": "feature"}, open(view, "w", encoding="utf-8"))
        return R._accept_unmarked(REPO, 7, items, R.P.merge_mod())

    M = R.P.merge_mod()
    dirs = M.repo_dirs().get(REPO)   # {"metis-pantheon"} из policy.toml поддельного HOME — как зовёт merge.py

    def req(branch, body):
        return Q.criteria_required(REPO, branch, body, dirs)

    def gap(body, recs, **over):
        """over — подмена функций merge.py у правила (pr_files, window_core, repo_dirs), остальное — настоящее."""
        C.write_records(state, recs)
        api = types.SimpleNamespace(**{**vars(M.criteria_api()), **over})
        return Q.review_criteria_gap(REPO, 7, H1, {"body": body, "headRefName": "feature", "baseRefName": "main"}, api)

    def boom():
        raise OSError("policy.toml не читается")

    pol = os.path.join(os.environ["HOME"], ".claude", "pantheon", "policy.toml")

    def mixed(fn):
        """policy.toml со смешанным регистром репозитория (metis-1266) на время fn."""
        old = open(pol, encoding="utf-8").read()
        open(pol, "w", encoding="utf-8").write('[merge_repos]\nmetis-pantheon = ["Latark/Agent-Kit"]\n')
        try:
            return fn()
        finally:
            open(pol, "w", encoding="utf-8").write(old)

    no_files, not_core = (lambda *a: None), {"pr_files": lambda *a: ["README.md"], "window_core": lambda f: False}
    sonnet = [verdict("accept", H1, criteria=both)]   # перечень CL — не на Opus

    return cases([
        ("required: Closes — неотмеченные пункты задачи",
         lambda: req("feature", "Closes metis-0001") == {"metis-0001": {1: A1, 2: A2}}),
        ("required: «часть» — ничего",
         lambda: req("feature", "Closes metis-0001\nчасть metis-0001") == {}),
        ("required: «пункт 2 <id>» — только он",
         lambda: req("feature", "пункт 2 metis-0002") == {"metis-0002": {2: A2}}),
        ("required: задача чужого направления — нет",
         lambda: req("feature", "Closes other-0003") == {}),
        ("required: отмеченный пункт — не нужен",
         lambda: req("metis-0004-x", "") == {"metis-0004": {2: A2}}),
        ("problem: «проба» без опоры — отказ «без опоры»",
         lambda: "без опоры" in (R._review_criteria_problem("accept", [f"metis-0001#2 {A2} проба"]) or "")),
        ("problem: «проба» с «ОПОРА» — что проверить вживую",
         lambda: "что проверить вживую" in (R._review_criteria_problem("accept", [crit("metis-0001", 2, A2, "проба",
                                                                                        "ОПОРА")]) or "")),
        ("problem: «проба» с опорой — годится", lambda: R._review_criteria_problem("accept", both) is None),
        ("accepted: «проба» в счёт, как «да»",
         lambda: Q.criteria_accepted(rec, 7, H1, "main", False, M) == {"metis-0001": {1: A1, 2: A2}}),
        ("probes: только пункт «проба» с опорой",
         lambda: Q.criteria_probes(rec, 7, H1, "main", False, M) == {"metis-0001": {2: (A2, "живая сессия")}}),
        ("unmarked: пункт 2 без отметки — причина называет только его",
         lambda: "metis-0001#2" in (w := unmarked("Closes metis-0001", both[:1]) or "") and "metis-0001#1" not in w),
        ("unmarked: «да» и «проба» на каждом — None", lambda: unmarked("Closes metis-0001", both) is None),
        ("unmarked: gh не дал тело — причина «gh pr view»", lambda: "gh pr view" in (unmarked(None, both) or "")),
        ("gap: нет приёмки на head — fail с пунктами",
         lambda: (g := gap("Closes metis-0001", []))[0] == "fail" and "metis-0001#1, metis-0001#2" in g[1]),
        ("gap: «да» и «проба» на Opus (ядро: файлы не узнать) — None",
         lambda: gap("Closes metis-0001", [verdict("accept", H1, criteria=both, cl=C.OPUS)]) is None),
        ("gap: «часть» — None", lambda: gap("часть metis-0001", []) is None),
        # metis-1266: ветки review_criteria_gap и criteria_dirs
        ("gap: файлов PR нет — как ядро: «принять» не на Opus не в счёт",
         lambda: (gap("Closes metis-0001", sonnet, pr_files=no_files) or ("",))[0] == "fail"),
        ("gap: файлы есть, не ядро — «принять» не на Opus в счёт",
         lambda: gap("Closes metis-0001", sonnet, **not_core) is None),
        ("gap: policy.toml не прочитан — задача любого направления",
         lambda: "other-0003#1" in (gap("Closes other-0003", [], repo_dirs=boom) or ("", ""))[1]),
        ("dirs: policy.toml со смешанным регистром — направления по repo любого регистра",
         lambda: mixed(lambda: Q.criteria_dirs("LATARK/agent-kit", M)) == {"metis-pantheon"}),
        ("unmarked: policy.toml со смешанным регистром — задача чужого направления не нужна",
         lambda: mixed(lambda: unmarked("Closes other-0003", [])) is None),
    ])


REVIEW_MUTANTS = [
    ("if not got and len(bits) == 3 and bits[2] == T.CRITERION_PROBE:", "if False:",
     "problem: «проба» без опоры — отказ «без опоры»"),
    ('"что проверить вживую после выпуска" if verdict == T.CRITERION_PROBE else', '"x" if False else',
     "problem: «проба» с «ОПОРА» — что проверить вживую"),
    ('return miss and (f"пункты', 'return None and (f"пункты', "unmarked: пункт 2 без отметки — причина называет только его"),
    ('if not isinstance(view, dict):\n        return "gh pr view', 'if False:\n        return "gh pr view',
     "unmarked: gh не дал тело — причина «gh pr view»"),
    ('P.criteria_dirs(repo, M),', 'None,', "unmarked: policy.toml со смешанным регистром — задача чужого направления не нужна"),
]
# правило отметок и отказ merge request — в ядре, review_rules.py (test_core_deps)
RULES_MUTANTS = [
    ("if all(v in CRITERION_OK for _, v, _ in vs)", 'if all(v == "да" for _, v, _ in vs)',
     "accepted: «проба» в счёт, как «да»"),
    ("for n, (h, bases) in items.items() if bases}", "for n, (h, bases) in items.items() if not bases}",
     "probes: только пункт «проба» с опорой"),
    ("want = {} if is_part(body) else", "want = {} if False else", "required: «часть» — ничего"),
    ('or (dirs is not None and head.get("direction") not in dirs):', "or False:",
     "required: задача чужого направления — нет"),
    ("for tid, nums in named_items(body).items():", "for tid, nums in {}.items():",
     "required: «пункт 2 <id>» — только он"),
    ("if nums is None or n in nums}", "if True}", "required: «пункт 2 <id>» — только он"),
    ("for n in T.unchecked_numbers(head, text) if", "for n in range(1, len(crit) + 1) if",
     "required: отмеченный пункт — не нужен"),
    ('return miss and ("fail"', 'return None and ("fail"', "gap: нет приёмки на head — fail с пунктами"),
    # metis-1266: файлов нет — ядро; policy.toml не прочитан — None, а не пустое множество; регистр — lower
    ("core = files is None or any(", "core = files is not None and any(",
     "gap: файлов PR нет — как ядро: «принять» не на Opus не в счёт"),
    ("задачи любого направления\n        return None", "задачи любого направления\n        return set()",
     "gap: policy.toml не прочитан — задача любого направления"),
    ("return M.repo_dirs().get(str(repo).lower())", "return M.repo_dirs().get(str(repo))",
     "dirs: policy.toml со смешанным регистром — направления по repo любого регистра"),
]


def test_review():
    tmp, home, state, gh, P = setup_review()
    try:
        R, Q = load(REVIEW_PY, P=P, name="real"), load(RULES_PY, P=P, name="real")
        for name, ok in scen_review(R, Q, state, gh).items():
            check("[review] " + name, ok)
        for path, muts in ((REVIEW_PY, REVIEW_MUTANTS), (RULES_PY, RULES_MUTANTS)):
            src, base = open(path, encoding="utf-8").read(), os.path.basename(path)
            for old, new, case in muts:
                if src.count(old) != 1:
                    check(f"[review] мутант «{old[:50]}»: строка в {base} одна", False, src.count(old))
                    continue
                m = load(path, src.replace(old, new), P)
                got = scen_review(m, Q, state, gh) if path == REVIEW_PY else scen_review(R, m, state, gh)
                check(f"[review] мутант {base} «{old[:50]}» убит случаем «{case}»", got.get(case) is False, got)
    finally:
        shutil.rmtree(tmp, True)


# --- [autoclose] ------------------------------------------------------------------------------------------------------

def probes_of(home, tid):
    return [(p, h, b) for p, h, b in T.load_tasks(home, T.WORK_TYPES).values()
            if h.get("title") == f"живая проба после выпуска: {tid}"]


def scen_autoclose(A):
    tmp, home, state, gh, env = C.make()
    try:
        return _scen_autoclose(A, home, state)
    finally:
        shutil.rmtree(tmp, True)


def _scen_autoclose(A, home, state):
    p = {i: put(home, f"metis-000{i}") for i in (1, 2, 3, 4, 6)}
    put(home, "metis-0007", status="waiting", waiting_on="выпуск latark/agent-kit: pantheon после 0.11.1")
    both = {1: A1, 2: A2}
    acc = {i: {f"metis-000{i}": dict(both)} for i in (1, 2, 3, 4, 6)}
    prb = {1: {"metis-0001": {2: (A2, "живая сессия: pantheon check")}}, 2: {"metis-0002": {2: (C.h("другой"), "x")}},
           3: {"metis-0003": {2: (A2, "окно")}}, 4: {"metis-0004": {1: (A1, "страница")}}}
    accepted = lambda repo, pr: acc.get(pr["number"], {})  # noqa: E731
    probes = lambda repo, pr: prb.get(pr["number"], {})  # noqa: E731
    res, ver = {}, [None]

    def close(n, plugins=("pantheon",), released=..., probes=probes, rel=None):
        pr = dict(C.mpr(n, f"Closes metis-000{n}", H1), head=H1, plugins=list(plugins))
        if released is not ...:
            pr["released"] = released
        log, errors = [], {}
        ok = A.close_pr(home, T0, REPO, pr, {"metis-pantheon"}, T, None, log, errors, accepted, probes, rel)
        return ok, errors

    def release(v):
        ver[0] = v
        A.probe_release(home, T0 + 60, T, lambda repo: None if ver[0] is None else {"pantheon": ver[0]}, [], {})
        return T.read(probes_of(home, "metis-0001")[0][0])[0]

    def boom(repo, pr):
        raise RuntimeError("журнал шлюза")

    def waiting_on(tid):
        """waiting_on пробы сразу после создания: probe_release ниже переводит пробы в todo, и task_set стирает поле."""
        return probes_of(home, tid)[0][1].get("waiting_on")
    steps = [
        ("ok1", lambda: close(1, released={"pantheon": "0.11.356"})[0]),
        ("ok1b", lambda: close(1, released={"pantheon": "0.11.356"})[0]),
        ("c2", lambda: close(2, released={"pantheon": "0.11.356"})),
        ("c3", lambda: close(3, plugins=())),
        ("w1", lambda: waiting_on("metis-0001")),
        ("c4", lambda: close(4, rel=lambda repo: {"pantheon": "0.11.300"})), ("w4", lambda: waiting_on("metis-0004")),
        ("c6", lambda: close(6, released={}, probes=boom)),
        ("r_none", lambda: release(None)), ("r_old", lambda: release("0.11.355")), ("r_same", lambda: release("0.11.356")),
        ("r_new", lambda: release("0.11.357")),
        ("t7", lambda: T.read(os.path.join(home, "directions", "metis-pantheon", "tasks", "metis-0007.md"))[0]),
    ]
    for k, fn in steps:
        try:
            res[k] = fn()
        except Exception as e:  # noqa: BLE001 — шаг упал: его случаи красные
            res[k] = e
    st = lambda i: T.read(p[i])[0].get("status")  # noqa: E731
    one = lambda tid: probes_of(home, tid)[0]  # noqa: E731
    wait = "выпуск latark/agent-kit: pantheon после 0.11.356"
    pid = lambda: one("metis-0001")[1]["id"]  # noqa: E731
    out = cases([
        ("close_pr: «да» и «проба» — задача done", lambda: st(1) == "done"),
        ("close_pr: «проба» → проба ждёт выпуска pantheon после 0.11.356",
         lambda: res["w1"] == wait and isinstance(res["r_none"], dict)
         and res["r_none"].get("status") == "waiting"),
        ("проба: source, тег, from, пункт с опорой, PR в теле",
         lambda: (h := one("metis-0001")[1]).get("source") == "metis-0001" and "проба" in h.get("tags")
         and h.get("from") == "остаток" and h.get("owner") == "metis-pantheon"
         and "metis-0001 п.2: второй пункт (тест) — проверить вживую: живая сессия: pantheon check" in one("metis-0001")[2]
         and "PR #1 (latark/agent-kit)" in one("metis-0001")[2]),
        ("исходная: строка журнала со ссылкой на пробу", lambda: f"пункты «проба» → {pid()}" in text(p[1])),
        ("повтор: вторая проба не заведена, PR обработан",
         lambda: len(probes_of(home, "metis-0001")) == 1 and res["ok1"] is True and res["ok1b"] is True),
        ("хеш пункта не сошёлся — пробы нет", lambda: probes_of(home, "metis-0002") == [] and st(2) == "done"),
        ("PR без плагинов — проба сразу todo с next",
         lambda: one("metis-0003")[1].get("status") == "todo" and one("metis-0003")[1].get("next") == A.PROBE_NEXT),
        ("выпуска нет в строке кэша — released(repo) при создании",
         lambda: res["w4"] == "выпуск latark/agent-kit: pantheon после 0.11.300"),
        ("сбой probes — PR повторим, ошибка в errors",
         lambda: res["c6"][0] is False and "RuntimeError: журнал шлюза" in res["c6"][1].get(f"{REPO}#6", "")),
        ("probe_release: старше — ждёт", lambda: res["r_old"].get("status") == "waiting"),
        ("probe_release: та же версия — ждёт", lambda: res["r_same"].get("status") == "waiting"),
        ("probe_release: новее — todo с next и строкой журнала",
         lambda: res["r_new"].get("status") == "todo" and res["r_new"].get("next") == A.PROBE_NEXT
         and "выпуск pantheon 0.11.357 вышел — живая проба в очередь" in one("metis-0001")[2]),
        ("probe_release: без тега «проба» — не тронута", lambda: res["t7"].get("status") == "waiting"),
        ("version_newer: числами, «—» — любая, пусто — нет",
         lambda: A.version_newer("0.11.10", "0.11.9") and not A.version_newer("0.11.9", "0.11.10")
         and A.version_newer("1", A.PROBE_NONE) and not A.version_newer(None, "1")),
    ])
    out.update(_scen_backlog(A, home, state))
    return out


def _scen_backlog(A, home, state):
    """Догон: PR уже в done состояния, «проба» принята после слияния → tick_backlog отмечает и заводит пробу."""
    pb = put(home, "metis-0009", status="review")
    open(pb, "a", encoding="utf-8").write("- 2026-11-09 10:00 — плановый проход: PR #71 (latark/agent-kit) слит, "
                                          "неотмечено 2 (пункты 1, 2)\n")
    row = dict(C.mpr(71, "Closes metis-0009", H1), head=H1, plugins=["pantheon"], released={"pantheon": "0.11.356"})
    cache, stf = os.path.join(state, "ac-prs.json"), os.path.join(state, "ac.json")
    json.dump({"fetched": T0, "merged": {REPO: [row]}}, open(cache, "w", encoding="utf-8"))
    json.dump({"since": T0 - 10, "done": {f"{REPO}#71": "2026-11-09T10:00:00"}}, open(stf, "w", encoding="utf-8"))
    acc = lambda repo, pr: {"metis-0009": {1: A1, 2: A2}} if pr["number"] == 71 else {}  # noqa: E731
    prb = lambda repo, pr: {"metis-0009": {1: (A1, "страница")}} if pr["number"] == 71 else {}  # noqa: E731
    try:
        A.run(home, stf, cache, T0, {REPO: {"metis-pantheon"}}, T, accepted=acc, probes=prb)
    except Exception:  # noqa: BLE001 — шаг упал: случай красный
        pass
    return cases([("догон: «проба» после слияния — проба заведена",
                   lambda: len(probes_of(home, "metis-0009")) == 1 and T.read(pb)[0].get("status") == "done")])


AUTOCLOSE_MUTANTS = [
    ("probed = make_probes(pantheon, t, repo, pr, dirs, T, probes, released, log, errors)", "probed = True",
     "close_pr: «проба» → проба ждёт выпуска pantheon после 0.11.356"),
    ("and ok and probed", "and ok", "сбой probes — PR повторим, ошибка в errors"),
    ('if any(h.get("title") == title and mark in (b or "") for _, h, b in tasks.values()):', "if False:",
     "повтор: вторая проба не заведена, PR обработан"),
    ("and T.criterion_hash(crit[k - 1][1]) == h]", "]", "хеш пункта не сошёлся — пробы нет"),
    ("if plugins and isinstance(before, dict):", "if False:",
     "close_pr: «проба» → проба ждёт выпуска pantheon после 0.11.356"),
    ("if before is None and plugins and released:", "if False:", "выпуска нет в строке кэша — released(repo) при создании"),
    (" or not all(version_newer(cur.get(x), v) for x, v in pairs):", ":", "probe_release: та же версия — ждёт"),
    ('> tuple(int(x) for x in str(old).split("."))', '!= tuple(int(x) for x in str(old).split("."))',
     "probe_release: старше — ждёт"),
    (' or PROBE_TAG not in (head.get("tags") or []):', ":", "probe_release: без тега «проба» — не тронута"),
    ("make_probes(pantheon, t, repo, pr, repo_dirs[repo], T, probes, released, log, errors, {tid})", "None",
     "догон: «проба» после слияния — проба заведена"),
]


def scen_extra(A, gh):
    env = dict(os.environ, PANTHEON_GH=os.path.join(gh, "gh"), FAKE_GH_DIR=gh)
    json.dump({"v": 1, "plugins": {"pantheon": {"version": "0.11.356", "tree": "x"}}},
              open(os.path.join(gh, "releases.json"), "w", encoding="utf-8"))
    pr, oid = C.mpr(1, "Closes metis-0001", H1), "a" * 40
    files = ["plugins/pantheon/lib/x.py", "README.md"]
    prev = {"merged": {REPO: [{"number": 1, "released": {"pantheon": "0.1"}}]}}
    return cases([
        ("extra: плагины из путей, released из releases.json на коммите слияния",
         lambda: (o := A.merged_extra(REPO, pr, oid, files, None, {}, {}, env))["plugins"] == ["pantheon"]
         and o.get("released") == {"pantheon": "0.11.356"}),
        ("extra: released из прошлого кэша", lambda: A.merged_extra(REPO, pr, oid, files, None, prev, {}, env)
         .get("released") == {"pantheon": "0.1"}),
        ("extra: PR уже в done — gh не зовётся, поля нет",
         lambda: "released" not in A.merged_extra(REPO, pr, oid, files, None, {}, {f"{REPO}#1": "x"}, env)),
        ("extra: без плагинов — поля нет", lambda: "released" not in A.merged_extra(REPO, pr, oid, ["README.md"], None,
                                                                                     {}, {}, env)),
    ])


EXTRA_MUTANTS = [
    ('out["released"] = old["released"]', "pass", "extra: released из прошлого кэша"),
    ("and f\"{repo}#{pr.get('number')}\" not in done", "", "extra: PR уже в done — gh не зовётся, поля нет"),
    ('"plugins": sorted({m.group(1) for f in files if (m := PLUGIN_PATH_RE.match(f))})', '"plugins": ["pantheon"]',
     "extra: без плагинов — поля нет"),
]


def test_autoclose():
    import autoclose as A0
    for name, ok in scen_autoclose(A0).items():
        check("[autoclose] " + name, ok)
    tmp, home, state, gh, env = C.make()
    try:
        for name, ok in scen_extra(A0, gh).items():
            check("[autoclose] " + name, ok)
        src = open(AUTOCLOSE_PY, encoding="utf-8").read()
        for muts, scen in ((AUTOCLOSE_MUTANTS, scen_autoclose), (EXTRA_MUTANTS, lambda m: scen_extra(m, gh))):
            for old, new, case in muts:
                if src.count(old) != 1:
                    check(f"[autoclose] мутант «{old[:50]}»: строка в autoclose.py одна", False, src.count(old))
                    continue
                got = scen(load(AUTOCLOSE_PY, src.replace(old, new)))
                check(f"[autoclose] мутант «{old[:50]}» убит случаем «{case}»", got.get(case) is False, got)
    finally:
        shutil.rmtree(tmp, True)


# --- [сверка] boardmerged.probes_stuck ---------------------------------------------------------------------------------

def scen_stuck(B, A):
    on = "выпуск latark/agent-kit: pantheon после 0.11.356"
    old = "## Журнал\n\n- 2026-11-01 10:00 — плановый проход: создана\n"
    young = "## Журнал\n\n- 2026-11-04 10:00 — плановый проход: создана\n"
    head = lambda tags: {"type": "task", "status": "waiting", "tags": tags, "waiting_on": on}  # noqa: E731
    tasks = {"metis-0101": ("", head(["проба"]), old), "metis-0102": ("", head(["проба"]), young),
             "metis-0103": ("", head([]), old)}
    t = T._journal(old)[0][0] + 4 * DAY
    got = lambda: {k for k, _, _ in B.probes_stuck(tasks, t, T, A)}  # noqa: E731
    return cases([
        ("stuck: проба ждёт выпуска 4 сут — строка сверки", lambda: "metis-0101" in got()),
        ("stuck: 1 сут — нет", lambda: "metis-0102" not in got()),
        ("stuck: без тега «проба» — нет", lambda: "metis-0103" not in got()),
        ("stuck: merged_stuck берёт пробы", lambda: any(k == "metis-0101" for k, _, _ in B.merged_stuck(tasks, {}, t, T, A))),
    ])


STUCK_MUTANTS = [
    ("if first is not None and t - first >= days * DAY:", "if first is not None:", "stuck: 1 сут — нет"),
    (' or tag not in (head.get("tags") or [])', "", "stuck: без тега «проба» — нет"),
    ("out = probes_stuck(tasks, t, T, A, days)", "out = []", "stuck: merged_stuck берёт пробы"),
]


def test_stuck():
    import autoclose as A0
    for name, ok in scen_stuck(load(BOARD_PY, name="real"), A0).items():
        check("[сверка] " + name, ok)
    src = open(BOARD_PY, encoding="utf-8").read()
    for old, new, case in STUCK_MUTANTS:
        if src.count(old) != 1:
            check(f"[сверка] мутант «{old[:50]}»: строка в boardmerged.py одна", False, src.count(old))
            continue
        got = scen_stuck(load(BOARD_PY, src.replace(old, new)), A0)
        check(f"[сверка] мутант «{old[:50]}» убит случаем «{case}»", got.get(case) is False, got)


# --- [выпуск] plugins.plugins_released и [cli] сквозной проход -----------------------------------------------------

def catalog(tmp, versions):
    cat = os.path.join(tmp, "catalog")
    os.makedirs(os.path.join(cat, ".claude-plugin"), exist_ok=True)
    os.makedirs(os.path.join(tmp, ".claude", "plugins"), exist_ok=True)
    json.dump({"agent-kit": {"source": {"source": "github", "repo": REPO}, "installLocation": cat}},
              open(os.path.join(tmp, ".claude", "plugins", "known_marketplaces.json"), "w", encoding="utf-8"))
    rel = os.path.join(cat, ".claude-plugin", "releases.json")
    if versions is None:
        if os.path.exists(rel):
            os.remove(rel)
        return
    json.dump({"v": 1, "plugins": {k: {"version": v, "tree": "x"} for k, v in versions.items()}},
              open(rel, "w", encoding="utf-8"))


def scen_released(R, tmp):
    def got(versions, repo):
        catalog(tmp, versions)
        return R.plugins_released(repo)
    return cases([
        ("released: репозиторий каталога — версии из releases.json",
         lambda: got({"pantheon": "0.11.357", "guard": "0.5.1"}, "LaTark/Agent-Kit") == {"pantheon": "0.11.357",
                                                                                         "guard": "0.5.1"}),
        ("released: другой репозиторий — None", lambda: got({"pantheon": "1"}, "latark/other") is None),
        ("released: нет releases.json — None", lambda: got(None, REPO) is None),
    ])


RELEASED_MUTANTS = [
    ('if not isinstance(src, dict) or str(src.get("repo") or "").lower() != str(repo or "").lower():',
     "if not isinstance(src, dict):", "released: другой репозиторий — None"),
]


def test_released_and_cli():
    tmp, home, state, gh, env = C.make()
    try:
        P = C.load_pantheon(tmp)
        for name, ok in scen_released(load(PLUGINS_PY, P=P, name="real"), tmp).items():
            check("[выпуск] " + name, ok)
        src = open(PLUGINS_PY, encoding="utf-8").read()
        for old, new, case in RELEASED_MUTANTS:
            ok = src.count(old) == 1 and scen_released(load(PLUGINS_PY, src.replace(old, new), P), tmp).get(case) is False
            check(f"[выпуск] мутант «{old[:50]}» убит случаем «{case}»", ok)
        catalog(tmp, None)
        cli(home, state, gh, env, tmp)
    finally:
        shutil.rmtree(tmp, True)


def cli(home, state, gh, env, tmp):
    pa = put(home, "metis-0001")
    C.write_records(state, [verdict("accept", H1, pr=1, criteria=[
        crit("metis-0001", 1, A1), crit("metis-0001", 2, A2, "проба", "живая сессия: pantheon check")])])
    row = dict(C.mpr(1, "Closes metis-0001", H1, files=("plugins/pantheon/README.md",)),
               mergeCommit={"oid": "b" * 40})
    json.dump([row], open(os.path.join(gh, "latark_agent-kit-merged.json"), "w", encoding="utf-8"))
    json.dump({"v": 1, "plugins": {"pantheon": {"version": "0.11.356", "tree": "x"}}},
              open(os.path.join(gh, "releases.json"), "w", encoding="utf-8"))
    r = C.pan(env, "autoclose", "fetch")
    pr = probes_of(home, "metis-0001")
    check("[cli] fetch: «да» и «проба» на head слияния — задача done, проба ждёт выпуска pantheon после 0.11.356",
          T.read(pa)[0].get("status") == "done" and len(pr) == 1
          and pr[0][1].get("waiting_on") == "выпуск latark/agent-kit: pantheon после 0.11.356",
          r.stdout + r.stderr + text(pa)[-400:])
    r = C.pan(env, "autoclose", "fetch", t=T0 + 60)
    check("[cli] повторный fetch — второй пробы нет", len(probes_of(home, "metis-0001")) == 1, r.stdout + r.stderr)
    catalog(tmp, {"pantheon": "0.11.356"})
    C.pan(env, "autoclose", "fetch", t=T0 + 120)
    check("[cli] каталог на той же версии — проба ждёт",
          T.read(probes_of(home, "metis-0001")[0][0])[0].get("status") == "waiting")
    catalog(tmp, {"pantheon": "0.11.357"})
    r = C.pan(env, "autoclose", "fetch", t=T0 + 180)
    h = T.read(probes_of(home, "metis-0001")[0][0])[0]
    check("[cli] новая версия в releases.json каталога — проба в todo", h.get("status") == "todo", r.stdout + r.stderr)


def main():
    test_review()
    test_autoclose()
    test_stuck()
    test_released_and_cli()
    print(f"{sum(C.results)} из {len(C.results)} прошли")
    return 0 if C.results and all(C.results) else 1


if __name__ == "__main__":
    sys.exit(main())
