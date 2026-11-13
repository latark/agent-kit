#!/usr/bin/env python3
"""Запор слияния guard, часть «r4»: перенос «принять»: чужой конфиг git (r4), медленный git, бюджет (r6), слитая база.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py; разрез metis-1119.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_r4.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403


def r4_history(h):
    """Истории для #134 r4 (один раз на прогон): T0 — база с подмодулем, симлинком, .gitattributes; TM — main, файлы
    PR не трогает; heads — (head, base) по имени; имя с «n» на конце — то же + main + номер версии."""
    if getattr(h, "r4", None):
        return h.r4
    s = kit_history(h)
    p = h.j("projects/agent-kit")
    F = lambda b: ("100644", b if isinstance(b, bytes) else b.encode())
    L = lambda t: ("120000", t.encode())
    G = lambda sha: ("160000", sha)
    t0 = plumb(p, [s["B"]], {"sub": G(s["B"]), "z.txt": F("z\n"), "t.txt": F("t\n"), "ln": L("t.txt"), "tf": F("t.txt"),
                             "crlf.txt": F("a\ny\n"), "data.bin": F(b"\x00\x01"), "w.txt": F("w\n"),
                             ".gitattributes": F("* diff=x binary\n")}, "r4: база")
    tm = plumb(p, [t0], {"main2.py": F("m = 2\n"), PJ: F(_man("pantheon", "0.11.85"))}, "r4: main")
    hex1, hex2 = "1" * 40, "2" * 40
    own = {"g1": {"sub": G(s["M1"])}, "g2": {"sub": G(s["M2"])},
           "ga1": {"sub": G(s["M1"]), "z.txt": F("z1\n")}, "ga2": {"sub": G(s["M1"]), "z.txt": F("z2\n")},
           "s1": {"ln": L("w.txt")}, "s2": {"ln": L("z.txt")},
           "ty0": {"w.txt": F("w1\n")}, "ty1": {"w.txt": F("w1\n"), "tf": L("t.txt")},
           "c1": {"crlf.txt": F("a\r\nx\n")}, "c2": {"crlf.txt": F("a\nx\n")},
           "b1": {"data.bin": F(b"\x00\ndiff --git a/x b/x\n" + hex1.encode() + b"\n")},
           "b2": {"data.bin": F(b"\x00\ndiff --git a/x b/x\n" + hex2.encode() + b"\n")},
           "nl1": {"x\ny.py": F("1\n")}, "nl2": {"x\ny.py": F("2\n")}, "nl3": {"x": F("1\n"), "y.py": F("1\n")}}
    heads = {}
    for name, ch in own.items():
        c = plumb(p, [t0], ch, "r4: " + name)
        heads[name] = (c, tm)
        n = plumb(p, [c, tm], dict(ch, **{"main2.py": F("m = 2\n"), PJ: F(_man("pantheon", "0.11.86"))}), "r4: main",
                  src=tm)
        heads[name + "n"] = (n, tm)
    # plugin.json: смена только режима, симлинк вместо файла
    pj = subprocess.run(["git", "-C", p, "rev-parse", s["N1"] + ":" + PJ], capture_output=True, text=True).stdout.strip()
    heads["pm"] = (plumb(p, [s["N1"]], {PJ: ("100755", subprocess.run(["git", "-C", p, "cat-file", "blob", pj],
                                                                       capture_output=True).stdout)}, "chmod +x"), s["M1"])
    heads["pl"] = (plumb(p, [s["N1"]], {PJ: L("../../README.md")}, "plugin.json — симлинк"), s["M1"])
    # rebase P на M1 без правок; P на main, правившем code.py, — конфликт решён иначе
    heads["Preb"] = (plumb(p, [s["M1"]], {"code.py": F(CODE.format(2)), "README.md": F(README.replace("r1\n", "r1p\n"))},
                           "rebase P"), s["M1"])
    mc = plumb(p, [s["B"]], {"code.py": F(CODE.format(8))}, "main: code.py")
    heads["Prc"] = (plumb(p, [mc], {"code.py": F(CODE.format(28)), "README.md": F(README.replace("r1\n", "r1p\n"))},
                          "rebase P с конфликтом"), mc)
    heads["Pmc"] = (s["P"], mc)
    # конфликт решён своей стороной: code.py как у P, правка main выброшена — новое содержимое то же, старое (osha) другое
    heads["Pours"] = (plumb(p, [mc], {"code.py": F(CODE.format(2)), "README.md": F(README.replace("r1\n", "r1p\n"))},
                            "rebase P: конфликт решён своей стороной"), mc)
    # cherry-pick правки README из PR в main
    mcp = plumb(p, [s["M1"]], {"README.md": F(README.replace("r1\n", "r1p\n"))}, "main: cherry-pick README из PR")
    heads["Ncp"] = (plumb(p, [s["P"], mcp], {"code.py": F(CODE.format(2)), PJ: F(_man("pantheon", "0.11.86"))},
                          "PR: подтянул main", src=mcp), mcp)
    # ветка эпика от B: PR перенацелен на неё, а head подтянул main
    epic = plumb(p, [s["B"]], {"epic.py": F("e = 1\n")}, "ветка эпика")
    heads["N1e"] = (s["N1"], epic)
    heads["Pe"] = (s["P"], epic)
    for name in ("P", "N1", "out", "ws", "wsin", "bin", "mode", "newfile", "field", "evil", "R", "A", "NA"):
        heads[name] = (s[name], s["M1"])
    h.r4 = {"heads": heads, "t0": t0, "tm": tm, "epic": epic}
    return h.r4


def hostile_config(d):
    """Конфиг git, который меняет вывод diff: diff.*, core.abbrev, атрибуты, textconv, подмодули → путь .gitconfig."""
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "order"), "w") as fh:
        fh.write("z.txt\nsub\nx*\n*\n")
    with open(os.path.join(d, "attrs"), "w") as fh:
        fh.write("* diff=x binary -text\n")
    with open(os.path.join(d, ".gitconfig"), "w") as fh:
        fh.write("[diff]\n\tsubmodule = log\n\tindentHeuristic = false\n\torderFile = %s\n\tsuppressBlankEmpty = true\n"
                 "\tmnemonicPrefix = true\n\tnoprefix = true\n\texternal = false\n\trenames = copies\n\trelative = true\n"
                 "\tignoreSubmodules = all\n\talgorithm = patience\n\tcontext = 9\n"
                 "[core]\n\tabbrev = 4\n\tattributesFile = %s\n\tquotePath = false\n\tautocrlf = true\n"
                 "[diff \"x\"]\n\ttextconv = echo same\n" % (os.path.join(d, "order"), os.path.join(d, "attrs")))
    return os.path.join(d, ".gitconfig")


def t_carry_r4(h):
    """#134 r4 (threat-134-carry, решение владельца 25.10 23:05): отпечаток — содержимое файлов (git diff --raw), от
    конфига и окружения git не зависит; подмодуль, симлинк, typechange, CRLF, двоичный файл, имя с \\n, режим
    plugin.json; rebase, cherry-pick, смена базы."""
    r4 = r4_history(h)
    heads = r4["heads"]
    mg = _load_merge_gate("merge_gate_carry_r4")
    kit = h.j("projects/agent-kit")
    gd, why = mg._carry_git(kit, "latark/agent-kit", r4["tm"])
    check("r4: _carry_git — git dir", gd and why is None, why)
    clean_home = h.j("r4-clean")
    os.makedirs(clean_home, exist_ok=True)

    def fp(name):
        head, base = heads[name]
        return mg._fingerprint(gd, base, head)[0]

    with _Env(HOME=clean_home, XDG_CONFIG_HOME=None):
        clean = {name: fp(name) for name in heads}
    ref = clean["P"]
    for a, b, why_ in (("g1", "g2", "правка только gitlink"), ("ga1", "ga2", "правка после gitlink"),
                       ("s1", "s2", "цель симлинка"), ("ty0", "ty1", "файл → симлинк с тем же текстом"),
                       ("c1", "c2", "CRLF против LF в одной строке"),
                       ("b1", "b2", "двоичный файл: «diff --git» и 40 hex внутри"),
                       ("nl1", "nl2", "имя с \\n, другое содержимое"), ("nl1", "nl3", "имя с \\n против двух файлов")):
        check(f"r4: {a} ≠ {b} — {why_}", clean[a] and clean[b] and clean[a] != clean[b], (clean[a], clean[b]))
    for name in ("g1", "ga1", "s1", "ty1", "c1", "b1", "nl1"):
        check(f"r4: {name}n = {name} (main и номер версии)", clean[name] and clean[name + "n"] == clean[name],
              (clean[name], clean[name + "n"]))
    check("r4: plugin.json chmod +x — отпечаток другой", clean["pm"] and clean["pm"] != clean["N1"] == ref,
          (clean["pm"], clean["N1"]))
    got = mg._fingerprint(gd, heads["pl"][1], heads["pl"][0])
    check("r4: plugin.json — симлинк (typechange) — отпечатка нет", got[0] is None and "plugin.json" in got[1], got)
    check("r4: чистый rebase P на M1 — тот же код, перенос", clean["Preb"] == ref, clean["Preb"])
    check("r4: rebase с конфликтом, решённым иначе — код другой", clean["Prc"] and clean["Prc"] != clean["Pmc"] == ref,
          (clean["Prc"], clean["Pmc"]))
    check("r4: rebase с конфликтом, решённым своей стороной (правка main откатится) — код другой",
          clean["Pours"] and clean["Pours"] != ref, (clean["Pours"], ref))
    check("r4: cherry-pick части PR в main — код другой (ложный отказ, строго)", clean["Ncp"] and clean["Ncp"] != ref,
          clean["Ncp"])
    check("r4: смена базы на ветку эпика — main в диффе PR, код другой", clean["N1e"] and clean["N1e"] != clean["Pe"]
          == ref, (clean["N1e"], clean["Pe"]))
    # конфиг: HOME/.gitconfig, XDG, .git/config, info/attributes, GIT_* окружения — отпечатки те же
    hostile = h.j("r4-hostile")
    hostile_config(hostile)
    xdg = os.path.join(hostile, "xdg")
    os.makedirs(os.path.join(xdg, "git"), exist_ok=True)
    shutil.copy(os.path.join(hostile, ".gitconfig"), os.path.join(xdg, "git", "config"))
    cfg = os.path.join(kit, ".git", "config")
    attrs = os.path.join(kit, ".git", "info", "attributes")
    os.makedirs(os.path.dirname(attrs), exist_ok=True)
    with open(cfg, "rb") as fh:
        saved = fh.read()
    try:
        with open(cfg, "ab") as fh:
            fh.write(b"[diff]\n\tsubmodule = log\n[submodule \"sub\"]\n\tignore = all\n[core]\n\tabbrev = 5\n")
        with open(attrs, "w") as fh:
            fh.write("* diff=x binary\n")
        with _Env(HOME=hostile, XDG_CONFIG_HOME=xdg, GIT_CONFIG_PARAMETERS="'diff.submodule'='log' 'core.abbrev'='4'",
                  GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="diff.relative", GIT_CONFIG_VALUE_0="true",
                  GIT_EXTERNAL_DIFF="false", GIT_DIFF_OPTS="--unified=9", GIT_DIR=h.j("nonexistent"),
                  GIT_OBJECT_DIRECTORY=h.j("nonexistent")):
            bad = {}
            for name in heads:
                got = fp(name)
                if got != clean[name]:
                    bad[name] = (clean[name], got)
        check(f"r4: конфиг и окружение git (diff.submodule=log, diff.*, core.abbrev=4, атрибуты) — те же отпечатки у "
              f"{len(heads)} head", not bad, bad)
    finally:
        with open(cfg, "wb") as fh:
            fh.write(saved)
        os.remove(attrs)
    # строгий разбор --raw: лишнее поле, чужой статус, пустой путь, повтор пути — отпечатка нет
    saved_git = mg._git_bytes
    for out, why_ in ((b":100644 100644 " + b"1" * 40 + b" " + b"2" * 40 + b" M\0ab", "без \\0 в конце"),
                      (b":100644 100644 " + b"1" * 40 + b" " + b"2" * 40 + b" R100\0a\0b\0", "статус R"),
                      (b":100644 100644 " + b"1" * 40 + b" " + b"2" * 40 + b" M\0\0", "пустой путь"),
                      (b":100644 100644 " + b"1" * 4 + b" " + b"2" * 40 + b" M\0a\0", "короткий sha"),
                      ((b":100644 100644 " + b"1" * 40 + b" " + b"2" * 40 + b" M\0a\0") * 2, "путь дважды")):
        mg._git_bytes = lambda gd_, *a, _o=out, **k: _o if "--raw" in a else saved_git(gd_, *a, **k)
        try:
            got = mg._fingerprint(gd, s_m1(h), heads["P"][0])
        finally:
            mg._git_bytes = saved_git
        check(f"r4: вывод --raw не по формату ({why_}) — отпечатка нет", got[0] is None and "--raw" in got[1], got)


def s_m1(h):
    return kit_history(h)["M1"]


def t_carry_r4_gate(h):
    """#134 r4 шлюзом: конфиг git в HOME не влияет на перенос, подмодуль, смена базы, таймаут git."""
    r4 = r4_history(h)
    heads = r4["heads"]
    s = kit_history(h)
    kit = "projects/agent-kit"
    tests = lambda sha: rec("tests", "latark/agent-kit", None, sha, "dev-opus")
    rej = lambda sha, who="y": opus(sha, who, "reject", checklist=None, session="s-y")

    def case(name, head, base, recs, allow, why="", extra_env=None):
        h.reset()
        kit_pr(h, head, base)
        h.seed(*recs)
        t = time.monotonic()
        got = h.pre(f"gh pr merge 7 --match-head-commit {head}", pdir=kit, extra_env=extra_env)
        merge_case(name, got, allow, why)
        return got, time.monotonic() - t

    hostile_config(h.root)  # HOME хука — h.root
    try:
        g1, tm = heads["g1"]
        case("r4 шлюз: .gitconfig с diff.submodule=log — N1 переносит «принять» с P", s["N1"], s["M1"],
             [opus(s["P"]), tests(s["N1"])], True)
        case("r4 шлюз: .gitconfig — правка кода не переносит", s["out"], s["M1"], [opus(s["P"]), tests(s["out"])], False,
             "нет «принять»")
        case("r4 шлюз: подмодуль g1 → g1n переносится", heads["g1n"][0], tm, [opus(g1), tests(heads["g1n"][0])], True)
        case("r4 шлюз: «принять» на g1 не переносится на g2 (другой gitlink)", heads["g2n"][0], tm,
             [opus(g1), tests(heads["g2n"][0])], False, "нет «принять»")
        case("r4 шлюз: другой argus принял g1n, «вернуть» на g1 с тем же кодом — в силе (0415b)", heads["g1n"][0], tm,
             [rej(g1), opus(heads["g1n"][0], "x"), tests(heads["g1n"][0])], False, "«вернуть» (reject)")
    finally:
        os.remove(h.j(".gitconfig"))
    case("r4 шлюз: «принять» на P (base M1) не переносится на N1 при базе — ветке эпика", s["N1"], r4["epic"],
         [opus(s["P"]), tests(s["N1"])], False, "нет «принять»")
    # таймаут git: diff --raw дольше своего timeout — без переноса, хук отказывает сам, а не по сроку DEADLINE. В тесте
    # timeout git поднят до HOOK_SUB_TIMEOUT (metis-0719), поэтому git спит дольше: SLOW_GIT > HOOK_DEADLINE
    wrap = h.j("gitwrap")
    os.makedirs(wrap, exist_ok=True)
    with open(os.path.join(wrap, "git"), "w") as fh:
        fh.write(f'#!/bin/sh\ncase "$*" in *--raw*) [ -f "$HOME/git.slow" ] && exec sleep {SLOW_GIT};; esac\n'
                 f'exec {shutil.which("git")} "$@"\n')
    os.chmod(os.path.join(wrap, "git"), 0o755)
    env = {"PATH": wrap + os.pathsep + h.j("bin") + os.pathsep + os.environ["PATH"]}
    open(h.j("git.slow"), "w").close()
    try:
        recs = [opus(s["P"], "x"), rej(s["R"]), opus(s["A"], "z", session="s-z"), opus(s["N1"], "w", session="s-w"),
                tests(s["NA"])]
        got, took = case("r4 шлюз: git diff --raw дольше таймаута — «вернуть» в силе", s["NA"], s["M1"], recs, False,
                         "«вернуть» (reject)", extra_env=env)
        # без timeout у git хук ждал бы SLOW_GIT и гас по сроку HOOK_DEADLINE — тогда и причина ниже другая
        check(f"r4 шлюз: таймаут git — хук за {took:.1f} с, не ждёт git {SLOW_GIT} с", took < HOOK_DEADLINE, took)
        check("r4 шлюз: таймаут git — причина в отказе", "не ответил" in got[1] or "дольше" in got[1], got[1])
    finally:
        os.remove(h.j("git.slow"))


def t_carry_r6(h):
    """r6 сверяет перенос по длинной истории (много вызовов git подряд): на load 200+ полного набора 15 с не хватало
    (metis-0989, r6 ctl2). Предел CARRY_BUDGET_MAX — только здесь: от общего 15 зависит t_carry_r4_gate (зависший
    git не должен выходить за бюджет)."""
    h.carry_budget = _load_merge_gate("merge_gate_r6_budget").CARRY_BUDGET_MAX
    try:
        _t_carry_r6(h)
    finally:
        h.carry_budget = HOOK_CARRY_BUDGET


def _t_carry_r6(h):
    """argus-b r2 (#134): откат force-push к точному старому head, принятому до «вернуть», после снятия «вернуть»
    правилом 3 — прямое «принять» до отсечки не засчитывается, как и перенос."""
    s = kit_history(h)
    kit = "projects/agent-kit"
    tests = lambda sha: rec("tests", "latark/agent-kit", None, sha, "dev-opus")
    rej = lambda sha, who="y": opus(sha, who, "reject", checklist=None, session="s-y")

    def case(name, head, base, recs, allow, why="", core=False):
        h.reset()
        kit_pr(h, s[head], s[base], core=core)
        h.seed(*recs)
        got = h.pre(f"gh pr merge 7 --match-head-commit {s[head]}", pdir=kit)
        merge_case(name, got, allow, why)
        return got

    case("r6 ctl1: z принял N1, y вернул R, слияние N1 — «вернуть» в силе", "N1", "M1",
         [opus(s["N1"], "z", session="s-z"), rej(s["R"]), tests(s["N1"])], False, "«вернуть» (reject)")
    case("r6 ctl2: z принял P, y вернул R, w принял A, слияние N1 — перенос отсечён", "N1", "M1",
         [opus(s["P"], "z", session="s-z"), rej(s["R"]), opus(s["A"], "w", session="s-w"), tests(s["N1"])], False,
         "нет «принять»")
    got = case("r6 обход: z принял N1, y вернул R, w принял A, force-push на N1 — отказ", "N1", "M1",
               [opus(s["N1"], "z", session="s-z"), rej(s["R"]), opus(s["A"], "w", session="s-w"), tests(s["N1"])],
               False, "нет «принять»")
    check("r6 обход: отказ называет «принять» z на N1 и отсёкшее его «вернуть» y на R",
          "записано раньше «вернуть»" in got[1] and f"на {s['N1'][:12]}" in got[1]
          and f"на {s['R'][:12]}" in got[1] and "ни на своём head" in got[1], got[1])
    case("r6: z снова принял N1 после «вернуть» — проходит", "N1", "M1",
         [opus(s["N1"], "z", session="s-z"), rej(s["R"]), opus(s["A"], "w", session="s-w"),
          opus(s["N1"], "z", session="s-z"), tests(s["N1"])], True)
    case("r6: w принял A после «вернуть» R, слияние A — проходит (правило 3 не тронуто)", "A", "M1",
         [opus(s["N1"], "z", session="s-z"), rej(s["R"]), opus(s["A"], "w", session="s-w"), tests(s["A"])], True)
    case("r6: y вернул R и сам принял R — отсечки нет, «принять» z на N1 до «вернуть» в силе", "N1", "M1",
         [opus(s["N1"], "z", session="s-z"), rej(s["R"]), opus(s["R"], "y", session="s-y"), tests(s["N1"])], True)
    # r7 (argus-134a5): отсечка берёт ПОСЛЕДНИЙ неснятый «вернуть», а не первый
    rej2 = lambda sha, who: opus(sha, who, "reject", checklist=None, session="s-" + who)
    case("r6 n3: y1 вернул out, z принял N1, y2 вернул R, w принял A, force-push на N1 — отказ", "N1", "M1",
         [rej2(s["out"], "y1"), opus(s["N1"], "z", session="s-z"), rej2(s["R"], "y2"),
          opus(s["A"], "w", session="s-w"), tests(s["N1"])], False, "нет «принять»")
    case("r6 n3 ctl: y1 вернул out, z принял N1, слияние N1 — проходит", "N1", "M1",
         [rej2(s["out"], "y1"), opus(s["N1"], "z", session="s-z"), tests(s["N1"])], True)
    # r7: своё «принять» не на Opus не засчитывается и отсечку не снимает
    sonnet = dict(CHECKLIST, ran="модель: claude-sonnet-5, heavy python3 -I tests/test_merge_gate.py")
    case("r6 n7 ctl: только «принять» не на Opus на N1 — отказ «не на Opus»", "N1", "M1",
         [rec("accept", "latark/agent-kit", 7, s["N1"], agent_id="q", session="s-q", checklist=sonnet),
          tests(s["N1"])], False, "не на Opus", core=True)
    case("r6 n7: z принял N1, y вернул R, y принял R не на Opus, w принял A, force-push на N1 — отказ", "N1", "M1",
         [opus(s["N1"], "z", session="s-z"), rej(s["R"]),
          rec("accept", "latark/agent-kit", 7, s["R"], agent_id="y", session="s-y", checklist=sonnet),
          opus(s["A"], "w", session="s-w"), tests(s["N1"])], False, "нет «принять»", core=True)


def t_carry_merged(h):
    """Перенос «принять», когда отпечаток другой, а код тот же (_merge_same): main сдвинул строки в файле PR
    (metis-0445), базовый PR слит squash и PR сверху перенесён rebase --onto (metis-0674). И база отпечатков — живая
    вершина ветки base, а не снимок baseRefOid (metis-0471)."""
    s = kit_history(h)
    kit = "projects/agent-kit"
    p = h.j(kit)
    F = lambda t: ("100644", t.encode())
    tests = lambda sha: rec("tests", "latark/agent-kit", None, sha, "dev-opus")
    lines = [f"c{i}\n" for i in range(30)]
    pr_c = "".join(lines[:20] + ["pr\n"] + lines[21:])
    bc = plumb(p, [s["B"]], {"c.txt": F("".join(lines))}, "main: c.txt")
    bc2 = plumb(p, [bc], {"c.txt": F("top\n" + "".join(lines))}, "main: строка над правкой PR")
    qc = plumb(p, [bc], {"c.txt": F(pr_c)}, "PR: правка c.txt")
    qcm = plumb(p, [qc, bc2], {"c.txt": F("top\n" + pr_c)}, "PR: подтянул main", src=bc2)
    qreb = plumb(p, [bc2], {"c.txt": F("top\n" + pr_c)}, "PR: rebase на main")
    qevil = plumb(p, [qc, bc2], {"c.txt": F("top\n" + pr_c), "evil.py": F("e = 1\n")}, "PR: слияние с правкой",
                  src=bc2)
    bcc = plumb(p, [bc], {"c.txt": F("".join(lines[:20] + ["main\n"] + lines[21:]))}, "main: та же строка")
    qconf = plumb(p, [qc, bcc], {"c.txt": F(pr_c)}, "PR: конфликт решён своей стороной", src=bcc)
    # PR1 (x1.py) от bc, PR2 (x2.py) сверху на ветке PR1; PR1 слит squash поверх bc2, PR2 — rebase --onto main
    p1 = plumb(p, [bc], {"x1.py": F("a = 1\n")}, "PR1")
    a2 = plumb(p, [p1], {"x2.py": F("b = 1\n")}, "PR2 на ветке PR1")
    sq = plumb(p, [bc2], {"x1.py": F("a = 1\n")}, "main: squash PR1")
    s2 = plumb(p, [sq], {"x2.py": F("b = 1\n")}, "PR2: rebase --onto main")
    sqx = plumb(p, [bc2], {"x1.py": F("a = 2\n")}, "main: squash PR1 с правкой после «принять» PR2")
    s2x = plumb(p, [sqx], {"x2.py": F("b = 1\n")}, "PR2: rebase --onto main")
    # metis-0471: в ветку PR влили X и откатили, X уже в main (живая вершина), снимок baseRefOid — до X
    x = plumb(p, [bc], {"x.py": F("x = 1\n")}, "X")
    xa = plumb(p, [bc], {"a.py": F("a = 1\n")}, "PR: a.py")
    xm = plumb(p, [xa, x], {"x.py": F("x = 1\n")}, "PR: влил X", src=xa)
    xs = plumb(p, [xm], {"x.py": None}, "PR: откат X")
    main_x = plumb(p, [bc, x], {"x.py": F("x = 1\n")}, "main: X", src=bc)

    def case(name, head, base, recs, allow, why="", tip=None):
        h.reset()
        if tip is not None:
            h.tip["agent-kit"] = tip
        kit_pr(h, head, base)
        h.seed(*recs)
        got = h.pre(f"gh pr merge 7 --match-head-commit {head}", pdir=kit)
        merge_case(name, got, allow, why)
        return got

    # сначала то, чего отпечаток не берёт: иначе тест 0445 ничего бы не проверял
    mg = _load_merge_gate("merge_gate_carry_merged")
    gd, why = mg._carry_git(p, "latark/agent-kit", bc2)
    check("0445: _carry_git — git dir", gd and why is None, why)
    fq, fqm = mg._fingerprint(gd, bc2, qc), mg._fingerprint(gd, bc2, qcm)
    check("0445: main сдвинул строки — отпечаток другой", fq[0] and fqm[0] and fq[0] != fqm[0], (fq, fqm))
    check("0445: _merge_same — слияние P с main и есть новый head", mg._merge_same(gd, qc, fq[1], fqm[1], qcm) is True)
    check("0445: _merge_same — rebase на main тоже", mg._merge_same(gd, qc, fq[1], bc2, qreb) is True)
    check("0445: _merge_same — правка в слиянии — нет", mg._merge_same(gd, qc, fq[1], bc2, qevil) is False)
    check("0445: _merge_same — конфликт с main — нет", mg._merge_same(gd, qc, fq[1], bcc, qconf) is False)
    qv = plumb(p, [qcm], {PJ: F(_man("pantheon", "0.11.99"))}, "PR: номер версии")
    qf = plumb(p, [qcm], {PJ: F(_man("pantheon", "0.11.84", description="x"))}, "PR: другое поле plugin.json")
    qj = plumb(p, [qcm], {"plugins/x/package.json": F(_man("x", "1.0.1"))}, "PR: version в package.json")
    qj0 = plumb(p, [bc2], {"plugins/x/package.json": F(_man("x", "1.0.0"))}, "main: package.json")
    qjm = plumb(p, [qc, qj0], {"c.txt": F("top\n" + pr_c), "plugins/x/package.json": F(_man("x", "1.0.1"))},
                "PR: слияние и номер в package.json", src=qj0)
    check("0445: _merge_same — только номер версии в plugin.json — да", mg._merge_same(gd, qc, fq[1], bc2, qv) is True)
    check("0445: _merge_same — другое поле plugin.json — нет", mg._merge_same(gd, qc, fq[1], bc2, qf) is False)
    check("0445: _merge_same — новый файл с полем version — нет", mg._merge_same(gd, qc, fq[1], bc2, qj) is False)
    check("0445: _merge_same — version в package.json (не plugin.json) — нет", mg._merge_same(gd, qc, fq[1], qj0, qjm) is False)
    check("0445: _merge_same — head без общей истории — нет", mg._merge_same(gd, s["orphan"], fq[1], bc2, qcm) is not True)
    # argus #375 Б2: «не посчитано» — None, а не False (конфликт)
    real = mg._git_code
    tree = mg._git_bytes(gd, "rev-parse", qreb + "^{tree}")  # настоящее дерево qreb: код 129 с ним — всё равно сбой
    for name, fake in (("git не запустился", lambda *a, **k: None), ("git без --merge-base (код 129)",
                                                                     lambda *a, **k: (129, tree)),
                       ("вывод не дерево", lambda *a, **k: (0, b"junk\n"))):
        # подмена — только merge-tree: diff и cat-file после него идут в настоящий git
        mg._git_code = lambda gd_, *a, fake=fake, **k: fake() if "merge-tree" in a else real(gd_, *a, **k)
        notes = []
        check(f"Б2: _merge_same — {name} — None (не посчитано)",
              mg._merge_same(gd, qc, fq[1], bc2, qreb, notes.append) is None)
        old = any("git старше 2.40" in n for n in notes)
        check(f"0981: _merge_same — {name} — причина «git старше 2.40» {'есть' if '129' in name else 'нет'}",
              old is ("129" in name), notes)
    mg._git_code = real
    # metis-0969: атрибуты merge=ours из папки git, info/attributes и core.attributesFile не решают конфликт за PR.
    # Конфликт qc с bcc: с атрибутом слияние берёт сторону PR и совпадает с qconf — без защиты «тот же код» (True).
    gitc = lambda *a: subprocess.run(["git", "--git-dir=" + gd, *a], capture_output=True, check=True)
    gitc("config", "merge.ours.driver", "true")
    ga = os.path.join(h.root, "attrs-0969")
    with open(ga, "w") as fh:
        fh.write("* merge=ours\n")
    info = os.path.join(gd, "info", "attributes")
    for where, path in (("папка git/.gitattributes", os.path.join(gd, ".gitattributes")), ("info/attributes", info),
                        ("core.attributesFile", None)):
        if path is None:
            gitc("config", "core.attributesFile", ga)
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write("* merge=ours\n")
        notes = []
        got = mg._merge_same(gd, qc, fq[1], bcc, qconf, notes.append)
        want = None if path == info else False
        check(f"0969: _merge_same — merge=ours в {where} — {want} (конфликт не снят)", got is want, (got, notes))
        if path == info:
            check("0969: info/attributes — причина названа", any("info/attributes" in n for n in notes), notes)
        if path is None:
            gitc("config", "--unset", "core.attributesFile")
        else:
            os.remove(path)
    check("0969: контроль — без атрибутов конфликт — False", mg._merge_same(gd, qc, fq[1], bcc, qconf) is False)
    # долг #388: драйвер по умолчанию из конфига git папки (merge.default=ours) — тот же обход без атрибутов
    gitc("config", "merge.default", "ours")
    got = mg._merge_same(gd, qc, fq[1], bcc, qconf)
    gitc("config", "--unset", "merge.default")
    check("#388: _merge_same — merge.default=ours в конфиге git папки — False (конфликт не снят)", got is False, got)
    # долг #388: merge.renormalize и core.autocrlf из конфига git папки сняли бы конфликт перевода строк. main перевёл
    # c.txt на CRLF, PR правит строку; head — ровно то, что дало бы слияние с renormalize
    crlf = plumb(p, [bc], {"c.txt": ("100644", "".join(lines).replace("\n", "\r\n").encode())}, "main: CRLF")
    norm = ["-c", "core.autocrlf=true", "-c", "merge.renormalize=true"]
    mt = subprocess.run(["git", "--git-dir=" + gd, *norm, "merge-tree", "--write-tree", "--no-messages",
                         "--merge-base=" + bc, qc, crlf], capture_output=True, cwd=h.root)
    check("#388: контроль — с renormalize и autocrlf git сливает CRLF чисто", mt.returncode == 0, mt)
    blob = gitc("cat-file", "blob", mt.stdout.decode().split()[0] + ":c.txt").stdout
    qn = plumb(p, [qc, crlf], {"c.txt": ("100644", blob)}, "PR: слияние с renormalize", src=crlf)
    check("#388: контроль — без renormalize конфликт CRLF — False", mg._merge_same(gd, qc, fq[1], crlf, qn) is False)
    gitc("config", "merge.renormalize", "true")
    gitc("config", "core.autocrlf", "true")
    try:
        got = mg._merge_same(gd, qc, fq[1], crlf, qn)
    finally:
        gitc("config", "--unset", "merge.renormalize")
        gitc("config", "--unset", "core.autocrlf")
    check("#388: _merge_same — merge.renormalize и core.autocrlf в конфиге git папки — False", got is False, got)
    # долг #388: атрибуты системы (etc/gitattributes) без root не положить — проверяется окружение и флаги вызова git
    seen, real_run = [], mg.subprocess.run
    mg.subprocess.run = lambda argv, **k: seen.append((argv, k.get("env") or {})) or real_run(argv, **k)
    try:
        mg._git_code(gd, "rev-parse", "HEAD")
    finally:
        mg.subprocess.run = real_run
    check("#388: _git_code — GIT_ATTR_NOSYSTEM=1 и core.attributesFile=/dev/null", len(seen) == 1
          and seen[0][1].get("GIT_ATTR_NOSYSTEM") == "1" and "core.attributesFile=" + os.devnull in seen[0][0], seen)
    real_b = mg._git_bytes
    mg._git_bytes = lambda gd_, *a, **k: None if "--git-path" in a else real_b(gd_, *a, **k)
    with open(info, "w") as fh:
        fh.write("* merge=ours\n")
    check("0969: путь info/attributes не узнать (сбой git) — None", mg._merge_same(gd, qc, fq[1], bcc, qconf) is None)
    os.remove(info)
    mg._git_bytes = real_b
    gitc("config", "--unset", "merge.ours.driver")
    for fn in ("_raw_entries", "_manifests"):
        keep = getattr(mg, fn)
        setattr(mg, fn, lambda *a, **k: None)
        check(f"Б2: _merge_same — {fn} не разобрал — None", mg._merge_same(gd, qc, fq[1], bc2, qv) is None)
        setattr(mg, fn, keep)
    pr_ = mg._Prints(None, "latark/agent-kit", qcm, [], lambda: {})
    pr_.allowed, pr_.ready, pr_.gd = {qcm, qc}, True, gd
    pr_.memo.update({qcm: ("f1", bc2), qc: ("f2", bc)})
    pr_.budget = -1
    check("Б2: _Prints.merged — бюджет вышел — None", pr_.merged(qc) is None)
    pr_.budget = 60
    check("Б2: _Prints.merged — посчитано — True", pr_.merged(qc) is True)
    check("Б2: _Prints.merged — у head нет отпечатка — None", pr_.merged(qreb) is None)

    qx = plumb(p, [bc], {"c.txt": F("x\n")}, "PR: третий head")

    class FP:
        def __init__(self, got):
            self.got = got

        def __call__(self, head):
            return {qc: ("fr", bc), qcm: ("fs", bc2), qx: ("fa", bc)}.get(head)

        def merged(self, head):
            return self.got

    x_rej = opus(qc, "x", "reject", checklist=None, session="s-x")
    check("Б2: _lifts — fp без merged (функция) — снимает по отпечатку, как раньше",
          mg._lifts(opus(qcm, "z", session="s-z"), x_rej, qcm, lambda head: FP(None)(head)) is True)
    for got, lift in ((None, False), (False, True), (True, False)):
        fp = FP(got)
        check(f"Б2: _lifts правило 2 — слияние {got} → снимает {lift}",
              mg._lifts(opus(qcm, "z", session="s-z"), x_rej, qcm, fp) is lift)
        check(f"Б2: _lifts правило 3 — слияние {got} → снимает {lift}",
              mg._lifts(opus(qx, "x", session="s-x"), x_rej, qcm, fp) is lift)
        got_c = mg._carried([opus(qc, "z", session="s-z")], qcm, fp, None, fp.merged)
        check(f"Б2: _carried — слияние {got} → переносит {got is True}", bool(got_c) is (got is True), got_c)
    case("0445: main сдвинул строки, PR подтянул main — «принять» переносится", qcm, bc2, [opus(qc), tests(qcm)], True)
    got = carry_lines(h)
    check("0445: перенос записан в carry.jsonl", len(got) == 1 and got[0]["sha"] == qcm
          and [r["sha"] for r in got[0]["from"]] == [qc] and got[0]["base"] == bc2, got)
    case("0445: rebase на сдвинутый main — переносится", qreb, bc2, [opus(qc), tests(qreb)], True)
    case("0445: правка внутри слияния — не переносится", qevil, bc2, [opus(qc), tests(qevil)], False, "нет «принять»")
    case("0445: конфликт с main решён своей стороной — не переносится", qconf, bcc, [opus(qc), tests(qconf)], False,
         "нет «принять»")
    case("0445: «вернуть» после «принять» — отсечка держит и такой перенос", qcm, bc2,
         [opus(qc), opus(qc, "y", "reject", checklist=None, session="s-y"), tests(qcm)], False, "«вернуть» (reject)")
    case("0674: PR1 слит squash, PR2 — rebase --onto main: «принять» PR2 переносится", s2, sq, [opus(a2), tests(s2)],
         True)
    case("0674: PR1 в main иной, чем под «принять» PR2 — не переносится", s2x, sqx, [opus(a2), tests(s2x)], False,
         "нет «принять»")
    case("0471 контроль: X не в main — влили и откатили, код PR тот же — переносится", xs, bc, [opus(xa), tests(xs)],
         True, tip=bc)
    case("0471: X в живом main, снимок baseRefOid до X — откат X не переносится", xs, bc, [opus(xa), tests(xs)], False,
         "нет «принять»", tip=main_x)
    got = case("0471: вершину base не получить от gh — не переносится", xs, bc, [opus(xa), tests(xs)], False,
               "нет «принять»", tip="fail")
    check("0471: отказ называет вершину ветки base", "вершину ветки base PR" in got[1], got[1])
    # argus #375 Б1 круг 2 (probe_375.py): принятый head на m4, main убрал m.txt (r6), новый head — squash на старую
    # базу bc с m.txt: слияние со своей базой git (bc) дало бы дерево squash, и m.txt вернулся бы в main
    m4 = plumb(p, [bc], {"m.txt": F("m\n")}, "main: m.txt")
    acc = plumb(p, [m4], {"a.py": F("a = 1\n")}, "PR на m4 — argus принял")
    r6 = plumb(p, [m4], {"m.txt": None}, "main: убрал m.txt")
    stale = plumb(p, [bc], {"m.txt": F("m\n"), "a.py": F("a = 1\n")}, "PR: squash на старую базу bc")
    good = plumb(p, [r6], {"a.py": F("a = 1\n")}, "PR: rebase на живой main")
    case("Б1 круг 2 контроль: rebase на живой main — переносится", good, r6, [opus(acc), tests(good)], True, tip=r6)
    case("Б1 круг 2: squash на старую базу вернул бы убранное main — не переносится", stale, r6,
         [opus(acc), tests(stale)], False, "нет «принять»", tip=r6)


CASES = [t_carry_r4, t_carry_r4_gate, t_carry_r6, t_carry_merged]


if __name__ == "__main__":
    sys.exit(main(CASES))
