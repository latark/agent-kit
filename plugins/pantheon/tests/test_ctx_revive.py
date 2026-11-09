#!/usr/bin/env python3
"""Список оборванных субагентов при продолжении сессии (hooks/ctx.py start, source=resume, metis-0864 слой 3):

- субагент без finished и stoppedByUser в meta.json, чей журнал записан до старта процесса и не старше
  REVIVE_MAX_AGE, попадает в список с типом, описанием, agentId, журналом, worktree и последним текстом;
- законченный, остановленный вами, старый и записанный уже нынешним процессом — не попадают;
- второй resume список не повторяет (метка ctx/marks/revive-<sid>), новый оборванный — показывается один;
- битый meta.json не роняет хук; сбой записи метки — строка в журнале хуков, SessionStart идёт дальше;
- не resume, субагент (agent_id), PANTHEON_CTX_OFF, неизвестный старт процесса — списка нет;
- process_started: позднее из записи реестра имён и ps, запись чужого PID не в счёт.

Запуск: python3 -I plugins/pantheon/tests/test_ctx_revive.py  (код выхода 0 — все прошли)
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HOOK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "ctx.py")
PY = os.environ.get("CTX_TEST_PYTHON") or sys.executable
tmp = os.path.realpath(tempfile.mkdtemp(prefix="ctx-revive-test-"))
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:900]))


home = tmp
pantheon, state = os.path.join(home, "ai", "pantheon"), os.path.join(home, ".local", "state", "pantheon")
for d in (pantheon, state, os.path.join(home, "tr"), os.path.join(home, ".claude", "sessions")):
    os.makedirs(d, exist_ok=True)
PID = str(os.getpid())
BASE = {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pantheon, "PANTHEON_VIEW": os.path.join(home, "v"),
        "PANTHEON_STATE": state, "CLAUDE_PID": PID, "CLAUDE_CODE_ENTRYPOINT": "cli", "TZ": "Europe/Moscow",
        "TMPDIR": tmp}
os.environ.update(BASE)
spec = importlib.util.spec_from_file_location("ctx_under_test", HOOK)
ctx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ctx)
HLOG = os.path.join(state, "logs", "ctx-hooks.log")
NOW = time.time()
# старт «нынешнего процесса» — запись реестра имён, как её пишет Claude Code (позднее ps запуска теста)
with open(os.path.join(home, ".claude", "sessions", PID + ".json"), "w") as f:
    json.dump({"pid": int(PID), "sessionId": "x", "startedAt": int(NOW * 1000)}, f)


def run(ev, **env):
    e = dict(BASE)
    for k, v in env.items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = v
    return subprocess.run([PY, "-I", HOOK, "start"], input=json.dumps(ev), env=e, capture_output=True, text=True,
                          timeout=60)


def ctx_text(out):
    try:
        return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError):
        return ""


def session(sid):
    tp = os.path.join(home, "tr", sid + ".jsonl")
    open(tp, "a").close()
    return {"session_id": sid, "transcript_path": tp, "source": "resume", "cwd": home}


def sub(ev, aid, meta, age=600, texts=("работаю над задачей",), raw_meta=None):
    folder = os.path.join(os.path.dirname(ev["transcript_path"]), ev["session_id"], "subagents")
    os.makedirs(folder, exist_ok=True)
    jl = os.path.join(folder, "agent-%s.jsonl" % aid)
    with open(jl, "w") as f:
        f.write(json.dumps({"type": "user", "agentId": aid, "message": {"role": "user", "content": "поручение"}}) + "\n")
        for t in texts:
            f.write(json.dumps({"type": "assistant", "agentId": aid, "message": {
                "role": "assistant", "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": t}]}},
                ensure_ascii=False) + "\n")
        f.write(json.dumps({"type": "assistant", "agentId": aid, "message": {
            "role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "x"}}]}}) + "\n")
        f.write("{битая строка\n")
    raw = raw_meta if raw_meta is not None else json.dumps(meta, ensure_ascii=False)
    with open(os.path.join(folder, "agent-%s.meta.json" % aid), "wb") as f:
        f.write(raw if isinstance(raw, bytes) else raw.encode())
    t = NOW - age
    os.utime(jl, (t, t))
    return jl


def meta(kind="dev-opus", desc="задача", **kw):
    m = {"agentType": kind, "isBuiltIn": False, "description": desc, "spawnDepth": 1, "requestShape": "background"}
    m.update(kw)
    return m


try:
    # 1. оборванный — в списке; законченный, остановленный, старый, записанный нынешним процессом — нет
    ev = session("s-main")
    wt = os.path.join(home, "wt", "agent-a1")
    jl1 = sub(ev, "a1", meta(desc="metis-0864 слой 3", name="dev-0864", worktreePath=wt),
              texts=("первый шаг", "  правлю   ctx.py,\n тесты дальше  "))
    sub(ev, "a2", meta(desc="законченный", finished=True))
    sub(ev, "a3", meta(desc="остановлен вами", stoppedByUser=True))
    sub(ev, "a4", meta(desc="давний"), age=ctx.REVIVE_MAX_AGE + 120)
    sub(ev, "a5", meta(desc="уже этого процесса"), age=-30)
    out = run(ev)
    text = ctx_text(out)
    check("resume: код 0 и есть блок", out.returncode == 0 and "Оборванные субагенты" in text, out.stdout + out.stderr)
    check("оборванный в списке: тип, описание, agentId, имя, журнал, worktree",
          "- dev-opus «metis-0864 слой 3» (agentId a1, имя dev-0864," in text
          and ctx.tilde(jl1) in text and "worktree ~/wt/agent-a1" in text, text)
    check("последний текст субагента — последний ассистентский, одной строкой", "«правлю ctx.py, тесты дальше»" in text,
          text)
    check("законченный (finished) не в списке", "законченный" not in text, text)
    check("остановленный вами (stoppedByUser) не в списке", "остановлен вами" not in text, text)
    check("старше REVIVE_MAX_AGE не в списке", "давний" not in text, text)
    check("журнал записан после старта процесса — не в списке", "уже этого процесса" not in text, text)
    check("указание: решает окно, SendMessage, новый субагент, worktree; итог живой пробы",
          all(s in text for s in ("решаешь ты", "SendMessage", "новый субагент того же типа", "worktree исполнителя",
                                  "Claude Code 2.1.318", "запускает заново")), text)
    with open(os.path.join(os.path.dirname(jl1), "agent-a1.meta.json")) as f:
        check("meta.json Claude Code не тронут", json.load(f).get("finished") is None)

    # 2. второй resume — не повторяет; новый оборванный — только он
    out2 = run(ev)
    check("второй resume: списка нет", out2.returncode == 0 and "Оборванные субагенты" not in ctx_text(out2),
          out2.stdout + out2.stderr)
    sub(ev, "a6", meta(desc="новый оборванный"))
    t3 = ctx_text(run(ev))
    check("третий resume: только новый оборванный", "новый оборванный" in t3 and "agentId a1," not in t3, t3)
    mark = json.load(open(ctx.revive_mark_path("s-main")))
    check("метка в state Пантеона хранит показанных", mark.get("agents") == ["a1", "a6"], mark)

    # 3. битый meta.json не роняет хук; рядом годный показывается
    ev = session("s-broken")
    sub(ev, "b1", None, raw_meta="{не json")
    sub(ev, "b2", None, raw_meta="[1, 2]")
    sub(ev, "b3", None, raw_meta=b"\xff\xfe{")
    sub(ev, "b4", meta(desc="годный рядом с битыми"))
    out = run(ev)
    text = ctx_text(out)
    check("битый meta.json: код 0, годный в списке, битых нет",
          out.returncode == 0 and "годный рядом с битыми" in text and "agentId b1" not in text
          and "agentId b2" not in text, out.stdout + out.stderr)

    # 4. не resume, субагент, выключатель, неизвестный старт процесса — списка нет
    for name, evx, env in (("startup", dict(session("s-x1"), source="startup"), {}),
                           ("событие субагента (agent_id)", dict(session("s-x2"), agent_id="zz"), {}),
                           ("PANTHEON_CTX_OFF=1", session("s-x3"), {"PANTHEON_CTX_OFF": "1"}),
                           ("CLAUDE_PID не число", session("s-x4"), {"CLAUDE_PID": "abc"})):
        sub(evx, "c1", meta(desc="оборванный c1"))
        o = run(evx, **env)
        check("%s: списка нет, код 0" % name, o.returncode == 0 and "оборванный c1" not in ctx_text(o),
              o.stdout + o.stderr)

    # 5. сбой записи метки — строка в журнале хуков, хук не падает, список не выдан (иначе повторится)
    ev = session("s-fail")
    sub(ev, "d1", meta(desc="метку не записать"))
    marks = os.path.join(state, "ctx", "marks")
    os.makedirs(marks, exist_ok=True)
    os.makedirs(ctx.revive_mark_path("s-fail") + ".lock")  # замок — папка: open() упадёт
    out = run(ev)
    log = open(HLOG).read() if os.path.exists(HLOG) else ""
    check("сбой метки: код 0, списка нет, строка в журнале хуков",
          out.returncode == 0 and "метку не записать" not in ctx_text(out)
          and "список оборванных субагентов не собран" in log, out.stdout + out.stderr + log)

    # 6. длинный последний текст режется до REVIVE_TEXT; много субагентов — «ещё N»
    ev = session("s-long")
    sub(ev, "e0", meta(desc="длинный"), texts=("я" * 1000,))
    for i in range(1, ctx.REVIVE_SHOW + 3):
        sub(ev, "e%d" % i, meta(desc="много %d" % i), age=600 - i)
    text = ctx_text(run(ev))
    check("длинный текст обрезан до REVIVE_TEXT", ("«" + "я" * (ctx.REVIVE_TEXT - 1) + "…»") in text
          and "я" * ctx.REVIVE_TEXT not in text, text[:600])
    check("больше REVIVE_SHOW — первые и строка «ещё N»",
          text.count("\n- dev-opus") == ctx.REVIVE_SHOW and "- ещё 3 — в папке" in text, text)
    check("весь вывод в пределе INJECT_MAX", len(text) <= ctx.INJECT_MAX)
    ev = session("s-room")
    for i in range(3):
        sub(ev, "r%d" % i, meta(desc="тесно %d" % i), age=600 - i, texts=("ж" * 250,))
    block = ctx.revive_block(ev, room=1200)
    check("мало места в пределе хука: блок в room, остальные — строкой «ещё N»",
          block and len(block) <= 1200 and "тесно 0" in block and "тесно 2" not in block
          and "- ещё 2 — в папке" in block, block)

    # 7. process_started: запись реестра имён и ps, чужой PID в записи не в счёт
    reg = os.path.join(home, ".claude", "sessions", PID + ".json")
    st = ctx.process_started(PID)
    check("process_started: запись реестра позднее ps — берётся она", abs(st - NOW) < 1.5, (st, NOW))
    with open(reg, "w") as f:
        json.dump({"pid": int(PID), "startedAt": int((NOW - 10 * 86400) * 1000)}, f)
    st = ctx.process_started(PID)
    # граница — запуск самого PID по ps, а не NOW - 600: от длины прогона не зависит (metis-0909)
    try:
        ps_out = subprocess.run(["ps", "-o", "etime=", "-p", PID], capture_output=True, text=True,
                                env=dict(os.environ, LC_ALL="C")).stdout.strip()
    except OSError:
        ps_out = ""
    pm = re.fullmatch(r"(?:(?:(\d+)-)?(\d+):)?(\d+):(\d+)", ps_out)
    if not pm:
        print("пропущено: ps недоступен (песочница окна) — проверка «время ps, а не запись 10-дневной давности»")
    else:
        d, h, mi, sec = (int(x or 0) for x in pm.groups())
        ps_start = time.time() - (((d * 24 + h) * 60 + mi) * 60 + sec)
        check("process_started: устаревшая запись — время ps (запуск этого PID, не 10 дней назад)",
              abs(st - ps_start) < 5 and st > NOW - 86400, (st, ps_start, NOW))
    with open(reg, "w") as f:
        json.dump({"pid": 1, "startedAt": int((NOW + 3600) * 1000)}, f)
    st = ctx.process_started(PID)
    check("process_started: запись с чужим pid не в счёт", st <= time.time(), (st, NOW))
    check("process_started: не число и мёртвый PID — 0",
          ctx.process_started("x") == 0.0 and ctx.process_started("999999999") == 0.0)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("%d/%d" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
