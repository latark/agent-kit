#!/usr/bin/env python3
"""Карточка задачи в Obsidian (metis-0506, metis-0501 [zeus-pr-link], metis-0572): «Откуда» и «Из чего», «Критерии
N из M», «Что вышло», ссылки на PR и коммиты на GitHub (у пачки — PR её задач), свойство «Хвост» и виды «Новое за
неделю» и «Хвосты» в Доска.base. Сквозная проверка: check --quiet пишет хвосты, проход board ставит их на карточку.

Запуск: python3 -I plugins/pantheon/tests/test_board_links.py  (код выхода 0 — все прошли)
Всё во временных папках: HOME, PANTHEON_HOME, PANTHEON_STATE, PANTHEON_VIEW подменены.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(os.path.dirname(HERE), "lib")
sys.path.insert(0, LIB)
sys.path.insert(0, HERE)
import autoclose as A  # noqa: E402
import tasks as T  # noqa: E402
from _py311 import PY311  # noqa: E402

CLI = os.path.join(LIB, "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(CLI), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
T0 = datetime(2026, 10, 28, 12, 0).timestamp()
R = "latark/agent-kit"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def H(i, **kw):
    h = {"type": "task", "id": i, "title": f"Задача {i}", "status": "doing", "project": "Пантеон",
         "direction": "metis-pantheon", "created": "2026-10-27", "updated": "2026-10-28T10:00", "owner": "a"}
    h.update(kw)
    return h


def journal(*lines):
    return "\n## Журнал\n\n" + "".join(f"- 2026-10-27 1{n}:00 — агент: {x}\n" for n, x in enumerate(lines))


def unit():
    # «Критерии N из M»
    check("Критерии: 2 из 3; только заглушка — «не заданы»; раздела нет — None",
          T.criteria_count("Готово, когда:\n- [x] а\n- [ ] б\n- [X] в\n") == "2 из 3"
          and T.criteria_count(f"## Готово, когда\n\n- [ ] {T.DONE_WHEN_HINT}\n") == "не заданы"
          and T.criteria_count("текст") is None,
          T.criteria_count("Готово, когда:\n- [x] а\n- [ ] б\n- [X] в\n"))
    dbl = T.DONE_WHEN_HINT.replace(" ", "  ", 1)
    check("metis-0711: заглушка с двойным пробелом — «не заданы», _is_stub один для всех",
          T.criteria_count(f"## Готово, когда\n\n- [ ] {dbl}\n") == "не заданы" and T._is_stub(f" {dbl} ")
          and not T._is_stub("другое") and T.done_criteria(f"## Готово, когда\n\n- [ ] {dbl}\n") == [],
          T.criteria_count(f"## Готово, когда\n\n- [ ] {dbl}\n"))
    # «Откуда», «Из чего», «Что вышло»
    tasks = {"metis-0001": ("", H("metis-0001"), ""),
             "metis-0002": ("", H("metis-0002", **{"from": "остаток", "source": "metis-0001"}), ""),
             "metis-0003": ("", H("metis-0003", **{"from": "ревью", "source": "metis-0001"}), ""),
             "metis-0004": ("", H("metis-0004", **{"from": "отчёт", "source": "inbox/отчёт.md"}), "")}
    names = {i: f"{i} Задача" for i in tasks}
    outs = T.outcomes(tasks)
    check("outcomes: что вышло из задачи — задачи с её source, по id", outs == {"metis-0001": ["metis-0002", "metis-0003"]}, outs)
    ctx = T.card_ctx("metis-0001", tasks["metis-0001"][1], tasks, names, {}, outs=outs)
    card, body = T.render_card(tasks["metis-0001"][1], "", "x.md", T0, names=names, ctx=ctx)
    check("карточка: «Что вышло» — ссылки на карточки", "**Что вышло:** [[metis-0002 Задача|metis-0002]], [[metis-0003 Задача|metis-0003]]"
          in body, body)
    card, body = T.render_card(tasks["metis-0002"][1], "", "x.md", T0, names=names, ctx={})
    check("карточка остатка: «Откуда» — остаток, «Из чего» — ссылка, строка «Из чего возникла»",
          card["Откуда"] == "остаток" and card["Из чего"] == "[[metis-0001 Задача|metis-0001]]"
          and "**Из чего возникла:** [[metis-0001 Задача|metis-0001]] (остаток)" in body, (card, body))
    card, _ = T.render_card(tasks["metis-0004"][1], "", "x.md", T0, names=names, ctx={})
    check("source — не id (файл): «Из чего» текстом", card["Из чего"] == "inbox/отчёт.md", card["Из чего"])
    check("новые свойства — в порядке карточки и с типами Obsidian",
          all(k in T.CARD_ORDER for k in ("Откуда", "Из чего", "Критерии", "Хвост"))
          and T.PROP_TYPES.get("Хвост") == "multitext" and T.PROP_TYPES.get("Критерии") == "text"
          and T.PROP_TYPES.get("Из чего") == "text")

    # ссылки на PR и коммиты
    repos = {"metis-pantheon": [R], "athena": ["latark/a", "latark/b"]}
    cache = {"merged": {R: [{"number": 163, "headRefName": "simplify-1", "body": "Closes metis-0010, 0011",
                             "mergedAt": "2026-10-27T18:00:00Z", "oid": "1a1f77a0000000000000000000000000000000ff"}]},
             "open_prs": {R: [{"number": 190, "closes": ["metis-0012"], "part": False}]}}
    idx = A.pr_index(cache)
    check("pr_index: слитый — по Closes-списку с коммитом, открытый — по closes",
          [x["number"] for x in idx.get("metis-0011", [])] == [163] and idx["metis-0010"][0]["sha"].startswith("1a1f77a")
          and idx["metis-0012"] == [{"repo": R, "number": 190, "sha": "", "merged": False}], idx)
    check("pr_index: кэш неверной формы — пусто без трассировки",
          A.pr_index({"merged": {R: [{"number": "x"}, 5, {"number": 1, "body": 5}]}, "open_prs": {R: [{"number": 2, "closes": 5}]}}) == {}
          and A.pr_index(None) == {} and A.pr_index({"merged": []}) == {})
    wl = lambda h, b="": T.work_links(h, b, idx, repos)  # noqa: E731
    check("work_links: из кэша — PR слит и коммит", wl(H("metis-0010")) == ([(R, 163, True)], [(R, "1a1f77a")]), wl(H("metis-0010")))
    check("work_links: открытый PR — «открыт»", wl(H("metis-0012")) == ([(R, 190, False)], []), wl(H("metis-0012")))
    check("work_links: поле release «PR #N → sha» — PR и коммит", wl(H("metis-0020", release="PR #40 → abcdef0"))
          == ([(R, 40, None)], [(R, "abcdef0")]), wl(H("metis-0020", release="PR #40 → abcdef0")))
    j = journal("PR #163 слит владельцем (squash 1a1f77a)", "PR #170 обсуждали", "см. evil/x#5 и github.com/evil/x/pull/6")
    check("work_links: журнал — «PR #N слит (squash sha)» да; «PR #N» без события и чужой репозиторий — нет",
          wl(H("metis-0021"), j) == ([(R, 163, None)], [(R, "1a1f77a")]), wl(H("metis-0021"), j))
    j2 = journal("PR #7 (latark/B) слит", "PR #8 слит", "коммит github.com/latark/a/commit/abc1234def")
    check("work_links: два репозитория — только явный («PR #7 (latark/B)», регистр не важен) и ссылка на коммит",
          T.work_links(H("athena-0001", direction="athena"), j2, {}, repos) == ([("latark/b", 7, None)], [("latark/a", "abc1234")]),
          T.work_links(H("athena-0001", direction="athena"), j2, {}, repos))
    check("work_links: PR из кэша, но репозиторий не своего направления — не берём",
          T.work_links(H("metis-0010", direction="athena"), "", idx, repos) == ([], []))
    bad_oid = A.pr_index({"merged": {R: [{"number": 3, "headRefName": "metis-0040", "body": "", "oid": "zz; rm"}]}})
    check("pr_index: oid не hex — коммита нет", bad_oid == {"metis-0040": [{"repo": R, "number": 3, "sha": "", "merged": True}]}, bad_oid)
    check("work_links: направление без репозиториев — пусто", T.work_links(H("x-0001", direction="x"), j, idx, repos) == ([], []))
    check("work_links: коммит дважды (полный и короткий) — один раз",
          wl(H("metis-0010"), journal("PR #163 слит, squash 1a1f77a")) == ([(R, 163, True)], [(R, "1a1f77a")]),
          wl(H("metis-0010"), journal("PR #163 слит, squash 1a1f77a")))
    lines = T.links_lines(wl(H("metis-0010")))
    check("раздел «PR и коммиты»: markdown-ссылки на GitHub",
          lines == [f"- [PR #163](https://github.com/{R}/pull/163) · {R} · слит",
                    f"- [коммит 1a1f77a](https://github.com/{R}/commit/1a1f77a) · {R}"], lines)
    ctx = T.card_ctx("metis-0010", H("metis-0010"), {"metis-0010": ("", H("metis-0010"), "")}, {}, {},
                     links=wl(H("metis-0010")))
    _, body = T.render_card(H("metis-0010"), "", "x.md", T0, ctx=ctx)
    check("карточка задачи: раздел «## PR и коммиты» со ссылками", "## PR и коммиты\n\n- [PR #163](https://github.com/"
          f"{R}/pull/163)" in body and f"](https://github.com/{R}/commit/1a1f77a)" in body, body)

    # пачка: список PR её задач
    st = {"s-0001": ("", H("s-0001", type="story", status="doing"), ""),
          "metis-0010": ("", H("metis-0010", parent="s-0001"), ""), "metis-0030": ("", H("metis-0030", parent="s-0001"), "")}
    _, sb = T.render_story_card(st["s-0001"][1], "", "s.md", T0, st, names={"metis-0010": "metis-0010 З"},
                                child_links={"metis-0010": wl(H("metis-0010")), "metis-0030": ([], [])})
    check("карточка пачки: «## PR задач» — ссылки по каждой задаче, задачи без PR не названы",
          f"## PR задач\n\n- [[metis-0010 З|metis-0010]]: [PR #163](https://github.com/{R}/pull/163), "
          f"[1a1f77a](https://github.com/{R}/commit/1a1f77a)" in sb and "metis-0030:" not in sb, sb)
    _, sb = T.render_story_card(st["s-0001"][1], "", "s.md", T0, st)
    check("карточка пачки без ссылок — раздела нет", "## PR задач" not in sb)

    # хвост на карточке
    ctx = T.card_ctx("metis-0001", tasks["metis-0001"][1], tasks, names, {}, tails={"metis-0001": ["застой: doing, 3 сут"]})
    card, body = T.render_card(tasks["metis-0001"][1], "", "x.md", T0, names=names, ctx=ctx)
    check("свойство «Хвост» и предупреждение в теле", card["Хвост"] == ["застой: doing, 3 сут"]
          and "> [!warning] Хвост\n> - застой: doing, 3 сут" in body, (card.get("Хвост"), body))
    card, _ = T.render_card(tasks["metis-0001"][1], "", "x.md", T0, names=names, ctx={})
    check("без хвоста — свойство пустое", card["Хвост"] is None and card["Критерии"] is None)

    # виды Доска.base
    views = dict((re.search(r"^    name: (.+)$", p, re.M).group(1), p)
                 for p in re.split(r"^  - type: ", T.BASE_FILE.split("\nviews:\n", 1)[1], flags=re.M)[1:])
    nw, tl = views.get("Новое за неделю", ""), views.get("Хвосты", "")
    check("вид «Новое за неделю»: созданные за 7 дней, по «Откуда», колонки «Из чего» и «Критерии»",
          "'note[\"Создана\"] >= today() - \"7d\"'" in nw and "property: note.Откуда" in nw
          and "note.Из чего" in nw and "note.Критерии" in nw, nw)
    check("вид «Хвосты»: свойство «Хвост» или открытый остаток/ревью",
          "'!note[\"Хвост\"].isEmpty()'" in tl and "'note[\"Откуда\"] == \"остаток\"'" in tl
          and "'note[\"Откуда\"] == \"ревью\"'" in tl and "'note[\"Статус\"] != \"Готово\"'" in tl
          and "note.Хвост" in tl, tl)
    check("«Все задачи»: колонки «Откуда» и «Критерии»", "note.Откуда, note.Критерии]" in views.get("Все задачи", ""))
    check("у новых видов есть строка справки", all(str(T.VIEW_HELP.get(v) or "").strip() for v in ("Новое за неделю", "Хвосты")))


def run(env, *args, t=T0):
    return subprocess.run([PY311, "-I", RUN_PY, *args], env=dict(env, PANTHEON_NOW=str(t)), capture_output=True,
                          text=True, timeout=300)


def live():
    """check --quiet → STATE/tails.json и Хвосты.md («ответил, а waiting», застой); board → «Хвост» на карточке."""
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="board-links-"))
    try:
        home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
        os.makedirs(os.path.join(home, "directions", "metis-pantheon", "tasks"))
        os.makedirs(os.path.join(home, "inbox", "tasks"))
        os.makedirs(os.path.join(state, "owner-log"))
        os.makedirs(os.path.join(view, "Доска"))
        os.makedirs(os.path.join(tmp, ".claude", "pantheon"))
        open(os.path.join(tmp, ".claude", "pantheon", "policy.toml"), "w").write(f'[merge_repos]\n"metis-pantheon" = ["{R}"]\n')
        open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
        open(os.path.join(home, "directions.toml"), "w").write('[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n')
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
               "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
               "PANTHEON_FAKE_IDLE": "0", "TMPDIR": tmp}
        r = run(env, "task", "new", "--direction", "metis-pantheon", "--title", "Ждёт ответа", "--text", "т",
                "--status", "waiting", "--waiting-on", "human", "--question", "Какой?", "--why", "нужно",
                "--option", "А — да", "--option", "Б — нет", "--recommend", "А — проще", "--if-no-answer", "ждём",
                t=T0 - 3600)
        q = r.stdout.split()[0] if r.returncode == 0 else ""
        r2 = run(env, "task", "new", "--direction", "metis-pantheon", "--title", "Слито", "--text", "т",
                 "--done-when", "сделано", t=T0 - 3600)
        m = r2.stdout.split()[0] if r2.returncode == 0 else ""
        run(env, "task", "set", m, "status=doing", "mode=single", "--note", "PR #163 слит (squash 1a1f77a)", t=T0 - 3500)
        with open(os.path.join(state, "owner-log", "zeus.md"), "w", encoding="utf-8") as fh:  # ответ в окне вопросов Зевса
            fh.write(f"## {datetime.fromtimestamp(T0 - 60).strftime('%Y-%m-%d %H:%M:%S')} · окно вопросов\n"
                     f"вопрос: [{q}] Какой?\nответ: А — да\n")
        r = run(env, "check", "--quiet", t=T0)
        tails = json.load(open(os.path.join(state, "tails.json"), encoding="utf-8")) if os.path.exists(
            os.path.join(state, "tails.json")) else {}
        bp = os.path.join(view, "Доска", "Хвосты.md")
        hv = open(bp, encoding="utf-8").read() if os.path.exists(bp) else ""
        check("check --quiet: «ответил, а waiting» — в Хвосты.md и STATE/tails.json, без печати",
              q and any("владелец ответил" in x for x in tails.get(q, [])) and f"{q}: владелец ответил" in hv
              and "доска" not in r.stdout, (q, tails, hv, r.stdout[-300:], r.stderr[-300:]))
        r = run(env, "board", t=T0 + 10)
        cards = {f: open(os.path.join(view, "Доска", f), encoding="utf-8").read()
                 for f in os.listdir(os.path.join(view, "Доска")) if f.endswith(".md")}
        qc = next((v for v in cards.values() if f"id: {q}" in v), "")
        mc = next((v for v in cards.values() if f"id: {m}" in v), "")
        check("board: на карточке «Хвост» с «владелец ответил»", "Хвост:" in qc and "владелец ответил" in qc,
              qc[:900] + r.stderr[-500:])
        check("board: на карточке «Критерии» и ссылка на PR и коммит из журнала (репозиторий из [merge_repos])",
              "Критерии: 0 из 1" in mc and f"[PR #163](https://github.com/{R}/pull/163)" in mc
              and f"[коммит 1a1f77a](https://github.com/{R}/commit/1a1f77a)" in mc, mc[:1500] + r.stderr[-500:])
        base = open(os.path.join(view, "Доска", "Доска.base"), encoding="utf-8").read() \
            if os.path.exists(os.path.join(view, "Доска", "Доска.base")) else ""
        check("board: Доска.base с видами «Новое за неделю» и «Хвосты»",
              "name: Новое за неделю" in base and "name: Хвосты" in base, base[-300:])
        r = run(env, "task", "set", q, "status=todo", "waiting_on=", "--note", "ответ взят", t=T0 + 20)
        run(env, "check", "--quiet", t=T0 + 30)
        tails = json.load(open(os.path.join(state, "tails.json"), encoding="utf-8"))
        check("расхождение ушло — хвост из STATE/tails.json уходит", q not in tails, tails)
    finally:
        shutil.rmtree(tmp, True)


def main():
    unit()
    live()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
