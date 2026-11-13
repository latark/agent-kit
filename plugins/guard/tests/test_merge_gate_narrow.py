#!/usr/bin/env python3
"""Запор слияния guard, часть «narrow»: узкая запись тестов (--affected): разбор записи, дельта, шлюз, полный набор пачки.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py; разрез metis-1119.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_narrow.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403


NARROW_CMD = ("pantheon review test -- python3.14 -I plugins/pantheon/scripts/run-tests.py -j 3 --affected --base "
              "origin/main plugins/guard plugins/pantheon plugins/project-tools")


def t_narrow_record(h):
    """metis-0666: узкая запись исполнителя (--affected в своей worktree, без heavy): хук пишет её на HEAD, шлюз на
    основном пути (CI зелёный) засчитывает, отказ «нет записи тестов» называет эту команду; на запасном пути (CI без
    минут) она не в счёт — там только FULL_TESTS."""
    sha, kit = h.sha["agent-kit"], "projects/agent-kit"
    merge = f"gh pr merge 7 --match-head-commit {sha}"
    d, why = h.pre(NARROW_CMD, role="dev-opus", pdir=kit, agent_id="d1")
    check("узкая команда: PreToolUse dev-opus — можно", d == "allow", why)
    h.seed(rec("accept", "latark/agent-kit", 7, sha))
    merge_case("нет записи тестов — отказ называет узкую команду", h.pre(merge, pdir=kit), False, f"`{NARROW_CMD}`")
    merge_case("отказ про tg-read (нет в NARROW_TESTS) — без узкой подсказки, шаблон как раньше",
               h.pre(f"gh pr merge 3 --match-head-commit {h.sha['tg-read']}"), False, "<команда тестов>` (запишет хук guard). Тесты")
    h.post("pantheon review test -- true", "dev-opus", cwd=kit, agent_id="d1")
    check("пустая команда рядом — записи нет, как раньше", [r for r in h.read() if r["kind"] == "tests"] == [], h.read())
    h.post(NARROW_CMD, "dev-opus", cwd=kit, agent_id="d1")
    tests = [r for r in h.read() if r["kind"] == "tests"]
    check("узкую команду хук пишет записью tests на HEAD agent-kit", len(tests) == 1 and tests[0]["sha"] == sha
          and tests[0]["repo"] == ["latark/agent-kit"] and tests[0]["cmd"] == NARROW_CMD
          and tests[0]["by"].get("agent_type") == "dev-opus", tests)
    merge_case("узкая запись, «принять» и зелёный CI — слияние проходит", h.pre(merge, pdir=kit), True)
    mg = _load_merge_gate("merge_gate_narrow")
    check("NARROW_TESTS agent-kit — команда узкой записи", "pantheon review test -- " + mg.NARROW_TESTS["agent-kit"]
          == NARROW_CMD)
    check("narrow_hint: репозиторий без строки — пусто", mg.narrow_hint("latark/tg-read") == "" and mg.narrow_hint(None) == "")
    check("запасной путь: узкая запись не полный набор (full_tests_record)", mg.full_tests_record("latark/agent-kit",
                                                                                                   tests[0]) is False)
    mg.read_records = lambda: tests
    got = mg._billing_problem("latark/agent-kit", 7, sha)[0] or ""
    check("запасной путь: при одной узкой записи — отказ с командой FULL_TESTS", "pantheon review test -- heavy" in got, got)


# узкая запись прохода outside (metis-0734): FULL_TESTS без heavy + `--affected --base <SHA>`, files и map
NARROW_FULL = ("python3.14 -I plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard plugins/pantheon "
               "plugins/project-tools")
NARROW_MAP = "plugins/pantheon/scripts/affected-map.json"
NARROW_MAP_BYTES = b'{"version": 1, "tests": {}}\n'
NARROW_MAP_HASH = hashlib.sha256(NARROW_MAP_BYTES).hexdigest()


def narrow_rec(sha, base, mp=NARROW_MAP_HASH, files=("guard/test_merge_gate.py", "pantheon/test_outside.py"),
               repo="latark/agent-kit", cmd=None):
    """Запись tests, как её пишет `pantheon outside test --affected` (append_tests с files и map)."""
    return dict(rec("tests", repo, None, sha, ""), files=list(files), map=mp,
                cmd=cmd or f"{NARROW_FULL} --affected --base {base}  # .pantheon-verify ветки (HEAD)")


def narrow_history(h):
    """Коммиты без рабочего дерева в клоне agent-kit от init S: H — head PR с картой, M — main ушёл вперёд, X — другая
    ветка, Hn — head без карты, H2 — карта другая, A/B и CA/CB — перекрёстные слияния (две merge-base)."""
    kit, s = h.j("projects/agent-kit"), h.sha["agent-kit"]
    m = {"S": s}
    m["H"] = plumb(kit, [s], {NARROW_MAP: ("100644", NARROW_MAP_BYTES), "x.py": ("100644", b"x = 1\n")}, "head")
    m["M"] = plumb(kit, [s], {"y.py": ("100644", b"y = 1\n")}, "main advanced")
    m["X"] = plumb(kit, [s], {"z.py": ("100644", b"z = 1\n")}, "other branch")
    m["Hn"] = plumb(kit, [s], {"x.py": ("100644", b"x = 2\n")}, "head without map")
    m["H2"] = plumb(kit, [m["H"]], {NARROW_MAP: ("100644", b"{}\n")}, "map changed")
    m["A"] = plumb(kit, [s], {NARROW_MAP: ("100644", NARROW_MAP_BYTES), "a.py": ("100644", b"a\n")}, "A")
    m["B"] = plumb(kit, [s], {"b.py": ("100644", b"b\n")}, "B")
    m["CA"] = plumb(kit, [m["A"], m["B"]], {"b.py": ("100644", b"b\n")}, "CA")
    m["CB"] = plumb(kit, [m["B"], m["A"]], {NARROW_MAP: ("100644", NARROW_MAP_BYTES), "a.py": ("100644", b"a\n")},
                    "CB")
    return m


def t_narrow_gate_unit(h):
    """metis-0734: narrow_tests_record (схема записи), _narrow_problem (база = merge-base head и base PR, карта из
    дерева head) и _billing_problem с узкой записью — напрямую."""
    mg = _load_merge_gate("merge_gate_narrow_unit")
    m, kit, repo = narrow_history(h), h.j("projects/agent-kit"), "latark/agent-kit"
    S, H = m["S"], m["H"]
    good = narrow_rec(H, S)
    check("narrow_tests_record: запись outside --affected → (база, карта)",
          mg.narrow_tests_record(repo, good) == (S, NARROW_MAP_HASH), mg.narrow_tests_record(repo, good))
    rt = f"pantheon review test -- heavy {NARROW_FULL} --affected --base {S}"
    check("narrow_tests_record: та же команда через pantheon review test с heavy → годится",
          mg.narrow_tests_record(repo, narrow_rec(H, S, cmd=rt)) == (S, NARROW_MAP_HASH))
    check("narrow_tests_record: ключи в другом месте команды → годится",
          mg.narrow_tests_record(repo, narrow_rec(H, S, cmd=NARROW_FULL.replace(
              "-j 3", f"-j 3 --base {S} --affected"))) == (S, NARROW_MAP_HASH))
    check("narrow_tests_record: репозиторий в другом регистре → годится",
          mg.narrow_tests_record("Latark/Agent-Kit", good) == (S, NARROW_MAP_HASH))
    bad = {
        "без --affected": dict(good, cmd=f"{NARROW_FULL} --base {S}"),
        "два --affected": dict(good, cmd=f"{NARROW_FULL} --affected --affected --base {S}"),
        "без --base": dict(good, cmd=f"{NARROW_FULL} --affected"),
        "два --base": dict(good, cmd=f"{NARROW_FULL} --affected --base {S} --base {S}"),
        "--base в конце без значения": dict(good, cmd=f"{NARROW_FULL} --affected --base"),
        "--base origin/main (ref, а не SHA)": dict(good, cmd=f"{NARROW_FULL} --affected --base origin/main"),
        "--base короткий SHA": dict(good, cmd=f"{NARROW_FULL} --affected --base {S[:12]}"),
        "--base=SHA одним словом": dict(good, cmd=f"{NARROW_FULL} --affected --base={S}"),
        "--base SHA заглавными": dict(good, cmd=f"{NARROW_FULL} --affected --base {S.upper()}"),
        "ещё --only": dict(good, cmd=f"{NARROW_FULL} --affected --base {S} --only guard/test_x.py"),
        "без плагина project-tools": dict(good, cmd=f"{NARROW_FULL[:-len(' plugins/project-tools')]} --affected "
                                                     f"--base {S}"),
        "&& true после": dict(good, cmd=f"{NARROW_FULL} --affected --base {S} && true"),
        "кавычка не закрыта": dict(good, cmd=f"{NARROW_FULL} --affected --base {S} '"),
        "files пустой": dict(good, files=[]),
        "files нет": {k: v for k, v in good.items() if k != "files"},
        "files строкой": dict(good, files="guard/test_merge_gate.py"),
        "files с числом": dict(good, files=["guard/test_merge_gate.py", 1]),
        "map нет": {k: v for k, v in good.items() if k != "map"},
        "map короткий": dict(good, map=NARROW_MAP_HASH[:63]),
        "map заглавными": dict(good, map=NARROW_MAP_HASH.upper()),
        "map не строка": dict(good, map=1),
        "cmd не строка": dict(good, cmd=None),
        "не словарь": [good],
    }
    for name, r in bad.items():
        check(f"narrow_tests_record: {name} → None", mg.narrow_tests_record(repo, r) is None,
              mg.narrow_tests_record(repo, r))
    check("narrow_tests_record: репозиторий без FULL_TESTS → None", mg.narrow_tests_record("latark/tg-read", good) is None)
    check("narrow_tests_record: полный набор — не узкая запись",
          mg.narrow_tests_record(repo, dict(full_rec(repo, H), files=["a"], map=NARROW_MAP_HASH)) is None)
    check("full_tests_record: узкая запись — не полный набор", mg.full_tests_record(repo, good) is False)
    check("narrow_map_path: карта рядом с run-tests.py FULL_TESTS", mg.narrow_map_path(repo) == NARROW_MAP,
          mg.narrow_map_path(repo))
    check("narrow_map_path: репозиторий без FULL_TESTS → None", mg.narrow_map_path("latark/tg-read") is None)

    def np(sha=H, base_oid=S, base=S, mp=NARROW_MAP_HASH, cwd=kit):
        return mg._narrow_problem(cwd, repo, sha, base_oid, base, mp)

    check("_narrow_problem: база = merge-base, карта из дерева head → None", np() is None, np())
    check("_narrow_problem: main ушёл вперёд (base PR — M), база — прежняя merge-base → None",
          np(base_oid=m["M"]) is None, np(base_oid=m["M"]))
    for name, kw, want in (
            ("база — коммит другой ветки, а не merge-base", dict(base=m["X"]), "узкий набор посчитан от"),
            ("база — сам head", dict(base=H), "узкий набор посчитан от"),
            ("база — вершина main, а merge-base старше", dict(base_oid=m["M"], base=m["M"]), "узкий набор посчитан от"),
            ("карта в записи не та", dict(mp="0" * 64), "карта в записи не та"),
            ("карта в дереве head другая", dict(sha=m["H2"]), "карта в записи не та"),
            ("карты нет в дереве head", dict(sha=m["Hn"]), "нет в дереве head"),
            ("head нет в git папки", dict(sha="d" * 40), "коммита head"),
            ("base PR нет в git папки", dict(base_oid="e" * 40), "коммита base PR"),
            ("base PR пустой", dict(base_oid=""), "коммита base PR"),
            ("папка слияния — не клон agent-kit", dict(cwd=h.j("projects/tg-read")), "не клон"),
            ("перекрёстные слияния: merge-base не одна", dict(sha=m["CA"], base_oid=m["CB"], base=m["A"]), "не одна")):
        got = np(**kw) or ""
        check(f"_narrow_problem: {name} → «{want}»", want in got, got)
    full = mg.FULL_TESTS["agent-kit"]
    mg.FULL_TESTS["agent-kit"] = "pytest"
    try:
        got = np() or ""
        check("_narrow_problem: у FULL_TESTS нет run-tests.py — карты нет → отказ", "affected-map.json нет" in got, got)
    finally:
        mg.FULL_TESTS["agent-kit"] = full

    def bp(recs, narrow=kit, base_oid=S, sha=H):
        mg.read_records = lambda: recs
        return mg._billing_problem(repo, 7, sha, narrow, base_oid)

    why, notes = bp([good])
    check("_billing_problem: PR вне ядра, узкая запись годится → пропуск со строкой «узкий прогон»",
          why is None and len(notes) == 1 and "засчитан местный узкий прогон" in notes[0] and "файлов 2" in notes[0],
          (why, notes))
    why, notes = bp([good], narrow=None)
    check("_billing_problem: без папки слияния (narrow None) узкая запись не сверить → отказ, команда FULL_TESTS",
          bool(why) and "задевает ядро" not in why and "pantheon review test -- heavy" in why and not notes, why)
    why, _ = bp([dict(good, map="0" * 64)])
    check("_billing_problem: узкая запись с чужой картой → отказ с причиной и подсказкой outside --affected",
          bool(why) and "Узкая запись есть, но не засчитана: карта в записи не та" in why
          and "pantheon outside test --affected --wait 590" in why, why)
    why, _ = bp([narrow_rec(m["X"], S)])
    check("_billing_problem: узкая запись на другом head → отказ (не на этом SHA), подсказка outside --affected",
          bool(why) and "не засчитана" not in why and "pantheon outside test --affected" in why, why)
    why, _ = bp([narrow_rec(H, S, repo="latark/tg-read")])
    check("_billing_problem: узкая запись другого репозитория → отказ", bool(why) and "не засчитана" not in why, why)
    why, notes = bp([dict(good, map="0" * 64), good])
    check("_billing_problem: одна узкая не годится, другая годится → пропуск", why is None and notes, (why, notes))
    why, notes = bp([full_rec(repo, H)], narrow=None)
    check("_billing_problem: полный набор без папки слияния → пропуск, как раньше",
          why is None and "запись полного набора" in notes[0], (why, notes))
    why, _ = bp([])
    check("_billing_problem: записей нет, PR вне ядра → подсказка outside --affected без «не засчитана»",
          bool(why) and "pantheon outside test --affected" in why and "не засчитана" not in why, why)
    why, _ = bp([], narrow=None)
    check("_billing_problem: записей нет, без папки слияния → без подсказки --affected", bool(why) and "--affected" not in why, why)
    why, _ = bp([narrow_rec(H, m["X"])], base_oid=m["M"])
    check("_billing_problem: база записи не merge-base → отказ «посчитан от» и «git fetch»",
          bool(why) and "узкий набор посчитан от" in why and "git fetch" in why, why)


def _delta_problem_checks(mg):
    """metis-0784: delta_problem напрямую — предел строк, сумма по файлам, двоичные, файлы шлюза в любом написании, ядро."""
    dp = mg.delta_problem
    check("delta_problem: пустая дельта → None", dp([]) is None)
    check("delta_problem: дельту не посчитали (None) → отказ", "не посчитать" in (dp(None) or ""))
    check("delta_problem: 200 строк → None", dp([("a.py", 150, 50)]) is None)
    check("delta_problem: 201 строка (добавлено + удалено) → отказ", "201 строк" in (dp([("a.py", 150, 51)]) or ""))
    check("delta_problem: строки по файлам складываются", "201 строк" in (dp([("a.py", 200, 0), ("b.py", 0, 1)]) or ""))
    check("delta_problem: двоичный файл → отказ", "двоичный" in (dp([("a.bin", None, None)]) or ""))
    for p in ("plugins/guard/hooks/merge_gate.py", "./plugins//guard/hooks/../hooks/merge_gate.py",
              "Plugins/Guard/Hooks/Merge_Gate.py", "plugins/pantheon/lib/merge.py", "plugins/guard/hooks/guard_rules.py",
              "plugins/pantheon/lib/review_rules.py"):
        check(f"delta_problem: файл шлюза {p} → отказ", "файл шлюза" in (dp([(p, 1, 0)]) or ""))
    check("delta_problem: ядро, но не файл шлюза — правило тестов пускает", dp([("plugins/guard/x.py", 1, 0)]) is None)
    core = lambda p: p.startswith("plugins/guard/")
    check("delta_problem: с core — ядро → отказ «ядро»", "ядро" in (dp([("Plugins/Guard/x.py", 1, 0)], core) or ""))
    check("delta_problem: с core — вне ядра → None", dp([("README.md", 1, 0)], core) is None)


def t_delta_gate_unit(h):
    """metis-0784: delta_problem напрямую; _narrow_problem и _billing_problem засчитывают узкую запись от прошлого head
    (дельта поверх него), если он — предок head, на нём запись полного набора или годная узкая (цепочка до
    DELTA_DEPTH), а дельта не задевает файлы шлюза, без двоичных и не длиннее DELTA_MAX_LINES строк."""
    mg = _load_merge_gate("merge_gate_delta_unit")
    m, kit, repo = narrow_history(h), h.j("projects/agent-kit"), "latark/agent-kit"
    S, H = m["S"], m["H"]
    F = lambda b: ("100644", b)
    D = plumb(kit, [H], {"x.py": F(b"x = 2\n")}, "мелкая правка")
    D2 = plumb(kit, [D], {"e.py": F(b"e\n")}, "ещё правка")
    D3 = plumb(kit, [D2], {"f.py": F(b"f\n")}, "третья правка")
    Dg = plumb(kit, [H], {"plugins/guard/hooks/merge_gate.py": F(b"g\n")}, "правка шлюза")
    Dc = plumb(kit, [H], {"plugins/guard/x.py": F(b"g\n")}, "ядро, но не файл шлюза")
    D200 = plumb(kit, [H], {"big.py": F(b"a\n" * 198)}, "198 строк + 2 строки x.py = 200")
    D200 = plumb(kit, [D200], {"x.py": F(b"x = 3\n")}, "x.py")
    D201 = plumb(kit, [H], {"big.py": F(b"a\n" * 201)}, "201 строка")
    Db = plumb(kit, [H], {"b.bin": F(b"\0\1\2")}, "двоичный")
    Dn = plumb(kit, [H], {"x.py": None, "x2.py": F(b"x = 1\n")}, "переименование x.py → x2.py")
    Hr = plumb(kit, [m["M"]], {NARROW_MAP: F(NARROW_MAP_BYTES), "x.py": F(b"x = 1\n")}, "head после rebase на M")
    Dr = plumb(kit, [Hr], {"x.py": F(b"x = 2\n")}, "правка после rebase")

    _delta_problem_checks(mg)

    gd = mg._carry_git(kit, repo, S)[0]
    check("_numstat: строки по файлу", mg._numstat(gd, H, D) == [("x.py", 1, 1)], mg._numstat(gd, H, D))
    check("_numstat: двоичный файл — числа None", mg._numstat(gd, H, Db) == [("b.bin", None, None)],
          mg._numstat(gd, H, Db))
    check("_numstat: сбой git (нет коммита) → None", mg._numstat(gd, H, "d" * 40) is None)
    check("_rename_problem: правка без переименования → None", mg._rename_problem(gd, H, D) is None)
    check("_rename_problem: переименование → DELTA_RENAME", mg._rename_problem(gd, H, Dn) == mg.DELTA_RENAME)
    check("_rename_problem: сбой → «не посчитать»", "не посчитать" in (mg._rename_problem(gd, H, "d" * 40) or ""))

    full = full_rec(repo, H)

    def np(sha=D, base=H, tests=(full,), mp=NARROW_MAP_HASH, depth=None):
        kw = {} if depth is None else {"depth": depth}
        return mg._narrow_problem(kit, repo, sha, S, base, mp, None if tests is None else list(tests), **kw)

    check("_narrow_problem: дельта от H с полной записью на H → None", np() is None, np())
    check("_narrow_problem: дельта 200 строк → None", np(sha=D200) is None, np(sha=D200))
    check("_narrow_problem: на H годная узкая запись (от merge-base) → None", np(tests=[narrow_rec(H, S)]) is None,
          np(tests=[narrow_rec(H, S)]))
    check("_narrow_problem: цепочка H → D → D2 → None", np(sha=D2, base=D, tests=[full, narrow_rec(D, H)]) is None,
          np(sha=D2, base=D, tests=[full, narrow_rec(D, H)]))
    calls, carry_git = [], mg._carry_git
    mg._carry_git = lambda *a: calls.append(a) or carry_git(*a)
    try:
        got = np(sha=D2, base=D, tests=[full, narrow_rec(D, H)])
    finally:
        mg._carry_git = carry_git
    check("_narrow_problem: цепочка — git папки ищется один раз, а не на каждом звене (Д3 argus #420)",
          got is None and len(calls) == 1, (got, len(calls)))
    chain = [full, narrow_rec(D, H), narrow_rec(D2, D)]
    check("_narrow_problem: цепочка из трёх звеньев при depth 3 → None", np(sha=D3, base=D2, tests=chain, depth=3) is None,
          np(sha=D3, base=D2, tests=chain, depth=3))
    for name, kw, want in (
            ("без записей журнала — правило дельты не действует", dict(tests=None), "узкий набор посчитан от"),
            ("на прошлом head записи нет", dict(tests=()), "нет записи тестов"),
            ("на прошлом head узкая запись не годна", dict(tests=[narrow_rec(H, m["X"])]), "узкий набор посчитан от"),
            ("цепочка длиннее depth", dict(sha=D3, base=D2, tests=chain, depth=2), "цепочка дельт длиннее"),
            ("дельта задевает файл шлюза", dict(sha=Dg), "файл шлюза"),
            ("дельта 201 строка", dict(sha=D201), "201 строк"),
            ("в дельте двоичный файл", dict(sha=Db), "двоичный"),
            ("в дельте переименование (Д1 argus #420)", dict(sha=Dn), "переименование"),
            ("база не предок head (rebase между кругами)", dict(sha=Dr), "не предок"),
            ("база — другая ветка", dict(base=m["X"]), "не предок"),
            ("карта в записи не та", dict(mp="0" * 64), "карта в записи не та")):
        got = np(**kw) or ""
        check(f"_narrow_problem: {name} → «{want}»", want in got, got)
    check("_narrow_problem: ядро, но не файл шлюза — тесты дельтой засчитываются", np(sha=Dc) is None, np(sha=Dc))

    def bp(recs, sha=D):
        mg.read_records = lambda: recs
        return mg._billing_problem(repo, 7, sha, kit, S)

    why, notes = bp([narrow_rec(D, H), full])
    check("_billing_problem: узкая от прошлого head с полной записью на нём → пропуск «узкий прогон»",
          why is None and notes and "узкий прогон" in notes[0], (why, notes))
    why, _ = bp([narrow_rec(D, H), full_rec("latark/tg-read", H)])
    check("_billing_problem: полная запись на прошлом head другого репозитория — не в счёт",
          bool(why) and "нет записи тестов" in why, why)
    why, _ = bp([narrow_rec(D, H)])
    check("_billing_problem: на прошлом head записи нет → отказ с подсказкой --base <тот head>",
          bool(why) and "как дельта прошлого head не засчитан" in why and "--affected --base <тот head>" in why, why)


def t_narrow_gate(h):
    """metis-0734: шлюз на запасном пути (CI без минут, ответ PR #222) пускает роль по узкой записи
    `pantheon outside test --affected` на head PR вне ядра; ядро (и с Touch ID), другой head, база не merge-base с
    main, чужая карта, путь без роли — отказ."""
    m, kit = narrow_history(h), "projects/agent-kit"
    H, S = m["H"], m["S"]
    cmd = f"gh pr merge 7 --match-head-commit {H}"
    runs = _saved(222, "runs")

    def view(files):
        h.runs["agent-kit"] = _runs_on(runs, H, 222)
        h.gh(files, head=H)
        h.ci(_saved(222)["statusCheckRollup"], name="agent-kit", head=H, baseRefOid=m["M"], baseRefName="main")
        _notes_on(h, runs)

    view(["README.md", "plugins/pantheon/lib/tasks.py"])
    h.seed(rec("accept", "latark/agent-kit", 7, H))
    h.seed(narrow_rec(m["X"], S))
    merge_case("вне ядра, узкая запись только на другом head — отказ «нет записи тестов»", h.pre(cmd, pdir=kit), False,
               "нет записи тестов на latark/agent-kit@")
    h.seed(rec("tests", "latark/agent-kit", None, H, "dev-opus"))
    merge_case("вне ядра, на head запись не полного и не узкого набора — отказ с подсказкой outside --affected",
               h.pre(cmd, pdir=kit), False, "Годится и узкий прогон: из корня чистой копии на "
               "этом коммите `pantheon outside test --affected --wait 590`")
    h.seed(narrow_rec(H, m["X"]))
    merge_case("вне ядра, база записи — не merge-base head и main — отказ", h.pre(cmd, pdir=kit), False,
               "узкий набор посчитан от")
    h.seed(narrow_rec(H, S, mp="1" * 64))
    merge_case("вне ядра, карта в записи не та — отказ", h.pre(cmd, pdir=kit), False, "карта в записи не та")
    shutil.rmtree(os.path.dirname(h.records))
    h.seed(rec("accept", "latark/agent-kit", 7, H), narrow_rec(H, S))
    r = _hook_out(h, cmd, kit)
    msg = json.loads(r.stdout).get("systemMessage", "") if r.stdout.strip() else ""
    check("вне ядра, узкая запись на head от merge-base, карта head — пропуск со строкой «узкий прогон»",
          decision(r)[0] == "allow" and "засчитан местный узкий прогон" in msg, r.stdout + r.stderr)
    view(["README.md", "plugins/guard/hooks/merge_gate.py"])
    h.approve(f"{ts()} merge-approve latark/agent-kit#7 {H}")
    merge_case("ядро с Touch ID, узкая запись на head от merge-base — проходит (metis-1050: полный набор ночью)",
               h.pre(cmd, pdir=kit), True)
    h.seed(full_rec("latark/agent-kit", H))
    merge_case("ядро с Touch ID, есть и полный набор — пропуск", h.pre(cmd, pdir=kit), True)
    shutil.rmtree(os.path.dirname(h.records))
    view(["README.md", "plugins/pantheon/lib/tasks.py"])
    h.seed(rec("accept", "latark/agent-kit", 7, H), narrow_rec(H, S))
    merge_case("без роли (путь владельца) узкая запись не в счёт — отказ", h.pre(cmd, role=None, pdir=kit), False,
               "не запускался: лимит минут")


def t_batch_full(h):
    """metis-1050 (решение владельца 09.11; было metis-0758): PR пачки (ветка batch/<story>) проверяется как любой
    другой — при зелёном CI хватает любой записи tests на head, полного набора не требуется (он идёт ночью на main)."""
    kit, sha = "projects/agent-kit", h.sha["agent-kit"]
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    h.seed(rec("tests", "latark/agent-kit", None, sha, "dev-opus"), rec("accept", "latark/agent-kit", 7, sha))
    merge_case("пачка: ветка не batch/, CI зелёный, запись не полного набора — проходит", h.pre(cmd, pdir=kit), True)
    h.ci([AFFECTED, TRACES], name="agent-kit", headRefName="batch/metis-0754")
    merge_case("пачка: batch/, CI зелёный, запись не полного набора — проходит (metis-1050)", h.pre(cmd, pdir=kit),
               True)
    mg = _load_merge_gate("merge_gate_batch")
    check("metis-1050: правила «пачке — только полный набор» больше нет",
          not hasattr(mg, "batch_tests_problem") and not hasattr(mg, "BATCH_BRANCH"))


CASES = [t_narrow_record, t_batch_full, t_narrow_gate_unit, t_delta_gate_unit, t_narrow_gate]


if __name__ == "__main__":
    sys.exit(main(CASES))
