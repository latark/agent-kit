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
import tempfile
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

r = subprocess.run([sys.executable, "-I", SCRIPT, "--end", "2026-10-14", "--weeks", "1"], env=ENV,
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

if not all(results):
    print(out.split("## По неделям")[0], r.stderr[-2000:])
shutil.rmtree(tmp)
print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
