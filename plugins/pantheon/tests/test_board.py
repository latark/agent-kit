#!/usr/bin/env python3
"""Задачи и доска владельца на временных папках: схема v1, pantheon task, ходы владельца, конфликты, ответы,
входящие, авторазблокировка, просрочка, копия не трогает Доску.

Запуск: python3 -I plugins/pantheon/tests/test_board.py  (код выхода 0 — все прошли)
"""
import json
import os
import re
import subprocess
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
CLI = os.path.join(LIB, "pantheon.py")
T0 = 1_792_000_000  # 2026-10-15
results = []


def check(name, ok):
    results.append(bool(ok))
    print(("ok  " if ok else "FAIL") + " " + name)


def make():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="board-test-"))
    home, state, view = (os.path.join(tmp, x) for x in ("pantheon", "state", "view"))
    for d in ("directions/metis-pantheon/tasks", "directions/athena-broker/tasks", "inbox/tasks"):
        os.makedirs(os.path.join(home, d))
    os.makedirs(view)
    open(os.path.join(home, "schedule.toml"), "w").write('primary_host = "mac-a"\n')
    env = {"PATH": os.environ["PATH"], "HOME": tmp, "PANTHEON_HOME": home, "PANTHEON_STATE": state,
           "PANTHEON_VIEW": view, "PANTHEON_HOST": "mac-a", "PANTHEON_DRYRUN": "1", "PANTHEON_NO_NOTIFY": "1"}
    return tmp, home, state, view, env


def run(env, *args, t=T0):
    e = dict(env, PANTHEON_NOW=str(t))
    return subprocess.run([sys.executable, "-I", CLI, *args], env=e, capture_output=True, text=True, timeout=60)


def head_of(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    pairs = (l.split(": ", 1) for l in m.group(1).split("\n"))
    return {k: json.loads(v) if v.startswith('"') else v for k, v in pairs}, text


def card(view, title):
    return os.path.join(view, "Доска", title + ".md")


def set_card(path, key, value):
    text = open(path, encoding="utf-8").read()
    text = re.sub(rf"^{key}: .*$", f"{key}: {value}", text, count=1, flags=re.M) if re.search(rf"^{key}: ", text, re.M) \
        else text.replace("\n---\n", f"\n{key}: {value}\n---\n", 1)
    open(path, "w", encoding="utf-8").write(text)


def main():
    tmp, home, state, view, env = make()
    src = lambda d, i: os.path.join(home, "directions", d, "tasks", i + ".md")

    # схема и pantheon task
    r = run(env, "task", "new", "--direction", "metis-pantheon", "--title", "Схема свойств", "--priority", "1",
            "--next", "написать schema.md", "--owner", "metis-pantheon", "--project", "Пантеон")
    check("task new: id по образцу и файл в tasks/", r.returncode == 0 and r.stdout.startswith("metis-0001 "))
    h, _ = head_of(src("metis-pantheon", "metis-0001"))
    check("task new: шапка по схеме v1", h["type"] == "task" and h["status"] == "todo" and h["schema_version"] == "1")
    r = run(env, "task", "set", "metis-0001", "status=waiting")
    check("task set: waiting без waiting_on — отказ", r.returncode == 1 and "waiting_on" in r.stderr)
    run(env, "task", "new", "--direction", "metis-pantheon", "--title", "Вопрос владельцу", "--status", "waiting",
        "--waiting-on", "human", "--next", "ждём ответ", "--question", "Где держать доску?", "--option", "В копии",
        "--option", "В knowledge", "--project", "Пантеон")
    run(env, "task", "new", "--direction", "athena-broker", "--title", "Налоги беты", "--due", "2026-10-10",
        "--project", "BrokerAssistant")
    run(env, "task", "new", "--direction", "metis-pantheon", "--title", "Ждёт схему", "--status", "waiting",
        "--waiting-on", "metis-0001", "--next", "после схемы", "--project", "Пантеон")
    r = run(env, "check")
    check("check: 4 задачи без ошибок", r.returncode == 0 and "задач: 4, с ошибками: 0" in r.stdout)
    open(src("athena-broker", "athena-0099"), "w").write("---\ntype: task\nid: athena-0099\nstatus: wip\n---\n")
    r = run(env, "check")
    check("check: битая шапка — ошибка с причиной", r.returncode == 1 and "athena-0099" in r.stdout and "wip" in r.stdout)
    os.remove(src("athena-broker", "athena-0099"))

    # доска: карточки
    r = run(env, "board")
    c1, c2 = card(view, "Схема свойств"), card(view, "Вопрос владельцу")
    ch1, _ = head_of(c1)
    check("board: карточка с русскими полями, колонка «Очередь»", ch1.get("Статус") == "Очередь"
          and ch1.get("Приоритет") == "🔥 высокий" and "type" not in ch1 and ch1.get("id") == "metis-0001")
    _, t2 = head_of(c2)
    check("board: вопрос с вариантами — галочки в карточке", "Статус: Ждёт вас" in t2 and "- [ ] В копии" in t2)
    check("board: Доска.base и Сводка", os.path.exists(os.path.join(view, "Доска", "Доска.base"))
          and "Ждёт вас (1)" in open(os.path.join(view, "Доска", "Сводка.md"), encoding="utf-8").read())
    check("board: просрочка — одна тревога", "просрочена: Налоги беты" in r.stdout)
    r = run(env, "board", t=T0 + 60)
    check("board: повтор — без второй тревоги и без перерисовки", "просрочена" not in r.stdout)

    # ход владельца
    set_card(c1, "Статус", "В работе")
    r = run(env, "board", t=T0 + 120)
    h, text = head_of(src("metis-pantheon", "metis-0001"))
    log = [json.loads(x) for x in open(os.path.join(state, "owner-log", "board.jsonl"))]
    check("ход: «Очередь» → «В работе» применён к задаче", h["status"] == "doing" and "ход владельца" in text)
    check("ход: в журнале владельца и «Сделать сейчас» будит агента",
          log[-1]["kind"] == "move" and log[-1]["dst"] == "В работе" and "Сделать сейчас" in r.stdout)
    # запрещённая колонка
    set_card(c1, "Статус", "На проверке")
    run(env, "board", t=T0 + 180)
    h, _ = head_of(src("metis-pantheon", "metis-0001"))
    _, ct = head_of(c1)
    check("ход в «На проверке» — не применён, карточка вернулась с пояснением",
          h["status"] == "doing" and "Статус: В работе" in ct and "переносит агент" in ct)
    # конфликт: агент изменил задачу, пока владелец двигал карточку
    set_card(c1, "Статус", "Готово")
    run(env, "task", "set", "metis-0001", "next=почти готово", t=T0 + 200)
    run(env, "board", t=T0 + 240)
    h, _ = head_of(src("metis-pantheon", "metis-0001"))
    _, ct = head_of(c1)
    check("конфликт: ход не применён, предупреждение в карточке", h["status"] == "doing" and "агент изменил задачу" in ct)
    set_card(c1, "Статус", "Готово")
    run(env, "board", t=T0 + 300)
    h, _ = head_of(src("metis-pantheon", "metis-0001"))
    _, ct = head_of(c1)
    check("повторный ход после конфликта — применён, предупреждение снято", h["status"] == "done" and "агент изменил" not in ct)
    # авторазблокировка
    h3, _ = head_of(src("metis-pantheon", "metis-0003"))
    check("авторазблокировка: ждала metis-0001 — теперь в очереди", h3["status"] == "todo")

    # заметка агенту и ответ галочкой
    set_card(c2, "Заметка агенту", "Сделайте как проще")
    t2 = open(c2, encoding="utf-8").read().replace("- [ ] В копии", "- [x] В копии")
    open(c2, "w", encoding="utf-8").write(t2)
    run(env, "board", t=T0 + 360)
    h, text = head_of(src("metis-pantheon", "metis-0002"))
    _, ct = head_of(c2)
    check("ответ галочкой: answer и задача в очередь", h.get("answer") == "В копии" and h["status"] == "todo")
    check("заметка агенту: в журнале задачи, в карточке очищена",
          "от владельца: Сделайте как проще" in text and 'Заметка агенту: ""' in ct)

    # новая карточка во «Входящих»
    open(os.path.join(view, "Доска", "Купить домен для лендинга.md"), "w", encoding="utf-8").write(
        "---\nСтатус: Входящие\n---\nдо пятницы\n")
    run(env, "board", t=T0 + 420)
    inbox = os.listdir(os.path.join(home, "inbox", "tasks"))
    hi, ti = head_of(os.path.join(home, "inbox", "tasks", inbox[0])) if inbox else ({}, "")
    _, cn = head_of(card(view, "Купить домен для лендинга"))
    check("входящие: задача для Зевса создана, карточка стала обычной",
          hi.get("status") == "inbox" and hi.get("owner") == "zeus" and "до пятницы" in ti and "id: " in cn)

    # pantheon task ready / claim
    r = run(env, "task", "ready", "--direction", "metis-pantheon", t=T0 + 480)
    check("ready: готовые задачи направления", "metis-0002" in r.stdout and "metis-0001" not in r.stdout)
    r1 = run(env, "task", "claim", "metis-0002", "--by", "hephaestus", t=T0 + 500)
    r2 = run(env, "task", "claim", "metis-0002", "--by", "dev-sonnet", t=T0 + 520)
    check("claim: второй агент не берёт чужую аренду", r1.returncode == 0 and r2.returncode == 1)

    # копия не трогает Доску
    src_dir, dst = os.path.join(tmp, "src"), os.path.join(tmp, "dst")
    os.makedirs(os.path.join(src_dir, "x"))
    open(os.path.join(src_dir, "board.md"), "w").write("доска\n")
    os.makedirs(os.path.join(dst, "Доска"))
    open(os.path.join(dst, "Доска", "Карточка.md"), "w").write("---\nСтатус: Очередь\n---\n")
    subprocess.run(["/bin/zsh", os.path.join(LIB, "view-sync.sh"), src_dir, dst, os.path.join(tmp, "inbox-view")],
                   capture_output=True, timeout=30)
    kept = os.path.exists(os.path.join(dst, "Доска", "Карточка.md"))
    writable = os.access(os.path.join(dst, "Доска", "Карточка.md"), os.W_OK)
    ro = not os.access(os.path.join(dst, "board.md"), os.W_OK)
    check("копия: Доска цела и записываема, остальное — только чтение", kept and writable and ro)

    print(f"\n{sum(results)} из {len(results)} прошли")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
