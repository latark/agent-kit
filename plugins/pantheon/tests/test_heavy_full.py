#!/usr/bin/env python3
"""metis-1007: heavy — полный набор тестов занимает жетон locks/heavy-full.lock, на Mac идёт один.

Запуск: python3 -I plugins/pantheon/tests/test_heavy_full.py  (код выхода 0 — все прошли)
- правило полного набора (lib/fullsuite.py, общее с outside.runner_args): run-tests.py с папками и ключами -j/--timeout/
  --log-dir — полный; --affected/--only, без папок, чужая команда — нет; strict (outside) отвергает абсолютный путь;
- два полных набора разом: второй ждёт жетон (75 по HEAVY_WAIT_MAX, не запускался), узкий (--affected) и одиночная
  команда в это время идут; жетон свободен — полный идёт, код выхода наружу;
- sh -c "… run-tests.py папки" тоже полный; файла жетона нет — heavy создаёт; не создать (песочница) — идёт без него;
- `heavy --status` показывает heavy-full;
- metis-1174: репозиторий со строкой ci: в .pantheon-verify (cwd или git-корень файла теста) — heavy отказывает командам
  тестов (код 2, без запуска), HEAVY_LOCAL_TESTS=1 — запасной путь; все прочие вызовы heavy — с cwd вне такого репозитория;
- heavy --probe: в ci-репозитории только один файл test_*.py, предел 120 с (HEAVY_PROBE_MAX уменьшает) — дольше код 124 и
  группа процессов убита; места — как у обычной команды, жетон полного набора не берёт.
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
    # cwd — не репозиторий со строкой ci: (metis-1174: heavy там отказывает командам тестов)
    return subprocess.run([sys.executable, "-I", HEAVY, *cmd], env=env, capture_output=True, text=True, timeout=60,
                          cwd=state)


def abs_path_checks(tmp, ci, nci, in_repo):
    py = sys.executable
    # Д1 argus #460: файл теста в репозитории «только CI» по абсолютному пути из другой папки — тоже отказ
    r = in_repo(tmp, py, os.path.join(ci, "sub", "test_abs.py"))
    check("ci:: абсолютный путь в ci-репозиторий из другой папки — отказ", r.returncode == 2
          and r.stderr.rstrip().endswith("запасной путь — pantheon outside test"), f"{r.returncode} {r.stderr!r}")
    r = in_repo(tmp, "/bin/sh", "-c", f"{py} {os.path.join(ci, 'sub', 'test_abs.py')}")
    check("ci:: абсолютный путь в ci-репозиторий внутри sh -c — отказ", r.returncode == 2, f"{r.returncode}")
    nfile = os.path.join(nci, "test_n.py")
    with open(nfile, "w") as fh:
        fh.write("print('ran n')\n")
    r = in_repo(tmp, py, nfile)
    check("ci:: абсолютный путь в репозиторий без ci: — идёт", r.returncode == 0 and "ran n" in r.stdout,
          f"{r.returncode} {r.stderr!r}")


def probe_checks(tmp, state, locks, ci, nci, ftest, fake, in_repo):
    """metis-1174, решение владельца 14.11: heavy --probe — один файл тестов в репозитории «только CI», предел 120 с."""
    py = sys.executable
    ftest2 = os.path.join(tmp, "test_fake2.py")
    shutil.copy(ftest, ftest2)
    r = in_repo(ci, "--probe", py, "-I", ftest)
    check("probe: один файл в ci-репозитории идёт", r.returncode == 0 and "ran test" in r.stdout,
          f"{r.returncode} {r.stderr!r}")
    r = in_repo(ci, "--probe", "nice", "-n", "5", py, "-X", "dev", "-I", ftest, "-v")
    check("probe: с обёрткой, флагами со значением и аргументами — идёт", r.returncode == 0 and "ran test" in r.stdout,
          f"{r.returncode} {r.stderr!r}")
    for name, cmd in (("run-tests.py", [py, "-I", fake, "plugins/x"]), ("два файла", [py, ftest, ftest2]),
                      ("sh -c", ["sh", "-c", f"{py} {ftest}"]), ("pytest", ["pytest", ftest]),
                      ("-m pytest", [py, "-m", "pytest", ftest]), ("-m unittest", [py, "-m", "unittest"]),
                      ("python -c", [py, "-c", "print('ran test')"]), ("не test_*.py", [py, fake.replace("run-tests", "x")]),
                      ("не python", ["/bin/echo", "ran test"])):
        r = in_repo(ci, "--probe", *cmd)
        last = (r.stderr.splitlines() or [""])[-1]
        check(f"probe: отказ в ci-репозитории — {name}", r.returncode == 2 and "ran test" not in r.stdout
              and last.startswith("heavy: --probe в репозитории «только CI» — один файл тестов")
              and last.endswith("— не запускалась"), f"{r.returncode} {r.stderr!r}")
    r = in_repo(tmp, "--probe", py, os.path.join(ci, "sub", "test_abs.py"), ftest2)
    check("probe: два файла, первый — в ci-репозитории по абсолютному пути — отказ", r.returncode == 2, f"{r.returncode}")
    r = in_repo(nci, "--probe", "/bin/sh", "-c", "echo plain")
    check("probe: вне ci-репозитория — любая команда идёт", r.returncode == 0 and "plain" in r.stdout,
          f"{r.returncode} {r.stderr!r}")
    probe_timeout_checks(tmp, ci, nci, in_repo)
    probe_queue_checks(state, locks, fake)


def probe_timeout_checks(tmp, ci, nci, in_repo):
    py = sys.executable
    # предел: процесс и его потомок убиты (группа процессов), код 124 и причина последней строкой
    slow = os.path.join(tmp, "test_slow.py")
    with open(slow, "w") as fh:
        fh.write("import os, signal, subprocess, sys, time\n"
                 "if sys.argv[2] == 'ign':\n    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                 "c = subprocess.Popen(['sleep', '30'])\n"
                 "open(sys.argv[1], 'w').write(f'{os.getpid()} {c.pid}')\ntime.sleep(30)\n")
    for mode, cwd in (("term", ci), ("ign", nci)):
        pids = os.path.join(tmp, f"pids-{mode}")
        t0 = time.monotonic()
        r = in_repo(cwd, "--probe", py, slow, pids, mode, extra={"HEAVY_PROBE_MAX": "1"})
        took = time.monotonic() - t0
        time.sleep(0.5)
        alive = []
        for pid in open(pids).read().split():
            try:
                os.kill(int(pid), 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
        last = (r.stderr.splitlines() or [""])[-1]
        fast = took < 4 if mode == "term" else took >= 5.5
        check(f"probe: дольше предела ({mode}) — код 124, процесс и потомок убиты, причина последней строкой",
              r.returncode == 124 and not alive and fast and last.startswith("heavy: --probe дольше 1 с")
              and last.endswith("код 124"), f"{r.returncode} {alive} {took:.1f} {r.stderr!r}")


def probe_queue_checks(state, locks, fake):
    py = sys.executable
    # очередь: места — как у обычной команды, жетон полного набора не берёт
    hold = os.open(os.path.join(locks, "heavy-full.lock"), os.O_RDONLY | os.O_CREAT, 0o644)
    fcntl.flock(hold, fcntl.LOCK_EX)
    r = run(state, "--probe", py, fake, "plugins/x", wait_max=2)
    check("probe: жетон полного набора занят — идёт (жетон не берёт)", r.returncode == 0 and "suite ran" in r.stdout,
          f"{r.returncode} {r.stderr!r}")
    fcntl.flock(hold, fcntl.LOCK_UN)
    os.close(hold)
    held = []
    for n in ("heavy-cmd-1", "heavy-cmd-2"):
        fd = os.open(os.path.join(locks, n + ".lock"), os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_EX)
        held.append(fd)
    r = run(state, "--probe", "/bin/sh", "-c", "echo plain", wait_max=1)
    check("probe: оба места заняты — ждёт, как обычная команда (75)", r.returncode == 75 and "plain" not in r.stdout,
          f"{r.returncode} {r.stderr!r}")
    for fd in held:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    # предел: HEAVY_PROBE_MAX только уменьшает PROBE_MAX (120 с)
    import importlib.util
    from importlib.machinery import SourceFileLoader
    loader = SourceFileLoader("heavy_mod", HEAVY)
    H = importlib.util.module_from_spec(importlib.util.spec_from_loader("heavy_mod", loader))
    loader.exec_module(H)
    got = {}
    for v in ("", "1", "99999", "0", "abc", "-5"):
        os.environ["HEAVY_PROBE_MAX"] = v
        got[v] = H.probe_limit()
    os.environ.pop("HEAVY_PROBE_MAX", None)
    check("probe: предел 120 с, HEAVY_PROBE_MAX только уменьшает",
          H.PROBE_MAX == 120 and got == {"": 120, "1": 1, "99999": 120, "0": 120, "abc": 120, "-5": 120}, str(got))


def ci_checks(tmp, state, locks, fake):
    py = sys.executable
    # metis-1174: репозиторий со строкой ci: в .pantheon-verify — heavy отказывает командам тестов (код 2, без запуска)
    ci = os.path.join(tmp, "cirepo")
    os.makedirs(os.path.join(ci, ".git"))
    os.makedirs(os.path.join(ci, "sub", "deep"))
    with open(os.path.join(ci, ".pantheon-verify"), "w") as fh:
        fh.write("python3.14 -I run-tests.py plugins/x\nci: uvx ruff check .\n")
    nci = os.path.join(tmp, "nocirepo")
    os.makedirs(os.path.join(nci, ".git"))
    with open(os.path.join(nci, ".pantheon-verify"), "w") as fh:
        fh.write("python3.14 -I run-tests.py plugins/x\n# ci: только в комментарии\n")
    wt = os.path.join(tmp, "wtrepo")  # worktree: .git — файл
    os.makedirs(wt)
    with open(os.path.join(wt, ".git"), "w") as fh:
        fh.write("gitdir: /nowhere\n")
    with open(os.path.join(wt, ".pantheon-verify"), "w") as fh:
        fh.write("ci: true\n")
    ftest = os.path.join(tmp, "test_fake.py")
    with open(ftest, "w") as fh:
        fh.write("print('ran test')\n")
    stamp = os.path.join(tmp, "stamp")

    def in_repo(cwd, *cmd, extra=None):
        env = env_for(state, 5)
        env.update(extra or {})
        return subprocess.run([sys.executable, "-I", HEAVY, *cmd], env=env, cwd=cwd, capture_output=True, text=True,
                              timeout=60)

    refuse = [[py, "-I", "plugins/guard/tests/test_x.py"], [py, ftest], ["python3.14", "-I", "scripts/run-tests.py", "x"],
              ["pytest", "-q"], ["uv", "run", "pytest"], [py, "-m", "unittest", "discover"], [py, "-m", "pytest"],
              ["env", "A=1", py, ftest], ["sh", "-c", f"{py} {ftest} 2>&1 | tail -5"],
              ["bash", "-c", "cd x && python3 plugins/pantheon/scripts/run-tests.py --affected plugins/x; echo $?"],
              # пропуски разбора (argus #460): флаги python со значением, -lc/-ec, обёртки с аргументами
              [py, "-X", "dev", ftest], [py, "-W", "error", ftest], [py, "-Xdev", "-I", ftest],
              ["bash", "-lc", f"{py} {ftest}"], ["bash", "-ec", f"{py} {ftest}"],
              ["nice", "-n", "10", py, ftest], ["env", "-C", ci, py, ftest], ["timeout", "600", py, ftest],
              ["uv", "run", "--with", "x", "pytest"], ["timeout", "-s", "KILL", "600", "env", "A=1", py, ftest]]
    for c in refuse:
        r = in_repo(ci, *c)
        check(f"ci:: отказ {' '.join(c)[:50]}",
              r.returncode == 2 and "ran test" not in r.stdout and r.stderr.splitlines()[-1].startswith(
                  "heavy: тесты этого репозитория идут в CI (строка ci: в .pantheon-verify) — итог: gh pr checks <N>;")
              and r.stderr.rstrip().endswith("запасной путь — pantheon outside test"), f"{r.returncode} {r.stderr!r}")
    r = in_repo(os.path.join(ci, "sub", "deep"), py, ftest)
    check("ci:: из подпапки репозитория — отказ", r.returncode == 2, f"{r.returncode} {r.stderr!r}")
    r = in_repo(wt, py, ftest)
    check("ci:: worktree (.git — файл) — отказ", r.returncode == 2, f"{r.returncode} {r.stderr!r}")
    r = in_repo(ci, py, ftest, extra={"HEAVY_LOCAL_TESTS": "1"})
    check("ci:: HEAVY_LOCAL_TESTS=1 — запасной путь идёт", r.returncode == 0 and "ran test" in r.stdout,
          f"{r.returncode} {r.stderr!r}")
    r = in_repo(ci, py, ftest, extra={"HEAVY_LOCAL_TESTS": "0"})
    check("ci:: HEAVY_LOCAL_TESTS=0 — не обход", r.returncode == 2, f"{r.returncode}")
    for name, cwd, cmd in (("не тест (pnpm build-подобная)", ci, ["/bin/sh", "-c", f"echo built > {stamp}"]),
                           ("grep по файлу теста", ci, ["grep", "print", ftest]),
                           ("python -c", ci, [py, "-c", "print('ran test')"]),
                           ("репозиторий без строки ci:", nci, [py, ftest]),
                           ("вне git", tmp, [py, ftest])):
        r = in_repo(cwd, *cmd)
        check(f"ci:: идёт — {name}", r.returncode == 0, f"{r.returncode} {r.stderr!r}")
    abs_path_checks(tmp, ci, nci, in_repo)
    probe_checks(tmp, state, locks, ci, nci, ftest, fake, in_repo)


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
                           env=env_for(state, 5), capture_output=True, text=True, timeout=60, cwd=state)
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
        p1 = subprocess.Popen([py, "-I", HEAVY, py, fake, "plugins/a"], env=e1, stdout=subprocess.PIPE, text=True,
                              cwd=state)
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

        ci_checks(tmp, state, locks, fake)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(total) - len(fails)}/{len(total)} ok")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
