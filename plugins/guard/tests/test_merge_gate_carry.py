#!/usr/bin/env python3
"""Запор слияния guard, часть «carry»: перенос «принять» в шлюзе: Opus, продукт, «вернуть», решение по заявке.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py; разрез metis-1119.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_carry.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403


def t_carry_gate(h):
    """Шлюз целиком: перенос «принять» с head, чей собственный дифф совпал, и запись переноса в журнал."""
    s = kit_history(h)
    kit = "projects/agent-kit"
    tests = lambda sha: rec("tests", "latark/agent-kit", None, sha, "dev-opus")
    merge = lambda sha: f"gh pr merge 7 --match-head-commit {sha}"

    def case(name, head, base, recs, allow, why="", cwd=None, cmd=None, extra_env=None):
        h.reset()
        kit_pr(h, s[head], s[base])
        h.seed(*recs)
        got = h.pre(cmd or merge(s[head]), pdir=kit, cwd=cwd, extra_env=extra_env)
        merge_case(name, got, allow, why)
        return got

    case("N1 = P + main + номер: «принять» с P переносится", "N1", "M1", [opus(s["P"]), tests(s["N1"])], True)
    got = carry_lines(h)
    check("перенос записан в merge-gate/carry.jsonl", len(got) == 1 and got[0].get("kind") == "carry"
          and got[0].get("sha") == s["N1"] and [x.get("sha") for x in got[0].get("from", [])] == [s["P"]]
          and len(got[0].get("fp") or "") == 64 and got[0].get("base") == s["M1"] and got[0].get("pr") == 7, got)
    st = os.stat(carry_file(h))
    check("carry.jsonl — 0600", stat.S_IMODE(st.st_mode) == 0o600, oct(st.st_mode))
    check("records.jsonl перенос не меняет (читают pantheon review status и metrics)",
          [r["kind"] for r in h.read()] == ["accept", "tests"], h.read())
    case("N2 = N1 + второй main + номер: переносится", "N2", "M2", [opus(s["P"]), tests(s["N2"])], True)
    case("Pv = P + номер, base M1: переносится", "Pv", "M1", [opus(s["P"]), tests(s["Pv"])], True)
    case("длинная история (35 пустых коммитов, 122-b-2): переносится", "Nlong", "M1",
         [opus(s["P"]), tests(s["Nlong"])], True)
    case("прямое «принять» на N1: проходит без переноса", "N1", "M1", [opus(s["N1"]), tests(s["N1"])], True)
    check("без переноса carry.jsonl не пишется", carry_lines(h) == [], carry_lines(h))
    case("папка .git клона (117-b3): переносится", "N1", "M1", [opus(s["P"]), tests(s["N1"])], True,
         cwd=kit + "/.git")
    for head, why in (("out", "правка кода"), ("ws", "только пробел"), ("bin", "двоичный файл"),
                      ("field", "другое поле plugin.json (117-b1)"), ("dup", "два ключа version (117-b1)"),
                      ("numver", "version числом (117-b1)"), ("mjson", "marketplace.json"), ("mode", "режим файла"),
                      ("evil", "правка в слиянии (117-a7)"), ("moddel", "modify/delete (117-b3)"),
                      ("side", "побочная ветка (122-b9)"), ("orphan", "без общей истории")):
        case(f"{head} — {why}: не переносится", head, "M1", [opus(s["P"]), tests(s[head])], False, "нет «принять»")
    case("тесты не переносятся: тесты только на P", "N1", "M1", [opus(s["P"]), tests(s["P"])], False,
         "нет записи тестов")
    h.reset()
    kit_pr(h, s["N1"], s["M1"])
    h.view["agent-kit"]["baseRefOid"] = "d" * 40
    h.write_view("agent-kit")
    h.seed(opus(s["P"]), tests(s["N1"]))
    merge_case("коммита base PR нет в git — не переносится, подсказка git fetch",
               h.pre(merge(s["N1"]), pdir=kit), False, "git fetch")
    case("слияние -R из клона другого репозитория (117-b3) — не переносится", "N1", "M1",
         [opus(s["P"]), tests(s["N1"])], False, "не клон", cwd="projects/tg-read",
         cmd=f"gh pr merge 7 -R latark/agent-kit --match-head-commit {s['N1']}")
    p = h.j(kit)
    with open(os.path.join(p, ".git", "shallow"), "w") as fh:
        fh.write(s["B"] + "\n")
    try:
        case("неполная история (122-b11, git fetch --depth) — не переносится", "N1", "M1",
             [opus(s["P"]), tests(s["N1"])], False, "неполная история")
    finally:
        os.remove(os.path.join(p, ".git", "shallow"))
    alt = os.path.join(p, ".git", "objects", "info", "alternates")
    os.makedirs(os.path.dirname(alt), exist_ok=True)
    with open(alt, "w") as fh:
        fh.write(os.path.join(p, ".git", "objects") + "\n")
    try:
        case("objects/info/alternates (объекты из другой папки) — не переносится", "N1", "M1",
             [opus(s["P"]), tests(s["N1"])], False, "alternates")
    finally:
        os.remove(alt)
    git(p, "replace", s["out"], s["N1"])
    try:
        case("git replace (117-b): head с правкой кода не переносит", "out", "M1", [opus(s["P"]), tests(s["out"])],
             False, "нет «принять»")
    finally:
        git(p, "replace", "-d", s["out"])
    # сбой git (122-a11-1) и старый git без флага (unknown option): diff --raw не отвечает — ни переноса, ни снятия
    # «вернуть». Медленный git (таймаут) — в t_carry_r4_gate и t_prod_timeouts: ветка git.slow с sleep 9 здесь
    # была мёртвой (файл git.slow никто не создавал, а при срезе 20 с у хука sleep 9 таймаута и не дал бы, metis-0730)
    wrap = h.j("gitwrap")
    os.makedirs(wrap, exist_ok=True)
    with open(os.path.join(wrap, "git"), "w") as fh:
        fh.write('#!/bin/sh\ncase "$*" in *--raw*)\n'
                 '  [ -f "$HOME/git.fail" ] && { echo "error: unknown option no-relative" >&2; exit 129; };;\n'
                 'esac\n'
                 f'exec {shutil.which("git")} "$@"\n')
    os.chmod(os.path.join(wrap, "git"), 0o755)
    env = {"PATH": wrap + os.pathsep + h.j("bin") + os.pathsep + os.environ["PATH"]}
    fixed = [opus(s["P"], "x"), opus(s["R"], "y", "reject"), opus(s["A"], "z", session="s-z"), tests(s["NA"])]
    case("«вернуть» на R снято «принять» на исправленном A, A переносится на NA", "NA", "M1", fixed, True,
         extra_env=env)
    open(h.j("git.fail"), "w").close()
    try:
        case("сбой git diff --raw (122-a11-1, старый git) — нет переноса, «вернуть» в силе", "NA", "M1", fixed, False,
             "«вернуть» (reject)", extra_env=env)
        case("сбой git — прямое «принять» на head проходит", "N1", "M1", [opus(s["N1"]), tests(s["N1"])], True,
             extra_env=env)
        case("сбой git diff --raw — head с правкой кода «принять» с P не переносит", "out", "M1",
             [opus(s["P"]), tests(s["out"])], False, "нет «принять»", extra_env=env)
    finally:
        os.remove(h.j("git.fail"))
    # «вернуть» привязано к PR
    rej = lambda sha, who="y": opus(sha, who, "reject", checklist=None, session="s-y")
    case("reject на P, «принять» другого argus на Arev (обратное слияние, 122-b9) — в силе", "N1", "M1",
         [rej(s["P"]), opus(s["Arev"], "x"), tests(s["N1"])], False, "«вернуть» (reject)")
    case("reject на P, «принять» другого argus на Pv (тот же код, 117-b3-2) — в силе", "N1", "M1",
         [rej(s["P"]), opus(s["Pv"], "x"), tests(s["N1"])], False, "«вернуть» (reject)")
    case("reject на A1, «принять» другого argus на A1 и перенос на N1 (122-b) — в силе", "N1", "M1",
         [opus(s["P"], "x"), rej(s["A1"]), opus(s["A1"], "x"), tests(s["N1"])], False, "«вернуть» (reject)")
    case("reject на Q, «принять» на QA после переименования в main (117-b3-2) — в силе", "QN", "M2",
         [opus(s["Q"], "x"), rej(s["Q"]), opus(s["QA"], "x"), tests(s["QN"])], False, "«вернуть» (reject)")
    case("reject на N1, тот же argus принял старый P (117-b7 K2) — в силе", "N1", "M1",
         [rej(s["N1"], "x"), opus(s["P"], "x", session="s-y"), tests(s["N1"])], False, "«вернуть» (reject)")
    case("amend после «вернуть» (122-b10) — в силе", "Nam", "M1",
         [opus(s["A1"], "x"), rej(s["Ram"]), tests(s["Nam"])], False, "«вернуть» (reject)")
    case("повтор слияния после reset (122-a10) — в силе", "Nredo", "M1",
         [opus(s["P"], "x"), rej(s["N1"]), tests(s["Nredo"])], False, "«вернуть» (reject)")
    case("откат правки после «вернуть» (122-a11-2) — старое «принять» не поднимается", "Nrev", "M1",
         [opus(s["N1"], "x"), rej(s["Rx"]), tests(s["Nrev"])], False, "«вернуть» (reject)")
    case("длинная история и reject (122-b-2) — в силе", "Nlong", "M1",
         [opus(s["P"], "x"), rej(s["P"]), tests(s["Nlong"])], False, "«вернуть» (reject)")
    case("reject на P, другой argus принял N1 с тем же кодом (правило 2, 0415b) — в силе", "N1", "M1",
         [rej(s["P"]), opus(s["N1"], "x"), tests(s["N1"])], False, "«вернуть» (reject)")
    case("reject на P, тот же argus принял N1 с перечнем — проходит", "N1", "M1",
         [rej(s["P"]), opus(s["N1"], "y", session="s-y"), tests(s["N1"])], True)
    case("свежее «принять» другого argus на NA после reject на R (код другой) — проходит (122-b10 зам. 1)", "NA",
         "M1", [rej(s["R"]), opus(s["NA"], "x"), tests(s["NA"])], True)
    # metis-0497 (Д1 ревью PR #149 r2): «вернули» — слово лида. Повторный круг (поле есть) снимает «вернуть» другого
    # argus, только если взял его отчёт; поле, назвавшее рецензента без «вернуть» на PR, — «принять» не в счёт
    again = lambda sha, returned, reported=(): dict(opus(sha, "x"), returned=list(returned), reported=list(reported))
    case("Д1: повторный круг x («вернули: y»), отчёт y не взят — «вернуть» y в силе", "NA", "M1",
         [rej(s["R"]), again(s["NA"], ["y/s-y"]), tests(s["NA"])], False, "«вернуть» (reject)")
    case("Д1: повторный круг x взял отчёт y — «вернуть» снято, проходит", "NA", "M1",
         [rej(s["R"]), again(s["NA"], ["y/s-y"], ["y/s-y"]), tests(s["NA"])], True)
    case("Д1: третий head (перенос с A на NA): отчёт y не взят — «вернуть» в силе", "NA", "M1",
         [opus(s["P"], "x"), rej(s["R"]), again(s["A"], ["y/s-y"]), tests(s["NA"])], False, "«вернуть» (reject)")
    case("Д1: третий head, отчёт y взят — переносится, проходит", "NA", "M1",
         [opus(s["P"], "x"), rej(s["R"]), again(s["A"], ["y/s-y"], ["y/s-y"]), tests(s["NA"])], True)
    got = case("поле «вернули» называет рецензента без «вернуть» на PR — отказ с причиной", "N1", "M1",
               [again(s["N1"], ["y/s-y"]), tests(s["N1"])], False, "поле «вернули»")
    check("отказ по полю называет пару и задачу", "вернули: y/s-y" in got[1] and "metis-0497" in got[1], got[1])
    case("«вернуть» y записано после «принять» с полем — поле врёт, отказ", "N1", "M1",
         [again(s["N1"], ["y/s-y"]), rej(s["P"]), tests(s["N1"])], False, "«вернуть» (reject)")
    case("поле «вернули» не врёт, «вернуть» y на N1 же — повторный круг тот же head: в силе", "N1", "M1",
         [rej(s["N1"]), again(s["N1"], ["y/s-y"], ["y/s-y"]), tests(s["N1"])], False, "«вернуть» (reject)")
    got = case("отказ «вернуть» называет head и правило снятия", "N1", "M1",
               [opus(s["P"], "x"), rej(s["Pv"]), tests(s["N1"])], False, f"на {s['Pv'][:12]}")
    check("отказ «вернуть» говорит, что оно привязано к PR", "привязано к PR" in got[1], got[1])
    # #134 r2 п.3: откат к коду P после «вернуть» R, снятого «принять» на исправленном A, — отказ называет отсечку
    got = case("откат к коду P после снятого «вернуть» R — «принять» P отсечено, отказ называет его", "N1", "M1",
               [opus(s["P"], "x"), opus(s["R"], "y", "reject"), opus(s["A"], "z", session="s-z"), tests(s["N1"])],
               False, "нет «принять»")
    check("отказ при отсечке называет «принять» P и «вернуть» R",
          "записано раньше «вернуть»" in got[1] and f"на {s['P'][:12]}" in got[1]
          and f"на {s['R'][:12]}" in got[1], got[1])
    # переполнение: 12 head с вердиктами, reject на самом старом (117-b2-2)
    many = [rej(s["R"])] + [opus("%040x" % i, "f%d" % i) for i in range(1, 11)] + [opus(s["A"], "x"), tests(s["NA"])]
    case("12 head, reject на самом старом, «принять» на исправленном A (117-b2-2) — в силе", "NA", "M1", many, False,
         "«вернуть» (reject)")
    # сливающий — рецензент перенесённого «принять»
    h.reset()
    kit_pr(h, s["N1"], s["M1"])
    h.seed(opus(s["P"], "L1", session="s-coord"), tests(s["N1"]))
    merge_case("сливающий — автор перенесённого «принять» — отказ",
               h.pre(merge(s["N1"]), role="hephaestus-pantheon", agent_id="L1", pdir=kit), False,
               "рецензент и сливающий")
    # журнал переноса не пишется — отказ
    h.reset()
    kit_pr(h, s["N1"], s["M1"])
    h.seed(opus(s["P"]), tests(s["N1"]))
    os.symlink(h.j("elsewhere.jsonl"), carry_file(h))
    merge_case("carry.jsonl — симлинк: перенос не записать — отказ", h.pre(merge(s["N1"]), pdir=kit), False,
               "не записать")
    check("через симлинк ничего не записано", not os.path.exists(h.j("elsewhere.jsonl")))


def t_carry_opus(h):
    """117-m: в защитах переносится только «принять» на Opus; Sonnet-«принять» не переносится и не мешает."""
    s = kit_history(h)
    kit = "projects/agent-kit"
    tests = rec("tests", "latark/agent-kit", None, s["N1"], "dev-opus")
    sonnet = dict(CHECKLIST, ran="модель: claude-sonnet-5, тесты")
    a = opus(s["P"])
    a["models"] = ["claude-sonnet-5"]
    for name, recs, allow, why, core in (
            ("A: ran Opus, модели транскрипта Sonnet — не переносится", [a, tests], False, "не на Opus", True),
            ("B: ran Sonnet — не переносится", [opus(s["P"], checklist=sonnet), tests], False, "не на Opus", True),
            ("C: Opus — переносится", [opus(s["P"]), tests], True, "", False),
            ("G: Sonnet на P и Opus другого argus на N1 — проходит",
             [opus(s["P"], checklist=sonnet), opus(s["N1"], "x"), tests], True, "", False),
            ("Sonnet-«принять» после reject того же argus на P не снимает", [opus(s["P"], "y", "reject", checklist=None),
             opus(s["P"], "y", checklist=sonnet), opus(s["Pv"], "x"), tests], False, "«вернуть» (reject)", True),
            # вне ядра (simplify п. 9) Sonnet переносится как любой argus
            ("не ядро: ran Sonnet — переносится", [opus(s["P"], checklist=sonnet), tests], True, "", False),
            ("не ядро: модели транскрипта Sonnet — переносится", [a, tests], True, "", False)):
        h.reset()
        kit_pr(h, s["N1"], s["M1"], core=core)
        h.seed(*recs)
        merge_case(f"защиты, 117-m {name}", h.pre(f"gh pr merge 7 --match-head-commit {s['N1']}", pdir=kit), allow, why)


def t_carry_product(h):
    """117-a2: в продукте проверка talos не переносится — нужна запись talos на новом head."""
    if not getattr(h, "broker_hist", None):
        p = h.j("projects/broker")
        H = Hist(p)
        H.br("t-base", h.sha["broker"])
        b = H.put({"app.py": CODE.format(1)}, "B")
        H.br("t-main", b)
        m1 = H.put({"other.py": "y = 1\n"}, "main")
        H.br("t-pr", b)
        pp = H.put({"app.py": CODE.format(2)}, "PR")
        n = H.merge(m1)
        git(p, "checkout", "-q", "main")
        h.broker_hist = {"M1": m1, "P": pp, "N": n}
    s = h.broker_hist
    cmd = f"gh pr merge 5 --match-head-commit {s['N']}"
    line = "2026-10-15 20:01 · athena-shop · latark/broker#5 ушло: налоги; откат: git revert abc"
    for name, talos, allow, why in (("talos только на P — отказ", s["P"], False, "нет проверки talos"),
                                    ("talos на N — проходит, «принять» перенесено", s["N"], True, "")):
        h.reset()
        h.ci(GREEN, name="broker", head=s["N"], baseRefOid=s["M1"])
        h.seed(rec("tests", "latark/broker", None, s["N"], "dev-opus"), rec("accept", "latark/broker", 5, s["P"]),
               rec("talos", "latark/broker", 5, talos, who="talos", agent_id="t1"))
        h.alert(line)
        merge_case(f"продукт (117-a2): {name}", h.pre(cmd, pdir="projects/broker"), allow, why)


def t_request_decision(h):
    """metis-0966, 0396, 0443 (вариант А): PreToolUse `pantheon merge request N -R repo` пишет в carry.jsonl решение
    kind "decision" — какие прошлые head с вердиктами argus с тем же кодом (same), какие посчитаны другими (differs).
    Проход владельца (pantheon merge.py) git не зовёт и судит по нему. Команда пропускается всегда."""
    s = kit_history(h)
    kit = "projects/agent-kit"
    p = h.j(kit)
    F = lambda t: ("100644", t.encode())
    lines = [f"d{i}\n" for i in range(30)]
    pr_d = "".join(lines[:20] + ["pr\n"] + lines[21:])
    bd = plumb(p, [s["B"]], {"d.txt": F("".join(lines))}, "main: d.txt")
    bd2 = plumb(p, [bd], {"d.txt": F("top\n" + "".join(lines))}, "main: строка над правкой PR")
    qd = plumb(p, [bd], {"d.txt": F(pr_d)}, "PR: правка d.txt")
    qdm = plumb(p, [qd, bd2], {"d.txt": F("top\n" + pr_d)}, "PR: подтянул main", src=bd2)
    qx = plumb(p, [bd], {"d.txt": F("".join(lines[:20] + ["other\n"] + lines[21:]))}, "PR: другой код")
    req = "pantheon merge request 7 -R latark/agent-kit"
    rej = lambda sha, aid="argus2", session="s-b": opus(sha, aid, "reject", checklist=None, session=session)

    def case(name, head, base, recs, cmd=req, cwd=None, view=None, extra_env=None):
        h.reset()
        kit_pr(h, head, base)
        if view:
            h.view["agent-kit"].update(view)
            for k in [k for k, v in view.items() if v is None]:
                del h.view["agent-kit"][k]
            h.write_view("agent-kit")
        h.seed(*recs)
        got = h.pre(cmd, pdir=kit, cwd=cwd, extra_env=extra_env)
        check(f"решение, {name}: команда пропущена", got[0] == "allow", got)
        return [x for x in carry_lines(h) if x.get("kind") == "decision"]

    got = case("тот же отпечаток", s["N1"], s["M1"], [opus(s["P"]), rej(s["P"]), opus(s["N1"], "argus3", session="s-c")])
    d = got[0] if len(got) == 1 else {}
    check("решение: отпечаток тот же — same=[P], differs пуст", d.get("same") == [s["P"]] and d.get("differs") == [], got)
    try:
        when = __import__("datetime").datetime.fromisoformat(d.get("time"))
    except (TypeError, ValueError):
        when = None
    check("решение: поля записи (repo, pr, sha, base, base_oid, by, время с поясом)",
          d.get("repo") == ["latark/agent-kit"] and d.get("pr") == 7 and d.get("sha") == s["N1"]
          and d.get("base") == "main" and d.get("base_oid") == s["M1"] and d.get("v") == 1
          and d.get("by") == {"agent_type": "domain-coordinator", "session_id": "s-coord", "agent_id": ""}
          and when is not None and when.tzinfo is not None, d)
    got = case("слияние с main (_merge_same)", qdm, bd2, [opus(qd)])
    check("решение: отпечаток другой, слияние то же — same", len(got) == 1 and got[0]["same"] == [qd]
          and got[0]["differs"] == [], got)
    got = case("тот же и другой код", qdm, bd2, [opus(qd), rej(qx)])
    check("решение: другой код — differs, порядок — новые первыми", len(got) == 1 and got[0]["same"] == [qd]
          and got[0]["differs"] == [qx], got)
    check("решение (metis-0784): head того же кода (same) и не предок (qx) — не в delta", got[0].get("delta") == [], got)
    # дельта мелкой правки поверх проверенного head (metis-0784): вне ядра — в delta, ядро и сборка окон — нет
    for name, change, want in (("мелкая правка вне ядра", {"e.txt": F("e\n")}, True),
                               ("правка ядра", {"plugins/guard/x.txt": F("x\n")}, False),
                               ("правка сборки окон", {"plugins/pantheon/lib/pantheon.py": F("x\n")}, False),
                               ("правка длиннее предела", {"e.txt": F("e\n" * 201)}, False),
                               ("переименование вне ядра", {"d.txt": None, "d3.txt": F(pr_d)}, False)):
        qn = plumb(p, [qd], change, "PR: " + name)
        got = case(f"дельта: {name}", qn, bd, [opus(qd)])
        check(f"решение (metis-0784): {name} — код другой (differs), delta {'[qd]' if want else 'пуст'}",
              len(got) == 1 and got[0]["differs"] == [qd] and got[0].get("delta") == ([qd] if want else []), got)
    # Д2 argus #420: head старше окна _carry_heads (CARRY_HEADS более новых head с вердиктами) — без отпечатка и не в delta
    qn = plumb(p, [qd], {"e.txt": F("e\n")}, "PR: мелкая правка поверх старого head")
    newer = [plumb(p, [bd], {"d.txt": F("".join(lines[:20] + [f"n{i}\n"] + lines[21:]))}, f"PR: другой код {i}")
             for i in range(8)]
    got = case("дельта: head вне окна сверки", qn, bd, [opus(qd)] + [rej(x, f"argus{i}", f"s-n{i}")
                                                                    for i, x in enumerate(newer)])
    check("решение (metis-0784): head старше 8 последних — не в delta, хоть он предок и дельта мелкая",
          len(got) == 1 and qd not in got[0].get("delta", [qd]) and got[0].get("delta") == [], got)
    got = case("клон другого репозитория", qdm, bd2, [opus(qd)], cwd="projects/tg-read")
    check("решение: git не сверить (не клон) — запись с пустыми same и differs и причиной", len(got) == 1
          and got[0]["same"] == [] and got[0]["differs"] == [] and got[0]["why"], got)
    alt = os.path.join(p, ".git", "objects", "info", "alternates")
    os.makedirs(os.path.dirname(alt), exist_ok=True)
    with open(alt, "w") as fh:
        fh.write(os.path.join(p, ".git", "objects") + "\n")
    try:
        got = case("alternates в клоне", qdm, bd2, [opus(qd)])
    finally:
        os.remove(alt)
    check("решение: objects/info/alternates — не сверено: same и differs пусты, причина названа", len(got) == 1
          and got[0]["same"] == [] and got[0]["differs"] == [] and any("alternates" in w for w in got[0]["why"]), got)
    got = case("два номера одного PR", qdm, bd2, [opus(qd)], cmd="pantheon merge request 7 7 -R Latark/Agent-Kit")
    check("решение: номер дважды — одна запись, repo в нижнем регистре", len(got) == 1
          and got[0]["repo"] == ["latark/agent-kit"], got)
    # metis-1153: окно для перезапуска после слияния (--restart <окно>) — не номер PR, решение пишется как без него
    for where in ("pantheon merge request 7 -R latark/agent-kit --restart athena-shop",
                  "pantheon merge request --restart athena-shop 7 -R latark/agent-kit"):
        got = case(f"--restart: {where}", qdm, bd2, [opus(qd)], cmd=where)
        check(f"решение (metis-1153): {where} — запись есть, same=[qd]", len(got) == 1 and got[0]["pr"] == 7
              and got[0]["same"] == [qd], got)
    for name, recs, kw in (
            ("вердикты только на head", [opus(qdm), rej(qdm)], {}),
            ("вердиктов нет", [rec("tests", "latark/agent-kit", None, qdm, "dev-opus")], {}),
            ("«принять» не от argus", [rec("accept", "latark/agent-kit", 7, qd, "dev-opus")], {}),
            ("вердикт на другом PR", [opus(qd, pr=8)], {}),
            ("cd в команде", [opus(qd)], {"cmd": f"cd {p} && {req}"}),
            ("без -R", [opus(qd)], {"cmd": "pantheon merge request 7"}),
            ("-R без репозитория", [opus(qd)], {"cmd": "pantheon merge request 7 -R"}),
            ("номер не число", [opus(qd)], {"cmd": "pantheon merge request 7x -R latark/agent-kit"}),
            ("номер с нулём впереди", [opus(qd)], {"cmd": "pantheon merge request 07 -R latark/agent-kit"}),
            ("номер переменной", [opus(qd)], {"cmd": 'pantheon merge request "$N" -R latark/agent-kit'}),
            ("номера нет", [opus(qd)], {"cmd": "pantheon merge request -R latark/agent-kit"}),
            ("не request", [opus(qd)], {"cmd": "pantheon merge status 7 -R latark/agent-kit"}),
            ("gh pr view не ответил", [opus(qd)], {"view": {"headRefOid": "не sha"}}),
            ("base PR неизвестна", [opus(qd)], {"view": {"baseRefName": None}})):
        got = case(name, qdm, bd2, recs, **kw)
        check(f"решение: {name} — записи нет", got == [], got)
        if name in ("вердиктов нет", "номер не число", "номер переменной"):
            log = open(h.j("gh.log")).read() if os.path.exists(h.j("gh.log")) else ""
            check(f"решение: {name} — gh pr view не зовётся", "pr view" not in log, log)
    got = [x for x in carry_lines(h) if x.get("kind") == "decision-miss"]
    check("решение (metis-1181): base PR неизвестна — след decision-miss с причиной", len(got) == 1
          and got[0]["pr"] == 7 and got[0]["sha"] == qdm and "gh pr view" in got[0]["why"][0], got)
    # срок хука (GUARD_TEST_DEADLINE тест только поднимает) — подменой _gh_fits: gh не зовётся, решения нет, есть след
    mg = _load_merge_gate("merge_gate_request_decision")
    calls = []
    mg._gh_fits = lambda *a: False
    mg._pr_view = lambda repo, pr, *a: calls.append(("view", pr)) or {}
    mg.append_carry = lambda r: calls.append(("carry", r))
    mg._decision({}, [opus(qd)], "latark/agent-kit", 7, p, {})
    check("решение: срок хука не вмещает gh — gh pr view не зовётся, решения нет, след decision-miss (metis-1181)",
          len(calls) == 1 and calls[0][0] == "carry" and calls[0][1]["kind"] == "decision-miss"
          and "срок хука" in calls[0][1]["why"][0], calls)


def t_decision_deadline(h):
    """metis-1181: gh решения шлюза при заявке — со своим сроком DECISION_GH_TIMEOUT (3 с), а не GH_TIMEOUT (6 с). До
    срока хука осталось 5 с: два gh по 6 с не влезли бы (решения не было, #461 14.11), по 3 с — влезают, решение
    записано. Осталось 3 с — не влезает и короткий: решения нет, но есть след decision-miss с причиной."""
    import types
    s = kit_history(h)
    p = h.j("projects/agent-kit")
    F = lambda t: ("100644", t.encode())
    lines = [f"d{i}\n" for i in range(30)]
    pr_d = "".join(lines[:20] + ["pr\n"] + lines[21:])
    bd = plumb(p, [s["B"]], {"d.txt": F("".join(lines))}, "main: d.txt")
    bd2 = plumb(p, [bd], {"d.txt": F("top\n" + "".join(lines))}, "main: строка над правкой PR")
    qd = plumb(p, [bd], {"d.txt": F(pr_d)}, "PR: правка d.txt")
    qdm = plumb(p, [qd, bd2], {"d.txt": F("top\n" + pr_d)}, "PR: подтянул main", src=bd2)
    for left, want in ((5.0, "decision"), (3.0, "decision-miss")):
        mg = _load_merge_gate(f"merge_gate_decision_deadline_{int(left)}")
        mg.signal = types.SimpleNamespace(ITIMER_REAL=0, getitimer=lambda which, left=left: (left, 0.0))
        calls, out = [], []
        mg._pr_view = lambda repo, pr, timeout=mg.GH_TIMEOUT, calls=calls: calls.append(("view", timeout)) or {
            "headRefOid": qdm, "baseRefName": "main", "baseRefOid": bd2}
        real_tip = mg._base_tip

        def tip(repo, branch, memo=None, timeout=mg.GH_TIMEOUT, real_tip=real_tip, calls=calls):
            if memo is not None:
                return real_tip(repo, branch, memo, timeout)
            calls.append(("tip", timeout))
            return bd2
        mg._base_tip = tip
        mg.append_carry = out.append
        mg._decision({}, [opus(qd)], "latark/agent-kit", 7, p, {})
        kinds = [r.get("kind") for r in out]
        first = out[0] if out else {}
        check(f"metis-1181: до срока хука {left:g} с — запись {want}", kinds == [want], out)
        if want == "decision":
            check("metis-1181: решение — код qd тот же (same), сверка не урезана", first.get("same") == [qd]
                  and first.get("why") == [], out)
            check(f"metis-1181: gh pr view и вершина base — со сроком {mg.DECISION_GH_TIMEOUT} с, вершина — один раз",
                  calls == [("view", mg.DECISION_GH_TIMEOUT), ("tip", mg.DECISION_GH_TIMEOUT)], calls)
        else:
            check("metis-1181: след без фактов о коде — причина «срок хука», gh не зовётся", calls == []
                  and "срок хука" in (first.get("why") or [""])[0] and "same" not in first, (calls, out))


def t_carry_rej(h):
    """argus #375 Б1 (проба probe.py): перенос слиянием не обходит «вернуть». X вернул qc, Z принял qc, X принял qa,
    head снова код qc и подтянул main со сдвигом строк (qcm): отпечаток qcm ≠ qc, но qc, слитый с merge-base qcm, —
    ровно qcm. «Вернуть» X держится и в правиле 3 _lifts (принято на третьем head), и в правиле 2 (принято на sha)."""
    s = kit_history(h)
    kit = "projects/agent-kit"
    p = h.j(kit)
    F = lambda t: ("100644", t.encode())
    tests = lambda sha: rec("tests", "latark/agent-kit", None, sha, "dev-opus")
    lines = [f"c{i}\n" for i in range(30)]
    pr_c = "".join(lines[:20] + ["pr\n"] + lines[21:])
    fix_c = "".join(lines[:20] + ["fixed\n"] + lines[21:])
    bc = plumb(p, [s["B"]], {"c.txt": F("".join(lines))}, "main: c.txt")
    bc2 = plumb(p, [bc], {"c.txt": F("top\n" + "".join(lines))}, "main: строка над правкой PR")
    bc3 = plumb(p, [bc], {"other.txt": F("o\n")}, "main: другой файл")
    qc = plumb(p, [bc], {"c.txt": F(pr_c)}, "PR: правка c.txt")
    qa = plumb(p, [bc], {"c.txt": F(fix_c)}, "PR: исправление")
    qcm = plumb(p, [qc, bc2], {"c.txt": F("top\n" + pr_c)}, "PR: вернулся к qc и подтянул main", src=bc2)
    qcr = plumb(p, [qc, bc3], {"other.txt": F("o\n")}, "PR: вернулся к qc, main не трогал c.txt", src=qc)
    qam = plumb(p, [qa, bc2], {"c.txt": F("top\n" + fix_c)}, "PR: исправление и подтянул main", src=bc2)

    def case(name, head, base, recs, allow, why=""):
        h.reset()
        kit_pr(h, head, base)
        h.seed(*recs)
        merge_case(name, h.pre(f"gh pr merge 7 --match-head-commit {head}", pdir=kit), allow, why)

    x_rej = opus(qc, "x", "reject", checklist=None, session="s-x")
    z_acc = opus(qc, "z", session="s-z")
    x_acc = opus(qa, "x", session="s-x")
    case("Б1 контроль: только «принять» Z на qc, qcm — переносится", qcm, bc2, [z_acc, tests(qcm)], True)
    case("Б1 контроль: X вернул qc, Z принял qc, X принял qa; main не трогал файл — отказ", qcr, bc3,
         [x_rej, z_acc, x_acc, tests(qcr)], False, "«вернуть» (reject)")
    case("Б1 контроль: X вернул qc, Z принял qc; qcm — отказ", qcm, bc2, [x_rej, z_acc, tests(qcm)], False,
         "«вернуть» (reject)")
    case("Б1 правило 3: X вернул qc, Z принял qc, X принял qa; qcm (код qc + main) — отказ", qcm, bc2,
         [x_rej, z_acc, x_acc, tests(qcm)], False, "«вернуть» (reject)")
    case("Б1 правило 2: X вернул qc, Z принял qcm (код qc + main) — отказ", qcm, bc2,
         [x_rej, opus(qcm, "z", session="s-z"), tests(qcm)], False, "«вернуть» (reject)")
    case("Б1 правило 2 контроль: X вернул qc, Z принял qam (иной код + main) — сливает", qam, bc2,
         [x_rej, opus(qam, "z", session="s-z"), tests(qam)], True)
    case("Б1 правило 3 контроль: X вернул qc, X принял qa; qam (код qa + main) — сливает", qam, bc2,
         [x_rej, x_acc, tests(qam)], True)


CASES = [t_carry_gate, t_carry_opus, t_carry_product, t_request_decision, t_decision_deadline, t_carry_rej]


if __name__ == "__main__":
    sys.exit(main(CASES))
