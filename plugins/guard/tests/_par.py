"""Случаи одного файла тестов — параллельно, каждый в своей копии процесса (fork), metis-0544.

    from _par import run_cases
    run_cases([(метка, функция без аргументов), …], sink, crash)

Зачем. Самые долгие файлы (test_watch, test_merge_gate, test_merge, test_read) дольше всех держат место очереди heavy
и прогона run-tests: их время — сотни запусков CLI и хука по 0.1–0.9 с, а ядра Mac при этом простаивают. Случаи этих
файлов друг от друга не зависят (у каждого свои временные папки), поэтому они идут по JOBS сразу.

Как. На случай — fork процесса файла: модуль теста уже загружен, а состояние после загрузки у каждого случая своё —
то же, что у первого случая при прогоне подряд, и прошлые случаи на него не влияют. Ребёнок пишет stdout и stderr в
свой файл, зовёт функцию, отдаёт родителю новые записи списка sink (FAILS или results файла — то, что добавила
функция) и выходит через os._exit, без atexit родителя (корневую временную папку убирает только родитель). Родитель
печатает вывод случаев целиком и по порядку списка — строки ok и FAIL те же, что при прогоне подряд, и раннер считает
их так же — и дописывает записи в sink в том же порядке.

Исключение в функции — строка «ОШИБКА: <метка> <тип> <текст>» и crash(метка, текст) в родителе. Ребёнок вышел без
итога (os._exit, сигнал, таймаут) — то же с причиной «процесс случая вышел с кодом N без итога»: такой случай не
пропадает молча, файл краснеет. Файл убили (таймаут run-tests: killpg группе) — дети в той же группе гаснут вместе
с ним.

Сколько сразу. TESTS_JOBS=<n> (n ≥ 1) — столько; иначе min(3, ядер // 2), не меньше 1: на 8 ядрах 3 (run-tests и так
гоняет 3 файла сразу, по 3 случая у самых долгих — ядра заняты, а не перегружены), на 2-ядерном CI 1 — подряд, но
тем же путём через fork. TESTS_JOBS=1 — подряд, для разбора упавшего случая.
"""
import json
import os
import sys
import tempfile
import traceback


def jobs():
    v = os.environ.get("TESTS_JOBS", "").strip()
    if v.isdigit() and int(v) > 0:
        return int(v)
    return max(1, min(3, (os.cpu_count() or 2) // 2))


def _child(fn, sink, out, res):
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    sys.stdout.reconfigure(line_buffering=True)  # строки stdout и stderr случая — в файле в порядке печати
    n0, err = len(sink), None
    try:
        fn()
    except BaseException as ex:  # noqa: BLE001 — любой исход случая уходит родителю, а не теряется в ребёнке
        err = f"{type(ex).__name__} {ex}"
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        with open(res, "w", encoding="utf-8") as fh:  # записи sink — строки и bool: JSON их держит
            json.dump([list(sink[n0:]), err], fh)
    finally:
        os._exit(0)


def run_cases(cases, sink, crash, n=None):
    """cases — [(метка, функция)]; sink — список итогов файла; crash(метка, текст) — записать провал случая, у
    которого исключение или нет итога. Возвращает число случаев."""
    n = n or jobs()
    work = tempfile.mkdtemp(prefix="par-")
    files = [(os.path.join(work, f"{i}.out"), os.path.join(work, f"{i}.res")) for i in range(len(cases))]
    running, done, nxt, shown = {}, {}, 0, 0
    while shown < len(cases):
        while nxt < len(cases) and len(running) < n:
            sys.stdout.flush()
            sys.stderr.flush()
            pid = os.fork()
            if pid == 0:
                _child(cases[nxt][1], sink, *files[nxt])
            running[pid] = nxt
            nxt += 1
        pid, st = os.wait()
        if pid in running:
            done[running.pop(pid)] = os.waitstatus_to_exitcode(st)
        while shown in done:
            label, (out, res) = cases[shown][0], files[shown]
            with open(out, "rb") as fh:
                sys.stdout.buffer.write(fh.read())
            sys.stdout.flush()
            try:
                with open(res, encoding="utf-8") as fh:
                    got, err = json.load(fh)
            except (OSError, ValueError):
                got, err = [], f"процесс случая вышел с кодом {done[shown]} без итога"
            sink.extend(got)
            if err:
                print("ОШИБКА:", label, err)
                crash(label, err)
            shown += 1
    for out, res in files:
        for p in (out, res):
            if os.path.exists(p):
                os.remove(p)
    os.rmdir(work)
    return len(cases)
