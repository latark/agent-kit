#!/usr/bin/env python3
"""run-tests.py <папка плагина> … — параллельный прогон файлов тестов плагинов, в духе prove (metis-0450).

  heavy python3 -I plugins/pantheon/scripts/run-tests.py plugins/guard plugins/pantheon
  -j N            воркеров (по умолчанию min(ядра // 2, 3), при load1 выше числа ядер — 1)
  --timeout С     предел одного файла, с (по умолчанию TIMEOUT; у медленных файлов свой — SLOW)
  --log-dir ПАПКА полный вывод каждого файла — в ПАПКА/<плагин>__<файл>.log

Каждый tests/test_*.py — отдельный процесс `<этот python> -I tests/<файл>` в папке плагина, как в
`_run_plugin_tests` (pantheon.py): свой HOME и TMPDIR во временной папке прогона, окружение без PANTHEON_*,
FORCE_COLOR и CLICOLOR_FORCE, с NO_COLOR=1. Тесты на 3.9 — тот же скрипт под /usr/bin/python3.

Порядок: сначала медленные (SLOW, по замеру), затем остальные по имени. Файлы SERIAL идут в конце по одному, когда
больше ничего не идёт: им параллель мешает.

Процессы. Файл тестов — в своей сессии и группе процессов (start_new_session). По таймауту файла гаснет вся его
группа (killpg SIGKILL), и после обычного выхода файла — тоже: оставленные им внуки не грузят Mac. SIGTERM, SIGHUP и SIGINT раннеру гасят группы всех идущих файлов, и раннер выходит с кодом 128 +
номер сигнала. Так таймаут задачи (run_job: группе задачи SIGTERM, через 5 с SIGKILL) и heavy, который передаёт
сигнал дальше, не оставляют сирот. Границы: внук, который сам ушёл в свою сессию (setsid), из группы файла выпадает,
и killpg его не достаёт; SIGKILL самому раннеру обработать нельзя — идущие файлы тогда доживают свой таймаут.

Итог: строка на каждый файл по мере готовности (ok / FAIL, время, число проверок), затем выводы упавших файлов
(хвост) и последняя строка — файлов, ok, FAIL, сумма проверок, время. Код выхода не 0, если: нет ни одного файла
тестов, файл упал (код не 0), превысил таймаут, вышел с кодом 0 без строки итога (кроме старых файлов NO_SUMMARY)
или с итогом без проверок, или раннер прерван сигналом. Число проверок файла — из его итоговой строки, без числа в ней — по строкам `ok`.
Python 3.9+, только stdlib.
"""
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

TIMEOUT = 600  # с на файл; медленным — свой предел в SLOW
# Медленные файлы по замеру metis-0450 (последовательный прогон, 3.14): идут первыми, предел — свой, с.
SLOW = {
}
# Файлы, которым параллель мешает: идут в конце по одному.
SERIAL = ()
# Файлы, которые и на main кончаются последней строкой ok без строки итога (замер metis-0450): у них код 0 со строками
# ok и без строк FAIL — зелёный. Новый файл без итога сюда не попадает и остаётся красным; файл, получивший итог,
# из списка убрать.
NO_SUMMARY = frozenset({
})

# Копия TEST_SUMMARY и _SUMMARY_TOTAL из pantheon.py (импортировать нельзя: pantheon.py требует 3.11+, раннер — 3.9+).
# Тест test_run_tests сверяет копию с pantheon.py.
TEST_SUMMARY = re.compile(r"(?:\d+\s*(?:из\s+\d+|/\s*\d+|команд\b)|тестов:\s*\d+|(?:OK|FAIL)\s+\d+$|ПРОВАЛ\b)")
ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-_])")
_SUMMARY_TOTAL = (
    (re.compile(r"тестов:\s*(\d+)\s+прошло,\s*(\d+)\s+не\s+прошло"), lambda m: int(m[1]) + int(m[2])),
    (re.compile(r"\d+\s*из\s+(\d+)"), lambda m: int(m[1])),
    (re.compile(r"\d+\s*/\s*(\d+)"), lambda m: int(m[1])),
    (re.compile(r"тестов:\s*(\d+)"), lambda m: int(m[1])),
    (re.compile(r"(\d+)\s*команд\b"), lambda m: int(m[1])),
)
SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
TAIL = 40  # строк вывода упавшего файла в итог


class Interrupted(Exception):
    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def workers(cpus, load):
    """Сколько файлов гонять сразу: min(ядра // 2, 3), не меньше одного; Mac перегружен (load1 > ядер) — один."""
    cpus = cpus or 1
    if load is not None and load > cpus:
        return 1
    return max(1, min(cpus // 2, 3))


def load1():
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


def collect(pdirs):
    """[(папка плагина, метка «плагин/файл»)] — все tests/test_*.py указанных папок."""
    items = []
    for pdir in pdirs:
        tdir = os.path.join(pdir, "tests")
        if not os.path.isdir(tdir):
            continue
        name = os.path.basename(os.path.normpath(os.path.abspath(pdir)))
        for f in sorted(os.listdir(tdir)):
            if f.startswith("test_") and f.endswith(".py"):
                items.append((os.path.abspath(pdir), f"{name}/{f}"))
    return items


def order(items, slow=None, serial=None):
    """(параллельные, серийные): параллельные — медленные первыми (по убыванию предела в slow), затем по имени."""
    slow = SLOW if slow is None else slow
    serial = SERIAL if serial is None else serial
    par = [it for it in items if it[1] not in serial]
    ser = [it for it in items if it[1] in serial]
    par.sort(key=lambda it: (-slow.get(it[1], 0), it[1]))
    return par, ser


def checks(out):
    """(есть ли итог, число проверок, плохой итог или None). Итог — последняя непустая строка, как TEST_SUMMARY в
    pantheon.py; число проверок — из итога, без числа в нём — по строкам ok."""
    lines = ANSI.sub("", out).splitlines()
    last = next((ln.strip() for ln in reversed(lines) if ln.strip()), "")
    nok = sum(1 for ln in lines if re.match(r"\s*ok\b", ln))
    if not TEST_SUMMARY.match(last):
        return False, nok, None
    total = None
    for rx, fn in _SUMMARY_TOTAL:
        m = rx.match(last)
        if m:
            total = fn(m)
            break
    passed = re.match(r"(\d+)\s*(?:из\s|/)", last)
    if passed and total is not None and int(passed[1]) < total:
        return True, total, f"итог «{last}» — прошли не все"
    if last.startswith("ПРОВАЛ"):
        return True, total if total is not None else nok, f"итог «{last}»"
    n = total if total is not None else nok
    if n == 0:
        return True, 0, f"итог «{last}» — ни одной проверки"
    return True, n, None


def verdict(rc, out, timed_out, label=None, no_summary=None):
    """(ok, почему не ok или None, число проверок). Код 0 без итога — красный, кроме файлов NO_SUMMARY со строками ok
    и без строк FAIL."""
    no_summary = NO_SUMMARY if no_summary is None else no_summary
    has, n, bad = checks(out)
    if timed_out:
        return False, "таймаут", n
    if rc != 0:
        why = f"сигнал {-rc}" if rc < 0 else f"код {rc}"
        return False, why, n
    if not has:
        if label in no_summary and n and not re.search(r"^\s*FAIL\b", ANSI.sub("", out), re.M):
            return True, None, n
        return False, "код 0 без строки итога", n
    if bad:
        return False, bad, n
    return True, None, n


def _killpg(pid, sig=signal.SIGKILL):
    """True, если в группе был кто-то живой."""
    try:
        os.killpg(pid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


class Job:
    def __init__(self, pdir, label, py, root, env0, timeout, seq):
        self.pdir, self.label, self.timeout = pdir, label, timeout
        self.dir = tempfile.mkdtemp(prefix=f"{seq:03d}-", dir=root)
        home, tdir = os.path.join(self.dir, "home"), os.path.join(self.dir, "tmp")
        os.mkdir(home)
        os.mkdir(tdir)
        self.outpath = os.path.join(self.dir, "out.log")
        self.fh = open(self.outpath, "wb")
        f = label.split("/", 1)[1]
        self.t0 = time.monotonic()
        self.proc = subprocess.Popen([py, "-I", os.path.join("tests", f)], cwd=pdir,
                                     env={**env0, "HOME": home, "TMPDIR": tdir}, stdin=subprocess.DEVNULL,
                                     stdout=self.fh, stderr=subprocess.STDOUT, start_new_session=True)
        self.timed_out = False

    def exited(self):
        """Вышел ли файл; вышел — гасит его группу (оставленных внуков). Лидер группы до killpg не пожимается
        (waitid WNOWAIT), чтобы номер группы не ушёл другому процессу; без waitid (3.9 на macOS) — poll, затем
        killpg: внуки держат группу живой, и её номер не переиспользуется, пока они есть."""
        pid = self.proc.pid
        if hasattr(os, "waitid"):
            try:
                if os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                    return False
            except ChildProcessError:
                pass
            _killpg(pid)
            self.proc.wait()
            return True
        if self.proc.poll() is None:
            return False
        _killpg(pid)
        return True

    def kill(self):
        _killpg(self.proc.pid)
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    def finish(self):
        self.sec = time.monotonic() - self.t0
        self.fh.close()
        with open(self.outpath, "rb") as fh:
            self.out = fh.read().decode("utf-8", "replace")
        shutil.rmtree(self.dir, ignore_errors=True)
        self.ok, self.why, self.n = verdict(self.proc.returncode, self.out, self.timed_out, self.label)


def parse(argv):
    opts = {"jobs": None, "timeout": None, "log_dir": None, "dirs": []}
    it = iter(argv)
    for a in it:
        if a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif a in ("-j", "--jobs", "--timeout", "--log-dir"):
            v = next(it, None)
            if v is None:
                sys.exit(f"run-tests: {a} без значения")
            if a == "--log-dir":
                opts["log_dir"] = v
            else:
                try:
                    num = int(v) if a != "--timeout" else float(v)
                except ValueError:
                    sys.exit(f"run-tests: {a} {v} — не число")
                if num <= 0:
                    sys.exit(f"run-tests: {a} {v} — нужно больше нуля")
                opts["jobs" if a != "--timeout" else "timeout"] = num
        elif a.startswith("-"):
            sys.exit(f"run-tests: неизвестный ключ {a}")
        else:
            opts["dirs"].append(a)
    return opts


def main(argv):
    opts = parse(argv)
    if not opts["dirs"]:
        print(__doc__)
        return 2
    for d in opts["dirs"]:
        if not os.path.isdir(d):
            print(f"run-tests: нет папки {d}")
            return 2
    par, ser = order(collect(opts["dirs"]))
    total_files = len(par) + len(ser)
    if not total_files:
        print(f"run-tests: ни одного файла tests/test_*.py в {' '.join(opts['dirs'])} — нечего проверять")
        return 1
    cpus, load = os.cpu_count(), load1()
    n = opts["jobs"] or workers(cpus, load)
    print(f"run-tests: {total_files} файлов, воркеров {n} (ядер {cpus}, load1 "
          f"{'—' if load is None else f'{load:.1f}'}), {sys.executable}", flush=True)
    if opts["log_dir"]:
        os.makedirs(opts["log_dir"], exist_ok=True)
    env0 = {k: v for k, v in os.environ.items()
            if not k.startswith("PANTHEON_") and k not in ("FORCE_COLOR", "CLICOLOR_FORCE")}
    env0.update({"NO_COLOR": "1", "PYTHON_COLORS": "0"})
    root = tempfile.mkdtemp(prefix="run-tests-")
    state = {"spawning": False, "pending": None}

    def on_signal(signum, _frame):
        if state["spawning"]:  # Popen ещё не вернул процесс — гасим его сразу после того, как он записан
            state["pending"] = signum
            return
        raise Interrupted(signum)

    old = {s: signal.signal(s, on_signal) for s in SIGNALS}
    running, done, t_all, seq = [], [], time.monotonic(), 0
    try:
        queue = list(par)
        while queue or ser or running:
            limit = n if queue else (0 if running else 1)
            src = queue if queue else ser
            while src and len(running) < limit:
                pdir, label = src.pop(0)
                seq += 1
                state["spawning"] = True
                try:
                    job = Job(pdir, label, sys.executable, root, env0,
                              opts["timeout"] or SLOW.get(label) or TIMEOUT, seq)
                    running.append(job)
                finally:
                    state["spawning"] = False
                if state["pending"] is not None:
                    raise Interrupted(state["pending"])
            for job in list(running):
                if job.exited():
                    pass
                elif time.monotonic() - job.t0 > job.timeout:
                    job.timed_out = True
                    job.kill()
                else:
                    continue
                running.remove(job)
                job.finish()
                done.append(job)
                report(job, opts["log_dir"])
            time.sleep(0.05)
    except Interrupted as e:
        for s in SIGNALS:
            signal.signal(s, signal.SIG_IGN)
        for job in running:
            _killpg(job.proc.pid)
        for job in running:
            job.kill()
            job.fh.close()
        n_killed, running = len(running), []
        shutil.rmtree(root, ignore_errors=True)
        print(f"run-tests: прерван сигналом {e.signum} — погашено файлов: {n_killed}, "
              f"готово {len(done)} из {total_files}", flush=True)
        return 128 + e.signum
    finally:
        # любой другой обрыв раннера (сбой запуска, ошибка в коде) тоже не оставляет идущих файлов
        for job in running:
            job.kill()
            job.fh.close()
        for s, h in old.items():
            signal.signal(s, h)
        shutil.rmtree(root, ignore_errors=True)
    return summary(done, total_files, n, time.monotonic() - t_all)


def report(job, log_dir):
    mark = "ok  " if job.ok else "FAIL"
    why = "" if job.ok else f" · {job.why}"
    print(f"{mark} {job.label} · {job.sec:.1f} с · проверок {job.n}{why}", flush=True)
    if log_dir:
        with open(os.path.join(log_dir, job.label.replace("/", "__") + ".log"), "w") as fh:
            fh.write(job.out)


def summary(done, total_files, n, sec):
    bad = [j for j in done if not j.ok]
    for j in bad:
        lines = j.out.rstrip("\n").splitlines()
        print(f"\n===== {j.label} · {j.why} · последние {min(TAIL, len(lines))} строк =====")
        print("\n".join(lines[-TAIL:]))
    slow = sorted(done, key=lambda j: -j.sec)[:5]
    print("\nмедленные: " + ", ".join(f"{j.label} {j.sec:.0f} с" for j in slow))
    checks_sum = sum(j.n for j in done)
    print(f"итого: файлов {total_files}, ok {len(done) - len(bad)}, FAIL {len(bad)}; проверок {checks_sum}; "
          f"{sec:.0f} с, воркеров {n}", flush=True)
    return 1 if bad or len(done) != total_files else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
