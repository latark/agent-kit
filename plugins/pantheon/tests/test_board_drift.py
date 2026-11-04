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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

ROOT = os.path.realpath(tempfile.mkdtemp(prefix="board-drift-"))
atexit.register(shutil.rmtree, ROOT, True)
LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "pantheon.py")
RUN_PY = os.path.join(os.path.dirname(LIB), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
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
        return subprocess.run([PY311, "-I", RUN_PY] + args, env=env, capture_output=True, text=True, timeout=120)

    def task(self, title, *extra):
        r = self.run(["task", "new", "--direction", DIR, "--title", title, "--text", "тело задачи", *extra])
        assert r.returncode == 0, (r.stdout, r.stderr)
        return r.stdout.split()[0]

    def set_status(self, tid, status):
        r = self.run(["task", "set", tid, "status=" + status, "--note", "тест"] + (["--force", "тест"] if status == "done" else []))
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

# 2б. задача ждёт агента (waiting_on не human), поле question осталось: это не «От меня нужно» (tasks.py, «Нужен ответ»)
for who in ("zeus", "metis-pantheon"):
    e = Env("answered-" + who)
    t = e.task("Вопрос ушёл к агенту", "--status", "waiting", "--waiting-on", "human", "--question", "Брать?",
               "--why", "нужно", "--option", "А — да", "--option", "Б — нет", "--recommend", "А — проще",
               "--if-no-answer", "ждём")
    r = e.run(["task", "set", t, "waiting_on=" + who, "--note", "тест"])
    assert r.returncode == 0, (r.stdout, r.stderr)
    with open(os.path.join(e.state, "owner-log", "zeus.md"), "w", encoding="utf-8") as fh:
        fh.write(f"## 2999-01-01 10:00:00 · окно вопросов\nвопрос: [{t}] Брать?\nответ: А — да\n")
    check(f"2б. waiting_on {who} с question и ответом: «От меня нужно» нет", e.drift()[1] == [], e.drift()[1])

# 3. записка обработана (есть задача с тем же заголовком), а лежит во «Входящих»
e = Env("inbox")
e.inbox("2026-10-20-взята.md", "# Взятая записка\nОт: zeus\n\nтекст\n")
code, lines = e.drift()
check("3. записка не обработана: расхождения нет", lines == [], lines)
t = e.task("Взятая записка")
code, lines = e.drift()
check("3. задача с заголовком записки есть: сообщение", len(lines) == 1 and "2026-10-20-взята.md" in lines[0] and t in lines[0],
      lines)


# 4. PR только упоминает задачу (ids, но не closes) и PR «часть» — задачу не закрывают, предупреждения нет (как review_pr)
e = Env("pr-mention")
t = e.task("Упомянутая в PR")
e.cache(open_prs={"o/r": [{"number": 8, "head": "a" * 40, "ids": [t], "closes": [], "part": False, "core": False},
                          {"number": 10, "head": "c" * 40, "ids": [t], "closes": [t], "part": True, "core": False}]},
        merged={"o/r": []})
check("4. PR только упоминает задачу / PR part=True: предупреждения нет", e.drift()[1] == [], e.drift()[1])
e.cache(open_prs={"o/r": [{"number": 8, "head": "a" * 40, "ids": [t], "closes": [t], "part": False, "core": False}]},
        merged={"o/r": []})
check("4. тот же PR с closes: предупреждение есть", len(e.drift()[1]) == 1, e.drift()[1])

# 4б. слитый PR «часть» задачу не закрывает; слияние раньше правки задачи — не расхождение
e = Env("pr-merged-part")
t = e.task("Слита частью", "--status", "doing")
e.cache(open_prs={"o/r": []}, merged={"o/r": [{"number": 11, "headRefName": f"feat/{t}", "body": "Часть " + t,
                                              "mergedAt": "2999-01-01T00:00:00Z", "oid": "d" * 40}]})
check("4б. слитый PR part: предупреждения нет", e.drift()[1] == [], e.drift()[1])
e.cache(open_prs={"o/r": []}, merged={"o/r": [{"number": 12, "headRefName": f"feat/{t}", "body": "",
                                              "mergedAt": "2000-01-01T00:00:00Z", "oid": "d" * 40}]})
check("4б. задача обновлена после слияния: предупреждения нет", e.drift()[1] == [], e.drift()[1])
e.cache(open_prs={"o/r": []}, merged={"o/r": [{"number": 13, "headRefName": f"feat/{t}", "body": "",
                                              "mergedAt": "2999-01-01T00:00:00Z", "oid": "d" * 40}]})
check("4б. контроль: слитый не part, задача старше слияния — предупреждение", len(e.drift()[1]) == 1, e.drift()[1])

# 4в. слитый PR и открытый PR закрывают одну задачу: «уже слит» не выходит (tid not in open_ids)
e = Env("pr-merged-and-open")
t = e.task("Закрывает и слитый, и открытый", "--status", "review")
e.cache(open_prs={"o/r": [{"number": 20, "head": "e" * 40, "ids": [t], "closes": [t], "part": False, "core": False}]},
        merged={"o/r": [{"number": 19, "headRefName": f"feat/{t}", "body": "", "mergedAt": "2999-01-01T00:00:00Z",
                         "oid": "f" * 40}]})
check("4в. есть открытый PR на задачу: «уже слит» нет", e.drift()[1] == [], e.drift()[1])
e.cache(open_prs={"o/r": []}, merged={"o/r": [{"number": 19, "headRefName": f"feat/{t}", "body": "",
                                              "mergedAt": "2999-01-01T00:00:00Z", "oid": "f" * 40}]})
check("4в. контроль: открытого PR нет — «уже слит»", len(e.drift()[1]) == 1 and "уже слит" in e.drift()[1][0], e.drift()[1])

# 5. галочка на доске (owner-log/board.jsonl)
e = Env("board")
t = e.task("Вопрос на доске", "--status", "waiting", "--waiting-on", "human", "--question", "Брать?", "--why", "нужно",
           "--option", "А — да", "--option", "Б — нет", "--recommend", "А — проще", "--if-no-answer", "ждём")


def board(*recs):
    with open(os.path.join(e.state, "owner-log", "board.jsonl"), "w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps({"kind": "answer", "time": "2999-01-01T10:00:00", "question": "Брать?", "answer": "А — да",
                                 **r}, ensure_ascii=False) + "\n")


board({"id": t})
lines = e.drift()[1]
check("5. галочка со своим id: сообщение", len(lines) == 1 and t in lines[0] and "ответил" in lines[0], lines)
board({"id": t + "-other"})
check("5. галочка на чужой id — не ответ", e.drift()[1] == [], e.drift()[1])
board({"id": t, "time": "2000-01-01T10:00:00"})
check("5. галочка старше вопроса — не ответ", e.drift()[1] == [], e.drift()[1])
board({"id": t, "question": "Брать %% да?"})
check("5. %% в вопросе — не ответ", e.drift()[1] == [], e.drift()[1])
board({"id": t, "question": "Брать <b>?"})
check("5. < в вопросе — не ответ", e.drift()[1] == [], e.drift()[1])
board({"id": t, "kind": "view"})
check("5. запись не kind=answer — не ответ", e.drift()[1] == [], e.drift()[1])
with open(os.path.join(e.state, "owner-log", "zeus.md"), "w", encoding="utf-8") as fh:
    fh.write(f"## 2999-01-01 10:00:00 · другое окно\nвопрос: [{t}] Брать?\nответ: А — да\n")
check("5. запись zeus.md не из окна вопросов — не ответ", e.drift()[1] == [], e.drift()[1])

# 6. записка: копия в inbox/done (в том числе «отклонено-»)
e = Env("inbox-done")
e.inbox("2026-10-20-старая.md", "# Старая записка\nОт: zeus\n\nтекст\n")
check("6. нет копии в done: расхождения нет", e.drift()[1] == [], e.drift()[1])
d = os.path.join(e.pan, "directions", DIR, "inbox", "done")
os.makedirs(d, exist_ok=True)
with open(os.path.join(d, "2026-10-20-старая.md"), "w", encoding="utf-8") as fh:
    fh.write("# Старая записка\n")
lines = e.drift()[1]
check("6. копия в inbox/done: сообщение", len(lines) == 1 and "inbox/done" in lines[0], lines)
os.rename(os.path.join(d, "2026-10-20-старая.md"), os.path.join(d, "отклонено-2026-10-20-старая.md"))
check("6. копия «отклонено-» в inbox/done: сообщение", len(e.drift()[1]) == 1, e.drift()[1])

# 7. check --quiet (плановый проход) строк «доска» не печатает, код выхода тот же
e = Env("quiet")
t = e.task("Тихая")
e.cache(open_prs={"o/r": [{"number": 7, "head": "a" * 40, "ids": [t], "closes": [t], "part": False, "core": False}]},
        merged={"o/r": []})
check("7. контроль: полный проход видит расхождение", len(e.drift()[1]) == 1, e.drift()[1])
r = e.run(["check", "--quiet"])
check("7. --quiet: строк «доска» нет, код 0", r.returncode == 0 and "доска" not in r.stdout, (r.returncode, r.stdout))

# 8. кэш верного JSON, но неверной формы: без трассировки, код 0
bad = [{"open_prs": {"o/r": [{"number": 1, "ids": 5, "closes": 5, "part": False}]}, "merged": {"o/r": []}},
       {"open_prs": {"o/r": [{"number": 1, "ids": [["x"]], "closes": [["x"], 5, None], "part": False}]}, "merged": {}},
       {"open_prs": {"o/r": []}, "merged": {"o/r": [{"number": 2, "headRefName": 5, "body": "", "mergedAt": "x"}]}},
       {"open_prs": {"o/r": []}, "merged": {"o/r": [{"number": 2, "headRefName": "a", "body": 5, "mergedAt": "x"}]}},
       {"open_prs": {"o/r": [5, "x", None]}, "merged": {"o/r": [[], 7]}}, {"open_prs": 5, "merged": [1]}]
e = Env("badshape")
e.task("Задача при кривом кэше", "--status", "doing")
for i, c in enumerate(bad):
    e.cache(**c)
    r = e.run(["check"])
    check(f"8.{i} кэш неверной формы: без трассировки, код 0", r.returncode == 0 and "Traceback" not in r.stderr
          and "· доска ·" not in r.stdout, (r.returncode, r.stderr[-300:], r.stdout[-200:]))

# 9. PR пачки (ветка batch/<id>) закрыл задачу с другим parent (metis-0799): предупреждение, parent не правится
e = Env("batch-outside")
s1 = e.task("Пачка: первая", "--type", "story", "--status", "doing", "--done-when", "всё слито")
s2 = e.task("Пачка: вторая", "--type", "story", "--done-when", "всё слито")
own = e.task("Своя задача", "--parent", s1, "--mode", "single")
other = e.task("Задача другой пачки", "--parent", s2, "--mode", "single")
loose = e.task("Задача без пачки")
pr = {"number": 294, "headRefName": f"batch/{s1}", "body": f"Closes {own}, {other} и {loose}",
      "mergedAt": "2000-01-01T00:00:00Z", "oid": "a" * 40, "cross": False}
e.cache(open_prs={"o/r": []}, merged={"o/r": [pr]})
lines = e.drift()[1]
check("9. PR пачки закрыл задачи другой пачки и без пачки: по строке на каждую, своя — нет",
      len(lines) == 2 and any(other in x and f"parent — {s2}" in x for x in lines)
      and any(loose in x and "parent — пусто" in x for x in lines) and not any(f"доска · {own}:" in x for x in lines)
      and all("o/r#294" in x for x in lines), lines)
with open(os.path.join(e.pan, "directions", DIR, "tasks", f"{other}.md"), encoding="utf-8") as fh:
    check("9. parent чужой задачи не тронут", f"parent: {s2}" in fh.read())
e.cache(open_prs={"o/r": [{"number": 300, "head": "b" * 40, "branch": f"batch/{s1}", "ids": [other], "closes": [other],
                           "part": False, "core": False, "cross": False}]}, merged={"o/r": []})
lines = e.drift()[1]
check("9. открытый PR пачки тоже: строка о задаче вне состава", any(other in x and "o/r#300" in x for x in lines), lines)
e.cache(open_prs={"o/r": []}, merged={"o/r": [dict(pr, headRefName=f"feat/{s1}")]})
check("9. ветка не batch/<id> — не PR пачки: строк о составе нет", not any("PR пачки" in x for x in e.drift()[1]), e.drift()[1])
e.cache(open_prs={"o/r": []}, merged={"o/r": [dict(pr, body=pr["body"] + "\nчасть")]})
check("9. PR пачки «часть» — не закрывает: строк нет", not any("PR пачки" in x for x in e.drift()[1]), e.drift()[1])
for fork in ({"cross": True}, {"cross": None}):
    row = {k: v for k, v in dict(pr, **fork).items() if v is not None}
    e.cache(open_prs={"o/r": []}, merged={"o/r": [row]})
    check(f"9. PR из форка или строка кэша без cross ({fork}) — не PR пачки: строк нет",
          not any("PR пачки" in x for x in e.drift()[1]), e.drift()[1])
e.set_status(s1, "done")
e.cache(open_prs={"o/r": []}, merged={"o/r": [pr]})
check("9. пачка закрыта — история не шумит", not any("PR пачки" in x for x in e.drift()[1]), e.drift()[1])

sys.exit(0 if all(results) else 1)
