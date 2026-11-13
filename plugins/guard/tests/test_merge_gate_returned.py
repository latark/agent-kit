#!/usr/bin/env python3
"""Запор слияния guard, часть «returned»: поле «вернули» и перенос «принять» через правки без кода: разбор, r2.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py; разрез metis-1119.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_returned.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403


def t_returned_unit(h):
    """metis-0497 (Д1 ревью PR #149 r2): поле «вернули» — слово лида. pair_match, returned_lie, returned_lifts и правила
    2 и 3 _lifts напрямую; agent_rounds — по транскрипту субагента."""
    mg = _load_merge_gate("merge_gate_returned")
    A, B = ("aaaa1111bbbb", "cccc2222dddd"), ("eeee3333ffff", "99998888aaaa")
    ra = rec("reject", "latark/agent-kit", 7, "a" * 40, agent_id=A[0], session=A[1])
    pa = "aaaa1111/cccc2222"
    for pair, want in ((pa, True), (pa.upper(), True), ("aaaa1111", True), ("aaaa1111/dddd", False),
                       ("eeee3333/cccc2222", False), ("", False), ("aaaa1111/", False), ("/cccc2222", False),
                       ("aaaa1111/cccc2222/x", False), (None, False)):
        check(f"pair_match({pair!r}) — {want}", mg.pair_match(pair, ra) is want)
    check("pair_match: у записи нет agent_id — не совпадает", not mg.pair_match("aaaa", dict(ra, by={"agent_id": ""})))
    check("pair_match: пара с сессией, у записи сессии нет — не совпадает",
          not mg.pair_match(pa, dict(ra, by={"agent_id": A[0]})))

    def acc(sha, who=B, **kw):
        return dict(rec("accept", "latark/agent-kit", 7, sha, agent_id=who[0], session=who[1]), **kw)

    b = acc("b" * 40, returned=[pa])
    check("returned_lie: «вернуть» вернувшего раньше — поле не врёт", mg.returned_lie(b, [ra, b]) == [])
    check("returned_lie: «вернуть» вернувшего после «принять» — врёт", mg.returned_lie(b, [b, ra]) == [pa])
    check("returned_lie: у названного только «принять» — врёт",
          mg.returned_lie(b, [acc("a" * 40, A), b]) == [pa])
    b2 = acc("b" * 40, returned=[pa, "12345678/9abcdef0"])
    check("returned_lie: врёт только про пару без «вернуть»", mg.returned_lie(b2, [ra, b2]) == ["12345678/9abcdef0"])
    for label, x in (("поля нет", acc("b" * 40)), ("поле пустое", acc("b" * 40, returned=[])),
                     ("поле не список", acc("b" * 40, returned=pa))):
        check(f"returned_lie: {label} — []", mg.returned_lie(x, [ra, x]) == [])
    # Д4 argus #382, вариант Б: своя пара рецензента (agent — его, сессия с опечаткой, #286) не сверяется
    own = acc("b" * 40, A, returned=["aaaa1111/eeee0000"])
    check("returned_lie Д4: своя пара с чужой сессией — не врёт", mg.returned_lie(own, [own]) == [])
    own2 = acc("b" * 40, A, returned=["aaaa1111/eeee0000", "12345678/9abcdef0"])
    check("returned_lie Д4: своя пара не сверяется, чужая без «вернуть» — врёт",
          mg.returned_lie(own2, [own2]) == ["12345678/9abcdef0"])
    check("returned_lie Д4: пара чужого agent с сессией рецензента — врёт",
          mg.returned_lie(acc("b" * 40, A, returned=["eeee3333/cccc2222"]), []) == ["eeee3333/cccc2222"])
    check("_empty_field_hint: поле без пар — названо в отказе с metis-0497",
          "без пар agent8/сессия8 (metis-0497)" in mg._empty_field_hint([ra, acc("b" * 40, returned=[])]))
    check("_empty_field_hint: поле с парами или без поля — пусто",
          mg._empty_field_hint([ra, acc("b" * 40, returned=[pa]), acc("c" * 40)]) == "")
    check("returned_lifts: поля «вернули» нет (свежий argus) — снимает", mg.returned_lifts(acc("b" * 40), ra))
    check("returned_lifts: поле есть, отчётов не брал — не снимает", not mg.returned_lifts(b, ra))
    check("returned_lifts: поле есть, reported не список — не снимает",
          not mg.returned_lifts(acc("b" * 40, returned=[pa], reported=pa), ra))
    check("returned_lifts: взял отчёт другого — не снимает",
          not mg.returned_lifts(acc("b" * 40, returned=[pa], reported=["12345678/9abcdef0"]), ra))
    check("returned_lifts: взял отчёт вернувшего — снимает", mg.returned_lifts(acc("b" * 40, returned=[pa],
                                                                                    reported=[pa]), ra))
    # правила 2 и 3 _lifts: код каждого head свой, merge-base общая (fp без merged — _code_of False)
    R, S, T = "a" * 40, "b" * 40, "c" * 40
    fp = {R: ("f-r", "m"), S: ("f-s", "m"), T: ("f-t", "m")}.get
    for label, kw, want in (("свежий argus", {}, True), ("повторный круг без отчёта", {"returned": [pa]}, False),
                            ("повторный круг с отчётом вернувшего", {"returned": [pa], "reported": [pa]}, True)):
        check(f"_lifts правило 2 (на sha, код другой): {label} — {want}", mg._lifts(acc(S, **kw), ra, S, fp) is want)
        check(f"_lifts правило 3 (третий head): {label} — {want}", mg._lifts(acc(T, **kw), ra, S, fp) is want)
    check("_lifts: сам вернувший с полем «вернули» без отчёта — снимает (правило 1, свой вердикт)",
          mg._lifts(acc(S, A, returned=[pa]), ra, S, fp))

    # agent_rounds: поручения лида (первое и SendMessage), уведомления о задачах — нет; отчёты — только успешные
    proj = h.j("cc-projects/-r")
    sid, aid = "s-coord", "ag1"
    path = os.path.join(proj, sid, "subagents", f"agent-{aid}.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    event = {"transcript_path": os.path.join(proj, sid + ".jsonl"), "session_id": sid, "agent_id": aid}

    def user(content, **kw):
        return dict({"type": "user", "message": {"role": "user", "content": content}}, **kw)

    def bash(tid, cmd):
        return {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd}}]}}

    def result(tid, err=False):
        b = {"type": "tool_result", "tool_use_id": tid, "content": "ok"}
        if err:
            b["is_error"] = True
        return user([b])

    def write(*entries):
        with open(path, "w") as fh:
            fh.write("не json\n")
            for e in entries:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        return mg.agent_rounds(event, "latark/agent-kit", 7)

    rep_ = lambda pair, repo="latark/agent-kit", pr=7: f"pantheon review report {repo} {pr} {pair}"
    got = write(user(f"Повторный круг: прошлый head {'a' * 40}, правка: x.py:1, вернули: {pa}, 12345678/9abcdef0"),
                user("вернули: deadbeef/deadbeef", isMeta=True),
                user("вернули: 01234567/01234567", origin={"kind": "task-notification"}),
                bash("t1", rep_(pa)), result("t1"),
                bash("t2", rep_("12345678/9abcdef0")), result("t2", err=True),
                bash("t3", rep_("12345678/9abcdef0", pr=8)), result("t3"),
                bash("t4", rep_("12345678/9abcdef0", repo="latark/other")), result("t4"),
                bash("t5", rep_("12345678/9abcdef0") + " && true"), result("t5"),
                bash("t6", rep_("12345678/9abcdef0")), user("t6 без tool_result-списка"))
    check("agent_rounds: поле из первого поручения; isMeta и task-notification не поручение; отчёт — только успешный "
          "на этот PR", got == (["12345678/9abcdef0", pa], [pa]), got)
    got = write(user("Полный круг PR 7"), user(f"Повторный круг, вернули: {pa}", origin={"kind": "coordinator"}),
                user("ещё глянь README", origin={"kind": "coordinator"}))
    check("agent_rounds: поле из сообщения лида (SendMessage), следующее сообщение без поля его не снимает",
          got == ([pa], []), got)
    got = write(user("Полный круг PR 7"), bash("t1", rep_(pa)), result("t1"))
    check("agent_rounds: поля нет ни в одном поручении — returned None (свежий argus)", got == (None, [pa]), got)
    got = write(user(f"вернули: {pa}» и дальше"), user(f"Узкий повтор, вернули: {pa.upper()}"))
    check("agent_rounds: пары без регистра и без повторов, «» и хвост не мешают", got == ([pa], []), got)
    # 0991 (Д1–Д3, Д5 argus #382)
    got = write(user(f"Повторный круг, Вернули: {pa}"))
    check("0991 Д1: «Вернули:» с заглавной — поле есть", got == ([pa], []), got)
    got = write(user(f"ВЕРНУЛИ: {pa}"))
    check("0991 Д1: «ВЕРНУЛИ:» — поле есть", got == ([pa], []), got)
    got = write(user("Повторный круг, вернули: <agent_id/сессия, …>"))
    check("0991 Д3: поле без пар — [] (повторный круг, строже), а не None", got == ([], []), got)

    def bg(tid, cmd):
        e = bash(tid, cmd)
        e["message"]["content"][0]["input"]["run_in_background"] = True
        return e
    short = "abcd/ef01"
    got = write(user("Полный круг"),
                bash("o1", rep_("aaaaaaa1") + " --out /tmp/r.md"), result("o1"),
                bash("o2", rep_("aaaaaaa2") + " --out=/tmp/r.md"), result("o2"),
                bash("o3", rep_(short) + " 2>&1"), result("o3"),
                bash("o4", rep_("aaaaaaa4") + " > /tmp/r.md 2>&1"), result("o4"),
                bash("o5", "pantheon review report --out /tmp/r.md latark/agent-kit 7 aaaaaaa5"), result("o5"))
    check("0991 Д2: --out, --out=, 2>&1, > файл, --out до позиционных, пара из 4 знаков — в reported",
          got == (None, sorted(["aaaaaaa1", "aaaaaaa2", short, "aaaaaaa4", "aaaaaaa5"])), got)
    got = write(user("Полный круг"),
                bash("n1", rep_("bbbbbbb1") + " --out"), result("n1"),
                bash("n2", rep_("bbbbbbb2") + " --out a --out b"), result("n2"),
                bash("n3", rep_("bbbbbbb3") + " --out=--x"), result("n3"),
                bash("n4", rep_("bbb")), result("n4"),
                bash("n5", rep_("bbbbbbb5") + " extra"), result("n5"),
                bash("n6", rep_("bbbbbbb6") + " | tee x"), result("n6"),
                bash("n7", rep_("bbbbbbb7") + " > $(x)"), result("n7"),
                bg("n8", rep_("bbbbbbb8")), result("n8"),
                bash("n9", rep_("bbbbbbb9")), dict(result("n9"), toolUseResult={"backgroundTaskId": "b1"}))
    check("0991 Д2/Д5: --out без пути, дважды, пара из 3 знаков, лишнее слово, |, $(), фон — не в reported",
          got == (None, []), got)
    check("agent_rounds: главная сессия (без agent_id) — None",
          mg.agent_rounds(dict(event, agent_id=None), "latark/agent-kit", 7) is None)
    os.remove(path)
    check("agent_rounds: транскрипта субагента нет — None", mg.agent_rounds(event, "latark/agent-kit", 7) is None)


def t_returned_record(h):
    """metis-0497: хук пишет в запись вердикта returned и reported из транскрипта субагента; без поля — не пишет."""
    sha = h.sha["agent-kit"]
    proj = h.j("cc-projects/-p")
    path = os.path.join(proj, "s-coord", "subagents", "agent-ag1.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def run(commission, kind="accept"):
        with open(path, "w") as fh:
            for e in ({"type": "user", "message": {"role": "user", "content": commission}},
                      {"type": "assistant", "message": {"model": "claude-opus-5-5", "role": "assistant", "content": [
                          {"type": "tool_use", "id": "t1", "name": "Bash",
                           "input": {"command": "pantheon review report latark/agent-kit 7 aaaa1111/cccc2222"}}]}},
                      {"type": "user", "message": {"role": "user", "content": [
                          {"type": "tool_result", "tool_use_id": "t1", "content": "отчёт"}]}}):
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        h.reset()
        args = "--opened a --unchecked c --ran \"модель: claude-opus-5-5, тесты\"" if kind == "accept" else "--why x"
        h.post(f"pantheon review {kind} latark/agent-kit 7 {sha} {args}", "argus", agent_id="ag1",
               transcript=os.path.join(proj, "s-coord.jsonl"))
        got = [r for r in h.read() if r["kind"] == kind]
        return got[0] if got else {}

    r = run("Повторный круг: вернули: aaaa1111/cccc2222, 12345678/9abcdef0")
    check("«принять» повторного круга: returned и reported в записи",
          r.get("returned") == ["12345678/9abcdef0", "aaaa1111/cccc2222"] and r.get("reported") == ["aaaa1111/cccc2222"],
          r)
    r = run("Полный круг PR 7")
    check("свежий argus (поля нет): returned и reported не пишутся", "returned" not in r and "reported" not in r, r)


def t_carry_unit(h):
    """Отпечаток собственного диффа PR (_fingerprint) и сверка git (_carry_git) — напрямую."""
    s = kit_history(h)
    mg = _load_merge_gate("merge_gate_carry")
    kit = h.j("projects/agent-kit")
    gd, why = mg._carry_git(kit, "latark/agent-kit", s["M1"])
    check("_carry_git: клон репозитория PR — git dir", gd and why is None, why)

    def fp(head, base=s["M1"]):
        got = mg._fingerprint(gd, base, head)
        return got[0] if got and got[0] else None

    ref = fp(s["P"])
    check("отпечаток P считается", isinstance(ref, str) and len(ref) == 64, ref)
    for name, base in (("N1", s["M1"]), ("A1", s["M1"]), ("Pv", s["M1"]), ("Arev", s["M1"]), ("Nlong", s["M1"]),
                       ("Nam", s["M1"]), ("Nredo", s["M1"]), ("Nrev", s["M1"]), ("N2", s["M2"])):
        check(f"отпечаток {name} = P (номер версии и подтянутый main)", fp(s[name], base) == ref, name)
    check("отпечаток P от base M2 — тот же", fp(s["P"], s["M2"]) == ref)
    for name, why_ in (("out", "правка кода"), ("ws", "только пробел"),
                       ("wsin", "отступ в правленой строке"), ("bin", "двоичный файл"),
                       ("field", "другое поле plugin.json (117-b1)"), ("mjson", "marketplace.json"),
                       ("mode", "режим файла"), ("newfile", "пустой новый файл"),
                       ("evil", "правка внутри слияния (117-a7)"), ("moddel", "файл, удалённый main, вернули (117-b3)"),
                       ("side", "слияние побочной ветки (122-b9)"), ("R", "правка, которую вернули"),
                       ("Rx", "правка x.py (122-a11-2)")):
        got = fp(s[name])
        check(f"отпечаток {name} ≠ P: {why_}", got is not None and got != ref, got)
    for name, why_ in (("dup", "два ключа version (117-b1)"), ("numver", "version числом (117-b1)")):
        got = mg._fingerprint(gd, s["M1"], s[name])
        check(f"{name}: отпечатка нет — {why_}", got[0] is None and got[1], got)
    got = mg._fingerprint(gd, s["M1"], s["orphan"])
    check("head без общей истории с base — отпечатка нет (нет merge-base)", got[0] is None and "merge-base" in got[1], got)
    got = mg._fingerprint(gd, s["M1"], "d" * 40)
    check("head нет в git — отпечатка нет", got[0] is None and "нет в git" in got[1], got)
    fa, fr, fq, fqa = (mg._fingerprint(gd, s["M2"], s[x]) for x in ("A", "R", "Q", "QA"))
    check("A и R — одна merge-base, разный код", fa[1] == fr[1] and fa[0] != fr[0], (fa, fr))
    check("Q и QA (переименование в main) — разные merge-base", fq[1] != fqa[1], (fq, fqa))
    # сверка git папки (_carry_git)
    got = mg._carry_git(h.j("projects/tg-read"), "latark/agent-kit", s["M1"])
    check("_carry_git: папка — клон другого репозитория — не переносится", got[0] is None and "не клон" in got[1], got)
    got = mg._carry_git(os.path.join(kit, ".git"), "latark/agent-kit", s["M1"])
    check("_carry_git: папка .git клона (117-b3) — git dir", got[0] and got[1] is None, got)
    got = mg._carry_git(kit, "latark/agent-kit", "d" * 40)
    check("_carry_git: коммита base PR нет в git — git fetch", got[0] is None and "git fetch" in got[1], got)
    got = mg._carry_git(h.root, "latark/agent-kit", s["M1"])
    check("_carry_git: не репозиторий — не переносится", got[0] is None and got[1], got)
    shallow = os.path.join(kit, ".git", "shallow")
    with open(shallow, "w") as fh:
        fh.write(s["B"] + "\n")
    try:
        got = mg._carry_git(kit, "latark/agent-kit", s["M1"])
        check("_carry_git: неполная история (.git/shallow, 122-b11) — не переносится",
              got[0] is None and "неполная история" in got[1], got)
    finally:
        os.remove(shallow)
    grafts = os.path.join(kit, ".git", "info", "grafts")
    os.makedirs(os.path.dirname(grafts), exist_ok=True)
    with open(grafts, "w") as fh:
        fh.write(s["N1"] + "\n")
    try:
        got = mg._carry_git(kit, "latark/agent-kit", s["M1"])
        check("_carry_git: info/grafts (117-b) — не переносится", got[0] is None and "grafts" in got[1], got)
    finally:
        os.remove(grafts)
    git(kit, "replace", s["out"], s["N1"])
    try:
        check("git replace (117-b): подменённый head не выдаёт себя за N1", fp(s["out"]) != ref)
    finally:
        git(kit, "replace", "-d", s["out"])
    # «вернуть» привязано к PR (_held): fp — словарь sha → (отпечаток, merge-base)
    S, P, R, A, X = "5" * 40, "6" * 40, "7" * 40, "8" * 40, "9" * 40
    prints = {S: ("f-s", "mb2"), P: ("f-s", "mb1"), R: ("f-r", "mb1"), A: ("f-a", "mb1"), X: ("f-s", "mb2")}

    def held(*recs, f=prints, sha=S):
        return [r["sha"] for r in mg._held(list(recs), sha, lambda x: f.get(x))]

    rj = opus(R, "y", "reject", checklist=None)
    check("reject на R, позже accept другого argus на A (тот же base, другой код) — снят",
          held(rj, opus(A, "x")) == [])
    check("тот же порядок, но отпечаток A неизвестен — в силе", held(rj, opus(A, "x"), f=dict(prints, **{A: None})) == [R])
    check("тот же порядок, отпечаток R неизвестен — в силе", held(rj, opus(A, "x"), f=dict(prints, **{R: None})) == [R])
    check("accept на A раньше reject — в силе", held(opus(A, "x"), rj) == [R])
    check("accept на A с тем же кодом, что R (тот же base) — в силе",
          held(rj, opus(A, "x"), f=dict(prints, **{A: ("f-r", "mb1")})) == [R])
    check("accept на A с другой merge-base (117-b3-2) — в силе",
          held(rj, opus(A, "x"), f=dict(prints, **{A: ("f-a", "mb9")})) == [R])
    check("код S тот же, что у R (откат исправления) — accept на A не снимает",
          held(rj, opus(A, "x"), f=dict(prints, **{S: ("f-r", "mb2")})) == [R])
    check("свежее accept на S другого argus — снимает reject с R", held(rj, opus(S, "x")) == [])
    check("accept того же рецензента на R — снимает", held(rj, opus(R, "y")) == [])
    check("правило 1: accept того же рецензента на R без перечня — не снимает (0415b)",
          held(rj, opus(R, "y", checklist=None)) == [R])
    check("правило 2: accept другого argus на S, код S равен коду R — не снимает (0415b)",
          held(rj, opus(S, "x"), f=dict(prints, **{S: ("f-r", "mb2")})) == [R])
    check("правило 2: код S не посчитан — accept другого argus на S не снимает",
          held(rj, opus(S, "x"), f=dict(prints, **{S: None})) == [R])
    check("правило 2: код R не посчитан — accept другого argus на S не снимает",
          held(rj, opus(S, "x"), f=dict(prints, **{R: None})) == [R])
    check("правило 2: тот же рецензент принял S с кодом R — снимает (сам передумал)",
          held(rj, opus(S, "y"), f=dict(prints, **{S: ("f-r", "mb2")})) == [])
    check("правило 2: тот же рецензент на S без перечня — не снимает", held(rj, opus(S, "y", checklist=None)) == [R])
    check("accept другого argus на R — в силе (metis-0158)", held(rj, opus(R, "x")) == [R])
    rs = opus(S, "y", "reject", checklist=None)
    check("reject на S, accept другого argus на S — в силе (metis-0158)", held(rs, opus(S, "x")) == [S])
    check("reject на S, тот же argus принял P с тем же кодом (117-b7 K2) — в силе", held(rs, opus(P, "y")) == [S])
    check("reject на S, тот же argus принял X с тем же кодом (117-b7 K2) — в силе", held(rs, opus(X, "y")) == [S])
    check("reject на S, тот же argus принял S — снят", held(rs, opus(S, "y")) == [])
    check("accept без перечня другого argus на S reject с R не снимает", held(rj, opus(S, "x", checklist=None)) == [R])
    # переносится только accept с перечнем на head с тем же отпечатком
    car = mg._carried([opus(P, "x"), opus(R, "z"), opus(X, "w", checklist=None), opus(S, "v")], S,
                      lambda x: prints.get(x))
    check("_carried: P (тот же отпечаток) — да, R — нет, без перечня — нет, сам S — нет",
          [r["sha"] for r in car] == [P], car)
    check("_carried: отпечаток S неизвестен — ничего",
          mg._carried([opus(P, "x")], S, lambda x: None if x == S else prints.get(x)) == [])
    check("_carried: reject не переносится (и с перечнем)",
          mg._carried([opus(P, "x", "reject", checklist=dict(CHECKLIST))], S, lambda x: prints.get(x)) == [])
    heads = ["%040x" % i for i in range(1, 13)]
    got = mg._carry_heads([opus(x, "a") for x in heads], S)
    check(f"_carry_heads: из 12 head — {mg.CARRY_HEADS} последних, старые — без отпечатка (117-b2-2)",
          got == set(heads[-mg.CARRY_HEADS:]) | {S}, sorted(got))


def t_carry_r2(h):
    """Замечания argus к #134 (metis-0415 r2): core.worktree не сужает дифф до .git/ (п.1), «принять», записанное
    раньше снятого «вернуть», не переносится (п.2), criss-cross — две merge-base — без отпечатка (п.3)."""
    s = kit_history(h)
    mg = _load_merge_gate("merge_gate_carry_r2")
    kit = h.j("projects/agent-kit")
    gd, why = mg._carry_git(kit, "latark/agent-kit", s["M1"])
    check("r2: _carry_git — git dir", gd and why is None, why)

    def fp(head, base=s["M1"]):
        return mg._fingerprint(gd, base, head)[0]

    ref = fp(s["P"])
    # п.1: core.worktree = корень клона → у git префикс .git/, и pathspec «.» значил бы только .git/, а
    # diff.relative — дифф только .git/ (без --no-relative)
    git(kit, "config", "core.worktree", kit)
    git(kit, "config", "diff.relative", "true")
    try:
        n1 = fp(s["N1"])
        check("п.1 core.worktree: отпечаток N1 — как у P (номер версии и main)", n1 == ref, n1)
        for name in ("out", "side", "evil", "newfile"):
            got = fp(s[name])
            check(f"п.1 core.worktree: отпечаток {name} ≠ N1 (правка вне .git/ видна)", got is not None and got != n1,
                  got)
    finally:
        git(kit, "config", "--unset", "core.worktree")
        git(kit, "config", "--unset", "diff.relative")
    # п.2: x «принять» A (код X), y «вернуть» R (код Y), z «принять» F (код Z) снимает R; N — снова код X
    A, R, F, N = "a" * 40, "b" * 40, "c" * 40, "d" * 40
    prints = {A: ("X", "mb1"), R: ("Y", "mb1"), F: ("Z", "mb1"), N: ("X", "mb2")}
    look = lambda x: prints.get(x)
    rj = opus(R, "y", "reject", checklist=None)
    v = [opus(A, "x"), rj, opus(F, "z")]
    check("п.2: «вернуть» R снято «принять» F (код N — не код R)", mg._held(v, N, look) == [])
    got = [r["sha"] for r in mg._carried(v, N, look)]
    check("п.2: «принять» A записано раньше «вернуть» R — не переносится на N с кодом A", got == [], got)
    got = [r["sha"] for r in mg._carried([rj, opus(A, "x")], N, look)]
    check("п.2: «принять» A записано после «вернуть» R — переносится", got == [A], got)
    got = [r["sha"] for r in mg._carried([opus(A, "x"), rj, opus(R, "y")], N, look)]
    check("п.2: «вернуть» R снял сам рецензент на R — «принять» A до него переносится", got == [A], got)
    got = [r["sha"] for r in mg._carried([opus(A, "x"), rj, opus(R, "y", checklist=None)], N, look)]
    check("п.2: тот же рецензент на R без перечня отсечку не снимает — A не переносится", got == [], got)
    got = [r["sha"] for r in mg._carried([opus(A, "x"), rj, opus(R, "w")], N, look)]
    check("п.2: «принять» другого argus на R не снимает отсечку — A не переносится", got == [], got)
    # r3 п.1: тот же рецензент снял «вернуть» R, но «принять» на другом head F — отсечка в силе (обычный поток:
    # исправление на новом коммите), откат N к коду A по старому «принять» A не проходит
    v3 = [opus(A, "x"), rj, opus(F, "y")]
    got = [r["sha"] for r in mg._carried(v3, N, look)]
    check("п.2 r3: «вернуть» R снял сам рецензент, но на другом head F — A не переносится", got == [], got)
    cut = []
    mg._carried(v3, N, look, cut)
    got = [(a["sha"], r["sha"]) for a, r in cut]
    check("п.2 r3: отсечённое «принять» A и отсёкшее «вернуть» R — для текста отказа", got == [(A, R)], got)
    cut = []
    mg._carried([rj, opus(A, "x")], N, look, cut)
    check("п.2 r3: «принять» после «вернуть» — не отсечено, cut пуст", cut == [], cut)
    # п.3: крест слияний — у head PR и base две merge-base
    H = Hist(kit)
    H.br("t-cc-main", s["B"])
    x1 = H.put({"cc-main.py": "m = 1\n"}, "main: правка")
    H.br("t-cc-pr", s["B"])
    y1 = H.put({"code.py": CODE.format(2)}, "PR: правка")
    H.br("t-cc-main2", x1)
    base2 = H.merge(y1)
    H.br("t-cc-pr2", y1)
    H.merge(x1)
    head2 = H.put({"cc-pr.py": "p = 1\n"}, "PR: ещё правка")
    git(kit, "checkout", "-q", "-f", "main")
    git(kit, "clean", "-qfdx")
    mbs = git(kit, "merge-base", "--all", base2, head2).split()
    check("п.3: крест слияний — две merge-base", len(mbs) == 2, mbs)
    got = mg._fingerprint(gd, base2, head2)
    check("п.3: две merge-base — отпечатка нет, «принять» не переносится",
          got[0] is None and "единственной merge-base" in got[1], got)
    # п.4: вставка после 5-го и 6-го блока периодического файла — у patch-id без номеров строк одна и та же
    per = ["A\n", " x\n"] * 20
    H.br("t-per", s["B"])
    bp = H.put({"p.txt": "".join(per)}, "main: периодический файл")
    q5 = H.put({"p.txt": "".join(per[:10] + [" y\n"] + per[10:])}, "PR: после 5-го блока")
    H.br("t-per6", bp)
    q6 = H.put({"p.txt": "".join(per[:12] + [" y\n"] + per[12:])}, "PR: после 6-го блока")
    lines = [f"c{i}\n" for i in range(30)]
    H.br("t-shift", s["B"])
    bc = H.put({"c.txt": "".join(lines)}, "main: файл c.txt")
    H.br("t-shift-main", bc)
    bc2 = H.put({"c.txt": "top\n" + "".join(lines)}, "main: строка над правкой PR")
    H.br("t-shift-pr", bc)
    qc = H.put({"c.txt": "".join(lines[:20] + ["pr\n"] + lines[21:])}, "PR: правка c.txt")
    qcm = H.merge(bc2)
    git(kit, "checkout", "-q", "-f", "main")
    git(kit, "clean", "-qfdx")
    f5, f6 = mg._fingerprint(gd, bp, q5)[0], mg._fingerprint(gd, bp, q6)[0]
    check("п.4: вставка в другом месте периодического файла — отпечаток другой", f5 and f6 and f5 != f6, (f5, f6))
    fc, fcm = mg._fingerprint(gd, bc, qc)[0], mg._fingerprint(gd, bc2, qcm)[0]
    check("цена: main правил файл PR (строка над правкой) — отпечаток другой (позовут argus)",
          fc and fcm and fc != fcm, (fc, fcm))


CASES = [t_returned_unit, t_returned_record, t_carry_unit, t_carry_r2]


if __name__ == "__main__":
    sys.exit(main(CASES))
