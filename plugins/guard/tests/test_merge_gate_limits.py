#!/usr/bin/env python3
"""Запор слияния guard, часть «limits»: сроки и пределы: сроки тестов и боя, таймаут git, бюджет сверки, типы манифеста, FULL_TESTS, слияние владельцем через API.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py; разрез metis-1119.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_limits.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403


def t_test_floors(h):
    """Сроки хука в тесте (metis-0719): окружение хука из теста поднимает DEADLINE и timeout подпроцессов через
    загрузчик _cached_main; без переменных (пусто, не число) — сроки как в бою."""
    script = h.j("floors.py")
    with open(script, "w") as fh:
        fh.write("import signal, subprocess\n"
                 "signal.setitimer(signal.ITIMER_REAL, 8)\n"
                 "left = signal.getitimer(signal.ITIMER_REAL)[0]\n"
                 "signal.setitimer(signal.ITIMER_REAL, 0)\n"
                 "try:\n"
                 "    subprocess.run(['sleep', '2'], timeout=0.5)\n"
                 "    sub = 'ждал'\n"
                 "except subprocess.TimeoutExpired:\n"
                 "    sub = 'таймаут'\n"
                 "print(f'{left:.0f} {sub}')\n")

    def run(env):
        return subprocess.run([sys.executable, "-I", CACHED, script], capture_output=True, text=True, env=env,
                              timeout=SUB_TIMEOUT).stdout.split()

    got = run(h.env("projects/tg-read"))
    check(f"сроки хука в тесте: DEADLINE не меньше {HOOK_DEADLINE} с, timeout не меньше {HOOK_SUB_TIMEOUT} с",
          got == [str(HOOK_DEADLINE), "ждал"], got)
    got = run(dict(h.env("projects/tg-read"), GUARD_TEST_DEADLINE="", GUARD_TEST_SUB_TIMEOUT="x"))
    check("сроки хука в тесте: без переменных — DEADLINE 8 с и timeout как в коде", got == ["8", "таймаут"], got)
    # merge_gate в процессе теста (r4, carry): git дольше боевого timeout=3 у _git_bytes — ответ, а не None
    slow = h.j("slowgit")
    os.makedirs(slow, exist_ok=True)
    with open(os.path.join(slow, "git"), "w") as fh:
        fh.write("#!/bin/sh\nsleep 3.5\necho medlenno\n")
    os.chmod(os.path.join(slow, "git"), 0o755)
    mg = _load_merge_gate("merge_gate_floors")
    with _Env(PATH=slow + os.pathsep + os.environ["PATH"]):
        got = mg._git_bytes(h.root, "rev-parse")
    check(f"сроки в процессе теста: git в _git_bytes ждёт до {HOOK_SUB_TIMEOUT} с, а не 3", got == b"medlenno\n", got)



def t_carry_budget(h):
    """Бюджет сверки (metis-0696): без GUARD_TEST_CARRY_BUDGET — боевые 4 с; мусор, ноль, меньше 4 — тоже 4; больше —
    поднят, но не выше CARRY_BUDGET_MAX. _Prints берёт бюджет из переменной: через 10 с сверки при 15 — считает дальше,
    без переменной — останавливается со словами «дольше 4 с»."""
    mg = _load_merge_gate("merge_gate_budget")
    check("бюджет сверки: боевой CARRY_BUDGET — 4 с, предел — больше 4", mg.CARRY_BUDGET == 4 < mg.CARRY_BUDGET_MAX,
          (mg.CARRY_BUDGET, mg.CARRY_BUDGET_MAX))
    check("бюджет сверки: тест ставит хуку GUARD_TEST_CARRY_BUDGET больше 4 и не выше предела",
          h.env("projects/tg-read").get(mg.CARRY_BUDGET_ENV) == str(HOOK_CARRY_BUDGET)
          and 4 < HOOK_CARRY_BUDGET <= mg.CARRY_BUDGET_MAX, HOOK_CARRY_BUDGET)
    for raw, want in ((None, 4), ("", 4), (" ", 4), ("x", 4), ("15с", 4), ("nan", 4), ("0", 4), ("-20", 4),
                      ("3", 4), ("4", 4), ("15", 15), ("4.5", 4.5), ("1e9", mg.CARRY_BUDGET_MAX),
                      ("inf", mg.CARRY_BUDGET_MAX)):
        with _Env(GUARD_TEST_CARRY_BUDGET=raw):
            got = mg._carry_budget()
        check(f"бюджет сверки: GUARD_TEST_CARRY_BUDGET={raw!r} — {want} с", got == want, got)
    saved = mg._fingerprint
    mg._fingerprint = lambda gd, base, head: ("отпечаток", "")
    try:
        for raw, want in (("15", ("отпечаток", "")), (None, None)):
            with _Env(GUARD_TEST_CARRY_BUDGET=raw):
                p = mg._Prints(h.root, "latark/agent-kit", OLD, [], lambda: {})
            p.ready, p.gd, p.base, p.t0 = True, h.root, BASE, time.monotonic() - 10
            got = p(OLD)
            check(f"бюджет сверки: _Prints, 10 с прошло, переменная {raw!r} — {want!r}", got == want, (got, p.why))
            if raw is None:
                check("бюджет сверки: без переменной — причина «дольше 4 с»", any("дольше 4 с" in w for w in p.why),
                      p.why)
        # metis-0974: бюджет — от конца запросов gh. gh pr view и вершина base шли 10 с — сверка всё равно считает;
        # вершина спрошена через память шлюза (tips), её же возьмёт сборка окон
        keep = mg._base_tip, mg._carry_git
        box = []

        def slow_tip(repo, branch, memo=None):
            box[0].t0 = time.monotonic() - 10   # gh ответил через 10 с после создания _Prints
            memo[(repo, branch)] = BASE
            return BASE
        mg._base_tip, mg._carry_git = slow_tip, lambda cwd, repo, base: (h.root, None)
        try:
            tips = {}
            p = mg._Prints(h.root, "latark/agent-kit", OLD, [], lambda: {"baseRefOid": BASE, "baseRefName": "main"},
                           tips)
            box.append(p)
            got = p(OLD)
            check("0974: gh шёл 10 с — бюджет сверки от конца gh, отпечаток посчитан", got == ("отпечаток", ""),
                  (got, p.why))
            check("0974: вершина base — в памяти шлюза", tips == {("latark/agent-kit", "main"): BASE}, tips)
        finally:
            mg._base_tip, mg._carry_git = keep
    finally:
        mg._fingerprint = saved


def prod_timeouts(sources):
    """Боевые сроки по тексту кода (AST), без ожидания и без GUARD_TEST_* (metis-0730). sources: {имя файла: текст}.
    → список нарушений. Правила: DEADLINE в guard.py, guard_rules.py, taint.py ровно 8 с; в merge_gate.py каждый
    timeout= у subprocess.run — вызов _git_timeout() (местный git, metis-0787) или GH_TIMEOUT, GH_TIMEOUT = 6,
    GIT_TIMEOUT = 3, GIT_TIMEOUT_MAX = 6; все они меньше DEADLINE, иначе хук гаснет по сроку раньше, чем успевает
    отказать сам. Мало найденных мест — тоже нарушение (разбор не пустой)."""
    import ast
    bad = []

    def consts(tree):
        return {n.targets[0].id: n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                and isinstance(n.value, ast.Constant)}

    for name in ("guard.py", "guard_rules.py", "taint.py"):
        got = consts(ast.parse(sources[name])).get("DEADLINE")
        if got != 8:
            bad.append(f"{name}: DEADLINE = {got!r}, боевой 8")
    tree = ast.parse(sources["merge_gate.py"])
    gh = consts(tree).get("GH_TIMEOUT")
    if gh != 6:
        bad.append(f"merge_gate.py: GH_TIMEOUT = {gh!r}, боевой 6")
    for k, want in (("GIT_TIMEOUT", 3), ("GIT_TIMEOUT_MAX", 6)):
        got = consts(tree).get(k)
        if got != want:
            bad.append(f"merge_gate.py: {k} = {got!r}, боевой {want}")
    margin = consts(tree).get("GIT_MARGIN")
    if not isinstance(margin, (int, float)) or margin < 1:
        bad.append(f"merge_gate.py: GIT_MARGIN = {margin!r}, нужен запас не меньше 1 с до срока хука")
    gits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "run" \
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess":
            for kw in n.keywords:
                if kw.arg != "timeout":
                    continue
                v = kw.value
                if isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "_git_timeout" \
                        and not v.args and not v.keywords:
                    gits.append(n.lineno)
                elif not (isinstance(v, ast.Name) and v.id == "GH_TIMEOUT"):
                    bad.append(f"merge_gate.py:{n.lineno}: timeout не _git_timeout() и не GH_TIMEOUT")
    if len(gits) < 3:
        bad.append(f"merge_gate.py: timeout=_git_timeout() у subprocess.run {len(gits)}, ждали 3")
    return bad


def t_prod_timeouts(h):
    """Боевые сроки хука (metis-0730, долг argus #281): тесты идут с поднятыми GUARD_TEST_DEADLINE и
    GUARD_TEST_SUB_TIMEOUT, поэтому timeout 4–19 с вместо боевых 3 с и DEADLINE 15 вместо 8 они не заметили бы.
    Читаем значения из кода, ничего не ждём. Мутанты — на копиях текста в самом случае."""
    hooks = os.path.dirname(GUARD)
    sources = {}
    for n in ("guard.py", "guard_rules.py", "taint.py", "merge_gate.py"):
        with open(os.path.join(hooks, n), encoding="utf-8") as fh:
            sources[n] = fh.read()
    got = prod_timeouts(sources)
    check("боевые сроки: DEADLINE 8 с, timeout git 3–6 с, GH_TIMEOUT 6 с — как в коде", got == [], got)
    check("боевые сроки: поднятые сроки теста выше боевых (иначе поднимать нечего)",
          HOOK_DEADLINE > 8 and HOOK_SUB_TIMEOUT > 3, (HOOK_DEADLINE, HOOK_SUB_TIMEOUT))
    for what, name, old, new in (
            ("timeout git → 15", "merge_gate.py", "timeout=_git_timeout(),\n                           env=_git_env())",
             "timeout=15,\n                           env=_git_env())"),
            ("timeout _git_bytes → 20", "merge_gate.py", "capture_output=True, timeout=_git_timeout(), env=env)",
             "capture_output=True, timeout=20, env=env)"),
            ("GIT_TIMEOUT 3 → 15", "merge_gate.py", "GIT_TIMEOUT = 3 ", "GIT_TIMEOUT = 15 "),
            ("GIT_TIMEOUT_MAX 6 → 9", "merge_gate.py", "GIT_TIMEOUT_MAX = 6 ", "GIT_TIMEOUT_MAX = 9 "),
            ("GIT_MARGIN 1.5 → 0", "merge_gate.py", "GIT_MARGIN = 1.5 ", "GIT_MARGIN = 0 "),
            ("GH_TIMEOUT 6 → 9", "merge_gate.py", "GH_TIMEOUT = 6", "GH_TIMEOUT = 9"),
            ("DEADLINE guard.py 8 → 15", "guard.py", "DEADLINE = 8 ", "DEADLINE = 15 "),
            ("DEADLINE guard_rules.py 8 → 15", "guard_rules.py", "DEADLINE = 8 ", "DEADLINE = 15 "),
            ("DEADLINE taint.py 8 → 15", "taint.py", "DEADLINE = 8 ", "DEADLINE = 15 ")):
        if old not in sources[name]:
            check(f"боевые сроки, мутант «{what}»: место найдено в {name}", False, old)
            continue
        mutated = dict(sources, **{name: sources[name].replace(old, new, 1)})
        check(f"боевые сроки, мутант «{what}» убит", prod_timeouts(mutated) != [], what)


def t_git_timeout(h):
    """metis-0787: местный git шлюза ждёт по остатку срока хука (от GIT_TIMEOUT 3 с до GIT_TIMEOUT_MAX 6 с, запас
    GIT_MARGIN), а не 3 с всегда: под нагрузкой Mac шлюз ложно отказывал «git не ответил». Без таймера — 3 с."""
    import signal
    mg = _load_merge_gate("merge_gate_git_timeout")
    seen = []

    class Rec:
        SubprocessError, TimeoutExpired = subprocess.SubprocessError, subprocess.TimeoutExpired

        @staticmethod
        def run(argv, **kw):
            seen.append(kw.get("timeout"))
            return subprocess.CompletedProcess(argv, 0, "" if kw.get("text") else b"", "")

    mg.subprocess = Rec
    old = signal.signal(signal.SIGALRM, lambda *a: None)
    try:
        signal.setitimer(signal.ITIMER_REAL, 0)
        check("git: без таймера хука — 3 с", mg._git_timeout() == 3, mg._git_timeout())
        # metis-0975: остаток меньше 3 с — git ждёт меньше 3 с и не переживает срок хука; меньше запаса — сразу гаснет
        for left, want in ((7.5, 6), (6.5, 5), (5.5, 4), (4, 2.5), (3, 1.5), (1.6, 0.1), (1, 0.05), (60, 6)):
            signal.setitimer(signal.ITIMER_REAL, left)
            got = mg._git_timeout()
            check(f"git: до срока хука {left} с — ждёт {want} с", abs(got - want) < 0.3 and got < left, got)
        signal.setitimer(signal.ITIMER_REAL, 1)
        mg._git_bytes(h.root, "status")
        check("0975: до срока хука 1 с — git ждёт не дольше 0.05 с, а не 3", seen and seen[-1] <= 0.05, seen)
        seen.clear()
        signal.setitimer(signal.ITIMER_REAL, 7)
        mg._git(h.root, "status")
        mg._gh_resolved(h.root)
        mg._git_bytes(h.root, "status")
        check("git: _git, _gh_resolved и _git_bytes ждут по остатку срока (5.5 с при 7 с)",
              len(seen) == 3 and all(5 < t <= 5.5 for t in seen), seen)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def t_manifest_types(h):
    """metis-0417 (argus-117b7): plugin.json сверяется по типам значений — true → 1, 1 → 1.0, "1" → 1 не «только
    version»; симлинк вместо файла — в t_carry_r4 (typechange, отпечатка нет)."""
    mg = _load_merge_gate("merge_gate_manifest_types")
    canon = lambda d: mg._manifest_canon(json.dumps(d).encode())
    base = {"name": "pantheon", "version": "0.11.1"}
    check("plugin.json: другой номер версии — тот же канон",
          canon(dict(base, x=True)) == canon(dict(base, x=True, version="0.11.2")))
    for a, b in ((True, 1), (False, 0), (1, 1.0), ("1", 1), (None, False), ([1], [True])):
        check(f"plugin.json: {a!r} → {b!r} — канон другой", canon(dict(base, x=a)) != canon(dict(base, x=b)), (a, b))


def t_full_tests_verify(h):
    """Долг argus #248: команда полного набора FULL_TESTS["agent-kit"] (её засчитывает запасной путь) и первая строка
    .pantheon-verify репозитория (её гоняет `pantheon outside test`) — один и тот же набор: без `heavy` и комментариев
    слова совпадают, и full_tests_record засчитывает запись прохода с этой строкой."""
    mg = _load_merge_gate("merge_gate_full_verify")
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    with open(os.path.join(root, ".pantheon-verify"), encoding="utf-8") as fh:
        line = next((x.strip() for x in fh if x.strip() and not x.lstrip().startswith("#")), "")
    want = mg.FULL_TESTS["agent-kit"].split()
    got = line.split()
    check(".pantheon-verify и FULL_TESTS: один набор (без heavy)",
          [w for w in got if w != "heavy"] == [w for w in want if w != "heavy"], (line, want))
    check(".pantheon-verify: запись прохода с его строкой засчитывается full_tests_record",
          mg.full_tests_record("latark/agent-kit", {"cmd": line + "  # .pantheon-verify ветки (HEAD)"}), line)


def t_owner_api_merge(h):
    """metis-0663: сессия без роли — слияние через `gh api … PUT repos/O/R/pulls/N/merge` (-X PUT, --method PUT,
    --method=PUT, флаг до api, полный адрес, плейсхолдеры {owner}/{repo}, поле sha) проходит ту же проверку CI, что
    gh pr merge. Фоновая проверка 02.11 — одно правило fail closed для записи gh api: невычислимое слово, склеенный или
    незнакомый флаг (`-XPUT`, `-fsha=`), `..` в адресе, адрес с pulls и merge не ровно в форме (полный адрес — только
    https://api.github.com/, --hostname — только github.com), graphql не ровно
    `graphql`, graphql из файла, мутация слияния — отказ. GET того же адреса и другие gh api — не судятся. Слово merge
    ищется после разбора bash (`gh pr mer''ge`), алиас слияния — отказ. Круг 2 (argus #257): репозиторий — из адреса,
    а не из папки (Б1); GET с невычислимым словом не судится, merge в --jq и соседней команде не в счёт (Д1);
    невычислимое значение флага — отказ только у слияния и graphql (Д2); записи в pulls/* без merge, имя репозитория и
    ветки со словами pulls и merge — не слияние (Д3, Д5); связка `-iX PUT` — запись (metis-0681)."""
    kit, sha = "projects/agent-kit", h.sha["agent-kit"]
    owner = dict(role=None, pdir=kit)
    nine = [dict(AFFECTED, prs=(9,)), dict(TRACES, prs=(9,))]
    red = [dict(nine[0], conclusion="FAILURE"), nine[1]]
    forms = (("-X PUT", "gh api -X PUT repos/latark/agent-kit/pulls/9/merge"),
             ("--method PUT после адреса", "gh api repos/latark/agent-kit/pulls/9/merge --method PUT"),
             ("--method=put", "gh api --method=put /repos/latark/agent-kit/pulls/9/merge"),
             ("-X PUT до api", "gh -X PUT api repos/latark/agent-kit/pulls/9/merge"),
             ("поле без -X (POST)", "gh api repos/latark/agent-kit/pulls/9/merge -f merge_method=squash"),
             ("кавычки внутри слова", "gh api -X PUT 'repos/latark/agent-kit/pulls/9/mer'ge"),
             ("полный путь к gh", "/usr/local/bin/gh api -X PUT repos/latark/agent-kit/pulls/9/merge"),
             ("полный адрес https://api.github.com/…", "gh api -X PUT https://api.github.com/repos/latark/agent-kit/pulls/9/merge"),
             ("плейсхолдеры {owner}/{repo}", "gh api -X PUT 'repos/{owner}/{repo}/pulls/9/merge'"),
             ("--hostname github.com", "gh api --hostname github.com -X PUT repos/latark/agent-kit/pulls/9/merge"),
             ("поле sha", f"gh api -X PUT repos/latark/agent-kit/pulls/9/merge -f sha={sha}"),
             ("поле --raw-field=sha=", f"gh api -X PUT repos/latark/agent-kit/pulls/9/merge --raw-field=sha={sha}"),
             ("флаги --paginate, --jq", "gh api --paginate -X PUT repos/latark/agent-kit/pulls/9/merge --jq .merged"),
             ("флаг --allow-escape-sequences", "gh api --allow-escape-sequences -X PUT repos/latark/agent-kit/pulls/9/merge"),
             # адрес сверяется после api_norm — %XX, //, ./
             ("адрес в %XX", "gh api -X PUT repos%2Flatark%2Fagent-kit%2Fpulls%2F9%2F%6Derge"),
             ("адрес с //", "gh api -X PUT repos//latark/agent-kit//pulls/9//merge"),
             ("адрес с ./", "gh api -X PUT ./repos/latark/./agent-kit/pulls/9/./merge"))
    for how, c in forms:
        h.ci(red, name="agent-kit")
        merge_case(f"без роли: gh api {how}, CI красный — отказ", h.pre(c, **owner), False,
                   "gh api …/pulls/N/merge — проверка GitHub tests/affected красная: FAILURE")
        h.ci(nine, name="agent-kit")
        merge_case(f"без роли: gh api {how}, CI зелёный — проходит", h.pre(c, **owner), True)
    h.ci(nine, name="agent-kit")
    base = "gh api -X PUT repos/latark/agent-kit/pulls/9/merge"
    glued = "склеенный или незнакомый"
    for c, how, why in (
            (f"{base} -f sha={'e' * 40}", "поле sha — другой коммит", "PR сейчас на другом коммите"),
            (f"{base} -f sha=abc", "поле sha не SHA", "один SHA из 40 знаков"),
            (f"{base} -F sha=@f", "поле sha из файла -F sha=@f", "один SHA из 40 знаков"),
            (f"{base} --field sha={'e' * 40}", "поле --field sha= — другой коммит", "PR сейчас на другом коммите"),
            (f"{base} -F sha={'e' * 40}", "поле -F sha= — другой коммит", "PR сейчас на другом коммите"),
            (f"{base} --raw-field=sha={'e' * 40}", "поле --raw-field=sha= — другой коммит", "PR сейчас на другом коммите"),
            (f"{base} --field=sha={'e' * 40}", "поле --field=sha= — другой коммит", "PR сейчас на другом коммите"),
            (f"{base} -f sha={sha} -f sha={'e' * 40}", "два поля sha", "один SHA из 40 знаков"),
            ("gh pr $(echo merge) 9", "sub gh из $(…), merge только в сыром тексте", "слово до подкоманды не вычислить"),
            ("gh $SUB mer''ge 9", "sub gh не вычислить, merge только после разбора", "слово до подкоманды не вычислить"),
            # склеенные и незнакомые флаги — отказ (pflag разбирает их иначе, чем шлюз)
            ("gh api -XPUT repos/latark/agent-kit/pulls/9/merge", "-XPUT слитно", glued),
            ("gh api -Xput repos/latark/agent-kit/pulls/9/merge", "-Xput слитно", glued),
            (f"{base} -Fsha={sha}", "-Fsha= слитно", glued),
            (f"{base} -fsha={sha}", "-fsha= слитно", glued),
            ("gh api -X POST repos/latark/agent-kit/issues/7/comments -fX=1", "-fX… склейка не у слияния", glued),
            (f"{base} --some-new-flag", "незнакомый флаг", glued),
            # невычислимое слово в записи — отказ и без слова merge
            (f"{base} -f sha=$SHA", "поле sha — переменная", "слово не вычислить"),
            ("gh api -X PUT repos/latark/agent-kit/pulls/$N/merge", "номер — переменная", "слово не вычислить"),
            ("gh api -X $M repos/latark/agent-kit/pulls/9/merge", "метод — переменная", "слово не вычислить"),
            ("gh api repos/latark/agent-kit/pulls/9/merge $F", "флаг — переменная, запись не видна, merge есть",
             "слово не вычислить"),
            ("gh api -X POST $URL -f a=1", "адрес записи — переменная, merge нет", "слово не вычислить"),
            ("gh api $URL -f a=1", "адрес — переменная, поле (POST), merge нет", "слово не вычислить"),
            ("gh api -X POST -f a=1 -- $URL", "адрес — переменная после --", "слово не вычислить"),
            ("gh -R latark/agent-kit api --method PATCH \"$(cat u)\"", "адрес из $(…), флаг до api", "слово не вычислить"),
            # невычислимое значение флага или лишнее слово — отказ у адреса слияния и graphql (Д2 argus #257)
            (f"{base} -H $H", "значение -H — переменная, адрес слияния", "слово не вычислить"),
            (f"{base} --jq $J", "значение --jq — переменная, адрес слияния", "слово не вычислить"),
            (f"{base} $F", "лишнее слово — переменная, адрес слияния", "слово не вычислить"),
            ("gh api graphql -f query=\"$Q\"", "graphql: запрос — переменная", "слово не вычислить"),
            # невычислимое слово может сдвинуть адрес: известный адрес слияния не первым словом — отказ
            ("gh api $X repos/o/r/pulls/7/merge -X PUT", "первое слово — переменная, за ним адрес слияния",
             "слово не вычислить"),
            ("gh api repos/o/r/issues/1 $X repos/o/r/pulls/7/merge -X PUT", "адрес слияния за переменной",
             "слово не вычислить"),
            ("gh api repos/o/r/issues/1 $X graphql -X POST", "graphql за переменной", "слово не вычислить"),
            # связка коротких флагов с X, f или F — запись (metis-0681), шлюз её не разбирает
            ("gh api -iX PUT repos/latark/agent-kit/pulls/9/merge", "-iX PUT связкой", glued),
            ("gh api -iXPUT repos/latark/agent-kit/pulls/9/merge", "-iXPUT связкой", glued),
            (f"{base} -iF sha={sha}", "-iF sha= связкой", glued),
            # адрес: .., не ровно форма
            ("gh api -X PUT repos/latark/agent-kit/pulls/9/../9/merge", "адрес с ..", "`..` в адресе"),
            ("gh api -X POST repos/latark/agent-kit/issues/7/../comments -f body=x", ".. не у слияния", "`..` в адресе"),
            ("gh api -X PUT repos/latark/agent-kit/pulls/x9/merge", "номер не число", "не число"),
            ("gh api -X PUT 'repos/{owner}/agent-kit/pulls/9/merge'", "плейсхолдер вперемешку", "плейсхолдер"),
            ("gh api -X PUT repositories/123/pulls/9/merge", "адрес repositories/<id>/…/merge", "не в форме"),
            ("gh api -X PUT repos/latark/agent-kit/pulls/9/merged", "…/merged", "не в форме"),
            ("gh api -X PUT 'repos/latark/agent-kit/pulls/9/merge?x=1'", "хвост ?x=1", "не в форме"),
            ("gh api -X PUT myrepos/latark/agent-kit/pulls/9/merge", "repos/ не с начала адреса", "не в форме"),
            # хост: CI сверяется на github.com — полный адрес только https://api.github.com/, --hostname только github.com
            ("gh api -X PUT https://ghe.example/api/v3/repos/latark/agent-kit/pulls/9/merge", "полный адрес GHE /api/v3",
             "не в форме"),
            ("gh api -X PUT https://ghe.example/repos/latark/agent-kit/pulls/9/merge", "полный адрес другого хоста",
             "не в форме"),
            ("gh api -X PUT http://api.github.com/repos/latark/agent-kit/pulls/9/merge", "http://", "не в форме"),
            ("gh api --hostname ghe.example -X PUT repos/latark/agent-kit/pulls/9/merge", "--hostname другой хост",
             "другой хост шлюз не сверяет"),
            ("gh api --hostname=ghe.example -X PUT repos/latark/agent-kit/pulls/9/merge", "--hostname= другой хост",
             "другой хост шлюз не сверяет"),
            ("gh api --hostname github.com --hostname ghe.example -X PUT repos/latark/agent-kit/pulls/9/merge",
             "два --hostname, второй чужой", "--hostname ghe.example"),
            # graphql
            ("gh api graphql -f query='mutation{mergePullRequest(input:{pullRequestId:\"x\"}){clientMutationId}}'",
             "GraphQL mergePullRequest", "GraphQL"),
            ("gh api graphql -f query='mutation{enablePullRequestAutoMerge(input:{pullRequestId:\"x\"}){clientMutationId}}'",
             "GraphQL enablePullRequestAutoMerge", "GraphQL"),
            ("gh api graphql -f query='mutation{enqueuePullRequest(input:{pullRequestId:\"x\"}){clientMutationId}}'",
             "GraphQL enqueuePullRequest (очередь слияния)", "GraphQL"),
            ("gh api graphql -F query='mutation{mergePullRequest(input:{pullRequestId:\"x\"}){clientMutationId}}'",
             "GraphQL mergePullRequest через -F", "GraphQL"),
            ("gh api graphql --raw-field=query='mutation{mergePullRequest(input:{pullRequestId:\"x\"}){clientMutationId}}'",
             "GraphQL mergePullRequest через --raw-field=", "GraphQL"),
            ("gh api graphql -F query=@q.graphql", "graphql: запрос из файла -F query=@", "graphql из файла"),
            ("gh api graphql --field query=@q.graphql", "graphql: запрос из файла --field query=@", "graphql из файла"),
            ("gh api graphql --field=query=@q.graphql", "graphql: запрос из файла --field=query=@", "graphql из файла"),
            ("gh api graphql -f query=x -F variables=@v.json", "graphql: переменные из файла", "graphql из файла"),
            ("gh api graphql --input q.json", "graphql: тело из файла --input", "graphql из файла"),
            ("gh api graphql --input=q.json", "graphql: тело из файла --input=", "graphql из файла"),
            ("gh api /graphql -Fquery=@q.graphql", "graphql: -Fquery=@ слитно", glued),
            ("gh api https://api.github.com/graphql -f query=x", "graphql по полному адресу", "не в форме `graphql`"),
            ("gh api graphql/ -f query=x", "graphql/ со слешем", "не в форме `graphql`"),
            ("gh api %67raphql -f query=x -F q=@f", "graphql в %XX, поле из файла", "graphql из файла"),
            # окружение
            ("GH_REPO=latark/tg-read gh api -X PUT 'repos/{owner}/{repo}/pulls/9/merge'", "GH_REPO= перед gh",
             "без переменных GH_*"),
            (f"cd {h.j(kit)} && gh api -X PUT 'repos/{{owner}}/{{repo}}/pulls/9/merge'", "cd и плейсхолдеры",
             "с cd в команде укажи репозиторий"),
            ("gh alias set m 'pr merge'", "gh alias set со словом merge", "gh alias со словом merge"),
            ("gh alias set --shell m 'gh pr mer''ge \"$1\"'", "gh alias set --shell с merge", "gh alias со словом merge")):
        merge_case(f"без роли: {how} — отказ", h.pre(c, **owner), False, why)
    merge_case("без роли: gh api -X PUT …/merge с GH_HOST в окружении — отказ",
               h.pre(base, extra_env={"GH_HOST": "x"}, **owner), False, "без переменных GH_*")
    h.reset_log()
    for c, how in (("gh api repos/latark/agent-kit/pulls/9/merge", "GET адреса слияния (слит ли PR)"),
                   ("gh api -X GET repos/latark/agent-kit/pulls/9/merge", "-X GET"),
                   ("gh api -X PUT repos/latark/agent-kit/merges -f base=main -f head=feat", "…/merges (ветка в ветку)"),
                   ("gh api -X POST repos/latark/agent-kit/issues/9/comments -f body=merged", "запись не на слияние"),
                   ("gh api -X POST repos/latark/agent-kit/issues/7/comments -f body=see/repos/a/b/pulls/9/merge",
                    "адрес слияния в поле, не в адресе"),
                   ("gh api --paginate -X POST repos/latark/agent-kit/issues -f title=x --jq .id", "запись: --paginate, --jq"),
                   ("gh api $URL", "чтение по адресу из переменной"),
                   ("gh api $URL $F", "чтение: адрес и флаг из переменных, merge нет"),
                   ("gh api -X GET $URL -f q=1", "-X GET по адресу из переменной"),
                   # Д1 argus #257: GET с невычислимым словом — не судится; merge в --jq и в соседней команде не в счёт
                   ("gh api repos/latark/agent-kit/pulls/$N --jq .merged", "GET: номер — переменная, --jq .merged"),
                   ('gh api "repos/$REPO/pulls/7" --jq .mergeable', "GET: репозиторий — переменная, --jq .mergeable"),
                   ('gh api "repos/$REPO/commits/main" ; gi' 't merge --ff-only origin/main',
                    "GET с переменной, слияние git соседней командой"),
                   ("gh api repos/latark/agent-kit/pulls/$N/merge", "GET адреса слияния с номером-переменной"),
                   ("gh api repos/latark/agent-kit/pulls/9/merge -H $H", "GET адреса слияния, заголовок — переменная"),
                   ("gh api $URL --jq .merged $F", "чтение: адрес и флаг из переменных, merge только в --jq"),
                   # Д2: невычислимое значение флага у записи не на слияние — пропуск
                   ("gh api -X POST repos/latark/agent-kit/issues/7/comments -f body=$B", "поле — переменная, merge нет"),
                   ('gh api repos/o/r/issues/1/comments -f body="$B"', "поле в кавычках — переменная, без -X"),
                   ("gh api repos/o/r/issues/1/comments -f body=see/repos/o/r/pulls/7/merge -f x=$Y",
                    "адрес слияния в поле, переменная в другом поле, лишнего слова нет"),
                   ('gh api -X POST repos/latark/agent-kit/issues/7/comments -f body="$B merged"',
                    "поле — переменная со словом merge"),
                   ("gh api -H $H repos/latark/agent-kit/issues/1/comments -f body=x", "значение -H — переменная"),
                   ("gh api -X $M repos/latark/agent-kit/issues/1/comments -f body=x", "метод — переменная, не слияние"),
                   # Д3: записи в pulls/* без merge — не слияние
                   ("gh api -X PATCH repos/latark/agent-kit/pulls/9 -f title=x", "PATCH pulls/9"),
                   ("gh api -X POST repos/latark/agent-kit/pulls/9/reviews -f event=APPROVE", "POST pulls/9/reviews"),
                   ("gh api -X POST repos/latark/agent-kit/pulls/9/comments -f body=x", "POST pulls/9/comments"),
                   # Д5: pulls и merge — по сегментам после repos/<owner>/<repo>/
                   ("gh api -X POST repos/latark/merge-bot/pulls -f title=x -f head=a -f base=main",
                    "POST repos/o/merge-bot/pulls (имя репозитория)"),
                   ("gh api -X DELETE repos/latark/agent-kit/git/refs/heads/fix-pulls-merge",
                    "DELETE ветки fix-pulls-merge"),
                   ("gh api -X DELETE repos/latark/pulls/git/refs/heads/merge-fix",
                    "DELETE ветки merge-fix в репозитории pulls"),
                   ("gh api -X DELETE repos/latark/agent-kit/git/refs/heads/merge/pulls", "DELETE ветки merge/pulls"),
                   ("gh api graphql -f 'query={viewer{login}}'", "graphql запрос словами, без слияния"),
                   ("gh api graphql -f query=@q", "graphql -f (сырое поле, не файл)"),
                   ("gh alias list", "gh alias list"),
                   ("gh alias", "gh alias без подкоманды"),
                   ("gh alias delete m-merge", "gh alias delete со словом merge"),
                   ("gh secret set merge_key --body x", "set со словом merge не у alias"),
                   ("echo $X; echo merge", "невычислимое слово не у gh, merge в строке"),
                   ("gh $SUB view 9", "подкоманда gh не вычисляется, merge нет"),
                   ("gi" "t merge --ff-only origin/main", "git merge (не gh)")):
        merge_case(f"без роли: {how} — можно, CI не спрашивается", h.pre(c, **owner), True)
    log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
    check("без роли: не слияние PR — gh не спрашивается", log == "", log)
    # фоновая проверка 02.11: слово merge в сыром тексте разорвано кавычками — после разбора bash это gh pr merge
    h.ci(red, name="agent-kit")
    for c, how in (("gh pr mer''ge 9", "mer''ge"), ('gh pr "mer"ge 9', '"mer"ge'), ("gh pr me\\rge 9", "me\\rge"),
                   ("S=merge; gh pr $S 9", "подкоманда из присвоения")):
        merge_case(f"без роли: gh pr {how}, CI красный — отказ (предфильтр после разбора bash)", h.pre(c, **owner),
                   False, "gh pr merge — проверка GitHub tests/affected красная")
    h.ci(nine, name="agent-kit")
    merge_case("без роли: gh pr mer''ge 9, CI зелёный — проходит", h.pre("gh pr mer''ge 9", **owner), True)
    # у ролей алиас слияния — тот же отказ (gh api с записью ролям закрыт и так)
    merge_case("роль: gh alias set m 'pr merge' — отказ", h.pre("gh alias set m 'pr merge'", pdir=kit), False,
               "gh alias со словом merge")
    merge_case("роль: gh alias set v 'pr view' — можно", h.pre("gh alias set v 'pr view'", pdir=kit), True)
    merge_case("роль: gh api -X PUT …/merge — отказ правилом push, как раньше", h.pre(base, pdir=kit), False,
               "gh api с записью")
    # metis-0681: связка коротких флагов с X, f или F — запись и у роли
    for c in ("gh api -iX PUT repos/latark/agent-kit/pulls/9/merge", "gh api -iXPUT repos/latark/agent-kit/pulls/9/merge",
              f"{base} -iF sha={sha}"):
        merge_case(f"роль: {c} — отказ правилом push", h.pre(c, pdir=kit), False, "gh api с записью")
    # Б1 argus #257: репозиторий берётся из адреса (-R), а не из папки — из tg-read (CI зелёный) адрес agent-kit
    # (CI красный) — отказ по CI agent-kit; плейсхолдеры {owner}/{repo} там же — CI tg-read, проходит
    h.ci(red, name="agent-kit")
    h.ci(GREEN, name="tg-read")
    merge_case("без роли: из папки tg-read адрес agent-kit, CI agent-kit красный — отказ",
               h.pre("gh api -X PUT repos/latark/agent-kit/pulls/9/merge", role=None, pdir="projects/tg-read"),
               False, "tests/affected красная")
    merge_case("без роли: из папки tg-read адрес {owner}/{repo}, CI tg-read зелёный — проходит",
               h.pre("gh api -X PUT 'repos/{owner}/{repo}/pulls/9/merge'", role=None, pdir="projects/tg-read"), True)


CASES = [t_test_floors, t_carry_budget, t_prod_timeouts, t_full_tests_verify, t_owner_api_merge, t_git_timeout, t_manifest_types]


if __name__ == "__main__":
    sys.exit(main(CASES))
