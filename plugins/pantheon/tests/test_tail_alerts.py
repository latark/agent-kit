#!/usr/bin/env python3
"""metis-0504: хвосты не теряются. Тик (check --quiet) поднимает три тревоги: (а) строка журнала задачи со словами
«хвост / остаток / не сделано / вынесен / позже» без id задачи в строке (в `check` без --quiet — ещё и предупреждение
«внимание», не ошибка); (б) файл knowledge/inbox старше суток без ссылки из задач (findings: 0 — исключение);
(в) directions/*/review-*.md с находкой класса Д без ссылки из задач. Один раз на ключ, первый проход без тревоги.

Запуск: python3 -I plugins/pantheon/tests/test_tail_alerts.py  (код выхода 0 — все прошли)
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import atexit as _atexit
import shutil as _shutil

_ROOT = tempfile.mkdtemp(prefix="tail-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CLI = os.path.join(LIB, "pantheon.py")
sys.path.insert(0, LIB)
import tasks as T

T0 = datetime(2026, 10, 24, 12, 0).timestamp()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="tail-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("directions/metis-pantheon/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    os.makedirs(os.path.join(tmp, "ai", "knowledge", "inbox"))
    os.makedirs(view)
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0", "PANTHEON_ALERTS_IN_DRYRUN": "1"}
    return tmp, home, state, env


def run(env, *args, t=T0):
    return subprocess.run([PY311, "-I", CLI, *args], env=dict(env, PANTHEON_NOW=str(t)), capture_output=True,
                          text=True, timeout=300)


def read(p):
    return open(p, encoding="utf-8").read()


def alerts_of(home):
    p = os.path.join(home, "alerts.md")
    return read(p) if os.path.exists(p) else ""


def new(env, text, t=T0):
    return run(env, "task", "new", "--direction", "metis-pantheon", "--title", "Проба", "--text", text, t=t)


def put(path, text, age_h=48):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(text)
    m = T0 - age_h * 3600
    os.utime(path, (m, m))


def lines_with(home, word):
    return [ln for ln in alerts_of(home).splitlines() if word in ln]


def main():
    tmp, home, state, env = make()
    inbox = os.path.join(tmp, "ai", "knowledge", "inbox")
    dirp = os.path.join(home, "directions", "metis-pantheon")
    seen_p = os.path.join(state, "tail-seen.json")

    # --- состояние до первого прохода: по одному кандидату каждого вида и «ссылка есть»
    new(env, "задача с хвостом")                                   # metis-0001
    new(env, "задача с отчётом, разбор research-linked.md")        # metis-0002
    run(env, "task", "set", "metis-0001", "--note", "сделано A; остался хвост по resume", t=T0)
    run(env, "task", "set", "metis-0002", "--note", "остаток вынесен в metis-0009", t=T0)
    put(os.path.join(inbox, "research-old.md"), "---\nfindings: 3\n---\n# a\n")
    put(os.path.join(inbox, "research-zero.md"), "---\nfindings: 0\n---\n# a\n")
    put(os.path.join(inbox, "research-linked.md"), "# a\n")
    put(os.path.join(inbox, "research-young.md"), "# a\n", age_h=1)
    put(os.path.join(dirp, "review-1-argus.md"), "Вердикт: принять\n- С заметка\n- Д · a.py:1 долг\n")
    put(os.path.join(dirp, "review-2-argus.md"), "Вердикт: принять\n- Б a.py:1 блокер\nДобавь Д3 в текст\n")
    put(os.path.join(dirp, "review-3-linked.md"), "1. Д a.py:1 долг\n")
    new(env, "из review-3-linked.md заведена")                     # metis-0003

    r = run(env, "check", "--quiet", t=T0 + 10)
    seen = json.loads(read(seen_p)) if os.path.exists(seen_p) else None
    check("первый проход: тревог нет, всё запомнено в tail-seen.json",
          r.returncode == 0 and seen is not None and not lines_with(home, "в журнале") and not lines_with(home, "inbox")
          and not lines_with(home, "ревью") and any("research-old" in k for k in seen), (r.stderr, alerts_of(home), seen))
    check("первый проход: кандидаты записаны, а findings: 0, ссылка, моложе суток, не-Д и ссылка из задач — нет",
          seen is not None and any("metis-0001" in k for k in seen) and any("review-1-argus" in k for k in seen)
          and not any(x in k for k in seen for x in ("research-zero", "research-linked", "research-young", "review-2",
                                                      "review-3", "metis-0002")), seen)

    # --- новое на втором проходе: по одному на каждый вид
    new(env, "ещё задача", t=T0 + 20)                              # metis-0004
    run(env, "task", "set", "metis-0004", "--note", "не сделано: кэш, позже", t=T0 + 30)
    put(os.path.join(inbox, "research-new.md"), "# b\n")
    put(os.path.join(dirp, "review-4-argus.md"), "x\n\n  * **Д** tasks.py:9 долг\n")
    run(env, "check", "--quiet", t=T0 + 60)
    a = alerts_of(home)
    check("новые: хвост без id — тревога с id задачи и строкой журнала",
          len(lines_with(home, "в журнале")) == 1 and "metis-0004" in lines_with(home, "в журнале")[0]
          and "не сделано: кэш, позже" in a and "metis-0001" not in a, a)
    check("новые: файл inbox — тревога с путём; прежние, findings: 0, ссылка, моложе суток молчат",
          len(lines_with(home, "inbox")) == 1 and "research-new.md" in a and "research-old" not in a
          and "research-zero" not in a and "research-linked" not in a and "research-young" not in a, a)
    check("новые: ревью с Д — тревога с путём и строкой (3); Б без Д, Д3 в тексте и ссылка из задач молчат",
          len(lines_with(home, "ревью")) == 1 and "review-4-argus.md:3" in a and "review-1" not in a
          and "review-2" not in a and "review-3" not in a, a)

    # --- второй проход не повторяет
    n = len(a.splitlines())
    run(env, "check", "--quiet", t=T0 + 120)
    check("второй проход: тот же набор — тревоги не повторяются", len(alerts_of(home).splitlines()) == n)

    # --- ссылка появилась: тревоги нет и ключ уходит из файла
    new(env, "разбор research-new.md и review-4-argus.md", t=T0 + 130)  # metis-0005
    run(env, "check", "--quiet", t=T0 + 140)
    seen = json.loads(read(seen_p))
    check("ссылка из задачи есть: новых тревог нет, ключи исчезли из tail-seen.json",
          len(alerts_of(home).splitlines()) == n and not any("research-new" in k or "review-4" in k for k in seen), seen)

    # --- в check без --quiet это предупреждение, не ошибка
    r = run(env, "check", t=T0 + 150)
    check("check без --quiet: «внимание · metis-0004: хвост…», это не ОШИБКА",
          "внимание · metis-0004: хвост в журнале без задачи" in r.stdout
          and not any("хвост" in ln for ln in r.stdout.splitlines() if ln.startswith("ОШИБКА")), r.stdout[-600:])

    # --- испорченный seen — как первый проход
    put(os.path.join(inbox, "research-after-break.md"), "# c\n")
    open(seen_p, "w", encoding="utf-8").write("не json")
    run(env, "check", "--quiet", t=T0 + 200)
    check("испорченный tail-seen.json — запомнено заново без тревоги",
          "after-break" not in alerts_of(home) and "after-break" in read(seen_p))

    # --- больше 12 за проход: 12 + «и ещё», остаток — следующим проходом
    for i in range(14):
        put(os.path.join(inbox, f"research-many-{i:02d}.md"), "# m\n")
    n0 = len(lines_with(home, "inbox"))
    run(env, "check", "--quiet", t=T0 + 300)
    run(env, "check", "--quiet", t=T0 + 360)
    run(env, "check", "--quiet", t=T0 + 420)
    ls = lines_with(home, "inbox")[n0:]
    check("14 новых файлов: первая тревога называет 12 и «и ещё 2», вторая — оставшиеся 2, третьего прохода тревоги нет",
          len(ls) == 2 and "и ещё 2" in ls[0]
          and all(sum(f"research-many-{i:02d}.md" in ln for ln in ls) == 1 for i in range(14)), ls)

    # --- чистые функции (одно и то же на 3.9 и 3.14)
    def mk(tid, body):
        return {tid: ("p", {"id": tid, "type": "task", "status": "todo"}, body)}

    def tl(body):
        return T.tail_lines(mk("x-0001", body), T0)

    j = "\n## Журнал\n\n- 2026-10-24 11:00 — агент: {}\n"
    check("tail_lines: каждое слово хвоста находится",
          all(tl(j.format(w)) for w in ("остался хвост", "Остаток не берём", "не сделано X", "вынесен позже", "потом, позже")))
    check("tail_lines: id задачи в строке гасит; слова без хвоста, actor check, старая и не-журнальная строки — нет",
          not tl(j.format("остаток вынесен в metis-0009")) and not tl(j.format("всё готово"))
          and not tl("\n## Журнал\n\n- 2026-10-24 11:00 — check: остаток\n")
          and not tl("\n## Журнал\n\n- 2026-10-01 11:00 — агент: остаток\n")
          and not tl("\nхвост в тексте, не в журнале\n\n## Журнал\n\n- 2026-10-24 11:00 — агент: создана\n"))
    dr = T.D_FINDING_RE
    check("D_FINDING_RE: «- Д ·», «1. Д —», «**Д**», «Д:» — да; «Д3», «Добавь», «Б», «Дифф» — нет",
          all(dr.match(x) for x in ("- Д · a:1 x", "1. Д — a", "  * **Д** a", "Д: a", "- Д a"))
          and not any(dr.match(x) for x in ("- Д3 a", "Добавь Д", "- Б a", "Дифф 1", "Д", "- Д")))

    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
