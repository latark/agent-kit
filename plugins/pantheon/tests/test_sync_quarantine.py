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
    r = subprocess.run([PY311, "-I", LIB, "task", "new", "--text", "тест", "--direction", "metis-pantheon", "--project", "Пантеон",
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
r2 = subprocess.run([PY311, "-I", LIB, "task", "new", "--text", "тест", "--direction", "metis-pantheon", "--project", "Пантеон",
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
    r2 = subprocess.run([PY311, "-I", LIB, "task", "new", "--text", "тест", "--direction", "metis-pantheon", "--project", "Пантеон",
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

# metis-0364 круг 3: у .sync-incoming смена task= — ответ по прежней задаче применён (sync.sh удалил файл, incoming_check
# в том же запуске записал новый вопрос D); «заменено» — правило только для .sync-held
e = with_card(held=".sync-incoming", applies=False)
with open(os.path.join(e.claude, "sync.sh"), "w") as fh:
    fh.write(f'#!/bin/sh\necho x >> "{e.mark}"\nrm -f "{e.claude}/.sync-incoming"\n'
             f'printf "task=metis-0778\\nfrom=a\\nto=b\\n" > "{e.claude}/.sync-incoming"\n')
e.window("Отправить")
r, ran = e.run()
check("incoming B заменён incoming D — «применён», вопрос B снят, «заменено» не печатается",
      ran and f"ответ по {e.task} применён" in r.stdout and card_question(e, e.task) is None
      and "заменено" not in r.stdout + r.stderr, r.stdout + r.stderr)

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

# --- слитый выпуск проходит карантин без карточки (metis-0209, вариант А) -------------------------------------------
# config-check.py решает, что идёт в карантин: файл, побайтно равный файлу plugins/pantheon|guard в вершине
# refs/remotes/origin/main клона agent-kit, флагов не получает, если вершину или её родителя слил владелец
# (merge.jsonl / merge-approve.log). Клон — мелкий, как у маркетплейса: головы PR в нём нет.
CHECK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "config-check.py")
HOOK = "#!/usr/bin/env python3\nprint('guard hook')\n"
HOOK2 = "#!/usr/bin/env python3\nprint('guard hook v2')\n"
KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
GIT_ENV = {"PATH": os.environ["PATH"], "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def run_git(d, *a, ok=True):
    r = subprocess.run(["git", "-C", d, *a], env=GIT_ENV, capture_output=True, text=True)
    assert not ok or r.returncode == 0, (a, r.stderr)
    return r.stdout.strip() if ok else r.returncode


MANIFEST = "plugins/guard/.claude-plugin/plugin.json"


def manifest(ver, desc="guard"):
    return '{\n  "name": "guard",\n  "version": "%s",\n  "description": "%s"\n}\n' % (ver, desc)


def put(d, rel, text):
    os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
    with open(os.path.join(d, rel), "w", newline="") as fh:
        fh.write(text)


class Rel:
    """Временный HOME: «origin» agent-kit, клон его main (по умолчанию --depth 1, как у маркетплейса), журналы
    владельца, репозиторий ~/.claude с правкой name в индексе.

    Выпуск — голова PR (ветка pr) с файлом rel_path. how: "merge" — в main merge-коммит со слитой головой вторым
    родителем (как `gh pr merge --merge`), "ff" — голова сама становится вершиной main, "none" — PR в main не попал.
    logged: какой SHA записан в журнал — "head" (голова PR) или "other" (чужой). later — содержимое второго выпуска,
    слитого после первого (тогда в журнале обе головы)."""
    n = 0

    def __init__(self, log="merge.jsonl", how="merge", logged="head", name="hooks/gate.py", content=HOOK,
                 release=HOOK, rel_path="plugins/guard/hooks/gate.py", event="merged", repo="latark/agent-kit",
                 later=None, shallow=True, bot=None, bot_merge=False, bot_exec=()):
        Rel.n += 1
        self.home = os.path.join(ROOT, f"r{Rel.n}")
        self.origin = origin = os.path.join(self.home, "origin")
        self.clone = os.path.join(self.home, ".claude", "plugins", "marketplaces", "agent-kit")
        self.cfg = os.path.join(self.home, ".claude")
        os.makedirs(origin)
        run_git(origin, "init", "-q", "-b", "main")
        put(origin, "README.md", "agent-kit\n")
        put(origin, MANIFEST, manifest("0.6.0"))
        run_git(origin, "add", "-A")
        run_git(origin, "commit", "-q", "-m", "root")
        heads = []
        for i, text in enumerate([release] + ([later] if later is not None else [])):
            run_git(origin, "checkout", "-q", "-b", f"pr{i}")
            put(origin, rel_path, text)
            run_git(origin, "add", "-A")
            run_git(origin, "commit", "-q", "-m", f"release {i}")
            heads.append(run_git(origin, "rev-parse", "HEAD"))
            run_git(origin, "checkout", "-q", "main")
            if how == "merge":
                run_git(origin, "merge", "-q", "--no-ff", "-m", f"Merge pull request #{7 + i}", f"pr{i}")
            elif how in ("ff", "ff+direct"):
                run_git(origin, "merge", "-q", "--ff-only", f"pr{i}")
            else:
                run_git(origin, "commit", "-q", "--allow-empty", "-m", "other")
        if how == "ff+direct":  # прямой коммит поверх слитой головы: первый родитель слит, второго нет
            run_git(origin, "commit", "-q", "--allow-empty", "-m", "direct")
        self.release = None
        if bot is not None:  # коммит выпуска workflow release (metis-0512) поверх main: один родитель, файлы bot
            if bot_merge:  # тот же коммит веткой, слитой в main merge-коммитом не владельцем — у вершины два родителя
                run_git(origin, "checkout", "-q", "-b", "botpr")
            for rel, text in bot.items():
                put(origin, rel, text)
                if rel in bot_exec:
                    os.chmod(os.path.join(origin, rel), 0o755)
            run_git(origin, "add", "-A")
            run_git(origin, "-c", "user.name=github-actions[bot]", "commit", "-q", "-m", "выпуск: guard 0.6.1")
            if bot_merge:
                run_git(origin, "checkout", "-q", "main")
                run_git(origin, "merge", "-q", "--no-ff", "-m", "Merge botpr", "botpr")
            self.release = run_git(origin, "rev-parse", "HEAD")
        self.head = heads[-1]
        os.makedirs(os.path.dirname(self.clone))
        run_git(self.home, "clone", "-q", *(["--depth", "1"] if shallow else []), "file://" + origin, self.clone)
        run_git(self.cfg, "init", "-q")
        put(self.cfg, "keep.txt", "x\n")
        run_git(self.cfg, "add", "keep.txt")
        run_git(self.cfg, "commit", "-q", "-m", "init")
        state = os.path.join(self.home, ".local", "state", "pantheon")
        os.makedirs(os.path.join(state, "logs"))
        os.makedirs(os.path.join(state, "owner-log"))
        shas = heads if logged == "head" else ["1234567890abcdef1234567890abcdef12345678"]
        if log == "merge.jsonl":
            with open(os.path.join(state, "logs", "merge.jsonl"), "w") as fh:
                for i, sha in enumerate(shas):
                    fh.write(json.dumps({"repo": repo, "pr": 7 + i, "sha": sha, "event": event}) + "\n")
        else:
            with open(os.path.join(state, "owner-log", "merge-approve.log"), "w") as fh:
                for i, sha in enumerate(shas):
                    fh.write(f"2026-10-23T17:00:00+03:00 merge-approve {repo}#{7 + i} {sha}\n")
        put(self.cfg, name, content)
        run_git(self.cfg, "add", name)

    def flags(self, script=CHECK):
        env = {"PATH": os.environ["PATH"], "HOME": self.home}
        r = subprocess.run([sys.executable, "-I", script, "--repo", self.cfg, "--staged"], env=env,
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)["flags"]


r_ok = Rel()
check("мелкий клон: shallow, головы PR в нём нет (старая сверка по истории здесь не работала)",
      run_git(r_ok.clone, "rev-parse", "--is-shallow-repository") == "true"
      and run_git(r_ok.clone, "cat-file", "-e", r_ok.head, ok=False) != 0)
check("слитый выпуск: вершина main — merge-коммит, слитая голова PR вторым родителем — без флагов",
      r_ok.flags() == [], r_ok.flags())
r_ap = Rel(log="approve")
check("слитый выпуск: слияние записано в merge-approve.log — без флагов", r_ap.flags() == [], r_ap.flags())
r_ff = Rel(how="ff")
check("слитый выпуск: перемотка, вершина main — сама голова PR — без флагов", r_ff.flags() == [], r_ff.flags())
r_full = Rel(shallow=False)
check("слитый выпуск: полный клон — без флагов", r_full.flags() == [], r_full.flags())
r_diff = Rel(content=HOOK + " ")
check("слитый выпуск: отличается на байт — флаги как раньше", r_diff.flags() != [], r_diff.flags())
r_nm = Rel(logged="other")
check("слитый выпуск: вершину и её родителей владелец не сливал — флаги", r_nm.flags() != [], r_nm.flags())
r_br = Rel(how="none")
check("слитый выпуск: голова PR в журнале, но в main не попала — флаги", r_br.flags() != [], r_br.flags())
r_tag = Rel(how="none")
run_git(r_tag.clone, "fetch", "-q", "--depth", "1", "origin", "pr0")
run_git(r_tag.clone, "tag", "origin/main", "FETCH_HEAD")
check("слитый выпуск: метка origin/main на голове PR не перекрывает ветку refs/remotes/origin/main — флаги",
      r_tag.flags() != [], r_tag.flags())
r_ev = Rel(event="window")
check("слитый выпуск: событие журнала не merged (window) — флаги", r_ev.flags() != [], r_ev.flags())
r_mf = Rel(event="merge-failed")
check("слитый выпуск: событие журнала merge-failed — флаги", r_mf.flags() != [], r_mf.flags())
r_repo = Rel(repo="evil/other")
check("слитый выпуск: запись журнала про чужой репозиторий — флаги", r_repo.flags() != [], r_repo.flags())
r_repo_ap = Rel(log="approve", repo="evil/other")
check("слитый выпуск: merge-approve.log про чужой репозиторий — флаги", r_repo_ap.flags() != [], r_repo_ap.flags())
r_evil = Rel(repo="evil/agent-kit")
check("слитый выпуск: запись журнала про evil/agent-kit (не latark/agent-kit) — флаги", r_evil.flags() != [], r_evil.flags())
r_evil_ap = Rel(log="approve", repo="evil/agent-kit")
check("слитый выпуск: merge-approve.log про evil/agent-kit — флаги", r_evil_ap.flags() != [], r_evil_ap.flags())
r_dir1 = Rel(how="ff+direct")
check("слитый выпуск: перемотанная слитая голова + прямой коммит поверх (второго родителя нет) — флаги",
      r_dir1.flags() != [], r_dir1.flags())
r_name = Rel(name="hooks/other.py")
check("слитый выпуск: то же содержимое под другим именем — флаги", r_name.flags() != [], r_name.flags())
r_dir = Rel(name="skills/x/hooks/gate.py")
check("слитый выпуск: тот же файл в другой папке (skills/x/hooks/gate.py) — флаги", r_dir.flags() != [], r_dir.flags())
r_tests = Rel(rel_path="plugins/guard/tests/gate.py", name="tests/gate.py")
check("слитый выпуск: файл из tests/ выпуска не доверен — флаги", r_tests.flags() != [], r_tests.flags())
r_key = Rel(content=HOOK + f"# {KEY}\n", release=HOOK + f"# {KEY}\n")
kinds = [f["kind"] for f in r_key.flags()]
check("слитый выпуск: ключ в тексте флаг secret сохраняет, остальные снимает", kinds != []
      and set(kinds) == {"secret"}, kinds)
r_old = Rel(later=HOOK2, shallow=False)
check("слитый выпуск: откат к старому выпуску (не вершина main) — флаги", r_old.flags() != [], r_old.flags())
r_new = Rel(later=HOOK2, content=HOOK2)
check("слитый выпуск: последний из двух выпусков — без флагов", r_new.flags() == [], r_new.flags())
r_del = Rel()
run_git(r_del.cfg, "commit", "-q", "-m", "add")
os.remove(os.path.join(r_del.cfg, "hooks", "gate.py"))
run_git(r_del.cfg, "add", "-A")
check("слитый выпуск: удаление файла — флаги", r_del.flags() != [], r_del.flags())
# коммит выпуска workflow release поверх слитого merge-коммита (metis-0512, argus-b PR #153 Б2): вершина main — коммит
# github-actions[bot] с одним родителем; доверен по содержимому — только строки version и releases.json
RELEASE_OK = {MANIFEST: manifest("0.6.1"), ".claude-plugin/releases.json": '{"v": 1, "plugins": {}}\n'}
r_bot = Rel(bot=RELEASE_OK)
parent = [ln.split()[1] for ln in run_git(r_bot.clone, "cat-file", "-p", "refs/remotes/origin/main").splitlines()
          if ln.startswith("parent ")][0]
check("коммит выпуска: в мелком клоне объекта родителя нет (догружает fetch --depth 2)",
      run_git(r_bot.clone, "cat-file", "-e", parent + "^{commit}", ok=False) != 0)
check("коммит выпуска поверх слитого merge-коммита, мелкий клон — без флагов", r_bot.flags() == [], r_bot.flags())
check("коммит выпуска: ветка origin/main клона после догрузки на месте",
      run_git(r_bot.clone, "rev-parse", "refs/remotes/origin/main") == r_bot.release)
r_bot_full = Rel(bot=RELEASE_OK, shallow=False)
check("коммит выпуска, полный клон — без флагов", r_bot_full.flags() == [], r_bot_full.flags())
r_bot_ff = Rel(bot=RELEASE_OK, how="ff")
check("коммит выпуска поверх перемотанной слитой головы — без флагов", r_bot_ff.flags() == [], r_bot_ff.flags())
r_bot_ap = Rel(bot=RELEASE_OK, log="approve")
check("коммит выпуска, слияние в merge-approve.log — без флагов", r_bot_ap.flags() == [], r_bot_ap.flags())
r_bot_nm = Rel(bot=RELEASE_OK, logged="other")
check("коммит выпуска поверх не слитого владельцем — флаги", r_bot_nm.flags() != [], r_bot_nm.flags())
r_bot_dir = Rel(bot=RELEASE_OK, how="ff+direct")
check("коммит выпуска поверх прямого коммита (слитая голова — его первый родитель) — флаги", r_bot_dir.flags() != [],
      r_bot_dir.flags())
r_bot_file = Rel(bot=dict(RELEASE_OK, **{"plugins/guard/hooks/gate.py": HOOK2}), content=HOOK2)
check("коммит выпуска меняет и файл плагина — флаги на этот файл", r_bot_file.flags() != [], r_bot_file.flags())
r_bot_other = Rel(bot=dict(RELEASE_OK, **{"plugins/guard/hooks/other.py": HOOK2}))
check("коммит выпуска добавляет файл плагина — вершина не доверена, флаги", r_bot_other.flags() != [],
      r_bot_other.flags())
r_bot_key = Rel(bot={MANIFEST: manifest("0.6.1", desc="evil"), ".claude-plugin/releases.json": "{}\n"})
check("коммит выпуска меняет в plugin.json не только version — флаги", r_bot_key.flags() != [], r_bot_key.flags())
r_bot_add = Rel(bot={MANIFEST: manifest("0.6.1"), "plugins/x/.claude-plugin/plugin.json": manifest("0.1.0")})
check("коммит выпуска добавляет plugin.json — флаги", r_bot_add.flags() != [], r_bot_add.flags())
r_bot_x = Rel(bot=RELEASE_OK, bot_exec=(MANIFEST,))
check("коммит выпуска делает plugin.json исполняемым (режим 100755) — флаги", r_bot_x.flags() != [], r_bot_x.flags())
r_bot_mc = Rel(bot=RELEASE_OK, bot_merge=True)
check("только version, но вершина — merge-коммит не слитой владельцем ветки (два родителя) — флаги",
      r_bot_mc.flags() != [], r_bot_mc.flags())
r_bot_net = Rel(bot=RELEASE_OK)
shutil.rmtree(r_bot_net.origin)
check("коммит выпуска, объект родителя не догрузить (origin недоступен) — флаги", r_bot_net.flags() != [],
      r_bot_net.flags())
# мутант «всегда пропускать»: сценарии «отличается на байт» и «не слит» проходят без флагов — значит, тесты выше
# на мутанте красные (их условие `!= []` не выполняется)
mut = os.path.join(ROOT, "config-check-mutant.py")
src = open(CHECK, encoding="utf-8").read()
assert "def is_released(path, data):\n" in src
with open(mut, "w", encoding="utf-8") as fh:
    fh.write(src.replace("def is_released(path, data):\n", "def is_released(path, data):\n    return True\n"))
check("мутант «всегда пропускать»: правка в байт проходит без флагов (тест на неё красный)", r_diff.flags(mut) == [],
      r_diff.flags(mut))
check("мутант «всегда пропускать»: не слитый коммит проходит без флагов (тест красный)", r_nm.flags(mut) == [])

for tag, a, b in (("parents вместо parents[1:]", "parents[1:]", "parents"),
                  ("endswith вместо точного имени", "== OWNER_REPO", '.endswith("/agent-kit")')):
    msrc = src.replace(a, b)
    assert msrc != src, tag
    mp = os.path.join(ROOT, "config-check-mutant2.py")
    with open(mp, "w", encoding="utf-8") as fh:
        fh.write(msrc)
    probe = r_dir1 if "parents" in tag else r_evil
    check(f"мутант «{tag}»: сценарий проходит без флагов (тест красный)", probe.flags(mp) == [], probe.flags(mp))

print(f"\n{sum(results)} из {len(results)} прошли")
sys.exit(0 if all(results) else 1)
