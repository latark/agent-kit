#!/usr/bin/env python3
"""pantheon check ловит расхождения доски (metis-0441): статус задачи против PR, отвеченный вопрос в «От меня нужно»,
обработанная записка во «Входящих». Чистая доска — без сообщений.

Запуск: python3 -I plugins/pantheon/tests/test_board_drift.py  (код выхода 0 — все прошли)
Всё во временных папках: HOME, PANTHEON_HOME, PANTHEON_STATE, PANTHEON_VIEW подменены; задачи заводит `pantheon task new`.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="board-drift-"))
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
results = []
DIR = "metis-pantheon"


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


class Env:
    def __init__(self, tag):
        self.home = os.path.join(ROOT, tag, "home")
        self.pan = os.path.join(ROOT, tag, "pantheon")
        self.state = os.path.join(ROOT, tag, "state")
        for d in (self.home, os.path.join(self.pan, "directions", DIR, "tasks"), os.path.join(self.pan, "inbox", "tasks"),
                  os.path.join(self.state, "owner-log")):
            os.makedirs(d, exist_ok=True)
        with open(os.path.join(self.pan, "directions.toml"), "w", encoding="utf-8") as fh:
            fh.write(f'[[direction]]\nname = "{DIR}"\nproject = "Пантеон"\n')

    def run(self, args):
        env = {"PATH": os.environ["PATH"], "HOME": self.home, "PANTHEON_HOME": self.pan, "PANTHEON_STATE": self.state,
               "PANTHEON_VIEW": os.path.join(ROOT, "view"), "PANTHEON_NO_NOTIFY": "1", "TMPDIR": ROOT}
        return subprocess.run([sys.executable, "-I", LIB] + args, env=env, capture_output=True, text=True, timeout=120)

    def task(self, title, *extra):
        r = self.run(["task", "new", "--direction", DIR, "--title", title, *extra])
        assert r.returncode == 0, (r.stdout, r.stderr)
        return r.stdout.split()[0]

    def set_status(self, tid, status):
        r = self.run(["task", "set", tid, "status=" + status, "--note", "тест"])
        assert r.returncode == 0, (r.stdout, r.stderr)

    def cache(self, **kw):
        with open(os.path.join(self.state, "autoclose-prs.json"), "w", encoding="utf-8") as fh:
            json.dump({"fetched": 1, **kw}, fh)

    def drift(self):
        r = self.run(["check"])
        return r.returncode, [ln for ln in r.stdout.splitlines() if "· доска ·" in ln]

    def inbox(self, name, text):
        d = os.path.join(self.pan, "directions", DIR, "inbox")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write(text)


# 0. чистая доска: задачи есть, расхождений нет — сообщений нет
e = Env("clean")
t1 = e.task("Просто задача")
e.cache(open_prs={"o/r": []}, merged={"o/r": []})
e.inbox("2026-10-20-новая.md", "# Новая записка\nОт: zeus\n\nтекст\n")
code, lines = e.drift()
check("0. чистая доска: сообщений о расхождении нет", lines == [], lines)

# 1а. PR открыт, а задача todo
e = Env("pr-open")
t = e.task("Правка с PR")
e.cache(open_prs={"o/r": [{"number": 7, "head": "a" * 40, "ids": [t], "closes": [t], "part": False, "core": False}]},
        merged={"o/r": []})
code, lines = e.drift()
check("1а. PR открыт, задача todo: сообщение", len(lines) == 1 and t in lines[0] and "o/r#7" in lines[0], lines)
check("1а. только предупреждение: код выхода check не меняется", code == 0, code)
e.set_status(t, "review")
check("1а. задача в review: расхождения нет", e.drift()[1] == [], e.drift()[1])

e.set_status(t, "done")
check("1а. PR открыт, задача done: сообщение", len(e.drift()[1]) == 1, e.drift()[1])

# 1б. PR слит, а задача doing
e = Env("pr-merged")
t = e.task("Правка слита", "--status", "doing")
merged = {"number": 9, "headRefName": f"feat/{t}", "body": "", "mergedAt": "2999-01-01T00:00:00Z", "oid": "b" * 40}
e.cache(open_prs={"o/r": []}, merged={"o/r": [merged]})
# слияние «в будущем» после updated задачи: расхождение
code, lines = e.drift()
check("1б. PR слит, задача doing: сообщение", len(lines) == 1 and t in lines[0] and "o/r#9" in lines[0], lines)
e.set_status(t, "done")
check("1б. задача done: расхождения нет", e.drift()[1] == [], e.drift()[1])

# 2. вопрос отвечен (окно вопросов у Зевса), а задача всё ещё waiting
e = Env("answered")
t = e.task("Вопрос владельцу", "--status", "waiting", "--waiting-on", "human", "--question", "Брать?", "--why", "нужно",
           "--option", "А — да", "--option", "Б — нет", "--recommend", "А — проще", "--if-no-answer", "ждём")
code, lines = e.drift()
check("2. вопрос без ответа: расхождения нет", lines == [], lines)
with open(os.path.join(e.state, "owner-log", "zeus.md"), "w", encoding="utf-8") as fh:
    fh.write(f"## 2999-01-01 10:00:00 · окно вопросов\nвопрос: [{t}] Брать?\nответ: А — да\n")
code, lines = e.drift()
check("2. ответ в журнале, задача waiting: сообщение", len(lines) == 1 and t in lines[0] and "ответил" in lines[0], lines)
with open(os.path.join(e.state, "owner-log", "zeus.md"), "w", encoding="utf-8") as fh:
    fh.write(f"## 2999-01-01 10:00:00 · окно вопросов\nвопрос: [{t}-other] Брать?\nответ: А — да\n")
check("2. ответ на чужой вопрос — не ответ", e.drift()[1] == [], e.drift()[1])

with open(os.path.join(e.state, "owner-log", "zeus.md"), "w", encoding="utf-8") as fh:
    fh.write(f"## 2000-01-01 10:00:00 · окно вопросов\nвопрос: [{t}] Брать?\nответ: А — да\n")
check("2. ответ старше вопроса (до создания задачи) — не ответ", e.drift()[1] == [], e.drift()[1])

# 3. записка обработана (есть задача с тем же заголовком), а лежит во «Входящих»
e = Env("inbox")
e.inbox("2026-10-20-взята.md", "# Взятая записка\nОт: zeus\n\nтекст\n")
code, lines = e.drift()
check("3. записка не обработана: расхождения нет", lines == [], lines)
t = e.task("Взятая записка")
code, lines = e.drift()
check("3. задача с заголовком записки есть: сообщение", len(lines) == 1 and "2026-10-20-взята.md" in lines[0] and t in lines[0],
      lines)

sys.exit(0 if all(results) else 1)
