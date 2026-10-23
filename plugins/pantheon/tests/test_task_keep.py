#!/usr/bin/env python3
"""metis-0402 п. 7: задача не теряется молча. `task new|set` — неизвестный флаг отказ с именем (код 2, файл не создан),
--body/--body-file кладут текст до «## Журнал», new без текста — отказ; новая задача — файл-уведомление координатору в
directions/<направление>/inbox/; тик (check --quiet) — две тревоги: открытая задача без описания старше часа и слово
владельца с [id] старше 30 минут без задачи и без записи «не задача».

Запуск: python3 -I plugins/pantheon/tests/test_task_keep.py  (код выхода 0 — все прошли)
"""
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _py311 import PY311  # CLI pantheon — только на Python 3.11+
import atexit as _atexit
import shutil as _shutil

_ROOT = tempfile.mkdtemp(prefix="keep-root-")
tempfile.tempdir = _ROOT
os.environ["TMPDIR"] = _ROOT
_atexit.register(_shutil.rmtree, _ROOT, True)

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CLI = os.path.join(LIB, "pantheon.py")
sys.path.insert(0, LIB)
T0 = datetime(2026, 10, 24, 12, 0).timestamp()
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name + ("" if ok or not detail else f"  [{detail}]"))


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="keep-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("directions/metis-pantheon/tasks", "directions/athena-shop/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    os.makedirs(view)
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1",
           "PANTHEON_FAKE_IDLE": "0", "PANTHEON_ALERTS_IN_DRYRUN": "1"}
    return tmp, home, state, env


def run(env, *args, t=T0):
    return subprocess.run([PY311, "-I", CLI, *args], env=dict(env, PANTHEON_NOW=str(t)), capture_output=True,
                          text=True, timeout=300)


def tasks_of(home, d="metis-pantheon"):
    p = os.path.join(home, "directions", d, "tasks")
    return sorted(f for f in os.listdir(p) if f.endswith(".md"))


def read(p):
    return open(p, encoding="utf-8").read()


def alerts_of(home):
    p = os.path.join(home, "alerts.md")
    return read(p) if os.path.exists(p) else ""


def strip_body(p, text):
    """Задача, как 32 старых: заголовок и журнал, без текста."""
    s = read(p)
    assert "\n" + text + "\n" in s
    open(p, "w", encoding="utf-8").write(s.replace("\n" + text + "\n", "", 1))


def new(env, *extra, t=T0):
    return run(env, "task", "new", "--direction", "metis-pantheon", "--title", "Проба", *extra, t=t)


def main():
    tmp, home, state, env = make()
    inbox = os.path.join(home, "directions", "metis-pantheon", "inbox")

    # (а) task new: неизвестный флаг
    r = new(env, "--bogus", "x", "--text", "тело")
    check("task new --bogus x: код 2, имя флага в сообщении, файл не создан",
          r.returncode == 2 and "--bogus" in r.stderr and tasks_of(home) == [], (r.returncode, r.stderr))
    r = new(env, "--text", "тело", "--body-fle", "x")
    check("task new: опечатка в имени флага (--body-fle) — тоже отказ", r.returncode == 2 and "--body-fle" in r.stderr
          and tasks_of(home) == [], r.stderr)
    r = new(env, "--text", "тело", "лишнее")
    check("task new: слово без флага — отказ, файла нет", r.returncode == 2 and "лишнее" in r.stderr and tasks_of(home) == [])
    r = new(env, "--text")
    check("task new: флаг --text без значения — отказ", r.returncode == 2 and "--text" in r.stderr and tasks_of(home) == [])

    # (а) без текста — отказ
    r = new(env)
    check("task new без --text/--body/--body-file: код 2, файла нет", r.returncode == 2 and "--body-file" in r.stderr
          and tasks_of(home) == [], r.stderr)
    r = new(env, "--body", "   ")
    check("task new --body из пробелов — тоже без текста, отказ", r.returncode == 2 and tasks_of(home) == [])

    # (а) --body и --body-file кладут тело до журнала
    r = new(env, "--body", "Цель: X.\nГотово, когда: Y.")
    p1 = os.path.join(home, "directions", "metis-pantheon", "tasks", "metis-0001.md")
    t1 = read(p1) if os.path.exists(p1) else ""
    check("task new --body: тело между заголовком и «## Журнал»", r.returncode == 0
          and re.search(r"# Проба\n\nЦель: X\.\nГотово, когда: Y\.\n\n## Журнал", t1), (r.stderr, t1))
    bf = os.path.join(tmp, "body.md")
    open(bf, "w", encoding="utf-8").write("Из файла.\n## Не раздел\nещё строка\n")
    r = new(env, "--body-file", bf)
    t2 = read(os.path.join(home, "directions", "metis-pantheon", "tasks", "metis-0002.md"))
    check("task new --body-file: текст из файла до журнала, «## » внутри экранирован",
          r.returncode == 0 and "Из файла.\n\\## Не раздел\nещё строка\n\n## Журнал" in t2, t2)
    r = new(env, "--body-file", os.path.join(tmp, "нет-такого.md"))
    check("task new --body-file с чужим путём: код 2, новой задачи нет", r.returncode == 2 and "не читается" in r.stderr
          and len(tasks_of(home)) == 2, r.stderr)
    r = new(env, "--text", "старый флаг", "--body", "новый")
    t3 = read(os.path.join(home, "directions", "metis-pantheon", "tasks", "metis-0003.md"))
    check("task new --text и --body вместе — оба в теле", r.returncode == 0 and "старый флаг\n\nновый" in t3, t3)
    r = new(env, "--question", "Выбрать?", "--why", "потому", "--option", "А — да. Цена: нет", "--waiting-on", "human")
    check("task new --question без текста — разрешён (суть в полях вопроса)", r.returncode == 0, r.stderr)

    # (в) уведомление координатору
    notes = sorted(os.listdir(inbox)) if os.path.isdir(inbox) else []
    one = [n for n in notes if n.endswith("-task-metis-0001.md")]
    body = read(os.path.join(inbox, one[0])) if one else ""
    check("task new → файл-уведомление в directions/<направление>/inbox/ с id, названием и пометкой «не находка»",
          len(one) == 1 and "metis-0001" in body and "Проба" in body and "Уведомление, а не находка" in body, notes)
    check("уведомление есть на каждую заведённую задачу", len(notes) == 4, notes)
    sys.path.insert(0, LIB)
    import tasks as T
    check("уведомление не становится карточкой «входящих» на доске владельца", T.inbox_items(home) == {}, T.inbox_items(home))
    r = run(dict(env, PANTHEON_SESSION="metis-pantheon"), "task", "new", "--direction", "metis-pantheon", "--title", "Своя",
            "--text", "сам завёл")
    check("координатор, заведший задачу сам, уведомления себе не получает",
          r.returncode == 0 and not [n for n in os.listdir(inbox) if n.endswith("task-metis-0005.md")], os.listdir(inbox))
    os.chmod(os.path.join(home, "directions", "athena-shop"), 0o555)  # inbox создать нельзя: задача уже есть, тревога
    r = run(env, "task", "new", "--direction", "athena-shop", "--title", "Чужая", "--text", "тело")
    os.chmod(os.path.join(home, "directions", "athena-shop"), 0o755)
    check("уведомление не записалось — задача создана, предупреждение в stderr и тревога",
          r.returncode == 0 and "уведомление" in r.stderr and "athena-0001" in r.stdout + alerts_of(home)
          or r.returncode == 0 and "уведомление" in r.stderr, (r.returncode, r.stderr, r.stdout))

    # (а) task set
    r = run(env, "task", "set", "metis-0001", "--bogus", "x")
    check("task set --bogus x: код 2, имя флага", r.returncode == 2 and "неизвестный флаг --bogus" in r.stderr, r.stderr)
    r = run(env, "task", "set", "metis-0001", "--note")
    check("task set --note без значения: код 2, имя флага", r.returncode == 2 and "у флага --note нет значения" in r.stderr, r.stderr)
    before = read(p1)
    r = run(env, "task", "set", "metis-0001", "next=сделать", "--bogus", "x")
    check("task set: поле до неизвестного флага не записывается", r.returncode == 2 and read(p1) == before)
    r = run(env, "task", "set", "metis-0001", "--body", "Новое тело", "--note", "переписал", "next=шаг")
    t = read(p1)
    check("task set --body: тело заменено до журнала, журнал и поле сохранены", r.returncode == 0
          and "# Проба\n\nНовое тело\n\n## Журнал" in t and "Цель: X" not in t and "переписал" in t and "создана" in t
          and 'next: шаг' in t, (r.stderr, t))
    open(bf, "w", encoding="utf-8").write("Из файла set.")
    r = run(env, "task", "set", "metis-0001", "--body-file", bf)
    check("task set --body-file", r.returncode == 0 and "# Проба\n\nИз файла set.\n\n## Журнал" in read(p1), r.stderr)

    # (г) тик: задача без описания
    tmp2, home2, state2, env2 = make()
    p = os.path.join(home2, "directions", "metis-pantheon", "tasks", "metis-0001.md")
    new(env2, "--body", "временно", t=T0)
    strip_body(p, "временно")  # задача, как 32 старых: заголовок и журнал
    r = run(env2, "check", "--quiet", t=T0 + 1800)
    check("тик: задача без описания моложе часа — тревоги нет", r.returncode == 0 and "без описания" not in alerts_of(home2),
          alerts_of(home2))
    r = run(env2, "check", "--quiet", t=T0 + 3700)
    a = alerts_of(home2)
    check("тик: открытая задача без описания старше часа — тревога с id", "без описания" in a and "metis-0001" in a, a)
    run(env2, "check", "--quiet", t=T0 + 3800)
    check("тик: тот же набор — повторной тревоги нет", alerts_of(home2).count("без описания") == 1)
    run(env2, "task", "set", "metis-0001", "--body", "Теперь есть цель", t=T0 + 3900)
    run(env2, "check", "--quiet", t=T0 + 4000)
    new(env2, "--body", "x", t=T0 + 4100)
    strip_body(os.path.join(home2, "directions", "metis-pantheon", "tasks", "metis-0002.md"), "x")
    run(env2, "task", "set", "metis-0002", "status=done", t=T0 + 4200)
    run(env2, "check", "--quiet", t=T0 + 9000)
    check("тик: описание дописали / задача закрыта — новой тревоги нет", alerts_of(home2).count("без описания") == 1,
          alerts_of(home2))

    # (г) тик: слово владельца с [id] без задачи
    tmp3, home3, state3, env3 = make()
    dec = os.path.join(home3, "decisions.md")
    open(dec, "w", encoding="utf-8").write(
        "# Решения\n\n- 24.10 11:00 — владелец: «сделайте так» [zeus-foo-bar]\n"
        "- 24.10 11:55 — владелец: свежее [zeus-fresh-one]\n"
        "- 24.10 10:00 — владелец: про [zeus-with-task]\n"
        "- 24.10 10:10 — владелец: про [zeus-not-task] — не задача, решение без работы\n"
        "- 24.10 10:20 — владелец: про [metis-0001] id самой задачи\n"
        "- 24.10 10:30 — [ссылка](http://x) и [просто-слово] не id\n")
    new(env3, "--body", "делаем [zeus-with-task]", t=T0 - 86400)
    r = run(env3, "check", "--quiet")
    a = alerts_of(home3)
    check("тик: [id] из decisions.md старше 30 мин без задачи — тревога", "zeus-foo-bar" in a and "без задачи" in a, a)
    check("тик: моложе 30 мин, с упоминанием в задаче, с «не задача», id самой задачи, не-id — молчит",
          not any(x in a for x in ("zeus-fresh-one", "zeus-with-task", "zeus-not-task", "metis-0001", "просто-слово")), a)
    zl = os.path.join(state3, "owner-log")
    os.makedirs(zl)
    open(os.path.join(zl, "zeus.md"), "w", encoding="utf-8").write(
        "## 2026-10-24 10:00:00 · окно вопросов\nвопрос: [zeus-from-log] выбрать?\nответ: да\n\n"
        "## 2026-10-24 10:05:00\nпросто текст про [zeus-chat-only]\n")
    run(env3, "check", "--quiet", t=T0 + 60)
    a = alerts_of(home3)
    check("тик: вопрос окна вопросов из owner-log без задачи — тревога; обычная реплика с [id] — нет",
          "zeus-from-log" in a and "zeus-chat-only" not in a, a)
    open(dec, "a", encoding="utf-8").write("- 24.10 12:01 — [zeus-foo-bar] завели задачу? нет — не задача\n")
    run(env3, "check", "--quiet", t=T0 + 120)
    n_alerts = alerts_of(home3).count("без задачи")
    run(env3, "check", "--quiet", t=T0 + 180)
    check("тик: тот же набор — повтор молчит", alerts_of(home3).count("без задачи") == n_alerts)
    check("тик: запись «не задача» гасит тревогу (набор изменился — одна новая строка без foo-bar)",
          alerts_of(home3).splitlines()[-1].count("zeus-foo-bar") == 0, alerts_of(home3).splitlines()[-1])
    # слишком старое (>7 дней) разбирает ревизия, а не тик
    open(dec, "a", encoding="utf-8").write("- 10.10 09:00 — старое [zeus-ancient-id]\n")
    run(env3, "check", "--quiet", t=T0 + 240)
    check("тик: слово старше 7 дней тревоги не даёт", "zeus-ancient-id" not in alerts_of(home3))

    # чистые функции (одно и то же на 3.9 и 3.14)
    desc = T.has_description
    check("has_description: заголовок и журнал — нет; текст — да; чужой раздел — да",
          not desc("\n# A\n\n## Журнал\n\n- x — агент: создана\n") and desc("\n# A\n\nтекст\n\n## Журнал\n")
          and desc("\n# A\n\n## Журнал\n\n- x\n\n## Заметки владельца\n\nа\n"))

    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
