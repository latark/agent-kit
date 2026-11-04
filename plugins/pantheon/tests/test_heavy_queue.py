#!/usr/bin/env python3
"""metis-0659: heavy — очередь на два места по порядку прихода, а не опрос замка (новые команды забирали место, старые
ждали больше часа).

Запуск: python3 -I plugins/pantheon/tests/test_heavy_queue.py  (код выхода 0 — все прошли)
- билеты: у первого нет живого билета впереди, у второго есть; снял первый — второй первый; билет умершего владельца
  (процесс завершён через os._exit, замок снят системой) убирается и очередь не держит;
- команда heavy: пока перед ней живой билет, свободное место она не занимает (код 75 по HEAVY_WAIT_MAX, без запуска);
  владелец билета умер или снял его — идёт, свой билет убирает; порядок двух ждущих — по приходу;
- папку билетов создать нельзя — ждёт и идёт опросом мест, как раньше;
- билет только создан (пустой, свежий, блокировки ещё нет) — впереди и не удаляется; пустой старый — убирается;
- ждущая команда обновляет время билета; остановленная (SIGSTOP) с билетом старше TICKET_STALE очередь не держит,
  а её билет остаётся; `heavy --status` считает только живые билеты;
- после сна Mac дольше TICKET_STALE голова очереди не застывает: возраст — от прошлого опроса ждущего (metis-0805).
"""
import fcntl
import importlib.machinery
import importlib.util
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEAVY = os.path.join(PLUGIN, "bin", "heavy")
fails = []
total = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f" {extra}" if not cond else ""))
    total.append(name)
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
              not c.ahead() and left() == [c.name], str(left()))
        c.drop()
        check("все билеты сняты — папка пуста", left() == [], str(left()))

        # билет только создан: файл пуст, блокировку владелец ещё не взял — это не умерший (TICKET_GRACE)
        young = os.path.join(qdir, "00000000000000000002-2")
        open(young, "w").close()
        d = H.Ticket()
        check("пустой свежий билет без блокировки впереди держит очередь и не удалён",
              d.ahead() and os.path.exists(young), str(left()))
        old = time.time() - H.TICKET_GRACE - 5
        os.utime(young, (old, old))
        check("пустой билет старше TICKET_GRACE — умерший: убран, очередь не держит",
              not d.ahead() and not os.path.exists(young), str(left()))
        d.drop()

        # команда heavy: перед ней живой билет — места свободны, но она ждёт
        front = H.Ticket()
        t0 = time.time()
        r = run(state, "/bin/sh", "-c", "echo ran", wait_max=2)
        check("живой билет впереди: места свободны, команда не запускалась (75)",
              r.returncode == 75 and "ran" not in r.stdout and "жду (0 мин)" in r.stderr and "не дождалась" in r.stderr,
              f"{r.returncode} {r.stdout!r} {r.stderr!r}")
        check("не дождавшаяся команда свой билет убрала", left() == [front.name], str(left()))
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

        # обновление билета: смена времени запрещена (песочница) — время обновляет запись pid
        f = H.Ticket()
        fpath = os.path.join(qdir, f.name)
        old = time.time() - 1000
        os.utime(fpath, (old, old))
        real_utime = os.utime

        def no_utime(*_a, **_k):
            raise PermissionError("utime запрещён")
        H.os.utime = no_utime
        try:
            f.touch()
        finally:
            H.os.utime = real_utime
        check("utime запрещён — билет обновлён записью pid", os.stat(fpath).st_mtime > time.time() - 60
              and open(fpath).read() == f"{os.getpid()}\n", str(os.stat(fpath).st_mtime))
        f.drop()

        # --status: умерший билет не в счёт, живой — в счёте
        pid = os.fork()
        if pid == 0:
            H.Ticket()
            os._exit(0)
        os.waitpid(pid, 0)
        front = H.Ticket()
        r = run(state, "--status")
        check("--status: живой билет и умерший — в очереди 1", "очередь на места: 1" in r.stdout and len(left()) == 2,
              f"{r.stdout!r} {left()}")
        front.drop()
        r = run(state, "--status")
        check("--status: только умерший — очереди нет", "очередь на места" not in r.stdout, repr(r.stdout))
        e = H.Ticket()
        e.ahead()  # умерший впереди убирается при проверке очереди
        e.drop()
        check("умерший билет убран, очередь пуста перед следующим случаем", left() == [], str(left()))

        # порядок трёх ждущих: оба места заняты, пришли A, B, C; освободилось одно место — идут по одному, A, B, C
        holds = []
        for n in ("heavy-cmd-1", "heavy-cmd-2"):
            fd = os.open(os.path.join(locks, n + ".lock"), os.O_RDONLY)
            fcntl.flock(fd, fcntl.LOCK_EX)
            holds.append(fd)
        order = os.path.join(tmp, "order")
        env = {"PATH": os.environ["PATH"], "HOME": state, "PANTHEON_STATE": state}
        procs = []
        for i, name in enumerate(("A", "B", "C"), 1):
            procs.append(subprocess.Popen([sys.executable, "-I", HEAVY, "/bin/sh", "-c", f"echo {name} >> {order}; sleep 1"],
                                          env=env, stderr=subprocess.DEVNULL))
            # metis-0759: ждём появления билета этой команды (до 30 с), а не фиксированную паузу: под нагрузкой
            # запуск python дольше пол-секунды, и порядок прихода держится только пока билет предыдущей уже лежит
            deadline = time.time() + 30
            while len(left()) < i and time.time() < deadline:
                time.sleep(0.05)
        check("трое пришли — три билета", len(left()) == 3, str(left()))
        # одно место свободно, второе держим: команды идут строго по одной, и порядок строк в order — порядок мест
        # (при двух свободных A и B шли бы вместе, и строку первой мог записать любой). Без очереди место берёт тот,
        # чей опрос случился раньше; живой билет впереди проверен выше детерминированно (код 75)
        fcntl.flock(holds[0], fcntl.LOCK_UN)
        os.close(holds[0])
        for p in procs:
            p.wait(timeout=120)
        fcntl.flock(holds[1], fcntl.LOCK_UN)
        os.close(holds[1])
        got = open(order).read().split()
        check("порядок запуска — по приходу A, B, C", got == ["A", "B", "C"], str(got))
        check("после прогона билетов не осталось", left() == [], str(left()))

        # застывший владелец (SIGSTOP) во главе очереди: ждущая команда обновляет время билета, остановленная — нет;
        # билет старше TICKET_STALE очередь обходит и не удаляет
        holds = []
        for n in ("heavy-cmd-1", "heavy-cmd-2"):
            fd = os.open(os.path.join(locks, n + ".lock"), os.O_RDONLY)
            fcntl.flock(fd, fcntl.LOCK_EX)
            holds.append(fd)
        p1 = subprocess.Popen([sys.executable, "-I", HEAVY, "/bin/sh", "-c", "echo P1"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        deadline = time.time() + 30
        while not left() and time.time() < deadline:
            time.sleep(0.05)
        tk = os.path.join(qdir, left()[0]) if left() else ""
        stale = time.time() - H.TICKET_STALE - 60
        if tk:
            os.utime(tk, (stale, stale))
        deadline = time.time() + 30
        while tk and os.path.exists(tk) and os.stat(tk).st_mtime < stale + 30 and time.time() < deadline:
            time.sleep(0.05)
        check("ждущая команда обновляет время своего билета",
              bool(tk) and os.path.exists(tk) and os.stat(tk).st_mtime > time.time() - 30, str(left()))
        os.kill(p1.pid, signal.SIGSTOP)
        os.waitpid(p1.pid, os.WUNTRACED)  # дождались остановки: после неё билет больше не обновится
        if tk:
            os.utime(tk, (stale, stale))
        for fd in holds:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        try:
            r = run(state, "/bin/sh", "-c", "echo ran", wait_max=15)
            check("остановленный владелец с билетом старше TICKET_STALE не держит очередь: команда пошла",
                  r.returncode == 0 and "ran" in r.stdout, f"{r.returncode} {r.stderr!r}")
            check("билет остановленного не удалён (владелец жив)", bool(tk) and os.path.exists(tk), str(left()))
            r = run(state, "--status")
            check("--status: застывший билет не в счёте", "очередь на места" not in r.stdout, repr(r.stdout))
        finally:
            p1.kill()  # SIGKILL снимает и остановленный процесс
            p1.wait(timeout=30)
        e = H.Ticket()
        e.ahead()  # билет убитого — умерший: убирается при проверке очереди
        e.drop()
        check("билет убитого владельца убран", left() == [], str(left()))

        # metis-0805: сон Mac дольше TICKET_STALE — оба билета не обновлялись, а их владельцы живы. Проснувшийся ждущий
        # не обходит голову: возраст её билета — от своего прошлого опроса (до сна), а не от «сейчас». Голова и дальше не
        # обновляется (остановлена) — через TICKET_STALE своих опросов она застывает, как раньше
        head, me = H.Ticket(), H.Ticket()
        before_sleep = time.time() - H.TICKET_STALE - 60
        for t in (head, me):
            os.utime(os.path.join(qdir, t.name), (before_sleep, before_sleep))
        me.prev = me.last = before_sleep  # последний опрос ждущего — до сна
        me.touch()  # первый опрос после сна
        check("после сна Mac голова очереди не застыла: ждущий её не обходит", me.ahead() is True,
              f"prev={me.prev} head={os.stat(os.path.join(qdir, head.name)).st_mtime}")
        me.touch()  # следующий опрос: голова так и не обновилась — она остановлена, а не спала
        check("голова не обновилась и после сна — застыла, ждущий её обходит", me.ahead() is False, str(left()))
        r = run(state, "--status")
        check("--status: билеты старше TICKET_STALE от «сейчас» не в счёте", "очередь на места" not in r.stdout,
              repr(r.stdout))
        me.drop()
        head.drop()
        check("билеты сна убраны", left() == [], str(left()))

        # папку билетов создать нельзя (в песочнице) — старое поведение: опрос мест
        shutil.rmtree(qdir)
        open(qdir, "w").close()  # на месте папки файл: makedirs упадёт
        r = run(state, "/bin/sh", "-c", "echo ran", wait_max=5)
        check("папку билетов не создать — команда идёт опросом мест", r.returncode == 0 and "ran" in r.stdout,
              f"{r.returncode} {r.stderr!r}")
        os.unlink(qdir)

        # FIFO в очереди (его мог положить кто угодно с записью в папку) не вешает команду и остаётся на месте
        os.makedirs(qdir)
        fifo = os.path.join(qdir, "00000000000000000001-1")
        os.mkfifo(fifo)
        env = {"PATH": os.environ["PATH"], "HOME": state, "PANTHEON_STATE": state}
        p = subprocess.Popen([sys.executable, "-I", HEAVY, "/bin/sh", "-c", "echo ran"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            out, err = p.communicate(timeout=15)
            hung = False
        except subprocess.TimeoutExpired:
            p.kill()  # SIGKILL
            out, err = p.communicate()
            hung = True
        check("FIFO в очереди: команда не висит и выполнилась", not hung and p.returncode == 0 and "ran" in out,
              f"hung={hung} {p.returncode} {out!r} {err!r}")
        check("FIFO не удалён (удаляются только обычные файлы), билет команды снят",
              left() == ["00000000000000000001-1"] and stat.S_ISFIFO(os.lstat(fifo).st_mode), str(left()))
        os.unlink(fifo)
        os.rmdir(qdir)

        # ссылка на месте папки очереди: heavy идёт и вне песочницы — в цели ничего не трогает
        victim = os.path.join(tmp, "victim")
        os.makedirs(victim)
        for n, data in (("secret.txt", "SECRET=1\n"), ("00000000000000000000-1", "1\n")):
            with open(os.path.join(victim, n), "w") as f:
                f.write(data)
        os.symlink(victim, qdir)
        r = run(state, "/bin/sh", "-c", "echo ran", wait_max=5)
        check("ссылка на месте папки очереди: команда выполнилась", r.returncode == 0 and "ran" in r.stdout,
              f"{r.returncode} {r.stderr!r}")
        check("ссылка на папку: файлы цели целы, secret.txt на месте",
              sorted(os.listdir(victim)) == ["00000000000000000000-1", "secret.txt"]
              and open(os.path.join(victim, "secret.txt")).read() == "SECRET=1\n", str(sorted(os.listdir(victim))))
        t = H.Ticket()
        check("Ticket по ссылке на папку: билета нет", t.fd is None and not t.ahead())
        t.drop()
        os.unlink(qdir)

        # --server: за жетон очереди нет, за два места есть (порядок прихода)
        front = H.Ticket()
        r = run(state, "--server", "/bin/sh", "-c", "echo ran", wait_max=2)
        check("--server стоит в очереди на места: живой билет впереди — 75, не запускалась",
              r.returncode == 75 and "ran" not in r.stdout, f"{r.returncode} {r.stdout!r} {r.stderr!r}")
        front.drop()
        r = run(state, "--server", "/bin/sh", "-c", "echo ran", wait_max=5)
        check("--server при пустой очереди идёт, билетов не осталось", r.returncode == 0 and "ran" in r.stdout
              and left() == [], f"{r.returncode} {r.stderr!r} {left()}")
        print(f"({time.time() - t0:.0f} с)")
    finally:
        shutil.rmtree(tmp, True)
    print(f"тестов: {len(total) - len(fails)} прошло, {len(fails)} не прошло")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
