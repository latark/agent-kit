#!/usr/bin/env python3
"""Тест `pantheon sync-answers` (metis-0209, SEC-15): ответ владельца по карантину ~/.claude запускает sync.sh.

Ответ — галочка на доске (owner-log/board.jsonl) или выбор в окне вопросов Зевса (owner-log/zeus.md, пометка
«· окно вопросов», вопрос «[<id>] …», строка «ответ: …», не старше 7 дней); из двух берётся более поздний — как в
настоящем sync.sh (owner_answer). Здесь sync.sh — заглушка, пишущая отметку: проверяется только «пора ли запускать».
Сам разбор карантина проверяет tests/test_sync_quarantine.sh (нужен настоящий ~/.claude/sync.sh).

Запуск: python3 -I plugins/pantheon/tests/test_sync_quarantine.py  (код выхода 0 — все прошли)
Идёт и на системном /usr/bin/python3 (3.9): pantheon.py тогда запускается через python3 3.11+ (tests/_py311.py).
Временный HOME и состояние; настоящие ~/.claude и журналы не трогаются.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

ROOT = tempfile.mkdtemp(prefix="sync-quarantine-")
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
T0 = 1_800_000_000
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  {detail}"))


def stamp(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


class Env:
    n = 0

    def __init__(self, task="metis-0099", held=".sync-held"):
        Env.n += 1
        base = os.path.join(ROOT, f"e{Env.n}")
        self.home = os.path.join(base, "home")
        self.claude = os.path.join(self.home, ".claude")
        self.pan = os.path.join(self.home, "ai", "pantheon")
        self.state = os.path.join(base, "state")
        self.mark = os.path.join(base, "sync-runs")
        self.task = task
        for d in (self.claude, self.pan, os.path.join(self.state, "owner-log")):
            os.makedirs(d)
        sh = os.path.join(self.claude, "sync.sh")
        with open(sh, "w") as fh:
            fh.write(f'#!/bin/sh\necho x >> "{self.mark}"\n')
        os.chmod(sh, 0o755)
        with open(os.path.join(self.claude, held), "w") as fh:
            fh.write(f"hash=abc\ntask={task}\nfiles=1\n")

    def board(self, answer, t=T0 - 100, tid=None):
        rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)), "kind": "answer",
               "id": tid or self.task, "answer": answer}
        with open(os.path.join(self.state, "owner-log", "board.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def window(self, answer, t=T0 - 100, tid=None, mark="· окно вопросов", q="[{id}] что делать с правкой?"):
        head = f"## {stamp(t)}" + (f" {mark}" if mark else "")
        body = f"вопрос: {q.format(id=tid or self.task)}\nответ: {answer}\n"
        with open(os.path.join(self.state, "owner-log", "zeus.md"), "a", encoding="utf-8") as fh:
            fh.write(f"{head}\n{body}\n")

    def run(self):
        env = {"PATH": os.environ["PATH"], "HOME": self.home, "PANTHEON_HOME": self.pan, "PANTHEON_STATE": self.state,
               "PANTHEON_NOW": str(T0), "PANTHEON_HOST": "mac-a", "PANTHEON_NO_NOTIFY": "1", "TMPDIR": ROOT}
        r = subprocess.run([PY311, "-I", LIB, "sync-answers"], env=env, capture_output=True, text=True, timeout=60)
        return r, os.path.exists(self.mark)


# --- доска (как было) ---
e = Env()
r, ran = e.run()
check("нет ответов — sync.sh не запущен", r.returncode == 0 and not ran, r.stderr)
e.board("Пока держать")
check("доска: «пока держать» — не запускает", not e.run()[1])
e.board("Отправить на другие Mac", tid="metis-0001")
check("доска: ответ по другой задаче — не запускает", not e.run()[1])
e.board("Откатить правку", t=T0 - 50)
r, ran = e.run()
check("доска: «откатить» по своей задаче — запускает", r.returncode == 0 and ran and "применён" in r.stdout, r.stdout)

# --- окно вопросов Зевса (metis-0209) ---
e = Env()
e.window("Отправить на другие Mac")
r, ran = e.run()
check("окно вопросов: «отправить» — запускает sync.sh", r.returncode == 0 and ran, r.stdout + r.stderr)

e = Env(held=".sync-incoming")
e.window("Откатить на всех Mac")
check("окно вопросов: «откатить на всех Mac» по .sync-incoming — запускает", e.run()[1])

e = Env()
e.window("Отправить")
check("окно вопросов: короткое «Отправить» (SYNC_ACT) — запускает", e.run()[1])

e = Env()
e.window("Откатить правку (Recommended)")
check("окно вопросов: «(Recommended)» в конце не мешает", e.run()[1])

e = Env()
e.window("Пока держать")
check("окно вопросов: «пока держать» — не запускает", not e.run()[1])

e = Env()
e.window("Отправить на другие Mac", tid="metis-0001")
check("окно вопросов: вопрос по другой задаче — не запускает", not e.run()[1])

e = Env()
e.window("Отправить на другие Mac", mark="")
check("запись без пометки «окно вопросов» (ввод владельца, не выбор) — не запускает", not e.run()[1])

e = Env()
e.window("Отправить на другие Mac", q="что с [{id}]? отправляй")
check("id внутри вопроса, а не в его начале, — не запускает", not e.run()[1])

e = Env()
e.window("Отправить на другие Mac", t=T0 - 8 * 86400)
check("ответ в окне старше 7 дней — не запускает", not e.run()[1])

# --- два журнала: берётся более поздний ответ ---
e = Env()
e.board("Отправить на другие Mac", t=T0 - 500)
e.window("Пока держать", t=T0 - 100)
check("доска «отправить» раньше, окно «пока держать» позже — не запускает", not e.run()[1])

e = Env()
e.window("Пока держать", t=T0 - 500)
e.board("Откатить правку", t=T0 - 100)
check("окно «пока держать» раньше, доска «откатить» позже — запускает", e.run()[1])

print(f"\n{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
