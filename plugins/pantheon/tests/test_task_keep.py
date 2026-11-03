#!/usr/bin/env python3
"""metis-0402 п. 7: задача не теряется молча. `task new|set` — неизвестный флаг отказ с именем (код 2, файл не создан),
--body/--body-file кладут текст до «## Журнал», new без текста — отказ; новая задача — файл-уведомление координатору в
directions/<направление>/inbox/; тик (check --quiet) — две тревоги: открытая задача без описания старше часа и слово
владельца с [id] старше 30 минут без задачи и без строки «не задача: [id] — причина» (один раз на id, первый проход
только запоминает). Уведомление узнаётся по точной форме; task set --body заменяет текст до «## Журнал».

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
RUN_PY = os.path.join(os.path.dirname(CLI), "run.py")  # загрузчик, как bin/pantheon: .pyc (metis-0544)
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
    return subprocess.run([PY311, "-I", RUN_PY, *args], env=dict(env, PANTHEON_NOW=str(t)), capture_output=True,
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
          and re.search(r"# Проба\n\nЦель: X\.\nГотово, когда: Y\.\n\n## Готово, когда\n\n- \[ \] [^\n]+\n\n## Журнал", t1), (r.stderr, t1))
    bf = os.path.join(tmp, "body.md")
    open(bf, "w", encoding="utf-8").write("Из файла.\n## Не раздел\nещё строка\n")
    r = new(env, "--body-file", bf)
    t2 = read(os.path.join(home, "directions", "metis-pantheon", "tasks", "metis-0002.md"))
    check("task new --body-file: текст из файла до журнала, «## » внутри экранирован",
          r.returncode == 0 and "Из файла.\n\\## Не раздел\nещё строка\n\n## Готово, когда\n\n- [ ] " in t2 and "\n\n## Журнал" in t2, t2)
    r = new(env, "--body-file", os.path.join(tmp, "нет-такого.md"))
    check("task new --body-file с чужим путём: код 2, новой задачи нет", r.returncode == 2 and "не читается" in r.stderr
          and len(tasks_of(home)) == 2, r.stderr)
    r = new(env, "--text", "старый флаг", "--body", "новый")
    t3 = read(os.path.join(home, "directions", "metis-pantheon", "tasks", "metis-0003.md"))
    check("task new --text и --body вместе — оба в теле", r.returncode == 0 and "старый флаг\n\nновый" in t3, t3)
    r = new(env, "--question", "Выбрать?", "--why", "потому", "--option", "А — да. Цена: нет", "--waiting-on", "human")
    check("task new --question без текста и с одним --option — отказ, код 2, файла нет",
          r.returncode == 2 and "--option" in r.stderr and len(tasks_of(home)) == 3, (r.returncode, r.stderr))
    r = new(env, "--question", "Выбрать?", "--option", "А — да", "--option", "Б — нет", "--waiting-on", "human")
    check("task new --question без текста и без --why — отказ, код 2, файла нет",
          r.returncode == 2 and "--why" in r.stderr and len(tasks_of(home)) == 3, (r.returncode, r.stderr))
    r = new(env, "--question", "Выбрать?", "--why", "потому", "--option", "А — да. Цена: нет", "--option", "Б — нет",
            "--waiting-on", "human")
    check("task new --question, --why и два --option без текста — разрешён (суть в полях вопроса)", r.returncode == 0,
          r.stderr)
    r = new(env, "--title=Другое", "--text", "тело")
    check("task new --title=X — отказ с подсказкой «через пробел», а не «неизвестный флаг»",
          r.returncode == 2 and "через пробел" in r.stderr and "неизвестный" not in r.stderr, r.stderr)

    # (в) уведомление координатору
    notes = sorted(os.listdir(inbox)) if os.path.isdir(inbox) else []
    one = [n for n in notes if n.endswith("-task-metis-0001.md")]
    body = read(os.path.join(inbox, one[0])) if one else ""
    check("task new → файл-уведомление в directions/<направление>/inbox/ с id, названием и пометкой «не находка»",
          len(one) == 1 and "metis-0001" in body and "Проба" in body and "Уведомление, а не находка" in body, notes)
    check("уведомление есть на каждую заведённую задачу", len(notes) == 4, notes)
    check("уведомление без PANTHEON_SESSION и PANTHEON_ROLE подписано «От: агент», не «владелец»",
          "\nОт: агент\n" in body and "владелец" not in body, body)
    sys.path.insert(0, LIB)
    import tasks as T
    check("уведомление не становится карточкой «входящих» на доске владельца", T.inbox_items(home) == {}, T.inbox_items(home))
    # находка, которая только цитирует пометку уведомления, остаётся находкой (argus b): точная форма — имя, первая
    # строка и существующая задача
    fake = {"2026-10-24-1200-finding.md": f"# Находка: про уведомления\n\nОт: argus\n\nЦитата: «{T.NOTICE_MARK} …»\n",
            "2026-10-24-1201-task-metis-0001.md": f"# Находка про metis-0001\n\n{T.NOTICE_MARK} цитата\n",
            "2026-10-24-1202-task-metis-0999.md": f"# Новая задача metis-0999: нет такой\n\n{T.NOTICE_MARK} x\n",
            "2026-10-24-1203-note-metis-0001.md": f"# Новая задача metis-0001: Проба\n\n{T.NOTICE_MARK} x\n",
            "2026-10-24-1204-task-metis-0001.md": "# Новая задача metis-0001: Проба\n\nбез пометки — находка\n"}
    for f, s in fake.items():
        open(os.path.join(inbox, f), "w", encoding="utf-8").write(s)
    files = sorted(x["file"] for x in T.inbox_items(home).values())
    check("находка с цитатой пометки, чужое имя, первая строка не «# Новая задача <id>:», задачи <id> нет — карточки есть",
          files == sorted(fake), files)
    for f in fake:
        os.remove(os.path.join(inbox, f))
    r = run(dict(env, PANTHEON_ROLE="argus"), "task", "new", "--direction", "metis-pantheon", "--title", "От роли",
            "--text", "тело")
    one = [n for n in os.listdir(inbox) if n.endswith("-task-" + r.stdout.split()[0] + ".md")] if r.returncode == 0 else []
    check("уведомление от роли подписано её именем", one and "\nОт: argus\n" in read(os.path.join(inbox, one[0])), one)
    r = run(dict(env, PANTHEON_SESSION="metis-pantheon"), "task", "new", "--direction", "metis-pantheon", "--title", "Своя",
            "--text", "сам завёл")
    check("координатор, заведший задачу сам, уведомления себе не получает",
          r.returncode == 0 and not [n for n in os.listdir(inbox) if n.endswith("task-metis-0006.md")], os.listdir(inbox))
    os.chmod(os.path.join(home, "directions", "athena-shop"), 0o555)  # inbox создать нельзя: задача уже есть, тревога
    r = run(env, "task", "new", "--direction", "athena-shop", "--title", "Чужая", "--text", "тело")
    os.chmod(os.path.join(home, "directions", "athena-shop"), 0o755)
    a = alerts_of(home)
    check("уведомление не записалось — задача создана, предупреждение в stderr и тревога с id в alerts.md",
          r.returncode == 0 and r.stdout.startswith("athena-0001 ") and "уведомление" in r.stderr
          and re.search(r"task-new · новая задача athena-0001 \(athena-shop\): уведомление в inbox не записано", a),
          (r.returncode, r.stderr, r.stdout, a))

    # (а) task set
    r = run(env, "task", "set", "metis-0001", "--bogus", "x")
    check("task set --bogus x: код 2, имя флага", r.returncode == 2 and "неизвестный флаг --bogus" in r.stderr, r.stderr)
    r = run(env, "task", "set", "metis-0001", "--note=x")
    check("task set --note=x: код 2, подсказка «через пробел»", r.returncode == 2 and "через пробел" in r.stderr, r.stderr)
    r = run(env, "task", "set", "metis-0001", "--note")
    check("task set --note без значения: код 2, имя флага", r.returncode == 2 and "у флага --note нет значения" in r.stderr, r.stderr)
    before = read(p1)
    r = run(env, "task", "set", "metis-0001", "next=сделать", "--bogus", "x")
    check("task set: поле до неизвестного флага не записывается", r.returncode == 2 and read(p1) == before)
    r = run(env, "task", "set", "metis-0001", "--body", "Новое тело", "--note", "переписал", "next=шаг")
    t = read(p1)
    check("task set --body: тело заменено до журнала, журнал и поле сохранены", r.returncode == 0
          and "# Проба\n\nНовое тело\n\n## Журнал" in t and "Цель: X" not in t and "переписал" in t and "создана" in t
          and 'next: шаг' in t and re.search(r"— агент: текст задачи заменён \(было \d+ знаков, стало 10\)", t), (r.stderr, t))
    open(bf, "w", encoding="utf-8").write("Из файла set.")
    r = run(env, "task", "set", "metis-0001", "--body-file", bf)
    check("task set --body-file", r.returncode == 0 and "# Проба\n\nИз файла set.\n\n## Журнал" in read(p1), r.stderr)
    # metis-0591: «## Готово, когда» из --body-file остаётся разделом, прочие «## » экранируются, дубля нет
    open(bf, "w", encoding="utf-8").write("Цель Z.\n\n## Готово, когда\n\n- [ ] первый\n- [x] второй\n\n## Журнал\nлишнее\n")
    r = run(env, "task", "set", "metis-0001", "--body-file", bf)
    t = read(p1)
    check("task set --body-file: «## Готово, когда» не экранирован и распознаётся, «## Журнал» экранирован, раздел один",
          r.returncode == 0 and "\n## Готово, когда\n\n- [ ] первый\n- [x] второй\n" in t and "\\## Готово" not in t
          and "\\## Журнал\nлишнее" in t and t.count("## Готово, когда") == 1 and T.done_criteria(t) == [(False, "первый"), (True, "второй")]
          and "критерии «Готово, когда» изменены" in t, (r.stderr, t))
    tl = datetime(2026, 10, 28, 12, 0, 0).timestamp()  # после CRITERIA_FROM: правило закрытия действует
    r = new(env, "--body", "Цель L.", t=tl)
    nl = sorted(tasks_of(home))[-1]
    pl = os.path.join(home, "directions", "metis-pantheon", "tasks", nl)
    run(env, "task", "set", nl[:-3], "--body-file", bf, t=tl)
    r = run(env, "task", "set", nl[:-3], "status=done", t=tl)
    check("task set status=done с неотмеченным пунктом из --body-file — отказ", r.returncode != 0 and "неотмечено 1" in r.stderr
          and "status: done" not in read(pl), (r.returncode, r.stderr, read(pl)))
    check("escape_desc: второй раздел «Готово, когда» экранируется, «## Заметки владельца» тоже",
          T.escape_desc("а\n## Готово, когда\n- [ ] x\n## Готово, когда\n## Заметки владельца") ==
          "а\n## Готово, когда\n- [ ] x\n\\## Готово, когда\n\\## Заметки владельца")
    r = new(env, "--body", "Цель Q.\n\n## Готово, когда\n\n- [ ] пункт Q")
    tq = read(sorted(tasks_of(home))[-1] if os.path.isabs(sorted(tasks_of(home))[-1]) else os.path.join(home, "directions", "metis-pantheon", "tasks", sorted(tasks_of(home))[-1]))
    check("task new с разделом в тексте: шаблон не добавлен, раздел один", r.returncode == 0
          and tq.count("## Готово, когда") == 1 and "впишите" not in tq and T.done_criteria(tq) == [(False, "пункт Q")], (r.stderr, tq))
    open(bf, "w", encoding="utf-8").write("Из файла set.")
    run(env, "task", "set", "metis-0001", "--body-file", bf)  # состояние для следующих проверок
    # разделы до журнала (argus a): «## Что сделать» заменяется вместе с текстом, «## Заметки владельца» остаётся
    old_desc = "Цель старая.\n\n## Что сделать\n\n1. старый шаг"
    s1 = read(p1).replace("# Проба\n\nИз файла set.\n\n", "# Проба\n\n" + old_desc + "\n\n"
                          "## Заметки владельца\n\n- 2026-10-24 11:00\n  > мысль владельца\n\n", 1)
    open(p1, "w", encoding="utf-8").write(s1)
    r = run(env, "task", "set", "metis-0001", "--body", "Новое описание целиком", "--text", "не флаг set")
    check("task set --text — неизвестный для set флаг, отказ", r.returncode == 2 and "--text" in r.stderr, r.stderr)
    r = run(env, "task", "set", "metis-0001", "--body", "Новое описание целиком")
    t = read(p1)
    check("task set --body: «## Что сделать» до журнала заменён, «Заметки владельца» и журнал на месте",
          r.returncode == 0 and "старый шаг" not in t and "Цель старая" not in t and "## Что сделать" not in t
          and "# Проба\n\nНовое описание целиком\n\n## Заметки владельца\n\n- 2026-10-24 11:00\n  > мысль владельца\n\n## Журнал" in t
          and f"текст задачи заменён (было {len(old_desc)} знаков" in t, (r.stderr, t))

    # (а) повтор одиночного флага — отказ (argus b, круг 2): opt() берёт последнее значение и молча терял бы первое
    tmpr, homer, stater, envr = make()
    for flags in (("--body", "Цель: ПЕРВАЯ", "--body", "Готово, когда: ВТОРАЯ"), ("--text", "A", "--text", "B"),
                  ("--body-file", bf, "--body-file", bf), ("--body", "x", "--release", "R1", "--wave", "R2"),
                  ("--body", "x", "--risky", "--risky"), ("--body", "x", "--title", "Другое")):
        r = new(envr, *flags)
        name = "--wave" if "--wave" in flags else "--title" if flags[-2] == "--title" else flags[-2] \
            if flags[-2].startswith("--") else flags[-1]
        check(f"task new {' '.join(flags[::2] if '--risky' not in flags else flags[2:])}: повтор — код 2, имя флага, файла нет",
              r.returncode == 2 and f"флаг {name} повторён" in r.stderr and tasks_of(homer) == [], (r.returncode, r.stderr))
    r = new(envr, "--body", "x", "--touches", "a.py", "--touches", "b.py", "--note-x", "y")
    check("task new: повтор --touches не считается повтором (отказ только за неизвестный --note-x)",
          r.returncode == 2 and "неизвестный флаг --note-x" in r.stderr, r.stderr)
    r = new(envr, "--body", "x", "--touches", "a.py", "--touches", "b.py", "--option", "А", "--option", "Б")
    pr = os.path.join(homer, "directions", "metis-pantheon", "tasks", "metis-0001.md")
    check("task new: --touches и --option повторяются — оба значения в шапке", r.returncode == 0
          and "a.py" in read(pr) and "b.py" in read(pr) and "Б" in read(pr), r.stderr)
    before = read(pr)
    for flags in (("--body", "A", "--body", "B"), ("--note", "n1", "--note", "n2"), ("--body-file", bf, "--body-file", bf),
                  ("--release", "R1", "--wave", "R2")):
        r = run(envr, "task", "set", "metis-0001", *flags)
        check(f"task set {flags[0]} … {flags[2]}: повтор — код 2, имя флага, файл не тронут",
              r.returncode == 2 and f"флаг {flags[2]} повторён" in r.stderr and read(pr) == before, (r.returncode, r.stderr))
    r = run(envr, "task", "set", "metis-0001", "--note", "--body", "--body", "Тело после", "--option", "В", "--option", "Г")
    check("task set: «--body» как значение --note — не повтор; --option повторяется", r.returncode == 0
          and "# Проба\n\nТело после\n\n## Журнал" in read(pr), r.stderr)

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

    # вопрос владельцу без текста: полный (why и два варианта) не в счёт, неполный (только question) — тревога
    r = new(env2, "--question", "Выбрать?", "--why", "потому", "--option", "А — да", "--option", "Б — нет",
            "--waiting-on", "human", t=T0 + 9100)
    new(env2, "--body", "y", t=T0 + 9100)
    strip_body(os.path.join(home2, "directions", "metis-pantheon", "tasks", "metis-0004.md"), "y")
    r2 = run(env2, "task", "set", "metis-0004", "question=Что?", "--option", "А — да", "--option", "Б — нет", t=T0 + 9150)
    new(env2, "--body", "z", t=T0 + 9100)
    strip_body(os.path.join(home2, "directions", "metis-pantheon", "tasks", "metis-0005.md"), "z")
    r3 = run(env2, "task", "set", "metis-0005", "question=Что?", "why=потому", "--option", "А — один", t=T0 + 9150)
    run(env2, "check", "--quiet", t=T0 + 9100 + 3700)
    last = [ln for ln in alerts_of(home2).splitlines() if "без описания" in ln][-1]
    check("тик: полный вопрос без текста (metis-0003) — не тревога; вопрос с вариантами без why (0004) и с why и одним вариантом (0005) — тревога",
          r.returncode == 0 and r2.returncode == 0 and r3.returncode == 0 and "metis-0004" in last and "metis-0005" in last
          and "metis-0003" not in last, (r.stderr, r2.stderr, r3.stderr, last))

    # (г) тик: слово владельца с [id] без задачи
    tmp3, home3, state3, env3 = make()
    dec = os.path.join(home3, "decisions.md")
    seen_p = os.path.join(state3, "unlinked-seen.json")
    open(dec, "w", encoding="utf-8").write("# Решения\n\n- 24.10 09:00 — владелец: давнее [zeus-old-one]\n")
    r = run(env3, "check", "--quiet")
    check("тик, первый проход: что уже есть — запомнено без тревоги (argus a: 122 старых id не шумят)",
          r.returncode == 0 and "без задачи" not in alerts_of(home3) and "zeus-old-one" in read(seen_p)
          if os.path.exists(seen_p) else False, alerts_of(home3))
    open(dec, "a", encoding="utf-8").write(
        "- 24.10 11:00 — владелец: «сделайте так» [zeus-foo-bar]\n"
        "- 24.10 11:55 — владелец: свежее [zeus-fresh-one]\n"
        "- 24.10 10:00 — владелец: про [zeus-with-task]\n"
        "- 24.10 10:10 — владелец: про [zeus-not-task]\n"
        "не задача: [zeus-not-task] — решение без работы\n"
        "- 24.10 10:11 — владелец: про [zeus-bullet-nt]\n"
        "- не задача: [zeus-bullet-nt] — уже сделано\n"
        "- 24.10 10:15 — владелец: [zeus-owner-says] это не задача на сегодня, но сделать до пятницы\n"
        "- 24.10 10:16 — владелец: [zeus-wordform] это шаги, а не задачами отдельными\n"
        "- 24.10 10:17 — владелец: [zeus-quoted] посмотрим\n"
        "> не задача: [zeus-quoted] — цитата, а не пометка\n"
        "- 24.10 10:18 — владелец: [zeus-in-journal] сделать\n"
        "- 24.10 10:19 — владелец: [zeus-dropped] передумал\n"
        "- 24.10 10:20 — владелец: про [metis-0001] id самой задачи\n"
        "- 24.10 10:30 — [ссылка](http://x) и [просто-слово] не id\n")
    new(env3, "--body", "делаем [zeus-with-task]", t=T0 - 86400)
    new(env3, "--body", "работа", t=T0 - 86400)
    run(env3, "task", "set", "metis-0002", "--note", "про [zeus-in-journal]", t=T0 - 86000)
    new(env3, "--body", "мусор, решено [zeus-dropped]", t=T0 - 86400)
    run(env3, "task", "set", "metis-0003", "status=dropped", t=T0 - 86000)
    run(env3, "check", "--quiet", t=T0 + 60)
    lines = [ln for ln in alerts_of(home3).splitlines() if "без задачи" in ln]
    a = lines[-1] if lines else ""
    check("тик: новые [id] старше 30 мин без задачи — одна строка; «не задача» внутри слова владельца, словоформа, "
          "цитата пометки, упоминание только в журнале — пометкой не считаются",
          len(lines) == 1 and all(x in a for x in ("zeus-foo-bar", "zeus-owner-says", "zeus-wordform", "zeus-quoted",
                                                   "zeus-in-journal")), lines)
    check("тик: прежнее, моложе 30 мин, [id] в теле задачи (и dropped), строка «не задача: [id] — причина», id задачи, "
          "не-id — молчит",
          not any(x in a for x in ("zeus-old-one", "zeus-fresh-one", "zeus-with-task", "zeus-not-task", "zeus-bullet-nt",
                                   "zeus-dropped", "metis-0001", "просто-слово")), a)
    zl = os.path.join(state3, "owner-log")
    os.makedirs(zl)
    open(os.path.join(zl, "zeus.md"), "w", encoding="utf-8").write(
        "## 2026-10-24 10:00:00 · окно вопросов\nвопрос: [zeus-from-log] выбрать?\nответ: да\n\n"
        "## 2026-10-24 10:05:00\nпросто текст про [zeus-chat-only]\n")
    run(env3, "check", "--quiet", t=T0 + 120)
    lines = [ln for ln in alerts_of(home3).splitlines() if "без задачи" in ln]
    check("тик: вопрос окна вопросов без задачи — новая строка только о нём (ключ — id, а не набор); реплика с [id] — нет",
          len(lines) == 2 and "zeus-from-log" in lines[-1] and "zeus-foo-bar" not in lines[-1]
          and "zeus-chat-only" not in alerts_of(home3), lines)
    run(env3, "check", "--quiet", t=T0 + 180)
    check("тик: тот же набор — повтор молчит", alerts_of(home3).count("без задачи") == 2, alerts_of(home3))
    run(env3, "check", "--quiet", t=T0 + 3600)
    lines = [ln for ln in alerts_of(home3).splitlines() if "без задачи" in ln]
    check("тик: [id] перешёл порог 30 мин — строка только о нём", len(lines) == 3 and "zeus-fresh-one" in lines[-1]
          and "zeus-foo-bar" not in lines[-1], lines)
    # испорченный файл показанных — как первый проход: запомнить без тревоги; записи старше 8 дней вычищаются
    open(seen_p, "w", encoding="utf-8").write("не json")
    open(dec, "a", encoding="utf-8").write("- 24.10 11:20 — владелец: [zeus-after-break] сделать\n")
    run(env3, "check", "--quiet", t=T0 + 3700)
    check("тик: испорченный unlinked-seen.json — запомнено заново без тревоги",
          alerts_of(home3).count("без задачи") == 3 and "zeus-after-break" in read(seen_p), read(seen_p))
    import json as _json
    sd = _json.loads(read(seen_p))
    sd["zeus-gone-long"] = T0 - 10 * 86400
    open(seen_p, "w", encoding="utf-8").write(_json.dumps(sd))
    run(env3, "check", "--quiet", t=T0 + 3800)
    check("тик: запись показанных старше 8 дней удалена из unlinked-seen.json", "zeus-gone-long" not in read(seen_p)
          and "zeus-foo-bar" in read(seen_p), read(seen_p))
    # слишком старое (>7 дней) разбирает ревизия, а не тик
    open(dec, "a", encoding="utf-8").write("- 10.10 09:00 — старое [zeus-ancient-id]\n")
    run(env3, "check", "--quiet", t=T0 + 3900)
    check("тик: слово старше 7 дней тревоги не даёт", "zeus-ancient-id" not in alerts_of(home3))
    # больше 12 новых за проход (argus b, круг 2): показанными отмечаются только названные, остальные — следующим проходом
    many = [f"zeus-many-{n:02d}" for n in range(15)]
    open(dec, "a", encoding="utf-8").write("".join(f"- 24.10 11:00 — владелец: сделать [{i}]\n" for i in many))
    before = alerts_of(home3).count("без задачи")
    run(env3, "check", "--quiet", t=T0 + 4000)
    first = [ln for ln in alerts_of(home3).splitlines() if "без задачи" in ln][before:]
    check("тик: 15 новых id — первая тревога называет 12 и «и ещё 3», неназванные не отмечены показанными",
          len(first) == 1 and all(i in first[0] for i in many[:12]) and "и ещё 3" in first[0]
          and not any(i in first[0] or i in read(seen_p) for i in many[12:]), (first, read(seen_p)))
    run(env3, "check", "--quiet", t=T0 + 4100)
    run(env3, "check", "--quiet", t=T0 + 4200)
    lines = [ln for ln in alerts_of(home3).splitlines() if "без задачи" in ln][before:]
    check("тик: следующий проход называет оставшиеся 3, третий молчит — каждый из 15 id назван в alerts.md ровно раз",
          len(lines) == 2 and all(sum(i in ln for ln in lines) == 1 for i in many) and "и ещё" not in lines[1], lines)

    # --- края тревоги (metis-0409) ---
    import fcntl
    import time as _time
    # п. 3: decisions.md не прочитался (не «файла нет») — проход пропущен, seen не пишется; следующий читаемый — первый
    tmp4, home4, state4, env4 = make()
    dec4, seen4 = os.path.join(home4, "decisions.md"), os.path.join(state4, "unlinked-seen.json")
    os.makedirs(dec4)  # каталог на месте файла: open → IsADirectoryError
    r = run(env4, "check", "--quiet")
    check("тик: decisions.md не читается — seen не создан, тревоги нет", r.returncode == 0 and not os.path.exists(seen4)
          and "без задачи" not in alerts_of(home4), (r.stderr, os.path.exists(seen4)))
    os.rmdir(dec4)
    open(dec4, "w", encoding="utf-8").write("- 24.10 09:00 — владелец: давнее [zeus-a-one]\n- 24.10 09:01 — владелец: давнее [zeus-a-two]\n")
    run(env4, "check", "--quiet", t=T0 + 60)
    check("тик: после нечитаемого прохода первый читаемый только запоминает — одной строки со всеми id нет",
          "без задачи" not in alerts_of(home4) and "zeus-a-two" in read(seen4), alerts_of(home4))
    # п. 4: id вопроса без дефиса закрывается пометкой «не задача»
    zl4 = os.path.join(state4, "owner-log")
    os.makedirs(zl4)
    open(os.path.join(zl4, "zeus.md"), "w", encoding="utf-8").write(
        "## 2026-10-24 10:00:00 · окно вопросов\nвопрос: [q1abc] выбрать?\n\n"
        "## 2026-10-24 10:01:00 · окно вопросов\nвопрос: [q2abc] выбрать?\n")
    open(dec4, "a", encoding="utf-8").write("не задача: [q1abc] — решено словами\n")
    run(env4, "check", "--quiet", t=T0 + 120)
    last = [ln for ln in alerts_of(home4).splitlines() if "без задачи" in ln]
    check("тик: id без дефиса — пометка «не задача: [q1abc] — причина» его закрывает, q2abc без пометки тревожит",
          len(last) == 1 and "q2abc" in last[0] and "q1abc" not in last[0], last)
    # п. 6а: тревога и запись seen — под замком; пока замок занят, тик ждёт
    open(dec4, "a", encoding="utf-8").write("- 24.10 09:30 — владелец: ещё [zeus-b-race]\n")
    os.makedirs(os.path.join(state4, "locks"), exist_ok=True)
    held = open(os.path.join(state4, "locks", "unlinked.lock"), "a")
    fcntl.flock(held, fcntl.LOCK_EX)
    proc = subprocess.Popen([PY311, "-I", RUN_PY, "check", "--quiet"], env=dict(env4, PANTHEON_NOW=str(T0 + 180)),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _time.sleep(4)
    waiting = proc.poll() is None and "zeus-b-race" not in alerts_of(home4)
    fcntl.flock(held, fcntl.LOCK_UN)
    held.close()
    proc.communicate(timeout=120)
    check("тик: пока замок unlinked занят другим проходом, тревога не пишется и проход ждёт; после — ровно одна строка",
          waiting and alerts_of(home4).count("zeus-b-race") == 1, (waiting, alerts_of(home4)))
    # п. 6б: seen не записывается — тревоги нет (не каждый проход)
    open(dec4, "a", encoding="utf-8").write("- 24.10 09:31 — владелец: ещё [zeus-c-nowrite]\n")
    n0 = alerts_of(home4).count("без задачи")
    os.chmod(state4, 0o500)
    try:
        r1 = run(env4, "check", "--quiet", t=T0 + 240)
        r2 = run(env4, "check", "--quiet", t=T0 + 300)
    finally:
        os.chmod(state4, 0o700)
    check("тик: seen не записан — тревоги «без задачи» нет ни в первый, ни во второй проход, причина в stderr",
          alerts_of(home4).count("без задачи") == n0 and "unlinked-seen.json не записан" in r1.stderr + r2.stderr
          and "zeus-c-nowrite" not in read(seen4), (r1.stderr[-300:], r2.stderr[-300:]))
    run(env4, "check", "--quiet", t=T0 + 360)
    check("тик: запись снова возможна — тревога о нём один раз", alerts_of(home4).count("zeus-c-nowrite") == 1,
          alerts_of(home4))
    # b2 3: сухой прогон без ALERTS_IN_DRYRUN печатает тревогу, но id не прячет от настоящего прохода
    open(dec4, "a", encoding="utf-8").write("- 24.10 09:32 — владелец: ещё [zeus-d-dry]\n")
    dry_env = {k: v for k, v in env4.items() if k != "PANTHEON_ALERTS_IN_DRYRUN"}
    r = run(dry_env, "check", "--quiet", t=T0 + 420)
    check("тик, сухой прогон: тревога только напечатана, в seen id не записан",
          "zeus-d-dry" in r.stdout and "zeus-d-dry" not in read(seen4) and "zeus-d-dry" not in alerts_of(home4),
          (r.stdout[-300:], read(seen4)))
    run(env4, "check", "--quiet", t=T0 + 480)
    check("тик: настоящий проход после сухого называет этот id", alerts_of(home4).count("zeus-d-dry") == 1, alerts_of(home4))
    # b2 1: пустые --option не варианты
    tmp5, home5, state5, env5 = make()
    r = run(env5, "task", "new", "--direction", "metis-pantheon", "--title", "В", "--question", "Что?", "--why", "потому",
            "--option", "", "--option", "")
    check("task new: вопрос без текста с двумя пустыми --option — отказ 2, файл не создан",
          r.returncode == 2 and "--option" in r.stderr and tasks_of(home5) == [], (r.returncode, r.stderr))
    check("is_full_question: пустые варианты не считаются",
          not T.is_full_question({"question": "?", "why": "w", "options": ["", " "]})
          and T.is_full_question({"question": "?", "why": "w", "options": ["А", "Б", ""]}))
    # п. 7: вопрос с текстом, но без --why или вариантов — предупреждение, не отказ
    r = new(env5, "--body", "Цель и готово", "--question", "Что?")
    r2 = new(env5, "--body", "Цель и готово", "--question", "Что?", "--why", "потому", "--option", "А — да", "--option", "Б — нет")
    check("task new: вопрос с текстом без --why/вариантов — код 0 и предупреждение; полный вопрос — без него",
          r.returncode == 0 and "вопрос владельцу без --why" in r.stderr and r2.returncode == 0
          and "вопрос владельцу без --why" not in r2.stderr, (r.stderr, r2.stderr))
    # b2 2: пустой --body в task set — отказ
    tp5 = os.path.join(home5, "directions", "metis-pantheon", "tasks", "metis-0001.md")
    before = read(tp5)
    r = run(env5, "task", "set", "metis-0001", "--body", "   ")
    open(os.path.join(tmp5, "empty.txt"), "w").write("\n")
    r2 = run(env5, "task", "set", "metis-0001", "--body-file", os.path.join(tmp5, "empty.txt"))
    check("task set: пустой --body и пустой --body-file — отказ 2, задача не изменена",
          r.returncode == 2 and r2.returncode == 2 and "пусты" in r.stderr and read(tp5) == before,
          (r.returncode, r2.returncode, r.stderr))

    # metis-0714, вариант А (argus-280b): цель окна отпускает «ждёт» только владельца с вопросом или другую задачу.
    # Сессия, поставившая «ждёт» с блокером, выдуманным ею самой, получает «остаётся в цели окна» — и WAITING_GOAL
    # (lib/sessions.py) велит проверяющей модели верить только строке «снята с цели окна».
    def wait_set(tid, *fields):
        r = run(env5, "task", "set", tid, "status=waiting", "next=ждать", *fields)
        return r.returncode, r.stdout
    ids = [new(env5, "--body", "Цель и готово").stdout.split()[0] for _ in range(6)]
    cases = [(ids[0], ("waiting_on=human", "question=Какой вариант?", "why=нужно решение"), True),
             (ids[1], ("waiting_on=metis-0001",), True),
             (ids[2], ("waiting_on=agent",), False),
             (ids[3], ("waiting_on=human",), False),
             (ids[4], (f"waiting_on={ids[4]}",), False)]
    # пробы argus-280c: блокер, которого нет или который задачу уже не держит, цель не отпускает
    more = [new(env5, "--body", "Цель и готово").stdout.split()[0] for _ in range(9)]
    drop, chain_hq, chain_ok = more[6], more[7], more[8]
    run(env5, "task", "set", drop, "status=dropped")
    wait_set(chain_hq, "waiting_on=human")  # «ждёт» без вопроса — сама в цели
    wait_set(chain_ok, "waiting_on=human", "question=Какой вариант?", "why=нужно решение")
    c1, c2 = more[4], more[5]
    wait_set(c2, f"waiting_on={c1}")  # c1 ещё не ждёт — c2 снята; c1 на c2 замыкает цикл
    cases += [(more[0], ("waiting_on=metis-9999",), False),
              (more[1], (f"waiting_on={drop}",), False),
              (more[2], ("waiting_on=athena-0042",), False),
              (more[3], ("waiting_on=metis-0001 и ревью",), False),
              (c1, (f"waiting_on={c2}",), False),
              (ids[5], (f"waiting_on={chain_hq}",), False)]
    got = {tid: wait_set(tid, *f) for tid, f, _ in cases}
    chain = wait_set(new(env5, "--body", "Цель и готово").stdout.split()[0], f"waiting_on={chain_ok}")
    check("task set waiting: блокер ждёт владельца с вопросом — цепочка отпускает, «снята с цели окна»",
          chain[0] == 0 and T.GOAL_OUT in chain[1] and T.GOAL_IN not in chain[1], chain)
    check("task set waiting: human+question и id другой задачи — «снята с цели окна»; agent, human без вопроса, "
          "своя же задача, metis-9999, athena-0042, dropped-блокер, «metis-0001 и ревью», цикл c1↔c2, блокер в «ждёт» "
          "без основания — «остаётся в цели окна»",
          all(got[tid][0] == 0 and (f"{tid}: {T.GOAL_OUT}" in got[tid][1]) == out
              and (f"{tid}: {T.GOAL_IN}" in got[tid][1]) == (not out) for tid, _, out in cases), got)
    # argus-280b (Б): A ждёт B — «снята»; потом B закрыли или B сам ждёт без основания — `task set B` печатает GOAL_IN
    # про A (и про ждущих A по цепочке), иначе последней строкой о A остаётся «снята» и A навсегда вне цели
    fresh = lambda: new(env5, "--body", "Цель и готово").stdout.split()[0]
    # цикл c1↔c2 уже в хранилище: обход цепочки ждущих при смене статуса чужой задачи не виснет (без `seen` — вечный
    # цикл). Короткий предел и выход — иначе каждый следующий task set ждал бы по 300 с
    try:
        loop = subprocess.run([PY311, "-I", RUN_PY, "task", "set", fresh(), "status=doing"], capture_output=True,
                              text=True, timeout=60, env=dict(env5, PANTHEON_NOW=str(T0)))
    except subprocess.TimeoutExpired:
        loop = None
    check("task set при цикле ожиданий c1↔c2 в хранилище — заканчивается, код 0", loop and loop.returncode == 0,
          loop and loop.stderr)
    if loop is None:
        print(f"\n{sum(results)}/{len(results)} — дальше task set повиснет так же, прогон остановлен")
        sys.exit(1)
    a1, b1, c3, a2, b2, a3, b3 = (fresh() for _ in range(7))
    first = [wait_set(a1, f"waiting_on={b1}"), wait_set(c3, f"waiting_on={a1}"),
             wait_set(a2, f"waiting_on={b2}"), wait_set(a3, f"waiting_on={b3}")]
    drop_b = run(env5, "task", "set", b1, "status=dropped")
    wait_b = wait_set(b2, "waiting_on=agent")
    doing_b = run(env5, "task", "set", b3, "status=doing")
    check("task set: блокер стал dropped или «ждёт» без основания — «<A>: остаётся в цели окна — блокер <B> <статус>» "
          "про каждую ждущую его задачу и по цепочке; блокер doing — строки нет",
          all(f[0] == 0 and T.GOAL_OUT in f[1] for f in first)
          and drop_b.returncode == 0 and f"{a1}: {T.GOAL_IN} — блокер {b1} dropped" in drop_b.stdout
          and f"{c3}: {T.GOAL_IN} — блокер {a1} waiting, цепочка до {b1}" in drop_b.stdout
          and f"{a2}: {T.GOAL_IN} — блокер {b2} waiting" in wait_b[1]
          and doing_b.returncode == 0 and a3 not in doing_b.stdout and T.GOAL_IN not in doing_b.stdout,
          (first, drop_b.stdout, wait_b, doing_b.stdout))
    r = run(env5, "task", "set", new(env5, "--body", "Цель и готово").stdout.split()[0], "status=doing")
    check("task set doing — ни строки «снята», ни «остаётся» (doing в цели и так)",
          r.returncode == 0 and T.GOAL_OUT not in r.stdout and T.GOAL_IN not in r.stdout, r.stdout)
    rel = T.goal_released
    check("goal_released без хранилища: doing, todo, waiting agent, waiting id — в цели; waiting human+question — нет",
          not rel({"status": "doing", "waiting_on": "human", "question": "?"}) and not rel({"status": "todo"})
          and not rel({"status": "waiting", "waiting_on": "agent", "question": "?"})
          and not rel({"status": "waiting", "waiting_on": "human", "question": "  "}) and not rel(None)
          and rel({"status": "waiting", "waiting_on": "human", "question": "Что?"})
          and not rel({"status": "waiting", "waiting_on": "athena-0042", "id": "metis-0001"}))
    def st(i, status, on=None, q=None):
        return (f"/{i}.md", {"id": i, "status": status, "waiting_on": on, "question": q}, "")
    store = {"ab-001": st("ab-001", "doing"), "ab-002": st("ab-002", "done"), "ab-003": st("ab-003", "dropped"),
             "ab-004": st("ab-004", "waiting", "ab-005"), "ab-005": st("ab-005", "waiting", "ab-004"),
             "ab-006": st("ab-006", "waiting", "agent"), "ab-007": st("ab-007", "waiting", "human", "Что?"),
             "ab-008": st("ab-008", "waiting", "ab-007"), "ab-009": st("ab-009", "inbox"),
             "ab-010": st("ab-010", "waiting", "ab-010"), "ab-011": ("/ab-011.md", {}, "")}
    w = lambda on: {"id": "mb-001", "status": "waiting", "waiting_on": on}
    check("goal_released с хранилищем: блокер есть и не done/dropped — снята; нет, done, dropped, цикл, блокер "
          "ждёт без основания, своя петля, без хранилища — в цели; цепочка до вопроса владельцу — снята",
          rel(w("ab-001"), store) and rel(w("ab-009"), store) and rel(w("ab-008"), store) and rel(w("ab-007"), store)
          and not rel(w("ab-002"), store) and not rel(w("ab-003"), store) and not rel(w("ab-004"), store)
          and not rel(w("ab-006"), store) and not rel(w("ab-010"), store) and not rel(w("ab-011"), store)
          and not rel(w("metis-9999"), store)
          and not rel(w("ab-001")) and not rel(w("ab-001 и ревью"), store)
          and not rel(store["ab-004"][1], store) and not rel({"id": "ab-004", "status": "waiting", "waiting_on": "ab-004"},
                                                                store))
    dep = T.goal_held_dependents
    check("goal_held_dependents: ждущая в цикле — в списке с блокером и его статусом; снятая (цепочка до вопроса "
          "владельцу) и ждущие не через tid — нет; цикл в стороне обход не вешает",
          dep("ab-005", store) == [("ab-004", "ab-005", "waiting")] and dep("ab-007", store) == []
          and dep("ab-002", store) == [] and dep("ab-001", store) == [] and dep("ab-001", None) == [],
          (dep("ab-005", store), dep("ab-007", store)))

    # чистые функции
    desc = T.has_description
    check("has_description: заголовок и журнал — нет; текст — да; чужой раздел — да",
          not desc("\n# A\n\n## Журнал\n\n- x — агент: создана\n") and desc("\n# A\n\nтекст\n\n## Журнал\n")
          and desc("\n# A\n\n## Журнал\n\n- x\n\n## Заметки владельца\n\nа\n"))
    check("has_description: раздел «Готово, когда» с подсказкой описанием не считается (metis-0502)",
          not desc("\n# A\n\n## Готово, когда\n\n- [ ] (впишите)\n\n## Журнал\n\n- x — агент: создана\n")
          and desc("\n# A\n\nтекст\n\n## Готово, когда\n\n- [ ] а\n\n## Журнал\n"))

    print(f"\n{sum(results)}/{len(results)}")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
