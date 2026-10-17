#!/usr/bin/env python3
"""Тесты замера минут владельца (lib/mmv.py; metis-0169). Запуск: python3 -I plugins/pantheon/tests/test_mmv.py

Модуль самостоятельный — идёт и на системном 3.9. Каждый тест — своя временная STATE; настоящие ~/.local/state и
~/.claude не трогаются. CLI (`pantheon mmv`, `night report`) проверяется интерпретатором 3.11+ из _py311.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("mmv_under_test", os.path.join(ROOT, "lib", "mmv.py"))
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
FAILS = []
TMPS = []


def check(cond, what):
    if not cond:
        FAILS.append(what)
        print("НЕ ПРОШЛО:", what)


def state(board=(), zeus=()):
    s = tempfile.mkdtemp(prefix="mmv-")
    TMPS.append(s)
    os.makedirs(os.path.join(s, "owner-log"))
    with open(os.path.join(s, "owner-log", "board.jsonl"), "w", encoding="utf-8") as fh:
        for b in board:
            fh.write(b + "\n")
    with open(os.path.join(s, "owner-log", "zeus.md"), "w", encoding="utf-8") as fh:
        for z in zeus:
            fh.write(f"## {z} · окно вопросов\n\nСЕКРЕТНЫЙ ТЕКСТ\n\n")
    return s


def rec(t):
    return json.dumps({"time": t, "kind": "answer", "id": "x-0001"})


def day(rs, d):
    return [r for r in rs if r["date"] == d][0]


# 1. пример из задачи: 10:00:00, 10:02:00, 10:20:00 → 2 мин + 45 с × 2 = 3,5 мин
s = state([rec("2026-10-15T10:00:00+03:00"), rec("2026-10-15T10:02:00"), rec("2026-10-15T10:20:00")])
r = day(M.rows(s), "2026-10-15")
check(r["min"] == 3.5 and r["entries"] == 2 and r["events"] == 3, f"пример 3,5 мин: {r}")

# 2. события из board.jsonl и md сливаются по времени; текст не попадает в вывод
s = state([rec("2026-10-15T10:00:00"), rec("2026-10-15T10:04:00")], ["2026-10-15 10:02:00"])
r = day(M.rows(s), "2026-10-15")
check(r["min"] == 4.75 and r["entries"] == 1 and r["events"] == 3, f"слияние источников: {r}")
check("СЕКРЕТНЫЙ" not in json.dumps(M.rows(s)), "текст журнала не читается")

# 3. ровно 5 мин — ещё один сеанс, 5 мин 1 с — перерыв
s = state([rec("2026-10-15T10:00:00"), rec("2026-10-15T10:05:00"), rec("2026-10-15T10:10:01")])
r = day(M.rows(s), "2026-10-15")
check(r["min"] == 5.0 + 1.5 and r["entries"] == 2, f"граница 5 мин: {r}")

# 4. через полночь — по дням
s = state([rec("2026-10-15T23:58:00"), rec("2026-10-16T00:02:00")])
rs = M.rows(s)
a, b = day(rs, "2026-10-15"), day(rs, "2026-10-16")
check(a["min"] == 2.75 and a["entries"] == 1, f"день до полуночи: {a}")
check(b["min"] == 2.0 and b["entries"] == 0 and b["events"] == 1, f"день после полуночи: {b}")

# 5. битые строки пропускаются
s = state(["не json", "{", '{"time": 5}', '{"time": "мусор"}', "[]", rec("2026-10-15T10:00:00"),
           rec("2026-10-15T10:01:00")])
with open(os.path.join(s, "owner-log", "bad.md"), "wb") as fh:
    fh.write(b"## 2026-13-45 99:99:99 x\n\xff\xfe\n## 2026-10-15 10:02:00\n")
r = day(M.rows(s), "2026-10-15")
check(r["events"] == 3 and r["min"] == 2.75, f"битые строки пропущены: {r}")

# 6. пустая папка, без owner-log
e = tempfile.mkdtemp(prefix="mmv-")
TMPS.append(e)
check(M.rows(e) == [], "пустой STATE — нет строк")
check(len(M.rows(e, 3, date(2026, 10, 17))) == 3, "days=3 даёт 3 дня с нулями")

# 7. save: строка за день в mmv.jsonl, повторный запуск не плодит дубли
s = state([rec("2026-10-15T10:00:00"), rec("2026-10-15T10:02:00")])
M.save(s, M.rows(s))
M.save(s, M.rows(s))
lines = open(os.path.join(s, "mmv.jsonl"), encoding="utf-8").read().splitlines()
check(len(lines) == 1 and json.loads(lines[0])["min"] == 2.75, f"mmv.jsonl: {lines}")

# 7а-г. save(): не терять дни
def jl(path):
    return [json.loads(x) for x in open(path, encoding="utf-8")]


def R(d, ev, mn=1.0):
    return {"date": d, "min": mn, "entries": 1, "events": ev}


def seed(rows, raw=None):
    d = tempfile.mkdtemp(prefix="mmv-save-")
    TMPS.append(d)
    with open(os.path.join(d, "mmv.jsonl"), "wb") as fh:
        fh.write(raw if raw is not None else "".join(json.dumps(r) + "\n" for r in rows).encode())
    return d


def byd(d):
    return {r["date"]: r for r in jl(os.path.join(d, "mmv.jsonl"))}


# а) файл есть, но не декодируется — не переписываем
bad = b"\xff\xfe\x00garbage\n"
d = seed(None, raw=bad)
M.save(d, [R("2026-10-01", 3)])
check(open(os.path.join(d, "mmv.jsonl"), "rb").read() == bad, "7а: нечитаемый mmv.jsonl не переписан")
check(os.listdir(d) == ["mmv.jsonl"], f"7а: нет лишних файлов: {os.listdir(d)}")

# б) пустой/неполный день не затирает полный; равный или больший — заменяет
d = seed([R("2026-10-01", 5, 9.0), R("2026-10-02", 2, 1.0)])
M.save(d, [R("2026-10-01", 0, 0.0), R("2026-10-02", 3, 2.0), R("2026-10-03", 0, 0.0)])
got = byd(d)
check(got["2026-10-01"]["min"] == 9.0, f"7б: пустой день не затёр полный: {got['2026-10-01']}")
check(got["2026-10-02"]["min"] == 2.0, f"7б: больше событий заменяет: {got['2026-10-02']}")
check("2026-10-03" in got, "7б: новый пустой день добавлен")
M.save(d, [R("2026-10-02", 3, 7.0)])
check(byd(d)["2026-10-02"]["min"] == 7.0, "7б: равное число событий заменяет")
M.save(d, [R("2026-10-01", 4, 1.0)])
check(byd(d)["2026-10-01"]["min"] == 9.0, "7б: неполный день (4<5) не затёр")

# в) временный файл — уникальное имя в той же папке; после записи не остаётся
seen = []
_rep = os.replace
os.replace = lambda a, b: (seen.append((a, b)), _rep(a, b))[1]
try:
    d = seed([R("2026-10-01", 1)])
    M.save(d, [R("2026-10-02", 1)])
    M.save(d, [R("2026-10-03", 1)])
finally:
    os.replace = _rep
check(len(seen) == 2 and seen[0][0] != seen[1][0] and seen[0][0] != seen[0][1] + ".tmp"
      and all(os.path.dirname(a) == d for a, _ in seen), f"7в: уникальные tmp в папке STATE: {seen}")
check(os.listdir(d) == ["mmv.jsonl"], f"7в: tmp убран: {os.listdir(d)}")

# г) дни, которых нет в new, не трогаются
d = seed([R("2026-09-01", 4, 5.0), R("2026-09-02", 2, 3.0)])
M.save(d, [R("2026-10-01", 1)])
check(list(byd(d)) == ["2026-09-01", "2026-09-02", "2026-10-01"], "7г: прежние дни остались")

# 8. line() для night report
T16 = time.mktime((2026, 10, 16, 12, 0, 0, 0, 0, -1))  # «сейчас» сводки, не настоящая дата
ln = M.line(s, 7, T16)
check("вчера 2,8" in ln, ln)
check([M._entries(n) for n in (1, 2, 5, 11, 12, 21, 22, 25)] ==
      ["1 вход", "2 входа", "5 входов", "11 входов", "12 входов", "21 вход", "22 входа", "25 входов"],
      "склонение «вход»")

# 9. CLI на 3.11+: pantheon mmv и night report (HOME и STATE — временные)
if PY311:
    s = state([rec("2026-10-15T10:00:00"), rec("2026-10-15T10:02:00"), rec("2026-10-15T10:20:00")])
    home = tempfile.mkdtemp(prefix="mmv-home-")
    TMPS.append(home)
    env = dict(os.environ, HOME=home, PANTHEON_HOME=os.path.join(home, "ai", "pantheon"), PANTHEON_STATE=s,
               PANTHEON_HOST="mac-a", PANTHEON_NOW=str(T16))
    cli = os.path.join(ROOT, "lib", "pantheon.py")

    def run(*a):
        return subprocess.run([PY311, "-I", cli] + list(a), capture_output=True, text=True, env=env, timeout=120)

    p = run("mmv", "--days", "400")
    check(p.returncode == 0 and "2026-10-15" in p.stdout and "3,5" in p.stdout,
          f"CLI mmv: {p.returncode} {p.stdout[-300:]} {p.stderr[-300:]}")
    rows = [json.loads(x) for x in open(os.path.join(s, "mmv.jsonl"), encoding="utf-8")]
    check(any(x["date"] == "2026-10-15" and x["min"] == 3.5 for x in rows), f"CLI пишет mmv.jsonl: {rows[:2]}")
    check(run("mmv", "--days", "x").returncode == 2, "CLI mmv --days x → код 2")
    p = run("night", "report")
    check(p.returncode == 0 and "ММВ" in p.stdout, f"night report содержит ММВ: {p.stdout[-400:]} {p.stderr[-300:]}")
    check("вчера 3,5 мин (2 входа)" in p.stdout, f"night report: «вчера» от PANTHEON_NOW: {p.stdout[-400:]}")
else:
    print("CLI пропущен: нет Python 3.11+")

for t in TMPS:
    shutil.rmtree(t, True)
print("FAIL" if FAILS else "OK", len(FAILS))
sys.exit(1 if FAILS else 0)
