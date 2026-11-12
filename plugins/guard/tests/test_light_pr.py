#!/usr/bin/env python3
"""Лёгкий PR ядра (metis-1065, решение владельца 12.11, Р2) в шлюзе guard (merge_gate.py).

Запуск: python3 -I plugins/guard/tests/test_light_pr.py   (код 0 — все прошли)
Проверяет: light_pr — лёгкий ли PR по записям REST pulls/N/files (status, deletions, filename, previous_filename):
одни добавленные строки тестов и README*.md, drafts/*.md — да; удалённая строка в тесте, run-tests.py, AGENTS.md,
CLAUDE.md, SKILL.md, roles/*.tmpl, папки инструкций, код, переименование, удаление, пустой и неполный список — нет.
light_accept — «принять» в счёт, только если модели транскрипта все claude-opus, а effort все high. Хук записи
вердикта (record) пишет поле efforts — значения message.output_config.effort записей api-request-blob транскрипта
argus. Push в принятый лёгкий PR ядра — test_push_accepted.py (t_light_core), шлюз владельца — test_merge_light.py.
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_merge_gate as tm  # noqa: E402  (Home, rec, _load_merge_gate)
from _py311 import mkroot  # noqa: E402  (metis-0729)

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))


def f(name, status="modified", plus=3, minus=0, prev=None):
    r = {"filename": name, "status": status, "additions": plus, "deletions": minus}
    if prev is not None:
        r["previous_filename"] = prev
    return r


T = "plugins/guard/tests/test_merge_gate.py"
LIGHT = [
    ("добавленный тест", [f("plugins/guard/tests/test_new.py", "added")]),
    ("тест правлен без удалённых строк", [f(T, plus=10)]),
    ("фикстура теста", [f("plugins/pantheon/tests/fixtures/morph-hooks/x.json", "added")]),
    ("README.md в корне с удалёнными строками", [f("README.md", minus=4)]),
    ("readme.MD любой регистр", [f("plugins/guard/readme.MD")]),
    ("README.en.md", [f("plugins/pantheon/docs/charon/README.en.md", "added")]),
    ("drafts/*.md", [f("drafts/1065-plan.md", "added"), f("drafts/0771-threat-model.md", minus=2)]),
    ("тест и README вместе", [f(T), f("README.md")]),
]
HEAVY = [
    ("удалённая строка в тесте", [f(T, minus=1)], "удалены строки"),
    ("run-tests.py (QUARANTINE, SKIP_NOT_MAC)", [f("plugins/pantheon/scripts/run-tests.py", plus=1)], "раннера"),
    ("AGENTS.md", [f("AGENTS.md")], "инструкция"),
    ("CLAUDE.md во вложенной папке", [f("plugins/pantheon/CLAUDE.md")], "инструкция"),
    ("SKILL.md", [f("plugins/pantheon/skills/new-direction/SKILL.md")], "инструкция"),
    ("roles/*.tmpl", [f("plugins/pantheon/roles/argus.tmpl")], "инструкция"),
    ("roles/_ref/*.md", [f("plugins/pantheon/roles/_ref/merge-rounds.md")], "инструкция"),
    ("README в roles/", [f("plugins/pantheon/roles/README.md")], "инструкция"),
    ("README в hooks/", [f("plugins/guard/hooks/README.md")], "инструкция"),
    ("README в .github/", [f(".github/README.md")], "инструкция"),
    ("README в .claude/", [f(".claude/README.md")], "инструкция"),
    ("агенты", [f("plugins/pantheon/agents/argus.md")], "инструкция"),
    ("команды", [f("plugins/pantheon/commands/x.md")], "инструкция"),
    ("шаблон в template/", [f("plugins/pantheon/template/pantheon/board.md")], "инструкция"),
    ("промпт lib/read_prompts", [f("plugins/pantheon/lib/read_prompts/default.md")], "инструкция"),
    ("тест в tests/hooks/", [f("plugins/guard/tests/hooks/x.py", "added")], "инструкция"),
    ("*.tmpl в tests/", [f("plugins/pantheon/tests/x.tmpl", "added")], "инструкция"),
    ("код и тест", [f("plugins/pantheon/lib/merge.py"), f(T)], "не тест и не документ"),
    ("другой .md вне drafts/", [f("plugins/pantheon/docs/plan.md", "added")], "не тест и не документ"),
    ("drafts/ вложенная папка", [f("drafts/x/plan.md", "added")], "не тест и не документ"),
    ("tests/ не в плагине", [f("tests/test_x.py", "added")], "не тест и не документ"),
    ("переименование теста", [f("plugins/guard/tests/test_b.py", "renamed", 0, 0, prev="plugins/guard/tests/test_a.py")],
     "renamed"),
    ("previous_filename при modified", [f(T, prev="plugins/guard/tests/test_old.py")], "modified"),
    ("удалённый тест", [f(T, "removed", 0, 9)], "removed"),
    ("копирование", [f("plugins/guard/tests/test_c.py", "copied")], "copied"),
    ("status changed", [f(T, "changed")], "changed"),
    ("deletions не число", [f(T, minus="0")], "удалены строки"),
    ("deletions — False", [f(T, minus=False)], "удалены строки"),
    ("deletions нет", [{"filename": T, "status": "modified"}], "удалены строки"),
    ("имени нет", [{"status": "added", "deletions": 0}], "нет имени"),
    ("путь с ..", [f("plugins/guard/tests/../hooks/merge_gate.py")], "инструкция"),
]


def t_light_pr():
    mg = tm._load_merge_gate("merge_gate_light")
    for name, files in LIGHT:
        ok, what = mg.light_pr(files, len(files))
        check(f"лёгкий: {name}", ok is True and "тестов" in what, (ok, what))
    for name, files, why in HEAVY:
        ok, what = mg.light_pr(files, len(files))
        check(f"не лёгкий: {name} — «{why}»", ok is False and why in what, (ok, what))
    one = [f(T)]
    for name, files, count in (("пустой список", [], 0), ("список не получен (None)", None, 1),
                               ("неполный: changedFiles больше", one, 2), ("changedFiles — True", one, True),
                               ("changedFiles нет", one, None), ("запись не словарь", ["README.md"], 1)):
        ok, what = mg.light_pr(files, count)
        check(f"не лёгкий: {name}", ok is False and "не получен" in what, (ok, what))


def t_light_accept():
    mg = tm._load_merge_gate("merge_gate_light2")
    for name, rec, want in (
            ("Opus high", {"models": ["claude-opus-5-5"], "efforts": ["high"]}, True),
            ("Opus с датой high", {"models": ["claude-opus-4-1-20250805"], "efforts": ["high"]}, True),
            ("Opus medium", {"models": ["claude-opus-5-5"], "efforts": ["medium"]}, False),
            ("Opus high и medium", {"models": ["claude-opus-5-5"], "efforts": ["high", "medium"]}, False),
            ("Opus без efforts (запись до metis-1065)", {"models": ["claude-opus-5-5"]}, False),
            ("Opus, efforts пустой", {"models": ["claude-opus-5-5"], "efforts": []}, False),
            ("efforts не список", {"models": ["claude-opus-5-5"], "efforts": "high"}, False),
            ("Opus и Sonnet high", {"models": ["claude-opus-5-5", "claude-sonnet-5"], "efforts": ["high"]}, False),
            ("без models high", {"efforts": ["high"]}, False),
            ("models пустой high", {"models": [], "efforts": ["high"]}, False)):
        check(f"light_accept: {name} — {want}", mg.light_accept(rec) is want, rec)


def blob(effort, content="x"):
    msg = {"role": "user", "content": [{"type": "text", "text": content}]}
    if effort is not None:
        msg["output_config"] = {"effort": effort}
    return json.dumps({"type": "api-request-blob", "agentId": "ag1", "message": msg})


def t_record_efforts(h):
    """record пишет efforts из транскрипта argus: значения message.output_config.effort записей api-request-blob."""
    sha = h.sha["agent-kit"]
    proj = h.j("cc-projects/-p")
    main_tp = os.path.join(proj, "s-coord.jsonl")
    path = os.path.join(proj, "s-coord", "subagents", "agent-ag1.jsonl")

    def accept(lines, kind="accept"):
        shutil.rmtree(proj, ignore_errors=True)
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            fh.write("".join(x + "\n" for x in lines))
        h.reset()
        h.seed(tm.rec("tests", "latark/agent-kit", None, sha, "dev-opus"))
        args = " --opened a --unchecked c --ran \"модель: claude-opus-5-5, тесты\"" if kind == "accept" else ""
        h.post(f"pantheon review {kind} latark/agent-kit 7 {sha}{args}", "argus", agent_id="ag1", transcript=main_tp)
        got = [r for r in h.read() if r["kind"] == kind]
        return got[0] if got else {}

    opus = json.dumps({"type": "assistant", "message": {"model": "claude-opus-5-5", "role": "assistant"}})
    r = accept([blob("high"), blob(None), opus, blob(None, '"output_config": {"effort": "low"}')])
    check("транскрипт: один запрос с effort high — efforts [high], models [opus]",
          r.get("efforts") == ["high"] and r.get("models") == ["claude-opus-5-5"], r)
    r = accept([blob("high"), blob("medium"), blob(" HIGH "), opus])
    check("транскрипт: high и medium — efforts отсортированы, без повторов и регистра",
          r.get("efforts") == ["high", "medium"], r)
    r = accept([opus, blob(None)])
    check("транскрипт без output_config — efforts [] (для лёгкого пути не в счёт)", r.get("efforts") == [], r)
    fake = json.dumps({"type": "user", "message": {"role": "user", "output_config": {"effort": "high"},
                                                   "content": "api-request-blob"}})
    r = accept([opus, fake, json.dumps({"type": "api-request-blob", "message": {"output_config": "high"}}), "не json"])
    check("effort только из записей type api-request-blob с объектом output_config", r.get("efforts") == [], r)
    r = accept([blob("high"), opus], kind="reject")
    check("reject — тоже с efforts", r.get("efforts") == ["high"], r)
    shutil.rmtree(proj, ignore_errors=True)
    h.reset()
    h.seed(tm.rec("tests", "latark/agent-kit", None, sha, "dev-opus"))
    h.post(f"pantheon review accept latark/agent-kit 7 {sha} --opened a --unchecked c --ran \"модель: claude-opus-5-5\"",
           "argus", agent_id="ag1", transcript=main_tp)
    r = [x for x in h.read() if x["kind"] == "accept"]
    check("транскрипта нет — ни models, ни efforts", r and "efforts" not in r[0] and "models" not in r[0], r)
    mg = tm._load_merge_gate("merge_gate_light3")
    check("_valid (read_records) принимает запись с полем efforts",
          mg._valid(dict(tm.rec("accept", "o/r", 7, sha), models=["claude-opus-5-5"], efforts=["high"])), "")


def main():
    t_light_pr()
    t_light_accept()
    base = None if not os.path.realpath(tempfile.gettempdir()).startswith(("/tmp", "/private/tmp")) else "/var/tmp"
    tmp = os.path.realpath(mkroot("light-pr-test-", first=base))
    try:
        h = tm.Home(tmp)
        h.reset()
        t_record_efforts(h)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
