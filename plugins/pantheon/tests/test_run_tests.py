#!/usr/bin/env python3
"""Параллельный раннер файлов тестов scripts/run-tests.py (metis-0450).

Запуск: python3 -I plugins/pantheon/tests/test_run_tests.py  (код выхода 0 — все прошли). Фальшивые плагины во временной папке: зелёный, падающий, зависающий, без итога, без файлов;
раннер в своей сессии, как задача run_job, гасится SIGTERM / SIGHUP / SIGINT — ни файла тестов, ни его внука после."""
import ast
import atexit
import hashlib
import importlib.util
import json
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

# --- упавшая проверка в середине длинного вывода видна в итоге, строки ok — нет (metis-0719) ---
p = mkplugin({"test_long.py": "for i in range(100): print(f'ok   до {i}')\nprint('FAIL середина  деталь')\n"
              "for i in range(100): print(f'ok   после {i}')\nprint('200 из 201')\nraise SystemExit(1)\n"})
r = run([p])
sect = r.stdout.split("===== ", 1)[-1]
check("падение в середине: FAIL-строка и итог файла в разделе упавшего",
      "FAIL середина  деталь" in sect and "200 из 201" in sect and "строки не ok: 2" in sect, r.stdout)
check("падение в середине: строк ok в разделе упавшего нет", "ok   после 99" not in sect and "ok   до 0" not in sect,
      r.stdout)
lines, n = R.not_ok("\n".join(f"FAIL {i}" for i in range(10)) + "\nok x\n\n", limit=4)
check("not_ok: больше предела — начало, пропуск, конец",
      n == 10 and lines == ["FAIL 0", "FAIL 1", "… пропущено 6 строк …", "FAIL 8", "FAIL 9"], lines)
check("not_ok: в пределе — все не-ok по порядку, ANSI снят",
      R.not_ok("\x1b[31mFAIL a\x1b[0m\nok b\n  ok c\nTraceback\n") == (["FAIL a", "Traceback"], 2))

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
check("папка без tests/ — код 2 и строка про tests", r.returncode == 2 and "tests" in r.stdout, r.stdout)
okp = mkplugin({"test_a.py": OK2})
r = run([okp, tempfile.mkdtemp(prefix="notests-")])
check("рядом с папкой без tests/ зелёная папка — всё равно код 2, ничего не пропущено молча",
      r.returncode == 2 and "ok   " not in r.stdout, r.stdout)
r = run([os.path.join(_ROOT, "нет-такой")])
check("несуществующая папка — код 2", r.returncode == 2, r.stdout)
r = run([])
check("без аргументов — код 2", r.returncode == 2, r.stdout)
r = run(["-j", "0", p])
check("-j 0 — отказ, не прогон", r.returncode != 0 and "больше нуля" in r.stdout, r.stdout)
for bad_args, word in ((["--bogus", p], "неизвестный ключ"), (["-j"], "без значения"), (["-j", "abc", p], "не число")):
    r = run(bad_args)
    check(f"ключи {' '.join(bad_args[:2])} — отказ без прогона", r.returncode != 0 and word in r.stdout
          and "файлов" not in r.stdout, r.stdout)

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

# --- пул multiprocessing (spawn), брошенный файлом: воркеры и resource_tracker гаснут с группой (metis-0568) ---
# файл выходит os._exit(0) без shutdown пула — как упавший или убитый: без killpg группы его воркеры и resource_tracker
# остаются сиротами с ppid 1 (СБ 28.10: ~40 таких по 4–11 дней от прогонов тестов)
MP = ("import os, sys, multiprocessing as mp\nfrom concurrent.futures import ProcessPoolExecutor\n"
      "def f(x):\n    return os.getpid()\n"
      "if __name__ == '__main__':\n"
      "    pool = ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn'))\n"
      "    list(pool.map(f, range(8)))\n"
      "    from multiprocessing import resource_tracker\n    resource_tracker.ensure_running()\n"
      "    rt = resource_tracker._resource_tracker._pid\n"
      "    open(sys.argv[0] + '.pid', 'w').write(' '.join(map(str, list(pool._processes) + [rt or 0])))\n"
      "    print('ok a'); print('1 из 1', flush=True)\n    os._exit(0)\n")
try:  # песочница окна роли не даёт семафоры: ProcessPoolExecutor там падает на sysconf (metis-0666)
    os.sysconf("SC_SEM_NSEMS_MAX")
    _sem = True
except PermissionError:
    _sem = False
if not _sem:
    print("пропущено: песочница окна не даёт семафоры — пул multiprocessing после выхода файла")
else:
    p = mkplugin({"test_mp.py": MP})
    r = run([p])
    mp_pids = [int(x) for x in open(os.path.join(p, "tests", "test_mp.py.pid")).read().split() if x != "0"]
    time.sleep(0.5)
    left = [x for x in mp_pids if alive(x)]
    for x in left:  # не оставлять сирот и при провале проверки
        try:
            os.kill(x, signal.SIGKILL)
        except OSError:
            pass
    check("пул multiprocessing после выхода файла: воркеры и resource_tracker погашены",
          r.returncode == 0 and len(mp_pids) >= 2 and not left, (r.stdout, mp_pids, left))

# --- окружение файла: свой HOME и TMPDIR, без PANTHEON_*, -I, папка плагина ---
ENVF = ("import os, sys\nprint(repr((os.environ.get('HOME'), os.environ.get('TMPDIR'), "
        "sorted(k for k in os.environ if k.startswith('PANTHEON_')), os.getcwd(), sys.flags.isolated, "
        "os.environ.get('NO_COLOR'), os.environ.get('FORCE_COLOR'))))\nprint('ok a')\nprint('1 из 1')\n")
p = mkplugin({"test_env1.py": ENVF, "test_env2.py": ENVF})
env = dict(os.environ, PANTHEON_STATE="/x", PANTHEON_HOME="/y", FORCE_COLOR="1")
r = run(["--log-dir", os.path.join(_ROOT, "logs-env"), p], env=env)
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
# --- явный провал в выводе при коде 0 (metis-0556) ---
for nm, body in (("FAIL <имя>", "ok a\nFAIL b  деталь\n2/2\n"), ("НЕ ПРОШЛО", "ok a\nНЕ ПРОШЛО: b\n1/1\n"),
                 ("Traceback", "ok a\nTraceback (most recent call last):\n  File x\n1/1\n"),
                 ("«не прошло: 2»", "ok a\nне прошло: 2\n1/1\n"), ("«FAIL 3»", "ok a\nFAIL 3\n"),
                 ("«2 не прошло»", "ok a\nтестов: 3 прошло, 2 не прошло\n"),
                 ("с ANSI", "ok a\n\x1b[31mFAIL b\x1b[0m\n1/1\n")):
    v = R.verdict(0, body, False)
    check(f"verdict: код 0 с {nm} — красный", v[0] is False and "в выводе" in (v[1] or ""), v)
for nm, body in (("«не прошло: 0»", "ok a\nне прошло: 0\n1/1\n"), ("«FAIL 0»", "ok a\nFAIL 0\n"),
                 ("FAIL внутри имени", "ok test_FAIL_case\nok a FAIL b\n2/2\n"),
                 ("«0 не прошло»", "ok a\nтестов: 3 прошло, 0 не прошло\n"),
                 ("Traceback в середине строки", "ok a  # ожидаемый Traceback (most recent call last)\n1/1\n"),
                 ("строка ok с «1 не прошло» в имени", "ok checks: «3 прошло, 1 не прошло» — 4\n4/4\n"),
                 ("«FAILED» без пробела", "ok a\nok FAILURE-mode\n1/1\n")):
    v = R.verdict(0, body, False)
    check(f"verdict: код 0 с {nm} — не ложное срабатывание", v[0] is True, v)
p = mkplugin({"test_lie.py": "print('ok a')\nprint('FAIL b  деталь')\nprint('2/2')\n"})
r = run([p])
check("раннер: файл с кодом 0 и строкой FAIL — красный, код 1", r.returncode == 1 and "в выводе строка FAIL" in r.stdout, r.stdout)
NS = frozenset({"g/test_old.py"})
check("verdict: старый файл без итога из списка — ok", R.verdict(0, "ok a\nok b\n", False, "g/test_old.py", NS)
      == (True, None, 2))
check("verdict: файл без итога не из списка — не ok", R.verdict(0, "ok a\n", False, "g/test_new.py", NS)[0] is False)
check("verdict: из списка, но со строкой FAIL — не ok",
      R.verdict(0, "ok a\nFAIL b  x\nok c\n", False, "g/test_old.py", NS)[0] is False)
check("verdict: из списка, без строк ok — не ok", R.verdict(0, "привет\n", False, "g/test_old.py", NS)[0] is False)
check("verdict: из списка, код 1 — не ok", R.verdict(1, "ok a\n", False, "g/test_old.py", NS)[0] is False)
missing = [lb for lb in tuple(R.NO_SUMMARY) + tuple(R.SLOW) + tuple(R.SERIAL) if not os.path.exists(
    os.path.join(os.path.dirname(PLUGIN), lb.split("/")[0], "tests", lb.split("/")[1]))]
check("NO_SUMMARY, SLOW, SERIAL — только существующие файлы", not missing, missing)

# --- карантин (metis-1050): упавший файл из QUARANTINE — строка «карантин», код прогона 0; другой FAIL — код 1 ---
missing = [lb for lb, task in R.QUARANTINE.items() if not re.fullmatch(r"metis-\d{4}", task) or not os.path.exists(
    os.path.join(os.path.dirname(PLUGIN), lb.split("/")[0], "tests", lb.split("/")[1]))]
check("QUARANTINE — существующие файлы, у каждого задача metis-NNNN", R.QUARANTINE and not missing, missing)


def _core_names():
    """Ядро защит — CORE_FILES и CORE_DIR из lib/merge.py (зеркало шлюза guard, сверяет test_merge) → (папки плагинов
    целиком, основы имён файлов ядра и папок ядра внутри плагинов)."""
    with open(os.path.join(PLUGIN, "lib", "merge.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    got = {t.id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
           for t in n.targets if isinstance(t, ast.Name) and t.id in ("CORE_FILES", "CORE_DIR")}
    whole = {d.split("/")[1] for d in got["CORE_DIR"] if d.count("/") == 1 and d.startswith("plugins/")}
    stems = {os.path.splitext(os.path.basename(f))[0].replace("-", "_").replace(".", "_") for f in got["CORE_FILES"]}
    stems |= {os.path.basename(d) for d in got["CORE_DIR"] if d.count("/") > 1}
    return whole, stems


def core_quarantine(labels):
    """Метки карантина, которым там не место (metis-1068): файлы плагина-ядра целиком (guard/*) и тесты файлов ядра —
    test_<основа>.py и test_<основа>_*.py для файла или папки ядра (merge.py → test_merge.py, ctx.py →
    test_ctx_clock.py, roles → test_roles_harness.py). Их настоящее падение карантин спрятал бы, а слияние ядра держит
    защиту."""
    whole, stems = _core_names()
    bad = []
    for lb in labels:
        plugin, name = lb.split("/", 1)
        stem = name[len("test_"):-len(".py")] if name.startswith("test_") and name.endswith(".py") else ""
        if plugin in whole or any(stem == s or stem.startswith(s + "_") for s in stems):
            bad.append(lb)
    return bad


check("core_quarantine: guard/*, тесты файлов ядра — найдены; test_outside_idle — нет (проверка не пустая)",
      core_quarantine(["guard/test_x.py", "pantheon/test_merge.py", "pantheon/test_ctx_clock.py",
                       "pantheon/test_window_rules.py", "pantheon/test_roles_harness.py", "pantheon/test_answers.py",
                       "pantheon/test_outside_idle.py", "pantheon/test_merger.py"])
      == ["guard/test_x.py", "pantheon/test_merge.py", "pantheon/test_ctx_clock.py", "pantheon/test_window_rules.py",
          "pantheon/test_roles_harness.py", "pantheon/test_answers.py"], _core_names())
check("QUARANTINE — без меток guard/* и тестов файлов ядра (metis-1068)", not core_quarantine(R.QUARANTINE),
      core_quarantine(R.QUARANTINE))
qlabel = next(iter(R.QUARANTINE))
qp = mkplugin({qlabel.split("/")[1]: "import sys\nprint('ok   a')\nsys.exit(1)\n", "test_fine.py": OK2},
              qlabel.split("/")[0])
r = run([qp])
check("карантин: файл из списка упал — строка «карантин … задача», итог «карантин 1», код 0",
      r.returncode == 0 and f"карантин {qlabel}" in r.stdout and f"задача {R.QUARANTINE[qlabel]}" in r.stdout
      and "FAIL 0, карантин 1" in r.stdout, r.stdout)
qp2 = mkplugin({qlabel.split("/")[1]: "import sys\nprint('ok   a')\nsys.exit(1)\n",
                "test_bad.py": "import sys\nprint('ok   a')\nsys.exit(1)\n"}, qlabel.split("/")[0])
r = run([qp2])
check("карантин: рядом упал файл не из списка — код 1, FAIL 1", r.returncode == 1 and "FAIL 1, карантин 1" in r.stdout,
      r.stdout)

# --- --affected: карта affected-map.json и выбор по ней (metis-0451) ---
REPO = os.path.dirname(os.path.dirname(PLUGIN))
amap, why = R.load_map()
check("карта репозитория читается, версия та", amap is not None, why)
amap = amap or {"tests": set(), "always": set(), "files": {}}
try:
    with open(R.MAP, encoding="utf-8") as fh:
        RAWMAP = json.load(fh)
except (OSError, ValueError):
    RAWMAP = {}
# сам этот файл в копии сборки проверяет прошлую карту: упал он в прошлой сборке — упадёт и в этой, если не исключить
check("карта: при сборке не упал ни один файл тестов",
      not set(RAWMAP.get("broken") or ()) - {"pantheon/test_run_tests.py"}, RAWMAP.get("broken"))
# metis-0791: правка bin/heavy — только тесты, что его запускают; линтер словаря читает heavy, но он в readers
HEAVY = amap["files"].get("plugins/pantheon/bin/heavy", set())
check("карта: bin/heavy → test_heavy_queue, не больше 12 тестов, без линтеров и test_watch (было 33)",
      "pantheon/test_heavy_queue.py" in HEAVY and len(HEAVY) <= 12
      and not HEAVY & {"pantheon/test_glossary.py", "pantheon/test_watch.py"}, sorted(HEAVY))
check("карта: readers — test_glossary (читает дерево), идёт всегда",
      "pantheon/test_glossary.py" in (RAWMAP.get("readers") or ()) and "pantheon/test_glossary.py" in amap["always"],
      RAWMAP.get("readers"))
check("FULL: lib/pantheon.py, hooks/python.sh обоих плагинов, сам раннер — общие",
      {"plugins/pantheon/lib/pantheon.py", "plugins/pantheon/hooks/python.sh", "plugins/guard/hooks/python.sh",
       "plugins/pantheon/scripts/run-tests.py"} <= R.FULL)
gone = sorted(p for p in R.FULL if not os.path.isfile(os.path.join(REPO, p)))
check("FULL: только существующие файлы", not gone, gone)
# карта по прогону видит ленивую загрузку: watch.py грузит pantheon.py по требованию, по тексту test_tick его не зовёт
for path, lb in (("plugins/pantheon/lib/watch.py", "pantheon/test_watch.py"),
                 ("plugins/guard/hooks/guard.py", "guard/test_guard.py"),
                 ("plugins/guard/hooks/merge_gate.py", "guard/test_merge_gate.py"),
                 ("plugins/project-tools/lib/project_tools.py", "project-tools/test_project_tools.py")):
    check(f"карта: {path} → {lb}", lb in amap["files"].get(path, ()), sorted(amap["files"].get(path, ())))
check("карта: AGENTS.md не задевает ни один тест", amap["files"].get("AGENTS.md") == set(),
      amap["files"].get("AGENTS.md"))


def mkmap(tests, files, broken=(), version=3, hashes=None, readers=()):
    p = os.path.join(tempfile.mkdtemp(prefix="map-"), "m.json")
    idx = {lb: i for i, lb in enumerate(tests)}
    with open(p, "w") as fh:
        json.dump({"version": version, "tests": list(tests), "broken": list(broken), "readers": list(readers),
                   "hashes": {lb: "0" for lb in tests} if hashes is None else hashes,
                   "files": {k: [idx[x] for x in v] for k, v in files.items()}}, fh)
    return p


ITEMS = [("/r/plugins/alpha", "alpha/test_x.py"), ("/r/plugins/alpha", "alpha/test_y.py"),
         ("/r/plugins/beta", "beta/test_b.py")]
MT = ["alpha/test_x.py", "alpha/test_y.py", "beta/test_b.py", "alpha/test_z.py", "gamma/test_g.py"]
AM, _ = R.load_map(mkmap(MT, {"plugins/alpha/lib/x.py": ["alpha/test_x.py"], "README.md": [],
                              "plugins/alpha/lib/z.py": ["alpha/test_z.py"], "plugins/gamma/g.py": ["gamma/test_g.py"],
                              "plugins/alpha/tests/_helper.py": ["alpha/test_y.py"]}))
check("load_map: метки по номерам", AM and AM["files"]["plugins/alpha/lib/x.py"] == {"alpha/test_x.py"}, AM)
sel = R.select(["plugins/alpha/lib/x.py"], "/r", ITEMS, AM)
check("select: файл из карты — только его тесты", sel == ([ITEMS[0]], [], []), sel)
sel = R.select(["plugins/alpha/tests/_helper.py"], "/r", ITEMS, AM)
check("select: помощник тестов из карты — его тесты", sel == ([ITEMS[1]], [], []), sel)
sel = R.select(["plugins/beta/tests/test_b.py"], "/r", ITEMS, AM)
check("select: правка файла тестов — он сам", sel == ([ITEMS[2]], [], []), sel)
sel = R.select(["plugins/alpha/tests/test_gone.py"], "/r", ITEMS, AM)
check("select: удалённый файл тестов — ничего", sel == ([], [], []), sel)
sel = R.select(["README.md"], "/r", ITEMS, AM)
check("select: только README (пустой список) — ничего", sel == ([], [], []), sel)
sel = R.select(["plugins/gamma/g.py"], "/r", ITEMS, AM)
check("select: тесты плагина не из аргументов — ничего", sel == ([], [], []), sel)
sel = R.select(["plugins/alpha/lib/z.py"], "/r", ITEMS, AM)
check("select: карта называет удалённый файл тестов — ничего", sel == ([], [], []), sel)
for path, why in (("plugins/alpha/lib/y.py", "нет в карте"), ("plugins/alpha/tests/_other.py", "нет в карте"),
                  ("plugins/pantheon/lib/pantheon.py", "общий файл"), ("plugins/guard/hooks/python.sh", "общий файл"),
                  ("plugins/pantheon/scripts/run-tests.py", "общий файл")):
    sel = R.select(["plugins/alpha/lib/x.py", path], "/r", ITEMS, AM)
    check(f"select: {path} — весь набор ({why})", sel[0] is None and sel[1] and sel[1][0][0] == path
          and why in sel[1][0][1], sel)
AM2, _ = R.load_map(mkmap(MT[:2], {"plugins/alpha/lib/x.py": ["alpha/test_x.py"], "README.md": []},
                          broken=["alpha/test_y.py"]))
sel = R.select(["plugins/alpha/lib/x.py"], "/r", ITEMS, AM2)
check("select: новый файл тестов (карта не знает) и упавший при сборке — всегда",
      sel == (ITEMS, [], ["alpha/test_y.py", "beta/test_b.py"]), sel)
sel = R.select(["README.md"], "/r", ITEMS, AM2)
check("select: ничего не задето — «всегда» (не из карты, упавшие при сборке) всё равно идут",
      sel == ([ITEMS[1], ITEMS[2]], [], ["alpha/test_y.py", "beta/test_b.py"]), sel)
# metis-0791: читающий дерево (readers) — всегда, даже когда правка (README) ни одного теста не задела; его связей в
# files нет, поэтому правка файла, который он только читал, не тянет других
AM3, _ = R.load_map(mkmap(MT[:3], {"plugins/alpha/lib/x.py": ["alpha/test_x.py"], "README.md": []},
                          readers=["beta/test_b.py"]))
sel = R.select(["README.md"], "/r", ITEMS, AM3)
check("select: readers идут при любой правке, в том числе README", sel == ([ITEMS[2]], [], ["beta/test_b.py"]), sel)
sel = R.select(["plugins/alpha/lib/x.py"], "/r", ITEMS, AM3)
check("select: правка x.py — его тест и readers, test_y — нет", sel == ([ITEMS[0], ITEMS[2]], [], ["beta/test_b.py"]),
      sel)
for body, why in (("{", "JSONDecodeError"), ('{"version": 2, "tests": [], "files": {}}', "версии 2"),
                  ('{"version": 1, "tests": [], "files": {}}', "версии 1"),
                  ('{"version": 3, "hashes": {}, "tests": ["a/test_a.py"], "files": {"x": [5]}}', "IndexError"),
                  ('{"version": 3, "tests": [], "files": {}}', "KeyError"),
                  ('{"version": 3, "files": {}}', "KeyError"), ("[]", "AttributeError")):
    p = os.path.join(tempfile.mkdtemp(prefix="map-"), "m.json")
    with open(p, "w") as fh:
        fh.write(body)
    got = R.load_map(p)
    check(f"load_map: {body[:30]} — нет карты ({why})", got[0] is None and why in got[1], got)
got = R.load_map("/нет/такой/карты.json")
check("load_map: нет файла — нет карты", got[0] is None and "не прочесть" in got[1], got)

# сквозная проба: временный репозиторий, своя карта через MAP модуля
GENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
            GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, env=GENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, check=True).stdout


def put(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)


repo = tempfile.mkdtemp(prefix="repo-")
al = os.path.join(repo, "plugins", "alpha")
put(os.path.join(repo, "README.md"), "# r\n")
put(os.path.join(al, "lib", "x.py"), "X = 1\n")
put(os.path.join(al, "lib", "y.py"), "Y = 1\n")
put(os.path.join(al, "tests", "test_x.py"), OK2)
put(os.path.join(al, "tests", "test_y.py"), OK2)
git(repo, "init", "-q", "-b", "main")
git(repo, "add", "-A")
git(repo, "commit", "-q", "-m", "база")
git(repo, "checkout", "-q", "-b", "work")
OK2H = hashlib.sha256(OK2.encode()).hexdigest()
MAPF = mkmap(["alpha/test_x.py", "alpha/test_y.py"], {"plugins/alpha/lib/x.py": ["alpha/test_x.py"], "README.md": [],
                                                      "plugins/alpha/lib/y.py": ["alpha/test_y.py"]},
             hashes={"alpha/test_x.py": OK2H, "alpha/test_y.py": OK2H})
DRV_AFF = ("import importlib.util, sys\nspec = importlib.util.spec_from_file_location('m', sys.argv[1])\n"
           "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
           "m.MAP = sys.argv[2]\nsys.exit(m.main(sys.argv[3:]))\n")


def run_aff(*args, mapf=MAPF):
    return subprocess.run([sys.executable, "-I", "-c", DRV_AFF, RUNNER, mapf, *args], env=GENV,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)


r = run_aff("--affected", "--base", "main", al)
check("--affected: изменений нет — код 3, «нечего гонять», без прогона", r.returncode == 3
      and "изменений нет — нечего гонять" in r.stdout and "итого" not in r.stdout, r.stdout)
put(os.path.join(repo, "README.md"), "# r\nправка\n")
r = run_aff("--affected", "--base", "main", al)
check("--affected: только README — код 3, «нечего гонять», без прогона", r.returncode == 3
      and "нечего гонять" in r.stdout and "README.md" in r.stdout and "итого" not in r.stdout, r.stdout)
check("--affected: причина — последней строкой", r.stdout.strip().splitlines()[-1].startswith("run-tests: затронутое"),
      r.stdout)
put(os.path.join(al, "lib", "x.py"), "X = 2\n")
git(repo, "commit", "-q", "-am", "x")
r = run_aff("--affected", "--base", "main", al)
check("--affected: закоммиченная правка x.py — только test_x", r.returncode == 0 and "тестов 1 из 2" in r.stdout
      and "alpha/test_x.py" in r.stdout and "test_y.py" not in r.stdout and "файлов 1, ok 1" in r.stdout, r.stdout)
put(os.path.join(al, "tests", "test_new.py"), OK2)
r = run_aff("--affected", "--base", "main", al)
check("--affected: новый файл тестов — он сам и затронутое", r.returncode == 0 and "тестов 2 из 3" in r.stdout
      and "alpha/test_new.py" in r.stdout and "test_y.py" not in r.stdout, r.stdout)
os.remove(os.path.join(al, "tests", "test_new.py"))
put(os.path.join(al, "lib", "new.py"), "N = 1\n")
r = run_aff("--affected", "--base", "main", al)
check("--affected: новый файл вне карты — весь набор", r.returncode == 0 and "lib/new.py — нет в карте" in r.stdout
      and "весь набор" in r.stdout and "файлов 2, ok 2" in r.stdout, r.stdout)
os.remove(os.path.join(al, "lib", "new.py"))
os.remove(os.path.join(al, "lib", "y.py"))
r = run_aff("--affected", "--base", "main", al)
check("--affected: удалённый файл из карты — его тесты", r.returncode == 0 and "тестов 2 из 2" in r.stdout, r.stdout)
git(repo, "checkout", "-q", "--", "plugins/alpha/lib/y.py")
r = run_aff("--affected", "--base", "main", al, mapf="/нет/карты.json")
check("--affected: карты нет — весь набор, причина строкой", r.returncode == 0 and "не прочесть" in r.stdout
      and "весь набор" in r.stdout and "файлов 2, ok 2" in r.stdout, r.stdout)
r = run_aff(al)
check("без --affected — полный прогон, как раньше", r.returncode == 0 and "файлов 2, ok 2" in r.stdout
      and "затронутое" not in r.stdout, r.stdout)
r = run_aff("--affected", "--base", "нет-такой-ветки", al)
check("--affected: нет базы — весь набор, причина строкой", r.returncode == 0
      and "изменённые файлы не получить" in r.stdout and "весь набор" in r.stdout and "файлов 2, ok 2" in r.stdout,
      r.stdout)
r = run_aff("--affected", "--base", "main", mkplugin({"test_a.py": OK2}))
check("--affected вне репозитория git — весь набор", r.returncode == 0 and "не получить" in r.stdout
      and "файлов 1, ok 1" in r.stdout, r.stdout)
put(os.path.join(al, "tests", "test_bad.py"), "import sys\nprint('ok   a')\nsys.exit(1)\n")
r = run_aff("--affected", "--base", "main", al)
check("--affected: упавший затронутый файл — код 1", r.returncode == 1 and "FAIL alpha/test_bad.py" in r.stdout,
      r.stdout)
os.remove(os.path.join(al, "tests", "test_bad.py"))
r = run(["--base", "main", al])
check("--base без --affected — отказ без прогона", r.returncode != 0 and "--base без --affected" in r.stdout
      and "файлов" not in r.stdout, r.stdout)

# --- --only: только названные файлы (дозапуск прохода outside, metis-0735) ---
r = run(["--only", "alpha/test_b.py,beta/test_c.py", a, b])
check("--only: идут только названные файлы двух плагинов",
      r.returncode == 0 and "файлов 2, ok 2, FAIL 0" in r.stdout and "alpha/test_a.py" not in r.stdout
      and "ok   alpha/test_b.py" in r.stdout and "ok   beta/test_c.py" in r.stdout, r.stdout)
r = run(["--only", "alpha/test_b.py", "--only", "beta/test_c.py", a, b])
check("--only дважды — объединение", r.returncode == 0 and "файлов 2, ok 2" in r.stdout, r.stdout)
r = run(["--only", "alpha/test_b.py,alpha/test_zz.py", a, b])
check("--only: метки нет среди файлов — код 2 без прогона", r.returncode == 2 and "alpha/test_zz.py" in r.stdout
      and "итого" not in r.stdout, r.stdout)
r = run(["--only", "alpha/test_b.py,", a])
check("--only: пустая метка — отказ без прогона", r.returncode not in (0, 2) and "пустая метка" in r.stdout
      and "итого" not in r.stdout, r.stdout)
r = run(["--only", "alpha/test_b.py", "--affected", a])
check("--only с --affected — отказ без прогона", r.returncode != 0 and "--only с --affected" in r.stdout
      and "итого" not in r.stdout, r.stdout)

# --- устаревшая карта: файл тестов, изменённый после её сборки, идёт всегда (хеши в карте) ---
Y2 = OK2 + "# правка после сборки карты\n"
put(os.path.join(al, "tests", "test_y.py"), Y2)
git(repo, "commit", "-q", "-am", "правка теста после карты")
git(repo, "branch", "b2")  # база — после правки теста: в diff от неё test_y уже нет, а карта его хеш не знает
put(os.path.join(al, "lib", "x.py"), "X = 3\n")
r = run_aff("--affected", "--base", "b2", al)
check("устаревшая карта: правка x.py — идёт и test_x, и test_y (изменён после сборки), причина в выводе",
      r.returncode == 0 and "тестов 2 из 2" in r.stdout and "изменены после сборки карты" in r.stdout
      and "alpha/test_y.py" in r.stdout and "файлов 2, ok 2" in r.stdout, r.stdout)
MAPOK = mkmap(["alpha/test_x.py", "alpha/test_y.py"], {"plugins/alpha/lib/x.py": ["alpha/test_x.py"], "README.md": [],
                                                       "plugins/alpha/lib/y.py": ["alpha/test_y.py"]},
              hashes={"alpha/test_x.py": OK2H, "alpha/test_y.py": hashlib.sha256(Y2.encode()).hexdigest()})
r = run_aff("--affected", "--base", "b2", al, mapf=MAPOK)
check("карта с теми же хешами: устаревших нет, идёт только test_x", r.returncode == 0 and "тестов 1 из 2" in r.stdout
      and "изменены после сборки" not in r.stdout and "файлов 1, ok 1" in r.stdout, r.stdout)
git(repo, "checkout", "-q", "--", "plugins/alpha/lib/x.py")
put(os.path.join(repo, "README.md"), "# только текст\n")
r = run_aff("--affected", "--base", "b2", al)
check("устаревшая карта: даже правка README гонит test_y (он мог начать читать README), test_x — нет",
      r.returncode == 0 and "тестов 1 из 2" in r.stdout and "изменены после сборки карты" in r.stdout
      and "файлов 1, ok 1" in r.stdout and "ok   alpha/test_y.py" in r.stdout, r.stdout)
r = run_aff("--affected", "--base", "b2", al, mapf=MAPOK)
check("карта с теми же хешами: README ничего не задевает — нечего гонять, код 3",
      r.returncode == 3 and "нечего гонять" in r.stdout, (r.returncode, r.stdout))
git(repo, "checkout", "-q", "--", "README.md")
SI = [("/r/plugins/alpha", "alpha/test_x.py"), ("/r/plugins/alpha", "alpha/test_y.py")]
SM = R.load_map(mkmap(["alpha/test_x.py", "alpha/test_y.py"], {"README.md": [], "plugins/alpha/lib/x.py": ["alpha/test_x.py"]}))[0]
sel = R.select(["README.md"], "/r", SI, SM, stale=["alpha/test_y.py"])
check("select: ничего не задето, но test_y устарел — идёт он", sel == ([SI[1]], [], []), sel)
sel = R.select(["plugins/alpha/lib/x.py"], "/r", SI, SM, stale=["alpha/test_y.py", "gamma/test_g.py"])
check("select: устаревший идёт вместе с затронутым, метка не из набора игнорируется", sel == (SI, [], []), sel)
sdir = mkplugin({"test_a.py": OK2, "test_b.py": OK2 + "# другой\n"}, "alpha")
sitems = [(sdir, "alpha/test_a.py"), (sdir, "alpha/test_b.py"), (sdir, "alpha/test_c.py")]
sm = R.load_map(mkmap(["alpha/test_a.py", "alpha/test_b.py"], {}, hashes={"alpha/test_a.py": OK2H, "alpha/test_b.py": "не тот"}))[0]
check("stale_tests: хеш другой — устарел; хеш тот же и файл, которого нет в карте, — нет",
      R.stale_tests(sitems, sm) == ["alpha/test_b.py"], R.stale_tests(sitems, sm))
sm = R.load_map(mkmap(["alpha/test_a.py", "alpha/test_b.py"], {}, hashes={}))[0]
check("stale_tests: в карте нет хеша файла — устарел", R.stale_tests(sitems, sm) == ["alpha/test_a.py", "alpha/test_b.py"],
      R.stale_tests(sitems, sm))
check("test_hash: sha256 содержимого; нет файла — None",
      R.test_hash(sdir, "alpha/test_a.py") == OK2H and R.test_hash(sdir, "alpha/test_zzz.py") is None)
# много устаревших (metis-0782): весь набор не из-за них — идут все устаревшие и затронутый, без «карта устарела»
N_STALE = 9
many = {f"test_{i}.py": OK2 + f"# {i}\n" for i in range(N_STALE + 3)}
mdir = mkplugin(many, "alpha")
mrepo2 = os.path.dirname(mdir)
put(os.path.join(mdir, "lib", "z.py"), "Z = 1\n")
git(mrepo2, "init", "-q", "-b", "main")
git(mrepo2, "add", "-A")
git(mrepo2, "commit", "-q", "-m", "база")
put(os.path.join(mdir, "lib", "z.py"), "Z = 2\n")
mlabels = sorted(f"alpha/{f}" for f in many)
zrel = os.path.relpath(os.path.join(mdir, "lib", "z.py"), mrepo2)
mm2 = mkmap(mlabels, {zrel: [mlabels[-1]]},
            hashes={lb: ("старый" if i < N_STALE else R.test_hash(mdir, lb)) for i, lb in enumerate(mlabels)})
r = run_aff("--affected", "--base", "main", mdir, mapf=mm2)
check(f"устаревшая карта: {N_STALE} из {len(mlabels)} файлов изменены — идут они и затронутый, не весь набор",
      r.returncode == 0 and "карта устарела" not in r.stdout and "изменены после сборки карты" in r.stdout
      and f"тестов {N_STALE + 1} из {len(mlabels)}" in r.stdout
      and f"файлов {N_STALE + 1}, ok {N_STALE + 1}" in r.stdout, r.stdout)
# устаревшая карта + новый файл вне карты: весь набор одной строкой с причиной и именем файла
put(os.path.join(mdir, "lib", "brand_new.py"), "B = 1\n")
r = run_aff("--affected", "--base", "main", mdir, mapf=mm2)
check("устаревшая карта + файл вне карты: весь набор, одна строка с причиной и файлом",
      r.returncode == 0 and "brand_new.py — нет в карте" in r.stdout and "весь набор" in r.stdout
      and r.stdout.count("run-tests: затронутое") == 1 and f"файлов {len(mlabels)}, ok {len(mlabels)}" in r.stdout, r.stdout)
# 7 файлов вне карты (долг argus #292, metis-0782): строка называет первые 5 и «и ещё 2», не один и не все
NEW7 = [f"brand_new{i}.py" for i in range(1, 7)]
for nm in NEW7:
    put(os.path.join(mdir, "lib", nm), "B = 1\n")
r = run_aff("--affected", "--base", "main", mdir, mapf=mm2)
line7 = next((ln for ln in r.stdout.splitlines() if ln.startswith("run-tests: затронутое")), "")
check("7 файлов вне карты: строка называет ровно 5 с причиной и «и ещё 2», весь набор",
      r.returncode == 0 and line7.count("— нет в карте") == 5 and line7.endswith(" и ещё 2 — весь набор")
      and "изменено 8" in line7 and f"файлов {len(mlabels)}, ok {len(mlabels)}" in r.stdout, r.stdout)
os.remove(os.path.join(mdir, "lib", NEW7[-1]))
r = run_aff("--affected", "--base", "main", mdir, mapf=mm2)
line6 = next((ln for ln in r.stdout.splitlines() if ln.startswith("run-tests: затронутое")), "")
check("6 файлов вне карты: 5 названо и «и ещё 1»", line6.count("— нет в карте") == 5
      and line6.endswith(" и ещё 1 — весь набор"), r.stdout)
for nm in NEW7[:-1] + ["brand_new.py"]:
    os.remove(os.path.join(mdir, "lib", nm))
r = run_aff("--affected", "--base", "main", mdir, mapf=mm2)
check("один файл вне карты убран, вне карты ничего: «и ещё» нет", "и ещё" not in r.stdout
      and "весь набор" not in r.stdout, r.stdout)

# --- affected-map.py: карта по прогону в копии с метками ---
MAPPER = os.path.join(PLUGIN, "scripts", "affected-map.py")
spec_m = importlib.util.spec_from_file_location("affected_map_mod", MAPPER)
AMOD = importlib.util.module_from_spec(spec_m)
spec_m.loader.exec_module(AMOD)
STMT = "exec('pass')"
for name, src in (("docstring", '"""Док.\n\nвторая строка"""\nimport os\nX = 1\n'),
                  ("docstring и __future__", '"""Д."""\nfrom __future__ import annotations\nX = 1\n'),
                  ("без docstring, import", "#!/usr/bin/env python3\nimport os\nX = 1\n"),
                  ("без docstring, def", "def f():\n    return 1\n"),
                  ("пустой", "")):
    new = AMOD.mark_py(src, STMT)
    ok = new is not None and STMT in new and compile(new, "x", "exec") is not None
    shift = 1 if name in ("без docstring, def", "пустой") else 0  # перед def — своя строка, это единственный сдвиг
    if ok:
        ok = new.count("\n") == src.count("\n") + shift
    if ok and src:
        t0, t1 = ast.parse(src), ast.parse(new)
        ok = ast.get_docstring(t0) == ast.get_docstring(t1) and [n.lineno + shift for n in t0.body if not isinstance(
            n, ast.Expr)][-1:] == [n.lineno for n in t1.body if not isinstance(n, ast.Expr)][-1:]
    check(f"mark_py: {name} — метка есть, docstring на месте, строки сдвинуты на {shift}", ok, new)
check("mark_py: не Python — None", AMOD.mark_py("def (:\n", STMT) is None)
sh = AMOD.mark_sh("#!/bin/sh\necho a\n", "printf x")
check("mark_sh: метка после #!", sh == "#!/bin/sh\nprintf x\necho a\n", sh)
sh = AMOD.mark_sh("# Поиск python\n# ещё\n\nx=1\n", "printf x")
check("mark_sh: шапка комментариев остаётся первой", sh == "# Поиск python\n# ещё\n\nprintf x\nx=1\n", sh)
sh = AMOD.mark_sh("# только шапка", "printf x")
check("mark_sh: файл из одних комментариев — метка в конце", sh == "# только шапка\nprintf x\n", sh)

mrepo = tempfile.mkdtemp(prefix="mrepo-")
ma = os.path.join(mrepo, "plugins", "alpha")
put(os.path.join(mrepo, "AGENTS.md"), "правила\n")
put(os.path.join(ma, "lib", "x.py"), '"""Модуль x."""\nX = 1\n')
put(os.path.join(ma, "lib", "lazy.py"), "L = 1\n")
put(os.path.join(ma, "lib", "front.py"), '"""Грузит lazy по требованию."""\nimport importlib.util, os, sys\n'
    "def load():\n    s = importlib.util.spec_from_file_location('lazy', os.path.join(os.path.dirname("
    "os.path.abspath(__file__)), 'lazy.py'))\n    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
    "    return m\nif __name__ == '__main__' and sys.argv[1:] == ['lazy']:\n    load()\n")
put(os.path.join(ma, "lib", "data.txt"), "данные\n")
put(os.path.join(ma, "lib", "s.sh"), "#!/bin/sh\necho s\n")
put(os.path.join(ma, "lib", "copied.py"), "print('copied')\n")
HDR = "import os, shutil, subprocess, sys, tempfile\nP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
put(os.path.join(ma, "tests", "test_x.py"), HDR + "sys.path.insert(0, os.path.join(P, 'lib'))\nimport x\n"
    "open(os.path.join(P, 'lib', 'data.txt')).read()\n" + OK2)
put(os.path.join(ma, "tests", "test_lazy.py"), HDR + "subprocess.run([sys.executable, '-I', os.path.join(P, 'lib', "
    "'front.py'), 'lazy'], check=True)\n" + OK2)
put(os.path.join(ma, "tests", "test_sh.py"), HDR + "subprocess.run(['/bin/sh', os.path.join(P, 'lib', 's.sh')], "
    "check=True, stdout=subprocess.DEVNULL)\n" + OK2)
put(os.path.join(ma, "tests", "test_copy.py"), HDR + "d = tempfile.mkdtemp()\nshutil.copy(os.path.join(P, 'lib', "
    "'copied.py'), d)\nsubprocess.run([sys.executable, '-I', os.path.join(d, 'copied.py')], check=True, "
    "stdout=subprocess.DEVNULL)\n" + OK2)
put(os.path.join(ma, "tests", "test_plain.py"), OK2)
put(os.path.join(ma, "lib", "tree", "a.txt"), "a\n")
put(os.path.join(ma, "lib", "tree", "sub", "b.txt"), "b\n")
put(os.path.join(ma, "tests", "test_tree.py"), HDR + "shutil.copytree(os.path.join(P, 'lib', 'tree'), "
    "os.path.join(tempfile.mkdtemp(), 't'))\n" + OK2)
TWIN = "#!/bin/sh\necho twin\n"
put(os.path.join(ma, "lib", "twin_a.sh"), TWIN)
put(os.path.join(ma, "lib", "twin_b.sh"), TWIN)
put(os.path.join(ma, "tests", "test_twin.py"), HDR + "a, b = (open(os.path.join(P, 'lib', f)).read() for f in "
    "('twin_a.sh', 'twin_b.sh'))\nassert a == b, 'копии разошлись'\nsubprocess.run(['/bin/sh', os.path.join(P, "
    "'lib', 'twin_a.sh')], check=True, stdout=subprocess.DEVNULL)\n" + OK2)
# metis-0791: текст `python -c` и пустой аргумент в папке плагина (от текущей папки — путь папки) и rmtree временной
# папки с lib/ (open с dir_fd хук видел от текущей папки) не связывают тест с файлами плагина
put(os.path.join(ma, "tests", "test_cscript.py"), HDR + "subprocess.run([sys.executable, '-I', '-c', '\\nimport os\\n"
    "x = 1\\n'], cwd=P, check=True)\nsubprocess.run([sys.executable, '-I', '-c', 'pass', ''], cwd=P, check=True)\n" + OK2)
put(os.path.join(ma, "tests", "test_rmtree.py"), HDR + "t = tempfile.mkdtemp()\nos.makedirs(os.path.join(t, 'lib', "
    "'tree'))\nopen(os.path.join(t, 'lib', 'x.py'), 'w').close()\nos.chdir(P)\nshutil.rmtree(t)\n" + OK2)
# читает дерево: открывает 25 файлов из пяти папок (порог — 20 из 5), ничего из них не запуская; s.sh запускает — эта
# связь остаётся. test_fewdirs — 20 файлов из четырёх папок, test_thin — 15 из пяти: обычные тесты, связи остаются
READ_DIRS = ("docs/a", "docs/b", "docs/c", "docs/d", "docs/e")
for sub in READ_DIRS:
    for i in range(5):
        put(os.path.join(ma, sub, f"f{i}.md"), f"{sub} {i}\n")


def reads(dirs, n):
    return HDR + f"for sub in {dirs!r}:\n    for f in sorted(os.listdir(os.path.join(P, sub)))[:{n}]:\n" \
        "        open(os.path.join(P, sub, f)).read()\n"


# metis-0817 (M9): s.sh и copied.py сначала открыты (метка «r»), потом запущены и скопированы (метка «o») — запуск не
# теряется: дедуп по пути без метки оставил бы только «r», и у читающего дерево связь пропала бы
put(os.path.join(ma, "tests", "test_reader.py"), reads(READ_DIRS, 5)
    + "open(os.path.join(P, 'lib', 's.sh')).read()\nopen(os.path.join(P, 'lib', 'copied.py')).read()\n"
    "subprocess.run(['/bin/sh', os.path.join(P, 'lib', 's.sh')], check=True, stdout=subprocess.DEVNULL)\n"
    "shutil.copy(os.path.join(P, 'lib', 'copied.py'), tempfile.mkdtemp())\n" + OK2)
# metis-0817 (M10): 20 модулей из 5 папок загружены (импорт: метка «m», он же открывает файл — «r») — не читают дерево:
# прочитанное без загрузки — ничего; без вычитания use они выглядели бы как 20 прочитанных из 5 папок
for _i in range(5):
    for _j in range(4):
        put(os.path.join(ma, "mods", f"d{_i}", f"m{_i}{_j}.py"), f"V = {_j}\n")
put(os.path.join(ma, "tests", "test_loader.py"), HDR + "for i in range(5):\n    sys.path.insert(0, os.path.join(P, 'mods', "
    "f'd{i}'))\nfor i in range(5):\n    for j in range(4):\n        __import__(f'm{i}{j}')\n" + OK2)
put(os.path.join(ma, "tests", "test_fewdirs.py"), reads(READ_DIRS[:4], 5) + OK2)
put(os.path.join(ma, "tests", "test_thin.py"), reads(READ_DIRS, 3) + OK2)
put(os.path.join(ma, "tests", "test_fail.py"), "import sys\nprint('ok   a')\nsys.exit(1)\n")
git(mrepo, "init", "-q", "-b", "main")
git(mrepo, "add", "-A")
git(mrepo, "commit", "-q", "-m", "база")
mout = os.path.join(tempfile.mkdtemp(prefix="mout-"), "map.json")
r = subprocess.run([sys.executable, "-I", MAPPER, "-j", "3", "--out", mout, ma], env=GENV, stdout=subprocess.PIPE,
                   stderr=subprocess.STDOUT, text=True, timeout=180)
check("affected-map: код 0, карта записана", r.returncode == 0 and os.path.isfile(mout), r.stdout)
mm, why = R.load_map(mout)
mm = mm or {"tests": set(), "always": set(), "files": {}}
F = mm["files"]
for path, want in (("plugins/alpha/lib/x.py", {"alpha/test_x.py"}),
                   ("plugins/alpha/lib/data.txt", {"alpha/test_x.py"}),
                   ("plugins/alpha/lib/front.py", {"alpha/test_lazy.py"}),
                   ("plugins/alpha/lib/lazy.py", {"alpha/test_lazy.py"}),
                   ("plugins/alpha/lib/copied.py", {"alpha/test_copy.py", "alpha/test_reader.py"}),
                   ("plugins/alpha/mods/d0/m00.py", {"alpha/test_loader.py"}),
                   ("plugins/alpha/mods/d4/m43.py", {"alpha/test_loader.py"}),
                   ("plugins/alpha/lib/tree/a.txt", {"alpha/test_tree.py"}),
                   ("plugins/alpha/lib/tree/sub/b.txt", {"alpha/test_tree.py"}),
                   ("plugins/alpha/lib/twin_a.sh", {"alpha/test_twin.py"}),
                   ("plugins/alpha/lib/twin_b.sh", {"alpha/test_twin.py"}),
                   # s.sh запускает и test_reader: запуск у читающего дерево остаётся связью
                   ("plugins/alpha/lib/s.sh", {"alpha/test_sh.py", "alpha/test_reader.py"}),
                   ("plugins/alpha/docs/a/f0.md", {"alpha/test_fewdirs.py", "alpha/test_thin.py"}),
                   ("plugins/alpha/docs/a/f4.md", {"alpha/test_fewdirs.py"}),
                   ("plugins/alpha/docs/e/f0.md", {"alpha/test_thin.py"}),
                   ("plugins/alpha/docs/e/f4.md", set()),
                   ("AGENTS.md", set())):
    check(f"affected-map: {path} → {sorted(want) or 'ничего'}", F.get(path) == want, (F.get(path), why))
# metis-0791: ни `python -c` с переводом строки, ни rmtree временной папки с lib/ не связывают тест с файлами плагина
for lb in ("alpha/test_cscript.py", "alpha/test_rmtree.py"):
    got = sorted(p for p, v in F.items() if lb in v and not p.startswith("plugins/alpha/tests/"))
    check(f"affected-map: {lb} не задевает файлов плагина", got == [], got)
with open(mout, encoding="utf-8") as fh:
    RAW = json.load(fh)
check("affected-map: readers — только читающий дерево (25 файлов из 5 папок); 20 из 4 и 15 из 5 — нет",
      RAW.get("readers") == ["alpha/test_reader.py"], RAW.get("readers"))
check("affected-map: readers идут всегда (load_map)", "alpha/test_reader.py" in mm["always"], mm["always"])
check("affected-map: version 3, hashes — sha256 каждого файла тестов", RAW.get("version") == 3 and mm.get("hashes") and all(
    mm["hashes"].get(lb) == hashlib.sha256(open(os.path.join(ma, "tests", lb.split("/")[1]), "rb").read()).hexdigest()
    for lb in mm["tests"]), mm.get("hashes"))
check("affected-map: tests — все файлы тестов, broken — упавший", mm["tests"] == {
    "alpha/test_x.py", "alpha/test_lazy.py", "alpha/test_sh.py", "alpha/test_copy.py", "alpha/test_plain.py",
    "alpha/test_fail.py", "alpha/test_tree.py", "alpha/test_twin.py", "alpha/test_cscript.py", "alpha/test_rmtree.py",
    "alpha/test_reader.py", "alpha/test_fewdirs.py", "alpha/test_thin.py", "alpha/test_loader.py"} and RAW.get("broken") == ["alpha/test_fail.py"],
      mm)
with open(os.path.join(ma, "lib", "x.py")) as fh:
    check("affected-map: исходники репозитория без меток", fh.read() == '"""Модуль x."""\nX = 1\n')
r = subprocess.run([sys.executable, "-I", MAPPER, "--out", mout, mkplugin({"test_a.py": OK2})], env=GENV,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
check("affected-map: не git — код 2", r.returncode == 2 and "не репозиторий git" in r.stdout, r.stdout)
os.makedirs(os.path.join(mrepo, "plugins", "empty", "tests"))
r = subprocess.run([sys.executable, "-I", MAPPER, "--out", mout, os.path.join(mrepo, "plugins", "empty")], env=GENV,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
check("affected-map: ни одного файла тестов — код 1", r.returncode == 1 and "ни одного файла" in r.stdout, r.stdout)
FAIL1 = "import sys\nprint('ok   a')\nsys.exit(1)\n"
put(os.path.join(mrepo, "plugins", "half", "tests", "test_f1.py"), FAIL1)
put(os.path.join(mrepo, "plugins", "half", "tests", "test_f2.py"), FAIL1)
put(os.path.join(mrepo, "plugins", "half", "tests", "test_ok.py"), OK2)
git(mrepo, "add", "-A")
git(mrepo, "commit", "-q", "-m", "half")
r = subprocess.run([sys.executable, "-I", MAPPER, "--out", mout, os.path.join(mrepo, "plugins", "half")], env=GENV,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120)
check("affected-map: упало больше половины — код 1, карта всё равно записана",
      r.returncode == 1 and os.path.isfile(mout), r.stdout)
FILES = ["a/x.py", "a/tree/b.txt", "a/tree/sub/c.txt", "a/treeX.txt", "z.md"]
check("expand: файл — он сам, папка — все файлы под ней, соседнее имя с тем же началом — нет",
      AMOD.expand({"a/x.py", "a/tree/"}, FILES) == {"a/x.py", "a/tree/b.txt", "a/tree/sub/c.txt"},
      AMOD.expand({"a/x.py", "a/tree/"}, FILES))
check("expand: корень и пустой путь не раскрываются во весь репозиторий", AMOD.expand({".", ""}, FILES) == set(),
      AMOD.expand({".", ""}, FILES))

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

# --- не macOS: явный пропуск файлов и заглушки команд macOS (CI на Linux) ---
IT = [("/r/plugins/pantheon", "pantheon/test_setup.py"), ("/r/plugins/pantheon", "pantheon/test_board.py"),
      ("/r/plugins/pantheon", "pantheon/test_tick.py")]
check("split_skipped: на macOS ничего не пропускается", R.split_skipped(IT, "darwin") == (IT, []))
got = R.split_skipped(IT, "linux", exists=lambda p: False)
check("split_skipped: на Linux — пропущен только test_setup (установщик), остальное идёт",
      got[0] == [IT[1], IT[2]] and [lb for lb, _ in got[1]] == ["pantheon/test_setup.py"] and all(why for _, why in got[1]), got)
# условие unless: файл идёт, если нужная программа есть (механизм остался, записей с ним сейчас нет)
real = R.SKIP_NOT_MAC
R.SKIP_NOT_MAC = {"pantheon/test_board.py": ("нужен zsh", "/bin/zsh")}
try:
    got = R.split_skipped(IT, "linux", exists=lambda p: False)
    got2 = R.split_skipped(IT, "linux", exists=lambda p: p == "/bin/zsh")
finally:
    R.SKIP_NOT_MAC = real
check("split_skipped: unless — без /bin/zsh board пропущен, с ним идёт",
      [lb for lb, _ in got[1]] == ["pantheon/test_board.py"] and got2 == (IT, []), (got, got2))
missing = [lb for lb in R.SKIP_NOT_MAC if not os.path.exists(
    os.path.join(os.path.dirname(PLUGIN), lb.split("/")[0], "tests", lb.split("/")[1]))]
check("SKIP_NOT_MAC — ровно test_setup: остальное пропускается случаями внутри тестов, а не файлом",
      set(R.SKIP_NOT_MAC) == {"pantheon/test_setup.py"}, sorted(R.SKIP_NOT_MAC))
check("SKIP_NOT_MAC — только существующие файлы, у каждого есть причина",
      not missing and all(why for why, _ in R.SKIP_NOT_MAC.values()), missing)
# --- окно роли (metis-0773): файлы WINDOW_FS идут в запасной корень или пропускаются строкой ---
wmiss = [lb for lb in R.WINDOW_FS if not os.path.exists(
    os.path.join(os.path.dirname(PLUGIN), lb.split("/")[0], "tests", lb.split("/")[1]))]
check("WINDOW_FS — только существующие файлы", not wmiss and R.WINDOW_FS, wmiss)
real_probe = R.fs_probe
try:
    R.fs_probe = lambda base: None
    check("window_roots: запись есть — корень прежний, строки нет",
          R.window_roots("/r", ["pantheon/test_roles.py"]) == ("/r", None, None))
    R.fs_probe = lambda base: "EPERM" if base == "/r" else None
    wr_alt = os.path.join("/tmp", f"claude-{os.getuid()}")
    if os.path.isdir(wr_alt):
        wr = R.window_roots("/r", ["pantheon/test_roles.py"])
        check("window_roots: под корнем нельзя, в /tmp/claude-<uid> можно — запасной корень и строка",
              wr[0].startswith(os.path.join(wr_alt, "run-tests-")) and wr[1] is None and "EPERM" in wr[2], wr)
        shutil.rmtree(wr[0], True)
    else:
        print("пропущено: нет /tmp/claude-<uid> — случай запасного корня")
    R.fs_probe = lambda base: "EPERM"
    wr = R.window_roots("/r", ["pantheon/test_roles.py"])
    check("window_roots: нигде нельзя — корня нет, причина названа", wr[0] is None and "EPERM" in wr[1], wr)
    check("window_roots: нет файлов WINDOW_FS — проба не нужна",
          R.window_roots("/r", ["pantheon/test_board.py"]) == ("/r", None, None))
finally:
    R.fs_probe = real_probe
# window_plan: решение для файлов, зависящих от окна (metis-0773), пробы подставлены
WL = ["pantheon/test_roles.py", "guard/test_merge_gate.py", "pantheon/test_outside.py", "pantheon/test_board.py"]
okp, no_bind = (lambda b: None), (lambda: "EPERM bind")
pl = R.window_plan("/r", WL, probe=okp, bind=lambda: None)
check("window_plan вне окна: корень прежний, пропускаемых нет, причины и строки нет — набор идёт как раньше",
      pl == ("/r", set(), "", None), pl)
check("WINDOW_NOT_TMP и WINDOW_BIND — подмножества существующих файлов",
      R.WINDOW_NOT_TMP <= R.WINDOW_FS and R.WINDOW_BIND and R.WINDOW_BIND <= R.WINDOW_FS | {"pantheon/test_outside.py"})
pl = R.window_plan("/r", WL, probe=okp, bind=no_bind)
check("window_plan: bind закрыт — пропущен только WINDOW_BIND, корень прежний",
      pl[0] == "/r" and pl[1] == R.WINDOW_BIND and "EPERM bind" in pl[2], pl)
pl = R.window_plan("/r", ["pantheon/test_roles.py", "pantheon/test_board.py"], probe=okp, bind=no_bind)
check("window_plan: файлов WINDOW_BIND в наборе нет — bind не проверяется, пропусков нет", pl[1] == set(), pl)
pl = R.window_plan("/r", WL, probe=lambda b: "EPERM" if b == "/r" else None, bind=lambda: None)
if os.path.isdir(os.path.join("/tmp", f"claude-{os.getuid()}")):
    check("window_plan: корень закрыт, запасной открыт — запасной корень, пропущен только WINDOW_NOT_TMP",
          pl[0] != "/r" and pl[0].startswith(os.path.join("/tmp", f"claude-{os.getuid()}", "run-tests-"))
          and pl[1] == R.WINDOW_NOT_TMP and "/tmp" in pl[2] and "EPERM" in pl[3], pl)
    shutil.rmtree(pl[0], True)
else:
    print("пропущено: нет /tmp/claude-<uid> — случай запасного корня")
pl = R.window_plan("/r", WL, probe=lambda b: "EPERM", bind=no_bind)
check("window_plan: закрыто везде — корня нет, пропущены WINDOW_FS и WINDOW_BIND, причины обе",
      pl[0] is None and pl[1] == R.WINDOW_FS | R.WINDOW_BIND and "EPERM" in pl[2] and "порт" in pl[2], pl)
# fs_probe на настоящих папках и подставленном внешнем вызове (metis-0773, ревью r1)
import contextlib, io
fp = tempfile.mkdtemp(prefix="fsp-")
check("fs_probe: папка с записью — None", R.fs_probe(fp) is None, R.fs_probe(fp))
ro = tempfile.mkdtemp(prefix="fsp-ro-")
os.chmod(ro, 0o555)
if os.access(ro, os.W_OK):
    print("пропущено: запись в chmod 555 разрешена (root) — случай папки без записи")
else:
    check("fs_probe: папка без записи (chmod 555) — причина названа", "PermissionError" in (R.fs_probe(ro) or ""), R.fs_probe(ro))
os.chmod(ro, 0o755)
real_makedirs, real_path = os.makedirs, os.environ["PATH"]
def deny_agents(path, *a, **k):
    if path.endswith(os.path.join(".claude", "agents")):
        raise PermissionError(1, "Operation not permitted")
    return real_makedirs(path, *a, **k)
try:
    os.makedirs = deny_agents
    check("fs_probe: `.claude/agents` создать нельзя — причина названа",
          "PermissionError" in (R.fs_probe(fp) or ""), R.fs_probe(fp))
finally:
    os.makedirs = real_makedirs
for rc, want in ((1, "init не вышел"), (0, None)):
    gd = tempfile.mkdtemp(prefix="fakegit-")
    with open(os.path.join(gd, "git"), "w") as fh:
        fh.write(f"#!/bin/sh\necho нет записи >&2\nexit {rc}\n")
    os.chmod(os.path.join(gd, "git"), 0o755)
    os.environ["PATH"] = gd + os.pathsep + real_path
    try:
        got = R.fs_probe(fp)
    finally:
        os.environ["PATH"] = real_path
    check(f"fs_probe: init выходит с кодом {rc} — " + ("причина названа" if want else "None"),
          (want in (got or "")) if want else got is None, got)
check("fs_probe: пробная папка за собой убрана", not os.listdir(fp), os.listdir(fp))

# main(): корень, строки skip, код выхода при подставленных пробах (metis-0773, ревью r1: Б и Д)
OKF = "print('ok a')\nprint('1 из 1')\n"
def main_with(files, fs=None, bind=None):
    saved = R.fs_probe, R.bind_probe
    R.fs_probe, R.bind_probe = fs or (lambda b: None), bind or (lambda: None)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = R.main([mkplugin(files, "pantheon"), "-j", "2"])
    finally:
        R.fs_probe, R.bind_probe = saved
    return rc, buf.getvalue()
WF = {"test_outside.py": OKF, "test_board.py": OKF}
rc, out = main_with(WF)
check("WINDOW_SKIP_CODE отличен от 3 и 0", R.WINDOW_SKIP_CODE not in (0, 1, 3))
check("main: пробы проходят — код 0, ни skip, ни строки про окно", rc == 0 and "skip " not in out and "годится" not in out
      and "файлов 2, ok 2, FAIL 0;" in out, (rc, out))
rc, out = main_with(WF, bind=lambda: "EPERM bind")
check("main: bind закрыт — код 4, skip с причиной, строка «для записи полного набора не годится»",
      rc == 4 and re.search(r"^skip pantheon/test_outside\.py · пропущено: .*EPERM bind", out, re.M)
      and "пропущены файлы окна — для записи полного набора не годится" in out
      and "файлов 1, ok 1, FAIL 0, пропущено 1;" in out, (rc, out))
rc, out = main_with(dict(WF, **{"test_board.py": "print('ok a')\nraise SystemExit(1)\n"}), bind=lambda: "EPERM bind")
check("main: пропуск окна и FAIL — код 1, а не 4", rc == 1 and "FAIL pantheon/test_board.py" in out, (rc, out))
rc, out = main_with({"test_outside.py": OKF}, bind=lambda: "EPERM bind")
check("main: пропущены все файлы окна — код 4 (не 3 «нечего гонять»), а не зелёный 0", rc == 4 and "для записи полного набора не годится" in out, (rc, out))
ALT = os.path.join("/tmp", f"claude-{os.getuid()}")
# TMPDIR сам может лежать под ALT (в окне роли этот файл идёт в запасном корне ALT/run-tests-…, metis-0941): префикс
# пути не различает. Запасной корень — ALT/run-tests-…, HOME файла в нём — <корень>/<NNN-…>/home: три уровня от HOME — ALT
HOME_IN = ("import os\nd = os.path.dirname\nok = {neg}(d(d(d(os.environ['HOME']))) == {alt!r})\n"
           "print('ok h' if ok else 'FAIL home ' + os.environ['HOME'])\n"
           "print('1 из 1' if ok else '0 из 1')\nraise SystemExit(0 if ok else 1)\n")
if os.path.isdir(ALT):
    alt_fs = lambda b: None if b == ALT else "EPERM fs"
    rc, out = main_with({"test_roles.py": HOME_IN.format(neg="", alt=ALT), "test_board.py": HOME_IN.format(neg="not ", alt=ALT)},
                        fs=alt_fs)
    check("main: корень закрыт, запасной открыт — файл WINDOW_FS идёт с HOME в запасном корне, прочие в обычном; код 0",
          rc == 0 and "ok   pantheon/test_roles.py" in out and "ok   pantheon/test_board.py" in out
          and "run-tests: окно режет запись" in out, (rc, out))
else:
    print("пропущено: нет /tmp/claude-<uid> — случай запасного корня в main")
rc, out = main_with({"test_roles.py": OKF, "test_board.py": OKF}, fs=lambda b: "EPERM fs")
check("main: запись закрыта везде — WINDOW_FS пропущен, board идёт, код 4",
      rc == 4 and "skip pantheon/test_roles.py" in out and "ok   pantheon/test_board.py" in out
      and "файлов 1, ok 1, FAIL 0, пропущено 1;" in out, (rc, out))

sd = tempfile.mkdtemp(prefix="stubs-")
check("make_stubs: на macOS заглушек нет", R.make_stubs(sd, "darwin", which=lambda c: None) == (None, []))
check("make_stubs: на Linux все команды есть — заглушек нет", R.make_stubs(sd, "linux", which=lambda c: "/x") == (None, []))
d, cmds = R.make_stubs(sd, "linux", which=lambda c: "/x" if c == "ioreg" else None)
check("make_stubs: на Linux только недостающие (pmset, scutil)", cmds == ["pmset", "scutil"]
      and sorted(os.listdir(d)) == ["pmset", "scutil"] and all(os.access(os.path.join(d, c), os.X_OK) for c in cmds),
      (d, cmds))
check("make_stubs: pmset отвечает «AC Power»",
      "AC Power" in subprocess.run([os.path.join(d, "pmset"), "-g", "batt"], stdout=subprocess.PIPE, text=True).stdout)
PEN = {"PATH": "/bin", "RUN_TESTS_PLATFORM": "linux"}  # на PATH только sh: ни ioreg, ни pmset, ни scutil
STUB_T = ("import shutil\nok = all(shutil.which(c) for c in ('ioreg', 'pmset', 'scutil'))\n"
          "print('ok   заглушки на PATH' if ok else 'FAIL нет заглушек')\nprint('1 из 1 прошли' if ok else '0 из 1')\n"
          "raise SystemExit(0 if ok else 1)\n")
p = mkplugin({"test_setup.py": "print('ok a')\nraise SystemExit(1)\n", "test_stub.py": STUB_T}, "pantheon")
r = run([p], env=PEN)
check("Linux: пропущенный файл — строка skip с причиной, код 0, число в итоге",
      r.returncode == 0 and re.search(r"^skip pantheon/test_setup\.py · пропущено: нужен macOS — \S", r.stdout, re.M)
      and "файлов 1, ok 1, FAIL 0, пропущено 1;" in r.stdout and "заглушки команд" in r.stdout, r.stdout)
check("Linux: заглушки ioreg, pmset, scutil видны файлу тестов", "ok   pantheon/test_stub.py" in r.stdout, r.stdout)
r = run([p], env=dict(PEN, RUN_TESTS_PLATFORM="darwin"))
check("macOS: ничего не пропущено, setup идёт и падает, заглушек нет — код 1",
      r.returncode == 1 and "skip " not in r.stdout and "FAIL pantheon/test_setup.py" in r.stdout
      and "FAIL pantheon/test_stub.py" in r.stdout and "пропущено" not in r.stdout, r.stdout)
p = mkplugin({"test_setup.py": "print('ok a')\nraise SystemExit(1)\n"}, "pantheon")
r = run([p], env=PEN)
check("Linux: все файлы пропущены — код 3 «нечего гонять», а не зелёный итог",
      r.returncode == 3 and "skip pantheon/test_setup.py" in r.stdout and "нечего гонять" in r.stdout
      and "итого" not in r.stdout, (r.returncode, r.stdout))

# --- metis-0647: файл тестов — в классе раннера; RUN_TESTS_QOS=utility на macOS с taskpolicy — `taskpolicy -c utility` ---
TP = R.TASKPOLICY
T = ["py", "-I", os.path.join("tests", "test_x.py")]
U = {"RUN_TESTS_QOS": "utility"}
c = R.launch_cmd("py", "test_x.py", "darwin", lambda p: p == TP, {})
check("macOS, taskpolicy есть, без RUN_TESTS_QOS: файл в классе раннера, без taskpolicy", c == T, c)
for val in ("", "default", "UTILITY", "background"):
    c = R.launch_cmd("py", "test_x.py", "darwin", lambda p: p == TP, {"RUN_TESTS_QOS": val})
    check(f"RUN_TESTS_QOS={val!r} — не utility: без taskpolicy", c == T, c)
c = R.launch_cmd("py", "test_x.py", "darwin", lambda p: p == TP, U)
check("RUN_TESTS_QOS=utility, macOS и taskpolicy есть: команда начинается с taskpolicy -c utility",
      c[:3] == [TP, "-c", "utility"] and c[3:] == T, c)
c = R.launch_cmd("py", "test_x.py", "darwin", lambda p: False, U)
check("RUN_TESTS_QOS=utility, macOS без taskpolicy: команда как раньше", c == T, c)
c = R.launch_cmd("py", "test_x.py", "linux", lambda p: True, U)
check("RUN_TESTS_QOS=utility, Linux: taskpolicy нет, даже если бинарь есть", c == T, c)
_qos = os.environ.pop("RUN_TESTS_QOS", None)
c = R.launch_cmd("py", "test_x.py", "darwin", lambda p: p == TP)
check("без env= берёт окружение процесса: переменной нет — без taskpolicy", c == T, c)
os.environ["RUN_TESTS_QOS"] = "utility"
c = R.launch_cmd("py", "test_x.py", "darwin", lambda p: p == TP)
check("без env= берёт окружение процесса: RUN_TESTS_QOS=utility — taskpolicy", c[:3] == [TP, "-c", "utility"], c)
os.environ.pop("RUN_TESTS_QOS")
check("не macOS — строки QoS нет", R.qos_line(sys.executable, dict(os.environ), "linux") is None)
if sys.platform == "darwin" and os.path.exists(TP):
    q = R.qos_line(sys.executable, dict(os.environ))
    check("macOS: строка QoS называет класс и для раннера, и для файла (класс раннера)",
          q and "раннер:" in q and "файл (класс раннера):" in q and "проба не удалась" not in q, q)
    os.environ["RUN_TESTS_QOS"] = "utility"
    try:
        q = R.qos_line(sys.executable, dict(os.environ))
    finally:
        os.environ.pop("RUN_TESTS_QOS")
    check("macOS, RUN_TESTS_QOS=utility: файл пробы — через taskpolicy -c utility и в классе utility",
          q and "файл (taskpolicy -c utility):" in q and "utility" in q.split("файл (")[1].split("):")[1], q)
    pl = mkplugin({"test_q.py": "import os\nprint('ok q', os.environ.get('RUN_TESTS_RUNNER'))\nprint('1/1')\n"}, "qq")
    r = run([pl])
    check("прогон печатает QoS-строку, а файлу виден RUN_TESTS_RUNNER=1",
          "run-tests: QoS (доля CPU)" in r.stdout and "ok   qq/test_q.py" in r.stdout, r.stdout)
else:
    print("пропущено: нужен macOS — живая проба QoS")
if _qos is not None:
    os.environ["RUN_TESTS_QOS"] = _qos

# настоящая карта: test_merge_gate читает .github/workflows (сверка OPTIONAL_CHECKS), правка workflow обязана его выбрать (#288)
real_map = json.load(open(os.path.join(PLUGIN, "scripts", "affected-map.json"), encoding="utf-8"))
gate = real_map["tests"].index("guard/test_merge_gate.py")
for wf in ("tests.yml", "release.yml", "check-traces.yml"):
    check(f"карта: .github/workflows/{wf} → guard/test_merge_gate.py",
          gate in real_map["files"].get(".github/workflows/" + wf, []), real_map["files"].get(".github/workflows/" + wf))

print(f"\n{total - len(fails)} из {total} прошли")
sys.exit(1 if fails else 0)
