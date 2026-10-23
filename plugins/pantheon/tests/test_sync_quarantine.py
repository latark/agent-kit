#!/usr/bin/env python3
"""Тест `pantheon sync-answers` (metis-0209, SEC-15): ответ владельца по карантину ~/.claude запускает sync.sh.

Ответ — галочка на доске (owner-log/board.jsonl) или выбор в окне вопросов Зевса (owner-log/zeus.md, пометка
«· окно вопросов», вопрос «[<id>] …», строка «ответ: …», не старше 7 дней); из двух берётся более поздний — как в
настоящем sync.sh (owner_answer). Здесь sync.sh — заглушка, пишущая отметку: проверяется «пора ли запускать» и снятие вопроса с карточки (при коде 0 и ответе из SYNC_ACT).
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

    def __init__(self, task="metis-0099", held=".sync-held", applies=True):
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
            # applies: заглушка снимает держание, как настоящий sync.sh; иначе выходит с 0, ничего не сняв
            rm = f'rm -f "{self.claude}/.sync-held" "{self.claude}/.sync-incoming"\n' if applies else ""
            fh.write(f'#!/bin/sh\necho x >> "{self.mark}"\n{rm}')
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

# --- вопрос карточки снимается после ответа (metis-0226) ---
def card_question(e, tid):
    import re
    for dp, _, fs in os.walk(os.path.join(e.pan, "directions")):
        for f in fs:
            if f.startswith(tid) and f.endswith(".md"):
                txt = open(os.path.join(dp, f), encoding="utf-8").read()
                m = re.search(r"^question: (.*)$", txt, re.M)
                return m.group(1) if m else None
    return "нет файла"


def with_card(held=".sync-held", applies=True):
    e = Env(held=held, applies=applies)
    os.makedirs(os.path.join(e.pan, "directions", "metis-pantheon", "tasks"))
    env = {"PATH": os.environ["PATH"], "HOME": e.home, "PANTHEON_HOME": e.pan, "PANTHEON_STATE": e.state,
           "PANTHEON_NOW": str(T0), "PANTHEON_HOST": "mac-a", "PANTHEON_NO_NOTIFY": "1", "TMPDIR": ROOT}
    r = subprocess.run([PY311, "-I", LIB, "task", "new", "--direction", "metis-pantheon", "--project", "Пантеон",
                        "--title", "Правки ~/.claude", "--status", "waiting", "--waiting-on", "human", "--priority", "1",
                        "--next", "выбрать", "--question", "Отправить правки?", "--option", "Отправить",
                        "--option", "Пока держать"], env=env, capture_output=True, text=True, timeout=60)
    import re
    m = re.search(r"[a-z]+-\d{4}", r.stdout)
    check("карточка создана", r.returncode == 0 and m, r.stdout + r.stderr)
    e.task = m.group(0) if m else "x-0000"
    with open(os.path.join(e.claude, held), "w") as fh:
        fh.write(f"hash=abc\ntask={e.task}\nfiles=1\n")
    return e


e = with_card()
e.window("Отправить")
check("карточка: до sync-answers вопрос есть", card_question(e, e.task) not in (None, "нет файла"), card_question(e, e.task))
r, ran = e.run()
check("карточка: ответ «Отправить» в окне — sync.sh запущен, вопрос снят", ran and card_question(e, e.task) is None,
      f"{card_question(e, e.task)} {r.stdout}{r.stderr}")

e = with_card()
e.window("Пока держать")
e.run()
check("карточка: «Пока держать» — вопрос остаётся", card_question(e, e.task) not in (None, "нет файла"))

e = with_card()
e.board("Отправить")
e.run()
check("карточка: ответ галочкой на доске — вопрос снят", card_question(e, e.task) is None)


# два держания: «Отправить» по .sync-held снимает вопрос, «Пока держать» по .sync-incoming — нет
e = with_card()
first = e.task
r2 = subprocess.run([PY311, "-I", LIB, "task", "new", "--direction", "metis-pantheon", "--project", "Пантеон",
                     "--title", "Чужие правки", "--status", "waiting", "--waiting-on", "human", "--priority", "1",
                     "--next", "выбрать", "--question", "Откатить?", "--option", "Пока держать"],
                    env={"PATH": os.environ["PATH"], "HOME": e.home, "PANTHEON_HOME": e.pan, "PANTHEON_STATE": e.state,
                         "PANTHEON_NOW": str(T0), "PANTHEON_HOST": "mac-a", "PANTHEON_NO_NOTIFY": "1", "TMPDIR": ROOT},
                    capture_output=True, text=True, timeout=60)
import re as _re
second = _re.search(r"[a-z]+-\d{4}", r2.stdout).group(0)
with open(os.path.join(e.claude, ".sync-incoming"), "w") as fh:
    fh.write(f"task={second}\nfrom=a\nto=b\n")
e.window("Отправить", tid=first)
e.window("Пока держать", tid=second)
e.run()
check("два держания: «Отправить» — вопрос снят", card_question(e, first) is None, card_question(e, first))
check("два держания: «Пока держать» — вопрос остался", card_question(e, second) not in (None, "нет файла"),
      card_question(e, second))

# sync.sh вернул не 0 — вопрос не снимается
e = with_card()
with open(os.path.join(e.claude, "sync.sh"), "w") as fh:
    fh.write(f'#!/bin/sh\necho x >> "{e.mark}"\nexit 3\n')
e.window("Отправить")
r, ran = e.run()
check("sync.sh код 3 — вопрос остаётся", ran and card_question(e, e.task) not in (None, "нет файла"), r.stdout + r.stderr)

# sync.sh код 0, но держание осталось (лок занят, нет папки, нет репозитория) — вопрос остаётся
for held in (".sync-held", ".sync-incoming"):
    e = with_card(held=held, applies=False)
    e.window("Отправить")
    r, ran = e.run()
    check(f"sync.sh код 0, {held} осталось — вопрос остаётся, строка в stdout",
          ran and card_question(e, e.task) not in (None, "нет файла")
          and f"sync-answers: {e.task} — sync.sh не применил, вопрос остаётся" in r.stdout, r.stdout + r.stderr)
# sync.sh код 0 и держание снято — вопрос снят
e = with_card(applies=True)
e.window("Отправить")
r, ran = e.run()
check("sync.sh код 0, держание снято — вопрос снят", ran and card_question(e, e.task) is None, r.stdout + r.stderr)

# metis-0364: держание не прочитано или без task= — остаётся; «применён» печатается только после проверки
def mixed(after):
    """.sync-held (задача A) sync.sh снимает, .sync-incoming (задача B) после него — по сценарию after."""
    e = with_card()
    a = e.task
    env = {"PATH": os.environ["PATH"], "HOME": e.home, "PANTHEON_HOME": e.pan, "PANTHEON_STATE": e.state,
           "PANTHEON_NOW": str(T0), "PANTHEON_HOST": "mac-a", "PANTHEON_NO_NOTIFY": "1", "TMPDIR": ROOT}
    r2 = subprocess.run([PY311, "-I", LIB, "task", "new", "--direction", "metis-pantheon", "--project", "Пантеон",
                         "--title", "Чужие правки", "--status", "waiting", "--waiting-on", "human", "--priority", "1",
                         "--next", "выбрать", "--question", "Откатить?", "--option", "Откатить правку"],
                        env=env, capture_output=True, text=True, timeout=60)
    b = _re.search(r"[a-z]+-\d{4}", r2.stdout).group(0)
    inc = os.path.join(e.claude, ".sync-incoming")
    with open(inc, "w") as fh:
        fh.write(f"task={b}\nfrom=a\nto=b\n")
    with open(os.path.join(e.claude, "sync.sh"), "w") as fh:
        fh.write(f'#!/bin/sh\necho x >> "{e.mark}"\nrm -f "{e.claude}/.sync-held" "{inc}"\n{after.format(inc=inc)}\n')
    e.window("Отправить", tid=a)
    e.window("Откатить правку", tid=b)
    r, ran = e.run()
    return e, a, b, r, ran


for label, after, why in (("нечитаемое (каталог)", 'mkdir "{inc}"', ".sync-incoming не прочитан"),
                          ("без task=", 'printf "from=a\\nto=b\\n" > "{inc}"', ".sync-incoming без task=")):
    e, a, b, r, ran = mixed(after)
    out = r.stdout + r.stderr
    check(f"два держания, второе {label}: первое применено, вопрос снят", ran and card_question(e, a) is None, out)
    check(f"два держания, второе {label}: вопрос второго остаётся, причина в выводе",
          card_question(e, b) not in (None, "нет файла") and f"sync-answers: {b} — sync.sh не применил" in r.stdout
          and why in r.stdout, out)
    check(f"два держания, второе {label}: «применён» только по первому",
          f"ответ по {a} применён" in r.stdout and f"ответ по {b} применён" not in r.stdout, out)

# одно держание, после sync.sh файл без task= — «применён» не печатается, вопрос остаётся
e = with_card(applies=False)
with open(os.path.join(e.claude, "sync.sh"), "w") as fh:
    fh.write(f'#!/bin/sh\necho x >> "{e.mark}"\nprintf "hash=abc\\n" > "{e.claude}/.sync-held"\n')
e.window("Отправить")
r, ran = e.run()
check("одно держание, после sync.sh без task= — не «применён», вопрос остаётся, причина в выводе",
      ran and "применён" not in r.stdout and card_question(e, e.task) not in (None, "нет файла")
      and ".sync-held без task=" in r.stdout, r.stdout + r.stderr)

# metis-0364 круг 2: sync.sh заменил держание задачи A держанием задачи C — по A нет «применён», вопрос остаётся
e = with_card(applies=False)
with open(os.path.join(e.claude, "sync.sh"), "w") as fh:
    fh.write(f'#!/bin/sh\necho x >> "{e.mark}"\n'
             f'printf "hash=def\\ntask=metis-0777\\nfiles=1\\n" > "{e.claude}/.sync-held"\n')
e.window("Отправить")
r, ran = e.run()
check("держание A заменено держанием C — не «применён», вопрос A остаётся, причина в выводе",
      ran and f"ответ по {e.task} применён" not in r.stdout and card_question(e, e.task) not in (None, "нет файла")
      and f"{e.task} — sync.sh не применил" in r.stdout and "держание заменено (task=metis-0777)" in r.stdout,
      r.stdout + r.stderr)

# владелец неизвестен: .sync-incoming появился во время sync.sh без task=, .sync-held задачи A снят — держание за всеми
e = with_card(applies=False)
with open(os.path.join(e.claude, "sync.sh"), "w") as fh:
    fh.write(f'#!/bin/sh\necho x >> "{e.mark}"\nrm -f "{e.claude}/.sync-held"\n'
             f'printf "from=a\\nto=b\\n" > "{e.claude}/.sync-incoming"\n')
e.window("Отправить")
r, ran = e.run()
check("владелец держания неизвестен (.sync-incoming без task= появился во время sync.sh) — не «применён», вопрос A остаётся",
      ran and f"ответ по {e.task} применён" not in r.stdout and card_question(e, e.task) not in (None, "нет файла")
      and ".sync-incoming без task=" in r.stdout, r.stdout + r.stderr)

print(f"\n{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
