"""Пул процессов, воркеры которого гаснут вместе с родителем (metis-0618).

Откуда сироты: test_shell_diff.py гонял ProcessPoolExecutor на (ядер − 1) воркеров. Родителя убил таймаут прогона
(старый `pantheon plugins update` гонял тесты выпуска в ~/.local/state/pantheon/plugins/tmp/guard-XXXXXXXX/base),
а воркеры остались: каждый держит и чтение, и запись очереди задач (multiprocessing.Queue передаётся воркеру
целиком), поэтому конца файла в очереди не бывает, и воркер ждёт задачу вечно. С ними живёт resource_tracker —
его канал тоже открыт в каждом воркере. Так 30.10 набралось 8 процессов guard-_9i3yizq (7 воркеров и tracker),
два дня с ppid 1.

Лекарство: initializer воркера запускает поток-сторож. Раз в WATCH_EVERY с он сверяет getppid() с родителем при
старте; родитель сменился (умер — воркер переходит к launchd, ppid 1, или к subreaper на Linux) — os._exit(0).
Воркеры гаснут, канал resource_tracker закрывается, и он выходит сам. Родитель при старте — тот, кто запустил
воркер: при spawn и fork это сам пул, при forkserver (Linux, 3.14) — процесс forkserver, а он выходит, когда умер
пул. Остаток: родитель умер ещё до запуска сторожа — ppid уже 1, это тоже выход; subreaper в этот миг не ловится.
Владелец пула — сам PID 1 (контейнер без init, metis-0805): ppid воркера 1 с самого старта, и это живой родитель, а не
launchd. Тогда выход — только по смене ppid: владелец (его pid пул передаёт воркеру, initargs) и есть 1.
"""
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor

WATCH_EVERY = 0.5


def _owner_gone(owner):
    """Владелец пула (pid из initargs) не существует. Нужно при forkserver (Linux, Python 3.14 по умолчанию): родитель
    воркера — процесс forkserver, а он живёт, пока живы воркеры (держат его канал), так что ppid не меняется, когда
    умер сам пул (проверено: воркеры и forkserver оставались с ppid 1)."""
    if not owner or owner == 1:
        return False
    try:
        os.kill(owner, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def _watch(start, owner):
    while True:
        ppid = os.getppid()
        if ppid != start or (ppid == 1 and owner != 1) or _owner_gone(owner):
            os._exit(0)
        time.sleep(WATCH_EVERY)


def die_with_parent(owner=None):
    """initializer воркера: поток-сторож, демон — обычному выходу воркера он не мешает. owner — pid владельца пула
    (process_pool передаёт свой): 1 — владелец сам PID 1, ppid 1 у воркера — живой родитель."""
    threading.Thread(target=_watch, args=(os.getppid(), owner), name="orphan-watch", daemon=True).start()


def process_pool(workers):
    return ProcessPoolExecutor(max_workers=workers, initializer=die_with_parent, initargs=(os.getpid(),))
