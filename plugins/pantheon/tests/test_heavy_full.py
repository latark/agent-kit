#!/usr/bin/env python3
"""metis-1007: heavy — полный набор тестов занимает жетон locks/heavy-full.lock, на Mac идёт один.

Запуск: python3 -I plugins/pantheon/tests/test_heavy_full.py  (код выхода 0 — все прошли)
- правило полного набора (lib/fullsuite.py, общее с outside.runner_args): run-tests.py с папками и ключами -j/--timeout/
  --log-dir — полный; --affected/--only, без папок, чужая команда — нет; strict (outside) отвергает абсолютный путь;
- два полных набора разом: второй ждёт жетон (75 по HEAVY_WAIT_MAX, не запускался), узкий (--affected) и одиночная
  команда в это время идут; жетон свободен — полный идёт, код выхода наружу;
- sh -c "… run-tests.py папки" тоже полный; файла жетона нет — heavy создаёт; не создать (песочница) — идёт без него;
- `heavy --status` показывает heavy-full.
"""
import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
import time

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEAVY = os.path.join(PLUGIN, "bin", "heavy")
sys.path.insert(0, os.path.join(PLUGIN, "lib"))
import fullsuite as F  # noqa: E402

fails, total = [], []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f" {extra}" if not cond else ""))
    total.append(name)
    if not cond:
        fails.append(name)


def env_for(state, wait_max=None):
    env = {"PATH": os.environ["PATH"], "HOME": state, "PANTHEON_STATE": state}
    if wait_max is not None:
        env["HEAVY_WAIT_MAX"] = str(wait_max)
    return env


def run(state, *cmd, wait_max=None, extra=None):
    env = env_for(state, wait_max)
    env.update(extra or {})
    return subprocess.run([sys.executable, "-I", HEAVY, *cmd], env=env, capture_output=True, text=True, timeout=60)


def main():
    tmp = tempfile.mkdtemp(prefix="tmp-heavyfull-")
    try:
        state = os.path.join(tmp, "state")
        locks = os.path.join(state, "locks")
        os.makedirs(locks)
        for n in ("heavy-cmd-1", "heavy-cmd-2", "heavy-server", "heavy-full"):
            open(os.path.join(locks, n + ".lock"), "a").close()
        fake = os.path.join(tmp, "run-tests.py")
        with open(fake, "w") as fh:
            fh.write("import os, sys, time\ntime.sleep(float(os.environ.get('FS', '0')))\n"
                     "print('suite ran', sys.argv[1:])\nsys.exit(int(os.environ.get('FX', '0')))\n")
        py = sys.executable

        yes = [[py, "-I", "plugins/pantheon/scripts/run-tests.py", "-j", "3", "plugins/guard", "plugins/pantheon"],
               [py, "/abs/x/scripts/run-tests.py", "plugins/guard"],
               ["bash", "-c", "cd x && python3 scripts/run-tests.py -j 3 plugins/guard"]]
        no = [[py, "scripts/run-tests.py", "--affected", "plugins/guard"],
              [py, "scripts/run-tests.py", "--only", "a.py", "plugins/guard"],
              [py, "scripts/run-tests.py"],
              [py, "-I", "plugins/guard/tests/test_x.py"],
              ["pnpm", "test"]]
        run_ = "python3.14 -I plugins/pantheon/scripts/run-tests.py -j 3 plugins/guard plugins/pantheon"
        yes += [["sh", "-c", f"{run_} 2>&1 | tail -20"],
                ["sh", "-c", f"{run_} 2>&1 | grep -E FAIL"],
                ["sh", "-c", f"{run_} >log.txt 2>&1 || true"],
                ["sh", "-c", f"{run_} > log.txt"],
                ["sh", "-c", f"cd x && {run_} ; echo done"]]
        no += [["sh", "-c", "grep foo plugins/pantheon/scripts/run-tests.py plugins/guard"],
               ["sh", "-c", f"{run_} --affected | tail"],
               ["grep", "foo", "plugins/pantheon/scripts/run-tests.py", "plugins/guard"],
               ["sh", "-c", f"echo {run_.split('python3.14')[0]}run-tests.py plugins/x"]]
        for c in yes:
            check(f"правило: полный {c[-1][:40]}", F.is_full(c) is True)
        for c in no:
            check(f"правило: не полный {' '.join(c)[-50:]}", F.is_full(c) is False)
        check("общее правило: strict отвергает абсолютный путь, прежний ответ outside",
              F.runner_args("python3 /a/run-tests.py plugins/x") is None
              and F.runner_args("python3 tools/run-tests.py -j 3 plugins/kit # c") == ("tools/run-tests.py", ["plugins/kit"]))

        # lib/fullsuite.py есть, но не грузится: heavy пишет одну строку в stderr, команда идёт как не полный набор
        bad = os.path.join(tmp, "badkit")
        os.makedirs(os.path.join(bad, "bin"))
        os.makedirs(os.path.join(bad, "lib"))
        shutil.copy(HEAVY, os.path.join(bad, "bin", "heavy"))
        with open(os.path.join(bad, "lib", "fullsuite.py"), "w") as fh:
            fh.write("raise ImportError('сломан')\n")
        r = subprocess.run([sys.executable, "-I", os.path.join(bad, "bin", "heavy"), py, fake, "plugins/x"],
                           env=env_for(state, 5), capture_output=True, text=True, timeout=60)
        lines = [x for x in r.stderr.splitlines() if "fullsuite не загрузился" in x]
        check("fullsuite не загрузился: строка в stderr, команда идёт",
              r.returncode == 0 and "suite ran" in r.stdout and len(lines) == 1
              and "сломан" in lines[0] and "жетон полного набора не работает" in lines[0],
              f"{r.returncode} {r.stderr!r}")

        hold = os.open(os.path.join(locks, "heavy-full.lock"), os.O_RDONLY)
        fcntl.flock(hold, fcntl.LOCK_EX)
        r = run(state, py, fake, "plugins/x", wait_max=2)
        check("второй полный: ждёт жетон, 75, не запускался",
              r.returncode == 75 and "suite ran" not in r.stdout and "полный набор" in r.stderr
              and "не дождалась" in r.stderr, f"{r.returncode} {r.stdout!r} {r.stderr!r}")
        r = run(state, "/bin/sh", "-c", f"{py} {fake} plugins/x", wait_max=2)
        check("полный в sh -c тоже ждёт", r.returncode == 75, f"{r.returncode} {r.stderr!r}")
        r = run(state, py, fake, "--affected", "plugins/x", wait_max=5)
        check("узкий (--affected) идёт при занятом жетоне", r.returncode == 0 and "suite ran" in r.stdout,
              f"{r.returncode} {r.stderr!r}")
        r = run(state, "/bin/sh", "-c", "echo single", wait_max=5)
        check("одиночная команда идёт при занятом жетоне", r.returncode == 0 and "single" in r.stdout, r.stderr)
        r = run(state, "--status")
        check("--status показывает heavy-full занятым", "heavy-full: занято" in r.stdout, r.stdout)
        fcntl.flock(hold, fcntl.LOCK_UN)
        os.close(hold)
        r = run(state, py, fake, "plugins/x", wait_max=5)
        check("жетон свободен — полный идёт", r.returncode == 0 and "suite ran" in r.stdout,
              f"{r.returncode} {r.stderr!r}")
        r = run(state, py, fake, "plugins/x", wait_max=5, extra={"FX": "3"})
        check("код выхода полного набора — наружу", r.returncode == 3, str(r.returncode))

        # гонка: первый полный идёт, второй ждёт, узкий проходит
        e1 = env_for(state, 20)
        e1["FS"] = "4"
        p1 = subprocess.Popen([py, "-I", HEAVY, py, fake, "plugins/a"], env=e1, stdout=subprocess.PIPE, text=True)
        time.sleep(1.5)
        r2 = run(state, py, fake, "plugins/b", wait_max=1)
        rn = run(state, py, fake, "--affected", "plugins/b", wait_max=5)
        out1 = p1.communicate(timeout=30)[0]
        check("гонка: второй полный отложен (75), узкий прошёл, первый дошёл",
              r2.returncode == 75 and rn.returncode == 0 and p1.returncode == 0 and "suite ran" in out1,
              f"{r2.returncode} {rn.returncode} {p1.returncode}")
        r = run(state, py, fake, "plugins/c", wait_max=3)
        check("после конца первого жетон свободен", r.returncode == 0, f"{r.returncode} {r.stderr!r}")

        os.unlink(os.path.join(locks, "heavy-full.lock"))
        r = run(state, py, fake, "plugins/x", wait_max=5)
        check("нет файла жетона — heavy создаёт, команда идёт",
              r.returncode == 0 and os.path.exists(os.path.join(locks, "heavy-full.lock")), r.stderr)
        os.unlink(os.path.join(locks, "heavy-full.lock"))
        os.chmod(locks, 0o500)
        try:
            r = run(state, py, fake, "plugins/x", wait_max=5)
            check("жетон не создать — идёт без него", r.returncode == 0 and "suite ran" in r.stdout,
                  f"{r.returncode} {r.stderr!r}")
        finally:
            os.chmod(locks, 0o700)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(total) - len(fails)}/{len(total)} ok")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
