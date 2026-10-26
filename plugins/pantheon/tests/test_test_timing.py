#!/usr/bin/env python3
"""Замер тестов плагина (metis-0447): _run_plugin_tests пишет в журнал прогона строку на каждый файл — интерпретатор,
wall, CPU детей (user+sys), rc, load до и после, — а _timing_summary даёт сводку самых медленных файлов.

Запуск: python3 -I plugins/pantheon/tests/test_test_timing.py  (код выхода 0 — все прошли)
Идёт и на системном /usr/bin/python3 (3.9): сам pantheon.py тогда запускается через python3 3.11+ (_py311).
Фальшивые test_*.py в временной папке: быстрый, медленный (жжёт CPU), падающий (код 3), зависающий (таймаут)."""
import os
import re
import subprocess
import sys
import tempfile
import atexit as _atexit
import shutil as _shutil

_ROOT = tempfile.mkdtemp(prefix="test_timing-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # noqa: E402

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        fails.append(name)


def mkplugin(files):
    d = tempfile.mkdtemp(prefix="plugin-")
    os.makedirs(os.path.join(d, "tests"))
    for f, body in files.items():
        with open(os.path.join(d, "tests", f), "w") as fh:
            fh.write(body)
    return d


DRIVER = r"""
import sys, io, os, tempfile
sys.path.insert(0, sys.argv[1])
import pantheon as P
P.PLUGIN_TEST_TIMEOUT = float(sys.argv[3])
pdir, tmp = sys.argv[2], tempfile.mkdtemp()
log = io.StringIO()
timings = []
P._run_plugin_tests(pdir, [sys.executable], tmp, log, "новая 1.0", __import__("time").monotonic() + 100, timings=timings)
log.write("\n".join(P._timing_summary(timings, top=int(sys.argv[4]))) + "\n")
sys.stdout.write(log.getvalue())
sys.stdout.write("PY=" + sys.executable + "\n")
"""

SLOW = "import time\nt = time.process_time()\nwhile time.process_time() - t < 0.4: pass\nprint('1 ok')\n"
FILES = {
    "test_a_fast.py": "print('1 ok')\n",
    "test_b_slow.py": SLOW + "time.sleep(0.5)\n",
    "test_c_fail.py": "import sys\nprint('FAIL x')\nsys.exit(3)\n",
    "test_d_hang.py": "import time\ntime.sleep(30)\n",
}


def run(files, timeout="2", top="8", env_extra=None):
    d = mkplugin(files)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PANTHEON_")}
    env.update({"HOME": tempfile.mkdtemp(prefix="home-"), "PANTHEON_TEST": "1", "PANTHEON_FAKE_SWAP": "0"})
    env.update(env_extra or {})
    r = subprocess.run([PY311, "-I", "-c", DRIVER, LIB, d, timeout, top], env=env, capture_output=True, text=True,
                       timeout=120)
    return r


r = run(FILES)
check("драйвер завершился кодом 0", r.returncode == 0, r.stderr[-400:])
out = r.stdout
py = re.search(r"^PY=(.*)$", out, re.M).group(1) if "PY=" in out else "?"
ROW = re.compile(r"^замер · (?P<label>.+?) · py=(?P<py>\S+) · файл=(?P<f>\S+) · wall=(?P<wall>\d+\.\d\d) с · "
                 r"cpu=(?P<cpu>\d+\.\d\d) с · rc=(?P<rc>\S+) · load=(?P<l0>[\d.—]+)→(?P<l1>[\d.—]+)$", re.M)
rows = {m["f"]: m for m in ROW.finditer(out)}
check("строка замера на каждый из 4 файлов", sorted(rows) == sorted(FILES), str(sorted(rows)))
check("в строке интерпретатор прогона", all(m["py"] == py for m in rows.values()), py)
check("в строке подпись прогона", all(m["label"] == "новая 1.0" for m in rows.values()))
check("rc: 0, 0, 3, таймаут", [rows[f]["rc"] for f in sorted(FILES)] == ["0", "0", "3", "таймаут"],
      str([rows[f]["rc"] for f in sorted(rows)]))
check("wall медленного >= 0.9 с", float(rows["test_b_slow.py"]["wall"]) >= 0.9, rows["test_b_slow.py"][0])
check("cpu медленного >= 0.35 с (жжёт процессор)", float(rows["test_b_slow.py"]["cpu"]) >= 0.35, rows["test_b_slow.py"][0])
check("cpu спящего меньше его wall", float(rows["test_d_hang.py"]["cpu"]) < float(rows["test_d_hang.py"]["wall"]) - 0.5,
      rows["test_d_hang.py"][0])
check("wall зависшего ~ таймаут 2 с", 1.9 <= float(rows["test_d_hang.py"]["wall"]) < 6, rows["test_d_hang.py"][0])
check("load до и после — числа (или —, если ОС не отдала)",
      all(re.fullmatch(r"\d+\.\d\d|—", m["l0"]) and re.fullmatch(r"\d+\.\d\d|—", m["l1"]) for m in rows.values()))
check("строка замера идёт после вывода своего файла",
      out.index("===== новая 1.0") < out.index("замер · новая 1.0"))

sm = out[out.index("===== замер:"):]
head = sm.splitlines()[0]
check("заголовок сводки: 4 из 4 файлов", "4 самых медленных из 4 прогнанных файлов" in head, head)
lines = [ln for ln in sm.splitlines()[1:] if re.match(r"\d+\. wall=", ln)]
walls = [float(re.search(r"wall=(\d+\.\d\d)", ln)[1]) for ln in lines]
check("сводка по убыванию wall", walls == sorted(walls, reverse=True) and len(walls) == 4, str(walls))
check("первым в сводке — зависший", "test_d_hang.py" in lines[0], lines[0] if lines else "")
check("вторым — медленный", "test_b_slow.py" in lines[1], lines[1] if len(lines) > 1 else "")

# top ограничивает сводку
r2 = run(FILES, top="2")
sm2 = r2.stdout[r2.stdout.index("===== замер:"):]
check("top=2: две строки и заголовок «2 самых медленных из 4»",
      len([ln for ln in sm2.splitlines() if re.match(r"\d+\. wall=", ln)]) == 2
      and "2 самых медленных из 4" in sm2.splitlines()[0], sm2)

# файл не из тестов и срок прогона: без файлов замера нет, строки «замер ·» нет
r3 = run({"test_only.py": "print('1 ok')\n"})
check("один файл — одна строка замера и сводка из 1", r3.stdout.count("замер · новая") == 1
      and "1 самых медленных из 1" in r3.stdout, r3.stdout[-300:])

# мутант: без timings (не передан) журнал всё равно пишет строки, список не нужен
DRV2 = DRIVER.replace("log, \"новая 1.0\", __import__(\"time\").monotonic() + 100, timings=timings)",
                      "log, \"новая 1.0\", __import__(\"time\").monotonic() + 100)")
d = mkplugin({"test_x.py": "print('1 ok')\n"})
env = {k: v for k, v in os.environ.items() if not k.startswith("PANTHEON_")}
env.update({"HOME": tempfile.mkdtemp(prefix="home-"), "PANTHEON_TEST": "1"})
r4 = subprocess.run([PY311, "-I", "-c", DRV2, LIB, d, "2", "8"], env=env, capture_output=True, text=True, timeout=60)
check("без списка timings строка замера всё равно в журнале", r4.returncode == 0 and "замер · новая 1.0" in r4.stdout,
      r4.stderr[-300:])

# срок прогона исчерпан: файл не запускался — строки замера нет
DRV3 = DRIVER.replace("__import__(\"time\").monotonic() + 100", "__import__(\"time\").monotonic() - 1")
r5 = subprocess.run([PY311, "-I", "-c", DRV3, LIB, d, "2", "8"], env=env, capture_output=True, text=True, timeout=60)
check("срок исчерпан: строки замера нет, сводка пустая", r5.returncode == 0 and "замер · новая" not in r5.stdout
      and "0 самых медленных из 0" in r5.stdout, r5.stdout[-300:] + r5.stderr[-300:])

print(f"\n{len(fails)} провалено" if fails else "\nвсе проверки прошли")
sys.exit(1 if fails else 0)
