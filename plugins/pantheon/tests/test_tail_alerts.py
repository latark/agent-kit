#!/usr/bin/env python3
"""metis-0504: хвосты не теряются. Тик (check --quiet) поднимает три тревоги: (а) строка журнала задачи со словами
«хвост / остаток / не сделано / вынесен / позже» без id задачи в строке (в `check` без --quiet — ещё и предупреждение
«внимание», не ошибка); (б) файл knowledge/inbox старше суток без ссылки из задач (findings: 0 — исключение);
(в) directions/*/review-*.md с находкой класса Д без ссылки из задач. Один раз на ключ; первый проход — одна
сводная тревога без перечня (metis-0572).

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
RUN_PY = os.path.join(os.path.dirname(CLI), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
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
    return subprocess.run([PY311, "-I", RUN_PY, *args], env=dict(env, PANTHEON_NOW=str(t)), capture_output=True,
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
    """Строки тревог со словом, кроме сводной тревоги первого прохода (её проверяют отдельно)."""
    return [ln for ln in alerts_of(home).splitlines() if word in ln and SUMMARY not in ln]


SUMMARY = "хвосты: слежение начато"


def main():
    tmp, home, state, env = make()
    inbox = os.path.join(tmp, "ai", "knowledge", "inbox")
    dirp = os.path.join(home, "directions", "metis-pantheon")
    seen_p = os.path.join(state, "tail-seen.json")

    # --- состояние до первого прохода: по одному кандидату каждого вида и «ссылка есть»
    new(env, "задача с хвостом")                                   # metis-0001
    new(env, "задача с отчётом, разбор research-linked.md")        # metis-0002
    run(env, "task", "set", "metis-0001", "--note", "сделано A; остался хвост по resume", t=T0)
    run(env, "task", "set", "metis-0002", "--note", "остаток вынесен в metis-0001", t=T0)
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
    check("первый проход: тревог по хвостам нет, всё запомнено в tail-seen.json",
          r.returncode == 0 and seen is not None and not lines_with(home, "в журнале") and not lines_with(home, "inbox")
          and not lines_with(home, "ревью") and any("research-old" in k for k in seen), (r.stderr, alerts_of(home), seen))
    summ = [ln for ln in alerts_of(home).splitlines() if SUMMARY in ln]
    check("0572: первый проход не молчит — одна сводная тревога: сколько всего и по видам, где список; без перечня",
          len(summ) == 1 and seen is not None and f"уже есть {len(seen)} —" in summ[0]
          and "хвост в журнале без задачи 1" in summ[0] and "ревью с находкой Д без задачи 1" in summ[0]
          and "Доска/Хвосты.md" in summ[0] and "metis-0001" not in alerts_of(home)
          and "research-old" not in alerts_of(home), (summ, seen))
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
    check("второй проход: тот же набор — тревоги не повторяются, сводная тоже",
          len(alerts_of(home).splitlines()) == n and sum(SUMMARY in ln for ln in alerts_of(home).splitlines()) == 1)

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
    check("испорченный tail-seen.json — запомнено заново, без перечня, одна новая сводная тревога",
          "after-break" not in alerts_of(home) and "after-break" in read(seen_p)
          and sum(SUMMARY in ln for ln in alerts_of(home).splitlines()) == 2)

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

    # --- чистые функции
    def mk(tid, body):
        return {tid: ("p", {"id": tid, "type": "task", "status": "todo"}, body)}

    def tl(body):
        return T.tail_lines(mk("x-0001", body), T0)

    j = "\n## Журнал\n\n- 2026-10-24 11:00 — агент: {}\n"
    check("tail_lines: каждое слово хвоста находится",
          all(tl(j.format(w)) for w in ("остался хвост", "Остаток не берём", "не сделано X", "вынесен позже", "потом, позже")))
    def tl2(text):
        return T.tail_lines(
            {"x-0001": ("p", {"id": "x-0001", "type": "task", "status": "todo"}, "\n## Журнал\n\n- 2026-10-24 11:00 — агент: " + text + "\n"),
             "metis-0009": ("p", {"id": "metis-0009", "type": "task", "status": "todo"}, "")}, T0)

    check("tail_lines: review-113, x86-64, свой id, несуществующий id — тревога; настоящий чужой id — гасит",
          all(tl2(x) for x in ("остаток из review-113-argus.md", "хвост на x86-64", "остаток: заведу metis-9999"))
          and not tl2("остаток вынесен в metis-0009") and not tl2("остаток: review-113, дальше metis-0009"))
    check("tail_lines: id задачи в строке гасит; слова без хвоста, actor check, старая и не-журнальная строки — нет",
          not tl2("остаток вынесен в metis-0009") and not tl(j.format("всё готово"))
          and not tl("\n## Журнал\n\n- 2026-10-24 11:00 — check: остаток\n")
          and not tl("\n## Журнал\n\n- 2026-10-01 11:00 — агент: остаток\n")
          and not tl("\nхвост в тексте, не в журнале\n\n## Журнал\n\n- 2026-10-24 11:00 — агент: создана\n"))
    # --- metis-0572: ложные хвосты не считаются, погашение строкой, часть-PR, доска
    def tl3(lines, status="todo", extra=None, own="x-0001"):
        body = "\n## Журнал\n\n" + "".join(f"- 2026-10-24 {h} — агент: {x}\n" for h, x in lines)
        ts = {own: ("p", {"id": own, "type": "task", "status": status}, body),
              "metis-0366": ("p", {"id": "metis-0366", "type": "task", "status": "todo"}, ""),
              "metis-0367": ("p", {"id": "metis-0367", "type": "task", "status": "todo"}, ""),
              "athena-0366": ("p", {"id": "athena-0366", "type": "task", "status": "todo"}, "")}
        ts.update(extra or {})
        return T.tail_lines(ts, T0)

    check("0572: строка открытой задачи о ней самой (её id) — не хвост; у закрытой — хвост",
          not tl3([("10:00", "остаток в x-0001")]) and tl3([("10:00", "остаток в x-0001")], status="done"))
    check("0572: остаток закрыт позже в той же задаче — не хвост; позже строка без слов закрытия — хвост",
          not tl3([("10:00", "остался хвост"), ("11:00", "остаток закрыт")])
          and tl3([("10:00", "остался хвост"), ("11:00", "работаю дальше")])
)
    check("0572: закрыт ПЕРЕД хвостом — хвост остаётся (порядок строк журнала)",
          tl3([("09:00", "остаток закрыт"), ("10:00", "остался хвост")]))
    check("0572: id без префикса: «0367» — одна задача, гасит; «0366» — две (metis, athena), не гасит; свой номер не гасит",
          not tl3([("10:00", "хвост → 0367")]) and tl3([("10:00", "хвост → 0366")])
          and tl3([("10:00", "хвост → 0001")], own="x-0001") and tl3([("10:00", "хвост 12 штук")]))
    check("0572: «не задача: …» в самой строке гасит хвост",
          not tl3([("10:00", "остаток, не задача: шум")]) and tl3([("10:00", "остаток, шум")]))
    check("0572: «из ревью …» в начале строки открытой задачи — находки дописаны в неё саму, не хвост",
          not tl3([("10:00", "из ревью PR #154 (область: роли): Д2 не сделано Codex")])
          and not tl3([("10:00", "23.10 22:1x из review-111-argus-b3: обёртка без хвоста")])
          and not tl3([("10:00", "Из ревью 154: остаток")], status="waiting"))
    check("0572: «из ревью» у закрытой задачи и не в начале строки — хвост",
          tl3([("10:00", "из ревью PR #154: Д2 не сделано")], status="done")
          and tl3([("10:00", "остаток из ревью PR #154")])
          and tl3([("10:00", "23.10 остаток из review-111")]) and tl3([("10:00", "из ревьюера: остаток")]))
    check("0572: «остаток недели / лимита / дня» — запас, не хвост; «остаток:» и другое слово хвоста в строке — хвост",
          not tl3([("10:00", "у разработчика (владелец: израсходовать остаток недели)")])
          and not tl3([("10:00", "остатка лимита хватит")]) and not tl3([("10:00", "Остаток дня — на ревью")])
          and tl3([("10:00", "остаток: тест смысла")]) and tl3([("10:00", "остаток недели, хвост по resume")]))
    check("0572: остаток времени/денег с любой формой слова — не хвост («остатком недели», «остатков лимита», «остаток месяца / "
          "бюджета / токенов / минут / часов / времени»)",
          not any(tl3([("10:00", x)]) for x in (
              "остатком недели хватит", "остатков лимита хватит", "остаток месяца", "остаток бюджета", "остаток токенов",
              "остаток минут", "остаток часов", "остаток часа", "остаток времени", "остатка дня", "остаток дней",
              "остаток дню", "остаток недель", "остатком минуты")))
    check("0572: «остаток временных файлов», «остаток часть тестов», «остатки тестов» — хвост (узкие основы)",
          all(tl3([("10:00", x)]) for x in ("остаток временных файлов уберу", "остаток часть тестов", "остатки тестов",
                                            "остаток частями", "остаток недельного плана перенесён",
                                            "остаток минутной проверки", "остаток дневного прогона",
                                            "остаток бюджетного модуля", "остаток токенизатора", "остаток лимитного теста",
                                            "остаток месячного отчёта")))
    check("0572: позже строка «→ <id>» или «не задача: …» гасит прежние хвосты задачи; обычная строка — нет",
          not tl3([("10:00", "остался хвост"), ("11:00", "→ metis-0367")])
          and not tl3([("10:00", "остался хвост"), ("11:00", "не задача: шум")])
          and tl3([("10:00", "остался хвост"), ("11:00", "дальше работаю")]))

    def part(lines, status="doing", t=T0):
        body = "\n## Журнал\n\n" + "".join(f"- 2026-10-{d} {h} — {a}: {x}\n" for d, h, a, x in lines)
        return T.part_stalled({"x-0001": ("p", {"id": "x-0001", "type": "task", "status": status}, body)}, t)

    note = "PR #155 (agent-kit) слит, в теле «часть» — задача не закрыта"
    check("0572: часть-PR: задача открыта, запись слияния старше 24 ч и последняя — тревога",
          part([("23", "10:00", "плановый проход", note)]))
    check("0572: часть-PR: моложе 24 ч, есть позже запись агента, задача закрыта — тревоги нет",
          not part([("24", "10:00", "плановый проход", note)]) and not part(
              [("23", "10:00", "плановый проход", note), ("23", "12:00", "агент", "взял в работу")])
          and not part([("23", "10:00", "плановый проход", note)], status="done")
          and not part([("23", "10:00", "плановый проход", "PR #5 (r) слит, закрыта")]))
    tmp2, home2, state2, env2 = make()
    new(env2, "задача", t=T0)
    run(env2, "task", "set", "metis-0001", "--note", "остался хвост", t=T0)
    os.makedirs(os.path.join(tmp2, "view", "Доска"), exist_ok=True)
    run(env2, "check", "--quiet", t=T0 + 10)
    bp = os.path.join(tmp2, "view", "Доска", "Хвосты.md")
    check("0572: Доска/Хвосты.md пишется и на первом проходе (тревоги нет): хвост виден владельцу",
          os.path.exists(bp) and "metis-0001" in read(bp) and "остался хвост" in read(bp)
          and not lines_with(home2, "в журнале"), read(bp) if os.path.exists(bp) else "нет файла")
    run(env2, "task", "set", "metis-0001", "--note", "→ metis-0001-x; не задача: шум", t=T0 + 20)
    run(env2, "check", "--quiet", t=T0 + 30)
    check("0572: после строки «не задача: …» Хвосты.md пустеет, файл не попадает на доску как карточка",
          "Нет — всё в порядке" in read(bp), read(bp))

    tmp3, home3, state3, env3 = make()
    new(env3, "задача без хвоста", t=T0)
    run(env3, "check", "--quiet", t=T0 + 10)
    check("0572: первый проход без хвостов — сводной тревоги нет, tail-seen.json пустой",
          SUMMARY not in alerts_of(home3) and os.path.exists(os.path.join(state3, "tail-seen.json"))
          and json.loads(read(os.path.join(state3, "tail-seen.json"))) == {}, alerts_of(home3))

    # 0572 (Д3): разное число хвостов по видам — счёт в сводной тревоге по виду, а не «всегда 1»
    tmp4, home4, state4, env4 = make()
    inbox4 = os.path.join(tmp4, "ai", "knowledge", "inbox")
    for i in range(3):
        new(env4, f"задача {i}", t=T0)
        run(env4, "task", "set", f"metis-000{i + 1}", "--note", "остался хвост", t=T0)
    for i in range(2):
        put(os.path.join(inbox4, f"research-n{i}.md"), "# a\n")
    put(os.path.join(home4, "directions", "metis-pantheon", "review-9-argus.md"), "- Д · a.py:1 долг\n")
    run(env4, "check", "--quiet", t=T0 + 10)
    s4 = [ln for ln in alerts_of(home4).splitlines() if SUMMARY in ln]
    check("0572: сводная тревога считает по видам: хвост 3, файл inbox 2, ревью 1, всего 6",
          len(s4) == 1 and "уже есть 6 —" in s4[0] and "хвост в журнале без задачи 3" in s4[0]
          and "файл inbox старше суток без задачи разбора 2" in s4[0] and "ревью с находкой Д без задачи 1" in s4[0], s4)

    # 0572 (Д3): запись tail-seen.json упала — сводной тревоги нет (следующий проход снова первый), тик не падает молча
    tmp5, home5, state5, env5 = make()
    new(env5, "задача", t=T0)
    run(env5, "task", "set", "metis-0001", "--note", "остался хвост", t=T0)
    os.makedirs(os.path.join(state5, "tail-seen.json"))  # папка на месте файла: чтение и запись — OSError
    r5 = run(env5, "check", "--quiet", t=T0 + 10)
    check("0572: запись tail-seen.json упала — сводной тревоги «слежение начато» нет",
          SUMMARY not in alerts_of(home5), (r5.returncode, r5.stderr[-300:], alerts_of(home5)))

    new(env2, "вторая", t=T0 + 40)
    run(env2, "check", "--quiet", t=T0 + 50)
    pt = os.path.join(home2, "directions", "metis-pantheon", "tasks", "metis-0002.md")
    put(pt, read(pt) + "- 2026-10-22 10:00 — плановый проход: PR #155 (agent-kit) слит, в теле «часть» — задача не закрыта\n", age_h=0)
    run(env2, "check", "--quiet", t=T0 + 60)
    check("0572: часть-PR без движения >24 ч — тревога «слит с «часть»» один раз и строка в Хвосты.md",
          len(lines_with(home2, "слит с «часть»")) == 1 and "metis-0002" in lines_with(home2, "слит с «часть»")[0]
          and "слит с «часть»" in read(bp), alerts_of(home2))

    # metis-0615 п. 5: «часть» без неотмеченных пунктов — строка в Хвосты.md сразу, а не молчание
    empty = "PR слит с «часть», а неотмеченных пунктов «Готово, когда» нет** — metis-0002"
    check("0615: часть-PR, а пунктов остатка нет (одна заглушка) — строка в Хвосты.md и «Хвост» карточки, без тревоги",
          empty in read(bp) and "PR слит с «часть», остаток не записан" in str(
              json.loads(read(os.path.join(state2, "tails.json"))).get("metis-0002"))
          and not lines_with(home2, "неотмеченных пунктов"), read(bp))

    def pni(crit, status="doing", note_line=note):
        body = ("Готово, когда:\n" + "".join(f"- [{'x' if ok else ' '}] {x}\n" for ok, x in crit)
                + "\n## Журнал\n\n- 2026-10-24 11:00 — плановый проход: " + note_line + "\n")
        return T.part_no_items({"x-0001": ("p", {"id": "x-0001", "type": "task", "status": status}, body)})
    check("0615: part_no_items — без пунктов, все отмечены, одна заглушка → строка; сразу, без 24 ч",
          pni([]) and pni([(True, "а")]) and pni([(False, T.DONE_WHEN_HINT)])
          and pni([])[0] == ("x-0001", "- 2026-10-24 11:00 — плановый проход: " + note))
    check("0615: part_no_items — есть неотмеченный пункт, задача закрыта, «часть» не было — нет",
          not pni([(False, "остаток")]) and not pni([(True, "а"), (False, "б")]) and not pni([], status="done")
          and not pni([], note_line="PR #5 (r) слит, закрыта"))
    run(env2, "task", "set", "metis-0002", "--note", "остаток впишу пунктом", t=T0 + 62)
    pt_text = read(pt).replace(T.DONE_WHEN_HINT, "второй шаг остатка")
    put(pt, pt_text, age_h=0)
    run(env2, "check", "--quiet", t=T0 + 64)
    check("0615: пункт остатка вписан — строки «часть … пунктов нет» в Хвосты.md больше нет", empty not in read(bp), read(bp))

    # metis-0583: застой doing/review — без записи в журнале дольше 2 суток; в Хвосты.md, без тревоги
    def stl(lines, status="doing", updated="2026-10-20T10:00:00"):
        body = "\n## Журнал\n\n" + "".join(f"- 2026-10-{d} {h} — {a}: {x}\n" for d, h, a, x in lines)
        return T.stalled({"x-0001": ("p", {"id": "x-0001", "type": "task", "status": status, "updated": updated}, body)}, T0)
    check("0583: застой — doing и review, последняя запись старше 2 суток; запись check движением не считается",
          stl([("21", "10:00", "агент", "взял")]) == [("x-0001", "doing", 3)]
          and stl([("21", "10:00", "агент", "взял")], status="review") == [("x-0001", "review", 3)]
          and stl([("21", "10:00", "агент", "взял"), ("24", "10:00", "check", "сверка")]) == [("x-0001", "doing", 3)],
          str(stl([("21", "10:00", "агент", "взял")])))
    check("0583: не застой — свежая запись (<2 сут), todo/waiting/done; без журнала — по updated",
          not stl([("22", "13:00", "агент", "взял")]) and not stl([("21", "10:00", "агент", "x")], status="todo")
          and not stl([("21", "10:00", "агент", "x")], status="waiting") and not stl([("21", "10:00", "агент", "x")], status="done")
          and not stl([], updated="2026-10-23T12:00:00") and stl([], updated="2026-10-20T12:00:00"))
    new(env2, "третья", t=T0 - 5 * 86400)
    run(env2, "task", "set", "metis-0003", "status=doing", "mode=single", t=T0 - 5 * 86400)
    before = len(alerts_of(home2).splitlines())
    run(env2, "check", "--quiet", t=T0 + 70)
    r = run(env2, "check", t=T0 + 80)
    check("0583: застой — строка в Хвосты.md и в сводке check, тревоги нет",
          "застой doing/review** — metis-0003: doing, без записи в журнале 5 сут" in read(bp)
          and "внимание · застой: 1 задач" in r.stdout and "metis-0003" in r.stdout
          and not any("metis-0003" in x for x in alerts_of(home2).splitlines()[before:]), read(bp) + r.stdout[-600:])
    run(env2, "task", "set", "metis-0003", "--note", "жду живой проверки", t=T0 + 90)
    run(env2, "check", "--quiet", t=T0 + 100)
    check("0583: запись хода в журнал гасит застой", "metis-0003" not in read(bp), read(bp))

    dr = T.D_FINDING_RE
    check("D_FINDING_RE: «- Д ·», «1. Д —», «**Д**», «Д:», «- Д3 a», «Д1.», «**Д2** —» — да; «Д3б», «Добавь», «Б», «Дифф» — нет",
          all(dr.match(x) for x in ("- Д · a:1 x", "1. Д — a", "  * **Д** a", "Д: a", "- Д a", "- Д3 a", "Д1. a", "**Д2** — a", "- **Д12** a"))
          and not any(dr.match(x) for x in ("Д3б a", "Добавь Д", "- Б a", "Дифф 1", "Д", "- Д")))

    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
