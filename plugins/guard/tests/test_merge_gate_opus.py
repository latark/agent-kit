#!/usr/bin/env python3
"""Запор слияния guard, часть «opus»: argus на Opus в PR ядра: перечень ran, вне ядра, модель из транскрипта.

Общее (поддельный HOME, gh, записи журнала, запуск случаев) — _merge_gate_common.py; разрез metis-1119.
Запуск: python3 -I plugins/guard/tests/test_merge_gate_opus.py   (код 0 — все прошли)
"""
# ruff: noqa: F403, F405
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _merge_gate_common import *  # noqa: E402, F403


def t_opus_protect(h):
    """metis-0176: в репозитории защит «принять» засчитывается, только если ran начинается с «модель: claude-opus»;
    в остальных репозиториях модель не проверяется. Незаменённый «<ID>» — отказ с подсказкой."""
    kit, sha = "projects/agent-kit", h.sha["agent-kit"]
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    tests = rec("tests", "latark/agent-kit", None, sha, "dev-opus")
    sonnet = dict(CHECKLIST, ran="модель: claude-sonnet-5, heavy python3 -I tests/test_merge_gate.py")
    h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=sonnet))
    merge_case("защиты: «принять» argus на Sonnet — отказ", h.pre(cmd, pdir=kit), False, "не на Opus")
    merge_case("отказ не на Opus подсказывает argus на Opus", h.pre(cmd, pdir=kit), False,
               "Проверку повторяет argus на Opus")
    for ran in ("heavy python3 -I tests/test_merge_gate.py", "тесты, модель: claude-opus-5-5",
                "модель: claude-haiku-4-5, claude-opus в тексте"):
        h.reset()
        h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=dict(CHECKLIST, ran=ran)))
        merge_case(f"защиты: ran «{ran}» — отказ", h.pre(cmd, pdir=kit), False, "не на Opus")
    for ran in ("модель: claude-opus-5-5, тесты", "  Модель:claude-opus-4-1 тесты", "МОДЕЛЬ: CLAUDE-OPUS-5-5"):
        h.reset()
        h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=dict(CHECKLIST, ran=ran)))
        merge_case(f"защиты: ran «{ran}» — проходит", h.pre(cmd, pdir=kit), True)
    h.reset()
    h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=sonnet),
           rec("accept", "latark/agent-kit", 7, sha, agent_id="argus2"))
    merge_case("защиты: Sonnet и второй argus на Opus — проходит (Sonnet не засчитан, но и не мешает)",
               h.pre(cmd, pdir=kit), True)
    h.reset()
    h.seed(tests, rec("reject", "latark/agent-kit", 7, sha, checklist=None),
           rec("accept", "latark/agent-kit", 7, sha, checklist=sonnet))
    merge_case("защиты: «вернуть», потом «принять» того же argus на Sonnet — «вернуть» в силе", h.pre(cmd, pdir=kit),
               False, "«вернуть» (reject)")
    h.reset()
    h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=dict(CHECKLIST, ran="модель: <ID>, тесты")))
    merge_case("защиты: ran «модель: <ID>» в журнале — отказ", h.pre(cmd, pdir=kit), False, "не на Opus")
    merge_case("отказ с «<ID>» подсказывает подставить ID", h.pre(cmd, pdir=kit), False, "остался шаблон «<ID>»")
    h.reset()
    h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=None))
    merge_case("защиты: «принять» без перечня — по-прежнему отказ Б6, а не «не на Opus»", h.pre(cmd, pdir=kit), False,
               "без перечня проверенного (Б6)")
    # не защиты — модель не проверяется
    h.reset()
    tsha = h.sha["tg-read"]
    h.seed(rec("tests", "latark/tg-read", None, tsha, "dev-opus"),
           rec("accept", "latark/tg-read", 3, tsha, checklist=sonnet))
    merge_case("внутреннее: «принять» на Sonnet — проходит (модель проверяют только защиты)",
               h.pre(f"gh pr merge 3 --match-head-commit {tsha}"), True)
    # незаменённый «<ID>» в команде argus — отказ до записи, с подсказкой (раньше общего отказа за < и >)
    base = f"pantheon review accept latark/agent-kit 7 {sha} --opened a --unchecked c"
    for ran in ('"модель: <ID>, тесты"', '"модель: < id >"'):
        d, why = h.pre(f"{base} --ran {ran}", role="argus", agent_id="a1")
        check(f"accept --ran {ran} — отказ «<ID>»", d == "deny" and "остался шаблон «<ID>»" in why
              and "Записи не будет" in why, why)
    h.reset()
    h.post(f"{base} --ran \"модель: <ID>, тесты\"", "argus")
    check("accept с «<ID>» — записи нет", h.read() == [], h.read())
    d, why = h.pre(f"{base} --ran \"модель: claude-opus-5-5, тесты\"", role="argus", agent_id="a1")
    check("accept с моделью Opus — PreToolUse можно", d == "allow", why)
    mg = _load_merge_gate("merge_gate_o")
    _, _, why = mg.verdict_parse("accept", ["latark/agent-kit", "7", sha, "--opened", "a", "--ran", "модель: <ID>",
                                            "--unchecked", "c"])
    check("verdict_parse: «<ID>» в ran — ошибка", bool(why) and "<ID>" in why, why)
    _, _, why = mg.verdict_parse("reject", ["latark/agent-kit", "7", sha, "--ran", "модель: <ID>"])
    check("verdict_parse: «<ID>» в ran у reject — без ошибки (вердикт «вернуть» в силе любой)", why is None, why)


def t_opus_not_core(h):
    """Упрощение п. 9: вне ядра хватает одного «принять» argus на любой модели (Sonnet); Opus нужен только в PR,
    который задевает ядро. Ядро ли — тот же _core_problem, что у Д3; проверить не удалось — считается ядром."""
    kit, sha = "projects/agent-kit", h.sha["agent-kit"]
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    tests = rec("tests", "latark/agent-kit", None, sha, "dev-opus")
    sonnet = dict(CHECKLIST, ran="модель: claude-sonnet-5, heavy python3 -I tests/test_merge_gate.py")
    h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=sonnet))
    merge_case("не ядро: один «принять» argus на Sonnet — проходит", h.pre(cmd, pdir=kit), True)
    h.reset()
    h.seed(tests, dict(rec("accept", "latark/agent-kit", 7, sha, checklist=sonnet), models=["claude-sonnet-5"]))
    merge_case("не ядро: Sonnet по --ran и по транскрипту — проходит", h.pre(cmd, pdir=kit), True)
    h.reset()
    h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=dict(CHECKLIST, ran="без модели, тесты")))
    merge_case("не ядро: ran без «модель:» — проходит", h.pre(cmd, pdir=kit), True)
    h.reset()
    h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=None))
    merge_case("не ядро: «принять» без перечня — по-прежнему отказ Б6", h.pre(cmd, pdir=kit), False,
               "без перечня проверенного (Б6)")
    h.reset()
    h.seed(tests, rec("reject", "latark/agent-kit", 7, sha, checklist=None, agent_id="r1"),
           rec("accept", "latark/agent-kit", 7, sha, checklist=sonnet))
    merge_case("не ядро: «вернуть» другого argus и «принять» на Sonnet — «вернуть» в силе", h.pre(cmd, pdir=kit),
               False, "«вернуть» (reject)")
    # ядро: тот же Sonnet-«принять» — отказ (мутант: условие «не ядро» всегда истинно — эти случаи его убьют)
    for label, files in (("ядро (merge_gate.py)", ["README.md", "plugins/guard/hooks/merge_gate.py"]),
                         ("ядро (роли)", ["plugins/pantheon/roles/argus.tmpl"]),
                         ("ядро (.github)", [".github/workflows/release.yml"]),
                         ("ядро: переименование из ядра", [{"filename": "docs/x.md", "status": "renamed",
                                                          "previous_filename": "plugins/guard/README.md"}])):
        h.reset()
        h.gh(files)
        h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=sonnet))
        merge_case(f"{label}: «принять» на Sonnet — отказ «не на Opus»", h.pre(cmd, pdir=kit), False, "не на Opus")
    # проверить, ядро ли PR, не удалось — строго, как для ядра
    h.reset()
    open(h.j("gh.api.fail"), "w").close()
    h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=sonnet))
    merge_case("список файлов PR не получен: «принять» на Sonnet — отказ «не на Opus»", h.pre(cmd, pdir=kit), False,
               "не на Opus")
    h.reset()
    h.gh(["README.md", "code.py", "x.py"], count=5)
    h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=sonnet))
    merge_case("список файлов PR неполон: «принять» на Sonnet — отказ «не на Opus»", h.pre(cmd, pdir=kit), False,
               "не на Opus")
    h.reset()
    open(h.j("gh.fail"), "w").close()
    h.seed(tests, rec("accept", "latark/agent-kit", 7, sha, checklist=sonnet))
    merge_case("gh pr view не ответил: «принять» на Sonnet — отказ", h.pre(cmd, pdir=kit), False, "")
    # ядро и Opus: по-прежнему только со строкой владельца
    h.reset()
    h.gh(["plugins/guard/hooks/merge_gate.py"])
    h.seed(tests, rec("accept", "latark/agent-kit", 7, sha))
    merge_case("ядро: «принять» на Opus без строки владельца — отказ Д3", h.pre(cmd, pdir=kit), False, CORE)


def t_opus_transcript(h):
    """metis-0176 п. 2: модель argus — из его транскрипта (message.model assistant-записей), а не со слов --ran.
    Путь хук выводит из входа: <папка transcript_path>/<session_id>/subagents/[workflows/<runId>/]agent-<agent_id>.jsonl.
    В защитах «принять» засчитывается, только если все модели транскрипта Opus и среди них модель из --ran;
    транскрипта нет — как раньше, по --ran, с пометкой models_note в записи."""
    kit, sha = "projects/agent-kit", h.sha["agent-kit"]
    cmd = f"gh pr merge 7 --match-head-commit {sha}"
    tests = rec("tests", "latark/agent-kit", None, sha, "dev-opus")
    proj = h.j("cc-projects/-p")
    main_tp = os.path.join(proj, "s-coord.jsonl")

    def transcript(models, path=None, extra=()):
        path = path or os.path.join(proj, "s-coord", "subagents", "agent-ag1.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "assistant"}}) + "\n")
            for m in models:
                fh.write(json.dumps({"type": "assistant", "message": {"model": m, "role": "assistant"}}) + "\n")
            for line in extra:
                fh.write(line + "\n")
        return path

    def accept(ran="модель: claude-opus-5-5, тесты", agent_id="ag1", tp=main_tp, repo="latark/agent-kit", pr=7, s=sha):
        h.reset()
        h.seed(dict(tests, repo=[repo], sha=s))
        # главная сессия argus (agent_id нет) — своя сессия, не та, что сливает
        h.post(f"pantheon review accept {repo} {pr} {s} --opened a --unchecked c --ran \"{ran}\"", "argus",
               agent_id=agent_id, transcript=tp, session="s-coord" if agent_id else "s-argus")
        got = [r for r in h.read() if r["kind"] == "accept"]
        return got[0] if got else {}

    def clean():
        shutil.rmtree(proj, ignore_errors=True)

    clean()
    transcript(["claude-opus-5-5", "claude-opus-5-5"])
    r = accept()
    check("транскрипт субагента на Opus — в записи models, без пометки",
          r.get("models") == ["claude-opus-5-5"] and "models_note" not in r, r)
    merge_case("защиты: --ran и транскрипт — Opus 5.5 — проходит", h.pre(cmd, pdir=kit), True)
    clean()
    transcript(["claude-sonnet-5"])
    r = accept()
    check("транскрипт на Sonnet — в записи models claude-sonnet-5", r.get("models") == ["claude-sonnet-5"], r)
    merge_case("защиты: --ran говорит Opus, транскрипт — Sonnet — отказ", h.pre(cmd, pdir=kit), False,
               "по транскрипту argus — claude-sonnet-5")
    clean()
    transcript(["claude-opus-5-5", "claude-sonnet-5", "<synthetic>"])
    r = accept()
    check("модели транскрипта — все, кроме <synthetic>", r.get("models") == ["claude-opus-5-5", "claude-sonnet-5"], r)
    merge_case("защиты: модель сменилась на Sonnet в ходе проверки — отказ", h.pre(cmd, pdir=kit), False, "не на Opus")
    clean()
    transcript(["claude-opus-4-1"])
    accept()
    merge_case("защиты: --ran claude-opus-5-5, транскрипт claude-opus-4-1 — отказ (не совпадает)",
               h.pre(cmd, pdir=kit), False, "в --ran claude-opus-5-5, а по транскрипту argus — claude-opus-4-1")
    clean()
    transcript(["claude-opus-4-1-20250805"])
    accept(ran="модель: claude-opus-4-1, тесты")
    merge_case("защиты: --ran claude-opus-4-1, транскрипт с датой claude-opus-4-1-20250805 — проходит",
               h.pre(cmd, pdir=kit), True)
    # агент из Workflow (metis-0413 п. 1): Claude Code кладёт его транскрипт в subagents/workflows/<runId>/
    wf = os.path.join(proj, "s-coord", "subagents", "workflows", "wf_8f3a2c1d", "agent-ag1.jsonl")
    clean()
    transcript(["claude-sonnet-5"], path=wf)
    r = accept()
    check("Workflow: транскрипт в subagents/workflows/<runId>/ — найден, Sonnet в models",
          r.get("models") == ["claude-sonnet-5"] and "models_note" not in r, r)
    merge_case("Workflow: argus на Sonnet, --ran говорит Opus — отказ по транскрипту", h.pre(cmd, pdir=kit), False,
               "по транскрипту argus — claude-sonnet-5")
    clean()
    transcript(["claude-opus-5-5"], path=os.path.join(proj, "s-coord", "subagents", "wf1", "agent-ag1.jsonl"))
    r = accept()
    check("транскрипт в одной подпапке subagents/<подпапка>/ — тоже найден", r.get("models") == ["claude-opus-5-5"], r)
    # свой транскрипт не подменяется главным (metis-0413 п. 2): главный transcript_path — сессия того, кто позвал
    clean()
    transcript(["claude-opus-5-5"], path=main_tp)
    r = accept()
    check("своего файла нет, главный на Opus — models нет, пометка субагента (главный не читается, metis-0489)",
          "models" not in r and r.get("models_note") == mg_agent_note, r)
    merge_case("своего файла нет — в защитах не в счёт, причина названа (metis-0489)", h.pre(cmd, pdir=kit), False,
               f"({mg_agent_note})")
    transcript(["claude-sonnet-5"], path=wf)
    r = accept()
    check("главный на Opus, свой в Workflow на Sonnet — models свои (Sonnet), а не главного",
          r.get("models") == ["claude-sonnet-5"], r)
    merge_case("главный на Opus, свой на Sonnet — отказ", h.pre(cmd, pdir=kit), False,
               "по транскрипту argus — claude-sonnet-5")
    clean()
    transcript(["claude-sonnet-5"], path=main_tp)
    r = accept(agent_id=None)
    check("главная сессия argus (без agent_id) — модели из самого transcript_path", r.get("models") == ["claude-sonnet-5"], r)
    merge_case("защиты: главная сессия argus на Sonnet — отказ", h.pre(cmd, pdir=kit), False, "по транскрипту argus")
    # транскрипта нет: у главной сессии argus — как раньше, по --ran, с пометкой; у субагента (agent_id есть) — своя
    # пометка, в защитах не в счёт (metis-0489): его файл должен быть, «нет» — смена раскладки Claude Code или сбой
    clean()
    bait = os.path.join(proj, "agent-ag1.jsonl")  # приманка на Sonnet: читать её нельзя ни в одном случае ниже
    for label, tp, aid in (("файла нет", main_tp, "ag1"), ("transcript_path нет во входе", None, "ag1"),
                           ("transcript_path нет во входе, главная сессия", None, None),
                           ("путь не абсолютный", os.path.relpath(bait), None),
                           ("agent_id с ../", main_tp, "x/../../../agent-ag1")):
        transcript(["claude-sonnet-5"], path=bait)
        os.makedirs(os.path.join(proj, "s-coord", "subagents", "agent-x"))  # чтобы ../ из agent_id разрешился
        r = accept(agent_id=aid, tp=tp)
        note = mg_agent_note if aid else mg_note
        check(f"{label}: models нет, пометка «{note}»", "models" not in r and r.get("models_note") == note, r)
        if aid:
            merge_case(f"{label}: субагент без своего транскрипта — в защитах отказ (metis-0489)",
                       h.pre(cmd, pdir=kit), False, f"({mg_agent_note})")
        else:
            merge_case(f"{label}: главная сессия argus — «принять» на Opus по --ran проходит", h.pre(cmd, pdir=kit),
                       True)
        clean()
    # запись субагента старше metis-0489 (пометка NO_TRANSCRIPT, agent_id есть) — тоже не в счёт; без пометки (запись до
    # metis-0176) — по --ran, как раньше
    for label, extra, allow in (("прежняя пометка у субагента", {"models_note": mg_note}, False),
                                ("запись до metis-0176 без пометки", {}, True)):
        h.reset()
        h.seed(tests, dict(rec("accept", "latark/agent-kit", 7, sha, agent_id="ag1",
                               checklist=dict(CHECKLIST, ran="модель: claude-opus-5-5, тесты")), **extra))
        merge_case(f"защиты: {label} — {'проходит' if allow else 'отказ'}", h.pre(cmd, pdir=kit), allow,
                   f"({mg_agent_note})")
    # вне защит модель не проверяется: субагент без транскрипта — «принять» в счёт
    tsha = h.sha["tg-read"]
    accept(repo="latark/tg-read", pr=3, s=tsha, tp=None)
    merge_case("внутреннее: субагент без транскрипта — проходит (модель проверяют только защиты)",
               h.pre(f"gh pr merge 3 --match-head-commit {tsha}"), True)
    # транскрипт найден, а моделей в нём нет (metis-0413 п. 3): не молча как «транскрипта нет» — models: [] и своя
    # пометка; в защитах «принять» не в счёт даже с Opus в --ran, отказ называет причину
    transcript([], extra=("не json", json.dumps({"type": "assistant", "message": "x"}),
                          json.dumps({"type": "assistant", "message": {"model": "<synthetic>"}})))
    r = accept()
    check(f"в транскрипте нет моделей — models: [] и пометка «{mg_no_models}», не «транскрипта нет»",
          r.get("models") == [] and r.get("models_note") == mg_no_models, r)
    merge_case("транскрипт без моделей: --ran Opus — отказ, причина названа", h.pre(cmd, pdir=kit), False,
               f"({mg_no_models})")
    accept(ran="модель: claude-sonnet-5, тесты")
    merge_case("транскрипт без моделей: --ran Sonnet — отказ по --ran", h.pre(cmd, pdir=kit), False, "(по --ran)")
    # симлинк на транскрипт не читается (O_NOFOLLOW)
    clean()
    real = transcript(["claude-opus-5-5"], path=os.path.join(proj, "elsewhere.jsonl"))
    os.makedirs(os.path.join(proj, "s-coord", "subagents"))
    os.symlink(real, os.path.join(proj, "s-coord", "subagents", "agent-ag1.jsonl"))
    r = accept()
    check("транскрипт — симлинк: не читается, пометка субагента",
          "models" not in r and r.get("models_note") == mg_agent_note, r)
    # reject тоже несёт модели; не защиты — модель транскрипта не проверяется
    clean()
    transcript(["claude-sonnet-5"])
    h.reset()
    h.post(f"pantheon review reject latark/agent-kit 7 {sha}", "argus", agent_id="ag1", transcript=main_tp)
    check("reject — тоже с models", [r.get("models") for r in h.read()] == [["claude-sonnet-5"]], h.read())
    tsha = h.sha["tg-read"]
    accept(repo="latark/tg-read", pr=3, s=tsha)
    merge_case("внутреннее: транскрипт на Sonnet — проходит (модель проверяют только защиты)",
               h.pre(f"gh pr merge 3 --match-head-commit {tsha}"), True)
    clean()


mg_note = "транскрипта argus нет — модель по --ran"
mg_no_models = "транскрипт argus найден, но моделей в нём нет — модель не подтвердить"
mg_agent_note = "транскрипт субагента argus не найден — модель не подтвердить"  # metis-0489


CASES = [t_opus_protect, t_opus_not_core, t_opus_transcript]
# случаи про «не на Opus»: правило действует только в PR ядра (simplify п. 9), поэтому PR agent-kit#7 в них — ядро;
# вне ядра те же записи проходят — это проверяют отдельные места в самих случаях (h.core = False; h.reset())
CASES_CORE = (t_opus_protect, t_opus_transcript)


if __name__ == "__main__":
    sys.exit(main(CASES, CASES_CORE))
