#!/usr/bin/env python3
"""Слияние PR ядра по Touch ID (metis-0285, lib/merge.py): поддельные gh и помощник окна.

Запуск: python3 -I plugins/pantheon/tests/test_merge.py  (код выхода 0 — все прошли)
Проверяет на временных папках: палец → строка merge-approve в owner-log и `gh pr merge N --match-head-commit <sha>
--merge`, заявка снята (одно применение); отказ, новый head, 24 ч → слияния нет, заявка снята; шлюз заново на тот же
head перед окном (новый «вернуть», нет тестов) → окна нет; CI идёт, владельца нет → ждёт; окно без ответа — повтор
позже; окно не показать → уведомление с `merge run --click`, щелчок сливает; из окна Claude Code — отказ; строку
согласия принимает шлюз guard (настоящий merge_gate.owner_approved); тик запускает проход, только когда есть заявки.
Фраза «слей #N <hex>» в owner-log (metis-0959, test_phrase_*): та же строка согласия без окна; чужой head, PR без
заявки, старше 2 ч, повтор, пометка, не первая строка, неоднозначность, обёртки NOT_OWNER настоящего хука ctx.py — нет.
Файл разрезан на части для параллельного прогона (общее — tests/_merge_common.py): здесь слияние по пальцу, шлюз, заявки; остальное — test_merge_window.py, _ci, _env, _batch.
"""
# ruff: noqa: F403, F405
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_common import *  # noqa: F403


# --- случаи -----------------------------------------------------------------------------------------------------------

def test_finger_merges_exact_sha():
    b = Box()
    r = b.request()
    req = b.req()
    check("заявка: стоит, SHA — head PR сейчас, файл 0600, папка 0700",
          r.returncode == 0 and req and req["sha"] == SHA and req["pr"] == PR
          and oct(os.stat(b.req_path()).st_mode & 0o777) == "0o600"
          and oct(os.stat(os.path.dirname(b.req_path())).st_mode & 0o777) == "0o700", b.outs[-1])
    check("заявка: окна и слияния нет — только плановый проход", not b.windows() and not b.merges(), b.calls("gh"))
    r = b.run()
    w = b.windows()
    check("палец: одно окно «Слить repo#N (sha7), файлов N, ядро: <файлы>. argus ×2 ✓, CI ✓. Заголовок: «…»»",
          len(w) == 1 and w[0][0] == f"Слить {REPO}#{PR} ({SHA[:7]}), файлов 2, ядро: {CORE_FILE}. argus ×2 ✓, "
          f"CI ✓. Заголовок: «{TITLE}»" and w[0][1] == "120", w)
    check("палец: gh pr merge N -R repo --match-head-commit <sha> --merge — ровно один раз",
          b.merges() == [["pr", "merge", str(PR), "-R", REPO, "--match-head-commit", SHA, "--merge"]], b.merges())
    check("gh: GH_REPO и GH_HOST из окружения убраны",
          all(c["env"] == [] for c in b.calls("gh")), b.calls("gh"))
    lines = b.approve_lines()
    check("палец: строка «<время> merge-approve repo#N sha» в owner-log/merge-approve.log, файл 0600",
          len(lines) == 1 and re.fullmatch(r"\S+ merge-approve " + re.escape(f"{REPO}#{PR} {SHA}"), lines[0])
          and oct(os.stat(os.path.join(b.state, "owner-log", "merge-approve.log")).st_mode & 0o777) == "0o600", lines)
    ok, out = guard_approves(b, REPO, PR, SHA)
    check("шлюз guard принимает строку согласия на этот SHA", ok, out)
    ok2, out2 = guard_approves(b, REPO, PR, SHA2)
    check("шлюз guard не принимает её для другого SHA", not ok2, out2)
    check("палец: заявка снята, журнал — window, merged", b.req() is None and b.log()[-2:] == ["window", "merged"],
          b.log())
    b.run()
    check("одно применение: второй проход не сливает и окна не показывает",
          len(b.merges()) == 1 and len(b.windows()) == 1, (b.merges(), b.windows()))


def test_refusal():
    b = Box()
    b.request()
    b.set("touchid-rc", 1)
    b.run()
    check("отказ: окно было, слияния нет, строки согласия нет, заявка снята",
          len(b.windows()) == 1 and not b.merges() and not b.approve_lines() and b.req() is None, b.outs[-1])
    b.set("touchid-rc", 0)
    b.run()
    check("отказ: следующий проход окна не показывает (заявки нет)", len(b.windows()) == 1 and not b.merges())


def test_new_head():
    b = Box()
    b.request()
    b.view(SHA2)
    b.gate_ok(SHA2)   # и шлюз на новом коммите пройден — всё равно новая заявка
    b.run()
    check("новый head: окна и слияния нет, заявка снята, тревога «новая заявка»",
          not b.windows() and not b.merges() and b.req() is None and "нужна новая заявка" in b.alerts(),
          (b.outs[-1], b.alerts()))


def test_expired():
    b = Box()
    b.request()
    b.run(t=T0 + 24 * 3600 + 1)
    check("24 ч: окна и слияния нет, заявка снята, тревога",
          not b.windows() and not b.merges() and b.req() is None and "24 ч" in b.alerts(), b.outs[-1])
    b2 = Box()
    b2.request()
    b2.run(t=T0 + 24 * 3600 - 60)
    check("до 24 ч — сливает", len(b2.merges()) == 1, b2.outs[-1])


def test_gate_rechecked():
    b = Box()
    b.request()
    b.add("reject", sid="s3", aid="a3")
    b.run()
    check("шлюз заново: «вернуть» после заявки → окна нет, слияния нет, заявка снята",
          not b.windows() and not b.merges() and b.req() is None and "вернуть" in b.alerts(), b.outs[-1])
    b = Box()
    b.request()
    b.add("reject", sid="s1", aid="a1")   # тот же рецензент передумал
    b.run()
    check("шлюз заново: последний вердикт рецензента — «вернуть» → окна нет", not b.windows() and not b.merges())
    b = Box()
    b.request()
    b.view(SHA, draft=True)
    b.run()
    check("шлюз заново: PR стал черновиком → окна нет", not b.windows() and not b.merges() and b.req() is None)
    b = Box()
    b.request()
    b.view(SHA, state="MERGED")
    b.run()
    check("PR уже слит → окна нет, заявка снята", not b.windows() and not b.merges() and b.req() is None)
    b = Box()
    b.request()
    b.view(SHA, checks=ci("SUCCESS", "FAILURE"))
    b.run()
    check("CI упал → окна нет, заявка снята", not b.windows() and not b.merges() and b.req() is None
          and "FAILURE" in b.alerts(), b.alerts())


def test_gate_batch():
    """metis-1050 (было metis-0758): PR пачки (ветка batch/<story>) проходит шлюз прохода как любой другой — при
    зелёном CI хватает любой записи tests на head, полного набора не требуется (он идёт ночью на main)."""
    narrow = "pantheon review test -- python3.14 -I plugins/pantheon/scripts/run-tests.py --affected plugins/guard"
    b = Box()
    b.records = []
    b.add("tests", who="", cmd=narrow)
    b.add("accept", sid="s1", aid="a1")
    b.add("accept", sid="s2", aid="a2")
    b.view(SHA, head={"headRefName": "batch/metis-0754"})
    b.request()
    b.run()
    check("1050: пачка, на head только узкая запись, CI зелёный — сливает", len(b.merges()) == 1,
          (b.outs[-1], b.alerts()))


def test_ci_billing_narrow():
    """metis-1050: CI не запускался из-за лимита минут — проход засчитывает и узкую запись `--affected` (у ядра и
    пачки тоже), если её база — merge-base head и вершины base, а карта — sha256 файла карты в дереве head
    (narrow_gh_problem, GitHub API); иначе заявка снята с причиной."""
    blocked = [dict(c, conclusion="FAILURE", notes=[billing_note()], job=JOB_IDLE) for c in ci("SUCCESS", "SUCCESS")]
    mapb = '{"v": 3}'
    mp = hashlib.sha256(mapb.encode()).hexdigest()
    cmd = (FULL_TESTS_CMD.split(" -- ", 1)[1].replace("heavy ", "").replace("run-tests.py", "run-tests.py --affected "
           "--base " + "c" * 40))

    def box(rec=None, setup=()):
        b = Box()
        b.records = []
        b.add("accept", sid="s1", aid="a1")
        b.add("accept", sid="s2", aid="a2")
        b.add("tests", sha=SHA, who="", cmd=cmd, **{"files": ["guard/test_guard.py"], "map": mp, **(rec or {})})
        b.request()
        b.set("gh-map", mapb)
        for name, value in setup:
            b.set(name, value)
        b.view(SHA, checks=blocked, head={"headRefName": "batch/metis-1048"})
        b.run()
        return b

    b = box()
    check("лимит, узкая запись от merge-base, карта head → окно и слияние", len(b.merges()) == 1
          and "узкий прогон" in b.windows()[0][0], (b.outs[-1], b.alerts()))
    for name, setup, rec in (("merge-base другая", (("gh-mb", "d" * 40),), None),
                             ("сбой gh на compare", (("gh-mb-fail", ""),), None),
                             ("вершина base не получена", (("gh-tip-fail", ""),), None),
                             ("карта в записи не та", (), {"map": "0" * 64}),
                             ("без files", (), {"files": []})):
        b = box(rec, setup)
        check(f"лимит, узкая запись — {name} → окна нет, заявка снята", not b.windows() and not b.merges()
              and b.req() is None and "годной узкой" in b.alerts(), b.alerts())


def test_gate_other_heads():
    """metis-0465: «вернуть» на другом head PR в силе и в шлюзе владельца, как в шлюзе guard; «принять» до него не
    в счёт (откат force-push на старый head с двумя «принять»)."""
    def box(*adds, differs=()):
        b = Box()
        b.request()
        for kind, sha, sid in adds:
            b.add(kind, sha=sha, sid=sid, aid="a" + sid[1:])
        if differs:
            b.decide(differs=differs)
        b.run()
        return b

    b = box(("reject", SHA2, "s3"))
    check("0465: «вернуть» на другом head, после него ни одного «принять» — окна нет, заявка снята, тревога",
          not b.windows() and not b.merges() and b.req() is None and "вернуть" in b.alerts(), (b.outs[-1], b.alerts()))
    b = box(("reject", SHA2, "s3"), ("accept", SHA, "s1"), differs=[SHA2])
    check("0465: «принять» на SHA после «вернуть» (код SHA2 другой) снимает его, но второе «принять» записано до — "
          "1 из 2",
          not b.windows() and not b.merges() and "1 из 2" in b.alerts() and "раньше «вернуть»" in b.alerts(),
          b.alerts())
    b = box(("reject", SHA2, "s3"), ("accept", SHA, "s1"), ("accept", SHA, "s2"), differs=[SHA2])
    check("0465: два свежих «принять» на SHA после «вернуть» на head с другим кодом (решение шлюза) — сливает",
          len(b.merges()) == 1, (b.outs[-1], b.alerts()))
    b = box(("reject", SHA2, "s3"), ("accept", SHA2, "s3"))
    check("0465: «вернуть» снял сам рецензент на том же head — отсечки нет, «принять» на SHA в силе — сливает",
          len(b.merges()) == 1, (b.outs[-1], b.alerts()))
    b = box(("reject", SHA2, "s3"), ("accept", "f" * 40, "s4"))
    check("0465: «принять» другого argus на третьем head «вернуть» не снимает — окна нет",
          not b.windows() and not b.merges() and "вернуть" in b.alerts(), b.alerts())
    b = box(("reject", SHA, "s3"), ("accept", SHA, "s4"))
    check("0465: «вернуть» на SHA, «принять» другого argus на тот же SHA — в силе (metis-0158)",
          not b.windows() and not b.merges() and "вернуть" in b.alerts(), b.alerts())
    b = box(("reject", SHA, "s3"), ("accept", SHA, "s1"), ("accept", SHA, "s2"))
    check("0465: «вернуть» на SHA и два «принять» других argus после него — в силе, не перекрыто числом",
          not b.windows() and not b.merges() and "в силе" in b.alerts(), b.alerts())
    b = Box()
    b.request()
    b.add("reject", sha=SHA2, pr=PR + 1, sid="s3", aid="a3")
    b.run()
    check("0465: «вернуть» на другом PR — не мешает", len(b.merges()) == 1, (b.outs[-1], b.alerts()))
    b = Box()
    b.request()
    b.add("reject", sha=SHA2, who="dev-opus", sid="s3", aid="a3")
    b.run()
    check("0465: запись reject не от argus — не в счёт", len(b.merges()) == 1, (b.outs[-1], b.alerts()))


def test_gate_returned():
    """metis-0497 (Д1 ревью PR #149 r2): поле «вернули» — слово лида, и в шлюзе владельца, как в шлюзе guard.
    «Принять» повторного круга (поле есть) снимает «вернуть» другого argus, только если взяло его отчёт (reported);
    поле, назвавшее рецензента без «вернуть» на PR, — «принять» не в счёт."""
    def box(*adds):
        b = Box()
        b.request()
        b.records = []
        b.add("tests", who="")
        for kind, sha, sid, extra in adds:
            b.add(kind, sha=sha, sid=sid, aid="a" + sid[1:], **extra)
        b.decide(differs=[SHA2])   # код SHA2 другой (metis-0966): снять «вернуть» может и другой argus
        b.run()
        return b

    back, took = {"returned": ["a3/s3"]}, {"returned": ["a3/s3"], "reported": ["a3/s3"]}
    b = box(("reject", SHA2, "s3", {}), ("accept", SHA, "s1", back), ("accept", SHA, "s2", back))
    check("0497: «вернуть» a3, оба «принять» с «вернули: a3», отчёта a3 не брали — в силе, окна нет",
          not b.windows() and not b.merges() and "вернуть" in b.alerts(), (b.outs[-1], b.alerts()))
    b = box(("reject", SHA2, "s3", {}), ("accept", SHA, "s1", took), ("accept", SHA, "s2", took))
    check("0497: взяли отчёт a3 — «вернуть» снято, сливает", len(b.merges()) == 1, (b.outs[-1], b.alerts()))
    b = box(("reject", SHA2, "s3", {}), ("accept", SHA, "s1", back), ("accept", SHA, "s2", {}))
    check("0497: свежий argus без поля снимает «вернуть», как раньше — сливает", len(b.merges()) == 1,
          (b.outs[-1], b.alerts()))
    b = box(("accept", SHA, "s1", {"returned": ["a9/s9"]}), ("accept", SHA, "s2", {}))
    check("0497: «вернули: a9», а «вернуть» a9 на PR нет — «принять» не в счёт, 1 из 2",
          not b.windows() and not b.merges() and "1 из 2" in b.alerts(), (b.outs[-1], b.alerts()))
    b = box(("accept", SHA, "s1", {"returned": ["a3/s3"]}), ("reject", SHA2, "s3", {}),
            ("accept", SHA, "s1", {"returned": ["a3/s3"]}), ("accept", SHA, "s2", {}))
    check("0497: «вернуть» a3 записано между — второе «принять» s1 поле не врёт, свежий s2 снимает — сливает",
          len(b.merges()) == 1, (b.outs[-1], b.alerts()))
    # Д4 argus #382, вариант Б: своя пара рецензента (agent тот же, сессия с опечаткой) не сверяется с журналом
    b = box(("accept", SHA, "s1", {"returned": ["a1/zz"]}), ("accept", SHA, "s2", {}))
    check("Д4: «вернули: a1/zz» у самого a1 — пара своя, «принять» в счёт — сливает", len(b.merges()) == 1,
          (b.outs[-1], b.alerts()))
    b = box(("accept", SHA, "s1", {"returned": ["a1/zz", "a9/s9"]}), ("accept", SHA, "s2", {}))
    check("Д4: своя пара и чужая без «вернуть» — «принять» не в счёт, 1 из 2",
          not b.merges() and "1 из 2" in b.alerts(), (b.outs[-1], b.alerts()))


def test_gate_base():
    """metis-0965: «принять» засчитывается только на той base PR, на которой записано; без поля base (запись до
    0965) — не в счёт; «вернуть» на другой base — в силе."""
    def box(bases, view_base="main", reject=None):
        b = Box()
        b.request()
        b.records = []
        b.add("tests", who="")
        if reject is not None:
            b.add("reject", sha=SHA, sid="s3", aid="a3", base=reject)
        for i, base in enumerate(bases, 1):
            b.add("accept", sha=SHA, sid=f"s{i}", aid=f"a{i}", base=base)
        b.view(SHA, base=view_base)
        b.run()
        return b
    b = box(["main", "main"])
    check("0965: оба «принять» на base main, PR в main — сливает", len(b.merges()) == 1, (b.outs[-1], b.alerts()))
    b = box(["main", "dev"])
    check("0965: одно «принять» на base dev, PR в main — 1 из 2", not b.merges() and "1 из 2" in b.alerts(),
          (b.outs[-1], b.alerts()))
    b = box(["dev", "dev"])
    check("0965: оба «принять» на dev, PR перевели в main — 0 из 2", not b.merges() and "0 из 2" in b.alerts(),
          (b.outs[-1], b.alerts()))
    b = box(["main", None])
    check("0965: «принять» без base (до 0965) — не в счёт, 1 из 2", not b.merges() and "1 из 2" in b.alerts(),
          (b.outs[-1], b.alerts()))
    b = box(["main", "main"], view_base=None)
    check("0965: base PR неизвестна — «принять» не в счёт, не сливает", not b.merges(), (b.outs[-1], b.alerts()))
    b = box(["main", "main"], reject="dev")
    check("0965: «вернуть» на другой base — в силе, не сливает", not b.merges() and "вернуть" in b.alerts(),
          (b.outs[-1], b.alerts()))



def test_gate_decision():
    """metis-0966, 0396, 0443 (вариант А): код прошлых head — из решения шлюза guard при `pantheon merge request`
    (carry.jsonl, kind decision). Без решения другой коммит — неизвестный код: второй argus «вернуть» не снимает,
    «принять» не переносится. Решение — только на этот head, нынешнюю base PR и не старше суток."""
    def box(adds, *decisions):
        b = Box()
        b.request()
        b.records = []
        b.add("tests", who="")
        for kind, sha, sid in adds:
            b.add(kind, sha=sha, sid=sid, aid="a" + sid[1:])
        for d in decisions:
            b.decide(**d)
        b.run()
        return b

    held = [("reject", SHA2, "s3"), ("accept", SHA, "s1"), ("accept", SHA, "s2")]
    b = box(held)
    check("0966: «вернуть» на SHA2, два свежих «принять» других argus на SHA, решения нет (rebase с тем же кодом?) — "
          "в силе, окна нет", not b.windows() and not b.merges() and "в силе" in b.alerts()
          and "merge request" in b.alerts(), (b.outs[-1], b.alerts()))
    b = box(held, {"same": [SHA2]})
    check("0966: решение — у SHA2 тот же код (rebase) — «вернуть» в силе", not b.merges() and "в силе" in b.alerts(),
          b.alerts())
    b = box(held, {"differs": [SHA2]})
    check("0966: решение — код SHA2 другой — «вернуть» снято, сливает", len(b.merges()) == 1, (b.outs[-1], b.alerts()))
    b = box(held, {"same": [SHA2], "differs": [SHA2]})
    check("0966: SHA2 и в same, и в differs (решение противоречит себе) — ни то ни другое, в силе",
          not b.merges() and "в силе" in b.alerts(), b.alerts())
    b = box(held, {"differs": [SHA2], "base": "dev"})
    check("0966: решение на другой base PR — не в счёт, в силе", not b.merges() and "в силе" in b.alerts(), b.alerts())
    b = box(held, {"differs": [SHA2], "sha": SHA3})
    check("0966: решение на другой head — не в счёт, в силе", not b.merges() and "в силе" in b.alerts(), b.alerts())
    b = box(held, {"differs": [SHA2], "t": T0 - 24 * 3600 - 60})
    check("0966: решение старше суток — не в счёт, в силе", not b.merges() and "в силе" in b.alerts(), b.alerts())
    for name, tip, fail in (("вершина base ушла вперёд после решения", "c" * 40, False),
                            ("вершину base не получить от gh", None, True)):
        b = Box()
        b.request()
        b.records = []
        b.add("tests", who="")
        for kind, sha, sid in held:
            b.add(kind, sha=sha, sid=sid, aid="a" + sid[1:])
        b.decide(differs=[SHA2])
        open(os.path.join(b.rec, "gh-tip-fail" if fail else "gh-tip"), "w").write(tip or "")
        b.run()
        check(f"0966: {name} — решение не в счёт, в силе", not b.merges() and "в силе" in b.alerts(), b.alerts())
    b = box(held, {"differs": [SHA2], "t": T0 + 3600})
    check("0966: решение из будущего (часы сдвинуты) — не в счёт, в силе", not b.merges() and "в силе" in b.alerts(),
          b.alerts())
    b = box(held, {"differs": [SHA2], "pr": PR + 1})
    check("0966: решение на другой PR — не в счёт, в силе", not b.merges() and "в силе" in b.alerts(), b.alerts())
    b = box(held, {"differs": [SHA2]}, {"same": [SHA2]})
    check("0966: решает последнее решение на head (позже — тот же код) — в силе", not b.merges()
          and "в силе" in b.alerts(), b.alerts())
    # 0396: «принять» с head того же кода переносится (release.py, rebase без правок)
    moved = [("accept", SHA2, "s1"), ("accept", SHA2, "s2")]
    b = box(moved)
    check("0396: два «принять» на SHA2, решения нет — не переносится, 0 из 2 с причиной",
          not b.merges() and "0 из 2" in b.alerts() and "не перенесено" in b.alerts(), b.alerts())
    b = box(moved, {"same": [SHA2]})
    check("0396: решение — у SHA2 тот же код — «принять» переносится, сливает", len(b.merges()) == 1,
          (b.outs[-1], b.alerts()))
    b = box(moved, {"differs": [SHA2]})
    check("0396: код SHA2 другой — не переносится", not b.merges() and "0 из 2" in b.alerts(), b.alerts())
    b = box([("accept", SHA2, "s1"), ("accept", SHA, "s2")], {"same": [SHA2]})
    check("0396: одно «принять» на SHA и одно перенесённое — два рецензента, сливает", len(b.merges()) == 1,
          (b.outs[-1], b.alerts()))
    b = box([("accept", SHA2, "s1"), ("accept", SHA, "s1")], {"same": [SHA2]})
    check("0396: тот же рецензент на SHA2 и SHA — один рецензент, 1 из 2", not b.merges() and "1 из 2" in b.alerts(),
          b.alerts())
    b = box([("accept", SHA2, "s1"), ("reject", SHA3, "s3"), ("accept", SHA, "s4")], {"same": [SHA2], "differs": [SHA3]})
    check("0396: «принять» на SHA2 записано до «вернуть» (отсечка) — не переносится, 1 из 2",
          not b.merges() and "1 из 2" in b.alerts() and "раньше «вернуть»" in b.alerts(), b.alerts())


def test_gate_delta():
    """metis-0784: SHA — мелкая правка вне ядра поверх SHA2 (поле delta решения шлюза guard): «принять» на SHA2
    переносится, только если после него на SHA есть «принять» другого argus (дельта-круг); иначе — как раньше."""
    def box(adds, **d):
        b = Box()
        b.request()
        b.records = []
        b.add("tests", who="")
        for kind, sha, sid in adds:
            b.add(kind, sha=sha, sid=sid, aid="a" + sid[1:])
        if d:
            b.decide(**d)
        b.run()
        return b

    # правило delta_carry (Б1 обоих argus #420): полный круг на SHA2 (два рецензента), «принять» на SHA, вернувшие SHA2
    # приняли SHA; одно «принять» на SHA2 и одно «принять» дельты на SHA — не сливает при любом порядке
    one = [("accept", SHA2, "s1"), ("accept", SHA, "s3")]
    for name, adds in (("принять SHA2, потом SHA", one), ("сначала свежее на SHA", one[::-1])):
        b = box(adds, differs=[SHA2], delta=[SHA2])
        check(f"0784: на SHA2 одно «принять», на SHA «принять» дельты другого ({name}) — не сливает, 1 из 2",
              not b.merges() and "1 из 2" in b.alerts(), (b.outs[-1], b.alerts()))
    b = box([("accept", SHA2, "s1"), ("accept", SHA2, "s2"), ("accept", SHA, "s1")], differs=[SHA2], delta=[SHA2])
    check("0784: двое приняли SHA2, дельту принял один из них — его «принять» на SHA и перенос второго, 2 из 2",
          len(b.merges()) == 1, (b.outs[-1], b.alerts()))
    b = box([("accept", SHA2, "s1"), ("accept", SHA2, "s2"), ("accept", SHA, "s3")], differs=[SHA2], delta=[SHA2])
    check("0784: двое приняли SHA2, дельту — третий — сливает (argus ×3)", len(b.merges()) == 1
          and any("argus ×3" in w[0] for w in b.windows()), (b.outs[-1], b.alerts(), b.windows()))
    # порядок A: s1 принял SHA2, s2 вернул SHA2 и принял SHA — сливает при любом порядке записей
    pa1, rp2, as2 = ("accept", SHA2, "s1"), ("reject", SHA2, "s2"), ("accept", SHA, "s2")
    for adds in ([pa1, rp2, as2], [rp2, pa1, as2], [rp2, as2, pa1]):
        b = box(adds, differs=[SHA2], delta=[SHA2])
        check(f"0784: s2 вернул SHA2 и принял SHA, s1 принял SHA2 (порядок {[k[0][0] + k[2][1] for k in adds]}) — "
              "сливает", len(b.merges()) == 1, (b.outs[-1], b.alerts()))
    b = box([pa1, rp2, ("accept", SHA2, "s2"), ("accept", SHA, "s3")], differs=[SHA2], delta=[SHA2])
    check("0784: вернувший SHA2 принял снова SHA2, а не SHA — перенос не годится, 1 из 2", not b.merges()
          and "1 из 2" in b.alerts(), (b.outs[-1], b.alerts()))
    b = box([("accept", SHA2, "s1"), ("accept", SHA2, "s2"), ("reject", SHA3, "s4"), ("accept", SHA, "s4")],
            differs=[SHA2, SHA3], delta=[SHA2])
    check("0784: «вернуть» на SHA3 вне delta, вернувший принял SHA — отсечка держит «принять» на SHA2 до него, 1 из 2",
          not b.merges() and "1 из 2" in b.alerts(), (b.outs[-1], b.alerts()))
    b = box([("accept", SHA2, "s1"), ("reject", SHA2, "s2"), ("accept", SHA, "s2")], differs=[SHA2])
    check("0784: то же, SHA2 не в delta — отсечка по «вернуть» s2 прежняя, 1 из 2", not b.merges()
          and "1 из 2" in b.alerts(), b.alerts())
    b = box([("accept", SHA3, "s1"), ("reject", SHA2, "s2"), ("accept", SHA, "s2")], same=[SHA3], differs=[SHA2],
            delta=[SHA2])
    check("0784: на SHA2 полного круга нет (один вернувший), s1 принял SHA3 того же кода, что SHA — не полный круг, "
          "1 из 2", not b.merges() and "1 из 2" in b.alerts(), b.alerts())
    # Б argus #420 r2 (probe.py): A принял P, C — дельту на S′; отказ «1 из 2»; вливание main — S того же кода, S′ в
    # same: «принять» на head из same — дельта-круг, ядро целиком видел один argus
    b = box([("accept", SHA2, "s1"), ("accept", SHA3, "s3")], same=[SHA3], differs=[SHA2], delta=[SHA2])
    check("0784: «принять» на SHA2 и «принять» дельты на SHA3, SHA3 в same после вливания main — не сливает, 1 из 2",
          not b.merges() and "1 из 2" in b.alerts(), (b.outs[-1], b.alerts()))
    b = box([("accept", SHA3, "s1"), ("reject", SHA2, "s2"), ("accept", SHA, "s2")], same=[SHA3], differs=[SHA2])
    check("0784: то же, но SHA2 не в delta — откат к коду SHA3, принятому до «вернуть», отсечён, 1 из 2",
          not b.merges() and "1 из 2" in b.alerts() and "раньше «вернуть»" in b.alerts(), b.alerts())
    b = box([("accept", SHA2, "s1"), ("reject", SHA2, "s2"), ("accept", SHA3, "s2")], differs=[SHA2, SHA3],
            delta=[SHA2])
    check("0784: вернувший принял другой head, не сливаемый — не сливает", not b.merges(), b.alerts())
    b = box([("reject", SHA2, "s1"), ("accept", SHA, "s3")], differs=[SHA2], delta=[SHA2])
    check("0784: «вернуть» на SHA2, снятое другим argus на SHA, не переносится как голос — 1 из 2", not b.merges()
          and "1 из 2" in b.alerts(), b.alerts())
    b = box(one, differs=[SHA2])
    check("0784: SHA2 не в delta (код другой) — не переносится, 1 из 2", not b.merges() and "1 из 2" in b.alerts()
          and "pantheon review delta" in b.alerts(), b.alerts())
    for name, adds, d in (
            ("на SHA свежего «принять» нет", [("accept", SHA2, "s1"), ("accept", SHA2, "s2")], {}),
            ("свежее «принять» на SHA — того же рецензента", [("accept", SHA2, "s1"), ("accept", SHA, "s1")], {}),
            ("свежее «принять» на SHA записано раньше переносимого", [("accept", SHA, "s3"), ("accept", SHA2, "s1")], {}),
            ("поле delta не список", one, {"delta": 5}),
            ("«принять» на SHA2 записано до «вернуть» (отсечка)",
             [("accept", SHA2, "s1"), ("reject", SHA3, "s4"), ("accept", SHA, "s3")], {"differs": [SHA2, SHA3]})):
        b = box(adds, **{"differs": [SHA2], "delta": [SHA2], **d})
        got = "0 из 2" if name == "на SHA свежего «принять» нет" else "1 из 2"
        check(f"0784: {name} — не переносится, {got}", not b.merges() and got in b.alerts(), b.alerts())


def test_ci_billing_delta():
    """metis-0784: CI не запускался из-за лимита минут — проход засчитывает узкую запись на SHA от прошлого head SHA2
    (`--affected --base SHA2`), если SHA2 — предок SHA (compare: ahead, merge-base — SHA2), дельта мелкая и не задевает
    файлы шлюза, а на SHA2 есть запись полного набора или годная узкая (delta_gh_problem)."""
    blocked = [dict(c, conclusion="FAILURE", notes=[billing_note()], job=JOB_IDLE) for c in ci("SUCCESS", "SUCCESS")]
    mapb = '{"v": 3}'
    mp = hashlib.sha256(mapb.encode()).hexdigest()
    narrow = lambda base: (FULL_TESTS_CMD.split(" -- ", 1)[1].replace("heavy ", "")
                           .replace("run-tests.py", "run-tests.py --affected --base " + base))
    small = {"filename": "README.md", "additions": 3, "deletions": 1, "patch": "@@ x"}
    good = {"status": "ahead", "merge_base_commit": {"sha": SHA2}, "files": [small]}

    def box(cmp=good, prev="full", more=None, chain=()):
        b = Box()
        b.records = []
        b.add("accept", sid="s1", aid="a1")
        b.add("accept", sid="s2", aid="a2")
        b.add("tests", sha=SHA, who="", cmd=narrow(SHA2), files=["guard/test_guard.py"], map=mp)
        if prev == "full":
            b.add("tests", sha=SHA2, who="")
        elif prev:
            b.add("tests", sha=SHA2, who="", cmd=narrow(prev), files=["guard/test_guard.py"], map=mp)
        for head, base in chain:  # звенья цепочки дальше SHA2: узкая от base или полная (base None)
            b.add("tests", sha=head, who="", **({} if base is None else
                                                 {"cmd": narrow(base), "files": ["guard/test_guard.py"], "map": mp}))
        b.request()
        b.set("gh-map", mapb)
        b.set("gh-cmp.json", json.dumps({f"{SHA2}...{SHA}": cmp, **(more or {})}))
        b.view(SHA, checks=blocked)
        b.run()
        return b

    b = box()
    check("0784: лимит, узкая от прошлого head с полной записью на нём → окно и слияние", len(b.merges()) == 1
          and "узкий прогон" in b.windows()[0][0], (b.outs[-1], b.alerts()))
    b = box(prev="c" * 40)
    check("0784: на прошлом head узкая от merge-base → слияние", len(b.merges()) == 1, (b.outs[-1], b.alerts()))
    # цепочка дельт (Д1 argus #420): SHA ← SHA2 ← H[0] ← … ← H[k-1] с полной записью; звеньев k + 1, предел DELTA_DEPTH 4
    H = [c * 40 for c in "d0123"]
    for links, ok in ((4, True), (5, False)):
        hs = H[:links - 1]
        chain = [(hs[j], hs[j + 1] if j + 1 < len(hs) else None) for j in range(len(hs))]
        cmps = {f"{b_}...{h_}": dict(good, merge_base_commit={"sha": b_}) for h_, b_ in [(SHA2, hs[0])] + chain[:-1]}
        b = box(prev=hs[0], chain=chain, more=cmps)
        check(f"0784: цепочка дельт из {links} звеньев → {'слияние' if ok else 'окна нет, «цепочка дельт длиннее»'}",
              len(b.merges()) == 1 if ok else not b.merges() and "цепочка дельт длиннее" in b.alerts(),
              (b.outs[-1], b.alerts()))
    gate_file = dict(small, filename="plugins/guard/hooks/merge_gate.py")
    for name, kw in (("на прошлом head записи нет", {"prev": None}),
                     ("сравнение не получено (gh)", {"cmp": None}),
                     ("прошлый head не предок (diverged)", {"cmp": dict(good, status="diverged")}),
                     ("merge-base сравнения — не прошлый head", {"cmp": dict(good, merge_base_commit={"sha": SHA3})}),
                     ("дельта задевает файл шлюза", {"cmp": dict(good, files=[gate_file])}),
                     ("переименование вне ядра (Д1 argus #420)", {"cmp": dict(good, files=[dict(
                         small, previous_filename="docs/old.md", status="renamed")])}),
                     ("переименование из файла шлюза", {"cmp": dict(good, files=[dict(
                         small, previous_filename="plugins/guard/hooks/merge_gate.py", status="renamed")])}),
                     ("дельта 201 строка", {"cmp": dict(good, files=[dict(small, additions=150, deletions=51)])}),
                     ("файл без patch (двоичный)", {"cmp": dict(good, files=[{"filename": "a.bin", "additions": 0,
                                                                               "deletions": 0}])}),
                     ("300 файлов — предел ответа", {"cmp": dict(good, files=[
                         {"filename": f"f{i}", "additions": 0, "deletions": 0, "patch": ""} for i in range(300)])}),
                     ("цикл записей SHA ↔ SHA2", {"prev": SHA, "more": {f"{SHA}...{SHA2}": dict(
                         good, merge_base_commit={"sha": SHA})}})):
        b = box(**kw)
        check(f"0784: лимит, узкая от прошлого head — {name} → окна нет, заявка снята",
              not b.windows() and not b.merges() and "годной узкой" in b.alerts(), (b.outs[-1], b.alerts()))
    b = box(cmp=dict(good, files=[{"filename": f"f{i}", "additions": 0, "deletions": 0, "patch": ""}
                                  for i in range(299)]))
    check("0784: 299 файлов без строк — дельта годится, слияние", len(b.merges()) == 1, (b.outs[-1], b.alerts()))


def test_request_conflict_blocked():
    """metis-0987: `pantheon merge request` с конфликтом с base заявки не ставит; BLOCKED (защита ветки base) —
    заявка ждёт, окна нет."""
    b = Box()
    b.view(SHA, mergeable="CONFLICTING", merge_state="DIRTY")
    r = b.request()
    check("0987: конфликт с main при request — код 1, заявки нет, причина названа",
          r.returncode == 1 and b.req() is None and "конфликт с main" in r.stderr, (r.returncode, r.stderr))
    b = Box()
    b.view(SHA, merge_state="BLOCKED")
    r = b.request()
    check("0987: BLOCKED при request — заявка стоит, в выводе — защита ветки",
          r.returncode == 0 and b.req() is not None and "защита ветки" in r.stdout, (r.returncode, r.stdout, r.stderr))
    b.run()
    check("0987: BLOCKED — окна нет, слияния нет, заявка ждёт с причиной", not b.windows() and not b.merges()
          and b.req() is not None and "защита ветки" in str(b.req().get("waiting")), (b.outs[-1], b.req()))
    b.view(SHA)
    b.run()
    check("0987: защиту прошли (CLEAN) — окно и слияние", len(b.windows()) == 1 and len(b.merges()) == 1, b.outs[-1])
    b = Box()
    b.view(SHA, mergeable="UNKNOWN", merge_state="UNKNOWN")
    r = b.request()
    check("0987: GitHub ещё считает при request — заявка стоит", r.returncode == 0 and b.req() is not None,
          (r.returncode, r.stderr))


def test_request_refusals():
    b = Box()
    r = b.request(repo="latark/shop")
    check("заявка: репозиторий не из [merge_repos] metis-pantheon → отказ, файла нет",
          r.returncode != 0 and not os.path.exists(os.path.join(b.state, "merge-queue")), r.stderr)
    b = Box()
    b.records = []
    b.add("tests")
    b.add("accept", sid="s1", aid="a1")
    r = b.request()
    check("заявка: один «принять» из двух → отказ", r.returncode != 0 and b.req() is None and "1 из 2" in r.stderr,
          r.stderr)
    b = Box()
    b.records = []
    b.add("tests")
    b.add("accept", sid="s1", aid="a1")
    b.add("accept", sid="s2", aid="a2", ran="модель: claude-sonnet-4-6, тесты")
    r = b.request()
    check("заявка: «принять» не на Opus не засчитан → отказ", r.returncode != 0 and b.req() is None, r.stderr)
    # metis-0176: модель — из транскрипта argus (поле models от хука guard), а не только со слов ran
    for name, models, ok in (
            ("модели транскрипта Opus и та же, что в ran (и с датой) → засчитан",
             ["claude-opus-5-5-20261001"], True),
            ("модели нет в записи (транскрипта не было) → по ran, засчитан", None, True),
            ("по транскрипту Sonnet, в ran Opus → не засчитан", ["claude-sonnet-4-6"], False),
            ("по транскрипту Opus и Sonnet → не засчитан", ["claude-opus-5-5", "claude-sonnet-4-6"], False),
            ("по транскрипту другой Opus, чем в ran → не засчитан", ["claude-opus-4-1"], False),
            ("пустой список моделей → не засчитан", [], False),
            ("модели не списком → не засчитан", {"claude-opus-5-5": 1}, False)):
        b = Box()
        b.records = []
        b.add("tests")
        b.add("accept", sid="s1", aid="a1")
        b.add("accept", sid="s2", aid="a2", models=models)
        r = b.request()
        check("заявка: " + name, (r.returncode == 0 and b.req() is not None) if ok
              else (r.returncode != 0 and b.req() is None and "1 из 2" in r.stderr), r.stderr)
    b = Box()
    b.records = []
    b.add("tests")
    b.add("accept", sid="s1", aid="a1")
    b.add("accept", sid="s2", aid="a2", pr=PR + 1)   # тот же SHA, но вердикт на другой PR
    r = b.request()
    check("заявка: «принять» на другой PR тем же SHA не засчитан → отказ", r.returncode != 0 and b.req() is None
          and "1 из 2" in r.stderr, r.stderr)
    b = Box()
    b.records = []
    b.add("accept", sid="s1", aid="a1")
    b.add("accept", sid="s2", aid="a2")
    r = b.request()
    check("заявка: нет записи тестов шлюза → отказ", r.returncode != 0 and "тестов" in r.stderr, r.stderr)
    b = Box()
    os.remove(os.path.join(b.rec, "gh-view.json"))
    r = b.request()
    check("заявка: gh не ответил → отказ", r.returncode != 0 and b.req() is None, r.stderr)
    b = Box()
    for args in (["merge", "request", "7"], ["merge", "request", "x", "-R", REPO], ["merge", "request", "7", "-R",
                 "../x"], ["merge", "request", "7", "-R", REPO, "--x"], ["merge", "run", "--now"], ["merge"]):
        r = b.cli(args)
        check(f"разбор: {' '.join(args[1:]) or '(пусто)'} → код 2", r.returncode == 2, r.stdout + r.stderr)


def test_ci_pending_and_presence():
    b = Box()
    b.view(SHA, checks=ci("SUCCESS", "PENDING"))
    r = b.request()
    check("заявка при идущем CI ставится", r.returncode == 0 and b.req() is not None, r.stderr)
    b.run()
    check("CI идёт → окна нет, заявка ждёт", not b.windows() and b.req() is not None, b.outs[-1])
    b.view(SHA, checks=[])
    b.run()
    check("проверок ещё нет → ждёт", not b.windows() and b.req() is not None, b.outs[-1])
    b.view(SHA, checks=ci("SUCCESS"))
    b.run()
    check("обязательной check-traces/traces нет (metis-0633) → окна нет, ждёт", not b.windows() and b.req() is not None,
          b.outs[-1])
    b.view(SHA)
    b.run(extra={"PANTHEON_FAKE_IDLE": "900"})
    check("владельца нет у Mac (простой 15 мин) → окна нет, ждёт", not b.windows() and b.req() is not None, b.outs[-1])
    b.run()
    check("CI зелёный и владелец у Mac → окно и слияние", len(b.windows()) == 1 and len(b.merges()) == 1, b.outs[-1])


def test_ci_required_names():
    """metis-0633: проход по Touch ID судит CI тем же ci_verdict, что шлюз: необязательная красная не мешает, дубль
    обязательной с красной записью — отказ, PR не в main не ждёт tests/affected; обязательную закрывает только запуск
    от pull_request с SUCCESS (SKIPPED — отказ, только push — ждёт), сбой запросов запусков — ждёт."""
    b = Box()
    b.request()
    b.view(SHA, checks=ci("SUCCESS", "SKIPPED"))
    b.run()
    check("обязательная traces SKIPPED → окна нет, заявка снята с тревогой",
          not b.windows() and not b.merges() and b.req() is None and "traces не прошла: SKIPPED" in b.alerts(),
          b.alerts())
    b = Box()
    b.request()
    b.view(SHA, checks=ci("SUCCESS") + [dict(ci("SUCCESS", "SUCCESS")[1], event="push")])
    b.run()
    check("traces только от push → окна нет, ждёт", not b.windows() and b.req() is not None, b.outs[-1])
    b = Box()
    b.request()
    b.view(SHA)
    b.set("gh-runs-fail", "")
    b.run()
    check("запуски Actions не получены → окна нет, заявка ждёт (не снята)", not b.windows() and b.req() is not None,
          b.outs[-1])
    os.remove(os.path.join(b.rec, "gh-runs-fail"))
    b.run()
    check("запуски снова отвечают → окно и слияние", len(b.windows()) == 1 and len(b.merges()) == 1, b.outs[-1])
    calls = [json.loads(x)["argv"] for x in open(os.path.join(b.rec, "gh-argv.jsonl"))]
    runs_calls = [a for a in calls if a[0] == "api" and ("/actions/runs?" in a[1] or "/check-runs?" in a[1])]
    check("запуски спрошены по SHA заявки", [f"repos/{REPO}/actions/runs?head_sha={SHA}&per_page=100"] in
          [a[1:] for a in runs_calls] and [f"repos/{REPO}/commits/{SHA}/check-runs?per_page=100"] in
          [a[1:] for a in runs_calls], runs_calls)
    b = Box()
    b.request()
    b.view(SHA, checks=ci("SUCCESS", "SUCCESS") + [dict(ci("SUCCESS", "SUCCESS", "FAILURE")[2], workflowName="tests",
                                                         name="full")])
    b.run()
    check("красная необязательная (tests/full) при зелёных обязательных → окно и слияние",
          len(b.windows()) == 1 and len(b.merges()) == 1, b.outs[-1])
    b = Box()
    b.request()
    b.view(SHA, checks=ci("SUCCESS", "SUCCESS", "FAILURE"))
    b.run()
    check("красная вне обязательных и необязательных (other/job2) → окна нет, заявка снята (Д1 argus #235)",
          not b.windows() and not b.merges() and "other/job2 красная" in b.alerts(), b.alerts())
    b = Box()
    b.request()
    b.view(SHA, checks=ci("SUCCESS", "SUCCESS") + [dict(ci("SUCCESS", "FAILURE")[1])])
    b.run()
    check("дубль check-traces/traces (зелёная и красная) → окна нет, заявка снята",
          not b.windows() and not b.merges() and b.req() is None and "traces красная" in b.alerts(), b.alerts())
    b = Box()
    b.request()
    b.records = []
    b.gate_ok(SHA, base="feature-x")   # «принять» записано на base PR (metis-0965)
    b.view(SHA, checks=ci("SUCCESS", "SUCCESS")[1:], base="feature-x")
    b.run()
    check("PR не в main: только traces зелёная → окно и слияние", len(b.windows()) == 1 and len(b.merges()) == 1,
          b.outs[-1])
    b = Box()
    b.request()
    b.view(SHA, checks=ci("SUCCESS", "SUCCESS")[1:], base=None)
    b.run()
    check("baseRefName нет: affected обязателен, его нет → окна нет, ждёт", not b.windows() and b.req() is not None,
          b.outs[-1])
    b = Box()
    b.request()
    b.view(SHA, checks=[dict(c, prs=[8]) for c in ci("SUCCESS", "SUCCESS")])
    b.run()
    check("зелёные запуски чужого PR #8 на том же SHA → окна нет, ждёт", not b.windows() and b.req() is not None,
          b.outs[-1])
    b = Box()
    b.request()
    b.view(SHA)
    b.set("gh-runs-total", 101)
    b.run()
    check("запусков больше, чем получено (total_count 101) → окна нет, заявка снята с тревогой «неполные данные»",
          not b.windows() and not b.merges() and b.req() is None and "неполные данные CI" in b.alerts(), b.alerts())


if __name__ == "__main__":
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(HERE)), "guard", "tests"))
    from _par import run_cases  # случаи параллельно, каждый в своём fork (metis-0544); исключение — провал случая
    run_cases([(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)], FAILS,
              lambda name, err: FAILS.append(name))
    print(f"\n{'ПРОВАЛ: ' + ', '.join(FAILS) if FAILS else 'все прошли'}")
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
