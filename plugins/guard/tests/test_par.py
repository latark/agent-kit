#!/usr/bin/env python3
"""Параллельные случаи файла тестов (_par.py, metis-0544): то же, что подряд, только быстрее.

Запуск: python3 -I plugins/guard/tests/test_par.py   (код выхода 0 — все прошли)
Каждый прогон — отдельный процесс DRIVER (как файл тестов): run_cases над случаями-пробами, вывод разбирается здесь.
Проверяет: случаи идут сразу по n (все n ждут друг друга у барьера — без замера времени); при n=1 — по одному; вывод
и записи sink — целиком и по порядку случаев, хотя первый кончается последним; исключение и выход без итога — строка
«ОШИБКА» и crash, остальные случаи идут; atexit родителя дети не запускают; TESTS_JOBS и число по умолчанию.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SUB_TIMEOUT = 60
results = []


def check(name, ok, info=None):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not info else "\n     " + str(info)[:900]))


DRIVER = r"""
import atexit, json, os, sys, time
sys.path.insert(0, sys.argv[1])
from _par import run_cases, jobs
work, mode, n = sys.argv[2], sys.argv[3], int(sys.argv[4])
sink, crashed = [], []
atexit.register(lambda: open(os.path.join(work, "atexit-" + str(os.getpid())), "w").close())


def barrier(i, k):
    # случай i ждёт, пока не придут k случаев: без параллели больше одного не придёт никогда
    open(os.path.join(work, f"in-{i}"), "w").close()
    end = time.monotonic() + 20
    while time.monotonic() < end:
        if sum(f.startswith("in-") for f in os.listdir(work)) >= k:
            return True
        time.sleep(0.01)
    return False


def overlap(i):
    # сколько случаев идут сразу: файл run-<i> живёт, пока идёт случай
    p = os.path.join(work, f"run-{i}")
    open(p, "w").close()
    seen = sum(f.startswith("run-") for f in os.listdir(work))
    time.sleep(0.05)
    seen = max(seen, sum(f.startswith("run-") for f in os.listdir(work)))
    os.remove(p)
    return seen


def case(i):
    def fn():
        if mode == "barrier":
            sink.append(barrier(i, n))
        elif mode == "serial":
            sink.append(overlap(i))
        elif mode == "order":
            time.sleep(0.4 if i == 0 else 0)  # первый кончается последним
            print(f"case {i} line 1")
            print(f"case {i} line 2", file=sys.stderr)
            sink.append(f"s{i}")
        elif mode == "fail":
            print(f"case {i}")
            if i == 1:
                raise ValueError("boom")
            if i == 2:
                os._exit(3)
            sink.append(i)
    return fn


cases = [(f"c{i}", case(i)) for i in range(int(os.environ.get("CASES", "3")))]
got = run_cases(cases, sink, lambda name, err: crashed.append([name, err]), n=n or None)
print("RESULT " + json.dumps({"n": got, "sink": sink, "crashed": crashed, "jobs": jobs()}))
"""


def drive(mode, n, cases=3, env_extra=None):
    work = tempfile.mkdtemp(prefix="par-test-")
    try:
        drv = os.path.join(work, "driver.py")
        with open(drv, "w") as fh:
            fh.write(DRIVER)
        sub = os.path.join(work, "w")
        os.makedirs(sub)
        env = {k: v for k, v in os.environ.items() if k != "TESTS_JOBS"}  # число по умолчанию — без чужой переменной
        env.update(CASES=str(cases), **(env_extra or {}))
        r = subprocess.run([sys.executable, "-I", drv, HERE, sub, mode, str(n)], capture_output=True, text=True,
                           env=env, timeout=SUB_TIMEOUT)
        res = next((json.loads(x[7:]) for x in r.stdout.splitlines() if x.startswith("RESULT ")), None)
        atexits = [f for f in os.listdir(sub) if f.startswith("atexit-")]
        return r, res, atexits
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    r, res, atexits = drive("barrier", 3)
    check("n=3: три случая идут сразу — все дошли до барьера на троих", res and res["sink"] == [True] * 3, (r.stdout, r.stderr))
    check("atexit родителя дети не запускают: один файл — от самого родителя", len(atexits) == 1, atexits)
    r, res, _ = drive("serial", 1, cases=4)
    check("n=1: случаи по одному — больше одного сразу не идёт", res and res["sink"] == [1, 1, 1, 1], (r.stdout, r.stderr))
    r, res, _ = drive("order", 3, cases=4)
    lines = [x for x in r.stdout.splitlines() if x.startswith("case ")]
    want = [f"case {i} line {k}" for i in range(4) for k in (1, 2)]
    check("вывод случаев (stdout и stderr) — целиком и по порядку, хотя первый кончился последним", lines == want, lines)
    check("записи sink — по порядку случаев", res and res["sink"] == ["s0", "s1", "s2", "s3"] and res["n"] == 4, res)
    r, res, _ = drive("fail", 3, cases=4)
    crashed = dict(map(tuple, res["crashed"])) if res else {}
    check("исключение в случае — crash с типом и текстом, строка «ОШИБКА» с меткой",
          crashed.get("c1") == "ValueError boom" and "ОШИБКА: c1 ValueError boom" in r.stdout, (r.stdout, crashed))
    check("выход случая без итога (os._exit) — crash «без итога» с кодом",
          "кодом 3 без итога" in crashed.get("c2", ""), crashed)
    check("остальные случаи идут и отдают записи: sink [0, 3]", res and res["sink"] == [0, 3], res)
    check("трассировка исключения — в выводе случая", "Traceback" in r.stdout and "ValueError: boom" in r.stdout, r.stdout)
    for val, want in (("2", 2), ("1", 1), ("0", None), ("x", None), ("", None)):
        _, res, _ = drive("order", 1, cases=1, env_extra={"TESTS_JOBS": val})
        dflt = max(1, min(3, (os.cpu_count() or 2) // 2))
        check(f"TESTS_JOBS={val!r} → {want or f'по умолчанию {dflt}'}", res and res["jobs"] == (want or dflt), res)
    print(f"{sum(results)} из {len(results)} прошли")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
