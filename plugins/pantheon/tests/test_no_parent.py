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
NOW = datetime(2026, 11, 7, 12, 0).timestamp()
DIR = "metis-pantheon"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


GATE = "Шлюз слияния ядра: перенос записи принять на PR после squash, gate() читает решение владельца по head"
BODY = "Цель: разобрать шлюз.\n\n## Готово, когда\n\n- [ ] пункт один"


def put(home, tid, title, text, status="todo", typ="task", parent=None, created="2026-11-05", touches=None, mode="single"):
    lines = ["---", f"type: {typ}", f"id: {tid}", f'title: "{title}"', f"status: {status}", "project: Пантеон",
             f"direction: {DIR}", f"owner: {DIR}", f"created: {created}", f"updated: {created}T10:00:00", "schema_version: 1"]
    if touches:
        lines.append(f"touches: [{', '.join(touches)}]")
    if parent:
        lines.append(f"parent: {parent}")
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
    r4 = pan(env, "check")
    check("check руками: предупреждение со списком, код выхода не меняется (0)",
          r4.returncode == 0 and "предупреждение · задачи без пачки старше суток" in r4.stdout and "metis-9101" in r4.stdout,
          r4.stdout[-300:] + str(r4.returncode))
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


def main():
    part_new()
    part_check()
    part_tick()
    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
