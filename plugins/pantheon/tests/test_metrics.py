#!/usr/bin/env python3
"""metrics.py (metis-0294): строка учёта при закрытии задачи, свод неделя / с начала, задним числом с пометкой «оценка».

Всё — во временной папке: поддельные транскрипты в HOME/.claude/projects, задачи, журнал шлюза и журнал владельца.
Модуль — напрямую (идёт и на системном 3.9); CLI `pantheon task set … status=done`, `pantheon metrics backfill` и
`pantheon board` — на 3.11+ (_py311), иначе эта часть честно пропускается.

Запуск: python3 -I plugins/pantheon/tests/test_metrics.py  (код выхода 0 — все прошли)
"""
import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from _py311 import PY311  # noqa: E402

CLI = os.path.join(PLUGIN, "lib", "pantheon.py")
spec = importlib.util.spec_from_file_location("metrics_under_test", os.path.join(PLUGIN, "lib", "metrics.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

results = []


def check(name, ok, got=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or got is None else f" — получено {got!r}"))


T0 = datetime(2026, 10, 19, 15, 0).timestamp()  # понедельник: неделя 2026-W43 начинается в этот день
KIT, OTHER = "latark/agent-kit", "latark/other-app"
REPOS = {"metis-pantheon": [KIT], "hermes-demo": [OTHER]}  # [merge_repos] policy.toml: «PR #N» в журнале metis — PR agent-kit
SECRET = "текст-поручения-не-сохранять"
SEQ = [0]


def req(model, out_tokens, effort=None, branch=None, cwd=None, rid=None):
    """Запись assistant. Вывод: opus-5-5 — 20 $ за 1M (100000 = 2 $), sonnet-5-5 — 10 $ за 1M (100000 = 1 $)."""
    SEQ[0] += 1
    d = {"type": "assistant", "requestId": rid or f"r{SEQ[0]}", "cwd": cwd or "/w/main", "gitBranch": branch or "main",
         "message": {"id": f"m{SEQ[0]}", "model": f"claude-{model}", "usage": {"input_tokens": 0,
                                                                              "output_tokens": out_tokens}}}
    if effort:
        d["effort"] = effort
    return d


def prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def write_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def sub(proj, sid, name, agent_type, records):
    p = os.path.join(proj, sid, "subagents", f"agent-{name}.jsonl")
    write_jsonl(p, records)
    if agent_type:
        with open(p[:-len(".jsonl")] + ".meta.json", "w") as fh:
            json.dump({"agentType": agent_type}, fh)


def task_text(head, body):
    lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, str) and ' ' in v else v}"
                       for k, v in head.items()] + ["---", "", body]
    return "\n".join(lines) + "\n"


def setup():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="metrics-test-"))
    atexit.register(shutil.rmtree, tmp, True)
    pantheon, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    proj = os.path.join(tmp, ".claude", "projects", "-w")
    # основная сессия metis: запись в ветке metis-0903-fix — 1 $ на 0903; запись, где id только в тексте, — не в счёт
    write_jsonl(os.path.join(proj, "s1.jsonl"), [
        {"type": "agent-setting", "agentSetting": "domain-coordinator"},
        prompt("обсуждаем metis-0903 и metis-0901"),
        req("sonnet-5-5", 100_000, "medium", branch="metis-0903-fix", cwd="/w/.claude/worktrees/x"),
        req("sonnet-5-5", 500_000, "medium"),
    ])
    # dev-opus по metis-0901: 2 запроса opus high по 2 $ + повтор того же requestId (не считается дважды) = 4 $
    sub(proj, "s1", "d1", "dev-opus", [prompt(f"Задача: metis-0901 — {SECRET}"),
                                       req("opus-5-5", 100_000, "high", rid="q1"), req("opus-5-5", 100_000, "high"),
                                       req("opus-5-5", 100_000, "high", rid="q1")])
    # argus по metis-0901: 1 $ — рецензент, в исполнители не идёт, считается в review_usd
    sub(proj, "s1", "a1", "argus", [prompt("Ревью PR #77 (metis-0901)"), req("sonnet-5-5", 100_000, "high")])
    # argus по metis-0907, исполнителя в транскриптах нет: argus в исполнители не идёт и тогда
    sub(proj, "s1", "a2", "argus", [prompt("Ревью metis-0907"), req("sonnet-5-5", 100_000, "high")])
    # dev-sonnet на две задачи сразу: 2 $ пополам — по 1 $ на metis-0902 и metis-0903
    sub(proj, "s1", "d2", "dev-sonnet", [prompt("Задачи metis-0902 и metis-0903, ещё zzz-0001 (не задача)"),
                                         req("sonnet-5-5", 200_000, "medium")])
    tasks_dir = os.path.join(pantheon, "directions", "metis-pantheon", "tasks")
    other_dir = os.path.join(pantheon, "directions", "athena-shop", "tasks")
    for d in (tasks_dir, other_dir, os.path.join(pantheon, "inbox", "tasks"), view):
        os.makedirs(d, exist_ok=True)
    with open(os.path.join(pantheon, "schedule.toml"), "w") as fh:
        fh.write('primary_host = "mac-a"\n')

    def head(tid, status, closed=None, updated="2026-10-19T12:00:00", direction="metis-pantheon", **kw):
        h = {"type": "task", "id": tid, "title": f"Задача {tid}", "status": status, "project": direction,
             "direction": direction, "owner": direction, "created": "2026-10-19", "updated": updated,
             "schema_version": 1}
        if closed:
            h["closed"] = closed
        h.update(kw)
        return h

    j = "## Журнал\n\n"
    specs = {
        "metis-0901": (head("metis-0901", "done", "2026-10-19"),
                       j + "- 2026-10-19 10:00 — dev-opus: взял dev-opus до 11:00\n"
                           "- 2026-10-19 11:00 — metis: PR #77 argus вернуть, ещё упомянут #99\n"),
        "metis-0902": (head("metis-0902", "done", "2026-10-19", updated="2026-10-19T14:00:00"),
                       j + "- 2026-10-19 09:00 — агент: создана\n- 2026-10-19 13:00 — metis: PR #78 слит\n"),
        "metis-0903": (head("metis-0903", "done", "2026-10-19"), j + "- 2026-10-19 08:00 — агент: создана\n"),
        "athena-0904": (head("athena-0904", "done", "2026-10-19", direction="athena-shop", executor="codex"),
                        j + "- 2026-10-19 08:00 — агент: создана\n"),
        "metis-0905": (head("metis-0905", "dropped", "2026-10-18", updated="2026-10-18T20:00:00"),
                       j + "- 2026-10-18 10:00 — агент: создана\n"),
        "metis-0906": (head("metis-0906", "doing"), j + "- 2026-10-19 10:00 — dev: взял dev-opus до 11:00\n"),
        "metis-0907": (head("metis-0907", "done", "2026-10-19"),
                       j + "- 2026-10-19 12:30 — metis: revert metis-0901 после слияния — сломал сборку\n"),
        "metis-0908": (head("metis-0908", "done", "2026-10-10", updated="2026-10-10T18:00:00"),
                       j + "- 2026-10-10 10:00 — агент: создана\n"),
    }
    tasks = {}
    for tid, (h, body) in specs.items():
        d = other_dir if h["direction"] == "athena-shop" else tasks_dir
        p = os.path.join(d, tid + ".md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(task_text(h, body))
        tasks[tid] = (p, h, body)
    # шлюз: PR 77 — «вернуть» дважды на один SHA (один круг), затем «принять» на новый; PR 78 — «принять» сразу;
    # PR 99 упомянут в журнале 0901 мимоходом — у него один вердикт, кругов 0901 он не сбивает
    # PR 77 другого репозитория — три «вернуть» и «принять»: кругов 0901 они не добавляют (номер тот же, repo чужой)
    gate = [{"kind": "reject", "repo": [KIT], "pr": 77, "sha": "a1", "time": "2026-10-19T10:30:00"},
            {"kind": "reject", "repo": [KIT], "pr": 77, "sha": "a1", "time": "2026-10-19T10:40:00"},
            {"kind": "tests", "repo": [KIT], "pr": 77, "sha": "b2", "time": "2026-10-19T10:50:00"},
            {"kind": "accept", "repo": [KIT], "pr": 77, "sha": "b2", "time": "2026-10-19T11:00:00"},
            {"kind": "accept", "repo": [KIT], "pr": 78, "sha": "c3", "time": "2026-10-19T13:00:00"},
            {"kind": "accept", "repo": [KIT], "pr": 99, "sha": "d4", "time": "2026-10-19T13:00:00"}]
    gate += [{"kind": "reject", "repo": [OTHER], "pr": 77, "sha": x, "time": "2026-10-18T10:00:00"} for x in "xyz"]
    gate += [{"kind": "accept", "repo": [OTHER], "pr": 77, "sha": "w", "time": "2026-10-18T11:00:00"}]
    write_jsonl(os.path.join(state, "merge-gate", "records.jsonl"), gate)
    write_jsonl(os.path.join(state, "owner-log", "board.jsonl"), [
        {"kind": "move", "id": "metis-0901", "src": "На проверке", "dst": "В работе", "time": "2026-10-19T11:10:00"},
        {"kind": "note", "id": "metis-0901", "text": "поправь", "time": "2026-10-19T11:11:00"},
        {"kind": "move", "id": "metis-0902", "src": "Очередь", "dst": "В работе", "time": "2026-10-19T11:12:00"}])
    with open(os.path.join(pantheon, "directions", "metis-pantheon", "review-77.md"), "w", encoding="utf-8") as fh:
        fh.write("# Ревью PR #77 (metis-0901)\n\n**Вердикт: вернуть.**\n")
    return tmp, pantheon, state, view, tasks


def unit():
    tmp, pantheon, state, view, tasks = setup()
    board = os.path.join(view, "Доска")
    ctx = M.Ctx(pantheon, state, tmp, T0, board, REPOS)
    os.makedirs(os.path.join(pantheon, "metrics"))
    with open(os.path.join(pantheon, "metrics", "since"), "w") as fh:
        fh.write("2026-10-19\n")
    rows_path = ctx.rows_path

    r1 = M.record(ctx, tasks, "metis-0901")
    check("закрытие: строка metis-0901 записана", r1 is not None and len(M.read_rows(rows_path)) == 1)
    r1 = r1 or {}
    check("исполнитель — роль субагента с наибольшим расходом, не рецензент: dev-opus",
          r1.get("executor") == "dev-opus", r1.get("executor"))
    check("модель и effort исполнителя: opus-5-5, high",
          (r1.get("model"), r1.get("effort")) == ("opus-5-5", "high"), (r1.get("model"), r1.get("effort")))
    check("расход: 4 $ dev-opus (повтор requestId не задвоен) + 1 $ argus = 5 $; argus — в review_usd",
          abs(r1.get("usd", 0) - 5.0) < 1e-6 and abs(r1.get("review_usd", 0) - 1.0) < 1e-6,
          (r1.get("usd"), r1.get("review_usd")))
    check("токены: вывод 300000, по ролям — dev-opus 200000",
          r1.get("tokens", {}).get("output") == 300_000 and r1.get("roles", {}).get("dev-opus", {}).get("tokens")
          == 200_000, (r1.get("tokens"), r1.get("roles")))
    check("запись основной сессии, где id только в тексте, не засчитана (связка — поручение)",
          r1.get("link") == ["поручение"], r1.get("link"))
    check("круги argus: вернуть (повтор на тот же SHA — один круг) → принять = 2, не с первого круга",
          (r1.get("argus_rounds"), r1.get("argus_first_pass"), r1.get("argus_rejects")) == (2, False, 1),
          (r1.get("argus_rounds"), r1.get("argus_first_pass"), r1.get("argus_rejects")))
    check("владелец: перенос назад «На проверке» → «В работе» — возврат; заметка — правка",
          (r1.get("owner_returns"), r1.get("owner_notes"), r1.get("owner_moves")) == (1, 1, 1))
    check("возвратов = «вернуть» argus + переносы владельцем назад = 2", r1.get("returns") == 2, r1.get("returns"))
    check("возврат после слияния: metis-0907 с revert metis-0901", r1.get("post_merge") == ["metis-0907"],
          r1.get("post_merge"))
    check("время: от аренды 10:00 до закрытия 12:00 = 2 ч, источник — claim",
          (r1.get("hours"), r1.get("start_source")) == (2.0, "claim"), (r1.get("hours"), r1.get("start_source")))
    check("закрытие после начала учёта — не оценка", r1.get("estimate") is False)
    raw = open(rows_path, encoding="utf-8").read()
    check("текст поручения и заметки владельца («поправь») в строку учёта не попал",
          SECRET not in raw and "обсуждаем" not in raw and "поправь" not in raw)

    check("повторное закрытие той же задачи строку не дублирует",
          M.record(ctx, tasks, "metis-0901") is None and len(M.read_rows(rows_path)) == 1)
    check("незакрытая задача строку не пишет", M.record(ctx, tasks, "metis-0906") is None)

    asked, orig = [], M.usage_for
    M.usage_for = lambda projects, tids, *a, **k: asked.append(sorted(tids)) or orig(projects, tids, *a, **k)
    try:
        rows = {r["id"]: r for r in M.sync(ctx, tasks)}
        again = M.sync(ctx, tasks)
    finally:
        M.usage_for = orig
    check("плановый проход не читает транскрипты задач, у которых строка уже есть (0901), второй — ничьих",
          asked and all("metis-0901" not in x for x in asked) and len(asked) <= 2, asked)
    check("плановый проход: дописаны закрытые за 3 дня без строки, без 0901 и без давней 0908",
          sorted(rows) == ["athena-0904", "metis-0902", "metis-0903", "metis-0905", "metis-0907"], sorted(rows))
    r2, r3 = rows.get("metis-0902", {}), rows.get("metis-0903", {})
    check("поручение на две задачи: 2 $ пополам — 0902 = 1 $, shared = 2",
          abs(r2.get("usd", 0) - 1.0) < 1e-6 and r2.get("shared") == 2, (r2.get("usd"), r2.get("shared")))
    check("0903: половина поручения 1 $ + ветка metis-0903-fix 1 $ = 2 $, связки обе",
          abs(r3.get("usd", 0) - 2.0) < 1e-6 and r3.get("link") == ["ветка/папка", "поручение"],
          (r3.get("usd"), r3.get("link")))
    check("0903: исполнитель — dev-sonnet (1 $) не перебит основной сессией (1 $ — тоже не рецензент) по имени",
          r3.get("executor") in ("dev-sonnet", "domain-coordinator") and r3.get("model") == "sonnet-5-5")
    check("0902: PR 78 принят сразу — с первого круга", (r2.get("argus_rounds"), r2.get("argus_first_pass")) == (1, True))
    check("0902: перенос владельцем вперёд (Очередь → В работе) — не возврат", r2.get("owner_returns") == 0)
    r4 = rows.get("athena-0904", {})
    check("без транскриптов и с executor=codex — исполнитель codex, модель codex, расход 0",
          (r4.get("executor"), r4.get("model"), r4.get("usd"), r4.get("link")) == ("codex", "codex", 0.0, ["нет"]),
          (r4.get("executor"), r4.get("model"), r4.get("usd"), r4.get("link")))
    r7 = rows.get("metis-0907", {})
    check("только argus в транскриптах — исполнитель не argus, а владелец задачи; 1 $ — в review_usd",
          (r7.get("executor"), r7.get("model"), r7.get("review_usd")) == ("metis-pantheon", "—", 1.0),
          (r7.get("executor"), r7.get("model"), r7.get("review_usd")))
    check("закрыта до начала учёта (18.10 < since 19.10) — плановый проход ставит «оценка»",
          rows.get("metis-0905", {}).get("estimate") is True and r2.get("estimate") is False)
    check("второй плановый проход ничего не дописывает", again == [])

    dry = M.backfill(ctx, tasks, "2026-10-01", "2026-10-19", dry=True)
    n_before = len(M.read_rows(rows_path))
    check("задним числом --dry-run: одна строка (0908), файл не тронут",
          [r["id"] for r in dry] == ["metis-0908"] and n_before == 6, ([r["id"] for r in dry], n_before))
    bf = M.backfill(ctx, tasks, "2026-10-01", "2026-10-19")
    check("задним числом: строка 0908 с пометкой «оценка», существующие строки не тронуты",
          [(r["id"], r["estimate"]) for r in bf] == [("metis-0908", True)]
          and len(M.read_rows(rows_path)) == 7)
    check("задним числом повторно — ничего", M.backfill(ctx, tasks, "2026-10-01", "2026-10-19") == [])

    s = M.summary(M.read_rows(rows_path), T0, M.post_merge_index(tasks))
    check("свод: неделя 2026-W43", s["week_name"] == "2026-W43", s["week_name"])
    wk, al = s["week"], s["all"]
    g = wk["by_executor"].get(("dev-opus", "opus-5-5", "high"), {})
    check("неделя × исполнитель×модель×effort: dev-opus/opus-5-5/high — 1 задача, 0 из 1 с первого круга, 5 $",
          (g.get("tasks"), g.get("first_pass"), g.get("first_known"), g.get("usd_per_task")) == (1, 0, 1, 5.0), g)
    check("неделя: отменённая 18.10 и давняя 0908 — не в неделе; с начала — все 7",
          wk["total"]["tasks"] + wk["total"]["dropped"] == 5 and al["total"]["tasks"] + al["total"]["dropped"] == 7,
          (wk["total"], al["total"]))
    check("с начала: отменено 1, оценок 2 (0905, 0908)", (al["total"]["dropped"], al["total"]["estimate"]) == (1, 2),
          al["total"])
    check("по направлениям: athena-shop — 1 задача, metis-pantheon — 4 за неделю",
          wk["by_direction"].get("athena-shop", {}).get("tasks") == 1
          and wk["by_direction"].get("metis-pantheon", {}).get("tasks") == 4,
          {k: v["tasks"] for k, v in wk["by_direction"].items()})
    check("после слияния: в своде metis-pantheon — 1 задача с возвратом", wk["by_direction"]["metis-pantheon"]
          ["post_merge"] == 1)
    md = M.week_md(s, T0)
    check("week md: разделы недели и с начала, строка dev-opus",
          "## Неделя 2026-W43" in md and "## С начала учёта" in md and "| dev-opus | opus-5-5 | high | 1 |" in md)

    udir = os.path.join(board, M.DIR_NAME)
    os.makedirs(udir)
    with open(os.path.join(udir, "моя заметка.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nТип: заметка\n---\nчужое\n")
    with open(os.path.join(udir, "старое-учёт.md"), "w", encoding="utf-8") as fh:
        fh.write('---\nТип: "учёт"\nПериод: "неделя"\n---\n')
    M.publish(ctx, tasks)
    week_file = os.path.join(pantheon, "metrics", "week-2026-W43.md")
    check("publish: metrics/week-2026-W43.md записан", os.path.isfile(week_file))
    notes = sorted(os.listdir(udir))
    check("publish: своя устаревшая заметка убрана, чужая на месте",
          "моя заметка.md" in notes and "старое-учёт.md" not in notes, notes)
    wn = [n for n in notes if n.startswith("неделя-исполнитель-dev-opus")]
    text = open(os.path.join(udir, wn[0]), encoding="utf-8").read() if wn else ""
    check("заметка Пульта: Тип учёт, Период неделя, Срез исполнитель, Модель, Долларов на задачу",
          'Тип: "учёт"' in text and 'Период: "неделя"' in text and 'Срез: "исполнитель"' in text
          and 'Модель: "opus-5-5"' in text and "Долларов на задачу: 5.0" in text, text)
    check("заметки на неделю и с начала, по исполнителю и направлению",
          any(n.startswith("всё-направление-athena-shop") for n in notes)
          and any(n.startswith("неделя-направление-metis-pantheon") for n in notes), notes)
    mt = os.path.getmtime(week_file)
    time.sleep(0.05)
    M.publish(ctx, tasks)
    check("повторный publish без изменений файл не переписывает", os.path.getmtime(week_file) == mt)


def argus_repo():
    """Вердикты шлюза — по repo и номеру PR: одинаковые номера разных репозиториев не смешиваются (ревью #83, п. 1)."""
    gate = [{"kind": "accept", "repo": [KIT], "pr": 83, "sha": "a", "time": "2026-10-19T11:00:00"}]
    gate += [{"kind": "reject", "repo": [OTHER], "pr": 83, "sha": x, "time": "2026-10-18T10:00:00"} for x in "bcd"]
    want = {"rounds": 1, "first_pass": True, "rejects": 0}
    full = "- 2026-10-19 11:00 — metis: PR latark/agent-kit#83 argus принять\n"
    got = M.argus_info("metis-0294", full, gate, [], None)
    check("owner/repo#N: круги только своего repo, три «вернуть» чужого #83 не в счёт", got == want, got)
    url = "- 2026-10-19 11:00 — metis: https://github.com/Latark/Agent-Kit/pull/83 слит\n"
    got = M.argus_info("metis-0294", url, gate, [], None)
    check("ссылка github.com/…/pull/N: repo из ссылки (без учёта регистра)", got == want, got)
    bare = "- 2026-10-19 11:00 — metis: PR #83 argus принять\n"
    got = M.argus_info("metis-0294", bare, gate, [], [KIT])
    check("«PR #N» без repo — repo направления из [merge_repos]", got == want, got)
    got = M.argus_info("metis-0294", bare, gate, [], [OTHER])
    check("«PR #N» у направления с другим repo — круги того repo",
          got == {"rounds": 3, "first_pass": False, "rejects": 3}, got)
    got = M.argus_info("metis-0294", bare, gate, [], None)
    check("«PR #N», repo направления не определить — не считается",
          got == {"rounds": 0, "first_pass": None, "rejects": 0}, got)


def argus_multi():
    """Направление с двумя repo (ревью #83, замечание 1): «PR #N» — только если вердикты на N у одного repo."""
    two = [KIT, OTHER]
    bare = "- 2026-10-19 11:00 — metis: PR #5 argus принять\n"
    gate = [{"kind": "accept", "repo": [KIT], "pr": 5, "sha": "a", "time": "2026-10-19T11:00:00"}]
    gate += [{"kind": "reject", "repo": [OTHER], "pr": 6, "sha": "q", "time": "2026-10-18T10:00:00"}]
    got = M.argus_info("metis-0294", bare, gate, [], two)
    check("два repo, вердикты на #5 только у одного — круги этого repo",
          got == {"rounds": 1, "first_pass": True, "rejects": 0}, got)
    gate += [{"kind": "reject", "repo": [OTHER], "pr": 5, "sha": x, "time": "2026-10-18T10:00:00"} for x in "bcd"]
    got = M.argus_info("metis-0294", bare, gate, [], two)
    check("два repo, вердикты на #5 у обоих — не считается",
          got == {"rounds": 0, "first_pass": None, "rejects": 0}, got)
    full = "- 2026-10-19 11:00 — metis: PR latark/agent-kit#5 argus принять\n"
    got = M.argus_info("metis-0294", full, gate, [], two)
    check("два repo, repo назван явно — круги названного",
          got == {"rounds": 1, "first_pass": True, "rejects": 0}, got)


def race():
    """Закрытие и плановый проход одной задачи разом (ревью #83, п. 2): пока закрытие читает транскрипты, проход
    успевает записать строку — закрытие её не дублирует. Без потоков: проход запускается изнутри чтения транскриптов."""
    tmp, pantheon, state, view, tasks = setup()
    ctx = M.Ctx(pantheon, state, tmp, T0, None, REPOS)
    os.makedirs(os.path.join(pantheon, "metrics"))
    with open(os.path.join(pantheon, "metrics", "since"), "w") as fh:
        fh.write("2026-10-19\n")
    orig, busy, synced = M.usage_for, [False], []

    def slow(projects, tids, *a, **k):
        if not busy[0]:
            busy[0] = True
            synced.extend(r["id"] for r in M.sync(ctx, tasks))  # плановый проход посреди чтения при закрытии
        return orig(projects, tids, *a, **k)

    M.usage_for = slow
    try:
        got = M.record(ctx, tasks, "metis-0901")
    finally:
        M.usage_for = orig
    ids = [r["id"] for r in M.read_rows(ctx.rows_path)]
    check("гонка: проход записал 0901 раньше закрытия — в файле одна строка 0901, закрытие вернуло None",
          "metis-0901" in synced and ids.count("metis-0901") == 1 and got is None, (synced, ids, got))
    added = M.append_rows(ctx.rows_path, [{"id": "metis-0901", "closed": "2026-10-19"},
                                          {"id": "metis-0901", "closed": "2026-10-20"}])
    check("append_rows: строка с тем же (id, closed) второй раз не пишется, новая — пишется",
          added == [{"id": "metis-0901", "closed": "2026-10-20"}] and len(M.read_rows(ctx.rows_path)) == len(ids) + 1,
          added)


def cli():
    if not PY311:
        print("skip CLI: нет Python 3.11+ для pantheon.py")
        return
    tmp, pantheon, state, view, tasks = setup()
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": pantheon, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0"}

    def run(*args, t=T0, **extra):
        return subprocess.run([PY311, "-I", CLI, *args], env=dict(env, PANTHEON_NOW=str(t), **extra),
                              capture_output=True, text=True, timeout=120)

    rows_path = os.path.join(pantheon, "metrics", "tasks.jsonl")
    policy = os.path.join(tmp, ".claude", "pantheon", "policy.toml")
    os.makedirs(os.path.dirname(policy), exist_ok=True)
    with open(policy, "w", encoding="utf-8") as fh:
        fh.write(f'[merge_repos]\nmetis-pantheon = ["{KIT}"]\nhermes-demo = ["{OTHER}"]\n')
    p = run("task", "set", "metis-0906", "status=done")
    rows = M.read_rows(rows_path)
    check("CLI task set status=done: строка учёта записана", p.returncode == 0 and [r["id"] for r in rows]
          == ["metis-0906"], (p.returncode, p.stderr[-300:], rows))
    r = rows[0] if rows else {}
    check("CLI: время от аренды 10:00 до закрытия 15:00 = 5 ч, не оценка",
          (r.get("hours"), r.get("estimate"), r.get("closed")) == (5.0, False, "2026-10-19"),
          (r.get("hours"), r.get("estimate"), r.get("closed")))
    p = run("task", "set", "metis-0906", "status=doing")
    p = run("task", "set", "metis-0906", "status=dropped", PANTHEON_METRICS="0")
    check("PANTHEON_METRICS=0: закрытие без строки учёта", p.returncode == 0 and len(M.read_rows(rows_path)) == 1,
          (p.returncode, p.stderr[-300:]))
    os.rename(rows_path, rows_path + ".bak")
    os.makedirs(rows_path)  # tasks.jsonl — папка: запись падает, как у роли без доступа в metrics/
    p = run("task", "set", "metis-0906", "status=doing")
    p = run("task", "set", "metis-0906", "status=done")
    check("учёт не записался — закрытие всё равно прошло, предупреждение в stderr",
          p.returncode == 0 and "допишет плановый проход" in p.stderr, (p.returncode, p.stderr[-300:]))
    os.rmdir(rows_path)
    os.rename(rows_path + ".bak", rows_path)

    p = run("metrics", "backfill", "--from", "2026-10-01", "--dry-run")
    check("CLI backfill --dry-run: строки с пометкой «оценка», файл не тронут",
          p.returncode == 0 and "оценка" in p.stdout and "проба, не записано" in p.stdout
          and len(M.read_rows(rows_path)) == 1, (p.returncode, p.stdout[-300:], p.stderr[-300:]))
    p = run("metrics", "backfill", "--from", "2026-10-15")
    rows = M.read_rows(rows_path)
    est = sorted(r["id"] for r in rows if r.get("estimate"))
    check("CLI backfill --from 2026-10-15: закрытые с 15.10 без строки — с пометкой «оценка», 0908 (10.10) — нет",
          p.returncode == 0 and est == ["athena-0904", "metis-0901", "metis-0902", "metis-0903", "metis-0905",
                                        "metis-0907"], (p.returncode, est, p.stderr[-300:]))
    r77 = next((r for r in rows if r["id"] == "metis-0901"), {})
    check("CLI: [merge_repos] из policy.toml — «PR #77» в журнале metis-0901 считается по repo направления",
          (r77.get("argus_rounds"), r77.get("argus_first_pass")) == (2, False),
          (r77.get("argus_rounds"), r77.get("argus_first_pass")))
    check("CLI backfill: свод недели записан", os.path.isfile(os.path.join(pantheon, "metrics", "week-2026-W43.md")))
    p = run("metrics", "backfill", "--from", "15.10")
    check("CLI backfill: дата не ГГГГ-ММ-ДД — код 2", p.returncode == 2)

    p = run("task", "set", "metis-0906", "status=doing")
    p = run("task", "set", "metis-0906", "status=done", t=T0 + 3600)
    os.remove(rows_path)
    p = run("board")
    for _ in range(100):  # учёт идёт фоновым процессом (metis-0320): board не ждёт его
        if M.read_rows(rows_path) and os.path.isdir(os.path.join(view, "Доска", M.DIR_NAME)):
            break
        time.sleep(0.2)
    time.sleep(1)
    rows = M.read_rows(rows_path)
    udir = os.path.join(view, "Доска", M.DIR_NAME)
    check("pantheon board: плановый проход дописал строки закрытий и заметки Пульта",
          p.returncode == 0 and len(rows) >= 7 and os.path.isdir(udir) and len(os.listdir(udir)) > 0,
          (p.returncode, len(rows), p.stderr[-300:]))
    p = run("metrics", "summary")
    check("CLI metrics summary: свод в окно", p.returncode == 0 and "По исполнителю × модели × effort" in p.stdout)
    with open(policy, "wb") as fh:
        fh.write(b'[merge_repos]\nx = ["\xff"]\n')
    p = run("metrics", "summary")
    check("policy.toml не в UTF-8: metrics без трассы, код 0",
          p.returncode == 0 and "Traceback" not in p.stderr, (p.returncode, p.stderr[-300:]))


unit()
argus_repo()
argus_multi()
race()
cli()
print(f"{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
