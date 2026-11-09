#!/usr/bin/env python3
"""Задачи без пачки (metis-0940, слово владельца 06.11): (1) `pantheon task new` без --parent печатает подсказку
batch-suggest; (2) `pantheon check` тревожит на открытую задачу без пачки старше суток (созданную с 2026-11-03);
(3) плановый `pantheon batch-suggest run` сам прикрепляет «уверенные» предложения и пишет строку в журнал.
Временные папки, настоящих задач и ~/ai/pantheon тест не трогает.

Запуск: python3 -I plugins/pantheon/tests/test_no_parent.py  (код выхода 0 — все прошли)
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+

_ROOT = tempfile.mkdtemp(prefix="noparent-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
RUN_PY = os.path.join(LIB, "run.py")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402
import batchsuggest as B  # noqa: E402
NOW = datetime(2026, 11, 7, 12, 0).timestamp()
DIR = "metis-pantheon"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


GATE = "Шлюз слияния ядра: перенос записи принять на PR после squash, gate() читает решение владельца по head"
BODY = "Цель: разобрать шлюз.\n\n## Готово, когда\n\n- [ ] пункт один"


def put(home, tid, title, text, status="todo", typ="task", parent=None, created="2026-11-05", touches=None, mode="single",
        extra=()):
    lines = ["---", f"type: {typ}", f"id: {tid}", f'title: "{title}"', f"status: {status}", "project: Пантеон",
             f"direction: {DIR}", f"owner: {DIR}", f"created: {created}", f"updated: {created}T10:00:00", "schema_version: 1"]
    if touches:
        lines.append(f"touches: [{', '.join(touches)}]")
    if parent:
        lines.append(f"parent: {parent}")
    lines += list(extra)
    if mode and typ == "task":
        lines += [f"mode: {mode}", "mode_why: тест"]
    lines += ["---", "", f"# {title}", "", text, "", "## Журнал", "", f"- {created} 10:00 — агент: создана", ""]
    with open(os.path.join(home, "directions", DIR, "tasks", tid + ".md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def make(stories=True):
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="noparent-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("directions/metis-pantheon/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    for d in (state, os.path.join(view, "Доска"), os.path.join(tmp, ".claude", "pantheon")):
        os.makedirs(d, exist_ok=True)
    with open(os.path.join(home, "schedule.toml"), "w") as fh:
        fh.write('primary_host = "mac-a"\n')
    with open(os.path.join(home, "directions.toml"), "w", encoding="utf-8") as fh:
        fh.write('[[direction]]\nname = "metis-pantheon"\nproject = "Пантеон"\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0", "TMPDIR": tmp, "PANTHEON_METRICS": "0", "PANTHEON_NOW": str(int(NOW))}
    if stories:
        put(home, "metis-9001", "Пачка: шлюз слияния", "Шлюз слияния и перенос записей.", typ="story", status="doing", mode=None)
        put(home, "metis-9002", "Шлюз слияния: вернуть на другом head", GATE, touches=["plugins/pantheon/lib/merge.py"],
            parent="metis-9001")
        put(home, "metis-9003", "Шлюз слияния: отпечаток переноса", GATE + " отпечаток", touches=["plugins/pantheon/lib/merge.py"],
            parent="metis-9001")
    return tmp, home, state, env


def pan(env, *a):
    return subprocess.run([PY311, "-I", RUN_PY, *a], env=dict(env), capture_output=True, text=True, timeout=120)


def card(home, tid):
    with open(os.path.join(home, "directions", DIR, "tasks", tid + ".md"), encoding="utf-8") as fh:
        return fh.read()


def new(env, *extra, title="merge.py: gate() теряет принять после squash", body=None):
    return pan(env, "task", "new", "--direction", DIR, "--title", title, "--text",
               body or "gate() в merge.py теряет запись принять после squash слияния, шлюз не переносит решение на PR.",
               *extra)


def part_new():
    tmp, home, state, env = make()
    r = new(env, "--touches", "plugins/pantheon/lib/merge.py")
    hint = [ln for ln in r.stderr.splitlines() if ln.startswith("без пачки:")]
    tid = r.stdout.split()[0] if r.stdout.split() else ""
    check("new без --parent: код 0, в stderr строка с пачкой-кандидатом и готовой командой",
          r.returncode == 0 and len(hint) == 1 and "metis-9001" in hint[0]
          and f"pantheon task set {tid} parent=metis-9001 mode=single mode_why=" in hint[0], r.stderr)
    check("new: stdout прежний (id и путь), подсказка не в stdout", tid.startswith("metis-") and "без пачки" not in r.stdout)
    s = pan(env, "task", "set", tid, "parent=metis-9001", "mode=single", "mode_why=тест")
    check("готовая команда из подсказки выполняется (код 0, parent записан)",
          s.returncode == 0 and "parent: metis-9001" in card(home, tid), s.stderr[-200:])
    r2 = new(env, title="Планы на отпуск", body="Отпуск на море: билеты, отель, экскурсии, фотографии заката и пляж.")
    check("new без кандидата: строка «без пачки: положите в пачку (pantheon task batch-suggest)», код 0",
          r2.returncode == 0 and "без пачки: положите в пачку (pantheon task batch-suggest)" in r2.stderr, r2.stderr)
    r3 = new(env, "--parent", "metis-9001", "--mode", "single", "--mode-why", "тест")
    check("new с --parent: подсказки нет", r3.returncode == 0 and "без пачки" not in r3.stderr, r3.stderr)
    r4 = new(env, "--type", "story", title="Пачка: новая", body=BODY)
    check("new --type story: подсказки нет", r4.returncode == 0 and "без пачки" not in r4.stderr, r4.stderr)
    r5 = pan(env, "task", "new", "--direction", DIR, "--title", "Решить вопрос", "--question", "Что выбрать?")
    check("вопрос владельцу без текста и без полей: отказ прежний (код 2), подсказки нет",
          r5.returncode == 2 and "без пачки" not in r5.stderr, r5.stderr)
    r6 = pan(env, "task", "new", "--direction", DIR, "--title", "Решить вопрос", "--question", "Что выбрать?", "--why", "мешает",
             "--option", "А — один", "--option", "Б — два")
    check("вопрос владельцу с полями и без текста: подсказки нет", r6.returncode == 0 and "без пачки" not in r6.stderr, r6.stderr)
    r7 = new(env, "--touches", "plugins/pantheon/lib/merge.py", "--mode", "single", "--mode-why", "одна")
    h7 = [ln for ln in r7.stderr.splitlines() if ln.startswith("без пачки:")]
    t7 = r7.stdout.split()[0] if r7.stdout.split() else ""
    check("new с --mode: в подсказке parent без повтора mode/mode_why (Д5)",
          len(h7) == 1 and h7[0].endswith(f"pantheon task set {t7} parent=metis-9001"), r7.stderr)
    r8 = new(env, "--batch", "ночь · 1", "--mode", "single", "--mode-why", "одна", "--touches", "plugins/pantheon/lib/merge.py")
    check("new с --batch: подсказки про parent нет (Д5)", r8.returncode == 0 and "без пачки" not in r8.stderr, r8.stderr)
    shutil.rmtree(tmp, True)


def part_pure():
    res = {"joins": [{"task": "metis-1", "story": "s-1"}, {"task": "metis-2", "story": "s-2"}]}
    check("best_join: берёт предложение именно этой задачи, не первое (Д3)",
          B.best_join(res, "metis-2") == res["joins"][1] and B.best_join(res, "metis-1") == res["joins"][0])
    check("best_join: нет предложения для задачи — None (Д3)", B.best_join(res, "metis-3") is None
          and B.best_join({"joins": []}, "metis-1") is None)
    tasks = {"metis-1": ("", {"type": "task", "direction": "d", "status": "todo", "batch": "ночь · 1"}, ""),
             "metis-2": ("", {"type": "task", "direction": "d", "status": "todo"}, ""),
             "metis-3": ("", {"type": "task", "direction": "d", "status": "todo", "parent": "metis-9"}, "")}
    check("suggest: задача со старым полем batch и задача с parent не «без пачки» (Д3)",
          B.suggest(tasks, "d")["open_loose"] == 1)
    done, sk = B.apply({"joins": [{"task": "a-1", "story": "s", "confidence": "high"},
                                  {"task": "a-2", "story": "s", "confidence": "high"}]}, {},
                       lambda t, sid: (_ for _ in ()).throw(OSError("диск полон")) if t == "a-1" else None)
    check("apply: сбой записи (OSError) на первой — пропуск со строкой, вторая прикреплена (Д6)",
          done == ["a-2 → s"] and len(sk) == 1 and "сбой записи" in sk[0] and "диск полон" in sk[0], (done, sk))


def part_attach_race():
    tmp, home, state, env = make()
    put(home, "metis-9005", "Пачка вторая", "x", typ="story", status="doing", mode=None)
    put(home, "metis-9020", "Свободная", "x")
    put(home, "metis-9021", "Уже в пачке после расчёта", "x", parent="metis-9001")
    try:
        T.task_attach(home, NOW, "metis-9021", "metis-9005", only_loose=True)
        err = ""
    except ValueError as e:
        err = str(e)
    check("task_attach only_loose: parent уже стоит — отказ до записи, карточки не тронуты (Д4)",
          "уже в пачке metis-9001" in err and "parent: metis-9001\n" in card(home, "metis-9021")
          and "9021" not in card(home, "metis-9005"), err)
    old = T.task_attach(home, NOW, "metis-9021", "metis-9005")
    check("task_attach без only_loose: ручной перенос между пачками работает как раньше", old == "metis-9001"
          and "parent: metis-9005" in card(home, "metis-9021"))
    check("task_attach only_loose: свободная прикрепляется", T.task_attach(home, NOW, "metis-9020", "metis-9005",
                                                                          only_loose=True) is None)
    shutil.rmtree(tmp, True)


def part_check():
    tmp, home, state, env = make(stories=False)
    put(home, "metis-9101", "Старая без пачки", "x", created="2026-11-05")           # тревога
    put(home, "metis-9102", "Свежая без пачки", "x", created="2026-11-07")           # моложе суток
    put(home, "metis-9103", "Хвост до плана 1.0", "x", created="2026-11-02")        # старый хвост
    put(home, "metis-9104", "Закрытая", "x", status="done", created="2026-11-05")
    put(home, "metis-9105", "Отброшенная", "x", status="dropped", created="2026-11-05")
    put(home, "metis-9106", "В пачке", "x", created="2026-11-05", parent="metis-9100")
    put(home, "metis-9100", "Пачка", "x", typ="story", created="2026-11-05", mode=None)
    put(home, "metis-9107", "Граница 03.11", "x", created="2026-11-03")              # тревога
    r = pan(env, "check", "--quiet")
    alerts = [ln for ln in r.stdout.splitlines() if "задачи без пачки" in ln]
    line = alerts[0] if alerts else ""
    check("check --quiet: одна тревога, в ней 9101 и 9107",
          len(alerts) == 1 and "metis-9101" in line and "metis-9107" in line, r.stdout[-400:])
    check("check --quiet: свежая, старый хвост, закрытые, в пачке и сама пачка не названы",
          not any(x in line for x in ("9102", "9103", "9104", "9105", "9106", "9100")), line)
    r2 = pan(env, "check", "--quiet")
    check("второй проход: тот же список не тревожит заново", "задачи без пачки" not in r2.stdout, r2.stdout[-300:])
    put(home, "metis-9108", "Ещё одна", "x", created="2026-11-04")
    r3 = pan(env, "check", "--quiet")
    a3 = [ln for ln in r3.stdout.splitlines() if "задачи без пачки" in ln]
    check("новая задача без пачки: тревога только про неё (один раз на id)",
          len(a3) == 1 and "metis-9108" in a3[0] and "metis-9101" not in a3[0], r3.stdout[-300:])
    put(home, "metis-9109", "С полем batch", "x", created="2026-11-05", extra=["batch: ночь · 1"])
    put(home, "metis-9110", "Во входящих", "x", status="inbox", created="2026-11-05")
    put(home, "metis-9111", "Вопрос владельцу", "x", status="waiting", created="2026-11-05", extra=["waiting_on: human"])
    put(home, "metis-9112", "Ждёт другую задачу", "x", status="waiting", created="2026-11-05", extra=["waiting_on: metis-9101"])
    r3b = pan(env, "check", "--quiet")
    a3b = " ".join(ln for ln in r3b.stdout.splitlines() if "задачи без пачки" in ln)
    check("check: поле batch, inbox и вопрос владельцу (waiting human) не названы; ждущая задачу — названа (Д3, С)",
          "9109" not in a3b and "9110" not in a3b and "9111" not in a3b and "metis-9112" in a3b, r3b.stdout[-300:])
    seen_p = os.path.join(state, "no-parent-seen.json")
    with open(seen_p, encoding="utf-8") as fh:
        seen_now = fh.read()
    os.rename(os.path.join(home, "directions", DIR, "tasks", "metis-9101.md"), os.path.join(tmp, "x.md"))
    pan(env, "check", "--quiet")
    with open(seen_p, encoding="utf-8") as fh:
        seen_gone = fh.read()
    os.rename(os.path.join(tmp, "x.md"), os.path.join(home, "directions", DIR, "tasks", "metis-9101.md"))
    r3c = pan(env, "check", "--quiet")
    check("check: ушедшая из списка задача забывается и при возвращении тревожит снова (Д3)",
          "metis-9101" in seen_now and "metis-9101" not in seen_gone and "metis-9101" in r3c.stdout, (seen_now, seen_gone))
    r4 = pan(env, "check")
    check("check руками: предупреждение со списком, код выхода не меняется (0)",
          r4.returncode == 0 and "предупреждение · задачи без пачки старше суток" in r4.stdout and "metis-9101" in r4.stdout,
          r4.stdout[-300:] + str(r4.returncode))
    shutil.rmtree(tmp, True)


def part_many():
    tmp, home, state, env = make(stories=False)
    for i in range(15):
        put(home, f"metis-92{i:02d}", f"Задача {i}", "x", created="2026-11-05")
    r = pan(env, "check", "--quiet")
    a = [ln for ln in r.stdout.splitlines() if "задачи без пачки" in ln]
    check("тревога на 15 задач: названы первые 12, «и ещё 3» (Д7)",
          len(a) == 1 and "metis-9211" in a[0] and "metis-9212" not in a[0] and "и ещё 3" in a[0], r.stdout[-300:])
    r2 = pan(env, "check", "--quiet")
    a2 = [ln for ln in r2.stdout.splitlines() if "задачи без пачки" in ln]
    check("скрытый хвост не считается виденным: следующий тик называет остальные три (Д7)",
          len(a2) == 1 and all(x in a2[0] for x in ("metis-9212", "metis-9213", "metis-9214")) and "metis-9200" not in a2[0],
          r2.stdout[-300:])
    r3 = pan(env, "check", "--quiet")
    check("потом тихо", "задачи без пачки" not in r3.stdout, r3.stdout[-200:])
    shutil.rmtree(tmp, True)


def part_tick():
    tmp, home, state, env = make()
    put(home, "metis-9010", "merge.py: gate() теряет принять после squash",
        GATE + " сверху", touches=["plugins/pantheon/lib/merge.py"])
    put(home, "metis-9011", "merge.py: ещё замечание про gate()", "gate() в merge.py: шлюз слияния, принять на PR после squash.",
        touches=["plugins/pantheon/lib/merge.py"], mode="undecided")
    put(home, "metis-9012", "Шлюз слияния ядра: перенос записи", GATE + " отпечаток")
    r = pan(env, "batch-suggest", "run")
    check("run: код 0, 9010 прикреплена к 9001 (уверенно), строка в выводе",
          r.returncode == 0 and "parent: metis-9001" in card(home, "metis-9010") and "прикреплено · metis-9010 → metis-9001" in r.stdout,
          r.stdout[-300:] + r.stderr[-200:])
    check("run: в журнале задачи строка о прикреплении от «плановый проход»",
          "плановый проход: прикреплена к пачке metis-9001" in card(home, "metis-9010"), card(home, "metis-9010")[-300:])
    with open(os.path.join(tmp, "view", "Доска", "Пачки-предложения.md"), encoding="utf-8") as fh:
        board = fh.read()
    check("run: прикреплённая уже не числится среди предложений на доске", "metis-9010 →" not in board, board[-300:])
    check("run: в журнале пачки строка о задаче", "прикреплена задача metis-9010" in card(home, "metis-9001"))
    check("run: без mode (9011, undecided) и «не уверенно» (9012) не прикреплены, проход не падает",
          "parent:" not in card(home, "metis-9011") and "parent:" not in card(home, "metis-9012") and r.returncode == 0,
          r.stdout[-400:])
    shutil.rmtree(tmp, True)


def part_tick_race():
    tmp, home, state, env = make()
    put(home, "metis-9005", "Пачка другая", "Другое.", typ="story", status="doing", mode=None)
    put(home, "metis-9010", "merge.py: gate() теряет принять после squash",
        GATE + " сверху", touches=["plugins/pantheon/lib/merge.py"])
    code = (f"import sys; sys.path.insert(0, {LIB!r}); import pantheon as P; T = P.tasks_mod(); B = P.batchsuggest_mod(); "
            "orig = B.suggest\n"
            "def late(tasks, d):\n"
            "    r = orig(tasks, d)\n"
            "    if not getattr(late, 'done', False) and r['joins']:\n"
            "        late.done = True\n"
            "        T.task_set(P.PANTHEON, P.now(), 'metis-9010', {'parent': 'metis-9005'}, note='руками, пока шёл расчёт')\n"
            "    return r\n"
            "B.suggest = late; P.batchsuggest_mod = lambda: B\n"
            "sys.exit(P.batch_suggest_run(['run']))")
    r = subprocess.run([PY311, "-I", "-c", code], env=dict(env), capture_output=True, text=True, timeout=120)
    check("проход: пачку поставили руками между расчётом и записью — не переносит, строка «пропущено» (Д4)",
          r.returncode == 0 and "parent: metis-9005" in card(home, "metis-9010") and "parent: metis-9001" not in card(home, "metis-9010")
          and "пропущено · metis-9010" in r.stdout and "предложение устарело" in r.stdout, r.stdout[-400:] + r.stderr[-300:])
    shutil.rmtree(tmp, True)


def main():
    part_new()
    part_pure()
    part_attach_race()
    part_check()
    part_many()
    part_tick()
    part_tick_race()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
