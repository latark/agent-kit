#!/usr/bin/env python3
"""Сводка классов провалов (metis-0859): failure_counts считает строки журнала «провал: <класс> — …» за N дней.

Запуск: python3 -I plugins/pantheon/tests/test_task_failures.py  (код выхода 0 — все прошли)
"""
import os
import sys
import time

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
sys.path.insert(0, LIB)
import tasks as T  # noqa: E402

NOW = time.mktime(time.strptime("2026-11-05 12:00", "%Y-%m-%d %H:%M"))
results = []


def check(name, ok):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name)


def body(*lines):
    return "# З\n\n## Журнал\n\n" + "\n".join(f"- {d} — агент: {t}" for d, t in lines) + "\n\n## Другое\n"


tasks = {
    "a": ("", {}, body(("2026-11-04 10:00", "провал: неверный подход — не тот слой"),
                       ("2026-11-05 09:00", "провал: неверный подход — снова"))),
    "b": ("", {}, body(("2026-11-03 10:00", "провал: непонятная задача — нет критериев"))),
    "c": ("", {}, body(("2026-10-20 10:00", "провал: трудная логика — гонка"))),  # старше 7 дней
    "d": ("", {}, body(("2026-11-04 10:00", "провал: выдумка — нет такого класса"),
                       ("2026-11-04 11:00", "не провал: просто строка"))),
}
r = T.failure_counts(tasks, NOW, 7)
check("неверный подход: две строки одной задачи", r["неверный подход"] == ["a", "a"])
check("непонятная задача: одна", r["непонятная задача"] == ["b"])
check("старше 7 дней не считается", r["трудная логика"] == [])
check("не хватило контекста: ключ есть, пусто", r["не хватило контекста"] == [])
check("неизвестный класс — «прочее», «не провал» не считается", r.get("прочее") == ["d"])
check("--days 30 захватывает старую", T.failure_counts(tasks, NOW, 30)["трудная логика"] == ["c"])
print(f"\n{sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
