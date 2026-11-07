#!/usr/bin/env python3
"""Правило «живой субагент» (lib/live_subagent.py, metis-0904) — общее для хука ctx и дежурного watch:

- фоновая команда (Д1): запущенная — только по ответу Bash в tool_result записи user; цитата в тексте ассистента, в
  поручении (строка user), в блоке tool_result записи не user — не запуск; содержимое tool_result строкой и списком
  блоков; конец — task-notification или TaskStop;
- сдача: последний ответ ассистента — SubagentHandback; ответы после сдачи (SendMessage поднял снова) — не сдан;
- done: stoppedByUser, finished без фоновой команды, сдача; finished с фоновой командой без итога — не done;
- live: время — позднее из журнала и meta.json (журнала нет — по meta), не старше LIVE_MAX; нынешнего процесса —
  старт неизвестен, запись позже старта + LIVE_GRACE или первая запись журнала позже старта; meta не словарь — нет.

Запуск: python3 -I plugins/pantheon/tests/test_live_subagent.py  (код выхода 0 — все прошли)
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "live_subagent.py")
spec = importlib.util.spec_from_file_location("live_subagent_under_test", LIB)
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
tmp = os.path.realpath(tempfile.mkdtemp(prefix="live-subagent-test-"))
results = []
NOW = time.time()


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:800]))


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def journal(name, records, at=None, meta=None, meta_at=None):
    """agent-<name>.jsonl из записей (dict или готовая строка) и, если meta не None, agent-<name>.meta.json."""
    jl = os.path.join(tmp, "agent-%s.jsonl" % name)
    with open(jl, "w") as f:
        for r in records:
            f.write((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n")
    t = NOW if at is None else at
    os.utime(jl, (t, t))
    if meta is not None:
        mp = R.meta_path(jl)
        with open(mp, "w") as f:
            json.dump(meta, f)
        mt = t if meta_at is None else meta_at
        os.utime(mp, (mt, mt))
    return jl


def user(content, ts=None):
    d = {"type": "user", "message": {"role": "user", "content": content}}
    if ts is not None:
        d["timestamp"] = iso(ts)
    return d


def result(content):
    return user([{"type": "tool_result", "tool_use_id": "t", "content": content}])


def says(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def handback(msg="готово"):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "h", "name": "SubagentHandback", "input": {"message": msg}}]}}


RUN = "Command running in background with ID: %s. Output is being written to: x"
MOVED = "Command was moved to the background (ID: %s) after running for 180s."


def note(i):
    return user("<task-notification>\n<task-id>%s</task-id>\n<status>completed</status>\n</task-notification>" % i)


def stop(i):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "s", "name": "TaskStop", "input": {"task_id": i}}]}}


try:
    # --- Д1: где искать запуск фоновой команды -----------------------------------------------------------------------
    bp = R.background_pending
    check("фон: ответ Bash в tool_result (строка) — идёт", bp(journal("b1", [result(RUN % "x1")])))
    check("фон: ответ Bash в tool_result (список блоков text) — идёт",
          bp(journal("b2", [result([{"type": "text", "text": MOVED % "x2"}])])))
    check("фон: текст ассистента с той же строкой — не запуск (Д1)",
          not bp(journal("b3", [says("видел: " + RUN % "x3")])))
    check("фон: поручение (строка user) с той же строкой — не запуск",
          not bp(journal("b4", [user("лог прошлого прогона: " + RUN % "x4")])))
    check("фон: блок tool_result в записи не user — не запуск",
          not bp(journal("b5", [{"type": "assistant", "message": {"role": "assistant", "content": [
              {"type": "tool_result", "content": RUN % "x5"}]}}])))
    check("фон: итог task-notification — закончена", not bp(journal("b6", [result(RUN % "x6"), note("x6")])))
    check("фон: TaskStop — закончена", not bp(journal("b7", [result(RUN % "x7"), stop("x7")])))
    check("фон: итог другой команды — эта идёт", bp(journal("b8", [result(RUN % "x8"), note("x9")])))
    check("фон: битые строки и нет файла — нет", not bp(journal("b9", ["{битая " + RUN % "y"]))
          and not bp(os.path.join(tmp, "нет.jsonl")))

    # --- сдача ----------------------------------------------------------------------------------------------------------
    check("сдача: последний ответ — SubagentHandback", R.handed_back(journal("h1", [says("сдаю"), handback(),
                                                                                    result("delivered"), "{битая"])))
    check("сдача: после сдачи снова ответы (SendMessage) — не сдан",
          not R.handed_back(journal("h2", [handback(), user("ещё одно"), says("продолжаю")])))
    check("сдача: без SubagentHandback — нет", not R.handed_back(journal("h3", [says("работаю")])))
    check("agent_report: текст последней сдачи, в том числе раньше последнего ответа",
          R.agent_report(journal("h4", [handback("первый"), says("продолжаю"), handback("  второй  "), says("x")]))
          == "второй" and R.agent_report(journal("h5", [says("x")])) == "")

    # --- done ---------------------------------------------------------------------------------------------------------
    plain = journal("d0", [says("работаю")])
    check("done: stoppedByUser", R.done({"stoppedByUser": True}, plain))
    check("done: finished без фоновой команды", R.done({"finished": True}, plain))
    check("done: finished, фоновая без итога — не done",
          not R.done({"finished": True}, journal("d1", [result(RUN % "z1")])))
    check("done: сдал последним ответом", R.done({}, journal("d2", [handback()])))
    check("done: ничего из этого — нет", not R.done({}, plain))
    check("agent_done: finished с фоновой без итога — нет; без finished — нет",
          not R.agent_done({"finished": True}, journal("d3", [result(RUN % "z3")])) and not R.agent_done({}, plain))

    # --- live: время и старт процесса -------------------------------------------------------------------------------
    started = NOW - 3600
    m = {"agentType": "dev"}
    check("live: журнал после старта + LIVE_GRACE", R.live(m, journal("l1", [says("x")], at=NOW - 60), started, NOW))
    check("live: журнал старше LIVE_MAX — нет",
          not R.live(m, journal("l2", [says("x")], at=NOW - R.LIVE_MAX - 60), 0, NOW))
    check("live: журнал до старта процесса — нет",
          not R.live(m, journal("l3", [says("x")], at=started - 60), started, NOW))
    check("live: старт неизвестен — только по сроку", R.live(m, journal("l4", [says("x")], at=started - 60), 0, NOW))
    check("live: журнал в пределах LIVE_GRACE, запущен после старта (born_after) — да",
          R.live(m, journal("l5", [user("x", ts=started + 5)], at=started + 30), started, NOW))
    check("live: журнал в пределах LIVE_GRACE, запущен до старта — нет",
          not R.live(m, journal("l6", [user("x", ts=started - 5)], at=started + 30), started, NOW))
    check("live: журнал старый, meta.json свежий — по позднему времени (как watch до metis-0904)",
          R.live(m, journal("l7", [says("x")], at=started - 600, meta=m, meta_at=NOW - 60), started, NOW))
    jl8 = journal("l8", [says("x")], meta=m, meta_at=NOW - 60)
    os.remove(jl8)
    check("live: журнала нет, meta.json свежий — живой", R.live(m, jl8, started, NOW))
    check("live: ни журнала, ни meta — нет", not R.live(m, os.path.join(tmp, "agent-nope.jsonl"), 0, NOW))
    check("live: finished с фоновой без итога — живой",
          R.live({"finished": True}, journal("l9", [result(RUN % "q")], at=NOW - 60), started, NOW))
    check("live: done — нет", not R.live({"finished": True}, journal("l10", [says("x")], at=NOW - 60), started, NOW)
          and not R.live({"stoppedByUser": True}, journal("l11", [says("x")], at=NOW - 60), started, NOW)
          and not R.live({}, journal("l12", [handback()], at=NOW - 60), started, NOW))
    check("live: сдал, а потом снова работает — живой",
          R.live({}, journal("l13", [handback(), user("ещё"), says("делаю")], at=NOW - 60), started, NOW))
    check("live: meta не словарь — нет", not R.live(["x"], journal("l14", [says("x")], at=NOW - 60), 0, NOW)
          and not R.live(None, journal("l15", [says("x")], at=NOW - 60), 0, NOW))
    check("stamp: позднее из журнала и meta",
          abs(R.stamp(journal("s1", [says("x")], at=NOW - 100, meta=m, meta_at=NOW - 10)) - (NOW - 10)) < 1
          and abs(R.stamp(journal("s2", [says("x")], at=NOW - 10, meta=m, meta_at=NOW - 100)) - (NOW - 10)) < 1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
