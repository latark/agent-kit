#!/usr/bin/env python3
"""Замер «как сейчас» на временных папках: коммит по вызову git commit (cd, git -C, -q без хеша), направление по
репозиторию коммита, разговор без коммита, ваши сообщения против служебных, возврат на переделку, автоматика,
цена из usage.py, недели.

Запуск: python3 -I plugins/pantheon/tests/test_baseline.py  (код выхода 0 — все прошли)
"""
import json
import os
import shutil
import subprocess
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import tempfile
# Все временные папки файла — внутри одной корневой, её убирает atexit при любом исходе (успех, провал, исключение);
# TMPDIR — для подпроцессов, которые тоже создают временные папки. Общий TMPDIR остаётся чистым.
import atexit as _atexit
import os as _os
import shutil as _shutil
_ROOT = tempfile.mkdtemp(prefix="baseline-root-")
tempfile.tempdir = _ROOT
_os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)
from datetime import datetime, timezone

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "baseline.py")
results = []


def check(name, ok):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name)


tmp = os.path.realpath(tempfile.mkdtemp(prefix="baseline-test-"))
home, pantheon, transcripts = tmp, os.path.join(tmp, "ai", "pantheon"), os.path.join(tmp, "claude-projects")
os.makedirs(pantheon)
with open(os.path.join(pantheon, "directions.toml"), "w") as fh:
    fh.write('[[direction]]\nname = "alpha"\nproject = "Альфа"\nfolders = ["~/projects/alpha"]\n\n'
             '[[direction]]\nname = "beta"\nproject = "Бета"\nfolders = ["~/projects/beta"]\n')
ENV = {"PATH": os.environ["PATH"], "HOME": home, "PANTHEON_HOME": pantheon, "BASELINE_TRANSCRIPTS": transcripts,
       "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "TZ": "Europe/Moscow"}
T0 = datetime(2026, 10, 8, 12, 0).timestamp()  # среда недели 07.10–13.10


def git(repo, *args, when=None):
    env = dict(ENV, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{int(when)} +0300"
    return subprocess.run(["git", "-C", repo, *args], env=env, capture_output=True, text=True, check=True).stdout


def repo(name):
    path = os.path.join(home, "projects", name)
    os.makedirs(path)
    git(path, "init", "-q")
    return path


def commit(path, file, text, msg, when):
    with open(os.path.join(path, file), "a") as fh:
        fh.write(text)
    git(path, "add", file)
    git(path, "commit", "-q", "-m", msg, when=when)
    return git(path, "rev-parse", "HEAD").strip()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def transcript(name, cwd, records, entry="cli"):
    folder = os.path.join(transcripts, cwd.replace("/", "-"))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name + ".jsonl"), "w") as fh:
        for i, r in enumerate(records):
            r.setdefault("cwd", cwd)
            r.setdefault("entrypoint", entry)
            r.setdefault("uuid", f"{name}-{i}")
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


def you(t, text):
    return {"type": "user", "timestamp": iso(t), "message": {"role": "user", "content": text}}


def bash(t, tid, cmd, req, cost_out=1000):
    return {"type": "assistant", "timestamp": iso(t), "requestId": req, "message": {
        "model": "claude-opus-5-5", "id": req, "content": [{"type": "tool_use", "id": tid, "name": "Bash",
                                                              "input": {"command": cmd}}],
        "usage": {"input_tokens": 0, "output_tokens": cost_out, "cache_read_input_tokens": 0}}}


def result(t, tid, text="", error=False):
    return {"type": "user", "timestamp": iso(t), "toolUseResult": {"stdout": text},
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": text,
                                                       "is_error": error}]}}


alpha, beta = repo("alpha"), repo("beta")
# Разговор 1 (из alpha): коммит в alpha через cd и -q, коммит в beta через git -C — две задачи
c1 = T0
transcript("conv1", alpha, [
    you(c1, "сделай фичу"),
    you(c1 + 5, "<command-name>/clear</command-name>"),
    {"type": "user", "timestamp": iso(c1 + 6), "isMeta": True, "message": {"content": "Caveat: служебное"}},
    bash(c1 + 60, "t1", f"cd {alpha} && git add a.txt && git commit -q -m 'фича'", "r1"),
    result(c1 + 62, "t1"),
    you(c1 + 120, "не так, переделай заголовок"),
    bash(c1 + 180, "t2", f"git -C {beta} commit -q -F - <<'EOF'\nправка беты\nEOF", "r2"),
    result(c1 + 182, "t2"),
])
sha_a = commit(alpha, "a.txt", "1", "фича", c1 + 61)
sha_b = commit(beta, "b.txt", "1", "правка беты", c1 + 181)
# Ошибка git commit — коммит в это время не засчитывается этому разговору
transcript("conv2", alpha, [you(c1 + 3600, "попробуй"), bash(c1 + 3610, "t3", "git commit -m x", "r3"),
                            result(c1 + 3612, "t3", "nothing to commit", error=True)])
commit(alpha, "d.txt", "1", "ручной коммит в тот же момент", c1 + 3611)  # не этого разговора: его commit упал
# Разговор 3 (из beta): исправление файла задачи из разговора 1 через два дня — возврат для alpha
c3 = T0 + 2 * 86400
transcript("conv3", beta, [you(c3, "почини"), bash(c3 + 30, "t4", f"cd {alpha} && git commit -q -am 'fix: заголовок'", "r4"),
                           result(c3 + 32, "t4")])
commit(alpha, "a.txt", "2", "fix: заголовок", c3 + 31)
# Коммит с «fix-labels» в середине — не исправление
commit(alpha, "c.txt", "1", "docs: правила fix-labels для годов", c3 + 600)
# Разговор без коммита
transcript("conv4", beta, [you(T0 + 4 * 3600, "изучи вопрос"), you(T0 + 4 * 3600 + 60, "спасибо")])
# Автоматический прогон: цена — в «Автоматике», в задачи не входит
transcript("auto1", alpha, [you(T0 + 7200, "ежечасная проверка"), bash(T0 + 7210, "t5", "ls", "r5", 5000),
                            result(T0 + 7211, "t5")], entry="sdk-py")
# Разговор вне периода — не считается
transcript("old", alpha, [you(T0 - 30 * 86400, "давно"), bash(T0 - 30 * 86400 + 5, "t6", "ls", "r6")])

r = subprocess.run([PY311, "-I", SCRIPT, "--end", "2026-10-14", "--weeks", "1"], env=ENV,
                   capture_output=True, text=True, timeout=120)
out = r.stdout
check("скрипт отработал", r.returncode == 0 and "# Замер «как сейчас»: 07.10–13.10.2026" in out)
rows = {}
for line in out.split("## По неделям")[0].splitlines():
    if line.startswith("| ") and not line.startswith("| Направление") and not line.startswith("| ---"):
        cells = [x.strip() for x in line.split("|")[1:-1]]
        rows[cells[0]] = cells
alpha_row, beta_row = rows.get("alpha (Альфа)"), rows.get("beta (Бета)")
check("alpha: две доведённые задачи (разговор 1 и починка из разговора 3)", alpha_row and alpha_row[2] == "2")
check("beta: задача по репозиторию коммита (git -C), хотя разговор открыт в alpha", beta_row and beta_row[2] == "1")
check("beta: разговор без коммита — отдельной колонкой", beta_row and beta_row[5] == "1")
check("ошибка git commit не делает задачу", alpha_row and alpha_row[1] == "3" and alpha_row[5] == "1")
check("возврат: fix: в начале, те же файлы, другой разговор — 1 из 2", alpha_row and alpha_row[8] == "1 из 2")
check("«fix-labels» в середине сообщения — не исправление (коммитов 4, возвратов 1)", alpha_row and alpha_row[10] == "4")
check("ваши сообщения: служебные не считаются (разговор 1 — 2 сообщения на 2 задачи → 1)",
      alpha_row and alpha_row[6].startswith("1 /"))
check("поправка «не так» учтена", alpha_row and alpha_row[7] != "—" and float(alpha_row[7]) > 0)
check("автоматика: цена отдельно, в разговоры не входит", alpha_row and alpha_row[11] != "—")
total = rows.get("**Всего**")
check("итог: 3 задачи", total and total[2] == "3")
check("правила подсчёта в отчёте", "## Правила подсчёта" in out and "В активную неделю" in out)
check("без --narrow и --p1 новых разделов и правил нет",
      "## Узко" not in out and "## Метрики P1" not in out and "Узкий режим" not in out and "Метрики P1" not in out)
if not all(results):
    print(out.split("## По неделям")[0], r.stderr[-2000:])


def table(text, head, stop="\n## "):
    """Строки таблицы раздела `head` → {первая ячейка: ячейки}."""
    part = text.split(head, 1)[1] if head in text else ""
    part = part.split(stop, 1)[0]
    found = {}
    for line in part.splitlines():
        if line.startswith("| ") and not line.startswith("| ---"):
            cells = [x.strip() for x in line.split("|")[1:-1]]
            found.setdefault(cells[0], cells)
    return found


def run(*flags):
    p = subprocess.run([PY311, "-I", SCRIPT, "--end", "2026-10-14", "--weeks", "1", *flags], env=ENV,
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr


# Узкий режим на тех же данных: разговор 1 (alpha) — своя задача в alpha; «не так, переделай» через минуту после
# коммита в alpha — приёмка; /clear не считается; задача beta из разговора 1 и починка alpha из разговора 3 (beta) —
# коммиты в чужое направление, узкий счёт их не видит
code, out, err = run("--narrow")
nr = table(out, "## Узко")
check("узко на старых данных: alpha — 1 задача, 2 сообщения (постановка и приёмка), beta — 0",
      code == 0 and nr.get("alpha (Альфа)", [""] * 6)[3:5] == ["1", "2 / 2.0"]
      and nr.get("beta (Бета)", [""] * 6)[3] == "0")
check("узко: широкие столбцы те же, что в итоге", nr.get("alpha (Альфа)", [""] * 6)[1] == "2")
check("правила узкого режима в отчёте только с --narrow", "Узкий режим (--narrow)" in out and "Метрики P1 (--p1)" not in out)
if not all(results):
    print(out.split("## Правила")[0], err[-2000:])

# Второй набор: узкий режим и P1 на своих папках — роли, координатор, очередь сообщений
tmp2 = os.path.realpath(tempfile.mkdtemp(prefix="baseline-test2-"))
home, pantheon, transcripts = tmp2, os.path.join(tmp2, "ai", "pantheon"), os.path.join(tmp2, "claude-projects")
os.makedirs(pantheon)
with open(os.path.join(pantheon, "directions.toml"), "w") as fh:
    fh.write('[[direction]]\nname = "alpha"\nproject = "Альфа"\nfolders = ["~/projects/alpha"]\n\n'
             '[[direction]]\nname = "beta"\nproject = "Бета"\nfolders = ["~/projects/beta"]\n\n'
             '[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\nfolders = ["~/projects/pant"]\n')
os.makedirs(os.path.join(home, ".claude", "agents"))
for role, text in (("hephaestus-alpha", "<!-- собрано pantheon roles build из lead.tmpl -->\nЛид."),
                   ("helper", "Обычный агент, не роль Пантеона.")):
    with open(os.path.join(home, ".claude", "agents", role + ".md"), "w") as fh:
        fh.write(text)
ENV = dict(ENV, HOME=home, PANTHEON_HOME=pantheon, BASELINE_TRANSCRIPTS=transcripts)
alpha, beta, pant = repo("alpha"), repo("beta"), repo("pant")
T1 = T0 + 86400


def note(t, text, **extra):
    r = you(t, text)
    r.update(extra)
    return r


def tools(t, req, *calls):
    return {"type": "assistant", "timestamp": iso(t), "requestId": req, "message": {
        "model": "claude-opus-5-5", "id": req, "content": [{"type": "tool_use", "id": tid, "name": name, "input": {}}
                                                           for tid, name in calls],
        "usage": {"input_tokens": 0, "output_tokens": 10, "cache_read_input_tokens": 0}}}


def queue(t, op, content=None):
    r = {"type": "queue-operation", "operation": op, "timestamp": iso(t)}
    if content is not None:
        r["content"] = content
    return r


def subagent(conv, cwd, agent, agent_type, records):
    folder = os.path.join(transcripts, cwd.replace("/", "-"), conv, "subagents")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"agent-{agent}.meta.json"), "w") as fh:
        json.dump({"agentType": agent_type}, fh)
    with open(os.path.join(folder, f"agent-{agent}.jsonl"), "w") as fh:
        for i, r in enumerate(records):
            r.setdefault("cwd", cwd)
            r.setdefault("uuid", f"{conv}-{agent}-{i}")
            r["isSidechain"] = True
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")


# n1 (alpha): постановка, служебное и не ваше, уточнение, коммит, приёмка дважды в 2 ч, обсуждение через 3 ч
k = T1
transcript("n1", alpha, [
    you(k, "поставь задачу"),
    you(k + 10, "[Пантеон: старт] роль поднята"),
    note(k + 20, "привет от соседней сессии", origin={"kind": "peer"}),
    note(k + 30, "фоновая задача закончилась", origin={"kind": "task-notification"}),
    note(k + 35, "ввод от системы", promptSource="system"),
    you(k + 40, "<command-message>commit-commands:commit</command-message>"),
    you(k + 50, "уточнение"),
    bash(k + 100, "u1", "git commit -q -m 'задача'", "q1"),
    result(k + 102, "u1"),
    you(k + 102 + 3600, "принято"),
    you(k + 102 + 3700, "и ещё мелочь"),
    you(k + 102 + 3 * 3600, "обсудим потом"),
])
commit(alpha, "n.txt", "1", "задача", k + 101)
# n2 (папка Пантеона) — сборка системы; n3 (вне направлений) и n4 (beta) коммитят только в alpha
transcript("n2", pant, [you(k + 20000, "правка системы"), bash(k + 20010, "u2", "git commit -q -m s", "q2"),
                        result(k + 20012, "u2")])
commit(pant, "p.txt", "1", "s", k + 20011)
transcript("n3", home, [you(k + 30000, "из дома"), bash(k + 30010, "u3", f"git -C {alpha} commit -q -m h", "q3"),
                        result(k + 30012, "u3")])
commit(alpha, "h.txt", "1", "h", k + 30011)
transcript("n4", beta, [you(k + 40000, "из беты"), bash(k + 40010, "u4", f"cd {alpha} && git commit -q -m b", "q4"),
                        result(k + 40012, "u4")])
commit(alpha, "b.txt", "1", "b", k + 40011)

# P1: координатор (agent-setting) с Agent, Skill, qmd, Read и повтором того же вызова; очередь — ваше сообщение ждёт
# 15 мин, сообщение сессии снято через 10 с (remove), ваше второе не взято до конца (60 с)
q = T1 + 50000
transcript("coord", beta, [
    {"type": "agent-setting", "agentSetting": "domain-coordinator", "sessionId": "coord"},
    you(q, "запусти работу"),
    tools(q + 10, "c1", ("a1", "Agent"), ("a2", "Skill"), ("a3", "mcp__qmd__query"), ("a4", "Read")),
    tools(q + 11, "c1b", ("a1", "Agent")),
    queue(q + 100, "enqueue", "ещё одно от вас"),
    queue(q + 1000, "dequeue"),
    queue(q + 1100, "enqueue", "<cross-session-message from=\"x\">привет</cross-session-message>"),
    queue(q + 1110, "remove", "<cross-session-message from=\"x\">привет</cross-session-message>"),
    queue(q + 2000, "enqueue", "и последнее"),
    tools(q + 2060, "c2", ("a5", "Read")),
])
subagent("coord", beta, "lead", "hephaestus-alpha", [tools(q + 20, "s1", ("b1", "Agent"), ("b2", "Bash"))])
subagent("coord", beta, "look", "Explore", [tools(q + 30, "s2", ("e1", "Read"), ("e2", "Skill"))])
subagent("coord", beta, "help", "helper", [tools(q + 40, "s3", ("h1", "Agent"))])

code, out, err = run("--narrow", "--p1")
check("второй набор: скрипт отработал с --narrow --p1", code == 0 and "## Узко" in out and "## Метрики P1" in out)
nr = table(out, "## Узко")
a = nr.get("alpha (Альфа)", [""] * 6)
check("узко alpha: одна задача кода (n1), из дома и из beta — не считаются", a[3] == "1" and a[1] == "3")
check("узко: постановка + уточнение + одна приёмка = 3; Пантеон, сессии, система, слэш-команда и поздний разговор — нет",
      a[4] == "3 / 3.0" and a[5] == "1 из 1")
check("узко: metis-pantheon — сборка системы, не задача кода",
      nr.get("metis-pantheon (Пантеон)", [""] * 6)[3].startswith("— (сборка системы)"))
check("узко: итог — 1 задача кода", nr.get("**Всего**", [""] * 6)[3] == "1")
p1 = table(out, "## Метрики P1", "\n### ")
coord = p1.get("Координаторы (основные сессии domain-coordinator)", [""] * 7)
check("P1 координатор: 5 вызовов (повтор id не считается), Agent 1 = 20 %, Skill 1, qmd 1",
      coord[1:] == ["1", "5", "1", "20.0 %", "1", "1"])
role = p1.get("Другие роли Пантеона (основные и субагенты)", [""] * 7)
check("P1 роли: субагент-лид из agents с пометкой сборки; агент без пометки — не роль",
      role[1:] == ["1", "2", "1", "50.0 %", "0", "0"])
sub = p1.get("Прочие субагенты (Explore, general-purpose, …)", [""] * 7)
check("P1 прочие субагенты: Explore и helper, Skill 1", sub[1:4] == ["2", "3", "1"] and sub[5] == "1")
both = p1.get("**Роли всего** (координаторы и другие роли)", [""] * 7)
check("P1 роли всего: 7 вызовов, 2 поручения", both[1:5] == ["2", "7", "2", "28.6 %"])
waits = [x for x in out.split("### Ожидание", 1)[-1].split("\n## ", 1)[0].splitlines()
         if x.startswith("| Координаторы")]
mine = [x for x in waits if "| вы |" in x]
peer = [x for x in waits if "| другие сессии" in x]
check("очередь: ваших 2 — одно ждало 15 мин, одно не взято (60 с), медиана 8 мин",
      mine and [c.strip() for c in mine[0].split("|")[3:8]] == ["2", "8 мин", "1", "1", "15 мин"])
check("очередь: сообщение сессии снято через 10 с", peer and [c.strip() for c in peer[0].split("|")[3:8]]
      == ["1", "10 с", "0", "0", "10 с"])
check("правила P1 в отчёте с --p1", "Метрики P1 (--p1)" in out and "Узкий режим (--narrow)" in out)
if not all(results):
    print(out.split("## Правила")[0], err[-2000:])
shutil.rmtree(tmp2)
shutil.rmtree(tmp)
print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
