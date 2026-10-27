#!/usr/bin/env python3
"""Параллельный раннер файлов тестов scripts/run-tests.py (metis-0450).

Запуск: python3 -I plugins/pantheon/tests/test_run_tests.py  (код выхода 0 — все прошли). Идёт и на системном
/usr/bin/python3 (3.9). Фальшивые плагины во временной папке: зелёный, падающий, зависающий, без итога, без файлов;
раннер в своей сессии, как задача run_job, гасится SIGTERM / SIGHUP / SIGINT — ни файла тестов, ни его внука после."""
import atexit
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

_ROOT = tempfile.mkdtemp(prefix="test_run_tests-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
atexit.register(shutil.rmtree, _ROOT, True)

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
RUNNER = os.path.join(PLUGIN, "scripts", "run-tests.py")
fails = []
total = 0


def check(name, cond, extra=""):
    global total
    total += 1
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else f"  {str(extra)[-600:]}"))
    if not cond:
        fails.append(name)


def mkplugin(files, name=None):
    d = tempfile.mkdtemp(prefix="plugin-")
    if name:
        d = os.path.join(d, name)
    os.makedirs(os.path.join(d, "tests"))
    for f, body in files.items():
        with open(os.path.join(d, "tests", f), "w") as fh:
            fh.write(body)
    return d


def run(args, timeout=120, env=None):
    return subprocess.run([sys.executable, "-I", RUNNER] + args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout, env=env, text=True)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # зомби — не живой: ps видит его со state Z
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], stdout=subprocess.PIPE, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")


def wait_file(p, sec=20):
    end = time.monotonic() + sec
    while time.monotonic() < end:
        if os.path.exists(p) and open(p).read().strip():
            return open(p).read().strip()
        time.sleep(0.05)
    return None


def load_runner():
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_tests_mod", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = load_runner()
OK2 = "print('ok   один')\nprint('ok   два')\nprint('2 из 2 прошли')\n"

# --- зелёный прогон: два плагина, сумма проверок из итогов ---
a = mkplugin({"test_a.py": OK2, "test_b.py": "print('тестов: 5, все прошли')\n"}, "alpha")
b = mkplugin({"test_c.py": "print('ok x')\nprint('1/1')\n"}, "beta")
r = run([a, b])
check("зелёный: код 0", r.returncode == 0, r.stdout)
check("зелёный: сумма проверок 2+5+1", "проверок 8;" in r.stdout and "файлов 3, ok 3, FAIL 0" in r.stdout, r.stdout)
check("зелёный: строка на файл с плагином", "ok   alpha/test_a.py" in r.stdout and "beta/test_c.py" in r.stdout,
      r.stdout)

# --- падение: код 1 у одного файла — раннер не 0, хвост вывода в итоге ---
p = mkplugin({"test_a.py": OK2, "test_bad.py": "print('ok   раз')\nprint('FAIL два  деталь')\nprint('1 из 2')\n"
              "raise SystemExit(1)\n"})
r = run([p])
check("падение: код не 0", r.returncode != 0, r.stdout)
check("падение: FAIL с кодом файла", re.search(r"FAIL \S+/test_bad\.py .*код 1", r.stdout) is not None, r.stdout)
check("падение: хвост вывода упавшего", "FAIL два  деталь" in r.stdout and "итого: файлов 2, ok 1, FAIL 1" in r.stdout,
      r.stdout)

# --- гибель по сигналу: os._exit не 0 и SIGKILL самого себя ---
p = mkplugin({"test_exit.py": "import os\nprint('ok a')\nos._exit(3)\n",
              "test_kill.py": "import os, signal\nprint('ok a')\nos.kill(os.getpid(), signal.SIGKILL)\n"})
r = run([p])
check("os._exit(3) и SIGKILL файла — раннер не 0", r.returncode != 0 and "код 3" in r.stdout and "сигнал 9" in r.stdout,
      r.stdout)

# --- код 0 без строки итога и итог без проверок ---
p = mkplugin({"test_bare.py": "print('ok   раз')\nprint('ok   два')\n"})
r = run([p])
check("код 0 без итога — раннер не 0", r.returncode != 0 and "код 0 без строки итога" in r.stdout, r.stdout)
p = mkplugin({"test_zero.py": "print('0 из 0 прошли')\n"})
r = run([p])
check("итог «0 из 0» — раннер не 0", r.returncode != 0 and "ни одной проверки" in r.stdout, r.stdout)
p = mkplugin({"test_part.py": "print('ok a')\nprint('1 из 2 прошли')\n"})
r = run([p])
check("код 0 с итогом «1 из 2» — раннер не 0", r.returncode != 0 and "прошли не все" in r.stdout, r.stdout)

# --- ноль файлов: пустая tests/ и папка без tests/ ---
p = mkplugin({"helper.py": "print(1)\n"})
r = run([p])
check("0 файлов — раннер не 0", r.returncode != 0 and "ни одного файла" in r.stdout, r.stdout)
r = run([tempfile.mkdtemp(prefix="empty-")])
check("папка без tests/ — раннер не 0", r.returncode != 0, r.stdout)
r = run([os.path.join(_ROOT, "нет-такой")])
check("несуществующая папка — код 2", r.returncode == 2, r.stdout)
r = run([])
check("без аргументов — код 2", r.returncode == 2, r.stdout)
r = run(["-j", "0", p])
check("-j 0 — отказ, не прогон", r.returncode != 0 and "больше нуля" in r.stdout, r.stdout)

# --- таймаут: файл висит, его внук тоже; оба погашены, раннер не 0 ---
gp = os.path.join(_ROOT, "gpid-timeout")
HANG = ("import subprocess, sys, time\nprint('ok   старт', flush=True)\n"
        "p = subprocess.Popen(['sleep', '120'])\nopen(sys.argv[0] + '.pid', 'w').write('%d %d' % (__import__('os').getpid(), p.pid))\n"
        "time.sleep(120)\n")
p = mkplugin({"test_hang.py": HANG, "test_a.py": OK2})
t0 = time.monotonic()
r = run(["--timeout", "2", p], timeout=60)
sec = time.monotonic() - t0
pids = open(os.path.join(p, "tests", "test_hang.py.pid")).read().split()
check("таймаут: раннер не 0, строка таймаута", r.returncode != 0 and re.search(r"FAIL \S+/test_hang\.py .*таймаут",
                                                                              r.stdout), r.stdout)
check("таймаут: вывод до таймаута в итоге", "ok   старт" in r.stdout, r.stdout)
check("таймаут: раннер не ждёт 120 с", sec < 30, sec)
time.sleep(0.3)
check("таймаут: файл и его внук погашены", not alive(int(pids[0])) and not alive(int(pids[1])), pids)

# --- внук, оставленный после обычного выхода файла, гасится вместе с группой ---
LEAVE = ("import subprocess, sys\np = subprocess.Popen(['sleep', '120'])\n"
         "open(sys.argv[0] + '.pid', 'w').write(str(p.pid))\nprint('ok a')\nprint('1 из 1')\n")
p = mkplugin({"test_leave.py": LEAVE})
r = run([p])
gpid = int(open(os.path.join(p, "tests", "test_leave.py.pid")).read())
time.sleep(0.3)
check("брошенный внук после выхода файла погашен", r.returncode == 0 and not alive(gpid), r.stdout)

# --- окружение файла: свой HOME и TMPDIR, без PANTHEON_*, -I, папка плагина ---
ENVF = ("import os, sys\nprint(repr((os.environ.get('HOME'), os.environ.get('TMPDIR'), "
        "sorted(k for k in os.environ if k.startswith('PANTHEON_')), os.getcwd(), sys.flags.isolated, "
        "os.environ.get('NO_COLOR'), os.environ.get('FORCE_COLOR'))))\nprint('ok a')\nprint('1 из 1')\n")
p = mkplugin({"test_env1.py": ENVF, "test_env2.py": ENVF})
env = dict(os.environ, PANTHEON_STATE="/x", PANTHEON_HOME="/y", FORCE_COLOR="1")
r = run(["--log-dir", os.path.join(_ROOT, "logs-env"), p], env=env)
import ast  # noqa: E402
seen = []
for f in ("test_env1.py", "test_env2.py"):
    with open(os.path.join(_ROOT, "logs-env", os.path.basename(p) + "__" + f + ".log")) as fh:
        seen.append(ast.literal_eval(fh.readline()))
home1, tmp1, pv1, cwd1, iso1, nc1, fc1 = seen[0]
check("окружение: HOME и TMPDIR — свои у каждого файла", home1 != seen[1][0] and tmp1 != seen[1][1]
      and home1 != os.environ.get("HOME") and os.path.isabs(home1), seen)
check("окружение: без PANTHEON_* и FORCE_COLOR, NO_COLOR=1", pv1 == [] and fc1 is None and nc1 == "1", seen)
check("окружение: cwd — папка плагина, флаг -I", os.path.realpath(cwd1) == os.path.realpath(p) and iso1 == 1, seen)
check("окружение: временные папки файлов убраны", not os.path.exists(home1) and not os.path.exists(tmp1), seen)

# --- параллель: три файла по 1.5 с идут одновременно при -j 3, серийный — отдельно ---
SPAN = ("import sys, time\nt0 = time.time()\ntime.sleep(1.5)\n"
        "open(sys.argv[0] + '.span', 'w').write('%f %f' % (t0, time.time()))\nprint('ok a')\nprint('1 из 1')\n")
p = mkplugin({"test_p1.py": SPAN, "test_p2.py": SPAN, "test_p3.py": SPAN, "test_s1.py": SPAN}, "par")
spans = {}
old_serial = R.SERIAL
r = run(["-j", "3", p])
for f in ("test_p1.py", "test_p2.py", "test_p3.py", "test_s1.py"):
    spans[f] = tuple(map(float, open(os.path.join(p, "tests", f + ".span")).read().split()))
starts = sorted(s for s, _ in spans.values())
check("-j 3: три файла идут одновременно", r.returncode == 0 and starts[2] < min(e for _, e in spans.values()),
      (r.stdout, spans))
r = run(["-j", "1", p])
for f in spans:
    spans[f] = tuple(map(float, open(os.path.join(p, "tests", f + ".span")).read().split()))
ss = sorted(spans.values())
check("-j 1: по одному", r.returncode == 0 and all(ss[i][1] <= ss[i + 1][0] for i in range(len(ss) - 1)), ss)

# серийная группа — через сам модуль (SERIAL — список в коде): файлы SERIAL не пересекаются ни с кем
par, ser = R.order([("/x", "par/test_p1.py"), ("/x", "par/test_s1.py"), ("/x", "par/test_p2.py")],
                   slow={"par/test_p2.py": 900}, serial=("par/test_s1.py",))
check("order: медленные первыми, серийные отдельно", [l for _, l in par] == ["par/test_p2.py", "par/test_p1.py"]
      and [l for _, l in ser] == ["par/test_s1.py"], (par, ser))
DRV = ("import importlib.util, sys\nspec = importlib.util.spec_from_file_location('m', sys.argv[1])\n"
       "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\nm.SERIAL = ('par/test_s1.py',)\n"
       "sys.exit(m.main(['-j', '3', sys.argv[2]]))\n")
r = subprocess.run([sys.executable, "-I", "-c", DRV, RUNNER, p], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                   text=True, timeout=120)
for f in spans:
    spans[f] = tuple(map(float, open(os.path.join(p, "tests", f + ".span")).read().split()))
s1 = spans["test_s1.py"]
others = [v for k, v in spans.items() if k != "test_s1.py"]
check("серийный файл идёт один, после параллельных", r.returncode == 0 and all(e <= s1[0] for _, e in others)
      and max(s for s, _ in others) < min(e for _, e in others), (r.stdout, spans))

# --- число воркеров ---
check("workers: 8 ядер — 3", R.workers(8, 1.0) == 3)
check("workers: 4 ядра — 2", R.workers(4, 0.5) == 2)
check("workers: 2 ядра и 1 ядро — 1", R.workers(2, 0.1) == 1 and R.workers(1, 0) == 1 and R.workers(None, None) == 1)
check("workers: load1 выше ядер — 1", R.workers(8, 8.5) == 1 and R.workers(8, 8.0) == 3)
check("workers: load неизвестен — по ядрам", R.workers(16, None) == 3)

# --- итог файла: проверки и плохие итоги ---
check("checks: «N из M» — M", R.checks("ok a\nok b\n2 из 3\n")[1] == 3)
check("checks: без числа в итоге — строки ok", R.checks("ok a\nok b\nПРОВАЛ: x\n")[:2] == (True, 2))
check("checks: «тестов: 3 прошло, 1 не прошло» — 4", R.checks("тестов: 3 прошло, 1 не прошло\n")[1] == 4)
check("checks: ANSI не мешает итогу", R.checks("\x1b[32mok a\x1b[0m\n\x1b[1m1 из 1\x1b[0m\n") == (True, 1, None))
check("verdict: код 0 с ПРОВАЛ — не ok", R.verdict(0, "ok a\nПРОВАЛ: b\n", False)[0] is False)
check("verdict: код 0, «1/1» — ok", R.verdict(0, "ok a\n1/1\n", False) == (True, None, 1))

# --- копия итоговых регулярок совпадает с pantheon.py (импортировать его на 3.9 нельзя) ---
src = open(os.path.join(PLUGIN, "lib", "pantheon.py"), encoding="utf-8").read()
m = re.search(r'^TEST_SUMMARY = re\.compile\(r"(.*)"\)$', src, re.M)
check("TEST_SUMMARY — как в pantheon.py", m is not None and m.group(1) == R.TEST_SUMMARY.pattern, m and m.group(1))
m = re.search(r"^_SUMMARY_TOTAL = \(\n(.*?)\n\)$", src, re.M | re.S)
pats = re.findall(r're\.compile\(r"(.*?)"\)', m.group(1)) if m else []
check("_SUMMARY_TOTAL — как в pantheon.py", pats == [rx.pattern for rx, _ in R._SUMMARY_TOTAL], pats)
m = re.search(r'^ANSI = re\.compile\(r"(.*)"\)$', src, re.M)
check("ANSI — как в pantheon.py", m is not None and m.group(1) == R.ANSI.pattern)

# --- сигналы: раннер в своей сессии, как задача run_job; killpg TERM/HUP/INT, через 5 с SIGKILL; сирот нет ---
for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
    p = mkplugin({"test_hang.py": HANG, "test_hang2.py": HANG, "test_a.py": OK2})
    job = subprocess.Popen([sys.executable, "-I", RUNNER, "-j", "3", p], start_new_session=True,
                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    got = [wait_file(os.path.join(p, "tests", f + ".pid")) for f in ("test_hang.py", "test_hang2.py")]
    if None in got:
        check(f"{sig.name}: файлы тестов запустились", False, got)
        os.killpg(job.pid, signal.SIGKILL)
        continue
    pids = [int(x) for g in got for x in g.split()]
    t0 = time.monotonic()
    os.killpg(job.pid, sig)  # как run_job: группе задачи
    try:
        out = job.communicate(timeout=5)[0].decode()
    except subprocess.TimeoutExpired:
        os.killpg(job.pid, signal.SIGKILL)
        out = job.communicate()[0].decode()
    time.sleep(0.3)
    check(f"{sig.name}: раннер вышел сам за 5 с с кодом 128+{int(sig)}",
          job.returncode == 128 + int(sig) and time.monotonic() - t0 < 5, (job.returncode, out))
    check(f"{sig.name}: строка о прерывании последней", out.strip().splitlines()[-1].startswith("run-tests: прерван"),
          out)
    left = [x for x in pids if alive(x)]
    check(f"{sig.name}: ни файлов тестов, ни внуков", not left, (left, out))
    for x in left:
        try:
            os.kill(x, signal.SIGKILL)
        except ProcessLookupError:
            pass

# --- сигнал только раннеру (heavy передаёт его процессу, а не группе) ---
p = mkplugin({"test_hang.py": HANG})
job = subprocess.Popen([sys.executable, "-I", RUNNER, p], start_new_session=True, stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
got = wait_file(os.path.join(p, "tests", "test_hang.py.pid"))
pids = [int(x) for x in (got or "").split()]
os.kill(job.pid, signal.SIGTERM)
try:
    out = job.communicate(timeout=5)[0].decode()
except subprocess.TimeoutExpired:
    os.killpg(job.pid, signal.SIGKILL)
    out = job.communicate()[0].decode()
time.sleep(0.3)
check("SIGTERM одному раннеру: код 143, файл и внук погашены", job.returncode == 143 and pids
      and not any(alive(x) for x in pids), (job.returncode, pids, out))

print(f"\n{total - len(fails)} из {total} прошли")
sys.exit(1 if fails else 0)
