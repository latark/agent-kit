#!/usr/bin/env python3
"""metis-0659: heavy — очередь на два места по порядку прихода, а не опрос замка (новые команды забирали место, старые
ждали больше часа).

Запуск: python3 -I plugins/pantheon/tests/test_heavy_queue.py  (код выхода 0 — все прошли)
- билеты: у первого нет живого билета впереди, у второго есть; снял первый — второй первый; билет умершего владельца
  (процесс завершён через os._exit, замок снят системой) убирается и очередь не держит;
- команда heavy: пока перед ней живой билет, свободное место она не занимает (код 75 по HEAVY_WAIT_MAX, без запуска);
  владелец билета умер или снял его — идёт, свой билет убирает; порядок двух ждущих — по приходу;
- папку билетов создать нельзя — ждёт и идёт опросом мест, как раньше.
"""
import fcntl
import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEAVY = os.path.join(PLUGIN, "bin", "heavy")
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f" {extra}" if not cond else ""))
    if not cond:
        fails.append(name)


def load(state):
    os.environ["PANTHEON_STATE"] = state
    loader = importlib.machinery.SourceFileLoader("heavy_under_test", HEAVY)
    spec = importlib.util.spec_from_loader("heavy_under_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def run(state, *cmd, wait_max=None, extra=None):
    env = {"PATH": os.environ["PATH"], "HOME": state, "PANTHEON_STATE": state}
    if wait_max is not None:
        env["HEAVY_WAIT_MAX"] = str(wait_max)
    return subprocess.run([sys.executable, "-I", HEAVY, *cmd], env=env, capture_output=True, text=True, timeout=60)


def main():
    tmp = tempfile.mkdtemp(prefix="tmp-heavyq-")
    try:
        state = os.path.join(tmp, "state")
        locks = os.path.join(state, "locks")
        os.makedirs(locks)
        for n in ("heavy-cmd-1", "heavy-cmd-2", "heavy-server"):
            open(os.path.join(locks, n + ".lock"), "a").close()
        H = load(state)
        qdir = os.path.join(locks, "heavy-queue")
        left = lambda: sorted(os.listdir(qdir)) if os.path.isdir(qdir) else []  # noqa: E731

        # билеты по порядку прихода
        a, b = H.Ticket(), H.Ticket()
        check("билеты: у первого впереди никого, у второго есть первый", not a.ahead() and b.ahead())
        a.drop()
        check("снял первый — второй первый, чужой билет не остался", not b.ahead() and len(left()) == 1, str(left()))
        # владелец умер (os._exit — без снятия билета): замок снят системой, билет убирается
        pid = os.fork()
        if pid == 0:
            H.Ticket()
            os._exit(0)
        os.waitpid(pid, 0)
        c = H.Ticket()
        check("билет умершего лежит, пока впереди живой b", len(left()) == 3 and c.ahead(), str(left()))
        b.drop()
        check("умерший билет не блокирует и убран: перед c никого, остался только её билет",
              not c.ahead() and left() == [os.path.basename(c.path)], str(left()))
        c.drop()
        check("все билеты сняты — папка пуста", left() == [], str(left()))

        # команда heavy: перед ней живой билет — места свободны, но она ждёт
        front = H.Ticket()
        t0 = time.time()
        r = run(state, "/bin/sh", "-c", "echo ran", wait_max=2)
        check("живой билет впереди: места свободны, команда не запускалась (75)",
              r.returncode == 75 and "ran" not in r.stdout and "жду (0 мин)" in r.stderr and "не дождалась" in r.stderr,
              f"{r.returncode} {r.stdout!r} {r.stderr!r}")
        check("не дождавшаяся команда свой билет убрала", left() == [os.path.basename(front.path)], str(left()))
        front.drop()
        r = run(state, "/bin/sh", "-c", "echo ran", wait_max=5)
        check("очередь пуста — команда идёт сразу, код выхода команды сохранён",
              r.returncode == 0 and "ran" in r.stdout and left() == [], f"{r.returncode} {r.stdout!r} {r.stderr!r} {left()}")
        r = run(state, "/bin/sh", "-c", "exit 3", wait_max=5)
        check("код выхода команды — наружу", r.returncode == 3, str(r.returncode))

        # владелец билета умер (os._exit), места свободны — команда идёт и чистит
        pid = os.fork()
        if pid == 0:
            H.Ticket()
            os._exit(0)
        os.waitpid(pid, 0)
        r = run(state, "/bin/sh", "-c", "echo ran", wait_max=5)
        check("билет умершего впереди не держит команду", r.returncode == 0 and "ran" in r.stdout and left() == [],
              f"{r.returncode} {r.stderr!r} {left()}")

        # порядок двух ждущих: оба места заняты, пришли A, потом B; места освободились — A первая
        holds = []
        for n in ("heavy-cmd-1", "heavy-cmd-2"):
            fd = os.open(os.path.join(locks, n + ".lock"), os.O_RDONLY)
            fcntl.flock(fd, fcntl.LOCK_EX)
            holds.append(fd)
        order = os.path.join(tmp, "order")
        env = {"PATH": os.environ["PATH"], "HOME": state, "PANTHEON_STATE": state}
        procs = []
        for name in ("A", "B", "C"):
            procs.append(subprocess.Popen([sys.executable, "-I", HEAVY, "/bin/sh", "-c", f"echo {name} >> {order}; sleep 1"],
                                          env=env, stderr=subprocess.DEVNULL))
            time.sleep(0.5)
        check("трое пришли — три билета", len(left()) == 3, str(left()))
        for fd in holds:  # оба места свободны сразу: без очереди выиграл бы тот, чей опрос случился раньше
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        for p in procs:
            p.wait(timeout=60)
        got = open(order).read().split()
        check("порядок запуска — по приходу A, B, C", got == ["A", "B", "C"], str(got))
        check("после прогона билетов не осталось", left() == [], str(left()))

        # папку билетов создать нельзя (в песочнице) — старое поведение: опрос мест
        shutil.rmtree(qdir)
        open(qdir, "w").close()  # на месте папки файл: makedirs упадёт
        r = run(state, "/bin/sh", "-c", "echo ran", wait_max=5)
        check("папку билетов не создать — команда идёт опросом мест", r.returncode == 0 and "ran" in r.stdout,
              f"{r.returncode} {r.stderr!r}")
        os.unlink(qdir)
        print(f"({time.time() - t0:.0f} с)")
    finally:
        shutil.rmtree(tmp, True)
    print(f"тестов: {len(fails)} не прошло")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
